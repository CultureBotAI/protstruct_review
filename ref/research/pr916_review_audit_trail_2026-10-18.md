# PR #916 Review and Fix Checkpoint (`2026-11-03` to `2026-11-04`; Research Artifact Baseline `2026-10-18`)

- **Pull request:** `#916` (branch `fix-911-prosmart-rama-z`)
- **Parent issue:** `#911` (ProSMART `T05_rama_z_score` capability correction, `ref/tools_and_measurements_guide.md`, and before/after refinement assessment on `1SAR` and the 22-structure control cohorts)
- **Review findings tracked against PR `#916`:** **30 findings** in addition to parent `#911`:
  - **27 accepted in scope:** `#917`–`#922` and `#926`–`#946`
  - **3 rejected and closed not planned:** `#923`–`#925`
- **Existing follow-ups outside PR `#916`'s closure set:** `#760`, `#765`, `#790`, `#799`, `#872`, `#873`, `#876`, `#914`, and `#915` are referenced only as existing repository context and are not resolved or closed by PR `#916`.
- **Research artifact baseline date in filenames:** `2026-10-18`
- **Actual PR `#916` review and fix dates:** `2026-11-03` to `2026-11-04`
- **Acceptance state:** `#920` was locally accepted at `d896f28f9842776998a8470c59299dd8d1a31e52` (final PR gates pending); Phase A guide correction surfaces were accepted by PRIMARY at `b5813da8113ca34039fa5f9410d82d22690d9246`; Phase B guide sections (`T05`, `T07`, `T10`, `T11`, `T14`, `T15`, `T16`, `T17`) and related matrix/synthesis text are updated in this Task 005 checkpoint (awaiting PRIMARY verification); remaining generated-report context corrections (`#934`, `#945` in Task 006), final fresh review (Task 007), and exact-head CI remain pending.

---

## 1. Prior Commit Lineage on `fix-911-prosmart-rama-z`

| Role | Commit SHA | Date | Summary |
|---|---|---|---|
| Base on `origin/main` | `6bd461b5e9f005646431cd373e97ffad3aa5d80d` | — | Merge-base for `fix-911-prosmart-rama-z` |
| Initial reviewed PR `#916` head | `1d760a97efc7b9f9fd80f9d469eadc4409299372` | `2026-11-03` (reviewed) | Initial PR `#916` implementation reviewed in Task 001 (`.orchestration/reports/001-review-911.md` and `.orchestration/reports/001-review-911-corrected.md`) |
| Task 002 Commit 1 (code/JSON/tests) | `7acc7ce84ae4337334b0e48e3f581fb851a4f582` | `2026-11-03` | Updated `scripts/assess_refinement.py`, regenerated `ref/research/data/refinement_assessment_1sar_and_controls_2026-10-18.json`, and updated `scripts/test_assess_refinement.py` |
| Task 002 Commit 2 (docs/tests) | `169b5e3aefaa160f4b60f2570bf7f95ea911f338` | `2026-11-04` | Initial updates to `ref/tools_and_measurements_guide.md`, `ref/research/refinement_assessment_case_study_2026-10-18.md`, `ref/research/pr916_review_audit_trail_2026-10-18.md`, and `scripts/test_tools_and_measurements_guide.py` |
| Task 003 Commit 3 (`#920` code/tests) | `d896f28f9842776998a8470c59299dd8d1a31e52` | `2026-11-04` | Completed `#920` source-admission, semantic context, deposited-header, and non-finite guards in `scripts/assess_refinement.py` and `scripts/test_assess_refinement.py` (locally accepted by PRIMARY for Task 003) |
| Task 004 Phase A initial commit | `8f00cd77d2d0a18d78182f40c60a16a3da871d27` | `2026-11-04` | Initial Phase A documentation edits to `ref/tools_and_measurements_guide.md`, `ref/research/refinement_assessment_case_study_2026-10-18.md`, and `ref/research/pr916_review_audit_trail_2026-10-18.md` |
| Task 004 Phase A repair commit | `b5813da8113ca34039fa5f9410d82d22690d9246` | `2026-11-04` | Repaired Phase A guide, case-study, and audit-trail findings (Phase A guide surfaces accepted by PRIMARY; excluded secondary repair report retained as historical artifact only) |

---

## 2. Provenance Boundary: Recomputed Archive Quantities vs Retained Historical Records

`scripts/assess_refinement.py` is a deterministic offline replay and recount tool; it does not invoke licensed PHENIX, CCP4 (`REFMAC5`, `ctruncate`, `aimless`), `Servalcat`, `gemmi sfcalc`, or standalone `MolProbity` executables at runtime.

1. **Directly recomputed by `scripts/assess_refinement.py` from archive and repository bytes:**
   - Extracts the starting and packaged-final PDB and MTZ members (`data/1sar.pdb`, `data/1sar_final.pdb`, `data/1sar.mtz`, `data/1sar_final.mtz`) from the retained archive (`data/coscientists/openscientist/cdba2c07-daff-4f60-ae96-12452b3a5fbb_artifacts.zip`). It recomputes starting/final atom, residue, water, and non-water heterogen inventories from the PDB records, and separately parses the admitted deposited reference's (`data/pdb_mtz/1sar_deposited.pdb`) `REMARK 3` $R$-value fields for deposition applicability.
   - Recomputes starting-to-final unsuperposed coordinate and $B$-factor displacement summaries across `1,493` shared non-hydrogen atoms (`1,488` protein + `5` in `A:97:SO4`) and `192` shared $\text{C}\alpha$ atoms, plus whole-model and per-chain $\text{C}\alpha$ Kabsch RMSD (`compare_pdb_pair()` and `kabsch_rmsd()`).
   - Recomputes reflection-column retention between `data/1sar.mtz` and `data/1sar_final.mtz` (`audit_mtz_retention()` via `scripts/t03_reflection_retention.py`: `6,494` positive-$F$ work reflections and `723` `R-free-flags == 1` reflections preserved; `11` zero-$F$ work reflections converted to `NaN`; `14` all-`NaN` HKL rows appended).
   - Replays the five 22-structure control-cohort summaries from `ref/research/data/negative_control_round3_bench.json`, `ref/research/data/negative_control_round4_recover.json`, and `ref/research/data/negative_control_round10_recover.json`.
2. **Read and cross-checked from pinned retained YAML/JSON records without new oracle execution:**
   - Reads the retained EVAL (`data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-09-23.yaml`), QDS (`data/coscientists/openscientist/QDS_1sar_cdba2c07_2026-09-23.yaml`), and coordinate/T13 audit (`data/coscientists/openscientist/retained_evidence_2026-09-23/coordinate_and_t13_audit.json`) records only after checking their actual byte digests against the fixed `1SAR` bundle. The assessor parses those verified buffers and validates the context and finite values of the consumed measurements. This is source admission and retained-record checking, not new oracle execution.
   - Intermediate round 5/6 summary scalars, saved `T13` log-parsed values, and historical `1SAR` oracle observations (including starting-to-packaged PHENIX `0.3334 / 0.3956 -> 0.1564 / 0.2116`, historical `REFMAC5` `0.1693 / 0.2128`, historical bin-rescaled `gemmi` `0.1622 / 0.2136` from the retained EVAL/QDS observations rather than a current execution or proven invocation of the retained original `data/coscientists/openscientist/gemmi_rfactor.py` script, `Servalcat` `0.1705 / 0.2209` with `n_free = 362`, historical `MolProbity` `3.63`, `mmtbx.validation_summary` `3.13`, and Holton `refinement_check.py` `3.32 -> 1.33 σ`) come from those pinned retained records; as documented in `EVAL_1sar_cdba2c07_2026-09-23.yaml`, several historical oracle values are report transcriptions whose original raw outputs and effective per-tool reflection selections are not independently established.

---

## 3. Canonical Registry and Code Identifiers Verified on Branch

- **ProSMART `T05_rama_z_score` capability correction (`#911`):**
  - `ref/tool_recommendations.yaml:2067–2070`: `REC_T05_rama_z_score_top_performing_2026_10_18_capability_correction` (`tool_ref: ProSMART`, `metric_definition_ref: T05_rama_z_score`, `role: deprecated`, superseding `REC_T05_rama_z_score_top_performing`).
  - `ref/tool_assumptions.yaml:766–823`: `ASSUM_prosmart_reference_dependent_2026_10_18` (`status: mitigated`, superseding `ASSUM_prosmart_reference_dependent`) and `ASSUM_prosmart_no_top8000_default_2026_10_18` (`status: mitigated`, superseding `ASSUM_prosmart_no_top8000_default`).
  - Existing live QDS v4 admission guard: `scripts/qds_emit_contract_v4.py` and `scripts/test_qds_live_admission.py`.
- **Canonical metric vs criterion IDs (`#921`):**
  - `T01_ca_rmsd_å` is the canonical metric ID in `ref/catalog.yaml` (`metric_definitions`), whereas `T01_ca_rmsd` is a structural criterion ID in `ref/structural_criteria.yaml:537`.

---

## 4. PR `#916` Issue Ledger (`#911` + 30 Findings `#917`–`#946`)

| Issue | Actual Issue Subject | Prior Commit(s) / Surface | Current Status |
|---|---|---|---|
| `#911` | Parent ProSMART `T05_rama_z_score` capability correction, `ref/tools_and_measurements_guide.md`, and before/after refinement assessment | `1d760a97efc7b9f9fd80f9d469eadc4409299372`, `7acc7ce84ae4337334b0e48e3f581fb851a4f582`, `169b5e3aefaa160f4b60f2570bf7f95ea911f338`, `d896f28f9842776998a8470c59299dd8d1a31e52`, `8f00cd77d2d0a18d78182f40c60a16a3da871d27`, `b5813da8113ca34039fa5f9410d82d22690d9246`, Task 005 | Open parent issue; Phase B guide updated in Task 005; generated context (`006`) and final verification (`007`) pending |
| `#917` | EOF whitespace QC failure (`git diff --check`) | `7acc7ce84ae4337334b0e48e3f581fb851a4f582`, `169b5e3aefaa160f4b60f2570bf7f95ea911f338`, `d896f28f9842776998a8470c59299dd8d1a31e52`, `8f00cd77d2d0a18d78182f40c60a16a3da871d27`, `b5813da8113ca34039fa5f9410d82d22690d9246` | Locally verified on branch; must remain clean on final PR head |
| `#918` | Unsupported criterion bindings can authorize verdicts (`resolve_verdict_status()` in `scripts/assess_refinement.py`) | `7acc7ce84ae4337334b0e48e3f581fb851a4f582` | Locally verified; pending final-head review |
| `#919` | Actual archive digest (`64`-hex SHA-256) and `coordinate_and_t13_audit.json` identity check in `scripts/assess_refinement.py` | `7acc7ce84ae4337334b0e48e3f581fb851a4f582` | Locally verified; pending final-head review |
| `#920` | Fixed-source byte/context admission, deposited `REMARK 3` header guards, finite values, and strict JSON in `scripts/assess_refinement.py` | `7acc7ce84ae4337334b0e48e3f581fb851a4f582`, `d896f28f9842776998a8470c59299dd8d1a31e52` | Locally accepted by PRIMARY at `d896f28f9842776998a8470c59299dd8d1a31e52`; final PR gates pending |
| `#921` | Canonical metric namespace (`T01_ca_rmsd_å`) and task applicability in `ref/tools_and_measurements_guide.md` and `scripts/test_tools_and_measurements_guide.py` | `169b5e3aefaa160f4b60f2570bf7f95ea911f338` | Guide tokens validated; note that `scripts/test_tools_and_measurements_guide.py` checks task applicability inside `#### \`TXX\`` subsections rather than top Quick-Reference Matrix rows (tracked for Task 007 disposition) |
| `#922` | Missing deposited $R_{\text{free}}$ (`deposition_clause: "unevaluable"`) versus available resolution metadata; no final-model `REFMAC5` substitution | `7acc7ce84ae4337334b0e48e3f581fb851a4f582`, `169b5e3aefaa160f4b60f2570bf7f95ea911f338` | Locally verified; pending final-head review |
| `#923` | Alleged extra live-catalog `T05` dependency | — | **Rejected and closed not planned** |
| `#924` | Alleged missing v4 admission guard/test (`scripts/qds_emit_contract_v4.py` and `scripts/test_qds_live_admission.py` already existed as evidence for rejection) | — | **Rejected and closed not planned** |
| `#925` | Alleged stale `NEXT_TASKS.md` reconciliation defect | — | **Rejected and closed not planned** |
| `#926` | False audit facts and disposition/execution claims in `ref/research/pr916_review_audit_trail_2026-10-18.md` | `b5813da8113ca34039fa5f9410d82d22690d9246`, Task 005 | Issue table accepted at `b5813da`; lines 33/38/39 provenance descriptions updated in Task 005; awaiting PRIMARY verification |
| `#927` | Unsupported/retired quality thresholds and false calibration authority in `ref/tools_and_measurements_guide.md` | `8f00cd77d2d0a18d78182f40c60a16a3da871d27`, `b5813da8113ca34039fa5f9410d82d22690d9246`, Task 005 | Phase A sections accepted at `b5813da`; Phase B sections (`T05`, `T07`, `T10`, `T11`, `T14`, `T15`, `T16`, `T17`) updated in Task 005; awaiting PRIMARY verification |
| `#928` | False benchmark designs, populations, values, and causal narratives in `ref/tools_and_measurements_guide.md` | `8f00cd77d2d0a18d78182f40c60a16a3da871d27`, `b5813da8113ca34039fa5f9410d82d22690d9246`, Task 005 | Phase A sections accepted at `b5813da`; Phase B sections (`T05`, `T07`, `T10`, `T14`, `T15`, `T16`) updated in Task 005; awaiting PRIMARY verification |
| `#929` | NMR reference/estimator/core-mask/sensitivity and XML wrapper capability description (`T17` in `ref/tools_and_measurements_guide.md`) | Task 005 | Updated in Task 005 (`T17`, matrix); awaiting PRIMARY verification |
| `#930` | Local metal heuristic capabilities and absolute $B$ intervals (`T10` in `ref/tools_and_measurements_guide.md`) | Task 005 | Updated in Task 005 (`T10`, matrix); awaiting PRIMARY verification |
| `#931` | Hydrogen producer provenance and still-suspended/void grading scopes (`T14` in `ref/tools_and_measurements_guide.md`) | Task 005 | Updated in Task 005 (`T14`, `T05`, matrix); awaiting PRIMARY verification |
| `#932` | Unsupported cross-dictionary geometry conclusion with absent second RMSZ operand (`mmtbx_bond_rmsz` / `mmtbx_angle_rmsz`) | `7acc7ce84ae4337334b0e48e3f581fb851a4f582`, `169b5e3aefaa160f4b60f2570bf7f95ea911f338` | Locally verified; pending final-head review |
| `#933` | Multifactor historical recovery contrast (`round 4` vs `round 10`) presented as isolated causality | `7acc7ce84ae4337334b0e48e3f581fb851a4f582`, `169b5e3aefaa160f4b60f2570bf7f95ea911f338`, Task 005 | Updated in `scripts/assess_refinement.py`, case study, and `T14` guide section; awaiting PRIMARY verification |
| `#934` | Unsupported $R$-factor causes and effective-selection matching across historical `1SAR` solvers | `7acc7ce84ae4337334b0e48e3f581fb851a4f582`, `8f00cd77d2d0a18d78182f40c60a16a3da871d27`, `b5813da8113ca34039fa5f9410d82d22690d9246` | Guide (`T03`) and case-study lines 61/65/68 updated; remaining case-study table/line 67 and generated assessment/JSON context pending Task 006 |
| `#935` | Statistic-specific available/unavailable denominators across control cohorts | `7acc7ce84ae4337334b0e48e3f581fb851a4f582`, `169b5e3aefaa160f4b60f2570bf7f95ea911f338` | Locally verified; pending final-head review |
| `#936` | Unsupported baseline-plus-delta endpoints across unmatched producer/source contexts (`post_*_r_free` `unavailable`) | `7acc7ce84ae4337334b0e48e3f581fb851a4f582`, `169b5e3aefaa160f4b60f2570bf7f95ea911f338` | Locally verified; pending final-head review |
| `#937` | Gemmi `FC` consumer/producer/20-bin path (`scripts/gemmi_rfactor.py` vs `data/coscientists/openscientist/gemmi_rfactor.py` vs `scripts/screen_round1.py`) and offline assessment replay | `8f00cd77d2d0a18d78182f40c60a16a3da871d27`, `b5813da8113ca34039fa5f9410d82d22690d9246`, Task 005 | Phase A guide (`T01`, `T02`, `T03`, `T06`) accepted at `b5813da`; audit line 39 updated in Task 005; remaining case-study line 67 context queued for Task 006 |
| `#938` | Unimplemented pocket/H-bond/deposited-pose/local-$B$ capabilities attributed to audit scripts | `8f00cd77d2d0a18d78182f40c60a16a3da871d27`, Task 005 | `T06` accepted at `b5813da`; `T10` updated in Task 005; awaiting PRIMARY verification |
| `#939` | PISA API attributed to the local interface wrapper (`scripts/t16_interface_quality.py`) rather than separate benchmark (`scripts/bench_t16_bsa_vs_pisa.py`) | Task 005 | Updated in Task 005 (`T16`, matrix); awaiting PRIMARY verification |
| `#940` | Mean atomic $B$ substituted for undefined/deprecated overall-$B$ metric (`T06_overall_b`) | `8f00cd77d2d0a18d78182f40c60a16a3da871d27`, `b5813da8113ca34039fa5f9410d82d22690d9246` | Accepted by PRIMARY for Phase A guide surface (`T06`, matrix); final PR gates pending |
| `#941` | `FSC-Q` (`T12_local_model_map_fsc_q`) per-residue agreement versus `MapQ` (`T12_q_score`) per-atom resolvability | `8f00cd77d2d0a18d78182f40c60a16a3da871d27`, `b5813da8113ca34039fa5f9410d82d22690d9246` | Accepted by PRIMARY for Phase A guide surface (`T12`, matrix); final PR gates pending |
| `#942` | Actual parsed/emitted `T13` wrapper measurements in `scripts/t13_data_quality.py` | `8f00cd77d2d0a18d78182f40c60a16a3da871d27`, `b5813da8113ca34039fa5f9410d82d22690d9246` | Accepted by PRIMARY for Phase A guide surface (`T13`, matrix); final PR gates pending |
| `#943` | `Servalcat` command attribution (`servalcat refine_xtal_norefmac`) and unsupported zero-cycle equivalence claim | `8f00cd77d2d0a18d78182f40c60a16a3da871d27`, `b5813da8113ca34039fa5f9410d82d22690d9246` | Accepted by PRIMARY for Phase A guide surface (`T03`); final PR gates pending |
| `#944` | Torsion extraction and PHENIX classifiers presented as independent classification validation | `8f00cd77d2d0a18d78182f40c60a16a3da871d27`, `b5813da8113ca34039fa5f9410d82d22690d9246`, Task 005 | `T04` accepted at `b5813da`; `T05` updated in Task 005; awaiting PRIMARY verification |
| `#945` | Lost crystallographic-contact / not-biological-assembly limitation beside DockQ/CAPRI | Task 005 | `T16` guide section updated in Task 005; generated assessment/JSON context pending Task 006 |
| `#946` | Unsupported global `scripts/toolchain.py` routing claim for `OST` and `US-align` | `b5813da8113ca34039fa5f9410d82d22690d9246` | Accepted by PRIMARY for Phase A guide surface (Layer 2 intro); final PR gates pending |

---

## 5. Validation Commands

The following commands run in the locked Python 3.12 `benchmark` environment (`uv run --locked --extra benchmark`):

```bash
uv run --locked --extra benchmark -- python scripts/test_tools_and_measurements_guide.py
uv run --locked --extra benchmark -- python scripts/test_assess_refinement.py
uv run --locked --extra benchmark -- bash scripts/validate.sh
```
