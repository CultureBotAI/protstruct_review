#!/usr/bin/env python3
"""Raw measurement-reference ancestry for corrected assumptions (#756).

Run, embedded and registry examples are schema-valid synthetic records. Original
explicit references constrain (and never replace) existing container ancestry;
changing or removing the successor reference cannot refresh historical scope.
No scientific executable or network call is used.
"""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import check_qds_trust_invariant as trust  # noqa: E402
import qds_emit  # noqa: E402
import qds_emit_contract_v4 as contract  # noqa: E402
from protstruct_review.models import Container  # noqa: E402
from qds_correction_projection import canonical_sha256  # noqa: E402
from test_qds_contract_v4 import NEW, OLD, QDS, SUBJECT, fixture, measurement, pin_for  # noqa: E402
from test_qds_measurement_assumption_ancestry import corpus_errors, corpus_records  # noqa: E402


FORMS = ("run", "embedded", "registry")
FOREIGN = "synthetic:model:foreign-explicit-reference"
COLLECTIONS = {"run": "assumptions", "embedded": "measurement_assumptions", "registry": "tool_assumptions"}


def assumption(row_id: str, ref: str | None, *, day: str | None = None) -> dict:
    row = {"id": row_id, "kind": "explicit", "scope": "measurement",
           "title": "Synthetic measured precondition", "description": "Verified only for the referenced evidence.",
           "status": "verified"}
    if ref is not None:
        row["measurement_ref"] = ref
    if day is not None:
        row.update(tool_ref="MolProbity (gold)", as_of_date=f"2026-09-{day}",
                   effective_at=f"2026-09-{day}T00:00:00+00:00")
    return row


def bound_measurement(*, relevant: bool) -> dict:
    row = measurement("M_bound_old", 0.2)
    row.update(metric_definition_ref="T05_rotamer_outlier", subject_ref=SUBJECT if relevant else FOREIGN)
    return row


def correction(owner: str, target: dict, successor: dict, collection: str, row_id: str = "C_explicit") -> dict:
    return {"id": row_id, "action": "replace", "target_collection": collection,
            "target_evaluation_run_ref": owner, "target_ref": target["id"],
            "target_sha256": canonical_sha256(target), "replacement_ref": successor["id"],
            "reason": "Synthetic raw-reference ancestry test.", "evidence_refs": ["ref/catalog.yaml"]}


def source_rows(documents: list[dict], form: str) -> tuple[dict, dict]:
    old, new = documents[0]["evaluation_runs"][-1], documents[1]["evaluation_runs"][0]
    if form == "run":
        return old["assumptions"][0], new["assumptions"][0]
    if form == "embedded":
        return old["measurements"][0]["assumptions"][0], new["measurements"][0]["assumptions"][0]
    return documents[1]["assumptions"][0], documents[1]["assumptions"][-1]


def documents_for(form: str, *, relevant: bool, locality: str = "local") -> list[dict]:
    documents = fixture()
    old, new = documents[0]["evaluation_runs"][0], documents[1]["evaluation_runs"][0]
    a_old = assumption("A_explicit_old", "M_bound_old", day="20" if form == "registry" else None)
    a_new = assumption("A_explicit_new", "M_new", day="23" if form == "registry" else None)
    if form == "registry":
        documents[1]["assumptions"] = [a_old, a_new]
        reference_owner, other_owner = new, old
    else:
        reference_owner, other_owner = old, new
        if form == "run":
            old["assumptions"], new["assumptions"] = [a_old], [a_new]
        else:
            old["measurements"][0]["assumptions"] = [a_old]
            new["measurements"][0]["assumptions"] = [a_new]
    if locality == "local":
        reference_owner["measurements"].append(bound_measurement(relevant=relevant))
    elif locality in {"global", "ambiguous"}:
        other_owner["measurements"].append(bound_measurement(relevant=relevant))
        if locality == "ambiguous":
            earlier = {"id": "EVAL_explicit_global_2026-09-19", "run_date": "2026-09-19",
                       "structure_ref": "synth4", "catalog_tasks_applied": ["T05"],
                       "measurements": [bound_measurement(relevant=True)]}
            documents[0]["evaluation_runs"].insert(0, earlier)
            documents[1]["qds_emission_contexts"][0]["source_evaluation_run_refs"].insert(0, earlier["id"])
    elif locality != "missing":
        raise AssertionError(locality)
    new["corrections"] = [correction(reference_owner["id"], a_old, a_new, COLLECTIONS[form])]
    return documents


def projected_ids(projection: dict, form: str) -> set[str]:
    if form == "registry":
        # The registry snapshot remains immutable; active selection is tested in
        # the actual report. Run/embedded assertions below inspect admitted rows.
        return set()
    if form == "run":
        return {a["id"] for run in projection["runs"] for a in run.get("assumptions", [])}
    return {a["id"] for run in projection["runs"] for m in run.get("measurements", [])
            for a in m.get("assumptions", [])}


class ExplicitAssumptionAncestryTests(unittest.TestCase):
    def emit(self, documents: list[dict], *, root: Path = REPO) -> tuple[dict, dict]:
        before = copy.deepcopy(documents)
        for doc in documents:
            Container.model_validate(doc)
        projection = contract.prepare_projection(documents, QDS, "synth4", root)
        qds = contract.emit_projection(projection)
        Container.model_validate({"quality_data_sheets": [qds]})
        self.assertEqual(documents, before)
        return projection, qds

    def assert_scope(self, documents: list[dict], form: str, *, relevant: bool) -> tuple[dict, dict]:
        projection, qds = self.emit(documents)
        expected = {"A_explicit_new"} if relevant else set()
        self.assertEqual({a["id"] for a in qds.get("assumptions_report", [])}, expected)
        if form != "registry":
            self.assertEqual(projected_ids(projection, form), expected)
        self.assertEqual(len(qds["applied_corrections"]),
                         sum(len(run.get("corrections", [])) for doc in documents for run in doc["evaluation_runs"]))
        return projection, qds

    def test_explicit_original_binding_constrains_all_three_valid_source_forms(self) -> None:
        for form in FORMS:
            for relevant in (True, False):
                with self.subTest(form=form, relevant=relevant):
                    self.assert_scope(documents_for(form, relevant=relevant), form, relevant=relevant)

    def test_raw_local_binding_wins_over_opposite_subject_same_id_elsewhere(self) -> None:
        for form in FORMS:
            for relevant in (True, False):
                with self.subTest(form=form, local_relevant=relevant):
                    documents = documents_for(form, relevant=relevant)
                    other = documents[0]["evaluation_runs"][0] if form == "registry" else documents[1]["evaluation_runs"][0]
                    other["measurements"].append(bound_measurement(relevant=not relevant))
                    self.assert_scope(documents, form, relevant=relevant)

    def test_unique_global_raw_binding_is_used_only_when_no_local_target_exists(self) -> None:
        for form in FORMS:
            for relevant in (True, False):
                with self.subTest(form=form, relevant=relevant):
                    self.assert_scope(documents_for(form, relevant=relevant, locality="global"), form, relevant=relevant)

    def test_missing_or_ambiguous_original_ref_never_falls_back_to_selected_carrier(self) -> None:
        for form in FORMS:
            for locality in ("missing", "ambiguous"):
                with self.subTest(form=form, locality=locality):
                    documents = documents_for(form, relevant=True, locality=locality)
                    before = copy.deepcopy(documents)
                    try:
                        self.assert_scope(documents, form, relevant=False)
                    except contract.QdsCompletenessError:
                        # Explicit rejection is also fail-closed; silently
                        # choosing the parent or one global candidate is not.
                        pass
                    self.assertEqual(documents, before)

    def test_removing_successor_reference_cannot_escape_original_foreign_binding(self) -> None:
        for form in FORMS:
            with self.subTest(form=form):
                documents = documents_for(form, relevant=False)
                source_rows(documents, form)[1].pop("measurement_ref")
                self.assert_scope(documents, form, relevant=False)

    def test_selected_reference_does_not_override_foreign_containing_measurement(self) -> None:
        documents = documents_for("embedded", relevant=True)
        documents[0]["evaluation_runs"][0]["measurements"][0]["subject_ref"] = FOREIGN
        self.assert_scope(documents, "embedded", relevant=False)

    def test_selected_global_reference_does_not_override_foreign_run_ancestry(self) -> None:
        documents = documents_for("run", relevant=True, locality="global")
        documents[0]["evaluation_runs"][0]["measurements"][0]["subject_ref"] = FOREIGN
        self.assert_scope(documents, "run", relevant=False)

    def test_retired_selected_original_measurement_remains_historical_anchor(self) -> None:
        for form in FORMS:
            with self.subTest(form=form):
                # Registry rows resolve globally to OLD; a same-owner scalar
                # withdrawal is intentionally not a legal correction operation.
                locality = "global" if form == "registry" else "local"
                documents = documents_for(form, relevant=True, locality=locality)
                old, new = documents[0]["evaluation_runs"][0], documents[1]["evaluation_runs"][0]
                target = next(m for m in old["measurements"] if m["id"] == "M_bound_old")
                new["corrections"].append({"id": "C_retire_original_operand", "action": "withdraw",
                    "target_collection": "measurements", "target_evaluation_run_ref": OLD,
                    "target_ref": target["id"], "target_sha256": canonical_sha256(target),
                    "reason": "Old selected observation retired separately; raw identity survives.",
                    "evidence_refs": ["ref/catalog.yaml"]})
                projection, _ = self.assert_scope(documents, form, relevant=True)
                self.assertFalse(any(m["id"] == "M_bound_old" for run in projection["runs"] for m in run["measurements"]))

    def test_two_hop_chain_cannot_reset_the_original_explicit_binding(self) -> None:
        for form in FORMS:
            for relevant in (True, False):
                with self.subTest(form=form, relevant=relevant):
                    documents = documents_for(form, relevant=relevant)
                    new = documents[1]["evaluation_runs"][0]
                    a_old, a_new = source_rows(documents, form)
                    if form == "registry":
                        a_mid = assumption("A_explicit_mid", "M_new", day="21")
                        documents[1]["assumptions"].insert(1, a_mid)
                        new["corrections"] = [correction(NEW, a_old, a_mid, COLLECTIONS[form], "C_first"),
                                              correction(NEW, a_mid, a_new, COLLECTIONS[form], "C_second")]
                    else:
                        middle = {"id": "EVAL_explicit_middle_2026-09-21", "run_date": "2026-09-21",
                                  "structure_ref": "synth4", "catalog_tasks_applied": ["T05"],
                                  "measurements": [measurement("M_mid")]}
                        a_mid = assumption("A_explicit_mid", "M_mid")
                        if form == "run":
                            middle["assumptions"] = [a_mid]
                        else:
                            middle["measurements"][0]["assumptions"] = [a_mid]
                        middle["corrections"] = [correction(OLD, a_old, a_mid, COLLECTIONS[form], "C_first")]
                        new["corrections"] = [correction(middle["id"], a_mid, a_new, COLLECTIONS[form], "C_second")]
                        documents[0]["evaluation_runs"].append(middle)
                        documents[1]["qds_emission_contexts"][0]["source_evaluation_run_refs"].insert(1, middle["id"])
                    self.assert_scope(documents, form, relevant=relevant)

    def test_live_emission_does_not_read_successor_ref_as_new_scope_authority(self) -> None:
        for form in FORMS:
            with self.subTest(form=form):
                documents = documents_for(form, relevant=False)
                custom_registry = copy.deepcopy(documents[1]["assumptions"])
                documents[1]["tools"] = yaml.safe_load((REPO / "ref/catalog.yaml").read_text())["tools"]
                for field, filename in (("tool_recommendations", "tool_recommendations.yaml"),
                                        ("assumptions", "tool_assumptions.yaml")):
                    documents[1][field] = yaml.safe_load((REPO / "ref" / filename).read_text())[field]
                documents[1]["assumptions"].extend(custom_registry)
                before = copy.deepcopy(documents)
                with mock.patch.object(contract, "_read_documents", return_value=documents):
                    qds = qds_emit.emit_qds([], qds_id=QDS, structure_id="synth4")
                self.assertNotIn("A_explicit_new", {a["id"] for a in qds.get("assumptions_report", [])})
                self.assertTrue(qds.get("assumptions_report"), "Applicable live tool caveats must survive")
                self.assertEqual(documents, before)

    def test_current_successor_reference_still_requires_active_dependency(self) -> None:
        for form in FORMS:
            with self.subTest(form=form):
                documents = documents_for(form, relevant=True)
                source_rows(documents, form)[1]["measurement_ref"] = "M_missing_successor"
                with self.assertRaises(contract.QdsCompletenessError):
                    self.emit(documents)

    def test_corpus_accepts_filtered_scope_and_rejects_forged_raw_target_hash(self) -> None:
        for form in FORMS:
            with self.subTest(form=form):
                documents = documents_for(form, relevant=False)
                for doc in documents:
                    for run in doc["evaluation_runs"]:
                        run["eval_filename_stem"] = doc["evaluation_runs"][0]["id"]
                _, qds = self.assert_scope(documents, form, relevant=False)
                self.assertEqual(corpus_errors(corpus_records(documents, qds)), [])
                documents[1]["evaluation_runs"][0]["corrections"][0]["target_sha256"] = "0" * 64
                errors = corpus_errors(corpus_records(documents, qds))
                self.assertTrue(any("target_sha256" in error for error in errors), errors)

    def test_pinned_replay_rejects_laundered_status_even_with_new_output_pin(self) -> None:
        for form in FORMS:
            with self.subTest(form=form), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "data").mkdir()
                documents = documents_for(form, relevant=False)
                projection, qds = self.emit(documents, root=root)
                self.assertNotIn("A_explicit_new", {a["id"] for a in qds.get("assumptions_report", [])})
                documents[1]["qds_replay_pins"] = [pin_for(qds, projection)]
                for doc in documents:
                    (root / "data" / (doc["evaluation_runs"][0]["id"] + ".yaml")).write_text(
                        yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
                qds_path = root / "data" / (QDS + ".yaml")
                qds_path.write_text(trust._canonical_qds_text(qds))
                index = trust._load_eval_runs(root, [])
                _, errors = trust._rebuild_coverage(qds_path, qds, index, root)
                self.assertEqual(errors, [])
                forged = copy.deepcopy(qds)
                forged["assumptions_report"] = [copy.deepcopy(source_rows(documents, form)[1])]
                qds_path.write_text(trust._canonical_qds_text(forged))
                documents[1]["qds_replay_pins"][0]["canonical_qds_sha256"] = hashlib.sha256(
                    trust._canonical_qds_text(forged).encode()).hexdigest()
                (root / "data" / (NEW + ".yaml")).write_text(yaml.safe_dump(documents[1], sort_keys=False, allow_unicode=True))
                index = trust._load_eval_runs(root, [])
                _, errors = trust._rebuild_coverage(qds_path, forged, index, root)
                self.assertFalse(any("canonical byte pin" in error for error in errors), errors)
                self.assertTrue(any("deterministic frozen contract-4 replay" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
