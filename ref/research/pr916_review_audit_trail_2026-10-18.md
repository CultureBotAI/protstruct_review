# PR #916 Review and Fix Record (`2026-11-03` to `2026-11-04`; Research Artifact Baseline `2026-10-18`)

- **Pull request:** `#916` (branch `fix-911-prosmart-rama-z`)
- **Issue scope of PR `#916`:** Addresses `#911` (ProSMART `T05_rama_z_score` capability correction, `ref/tools_and_measurements_guide.md`, and before/after refinement assessment on `1SAR` and the 22-structure control cohorts). PR `#916` does **not** resolve or close `#914` or `#915`.
- **Research artifact baseline date in filenames:** `2026-10-18`
- **Actual PR `#916` review and fix dates:** `2026-11-03` to `2026-11-04`
- **Acceptance state:** Local code, test, and documentation fixes are implemented on `fix-911-prosmart-rama-z`; final issue disposition and PR acceptance remain pending independent PRIMARY verification.

---

## 1. Commit Lineage on `fix-911-prosmart-rama-z`

| Role | Commit SHA | Date | Summary |
|---|---|---|---|
| Base on `origin/main` | `6bd461b5e9f005646431cd373e97ffad3aa5d80d` | — | Merge-base for `fix-911-prosmart-rama-z` |
| Initial reviewed PR `#916` head | `1d760a97efc7b9f9fd80f9d469eadc4409299372` | `2026-11-03` (reviewed) | Initial PR `#916` implementation reviewed in Task 001 (`.orchestration/reports/001-review-911.md` and `.orchestration/reports/001-review-911-corrected.md`) |
| Task 002 Commit 1 (code/JSON/tests) | `7acc7ce84ae4337334b0e48e3f581fb851a4f582` | `2026-11-03` | Updated `scripts/assess_refinement.py`, regenerated `ref/research/data/refinement_assessment_1sar_and_controls_2026-10-18.json`, and updated `scripts/test_assess_refinement.py` |
| Task 002 Commit 2 (docs/tests) | `169b5e3aefaa160f4b60f2570bf7f95ea911f338` | `2026-11-04` | Initial updates to `ref/tools_and_measurements_guide.md`, `ref/research/refinement_assessment_case_study_2026-10-18.md`, `ref/research/pr916_review_audit_trail_2026-10-18.md`, and `scripts/test_tools_and_measurements_guide.py` |
| Task 003 Commit 3 (`#920` code/tests) | `d896f28f9842776998a8470c59299dd8d1a31e52` | `2026-11-04` | Completed `#920` source-admission, semantic context, deposited-header, and non-finite guards in `scripts/assess_refinement.py` and `scripts/test_assess_refinement.py` (accepted by PRIMARY for Task 003) |
| Task 004 Phase A Commit 4 (docs) | Current `HEAD` on `fix-911-prosmart-rama-z` | `2026-11-04` | Replaced this audit record (`#926`), updated `ref/research/refinement_assessment_case_study_2026-10-18.md` (`#937`), and completed Phase A source-grounded corrections for task sections `T01`, `T02`, `T03`, `T04`, `T06`, `T08`, `T09`, `T12`, and `T13` (plus intro/matrix attribution) in `ref/tools_and_measurements_guide.md`; task sections `T05`, `T07`, `T10`, `T11`, `T14`, `T15`, `T16`, and `T17` remain scheduled for Phase B |

---

## 2. Provenance Boundary: Recomputed Archive Quantities vs Retained Historical Scalars

`scripts/assess_refinement.py` is a deterministic offline replay and recount tool; it does not invoke licensed PHENIX, CCP4 (`REFMAC5`, `ctruncate`, `aimless`), `Servalcat`, `gemmi sfcalc`, or standalone `MolProbity` executables at runtime.

1. **Directly recomputed from retained archive and repository bytes:**
   - Atom, residue, water, and non-water heterogen inventories and `REMARK 3` headers from `data/coscientists/openscientist/cdba2c07-daff-4f60-ae96-12452b3a5fbb_artifacts.zip` (`data/1sar.pdb`, `data/1sar_final.pdb`, `data/1sar_round5.pdb`, `data/1sar_round6.pdb`) and `data/pdb_mtz/1sar_deposited.pdb`.
   - Unsuperposed and Kabsch-superposed coordinate and $B$-factor displacements across the `1,493` shared non-hydrogen atoms (`1,488` protein + `5` in `A:97:SO4`) and `192` shared $C_\alpha$ atoms (`compare_pdb_pair()` and `kabsch_rmsd()`).
   - Reflection-column retention between `data/1sar.mtz` and `data/1sar_final.mtz` (`audit_mtz_retention()` via `scripts/t03_reflection_retention.py`: `6,494` positive-$F$ work reflections and `723` `R-free-flags == 1` reflections preserved; `11` zero-$F$ work reflections converted to `NaN`; `14` all-`NaN` HKL rows appended).
   - Saved `T13` log parsing and observation/header equivalence in `data/coscientists/openscientist/retained_evidence_2026-09-23/coordinate_and_t13_audit.json` (produced by `scripts/audit_1sar_retained_evidence.py`).
   - Five 22-structure control cohort summaries replayed from `ref/research/data/negative_control_round3_bench.json`, `ref/research/data/negative_control_round4_recover.json`, and `ref/research/data/negative_control_round10_recover.json`.
2. **Cross-checked against retained YAML records without raw historical oracle outputs:**
   - Historical `1SAR` oracle scalars in `data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-09-23.yaml` and `data/coscientists/openscientist/QDS_1sar_cdba2c07_2026-09-23.yaml` are verified by SHA-256 digest and semantic context in `assess_1sar_case_study()` (`_require_eval_measurement_map()`, `_require_qds_claim_audit_map()`, `_require_eval_numeric()`, `_require_eval_text()`, `_require_qds_numeric()`, `_assert_close()`).
   - As recorded in `data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-09-23.yaml:4277–4284,5015–5020,5081–5087,5102–5108,5145–5152`, several historical `1SAR` entries (including the starting-to-packaged PHENIX $R$-factor delta `0.3334 / 0.3956 -> 0.1564 / 0.2116`, historical `REFMAC5` `0.1693 / 0.2128`, `Servalcat` `0.1705 / 0.2209` on `n_work = 6,855` / `n_free = 362`, historical `MolProbity` `3.63`, `mmtbx.validation_summary` `3.13`, and Holton `refinement_check.py` `3.32 -> 1.33 σ`) are transcriptions from earlier evaluation reports whose original raw oracle outputs are unavailable and whose matched reflection/free-set selection across historical runs is not independently established.

---

## 3. Canonical Registry and Code Identifiers Verified on Branch

- **ProSMART `T05_rama_z_score` capability correction (`#911`, `#924`):**
  - `ref/tool_recommendations.yaml:2067–2070`: `REC_T05_rama_z_score_top_performing_2026_10_18_capability_correction` (`tool_ref: ProSMART`, `metric_ref: T05_rama_z_score`, `role: deprecated`, superseding `REC_T05_rama_z_score_top_performing`).
  - `ref/tool_assumptions.yaml:766–823`: `ASSUM_prosmart_reference_dependent_2026_10_18` (`status: mitigated`, superseding `ASSUM_prosmart_reference_dependent`) and `ASSUM_prosmart_no_top8000_default_2026_10_18` (`status: mitigated`, superseding `ASSUM_prosmart_no_top8000_default`).
  - Live QDS v4 admission guard: `scripts/qds_emit_contract_v4.py` and `scripts/test_qds_live_admission.py`.
- **Canonical metric vs criterion IDs (`#926`):**
  - `T01_ca_rmsd_å` is the canonical metric ID in `ref/catalog.yaml` (`metric_definitions`), whereas `T01_ca_rmsd` is a structural criterion ID in `ref/structural_criteria.yaml:537`.

---

## 4. Issue Disposition Summary (`#917`–`#944`)

| Issue | Scope | Implementation Commit(s) | Status |
|---|---|---|---|
| `#917` | Control-cohort baseline matching (`ISOT` vs `ANIS`, CIF hash check, per-metric `count` / `unavailable_count`) in `scripts/assess_refinement.py` | `7acc7ce84ae4337334b0e48e3f581fb851a4f582` | Implemented; awaiting PRIMARY verification |
| `#918` | `resolve_verdict_status()` rejects non-empty `pass_criterion_bindings` and unknown statuses in `scripts/assess_refinement.py` | `7acc7ce84ae4337334b0e48e3f581fb851a4f582` | Implemented; awaiting PRIMARY verification |
| `#919` | Full `64`-hex archive SHA-256 verification and `coordinate_and_t13_audit.json` cross-check in `scripts/assess_refinement.py` | `7acc7ce84ae4337334b0e48e3f581fb851a4f582` | Implemented; awaiting PRIMARY verification |
| `#920` | 1SAR source-admission SHA-256 digests, semantic context checks, deposited `REMARK 3` header guards, and strict non-finite JSON rejection in `scripts/assess_refinement.py` | `7acc7ce84ae4337334b0e48e3f581fb851a4f582`, `d896f28f9842776998a8470c59299dd8d1a31e52` | Implemented (accepted by PRIMARY for Task 003) |
| `#921` | `1SAR` resolution metadata (`49.972–2.500 Å` MTZ / packaged header vs `1.80 Å` deposited) and `Asn39` (`1sar:A:39`) outlier identity | `7acc7ce84ae4337334b0e48e3f581fb851a4f582`, `169b5e3aefaa160f4b60f2570bf7f95ea911f338` | Implemented; awaiting PRIMARY verification |
| `#922` | `deposition_applicability(None)` preserves `deposition_clause: "unevaluable"` on `1SAR` without substituting `REFMAC5` $R_{\text{free}}$ | `7acc7ce84ae4337334b0e48e3f581fb851a4f582`, `169b5e3aefaa160f4b60f2570bf7f95ea911f338` | Implemented; awaiting PRIMARY verification |
| `#923` | `unchanged_null` solver-conflict target identities (`2VXN`, `9TXE`) in `scripts/assess_refinement.py` and case study | `7acc7ce84ae4337334b0e48e3f581fb851a4f582`, `169b5e3aefaa160f4b60f2570bf7f95ea911f338` | Implemented; awaiting PRIMARY verification |
| `#924` | Live v4 QDS admission rejects deprecated `ProSMART` `T05_rama_z_score` (`scripts/qds_emit_contract_v4.py`, `scripts/test_qds_live_admission.py`) | `1d760a97efc7b9f9fd80f9d469eadc4409299372` | Verified on branch; awaiting PRIMARY verification |
| `#925` | `scripts/test_tools_and_measurements_guide.py` validates full backticked `T\d{2}_[^`]*` tokens and task `applicable_task_refs` | `169b5e3aefaa160f4b60f2570bf7f95ea911f338` | Implemented; awaiting PRIMARY verification |
| `#926` | Factual PR `#916` review/fix record with November 3–4 dates, exact commit hashes, real identifiers, and provenance boundaries | Task 004 Phase A commit | Implemented in Phase A; awaiting PRIMARY verification |
| `#927` | Remove unbacked threshold/calibration numbers and false `ref/threshold_evidence_status.yaml` `literature_consensus` attributions in `ref/tools_and_measurements_guide.md` | Task 004 Phase A commit (Phase B remaining) | Phase A complete for `T01`, `T02`, `T03`, `T04`, `T06`, `T08`, `T09`, `T12`, `T13` + intro/matrix; `T05`, `T07`, `T10`, `T11`, `T14`, `T15`, `T16`, `T17` scheduled for Phase B; awaiting PRIMARY verification |
| `#928` | Source-grounded benchmark descriptions for `T01`, `T03`, `T04`, `T05`, `T15`, and `T16` in `ref/tools_and_measurements_guide.md` | Task 004 Phase A commit (Phase B remaining) | Phase A complete for `T01`, `T03`, `T04`; `T05`, `T15`, `T16` scheduled for Phase B; awaiting PRIMARY verification |
| `#929` | Accurate `scripts/t17_restraint_summary.py` XML bin/count scope and `1D3Z`/5-ensemble cutoff-spread statistics in `ref/tools_and_measurements_guide.md` | Scheduled for Task 004 Phase B | `T17` scheduled for Phase B; awaiting PRIMARY verification |
| `#930` | Accurate `scripts/checkmymetal_local.py` (`INNER_SPHERE_CUTOFF = 3.20` and absolute per-element `b_in_range`) description in `ref/tools_and_measurements_guide.md` | Scheduled for Task 004 Phase B | `T10` scheduled for Phase B; awaiting PRIMARY verification |
| `#931` | Accurate `T14` `mmtbx.reduce2` flip-conflict suspension (`policy_state: suspended`, `evidence_state: producer_mismatch`) and void heterogen H-count status in `ref/tools_and_measurements_guide.md` | Scheduled for Task 004 Phase B | `T14` scheduled for Phase B; awaiting PRIMARY verification |
| `#932` | Null `mmtbx_bond_rmsz` / `mmtbx_angle_rmsz` provenance boundary in `scripts/assess_refinement.py` and case study | `7acc7ce84ae4337334b0e48e3f581fb851a4f582`, `169b5e3aefaa160f4b60f2570bf7f95ea911f338` | Implemented; awaiting PRIMARY verification |
| `#933` | Multi-factor framing of `round 4` vs `round 10` recovery cohorts in `scripts/assess_refinement.py`, case study, and guide | `7acc7ce84ae4337334b0e48e3f581fb851a4f582`, `169b5e3aefaa160f4b60f2570bf7f95ea911f338` | Implemented; awaiting PRIMARY verification |
| `#934` | Separate retained-archive MTZ column recounts from historical `1SAR` tool reflection/free-set selection and raw-output availability in `scripts/assess_refinement.py`, case study, and guide | `7acc7ce84ae4337334b0e48e3f581fb851a4f582`, `169b5e3aefaa160f4b60f2570bf7f95ea911f338`, Task 004 Phase A commit | Implemented (`T03` updated in Phase A); awaiting PRIMARY verification |
| `#935` | `damaged_dynamics` REFMAC `zBOND` vs cctbx geometry divergence noted in `scripts/assess_refinement.py` and case study | `7acc7ce84ae4337334b0e48e3f581fb851a4f582`, `169b5e3aefaa160f4b60f2570bf7f95ea911f338` | Implemented; awaiting PRIMARY verification |
| `#936` | Explicit `status: "unavailable"` (`count: 0`, `unavailable_count: 22`) for `post_*_r_free` when only `d_*` deltas are retained | `7acc7ce84ae4337334b0e48e3f581fb851a4f582`, `169b5e3aefaa160f4b60f2570bf7f95ea911f338` | Implemented; awaiting PRIMARY verification |
| `#937` | Accurate `scripts/gemmi_rfactor.py` two-MTZ (`nbins=20`) contract vs `scripts/screen_round1.py` `gemmi sfcalc` producer chain and offline `scripts/assess_refinement.py` replay | Task 004 Phase A commit | Implemented in Phase A (`T03`, `T06`, matrix, case study); awaiting PRIMARY verification |
| `#938` | External `scripts/toolchain.py` paths for `reduce`/`probe`, absence of `gemmi validate` subcommand, and global-protein-mean $B$ scope in `scripts/audit_1sar_retained_evidence.py` | Task 004 Phase A commit (intro; `T05`/`T10`/`T14` in Phase B) | Intro layer updated in Phase A; `T05`, `T10`, `T14` scheduled for Phase B; awaiting PRIMARY verification |
| `#939` | Offline `scripts/t16_interface_quality.py` vs opt-in `scripts/bench_t16_bsa_vs_pisa.py` PISA API path, and per-residue `T01_per_residue_displacement` vs aggregate `scripts/assess_refinement.py` shift summaries | Task 004 Phase A commit (`T01`; `T16` in Phase B) | `T01` updated in Phase A; `T16` scheduled for Phase B; awaiting PRIMARY verification |
| `#940` | Respect `REC_T06_overall_b_top_considered_2026_09_27_capability_correction` (deprecated/undefined `T06_overall_b`; do not substitute mean atomic $B$ or Wilson $B$) | Task 004 Phase A commit | Implemented in Phase A (`T06`, matrix); awaiting PRIMARY verification |
| `#941` | Distinguish per-residue `FSC-Q` (`T12_local_model_map_fsc_q`) from per-atom `MapQ` (`T12_q_score`) | Task 004 Phase A commit | Implemented in Phase A (`T12`, matrix); awaiting PRIMARY verification |
| `#942` | Match `T13` local integration prose to `scripts/t13_data_quality.py` parsed/emitted fields (`T13_wilson_b`, `T13_anisotropy_δb_aniso`, `T13_l-test_twinning`, `T13_tncs_flag`, `T13_ice-ring_flags`) | Task 004 Phase A commit | Implemented in Phase A (`T13`, matrix); awaiting PRIMARY verification |
| `#943` | Accurate `ASSUM_servalcat_refine_xtal_actually_refines` (`servalcat refine_xtal_norefmac`) and retained `--ncycle 0` benchmark command provenance | Task 004 Phase A commit | Implemented in Phase A (`T03`, `T06`); awaiting PRIMARY verification |
| `#944` | Separate `mmtbx.validation.{ramalyze,rotalyze,cbetadev}` (`cctbx` family) and deposited wwPDB validation reproduction from standalone `reduce` + `probe` clashscore and torsion-only `OpenStructure`/`gemmi` inspection | Task 004 Phase A commit (`T04`; `T05` in Phase B) | `T04` updated in Phase A; `T05` scheduled for Phase B; awaiting PRIMARY verification |

---

## 5. Executed Validation Commands

The following commands are executed in the locked Python 3.12 `benchmark` environment (`uv run --locked --extra benchmark`):

```bash
uv run --locked --extra benchmark -- python scripts/test_tools_and_measurements_guide.py
uv run --locked --extra benchmark -- python scripts/test_assess_refinement.py
uv run --locked --extra benchmark -- python scripts/test_qds_live_admission.py
uv run --locked --extra benchmark -- bash scripts/validate.sh
```
