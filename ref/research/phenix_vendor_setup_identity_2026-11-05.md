# PHENIX Configured-Install Vendor Setup Build Identity (#954, #955) — 2026-11-05

## Problem statement and root cause (#954)

In PHENIX `2.0-5936` (observed identically on both the original M1 installation and the M5 copy), the command-line dispatcher `<prefix>/phenix_bin/phenix.version` resolves to `<prefix>/bin/phenix.version` and runs `<prefix>/lib/python3.9/site-packages/phenix/command_line/version.py` (`phenix_info.show_banner()`). `phenix_info.py` reads `PHENIX_VERSION` and `PHENIX_RELEASE_TAG` from its process environment, falling back to `../TAG` relative to the `libtbx` distribution only when those variables are absent.

Read-only inspection of the installed `2.0-5936` prefix confirmed:

1. No `TAG` or `cctbx_bundle_TAG` file is present anywhere in `<prefix>` or in any of the 284 installed conda package manifests (`conda-meta/*.json`).
2. `<prefix>/bin/phenix.version` does not source `<prefix>/phenix_env.sh`.
3. `<prefix>/phenix_env.sh` is the vendor-shipped setup script that exports `PHENIX_VERSION=2.0-5936`.
4. Because `scripts/toolchain.py` strips inherited `PHENIX_VERSION` and `PHENIX_RELEASE_TAG` from the parent environment to prevent cross-installation spoofing (#816), invoking `phenix.version` directly without sourcing the target installation's own `phenix_env.sh` exits `0` with only the title and `User:` lines:

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
   - The installation prefix is derived strictly from the configured binary directory (`PHENIX_BIN` or explicit `configured_bin`): if its lexical name is `phenix_bin` or `bin`, the prefix is its resolved parent directory; otherwise the prefix is the resolved directory itself.
   - Every intermediate symlink hop on `<configured_bin>/phenix.version` and `<prefix>/phenix_env.sh` is checked step-by-step. Any symlink hop or final resolved target that escapes the resolved installation prefix, any symlinked parent directory, any missing or non-regular `phenix_env.sh`, or any `PATH`-only fallback when `configured_bin` is absent is rejected.
   - No new environment variable or per-runner setup path constant is introduced.

2. **Sanitized child environment and shell-hook neutralization (#816 preserved):**
   - `phenix_version_environment()` copies the source environment without mutating `os.environ`, removes `PHENIX_VERSION` and `PHENIX_RELEASE_TAG` (recording removed keys in `ignored_inherited_version_variables`), removes shell startup/execution hooks (`BASH_ENV`, `ENV`, `SHELLOPTS`, `BASHOPTS`, `POSIXLY_CORRECT`, `CDPATH`, `GLOBIGNORE`, `PROMPT_COMMAND`, `PS4`), removes all `BASH_FUNC_*` variables and any variable whose value starts with `"() {"`, and sets `PYTHONDONTWRITEBYTECODE=1`.
   - The setup probe invokes `/bin/bash --noprofile --norc -c <_PHENIX_SETUP_SCRIPT> protstruct-phenix-setup <resolved_setup_path>` with positional argument `$1` (`source -- "$1"`), never interpolating file paths into shell text.

3. **Separate setup and dispatcher streams, independent normalization, and single-banner rule:**
   - The setup probe verifies inside the child shell that `PHENIX_VERSION` and `PHENIX_RELEASE_TAG` are unset before sourcing, counts assignments to `PHENIX_VERSION` and `PHENIX_RELEASE_TAG` in `<prefix>/phenix_env.sh` to reject duplicate definitions, sources `<prefix>/phenix_env.sh` with stdout/stderr redirected to `/dev/null` while capturing any chatter separately, and emits NUL-delimited records on stdout only when setup exits `0` with zero stdout/stderr chatter.
   - `parse_phenix_setup_build()` normalizes the setup-exported `PHENIX_VERSION` / `PHENIX_RELEASE_TAG` fields independently of the banner parser, rejecting missing, malformed, or contradictory fields.
   - The resolved `<prefix>/bin/phenix.version` dispatcher is then executed directly (`shell=False`) using the base sanitized environment overlaid only with the non-empty `PHENIX_VERSION` / `PHENIX_RELEASE_TAG` values exported by `<prefix>/phenix_env.sh`.
   - `parse_phenix_build()` accepts **one** consistent `Version:` / `Release tag:` pair within a single PHENIX banner header (confirming the user's clarification of #814 / #954) and rejects multiple PHENIX banner headers, duplicate `Version:` or `Release tag:` lines, contradictory single-line and split-line values, or fragments split across stdout and stderr.
   - Setup and dispatcher files and symlink targets are stat/digest-checked before and after execution; any mid-probe file or symlink change invalidates the probe.
   - Admission to `reported_version_source="vendor_setup_environment"` requires `setup_build == banner_build` and no banner fragments on `stderr`. Any failure, timeout, chatter, escape, or disagreement leaves `reported_version=None` and `reported_version_source=None` while retaining full diagnostic fields.

4. **Explicit bare probe retained:**
   - `phenix_bare_build_evidence()` (or `phenix_build_evidence(..., use_vendor_setup=False)`) preserves direct `phenix.version` probing with `reported_version_source="command_output"`.
   - Default `phenix_build_evidence()` never falls back to accepting bare output or path-derived version hints when `phenix_env.sh` is missing or invalid.

5. **Structural and semantic cache-gate verification (`scripts/refinement_cache.py`):**
   - `_build_is_measured()` validates all required `vendor_setup_environment` bindings: non-empty `parsed_build`, exact `reported_version == parsed_build`, `configured_path` / `resolved_path` / `setup_configured_path` / `setup_resolved_path` containment within the installation prefix, 64-hex `sha256` and `setup_sha256`, exact `argv == [resolved_path]` and `setup_argv == phenix_setup_argv(setup_resolved_path)`, `int` zero `returncode` and `setup_returncode`, empty `setup_stdout` and `setup_stderr`, no banner fragments in `stderr`, exact `stdout.strip() == reported_version`, and equality of `parse_phenix_setup_build(setup_version_fields) == parse_phenix_build(stdout) == parsed_build`.
   - `setup_configured_path`, `setup_resolved_path`, `setup_sha256`, `setup_argv`, `setup_returncode`, `setup_stdout`, `setup_stderr`, and `setup_version_fields` are bound into `refinement_cache_v1` `key_material` alongside the dispatcher identity, so changing either `phenix_env.sh` or `phenix.version` bytes produces a distinct cache key and invalidates stale reuse.

6. **Hermetic unit-test isolation for `benchmark_environment` (#955):**
   - `scripts/test_benchmark_environment.py` now isolates default-route `benchmark_environment()` and `announce_benchmark_environment()` calls with deterministic synthetic tool reports and wraps the test suite in a `toolchain.subprocess.run` tripwire so unit tests never execute installed PHENIX/CCP4 or other external binaries during `scripts/validate.sh`. Runtime `benchmark_environment()` collection remains live when called in opt-in benchmarks.

## Explicit scope limits

- **Not a whole-installation or library hash:** `setup_sha256` and `sha256` authenticate `<prefix>/phenix_env.sh` and `<prefix>/bin/phenix.version`, not every Python module or shared library imported by PHENIX. Unversioned in-place library edits still require a fresh cache directory.
- **Version-only setup probe:** Sourcing `<prefix>/phenix_env.sh` in `phenix_build_evidence()` applies only to the version-discovery probe in `scripts/toolchain.py` (CODING_STANDARDS rule 19b). It does not claim that scientific PHENIX refinement runners source `phenix_env.sh` when invoking `phenix.refine`, `phenix.real_space_refine`, `phenix.model_vs_data`, or `phenix.mtriage`.
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
