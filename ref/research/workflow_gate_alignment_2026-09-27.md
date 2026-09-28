# Workflow gate alignment — 2026-09-27

Active guidance correction for #762 and the related workflow defects #815, #817
and #819. Baseline: `df011cc`. Historical scientific records, numeric thresholds,
issued sheets, and CI execution behavior are unchanged.

## Evidence and changes

`.github/workflows/validate.yml` already synchronizes and runs the locked
`benchmark` extra on Ubuntu and macOS. The active routing docs now prescribe
those same commands and the repository-selected Python 3.12. `uv.lock` selects
Biotite 1.6.0 below Python 3.12 and 1.7.1 on Python 3.12; the retained T15/BSA
evidence names 1.7.1. Their tests explicitly skip exact numeric replay under
other versions. Therefore the extra alone is not an interpreter-independent
claim of CI parity. Python 3.11 remains supported with that scope caveat.

The backlog prompt and issue-review skill collect explicitly targeted full
queues, including issue bodies/comments, and compare list sizes to API totals.
The merge checklist checks the reviewed head, both CI jobs, intended automatic
closures and the squash message; it separately verifies outstanding issues
remain open after merge. PR #811 demonstrated why: a negated closing directive
still caused GitHub to mark #799 complete. The wording was corrected and #799
reopened because its scientific work was unfinished (#815).

Review negative controls now use in-memory historical code or isolated scratch
fixtures rather than mutating and restoring the reviewed checkout (#817). The
prompt starts from the repository root instead of a personal absolute path
(#819). Cleanup is conditional on verified merged content, exact branch identity,
dependency checks and authorization; it is not a blanket force-delete recipe.

## Verification scope

`scripts/test_workflow_docs.py` compares active guidance with the CI commands and
checks the survey/review/merge safeguards. Its five hermetic tests include
in-memory mutations for missing extras, interpreter scope, truncated surveys,
read-only review and intended-closure checks. Loading the actual baseline docs
from git into memory produces the expected rejection, including the no-CI and
incomplete-survey defects; this is not a checkout/revert test. These are bounded
documentation regressions, not a proof that arbitrary prose can be interpreted
semantically or that GitHub operations were executed by the tests.

Independent review and the final full-gate result are reported in the PR. No
licensed scientific tool, online benchmark or measurement was run for this
documentation correction.
