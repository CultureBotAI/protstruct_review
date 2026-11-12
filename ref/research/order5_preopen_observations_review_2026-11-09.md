# Order 5 Review: Pre-`fstat` Lookup and Traversal Observation Retention (`#1168` Bounded Slice, 2026-11-09)

## Scope and Provenance

- **Issues**:
  - `#1168` (`https://github.com/CultureBotAI/protstruct_review/issues/1168`, including comment `6758033115`) — bounded pre-`fstat` observation retention slice after completed pre-open lookup and component traversal in `_stream_observe_regular_file`, including public projection of detected dependency conflicts on partial owners.
  - `#1157` (`https://github.com/CultureBotAI/protstruct_review/issues/1157`, comments `6758007869` and `6758340122`) — guardrail fixture call correction and aliased-`TMPDIR` canonicalization in `scripts/test_refmac_diagnostic_profile.py`.
  - `#1212` (`https://github.com/CultureBotAI/protstruct_review/issues/1212`, including comment `6758340617`) — audit receipt alignment with actual implementation, symbols, baseline receipts, and execution boundaries.
- **Target worktree / branch**: `protstruct_review-wt-078` (`analysis/1sar-rerun-2026-11-06`).
- **Source and baseline evidence**:
  - `.orchestration/reports/847-order5-contract-audit.md` (`#1168` section)
  - `.orchestration/reports/858-order5-observation-acceptance.md` (`#1168` section)
  - `.orchestration/evidence/845-approved-next-steps/issue-1168-before.json`
  - `.orchestration/evidence/845-approved-next-steps/1168-baseline/result.json` (4-case initial baseline) and `.orchestration/evidence/845-approved-next-steps/1168-forward-baseline-v2/result.json` (6-case core old-source baseline)
  - `.orchestration/evidence/845-approved-next-steps/{1168-forward-candidate0,1168-integration-candidate0,1168-focused0,1168-focused1,1168-alias-temp-baseline}`
  - `.orchestration/evidence/845-approved-next-steps/{probe-1168-partial-conflict.py,1168-partial-conflict-candidate0/result.json,probe-1168-manifest-conflict.py,1168-manifest-conflict-candidate0/result.json}`
- **Product files in scope**:
  - `scripts/refmac_diagnostic_profile.py` (SHA-256 `ec6355458702277b9fbbc6ba83e24a89c690719fee98f3d23a2563e2e98dd2cd`; historical `candidate0`/`candidate1` SHA-256 `88cbfb64a6f820e46eb3e3c8961cc4fa038d172d1ffe31932181d9b7a547c033`)
  - `scripts/test_refmac_diagnostic_profile.py`
  - `ref/research/order5_preopen_observations_review_2026-11-09.md` (this note)
- **Untouched boundaries**:
  - No raw, frozen, or retained run/attempt artifacts were modified.
  - No native PHENIX/CCP4/REFMAC execution was performed.

---

## Pre-Open Lookup Flow and Baseline Gaps

In `scripts/refmac_diagnostic_profile.py`, `_stream_observe_regular_file(raw_lexical, *, expected_pin=None, chunk_size=STREAM_CHUNK_BYTES, retain_bytes=False)` (`:1502–1730`) completes three pre-open steps before calling `os.open` and initial `os.fstat`:

1. `lex_lstat_before, lex_stat_before = _validate_kernel_regular_lookup(raw_lexical)` (`:1194–1213`, called at `:1510`) — runs `os.lstat(raw_lexical)` and `os.stat(raw_lexical)` and verifies `stat.S_ISREG(lex_stat.st_mode)`.
2. `traversal_before = _traverse_path_components(raw_lexical)` (`:1229–1440`, called at `:1511`) — resolves `raw_lexical` left-to-right from `/` and returns `_PathTraversalResult` (`:1216–1226`).
3. `resolved_before, target_lstat_before = _resolve_regular_target_strict(raw_lexical)` (`:1448–1490`, called at `:1513`) — strictly resolves `raw_lexical`, verifies that no component along the resolved path is a symlink and all parents are directories, runs `os.lstat(resolved_str)`, and verifies the resolved target is a regular file matching `lex_stat_before` in `(dev, ino, mode, uid, gid)` and `st_size` (`:1515–1522`).

Prior to Task 851 (`.orchestration/evidence/845-approved-next-steps/1168-baseline/result.json`), `_stream_observe_regular_file` raised `_PartialFileReadError` only after `pre_eof_after_fstat = True` was set following both `os.open` and initial `os.fstat`. An `OSError` at `os.open` or initial `os.fstat` raised a plain `ValueError` and dropped the completed pre-open lookup and traversal observations.

In historical `candidate0`/`candidate1` (`88cbfb64...`), `_record_partial_read_dependencies` (`:3606–3641`) detected shared directory/symlink identity conflicts and returned `_ObservedFileDependencies(complete=False, errors=...)` privately on `manifest_dependencies` and `file_dependencies[file_id]`, but public projection (`ProfileValidationError.manifest_identity`, `ProfileValidationError.files[file_id]`, `ProfileValidationError.errors`, and `to_provenance()`) reused the unprojected `PartialFileReadObservation` with `dependencies_complete=True` and omitted the conflict message (`#1168` comment `6758033115`, reproduced in `1168-partial-conflict-candidate0/result.json` and `1168-manifest-conflict-candidate0/result.json`).

---

## Bounded Implementation

1. **`LookupStatObservation` and `PreOpenLookupSnapshot`**:
   - `LookupStatObservation` (`:681–766`) is a frozen dataclass storing `dev`, `ino`, `mode`, `uid`, `gid`, `size_bytes`, `is_symlink: bool = False`, and `is_regular: bool = True`. `from_stat_result` (`:727–738`) extracts permission bits via `int(stat.S_IMODE(st.st_mode))` into `mode` and separately sets `is_symlink=bool(stat.S_ISLNK(st.st_mode))` and `is_regular=bool(stat.S_ISREG(st.st_mode))`. `__post_init__` (`:694–725`) enforces non-boolean `int` fields, positive `(dev, ino)`, non-negative `mode`/`uid`/`gid`/`size_bytes`, boolean type flags, and `self.is_symlink != self.is_regular`.
   - `PreOpenLookupSnapshot` (`:769–909`) is a frozen dataclass storing `lexical_path`, `resolved_path`, `lexical_lstat`, `lexical_stat`, `resolved_target_lstat`, `symlinks: tuple[_SymlinkEdge, ...]`, `symlink_identities: tuple[_ObservedSymlinkIdentity, ...]`, and `traversed_directories: tuple[_ObservedDirectoryIdentity, ...]`.
   - In `_stream_observe_regular_file` (`:1524–1535`), `lookup_snapshot_before` is constructed from `lex_lstat_before`, `lex_stat_before`, `resolved_before` and `target_lstat_before` (returned by `_resolve_regular_target_strict`), and `traversal_before.{symlink_edges, symlink_identities, directory_identities}`.
   - `PartialFileReadObservation` (`:911–1150`) carries `lookup_snapshot: PreOpenLookupSnapshot | None = None` and serializes it in `to_dict()` (`:1142–1146`). When descriptor `fstat` identity fields (`dev`, `ino`, `mode`, `uid`, `gid`) are `None`, `__post_init__` (`:999–1007`) requires `stat_size_bytes is None` and `streamed_size_bytes == 0`, while `sha256` and `size_bytes` are `None` and `read_complete == verified == False`.

2. **Symlink Identity Capture During Traversal**:
   - In `_traverse_path_components` (`:1337–1353, 1427–1440`), each visited symlink component constructs `_ObservedSymlinkIdentity` directly from the existing `os.lstat(cand_path)` and `os.readlink(cand_path)` results, verifies identity stability if revisited during the same traversal, and returns `symlink_identities: tuple[_ObservedSymlinkIdentity, ...]` on `_PathTraversalResult` without additional syscalls.

3. **Bounded `os.open` / Initial `os.fstat` Partial Retention**:
   - `_stream_observe_regular_file` sets `in_open_or_initial_fstat = True` (`:1595`) immediately before `fd = os.open(resolved_before, open_flags)` (`:1596`) and `fstat_before = os.fstat(fd)` (`:1597`), then resets `in_open_or_initial_fstat = False` (`:1598`).
   - In `except Exception as exc:` (`:1665–1693`), if `in_open_or_initial_fstat` is `True`, `_stream_observe_regular_file` builds `err_msg = f"Failed reading regular file {raw_lexical!r} ({type(exc).__name__}): {exc}"` and raises `_PartialFileReadError(err_msg, observation=_build_partial_read_obs(err_msg, fstat_st=None, streamed_bytes=0)) from exc` (`:1675–1683`), where `_build_partial_read_obs` (`:1555–1592`) takes `err_msg: str` and populates `ancestors=traversal_before.directory_identities`, `symlink_identities=traversal_before.symlink_identities`, and `lookup_snapshot=lookup_snapshot_before`. If `os.open` returned a descriptor before initial `os.fstat` failed, `finally` (`:1695–1699`) closes `fd`.

4. **Contextual Partial Projection and Admission/Postflight Propagation**:
   - `_record_partial_read_dependencies` (`:3606–3641`) records canonical `partial_obs.ancestors` (`_ObservedDirectoryIdentity`) and `partial_obs.symlink_identities` (`_ObservedSymlinkIdentity`) into `observed_ancestors` and `observed_symlinks` in memory, retaining the earlier global entries while capturing any conflict messages in `_ObservedFileDependencies.errors` (`complete=False`).
   - `_build_partial_file_observation` (`:6614–6721`) projects a contextual `PartialFileReadObservation` purely in memory: it preserves `partial_obs.errors` first (keeping message-prefix size-mismatch classification in `_is_size_mismatch_partial_observation` at `:7959–7966` intact), appends per-owner and dependency conflict errors without duplication, retains per-owner measured `ancestors`, `symlink_identities`, and `lookup_snapshot`, and computes `dependencies_complete = bool(partial_obs.dependencies_complete and ...)` so incomplete dependency evidence is never upgraded and detected conflicts set `dependencies_complete=False`. When no fields change, it returns `partial_obs` unchanged.
   - In `_validate_and_observe_outer_profile` (`:4090–4139, 4218–4238, 4548–4574`) and `validate_profile` (`:7700–7729`), manifest and declared-file `_PartialFileReadError` handlers record the primary `_PartialFileReadError` (chained to the original `os.open`/`os.fstat` `OSError`) first, record any `manifest_dependencies.errors` or `file_dependencies[file_id].errors` as comparison `ValueError` entries (with `error_errno=None` and `__cause__=None`) in `manifest_error_messages` / `per_file_error_messages[file_id]` and aggregate `errors` / `error_records`, and project `partial_manifest_observation`, `manifest_file_observation`, `partial_files[file_id]`, and `file_observations[file_id]` via `_build_partial_file_observation`.
   - During private recheck (`_reobserve_outer_profile_state`, `:4718–4724, 4805–4811`) and public `recheck_profile` (`:8226–8227, 8285–8299, 8306–8312, 8356–8357, 8421–8437, 8444–8450`), pre-`fstat` partials have `exc.is_size_mismatch == False` and do not match the message prefixes in `_is_size_mismatch_partial_observation` (`:7959–7966`, which checks `"Size mismatch for "` and `"Pinned JSON size mismatch for "` on `pobs.errors[0]`), so their original `OSError` causes are retained and their current `ancestors` and `symlinks` participate in postflight dependency error association.

5. **Out-of-Scope Failure Boundaries (Unchanged)**:
   - Pre-traversal lookup failures in `_validate_kernel_regular_lookup`, mid-traversal failures in `_traverse_path_components`, strict resolution failures in `_resolve_regular_target_strict`, post-initial-`fstat` non-regular or `(dev, ino, mode, uid, gid)` identity-mismatch `ValueError`s (`:1599–1608`), and post-EOF verification failures (`fstat_after` `OSError` at `:1662` or post-read identity/size/lookup/traversal drift checks at `:1701–1730`) still raise plain `ValueError` without `_PartialFileReadError`.

---

## Permanent Test Coverage vs PRIMARY Execution Status

### Permanent Tests in `scripts/test_refmac_diagnostic_profile.py`

Class `TestTask851Issue1168PreOpenObservations` (`:8034–9577`) defines helper `_assert_pre_fstat_partial_obs` (`:8037–8107`) and **four** test methods:

1. `test_1168_open_and_initial_fstat_failures_across_ordinary_intermediate_and_terminal_symlink_paths` (`:8109–8586`):
   - Exercises `os.open` (`PermissionError(EACCES)`) and initial `os.fstat` (`OSError(EIO)`) one-shot failures across three declared-file path shapes: ordinary regular file (`launcher`), intermediate symlink + `..` (`support/inter-link/sub/../inter-target.txt`), and terminal symlink (`alias_symlink`).
   - Across `validate_profile`, `_reobserve_outer_profile_state`, and `recheck_profile`, asserts retained `PartialFileReadObservation` and `PreOpenLookupSnapshot` fields (including terminal-symlink `lexical_lstat.is_symlink=True` vs `lexical_stat.is_regular=True`), null descriptor `fstat` and full-stream fields, bystander fd safety and owned fd closure (`EBADF`), original exception identity in causes and `mutation_causes_out`, and in-memory `adm_err.to_provenance()` / `adm_fobs.to_dict()` serialization while `os.lstat`, `os.stat`, `os.open`, and `os.readlink` are patched to fail (`:8439–8459`).
2. `test_1168_manifest_open_and_initial_fstat_failures_across_admission_and_recheck` (`:8588–8803`):
   - Exercises `os.open` and initial `os.fstat` failures on a terminal-symlinked manifest (`manifest-link.json`) across `validate_profile`, `_reobserve_outer_profile_state`, and `recheck_profile`, asserting retained `manifest_identity` / `partial_manifest_observation`, owned fd closure on initial `os.fstat` failure, and that `_parse_verified_json_bytes`, `_validate_outer_manifest_shape`, and `_observe_controlled_root` are not called during failed manifest admission.
3. `test_1168_shared_dependency_failure_association_and_guardrail_boundaries` (`:8805–9030`):
   - Exercises a shared Step 4 ancestor directory failure (`support_dir`) alongside an `os.open` failure on `alias_symlink` in `recheck_profile` (verifying both causes attach to `profile:file:{alias_fid}` in `mutation_causes_out`), checks `LookupStatObservation` / `PartialFileReadObservation` validation guardrails, and checks that four out-of-scope boundaries (initial `os.lstat` failure, `_traverse_path_components` failure, initial `fstat` identity mismatch, and post-EOF second `os.fstat` failure) raise plain `ValueError` rather than `_PartialFileReadError` (`:8960–9030`).
4. `test_1168_partial_owner_dependency_conflicts_across_declared_file_and_manifest_stages` (`:9031–9577`):
   - Deterministic regression test for `#1168` comment `6758033115` covering both declared-file (`zz_second_shared_symlink_user` shared-symlink rename/recreate inode conflict) and manifest (evidence-root shared-ancestor permission-bit flip) partial owners crossed with `open` and `initial_fstat` `OSError(errno.EIO)` failures, plus 60-file and 59-file positive controls.
   - Asserts both conflicting identities survive (earlier in `observed_symlinks`/`observed_ancestors` and first file; later on the partial owner and its `lookup_snapshot`), `dependencies_complete=False` and `verified=False` publicly and privately, both the read error (first) and conflict error (second) appear on the partial owner and in aggregate `ProfileValidationError.errors` / `to_provenance()["errors"]`, `cause_exception` remains the exact original `OSError(errno.EIO)` while the conflict record has `error_type="ValueError"` and `error_errno=None`, unverified manifests are never parsed, `_build_partial_file_observation` never upgrades incomplete dependency evidence, and `to_provenance()` remains pure under poisoned filesystem readers.

### Separate PRIMARY Probes vs Permanent Suite Status

- **PRIMARY standalone probes on historical `candidate0`/`candidate1` (`88cbfb64...`)**:
  - `1168-forward-baseline-v2/result.json` and `1168-forward-candidate0`: all 6 owned core cases (ordinary, intermediate symlink + `..`, terminal symlink × `os.open`, initial `os.fstat`) **PASSED** on `candidate0`, while the separate 6-case core old-source baseline (`1168-forward-baseline-v2/result.json`; earlier `1168-baseline/result.json` recorded 4 ordinary and symlink/dotdot × `open`/`initial_fstat` cases) exercised all 6 cases on frozen pre-Task-851 source and confirmed old source raised plain `ValueError` with no retained partial observation.
  - `1168-integration-candidate0`: all 12 owned integration cases (manifest and launcher × `os.open` and initial `os.fstat` × public admission, private recheck, public recheck) **PASSED** on `candidate0`; on frozen pre-Task-851 source, the integration sensitivity run stopped at its first manifest/`open`/admission missing-observation assertion (only `candidate0` ran all 12 integration cases).
  - `1168-focused0` and `1168-focused1`: after Task 866 fixed the four `#1157` guardrail calls (`candidate1`, source still `88cbfb64...`), all 56 tests in `scripts/test_refmac_diagnostic_profile.py` **PASSED** (`1168-focused1`).
  - `1168-partial-conflict-candidate0` and `1168-manifest-conflict-candidate0`: PRIMARY executed the four baseline conflict witnesses (`probe-1168-partial-conflict.py` and `probe-1168-manifest-conflict.py`, 2 owners × 2 stages) against `88cbfb64...`, reproducing the public conflict-projection loss on partial owners.
- **`candidate2` (`ec6355458702277b9fbbc6ba83e24a89c690719fee98f3d23a2563e2e98dd2cd`) and Task 868 fixture portability fix**:
  - With production source `ec635545...`, PRIMARY's canonical 57-test focused suite (`scripts/test_refmac_diagnostic_profile.py`) and 22 independent probe cases **PASSED**.
  - Under an owned symlinked `TMPDIR` (`.orchestration/evidence/845-approved-next-steps/1168-alias-temp-baseline`), the manifest conflict fixture at line `9358` (`owned = Path(tmpdir)`) failed at line `9392` before reaching the intended `EIO` because `_build_synthetic_outer_profile_fixture` canonicalizes `evidence_root` (`#1157` comment `6758340122`).
  - Task 868 updated line `9358` of `scripts/test_refmac_diagnostic_profile.py` to `owned = Path(tmpdir).resolve(strict=True)` via file tools only (leaving `scripts/refmac_diagnostic_profile.py` unchanged at `ec635545...`). Re-running the aliased-`TMPDIR` regression and canonical 57-test focused suite, fresh independent review acceptance, and full hermetic QC remain pending PRIMARY execution.
