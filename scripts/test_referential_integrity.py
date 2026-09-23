#!/usr/bin/env python3
"""Focused contract-4 relationship checks; no scientific tools or network."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import check_referential_integrity as integrity  # noqa: E402
import qds_correction_projection as projection  # noqa: E402
import qds_emit_contract_v4 as contract  # noqa: E402
from protstruct_review.models import Container  # noqa: E402


OLD = "EVAL_integrity_old_2026-09-22"
NEW = "EVAL_integrity_new_2026-09-23"
QDS = "QDS_integrity_new_2026-09-23"
SUBJECT = "synthetic:integrity:model"


def source_documents() -> list[dict]:
    measurement = {
        "id": "integrity_M_old", "catalog_task_ref": "T05", "stage": "final",
        "scope": "complex", "metric_definition_ref": "T05_clashscore",
        "oracle_tool_ref": "MolProbity (gold)", "oracle_family": "non_cctbx",
        "oracle_measure": {"value_numeric": 5.0}, "pass_status": "informational",
        "subject_ref": SUBJECT,
    }
    old = {
        "id": OLD, "eval_filename_stem": OLD, "run_date": "2026-09-22",
        "structure_ref": "fixture", "catalog_tasks_applied": ["T05"],
        "measurements": [measurement],
    }
    new = {
        "id": NEW, "eval_filename_stem": NEW, "run_date": "2026-09-23",
        "structure_ref": "fixture", "catalog_tasks_applied": ["T05"],
        "measurements": [{**copy.deepcopy(measurement), "id": "integrity_M_new"}],
        "corrections": [{
            "id": "integrity_correction", "action": "withdraw",
            "target_collection": "measurements", "target_evaluation_run_ref": OLD,
            "target_ref": measurement["id"],
            "target_sha256": projection.canonical_sha256(measurement),
            "reason": "Invented correction for a relationship test.",
            "evidence_refs": ["ref/catalog.yaml"],
        }],
    }
    context = {
        "id": "integrity_context", "qds_ref": QDS,
        "owner_evaluation_run_ref": NEW, "snapshot_owner_evaluation_run_ref": NEW,
        "source_evaluation_run_refs": [OLD, NEW], "structure_ref": "fixture",
        "subject_ref": SUBJECT, "issued_at": "2026-09-23T12:00:00+00:00",
        "coverage_scope": "cumulative", "scope_notes": "Synthetic test only.",
        "identity_description": "Fictional structure.", "headline_verdict": "Synthetic only.",
    }
    return [{"evaluation_runs": [old]}, {
        "evaluation_runs": [new], "qds_emission_contexts": [context],
        "structures": [{"id": "fixture"}],
        "tools": [{"id": "MolProbity (gold)", "family": "non_cctbx",
                   "catalog_tasks_served": ["T05", "T10"]}],
        "tool_recommendations": [], "assumptions": [],
    }]


def emit(documents: list[dict]) -> dict:
    prepared = contract.prepare_projection(documents, QDS, "fixture", repo_root=integrity.REPO)
    return contract.emit_projection(prepared)


def records_for(documents: list[dict], qds: dict) -> list[tuple[Path, dict]]:
    return [
        (Path(f"data/test/{document['evaluation_runs'][0]['eval_filename_stem']}.yaml"), document)
        for document in documents
    ] + [
        (Path(f"data/test/{QDS}.yaml"), {"quality_data_sheets": [qds]}),
    ]


def violations(records: list[tuple[Path, dict]]) -> list[str]:
    indices = integrity.build_corpus_indices(records)
    out = integrity.check_duplicate_ids(indices)
    for path, document in records:
        out.extend(integrity.check_corpus_refs(document, path, indices))
    return out


class ContractFourIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.documents = source_documents()
        self.qds = emit(self.documents)

    def failures(self) -> list[str]:
        return violations(records_for(self.documents, self.qds))

    def assert_failure(self, text: str) -> None:
        failures = self.failures()
        self.assertTrue(any(text in failure for failure in failures), failures)

    def test_schema_and_raw_source_projection_accept_cumulative_and_partial(self) -> None:
        for scope in ("cumulative", "partial"):
            with self.subTest(scope=scope):
                self.documents[1]["qds_emission_contexts"][0]["coverage_scope"] = scope
                self.qds = emit(self.documents)
                for document in [*self.documents, {"quality_data_sheets": [self.qds]}]:
                    Container.model_validate(document)
                self.assertEqual(self.failures(), [])
                self.assertEqual(self.qds["derived_from_evaluation_run_refs"], [OLD, NEW])
                self.assertEqual(self.qds["active_evaluation_run_refs"], [NEW])

    def test_withdrawn_raw_target_tamper_cannot_hide_behind_projection(self) -> None:
        self.documents[0]["evaluation_runs"][0]["measurements"][0]["oracle_measure"]["value_numeric"] = 9
        self.assert_failure("target_sha256")

    def test_dangling_target_and_wrong_owner_are_rejected(self) -> None:
        correction = self.documents[1]["evaluation_runs"][0]["corrections"][0]
        correction["target_ref"] = "missing_target"
        self.assert_failure("target")
        correction["target_ref"] = "integrity_M_old"
        correction["target_evaluation_run_ref"] = NEW
        self.assert_failure("target")

    def test_unused_orphan_corrections_are_rejected(self) -> None:
        self.documents[1].pop("qds_emission_contexts")
        self.assert_failure("orphaned")

    def test_snapshot_owner_must_equal_local_context_owner(self) -> None:
        self.documents[1]["qds_emission_contexts"][0]["snapshot_owner_evaluation_run_ref"] = OLD
        self.assert_failure("snapshot_owner_evaluation_run_ref")

    def test_missing_complete_owner_snapshot_is_rejected(self) -> None:
        self.documents[1].pop("tool_recommendations")
        self.assert_failure("complete tool_recommendations snapshot")

    def test_applied_correction_metadata_cannot_be_forged(self) -> None:
        self.qds["applied_corrections"][0]["reason"] = "A different rationale."
        self.assert_failure("applied_corrections differs")

    def test_measurement_origins_accept_standalone_replacement_and_chain(self) -> None:
        for mode in ("standalone", "replacement", "chain"):
            with self.subTest(mode=mode):
                documents = source_documents()
                old = documents[0]["evaluation_runs"][0]
                new = documents[1]["evaluation_runs"][0]
                origin_run, origin_measurement = new, new["measurements"][0]
                if mode != "standalone":
                    new["corrections"][0].update(
                        action="replace", replacement_ref=new["measurements"][0]["id"]
                    )
                    origin_run, origin_measurement = old, old["measurements"][0]
                if mode == "chain":
                    earlier = copy.deepcopy(old)
                    earlier["id"] = "EVAL_integrity_origin_2026-09-21"
                    earlier["eval_filename_stem"] = earlier["id"]
                    earlier["run_date"] = "2026-09-21"
                    earlier["measurements"][0]["id"] = "integrity_M_origin"
                    old["corrections"] = [{
                        "id": "integrity_correction_first", "action": "replace",
                        "target_collection": "measurements",
                        "target_evaluation_run_ref": earlier["id"],
                        "target_ref": earlier["measurements"][0]["id"],
                        "target_sha256": projection.canonical_sha256(earlier["measurements"][0]),
                        "replacement_ref": old["measurements"][0]["id"],
                        "reason": "Invented first correction in a retained chain.",
                        "evidence_refs": ["ref/catalog.yaml"],
                    }]
                    documents[1]["qds_emission_contexts"][0]["source_evaluation_run_refs"].insert(
                        0, earlier["id"]
                    )
                    documents.insert(0, {"evaluation_runs": [earlier]})
                    origin_run, origin_measurement = earlier, earlier["measurements"][0]
                qds = emit(documents)
                self.assertEqual(qds["measurement_evidence_origins"], [{
                    "source_evaluation_run_ref": NEW,
                    "source_measurement_ref": new["measurements"][0]["id"],
                    "origin_evaluation_run_ref": origin_run["id"],
                    "origin_measurement_ref": origin_measurement["id"],
                    "origin_run_date": origin_run["run_date"],
                }])
                for document in [*documents, {"quality_data_sheets": [qds]}]:
                    Container.model_validate(document)
                self.assertEqual(violations(records_for(documents, qds)), [])

    def test_measurement_origin_fields_match_exact_derived_lineage(self) -> None:
        origin = self.qds["measurement_evidence_origins"][0]
        for field, bad in (
            ("source_evaluation_run_ref", OLD),
            ("source_measurement_ref", "integrity_M_old"),
            ("origin_evaluation_run_ref", OLD),
            ("origin_measurement_ref", "integrity_M_old"),
            ("origin_run_date", "2000-01-01"),
        ):
            with self.subTest(field=field):
                saved = origin[field]
                origin[field] = bad
                self.assert_failure("measurement_evidence_origins differs")
                origin[field] = saved

    def test_measurement_origin_list_membership_order_and_shape_are_exact(self) -> None:
        new = self.documents[1]["evaluation_runs"][0]
        additional = copy.deepcopy(new["measurements"][0])
        additional["id"] = "integrity_M_second"
        new["measurements"].append(additional)
        self.qds = emit(self.documents)
        original = copy.deepcopy(self.qds["measurement_evidence_origins"])
        self.assertEqual(len(original), 2)
        self.assertEqual(self.failures(), [])
        for label, bad in (
            ("omitted row", original[:1]),
            ("duplicate row", [*original, original[0]]),
            ("order", list(reversed(original))),
            ("empty", []),
            ("mapping", original[0]),
            ("null", None),
            ("unexpected payload", [{**row, "value_numeric": 5.0} for row in original]),
        ):
            with self.subTest(case=label):
                self.qds["measurement_evidence_origins"] = bad
                self.assert_failure("measurement_evidence_origins differs")
        self.qds.pop("measurement_evidence_origins")
        self.assert_failure("measurement_evidence_origins differs")

    def test_measurement_origins_are_contract_four_only(self) -> None:
        # Isolate this field: another v4-only payload must not make the
        # assertion pass if origins are accidentally omitted from that guard.
        for field in ("active_evaluation_run_refs", "applied_corrections",
                      "dataset_associations", "corrected_qds_refs"):
            self.qds.pop(field, None)
        for version in ("1", "2", "3"):
            with self.subTest(version=version):
                self.qds["emitter_contract_version"] = version
                self.assert_failure("contract-4-only evidence fields")

    def test_misplaced_origin_metadata_is_not_exempt_from_scalar_checks(self) -> None:
        origin = copy.deepcopy(self.qds["measurement_evidence_origins"][0])
        for placement in ("scalar", "nested field", "nested QDS", "outside QDS"):
            with self.subTest(placement=placement):
                qds = copy.deepcopy(self.qds)
                records = records_for(self.documents, qds)
                if placement == "scalar":
                    qds["geometry_summary"]["clashscore"] = origin
                elif placement == "nested field":
                    qds["geometry_summary"]["measurement_evidence_origins"] = [origin]
                elif placement == "nested QDS":
                    qds["nested"] = {"quality_data_sheets": [{
                        "emitter_contract_version": "4",
                        "measurement_evidence_origins": [origin],
                    }]}
                else:
                    records[-1][1]["measurement_evidence_origins"] = [origin]
                failures = violations(records)
                self.assertTrue(any("does not exactly match source measurement" in failure
                                    for failure in failures), failures)

    def test_origin_fields_do_not_exempt_a_forged_scalar_copy(self) -> None:
        scalar = self.qds["geometry_summary"]["clashscore"]
        scalar.update(self.qds["measurement_evidence_origins"][0])
        scalar["value_numeric"] = 123.0
        self.assert_failure("does not exactly match source measurement")

    def test_active_lineage_cannot_resurrect_a_fully_withdrawn_input(self) -> None:
        self.qds["active_evaluation_run_refs"].insert(0, OLD)
        self.assert_failure("active_evaluation_run_refs differs")

    def test_duplicate_source_correction_ids_fail(self) -> None:
        run = self.documents[1]["evaluation_runs"][0]
        run["corrections"].append(copy.deepcopy(run["corrections"][0]))
        self.assert_failure("duplicate EvidenceCorrection id")

    def test_snapshot_owner_family_is_used_for_original_scalar_comparison(self) -> None:
        # A stale carrier-local declaration must not override the recipe's
        # authoritative snapshot for a still-active raw source measurement.
        old = self.documents[0]["evaluation_runs"][0]
        self.documents[1]["evaluation_runs"][0]["corrections"] = []
        self.documents[1]["evaluation_runs"][0]["measurements"] = []
        self.documents[0]["tools"] = [{"id": "MolProbity (gold)", "family": "cctbx",
                                      "catalog_tasks_served": ["T05"]}]
        self.qds = emit(self.documents)
        self.assertEqual(self.qds["geometry_summary"]["clashscore"]["source_measurement_ref"],
                         old["measurements"][0]["id"])
        self.assertEqual(self.failures(), [])

    def test_new_fields_do_not_change_contract_three_semantics(self) -> None:
        self.qds["emitter_contract_version"] = "3"
        self.qds["coverage_scope"] = "partial"
        self.documents[1]["qds_emission_contexts"][0]["coverage_scope"] = "partial"
        self.assert_failure("contract-4-only context fields")
        self.assert_failure("contract-4-only evidence fields")

    def test_contract_four_requires_context_for_cumulative_sheet(self) -> None:
        self.qds.pop("emission_context_ref")
        self.assert_failure("emission_context_ref is required")

    def test_contract_four_pin_requires_raw_run_structure_and_context_digests(self) -> None:
        pin = {
            "id": "integrity_pin", "qds_ref": QDS,
            "source_evaluation_run_refs": [OLD, NEW], "emitter_contract_version": "4",
            "qds_emission_context_ref": "integrity_context",
            "canonical_qds_sha256": "a" * 64, "emitter_source_sha256": "b" * 64,
            "source_tools_sha256": "c" * 64,
            "source_tool_recommendations_sha256": "d" * 64,
            "source_tool_assumptions_sha256": "e" * 64,
            "source_qds_emission_context_sha256": "f" * 64,
            "source_evaluation_runs_sha256": "1" * 64,
            "source_structures_sha256": "2" * 64,
        }
        self.documents[1]["qds_replay_pins"] = [pin]
        Container.model_validate(self.documents[1])
        self.assertEqual(self.failures(), [])
        for field in ("source_evaluation_runs_sha256", "source_structures_sha256",
                      "source_qds_emission_context_sha256"):
            with self.subTest(field=field):
                saved = pin.pop(field)
                self.assert_failure(field)
                pin[field] = saved

    def test_corrected_sheets_resolve_are_earlier_and_match_structure(self) -> None:
        previous = {"id": "QDS_prior", "structure_ref": "fixture",
                    "issued_at": "2026-09-22T12:00:00Z",
                    "emitter_contract_version": "3", "coverage_scope": "cumulative",
                    "derived_from_evaluation_run_refs": [OLD]}
        context = self.documents[1]["qds_emission_contexts"][0]
        context["corrected_qds_refs"] = [previous["id"]]
        self.qds = emit(self.documents)
        records = records_for(self.documents, self.qds)
        records.append((Path("data/test/QDS_prior.yaml"), {"quality_data_sheets": [previous]}))
        self.assertEqual(violations(records), [])
        for field, value, expected in (
            ("issued_at", context["issued_at"], "strictly earlier"),
            ("structure_ref", "another_structure", "another structure"),
        ):
            saved = previous[field]
            previous[field] = value
            self.assertTrue(any(expected in failure for failure in violations(records)))
            previous[field] = saved
        context["corrected_qds_refs"] = ["QDS_missing"]
        self.assert_failure("does not resolve to a QualityDataSheet")

    def test_dataset_diagnostics_keep_original_subject_and_require_raw_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mtz = root / "input.mtz"
            mtz.write_bytes(b"synthetic bytes; no reflection program is invoked")
            digest = hashlib.sha256(mtz.read_bytes()).hexdigest()
            dataset = f"mtz:sha256:{digest}"
            old = self.documents[0]["evaluation_runs"][0]
            old["measurements"] = []
            new = self.documents[1]["evaluation_runs"][0]
            new["corrections"] = []
            new["catalog_tasks_applied"].append("T13")
            new["measurements"].append({
                "id": "integrity_M_dataset", "catalog_task_ref": "T13", "stage": "all",
                "scope": "dataset", "scope_selector": "all input reflections",
                "metric_definition_ref": "T13_aimless_run_status",
                "oracle_tool_ref": "CCP4 aimless", "oracle_family": "non_cctbx",
                "oracle_measure": {"value_text": "unavailable"},
                "pass_status": "informational", "subject_ref": dataset,
            })
            self.documents[1]["tools"].append({
                "id": "CCP4 aimless", "family": "non_cctbx", "catalog_tasks_served": ["T13"],
            })
            association = {
                "id": "integrity_dataset", "model_subject_ref": SUBJECT,
                "dataset_subject_ref": dataset, "dataset_path": "input.mtz",
                "dataset_sha256": digest, "owner_evaluation_run_ref": NEW,
                "catalog_task_ref": "T13", "stage": "all", "scope": "dataset",
                "scope_selectors": ["all input reflections"], "evidence_refs": ["input.mtz"],
            }
            self.documents[1]["qds_emission_contexts"][0]["dataset_associations"] = [association]
            with mock.patch.object(integrity, "REPO", root):
                self.qds = emit(self.documents)
                Container.model_validate({"quality_data_sheets": [self.qds]})
                self.assertEqual(self.failures(), [])
                diagnostic = self.qds["data_quality_summary"]["diagnostics"][0]
                self.assertEqual(diagnostic["subject_ref"], dataset)
                diagnostic["subject_ref"] = SUBJECT
                self.assert_failure("does not exactly match source measurement")
                diagnostic.clear()
                diagnostic["value_text"] = "forged without provenance"
                self.assert_failure("carry source_evaluation_run_ref plus source_measurement_ref")


if __name__ == "__main__":
    unittest.main()
