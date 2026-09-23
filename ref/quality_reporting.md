# Reporting protein-structure quality — what the field considers load-bearing

This doc is a synthesis of the community consensus on **the smallest defensible quality report** for two cases: (1) a single structure, and (2) a candidate vs. a reference structure. It is the evidence base for the `QualityDataSheet` LinkML class in this repo. Every metric named here can be reproduced by at least one non-cctbx oracle from `ref/oracle_tools.md`.

The trust model — **cross-tool agreement, never PHENIX-grading-PHENIX** — is itself a documented community principle (Joosten et al. 2012; Brink et al. 2021); see [§3](#3-cross-validation-is-the-principle-not-a-courtesy).

---

## 1. Single-structure report

The fields below are organised by **modality** (X-ray / cryo-EM / predicted) because the load-bearing metrics differ. The thresholds are **resolution-dependent** for X-ray and cryo-EM — always quote the metric next to the resolution it was measured at.

### 1.1 Geometry / stereochemistry — universal

These four are required for any model, regardless of modality. They come from the **MolProbity** / Richardson-lab framework and are computed by the `probe` + `reduce` standalone binaries (`ref/oracle_tools.md`).

| Metric | Tool | Good | Questionable | Bad |
|---|---|---|---|---|
| **Clashscore** (clashes ≥ 0.4 Å per 1000 atoms) | MolProbity (probe + reduce); `mmtbx.validation_summary` | < 5 | 5–15 | > 15 |
| **Ramachandran favored %** | MolProbity Top8000 reference | ≥ 95 (high res) / ≥ 90 (mid) / ≥ 80 (low) | 80–90 (mid res) | < 80 (mid res) |
| **Ramachandran outliers %** | MolProbity | < 0.3 | 0.3–2 | > 2 |
| **Rotamer outliers %** | MolProbity (probe + reduce) | < 1 | 1–3 | > 3 |
| **MolProbity score** (composite, log-scaled) | MolProbity | ≤ 1.5 | 1.5–2.0 | > 2.5 |

**Always report a percentile rank against the PDB archive at the same resolution** — this is what `mmtbx.validation_summary` and the wwPDB validation report give as `(percentile: NN.N)`. A clashscore of 8 might be 90th percentile at 3 Å but 30th percentile at 1.5 Å. Without context, the bare number is misleading (Williams et al. 2018).

The **MolProbity score** is the only single-number geometry summary the field treats as authoritative. It is calibrated so the value approximates the resolution at which that combination of clashscore + Ramachandran + rotamer would be average — a MolProbity score of 1.6 is "as good as a typical 1.6 Å structure."

### 1.2 X-ray model-vs-data

| Metric | Tool | Good | Caveat |
|---|---|---|---|
| **R-free** (5–10% test set) | `phenix.refine`, `phenix.model_vs_data`; `servalcat sigmaa`; gemmi sfcalc | ≤ resolution / 10 (rule of thumb, Evans & Murshudov 2013) | Always report alongside R-work. Never quote alone. |
| **R-work** | same | within 0.05 of R-free | Gap > 0.05 ⇒ overfitting suspect. |
| **CC*** | `phenix.model_vs_data`; CCP4 `aimless` (data side) | > 0.85 | Upper bound on CCwork; below 0.85 the data limits the model. |
| **Bond / angle RMSZ** | `phenix.holton_geometry_validation`; Servalcat | < 1 (angle), < 2 (bond) | RMSZ > 2.5 ⇒ over-refinement or refined-against-broken-restraints. |

The R-free rule of thumb (Brünger 1992; Evans & Murshudov 2013): expected R-free ≈ resolution_Å / 10. At 2.5 Å, ≤ 0.25; at 1.8 Å, ≤ 0.18. Numbers far above the expectation flag the model, not the data; numbers far below raise an overfitting flag.

**Never report the R-factors that come out of `phenix.refine`'s in-run log alone.** They incorporate the same bulk-solvent and scaling that drove the refinement. The catalog T06 oracle is `phenix.model_vs_data`, not `phenix.refine`'s log; the non-cctbx oracle is `gemmi sfcalc` plus an explicitly named R-factor estimator. On the same packaged 1SAR model, the historical PHENIX/gemmi R-free offset was +0.0020, not 0.013, and it is informational because no R-free-specific cross-tool benchmark is registered. The roughly 0.013 discrepancy was between an unretained round-7 claim and the packaged round-4 model, so it measured a model/package mismatch rather than same-model oracle agreement.

### 1.3 X-ray data quality

These are not model-quality metrics; they bound how good the model could possibly be. Report them on the same line as the resolution.

| Metric | Tool | Threshold | Note |
|---|---|---|---|
| **Completeness** (overall + outer shell) | data-processing log; `phenix.xtriage` | > 90% overall, > 70% in outer shell | Anisotropic data may legitimately drop. |
| **⟨I/σ(I)⟩** outer shell | data-processing log | > 1.5 (preferably > 2) | Sets the real resolution. Resolution claims with ⟨I/σ⟩ < 1.0 in outer shell are unsupported. |
| **CC½** outer shell | data-processing log | > 0.5 | Replaces R-merge as the resolution-cutoff diagnostic (Karplus & Diederichs 2012). |
| **R-merge / R-meas** | data-processing log | < 10% (overall) | Reproducibility of merging — does not measure model quality. |

### 1.4 Cryo-EM model-vs-map

| Metric | Tool | Good | Caveat |
|---|---|---|---|
| **CC_mask** (within mask of model) | `phenix.real_space_refine`, `phenix.map_correlations`; `servalcat fsc` | > 0.7 (typical), > 0.8 (excellent) | Always specify mask radius (1.5–2.0 Å). CC_box and CC_volume should also agree. |
| **d_FSC_model** (model–map FSC at 0.5) | `phenix.mtriage`; `servalcat fsc`; RELION `postprocess` | within 0.1 Å of global FSC at 0.143 | If d_FSC_model >> global FSC → underfit; if << → noise-fit. |
| **EMRinger** | EMRinger CLI | > 1.5 (high res) | Side-chain–density agreement; resolution-sensitive. |
| **Q-score** | MapQ ChimeraX plugin | depends on resolution | Per-atom, robust to over-sharpening. |

The 2019 EMDataResource cryo-EM validation challenge (Brink et al. 2021, *Nat. Methods*) found that single-metric reports are unreliable: validation tools cluster into roughly three families that disagree systematically across resolution ranges. The community recommendation is **map-model FSC + a residue-level metric (EMRinger or Q-score) + a global CC**, not any one of them alone.

### 1.5 Predicted-model confidence (AlphaFold / RoseTTAFold)

When the structure is a prediction, the relevant numbers are intrinsic to the predictor — there is no R-free, no FSC.

| Metric | Source | Bands |
|---|---|---|
| **Mean pLDDT** + distribution | AF2/3 output (B-factor column) | ≥ 90 very high · 70–90 high · 50–70 low · < 50 disordered (Jumper et al. 2021) |
| **pLDDT distribution shape** | derived | Bimodal sharp = confident core + disordered tails. Broad ≈ 70 = uncertain throughout. |
| **PAE matrix** (max, median, off-diagonal block min for multimers) | AF2/3 output (`*.json`) | < 5 Å confident relative position; > 15 Å unreliable |

`phenix.process_predicted_model` (catalog T07) trims and converts the prediction into a refinable model, and converts pLDDT into B-factors via `B = 1.5 / pLDDT²`. Report mean and distribution; **a single mean pLDDT is not a quality summary** — the spread is what tells you whether the structure is uniformly confident or hides disordered regions.

### 1.6 Antipatterns to avoid

These appear repeatedly in literature reviews and in the wwPDB validation guidance.

1. **Resolution as a quality proxy.** A 1.8 Å structure with R-free 0.30 and clashscore 25 is worse than a 2.8 Å structure with R-free 0.22 and clashscore 4. Resolution is the budget, not the result.
2. **R-work without R-free.** Always together. Always with the gap.
3. **Mean B-factor without distribution.** `<B>` is influenced by overall scaling. Bimodal core/surface distributions are normal and informative; the mean alone is not.
4. **Comparing B-factors across datasets.** Refinement-protocol-dependent. Cross-dataset B-factor differences are not interpretable (Merritt 2012).
5. **Geometry % without resolution context.** "85% Ramachandran favored" is bad at 1.5 Å, fine at 3.0 Å. Quote the resolution.
6. **PHENIX-grading-PHENIX.** The same code base that minimised the geometry restraints cannot be the only judge of how well they were minimised. Use MolProbity standalone, Servalcat, gemmi, REFMAC.
7. **Global score covering local problems.** Clashscore 5 globally is fine, but if 3 of those clashes sit in the active site, the model is broken in the place that matters. Always inspect locally for important sites.

---

## 2. Pair-of-structures report

The candidate is being compared against a **reference**. State up front which kind of reference: deposited PDB entry, AlphaFold model, refinement starting model, ground truth in a benchmark. The interpretation of every Δ-metric depends on this.

### 2.1 Global similarity — pick the right tool

| Metric | What it measures | When to use | When it lies |
|---|---|---|---|
| **CA RMSD** (LSQ-aligned) | Average pairwise Cα distance after global superposition | High-identity comparisons (refinement variants, NCS copies, redepositions). Cite alignment method, atom set, # aligned residues. | Domain motions inflate it even if local structure is correct. Length differences. Different space groups without symmetry-aware alignment. |
| **TM-score** | Length-normalised similarity, 0–1 | Cross-fold and cross-resolution comparisons. > 0.5 ≈ same fold (Zhang & Skolnick 2004). | Smooths out small but functionally critical local errors. |
| **GDT-TS / GDT-HA** | % Cα within 1/2/4/8 Å (TS) or 0.5/1/2/4 Å (HA) | CASP-style benchmarks; comparing predictions to experimental references. | Discrete cut-offs; less granular than lDDT for nearby structures. |
| **lDDT / lDDT-Cα** | Local distance preservation, **superposition-free** | Modern default. Catches local errors RMSD/TM-score smooth over. CASP15+ primary metric (Mariani et al. 2013). | Doesn't tell you about global topology — pair with TM-score for context. |

**Recommended default for the harness:** report TM-score *and* lDDT for every pair. RMSD is reported additionally because it is the legible number people read; it is not the basis for the verdict.

### 2.2 Local / per-residue comparison

| Metric | What it tells you |
|---|---|
| Per-residue Cα displacement (or per-residue lDDT) | Where the model agrees and where it diverges. Plot vs. residue index. Hot-spots > 2 Å are flagged. |
| ΔRamachandran outliers | New outliers introduced by refinement (bad) vs. inherited from reference (less bad). |
| ΔRotamer outliers | Same — track *new* outliers rather than the absolute count. |
| Active-site / interface RMSD | If the structure has a functional pocket, report a separate RMSD over those residues. A perfect global RMSD with a wrecked active site is still wrecked. |

### 2.3 Refinement comparisons (Δ model-vs-data)

When the candidate was refined against the same data as the reference (or against fresh data of the same target), report the Δ metrics — and **always state which baseline**.

| Δ metric | When | Interpretation |
|---|---|---|
| ΔR-free = R-free(candidate) − R-free(reference) | Same data | Negative ⇒ candidate fits data better. Within ±0.01 ⇒ equivalent. ΔR-free vs *starting model* answers a different question (refinement worked) than ΔR-free vs *deposited reference* (candidate is at least as good as gold). |
| ΔCC_mask | Cryo-EM, same map | Same logic, with CC_mask. Δ < 0.01 is noise. |
| ΔRMSD start→final | Refinement | If reference is the **starting** model: closer is *not* always better — overshooting (RMSD ≈ 0) vs. a mediocre starting model can mean overfitting. If reference is **truth**: smaller is better, with the caveats from §2.1. |

**ΔRMSD vs starting model and ΔRMSD vs reference truth answer different questions.** Mixing them — "candidate is 0.2 Å from starting and 0.4 Å from reference, refinement improved by 0.6 Å" — is incoherent. Report each separately, with the baseline named.

### 2.4 Pitfalls

1. **RMSD without context** — quote alignment method, atom set, # aligned residues. The 1SAR eval in this repo cites "0.43 Å (192/192 residues)" not "0.43 Å".
2. **Comparing across space groups without symmetry-aware alignment** — gemmi `align` with explicit handling, or restrict to one asymmetric unit.
3. **Treating an ensemble as a single model** — NMR ensembles, cryo-EM heterogeneity. Report mean ± stdev across ensemble members, not a single best-model number.
4. **ΔRMSD = 0 read as good** — if the reference is the starting model and the refinement chose to do nothing, that is bad. Refinement must move the model in the direction the data pulls; zero motion is a flag.
5. **Single-tool RMSD** — TM-align, gemmi, ChimeraX `matchmaker`, PHENIX `superpose_models` all answer slightly different questions. Two tools should agree within 0.1 Å on the same atom set.

---

## 3. Cross-validation is the principle, not a courtesy

The literature is explicit that single-validator reports are not trustworthy.

- **PDB-REDO** (Joosten et al. 2009, 2012) re-refines deposited X-ray structures with REFMAC and a different parameter regime. It exists precisely because PHENIX, REFMAC, and BUSTER produce different numbers from the same data, and only cross-tool consensus is robust.
- The **EMDataResource 2019 cryo-EM model-validation challenge** (Brink et al. 2021, *Nat. Methods*) tested ten validation tools across thirteen models. It found that fit-to-map metrics cluster into three families that disagree systematically across resolution. A report based on one family is not robust.
- The **wwPDB validation report** (Velankar et al. 2018) embeds this principle in its design — it always shows the value plus a percentile rank against the archive.

For this harness, the practical implication is the rule already in `ref/oracle_tools.md`: every metric in a report must have at least one independent (non-cctbx) measurement. The 1SAR evaluation closed this gap for T01 (TM-align), T03/T06 (gemmi sfcalc + Servalcat sigmaa), and T05 (probe + reduce). Future evals follow the same shape.

---

## 3a. Local quality — per-residue, per-site, per-ligand

Global metrics can pass while the active site is wrecked. Reviews of deposited structures (Read et al. 2011, *Structure*; PDB-REDO findings) consistently show that the average residue is fine and the failures cluster at active sites, interfaces, and weakly-supported loops. The schema covers this with three layers:

### Per-residue (scope = `residue`)

| Metric | What it tells you | Tool / source |
|---|---|---|
| **Per-residue lDDT** | Local distance preservation around each residue. Robust to global alignment errors. CASP15+ primary metric. | OpenStructure `lddt`; lDDT web service; Mariani et al. 2013. |
| **Per-residue Cα displacement** | Distance candidate-Cα to reference-Cα after global align. Plot vs. residue index; hot-spots > 2 Å are flagged regions. | gemmi script; ChimeraX matchmaker. |
| **RSRZ** | wwPDB validation report's per-residue real-space R-factor Z-score. RSRZ > 2 ⇒ poor density agreement at that residue. | wwPDB validation pipeline; phenix.real_space_correlation. |
| **Ramachandran outlier residue list** | The actual residue ids flagged, not just a percentage. | MolProbity `ramalyze`; phenix.holton_geometry_validation. |
| **Rotamer outlier residue list** | Same — list, not just %. | MolProbity `rotalyze`. |
| **C-β deviation residue list** | Residues with Cβ > 0.25 Å from ideal. | MolProbity. |
| **Difference-density peaks** (mFo−DFc > +4σ or < −4σ) | Unmodelled mass / atoms with no density. The driving example flags peaks > 4σ as load-bearing eval signal. | phenix.find_peaks_holes; CCP4 `peakmax`. |

**Reporting per-residue values** — store every value in the per-residue array AND surface a summary on the corresponding scalar slot. The schema's `TypedMeasurementValue` carries `value_numeric` (the scalar — usually the mean), plus `mean`, `std_dev`, `min_value`, `max_value`, and `count` so a summary can be reconstructed without downloading the full array. The full values live in `PerResidueQuality.lddt_per_residue[]`, `displacement_per_residue_a[]`, `rsrz_per_residue[]` etc. as a list of `PerResidueValue`.

### Per-site (scope = `site`)

A `Site` (active site, binding site, interface, metal-coordination sphere) is an explicit selection of residues. `SiteQuality` carries:

- site RMSD to a reference (computed only over the member residues)
- mean per-residue lDDT within the site
- site clashscore (clashscore restricted to atoms in member residues)
- site Ramachandran outlier count
- difference-density peaks within the site
- ligand quality (when a ligand is bound — see below)

A model can have global clashscore = 3 (great) and site clashscore = 18 (broken) in the active site. Without site-scoping, this fails silently.

### Per-ligand (scope = `ligand`)

For bound ligands the catalog T10 metrics are load-bearing:

| Metric | Threshold | Tool |
|---|---|---|
| **RSCC** (real-space correlation) | Corroboration only, with a matched limiting-radius convention; no fixed quality cutoff | phenix.real_space_correlation; CCP4 `edstats`; registry §2, “Real-space density fit (ligand/loop)”. |
| **RSR** (real-space R-factor) | Informational density-fit diagnostic; no fixed quality cutoff | same |
| **RSZD / RSZO** | Assess density accuracy / precision using registry §2, “Real-space density fit (ligand/loop)”, when these statistics and their inputs are available | CCP4 `edstats`; PDB-REDO `density-fitness` |
| **Ligand B vs. surrounding protein B** | ratio < 1.5 | phenix.b_factor_statistics |
| **Protein-ligand H-bond count** | informational | gemmi `contact`; PLIP |
| **Pose RMSD to deposited reference** | Informational pending a ligand-specific registry criterion; record reference, matched atom mapping, symmetry handling and common receptor frame | independent coordinate comparison; fitting the ligand alone measures conformation, not binding-site pose |

Report ligand RSCC when a ligand is structurally important, alongside the limiting-radius convention and available density diagnostics. RSCC and RSR do not supply B-factor-independent significance criteria (Tickle 2012); a high RSCC alone cannot establish a correct ligand. When RSZD/RSZO are unavailable, retain that evidence gap and keep RSCC/RSR informational instead of substituting an absolute cutoff. The same restriction applies to waters and loops.

### Outlier reporting

Always report outlier *lists*, not just outlier *counts*. A "0.5% Ramachandran outlier" rate is cheap when the outliers are buried in a flexible loop and load-bearing when one of them is a catalytic residue. The schema's `ResidueOutlier` class is the unit of report: one row per (residue, outlier-kind), with the outlier kind being one of `ramachandran` / `rotamer` / `c_beta` / `clash` / `cablam` / `cis_omega` / `bad_geometry` / `density_misfit`.

## 3b. Metric scope — every measurement says what it covers

Every `MeasurementValue` declares a `scope` (overriding the canonical scope on its `MetricDefinition` if needed):

| Scope | What it covers | Examples |
|---|---|---|
| `complex` | Whole asymmetric unit / biological assembly | global clashscore, R-free, MolProbity score |
| `chain` | One polypeptide / nucleic-acid chain | per-chain pLDDT mean, per-chain Ramachandran favored % |
| `site` | A named functional site | site RMSD, site clashscore |
| `residue` | A single residue or a residue array | per-residue lDDT, RSRZ |
| `atom` | A single atom or atom set | clash atom-pair list |
| `dataset` | Diffraction data / cryo-EM map (not the model) | completeness, ⟨I/σ⟩, CC½, R-merge |
| `ligand` | A bound ligand | RSCC, RSR, pose RMSD |

When `scope` is set to `residue`, `chain`, `atom`, or `ligand`, the measurement should also set `scope_selector` (free text — e.g. "chain A residues 30-45", "Asn A 39", "Ca²⁺ A 33") so a reader can locate what was measured without parsing the full array.

For per-residue / per-atom / per-chain measurements, populate **every value in the array slot** plus the scalar summary on `TypedMeasurementValue`: `mean`, `std_dev`, `min_value`, `max_value`, `count`. The summary is what the QDS surfaces; the array is what auditing tools and per-residue plots consume.

## 4. The minimal Quality Data Sheet

The fields below are the **smallest defensible** report. Anything beyond is fine; anything less leaves a downstream consumer guessing.

### 4.1 Single structure (X-ray)

```
identity:           PDB id, resolution, space group
data_quality:       completeness (overall, outer shell), ⟨I/σ⟩ outer, CC½ outer
model_vs_data:      R-work, R-free, gap, CC*, all by an independent oracle
                    (gemmi sfcalc, REFMAC, or Servalcat) — not by phenix.refine alone
geometry:           clashscore + percentile, Ramachandran favored % + outlier %,
                    rotamer outlier %, MolProbity score, bond/angle RMSZ
                    — all by MolProbity standalone (probe + reduce)
oracle_provenance:  which non-cctbx tool measured each metric
verdict:            one-paragraph human summary; pass/fail per declared criteria
```

### 4.2 Single structure (cryo-EM)

Same as X-ray, replacing the model-vs-data block:

```
model_vs_map:       CC_mask (with mask radius), CC_box, CC_volume,
                    d_FSC_model, EMRinger, Q-score (≥ 2 of these)
map_quality:        global FSC at 0.143, local resolution range
```

### 4.3 Single structure (predicted)

```
identity:           UniProt accession, predictor + version
confidence:         mean pLDDT, pLDDT distribution (sharp bimodal /
                    broad / narrow-high), PAE max & off-diagonal min
                    (multimers)
geometry:           clashscore, Ramachandran (post-processed model only)
oracle_provenance:  experimental reference if one exists (lDDT or RMSD vs. PDB)
```

### 4.4 Pair of structures

```
reference_kind:     deposited / AlphaFold / starting-model / ground-truth
alignment:          tool (TM-align, gemmi, ChimeraX), atom set, # aligned
similarity:         TM-score AND lDDT (mandatory pair)
                    CA RMSD with full context
local:              per-residue lDDT distribution; max displacement; flagged regions
delta_data:         ΔR-free or ΔCC_mask (state baseline: starting vs reference)
verdict:            improved / equivalent / worse / incomparable
```

### 4.5 When functional sites or ligands are present (mandatory additions)

A QDS without these is incomplete for any structure where downstream consumers care about the binding site:

```
sites:              one entry per active site / binding site / interface
                    each with: kind, member residue refs, ligand ref (if any)
site_qualities:     one entry per site with:
                      site_rmsd_to_reference_a (over member residues)
                      mean_per_residue_lddt
                      site_clashscore (atoms in members only)
                      site_ramachandran_outlier_count
                      site_density_peaks (Δρ peaks within the site)
                      ligand_quality (when ligand_ref is set)
ligand_quality:     RSCC and RSR (informational; matched-radius RSCC corroboration),
                    ligand_b_factor_vs_surroundings,
                    protein_ligand_hbond_count,
                    pose_rmsd_to_deposited_a
per_residue_quality: lddt_per_residue[], displacement_per_residue_a[],
                    rsrz_per_residue[], outliers[] (ResidueOutlier list),
                    density_peaks[], flagged_regions[]
```

For per-residue arrays, the QDS surfaces summary statistics (mean ± std_dev, min, max, count) on the matching scalar slot; full values live in the array.

---

## 5. References

These are the citable sources for every threshold and rule above. The reference column in the QualityDataSheet schema should point at one of these.

1. **Brünger, A. T. (1992).** Free R value: a novel statistical quantity for assessing the accuracy of crystal structures. *Nature* 355, 472–475. [R-free as cross-validation]
2. **Davis, I. W. et al. (2007).** MolProbity: all-atom contacts and structure validation for proteins and nucleic acids. *Nucleic Acids Research* 35, W375–W383. [Original MolProbity, clashscore]
3. **Williams, C. J. et al. (2018).** MolProbity: more and better reference data for improved all-atom structure validation. *Protein Science* 27, 293–315. [Top8000, current MolProbity thresholds]
4. **Karplus, P. A. & Diederichs, K. (2012).** Linking crystallographic model and data quality. *Science* 336, 1030–1033. [CC½, CC*]
5. **Evans, P. R. & Murshudov, G. N. (2013).** How good are my data and what is the resolution? *Acta Cryst. D* 69, 1204–1214. [R-free expectations vs. resolution; CC*]
6. **Joosten, R. P., Long, F., Murshudov, G. N. & Perrakis, A. (2012).** The PDB_REDO server for macromolecular structure model optimization. *IUCrJ* 1, 213–220. [PDB-REDO, multi-validator philosophy]
7. **Velankar, S. et al. (2018).** wwPDB Validation Report: a working tool for validating macromolecular structures. *Acta Cryst. D* 74, 200–209. [wwPDB validation specification]
8. **Afonine, P. V. et al. (2018).** New tools for the analysis and validation of cryo-EM maps and atomic models. *Acta Cryst. D* 74, 814–840. [CC_mask, CC_box, CC_volume, mtriage]
9. **Brink, J., Carragher, B. et al. (2021).** Outcomes of the 2019 EMDataResource model-vs-map challenge. *Nature Methods* 18, 156–164. [Multi-validator cryo-EM consensus]
10. **Yamashita, K. et al. (2021).** Cryo-EM single-particle structure refinement and map calculation using Servalcat. *Acta Cryst. D* 77, 1282–1291. [Servalcat as independent cryo-EM oracle]
11. **Zhang, Y. & Skolnick, J. (2004).** Scoring function for automated assessment of protein structure template quality. *Proteins* 57, 702–710. [TM-score definition and 0.5 threshold]
12. **Zemla, A. (2003).** LGA: a method for finding 3D similarities in protein structures. *Nucleic Acids Research* 31, 3370–3374. [GDT-TS / GDT-HA]
13. **Mariani, V., Biasini, M., Barbato, A. & Schwede, T. (2013).** lDDT: a local superposition-free score for comparing protein structures and models using distance difference tests. *Bioinformatics* 29, 2722–2728. [lDDT, modern standard for model comparison]
14. **Jumper, J. et al. (2021).** Highly accurate protein structure prediction with AlphaFold. *Nature* 596, 583–589. [pLDDT bands, AlphaFold output]
15. **Varadi, M. et al. (2022).** AlphaFold Protein Structure Database. *Nucleic Acids Research* 50, D439–D444. [pLDDT and PAE for predicted models at scale]
16. **Word, J. M. et al. (1999).** Asparagine and glutamine: using hydrogen-atom contacts in the choice of side-chain amide orientation. *J. Mol. Biol.* 285, 1735–1747. [reduce, H-placement underlying clashscore]
17. **Kidmose, R. T. et al. (2019).** Namdinator — automatic molecular dynamics flexible fitting of structural models into cryo-EM and crystallography experimental maps. *IUCrJ* 6, 526–531. [orthogonal cryo-EM refinement oracle, listed here for completeness]
18. **Pintilie, G. et al. (2020).** Measurement of atom-resolvability in cryo-EM maps with Q-scores. *Nature Methods* 17, 328–334. [Q-score]
19. **Read, R. J. et al. (2011).** A new generation of crystallographic validation tools for the Protein Data Bank. *Structure* 19, 1395–1412. [wwPDB validation report design; per-residue RSRZ]
20. **Tickle, I. J. (2012).** Statistical quality indicators for electron-density maps. *Acta Cryst. D* 68, 454–467. [RSZD/RSZO significance and limitations of RSCC/RSR]
21. **Pozharski, E. et al. (2013).** Techniques, tools and best practices for ligand electron-density analysis and results from their application to deposited crystal structures. *Acta Cryst. D* 69, 150–167. [Mismodelled ligands flagged by RSCC across the PDB]
22. **Smart, O. S. et al. (2018).** Validation of ligands in macromolecular structures determined by X-ray crystallography. *Acta Cryst. D* 74, 228–236. [Ligand validation pipeline; pose-RMSD and RSCC standards]

URLs for tooling cited inline (not bibliographic, but useful from the harness):

- wwPDB validation report: <https://www.wwpdb.org/validation/validation-reports>
- MolProbity standalone (probe + reduce): <https://github.com/rlabduke/MolProbity>
- TM-align / TM-score: <https://zhanggroup.org/TM-align/>
- Servalcat: <https://github.com/keitaroyam/servalcat>
- gemmi: <https://gemmi.readthedocs.io/>
