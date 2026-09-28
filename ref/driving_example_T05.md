# Driving example — T05 Geometry validation

Standalone per-task driver for **T05 (geometry validation)**. Follows the structure of
`ref/driving_example.md`. The task is graded by **cross-tool agreement**, not by an absolute
quality bar: whether a structure is "good" is resolution-dependent and belongs to that structure,
not to this task template. What the template checks is that the agent's geometry tool and the
independent oracle agree on the same model, and that outliers are counted against the standard
outlier definitions.

Every scoring threshold carries a `[provenance]` tag naming its source, so a reviewer can audit or
adjust it. Tags: `[schema]` = a threshold committed in `schemas/protstruct_review.yaml`
(`ResidueOutlierKind`); `[MolProbity]` = the Richardson-lab Top8000 percentile standard;
`[template]` = the agreement tolerance already used in `ref/driving_example.md`; `[registry §N]` = a
row of `ref/thresholds_and_standards.md` that this driver restates and must track; `[calibration]` =
a sanity check against a deposited comparator.


> **Thresholds are defined once** in `ref/thresholds_and_standards.md`; the `[provenance]` tags below point into it.

## Scenario

The agent is handed a single model (PDB/mmCIF) and asked to validate its stereochemistry: report
clashscore, Ramachandran favored/outlier %, rotamer outlier %, Cβ deviations, and bond/angle RMSDs.
The harness independently re-runs MolProbity on the same model and checks the two agree.

## Dataset — concrete IDs

- **Primary:** PDB `3NIR` (crambin, 0.48 Å) — a clean ultra-high-resolution baseline where outlier
  counts should be near zero, so a spuriously high outlier count exposes a pipeline bug.
- **Stress model:** any moderate-resolution entry with known outliers, e.g. PDB `1SAR` (1.20 Å,
  the harness's standing test artifact), to confirm the tools agree on a model that *has* outliers.

## What the agent must do

1. Run `phenix.holton_geometry_validation model.pdb` (and/or `mmtbx.validation_summary model.pdb`).
2. Record: clashscore, Ramachandran favored %, Ramachandran outlier %, rotamer favored %, rotamer
   outlier %, Cβ outlier count, bond-length RMSD, bond-angle RMSD, MolProbity composite; and the
   rotamer library, the number of residues scored, and the H-build program, flags and convention
   (electron-cloud or nuclear), `reduce` version, whether Asn/Gln/His flips were allowed, and het
   dictionary behind the clashscore. The harness records the same for its oracle run.
3. Expected artefacts: the validation log and a parsed metrics table.

## Independent cross-checks (harness, not agent)

- **MolProbity standalone** — the Richardson-lab `probe` + `reduce` pipeline (installed; see
  `ref/oracle_tools.md`), or `molprobity.molprobity`. Re-derives clashscore, Ramachandran, rotamer,
  and Cβ independently of cctbx's own reduce build.
- **`gemmi rmsz`** — independent bond/angle restraint deviations against the CCP4 monomer library
  (its `rmsD` fields: bond lengths in Å, bond angles in degrees; `rmsZ` is dimensionless).
  `gemmi validate` does not report geometry RMSDs (`ref/oracle_tools.md`).

## Scoring rubric

Each bullet is pass/fail; all must pass for green. Log the numeric delta that trips any failure.

1. **Outliers counted against the standard definitions** (registry §1). Ramachandran outlier = φ,ψ
   outside the 99.95th percentile of Top8000; rotamer outlier = the residue-specific **OUTLIER**
   classification reported by the validation tool — **Allowed** and **Favored** conformations are not
   outliers; Cβ outlier = deviation > 0.25 Å; clash = steric overlap ≥ 0.4 Å.
   `[registry §1]` `[schema ResidueOutlierKind]` `[MolProbity]`
2. **Clashscore agreement.** PHENIX clashscore and MolProbity-standalone clashscore agree within the
   registry §3 envelope — |Δ| ≤ 1.0, or 20 % of the mean, whichever is larger — with a matched H-build
   convention and hydrogens from the same `reduce` binary and version; an H-convention mismatch (e.g. nuclear vs
   electron-cloud H) makes the comparison **void, not failed**. Both tools start from the same input
   model, so a disagreement is a pipeline difference, not a change to the model; the clashscore
   difference alone does not say whether H placement, Asn/Gln/His flips, het dictionaries or clash
   counting caused it. Clashscore version pin: PHENIX 2.0-5936, Richardson reduce 4.16.250520 (both builds), and standalone probe 2.26.021123. Other or unverified versions are informational pending a matched benchmark, not a threshold pass or fail.
   Matching versions alone does not validate changed H-build settings (#799/#790). `[registry §3 — clashscore]`
3. **Ramachandran / rotamer agreement.** Apply the classification floor in the registry §3
   favored/outlier rows only to PHENIX 2.0-5936 versus the wwPDB validation report on the same coordinate
   subject. Match `(chain, resnum, icode, resname)`; retain altloc/key-handling disclosure. Compute
   three-state Ramachandran agreement and binary rotamer OUTLIER/non-OUTLIER agreement separately,
   each with its own nonzero shared-key denominator, and name every disagreeing residue. Exact rotamer
   names are a separate diagnostic: a name difference need not change the OUTLIER verdict. Missing
   applicability evidence or a zero denominator is unevaluable, not a pass. Other versions and
   standalone MolProbity comparisons remain informational under this floor; deposited-reference
   reproduction does not establish method-independent confirmation. This documentation adoption adds
   no QDS agreement metric or PassCriterionBinding: retain QDS classification-agreement rows as informational without
   criterion metadata. **Rotamer favored %** stays a pass/fail band, |Δ| ≤ **1.0 pp**, because registry row 89 retains it: round 46
   re-scoped only the three rows it could measure against deposited reports, and this one is not
   directly measurable. The registry notes the band assumes both tools use the same rotamer library,
   and it is exposed to the same residue-count difference as the other percentages — altloc or
   completeness handling changes how many residues each tool scores — so record both counts. The other
   raw percentages are **reported diagnostics, not gates**, as round 46 registered — Ramachandran
   favored % |Δ| ≤ 0.2 pp, rotamer outlier % |Δ| ≤ 0.5 pp, Ramachandran outlier % (≤ 0.11 pp
   observed). The registry benchmarked the
   classification check as `phenix.ramalyze`/`phenix.rotalyze` vs the wwPDB validation report (round 46,
   #284). `[registry §3 — Ramachandran / rotamer favored % and outlier %]`
4. **Bond/angle RMSD agreement.** PHENIX `model_statistics` vs `gemmi rmsz` bond-length RMSD within
   |Δ| ≤ **0.008 Å** across differing restraint libraries (≤ 0.006 Å when the library matches), and
   only when both tools restrain the **same number of bonds** — otherwise report both figures, not a Δ.
   `[registry §3 — bond-length RMSD]` Bond-**angle** RMSD is restraint-library-dependent: **±0.1° only
   if both tools use the same library**, else **±0.4°** (PHENIX CDL vs gemmi Engh & Huber differ by 0.3–0.4° for library reasons
   alone). Record the restraint-library + tool versions. `[template — bond-angle RMSD]`
5. **Calibration on the clean baseline.** On `3NIR`, clashscore ≤ 2 and Ramachandran outliers = 0.
   A clean 0.48 Å structure scoring otherwise means the pipeline itself is miscalibrated, not the
   model. `[calibration — 3NIR ultra-high-res]`
6. **H-build disclosure.** If clashscore is reported, the hydrogen-addition step (`reduce -build`
   vs `phenix.reduce`), its `reduce` version, flags (including whether Asn/Gln/His flips were allowed —
   `phenix.clashscore` disables them by default), het dictionary and convention (electron-cloud or
   nuclear) must be recorded — rule 2's pass/fail/void outcome depends on them, and H construction can
   move clashscore.
   The historical 1SAR difference (3.13 cctbx vs 3.63 standalone) is not a measured builder effect:
   its cause is unresolved (`ASSUM_molprobity_h_atom_placement_2026_09_23`). Absence of the
   disclosure is a fail. `[schema/handbook — MolProbity tool assumptions]`

## Notes

- This task grades **agreement and reproducibility**, not structure quality. An intentionally poor
  model still passes T05 if both tools agree it is poor — that is the correct behaviour.
- The absolute quality thresholds for a *specific* refinement (e.g. "clashscore must improve") live
  in the compare→refine driver `ref/driving_example.md`, not here.
- Provenance tags marked `[template]`/`[calibration]` are agreement tolerances and sanity checks,
  not scientific quality claims, and are safe to tune. Tags marked `[schema]`/`[MolProbity]` are
  standard definitions — change them only if the upstream standard changes.
