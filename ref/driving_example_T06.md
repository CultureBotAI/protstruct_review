# Driving example — T06 Model-vs-data statistics

Standalone per-task driver for **T06 (model-vs-data statistics)**. Follows the structure of
`ref/driving_example.md`. Graded by **cross-tool agreement**: an independent R-factor / CC
re-derivation must corroborate PHENIX, with the deposition-header values as tiebreaker.

> **Thresholds are defined once** in `ref/thresholds_and_standards.md`; the `[provenance]` tags below
> point into it.

## Scenario

The agent is handed a model + experimental data (MTZ for X-ray, or half-maps for cryo-EM) — the model
is treated as fixed — and asked to report R-work, R-free, correlation coefficients, and B-factor
statistics from a fresh re-derivation (not read from a refinement log).

## Dataset — concrete IDs

- **X-ray:** PDB `1YQV` + deposited MTZ.
- **Cryo-EM:** PDB `7a4m` + EMDB-`11668` half-maps.

## What the agent must do

1. Run `phenix.model_vs_data model.pdb data.mtz` (X-ray) / `phenix.mtriage` (cryo-EM).
2. Record R-work, R-free, CC_work, CC_free, CC*, overall/Wilson B (X-ray); map-model FSC, d_FSC_model
   (cryo-EM).
3. Expected artefacts: the model_vs_data / mtriage report.

## Independent cross-checks (harness, not agent)

- **`gemmi sfcalc`** — independent R-factor / CC re-derivation (different bulk-solvent + shell binning).
- **Servalcat** (`fsc`, `sigmaa`) — independent per-shell R / FSC.
- Deposition header — the reported R-values / resolution are the tiebreaker.

## Scoring rubric

Each bullet is pass/fail; all must pass for green.

1. **R tracks the deposition.** PHENIX R-work/R-free within **± 0.02** of the deposited values.
   `[catalog — R-free vs deposited]`
2. **Independent-code-path R-work offset.** With the same model, MTZ, work set and cctbx mask radii,
   the directly summed `gemmi sfcalc` R-work must satisfy the registry's absolute agreement envelope.
   The benchmark observed gemmi above PHENIX in 15/15 cases, so a non-positive offset is an
   investigation flag, not an automatic failure. The benchmark does not govern R-free offsets or
   `gemmi_rfactor.py`'s additional bin-rescaled estimator. `[benchmark — registry §3]`
3. **Model treated as fixed.** T06 re-derives statistics from a fixed model — no refinement. If the
   reported R differs materially from a `phenix.model_vs_data` re-run, the number came from a
   refinement log, which is not the T06 metric. `[handbook — phenix.model_vs_data]`
4. **Deposition-header sanity (cryo-EM).** d_FSC_model on the deposited model is within **0.10 Å** of
   the EMDB-header resolution — a pipeline calibration check. `[calibration]`

## Notes

- Unlike T03, T06 does not refine; it grades whether the agent's fixed-model statistics reproduce
  under an independent code path and match the deposition.
