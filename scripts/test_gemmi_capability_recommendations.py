#!/usr/bin/env python3
"""#785: capability-specific Gemmi recommendations preserve dated history.

Hermetic schema, lineage and text-contract checks. No Gemmi execution.
"""
from __future__ import annotations

import copy
import datetime as dt
import io
from pathlib import Path
import sys
import unittest

import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import qds_emit
import qds_emit_contract_v1 as frozen
from records_to_tsv import emit_catalog
from protstruct_review.models import Container

EFFECTIVE = dt.datetime.fromisoformat("2026-09-27T21:11:57-07:00")
SUFFIX = "_2026_09_27_capability_correction"
EXPECTED = {
    "T02_omega_cis_trans_flips": ("gemmi validate", "deprecated"),
    "T03_bond_angle_rmsd": ("gemmi rmsz", "top_considered"),
    "T05_bond-length_rmsd": ("gemmi rmsz", "top_considered"),
    "T05_bond-angle_rmsd": ("gemmi rmsz", "top_considered"),
    "T05_planarity_rmsd": ("gemmi validate", "deprecated"),
    "T05_chirality_outliers": ("gemmi rmsz", "alternative"),
    "T06_overall_b": ("gemmi validate", "deprecated"),
}
CLAUSES = {
    "T02_omega_cis_trans_flips": (
        "single-model torsion-restraint deviations", "not matched-residue cis/trans",
        "No paired omega-flip wrapper",
    ),
    "T03_bond_angle_rmsd": (
        "bond-length rmsD in Å", "bond-angle rmsD in degrees", "not dimensionless rmsZ",
        "not a new benchmark", "matched bond-count", "restraint-library preconditions",
        "monomer-library provenance",
    ),
    "T05_bond-length_rmsd": (
        "rmsD", "in Å", "not dimensionless rmsZ", "bond counts match",
        "matched and differing restraint libraries", "monomer-library provenance",
        "informationally",
    ),
    "T05_bond-angle_rmsd": (
        "rmsD", "in degrees", "not dimensionless rmsZ", "restraint counts",
        "matched and differing libraries", "monomer-library provenance",
    ),
    "T05_planarity_rmsd": (
        "maximum atom-to-plane deviation", "not established", "No validated producer",
    ),
    "T05_chirality_outliers": (
        "wrong-handed chirality counts", "not general chiral-volume outliers",
        "checked-centre denominator", "monomer-library provenance",
        "No implemented wrapper or cross-tool benchmark",
    ),
    "T06_overall_b": (
        "undefined overall B", "not a B-factor producer",
        "Do not substitute mean atomic B or Wilson B", "validated producer",
    ),
}


def old_id(metric: str) -> str:
    return "REC_" + metric + "_top_considered"


def capability_errors(row: dict) -> list[str]:
    metric = row["metric_definition_ref"]
    tool, role = EXPECTED[metric]
    errors = []
    if (row.get("tool_ref"), row.get("role")) != (tool, role):
        errors.append("wrong capability or role")
    text = " ".join(row.get("justification", "").split())
    errors.extend(clause for clause in CLAUSES[metric] if clause not in text)
    return errors


class GemmiCapabilityRecommendations(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = yaml.safe_load((REPO / "ref/catalog.yaml").read_text())
        cls.registry = yaml.safe_load((REPO / "ref/tool_recommendations.yaml").read_text())
        cls.rows = cls.registry["tool_recommendations"]
        cls.by_id = {row["id"]: row for row in cls.rows}

    def test_schema_and_exact_seven_successors(self) -> None:
        Container.model_validate(self.catalog)
        Container.model_validate(self.registry)
        selected = [row for row in self.rows if row["id"].endswith(SUFFIX)]
        self.assertEqual(len(selected), 7)
        self.assertEqual({row["metric_definition_ref"] for row in selected}, set(EXPECTED))
        for metric in EXPECTED:
            with self.subTest(metric=metric):
                row = self.by_id[old_id(metric) + SUFFIX]
                self.assertEqual(row["supersedes_recommendation_ref"], old_id(metric))
                self.assertEqual(str(row["as_of_date"]), "2026-09-27")
                self.assertEqual(dt.datetime.fromisoformat(str(row["effective_at"])), EFFECTIVE)
                self.assertEqual(capability_errors(row), [])

    def test_historical_rows_are_not_rewritten(self) -> None:
        original_justification = (
            "Independent covalent-geometry parser (bond/angle/planarity/chirality/omega), "
            "non-cctbx."
        )
        for metric in EXPECTED:
            with self.subTest(metric=metric):
                self.assertEqual(self.by_id[old_id(metric)], {
                    "id": old_id(metric),
                    "metric_definition_ref": metric,
                    "tool_ref": "gemmi validate",
                    "role": "top_considered",
                    "rank": 1,
                    "justification": original_justification,
                    "as_of_date": "2026-07-21",
                    "effective_at": "2026-07-21T00:00:00+00:00",
                })

    def test_issue_time_boundary_in_live_and_retained_selection(self) -> None:
        before = EFFECTIVE - dt.timedelta(microseconds=1)
        original = copy.deepcopy(self.rows)
        for implementation in (qds_emit, frozen):
            for instant in (before, EFFECTIVE, EFFECTIVE + dt.timedelta(days=1)):
                active = implementation._active_registry_rows(
                    self.rows, issued_at=instant, registry_name="recommendations",
                    supersedes_field="supersedes_recommendation_ref",
                )
                active_ids = {row["id"] for row in active}
                for metric in EXPECTED:
                    with self.subTest(module=implementation.__name__, time=instant, metric=metric):
                        predecessor = old_id(metric)
                        successor = predecessor + SUFFIX
                        self.assertEqual(predecessor in active_ids, instant < EFFECTIVE)
                        self.assertEqual(successor in active_ids, instant >= EFFECTIVE)
        self.assertEqual(self.rows, original)

    def test_snapshot_builder_keeps_deprecation_instead_of_reviving_old_role(self) -> None:
        runs = [{"measurements": [{"metric_definition_ref": metric} for metric in EXPECTED]}]
        old_ids = {old_id(metric) for metric in EXPECTED}
        new_ids = {row_id + SUFFIX for row_id in old_ids}
        old_snapshot = [copy.deepcopy(self.by_id[row_id]) for row_id in sorted(old_ids)]
        for implementation in (qds_emit, frozen):
            current = implementation.build_tool_recommendations_applied(
                runs, issued_at=EFFECTIVE, registry_rows=self.rows,
            )
            self.assertTrue(new_ids <= {row["id"] for row in current})
            self.assertFalse(old_ids & {row["id"] for row in current})
            self.assertEqual(
                sum(row["role"] == "deprecated" for row in current if row["id"] in new_ids), 3,
            )
            historical = implementation.build_tool_recommendations_applied(
                runs, issued_at="2026-07-22T00:00:00Z", registry_rows=old_snapshot,
            )
            self.assertEqual({row["id"] for row in historical}, old_ids)
        self.assertEqual(old_snapshot, [self.by_id[row_id] for row_id in sorted(old_ids)])

    def test_capability_qualifier_mutations_are_detected(self) -> None:
        for metric, clauses in CLAUSES.items():
            original = self.by_id[old_id(metric) + SUFFIX]
            for clause in clauses:
                with self.subTest(metric=metric, removed=clause):
                    changed = copy.deepcopy(original)
                    changed["justification"] = changed["justification"].replace(clause, "")
                    self.assertTrue(capability_errors(changed))
            for key in ("role", "tool_ref"):
                changed = copy.deepcopy(original)
                changed[key] = "unsupported"
                self.assertTrue(capability_errors(changed))

    def test_catalog_links_and_historical_tool_identity(self) -> None:
        tasks = {row["id"]: row for row in self.catalog["catalog_tasks"]}
        tools = {row["id"]: row for row in self.catalog["tools"]}
        self.assertEqual(tools["gemmi rmsz"]["family"], "non_cctbx")
        self.assertEqual(set(tools["gemmi rmsz"]["catalog_tasks_served"]), {"T03", "T05"})
        for task in ("T03", "T05"):
            self.assertIn("gemmi rmsz", tasks[task]["oracle_tool_refs"])
        self.assertNotIn("gemmi validate", tasks["T06"]["oracle_tool_refs"])
        self.assertEqual(tools["gemmi validate"], {
            "id": "gemmi validate", "family": "non_cctbx", "catalog_tasks_served": ["T06"],
        })

    def test_generated_tsv_and_scoped_markdown(self) -> None:
        output = io.StringIO()
        emit_catalog(self.catalog, output)
        self.assertEqual(output.getvalue(), (REPO / "ref/tasks_and_evaluations.tsv").read_text())
        markdown = (REPO / "ref/tasks_and_evaluations.md").read_text()
        for task, clause in (
            ("T02", "not paired-model cis/trans changes"),
            ("T03", "bond-length rmsD (Å) and bond-angle rmsD (degrees) separate"),
            ("T05", "checked-centre denominator"),
            ("T06", "Do not substitute mean atomic B or Wilson B"),
        ):
            section = markdown.split("### " + task + " ", 1)[1].split("\n### ", 1)[0]
            self.assertIn(clause, section)
        t06 = markdown.split("### T06 ", 1)[1].split("\n### ", 1)[0]
        oracle_line = next(line for line in t06.splitlines() if "**Independent oracle(s):**" in line)
        self.assertNotIn("gemmi validate", oracle_line)

    def test_active_driver_and_oracle_guidance_preserve_field_units(self) -> None:
        driver = (REPO / "ref/driving_example_T05.md").read_text()
        self.assertIn("bond lengths in Å, bond angles in degrees", driver)
        self.assertIn("`rmsZ` is dimensionless", driver)
        guidance = (REPO / "ref/oracle_tools.md").read_text()
        self.assertIn("bond lengths and plane deviations in Å, bond angles and torsions in degrees", guidance)
        self.assertIn("**rmsZ** (unitless)", guidance)
        self.assertNotIn("**rmsD** (Å)", guidance)


if __name__ == "__main__":
    unittest.main()
