#!/usr/bin/env python3
"""Hermetic one-entry #799 driver tests; no scientific executable or network.

Use a scratch TMPDIR when running this staged suite. Only the final isolation
test launches a short ordinary Python sleeper, never a scientific program.
"""
from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import bench_dictionary_loaded_reduce as driver
import benchmark_environment
from entry_sandbox import EntrySandbox, ProcessGroupResult


def atom(name="CA", element="C", serial=1) -> str:
    return (f"ATOM  {serial:5d} {name:^4s} ALA A   1    "
            f"{0.0:8.3f}{0.0:8.3f}{0.0:8.3f}{1.0:6.2f}{20.0:6.2f}          {element:>2s}\n")


def pdb(entry="24MR") -> bytes:
    return (f"HEADER    {'SYNTHETIC':40s}{'01-JAN-00':9s}   {entry}\n" + atom() + "END\n").encode()


def contact() -> str:
    return ":".join(["", "1->2", "bo", " A   1 ALA  CA  ", " A   1 ALA  H   ",
                     "-0.5", "-0.45", "0", "0", "0", "0", "0", "C", "H",
                     "0", "0", "0", "20", "20"]) + "\n"


class Response:
    status = 200
    headers = {"Date": "Synthetic HTTP date", "ETag": "synthetic-etag"}

    def __init__(self, data):
        self.data = data

    def read(self, size):
        return self.data[:size]

    def geturl(self):
        return "https://files.rcsb.org/download/24MR.pdb"

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


class DictionaryLoadedDriverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="dictionary-driver-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        (self.root / "scripts").mkdir()
        for name in driver.SOURCE_FILES:
            (self.root / "scripts" / name).write_text(f"# retained synthetic source {name}\n")
        self.prereg = self.root / "preregistration.md"
        self.prereg.write_text("# Synthetic preregistration; no science\n")
        self.model = self.root / "retained.pdb"
        self.model.write_bytes(pdb())
        self.reduce, self.probe, self.dictionary = [self.root / name for name in ("reduce-fake", "probe-fake", "dictionary.txt")]
        for path in (self.reduce, self.probe, self.dictionary):
            path.write_text(f"synthetic identity {path.name}")
        self.calls, self.versions, self.launches = [], [], []
        self.build_rc, self.probe_rc, self.build_stderr, self.probe_stderr = 0, 0, "", ""
        self.probe_output = contact()
        self.on_command = None
        self.version_override = None
        patches = (
            mock.patch.object(driver, "REPO_ROOT", self.root),
            mock.patch.object(driver.toolchain, "REDUCE", self.reduce),
            mock.patch.object(driver.toolchain, "PROBE", self.probe),
            mock.patch.object(driver.toolchain, "REDUCE_HET_DICT", self.dictionary),
            mock.patch.object(driver.clash, "PROBE", self.probe),
            mock.patch.object(driver.toolchain, "run_capture", side_effect=self.fake_version),
            mock.patch.object(driver.toolchain, "run_to_file", side_effect=self.fake_command),
            mock.patch.object(driver.clash, "run_to_file", side_effect=self.fake_command),
            mock.patch.object(driver.toolchain, "phenix", side_effect=AssertionError("PHENIX forbidden")),
            mock.patch.object(driver.toolchain, "phenix_build_evidence", side_effect=AssertionError("PHENIX version forbidden")),
            mock.patch.object(driver.toolchain, "external_tool_report", side_effect=AssertionError("All-tools environment report forbidden")),
            mock.patch.object(benchmark_environment, "external_tool_report", side_effect=AssertionError("Unrelated environment probe forbidden")),
            mock.patch.object(driver.toolchain, "ccp4_environment", side_effect=AssertionError("CCP4 forbidden")),
            mock.patch.object(driver.clash, "run_phenix_clashscore", side_effect=AssertionError("PHENIX forbidden")),
            mock.patch.object(driver.clash, "collect", side_effect=AssertionError("Cohort collector forbidden")),
            mock.patch.object(driver.clash, "main", side_effect=AssertionError("Benchmark main forbidden")),
            mock.patch.object(driver.urllib.request, "urlopen", side_effect=AssertionError("Network forbidden")),
        )
        for patch in patches:
            patch.start(); self.addCleanup(patch.stop)

    def fake_version(self, arguments, **kwargs):
        self.versions.append([str(x) for x in arguments])
        self.assertEqual(arguments[1:], ["-version"])
        name = "reduce" if Path(arguments[0]) == self.reduce else "probe"
        self.assertIn(Path(arguments[0]), (self.reduce, self.probe))
        self.assertEqual(kwargs["timeout"], 10)
        version = driver.toolchain.REDUCE_VERSION if name == "reduce" else driver.toolchain.PROBE_VERSION
        if self.version_override:
            return self.version_override(arguments, name)
        return subprocess.CompletedProcess(arguments, 2 if name == "reduce" else 0,
                                           "" if name == "reduce" else f"probe.{version}\n",
                                           f"reduce.{version}\n" if name == "reduce" else "")

    def fake_command(self, arguments, output, **kwargs):
        environment = json.loads((Path.cwd() / "benchmark-environment.json").read_text())
        self.assertIn("reduce", environment["external_tools"])
        self.assertTrue(environment["python_packages"]["PyYAML"])
        args = [str(x) for x in arguments]
        self.calls.append(args)
        self.assertIn(Path(args[0]), (self.reduce, self.probe))
        if Path(args[0]) == self.reduce:
            self.assertEqual(args[1:4], ["-quiet", "-build", "-DB"])
            self.assertEqual(args[4], str(self.dictionary))
            self.assertNotIn("-nuclear", args)
            data = Path(args[-1]).read_text().replace("END\n", "")
            data += atom("H", "H", 2) + "USER  MOD synthetic raw record\nEND\n"
            error, code = self.build_stderr, self.build_rc
        else:
            self.assertEqual(args[1:8], ["-u", "-q", "-mc", "-het", "-once", "ogt33 not water", "ogt33"])
            data, error, code = self.probe_output, self.probe_stderr, self.probe_rc
        Path(output).write_text(data)
        kwargs["stderr"].write(error)
        if self.on_command:
            self.on_command(args)
        return subprocess.CompletedProcess(args, code)

    def fake_launch(self, sandbox, args, log_name, **kwargs):
        self.launches.append((args, kwargs))
        self.assertEqual(kwargs["timeout"], 900)
        self.assertEqual(kwargs["env"]["PROTSTRUCT_REDUCE"], str(self.reduce))
        previous = Path.cwd()
        try:
            os.chdir(sandbox.path)
            with mock.patch.object(driver.os, "getpgrp", return_value=os.getpid()):
                code = driver.main(["--worker", str(args[-1])])
            (sandbox.path / log_name).write_text("synthetic worker log\n")
        finally:
            os.chdir(previous)
        return ProcessGroupResult([str(x) for x in args], code, 123, 123, False, None)

    def cli(self, *extra, execute=True, entry="24MR", cohort="clashscore", retained=True, suffix="evidence"):
        args = ["--cohort", cohort, "--entry", entry, "--evidence-root", str(self.root / suffix),
                "--preregistration", str(self.prereg)]
        if retained:
            args += ["--input", str(self.model), "--unknown-origin-reason", "Original download metadata unavailable"]
        if execute:
            args += ["--execute"]
        args += list(extra)
        with mock.patch.object(EntrySandbox, "run_logged", autospec=True, side_effect=self.fake_launch), \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return driver.main(args)

    def result(self, name="result.json", entry="24MR", suffix="evidence"):
        return json.loads((self.root / suffix / entry / name).read_text())

    def test_plan_only_has_no_writes_network_versions_or_helpers(self):
        before = sorted(str(path.relative_to(self.root)) for path in self.root.rglob("*"))
        with mock.patch.object(driver, "announce_benchmark_environment",
                               side_effect=AssertionError("plan must not announce/probe")):
            self.assertEqual(self.cli(execute=False, retained=False), 0)
        self.assertEqual(self.calls, []); self.assertEqual(self.versions, []); self.assertEqual(self.launches, [])
        self.assertEqual(before, sorted(str(path.relative_to(self.root)) for path in self.root.rglob("*")))

    def test_scoped_environment_uses_captured_versions_before_build(self):
        for cohort, entry, expected in (("clashscore", "24MR", {"reduce", "probe"}),
                                        ("flip", "12OC", {"reduce"})):
            with self.subTest(cohort=cohort):
                self.model.write_bytes(pdb(entry=entry))
                self.assertEqual(self.cli(cohort=cohort, entry=entry, suffix=cohort), 0)
                worker = self.result("worker-result.json", entry=entry, suffix=cohort)
                environment = self.result("benchmark-environment.json", entry=entry, suffix=cohort)
                self.assertEqual(environment, worker["benchmark_environment"])
                self.assertEqual(set(environment["external_tools"]), expected)
                for name in expected:
                    self.assertEqual(environment["external_tools"][name]["version_command"],
                                     self.result(f"{name}-version.json", entry=entry, suffix=cohort))
                self.assertIn("benchmark-environment.json",
                              self.result(entry=entry, suffix=cohort)["retained_files"])

    def test_scoped_environment_tamper_after_worker_is_refused(self):
        original_launch = self.fake_launch
        def tamper(sandbox, args, log_name, **kwargs):
            process = original_launch(sandbox, args, log_name, **kwargs)
            self.assertEqual(process.returncode, 0)
            path = sandbox.path / "benchmark-environment.json"
            metadata = json.loads(path.read_text())
            metadata["external_tools"]["reduce"]["reported_version"] = "fabricated"
            path.write_text(json.dumps(metadata))
            return process
        self.fake_launch = tamper
        self.assertEqual(self.cli(), 1)
        self.assertEqual(self.result()["status"], "failed")

    def test_symlink_alias_preserves_plan_and_strict_complete_evidence(self):
        self.assertEqual(self.root, self.root.resolve())
        alias = self.root / "repo-alias"
        alias.symlink_to(self.root, target_is_directory=True)
        plans = []
        for spelling in (self.root, alias):
            arguments = ["--cohort", "clashscore", "--entry", "24MR",
                         "--evidence-root", str(spelling / "planned-evidence"),
                         "--preregistration", str(spelling / self.prereg.name),
                         "--input", str(spelling / self.model.name),
                         "--unknown-origin-reason", "Original download metadata unavailable"]
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(driver.main(arguments), 0)
            plans.append(json.loads(output.getvalue()))
        self.assertEqual(plans[0], plans[1])
        self.assertEqual(plans[0]["evidence_root"], str(self.root / "planned-evidence"))
        self.assertFalse((self.root / "planned-evidence").exists())
        self.assertEqual(self.calls, []); self.assertEqual(self.versions, []); self.assertEqual(self.launches, [])

        workers = []
        for spelling, suffix in ((self.root, "canonical-evidence"), (alias, "alias-evidence")):
            self.assertEqual(self.cli("--evidence-root", str(spelling / suffix),
                                      "--preregistration", str(spelling / self.prereg.name),
                                      "--input", str(spelling / self.model.name), suffix=suffix), 0)
            self.assertEqual(self.result(suffix=suffix)["status"], "complete")
            worker = self.result("worker-result.json", suffix=suffix)
            # The production strict admission routine remains active; no path
            # comparison, manifest, or #841 integrity guard is mocked away.
            driver.admit_evidence(self.result("request.json", suffix=suffix),
                                  self.root / suffix / "24MR", worker)
            workers.append(worker)
        self.assertEqual(workers[0]["h_inventory"], workers[1]["h_inventory"])
        self.assertEqual(workers[0]["h_model"]["sha256"], workers[1]["h_model"]["sha256"])
        self.assertEqual(workers[0]["clashscore"], workers[1]["clashscore"])

    def test_complete_retained_input_keeps_unavailable_origin_honest_and_all_evidence(self):
        self.assertEqual(self.cli(), 0)
        outcome = self.result()
        self.assertEqual(outcome["status"], "complete")
        worker = self.result("worker-result.json")
        self.assertEqual(worker["clashscore"], 500.0)
        self.assertEqual(worker["h_inventory"]["h_all_records"], 1)
        self.assertEqual(worker["raw_user_mod_record_count"], 1)
        self.assertIn("unavailable", worker["component_dictionary_coverage"])
        self.assertIn("one-entry", outcome["completion_scope"])
        provenance = self.result("input-provenance.json")
        self.assertEqual(provenance["origin"], "retained_local")
        self.assertIsNone(provenance["original_url"]); self.assertIsNone(provenance["original_retrieved_at"])
        self.assertTrue(provenance["supplied_metadata_is_asserted"])
        self.assertEqual(provenance["original_file"]["sha256"], driver.digest(pdb()))
        self.assertEqual(self.result("reduce-version.json")["returncode"], 2)
        self.assertEqual(self.result("probe-version.json")["returncode"], 0)
        self.assertEqual(len(self.calls), 2)
        for name in ("commands/01/request.json", "commands/01/result.json", "commands/01/stdout.bin",
                     "commands/01/stderr.bin", "commands/02/result.json", "raw-user-mod.txt", "request.json",
                     "launch-request.json", "sources/standalone_reduce.py", "sources/preregistration.md"):
            self.assertIn(name, outcome["retained_files"])
        for path, sha in outcome["retained_files"].items():
            self.assertEqual(driver.digest((self.root / "evidence/24MR" / path).read_bytes()), sha)

    def test_fresh_fetch_is_exactly_once_and_keeps_response_url_and_actual_time(self):
        with mock.patch.object(driver.urllib.request, "urlopen", return_value=Response(pdb())) as fetch:
            self.assertEqual(self.cli(retained=False), 0)
        fetch.assert_called_once_with("https://files.rcsb.org/download/24MR.pdb", timeout=180)
        provenance = self.result("input-provenance.json")
        self.assertEqual(provenance["origin"], "fresh_fetch")
        self.assertEqual(provenance["requested_url"], provenance["response_url"])
        self.assertTrue(provenance["retrieved_at"].endswith("+00:00"))
        self.assertEqual(provenance["http_status"], 200)

    def test_no_overwrite_of_success_or_failed_entry_root(self):
        self.assertEqual(self.cli(), 0)
        retained = {p: p.read_bytes() for p in (self.root / "evidence").rglob("*") if p.is_file()}
        self.assertEqual(self.cli(), 1)
        self.assertEqual(retained, {p: p.read_bytes() for p in retained})
        self.build_rc = 1
        self.assertEqual(self.cli(suffix="failed"), 1)
        count = len(self.calls)
        self.assertEqual(self.cli(suffix="failed"), 1)
        self.assertEqual(len(self.calls), count)

    def test_fixed_cohorts_and_no_accidental_phenix_flip_arm(self):
        self.assertEqual(driver.DEFAULT_SET, tuple("24MR 37AS 37AP 11AF 28SZ 37BG 12LO 30IZ 9LLR 9PN7".split()))
        self.assertEqual(driver.DEFAULT_SET, tuple(driver.clash.DEFAULT_SET))
        repository = Path(driver.clash.__file__).resolve().parent.parent
        historical = json.loads((repository / "ref/research/data/round48_flip_sets.json").read_text())
        self.assertEqual(driver.FLIP_SET, tuple(row["pdb_id"] for row in historical["rows"]))
        self.assertEqual(len(driver.FLIP_SET), 41)
        self.assertEqual(len(set(driver.FLIP_SET)), 41); self.assertNotIn("12CI", driver.FLIP_SET)
        for entry, cohort in (("12CI", "flip"), ("1SAR", "clashscore"), ("24MR,37AS", "clashscore")):
            self.assertEqual(self.cli(entry=entry, cohort=cohort), 1)
        self.model.write_bytes(pdb("3G7M"))
        self.probe.unlink()  # Flip raw-build arm does not require Probe or its version.
        self.assertEqual(self.cli(entry="3G7M", cohort="flip"), 0)
        self.assertEqual(len(self.calls), 1); self.assertEqual(len(self.versions), 1)
        result = self.result("worker-result.json", entry="3G7M")
        self.assertNotIn("clashscore", result)
        self.assertIn("unavailable", result["parsed_flip_conclusions"])

    def test_bad_identity_format_models_hydrogens_and_atoms_fail_before_tools(self):
        base = pdb().decode()
        header, coords, end = base.splitlines(keepends=True)
        cases = {
            "wrong-header": pdb("37AS"), "no-header": (coords + end).encode(),
            "two-headers": (header + base).encode(),
            "multiple-models": (header + "MODEL        1\n" + coords + "ENDMDL\nMODEL        2\n" + coords + "ENDMDL\n").encode(),
            "outside-model": (header + coords + "MODEL        1\n" + coords + "ENDMDL\n").encode(),
            "pre-h": (header + atom("H", "H") + end).encode(),
            "pre-d": (header + atom("D", "D") + end).encode(),
            "missing-element": (header + coords[:76] + "  \n" + end).encode(),
            "duplicate": (header + coords + coords + end).encode(),
            "nonfinite": (header + coords[:30] + "     nan" + coords[38:] + end).encode(),
        }
        for label, data in cases.items():
            with self.subTest(case=label):
                self.model.write_bytes(data)
                self.assertEqual(self.cli(suffix=label), 1)
                self.assertEqual(self.result(suffix=label)["status"], "failed")
        self.assertEqual(self.calls, []); self.assertEqual(self.versions, [])

    def test_reduce_failure_and_zero_exit_dictionary_error_retain_attempts(self):
        for label, rc, stderr in (("nonzero", 2, "failure"), ("dictionary", 0, "ERROR CTab(dict): could not open")):
            with self.subTest(case=label):
                self.build_rc, self.build_stderr = rc, stderr
                self.assertEqual(self.cli(suffix=label), 1)
                record = self.result("commands/01/result.json", suffix=label)
                self.assertEqual(record["returncode"], rc)
                self.assertEqual((self.root / label / "24MR/commands/01/stderr.bin").read_text(), stderr)
                self.assertEqual(self.result("worker-result.json", suffix=label)["status"], "failed")
                self.assertFalse((self.root / label / "24MR/commands/02").exists())

    def test_probe_failure_never_becomes_complete(self):
        self.probe_rc, self.probe_stderr = 1, "Probe synthetic failure"
        self.assertEqual(self.cli(), 1)
        self.assertEqual(self.result("commands/02/result.json")["returncode"], 1)
        self.assertNotIn("clashscore", self.result("worker-result.json"))

    def test_version_mismatch_fails_without_scientific_run(self):
        self.version_override = lambda args, name: subprocess.CompletedProcess(args, 2, "", "reduce.OTHER\n")
        self.assertEqual(self.cli(), 1)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.result("reduce-version.json")["stderr"], "reduce.OTHER\n")

    def test_version_timeout_retains_partial_output_without_build(self):
        def timeout(args, name):
            raise subprocess.TimeoutExpired(args, 10, output=b"partial version\n", stderr=b"partial error\n")
        self.version_override = timeout
        self.assertEqual(self.cli(), 1)
        self.assertEqual(self.calls, [])
        self.assertIn("TimeoutExpired", self.result("reduce-version.json")["error"])
        directory = self.root / "evidence/24MR"
        self.assertEqual((directory / "reduce-version-stdout.bin").read_bytes(), b"partial version\n")
        self.assertEqual((directory / "reduce-version-stderr.bin").read_bytes(), b"partial error\n")

    def test_reduce_version_exit_exception_is_specific_not_generic_success(self):
        self.version_override = lambda args, name: subprocess.CompletedProcess(
            args, 0, "", f"reduce.{driver.toolchain.REDUCE_VERSION}\n")
        self.assertEqual(self.cli(), 1)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.result("reduce-version.json")["returncode"], 0)

    def test_outside_git_or_existing_root_and_missing_preregistration_refused(self):
        for root in (self.root.parent / "outside-evidence", self.root / ".git/new-evidence", self.root / "retained.pdb"):
            self.assertEqual(self.cli("--evidence-root", str(root)), 1)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.launches, [])
        self.prereg.unlink()
        self.assertEqual(self.cli(), 1)
        self.assertIn("FileNotFoundError", self.result()["error"])
        self.assertEqual(self.launches, [])

    def test_asserted_origin_is_not_presented_as_authenticated_download(self):
        self.assertEqual(self.cli("--source-url", "https://example.invalid/asserted.pdb",
                                  "--retrieved-at", "2026-09-27T00:00:00Z"), 0)
        provenance = self.result("input-provenance.json")
        self.assertEqual(provenance["origin"], "retained_local")
        self.assertEqual(provenance["original_url"], "https://example.invalid/asserted.pdb")
        self.assertEqual(provenance["original_retrieved_at"], "2026-09-27T00:00:00Z")
        self.assertTrue(provenance["supplied_metadata_is_asserted"])
        self.assertNotIn("requested_url", provenance)

    def test_late_change_after_worker_success_is_not_published(self):
        real_fake_launch = self.fake_launch
        def late_change(sandbox, args, log_name, **kwargs):
            process = real_fake_launch(sandbox, args, log_name, **kwargs)
            self.assertEqual(process.returncode, 0)
            (sandbox.path / "input.pdb").write_bytes(b"changed after worker finished\n")
            return process
        self.fake_launch = late_change
        self.assertEqual(self.cli(), 1)
        self.assertEqual(self.result("worker-result.json")["status"], "complete")
        self.assertEqual(self.result()["status"], "failed")
        self.assertIn("changed", self.result()["error"])

    def test_h_bytes_change_between_interpretation_and_identity_is_refused(self):
        original_write = driver.write_new
        def change_h(path, data):
            if path.name == "raw-user-mod.txt":
                files = list((self.root / "evidence/24MR/work").rglob("*.pdb"))
                self.assertEqual(len(files), 1)
                text = files[0].read_text().replace("END\n", "")
                files[0].write_text(text + atom("H2", "H", 3) + "END\n")
            return original_write(path, data)
        with mock.patch.object(driver, "write_new", side_effect=change_h):
            self.assertEqual(self.cli(), 1)
        self.assertEqual(self.result()["status"], "failed")
        self.assertEqual(self.result("worker-result.json")["status"], "failed")
        self.assertFalse((self.root / "evidence/24MR/commands/02").exists())

    def test_probe_stdout_truncation_after_worker_is_refused(self):
        original_launch = self.fake_launch
        def change_probe(sandbox, args, log_name, **kwargs):
            process = original_launch(sandbox, args, log_name, **kwargs)
            result = json.loads((sandbox.path / "worker-result.json").read_text())
            self.assertEqual(result["status"], "complete")
            (Path(result["probe_manifest"]).parent / "stdout.txt").write_bytes(b"")
            return process
        self.fake_launch = change_probe
        self.assertEqual(self.cli(), 1)
        self.assertEqual(self.result()["status"], "failed")
        self.assertEqual(self.result("worker-result.json")["status"], "complete")

    def test_worker_rejects_post_helper_mutation_and_inconsistent_score(self):
        original_probe = driver.clash.run_probe_clashscore
        for kind in ("stdout", "stderr", "manifest", "source_copy", "returned_score"):
            with self.subTest(kind=kind):
                def mutate(model, work, evidence):
                    score = original_probe(model, work, evidence)
                    manifest_path = Path(evidence["manifest"])
                    if kind == "returned_score":
                        return score + 1
                    if kind == "manifest":
                        manifest = json.loads(manifest_path.read_text())
                        manifest["clashscore"] += 1
                        manifest_path.write_text(json.dumps(manifest))
                    else:
                        path = (work.parent / "sources/standalone_reduce.py" if kind == "source_copy"
                                else manifest_path.parent / ("stdout.txt" if kind == "stdout" else "stderr.log"))
                        path.write_bytes(path.read_bytes() + b"changed\n")
                    return score
                with mock.patch.object(driver.clash, "run_probe_clashscore", side_effect=mutate):
                    self.assertEqual(self.cli(suffix=kind), 1)
                self.assertEqual(self.result("worker-result.json", suffix=kind)["status"], "failed")

    def test_admission_recounts_exact_legacy_ec_not_a_different_clash_definition(self):
        fields = contact().strip().split(":")
        reverse = fields.copy(); reverse[3], reverse[4] = reverse[4], reverse[3]; reverse[2] = "wo"
        min_only = fields.copy(); min_only[5], min_only[6] = "-0.5", "-0.1"
        gap_only = fields.copy(); gap_only[5], gap_only[6] = "-0.1", "-0.5"
        hbond = fields.copy(); hbond[2] = "hb"
        cases = {
            "empty": ("", 0),
            "pair-dedup": (contact() + ":".join(reverse) + "\n", 500),
            "legacy-min-gap": (":".join(min_only) + "\n", 500),
            "not-raw-gap": (":".join(gap_only) + "\n", 0),
            "not-hbond": (":".join(hbond) + "\n", 0),
        }
        for label, (raw, expected) in cases.items():
            with self.subTest(case=label):
                self.probe_output = raw
                self.assertEqual(self.cli(suffix=label), 0)
                self.assertEqual(self.result("worker-result.json", suffix=label)["clashscore"], expected)

    def test_mutated_helper_manifest_stderr_source_copy_or_result_is_refused(self):
        original_launch = self.fake_launch
        for kind in ("reduce_manifest", "probe_manifest", "reduce_stderr", "probe_stderr",
                     "source_copy", "raw_user_mod", "command_result", "worker_score"):
            with self.subTest(kind=kind):
                def change(sandbox, args, log_name, **kwargs):
                    process = original_launch(sandbox, args, log_name, **kwargs)
                    result_path = sandbox.path / "worker-result.json"
                    result = json.loads(result_path.read_text())
                    self.assertEqual(result["status"], "complete")
                    locations = {
                        "reduce_manifest": Path(result["h_model"]["path"]).parent / "manifest.json",
                        "probe_manifest": Path(result["probe_manifest"]),
                        "reduce_stderr": Path(result["h_model"]["path"]).parent / "stderr.log",
                        "probe_stderr": Path(result["probe_manifest"]).parent / "stderr.log",
                        "source_copy": sandbox.path / "sources/standalone_reduce.py",
                        "raw_user_mod": sandbox.path / "raw-user-mod.txt",
                        "command_result": sandbox.path / "commands/02/result.json",
                        "worker_score": result_path,
                    }
                    path = locations[kind]
                    if kind == "worker_score":
                        result["clashscore"] += 1
                        path.write_text(json.dumps(result))
                    else:
                        path.write_bytes(path.read_bytes() + b"changed\n")
                    return process
                self.fake_launch = change
                self.assertEqual(self.cli(suffix=kind), 1)
                self.assertEqual(self.result(suffix=kind)["status"], "failed")

    def test_changed_input_dictionary_binary_or_source_is_not_complete(self):
        for label in ("input", "dictionary", "binary", "source"):
            with self.subTest(changed=label):
                def mutate(args):
                    if Path(args[0]) != self.reduce:
                        return
                    path = {"input": Path(args[-1]), "dictionary": self.dictionary,
                            "binary": self.reduce, "source": self.root / "scripts/toolchain.py"}[label]
                    path.write_bytes(path.read_bytes() + b"changed\n")
                self.on_command = mutate
                self.assertEqual(self.cli(suffix=label), 1)
                self.assertEqual(self.result(suffix=label)["status"], "failed")
                self.assertIn("changed", self.result("worker-result.json", suffix=label)["error"].lower())

    def test_outer_timeout_preserves_request_and_never_infers_success(self):
        def timeout(sandbox, args, log_name, **kwargs):
            self.assertEqual(kwargs["timeout"], 900)
            (sandbox.path / log_name).write_text("synthetic timeout\n")
            return ProcessGroupResult(list(args), -15, 456, 456, True, 15)
        self.fake_launch = timeout
        self.assertEqual(self.cli(), 1)
        result = self.result()
        self.assertTrue(result["process"]["timed_out"])
        self.assertEqual(result["process"]["pid"], result["process"]["pgid"])
        self.assertIn("request.json", result["retained_files"])
        self.assertEqual(self.calls, [])

    def test_fetch_failure_retained_as_failure_not_empty_input(self):
        with mock.patch.object(driver.urllib.request, "urlopen", side_effect=OSError("synthetic network failure")):
            self.assertEqual(self.cli(retained=False), 1)
        self.assertIn("synthetic network failure", self.result("worker-result.json")["error"])
        self.assertEqual(self.calls, [])

    def test_real_entry_sandbox_timeout_is_owned_and_bounded(self):
        # Ordinary Python only; this verifies the actual adapter selected by the driver.
        sandbox = EntrySandbox(self.root / "python-only", "synthetic")
        result = sandbox.run_logged([sys.executable, "-B", "-c", "import time; time.sleep(10)"],
                                    "sleep.log", timeout=0.1, terminate_grace=0.05)
        self.assertTrue(result.timed_out)
        self.assertEqual(result.pid, result.pgid)
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
