#!/usr/bin/env python3
"""Hermetic source/seed/generator-bound perturbation cache regressions (#812)."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bench_refinement_deltas as bench
from refinement_cache import CacheEvidenceError


def atom(serial, record="ATOM  "):
    return (f"{record}{serial:5d}  CA  ALA A{serial:4d}    "
            f"{float(serial):8.3f}{float(serial + 1):8.3f}{float(serial + 2):8.3f}"
            "  1.00 10.00           C")


class PerturbationCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="perturb-cache-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.model = self.root / "entry.pdb"
        self.original = ("HEADER    test\n" + "\n".join(atom(i) for i in range(1, 5))
                         + "\n" + atom(5, "HETATM") + "\nEND\n").encode()
        self.model.write_bytes(self.original)
        self.work = self.root / "work"
        self.work.mkdir()

    def generate(self, sigma=0.25, seed=7):
        return bench.perturb(self.model, sigma, self.work, seed)

    def evidence(self, path):
        return json.loads((path.parent / "evidence.json").read_text())

    def test_identical_input_reuses_verified_bytes_without_rewriting(self):
        first = self.generate()
        before = first.stat().st_mtime_ns
        original = first.read_bytes()
        self.assertEqual(first, self.generate())
        self.assertEqual(first.read_bytes(), original)
        self.assertEqual(first.stat().st_mtime_ns, before)
        evidence = self.evidence(first)
        self.assertEqual(evidence["source"]["sha256"], hashlib.sha256(self.original).hexdigest())
        self.assertEqual(evidence["output"]["sha256"], hashlib.sha256(original).hexdigest())
        self.assertEqual(evidence["sigma_hex"], (0.25).hex())
        self.assertEqual(evidence["seed"], 7)

    def test_seed_change_cannot_reuse_previous_coordinates(self):
        first = self.generate(seed=7)
        before = first.read_bytes()
        second = self.generate(seed=8)
        self.assertNotEqual(first, second)
        self.assertNotEqual(before, second.read_bytes())
        self.assertEqual(first.read_bytes(), before)
        self.assertEqual(self.evidence(second)["seed"], 8)

    def test_source_change_cannot_reuse_previous_coordinates(self):
        first = self.generate()
        before = first.read_bytes()
        self.model.write_bytes(self.original.replace(b"   1.000", b"  91.000", 1))
        second = self.generate()
        self.assertNotEqual(first, second)
        self.assertNotEqual(before, second.read_bytes())
        self.assertEqual(first.read_bytes(), before)
        self.assertEqual(self.evidence(second)["source"]["sha256"],
                         hashlib.sha256(self.model.read_bytes()).hexdigest())

    def test_same_stem_different_models_do_not_collide(self):
        first = self.generate()
        other = self.root / "different-source" / "entry.pdb"
        other.parent.mkdir()
        other.write_bytes(self.original.replace(b"   1.000", b"  91.000", 1))
        second = bench.perturb(other, 0.25, self.work)
        self.assertNotEqual(first, second)
        self.assertNotEqual(first.read_bytes(), second.read_bytes())

    def test_exact_sigma_and_seed_remain_bound_when_rounding_masks_difference(self):
        first = self.generate(sigma=0.25)
        close = self.generate(sigma=0.25000000000000006)
        self.assertEqual(first.read_bytes(), close.read_bytes())
        self.assertNotEqual(first, close)
        seed1 = self.generate(sigma=0.0, seed=7)
        seed2 = self.generate(sigma=0.0, seed=8)
        self.assertEqual(seed1.read_bytes(), seed2.read_bytes())
        self.assertNotEqual(seed1, seed2)

    def test_producer_identity_changes_without_overwriting_previous_bundle(self):
        producer = self.root / "producer.py"
        producer.write_text("generator version one")
        with patch.object(bench, "__file__", str(producer)):
            first = self.generate()
            producer.write_text("generator version two")
            second = self.generate()
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertNotEqual(self.evidence(first)["generator"]["producer_sha256"],
                            self.evidence(second)["generator"]["producer_sha256"])

    def test_actual_generator_output_is_also_part_of_identity(self):
        first = self.generate()
        with patch.object(bench, "_perturb_coordinates", return_value=b"HEADER changed generator\n"):
            second = self.generate()
        self.assertNotEqual(first, second)
        self.assertEqual(second.read_bytes(), b"HEADER changed generator\n")

    def test_legacy_products_are_preserved_not_adopted(self):
        legacy = self.work / "entry_perturb0.25.pdb"
        legacy.write_text("legacy wrong coordinates")
        new = self.generate()
        self.assertNotEqual(new, legacy)
        self.assertEqual(legacy.read_text(), "legacy wrong coordinates")

    def test_corrupt_output_is_refused_without_repair(self):
        first = self.generate()
        first.write_text("corrupted coordinates")
        with self.assertRaises(CacheEvidenceError):
            self.generate()
        self.assertEqual(first.read_text(), "corrupted coordinates")

    def test_missing_and_mutated_evidence_are_refused_without_repair(self):
        first = self.generate()
        manifest = first.parent / "evidence.json"
        manifest.write_text("{}")
        with self.assertRaises(CacheEvidenceError):
            self.generate()
        self.assertEqual(manifest.read_text(), "{}")
        manifest.unlink()
        with self.assertRaises(CacheEvidenceError):
            self.generate()
        self.assertFalse(manifest.exists())

    def test_symlinked_output_or_evidence_cannot_authenticate_cache(self):
        for label in ("model.pdb", "evidence.json"):
            with self.subTest(label=label):
                output = self.generate(seed=7 if label == "model.pdb" else 8)
                victim = output.parent / label
                saved = self.root / ("saved-" + label)
                victim.rename(saved)
                victim.symlink_to(saved)
                with self.assertRaises(CacheEvidenceError):
                    self.generate(seed=7 if label == "model.pdb" else 8)

    def test_zero_sigma_preserves_original_coordinates_and_noncoordinate_lines(self):
        self.assertEqual(self.generate(sigma=0).read_bytes(), self.original)

    def test_legacy_algorithm_coordinate_bytes_are_preserved(self):
        # Literal baseline output from the pre-#812 implementation, seed 7/sigma .25.
        expected_xyz = [
            "   0.936   2.128   2.943",
            "   1.921   2.767   3.947",
            "   3.278   4.106   5.259",
            "   4.062   5.099   6.046",
            "   4.583   6.214   7.127",
        ]
        lines = self.generate().read_text().splitlines()
        self.assertEqual([line[30:54] for line in lines
                          if line.startswith(("ATOM", "HETATM"))], expected_xyz)
        self.assertEqual(lines[0], "HEADER    test")
        self.assertEqual(lines[-1], "END")


if __name__ == "__main__":
    unittest.main()
