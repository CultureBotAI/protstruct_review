#!/usr/bin/env python3
"""Network-free tests for per-entry process isolation (#356)."""
from __future__ import annotations

import json
import signal
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

from entry_sandbox import EntrySandbox

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

print(f"\n{PASSED} checks passed")
