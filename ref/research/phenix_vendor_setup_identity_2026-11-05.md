# PHENIX Configured-Install Vendor Setup Build Identity (#954, #955, #956, #958, #959, #960, #961, #962, #409) — 2026-11-05

## Problem statement and root cause (#954)

In the checked PHENIX `2.0-5936` installation (observed identically on both the original M1 installation and the M5 copy), the command-line dispatcher `<prefix>/phenix_bin/phenix.version` resolves to `<prefix>/bin/phenix.version` and runs `<prefix>/lib/python3.9/site-packages/phenix/command_line/version.py` (`phenix_info.show_banner()`). In `phenix_info.py`, banner version discovery reads `PHENIX_VERSION` and `PHENIX_RELEASE_TAG` from the process environment, and includes a fallback to `../TAG` relative to the `libtbx` distribution when those environment variables are absent.

Read-only inspection of the checked `2.0-5936` installation prefix confirmed:

1. Although `phenix_info.py` implements the `../TAG` fallback, no `TAG` or `cctbx_bundle_TAG` file is present anywhere in the checked `2.0-5936` `<prefix>` or in any of its 284 installed conda package manifests (`conda-meta/*.json`).
2. `<prefix>/bin/phenix.version` does not source `<prefix>/phenix_env.sh`.
3. `<prefix>/phenix_env.sh` is the vendor-shipped setup script in `<prefix>` that exports `PHENIX_VERSION=2.0-5936`.
4. Because `scripts/toolchain.py` strips inherited `PHENIX_VERSION` and `PHENIX_RELEASE_TAG` from the parent environment to prevent cross-installation spoofing (#816), invoking `phenix.version` directly on the checked `2.0-5936` installation without sourcing its own `phenix_env.sh` exits `0` with only the title and `User:` lines:

```text
-------------------------------------------------------------------------------
  Phenix: Python-based Hierarchical ENvironment for Integrated Xtallography
  User: <username>
-------------------------------------------------------------------------------
```

Without `Version:` or `Release tag:` lines, `parse_phenix_build()` returns `None` and `refinement_cache._build_is_measured()` rejects the build as unmeasured (`reusable: False`), preventing authenticated refinement-cache reuse (#777, #818).

## Implemented trust contract (Option 2: isolated configured-install setup adapter)

`scripts/toolchain.py` and `scripts/refinement_cache.py` implement an audited, version-only vendor setup adapter for PHENIX build discovery while preserving #816 inherited-variable isolation and fail-closed cache admission:

1. **Strict prefix, setup, and dispatcher containment (#954, #958, #960, #409):**
   - The installation prefix is derived strictly from the configured binary directory (`PHENIX_BIN` or explicit `configured_bin`): if its lexical name is `phenix_bin` or `bin`, the prefix is its parent directory; otherwise the prefix is the directory itself.
   - Neither `configured_bin` nor `configured_prefix` may be a symlink, and path resolution converts Python 3.12 `Path.resolve()` `RuntimeError` symlink-loop exceptions into `ValueError` at the path boundary (#960) so symlink loops return diagnostic unknown evidence without raising uncaught exceptions.
   - Every directory component and terminal symlink hop of `<configured_bin>/phenix.version` is walked step-by-step via `_resolve_within_prefix` using `os.lstat` and `os.readlink` (#958), rejecting any intermediate directory symlink or terminal symlink hop that escapes the installation prefix even if a subsequent symlink returns inside the prefix.
   - `<prefix>/phenix_env.sh` must be a regular non-symlink file directly under `<prefix>`, and `<prefix>/bin/phenix.version` must be a regular file inside `<prefix>`. In `external_tool_report()`, PHENIX executable availability additionally requires `os.access(discovered, os.X_OK)` (with no `PATH` fallback), kept separate from version-identity verification (#409).
   - No new environment variable or per-runner setup path constant is introduced.

2. **Sanitized child environment and shell-hook neutralization (#816, #956):**
   - `phenix_version_environment()` copies `os.environ` without mutating the parent environment, removes `PHENIX_VERSION` and `PHENIX_RELEASE_TAG` (recorded in `ignored_inherited_version_variables`), and removes shell startup/execution hooks (`BASH_ENV`, `ENV`, `SHELLOPTS`, `BASHOPTS`, `POSIXLY_CORRECT`, `CDPATH`, `GLOBIGNORE`, `PROMPT_COMMAND`, `PS4`), all `BASH_FUNC_*` variables, and any legacy exported shell function whose value starts with `"() {"` (recorded in `ignored_inherited_shell_hooks`).
   - Version-variable classification (`PHENIX_VERSION`, `PHENIX_RELEASE_TAG`) takes precedence over `_is_shell_hook_variable`, so function-shaped `PHENIX_VERSION='() { ... }'` or `PHENIX_RELEASE_TAG='() { ... }'` values are removed and recorded only in `ignored_inherited_version_variables` without overlapping `ignored_inherited_shell_hooks` (#956).
   - The setup probe invokes `/bin/bash --noprofile --norc -c <_PHENIX_SETUP_SCRIPT> protstruct-phenix-setup <resolved_setup_path>` with positional argument `$1` (`builtin . "$1"`), never interpolating file paths into shell text, and first unsets shell builtins/functions (`export`, `unset`, `printf`, `.`, `exit`) and `PHENIX_VERSION`, `PHENIX_RELEASE_TAG`, `BASH_ENV`, and `ENV`.

3. **Deliberate version-only field transfer, independent normalization, and single-banner rule (#954, #959, #961, #962):**
   - The setup probe sources `<prefix>/phenix_env.sh` in the isolated child shell, separates any setup stdout/stderr chatter from the NUL-delimited final `PHENIX_VERSION` / `PHENIX_RELEASE_TAG` record, and requires zero exit status and empty `setup_stdout` / `setup_stderr`.
   - `parse_phenix_setup_build()` normalizes the final setup-exported `PHENIX_VERSION` / `PHENIX_RELEASE_TAG` fields independently of the banner parser, rejecting missing, malformed, or contradictory final fields (#959).
   - **Version-only transfer:** Only the two setup-derived version variables (`PHENIX_VERSION` and `PHENIX_RELEASE_TAG`) are overlaid onto the sanitized `base_env` when invoking `<prefix>/bin/phenix.version` (`shell=False`). The adapter deliberately does **not** transfer the complete sourced setup environment (such as `PATH`, `PHENIX`, or library variables) to `phenix.version` or to scientific runners.
   - `parse_phenix_build()` accepts **one** consistent `Version:` / `Release tag:` pair within a single PHENIX banner header (as explicitly confirmed by the user) and rejects multiple PHENIX banner headers, duplicate `Version:` or `Release tag:` lines, contradictory single-line and split-line values, or fragments split across banners or stdout/stderr.
   - If either the setup child or the dispatcher child (in vendor or bare mode) raises `subprocess.TimeoutExpired`, partial `stdout` and `stderr` (`str` or `bytes`) are preserved in `setup_stdout`/`setup_stderr` or `stdout`/`stderr` with `None` return code and unknown admission (#961).
   - Configured setup and dispatcher targets are re-resolved and their regular-file SHA-256 content digests (`setup_sha256`, `sha256`) are compared before and after execution; an observed mismatch between the before and after observations leaves the build unknown (`reported_version=None`, `reported_version_source=None`), without claiming to detect transient changes that revert between observations or checking executable-permission stability in `phenix_build_evidence()` (#962).

4. **Explicit bare probe retained:**
   - `phenix_bare_build_evidence()` (or `phenix_build_evidence(..., use_vendor_setup=False)`) preserves direct `phenix.version` probing with `reported_version_source="command_output"`.
   - Default `phenix_build_evidence()` never falls back to accepting bare output or path-derived version hints when `phenix_env.sh` is missing or invalid.

5. **Structural and semantic cache-gate verification (`scripts/refinement_cache.py`):**
   - `_build_is_measured()` validates all required `vendor_setup_environment` bindings: non-empty `parsed_build`, exact `reported_version` banner match, `configured_prefix` / `resolved_prefix` / `setup_configured_path` / `setup_resolved_path` / `configured_path` / `resolved_path` containment within the installation prefix, 64-hex `sha256` and `setup_sha256`, exact `argv == [resolved_path]` and `setup_argv == phenix_setup_argv(setup_resolved_path)`, `int` zero `returncode` and `setup_returncode`, empty `setup_stdout` and `setup_stderr`, no banner fragments in `stderr`, valid `setup_version_fields`, equality of `parse_phenix_setup_build(setup_version_fields) == parse_phenix_build(stdout) == setup_parsed_build == parsed_build`, and well-formed `ignored_inherited_version_variables` and `ignored_inherited_shell_hooks`.
   - Because `version_probe` (including `setup_configured_path`, `setup_resolved_path`, `setup_sha256`, `setup_argv`, `setup_returncode`, `setup_stdout`, `setup_stderr`, and `setup_version_fields`) is embedded in `measured_build` inside `refinement_cache_v1` `key_material`, changing either `phenix_env.sh` or `phenix.version` bytes produces a distinct cache key and invalidates stale reuse.

## PRIMARY acceptance and fresh-review triage (#955, #956, #958, #959, #960, #961, #962, #409)

1. **#955 (`scripts/test_benchmark_environment.py` hermetic isolation):**
   - Isolated default-route metadata/announcement assertions in `scripts/test_benchmark_environment.py` using deterministic synthetic tool reports, preserved an explicit assertion that omitting `external_tools` dispatches through `external_tool_report()` (`call_count == 2`), and added a `toolchain.subprocess.run` tripwire proving the unit suite cannot spawn external tool subprocesses.

2. **#956 (legacy exported shell function names and function-shaped `PHENIX_VERSION` / `PHENIX_RELEASE_TAG`):**
   - Aligned `refinement_cache._valid_ignored_hooks()` with `toolchain._is_shell_hook_variable()` so arbitrary legacy exported function names (`LEGACY_FUNC='() { :; }'`) are accepted in `ignored_inherited_shell_hooks`, and gave `_PHENIX_VERSION_VARIABLES` precedence over `_is_shell_hook_variable()` so function-shaped `PHENIX_VERSION` or `PHENIX_RELEASE_TAG` values are recorded only in `ignored_inherited_version_variables` without hook-list overlap.

3. **#958 (intermediate directory symlink escape returning inside prefix):**
   - Replaced whole-parent `next_path.parent.resolve(strict=True)` in `_resolve_phenix_dispatcher()` with component-by-component `_resolve_within_prefix()` walking every directory and terminal symlink hop via `os.lstat` and `os.readlink`, rejecting `prefix/escape -> outside` + `outside/return -> prefix/bin` before setup or dispatcher execution.

4. **#959 (remove static regex assignment count on `phenix_env.sh` source text):**
   - Removed `_setup_script_has_duplicate_version_fields()`, which falsely rejected inline comments containing `PHENIX_VERSION=...` and missed quoted exports. The contract is enforced on the final captured `setup_version_fields` and single-banner agreement.

5. **#960 (path-resolution symlink loops on Python 3.12):**
   - Added `_strict_resolve()` at the path-resolution boundary to convert Python 3.12 `Path.resolve()` `RuntimeError("Symlink loop from ...")` into `ValueError`, returning diagnostic unknown evidence on both vendor and bare routes without executing setup or dispatcher.

6. **#961 (`TimeoutExpired` partial `stdout` / `stderr` retention):**
   - Preserved partial `stdout` and `stderr` (`str` or `bytes`) from `subprocess.TimeoutExpired` in `setup_stdout`/`setup_stderr` (for setup timeouts) and `stdout`/`stderr` (for vendor and bare dispatcher timeouts) with `None` return code and unknown admission.

7. **#409 regression (`external_tool_report` executable availability for mode-`0644` `phenix.version`):**
   - Required `os.access(discovered, os.X_OK)` in `external_tool_report()` (separate from version identity verification and with no `PATH` fallback), so a non-executable (`0644`) or absent `phenix.version` reports `available=False`, `discovered_executable=None`, `version_divergence=None`, while preserving `available=True`, `reported_version=None`, `version_divergence=True` when `phenix.version` is executable (`0755`) but `phenix_env.sh` is missing.

8. **#962 (audit accuracy on before/after target and digest comparison vs executable availability):**
   - Corrected line 45 of this audit record so it states what `phenix_build_evidence()` actually verifies after successful execution: configured targets are re-resolved (`_resolve_phenix_dispatcher`, `_resolve_phenix_setup`) and setup/dispatcher regular-file SHA-256 digests (`setup_sha256`, `sha256`) are compared at the before and after observation points, with an observed mismatch leaving the build unknown. Removed the overstated claim that `phenix_build_evidence()` checks executable-permission stability before/after or detects every transient mid-probe change; executable permission (`os.access(discovered, os.X_OK)`) remains the separate `external_tool_report()` availability check (#409).

## Explicit scope limits

- **Not a whole-installation or library hash:** `setup_sha256` and `sha256` authenticate `<prefix>/phenix_env.sh` and `<prefix>/bin/phenix.version`, not every Python module or shared library imported by PHENIX. Unversioned in-place library edits still require a fresh cache directory.
- **Version-only field transfer:** Sourcing `<prefix>/phenix_env.sh` in `phenix_build_evidence()` applies only to the version-discovery probe in `scripts/toolchain.py` (CODING_STANDARDS rule 19b) and transfers only `PHENIX_VERSION` and `PHENIX_RELEASE_TAG` to `phenix.version`. It does not transfer full `phenix_env.sh` environment mutations (`PATH`, `PHENIX`, library paths) to `phenix.version` or to scientific PHENIX refinement runners (`phenix.refine`, `phenix.real_space_refine`, `phenix.model_vs_data`, `phenix.mtriage`).
- **No scientific re-measurement or live installation mutation:** This change does not modify any installed PHENIX files, does not run scientific benchmarks, and does not retroactively alter or re-authenticate historical benchmark records.

## Hermetic verification

- `uv run --locked --extra benchmark -- python scripts/test_phenix_vendor_setup.py`
- `uv run --locked --extra benchmark -- python scripts/test_phenix_version_environment.py`
- `uv run --locked --extra benchmark -- python scripts/test_toolchain.py`
- `uv run --locked --extra benchmark -- python scripts/test_refinement_cache.py`
- `uv run --locked --extra benchmark -- python scripts/test_refinement_cache_xray.py`
- `uv run --locked --extra benchmark -- python scripts/test_refinement_cache_em.py`
- `uv run --locked --extra benchmark -- python scripts/test_benchmark_environment.py`
- `uv run --locked --extra benchmark -- bash scripts/validate.sh`

Fresh-context fix-diff review 032 at commit `116fd4d8ece3ebdcf454c9652a9dd69d0bc4d067` (`116fd4d`) found no actionable regression and observed a pre-existing path-validity edge case (filed as P3 follow-up #963): a configured `phenix.version` symlink alias containing a regular-file component followed by `..` (such as `../bin/phenix.version/../phenix.version`) is OS-invalid (`NotADirectoryError`) if opened directly, but Python lexical canonicalization and component resolution collapse the `<regular-file>/..` segment to the valid inside-prefix dispatcher `<prefix>/bin/phenix.version` and obtain measured build identity. Independent reproduction confirmed the same behavior exists on original `main` (`f3cfad326f28ddbf652dcdb0c5858443bee6e413`, `f3cfad3`), and no outside-prefix execution, wrong build identity, or vendor-file mutation was demonstrated. Issue #963 is left open for a separate fix because the tested vendor layout and this PR's prefix-containment and final-field consistency work are unaffected.
