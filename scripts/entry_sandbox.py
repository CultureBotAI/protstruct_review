#!/usr/bin/env python3
"""Per-entry work directories and process-group-scoped command execution.

The negative-control agent leg once used name-based ``pkill`` patterns that
crossed entry boundaries.  This module makes the safe unit explicit: one entry
owns one directory and every launched process owns one POSIX session/process
group.  Cleanup after every leader outcome targets that recorded PGID, never a
process name. A reaped leader alone does not prove its descendants have stopped.
"""
from __future__ import annotations

import json
import math
import os
import re
import signal
import subprocess
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Sequence


_ENTRY_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_ACTIVE_LOCK = threading.Lock()
_ACTIVE_PROCESSES: dict[int, subprocess.Popen[str]] = {}
_CLEANUP_REAP_TIMEOUT = 1.0


class ProcessGroupCleanupError(RuntimeError):
    """An owned group could not be proven absent within bounded cleanup."""


@dataclass(frozen=True)
class ProcessGroupResult:
    """Serializable outcome of one isolated process-group launch."""

    arguments: list[str]
    returncode: int
    pid: int
    pgid: int
    timed_out: bool
    termination_signal: int | None
    start_new_session: bool = True
    cleanup: dict | None = None

    def to_record(self) -> dict:
        return asdict(self)


class EntrySandbox:
    """A single entry's collision-free directory and process namespace."""

    def __init__(self, root: str | os.PathLike[str], entry_id: str):
        if not _ENTRY_ID.fullmatch(entry_id):
            raise ValueError(f"unsafe entry id {entry_id!r}")
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = (self.root / entry_id).resolve()
        if self.path.parent != self.root:
            raise ValueError(f"entry path escapes sandbox root: {entry_id!r}")
        self.path.mkdir(parents=False, exist_ok=True)

    def child(self, relative: str | os.PathLike[str]) -> Path:
        """Resolve a path that must remain inside this entry's directory."""
        rel = Path(relative)
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError(f"sandbox path must be relative and contained: {relative}")
        candidate = (self.path / rel).resolve()
        if candidate != self.path and self.path not in candidate.parents:
            raise ValueError(f"sandbox path escapes entry directory: {relative}")
        return candidate

    def write_json_atomic(self, relative: str, payload: dict) -> Path:
        destination = self.child(relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, indent=2) + "\n")
        temporary.replace(destination)
        return destination

    def run_logged(
        self,
        arguments: Sequence[str | os.PathLike[str]],
        log_name: str,
        *,
        timeout: float | None = None,
        env: Mapping[str, str] | None = None,
        input_text: str | None = None,
        terminate_grace: float = 5.0,
    ) -> ProcessGroupResult:
        """Run in a fresh session, checking/cleaning its PGID on every outcome.

        ``start_new_session=True`` makes the child's PID its PGID before exec.
        Recording that value avoids the race in querying a very short-lived
        child with ``os.getpgid()`` after it has already exited.
        """
        if not math.isfinite(terminate_grace) or terminate_grace < 0:
            raise ValueError("terminate_grace must be finite and nonnegative")
        log_path = self.child(log_name)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        argv = [os.fspath(argument) for argument in arguments]
        log_handle = log_path.open("w")
        primary_error = None
        propagating_error = None
        cleanup = None
        try:
            process = subprocess.Popen(
                argv,
                cwd=self.path,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE if input_text is not None else None,
                text=True,
                env=dict(env) if env is not None else None,
                start_new_session=True,
            )
            pgid = process.pid
            timed_out = False
            cleanup_failure = None
            diagnostic_failure = False
            with _ACTIVE_LOCK:
                _ACTIVE_PROCESSES[pgid] = process
            try:
                try:
                    process.communicate(input=input_text, timeout=timeout)
                except subprocess.TimeoutExpired as error:
                    timed_out = True
                    primary_error = error
                except BaseException as error:
                    primary_error = error
                try:
                    cleanup = self._terminate_group(process, pgid, terminate_grace)
                except BaseException as error:
                    cleanup_failure = error
                    cleanup = getattr(error, "cleanup_record", {
                        "status": "unresolved", "pgid": pgid,
                        "group_absent_verified": False,
                        "error": f"{type(error).__name__}: {error}",
                    })
                    if primary_error is not None:
                        primary_error.add_note(f"Owned PGID cleanup unresolved: {cleanup}")
                        primary_error.cleanup_record = cleanup
                        raise primary_error from error
                    raise
                finally:
                    record = {"cleanup": cleanup, "leader_returncode": process.returncode,
                              "timed_out": timed_out}
                    if primary_error is not None:
                        record["primary_exception"] = f"{type(primary_error).__name__}: {primary_error}"
                    try:
                        log_handle.write("\n[entry_sandbox cleanup] " + json.dumps(record, sort_keys=True) + "\n")
                        log_handle.flush()
                    except BaseException as log_error:
                        diagnostic_failure = True
                        original_error = primary_error if primary_error is not None else cleanup_failure
                        if original_error is None:
                            raise
                        original_error.add_note(f"Cleanup diagnostic write failed: {type(log_error).__name__}: {log_error}")
                if primary_error is not None and (not timed_out or diagnostic_failure):
                    primary_error.cleanup_record = cleanup
                    raise primary_error
            finally:
                with _ACTIVE_LOCK:
                    _ACTIVE_PROCESSES.pop(pgid, None)
        except BaseException as error:
            propagating_error = error
            raise
        finally:
            # A context manager's implicit close could replace the exception
            # above. Preserve that exact object and its cleanup cause instead.
            try:
                log_handle.close()
            except BaseException as log_error:
                original_error = propagating_error if propagating_error is not None else primary_error
                if original_error is None:
                    raise
                original_error.add_note(f"Cleanup diagnostic close failed: {type(log_error).__name__}: {log_error}")
                if cleanup is not None:
                    original_error.cleanup_record = cleanup
                if propagating_error is None:
                    # An otherwise handled timeout must expose lost diagnostics,
                    # not discard the only exception carrying their failure.
                    raise original_error
        return ProcessGroupResult(
            arguments=argv,
            returncode=process.returncode,
            pid=process.pid,
            pgid=pgid,
            timed_out=timed_out,
            termination_signal=(-process.returncode if process.returncode < 0 else None),
            cleanup=cleanup,
        )

    @staticmethod
    def _terminate_group(
        process: subprocess.Popen[str], pgid: int, terminate_grace: float
    ) -> dict:
        """Terminate one known process group, escalating TERM to KILL.

        The group leader may obey TERM while one of its descendants ignores
        it.  Waiting only for the leader therefore is not proof that the
        owned process group is gone (#416).
        """
        if not math.isfinite(terminate_grace) or terminate_grace < 0:
            raise ValueError("terminate_grace must be finite and nonnegative")
        record = {"status": "unresolved", "pgid": pgid, "signal_attempts": [],
                  "group_absent_verified": False}
        try:
            if EntrySandbox._group_exists(pgid):
                record["signal_attempts"].append("SIGTERM")
                try:
                    os.killpg(pgid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                deadline = time.monotonic() + terminate_grace
                while EntrySandbox._group_exists(pgid) and time.monotonic() < deadline:
                    process.poll()  # Reap the leader promptly; descendants may remain.
                    time.sleep(min(0.02, max(0.0, deadline - time.monotonic())))
                process.poll()  # Reap again before deciding whether escalation is needed.
                if EntrySandbox._group_exists(pgid):
                    record["signal_attempts"].append("SIGKILL")
                    try:
                        os.killpg(pgid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    except PermissionError:
                        # Preserve #850: suppress EPERM only when both the
                        # leader has exited and a fresh group check is absent.
                        returncode = process.poll()
                        if returncode is None or EntrySandbox._group_exists(pgid):
                            raise
            deadline = time.monotonic() + _CLEANUP_REAP_TIMEOUT
            try:
                process.communicate(timeout=_CLEANUP_REAP_TIMEOUT)
            except subprocess.TimeoutExpired as error:
                raise ProcessGroupCleanupError("Leader not reaped within cleanup bound") from error
            while EntrySandbox._group_exists(pgid):
                if time.monotonic() >= deadline:
                    raise ProcessGroupCleanupError(
                        "Owned group remains present or unqueryable after cleanup; "
                        "running descendants and unreaped zombies are not distinguished"
                    )
                time.sleep(min(0.02, max(0.0, deadline - time.monotonic())))
            record.update(status="group_absent", group_absent_verified=True)
            return record
        except BaseException as error:
            record["error"] = f"{type(error).__name__}: {error}"
            error.cleanup_record = record
            raise

    @staticmethod
    def _group_exists(pgid: int) -> bool:
        """Return whether any process still belongs to the recorded PGID."""
        try:
            os.killpg(pgid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    @staticmethod
    def active_pgids() -> list[int]:
        with _ACTIVE_LOCK:
            return sorted(_ACTIVE_PROCESSES)

    @staticmethod
    def terminate_all_active(terminate_grace: float = 5.0) -> None:
        """Signal every process group owned by this Python process.

        Used by a concurrent driver when its main thread is interrupted.  The
        worker thread remains the sole caller of ``communicate()``; this method
        only signals the recorded groups, avoiding unsafe concurrent reads of a
        ``Popen`` object.
        """
        with _ACTIVE_LOCK:
            active = list(_ACTIVE_PROCESSES.items())
        for pgid, _process in active:
            if EntrySandbox._group_exists(pgid):
                try:
                    os.killpg(pgid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        deadline = time.monotonic() + terminate_grace
        while time.monotonic() < deadline:
            if all(not EntrySandbox._group_exists(pgid) for pgid, _ in active):
                return
            time.sleep(0.02)
        for pgid, _process in active:
            if EntrySandbox._group_exists(pgid):
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def inventory(self) -> list[str]:
        """Return every work artefact as a relative, collision-auditable path."""
        return sorted(
            str(path.relative_to(self.path))
            for path in self.path.rglob("*")
            if path.is_file()
        )
