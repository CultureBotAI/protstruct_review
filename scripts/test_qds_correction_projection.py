#!/usr/bin/env python3
"""In-memory positive and adversarial tests of the contract-4 evidence view."""
from __future__ import annotations

import copy
import datetime as dt
import unittest

from qds_correction_projection import (
    NESTED_COLLECTIONS, REGISTRY_COLLECTIONS, RUN_ROW_COLLECTIONS,
    QdsCompletenessError, canonical_sha256, project_sources,
    validate_active_dependencies,
)


def registry_row(row_id: str, *, date: str = "2026-09-20", **extra: object) -> dict:
    return {
        "id": row_id, "as_of_date": date, "effective_at": f"{date}T00:00:00+00:00",
        "tool_ref": "oracle", **extra,
    }


def documents() -> list[dict]:
    return [
        {"evaluation_runs": [{
            "id": "old", "run_date": "2026-09-20", "structure_ref": "s",
            "measurements": [{"id": "m0", "subject_ref": "model:s"}],
            "headline_verdict": "Original headline.",
        }]},
        {
            "evaluation_runs": [{
                "id": "new", "run_date": "2026-09-23", "structure_ref": "s",
                "measurements": [{"id": "m1", "subject_ref": "model:s"}],
                "headline_verdict": "Corrected headline.",
            }],
            "structures": [{"id": "s", "description": "Synthetic structure."}],
            "tools": [{"id": "oracle", "oracle_family": "non_cctbx"}],
            "tool_recommendations": [], "assumptions": [],
            "qds_emission_contexts": [{
                "id": "ctx", "qds_ref": "qds", "owner_evaluation_run_ref": "new",
                "snapshot_owner_evaluation_run_ref": "new", "structure_ref": "s",
                "subject_ref": "model:s", "source_evaluation_run_refs": ["old", "new"],
                "issued_at": "2026-09-23T12:00:00+00:00", "coverage_scope": "cumulative",
                "scope_notes": "Synthetic parser test; no scientific measurements.",
                "identity_description": "Synthetic model s.", "headline_verdict": "Current scoped view.",
            }],
        },
    ]


def source_run(docs: list[dict], which: int = 0) -> dict:
    return docs[which]["evaluation_runs"][0]


def context(docs: list[dict]) -> dict:
    return docs[1]["qds_emission_contexts"][0]


def correction(
    docs: list[dict], collection: str, target_ref: str, target: object,
    *, replacement_ref: str | None = None, target_run: str = "old",
    correction_id: str = "C1",
) -> dict:
    row = {
        "id": correction_id, "action": "replace" if replacement_ref is not None else "withdraw",
        "target_collection": collection, "target_evaluation_run_ref": target_run,
        "target_ref": target_ref, "target_sha256": canonical_sha256(target),
        "reason": "Synthetic correction for projection contract test.",
        "evidence_refs": ["retained/raw.log"],
    }
    if replacement_ref is not None:
        row["replacement_ref"] = replacement_ref
    source_run(docs, 1).setdefault("corrections", []).append(row)
    return row


class ProjectionTests(unittest.TestCase):
    def project(self, docs: list[dict]) -> dict:
        return project_sources(docs, "qds", "s")

    def rejects(self, docs: list[dict], text: str) -> None:
        with self.assertRaisesRegex(QdsCompletenessError, text):
            self.project(docs)

    def test_no_corrections_preserves_legacy_sources_and_inputs(self) -> None:
        docs = documents()
        before = copy.deepcopy(docs)
        out = self.project(docs)
        self.assertEqual(docs, before)
        self.assertEqual(out["raw_runs"], out["runs"])
        self.assertEqual(out["raw_source_sha256"], canonical_sha256({"evaluation_runs": out["raw_runs"]}))
        self.assertEqual(out["source_evaluation_runs_sha256"], out["raw_source_sha256"])
        out["runs"][0]["measurements"][0]["id"] = "mutated"
        self.assertEqual(out["raw_runs"][0]["measurements"][0]["id"], "m0")
        self.assertEqual(docs, before)

    def test_all_run_row_kinds_withdraw_and_replace(self) -> None:
        for collection in RUN_ROW_COLLECTIONS:
            for action in ("withdraw", "replace"):
                with self.subTest(collection=collection, action=action):
                    docs = documents()
                    old = {"id": f"old_{collection}"}
                    new = {"id": f"new_{collection}"}
                    source_run(docs)[collection] = [old]
                    source_run(docs, 1)[collection] = [new]
                    operation = correction(
                        docs, collection, old["id"], old,
                        replacement_ref=new["id"] if action == "replace" else None,
                    )
                    before = copy.deepcopy(docs)
                    out = self.project(docs)
                    self.assertEqual(out["runs"][0][collection], [])
                    self.assertEqual(out["runs"][1][collection], [new])
                    self.assertEqual(out["raw_runs"][0][collection], [old])
                    self.assertEqual(out["corrections"], [operation])
                    self.assertEqual(docs, before)

    def test_nested_assumptions_all_kinds_both_actions(self) -> None:
        for collection, parent in NESTED_COLLECTIONS.items():
            for replace in (False, True):
                with self.subTest(collection=collection, replace=replace):
                    docs = documents()
                    old, new = {"id": "a0"}, {"id": "a1"}
                    source_run(docs)[parent] = [{"id": "p0", "assumptions": [old]}]
                    source_run(docs, 1)[parent] = [{"id": "p1", "assumptions": [new]}]
                    correction(docs, collection, "a0", old, replacement_ref="a1" if replace else None)
                    out = self.project(docs)
                    self.assertEqual(out["runs"][0][parent][0]["assumptions"], [])
                    self.assertEqual(out["runs"][1][parent][0]["assumptions"], [new])

    def test_headline_scalar_both_actions(self) -> None:
        for replace in (False, True):
            docs = documents()
            correction(docs, "headline_verdict", "old", source_run(docs)["headline_verdict"], replacement_ref="new" if replace else None)
            out = self.project(docs)
            self.assertNotIn("headline_verdict", out["runs"][0])
            self.assertEqual(out["runs"][1]["headline_verdict"], "Corrected headline.")
            self.assertEqual(out["context"]["headline_verdict"], "Current scoped view.")

    def test_whole_run_withdrawal_retains_raw_audit_lineage(self) -> None:
        docs = documents()
        correction(docs, "evaluation_run", "old", source_run(docs))
        out = self.project(docs)
        self.assertEqual([row["id"] for row in out["runs"]], ["new"])
        self.assertEqual([row["id"] for row in out["raw_runs"]], ["old", "new"])
        self.assertEqual(out["context"]["source_evaluation_run_refs"], ["old", "new"])
        self.assertEqual(out["active_evaluation_run_refs"], ["new"])

    def test_registry_both_kinds_both_actions_complete_snapshot(self) -> None:
        for kind, (field, _) in REGISTRY_COLLECTIONS.items():
            for replace in (False, True):
                with self.subTest(kind=kind, replace=replace):
                    docs = documents()
                    old, new = registry_row("r0"), registry_row("r1", date="2026-09-23")
                    docs[1][field] = [old, new]
                    correction(docs, kind, "r0", old, replacement_ref="r1" if replace else None, target_run="new")
                    out = self.project(docs)
                    self.assertEqual(out[field], [old, new])
                    self.assertEqual(out["withdrawn_registry_ids"][kind], ["r0"])
                    self.assertEqual(out[f"active_registry_{kind}"], [new])

    def test_withdrawn_registry_successor_never_resurrects_predecessor(self) -> None:
        docs = documents()
        old = registry_row("r0")
        new = registry_row("r1", date="2026-09-23", supersedes_recommendation_ref="r0")
        docs[1]["tool_recommendations"] = [old, new]
        correction(docs, "tool_recommendations", "r1", new, target_run="new")
        out = self.project(docs)
        self.assertEqual(out["tool_recommendations"], [old, new])
        self.assertEqual(out["active_registry_tool_recommendations"], [])

    def test_registry_validates_complete_even_future_and_withdrawn_lineage(self) -> None:
        docs = documents()
        old = registry_row("r0", supersedes_recommendation_ref="missing")
        docs[1]["tool_recommendations"] = [old]
        correction(docs, "tool_recommendations", "r0", old, target_run="new")
        self.rejects(docs, "dangling")
        docs = documents()
        docs[1]["assumptions"] = [registry_row("future", date="2026-09-24", supersedes_assumption_ref="missing")]
        self.rejects(docs, "dangling")

    def test_registry_rejects_future_target_and_replacement(self) -> None:
        for future_target in (False, True):
            docs = documents()
            old = registry_row("r0", date="2026-09-24" if future_target else "2026-09-20")
            new = registry_row("r1", date="2026-09-24")
            docs[1]["tool_recommendations"] = [old, new]
            correction(docs, "tool_recommendations", "r0", old, target_run="new", replacement_ref="r1")
            self.rejects(docs, "future registry row")

    def test_owner_snapshot_is_authoritative_not_live_or_legacy_merged(self) -> None:
        docs = documents()
        docs[0]["tools"] = [{"id": "oracle", "description": "Unrelated historic definition."}]
        out = self.project(docs)
        self.assertEqual(out["tools"], docs[1]["tools"])
        for field in ("structures", "tools", "tool_recommendations", "assumptions"):
            broken = copy.deepcopy(docs)
            del broken[1][field]
            self.rejects(broken, f"complete {field} snapshot")

    def test_context_required_for_both_partial_and_cumulative(self) -> None:
        for scope in ("partial", "cumulative"):
            docs = documents()
            context(docs)["coverage_scope"] = scope
            self.assertEqual(self.project(docs)["context"]["coverage_scope"], scope)
        docs = documents()
        del docs[1]["qds_emission_contexts"]
        self.rejects(docs, "exactly one")

    def test_context_exact_all_raw_runs_and_owner_carrier(self) -> None:
        for refs in (["new"], ["new", "old"], ["old", "new", "absent"], ["old", "old"]):
            docs = documents()
            context(docs)["source_evaluation_run_refs"] = refs
            self.rejects(docs, "source_evaluation_run_refs")
        docs = documents()
        context(docs)["owner_evaluation_run_ref"] = "old"
        context(docs)["snapshot_owner_evaluation_run_ref"] = "old"
        self.rejects(docs, "own source carrier")
        docs = documents()
        context(docs)["snapshot_owner_evaluation_run_ref"] = "old"
        self.rejects(docs, "snapshot owner must equal")

    def test_context_dates_and_structures(self) -> None:
        for timestamp in ("2026-09-23", "nonsense", "2026-09-23T12:00:00"):
            docs = documents()
            context(docs)["issued_at"] = timestamp
            self.rejects(docs, "datetime|timezone")
        docs = documents()
        source_run(docs, 1)["run_date"] = "2026-09-24"
        self.rejects(docs, "later than context")
        docs = documents()
        source_run(docs)["structure_ref"] = "different"
        self.rejects(docs, "another structure")
        docs = documents()
        context(docs)["structure_ref"] = "different"
        self.rejects(docs, "structure_ref conflicts")

    def test_deterministic_document_and_correction_order(self) -> None:
        docs = documents()
        first = correction(docs, "measurements", "m0", source_run(docs)["measurements"][0], correction_id="C2")
        second = correction(docs, "headline_verdict", "old", source_run(docs)["headline_verdict"], correction_id="C1")
        out = self.project(docs)
        self.assertEqual(out["corrections"], [second, first])
        self.assertEqual(out, self.project(list(reversed(docs))))
        source_run(docs)["run_date"] = dt.date(2026, 9, 20)
        self.assertEqual(self.project(docs)["raw_runs"][0]["run_date"], dt.date(2026, 9, 20))

    def test_digest_is_raw_not_canonicalized_or_projected(self) -> None:
        docs = documents()
        raw_row = source_run(docs)["measurements"][0]
        raw_row["notes"] = "Original bytes represented as YAML value. α"
        c = correction(docs, "measurements", "m0", raw_row)
        expected = canonical_sha256(raw_row)
        self.assertEqual(c["target_sha256"], expected)
        self.project(docs)
        raw_row["notes"] += " Changed."
        self.rejects(docs, "target_sha256")

    def test_unknown_fields_and_bad_correction_shape(self) -> None:
        mutations = [
            ("action", "merge", "unknown action"),
            ("target_collection", "measuremnts", "unknown target_collection"),
            ("target_ref", "missing", "dangling or wrong-kind"),
            ("target_evaluation_run_ref", "missing", "dangling or wrong-kind"),
            ("target_sha256", "0" * 64, "target_sha256"),
            ("target_sha256", "BAD", "target_sha256"),
            ("evidence_refs", [], "non-empty"),
            ("evidence_refs", "old", "list"),
            ("reason", " ", "non-empty string"),
            ("replacement_reff", "m1", "unknown fields"),
        ]
        for field, value, pattern in mutations:
            with self.subTest(field=field, value=value):
                docs = documents()
                c = correction(docs, "measurements", "m0", source_run(docs)["measurements"][0])
                c[field] = value
                self.rejects(docs, pattern)
        docs = documents()
        c = correction(docs, "measurements", "m0", source_run(docs)["measurements"][0])
        del c["reason"]
        self.rejects(docs, "missing fields")

    def test_no_self_future_or_same_date_run_target(self) -> None:
        for target_date in ("2026-09-23", "2026-09-24"):
            docs = documents()
            source_run(docs)["run_date"] = target_date
            context(docs)["issued_at"] = "2026-09-25T00:00:00+00:00"
            context(docs)["source_evaluation_run_refs"] = ["new", "old"]
            correction(docs, "measurements", "m0", source_run(docs)["measurements"][0])
            self.rejects(docs, "same-day target")
        docs = documents()
        correction(docs, "measurements", "m1", source_run(docs, 1)["measurements"][0], target_run="new")
        self.rejects(docs, "self/future")

    def test_replacement_must_be_present_new_same_kind_owner_row(self) -> None:
        for ref in ("missing", "m0", "old"):
            docs = documents()
            correction(docs, "measurements", "m0", source_run(docs)["measurements"][0], replacement_ref=ref)
            self.rejects(docs, "same-kind row")
        docs = documents()
        source_run(docs, 1)["measurements"] = [{"id": "m0"}]
        correction(docs, "measurements", "m0", source_run(docs)["measurements"][0], replacement_ref="m0")
        self.rejects(docs, "new id")
        docs = documents()
        c = correction(docs, "measurements", "m0", source_run(docs)["measurements"][0])
        c["replacement_ref"] = "m1"
        self.rejects(docs, "withdrawal forbids")
        docs = documents()
        correction(docs, "evaluation_run", "old", source_run(docs), replacement_ref="new")
        self.rejects(docs, "whole evaluation_run replacement")

    def test_duplicate_targets_ids_and_successors(self) -> None:
        docs = documents()
        row = source_run(docs)["measurements"][0]
        correction(docs, "measurements", "m0", row, correction_id="A")
        correction(docs, "measurements", "m0", row, correction_id="B")
        self.rejects(docs, "duplicate correction target")
        docs = documents()
        source_run(docs)["measurements"].append({"id": "m2"})
        for i, row in enumerate(source_run(docs)["measurements"]):
            correction(docs, "measurements", row["id"], row, replacement_ref="m1", correction_id=f"C{i}")
        self.rejects(docs, "duplicate correction successor")
        source_run(docs, 1)["corrections"][1]["id"] = "C0"
        self.rejects(docs, "duplicate id")

    def test_replacement_chain_keeps_only_final_at_original_owner(self) -> None:
        docs = documents()
        old = source_run(docs)
        new = source_run(docs, 1)
        middle = {"id": "middle", "run_date": "2026-09-21", "structure_ref": "s", "measurements": [{"id": "mid"}]}
        docs[0]["evaluation_runs"].append(middle)
        first = correction(docs, "measurements", "m0", old["measurements"][0], replacement_ref="mid", correction_id="C1")
        new["corrections"].remove(first)
        middle["corrections"] = [first]
        correction(docs, "measurements", "mid", middle["measurements"][0], replacement_ref="m1", target_run="middle", correction_id="C2")
        context(docs)["source_evaluation_run_refs"] = ["old", "middle", "new"]
        out = self.project(docs)
        self.assertEqual([run["measurements"] for run in out["runs"]], [[], [], [{"id": "m1", "subject_ref": "model:s"}]])

    def test_registry_replacement_cycle_rejected(self) -> None:
        docs = documents()
        rows = [registry_row("r0"), registry_row("r1")]
        docs[1]["tool_recommendations"] = rows
        correction(docs, "tool_recommendations", "r0", rows[0], replacement_ref="r1", target_run="new", correction_id="A")
        correction(docs, "tool_recommendations", "r1", rows[1], replacement_ref="r0", target_run="new", correction_id="B")
        self.rejects(docs, "replacement cycle")

    def test_registry_replacement_cannot_point_backward_in_time(self) -> None:
        for kind, (field, _) in REGISTRY_COLLECTIONS.items():
            docs = documents()
            target = registry_row("newer", date="2026-09-23")
            older = registry_row("older", date="2026-09-20")
            docs[1][field] = [target, older]
            correction(docs, kind, "newer", target, replacement_ref="older", target_run="new")
            self.rejects(docs, "activates before its target")

    def test_run_replacement_id_cannot_reuse_another_source_identity(self) -> None:
        docs = documents()
        source_run(docs)["measurements"].append({"id": "m1", "notes": "Older different meaning."})
        correction(docs, "measurements", "m0", source_run(docs)["measurements"][0], replacement_ref="m1")
        self.rejects(docs, "already used by another source row")

    def test_surviving_measurement_dependencies_fail_after_withdrawal(self) -> None:
        for field, value in (("delta_from_measurement_ref", "m0"), ("derived_from_measurement_refs", ["m0"])):
            docs = documents()
            source_run(docs)["measurements"].append({"id": "derived", field: value})
            correction(docs, "measurements", "m0", source_run(docs)["measurements"][0], replacement_ref="m1")
            self.rejects(docs, "depends on missing or withdrawn")

    def test_surviving_headline_assumption_and_structure_dependencies(self) -> None:
        docs = documents()
        source_run(docs)["headline_findings"] = [{"id": "h", "supporting_measurement_refs": ["m0"]}]
        correction(docs, "measurements", "m0", source_run(docs)["measurements"][0])
        self.rejects(docs, "supporting_measurement_refs")
        docs = documents()
        source_run(docs)["assumptions"] = [{"id": "a", "measurement_ref": "m0"}]
        correction(docs, "measurements", "m0", source_run(docs)["measurements"][0])
        self.rejects(docs, "measurement_ref")
        docs = documents()
        source_run(docs)["sites"] = [{"id": "site", "ligand_ref": "lig"}]
        source_run(docs)["ligands"] = [{"id": "lig"}]
        correction(docs, "ligands", "lig", source_run(docs)["ligands"][0])
        self.rejects(docs, "ligand_ref")

    def test_headline_can_support_unchanged_measurement_from_another_run(self) -> None:
        docs = documents()
        finding = {"id": "h", "supporting_measurement_refs": ["m0"]}
        source_run(docs, 1)["headline_findings"] = [finding]
        before = copy.deepcopy(docs)
        out = self.project(docs)
        self.assertEqual(out["runs"][1]["headline_findings"], [finding])
        self.assertEqual(docs, before)

    def test_cross_run_headline_support_must_remain_active(self) -> None:
        docs = documents()
        source_run(docs, 1)["headline_findings"] = [{"id": "h", "supporting_measurement_refs": ["m0"]}]
        correction(docs, "measurements", "m0", source_run(docs)["measurements"][0])
        self.rejects(docs, "supporting_measurement_refs.*missing or withdrawn")

    def test_cross_run_headline_support_requires_unique_raw_owner(self) -> None:
        docs = documents()
        middle = {"id": "middle", "run_date": "2026-09-21", "structure_ref": "s", "measurements": [{"id": "m0"}]}
        docs[0]["evaluation_runs"].append(middle)
        context(docs)["source_evaluation_run_refs"] = ["old", "middle", "new"]
        source_run(docs, 1)["headline_findings"] = [{"id": "h", "supporting_measurement_refs": ["m0"]}]
        self.rejects(docs, "supporting_measurement_refs.*ambiguous raw source owners")

    def test_withdrawn_local_headline_support_cannot_retarget_global_duplicate(self) -> None:
        docs = documents()
        source_run(docs, 1)["measurements"][0]["id"] = "m0"
        source_run(docs)["headline_findings"] = [{"id": "h", "supporting_measurement_refs": ["m0"]}]
        self.project(docs)
        correction(docs, "measurements", "m0", source_run(docs)["measurements"][0])
        self.rejects(docs, "supporting_measurement_refs.*missing or withdrawn")

    def test_cross_run_headline_support_cannot_depend_on_subject_filtered_row(self) -> None:
        docs = documents()
        source_run(docs)["measurements"][0]["subject_ref"] = "other-model"
        source_run(docs, 1)["headline_findings"] = [{"id": "h", "supporting_measurement_refs": ["m0"]}]
        out = self.project(docs)
        with self.assertRaisesRegex(QdsCompletenessError, "supporting_measurement_refs.*missing or withdrawn"):
            validate_active_dependencies(out["runs"][1:], out["raw_runs"])

    def test_computational_operands_remain_same_run_despite_global_match(self) -> None:
        for field, ref in (("delta_from_measurement_ref", "m0"), ("derived_from_measurement_refs", ["m0"])):
            with self.subTest(field=field):
                docs = documents()
                source_run(docs, 1)["measurements"][0][field] = ref
                self.rejects(docs, f"{field}.*missing or withdrawn")

    def test_scoped_selectors_require_surviving_declared_target(self) -> None:
        for scope, collection in (("site", "sites"), ("ligand", "ligands"), ("domain", "domain_assignments"), ("interface", "interface_qualities"), ("ensemble", "nmr_ensemble_qualities")):
            with self.subTest(scope=scope):
                docs = documents()
                target = {"id": "target"}
                source_run(docs)[collection] = [target]
                source_run(docs)["measurements"][0].update(scope=scope, scope_selector="target")
                self.project(docs)
                correction(docs, collection, "target", target)
                self.rejects(docs, "scope_selector")

    def test_whole_run_withdrawal_catches_cross_run_dependencies(self) -> None:
        docs = documents()
        source_run(docs, 1)["refinements"] = [{"id": "refine", "evaluation_run_ref": "old"}]
        correction(docs, "evaluation_run", "old", source_run(docs))
        self.rejects(docs, "EvaluationRun")

    def test_withdraw_all_dependent_rows_and_keep_raw_evidence_citations(self) -> None:
        docs = documents()
        source_run(docs)["headline_findings"] = [{"id": "h", "supporting_measurement_refs": ["m0"]}]
        source_run(docs, 1)["measurements"][0]["evidence_refs"] = ["old", "m0"]
        correction(docs, "measurements", "m0", source_run(docs)["measurements"][0], correction_id="A")
        correction(docs, "headline_findings", "h", source_run(docs)["headline_findings"][0], correction_id="B")
        out = self.project(docs)
        self.assertEqual(out["runs"][1]["measurements"][0]["evidence_refs"], ["old", "m0"])

    def test_bundle_partial_removal_rejected_whole_removal_allowed(self) -> None:
        docs = documents()
        source_run(docs)["measurements"] = [{"id": "a", "bundle_ref": "bundle"}, {"id": "b", "bundle_ref": "bundle"}]
        correction(docs, "measurements", "a", source_run(docs)["measurements"][0], correction_id="A")
        self.rejects(docs, "bundle.*missing or withdrawn")
        correction(docs, "measurements", "b", source_run(docs)["measurements"][1], correction_id="B")
        self.assertEqual(self.project(docs)["runs"][0]["measurements"], [])

    def test_dependency_cycle_rejected(self) -> None:
        docs = documents()
        source_run(docs)["measurements"] = [{"id": "a", "derived_from_measurement_refs": ["b"]}, {"id": "b", "delta_from_measurement_ref": "a"}]
        self.rejects(docs, "dependency cycle")

    def test_dependencies_rechecked_after_subject_filtering(self) -> None:
        docs = documents()
        source_run(docs)["measurements"].append({"id": "derived", "derived_from_measurement_refs": ["m0"]})
        out = self.project(docs)
        out["runs"][0]["measurements"].pop(0)
        with self.assertRaisesRegex(QdsCompletenessError, "missing or withdrawn"):
            validate_active_dependencies(out["runs"], out["raw_runs"])

    def test_withdrawn_local_site_cannot_retarget_same_id_in_another_run(self) -> None:
        docs = documents()
        source_run(docs)["sites"] = [{"id": "same_site", "description": "Original definition."}]
        source_run(docs, 1)["sites"] = [{"id": "same_site", "description": "Different definition."}]
        source_run(docs)["measurements"][0].update(scope="site", scope_selector="same_site")
        # Repeated legacy ids are resolvable by their original local owner.
        out = self.project(docs)
        filtered = copy.deepcopy(out["runs"])
        filtered[0]["sites"] = []
        with self.assertRaisesRegex(QdsCompletenessError, "scope_selector.*missing or withdrawn"):
            validate_active_dependencies(filtered, out["raw_runs"])
        correction(docs, "sites", "same_site", source_run(docs)["sites"][0])
        self.rejects(docs, "scope_selector.*missing or withdrawn")

    def test_withdrawn_local_assumption_operand_cannot_retarget_same_id(self) -> None:
        docs = documents()
        source_run(docs, 1)["measurements"][0]["id"] = "m0"
        source_run(docs)["assumptions"] = [{"id": "assumption", "measurement_ref": "m0"}]
        self.project(docs)
        correction(docs, "measurements", "m0", source_run(docs)["measurements"][0])
        self.rejects(docs, "measurement_ref.*missing or withdrawn")

    def test_cross_run_dependency_requires_unique_raw_owner(self) -> None:
        docs = documents()
        source_run(docs)["sites"] = [{"id": "site"}]
        source_run(docs, 1)["measurements"][0].update(scope="site", scope_selector="site")
        self.project(docs)
        middle = {"id": "middle", "run_date": "2026-09-21", "structure_ref": "s", "sites": [{"id": "site"}]}
        docs[0]["evaluation_runs"].append(middle)
        context(docs)["source_evaluation_run_refs"] = ["old", "middle", "new"]
        self.rejects(docs, "ambiguous raw source owners")

    def test_selected_registry_assumption_can_reference_active_global_measurement(self) -> None:
        docs = documents()
        selected = [registry_row("a", measurement_ref="m0")]
        out = self.project(docs)
        before = copy.deepcopy((out, selected))
        validate_active_dependencies(
            out["runs"], out["raw_runs"], registry_rows=selected, registry_owner="new",
        )
        self.assertEqual((out, selected), before)
        # A snapshot owner need not itself contribute measurements to this QDS.
        validate_active_dependencies(
            out["runs"][:1], out["raw_runs"], registry_rows=selected, registry_owner="new",
        )

    def test_selected_registry_assumption_cannot_depend_on_withdrawn_measurement(self) -> None:
        docs = documents()
        correction(docs, "measurements", "m0", source_run(docs)["measurements"][0], replacement_ref="m1")
        out = self.project(docs)
        with self.assertRaisesRegex(QdsCompletenessError, "registry snapshot new/a.measurement_ref.*missing or withdrawn"):
            validate_active_dependencies(
                out["runs"], out["raw_runs"],
                registry_rows=[registry_row("a", measurement_ref="m0")], registry_owner="new",
            )

    def test_selected_registry_assumption_requires_unambiguous_raw_global_owner(self) -> None:
        docs = documents()
        middle = {"id": "middle", "run_date": "2026-09-21", "structure_ref": "s", "measurements": [{"id": "m0"}]}
        docs[0]["evaluation_runs"].append(middle)
        context(docs)["source_evaluation_run_refs"] = ["old", "middle", "new"]
        out = self.project(docs)
        selected = [registry_row("a", measurement_ref="m0")]
        with self.assertRaisesRegex(QdsCompletenessError, "ambiguous raw source owners"):
            validate_active_dependencies(
                out["runs"], out["raw_runs"], registry_rows=selected, registry_owner="new",
            )
        # Filtering one duplicate does not repair ambiguous original ownership.
        with self.assertRaisesRegex(QdsCompletenessError, "ambiguous raw source owners"):
            validate_active_dependencies(
                [out["runs"][0], out["runs"][2]], out["raw_runs"],
                registry_rows=selected, registry_owner="new",
            )

    def test_registry_local_owner_preference_cannot_retarget_filtered_measurement(self) -> None:
        docs = documents()
        source_run(docs, 1)["measurements"][0].update(id="m0", subject_ref="other-model")
        out = self.project(docs)
        selected = [registry_row("a", measurement_ref="m0")]
        validate_active_dependencies(
            out["runs"], out["raw_runs"], registry_rows=selected, registry_owner="new",
        )
        filtered = copy.deepcopy(out["runs"])
        filtered[1]["measurements"] = []
        with self.assertRaisesRegex(QdsCompletenessError, "measurement_ref.*missing or withdrawn"):
            validate_active_dependencies(
                filtered, out["raw_runs"], registry_rows=selected, registry_owner="new",
            )

    def test_registry_unique_wrong_subject_operand_cannot_survive_filtering(self) -> None:
        docs = documents()
        source_run(docs)["measurements"][0]["subject_ref"] = "other-model"
        out = self.project(docs)
        with self.assertRaisesRegex(QdsCompletenessError, "measurement_ref.*missing or withdrawn"):
            validate_active_dependencies(
                out["runs"][1:], out["raw_runs"],
                registry_rows=[registry_row("a", measurement_ref="m0")], registry_owner="new",
            )

    def test_registry_inactive_ancestor_kept_raw_but_not_dependency_checked(self) -> None:
        docs = documents()
        ancestor = registry_row("a0", measurement_ref="m0")
        successor = registry_row(
            "a1", date="2026-09-23", measurement_ref="m1", supersedes_assumption_ref="a0",
        )
        docs[1]["assumptions"] = [ancestor, successor]
        correction(docs, "measurements", "m0", source_run(docs)["measurements"][0], replacement_ref="m1")
        out = self.project(docs)
        before = copy.deepcopy(out)
        self.assertEqual(out["active_registry_tool_assumptions"], [successor])
        validate_active_dependencies(
            out["runs"], out["raw_runs"],
            registry_rows=out["active_registry_tool_assumptions"], registry_owner="new",
        )
        self.assertEqual(out, before)
        self.assertEqual(out["assumptions"], [ancestor, successor])
        # Supplying complete ancestry instead of emitted rows is deliberately
        # rejected, preventing the adapter from weakening closure to accept it.
        with self.assertRaisesRegex(QdsCompletenessError, "a0.measurement_ref.*missing or withdrawn"):
            validate_active_dependencies(
                out["runs"], out["raw_runs"], registry_rows=out["assumptions"], registry_owner="new",
            )

    def test_registry_dependency_owner_is_explicit_and_source_bound(self) -> None:
        out = self.project(documents())
        for owner in (None, "", "missing"):
            with self.subTest(owner=owner):
                with self.assertRaisesRegex(QdsCompletenessError, "registry snapshot owner"):
                    validate_active_dependencies(
                        out["runs"], out["raw_runs"], registry_rows=[], registry_owner=owner,
                    )
        with self.assertRaisesRegex(QdsCompletenessError, "requires explicit selected registry_rows"):
            validate_active_dependencies(out["runs"], out["raw_runs"], registry_owner="new")

    def test_schema_malformed_reference_shapes_raise_contract_error(self) -> None:
        docs = documents()
        source_run(docs)["measurements"][0]["scope"] = []
        self.rejects(docs, "scope must be a non-empty string")
        docs = documents()
        source_run(docs)["refinements"] = [{"id": "r", "evaluation_run_ref": []}]
        self.rejects(docs, "evaluation_run_ref must be a non-empty string")
        docs = documents()
        row = registry_row("a", tool_ref=[])
        docs[1]["assumptions"] = [row]
        self.rejects(docs, "tool_ref must be a non-empty string")
        docs = documents()
        c = correction(docs, "measurements", "m0", source_run(docs)["measurements"][0])
        c[1], c["typo"] = "x", "x"
        self.rejects(docs, "unknown fields")

    def test_legacy_assumptions_translated_not_silently_bypassed(self) -> None:
        for collection, parent in (("assumptions", None), *NESTED_COLLECTIONS.items()):
            docs = documents()
            if parent is None:
                source_run(docs)["assumptions"] = [{"id": "a0"}]
            else:
                source_run(docs)[parent] = [{"id": "p", "assumptions": [{"id": "a0"}]}]
            source_run(docs, 1)["superseded_assumption_refs"] = ["a0"]
            out = self.project(docs)
            self.assertEqual(out["legacy_superseded_assumption_refs"], ["a0"])
            self.assertNotIn("superseded_assumption_refs", out["runs"][1])
            self.assertEqual(out["raw_runs"][1]["superseded_assumption_refs"], ["a0"])
            if parent is None:
                self.assertEqual(out["runs"][0]["assumptions"], [])
            else:
                self.assertEqual(out["runs"][0][parent][0]["assumptions"], [])

    def test_legacy_bad_refs_and_typed_duplicate_fail(self) -> None:
        for refs in (["missing"], ["a0", "a0"], ["self"]):
            docs = documents()
            source_run(docs)["assumptions"] = [{"id": "a0"}]
            source_run(docs, 1)["assumptions"] = [{"id": "self"}]
            source_run(docs, 1)["superseded_assumption_refs"] = refs
            self.rejects(docs, "duplicate|earlier input assumption")
        docs = documents()
        source_run(docs)["assumptions"] = [{"id": "a0"}]
        source_run(docs, 1)["superseded_assumption_refs"] = ["a0"]
        correction(docs, "assumptions", "a0", source_run(docs)["assumptions"][0])
        self.rejects(docs, "duplicates a legacy")

    def test_duplicate_raw_rows_and_ambiguous_nested_targets_fail(self) -> None:
        docs = documents()
        source_run(docs)["measurements"].append(copy.deepcopy(source_run(docs)["measurements"][0]))
        self.rejects(docs, "duplicate id")
        docs = documents()
        source_run(docs)["measurements"] = [{"id": "p0", "assumptions": [{"id": "same"}]}, {"id": "p1", "assumptions": [{"id": "same"}]}]
        self.rejects(docs, "ambiguous nested")


if __name__ == "__main__":
    unittest.main()
