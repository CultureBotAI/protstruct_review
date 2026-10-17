# Project goals and backlog reconciliation — documentation review

Reviewed 2026-10-16 against default-branch commit
`8aef21ccb528b60d811a3356af70c7346045a5e1`.

## Scope

The change records the user's refinement-assessment and tools/measurements goals
in `CLAUDE.md`, adds `.claude/skills/reconcile-next-tasks/SKILL.md`, routes requested
document updates from the issue-review skill, and reconciles `NEXT_TASKS.md`.
The backlog's dated snapshot remains 2026-10-15. A subsequent GitHub check on
2026-10-16 found the same main commit, open issue identities/update times, and
empty open-PR queue before publication of this change.

## Separate read-only review

An independent reviewer inspected the complete documentation diff, new skill,
saved issue bodies/comments and API totals, exact merged-PR records, and relevant
default-branch code and retained evidence. The review found no material defect.
The author separately checked the skill routing, scope, and changed-file list.
No review finding required a new issue or a scientific correction in this change.

The review specifically checked that:

- Every open issue remains visible, including the intentionally stopped #799/#876
  work and #765's input-population design decision.
- Delivered engineering prerequisites do not imply completed calibration,
  admitted measurements, or new grading authority.
- #760's installation requirement is labeled as the recorded access blocker,
  rather than a newly measured installation inventory.
- Proposed assessment and tools-guide deliverables remain explicitly untracked
  recommendations. The generated threshold summary and historical qualifications
  remain intact.
- A request to reconcile authorizes the local document edit; a plain review
  request returns findings or a proposed diff without editing.
- Unavailable GitHub permits only supported partial corrections, with incomplete
  coverage disclosed and the last complete reconciliation stamp preserved.
- Existing user changes are preserved, and local or unmerged work is distinguished
  from delivered default-branch work.

The scenario checks were instruction-level review, not execution of simulated
agent sessions. No scientific tool was run and no historical result was regraded.

## Validation boundary

The skill validator accepted both the new reconciliation skill and the modified
issue-review skill. The focused workflow-documentation tests and backlog guards
passed during authoring; `git diff --check` found no whitespace errors.

The required pre-commit gate is
`uv run --locked --extra benchmark -- bash scripts/validate.sh`. Its completion
status and Linux/macOS CI results are reported with the PR for the reviewed head.
These checks do not independently validate scientific claims or replace the
GitHub completeness checks and source review above.
