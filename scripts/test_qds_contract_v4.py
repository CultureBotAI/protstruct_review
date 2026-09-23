#!/usr/bin/env python3
"""Synthetic correction/admission/replay regressions; no scientific tools run."""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import yaml

import check_qds_trust_invariant as trust
import qds_emit_contract_v1 as v1
import qds_emit_contract_v4 as v4
from qds_correction_projection import canonical_sha256


REPO = Path(__file__).resolve().parent.parent
CATALOG = yaml.safe_load((REPO / "ref/catalog.yaml").read_text())
SUBJECT = "synthetic:model:v4"
OLD = "EVAL_synth_contract4_2026-09-20"
NEW = "EVAL_synth_contract4_2026-09-23"
QDS = "QDS_synth_contract4_2026-09-23"


def measurement(row_id: str, value: float = 3.0) -> dict:
    return {
        "id": row_id, "catalog_task_ref": "T05", "metric_definition_ref": "T05_clashscore",
        "oracle_tool_ref": "MolProbity (gold)", "oracle_family": "non_cctbx",
        "stage": "final", "scope": "complex", "subject_ref": SUBJECT,
        "oracle_measure": {"value_numeric": value}, "pass_status": "informational",
    }


def fixture() -> list[dict]:
    old = {"id": OLD, "structure_ref": "synth4", "run_date": "2026-09-20",
           "catalog_tasks_applied": ["T05"], "measurements": [measurement("M_old", 9.0)],
           "headline_verdict": "Superseded old headline must not be concatenated."}
    new = {"id": NEW, "structure_ref": "synth4", "run_date": "2026-09-23",
           "catalog_tasks_applied": ["T05"], "measurements": [measurement("M_new")],
           "corrections": [{
               "id": "C_replace", "action": "replace", "target_collection": "measurements",
               "target_evaluation_run_ref": OLD, "target_ref": "M_old",
               "target_sha256": canonical_sha256(old["measurements"][0]),
               "replacement_ref": "M_new", "reason": "Invented correction test, not a real run.",
               "evidence_refs": ["ref/research/synthetic_active_site_review_2026-09-23.md"],
           }]}
    return [{"evaluation_runs": [old]}, {
        "structures": [{"id": "synth4", "method": "xray", "resolution_a": 1.8,
                        "space_group": "P 21 21 21", "description": "Invented test structure."}],
        "tools": [copy.deepcopy(t) for t in CATALOG["tools"]
                  if t["id"] in {"MolProbity (gold)", "ctruncate", "CCP4 aimless"}],
        "tool_recommendations": [], "assumptions": [], "evaluation_runs": [new],
        "qds_emission_contexts": [{
            "id": "CTX_v4", "qds_ref": QDS, "owner_evaluation_run_ref": NEW,
            "snapshot_owner_evaluation_run_ref": NEW, "structure_ref": "synth4",
            "subject_ref": SUBJECT, "source_evaluation_run_refs": [OLD, NEW],
            "issued_at": "2026-09-23T08:00:00+00:00", "coverage_scope": "cumulative",
            "scope_notes": "Synthetic correction/admission test only, no scientific runs.",
            "identity_description": "Invented test structure, not a deposition.",
            "headline_verdict": "Current synthetic correction, not a quality verdict.",
        }],
    }]


def add_dataset(documents: list[dict], root: Path) -> str:
    path = root / "data" / "synthetic.mtz"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"Synthetic digest fixture only, not parsed as MTZ.\n")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    subject = f"mtz:sha256:{digest}"
    run = documents[-1]["evaluation_runs"][0]
    context = documents[-1]["qds_emission_contexts"][0]
    context["dataset_associations"] = [{
        "id": "ASSOC_dataset", "model_subject_ref": SUBJECT, "dataset_subject_ref": subject,
        "dataset_path": "data/synthetic.mtz", "dataset_sha256": digest,
        "owner_evaluation_run_ref": NEW, "catalog_task_ref": "T13", "stage": "all",
        "scope": "dataset", "scope_selectors": ["/*/*/[F,SIGF]", "all input reflections"],
        "evidence_refs": ["data/synthetic.mtz"],
    }]
    metrics = {
        "T13_wilson_b": 14.2, "T13_l-test_twinning": 0.03,
        "T13_anisotropy_δb_aniso": 8.0,
        "T13_tncs_flag": "unavailable — synthetic missing log",
        "T13_ice-ring_flags": "not flagged — fictional recognized summary",
        "T13_aimless_status": "unavailable — synthetic merged-only input",
    }
    for number, (metric, value) in enumerate(metrics.items()):
        run["measurements"].append({
            "id": f"M_dataset_{number}", "catalog_task_ref": "T13",
            "metric_definition_ref": metric,
            "oracle_tool_ref": "CCP4 aimless" if metric == "T13_aimless_status" else "ctruncate",
            "oracle_family": "non_cctbx", "stage": "all", "scope": "dataset",
            "scope_selector": "all input reflections" if metric == "T13_aimless_status" else "/*/*/[F,SIGF]",
            "subject_ref": subject,
            "oracle_measure": {"value_numeric" if isinstance(value, float) else "value_text": value},
            "pass_status": "informational", "evidence_refs": ["data/synthetic.mtz"],
        })
    return subject


def pin_for(qds: dict, projection: dict) -> dict:
    return {
        "id": "PIN_v4", "qds_ref": QDS, "source_evaluation_run_refs": [OLD, NEW],
        "qds_emission_context_ref": "CTX_v4", "emitter_contract_version": "4",
        "canonical_qds_sha256": hashlib.sha256(trust._canonical_qds_text(qds).encode()).hexdigest(),
        "emitter_source_sha256": hashlib.sha256(Path(v4.__file__).read_bytes()).hexdigest(),
        "source_tools_sha256": trust._snapshot_digest("tools", projection["tools"]),
        "source_structures_sha256": trust._snapshot_digest("structures", projection["structures"]),
        "source_tool_recommendations_sha256": trust._snapshot_digest("tool_recommendations", projection["tool_recommendations"]),
        "source_tool_assumptions_sha256": trust._snapshot_digest("assumptions", projection["assumptions"]),
        "source_qds_emission_context_sha256": trust._snapshot_digest("qds_emission_contexts", [projection["context"]]),
        "source_evaluation_runs_sha256": trust._snapshot_digest("evaluation_runs", projection["raw_runs"]),
    }


class Contract4Tests(unittest.TestCase):
    def test_current_default_emits_full_corrected_synthetic_fixture(self) -> None:
        import qds_emit

        source = REPO / "data/examples/eval/EVAL_synth_active_site_2026-09-23.yaml"
        document = yaml.safe_load(source.read_text())
        context = document["qds_emission_contexts"][0]
        context["qds_ref"] = "QDS_current_contract4_synthetic"
        context["snapshot_owner_evaluation_run_ref"] = context["owner_evaluation_run_ref"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / source.name
            path.write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True))
            qds = qds_emit.emit_qds([path], qds_id=context["qds_ref"], structure_id="synth1")
        self.assertEqual(qds["emitter_contract_version"], "4")
        for key in ("per_residue_quality", "site_qualities", "pairwise_comparisons",
                    "tool_recommendations_applied", "assumptions_report", "cross_tool_coverage"):
            self.assertTrue(qds[key], key)
        self.assertEqual(len(qds["per_residue_quality"]["lddt_per_residue"]), 5)
        self.assertEqual(qds["site_qualities"][0]["ligand_quality"]["rscc"]["oracle_tool_ref"], "edstats")

    def test_headline_assumption_replacement_reaches_output(self) -> None:
        for correction_only in (False, True):
            with self.subTest(correction_only=correction_only):
                documents = fixture()
                old, new = documents[0]["evaluation_runs"][0], documents[1]["evaluation_runs"][0]
                a = {"id": "A_old", "kind": "implicit", "scope": "tool", "title": "Old",
                     "description": "Old assumption", "status": "unchecked"}
                old["headline_findings"] = [{"id": "F_old", "assumptions": [a]}]
                new["headline_findings"] = [{"id": "F_new", "assumptions": [{**a, "id": "A_new"}]}]
                if correction_only:
                    new["measurements"] = []
                new["corrections"][0].update(
                    target_collection="headline_assumptions", target_ref="A_old",
                    target_sha256=canonical_sha256(a), replacement_ref="A_new",
                )
                qds = v4.emit_projection(v4.prepare_projection(documents, QDS, "synth4"))
                self.assertEqual([a["id"] for a in qds["assumptions_report"]], ["A_new"])

    def test_correction_only_owner_keeps_applicable_replacement_assumption(self) -> None:
        documents = fixture()
        old, new = documents[0]["evaluation_runs"][0], documents[1]["evaluation_runs"][0]
        assumption = {"id": "A_old", "kind": "implicit", "scope": "tool", "title": "Old",
                      "description": "Old assumption", "status": "unchecked"}
        old["assumptions"] = [assumption]
        new["measurements"] = []
        new["assumptions"] = [{**assumption, "id": "A_new", "description": "Corrected assumption"},
                              {**assumption, "id": "A_unrelated"}]
        new["corrections"][0].update(
            target_collection="assumptions", target_ref="A_old",
            target_sha256=canonical_sha256(assumption), replacement_ref="A_new",
        )
        qds = v4.emit_projection(v4.prepare_projection(documents, QDS, "synth4"))
        self.assertEqual(qds["active_evaluation_run_refs"], [OLD, NEW])
        self.assertEqual([a["id"] for a in qds["assumptions_report"]], ["A_new"])

    def test_whole_headline_replacement_keeps_embedded_assumptions(self) -> None:
        documents = fixture()
        old, new = documents[0]["evaluation_runs"][0], documents[1]["evaluation_runs"][0]
        a = {"id": "A_old", "kind": "implicit", "scope": "tool", "title": "Old",
             "description": "Synthetic assumption", "status": "unchecked"}
        old["headline_findings"] = [{"id": "F_old", "assumptions": [a]}]
        new["measurements"] = []
        new["headline_findings"] = [{"id": "F_new", "assumptions": [{**a, "id": "A_new"}]}]
        new["corrections"][0].update(
            target_collection="headline_findings", target_ref="F_old",
            target_sha256=canonical_sha256(old["headline_findings"][0]), replacement_ref="F_new",
        )
        qds = v4.emit_projection(v4.prepare_projection(documents, QDS, "synth4"))
        self.assertEqual([a["id"] for a in qds["assumptions_report"]], ["A_new"])
        self.assertEqual(qds["active_evaluation_run_refs"], [OLD, NEW])

    def test_terminal_auxiliary_replacement_follows_raw_ancestry(self) -> None:
        for kind in ("assumptions", "headline_assumptions", "headline_findings", "mixed_headline"):
            for relevant in (True, False):
                with self.subTest(kind=kind, relevant=relevant):
                    documents = fixture()
                    old, new = documents[0]["evaluation_runs"][0], documents[1]["evaluation_runs"][0]
                    middle = {"id": "EVAL_synth_contract4_2026-09-21", "run_date": "2026-09-21",
                              "structure_ref": "synth4", "measurements": []}
                    a = {"id": "A_old", "kind": "implicit", "scope": "tool", "title": "Old",
                         "description": "Synthetic assumption", "status": "unchecked"}
                    for run, suffix in ((old, "old"), (middle, "mid"), (new, "new")):
                        assumption = {**a, "id": f"A_{suffix}"}
                        if kind == "assumptions":
                            run["assumptions"] = [assumption]
                        else:
                            run["headline_findings"] = [{"id": f"F_{suffix}", "assumptions": [assumption]}]
                    new["measurements"] = []
                    if not relevant:
                        old["measurements"][0]["subject_ref"] = "different-model"
                        # A separate surviving model row permits emission, but
                        # must not admit another subject's correction ancestry.
                        control = {"id": "EVAL_control_2026-09-19", "run_date": "2026-09-19",
                                   "structure_ref": "synth4", "measurements": [measurement("M_control")]}
                        documents[0]["evaluation_runs"].insert(0, control)
                        documents[-1]["qds_emission_contexts"][0]["source_evaluation_run_refs"].insert(0, control["id"])
                    template = new["corrections"][0]
                    for index, (previous, current, suffix) in enumerate(((old, middle, "mid"), (middle, new, "new"))):
                        collection = kind
                        if kind == "mixed_headline":
                            collection = "headline_findings" if index == 0 else "headline_assumptions"
                        if collection == "assumptions":
                            target = previous["assumptions"][0]
                            successor = current["assumptions"][0]
                        elif collection == "headline_findings":
                            target = previous["headline_findings"][0]
                            successor = current["headline_findings"][0]
                        else:
                            target = previous["headline_findings"][0]["assumptions"][0]
                            successor = current["headline_findings"][0]["assumptions"][0]
                        current["corrections"] = [{**template, "id": f"C_{suffix}",
                            "target_collection": collection, "target_evaluation_run_ref": previous["id"],
                            "target_ref": target["id"], "target_sha256": canonical_sha256(target),
                            "replacement_ref": successor["id"]}]
                    documents[0]["evaluation_runs"].append(middle)
                    documents[-1]["qds_emission_contexts"][0]["source_evaluation_run_refs"].insert(-1, middle["id"])
                    qds = v4.emit_projection(v4.prepare_projection(documents, QDS, "synth4"))
                    self.assertEqual([a["id"] for a in qds.get("assumptions_report", [])],
                                     ["A_new"] if relevant else [])
                    self.assertEqual(len(qds["applied_corrections"]), 2)
                    self.assertEqual(NEW in qds["active_evaluation_run_refs"], relevant)

    def test_registry_assumption_requires_active_unambiguous_dependency(self) -> None:
        registry = {"id": "A_registry", "kind": "implicit", "scope": "measurement",
                    "tool_ref": "MolProbity (gold)", "measurement_ref": "M_new",
                    "title": "Dependency test", "description": "Synthetic dependency",
                    "status": "unchecked", "as_of_date": "2026-09-20",
                    "effective_at": "2026-09-20T00:00:00+00:00"}
        documents = fixture()
        documents[-1]["assumptions"] = [registry]
        qds = v4.emit_projection(v4.prepare_projection(documents, QDS, "synth4"))
        self.assertEqual(qds["assumptions_report"][0]["measurement_ref"], "M_new")
        registry["measurement_ref"] = "M_old"
        with self.assertRaisesRegex(v4.QdsCompletenessError, "missing or withdrawn"):
            v4.emit_projection(v4.prepare_projection(documents, QDS, "synth4"))
        # Inactive registry predecessors are retained for audit, not validated
        # as active dependencies or reintroduced after a correction.
        successor = {**registry, "id": "A_successor", "measurement_ref": "M_new",
                     "supersedes_assumption_ref": "A_registry",
                     "as_of_date": "2026-09-21", "effective_at": "2026-09-21T00:00:00+00:00"}
        documents[-1]["assumptions"].append(successor)
        qds = v4.emit_projection(v4.prepare_projection(documents, QDS, "synth4"))
        self.assertEqual([a["id"] for a in qds["assumptions_report"]], ["A_successor"])

    def test_alternating_nested_and_whole_replacements_keep_terminal_only(self) -> None:
        for pattern in (("nested", "whole", "nested"), ("whole", "nested", "whole")):
            for relevant in (True, False):
                with self.subTest(pattern=pattern, relevant=relevant):
                    documents = fixture()
                    old, new = documents[0]["evaluation_runs"][0], documents[1]["evaluation_runs"][0]
                    middle = [{"id": f"EVAL_synth_contract4_2026-09-{day}", "run_date": f"2026-09-{day}",
                               "structure_ref": "synth4", "measurements": []} for day in (21, 22)]
                    runs = [old, *middle, new]
                    for i, run in enumerate(runs):
                        run["headline_findings"] = [{"id": f"F_{i}", "assumptions": [{
                            "id": f"A_{i}", "kind": "implicit", "scope": "tool", "title": "Synthetic",
                            "description": "Synthetic assumption", "status": "unchecked"}]}]
                    new["measurements"] = []
                    template = new["corrections"][0]
                    for i, (previous, current, kind) in enumerate(zip(runs, runs[1:], pattern)):
                        target = previous["headline_findings"][0]
                        successor = current["headline_findings"][0]
                        if kind == "nested":
                            target = target["assumptions"][0]
                            successor = successor["assumptions"][0]
                        current["corrections"] = [{**template, "id": f"C_{i}",
                            "target_collection": "headline_findings" if kind == "whole" else "headline_assumptions",
                            "target_evaluation_run_ref": previous["id"], "target_ref": target["id"],
                            "target_sha256": canonical_sha256(target), "replacement_ref": successor["id"]}]
                    # Only terminal nested replacements inherit their exact
                    # ancestry, not unrelated siblings in the same new holder.
                    if pattern[-1] == "nested":
                        new["headline_findings"][0]["assumptions"].append({
                            **new["headline_findings"][0]["assumptions"][0], "id": "A_unrelated"})
                    documents[0]["evaluation_runs"].extend(middle)
                    context = documents[-1]["qds_emission_contexts"][0]
                    context["source_evaluation_run_refs"] = [r["id"] for r in runs]
                    if not relevant:
                        old["measurements"][0]["subject_ref"] = "other-model"
                        control = {"id": "EVAL_control_2026-09-19", "run_date": "2026-09-19",
                                   "structure_ref": "synth4", "measurements": [measurement("M_control")]}
                        documents[0]["evaluation_runs"].insert(0, control)
                        context["source_evaluation_run_refs"].insert(0, control["id"])
                    qds = v4.emit_projection(v4.prepare_projection(documents, QDS, "synth4"))
                    self.assertEqual([a["id"] for a in qds.get("assumptions_report", [])],
                                     ["A_3"] if relevant else [])
                    self.assertEqual(len(qds["applied_corrections"]), 3)

    def test_replacement_headline_can_retain_cross_run_measurement_support(self) -> None:
        documents = fixture()
        old, new = documents[0]["evaluation_runs"][0], documents[1]["evaluation_runs"][0]
        assumption = {"id": "A_old", "kind": "implicit", "scope": "tool", "title": "Synthetic",
                      "description": "Synthetic support", "status": "unchecked"}
        old["headline_findings"] = [{"id": "F_old", "supporting_measurement_refs": ["M_old"],
                                     "assumptions": [assumption]}]
        new["measurements"] = []
        new["headline_findings"] = [{"id": "F_new", "supporting_measurement_refs": ["M_old"],
                                     "assumptions": [{**assumption, "id": "A_new"}]}]
        new["corrections"][0].update(
            target_collection="headline_findings", target_ref="F_old",
            target_sha256=canonical_sha256(old["headline_findings"][0]), replacement_ref="F_new",
        )
        qds = v4.emit_projection(v4.prepare_projection(documents, QDS, "synth4"))
        self.assertEqual(qds["geometry_summary"]["clashscore"]["source_evaluation_run_ref"], OLD)
        self.assertEqual([a["id"] for a in qds["assumptions_report"]], ["A_new"])

    def test_substantive_owner_cannot_relabel_foreign_auxiliary_ancestry(self) -> None:
        for collection in ("assumptions", "headline_assumptions", "headline_findings", "cross_tool_waivers"):
            with self.subTest(collection=collection):
                documents = fixture()
                old, new = documents[0]["evaluation_runs"][0], documents[1]["evaluation_runs"][0]
                old["measurements"][0]["subject_ref"] = "other-model"
                a = {"id": "A_old", "kind": "implicit", "scope": "tool", "title": "Foreign",
                     "description": "Other model assumption", "status": "unchecked"}
                fresh = {**a, "id": "A_fresh", "description": "Fresh selected-owner context"}
                new["assumptions"] = [fresh]
                if collection == "cross_tool_waivers":
                    target = {"id": "W_old", "catalog_task_ref": "T05", "reason": "Foreign context",
                              "as_of_date": "2026-09-20"}
                    successor = {**target, "id": "W_new", "as_of_date": "2026-09-23"}
                    old[collection] = [target]
                    new[collection] = [successor]
                elif collection == "assumptions":
                    target, successor = a, {**a, "id": "A_new"}
                    old[collection] = [target]
                    new[collection].append(successor)
                else:
                    old["headline_findings"] = [{"id": "F_old", "assumptions": [a]}]
                    new["headline_findings"] = [{"id": "F_new", "assumptions": [{**a, "id": "A_new"}]}]
                    target, successor = old["headline_findings"][0], new["headline_findings"][0]
                    if collection == "headline_assumptions":
                        target, successor = target["assumptions"][0], successor["assumptions"][0]
                new["corrections"][0].update(
                    target_collection=collection, target_ref=target["id"],
                    target_sha256=canonical_sha256(target), replacement_ref=successor["id"],
                )
                qds = v4.emit_projection(v4.prepare_projection(documents, QDS, "synth4"))
                self.assertEqual(qds["active_evaluation_run_refs"], [NEW])
                self.assertEqual([a["id"] for a in qds["assumptions_report"]], ["A_fresh"])
                self.assertNotIn("cross_tool_waivers", qds)

    def test_associated_dataset_outranks_newer_legacy_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            documents = fixture()
            subject = add_dataset(documents, root)
            old, new = documents[0]["evaluation_runs"][0], documents[1]["evaluation_runs"][0]
            data = [row for row in new["measurements"] if row["catalog_task_ref"] == "T13"]
            new["measurements"] = [row for row in new["measurements"] if row not in data]
            old["measurements"].extend(data)
            documents[-1]["qds_emission_contexts"][0]["dataset_associations"][0][
                "owner_evaluation_run_ref"] = OLD
            wilson = next(row for row in data if row["metric_definition_ref"] == "T13_wilson_b")
            new["measurements"].append({**copy.deepcopy(wilson), "id": "legacy", "subject_ref": None,
                                        "oracle_measure": {"value_numeric": 999.0}})
            p = v4.prepare_projection(documents, QDS, "synth4", root)
            winner = v4.emit_projection(p)["data_quality_summary"]["wilson_b"]
            self.assertEqual(winner["subject_ref"], subject)
            self.assertEqual(winner["source_evaluation_run_ref"], OLD)
            self.assertEqual(winner["value_numeric"], 14.2)

    def test_correction_precedes_every_builder_and_preserves_raw_lineage(self) -> None:
        documents = fixture()
        before = copy.deepcopy(documents)
        projected = v4.prepare_projection(documents, QDS, "synth4")
        qds = v4.emit_projection(projected)
        self.assertEqual(documents, before)
        self.assertEqual(qds["derived_from_evaluation_run_refs"], [OLD, NEW])
        self.assertEqual(qds["active_evaluation_run_refs"], [NEW])
        self.assertEqual(qds["geometry_summary"]["clashscore"]["value_numeric"], 3.0)
        self.assertEqual(qds["geometry_summary"]["clashscore"]["source_evaluation_run_ref"], NEW)
        self.assertNotIn("Superseded old headline", qds["headline_verdict"])
        self.assertEqual(qds["applied_corrections"][0]["target_ref"], "M_old")
        reversed_projection = v4.prepare_projection(list(reversed(documents)), QDS, "synth4")
        self.assertEqual(qds, v4.emit_projection(reversed_projection))

    def test_invalid_withdrawn_measurement_is_not_canonicalized_or_graded(self) -> None:
        documents = fixture()
        old = documents[0]["evaluation_runs"][0]["measurements"][0]
        old.update(oracle_tool_ref="wrong historical attribution", pass_criterion="invented old cutoff")
        documents[1]["evaluation_runs"][0]["corrections"][0]["target_sha256"] = canonical_sha256(old)
        qds = v4.emit_projection(v4.prepare_projection(documents, QDS, "synth4"))
        self.assertEqual(qds["geometry_summary"]["clashscore"]["oracle_tool_ref"], "MolProbity (gold)")

    def test_dataset_subject_survives_all_selectors_and_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            documents = fixture()
            subject = add_dataset(documents, root)
            projection = v4.prepare_projection(documents, QDS, "synth4", root)
            qds = v4.emit_projection(projection)
            quality = qds["data_quality_summary"]
            self.assertEqual(quality["wilson_b"]["subject_ref"], subject)
            self.assertEqual(len(quality["diagnostics"]), 6)
            self.assertEqual({row["subject_ref"] for row in quality["diagnostics"]}, {subject})
            coverage = qds["cross_tool_coverage"]["task_coverage"]
            self.assertEqual(len([r for r in coverage if r["catalog_task_ref"] == "T13"]), 6)
            self.assertEqual({r["subject_ref"] for r in coverage if r["catalog_task_ref"] == "T13"}, {subject})
            self.assertEqual(qds["geometry_summary"]["clashscore"]["subject_ref"], SUBJECT)
            unrelated = copy.deepcopy(documents[-1]["evaluation_runs"][0]["measurements"][-1])
            unrelated.update(id="M_unrelated", subject_ref="mtz:sha256:" + "a" * 64)
            documents[-1]["evaluation_runs"][0]["measurements"].append(unrelated)
            self.assertEqual(qds, v4.emit_projection(v4.prepare_projection(documents, QDS, "synth4", root)))

    def test_dataset_binding_mutations_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = fixture()
            add_dataset(baseline, root)
            for field, bad in (("dataset_sha256", "0" * 64), ("dataset_subject_ref", SUBJECT),
                               ("model_subject_ref", "different-model"), ("scope", "complex"),
                               ("stage", "final"), ("catalog_task_ref", "T05"),
                               ("scope_selectors", ["different columns"]), ("evidence_refs", []),
                               ("owner_evaluation_run_ref", OLD), ("dataset_path", "../outside.mtz")):
                with self.subTest(field=field):
                    doc = copy.deepcopy(baseline)
                    doc[-1]["qds_emission_contexts"][0]["dataset_associations"][0][field] = bad
                    with self.assertRaises(v4.QdsCompletenessError):
                        v4.prepare_projection(doc, QDS, "synth4", root)
            (root / "data/synthetic.mtz").write_bytes(b"mutated bytes")
            with self.assertRaisesRegex(v4.QdsCompletenessError, "bytes do not match"):
                v4.prepare_projection(baseline, QDS, "synth4", root)

    def test_owner_snapshots_are_used_without_live_registry_fallback(self) -> None:
        projection = v4.prepare_projection(fixture(), QDS, "synth4")
        with mock.patch.object(v1, "_load_catalog_tool_families", side_effect=AssertionError("live catalog consulted")):
            qds = v4.emit_projection(projection)
        self.assertEqual(qds["emitter_contract_version"], "4")

    def test_pinned_replay_detects_raw_withdrawn_source_and_output_mutations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            data.mkdir()
            documents = fixture()
            projection = v4.prepare_projection(documents, QDS, "synth4", root)
            qds = v4.emit_projection(projection)
            documents[1]["qds_replay_pins"] = [pin_for(qds, projection)]
            for document in documents:
                ref = document["evaluation_runs"][0]["id"]
                (data / f"{ref}.yaml").write_text(yaml.safe_dump(document, sort_keys=False, allow_unicode=True))
            qds_path = data / f"{QDS}.yaml"
            qds_path.write_text(trust._canonical_qds_text(qds))
            failures: list[str] = []
            index = trust._load_eval_runs(root, failures)
            expected, errors = trust._rebuild_coverage(qds_path, qds, index, root)
            self.assertEqual(failures + errors, [])
            self.assertEqual(expected, qds["cross_tool_coverage"])
            # Even an otherwise unrendered old headline is part of the raw pin.
            index[OLD][0].source_document["evaluation_runs"][0]["headline_verdict"] = "mutated old narrative"
            _, errors = trust._rebuild_coverage(qds_path, qds, index, root)
            self.assertTrue(any("source_evaluation_runs_sha256" in e for e in errors), errors)
            qds["headline_verdict"] = "fabricated current verdict"
            qds_path.write_text(trust._canonical_qds_text(qds))
            index = trust._load_eval_runs(root, [])
            _, errors = trust._rebuild_coverage(qds_path, qds, index, root)
            self.assertTrue(any("canonical byte pin" in e for e in errors), errors)
            self.assertTrue(any("deterministic frozen contract-4 replay" in e for e in errors), errors)


if __name__ == "__main__":
    unittest.main()
