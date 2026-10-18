# Next tasks

A curated working view of substantive work not yet done. **GitHub Issues are the source of truth**
for what is open; this file carries execution detail and context, and names every open item that has
**no** issue as such, so an empty queue is never mistaken for an empty backlog.

**Last reconciled: 2026-10-17**, against `main` at
[`d06475e`](https://github.com/CultureBotAI/protstruct_review/commit/d06475eb378f32e948c2eca177a92aad3ca99121)
(PR #905): **13 open issues, 1 open PR** ([#912](https://github.com/CultureBotAI/protstruct_review/pull/912)),
with both complete lists checked against API totals after the PR's fresh adversarial review.
The date is local (America/Los_Angeles; the review snapshot is 2026-10-18 UTC).
Issue bodies and comments, exact merged PRs, current code and retained records were reviewed;
this was a documentation reconciliation, not a scientific rerun or a new installation inventory.
The live ledger and proposed work directions are under [Open](#open). **Check GitHub before execution;
this file does not mirror it in real time.**

**Previous reconciliation history:** the 2026-10-15 review checked `main` at `8aef21c` (PR #878),
with seven open issues and no open PRs. PR #905 delivered that reconciliation, the project goals,
and the backlog-update skill. The initial 2026-10-17 prepublication snapshot contained twelve
issues and no PRs: four additional issues tracked the quality-guide defects and a fifth the
related ProSMART capability audit. PR #912's fresh review added the residual reporting issue #913.
The seven preceding scientific issues retain their dispositions.
The 2026-09-26 review checked `main` at `121d088` (PR #754).
The queue was empty then; that reconciliation filed #760–#767, and its reviews filed #769–#780
(#769–#773 and #778–#780 fixed in PR #768). Its coverage since 2026-08-29 included the
gate-consolidation close-out (#293), the toolchain/CI hardening after the transfer, and the September
[QDS integrity and 1SAR evidence correction](#qds-integrity-and-the-1sar-evidence-correction-2026-09-09--2026-09-23)
track.

The repository lives at `CultureBotAI/protstruct_review` since 2026-08-29 (transferred from
`realmarcin` to escape a personal-account Actions billing lock, [#410](https://github.com/CultureBotAI/protstruct_review/issues/410)).
The GitHub Actions workflow runs the hermetic gate on Linux and macOS on every PR and `main` push
(first green on `main`: run 33283623725, after [#492](https://github.com/CultureBotAI/protstruct_review/issues/492)/PR #494
removed the gate's dependency on a Homebrew `gemmi` CLI; historical green `main` at `121d088` in run 35915199044).
Licensing and citation landed in #479 (2026-08-26). The required local gate is
`uv run --locked --extra benchmark -- bash scripts/validate.sh` using the repository-selected
Python 3.12; bootstrap with `uv sync --locked --extra benchmark`. It must exit 0 before a merge,
and Linux/macOS CI must be green on the reviewed PR head. Python 3.11 remains supported, but its
locked Biotite version skips the exact retained T15/T16 numerical replays; a clean no-extra
environment also skips them. Neither substitutes for the CI-equivalent gate. External-tool and
online benchmarks remain manual.

**Date conventions differ by section, so two dates for one PR can differ by a day.** The negative-control
table and its close-out notes use GitHub (UTC) merge dates — only the table **rows** are checked, against
the squash commits within ±1 day, by `scripts/check_next_tasks_dates.py`; the close-out prose is not; the
tolerance table uses round dates (also unchecked); the gate-consolidation and QDS-track prose use squash-commit dates; issue closures are GitHub
UTC close dates.

## The negative-control track (2026-08-08 → 2026-08-26)

A second benchmark series, planned from a deep-research run and executed in eleven preregistered
rounds: gold-standard sub-Å structures as **negative tests** for refinement. Full plan:
`ref/research/negative_control_benchmark_plan.md`; tracking issue
[#295](https://github.com/CultureBotAI/protstruct_review/issues/295) (closed 2026-08-26); round docs
`ref/research/negative_control_round<N>.md`; records under `ref/research/data/`.

| Milestone | PR | Outcome |
|---|---|---|
| Plan (from deep research) | [#294](https://github.com/CultureBotAI/protstruct_review/pull/294) (2026-08-08) | curation, prior art, confound handling, metric families registered as a phased plan |
| Phase 0 feasibility + phase 1 masks | #299, #305 | every window viable (≤1.0 Å strict: 254 entries/116 clusters); residue-level masks with post-mask outlier protection |
| gemmi R path promoted + hardened | #300, #326 | non-cctbx R oracle in `scripts/`; work-only scale fit (free-set leakage removed, offset ≤1e-5) |
| Codex external review remediation | #313, #326, #328, #330, #332 | all 10 findings resolved: trust invariant ENFORCED with waivers (validate 3c), record-reconciliation guard (3b), unified array selection, null-centered statistics, provenance + hash-verified caches |
| Rounds NC-1/NC-2: enrollment | #307/#310, #313/#334 | NC-1 stopped at its registered finding (the preregistration working); NC-2 enrolled **22 gold standards** |
| Round NC-3: the bench | #336/#339 | Q1: **0/22 false verdicts on nulls**; SA's sub-Å signature measured (fit destruction, geometry preserved) |
| Round NC-4: perturb-recover | #340/#343 | the anti-gaming arch closes: do-nothing fails NC-4 (22/22 flagged), damage fails NC-3; plain recovery = coordinates yes, fit no (3/22) |
| Round NC-5: **first agent subjects** | #346/#352 (merged 2026-08-15→17) | ladder measured: protocol 3/22 → solvent 11/22 → **blinded agents 21/21 certified, 14 better than the depositions**; 22/22 transcripts audit-compliant; an agent subject discovered a benchmark flaw (MLHL, #350) |
| Round NC-6: data hygiene | #357/#359 (2026-08-17) | durable store + universal row hashes + fetch-time strip (12 entries carried derived columns, not 1 — prereg census corrected); 8R5K re-screened clean (**#349 closed at merge; #350's deliverables shipped here, closed at the 2026-08-17 reconciliation**); **U3 falsified** — the C1 table moved, adoption refused pending re-registration (done in NC-7's H1); 2VXN deepened into a four-tool spread with the deposition tiebreaker siding against both Murshudov tools |
| Round NC-7: attribution | #363/#367/#370 (2026-08-17) | **2VXN attributed (#355 closed): the Murshudov family never applied the deposited aniso ADPs** — iso-only model moves both R paths +0.051, REFMAC/Servalcat 0.000; closing invocation `REFI BREF ANIS` (0.1712→0.1371) registered as the third-opinion amendment. H1 flip sweep: 66 rows, zero verdict flips. **V3 falsified** (9YGW's aniso block is internally consistent — CYS-altA/CSO-altB microheterogeneity; stays named-unmeasurable, census 21/22). **V4 falsified with mechanism** (the converter rolls random free flags on unmeasured reflections — refetch is provably non-reproducible for 11/12); 8R5K remediated end-to-end on the user's explicit go-ahead (#370) |
| Round NC-8: closeout | #373/#376/#378 (merged 2026-08-17→19) | **the aniso tax is set-wide: 21/21 entries drop under `REFI BREF ANIS`** (median −0.033, all ~6× beyond `d_refmac` — the no-mixing rule proved structural). **W4 falsified terminally**: 9YGW's PDB form fails at the same CYS/CSO position — **stood down to permanent two-path status**. All 11 wavelength patches proof-verified, then written on the user's named go-ahead (#378, deposition values incl. two converter-placeholder corrections); the store is complete, 22/22 nonzero-wavelength and sidecar-consistent (**#361 closed**) |
| Round NC-9: **the ANIS adoption** | #379/#383 (merged 2026-08-19→20 UTC) | first falsification-free round — **X1/X2/X3 all hold**: 22 nulls regenerated, reproducing committed deltas at worst gap 0.0006 (8R5K's match also quantifies the MLHL contamination's delta impact as negligible); **`d_refmac_anis` = 0.01150** registered with record cross-check; direction agreement 20/21 vs 17/21 — 2VXN's null flips −0.0122 → +0.0130, so **the #355 sign conflict was manufactured by iso-collapse**. From round 10, the third opinion grades gold standards with their anisotropy applied; ISOT retained as history |
| Round NC-10: **`osol_h` + per-entry sandboxes** | [#415](https://github.com/CultureBotAI/protstruct_review/pull/415) | **Y1 holds: 15/22 recoveries**, four above `osol` with no old success lost. **Y3 holds exactly:** 22 distinct sandboxes/PGIDs, zero signal-terminated refinements or store mutations; #356's remaining half ships. ANIS is measurable 21/21 with zero convention mixing, but **Y2 is falsified** by 2VXN's one W4 contradiction; the driver preserves all 22 rows then exits nonzero. Perturbations regenerated with maximum round-4 reproduction gaps 0.0214 Å unmasked / 0.0181 Å all-residue. |
| Round NC-11: **the 2VXN echo** | [#421](https://github.com/CultureBotAI/protstruct_review/pull/421)/[#423](https://github.com/CultureBotAI/protstruct_review/pull/423) (merged 2026-08-22) | **Z1/Z2 hold, Z3 falsified — and the falsification is the finding.** The candidate-leg pre-gap decomposes almost exactly (0.0328 = solvent 0.0410 − riding-H 0.0111 + 0.0029, sandboxed zero-cycle REFMAC), while posts agree within 0.0012. The post-agreement amendment **refused itself** by its registered L3 safety sweep (54/78 rule flips), so the else-branch stand-down is enacted: `CANDIDATE_LEG_THIRD_OPINION_STANDDOWN = {"2VXN"}` — 2VXN contributes no REFMAC third opinion on candidate legs; its rows are two-path and say so. |

Also landed alongside NC-8/9: the record-reconciliation guard now covers **bench and
recover records** with verdicts recomputed from their own evidence (**#338 closed**, #381).

**Gate consolidation (#293, closed 2026-08-30):** the design pass the issue requires before any gate is touched
landed as `ref/research/gate_consolidation_inventory.md` (PR #454) — 11 guards classified, nine multiply-stated
facts (eight with a machine-readable source), three ranked consolidation steps (in-record NC headline
block → thresholds YAML sidecar → round-count check extended to `lessons.md`). Implementation is one PR per step,
each with its regression test before the swap. **Step (a) landed** (`scripts/nc_headlines.py`, PR #511,
2026-08-29): the three per-family prose checks are one generic rule over a top-level `headlines` block the
drivers write; records without the block are rendered by legacy-equivalent renderers, so no committed
record was rewritten. **Step (b)** (`ref/thresholds_and_standards.yaml` + validating loader in
`check_driver_thresholds.py`, keyed lookups replace `CHECKS[0]`; PR #524, 2026-08-29). **Step (c)** (PR #532,
2026-08-30): the rendered round-count comparison now runs on `lessons.md` as well as this file
(`check_summary_coverage`, the #467 class). All three steps are done and **#293 is closed**. Two things it
did not do: the `headlines` block governs **no committed record yet** (0 of the 14 NC records carry it, so
every NC headline check still runs through the legacy renderers until the next NC round writes one), and
the partial-record ledger sidecar — the example that motivated #293 — was deferred by the inventory as a
separate design question. **2026-10-15 qualification:** PR #842 subsequently delivered the scoped
§3/§4 descriptive evidence ledger at `ref/threshold_evidence_status.yaml`; whether broader coverage is
useful remains optional under [Open](#open), with no issue. The inventory's guard tables describe the
state before consolidation and predate the September guards (`check_pass_status.py`, `strict_yaml.py`).

**NC-11 closeout and the registry:** the stopping/consolidation checklist promised by #292 landed as
`ref/research/stopping_criteria.md` ([#427](https://github.com/CultureBotAI/protstruct_review/pull/427), merged 2026-08-26; #292 closed at merge). Phase 5 of #295 — the promised
registry treatment — is `ref/thresholds_and_standards.md` §6 (negative-control verdict rules, guarded
against `bench_recover_leg`'s record-derived constants in validate 3b; #433), with 3b now opening every
committed record family (#434) and this table reconciled (#435).

**NC-10 closeout:** the first verdict-bearing ANIS round and #356's remaining sandbox half are
complete. The mask-constrained D6 criterion from #321 landed before this round and remains bound to
the next screen registration; it was correctly outside NC-10's recover-leg scope.

## QDS integrity and the 1SAR evidence correction (2026-09-09 → 2026-09-23)

A September track that re-audited the one real co-scientist record — the OpenScientist 1SAR (RNase Sa)
refinement — and rebuilt QualityDataSheet (QDS) emission so an issued sheet can be replayed and corrected
without rewriting history. That implementation and correction track is complete within its dated
scope; the later scientific follow-ups in [Open](#open) remain separate. Detail lives in the records
and review trails named below, not here. Dates are squash-commit dates.

**The current 1SAR account is
[`QDS_1sar_cdba2c07_2026-09-23.yaml`](data/coscientists/openscientist/QDS_1sar_cdba2c07_2026-09-23.yaml)
with its narrative
[`EVAL_1sar_cdba2c07_2026-09-23.md`](data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-09-23.md).**
Cite it, never an earlier 1SAR sheet: the frozen April–September sheets keep their withdrawn
interpretations by design and are listed in that sheet's `corrected_qds_refs` (9).

- **What the artefact actually contains** (#536, 2026-09-09). The packaged `1sar_final.pdb` is the
  round-4 output; the round-7 model the agent's report describes was never packaged, and its reported
  R-factors are attested only by the agent's own log. The earlier "R-free matches no model" accusation was
  withdrawn, the wrong-protein identity was re-attributed to the harness prompt, and the May ion, SO4 and
  "T03 settled" conclusions were withdrawn. The April and May records were left byte-identical. #602
  (2026-09-10) reworded the gemmi recommendations to stop asserting the withdrawn finding; #689 later
  superseded those entries.
- **Verdict integrity** (#587 2026-09-09, #690 and #705 2026-09-22). `pass_status` semantics are gated
  (validate step 3c-bis, CODING_STANDARDS 13c); evaluation records are accepted only in canonical
  `EVAL_*.yaml` carriers; YAML loaders reject duplicate keys. A new verdict now requires a registry-grounded
  `PassCriterionBinding` with evidence-backed preconditions, and **none has been admitted**
  (`ref/structural_criteria.yaml`: `pass_criterion_bindings: []`), so no new pass/fail verdict can land
  unless the same change admits a binding for it. All verdict-bearing rows sit in two content-pinned
  legacy files.
- **Rubric reconciliation** (#689, 2026-09-22). Consumers of the §3 R-work agreement row (the T03/T06
  drivers, the skill, `gemmi_rfactor.py`) were aligned with the registry's existing |ΔR| ≤ 0.02 envelope,
  now scoped to directly summed R-work: R-free offsets and the bin-rescaled estimator stay informational.
  T14 flip-set agreement was split, with the ≤ 10 % confident-conflict band applying to preregistered
  cohorts only. The 2026-09-07 1SAR record was re-scoped to informational. QDS emitter contract 2.
  **Later policy:** #809 / PR #835 suspended the unsupported flip grading rule; the September 22
  description here is historical, not current grading authority.
- **Replayable partial sheets** (#613 and #719, 2026-09-22). Emitter contract 1 frozen with replay pins
  and subject isolation; contract 3 adds a typed, source-owned emission context for partial sheets.
  Partial 1SAR sheets for T16 (2026-09-21) and T15+T16 (2026-09-22) were published with retained
  evidence. #613 re-tagged the T15 secondary-structure row `[benchmark — historical denominator unproven]`
  (see #765, #766) and moved CI to `--extra benchmark`.
- **T13 and density guidance** (#726, 2026-09-22). The T13 wrapper emits informational single-oracle
  diagnostics with the input MTZ identified by SHA-256; live RSCC/RSR, water and ligand-pose guidance
  now matches the registry. Its tests mock CCP4 execution; PR #831 separately
  retains a real installed-CCP4 operational canary (#767).
- **Synthetic active-site correction** (#731, 2026-09-23). A new, explicitly fictional contract-3
  example pair with corrected tool provenance; dated registry successors stop attributing the historical
  1SAR clashscore gap to hydrogen building (cause unresolved) and stop treating Allowed rotamers as
  outliers. The drivers had not been updated to match; #761 and #775 fixed them and put those rows under
  the driver-threshold guard, and #763, #774 and #776 withdrew the remaining "identical H coordinates"
  basis from the registry, T05, T14 and the two benchmark records, settling one clashscore
  precondition (matched convention, same `reduce` binary and version). Decomposing the residual is
  optional work (#790).
- **Correction-aware contract 4 and the dated 1SAR correction** (#754, 2026-09-23). Typed, hash-pinned
  corrections withdraw or replace exact historical targets before every builder; a typed model-to-dataset
  association admits retained T13 diagnostics; a `measurement_evidence_origins` ledger keeps a correction's
  date from making an old observation look new (CODING_STANDARDS 13h/13i). Applied to 1SAR: all 83 April
  scalar rows carry an explicit disposition (60 replaced, 23 withdrawn), every active row is informational,
  and the 11 cctbx-only gaps carry named waivers, not passes. **Scope:** a retained-evidence correction of the
  packaged round-4 model — not a quality-assessment rerun and not a quality pass. No PHENIX, CCP4, gemmi or
  canonical CheckMyMetal run was made; the only new observations are 3 coordinate recounts, which are
  arithmetic on retained coordinates, not geometry validation. Review trail:
  `ref/research/qds_correction_contract_review_2026-09-23.md` (three needs-attention passes, then approval
  of the emitter at `5bcf2cb6`).

What this track left open is in the [Open](#open) ledger; its disclosed external limits are under
[Not actionable](#not-actionable-in-this-repo-listed-so-the-gaps-are-explained-not-recommended).

## Where the tolerance work stands

Forty-eight rounds of benchmarking have replaced inferred magnitudes with measured ones. Round 6 found
that **two of three "blockers" were wrong** — both mis-invocations rather than limits of a tool.
Round 7 then found that **two bands set in rounds 5 and 6 were themselves wrong**, fitted to a narrow
resolution range and breached by null re-refinement once low-resolution entries were included.

<!-- threshold-status-summary:start -->
**Current descriptive inventory (§3/§4; not grading authorization).**

21 rows; 20 benchmark-family rows (including qualified tags); 41 scoped components.
Historical through-round48 labels: 18 reported-backed / 2 reported-partial / 1 excluded-literature rows. These are historical claims, not current scientific certification.

Component policy counts: active_conditional=29; informational=6; not_evaluable=1; policy_unresolved=1; provisional_conditional=1; provisional_informational=2; suspended=1.

Component evidence counts: denominator_unproven=1; external_standard_cited=1; limited_controls=1; partial_record=4; producer_mismatch=1; retained_record=23; unmeasured=9; unverified_ancillary=1.

Scoped row flags (overlapping, not additive): suspended: h_placement; not_evaluable: clashscore; policy_unresolved: favored_percent; provisional_informational: secondary_structure; provisional_conditional: geometry_delta.

The ledger separates active rules from retained evidence, provisional interpretation, suspension and unavailable calibration. Retained records do not by themselves establish independent calibration or complete execution provenance. Counts of components are not counts of rows or distinct benchmarks. See `ref/threshold_evidence_status.yaml`; scientific grading still requires the applicable registry criterion and evidence.
<!-- threshold-status-summary:end -->

**Historical registry narrative (through round48; not current policy).** Round 17 audited every `[benchmark]` row and found **7 quote a figure
from a set that can no longer be reconstructed**; they are marked `⚠ partial record`. Round 18 fixed
the cause — **every `bench_*.py` now commits the set it ran on**, and `scripts/validate.sh` fails if
one does not. **The historical inventory reported 18 fully backed rows** (rounds 42 and 44 re-based every §4 `d_min ≥ 2.5 Å` X-ray figure — both band widths and the geometry row's clashscore null ratio / starting ceiling — off their lost sets onto the 44 named entries, fully backing the ΔRMSD and geometry rows; rounds 45–46 backed both vs-deposited geometry-% rows on the 42 named entries — **favored %** on named data, and **outlier %** by making the check per-shared-residue classification agreement rather than the denominator-sensitive raw % (#284); rounds 47–48 backed the **H-placement flip-set** row on the named set with the check made the confident-conflict rate rather than the raw disagreement rate inflated by one builder's uncertainty (#287) — the two remaining marks are both RETAIN, so every *resolvable* partial record is resolved). **That reported inventory is not current independent calibration:** #809 suspends T14 flip grading because the retained benchmark used PHENIX-distributed Reduce, not the claimed standalone producer; #613 (2026-09-22) requalified one of the 18, the §3 secondary-structure agreement row, as `[benchmark — historical denominator unproven]` — its 0.65 expectation is non-gradeable until the benchmark is rerun with exact per-assigner denominators ([#765](https://github.com/CultureBotAI/protstruct_review/issues/765)). The descriptive ledger now recounts scoped policy and evidence states (#766); it does not retire the scientific limits behind #765 or #809.

**2026-10-15 T15 status:** the original exact-domain rerun is stopped; the current next step is
input-based comparison-population design under #765 in [Open](#open). Neither the retained diagnostic
nor that design proposal recalibrates the historical expectation.

**Historical count convention (round 18) — two different counting units.** §3 and §4
hold **21 rows**, of which **20 carry `[benchmark]`**; the exception is §4's *absolute geometry
floors*, which is `[literature]` and was never measured here. Those 20 rows carry **21 benchmarked
tolerances**, because the map-model row holds two, CC_mask and `d_FSC_model`. So "21 rows" and "lost
21 times out of 21" are both correct and count different things — and round 17's "20 rows, not 21"
was itself a miscount, blaming the shared map-model row when the real exception is the `[literature]`
floors row.

| Round | PR | Settled |
|---|---|---|
| 1 | [#24](https://github.com/CultureBotAI/protstruct_review/pull/24) (2026-07-25) | interface BSA, Wilson B — the two marked *provisional* |
| 2 | [#28](https://github.com/CultureBotAI/protstruct_review/pull/28) (2026-07-26) | R offset, clashscore, H-placement, CA RMSD, aligned-residue count, bond-length RMSD |
| 3 | [#32](https://github.com/CultureBotAI/protstruct_review/pull/32) (2026-07-26) | restraint-library decomposition, Asn/Gln/His flip sets, L-test |
| 4 | [#36](https://github.com/CultureBotAI/protstruct_review/pull/36) (2026-07-26) | Ramachandran/rotamer outlier %, R-free, completeness, SS agreement, DockQ mapping, NMR ordered core |
| 5 | [#39](https://github.com/CultureBotAI/protstruct_review/pull/39) (2026-07-26) | the §4 refinement Δ-tolerances (X-ray + cryo-EM), Ramachandran favored % |
| 6 | [#42](https://github.com/CultureBotAI/protstruct_review/pull/42) (2026-07-26) | flip sets vs reduce2, rotamer assignment agreement, §4 detection floor |
| 7 | [#44](https://github.com/CultureBotAI/protstruct_review/pull/44) (2026-07-26) | §4 bands made resolution-conditional; rotamer boundary bounded |
| 8 | [#46](https://github.com/CultureBotAI/protstruct_review/pull/46) (2026-07-26) | 2.5 Å split validated; restraint effect measured; round-7 `d_FSC_model` diagnosis withdrawn |
| 9 | [#48](https://github.com/CultureBotAI/protstruct_review/pull/48) (2026-07-27) | `d_FSC_model` mechanism found; the clause is gateable after all |
| 10 | [#50](https://github.com/CultureBotAI/protstruct_review/pull/50) (2026-07-27) | EM set completed (CC_mask band breached and widened); §4 high-res end filled; rotamer chi geometry verified |
| 11 | [#52](https://github.com/CultureBotAI/protstruct_review/pull/52) (2026-07-27) | both "edge" bands breached; CC_mask made resolution-conditional; rotamer library corroborated |
| 12 | [#54](https://github.com/CultureBotAI/protstruct_review/pull/54) (2026-07-27) | CC_mask holds at 22 entries and its split is located; `d_FSC_model` band made relative |
| 13 | [#56](https://github.com/CultureBotAI/protstruct_review/pull/56) (2026-07-27) | CC_mask `< 3.0 Å` breached and widened; `d_FSC_model` band corrected to one-sided |
| 14 | [#60](https://github.com/CultureBotAI/protstruct_review/pull/60) (2026-07-27) | EM benchmark made reproducible; entry count shown not to be evidence; split kept |
| 15 | [#62](https://github.com/CultureBotAI/protstruct_review/pull/62) (2026-07-28) | pre-registered low-resolution widening: P1–P4 confirmed, P5/P6 falsified, clustering withdrawn |
| 16 | [#66](https://github.com/CultureBotAI/protstruct_review/pull/66) (2026-07-30) | per-entry record made durable; all 5 predictions held; `d_FSC_model` tail shown to be sampled thinly, not thin |
| 17 | [#69](https://github.com/CultureBotAI/protstruct_review/pull/69) (2026-07-30) | rate question closed as underpowered; 10BU verified byte-identical; registry audited (7 rows marked partial); ligand screen moved to fetch time |
| 18 | [#69](https://github.com/CultureBotAI/protstruct_review/pull/69) (2026-07-31) | every benchmark commits its set + gate; bond-angle recovered and DockQ mark withdrawn; fetch attrition made durable; §4 staleness diagnosed as two untested clauses |
| 19 | [#82](https://github.com/CultureBotAI/protstruct_review/pull/82) (2026-08-01) | EM set 59→69 named entries; all bands held; P4 falsified and round 16's tail reading corrected; 10BU located at 3.24× the next-largest; zero refinement-stage attrition |
| 20 | [#86](https://github.com/CultureBotAI/protstruct_review/pull/86) (2026-08-02) | the two §4 clauses untested since round 7 re-measured: both hold, both worst cases reproduce exactly; the clashscore ratio gate found undefined at `pre = 0` and given a low-end guard; `phenix.refine` shown deterministic 8/8 |
| 21 | [#92](https://github.com/CultureBotAI/protstruct_review/pull/92) (2026-08-03) | L-test made re-derivable on a committed 24-dataset set instead of being retired — a subset re-run, so reproducible rather than corroborating; EM benchmark now writes per-entry results as it goes |
| 22 | (2026-08-03) | 10BU shown to be a genuine statistical outlier; a candidate mechanism supported but not established (n = 2), with the successor test specified; flip-set row shown **not** to be fixable by round 21's route |
| 23 | (2026-08-03) | crossing-quality test **could not be run at the 1.3 cut** — 0 of 24 screened; at the data-driven 1.074 fence one already-refined near-miss (10EU) leans against it; estimator characterised over 60 crossings; the fetcher's all-or-nothing write fixed |
| 24 | (2026-08-04) | staleness audit: the registry's `named entries` definition had drifted to yield 93 not 69; a gate now recomputes 8 dataset-dependent figures and fails on a stale value **or** a rewrite |
| 25 | [#129](https://github.com/CultureBotAI/protstruct_review/pull/129) (2026-08-04) | first systematic audit of `scripts/` itself — **12 defects** (#116–#127), 4 high, including a guard that **could not fail** (it compared four counts it derived itself and never read the registry) and a wwPDB parser fabricating `0.0` violations where the real value is 17.4. No tolerance changed |
| 26 | [#141](https://github.com/CultureBotAI/protstruct_review/pull/141) (2026-08-04) | tested round 25's three parting claims: **P1 and P3 confirmed, P2 falsified, P4 indeterminate**. Declared the EM `status` vocabulary once beside its writer; gated a round document's claims about its own findings. Six review passes found **14 defects** (#139–#153), several inside the round's own fixes. No tolerance changed |
| 27 | (2026-08-04) | gated the counts the summary files quote, after **9 miscounts** shipped across rounds 24–26; found the round-coverage gate merged one PR earlier had **two false passes** (an unrelated table, and a fenced example row) because it lived in shell and could not be tested |
| 28 | (2026-08-04) | **measured** the miscount class instead of gating it again: ~326 numeric claims swept by hand, ~307 verifiable, **7 wrong** (~2.3 %) + 3 contested. Two of four predictions falsified — self-contradiction does *not* dominate (2 of 7), and the gate-covered files are *not* where the errors are. The registry is **~5.7× cleaner** than the round trails, which have no gate at all |
| 29 | (2026-08-04) | set out to gate the registry's **per-entry** figures (12 aggregate, 0 per-entry, and both of round 28's registry errors were per-entry) and **did not**: P1 falsified — every derivable per-entry figure already matched — and **P2 indeterminate**, the derivable/underivable split flipping with the counting method (#182). Five checks ship, on P1 alone; the gate now states its own coverage |
| 30 | (2026-08-04) | classified every figure found wrong in rounds 24–29: **27 wrong-at-write, 6 stale, 0 undecidable** (corrected in #187 — P3 was reported confirmed and is falsified). Round 28's proposed snapshot convention addresses **1 in 5**, so it was **not written**. 56 % of the rest are counts restated from memory, against a rule the repo already has — **the gap is adherence, not invention** |
| 31 | (2026-08-05) | asked whether **corrections are more defective than the text they correct**. **Indeterminate — underpowered**: 0 of 35 verified claims wrong across 33 `Fix #` commits, but P(0) = 0.446 at round 28's 2.3 % base rate, and 130 verified claims are needed before zero is surprising. Three stale-by-nature counts, no wrong-at-write. Three copies of one pre-#187 figure outlived the correction that fixed the fourth — two live on `main` (#210), one in the tool built to prevent it (#209): **review is not a sweep** |
| 32 | (2026-08-05) | exhausted round 31's inventory under a stopping rule fixed in advance: **58 verifiable claims, 2 wrong (3.45 %)** against round 28's 2.28 % — the predicted direction, and `P(≥2) = 0.382`, indistinguishable from chance. **P5 confirmed**: the inventory yields 58, the test needs 130, so **this population cannot answer the question**. Both wrong claims were introduced by `Fix #` commits and both involve **scope**, which `round_figures.py` would not have caught |
| 33 | (2026-08-05) | exhausted the ungated arm — PR and issue prose, 109 bodies, 493 lines, **101 claims, 3 wrong (2.97 %)**. **P6 falsified in direction**: the ungated channel is *cleaner* than the gated one (3.45 %), so **the gating apparatus is not visible in the error rate**. P7 falsified (101 < 130), P2 falsified on pooled evidence (memory 3, scope 2). Pooled 5 of 159 = 3.14 % vs a 2.28 % base rate — a **0.86 pp** difference needing **~5,542 claims per arm**. **The question is closed as unanswerable here** |
| 34 | (2026-08-05) | ran the crossing-quality screen at the **1.074 fence** round 23 established: **0 of 13** above it, `P(0) = 0.408` at the prior rate — an underpowered draw, **not a refutation**. The blocker is the **query**, not cost: `--per-stratum 6 × 8 strata` offers only 48 candidates, so 2.5 GB bought 14 entries. Six tooling defects found by the canary and the batch (#226–#228, #230–#232), including `entries.json` **overwriting** itself and dropping a paid-for entry from the screen's denominator |
| 35 | (2026-08-05) | widened the query as round 34 said to — 160 candidates, **50 entries fetched** against round 34's 14 — and screened up the **first candidate** the project has ever produced, 7DZX at ratio 1.210. It does not survive inspection: `cc_mask_pre` **0.2083**, worse than every entry on record. **The fence is confounded with model-map fit** (#234) — 2 of the 5 entries ever above it barely fit their maps. Base rate revised **6.7 % → 4.5 %**, or **2.7 %** counting genuine candidates only |
| 36 | (2026-08-05) | pre-registration only — fixed the fit-quality exclusion (`cc_mask_pre ≥ 0.6038`, the Tukey fence over the record) **before** it could be fitted to 7DZX. What it leaves is the finding: the eligible, **non-circular** candidate pool for #224 has **one** member, 10EU, which already fails the 10× bar. Three such candidates needs **~330 screened, ~220 more** |
| 37 | (2026-08-05) | first **named** low-resolution X-ray set — 21 selected by query, **10 usable**. Bands hold; fresh maxima **0.1828 Å** and **2.61 pp** fall short of the lost 0.285 Å / 5.26 pp, which the registration said in advance is weak evidence. **P5 falsified**: the "not reproducible" clashscore 17.2 is ordinary — a fresh sample reaches **38.70**. 11 of 21 lost to three filed defects (#241–#243) |
| 38 | (2026-08-05) | round 37 with the selector fixed. The fix removed the selector-caused **excess attrition** — R-free refinement failures fell **7/18 → 1/17**, **14 of 17** refinement attempts usable against round 37's 10 of 18, 0 lost to nucleic acid — though ~30 % baseline loss (fetch rejects, non-R-free refine failures) remains, untouched by any selector. But an era-spread sample **breached the −6 pp favored band** for the first time: **6LE5 drops 6.28 pp** under a well-behaved null re-refinement, past the lost 5.26 pp. **P3 falsified** (the strong direction); P2 holds weakly (Cα max 0.2004 < 0.285, up from 0.1828); P5 falsified again (max 27.71). Band **not re-fitted** — widening deferred to a registered decision |
| 39 | (2026-08-06) | **arm 1 only.** Settled #253: the favored-band breach is an **unrestrained artefact**. Re-refined the round-38 set **with restraints** (no downloads): **6LE5's drop fell 6.28 → 2.21 pp** (P1), 11 of 14 entries improved and **no restrained entry breached** −6 pp (P2), median favored Δ +0.035 → +1.505. **Band kept at −6 pp** — the breach is specific to unrestrained refinement, not the low-resolution restrained protocol; §4 caveat strengthened. Arm 2 (fresh unrestrained set, P3) left registered and unrun; subsumed by #225 |
| 40 | (2026-08-06) | **answered #224** — the redesign. The crossing-quality mechanism is real, but the *ratio* was the wrong measure: over 19 entries its Spearman ρ with \|excursion\| collapses +0.319 → **+0.049** without the two extremes (2-point leverage), while **crossing determinacy (perturbation-recross) predicts robustly** — ρ **+0.792** extremes-removed (LOO 0.75–0.85), partial **+0.773** controlling for fit (P1, P3 confirmed, so not the #234 confound). **P2 falsified**: the excursion is real movement, 2–2900× the perturbation shift, not jitter. §4 caveat retired the n=2 ratio hypothesis; band unchanged. Resolved on existing labels, ~5 GB, no 50 GB screen. #224 closed, #234/#258 superseded |
| 41 | (2026-08-06) | **#225** — largest fresh X-ray set (round 39 arm 2): **20 usable of 25**, era-spread, excluding all 37 round-37/38 ids. **P3 falsified** (weak direction): worst favored drop **−1.85 pp**, nowhere near round 38's 6.28 — so **6LE5 is an isolated outlier**, 1 of **44** pooled fresh entries to breach −6 pp, and the one arm 1 showed restraints tame. Cα max **0.1849 Å** (< 0.2004 < lost 0.285). Both §4 X-ray bands hold; nothing re-fitted. Lost maxima still unreproduced — the *widths* rest on them, but the bands now have 44 fresh entries under them |
| 42 | (2026-08-06) | **#269** — re-based the §4 `d_min ≥ 2.5 Å` X-ray band *widths* off their lost maxima onto **coverage bounds over the 44 named entries** (research from #225: a lone observed max is a biased, least-robust, low-confidence basis; structural biology uses percentiles). **Cα band 0.35 → 0.25 Å** (99/95 lognormal UTL 0.2514, flags 0 of 44, better detection power); **favored kept at −6 pp** (round 39), re-justified as ~98% coverage. **Resolved the "most expensive partial record"** — 13→**14 backed rows**; the geometry row stays marked only for its clashscore figures. Re-runnable via `analyze_xray_band_coverage.py` |
| 44 | (2026-08-07) | **P3b triage item #1** — re-based the geometry row's last partial figures (clashscore 4.26× null ratio, 17.2 starting) onto the **44 fresh named entries**: max null ratio **4.25×** (37 gate-valid, none ≥ 5×; the figure that set the gate reproduces on named data) and starting clashscore reaches **38.70** (the lost "not reproducible 17.2" exceeded). **No band value changed**; the geometry row **resolves** — 14→**15 backed**, 6→**5 marked**. Five partial rows remain (triage: 3 remeasure, 1 cite round 21, 1 retain) |
| 45 | (2026-08-07) | **P3b items #3 + #4** — re-based the vs-deposited geometry-% rows on the **42 named entries** (`round45_ids.json`). The run first uncovered an **oracle bug** (#281/#282: rotamer outlier % was read from `key_validation_stats`' `protein_sidechains`, a broader metric inconsistent with the report's per-residue `rota=OUTLIER` verdicts — fixed, tested). On the corrected instrument: **#3 favored resolves** (median \|Δ\| **0.000**, band holds — 15→**16 backed**), **#4 outlier half-resolves** — Ramachandran ≤ 0.11 pp, rotamer exact on **39/41**, but **14ZZ (1.52 pp)** and 2YOL (0.57) breach ±0.5 for an **altloc denominator** reason (rotamer names agree exactly). Per the decision rule a breached band is a finding, not a widen — #4's mark **stays** (#284); historical rotamer "0.34 pp" superseded. **5→4 marked** |
| 46 | (2026-08-07) | **#284 closed** — settled the vs-deposited band question round 45 opened. The raw favored-/rotamer-% bands are denominator-sensitive under altloc/completeness, so the **load-bearing check is now per-shared-residue classification agreement** (do the pipelines assign the same verdict to residues they both evaluate?), robust to the denominator difference; raw-% `\|Δ\|` demoted to reported diagnostics. Rotamer OUTLIER-verdict agreement **1.0000 on all 41** and Ramachandran verdict agreement (new `ramachandran_agreement`, tested, keyed with insertion code) **1.0000 on all 41**; the stricter rotamer-*name* agreement is 0.9919 on 15C8 (three insertion-code residues, different names, all Favored — named). **#4 outlier row resolves** — 16→**17 backed**, 4→**3 marked** |
| 47 | (2026-08-07) | **P3b item #5** — re-based the H-placement flip-set figure (`reduce` vs `mmtbx.reduce2`) on the fresh named 42-set (`round45_ids.json`), **not** the lost 17 (round 22: a subset re-run would mislead). Record committed. **P1 falsified**: the raw flip-disagreement rate is **10.95 %** (340/3105), above the ≤ 10 % band (worst 1TIJ 40 %, 25/41 models over 10 %). But **P3 confirmed** — **82 %** of disagreements (279/340) are residues `reduce` itself flagged **uncertain (X)**; the **genuine confident-conflict rate is 1.80 %**. Per the decision rule a breached band is a finding, not a widen — **mark stays**; the check is being switched to the confident-conflict rate (**#287**, approved), which round 48 applies. **No count change** (17 backed / 3 marked) |
| 48 | (2026-08-07) | **#287 closed** — made the flip-set check the **confident-conflict rate** (`reduce` confident F/K but `reduce2` disagrees; category X/C is one builder hedging, not conflict), raw rate demoted to diagnostic. **56/3105 = 1.80 %** on the named set, well under ≤ 10 % (band unchanged); four small-n models named over 10 % (1TIJ 20 %, …). Same shape as 45→46. **#5 H-placement resolves** — 17→**18 backed**, 3→**2 marked**; the two remaining marks (L-test, EM map-model) are both **RETAIN**, so **every resolvable partial record is now resolved**. `confident_conflicts()` tested |

Per-tolerance detail lives in the audit trails under `ref/research/tolerance_benchmark_*.md` and in
the re-runnable `scripts/bench_*.py`. It is deliberately **not** duplicated here — a backlog that
accumulates a changelog stops being readable as a backlog.

**Lessons live in [`ref/research/lessons.md`](ref/research/lessons.md)** — forty-eight rounds of
rules about how these tolerances fail, extracted so this file stays readable as a backlog (#65).
Record new ones there. The operative few, for anyone about to add a tolerance or widen a band:

- **A tolerance that has never been run is a hypothesis** — it lost 21 times out of 21 here. So is a
  "blocked" item, a measured band outside its measured regime, and a mechanism from two data points.
- **Register the prediction before the data.** It changed the outcome twice in round 15 alone.
- **Count what the clause can actually be broken by.** A one-sided band gains nothing from an
  improvement, so a round can raise every count in the tolerance row while strengthening nothing.
- **Check the clause's direction and shape before sizing it.** Two rounds were spent widening a band
  that was the wrong shape, and one reported improvements as breaches.
- **Record every entry, not the interesting ones.** A partial history does not just lose evidence, it
  biases the priors built on what survives — and four entries counted in the published totals are now
  unidentifiable. `scripts/validate.sh` gates that each round leaves its lesson here.
- **Check the power before hunting the mechanism.** Mechanism hunts are 0 for 3 here. Round 17's
  gate showed the phenomenon it was asked to explain (4/8 vs 1/9) is p = 0.131 — the question needed
  ~20 entries per arm and the rounds build 8.
- **Registering a prediction does not protect you from registering a bad test.** Round 17's P2 held
  as registered and was still wrong, because correlating a change against its own baseline is
  negatively biased by construction. Name the test's artefacts *in* the registration.
- **Confirm a suspected gap by running, not by reading.** Round 17 marked the DockQ row partial from
  a `limit=8` in the code; re-running showed the cap was never reached and the record was complete.
- **When the set grows, re-test every clause it backs.** Rounds 8/10/11 grew the §4 X-ray set
  19 → 37 while re-testing only two of its four clauses; the other two went untested from round 7
  until round 20 re-measured them (both held, both worst cases reproduced exactly).
- **A reproduced extreme is binding, not disposable.** 10BU sits 3.24× above every other
  `d_FSC_model` degradation, and round 17 proved it reproduces byte-identically — so the band stays
  where it is, precisely located rather than defended.
- **A prediction confirmed once describes the round that confirmed it.** Round 16 confirmed
  "largest degradation > 1.1 %"; round 19 registered the same threshold and falsified it.
- **Catching a class three times by luck is not a process.** Three aged figures (#72, #107, #113)
  were all found while reviewing something else. The signal to build the guard is the second
  recurrence, not the third.
- **Price the sampling before promising the test.** Round 22 called its successor test cheap because
  the selector was measurable before refinement. The candidates occur at 3.3 %, so screening 24 found
  none; three candidates need ~60–90 screened entries. A cheap selector is not a cheap experiment.
- **Whether a subset re-run helps depends on which members were lost.** The L-test's missing
  datasets were unremarkable; the flip-set row's are the zero-disagreement models, i.e. the
  denominator — re-running there manufactures a contradiction rather than resolving one.
- **A lost set can sometimes be replaced instead of recovered.** Round 18 proposed retiring the
  L-test's unverifiable half; round 21 re-measured it on a committed set instead, because a fix made
  three rounds earlier for an unrelated reason had made the inputs reproducible.
- **A relative gate needs bounds at both ends.** The 5× clashscore ratio was guarded above
  `pre ≈ 20` and not below; at `pre = 0` it is undefined and fires on a model well inside the
  absolute quality bar.
- **A gate that only compares numbers is defeated by a rewrite.** The staleness gate therefore fails
  in two ways: when the recomputed value differs, and when the quoted literal has *disappeared*. A
  reworded claim cannot be silently correct, because nothing verified it.
- **Review the code that makes the number, not only the number.** Twenty-four rounds re-read the
  registry adversarially; the scripts computing it had been read once each, when written. The first
  systematic pass found twelve defects, four high.
- **A guard must assert against the artefact it polices.** Round 24's nesting check compared four
  counts it derived *itself* from one file, and those inclusions hold by construction of the writer —
  so no run of the pipeline could fail it. If a check's inputs and expectations come from the same
  place, it is a tautology with a status field.
- **A default bucket makes "unrecognised" and "miscounted" independent.** 28 of 97 status values
  matched no declared predicate, and every denominator was still correct, because `attempted` is
  defined by subtraction. Right by luck of the default, and only until a status arrives that does not
  belong there.
- **Register the consequence you will check, not one you assume follows** — and a prediction
  resolvable only by a rule you invent afterwards was not a well-formed prediction. Round 26 wrote
  "0 rows outside the vocabulary, and if violated a denominator is wrong today" as one claim; they
  are two, and the second did not follow.

## Open

The live ledger, reconciled **2026-10-17** against `main` at **`d06475e`** (PR #905):
**13 open issues, 1 open PR** (#912), verified against API totals after its fresh adversarial review
(2026-10-18 UTC / 2026-10-17 local). Every open issue is listed below; the guide corrections are
unmerged work in PR #912. GitHub is authoritative for tracker state. Items marked
**proposed / no issue** are work recommendations, not delivered features or scheduled experiments.
Engineering and policy delivery do not complete a scientific measurement or authorize grading.

### Tracked on GitHub

- **Correct the scientific quality-reporting guide** — first recommended task, implemented on
  `correct-quality-reporting-2026-10-17` in PR #912, pending final checks and merge. The findings are
  [#907](https://github.com/CultureBotAI/protstruct_review/issues/907) (P1, confidence conversion
  and interpretation), [#908](https://github.com/CultureBotAI/protstruct_review/issues/908)
  (P1, unsupported quality/refinement verdicts),
  [#909](https://github.com/CultureBotAI/protstruct_review/issues/909) (P1, tool independence,
  literature and 1SAR coverage), and
  [#910](https://github.com/CultureBotAI/protstruct_review/issues/910) (P2, schema/emitter instructions).
  The fresh review added [#913](https://github.com/CultureBotAI/protstruct_review/issues/913)
  (P2, residual summary-routing and T07/T17 ensemble instructions), corrected in the same PR.
  The correction aligns [`quality_reporting.md`](ref/quality_reporting.md) and directly repeated
  descriptions with primary sources and the executable contract. It distinguishes measurement
  agreement, final-model quality, and benefit over the actual starting model; it retains 1SAR's
  missing evidence and points grading decisions to applicable registry bindings. Next: complete
  independent review and the required gates, then merge with approval. These documentation issues
  require no scientific rerun. See the
  [dated audit](ref/research/quality_reporting_review_2026-10-17.md).
- **Audit the ProSMART Ramachandran-Z recommendation**
  ([#911](https://github.com/CultureBotAI/protstruct_review/issues/911), P1; newly tracked).
  `REC_T05_rama_z_score_top_performing` and two active assumptions describe a ProSMART Rama-Z
  capability that the cited structural-comparison scores and retained 1SAR correction do not
  establish. Next: verify the exact producer/output identity and supersede unsupported registry
  descriptions through dated, append-only recommendations/assumptions. Preserve frozen snapshots.
  The guide correction limits its claims to supported observations; this registry audit remains
  separate work and must precede reliance on the disputed Rama-Z recommendation.
- **Standalone dictionary benchmark — incomplete and intentionally stopped**
  ([#799](https://github.com/CultureBotAI/protstruct_review/issues/799), P1). PR #811 delivered explicit
  dictionary loading and error retention; later evidence/admission work culminated in PR #875's
  preserved 24MR canary. Native Reduce returned a nonzero status and the attempt was rejected before
  Probe scoring. Its coordinate output is failed-attempt evidence, not an admitted hydrogen build.
  The [2026-09-28 disposition](https://github.com/CultureBotAI/protstruct_review/issues/799#issuecomment-5875777839)
  keeps #799 and #876 open and hands off the failure: **no retry, diagnostic execution, installed-tool
  modification, or cohort expansion is queued**. What remains is admitted standalone-leg evidence
  and scientific reconciliation, or an explicit scope disposition. A future restart first needs the
  separately reviewed protocol below. See the
  [execution report](ref/research/standalone_dictionary_canary_execution_2026-09-28.md) and
  [stopped campaign record](data/coscientists/openscientist/retained_799_campaign_2026-09-28/stopped-after-canary.json).
- **Resolve native Reduce status ambiguity before any #799 restart**
  ([#876](https://github.com/CultureBotAI/protstruct_review/issues/876), P2; prerequisite to #799).
  Installed-source inspection found a status path shared by successful zero-change optimization and
  failed/abandoned optimization; the quiet canary does not establish which occurred. Do not accept
  status 1 merely because coordinates exist, or claim that it proves abandonment. The next possible
  step is a bounded diagnostic/adapter **design** retaining discriminating native evidence, followed
  by separate review and prospective registration before execution into a fresh destination.
  Keep the original failed bundle and zero-status admission rule unchanged. The
  [latest disposition](https://github.com/CultureBotAI/protstruct_review/issues/876#issuecomment-5875778892)
  explicitly preserves the stop; designing a restart is not permission to run it.
- **T15 — define an input-based comparison population**
  ([#765](https://github.com/CultureBotAI/protstruct_review/issues/765), P2; calibration remains
  non-gradeable). PR #831 retained stopped attempts; PR #871 delivered failed-pair evidence and a
  [bounded 1BNI diagnostic](ref/research/t15_failed_attempt_diagnostic_execution_2026-09-28.md), closing
  #829. It did not recover discarded earlier streams, complete the cohort, or authorize resumption.
  The [2026-09-28 design disposition](https://github.com/CultureBotAI/protstruct_review/issues/765#issuecomment-5875812783)
  keeps the original exact-domain registration stopped. Next: freeze eligibility from input coordinates
  before assignment, first-model extraction, whole-context alternate-conformer handling, modified
  residues, chain/TER/gap identity, exact inputs/versions, retention, and stop rules. Preserve supported
  structural context and require both tools to assign every eligible residue; do not score an output
  intersection, convert missing states to coil, or pool successful prefixes. Review the design and
  hermetic negative tests before a new result-free protocol and fresh-destination canary. The current
  public wrapper's exact-full-domain contract stays intact. The prospective #874 / PR #877 native-state
  admission fix and descriptive #766 ledger do not supply a calibration. No execution is queued.
- **Decompose the matched-convention clashscore residual**
  ([#790](https://github.com/CultureBotAI/protstruct_review/issues/790), P2 — optional, unperformed,
  licensed PHENIX). Separate flip policy and dictionary loading before comparing counters on the same
  hydrogen-built coordinates. This needs the two execution prerequisites below and valid native-status
  admission for the selected builder path; #799's rejected output cannot substitute. Next: a bounded
  design and reviewed adapters before registration/execution. Completion means the residual is
  decomposed or bounded with retained evidence and dated scientific reconciliation. This optional
  causal study need not block the general refinement-assessment workflow.
- **Bound nested PHENIX helper processes for #790**
  ([#872](https://github.com/CultureBotAI/protstruct_review/issues/872), P2 execution prerequisite).
  The proposed outer process-group bound does not cover PHENIX helpers that detach into their own
  groups. Before that study, use explicit shell-free recording at both Reduce and Probe boundaries,
  preserving the owned group, actual arguments, statuses, and streams. Verify timeout cleanup and
  exact payload behavior hermetically; retain scientific scoring semantics and label the transport
  adaptation. The delivered generic EntrySandbox cleanup does not resolve detached helper groups.
- **Retain native Reduce status through the PHENIX dispatcher for #790**
  ([#873](https://github.com/CultureBotAI/protstruct_review/issues/873), P2 execution prerequisite).
  Dispatcher success can mask native failure. Record the native executable's status and streams with
  the dispatcher's exact injected flags, and add a hermetic native-nonzero regression before a builder
  canary. Label the adaptation and preserve installed tools. This is specific to the PHENIX study;
  the standalone-only #799 path does not use that dispatcher.
- **P3a — cross-version PHENIX reproducibility (round 43)**
  ([#760](https://github.com/CultureBotAI/protstruct_review/issues/760), P2, access-blocked).
  The remaining item of the [Codex action plan](ref/research/codex_review_action_plan.md), registered in
  [round 43](ref/research/tolerance_benchmark_round43_preregistration.md) (PR #273). The recorded unblock
  condition is a second, newer licensed and installed PHENIX build; availability was not re-inventoried
  in this reconciliation. **#777 and #816 are delivered**, through PRs #818/#823, per the
  [engineering checkpoint](https://github.com/CultureBotAI/protstruct_review/issues/760#issuecomment-5863595057).
  Once access is available, preserve the registered design and its baseline/fetch amendments; canary
  one entry using the content/build-bound runners and isolated version probing in
  [oracle guidance](ref/oracle_tools.md). Verify invocation, measured build, input hashes, return status,
  and product hashes before expansion. A path-version hint alone cannot authenticate a run; unversioned
  in-place library changes still require a fresh cache. Lack of access does not retire this registration
  under [stopping criteria](ref/research/stopping_criteria.md), and no cross-version result is claimed.

### Delivered prerequisites (not open reruns)

- **Project goals and backlog updates:** PR #905 (`d06475e`) delivered the two goals in
  `CLAUDE.md`, `.claude/skills/reconcile-next-tasks/SKILL.md`, and the preceding complete issue
  reconciliation. Use that existing skill to update this file; no duplicate update skill is needed.
  The same PR resolved #906 by suppressing automatic maintenance during disposable Git-fixture
  construction and adding a Trace2 regression; this is a test-fixture fix, not scientific evidence.
- **#762 workflow safeguards:** PR #820 (`849535c`) delivered the locked Python 3.12
  benchmark-extra gate, complete-queue checks, read-only review and reviewed-head
  CI/closure safeguards.
- **#777 cache integrity / #816 version identity:** PR #818 (`15edb68`) and runtime follow-up
  PR #823 (`fbacb66`) delivered content/build-bound caches and isolation from inherited PHENIX version
  overrides. Cross-version science and the installation-access blocker remain #760.
- **#785 Gemmi capability correction:** PR #832 (`f6e8722`) delivered the catalog
  and dated successor recommendations with scoped capability claims.
- **#798 version policy / #809 flips:** PR #835 (`fec9334`) pins both clashscore
  rows to benchmarked versions and suspends the unsupported T14 flip grading rule.
  Correctly attributed historical flip numbers remain informational.
- **#764 and #786 scientific policy:** PR #837 (`5ef268c`) keeps missing deposited
  R-free unevaluable, rejects unexplained usable-input observation loss, and adopts
  ≥0.99 only for the benchmarked PHENIX 2.0-5936/wwPDB shared-residue comparison
  with insertion-code keys. It does not authorize standalone MolProbity grading.
- **#799 engineering and failure handoff:** PR #811 (`df011cc`) delivered dictionary-loading/error
  checks; PRs #849 (`2626fc8`), #866 (`9f25a7b`), #867 (`c2d9e08`), and #875 (`f6f8b39`) delivered
  the standalone evidence driver, flip recount admission, owned-process cleanup, component inventories,
  and retained stopped canary. These are execution/provenance deliveries; #799 remains scientifically
  incomplete and #876 blocks any restart.
- **#767 T13 operational acceptance:** PR #831 retains the installed-CCP4
  invocation, real logs, output hashes and independent replay checks for one
  merged-input canary. This does not validate unmerged-data handling, supply a
  paired xtriage comparison, or establish a model-quality verdict. Its stopped
  T15 rerun remains separately tracked above.
- **#829 T15 failure retention / #874 native-state admission:** PR #871 (`79858e2`) retained the
  rejected 1BNI pair and diagnostic; PR #877 (`6dc9b94`) rejects unavailable/unknown Biotite states
  instead of fabricating coil. Both issues are closed. Neither completes or recalibrates #765.
- **#766 descriptive evidence ledger:** PR #842 (`246eb8c`) delivered
  `ref/threshold_evidence_status.yaml`, its generated summaries and guard. It separates scoped policy
  and evidence states in registry §3/§4; it does not independently validate thresholds or authorize grading.
- **Storage inventory and retention review:** PR #878 (`8aef21c`) delivered
  `scripts/inventory_storage.py` and `.claude/skills/review-data-retention/SKILL.md`. This is a bounded
  inventory/review capability, not completed cleanup or permission to remove scientific evidence.
- **Earlier reconciliation:** PR #768 fixed wording issues #769–#773 and #778–#780.

### Recommended next directions

Use the two [project goals](CLAUDE.md#project-goals) together: assess refinement results and explain
the landscape of tools and measurements. Direction 1 is now tracked and under correction;
directions 2 and 3 remain **proposed / no issue** and do not schedule experiments.

1. **Finish the scientific-guide correction** (#907–#910 and #913, PR #912, tracked above). The revision covers
   confidence, contextual metric interpretation, tool capabilities and independence, retained 1SAR
   limits, and actual reporting support. **Done when:** the reviewed correction is merged and the
   guide and directly repeated descriptions agree with canonical sources without competing grading
   thresholds. Keep the separately filed ProSMART recommendation audit (#911) visible and resolve it
   before using that capability. This prepares the next deliverable; it does not itself implement a
   reusable assessment.
2. **Deliver a reusable before/after refinement assessment.** Build on the existing negative-control
   and agent-evaluation work with one fully retained X-ray case. Preserve exact starting/final model
   identities, observations/free flags, selections, and tool versions; report paired experimental-fit,
   geometry, structural-change, and important-site measurements with independent checks. **Done when:**
   a reproducible human-readable comparison and EvaluationRun/QDS records separately explain
   measurement agreement, final-model quality, and benefit over the actual input, including missing,
   conflicting, and inapplicable evidence. Exercise unchanged, damaged, and recovered controls under
   an appropriate reviewed protocol. New verdicts require applicable registry bindings; unsupported
   comparisons remain informational. Use 1SAR as a missing-artifact case, not proof of an adjudicated
   final round whose coordinates are absent. Extend to cryo-EM after the first workflow is usable.
3. **Make a question-based tools-and-measurements guide.** Reuse `ref/catalog.yaml`,
   `ref/tool_recommendations.yaml`, `ref/tool_assumptions.yaml`, and the scoped evidence ledger.
   Organize experimental fit, geometry, structural change, sites/interfaces, prediction confidence,
   and classification by the question each answers. **Done when:** users can determine required inputs,
   modality, scope, reference dependence, implementation dependencies, available integrations, and
   grading eligibility for a proposed assessment. Distinguish documented capability, runnable
   integration, retained independent evidence, and calibrated interpretation; shared code or separate
   executable names alone do not establish independence.

For the tracked benchmark work, prioritize #876's diagnostic **design** and #765's input-population
design when their measurements are needed. Resolve #872/#873 before scheduling optional #790; retain
#760 as access-blocked. These dependencies do not prevent the guide and general assessment work.
Apply the existing [stopping criteria](ref/research/stopping_criteria.md) when choosing another
benchmark or assurance pass; a further audit is a deliberate scoped investment, not the default task.

### Open questions and optional work (no issue)

- **Is an R-free cross-tool offset band wanted?** Undecided as of 2026-09-26. #576 and #669 closed with
  only the scoping half done: the §3 agreement row governs directly summed R-work, while R-free offsets
  and `gemmi_rfactor.py`'s bin-rescaled estimator stay informational "pending matched benchmarks", so T03
  has no gradeable same-model cross-tool R-free offset band. (Rule 1's ±0.02 comparison against the
  deposited value and a REFMAC5 re-refinement is a separate, graded check.) If wanted, it is a preregistered PHENIX benchmark on the
  r_offset set; if not, record it as intentional scope.
- **Broader partial-record ledger coverage** — #293 deferred the original design question, but PR #842
  has since delivered the machine-readable §3/§4 descriptive ledger and generated summary above.
  Reuse that source. Decide whether coverage outside those registry sections is needed for a concrete
  assessment; any broader ledger remains an optional design task, not a missing implementation of the
  existing scoped inventory.
- **A same-subject 1SAR reassessment** — optional and partly blocked. Two different gaps: a same-model
  rerun with retained raw output would close the missing raw-output gap (M_001–M_003) but stays
  cctbx-only and informational, so it closes **no** waiver. Closing the 11 cctbx-only waivers needs
  retained **independent** outputs, per the sheet's `cross_tool_waivers`: a non-cctbx starting-to-packaged
  R-free delta with matched reflections, free flags and estimator (WAIVER_001); standalone MolProbity
  classifiers and composite on the packaged model (002–006); an independent completeness calculation on the
  pinned MTZ (008); and CCP4 EDSTATS RSZD/RSZO plus a matched limiting-radius RSCC comparison for the three
  ligand sites (009–011). No retained independent implementation of the Holton energy ratio exists, so
  nothing currently closes WAIVER_007. Adjudicating the reported round-7 model needs coordinates that were never retained (see
  [Not actionable](#not-actionable-in-this-repo-listed-so-the-gaps-are-explained-not-recommended)). Worth
  doing only if 1SAR becomes load-bearing.
- **T10 ligand assessment** — no registered ligand-specific pose criterion (pose RMSD stays informational,
  #723), and no script runs EDSTATS although the CCP4 install ships it and the catalog registers it for
  T05/T06/T10. Low priority unless T10 becomes a regression target.

### History: round 21 closed both remaining items

The **L-test** was re-measured rather than retired. Round 18 had proposed dropping its unverifiable
figures; round 19 spotted that the inputs were already committed, and round 21 ran it: Wilson B's
committed 24-dataset set regenerates L-test inputs, giving a measurement anyone can reproduce from a
clean checkout. It returns the historical figures — median |Δ| 0.0065 vs 0.006, 22/24 vs 25/27
inside ±0.02, max 0.047 vs 0.047, twin call unanimous both times — but that is **reproducibility, not
corroboration**: the 24 is almost certainly a *subset* of the 27, so the same structures went through
the same deterministic programs. Both breaching datasets were already named in the old trail, which
turns out to be structural rather than lucky — a worst-N table contains every breach whenever
breaches ≤ N. The original 27 remain unreconstructable; what changed is that anyone can now
regenerate the numbers the row quotes.

The **EM benchmark** now appends each entry's result as it completes, on all five exit paths. The
last all-or-nothing step in the pipeline is gone — a crash nine hours into a batch no longer takes
the completed entries with it. Tested by simulating a crash at entry 3 of 5.

### Tolerance-series status

**The two bounded measurement projects that dominated this section since round 22 are now done.** What
was "state as of round 27" — a menu of three candidates — has resolved into rounds 40–42:

- **Crossing-quality hypothesis (#224)** — **answered by round 40's determinacy redesign.** The ratio
  screen was 2-point leverage (Spearman ρ with |excursion| collapses to **+0.049** without the two
  extremes); a perturbation-recross *determinacy* measure predicts the excursion robustly (ρ **+0.792**
  extremes-removed, LOO 0.75–0.85) and independent of fit (partial **+0.773**). Resolved on 19 existing
  labels — no 50 GB screen. **#224 closed**, #234/#258 superseded, the §4 caveat re-based.
- **Fresh low-resolution X-ray measurement (#225)** — **done across rounds 37/38/41/42.** Rounds
  37/38/41 built **44 fresh named entries**; round 42 (#269) re-based the §4 `d_min ≥ 2.5 Å` X-ray band
  widths off their lost maxima onto **coverage bounds** over those 44 (Cα **0.35 → 0.25 Å**; favored kept
  at −6 pp, re-justified as ~98 % coverage), resolving the "most expensive partial record." **#225/#269
  closed.**

**The tail of the Codex conceptual-review action plan** (reconciled 2026-09-26;
[`ref/research/codex_review_action_plan.md`](ref/research/codex_review_action_plan.md)): **P1**
shipped (#271); **P2** done (#272); **P3b** done through round 48 (every resolvable partial record
resolved at the time — see the T15 requalification above); **P3c** done (#291 — the round-42 lognormal
is guarded, not assumed); **P4 done** — [#292](https://github.com/CultureBotAI/protstruct_review/issues/292)
(stopping/consolidation criteria, `ref/research/stopping_criteria.md`, closed 2026-08-26) and
[#293](https://github.com/CultureBotAI/protstruct_review/issues/293) (gate consolidation, PRs #454, #511,
#524 and #532, closed 2026-08-30). **Only P3a remains**, blocked on a second PHENIX build
([#760](https://github.com/CultureBotAI/protstruct_review/issues/760), in the ledger above). A **second, code-level Codex review
(2026-08-12) was fully remediated** in the negative-control track above (PRs #313–#332), including
two invariants the whole repo now enforces: the trust model as a gate (validate 3c) and
negative-control record reconciliation (3b).

**2026-10-15 scope note:** the dated action-plan completion above does not settle the subsequently
requalified T15 calibration or T14 independent flip-grading evidence. Their current limits and
related #765/#799 work remain in [Open](#open).

The one **unbounded** option that persists from the old menu: **another `scripts/` audit pass with a
new lens** — it has found defects every time (12, then 2, then 5), the lens must differ each pass, and
there is no defined endpoint. Cheap per pass, unbounded in total; picking it is a deliberate choice to
spend a round on assurance rather than on measurement.

#### [x] Crossing-quality hypothesis — answered (round 40, #224)

Rounds 23–36 priced and screened this at the 1.074 fence and could not power it (0–1 candidate per
batch, ~50 GB for three). Round 40 stopped screening for the rare event and **measured the mechanism
directly** instead: crossing determinacy (perturbation-recross) predicts the excursion where the ratio
was 2-point leverage, so the §4 caveat is re-based and #224 is closed without the expensive screen. The
detail lives in `ref/research/tolerance_benchmark_round40.md` and the memo #258.

### Standing risk, not tasks

Current policy/evidence states are in the [generated inventory above](#where-the-tolerance-work-stands)
and `ref/threshold_evidence_status.yaml`. The following round-by-round account is historical, not
an independent-calibration certificate.

- **The historical inventory reported two `⚠ partial record` rows, both RETAIN** (rounds 42/44 resolved the ΔRMSD and
  geometry rows; rounds 45–46 resolved both vs-deposited geometry-% rows, #284; rounds 47–48 resolved the
  H-placement flip-set row, #287). The two that remain — #2 L-test and #6 EM map-model — are RETAIN
  (honest disclosed limits, not resolvable by re-measurement). That inventory is not current grading
  authority: #613 requalified T15 (#765/#766), and #809 suspends flip grading because the retained
  producer pair does not establish the claimed independent benchmark. Round 21
  showed one route
  out (re-measure on a committed subset) and round 22 showed its limit: **it works only when the lost
  members were unremarkable.** For the flip-set row it is established *not* to work — the five missing
  models are the zero-disagreement ones, so a 12-model re-run would report a higher rate than the
  published 7.5 % purely because the denominator shrank. Round 42 showed a *third* route for a band
  width: retire the lost maximum as the wrong estimator and re-base on a coverage bound over named data.
  Round 45 showed a *fourth* outcome: re-measuring can resolve the **record** (name the set, commit
  per-entry values) yet surface that the **band itself** fails on named data — the rotamer ±0.5 pp check
  is denominator-sensitive under altlocs. Round 46 then showed the *fifth*: when the raw band is the
  wrong instrument, **change what the check measures** — per-shared-residue classification agreement is
  robust to the denominator and resolved #4 (#284 closed). Round 47 hit that same shape on #5: the
  flip-set re-measure committed the record but the **raw** ≤ 10 % band breached at 10.95 % — 82 % of it
  one builder's own uncertain (X) calls, genuine confident-conflict only 1.80 % — so round 48 switched
  the check to the confident-conflict rate (#287), resolving #5. The two remaining marks, #2 L-test and
  #6 EM map-model, are RETAIN. The former resolved-all claim is superseded by T15's denominator gap
  (#765/#766) and the T14 producer-attribution/grading correction (#809).
  Ask what the lost members contributed before trying to re-measure.
- **The §4 X-ray band widths no longer rest on lost entries** (was a standing risk through round 41).
  Round 42 re-based both `d_min ≥ 2.5 Å` widths onto coverage bounds over the 44 fresh named entries
  (rounds 37/38/41), so the widths are now fully-backed, re-runnable figures. The two lost maxima
  (0.285 Å, 5.26 pp) are retired as the wrong target, not mourned as lost data.
- **The audit of `scripts/` is a lower bound, not a total.** Round 25 found 12 defects in the first
  systematic pass; round 26 found 2 more with a *different lens*, and a sixth pass — enumerating each
  guard's input space rather than reading — found 5 more in code the earlier passes had just
  reviewed. Reading finds the defect you can imagine. Nothing establishes where the bottom is, and
  the same argument applies to every further pass.
- **Two of round 26's guards are heuristics with stated residual risk.** `check_round_figures.py`
  decides "is this markdown a quotation" by inspecting a match's immediate context; it handles every
  construct these documents currently use and may be wrong on one nobody has written yet. And its
  findings record is a *snapshot* — any round that files an issue after refreshing it goes stale, as
  round 26 did three times. Both are recorded in that round's scope limits rather than implied closed.
- **`d_FSC_model` still rests on one verified extreme.** 10BU is an outlier by every criterion tried — **3.24×
  the next-largest degradation**, which needs no distributional assumption, and above the 1.5 × IQR
  fence under all three quartile conventions (3.017 / 2.370 / 1.724, on n = 8). It also reproduces
  byte-identically. Round 40 answered whether it is explicable: the excursion is **real model
  movement, not estimator jitter** (a controlled perturbation moves the crossing 2–2900× less than
  refinement did), and crossing determinacy predicts excursion magnitude — so 10BU's outlier status is
  genuine, and the band stays where it is.
- **Contract-4 assurance is pinned to one emitter hash.** Every internal review round and the first three
  external passes on #754 found new defects (#732–#759) before the fourth approved
  `scripts/qds_emit_contract_v4.py` at `5bcf2cb6`. That approval does not cover later edits to the emitter
  or to `scripts/qds_correction_projection.py`, which it imports; treat any change to either as needing a
  fresh adversarial review.
- **Some September guards are lexical.** The density-guidance drift guard (#726) catches the exact retired
  RSCC/RSR, water and ligand-pose wording, not paraphrases of it. Model subjects are path labels
  (`artifact:<run>#data/1sar_final.pdb`) that the gates check for consistency across rows; only T13
  datasets are bound to a content digest (`mtz:sha256:…`). So "the measured model is the claimed model" —
  the question the 1SAR packaging error raised — rests on the skill and the records, not on a gate that
  hashes coordinates. Review for both by reading.

## Not actionable in this repo (listed so the gaps are explained, not recommended)

- **ctruncate Wilson-plot fit range** (residual confound from #19): the fit ranges were not matched
  because ctruncate does not report the range it used, so the measured 13.7 % is an upper bound on
  estimator divergence. Needs a ctruncate that reports or accepts an explicit range. *Partial local
  probe:* re-run `phenix.xtriage` with a restricted low-resolution cutoff to bound how much of the
  gap is range choice — worth doing only if the Wilson-B tolerance becomes load-bearing.
- **L-test matched resolution range**: the same shape, and confirmed unachievable — ctruncate
  restricts the L-test by a median 0.46 Å and its usage line exposes no resolution flag. Recorded as
  a caveat on the tolerance rather than a gate.
- **Fragment guard is `SSBOND`-only** (from #25): a cleaved molecule held together by something other
  than a disulfide, or an entry omitting `SSBOND` records, would not be caught. Extending it needs
  RCSB entity annotations rather than the coordinate file alone.
- **T16 BSA covers protein–protein only**: nucleic-acid and protein–ligand interfaces are out of
  scope for the tolerance as written (protein-only atom selection).
- **T17 independent NMR oracle**: no local wwPDB NMR validation / PROCHECK-NMR / RPF install;
  deposited validation reports are fetched per entry. A deliberate gap in `ref/oracle_tools.md`.
- **ChimeraX (T01, T08), MoRDa (T09), STRIDE (T15)**: recorded deliberate gaps; install only if those
  tasks become regression targets. **STRIDE is worth more now than before**: it is a third SS
  assigner, and round 4 could not tell whether DSSP or P-SEA is the outlier when they disagree.
- **The reported 1SAR round-7 model is not retained.** The co-scientist archive holds the round-4 output
  as `data/1sar_final.pdb`; the round-7 coordinates and their R-factors exist only in the agent's log, so
  the report's final model cannot be adjudicated here. Recovery needs the upstream artefact store.
- **The OpenScientist harness prompt mislabels 1SAR** as staphylococcal nuclease and primes a Ca²⁺ site
  (archive `claude_iterations.log`). The fix belongs to the external harness; do not reuse this artefact as
  a benchmark until it is fixed there.
- **1SAR T03 against its deposition**: the 1990 entry has no free R (`FREE R VALUE : NULL`), and no
  unmerged intensities were retained, so the deposition-relative T03 clause and the aimless merging
  diagnostics cannot be evaluated from retained data (#764 covers the rubric's general definition).
- **PHENIX 2.0-5936's `phenix.structure_comparison` is GUI/project-bound**: a headless run exits 1 with no
  report, so the PHENIX side of T02 cannot be automated and unattended runs record it as unmeasured
  (`ref/driving_example_T02.md`).

## Other tracked work

- **GitHub #2** *(closed — informational)*: driving examples complete (17/17).
- **GitHub #3** *(closed — historical implementation milestone)*: T15/T16/T17 wrappers delivered.
  Current T15 population/calibration limits and stopped execution are tracked under #765 in [Open](#open);
  the historical milestone does not settle them.
- **GitHub #18, #19** *(closed 2026-07-25, PR #24)*: the two provisional tolerances.
- **GitHub #25, #26, #27** *(closed 2026-07-25, PR #24)*: intramolecular fragment pairs counted as
  interfaces, cache written into the working tree, multi-block sf-cifs.
- **GitHub #29, #30, #31** *(closed 2026-07-26, PR #28)*: two-block `model_vs_data` logs and outlier
  asymmetry, the near-identical-pairs weakness in the CA RMSD floor, dead code.
- **GitHub #33, #34, #35** *(closed 2026-07-26, PR #32)*: subset-dependent library share,
  unknown-vs-mismatched L-test ranges, and the het-dictionary difference that exposed a wrong
  H-count tolerance.
- **GitHub #37, #38** *(closed 2026-07-26, PR #36)*: the Ramachandran 0.00-vs-0.00 evidence base, and
  the SS-agreement metric being degenerate at the bad end.
- **GitHub #57** *(closed 2026-07-28, PR #56)*: a self-review finding — the round-13 write-up claimed
  a "fifth consecutive round" of thinnest-band failures when the record is 3 breaks in 4 widenings,
  round 12 having held. Logged because the correction changed a stated rule of thumb, not just a
  number: the heuristic is 3 for 4, and its one miss was a band of the wrong *shape* rather than the
  wrong size — a failure mode headroom does not track.
- **GitHub #59** *(closed 2026-07-28, PR #58)*: the round-11 "below 1.2× headroom, treat as already
  broken" rule, back-tested and found not to hold — breaks at 1.15×, 1.44× and 1.55× while the one
  band that survived two rounds of set growth sat at 1.26×. Logged because it retired a *lesson*, not
  a tolerance: the rule was generalised from one observation and never re-tested.
- **GitHub #61** *(closed 2026-07-28, PR #60)*: degradation frequency and magnitude conflated, which
  had inverted a widening recommendation. Degradation is more frequent below 3.0 Å (4/8 vs 5/14) but
  3–7× larger above it; only magnitude re-fits a band. Round 15 then confirmed the corrected version.
- **GitHub #63** *(closed 2026-07-29, PR #62)*: "14 CC_mask degradations" stated as a count when it is
  a lower bound (14–19) — round 13 published only its branch minimum. Logged because the degradation
  count is now the headline evidence measure, so an unverifiable figure there is not an improvement on
  an inflated one.
- **Rounds 17–18 self-corrections** *(no issue raised; recorded in the round trails and PR #69)*.
  Three, all of the same family as #57/#59/#61/#63 — a published figure that did not survive being
  checked:
  - **`d_FSC_model`'s worst degradation is +4.786 %, not +4.787 %.** The old value came from
    recomputing the ratio out of intermediates already rounded to 4 dp during round 16's backfill.
    Logged because it is *the* number setting the thinnest band in the file, and it was not the
    number the pipeline produces. Headroom 1.0445× → 1.0448×; no verdict changed.
  - **Round 17's DockQ "partial record" mark was wrong**, and round 18 withdrew it. The audit
    inferred unpublished mappings from a `limit=8` in the code; re-running showed the cap was never
    reached. Logged because it retired an *audit finding* rather than a tolerance — the first time
    this series over-reported a gap rather than under-reporting one.
  - **Round 17's row-count correction was itself a miscount.** It reported "20 rows, not 21" and
    blamed the shared map-model row; §3+§4 really do hold 21 rows, and the exception is the
    `[literature]` absolute-floors row. Reconciled in round 18: **21 rows, 20 `[benchmark]`, 21
    benchmarked tolerances.** Logged because the wrong explanation had already propagated into four
    files before it was caught.
