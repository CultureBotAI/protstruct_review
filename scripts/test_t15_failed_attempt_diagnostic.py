#!/usr/bin/env python3
"""Hermetic launcher controls: no scientific tool, network, Git write or real child."""
from __future__ import annotations

import base64
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_t15_failed_attempt_diagnostic as launch  # noqa: E402

COMMIT = "1" * 40
REAL_PYTHON_ENVIRONMENT = launch.python_environment


@contextlib.contextmanager
def package_environment(repo):
    """Synthetic metadata only: no package imports or executable probes."""
    versions = {name: "1.0" for name in launch.PACKAGES}
    versions.update(biotite="1.7.1", gemmi="0.7.5")
    distributions = {}
    lock = []
    for name, version in versions.items():
        directory = repo / ".venv/lib/mock-site-packages" / (name + ".dist-info")
        launch.write_new(directory / "METADATA",
                         f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n\n".encode())
        distributions[name] = launch.importlib.metadata.PathDistribution(directory)
        lock.append(f'[[package]]\nname = "{name}"\nversion = "{version}"\n')
    (repo / "uv.lock").write_text("\n".join(lock))
    with mock.patch.object(launch.sys, "version_info", (3, 12, 0)), \
            mock.patch.object(launch.sys, "prefix", str(repo / ".venv")), \
            mock.patch.object(launch.importlib.metadata, "distribution",
                              side_effect=distributions.__getitem__):
        yield distributions


@contextlib.contextmanager
def deny_blocking_path_open():
    """A removed guard fails an assertion instead of hanging the test gate."""
    original = Path.open

    def checked(path, *args, **kwargs):
        if path.exists() and stat.S_ISFIFO(path.lstat().st_mode):
            raise AssertionError(f"unsafe potentially blocking FIFO read: {path}")
        return original(path, *args, **kwargs)

    with mock.patch.object(Path, "open", checked):
        yield


def bytes_block(raw):
    return {**launch.identity_bytes(raw), "encoding": "base64",
            "bytes_base64": base64.b64encode(raw).decode()}


def coordinate_source():
    # Synthetic coordinates cover the exact registered key domain; no assigner
    # is run on this CA-only fixture or asked to infer real secondary structure.
    lines = []
    for chain in "ABC":
        for resnum in range(3, 111):
            line = list(" " * 80)
            line[:6], line[6:11], line[12:16] = "ATOM  ", f"{len(lines) + 1:5d}", " CA "
            line[17:20], line[21], line[22:26] = "ALA", chain, f"{resnum:4d}"
            for start in (30, 38, 46):
                line[start:start + 8] = "   1.000"
            line[54:60], line[60:66], line[76:78] = "  1.00", " 20.00", " C"
            lines.append("".join(line))
    return ("\n".join(lines) + "\nEND\n").encode()


def dssp_bytes(assignments):
    lines = [f"{len(assignments):5d}{3:3d}{0:3d}{0:3d}{0:3d} TOTAL NUMBER OF RESIDUES, "
             "NUMBER OF CHAINS, NUMBER OF SS-BRIDGES(TOTAL,INTRACHAIN,INTERCHAIN)                .",
             "  #  RESIDUE AA STRUCTURE BP1 BP2  ACC     N-H-->O    O-->H-N    N-H-->O    O-->H-N"
             "    TCO  KAPPA ALPHA  PHI   PSI    X-CA   Y-CA   Z-CA"]
    for serial, row in enumerate(assignments, 1):
        line = list(" " * 136)
        line[:5], line[5:10] = f"{serial:5d}", f"{int(row['resnum']):5d}"
        line[10], line[11], line[13] = row["icode"] or " ", row["chain"], "A"
        line[16] = " " if row["state"] == "C" else row["state"]
        for start in (25, 29, 34):
            line[start:start + 4] = "   0"
        for start in (39, 50, 61, 72):
            line[start:start + 11] = "     0, 0.0"
        for start in (85, 91, 97, 103, 109, 116, 123, 130):
            line[start:start + 6] = " 0.000" if start == 85 else "   0.0"
        for start in (116, 123, 130):
            line[start:start + 6] = "   1.0"
        lines.append("".join(line))
    return ("\n".join(lines) + "\n").encode()


def reset_streams(payload, a, b):
    payload["dssp"]["assignments"] = a
    payload["biotite_psea"]["assignments"] = b
    payload["dssp"]["raw_output"] = bytes_block(dssp_bytes(a))
    ka = {(r["chain"], r["resnum"], r["icode"]) for r in a}
    kb = {(r["chain"], r["resnum"], r["icode"]) for r in b}
    shared, only_a, only_b = ka & kb, ka - kb, kb - ka
    payload["failure"] = {
        "stage": "residue_key_admission",
        "reason_code": "unequal_residue_keys" if shared else "no_shared_residue_keys",
        "counts": {"n_dssp": len(a), "n_biotite": len(b), "n_shared": len(shared),
                   "n_dssp_only": len(only_a), "n_biotite_only": len(only_b)},
        **{name + "_keys": [{"chain": c, "resnum": r, "icode": i} for c, r, i in sorted(keys)]
           for name, keys in (("shared", shared), ("dssp_only", only_a), ("biotite_only", only_b))},
    }


def failed_bundle(request, source, missing=("C", "3", "")):
    _, keys = launch.coordinate_inventory(source)
    b = [{"chain": c, "resnum": r, "icode": i, "state": "H"} for c, r, i in sorted(keys)]
    a = [dict(row) for row in b if (row["chain"], row["resnum"], row["icode"]) != missing]
    raw = dssp_bytes(a)
    normalized_path = str(Path(request["entry_absolute"]) / "tmp/normalized.pdb")
    payload = {
        "evidence_format": "protstruct-review-t15-failed-attempt-v1",
        "attempt_status": "failed_denominator_admission", "measurements_emitted": False,
        "catalog_task_ref": "T15", "eval_id": launch.EVAL_ID, "subject_ref": launch.SUBJECT,
        "failure": {
            "stage": "residue_key_admission", "reason_code": "unequal_residue_keys",
            "counts": {"n_dssp": 1, "n_biotite": 2, "n_shared": 1,
                       "n_dssp_only": 0, "n_biotite_only": 1},
            "shared_keys": [{"chain": "A", "resnum": "1", "icode": ""}],
            "dssp_only_keys": [],
            "biotite_only_keys": [{"chain": "C", "resnum": "3", "icode": ""}],
        },
        "source": bytes_block(source),
        "normalization": {
            **bytes_block(source),
            "tool_version": "gemmi 0.7.5",
            "execution": {"argv": [request["executables"]["gemmi"]["path"], "convert",
                                  str(Path(request["repo"]) / launch.INPUT), normalized_path],
                          "returncode": 0, "stdout": "normalize text\n", "stderr": ""},
        },
        "dssp": {
            "raw_output": bytes_block(raw), "assignments": a,
            "tool_version": "mkdssp version 4.6.1",
            "execution": {"argv": [request["executables"]["dssp"]["path"],
                                  "--output-format", "dssp", normalized_path,
                                  str(Path(request["entry_absolute"]) / "tmp/raw.dssp")],
                          "returncode": 0, "stdout": "", "stderr": ""},
        },
        "biotite_psea": {"assignments": b, "tool_version": "1.7.1",
                         "execution": {"mode": "in_process", "status": "returned_assignments"}},
    }
    reset_streams(payload, a, b)
    return payload


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name).resolve()
        self.source = coordinate_source()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(launch, "INPUT_SHA", launch.sha(self.source)))
        self.stack.enter_context(mock.patch.object(launch, "INPUT_SIZE", len(self.source)))
        self.stack.enter_context(mock.patch.object(
            launch, "SUBJECT", f"retained:1BNI:sha256:{launch.sha(self.source)}"
        ))
        self.committed = {}
        for name in launch.SOURCES:
            raw = (Path(launch.__file__).read_bytes() if name == launch.SELF
                   else f"registered {name}\n".encode())
            launch.write_new(self.repo / name, raw)
            self.committed[name] = raw
        launch.write_new(self.repo / launch.INPUT, self.source)
        self.committed[launch.INPUT] = self.source

        def git_bytes(_repo, *arguments):
            if arguments == ("rev-parse", "HEAD"):
                return (COMMIT + "\n").encode()
            if arguments[0] == "show":
                commit, name = arguments[1].split(":", 1)
                assert commit == COMMIT
                return self.committed[name]
            raise AssertionError(f"unexpected Git operation {arguments}")

        self.stack.enter_context(mock.patch.object(launch, "git_bytes", side_effect=git_bytes))
        self.python = {
            "version": "mock Python 3.12", "executable": sys.executable,
            "prefix": str(self.repo / ".venv"), "packages": {"biotite": "1.7.1"},
            "executable_identity": launch.identity(Path(sys.executable).resolve()),
            "package_metadata": {},
        }
        self.stack.enter_context(mock.patch.object(
            launch, "python_environment", return_value=self.python
        ))
        self.executables = {}
        for name in ("gemmi", "dssp"):
            binary = self.repo / f"mock-{name}"
            launch.write_new(binary, f"not an executable: {name}\n".encode())
            self.executables[name] = {"path": str(binary), **launch.identity(binary)}
        self.stack.enter_context(mock.patch.object(
            launch, "executable_identities", return_value=self.executables
        ))
        self.calls, self.behavior = [], "expected"
        owner = self

        class FakeSandbox:
            def __init__(self, root, entry_id):
                self.path = Path(root) / entry_id
                self.path.mkdir(parents=True)

            @staticmethod
            def active_pgids():
                return []

            def run_logged(self, argv, log_name, *, timeout, env):
                owner.calls.append((argv, timeout, env))
                assert timeout == 900
                assert env["PROTSTRUCT_GEMMI"] == owner.executables["gemmi"]["path"]
                assert env["PROTSTRUCT_DSSP"] == owner.executables["dssp"]["path"]
                request_path = Path(argv[argv.index("--worker") + 1])
                request = json.loads(request_path.read_bytes())
                assert argv[-1] == launch.sha(request_path.read_bytes())
                assert request["wrapper_argv"][2] == str(owner.repo / launch.WRAPPER)
                assert request["wrapper_argv"][3] == str(owner.repo / launch.INPUT)
                launch.write_new(self.path / log_name, b"mock owned launch\n")
                launch.save_new(self.path / "worker-context.json", {
                    "pid": 12345, "pgid": 12345, "wrapper_argv": request["wrapper_argv"],
                    "request_sha256": launch.sha(request_path.read_bytes()),
                })
                payload = failed_bundle(request, owner.source,
                                        missing=("C", "4", "") if owner.behavior == "different_key"
                                        else ("C", "3", ""))
                if owner.behavior == "bad_bundle":
                    payload["dssp"]["assignments"][0]["state"] = "C"
                if owner.behavior == "version_drift":
                    payload["dssp"]["tool_version"] = "mkdssp version 9.0.0"
                launch.save_new(self.path / "failed-attempt.json", payload)
                stdout = b"- unexpected measurement\n" if owner.behavior in {
                    "stdout", "unexpected_success"
                } else b""
                launch.write_new(self.path / "wrapper.stdout", stdout)
                launch.write_new(self.path / "wrapper.stderr",
                                 b"failed-attempt evidence retained: failed-attempt.json\n")
                if owner.behavior == "source_drift":
                    (owner.repo / launch.WRAPPER).write_bytes(b"changed after launch\n")
                if owner.behavior.startswith("snapshot_"):
                    _, operation, kind = owner.behavior.split("_", 2)
                    relative = (f"source_snapshot/{launch.WRAPPER}" if kind == "source"
                                else "input_snapshot/1bni.pdb")
                    retained = owner.repo / request["root"] / relative
                    if operation == "mutate":
                        retained.write_bytes(b"changed retained copy\n")
                    elif operation == "remove":
                        retained.unlink()
                    else:
                        raise AssertionError(operation)
                record = {
                    "arguments": argv, "returncode": 0 if owner.behavior == "unexpected_success" else 1,
                    "pid": 12345, "pgid": 12345,
                    "timed_out": owner.behavior == "timeout", "termination_signal": None,
                    "start_new_session": True,
                    "cleanup": {"status": "group_absent", "pgid": 12345,
                                "group_absent_verified": True},
                }
                return SimpleNamespace(**record, to_record=lambda: record)

        self.stack.enter_context(mock.patch.object(
            launch, "load_module", return_value=SimpleNamespace(EntrySandbox=FakeSandbox)
        ))
        self.args = ["--repo", str(self.repo), "--registration-commit", COMMIT,
                     "--run-id", "mock01"]
        self.root = (self.repo / "data/coscientists/openscientist" /
                     "retained_evidence_2026-09-27_t15-diagnostic-mock01")
        self.entry = self.root / "entries/T15_1BNI"
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))

    def test_read_only_default(self):
        self.assertEqual(launch.main(self.args), 0)
        self.assertFalse(self.root.exists())
        self.assertEqual(self.calls, [])

    def test_unverified_owned_group_cleanup_cannot_admit_diagnostic(self):
        sandbox = launch.load_module(self.repo, "entry_sandbox").EntrySandbox
        original_run = sandbox.run_logged
        for kind in ("missing", "unresolved", "wrong_pgid", "truthy"):
            with self.subTest(kind=kind):
                def corrupt(owner, *arguments, **kwargs):
                    result = original_run(owner, *arguments, **kwargs)
                    record = result.to_record()
                    if kind == "missing":
                        record.pop("cleanup")
                    elif kind == "unresolved":
                        record["cleanup"].update(status="unresolved", group_absent_verified=False)
                    elif kind == "wrong_pgid":
                        record["cleanup"]["pgid"] += 1
                    else:
                        record["cleanup"]["group_absent_verified"] = 1
                    return SimpleNamespace(**record, to_record=lambda: record)

                args = list(self.args); args[-1] = "cleanup-" + kind
                root = self.root.with_name(self.root.name.replace("mock01", args[-1]))
                with mock.patch.object(sandbox, "run_logged", corrupt):
                    self.assertEqual(launch.main(args + ["--execute"]), 1)
                result = json.loads((root / "entries/T15_1BNI/launch-result.json").read_bytes())
                self.assertFalse(result["diagnostic_retention_valid"])
                self.assertIn("group absence was not verified", result["audit_error"])

    def test_launch_exception_retains_cleanup_and_notes(self):
        sandbox = launch.load_module(self.repo, "entry_sandbox").EntrySandbox
        cleanup = {"status": "unresolved", "pgid": 12345, "group_absent_verified": False}
        exception = launch.subprocess.TimeoutExpired(["mock-wrapper"], 900)
        exception.cleanup_record = cleanup
        exception.add_note("Cleanup diagnostic write failed: OSError: synthetic full device")
        with mock.patch.object(sandbox, "run_logged", side_effect=exception):
            self.assertEqual(launch.main(self.args + ["--execute"]), 1)
        result = json.loads((self.entry / "launch-result.json").read_bytes())
        self.assertFalse(result["diagnostic_retention_valid"])
        self.assertIsNone(result["process"])
        self.assertEqual(result["launcher_exception"]["cleanup_record"], cleanup)
        self.assertEqual(result["launcher_exception"]["notes"], exception.__notes__)
        self.assertEqual(result["launcher_exception"]["type"], "TimeoutExpired")
        self.assertTrue((self.root / "final-file-manifest.json").is_file())

    def test_repository_alias_uses_canonical_fixture_identity(self):
        alias = self.repo / "repository-alias"
        alias.symlink_to(self.repo, target_is_directory=True)
        args = list(self.args)
        args[args.index("--repo") + 1] = str(alias)
        self.assertEqual(launch.main(args + ["--execute"]), 0)
        request = json.loads((self.entry / "launch-request.json").read_bytes())
        self.assertEqual(request["repo"], str(self.repo))
        self.assertEqual(request["wrapper_argv"][2], str(self.repo / launch.WRAPPER))
        self.assertEqual(request["wrapper_argv"][3], str(self.repo / launch.INPUT))

    def test_retained_snapshot_mutation_and_removal_stop_with_manifest(self):
        for operation in ("mutate", "remove"):
            for kind in ("source", "input"):
                with self.subTest(operation=operation, kind=kind):
                    self.behavior = f"snapshot_{operation}_{kind}"
                    args = list(self.args)
                    args[-1] = self.behavior.replace("_", "-")
                    root = self.root.with_name(self.root.name.replace("mock01", args[-1]))
                    self.assertEqual(launch.main(args + ["--execute"]), 1)
                    result = json.loads((root / "entries/T15_1BNI/launch-result.json").read_bytes())
                    self.assertFalse(result["diagnostic_retention_valid"])
                    self.assertIsNone(result["audit"])
                    relative = (f"source_snapshot/{launch.WRAPPER}" if kind == "source"
                                else "input_snapshot/1bni.pdb")
                    self.assertTrue(any(relative in problem for problem in result["identity_drift"]))
                    manifest = json.loads((root / "final-file-manifest.json").read_bytes())
                    actual = launch.inventory(root)
                    actual.pop("final-file-manifest.json")
                    self.assertEqual(manifest["files"], actual)
                    if operation == "mutate":
                        self.assertEqual((root / relative).read_bytes(), b"changed retained copy\n")
                        self.assertEqual(manifest["files"][relative], launch.identity(root / relative))
                    else:
                        self.assertFalse((root / relative).exists())
                        self.assertNotIn(relative, manifest["files"])
                        self.assertIsNone(result["snapshot_identities_after"][relative])
                    self.assertEqual((self.repo / launch.WRAPPER).read_bytes(),
                                     self.committed[launch.WRAPPER])
                    self.assertEqual((self.repo / launch.INPUT).read_bytes(), self.source)
        self.assertEqual(len(self.calls), 4)

    def test_inventory_mutation_after_initial_checks_is_not_accepted(self):
        original_inventory = launch.inventory

        def mutate_before_inventory(root):
            (root / "input_snapshot/1bni.pdb").write_bytes(b"late changed copy\n")
            return original_inventory(root)

        with mock.patch.object(launch, "inventory", side_effect=mutate_before_inventory):
            self.assertEqual(launch.main(self.args + ["--execute"]), 1)
        result = json.loads((self.entry / "launch-result.json").read_bytes())
        self.assertFalse(result["diagnostic_retention_valid"])
        self.assertTrue(any("final inventory snapshot" in problem
                            for problem in result["identity_drift"]))
        manifest = json.loads((self.root / "final-file-manifest.json").read_bytes())
        self.assertEqual(manifest["files"]["input_snapshot/1bni.pdb"],
                         launch.identity(self.root / "input_snapshot/1bni.pdb"))

    def test_final_inventory_binds_exact_bytes_consumed_for_admission(self):
        original_inventory = launch.inventory
        names = ("failed-attempt.json", "wrapper.stdout", "wrapper.stderr",
                 "launch-request.json", "worker-context.json", "owned-launch.json")
        for operation in ("mutate", "remove"):
            for number, name in enumerate(names):
                with self.subTest(operation=operation, name=name):
                    args = list(self.args)
                    args[-1] = f"admission-{operation}-{number}"
                    root = self.root.with_name(self.root.name.replace("mock01", args[-1]))
                    relative = f"entries/T15_1BNI/{name}"
                    audited_pin = None

                    def change_after_audit(inventory_root):
                        nonlocal audited_pin
                        path = inventory_root / relative
                        audited_pin = launch.identity(path)
                        if operation == "remove":
                            path.unlink()
                        elif name == "failed-attempt.json":
                            bundle = json.loads(path.read_bytes())
                            bundle["failure"]["counts"]["n_dssp"] = 999
                            path.write_text(json.dumps(bundle))
                        else:
                            path.write_bytes(path.read_bytes() + b"\nchanged after admission\n")
                        return original_inventory(inventory_root)

                    with mock.patch.object(launch, "inventory", side_effect=change_after_audit):
                        self.assertEqual(launch.main(args + ["--execute"]), 1)
                    result = json.loads((root / "entries/T15_1BNI/launch-result.json").read_bytes())
                    self.assertFalse(result["diagnostic_retention_valid"])
                    self.assertIsNone(result["audit"])
                    self.assertEqual(result["admission_file_identities"][relative], audited_pin)
                    self.assertTrue(any("admission evidence" in problem and name in problem
                                        for problem in result["identity_drift"]))
                    manifest = json.loads((root / "final-file-manifest.json").read_bytes())
                    actual = original_inventory(root)
                    actual.pop("final-file-manifest.json")
                    self.assertEqual(manifest["files"], actual)
                    if operation == "remove":
                        self.assertNotIn(relative, manifest["files"])
                    else:
                        self.assertNotEqual(manifest["files"][relative], audited_pin)
        self.assertEqual(len(self.calls), 12)

    def test_expected_diagnostic_and_complete_manifest(self):
        self.assertEqual(launch.main(self.args + ["--execute"]), 0)
        self.assertEqual(len(self.calls), 1)
        result = json.loads((self.entry / "launch-result.json").read_bytes())
        self.assertTrue(result["diagnostic_retention_valid"])
        self.assertTrue(result["audit"]["prediction_matches"])
        self.assertEqual(result["process"]["returncode"], 1)
        self.assertEqual((self.entry / "wrapper.stdout").read_bytes(), b"")
        manifest_path = self.root / "final-file-manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        actual = launch.inventory(self.root)
        actual.pop("final-file-manifest.json")
        self.assertEqual(manifest["files"], actual)
        self.assertEqual(manifest["file_count"], len(actual))
        for name, expected in self.committed.items():
            snapshot = (self.root / "input_snapshot/1bni.pdb" if name == launch.INPUT
                        else self.root / "source_snapshot" / name)
            self.assertEqual(snapshot.read_bytes(), expected)

    def test_coordinated_request_context_change_rejects_original_launch_mismatch(self):
        sandbox = launch.load_module.return_value.EntrySandbox
        original = sandbox.run_logged

        def mutate(worker, argv, name, **kwargs):
            result = original(worker, argv, name, **kwargs)
            path = worker.path / "launch-request.json"
            request = json.loads(path.read_bytes())
            request["registration_commit"] = "2" * 40
            path.write_bytes(launch.serialized(request))
            context_path = worker.path / "worker-context.json"
            context = json.loads(context_path.read_bytes())
            context["request_sha256"] = launch.sha(path.read_bytes())
            context_path.write_bytes(launch.serialized(context))
            self.assertNotEqual(argv[-1], context["request_sha256"])
            return result

        with mock.patch.object(sandbox, "run_logged", new=mutate):
            self.assertEqual(launch.main(self.args + ["--execute"]), 1)
        outcome = json.loads((self.entry / "launch-result.json").read_bytes())
        self.assertFalse(outcome["diagnostic_retention_valid"])
        self.assertIn("original parent pin", outcome["audit_error"])
        self.assertEqual(outcome["launched_request_sha256"], self.calls[0][0][-1])

    def test_inventory_errors_keep_terminal_failure_without_following_aliases(self):
        original_inventory, original_reader = launch.inventory, launch.read_regular
        for kind in ("symlink", "unreadable", "fifo"):
            with self.subTest(kind=kind):
                args = list(self.args)
                args[-1] = f"inventory-{kind}"
                root = self.root.with_name(self.root.name.replace("mock01", args[-1]))
                target = root / "input_snapshot/1bni.pdb"

                def checked_read(path):
                    if Path(path) == target:
                        raise PermissionError("synthetic inventory read failure")
                    return original_reader(path)

                def corrupt(inventory_root):
                    if kind in ("symlink", "fifo"):
                        target.unlink()
                        if kind == "symlink":
                            target.symlink_to(self.repo / launch.INPUT)
                        else:
                            launch.os.mkfifo(target)
                        return original_inventory(inventory_root)
                    with mock.patch.object(launch, "read_regular", side_effect=checked_read):
                        return original_inventory(inventory_root)

                with mock.patch.object(launch, "inventory", side_effect=corrupt):
                    self.assertEqual(launch.main(args + ["--execute"]), 1)
                outcome = json.loads((root / "entries/T15_1BNI/launch-result.json").read_bytes())
                manifest = json.loads((root / "final-file-manifest.json").read_bytes())
                self.assertFalse(outcome["diagnostic_retention_valid"])
                self.assertFalse(outcome["inventory_complete"])
                self.assertFalse(manifest["inventory_complete"])
                self.assertIn("input_snapshot/1bni.pdb", outcome["inventory_errors"])
                self.assertNotIn("sha256", manifest["files"]["input_snapshot/1bni.pdb"])
                self.assertEqual((self.repo / launch.INPUT).read_bytes(), self.source)

    def test_every_post_worker_read_refuses_special_files_and_retains_terminal_result(self):
        sandbox = launch.load_module(self.repo, "entry_sandbox").EntrySandbox
        original_run = sandbox.run_logged
        targets = (
            "source", "input", "lock", "executable", "source_snapshot", "input_snapshot",
            "worker-context.json", "launch-request.json", "owned-launch.json",
            "wrapper.stdout", "wrapper.stderr", "failed-attempt.json",
        )
        for kind in ("symlink", "fifo"):
            for label in targets:
                with self.subTest(kind=kind, label=label):
                    args = list(self.args)
                    args[-1] = f"post-{kind}-{label.replace('.', '-')}"
                    root = self.root.with_name(self.root.name.replace("mock01", args[-1]))
                    entry = root / "entries/T15_1BNI"
                    target = {
                        "source": self.repo / launch.WRAPPER,
                        "input": self.repo / launch.INPUT,
                        "lock": self.repo / "uv.lock",
                        "executable": Path(self.executables["gemmi"]["path"]),
                        "source_snapshot": root / "source_snapshot" / launch.WRAPPER,
                        "input_snapshot": root / "input_snapshot/1bni.pdb",
                    }.get(label, entry / label)
                    original_bytes = None
                    alias = self.repo / f"alias-{args[-1]}"

                    def replace_after_worker(owner, *arguments, **kwargs):
                        nonlocal original_bytes
                        result = original_run(owner, *arguments, **kwargs)
                        original_bytes = target.read_bytes()
                        target.unlink()
                        if kind == "symlink":
                            alias.write_bytes(original_bytes)
                            target.symlink_to(alias)
                        else:
                            os.mkfifo(target)
                        return result

                    try:
                        with mock.patch.object(sandbox, "run_logged", replace_after_worker), \
                                deny_blocking_path_open():
                            self.assertEqual(launch.main(args + ["--execute"]), 1)
                        result = json.loads((entry / "launch-result.json").read_bytes())
                        manifest = json.loads((root / "final-file-manifest.json").read_bytes())
                        self.assertFalse(result["diagnostic_retention_valid"])
                        self.assertIsNone(result["audit"])
                        self.assertIn("entries/T15_1BNI/launch-result.json", manifest["files"])
                        if target.is_relative_to(root):
                            self.assertFalse(manifest["inventory_complete"])
                            self.assertIn(target.relative_to(root).as_posix(), manifest["inventory_errors"])
                    finally:
                        if original_bytes is not None:
                            target.unlink()
                            target.write_bytes(original_bytes)

    def test_post_worker_metadata_change_is_terminal_without_rediscovery(self):
        sandbox = launch.load_module(self.repo, "entry_sandbox").EntrySandbox
        original_run = sandbox.run_logged
        with package_environment(self.repo) as distributions:
            self.committed["uv.lock"] = (self.repo / "uv.lock").read_bytes()
            metadata = Path(distributions["biotite"]._path) / "METADATA"
            original_raw = metadata.read_bytes()
            for kind in ("unchanged", "symlink", "fifo", "changed"):
                with self.subTest(kind=kind):
                    finished = False

                    def discover(name):
                        if finished:
                            raise AssertionError("post-run package rediscovery")
                        return distributions[name]

                    def replace_after_worker(owner, *arguments, **kwargs):
                        nonlocal finished
                        result = original_run(owner, *arguments, **kwargs)
                        finished = True
                        if kind == "unchanged":
                            return result
                        metadata.unlink()
                        if kind == "fifo":
                            os.mkfifo(metadata)
                        elif kind == "symlink":
                            alias = metadata.with_name("alias")
                            alias.write_bytes(original_raw)
                            metadata.symlink_to(alias)
                        else:
                            metadata.write_bytes(b"changed metadata\n")
                        return result

                    args = list(self.args); args[-1] = f"metadata-{kind}"
                    root = self.root.with_name(self.root.name.replace("mock01", args[-1]))
                    try:
                        with mock.patch.object(sandbox, "run_logged", replace_after_worker), \
                                mock.patch.object(launch, "python_environment",
                                                  side_effect=REAL_PYTHON_ENVIRONMENT), \
                                mock.patch.object(launch.importlib.metadata, "distribution",
                                                  side_effect=discover), \
                                deny_blocking_path_open():
                            self.assertEqual(launch.main(args + ["--execute"]),
                                             0 if kind == "unchanged" else 1)
                        result = json.loads((root / "entries/T15_1BNI/launch-result.json").read_bytes())
                        self.assertEqual(result["diagnostic_retention_valid"], kind == "unchanged")
                        if kind == "unchanged":
                            request = json.loads((root / "entries/T15_1BNI/launch-request.json").read_bytes())
                            self.assertEqual(result["python_after"], request["python"])
                        else:
                            self.assertIn("error", result["python_after"])
                        self.assertTrue((root / "final-file-manifest.json").is_file())
                    finally:
                        metadata.unlink()
                        metadata.write_bytes(original_raw)

    def test_raw_geometry_rounding_and_disulfide_mapping_are_format_rules(self):
        rows = [{"chain": "A", "resnum": "3", "icode": "", "state": "H"}]
        raw = dssp_bytes(rows)
        atoms, _ = launch.coordinate_inventory(self.source)
        first = next(key for key in atoms if key[1:4] == ("A", "3", ""))
        for value in (0.95, 1.0, 1.05):
            with self.subTest(value=value):
                adjusted = dict(atoms)
                adjusted[first] = (value, value, value, *atoms[first][3:])
                launch.bind_raw_dssp_to_atoms(raw, adjusted)
        for value in (0.949, 1.051):
            adjusted = dict(atoms)
            adjusted[first] = (value, value, value, *atoms[first][3:])
            with self.assertRaisesRegex(ValueError, "CA coordinates disagree"):
                launch.bind_raw_dssp_to_atoms(raw, adjusted)
        cysteine = dict(atoms)
        cysteine[(*first[:4], "CYS", *first[5:])] = cysteine.pop(first)
        for marker in ("C", "a", "z"):
            lines = raw.splitlines()
            row = bytearray(lines[2]); row[13] = ord(marker); lines[2] = bytes(row)
            altered = b"\n".join(lines) + b"\n"
            launch.bind_raw_dssp_to_atoms(altered, cysteine)
            with self.assertRaisesRegex(ValueError, "CA coordinates disagree"):
                launch.bind_raw_dssp_to_atoms(altered, atoms)

    def test_malformed_post_worker_lock_keeps_terminal_failure(self):
        sandbox = launch.load_module(self.repo, "entry_sandbox").EntrySandbox
        original_run = sandbox.run_logged
        malformed = (
            b"schema = 1\n", b"package = 1\n", b"package = []\n",
            b"[package]\nname = 'numpy'\nversion = '1.0'\n",
            b"package = [1]\n", b"[[package]]\nname = 'numpy'\n",
            b"[[package]]\nname = ['numpy']\nversion = '1.0'\n",
            b"[[package]]\nname = 'numpy'\nversion = [1]\n",
        )
        with package_environment(self.repo):
            lock_path = self.repo / "uv.lock"
            original_lock = lock_path.read_bytes()
            self.committed["uv.lock"] = original_lock
            for number, corrupted in enumerate(malformed):
                with self.subTest(lock=corrupted):
                    def corrupt_after_worker(owner, *arguments, **kwargs):
                        result = original_run(owner, *arguments, **kwargs)
                        lock_path.write_bytes(corrupted)
                        return result

                    args = list(self.args); args[-1] = f"malformed-lock-{number}"
                    root = self.root.with_name(self.root.name.replace("mock01", args[-1]))
                    try:
                        with mock.patch.object(sandbox, "run_logged", corrupt_after_worker), \
                                mock.patch.object(launch, "python_environment",
                                                  side_effect=REAL_PYTHON_ENVIRONMENT):
                            status, escaped = None, None
                            try:
                                status = launch.main(args + ["--execute"])
                            except (KeyError, TypeError, AttributeError, ValueError) as exc:
                                escaped = exc
                            self.assertIsNone(escaped, f"post-run lock error escaped: {escaped}")
                            self.assertEqual(status, 1)
                        result = json.loads((root / "entries/T15_1BNI/launch-result.json").read_bytes())
                        self.assertFalse(result["diagnostic_retention_valid"])
                        self.assertIn("changed bytes: uv.lock", result["identity_drift"])
                        self.assertIn("ValueError", result["python_after"]["error"])
                        manifest = json.loads((root / "final-file-manifest.json").read_bytes())
                        self.assertIn("entries/T15_1BNI/launch-result.json", manifest["files"])
                    finally:
                        lock_path.write_bytes(original_lock)

    def test_independent_parser_requires_complete_pinned_header(self):
        raw = dssp_bytes([{"chain": "A", "resnum": "3", "icode": "", "state": "H"}])
        self.assertEqual(launch.raw_dssp_assignments(raw), {("A", "3", ""): "H"})
        header = launch.DSSP_HEADER.encode()
        for changed in (b"  #  RESIDUE AA STRUCTURE ", header.replace(b"X-CA", b"X-CB")):
            with self.subTest(header=changed):
                with self.assertRaisesRegex(ValueError, "exactly one residue table"):
                    launch.raw_dssp_assignments(raw.replace(header, changed))

    def test_common_omissions_and_empty_dssp_are_retained_as_prediction_failures(self):
        original = failed_bundle
        for kind in ("common_omission", "empty_dssp"):
            with self.subTest(kind=kind):
                def incomplete(request, source, **kwargs):
                    payload = original(request, source, **kwargs)
                    a, b = payload["dssp"]["assignments"], payload["biotite_psea"]["assignments"]
                    if kind == "empty_dssp":
                        a, b = [], [r for r in b if (r["chain"], r["resnum"]) == ("C", "3")]
                    else:
                        omitted = a[0]
                        a, b = a[1:], [r for r in b if r != omitted]
                    reset_streams(payload, a, b)
                    return payload

                args = list(self.args)
                args[-1] = kind.replace("_", "-")
                root = self.root.with_name(self.root.name.replace("mock01", args[-1]))
                with mock.patch(__name__ + ".failed_bundle", side_effect=incomplete):
                    self.assertEqual(launch.main(args + ["--execute"]), 1)
                outcome = json.loads((root / "entries/T15_1BNI/launch-result.json").read_bytes())
                self.assertTrue(outcome["diagnostic_retention_valid"])
                self.assertFalse(outcome["audit"]["prediction_matches"])
                self.assertTrue(outcome["audit"]["biotite_unassigned_source_keys"])

    def test_source_normalization_and_raw_semantic_corruption_refuse_public_cli(self):
        original = failed_bundle
        for kind in ("non_pdb_normalization", "changed_coordinate", "foreign_key", "raw_Z",
                     "truncated_row", "whole_row_loss", "duplicate_key", "foreign_ca",
                     "wrong_amino_acid", "truncated_header", "changed_header"):
            with self.subTest(kind=kind):
                def corrupt(request, source, **kwargs):
                    payload = original(request, source, **kwargs)
                    if kind == "non_pdb_normalization":
                        payload["normalization"].update(bytes_block(b"arbitrary non-PDB bytes\n"))
                    elif kind == "changed_coordinate":
                        payload["normalization"].update(bytes_block(source.replace(b"   1.000", b"   2.000", 1)))
                    elif kind == "foreign_key":
                        a, b = payload["dssp"]["assignments"], payload["biotite_psea"]["assignments"]
                        a[0] = {**a[0], "resnum": "999"}
                        b[0] = {**b[0], "resnum": "999"}
                        reset_streams(payload, a, b)
                    else:
                        lines = base64.b64decode(payload["dssp"]["raw_output"]["bytes_base64"]).splitlines()
                        if kind == "raw_Z":
                            row = bytearray(lines[2]); row[16] = ord("Z"); lines[2] = bytes(row)
                            payload["dssp"]["assignments"][0]["state"] = "C"
                        elif kind == "truncated_row":
                            lines[2] = lines[2][:16]
                        elif kind == "whole_row_loss":
                            lines.pop(2)
                        elif kind == "foreign_ca":
                            row = bytearray(lines[2]); row[116:122] = b" 999.0"; lines[2] = bytes(row)
                        elif kind == "wrong_amino_acid":
                            row = bytearray(lines[2]); row[13] = ord("G"); lines[2] = bytes(row)
                        elif kind == "truncated_header":
                            lines[1] = b"  #  RESIDUE AA STRUCTURE "
                        elif kind == "changed_header":
                            lines[1] = lines[1].replace(b"X-CA", b"X-CB")
                        else:
                            lines[3] = lines[3][:5] + lines[2][5:]
                        payload["dssp"]["raw_output"] = bytes_block(b"\n".join(lines) + b"\n")
                    return payload

                args = list(self.args)
                args[-1] = kind.lower().replace("_", "-")
                root = self.root.with_name(self.root.name.replace("mock01", args[-1]))
                with mock.patch(__name__ + ".failed_bundle", side_effect=corrupt):
                    self.assertEqual(launch.main(args + ["--execute"]), 1)
                outcome = json.loads((root / "entries/T15_1BNI/launch-result.json").read_bytes())
                self.assertFalse(outcome["diagnostic_retention_valid"])
                self.assertIsNone(outcome["audit"])

    def test_pinned_input_domain_and_saved_raw_outputs_recount_without_tools(self):
        repo = Path(os.environ.get("PROTSTRUCT_TEST_BASE_ROOT",
                                   Path(__file__).resolve().parent.parent)).resolve()
        source = (repo / launch.INPUT).read_bytes()
        expected_sha = "e7a0612d97d3b9f52f2ab6efcaa94b8baa410c37e30107992e4e2564b5385796"
        self.assertEqual(launch.sha(source), expected_sha)
        _, keys = launch.coordinate_inventory(source)
        self.assertEqual(keys, {(c, str(r), "") for c in "ABC" for r in range(3, 111)})
        evidence = repo / "data/coscientists/openscientist/retained_evidence_2026-09-27_canaries02/t15_evidence"
        records = sorted(evidence.glob("*.json"))
        self.assertEqual(len(records), 8)
        for path in records:
            payload = json.loads(path.read_bytes())
            raw = base64.b64decode(payload["dssp"]["raw_output_base64"])
            self.assertEqual(len(launch.raw_dssp_assignments(raw)), payload["aggregate"]["n_dssp"])
            normalized = base64.b64decode(payload["normalization"]["bytes_base64"])
            self.assertEqual(launch.identity_bytes(normalized),
                             {key: payload["normalization"][key] for key in ("sha256", "size_bytes")})
            atoms, _ = launch.coordinate_inventory(normalized)
            source_path = evidence.parent / "t15_cache" / (path.name.split(".")[0] + ".pdb")
            saved_source = source_path.read_bytes()
            self.assertEqual(launch.sha(saved_source), payload["source_sha256"])
            source_atoms, _ = launch.coordinate_inventory(saved_source)
            self.assertEqual(atoms, source_atoms)
            launch.bind_raw_dssp_to_atoms(raw, atoms)

    def test_all_nine_raw_states_have_explicit_unchanged_collapse(self):
        rows = [{"chain": "A", "resnum": str(i + 3), "icode": "", "state": "H"} for i in range(9)]
        raw = dssp_bytes(rows).splitlines()
        states = "HBEGIPTS "
        for i, state in enumerate(states):
            line = bytearray(raw[i + 2]); line[16] = ord(state); raw[i + 2] = bytes(line)
        parsed = launch.raw_dssp_assignments(b"\n".join(raw) + b"\n")
        self.assertEqual([parsed[("A", str(i + 3), "")] for i in range(9)], list("HEEHHCCCC"))

    def test_registration_rejects_source_plan_and_input_mutations(self):
        for name in (launch.PLAN, launch.WRAPPER, launch.INPUT):
            with self.subTest(name=name):
                original = (self.repo / name).read_bytes()
                (self.repo / name).write_bytes(original + b"changed")
                with self.assertRaises(ValueError):
                    launch.main(self.args + ["--execute"])
                (self.repo / name).write_bytes(original)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.root.exists())

    def test_wrong_commit_and_old_cohort_rejected(self):
        for commit in ("2" * 40, "4a150693dd64b79c38e9e57561667215994a35a1", "short"):
            args = list(self.args)
            args[args.index("--registration-commit") + 1] = commit
            with self.assertRaises(ValueError):
                launch.main(args + ["--execute"])
        self.assertEqual(self.calls, [])

    def test_existing_root_and_dangling_alias_rejected(self):
        self.root.mkdir()
        with self.assertRaises(FileExistsError):
            launch.main(self.args + ["--execute"])
        self.root.rmdir()
        target = self.root.parent / "new-target"
        self.root.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "symlink"):
            launch.main(self.args + ["--execute"])
        self.assertTrue(self.root.is_symlink())
        self.assertFalse(target.exists())
        self.assertEqual(self.calls, [])

    def test_no_scalar_or_tampered_diagnostic_is_accepted(self):
        request = {"repo": str(self.repo), "entry_absolute": str(self.entry),
                   "executables": self.executables}
        payload = failed_bundle(request, self.source)
        for mutate in (
            lambda p: p["source"].update(sha256="0" * 64),
            lambda p: p["failure"]["counts"].update(n_biotite=1),
            lambda p: p["failure"]["counts"].update(n_dssp=True),
            lambda p: p["failure"]["biotite_only_keys"][0].update(icode="A"),
            lambda p: p["dssp"]["assignments"].append(p["dssp"]["assignments"][0]),
            lambda p: p.update(aggregate={"fraction": 1.0}),
            lambda p: p["biotite_psea"].update(pass_status="pass"),
        ):
            altered = copy.deepcopy(payload)
            mutate(altered)
            with self.assertRaises(ValueError):
                launch.audit_failed_bundle(altered, request, self.source)

    def test_unexpected_outcomes_are_retained_and_stop(self):
        for behavior in ("unexpected_success", "stdout", "timeout", "bad_bundle",
                         "version_drift", "different_key", "source_drift"):
            with self.subTest(behavior=behavior):
                self.behavior = behavior
                args = list(self.args)
                args[-1] = behavior.replace("_", "-")
                expected_root = self.root.with_name(self.root.name.replace("mock01", args[-1]))
                rc = launch.main(args + ["--execute"])
                self.assertEqual(rc, 1)
                result = json.loads((expected_root / "entries/T15_1BNI/launch-result.json").read_bytes())
                self.assertEqual(result["decision"], "STOP; no automatic retry or cohort continuation")
                self.assertTrue((expected_root / "final-file-manifest.json").is_file())
                if behavior == "different_key":
                    self.assertTrue(result["diagnostic_retention_valid"])
                    self.assertFalse(result["audit"]["prediction_matches"])
                else:
                    self.assertFalse(result["diagnostic_retention_valid"])
                # Restore only this synthetic fixture for the next independent control.
                (self.repo / launch.WRAPPER).write_bytes(self.committed[launch.WRAPPER])
        self.assertEqual(len(self.calls), 7)

    def test_worker_rejects_changed_request_before_exec(self):
        path = self.repo / "request.json"
        launch.save_new(path, {})
        with mock.patch.object(launch.os, "execvpe") as execute:
            with self.assertRaisesRegex(ValueError, "request changed"):
                launch.worker(path, "0" * 64)
            execute.assert_not_called()

    def test_worker_redirects_separate_streams_and_execs_same_group(self):
        self.assertEqual(launch.main(self.args + ["--execute"]), 0)
        request = json.loads((self.entry / "launch-request.json").read_bytes())
        fresh_entry = self.root / "worker-control"
        fresh_entry.mkdir()
        request["entry_absolute"] = str(fresh_entry)
        request_path = fresh_entry / "request.json"
        launch.save_new(request_path, request)
        digest = launch.sha(request_path.read_bytes())
        with (mock.patch.object(launch.os, "dup2") as redirect,
              mock.patch.object(launch.os, "execvpe", side_effect=RuntimeError("mock exec")) as execute):
            with self.assertRaisesRegex(RuntimeError, "mock exec"):
                launch.worker(request_path, digest)
        self.assertEqual([call.args[1] for call in redirect.call_args_list], [1, 2])
        self.assertEqual(execute.call_args.args[:2],
                         (request["wrapper_argv"][0], request["wrapper_argv"]))
        self.assertEqual((fresh_entry / "wrapper.stdout").read_bytes(), b"")
        self.assertEqual((fresh_entry / "wrapper.stderr").read_bytes(), b"")
        context = json.loads((fresh_entry / "worker-context.json").read_bytes())
        self.assertEqual(context["request_sha256"], digest)
        self.assertEqual(context["pid"], launch.os.getpid())
        self.assertEqual(context["pgid"], launch.os.getpgrp())


class PackageMetadataTests(unittest.TestCase):
    def test_pinned_metadata_replay_never_rediscovers_packages(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory).resolve()
            with package_environment(repo):
                original = REAL_PYTHON_ENVIRONMENT(repo)
                with mock.patch.object(launch.importlib.metadata, "distribution",
                                       side_effect=AssertionError("post-run package rediscovery")):
                    replay = REAL_PYTHON_ENVIRONMENT(repo, metadata_pins=original["package_metadata"])
                    self.assertEqual(original, replay)

    def test_pinned_metadata_rejects_alias_fifo_changes_and_ambiguous_fields(self):
        for kind in ("symlink", "directory_alias", "fifo", "changed", "duplicate_name",
                     "duplicate_version"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                repo = Path(directory).resolve()
                with package_environment(repo), deny_blocking_path_open():
                    original = REAL_PYTHON_ENVIRONMENT(repo)
                    target = Path(original["package_metadata"]["biotite"]["path"])
                    raw = target.read_bytes()
                    target.unlink()
                    if kind == "symlink":
                        alias = target.with_name("real")
                        alias.write_bytes(raw)
                        target.symlink_to(alias)
                    elif kind == "directory_alias":
                        parent = target.parent
                        alias = parent.with_name("alias.dist-info")
                        parent.rename(alias)
                        (alias / "METADATA").write_bytes(raw)
                        parent.symlink_to(alias, target_is_directory=True)
                    elif kind == "fifo":
                        os.mkfifo(target)
                    elif kind == "changed":
                        target.write_bytes(raw + b"changed body\n")
                    else:
                        field = "Name: biotite" if kind == "duplicate_name" else "Version: 1.7.1"
                        target.write_bytes((field + "\n").encode() + raw)
                    with mock.patch.object(launch.importlib.metadata, "distribution",
                                           side_effect=AssertionError("post-run package rediscovery")):
                        with self.assertRaises((OSError, ValueError)):
                            REAL_PYTHON_ENVIRONMENT(repo, metadata_pins=original["package_metadata"])
                    if kind.startswith("duplicate_"):
                        with self.assertRaisesRegex(ValueError, "ambiguous package"):
                            REAL_PYTHON_ENVIRONMENT(repo)


def main():
    suite = unittest.TestSuite(
        unittest.defaultTestLoader.loadTestsFromTestCase(cls)
        for cls in (LauncherTests, PackageMetadataTests)
    )
    return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
