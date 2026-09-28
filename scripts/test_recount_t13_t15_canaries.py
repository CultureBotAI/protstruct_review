#!/usr/bin/env python3
"""Hermetic replay fixtures: no network, scientific library, executable, or real git."""
from __future__ import annotations

import base64
from contextlib import redirect_stderr
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest import mock

import yaml

import recount_t13_t15_canaries as replay


HISTORICAL_MAIN = b"""
def _repository_location(path):
    return path, path.relative_to(REPO_ROOT).as_posix()

def main():
    p = argparse.ArgumentParser()
    p.add_argument('mtz', type=Path)
    p.add_argument('--eval-id')
    p.add_argument('--columns')
    p.add_argument('--logdir', type=Path)
    args = p.parse_args()
    logs, _ = _repository_location(args.logdir)
    try:
        logs.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise SystemExit('refusing to overwrite')
    try_aimless(args.mtz, logs)
    run_ctruncate(args.mtz, args.columns, logs)
"""


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def tiny_mtz():
    raw = bytearray(80)
    raw[:4] = b"MTZ "
    raw[4:8] = struct.pack("<i", 31)
    raw[8:12] = bytes.fromhex("44410000")
    return bytes(raw) + b"\0" * 40 + b"NCOL 5 2 0".ljust(80) + b"END".ljust(80)


def dssp_row(resnum, state):
    row = list(" " * 18)
    row[5:10] = f"{resnum:5d}"
    row[11], row[13], row[16] = "A", "A", state
    return "".join(row)


class CanaryReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="test-canary-replay-")
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name).resolve()
        self.sources = {name: ("historical " + name).encode() for name in replay.SOURCE_PINS}
        self.sources["scripts/t13_data_quality.py"] = HISTORICAL_MAIN
        self.pins = {name: replay.sha(raw) for name, raw in self.sources.items()}
        self.input = tiny_mtz()
        for name, value in (("SOURCE_PINS", self.pins), ("INPUT_SHA", replay.sha(self.input))):
            patcher = mock.patch.object(replay, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name, raw in self.sources.items():
            path = self.repo / replay.SNAPSHOT / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        input_path = self.repo / replay.INPUT
        input_path.parent.mkdir(parents=True, exist_ok=True)
        input_path.write_bytes(self.input)
        self.roots = {}
        for label, prefix in replay.PREFIXES.items():
            root = self.repo / replay.BASE / ("retained_evidence_2026-09-27_" + label)
            self.roots[label] = root
            dump(root / "launch-root.json", {
                "format": "preregistered-canaries-launch-root-v1",
                "preregistration_commit": replay.COMMIT, "source_hashes": self.pins,
            })
            ids = ["T15_" + pdb for pdb in replay.COHORT[:prefix]]
            if label == "canaries01":
                ids.insert(0, "T13_1SAR")
            for index, entry_id in enumerate(ids):
                self.make_entry(root, entry_id, index, last=index == len(ids) - 1)

    def make_success(self, root, entry, pdb):
        source = root / "t15_cache" / (pdb.lower() + ".pdb")
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(("synthetic " + pdb).encode())
        normalized = b"HEADER synthetic normalized input\n"
        raw = ("DSSP NKI version 4.6.1\n  #  RESIDUE\n"
               + dssp_row(1, "H") + "\n" + dssp_row(2, "E") + "\n").encode()
        values = {"n_dssp": 2, "n_biotite": 2, "n_scored": 2, "n_dropped": 0,
                  "n_agree": 2, "fraction": 1.0, "dssp_h": 1, "dssp_e": 1, "dssp_c": 0,
                  "dssp_ss_content": 1.0}
        source_digest, normalized_digest = replay.sha(source.read_bytes()), replay.sha(normalized)
        payload = {"subject_ref": None, "input_sha256": source_digest,
                   "normalization_mode": "gemmi convert", "normalized_sha256": normalized_digest,
                   "gemmi_version": "gemmi 0.7.5", "dssp_version": "mkdssp version 4.6.1",
                   "biotite_version": "1.7.1", **values}
        bundle = "EVAL_BENCH_T15_SS_" + replay.sha(
            yaml.safe_dump(payload, sort_keys=True, allow_unicode=True).encode())[:16]
        evidence_path = root / "t15_evidence" / (pdb.lower() + ".t15-evidence.json")
        dump(evidence_path, {
            "evidence_format": "protstruct-review-t15-v1", "subject_ref": None,
            "metric_definition_refs": list(replay.METRICS), "source_sha256": source_digest,
            "bundle_ref": bundle, "aggregate": values,
            "normalization": {"bytes_base64": base64.b64encode(normalized).decode(),
                              "sha256": normalized_digest, "size_bytes": len(normalized),
                              "tool_version": "gemmi 0.7.5"},
            "dssp": {"raw_output_base64": base64.b64encode(raw).decode(),
                     "raw_output_sha256": replay.sha(raw), "raw_output_size_bytes": len(raw),
                     "tool_version": "mkdssp version 4.6.1"},
            "biotite_psea": {"tool_version": "1.7.1"},
            "per_residue_assignments": [{"chain": "A", "resnum": str(i), "icode": "",
                                        "dssp": state, "biotite_psea": state}
                                       for i, state in ((1, "H"), (2, "E"))],
        })
        provenance = "gemmi 0.7.5 mkdssp version 4.6.1 1.7.1 " + source_digest + " " + normalized_digest
        rows = []
        for index, metric in enumerate(replay.METRICS):
            rows.append({
                "id": bundle + ("_M_agreement" if index == 0 else "_M_content"),
                "catalog_task_ref": "T15", "stage": "final", "scope": "complex",
                "metric_definition_ref": metric, "oracle_family": "non_cctbx",
                "oracle_tool_ref": "DSSP + biotite P-SEA" if index == 0 else "DSSP",
                "bundle_ref": bundle, "pass_status": "informational",
                "oracle_measure": {"value_numeric": 1.0, "unit": "fraction"},
                "evidence_refs": [evidence_path.relative_to(self.repo).as_posix()],
                "notes": provenance + (" 2/2 concordant over residues scored by both "
                                      "(DSSP 2, biotite 2, 0 scored by only one and excluded)"
                                      if index == 0 else " (1 H + 1 E) / 2 = 1.0000"),
            })
        (root / "t15_cache" / ("t15_" + pdb.lower() + ".log")).write_text(yaml.safe_dump(rows))
        dump(entry / "benchmark.json", {"rows": [{
            "pdb_id": pdb, "agreement": 1.0, "ss_content": 1.0, "n_concordant": 2,
            "n_scored": 2, "n_dssp": 2, "n_biotite": 2, "n_dropped": 0,
            "clears_provisional_content_precondition": True,
            "meets_provisional_0_65_expectation": True,
        }], "skipped": [], "summary": {}})
        (entry / "launcher.log").write_text("synthetic successful launcher\n")

    def make_t13(self, entry):
        logs = entry / "tool_logs"
        logs.mkdir()
        (logs / "aimless.log").write_text("CCP4 9.0.015 AIMLESS version 0.8.3\n"
                                         "hkl_unmerge_list::prepare - EMPTY\n")
        (logs / "ctruncate.log").write_text(
            "CCP4 9.0.015 ctruncate version 1.17.29\n"
            "Estimate of Wilson B factor: 14.542\nTwin fraction estimate from L-test: 0.03\n"
            "Anisotropic B scaling (orthogonal coords):\n\n"
            "| 10.0 0.0 0.0 |\n| 0.0 17.0 0.0 |\n| 0.0 0.0 14.0 |\n\n"
            "Some anisotropy detetect.\n"
            "No translational NCS detected (with resolution limited to  4.00 A)\n"
            "First principles calculation has found no potential twinning operators\n"
            "3.90 no 1\n3.67 no 1\n3.44 yes 1\n2.67 no 1\n")
        (logs / "ctruncate_out.mtz").write_bytes(self.input)
        expected = {"T13_wilson_b": {"value_numeric": 14.542, "unit": "Å²"},
                    "T13_l-test_twinning": {"value_numeric": .03, "unit": "fraction"},
                    "T13_anisotropy_δb_aniso": {"value_numeric": 7.0, "unit": "Å²"},
                    "T13_tncs_flag": {"value_text": "false"},
                    "T13_ice-ring_flags": {"value_text": "3.44Å"},
                    "T13_aimless_status": {"value_text": "failed"}}
        rows = []
        for metric, value in expected.items():
            attempt = metric == "T13_aimless_status"
            rows.append({
                "id": "synthetic_" + metric, "catalog_task_ref": "T13", "stage": "all",
                "scope": "dataset", "subject_ref": "mtz:sha256:" + replay.INPUT_SHA,
                "scope_selector": "all input reflections" if attempt else "/*/*/[F-obs,SIGF-obs]",
                "metric_definition_ref": metric, "oracle_family": "non_cctbx",
                "oracle_tool_ref": "CCP4 aimless" if attempt else "ctruncate",
                "agent_claim": {"is_not_applicable": True}, "oracle_measure": value,
                "pass_status": "informational", "evidence_refs": [
                    (logs / ("aimless.log" if attempt else "ctruncate.log")).relative_to(self.repo).as_posix()],
            })
        (entry / "launcher.log").write_text(yaml.safe_dump(rows))

    def make_entry(self, root, entry_id, index, last):
        entry = root / "entries" / entry_id
        entry.mkdir(parents=True)
        moment = datetime(2026, 9, 28, tzinfo=timezone.utc) + timedelta(seconds=10 * index)
        request = {"mode": "execute", "preregistration_commit": replay.COMMIT,
                   "repo": "/historical/checkout", "root": root.relative_to(self.repo).as_posix(),
                   "entry": entry.relative_to(self.repo).as_posix(), "source_hashes": self.pins,
                   "timeout_seconds": 900, "t13_input_sha256_before": replay.INPUT_SHA,
                   "python": "3.12.11 synthetic", "python_packages": {"gemmi": "0.7.5", "biotite": "1.7.1"},
                   "started_at": moment.isoformat()}
        old = "/historical/checkout"
        historical_entry = old + "/" + request["entry"]
        historical_root = old + "/" + request["root"]
        if entry_id == "T13_1SAR":
            request["argv"] = [old + "/.venv/bin/python", "-B",
                               old + "/scripts/t13_data_quality.py", old + "/" + replay.INPUT,
                               "--columns", "F-obs,SIGF-obs", "--eval-id", "EVAL_T13_OPERATIONAL_CANARY",
                               "--logdir", historical_entry + "/tool_logs"]
        else:
            request["argv"] = [old + "/.venv/bin/python", "-B",
                               old + "/scripts/bench_t15_ss_agreement.py", entry_id[4:],
                               "--cache", historical_root + "/t15_cache", "--evidence-dir",
                               historical_root + "/t15_evidence", "--json",
                               historical_entry + "/benchmark.json"]
        dump(entry / "launch-request.json", request)
        if entry_id == "T13_1SAR":
            self.make_t13(entry)
        elif not last:
            self.make_success(root, entry, entry_id[4:])
        elif root.name.endswith("canaries01"):
            (entry / "launcher.log").write_text("socket.gaierror: nodename nor servname provided, or not known")
        else:
            (entry / "launcher.log").write_text("t15_ss_agreement failed\n")
            (root / "t15_cache" / "1bni.pdb").write_text("".join(
                f"ATOM  {serial:5d} {atom:>4s} VAL C   3 \n"
                for serial, atom in enumerate(("CA", "C", "O"), 1)))
            (root / "t15_cache" / "t15_1bni.log").write_text(
                "assigners scored different residue sets: DSSP-only=0, biotite-only=1")
            dump(entry / "benchmark.json", {"rows": [], "skipped": [
                {"pdb_id": "1BNI", "reason": "t15_ss_agreement failed"}], "summary": {"n": 0}})
        dump(entry / "launch-result.json", {
            "process": {"arguments": request["argv"], "returncode": 1 if last else 0,
                        "pid": index + 100, "pgid": index + 100, "timed_out": False,
                        "termination_signal": None, "start_new_session": True},
            "launcher_error": None, "interrupted_pgids": [], "source_hashes_after": self.pins,
            "sources_unchanged": True, "t13_input_sha256_after": replay.INPUT_SHA,
            "t13_input_unchanged": True, "completed_at": (moment + timedelta(seconds=1)).isoformat(),
            "files_before_result_manifest": replay.inventory(root),
        })

    def rebind(self, label="canaries02"):
        """Re-hash retained files to test semantic guards independently of file hashes."""
        root = self.roots[label]
        entries = sorted((root / "entries").iterdir(),
                         key=lambda p: replay.load_json(p / "launch-request.json")["started_at"])
        for entry in entries:
            path = entry / "launch-result.json"
            value = replay.load_json(path)
            files = replay.inventory(root)
            value["files_before_result_manifest"] = {
                ref: files[ref] for ref in value["files_before_result_manifest"] if ref in files}
            dump(path, value)

    def change_json(self, relative, mutate, label="canaries02", rebind=True):
        path = self.roots[label] / relative
        value = replay.load_json(path)
        mutate(value)
        dump(path, value)
        if rebind:
            self.rebind(label)

    def test_portable_both_roots_with_no_git_or_current_wrapper(self):
        current = self.repo / "scripts/t15_ss_agreement.py"
        current.parent.mkdir()
        current.write_text("raise AssertionError('today is not the instrument')\n")
        before = replay.inventory(self.repo)
        with mock.patch.object(subprocess, "run", side_effect=AssertionError("external execution")):
            result = replay.recount(self.repo)
        self.assertEqual(before, replay.inventory(self.repo))
        self.assertEqual([(r["t15_admitted"], r["t15_failed"], len(r["unstarted_t15"]))
                          for r in result["roots"]], [(5, 1, 10), (8, 1, 7)])
        self.assertEqual(result["roots"][0]["attempts"][0]["status"], "operational_only")
        self.assertTrue(result["roots"][0]["attempts"][0][
            "historical_overwrite_refusal_with_tools_and_writes_denied"])
        self.assertEqual(result["roots"][1]["attempts"][-1]["status"], "failed_denominator_admission")
        self.assertIn("unavailable", result["roots"][1]["attempts"][-1]["raw_assignments"])
        inspection = result["roots"][1]["attempts"][-1]["input_coordinate_inspection"]
        self.assertEqual(inspection["atom_residues"], 1)
        self.assertEqual(inspection["residues_per_chain"], {"C": 1})
        self.assertEqual(inspection["incomplete_backbone_residues"], [{
            "chain": "C", "resnum": "3", "icode": "", "resname": "VAL",
            "missing_backbone_atoms": ["N"],
        }])
        self.assertTrue(all(not root["complete_cohort"] for root in result["roots"]))

    def test_missing_snapshot_falls_back_only_to_historical_git_objects(self):
        self.assert_historical_fallback(self.repo)

    def test_repository_alias_preserves_exact_historical_git_fallback(self):
        with tempfile.TemporaryDirectory(prefix="test-canary-alias-") as temporary:
            alias = Path(temporary) / "repository-alias"
            alias.symlink_to(self.repo, target_is_directory=True)
            self.assertNotEqual(alias, self.repo)
            self.assertEqual(alias.resolve(), self.repo)
            self.assert_historical_fallback(alias)

    def assert_historical_fallback(self, repository):
        exists = Path.exists
        snapshot = self.repo / replay.SNAPSHOT
        def historical(command, **kwargs):
            self.assertEqual(command[:4], ["git", "-C", str(self.repo), "show"])
            revision, name = command[4].split(":", 1)
            self.assertEqual(revision, replay.COMMIT)
            return subprocess.CompletedProcess(command, 0, self.sources[name])
        with mock.patch.object(Path, "exists", lambda p: False if p == snapshot else exists(p)), \
                mock.patch.object(subprocess, "run", side_effect=historical) as calls:
            result = replay.recount(repository)
        self.assertEqual(calls.call_count, 8)
        self.assertEqual({call.args[0][4] for call in calls.call_args_list},
                         {f"{replay.COMMIT}:{name}" for name in self.sources})
        self.assertEqual(result["source_pin_verification"], "preregistered_git_commit")

    def test_changed_snapshot_does_not_fall_back_to_live_source(self):
        (self.repo / replay.SNAPSHOT / "scripts/t15_ss_agreement.py").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "historical source digest mismatch"):
            replay.recount(self.repo)

    def test_missing_attempt_is_not_a_success_only_cohort(self):
        entry = self.roots["canaries02"] / "entries/T15_1BNI"
        entry.rename(entry.with_name("hidden_failure"))
        with self.assertRaisesRegex(ValueError, "missing/extra attempted entry"):
            replay.recount(self.repo)

    def test_unmanifested_file_is_not_silently_ignored(self):
        (self.roots["canaries02"] / "unrecorded.txt").write_text("unrecorded")
        with self.assertRaisesRegex(ValueError, "unmanifested"):
            replay.recount(self.repo)

    def test_hash_mismatch_even_for_a_successful_early_attempt(self):
        path = self.roots["canaries02"] / "entries/T15_1UBQ/launcher.log"
        path.write_bytes(path.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "manifest file/hash mismatch"):
            replay.recount(self.repo)

    def test_missing_required_manifest_entry_cannot_hide_launch_log(self):
        self.change_json("entries/T15_1UBQ/launch-result.json",
                         lambda r: r["files_before_result_manifest"].pop("entries/T15_1UBQ/launcher.log"))
        with self.assertRaisesRegex(ValueError, "manifest omits required"):
            replay.recount(self.repo)

    def test_source_pin_omission_cannot_shrink_provenance(self):
        self.change_json("entries/T15_1UBQ/launch-request.json",
                         lambda r: r["source_hashes"].pop("scripts/t15_ss_agreement.py"))
        with self.assertRaisesRegex(ValueError, "launch request provenance"):
            replay.recount(self.repo)

    def test_own_output_must_be_in_its_attempt_manifest_not_only_a_later_one(self):
        self.change_json("entries/T15_1UBQ/launch-result.json", lambda r:
                         r["files_before_result_manifest"].pop("t15_evidence/1ubq.t15-evidence.json"))
        with self.assertRaisesRegex(ValueError, "manifest snapshot omits"):
            replay.recount(self.repo)

    def test_changed_executed_argv_is_rejected(self):
        self.change_json("entries/T15_1UBQ/launch-result.json",
                         lambda r: r["process"]["arguments"].__setitem__(3, "1LYZ"))
        with self.assertRaisesRegex(ValueError, "argv mismatch"):
            replay.recount(self.repo)

    def test_overlapping_entries_are_rejected(self):
        self.change_json("entries/T15_1LYZ/launch-request.json",
                         lambda r: r.__setitem__("started_at", "2026-09-28T00:00:00+00:00"))
        with self.assertRaisesRegex(ValueError, "overlapping"):
            replay.recount(self.repo)

    def test_failure_cannot_be_relabelled_success(self):
        self.change_json("entries/T15_1BNI/launch-result.json",
                         lambda r: r["process"].__setitem__("returncode", 0))
        with self.assertRaisesRegex(ValueError, "success/failure sequence"):
            replay.recount(self.repo)

    def test_failure_log_and_skipped_row_must_remain(self):
        self.change_json("entries/T15_1BNI/benchmark.json", lambda r: r.__setitem__("skipped", []))
        with self.assertRaisesRegex(ValueError, "skipped outcome missing"):
            replay.recount(self.repo)

    def test_raw_dssp_disagreement_is_caught_after_rehashing_payload(self):
        def mutate(e):
            raw = base64.b64decode(e["dssp"]["raw_output_base64"]).replace(
                dssp_row(1, "H").encode(), dssp_row(1, "E").encode())
            e["dssp"]["raw_output_base64"] = base64.b64encode(raw).decode()
            e["dssp"]["raw_output_sha256"] = replay.sha(raw)
        self.change_json("t15_evidence/1ubq.t15-evidence.json", mutate)
        with self.assertRaisesRegex(ValueError, "raw DSSP/assignment mismatch"):
            replay.recount(self.repo)

    def test_duplicate_and_unequal_assignment_keys_are_rejected(self):
        def mutate(e):
            e["per_residue_assignments"][1]["resnum"] = "1"
        self.change_json("t15_evidence/1ubq.t15-evidence.json", mutate)
        with self.assertRaisesRegex(ValueError, "duplicate assignment"):
            replay.recount(self.repo)

    def test_raw_dssp_unknown_state_cannot_become_coil_silently(self):
        raw = b"DSSP version 4.6.1\n  #  RESIDUE\n" + dssp_row(1, "?").encode()
        with self.assertRaisesRegex(ValueError, "unknown raw DSSP state"):
            replay.raw_dssp_assignments(raw)

    def test_subject_override_is_not_accepted_for_unlabelled_invocation(self):
        self.change_json("t15_evidence/1ubq.t15-evidence.json",
                         lambda e: e.__setitem__("subject_ref", "model:someone_else"))
        with self.assertRaisesRegex(ValueError, "no subject override"):
            replay.recount(self.repo)

    def test_false_or_changed_aggregate_does_not_pass_as_equal(self):
        self.change_json("t15_evidence/1ubq.t15-evidence.json",
                         lambda e: e["aggregate"].__setitem__("n_dropped", False))
        with self.assertRaisesRegex(ValueError, "aggregate count type"):
            replay.recount(self.repo)

    def test_version_placeholder_is_rejected(self):
        self.change_json("t15_evidence/1ubq.t15-evidence.json",
                         lambda e: e["dssp"].__setitem__("tool_version", "unknown"))
        with self.assertRaisesRegex(ValueError, "version mismatch"):
            replay.recount(self.repo)

    def test_informational_wrapper_cannot_gain_criterion_metadata(self):
        path = self.roots["canaries02"] / "t15_cache/t15_1ubq.log"
        rows = yaml.safe_load(path.read_text())
        rows[0]["pass_criterion"] = ">=0.65"
        path.write_text(yaml.safe_dump(rows))
        self.rebind()
        with self.assertRaisesRegex(ValueError, "criterion metadata"):
            replay.recount(self.repo)

    def test_wrapper_numeric_notes_cannot_drift_from_counted_stream(self):
        path = self.roots["canaries02"] / "t15_cache/t15_1ubq.log"
        path.write_text(path.read_text().replace("2/2 concordant", "1/2 concordant"))
        self.rebind()
        with self.assertRaisesRegex(ValueError, "wrapper note counts"):
            replay.recount(self.repo)

    def test_t13_missing_negative_flag_text_is_not_false(self):
        path = self.roots["canaries01"] / "entries/T13_1SAR/tool_logs/ctruncate.log"
        path.write_text(path.read_text().replace(
            "No translational NCS detected (with resolution limited to  4.00 A)", "TRUNCATED"))
        self.rebind("canaries01")
        with self.assertRaisesRegex(ValueError, "explicit negative T13 flag"):
            replay.recount(self.repo)

    def test_historical_refusal_does_not_execute_science_if_guard_regresses(self):
        source = HISTORICAL_MAIN.replace(b"raise SystemExit('refusing to overwrite')", b"pass")
        logs = self.roots["canaries01"] / "entries/T13_1SAR/tool_logs"
        with self.assertRaisesRegex(ValueError, "scientific execution forbidden"):
            replay.check_overwrite_refusal(self.repo, logs, source)

    def test_duplicate_json_yaml_and_unsafe_paths_are_rejected(self):
        path = self.repo / "duplicate.json"
        path.write_text('{"value": 1, "value": 2}')
        with self.assertRaisesRegex(ValueError, "duplicate mapping"):
            replay.load_json(path)
        with self.assertRaisesRegex(ValueError, "duplicate mapping"):
            yaml.load("value: 1\nvalue: 2\n", Loader=replay.UniqueYaml)
        for reference in ("../outside", "/absolute", "a/../b", "a\\b"):
            with self.subTest(reference=reference), self.assertRaisesRegex(ValueError, "unsafe path"):
                replay.safe_path(self.repo, reference)

    def test_symlink_alias_is_rejected_without_following_target(self):
        alias = self.roots["canaries02"] / "alias"
        alias.symlink_to(self.repo / replay.INPUT)
        with self.assertRaisesRegex(ValueError, "symlink"):
            replay.recount(self.repo)

    def test_cli_failure_exits_two_without_partial_report(self):
        with mock.patch.object(replay, "recount", side_effect=ValueError("bad evidence")), \
                mock.patch.object(replay.sys, "argv", ["recount"]), redirect_stderr(io.StringIO()) as out:
            with self.assertRaises(SystemExit) as error:
                replay.main()
        self.assertEqual(error.exception.code, 2)
        self.assertIn("bad evidence", out.getvalue())


class RetainedCanaryReplayTests(unittest.TestCase):
    def test_committed_stopped_records_replay_without_execution_or_writes(self):
        repo = Path(os.environ.get("PROTSTRUCT_TEST_BASE_ROOT", replay.REPO_ROOT)).resolve()
        roots = [repo / replay.BASE / ("retained_evidence_2026-09-27_" + label)
                 for label in replay.PREFIXES]
        roots.append(repo / replay.SNAPSHOT)
        self.assertTrue(roots[-1].is_dir(), "committed source snapshot required for shallow CI")
        before = [replay.inventory(root) for root in roots]
        input_before = (repo / replay.INPUT).read_bytes()
        original_open = Path.open
        def readonly_open(path, mode="r", *args, **kwargs):
            self.assertFalse(any(flag in mode for flag in "wax+"), "replay attempted a file write")
            return original_open(path, mode, *args, **kwargs)
        with mock.patch.object(replay.subprocess, "run", side_effect=AssertionError("external execution")), \
                mock.patch.object(Path, "open", readonly_open), \
                mock.patch.object(Path, "write_text", side_effect=AssertionError("write_text")), \
                mock.patch.object(Path, "write_bytes", side_effect=AssertionError("write_bytes")), \
                mock.patch.object(Path, "mkdir", side_effect=AssertionError("mkdir")):
            result = replay.recount(repo)
        self.assertEqual(result["source_pin_verification"], "retained_snapshot")
        self.assertEqual([(r["t15_admitted"], r["t15_failed"], len(r["unstarted_t15"]))
                          for r in result["roots"]], [(5, 1, 10), (8, 1, 7)])
        operational = result["roots"][0]["attempts"][0]
        self.assertEqual(operational["entry_id"], "T13_1SAR")
        self.assertEqual(operational["status"], "operational_only")
        self.assertEqual(operational["measurement_rows"], 6)
        self.assertEqual(operational["output_reflections"], 7248)
        self.assertTrue(operational["historical_overwrite_refusal_with_tools_and_writes_denied"])
        self.assertEqual(result["roots"][0]["attempts"][-1]["status"], "failed_fetch")
        self.assertEqual(result["roots"][1]["attempts"][-1]["status"], "failed_denominator_admission")
        inspection = result["roots"][1]["attempts"][-1]["input_coordinate_inspection"]
        self.assertEqual(inspection["atom_records"], 2547)
        self.assertEqual(inspection["atom_residues"], 324)
        self.assertEqual(inspection["residues_per_chain"], {"A": 108, "B": 108, "C": 108})
        self.assertEqual(inspection["incomplete_backbone_residues"], [{
            "chain": "C", "resnum": "3", "icode": "", "resname": "VAL",
            "missing_backbone_atoms": ["N"],
        }])
        self.assertTrue(all(not root["complete_cohort"] for root in result["roots"]))
        observed = [(r["pdb_id"], r["n_scored"], r["n_agree"], r["dssp_h"] + r["dssp_e"])
                    for r in result["roots"][1]["attempts"] if r["status"] == "admitted_informational"]
        self.assertEqual(observed, [
            ("1UBQ", 76, 57, 44), ("1LYZ", 129, 93, 64), ("1LZ1", 130, 98, 67),
            ("2PTN", 223, 154, 104), ("7RSA", 124, 98, 70), ("1CA2", 256, 181, 119),
            ("1MBN", 153, 130, 120), ("3EST", 240, 163, 116),
        ])
        self.assertEqual(before, [replay.inventory(root) for root in roots])
        self.assertEqual(input_before, (repo / replay.INPUT).read_bytes())


if __name__ == "__main__":
    unittest.main()
