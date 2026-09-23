# Open-issue review — 2026-09-23

## Revision and scope

Applied the requested `review-open-issues` skill to this structural-biology
repository, not to the GenomeExplainer-specific paths in its template. Read every
body and comment in the complete initial queue: **15 issues**, matching GitHub's
GraphQL `totalCount`. Local HEAD and GitHub main both resolve to
`c71682dd94d482f8f1d4882d238add0776ae5c3d`; there are no open PRs. The working tree
is dirty on `qds-correction-contract-2026-09-23`: contract-4 implementation,
schema/generated models, guard/test integration, and audit documentation are
uncommitted. These changes are **not fixes delivered on main**.

The review filed #738 and #739; a subsequent contract-4 review filed #740 and #741,
bringing the first checkpoint queue to **19**. Continued rounds 4–5 filed #742–746.
The subsequent retained-data audit filed #747/#748, then integration preparation
independently reproduced and filed #749. Its local fix exposed the integrity-checker
integration defect #750 in the full gate. That checkpoint had **28** open issues.
The subsequent complete-queue review read all 29 bodies/comments after #751;
real-record acceptance then filed #752/#753 before their fixes. The latest queue
has **31** open issues, matching GraphQL, with the same main revision and no open
PRs, rechecked against every issue body/comment at September 23 18:31 UTC.
No issue was closed, no
PR merged, and no branch deleted during this review.

## Already delivered

- PR #726 is merged as `44e43444faebf6a42f1eca3b36908c9aae4cbede`: live density
  guidance and T13 generation corrected. This does not repair frozen 1SAR rows.
- PR #731 is merged as `c71682dd94d482f8f1d4882d238add0776ae5c3d`: corrected active
  synthetic fixture and tests. #691 and #729 are closed. Historical synthetic
  carriers remain frozen; the real-1SAR corrections are a separate deliverable.
- PR #719 is merged as `af81a267f24c32bb19ddbf388289cd4fa326bb82`: explicitly
  partial T15/T16 sheet, not a cumulative correction. The deck coverage correction
  was already delivered in `5c96e01` (#689); `git blame main` of slide 6 establishes
  that provenance rather than attributing it to the later audit checkpoint.
- GitHub merge metadata confirms these merges. Exact `git ls-remote --heads`
  queries show the #726/#731 remote branches are gone; neither local branch is
  present. Stale local remote-tracking refs do not mean remote branches remain.
- The originally requested `qds-integrity-1sar-2026-09-21` branch was merged by
  PR #613 on September 22 at 10:33:10 UTC, commit
  `c32bb0153c971cf99854134e2fe3daad9a503e01`. Exact remote-head and complete local-ref
  checks confirm that branch is already gone. No additional deletion is needed.

## Ranked current-main remainders

| Priority | Issue | Disposition and specific evidence | Minimum remaining action |
| --- | --- | --- | --- |
| P1 | #610 | Still open on main. Its assumption-only suppression cannot correct all measurement, structured-row, headline, registry and coverage outputs. Contract 4 is only in the working tree. | Finish all-builder correction semantics, review and merge; demonstrate them with the real dated correction. |
| P1 | #725 | Still open on main. Retained v3 uses model-subject admission; honest MTZ-subject T13 rows need an explicit association. The new adapter's `_dataset_associations` and `_builders` address this locally. | Validate exact retained dataset bytes/ownership and unrelated-data exclusion; include real cumulative 1SAR acceptance coverage. |
| P1 | #585 | Partly fixed: deck framing changed, but the September 7 QDS still names only its own Eval and omits typed partial context. Its complete mapping has no `coverage_scope`, `scope_notes` or current headline (`QDS_1sar_cdba2c07_2026-09-07.yaml`, lines 2–21 and full parsed mapping). | Publish a discoverable dated, standalone-safe correction; the September 22 partial T15/T16 sheet is not that correction. |
| P1 | #692 | Still reproducible. April Eval lines 979–1015 label ProSMART displacement 0.5262 as `T05_per_residue_rsrz`, apply an unregistered cutoff and claim Ramachandran confirmation. Catalog lines 1613–1617 define RSRZ as a density R-factor Z-score. | Correct measurement identity/status, nested interpretation and propagated pairwise prose without rewriting frozen sources. |
| P1 | #693 | Still reproducible. April Eval lines 1160–1276 assign canonical CheckMyMetal provenance to the local heuristic and overstate Mg exclusion/Ca identity. `checkmymetal_local.py:1–8` disclaims canonical-service provenance; lines 104–129 show the limited screen. | Correct all affected ion rows and interpretations; retain uncertainty and remove wrong-protein biological reasoning. |
| P1 | #694 | Live guidance fixed, historical record not corrected. April Eval lines 1027–1032 grade a fixed ligand RSCC bar; 1154–1159 grade a water distribution; 1794–1821 promote low RSCC to outlier labels. The registry at `thresholds_and_standards.md:76` rejects that significance interpretation. | Correct both scalar verdicts and structured water/ligand conclusions. Removing one criterion field is insufficient. |
| P1 | #591 | Partly stale: enum, live T13 and active synthetic fixture are fixed. April ion rows still carry criteria on informational statuses (1173–1174, 1235–1236); the ice row does too (1348–1349). | Resolve criterion applicability and evidence first; do not mechanically relabel unsupported tests as failures. |
| P2 | #695 | Still reproducible. April Eval lines 2146–2170 converts similarity to `improved` and also repeats the ProSMART overclaim. | Replace directional improvement with preservation/equivalence unless separate directional quality evidence supports it. |
| P2 | #580 | Original self-grading harm mitigated; raw-evidence reproducibility remains unresolved. September narrative lines 141–146 expressly acknowledges absent oracle output and absent final coordinates. | Retained rerun evidence **or** durable typed unavailable-evidence treatment. Do not imply a rerun occurred. |
| P2 | #739 | New active-main remainder after #729. Schema lines 179–180, generated models lines 382–384 and threshold registry line 56 equate outside-Favored with rotamer outliers; active tool-assumption prose lines 147–159 distinguishes Allowed from OUTLIER. | Correct both canonical definitions, regenerate models and regression-test the distinction; preserve frozen records. All three corrections are local, not delivered. |
| P1 | #747 | Newly verified historical metric-identity defect: April `M_peak_inventory_oracle_vs_agent` stores 23 positive + 8 negative density peaks as `T05_clashes_unique_pairs`. Catalog lines 1476–1480 define that metric as steric atom-pair clashes. | Withdraw/correct the scalar through the dated record, preserve genuine peak observations, and prevent density peaks from contributing to clash coverage. |
| P2 | #748 | Newly recalculated denominator defect: four April ligand B-ratio rows use overall heavy-atom mean 15.9814 while claiming protein mean/local surroundings. Protein-only mean is 15.4847. The old Ca agreement grade also fails its own arithmetic. Active handbook line 368, quality guidance line 188 and T10 driver lines 54–55 can reintroduce unsupported ratio/occupancy interpretations; this remainder was reported on the issue before any guidance fix. | Name exact atom selection and denominator, correct ratios and unsupported occupancy claims through dated evidence, reconcile active guidance, and retain exact-selection regressions. |

The April and September paths in this table are under
`data/coscientists/openscientist/`; all cited main-revision evidence was inspected
directly, using `git show main` where local modifications could affect the file.
One part of #610's original body is stale: main already rejects self, future and
dangling assumption supersessions (`scripts/qds_emit_contract_v1.py:2089–2129`).
Its all-evidence-class correction requirement remains unresolved on main.

## Unmerged contract-4 review issues

These are implementation/review defects, not demonstrated corruption of a
published contract-4 sheet. None qualifies for closure before reviewed delivery.

| Priority | Issue | Disposition at this checkpoint |
| --- | --- | --- |
| P1 | #732 | Locally mitigated: fresh replacement IDs and non-backward registry activation checks. Not merged. |
| P1 | #733 | Locally mitigated: exact raw dependency ownership prevents same-ID retargeting after withdrawal. Not merged. |
| P1 | #734 | Locally mitigated: correction-only owners retain applicable replacement assumptions. Broader terminal-chain coverage is tracked by #737. |
| P1 | #735 | Locally mitigated: associated dataset evidence outranks unlabelled legacy fallback while retaining its MTZ subject. |
| P2 | #736 | Locally mitigated: admitted headline assumptions reach the QDS report; frozen builders remain unchanged. |
| P1 | #737 | Round-2 fixes under review: follow exact raw replacement ancestry through retired intermediate owners and retain assumptions nested in whole-finding replacements. New end-to-end controls include wrong-subject exclusion. |
| P2 | #738 | Newly filed and locally mitigated: selected registry assumptions undergo exact active-dependency closure. The reproduced pre-fix output referenced withdrawn `M_old` while only `M_new` remained active. |
| P1 | #740 | Newly filed and locally mitigated in round 3: corrected headlines were unable to cite unchanged active measurements in earlier runs. Support refs now resolve exact raw local-first/otherwise unique-global ownership; computational operands remain same-run. |
| P1 | #741 | Newly filed and locally mitigated in round 3: alternating nested/whole/nested replacements still lost terminal assumptions. Applicability now propagates over exact correction and container/descendant relationships; both alternating forms and unrelated-subject/sibling controls are tested. |
| P1 | #742 | Locally mitigated: live emission previously accepted empty snapshots despite applicable dated registry guidance. Exact applicable rows and ancestor closure are now required before explicit corrections. |
| P1 | #743 | Locally mitigated: foreign auxiliary replacements leaked through substantive owners. Exact correction-origin admission now also applies to mixed substantive carriers. |
| P1 | #744 | Locally mitigated: same-ID registry assumptions silently displaced corrected source payloads. Cross-origin active payload conflicts now fail before deduplication. |
| P1 | #745 | Locally mitigated: source-only supersession bypassed raw snapshot completeness. Effective retirement now requires exact typed correction authority. |
| P2 | #746 | Locally mitigated: independent exact measurement support now anchors an original headline even if one nested correction came from a foreign subject. Surviving support must still resolve to active evidence. |
| P1 | #749 | Locally mitigated: replacement chronology follows the exact original owning run, with a derived origin ledger and original-owner bundle boundaries. All 23 focused tests pass; restoring old selection behavior in memory causes 16 failures. Integration exposed #750; not merged or ready for closure. |
| P1 | #750 | Locally mitigated after six full-gate failures: the integrity checker now distinguishes only the direct contract-4 QDS origin list, validating it against the complete derived projection. All 21 RI tests pass; restoring the old walker in memory causes 10 failures. The subsequent full gate passed; not delivered. |

Focused checks after #740/#741: 15 contract-4 integration tests and 51 projection
tests pass. Earlier migration checks reported 116 trust checks and 364 guard
checks passing. The full hermetic gate passed after #737/#738, before the round-3
fixes. Those later changes still require independent re-review and a final gate;
the earlier pass does not establish that the current branch is mergeable.

The subsequent full gate also passed after round 4, before #745/#746. At that
checkpoint, independent Codex-plugin escalation and final validation were pending.
#739 is locally fixed with regenerated models and two guard checks; restoring the
old schema description in memory provably fails the new regression. It is not
delivered on main yet.

### Latest requested-skill checkpoint

A complete-queue read at the preceding checkpoint returned **24 issues**, matching GraphQL's
`totalCount`, with unchanged main `c71682d` and no open PRs. An independent
read-only audit of all nine original issues and their comments confirmed that
none is ready for closure. The 15 newer review issues also remain unmerged.

Current focused validation passes: 16 contract integration tests, 51 projection
tests, 19 live-registry admission tests, 10 headline-support tests, 11 assumption
collision tests, 15 referential-integrity tests, 116 trust checks, and 366 guard
checks. The retained ancestry suite passes all 128 six-hop cases. Ruff initially
identified an unused test-local variable; removing that assignment leaves all
focused lint checks clean. The full hermetic gate then passed with exit 0:
`uv run --locked -- bash scripts/validate.sh --quiet`. It included the final
#745/#746 fixes and retained ancestry matrix. No new scientific measurement or
external oracle run was performed. Historical data and frozen v1/v2/v3 modules
remain unchanged.

The installed Codex plugin invocation was **blocked before execution** by the
approval system because it would transmit tracked and untracked repository
contents to an external Codex service. No plugin review result exists. Explicit
user approval for that transfer is required; no indirect retry or substitute
same-family review is being counted as the independent escalation. This remains
a merge blocker even if the local gate passes.

The literal goal references #592/#593 were rechecked: both are already closed.
#592's documentation invariant is present in rule 13c and the skill; #593's scalar
criterion enforcement shipped in PR #705 (`9b6bc8e`). The scientific remainders
are #692/#693 and remain explicitly included here rather than silently dropped.

### Retained-data acceptance checkpoint: 27 open issues

`scripts/audit_1sar_retained_evidence.py` performs fixed-column arithmetic and
saved-log parsing only. Root reran it and its 35 new regression tests. The tests
include an independent decimal sum of PDB B-factors and an independent IEEE-word
traversal of both retained MTZ tables; all 35 pass. No PHENIX, CCP4 or gemmi
executable is invoked. The new helper rejects incomplete MTZ header records and
invalid observation-column pairs; those are synthetic input-hardening checks,
not claims that the retained files are malformed.

The archive SHA-256 is
`9fc5352284b7ffa7763c633a3eb4d3d0db96b8c25a1be9bcea361722d2c53054`.
Its `data/1sar_final.pdb` yields the following exact selections (no H/D, no
occupancy weighting):

| Selection | Atoms | Mean B (Å²) |
| --- | ---: | ---: |
| All heavy atoms | 1641 | 15.9814137721 |
| Standard amino-acid residues | 1488 | 15.4846706989 |
| HOH waters | 146 | 20.7588356164 |

Ca/Na/sulfate mean B divided by the global amino-acid mean gives
2.7595033069 / 1.4756529502 / 1.1358330017. These are not local-surrounding
ratios and do not establish chemical identity or occupancy. This supports #748;
it does not correct the immutable historical output by itself.

All 7248 H/K/L-indexed F/SIGF pairs in archived `data/1sar.mtz` match the saved
`t13_oracle_logs/ctruncate_out.mtz` selected float bytes, including 20 missing
observations. Their sorted selected-observation digest is
`927d368a4d9d3b29588813c304b45b3c47bafa51f2cd6585cf93ebc9e61c937d`.
The full MTZ files differ. This establishes selected-observation equivalence,
not exact recovery of the unretained historical input file or a new execution.
The retained logs identify May 4, 2026; aimless failed with an empty input-list
error, while the current pure parser reads ctruncate's acentric second moment
as **1.968**, not the historical row's 1.997.

The #749 reproduction uses `test_qds_contract_v4.fixture()` with three owners:
September 20 owns MolProbity clashscore 9; September 22 owns an unchanged
same-subject/same-tool clashscore 2; September 23 owns a typed metadata-only
replacement of the September 20 row, still value 9. Both before/after sheets
emit successfully:

```text
before: M_recent = 2.0, source EVAL_synth_recent_2026-09-22
after:  M_new    = 9.0, source EVAL_synth_contract4_2026-09-23
```

`qds_emit_contract_v4.prepare_projection` calls frozen `_annotated_runs`, which
assigns the replacement carrier's date (`qds_emit_contract_v1.py:403–404`).
`_candidate_priority` then uses that date for recency (`:632–640`). The correction
does not constitute a new measurement, but its publication date silently wins.
This is a demonstrated unpublished-contract defect, not damage to an already
issued contract-4 sheet. Same-date conflicting-bundle rejection is a separate,
correct safety behavior and must not be weakened to hide this defect.

Scratch plans cover all 83 April scalar rows and affected structured rows, but
remain unpublished authoring plans. Review caught and corrected one repeated
B-denominator phrase and per-row references that split shared R-factor bundles.
Actual tool identities, compatible metrics, full distribution provenance and
scientific observation chronology still need resolution. No new dated real Eval
or QDS exists yet, and the nine original issues plus 18 later issues remain open.

Final validation at this checkpoint: the full hermetic gate
`uv run --locked -- bash scripts/validate.sh --quiet` passed with exit 0, including
the 35 retained-evidence tests and all 369 guard checks. Whitespace checks also
pass. This is code/replay validation, not a new scientific rerun, and does not
resolve #749: its newly reproduced chronology case is not implemented in the
passing suite yet. The external plugin review still has no approval or result.

### Chronology fix and gate-integration checkpoint: 28 open issues

The local #749 fix treats a typed measurement replacement as a correction of an
existing observation, never proof of a new execution. The complete raw replacement
chain supplies its original owning run and declared date, including withdrawn
intermediates. The correcting source IDs and carrier date stay unchanged. The QDS
exposes all active measurements in `measurement_evidence_origins`, including those
not selected for summary. That date is a source-record ordering proxy, not a
verified tool-execution timestamp. Genuine new execution requires a standalone
measurement with retained execution evidence; parsing an old log today does not
refresh its underlying observation.

Original ownership also participates in equality and R/T15/T16 bundle selection.
This prevents separate historical invocations from becoming one coherent bundle
merely because their corrected rows share a new carrier. The 23 new recency tests
pass. Restoring the pre-fix selector, bundle keys and payload equality in memory
produces 16 failures and no errors, demonstrating regression sensitivity without
rewriting any repository file. Five-field origin tampering also fails full pinned
replay, including when the output hash is refreshed.

The subsequent full gate **failed**, not passed: six cases in
`scripts/test_referential_integrity.py` reject valid origin metadata as if it were
a wrapped scalar. `check_referential_integrity.py` infers scalar equality from the
source-run/source-measurement pair without distinguishing this new schema-owned
metadata list. This is #750, filed before its fix. The 23 chronology tests passed
inside that gate; their success did not establish whole-system integration.
Earlier gate passes in this report are historical checkpoints, not current
merge evidence. No issued scientific record or frozen contract was changed.

The #750 fix is now local: only the exact direct contract-4 QDS field receives
origin-list validation instead of scalar-copy comparison. The complete ordered
list must match the source projection. Other contracts reject it; nested or
misplaced origin-shaped dictionaries still receive scalar checks. Six added test
methods cover standalone/replacement/chained provenance, all five fields,
omitted/duplicate/reordered/malformed entries and scalar spoofing. Root reran all
21 RI and 23 recency tests successfully. Restoring the old walker in memory makes
10 RI assertions fail, with no errors. The subsequent full-gate run completed
with exit 0 (`uv run --locked -- bash scripts/validate.sh --quiet`). This checks
the integrated local fix; it does not establish independent-review completion.

Real-correction preparation also distinguished documented from invented tool
provenance. The May 5 narrative explicitly names `checkmymetal_local.py` and its
invocation (lines 144–148, 233). Root independently recomputed the two sites with
decimal fixed-column coordinate arithmetic, the script's strict distance cutoff,
and its displayed normalization constants: each has three direct-coordinate
neighbors; mean distances are 2.8874064349682985 and 2.7731465709850792 Å. The four
rounded diagnostics are 16.35, 3.25, 14.06 and 1.87, matching the historical local
scores. This does not establish canonical-service provenance, calibrated
significance, occupancy or ion identity; no symmetry expansion or scientific
executable was used. The categorical biological conclusions are not outputs of
the local script and must not be relabelled as oracle results.

The scratch-only scalar plan still accounts for exactly all 83 frozen April IDs:
61 proposed replacements and 22 withdrawals, with three separately evidenced
standalone coordinate recounts planned. Those recounts must not be typed
replacements under #749's chronology semantics. Incorrectly typed global B ratios
remain in the audit narrative/evidence rather than silently redefining the local
surroundings metric. The plan is not an issued correction: 20 rows still carry
unresolved identity/evidence requirements, and the new recounts additionally
require an actual registered method and retained output. No new real Eval/QDS
was written or scientific issue closed.

## Evidence limits and next actions

### Latest real-record integration checkpoint

The dated real September 23 narrative, Eval and QDS now exist in the working tree,
alongside the retained input MTZ and exact `coordinate_and_t13_audit.json` output.
They remain uncommitted and unmerged, not delivered fixes. The source accounts
for all 83 April scalar rows with 60 replacements and 23 withdrawals, plus three
fresh standalone coordinate recounts. The cumulative QDS contains 148 correction
operations (115 replacements, 33 withdrawals), 63 active measurement origins,
11 metric/context waivers and references to nine corrected historical sheets.
Frozen scientific carriers and retained v1/v2/v3 modules remain unchanged.

| Priority | Issue | Current disposition |
| --- | --- | --- |
| P2 | #751 | Local real correction withdraws false sfcalc count/B/displacement attribution. Three fresh recounts name the actual registered method; historical local displacements explicitly lack verified producer provenance. Not merged. |
| P1 | #752 | Filed before fixing a real acceptance gap: schema-valid cumulative output lacked resolution and space group. The new Structure snapshot now names 2.50 Å and P 21 21 21 from the packaged PDB header; actual-record tests compare both emitted fields to that header. Not merged. |
| P2 | #753 | Filed before resolving 24 stale legacy tool/task exemptions after legitimate producer registrations. Root verified every exact row hash and its actual tool/task link, removed only those obsolete entries, and retained stale-exemption enforcement. Five regressions pass; restoring the removed exemptions in memory causes 49 failures and no errors across three selected tests. Not merged. |

The #748 active guidance and historical-record portions are now both implemented
locally. The full-repository referential-integrity check passes after publication
of the narrative and retirement of obsolete exemptions. The pass-status check
passes for 196 measurements with 26 explicitly frozen exceptions; whole-sheet
trust/replay also passes. Root reran 21 actual-record acceptance tests and 42 audit
helper tests successfully. The prior 194 focused tests are a separate earlier
checkpoint. The full hermetic gate for the actual real-record bundle has now
completed with exit 0 (`uv run --locked -- bash scripts/validate.sh --quiet`).
The identity-field negative controls each produce one assertion failure and no
errors when resolution or space group is removed in memory. These checks prove
the regression detects each omission, not that schema validation alone does so.

The audit JSON now retains selected F/SIGF equivalence plus exact-decimal cell/
resolution metadata, normalized space-group/symmetry records and internal
dataset-cell/column consistency. It does not claim recovery of the complete
historical execution input. Fresh coordinate arithmetic and saved-log parsing
remain distinct from new scientific oracle execution. Scratch authoring decisions
have now become actual source records, but independent scientific truth is not
established merely by their schema or replay checks.

The required external plugin escalation remains unexecuted pending explicit
repository-content transfer approval. The user was asked again after actual
publication work; no retry or same-family substitute was counted as escalation.

No new external scientific oracle was executed. New evidence consists of
fixed-column coordinate arithmetic and retained-log parsing; the other checks
exercise saved records and synthetic code paths. Ignore-inclusive filename/content searches
and inspection of all **241** ZIP members did not locate the missing 1SAR raw
oracle/ProSMART outputs or round-7 coordinate/reflection members. This establishes
unavailability in the searched repository/archive, not that the historical run
never happened. The record's missing-input claims remain unverified scientifically.

1. Complete the required independent plugin review after explicit approval for
   its external repository-content transfer, including the actual dated records.
2. Complete reviewed delivery of the locally validated real correction
   covering #580/#585/#591/#692–#695/#747/#748/#751 and exercising #725/#752.
3. Deliver the local contract, catalog/guard and active-guidance fixes together.
   Close each issue only when its complete acceptance scope is delivered, citing
   the merged PR and commit.

No external scientific tool or data acquisition is required to state unavailable
evidence honestly. A future independent rerun or canonical CheckMyMetal service
result is optional additional evidence, not an excuse to keep unsupported grades.
Registry snapshot completeness is also an explicit review question: snapshot
presence and replay pinning alone do not prove that all applicable caveats were
captured. The local #742/#745 fixes address that boundary and await the required
independent review; this is not demonstrated damage to a published contract-4 sheet.

**Verdict:** no current open issue is ready for closure. The current branch is not
mergeable at this checkpoint: independent escalation is blocked pending explicit
approval for the external transfer. The actual local real-record bundle now
passes the full gate, but that result does not substitute for independent review.
The historical correction is now part of this branch, not a deferred follow-up.
Previous merged branches need no further deletion.
