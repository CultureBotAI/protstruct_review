# Driving example — compare → refine → RMSD (T01 + T04 + T05 + T06)

Worked end-to-end rote task that exercises structure superposition (**T01**), real-space refinement against a map (**T04**), geometry validation (**T05**), and model-vs-data statistics (**T06**). This is the template; per-task driving examples (`driving_example_T<NN>.md`) will follow the same structure for the rest of the catalog.

## Scenario

The agent is handed:

1. A **reference** deposited model + cryo-EM map (the "ground truth").
2. A **candidate** model — a perturbed or agentically refined variant of the reference.

The agent must compare the candidate to the reference, refine the candidate against the map, and report whether the refinement improved things.

## Dataset — concrete IDs

- **Reference model:** PDB `7a4m` (apoferritin, 1.22 Å cryo-EM reconstruction).
- **Reference map(s):** EMDB-`11668` full map + two half-maps (for FSC).
- **Candidate model:** perturbed variant of `7a4m` produced by one of:
  - rigid-body jitter (random rot/trans ≤ 1.0 Å / ≤ 3°) applied with `gemmi transform`, **or**
  - AlphaFold model `AF-P02794-F1` (human ferritin-H) positioned by `phenix.dock_predicted_model`, **or**
  - the deposited model with every B-factor reset + 5% of side-chains randomised to the next-most-populated rotamer.

The perturbation recipe is deterministic (fixed random seed) so regression runs are reproducible. Pick one of the three depending on what dimension the evaluation run is stressing (registration / topology / stereochemistry).

## What the agent must do

### Step 1 — Compare candidate vs reference (T01)

- Run `phenix.superpose_models fixed=reference.pdb moving=candidate.pdb output=candidate_sup.pdb`.
- Record CA RMSD, all-atom RMSD, number of aligned residues.
- Expected output artefacts: `candidate_sup.pdb`, `superpose_models.log`.

### Step 2 — Refine candidate against the map (T04)

- Run `phenix.real_space_refine candidate_sup.pdb reference.map resolution=1.22 output.prefix=candidate_rsr`.
- Expected artefacts: `candidate_rsr_real_space_refined_000.pdb` (or similar), `.log`, `.geo`.

### Step 3 — Re-measure post-refinement RMSD (T01 again)

- Re-run `phenix.superpose_models` with the refined model as `moving`.
- Record **ΔRMSD = RMSD_pre − RMSD_post**. For a good refinement, ΔRMSD should be ≥ 0 (refinement pulled the model *towards* the reference) and within a sensible range (not collapsing to zero via over-fitting).

### Step 4 — Geometry validation (T05)

- Run `phenix.holton_geometry_validation candidate_rsr_*.pdb`.
- Record clashscore, Ramachandran favored %, rotamer outliers, bond/angle RMSD, MolProbity-style composite.
- Also run the independent oracle — **MolProbity** (standalone CLI `molprobity.molprobity` or the web server) — on the same model. Record the same metrics from MolProbity.

### Step 5 — Model-vs-data statistics (T06)

- Run `phenix.model_vs_data candidate_rsr_*.pdb reference.map` (for EM) / `phenix.mtriage` on the half-maps with the refined model as input.
- Record CC_mask, CC_box, CC_peaks, map-model FSC at 0.5 (d_FSC_model).

### Step 6 — Independent cross-checks (the evaluation part)

The harness (not the agent) independently runs:

- **ChimeraX `matchmaker`** on reference vs refined candidate → independent CA RMSD.
- **Servalcat** on refined candidate + half-maps → independent CC/FSC.
- **MolProbity standalone** → independent clashscore / Ramachandran / rotamer metrics.

## Scoring rubric

Each bullet is a pass/fail check. All must pass for the task to be marked green.

1. **Tool invocations in correct order.** superpose → refine → superpose → validate → model_vs_data. Agent logs must show this sequence (simple grep on the conversation / tool-call trace).
2. **All expected output artefacts present.** `candidate_sup.pdb`, `candidate_rsr_*.pdb`, `*_real_space_refined.log`, validation report, model_vs_data report.
3. **Cross-tool RMSD agreement.** PHENIX `superpose_models` CA RMSD vs ChimeraX `matchmaker` CA RMSD on the same aligned atoms, **only when both report the same aligned-residue count**: |Δ| ≤ **0.03 Å**. `[registry §3 — CA RMSD]`
4. **ΔRMSD sane.** RMSD_post ≤ RMSD_pre + the resolution-conditional §4 band: **+0.12 Å** (`d_min < 2.5 Å`) or **+0.25 Å** (`d_min ≥ 2.5 Å`). (Refinement must not substantially *worsen* agreement; equality is OK, improvements are bonus.) `[registry §4 — ΔRMSD]`
5. **Geometry did not degrade.** Apply the §4 **Δ clause** — favored_post ≥ favored_pre − **6 pp** (`d_min ≥ 2.5 Å`; − **0.5 pp** below); clashscore ratio_post/pre < **5×** while `1 ≲ clashscore_pre ≲ 20`; rotamer outliers_post ≤ outliers_pre + **4 pp** — **and** the separate §4 **absolute floors** (clashscore ≤ **4**, favored ≥ **97 %**, rotamer outliers ≤ **2 %**), which are quality bars, not degradation checks. `[registry §4 — geometry Δ + floors]`
6. **Map-model fit did not degrade.** CC_mask_post ≥ CC_mask_pre − the §4 band: **−0.04** (`d_min < 3.0 Å`) or **−0.06** (`d_min ≥ 3.0 Å`); d_FSC_model_post ≤ d_FSC_model_pre **× 1.05** (relative, one-sided). `[registry §4 — map-model]`
7. **MolProbity ≈ PHENIX.** MolProbity clashscore and PHENIX-reported clashscore agree within **±1.0** (or 20 % of the mean, whichever is larger), with a matched H-build convention; a mismatched convention (nuclear vs electron-cloud H) makes the comparison **void, not failed**. Both tools score the same model, so a disagreement is a pipeline difference; the clashscore difference alone does not say whether H placement, dictionaries or clash counting caused it. `[registry §3 — clashscore]`
8. **Deposition-header sanity (T06).** Reported `d_FSC_model` on the *reference* (un-perturbed) model is within **0.10 Å** of the EMDB-header resolution (a calibration check that the metric pipeline itself is sound). `[registry §5 — resolution calibration]`

Any failure → task scored red. Log which check failed, with the numeric delta that tripped it.

## Notes

- The perturbation recipe must be recorded (commit the exact CLI in a `perturb.sh` alongside the run).
- Pre-refinement baseline metrics (clashscore_pre, CC_mask_pre, RMSD_pre) are computed once by the harness at dataset-instantiation time and cached — the agent does not recompute them.
- This example is deliberately small (apoferritin, 1.22 Å) so each tool runs in minutes; regression tests can run it per-commit. Use a larger target (e.g. ribosome subunit) as a separate slow suite.
