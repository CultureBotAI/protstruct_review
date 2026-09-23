#!/usr/bin/env python3
"""Historical dataset bindings survive correction/owner retirement (#757/#759).

The MTZ payload is synthetic and all fixture file I/O is in memory. No scientific
executable runs, and no temporary files or repository data are written.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
import hashlib
import itertools
from pathlib import Path
import sys
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
from test_qds_contract_v4 import NEW, OLD, QDS, add_dataset, fixture, pin_for  # noqa: E402


PAYLOAD = b"Synthetic digest fixture only, not parsed as MTZ.\n"
DATASET_PATH = REPO / "data/synthetic.mtz"


@contextmanager
def memory_files():
    """Intercept only virtual fixture paths; retained source reads remain real."""
    contents = {DATASET_PATH: PAYLOAD}
    original_bytes, original_text = Path.read_bytes, Path.read_text
    original_file, original_exists = Path.is_file, Path.exists

    def read_bytes(path):
        return contents[path] if path in contents else original_bytes(path)

    def read_text(path, *args, **kwargs):
        return contents[path].decode() if path in contents else original_text(path, *args, **kwargs)

    with (mock.patch.object(Path, "read_bytes", read_bytes),
          mock.patch.object(Path, "read_text", read_text),
          mock.patch.object(Path, "is_file", lambda path: path in contents or original_file(path)),
          mock.patch.object(Path, "exists", lambda path: path in contents or original_exists(path))):
        yield contents


def assumption(row_id: str) -> dict:
    return {"id": row_id, "kind": "implicit", "scope": "tool", "title": "Synthetic binding",
            "description": "Synthetic dataset ancestry, not an actual scientific result.",
            "status": "verified"}


def dataset_chain(pattern: tuple[str, ...] = ("whole",)) -> list[dict]:
    """Each run has only one same-MTZ T13 row and an exact owner binding."""
    documents = fixture()
    # add_dataset's only writes create this known synthetic fixture. Intercept
    # them here rather than writing a fake MTZ into the repository or /tmp.
    with (mock.patch.object(Path, "mkdir"),
          mock.patch.object(Path, "write_bytes", return_value=len(PAYLOAD))):
        add_dataset(documents, REPO)
    old, new = documents[0]["evaluation_runs"][0], documents[1]["evaluation_runs"][0]
    template = copy.deepcopy(new["corrections"][0])
    measured = copy.deepcopy(next(row for row in new["measurements"] if row["id"] == "M_dataset_0"))
    middle = [{"id": f"EVAL_dataset_history_2026-09-{21 + index}",
               "run_date": f"2026-09-{21 + index}", "structure_ref": "synth4"}
              for index in range(len(pattern) - 1)]
    runs = [old, *middle, new]
    context = documents[1]["qds_emission_contexts"][0]
    association = copy.deepcopy(context["dataset_associations"][0])
    association["scope_selectors"] = [measured["scope_selector"]]
    context["dataset_associations"] = []
    for index, run in enumerate(runs):
        row = {**copy.deepcopy(measured), "id": f"M_dataset_{index}",
               "assumptions": [assumption(f"A_dataset_{index}")]}
        run["measurements"] = [row]
        run["catalog_tasks_applied"] = ["T13"]
        run.pop("corrections", None)
        context["dataset_associations"].append({
            **copy.deepcopy(association), "id": f"ASSOC_dataset_{index}",
            "owner_evaluation_run_ref": run["id"],
        })
    for index, kind in enumerate(pattern):
        previous, current = runs[index:index + 2]
        target, successor = previous["measurements"][0], current["measurements"][0]
        collection = "measurements"
        if kind == "nested":
            target, successor = target["assumptions"][0], successor["assumptions"][0]
            collection = "measurement_assumptions"
        current["corrections"] = [{
            **template, "id": f"C_dataset_{index}", "target_collection": collection,
            "target_evaluation_run_ref": previous["id"], "target_ref": target["id"],
            "target_sha256": canonical_sha256(target), "replacement_ref": successor["id"],
        }]
    documents[0]["evaluation_runs"] = runs[:-1]
    context["source_evaluation_run_refs"] = [run["id"] for run in runs]
    for document in documents:
        for run in document["evaluation_runs"]:
            run["eval_filename_stem"] = document["evaluation_runs"][0]["id"]
    return documents


def corrected_out_of_scope_dataset(field: str = "stage", value: str = "final") -> list[dict]:
    """A retired bad Wilson row cannot veto its valid same-dataset sibling."""
    documents = dataset_chain()
    old, new = documents[0]["evaluation_runs"][0], documents[1]["evaluation_runs"][0]
    retired = old["measurements"][0]
    sibling = copy.deepcopy(retired)
    sibling.update(id="M_old_aimless", metric_definition_ref="T13_aimless_status",
                   oracle_tool_ref="CCP4 aimless", scope_selector="all input reflections",
                   oracle_measure={"value_text": "unavailable — synthetic input"})
    sibling.pop("assumptions")
    old["measurements"].append(sibling)
    retired[field] = value
    new["corrections"][0]["target_sha256"] = canonical_sha256(retired)
    documents[1]["qds_emission_contexts"][0]["dataset_associations"][0][
        "scope_selectors"] = ["all input reflections"]
    return documents


def replay_index(documents: list[dict]) -> dict:
    """Use the same metadata class as canonical source discovery, without files."""
    index = {}
    for document in documents:
        for run in document["evaluation_runs"]:
            index[run["id"]] = [trust.EvalRunSource(
                run=run, structures=tuple(document.get("structures", [])),
                tools=tuple(document.get("tools", [])),
                tool_recommendations=tuple(document.get("tool_recommendations", [])),
                assumptions=tuple(document.get("assumptions", [])),
                qds_emission_contexts=tuple(document.get("qds_emission_contexts", [])),
                has_tool_recommendations="tool_recommendations" in document,
                has_assumptions="assumptions" in document,
                qds_replay_pins=tuple(document.get("qds_replay_pins", [])),
                source_document=copy.deepcopy(document),
            )]
    return index


def corpus_errors(documents: list[dict], qds: dict) -> list[str]:
    records = [(Path("data/test") / (document["evaluation_runs"][0]["id"] + ".yaml"), document)
               for document in documents]
    records.append((Path("data/test") / (QDS + ".yaml"), {"quality_data_sheets": [qds]}))
    indices = integrity.build_corpus_indices(records)
    errors = integrity.check_duplicate_ids(indices)
    for path, document in records:
        errors.extend(integrity.check_corpus_refs(document, path, indices))
    return errors


class HistoricalDatasetAncestryTests(unittest.TestCase):
    def emitted(self, documents: list[dict]) -> tuple[dict, dict]:
        before = copy.deepcopy(documents)
        for document in documents:
            Container.model_validate(document)
        projection = contract.prepare_projection(documents, QDS, "synth4")
        qds = contract.emit_projection(projection)
        Container.model_validate({"quality_data_sheets": [qds]})
        self.assertEqual(documents, before, "Historical association/target bytes remain immutable")
        return projection, qds

    def assert_terminal(self, projection: dict, qds: dict, terminal: int) -> None:
        expected = {f"A_dataset_{terminal}"}
        self.assertEqual({row["id"] for row in qds.get("assumptions_report", [])}, expected)
        self.assertEqual({a["id"] for run in projection["runs"] for m in run["measurements"]
                          for a in m.get("assumptions", [])}, expected)
        self.assertEqual(qds["data_quality_summary"]["wilson_b"]["source_measurement_ref"],
                         f"M_dataset_{terminal}")

    def test_whole_replacement_retains_assumption_and_only_active_output_binding(self) -> None:
        with memory_files():
            documents = dataset_chain()
            projection, qds = self.emitted(documents)
            self.assert_terminal(projection, qds, 1)
            self.assertEqual(qds["active_evaluation_run_refs"], [NEW])
            self.assertEqual(qds["derived_from_evaluation_run_refs"], [OLD, NEW])
            self.assertEqual([a["owner_evaluation_run_ref"] for a in qds["dataset_associations"]], [NEW])
            self.assertEqual(len(projection["context"]["dataset_associations"]), 2)
            self.assertEqual(qds["data_quality_summary"]["wilson_b"]["subject_ref"],
                             "mtz:sha256:" + hashlib.sha256(PAYLOAD).hexdigest())

    def test_all_eight_three_hop_whole_nested_chains(self) -> None:
        with memory_files():
            for pattern in itertools.product(("whole", "nested"), repeat=3):
                with self.subTest(pattern=pattern):
                    documents = dataset_chain(pattern)
                    projection, qds = self.emitted(documents)
                    self.assert_terminal(projection, qds, 3)
                    self.assertEqual(len(qds["applied_corrections"]), 3)
                    self.assertEqual(len(qds["derived_from_evaluation_run_refs"]), 4)
                    active = {run["id"] for run in projection["runs"] if run["measurements"]}
                    self.assertEqual({a["owner_evaluation_run_ref"] for a in qds["dataset_associations"]}, active)

    def test_explicitly_withdrawn_intermediate_owner_remains_historical_anchor(self) -> None:
        with memory_files():
            documents = dataset_chain(("whole", "whole", "whole"))
            middle = documents[0]["evaluation_runs"][1]
            new = documents[1]["evaluation_runs"][0]
            new["corrections"].append({
                "id": "C_retire_middle", "action": "withdraw", "target_collection": "evaluation_run",
                "target_evaluation_run_ref": middle["id"], "target_ref": middle["id"],
                "target_sha256": canonical_sha256(middle), "reason": "Retired synthetic carrier.",
                "evidence_refs": ["ref/research/synthetic_active_site_review_2026-09-23.md"],
            })
            projection, qds = self.emitted(documents)
            self.assert_terminal(projection, qds, 3)
            self.assertEqual(qds["active_evaluation_run_refs"], [NEW])
            self.assertIn(middle["id"], qds["derived_from_evaluation_run_refs"])
            self.assertEqual([a["owner_evaluation_run_ref"] for a in qds["dataset_associations"]], [NEW])

    def test_missing_original_binding_cannot_borrow_successor_binding(self) -> None:
        with memory_files():
            documents = dataset_chain()
            documents[1]["qds_emission_contexts"][0]["dataset_associations"].pop(0)
            projection, qds = self.emitted(documents)
            self.assertEqual(qds.get("assumptions_report", []), [])
            self.assertEqual(projection["runs"][0]["measurements"][0].get("assumptions", []), [])
            self.assertEqual(qds["data_quality_summary"]["wilson_b"]["source_measurement_ref"], "M_dataset_1")

    def test_active_binding_selectors_intersect_surviving_exact_owner_rows(self) -> None:
        with memory_files():
            documents = dataset_chain()
            old = documents[0]["evaluation_runs"][0]
            other = copy.deepcopy(old["measurements"][0])
            other.update(id="M_old_aimless", metric_definition_ref="T13_aimless_status",
                         oracle_tool_ref="CCP4 aimless", scope_selector="all input reflections",
                         oracle_measure={"value_text": "unavailable — synthetic input"})
            other.pop("assumptions")
            old["measurements"].append(other)
            context = documents[1]["qds_emission_contexts"][0]
            context["dataset_associations"][0]["scope_selectors"].append("all input reflections")
            projection, qds = self.emitted(documents)
            self.assert_terminal(projection, qds, 1)
            active_old = next(a for a in qds["dataset_associations"] if a["owner_evaluation_run_ref"] == OLD)
            self.assertEqual(active_old["scope_selectors"], ["all input reflections"])
            self.assertEqual(context["dataset_associations"][0]["scope_selectors"],
                             ["/*/*/[F,SIGF]", "all input reflections"])

    def test_invalid_historical_bindings_fail_before_ancestry_admission(self) -> None:
        mutations = (
            ("owner_evaluation_run_ref", "EVAL_missing_2026-09-19"),
            ("owner_evaluation_run_ref", NEW),
            ("scope_selectors", ["foreign columns"]),
            ("scope_selectors", ["/*/*/[F,SIGF]", "unused historical selector"]),
            ("model_subject_ref", "foreign-model"),
            ("catalog_task_ref", "T05"), ("stage", "final"), ("scope", "complex"),
            ("dataset_path", "../outside.mtz"), ("dataset_subject_ref", "mtz:sha256:" + "0" * 64),
        )
        with memory_files():
            for field, value in mutations:
                with self.subTest(field=field, value=value):
                    documents = dataset_chain()
                    documents[1]["qds_emission_contexts"][0]["dataset_associations"][0][field] = value
                    with self.assertRaises(contract.QdsCompletenessError):
                        contract.prepare_projection(documents, QDS, "synth4")
            documents = dataset_chain()
            historical = documents[1]["qds_emission_contexts"][0]["dataset_associations"][0]
            historical.update(dataset_sha256="0" * 64, dataset_subject_ref="mtz:sha256:" + "0" * 64)
            with self.assertRaisesRegex(contract.QdsCompletenessError, "bytes do not match"):
                contract.prepare_projection(documents, QDS, "synth4")

    def test_live_emission_keeps_corrected_dataset_assumption(self) -> None:
        with memory_files():
            documents = dataset_chain()
            documents[-1]["tools"] = yaml.safe_load((REPO / "ref/catalog.yaml").read_text())["tools"]
            for field, filename in (("tool_recommendations", "tool_recommendations.yaml"),
                                    ("assumptions", "tool_assumptions.yaml")):
                documents[-1][field] = yaml.safe_load((REPO / "ref" / filename).read_text())[field]
            with mock.patch.object(contract, "_read_documents", return_value=copy.deepcopy(documents)):
                qds = qds_emit.emit_qds([], qds_id=QDS, structure_id="synth4")
            ids = {row["id"] for row in qds.get("assumptions_report", [])}
            self.assertIn("A_dataset_1", ids)
            self.assertNotIn("A_dataset_0", ids)

    def test_corpus_accepts_historical_binding_and_rejects_wrong_owner(self) -> None:
        with memory_files():
            documents = dataset_chain()
            _, qds = self.emitted(documents)
            self.assertEqual(corpus_errors(documents, qds), [])
            documents[1]["qds_emission_contexts"][0]["dataset_associations"][0][
                "owner_evaluation_run_ref"] = "EVAL_missing_2026-09-19"
            errors = corpus_errors(documents, qds)
            self.assertTrue(any("dataset association owner" in error for error in errors), errors)

    def test_pinned_replay_requires_corrected_assumption_even_after_output_repin(self) -> None:
        with memory_files() as contents:
            documents = dataset_chain()
            projection, qds = self.emitted(documents)
            documents[1]["qds_replay_pins"] = [pin_for(qds, projection)]
            qds_path = REPO / "data/test" / (QDS + ".yaml")
            contents[qds_path] = trust._canonical_qds_text(qds).encode()
            _, errors = trust._rebuild_coverage(qds_path, qds, replay_index(documents), REPO)
            self.assertEqual(errors, [])
            forged = copy.deepcopy(qds)
            forged["assumptions_report"] = []
            contents[qds_path] = trust._canonical_qds_text(forged).encode()
            documents[1]["qds_replay_pins"][0]["canonical_qds_sha256"] = hashlib.sha256(contents[qds_path]).hexdigest()
            _, errors = trust._rebuild_coverage(qds_path, forged, replay_index(documents), REPO)
            self.assertFalse(any("canonical byte pin" in error for error in errors), errors)
            self.assertTrue(any("deterministic frozen contract-4 replay" in error for error in errors), errors)

    def test_corrected_out_of_scope_raw_rows_do_not_veto_valid_sibling_binding(self) -> None:
        for field, value in (("stage", "final"), ("scope", "complex"),
                             ("scope_selector", "incorrect historical columns")):
            with self.subTest(field=field), memory_files():
                documents = corrected_out_of_scope_dataset(field, value)
                projection, qds = self.emitted(documents)
                self.assertEqual(qds["active_evaluation_run_refs"], [OLD, NEW])
                diagnostics = qds["data_quality_summary"]["diagnostics"]
                self.assertEqual({row["source_measurement_ref"] for row in diagnostics},
                                 {"M_old_aimless", "M_dataset_1"})
                self.assertEqual(qds["data_quality_summary"]["wilson_b"]["source_measurement_ref"], "M_dataset_1")
                self.assertEqual(qds.get("assumptions_report", []), [],
                                 "The ineligible raw Wilson parent cannot establish verified ancestry")
                self.assertEqual({a["id"] for run in projection["runs"] for row in run["measurements"]
                                  for a in row.get("assumptions", [])}, set())
                self.assertEqual([a["scope_selectors"] for a in qds["dataset_associations"]],
                                 [["all input reflections"], ["/*/*/[F,SIGF]"]])
                raw_old = next(run for run in projection["raw_runs"] if run["id"] == OLD)
                self.assertEqual(raw_old["measurements"][0][field], value)

    def test_surviving_out_of_scope_dataset_rows_still_fail_closed(self) -> None:
        for field, value in (("stage", "final"), ("scope", "complex"),
                             ("scope_selector", "incorrect historical columns")):
            with self.subTest(field=field), memory_files():
                documents = corrected_out_of_scope_dataset(field, value)
                documents[1]["evaluation_runs"][0]["corrections"] = []
                with self.assertRaisesRegex(contract.QdsCompletenessError, "falls outside its association"):
                    contract.prepare_projection(documents, QDS, "synth4")

    def test_raw_binding_selectors_require_eligible_not_merely_same_subject_evidence(self) -> None:
        for field, value in (("stage", "final"), ("scope", "complex")):
            for keep_valid_sibling in (False, True):
                with self.subTest(field=field, keep_valid_sibling=keep_valid_sibling), memory_files():
                    documents = corrected_out_of_scope_dataset(field, value)
                    old = documents[0]["evaluation_runs"][0]
                    historical = documents[1]["qds_emission_contexts"][0]["dataset_associations"][0]
                    if keep_valid_sibling:
                        historical["scope_selectors"].append("/*/*/[F,SIGF]")
                    else:
                        old["measurements"] = old["measurements"][:1]
                        historical["scope_selectors"] = ["/*/*/[F,SIGF]"]
                    with self.assertRaises(contract.QdsCompletenessError):
                        contract.prepare_projection(documents, QDS, "synth4")

    def test_live_emission_accepts_repaired_dataset_without_foreign_verification(self) -> None:
        with memory_files():
            documents = corrected_out_of_scope_dataset()
            documents[-1]["tools"] = yaml.safe_load((REPO / "ref/catalog.yaml").read_text())["tools"]
            for field, filename in (("tool_recommendations", "tool_recommendations.yaml"),
                                    ("assumptions", "tool_assumptions.yaml")):
                documents[-1][field] = yaml.safe_load((REPO / "ref" / filename).read_text())[field]
            with mock.patch.object(contract, "_read_documents", return_value=copy.deepcopy(documents)):
                qds = qds_emit.emit_qds([], qds_id=QDS, structure_id="synth4")
            self.assertEqual(len(qds["data_quality_summary"]["diagnostics"]), 2)
            ids = {row["id"] for row in qds.get("assumptions_report", [])}
            self.assertFalse(ids & {"A_dataset_0", "A_dataset_1"})

    def test_corpus_accepts_repaired_dataset_but_not_unretired_out_of_scope_row(self) -> None:
        with memory_files():
            documents = corrected_out_of_scope_dataset()
            _, qds = self.emitted(documents)
            self.assertEqual(corpus_errors(documents, qds), [])
            documents[1]["evaluation_runs"][0]["corrections"] = []
            errors = corpus_errors(documents, qds)
            self.assertTrue(any("falls outside its association" in error for error in errors), errors)

    def test_repaired_dataset_replay_rejects_borrowed_assumption_after_output_repin(self) -> None:
        with memory_files() as contents:
            documents = corrected_out_of_scope_dataset()
            projection, qds = self.emitted(documents)
            documents[1]["qds_replay_pins"] = [pin_for(qds, projection)]
            qds_path = REPO / "data/test" / (QDS + ".yaml")
            contents[qds_path] = trust._canonical_qds_text(qds).encode()
            _, errors = trust._rebuild_coverage(qds_path, qds, replay_index(documents), REPO)
            self.assertEqual(errors, [])
            forged = copy.deepcopy(qds)
            forged["assumptions_report"] = [assumption("A_dataset_1")]
            contents[qds_path] = trust._canonical_qds_text(forged).encode()
            documents[1]["qds_replay_pins"][0]["canonical_qds_sha256"] = hashlib.sha256(contents[qds_path]).hexdigest()
            _, errors = trust._rebuild_coverage(qds_path, forged, replay_index(documents), REPO)
            self.assertFalse(any("canonical byte pin" in error for error in errors), errors)
            self.assertTrue(any("deterministic frozen contract-4 replay" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
