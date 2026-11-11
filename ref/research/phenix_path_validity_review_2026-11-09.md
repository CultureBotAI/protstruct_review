# PHENIX Dispatcher Path-Component Validity Review (#963) — 2026-11-09

## Defect Summary

In [`scripts/toolchain.py`](../../scripts/toolchain.py), `_resolve_within_prefix` previously handled `".."` components during PHENIX dispatcher symlink resolution by taking the lexical parent (`current = current.parent`) without verifying that the preceding path component `current` was an existing directory on disk (`stat.S_ISDIR(os.lstat(current).st_mode)`). In addition, `_resolve_phenix_dispatcher` relied on `Path.is_symlink()` (which catches `OSError` / `NotADirectoryError` and returns `False`) and `Path.resolve(strict=True)` (which in Python's `posixpath._joinrealpath` collapses `regular_file/..` lexically when encountering `".."`).

When an intermediate component of the configured dispatcher path or of a recursively expanded symlink target resolved to an existing regular file inside the installation prefix — for example `phenix_bin/phenix.version -> ../bin/phenix.version/../phenix.version`, or an intermediate symlink-to-file followed by `/..` — `_resolve_within_prefix` collapsed `file/..` in memory and resolved to the regular file `<prefix>/bin/phenix.version`. Because `phenix_build_evidence` and `phenix_bare_build_evidence` then invoked `[str(resolved_dispatcher)]` directly, both the vendor-setup route and the bare route could accept a broken dispatcher path that the OS kernel rejects with `ENOTDIR` (`NotADirectoryError`) when accessed via `configured_dispatcher`.

## Contract Enforced

1. **Directory requirement on every intermediate component (`scripts/toolchain.py`)**:
   - `_require_directory(path, context_target)` inspects `os.lstat(path)` and raises `NotADirectoryError(errno.ENOTDIR, ...)` whenever `stat.S_ISDIR(info.st_mode)` is `False`.
   - `_walk_directory_components` walks `configured_prefix` and `configured_bin` component-by-component from `"/"` (including any ancestor symlinks), verifying that every intermediate component and the resolved directory endpoints are directories on disk before consuming any following component, including `".."` and `"."`.
   - `_resolve_within_prefix` parses raw path strings via `_raw_path_parts` (preserving `"."` segments and converting trailing `"/"` into a trailing `"."` lookup), matches absolute targets against `resolved_prefix` and `configured_prefix` via `_match_absolute_prefix_parts` (allowing redundant `"."` directory components inside the matched prefix while walking and verifying every raw prefix component via `_walk_directory_components` before returning the untouched raw suffix), verifies `_require_directory` on `resolved_prefix` and `current` before consuming any component (`"."`, `".."`, or child name), and verifies `_require_directory(current, target)` after any non-final component (`index < len(parts) - 1`).
   - If a recursive symlink expansion in `_resolve_within_prefix` returns a regular file while its caller still has remaining path components (`has_remaining`), `_require_directory(current, target)` rejects immediately before the caller can consume `".."` or any subsequent segment.
   - A final regular file (`stat.S_ISREG`) remains permitted for the terminal dispatcher target when no further path components follow.

2. **Preserved behaviors and rejection boundary**:
   - Allowed vendor symlink layouts (`phenix_bin/phenix.version -> ../bin/phenix.version`), allowed in-prefix `directory/..` traversals (both direct in-prefix `../subdir/../bin/phenix.version` and in-prefix directory-symlink `dir_hop/../bin/phenix.version`), and allowed absolute in-prefix symlink targets containing harmless `"."` directory components in either the `configured_prefix` or `resolved_prefix` spelling (`#1206`) continue to resolve and pass both vendor and bare probes.
   - Existing `#958` installation-prefix containment checks, `#960` symlink-loop and 40-hop limits, argument-vector safety, and pre/post-measurement hash consistency checks are preserved.
   - Invalid non-directory intermediate components fail in `_resolve_phenix_dispatcher` before either `run_capture` (bare probe) or `_run_phenix_setup` (vendor setup probe) executes. Both `phenix_build_evidence` and `phenix_bare_build_evidence` record the `NotADirectoryError` in `version_probe["error"]`, keep `reported_version_source`, `reported_version`, `parsed_build`, and `version_probe["resolved_path"]` as `None`, and remain unmeasured (`_build_is_measured(...) is False`); `external_tool_report()["PHENIX"]["available"]` likewise reports `False`.

3. **Scope boundary**:
   - This change enforces POSIX pathname-component directory validity (`ENOTDIR`) during PHENIX dispatcher resolution (`#963`). It does not claim a new filesystem concurrency or TOCTOU guarantee beyond the existing pre/post-measurement checks in `phenix_build_evidence`, does not alter refinement cache schemas or retained evaluation artifacts, and uses no installed vendor tools.

## Regression Coverage Authored

In [`scripts/test_phenix_vendor_setup.py`](../../scripts/test_phenix_vendor_setup.py), `PhenixVendorSetupTests.test_dispatcher_path_component_validity_across_vendor_and_bare_routes` uses owned inert temporary prefixes (`tempfile.TemporaryDirectory`) and no installed tools to test both `phenix_build_evidence` and `phenix_bare_build_evidence` across:

- **Valid paths**:
  - `normal-vendor-symlink`: `phenix_bin/phenix.version -> ../bin/phenix.version`
  - `in-prefix-directory-dotdot`: `phenix_bin/phenix.version -> ../subdir/../bin/phenix.version`
  - `in-prefix-dir-symlink-dotdot`: `phenix_bin/phenix.version -> dir_hop/../bin/phenix.version` (where `dir_hop -> ../subdir`)
  - `absolute-configured-prefix-with-dot` (`#1206`): `phenix_bin/phenix.version -> <configured_prefix_parent>/./<prefix_name>/bin/phenix.version`
  - `absolute-resolved-prefix-with-dot` (`#1206`): `phenix_bin/phenix.version -> <resolved_prefix_parent>/./<prefix_name>/bin/phenix.version`
- **Invalid paths**:
  - `direct-file-dotdot-file`: `phenix_bin/phenix.version -> ../bin/phenix.version/../phenix.version`
  - `intermediate-symlink-to-file-dotdot-file`: `phenix_bin/phenix.version -> file_hop/../phenix.version` (where `file_hop -> ../bin/phenix.version`)
  - `multi-hop-chain-to-file-dotdot`: `phenix_bin/phenix.version -> hop1 -> hop2 -> ../bin/phenix.version/../phenix.version`
  - `multi-hop-file-symlink-then-dotdot`: `phenix_bin/phenix.version -> hop_a/../bin/phenix.version` (where `hop_a -> hop_b -> ../bin/phenix.version`)
  - `absolute-dot-prefix-with-file-dotdot-suffix`: `phenix_bin/phenix.version -> <configured_prefix_parent>/./<prefix_name>/bin/phenix.version/../phenix.version`
  - `configured-path-regular-file-dotdot`: `configured_bin = <prefix>/bin/phenix.version/../../phenix_bin` with valid `phenix_bin/phenix.version -> ../bin/phenix.version`
  - `external_tool_report()` with `phenix_bin/phenix.version -> ../bin/phenix.version/../phenix.version`
  - Explicit root prefix `Path("/")` (`#1207`): owned-file hermetic regression verifying `_match_absolute_prefix_parts` returns the expected suffix tuple and `_resolve_within_prefix` resolves an absolute symlink target to the owned dispatcher without creating files at `/` or invoking setup/dispatcher, plus a `regular-file/..` suffix rejection control under `Path("/")`.

Each valid case asserts `os.readlink(self.configured_dispatcher) == link_target` and `os.path.samefile(self.configured_dispatcher, self.real_dispatcher)`. Each invalid case first asserts `os.stat(raw_dispatcher_path)` raises `NotADirectoryError` so the test fixture has not normalized away the kernel-level `ENOTDIR` defect, then asserts under `wraps=` spies on `_run_phenix_setup` and `run_capture` that neither subprocess helper is invoked and neither route is accepted as a measured build.

## Review History and Validation Stage

- **Candidate 0 (`#1206` review finding)**:
  - Candidate 0 passed PRIMARY focused test suites, and non-destructive baseline verification confirmed the new invalid-path subtests failed against baseline `toolchain.py` on the intended assertions.
  - Independent static review of Candidate 0 identified one P2 regression (filed as `#1206`, `https://github.com/CultureBotAI/protstruct_review/issues/1206`), which PRIMARY independently reproduced: an absolute symlink target containing a harmless `"."` component before the end of the installation prefix (`<prefix-parent>/./<prefix-name>/bin/phenix.version`) is kernel-valid and accepted by baseline `toolchain.py`, but Candidate 0 rejected it as a prefix escape because `_resolve_within_prefix` compared dot-preserving `raw_parts` directly against dot-normalized `resolved_prefix` and `configured_prefix` segment tuples.
- **Candidate 1 (`#1206` correction and `#1207` review finding)**:
  - Added `_match_absolute_prefix_parts` in `scripts/toolchain.py` and positive/negative `/./` prefix regressions in `scripts/test_phenix_vendor_setup.py`.
  - Candidate 1 passed PRIMARY focused test suites and extended historical sensitivity checks, and independent re-review accepted the `#1206` correction while identifying one P3 root-prefix boundary regression (filed as `#1207`, `https://github.com/CultureBotAI/protstruct_review/issues/1207`), which PRIMARY independently reproduced: `_match_absolute_prefix_parts` returned `None` when `prefix_parts` was empty (`prefix == Path("/")`), rejecting valid absolute targets under an explicitly configured root prefix that baseline and Candidate 0 accepted.
- **Candidate 2 (`#1207` correction — current stage)**:
  - Removed the `if not prefix_parts: return None` guard in `_match_absolute_prefix_parts` so an empty/root prefix (`Path("/")`) validates `"/"` via `_walk_directory_components(Path("/"), matched_raw_prefix) == resolved_prefix` and returns the untouched raw suffix `raw_parts[raw_index:]`.
  - Added an owned-file hermetic regression in `scripts/test_phenix_vendor_setup.py` for explicit `Path("/")` prefix matching and resolution alongside an invalid `regular-file/..` suffix control.
  - **Pending PRIMARY verification**: Candidate 2 was authored in a file-tools-only secondary pass; final focused execution, re-review, and the full hermetic validation gate (`scripts/validate.sh`) are pending execution by PRIMARY.
