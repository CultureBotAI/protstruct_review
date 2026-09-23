# Density guidance and T13 generator review — 2026-09-23

## Revision, queue and evidence

The review-open-issues procedure was applied to the complete protstruct_review
queue, adapting its evidence locations to this repository. Local and GitHub
default-branch main both resolved to
`af81a267f24c32bb19ddbf388289cd4fa326bb82` (PR #719). There were no open PRs.
The working branch is `density-t13-corrections-2026-09-23`; its changes are the
live-authoring/generator repair, not new scientific measurements.

The initial GraphQL queue contained all 10 open issues (returned nodes matched
`totalCount`); all bodies and comments were read. Five additional review issues
were filed below. No initial issue is fully resolved on the reviewed main.
Issues #592 and #593, also named in the goal, are already closed: #592's
pass-status documentation exists, and #593's scalar guard was delivered by
PR #705. The intended adjacent scientific corrections are #692 and #693.

Evidence consists of current source code, immutable Eval/QDS files, and the
retained `data/coscientists/openscientist/t13_oracle_logs/ctruncate.log`.
Parser tests recount that saved log and mutate synthetic log text. Execution
tests mock scientific commands; they do not establish fresh CCP4 performance.
No PHENIX or CCP4 scientific executable was invoked for this work. Authoring
guidance searches included ignored files (`rg -uu`), excluding `.git`, `.venv`,
and historical data/research where explicitly scoped to active guidance.

## Full-queue disposition and priority

| Priority | Issue | Disposition and remaining work |
|---|---|---|
| P1 | #694 | Partly stale: active density guidance is corrected in this branch; frozen RSCC/RSR and water conclusions still require the dated #610 correction. Keep open. |
| P1 | #591 | Partly stale: `fail_criterion` already exists; this branch fixes live T13 output. Synthetic and April historical rows remain and require #691/#610. Keep open. |
| P1 | #691 | Reproducible in the frozen synthetic fixture and its active emitter test. Publish a corrected dated pair, then move active tests; do not rewrite history. |
| P1 | #610 | Reproducible architectural blocker: assumption-only suppression cannot correct all cumulative emitted evidence. New contract must construct a validated active evidence view before every builder. |
| P1 | #692 | Historical ProSMART displacement remains mislabelled RSRZ and overinterpreted as Ramachandran confirmation. Correct through #610; retained raw output is unavailable. |
| P1 | #693 | Historical local ion heuristic remains labelled canonical CheckMyMetal and overclaims identity. Correct provenance and conclusions through #610. |
| P1 | #585 | Deck half fixed; September 7 QDS still lacks standalone partial/cumulative context. A discoverable corrected sheet is still required. |
| P2 | #695 | Historical similarity-only pairwise row still says improved. Dated correction must remove directional quality inference. |
| P2 | #580 | Grading harm mitigated on main; original R-factor oracle output remains unavailable. Retain a reproducible rerun or typed unavailable-evidence treatment in the correction. |
| P2 | #720 | Fixed locally: T13 availability/execution share the configured CCP4 environment and shared shell-free runner. |
| P1 | #721 | Fixed locally: missing/truncated/conflicting parser evidence no longer becomes a negative scientific flag or invented operator presence. |
| P2 | #722 | Fixed locally after independent review: rank-only water outliers, fixed RSCC agreement, and RSCC-tail-as-quality instructions removed. |
| P2 | #723 | Fixed locally after independent review: ligand-pose agreement no longer proves correct pose or borrows the Cα calibration. |
| P1 | #724 | Fixed locally: portable, existing repository evidence paths replace absolute refs; the real RI boundary is tested, including external/symlink escapes and missing logs. |
| P1 | #725 | New #610 dependency: explicitly associate dataset subjects with the model sheet before admitting T13 evidence. Do not substitute a model digest for an MTZ digest. |

The order remains: stop new invalid output; replace the active synthetic
fixture; implement correction contract 4 plus the dated real correction. The
historical missing-evidence cases need no invented rerun to unblock honest
reporting: typed unavailability is an acceptable outcome, not a measurement.

## Independent adversarial rounds

1. The T13 implementer identified missing/empty operator-section defaults;
   root reproduced those and the empty ice-table false negative, then filed
   #721 before changes. A separate reviewer found three remaining active
   density contradictions and #722 was filed before fixes.
2. Re-review accepted the #722 fixes, but found the T10 pose rubric answering
   the wrong question and transferring a calibration across atom domains.
   Filed #723; retained informational pose comparison with explicit identity,
   atom correspondence, symmetry handling and receptor frame. The unavailable
   ligand-specific criterion remains an assessment gap, not a passing grade.
3. Independent review accepted the pose changes and found no further concrete
   parser regression, but caught absolute evidence refs at the actual RI
   boundary (#724) and model-only admission of dataset rows (#725). Schema and
   pass-status validation alone had missed the former. The latter is explicitly
   assigned to the new correction contract; legacy emitter replays stay frozen.
4. Re-review of #724 was clean: the reviewer rendered all six retained-log rows
   from foreign cwd `/private/tmp`, and every portable evidence ref passed the
   actual RI checker. Missing/directory/external/nonportable paths were rejected;
   symlink containment and exclusive-output behavior were reviewed. No new
   blocker remained within this live-generator/guidance scope. #725 remains
   the explicit contract-4 dependency, not a reason to falsify dataset identity.

## Live repair boundaries

The six T13 output paths are informational, without placeholder criteria,
unsupported absolute cutoffs or fabricated agent claims. Registry T13
agreement criteria require paired measurements and preconditions absent from
this wrapper. Actual measured values and explicit tool flags are preserved;
unknown flags remain unavailable. Input bytes are identified by SHA-256,
columns are explicit, logs/output MTZs are not overwritten, and input mutation
prevents emission.

RSCC/RSR remain descriptive diagnostics. The drift guard targets the exact
retired authoring instructions across schema, generated models, catalog,
drivers, skill and quality guidance; it is not a semantic proof that every
possible paraphrase is excluded. No numeric threshold was added to the
registry. Generated models and catalog TSV were regenerated from their
authoritative sources (the TSV bytes did not change).

No frozen Eval or QDS was edited. Existing exceptions remain unvalidated
history, not newly endorsed science. In particular this branch must not close
#591 or #694 until their remaining dated corrections are delivered.

## Verification

The clean-main baseline full gate passed before implementation. Focused checks
passed during development: density/domain-boundary guard 79 checks, all eight
governed registry entries, 18 T13 test cases, 16 record-tool checks, Ruff, and
`git diff --check`. After the #724 repair and clean round-4 review,
`PYTHON=.venv/bin/python bash scripts/validate.sh --quiet` completed with exit 0
and `All checks passed!`, including the 18-case T13 suite. An earlier complete
gate also passed before #724; that does not substitute for the final boundary
tests and post-fix gate. `git diff --name-only main -- data` was empty.
