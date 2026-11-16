# 1SAR / REFMAC5 Prospective Policy Selections (`SAR1`–`SAR6`) and Post-Stage-4 Execution Hold (`2026-11-15`)

**User approval date:** 2026-11-15
**Authored date:** 2026-11-15
**Policy status:** `prospective_policy_selected_execution_held` (historical Attempts 01–04 gates remain immutable; **all `REFMAC5` follow-up HELD until AFTER PHENIX Stage 4 `frozen_result_free` lands on `main`**)
**Base commit on `main`:** `28b6596c2ad6d88ab4e4bb0cc0f4cc32207a0156` (`28b6596`)
Historical source line numbers in this record refer to commit `28b6596c2ad6d88ab4e4bb0cc0f4cc32207a0156`, before the dated status pointers added in this change.
**Authoritative Step 1 approval handoff:** `.orchestration/handoffs/step1-user-approved-decisions-2026-11-15.md` (SHA-256 `a2bde2595d47840c714bb522771a4a81f96263009ab2d001bb5ec26c7a9ddfef`, approved `2026-11-15`)
**Retained scientific evidence & contract sources:** [`1sar_rerun_2026_11_12_scientific_decisions.md`](1sar_rerun_2026_11_12_scientific_decisions.md), [`1sar_rerun_2026_11_09_contract_assessment.md`](1sar_rerun_2026_11_09_contract_assessment.md) (`C`, SHA-256 `bec85a39d339aa28564e9f5825b2fabe8df5c4489eac94b84dfe46e2b0bbf681`), and [`1sar_rerun_2026_11_15_integration_review.md`](1sar_rerun_2026_11_15_integration_review.md)

---

## 1. Scope, Mandatory Post-PHENIX-Stage-4 Hold, and Historical Immutability Boundary

1. **Prospective policy record only (zero new measurements, zero code/gate mutations):**
   - On `2026-11-15`, the user approved the prospective policy selections `SAR1`–`SAR6` (`#1102`, `#1109`–`#1112`) resolving the six decision items presented in [`1sar_rerun_2026_11_12_scientific_decisions.md`](1sar_rerun_2026_11_12_scientific_decisions.md) §`Decisions to select next`.
   - This document records **prospective selected policy** for any future, separately authorized `1SAR` `Attempt 05`. It is **neither** an admission-gate implementation **nor** a new diagnostic or vendor-source assessment, and every numeric value cited below is either an explicit `2026-11-15` user policy selection or an already-committed historical fact from [`1sar_rerun_2026_11_12_scientific_decisions.md`](1sar_rerun_2026_11_12_scientific_decisions.md) and [`1sar_rerun_2026_11_09_contract_assessment.md`](1sar_rerun_2026_11_09_contract_assessment.md).

2. **Mandatory hold on ALL `REFMAC5` follow-up (including offline `F3` and `Attempt 05`) until AFTER PHENIX Stage 4 (`frozen_result_free`) lands on `main`:**
   - Per the `2026-11-15` user approval, **ALL `REFMAC5` follow-up is HELD until AFTER PHENIX Stage 4 (`registration_status: "frozen_result_free"`) lands on `main`**.
   - This hold explicitly covers:
     1. **The offline `F3` CCP4 library/source check** (inspecting exact-build-associated CCP4 library source for `LSTLSQ`/`LRCLOS` state conservation across `oppro_allocate.f:3924–3926` under `premise L`),
     2. **Any other offline `REFMAC5` diagnostic, library, or source follow-up**, and
     3. **Any `1SAR` `Attempt 05` instrumentation build, profile composition, or native `refmac5` execution**.
   - Although [`1sar_rerun_2026_11_12_scientific_decisions.md`](1sar_rerun_2026_11_12_scientific_decisions.md) (line 174) noted as an evidentiary possibility that exact-build-associated CCP4 library source could discharge `F3` (`premise L`) offline without another native run, **that offline possibility is NOT an exception to the `2026-11-15` hold**: no CCP4 library or vendor `REFMAC5` inspection is performed or authorized now.
   - Furthermore, **landing PHENIX Stage 4 (`frozen_result_free`) on `main` is only a prerequisite to lifting this hold**; executing `Attempt 05` still requires **separate explicit user execution approval**, a fresh evidence root, a distinct instrumented build/profile, and prospective preregistration.

3. **Immutability of historical `Attempts 01–04` and exact attribution of the `Attempt 04` gate vector:**
   - All `105` committed raw files across `data/coscientists/openscientist/retained_1sar_pr1007_R4_rfactors_attempt01` through `attempt04` (`84` files in Attempts 01–03 plus `21` files in Attempt 04 `R`), together with `X`, `A`, and `B`, remain byte-for-byte immutable. No historical receipt is reinterpreted as passing by these prospective selections.
   - In the retained **Attempt 04** operation manifest (`data/coscientists/openscientist/retained_1sar_pr1007_R4_rfactors_attempt04/refmac/refmac_operation_manifest.json`, alias `R/refmac/refmac_operation_manifest.json`, SHA-256 `f0a6736e37aa6d0594ec45864e2daf2ed7cc2aaadd6fe8bbc2b55268caf9c6bd`):
     - `preregistered_gates.gate_2_native_log_extraction_and_internal_reconciliation`: **`proven = true`** (limited strictly to native log extraction and internal reconciliation, with `xmlout_status = "supported_cycle_association_unproven"` preserved).
     - `preregistered_gates.gate_1_immutable_input_and_toolchain_admission` (`operational_immutability_and_profile_checks_verified = true`, `proven = false`), `preregistered_gates.gate_3_effective_hkls_proven` (`proven = false`), `preregistered_gates.gate_4_native_bin_membership_proven` (`proven = false`), `preregistered_gates.gate_5_native_residual_reconstruction_proven` (`proven = false`), and `preregistered_gates.gate_6_model_preservation_proven` (`proven = false`): all **`proven = false`**.
     - Top-level readiness and admission flags `all_preregistered_gates_passed`, `scientific_admission_proven`, `canary_admission_eligible`, `batch_execution_eligible`, `eval_admission_eligible`, `qds_admission_eligible`, and `canonical_eval_qds_eligible`: all **`false`**.
     - `diagnostic_producer.runtime_image_coverage` (and `B/index.json::runtime_image_coverage`): **`"not_assessed"`**.
   - This 6-gate vector (`Gate 2 = true`, `Gates 1, 3, 4, 5, 6 = false`) is the persisted state of **Attempt 04** (`R/refmac/refmac_operation_manifest.json`); earlier blocked receipts in `Attempts 01–03` retain their own historical failure receipts without having Attempt 04's manifest vector retrofitted onto them.

4. **Strict namespace separation from PHENIX `U01`–`U14` and empty `pass_criterion_bindings` (`CODING_STANDARDS.md` rule 13c):**
   - `SAR1`–`SAR6` are strictly separate from the PHENIX Step 1 policy selections `U01`–`U14` (`#1048` / `#1047`) recorded in the sibling note [`phenix_step1_user_selections_2026-11-15.md`](phenix_step1_user_selections_2026-11-15.md); there is **zero assumed `U`-to-`SAR` crosswalk**.
   - `ref/structural_criteria.yaml:13–17` (`pass_criterion_bindings: []`) remains empty and unchanged, and no `EVAL` or `QDS` records are emitted.

---

## 2. Approved Prospective `1SAR` / `REFMAC5` Policy Selections (`SAR1`–`SAR6`)

Repository-relative aliases below follow [`1sar_rerun_2026_11_12_scientific_decisions.md`](1sar_rerun_2026_11_12_scientific_decisions.md) and [`1sar_rerun_2026_11_09_contract_assessment.md`](1sar_rerun_2026_11_09_contract_assessment.md) (`C`):
- `R` = `data/coscientists/openscientist/retained_1sar_pr1007_R4_rfactors_attempt04`
- `X` = `data/coscientists/openscientist/retained_1sar_pr1007_R4_rfactors_attempt04_execution`
- `A` = `data/coscientists/openscientist/retained_1sar_pr1007_R4_rfactors_attempt04_analysis`
- `B` = `data/coscientists/openscientist/retained_evidence_2026-11-08_refmac-diagnostic-build633`
- `C` = [`ref/research/1sar_rerun_2026_11_09_contract_assessment.md`](1sar_rerun_2026_11_09_contract_assessment.md)

---

### `SAR1` — Additive-Hook `5.8.0431` Producer Scope and Runtime / Unhooked-Stock Parity Prerequisites (`Gate 1`)

- **Approved prospective policy (`2026-11-15`):**
  1. **Bounded claim scope (`native-accounting/trace claims only`):** An additive-hook instrumented build of `REFMAC 5.8.0431` may be admitted **solely for native-accounting and trace claims**—**never** as a claim of `"stock numerical equivalence"`.
  2. **Two mandatory prospective gates for any future `Attempt 05`:**
     - **(a) Bounded runtime `dyld` image inventory.**
     - **(b) Unhooked stock `5.8.0431` output-byte parity.** Exact inventory/parity schemas and comparator identity remain prospective preregistration details; they are not selected by this record.
- **Retained historical facts and boundaries (`1sar_rerun_2026_11_12_scientific_decisions.md` lines 29–38, 66, 176; `C` §3):**
  - In Attempt 04 (`R/refmac/refmac_operation_manifest.json::diagnostic_producer`), the instrumented binary (`profile_id = "refmac_5_8_0431_instrumented_attempt4_v1"`, `selected_executable.sha256 = "4f4c7045c73a9c2c725746b3d8ab73adbb98a2f6379b5493e9422d8da65db89b"`, `40,983,744` bytes) and the installed CCP4 `9.0.015` stock reference binary (`installed_reference.sha256 = "493f382202cdd6a62946d143c2a3fe675b346bef35b9b435ab008f7314bd48b4"`, `40,738,104` bytes) are distinct binaries (`distinct_from_installed_reference = true`), and `runtime_image_coverage` is `"not_assessed"`.
  - Neither the bounded runtime `dyld` inventory nor unhooked stock `5.8.0431` output-byte parity has been executed or measured; both remain prospective prerequisites for a separately authorized `Attempt 05` after the post-PHENIX-Stage-4 hold is lifted. Even when satisfied, they never authorize calling the hooked producer `"stock numerical equivalence"`. Attempt 04 `gate_1_immutable_input_and_toolchain_admission` remains `proven = false`.

---

### `SAR2` — Role-Aware MTZ Dataset Binding and Exact `7,248`-Row HKL Bijection (`#1102`, `Gate 3` Dataset Roles)

- **Approved prospective policy (`2026-11-15`):**
  1. **Role-aware MTZ dataset binding:** For prospective `Attempt 05` output admission under `#1102`, bind:
     - **Dataset `0` (`HKL_base`):** `H`, `K`, `L`, and `R-free-flags`.
     - **Dataset `1`:** `F-obs`, `SIGF-obs`, and all calculated structure-factor/phase/weight columns through `FOM` / map coefficients (`F..FOM`, i.e., `F-obs, SIGF-obs, FC..PHIC_ALL_LS`).
  2. **Exact `7,248`-row `(H, K, L)` bijection and crystallographic conservation:** Require an exact **`7,248`-row `(H, K, L)` bijection** between input `MTZIN` and output `HKLOUT`, together with **conservation of unit-cell dimensions (`dcell_tokens`), active dataset wavelength (`DWAVEL`), and free-flag partition assignments**.
  3. **Explicit non-excuse of `#1110`:** Adopting role-aware dataset binding under `SAR2` **does NOT excuse `#1110`** (the loss of exported `F-obs`/`SIGF-obs` values on the `11` finite zero-`F` work reflections or the `20` padding-flag rewrites).
- **Retained historical facts and boundaries (`1sar_rerun_2026_11_12_scientific_decisions.md` line 67; `C` §4.1):**
  - In Attempt 04, `R/inputs/projected_observations.mtz` (`NDIF 1`) assigns all `6` input columns (`H, K, L, F-obs, SIGF-obs, R-free-flags`) to `dataset_id = 1`, whereas `R/refmac/refmac_hklout.mtz` (`NDIF 2`, header start `492944`) assigns `H, K, L, R-free-flags` to `dataset_id = 0` (`DWAVEL 0.00000`) and `F-obs, SIGF-obs, FC..PHIC_ALL_LS` to `dataset_id = 1` (`DWAVEL 1.00000`), with shared `dcell_tokens = ["64.8970", "78.3230", "38.7920", "90.0000", "90.0000", "90.0000"]` (`rcard_tor1.f:7182–7185, 7249–7289`).
  - Historical Attempt 04 strict output rejection (`R/refmac/refmac_hklout_audit.json`) and `gate_3_effective_hkls_proven = false` remain unchanged.

---

### `SAR3` — Primary `7,228` Input-Eligible Denominator, Secondary `7,217` `refmac_native_positive_f_active` Estimand, `7,217 + 11 + 20` Ledger, and `HKLOUT` Reuse Ban (`#1110`, `Gate 3` Population)

- **Approved prospective policy (`2026-11-15`):**
  1. **Primary cross-tool denominator (`7,228` full input-eligible reflections):** Keep the full **`7,228` input-eligible reflection set (`6,505` work + `723` free)** as the **primary cross-tool denominator**. Never silently substitute the native positive-`F` subset (`7,217`) for the `7,228` input-eligible denominator.
  2. **Secondary native-active estimand (`refmac_native_positive_f_active`, `7,217` reflections) with full `7,217 + 11 + 20 = 7,248` accounting ledger:** Register **`refmac_native_positive_f_active` (`7,217 = 6,494` work + `723` free)** as a **distinct secondary estimand**, always co-reported with the exact three-part `7,248`-row accounting ledger:
     - **`7,217` active positive-`F` rows** (`6,494` work + `723` free, `SO > 0` in `LSQ_COEF`).
     - **`11` originally eligible finite zero-`F` work rows** (`F-obs = 00000000`, `SIGF-obs > 0`, `R-free-flags = 00000000` in `MTZIN`, overwritten with `ADATA(ISO) = -0.01` at `oppro_allocate.f:4274`, skipped at `subcf_scale1.f:136, 168`, and exported with `F-obs = SIGF-obs = fffa5a5a` `NaN` in `HKLOUT` at `oppro_allocate.f:5960–5961, 5999–6000, 6292–6294`).
     - **`20` all-`NaN` input padding rows** (`F-obs = SIGF-obs = R-free-flags = fffa5a5a` at 0-based `row_index = 7228..7247` in `R/inputs/input_hkl_ledger.json`, where `oppro_allocate.f:4350` sets `FREER(I) = -FREER(I)` = `-0.0` `80000000` and `oppro_allocate.f:6308` exports `ABS(FREER(IR))` = `+0.0` `00000000` while `F-obs`/`SIGF-obs` remain `fffa5a5a`).
  3. **Absolute ban on reusing `HKLOUT` as input `MTZ` (`MTZIN`):** Never reuse `refmac_hklout.mtz` (`HKLOUT`) as an input `MTZ` for any subsequent refinement or cross-tool evaluation.
- **Retained historical facts and boundaries (`1sar_rerun_2026_11_12_scientific_decisions.md` lines 68, 81–90; `C` §§4.2, 5.2):**
  - The `7,248` rows of `MTZIN` and `HKLOUT` (`7,217` active + `31` `SO <= 0` excluded = `7,217 + 11 + 20`) are distinct from the separate completeness loop (`refmac_completeness.f90:115–147`), which traverses **`7,262` generated-ASU rows** (`7,217` observed + `45` missing, where `45 = 31` shared `SO <= 0` input HKLs + `14` additional generated-ASU HKLs absent from the `7,248`-row input MTZ; `A/current/completeness_members.json`, `C` §5.2). Historical Attempt 04 `gate_3_effective_hkls_proven` remains `proven = false`.

---

### `SAR4` — Post-`SAR1`–`SAR3` Prerequisite Ordering and Native `J` + Binary32 `C0`/`L0` Bounds vs. `float64` $d^{*2}$ Cross-Tool Shells (`#1111`, `Gate 4`)

- **Approved prospective policy (`2026-11-15`):**
  1. **Prerequisite ordering (`post SAR1–SAR3`):** Shell-level reconciliation and admission under `SAR4` apply **only after `SAR1`, `SAR2`, and `SAR3` are satisfied**.
  2. **Native shell reconciliation (`native J + binary32 C0/L0 bounds`):** Reconcile native `REFMAC5` per-shell statistics using **captured native shell index `J`** and the **captured binary32 `C0` / `L0` boundary tables** (`SMINB(1..21)` and `SMAXB(1..21)` from `define_reso_bins_stats` at `oppro_allocate.f:4751–4759`; `C0` bounds retained in raw trace lines `3–23`; `A/current/native_bin_bounds.json` contains the `L0` bounds corresponding to raw trace lines `29097–29117`, with endpoint words `3C23EEAD` and `3E4CCC57` repeated in overall slot `21`). Never infer native shells from printed `Smean = 2.0*(SMINB(J)**2 + SMAXB(J)**2)` log tokens (`subag_scale_hessian.f:339–349`) or midpoint formulas.
  3. **Cross-tool shell evaluation (`float64 d*^2 on MTZIN`):** Define cross-tool resolution shells using **independent IEEE `float64` $d^{*2}$ computed directly on `MTZIN`** (`projected_observations.mtz`), without claiming floating-point arithmetic equivalence between independent `float64` $d^{*2}$ and `REFMAC5`'s internal binary32 `define_res` (`refmac_completeness.f90:115–147`) or `LSTLSQ` (`subcf_scale1.f:105–107`).
- **Retained historical facts and boundaries (`1sar_rerun_2026_11_12_scientific_decisions.md` lines 69, 92–96; `C` §5):**
  - In Attempt 04, all `7,217` active `(HKL, IFREE, J)` tuples match 1:1 between `LSQ_COEF` and observed completeness (`6,494` work, `723` free) and all `7,248` shared HKLs have identical matched `J`, while `2,939` shared HKLs differ in binary32 `RHO` between `define_res` and `LSTLSQ` (`0` shell changes). Historical Attempt 04 `gate_4_native_bin_membership_proven` remains `proven = false`.

---

### `SAR5` — Distinct Schema Keys for Four $R$-Factor Quantities and Required `F1` Partial + `F2`–`F4` Witnesses (`#1109`, `Gate 5`)

- **Approved prospective policy (`2026-11-15`):**
  1. **Four distinct schema keys without tolerance tuning:** Maintain separate, non-interchangeable schema keys for each of the four retained `REFMAC5` $R$-factor representations—with **zero tolerance tuning, zero post-hoc scale fitting, and zero representation collapsing**:
     - **(1) Binary32 final carriers** (`RFACTOR_WORK` / `RFACTOR_FREE` at `subcf_scale1.f:384, 392`; in Attempt 04: `3E2D5A39` = `11360825/67108864` = `0.16928948462009429931640625` work and `3E59E4E1` = `14279905/67108864` = `0.21278716623783111572265625` free; `A/current/result.json::native_carriers`).
     - **(2) Printed log and XML tokens** (`R/refmac/refmac.log:1171–1172, 1200`: `0.1693` work / `0.2128` free; `R/refmac/refmac_xmlout.xml:19`: `0.169` work / `0.213` free).
     - **(3) Exact `S0` captured-operand rational sums** ($\sum |\text{YOS}_i - \text{YC\_ALL}_i| / \sum \text{YOS}_i$ over the `7,217` `S0` records; in Attempt 04: `1147753088519/6779817333088` = `0.1692896773070187536...` work and `155910436577/732706205892` = `0.2127871107454233955...` free; `C` §6.2).
     - **(4) Exported `HKLOUT` post-`APPLYSCALES` column ratios** ($\sum |F_{\text{out},i} - \text{FC\_ALL\_LS}_{\text{out},i}| / \sum F_{\text{out},i}$, reflecting per-HKL division by `EXPAN` across `7,207` distinct captured binary32 `EXPAN` words; in Attempt 04: `1147828313894/6771678021525` = `0.1695042661871135441...` work and `38960352489/182802227126` = `0.2131284344919157755...` free; `C` §6.2).
  2. **Require `F1` partial `YC`/`PHI`, `F2`, `F3`, and `F4` witnesses:**
     - **`F1` partial `YC`/`PHI`:** Main-slot `YC0`/`PHI0` is already captured in `S0` (`sumsfs_ls_deriv_row`, first at raw trace line `29120`), and the `F1` caller edge (`RESIDVAL -> REFALL -> REFALL1/REF_ALL -> PROPI -> LSQ_COEF`), `P1` scalar reaching definitions, and `P2` cycle-slot ancestry (`NCYCLE_OVERALL = 1`) are closed at the static vendor-source level (`1sar_rerun_2026_11_12_scientific_decisions.md:124–133, 172`, `C` §6.3). Prospectively require occurrence-bound capture or complete state proof of the **remaining partial `YC`/`PHI` (`FC`/`phase`) array state** (`ls_scaling_double.f:514` onward).
     - **`F2` (`APPLYSCALES`):** Bind per-HKL `RSQ` and recomputed `EXPAN` to pre/post `FO`/`SIGO`, main `FC` store (`fc(ipos,1)`), and partial `FC` stores inside `APPLYSCALES` (`ml_scaling_double.f:4345–4403`).
     - **`F3` (`premise L` / post-`APPLYSCALES` `ML1CF`):** Require proof of `premise L` (equivalence of `LSTLSQ` resolution metric/result and geometry state across `ML` initialization, `LSQ` evaluation, and `ML1CF`, including across `LRCLOS(MTZIN)` at `oppro_allocate.f:3924–3926`) via exact-build-associated CCP4 library source or occurrence-bound runtime witness. **Explicit hold rule:** The existence of an offline CCP4 library-source route for `F3` (`1sar_rerun_2026_11_12_scientific_decisions.md:174`) is **NOT** an exception to the user's `2026-11-15` hold; **offline `F3` inspection is HELD until AFTER PHENIX Stage 4 (`frozen_result_free`) lands on `main`**.
     - **`F4` (`MTZWRITE` exporter-to-bytes):** Bind `EXTRACT_ABS` outputs (`A_CALCS`, `B_CALCS`), `a_all_ls`/`b_all_ls` accumulation and square-root storage (`FC_ALL_LS`), `LIND` row permutation order, and pre-`LWREFL` `BDATA` words to the final `HKLOUT` binary32 words (`oppro_allocate.f:6049, 6076–6077, 6089–6090, 6118–6119, 6338, 6646, 6650`; a final `BDATA` snapshot alone closes only the last export edge).
- **Retained historical boundary:** Historical Attempt 04 `gate_5_native_residual_reconstruction_proven` remains `proven = false` (and `gate_2` `xmlout_status = "supported_cycle_association_unproven"` remains unchanged).

---

### `SAR6` — Two-Tier Model Preservation Policy: `Tier 6A` Keyed `1,641`-Heavy-Atom Equivalence vs. Settled `Tier 6B` `#1104` `MAKE HYDR All` / `HOUT No` (`#1112`, `#1104`, `Gate 6`)

- **Approved prospective policy (`2026-11-15`):**
  1. **`Tier 6A` — Keyed heavy-atom equivalence across `1,641` heavy atoms with logged canonicalizations (`#1112`):**
     - Require exact keyed heavy-atom bijection and zero coordinate, occupancy, or B-factor differences across all **`1,641` heavy atoms** (`coordinate_difference_count = 0`, `occupancy_difference_count = 0`, `b_factor_difference_count = 0`), with explicitly logged canonicalizations restricted to:
       1. **`SO4 A 97` intra-residue atom order:** `O1, O2, O3, O4, S` (`R/inputs/original_model.pdb:863–867`) $\to$ `S, O1, O2, O3, O4` (`R/refmac/refmac_xyzout.pdb:859–863`, `R/refmac/refmac_xyzout.mmcif:1775–1779`; 0-based heavy-atom `order_index = 744..748`).
       2. **`SO4 A 97` record class (`ATOM -> HETATM`):** `5` sulfate atom records normalized from `ATOM` to `HETATM` (`make_CIF.f:8676–8700`, `record_type_difference_count = 5`).
       3. **Ion element-symbol case (`Ca -> CA`, `Na -> NA`):** `2` ion records on `CA A 98` and `NA B 98` uppercased from `"Ca"` / `"Na"` to `"CA"` / `"NA"` (`make_subr.f:1342–1377`, `element_difference_count = 2`).
       4. **Atom serial renumbering (`serials`):** Logged atom serial renumbering (`877` serial differences in `A/raw-side-effects.json::model.field_differences.serial.count`).
       5. **Formal charge text canonicalization (`2+ -> +2`):** Logged charge string reordering `2+ -> +2` (observed on `CA A 98`).
     - **Distinction between literal approved `2+ -> +2` and retained `1+ -> +1` observation (no silent policy widening):**
       - In the retained Attempt 04 evidence (`R/refmac/refmac_xyzout_audit.json::comparison`, `A/raw-side-effects.json::model.field_differences`, [`1sar_rerun_2026_11_12_scientific_decisions.md`](1sar_rerun_2026_11_12_scientific_decisions.md) lines 110–115, and `C` §7.1), the three Attempt 04 `gate_6` blockers in `scripts/onesar_refmac.py:8883–8940` are `SO4 A 97` atom order, the `5` `SO4 A 97` `ATOM -> HETATM` changes, and the `2` `"Ca"/"Na" -> "CA"/"NA"` element-case changes, whereas the `877` `serial` changes, `0` `segment` changes, and **`2` charge-text reorderings (`"2+" -> "+2"` on `CA A 98` and `"1+" -> "+1"` on `NA B 98`)** are separate non-gating field observations.
       - Because the `2026-11-15` user approval literally names **`2+ -> +2`**, this record preserves the exact literal selection `2+ -> +2` while explicitly noting that retained Attempt 04 evidence also contains `1+ -> +1` on `NA B 98`. No unselected transformation may be silently added, and any future `Attempt 05` validator implementation must **not** broaden charge canonicalization beyond `2+ -> +2` (e.g., to `1+ -> +1` or arbitrary charge strings) without an explicit rule clarification.
       - Keyed heavy-atom coordinate equivalence does not by itself prove internal prepared-state chemistry or active scatterer equivalence.
  2. **`Tier 6B` — `#1104` `MAKE HYDR All` / `MAKE HOUT No` separate and settled:**
     - Governed by `ref/research/1sar_rerun_2026_11_07_hydrogen_policy.json` (`decision = "keep_defaults_disclose"`, `user_decision_text = "Keep defaults, disclose"`), `Tier 6B` remains separate from `Tier 6A` and settled: under native `MAKE HYDR All` and `MAKE HOUT No`, riding hydrogens are generated internally and contribute to structure factors while `R/refmac/refmac_xyzout.pdb` contains `1,641` heavy-atom coordinate records (`0` `H`, `0` `D`) and sibling `R/refmac/refmac_xyzout.mmcif` contains `3,035` `_atom_site` rows (`1,641` heavy atoms, `1,394` `H`, `0` `D`). Neither coordinate file establishes the internal active structure-factor scatterer census during `NCYC 0` evaluation, and `#1104` remains open for downstream slide/report disclosure.

---

## 3. Summary Table of Prospective `SAR1`–`SAR6` Selections and Hold Posture

| ID & issue / gate | Approved prospective policy (`2026-11-15`) | Retained Attempt 04 evidence & caveats preserved | Current execution & gate status |
|---|---|---|---|
| **`SAR1`**<br>Producer / `Gate 1` | Admit additive-hook `5.8.0431` for **native-accounting/trace claims only** (never `"stock numerical equivalence"`), gated on **(a) bounded runtime `dyld` image inventory** + **(b) unhooked stock `5.8.0431` output-byte parity**. | Instrumented (`4f4c7045..`) vs. stock CCP4 `9.0.015` (`493f3822..`) are distinct; Attempt 04 `runtime_image_coverage = "not_assessed"`. Parity & `dyld` inventory are prospective prerequisites, not measured Attempt 04 facts. | **HELD** until after PHENIX Stage 4 (`frozen_result_free`) lands on `main` + separate `Attempt 05` approval; Attempt 04 `gate_1 = false`. |
| **`SAR2`**<br>`#1102` / `Gate 3` (datasets) | Role-aware MTZ binding: **`H, K, L, R-free-flags` in dataset `0`**, **`F..FOM` (`F-obs, SIGF-obs, FC..PHIC_ALL_LS`) in dataset `1`**, with exact **`7,248`-row `(H, K, L)` bijection** + cell/wavelength/flag conservation; **does NOT excuse `#1110`**. | Attempt 04 `projected_observations.mtz` has all `6` cols in dataset `1`; `refmac_hklout.mtz` splits `H,K,L,R-free-flags` (dataset `0`) vs. `F-obs..PHIC_ALL_LS` (dataset `1`). | **HELD** until after PHENIX Stage 4 lands on `main`; Attempt 04 `gate_3 = false`. |
| **`SAR3`**<br>`#1110` / `Gate 3` (population) | Keep **`7,228` (`6,505` work + `723` free) full input-eligible primary cross-tool denominator** + secondary **`refmac_native_positive_f_active` (`7,217 = 6,494 + 723`)** estimand with **`7,217 + 11` zero-`F` (`fffa5a5a`) + `20` padding (`80000000 -> 00000000`) = `7,248` ledger**; **never reuse `HKLOUT` as input `MTZ`**. | Separate completeness loop has `7,262` generated-ASU rows (`7,217` observed + `45 = 31 + 14` missing), not `7,262` `HKLOUT` rows. No denominator substitution or imputation. | **HELD** until after PHENIX Stage 4 lands on `main`; Attempt 04 `gate_3 = false`. |
| **`SAR4`**<br>`#1111` / `Gate 4` (shells) | **Post `SAR1`–`SAR3`:** Use **captured native `J` + binary32 `C0`/`L0` bounds** (`3C23EEAD`..`3E4CCC57`, slot `21` repeats endpoints) for native shell reconciliation vs. **independent `float64` $d^{*2}$ on `MTZIN`** for cross-tool shells (no midpoint/inferred bins or unproved FP equivalence). | Attempt 04 has `7,217` 1:1 active `(HKL,IFREE,J)` matches, `7,248` shared `J` matches, and `2,939` `RHO` word differences (`0` shell crossings). | **HELD** until after PHENIX Stage 4 lands on `main`; Attempt 04 `gate_4 = false`. |
| **`SAR5`**<br>`#1109` / `Gate 5` (residuals) | Keep **distinct schema keys** for (1) binary32 carriers (`3E2D5A39`/`3E59E4E1`), (2) log/XML tokens (`0.1693`/`0.2128`, `0.169`/`0.213`), (3) exact `S0` sums (`1147753088519/6779817333088`, `155910436577/732706205892`), and (4) `HKLOUT` `APPLYSCALES` ratios (`1147828313894/6771678021525`, `38960352489/182802227126`) without tolerance tuning; **require `F1` partial `YC`/`PHI`, `F2`, `F3`, and `F4`**. | `F1` caller, `P1`, and `P2` are closed at source level; main-slot `YC0`/`PHI0` is already in `S0`. **Offline `F3` CCP4 library check is explicitly HELD** along with `Attempt 05` until after PHENIX Stage 4 lands on `main`. | **HELD** (both offline `F3` and `Attempt 05`) until after PHENIX Stage 4 lands on `main`; Attempt 04 `gate_5 = false`. |
| **`SAR6`**<br>`#1112` & `#1104` / `Gate 6` (model) | **`Tier 6A`:** Keyed heavy-atom equivalence across **`1,641` heavy atoms** (`0` coord/occ/B diffs) with logged canonicalizations for `SO4 A 97` order (`O1..O4,S -> S,O1..O4`), `5` `SO4` `ATOM -> HETATM`, `2` `Ca -> CA` / `Na -> NA`, `877` `serials`, and literal `2+ -> +2` (distinguished from retained `1+ -> +1` observation on `NA B 98`; no silent widening).<br>**`Tier 6B` (`#1104`):** `MAKE HYDR All` / `HOUT No` separate & settled (`refmac_xyzout.pdb` `0` `H` vs. `refmac_xyzout.mmcif` `1,394` `H`; neither is an internal active-scatterer census). | Attempt 04 `gate_6` blockers are `SO4 A 97` order, `5` `SO4` `ATOM -> HETATM`, and `2` `"Ca"/"Na" -> "CA"/"NA"`; `877` `serial` and `2` `charge` (`2+ -> +2`, `1+ -> +1`) are separate field observations. | **HELD** until after PHENIX Stage 4 lands on `main`; Attempt 04 `gate_6 = false`; `#1104` open for downstream slide/report disclosure. |
