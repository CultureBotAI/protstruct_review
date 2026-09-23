#!/usr/bin/env python3
"""Contract-4 existing-evidence corrections must not masquerade as fresh evidence.

Synthetic, in-memory end-to-end tests only. Recorded source dates describe
evidence chronology, not independently established scientific execution dates.
No frozen emitter module is patched and no scientific tool is executed.
"""
from __future__ import annotations

import copy
import hashlib
import itertools
from pathlib import Path
import tempfile
import unittest

import yaml

import check_qds_trust_invariant as trust
import qds_emit_contract_v4 as v4
from qds_correction_projection import canonical_sha256
from test_qds_contract_v4 import CATALOG, NEW, OLD, QDS, SUBJECT, fixture, measurement, pin_for


def runs(documents: list[dict]) -> list[dict]:
    return [run for document in documents for run in document.get("evaluation_runs", [])]


def owner(documents: list[dict], run_id: str) -> dict:
    return next(run for run in runs(documents) if run["id"] == run_id)


def sync_context(documents: list[dict]) -> None:
    context = next(context for document in documents
                   for context in document.get("qds_emission_contexts", []))
    context["source_evaluation_run_refs"] = [
        run["id"] for run in sorted(runs(documents), key=lambda run: (run["run_date"], run["id"]))
    ]


def correction(previous: dict, target: dict, replacement: dict, row_id: str) -> dict:
    return {
        "id": row_id, "action": "replace", "target_collection": "measurements",
        "target_evaluation_run_ref": previous["id"], "target_ref": target["id"],
        "target_sha256": canonical_sha256(target), "replacement_ref": replacement["id"],
        "reason": "Synthetic existing-evidence correction; not a new scientific execution.",
        "evidence_refs": ["ref/research/synthetic_active_site_review_2026-09-23.md"],
    }


def observation_run(run_id: str, date: str, row: dict) -> dict:
    return {"id": run_id, "structure_ref": "synth4", "run_date": date,
            "catalog_tasks_applied": [row["catalog_task_ref"]], "measurements": [row]}


def recency_fixture(*, replacement_value: float = 9.0,
                    recent_date: str = "2026-09-22", recent_row_id: str = "M_recent") -> list[dict]:
    documents = fixture()
    old, new = owner(documents, OLD), owner(documents, NEW)
    new["measurements"][0]["oracle_measure"]["value_numeric"] = replacement_value
    new["measurements"][0]["notes"] = "Corrected metadata on an existing recorded observation."
    new["corrections"] = [correction(old, old["measurements"][0], new["measurements"][0], "C_replace")]
    recent = observation_run("EVAL_recent_" + recent_date, recent_date, measurement(recent_row_id, 2.0))
    documents[0]["evaluation_runs"].append(recent)
    sync_context(documents)
    return documents


def r_triple(prefix: str, values: tuple[float, float, float]) -> list[dict]:
    metrics = ("T03_r-work", "T03_r-free", "T03_r-free_r-work_gap")
    suffixes = ("work", "free", "gap")
    return [{
        "id": f"{prefix}_{suffix}", "catalog_task_ref": "T06", "metric_definition_ref": metric,
        "oracle_tool_ref": "gemmi sfcalc", "oracle_family": "non_cctbx",
        "stage": "final", "scope": "complex", "subject_ref": SUBJECT,
        "oracle_measure": {"value_numeric": value}, "pass_status": "informational",
    } for suffix, metric, value in zip(suffixes, metrics, values)]


def r_fixture() -> list[dict]:
    documents = recency_fixture()
    old, new = owner(documents, OLD), owner(documents, NEW)
    recent = owner(documents, "EVAL_recent_2026-09-22")
    for run, prefix, values in ((old, "R_old", (0.2, 0.29, 0.09)),
                                (new, "R_corrected", (0.2, 0.29, 0.09)),
                                (recent, "R_recent", (0.15, 0.17, 0.02))):
        run["measurements"] = r_triple(prefix, values)
        run["catalog_tasks_applied"] = ["T06"]
    new["corrections"] = [correction(old, target, replacement, f"C_R_{index}")
                          for index, (target, replacement) in enumerate(zip(
                              old["measurements"], new["measurements"]))]
    documents[1]["tools"].append(copy.deepcopy(next(tool for tool in CATALOG["tools"]
                                                   if tool["id"] == "gemmi sfcalc")))
    return documents


def t15_pair(prefix: str, content: float, agreement: float, bundle: str) -> list[dict]:
    """Fictional DSSP content plus two-independent-assigner agreement recipe."""
    return [{
        "id": prefix + "_" + suffix, "catalog_task_ref": "T15",
        "metric_definition_ref": metric, "oracle_tool_ref": tool,
        "oracle_family": "non_cctbx", "stage": "final", "scope": "complex",
        "scope_selector": "all model residues", "subject_ref": SUBJECT,
        "bundle_ref": bundle, "oracle_measure": {"value_numeric": value, "unit": "fraction"},
        "pass_status": "informational",
        "notes": "Synthetic DSSP H+E content and DSSP/P-SEA three-state agreement; no execution.",
    } for suffix, metric, tool, value in (
        ("content", "T15_secondary_structure_content", "DSSP", content),
        ("agreement", "T15_secondary_structure_agreement", "DSSP + biotite P-SEA", agreement),
    )]


def t16_rows(prefix: str, bsa: float, dockq: float, capri: str) -> tuple[list[dict], list[dict]]:
    """Fictional matched InterfaceQuality rows, including a swapped-map control."""
    selector, reference = prefix + "_IFACE_AB", "synthetic:native:v4"
    bsa_evidence, dockq_evidence = f"synthetic:{prefix}:bsa", f"synthetic:{prefix}:dockq"
    interface = {
        "id": selector, "structure_ref": "synth4", "subject_ref": SUBJECT,
        "reference_subject_ref": reference, "interface_label": "Synthetic crystallographic contact",
        "chain_id_1": "A", "chain_id_2": "B", "model_to_native_chain_mapping": "AB:AB",
        "buried_surface_area": {"value_numeric": bsa, "unit": "Å²"},
        "dockq_score": {"value_numeric": dockq}, "capri_quality_class": {"value_text": capri},
        "evidence_refs": [bsa_evidence, dockq_evidence],
        "notes": "Synthetic fixture only; no structure or external execution is asserted.",
    }
    control = {**copy.deepcopy(interface), "id": prefix + "_IFACE_SWAPPED",
               "model_to_native_chain_mapping": "AB:BA", "dockq_score": {"value_numeric": 0.01},
               "capri_quality_class": {"value_text": "Incorrect"},
               "interface_label": "Synthetic swapped-chain mapping control"}
    control.pop("buried_surface_area")
    measurements = []
    for suffix, metric, tool, field, evidence in (
        ("bsa", "T16_interface_buried_surface_area", "biotite SASA", "buried_surface_area", bsa_evidence),
        ("dockq", "T16_interface_dockq_score", "DockQ", "dockq_score", dockq_evidence),
        ("capri", "T16_capri_interface_quality_class", "DockQ", "capri_quality_class", dockq_evidence),
    ):
        row = {"id": prefix + "_" + suffix, "catalog_task_ref": "T16",
               "metric_definition_ref": metric, "oracle_tool_ref": tool, "oracle_family": "non_cctbx",
               "stage": "final", "scope": "interface", "scope_selector": selector,
               "subject_ref": SUBJECT, "oracle_measure": copy.deepcopy(interface[field]),
               "pass_status": "informational", "evidence_refs": [evidence]}
        if suffix != "bsa":
            row["reference_subject_ref"] = reference
        measurements.append(row)
    return measurements, [interface, control]


def coupled_fixture(task: str) -> list[dict]:
    documents = recency_fixture()
    old, new = owner(documents, OLD), owner(documents, NEW)
    recent = owner(documents, "EVAL_recent_2026-09-22")
    for run, prefix, is_recent in ((old, task + "_old", False),
                                   (new, task + "_corrected", False),
                                   (recent, task + "_recent", True)):
        run["catalog_tasks_applied"] = [task]
        if task == "T15":
            values = (0.3, 0.9) if is_recent else (0.4, 0.8)
            run["measurements"] = t15_pair(prefix, *values, "synthetic:T15:" + ("recent" if is_recent else "old"))
        elif task == "T16":
            values = (450.0, 0.7, "Medium") if is_recent else (500.0, 0.9, "High")
            run["measurements"], run["interface_qualities"] = t16_rows(prefix, *values)
        else:
            raise ValueError("Unsupported synthetic coupled task")
    new["corrections"] = [correction(old, target, replacement, f"C_{task}_{index}")
                          for index, (target, replacement) in enumerate(zip(
                              old["measurements"], new["measurements"]))]
    tool_ids = {"DSSP", "DSSP + biotite P-SEA"} if task == "T15" else {"biotite SASA", "DockQ"}
    documents[1]["tools"].extend(copy.deepcopy(tool) for tool in CATALOG["tools"] if tool["id"] in tool_ids)
    return documents


def mixed_coupled_origins(task: str) -> list[dict]:
    documents = coupled_fixture(task)
    old, new = owner(documents, OLD), owner(documents, NEW)
    other = {"id": f"EVAL_other_{task}_2026-09-21", "run_date": "2026-09-21",
             "structure_ref": "synth4", "catalog_tasks_applied": [task],
             "measurements": copy.deepcopy(old["measurements"][1:])}
    old["measurements"] = old["measurements"][:1]
    if task == "T16":
        other["interface_qualities"] = copy.deepcopy(old["interface_qualities"])
        for interface in other["interface_qualities"]:
            interface["id"] = interface["id"].replace("T16_old_", "T16_other_")
        for row in other["measurements"]:
            row["scope_selector"] = row["scope_selector"].replace("T16_old_", "T16_other_")
    documents[0]["evaluation_runs"] = [old, other]
    new["corrections"] = [correction(old, old["measurements"][0], new["measurements"][0], "C_first")]
    new["corrections"] += [correction(other, target, replacement, f"C_other_{index}")
                           for index, (target, replacement) in enumerate(zip(
                               other["measurements"], new["measurements"][1:]))]
    sync_context(documents)
    return documents


def replay_errors(documents: list[dict], emitted: dict, *,
                  tamper_field: str | None = None, tamper_value: str | None = None,
                  repin_output: bool = False) -> list[str]:
    """Exercise actual source discovery, canonical pin checking and frozen replay."""
    documents, baseline, candidate = copy.deepcopy(documents), copy.deepcopy(emitted), copy.deepcopy(emitted)
    if tamper_field is not None:
        candidate["measurement_evidence_origins"][0][tamper_field] = tamper_value
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        data = root / "data"
        data.mkdir()
        projection = v4.prepare_projection(documents, QDS, "synth4", root)
        pin = pin_for(baseline, projection)
        pin["source_evaluation_run_refs"] = [run["id"] for run in projection["raw_runs"]]
        if repin_output:
            pin["canonical_qds_sha256"] = hashlib.sha256(trust._canonical_qds_text(candidate).encode()).hexdigest()
        owner_document = next(document for document in documents
                              if any(run["id"] == NEW for run in document["evaluation_runs"]))
        owner_document["qds_replay_pins"] = [pin]
        for document in documents:
            source_path = data / (document["evaluation_runs"][0]["id"] + ".yaml")
            source_path.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True))
        qds_path = data / (QDS + ".yaml")
        qds_path.write_text(trust._canonical_qds_text(candidate))
        errors: list[str] = []
        index = trust._load_eval_runs(root, errors)
        _, replay_failures = trust._rebuild_coverage(qds_path, candidate, index, root)
        return errors + replay_failures


class CorrectionRecencyTests(unittest.TestCase):
    def emit(self, documents: list[dict]) -> dict:
        before = copy.deepcopy(documents)
        try:
            return v4.emit_projection(v4.prepare_projection(documents, QDS, "synth4"))
        finally:
            self.assertEqual(documents, before, "Projection/emission must not mutate raw source documents")

    def assert_clashscore(self, qds: dict, value: float, run_id: str, row_id: str) -> None:
        summary = qds["geometry_summary"]["clashscore"]
        self.assertEqual(summary["value_numeric"], value)
        self.assertEqual(summary["source_evaluation_run_ref"], run_id)
        self.assertEqual(summary["source_measurement_ref"], row_id)

    def assert_r_triple(self, qds: dict, values: tuple[float, float, float], run_id: str,
                        prefix: str) -> None:
        block = qds["refinement_summary"]
        for slot, suffix, value in zip(("r_work", "r_free", "r_free_gap"),
                                       ("work", "free", "gap"), values):
            self.assertEqual(block[slot]["value_numeric"], value)
            self.assertEqual(block[slot]["source_evaluation_run_ref"], run_id)
            self.assertEqual(block[slot]["source_measurement_ref"], f"{prefix}_{suffix}")

    def assert_origin(self, qds: dict, source_run: str, source_row: str,
                      origin_run: str, origin_row: str, date: str) -> None:
        matches = [row for row in qds["measurement_evidence_origins"]
                   if (row["source_evaluation_run_ref"], row["source_measurement_ref"])
                   == (source_run, source_row)]
        self.assertEqual(matches, [{
            "source_evaluation_run_ref": source_run, "source_measurement_ref": source_row,
            "origin_evaluation_run_ref": origin_run, "origin_measurement_ref": origin_row,
            "origin_run_date": date,
        }])

    def test_september23_metadata_correction_does_not_refresh_september20_evidence(self) -> None:
        qds = self.emit(recency_fixture())
        self.assert_clashscore(qds, 2.0, "EVAL_recent_2026-09-22", "M_recent")
        self.assertEqual(qds["applied_corrections"][0]["replacement_ref"], "M_new")
        self.assertEqual(qds["derived_from_evaluation_run_refs"],
                         [OLD, "EVAL_recent_2026-09-22", NEW])
        self.assertEqual(len(qds["measurement_evidence_origins"]), 2)
        self.assert_origin(qds, NEW, "M_new", OLD, "M_old", "2026-09-20")
        self.assert_origin(qds, "EVAL_recent_2026-09-22", "M_recent",
                           "EVAL_recent_2026-09-22", "M_recent", "2026-09-22")

    def test_numeric_transcription_correction_is_not_a_new_observation(self) -> None:
        for value in (8.0, 1.0):
            with self.subTest(corrected_value=value):
                documents = recency_fixture(replacement_value=value)
                owner(documents, NEW)["corrections"][0]["reason"] = (
                    "Synthetic numeric transcription fix to the September20 evidence."
                )
                self.assert_clashscore(self.emit(documents), 2.0, "EVAL_recent_2026-09-22", "M_recent")

    def test_typed_replacement_semantics_do_not_depend_on_fresh_execution_prose(self) -> None:
        documents = recency_fixture()
        owner(documents, NEW)["corrections"][0]["reason"] = "New run! Fresh execution today!"
        owner(documents, NEW)["measurements"][0]["notes"] = "A rerun today supersedes everything."
        self.assert_clashscore(self.emit(documents), 2.0, "EVAL_recent_2026-09-22", "M_recent")

    def test_selected_replacement_keeps_correcting_source_ids_not_origin_ids(self) -> None:
        documents = fixture()
        qds = self.emit(documents)
        self.assert_clashscore(qds, 3.0, NEW, "M_new")
        self.assertEqual(qds["applied_corrections"][0]["target_ref"], "M_old")
        self.assert_origin(qds, NEW, "M_new", OLD, "M_old", "2026-09-20")

    def test_origin_priority_does_not_rewrite_source_carrier_dates(self) -> None:
        documents = recency_fixture()
        before = copy.deepcopy(documents)
        projection = v4.prepare_projection(documents, QDS, "synth4")
        expected_dates = {OLD: "2026-09-20", "EVAL_recent_2026-09-22": "2026-09-22",
                          NEW: "2026-09-23"}
        self.assertEqual({run["id"]: run["run_date"] for run in projection["raw_runs"]}, expected_dates)
        self.assertEqual(next(run for run in projection["runs"] if run["id"] == NEW)["run_date"],
                         "2026-09-23")
        qds = v4.emit_projection(projection)
        self.assertEqual(documents, before)
        self.assert_origin(qds, NEW, "M_new", OLD, "M_old", "2026-09-20")
        self.assertEqual(owner(documents, NEW)["run_date"], "2026-09-23")

    def test_transitive_correction_uses_oldest_target_not_immediate_parent_date(self) -> None:
        for recent_date in ("2026-09-21", "2026-09-22"):
            with self.subTest(recent_date=recent_date):
                documents = recency_fixture(replacement_value=7.0, recent_date=recent_date)
                old, new = owner(documents, OLD), owner(documents, NEW)
                middle = observation_run("EVAL_middle_2026-09-21", "2026-09-21", measurement("M_middle", 8.0))
                middle["corrections"] = [correction(old, old["measurements"][0], middle["measurements"][0], "C_middle")]
                new["corrections"] = [correction(middle, middle["measurements"][0], new["measurements"][0], "C_terminal")]
                documents[0]["evaluation_runs"].append(middle)
                sync_context(documents)
                qds = self.emit(documents)
                self.assert_clashscore(qds, 2.0, "EVAL_recent_" + recent_date, "M_recent")
                self.assertEqual(len(qds["applied_corrections"]), 2)
                self.assert_origin(qds, NEW, "M_new", OLD, "M_old", "2026-09-20")
                self.assertEqual(len(qds["measurement_evidence_origins"]), 2)

    def test_same_measurement_id_in_unrelated_owner_does_not_change_target_origin(self) -> None:
        documents = recency_fixture(recent_row_id="M_old")
        qds = self.emit(documents)
        self.assert_clashscore(qds, 2.0, "EVAL_recent_2026-09-22", "M_old")
        self.assertEqual(qds["applied_corrections"][0]["target_evaluation_run_ref"], OLD)
        self.assert_origin(qds, NEW, "M_new", OLD, "M_old", "2026-09-20")
        self.assert_origin(qds, "EVAL_recent_2026-09-22", "M_old",
                           "EVAL_recent_2026-09-22", "M_old", "2026-09-22")

    def test_fresh_standalone_observation_keeps_new_date_with_or_without_withdrawal(self) -> None:
        for withdraw, same_value in itertools.product((False, True), (False, True)):
            with self.subTest(withdraw=withdraw, same_value=same_value):
                value = 9.0 if same_value else 1.0
                documents = recency_fixture(replacement_value=value)
                new = owner(documents, NEW)
                new["measurements"][0]["notes"] = "Historical-looking correction prose is not a typed replacement."
                if withdraw:
                    new["corrections"][0]["action"] = "withdraw"
                    new["corrections"][0].pop("replacement_ref")
                else:
                    new["corrections"] = []
                qds = self.emit(documents)
                self.assert_clashscore(qds, value, NEW, "M_new")
                self.assert_origin(qds, NEW, "M_new", NEW, "M_new", "2026-09-23")

    def test_equal_recorded_date_conflict_still_fails_after_metadata_correction(self) -> None:
        documents = recency_fixture(recent_date="2026-09-20")
        with self.assertRaisesRegex(v4.QdsCompletenessError, "ambiguous|equally ranked"):
            self.emit(documents)

    def test_equal_values_from_distinct_same_date_original_owners_remain_ambiguous(self) -> None:
        documents = fixture()
        old, new = owner(documents, OLD), owner(documents, NEW)
        other = observation_run("EVAL_other_2026-09-20", "2026-09-20", measurement("M_other_old", 9.0))
        documents[0]["evaluation_runs"].append(other)
        new["measurements"] = [measurement("M_new", 3.0), measurement("M_other_corrected", 3.0)]
        new["corrections"] = [
            correction(old, old["measurements"][0], new["measurements"][0], "C_first"),
            correction(other, other["measurements"][0], new["measurements"][1], "C_second"),
        ]
        first, second = [dict(row) for row in new["measurements"]]
        first.pop("id")
        second.pop("id")
        self.assertEqual(first, second, "Only exact correction ancestry should distinguish these payloads")
        sync_context(documents)
        with self.assertRaisesRegex(v4.QdsCompletenessError, "ambiguous|equally ranked"):
            self.emit(documents)

    def test_foreign_subject_replacement_stays_excluded(self) -> None:
        documents = recency_fixture()
        old, new = owner(documents, OLD), owner(documents, NEW)
        old["measurements"][0]["subject_ref"] = "synthetic:another-model"
        new["measurements"][0]["subject_ref"] = "synthetic:another-model"
        new["corrections"] = [correction(old, old["measurements"][0], new["measurements"][0], "C_replace")]
        qds = self.emit(documents)
        self.assert_clashscore(qds, 2.0, "EVAL_recent_2026-09-22", "M_recent")
        self.assertEqual(len(qds["measurement_evidence_origins"]), 1)
        self.assert_origin(qds, "EVAL_recent_2026-09-22", "M_recent",
                           "EVAL_recent_2026-09-22", "M_recent", "2026-09-22")

    def test_corrected_old_complete_rfactor_bundle_does_not_outrank_recent_bundle(self) -> None:
        qds = self.emit(r_fixture())
        self.assert_r_triple(qds, (0.15, 0.17, 0.02), "EVAL_recent_2026-09-22", "R_recent")
        self.assertEqual(len(qds["measurement_evidence_origins"]), 6)
        for suffix in ("work", "free", "gap"):
            self.assert_origin(qds, NEW, "R_corrected_" + suffix, OLD, "R_old_" + suffix, "2026-09-20")
            self.assert_origin(qds, "EVAL_recent_2026-09-22", "R_recent_" + suffix,
                               "EVAL_recent_2026-09-22", "R_recent_" + suffix, "2026-09-22")

    def test_selected_complete_corrected_rfactor_bundle_preserves_new_source_ids(self) -> None:
        documents = r_fixture()
        documents[0]["evaluation_runs"] = [owner(documents, OLD)]
        sync_context(documents)
        self.assert_r_triple(self.emit(documents), (0.2, 0.29, 0.09), NEW, "R_corrected")

    def test_correction_carrier_cannot_combine_r_values_from_distinct_original_runs(self) -> None:
        documents = r_fixture()
        old, new = owner(documents, OLD), owner(documents, NEW)
        other = observation_run("EVAL_other_origin_2026-09-21", "2026-09-21", measurement("unused"))
        other["catalog_tasks_applied"] = ["T06"]
        other["measurements"] = copy.deepcopy(old["measurements"][1:])
        old["measurements"] = old["measurements"][:1]
        documents[0]["evaluation_runs"] = [old, other]
        new["corrections"] = [correction(old, old["measurements"][0], new["measurements"][0], "C_work")]
        new["corrections"] += [correction(other, target, replacement, f"C_other_{index}")
                               for index, (target, replacement) in enumerate(zip(
                                   other["measurements"], new["measurements"][1:]))]
        sync_context(documents)
        with self.assertRaisesRegex(v4.QdsCompletenessError, "coherent|bundle|code.path"):
            self.emit(documents)

    def test_new_partial_rfactor_observation_does_not_complete_a_different_bundle(self) -> None:
        documents = r_fixture()
        new = owner(documents, NEW)
        new["measurements"] = r_triple("R_fresh_partial", (0.12, 0.18, 0.06))[:1]
        new["corrections"] = []
        self.assert_r_triple(self.emit(documents), (0.15, 0.17, 0.02),
                             "EVAL_recent_2026-09-22", "R_recent")

    def test_input_row_and_correction_order_do_not_change_selection_or_output(self) -> None:
        documents = r_fixture()
        baseline = self.emit(documents)
        self.assert_r_triple(baseline, (0.15, 0.17, 0.02), "EVAL_recent_2026-09-22", "R_recent")
        for documents_reversed, runs_reversed, rows_reversed in itertools.product((False, True), repeat=3):
            with self.subTest(documents_reversed=documents_reversed,
                              runs_reversed=runs_reversed, rows_reversed=rows_reversed):
                variant = copy.deepcopy(documents)
                if documents_reversed:
                    variant.reverse()
                for document in variant:
                    if runs_reversed:
                        document["evaluation_runs"].reverse()
                    if rows_reversed:
                        for run in document["evaluation_runs"]:
                            run["measurements"].reverse()
                            if "corrections" in run:
                                run["corrections"].reverse()
                self.assertEqual(self.emit(variant), baseline)

    def test_t15_recent_complete_pair_wins_over_old_evidence_correction(self) -> None:
        qds = self.emit(coupled_fixture("T15"))
        summary = qds["classification_summary"]
        for suffix, value in (("content", 0.3), ("agreement", 0.9)):
            row = summary["secondary_structure_" + suffix]
            self.assertEqual(row["value_numeric"], value)
            self.assertEqual(row["source_evaluation_run_ref"], "EVAL_recent_2026-09-22")
            self.assertEqual(row["source_measurement_ref"], "T15_recent_" + suffix)
            self.assertEqual(row["pass_status"], "informational")
            self.assert_origin(qds, NEW, "T15_corrected_" + suffix, OLD, "T15_old_" + suffix, "2026-09-20")

    def test_t15_corrected_complete_pair_without_newer_evidence_retains_source_ids(self) -> None:
        documents = coupled_fixture("T15")
        documents[0]["evaluation_runs"] = [owner(documents, OLD)]
        sync_context(documents)
        qds = self.emit(documents)
        for suffix, value in (("content", 0.4), ("agreement", 0.8)):
            row = qds["classification_summary"]["secondary_structure_" + suffix]
            self.assertEqual(row["value_numeric"], value)
            self.assertEqual(row["source_evaluation_run_ref"], NEW)
            self.assertEqual(row["source_measurement_ref"], "T15_corrected_" + suffix)

    def test_t15_shared_bundle_id_does_not_merge_distinct_original_owners(self) -> None:
        with self.assertRaisesRegex(v4.QdsCompletenessError, "T15 coherence"):
            self.emit(mixed_coupled_origins("T15"))

    def test_t16_recent_complete_mapping_bundle_wins_over_old_evidence_correction(self) -> None:
        qds = self.emit(coupled_fixture("T16"))
        summary = qds["interface_quality_summary"]
        slots = (("interface_buried_surface_area", "bsa", "value_numeric", 450.0),
                 ("interface_dockq_score", "dockq", "value_numeric", 0.7),
                 ("capri_interface_quality_class", "capri", "value_text", "Medium"))
        for slot, suffix, value_kind, value in slots:
            self.assertEqual(summary[slot][value_kind], value)
            self.assertEqual(summary[slot]["source_evaluation_run_ref"], "EVAL_recent_2026-09-22")
            self.assertEqual(summary[slot]["source_measurement_ref"], "T16_recent_" + suffix)
            self.assertEqual(summary[slot]["scope_selector"], "T16_recent_IFACE_AB")
            self.assert_origin(qds, NEW, "T16_corrected_" + suffix, OLD, "T16_old_" + suffix, "2026-09-20")
        self.assertTrue(any(row["model_to_native_chain_mapping"] == "AB:BA"
                            for row in summary["interface_qualities"]))

    def test_t16_corrected_complete_bundle_without_newer_evidence_keeps_source_ids(self) -> None:
        documents = coupled_fixture("T16")
        documents[0]["evaluation_runs"] = [owner(documents, OLD)]
        sync_context(documents)
        qds = self.emit(documents)
        for slot, suffix in (("interface_buried_surface_area", "bsa"),
                              ("interface_dockq_score", "dockq"),
                              ("capri_interface_quality_class", "capri")):
            row = qds["interface_quality_summary"][slot]
            self.assertEqual(row["source_evaluation_run_ref"], NEW)
            self.assertEqual(row["source_measurement_ref"], "T16_corrected_" + suffix)

    def test_t16_matching_interface_metadata_does_not_merge_distinct_original_owners(self) -> None:
        with self.assertRaisesRegex(v4.QdsCompletenessError, "T16 coherence"):
            self.emit(mixed_coupled_origins("T16"))

    def test_pinned_replay_rejects_tampered_evidence_origin_date_owner_and_identity(self) -> None:
        documents = fixture()
        qds = self.emit(documents)
        self.assertEqual(replay_errors(documents, qds), [])
        for field, bad in (("origin_run_date", "2026-09-23"),
                           ("origin_evaluation_run_ref", NEW),
                           ("origin_measurement_ref", "M_new"),
                           ("source_evaluation_run_ref", OLD),
                           ("source_measurement_ref", "M_old")):
            for repin_output in (False, True):
                with self.subTest(field=field, repin_output=repin_output):
                    errors = replay_errors(documents, qds, tamper_field=field,
                                           tamper_value=bad, repin_output=repin_output)
                    self.assertTrue(any("deterministic frozen contract-4 replay" in error for error in errors), errors)
                    self.assertEqual(any("canonical byte pin" in error for error in errors), not repin_output)


if __name__ == "__main__":
    unittest.main()
