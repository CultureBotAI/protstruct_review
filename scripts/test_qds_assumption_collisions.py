#!/usr/bin/env python3
"""In-memory contract-4 assumption identity and selection regressions (#744)."""
from __future__ import annotations

import copy
import itertools
import unittest

import qds_emit_contract_v4 as v4
from qds_correction_projection import canonical_sha256
from test_qds_contract_v4 import NEW, OLD, QDS, fixture


ORIGINS = ("registry", "measurement", "run", "headline")


def assumption(row_id: str = "A_shared", description: str = "Synthetic shared assumption.") -> dict:
    return {
        "id": row_id, "kind": "implicit", "scope": "tool", "title": "Synthetic assumption",
        "description": description, "status": "unchecked", "tool_ref": "MolProbity (gold)",
        "as_of_date": "2026-09-20", "effective_at": "2026-09-20T00:00:00+00:00",
    }


def add_assumption(documents: list[dict], origin: str, row: dict) -> None:
    run = documents[1]["evaluation_runs"][0]
    row = copy.deepcopy(row)
    if origin == "registry":
        documents[1]["assumptions"].append(row)
    elif origin == "measurement":
        run["measurements"][0].setdefault("assumptions", []).append(row)
    elif origin == "run":
        run.setdefault("assumptions", []).append(row)
    elif origin == "headline":
        run.setdefault("headline_findings", [{"id": "F_new", "catalog_task_refs": ["T05"]}])[0].setdefault("assumptions", []).append(row)
    else:
        raise AssertionError(origin)


def emit(documents: list[dict]) -> dict:
    return v4.emit_projection(v4.prepare_projection(documents, QDS, "synth4"))


class AssumptionCollisionTests(unittest.TestCase):
    def test_conflicting_payloads_rejected_across_every_origin_pair(self) -> None:
        for first, second in itertools.combinations(ORIGINS, 2):
            with self.subTest(first=first, second=second):
                documents = fixture()
                add_assumption(documents, first, assumption(description="First interpretation."))
                add_assumption(documents, second, assumption(description="Different interpretation."))
                with self.assertRaisesRegex(v4.QdsCompletenessError, "conflicting active assumption id 'A_shared'"):
                    emit(documents)

    def test_identical_payloads_dedupe_across_every_origin_pair(self) -> None:
        for first, second in itertools.combinations(ORIGINS, 2):
            with self.subTest(first=first, second=second):
                documents = fixture()
                row = assumption()
                add_assumption(documents, first, row)
                add_assumption(documents, second, row)
                before = copy.deepcopy(documents)
                qds = emit(documents)
                self.assertEqual(qds["assumptions_report"], [row])
                self.assertEqual(documents, before)

    def test_conflicting_run_assumptions_from_different_active_runs_fail(self) -> None:
        documents = fixture()
        old, new = documents[0]["evaluation_runs"][0], documents[1]["evaluation_runs"][0]
        new["corrections"] = []
        old["assumptions"] = [assumption(description="Old retained interpretation.")]
        new["assumptions"] = [assumption(description="Different newer interpretation.")]
        with self.assertRaisesRegex(v4.QdsCompletenessError, "conflicting active assumption id"):
            emit(documents)

    def test_typed_replacement_cannot_be_hidden_by_registry_collision(self) -> None:
        documents = fixture()
        old, new = documents[0]["evaluation_runs"][0], documents[1]["evaluation_runs"][0]
        old["assumptions"] = [assumption("A_old", "Old assumption.")]
        new["assumptions"] = [assumption("A_new", "Correct replacement content.")]
        new["corrections"][0].update(
            target_collection="assumptions", target_ref="A_old",
            target_sha256=canonical_sha256(old["assumptions"][0]), replacement_ref="A_new",
        )
        documents[1]["assumptions"] = [assumption("A_new", "Different registry payload.")]
        with self.assertRaisesRegex(v4.QdsCompletenessError, "conflicting active assumption id 'A_new'"):
            emit(documents)

    def test_withdrawn_registry_id_does_not_remove_distinct_run_assumption(self) -> None:
        documents = fixture()
        registry = assumption(description="Withdrawn registry payload.")
        registry["measurement_ref"] = "M_old"
        documents[1]["assumptions"] = [registry]
        run_row = assumption(description="Independent surviving run interpretation.")
        add_assumption(documents, "run", run_row)
        documents[1]["evaluation_runs"][0]["corrections"].append({
            "id": "C_registry", "action": "withdraw", "target_collection": "tool_assumptions",
            "target_evaluation_run_ref": NEW, "target_ref": registry["id"],
            "target_sha256": canonical_sha256(registry), "reason": "Synthetic registry withdrawal.",
            "evidence_refs": [OLD],
        })
        qds = emit(documents)
        self.assertEqual(qds["assumptions_report"], [run_row])

    def test_irrelevant_registry_same_id_is_not_emitted_or_dependency_checked(self) -> None:
        documents = fixture()
        unrelated = assumption(description="Unrelated tool interpretation.")
        unrelated.update(tool_ref="ctruncate", measurement_ref="M_old")
        documents[1]["assumptions"] = [unrelated]
        run_row = assumption(description="Relevant run interpretation.")
        add_assumption(documents, "run", run_row)
        self.assertEqual(emit(documents)["assumptions_report"], [run_row])

    def test_future_registry_same_id_is_not_emitted(self) -> None:
        documents = fixture()
        future = assumption(description="Future registry interpretation.")
        future.update(as_of_date="2026-09-24", effective_at="2026-09-24T00:00:00+00:00")
        documents[1]["assumptions"] = [future]
        run_row = assumption(description="Current run interpretation.")
        add_assumption(documents, "run", run_row)
        self.assertEqual(emit(documents)["assumptions_report"], [run_row])

    def test_inactive_ancestor_payload_does_not_conflict_or_reactivate(self) -> None:
        documents = fixture()
        ancestor = assumption(description="Retired registry interpretation.")
        ancestor["measurement_ref"] = "M_old"
        successor = assumption("A_successor", "Active registry interpretation.")
        successor.update(as_of_date="2026-09-23", effective_at="2026-09-23T00:00:00+00:00", supersedes_assumption_ref="A_shared")
        documents[1]["assumptions"] = [ancestor, successor]
        run_row = assumption(description="Distinct active run interpretation.")
        add_assumption(documents, "run", run_row)
        before = copy.deepcopy(documents)
        qds = emit(documents)
        self.assertEqual(qds["assumptions_report"], [run_row, successor])
        self.assertEqual(documents, before)

    def test_selected_registry_dependency_to_withdrawn_measurement_still_fails(self) -> None:
        documents = fixture()
        registry = assumption()
        registry["measurement_ref"] = "M_old"
        documents[1]["assumptions"] = [registry]
        with self.assertRaisesRegex(v4.QdsCompletenessError, "measurement_ref.*missing or withdrawn"):
            emit(documents)

    def test_selected_registry_dependency_to_active_measurement_passes(self) -> None:
        documents = fixture()
        registry = assumption()
        registry["measurement_ref"] = "M_new"
        documents[1]["assumptions"] = [registry]
        self.assertEqual(emit(documents)["assumptions_report"], [registry])

    def test_report_is_detached_from_projection_inputs(self) -> None:
        documents = fixture()
        add_assumption(documents, "run", assumption())
        projection = v4.prepare_projection(documents, QDS, "synth4")
        before = copy.deepcopy(projection)
        rows = v4._collect_assumptions_report(projection)
        rows[0]["description"] = "Changed returned copy."
        self.assertEqual(projection, before)


if __name__ == "__main__":
    unittest.main()
