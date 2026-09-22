# Driving example — T03 Reciprocal-space refinement (X-ray)

Standalone per-task driver for **T03 (reciprocal-space refinement, X-ray)**. Follows the structure of
`ref/driving_example.md`. Graded by **cross-tool agreement**: an independent refiner (REFMAC5) and an
independent R-factor re-derivation must corroborate the agent's PHENIX refinement, with the deposited
R-values as tiebreaker.

> **Thresholds are defined once** in `ref/thresholds_and_standards.md`; the `[provenance]` tags below
> point into it.

## Scenario

The agent is handed a starting model + reflection data (MTZ with F/SIGF + R-free flags) and asked to
refine in reciprocal space and report R-work, R-free, the R-free − R-work gap, and post-refinement
geometry.

## Dataset — concrete IDs

- **Primary:** PDB `1YQV` + its deposited MTZ (a PHENIX refinement tutorial target).
- **Second:** any PDB-REDO entry (supplies model + public MTZ + a re-refined comparator).

## What the agent must do

1. Run `phenix.refine model.pdb data.mtz` (keeping the deposited R-free flag set untouched).
2. Record R-work, R-free, the gap, ΔR-free vs input, plus clashscore / Ramachandran favored %.
3. Expected artefacts: refined PDB, `.log`, `.geo`.

## Independent cross-checks (harness, not agent)

- **REFMAC5 (CCP4)** — independent maximum-likelihood refiner; a short re-refinement (or `NCYC=0` for
  in-place R-factors) gives an independent R-free.
- **`gemmi sfcalc`** — independent R-factor re-derivation from model + data (different code path).
- **MolProbity standalone** — independent geometry after refinement.

## Scoring rubric

Each bullet is pass/fail; all must pass for green.

1. **R-free tracks the deposition.** The agent's R-free is within **± 0.02** of the deposited value
   and of a REFMAC5 re-refinement. `[catalog — R-free vs deposited]`
2. **Independent-code-path R-work offset.** With the same model, MTZ, work set and cctbx mask radii,
   the directly summed `gemmi sfcalc` R-work must satisfy the registry's absolute agreement envelope.
   The benchmark observed gemmi above PHENIX in 15/15 cases, so a non-positive offset is an
   investigation flag, not an automatic failure. The benchmark does not govern R-free offsets or
   `gemmi_rfactor.py`'s additional bin-rescaled estimator. `[benchmark — registry §3]`
3. **R-free flags untouched.** Reflection count and R-free flag column match the input — regenerated
   flags silently break cross-validation. `[handbook — phenix.refine R-free flag set]`
4. **Geometry did not degrade.** clashscore and Ramachandran favored stay within the refinement
   Δ-tolerances (registry §4); MolProbity vs PHENIX clashscore agree within **± 1.0**. `[template]`

## Notes

- The gradeable signal is that an independent refiner and an independent R-calc *agree* with the
  agent, not that R-free is low — an over-fit model with a suspiciously low R-free fails rule 1.
