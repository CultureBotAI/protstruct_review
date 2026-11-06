# PHENIX Configured-Install Vendor Setup Build Identity (#954, #955, #956) — 2026-11-05

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

1. **Strict prefix, setup, and dispatcher containment:**
   - The installation prefix is derived strictly from the configured binary directory (`PHENIX_BIN` or explicit `configured_bin`): if its lexical name is `phenix_bin` or `bin`, the prefix is its parent directory; otherwise the prefix is the directory itself.
   - Neither `configured_bin` nor `configured_prefix` may be a symlink. Every intermediate symlink hop on `<configured_bin>/phenix.version` is checked step-by-step, and `<prefix>/phenix_env.sh` must be a regular non-symlink file directly under `<prefix>`. Any symlink hop or final resolved target that escapes the resolved installation prefix, any missing or non-regular `phenix_env.sh`, or any `PATH`-only fallback when `configured_bin` is absent is rejected.
   - No new environment variable or per-runner setup path constant is introduced.

2. **Sanitized child environment and shell-hook neutralization (#816, #956):**
   - `phenix_version_environment()` copies `os.environ` without mutating the parent environment, removes `PHENIX_VERSION` and `PHENIX_RELEASE_TAG` (recorded in `ignored_inherited_version_variables`), and removes shell startup/execution hooks (`BASH_ENV`, `ENV`, `SHELLOPTS`, `BASHOPTS`, `POSIXLY_CORRECT`, `CDPATH`, `GLOBIGNORE`, `PROMPT_COMMAND`, `PS4`), all `BASH_FUNC_*` variables, and any legacy exported shell function whose value starts with `"() {"` (recorded in `ignored_inherited_shell_hooks`).
   - The setup probe invokes `/bin/bash --noprofile --norc -c <_PHENIX_SETUP_SCRIPT> protstruct-phenix-setup <resolved_setup_path>` with positional argument `$1` (`builtin . "$1"`), never interpolating file paths into shell text, and first unsets shell builtins/functions (`export`, `unset`, `printf`, `.`, `exit`) and `PHENIX_VERSION`, `PHENIX_RELEASE_TAG`, `BASH_ENV`, and `ENV`.

3. **Deliberate version-only field transfer, independent normalization, and single-banner rule:**
   - The setup probe counts active assignments to `PHENIX_VERSION` and `PHENIX_RELEASE_TAG` in `<prefix>/phenix_env.sh` to reject duplicate definitions, sources `<prefix>/phenix_env.sh` in the isolated child shell, separates any setup stdout/stderr chatter from the NUL-delimited version record, and requires zero exit status and empty `setup_stdout` / `setup_stderr`.
   - `parse_phenix_setup_build()` normalizes the setup-exported `PHENIX_VERSION` / `PHENIX_RELEASE_TAG` fields independently of the banner parser, rejecting missing, malformed, or contradictory fields.
   - **Version-only transfer:** Only the two setup-derived version variables (`PHENIX_VERSION` and `PHENIX_RELEASE_TAG`) are overlaid onto the sanitized `base_env` when invoking `<prefix>/bin/phenix.version` (`shell=False`). The adapter deliberately does **not** transfer the complete sourced setup environment (such as `PATH`, `PHENIX`, or library variables) to `phenix.version` or to scientific runners.
   - `parse_phenix_build()` accepts **one** consistent `Version:` / `Release tag:` pair within a single PHENIX banner header (as explicitly confirmed by the user) and rejects multiple PHENIX banner headers, duplicate `Version:` or `Release tag:` lines, contradictory single-line and split-line values, or fragments split across banners or stdout/stderr.
   - Setup and dispatcher files and symlink targets are verified before and after execution; any mid-probe file or symlink change invalidates the probe.
   - Admission to `reported_version_source="vendor_setup_environment"` requires `setup_build == banner_build` and no banner fragments on `stderr`. Any failure, timeout, chatter, escape, or disagreement leaves `reported_version=None` and `reported_version_source=None` while retaining full diagnostic fields.

4. **Explicit bare probe retained:**
   - `phenix_bare_build_evidence()` (or `phenix_build_evidence(..., use_vendor_setup=False)`) preserves direct `phenix.version` probing with `reported_version_source="command_output"`.
   - Default `phenix_build_evidence()` never falls back to accepting bare output or path-derived version hints when `phenix_env.sh` is missing or invalid.

5. **Structural and semantic cache-gate verification (`scripts/refinement_cache.py`):**
   - `_build_is_measured()` validates all required `vendor_setup_environment` bindings: non-empty `parsed_build`, exact `reported_version` banner match, `configured_prefix` / `resolved_prefix` / `setup_configured_path` / `setup_resolved_path` / `configured_path` / `resolved_path` containment within the installation prefix, 64-hex `sha256` and `setup_sha256`, exact `argv == [resolved_path]` and `setup_argv == phenix_setup_argv(setup_resolved_path)`, `int` zero `returncode` and `setup_returncode`, empty `setup_stdout` and `setup_stderr`, no banner fragments in `stderr`, valid `setup_version_fields`, equality of `parse_phenix_setup_build(setup_version_fields) == parse_phenix_build(stdout) == setup_parsed_build == parsed_build`, and well-formed `ignored_inherited_version_variables` and `ignored_inherited_shell_hooks`.
   - Because `version_probe` (including `setup_configured_path`, `setup_resolved_path`, `setup_sha256`, `setup_argv`, `setup_returncode`, `setup_stdout`, `setup_stderr`, and `setup_version_fields`) is embedded in `measured_build` inside `refinement_cache_v1` `key_material`, changing either `phenix_env.sh` or `phenix.version` bytes produces a distinct cache key and invalidates stale reuse.

## PRIMARY acceptance triage and fixes (#955, #956)

1. **#955 (`scripts/test_benchmark_environment.py` hermetic isolation):**
   - **Finding:** `scripts/test_benchmark_environment.py` previously called `benchmark_environment()` and `announce_benchmark_environment()` with `external_tools=None` without mocking `external_tool_report()`, causing `scripts/validate.sh` to invoke live external version probes (including two `phenix.version` calls) when installed on M5.
   - **Fix & verification:** Isolated default-route metadata/announcement assertions in `scripts/test_benchmark_environment.py` using deterministic synthetic tool reports, preserved an explicit assertion that omitting `external_tools` dispatches through `external_tool_report()` (`call_count == 2`), and added a `toolchain.subprocess.run` tripwire proving the unit suite cannot spawn external tool subprocesses. Production `benchmark_environment()` remains live for opt-in benchmarks.

2. **#956 (legacy exported shell function names in `ignored_inherited_shell_hooks`):**
   - **Finding:** `toolchain._is_shell_hook_variable()` detects legacy exported bash functions by value prefix (`() {`) regardless of variable name (e.g. `LEGACY_FUNC='() { :; }'`), strips them in `phenix_version_environment()`, and records the variable name in `version_probe["ignored_inherited_shell_hooks"]`. In the initial 027 draft, `refinement_cache._valid_ignored_hooks()` checked a name-only whitelist (`_SHELL_HOOK_VARIABLES` or `BASH_FUNC_*`), causing `_build_is_measured()` to return `False` and preventing cache reuse whenever a legacy exported function was present in the parent environment.
   - **Fix & verification:** Updated `refinement_cache._valid_ignored_hooks()` to validate `ignored_inherited_shell_hooks` as a sorted, deduplicated sequence of non-empty, whitespace/NUL/`=`-free environment variable names disjoint from `_PHENIX_VERSION_VARIABLES`, aligning validator and producer semantics while rejecting malformed, unsorted, duplicate, or misplaced version-variable entries. Extended `test_spoofed_inherited_vars_and_shell_hook_tripwires_are_neutralized` in `scripts/test_phenix_vendor_setup.py` to assert `_build_is_measured(evidence) is True` and single-execution cache reuse (`len(self.calls) == 1`, `success.json`) both for the combined hook fixture and for `LEGACY_FUNC='() { :; }'` alone.

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
