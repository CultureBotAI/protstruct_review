#!/usr/bin/env python3
"""Hermetic checks for #786's scoped documentary classification-floor adoption."""
from __future__ import annotations

from decimal import Decimal
import json
import os
from pathlib import Path
import sys
import unittest

import yaml

REPO = Path(__file__).resolve().parent.parent
POLICY_ROOT = Path(os.environ.get("PROTSTRUCT_T05_POLICY_ROOT", REPO))
BASE = Path(os.environ.get("PROTSTRUCT_TEST_BASE_ROOT", REPO))
sys.path.insert(0, str(BASE / "scripts"))
import check_driver_thresholds as guard  # noqa: E402
from bench_vs_deposited import (  # noqa: E402
    local_rotamers, ramachandran_agreement, report_rotamers, rotamer_agreement,
)

REGISTRY = "ref/thresholds_and_standards.md"
SIDECAR = "ref/thresholds_and_standards.yaml"
DRIVER = "ref/driving_example_T05.md"
METRICS = (
    "Ramachandran classification floor, favored row (§3)",
    "Ramachandran/rotamer classification floor, outlier row (§3)",
)
LABELS = ("Ramachandran / rotamer favored %", "Ramachandran / rotamer outlier %")


def read(relative: str, *, policy: bool = False) -> str:
    root = POLICY_ROOT if policy else REPO
    path = root / relative
    return (path if path.exists() else BASE / relative).read_text()


def row(text: str, label: str) -> str:
    found = [line for line in text.splitlines() if line.startswith(f"| {label} |")]
    if len(found) != 1:
        raise ValueError(f"Expected one row: {label}")
    return found[0]


class ClassificationPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = read(REGISTRY, policy=True)
        cls.driver = read(DRIVER, policy=True)
        cls.checks = {c["metric"]: c for c in guard.load_checks(POLICY_ROOT / SIDECAR)}
        cls.rows = json.loads(read("ref/research/data/round46_vs_deposited.json"))["rows"]
        cls.protein = [r for r in cls.rows if r.get("ramachandran_n_shared", 0)
                       and r.get("rotamer_n_shared", 0)]

    def test_01_both_rows_adopt_the_preregistered_floor(self) -> None:
        for metric, label in zip(METRICS, LABELS):
            with self.subTest(row=label):
                self.assertIn(metric, self.checks)
                entry = self.checks[metric]
                self.assertEqual(guard.registry_value(entry["registry"], self.registry), "0.99")
                self.assertIn(DRIVER, entry["consumers"])
                self.assertEqual(entry["section"], 3)
                self.assertEqual(row(self.registry, label).count("**Classification floor:"), 1)
                self.assertIn("classification agreement **≥ 0.99**", read(
                    "ref/research/tolerance_benchmark_round46_preregistration.md"))

    def test_02_missing_or_changed_floor_is_not_silently_accepted(self) -> None:
        for metric, label in zip(METRICS, LABELS):
            entry = self.checks[metric]
            original = row(self.registry, label)
            for replacement in ("agreement ≥ 0.98", "agreement ≥ 1.00", "agreement unspecified"):
                with self.subTest(row=label, replacement=replacement):
                    changed = original.replace("agreement ≥ 0.99", replacement)
                    self.assertNotEqual(changed, original)
                    mutated = self.registry.replace(original, changed)
                    self.assertNotEqual(guard.registry_value(entry["registry"], mutated), entry["current"])

    def test_03_scope_and_denominator_changes_in_either_row_fail(self) -> None:
        mutations = (
            ("PHENIX 2.0-5936", "PHENIX any version"),
            ("versus the wwPDB validation report only", "versus standalone MolProbity"),
            ("same coordinate subject", "different coordinate subjects"),
            ("(chain, resnum, icode, resname)", "(chain, resnum, resname)"),
            ("nonzero shared-key denominator", "whole-model residue count"),
            ("Do not pool models or Ramachandran/rotamer denominators.", ""),
            ("Missing applicability evidence or a zero denominator is unevaluable, not a pass.", ""),
            ("Other versions and standalone MolProbity comparisons are informational, not covered by this floor.", ""),
            ("No QDS agreement metric or PassCriterionBinding is registered by this adoption; retain QDS classification-agreement rows as informational without criterion metadata.", ""),
        )
        for metric, label in zip(METRICS, LABELS):
            original = row(self.registry, label)
            for old, new in mutations:
                with self.subTest(row=label, mutation=old):
                    self.assertIn(old, original)
                    changed = self.registry.replace(original, original.replace(old, new))
                    self.assertIsNone(guard.registry_value(self.checks[metric]["registry"], changed))

    def test_04_classification_not_exact_name_or_pooled_population(self) -> None:
        entry = self.checks[METRICS[1]]
        original = row(self.registry, LABELS[1])
        for old, new in (
            ("binary rotamer OUTLIER/non-OUTLIER verdict", "exact rotamer name"),
            ("separately for the three-state", "pooled for the three-state"),
        ):
            changed = self.registry.replace(original, original.replace(old, new))
            self.assertIsNone(guard.registry_value(entry["registry"], changed))
        favored = row(self.registry, LABELS[0])
        self.assertIn("this does not calibrate rotamer favored %", favored)
        self.assertIn("**Rotamer favored %: ± 1.0 pp retained, not directly measurable**", favored)

    def test_05_driver_cites_scope_without_redefining_numeric_floor(self) -> None:
        normalized = " ".join(self.driver.split())
        for required in (
            "classification floor in the registry §3",
            "only to PHENIX 2.0-5936 versus the wwPDB validation report",
            "(chain, resnum, icode, resname)",
            "three-state Ramachandran agreement and binary rotamer OUTLIER/non-OUTLIER agreement separately",
            "each with its own nonzero shared-key denominator",
            "name every disagreeing residue",
            "standalone MolProbity comparisons remain informational",
            "no QDS agreement metric or PassCriterionBinding",
            "QDS classification-agreement rows as informational without criterion metadata",
        ):
            self.assertIn(required, normalized)
        self.assertNotIn("0.99", self.driver)
        old = "classification agreement**: for the residues both tools evaluate, they assign the same Ramachandran"
        for metric in METRICS:
            self.assertTrue(guard.stale_hits(old, self.checks[metric]["retired"]))
            self.assertEqual(guard.stale_hits(self.driver, self.checks[metric]["retired"]), [])

    def test_06_named_cohort_and_distinct_shared_denominators(self) -> None:
        self.assertEqual(len(self.rows), 42)
        self.assertEqual(len(self.protein), 41)
        self.assertEqual([r["pdb_id"] for r in self.rows if r not in self.protein], ["12CI"])
        self.assertEqual(sum(r["ramachandran_n_shared"] for r in self.protein), 46677)
        self.assertEqual(sum(r["rotamer_n_shared"] for r in self.protein), 38744)
        for r in self.protein:
            self.assertEqual(r["ramachandran_n_same"], r["ramachandran_n_shared"])
            self.assertEqual(len(r["ramachandran_disagreements"]), 0)
            self.assertEqual(r["rotamer_n_shared"] - r["rotamer_n_same_rotamer"],
                             len(r["rotamer_name_disagreements"]))
        nucleic = next(r for r in self.rows if r["pdb_id"] == "12CI")
        self.assertEqual(nucleic["ramachandran_n_shared"], 0)
        self.assertEqual(nucleic["rotamer_n_shared"], 0)
        self.assertNotIn("ramachandran_agreement", nucleic)
        self.assertNotIn("rotamer_rotamer_agreement", nucleic)

    def test_07_15c8_name_difference_is_not_outlier_disagreement(self) -> None:
        r = next(r for r in self.protein if r["pdb_id"] == "15C8")
        self.assertEqual((r["rotamer_n_same_rotamer"], r["rotamer_n_shared"]), (368, 371))
        self.assertEqual((r["ramachandran_n_same"], r["ramachandran_n_shared"]), (426, 426))
        differences = r["rotamer_name_disagreements"]
        self.assertEqual([d["residue"] for d in differences],
                         [["H", 52, "A", "PRO"], ["H", 82, "A", "SER"], ["H", 82, "B", "SER"]])
        self.assertTrue(all(d["phenix_verdict"] == "Favored" for d in differences))
        self.assertTrue(all(d["report"] != "OUTLIER" for d in differences))
        # The report records non-OUTLIER names, not a Favored/Allowed classification.
        self.assertTrue(all("report_verdict" not in d for d in differences))
        self.assertEqual(sum(r["rotamer_n_same_rotamer"] for r in self.protein), 38741)
        outlier_differences = [
            d for r in self.protein for d in r["rotamer_name_disagreements"]
            if (d["report"] == "OUTLIER") != (d["phenix_verdict"] == "OUTLIER")
        ]
        self.assertEqual(outlier_differences, [])
        floor = Decimal(guard.registry_value(self.checks[METRICS[1]]["registry"], self.registry))
        self.assertGreater(Decimal(368) / Decimal(371), floor)

    def test_08_exact_floor_boundary_uses_counts_not_rounded_display(self) -> None:
        floor = Decimal(guard.registry_value(self.checks[METRICS[0]]["registry"], self.registry))
        # Arithmetic illustration only; not a new grading implementation or QDS binding.
        self.assertTrue(Decimal(99) / Decimal(100) >= floor)
        self.assertFalse(Decimal(9899) / Decimal(10000) >= floor)
        self.assertEqual(round(9899 / 10000, 2), float(floor))

    def test_09_existing_parser_preserves_insertion_keys_and_name_diagnostic(self) -> None:
        xml = (
            '<ModelledSubgroup rama="Favored" rota="t0" chain="H" resnum="52" icode="A" resname="PRO">'
            '<ModelledSubgroup rama="OUTLIER" rota="OUTLIER" chain="H" resnum="52" icode="B" resname="PRO">'
        )
        rota = (
            " H  52A PRO:1.00:80.0:0.0:Favored:Cg_exo\n"
            " H  52B PRO:1.00:0.1:0.0:OUTLIER:OUTLIER\n"
        )
        rama = (
            " H  52A PRO:80.0:-60.0:40.0:Favored:General\n"
            " H  52B PRO:0.1:-60.0:40.0:OUTLIER:General\n"
        )
        names = rotamer_agreement(xml, rota)
        self.assertEqual(names["n_shared"], 2)
        self.assertEqual(names["n_same_rotamer"], 1)
        ref, local = report_rotamers(xml), local_rotamers(rota)
        shared = ref.keys() & local.keys()
        self.assertEqual(len(shared), 2)
        self.assertTrue(all((ref[k] == "OUTLIER") == (local[k][1] == "OUTLIER") for k in shared))
        self.assertEqual(ramachandran_agreement(xml, rama)["agreement"], 1.0)
        self.assertEqual(rotamer_agreement("", rota), {"n_shared": 0})
        self.assertEqual(ramachandran_agreement("", rama), {"n_shared": 0})

    def test_10_all_existing_governed_values_still_match(self) -> None:
        for entry in self.checks.values():
            with self.subTest(metric=entry["metric"]):
                self.assertEqual(guard.registry_value(entry["registry"], self.registry), entry["current"])
                if DRIVER in entry["consumers"]:
                    self.assertEqual(guard.stale_hits(self.driver, entry["retired"]), [])

    def test_11_documentary_adoption_does_not_create_a_qds_binding(self) -> None:
        criteria = yaml.safe_load(read("ref/structural_criteria.yaml"))
        self.assertEqual(criteria["pass_criterion_bindings"], [])
        catalog = yaml.safe_load(read("ref/catalog.yaml"))
        agreement_metrics = [
            item["id"] for item in catalog["metric_definitions"]
            if item["id"].startswith("T05_") and "agreement" in item["id"]
        ]
        self.assertEqual(agreement_metrics, [])

    def test_12_current_floor_must_lead_each_tolerance_cell(self) -> None:
        for metric, label in zip(METRICS, LABELS):
            with self.subTest(row=label):
                prefix = f"| {label} | "
                original = row(self.registry, label)
                self.assertTrue(original.startswith(prefix + "**Classification floor:"))
                self.assertIn("**Historical percentage diagnostics (not classification gates):**", original)
                # #830: the initial proposal contained a floor but buried it after
                # percentage-leading prose. Presence alone must not satisfy the guard.
                buried = original.replace(prefix, prefix + "Historical percentage lead. ", 1)
                self.assertIn("**Classification floor: agreement ≥ 0.99**", buried)
                changed = self.registry.replace(original, buried)
                self.assertIsNone(guard.registry_value(self.checks[metric]["registry"], changed))
        favored = row(self.registry, LABELS[0])
        self.assertIn("**Separate unresolved rotamer-favored exception (not calibrated by this adoption):**", favored)
        self.assertNotIn("The band question — classification agreement vs raw-% agreement — is **#284**",
                         row(self.registry, LABELS[1]))


if __name__ == "__main__":
    unittest.main()
