# 1SAR Attempt 04: verified offline evidence and decisions still required

This assessment is result-free with respect to new native execution. It selects no
scientific policy and changes no historical evidence. Offline consistency is not an
eligible canary: the retained manifest's limited Gate 2 remains true, while Gates
1, 3, 4, 5 and 6 remain false. Its `scientific_admission_proven`,
`canary_admission_eligible`, `batch_execution_eligible`, `eval_admission_eligible`
and `qds_admission_eligible` fields remain false. The Gate 2 receipt still says
`xmlout_status: supported_cycle_association_unproven`; later source analysis does
not rewrite that receipt. Source: `R/refmac/refmac_operation_manifest.json`.

## Evidence identity and scope

The following repository-relative aliases identify committed evidence:

- `R`: `data/coscientists/openscientist/retained_1sar_pr1007_R4_rfactors_attempt04`.
- `X`: `data/coscientists/openscientist/retained_1sar_pr1007_R4_rfactors_attempt04_execution`.
- `A`: `data/coscientists/openscientist/retained_1sar_pr1007_R4_rfactors_attempt04_analysis`.
- `B`: `data/coscientists/openscientist/retained_evidence_2026-11-08_refmac-diagnostic-build633`.
- `C`: `ref/research/1sar_rerun_2026_11_09_contract_assessment.md`.

This assessment starts from `eafe7d8b6e1352b233c8856a8bd81faa99396a4b`.
`X/index.json::execution_code_commit` identifies the native execution as
`75c0442c51a1bd679a54bc268334b8378af3a5dd`. Vendor file:line references below mean
the unmodified REFMAC tag `5.8.0431`, commit
`be25e793829952f4f177d7dfd0c10a1eb6bbd180`, identified by
`B/source/refmac_diagnostic_source_manifest.json::upstream_source`.

`B/profile/diagnostic-profile.json::profile_id` and
`R/refmac/refmac_operation_manifest.json::diagnostic_producer.profile_id` identify
`refmac_5_8_0431_instrumented_attempt4_v1`. The manifest's
`diagnostic_producer.selected_executable.sha256` is
`4f4c7045c73a9c2c725746b3d8ab73adbb98a2f6379b5493e9422d8da65db89b`;
`diagnostic_producer.installed_reference.sha256` is
`493f382202cdd6a62946d143c2a3fe675b346bef35b9b435ab008f7314bd48b4`.
These are distinct producers. Verified build/profile/disk identities do not prove
stock numerical equivalence or runtime memory identity:
`diagnostic_producer.runtime_image_coverage` remains `not_assessed`.

| Authoritative artifact | SHA-256 |
| --- | --- |
| `R/refmac/refmac_native_trace.jsonl` | `4dd312bf512d32cdf4095f1e3ee0c5471cb2ad91deb602b2c60d4f210216505d` |
| `R/refmac/refmac_operation_manifest.json` | `f0a6736e37aa6d0594ec45864e2daf2ed7cc2aaadd6fe8bbc2b55268caf9c6bd` |
| `R/inputs/input_hkl_ledger.json` | `35543c5821665de8f65b5fbd153669556dfef766ac8b156dc001a0c5b667a51e` |
| `R/refmac/refmac_hklout.mtz` | `e21ce039b11e8b83c5deebfa3059fafeef7906cf1d10a1d3cf20b57f56b578e2` |
| `R/refmac/refmac_xyzout.pdb` | `1c495e84880beb4b85bebd9f33095c4fed519a3cfaed9d8f76427f7784111ee6` |
| `B/index.json` | `da109f1edd0259b41dd8ebf3e2cdd6050c155034981346aae8093b54a442d2bf` |
| `B/source/refmac_diagnostic_source_manifest.json` | `7ce2ed76d5a7bbd0a156015301c8eb7af4dd1a33934c51754d9dccab21036b51` |
| `C` | `bec85a39d339aa28564e9f5825b2fabe8df5c4489eac94b84dfe46e2b0bbf681` |

## What the retained evidence establishes

The trace has 94,281 numbered events plus its header and writer-close footer:
94,283 physical records. This distinction is visible in the first/final raw
records and `A/current/result.json::event_counts`. The fixed-fixture checker in
`scripts/check_onesar_attempt04_membership.py` binds eleven retained file hashes,
projects complete saved member/slot records from those trace bytes, checks all
17 HKLOUT column words per row, and joins captured HKLs across namespaces.
Its successful diagnostic result explicitly leaves `scientific_admission`,
`batch_eligible`, `effective_hkls_proven` and `native_bin_membership_proven` false.
The membership and contract-replay test modules exercise these bounded checks;
they do not constitute a complete native grammar or a new admission route.

| Issue / gate | Established facts | Boundary still open |
| --- | --- | --- |
| Producer / Gate 1 | The manifest distinguishes the instrumented binary/profile from stock and records verified operational checks. | Admission of that distinct producer and a defined runtime-image claim are not supplied by disk hashes. |
| #1102 / Gate 3 | Original/projected selected input columns carry dataset 1. HKLOUT assigns H/K/L/free flags to dataset 0 and observed/calculated columns to dataset 1. | The strict output audit rejects this split. Role-aware admission is unselected, and native library dataset-table state was not captured. |
| #1110 / Gate 3 | Input and HKLOUT each have 7,248 rows. Input eligibility is 7,228 = 6,505 work + 723 free, including 11 zero-F work rows; 20 other rows are unassigned padding. Native residual inclusion is 7,217 = 6,494 work + 723 free. | The 11 originally eligible zero-F rows lose their exported F/SIGF values. A native-active population cannot silently replace the original input denominator. |
| #1111 / Gate 4 | Captured J and binary32 bounds cover 20 shells plus overall slot 21. All 7,248 shared HKLs, including exclusions, have matching captured J in the residual/completeness namespaces. | These observations do not establish producer/population admission or native floating-point equivalence with an independent resolution calculation. |
| #1109 / Gate 5 | Native carriers, exact captured-operand sums, printed tokens and exported-column residuals are distinct retained quantities. Source-level caller/scalar/cycle ancestry is established on the ordinary NCYC 0 path. | Partial-array and export ancestry still have the finite gaps below; diagnostic consistency is not an admitted R reconstruction. |
| #1112 / Gate 6 | Both PDBs contain 1,641 heavy-atom keys with no keyed coordinate/occupancy/B differences. The three gate causes are sulfate A97 order, five sulfate ATOM-to-HETATM changes and two ion element-case changes. | Output-representation policy is unselected; keyed coordinate agreement does not independently prove prepared-state chemistry/scatterer equivalence. |

Sources for the table: `R/inputs/input_hkl_ledger.json::counts`,
`R/refmac/refmac_hklout_audit.json::{errors,output_layout_summary,populations}`,
`R/refmac/refmac_hklout_raw_export.json::{header_parse,rows}`,
`A/current/{result,residual_members,completeness_members,native_bin_bounds,native_slot_records,completeness_slot_records}.json`,
`R/refmac/refmac_xyzout_audit.json::{comparison,model_preservation_unproven_reason}`,
and `C` §§3–7. `_inspect_mtz_layout` is a structural helper; its permitted
flag-column dataset binding must not be confused with the stricter output audit.

The separate completeness loop has 7,262 generated-ASU rows: 7,217 observed and
45 missing. Those 45 comprise 31 shared excluded HKLs and 14 additional ASU HKLs;
they are not additional HKLOUT rows (`A/current/completeness_members.json`,
`C` §5.2). The native reader marks nonpositive input F with negative sigma
(`oppro_allocate.f:4274`); the residual guards skip nonpositive SO
(`subcf_scale1.f:136,168`). The writer leaves F/SIGF at `fffa5a5a` for the 31
unobserved output rows, while `ABS(FREER(IR))` maps native padding `80000000`
to exported `00000000` (`oppro_allocate.f:5960–5961,5999–6000,6292–6294,6308`;
`A/raw-side-effects.json::{invalidated_eligible,padding_flag_observations}`).
This mechanism explains observed words without admitting the changed domain.

C0 bounds are in raw trace lines 3–23; the saved
`A/current/native_bin_bounds.json` contains L0 bounds, at raw lines 29097–29117.
Overall slot 21 repeats the endpoint pair rather than being a zero bound.
The endpoint words are `3C23EEAD` and `3E4CCC57`; captured J is used directly,
without midpoint-derived bins (`C` §§5.1–5.2 and the raw records).

For #1109, `A/current/result.json::native_carriers` retains work/free words
`3E2D5A39` / `3E59E4E1`; the log prints `0.1693` / `0.2128` and XML prints
`0.169` / `0.213` (`R/refmac/refmac.log:1171–1172,1200`;
`R/refmac/refmac_xmlout.xml:19`). Exact captured-operand ratios are
`1147753088519/6779817333088` and `155910436577/732706205892`;
the fixed exported-column ratios are `1147828313894/6771678021525` and
`38960352489/182802227126` (`C` §6.2 and its pinned `replay_export.py`).
Exact real/rational sums do not equal ordered native binary32 accumulation.
No fitted scale, tolerance change, or positive-only substitution resolves that
distinction. `YOS = FO / SCALE_LS_OVER`; the exported F/FC quantities follow
the separate APPLYSCALES representation described in `C` §§6.1–6.2.

The sulfate order change is `O1,O2,O3,O4,S` to `S,O1,O2,O3,O4`
(`R/inputs/original_model.pdb:863–867`, `R/refmac/refmac_xyzout.pdb:859–863`).
The element-case changes are CA A98 and NA B98, not water residues. The 877
serial changes, zero segment changes and two charge-text reorderings
(`2+` to `+2`, `1+` to `+1`) are separate observations, not extra gate causes
(`A/raw-side-effects.json::model.field_differences`, `C` §7.1).

The settled #1104 choice remains **MAKE HYDR All / HOUT No**: riding hydrogens
contribute to structure factors while written PDB coordinates are hydrogen-free.
The companion mmCIF hydrogen count is not an internal active-scatterer census.
Source: `ref/research/1sar_rerun_2026_11_07_hydrogen_policy.json` and `C` §7.2.

## Source ancestry and the remaining witnesses

`C` §6.3 establishes the source-level F1 caller edge:
`RESIDVAL -> REFALL -> REFALL1/REF_ALL -> PROPI -> LSQ_COEF`, under the ordinary
NCYC 0 path. It separately establishes P1 scalar reaching definitions and P2
`NCYCLE_OVERALL = 1` array/print ancestry through REPORT_ALL_STATS and
REPORT_XRAY_STATS. XML's cycle label is zero. This is not a newly observed
print-memory read, machine-code certification, or a rewrite of the historical
Gate 2 receipt. The captured `NREF = 7248` is a reflection count, not a cycle count.
Vendor anchors: `hkon_secder_tch.f:2402–2444,3071–3072,5050–5085`;
`subag_scale_hessian.f:130,285–288,492–495,508–512`;
`subcf_scale1.f:384,392`; `refmac_xml.f:261–296,544–554,592–597,912–923`.

F3 can be narrowed beyond the older statement that ML1CF lacks a hook.
Under the retained ordinary active mode, the vendor-local post-APPLYSCALES
path preserves FO/SIGO/FC/PHASE **conditional on premise L**: the external
LSTLSQ resolution metric/result and relevant geometry state are equivalent
for each retained HKL at ML initialization, LSQ evaluation and ML1CF,
including across `LRCLOS(MTZIN)` (`oppro_allocate.f:3924–3926`).

The source argument uses the active call chain in `subag_scale_hessian.f:145–167`
and `ml_scaling_double.f:558–609,808–1532,2269–2291,2837–3016,3083–3104,3257–3784`.
DPPI alternatives and LREFIN write blocks are inactive. The remaining ML1CF
write guard compares `STL_C = 2*sqrt(LSTLSQ(...))` with `SMINB_ML(1)` and
`SMAXB_ML(NBIN_ML)` (`subcf_scale1.f:637–718`). Let s/t be the captured
statistics endpoints. Initialization gives outer bounds
`lo = max(1e-16, 2*s - 1e-4)` and `hi = min(T, 2*t + 1e-5)*1.0001`, where T
is the maximum initializer `sqrt(4*LSTLSQ)` among positive-F/positive-sigma
rows (`oppro_allocate.f:4993–5021,5050–5056`). Under L and the source-preserved
population, the retained positive upper-endpoint row (12,25,6) establishes
`T >= 2*t` (raw trace line 68274). Thus the outer margins contain the active
captured range; the guard does not zero it. This is a conditional source bound,
not a reconstruction of unobserved ML interior bins or endpoint words.

The normal-path source also excludes LSQ's array-write block with captured
IMODE 0 (`subcf_scale1.f:194–208`). APPLYSCALES does not receive the separately
allocated PHASE1 array (`hkon_secder_tch.f:5050–5066`;
`subag_scale_hessian.f:140`; `ml_scaling_double.f:4318–4408`). The optional
`write_fofc_sigma` returns when FCFOUT is absent (`hkon_secder_tch.f:6324–6325`):
that absence is operationally validated in the retained pre-execution checkpoint
and execution-commit profile/runner path, not inferred from a missing file
(`R/refmac/refmac_pre_execution_checkpoint.json::invocation.diagnostic_profile_baseline`;
at `75c0442c`, `scripts/refmac_diagnostic_profile.py:7331–7340` and
`scripts/onesar_refmac.py:9220–9254,9537–9538`).
`make_BDATA_OUT` copies named output values into BDATA before LWREFL
(`rcard_tor1.f:6364–6373`; `oppro_allocate.f:6646,6650`). These source subedges
do not supply the missing exact per-occurrence values in the following table.

| Open item | Minimal missing proof or witness |
| --- | --- |
| F1 partial-array state | S0 already captures main-slot YC0/PHI0 (raw `sumsfs_ls_deriv_row`, first at line 29120). The corresponding partial FC/phase input state still needs retained occurrence-bound words or a complete source/state proof; do not request the already captured main-slot fields again. See `C` §6.3 F1 and `ls_scaling_double.f:514` onward. |
| F2 scaling/stores | Bind per-HKL RSQ and recomputed EXPAN to the pre/post FO/SIGO, main FC store and partial FC stores inside APPLYSCALES (`ml_scaling_double.f:4345–4403`). These are not division by SCALE_ML. Closed source subedges may replace redundant capture where sufficient. |
| F3 premise L | Exact-build-associated CCP4 library source proving the relevant LSTLSQ/LRCLOS state lifecycle could discharge L offline. An occurrence-bound metric/state witness is an alternative; another native run is not inherently required. Unassociated local library source is not exact-build proof. |
| F4 exporter-to-bytes | Bind EXTRACT_ABS outputs, a_all_ls/b_all_ls accumulation and square-root storage, LIND row order and the resulting pre-LWREFL BDATA words to final MTZ words (`oppro_allocate.f:6049,6076–6077,6089–6090,6118–6119,6338,6646,6650`; `C` §6.3). A final BDATA snapshot alone closes only that last edge. |
| Runtime coverage | Define a bounded process/phase/loaded-image claim and retain the corresponding inventory/identity observations, explicitly identifying shared-cache or uncovered regions and mutation limitations. Disk hashes alone do not establish loaded memory bytes or timeless identity; diagnostic coverage does not imply stock numerical equivalence. |

Any new capture requires a separately authorized Attempt 05, with a fresh
evidence root, distinct instrumented build/profile, explicit preregistration,
and additive provenance-bound hooks. Nothing here authorizes it. Earlier
attempts, recipes and receipts remain immutable; no batch follows an ineligible
canary.

## Decisions to select next

The following **SAR1–SAR6 choices are all unselected**. They are separate from
U01–U14 in `ref/research/phenix_evaluation_preregistration_spec_2026-11-11.md` §5;
there is no asserted mapping between the two menus. They can be considered in
the same next planning step. Any changed admission convention or estimand needs
its own reviewed prospective registration and never rewrites historical gates.

| Choice | Current boundary | Prospective alternative for the user to evaluate |
| --- | --- | --- |
| SAR1: producer | Keep the instrumented producer diagnostic-only under the current gate. | Define whether and for what claim this distinct producer may be admitted, with a bounded runtime-coverage requirement; do not call it stock equivalence. |
| SAR2: dataset roles | Keep the retained split-layout output rejection. | Consider role-aware flag/base and amplitude dataset bindings, with explicit identity evidence. This does not resolve lost zero-F observations. |
| SAR3: population | Preserve the full original eligible input contract and reject the observed losses. | Consider a separately registered native-active estimand while retaining all original rows and exclusion reasons. No retrospective denominator substitution or imputation. |
| SAR4: bins | Keep Gate 4 false. | After producer and population admission, define the evidentiary role of captured native J/bounds and independent checks without inferring native bins or claiming unproved arithmetic equivalence. |
| SAR5: R quantity | Keep the unresolved reconstruction gate and report the distinct quantities separately. | Specify which representation is compared and what ancestry proof is required, retaining native carriers, captured sums and exported residuals rather than tuning them into agreement. |
| SAR6: model representation | Keep the three observed representation differences as Gate 6 blockers. | Consider an explicit output order/record-class/element-case convention. Internal chemistry/scatterer equivalence remains a separate stronger claim; #1104 stays settled. |
