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

Each clause is pass, fail, or unevaluable; all clauses must pass for green.
Missing required evidence is unevaluable, not a pass or an automatic scientific failure.

1. **R-free tracks the deposition.** Apply the registry's deposited-reference tolerance and
   retain the separate REFMAC5 re-refinement comparison on matched data. Missing deposited R-free
   makes this clause unevaluable even when REFMAC5 is available; neither REFMAC5 nor a recomputed
   DCC value supplies the absent deposited reference. Report the available independent result with
   its exact subject and flag set, without making T03 green. `[registry §3 — R-free vs deposited]`
2. **Independent-code-path R-work offset.** With the same model, MTZ, work set and cctbx mask radii,
   the directly summed `gemmi sfcalc` R-work must satisfy the registry's absolute agreement envelope.
   The benchmark observed gemmi above PHENIX in 15/15 cases, so a non-positive offset is an
   investigation flag, not an automatic failure. The benchmark does not govern R-free offsets or
   `gemmi_rfactor.py`'s additional bin-rescaled estimator. `[benchmark — registry §3]`
3. **Input observations and R-free flags retained.** Use registry §3's input-defined retention
   domain, not raw MTZ row-count equality or a surviving HKL intersection. Select F/SIGF/flag columns
   explicitly; retain finite F including zero and negative values, with finite positive SIGF.
   Missing or malformed flags on otherwise eligible input make the audit unevaluable, not a
   smaller passing subset. Declare the flag encoding/free value and match HKL/indexing context.
   Report missing input HKLs, observations invalidated at surviving keys, changed observations or
   flags, newly usable output keys, and separately counted excluded/padding rows. The read-only
   `scripts/t03_reflection_retention.py` helper implements the unchanged-input check for its
   explicitly supported merged-amplitude MTZ format: explicit `VALM NAN`, complete zero-batch
   `NCOL`, and no unmerged column/header markers. Unsupported input is unevaluable.
   `[registry §3 — T03 applicability and reflection-retention policy]`
4. **Geometry did not degrade.** clashscore and Ramachandran favored stay within the refinement
   Δ-tolerances (registry §4); MolProbity vs PHENIX clashscore agree within the registry §3 envelope — |Δ| ≤ 1.0, or 20 % of
   the mean, whichever is larger, with a matched H-build convention and hydrogens from the same
   `reduce` binary and version (an H-convention mismatch is void, not failed; record each tool's H convention and
   `reduce` version). Clashscore version pin: PHENIX 2.0-5936, Richardson reduce 4.16.250520 (both builds), and standalone probe 2.26.021123. Other or unverified versions are informational pending a matched benchmark, not a threshold pass or fail.
   Matching versions alone does not validate changed H-build settings (#799/#790). `[registry §3 — clashscore]`

## Notes

- The gradeable signal is that an independent refiner and an independent R-calc *agree* with the
  agent, not that R-free is low — an over-fit model with a suspiciously low R-free fails rule 1.

These definitions do not rewrite or automatically regrade issued EVAL/QDS records. The new
retained-byte recount in `ref/research/t03_reflection_policy_2026-09-27.md` finds that the 1SAR
outputs retain every input HKL and flag but invalidate eleven finite zero-amplitude input
observations. Their extra all-NaN rows do not explain or excuse that loss. This is not a new
refinement run, and the missing deposited R-free still prevents a complete T03 result.
