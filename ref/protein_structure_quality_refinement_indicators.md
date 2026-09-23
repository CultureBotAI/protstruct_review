# Protein Structure Quality and Refinement Indicators

Issued: 2026-05-05

This report identifies protein-structure measurements, scores, classifications,
and before/after refinement signals that could be represented in the ontology.
It is scoped as additions or promotions beyond the current core Quality Data
Sheet coverage.

The existing project already covers many load-bearing concepts, including
MolProbity geometry, R-work/R-free, X-ray data quality, cryo-EM CC/FSC/EMRinger
/ Q-score, pLDDT/PAE, RMSD/TM/GDT/lDDT, RSRZ, density peaks, ligand/site
quality, and hydrogen/protonation checks. See:

- `schemas/protstruct_review.yaml`
- `ref/catalog.yaml`
- `ref/quality_reporting.md`

## Candidate Concepts

| Candidate | Measures | Scope | Source/tool | Use | Refinement signal | Suggested term | Parent/category | Caveat |
|---|---|---:|---|---|---|---|---|---|
| CaBLAM severity/profile | Backbone geometry at lower resolution | residue/region | MolProbity, Phenix | experimental/refined | fewer severe backbone flags | `cablam_severity_profile` | backbone validation | Already partly present; promote to summary |
| Ramachandran-Z | Whole Ramachandran distribution normality | global | PDB-REDO, WHAT_CHECK | all | Z closer to expected range | `ramachandran_z_score` | stereochemical validation | More informative than "0 outliers" |
| Unsatisfied buried H-bonds | Bad packing/polar burial | residue/site/global | MolProbity/RosettaHoles-style validation | all | count decreases, especially core/site | `unsatisfied_buried_hbond_count` | packing validation | Needs robust H placement |
| Packing/holes Z-score | Core packing and voids | global/region | RosettaHoles2, PDB-REDO | all | fewer holes, better packing percentile | `packing_z_score` | packing validation | Sensitive to waters and resolution |
| Per-residue RSCC | Informational local density correlation | residue/site | wwPDB, EDSTATS, Phenix | X-ray/refined | descriptive comparison only | `residue_rscc` | local model-data fit | Match limiting-radius convention; significance requires other evidence under registry §2 |
| RSCC outlier fraction (legacy name) | Informational fraction below a stated reporting cutoff | chain/global | RCSB/wwPDB-style | X-ray/refined | no directional quality verdict | `rscc_outlier_fraction` | local model-data fit | Record cutoff, radius convention and denominator; no B-factor-independent significance criterion (registry §2) |
| ADP/B-factor outlier Z | Local mobility/support mismatch | atom/residue | wwPDB, Phenix, REFMAC | experimental/refined | extreme local B outliers decrease | `b_factor_outlier_z` | uncertainty/flexibility | Cross-dataset B values are not comparable |
| Occupancy/altloc consistency | Partial occupancy modeling quality | atom/residue/ligand | Coot, Phenix, wwPDB | experimental/refined | occupancies sum correctly; fewer clashes | `alternate_conformation_consistency` | model completeness | Hard to score globally |
| Coordinate precision/DPI | Estimated coordinate uncertainty | global | REFMAC, BUSTER, PDB-REDO | X-ray/refined | lower uncertainty at same data quality | `diffraction_precision_index` | uncertainty | Data-quality dependent |
| PDB-REDO change class | Constructive validation outcome | global | PDB-REDO | X-ray/refined | improved/equivalent/worse class | `redo_improvement_class` | refinement trajectory | Best as external comparison, not truth |
| R-free monotonicity/stability | Overfitting/refinement stability | trajectory | Phenix, REFMAC, Servalcat | refined | final improves without late rebound | `r_free_trajectory_stability` | refinement trajectory | Small deltas can be scaling noise |
| DSSP/STRIDE assignment | Secondary-structure annotation | residue/region | DSSP, STRIDE | all | helices/sheets become more coherent | `secondary_structure_assignment` | structural classification | Classification, not direct quality |
| Secondary-structure agreement | Candidate vs reference secondary-structure match | residue/region/global | DSSP, STRIDE | predicted/refined | fewer secondary-structure flips in stable regions | `secondary_structure_agreement` | pairwise comparison | Loops/flexible regions may legitimately change |
| Domain boundary classification | Domain segmentation | domain | CATH, SCOPe, ECOD, PAE splitters | all | refined model preserves plausible domains | `structural_domain_assignment` | domain classification | Databases lag new PDB entries |
| Fold/superfamily class | Fold context | domain | CATH/SCOPe/ECOD | all | confirms fold after refinement | `fold_classification` | domain classification | Not a refinement score by itself |
| Hinge/domain-motion class | Rigid-body vs local change | domain/pair | DynDom-style, PAE/domain comparison | refined/predicted | separates real domain motion from distortion | `domain_motion_class` | pairwise comparison | Needs reference or ensemble |
| Interface buried surface area | Interface plausibility | interface/site | PISA/PDBePISA | complexes | plausible buried surface area maintained/improved | `interface_buried_surface_area` | interface quality | Crystal contacts can mislead |
| Interface free energy / assembly call | Biological vs crystal interface | assembly/interface | PISA | experimental complexes | better assembly plausibility | `assembly_stability_class` | assembly quality | Thermodynamic estimate, not definitive |
| DockQ/CAPRI class | Complex/interface accuracy | interface/complex | DockQ, CAPRI | predicted/refined complexes | class improves; DockQ increases | `interface_dockq_score` | interface quality | Requires native/reference complex |
| Fnat/iRMSD/LRMSD | Interface contact recovery and pose | interface | CAPRI/DockQ | predicted/refined complexes | higher Fnat, lower RMSDs | `capri_interface_quality_class` | interface quality | Reference-dependent |
| AlphaFold pTM/ipTM | Global/interface prediction confidence | global/interface | AlphaFold/ColabFold | predicted/refined starts | higher interface confidence; lower PAE | `predicted_tm_score`, `interface_predicted_tm_score` | prediction confidence | Not experimental validation |
| Model convergence across seeds | Prediction robustness | global/domain/interface | AlphaFold/ColabFold | predicted | top models converge on same fold/interface | `prediction_ensemble_convergence` | prediction confidence | Can converge on the same wrong answer |
| QMEANDisCo / ProSA / Verify3D | Single-model statistical plausibility | global/residue | SWISS-MODEL QMEAN, ProSA, Verify3D | predicted/homology | local unreliable regions shrink | `single_model_quality_estimate` | model-quality estimate | Lower priority than experimental fit |
| 3DFSC anisotropy | Directional map resolution | map/dataset | cryoSPARC 3DFSC | cryo-EM | less severe directional anisotropy | `directional_resolution_anisotropy` | map quality | Map quality, not model quality |
| FSC-Q / atom inclusion | Local model-map fit/overfit check | atom/residue/region | FSC-Q, wwPDB EM validation | cryo-EM/refined | local fit improves without overfitting | `local_model_map_fsc_q` | model-map fit | Resolution and sharpening sensitive |
| NMR restraint violations | Agreement with NOE/restraint data | ensemble/residue | wwPDB NMR, PROCHECK-NMR, RPF | NMR/refined | fewer/max smaller violations | `nmr_restraint_violation_summary` | NMR validation | Only for restraint-backed models |
| NMR ensemble precision | Conformer spread in defined regions | ensemble/region | wwPDB NMR | NMR/refined | lower RMSD in well-defined core | `nmr_ensemble_precision_rmsd` | uncertainty/flexibility | Precision is not accuracy |

## Recommended Ontology Categories

Add or promote these higher-level categories:

- `PackingValidationMetric`
- `InterfaceQualityMetric`
- `StructuralClassification`
- `DomainClassification`
- `PredictionConfidenceMetric`
- `RefinementTrajectoryMetric`
- `NMRValidationMetric`

Highest-value concrete terms to add or promote:

- `ramachandran_z_score`
- `packing_z_score`
- `unsatisfied_buried_hbond_count`
- `residue_rscc`
- `secondary_structure_assignment`
- `structural_domain_assignment`
- `interface_buried_surface_area`
- `interface_dockq_score`
- `interface_predicted_tm_score`
- `prediction_ensemble_convergence`
- `directional_resolution_anisotropy`
- `nmr_restraint_violation_summary`

## Implementation Plan

### Phase 1: Schema Vocabulary

1. Extend `schemas/protstruct_review.yaml` with enums/classes for the new
   concept families:
   - `StructuralClassificationKind`
   - `DomainClassificationKind`
   - `InterfaceQualityKind`
   - `PredictionConfidenceKind`
   - `NmrValidationKind`
2. Add `MeasurementScope` values only if needed. The current scopes cover most
   additions; likely additions are:
   - `domain`
   - `interface`
   - `ensemble`
   - `assembly`
3. Add structured classes where scalar `MeasurementValue` is insufficient:
   - `SecondaryStructureAssignment`
   - `DomainAssignment`
   - `InterfaceQuality`
   - `NmrEnsembleQuality`
   - `PredictionEnsembleQuality`

### Phase 2: Catalog Additions

1. Add new metric definitions to `ref/catalog.yaml`.
2. Reuse existing catalog tasks where possible:
   - T02 for secondary-structure agreement and domain-motion comparison.
   - T05 for Ramachandran-Z, packing, buried H-bonds, ADP/B-factor outliers,
     occupancy/altloc consistency.
   - T06 for per-residue RSCC and coordinate precision.
   - T07 for pTM, ipTM, and prediction ensemble convergence.
   - T12 for 3DFSC anisotropy and FSC-Q.
3. Add new tasks only where current task boundaries become awkward:
   - `T15 Structural/domain classification`
   - `T16 Interface and assembly quality`
   - `T17 NMR ensemble/restraint validation`

### Phase 3: Quality Data Sheet Surface

1. Add optional QDS summary blocks:
   - `packing_summary`
   - `classification_summary`
   - `interface_quality_summary`
   - `prediction_ensemble_summary`
   - `nmr_validation_summary`
2. Extend `PerResidueQuality` with:
   - `rscc_per_residue`
   - `b_factor_z_per_residue`
   - `secondary_structure_per_residue`
   - `fsc_q_per_residue`
3. Extend `SiteQuality` or create `InterfaceQuality` for interface-specific
   metrics:
   - buried surface area
   - interface free-energy estimate
   - DockQ
   - CAPRI class
   - Fnat
   - iRMSD
   - LRMSD

### Phase 4: Tool and Oracle Mapping

1. Add canonical tools to `ref/catalog.yaml`:
   - DSSP
   - STRIDE
   - CATH
   - SCOPe
   - ECOD
   - PISA/PDBePISA
   - DockQ
   - PDB-REDO
   - RosettaHoles2
   - QMEANDisCo
   - ProSA
   - Verify3D
   - 3DFSC
   - FSC-Q
   - wwPDB NMR validation
   - PROCHECK-NMR
   - RPF
2. Mark each tool as `non_cctbx` unless it is explicitly a Phenix/cctbx tool.
3. Add tool assumptions for resolution dependence, reference distributions,
   threshold provenance, and reference-structure requirements.

### Phase 5: Emitters and Validation

1. Update `scripts/qds_emit.py` to aggregate the new summaries.
2. Update `scripts/tsv_to_records.py` and `scripts/records_to_tsv.py` if new
   metric fields need round-tripping.
3. Add referential-integrity checks for new structured references:
   - domain references
   - interface references
   - ensemble/model references
4. Add test fixtures under `data/examples/` for:
   - one X-ray structure with packing/RSCC additions
   - one AlphaFold/complex prediction with pTM/ipTM/DockQ
   - one cryo-EM structure with 3DFSC/FSC-Q
   - one NMR ensemble with restraint violations

### Phase 6: Prioritization

Implement in this order:

1. Low-risk scalar additions:
   - `ramachandran_z_score`
   - `residue_rscc`
   - `rscc_outlier_fraction`
   - `diffraction_precision_index`
2. Refinement and packing additions:
   - `packing_z_score`
   - `unsatisfied_buried_hbond_count`
   - `r_free_trajectory_stability`
3. Classification additions:
   - `secondary_structure_assignment`
   - `structural_domain_assignment`
   - `fold_classification`
4. Interface additions:
   - `interface_buried_surface_area`
   - `interface_dockq_score`
   - `capri_interface_quality_class`
5. Modality-specific additions:
   - `directional_resolution_anisotropy`
   - `local_model_map_fsc_q`
   - `nmr_restraint_violation_summary`

## Sources

- wwPDB X-ray validation: https://remediation.wwpdb.org/validation/XrayValidationReportHelp
- MolProbity validation: https://molprobity.manchester.ac.uk/help/validation_options/validation_options.html
- CaBLAM in Phenix: https://phenix-online.org/documentation/reference/cablam_validation.html
- PDB-REDO: https://pdb-redo.eu/
- DSSP 4: https://pmc.ncbi.nlm.nih.gov/articles/PMC12268231/
- CATH: https://www.cathdb.info/
- SCOPe: https://scop.berkeley.edu/help/
- AlphaFold 3 outputs: https://github.com/google-deepmind/alphafold3/blob/main/docs/output.md
- QMEAN: https://swissmodel.expasy.org/qmean/help
- PISA: https://cloud.ccp4.ac.uk/manuals/html-taskref/doc.task.PISA.html
- DockQ: https://journals.plos.org/plosone/article?id=10.1371%2Fjournal.pone.0161879
- wwPDB NMR validation: https://www.wwpdb.org/validation/NMRValidationReportHelp
- Cryo-EM validation challenge: https://pmc.ncbi.nlm.nih.gov/articles/PMC7864804/
