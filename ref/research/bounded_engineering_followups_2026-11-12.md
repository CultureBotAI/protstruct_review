# Bounded engineering follow-ups — 2026-11-12

This note records the collector follow-ups after
`eafe7d8b6e1352b233c8856a8bd81faa99396a4b` on Draft PR #1007. The older
[retention audit](bounded_retention_followups_2026-11-11.md) records the preceding
checkpoint. These are persistence and offline diagnostic changes, not new native
measurements or scientific admission.

The collector source SHA-256 is
`f27b724bf6434d97cdd611cd2ad3a05c09daece8b307a5a53d76c78fa0e45eb2`;
`scripts/test_onesar_refmac.py` is
`e680388600c6bb7342eaf9d50272b090cde38692397e766b0555421b8dac3127`.
Function and test names below refer to those exact files.

## Implemented contracts

### Direct keyword-file retention (#1045)

`scripts/onesar_refmac.py::_write_new_regular_file_text` still creates the direct
`refmac_keywords.txt` leaf. It checks the root/ancestors before opening, requests
exclusive no-follow creation and close-on-exec where available, and requests mode
`0o644` subject to umask. It compares the opened regular descriptor with a
pre-write no-follow leaf observation, writes UTF-8 through a complete `os.write`
loop, handles partial/no-progress writes, and calls `fsync`. Only `EINVAL` and
`ENOTSUP` fsync errors are tolerated.

It attempts to close the owned descriptor in `finally`. A secondary close
`OSError` is attached to an existing primary exception without replacing that
primary; a close-only `OSError` propagates. Simultaneous secondary non-`OSError`
interruption precedence is outside this correction. Failure cleanup never
unlinks/removes the created leaf or a foreign replacement. This is distinct from
JSON retained-temporary receipts: no JSON cleanup/history fields are fabricated.

After close it checks the pathname digest and a final no-follow leaf identity
against the originally opened inode. The root/ancestor guard is not repeated
there. These are point-in-time observations, not atomic publication,
descriptor-relative parent traversal, original-descriptor hashing, or a guarantee
against swap-away-and-back or future replacement.

`TestRefmacCollectorFirstSlice.test_direct_text_writer_retains_owned_and_foreign_entries`
uses owned files and injected boundaries to check retention, actual descriptor
closure, partial writes, primary/close errors, fsync errors, observed replacement
identity and collector keyword-stage failure before the fake runner. The
historical sensitivity witness renames the created leaf, installs a foreign
marker during fsync, and raises the same EIO: the old helper deletes that marker,
while the candidate retains both entries. Candidate-only `os.write`/`os.close`
hooks do not intercept historical file-object I/O; those misses are not historical
proof.

### Optional scan observations (#1050)

`_scan_refmac_directory_entries` preserves unavailable child facts as `None` in
the optional no-admitted-baseline path. It records parent observations separately,
distinguishes an unattempted child lookup from an attempted failure, preserves
actual refusal causes, and avoids extra readlink work on these symlink refusals.
`_build_scan_refusal_result` preserves explicit regular-file booleans and does not
turn unknown type into false or infer type from permission bits. Parent lookup
`ValueError` joins the structured refusal path; the child lookup's exception
boundary remains narrower. This does not claim general malformed-path handling
or immunity to concurrent in-place changes.

The owned fixtures are
`test_scan_refmac_directory_entries_no_baseline_observations` and
`test_scan_refmac_directory_entries_nullable_refusal_observations_task_968`.
They cover their named parent/child absence, refusal, type and healthy paths;
review corrections #1285/#1286 retain the actual refusal boundary, and the later
#1050 correction preserves an observed regular file as true.

### Readback interruption ordering (#1273)

`_atomic_write_new_json_file` records the readback error, distinct observed close
error and already-observed cleanup errors before invoking interruptible temporary
finalization. It publishes conservative directory status and a partial receipt
with expected versus observed readback fields kept separate. Pending temporary
handling remains `None`; strict handling classifiers reject it.

An escaping finalizer interruption carries the preliminary metadata, and the
outer cleanup still attempts owned directory-descriptor closure. Later close
metadata enriches the active exception/status snapshot. The original readback
exception's preliminary receipt need not contain that later enrichment. No
durable diagnostics/manifest pair or universal interrupt guarantee is asserted.

The new owned fixture is
`test_atomic_writer_readback_error_preserved_before_finalizer_interrupt`, checked
alongside
`test_atomic_writer_and_history_verifier_final_leaf_temp_ownership_and_close_boundaries`
and
`test_atomic_write_new_json_file_saved_partial_accounting_and_postlink_readback_or_namespace_loss`.
Review correction #1287 made the fixtures use the actual baseline/receipt APIs
and observable close boundaries rather than counting setup errors as coverage.

### Saved fallback pair (#1157)

In `test_late_publication_first_d0_and_m0_child_write_failures`, F2 keeps the actual
writer receipt dictionary so later parent provenance enrichment remains visible.
It compares saved M1's complete diagnostics reference with that receipt, reopens
D1 through the saved reference with digest/size checks, and compares the complete
payload with the public failure payload. F1 and F2 retain their separate factory
counts and failure paths. These added assertions pass on both historical and
current sources; they strengthen coverage rather than prove a historical failure.

## Offline replay and scientific limits

The new discovered `test_onesar_attempt04_contract_replay.py` suite (#1284) runs the
existing hash-pinned `ref/research/1sar_attempt04_contract_assessment/replay_bins.py`
and `replay_export.py` in isolated Python children, checking their fixed outputs
and refusal boundaries. `check_onesar_attempt04_membership.py` and its test suite
add a fixed-fixture, hash-pinned membership/word consistency check. These are
bounded diagnostics; successful replay does not admit a producer, population,
bin convention, R reconstruction or model representation.

The [scientific decision note](1sar_rerun_2026_11_12_scientific_decisions.md)
separates established Attempt 04 facts, unselected policies and missing witnesses.
All 105 retained raw files in the four Attempt 01–04 roots named
`data/coscientists/openscientist/retained_1sar_pr1007_R4_rfactors_attempt01`
through `retained_1sar_pr1007_R4_rfactors_attempt04`, and all 830 protected tracked
data files across `data/` and `ref/research/data/`, are preserved. Historical receipts and scientific
criteria remain unchanged: only the limited historical Gate 2 is true; other
gates and all canary/batch/EVAL/QDS eligibility remain false. No native execution,
issue closure or merge is part of this change.

## Local verification checkpoint

PRIMARY used the locked benchmark-extra Python 3.12.11 environment, with native
and external process launches blocked for focused fixtures. These are local
checkpoint results, distinct from the final full gate and remote CI. The scan
and readback focused receipts use earlier candidate snapshots; the expanded
collector-class result covers the final source/test hashes printed above:

| Scope | Candidate checkpoint result | Historical sensitivity at eafe7d8 |
| --- | --- | --- |
| Optional scan: 2 methods | 33 subcases pass | 25 assertion failures and one missing `lookup_attempted` KeyError after the intended FIFO events; later assertions in failing subcases were not reached. |
| Readback/finalizer: 3 methods | 28 subcases pass | Four missing-cleanup-sink failures after actual interruption/context/owned-file/FD checks; later exact receipt assertions were not reached. |
| Direct text and F2: 2 methods | 11 subcases pass | The fsync replacement witness demonstrates destructive old cleanup; candidate-only hooks are not historical evidence. F2 passes both versions. |
| Expanded collector class | 64 methods, 301 subcases pass | Current integration control, not a historical comparison. |
| Contract replay suite | 6 methods pass | Existing pinned recipes, isolated Python children and owned negative controls. |
| Membership suite | 9 methods pass | Public pinned positive plus owned inconsistency controls; no native child. |

Current focused/class runs had no failures, errors or skips; correctness Ruff
checks passed. Before commit, PRIMARY must also run the required locked Python
3.12 benchmark-extra `scripts/validate.sh` gate and explicit
`scripts/test_slides_2026_11_06.py` suite, then verify both validate jobs on the
pushed exact head. Those later receipts belong to the PR checkpoint, not to an
unperformed claim in this note.

## Review and correction record

Each finding was filed or deduplicated before its in-scope correction; issue
resolution here means corrected on the branch, not closed or merged.

- #1285/#1286: optional-scan refusal causes and parent lookup exception handling.
- #1287: actual readback fixture APIs and close/receipt assertions.
- #1288–#1294: real trace-envelope API; canonical binary32 decoding; C1/carrier
  consistency; contextual missing slots; actual MTZ HKL identity; strict integer
  metadata; and the fixture's unbound loader identity. All corrected and reviewed.
- #1295–#1302: scientific-note dataset claims, native-bin facts, model identities,
  decision-menu separation, F3 formula/premise, exact numerical ledger, unselected
  R representation, and export-witness scope. The corrected note also addresses
  duplicated findings on #1190, #1193, #1194, #1200, #1201, #1148 and #1199.
- #1303–#1306: the first engineering-audit draft was rejected for inaccurate source locations,
  chronology, fixture coverage and conservation paths. Its correction uses actual
  function/test boundaries and does not upgrade a successful diagnostic into
  scientific readiness.
