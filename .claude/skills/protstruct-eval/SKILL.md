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
- **H-atom placement.** `reduce -build` does its own Asn/Gln/His flips and adds H atoms with default bond-length and rotamer choices. In the matched 1SAR comparison, `phenix.reduce` and standalone `reduce` dispatched the same builder; the residual clashscore difference came from the cctbx-versus-probe counting path, not different H placement. Distinct-builder comparisons such as `reduce` versus `mmtbx.reduce2` require their own matched evidence.
- **Water and altloc handling.** `probe`'s default `ogt33` water filter and altloc selection determines which atoms can clash. Quote the flags used.
- **Rotamer library.** Rotamer outliers use a discrete library; a side-chain that is 1° outside the favored region scores as outlier. The "% outliers" number is sharp by construction; flag clusters near boundaries in `notes`.

### `phenix.refine` (in-run R-factors)
- **Bulk-solvent and anisotropic scaling.** In-run R-work / R-free use the refinement's bulk-solvent and scaling state; a fresh `phenix.model_vs_data` derivation can differ. Measure that effect only on the exact same model and MTZ. For packaged 1SAR round 4, the PDB header and fresh result differ by just 0.0001 / 0.0002; the old 0.01–0.015 claim compared the round-7 log with the round-4 package and is withdrawn.
- **R-free flag set.** Assumes the test set is fixed and untouched. If the agent regenerated R-free flags between rounds, cross-validation is broken silently. Compare reflection counts and column labels at every round when in doubt.

### `phenix.model_vs_data`
- **Same bulk-solvent / scaling code path as `phenix.refine`** in principle, but a separate full re-derivation. Catalog T06 oracle of record. Treats the model as fixed; not a refinement.

### `gemmi sfcalc` + custom R calc
- **The benchmark is estimator-specific.** `gemmi sfcalc --scale-to` uses flat-mask bulk solvent, one global anisotropic tensor and global solvent parameters. Registry §3's **|ΔR_work| ≤ 0.02** envelope covers direct summation of those globally scaled FC values with the same model, MTZ, work set and `--radii-set=cctbx`; the observed positive sign is diagnostic, not a pass condition. `gemmi_rfactor.py` adds a work-fitted bin-wise isotropic rescale and is not covered by that benchmark. Keep its R-work and R-free offsets informational until estimator-matched benchmarks exist.
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
- **Peak threshold (σ cutoff)** controls what's reported. Default 4.0 σ; lowering surfaces noise, raising hides real peaks. A 1SAR run on the packaged round-4 model found 23 positive + 8 negative peaks at 4 σ, while the report described round 7 and listed 9. Because the models differ, that mismatch cannot identify a cutoff or reporting defect; it demonstrates why peak inventories must be bound to the exact subject.
- **Peak-merging radius** can collapse multi-atom features into one entry.
- **Atom exclusion.** Peaks within X Å of modelled atoms are typically excluded. Describing peaks by a nearest atom does not establish the exclusion policy. Record the actual flags and radius; different exclusion settings produce different counts.

### lDDT
- **Distance inclusion radius** (default 15 Å) determines what counts as "local". Smaller radius rewards local fidelity, larger rewards extended geometry.
- **Tolerance thresholds** (0.5 / 1 / 2 / 4 Å) are baked in — comparing two lDDT scores produced by different code paths requires verifying the same thresholds.

### CCP4 `aimless` and `ctruncate` (T13 data-quality oracle)
- **`aimless` requires unmerged intensities** (M/ISYM column). On a merged-only MTZ (e.g. F-obs / SIGF-obs only — the 1SAR case) it aborts immediately with `hkl_unmerge_list::prepare - EMPTY`. CC½, ⟨I/σ⟩ outer, and Rmerge / Rmeas all flow from unmerged data and are **unobtainable** if the artefact does not ship it. Document this as a known gap rather than substituting unrelated metrics.
- **`ctruncate` is the merged-data fallback** for the T13 metrics that *are* recoverable from amplitudes alone: Wilson B, L-test twin fraction (+ moments), ΔB anisotropy, tNCS via Patterson search, ice-ring summary. These are CCP4 / non-cctbx and close the T13 cross-tool gap when aimless can't run.
- **`scripts/t13_data_quality.py`** wraps both using the configured CCP4 environment: it tries aimless first (captured as a provenance row), then runs ctruncate and emits informational EvaluationMeasurement rows bound to the input MTZ digest. Pass `--columns 'F-obs,SIGF-obs'` for typical phenix-refined MTZs and a fresh repository-local `--logdir` (default `<mtz_dir>/t13_oracle_logs/`); retained logs/output MTZs are never overwritten, and evidence refs are portable repository-relative paths. Missing or unrecognized flag evidence is unavailable, not false. Paired agreement grading still requires the corresponding agent measurement and registry preconditions.
- **Twinning thresholds.** L-test fraction < 0.05 = effectively untwinned; 0.05–0.20 = mild / borderline; > 0.20 = strong. ctruncate's "first-principles operator search" is independent of the L-test and reports zero operators when the lattice/symmetry permits no twin laws.
- **Anisotropy ΔB rule of thumb.** Eigenvalue spread (max − min) < ~20 Å² on the orthogonal-coords B-tensor is acceptable for general refinement; ctruncate's "some anisotropy detect" message fires at much lower thresholds and is informational unless ΔB is large.

### wwPDB validation report
- **Percentile rankings** computed against the entire archive (and against the resolution-binned subset). Quote which one. A clashscore of 8 is 70th percentile vs all PDB but 30th percentile at 1.5 Å.

## OpenScientist agentic-framework assumptions

Specific to the way the OpenScientist agent aggregates and interprets oracle outputs in `data/coscientists/openscientist/`. These assumptions came out of the 1SAR re-measurement work; flag any of them when reviewing future OpenScientist artefacts.

### Reporting

- **R-factors may be read from `phenix.refine`'s in-run log** (or stored MTZ statistics) rather than re-derived by `phenix.model_vs_data`. Re-derive against the exact same model and MTZ before attributing a difference to scaling. The 1SAR round-7 values are log-attested, but its coordinates are not retained; comparing them with the round-4 package cannot calibrate an in-run-versus-fresh offset.
- **Per-round table aggregation collapses rounds.** "Round 5–6" appears as one row in the agent's report despite being two distinct refinements. Preserve one row and subject identity per round. The retained round-6 oracle R-free is 0.2068; round 7 has only the agent's 0.1989 log value, not an oracle measurement, so their direction cannot be adjudicated as an oracle trend.
- **Numeric positions require subject identity.** A coordinate quoted for one round must be checked against that round's model. The 1SAR report's Ca²⁺ position and the packaged round-4 position differ by 0.215 Å, but the reported round-7 coordinates are absent, so that difference does not prove an initial-versus-final templating error.
- **Water counts require subject identity.** The 1SAR report claims 159 ordered waters while the packaged round-4 file has 146, accounting for the package's 13-atom gap. That is a claim-to-package mismatch across rounds; without round-7 coordinates it does not establish a later pruning step or a reporting error.
- **Mean B-factor requires subject and atom-selection identity.** The 1SAR report quotes 14.6 Å² while the packaged round-4 audit finds 15.98 Å². Because the models differ, the delta cannot diagnose rounding or a heavy-atom/solvent selection choice. Record the model digest and selected atom population before comparing.

### Interpretation

- **Ion identity inferred from peak height alone.** "6.5 σ peak near Asp33 = Ca²⁺" is asserted from the difference map alone. No anomalous-Fourier check, no Mg/Mn/Na elimination, no occupancy refinement that would distinguish them. Mg²⁺ would give very similar geometry. Document the inference chain in `notes` and downgrade the verdict to "consistent with Ca²⁺ — alternatives not excluded" unless an anomalous map confirms.
- **Density-peak narratives are interpretive, not measured.** "All peaks > 4 σ are explained by known features" is an annotation, not a measurement. Re-run `phenix.find_peaks_holes` independently on the exact claimed model before adopting it. The 1SAR inventory of 23 positive peaks belongs to the packaged round-4 model, whereas the nine-peak report describes the absent round-7 model; their difference is not a same-subject finding.
- **NCS effective data-to-parameter ratio is a heuristic.** "846 NCS torsion restraints effectively double the data" assumes the restraints are saturated and uncorrelated with model coordinates. The actual contribution depends on restraint weight + geometry coupling and is not a measured quantity. Agent reports 0.98 → 1.79; this is a model-assumption number, not a re-derivation.
- **Pre-refinement baseline = deposited model.** The deposited 1SAR is itself a refined product; the "Δ start → final" framing implicitly equates the deposited model with an unrefined starting point. For agentically-refined targets the proper baseline is whichever model the agent was actually given, which may or may not be the deposition.
- **Cooperative binding rationale is literature interpretation, not measurement.** "Weaker Ca²⁺ binding because of missing nucleotide cofactor" is a bona-fide structural-biology hypothesis but it's not measured by any oracle in the catalog. Treat such reasoning as inference, not a quality finding.
- **Round-7 NCS-restraint improvement is not independently adjudicable here.** The agent log says the gap moved from 0.053 to 0.050. Round 6 has a retained oracle measurement, but round 7's coordinates are absent; 0.055 belongs to the packaged round-4 model, not round 7. Verify any "X improved Y by Z" claim on retained before/after subjects with the same oracle.

### Aggregation

- **Single-model verdicts.** Agent treats the final PDB as a point estimate. No B-factor uncertainty propagation, no rotamer alternate-conformation enumeration, no map-error envelope. The QDS schema's `TypedMeasurementValue` summary stats (mean / std_dev / min / max / count) exist for this purpose — populate them when an array of values is available.
- **Geometry outlier rates require subject identity.** The agent's round-7 report says 0.00% Ramachandran outliers, while the packaged round-4 audit found one. Because the round-7 coordinates are absent, that cross-round difference does not establish rounding or omission. For any retained subject, preserve every outlier residue id even when an aggregate rate falls below display precision or a threshold.
- **Single-tool geometry validation.** `phenix.molprobity` (the cctbx wrapper) provided the geometry numbers for the agent's report. Same code base as the refiner that minimised those restraints. Document this as `oracle_family: cctbx` and require a non-cctbx confirmation before adopting any geometry pass/fail verdict.

### How to apply these in a review

When evaluating a new OpenScientist artefact:

1. **Always re-derive R-factors** with `phenix.model_vs_data` even when the agent reports R-factors. Note the gap.
2. **Re-extract atom counts and water counts** from the deposited PDB; compare to the agent's narrative numbers.
3. **Re-run `phenix.find_peaks_holes` at 4 σ on the exact claimed model and map/reflection data**, recording the subject digests and flags, and compare only with the agent's inventory for that same subject. Five or more unlisted peaks > 5 σ is a flag only in that matched comparison. If the claimed model or map is unavailable, record the inventory as unadjudicable; do not substitute another round or the deposition.
4. **For any "X moved by Y Å" or position quote**, verify the quoted coordinates exist in the deposited PDB to within ≤ 0.05 Å.
5. **For ion identity claims**, ask whether anomalous data was used; if not, downgrade the verdict.
6. **For Δ-claims between rounds**, run the oracle on each round's PDB+MTZ (we have the MTZs in the artefact zip) and confirm the direction of change.
7. **Quote `oracle_family`** on every measurement; require ≥ 1 non-cctbx confirmation for every load-bearing finding.
8. **Run the T13 data-quality oracle** with `python scripts/t13_data_quality.py <mtz> --eval-id <EVAL-id> --logdir <new-dir>`. Wilson B, twinning, anisotropy ΔB, tNCS, and ice-ring flags are retained as informational ctruncate diagnostics where recognized; aimless is tried first to capture its status. This supplies independent-family evidence, not an automatic T13 pass: paired agreement checks still require the same dataset, agent measurements, and registry preconditions.

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

**Pass criteria do NOT live in this catalog or in the per-task drivers.** The catalog is
metric-shape; numeric definitions live only in `ref/thresholds_and_standards.md`, and drivers cite
and contextualize that registry.

**Per-task drivers exist for all 17 tasks (T01–T17)** (`ref/driving_example_T<NN>.md`),
plus the combined `ref/driving_example.md` (T01+T04+T05+T06). Each per-task driver grades **cross-tool
agreement**, not an absolute quality bar, and cites registry thresholds carrying approved provenance
(`[schema]` / `[MolProbity]` / `[literature]` / `[catalog]` / `[template]` / `[calibration]` /
`[benchmark]`) so a
domain reviewer can audit it. The T15/T16/T17 drivers correspond to the runnable wrappers
`scripts/t15_ss_agreement.py`, `scripts/t16_interface_quality.py`,
`scripts/t17_nmr_ensemble.py`, and `scripts/t17_restraint_summary.py`.
T15 invocations must supply a new repository-local `--evidence-out`; do not paste its rows unless
the retained JSON exists and both rows cite it. When the input came from a retained ZIP, also pass
`--source-archive` and `--source-member`. The wrapper rejects duplicate or size-mismatched members,
refuses overwrite, pins the complete archive and exact member/source bytes, and retains the
normalized input, raw DSSP bytes, both assignment streams, hashes, and tool versions.

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

T15–T17 deliberately have **no PHENIX implementation**, but their numeric checks are runnable
through independent oracle paths: informational DSSP H+E content plus informational DSSP +
biotite agreement for T15,
DockQ + biotite for T16, and biotite plus deposited wwPDB validation reports for T17. See
`ref/oracle_tools.md` for versions, limitations, thresholds, and the exact wrappers.

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
   label. T15 currently has a provisional interpretability precondition, but neither oracle-pair
   value grades model quality: report
   `T15_secondary_structure_content` (DSSP H+E) alongside
   `T15_secondary_structure_agreement` (three-state DSSP vs an independent second assigner —
   STRIDE preferred, biotite P-SEA the runnable fallback via `scripts/t15_ss_agreement.py`)
   with both rows informational and no `pass_criterion`. Content **≥ 0.20** provisionally supports
   interpreting the agreement; below it, coil/coil agreement may dominate, which weakens the
   agreement rather than failing the model. The historical **0.65** expectation is non-gradeable
   pending exact-denominator recalibration. The separate
   agent-vs-DSSP **≥ 0.85** comparison is T15's gradeable numeric context, but that clause is
   unevaluable when no agent assignment exists. Per-residue labels ride along as informational
   content.

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
5. If a recommendation is wrong (a tool consistently disagrees with consensus, or a new tool outperforms the recommended one), **update `ref/tool_recommendations.yaml`** — add a new id with a later `as_of_date`, an exact timezone-qualified `effective_at`, and `supersedes_recommendation_ref` pointing to the prior row; never mutate or delete the snapshotted predecessor. Give new or revised rows in `ref/tool_assumptions.yaml` the analogous dated/timestamped `supersedes_assumption_ref` lineage. Re-run `bash scripts/validate.sh` after edits.

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
| `classification_summary` | `ClassificationSummary` | T15 — informational DSSP H+E content diagnostic plus secondary-structure agreement (informational pending exact-denominator recalibration), with SS / domain / fold labels (informational) |
| `interface_quality_summary` | `InterfaceQualitySummary` | T16 — total two-sided buried surface area (`ΣSASA(chains) − SASA(complex)`), DockQ, CAPRI class. Double PISA's per-side `interface_area` before comparison; BSA tolerance is `max(3% of mean, 30 Å²)`. Required when any `scope=interface` measurement exists |
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

1. **Position vs the claimed subject** — verify quoted coordinates against the exact model/version the report names, identified by digest, to within ≤ 0.05 Å (gemmi audit script). A comparison with a deposition or differently packaged round answers a different question. In 1SAR the 0.215 Å report-to-package difference crosses round identities and cannot diagnose initial-versus-final templating.
2. **Density support** — assess accuracy and precision with independent `edstats` RSZD/RSZO when available, following registry §2's “Real-space density fit (ligand/loop)” rule. Retain RSCC/RSR as informational diagnostics; RSCC corroboration across tools requires a matched limiting-radius convention. Neither statistic has a fixed quality cutoff. If RSZD/RSZO or matched-radius metadata are absent, state the gap rather than grading absolute RSCC/RSR values.
3. **B-factor vs surroundings** — compute the ratio `B(ligand) / mean_B(protein)`. < 1.5× = consistent with full occupancy. 1.5–3× = partial occupancy or weak binding. > 3× = very weak; investigate alternative interpretations.
4. **Coordination geometry** (metals) — inner-sphere bonds 2.0–2.6 Å for hard metals (Ca²⁺, Mg²⁺, Zn²⁺); coordination number 6–8 for Ca²⁺. Use `gemmi contact` or a small gemmi script.
5. **Element identity** (metals) — does the data type allow it to be cross-checked?
   - **Anomalous data present** (e.g. multi-wavelength MAD, peak/edge/remote) → run anomalous Fourier; check anomalous map peak height at the metal site. Tools: `phenix.anomalous_signal`, CCP4 `fft` with anomalous coefficients.
   - **No anomalous data** → element identity cannot be cross-validated by oracle. Downgrade verdict to "consistent with X — alternatives not excluded". For 1SAR's `1sar.mtz` (only F-obs / SIGF-obs / R-free flags) this is the case.
   - **CheckMyMetal web service** (<https://checkmymetal.research.uchicago.edu/>) — geometry-based heuristic check: classifies modelled element by coordination geometry against expected. No anomalous data needed; web-only, no install. Useful when the only choice is "downgrade to consistent-with" or "submit for an external sanity check".
6. **Pose RMSD to deposited reference** (small-molecule ligands) — informational pending a ligand-specific registry criterion. Identify both coordinate subjects, matched ligand atom mapping, symmetry-equivalent atom handling and common receptor frame. Fitting the ligand itself measures conformation, not its placement at the binding site. Cross-tool agreement confirms a calculation, not a correct pose; do not borrow the Cα-superposition tolerance.
7. **H-bond network** — `gemmi contact` or PLIP. Count protein–ligand H-bonds; compare to expected for the ligand class.

### Per-water audit (whole-structure, not per-residue)

For the water set as a whole:

1. **Count** waters in the exact claimed model (`grep -cE '^HETATM.* HOH ' model.pdb` or `gemmi residues`) and record its digest. A deposition or stale packaged round is a separate subject. In 1SAR the packaged round-4 count is 146 and the round-7 report says 159; this is a package/claim gap, not a same-model count error.
2. **B-factor distribution** — mean, std, min, max. Mean ~1.5–2× protein-mean is typical for surface waters. Flag waters with B > 60 Å² as `density_misfit` candidates.
3. **Density-fit distribution** — retain per-water RSCC values and their radius convention as informational diagnostics. Apply registry §2's density-fit rule to available RSZD/RSZO evidence. Do not infer a `density_misfit` outlier or a water-quality verdict from an absolute RSCC cutoff. The historical 1SAR RSCC-only water flags require a new dated correction before reuse as density-misfit findings.
4. **Per-water summary on the QDS** — populate `TypedMeasurementValue.mean / std_dev / min_value / max_value / count` on a single scope=complex measurement. Ranking may identify waters for review, but add `density_misfit` ResidueOutlier rows only when retained significance evidence supports that classification.

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

For waters specifically: do NOT declare every HOH as a Ligand. Use a single scope=complex measurement carrying the water B and RSCC distribution stats (mean/std/min/max/count). Add `density_misfit` ResidueOutlier rows only when retained significance evidence supports that classification; rank-only or RSCC-only review candidates remain informational observations. The historical 1SAR water flags are not a validated template for assigning outlier status.

## QDS emitter contract (schema v5)

`scripts/qds_emit.py` follows these hard rules:

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

3. **Fail-hard on cctbx-only coverage (#315).** Coverage is computed per metric and comparison context, never by task-level union: an unrelated or failed oracle attempt cannot close a claim. A cctbx-only or unclassifiable claim refuses to emit unless the eval declares a matching `CrossToolWaiver` (task plus metric/context qualifiers, reason, `as_of_date`). A legacy task-only waiver is accepted only when one claim for that task is gated. The waiver is surfaced on the QDS and annotates only the row it excuses (`… — WAIVED <date>: <reason>`). Non-cctbx-only coverage is deliberately not gated — the trust model forbids self-grading, not independent-only evidence. Committed QDS files are separately checked by `scripts/check_qds_trust_invariant.py` (validate step 3c), which rebuilds coverage and waivers from the referenced source EvaluationRuns. Modern source documents must pin the relevant top-level `Structure`, `Tool`, `tool_recommendations`, and `assumptions` snapshots plus a `qds_replay_pins` content-addressed boundary; the sheet pins `emitter_contract_version`. Whole-sheet derivation is replayed through the retained contract module using only those source snapshots, then independently canonicalized and compared with the source-owned output pin. Today's emitter, catalog, and registries cannot reinterpret an older artifact. Live selection and retained-contract preflight reject equal-priority sources that differ in criterion binding/preconditions, claim/delta lineage, or assumptions, and reject nested source lineage/verdict fields. This protects frozen v1/v2 output shapes without adding fields to them. Contract implementations and supported-version dispatch are append-only. Historical exemptions are an explicit frozen allowlist keyed by repository path, QDS identity, issue timestamp, and content fingerprint; there is no date-based grandfathering.

4. **A verdict must name an applicable, registry-grounded criterion (#567, #588).** Any
   `pass_status` that asserts an outcome requires a numeric-comparison `pass_criterion` and a
   `pass_criterion_ref` resolving in
   `ref/structural_criteria.yaml::pass_criterion_bindings`. The binding must match the row's exact
   metric, task, stage, scope, oracle tool/family, effective date, canonical unit, and bidirectional
   catalog task links. It selects one complete normalized registry cell by section, first-cell row
   label, and one-based column. That cell must contain exactly one strict positive-polarity numeric
   comparison; the binding declares its operand/transform and the guard recomputes the result with
   exact decimal arithmetic (including exact unit-compatible `delta = oracle_measure - agent_claim`).
   The row's displayed criterion and status must match the cell and result. Its dedicated
   Provenance/Source cell must carry an approved tag. Do not copy threshold values into the catalog
   or binding.

   Encode every load-bearing condition in the selected cell as `[requires: id,...]`; the binding's
   ids must match that annotation exactly. A verdict carries every required
   `criterion_preconditions[]` check once, as `satisfied` with non-circular retained evidence.
   `criterion_inapplicable` retains the authoritative criterion/ref and documents at least one
   required `void`/`unknown` check. `informational` carries no criterion/ref/preconditions. All four
   disagreement statuses (`fail_by_oracle`, `fail_by_oracle_within_cctbx`, `pass_with_caveat`, and
   `pass_criterion_fail_headline`) require a finite numeric, unit-compatible agent claim that differs
   from the oracle; text-only disagreement cannot grade a numeric rule, and plain `pass` or
   `fail_criterion` cannot hide a contradictory claim. Value carriers set exactly one of numeric,
   text, or true-not-applicable and cannot contain nested QDS lineage/verdict fields.

   `fail_by_oracle_within_cctbx` is the only criterion-bearing status permitted on a cctbx row; put
   hard verdicts on an independent non-cctbx measurement. Bindings use inclusive effective intervals
   and immediate-predecessor, same-context, append-only supersession; the EVAL filename date equals
   `run_date`. Notes do not substitute for structured applicability or justify opposite statuses on
   otherwise identical evidence. Committed records are checked by `scripts/check_pass_status.py`
   (validate step 3c-bis). Pre-registry files and their known R2/R3 defects are preserved only by exact
   path/file/row SHA-256 pins: this records unvalidated history, not approval. Backdating never grants
   an exemption; correct a frozen Eval/QDS pair by publishing a new dated record. Duplicate YAML keys,
   unknown enum values, statusless criterion metadata, and malformed schema, binding, carrier, or
   record shapes fail hard.

5. **Selection is subject-aware and provenance-preserving.** Put a stable `subject_ref` on every
   measurement when an eval contains more than one concrete model, dataset, or assembly. The QDS
   names its subject too. Exact-subject measurements outrank legacy rows with no subject; explicit
   non-matches are excluded. Every wrapped QDS scalar keeps its source run/measurement ids, metric,
   stage, scope/selector, tool/family, status, criterion, and notes. Frozen output contracts do not
   inline newer binding/precondition fields; resolve `source_measurement_ref` for full context.
   `scope_selector` remains a terse
   machine selector; provenance prose belongs in `notes` or first-class fields.

6. **Coupled values stay on one code path.** R-work, R-free, and the gap are one bundle, selected
   from the same run, subject, tool, and oracle family. If no coherent bundle covers the available
   slots, the emitter fails instead of manufacturing a mixed-family or mixed-tool triple.

7. **Contract-3 partial sheets require one typed emission context.** Put exactly one
   `qds_emission_contexts[]` row in a canonical source `EVAL_*.yaml`, owned by one of the named
   EvaluationRuns. It binds the target QDS, deterministic source-run order, structure, exact
   subject, timezone-qualified issue timestamp, `coverage_scope: partial`, boundary note, identity description, and
   current combined headline. Point both the QDS and replay pin to it and pin the context snapshot
   digest. This is required even for a one-run partial sheet. A cumulative contract-3 sheet carries
   no context and retains run-level headline concatenation. Never infer summary prose from input
   file order, “latest run,” or stale per-run retraction language.

   Retained v1/v2 emitters are replay-only, not authoring alternatives. Every new committed QDS
   uses the current contract. The only exception is an already-issued artifact whose repository
   path, QDS id, timestamp, contract, and complete carrier digest match the immutable guard
   allowlist; that artifact still has to pass its ordinary source-pin replay.
   Keep EvaluationRuns and QDSs in canonical `data/**/EVAL_*.yaml` and
   `data/**/QDS_*.yaml` carriers. The schema's generic Container shape does not authorize placing
   either collection in a registry or other YAML file that its dedicated guards do not discover.
   The suffix is exact lowercase `.yaml`; case variants and symlink aliases are discovered and
   rejected under their lexical paths.

8. **Bind retained archive provenance to the subject.** For T15 artifact runs, provide the exact
   repository-local archive and member. The wrapper derives the canonical `artifact:<id>#<member>`
   subject from that pair or rejects a conflicting `--subject-ref` before invoking any oracle.

Regression tests at `scripts/test_qds_emit.py` enforce that the 1SAR example has every expected geometry slot populated, the synthetic active-site eval (`data/examples/eval/EVAL_synth_active_site_*.yaml`) populates per_residue_quality / site_qualities / ligand_quality / pairwise_comparisons / tool_recommendations_applied, and the negative test confirms the fail-hard behaviour. `scripts/validate.sh` runs all of this in sequence.

## Common pitfalls

- **Inverting the trust model.** MolProbity is the geometry oracle; it is not a PHENIX tool. `phenix.holton_geometry_validation` and MolProbity are *both* run, and the harness compares them.
- **Naming drift.** It's `phenix.superpose_models`, not `phenix.superpose_pdbs`. Verify in `ref/phenix_docs/phenix-online.org/documentation/reference/` before adding a new row.
- **Adding pass thresholds to the catalog or driver.** Don't. Define them once in
  `ref/thresholds_and_standards.md`; drivers cite that row.
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
