#!/usr/bin/env python3
"""Hermetic EM cache integration tests; no PHENIX or gemmi execution."""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import bench_refinement_deltas_em as em
from refinement_cache import CacheEvidenceError
import toolchain


class EmCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.model = self.root / "entry.cif"
        self.map = self.root / "entry.map"
        self.launcher = self.root / "mock-launcher"
        for path in (self.model, self.map, self.launcher):
            path.write_text(path.name)
        self.work = self.root / "work"
        self.build = {"reported_version_source": "command_output",
                      "reported_version": "PHENIX 2.0-5936"}
        self.calls = []
        self.fail = set()
        self.missing_curve = False
        self.ambiguous_model = False
        for patcher in (
            patch.object(toolchain, "phenix", return_value=self.launcher),
            patch.object(toolchain, "phenix_build_evidence", side_effect=lambda: self.build),
            patch.object(toolchain, "run_logged", side_effect=self.execute),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def execute(self, argv, log_path, *, cwd, timeout):
        self.calls.append((argv, cwd, timeout))
        name = cwd.parent.name
        log_path.write_text("CC_mask : 0.82\nFSC(map, model map)=0.143 : 3.0 3.1\n")
        if name == "em-mtriage" and not self.missing_curve:
            (cwd / em.FSC_CURVE).write_text("0.1 0.8\n" + "0.3333333333333333 0.1\n" * 20)
        if name == "em-real-space-refine":
            (cwd / "refined_real_space_refined_000.cif").write_text("refined model")
            if self.ambiguous_model:
                (cwd / "refined_real_space_refined_001.cif").write_text("another model")
        return subprocess.CompletedProcess(argv, 1 if name in self.fail else 0)

    def measure(self, resolution=3.2, tag="entry_pre"):
        return em.measure(self.model, self.map, resolution, self.work, tag)

    def test_identical_measurement_reuses_both_operations_across_tags(self):
        first = self.measure()
        second = self.measure(tag="screen_entry")
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(first, second)
        self.assertEqual(first["cc_mask"], 0.82)
        self.assertEqual(first["d_fsc_model_masked"], 3.0)
        for key in ("cc_log", "curve_path", "fsc_log", "cc_evidence", "fsc_evidence"):
            self.assertTrue(first[key].is_file())

    def test_input_and_build_and_exact_resolution_changes_rerun(self):
        previous = self.measure(3.2000001)
        for change in (lambda: self.model.write_text("changed model"),
                       lambda: self.map.write_text("changed map"),
                       lambda: self.build.update(reported_version="PHENIX 2.1-6000")):
            change()
            result = self.measure(3.2000001)
            self.assertNotEqual(previous["curve_path"], result["curve_path"])
            previous = result
        result = self.measure(3.2000002)
        self.assertNotEqual(previous["curve_path"], result["curve_path"])
        self.assertEqual(len(self.calls), 10)

    def test_unknown_build_does_not_reuse(self):
        self.build = {"configured_path_version_hint": "2.0-5936"}
        first, second = self.measure(), self.measure()
        self.assertNotEqual(first["cc_log"], second["cc_log"])
        self.assertEqual(len(self.calls), 4)

    def test_nonzero_numeric_logs_are_not_measurements(self):
        self.fail = {"em-map-correlations", "em-mtriage"}
        result = self.measure()
        self.assertIsNone(result["cc_mask"])
        self.assertIsNone(result["d_fsc_model_masked"])
        self.assertIsNone(result["curve_path"])
        self.assertIsNone(result["cc_evidence"])
        self.assertTrue(result["cc_log"].is_file())
        self.assertTrue(result["fsc_log"].is_file())
        self.measure()
        self.assertEqual(len(self.calls), 4)

    def test_missing_fsc_product_is_unavailable_not_legacy_curve(self):
        self.missing_curve = True
        legacy = self.work / "mt_entry_pre_3.2A" / em.FSC_CURVE
        legacy.parent.mkdir(parents=True)
        legacy.write_text("legacy curve\n")
        result = self.measure()
        self.assertIsNone(result["d_fsc_model_masked"])
        self.assertIsNone(result["curve_path"])
        self.assertEqual(legacy.read_text(), "legacy curve\n")

    def test_corrupt_curve_stops_without_overwriting(self):
        result = self.measure()
        result["curve_path"].write_text("tampered")
        with self.assertRaises(CacheEvidenceError):
            self.measure()
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(result["curve_path"].read_text(), "tampered")

    def test_real_space_refinement_reuses_only_matching_evidence(self):
        first, reason = em.refine(self.model, self.map, 3.2, self.work, "entry")
        self.assertIsNone(reason)
        second, _ = em.refine(self.model, self.map, 3.2, self.work, "alias")
        self.assertEqual(first, second)
        self.assertEqual(len(self.calls), 1)
        self.build["reported_version"] = "PHENIX 2.1-6000"
        third, _ = em.refine(self.model, self.map, 3.2, self.work, "entry")
        self.assertNotEqual(first, third)
        manifest = json.loads((third.parent / "success.json").read_text())
        self.assertEqual(manifest["invocation"]["measured_build"], self.build)

    def test_multiple_refinement_models_not_arbitrarily_selected(self):
        self.ambiguous_model = True
        model, reason = em.refine(self.model, self.map, 3.2, self.work, "entry")
        self.assertIsNone(model)
        self.assertIsNotNone(reason)
        self.assertFalse(list(self.work.rglob("success.json")))

    def test_determinacy_reads_returned_curve_not_reconstructed_filename(self):
        # This path tests the downstream consumer without importing/executing gemmi.
        with patch.dict(sys.modules, {"gemmi": types.ModuleType("gemmi")}):
            determinacy = importlib.import_module("bench_dfsc_determinacy")
        dep = self.measure()
        with (patch.object(determinacy.EM, "measure", return_value=dep),
              patch.object(determinacy, "SIGMAS", ()),
              patch.object(determinacy, "d_width", return_value=1.25) as width):
            row = determinacy.measure_entry("entry", 3.2, self.root, self.work)
        self.assertEqual(row["d_width"], 1.25)
        self.assertEqual(len(width.call_args.args[0]), 21)


if __name__ == "__main__":
    unittest.main()
