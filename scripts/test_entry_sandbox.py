#!/usr/bin/env python3
"""Network-free tests for per-entry process isolation (#356)."""
from __future__ import annotations

import json
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

from entry_sandbox import EntrySandbox, ProcessGroupCleanupError

PASSED = 0


def check(label, got, want):
    global PASSED
    if got != want:
        print(f"FAIL  {label}: got {got!r}, want {want!r}")
        sys.exit(1)
    PASSED += 1
    print(f"PASS  {label}")


# Deterministic boundary controls for #850; no real signal or process is used.
for disappears, leader_exited in ((True, True), (False, True), (False, False), (True, False)):
    state = {"exists": True, "raced": False}
    process = mock.Mock()

    def poll():
        if state["raced"] and disappears:
            state["exists"] = False
        return -signal.SIGTERM if state["raced"] and leader_exited else None

    def signal_group(pgid, sig):
        check("cleanup signals only its supplied owned PGID", pgid, 424242)
        if sig == signal.SIGKILL:
            state["raced"] = True
            raise PermissionError("synthetic escalation race")

    process.poll.side_effect = poll
    with mock.patch.object(EntrySandbox, "_group_exists", side_effect=lambda pgid: state["exists"]), \
            mock.patch("entry_sandbox.os.killpg", side_effect=signal_group):
        try:
            EntrySandbox._terminate_group(process, 424242, 0)
        except PermissionError:
            refused = True
        else:
            refused = False
    recoverable = disappears and leader_exited
    check("EPERM recovers only with an exited leader and absent group", refused, not recoverable)
    check("unresolved EPERM is not followed by potentially blocking communicate",
          process.communicate.call_count, int(recoverable))
    check("leader is reaped before escalation and after EPERM", process.poll.call_count, 2)


# #858: wrapper completion is not proof that its process group is absent.
# All signals and processes in this block are mocks.
with tempfile.TemporaryDirectory() as temporary:
    sandbox = EntrySandbox(temporary, "mocked-exits")
    for returncode in (0, 1, -signal.SIGKILL):
        for ignores_term in (False, True):
            process = mock.Mock(pid=424242, returncode=returncode)
            process.poll.return_value = returncode
            state = {"exists": True}

            def signal_group(pgid, sig):
                check("post-exit cleanup targets only the owned PGID", pgid, 424242)
                if sig == signal.SIGKILL or not ignores_term:
                    state["exists"] = False

            with mock.patch("entry_sandbox.subprocess.Popen", return_value=process), \
                    mock.patch.object(EntrySandbox, "_group_exists", side_effect=lambda pgid: state["exists"]) as exists, \
                    mock.patch("entry_sandbox.os.killpg", side_effect=signal_group):
                result = sandbox.run_logged(["mock-program"], "exit.log", terminate_grace=0)
            check("all exit classes check the owned group", exists.call_count > 0, True)
            check("descendant cleanup preserves the original wrapper status", result.returncode, returncode)
            check("ordinary exit cleanup does not masquerade as timeout", result.timed_out, False)
            check("successful result retains verified group absence", result.cleanup["group_absent_verified"], True)
            check("cleanup records TERM and any required KILL", result.cleanup["signal_attempts"],
                  ["SIGTERM", "SIGKILL"] if ignores_term else ["SIGTERM"])
            retained = json.loads(sandbox.child("exit.log").read_text().split("[entry_sandbox cleanup] ")[1])
            check("launch log retains the same cleanup evidence", retained["cleanup"], result.cleanup)
            check("active registry clears after completed cleanup", EntrySandbox.active_pgids(), [])

    process = mock.Mock(pid=424242, returncode=0)
    with mock.patch("entry_sandbox.subprocess.Popen", return_value=process), \
            mock.patch.object(EntrySandbox, "_group_exists", return_value=False), \
            mock.patch("entry_sandbox.os.killpg") as signals:
        result = sandbox.run_logged(["mock-program"], "absent.log")
    check("already absent group needs no signal", signals.call_count, 0)
    check("already absent group still has a verified cleanup outcome", result.cleanup["status"], "group_absent")

    for returncode in (0, 1, -signal.SIGKILL):
        process = mock.Mock(pid=424242, returncode=returncode)
        with mock.patch("entry_sandbox.subprocess.Popen", return_value=process), \
                mock.patch.object(EntrySandbox, "_group_exists", return_value=True), \
                mock.patch("entry_sandbox.os.killpg"), \
                mock.patch("entry_sandbox._CLEANUP_REAP_TIMEOUT", 0):
            try:
                sandbox.run_logged(["mock-program"], "unresolved.log", terminate_grace=0)
            except ProcessGroupCleanupError as error:
                record = error.cleanup_record
            else:
                raise AssertionError("A present/unknown group must not return an admissible result")
        check("reaped leader does not excuse a present or zombie group", record["status"], "unresolved")
        check("unresolved cleanup never claims verified absence", record["group_absent_verified"], False)
        retained = json.loads(sandbox.child("unresolved.log").read_text().split("[entry_sandbox cleanup] ")[1])
        check("unresolved cleanup retains original leader status", retained["leader_returncode"], returncode)
        check("unresolved cleanup is retained in the launch log", retained["cleanup"], record)

    for primary in (KeyboardInterrupt("synthetic interrupt"), OSError("synthetic communicate failure"),
                    subprocess.TimeoutExpired(["mock-program"], 1)):
        for cleanup_fails in (False, True):
            process = mock.Mock(pid=424242, returncode=-signal.SIGTERM)
            process.communicate.side_effect = primary
            cleanup_error = PermissionError("synthetic group permission failure")
            cleanup = {"status": "unresolved" if cleanup_fails else "group_absent", "pgid": 424242,
                       "group_absent_verified": not cleanup_fails}
            cleanup_error.cleanup_record = cleanup
            with mock.patch("entry_sandbox.subprocess.Popen", return_value=process), \
                    mock.patch.object(EntrySandbox, "_terminate_group", side_effect=cleanup_error if cleanup_fails else None,
                                      return_value=cleanup) as cleanup_call:
                caught = None
                try:
                    result = sandbox.run_logged(["mock-program"], "exception.log")
                except BaseException as error:
                    caught = error
            check("exception path always attempts owned cleanup", cleanup_call.call_count, 1)
            returns_timeout = isinstance(primary, subprocess.TimeoutExpired) and not cleanup_fails
            check("original exception survives cleanup failure", caught is primary, not returns_timeout)
            if cleanup_fails:
                check("cleanup failure remains chained to primary exception", caught.__cause__ is cleanup_error, True)
                check("primary exception retains cleanup evidence", caught.cleanup_record, cleanup)
            elif returns_timeout:
                check("cleaned timeout still returns a timeout result", result.timed_out, True)
            retained = json.loads(sandbox.child("exception.log").read_text().split("[entry_sandbox cleanup] ")[1])
            check("primary exception text is retained", str(primary) in retained["primary_exception"], True)

    for invalid_grace in (-1, float("inf"), float("nan")):
        with mock.patch("entry_sandbox.subprocess.Popen") as launch:
            try:
                sandbox.run_logged(["mock-program"], "invalid.log", terminate_grace=invalid_grace)
            except ValueError:
                refused = True
            else:
                refused = False
        check("unbounded or negative cleanup grace is rejected before launch", refused and launch.call_count == 0, True)

    process = mock.Mock(pid=424242, returncode=None)
    process.communicate.side_effect = subprocess.TimeoutExpired(["mock-program"], 1)
    with mock.patch.object(EntrySandbox, "_group_exists", return_value=False):
        try:
            EntrySandbox._terminate_group(process, 424242, 0)
        except ProcessGroupCleanupError as error:
            record = error.cleanup_record
        else:
            raise AssertionError("An unreaped leader must fail within the cleanup bound")
    check("leader reap call is bounded even when group lookup is absent",
          process.communicate.call_args.kwargs.get("timeout"), 1.0)
    check("unreaped leader cleanup remains unresolved", record["status"], "unresolved")

    # Failure to retain diagnostics cannot mask an existing primary exception.
    primary = OSError("primary communicate error")
    process = mock.Mock(pid=424242, returncode=-signal.SIGTERM)
    process.communicate.side_effect = primary
    handle = mock.MagicMock()
    handle.__enter__.return_value = handle
    handle.write.side_effect = OSError("synthetic disk write failure")
    cleanup = {"status": "group_absent", "pgid": 424242, "group_absent_verified": True}
    with mock.patch("entry_sandbox.subprocess.Popen", return_value=process), \
            mock.patch.object(EntrySandbox, "_terminate_group", return_value=cleanup), \
            mock.patch.object(Path, "open", return_value=handle):
        try:
            sandbox.run_logged(["mock-program"], "log-failure.log")
        except OSError as error:
            caught = error
        else:
            raise AssertionError("The primary execution error must still propagate")
    check("log write failure preserves original exception identity", caught is primary, True)
    check("log write failure is disclosed on the primary exception",
          any("diagnostic write failed" in note for note in caught.__notes__), True)


# #865: use a real retained file underneath a fault-injecting handle. In
# particular, close() itself raises; mocking only __exit__ would not exercise
# the explicit close boundary or establish that the stream was actually closed.
class DiagnosticHandle:
    def __init__(self, path, failures):
        self.stream = path.open("w")
        self.failures = failures
        self.errors = {name: OSError(f"synthetic diagnostic {name} failure")
                       for name in failures}
        self.close_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False

    def write(self, text):
        if "write" in self.failures:
            raise self.errors["write"]
        return self.stream.write(text)

    def flush(self):
        if "flush" in self.failures:
            raise self.errors["flush"]
        return self.stream.flush()

    def close(self):
        self.close_calls += 1
        self.stream.close()
        if "close" in self.failures:
            raise self.errors["close"]


with tempfile.TemporaryDirectory() as temporary:
    sandbox = EntrySandbox(temporary, "diagnostic-failures")
    for primary_kind in ("none", "timeout", "interrupt", "io"):
        for cleanup_fails in (False, True):
            for failures in (("write",), ("flush",), ("close",),
                             ("write", "close"), ("flush", "close")):
                label = f"#865 {primary_kind}/{cleanup_fails}/{failures}"
                primary = {"none": None,
                           "timeout": subprocess.TimeoutExpired(["mock-program"], 1),
                           "interrupt": KeyboardInterrupt("primary communicate interrupt"),
                           "io": OSError("primary communicate failure")}[primary_kind]
                process = mock.Mock(pid=424242, returncode=-signal.SIGTERM)
                process.communicate.side_effect = primary
                cleanup = {"status": "unresolved" if cleanup_fails else "group_absent", "pgid": 424242,
                           "group_absent_verified": not cleanup_fails}
                cleanup_error = PermissionError("primary cleanup failure")
                cleanup_error.cleanup_record = cleanup
                handle = DiagnosticHandle(sandbox.child("matrix.log"), failures)
                caught = None
                with mock.patch("entry_sandbox.subprocess.Popen", return_value=process), \
                        mock.patch.object(EntrySandbox, "_terminate_group",
                                          side_effect=cleanup_error if cleanup_fails else None,
                                          return_value=cleanup) as cleanup_call, \
                        mock.patch.object(Path, "open", return_value=handle), \
                        mock.patch("entry_sandbox.os.killpg", side_effect=AssertionError("No signals")):
                    try:
                        sandbox.run_logged(["mock-program"], "matrix.log")
                    except BaseException as error:
                        caught = error
                expected = primary if primary is not None else (
                    cleanup_error if cleanup_fails else handle.errors[failures[0]])
                check(f"{label}: exact original exception escapes", caught is expected, True)
                check(f"{label}: cleanup attempted once", cleanup_call.call_count, 1)
                check(f"{label}: real stream closed exactly once",
                      (handle.close_calls, handle.stream.closed), (1, True))
                check(f"{label}: active process removed", EntrySandbox.active_pgids(), [])
                if primary is not None or cleanup_fails:
                    check(f"{label}: cleanup evidence preserved", caught.cleanup_record, cleanup)
                    notes = getattr(caught, "__notes__", [])
                    for failure in failures:
                        check(f"{label}: {failure} failure is observable",
                              any(str(handle.errors[failure]) in note for note in notes), True)
                if primary is not None and cleanup_fails:
                    check(f"{label}: cleanup remains the original explicit cause",
                          caught.__cause__ is cleanup_error, True)
                elif len(failures) > 1:
                    check(f"{label}: close cannot replace first diagnostic failure",
                          str(handle.errors["close"]) in " ".join(getattr(caught, "__notes__", [])), True)

    for primary in (OSError("Popen failed"), KeyboardInterrupt("Popen interrupted")):
        handle = DiagnosticHandle(sandbox.child("launch-failure.log"), ("close",))
        with mock.patch("entry_sandbox.subprocess.Popen", side_effect=primary), \
                mock.patch.object(EntrySandbox, "_terminate_group") as cleanup_call, \
                mock.patch.object(Path, "open", return_value=handle):
            try:
                sandbox.run_logged(["mock-program"], "launch-failure.log")
            except BaseException as error:
                caught = error
            else:
                raise AssertionError("A failed launch must not return a result")
        check("#865 close cannot replace Popen exception identity", caught is primary, True)
        check("#865 failed launch never invents an owned process group", cleanup_call.call_count, 0)
        check("#865 failed launch closes its real log stream once",
              (handle.close_calls, handle.stream.closed), (1, True))
        check("#865 failed-launch close error is disclosed",
              str(handle.errors["close"]) in " ".join(caught.__notes__), True)


with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    first = EntrySandbox(root, "1AAA")
    second = EntrySandbox(root, "2BBB")
    code = (
        "from pathlib import Path; import os; "
        "Path('same-name.txt').write_text(os.getcwd())"
    )
    result_a = first.run_logged([sys.executable, "-c", code], "run.log")
    result_b = second.run_logged([sys.executable, "-c", code], "run.log")
    check("normal isolated launch succeeds", result_a.returncode, 0)
    check("start_new_session makes pid the recorded pgid",
          result_a.pid, result_a.pgid)
    check("sequential entries receive distinct process groups",
          result_a.pgid != result_b.pgid, True)
    check("same output name stays in each entry directory",
          ((first.child("same-name.txt").exists()
            and second.child("same-name.txt").exists())), True)
    check("the child really ran with the entry sandbox as cwd",
          first.child("same-name.txt").read_text(), str(first.path))
    check("inventory is relative to the entry, never the shared root",
          first.inventory(), ["run.log", "same-name.txt"])

    for unsafe in ("../sibling.txt", str(root / "absolute.txt")):
        try:
            first.child(unsafe)
        except ValueError:
            refused = True
        else:
            refused = False
        check(f"escaping path is refused: {unsafe}", refused, True)

    # The child installs a TERM handler while its parent remains the process
    # tracked by EntrySandbox.  A PGID-scoped timeout reaches both; killing
    # only the parent would never create child-term.json.
    timed = EntrySandbox(root, "3CCC")
    child_code = (
        "import json,signal,time; from pathlib import Path; "
        "signal.signal(signal.SIGTERM, lambda *_: "
        "(Path('child-term.json').write_text(json.dumps({'signal':'TERM'})), "
        "exit(0))); time.sleep(30)"
    )
    parent_code = (
        "import subprocess,sys,time; from pathlib import Path; "
        f"p=subprocess.Popen([sys.executable,'-c',{child_code!r}]); "
        "Path('child-pid.txt').write_text(str(p.pid)); time.sleep(30)"
    )
    timeout_result = timed.run_logged(
        [sys.executable, "-c", parent_code], "timeout.log",
        timeout=0.5, terminate_grace=1.0,
    )
    deadline = time.monotonic() + 2.0
    while not timed.child("child-term.json").exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    check("timeout is recorded", timeout_result.timed_out, True)
    check("timeout terminates the tracked group by signal",
          timeout_result.termination_signal is not None, True)
    check("PGID cleanup reaches a spawned descendant",
          json.loads(timed.child("child-term.json").read_text())["signal"],
          "TERM")

    stubborn = EntrySandbox(root, "3DDD")
    stubborn_child = (
        "import signal,time; from pathlib import Path; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(1); "
        "Path('survived.txt').write_text('alive'); time.sleep(30)"
    )
    stubborn_parent = (
        "import subprocess,sys,time; from pathlib import Path; "
        f"p=subprocess.Popen([sys.executable,'-c',{stubborn_child!r}]); "
        "Path('child-pid.txt').write_text(str(p.pid)); time.sleep(30)"
    )
    stubborn_result = stubborn.run_logged(
        [sys.executable, "-c", stubborn_parent], "stubborn.log",
        timeout=0.5, terminate_grace=0.2,
    )
    time.sleep(1.0)
    check("timeout kills a TERM-ignoring descendant after its leader exits",
          stubborn.child("survived.txt").exists(), False)
    check("stubborn timeout still records the leader signal",
          stubborn_result.termination_signal, 15)

    concurrent = EntrySandbox(root, "4DDD")
    result_box = []
    thread = threading.Thread(
        target=lambda: result_box.append(concurrent.run_logged(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            "concurrent.log", timeout=60,
        ))
    )
    thread.start()
    deadline = time.monotonic() + 2.0
    while not EntrySandbox.active_pgids() and time.monotonic() < deadline:
        time.sleep(0.02)
    active = EntrySandbox.active_pgids()
    EntrySandbox.terminate_all_active(terminate_grace=1.0)
    thread.join(timeout=2.0)
    check("concurrent driver can enumerate only its active PGIDs",
          len(active), 1)
    check("concurrent cancellation lets the worker finish", thread.is_alive(), False)
    check("concurrent cancellation records signal termination",
          result_box[0].termination_signal is not None, True)
    check("active registry is empty after worker cleanup",
          EntrySandbox.active_pgids(), [])

    concurrent_stubborn = EntrySandbox(root, "5EEE")
    concurrent_box = []
    thread = threading.Thread(
        target=lambda: concurrent_box.append(concurrent_stubborn.run_logged(
            [sys.executable, "-c", stubborn_parent],
            "concurrent-stubborn.log", timeout=60,
        ))
    )
    thread.start()
    deadline = time.monotonic() + 2.0
    while (not concurrent_stubborn.child("child-pid.txt").exists()
           and time.monotonic() < deadline):
        time.sleep(0.02)
    EntrySandbox.terminate_all_active(terminate_grace=0.2)
    thread.join(timeout=2.0)
    time.sleep(1.0)
    check("concurrent cancellation kills a TERM-ignoring descendant",
          concurrent_stubborn.child("survived.txt").exists(), False)
    check("stubborn concurrent worker finishes", thread.is_alive(), False)
    check("stubborn concurrent cancellation records leader signal",
          concurrent_box[0].termination_signal, 15)

    # Ordinary Python only. Each wrapper exits after its child has explicitly
    # installed SIGTERM-ignore; the child must not outlive the return boundary.
    for code in (0, 1, -signal.SIGKILL):
        exited = EntrySandbox(root, f"exit-{abs(code)}")
        child_code = (
            "import signal,time; from pathlib import Path; "
            "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
            "Path('child-ready.txt').write_text('ready'); time.sleep(1); "
            "Path('child-survived.txt').write_text('alive'); time.sleep(30)"
        )
        parent_code = (
            "import os,signal,subprocess,sys,time; from pathlib import Path; "
            f"p=subprocess.Popen([sys.executable,'-c',{child_code!r}]); "
            "Path('child-pid.txt').write_text(str(p.pid)); deadline=time.monotonic()+5\n"
            "while not Path('child-ready.txt').exists() and time.monotonic()<deadline: time.sleep(0.01)\n"
            "assert Path('child-ready.txt').exists(), 'child readiness timed out'\n"
            + (f"os.kill(os.getpid(), {-code})" if code < 0 else f"sys.exit({code})")
        )
        result = exited.run_logged([sys.executable, "-c", parent_code], "exit.log",
                                   timeout=8, terminate_grace=0.05)
        check("real wrapper exit status survives descendant cleanup", result.returncode, code)
        check("real exiting wrapper is not reported as timed out", result.timed_out, False)
        check("real surviving child requires scoped escalation", result.cleanup["signal_attempts"], ["SIGTERM", "SIGKILL"])
        check("recorded group is absent at the public return boundary", EntrySandbox._group_exists(result.pgid), False)
    time.sleep(1.1)
    check("no exited wrapper's child continues writing after return",
          any((root / f"exit-{abs(code)}" / "child-survived.txt").exists() for code in (0, 1, -signal.SIGKILL)), False)

print(f"\n{PASSED} checks passed")
