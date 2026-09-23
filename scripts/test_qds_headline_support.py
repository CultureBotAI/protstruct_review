#!/usr/bin/env python3
"""Exact historical headline-support applicability regressions (#746)."""
from __future__ import annotations

import copy
import unittest

import qds_emit_contract_v4 as v4
from qds_correction_projection import canonical_sha256
from test_qds_contract_v4 import NEW, OLD, QDS, fixture, measurement


def assumption(row_id: str) -> dict:
    return {"id": row_id, "kind": "implicit", "scope": "tool", "title": row_id,
            "description": "Synthetic support test only.", "status": "unchecked"}


def context_refs(documents: list[dict]) -> None:
    runs = sorted((run for document in documents for run in document["evaluation_runs"]),
                  key=lambda run: (run["run_date"], run["id"]))
    documents[1]["qds_emission_contexts"][0]["source_evaluation_run_refs"] = [r["id"] for r in runs]


def supported_parent_fixture() -> list[dict]:
    documents = fixture()
    old, new = documents[0]["evaluation_runs"][0], documents[1]["evaluation_runs"][0]
    foreign = {
        "id": "EVAL_foreign_2026-09-19", "run_date": "2026-09-19", "structure_ref": "synth4",
        "catalog_tasks_applied": ["T05"],
        "measurements": [{**measurement("M_foreign"), "subject_ref": "other-model"}],
        "headline_findings": [{"id": "F_foreign", "catalog_task_refs": ["T05"],
                               "assumptions": [assumption("A_foreign")]}],
    }
    old["headline_findings"] = [{
        "id": "F_old", "catalog_task_refs": ["T05"], "supporting_measurement_refs": ["M_old"],
        "assumptions": [assumption("A_imported")],
    }]
    template = copy.deepcopy(new["corrections"][0])
    old["corrections"] = [{
        **template, "id": "C_child", "target_collection": "headline_assumptions",
        "target_evaluation_run_ref": foreign["id"], "target_ref": "A_foreign",
        "target_sha256": canonical_sha256(foreign["headline_findings"][0]["assumptions"][0]),
        "replacement_ref": "A_imported",
    }]
    new["measurements"] = []
    new["headline_findings"] = [{
        "id": "F_new", "catalog_task_refs": ["T05"], "supporting_measurement_refs": ["M_old"],
        "assumptions": [assumption("A_new")],
    }]
    new["corrections"] = [{
        **template, "target_collection": "headline_findings", "target_ref": "F_old",
        "target_sha256": canonical_sha256(old["headline_findings"][0]), "replacement_ref": "F_new",
    }]
    documents[0]["evaluation_runs"].insert(0, foreign)
    context_refs(documents)
    return documents


def old_run(documents: list[dict]) -> dict:
    return next(r for r in documents[0]["evaluation_runs"] if r["id"] == OLD)


def refresh_parent_digest(documents: list[dict]) -> None:
    documents[1]["evaluation_runs"][0]["corrections"][0]["target_sha256"] = canonical_sha256(old_run(documents)["headline_findings"][0])


def emit(documents: list[dict]) -> dict:
    return v4.emit_projection(v4.prepare_projection(documents, QDS, "synth4"))


class HeadlineSupportTests(unittest.TestCase):
    def test_independent_parent_support_survives_foreign_derived_child(self) -> None:
        documents = supported_parent_fixture()
        before = copy.deepcopy(documents)
        qds = emit(documents)
        self.assertEqual(qds["active_evaluation_run_refs"], [OLD, NEW])
        self.assertEqual([row["id"] for row in qds["assumptions_report"]], ["A_new"])
        self.assertEqual(documents, before)

    def test_original_correction_only_headline_can_use_cross_run_support(self) -> None:
        documents = fixture()
        new = documents[1]["evaluation_runs"][0]
        new["measurements"], new["corrections"] = [], []
        new["headline_findings"] = [{"id": "F_new", "supporting_measurement_refs": ["M_old"],
                                     "catalog_task_refs": ["T05"], "assumptions": [assumption("A_new")]}]
        qds = emit(documents)
        self.assertEqual(qds["active_evaluation_run_refs"], [OLD, NEW])
        self.assertEqual([row["id"] for row in qds["assumptions_report"]], ["A_new"])

    def test_original_correction_only_parent_anchors_later_nested_replacement(self) -> None:
        documents = fixture()
        new = documents[1]["evaluation_runs"][0]
        middle = {"id": "EVAL_middle_2026-09-21", "run_date": "2026-09-21", "structure_ref": "synth4",
                  "catalog_tasks_applied": ["T05"], "measurements": [], "headline_findings": [{
                      "id": "F_mid", "catalog_task_refs": ["T05"], "supporting_measurement_refs": ["M_old"],
                      "assumptions": [assumption("A_mid")]}]}
        new["measurements"] = []
        new["headline_findings"] = [{"id": "F_new", "catalog_task_refs": ["T05"],
                                     "assumptions": [assumption("A_new")]}]
        new["corrections"][0].update(
            target_collection="headline_assumptions", target_evaluation_run_ref=middle["id"],
            target_ref="A_mid", target_sha256=canonical_sha256(middle["headline_findings"][0]["assumptions"][0]),
            replacement_ref="A_new",
        )
        documents[0]["evaluation_runs"].append(middle)
        context_refs(documents)
        self.assertEqual([row["id"] for row in emit(documents)["assumptions_report"]], ["A_new"])

    def test_explicit_foreign_support_overrides_unrelated_carrier_measurement(self) -> None:
        documents = supported_parent_fixture()
        old_run(documents)["headline_findings"][0]["supporting_measurement_refs"] = ["M_foreign"]
        refresh_parent_digest(documents)
        qds = emit(documents)
        self.assertNotIn("assumptions_report", qds)
        self.assertNotIn(NEW, qds["active_evaluation_run_refs"])

    def test_local_foreign_same_id_cannot_use_global_selected_subject_match(self) -> None:
        documents = supported_parent_fixture()
        original = old_run(documents)
        original["measurements"].append({**measurement("M_shared"), "subject_ref": "other-model"})
        original["headline_findings"][0]["supporting_measurement_refs"] = ["M_shared"]
        control = {"id": "EVAL_control_2026-09-18", "run_date": "2026-09-18", "structure_ref": "synth4",
                   "catalog_tasks_applied": ["T05"], "measurements": [measurement("M_shared")]}
        documents[0]["evaluation_runs"].insert(0, control)
        context_refs(documents)
        refresh_parent_digest(documents)
        self.assertNotIn("assumptions_report", emit(documents))

    def test_ambiguous_global_raw_support_cannot_anchor_retired_parent(self) -> None:
        documents = supported_parent_fixture()
        old_run(documents)["headline_findings"][0]["supporting_measurement_refs"] = ["M_shared"]
        for day in (17, 18):
            documents[0]["evaluation_runs"].insert(0, {
                "id": f"EVAL_control_2026-09-{day}", "run_date": f"2026-09-{day}", "structure_ref": "synth4",
                "catalog_tasks_applied": ["T05"], "measurements": [measurement("M_shared")],
            })
        context_refs(documents)
        refresh_parent_digest(documents)
        self.assertNotIn("assumptions_report", emit(documents))

    def test_successor_cannot_self_anchor_via_independent_current_carrier_support(self) -> None:
        documents = fixture()
        old, new = documents[0]["evaluation_runs"][0], documents[1]["evaluation_runs"][0]
        old["measurements"][0]["subject_ref"] = "other-model"
        old["headline_findings"] = [{"id": "F_old", "catalog_task_refs": ["T05"],
                                     "supporting_measurement_refs": ["M_old"], "assumptions": [assumption("A_old")]}]
        new["headline_findings"] = [{"id": "F_new", "catalog_task_refs": ["T05"],
                                     "supporting_measurement_refs": ["M_new"], "assumptions": [assumption("A_new")]}]
        new["corrections"][0].update(
            target_collection="headline_findings", target_ref="F_old",
            target_sha256=canonical_sha256(old["headline_findings"][0]), replacement_ref="F_new",
        )
        self.assertNotIn("assumptions_report", emit(documents))

    def _replace_support(self, documents: list[dict], *, surviving_old_ref: bool) -> None:
        original, new = old_run(documents), documents[1]["evaluation_runs"][0]
        new["measurements"] = [measurement("M_new")]
        new["corrections"].append({
            "id": "C_support", "action": "replace", "target_collection": "measurements",
            "target_evaluation_run_ref": OLD, "target_ref": "M_old",
            "target_sha256": canonical_sha256(original["measurements"][0]), "replacement_ref": "M_new",
            "reason": "Synthetic support replacement.", "evidence_refs": [OLD],
        })
        new["headline_findings"][0]["supporting_measurement_refs"] = ["M_old" if surviving_old_ref else "M_new"]

    def test_retired_original_support_still_establishes_historical_subject_ancestry(self) -> None:
        documents = supported_parent_fixture()
        self._replace_support(documents, surviving_old_ref=False)
        qds = emit(documents)
        self.assertEqual([row["id"] for row in qds["assumptions_report"]], ["A_new"])
        self.assertEqual(qds["geometry_summary"]["clashscore"]["source_measurement_ref"], "M_new")

    def test_surviving_headline_cannot_continue_citing_retired_support(self) -> None:
        documents = supported_parent_fixture()
        self._replace_support(documents, surviving_old_ref=True)
        with self.assertRaisesRegex(v4.QdsCompletenessError, "supporting_measurement_refs.*missing or withdrawn"):
            emit(documents)

    def test_fresh_supported_parent_does_not_relabel_foreign_child(self) -> None:
        documents = supported_parent_fixture()
        new = documents[1]["evaluation_runs"][0]
        new["headline_findings"], new["corrections"] = [], []
        qds = emit(documents)
        self.assertNotIn("assumptions_report", qds)
        self.assertEqual(qds["active_evaluation_run_refs"], [OLD])


if __name__ == "__main__":
    unittest.main()
