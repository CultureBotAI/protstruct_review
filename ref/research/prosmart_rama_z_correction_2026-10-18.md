# ProSMART Ramachandran-Z capability and assumptions audit — 2026-10-18

Resolves: [#911](https://github.com/CultureBotAI/protstruct_review/issues/911)
Base: `main` at `922fae212f1dff41a1b4727bbb7cc13dce043a66` (PR #912)
Task branch: `fix-911-prosmart-rama-z`

## Summary of defect and scope

During the 2026-10-17 review of `ref/quality_reporting.md` and its sibling registries, [#911](https://github.com/CultureBotAI/protstruct_review/issues/911) identified an unverified capability attribution in the active tool-recommendation and assumption registries:

1. `ref/tool_recommendations.yaml::REC_T05_rama_z_score_top_performing` (and the section comment at lines 500–505) recommended `ProSMART` as `top_performing` (`rank: 1`) for `T05_rama_z_score`, asserting that ProSMART *"computes a non-cctbx per-residue Ramachandran-Z score — exactly this metric"* and citing `Nicholls2014`.
2. `ref/tool_assumptions.yaml::ASSUM_prosmart_reference_dependent` and `ASSUM_prosmart_no_top8000_default` described a reference-dependent *"ProSMART Rama-Z"* and contrasted it with MolProbity's Top8000 reference distribution (suggesting Top8000 might be supplied via ProSMART data files).

This audit verifies the metric definition, the cited primary source, the retained 1SAR evaluation records, and the repository's executable/artifact state, and applies dated, append-only registry corrections while preserving all historical rows and frozen `EVAL_*` / `QDS_*` snapshots byte-identically.

## Evidence and verification boundary

### 1. Catalog and schema definition of `T05_rama_z_score`

- `ref/catalog.yaml` defines `T05_rama_z_score` (`name: Rama-Z score`, `applicable_task_refs: [T05]`) under Task `T05` (`Geometry validation`). Task `T05.oracle_tool_refs` lists `wwPDB validation pipeline` (alongside `MolProbity (gold)`, `gemmi validators`, `gemmi rmsz`, `RosettaHoles2`, `ProSA`, `Verify3D`, and `protstruct retained-coordinate audit`), not `ProSMART`. `ProSMART` appears only under `T02.oracle_tool_refs` (`Per-residue structural comparison`).
- `schemas/protstruct_review.yaml` (`GeometrySummary.ramachandran_z_score`, routed from `T05_rama_z_score` in `scripts/qds_emit.py` and `scripts/qds_emit_contract_v*.py`) defines `ramachandran_z_score` as *"Ramachandran Z-score (distribution match vs high-resolution reference); typical acceptable range -3 to +3"* (the Sobolev et al. 2020 / Tortoize / wwPDB validation pipeline distribution statistic).
- `ref/tool_recommendations.yaml::REC_T05_rama_z_score_top_considered` already assigns `wwPDB validation pipeline` (`role: top_considered`, `rank: 1`) as the canonical source for `T05_rama_z_score`.

### 2. Primary source (`Nicholls2014`) and comparative observable

- The sole citation on `REC_T05_rama_z_score_top_performing`, Nicholls et al. (2014), *"Conformation-independent structural comparison of macromolecules with ProSMART"*, *Acta Cryst.* D70, 2487–2499 (`Nicholls2014`), defines local backbone fragment comparison between a target chain and an explicit reference chain (`-p1` / `-p2`):
  - **Procrustes score**: minimum local backbone coordinate RMSD (Å) of a sliding fragment window of length $n$ (typically 9 residues) between target and reference after rigid-body superposition of that fragment.
  - **Flexible score** and **Hinging score**: local conformational change diagnostics derived from the aligned fragment windows.
  - **Central-atom distance**: post-superposition displacement of the central residue's Cα atom within the aligned fragment window.
- `Nicholls2014` does not define or compute a single-model Ramachandran distribution Z-score (`T05_rama_z_score`) against a high-resolution reference distribution, nor does it classify Ramachandran outliers against Top8000 contours.

### 3. Retained 1SAR evidence and local environment boundary

- The only retained ProSMART numbers in the repository come from the historical 1SAR evaluation (`prosmart -p1 data/1sar_final.pdb -p2 data/1sar.pdb` in `data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-04-24.yaml`):
  - `EVAL_1sar_cdba2c07_2026-04-24_M_prosmart_global_rmsd`: fragment-alignment RMSD `0.475` Å (`T01_ca_rmsd_å`).
  - `EVAL_1sar_cdba2c07_2026-04-24_M_prosmart_asn_a39_score`: `Procrustes score 0.5262 (avg 0.27-0.40); MaxDist 1.313 Å; hinge 12°` on `1sar:A:39`, originally misfiled under `T05_per_residue_rsrz`.
- In the retained 2026-09-23 correction (`data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-09-23.md` and `EVAL_1sar_cdba2c07_2026-09-23.yaml`, rows `EVAL_1sar_cdba2c07_2026-09-23_CORR_SCALAR_062` and `EVAL_1sar_cdba2c07_2026-09-23_CORR_SCALAR_063`), both rows were explicitly withdrawn from `T01_ca_rmsd_å` and `T05_per_residue_rsrz` because fragment-based Procrustes displacement between `data/1sar_final.pdb` and `data/1sar.pdb` is a pairwise structural-comparison observable, not RSRZ, Ramachandran classification, or a Ramachandran-distribution Z-score.
- A gitignore-independent search (`rg --no-ignore --hidden` and `find` across the repository) confirms that no raw ProSMART output tables, wrapper scripts, or benchmark drivers are retained in the workspace.
- On the current workstation, the configured CCP4 9.0.015 path (`/Applications/ccp4-9.0.015-shelx-arpwarp-macosarm/ccp4-9/`) is not installed (`scripts/toolchain.py` reports `prosmart` unavailable). In accordance with the issue's evidentiary boundary, this audit does **not** infer solely from an old manual that an uninspected installed ProSMART build could never contain extra analysis modes. Rather, the registry correction rests on two established facts:
  1. No verified ProSMART command, output field, or retained execution in this repository produces the catalog's `T05_rama_z_score` (`ramachandran_z_score`) observable.
  2. ProSMART's documented and retained Procrustes, Flexible, and Hinging scores (`Nicholls2014`) are pairwise structural-comparison statistics against a comparator structure and must not be reinterpreted as Ramachandran-Z scores.

## Registry and documentation changes

| File | Change | Historical preservation |
|---|---|---|
| `ref/tool_recommendations.yaml` | Append `REC_T05_rama_z_score_top_performing_2026_10_18_capability_correction` (`role: deprecated`, `tool_ref: ProSMART`, `as_of_date: '2026-10-18'`, `effective_at: '2026-10-18T00:00:00+00:00'`, `supersedes_recommendation_ref: REC_T05_rama_z_score_top_performing`); update the section comment at lines 500–506 to note the supersession. | `REC_T05_rama_z_score_top_performing` and `REC_T05_rama_z_score_top_considered` (`wwPDB validation pipeline`) remain byte-identical. |
| `ref/tool_assumptions.yaml` | Append `ASSUM_prosmart_reference_dependent_2026_10_18` (`supersedes_assumption_ref: ASSUM_prosmart_reference_dependent`) and `ASSUM_prosmart_no_top8000_default_2026_10_18` (`supersedes_assumption_ref: ASSUM_prosmart_no_top8000_default`) with `as_of_date: '2026-10-18'` and `effective_at: '2026-10-18T00:00:00+00:00'`, replacing the `"ProSMART Rama-Z"` / Top8000 framing with ProSMART's actual reference-dependent comparative fragment scores (`-p1`/`-p2`). | `ASSUM_prosmart_reference_dependent` and `ASSUM_prosmart_no_top8000_default` remain byte-identical for historical QDS snapshots (`QDS_1sar_cdba2c07_2026-05-01.yaml`, `2026-05-04`, `2026-05-05`, `2026-09-23`). |
| `ref/oracle_tools.md` | Clarify the CCP4 ProSMART table entries so ProSMART is described as a reference-dependent Procrustes per-residue comparative tool (`T02`) rather than an active `T05` geometry or `T05_rama_z_score` validator, noting that `ProSMART`'s `T05` entry in `ref/catalog.yaml::tools` is retained solely for historical `tool_ref` resolution on the 2026-04-24 1SAR record. | Preserves `ref/catalog.yaml::tools` historical task resolution and all frozen `EVAL_*` / `QDS_*` files. |
| `scripts/test_prosmart_capability_recommendations.py` | Add hermetic tests verifying predecessor byte-identity, `as_of_date` / `effective_at` cutoff filtering in `qds_emit` and `qds_emit_contract_v1` across both `build_tool_recommendations_applied` and `build_assumptions_report`, microsecond issue-time boundary behavior, referential integrity, and prose alignment. | Runs inside `scripts/validate.sh` with no external binaries. |
