#!/usr/bin/env python3
"""Exact-parent admission for corrected measurement assumptions (#755).

Synthetic measurements only: no scientific executable or network invocation.
The projected nested arrays and emitted report must agree; report-only filtering
would leave foreign evidence available to other builders and is not sufficient.
"""
from __future__ import annotations

import copy
import hashlib
import itertools
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import check_qds_trust_invariant as trust  # noqa: E402
import check_referential_integrity as integrity  # noqa: E402
import qds_emit  # noqa: E402
import qds_emit_contract_v4 as contract  # noqa: E402
from protstruct_review.models import Container  # noqa: E402
from qds_correction_projection import canonical_sha256  # noqa: E402
from test_qds_contract_v4 import NEW, OLD, QDS, SUBJECT, add_dataset, fixture, measurement, pin_for  # noqa: E402


FOREIGN = "synthetic:model:foreign-measurement-parent"


def assumption(row_id: str) -> dict:
    # No measurement_ref: schema-valid tool-scoped nested assumptions need the
    # exact container ancestry rule, not an incidental dependency-check failure.
    return {
        "id": row_id, "kind": "implicit", "scope": "tool",
        "title": "Synthetic nested assumption", "description": "Invented ancestry diagnostic only.",
        "status": "verified",
    }


def control(row_id: str) -> dict:
    row = measurement(row_id, 0.2)
    row["metric_definition_ref"] = "T05_rotamer_outlier"
    return row


def correction(owner: dict, target_owner: dict, target: dict, successor: dict, collection: str, row_id: str) -> dict:
    return {
        "id": row_id, "action": "replace", "target_collection": collection,
        "target_evaluation_run_ref": target_owner["id"], "target_ref": target["id"],
        "target_sha256": canonical_sha256(target), "replacement_ref": successor["id"],
        "reason": "Synthetic exact-parent correction; no new scientific evidence.",
        "evidence_refs": ["ref/research/synthetic_active_site_review_2026-09-23.md"],
    }


def nested_documents(*, relevant: bool, mixed_old: bool = False) -> list[dict]:
    documents = fixture()
    old, new = documents[0]["evaluation_runs"][0], documents[1]["evaluation_runs"][0]
    parent, successor = old["measurements"][0], new["measurements"][0]
    parent["subject_ref"] = SUBJECT if relevant else FOREIGN
    parent["assumptions"] = [assumption("A_old")]
    successor["assumptions"] = [assumption("A_new")]
    new["corrections"] = [correction(new, old, parent["assumptions"][0],
                                     successor["assumptions"][0], "measurement_assumptions", "C_nested")]
    if mixed_old:
        old["measurements"].append(control("M_old_selected_control"))
    return documents


def chain_documents(pattern: tuple[str, ...], *, relevant: bool, mixed_old: bool) -> list[dict]:
    documents = fixture()
    old, new = documents[0]["evaluation_runs"][0], documents[1]["evaluation_runs"][0]
    old["run_date"] = "2026-09-20"
    middle = [{"id": f"EVAL_measurement_chain_2026-09-{day}", "run_date": f"2026-09-{day}",
               "structure_ref": "synth4", "catalog_tasks_applied": ["T05"]} for day in (21, 22)]
    runs = [old, *middle, new]
    for index, run in enumerate(runs):
        row = measurement(f"M_chain_{index}", 3.0)
        row["subject_ref"] = SUBJECT if relevant or index == 3 else FOREIGN
        row["assumptions"] = [assumption(f"A_chain_{index}")]
        run["measurements"] = [row]
        # Every intermediate/terminal carrier has independent selected evidence;
        # none may launder the other measurement's foreign ancestry.
        if index or mixed_old:
            run["measurements"].append(control(f"M_chain_control_{index}"))
        run.pop("corrections", None)
    for index, kind in enumerate(pattern):
        previous, current = runs[index:index + 2]
        target, successor = previous["measurements"][0], current["measurements"][0]
        collection = "measurements"
        if kind == "nested":
            target, successor = target["assumptions"][0], successor["assumptions"][0]
            collection = "measurement_assumptions"
        current["corrections"] = [correction(current, previous, target, successor, collection, f"C_chain_{index}")]
    documents[0]["evaluation_runs"] = runs[:-1]
    documents[-1]["qds_emission_contexts"][0]["source_evaluation_run_refs"] = [run["id"] for run in runs]
    return documents


def nested_ids(projection: dict) -> set[str]:
    return {a["id"] for run in projection["runs"] for row in run.get("measurements", [])
            for a in row.get("assumptions", [])}


def corpus_records(documents: list[dict], qds: dict) -> list[tuple[Path, dict]]:
    return [(Path("data/test") / (doc["evaluation_runs"][0]["id"] + ".yaml"), doc)
            for doc in documents] + [(Path("data/test") / (QDS + ".yaml"), {"quality_data_sheets": [qds]})]


def corpus_errors(records: list[tuple[Path, dict]]) -> list[str]:
    indices = integrity.build_corpus_indices(records)
    failures = integrity.check_duplicate_ids(indices)
    for path, document in records:
        failures.extend(integrity.check_corpus_refs(document, path, indices))
    return failures


class MeasurementAssumptionAncestryTests(unittest.TestCase):
    def emitted(self, documents: list[dict], *, root: Path = REPO) -> tuple[dict, dict]:
        before = copy.deepcopy(documents)
        for document in documents:
            Container.model_validate(document)
        projection = contract.prepare_projection(documents, QDS, "synth4", root)
        qds = contract.emit_projection(projection)
        Container.model_validate({"quality_data_sheets": [qds]})
        self.assertEqual(documents, before, "Admission must not rewrite the raw correction targets")
        return projection, qds

    def assert_ids(self, projection: dict, qds: dict, expected: set[str]) -> None:
        self.assertEqual(nested_ids(projection), expected)
        self.assertEqual({a["id"] for a in qds.get("assumptions_report", [])}, expected)

    def test_direct_nested_correction_uses_exact_parent_not_old_or_new_owner(self) -> None:
        for relevant, mixed in itertools.product((True, False), repeat=2):
            with self.subTest(relevant=relevant, mixed_old=mixed):
                documents = nested_documents(relevant=relevant, mixed_old=mixed)
                projection, qds = self.emitted(documents)
                self.assert_ids(projection, qds, {"A_new"} if relevant else set())
                self.assertEqual(qds["derived_from_evaluation_run_refs"], [OLD, NEW])
                self.assertEqual(len(qds["applied_corrections"]), 1)
                self.assertIn(NEW, qds["active_evaluation_run_refs"])

    def test_unreplaced_selected_child_survives_beside_foreign_replacement(self) -> None:
        documents = nested_documents(relevant=False, mixed_old=True)
        documents[1]["evaluation_runs"][0]["measurements"][0]["assumptions"].append(assumption("A_fresh"))
        projection, qds = self.emitted(documents)
        self.assert_ids(projection, qds, {"A_fresh"})

    def test_fresh_selected_measurement_assumption_needs_no_correction(self) -> None:
        documents = fixture()
        documents[1]["evaluation_runs"][0]["corrections"] = []
        documents[1]["evaluation_runs"][0]["measurements"][0]["assumptions"] = [assumption("A_fresh")]
        projection, qds = self.emitted(documents)
        self.assert_ids(projection, qds, {"A_fresh"})

    def test_same_measurement_id_in_another_owner_cannot_supply_parent_identity(self) -> None:
        documents = nested_documents(relevant=False)
        new = documents[1]["evaluation_runs"][0]
        sibling = control("M_old")
        new["measurements"].append(sibling)
        projection, qds = self.emitted(documents)
        self.assert_ids(projection, qds, set())

    def test_32_three_hop_whole_nested_exact_subject_cases(self) -> None:
        cases = 0
        for pattern in itertools.product(("whole", "nested"), repeat=3):
            for relevant, mixed in itertools.product((True, False), repeat=2):
                cases += 1
                with self.subTest(pattern=pattern, relevant=relevant, mixed_old=mixed):
                    documents = chain_documents(pattern, relevant=relevant, mixed_old=mixed)
                    projection, qds = self.emitted(documents)
                    self.assert_ids(projection, qds, {"A_chain_3"} if relevant else set())
                    self.assertEqual(len(qds["applied_corrections"]), 3)
                    self.assertEqual(len(qds["derived_from_evaluation_run_refs"]), 4)
        self.assertEqual(cases, 32)

    def test_whole_measurement_ancestry_survives_retired_intermediate_owners(self) -> None:
        documents = chain_documents(("whole", "whole", "whole"), relevant=True, mixed_old=False)
        for document in documents:
            for run in document["evaluation_runs"]:
                run["measurements"] = [row for row in run["measurements"]
                                       if not row["id"].startswith("M_chain_control_")]
        projection, qds = self.emitted(documents)
        self.assert_ids(projection, qds, {"A_chain_3"})
        self.assertEqual(qds["active_evaluation_run_refs"], [NEW])
        self.assertEqual(len(qds["derived_from_evaluation_run_refs"]), 4)

    def test_selected_original_parent_with_foreign_child_can_anchor_whole_replacement(self) -> None:
        documents = nested_documents(relevant=False, mixed_old=True)
        old, middle = documents[0]["evaluation_runs"][0], documents[1]["evaluation_runs"][0]
        middle["id"] = "EVAL_measurement_independent_2026-09-21"
        middle["run_date"] = "2026-09-21"
        middle["measurements"][0]["assumptions"].append(assumption("A_middle_fresh"))
        new = {"id": NEW, "run_date": "2026-09-23", "structure_ref": "synth4",
               "catalog_tasks_applied": ["T05"], "measurements": [measurement("M_terminal")]}
        new["measurements"][0]["assumptions"] = [assumption("A_terminal")]
        new["corrections"] = [correction(new, middle, middle["measurements"][0],
                                         new["measurements"][0], "measurements", "C_whole")]
        documents[0]["evaluation_runs"] = [old, middle]
        documents[1]["evaluation_runs"] = [new]
        documents[1]["qds_emission_contexts"][0]["source_evaluation_run_refs"] = [old["id"], middle["id"], NEW]
        projection, qds = self.emitted(documents)
        self.assert_ids(projection, qds, {"A_terminal"})

    def test_foreign_whole_parent_does_not_borrow_selected_nested_child(self) -> None:
        documents = nested_documents(relevant=True, mixed_old=True)
        old, middle = documents[0]["evaluation_runs"][0], documents[1]["evaluation_runs"][0]
        middle["id"] = "EVAL_measurement_foreign_2026-09-21"
        middle["run_date"] = "2026-09-21"
        middle["measurements"][0]["subject_ref"] = FOREIGN
        middle["measurements"].append(control("M_middle_control"))
        new = {"id": NEW, "run_date": "2026-09-23", "structure_ref": "synth4",
               "catalog_tasks_applied": ["T05"], "measurements": [measurement("M_terminal")]}
        new["measurements"][0]["assumptions"] = [assumption("A_terminal")]
        new["corrections"] = [correction(new, middle, middle["measurements"][0],
                                         new["measurements"][0], "measurements", "C_whole")]
        documents[0]["evaluation_runs"] = [old, middle]
        documents[1]["evaluation_runs"] = [new]
        documents[1]["qds_emission_contexts"][0]["source_evaluation_run_refs"] = [old["id"], middle["id"], NEW]
        projection, qds = self.emitted(documents)
        self.assert_ids(projection, qds, set())

    def test_dataset_parent_uses_owner_scoped_association_not_model_sibling(self) -> None:
        for associated in (True, False):
            with self.subTest(associated=associated), tempfile.TemporaryDirectory() as tmp:
                documents = nested_documents(relevant=False, mixed_old=True)
                old, new = documents[0]["evaluation_runs"][0], documents[1]["evaluation_runs"][0]
                add_dataset(documents, Path(tmp))
                dataset_row = copy.deepcopy(new["measurements"][1])
                dataset_row["id"] = "M_old_dataset"
                dataset_row["assumptions"] = [assumption("A_old")]
                old["measurements"][0] = dataset_row
                old["catalog_tasks_applied"].append("T13")
                association = documents[1]["qds_emission_contexts"][0]["dataset_associations"][0]
                if associated:
                    association = copy.deepcopy(association)
                    association.update(id="ASSOC_old_dataset", owner_evaluation_run_ref=OLD,
                                       scope_selectors=[dataset_row["scope_selector"]])
                    documents[1]["qds_emission_contexts"][0]["dataset_associations"].append(association)
                new["corrections"][0]["target_sha256"] = canonical_sha256(dataset_row["assumptions"][0])
                projection, qds = self.emitted(documents, root=Path(tmp))
                self.assert_ids(projection, qds, {"A_new"} if associated else set())
                self.assertEqual(len(qds["data_quality_summary"]["diagnostics"]), 7 if associated else 6)

    def test_live_emission_filters_before_assumption_aggregation(self) -> None:
        documents = nested_documents(relevant=False, mixed_old=True)
        documents[-1]["tools"] = yaml.safe_load((REPO / "ref/catalog.yaml").read_text())["tools"]
        for field, filename in (("tool_recommendations", "tool_recommendations.yaml"),
                                ("assumptions", "tool_assumptions.yaml")):
            documents[-1][field] = yaml.safe_load((REPO / "ref" / filename).read_text())[field]
        with mock.patch.object(contract, "_read_documents", return_value=copy.deepcopy(documents)):
            qds = qds_emit.emit_qds([], qds_id=QDS, structure_id="synth4")
        self.assertNotIn("A_new", {a["id"] for a in qds.get("assumptions_report", [])})
        self.assertTrue(qds["assumptions_report"], "Real applicable registry guidance must still be admitted")

    def test_corpus_accepts_filtered_output_and_rejects_wrong_exact_target_owner(self) -> None:
        documents = nested_documents(relevant=False, mixed_old=True)
        for document in documents:
            for run in document["evaluation_runs"]:
                run["eval_filename_stem"] = document["evaluation_runs"][0]["id"]
        projection, qds = self.emitted(documents)
        self.assert_ids(projection, qds, set())
        records = corpus_records(documents, qds)
        self.assertEqual(corpus_errors(records), [])
        documents[1]["evaluation_runs"][0]["corrections"][0]["target_evaluation_run_ref"] = NEW
        errors = corpus_errors(corpus_records(documents, qds))
        self.assertTrue(any("target" in error for error in errors), errors)

    def test_pinned_replay_rejects_reinjected_foreign_child_even_after_output_repin(self) -> None:
        documents = nested_documents(relevant=False, mixed_old=True)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            projection, qds = self.emitted(documents, root=root)
            self.assert_ids(projection, qds, set())
            documents[1]["qds_replay_pins"] = [pin_for(qds, projection)]
            for doc in documents:
                path = root / "data" / (doc["evaluation_runs"][0]["id"] + ".yaml")
                path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
            qds_path = root / "data" / (QDS + ".yaml")
            qds_path.write_text(trust._canonical_qds_text(qds))
            index = trust._load_eval_runs(root, [])
            _, errors = trust._rebuild_coverage(qds_path, qds, index, root)
            self.assertEqual(errors, [])
            forged = copy.deepcopy(qds)
            forged["assumptions_report"] = [assumption("A_new")]
            qds_path.write_text(trust._canonical_qds_text(forged))
            _, errors = trust._rebuild_coverage(qds_path, forged, index, root)
            self.assertTrue(any("canonical byte pin" in error for error in errors), errors)
            self.assertTrue(any("deterministic frozen contract-4 replay" in error for error in errors), errors)
            documents[1]["qds_replay_pins"][0]["canonical_qds_sha256"] = hashlib.sha256(
                trust._canonical_qds_text(forged).encode()).hexdigest()
            (root / "data" / (NEW + ".yaml")).write_text(yaml.safe_dump(documents[1], sort_keys=False, allow_unicode=True))
            index = trust._load_eval_runs(root, [])
            _, errors = trust._rebuild_coverage(qds_path, forged, index, root)
            self.assertFalse(any("canonical byte pin" in error for error in errors), errors)
            self.assertTrue(any("deterministic frozen contract-4 replay" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
