#!/usr/bin/env python3
"""Exact retirement of obsolete tool/task exceptions; no scientific tool runs."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import unittest
from unittest import mock

import check_referential_integrity as integrity
from strict_yaml import strict_yaml_load


REPO = Path(__file__).resolve().parent.parent
RETIRED = (
    ("data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-04-24.yaml", "EVAL_1sar_cdba2c07_2026-04-24", "EVAL_1sar_cdba2c07_2026-04-24_M_004"),
    ("data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-04-24.yaml", "EVAL_1sar_cdba2c07_2026-04-24", "EVAL_1sar_cdba2c07_2026-04-24_M_005"),
    ("data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-04-24.yaml", "EVAL_1sar_cdba2c07_2026-04-24", "EVAL_1sar_cdba2c07_2026-04-24_M_006"),
    ("data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-04-24.yaml", "EVAL_1sar_cdba2c07_2026-04-24", "EVAL_1sar_cdba2c07_2026-04-24_M_008"),
    ("data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-04-24.yaml", "EVAL_1sar_cdba2c07_2026-04-24", "EVAL_1sar_cdba2c07_2026-04-24_M_010"),
    ("data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-04-24.yaml", "EVAL_1sar_cdba2c07_2026-04-24", "EVAL_1sar_cdba2c07_2026-04-24_M_013"),
    ("data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-04-24.yaml", "EVAL_1sar_cdba2c07_2026-04-24", "EVAL_1sar_cdba2c07_2026-04-24_M_018"),
    ("data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-04-24.yaml", "EVAL_1sar_cdba2c07_2026-04-24", "EVAL_1sar_cdba2c07_2026-04-24_M_030"),
    ("data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-04-24.yaml", "EVAL_1sar_cdba2c07_2026-04-24", "EVAL_1sar_cdba2c07_2026-04-24_M_round0_rfree"),
    ("data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-04-24.yaml", "EVAL_1sar_cdba2c07_2026-04-24", "EVAL_1sar_cdba2c07_2026-04-24_M_round0_rwork"),
    ("data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-04-24.yaml", "EVAL_1sar_cdba2c07_2026-04-24", "EVAL_1sar_cdba2c07_2026-04-24_M_round2_rfree"),
    ("data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-04-24.yaml", "EVAL_1sar_cdba2c07_2026-04-24", "EVAL_1sar_cdba2c07_2026-04-24_M_round2_rwork"),
    ("data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-04-24.yaml", "EVAL_1sar_cdba2c07_2026-04-24", "EVAL_1sar_cdba2c07_2026-04-24_M_round3_rfree"),
    ("data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-04-24.yaml", "EVAL_1sar_cdba2c07_2026-04-24", "EVAL_1sar_cdba2c07_2026-04-24_M_round3_rwork"),
    ("data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-04-24.yaml", "EVAL_1sar_cdba2c07_2026-04-24", "EVAL_1sar_cdba2c07_2026-04-24_M_round5_rfree"),
    ("data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-04-24.yaml", "EVAL_1sar_cdba2c07_2026-04-24", "EVAL_1sar_cdba2c07_2026-04-24_M_round5_rwork"),
    ("data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-04-24.yaml", "EVAL_1sar_cdba2c07_2026-04-24", "EVAL_1sar_cdba2c07_2026-04-24_M_round6_rfree"),
    ("data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-04-24.yaml", "EVAL_1sar_cdba2c07_2026-04-24", "EVAL_1sar_cdba2c07_2026-04-24_M_round6_rwork"),
    ("data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-04-24.yaml", "EVAL_1sar_cdba2c07_2026-04-24", "EVAL_1sar_cdba2c07_2026-04-24_M_round7_rfree"),
    ("data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-04-24.yaml", "EVAL_1sar_cdba2c07_2026-04-24", "EVAL_1sar_cdba2c07_2026-04-24_M_round7_rwork"),
    ("data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-09-07.yaml", "EVAL_1sar_cdba2c07_2026-09-07", "EVAL_1sar_cdba2c07_2026-09-07_M_001"),
    ("data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-09-07.yaml", "EVAL_1sar_cdba2c07_2026-09-07", "EVAL_1sar_cdba2c07_2026-09-07_M_002"),
    ("data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-09-07.yaml", "EVAL_1sar_cdba2c07_2026-09-07", "EVAL_1sar_cdba2c07_2026-09-07_M_003"),
    ("data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-09-07.yaml", "EVAL_1sar_cdba2c07_2026-09-07", "EVAL_1sar_cdba2c07_2026-09-07_M_004"),
)


class CatalogExceptionRetirementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.records = [(path, strict_yaml_load(path.read_text()))
                       for path in integrity.target_paths()]
        cls.index = integrity.build_corpus_indices(cls.records)
        catalog = strict_yaml_load((REPO / "ref/catalog.yaml").read_text())
        cls.served = {row["id"]: set(row.get("catalog_tasks_served", []))
                      for row in catalog["tools"]}

    def target(self, identity):
        path, owner, row_id = identity
        targets = self.index["measurement"][row_id]
        self.assertEqual(len(targets), 1)
        target = targets[0]
        self.assertEqual(target.file.relative_to(REPO).as_posix(), path)
        self.assertEqual(target.owner_run_id, owner)
        return target

    def test_exact_retired_rows_have_real_registered_producer_links(self):
        self.assertEqual(len(RETIRED), 24)
        for identity in RETIRED:
            with self.subTest(row=identity[2]):
                target = self.target(identity)
                row = target.node
                self.assertIn(row["oracle_tool_ref"],
                              {"phenix.model_vs_data", "reduce (standalone, Richardson)"})
                self.assertIn(row["catalog_task_ref"], self.served[row["oracle_tool_ref"]])
                self.assertNotIn(("tool_task", *identity),
                                 integrity.LEGACY_MEASUREMENT_SEMANTIC_EXCEPTIONS)
                self.assertFalse(integrity._legacy_measurement_semantic_exception(
                    "tool_task", target, set()))

    def test_current_corpus_has_no_stale_or_uncovered_semantic_exceptions(self):
        self.assertEqual(integrity.check_measurement_catalog_semantics(
            self.index, enforce_legacy_policy=True), [])

    def test_old_identity_cannot_hide_a_new_producer_task_mismatch(self):
        for identity in RETIRED:
            with self.subTest(row=identity[2]):
                target = self.target(identity)
                tool = target.node["oracle_tool_ref"]
                # Retain the exact frozen row/hash; change only the hypothetical
                # authoritative producer declaration so its task is now invalid.
                changed = replace(target, source_tool_tasks=((tool, ("T17",)),))
                index = dict(self.index)
                index["measurement"] = {identity[2]: [changed]}
                failures = integrity.check_measurement_catalog_semantics(index)
                self.assertTrue(any("serves only" in failure and target.pointer in failure
                                    for failure in failures), failures)

    def test_restoring_retired_allowlist_entries_fails_staleness_check(self):
        restored = {("tool_task", *identity):
                    integrity._canonical_digest(self.target(identity).node)
                    for identity in RETIRED}
        with mock.patch.dict(integrity.LEGACY_MEASUREMENT_SEMANTIC_EXCEPTIONS, restored):
            failures = integrity.check_measurement_catalog_semantics(
                self.index, enforce_legacy_policy=True)
        stale = [failure for failure in failures if
                 "stale or changed legacy measurement semantic exception" in failure]
        self.assertEqual(len(stale), 24, failures)
        for identity in RETIRED:
            self.assertTrue(any(f"row={identity[2]}" in failure for failure in stale))

    def test_unrelated_frozen_exception_still_requires_exact_content(self):
        row_id = "EVAL_1sar_cdba2c07_2026-04-24_M_007"
        target = self.index["measurement"][row_id][0]
        self.assertTrue(integrity._legacy_measurement_semantic_exception(
            "tool_task", target, set()))
        changed = replace(target, node={**target.node, "notes": "changed after publication"})
        self.assertFalse(integrity._legacy_measurement_semantic_exception(
            "tool_task", changed, set()))


if __name__ == "__main__":
    unittest.main()
