# Slide Content Package — `protstruct_review` Technical Review (`slides_2026-11-06`)

- **Source revision**: `f3cfad326f28ddbf652dcdb0c5858443bee6e413` (`main`)
- **Slide count**: 39 (`S01`–`S09`, `S09a`/`S09f`/`S09b`, `S10`–`S12`, `S13a`/`S13`/`S13b`–`S18a`/`S18`/`S18b`, `S19`–`S24`) across 5 sections
- **Figure manifest**: `data/coscientists/openscientist/slides_2026-11-06/figures.json`
- **User input questions**: `data/coscientists/openscientist/slides_2026-11-06/questions.md`

---

## Section 1 — Motivation and Verification Framing (`S01`–`S04`)

### Slide S01 (`S01-reliable-refinement-needs-evidence`)
- **Slide ID**: `S01` (`S01-reliable-refinement-needs-evidence`)
- **Section**: `Section 1 — Motivation and Verification Framing`
- **title_general**: Better structures need evidence.
- **subtitle_technical**: Reproducible assessment of protein refinement and measurement tools
- **One-line message**: `protstruct_review` pairs reproducible before-and-after measurements on actual structures with a clear map of what each structural-biology tool evaluates.
- **Slide body**:
  - Compare the actual starting and refined structures.
  - Cross-check measurements and expose evidence gaps.
  - Explain what each tool measures and when its conclusions apply.
- **Figure**: `None`
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `AGENTS.md:5-15` (two project goals: assess protein refinement results and understand the landscape of protein structure tools and measurements)
  - `AGENTS.md:62-65` (trust model: never grade PHENIX solely with PHENIX/cctbx; re-measure quantitative claims with an independent oracle)
  - `ref/tools_and_measurements_guide.md:19-27` (`PHENIX` macromolecular structure software suite being assessed)
  - `ref/quality_reporting.md:182-187` (`cctbx` crystallographic software framework shared by PHENIX components)
  - `README.md:3-5` (harness scope: cross-tool measurements, independent-oracle checks, and LinkML-validated evaluation and Quality Data Sheet (`QDS`) records)
- **Speaker notes**:
  `protstruct_review` has two linked scientific goals (`AGENTS.md:5-15`): assessing protein refinement results by comparing the actual starting and refined structures with independent cross-checks, and explaining what each macromolecular structure tool and measurement evaluates, requires, and assumes. Here `PHENIX` is the macromolecular structure software suite being assessed (`ref/tools_and_measurements_guide.md:19-27`), and under the repository trust model (`AGENTS.md:62-65`, `ref/quality_reporting.md:182-187`), PHENIX outputs are never graded solely by PHENIX or its shared `cctbx` crystallographic software framework.

---

### Slide S02 (`S02-role-in-agentifying-phenix`)
- **Slide ID**: `S02` (`S02-role-in-agentifying-phenix`)
- **Section**: `Section 1 — Motivation and Verification Framing`
- **title_general**: Automated work needs a defined checking role.
- **subtitle_technical**: Positioning the harness within agentifying PHENIX
- **One-line message**: Committed repository records define the independent assessment harness, while leaving the upstream architecture for agentifying PHENIX and presentation framing as explicit user inputs.
- **Slide body**:
  - The harness records measurements and evidence about actual structures.
  - [USER INPUT: Q1 — Define its role within agentifying PHENIX.]
  - [USER INPUT: Q2 — Define the audience, talk length and technical emphasis.]
- **Figure**: `None`
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `AGENTS.md:3-15` (quality-assessment harness for agent-refined or generated protein structures and two project goals)
  - `ref/quality_reporting.md:19-36` (separating measurement agreement, model suitability, and refinement improvement on identified artifacts)
- **Package artifacts**:
  - `data/coscientists/openscientist/slides_2026-11-06/questions.md` (`Q1` and `Q2` user-framing placeholders)
- **Speaker notes**:
  Committed records define `protstruct_review` as a quality-assessment harness for agent-refined or generated protein structures (`AGENTS.md:3-15`, `ref/quality_reporting.md:19-36`), without prescribing an upstream autonomous planner or controller architecture for agentifying PHENIX. This slide keeps the intended checking role (`[USER INPUT: Q1]`) and the presentation audience, talk length, and emphasis (`[USER INPUT: Q2]`) as explicit user inputs documented in `questions.md`.

---

### Slide S03 (`S03-agreement-suitability-improvement`)
- **Slide ID**: `S03` (`S03-agreement-suitability-improvement`)
- **Section**: `Section 1 — Motivation and Verification Framing`
- **title_general**: Agreement, quality and improvement answer different questions.
- **subtitle_technical**: Implementation agreement, final-model suitability and change relative to input
- **One-line message**: Cross-tool measurement agreement, model suitability in context, and before-and-after refinement improvement require distinct evidence and cannot be collapsed into one verdict.
- **Slide body**:
  - Agreement asks whether matched measurements agree.
  - Quality asks whether the retained model is suitable in its experimental context.
  - Improvement compares actual starting and final models under matched conditions.
- **Figure**: `None`
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `ref/quality_reporting.md:19-26` (three distinct questions, required evidence, and what each result establishes)
  - `scripts/assess_refinement.py:4-28` (`implementation_agreement`, `final_model_quality_support`, and `change_relative_to_input` design)
- **Speaker notes**:
  `ref/quality_reporting.md:19-26` and `scripts/assess_refinement.py:4-28` separate three questions that cannot be collapsed into a single pass/fail badge. Implementation agreement tests whether two tools return consistent numbers on the same model and data within a declared scope. Model quality evaluates experimental fit, stereochemistry, and local features of the retained structure in its resolution context. Refinement improvement compares the actual starting and final structures under matched data and conventions; neither tool agreement nor coordinate movement alone establishes improvement.

---

### Slide S04 (`S04-artifact-identity-before-grading`)
- **Slide ID**: `S04` (`S04-artifact-identity-before-grading`)
- **Section**: `Section 1 — Motivation and Verification Framing`
- **title_general**: The exact file determines what we can test.
- **subtitle_technical**: Artifact identity and lineage in the 1SAR case study
- **One-line message**: A Protein Data Bank (`PDB`) identifier or filename does not identify a refinement round: exact coordinate and reflection files determine which claims can be verified.
- **Slide body**:
  - A structure identifier does not identify a particular refinement round.
  - Starting files, deposited references and packaged outputs serve different roles.
  - Missing coordinates limit what independent measurements can establish.
- **Figure**: `None`
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `ref/quality_reporting.md:27-36,196-204` (artifact identification rules and current retained `1SAR` correction scope)
  - `ref/research/refinement_assessment_case_study_2026-10-18.md:41-51` (`1SAR` archive inventory and Round-4 vs absent Round-7 packaging audit)
- **Speaker notes**:
  Before evaluating any metric, the harness identifies the exact coordinate and diffraction-data files being compared (`ref/quality_reporting.md:27-36`). In the retained `1SAR` case study (`ref/research/refinement_assessment_case_study_2026-10-18.md:41-51`), the starting model `data/1sar.pdb` is a stripped tutorial input distinct from the public `1SAR` PDB entry, the packaged file `data/1sar_final.pdb` is Round 4, and the narrative report's Round-7 coordinates were not retained in the archive.

---

## Section 2 — Harness Development and Measurement Context (`S05`–`S10`)

### Slide S05 (`S05-tools-enter-at-different-stages`)
- **Slide ID**: `S05` (`S05-tools-enter-at-different-stages`)
- **Section**: `Section 2 — Harness Development and Measurement Context`
- **title_general**: Different tools provide different kinds of evidence.
- **subtitle_technical**: Capabilities, local wrappers, retained measurements and calibrated interpretation
- **One-line message**: The harness distinguishes documented catalog capability, runnable local wrappers, retained empirical evidence, and calibrated interpretation across tools and observables.
- **Terms**:
  - **`R-factors` (`R-work` / `R-free`)**: Diffraction R-factors measure model–data disagreement on reflections used in refinement (`R-work`) versus reflections withheld from refinement (`R-free`).
  - **`map-model FSC`**: Map-model Fourier shell correlation compares a model-derived map with an experimental map across spatial-frequency shells.
  - **`RMSD` vs `RMSZ`**: Root-mean-square deviation (`RMSD`) measures physical coordinate or geometry differences in ångströms (`Å`, distance) or degrees (`°`, angle), whereas root-mean-square Z-score (`RMSZ`) divides target deviations by restraint uncertainties and has no units.
- **Slide body**:
  | Tool / Family | Functional Role | Evidence Stage |
  | :--- | :--- | :--- |
  | `PHENIX` / `cctbx` | Refinement, diffraction fit and geometry | Primary subject; never self-grades |
  | `Gemmi` | Structure factors (`sfcalc`) and geometry (`rmsz`) | Runnable wrapper; retained benchmarks |
  | `REFMAC5` / `Servalcat` / `ctruncate` | R-factors, map-model FSC and data quality | R-factor & data-quality wrappers; `Servalcat` FSC catalogued only |
  | `Reduce` / `Probe` | Hydrogen placement and contact clashes | Matched-H wrapper; no backbone/rotamer checks |
  | `TM-align` / `OpenStructure` | Coordinate superposition and local distance scores | Runnable comparison oracles |
  | `DSSP` / `Biotite` / `DockQ` | Secondary structure, interfaces and ensemble spread | Runnable wrappers; scoped calibration |
- **Figure**: `None`
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `ref/tools_and_measurements_guide.md:6-11,19-35,68-71` (four epistemic layers and functional tool roles across tasks)
  - `ref/oracle_tools.md:32-62` (installed local oracles, task coverage, and documented `Servalcat` capability at line `40`)
  - `scripts/bench_refinement_deltas_em.py:20-24` (retained cryo-EM map-model runner using `phenix.map_correlations` and `phenix.mtriage` rather than `Servalcat`)
  - `ref/catalog.yaml:1248-1251` (`T06_map-model_fsc_global_per-shell`: global and per-shell map-model Fourier shell correlation)
  - `ref/quality_reporting.md:52,63-66,91-104` (definitions of `RMSD` vs `RMSZ`, diffraction R-factors `R-work` and `R-free`, and `map-model FSC`)
- **Speaker notes**:
  `ref/tools_and_measurements_guide.md:6-11` separates four stages so a catalog entry is never confused with a calibrated check: documented capability in `ref/catalog.yaml`, runnable local wrappers (`scripts/toolchain.py`, `scripts/gemmi_rfactor.py`, `scripts/t13_data_quality.py`, `scripts/t15_ss_agreement.py`, `scripts/t16_interface_quality.py`, `scripts/t17_nmr_ensemble.py`), retained evidence on disk, and calibrated versus informational interpretation. Even within row 3, evidence stage depends on the observable: `REFMAC5` R-factors and `ctruncate` reflection diagnostics have runnable wrappers and retained cohorts, whereas `Servalcat` `map-model FSC` (`ref/catalog.yaml:1248-1251`, `ref/oracle_tools.md:40`) is a catalogued capability without a retained FSC benchmark wrapper (the retained cryo-EM runner `scripts/bench_refinement_deltas_em.py:20-24` uses `phenix.map_correlations` and `phenix.mtriage`). Here `DSSP` assigns secondary structure, `Biotite` computes structure-analysis checks, and `DockQ` scores interfaces against a reference (`ref/oracle_tools.md:36-51`).

---

### Slide S06 (`S06-three-geometry-configurations`)
- **Slide ID**: `S06` (`S06-three-geometry-configurations`)
- **Section**: `Section 2 — Harness Development and Measurement Context`
- **title_general**: Geometry measurements depend on their definitions.
- **subtitle_technical**: Three benchmarked restraint configurations and the geometry-target taxonomy
- **One-line message**: Three top panels (`A`, `B`, `C`) carry the 17-model covalent-geometry benchmark (`Benchmarked · 17 models`), while three lower taxonomy categories (`not yet benchmarked` in this 17-model comparison) separate force fields, ligand restraint generators, and protonation conventions from local install presence.
- **Slide body**:
  - **Top 3 panels (`Benchmarked · 17 models`)**: **A** (`PHENIX CDL`, conformation-dependent library), **B** (`PHENIX E&H`, static Engh & Huber targets; `A vs B` isolates the within-PHENIX library switch), and **C** (`Gemmi rmsz` / `CCP4 Monomer Library`, the monomer dictionary supplying geometry restraint targets; `B vs C` retains engine, dictionary, and bond-population differences).
  - **Lower 3 categories (`not yet benchmarked` in this 17-model `A/B/C` comparison)**: Force-field restraints (`phenix.amber`, `T03`); ligand restraint generators and dictionaries (`phenix.eLBOW`, `CCP4 libcheck` / `AceDRG`, `T10`); hydrogen and protonation conventions (`reduce`, `phenix.ready_set`, `Schrödinger PrepWizard`, `T14`).
  - **Renderer handoff**: Render three larger top panels (`A`, `B`, `C`), each with its own `Benchmarked · 17 models` badge, followed by three smaller category panels below, each with its own `not yet benchmarked` badge scoped to this comparison.
- **Figure**: `None`
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `ref/research/tolerance_benchmark_restraint_library.md:15-32,109-118` (`A`, `B`, and `C` 17-model configurations, why `B vs C` is a near-matched contrast retaining non-identical dictionary and population differences, and `gemmi 0.7.4` disclosure)
  - `ref/structural_criteria.yaml:489-505` (Engh & Huber 1991 static targets and Moriarty et al. 2016 `CDL` backbone-conformation-dependent targets)
  - `ref/tool_assumptions.yaml:396-405` (`ASSUM_refmac_restraint_library` for CCP4 Monomer Library identity)
  - `ref/catalog.yaml:49-64,269-295,390-410,623-626,842-845,866-869,979-982` (`phenix.amber` in `T03`, `phenix.eLBOW` and `CCP4 libcheck`/`AceDRG` in `T10`, and `reduce`/`phenix.ready_set`/`Schrödinger PrepWizard` in `T14`)
- **Package artifacts**:
  - `ref/research/geometry_tool_presence_2026-11-06.json` (dated metadata-only filesystem presence check on configured default paths without executable runs: `phenix.amber` absent in configured `phenix_bin`; `phenix.elbow`, `phenix.ready_set`, and CCP4 `acedrg`/`libcheck` present; user/XMechBay reports no `Schrödinger`/`OpenEye` installations)
- **Speaker notes**:
  The top three panels show the 17-model covalent-geometry benchmark (`Benchmarked · 17 models`, `ref/research/tolerance_benchmark_restraint_library.md:15-32,109-118`): **A** uses PHENIX's Conformation-Dependent Library (`CDL`, Moriarty et al. 2016), **B** uses static Engh & Huber (`E&H`, 1991) ideal geometry targets on the same PHENIX code path (`ref/structural_criteria.yaml:489-505`), and **C** uses `gemmi rmsz` (`0.7.4`) with the `CCP4 Monomer Library`—the CCP4 monomer dictionary supplying geometry restraint targets (`ref/tool_assumptions.yaml:396-405`). Comparing **A vs B** isolates the within-PHENIX library switch, whereas **B vs C** retains engine, dictionary, and bond-population differences. The lower three categories—force-field energy restraints (`phenix.amber`, `T03`), ligand restraint generators and dictionaries (`phenix.eLBOW`, `CCP4 libcheck`/`AceDRG`, `T10`), and hydrogen/protonation conventions (`reduce`, `phenix.ready_set`, `Schrödinger PrepWizard`, `T14`)—carry `not yet benchmarked` badges scoped specifically to this 17-model `A/B/C` comparison (not claiming absence of `T14` or other experiments elsewhere). Separate metadata-only path checks (`ref/research/geometry_tool_presence_2026-11-06.json`) show `phenix.elbow`, `phenix.ready_set`, `acedrg`, and `libcheck` present on disk, `phenix.amber` absent in `phenix_bin`, and no `Schrödinger`/`OpenEye` installs reported by the user/XMechBay.

---

### Slide S07 (`S07-measurement-records-retain-context`)
- **Slide ID**: `S07` (`S07-measurement-records-retain-context`)
- **Section**: `Section 2 — Harness Development and Measurement Context`
- **title_general**: Measurements need a record of their context.
- **subtitle_technical**: Subjects, tools, units, evidence and criterion preconditions
- **One-line message**: LinkML data-schema classes in `schemas/protstruct_review.yaml` and `schemas/structural_criteria.yaml` record subject identity, tool family (`cctbx` or `non_cctbx`), assumptions, units, and preconditions alongside each value.
- **Slide body**:
  - Identify the model, run and measurement scope.
  - Retain tool versions, library assumptions and units.
  - Link measurements to evidence and applicable criteria; context fields are not all universally required.
- **Figure**: `None`
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `schemas/protstruct_review.yaml:49-58,564-610,761-889,1033-1070,1434-1485` (`ToolFamily` enum `cctbx`/`non_cctbx`, `Tool`, `MetricDefinition`, `MeasurementValue`, `EvaluationRun`, and `QualityDataSheet` class definitions)
  - `schemas/structural_criteria.yaml:150-205` (`CriteriaCollection` and `PassCriterionBinding` class definitions)
  - `schemas/README.md:5-15` (`LinkML` machine-readable schema framework for `EVAL` evaluation records and `QDS` quality data sheets)
  - `CODING_STANDARDS.md:68-143` (QDS trust, criterion-binding, subject-context, and coupled-bundle invariants)
  - `ref/quality_reporting.md:27-36` (reporting artifact identity, selections, settings, and raw-output provenance)
- **Speaker notes**:
  A measurement is uninterpretable without its context (`ref/quality_reporting.md:27-36`). The repository defines its records with `LinkML`—a machine-readable data-schema framework (`schemas/README.md:5-15`). In `schemas/protstruct_review.yaml`, `Tool` (`lines 564-588`) records `version`, explicit `assumptions`, and `family` using the two-value `ToolFamily` enum (`cctbx` and `non_cctbx` only, `lines 49-58`). `MetricDefinition` (`lines 589-610`) defines canonical metric IDs and units; `MeasurementValue` (`lines 761-889`) links observations to `subject_ref`, `stage`, `scope_selector`, `evidence_refs`, `pass_criterion_ref`, and `criterion_preconditions` (`PassCriterionBinding` in `schemas/structural_criteria.yaml:172-205`); and `EvaluationRun` (`lines 1033-1070`) and `QualityDataSheet` (`lines 1434-1485`) group runs and quality sheets. Context fields are recorded where applicable rather than all being universally required across every historical and active record (`CODING_STANDARDS.md:75-86,123-126`).

---

### Slide S08 (`S08-harness-links-inputs-to-measurements`)
- **Slide ID**: `S08` (`S08-harness-links-inputs-to-measurements`)
- **Section**: `Section 2 — Harness Development and Measurement Context`
- **title_general**: The harness connects inputs to checkable reports.
- **subtitle_technical**: Catalog, schema, evaluation records, quality sheets and replay guards
- **One-line message**: From catalog and schema definitions to evaluation records (`EVAL`), Quality Data Sheets (`QDS`), and before/after assessments, guarded code paths preserve lineage and surface missing or conflicting evidence explicitly.
- **Slide body**:
  - Define the task and measurement context.
  - Retain measurements and evidence before producing reports.
  - Check active records for schema, trust and replay consistency; historical exemptions have explicit boundaries.
- **Figure**: `None`
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `README.md:45-69` (hermetic validation gate `scripts/validate.sh` and canonical sources of truth)
  - `schemas/README.md:8-9` (`EVAL` evaluation-record files and `QDS` artifact-specific retained assessment snapshots)
  - `scripts/assess_refinement.py:4-29` (three separated questions, explicit provenance, and `missing_conflicting_and_inapplicable_evidence`)
  - `CODING_STANDARDS.md:58-86,123-169` (`qds_emit.py`, `check_qds_trust_invariant.py`, `check_pass_status.py`, and historical SHA-256 allowlist boundaries)
- **Speaker notes**:
  First, `ref/catalog.yaml` and `schemas/protstruct_review.yaml` define valid tasks, tools, and metrics (`README.md:60-69`). Second, evaluation-record files (`EVAL_*.yaml`) and `scripts/assess_refinement.py:17-29` attach measurements to SHA-256-pinned inputs and record unavailable, conflicting, or inapplicable comparisons in `missing_conflicting_and_inapplicable_evidence`. Third, `scripts/qds_emit.py` emits Quality Data Sheets (`QDS_*.yaml`, artifact-specific retained assessment snapshots, `schemas/README.md:8-9`), and `scripts/validate.sh` enforces referential integrity, non-`cctbx` coverage (`check_qds_trust_invariant.py`), and verdict rules (`check_pass_status.py`) on active guarded records while pinning pre-registry historical artifacts under explicit SHA-256 allowlists (`CODING_STANDARDS.md:75-86,123-126`).

---

### Slide S09 (`S09-threshold-discovery-matched-comparisons`)
- **Slide ID**: `S09` (`S09-threshold-discovery-matched-comparisons`)
- **Section**: `Section 2 — Harness Development and Measurement Context`
- **title_general**: A useful threshold needs the right comparison.
- **subtitle_technical**: Agreement tolerances, quality criteria and refinement-change benchmarks
- **One-line message**: Cross-tool agreement bands, single-model quality criteria, and refinement-change benchmarks answer different questions and hold only when their selections, libraries, and measurement conventions match.
- **Slide body**:
  - Tool agreement, model quality and refinement change use different thresholds.
  - Selections, libraries and measurement conventions determine applicability.
  - A mismatched comparison cannot support a valid grade.
- **Figure**: `None`
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `ref/thresholds_and_standards.md:3-38,97-110,122-144` (provenance tags, descriptive ledger summary, cross-tool agreement tolerances, and method-dependence preconditions)
  - `ref/research/tolerance_benchmark_bond_rmsd.md:55-68,87-108` (equal-count `6/17` vs different-count `11/17` bond-RMSD findings and scope limits)
  - `ref/threshold_evidence_status.yaml:1-90` (scoped policy and evidence states across the 21 registry rows)
- **Speaker notes**:
  `ref/thresholds_and_standards.md:3-38` and `ref/threshold_evidence_status.yaml` distinguish cross-tool agreement tolerances on the same input, single-model quality criteria, and refinement-change benchmarks. Every cross-tool agreement tolerance requires matched selections, hydrogen conventions, restraint libraries, or scaling estimators (`ref/thresholds_and_standards.md:97-110,122-144`). For example, in `ref/research/tolerance_benchmark_bond_rmsd.md:55-68,87-108` and `ref/thresholds_and_standards.md:109`, the differing-library equal-count bond-RMSD diagnostic (`|Δ| ≤ 0.008 Å` for `PHENIX model_statistics` CDL vs `Gemmi rmsz` CCP4 Monomer Library) applies only to the `6/17` models where both tools restrain equal bond counts; even there, per-bond restraint lists were not diffed so equal counts do not prove identical restraint populations (`ref/research/tolerance_benchmark_bond_rmsd.md:104-105`), and the `11/17` unequal-count models are void rather than failed.

---

### Slide S09a (`S09a-threshold-discovery-evidence-ledger-intro`)
- **Slide ID**: `S09a` (`S09a-threshold-discovery-evidence-ledger-intro`)
- **Section**: `Section 2 — Harness Development and Measurement Context`
- **title_general**: We test the rules before using them.
- **subtitle_technical**: Preregistration, null re-refinement and the threshold evidence ledger
- **One-line message**: Before examining the threshold ledger and Section 6 registration history, we define preregistration, null re-refinement, noise scale `S` versus `MAD`, ledger rows and components, and every metric on the figure.
- **Terms**:
  - **Tolerance**: A tolerance limits acceptable disagreement or change.
  - **Null re-refinement**: Null re-refinement reruns refinement on an undamaged deposited model against its own data.
  - **Preregistration**: Preregistration commits the plan before examining benchmark results.
  - **MAD / noise scale S**: Median absolute deviation is the median absolute distance from the sample median. S is the enrollment-screen MAD of non-improving R-free changes, with a pooled fallback when needed.
  - **Row / component**: A registry row contains one or more scoped rule components.
  - **Evidence / policy state**: Evidence state describes retained support; policy state describes how the rule is currently treated.
  - **R-free / ΔR-free**: R-free measures model–data disagreement on withheld reflections; ΔR-free is post-refinement minus baseline R-free, a unitless fraction.
  - **FIT / §3 / §4 / §6**: FIT names the fit-degradation rule; §3, §4 and §6 label registry sections for tool agreement, refinement changes and negative controls.
  - **ADP / ISOT / ANIS**: Atomic displacement parameters model positional spread; isotropic (ISOT) evaluation collapses directional information, while anisotropic (ANIS) evaluation retains it here.
  - **Å / Cα / ΔRMSD**: Å means ångström and Cα means the backbone alpha-carbon atom; here ΔRMSD measures matched Cα coordinate shifts in Å without realigning the models.
  - **Clashscore**: Clashscore counts serious atomic overlaps per 1,000 atoms.
  - **Figure abbreviations**: denom., prod., ext. and unverif. ancill. mean denominator, producer, external and unverified ancillary; cond., prov. and inform. mean conditional, provisional and informational; ret, hist and cur mean retired, historical and current.
- **Slide body**:
  - **The experiment**:
    - Preregister, benchmark, retain records, assert record–registration equality, track the ledger, and re-register changes.
    - Committed tolerance-series files total 60: 40 reports + 20 preregistrations; there are also 11 negative-control reports and 34 preregistration-named documents. These file counts overlap.
  - **Reading the figure**:
    - Panels A/B classify the same components by evidence and policy.
    - Panel C compares registered conditions: PHENIX blue circles, Gemmi orange diamonds, REFMAC green triangles; lines connect history, not performance trends.
- **Figure**: `None`
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `ref/threshold_evidence_status.yaml:4-16` (ledger scope, row/component structure, and `policy_state` / `evidence_state` definitions)
  - `ref/thresholds_and_standards.md:15-21,28-37,204-211,261-273` (`[benchmark]` provenance tags, `§3`/`§4` descriptive inventory, `§4` null case, and `§6` `FIT` rules, re-registration, and falsified-predictions invariants)
  - `ref/research/negative_control_round1_preregistration.md:50-65,114-117` (`D6` noise scale `S` on non-improving `Δ ≥ 0` with pooled fallback, and no threshold tuning after data)
  - `ref/research/negative_control_round9.md:20-48` (isotropic `BREF ISOT` collapse versus anisotropic `REFI BREF ANIS` ADP evaluation context)
  - `scripts/bench_recover_leg.py:43-54,82-129` (`REGISTERED_FIT_THRESHOLDS`, `REGISTERED_FIT_THRESHOLDS_ANIS`, `MAD_FLOOR = 0.0005`, and record-equals-registration assertion)
  - `CODING_STANDARDS.md:46-56` and `scripts/check_negative_control_records.py:1-24` (Rule 10 record/registry equality and validate 3b negative-control record guard)
  - `ref/quality_reporting.md:49-51,63-66,166-169`, `ref/catalog.yaml:1521`, and `ref/research/tolerance_benchmark_refinement_deltas.md:22-32` (`clashscore` per 1,000 atoms, `R-free`, `ΔR-free`, and unsuperposed `Cα` `ΔRMSD` definitions)
- **Package artifacts**:
  - `data/coscientists/openscientist/slides_2026-11-06/build_figures.py` (`build_fig07_threshold_evidence_history`, `_list_research_markdown_inventory`)
  - `data/coscientists/openscientist/slides_2026-11-06/figures.json#/figures/6` (derived inventory path lists, regex patterns, and source pin `f3cfad326f28ddbf652dcdb0c5858443bee6e413`)
- **Speaker notes**:
  This intro defines how thresholds are discovered, registered, and audited before Figure 7 appears. Rules are preregistered before viewing benchmark data (`ref/research/negative_control_round1_preregistration.md:114-117`), tested on deposited structures, and updated only by explicit re-registration with earlier falsified predictions preserved (`ref/thresholds_and_standards.md:268-273`; `CODING_STANDARDS.md:46-56` enforces record-to-registry equality). Keep two MAD-based quantities distinct: the enrollment-screen noise scale `S` (`negative_control_round1_preregistration.md:50-65`) is the MAD of non-improving `ΔR-free ≥ 0` (with a pooled fallback when `< 8` entries), whereas the `§6` `FIT` threshold on Panel C uses the full signed null distribution (`median + 3 × max(MAD, 0.0005)`, `scripts/bench_recover_leg.py:82-129`). At source revision `f3cfad326f28ddbf652dcdb0c5858443bee6e413` (`figures.json#/figures/6`), the committed `ref/research/` tree contains `60` `tolerance_benchmark_round*.md` files (`40` numbered reports + `20` preregistrations), `11` `negative_control_round[0-9]+.md` reports, and `34` Markdown filenames containing `preregistration` (overlapping file counts, not `60` rounds). Panels A and B classify the same `41` `§3`/`§4` components across `21` rows, while Panel C tracks `§6` `FIT` thresholds across three registered conditions.

---

### Slide S09f (`S09f-threshold-discovery-evidence-ledger`)
- **Slide ID**: `S09f` (`S09f-threshold-discovery-evidence-ledger`)
- **Section**: `Section 2 — Harness Development and Measurement Context`
- **title_general**: The rules have different levels of support.
- **subtitle_technical**: Sections 3/4 evidence inventory and Section 6 registered ΔR-free history
- **One-line message**: Figure 7 pairs the orthogonal evidence and policy classifications across the 41 Section 3/4 components (where `retained_record` does not mean validated calibration) with the 9 registered Section 6 `ΔR-free` thresholds across `R4`, `R7`, and `R9`.
- **Slide body**:
  - Evidence and policy states classify the same 41 components, while the 9 registered `ΔR-free` values reflect three distinct cohort and convention regimes.
- **Figure**: `figures/fig07_threshold_evidence_history.png` — *Panels A–B: Orthogonal evidence-state (`8` states) and policy-state (`7` states) counts across the `41` components in the `21` rendered `§3`/`§4` registry rows (`17 §3 + 4 §4`). Panel C: Registered `§6` `FIT` `ΔR-free` thresholds (unitless fraction) across `PHENIX`, `Gemmi`, and `REFMAC5` under three distinct registered conditions: `R4` retired (`0.01220 / 0.01090 / 0.00540`), `R7` `ISOT` history (`0.01200 / 0.01025 / 0.00560`), and `R9` `ANIS` current (`0.01200 / 0.01025 / 0.01150`).*
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `ref/threshold_evidence_status.yaml:4-16,17-759` (`21` rows = `17 §3 + 4 §4` and `41` components classified by `evidence_state` and `policy_state`)
  - `ref/thresholds_and_standards.md:28-37,261-263` (`§3`/`§4` status summary and `§6` `ISOT` history vs `ANIS` current `FIT` threshold tables)
  - `ref/research/negative_control_round4_preregistration.md:20-28` and `ref/research/negative_control_round7_preregistration.md:21-34` (`R4` retired `0.01220 / 0.01090 / 0.00540` and `R7` `H1` `0.01200 / 0.01025 / 0.00560` tables)
  - `scripts/bench_recover_leg.py:43-54,82-129` (`REGISTERED_FIT_THRESHOLDS` and `REGISTERED_FIT_THRESHOLDS_ANIS` constants and derivations)
  - `ref/research/data/negative_control_round3_bench.json#/rows`, `ref/research/data/negative_control_round6_hygiene.json#/g3_8r5k_rescreen/clean_null_deltas`, and `ref/research/data/negative_control_round9_anis.json#/rows` and `#/j2_anis`
- **Package artifacts**:
  - `data/coscientists/openscientist/slides_2026-11-06/figures/fig07_threshold_evidence_history.png`
  - `data/coscientists/openscientist/slides_2026-11-06/figures.json#/figures/6/derived_summaries`
- **Speaker notes**:
  Figure 7 (`figures/fig07_threshold_evidence_history.png`) juxtaposes two distinct parts of the threshold registry. On the left, Panels A and B summarize the `21` rendered rows (`17` in `§3` + `4` in `§4`, comprising `41` scoped components) in `ref/threshold_evidence_status.yaml:4-16`: `23/41` components carry `retained_record` (identifiable retained evidence for the scoped claim, not complete execution provenance or independent calibration), while `29/41` carry `active_conditional` policy status. On the right, Panel C plots the `9` registered `§6` `FIT` `ΔR-free` thresholds (`median_null + 3 × max(MAD_null, 0.0005)`, `scripts/bench_recover_leg.py:82-129`, `ref/thresholds_and_standards.md:261-263`): `R4` retired (`0.01220 / 0.01090 / 0.00540` on `n = 22 / 22 / 19`), `R7` `ISOT` history (`0.01200 / 0.01025 / 0.00560` on `n = 22 / 22 / 20` after substituting `8R5K` on `PHENIX`/`Gemmi` and adding its clean `REFMAC` null), and `R9` `ANIS` current (`0.01200 / 0.01025 / 0.01150`, where `PHENIX` and `Gemmi` retain `R7` `n = 22` and `REFMAC5` uses `n = 21` under `REFI BREF ANIS`, distinct from the non-registered Round-9 `ISOT` comparison value `0.00540`).

---

### Slide S09b (`S09b-threshold-discovery-evidence-ledger-results`)
- **Slide ID**: `S09b` (`S09b-threshold-discovery-evidence-ledger-results`)
- **Section**: `Section 2 — Harness Development and Measurement Context`
- **title_general**: Better evidence changes the rules, not the past.
- **subtitle_technical**: Ledger evidence states, null-test failures and registered FIT revisions
- **One-line message**: Across the 41 Section 3/4 components and the Section 6 FIT history, empirical audits separate retained records from unproven calibration, replace failed tolerances by re-registration, and preserve past falsified predictions.
- **Slide body**:
  - 23/41 components have retained records; 9 are unmeasured and 4 partial. Retention alone does not establish calibration.
  - 29 are active but conditional; flip-conflict grading is suspended because the retained producer pair differs from the claimed independent comparison.
  - Without deliberate model edits, null refinement breached old limits on 5/8 entries for coordinate shift and 3/8 for clashscore.
  - R4 → R7 incorporates the cleaned 8R5K null; R7 → R9 changes REFMAC's displacement convention.
  - Revised thresholds require re-registration; earlier falsified predictions remain falsified.
- **Figure**: `None`
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `ref/threshold_evidence_status.yaml:4-16,567-575` (`23/41` `retained_record`, `29/41` `active_conditional`, and `h_placement.flip_conflict` `suspended` / `producer_mismatch`)
  - `ref/thresholds_and_standards.md:28-37,204-211,261-273` (orthogonal ledger counts, `5/8` `ΔRMSD` and `3/8` `clashscore` null breaches, `R4`/`R7`/`R9` `§6` `FIT` tables, and the falsified-predictions invariant)
  - `ref/research/tolerance_benchmark_refinement_deltas.md:22-32,39-48,61-66` (X-ray null re-refinement `Cα` shifts `0.008–0.107 Å` and `5/8` `ΔRMSD`, `3/8` `clashscore` clause failures)
  - `ref/research/negative_control_round4_preregistration.md:3-7,20-28` and `ref/research/negative_control_round7_preregistration.md:21-34` (`R4` null-centered registration and `R7` `H1` `8R5K` clean-null recompute and disclosure rule)
  - `scripts/bench_recover_leg.py:43-54,82-129`, `CODING_STANDARDS.md:46-56`, and `scripts/check_negative_control_records.py:1-24` (record-derived `§6` constants and registry guard)
  - `ref/research/data/negative_control_round3_bench.json#/rows`, `ref/research/data/negative_control_round6_hygiene.json#/g3_8r5k_rescreen/clean_null_deltas`, and `ref/research/data/negative_control_round9_anis.json#/rows` and `#/j2_anis`
- **Package artifacts**:
  - `data/coscientists/openscientist/slides_2026-11-06/figures.json#/figures/6/derived_summaries`
- **Speaker notes**:
  Five source-established results follow from Figure 7. First, across the `41` `§3`/`§4` components (`ref/threshold_evidence_status.yaml:4-16`), `23` have `retained_record`, `9` are `unmeasured`, `4` have `partial_record`, and `5` occupy single-component states (`denominator_unproven`, `external_standard_cited`, `limited_controls`, `producer_mismatch`, `unverified_ancillary`); `retained_record` never implies complete provenance or independent calibration. Second, `29/41` components are `active_conditional` (`6` `informational`, `2` `provisional_informational`), while `h_placement.flip_conflict` is `suspended` because its `reduce` vs `reduce2` comparison is `producer_mismatch` (`lines 567-575`). Third, re-refining undamaged deposited X-ray structures (`ref/research/tolerance_benchmark_refinement_deltas.md:22-32,39-48,61-66`) still moves `Cα` coordinates by `0.008–0.107 Å` (`median 0.072 Å`), breaching the old `§4` bands on `5/8` entries for `ΔRMSD` and `3/8` for `clashscore`. Fourth, `R4 → R7 → R9` `§6` `FIT` changes reflect `8R5K`'s clean null (`19 → 20` on `REFMAC`, `negative_control_round7_preregistration.md:21-34`) and switching `REFMAC5` to `REFI BREF ANIS` (`n = 21`, `0.01150`). Fifth, rules change only by re-registration and falsified predictions stay falsified (`ref/thresholds_and_standards.md:268-273`).

---

### Slide S10 (`S10-current-assessment-remains-informational`)
- **Slide ID**: `S10` (`S10-current-assessment-remains-informational`)
- **Section**: `Section 2 — Harness Development and Measurement Context`
- **title_general**: The current assessment reports evidence without grading it.
- **subtitle_technical**: Empty pass-criterion bindings keep before/after verdicts informational
- **One-line message**: Because `ref/structural_criteria.yaml` currently sets `pass_criterion_bindings: []`, `scripts/assess_refinement.py` resolves supported verdict requests to `"informational"` and rejects non-empty bindings.
- **Slide body**:
  - The registry currently has no admitted machine verdict bindings.
  - The assessment returns informational status for supported requests.
  - Documentary benchmarks do not automatically authorize generic pass/fail grades.
- **Figure**: `None`
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `ref/structural_criteria.yaml:13-18` (`pass_criterion_bindings: []`)
  - `scripts/assess_refinement.py:24-28,136,207-230` (`VALID_VERDICT_STATUSES` and `resolve_verdict_status` implementation)
  - `ref/research/t05_classification_floor_adoption_2026-09-27.md:19-23` (documentary adoption vs executable `PassCriterionBinding` grading)
- **Speaker notes**:
  `protstruct_review` separates documentary threshold policies from executable pass/fail grading (`ref/quality_reporting.md:5-16`). In `ref/structural_criteria.yaml:13-18`, `pass_criterion_bindings` is currently `[]`, and adopted documentary rules such as the Round-46 classification floor (`ref/research/t05_classification_floor_adoption_2026-09-27.md:19-23`) do not create automatic QDS grades. In `scripts/assess_refinement.py:136,207-230`, `resolve_verdict_status(bindings, requested_status)` validates that `requested_status` is `None` or in `{"pass", "fail", "NeedsReview", "informational"}`, raises `ValueError` if `pass_criterion_bindings` is non-empty, and otherwise returns `"informational"`.

---

## Section 3 — Extreme-Resolution Control Evaluation Set (`S11`–`S13b`)

### Slide S11 (`S11-extreme-resolution-control-baseline`)
- **Slide ID**: `S11` (`S11-extreme-resolution-control-baseline`)
- **Section**: `Section 3 — Extreme-Resolution Control Evaluation Set`
- **title_general**: We begin with exceptionally detailed experimental structures.
- **subtitle_technical**: Preregistered extreme-resolution X-ray controls and eligibility filters
- **One-line message**: Preregistered X-ray crystal structures with diffraction resolution `d_min ≤ 1.00 Å` (where `d_min` is the high-resolution diffraction limit in ångströms, `Å`, and smaller values mean finer spatial detail) form a curated stress set.
- **Slide body**:
  - Select X-ray entries at or better than 1.00 Å with released diffraction data.
  - Apply registered geometry, data-quality and protein-size filters.
  - Sample sequence clusters with deterministic replacement; this is a curated stress set, not a complete census.
- **Figure**: `None`
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `ref/research/negative_control_round1_preregistration.md:13-48` (`D1` window `d_min ≤ 1.0 Å`, `D2` quality gates, `D3` `≥ 50` unmasked-residue floor, and `D4` cluster representative/replacement rule)
  - `ref/research/negative_control_round2_preregistration.md:14-25,102-126` (`R1` `deposited_polymer_monomer_count ≥ 100`, `D7′` stratum-oversampled draw, and stress-set estimand)
  - `scripts/select_gold_standards.py:201-215` and `ref/catalog.yaml:1533-1536` (`d_min` high-resolution diffraction limit in `Å`)
  - `ref/quality_reporting.md:49-51,63-66` (`clashscore`, `Ramachandran outliers`, `rotamer outliers`, and `R-free` definitions)
- **Speaker notes**:
  Here `d_min` is the high-resolution limit of the X-ray diffraction data in ångströms (`Å`, the atomic-scale distance unit), with smaller values indicating finer spatial detail (`scripts/select_gold_standards.py:201-215`, `ref/catalog.yaml:1533-1536`), and `R-free` measures model–data disagreement on reflections withheld from refinement (`ref/quality_reporting.md:63-66`). Registered filters (`ref/research/negative_control_round1_preregistration.md:13-48`, `ref/research/negative_control_round2_preregistration.md:14-25,102-126`) require X-ray `d_min ≤ 1.00 Å`, released structure factors, `≥ 1` protein entity, `deposited_polymer_monomer_count ≥ 100` (`R1`), `reported R-free ≤ 0.18`, `clashscore ≤ 2` (serious non-bonded atomic overlaps), `Ramachandran outliers ≤ 0.5%` (unusual backbone torsion-angle combinations), `rotamer outliers ≤ 1.0%` (unusual side-chain conformations; `ref/quality_reporting.md:49-51`), and `≥ 50` unmasked residues (`D3`), sampled one per 30%-identity cluster with deterministic replacement (`D4`) and `≤ 0.90 Å` oversampling (`D7′`, `26` of `30` clusters).

---

### Slide S12 (`S12-screening-enrolled-22-controls`)
- **Slide ID**: `S12` (`S12-screening-enrolled-22-controls`)
- **Section**: `Section 3 — Extreme-Resolution Control Evaluation Set`
- **title_general**: Screening leaves a smaller, usable test set.
- **subtitle_technical**: The Round-2 enrollment funnel
- **One-line message**: Across 30 initial cluster representatives and 28 deterministic within-cluster replacements (`58` attempts), floor, data-defect, and headroom gates produced the 22 enrolled control structures.
- **Slide body**:
  - 58 attempts comprise 30 initial representatives and 28 replacements.
  - 35 exclusions leave 23 screened structures.
  - One headroom exclusion leaves 22 enrolled controls.
- **Figure**: `None`
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `ref/research/negative_control_round2.md:3-11,41-65` (`58 = 30 + 28` attempts, `3` floor failures, `32` data defects by cause, `23` screened, `1` headroom exclusion `2DDX`, and `22` enrolled)
  - `ref/research/data/negative_control_round2_screen.json#/rows` and `#/d6` (per-attempt status records and `D6` two-path headroom summary)
  - `ref/research/data/negative_control_round2_enrolled.json#/n_enrolled` (`n_enrolled = 22`)
- **Speaker notes**:
  `ref/research/negative_control_round2.md:3-11,41-65` and `ref/research/data/negative_control_round2_screen.json` record the Round-2 enrollment funnel across 30 sequence clusters (`58` total attempts = `30` initial representatives + `28` `D4` replacements). Before screening, `35` attempts were excluded: `3` failed the `≥ 50` unmasked-residue floor (`D3`) and `32` had protocol data or restraint defects (`18` missing ligand restraint dictionaries under `R3`, `11` intensity-only depositions incompatible with the two-path `gemmi` amplitude requirement, `2` lacking registered observation labels, and `1` fetch failure), leaving `23` screened structures. One screened structure (`2DDX`, `-0.0085 / -0.0083`) improved beyond both two-path `-3S` headroom cutoffs (`-0.00825 / -0.00780`, `D6`), leaving `22` enrolled controls.

---

### Slide S13a (`S13a-actual-resolutions-describe-enrolled-proteins-intro`)
- **Slide ID**: `S13a` (`S13a-actual-resolutions-describe-enrolled-proteins-intro`)
- **Section**: `Section 3 — Extreme-Resolution Control Evaluation Set`
- **title_general**: The test set starts with unusually detailed structures.
- **subtitle_technical**: Round-2 resolution, inherited cluster strata and the enrollment process
- **One-line message**: Before examining the cohort distribution, we define diffraction resolution (`d_min` in `Å`), group counts (`n`), medians, and the distinction between measured resolution and stored `stratum` labels.
- **Terms**:
  - **`d_min`**: `d_min` is the high-resolution limit of the diffraction data, with smaller values indicating finer spatial detail.
  - **`Å`**: `Å` denotes the ångström, the distance unit used here for atomic coordinates and diffraction resolution.
  - **`n`**: `n` is the number of structures contributing to the named group.
  - **`median`**: The median is the middle sorted value, or the mean of the middle pair when needed.
  - **`stratum` (`stratum=T` / `stratum=F`)**: `stratum` is a stored enrollment-group label (`true` or `false`) that can be inherited during within-cluster replacement rather than recalculated from the replacement's resolution.
- **Slide body**:
  - **The experiment**:
    - 22 enrolled controls from 58 screening attempts form a curated X-ray stress set.
    - Panel A compares overlapping resolution and stored-stratum groups; Panel B ranks the same 22 structures by `d_min`.
  - **Reading the figure**:
    - Both vertical axes show `d_min` in `Å` (smaller values mean finer diffraction detail).
    - Boxes show the middle 50%, dark horizontal lines the median, whiskers the full range, and the `0.90 Å` dotted line the stratum split (not a grading threshold).
- **Figure**: `None`
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `ref/research/negative_control_round2.md:3-11` (`22` enrolled controls from `58` attempts)
  - `ref/research/negative_control_round2_preregistration.md:112-119` (`0.90 Å` stratum split in the `D7′` sampling design)
  - `scripts/select_gold_standards.py:201-215` and `ref/catalog.yaml:1533-1536` (`d_min` high-resolution limit in `Å`)
  - `scripts/screen_round1.py:660-669` (`D4` replacement queue copying `row.get("stratum")` from the initial seed)
  - `ref/research/data/negative_control_round2_enrolled.json#/entries` (`22` enrolled entries with `pdb_id`, `d_min`, and `stratum`)
- **Package artifacts**:
  - `data/coscientists/openscientist/slides_2026-11-06/build_figures.py` (`build_fig01_cohort_resolution`, `draw_box_and_strip`, `summary_stats`, and `deterministic_offsets` horizontal jitter)
  - `data/coscientists/openscientist/slides_2026-11-06/figures.json#/figures/0`
- **Speaker notes**:
  This intro defines every measure and visual encoding in Figure 1 (`build_fig01_cohort_resolution`). In Panel A, `All (n=22)` uses dark circles, actual `≤0.90 Å (n=15)` uses blue circles, actual `0.90–1.00 (n=7)` uses orange diamonds, stored `stratum=T (n=20)` uses green upward triangles, and stored `stratum=F (n=2)` uses purple squares; horizontal jitter separates overlapping points without changing measured `d_min` (`draw_box_and_strip`). In Panel B, structures ranked from finest to coarsest `d_min` use blue circles for `d_min ≤ 0.90 Å (n=15)`, red upward triangles for `>0.90 Å` with `stratum=true (n=5)`, and purple squares for `>0.90 Å` with `stratum=false (n=2)`. The dotted `0.90 Å` line marks the sampling stratum boundary (`ref/research/negative_control_round2_preregistration.md:112-119`), not a grading threshold.

---

### Slide S13 (`S13-actual-resolutions-describe-enrolled-proteins`)
- **Slide ID**: `S13` (`S13-actual-resolutions-describe-enrolled-proteins`)
- **Section**: `Section 3 — Extreme-Resolution Control Evaluation Set`
- **title_general**: The selected structures span a narrow range of detail.
- **subtitle_technical**: Measured resolution distribution of the 22 enrolled controls
- **One-line message**: Figure 1 compares the 22 enrolled controls' measured diffraction resolutions (`0.79–1.00 Å`, median `0.895 Å`) against their stored cluster-stratum labels.
- **Slide body**:
  - Measured `d_min` and stored cluster labels describe different aspects of enrollment.
- **Figure**: `figures/fig01_cohort_resolution.png` — *Panel A: Diffraction resolution `d_min (Å)` for all 22 enrolled proteins (`median 0.895 Å`), actual `d_min ≤ 0.90 Å` (`n = 15`) vs `(0.90, 1.00] Å` (`n = 7`), and stored cluster `stratum = true` (`n = 20`) vs `false` (`n = 2`). Panel B: Ranked `d_min` profile across all 22 enrolled PDB entries.*
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `ref/research/data/negative_control_round2_enrolled.json#/entries` (`22` enrolled records with `pdb_id`, `d_min`, and `stratum`)
- **Package artifacts**:
  - `data/coscientists/openscientist/slides_2026-11-06/figures/fig01_cohort_resolution.png`
  - `data/coscientists/openscientist/slides_2026-11-06/figures.json#/figures/0/derived_summaries`
- **Speaker notes**:
  Figure 1 (`figures/fig01_cohort_resolution.png`) plots the measured diffraction resolution `d_min` from `ref/research/data/negative_control_round2_enrolled.json#/entries` across the 22 enrolled controls. Panel A shows the five overlapping groupings side by side, while Panel B orders the 22 structures from finest (`4M7G` and `7R2H` at `0.79 Å`) to coarsest (`6ZWY` at `1.00 Å`) around the `0.895 Å` cohort median.

---

### Slide S13b (`S13b-actual-resolutions-describe-enrolled-proteins-results`)
- **Slide ID**: `S13b` (`S13b-actual-resolutions-describe-enrolled-proteins-results`)
- **Section**: `Section 3 — Extreme-Resolution Control Evaluation Set`
- **title_general**: Stored groups differ from actual detail levels.
- **subtitle_technical**: Actual resolution bands differ from inherited cluster strata
- **One-line message**: Measured `d_min` spans `0.79–1.00 Å` (`median 0.895 Å`), with `15` structures at `≤ 0.90 Å` versus `20` carrying `stratum = true` inherited during within-cluster replacement.
- **Slide body**:
  - Enrolled `d_min` spans `0.79–1.00 Å` with a median of `0.895 Å` (`n = 22`).
  - Fifteen structures have actual `d_min ≤ 0.90 Å` and seven lie in `(0.90, 1.00] Å`, whereas stored `stratum` is `true` for 20 and `false` for 2.
  - Five within-cluster replacements above `0.90 Å` inherited their seed cluster labels, so resolution counts must use actual `d_min`.
- **Figure**: `None`
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `ref/research/data/negative_control_round2_enrolled.json#/entries` (`22` enrolled entries with `d_min` and `stratum`)
  - `scripts/screen_round1.py:660-669` (`D4` replacement queue copying `row.get("stratum")` into within-cluster replacement entries)
- **Package artifacts**:
  - `data/coscientists/openscientist/slides_2026-11-06/figures.json#/figures/0/derived_summaries`
- **Speaker notes**:
  In `ref/research/data/negative_control_round2_enrolled.json#/entries`, measured `d_min` ranges from `0.79 Å` (`4M7G`, `7R2H`) to `1.00 Å` (`6ZWY`) with a median of `0.895 Å`; because `6ZWY` is at `1.00 Å` exactly, the cohort is extreme-resolution (`0.79–1.00 Å`) rather than all sub-ångström. Actual `d_min` splits `15` (`≤ 0.90 Å`) versus `7` (`> 0.90 Å`), whereas stored `stratum` splits `20` (`true`) versus `2` (`false`). As `scripts/screen_round1.py:660-669` shows, `D4` replacement copies `row.get("stratum")` from the initial seed into the replacement entry, which is why five replacements above `0.90 Å` (`7ATV`, `6ZWY`, `8QXQ`, `6F1O`, `5KXV`) retain `stratum = true`.

---

## Section 4 — Empirical Results and Case-Study Audits (`S14a`–`S21`)

### Slide S14a (`S14a-clean-null-refinements-data-fit-changes-intro`)
- **Slide ID**: `S14a` (`S14a-clean-null-refinements-data-fit-changes-intro`)
- **Section**: `Section 4 — Empirical Results and Case-Study Audits`
- **title_general**: Fitting alone can change the score.
- **subtitle_technical**: Round-9 null re-refinement and post-minus-deposited ΔR-free
- **One-line message**: Before viewing the Round-9 null distributions, we define `R-free`, `ΔR-free`, `null refinement`, the three evaluators (`PHENIX`, `Gemmi`, `REFMAC5 ANIS`), and the `§6` benchmark drift lines.
- **Terms**:
  - **`R-free`**: `R-free` measures model–data disagreement on reflections withheld from refinement, with lower values indicating better fit under matched conventions.
  - **`ΔR-free` (`post − baseline`)**: `ΔR-free` here is the post-refinement `R-free` minus the deposited baseline, so positive values mean worse fit and negative values mean better fit.
  - **`unitless fraction`**: A unitless fraction is a ratio, rather than a value expressed as a percentage.
  - **`null refinement`**: Null refinement reruns the refinement protocol on an undamaged deposited model to measure the changes the protocol itself produces.
  - **`PHENIX model_vs_data` / `Gemmi sfcalc` / `REFMAC5 (ANIS)`**: Three evaluators computing diffraction `R-free` on the baseline and post-refinement models (`PHENIX` crystallographic evaluator, `Gemmi` structure-factor calculator, and `CCP4 REFMAC5` zero-cycle evaluation).
  - **`atomic displacement parameters`**: Atomic displacement parameters describe the modeled spread of an atom's position around its average coordinate, which may depend on direction.
  - **`ANIS`**: `ANIS` is the `REFMAC5` evaluation mode (`BREF ANIS`) that applies the retained anisotropic displacement parameters on both baseline and post-refinement models.
  - **`§6`**: `§6` denotes Section 6 of the repository's threshold registry, containing the negative-control refinement-change benchmark rules.
  - **`n` / `med`**: `n` is the number of structures in the group; `med` is the group's median value.
- **Slide body**:
  - **The experiment**:
    - Refine the deposited control structures without deliberate damage and measure `ΔR-free` (`post − baseline`) across `PHENIX`, `Gemmi`, and `REFMAC5 ANIS`.
  - **Reading the figure**:
    - The vertical axis shows `ΔR-free` as a unitless fraction (positive means worse fit, negative means better fit).
    - Blue circles show `PHENIX`, orange diamonds `Gemmi`, and green upward triangles `REFMAC5 ANIS`, with middle-50% boxes, dark median lines, and full-range whiskers.
    - Dashed per-tool segments mark `§6` refinement-change benchmark thresholds, not cross-tool agreement bands.
- **Figure**: `None`
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `ref/research/negative_control_round9.md:7-36,55-64` (`J1/X1` regenerated null protocol, `J2/X2` `ANIS` evaluation, and `J3` `§6` threshold table)
  - `ref/quality_reporting.md:63-70,166-169` (`R-free` definition and `post − baseline` delta sign convention)
  - `ref/thresholds_and_standards.md:245-264` (`§6` negative-control benchmark rules)
  - `ref/research/data/negative_control_round9_anis.json#/rows`
- **Package artifacts**:
  - `data/coscientists/openscientist/slides_2026-11-06/build_figures.py` (`build_fig02_r9_null_delta_rfree`, `draw_box_and_strip`, `summary_stats`)
  - `data/coscientists/openscientist/slides_2026-11-06/figures.json#/figures/1`
- **Speaker notes**:
  This intro defines the experiment and visual encodings for Figure 2 (`build_fig02_r9_null_delta_rfree`). Undamaged deposited controls are re-refined under the registered protocol (`ref/research/negative_control_round9.md:7-22`), and each evaluator computes `ΔR-free = post − deposited baseline` as a unitless fraction (`ref/quality_reporting.md:63-70,166-169`). Blue circles represent `PHENIX model_vs_data`, orange diamonds `Gemmi sfcalc`, and green upward triangles `REFMAC5` in `ANIS` mode (zero-cycle evaluation preserving anisotropic displacement parameters). The dashed horizontal segments (`+0.01200`, `+0.01025`, `+0.01150`) are `§6` refinement-change benchmark cutoffs (`ref/thresholds_and_standards.md:245-264`), not cross-tool agreement tolerances.

---

### Slide S14 (`S14-clean-null-refinements-data-fit-changes`)
- **Slide ID**: `S14` (`S14-clean-null-refinements-data-fit-changes`)
- **Section**: `Section 4 — Empirical Results and Case-Study Audits`
- **title_general**: Repeated fitting leaves a spread of changes.
- **subtitle_technical**: Round-9 native-population ΔR-free across three evaluators
- **One-line message**: Figure 2 shows the native Round-9 null-refinement `ΔR-free` distributions across `PHENIX` (`n = 22`), `Gemmi` (`n = 22`), and `REFMAC5 ANIS` (`n = 21`, with `9YGW` absent).
- **Slide body**:
  - All points are shown; `REFMAC5` excludes `9YGW`, which is absent rather than zero.
- **Figure**: `figures/fig02_r9_null_delta_rfree.png` — *Round-9 regenerated null-refinement `ΔR-free` (`post − deposited baseline`, unitless fraction; positive = worse fit) across `PHENIX` (`n = 22`), `Gemmi` (`n = 22`), and `REFMAC5 BREF ANIS` (`n = 21`, `9YGW` absent). Dashed lines indicate §6 refinement-change benchmark thresholds.*
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `ref/research/data/negative_control_round9_anis.json#/rows` and `#/j2_anis`
  - `ref/thresholds_and_standards.md:262-263`
- **Package artifacts**:
  - `data/coscientists/openscientist/slides_2026-11-06/figures/fig02_r9_null_delta_rfree.png`
  - `data/coscientists/openscientist/slides_2026-11-06/figures.json#/figures/1/derived_summaries`
- **Speaker notes**:
  Figure 2 (`figures/fig02_r9_null_delta_rfree.png`) plots every native observation from `ref/research/data/negative_control_round9_anis.json#/rows`. `PHENIX` and `Gemmi` each include all 22 enrolled structures, whereas `REFMAC5 ANIS` includes 21 structures because `9YGW` was permanently stood down to two-path status in Round 8 and is absent rather than plotted as zero.

---

### Slide S14b (`S14b-clean-null-refinements-data-fit-changes-results`)
- **Slide ID**: `S14b` (`S14b-clean-null-refinements-data-fit-changes-results`)
- **Section**: `Section 4 — Empirical Results and Case-Study Audits`
- **title_general**: Typical changes are positive, but vary across structures.
- **subtitle_technical**: Native null medians, reproducibility and benchmark scope
- **One-line message**: Native Round-9 null `ΔR-free` medians are `+0.00330` (`PHENIX`, `n = 22`), `+0.00365` (`Gemmi`, `n = 22`), and `+0.00370` (`REFMAC5 ANIS`, `n = 21`, newly measured in Round 9), while the 44 `PHENIX`/`Gemmi` deltas reproduce Round 3 within `0.0006`.
- **Slide body**:
  - Native null `ΔR-free` medians are `+0.00330` on `PHENIX` and `+0.00365` on `Gemmi` (`n = 22` each).
  - Native `REFMAC5 ANIS` median is `+0.00370` (`n = 21`; `9YGW` is permanently two-path).
  - Regenerated two-path deltas reproduce committed Round-3 values within `0.0006` (`≤ 0.002` registered bound).
  - Dashed thresholds (`0.01200`, `0.01025`, `0.01150`) describe benchmark refinement drift rather than cross-tool agreement.
- **Figure**: `None`
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `ref/research/data/negative_control_round9_anis.json#/rows` and `#/j2_anis` (per-PDB `paths.phenix.delta`, `paths.gemmi.delta`, `refmac.anis.delta`, and native medians)
  - `ref/research/negative_control_round9.md:7-22,55-64` (`J1/X1` reproduction within `0.0006` and `J3` threshold provenance)
  - `ref/thresholds_and_standards.md:262-263` (`§6` Round-7 `H1` two-path thresholds and Round-9 `J2` `REFMAC5 ANIS` threshold)
- **Package artifacts**:
  - `data/coscientists/openscientist/slides_2026-11-06/figures.json#/figures/1/derived_summaries`
- **Speaker notes**:
  Across the regenerated Round-9 null refinements (`ref/research/negative_control_round9.md:7-22`), native `ΔR-free` medians are `+0.00330` on `PHENIX` (`n = 22`), `+0.00365` on `Gemmi` (`n = 22`), and `+0.00370` on `REFMAC5 ANIS` (`n = 21`, newly measured in Round 9; on the common 21-structure subset, `PHENIX` and `Gemmi` medians are `+0.00320` and `+0.00300`). All 44 `PHENIX`/`Gemmi` two-path deltas reproduced committed Round-3 values within `0.0006` (`8R5K` maximum difference, inside the `0.002` bound). In `ref/thresholds_and_standards.md:262-263` and `ref/research/negative_control_round9.md:55-64`, the `PHENIX` (`0.01200`) and `Gemmi` (`0.01025`) `§6` thresholds come from Round 7 (`H1`), while the `REFMAC5 ANIS` threshold (`0.01150`) comes from Round 9 (`J2`).

---

### Slide S15a (`S15a-adp-conventions-change-comparison-intro`)
- **Slide ID**: `S15a` (`S15a-adp-conventions-change-comparison-intro`)
- **Section**: `Section 4 — Empirical Results and Case-Study Audits`
- **title_general**: Atomic motion needs a consistent description.
- **subtitle_technical**: Paired REFMAC ISOT versus ANIS on the common 21 controls
- **One-line message**: Before examining the paired `REFMAC5` comparison, we define atomic displacement parameters (`ADP`), `ISOT`, `ANIS`, `ANISOU` coordinate records, and directional sign agreement across the 21 common controls.
- **Terms**:
  - **`R-free`**: `R-free` measures model–data disagreement on reflections withheld from refinement, with lower values indicating better fit under matched conventions.
  - **`ΔR-free` (`post − baseline`)**: `ΔR-free` is the post-refinement `R-free` minus the deposited baseline, expressed as a unitless fraction.
  - **`ADP`**: An atomic displacement parameter describes the modeled spread of an atom's position around its average coordinate.
  - **`ISOT`**: `ISOT` is the `REFMAC5` evaluation mode (`BREF ISOT`) that replaces directional displacement parameters with isotropic equivalents on both baseline and re-refined models in this comparison.
  - **`ANIS`**: `ANIS` is the `REFMAC5` zero-cycle evaluation mode (`REFI BREF ANIS`) that retains and applies anisotropic displacement parameters on both baseline and re-refined models.
  - **`ANISOU`**: `ANISOU` is a coordinate-file record carrying anisotropic displacement information for individual atoms.
  - **`sign agreement`**: Sign agreement means that evaluators agree on whether a measured change is positive or negative for the same structure.
  - **`n` / `med`**: `n` is the number of structures (`n = 21` common controls where `REFMAC5` runs, with `9YGW` excluded), and `med` is the group median.
- **Slide body**:
  - **The experiment**:
    - All 21 `REFMAC5`-compatible negative controls carry deposited `ANISOU` records, so we scored the same baseline and re-refined coordinate pairs under both `REFMAC5 ISOT` and `REFMAC5 ANIS` alongside the common-subset `PHENIX` and `Gemmi` distributions (`n = 21`).
  - **Reading the figure**:
    - Columns 1 and 2 show common-subset `PHENIX` (blue circles) and `Gemmi` (orange diamonds), while columns 3 and 4 pair each structure's `REFMAC5 ISOT` (light-green downward triangles) and `REFMAC5 ANIS` (green upward triangles) deltas with green dashed connecting lines (and a red solid line for `2VXN`).
- **Figure**: `None`
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `ref/research/negative_control_round9.md:20-22,24-48,61-64` (paired `ISOT` vs `ANIS` test on `n = 21`, `ANISOU` preservation, and `§6` thresholds)
  - `scripts/bench_negative_control.py:108-120` (zero-cycle `REFMAC5` `REFI BREF ANIS` evaluation configuration)
  - `ref/quality_reporting.md:63-66,166-169` (`R-free` fit definition and `post − baseline` delta sign interpretation)
  - `ref/research/data/negative_control_round9_anis.json#/rows` and `#/x3_direction_agreement` (paired `refmac.isot` and `refmac.anis` delta records)
- **Package artifacts**:
  - `data/coscientists/openscientist/slides_2026-11-06/build_figures.py` (`build_fig03_r9_isot_vs_anis_paired`, `draw_box_and_strip`, lines `764-775` paired line styles)
  - `data/coscientists/openscientist/slides_2026-11-06/figures.json#/figures/2`
- **Speaker notes**:
  This intro slide sets up the paired convention test in Figure 3. `R-free` fit and its `post − baseline` delta sign convention follow `ref/quality_reporting.md:63-66,166-169`. Because all 21 `REFMAC5`-measurable negative-control structures (`9YGW` excluded) contain deposited anisotropic displacement records (`ANISOU`), evaluating them with `REFMAC5`'s default isotropic mode (`BREF ISOT`) strips directional displacement parameters on both the baseline and re-refined models (`ref/research/negative_control_round9.md:20-22,24-48`). Running zero-cycle `REFMAC5` with `REFI BREF ANIS` (`scripts/bench_negative_control.py:108-120`) preserves `ANISOU` on both sides of the delta. In the plot (`build_figures.py:764-775`), each box spans the 25th to 75th percentiles with a horizontal median line and full-range whiskers, while green dashed segments connect each ordinary structure's `ISOT` delta to its paired `ANIS` delta and a red solid line tracks `2VXN`.

---

### Slide S15 (`S15-adp-conventions-change-comparison`)
- **Slide ID**: `S15` (`S15-adp-conventions-change-comparison`)
- **Section**: `Section 4 — Empirical Results and Case-Study Audits`
- **title_general**: A scoring setting changes the comparison.
- **subtitle_technical**: Paired ISOT/ANIS deltas with PHENIX/Gemmi reference distributions
- **One-line message**: Figure 3 connects each of the 21 common controls between `REFMAC5 BREF ISOT` and `REFMAC5 BREF ANIS` alongside common-subset `PHENIX` and `Gemmi`, highlighting `2VXN` (`-0.0122 → +0.0130`).
- **Slide body**:
  - Connecting lines show within-structure changes in the REFMAC evaluation convention.
- **Figure**: `figures/fig03_r9_isot_vs_anis_paired.png` — *Paired `n = 21` comparison (`9YGW` absent) connecting each structure across `REFMAC5 BREF ISOT` and `REFMAC5 BREF ANIS` alongside common-subset `PHENIX` and `Gemmi`, highlighting `2VXN` (`-0.0122 → +0.0130`).*
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `ref/research/data/negative_control_round9_anis.json#/rows` and `#/x3_direction_agreement` (paired `refmac.isot.delta` and `refmac.anis.delta` values and common-21 `PHENIX`/`Gemmi` deltas)
  - `ref/research/negative_control_round9.md:20-22,24-48` (`J2/X2` and `X3` paired convention comparison)
- **Package artifacts**:
  - `data/coscientists/openscientist/slides_2026-11-06/figures/fig03_r9_isot_vs_anis_paired.png`
  - `data/coscientists/openscientist/slides_2026-11-06/figures.json#/figures/2`
- **Speaker notes**:
  Figure 3 (`figures/fig03_r9_isot_vs_anis_paired.png`) shows the common 21-structure subset across `PHENIX` (`med = +0.00320`), `Gemmi` (`med = +0.00300`), `REFMAC5 ISOT` (`med = +0.00180`), and `REFMAC5 ANIS` (`med = +0.00370`). The green dashed connecting segments between columns 3 and 4 (`build_figures.py:764-775`) show how changing only the `REFMAC5` ADP evaluation keyword shifts individual structure deltas, while the red solid line marks `2VXN` moving from `-0.0122` under `ISOT` to `+0.0130` under `ANIS`.

---

### Slide S15b (`S15b-adp-conventions-change-comparison-results`)
- **Slide ID**: `S15b` (`S15b-adp-conventions-change-comparison-results`)
- **Section**: `Section 4 — Empirical Results and Case-Study Audits`
- **title_general**: Matching the setting improves directional agreement.
- **subtitle_technical**: REFMAC sign agreement rises from 17/21 to 20/21
- **One-line message**: Switching both sides of the `REFMAC5` delta from `BREF ISOT` to `BREF ANIS` shifts its median `ΔR-free` from `+0.00180` to `+0.00370`, raises sign agreement from `17/21` to `20/21`, and flips `2VXN` from `-0.0122` to `+0.0130`.
- **Slide body**:
  - `REFMAC5` median `ΔR-free` shifts from `+0.00180` (`ISOT`) to `+0.00370` (`ANIS`) across the 21 controls.
  - Delta-sign agreement with `PHENIX` and `Gemmi` rises from `17/21` (`ISOT`) to `20/21` (`ANIS`).
  - `2VXN` flips from `-0.0122` (`ISOT`) to `+0.0130` (`ANIS`), matching positive `PHENIX` (`+0.0214`) and `Gemmi` (`+0.0220`).
  - One sign disagreement remains (`20/21`), so matching conventions does not guarantee agreement.
- **Figure**: `None`
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `ref/research/data/negative_control_round9_anis.json#/rows` and `#/x3_direction_agreement` (paired `ISOT`/`ANIS` medians, `17/21` vs `20/21` sign agreement, and `2VXN` `R-free` operands and delta flip)
  - `ref/research/negative_control_round9.md:24-48` (`J2/X2` and `X3` analysis and `2VXN`-specific baseline anisotropy-collapse mechanism)
- **Package artifacts**:
  - `data/coscientists/openscientist/slides_2026-11-06/figures.json#/figures/2/derived_summaries`
- **Speaker notes**:
  Across the 21 common negative controls (`ref/research/data/negative_control_round9_anis.json#/rows` and `#/x3_direction_agreement`), switching `REFMAC5` from `BREF ISOT` to `REFI BREF ANIS` shifts its median `ΔR-free` from `+0.00180` to `+0.00370` (compared with `+0.00320` on `PHENIX` and `+0.00300` on `Gemmi` on the same 21 entries) and raises delta-sign agreement with `PHENIX` and `Gemmi` from `17/21` to `20/21`. For `2VXN` specifically (`ref/research/negative_control_round9.md:42-48`, `negative_control_round9_anis.json#/rows` for `pdb_id = "2VXN"`), collapsing deposited anisotropic ADPs under `BREF ISOT` penalized the deposited baseline (`R-free` `0.1712` `ISOT` vs `0.1371` `ANIS`) more than the re-refined model (`0.1590` `ISOT` vs `0.1501` `ANIS`), producing an apparent `-0.0122` improvement (`0.1590 − 0.1712`) that flips to `+0.0130` (`0.1501 − 0.1371`) under `ANIS`. That baseline-penalty mechanism is specific to `2VXN` and is not uniform across the 21-entry cohort: the `ANIS − ISOT` delta shift is negative on four structures (`7R2H`, `6ZWY`, `7TVL`, and `9TEU`). Even under `ANIS`, one directional disagreement remains (`20/21`).

---

### Slide S16a (`S16a-recovery-leaves-spread-of-changes-intro`)
- **Slide ID**: `S16a` (`S16a-recovery-leaves-spread-of-changes-intro`)
- **Section**: `Section 4 — Empirical Results and Case-Study Audits`
- **title_general**: Recovery is compared with the original structure.
- **subtitle_technical**: Round-10 osol_h recovery relative to deposited baselines
- **One-line message**: Before viewing the Round-10 recovery distributions, we define `recovery refinement`, the multi-factor `osol_h` regimen, baseline-referenced `ΔR-free`, and the `W4` recovery check.
- **Terms**:
  - **`recovery refinement`**: Recovery refinement starts from a deliberately perturbed model to test recovery of its original structure and data fit.
  - **`osol_h`**: `osol_h` names the historical Round-10 recovery protocol combining ordered-solvent refinement with riding hydrogens, regenerated `phenix.dynamics` perturbations, and `REFMAC5 ANIS` evaluation.
  - **`riding hydrogens`**: Riding hydrogens follow the positions of their attached heavy atoms during refinement.
  - **`ordered solvent`**: Ordered solvent is solvent represented explicitly in the model, such as modeled water molecules (`ordered_solvent=True`).
  - **`R-free`**: `R-free` measures model–data disagreement on reflections withheld from refinement.
  - **`ΔR-free` (`recovered − baseline`)**: `ΔR-free` here is the post-recovery `R-free` minus the deposited baseline (unitless fraction), rather than minus the damaged intermediate.
  - **`ANIS`**: `ANIS` is the `REFMAC5` zero-cycle evaluation mode (`REFI BREF ANIS`) that applies retained anisotropic displacement parameters.
  - **`§6`**: `§6` denotes Section 6 of the repository's threshold registry, containing the negative-control benchmark rules.
  - **`W4`**: `W4` is the benchmark check that rejects a claimed recovery success when a measurable positive `R` residual exceeds twice its registered threshold (`> 2 × §6`).
  - **`n` / `med`**: `n` is the number of structures (`n = 22` for `PHENIX` and `Gemmi`; `n = 21` for `REFMAC5 ANIS`, with `9YGW` excluded), and `med` is the group median.
- **Slide body**:
  - **The experiment**:
    - Each deposited control was perturbed by heated molecular dynamics (`phenix.dynamics`, `stop_at_diff=0.5`, `seed=42`) and then re-refined under the historical `osol_h` recovery workflow (`phenix.ready_set` riding hydrogens and `ordered_solvent=True`), with `ΔR-free` measured relative to the original deposited baseline.
  - **Reading the figure**:
    - Blue circles (`PHENIX`, `n = 22`), orange diamonds (`Gemmi`, `n = 22`), and green upward triangles (`REFMAC5 ANIS`, `n = 21`) are plotted on the same `(-0.016, +0.036)` y-axis scale as the zero-dose null figure, with dashed horizontal `§6` reference segments and red callouts on `2VXN`.
- **Figure**: `None`
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `ref/research/negative_control_round10.md:11-40` (Round-10 `osol_h` protocol, regenerated perturbations disclosure, and baseline-referenced `ΔR-free` definition)
  - `ref/research/data/negative_control_round10_recover.json#/rows` and `#/run/fit_thresholds` (stored delta-only recovery rows and registered thresholds)
  - `ref/thresholds_and_standards.md:262-264` (`§6` zero-dose drift bounds and `W4` recovery check definition)
  - `ref/research/refinement_assessment_case_study_2026-10-18.md:160-166` (case-study summary of Round-10 multi-factor recovery and `W4` handling)
- **Package artifacts**:
  - `data/coscientists/openscientist/slides_2026-11-06/build_figures.py` (`build_fig04_r10_recovery_delta_rfree`, `draw_box_and_strip`)
  - `data/coscientists/openscientist/slides_2026-11-06/figures.json#/figures/3`
- **Speaker notes**:
  This intro slide defines the Round-10 `osol_h` recovery test plotted in Figure 4 (`ref/research/negative_control_round10.md:11-40`). Unlike a delta measured against the perturbed intermediate, every `ΔR-free` value here is `recovered − deposited baseline`: zero means returning to the deposited baseline `R-free`, positive values mean the recovered model still has higher `R-free` than the deposited structure, and negative values mean lower `R-free` than the deposited baseline. Because Round 10 regenerated the `phenix.dynamics` perturbations (`stop_at_diff=0.5`, `seed=42`) and simultaneously enabled `phenix.ready_set` riding hydrogens, `ordered_solvent=True`, and `REFMAC5 ANIS`, it is a historical multi-factor regimen rather than an isolated single-factor ablation.

---

### Slide S16 (`S16-recovery-leaves-spread-of-changes`)
- **Slide ID**: `S16` (`S16-recovery-leaves-spread-of-changes`)
- **Section**: `Section 4 — Empirical Results and Case-Study Audits`
- **title_general**: Recovery leaves a wide range of changes.
- **subtitle_technical**: Round-10 recovery ΔR-free in native evaluator populations
- **One-line message**: Figure 4 plots the Round-10 `osol_h` recovery `ΔR-free` distributions relative to deposited baselines across `PHENIX` (`n = 22`), `Gemmi` (`n = 22`), and `REFMAC5 ANIS` (`n = 21`), highlighting `2VXN`.
- **Slide body**:
  - Positive and negative changes coexist across structures, and 2VXN has opposing signs across evaluators.
- **Figure**: `figures/fig04_r10_recovery_delta_rfree.png` — *Round-10 `osol_h` recovery `ΔR-free` relative to deposited baselines across `PHENIX` (`n = 22`), `Gemmi` (`n = 22`), and `REFMAC5 ANIS` (`n = 21`, `9YGW` absent) on the shared `(-0.016, +0.036)` y-axis scale, highlighting `2VXN` (`+0.0221 / +0.0211` vs `REFMAC -0.0095`).*
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `ref/research/data/negative_control_round10_recover.json#/rows` and `#/summary` (`recovered.numbers.d_phenix`, `d_gemmi`, `d_refmac`, and `W4` count)
  - `ref/research/negative_control_round10.md:22-49,92-94` (Round-10 `osol_h` distributions and `2VXN` `W4` exception)
- **Package artifacts**:
  - `data/coscientists/openscientist/slides_2026-11-06/figures/fig04_r10_recovery_delta_rfree.png`
  - `data/coscientists/openscientist/slides_2026-11-06/figures.json#/figures/3`
- **Speaker notes**:
  Figure 4 (`figures/fig04_r10_recovery_delta_rfree.png`) plots the Round-10 `osol_h` recovery `ΔR-free` distributions on the same `(-0.016, +0.036)` vertical axis as Figure 2. Across the cohort, individual structures span negative values (below the deposited baseline `R-free`) to positive residuals above `+0.03`, while `2VXN` sits near the top of the `PHENIX` (`+0.0221`) and `Gemmi` (`+0.0211`) distributions but below zero on `REFMAC5 ANIS` (`-0.0095`).

---

### Slide S16b (`S16b-recovery-leaves-spread-of-changes-results`)
- **Slide ID**: `S16b` (`S16b-recovery-leaves-spread-of-changes-results`)
- **Section**: `Section 4 — Empirical Results and Case-Study Audits`
- **title_general**: A disagreement limits the recovery claim.
- **subtitle_technical**: Positive medians and the retained 2VXN W4 exception
- **One-line message**: Relative to deposited baselines, Round-10 recovery `ΔR-free` medians are `+0.00630` (`PHENIX`), `+0.00800` (`Gemmi`), and `+0.00730` (`REFMAC5 ANIS`), with `2VXN` retained as an explicit `W4` exception (`1` case).
- **Slide body**:
  - Native recovery `ΔR-free` medians are `+0.00630` (`PHENIX`, `n = 22`), `+0.00800` (`Gemmi`, `n = 22`), and `+0.00730` (`REFMAC5 ANIS`, `n = 21`).
  - On `2VXN`, `Gemmi` (`+0.0211 > 0.02050`) triggers `W4` while `PHENIX` (`+0.0221 < 0.02400`) worsens and `REFMAC5 ANIS` improves (`-0.0095`).
  - Cross-family conflict blocks a fit-degradation verdict, while `W4` prevents self-certified recovery (`1` case, nonzero exit).
  - Regenerated perturbations and protocol changes occurred together, so hydrogen causality is not isolated.
- **Figure**: `None`
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `ref/research/data/negative_control_round10_recover.json#/rows` and `#/summary` (native and common-21 medians, `2VXN` deltas `+0.0221 / +0.0211 / -0.0095`, and `W4` count `1`)
  - `ref/research/negative_control_round10.md:22-49,92-94` (`K1` regenerated perturbations with seed `42`, `2VXN` `W4` trigger and nonzero exit, and non-certified status)
  - `ref/thresholds_and_standards.md:262-264` (`§6` thresholds and `W4` recovery check)
- **Package artifacts**:
  - `data/coscientists/openscientist/slides_2026-11-06/figures.json#/figures/3/derived_summaries`
- **Speaker notes**:
  In `ref/research/data/negative_control_round10_recover.json#/rows`, which stores delta values (`d_phenix`, `d_gemmi`, `d_refmac`) rather than absolute `R-free` endpoints, native recovery `ΔR-free` medians are `+0.00630` on `PHENIX` (`n = 22`), `+0.00800` on `Gemmi` (`n = 22`), and `+0.00730` on `REFMAC5 ANIS` (`n = 21`; on the common 21-structure subset where `recovered.numbers.d_refmac` is non-null, `PHENIX` and `Gemmi` medians are `+0.00550` and `+0.00730`). On `2VXN`, `Gemmi` (`+0.0211`) exceeds twice its `§6` threshold (`2 × 0.01025 = 0.02050`), whereas `PHENIX` (`+0.0221`) stays below `2 × 0.01200 = 0.02400` and `REFMAC5 ANIS` reports `-0.0095` (`ref/thresholds_and_standards.md:264`). As `ref/research/negative_control_round10.md:42-47` records, the cross-family conflict prevents a fit-degradation verdict, but `W4` (`summary` count `1`) prevents the nominal success from certifying itself and the round exits nonzero. Because Round 10 regenerated perturbations (with the same registered `seed=42`) alongside riding hydrogens, ordered solvent, and `REFMAC5 ANIS`, it does not isolate a single-factor hydrogen effect (`lines 24-29,92-94`).

---

### Slide S17a (`S17a-library-and-population-choices-shift-bond-rmsd-intro`)
- **Slide ID**: `S17a` (`S17a-library-and-population-choices-shift-bond-rmsd-intro`)
- **Section**: `Section 4 — Empirical Results and Case-Study Audits`
- **title_general**: Bond measurements depend on what is counted.
- **subtitle_technical**: Published A/B/C bond-RMSD configurations and equal-count subsets
- **One-line message**: Before examining the 17-model bond-geometry figure, we define bond-length `RMSD` in `Å` (versus dimensionless `RMSZ`), configurations `A`/`B`/`C`, absolute shifts `|B − A|` and `|C − B|`, and equal versus different bond counts.
- **Terms**:
  - **`Å`**: `Å` denotes the ångström, the distance unit used here for bond-length deviations.
  - **`bond RMSD`**: Bond root-mean-square deviation measures modeled bond-length differences from their restraint targets in `Å`.
  - **`RMSZ`**: `RMSZ` is the root mean square of target deviations divided by their restraint uncertainties, so it has no units and is not plotted here.
  - **`A` / `B` / `C`**: `A`, `B`, and `C` label the three published tool-and-library configurations (`A: PHENIX CDL`, `B: PHENIX E&H`, and `C: Gemmi 0.7.4 rmsz`).
  - **`CDL`**: `CDL` is the conformation-dependent geometry library used by `PHENIX` in configuration `A`.
  - **`E&H`**: `E&H` denotes the static Engh and Huber geometry targets used by `PHENIX` in configuration `B`.
  - **`CCP4 Monomer Library`**: The `CCP4 Monomer Library` supplies the related but non-identical geometry targets used by `Gemmi` in configuration `C`.
  - **`|B − A|` / `|C − B|`**: The bars in `|B − A|` and `|C − B|` denote the magnitude of each pairwise bond-RMSD difference in `Å`, irrespective of sign.
  - **`equal` (`eq`) / `different` (`diff`) bond counts**: Equal bond counts (`eq`, `n = 6`) mean equal numbers of evaluated bonds between `PHENIX` and `Gemmi` without proving that the bond lists are identical, whereas `diff` (`n = 11`) marks models with unequal bond counts.
  - **`n` / `med`**: `n` is the number of models in each plotted group (`n = 17` total, split into `n = 6` and `n = 11`), and `med` is the group median.
- **Slide body**:
  - **The experiment**:
    - We reconstructed the 17 deposited X-ray rows from the committed restraint-library and bond-RMSD benchmark tables at published precision (without a raw rerun) across `A: PHENIX CDL`, `B: PHENIX E&H`, and `C: Gemmi 0.7.4` (`CCP4 Monomer Library`).
  - **Reading the figure**:
    - Panel A plots `bond RMSD` (`Å`, not dimensionless `RMSZ`) for `A` (blue circles), `B` (light-blue squares), and `C` (orange diamonds) connected by solid dark lines when bond counts match (`eq`, `n = 6`) and dotted muted lines when counts differ (`diff`, `n = 11`), while Panel B splits `|B − A|` and `|C − B|` by `eq` versus `diff` with no single agreement threshold drawn across groups.
- **Figure**: `None`
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `ref/research/tolerance_benchmark_restraint_library.md:17-32,38-65,109-118` (`A/B/C` configurations, 17-model published table, and near-matched `B vs C` scope)
  - `ref/research/tolerance_benchmark_bond_rmsd.md:17-29,35-59,104-105` (17 deposited X-ray models, per-model bond counts, `6` equal-count vs `11` different-count split, and unverified restraint-list diff caveat)
  - `ref/structural_criteria.yaml:478-505` and `ref/quality_reporting.md:52` (`bond RMSD` in `Å` vs dimensionless `RMSZ`)
  - `ref/research/template_tolerance_review.md:25-32` (`RMSD` vs `RMSZ` unit and normalization distinction)
- **Package artifacts**:
  - `data/coscientists/openscientist/slides_2026-11-06/build_figures.py` (`build_fig05_bond_rmsd_abc`, `draw_box_and_strip`)
  - `data/coscientists/openscientist/slides_2026-11-06/figures.json#/figures/4`
- **Speaker notes**:
  This intro slide sets up Figure 5 (`figures/fig05_bond_rmsd_abc.png`), which is reconstructed directly from the committed 17-model markdown tables (`ref/research/tolerance_benchmark_restraint_library.md:38-65` and `ref/research/tolerance_benchmark_bond_rmsd.md:35-59`) at published precision without a raw rerun. Every y-axis value is bond-length RMSD in `Å` (`covalent geometry : bond` in `PHENIX` and `Model rmsD: bond` in `Gemmi 0.7.4 rmsz`), never dimensionless `RMSZ`. Panel A retains all 17 models on the full vertical axis—including the `30TW` outlier (`C = 0.08100 Å`)—and uses solid dark connecting lines for the `6` models with equal `PHENIX` and `Gemmi` bond counts and dotted muted lines for the `11` models with different bond counts. Panel B plots the absolute shifts `|B − A|` and `|C − B|` separately for the `eq` (`n = 6`) and `diff` (`n = 11`) populations; no horizontal grading threshold is drawn because no single cross-tool threshold applies across unequal restraint populations.

---

### Slide S17 (`S17-library-and-population-choices-shift-bond-rmsd`)
- **Slide ID**: `S17` (`S17-library-and-population-choices-shift-bond-rmsd`)
- **Section**: `Section 4 — Empirical Results and Case-Study Audits`
- **title_general**: The measurement setup changes the reported bond fit.
- **subtitle_technical**: Bond-RMSD distributions for 17 models with population limits retained
- **One-line message**: Figure 5 plots all 17 published bond-RMSD observations across `A`, `B`, and `C` alongside the `6` equal-count and `11` different-count pairwise shift distributions.
- **Slide body**:
  - Reconstructed at published precision; all 17, 6 and 11 observations remain visible.
- **Figure**: `figures/fig05_bond_rmsd_abc.png` — *Reconstructed from the committed 17-model benchmark table at published precision; no raw rerun. Panel A: Full `n = 17` bond-length RMSD (`Å`, not `RMSZ`) across `A: PHENIX CDL`, `B: PHENIX E&H`, and `C: Gemmi 0.7.4` (`30TW` `0.08100 Å` included). Panel B: Full `|B − A|` and `|C − B|` distributions split by equal (`n = 6`) vs different (`n = 11`, `|C − B|` median `0.00495 Å`, max `0.06673 Å`) bond counts; no single agreement threshold applies across these groups.*
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `ref/research/tolerance_benchmark_restraint_library.md:38-65,109-118` (17-row `A/B/C` bond-RMSD table and configuration definitions)
  - `ref/research/tolerance_benchmark_bond_rmsd.md:35-59,104-105` (per-model bond counts and `6` equal-count vs `11` different-count split)
- **Package artifacts**:
  - `data/coscientists/openscientist/slides_2026-11-06/figures/fig05_bond_rmsd_abc.png`
  - `data/coscientists/openscientist/slides_2026-11-06/figures.json#/figures/4`
- **Speaker notes**:
  Figure 5 (`figures/fig05_bond_rmsd_abc.png`) shows all 17 published models in Panel A (`n = 17` per configuration) and both population subgroups (`eq`, `n = 6`; `diff`, `n = 11`) in Panel B. Keeping `30TW` (`C = 0.08100 Å`, `|C − B| = 0.06673 Å`) on the main canvas makes the unequal-population tail immediately visible alongside the tighter `|B − A|` and equal-count `|C − B|` distributions.

---

### Slide S17b (`S17b-library-and-population-choices-shift-bond-rmsd-results`)
- **Slide ID**: `S17b` (`S17b-library-and-population-choices-shift-bond-rmsd-results`)
- **Section**: `Section 4 — Empirical Results and Case-Study Audits`
- **title_general**: Equal counts do not ensure equal bonds.
- **subtitle_technical**: Related libraries and restraint populations confound the cross-tool contrast
- **One-line message**: All-model bond-RMSD medians are `0.00872 Å` (`A`), `0.00914 Å` (`B`), and `0.01100 Å` (`C`), with only `6/17` models sharing equal bond counts and neither library nor population effects isolated alone in `B vs C`.
- **Slide body**:
  - All-model bond-RMSD medians are `0.00872 Å` (`A: PHENIX CDL`), `0.00914 Å` (`B: PHENIX E&H`), and `0.01100 Å` (`C: Gemmi 0.7.4`).
  - Only `6/17` models share equal bond counts (`|B − A|` median `0.00085 Å`, `|C − B|` median `0.00320 Å`), while `11/17` have different counts (`|C − B|` median `0.00495 Å`).
  - On `30TW`, `Gemmi` reaches `0.08100 Å` (`|C − B| = 0.06673 Å`) while evaluating `9,544` bonds versus `PHENIX`'s `4,677`.
  - In `B` versus `C`, because target dictionaries are not identical and restraint lists were not diffed, neither library nor population effects are isolated alone (`A` versus `B` isolates the within-`PHENIX` library switch).
- **Figure**: `None`
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `ref/research/tolerance_benchmark_restraint_library.md:38-65,109-118` (17-row `A/B/C` medians, `6/17` vs `11/17` subgroup shifts, and near-matched `B vs C` contrast caveat)
  - `ref/research/tolerance_benchmark_bond_rmsd.md:35-59,104-105` (`30TW` `4,677` vs `9,544` bond counts and unverified restraint-list identity caveat)
- **Package artifacts**:
  - `data/coscientists/openscientist/slides_2026-11-06/figures.json#/figures/4/derived_summaries`
- **Speaker notes**:
  Across all 17 deposited X-ray models (`ref/research/tolerance_benchmark_restraint_library.md:38-65`), published bond-RMSD medians are `0.00872 Å` (`A: PHENIX CDL`), `0.00914 Å` (`B: PHENIX E&H`), and `0.01100 Å` (`C: Gemmi 0.7.4`). Splitting by evaluated bond counts (`ref/research/tolerance_benchmark_bond_rmsd.md:35-59`) separates the `6/17` equal-count models (`|B − A|` median `0.00085 Å`, `|C − B|` median `0.00320 Å`) from the `11/17` different-count models (`|B − A|` median `0.00035 Å`, `|C − B|` median `0.00495 Å`, reaching `0.06673 Å` on `30TW` where `Gemmi` evaluates `9,544` bonds versus `PHENIX`'s `4,677`). While `A vs B` isolates the within-`PHENIX` `CDL → E&H` library switch, `tolerance_benchmark_restraint_library.md:109-113` and `tolerance_benchmark_bond_rmsd.md:104-105` document that `B vs C` is a near-matched contrast where neither library nor population effects are isolated alone because `PHENIX`'s static `E&H` dictionary and `Gemmi`'s `CCP4 Monomer Library` are not identical and equal bond counts were not verified by restraint-list diffing.

---

### Slide S18a (`S18a-shared-methods-limit-classifier-agreement-intro`)
- **Slide ID**: `S18a` (`S18a-shared-methods-limit-classifier-agreement-intro`)
- **Section**: `Section 4 — Empirical Results and Case-Study Audits`
- **title_general**: Percentages need comparable populations.
- **subtitle_technical**: Raw rotamer-outlier percentages and shared-key classifications
- **One-line message**: Before viewing the Round-46 classifier comparison, we define rotamers, rotamer outliers, pipeline-specific outlier percentages, percentage points (`pp`), four-part shared residue keys, and `MolProbity`/`wwPDB` roles.
- **Terms**:
  - **`rotamer`**: A rotamer is a side-chain conformation classified against a reference distribution.
  - **`rotamer outlier`**: A rotamer outlier is a side chain classified outside the accepted region of that reference distribution (`OUTLIER`).
  - **`outlier %`**: The outlier percentage expresses rotamer outliers relative to the residue population evaluated by that pipeline.
  - **`pp`**: Percentage points are the arithmetic difference (`PHENIX − wwPDB`) between two reported percentages.
  - **`shared key`**: A shared key identifies a residue evaluated by both pipelines using four components: chain identifier, residue number, insertion code, and residue name (`(chain, resnum, icode, resname)`, with `altloc` not part of the key).
  - **`classification agreement`**: Classification agreement is the fraction of shared keys assigned the same verdict.
  - **`altloc`**: An `altloc` labels an alternate modeled atomic conformation and can affect which residue population a pipeline evaluates.
  - **`MolProbity`**: `MolProbity` is the validation method family underlying both classifiers in this comparison (distinct from the composite MolProbity score).
  - **`wwPDB`**: `wwPDB` is the Worldwide Protein Data Bank organization, whose validation report supplies the deposited structure's reference classifications.
  - **`n` / `med`**: `n` is the number of positive-denominator protein entries (`n = 41` of `42` retained rows in `round46_vs_deposited.json`, with nucleic-acid entry `12CI` excluded for zero shared rotamer and Ramachandran keys), and `med` is the group median.
- **Slide body**:
  - **The experiment**:
    - Across the 41 positive-denominator protein entries in `round46_vs_deposited.json` (`12CI` excluded for zero shared rotamer and Ramachandran keys), we compared `phenix.rotalyze` against deposited `wwPDB` validation reports in two ways: raw summary `outlier %` over each pipeline's own denominator and per-residue verdicts matched on the four-part `shared key` `(chain, resnum, icode, resname)`.
  - **Reading the figure**:
    - Panel A pairs each protein's raw `PHENIX` (blue circles) and `wwPDB` (purple squares) rotamer-outlier percentages (`red` lines highlight nonzero differences on `14ZZ` and `2YOL`), while Panel B plots the raw `PHENIX − wwPDB` shift in `pp` alongside the reconstructed shared-key `OUTLIER` agreement callout.
- **Figure**: `None`
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `ref/tools_and_measurements_guide.md:153` and `ref/quality_reporting.md:49-51` (`rotamer` and `rotamer outlier` definitions)
  - `scripts/bench_vs_deposited.py:145-180` and `scripts/check_pass_status.py:470-471` (pipeline-reported `outlier %` and `pp` arithmetic difference)
  - `ref/thresholds_and_standards.md:107-108` (`altloc` population handling)
  - `ref/research/tolerance_benchmark_round46.md:32-63` and `ref/research/t05_classification_floor_adoption_2026-09-27.md:11-17,31-61` (41-protein cohort, `12CI` zero shared rotamer and Ramachandran keys exclusion, four-part shared key without `altloc`, and `MolProbity` lineage)
- **Package artifacts**:
  - `data/coscientists/openscientist/slides_2026-11-06/build_figures.py` (`build_fig06_round46_rotamer_outlier_pct`, `draw_box_and_strip`)
  - `data/coscientists/openscientist/slides_2026-11-06/figures.json#/figures/5`
- **Speaker notes**:
  This intro slide defines the two comparison levels shown in Figure 6 (`figures/fig06_round46_rotamer_outlier_pct.png`). The Round-46 dataset (`ref/research/data/round46_vs_deposited.json`) contains 42 retained entries; excluding the nucleic-acid entry `12CI` (`rotamer_n_shared = 0` and `ramachandran_n_shared = 0`, zero shared rotamer and Ramachandran keys) leaves `n = 41` positive-denominator proteins (`ref/research/t05_classification_floor_adoption_2026-09-27.md:31-48`). Panel A and Panel B plot the raw reported rotamer-outlier percentages (`outlier %`) and their `PHENIX − wwPDB` arithmetic difference in percentage points (`pp`), where each pipeline divides by its own evaluated residue population. Separately, the per-residue comparison matches residues on the four-part key `(chain, resnum, icode, resname)`—chain identifier, residue number, insertion code, and residue name (`altloc` is not an extra field in the key, though alternate conformations can affect which residues a pipeline evaluates; `ref/thresholds_and_standards.md:107-108`, `t05_classification_floor_adoption_2026-09-27.md:55-61`).

---

### Slide S18 (`S18-shared-methods-limit-classifier-agreement`)
- **Slide ID**: `S18` (`S18-shared-methods-limit-classifier-agreement`)
- **Section**: `Section 4 — Empirical Results and Case-Study Audits`
- **title_general**: Matching labels can coexist with different percentages.
- **subtitle_technical**: 41 proteins, raw reported percentages and shared-key OUTLIER verdicts
- **One-line message**: Figure 6 contrasts raw reported rotamer-outlier percentages across the 41 Round-46 proteins (`14ZZ -1.52 pp`, `2YOL +0.57 pp`) with `1.0000` shared-key binary `OUTLIER` agreement.
- **Slide body**:
  - Plotted percentages are raw pipeline summaries, not recalculated shared-residue rates.
- **Figure**: `figures/fig06_round46_rotamer_outlier_pct.png` — *Panel A: Raw reported rotamer outlier `%` from `phenix.rotalyze` vs `wwPDB` validation reports across `n = 41` proteins (`12CI` excluded). Panel B: Raw `%` difference (`PHENIX − wwPDB`, showing `14ZZ -1.52 pp` and `2YOL +0.57 pp`) contrasted with `1.0000` shared-key binary `OUTLIER` agreement.*
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `ref/research/data/round46_vs_deposited.json#/rows` and `#/summary` (`41` protein rows, `12CI` zero denominator, raw `%` values, and shared-key counts)
  - `ref/research/tolerance_benchmark_round46.md:48-63,79-80` (raw `%` denominator shifts on `14ZZ` and `2YOL` vs shared-key agreement)
  - `ref/research/t05_classification_floor_adoption_2026-09-27.md:11-23,31-56` (integer shared-key recount and reconstructed binary `OUTLIER` agreement)
- **Package artifacts**:
  - `data/coscientists/openscientist/slides_2026-11-06/figures/fig06_round46_rotamer_outlier_pct.png`
  - `data/coscientists/openscientist/slides_2026-11-06/figures.json#/figures/5`
- **Speaker notes**:
  Figure 6 (`figures/fig06_round46_rotamer_outlier_pct.png`) contrasts raw summary percentages with shared-key residue classifications across the `n = 41` proteins (`median 6.54%` on both `PHENIX` and `wwPDB`). While `39/41` proteins have `0.00 pp` raw difference, `14ZZ` (`3.49%` vs `5.01%`, `-1.52 pp`) and `2YOL` (`10.17%` vs `9.60%`, `+0.57 pp`) diverge because the two pipelines evaluated different total residue counts (`ref/research/tolerance_benchmark_round46.md:48-63`).

---

### Slide S18b (`S18b-shared-methods-limit-classifier-agreement-results`)
- **Slide ID**: `S18b` (`S18b-shared-methods-limit-classifier-agreement-results`)
- **Section**: `Section 4 — Empirical Results and Case-Study Audits`
- **title_general**: Agreement shows reproduction within a shared method.
- **subtitle_technical**: MolProbity-derived pipelines and the limits of binary OUTLIER agreement
- **One-line message**: Across the 41 Round-46 proteins (`12CI` excluded), reconstructed shared-key `OUTLIER` verdicts agree `38,744 / 38,744` (`1.0000`) within shared `MolProbity` lineage while raw percentages shift on `14ZZ` (`-1.52 pp`) and `2YOL` (`+0.57 pp`).
- **Slide body**:
  - Across the `42` retained entries in `round46_vs_deposited.json`, `41` proteins have positive denominators (`12CI` has zero shared rotamer and Ramachandran keys and is excluded).
  - Raw `PHENIX − wwPDB` rotamer-outlier differences are `0.00 pp` on `39/41` proteins, with denominator-driven shifts on `14ZZ` (`-1.52 pp`) and `2YOL` (`+0.57 pp`).
  - Reconstructed binary `OUTLIER` verdicts agree on all `38,744 / 38,744` shared four-part rotamer keys (`1.0000`).
  - Because both pipelines share MolProbity lineage, this agreement tests reference reproduction rather than independent methods.
- **Figure**: `None`
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `ref/research/data/round46_vs_deposited.json#/rows` and `#/summary` (`42` retained rows, `41` positive-denominator protein rows, `12CI` zero shared rotamer and Ramachandran keys, `14ZZ`/`2YOL` raw `%` shifts, and `38,741 / 38,744` rotamer-name / `46,677 / 46,677` Ramachandran shared-key counts)
  - `ref/research/t05_classification_floor_adoption_2026-09-27.md:11-23,31-56` (reconstructed binary `OUTLIER` agreement from summarized producer output, unretained `15C8` report-side `Favored`/`Allowed` labels, and `MolProbity` reference-reproduction boundary)
  - `ref/research/tolerance_benchmark_round46.md:48-63,79-80` (`14ZZ` `402` shared vs `459` report residues, `2YOL` denominator shift, and shared-lineage caveat)
- **Package artifacts**:
  - `data/coscientists/openscientist/slides_2026-11-06/figures.json#/figures/5/derived_summaries`
- **Speaker notes**:
  In `ref/research/data/round46_vs_deposited.json#/rows` (`n = 41` positive-denominator proteins out of `42` retained entries after excluding `12CI`, which has zero shared rotamer and Ramachandran keys), raw reported rotamer-outlier percentages match to `0.00 pp` on `39/41` entries and differ on `14ZZ` (`-1.52 pp`, where `402` shared keys compare against `459` `wwPDB` report residues) and `2YOL` (`+0.57 pp`; `ref/research/tolerance_benchmark_round46.md:48-63`). Across the `38,744` shared four-part `(chain, resnum, icode, resname)` rotamer keys, exact rotamer-name agreement is `38,741 / 38,744` (`0.999923`, with `3` non-outlier rotamer-name differences on `15C8`), and binary `OUTLIER` versus non-outlier agreement is `38,744 / 38,744` (`1.0000`, alongside `46,677 / 46,677` Ramachandran agreement). As `ref/research/t05_classification_floor_adoption_2026-09-27.md:43-56` records, that binary `OUTLIER` agreement is reconstructed from summarized producer output rather than a fresh XML/log audit (report-side `Favored`/`Allowed` labels for `15C8` are not retained), and because both `phenix.rotalyze` and `wwPDB` validation reports share `MolProbity` lineage, `1.0000` agreement demonstrates reference reproduction rather than cross-family independence.

---

### Slide S19 (`S19-actual-1sar-input-differs-from-deposited`)
- **Slide ID**: `S19` (`S19-actual-1sar-input-differs-from-deposited`)
- **Section**: `Section 4 — Empirical Results and Case-Study Audits`
- **title_general**: The starting structure differs from its public reference.
- **subtitle_technical**: Actual 1SAR inputs versus the deposited structure
- **One-line message**: In the retained `1SAR` archive (`cdba2c07`), the starting model `data/1sar.pdb` (`0` waters) and `2.50 Å` dataset `data/1sar.mtz` differ from the `1.80 Å` deposited `1SAR` entry (`FREE R VALUE : NULL`).
- **Slide body**:
  - The archived starting coordinates and diffraction data define the before/after baseline.
  - The public reference has different data resolution and no deposited free-R value.
  - Historical final-model observations do not independently measure the before/after change.
- **Figure**: `None`
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `ref/research/refinement_assessment_case_study_2026-10-18.md:24-33,41-49,59-67,84-141` (`1SAR` artifact inventory, `2.50 Å` vs `1.80 Å` context, `FREE R VALUE : NULL`, reflection retention, and historical observation limits)
  - `ref/tools_and_measurements_guide.md:88` (archive reflection recount vs unestablished historical effective denominators and start-to-final selections)
- **Speaker notes**:
  Slide 19 summarizes what can and cannot be concluded about the `1SAR` baseline (`ref/research/refinement_assessment_case_study_2026-10-18.md:24-33,41-49,84-141`). The actual starting model inside the archive is `data/1sar.pdb` (`1,498` non-hydrogen atoms, `0` waters, evaluated with `data/1sar.mtz` at `49.972–2.500 Å`), not the `1.80 Å` 1991 deposited `1SAR` reference (`138` waters, `REMARK 3 FREE R VALUE : NULL`, which makes the deposited-`R-free` clause `unevaluable`). Direct byte-level audits quantify coordinate `RMSD`—root-mean-square coordinate displacement after best-fit rigid (`Kabsch`) alignment across the `192` shared `Cα` (backbone alpha-carbon) atoms (`0.4191 Å`, `line 122`)—along with inventory changes (`0 → 146` waters, one sulfate ion `SO4` removed, and one calcium ion `CA`, distinct from backbone `Cα`, plus one sodium ion `NA` added) and reflection retention (`6,494` work and `723` free reflections with positive structure-factor amplitude `F` preserved; `11` zero-`F` work reflections converted to `NaN`, a missing numeric value, `audit_status: "not_preserved"`). Historical `phenix` (`0.3956 → 0.2116` `R-free`), `REFMAC5` (`0.2128`), `Servalcat` (`0.2209`, `n_free = 362`), and bin-rescaled `gemmi` (`0.2136`) records lack raw outputs and effective selections, and the non-`cctbx` records evaluate only the final model rather than remeasuring the before/after delta (`lines 59-67`).

---

### Slide S20 (`S20-packaged-1sar-differs-from-reported-final`)
- **Slide ID**: `S20` (`S20-packaged-1sar-differs-from-reported-final`)
- **Section**: `Section 4 — Empirical Results and Case-Study Audits`
- **title_general**: The packaged file is not the reported final result.
- **subtitle_technical**: Retained 1SAR Round-4 coordinates versus log-attested Round-7
- **One-line message**: Byte-level inspection of the retained `1SAR` archive proves that `data/1sar_final.pdb` is Round 4 (`146` waters), whereas the narrative report's Round 7 (`159` waters) is absent and log-attested only.
- **Slide body**:
  - The packaged final file is Round 4, with 146 waters.
  - Logs report 159 waters for Round 7, whose coordinates are absent.
  - Logs establish reported history; they cannot replace the missing structure for remeasurement.
- **Figure**: `None`
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `ref/research/refinement_assessment_case_study_2026-10-18.md:44-51` (byte-level SHA-256 inventory of `data/1sar_final.pdb` Round 4, `data/1sar_round5.pdb`, `data/1sar_round6.pdb`, and absent Round 7)
  - `ref/quality_reporting.md:196-204` (September 23 `1SAR` retained-evidence correction scope and historical QDS context)
  - `README.md:71-78` (summary of the September 23 correction on the packaged Round-4 model)
- **Speaker notes**:
  Slide 20 details the packaging discrepancy documented in `ref/research/refinement_assessment_case_study_2026-10-18.md:44-51` and `ref/quality_reporting.md:196-204`. The OpenScientist narrative report and `claude_iterations.log` (`lines 510, 752`) described a Round-7 final model (`R_work / R_free = 0.1488 / 0.1989`, `159` waters, `1,654` heavy atoms, restored `B:97:SO4`). However, SHA-256 inspection of `cdba2c07-daff-4f60-ae96-12452b3a5fbb_artifacts.zip` showed that `data/1sar_final.pdb` is the Round-4 model (`0.1563 / 0.2114` header, `0.1564 / 0.2116` `phenix`, `146` waters, `1,641` heavy atoms), while Rounds 5 and 6 sit separately in the archive and Round 7 was never packaged. In current repository records, packaged-output assessment concerns the retained Round-4 model, while Rounds 5 and 6 remain separate archive intermediates and Round 7 is recorded as unretained and log-attested only.

---

### Slide S21 (`S21-prosmart-shape-does-not-measure-rama-z`)
- **Slide ID**: `S21` (`S21-prosmart-shape-does-not-measure-rama-z`)
- **Section**: `Section 4 — Empirical Results and Case-Study Audits`
- **title_general**: Similarity to another structure is a different measurement.
- **subtitle_technical**: ProSMART fragment comparisons versus Rama-Z population scoring
- **One-line message**: Capability correction `#911` deprecated `ProSMART` for `T05_rama_z_score` because reference-dependent local fragment comparison (`T02`) is not a single-model Ramachandran distribution Z-score.
- **Slide body**:
  - `ProSMART` (local fragment comparison tool) compares local backbone fragments against a reference structure or motif.
  - It does not provide the single-model `Rama-Z` (standardized comparison of a model's backbone Ramachandran distribution with a high-resolution reference population) score.
  - The recommendation was superseded; this package reports no newly measured independent `Rama-Z`.
- **Figure**: `None`
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `ref/tool_recommendations.yaml:2067-2097` (`REC_T05_rama_z_score_top_performing_2026_10_18_capability_correction` deprecating `ProSMART` for `T05_rama_z_score`)
  - `ref/tools_and_measurements_guide.md:154-157,194` (`T05` capability correction `#911`, `ProSMART` local fragment comparison, `wwPDB validation pipeline` / `Tortoize` recommendation, and `T02` routing)
  - `ref/catalog.yaml:1711-1715` (`T05_rama_z_score` single-model Ramachandran distribution Z-score definition)
- **Speaker notes**:
  Slide 21 illustrates how the harness corrects catalog capability assumptions against primary documentation (`ref/tool_recommendations.yaml:2067-2097`, `ref/tools_and_measurements_guide.md:154-157,194`, `ref/catalog.yaml:1711-1715`). `ProSMART` (Nicholls et al. 2014) was previously listed as `top_performing` for `T05_rama_z_score`. Inspection of its CLI and primary literature established that `ProSMART` computes reference-dependent local peptide fragment Procrustes, flexible, and hinging scores (`T02`) and never computes a single-model Ramachandran Z-score (`Rama-Z`, which standardizes a model's backbone `(φ, ψ)` torsion-angle distribution against a high-resolution reference population). Under `#911`, `REC_T05_rama_z_score_top_performing_2026_10_18_capability_correction` deprecates `ProSMART` for `T05_rama_z_score`, routes fragment comparisons to `T02`, and retains `wwPDB validation pipeline` / `Tortoize` (`top_considered`) as distinct from local `cctbx` `mmtbx.validation.rama_z`; no independent `Rama-Z` was newly measured for this slide package.

---

## Section 5 — Takeaways, Evidence Gaps, and Open Decisions (`S22`–`S24`)

### Slide S22 (`S22-distributions-reveal-limits-scalar-verdicts-hide`)
- **Slide ID**: `S22` (`S22-distributions-reveal-limits-scalar-verdicts-hide`)
- **Section**: `Section 5 — Takeaways, Evidence Gaps, and Open Decisions`
- **title_general**: Distributions expose limits that single scores can hide.
- **subtitle_technical**: Variation, conventions, populations and evidence boundaries
- **One-line message**: Across the extreme-resolution control cohorts, the 17-model bond-RMSD table, the 41-protein Round-46 set, and `1SAR`, full distributions expose convention, population, and provenance limits that a single scalar hides.
- **Slide body**:
  - Compare the spread, not only a typical value.
  - Track definitions, denominators and shared method lineage.
  - These examples illustrate specific safeguards; they do not establish universal grading coverage.
- **Figure**: `None`
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `ref/quality_reporting.md:19-36,189-204` (separating agreement, suitability, and improvement, and preserving disagreements and scope limits)
  - `ref/research/data/negative_control_round2_enrolled.json#/entries` (enrolled `d_min` `15 ≤ 0.90 Å` vs stored `stratum` `20` counts)
  - `ref/research/negative_control_round9.md:7-48` and `ref/research/negative_control_round10.md:9-49` (Round-9 null/ADP distributions and Round-10 recovery spread/exceptions)
  - `ref/research/tolerance_benchmark_restraint_library.md:38-66,104-118` and `ref/research/tolerance_benchmark_round46.md:48-80` (17-model bond-RMSD and 41-protein Round-46 scope limits)
  - `ref/research/refinement_assessment_case_study_2026-10-18.md:20-52` (`1SAR` and control-cohort synthesis)
- **Speaker notes**:
  Synthesizing Figures 1 through 6 and the `1SAR` audit shows why `protstruct_review` reports full distributions and separated evaluation questions instead of a single composite score (`ref/quality_reporting.md:19-36`). Each dataset exposes a concrete structural or methodological boundary: actual `d_min` (`15 ≤ 0.90 Å`) versus inherited `stratum` (`20`) in Figure 1; `ANISOU` scoring-convention sensitivity (`17/21 → 20/21` sign agreement) in Figures 2 and 3; wide recovery spread and the retained `2VXN` `W4` exception under Round 10's multi-factor regimen in Figure 4; restraint-population and dictionary confounding (`11/17` unequal bond counts) in Figure 5; denominator-sensitive raw percentages versus shared-key `MolProbity` reproduction in Figure 6; and packaged Round 4 versus absent Round 7 in `1SAR`. Together these examples illustrate specific safeguards without claiming universal grading coverage.

---

### Slide S23 (`S23-retained-gaps-define-next-evidence`)
- **Slide ID**: `S23` (`S23-retained-gaps-define-next-evidence`)
- **Section**: `Section 5 — Takeaways, Evidence Gaps, and Open Decisions`
- **title_general**: The evidence gaps define the next useful work.
- **subtitle_technical**: Missing artifacts, calibration boundaries and unresolved measurement context
- **One-line message**: Committed records distinguish retained evidence gaps—contextual verdict bindings, missing `1SAR`/recovery artifacts, restraint-population diffs, and `T14`/`T15` calibration items—from already completed control stand-downs.
- **Slide body**:
  - Admit reviewed criterion bindings before automated grading.
  - Retain missing coordinates, raw outputs and denominator evidence.
  - Resolve metric-specific calibration and population gaps; distinguish them from already completed stand-downs.
- **Figure**: `None`
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `scripts/assess_refinement.py:24-28` and `ref/structural_criteria.yaml:13-17` (`pass_criterion_bindings: []` and informational verdict status)
  - `ref/research/refinement_assessment_case_study_2026-10-18.md:51,59-72,158-166` (absent `1SAR` Round-7 coordinates, unretained raw outputs and denominators, missing second-dictionary `RMSZ`, multi-factor `R4 → R10` recovery history, and delta-only JSONs)
  - `ref/research/t05_classification_floor_adoption_2026-09-27.md:19-23` (documentary classification floor and unmeasured rotamer-favored `%` clause)
  - `ref/research/tolerance_benchmark_restraint_library.md:109-118` (unverified `11/17` bond-count diffs and near-matched `B vs C` contrast)
  - `ref/threshold_evidence_status.yaml:360-377,567-575` (`T15` exact-denominator recalibration `#765` at lines `360-377` and `T14` flip-grading policy at lines `567-575`)
  - `ref/research/negative_control_round8.md:29-39` and `ref/thresholds_and_standards.md:263-265` (completed Round-8 permanent stand-down of `9YGW` and Round-11 `{2VXN}` candidate-leg stand-down)
- **Speaker notes**:
  Committed source files distinguish retained evidence gaps from already completed stand-downs without promising unrun experiments. First, `ref/structural_criteria.yaml:13-17` keeps `pass_criterion_bindings: []`, so `scripts/assess_refinement.py:24-28` and QDS classification-agreement rows remain `"informational"` until reviewed bindings are admitted (`ref/research/t05_classification_floor_adoption_2026-09-27.md:19-23`). Second, `1SAR` lacks the logged Round-7 coordinate file, a second-dictionary `RMSZ` check, and raw historical outputs/effective denominators (`ref/research/refinement_assessment_case_study_2026-10-18.md:51,59-72`), while the Round-4/Round-10 recovery JSONs store deltas only across a multi-factor protocol change (`lines 158-166`). Third, `11/17` bond-RMSD models lack restraint-list diffs (`ref/research/tolerance_benchmark_restraint_library.md:109-118`), Round 46 tests shared-lineage `MolProbity` reproduction, and `ref/threshold_evidence_status.yaml` records `T15` exact-denominator recalibration (`lines 360-377`, `#765`) and `T14` flip-grading scope (`lines 567-575`). By contrast, the negative-control series already completed the permanent Round-8 stand-down of `9YGW` (`ref/research/negative_control_round8.md:29-39`) and the Round-11 `{2VXN}` candidate-leg third-opinion stand-down (`ref/thresholds_and_standards.md:263-265`).

---

### Slide S24 (`S24-project-choices-set-next-step`)
- **Slide ID**: `S24` (`S24-project-choices-set-next-step`)
- **Section**: `Section 5 — Takeaways, Evidence Gaps, and Open Decisions`
- **title_general**: The next step depends on the project priorities.
- **subtitle_technical**: Open decisions for the PHENIX-agentification narrative and development scope
- **One-line message**: Historical scientific claims and figures are locked to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`, current package inputs record the resolved six-panel `Q3` layout on Slide `S06`, and `Q1`, `Q2`, and `Q4` remain open user decisions.
- **Slide body**:
  - `[USER INPUT: Q1 — Confirm the checking role within agentifying PHENIX.]` and `[USER INPUT: Q2 — Confirm the presentation audience, talk length and technical emphasis.]`
  - Decided geometry scope (`Q3`): Slide `S06` pairs the 3 benchmarked `A/B/C` configurations (`17` models) above 3 lower categories (`force-field restraints`; `ligand restraint generators and dictionaries`; `hydrogen and protonation conventions`).
  - `[USER INPUT: Q4 — Choose which source-established scientific or engineering gap from Slide S23 to prioritize next.]`
- **Figure**: `None`
- **Sources** (pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`):
  - `AGENTS.md:5-15` (two project goals used when choosing next directions of work)
  - `ref/quality_reporting.md:19-36` (evidence-based reporting principles)
- **Package artifacts**:
  - `data/coscientists/openscientist/slides_2026-11-06/questions.md` (`Q1`, `Q2`, and `Q4` open user-decision specifications; `Q3` resolved)
  - `ref/research/geometry_tool_presence_2026-11-06.json` (current package input recording filesystem presence only for the `Q3` six-panel taxonomy on Slide `S06`; no version probe was run)
- **Speaker notes**:
  We close by separating historical scientific evidence from current package inputs and open user decisions (`AGENTS.md:5-15`, `ref/quality_reporting.md:19-36`, and `data/coscientists/openscientist/slides_2026-11-06/questions.md`). All historical scientific benchmarks, provenance audits, and plotted distributions in Slides `S01` through `S23` are pinned to committed repository sources at `f3cfad326f28ddbf652dcdb0c5858443bee6e413`, whereas `questions.md` and `ref/research/geometry_tool_presence_2026-11-06.json` are current package inputs created on this branch. With `Q3` decided on Slide `S06`—pairing the 3 benchmarked `A/B/C` restraint configurations (`17` models) above 3 lower categories (`force-field restraints` via `phenix.amber`; `ligand restraint generators and dictionaries` via `phenix.eLBOW` and `CCP4 libcheck`/`AceDRG`; `hydrogen and protonation conventions` via `reduce`, `phenix.ready_set`, and `Schrödinger PrepWizard`, which are not benchmarked in that `17`-model table)—three bracketed user inputs remain: `Q1` defines the checking role within agentifying `PHENIX`, `Q2` sets the presentation audience, talk length, and technical emphasis, and `Q4` selects which source-established gap from Slide `S23` to prioritize next.
