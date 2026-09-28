<task>
From the repository root, take a goal through the full change cycle in the
structural-biology evaluation harness (GitHub repo CultureBotAI/protstruct_review):

  survey → triage and prioritize → branch → work → push → PR → adversarial review
         → file issues → address → pause for approval → merge → clean up

Use this with /goal. State which phase you are in as you go, and do not skip a phase because the
change looks small — docs-only and "obviously safe" changes are exactly the category that lands on
main by accident and carries wrong numbers into the registry.

Two rules override everything else in this prompt:
  1. MERGING IS THE USER'S CALL. Never merge without explicit go-ahead in the current conversation.
     Approval of a previous PR is not approval of this one.
  2. BRANCH BEFORE THE FIRST EDIT, not after the work is done.

Use the repository-selected Python 3.12 and `uv sync --locked --extra benchmark`.
The required local gate is `uv run --locked --extra benchmark -- bash scripts/validate.sh`;
it includes the tolerance unit suite and must exit 0 before commit. CI runs the same command
on Ubuntu and macOS for PRs and main pushes. Python 3.11 remains supported, but its locked Biotite
version differs; a Python 3.11 or no-extra run can skip exact evidence replays and is not CI-equivalent.
Before merging, both `validate (ubuntu-latest)` and `validate (macos-latest)` must report SUCCESS
for the reviewed head. External-tool runs remain opt-in, not part of this hermetic gate.
</task>

<survey>
Before proposing anything, establish state and report it in one short paragraph:

  set -euo pipefail
  issue_queue="$(mktemp "${TMPDIR:-/tmp}/protstruct-issues.XXXXXX")"
  pr_queue="$(mktemp "${TMPDIR:-/tmp}/protstruct-prs.XXXXXX")"
  gh issue list --repo CultureBotAI/protstruct_review --state open --limit 5000 \
    --json number,title,body,comments,labels,url > "$issue_queue"
  gh pr list --repo CultureBotAI/protstruct_review --state open --limit 5000 \
    --json number,title,baseRefName,headRefName,mergeable,mergeStateStatus,url > "$pr_queue"
  totals="$(gh api graphql -f query='query { repository(owner:"CultureBotAI", name:"protstruct_review") { issues(states:OPEN) { totalCount } pullRequests(states:OPEN) { totalCount } } }')"
  test "$(jq length "$issue_queue")" -eq "$(jq -r '.data.repository.issues.totalCount' <<< "$totals")" || { echo "Incomplete issue queue" >&2; exit 1; }
  test "$(jq length "$pr_queue")" -eq "$(jq -r '.data.repository.pullRequests.totalCount' <<< "$totals")" || { echo "Incomplete PR queue" >&2; exit 1; }
  git branch --show-current && git status --short
  git fetch origin && git log origin/main..HEAD --oneline
  uv run --locked --extra benchmark -- bash scripts/validate.sh

Note specifically: whether main has moved, whether any open PR is based on another branch rather
than main (see <pr_dependencies>), and whether the working tree is clean. Read every saved issue
body and comment. If a count differs, paginate/increase the limit or re-fetch a changed queue;
do not claim a complete survey until both list counts equal the API totals. Stop on any command
failure and disclose unavailable remote state rather than treating it as an empty queue.
</survey>

<triage>
For each open issue decide: is it real, how bad, and what does it block? Verify the claim yourself
against the data or the code before accepting it — an issue can be wrong, and a false finding acted
on is its own defect.

Rank by:
  1. A wrong or unsupported PUBLISHED claim — a bad number, a stale figure, an overstated verdict.
     Highest, because every downstream document inherits it.
  2. A GUARD THAT DOES NOT GUARD — a test or gate that would pass with the defect present. Nearly as
     bad as the defect, because it hides the whole class.
  3. A SILENT FAILURE PATH — anything that degrades to "no output" rather than an error.
  4. STALENESS — a figure that was right when written and is not now.
  5. READABILITY of load-bearing text — a correct claim nobody can parse still misleads.

Then say which you will fix in THIS change and which stay filed, and why. "As needed" is a
judgement, not a rubber stamp: fixing everything at once produces an unreviewable diff.
</triage>

<work>
Branch first: `git checkout -b <short-descriptive-name>`.

CANARY BEFORE ANY COSTLY BATCH — downloads, refinements, billed calls, mass rewrites. Run exactly
one unit end to end through the SAME script and cache the batch will use, then verify the SIDE
EFFECTS, not the exit code: the row is in the committed file, it is non-empty, the artefact is on
disk. Say what the canary did and did not exercise, and treat the rest as unverified.

If the change produces a measurement or tests a hypothesis:
  - Register predictions in a commit CONTAINING NO RESULTS, so the registration is verifiable in git
    history rather than asserted afterwards.
  - Work out the statistical power AND the sampling cost first. A cheap selector is not a cheap
    experiment. Write down in advance the outcome where the round cannot answer the question — that
    is a real result, not a failure.
  - Predict the comparison you care about, not an interval around a point estimate.
  - Every figure a document quotes must come from a committed, re-runnable script.

CHECK THE BRANCH AGAIN BEFORE YOU STAGE. Rule 2 guards the START of the work; this guards the end,
and the two are separated by however long the work took — which is exactly when "I branched, so I am
on the branch" stops being true. Immediately before `git add`:

    git branch --show-current && git status --short

and read the staged list back before committing. Confirm it is the work you mean and NOTHING ELSE.
An intervening `git checkout` — to read a file, to check another PR — leaves you somewhere else with
no warning, and `git add -A` does not care. This has happened here: a 19-file audit round landed on
an unrelated docs branch and had to be cherry-picked back onto main. It was recoverable only because
it had not been pushed yet.

Commit messages state what changed, WHY, and what failure it prevents. Push, then open a PR whose
body a reviewer could act on without reading the diff first.

List the exact intended issue closures and the separate outstanding issues. Automatic closing
directives belong only on fully completed issues. Never negate a closing directive: GitHub can
still interpret it as a closure (#815). Use neutral “Related” or “Remaining work” references for
unfinished scope, and check both the PR body and planned squash message for unintended directives.
</work>

<review_contract>
The review is a SEPARATE, READ-ONLY pass. Do not edit, push, or fix while reviewing. Re-read the
diff as someone trying to find what is wrong with it, not as the person who wrote it.

Re-derive every quoted figure FROM THE COMMITTED ARTEFACT — not from the prose, and not from a
rounded table. If a document cites a script, run that script and diff its output against the text.

Check specifically:
  - NUMBERS vs the data. Counts, medians, denominators, n. Recompute; do not read.
  - DOES THE CLAIM MATCH THE ARITHMETIC? The arithmetic being right is not the claim being right.
    Watch for a stronger version of a true result: "validated" for "measured on a subset",
    "independent" for a re-run of the same inputs, "across versions" for one pinned binary.
  - DENOMINATORS. Did a count silently change meaning? Is n stated anywhere?
  - GUARDS. Would the new test fail against the old behavior? Prove the expected failure using
    an in-memory historical implementation or an isolated scratch copy/fixture. Never revert or
    restore the reviewed worktree; it remains read-only (#817). Record exactly which assertion
    failed, not merely an import/setup error.
  - SIBLINGS. If this fixes one instance of a defect class, grep for the others. A defect fixed in
    one script is usually still present in its neighbour.
  - LEAD SENTENCES. In the long §3/§4 rows of ref/thresholds_and_standards.md the bolded opener is
    what actually gets read; a correction buried mid-cell is not a correction.
  - SCOPE LIMITS. Does the write-up's own caveat section contradict its headline?

Delegating breadth to sub-agents is useful — they read the diff without the author's memory of
intending something. VERIFY EACH FINDING YOURSELF before acting on it.

REVIEW THE FIX COMMITS TOO. Fixes written under review pressure are where new defects go.
</review_contract>

<issues_and_fixes>
File one GitHub issue per finding BEFORE fixing any of them. An issue is the record that the finding
existed even when the answer is "won't fix". Each states: the claim, why it is wrong, the evidence
quoted, a suggested fix, and a severity.

Then fix what belongs in this change; leave the rest filed and say which is which. Re-run the gate
and the tests, and re-verify each corrected figure against its source — a fix that introduces a new
wrong number is common.

Record what the review found in the change's own audit trail under ref/research/. A defect caught
and quietly fixed teaches nobody; the pattern across several is usually the more valuable finding.
</issues_and_fixes>

<pr_dependencies>
DELETING A BASE BRANCH DOES NOT RETARGET ITS DEPENDENT PRs — GITHUB CLOSES THEM. This is the trap
worth remembering; it costs a branch rebuild every time.

When PR B is based on PR A's branch:
  1. Merge A first. There is no other order — B's diff is meaningless without A.
  2. Deleting A's branch CLOSES B. Either retarget B to main before deleting, or expect to rebuild.
  3. After A is squash-merged, B's branch still holds A's individual commits, which main no longer
     has. Rebuilding B on main and re-applying only B's own changes is cleaner than merging:

         git checkout -b <rebuilt> origin/main
         git diff <B-first-commit>^..<B-head> > /tmp/b.patch     # NOTE the ^
         git apply --3way /tmp/b.patch

     The `^` is load-bearing. `git diff <first>..<head>` starts AFTER that commit and silently drops
     it — on the round-19 rebuild this recipe came from, that would have lost the entire
     pre-registration document, i.e. the commit proving predictions were made before the data.
     Diff from the PARENT of B's first commit, and check the file count against `git show --stat` on
     each of B's commits before trusting the patch. Do not diff from the shared ancestor either, or
     you replay A's work too.
  4. Where both touched the same lines, resolve by KEEPING BOTH SIDES — a late fix in A and a change
     in B are usually both wanted. Afterwards, verify explicitly that none of A's fixes were dropped.

If more than two are stacked, say so and propose an order before touching anything.
</pr_dependencies>

<merge_and_cleanup>
PAUSE. Summarize what merging would land, then wait for explicit go-ahead.

On approval, match the repo's existing merge style (squash; main's history is one commit per round,
titled "... (#NN)"):

  uv run --locked --extra benchmark -- bash scripts/validate.sh  # must exit 0
  gh pr view <N> --repo CultureBotAI/protstruct_review --json headRefOid,baseRefName,statusCheckRollup,closingIssuesReferences
  gh pr merge <N> --repo CultureBotAI/protstruct_review --squash --match-head-commit <reviewed-sha>
  git checkout main && git pull
  gh issue close <fixed> --comment "Fixed in #<N>, merged to main as <sha>."

Before the merge command, verify the exact headRefOid equals the reviewed SHA, the base is correct,
and both named CI jobs above succeeded for that head. If the head changes, repeat review and
validation. Compare closingIssuesReferences with the exact intended closure list, including an
empty list when nothing is fully resolved. Inspect the planned squash message as well; GitHub's
closing references are not a substitute for checking its commit-message directives.

Do not delete a base branch while dependent PRs still target it. After the merge is confirmed,
resolve the exact local/remote branch tips, verify the merged content, and delete only the authorized
completed branch. Prefer ordinary local `git branch -d`; a squash merge can require explicit `-D`,
but only after content verification, not as an unconditional cleanup step. Preserve unrelated
changes and worktrees; do not switch or pull across a dirty worktree just to follow this example.

Then confirm each separately — PR merged, REMOTE branch gone (`git ls-remote --heads origin
<branch>`), local branch gone, intended issues closed, outstanding issues still open, gate green on
main. Verify both closure and non-closure against the pre-merge lists (#815). Do not infer the remote from the
local deletion; they are done by different commands. Note that squash
merging collapses the pre-registration commit, so a write-up citing a bare hash will not resolve
from main — cite the PR instead.
</merge_and_cleanup>

<pause_points>
Stop and ask a direct question with concrete options — never "shall I proceed?" — when:
  - Merging anything.
  - Priorities depend on what the user wants rather than on the code.
  - A fix would change an already-published result or a tolerance band.
  - Force-pushing a shared branch, reverting on main, or deleting anything you did not create.
  - Scope has grown past what was asked.
  - You would otherwise guess.

Do NOT pause for reversible work that follows from the request, or a choice with an obvious default.
Make it, say you made it, and carry on.
</pause_points>

<recurring_traps>
Defects this repo has actually shipped and then caught. Check for these by name:
  - A figure recomputed from a ROUNDED table instead of the source (round 17's +4.787 %, and again
    in round 22's rank correlation).
  - A statistic that ages silently when the dataset grows, quoted with no n.
  - A count that switches convention — same word, different denominator (53 → 69 for +10 entries).
  - A relative gate bounded at one end only; check what happens at zero.
  - "It reproduces" when the same pinned binary ran on the same inputs.
  - A subset re-run described as independent corroboration.
  - A fix applied to one script and not its sibling.
  - A test named for the thing it does not actually exercise.
  - A conclusion that lands, by coincidence, in the direction that FLATTERS THE HYPOTHESIS UNDER
    TEST. Check those hardest — round 23's miscount turned "one near-miss against" into "none
    examined".
</recurring_traps>

<action_safety>
Read-write, but bounded. Never merge, force-push a shared branch, revert on main, or delete a branch
you did not create without explicit approval in the current conversation. The review phase is
strictly read-only. Leave the working tree clean and on main when finished.
</action_safety>
