# Correction-aware QDS contract — 2026-09-23

## Priority and scope

Branch `qds-correction-contract-2026-09-23` starts from main
`c71682dd94d482f8f1d4882d238add0776ae5c3d` (merged PR #731). The preceding
turn completed the corrected synthetic fixture, with independent review and local,
Ubuntu and macOS gates green. The next full-queue read found nine open issues and
no open PRs: #580/#585/#591/#610/#692–#695/#725.

#610 and #725 were the initial P1 dependencies: corrected cumulative sheets need
all-evidence projection and explicit model/dataset admission. The branch initially
contained only that implementation; it now also contains the dated real 1SAR
correction for #580/#585/#591/#692–#695 and subsequent acceptance findings. The
latest publication checkpoint below describes the actual local artifacts. None
is merged, and all pre-existing Eval/QDS artifacts and retained v1/v2/v3 modules
remain unchanged.

## Contract boundaries

- Source-owned contexts govern both partial and cumulative sheets, including
  exact raw source order, authoritative snapshot owner, subject, scope and headline.
- Typed corrections pin original target identity and canonical bytes. The pure
  projection validates lineage and surviving dependencies before any builder.
- Raw audit inputs remain separate from active contributors. Replay pins cover
  raw runs, Structure snapshots, complete registry snapshots and the context.
- Typed associations bind T13 diagnostics to retained MTZ bytes and explicit
  owning-run/selectors while retaining true dataset subjects. Every admitted T13
  diagnostic is surfaced, including unavailable/attempt metadata.
- New sheets use contract 4; the exact already-issued September22 real and
  September23 synthetic contract-3 sheets retain full frozen replay authorization.
  No generic old-contract authoring exception is added.

## Adversarial review round 1

Each issue was independently reproduced by the root reviewer and filed before its fix.

| Issue | Demonstrated defect | Resolution under test |
| --- | --- | --- |
| #732 | Replacement IDs could reuse history; registry replacements could move backward in time. | Fresh run-row IDs and non-backward registry activation checks. |
| #733 | A withdrawn Site could silently resolve to a same-ID Site in another run. | Resolve exact original dependency ownership, then require that target to survive. |
| #734 | A correction-only owner lost its replacement run assumption. | Preserve only subject-applicable replacement auxiliary rows from such owners. |
| #735 | Associated MTZ evidence lost priority to a newer unlabelled fallback. | Propagate exact-association priority into the isolated selector policy. |
| #736 | Corrected HeadlineFinding assumptions survived projection but disappeared from QDS aggregation. | Aggregate admitted headline assumptions in v4 without changing frozen helpers. |

Initial focused verification: projection suite 38 tests, contract-4 integration
suite 10 tests, new RI suite 15 tests. These exercise synthetic code paths and
saved-file checks, not new scientific oracle measurements. Old-suite migration,
full-gate results and subsequent independent review are still pending; this is an
unpublished branch, not a completed or mergeable deliverable yet.

## Adversarial review round 2 and full-queue refresh

The renewed `review-open-issues` skill review is recorded separately in
`open_issue_review_2026-09-23.md`. It distinguishes main from these uncommitted
fixes and retains a disposition for every open issue; no closure is justified yet.

- #737: terminal assumptions disappeared across correction-only replacement
  chains, and whole-headline replacements lost embedded assumptions. The fix
  follows exact raw successor/target ancestry, including whole-finding-to-nested
  chains, and checks the original subject ownership. Wrong-subject controls remain
  excluded; applied corrections do not themselves make evidence applicable.
- #738: active registry assumptions bypassed run dependency closure and could
  still reference a withdrawn measurement. Selected emitted registry rows now
  undergo the same exact raw-owner/active-target checks. Inactive predecessors
  remain in the pinned snapshot without becoming active dependencies.

After these fixes, 13 integration tests and 45 pure projection tests pass; Ruff
and whitespace checks pass. Migrated retained/current emitter tests, 116 trust
checks and 364 guard checks also passed. The full hermetic gate passed with exit
0 at this point, before the round-3 changes below.
All existing data carriers and frozen v1/v2/v3 modules remain byte-unchanged.

## Adversarial review round 3

#740 was filed after independent review and root reproduction: a whole-headline
replacement citing an unchanged active measurement in an older run is rejected.
Support citations are being treated like same-run computational operands. The
fix allows an exact unambiguous surviving cross-run support reference while
retaining strict computational operand and no-retargeting rules. No scientific
rerun is appropriate merely to correct interpretation of existing evidence.

#741 was independently reproduced and filed before its fix: alternating
nested/whole/nested replacements lost the terminal assumption because a linear
ancestry walk stopped at a correction-only container. Applicability now reaches
a fixed point over exact successor/target and container/descendant relationships.
Tests exercise both alternating directions, unrelated-subject exclusion and
unrelated siblings in terminal nested-replacement holders.

After these fixes, 15 current-contract integration tests and 51 pure projection
tests pass. The earlier full-gate pass predates them; final independent review and
the final gate remain required before publication. The registry snapshot
completeness/authority question also remains under explicit review.

## Adversarial review round 4

All findings were independently reproduced and filed before fixes.

- #742 resolved the registry-authority question as a demonstrated live-authoring
  regression: explicit empty snapshots omitted three applicable recommendations
  and four MolProbity assumptions. Live admission now requires exact applicable
  dated rows and complete predecessor ancestry, while replay remains source-only.
- #743: foreign-subject auxiliary replacements leaked when the correcting owner
  also contained an unrelated selected-subject measurement. Subject ancestry now
  applies to substantive owners as well as correction-only carriers, and explicit
  successor identities are not seeded merely by carrier membership.
- #744: a registry assumption could silently replace a corrected run assumption
  with the same ID but different content. Every selected registry, measurement,
  run and headline origin is now collision-checked before identical-row deduplication.
  Registry withdrawal is scoped to registry identity rather than every same-ID row.

The full hermetic gate passed after these fixes. It predates the round-5 fixes.

## Adversarial review round 5 and independent escalation

- #745: retaining exact live rows in the raw snapshot was insufficient. A
  source-only successor could retire applicable guidance, including via a changed
  tool or metric, without any typed correction. Live admission now checks effective
  source-graph retirement and requires exact typed correction authority.
- #746: a foreign-derived child caused an independently measurement-supported
  original headline to lose subject applicability, then lose its replacement.
  The fix recognizes exact raw subject-admissible support as an independent
  original anchor, while surviving support still passes active-dependency closure.

The other round-5 reviewer reported no new findings in the scoped ancestry,
collision and rotamer fixes: 128 six-hop whole/nested ancestry probes passed,
including foreign ancestry with a substantive selected-subject terminal owner.
This does not negate the two findings above, which exercised different cases.
The matrix is now retained in `scripts/test_qds_ancestry_matrix.py`; the root
reviewer reran all 128 cases successfully. The final targeted suites also pass:
16 integration, 51 projection, 19 live-admission, 10 headline-support, 11
assumption-collision and 15 referential-integrity tests, plus 116 trust and 366
guard checks. Focused Ruff checks pass after removing one unused test variable.

Five consecutive issue-returning rounds warrant independent escalation before
publication. The attempted installed Codex-plugin adversarial review was blocked
before execution by the approval system: transferring tracked and untracked
repository contents to the external Codex service requires explicit user approval.
No plugin review findings or approval exist, and no workaround was attempted.
The intended review remains read-only and includes the final fixes. The full
hermetic gate (`uv run --locked -- bash scripts/validate.sh --quiet`) passed with
exit 0 after #745/#746 and the retained 128-case matrix, including the minor
test-local lint fix. It cannot substitute for this escalation. No merge is authorized by
test results alone; the existing user authorization to complete the review/fix/
merge workflow remains contingent on verified completion of those checks.

## Related active-schema fix

#739 corrects the canonical rotamer outlier enum to the tool-reported OUTLIER
classification, explicitly excluding Allowed and Favored. Models were regenerated
with the official pinned LinkML generator. Follow-up inspection found the same
obsolete definition in the active threshold registry; that remainder was reported
on #739 before correcting it. Both definitions are now regression-guarded, and
the focused guard suite passes 369 checks. An in-memory mutation restoring the
old schema definition fails the new regression as intended. No new numeric
threshold was invented, and no historical Eval/QDS record was rewritten. The
full-gate pass above predates the three additional registry checks.

## Real-record acceptance preparation

The correction must preserve scientific observations while retiring invalid
interpretations; changing every status mechanically is not sufficient. A pure
fixed-column/retained-log audit, `scripts/audit_1sar_retained_evidence.py`, recounts
archived coordinates and compares the saved MTZ observations without invoking
PHENIX, CCP4 or gemmi. This is fresh coordinate arithmetic plus historical-log
parsing, not a new scientific oracle execution.

Two additional historical defects were filed before any record correction:
#747 stores density peaks under a steric-clash metric; #748 misidentifies the
ligand B-ratio denominator and overinterprets occupancy. Scratch authoring plans
inventory all 83 April scalar rows and the affected structured rows. They are
not issued Eval/QDS artifacts or completed fixes. Exact tool identity, local vs
global denominator semantics, preservation of alternative oracle observations,
and real-source projection remain acceptance questions to resolve before the
dated correction can be published. No scientific issue is closed by these plans.

The helper's 35 stdlib-only tests pass, including independent decimal PDB sums
and an independent exact-byte MTZ comparison for all 7248 reflection keys. No
retained scientific file or frozen emitter module changed.

Preparation then exposed **#749**, independently reproduced by the root before
filing: a metadata-only replacement of an old clashscore changes the selected
sheet value from a newer observation's 2 to the old observation's unchanged 9.
The new carrier date becomes `_source_run_date`, so the selector treats a
correction as a fresh measurement. At that checkpoint the issue was not fixed. Define and validate
scientific observation chronology separately from correction publication; do not
invent dates, delete alternative measurements, or suppress honest ambiguity
checks. The complete issue review records the reproduction and the final
27-issue queue. Passing existing tests is not evidence that this defect is fixed.

The full hermetic gate was rerun after adding the audit helper/tests and extending
#739 to the threshold registry. It passed with exit 0, including 35 audit tests
and 369 guard checks; whitespace checks pass. #749 remained a known unresolved
acceptance gap outside those passing tests, and the required external Codex
review remains blocked pending explicit transfer approval. No commit, push,
merge, issue closure or additional branch deletion was performed at this checkpoint.

## Chronology implementation and integration finding #750

The later local #749 fix separates correction publication from observation
ordering. Typed replacement always corrects existing evidence; the oldest exact
raw replacement target supplies its original owner and declared run date, even
through withdrawn intermediates. Current source IDs and carrier dates remain
unchanged. A derived `measurement_evidence_origins` QDS list exposes this lineage
for every admitted measurement, selected or not. The inherited date is explicitly
a source-record ordering proxy, not verified execution time. New execution uses
a standalone measurement with retained execution evidence, optionally accompanied
by withdrawal of obsolete evidence. Neither prose nor changed numbers implies a
fresh execution.

Original owner also constrains scientific equality and coherent R/T15/T16
bundles. All 23 chronology tests pass; restoring the previous selection/bundle/
payload behavior in memory yields 16 failures and no errors. Tests include
old-vs-new selection, chained corrections, exact ownership, same-date ambiguity,
mixed-original-owner bundle rejection and full replay tampering of all five
origin fields, even with a refreshed output pin. Frozen v1/v2/v3 and all existing
Eval/QDS bytes remain unchanged.

The full hermetic gate then **failed** in six referential-integrity tests.
The new QDS-level metadata carries source run/measurement IDs, which the general
walker incorrectly treats as sufficient evidence that a node is a copied scalar.
It therefore demands scalar metric/value/tool fields from an origin record.
This integration defect was filed as #750 before its fix. The appropriate
boundary is the exact direct contract-4 QDS origin-list field, checked against
the complete derived source projection, not an exemption based on arbitrary
origin-looking dictionary contents. The current 28-issue queue and gate failure
are recorded in the companion open-issue review. The independent plugin review
still has no result or transfer approval; no closure or merge is justified.

The local #750 fix is restricted to the exact direct contract-4 QDS origin-list
field. Its complete ordered payload must equal the derived source projection;
the field is forbidden for older contracts. Origin-shaped scalar, nested and
out-of-QDS dictionaries retain strict source-scalar equality. Six added test
methods cover valid standalone/replacement/two-hop provenance, each origin field,
missing/duplicate/reordered/malformed lists and scalar spoofing. Root reran all
21 RI tests and 23 chronology/replay tests successfully. Restoring the pre-fix
walker in memory causes 10 RI failures and no errors. The subsequent full-gate
rerun (`uv run --locked -- bash scripts/validate.sh --quiet`) completed with
exit 0, including the final chronology/integrity integration. Whitespace checks
pass. The external-review boundary remains unchanged: no plugin result or
transfer approval exists, and no merge or issue closure was performed.

The real-record authoring plan now distinguishes three new coordinate recounts
from historical replacements. All 83 April scalar IDs remain accounted for
(61 proposed replacements, 22 withdrawals); unsupported tool attribution or
metric identity is not repaired by guessing another tool name. In particular,
categorical ion conclusions are withdrawals, not fabricated local-tool output,
and global B-ratios are not silently republished as local-surroundings metrics.
The companion issue review records a separate decimal-coordinate reproduction
of the four historical local metal diagnostics and its limits. These are
preparation results only; exact tool registration, remaining evidence identities
and actual dated Eval/QDS publication are still required.

## Real-record publication and acceptance checkpoint

The preceding preparation counts are historical checkpoints. The September 23
real Eval/QDS and narrative are now present, with retained coordinate/T13 audit
JSON and the exact archived input MTZ. All 83 April scalar rows have an explicit
disposition: 60 replacements and 23 withdrawals, plus three standalone fresh
coordinate recounts. The complete sheet carries 148 operations (115 replacements,
33 withdrawals), 63 active measurement origins, 11 exact-context waivers and
nine corrected-sheet references. Six raw source runs remain pinned, including
the non-admitted T06 dataset owner. No scientific oracle was newly executed.

The scratch authoring helpers are not replay dependencies. Actual records replay
from their five canonical source carriers through the retained contract, and
the committed audit helper reproduces the retained JSON exactly. Root reran all
21 actual-record acceptance tests, 42 retained-audit tests and five catalog
exception-retirement tests successfully. The full corpus reference check,
pass-status check (196 measurements, 26 frozen exceptions) and whole-sheet
trust/replay check pass. The full hermetic gate for this real-record bundle has
now completed with exit 0 (`uv run --locked -- bash scripts/validate.sh --quiet`).

Two integration findings were filed before correction:

- #752: the schema-valid cumulative draft omitted resolution/space group. The
  new source Structure snapshot now includes 2.50 Å and P 21 21 21 from the exact
  packaged PDB's REMARK 3 and CRYST1. Acceptance compares both source and emitted
  fields with the archived header, rather than treating narrative presence as enough.
  Removing either field in memory produces one assertion failure and no errors.
- #753: legitimate producer/task registrations made 24 narrow historical
  tool-task exceptions obsolete. Each target/hash and actual task link was checked
  before removing its allowlist entry. The strict stale-exception check remains;
  reinstating the obsolete entries in memory produces 49 failures and no errors
  across three selected regressions. Unrelated historical exceptions remain exact.

The new real-record suite checks all scalar correction hashes/actions, source
immutability, live/snapshot replay, origin-date tampering, unavailable PHENIX output,
all seven T13 diagnostics, failed aimless, independent-only versus waived coverage,
and each identified scientific misclassification. The retained-data audit now also
checks crystallographic context, not just equality of selected F/SIGF bytes.

The human-readable narrative retracts cross-round adjudication and wrong-protein
biology, documents all 23 scalar withdrawals, separates new recounts from old log
parsing, and preserves unavailable-evidence limits. README links the new correction
so frozen older sheets are not the only discoverable account.

All changes remain uncommitted/unmerged. These acceptance checks and authoring
assistance are not the required independent Codex-plugin escalation, which has
no result and still awaits explicit approval for external repository-content
transfer. No issue is closed and no merge is justified by local checks alone.
