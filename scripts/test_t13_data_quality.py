#!/usr/bin/env python3
"""T13 emission and CCP4-adapter regression tests; no scientific executables."""
from __future__ import annotations

import copy
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
import hashlib
import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import check_pass_status as status_guard  # noqa: E402
import check_referential_integrity as integrity  # noqa: E402
import t13_data_quality as t13  # noqa: E402
from protstruct_review.models import MeasurementValue  # noqa: E402


LOG_PATH = REPO / "data/coscientists/openscientist/t13_oracle_logs/ctruncate.log"
AIMLESS_LOG = LOG_PATH.with_name("aimless.log")
EVAL_ID = "EVAL_t13_test_2026-09-23"
SUBJECT = "mtz:sha256:" + "a" * 64
SELECTOR = "/*/*/[F-obs,SIGF-obs]"


def rows_for(stats: dict, aimless: dict | None = None) -> list[dict]:
    return yaml.safe_load(t13.render_yaml(
        stats, EVAL_ID, aimless or {
            "status": "missing", "reason": "synthetic missing-tool fixture", "log": None,
        }, subject_ref=SUBJECT, scope_selector=SELECTOR,
    ))


def guard_failures(row: dict) -> list[str]:
    failures: list[str] = []
    status_guard.check_measurement(
        Path(EVAL_ID + ".yaml"), EVAL_ID + ".yaml", EVAL_ID,
        date(2026, 9, 23), row, {}, False, failures, [], set(), set(),
    )
    return failures


class EmissionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.stats = t13.parse_ctruncate(LOG_PATH.read_text(), str(LOG_PATH))

    def assert_admissible(self, rows: list[dict]) -> None:
        for row in rows:
            with self.subTest(metric=row["metric_definition_ref"]):
                MeasurementValue.model_validate(row)
                self.assertEqual(guard_failures(row), [])
                self.assertEqual(row["pass_status"], "informational")
                self.assertFalse({
                    "pass_criterion", "pass_criterion_ref", "criterion_preconditions",
                } & row.keys())
                self.assertEqual(row["scope"], "dataset")
                self.assertEqual(row["subject_ref"], SUBJECT)
                self.assertEqual(row["scope_selector"],
                                 "all input reflections" if row["oracle_tool_ref"] == "CCP4 aimless"
                                 else SELECTOR)
                self.assertEqual(row["oracle_family"], "non_cctbx")

    def test_retained_output_all_six_paths_pass_schema_and_guard(self) -> None:
        rows = rows_for(self.stats, {
            "status": "failed", "reason": "merged amplitudes", "log": str(AIMLESS_LOG),
        })
        self.assertEqual(len(rows), 6)
        self.assert_admissible(rows)
        by_metric = {row["metric_definition_ref"]: row for row in rows}
        self.assertEqual(by_metric["T13_wilson_b"]["oracle_measure"], {
            "value_numeric": 14.542, "unit": "Å²",
        })
        self.assertEqual(by_metric["T13_l-test_twinning"]["oracle_measure"], {
            "value_numeric": 0.03, "unit": "fraction",
        })
        self.assertIn("moments-based twin fraction 0.02", by_metric["T13_l-test_twinning"]["notes"])
        self.assertAlmostEqual(
            by_metric["T13_anisotropy_δb_aniso"]["oracle_measure"]["value_numeric"],
            17.8813 - 10.5625,
        )
        self.assertEqual(by_metric["T13_tncs_flag"]["oracle_measure"], {"value_text": "false"})
        self.assertEqual(by_metric["T13_ice-ring_flags"]["oracle_measure"], {"value_text": "3.44Å"})
        catalog = yaml.safe_load((REPO / "ref/catalog.yaml").read_text())
        task = next(task for task in catalog["catalog_tasks"] if task["id"] == "T13")
        for row in rows:
            self.assertIn(row["metric_definition_ref"], task["metric_definition_refs"])
            self.assertIn(row["oracle_tool_ref"], task["oracle_tool_refs"])
            self.assertEqual(row["evidence_refs"], [
                (AIMLESS_LOG if row["oracle_tool_ref"] == "CCP4 aimless" else LOG_PATH)
                .relative_to(REPO).as_posix()
            ])
            for ref in row["evidence_refs"]:
                self.assertEqual(integrity._check_evidence_path(
                    ref, Path(EVAL_ID + ".yaml"), "evidence_refs", reject_self=True,
                ), ([], True))

    def test_old_failure_paths_are_not_hidden_by_new_status_names(self) -> None:
        for fraction, spread in [(0.0, 0.0), (0.05, 20.0), (0.2, 20.001), (0.5, 45.0)]:
            for tncs, rings in [(False, []), (True, [2.67, 3.44])]:
                stats = {**self.stats, "twin_fraction_l": fraction, "delta_b_aniso": spread,
                         "tncs_flag": tncs, "ice_ring_resolutions_flagged": rings}
                rows = rows_for(stats)
                self.assert_admissible(rows)
                by_metric = {r["metric_definition_ref"]: r for r in rows}
                self.assertEqual(by_metric["T13_tncs_flag"]["oracle_measure"]["value_text"],
                                 str(tncs).lower())
                self.assertEqual(by_metric["T13_ice-ring_flags"]["oracle_measure"]["value_text"],
                                 "2.67Å,3.44Å" if rings else "none")

    def test_guard_rejects_precise_legacy_failures(self) -> None:
        rows = rows_for(self.stats)
        for row in rows:
            legacy = copy.deepcopy(row)
            legacy["pass_criterion"] = "informational"
            self.assertTrue(guard_failures(legacy), "old informational criteria must fail")
        legacy = copy.deepcopy(rows[1])
        legacy.update(pass_status="fail", pass_criterion="< 0.05")
        self.assertTrue(guard_failures(legacy), "old enum typo must fail")
        legacy.update(pass_status="fail_criterion")
        self.assertTrue(guard_failures(legacy), "renaming fail alone must still fail")

    def test_aimless_states_and_absent_ctruncate_fields_do_not_fabricate_metrics(self) -> None:
        for state, log in [("ran", str(AIMLESS_LOG)), ("failed", str(AIMLESS_LOG)), ("missing", None)]:
            rows = rows_for({}, {"status": state, "reason": "fixture status", "log": log})
            self.assertEqual(len(rows), 1)
            self.assert_admissible(rows)
            self.assertEqual(rows[0]["oracle_measure"], {"value_text": state})
            self.assertEqual(rows[0].get("evidence_refs", []),
                             [AIMLESS_LOG.relative_to(REPO).as_posix()] if log else [])

    def test_nonfinite_numeric_and_undeclared_dataset_are_rejected(self) -> None:
        for value in [float("nan"), float("inf"), float("-inf"), True]:
            with self.assertRaisesRegex(ValueError, "finite numeric"):
                rows_for({**self.stats, "wilson_b": value})
        with self.assertRaisesRegex(ValueError, "subject and column"):
            t13.render_yaml({}, EVAL_ID, {}, subject_ref="", scope_selector=SELECTOR)

    def test_ri_boundary_rejects_the_previous_absolute_reference(self) -> None:
        violations, retained = integrity._check_evidence_path(
            str(LOG_PATH), Path(EVAL_ID + ".yaml"), "evidence_refs",
        )
        self.assertFalse(retained)
        self.assertTrue(any("absolute, non-portable" in message for message in violations))


class MissingEvidenceTests(unittest.TestCase):
    TWIN_HEADER = "Twin fraction estimates by twinning operator\n"
    ICE_HEADER = (
        "ICE RING SUMMARY:\n"
        " reso ice_ring mean_I mean_Sigma Estimated_I Ratio Zscore Completeness Ave_Completeness\n"
    )
    ICE_NO = "3.44 no 100.0 10.0 100.0 1.0 0.0 1.0 1.0\n"
    ICE_YES = "3.44 yes 100.0 10.0 50.0 2.0 5.0 1.0 1.0\n"
    END = "WILSON SCALING:\n"

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        patcher = mock.patch.object(t13, "REPO_ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def parse(self, text: str) -> dict:
        log = self.root / "fixture.log"
        log.write_text(text)
        return t13.parse_ctruncate(text, str(log))

    def test_operator_missing_truncated_unknown_and_conflicting_sections(self) -> None:
        for text in [
            "", self.TWIN_HEADER, self.TWIN_HEADER + "new unknown layout\n",
            self.TWIN_HEADER + "h,-k,-l\n",
            self.TWIN_HEADER + "h,-k,-l not numeric\n",
            self.TWIN_HEADER + "No operators found\nh,-k,-l not numeric\n",
            self.TWIN_HEADER + "h,-k,-l 0.02 0.03\nNo operators found\n",
            self.TWIN_HEADER + "No operators found\n" + self.TWIN_HEADER,
            self.TWIN_HEADER + "No operators found\n" + self.TWIN_HEADER + "h,-k,-l 0.02 0.03\n",
        ]:
            with self.subTest(text=text):
                parsed = self.parse(text)
                self.assertIsNone(parsed["twin_operators_found"])
                row = rows_for({**parsed, "twin_fraction_l": 0.1})[0]
                self.assertIn("twinning-operator presence: unavailable", row["notes"])
        for report, expected in [("No operators found\n", 0), ("h,-k,-l 0.02 0.03\n", 1)]:
            for repetitions in [1, 2]:
                self.assertEqual(self.parse((self.TWIN_HEADER + report) * repetitions)["twin_operators_found"],
                                 expected)

    def test_ice_missing_header_only_truncated_malformed_and_conflicting(self) -> None:
        for text in [
            "", "ICE RING SUMMARY:\n", self.ICE_HEADER + self.END,
            self.ICE_HEADER + self.ICE_NO,
            self.ICE_HEADER + "3.44 no\n" + self.END,
            self.ICE_HEADER + self.ICE_NO + "3.90 unknown 1 1 1 1 1 1 1\n" + self.END,
            self.ICE_HEADER + self.ICE_NO.replace("100.0", "nan") + self.END,
            self.ICE_HEADER + self.ICE_NO * 2 + self.END,
            self.ICE_HEADER + self.ICE_NO + self.END + self.ICE_HEADER,
            self.ICE_HEADER + self.ICE_NO + self.END + self.ICE_HEADER + self.ICE_YES + self.END,
        ]:
            with self.subTest(text=text):
                parsed = self.parse(text)
                self.assertNotIn("ice_ring_resolutions_flagged", parsed)
                rows = rows_for(parsed)
                row = next(r for r in rows if r["metric_definition_ref"] == "T13_ice-ring_flags")
                self.assertEqual(row["oracle_measure"], {"value_text": "unavailable"})
                self.assertEqual(guard_failures(row), [])
        for report, expected in [(self.ICE_NO, []), (self.ICE_YES, [3.44])]:
            for repetitions in [1, 2]:
                parsed = self.parse((self.ICE_HEADER + report + self.END) * repetitions)
                self.assertEqual(parsed["ice_ring_resolutions_flagged"], expected)
                self.assertEqual(parsed["ice_ring_count_total"], 1)

    def test_tncs_absence_unknown_negations_and_conflicting_repeats(self) -> None:
        header = "TRANSLATIONAL NCS:\n"
        positive = "Translational NCS detected\n"
        negative = "No translational NCS detected\n"
        for text in ["", "When translational NCS is detected, inspect the map.\n",
                     "Translational NCS may not be detected\n", "Translational NCS detected: no\n",
                     positive + negative,
                     header + negative + header, header + negative + header + positive]:
            with self.subTest(text=text):
                parsed = self.parse(text)
                self.assertIsNone(parsed["tncs_flag"])
                row = next(r for r in rows_for(parsed) if r["metric_definition_ref"] == "T13_tncs_flag")
                self.assertEqual(row["oracle_measure"], {"value_text": "unavailable"})
        for report, expected in [(positive, True), (negative, False),
                                 ("Translational NCS was not detected\n", False)]:
            self.assertEqual(self.parse((header + report) * 2)["tncs_flag"], expected)

    def test_anisotropy_absence_and_conflict_never_mean_none_flagged(self) -> None:
        header = "ANISOTROPY ANALYSIS:\n"
        positive = "Some anisotropy detetect.\n"
        negative = "No anisotropy detected.\n"
        for text in ["", "Some anisotropy might be detected.\n", positive + negative,
                     header + negative + header, header + negative + header + positive]:
            with self.subTest(text=text):
                parsed = self.parse(text)
                self.assertEqual(parsed["aniso_flag"], "unavailable")
        for report, expected in [(positive, "some"), (negative, "none_flagged")]:
            self.assertEqual(self.parse((header + report) * 2)["aniso_flag"], expected)


class ExecutionAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo_patch = mock.patch.object(t13, "REPO_ROOT", self.root)
        self.repo_patch.start()
        self.addCleanup(self.repo_patch.stop)
        self.environment = {"PATH": "/configured/ccp4/bin"}
        self.env_patch = mock.patch.object(t13, "ccp4_environment", return_value=self.environment)
        self.which_patch = mock.patch.object(
            t13.shutil, "which", side_effect=lambda tool, *, path: str(Path(path) / tool),
        )
        self.env = self.env_patch.start()
        self.which = self.which_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.addCleanup(self.which_patch.stop)

    def test_shared_runner_uses_configured_ccp4_environment_and_literal_paths(self) -> None:
        mtz = self.root / "input ; $(literal).mtz"
        result = SimpleNamespace(returncode=0, stdout=LOG_PATH.read_text(), stderr="diagnostic")
        with mock.patch.object(t13, "run_capture", return_value=result) as run:
            stats = t13.run_ctruncate(mtz, "F-obs,SIGF-obs", self.root)
        self.which.assert_called_once_with("ctruncate", path=self.environment["PATH"])
        call = run.call_args
        self.assertEqual(call.args[0][0], "/configured/ccp4/bin/ctruncate")
        self.assertEqual(call.args[0][2], str(mtz.resolve()))
        self.assertEqual(call.kwargs["env"], self.environment)
        self.assertEqual(call.kwargs["cwd"], str(self.root.resolve()))
        self.assertEqual(Path(stats["log"]).read_text(), result.stdout + result.stderr)

    def test_aimless_success_merged_failure_other_failure_and_missing(self) -> None:
        for index, (code, stdout, expected) in enumerate([
            (0, "completed", "ran"),
            (1, "hkl_unmerge_list::prepare - EMPTY", "failed"),
            (2, "bad columns", "failed"),
        ]):
            logdir = self.root / str(index)
            logdir.mkdir()
            with mock.patch.object(t13, "run_capture", return_value=SimpleNamespace(
                returncode=code, stdout=stdout, stderr="",
            )) as run:
                result = t13.try_aimless(self.root / "input.mtz", logdir)
            self.assertEqual(result["status"], expected)
            self.assertEqual(Path(result["log"]).read_text(), stdout)
            self.assertEqual(run.call_args.kwargs["input_text"], "END\n")
            self.assertEqual(run.call_args.kwargs["env"], self.environment)
            self.assertEqual(run.call_args.kwargs["cwd"], str(logdir.resolve()))
            if "EMPTY" in stdout:
                self.assertIn("requires unmerged intensities", result["reason"])
        with mock.patch.object(t13.shutil, "which", return_value=None), \
                mock.patch.object(t13, "run_capture") as run:
            self.assertEqual(t13.try_aimless(self.root / "in.mtz", self.root)["status"], "missing")
            run.assert_not_called()

    def test_ctruncate_failures_do_not_emit_stats(self) -> None:
        with mock.patch.object(t13, "run_capture", return_value=SimpleNamespace(
            returncode=4, stdout="bad input", stderr="failure",
        )), self.assertRaisesRegex(SystemExit, "ctruncate failed"):
            t13.run_ctruncate(self.root / "in.mtz", "F,SIGF", self.root)
        self.assertEqual((self.root / "ctruncate.log").read_text(), "bad inputfailure")
        with mock.patch.object(t13.shutil, "which", return_value=None), \
                mock.patch.object(t13, "run_capture") as run, \
                self.assertRaisesRegex(SystemExit, "absent from configured"):
            t13.run_ctruncate(self.root / "in.mtz", "F,SIGF", self.root)
        run.assert_not_called()
        with mock.patch.object(t13, "ccp4_environment", side_effect=FileNotFoundError("no setup")), \
                mock.patch.object(t13, "run_capture") as run:
            self.assertEqual(t13.try_aimless(self.root / "in.mtz", self.root)["status"], "missing")
            with self.assertRaisesRegex(SystemExit, "CCP4 setup unavailable"):
                t13.run_ctruncate(self.root / "in.mtz", "F,SIGF", self.root)
        run.assert_not_called()

    def test_existing_evidence_and_outputs_are_never_overwritten(self) -> None:
        for name in ["ctruncate.log", "ctruncate_out.mtz", "aimless.log", "aimless_scaled.mtz"]:
            with self.subTest(name=name):
                logdir = self.root / name.replace(".", "_")
                logdir.mkdir()
                retained = logdir / name
                retained.write_text("retained")
                with mock.patch.object(t13, "run_capture") as run, self.assertRaises(FileExistsError):
                    if name.startswith("aimless"):
                        t13.try_aimless(self.root / "in.mtz", logdir)
                    else:
                        t13.run_ctruncate(self.root / "in.mtz", "F,SIGF", logdir)
                run.assert_not_called()
                self.assertEqual(retained.read_text(), "retained")

    def test_cli_binds_input_bytes_and_columns_and_requires_new_logdir(self) -> None:
        mtz = self.root / "input.mtz"
        mtz.write_bytes(b"synthetic test bytes; no real oracle")
        expected = "mtz:sha256:" + hashlib.sha256(mtz.read_bytes()).hexdigest()
        logdir = self.root / "logs"
        argv = ["t13_data_quality.py", str(mtz), "--eval-id", EVAL_ID,
                "--columns", "F,SIGF", "--logdir", str(logdir)]
        output = io.StringIO()
        with mock.patch.object(sys, "argv", argv), \
                mock.patch.object(t13, "try_aimless", return_value={
                    "status": "missing", "reason": "test", "log": None,
                }) as aimless, \
                mock.patch.object(t13, "run_capture", return_value=SimpleNamespace(
                    returncode=0, stdout=LOG_PATH.read_text(), stderr="",
                )), \
                redirect_stdout(output), redirect_stderr(io.StringIO()):
            self.assertEqual(t13.main(), 0)
            rows = yaml.safe_load(output.getvalue())
            self.assertTrue(all(r["subject_ref"] == expected for r in rows))
            self.assertEqual(rows[0]["scope_selector"], "/*/*/[F,SIGF]")
            self.assertEqual(rows[-1]["scope_selector"], "all input reflections")
            with mock.patch.object(integrity, "REPO", self.root):
                for row in rows:
                    for ref in row.get("evidence_refs", []):
                        self.assertEqual(integrity._check_evidence_path(
                            ref, Path(EVAL_ID + ".yaml"), "evidence_refs", reject_self=True,
                        ), ([], True))
                        self.assertEqual(ref, "logs/ctruncate.log")
            with self.assertRaisesRegex(SystemExit, "use a new --logdir"):
                t13.main()
            self.assertEqual(aimless.call_count, 1)

    def test_cli_rejects_input_changed_by_an_oracle(self) -> None:
        mtz = self.root / "input.mtz"
        mtz.write_bytes(b"before")

        def mutate_input(*_args: object) -> dict:
            mtz.write_bytes(b"after")
            return {"log": "test.log", "wilson_b": 1.0}

        output = io.StringIO()
        with mock.patch.object(sys, "argv", [
            "t13_data_quality.py", str(mtz), "--eval-id", EVAL_ID,
        ]), mock.patch.object(t13, "try_aimless", return_value={
            "status": "missing", "reason": "test", "log": None,
        }), mock.patch.object(t13, "run_ctruncate", side_effect=mutate_input), \
                redirect_stdout(output), redirect_stderr(io.StringIO()), \
                self.assertRaisesRegex(SystemExit, "MTZ changed"):
            t13.main()
        self.assertEqual(output.getvalue(), "")

    def test_external_and_symlink_escape_logdirs_fail_before_execution(self) -> None:
        mtz = self.root / "input.mtz"
        mtz.write_bytes(b"input fixture")
        with tempfile.TemporaryDirectory() as external:
            external_root = Path(external)
            link = self.root / "escape"
            link.symlink_to(external_root, target_is_directory=True)
            for logdir in [external_root / "logs", link / "logs"]:
                with self.subTest(logdir=logdir), \
                        mock.patch.object(sys, "argv", [
                            "t13_data_quality.py", str(mtz), "--eval-id", EVAL_ID,
                            "--logdir", str(logdir),
                        ]), mock.patch.object(t13, "try_aimless") as aimless, \
                        mock.patch.object(t13, "run_ctruncate") as ctruncate, \
                        self.assertRaisesRegex(SystemExit, "inside the repository"):
                    t13.main()
                aimless.assert_not_called()
                ctruncate.assert_not_called()
                self.assertFalse((external_root / "logs").exists())
            with mock.patch.object(t13, "run_capture") as run:
                with self.assertRaisesRegex(ValueError, "inside the repository"):
                    t13.try_aimless(mtz, external_root)
                with self.assertRaisesRegex(ValueError, "inside the repository"):
                    t13.run_ctruncate(mtz, "F,SIGF", external_root)
                run.assert_not_called()

    def test_missing_or_escaped_retained_evidence_prevents_emission(self) -> None:
        for log in [None, "missing.log", str(self.root / "missing.log"), str(self.root)]:
            with self.subTest(log=log), self.assertRaisesRegex(ValueError, "retained"):
                rows_for({"wilson_b": 1.0, "log": log})
        for state in ["ran", "failed"]:
            with self.assertRaisesRegex(ValueError, "retained log"):
                rows_for({}, {"status": state, "reason": "fixture", "log": None})
        with tempfile.TemporaryDirectory() as external:
            external_log = Path(external) / "outside.log"
            external_log.write_text("external evidence")
            link = self.root / "escaped.log"
            link.symlink_to(external_log)
            for log in [str(link), "escaped.log", str(external_log)]:
                with self.subTest(log=log), self.assertRaisesRegex(ValueError, "inside the repository"):
                    rows_for({"wilson_b": 1.0, "log": log})


if __name__ == "__main__":
    unittest.main()
