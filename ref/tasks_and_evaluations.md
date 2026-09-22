# Rote structural-biology tasks × evaluation methods

This is the **key reference table** for the protstruct-review harness. Each row is a routine structural-biology operation an agent must be able to carry out (using PHENIX and/or related tools), paired with:

- The PHENIX tool(s) expected to perform it.
- **Independent oracle tool(s)** used by the harness to evaluate whether the agent's output is correct (cross-tool agreement is the primary trust signal — we do not grade PHENIX output with PHENIX alone).
- Typical inputs, concrete evaluation metrics, a gold-standard source, and an example dataset for reproducibility.

PHENIX documentation paths below are upstream routes. The repository does not distribute a mirror;
`ref/download_phenix_docs.sh` can create an ignored local cache after the user reviews the upstream
terms. TSV form with the same rows: `ref/tasks_and_evaluations.tsv`.

## Legend

- **PHENIX tool(s):** primary implementation, CLI entry points in `phenix.<tool>` form where applicable.
- **Independent oracle(s):** non-PHENIX tools that compute the same (or a comparable) metric, used for cross-checking. At least one is listed per task — if none is available, that is called out explicitly.
- **Metric(s):** numeric deliverables the harness records. Thresholds/pass criteria live in the per-task driving-example files, not here.
- **Gold standard:** source of ground truth (deposited PDB/EMDB entry, paper benchmark, cross-tool consensus, held-out original).
- **Example dataset:** a concrete identifier so an evaluation run is reproducible without scavenger-hunting for data.

## Task catalog

### T01 — Structure superposition + RMSD

- **PHENIX tool(s):** `phenix.superpose_models` (LSQ / SSM), `phenix.chain_comparison`
- **Doc paths:** `reference/superpose_models.html`, `reference/chain_comparison.html`
- **Independent oracle(s):** ChimeraX `matchmaker`, PyMOL `align` / `super` / `cealign`, TM-align, gemmi `align`, US-align
- **Typical inputs:** fixed PDB, moving PDB; optional chain/atom selection
- **Metrics:** CA RMSD (Å), all-atom RMSD (Å), number of aligned residues, TM-score, GDT-TS, per-residue ΔCA
- **Gold standard:** cross-tool RMSD agreement (PHENIX vs ChimeraX within ≤ 0.1 Å on aligned atoms); or deposition-time reference pose
- **Example dataset:** any pair of near-identical structures, e.g. `1UBQ` vs `1UBI` (ubiquitin redeterminations), or a held-out deposited structure vs its AlphaFold model

### T02 — Per-residue structural comparison

- **PHENIX tool(s):** `phenix.structure_comparison`
- **Doc paths:** `reference/structure_comparison.html`
- **Independent oracle(s):** ProSMART, LSQMAN, PyMOL `rms_cur` with per-residue loop, custom gemmi script
- **Typical inputs:** two or more near-identical PDBs (different crystal forms, mutants, NCS copies); optional sequence file; optional maps
- **Metrics:** per-residue Ramachandran / rotamer outlier differences, secondary-structure agreement, B-factor deltas, ligand centre-of-mass distances, omega angle (cis/trans) flips, histidine protonation differences
- **Gold standard:** cross-tool per-residue agreement; manual Coot inspection for hotspots
- **Example dataset:** paired lysozyme mutant structures, or NCS copies from a single asymmetric unit

### T03 — Reciprocal-space refinement (X-ray)

- **PHENIX tool(s):** `phenix.refine`, `phenix.den_refine`, `phenix.rosetta_refine`, `phenix.amber`
- **Doc paths:** `reference/refinement.html`, `reference/den_refine.html`, `reference/rosetta_refine.html`, `reference/amber.html`
- **Independent oracle(s):** REFMAC5 (CCP4), BUSTER (Global Phasing), Servalcat
- **Typical inputs:** starting model (PDB), reflection data (MTZ with F/SIGF + R-free flags), optional ligand restraint CIFs
- **Metrics:** R-work, R-free, R-free − R-work gap, ΔR-free vs input, bond/angle RMSD, MolProbity score, clashscore, Ramachandran favored %
- **Gold standard:** deposited R-values for the target PDB; REFMAC-refined variant produces comparable R-free (within ~0.01–0.02)
- **Example dataset:** PDB `1YQV` (Phaser/phenix.refine tutorial), or any deposited structure with public MTZ (PDB-REDO supplies these)

### T04 — Real-space refinement (map-based)

- **PHENIX tool(s):** `phenix.real_space_refine`, `phenix.varref` (variability-aware)
- **Doc paths:** `reference/real_space_refine.html`, `reference/varref.html`
- **Independent oracle(s):** Servalcat, ISOLDE (interactive, ChimeraX-embedded), REFMAC real-space, Rosetta `cryo_em_refinement`
- **Typical inputs:** starting model (PDB), map (MRC/CCP4), resolution estimate
- **Metrics:** map-model CC_mask, CC_box, CC_peaks, CC_volume, d_FSC_model (resolution at which model-map FSC = 0.5), ΔCC vs input, clashscore, Ramachandran favored %
- **Gold standard:** deposited refined model for the same EMDB entry; Servalcat second opinion on CC/FSC
- **Example dataset:** EMDB-`11668` / PDB `7a4m` (apoferritin, high-res), or EMDB-`20646` / PDB `6u42`

### T05 — Geometry validation

- **PHENIX tool(s):** `phenix.holton_geometry_validation`, `phenix.validation` (GUI), `phenix.cablam`, `mmtbx.validation_summary`
- **Doc paths:** `reference/holton_geometry_validation.html`, `reference/validation.html`, `reference/cablam_validation.html`
- **Independent oracle(s):** **MolProbity** (web/standalone — gold standard for geometry), wwPDB validation pipeline, iotbx-independent parsers via gemmi, RosettaHoles2 (packing), ProSA, Verify3D
- **Typical inputs:** model (PDB/mmCIF)
- **Metrics:** clashscore, Ramachandran favored %, Ramachandran outlier %, rotamer outlier %, CBeta outliers, bond-length RMSD, bond-angle RMSD, planarity RMSD, chirality outliers, MolProbity composite score, CaBLAM outliers, Ramachandran-Z score, packing Z-score (complex), unsatisfied buried H-bond count (complex), B-factor outlier Z-score (per-residue)
- **Gold standard:** MolProbity report; wwPDB validation report for deposited comparator
- **Example dataset:** any PDB entry; for regression use `3nir` (ultra-high-res crambin) as a clean baseline

### T06 — Model-vs-data statistics

- **PHENIX tool(s):** `phenix.model_vs_data`, `phenix.mtriage` (map side), `phenix.fmodel` (listed in the PHENIX reference index but its doc page currently 404s upstream), `phenix.map_correlations`
- **Doc paths:** `reference/model_vs_data.html`, `reference/mtriage.html`, `reference/map_correlations.html`
- **Independent oracle(s):** CCP4 `sfcheck` / `refmac -hklin`, Servalcat, `gemmi` (`gemmi sfcalc`, `gemmi validate`), PDB-REDO, FSC-Q
- **Typical inputs:** model + experimental data (MTZ for X-ray, map(s) for cryo-EM)
- **Metrics:** R-work, R-free, CC_work, CC_free, CC*, map-model FSC (global + per-resolution-shell), d_FSC_model, overall B, Wilson B, residue RSCC (per-residue), RSCC outlier fraction (complex), diffraction precision index (complex)
- **Gold standard:** values reported in the deposition header for that PDB/EMDB pair
- **Example dataset:** PDB `1YQV` + deposited MTZ; PDB `7a4m` + EMDB-`11668` half-maps

### T07 — Predicted-model processing

- **PHENIX tool(s):** `phenix.process_predicted_model`, `phenix.predict_model`, `phenix.predict_and_build`
- **Doc paths:** `reference/process_predicted_model.html`, `reference/predict_model.html`, `reference/predict_and_build.html`, `overviews/predicted_models_index.html`
- **Independent oracle(s):** `pae_to_domains.py` (Croll/Tronrud), `biotite` AlphaFold parsers, `colabfold` domain-splitter, ChimeraX `alphafold` tool, QMEANDisCo
- **Typical inputs:** AlphaFold/RoseTTAFold prediction (PDB/mmCIF) with pLDDT in B-factor column, optional PAE matrix (JSON)
- **Metrics:** fraction of residues retained after pLDDT trim, mean pLDDT before/after, B-factor ↔ (1/pLDDT²) correlation post-conversion, domain count agreement vs PAE-clustering oracle, RMSD of processed model vs reference experimental structure, predicted TM-score (complex), interface predicted TM-score (interface), prediction ensemble convergence (ensemble)
- **Gold standard:** AlphaFold-DB deposited pLDDT values; experimental structure for the same UniProt entry (when one exists) for downstream RMSD
- **Example dataset:** `AF-P00698-F1` (lysozyme AF2 model) vs PDB `2LYZ`; `AF-P0DTC2-F1` (SARS-CoV-2 spike) vs `6VXX`

### T08 — Docking predicted/homology model into a map

- **PHENIX tool(s):** `phenix.dock_predicted_model`, `phenix.dock_in_map`, `phenix.em_placement`, `phenix.dock_and_rebuild`
- **Doc paths:** `reference/dock_predicted_model.html`, `reference/dock_in_map.html`, `reference/em_placement.html`, `reference/dock_and_rebuild.html`
- **Independent oracle(s):** UCSF ChimeraX `fitmap`, Situs `colores` / `collage`, gmfit, cryoSPARC flex-refine rigid body
- **Typical inputs:** predicted/homology model, cryo-EM map, optional mask / rough centre guess
- **Metrics:** placement CC, ΔCC vs random placement, RMSD to deposited (ground-truth) position, translation / rotation error, `em_placement` LLG
- **Gold standard:** deposited EMDB-PDB pair (rigid-body superpose deposited model onto agent's placed model)
- **Example dataset:** EMDB-`20646` / PDB `6u42` (ribosome subunit or similar medium-resolution target with a clear AlphaFold handle)

### T09 — Molecular replacement

- **PHENIX tool(s):** `phenix.phaser` (Phaser MR), `phenix.MRage`, `phenix.mr_rosetta`, `phenix.morph_model`, `phenix.sculptor`, `phenix.ensembler`
- **Doc paths:** `reference/phaser_mr.html`, `reference/MRage.html`, `reference/mr_rosetta.html`, `reference/morph_model.html`, `reference/sculptor.html`, `reference/ensembler.html`, `reference/phaser.html`
- **Independent oracle(s):** MoRDa (automated MR), CCP4 `Phaser` standalone, ARCIMBOLDO, MOLREP
- **Typical inputs:** search model (PDB, often trimmed AlphaFold), reflection data (MTZ), target sequence, expected copies per ASU
- **Metrics:** Phaser TFZ-score, LLG, translation/rotation of top solution, post-MR R-free after a short refine run, time-to-solution
- **Gold standard:** deposited structure — MR top solution should superpose on deposited pose within a few Å CA RMSD
- **Example dataset:** PDB `1YQV` MR tutorial data (Phaser tutorial); any AlphaFold-guided MR benchmark target

### T10 — Ligand fitting

- **PHENIX tool(s):** `phenix.ligandfit`, `phenix.ligand_pipeline`, `phenix.find_all_ligands`, `phenix.eLBOW` (restraint generation), `phenix.REEL` (restraint editing), `phenix.guided_ligand_replacement`
- **Doc paths:** `reference/ligandfit.html`, `reference/ligand_pipeline.html`, `reference/find_all_ligands.html`, `reference/elbow.html`, `reference/reel.html`, `reference/guided_ligand_replacement.html`
- **Independent oracle(s):** Coot `Find Ligand`, AFITT (OpenEye), rhofit (Global Phasing), CCP4 `libcheck` / `acedrg` for restraints
- **Typical inputs:** apo (or ligand-free) model, map / MTZ, ligand SMILES or coordinates
- **Metrics:** ligand RSCC (real-space correlation coefficient), ligand RSR (real-space R), ligand B-factor vs surroundings, protein-ligand hbond count, RMSD to deposited ligand pose
- **Gold standard:** deposited holo structure for the same complex (PDB co-crystal entry)
- **Example dataset:** PDB `1OYT` (factor Xa + inhibitor); PHENIX `ligandfit` tutorial data

### T11 — Loop / missing-region fitting

- **PHENIX tool(s):** `phenix.fit_loops`, `phenix.fix_insertions_deletions`, `phenix.fit_loops` (real-space), `phenix.rebuild_model`
- **Doc paths:** `reference/fit_loops.html`, `reference/fix_insertions_deletions.html`, `reference/rebuild_model.html`
- **Independent oracle(s):** Coot `Fit Loop…` (DB / Rama-search), ModLoop (web), Rosetta `loopmodel`, Sphinx / `RosettaCM`
- **Typical inputs:** model with a gap, sequence of the missing segment, map / density (for real-space fits)
- **Metrics:** loop RSCC, Ramachandran favored-% within loop, RMSD of rebuilt loop vs reference loop, #outliers introduced vs baseline
- **Gold standard:** deposited full model (remove a loop, rebuild it, compare to the held-out segment)
- **Example dataset:** any mid-resolution structure with a disorder-prone loop — e.g. PDB `3KEE` has a flexible HIV-1 protease flap; or delete residues 60–70 from `3NIR` and rebuild

### T12 — Map quality assessment (cryo-EM)

- **PHENIX tool(s):** `phenix.mtriage`, `phenix.local_resolution`, `phenix.map_sharpening`, `phenix.resolve_cryo_em`
- **Doc paths:** `reference/mtriage.html`, `reference/local_resolution.html`, `reference/map_sharpening.html`, `reference/resolve_cryo_em.html`, `overviews/cryo-em_index.html`
- **Independent oracle(s):** RELION `postprocess`, cryoSPARC 3DFSC, ResMap, Phenix-independent `gemmi fprime`, `e2proc3d.py` (EMAN2), 3DFSC, FSC-Q
- **Typical inputs:** two half-maps (MRC/CCP4), optional mask, optional model for model-map FSC
- **Metrics:** global FSC resolution at 0.143 (unmasked + masked), local resolution distribution (mean, stdev, 10th/90th percentile), d_FSC_model (if model provided), B-factor sharpening estimate, directional resolution anisotropy (dataset), local model-map FSC-Q (per-residue)
- **Gold standard:** EMDB-deposited resolution; RELION `postprocess` reports on the same half-maps
- **Example dataset:** EMDB-`11668` half-maps (apoferritin), EMDB-`20646` half-maps

### T13 — X-ray data quality assessment

- **PHENIX tool(s):** `phenix.xtriage`, `phenix.reflection_statistics`, `phenix.anomalous_signal`, `phenix.explore_metric_symmetry`
- **Doc paths:** `reference/xtriage.html`, `reference/reflection_statistics.html`, `reference/anomalous_signal.html`, `reference/explore_metric_symmetry.html`
- **Independent oracle(s):** CCP4 `aimless`, `pointless`, `ctruncate`, `phaser` anisotropy analysis
- **Typical inputs:** merged or unmerged reflection data (MTZ, SCA, CIF)
- **Metrics:** completeness (overall + outer shell), ⟨I/σ(I)⟩, R-merge / R-meas, CC½, L-test statistic (twinning), anisotropy (Δ B_aniso), Wilson B, translational NCS indicator, ice-ring flags, `aimless` run status
- **Gold standard:** data-processing table (Table 1) from the corresponding publication / wwPDB deposition; `aimless` log on the same reflections
- **Example dataset:** PHENIX xtriage tutorial MTZ; any `.mtz` from PDB-REDO

### T14 — Hydrogen placement / protonation

- **PHENIX tool(s):** `phenix.reduce`, `phenix.ready_set`, `mmtbx.reduce2`
- **Doc paths:** `reference/hydrogens.html`, `reference/ready_set.html`
- **Independent oracle(s):** `reduce` (standalone, Richardson lab), `propka3` (pKa), OpenBabel `--addh`, `pdb2pqr`, Schrödinger `PrepWizard`
- **Typical inputs:** model without hydrogens (or partial H)
- **Metrics:** number of H atoms added, Asn/Gln/His flips proposed, clashscore delta (pre vs post), hbond-network consistency vs standalone `reduce`
- **Gold standard:** standalone `reduce` output on the same input (PHENIX `phenix.reduce` wraps it but exposing both lets us catch wrapping bugs); neutron structure if available (e.g. PDB `5E5V`)
- **Example dataset:** PDB `1HQ1` (high-res, no hydrogens deposited), or a neutron-paired structure for comparison

### T15 — Structural/domain classification

- **PHENIX tool(s):** none — PHENIX has no first-class fold/domain classifier, so this task is oracle-only.
- **Doc paths:** none
- **Independent oracle(s):** DSSP, STRIDE, biotite P-SEA (secondary structure); CATH, SCOPe, ECOD (domain and fold classification)
- **Typical inputs:** model (PDB/mmCIF)
- **Metrics:** secondary-structure assignment agreement (three-state DSSP vs an independent second assigner — STRIDE preferred, biotite P-SEA the runnable fallback — complex scope); DSSP H+E secondary-structure content (complex scope, the load-bearing interpretability gate); secondary-structure assignment (per-residue labels, informational); structural domain assignment (per-domain boundaries, informational); fold classification (per-domain, informational)
- **Gold standard:** CATH/SCOPe/ECOD consensus where available. For the oracle-side secondary-structure result, first require DSSP H+E content **≥ 0.20**, then require DSSP-vs-second-assigner agreement **≥ 0.65**. The agent-vs-DSSP **≥ 0.85** clause is separate and is unevaluable without an agent-supplied per-residue assignment.
- **Example dataset:** PDB `1AKE` (multi-domain, CATH-classified); PDB `2LYZ` (single-domain control)

### T16 — Interface and assembly quality

- **PHENIX tool(s):** none — interface scoring is handled entirely by external oracles.
- **Doc paths:** none
- **Independent oracle(s):** PISA/PDBePISA (buried surface area, assembly prediction), biotite SASA (buried surface area, installable Shrake-Rupley stand-in), DockQ (interface model quality)
- **Typical inputs:** complex or assembly model (PDB/mmCIF)
- **Metrics:** interface buried surface area (Å², **total two-sided** per interface: `ΣSASA(separated chains) − SASA(complex)`), interface DockQ score (per interface), CAPRI interface quality class (per interface, informational — the ordinal class label behind the DockQ score)
- **Gold standard:** deposited biological assembly and CAPRI/DockQ class where available. PISA `interface_area` is per side and must be doubled before comparison with the harness total; with matched 1.4 Å probe and protein-only atom selection, the BSA tolerance is **max(3% of the mean, 30 Å²)**.
- **Example dataset:** PDB `1BRS` (barnase–barstar); PDB `2SIC` (subtilisin–SSI)

### T17 — NMR ensemble/restraint validation

- **PHENIX tool(s):** none — NMR restraint validation is handled by external oracles.
- **Doc paths:** none
- **Independent oracle(s):** wwPDB NMR validation pipeline, PROCHECK-NMR, RPF, biotite ensemble (installable Cα-RMSF precision from the ensemble alone)
- **Typical inputs:** NMR ensemble model plus deposited restraints where available
- **Metrics:** NMR ensemble precision RMSD (Å, across accepted models); NMR restraint violation summary (per ensemble, informational)
- **Gold standard:** wwPDB NMR validation report and deposited restraint files
- **Example dataset:** PDB `1D3Z` (ubiquitin NMR ensemble, deposited restraints + wwPDB NMR validation report)

## How the harness uses this table

1. Pick a row. Instantiate the example dataset (download PDB/EMDB/MTZ).
2. Prompt the agent to perform the task — the agent chooses tools, runs them, and produces the listed metric(s).
3. Harness runs the **independent oracle(s)** on the same inputs and records the same metrics.
4. Pass criteria (per-task, defined in `driving_example_T<NN>.md` files) check cross-tool agreement and/or agreement with the gold standard. The driving example for T01+T04+T05+T06 is in `ref/driving_example.md`.
