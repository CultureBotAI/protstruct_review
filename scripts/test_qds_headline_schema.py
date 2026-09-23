#!/usr/bin/env python3
"""Schema-valid headline-assumption correction acceptance (#758/#756).

Exercise the public schema, live emitter, corpus relationships and pinned replay,
not only permissive dictionaries passed to private projection helpers. All inputs
are synthetic; no scientific executable or external service is invoked.
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
from protstruct_review.models import Assumption, Container  # noqa: E402
from qds_correction_projection import canonical_sha256  # noqa: E402
from test_qds_contract_v4 import NEW, OLD, QDS, pin_for  # noqa: E402
from test_qds_explicit_assumption_ancestry import FOREIGN, documents_for  # noqa: E402
from test_qds_measurement_assumption_ancestry import corpus_errors, corpus_records  # noqa: E402


SCHEMA = yaml.safe_load((REPO / "schemas/protstruct_review.yaml").read_text())


def headline_documents(kind: str, *, relevant: bool = True) -> list[dict]:
    documents = documents_for("run", relevant=relevant)
    old, new = documents[0]["evaluation_runs"][0], documents[1]["evaluation_runs"][0]
    for run, suffix in ((old, "old"), (new, "new")):
        run["headline_findings"] = [{
            "id": f"F_{suffix}", "catalog_task_refs": ["T05"],
            "supporting_measurement_refs": [f"M_{suffix}"],
            "assumptions": run.pop("assumptions"),
        }]
    target, successor = old["headline_findings"][0], new["headline_findings"][0]
    collection = "headline_findings"
    if kind == "nested":
        target, successor = target["assumptions"][0], successor["assumptions"][0]
        collection = "headline_assumptions"
    elif kind != "whole":
        raise AssertionError(kind)
    new["corrections"][0].update(target_collection=collection, target_ref=target["id"],
                                 target_sha256=canonical_sha256(target), replacement_ref=successor["id"])
    return documents


def headline_assumption_ids(projection: dict) -> set[str]:
    return {a["id"] for run in projection["runs"] for finding in run.get("headline_findings", [])
            for a in finding.get("assumptions", [])}


class HeadlineSchemaTests(unittest.TestCase):
    def emit(self, documents: list[dict], *, root: Path = REPO) -> tuple[dict, dict]:
        before = copy.deepcopy(documents)
        for document in documents:
            Container.model_validate(document)
        projection = contract.prepare_projection(documents, QDS, "synth4", root)
        qds = contract.emit_projection(projection)
        Container.model_validate({"quality_data_sheets": [qds]})
        self.assertEqual(documents, before)
        return projection, qds

    def assert_ids(self, projection: dict, qds: dict, expected: set[str]) -> None:
        self.assertEqual(headline_assumption_ids(projection), expected)
        self.assertEqual({row["id"] for row in qds.get("assumptions_report", [])}, expected)

    def test_canonical_schema_and_generated_model_declare_typed_nested_assumptions(self) -> None:
        attributes = SCHEMA["classes"]["HeadlineFinding"]["attributes"]
        self.assertIn("assumptions", attributes)
        field = attributes["assumptions"]
        self.assertEqual(field["range"], "Assumption")
        self.assertTrue(field["multivalued"])
        self.assertTrue(field["inlined_as_list"])
        document = headline_documents("nested")[0]
        parsed = Container.model_validate(document)
        finding = parsed.evaluation_runs[0].headline_findings[0]
        self.assertEqual(len(finding.assumptions), 1)
        self.assertIsInstance(finding.assumptions[0], Assumption)
        self.assertEqual(finding.assumptions[0].measurement_ref, "M_bound_old")

    def test_nested_schema_fields_and_required_headline_task_refs_are_enforced(self) -> None:
        for mutation in ("bad_status", "missing_assumption_title", "missing_catalog_task_refs"):
            with self.subTest(mutation=mutation):
                document = headline_documents("nested")[0]
                finding = document["evaluation_runs"][0]["headline_findings"][0]
                if mutation == "bad_status":
                    finding["assumptions"][0]["status"] = "synthetic_invalid_status"
                elif mutation == "missing_assumption_title":
                    finding["assumptions"][0].pop("title")
                else:
                    finding.pop("catalog_task_refs")
                with self.assertRaises(ValueError):
                    Container.model_validate(document)

    def test_whole_and_nested_corrections_emit_schema_valid_current_assumptions(self) -> None:
        for kind in ("whole", "nested"):
            with self.subTest(kind=kind):
                documents = headline_documents(kind)
                projection, qds = self.emit(documents)
                self.assert_ids(projection, qds, {"A_explicit_new"})
                self.assertEqual(qds["derived_from_evaluation_run_refs"], [OLD, NEW])
                self.assertEqual(qds["applied_corrections"][0]["target_collection"],
                                 "headline_findings" if kind == "whole" else "headline_assumptions")

    def test_default_live_emission_supports_both_schema_valid_correction_forms(self) -> None:
        for kind in ("whole", "nested"):
            with self.subTest(kind=kind):
                documents = headline_documents(kind)
                documents[1]["tools"] = yaml.safe_load((REPO / "ref/catalog.yaml").read_text())["tools"]
                for field, filename in (("tool_recommendations", "tool_recommendations.yaml"),
                                        ("assumptions", "tool_assumptions.yaml")):
                    documents[1][field] = yaml.safe_load((REPO / "ref" / filename).read_text())[field]
                for document in documents:
                    Container.model_validate(document)
                before = copy.deepcopy(documents)
                with mock.patch.object(contract, "_read_documents", return_value=documents):
                    qds = qds_emit.emit_qds([], qds_id=QDS, structure_id="synth4")
                Container.model_validate({"quality_data_sheets": [qds]})
                ids = {row["id"] for row in qds["assumptions_report"]}
                self.assertIn("A_explicit_new", ids)
                self.assertNotIn("A_explicit_old", ids)
                self.assertEqual(qds["emitter_contract_version"], "4")
                self.assertEqual(documents, before)

    def test_selected_headline_support_cannot_relabel_original_foreign_measurement_binding(self) -> None:
        for remove_successor_ref in (False, True):
            with self.subTest(remove_successor_ref=remove_successor_ref):
                documents = headline_documents("nested", relevant=False)
                if remove_successor_ref:
                    documents[1]["evaluation_runs"][0]["headline_findings"][0]["assumptions"][0].pop("measurement_ref")
                projection, qds = self.emit(documents)
                self.assert_ids(projection, qds, set())
                self.assertIn(OLD, qds["active_evaluation_run_refs"])
                self.assertIn(NEW, qds["active_evaluation_run_refs"])

    def test_whole_parent_applicability_does_not_override_fresh_child_foreign_binding(self) -> None:
        documents = headline_documents("whole")
        old, new = documents[0]["evaluation_runs"][0], documents[1]["evaluation_runs"][0]
        next(m for m in old["measurements"] if m["id"] == "M_bound_old")["subject_ref"] = FOREIGN
        new["headline_findings"][0]["assumptions"][0]["measurement_ref"] = "M_bound_old"
        projection, qds = self.emit(documents)
        self.assert_ids(projection, qds, set())

    def test_corpus_accepts_typed_headlines_and_rejects_wrong_exact_correction_owner(self) -> None:
        for kind in ("whole", "nested"):
            with self.subTest(kind=kind):
                documents = headline_documents(kind)
                for document in documents:
                    for run in document["evaluation_runs"]:
                        run["eval_filename_stem"] = document["evaluation_runs"][0]["id"]
                _, qds = self.emit(documents)
                self.assertEqual(corpus_errors(corpus_records(documents, qds)), [])
                documents[1]["evaluation_runs"][0]["corrections"][0]["target_evaluation_run_ref"] = NEW
                errors = corpus_errors(corpus_records(documents, qds))
                self.assertTrue(any("target" in error for error in errors), errors)

    def test_source_owned_pin_replays_and_rejects_modified_headline_assumption_after_repin(self) -> None:
        for kind in ("whole", "nested"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                documents = headline_documents(kind)
                root = Path(tmp)
                (root / "data").mkdir()
                projection, qds = self.emit(documents, root=root)
                self.assert_ids(projection, qds, {"A_explicit_new"})
                documents[1]["qds_replay_pins"] = [pin_for(qds, projection)]
                for document in documents:
                    (root / "data" / (document["evaluation_runs"][0]["id"] + ".yaml")).write_text(
                        yaml.safe_dump(document, sort_keys=False, allow_unicode=True))
                path = root / "data" / (QDS + ".yaml")
                path.write_text(trust._canonical_qds_text(qds))
                index = trust._load_eval_runs(root, [])
                _, errors = trust._rebuild_coverage(path, qds, index, root)
                self.assertEqual(errors, [])
                forged = copy.deepcopy(qds)
                forged["assumptions_report"][0]["measurement_ref"] = "M_old"
                path.write_text(trust._canonical_qds_text(forged))
                documents[1]["qds_replay_pins"][0]["canonical_qds_sha256"] = hashlib.sha256(
                    trust._canonical_qds_text(forged).encode()).hexdigest()
                (root / "data" / (NEW + ".yaml")).write_text(yaml.safe_dump(documents[1], sort_keys=False, allow_unicode=True))
                index = trust._load_eval_runs(root, [])
                _, errors = trust._rebuild_coverage(path, forged, index, root)
                self.assertFalse(any("canonical byte pin" in error for error in errors), errors)
                self.assertTrue(any("deterministic frozen contract-4 replay" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
