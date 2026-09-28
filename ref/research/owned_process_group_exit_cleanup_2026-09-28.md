# Owned process-group cleanup after wrapper exit — 2026-09-28

Issue #858 is an execution-boundary defect, not a scientific result. The prior
`EntrySandbox.run_logged()` cleaned its owned group on timeout or an exception
from `communicate()`, but returned directly when the wrapper exited normally,
with a nonzero status, or from a signal. A wrapper can exit while descendants
remain in the same group, so those return codes alone do not make retained
outputs safe to audit.

## Bounded change

Every completed `communicate()` path now checks and cleans the recorded PGID
before returning to the caller. It preserves the original wrapper return code,
signal and timeout status. Remaining group members receive SIGTERM followed by
SIGKILL if necessary, scoped exclusively to the recorded group created by
`start_new_session=True`. No process-name matching, global process scan or
unrelated-group termination is introduced.

Cleanup requires the wrapper to be reaped and `killpg(pgid, 0)` to report group
absence. The configured TERM grace must be finite and nonnegative. The
post-escalation leader-reap/group-observation phase has a one-second timeout
budget, rather than an unbounded final `communicate()`. These are process-control
parameters, not scientific or quality thresholds. Scheduling and system-call
latency are not real-time guarantees.

The #850 SIGKILL PermissionError correction is retained: suppression requires
both an exited leader and a fresh absent-group observation. A live or uncertain
group still fails. A successful signal syscall or reaped leader is not itself
evidence that every group member has disappeared.

`ProcessGroupResult.cleanup` retains the group check outcome and signal attempts.
An explicit `[entry_sandbox cleanup]` JSON record is appended to the combined
launch log on success and failure. The log is therefore an instrumented launch
log, not a byte-for-byte standalone stdout stream. Existing separate scientific
stdout/stderr capture paths are unchanged.

Unresolved cleanup raises before a caller receives a successful process result.
If execution already raised an exception, that original exception is preserved,
with cleanup evidence attached and any cleanup failure chained as its cause.
The log retains both facts. Failure to write diagnostics is disclosed on an
existing exception rather than replacing it; if there is no prior exception,
the write failure is itself fatal. An otherwise handled timeout is re-raised as
the original `TimeoutExpired` if diagnostic write, flush or close fails; its
cleanup evidence and diagnostic notes remain observable to the caller.

## Conservative process-state interpretation

`killpg(pgid, 0)` does not distinguish a running descendant from an unreaped
zombie, and PermissionError does not prove absence. If the group remains present
or unqueryable after the bounded attempt, the outcome is unresolved—even when
the leader has already exited or the remaining members might be zombies. The
implementation neither fabricates a live-process count nor labels a group
absent solely from the leader's status. Harmless but unreaped zombie groups can
therefore cause conservative refusal.

The guarantee is limited to the recorded PGID. Descendants that deliberately
detach into another process group/session are not discovered or killed. This
does not establish containment against hostile executables, immutable artifacts
against unrelated writers, or successful cleanup after abrupt termination of
the orchestrator itself. An unresolved attempt is surfaced, not automatically
retried through process-name searches or stale group identifiers.

The new optional result field preserves construction compatibility for existing
mocked/historical records. A missing or null field does not retrospectively
certify cleanup of an old execution. No retained historical process record,
scientific evidence, grade, cache or benchmark algorithm is rewritten.

## Focused verification

`scripts/test_entry_sandbox.py` passes 427 checks, including:

- All four deterministic #850 exited/live-leader and absent/present-group cases.
- Mocked wrapper exit codes 0, 1 and SIGKILL with both cooperative and
  TERM-ignoring surviving groups; status preservation and retained diagnostics.
- Still-present/unqueryable groups after escalation, bounded leader reaping,
  invalid grace values and primary-exception preservation when cleanup or
  diagnostic writing fails.
- Ordinary Python wrappers that exit 0, 1 or SIGKILL after their child confirms
  SIGTERM-ignore. The group is verified absent before return, and the child does
  not later write its survival marker.
- Existing timeout, descendant, entry-isolation and concurrent-cancellation
  controls.
- The #865 public-entrypoint diagnostic matrix: 40 combinations of primary
  exception, cleanup outcome and write/flush/close failures, plus two launch
  failures. A real file lies beneath the fault-injecting handle, and its actual
  `close()` method is called exactly once. Tests check original exception
  identity, retained notes and cleanup evidence, unchanged explicit cleanup
  cause, and clearing of the active-process registry.

With the candidate adapter explicitly first in the import path, the existing
dictionary-driver suite passes 26 tests and round-10 mocked suite passes 23
checks. Three scratch-only in-memory controls remove completion cleanup,
post-signal absence verification, or the leader-reap timeout. Each reaches its
intended assertion failure without launching real processes or changing source.
Ruff correctness checks pass.

No scientific executable, version probe, network call, full repository gate or
historical remeasurement was run for this bounded engineering proposal. The
candidate still requires independent review, the full integration gate and
Linux/macOS CI before merge.

## Independent integration finding #865

The pre-integration review found two diagnostic-preservation defects, reproduced
by the integrator and filed before this correction. First, a log-write failure
was attached to an otherwise handled `TimeoutExpired` that was then discarded
when a timeout result was returned. Second, the log context manager's final close
could replace a preserved execution exception, including `KeyboardInterrupt`.
Neither reproduction demonstrated a surviving-group false success: both used
successful cleanup, and existing callers still reject timeout results.

The corrected boundary closes the log explicitly. A propagating launch,
execution or cleanup exception remains the exact same object; diagnostic
failures are notes, and simultaneous cleanup failure retains its original
explicit cause. When no exception would otherwise escape, a diagnostic failure
is fatal. In the timeout case, the same original timeout is raised with cleanup
evidence instead of silently losing the only diagnostic-failure note. The fix
does not change process signalling, group observation, cleanup bounds or result
fields.

Scratch-only controls preserve the pre-#865 adapter and restore each removed
guard independently in memory. The old adapter fails the combined write/close
case. Removing timeout write/flush propagation, close exception preservation or
timeout-close propagation causes the intended assertion failure, not a setup
error. These controls execute only the deterministic mocked test prefix, with
no process or scientific tool launches. The corrected full focused suite still
includes ordinary Python process checks. Historical evidence and scientific
outputs are unchanged.
