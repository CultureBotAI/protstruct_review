#!/usr/bin/env python3
"""Hermetic mmCIF perturbation-cache tests using synthetic Gemmi fixtures (#822)."""
from __future__ import annotations

import hashlib
import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import gemmi

import bench_dfsc_determinacy as bench
from refinement_cache import CacheEvidenceError


PDB = """HEADER    TEST
ATOM      1  CA  ALA A   1       1.000   2.000   3.000  1.00 10.00           C
ATOM      2  CA  ALA A   2       2.000   3.000   4.000  1.00 10.00           C
ATOM      3  CA  ALA A   3       3.000   4.000   5.000  1.00 10.00           C
END
"""


def positions(path):
    structure = gemmi.read_structure(str(path))
    return [(atom.pos.x, atom.pos.y, atom.pos.z)
            for model in structure for chain in model for residue in chain for atom in residue]


class CifPerturbationCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cif-perturb-cache-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.model = self.root / "entry.cif"
        structure = gemmi.read_pdb_string(PDB)
        structure.setup_entities()
        structure.make_mmcif_document().write_file(str(self.model))
        self.original = self.model.read_bytes()
        self.out = self.root / "work" / "entry_p0.2_7.cif"
        self.out.parent.mkdir()

    def generate(self, sigma=0.2, seed=7, out=None):
        return bench.perturb_cif(self.model, sigma, seed, out or self.out)

    def evidence(self, path):
        return json.loads((path.parent / "evidence.json").read_text())

    def test_identical_call_reuses_complete_verified_product_without_rewrite(self):
        first = self.generate()
        before = first.read_bytes()
        mtime = first.stat().st_mtime_ns
        self.assertEqual(first, self.generate())
        self.assertEqual(first.stat().st_mtime_ns, mtime)
        self.assertEqual(first.read_bytes(), before)
        evidence = self.evidence(first)
        self.assertEqual(evidence["source"]["sha256"], hashlib.sha256(self.original).hexdigest())
        self.assertEqual(evidence["output"]["sha256"], hashlib.sha256(before).hexdigest())
        self.assertEqual(evidence["random_seed"], "entry:0.2:7")
        self.assertEqual(evidence["generator"]["gemmi_version"], gemmi.__version__)
        self.assertEqual(evidence["generator"]["gemmi_module"], str(Path(gemmi.__file__).resolve()))

    def test_same_output_after_source_mutation_cannot_reuse_old_coordinates(self):
        first = self.generate()
        before = first.read_bytes()
        changed = gemmi.read_structure(str(self.model))
        changed[0][0][0][0].pos.x += 91
        changed.make_mmcif_document().write_file(str(self.model))
        second = self.generate()
        self.assertNotEqual(first, second)
        self.assertNotEqual(positions(first), positions(second))
        self.assertEqual(first.read_bytes(), before)

    def test_same_requested_output_after_seed_change_cannot_reuse_old_coordinates(self):
        first = self.generate(seed=7)
        before = first.read_bytes()
        second = self.generate(seed=11)
        self.assertNotEqual(first, second)
        self.assertNotEqual(positions(first), positions(second))
        self.assertEqual(first.read_bytes(), before)
        self.assertEqual(self.evidence(second)["seed"], 11)

    def test_parameter_spelling_that_controls_rng_is_preserved(self):
        as_int = self.generate(sigma=1)
        as_float = self.generate(sigma=1.0)
        self.assertNotEqual(positions(as_int), positions(as_float))
        self.assertEqual(self.evidence(as_int)["random_seed"], "entry:1:7")
        self.assertEqual(self.evidence(as_float)["random_seed"], "entry:1.0:7")

    def test_gemmi_runtime_version_changes_produce_separate_evidence(self):
        first = self.generate()
        with patch.object(bench.gemmi, "__version__", gemmi.__version__ + "-test"):
            second = self.generate()
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_bytes(), second.read_bytes())
        self.assertNotEqual(self.evidence(first)["generator"]["gemmi_version"],
                            self.evidence(second)["generator"]["gemmi_version"])

    def test_requested_basename_is_not_scientific_identity(self):
        self.assertEqual(self.generate(), self.generate(out=self.out.with_name("alias.cif")))

    def test_legacy_requested_output_is_preserved_not_adopted(self):
        self.out.write_text("old unproven mmCIF")
        first = self.generate()
        self.assertNotEqual(first, self.out)
        self.assertEqual(self.out.read_text(), "old unproven mmCIF")
        self.assertEqual(len(positions(first)), 3)

    def test_corrupted_product_or_metadata_refused_without_repair(self):
        for product in ("model.cif", "evidence.json"):
            with self.subTest(product=product):
                output = self.generate(seed=7 if product == "model.cif" else 11)
                victim = output.parent / product
                victim.write_text("corrupted")
                with self.assertRaises(CacheEvidenceError):
                    self.generate(seed=7 if product == "model.cif" else 11)
                self.assertEqual(victim.read_text(), "corrupted")

    def test_input_change_during_gemmi_read_fails_before_publication(self):
        original_reader = bench.gemmi.read_structure
        def changing_reader(path):
            result = original_reader(path)
            self.model.write_bytes(self.original + b"\n# changed during read\n")
            return result
        with patch.object(bench.gemmi, "read_structure", side_effect=changing_reader):
            with self.assertRaises(CacheEvidenceError):
                self.generate()
        self.assertFalse(list(self.out.parent.rglob("evidence.json")))

    def test_coordinates_follow_original_model_stem_gaussian_algorithm(self):
        result = positions(self.generate())
        rng = random.Random("entry:0.2:7")
        for actual, original in zip(result, positions(self.model), strict=True):
            for value, coordinate in zip(actual, original, strict=True):
                self.assertAlmostEqual(value, coordinate + rng.gauss(0, 0.2), places=5)


if __name__ == "__main__":
    unittest.main()
