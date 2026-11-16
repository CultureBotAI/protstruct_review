# PHENIX Refinement Evaluation Step 1 Approved Scientific Policy Selections (`U01`–`U14`, `#1048` / `#1047`)

**User approval date:** 2026-11-15
**Authored date:** 2026-11-15
**Registration status:** `selected_decisions_recorded` (**NOT** `frozen_result_free`)
**Base commit on `main`:** `28b6596c2ad6d88ab4e4bb0cc0f4cc32207a0156` (`28b6596`)
**Prior high-level decision baseline (`D1`–`D5`, `P1`–`P6`):** `bf7f7089e976afc16b1b826cba370cc3476530a3` (`bf7f708`, user decision date `2026-11-10`, landed via PR `#1244`)
**Authoritative Step 1 approval handoff:** `.orchestration/handoffs/step1-user-approved-decisions-2026-11-15.md` (SHA-256 `a2bde2595d47840c714bb522771a4a81f96263009ab2d001bb5ec26c7a9ddfef`, approved `2026-11-15`)

---

## 1. Provenance, Registration State, and Hard Governance Boundaries

1. **Purpose and provenance of this record (`selected_decisions_recorded` vs. `frozen_result_free`):**
   - On `2026-11-15`, the user approved the concrete Step 1 scientific and policy selections `U01`–`U14` for Issues `#1048` and `#1047`, extending the `2026-11-10` study-design selections `D1`–`D5` and `P1`–`P6` (`bf7f7089e976afc16b1b826cba370cc3476530a3`, documented in [`phenix_evaluation_protocol_design_2026-11-09.md`](phenix_evaluation_protocol_design_2026-11-09.md) and [`phenix_resolution_profile_decisions_2026-11-09.md`](phenix_resolution_profile_decisions_2026-11-09.md)) and resolving the fourteen Stage 1 decision slots enumerated in [`phenix_evaluation_preregistration_spec_2026-11-11.md`](phenix_evaluation_preregistration_spec_2026-11-11.md) §5.
   - The `2026-11-15` user-approved handoff selections override earlier unresolved menu options. They complete **Stage 1 at the study policy level (`registration_status: "selected_decisions_recorded"`)**, **NOT** Stage 4 (`registration_status: "frozen_result_free"`).
   - Recording these approved policy selections **does NOT authorize execution**: no canary runs, refinement trials, held-out target downloads, human refiner sessions, paid LLM/API requests, external email disclosures, or native `REFMAC5` executions are authorized by this document.

2. **Three-way epistemic separation — selected study policy vs. existing repository/source facts vs. future Stage 2–4 artifacts:**
   - **Selected study policy (`2026-11-15`):** Prospective rules, sample sizes, margins, factor schedules, holdout partitions, selector formulas, and budgets approved by the user for `#1048` and `#1047`.
   - **Existing repository and static vendor-source facts (`28b6596`):** Verified properties of committed scripts (`scripts/t03_reflection_retention.py:25–35, 37–149`, `scripts/gemmi_rfactor.py:10–38, 124–160, 179–249`, `scripts/checkmymetal_local.py:28–39, 69–78`), committed development exclusion datasets (`ref/research/data/negative_control_round2_enrolled.json` and `ref/research/data/refinement_assessment_1sar_and_controls_2026-10-18.json`), and read-only static AST/byte witnesses of `PHENIX 2.0-5936` under portable prefix `PHENIX_PREFIX/lib/python3.9/site-packages/` ([`phenix_resolution_profile_decisions_2026-11-09.md`](phenix_resolution_profile_decisions_2026-11-09.md) §1 and [`data/phenix_langchain_static_witness_2026-11-15.json`](data/phenix_langchain_static_witness_2026-11-15.json)).
   - **Unauthored future Stage 2–4 freeze artifacts:** Concrete Stage 2 development-frozen `.eff` files, shared dated LLM snapshot identifier and subrole configuration hashes, deterministic perturbation executables, Stage 3 enrolled held-out target tables (`N = 48`), `dedup_lineage.json`, sealed `R_sleep` derivative bundles, pre-frozen site JSONs, and Stage 4 synthetic-verified plotting scripts remain to be produced and verified in their respective sequential stages (Section 4) before the study can reach `frozen_result_free`.

3. **Zero trial outcomes, zero figures, and unchanged `pass_criterion_bindings: []` (`CODING_STANDARDS.md` rule 13c):**
   - No enrolled held-out cohort, trial execution records, outcome figures, or new `EVAL` / `QDS` records are introduced in this document.
   - `ref/structural_criteria.yaml:13–17` (`pass_criterion_bindings: []`) remains **empty and unchanged**. The prospective paired $\Delta R_{\text{free}}$ non-inferiority, equivalence, superiority, and clean-null margins (`U03`) and the outer-loop `T05` geometry guardrails (`U10`) define comparative study inference and candidate-selection policy for `#1048` / `#1047` only; they **do not create registry-bound pass verdicts** in `ref/structural_criteria.yaml`.

4. **Strict separation from `1SAR` / `REFMAC5` (`SAR1`–`SAR6`) and hold on all `REFMAC5` follow-up:**
   - All fourteen `U01`–`U14` decisions govern the PHENIX evaluation program (`#1048` / `#1047`) and are kept **strictly separate** from the `1SAR` / `REFMAC5` gate decisions `SAR1`–`SAR6` (`#1102`, `#1109`–`#1112`) with **zero assumed crosswalk**.
   - As recorded in the sibling note [`1sar_prospective_policy_selections_2026-11-15.md`](1sar_prospective_policy_selections_2026-11-15.md), all `REFMAC5` follow-up—including the offline `F3` CCP4 library check and any separately authorized `1SAR` `Attempt 05`—is **HELD until AFTER PHENIX Stage 4 (`frozen_result_free`) lands on `main`**. `SAR1`–`SAR6` are neither restated nor implemented here.

---

## 2. Approved Step 1 PHENIX Study Policy Selections (`U01`–`U14`)

### `U01` — Held-Out Target Source, Intake Filter, Missing-Header $R_{\text{free}}$ Policy, and Frozen Target Inventory Contract

- **Approved policy selection (`2026-11-15`):**
  1. **Archive source and crystallographic filter:** Candidate held-out targets must be wwPDB/RCSB X-ray diffraction entries with a **single diffraction dataset**, overall reflection **completeness $\ge 90\%$**, and **standard polymer chains** (excluding `CA`-only and `UNK`-only coordinate depositions).
  2. **Merged-amplitude MTZ and frozen integer free-mask gate (`scripts/t03_reflection_retention.py:37–149`):** Every enrolled parent MTZ must carry merged structure-factor amplitudes (`F/SIGF`) and a frozen integer free-flag partition passing `scripts/t03_reflection_retention.py:37–149`.
  3. **Minimum reflection counts and free-flag fraction band:** Each target must have **$\ge 50$ free `HKL`s** constituting **$4.5\%\text{–}10.5\%$** of eligible observations, and **$\ge 1{,}000$ work `HKL`s**.
  4. **Missing deposited header $R_{\text{free}}$ scalar policy (`D1`, `C7`):** A missing deposited header $R_{\text{free}}$ scalar does **not** exclude an otherwise eligible target with a valid frozen MTZ free mask; such targets remain eligible with `deposition_clause = "unevaluable"` (`scripts/t03_reflection_retention.py:25–35`).
  5. **Stage 3 per-target hash and column-selector freeze across the four `#1047` resolution tiers (`P1c`):** Freeze parent coordinate model, parent MTZ, and ligand CIF SHA-256 digests (`parent_model_sha256`, `parent_mtz_sha256`, `parent_ligand_cif_sha256`) together with explicit `(obs_f, obs_sigf, free_flag, test_value, valid_flag_set)` bindings across all four `#1047` resolution tiers:
     - `Tier 1 — Ultra-High`: $d_{\min} < 1.10\text{ Å}$ (`< 1.10 Å`)
     - `Tier 2 — High`: $1.10\text{ Å} \le d_{\min} < 1.50\text{ Å}$ (`[1.10, 1.50) Å`)
     - `Tier 3 — Medium`: $1.50\text{ Å} \le d_{\min} < 2.80\text{ Å}$ (`[1.50, 2.80) Å`)
     - `Tier 4 — Low`: $d_{\min} \ge 2.80\text{ Å}$ (`>= 2.80 Å`)
- **Existing repository source facts (`scripts/t03_reflection_retention.py:25–35, 37–149`):**
  - `deposition_applicability` (`:25–35`) sets `deposited_reference: "available" | "unavailable"`, `refmac_reference: "available" | "unavailable"`, and `deposition_clause: "evaluable" | "unevaluable"`, ensuring `REFMAC` availability cannot substitute for a missing deposited $R_{\text{free}}$ reference.
  - `_column_bindings` (`:37–47`) requires three distinct explicit labels `(F, SIGF, flag)` with MTZ column types `["F", "Q", "I"]` (`:43–44`), requires selected `F` (`labels[0]`) and `SIGF` (`labels[1]`) to share `dataset_id` (`:45–46`), and records the selected flag column's (`labels[2]`) own `dataset_id` (`:41–47`) without requiring all three columns to share one `dataset_id` (`#1251`).
  - `_require_supported_mtz` (`:50–76`) enforces `VALM NAN` (`:54–56`), a single complete zero-batch `NCOL ncols nrows nbatches` record (`ncols >= 3`, `nrows > 0`, `nbatches == 0` at `:57–66`), and absence of unmerged `BATCH` header records or unmerged `M/ISYM`/`BATCH` column names or `Y`/`B` column types (`:67–76`).
  - `_rows` (`:78–86`), `_selection` (`:88–112`), and `audit_mtz_retention` (`:115–149`) require explicit integer `flag_values` (`len >= 2`) and `free_value in flag_values` (`:132–135`), reject usable finite-`F` / positive-finite-`SIGF` observations carrying malformed/invalid flags (`:96–108, 146–147`), and reject empty observed work or free sets (`:148–149`; `#1252`).
- **Stage boundary:** Policy is locked; actual candidate querying and the populated 48-target Stage 3 `held_out_target_and_dedup_manifest` remain unexecuted here.

---

### `U02` — Sequence and Structural-Fold Deduplication Rule and Lineage Artifact

- **Approved policy selection (`2026-11-15`):**
  1. **Disjointness against all 23 development exclusions and pairwise in-cohort:** Every held-out target must be disjoint against **all 23 excluded development structures** (`22` Round-2 sub-Å negative controls in `ref/research/data/negative_control_round2_enrolled.json::entries[].pdb_id` plus the separate identifier-level `1SAR` exclusion in `ref/research/data/refinement_assessment_1sar_and_controls_2026-10-18.json`; [`phenix_evaluation_preregistration_spec_2026-11-11.md`](phenix_evaluation_preregistration_spec_2026-11-11.md) §3, `#1247`) **and** pairwise disjoint within the held-out cohort under **BOTH** sequence and 3D structural-fold criteria:
  2. **Sequence deduplication (`MMseqs2` `< 30%` sequence identity):**
     - Primary bidirectional coverage screen: `--min-seq-id 0.30 -c 0.80 --cov-mode 0`
     - Domain-coverage guard: `--min-seq-id 0.30 -c 0.50 --cov-mode 1`
     - Scope: Evaluated over all polymer chains with length $\ge 25$ residues (`polymer len >= 25`).
  3. **Structural-fold deduplication (`US-align` exact all-vs-all `< 0.50`):**
     - Exact all-vs-all `US-align` comparison at **both chain level and domain level** enforcing $\max(\text{TM}_q, \text{TM}_t) < 0.50$.
  4. **Committed Stage 3 lineage receipt:** Commit `dedup_lineage.json` together with its SHA-256 digest (`dedup_lineage_sha256`) in the Stage 3 held-out intake bundle before any held-out refinement or evaluation.
- **Stage boundary:** Tool flags, polymer-length floor, and similarity cutoffs are locked; `dedup_lineage.json` is generated in Stage 3.

---

### `U03` — Sample Size $N$, Per-Tier Allocation, Holo/Metalloprotein Floor, and Prospective Decision Margins

- **Approved policy selection (`2026-11-15`):**
  1. **Sample size and balanced four-tier allocation:** Total held-out sample size **$N = 48$ targets**, allocated strictly as **`[12, 12, 12, 12]` per tier** across `Tier 1 (< 1.10 Å)`, `Tier 2 ([1.10, 1.50) Å)`, `Tier 3 ([1.50, 2.80) Å)`, and `Tier 4 (>= 2.80 Å)`.
  2. **Holo/metalloprotein representation floor:** At least **$\ge 4$ holo/metalloprotein targets per tier** (**$\ge 16$ total** across the $N = 48$ cohort) so every resolution tier contributes to the pre-frozen active-site/ligand/metal evaluation module (`D5a`, `U11`).
  3. **Prospective decision margins on paired contrast $\delta_{a,b,i}^{(e)} = \Delta_{a,i}^{(e)} - \Delta_{b,i}^{(e)}$ ($\Delta R_{\text{free}}$):**
     - **Non-inferiority (`NI`) margin:** **$+0.0030$** ($+0.30\text{ percentage points}$ in $R_{\text{free}}$).
     - **Equivalence margin:** **$[-0.0030, +0.0030]$** ($\pm 0.30\text{ percentage points}$ in $R_{\text{free}}$).
     - **Superiority criterion:** Requires **upper $97.5\%$ CI bound $< 0$** **AND** **point estimate $\le -0.0020$** ($-0.20\text{ percentage points}$ in $R_{\text{free}}$) **AND** **zero `T05` geometry regression**.
     - **Track (i) clean-null stability ("do-no-harm") criterion:** Requires **upper $97.5\%$ CI bound $\le +0.0015$** ($+0.15\text{ percentage points}$ in $R_{\text{free}}$).
- **Epistemic and registry caveats:**
  - Recording $N = 48$ (`[12, 12, 12, 12]`) and these prospective decision margins locks the study's pre-specified sample size and inference thresholds; it **does not claim that statistical power has been empirically demonstrated by the selected $N$ alone** prior to Stage 2 development-set variance characterization, and concrete inferential script implementation beyond the approved `U03` margins/criteria and `U08` Holm–Bonferroni ($\alpha = 0.05$ two-sided / $0.025$ NI) rules remains Stage 4 freeze work.
  - These prospective study margins apply strictly to comparative study inference under `#1048` / `#1047` and **do not create registry-bound pass verdicts** (`ref/structural_criteria.yaml:13–17` `pass_criterion_bindings: []` remains empty).

---

### `U04` — Per-Tier Fixed `.eff` Profiles (`Arm 3b`), Pruned Crossed Factorial Schedule, `ready_set` Hydrogen Isolation, and `S1`–`S4` Sensitivity Arms

- **Approved policy selection (`2026-11-15`):**
  1. **Macro-cycle budget and Stage 2 development-set profile freeze (`P5a`):**
     - Both `Arm 3b-refine-only` and `Arm 3b-plus-readyset` run for **`5` macro-cycles** (`main.number_of_macro_cycles = 5`), with concrete per-tier `.eff` templates frozen strictly on the **`23` development structures** (`22` Round-2 controls + `1SAR`) in Stage 2:
       - **`T1` ($< 1.10\text{ Å}$) & `T2` ($[1.10, 1.50)\text{ Å}$):** Macromolecular heavy-atom `ANISOU` (anisotropic ADPs), waters isotropic in $[0.90, 1.50)\text{ Å}$ and development-tested at $< 0.90\text{ Å}$ on the Stage 2 development set, `main.ordered_solvent = True`, riding hydrogens (`riding H`), `refinement.pdb_interpretation.restraints_library.cdl = True` (`#1238`), and `target_weights.optimize_xyz_weight = True` / `target_weights.optimize_adp_weight = True`.
       - **`T3` ($[1.50, 2.80)\text{ Å}$):** Isotropic ADPs + TLS (`iso+tls`), `main.ordered_solvent = True`, riding H, `refinement.pdb_interpretation.restraints_library.cdl = True`, and optimized XYZ/ADP weights (`optimize_xyz_weight = True`, `optimize_adp_weight = True`).
       - **`T4` ($\ge 2.80\text{ Å}$):** Isotropic/group ADPs + TLS (`iso/group+tls`), `main.ordered_solvent = False`, `torsion_ncs` + secondary-structure (`SS`) + `rotamer` restraints enabled, `refinement.pdb_interpretation.restraints_library.cdl = True`, and riding H.
  2. **Pruning of native no-op / demoted factorial cells (`16` cells in `T1`–`T3`, `8` cells in `T4`):**
     - **Drop `sol_on` at $d_{\min} \ge 2.80\text{ Å}$ (`T4`)** per `PHENIX_PREFIX/lib/python3.9/site-packages/phenix/refinement/task_table.py:118–124` (where `run_sol` requires strict `ordered_solvent.low_resolution > d_min`, default `2.8 > d_min`).
     - **Drop unrequested `aniso_macromol` at $d_{\min} > 1.50\text{ Å}$** per `PHENIX_PREFIX/lib/python3.9/site-packages/phenix/refinement/fsr/preprocess.py:395–396` (`assert_no_anisotropic_atoms_at_low_resolution` at `:394–417`, which converts unrequested anisotropic scatterers to isotropic when `d_min > main.switch_to_isotropic_high_res_limit`, default `1.5 Å`).
     - **Force weight optimization in `wt_opt` factorial cells:** Set `target_weights.force_optimize_weights = True` whenever `wt_opt` (`optimize_xyz_weight = True`, `optimize_adp_weight = True`) is scheduled, per `PHENIX_PREFIX/lib/python3.9/site-packages/phenix/refinement/xyz_reciprocal_space.py:452–464`, preventing the native skip predicate (`r_free < r_work or abs(r_free - r_work) < 0.01` when `not force_optimize_weights`) from turning `wt_opt` cells into silent no-ops.
     - **Resulting resolution-feasible crossed factorial cell counts ($\text{ready\_set H} \times \text{ordered\_solvent} \times \text{ADP/TLS mode} \times \text{optimize\_weights}$):** **`16` cells per target in `T1`–`T3`** ($2 \times 2 \times 2 \times 2$) and **`8` cells per target in `T4`** ($2 \times 1 \times 2 \times 2$ with `sol_on` pruned).
  3. **Hydrogen isolation contract in factorial `H_riding` (`#1240`):**
     - Isolate the hydrogen factor `H_riding` in the crossed factorial core by running `phenix.ready_set` with **`ready_set.actions.hydrogens = True` and `ready_set.actions.ligands = False`** (`PHENIX_PREFIX/lib/python3.9/site-packages/elbow/programs/ready_set_params.py:31–38, 79–101`; `#1240`) paired with **shared frozen ligand CIF restraints** across both `H_off` and `H_riding` cells.
     - The default combined `ready_set.actions.hydrogens = True, ready_set.actions.ligands = True` setting is reserved for **`Arm 3b-plus-readyset`**.
  4. **Four separate one-factor sensitivity arms (`S1`–`S4`, explicitly without interaction claims):**
     - **`S1`:** `1.5 Å` code default (`__init__.params:477`, `preprocess.py:395–396`) vs. `1.7 Å` FAQ (`phenix_html/rst_files/faqs/refine.txt:444–448`) `main.switch_to_isotropic_high_res_limit` evaluated on targets within $[1.50, 1.70]\text{ Å}$.
     - **`S2`:** `refinement.pdb_interpretation.restraints_library.cdl` `True` vs. `False` (`mmtbx/monomer_library/pdb_interpretation.py:151–160, 227, 578`; `#1238`).
     - **`S3`:** `refinement.pdb_interpretation.c_beta_restraints` (`True` vs. `False`) and `refinement.pdb_interpretation.nonbonded_weight` (`100` vs. `16`; `preprocess.py:162–174`).
     - **`S4`:** In Tier 4 (`T4`), `torsion_ncs`, secondary-structure (`SS`), and `rotamer` restraints turned off **one-by-one vs. all-on**.
     - **Dormant source block untouched:** The dormant `set_TLSplusADP_params` guard block at `PHENIX_PREFIX/lib/python3.9/site-packages/phenix/refinement/fsr/preprocess.py:483–508` (`#1220`) remains untouched.

---

### `U05` — Perturbation-Recovery Track (`Track (ii)`) Recipes, Deterministic Seeding, and Unpooled Separation

- **Approved policy selection (`2026-11-15`):**
  1. **Deterministic keyed PRNG seed and frozen starting models:** Track (ii) (`perturbation_recovery`) starting models are generated once per target using a deterministic seed derived via **`HMAC-SHA256("protstruct-track2-v1", anon_target_id)`** and frozen by SHA-256 digest before branching to any refinement arm.
  2. **Exact five-component perturbation operator sequence:**
     - Strip all crystallographic waters (`HOH` / `DOD`).
     - Strip all `ANISOU` records (converting atoms to isotropic B-factors).
     - Apply **$\pm 20\%$ log-normal isotropic B-factor jitter** clamped to **$[5, 150]\text{ Å}^2$**.
     - Apply coordinate perturbation **`sites.shake = 0.25 Å`** for $d_{\min} < 1.50\text{ Å}$ (`T1`–`T2`) and **`sites.shake = 0.35 Å`** for $d_{\min} \ge 1.50\text{ Å}$ (`T3`–`T4`).
     - Apply **$15^\circ$ RMS $\chi_1 / \chi_2$ torsion noise on $10\%$ of surface and binding-pocket sidechains**.
  3. **Strict unpooled separation (`D1`, `P3`):** Track (ii) perturbation-recovery outcomes are never pooled with Track (i) (`clean_null_stability`) or Track (iii) (`parameter_sensitivity`).

---

### `U06` — Co-Reported Reciprocal-Space Evaluators, Work-Fitted Linear-Bin Rescaling vs. Direct-Sum Companion, Mask Parameters, and `(H, K, L)` Equality

- **Approved policy selection (`2026-11-15`):**
  1. **Three co-reported reciprocal-space readouts (reported side-by-side without cross-tool averaging):**
     - **(1) `phenix.model_vs_data` (`T03` / `T06`):** Evaluated with `scattering_table = wk1995`.
     - **(2) `scripts/gemmi_rfactor.py:10–38` work-fitted linear-bin rescaled $R_{\text{work}}$ / $R_{\text{free}}$ / $R_{\text{sleep}}$:** Computed from `gemmi sfcalc` structure factors using `wk1995` scattering factors and bulk-solvent mask parameters **`r_probe = 1.1 Å`, `r_shrink = 0.9 Å`**, followed by `scripts/gemmi_rfactor.py`'s per-bin linear least-squares isotropic rescaling (`binwise_scale` at `:124–160`, `nbins = 20`) **fit strictly on active work `HKL`s** (`fit_mask = work_mask`, `#316`) and applied unchanged to `R_free` and `R_sleep`.
     - **(3) Raw `gemmi sfcalc --scale-to` companion diagnostic:** Direct summation of globally scaled `gemmi sfcalc --scale-to` `FC` values without the extra 20-bin post-hoc rescaling (`scripts/gemmi_rfactor.py:15–23, 35–38`).
  2. **Exact `(H, K, L)` set equality:** Enforce exact `(H, K, L)` reflection set equality across tools and across work, `R_free`, and `R_sleep` partitions.
- **Existing repository source facts and estimator-matching boundary (`scripts/gemmi_rfactor.py:10–38, 124–160`):**
  - In `scripts/gemmi_rfactor.py:124–160`, `binwise_scale` orders reflections by $s^2 = 1/d^2$ (`order = np.argsort(s2)` at `:148`) and partitions them via `np.array_split(order, nbins)` (`:149`) into **20 equal-count resolution bins** (referred to in `:17–18` as "linear reflection-count bins", explicitly documented at `:129–130` as *"Equal-count (not equal-width) bins"*), fitting a per-bin linear scale factor $s = \sum (F_{\text{obs}} F_{\text{calc}}) / \max(\sum F_{\text{calc}}^2, 10^{-12})$ strictly on `fit_mask` (`work_mask` at `:238`). This must **never** be misdescribed as equal-width resolution shells.
  - As documented in `scripts/gemmi_rfactor.py:15–23, 35–38`, only the directly summed `gemmi sfcalc --scale-to` `R-work` offset is benchmarked under registry §3; `scripts/gemmi_rfactor.py`'s bin-rescaled `R-work` and `R-free` offsets remain informational pending estimator-matched benchmarks, and `phenix.model_vs_data` and `gemmi` values must never be averaged.

---

### `U07` — Atom-Population Bijection, Altloc Rules, Dual `T05` Readout, Restraint Libraries, Symmetric `T16`, and Suspended `flip_conflict`

- **Approved policy selection (`2026-11-15`):**
  1. **Heavy-atom bijection and altloc rule (`T01`, `T02`, `T10`):** Compare non-hydrogen (`non-H`) heavy atoms keyed by **`(chain, resseq, icode, resname, atom_name)`**, selecting the **maximum-occupancy (`occ-max`) alternate conformer as primary** (with exact occupancy ties broken by `"A"`) paired with a **full-altloc audit** across all conformers.
  2. **Dual `T05` geometry readout (with `#798` / `#799` / `#790` non-equivalence boundary):**
     - Report **both** (a) standardized re-protonation via **Richardson `reduce 4.16.250520 -Nuclear -NOFLIP` + standalone `probe 2.26.021123`** **AND** (b) **`as-output` coordinates**.
     - Make **zero `#798` / `#799` cross-dictionary or changed-pipeline equivalence claims** (`ref/threshold_evidence_status.yaml:78–97`: `changed_pipeline` clashscore is `policy_state: not_evaluable`, `evidence_state: unmeasured`).
  3. **Co-reported covalent geometry restraint libraries (`ref/structural_criteria.yaml:485–505`):** Co-report **`phenix.model_statistics`** (covalent geometry scored against the Conformation-Dependent Library **`CDL`**) and **`gemmi rmsz`** (scored against the static CCP4 monomer library **`$CLIBD_MON`**) without conflating the two dictionaries.
  4. **Symmetric chain permutations and two-sided PISA BSA for `T16` (`ref/catalog.yaml:470–475, 1859–1869`):** On multimeric targets, evaluate **all sequence-equivalent symmetric chain permutations** for `T16`, justify the headline mapping independently of maximizing `T16_interface_dockq_score`, and report `T16_interface_buried_surface_area` as two-sided total BSA (**`2x PISA BSA`**, i.e., $2 \times \text{PISA }\texttt{interface\_area} = \sum\text{SASA}(\text{chains}) - \text{SASA}(\text{complex})$).
  5. **Suspended `flip_conflict` (`#809` / `#1236`):** `T14_asn_gln_his_flip_set_conflicts` (`flip_conflict`) remains **suspended** (`policy_state: suspended`, `evidence_state: producer_mismatch` in `ref/threshold_evidence_status.yaml:567–575`).

---

### `U08` — Staged Gate A / Gate B Contrast Hierarchy, Multiplicity, Clustered Bootstrap & Nonparametric Tests, Natural Cubic Spline, Worst-Rank Imputation, and 8-Code Status Vocabulary

- **Approved policy selection (`2026-11-15`):**
  1. **Staged two-gate contrast hierarchy (all 6 arms strictly unpooled):**
     - **Gate A (computational comparison):** `{Arm 1a, Arm 1b}` vs. `{Arm 3b-plus-readyset, Arm 3b-refine-only}`, with literal zero-override `{Arm 3a}` evaluated as secondary reference.
     - **Staged Gate B (agentic vs. qualified human):** `{Arm 1a, Arm 1b}` vs. `{Arm 2}` (staged per `D2a`).
     - All **6 arms** (`Arm 1a`, `Arm 1b`, `Arm 2`, `Arm 3a`, `Arm 3b-refine-only`, `Arm 3b-plus-readyset`) remain strictly unpooled.
  2. **Multiplicity adjustment:** **Holm–Bonferroni** step-down procedure controlling family-wise error rate at **$\alpha = 0.05$ two-sided / $0.025$ NI**.
  3. **Primary location estimator, clustered bootstrap CI, and nonparametric tests:**
     - **Tier-stratified, target-clustered** (`target` cluster in Gate A; `target × refiner` cluster in Gate B for `Arm 2`) **BCa bootstrap with `10,000` (`10k`) resamples** on the **Hodges–Lehmann pseudomedian**, reported alongside **full-denominator Wilcoxon signed-rank and Friedman tests**.
  4. **Continuous resolution spline model (`P1c`):** **Natural cubic spline** in $d_{\min}$ with knots at **`0.9`, `1.5`, `1.7` [FAQ-derived, `phenix_html/rst_files/faqs/refine.txt:444–448`], `2.8`, `3.0`, and `3.5 Å`**.
  5. **Full-denominator worst-rank assignment and tie-breaking (`D3c`):**
     - Over $K = K_{\text{valid}} + K_{\text{fail}}$ scheduled arms on a target, every failed or incommensurable run is assigned the **tied worst mid-rank**:
       $$\text{rank}_{\text{fail}} = K_{\text{valid}} + \frac{K_{\text{fail}} + 1}{2}$$
     - Valid runs with $|\Delta R_{\text{free},a} - \Delta R_{\text{free},b}| \le 10^{-6}$ (`ties <= 1e-6`) are assigned tied mid-ranks.
     - Ordinal ranks are **never treated as numerical $\Delta R_{\text{free}}$ values** and are always co-reported with explicit per-tier and per-arm completion rates.
  6. **Finite 8-code completion and failure/incommensurability status vocabulary:**
     1. `COMPLETED_COMMENSURABLE`
     2. `FAIL_PROCESS_CRASH_OR_NONZERO_EXIT`
     3. `FAIL_BUDGET_OR_WALLCLOCK_EXCEEDED`
     4. `FAIL_UNPARSABLE_OR_MISSING_ARTIFACT`
     5. `INCOMMENSURABLE_ARM3A_AUTODETECT_MISMATCH`
     6. `INCOMMENSURABLE_REFLECTION_DROP_OR_DOMAIN_CHANGE`
     7. `INCOMMENSURABLE_FREE_OR_SLEEP_FLAG_MUTATION`
     8. `INCOMMENSURABLE_ATOM_IDENTITY_OR_CELL_CORRUPTION`

---

### `U09` — Secondary Holdout `R_sleep` Partitioning, Pre-Branch MTZ Hygiene, `#1239` Hygiene-Matched Control, and `#1249` Custodian Enclave Isolation

- **Approved policy selection (`2026-11-15`):**
  1. **`R_sleep` sampling fraction, shell stratification, and keyed seed:** Partition **`5.0%` of active work `HKL`s** (with an absolute floor of **$\ge 50$ reflections**), stratified across **`20` equal-count resolution shells** using deterministic PRNG **`HMAC-SHA256("protstruct-rsleep-v1", parent_mtz_sha256)`**.
  2. **Physical removal from `common_analysis_derivative` MTZ:** Physically remove `R_sleep` reflection rows from the shared `common_analysis_derivative` MTZ before branching to any comparative arm (`Arm 1a`, `Arm 1b`, `Arm 2`, derivative `Arm 3a`, `Arm 3b-refine-only`, `Arm 3b-plus-readyset`), guaranteeing that `R_sleep` reflections cannot enter internal ML $\sigma_A$ estimation, bulk-solvent mask/scale fitting, or target-weight optimization during refinement.
  3. **Common pre-branch MTZ hygiene:** Strip Hendrickson–Lattman phase columns (`HLA`, `HLB`, `HLC`, `HLD`, which otherwise trigger `MLHL` target selection in `PHENIX`; `ref/research/negative_control_round5.md:54–60`, `ref/research/negative_control_round6.md:40–44`) and strip unselected observation arrays before branching.
  4. **`#1239` hygiene-matched pre-`R_sleep` control:** Record boolean `parent_already_hygienic` per target. Whenever `parent_already_hygienic` is `false`, define **`hygiene_matched_pre_rsleep_control`** (applying identical `HL*` and unselected-array stripping without removing `R_sleep` reflections) so that isolated `R_sleep`-withholding attribution is not confounded with `MLHL`-to-`ML` target changes (`#1239`).
  5. **`#1249` Custodian enclave isolation and post-trajectory execution lock:** Execute both the **unmodified parent-MTZ `Arm 3a` reference run** and **`hygiene_matched_pre_rsleep_control`** **ONLY inside the Custodian enclave and ONLY AFTER all comparative-arm trajectories are cryptographically locked** (`#1249`), preventing any pre-withholding reflection information from reaching comparative execution or candidate selection.

---

### `U10` — Deterministic Outer-Loop Candidate Selection, `T05` Guardrails, Tie-Breaking, and Early Stopping

- **Approved policy selection (`2026-11-15`):**
  1. **Holdout redaction / exclusion:** Redact and exclude both standard `R_free` and sealed `R_sleep` from the outer-loop candidate selector in multi-move agentic workflows (`Arm 1a`, `Arm 1b`).
  2. **Deterministic candidate selection over `COMPLETED_COMMENSURABLE` moves passing `T05` guardrails:** Among outer-loop moves with status `COMPLETED_COMMENSURABLE` that satisfy all four `T05` stereochemical guardrails relative to the starting model (`start`):
     - $\text{bond\_rmsz} \le \max(\text{start} + 0.15,\ 1.0)$
     - $\text{angle\_rmsz} \le \max(\text{start} + 0.20,\ 1.5)$
     - $\text{clashscore} \le \max(1.1 \times \text{start} + 1,\ 15)$
     - $\text{rama\_out} \le \max(\text{start} + 0.5\%,\ 1.0\%)$
     select **`argmin R_work`**.
  3. **Deterministic tie-breaking (`<= 5e-4`):** When candidate moves tie within $| \Delta R_{\text{work}} | \le 5 \times 10^{-4}$ (`5e-4`), break ties first by **`LLG_work`** (higher work-set log-likelihood gain) and second by **`MolProbity` composite score** (`T05_molprobity_composite`, lower is better).
  4. **Deterministic stopping rule:** Stop at the outer-loop budget cap (`U12`) or after **`2` consecutive moves** with **$\Delta R_{\text{work}} > -0.0005$ AND $\Delta \text{clashscore} \ge -0.5$**.
- **Registry boundary:** These `T05` guardrails govern internal outer-loop move selection only and do not create `pass_criterion_bindings` in `ref/structural_criteria.yaml:13–17`.

---

### `U11` — Stage 3 Pre-Frozen Active-Site, Ligand, and Metal Registry Specification (`D5a`)

- **Approved policy selection (`2026-11-15`):**
  1. **Pre-frozen Stage 3 site JSON scope:** For every holo and metalloprotein target, freeze a Stage 3 site registry JSON prior to any refinement run covering:
     - **Non-water ligands:** All non-water heterogens with **$\ge 6$ heavy atoms**, excluding crystallization buffer and cryoprotectant species unless annotated as catalytic.
     - **Metal ions:** All modelled metal sites, evaluated with the **`3.20 Å` inner-sphere cutoff** (`INNER_SPHERE_CUTOFF = 3.20`) and seven canonical element profiles (`Ca`, `Mg`, `Na`, `K`, `Zn`, `Mn`, `Fe`) in `scripts/checkmymetal_local.py:28–39` (`CANONICAL` element table at `:28–36`, `INNER_SPHERE_CUTOFF = 3.20` at `:38–39`, scoring helper `score` at `:69–78`).
  2. **Binding-pocket and receptor Kabsch superposition frame (`T10_rmsd_to_deposited_ligand_pose`):**
     - **`4.0 Å` binding pocket** around each target ligand/metal site.
     - **Kabsch superposition on backbone `N, CA, C` atoms** of receptor residues within **`10.0 Å` of the ligand centroid**, explicitly **excluding the ligand itself and flexible terminal tails**.
  3. **Map radii, symmetry expansion, local B-factor shell, and anomalous status:**
     - **`2mFo-DFc` / `mFo-DFc` atomic limiting radius** (`T10_ligand_rscc`, `T10_ligand_rsr`, `T06_residue_rscc`, `T05_per_residue_rsrz`): **`1.5 Å`** for $d_{\min} < 2.0\text{ Å}$ (`< 2.0 Å`) and **$0.75 \times d_{\min}$** for $d_{\min} \ge 2.0\text{ Å}$ (`>= 2.0 Å`).
     - **Crystallographic symmetry expansion (`symexp`):** **`5.0 Å`** cutoff around site atoms.
     - **Local B-factor neighbor shell (`T10_ligand_b_vs_surroundings`):** **`4.0 Å` occupancy-weighted non-hydrogen (`non-H`) neighbor B-factor shell**.
     - **Anomalous data status:** Explicitly recorded per target as **`"available"`** or **`"unavailable"`**.

---

### `U12` — Static `libtbx.langchain` Source Witness, Shared Dated LLM Snapshot Policy, Execution Budgets, and Fail-Closed Flag-Generation Guard

- **Committed static source witness (`ref/research/data/phenix_langchain_static_witness_2026-11-15.json`):**
  - Read-only byte and AST inspection of the **`44` Python source files** retained in the `files` array under `PHENIX_PREFIX/lib/python3.9/site-packages/libtbx/langchain/` in `PHENIX 2.0-5936` (without implying inspection of non-Python or bytecode/cache contents, and with zero vendor imports, zero binary execution, zero network/API calls, and portable `PHENIX_PREFIX` paths only) is committed in [`data/phenix_langchain_static_witness_2026-11-15.json`](data/phenix_langchain_static_witness_2026-11-15.json), pinning four selected source files and four bounded observations (`U12-W1` through `U12-W4`):
    1. **`U12-W1` (`PHENIX_PREFIX/lib/python3.9/site-packages/libtbx/langchain/core/llm.py:21–58, 60–136`, SHA-256 `dae8e47d81e3cb908daaecd43ef1df0a96a305e396bc29c91586c2677cef979d`, `182` lines):** The native factory accepts explicit `llm_model_name` and `temperature` (default `0.0`) arguments and defines source provider branches for **`ollama`**, **`google`**, and **`openai`** (raising `ValueError` for unsupported providers).
    2. **`U12-W2` (`PHENIX_PREFIX/lib/python3.9/site-packages/libtbx/langchain/core/llm.py:142–182`):** The expensive and cheap helper constructors choose **different named model defaults**; therefore, matching provider names or relying on helper defaults does **not** yield a shared pinned model snapshot.
    3. **`U12-W3` (`PHENIX_PREFIX/lib/python3.9/site-packages/libtbx/langchain/agent/planner.py:646–658, 1092–1125, 1340–1362`, SHA-256 `57af0c6b57a2a274e5d3e2ee00304c1bc561ae56c85b5b5536e0b63b8a03d65c`, `1,369` lines; `langchain_tools.py`, SHA-256 `6118edea8187b692fcfd77ec298fd30c8676355c23f09b26a8421313d7b9622c`, `135` lines):** The planner accepts injected `llm`, `cheap_llm`, and `command_llm` objects, generates the LLM primary command (`cmd_chain.invoke`), immediately constructs a mechanical backup command (`construct_command_mechanically`, `:78–100`) at `:1111–1118` and returns it in a separate field (`:1362`), and may still return invalid commands (`:1340–1342`).
    4. **`U12-W4` (`PHENIX_PREFIX/lib/python3.9/site-packages/libtbx/langchain/agent/planner.py:78–100, 1347–1351`; `PHENIX_PREFIX/lib/python3.9/site-packages/libtbx/langchain/validation/mtz_utils.py:47–60, 86–106`, SHA-256 `13daebc7cbab5a85c385d43e3e7a1d8dc78a48e215fb1e894bdec34c85549930`, `106` lines):** The mechanical refine path contains `r_free_flags.generate=True`, and `add_rfree_generation_if_needed` appends `xray_data.r_free_flags.generate=True` when MTZ flag inspection (`mtz_has_rfree_flags`) reports `False` (including on dump errors at `:58–60`).
- **Static-versus-runtime epistemic boundary:**
  - Static source inspection proves the existence of the `ollama` / `google` / `openai` factory branches, explicit `llm_model_name` and `temperature` forwarding, planner `llm` / `cheap_llm` / `command_llm` object injection, and differing expensive/cheap helper defaults. It proves **neither** runtime provider/package/credential availability **nor** any concrete dated model snapshot identifier (`selected_identifier: null`, `runtime_binding: "not_assessed"`, `availability: "not_assessed"` in [`data/phenix_langchain_static_witness_2026-11-15.json`](data/phenix_langchain_static_witness_2026-11-15.json)).
- **Approved policy selection (`2026-11-15`):**
  1. **ONE shared native-supported dated snapshot at Stage 2 freeze (`temperature = 0.0`):** Bind **ONE shared dated model snapshot** supported natively by `libtbx.langchain` across **BOTH `Arm 1a` and `Arm 1b`** and across all planner LLM subroles (`llm`, `cheap_llm`, `command_llm`) at **Stage 2 development freeze**, with **`temperature = 0.0`**. No snapshot identifier is invented here, and differing helper defaults are never treated as a shared pin. Concrete identifier, endpoint/provider, adapter/dependency hashes, prompt hashes, and effective-config bindings across all LLM subroles remain a mandatory Stage 2 freeze artifact.
  2. **Per-target execution budgets and Move 1 checkpoint:** Cap each target run at **`8` outer moves**, **`25` cumulative macro-cycles** (with **checkpoint Move 1 = `5` macro-cycles** matching `Arm 3b`), **`150k` (`150,000`) total tokens**, and **`2.0` wall-clock hours on `8` CPU threads**.
  3. **Primary vs. mechanical backup provenance (`#1222`, `V5`) and fail-closed flag guard:** Log `Arm 1b` LLM primary command vs. immediate mechanical backup command, actual executed command, and effective `.eff` on every move, and **fail closed on `r_free_flags.generate = True`** (rejecting any command or parameter block that requests R-free flag generation).

---

### `U13` — Qualified Adaptive Human Refiner Arm (`Arm 2`) Cohort, Overlap/Repeat Design, Tool Parity, and Staging

- **Approved policy selection (`2026-11-15`):**
  1. **Crystallographer cohort and qualification floor:** **$M = 3$ practicing macromolecular crystallographers**, each with **$\ge 3\text{ years}$** of crystallographic refinement experience and **$\ge 5$ deposited PDB structures**.
  2. **Target allocation, 3-rater overlap, and blinded intra-rater repeats:**
     - **`16` primary targets per crystallographer**.
     - **`12`-target (`3` per tier) 3-rater overlap subset** refined independently by all $M = 3$ crystallographers to estimate inter-rater variance.
     - **`4` blinded intra-rater repeats per refiner** to estimate within-refiner repeatability.
     - Concrete target-to-refiner and repeat allocation manifests remain Stage 3/4 freeze work.
  3. **Allowed tool surface and budget parity on the blinded derivative (`D4a`):**
     - Interactive building in **`Coot`** plus the **5-program `PHENIX 2.0-5936` toolkit** (`phenix.xtriage`, `phenix.ready_set`, `phenix.refine`, `phenix.ligandfit`, `phenix.pdbtools`), with **no external database, sequence/structure homolog, or AFDB searches**.
     - Capped at **`2.0` wall-clock hours** and **`25` cumulative macro-cycles** per target on the identical blinded `common_analysis_derivative` bundle.
  4. **Staged execution (`D2a`):** `Arm 2` remains staged (`D2a`) so computational arms need not wait for human cohort completion once Stage 1–4 freeze and explicit Stage 5/6 run authorizations are met (`wxGUI2` presets are never a human arm; `#1221`).

---

### `U14` — Stage 4 Synthetic-Verified Figure Schemas and Plotting Scripts (`D5b` + `P6`)

- **Approved policy selection (`2026-11-15`):**
  1. **1-to-1 Stage 4 schema and script binding:** In Stage 4 (prior to any trial execution), commit synthetic-data-verified declarative figure schemas and deterministic plotting scripts bound **1-to-1** to the **`4` `#1048` (`D5b`) figure families** and **`3` `#1047` (`P6`) figure families** (`7` figure families total, matching [`phenix_evaluation_protocol_design_2026-11-09.md`](phenix_evaluation_protocol_design_2026-11-09.md) §10 `D5b` and [`phenix_resolution_profile_decisions_2026-11-09.md`](phenix_resolution_profile_decisions_2026-11-09.md) §4 `P6`):
     - **`D5b` families (`#1048`):** (i) paired arm-contrast forest/raincloud plots of $\delta_{a,b,i}^{(e)}$ with `U03` margins and full failure denominators, (ii) clean-null (`Track (i)`) vs. perturbation-recovery (`Track (ii)`) trajectory panels, (iii) parameter-sensitivity (`Track (iii)`) crossed-factorial **main and interaction effect** plots plus **separately labeled one-factor sensitivity (`S1`–`S4`, without interaction claims)** plots across `#1047` tiers, and (iv) local active-site density/coordination comparison cards (`U11`).
     - **`P6` families (`#1047`):** (i) target $d_{\min}$ resolution distribution mapped against $(1.10, 1.50, 2.80\text{ Å})$ tier cutoffs, the six spline knots (`0.9, 1.5, 1.7 [FAQ], 2.8, 3.0, 3.5 Å`), and native PHENIX mechanism cutoffs, (ii) paired before/after multi-metric profile panels (`T03`, `T05`, `T06`, `T10`, `T01`, conditional `T16`) by tier with full failure denominators, and (iii) crossed-factorial **main and interaction effect** plus **separately labeled one-factor sensitivity (`S1`–`S4`, without interaction claims)** contrast plots across ADP/TLS, H, ordered solvent, and weight settings.
  2. **Mandatory visual invariants across all figure schemas (no figures generated here):** Enforce **full $N = 48$ scheduled denominators**, **stacked 8-code completion/failure bars (`U08`)**, **explicit spline knots (`0.9, 1.5, 1.7 [FAQ], 2.8, 3.0, 3.5 Å`)**, and **strictly separated crossed-factorial (`16` cells `T1`–`T3`, `8` cells `T4`) main and interaction effect panels vs. separately labeled one-factor sensitivity (`S1`–`S4`, without interaction claims) panels (`U04`)**. Zero figures are generated prior to separately authorized trials.

---

## 3. Summary Matrix: Policy Status vs. Remaining Stage 2–4 Artifacts

| Decision ID | Policy selection status (`2026-11-15`) | Key approved parameters & source anchors | Remaining executable/freeze artifact required before `frozen_result_free` (Stages 2–4) |
|---|---|---|---|
| **`U01`** | `SELECTED` (`selected_decisions_recorded`) | wwPDB/RCSB X-ray, single dataset, completeness $\ge 90\%$, standard polymer chains, `scripts/t03_reflection_retention.py:37–149`, $\ge 50$ free HKLs ($4.5\text{–}10.5\%$), $\ge 1{,}000$ work HKLs, missing header $R_{\text{free}} \to$ `deposition_clause="unevaluable"` (`:25–35`), 4 tiers (`<1.10`, `[1.10,1.50)`, `[1.50,2.80)`, `>=2.80 Å`) | Stage 3 `held_out_target_and_dedup_manifest` with 48 target SHA-256s and explicit `(obs_f, obs_sigf, free_flag, test_value, valid_flag_set)` bindings |
| **`U02`** | `SELECTED` (`selected_decisions_recorded`) | Disjoint vs. all 23 dev exclusions (`22` Round-2 controls + `1SAR`) & pairwise in-cohort via BOTH MMseqs2 (`<30%` seq-ID, `--min-seq-id 0.30 -c 0.80 --cov-mode 0` + domain guard `-c 0.50 --cov-mode 1`, polymer len $\ge 25$) AND exact all-vs-all US-align chain & domain $\max(\text{TM}_q,\text{TM}_t) < 0.50$ | Stage 3 committed `dedup_lineage.json` + SHA-256 digest |
| **`U03`** | `SELECTED` (`selected_decisions_recorded`) | $N = 48$ (`[12, 12, 12, 12]`), $\ge 4$ holo/metal per tier ($\ge 16$ total); NI $+0.0030$, equivalence $[-0.0030, +0.0030]$, superiority upper $97.5\%$ CI $< 0$ with point $\le -0.0020$ & zero `T05` regression, Track (i) clean-null upper $97.5\%$ CI $\le +0.0015$ | Stage 2 dev variance characterization; Stage 3 48-target enrollment verification (no power claim from $N$ alone; `pass_criterion_bindings: []` unchanged) |
| **`U04`** | `SELECTED` (`selected_decisions_recorded`) | `5` macro-cycles in `3b-refine-only` & `3b-plus-readyset`; prune `sol_on` at $\ge 2.80\text{ Å}$ (`task_table.py:118–124`) & unrequested `aniso_macromol` at $> 1.50\text{ Å}$ (`preprocess.py:395–396`); set `force_optimize_weights=True` in `wt_opt` (`xyz_reciprocal_space.py:452–464`) $\to$ `16` cells `T1`–`T3`, `8` cells `T4`; isolate factorial `H_riding` via `hydrogens=True, ligands=False` (`#1240`) + shared frozen ligand CIFs; `S1`–`S4` one-factor arms; dormant `preprocess.py:483–508` untouched | Stage 2 `dev_freeze_and_profile_bundle` locking per-tier `.eff` templates and factorial/sensitivity `.eff` generators on the 23 dev set |
| **`U05`** | `SELECTED` (`selected_decisions_recorded`) | `HMAC-SHA256("protstruct-track2-v1", anon_target_id)` seed; strip waters + strip `ANISOU` + $\pm 20\%$ log-normal iso-B jitter ($[5, 150]\text{ Å}^2$) + `sites.shake` `0.25 Å` ($<1.50$) / `0.35 Å` ($\ge 1.50$) + $15^\circ$ RMS $\chi_1/\chi_2$ noise on $10\%$ surface/pocket sidechains; unpooled from Track (i) | Stage 2 verified perturbation script; Stage 3 frozen perturbed starting-model SHA-256 manifests |
| **`U06`** | `SELECTED` (`selected_decisions_recorded`) | Co-report without averaging: (1) `phenix.model_vs_data` (`wk1995`), (2) `scripts/gemmi_rfactor.py:10–38` work-fitted equal-count linear-bin rescaled $R_{\text{free}}/R_{\text{sleep}}$ (`wk1995`, `r_probe=1.1`, `r_shrink=0.9 Å`, fit strictly on active work HKLs), (3) raw `gemmi sfcalc --scale-to` companion diagnostic; exact `(H,K,L)` equality | Stage 2/4 evaluator wrapper verification enforcing exact `(H,K,L)` set equality and dual `gemmi` reporting |
| **`U07`** | `SELECTED` (`selected_decisions_recorded`) | Non-H heavy atoms keyed by `(chain,resseq,icode,resname,atom_name)` (`occ-max` primary altloc, tie `"A"` + full-altloc audit); dual `T05` (`reduce 4.16.250520 -Nuclear -NOFLIP` + `probe 2.26.021123` AND `as-output`, no `#798`/`#799` equivalence claims); co-report `phenix.model_statistics` (`CDL`) & `gemmi rmsz` (`$CLIBD_MON`); all symmetric chain permutations for `T16` (`2x PISA BSA`); `flip_conflict` (`#809`/`#1236`) suspended | Stage 2/4 evaluation pipeline wiring for keyed heavy-atom bijection, dual `T05`, and symmetric `T16` permutation audit |
| **`U08`** | `SELECTED` (`selected_decisions_recorded`) | Gate A (`{1a,1b}` vs. `{3b+rs,3b-only}`, `3a` secondary) & staged Gate B (`{1a,1b}` vs. `Arm 2`), all 6 arms unpooled; Holm–Bonferroni ($\alpha=0.05$ 2-sided / $0.025$ NI); tier-stratified target-clustered (`target × refiner` for `Arm 2`) BCa bootstrap (`10k`) on Hodges–Lehmann pseudomedian + Wilcoxon/Friedman; natural cubic spline at `0.9, 1.5, 1.7[FAQ], 2.8, 3.0, 3.5 Å`; tied worst mid-rank $K_{\text{valid}}+(K_{\text{fail}}+1)/2$ (ties $\le 10^{-6}$); 8 status codes | Stage 4 pre-registered statistical analysis script verified on synthetic data |
| **`U09`** | `SELECTED` (`selected_decisions_recorded`) | `5.0%` active work HKLs ($\ge 50$), 20 equal-count shells via `HMAC-SHA256("protstruct-rsleep-v1", parent_mtz_sha256)`, physically removed from `common_analysis_derivative` MTZ; strip `HLA/HLB/HLC/HLD` & unselected obs arrays; `hygiene_matched_pre_rsleep_control` whenever `parent_already_hygienic` is `false` (`#1239`); run unmodified parent `Arm 3a` & pre-`R_sleep` controls ONLY in Custodian enclave AFTER comparative trajectories lock (`#1249`) | Stage 3 `input_derivative_and_rsleep_seal_manifest` with sealed `R_sleep` hashes, `parent_already_hygienic` flags, and Custodian enclave custody hashes |
| **`U10`** | `SELECTED` (`selected_decisions_recorded`) | Redact/exclude `R_free` & `R_sleep` from outer-loop selector; pick `argmin R_work` (tie $\le 5\times 10^{-4}$: `LLG_work` then `MolProbity`) among `COMPLETED_COMMENSURABLE` moves passing `T05` guardrails (`bond_rmsz<=max(start+0.15,1.0)`, `angle_rmsz<=max(start+0.20,1.5)`, `clashscore<=max(1.1*start+1,15)`, `rama_out<=max(start+0.5%,1.0%)`); stop at cap or 2 consecutive moves with $\Delta R_{\text{work}} > -0.0005$ & $\Delta \text{clashscore} \ge -0.5$ | Stage 2 controller selector/stopper implementation and holdout-redaction audit test |
| **`U11`** | `SELECTED` (`selected_decisions_recorded`) | Stage 3 frozen site JSON: non-water ligands ($\ge 6$ heavy atoms, excl. buffer/cryo unless catalytic) + metals (`3.20 Å` inner sphere per `scripts/checkmymetal_local.py:28–39`); `4.0 Å` pocket; Kabsch `N,CA,C` superposition within `10.0 Å` of ligand centroid (excl. ligand/tails); `2mFo-DFc`/`mFo-DFc` radius `1.5 Å` ($<2.0$) or $0.75\times d_{\min}$ ($\ge 2.0$); `5.0 Å` `symexp`; `4.0 Å` occ-weighted non-H neighbor B-shell; `"available"`/`"unavailable"` anomalous status | Stage 3 `active_site_prefreeze_registry` JSON files frozen across all enrolled holo/metalloprotein targets |
| **`U12`** | `SELECTED` (`selected_decisions_recorded`) | Static witness [`data/phenix_langchain_static_witness_2026-11-15.json`](data/phenix_langchain_static_witness_2026-11-15.json) (`44` Python source files); bind ONE shared native-supported dated snapshot across BOTH `Arm 1a` & `1b` (`llm`, `cheap_llm`, `command_llm`) at Stage 2 freeze (`temperature=0.0`); cap `8` outer moves, `25` macro-cycles (Move 1 checkpoint = `5` cycles), `150k` tokens, `2.0` wall-h (`8` CPU threads); log `1b` primary vs. mechanical backup (`#1222`); fail closed on `r_free_flags.generate=True` | Stage 2 concrete dated snapshot identifier, provider/endpoint & adapter/prompt/effective-config hashes across all LLM subroles, and fail-closed flag-generation guard verification |
| **`U13`** | `SELECTED` (`selected_decisions_recorded`) | $M = 3$ crystallographers ($\ge 3\text{ yr}$ & $\ge 5$ PDB structures), `16` primary targets each + `12`-target (`3`/tier) 3-rater overlap + `4` blinded intra-rater repeats/refiner; `Coot` + 5-program `PHENIX 2.0-5936` (no external DB/AFDB search), `2.0` wall-h & `25`-cycle cap on blinded derivative; staged (`D2a`) | Stage 3/4 blinded human-session packaging protocol and anonymized packet manifests |
| **`U14`** | `SELECTED` (`selected_decisions_recorded`) | Stage 4 synthetic-verified schemas/scripts bound 1-to-1 to the `4` `D5b` (`#1048`) + `3` `P6` (`#1047`) figure families with full $N = 48$ denominators, 8-code failure bars, spline knots, and separated crossed-factorial main and interaction effect panels vs. separately labeled `S1`–`S4` one-factor sensitivity panels (without interaction claims); zero figures generated here | Stage 4 declarative figure schemas and synthetic-verified plotting scripts |

---

## 4. Stage 2 Readiness and Sequential Artifact Checklist

Approval of `U01`–`U14` is complete at the **study policy level (`selected_decisions_recorded`)**, but **none of the Stage 2–4 executable or frozen study artifacts are executed by this PR**, and **future canary or benchmark trials still require separate explicit user authorization after Stage 4 lands on `main`**:

- [x] **Stage 1 — User policy selection (`U01`–`U14`) (`selected_decisions_recorded`, completed in this document):**
  - All fourteen `U01`–`U14` policy selections approved on `2026-11-15` and recorded above, with static `libtbx.langchain` source witness committed at [`data/phenix_langchain_static_witness_2026-11-15.json`](data/phenix_langchain_static_witness_2026-11-15.json) and `ref/structural_criteria.yaml:13–17` (`pass_criterion_bindings: []`) unchanged.
- [ ] **Stage 2 — Development-only profile, controller, snapshot, perturbation, and factorial freeze (`dev_freeze_and_profile_bundle`, pending):**
  - Lock concrete per-tier `.eff` templates for `Arm 3b-refine-only` and `Arm 3b-plus-readyset` (`5` macro-cycles; water ADP behavior at $< 0.90\text{ Å}$ tested strictly on the 23-structure development set; `U04`).
  - Lock executable `.eff` generators for the pruned crossed factorial schedule (`16` cells in `T1`–`T3`, `8` cells in `T4` with `force_optimize_weights = True` and `ready_set.actions.hydrogens = True, ligands = False` + shared frozen ligand CIFs) and the four one-factor sensitivity arms `S1`–`S4` (`U04`).
  - Pin the exact shared native-supported dated LLM snapshot identifier (`temperature = 0.0`), provider/endpoint configuration, adapter/dependency hashes, and prompt/effective-config hashes across all planner subroles (`llm`, `cheap_llm`, `command_llm`) for `Arm 1a` and `Arm 1b`, and verify the fail-closed `r_free_flags.generate = True` guard and outer-loop `U10` selector/stopper on the 23-structure development set (`U10`, `U12`).
  - Verify the deterministic `Track (ii)` perturbation operator (`HMAC-SHA256("protstruct-track2-v1", anon_target_id)`) on the development set (`U05`).
- [ ] **Stage 3 — Held-out target inventory, deduplication lineage, sealed `R_sleep` derivatives, and pre-frozen active-site registry (pending, result-free):**
  - Enroll $N = 48$ (`[12, 12, 12, 12]`, $\ge 4$ holo/metalloprotein per tier) held-out targets passing `U01` (`scripts/t03_reflection_retention.py:37–149`) and commit `dedup_lineage.json` proving `U02` (`MMseqs2` + `US-align`) disjointness against all 23 development exclusions and pairwise in-cohort.
  - Generate `common_analysis_derivative` MTZs (`HL*` and unselected-array stripping + physical removal of `5.0%` 20-shell stratified `R_sleep` work HKLs via `HMAC-SHA256("protstruct-rsleep-v1", parent_mtz_sha256)`), record `parent_already_hygienic` and `hygiene_matched_pre_rsleep_control` (`#1239`), and lock Custodian enclave custody for unmodified parent `Arm 3a` and pre-`R_sleep` controls (`#1249`, `U09`).
  - Freeze per-target active-site/ligand/metal JSONs (`U11`) and `Track (ii)` perturbed starting coordinate SHA-256 digests (`U05`) with zero held-out refinement runs.
- [ ] **Stage 4 — Result-free preregistration freeze (`registration_status: "frozen_result_free"`, pending):**
  - Commit the complete result-free preregistration bundle (`study_preregistration_manifest`) together with synthetic-data-verified `U08` statistical analysis scripts and `U14` figure schemas/plotting scripts (`4` `D5b` + `3` `P6` families), pass `uv run --locked --extra benchmark -- bash scripts/validate.sh` and independent review, and land on `main`.
  - **Hold on all `REFMAC5` follow-up until after PHENIX Stage 4 lands on `main`:** As documented in [`1sar_prospective_policy_selections_2026-11-15.md`](1sar_prospective_policy_selections_2026-11-15.md), both the offline `F3` CCP4 library check and any `1SAR` `Attempt 05` remain held until after PHENIX Stage 4 (`frozen_result_free`) is merged to `main`.
- [ ] **Stages 5 and 6 — Separately authorized canary and full benchmark campaign (blocked on Stage 4 + explicit user go-ahead):**
  - Require separate explicit user authorization after Stage 4 lands on `main`.
