# 1SAR Instrumented REFMAC Build 633 and Collector Pre-Launch Audit (`2026-11-09`)

## 1. Scope and Historical Pre-Launch Boundary

This note records the pre-launch audit trail for the separate instrumented REFMAC `5.8.0431` diagnostic build (`build633`) and the diagnostic collector integration at commit `7174cafb6663130c252128fb1c0c812d7b78a853`, following `ref/research/1sar_rerun_2026_11_08_instrumented_attempt04_preregistration.md`.

As of this audit, the single preregistered instrumented run on subject `R4` (`Attempt 04`, target root `data/coscientists/openscientist/retained_1sar_pr1007_R4_rfactors_attempt04`) has **not** executed. All 84 retained files across the three prior attempts (`14` in Attempt 01, `33` in Attempt 02, and `37` in Attempt 03) remain untouched. No PHENIX execution, refinement run, control run, or additional native probe was performed in this milestone.

## 2. Separate Vendor Source, Build 633, and Portable Evidence Layout

The diagnostic producer was built from upstream CCP4 REFMAC `5.8.0431` commit `be25e793829952f4f177d7dfd0c10a1eb6bbd180` in isolated source and build directories linked against the installed CCP4 libraries and macOS `Accelerate`, leaving the installed CCP4 tree unmodified:

- **Stock installed `refmac5` SHA-256:** `493f382202cdd6a62946d143c2a3fe675b346bef35b9b435ab008f7314bd48b4`
- **Diagnostic `refmac5` (`build633`) SHA-256:** `4f4c7045c73a9c2c725746b3d8ab73adbb98a2f6379b5493e9422d8da65db89b`

Hook preparation (`scripts/prepare_refmac_diagnostic.py`, `scripts/refmac_diagnostic/trace_writer.f90`, `scripts/refmac_diagnostic/trace_hooks.f90`) verified original vendor files against `scripts/prepare_refmac_diagnostic.py::PINNED_ORIGINAL_FILE_SHA256` and introduced read-only `intent(in)` emission hooks without modifying native arithmetic, reflection selection, resolution binning, or scaling within the audited source scope. This audit does not claim behavioral equivalence with the stock binary, runtime mapped-image proof, atomic filesystem guarantees, or an independently reproducible third-party build.

Portable review artifacts are retained under `data/coscientists/openscientist/retained_evidence_2026-11-08_refmac-diagnostic-build633`:

- `data/coscientists/openscientist/retained_evidence_2026-11-08_refmac-diagnostic-build633/source/refmac_diagnostic_source_manifest.json` and `data/coscientists/openscientist/retained_evidence_2026-11-08_refmac-diagnostic-build633/source/refmac_diagnostic_hooks.patch`
- `data/coscientists/openscientist/retained_evidence_2026-11-08_refmac-diagnostic-build633/build/build-receipt.json` and `data/coscientists/openscientist/retained_evidence_2026-11-08_refmac-diagnostic-build633/build/toolchain-inventory.json`
- `data/coscientists/openscientist/retained_evidence_2026-11-08_refmac-diagnostic-build633/index.json`

Copied receipts preserve original workstation absolute paths and timestamps byte-for-byte; `index.json` records the source-to-retained copy mapping rather than rewriting embedded paths. Full vendor source trees, build objects, local installation directories, and executable binaries remain local on the workstation; the committed directory is portable review evidence, not a runnable installation.

## 3. Collector Wiring, Review Findings, and Bounded Fixes (`7174caf`)

Diagnostic collector support (`scripts/onesar_refmac.py`, `scripts/refmac_diagnostic_profile.py`, `scripts/refmac_diagnostic_trace.py`, `scripts/onesar_records.py`) enforces:

1. **Raw-first post-launch capture (`#1184`):** `scripts/onesar_refmac.py::run_refmac_rfactor_operation` inspects and hashes raw outputs (`XYZOUT`, `HKLOUT`, `XMLOUT`, `refmac.log`, `refmac_native_trace.jsonl`) via `scripts/onesar_refmac.py::_inspect_output_artifact` before running `scripts/refmac_diagnostic_profile.py::recheck_profile` or `scripts/refmac_diagnostic_trace.py::inspect_native_trace_envelope`.
2. **Role and environment binding (`#1163`):** Preflight binds the 8 ordered `collector_helpers` modules (`scripts/onesar_refmac.py::_verify_diagnostic_collector_helper_role_join`), sets child activation (`REFMAC_DIAGNOSTIC_TRACE` and `DYLD_PRINT_LIBRARIES=1`), and rejects inherited loader/override variables.
3. **Cause and progress fidelity (`#1185`):** Original primary exceptions (`primary_cause` and `__cause__`) are preserved when later postflight audits also fail. Unexpected trace-reader exceptions record `null` progress (`event_count: null`, `bytes_read: null`, `partial_sha256: null`, and `operation_checks.native_trace_event_count: null`). By contrast, integer `0` is recorded for the event count (`event_count: 0` and `operation_checks.native_trace_event_count: 0`) when the reader is skipped or when a trace is genuinely closed with zero events: a skipped reader on a missing or unreadable raw trace records `bytes_read: 0` with `null` prefix/observed digests (`partial_sha256: null`, `observed_sha256: null`), whereas a genuinely closed zero-event trace retains its positive header/footer `bytes_read` and actual observed byte size and SHA-256 digest.
4. **Non-promotion (`schema_version = 2`):** Diagnostic runs emit `schema_version = 2` and `collector_stage = "instrumented_native_trace_capture_v1"`, set all `canonical_eval_qds_eligible`, `eval_admission_eligible`, `qds_admission_eligible`, `canary_admission_eligible`, `scientific_admission_proven`, `batch_execution_eligible`, and `all_preregistered_gates_passed` flags to `False`, and are rejected by `scripts/onesar_records.py::verify_retained_refmac_rfactor_evidence`.

Bounded pre-launch review caught and resolved collector source defects in `scripts/onesar_refmac.py`—`#1163` (collector helper role join), `#1184` (raw-first output observation ordering before postflight profile and trace audits), and `#1185` (reader-owned progress in `scripts/onesar_refmac.py::_inspect_retained_native_trace_envelope` and `null` unknown event-count projection in `scripts/onesar_refmac.py::_populate_post_checkpoint_status_fields` and nested `scripts/onesar_refmac.py::_derive_final_collection_outcome`)—as well as test, fixture, and lint defects in `scripts/test_onesar_refmac_diagnostic.py` (`#1182` fixture/API/assertion/coverage corrections and `#1183` unused test imports). Both the collector source defects and the test/fixture/lint defects were caught and verified using synthetic unit tests and inert controls; no native REFMAC run was executed. Inherited concurrent directory-replacement exposure remains an open follow-up (`#1050`); no atomic directory guarantees are claimed.

## 4. Validation, Runtime Configuration, and Intact Scientific Gates

Accepted validation covers 12 diagnostic unit tests (`scripts/test_onesar_refmac_diagnostic.py`), 41 legacy collector tests (`scripts/test_onesar_refmac.py`), and 6 independent inert controls—each recording 0 denied operations in its guarded Python execution receipt—alongside separate passing Ruff checks and a passing locked Python 3.12 (`--extra benchmark`) hermetic gate (`scripts/validate.sh`) that verified all 917 inventoried input hashes unchanged (including the then-untracked `scripts/test_onesar_refmac_diagnostic.py`):

- `data/coscientists/openscientist/retained_evidence_2026-11-08_refmac-diagnostic-build633/qc/collector781-focused-01/result.json` (12 diagnostic + 41 legacy guarded Python tests passing with empty denial arrays / 0 denied operations; Ruff passed separately outside the Python test guard)
- `data/coscientists/openscientist/retained_evidence_2026-11-08_refmac-diagnostic-build633/qc/collector781-independent01/results.json` (6 independent inert controls passing, with empty denial arrays / 0 denied operations)
- `data/coscientists/openscientist/retained_evidence_2026-11-08_refmac-diagnostic-build633/qc/full-qc639-01/result.json` (hermetic `scripts/validate.sh` pass with all 917 inventoried inputs unchanged, recorded on parent `HEAD` `47569d52c54323af56d1a7bd1d9c3a9d06f0f426` over identical working-tree bytes before committing `7174cafb6663130c252128fb1c0c812d7b78a853`; remote CI on the new commit is not yet claimed)
- `data/coscientists/openscientist/retained_evidence_2026-11-08_refmac-diagnostic-build633/qc/runtime-configuration-03.json` (read-only binding of the configured CCP4 resolver, 2 setup scripts, and 7 static library dependencies; static dependency identity does not establish runtime loaded-image coverage, which remains `not_assessed`)

Per `ref/research/1sar_rerun_2026_11_07_hydrogen_policy.json` (`#1104`), native defaults `MAKE HYDR All` and `MAKE HOUT No` remain in force: riding hydrogens contribute to internal structure factors while `XYZOUT` coordinates omit generated hydrogens, so output hydrogen counts do not prove internal active scatterer membership. All R-factor, HKL, bin, model, and dataset gates remain intact; `#1109`–`#1112` await the single prospective `Attempt 04` trace capture and offline audits, with no inferred native bins, fitting, tolerance changes, retries, or batch runs permitted before an eligible canary.
