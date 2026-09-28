# Standalone evidence driver: engineering acceptance

This is result-free engineering for #799, not a scientific registration or a
benchmark result. No new Reduce/Probe measurement is supplied by this change.
The existing scoring algorithm, registry and historical EVAL/QDS records are
unchanged. #799 and the shared-coordinate decomposition in #790 remain open.

`scripts/bench_dictionary_loaded_reduce.py` defaults to a read-only plan. An
explicit execution accepts one member of the fixed 10-entry clashscore or
41-entry flip cohort, a repository-local registration and a wholly new evidence
root. The external orchestrator must inspect the 24MR canary before expanding
either study and stop on failure. The driver is not a batch runner.

An executed attempt retains input origin/bytes, source and registration copies,
tool/dictionary identities, version-command results, command receipts, full
outputs, H-built coordinates, raw USER MOD records, and hash inventories. The
worker owns a process group with a 900-second timeout. A completed attempt is
not cohort completion, historical same-input reproduction, or grading authority.
Loaded dictionary identity does not establish complete ligand coverage. Parsed
flip decisions and a PHENIX comparator are explicitly unavailable here.

## Review corrections

- **#841:** root reproduced H-coordinate mutation between interpretation and
  hashing, and retained Probe-output mutation after worker completion. Both
  could previously produce a completed attempt with inconsistent evidence.
  Identity now precedes interpretation; strict admission in worker and parent
  binds source/input/H bytes, tool identities, command receipts, manifests,
  raw contacts and the unchanged legacy EC recount. Failed attempts remain
  failures and are preserved. This was a proposed-driver defect, not evidence
  that historical scientific artifacts were corrupted.
- **#844:** unresolved temporary roots caused two fixture assertions on macOS
  path aliases. The fixture now canonicalizes its root. An explicit alias
  regression compares plans and exercises complete evidence through strict
  production admission. Production containment checks are not weakened. The
  companion PR #831 corrects the same fixture class in its retained-evidence
  replay suite; this driver alone does not deliver that companion correction.
- **#847:** the initial integrated full gate rejected the missing shared
  benchmark-environment hook. The driver now announces and retains Python/
  package metadata plus its already verified standalone command evidence inside
  the owned worker, before H-building/scoring. The shared environment helper
  accepts explicit captured tool metadata without probing unrelated tools;
  existing callers retain their default behavior. Plan mode does not announce
  or execute probes. No gate exception or filename-based workaround was added.
- **#850:** macOS CI reached an EPERM error while escalating the ordinary-Python
  timeout test to SIGKILL. The log did not establish the underlying kernel state.
  Cleanup now reaps the owned leader again before escalation; if SIGKILL returns
  EPERM, it recovers only when a further reap and group check establish that the
  group has disappeared. A still-existing group remains a hard cleanup error.
  Deterministic disappearing/still-existing controls supplement the unchanged
  real timeout and descendant-isolation tests; no timeout test is skipped.

The 26 focused tests use mocked scientific/network boundaries, including
mutation controls and both canonical and alias paths. The process timeout test
uses an ordinary Python sleeper, not a scientific program. These engineering
tests do not establish installed-tool compatibility. A reviewed, result-free
scientific registration and one-entry installed-tool canary remain prerequisites
to any batch or scientific conclusion.
