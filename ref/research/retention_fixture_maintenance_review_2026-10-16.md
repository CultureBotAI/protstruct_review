# Retention fixture maintenance isolation — #906

## Observed failure and diagnosis boundary

PR #905's original documentation-only head `e59578f` failed the unchanged
`test_pack_recipe_measures_without_writing_objects` snapshot assertion in both
[macOS attempt 1](https://github.com/CultureBotAI/protstruct_review/actions/runs/38956337590/job/117160038684)
and [attempt 2](https://github.com/CultureBotAI/protstruct_review/actions/runs/38956337590/job/117163388779).
The command and packed-size assertions passed. The truncated snapshot diff showed
directory metadata changing, but did not name the changed path or responsible process.
The runner used Git 2.56.0; the local full gate passed with Apple Git 2.50.1.

Local runs with both Apple Git and an uninstalled upstream Git 2.56.0 build did
**not reproduce that exact directory mismatch**. Trace2 did establish that the
original fixture's setup commit launches detached automatic maintenance. The
diagnostic helper retains full changed-path tuples and Trace2 events when run;
the original retention test now also permits an untruncated unittest diff.

The inspected upstream release is commit
`a018953688f1b10bddf91bff8747068f5f4746a4` (tag `v2.56.0`). Its
[maintenance launcher](https://github.com/git/git/blob/a018953688f1b10bddf91bff8747068f5f4746a4/run-command.c#L1956)
defaults to detached execution, and its
[maintenance task runner](https://github.com/git/git/blob/a018953688f1b10bddf91bff8747068f5f4746a4/builtin/gc.c#L1392)
holds the object directory's `maintenance.lock` across detachment and background
task checks. The setup commit can therefore return before its child removes the
lock. Because the snapshot walks and stats entries separately, that removal can
change directory metadata during collection even if no lock-file row survives.
This is a concrete race in fixture isolation and a plausible explanation of the
CI failure; the truncated original logs do not prove that attribution.

## Bounded correction

`Tree.git` now passes `maintenance.auto=false` and `gc.auto=0` on fixture setup
commands, including calls targeting nested repositories. These are command-line
defaults, not persistent settings or environment changes applied to the audited
shell recipes or inventory CLI. The production inventory, documented pack recipe,
snapshot fields, and strict equality assertion are unchanged.

A regression records actual Git Trace2 setup commands, checks that automatic
maintenance was not launched even when repository configuration enables it, and
uses an explicitly enabled synchronous maintenance command as a positive control.
It exercises the main fixture and another repository through the same helper.

The guard was first run before changing `Tree.git`: both repository cases failed
the `fixture setup launched automatic maintenance` assertion. The retained
[regression proof](retention_fixture_regression_2026-10-16.json) repeats that check
against the old helper in memory and passes against the corrected helper. It does
not revert or modify the reviewed worktree. That proof establishes the guard's
behavior; it is not a claim to have replayed the original CI timing.

## Reproduction and validation

The provenance helpers are:

- `scripts/adhoc/build_git_2_56_for_retention_diagnostic.sh`: fetches the pinned
  upstream release into a new scratch directory and builds Git without installing it.
- `scripts/adhoc/diagnose_retention_pack_snapshot.py`: runs disposable-fixture
  diagnostics, or uses `--check-regression` for the current/historical guard proof.
  Use `--setup-config maintenance.auto=true` to examine the original maintenance
  behavior with the corrected fixture helper. Setup configuration does not alter
  the shell recipe.

To reproduce the retained proof, put the scratch Git build directory first on
`PATH`, then run:

```bash
uv run --locked --extra benchmark -- python -B \
  scripts/adhoc/diagnose_retention_pack_snapshot.py --check-regression
```

With the upstream Git build, the full storage-inventory suite passed with its
filesystem-conditional skip, and the retention-command suite passed. The local
full gate and Linux/macOS CI results for the final reviewed head are reported in
the PR. No scientific tools or experiments are part of this correction.

## Review

An independent read-only design review confirmed setup-only configuration covers
nested repositories and preserves the existing read-only, filter, index, and
reflog controls. A separate implementation review found no material defect in the
tests, helpers, or evidence report. The reviewer compared the historical helper
with `e59578f` and reran the current/historical regression proof with Apple Git
2.50.1 and upstream Git 2.56.0: corrected setup passed and historical setup failed
the intended maintenance assertions. Reviewed-head CI remains required before
merge; its outcome is recorded with the PR.
