---
name: reconcile-next-tasks
description: Update protstruct_review's NEXT_TASKS.md against the complete live GitHub issue and PR queues, current main, and retained scientific evidence. Use when asked to reconcile, refresh, or synchronize the backlog document, including priorities and blockers. Ordinary issue review remains read-only; reconciliation edits the local document without changing GitHub or running experiments.
---

# Reconcile NEXT_TASKS.md

Make `NEXT_TASKS.md` an accurate working view of what remains, what can start,
and what supports the repository's goals. All repository paths below are relative
to the root; sibling skill links are relative to this file.

## Scope and authority

An instruction to reconcile or update the document authorizes the local edit;
do not ask again before making it. A request for a preview or review alone calls
for a proposed diff or findings instead. Creating or editing this skill does not
itself invoke reconciliation.

Read `CLAUDE.md`, `CODING_STANDARDS.md`, and all of `NEXT_TASKS.md`. Read the
relevant parts of [protstruct-eval](../protstruct-eval/SKILL.md) when interpreting
scientific status. Preserve existing user edits and work on a task branch before
editing; do not reset, stash, or replace unrelated work.

Use three distinct authorities:

- **GitHub** establishes issue/PR state and recorded discussion or disposition.
- **Current default-branch code and retained evidence** establish what was
  delivered and what was measured. Local or unmerged work is identified separately.
- **The project goals in `CLAUDE.md`** guide recommended priorities: assess
  refinement results and explain the landscape of tools and measurements.

The write scope is `NEXT_TASKS.md`. Reconciliation does not authorize issue
creation, comments, closure, relabeling, PR publication, merging, scientific runs,
threshold changes, or rewriting EVAL/QDS records. Follow any broader authorization
already given by the user; do not invent another approval step for it.

## Collect a complete, dated snapshot

Use the collection and verification procedures in
[review-open-issues](../review-open-issues/SKILL.md), especially its current-main,
queue-total, comment, and exact-PR checks. That skill's read-only boundary applies
to ordinary reviews; the user's reconciliation request authorizes the document
edit described here. Do not invoke its implementation/issue-mutation workflow.

Record the repository identity, collection date, default-branch SHA, local HEAD,
branch, and existing changes. Fetch the default branch when permitted, and keep
local changes distinct from delivered main-branch work.

Fetch both complete open queues with an explicit limit or pagination. Include
issue bodies, labels, comments, and update times; inspect PR base/head and merge
state. Compare issue and PR list lengths with separate API totals. Check for
changes during collection; refresh affected records and totals before declaring
the snapshot complete. Empty output from a failed request is not an empty queue.

Also fetch the exact issues and PRs referenced by current-work entries that are
absent from the open lists. They may be closed, reopened, transferred, or replaced.
Read later comments before relying on an issue's original proposed next step.
Verify claimed delivery against current main and exact merged PRs, not a commit
on another branch or a PR title containing a similar number.

If live state is unavailable or the collection remains incomplete, make only
independently supported corrections and explicitly label the remaining coverage
as partial. Preserve the last complete reconciliation date/SHA; do not present a
local-only review as a fresh complete GitHub reconciliation.

## Reconcile state before ranking work

Build a working ledger covering **every open issue and every existing current-work
entry**, including items marked `no issue`. For each, establish:

| Field | Required distinction |
|---|---|
| Identity | Exact issue/PR link, or explicitly `no issue` |
| Delivery | On main, unmerged, local-only, or not implemented |
| Scientific status | Unmeasured, stopped/failed, informational, or supported within its stated scope |
| Disposition | Next action, blocker, optional work, deliberate gap, or completed work |
| Evidence | Relevant commit/PR, dated comment, code, or retained-record path |

Group related issues by dependency while keeping each issue number visible.
Do not silently collapse a tracker and its actionable children.

Apply these distinctions when reconciling:

- A merged execution fix does not complete a benchmark or calibrate a changed
  pipeline. Move the delivered prerequisite, retain the scientific remainder.
- A successful canary or diagnostic is not a completed cohort. Failed/stopped
  attempts and unstarted entries remain visible; successful prefixes from
  separate attempts cannot be pooled into a completed study.
- Later recorded stop decisions and design amendments can supersede an issue
  body's run instructions. Preserve their scope and source. They do not grant
  execution permission, and the user's current explicit direction takes precedence.
- A changed comparison population or instrument needs its own prospective design;
  it does not retrospectively rescue an earlier calibration. Keep historical and
  current criteria separate.
- GitHub closure alone does not prove scientific completion. If a closed issue
  still has unsupported deliverables, say `closed on GitHub; work remains` and
  identify the missing tracker or linked successor without creating one.
- Distinguish an external access blocker from an engineering dependency and from
  a deliberate scope decision. State the concrete unblock condition.
- Preserve informational, suspended, waived, and unevaluable qualifications.
  Retained evidence is not automatically independent corroboration or permission
  to grade; documentation synchronization cannot promote it.

Prefer linking retained records to copying scientific numbers. If a numerical
claim must change, derive it from machine-readable evidence or an existing
derivation script, not rounded narrative tables. Save any new helper script in
`scripts/adhoc/` with purpose, inputs, outputs, issue/task, and date; keep it with
the result. Include ignored files in searches used to establish absence
(`rg --no-ignore --hidden`), and state any search exclusions or unresolved gaps.

## Update the document

Preserve its historical sections, links, date conventions, and evidence caveats.
Update current-work prose where it lives instead of appending a competing backlog.

- After a complete collection, update the top and `Open` reconciliation stamps consistently
  with the checked date, default-branch SHA, and complete issue/PR counts. Keep
  prior reconciliation history clearly historical; do not leave an old statement
  that the queue was empty sounding current.
- Make every open issue findable in `Tracked on GitHub`, including blocked and
  intentionally stopped work. Each entry should say what remains, what blocks it,
  the next bounded step, and the evidence for that state.
- Move verified engineering deliveries to `Delivered prerequisites` while keeping
  unresolved measurements tracked. Identify implemented-but-still-open issues as
  closure candidates without closing them or hiding their open status.
- Preserve `Open questions and optional work (no issue)`, deliberate gaps, and
  standing risks unless evidence establishes a new disposition. An empty GitHub
  queue does not erase untracked work.
- Recommend a dependency-ordered next direction using both project goals. Label
  proposed work as proposed and untracked where appropriate. Prefer concrete
  deliverables and completion conditions; do not turn another assurance pass into
  the default or block all progress on an optional experiment.
- Correct stale current references elsewhere in the document when needed, but
  retain dated historical accounts as history. Add a dated qualification rather
  than rewriting a historical result into a different scientific claim.

The `threshold-status-summary` marker block is generated from
`ref/threshold_evidence_status.yaml` by `scripts/check_threshold_evidence_status.py`.
Preserve it and the historical qualifiers checked by that script. Do not hand-edit
the counts or change the ledger/registry merely to make a backlog statement pass.
Report any source-level inconsistency as a separate finding.

## Validate and hand off

Review the diff for lost issues, erased blockers, accidental scientific upgrades,
and unrelated edits. Check internal links after changing headings. Recheck changed
GitHub states when needed; a different main SHA or queue invalidates an unqualified
claim to have reconciled the latest state.

For the document edit, run the existing focused guards in the locked environment:

```bash
uv run --locked --extra benchmark -- python scripts/check_next_tasks_dates.py
uv run --locked --extra benchmark -- python scripts/check_summary_coverage.py
uv run --locked --extra benchmark -- python scripts/check_threshold_evidence_status.py
git diff --check
```

These checks cover historical dates, summary coverage, and the generated evidence
summary; they do not verify live issue completeness or scientific conclusions.
If committing, run the required full gate first:
`uv run --locked --extra benchmark -- bash scripts/validate.sh`.
Disclose failed or unavailable checks without relaxing them or changing scientific
sources to make a documentation update pass.

Report the edited path, snapshot date/SHA and coverage, material status corrections,
recommended next steps, remaining uncertainties, and checks run. List any helper
scripts left uncommitted. Keep GitHub mutations and scientific execution outside
the reconciliation unless the user has separately included them in the task.
