"""Hermetic #777 checks of the configured version probe and real X-ray callers."""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import bench_refinement_deltas as xray
import toolchain
from refinement_cache import CacheEvidenceError, OperationFailed, cached_phenix_operation, sha256


class PhenixCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="phenix-cache-fixture-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "configured phenix"
        self.bin.mkdir()
        for name in ("phenix.version", "phenix.refine", "phenix.clashscore"):
            (self.bin / name).write_text(f"fake {name} executable bytes\n")
        self.model = self.root / "model [literal] {operation_dir}.pdb"
        self.mtz = self.root / "data.mtz"
        self.model.write_text("model bytes\n")
        self.mtz.write_text("reflection bytes\n")
        self.work = self.root / "work"
        self.work.mkdir()
        self.version_text = "PHENIX version: 2.0-5936\n"
        self.version_code = 0
        self.version_calls = []
        self.calls = []
        self.code = 0
        self.write_model = True
        self.log = "r_work=0.1000 r_free=0.2000\nr_work=0.0900 r_free=0.1900\nclashscore = 3.14\n"
        for patcher in (
            mock.patch.object(toolchain, "PHENIX_BIN", self.bin),
            mock.patch.object(toolchain, "run_capture", side_effect=self.version),
            mock.patch.object(xray, "run_logged", side_effect=self.runner),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def version(self, argv, **kwargs):
        self.version_calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, self.version_code, self.version_text, "version stderr\n")

    def runner(self, argv, log, **kwargs):
        self.calls.append((argv, log, kwargs))
        log.write_text(self.log)
        if Path(argv[0]).name == "phenix.refine" and self.write_model:
            prefix = next(value.split("=", 1)[1] for value in argv if value.startswith("output.prefix="))
            (kwargs["cwd"] / f"{prefix}_001.pdb").write_text("refined model\n")
        return subprocess.CompletedProcess(argv, self.code)

    def refine(self, **kwargs):
        return xray.refine(self.model, self.mtz, self.work, **kwargs)

    def test_probe_is_same_configured_tree_with_complete_evidence(self):
        with mock.patch.object(toolchain, "_discover_executable", side_effect=AssertionError("no fallback")):
            result = toolchain.phenix_build_evidence()
        self.assertEqual(self.version_calls[0][0], [(self.bin / "phenix.version").resolve()])
        probe = result["version_probe"]
        self.assertEqual(probe["configured_path"], str(self.bin / "phenix.version"))
        self.assertEqual(probe["stdout"], self.version_text)
        self.assertEqual(probe["stderr"], "version stderr\n")
        self.assertEqual(probe["returncode"], 0)
        self.assertEqual(probe["sha256"], sha256(self.bin / "phenix.version"))

    def test_missing_version_never_falls_back_to_path(self):
        (self.bin / "phenix.version").unlink()
        with mock.patch.object(toolchain, "_discover_executable", side_effect=AssertionError("no fallback")):
            result = toolchain.phenix_build_evidence()
        self.assertIsNone(result["reported_version"])
        self.assertEqual(self.version_calls, [])

    def test_version_failure_retains_raw_evidence_and_never_reuses(self):
        self.version_code = 1
        first, _ = self.refine()
        second, _ = self.refine()
        self.assertNotEqual(first, second)
        record = json.loads((first.parent / "uncached_success.json").read_text())
        self.assertFalse(record["reusable"])
        self.assertEqual(record["invocation"]["measured_build"]["version_probe"]["stdout"], self.version_text)
        self.assertEqual(len(self.calls), 2)

    def test_unrecognized_version_never_reuses(self):
        self.version_text = "PHENIX unknown build"
        self.assertNotEqual(self.refine()[0], self.refine()[0])
        self.assertEqual(len(self.calls), 2)

    def test_vendor_split_banner_supports_same_build_reuse(self):
        # Source-grounded: phenix_info.version_and_release_tag/show_banner splits
        # PHENIX_VERSION=2.0-5936 into these fields when phenix_env.sh is sourced.
        self.version_text = ("Phenix: Python-based Hierarchical ENvironment for Integrated Xtallography\n"
                             "  Version: 2.0\n  Release tag: 5936\n")
        first = self.refine()[0]
        self.assertEqual(self.refine()[0], first)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(toolchain.parse_phenix_build(self.version_text), "2.0-5936")

    def test_only_explicit_unambiguous_version_fields_can_authorize_reuse(self):
        for banner in (
            "Phenix: unknown\nVersion: unknown\nRelease tag: unknown\nwarning: expected PHENIX 2.0-5936",
            "Phenix: title\nVersion: unknown\ncctbx tag: 2.0-5936",
            "Phenix: title\nVersion: 2.0-5936\nRelease tag: 9999",
            "Phenix: title\nVersion: 2.0\nRelease tag: 5936\nRelease tag: 9999",
            "Phenix: title\nVersion: 2.0\nRelease tag: 5936+SVN",
            "Phenix: title\nVersion: 2.0\nRelease tag: unknown\nPHENIX 2.0-5936",
            "warning: expected PHENIX 2.0-5936",
            "cctbx 2.0-5936",
        ):
            with self.subTest(banner=banner):
                self.assertIsNone(toolchain.parse_phenix_build(banner))
                self.version_text = banner
                self.assertNotEqual(self.refine()[0], self.refine()[0])
        self.assertEqual(toolchain.parse_phenix_build("Phenix: title\nVersion: 2.0-5936"), "2.0-5936")

    def test_refinement_reuses_only_identical_input_build_and_options(self):
        first, stats = self.refine()
        self.assertEqual(stats, {"r_work_pre": 0.1, "r_free_pre": 0.2,
                                 "r_work_post": 0.09, "r_free_post": 0.19})
        self.assertEqual(first, self.refine()[0])
        self.assertEqual(len(self.calls), 1)
        outputs = [first]
        for path in (self.model, self.mtz, self.bin / "phenix.refine", self.bin / "phenix.version"):
            path.write_text(path.read_text() + "changed\n")
            outputs.append(self.refine()[0])
        self.version_text = "PHENIX version: 2.0-9999\n"
        outputs.append(self.refine()[0])
        with mock.patch.object(xray, "MACRO_CYCLES", 8):
            outputs.append(self.refine()[0])
        outputs.append(self.refine(restraints=True)[0])
        with mock.patch.object(xray, "LOW_RES_RESTRAINTS", "ncs_search.enabled=False"):
            outputs.append(self.refine(restraints=True)[0])
        self.assertEqual(len(set(outputs)), 9)
        self.assertEqual(len(self.calls), 9)

    def test_literal_scientific_paths_reach_refiner_unchanged(self):
        self.refine()
        self.assertEqual(self.calls[0][0][1:3], [str(self.model.resolve()), str(self.mtz.resolve())])

    def test_legacy_refined_models_are_ignored_and_preserved(self):
        legacy = self.work / f"{xray.refine_prefix(self.model.stem, False)}_001.pdb"
        legacy.write_text("legacy wrong model")
        result, _ = self.refine()
        self.assertNotEqual(result, legacy)
        self.assertEqual(legacy.read_text(), "legacy wrong model")
        self.assertEqual(len(self.calls), 1)

    def test_refinement_failure_retains_specific_rfree_diagnosis(self):
        self.code = 1
        self.log = "No array of R-free flags found\n"
        result, stats = self.refine()
        self.assertIsNone(result)
        self.assertIn("no usable R-free flags", stats["failure_reason"])
        self.assertFalse(list(self.work.rglob("success.json")))

    def test_missing_model_is_operational_failure_with_real_log(self):
        self.write_model = False
        self.log = "Sorry: Crystal symmetry mismatch\n"
        result, stats = self.refine()
        self.assertIsNone(result)
        self.assertIn("symmetry", stats["failure_reason"])

    def test_corrupt_evidence_is_not_downgraded_to_skip(self):
        result, _ = self.refine()
        (result.parent / "stdout.log").write_text("tampered")
        with self.assertRaises(CacheEvidenceError) as raised:
            self.refine()
        self.assertNotIsInstance(raised.exception, OperationFailed)
        self.assertEqual(len(self.calls), 1)

    def test_nonzero_validator_never_returns_or_caches_plausible_number(self):
        self.code = 1
        for _ in range(2):
            self.assertIsNone(xray.run_tool("phenix.clashscore", self.model, self.work, "pre", xray._CLASHSCORE))
        self.assertEqual(len(self.calls), 2)
        self.assertFalse(list(self.work.rglob("success.json")))

    def test_validator_ignores_old_log_and_reuses_only_verified_new_log(self):
        old = self.work / f"pre_{self.model.stem}.log"
        old.write_text("clashscore = 999.0\n")
        for tag in ("pre", "different-display-tag"):
            self.assertEqual(xray.run_tool("phenix.clashscore", self.model, self.work, tag, xray._CLASHSCORE), 3.14)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(old.read_text(), "clashscore = 999.0\n")
        self.model.write_text("different input bytes\n")
        self.assertEqual(xray.run_tool("phenix.clashscore", self.model, self.work, "pre", re.compile(r"clashscore = ([\d.]+)")), 3.14)
        self.assertEqual(len(self.calls), 2)

    def test_wrapper_failure_exposes_retained_log_path(self):
        self.code = 1
        with self.assertRaises(OperationFailed) as raised:
            cached_phenix_operation(self.work, "validator", executable="phenix.clashscore",
                                    inputs={"model": self.model}, arguments=[self.model],
                                    required_outputs={}, timeout=1, runner=self.runner)
        self.assertEqual(raised.exception.log_path.read_text(), self.log)


if __name__ == "__main__":
    unittest.main()
