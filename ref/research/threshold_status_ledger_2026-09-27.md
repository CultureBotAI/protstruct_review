# Descriptive threshold-evidence ledger — 2026-09-27

Issue #766 concerned a current certification headline that outlived the T15
denominator requalification. The replacement is a descriptive inventory, not a
new grading framework: policy status and retained-evidence status are separate
axes, and neither a historical label nor a retained file authorizes a verdict.

`ref/threshold_evidence_status.yaml` inventories the rendered §3/§4 table rows.
It does not claim to cover every registry paragraph or establish the truth of
every historical figure. In particular, #764's input-retention prose is not an
extra benchmark row. Threshold values remain solely in the canonical registry.

## Recount and scientific boundaries

`scripts/check_threshold_evidence_status.py --json` independently enumerates
the rendered registry rows, validates evidence/row fingerprints and anchors,
and recounts the ledger. The current inventory is 21 rows (17 in §3, 4 in §4),
20 benchmark-family rows and 41 scoped components. Historical through-round48
labels remain 18 reported-backed, 2 reported-partial and 1 excluded-literature;
these are not current scientific certifications.

The policy counts are 29 active-conditional, 6 informational, 1 not-evaluable,
1 unresolved, 1 provisional-conditional, 2 provisional-informational and
1 suspended. Component counts are neither row counts nor independent benchmarks.
Scoped row flags overlap and must not be added together.

The approved #786 adoption moves only the two shared-classification components
into active-conditional policy. Their retained-record evidence status does not
change. The scope remains the benchmarked PHENIX/wwPDB pair and insertion-code
keys, with no new QDS machine binding. Rotamer-favored calibration stays unresolved.
T15 retains its unproven historical denominator and informational expectation;
an incomplete rerun cannot repair that. T14 flip grading stays suspended after
the producer correction. DockQ/NMR selection checks do not establish independent
cross-tool calibration. No numeric policy was changed by this ledger.

## Review audit

Independent review checked the scientific classifications against their cited
evidence and the rendered registry, and recounted the rows/components without
accepting the proposed totals as authority. All row/evidence hashes and anchors
matched, the actual table contents were unchanged, and sixteen focused tests
passed after the following correction.

Review issue #836 was filed and reproduced before fixing a guard gap: replacing
the historical headings in the registry or NEXT_TASKS with a current-policy
heading still passed the original generated-summary checker. The corrected
guard requires the four known historical qualifiers across three consumers to
remain visibly rendered. Deletion, replacement, duplication, code-fencing,
commenting and indentation have negative tests. Pre-fix in-memory controls
accepted both actual-heading mutations; the new guard rejects them. This is a
bounded presentation check, not a general prose validator.

The partial-record triage document already had a whole-file evidence hash, so
its explicit qualifier check is a clearer intent/diagnostic, not a third
previously unguarded deletion path. Historical narratives are preserved and
visibly distinguished from the generated current summary.

Replaying the guard reads files only; it invokes no scientific tool. Changed
evidence or policy requires review before fingerprints are refreshed. Making
hashes match is not scientific validation, and this ledger does not close the
separate execution requirements in #760, #765, #790 or #799.

## Live-backlog reconciliation (#838)

Review also found that the `NEXT_TASKS.md` Open section still described merged
engineering and policy as missing. The live section now separates delivered
prerequisites (PRs #811, #818, #820, #823, #832, #835 and #837, with merge SHAs)
from pending science. This is a status correction, not a retrospective edit to
the historical benchmark narratives or a claim that those engineering merges
complete #760, #765, #790 or #799. PR #831's T13 operation and stopped T15 prefix
are identified as evidence awaiting delivery; no complete-cohort claim is made.
