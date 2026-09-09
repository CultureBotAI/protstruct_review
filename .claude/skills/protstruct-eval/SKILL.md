---
name: protstruct-eval
description: Conventions for the protstruct_review harness — the task × evaluation catalog, per-task driving examples, PHENIX tool + independent oracle pairings, and the cross-tool trust model. Use when adding or editing catalog entries, authoring a driving_example_T<NN>.md, wiring an evaluation run, choosing an oracle for a structural-biology operation, or checking the PHENIX docs mirror.
---

# Protstruct Eval Skill

<!-- catalog-state: tasks=T01–T17; count=17; drivers=17 -->

Support work on the **protstruct_review** harness — a quality-assessment framework for agentically refined or generated protein structures, built around PHENIX with cross-tool oracles for trust.

## Usage

When the user invokes `/protstruct-eval` or asks about:

- Adding/editing entries in the task × evaluation catalog
- Authoring or extending a per-task driving example (`driving_example_T<NN>.md`)
- Picking the right PHENIX tool + independent oracle pair for a structural-biology operation
- Wiring an evaluation run that respects the cross-tool trust model
- Sanity-checking the PHENIX docs mirror

…follow the conventions documented below. All paths in this skill are relative to the repo root.

The enforceable form of these conventions — the rules a code review can cite as hard violations —
lives in `CODING_STANDARDS.md` at the repo root. This handbook is the *why and how*; that file is
the *must*. Keep them in agreement.

## Trust model (load-bearing — do not violate)

Every task in the catalog is graded by **cross-tool agreement**, not by PHENIX alone. The harness re-runs critical metrics with at least one independent oracle (MolProbity, ChimeraX, REFMAC/Servalcat, TM-align, RELION, gemmi, …) and compares. The deposited PDB/EMDB entry or publication Table 1 is the tiebreaker.

If you are about to add a task whose only oracle is another PHENIX tool, stop — find an external oracle or call out explicitly that none exists.

## Tool assumptions (implicit and explicit)

Every oracle in this harness rests on assumptions that determine what it sees and what it misses. Surface them in the eval `notes:` field whenever a measurement is borderline; bake them into the QDS narrative when they materially change a verdict.

### MolProbity / probe / reduce
- **Reference distribution.** Top8000 is built from high-resolution (≤ 2.0 Å) structures. Applying its percentile thresholds to a 3.0 Å model is implicit — the percentile is still computed but the outlier definition was set against tighter geometry than the model can deliver.
- **H-atom placement.** `reduce -build` does its own Asn/Gln/His flips and adds H atoms with default bond-length and rotamer choices. Different H-builds can shift clashscore by ~0.5 (we saw 3.13 cctbx vs 3.63 standalone on 1SAR — same model, different H placement). Do not equate "matches MolProbity" with "matches a fresh reduce + probe run" without saying so.
- **Water and altloc handling.** `probe`'s default `ogt33` water filter and altloc selection determines which atoms can clash. Quote the flags used.
- **Rotamer library.** Rotamer outliers use a discrete library; a side-chain that is 1° outside the favored region scores as outlier. The "% outliers" number is sharp by construction; flag clusters near boundaries in `notes`.

### `phenix.refine` (in-run R-factors)
- **Bulk-solvent and anisotropic scaling.** In-run R-work / R-free use a particular bulk-solvent model and overall scale that minimise during refinement. They are NOT the same numbers `phenix.model_vs_data` produces from a fresh re-derivation. The 1SAR eval shows this gap routinely at 0.01–0.015 R-units.
- **R-free flag set.** Assumes the test set is fixed and untouched. If the agent regenerated R-free flags between rounds, cross-validation is broken silently. Compare reflection counts and column labels at every round when in doubt.

### `phenix.model_vs_data`
- **Same bulk-solvent / scaling code path as `phenix.refine`** in principle, but a separate full re-derivation. Catalog T06 oracle of record. Treats the model as fixed; not a refinement.

### `gemmi sfcalc` + custom R calc
- **Bulk-solvent fit is simpler** than PHENIX's. The script we ship (`gemmi_rfactor.py`) does flat-bulk + bin-wise isotropic rescaling, no anisotropic correction. Expect 0.005–0.015 higher R-work than PHENIX even on identical data. That's the price of an independent code path.
- **Resolution shells are linearly binned** by the calc script — different from PHENIX's adaptive shells.

### TM-align / TM-score
- **TM-score normalisation** defaults to "length of chain 1" (the first input). Swapping arguments swaps the normaliser. Always state which reference was first.
- **Sequence-independent.** Treats only Cα geometry; ignores sequence identity. For near-identical structures this gives an optimistic alignment that LSQ would not produce.
- **Optimal Cα selection.** TM-align drops Cα pairs from the score that are too far apart, by design. The `Aligned length` field tells you how many were used.

### `gemmi align`, ChimeraX `matchmaker`, PyMOL `super` / `cealign`
- Each picks a different objective (sequence-aware vs structure-only, iterative vs single-pass). Two tools "agreeing within 0.1 Å" is a guarantee about the score, not the alignment — they may have aligned different residues to get there.

### Servalcat (`sigmaa`, `fofc`, `refine_xtal_norefmac`)
- **Per-shell R uses Murshudov-group sigma-A weighting** with bins set by reflection count. The "overall R" surfaced in QDS is a per-shell weighted mean, not a separately-cross-validated R-work / R-free.
- **`refine_xtal_norefmac` runs a full refinement** when invoked — the resulting R-factor is *not* a cross-check of the agent's model in place; it's a re-refined model's R-factor. Cite both numbers explicitly when reporting.

### `phenix.holton_geometry_validation`
- **Restraint library version.** Reports σ-units against PHENIX's internal restraint targets. RMSZ ≠ raw RMSD; "small RMSD" can still be high RMSZ if restraints are tight. Always state which.
- **Geometry-energy ratio** is computed against the library's expected distribution. Resolution-aware? No — the metric is library-aware, not data-aware.

### `phenix.find_peaks_holes`
- **Peak threshold (σ cutoff)** controls what's reported. Default 4.0 σ; lowering surfaces noise, raising hides real peaks. The 1SAR oracle run found 23 positive + 8 negative peaks at 4 σ — agent's report listed 9, suggesting a different cutoff (or a peak-merging radius) was used.
- **Peak-merging radius** can collapse multi-atom features into one entry.
- **Atom exclusion.** Peaks within X Å of modelled atoms are typically excluded. The agent's report describes peaks BY their nearest atom — implying their tool did NOT exclude near-atom peaks. Different exclusion = different counts.

### lDDT
- **Distance inclusion radius** (default 15 Å) determines what counts as "local". Smaller radius rewards local fidelity, larger rewards extended geometry.
- **Tolerance thresholds** (0.5 / 1 / 2 / 4 Å) are baked in — comparing two lDDT scores produced by different code paths requires verifying the same thresholds.

### CCP4 `aimless` and `ctruncate` (T13 data-quality oracle)
- **`aimless` requires unmerged intensities** (M/ISYM column). On a merged-only MTZ (e.g. F-obs / SIGF-obs only — the 1SAR case) it aborts immediately with `hkl_unmerge_list::prepare - EMPTY`. CC½, ⟨I/σ⟩ outer, and Rmerge / Rmeas all flow from unmerged data and are **unobtainable** if the artefact does not ship it. Document this as a known gap rather than substituting unrelated metrics.
- **`ctruncate` is the merged-data fallback** for the T13 metrics that *are* recoverable from amplitudes alone: Wilson B, L-test twin fraction (+ moments), ΔB anisotropy, tNCS via Patterson search, ice-ring summary. These are CCP4 / non-cctbx and close the T13 cross-tool gap when aimless can't run.
- **`scripts/t13_data_quality.py`** wraps both: it tries aimless first (so the limitation is captured as a provenance row), then runs ctruncate and parses out the scalars into ready-to-paste EvaluationMeasurement rows. Pass `--columns 'F-obs,SIGF-obs'` for typical phenix-refined MTZs; logs and output MTZs are persisted under `<mtz_dir>/t13_oracle_logs/` for QDS evidence_refs.
- **Twinning thresholds.** L-test fraction < 0.05 = effectively untwinned; 0.05–0.20 = mild / borderline; > 0.20 = strong. ctruncate's "first-principles operator search" is independent of the L-test and reports zero operators when the lattice/symmetry permits no twin laws.
- **Anisotropy ΔB rule of thumb.** Eigenvalue spread (max − min) < ~20 Å² on the orthogonal-coords B-tensor is acceptable for general refinement; ctruncate's "some anisotropy detect" message fires at much lower thresholds and is informational unless ΔB is large.

### wwPDB validation report
- **Percentile rankings** computed against the entire archive (and against the resolution-binned subset). Quote which one. A clashscore of 8 is 70th percentile vs all PDB but 30th percentile at 1.5 Å.

## OpenScientist agentic-framework assumptions

Specific to the way the OpenScientist agent aggregates and interprets oracle outputs in `data/coscientists/openscientist/`. These assumptions came out of the 1SAR re-measurement work; flag any of them when reviewing future OpenScientist artefacts.

### Reporting

- **R-factors are read from `phenix.refine`'s in-run log** (or from the refined MTZ's stored statistics) rather than re-derived by `phenix.model_vs_data`. The 1SAR eval shows this convention puts the published R-free 0.01–0.015 below the cross-tool oracle's value, and turns the round-7 R-free-gap claim from 0.055 (oracle) to 0.050 (agent) — exactly straddling the < 0.05 success criterion.
- **Per-round table aggregation collapses rounds.** "Round 5–6" appears as one row in the agent's report despite being two distinct refinements. The actual round 6 oracle R-free (0.207) is *better* than round 7's (0.212) — an effect the collapsed reporting hides.
- **Numeric position fields can refer to the initial placement, not the final**. The Ca²⁺ position quoted in the 1SAR report (66.611, 3.895, 13.404) is the initial placement; the final coordinates in `1sar_final.pdb` are 0.215 Å away at (66.752, 3.733, 13.397). The agent's text describes a "0.19 Å coordinate shift" elsewhere — implying the report templating fixed the *initial* coordinates as the position-of-record.
- **Water counts can come from a different stage than the deposited PDB.** Agent claimed 159 ordered waters; the final PDB has 146. This 13-water gap also accounts for the +13 total-atom discrepancy. Likely cause: counting waters at one refinement step but writing the PDB after a subsequent water-pruning step.
- **Mean B-factor is reported with rounding that hides distribution shifts.** Agent quotes `<B> = 14.6 Å²`; oracle finds `<B> = 15.98 Å²`. Δ = 1.4 Å² is small in absolute terms but exceeds the published wwPDB B-factor uncertainty bracket; it suggests a different atom subset was averaged (heavy-atom only? excluding solvent?).

### Interpretation

- **Ion identity inferred from peak height alone.** "6.5 σ peak near Asp33 = Ca²⁺" is asserted from the difference map alone. No anomalous-Fourier check, no Mg/Mn/Na elimination, no occupancy refinement that would distinguish them. Mg²⁺ would give very similar geometry. Document the inference chain in `notes` and downgrade the verdict to "consistent with Ca²⁺ — alternatives not excluded" unless an anomalous map confirms.
- **Density-peak narratives are interpretive, not measured.** "All peaks > 4 σ are explained by known features" is the agent's annotation, not an oracle-verifiable claim. The independent peak inventory found 23 positive peaks at 4 σ where the agent's table listed 9; five additional peaks above 5 σ were not surfaced. Re-run `phenix.find_peaks_holes` independently before adopting this kind of summary claim.
- **NCS effective data-to-parameter ratio is a heuristic.** "846 NCS torsion restraints effectively double the data" assumes the restraints are saturated and uncorrelated with model coordinates. The actual contribution depends on restraint weight + geometry coupling and is not a measured quantity. Agent reports 0.98 → 1.79; this is a model-assumption number, not a re-derivation.
- **Pre-refinement baseline = deposited model.** The deposited 1SAR is itself a refined product; the "Δ start → final" framing implicitly equates the deposited model with an unrefined starting point. For agentically-refined targets the proper baseline is whichever model the agent was actually given, which may or may not be the deposition.
- **Cooperative binding rationale is literature interpretation, not measurement.** "Weaker Ca²⁺ binding because of missing nucleotide cofactor" is a bona-fide structural-biology hypothesis but it's not measured by any oracle in the catalog. Treat such reasoning as inference, not a quality finding.
- **Round-7 NCS-restraint improvement claim doesn't hold by oracle.** Agent: "Round 7 reduced the gap from 0.053 to 0.050 by adding NCS torsion restraints." Oracle: round 6 gap was 0.053, round 7 gap is 0.055 — restraints increased the gap, not reduced it. Verify any "X improved Y by Z" claim with the oracle re-measurement of X-without and X-with.

### Aggregation

- **Single-model verdicts.** Agent treats the final PDB as a point estimate. No B-factor uncertainty propagation, no rotamer alternate-conformation enumeration, no map-error envelope. The QDS schema's `TypedMeasurementValue` summary stats (mean / std_dev / min / max / count) exist for this purpose — populate them when an array of values is available.
- **Geometry "0.00% Rama outliers" rounds 1 outlier to zero.** The agent's pass/fail framing treats ≤ 0.5% as 0%. The PerResidueQuality.outliers list is the antidote: surface every outlier residue id even when the rate is sub-threshold.
- **Single-tool geometry validation.** `phenix.molprobity` (the cctbx wrapper) provided the geometry numbers for the agent's report. Same code base as the refiner that minimised those restraints. Document this as `oracle_family: cctbx` and require a non-cctbx confirmation before adopting any geometry pass/fail verdict.

### How to apply these in a review

When evaluating a new OpenScientist artefact:

1. **Always re-derive R-factors** with `phenix.model_vs_data` even when the agent reports R-factors. Note the gap.
2. **Re-extract atom counts and water counts** from the deposited PDB; compare to the agent's narrative numbers.
3. **Re-run `phenix.find_peaks_holes` at 4 σ** and compare the peak inventory to the agent's table. Five-or-more peaks > 5 σ that the agent did not list is a flag.
4. **For any "X moved by Y Å" or position quote**, verify the quoted coordinates exist in the deposited PDB to within ≤ 0.05 Å.
5. **For ion identity claims**, ask whether anomalous data was used; if not, downgrade the verdict.
6. **For Δ-claims between rounds**, run the oracle on each round's PDB+MTZ (we have the MTZs in the artefact zip) and confirm the direction of change.
7. **Quote `oracle_family`** on every measurement; require ≥ 1 non-cctbx confirmation for every load-bearing finding.
8. **Run the T13 data-quality oracle** with `python scripts/t13_data_quality.py <mtz> --eval-id <EVAL-id>`. Wilson B, twinning, anisotropy ΔB, tNCS, and ice-ring flags all come from a single ctruncate pass; aimless will be tried first so the unmerged-data limitation is captured as a provenance row. Without this step the cross-tool coverage for T13 stays "open — cctbx only".

## Repo layout (the parts that matter for this skill)

```
ref/
├── README.md                       # Index + how to regen the docs mirror
├── download_phenix_docs.sh         # wget --mirror script (idempotent)
├── phenix_docs/                    # Offline PHENIX doc mirror (550+ files)
├── catalog.yaml                    # CANONICAL machine-readable catalog (LinkML)
├── tasks_and_evaluations.md        # Human-readable task catalog (T01–T17)
├── tasks_and_evaluations.tsv       # GENERATED from catalog.yaml
├── tool_recommendations.yaml       # Per-metric oracle recommendations
├── tool_assumptions.yaml           # Per-tool assumption records
├── oracle_tools.md                 # Install status + per-task oracle assignment
└── driving_example.md              # Worked end-to-end (T01+T04+T05+T06)
                                    # Template for future driving_example_T<NN>.md
schemas/protstruct_review.yaml      # LinkML schema for every record above
protstruct_review/models.py         # GENERATED by gen-pydantic from the schema
scripts/                            # qds_emit.py, validate.sh, records_to_tsv.py, …
```

## Catalog schema — both files must stay in sync

`ref/tasks_and_evaluations.tsv` columns (tab-separated; lists inside columns are pipe-separated):

| Column | Content |
|---|---|
| `id` | `T01`, `T02`, … (zero-padded, immutable once assigned) |
| `task` | One-line operation name |
| `phenix_tools` | `phenix.<tool>` entry points, pipe-separated |
| `phenix_doc_paths` | Paths under `phenix_docs/phenix-online.org/documentation/` |
| `independent_oracles` | Non-PHENIX tools that compute the same metric |
| `inputs` | Required and optional inputs |
| `metrics` | Numeric deliverables the harness records |
| `gold_standard` | Source of truth (deposition, paper, cross-tool consensus) |
| `example_dataset` | Concrete PDB/EMDB IDs so a run is reproducible |

**`ref/catalog.yaml` is canonical.** The other two are views of it:

- `tasks_and_evaluations.tsv` is **generated** — never hand-edit it. Regenerate with
  `python3 scripts/records_to_tsv.py ref/catalog.yaml --kind catalog -o ref/tasks_and_evaluations.tsv`.
- `tasks_and_evaluations.md` is **hand-written prose** carrying detail the YAML doesn't hold
  (caveats, why a tool is listed, doc-page quirks). Update it in the same edit as the catalog.

`scripts/validate.sh` enforces both: it fails if the TSV differs from a fresh regeneration, and if
any catalog task has no `### T<NN> ` section in the Markdown. That gate exists because T15–T17 once
shipped in `catalog.yaml` alone and the published views went stale without anything noticing.

**Pass criteria do NOT live in this catalog** — they live in the per-task driving-example files. The catalog is metric-shape, not thresholds.

**Per-task drivers exist for all 17 tasks (T01–T17)** (`ref/driving_example_T<NN>.md`),
plus the combined `ref/driving_example.md` (T01+T04+T05+T06). Each per-task driver grades **cross-tool
agreement**, not an absolute quality bar, and tags every rubric threshold with its provenance
(`[schema]` / `[MolProbity]` / `[literature]` / `[catalog]` / `[template]` / `[calibration]`) so a
domain reviewer can audit it. The T15/T16/T17 drivers correspond to the runnable wrappers
`scripts/t15_ss_agreement.py`, `scripts/t16_interface_quality.py`,
`scripts/t17_nmr_ensemble.py`, and `scripts/t17_restraint_summary.py`.

## Existing tasks (don't reinvent these — extend them)

| ID | Task |
|---|---|
| T01 | Structure superposition + RMSD |
| T02 | Per-residue structural comparison |
| T03 | Reciprocal-space refinement (X-ray) |
| T04 | Real-space refinement (map-based) |
| T05 | Geometry validation |
| T06 | Model-vs-data statistics |
| T07 | Predicted-model processing |
| T08 | Docking predicted/homology model into a map |
| T09 | Molecular replacement |
| T10 | Ligand fitting |
| T11 | Loop / missing-region fitting |
| T12 | Map quality assessment (cryo-EM) |
| T13 | X-ray data quality assessment |
| T14 | Hydrogen placement / protonation |
| T15 | Structural/domain classification (oracle-only — no PHENIX tool) |
| T16 | Interface and assembly quality (oracle-only — no PHENIX tool) |
| T17 | NMR ensemble/restraint validation (oracle-only — no PHENIX tool) |

T15–T17 deliberately have **no PHENIX implementation**, but their gradeable metrics are runnable
through independent oracle paths: DSSP + biotite for T15, DockQ + biotite for T16, and biotite plus
deposited wwPDB validation reports for T17. See `ref/oracle_tools.md` for versions, limitations, and
the exact wrappers.

## Driving-example convention

`ref/driving_example.md` is the template — a worked end-to-end run that exercises **T01 + T04 + T05 + T06** on apoferritin (PDB `7a4m` / EMDB-`11668`). Per-task drivers follow the filename pattern `driving_example_T<NN>.md` and the same internal structure:

1. **Scenario** — what the agent receives and is asked to do
2. **Dataset — concrete IDs** — exact PDB/EMDB/MTZ IDs (no hand-waving)
3. **What the agent must do** — numbered steps with the exact CLI invocations expected
4. **Independent cross-checks** — what the harness re-runs (NOT the agent)
5. **Scoring rubric** — pass/fail bullets with numeric tolerances; all must pass for green

Note the canonical order in the template: **compare baseline → refine → re-compare → validate geometry → model-vs-data**. The pre-refinement baseline is essential — without it ΔRMSD / ΔCC / Δclashscore are uncomputable.

## Adding a new task — exact steps

1. Pick the next free `T<NN>` ID.
2. Identify the PHENIX tool(s). Verify each name exists by `find ref/phenix_docs -name '*<tool>*'` (typo-check) and record the doc path(s) relative to `phenix_docs/phenix-online.org/documentation/`.
3. Find at least one **non-PHENIX** oracle that computes the same metric. If none exists, say so in the row and flag it for follow-up.
4. List concrete inputs (file types + optional flags), metrics, gold-standard source, and a real
   example dataset (PDB/EMDB ID, not "any structure").

   **Every task needs at least one gradeable metric, and gradeable means numeric** — a number two
   tools can disagree about. No "good fit", no bare pass/fail prose.

   A metric may be **label-valued** (a secondary-structure state, a CATH fold id, a CAPRI class)
   only when it is *descriptive content* rather than the thing being graded. Such rows must carry
   `pass_status: informational`, and the task must still have a numeric metric alongside them.
   The usual move is to grade the *agreement* between two independent labellers rather than the
   label: `T15_secondary_structure_agreement` (three-state DSSP vs an independent second assigner —
   STRIDE preferred, biotite P-SEA the runnable fallback via `scripts/t15_ss_agreement.py`) is the
   gradeable metric for T15, while the per-residue labels ride along as informational content. That is
   the trust model applied to categorical data — cross-tool agreement, expressed as a number.

5. Add the metric definition(s) to `ref/catalog.yaml` and reference them from the task's
   `metric_definition_refs`. Regenerate the TSV (step 4 of "Catalog schema" above).
6. Add the matching prose section `### T<NN> — <task>` to `tasks_and_evaluations.md` in the same commit.
   Add a `ref/tool_recommendations.yaml` row for each gradeable metric naming the oracle you'd
   actually use, and record any not-yet-installed oracle in `ref/oracle_tools.md`.
7. If this task is going to be exercised on its own, draft `ref/driving_example_T<NN>.md` using `driving_example.md` as the template.

## Loading the catalog programmatically

```python
import pandas as pd
df = pd.read_csv("ref/tasks_and_evaluations.tsv", sep="\t")
list_cols = ["phenix_tools", "phenix_doc_paths", "independent_oracles",
             "inputs", "metrics"]
for c in list_cols:
    df[c] = df[c].str.split("|")
```

## Maintaining the PHENIX docs mirror

```bash
bash ref/download_phenix_docs.sh
find ref/phenix_docs -name '*.html' | wc -l   # sanity: should be ≥ 100 (currently 252 HTML of 557 files)
```

The script is idempotent (`wget --mirror` skips unchanged files). Re-run if you suspect doc paths in the catalog are stale.

## PHENIX availability

PHENIX is **not** in conda-forge or Homebrew (verified). It must be installed from <https://phenix-online.org/download/> after academic registration. The catalog and driving examples can be authored, reviewed, and committed without a working PHENIX install — actually executing a run obviously requires one.

If a task needs a tool the agent doesn't have, the agent should declare the gap explicitly rather than fall back to a PHENIX-only oracle.

## Picking an oracle for a new measurement

When the user asks for a metric measurement (e.g. "what's the clashscore?"):

1. **Check `ref/tool_recommendations.yaml`** for the metric's `top_considered` and `top_performing` recommendations. The schema class is `ToolRecommendation` (`schemas/protstruct_review.yaml`).
2. **Run the recommended tool** (verify it's installed via `ref/oracle_tools.md`). If it's missing, run the next-ranked alternative and flag the gap.
3. **Record in the eval** which tool was used (`MeasurementValue.oracle_tool_ref`). It should match the recommendation, or the discrepancy should be noted.
4. **Cross-check against a tool from a different family.** Never let the only oracle for a measurement be a cctbx tool. The trust model in `ref/quality_reporting.md` §3 is the principle, not a courtesy.
5. If a recommendation is wrong (a tool consistently disagrees with consensus, or a new tool outperforms the recommended one), **update `ref/tool_recommendations.yaml`** — bump `as_of_date` and add a new row, don't mutate in place. Re-run `bash scripts/validate.sh` after edits.

## Quality Data Sheet — when to emit and what goes in it

A `QualityDataSheet` (schema class `QualityDataSheet`, emitter `scripts/qds_emit.py`) is the **citable, dated, immutable snapshot** of cross-tool findings for one structure. Emit one when:

- A structure has been evaluated against the catalog and you want a one-page summary downstream consumers can cite.
- A new oracle has been added and you want to publish the now-hardened findings.

The QDS holds these summary blocks (use only the ones the modality needs):

| Block | Class | When to populate |
|---|---|---|
| `identity_block` | `IdentityBlock` | always |
| `geometry_summary` | `GeometrySummary` | always (clashscore, Ramachandran, rotamer, MolProbity score, RMSZ) |
| `data_quality_summary` | `DataQualitySummary` | X-ray only — populated from `stage: all` measurements (completeness, ⟨I/σ⟩ outer, CC½ outer, R-merge/R-meas) |
| `refinement_summary` | `RefinementSummary` | X-ray only (R-work, R-free, gap) |
| `map_summary` | `MapSummary` | cryo-EM only (CC_mask, d_FSC_model) |
| `predicted_confidence_summary` | `PredictedConfidenceSummary` | predicted models only (mean pLDDT + distribution shape, PAE max, multimer-block min) |
| `pairwise_comparisons[]` | `PairwiseComparison` | one per relevant reference (deposited / starting / AlphaFold / truth) — TM-score AND lDDT mandatory pair, RMSD reported additionally |
| `per_residue_quality` | `PerResidueQuality` | populate when local/per-residue measurements exist (per-residue lDDT, displacement, RSRZ; outlier residue list; difference-density peaks; flagged regions) |
| `site_qualities[]` | `SiteQuality` | one per active site / binding site / interface / metal site. Required when a functional site or bound ligand is present |
| `packing_summary` | `PackingSummary` | when packing / B-factor-outlier indicators were measured (packing Z-score, unsatisfied buried H-bonds, per-residue B-factor outlier Z) |
| `classification_summary` | `ClassificationSummary` | T15 — secondary-structure agreement (gradeable) plus SS / domain / fold labels (informational) |
| `interface_quality_summary` | `InterfaceQualitySummary` | T16 — buried surface area, DockQ, CAPRI class. Required when any `scope=interface` measurement exists |
| `prediction_ensemble_summary` | `PredictionEnsembleSummary` | T07/T17 — ensemble convergence across predicted models. Required when any `scope=ensemble` measurement exists |
| `nmr_validation_summary` | `NmrValidationSummary` | T17 — restraint violations, ensemble precision RMSD |
| `assumptions_report` | assumption records | when a measurement's validity depends on a tool assumption that could change the verdict (schema v5) |
| `cross_tool_coverage` | `CrossToolCoverage` | always — surfaces which tool families confirmed each task |
| `tool_recommendations_applied[]` | `ToolRecommendation` | snapshot of recommendations active at issue time |
| `headline_verdict` | string | always |

## Metric scope and per-residue summary discipline

Every `MeasurementValue` declares a `scope` (overriding the canonical scope on its `MetricDefinition` if needed). The `MeasurementScope` enum has values: `complex`, `chain`, `site`, `residue`, `atom`, `dataset`, `ligand`, `domain`, `interface`, `ensemble`.

`domain`, `interface`, and `ensemble` are the T15–T17 scopes. Each has a fail-hard rule in the
emitter: a measurement at that scope implies its structured block (`ClassificationSummary`,
`InterfaceQualitySummary` / `PredictionEnsembleSummary`, `NmrValidationSummary`), and emitting the
scalar without the rows raises `QdsCompletenessError`.

For non-`complex` scopes, also set `scope_selector` (free text) so the reader can locate what was measured: e.g. `"chain A"`, `"chain A residues 30-45"`, `"Asn A 39"`, `"Ca²⁺ A 33"`, `"active site 1"`.

For per-residue / per-atom / per-chain measurements, the discipline is **store everything, surface the summary**:

- Store the full array under `PerResidueQuality.lddt_per_residue[]` (or `displacement_per_residue_a[]`, `rsrz_per_residue[]`, ...) — one `PerResidueValue` per residue.
- Surface mean / std / min / max / count on the matching scalar MeasurementValue via `TypedMeasurementValue.mean`, `std_dev`, `min_value`, `max_value`, `count`. The `value_numeric` slot conventionally holds the mean.

This way a downstream consumer can read the QDS as a one-page summary AND drill into the per-residue details when needed.

What's load-bearing per modality is documented with citations in `ref/quality_reporting.md`.

Filename: `QDS_<structure>_<artifact-short-id>_<YYYY-MM-DD>.yaml`. Same convention as `EVAL_*` per `ref/eval_naming.md`.

## Validating waters, ligands, and metals

Catalog T10 (ligand fitting) declares the metrics; the skill version below makes them an explicit checklist so an agent doesn't ship a QDS that's silent on these. Run these on every artefact that has a non-protein residue (HOH, SO4, metal ion, drug-like ligand, glycan, …).

### Per-ligand / per-metal checklist

For every Ligand record in the eval:

1. **Position vs deposited PDB** — verify quoted coordinates against the deposited final-model coordinates to within ≤ 0.05 Å (gemmi audit script). Treat > 0.05 Å as a flag — possibly the agent quoted an *initial* placement (1SAR Ca²⁺ was 0.215 Å off for exactly this reason).
2. **Density support — RSCC** — `phenix.real_space_correlation` (cctbx) and ideally a non-cctbx confirmation (`edstats` from CCP4, or `gemmi sfcalc` + custom RSCC script). Threshold: > 0.85 for ligands at typical resolutions; document any deviation in `notes`.
3. **B-factor vs surroundings** — compute the ratio `B(ligand) / mean_B(protein)`. < 1.5× = consistent with full occupancy. 1.5–3× = partial occupancy or weak binding. > 3× = very weak; investigate alternative interpretations.
4. **Coordination geometry** (metals) — inner-sphere bonds 2.0–2.6 Å for hard metals (Ca²⁺, Mg²⁺, Zn²⁺); coordination number 6–8 for Ca²⁺. Use `gemmi contact` or a small gemmi script.
5. **Element identity** (metals) — does the data type allow it to be cross-checked?
   - **Anomalous data present** (e.g. multi-wavelength MAD, peak/edge/remote) → run anomalous Fourier; check anomalous map peak height at the metal site. Tools: `phenix.anomalous_signal`, CCP4 `fft` with anomalous coefficients.
   - **No anomalous data** → element identity cannot be cross-validated by oracle. Downgrade verdict to "consistent with X — alternatives not excluded". For 1SAR's `1sar.mtz` (only F-obs / SIGF-obs / R-free flags) this is the case.
   - **CheckMyMetal web service** (<https://checkmymetal.research.uchicago.edu/>) — geometry-based heuristic check: classifies modelled element by coordination geometry against expected. No anomalous data needed; web-only, no install. Useful when the only choice is "downgrade to consistent-with" or "submit for an external sanity check".
6. **Pose RMSD to deposited reference** (small-molecule ligands) — `phenix.superpose_models` on the ligand atoms only. Threshold < 0.5 Å for "good fit" against a deposited co-crystal.
7. **H-bond network** — `gemmi contact` or PLIP. Count protein–ligand H-bonds; compare to expected for the ligand class.

### Per-water audit (whole-structure, not per-residue)

For the water set as a whole:

1. **Count** the waters in the deposited PDB (`grep -cE '^HETATM.* HOH ' final.pdb` or `gemmi residues`). Compare to agent claim — 1SAR had a 13-water gap (146 actual vs 159 reported), exactly matching the total-atom gap.
2. **B-factor distribution** — mean, std, min, max. Mean ~1.5–2× protein-mean is typical for surface waters. Flag waters with B > 60 Å² as `density_misfit` candidates.
3. **RSCC distribution** — `phenix.real_space_correlation` outputs RSCC per HOH. Expect mean ~0.85, range 0.65–0.99. Flag waters with RSCC < 0.7 as **density_misfit ResidueOutliers**. 1SAR had 3 such waters (HOH S 680, 707, 729) with RSCC 0.658–0.691.
4. **Per-water summary on the QDS** — populate `TypedMeasurementValue.mean / std_dev / min_value / max_value / count` on a single scope=complex measurement. Add `ResidueOutlier` rows for the worst N waters (not all N=146).

### Tools — what we have and what's missing

| Check | Available oracles | Gap |
|---|---|---|
| RSCC (per residue) | `phenix.real_space_correlation` (cctbx) | non-cctbx: `edstats` (CCP4, installed-but-needs-wiring), `gemmi sfcalc + sigma-A`-style scripting |
| Difference-density peaks | `phenix.find_peaks_holes` (cctbx) | non-cctbx: `gemmi blobs --diff` (installed; flag-handling quirks in 0.7.5 — emit a CCP4 `.map` from REFMAC and run on that) |
| B-factor extraction | gemmi structural audit (non-cctbx) | none |
| Coordination geometry | gemmi (non-cctbx) | none |
| Element identity (geometry-based) | none locally | **CheckMyMetal web service** (free, no install). Add as a manual step for any ion claim. |
| Element identity (anomalous-Fourier) | `phenix.anomalous_signal`, CCP4 `fft` | requires anomalous data in the MTZ |
| Pose RMSD | `phenix.superpose_models`, `gemmi align` | none |
| H-bond network | `gemmi contact` | none — additional tools (PLIP) optional |

### Schema integration

Each per-ligand check populates a `MeasurementValue` at `scope: ligand`, `scope_selector: <ligand_id>`, with the canonical T10 metric:
- `T10_ligand_rscc` → `LigandQuality.rscc`
- `T10_ligand_rsr` → `LigandQuality.rsr`
- `T10_ligand_b_vs_surroundings` → `LigandQuality.ligand_b_factor_vs_surroundings`
- `T10_protein-ligand_hbond_count` → `LigandQuality.protein_ligand_hbond_count`
- `T10_rmsd_to_deposited_ligand_pose` → `LigandQuality.pose_rmsd_to_deposited_a`

The QDS emitter joins via `Site.ligand_ref` → `LigandQuality` so every ligand bound at a Site has its quality block in `site_qualities[].ligand_quality`. Declare the Site (kind: `binding_site`, `metal_coordination`, etc.) explicitly in the eval — without it, scope=ligand measurements will trigger `_check_implied_blocks` to fail the QDS emit.

For waters specifically: do NOT declare every HOH as a Ligand (146 records would explode the YAML). Use a single scope=complex measurement carrying the water B and RSCC distribution stats (mean/std/min/max/count), plus ResidueOutlier rows only for the worst N. The 1SAR eval shows the pattern — 4 outliers (1 Asn A 39 + 3 waters) explicitly listed; 146 waters summarised in two scope=complex rows.

## QDS emitter contract (schema v5)

`scripts/qds_emit.py` follows two hard rules:

1. **Routing is by canonical metric id, not substring.** A single `METRIC_TO_QDS_SLOT` table at the top of the file maps every metric id to its destination. The table is validated against `ref/catalog.yaml` at startup; a typo is a hard error. Adding a new metric → add a new row in the table. Do NOT extend with substring matching, and do NOT add a second table.

   A row's value is either one `(block, slot)` pair, or a **list** of them when a metric deliberately lands in more than one block — a headline summary plus a newer specialized block. `T05_packing_z_score` and `T05_unsatisfied_buried_hbond_count` do this (geometry + packing), as does `T07_prediction_ensemble_convergence` (predicted-confidence + prediction-ensemble). The value is emitted once per listed slot, so the same number appears in both blocks by design.

2. **Fail-hard on implied content.** If the source eval has any of these, the QDS MUST surface the corresponding block or the emitter exits non-zero with a specific error (`QdsCompletenessError`, which subclasses `SystemExit`):
   - `scope=site` measurement → `SiteQuality` block required (declare a `Site` on the eval)
   - `scope=ligand` measurement → `LigandQuality` nested in a `SiteQuality` required
   - `scope=residue` measurement OR any `residue_outliers[]` / `density_peaks[]` / `flagged_regions[]` / `per_residue_values[]` on the eval → `PerResidueQuality` block required
   - `scope=domain` measurement → `ClassificationSummary` rows required
   - `scope=interface` measurement → `InterfaceQualitySummary` rows required
   - `scope=ensemble` measurement → `PredictionEnsembleSummary` or `NmrValidationSummary` rows required
   - `pairwise_comparisons[]` on the eval → must surface in QDS

3. **Fail-hard on cctbx-only coverage (#315).** A gradeable applied task whose cross-tool coverage is cctbx-only or unclassifiable refuses to emit unless the eval declares a matching `CrossToolWaiver` (task ref, reason, `as_of_date`); the waiver is surfaced on the QDS and annotates the coverage row it excuses (`… — WAIVED <date>: <reason>`). Non-cctbx-only coverage is deliberately not gated — the trust model forbids self-grading, not independent-only evidence. Committed QDS files are separately checked by `scripts/check_qds_trust_invariant.py` (validate step 3c); pre-2026-08-13 history is grandfathered by name on every run.

4. **A verdict must name its criterion (#567).** Any `pass_status` that asserts an outcome requires a non-empty `pass_criterion`; `informational` means "reported without a declared criterion" and must not carry one; `fail_by_oracle` / `fail_by_oracle_within_cctbx` require the `agent_claim` they disagree with, and the latter requires `oracle_family: cctbx`. Reasoning a verdict out in `notes` while leaving `pass_criterion` empty is the defect this rule exists to stop — it is what let one 1SAR row ship marked `pass` with no criterion, and two identical rows be graded on opposite conclusions from the same premise. Committed records are checked by `scripts/check_pass_status.py` (validate step 3c-bis); pre-2026-09-07 history is grandfathered by name, and a `PassStatus` value the guard does not classify is a hard failure so the rules cannot silently fall out of step with the schema.

Regression tests at `scripts/test_qds_emit.py` enforce that the 1SAR example has every expected geometry slot populated, the synthetic active-site eval (`data/examples/eval/EVAL_synth_active_site_*.yaml`) populates per_residue_quality / site_qualities / ligand_quality / pairwise_comparisons / tool_recommendations_applied, and the negative test confirms the fail-hard behaviour. `scripts/validate.sh` runs all of this in sequence.

## Common pitfalls

- **Inverting the trust model.** MolProbity is the geometry oracle; it is not a PHENIX tool. `phenix.holton_geometry_validation` and MolProbity are *both* run, and the harness compares them.
- **Naming drift.** It's `phenix.superpose_models`, not `phenix.superpose_pdbs`. Verify in `ref/phenix_docs/phenix-online.org/documentation/reference/` before adding a new row.
- **Adding pass thresholds to the catalog.** Don't. They go in `driving_example_T<NN>.md`.
- **Skipping the baseline.** Pre-refinement metrics are required to compute Δ-anything. The driving example shows this; per-task drivers should follow.
- **Vague example datasets.** "Any high-resolution structure" is not reproducible. Use a PDB/EMDB ID.
- **Reporting RMSD alone for pair comparisons.** TM-score and lDDT are the mandatory pair (`ref/quality_reporting.md` §2.1); RMSD is reported additionally for legibility, never as the basis of the verdict.
- **Quoting R-work alone.** Always with R-free and the gap. The R-free expectation rule of thumb is `≤ resolution_Å / 10` (Brünger 1992; Evans & Murshudov 2013).
- **Mean pLDDT without distribution.** A bimodal-sharp distribution (confident core + disordered tails) is normal; a broad distribution centred on 70 is a different story. Always report distribution shape via the `PlddtDistributionShape` enum.

## Reference materials

- PHENIX docs: `ref/phenix_docs/`
- Task catalog: `ref/catalog.yaml` (canonical, LinkML-validated) + `ref/tasks_and_evaluations.{md,tsv}` (denormalized export)
- Quality reporting consensus: `ref/quality_reporting.md` — what to report and why, with citations
- Tool recommendations: `ref/tool_recommendations.yaml` — `top_considered` vs `top_performing` per metric
- Oracle install status: `ref/oracle_tools.md`
- Schema: `schemas/protstruct_review.yaml`; validate with `bash scripts/validate.sh`
- Eval filename convention: `ref/eval_naming.md`
- Driving example: `ref/driving_example.md`
- Project overview: `ref/README.md`
