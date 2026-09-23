#!/usr/bin/env python3
"""Live registry admission versus immutable contract-4 replay; no tool runs."""
from __future__ import annotations

import copy
from pathlib import Path
import unittest
from unittest import mock

import yaml

import qds_emit
import qds_emit_contract_v4 as v4
from qds_correction_projection import canonical_sha256


RUN = "EVAL_live_admission_2026-09-23"
QDS = "QDS_live_admission_2026-09-23"
SUBJECT = "synthetic:live-admission"
TOOL = "MolProbity (gold)"
METRIC = "T05_clashscore"


def registries() -> dict[str, list[dict]]:
    assumption = {
        "id": "A_old", "as_of_date": "2026-09-20",
        "effective_at": "2026-09-20T00:00:00+00:00", "tool_ref": TOOL,
        "kind": "implicit", "scope": "tool", "title": "Synthetic assumption",
        "description": "Invented test guidance", "status": "unchecked",
    }
    recommendation = {
        "id": "REC_old", "as_of_date": "2026-09-20",
        "effective_at": "2026-09-20T00:00:00+00:00", "tool_ref": TOOL,
        "metric_definition_ref": METRIC, "role": "top_performing", "rank": 1,
        "justification": "Invented test recommendation",
    }
    return {
        "assumptions": [assumption, {
            **assumption, "id": "A_current", "as_of_date": "2026-09-21",
            "effective_at": "2026-09-21T00:00:00+00:00",
            "supersedes_assumption_ref": "A_old",
        }],
        "tool_recommendations": [recommendation, {
            **recommendation, "id": "REC_current", "as_of_date": "2026-09-21",
            "effective_at": "2026-09-21T00:00:00+00:00",
            "supersedes_recommendation_ref": "REC_old",
        }],
    }


def document(rows: dict[str, list[dict]]) -> dict:
    return {
        "structures": [{"id": "synth_live", "description": "Synthetic test only."}],
        "tools": [{"id": TOOL, "family": "non_cctbx", "catalog_tasks_served": ["T05"]}],
        **copy.deepcopy(rows),
        "evaluation_runs": [{
            "id": RUN, "run_date": "2026-09-23", "structure_ref": "synth_live",
            "catalog_tasks_applied": ["T05"], "measurements": [{
                "id": "M_live", "catalog_task_ref": "T05", "metric_definition_ref": METRIC,
                "oracle_tool_ref": TOOL, "oracle_family": "non_cctbx",
                "stage": "final", "scope": "complex", "subject_ref": SUBJECT,
                "oracle_measure": {"value_numeric": 3.0}, "pass_status": "informational",
            }],
        }],
        "qds_emission_contexts": [{
            "id": "CTX_live", "qds_ref": QDS, "owner_evaluation_run_ref": RUN,
            "snapshot_owner_evaluation_run_ref": RUN, "structure_ref": "synth_live",
            "subject_ref": SUBJECT, "source_evaluation_run_refs": [RUN],
            "issued_at": "2026-09-23T08:00:00+00:00", "coverage_scope": "cumulative",
            "scope_notes": "Invented live-admission fixture; no scientific tool execution.",
            "identity_description": "Synthetic structure", "headline_verdict": "Synthetic only.",
        }],
    }


def projected(rows: dict[str, list[dict]]) -> dict:
    doc = document(rows)
    return {
        **copy.deepcopy(rows), "context": doc["qds_emission_contexts"][0],
        "runs": doc["evaluation_runs"],
    }


def source_superseders(
    doc: dict, field: str, *, count: int = 1, cross_tool: bool = False,
    cross_metric: bool = False, date: str = "2026-09-23",
) -> dict:
    supersedes = "supersedes_assumption_ref" if field == "assumptions" else "supersedes_recommendation_ref"
    target = doc[field][-1]
    if cross_tool:
        doc["tools"].append({"id": "ctruncate", "family": "non_cctbx", "catalog_tasks_served": ["T13"]})
    for number in range(count):
        predecessor = doc[field][-1]
        successor = {
            **predecessor, "id": f"{field}_source_only_{number}",
            "as_of_date": date, "effective_at": f"{date}T00:00:00+00:00",
            supersedes: predecessor["id"],
        }
        if cross_tool:
            successor["tool_ref"] = "ctruncate"
        if cross_metric:
            successor["metric_definition_ref"] = "T13_wilson_b"
        doc[field].append(successor)
    return target


class LiveAdmissionTests(unittest.TestCase):
    def check_admission(self, projection: dict, live: dict[str, list[dict]]) -> None:
        with mock.patch.object(
            v4, "_load_live_registry_rows",
            side_effect=lambda _root, _filename, field: copy.deepcopy(live[field]),
        ):
            v4._validate_live_registry_snapshots(projection, Path("unused-test-root"))

    def emit(self, doc: dict, live: dict[str, list[dict]], **kwargs: object) -> dict:
        with mock.patch.object(v4, "_read_documents", return_value=[doc]), mock.patch.object(
            v4, "_load_live_registry_rows",
            side_effect=lambda _root, _filename, field: copy.deepcopy(live[field]),
        ):
            return qds_emit.emit_qds([], QDS, "synth_live", **kwargs)

    def test_current_default_rejects_empty_or_individually_omitted_snapshots(self) -> None:
        live = registries()
        for empty in (("tool_recommendations", "assumptions"),
                      ("tool_recommendations",), ("assumptions",)):
            with self.subTest(empty=empty):
                doc = document(live)
                for field in empty:
                    doc[field] = []
                with self.assertRaisesRegex(qds_emit.QdsCompletenessError, "snapshot omits applicable"):
                    self.emit(doc, live)

    def test_complete_relevant_snapshots_emit_and_remain_unchanged(self) -> None:
        live = registries()
        doc = document(live)
        before = copy.deepcopy(doc)
        qds = self.emit(doc, live)
        self.assertEqual(qds["emitter_contract_version"], "4")
        self.assertEqual([r["id"] for r in qds["tool_recommendations_applied"]], ["REC_current"])
        self.assertEqual([r["id"] for r in qds["assumptions_report"]], ["A_current"])
        self.assertEqual(doc, before)

    def test_mutated_applicable_rows_fail_exact_source_comparison(self) -> None:
        live = registries()
        for field, payload in (("tool_recommendations", "justification"),
                               ("assumptions", "description")):
            with self.subTest(field=field):
                p = projected(live)
                p[field][-1][payload] = "Changed without a typed replacement."
                with self.assertRaisesRegex(v4.QdsCompletenessError, "differs from its exact registry"):
                    self.check_admission(p, live)

    def test_ancestor_closure_is_required_even_when_ancestor_no_longer_applies(self) -> None:
        for field, applies_to in (("tool_recommendations", "metric_definition_ref"),
                                  ("assumptions", "tool_ref")):
            with self.subTest(field=field):
                live = registries()
                live[field][0][applies_to] = "historical-other-scope"
                p = projected(live)
                p[field].pop(0)
                with self.assertRaisesRegex(v4.QdsCompletenessError, "row or ancestor.*old"):
                    self.check_admission(p, live)

    def test_future_and_unrelated_rows_need_not_be_in_curated_snapshot(self) -> None:
        live = registries()
        p = projected(live)
        for field, supersedes, applies_to in (
            ("tool_recommendations", "supersedes_recommendation_ref", "metric_definition_ref"),
            ("assumptions", "supersedes_assumption_ref", "tool_ref"),
        ):
            live[field].append({
                **live[field][-1], "id": f"{field}_future", "as_of_date": "2026-09-24",
                "effective_at": "2026-09-24T00:00:00+00:00", supersedes: live[field][-1]["id"],
            })
            live[field].append({**live[field][0], "id": f"{field}_unrelated", applies_to: "unused"})
        self.check_admission(p, live)

    def test_applicability_uses_corrected_subject_admitted_runs(self) -> None:
        live = registries()
        p = projected({"tool_recommendations": [], "assumptions": []})
        p["raw_runs"] = copy.deepcopy(p["runs"])
        p["runs"][0]["measurements"] = []
        self.check_admission(p, live)

    def test_issue_instant_is_inclusive(self) -> None:
        live = registries()
        p = projected({field: rows[:1] for field, rows in live.items()})
        p["context"]["issued_at"] = "2026-09-20T23:59:59+00:00"
        self.check_admission(p, live)
        p["context"]["issued_at"] = "2026-09-21T00:00:00+00:00"
        with self.assertRaisesRegex(v4.QdsCompletenessError, "snapshot omits applicable"):
            self.check_admission(p, live)

    def test_explicit_withdrawal_keeps_raw_admission_but_suppresses_output(self) -> None:
        live = registries()
        for collection, field, output in (
            ("tool_recommendations", "tool_recommendations", "tool_recommendations_applied"),
            ("tool_assumptions", "assumptions", "assumptions_report"),
        ):
            with self.subTest(collection=collection):
                doc = document(live)
                target = doc[field][-1]
                doc["evaluation_runs"][0]["corrections"] = [{
                    "id": "C_withdraw", "action": "withdraw", "target_collection": collection,
                    "target_evaluation_run_ref": RUN, "target_ref": target["id"],
                    "target_sha256": canonical_sha256(target), "reason": "Synthetic explicit withdrawal.",
                    "evidence_refs": ["ref/research/synthetic_active_site_review_2026-09-23.md"],
                }]
                qds = self.emit(doc, live)
                self.assertNotIn(output, qds)
                self.assertEqual(qds["applied_corrections"][0]["target_ref"], target["id"])

    def test_explicit_replacement_can_add_source_owned_successor(self) -> None:
        live = registries()
        doc = document(live)
        target = doc["assumptions"][-1]
        successor = {**target, "id": "A_local_correction", "as_of_date": "2026-09-23",
                     "effective_at": "2026-09-23T00:00:00+00:00"}
        successor.pop("supersedes_assumption_ref")
        doc["assumptions"].append(successor)
        doc["evaluation_runs"][0]["corrections"] = [{
            "id": "C_replace", "action": "replace", "target_collection": "tool_assumptions",
            "target_evaluation_run_ref": RUN, "target_ref": target["id"],
            "target_sha256": canonical_sha256(target), "replacement_ref": successor["id"],
            "reason": "Synthetic explicit replacement.",
            "evidence_refs": ["ref/research/synthetic_active_site_review_2026-09-23.md"],
        }]
        qds = self.emit(doc, live)
        self.assertEqual([row["id"] for row in qds["assumptions_report"]], [successor["id"]])

    def test_source_only_retirement_requires_authority_across_tools_metrics_and_chains(self) -> None:
        live = registries()
        for field in ("assumptions", "tool_recommendations"):
            changes = ((False, False), (True, False))
            if field == "tool_recommendations":
                changes += ((False, True), (True, True))
            for cross_tool, cross_metric in changes:
                for count in (1, 2, 3):
                    with self.subTest(field=field, cross_tool=cross_tool,
                                      cross_metric=cross_metric, count=count):
                        doc = document(live)
                        source_superseders(doc, field, count=count,
                                           cross_tool=cross_tool, cross_metric=cross_metric)
                        with self.assertRaisesRegex(qds_emit.QdsCompletenessError, "source-only.*exact typed registry correction"):
                            self.emit(doc, live)

    def test_source_only_retirement_accepts_exact_typed_replacement_or_withdrawal(self) -> None:
        live = registries()
        for field, collection in (("assumptions", "tool_assumptions"),
                                  ("tool_recommendations", "tool_recommendations")):
            for action in ("withdraw", "replace"):
                with self.subTest(field=field, action=action):
                    doc = document(live)
                    target = source_superseders(doc, field, count=2)
                    correction = {
                        "id": "C_authorized", "action": action, "target_collection": collection,
                        "target_evaluation_run_ref": RUN, "target_ref": target["id"],
                        "target_sha256": canonical_sha256(target), "reason": "Explicit synthetic retirement.",
                        "evidence_refs": ["ref/research/synthetic_active_site_review_2026-09-23.md"],
                    }
                    if action == "replace":
                        correction["replacement_ref"] = doc[field][-1]["id"]
                    doc["evaluation_runs"][0]["corrections"] = [correction]
                    qds = self.emit(doc, live)
                    self.assertEqual(qds["applied_corrections"], [correction])

    def test_correcting_another_ancestor_does_not_authorize_live_row_retirement(self) -> None:
        live = registries()
        for field, collection in (("assumptions", "tool_assumptions"),
                                  ("tool_recommendations", "tool_recommendations")):
            with self.subTest(field=field):
                doc = document(live)
                source_superseders(doc, field)
                ancestor = doc[field][0]
                doc["evaluation_runs"][0]["corrections"] = [{
                    "id": "C_other", "action": "withdraw", "target_collection": collection,
                    "target_evaluation_run_ref": RUN, "target_ref": ancestor["id"],
                    "target_sha256": canonical_sha256(ancestor), "reason": "Unrelated ancestor correction.",
                    "evidence_refs": ["ref/research/synthetic_active_site_review_2026-09-23.md"],
                }]
                with self.assertRaisesRegex(qds_emit.QdsCompletenessError, "source-only.*exact typed registry correction"):
                    self.emit(doc, live)

    def test_retirement_authority_matches_exact_collection_owner_and_payload(self) -> None:
        live = registries()
        doc = document(live)
        target = source_superseders(doc, "assumptions")
        p = projected({field: doc[field] for field in live})
        correct = {
            "id": "C_exact", "action": "withdraw", "target_collection": "tool_assumptions",
            "target_evaluation_run_ref": RUN, "target_ref": target["id"],
            "target_sha256": canonical_sha256(target),
            "reason": "Exact synthetic retirement authority.",
            "evidence_refs": ["ref/research/synthetic_active_site_review_2026-09-23.md"],
        }
        for field, value in (("target_collection", "assumptions"),
                             ("target_evaluation_run_ref", "OTHER_RUN"),
                             ("target_sha256", "0" * 64)):
            with self.subTest(field=field):
                p["corrections"] = [{**correct, field: value}]
                with self.assertRaisesRegex(v4.QdsCompletenessError, "source-only.*exact typed registry correction"):
                    self.check_admission(p, live)
        p["corrections"] = [correct]
        self.check_admission(p, live)

    def test_future_source_supersession_does_not_retire_issue_time_guidance(self) -> None:
        live = registries()
        doc = document(live)
        for field in live:
            source_superseders(doc, field, date="2026-09-24")
        qds = self.emit(doc, live)
        self.assertEqual([r["id"] for r in qds["assumptions_report"]], ["A_current"])
        self.assertEqual([r["id"] for r in qds["tool_recommendations_applied"]], ["REC_current"])

    def test_supersession_of_inapplicable_live_guidance_is_not_blocked(self) -> None:
        live = registries()
        for field in live:
            unrelated = {**live[field][0], "id": f"{field}_unrelated"}
            if field == "assumptions":
                unrelated["tool_ref"] = "ctruncate"
            else:
                unrelated["metric_definition_ref"] = "T13_wilson_b"
            live[field].append(unrelated)
        doc = document(live)
        doc["tools"].append({"id": "ctruncate", "family": "non_cctbx", "catalog_tasks_served": ["T13"]})
        for field in live:
            source_superseders(doc, field)
        qds = self.emit(doc, live)
        self.assertEqual([r["id"] for r in qds["assumptions_report"]], ["A_current"])
        self.assertEqual([r["id"] for r in qds["tool_recommendations_applied"]], ["REC_current"])

    def test_pinned_replay_does_not_reinterpret_source_only_supersession(self) -> None:
        live = registries()
        doc = document(live)
        source_superseders(doc, "assumptions")
        expected = v4.emit_projection(v4.prepare_projection([doc], QDS, "synth_live"))
        with mock.patch.object(v4, "_read_documents", return_value=[doc]), mock.patch.object(
            v4, "_load_live_registry_rows", side_effect=AssertionError("live registry read during replay"),
        ), mock.patch.object(Path, "read_text", side_effect=AssertionError("live file read during replay")):
            replayed = qds_emit.emit_qds([], QDS, "synth_live", require_pinned_tool_snapshot=True)
        self.assertEqual(replayed, expected)

    def test_pinned_replay_never_reads_live_registries_or_catalog(self) -> None:
        doc = document({"tool_recommendations": [], "assumptions": []})
        expected = v4.emit_projection(v4.prepare_projection([doc], QDS, "synth_live"))
        with mock.patch.object(v4, "_read_documents", return_value=[doc]), mock.patch.object(
            v4, "_load_live_registry_rows", side_effect=AssertionError("live registry read during replay"),
        ), mock.patch.object(Path, "read_text", side_effect=AssertionError("live file read during replay")):
            replayed = qds_emit.emit_qds([], QDS, "synth_live", require_pinned_tool_snapshot=True)
        self.assertEqual(replayed, expected)

    def test_live_registry_loader_rejects_missing_malformed_or_duplicate_authority(self) -> None:
        for bad in (OSError("unavailable"), "[]", "assumptions: null", "assumptions: []\nassumptions: []"):
            with self.subTest(bad=bad):
                patch = {"side_effect": bad} if isinstance(bad, Exception) else {"return_value": bad}
                with mock.patch.object(Path, "read_text", **patch):
                    with self.assertRaises(v4.QdsCompletenessError):
                        v4._load_live_registry_rows(Path("unused-test-root"), "tool_assumptions.yaml", "assumptions")

    def test_real_current_synthetic_snapshot_remains_admissible(self) -> None:
        source = v4.REPO / "data/examples/eval/EVAL_synth_active_site_2026-09-23.yaml"
        doc = yaml.safe_load(source.read_text())
        context = doc["qds_emission_contexts"][0]
        context["snapshot_owner_evaluation_run_ref"] = context["owner_evaluation_run_ref"]
        p = v4.prepare_projection([doc], context["qds_ref"], "synth1")
        v4._validate_live_registry_snapshots(p, v4.REPO)


if __name__ == "__main__":
    unittest.main()
