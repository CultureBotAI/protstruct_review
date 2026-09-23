# Driving example — T10 Ligand fitting

Standalone per-task driver for **T10 (ligand fitting)**. Follows the structure of
`ref/driving_example.md`. Assesses density significance with independent evidence and reports
ligand-pose comparisons against an identified deposited reference. Pose comparisons are
informational until a ligand-specific criterion and its preconditions are registered.

> **Thresholds are defined once** in `ref/thresholds_and_standards.md`; the `[provenance]` tags below
> point into it.

## Scenario

The agent is handed a model + map/data + a ligand to fit into difference density, and asked to place
the ligand and report its fit and pose.

## Dataset — concrete IDs

- **Primary:** a deposited protein–ligand complex + its MTZ (the deposited ligand pose is the
  reference), e.g. any PDB-REDO ligand entry.

## What the agent must do

1. Run `phenix.ligandfit` / `phenix.ligand_pipeline`.
2. Record ligand RSCC, RSR, ligand-B vs surroundings, protein–ligand H-bond count, and RMSD to the
   deposited ligand pose.
3. Expected artefacts: the fitted ligand + report.

## Independent cross-checks (harness, not agent)

- **EDSTATS** — independent per-ligand real-space correlation (RSCC) and RSR.
- **`gemmi` script** — independent ligand B-factor comparison and RMSD to the deposited pose.
- **MolProbity `probe`** — independent protein–ligand contact / H-bond count.

## Scoring rubric

Rule 1 assesses density significance when its evidence is available. Rules 2–4
are informational/interpretability checks, not standalone numeric quality grades.
A passing density check alone is not a complete ligand-quality or correct-pose verdict;
the uncalibrated pose criterion remains an explicit assessment gap.

1. **Ligand fits the density (accuracy).** EDSTATS real-space difference-density Z-score **RSZD**
   is within **±3σ** (no significant misplaced-atom or unexplained-density outlier), and the
   observed-density Z-score **RSZO** is above **~1σ**. These are the B-factor-independent metrics;
   RSCC/RSR have no resolution-independent significance criterion (Tickle 2012). `[literature — real-space density fit]`
2. **RSCC is corroboration-only.** Cross-tool interpretation requires a **matched limiting-radius
   convention**. Matching radii does not establish a fixed agreement tolerance or a quality cutoff;
   retain the comparison as informational under registry §2. `[literature — real-space density fit]`
3. **Pose comparison vs deposited (informational).** Record the exact model/reference, matched
   ligand atom mapping, symmetry-equivalent atom handling, and coordinate/alignment frame.
   Measure the ligand displacement in a common receptor frame; separately fitting the ligand
   itself measures conformation, not binding-site pose. Independent agreement on an RMSD
   confirms the calculation, not a correct pose. No ligand-specific tolerance is registered;
   do not transfer registry §3's Cα-superposition calibration to ligand atoms.
4. **B-factor sanity.** The ligand's mean B relative to its surroundings is recorded — a ligand B far
   above its contacts signals a fit into noise even at acceptable RSCC.

## Notes

- Density significance and pose must both be assessed: a ligand can have high RSCC in the wrong
  orientation (rule 3), or sit in a plausible pose with weak density (rule 1). High RSCC alone does
  not establish either conclusion.
