---
name: review-open-issues
description: Sweep and prioritize the complete protstruct_review GitHub issue queue against current main, scientific records, guards, and repository invariants. Use when asked to review issues, triage the backlog, identify urgent work, or reconcile NEXT_TASKS.md with GitHub. Produces a read-only ranked report by default; it does not close, relabel, comment on, or implement issues unless the user separately asks.
---

# Review and prioritize open issues

## Purpose and boundary

Sweep the entire open-issue queue, verify each issue against the current default
branch, group overlaps, and produce an evidence-backed priority ranking.
`NEXT_TASKS.md` is a curated working view, not the issue source of truth; compare
it with GitHub but do not treat its contents as proof that an issue is live.

This skill triages work. It is read-only by default and does not implement fixes,
edit `NEXT_TASKS.md`, close or relabel issues, post comments, or maintain a tracker
unless the user explicitly requests that separate mutation.

Before triage, read the repository routing and authority files:

1. `CLAUDE.md`
2. `CODING_STANDARDS.md`
3. `.claude/skills/protstruct-eval/SKILL.md` when scientific claims, oracle
   coverage, QDS output, catalog entries, thresholds, or benchmark records are
   involved

## 1. Establish current state

Refresh and inspect the default branch, local tree, and open PR dependencies:

```bash
review_dir=$(mktemp -d "${TMPDIR:-/tmp}/protstruct-review-triage.XXXXXX")
git fetch origin
git branch --show-current
git status --short
git log origin/main..HEAD --oneline
gh pr list --repo CultureBotAI/protstruct_review --state open --limit 5000 \
  --json number,title,baseRefName,headRefName,mergeable,mergeStateStatus,url \
  > "$review_dir/open-prs.json"
jq . "$review_dir/open-prs.json"
gh api graphql -f query='query {
  repository(owner:"CultureBotAI", name:"protstruct_review") {
    issues(states:OPEN) { totalCount }
    pullRequests(states:OPEN) { totalCount }
    defaultBranchRef { name target { oid } }
  }
}' > "$review_dir/queue-totals.json"
jq -e --slurpfile totals "$review_dir/queue-totals.json" \
  'length == $totals[0].data.repository.pullRequests.totalCount' "$review_dir/open-prs.json"
```

State whether `main` has moved, whether the tree is clean, and whether any open
PR is based on a non-main branch. An issue implemented only on an unmerged branch
is still open work. If the user's read-only boundary prohibits fetching, compare
against the API's default-branch SHA without changing local refs; disclose stale
or unavailable local state. Use the user-approved scratch location when one is
specified, rather than the generic temporary directory above.

## 2. Fetch the complete issue queue

```bash
gh issue list --repo CultureBotAI/protstruct_review --state open --limit 5000 \
  --json number,title,body,labels,comments,createdAt,updatedAt,url \
  > "$review_dir/open-issues.json"
jq -r '.[] | [.number, .createdAt[:10], .title] | @tsv' "$review_dir/open-issues.json"
jq length "$review_dir/open-issues.json"
jq -e --slurpfile totals "$review_dir/queue-totals.json" \
  'length == $totals[0].data.repository.issues.totalCount' "$review_dir/open-issues.json"
```

Read and assess the saved bodies, labels, and comments, not only the title list.
Omitting `--limit` silently samples the first 30. Require successful commands and
compare both saved list counts with the API totals before claiming complete
coverage. If either count differs, increase the limit or paginate and re-fetch
the totals; if the queue changed during collection, refresh both lists and totals.
If a complete consistent collection cannot be obtained, report coverage as
incomplete rather than treating a partial list or failed query as an empty queue.

## 3. Group without hiding issues

Group likely overlaps by shared PR/review origin, file or function, failure mode,
and dependency. Identify umbrella/tracking issues separately from actionable leaf
issues: a tracker inherits the priority of its most urgent live child but is not
itself the next implementation unit.

Keep every issue visible in the report. A grouping is not permission to silently
merge or close issues.

## 4. Verify each issue against current reality

For every open issue, determine whether it is live, fixed/stale, duplicate,
superseded, blocked, or an umbrella.

### Main-branch and PR evidence

- Search only the refreshed default branch for an exact issue reference:

  ```bash
  git log --oneline origin/main --perl-regexp --grep '#<N>\b'
  ```

  Do not use `--all`; unmerged work is not a fix. The word boundary is
  load-bearing because a plain search for `#48` also finds `#480`.
- Query exact linked PRs with:

  ```bash
  gh issue view <N> --repo CultureBotAI/protstruct_review \
    --json closedByPullRequestsReferences
  gh pr view <PR> --repo CultureBotAI/protstruct_review --json mergedAt,state,url
  ```

  Do not infer linkage from a bare-number PR search.
- Confirm that cited files, functions, schema fields, generated views, and tests
  still exist in the described form. A moved line number is not itself stale;
  test the underlying claim.

### Scientific and publication evidence

- Recompute quoted counts and figures from committed machine-readable records or
  their committed derivation scripts. Do not accept prose, rounded tables, issue
  labels, or `NEXT_TASKS.md` as the source.
- Check whether a quantitative claim is independently re-measured and whether a
  non-cctbx oracle supports every load-bearing PHENIX result. A PHENIX-grades-
  PHENIX path violates the trust model even when its arithmetic is correct.
- For QDS/emitter issues, test whether scoped or implied content can be silently
  dropped and whether the cross-tool coverage guard fails closed.
- For schema/catalog issues, inspect canonical sources and generated views:
  `ref/catalog.yaml` owns the TSV; `schemas/protstruct_review.yaml` owns
  `protstruct_review/models.py`. Never diagnose drift from a generated file alone.
- When authorized and useful for a claim, use focused hermetic tests with
  `uv run --locked --extra benchmark -- python scripts/test_<area>.py`, or the
  required gate `uv run --locked --extra benchmark -- bash scripts/validate.sh`.
  Use repository-selected Python 3.12 (`.python-version`), bootstrapped with
  `uv sync --locked --extra benchmark`. Python 3.11 remains supported, but its
  locked Biotite 1.6.0 skips exact retained T15/T16 replays from 1.7.1; a clean
  no-extra environment also skips them. Neither is equivalent to the required
  gate. Dependency installation may need network access; after installation the
  gate itself is offline. Do not launch licensed PHENIX/CCP4 runs, online data
  fetches, or costly benchmark batches merely to triage. Mark evidence requiring
  an optional external rerun as unverified and explain what is missing.

### Guard evidence

For an alleged guard gap, identify the exact malformed input or reverted defect
that would still pass. A test name is not evidence that the behavior is covered.
Prefer an existing negative test or a non-mutating temporary reproduction.

## 5. Assign priority and blockage

Prioritize the consequence, not the age or amount of work.

- **P0 — published correctness, silent corruption, trust, or security.** A wrong
  or unsupported published scientific claim; silent loss or corruption of QDS,
  catalog, schema, or benchmark content; a cross-tool trust violation that can
  reach a verdict; a security defect; or a universally hit crash/hang that blocks
  releases. A guard hole is P0 only when it permits one of these outcomes to pass
  undetected.
- **P1 — real and should be scheduled soon.** A reproducible narrower defect;
  a hermetic-gate or reproducibility failure; a safety-relevant guard gap without
  evidence of current published corruption; authoritative documentation that
  can direct contributors into an invalid workflow; or a process defect with a
  demonstrated near-miss.
- **P2 — maintenance, clarity, or low-risk process.** Publication metadata,
  documentation/readability drift that does not change a scientific conclusion,
  consolidation, cadence policy, minor non-critical test gaps, and cleanup.

Use P0 sparingly and justify it. For each issue state what it blocks: publication,
QDS emission, the hermetic gate, benchmark reproducibility, a later issue, or
nothing immediate. Note dependency order explicitly; prerequisites outrank work
that cannot start safely without them.

## 6. Present the report

Report:

- the exact number of issues reviewed and whether coverage was complete;
- grouped ranked lists, P0 first, with every issue number and a one-sentence
  evidence-based rationale;
- fixed/stale, duplicate, and superseded closure candidates with the specific
  main commit, merged PR, or current-code evidence;
- disagreements between GitHub and `NEXT_TASKS.md`;
- the top two or three actionable leaf issues, in recommended execution order;
- important uncertainty, especially where optional external tools would be
  needed to reproduce a claim.

Do not drop old issues. Age is useful context, not evidence of staleness.

## 7. Mutate only when separately authorized

The review itself never changes GitHub or repository state. If the user later
asks to act:

- confirm exact issue numbers before closing stale or duplicate issues;
- close one issue at a time with a comment citing the verified evidence;
- update an existing umbrella tracker rather than creating a duplicate, after
  verifying that tracker is still open;
- follow `prompts/backlog-loop-goal.md` for implementation: branch before the
  first edit, use a separate read-only adversarial review, file findings before
  fixing them, run the hermetic gate, and pause for explicit merge approval.

## Recurring traps

- A figure recomputed from a rounded presentation instead of its source record.
- A count whose denominator silently changed or is not stated.
- “Independent corroboration” that reused the same code family, binary, or
  inputs.
- A correct arithmetic result promoted into a stronger scientific claim.
- A guard that checks a summary copied from rows rather than re-deriving it.
- One fixed script with an unfixed sibling carrying the same defect.
- A tracking issue ranked as if it were a small actionable patch.
- A result that happens to flatter the hypothesis and therefore receives less
  scrutiny rather than more.
