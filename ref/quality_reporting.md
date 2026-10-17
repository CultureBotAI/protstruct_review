# Reporting protein-structure quality and refinement outcomes

This guide supports two repository goals: assessing protein refinement results and
understanding which structure tools and measurements answer which questions.
It distinguishes scientific interpretation, repository grading policy, and implemented
QualityDataSheet (QDS) behavior. It does not define another set of acceptance thresholds.

Use the [catalog](catalog.yaml) for metric identities and the
[threshold registry](thresholds_and_standards.md) for criteria and their applicability.
The [evidence-status ledger](threshold_evidence_status.yaml) records qualifications,
suspensions and evidence limits; a historical benchmark label is not sufficient grading authority.
[Structural criteria](structural_criteria.yaml) bind eligible verdicts to registry cells.
[Tool recommendations](tool_recommendations.yaml), [tool assumptions](tool_assumptions.yaml)
and [oracle capabilities](oracle_tools.md) describe the available measurement paths.

## State the question and identify the evidence

Separate three conclusions that can require different evidence:

| Question | Evidence needed | What the result establishes |
|---|---|---|
| Do measurements agree? | Two implementations measuring the same metric on matched inputs | Agreement within a declared scope; not automatically model quality |
| Is this model suitable for the intended use? | Experimental fit where available, geometry, local inspection and relevant references | A qualified assessment of the exact model and features examined |
| Did refinement improve the input? | Retained starting and final models evaluated under matched conditions | Benefit or deterioration on specified measures; coordinate movement alone is insufficient |

Identify the exact coordinate artifact and dataset, retained hashes, model/chain/atom
selections, processing stage and baseline. A PDB identifier or filename alone does not
distinguish a tutorial input, deposited structure, intermediate output and reported final model.
Record tool versions, settings, restraint libraries, raw outputs and observation dates.
Distinguish a new measurement from a stored header value, agent claim or historical transcription.

For before/after comparisons, use the same experimental observations, resolution range,
free-reflection flags, map treatment, selections and calculation conventions where applicable.
A fresh dataset of the same protein is a different comparison context. Changes in data,
model completeness, assembly, ligand content or atom mapping must be explicit.

## 1. Single-model measurements

### 1.1 Geometry and stereochemistry

Geometry checks apply to experimental and predicted models, including unprocessed predictions.
Report the coordinate version examined and the denominator behind each count or percentage.
Use the registry's outlier definitions; distinguish a residue classified as **Allowed**
from one classified as **OUTLIER**.

| Measurement | Interpretation and implementation boundary |
|---|---|
| Clashscore and clash list | All-atom contact diagnostic. Hydrogen placement, atom inclusion and contact conventions affect the result. Reduce prepares hydrogens; Probe supplies contact analysis. |
| Ramachandran and rotamer classifications | Backbone/side-chain conformational checks against specified reference distributions. Require the relevant classifiers; Probe and Reduce alone do not produce these classifications. |
| MolProbity score | Composite of clashscore and conformational statistics; a summary alongside its components and local outliers. It is not an overall accuracy measurement. |
| Bond/angle RMSD and RMSZ | RMSD has units of Å or degrees; RMSZ is dimensionless and depends on restraint targets and uncertainties. Retain restraint counts and library provenance. |
| Cβ, peptide, chirality and other local checks | Use a tool that implements the particular definition; a generic geometry command does not establish interchangeable outputs. |

Where an appropriate archive comparison exists, report the percentile, reference population
and resolution context. An archive percentile is a relative ranking, not proof of correctness.
Do not infer that low resolution makes a particular outlier harmless. MolProbity's score
approximates the resolution at which that combination of component scores is average;
its authors describe it as a rough comparative guide. [Williams et al. (2018)][molprobity].

### 1.2 X-ray model-vs-data and data quality

Report R-work and R-free together, with the actual free-set identity/count, resolution
selection and scaling/bulk-solvent conventions. R-free assesses withheld reflections;
retain the same flags throughout refinement. A lower value on matched data is evidence
of improved fit on that measure, not by itself an overall quality verdict.
[PHENIX refinement guidance][refine-faq].

Do not apply a universal R-free = resolution/10 rule, R-work/R-free gap cutoff, or
fixed ΔR-free equivalence band from this guide. Model errors, data properties, test-set
sampling and calculation choices all matter. A suspicious statistic calls for investigation;
it does not uniquely identify overfitting or establish that the model rather than the data is wrong.

Report completeness, intensity signal-to-noise and CC½ with their resolution bins and
input provenance when available. CC* estimates the relation between merged observations
and underlying signal; interpret it alongside model–data correlations under compatible
definitions, not as an isolated quality cutoff. [Karplus & Diederichs (2012)][cc-star].
The input requirements differ: do not infer unavailable unmerged-data statistics from
a merged-amplitude file. Record unavailable diagnostics and their missing inputs.

Resolution selection should consider the data and intended analysis. Useful weak data
can extend beyond traditional I/σ cutoffs; a universal I/σ or CC½ threshold is not supported
by the cited resolution study. [Evans & Murshudov (2013)][data-quality].

Name the R-factor estimator as well as the structure-factor calculator. `gemmi sfcalc`
does not by its name establish a particular scaling, free-set or R-factor convention.
Independent recalculation and agreement grading are separate steps governed by the registry.

### 1.3 Cryo-EM fit and map quality

Record map identity, grid/origin, masking, sharpening, resolution conventions and available
half maps. Keep model–map fit separate from half-map reproducibility and from geometry.

| Measurement | What to retain and compare |
|---|---|
| CC_mask, CC_box, CC_volume | The particular voxel population and map calculation. These coefficients answer different questions and need not agree. |
| Model–map FSC and its resolution summary | The full curve, threshold, masks and model-map generation settings. Compare like calculations. |
| Half-map FSC | Half-map identities, masking/correction procedure and reported threshold; it is a different comparison from model–map FSC. |
| EMRinger or Q-score | Relevant global/local values, atom/residue selection, resolution and map processing; each assesses particular structural features. |
| Local/directional resolution | Method and spatial context; a global resolution cannot describe every site. |

There is no universal requirement here that model–map FSC at one threshold match half-map
FSC at another within a fixed distance. Such differences alone do not diagnose underfitting
or fitting noise. Map processing and masks affect the measurements.
[Afonine et al. (2018)][cryo-tools].

The 2019 EMDataResource challenge distinguishes monitoring optimization against one map
from comparing models across an archive. Most evaluated global fit-to-map metrics behaved
similarly for the former; map–model FSC, EMRinger and Q-score had useful properties for
archive comparison. It also recommends local diagnostics and backbone validation.
It does not prescribe one mandatory metric combination for every report.
[Lawson et al. (2021)][em-challenge].

### 1.4 Prediction confidence and conversion to pseudo-B values

pLDDT, PAE, pTM and ipTM are predictor confidence outputs, not measurements against
experimental truth. Report predictor/version, original output and selections used for
summaries. AF2 pLDDT is per residue; AF3 provides per-atom pLDDT, so identify the aggregation.
Confidence stored in the B-factor field must not be mistaken for a refined displacement
parameter. [AlphaFold documentation][af-faq]; [AF3 output specification][af3-output].

Show confidence along the sequence or structure as well as its distribution. Low confidence
can accompany disorder or an incorrect prediction; a histogram alone cannot establish
disorder, locate uncertain tails or certify a core. PAE describes expected positional error
conditional on alignment; inspect relevant domain/interface blocks rather than interpreting
the minimum of an entire block as validation of an interface. [PAE guidance][pae].

The documented `phenix.process_predicted_model` conversion uses an empirical positional-error
estimate followed by a pseudo-B conversion. With input pLDDT on a 0–100 scale:

```text
L = pLDDT / 100                         # dimensionless, 0–1
estimated_RMSD = 1.5 Å × exp[4 × (0.7 − L)]
pseudo_B = (8π² / 3) × estimated_RMSD²   # Å²
```

If confidence is already fractional, use it directly as L. Record the selected input
interpretation and processing options: trimming/domain splitting change the coordinate
subject, and optional B-value adjustments change the written values. This empirical
conversion does not turn confidence into measured atomic displacement.
[PHENIX processing documentation][predicted-processing].

Assess processed coordinates separately. Inherited pLDDT does not become a fresh assessment
of refined coordinates. Experimental fit can be evaluated for a prediction when suitable
data and placement are available; otherwise disclose its absence. Compare with an experimental
reference only after establishing correspondence and the relevant biological state.

## 2. Structural comparisons and refinement deltas

### 2.1 Pairwise similarity

| Measurement | Definition and reporting context |
|---|---|
| Cα RMSD | Square root of the mean squared distances between matched Cα atoms after the stated superposition. Report atom mapping, fit selection, evaluation selection and aligned count. |
| TM-score | Length-normalized structural similarity; state normalization length and alignment procedure. It can obscure local errors. |
| GDT-TS / GDT-HA | Average of the percentages within their respective distance cutoffs under the GDT procedure; not a single RMSD or one fraction from an arbitrary fit. |
| lDDT / lDDT-Cα | Superposition-free preservation of local interatomic distances. State variant, atom coverage and reference; local preservation does not by itself establish correct domain arrangement. |
| Local displacement or site comparison | Identify residues/atoms and whether fitting used the whole model, receptor or selected site. The fitting frame changes the question. |

Use complementary measures where they resolve an ambiguity, rather than making a fixed
pair mandatory for all comparisons. See the [catalog](catalog.yaml),
[Zemla (2003)][gdt] and [Mariani et al. (2013)][lddt] for definitions.

### 2.2 Before/after interpretation

Define each delta with operands, units and sign: for example, R-free(final) − R-free(start)
on matched data, or CC(final) − CC(start) using the same map and calculation. Decreased
R-free or increased CC describes a directional fit change; significance, equivalence and
overall benefit require additional evidence and applicable criteria.

RMSD(start, final) measures coordinate movement. It is not a difference in accuracy scores,
and neither zero nor large movement proves success or failure. Improvement relative to
a reference requires comparing both start and final to that same reference with compatible
mapping and scoring. A deposited reference is an experimental model with its own uncertainty.

Track newly introduced, resolved and retained local outliers alongside data fit. Distinguish
coordinate uncertainty from variation across ensemble members. Resolve symmetry, chain
permutations, alternate conformers and missing residues before interpreting disagreement.

## 3. Independence, coverage and retained evidence

The repository requests non-cctbx corroboration of PHENIX-derived claims. That is a
repository trust policy, evaluated per metric and claim context. A tool installed for a task
does not cover every metric in that task. Record missing coverage and explicit waivers.
Two tool names or wrappers do not establish algorithmic independence; modern MolProbity
components share CCTBX code with PHENIX, and some dispatchers invoke the same underlying
binary. [Williams et al. (2018)][molprobity].

Keep provenance reproducibility, implementation independence, numerical agreement and
scientific validity separate. QDS dual-family coverage explicitly does not evaluate agreement.
An agreement tolerance must have its own matched-input preconditions; it is not a model-quality
cutoff. Retain disagreements and investigate them without choosing whichever score looks better.
PDB-REDO demonstrates constructive validation through refinement and rebuilding, not a rule
that cross-tool consensus alone establishes correctness. [Joosten et al. (2014)][pdb-redo].

The current retained 1SAR account is the
[2026-09-23 QDS](../data/coscientists/openscientist/QDS_1sar_cdba2c07_2026-09-23.yaml)
and its [correction narrative](../data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-09-23.md).
It concerns the packaged round-4 ribonuclease Sa model. The reported round-7 coordinates
were not retained, and the tutorial starting model is distinct from the deposited structure.
Active measurements are informational; cctbx-only gaps carry named waivers. Numerous
historical observations lack original raw output. This correction is neither a new scientific
rerun nor an overall quality pass, and cannot adjudicate the absent reported final model.
Earlier sheets remain audit history; use the current correction for its stated subject.

## 4. Local sites, ligands and outliers

Inspect features that matter to the intended use, even when global summaries look satisfactory.
Define each site by explicit members and context. A local outlier flags a feature for review;
neither its location nor a site-normalized score alone proves a functional defect.
Retain local experimental fit, geometry, contacts and the coordinate comparison frame.

| Ligand measurement | Interpretation and provenance |
|---|---|
| RSCC / RSR | Density-fit diagnostics; matched limiting-radius conventions are needed for RSCC corroboration. No fixed quality cutoff here. |
| RSZD / RSZO | Use registry §2, “Real-space density fit (ligand/loop)”, when the required statistics and inputs are available. |
| **Ligand B vs. surrounding protein B** | Informational; retain atom populations and any local shell. No fixed quality classification. |
| Contacts and H-bonds | Record eligible atoms, geometry, protonation and symmetry conventions; counts alone do not establish binding. |
| Pose RMSD | Retain reference, atom mapping, symmetry handling and common receptor frame. Fitting the ligand alone measures conformation rather than binding-site pose. |

**Ligand B-factor comparison.** Retain the exact coordinate subject, both atom populations
(residue/atom membership, hydrogen, solvent and alternate-conformer handling, and weighting),
their counts and mean B values, and the resulting ratio. If reporting local surroundings,
define the local shell's distance rule/cutoff, ligand atoms used, eligible neighbouring atoms
and symmetry handling. A global protein mean or all-model mean is not a local-surroundings
measurement; name that denominator explicitly. The ratio alone does not establish occupancy,
weak binding or a fit into noise; those interpretations require additional evidence.

For density-fit interpretation, see [Tickle (2012)][density] and the
[canonical registry](thresholds_and_standards.md). Keep model B values distinct from
prediction confidence and confidence-derived pseudo-B values.

### Outlier reporting

Retain residue/atom identifiers, the classification method and version, supporting values,
denominators and any comparison baseline. Include relevant lists as well as counts.
RSRZ is a standardized real-space residual requiring its reference distribution; a tool's
RSR or real-space correlation output is not automatically RSRZ. Difference-map peaks depend
on map construction and contour conventions and need interpretation, not an automatic
assignment to missing atoms. [wwPDB validation documentation][wwpdb-validation].

## 5. Represent the evidence in the current QDS implementation

The [schema](../schemas/protstruct_review.yaml) defines available representations;
[qds_emit.py](../scripts/qds_emit.py) and its retained contract modules define emission.
The current default is contract 4, which applies source corrections before projection.
An available schema slot does not guarantee a producer, metric mapping or emitted value.

1. Author source `EvaluationRun` records with canonical metric IDs, concrete `subject_ref`,
   stage, scope, tool provenance and retained evidence. Add `reference_subject_ref` for
   comparisons where applicable. Keep unsupported claims and missing measurements explicit.
2. For `scope=site` or `scope=ligand`, `scope_selector` is the exact declared `Site.id` or
   `Ligand.id`; put prose qualifiers in `notes`. Supply site membership and ligand declarations.
   The current builder requires each measured ligand to be bound to exactly one declared site.
3. Supply `per_residue_values`, outlier lists and other structured evidence in supported source
   slots. Provide scalar summaries explicitly where a supported metric routes them. Supply
   `mean`, `std_dev`, `min_value`, `max_value` and `count` when appropriate; the schema's
   reporting instructions require `count` with `mean`. State weighting and population/sample
   conventions. Supply any `percentile`
   with its reference population. Array retention does not automatically calculate these
   summaries or fill every schema field.
4. Check the actual routing tables. Current site scalar routes cover clashscore,
   Ramachandran outliers and Cα RMSD; schema fields such as site mean lDDT are not thereby
   populated. Verify count/percentage units rather than inferring them from a slot name.
   Confidence fields for pLDDT/PAE exist in the schema, but current routing does not populate
   their summaries; the routed T07 scalars cover pTM, ipTM and convergence. Retain original
   prediction outputs and document that reporting gap.
5. Separate the source interpretation from the numeric carrier. A new graded row needs an
   admitted `PassCriterionBinding` and evidence-backed applicability checks. The binding list
   is currently empty; no new pass/fail verdict follows merely from citing a threshold.
   Follow the repository validation and replay requirements before issuing a dated sheet.

A useful report identifies the question, exact subjects, available modality-specific fit,
geometry/local findings, relevant comparisons, coverage gaps and limitations. Its conclusion
should say which measures changed and what remains undecidable. Neither a complete-looking
QDS nor successful emission establishes that refinement improved a model.

[molprobity]: https://pmc.ncbi.nlm.nih.gov/articles/PMC5734394/ "Williams et al. (2018), MolProbity: more and better reference data for improved all-atom structure validation"
[refine-faq]: https://phenix-online.org/version_docs/dev-3329/faqs/refine.html "PHENIX refinement FAQ: R-free flags and interpretation"
[cc-star]: https://doi.org/10.1126/science.1218231 "Karplus & Diederichs (2012), Linking crystallographic model and data quality"
[data-quality]: https://journals.iucr.org/d/issues/2013/07/00/ba5190/index.html "Evans & Murshudov (2013), How good are my data and what is the resolution?"
[cryo-tools]: https://journals.iucr.org/d/issues/2018/09/00/kw5139/kw5139.pdf "Afonine et al. (2018), New tools for the analysis and validation of cryo-EM maps and atomic models"
[em-challenge]: https://www.nature.com/articles/s41592-020-01051-w "Lawson et al. (2021), Cryo-EM model validation recommendations based on outcomes of the 2019 EMDataResource challenge"
[af-faq]: https://alphafold.ebi.ac.uk/faq "AlphaFold Protein Structure Database FAQ"
[af3-output]: https://raw.githubusercontent.com/google-deepmind/alphafold3/main/docs/output.md "AlphaFold 3 output specification"
[pae]: https://www.ebi.ac.uk/training/online/courses/alphafold/inputs-and-outputs/evaluating-alphafolds-predicted-structures-using-confidence-scores/pae-a-measure-of-global-confidence-in-alphafold-predictions/ "EMBL-EBI AlphaFold PAE guidance"
[predicted-processing]: https://www.phenix-online.org/documentation/reference/process_predicted_model.html "PHENIX: Processing AlphaFold2, RoseTTAFold and other predicted models"
[gdt]: https://academic.oup.com/nar/article/31/13/3370/2904193 "Zemla (2003), LGA: a method for finding 3D similarities in protein structures"
[lddt]: https://doi.org/10.1093/bioinformatics/btt473 "Mariani et al. (2013), lDDT: a local superposition-free score for comparing protein structures and models using distance difference tests"
[pdb-redo]: https://pmc.ncbi.nlm.nih.gov/articles/PMC4107921/ "Joosten et al. (2014), The PDB_REDO server for macromolecular structure model optimization"
[density]: https://journals.iucr.org/d/issues/2012/04/00/dz5235/ "Tickle (2012), Statistical quality indicators for electron-density maps"
[wwpdb-validation]: https://www.wwpdb.org/validation/fetch?page=XrayValidationReportHelp "wwPDB X-ray validation report user guide"
