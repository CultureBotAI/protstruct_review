#!/usr/bin/env python3
"""Pure, append-only evidence projection for QualityDataSheet contract 4.

Raw sources are audit records, never patch targets. A replacement retires its
target and leaves the replacement at its *own* source location. Registry rows
remain complete so time slicing cannot resurrect a withdrawn predecessor.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import re
from typing import Any

import yaml

import qds_emit_contract_v3 as _v3


QdsCompletenessError = _v3.QdsCompletenessError
_v1 = _v3._v2._v1
SUBJECT_ROW_KEYS = tuple(_v1.SUBJECT_ROW_KEYS)
RUN_ROW_COLLECTIONS = SUBJECT_ROW_KEYS + (
    "measurements", "headline_findings", "assumptions", "cross_tool_waivers",
    "refinements",
)
NESTED_COLLECTIONS = {
    "measurement_assumptions": "measurements",
    "headline_assumptions": "headline_findings",
}
REGISTRY_COLLECTIONS = {
    "tool_recommendations": ("tool_recommendations", "supersedes_recommendation_ref"),
    "tool_assumptions": ("assumptions", "supersedes_assumption_ref"),
}
TARGET_COLLECTIONS = frozenset(RUN_ROW_COLLECTIONS) | frozenset(NESTED_COLLECTIONS) | {
    "headline_verdict", "evaluation_run", *REGISTRY_COLLECTIONS,
}
CORRECTION_FIELDS = frozenset({
    "id", "action", "target_collection", "target_evaluation_run_ref", "target_ref",
    "target_sha256", "replacement_ref", "reason", "evidence_refs",
})
_REQUIRED_CORRECTION_FIELDS = CORRECTION_FIELDS - {"replacement_ref"}
_SNAPSHOT_FIELDS = ("structures", "tools", "tool_recommendations", "assumptions")
Target = tuple[str, str, str]


def canonical_sha256(value: Any) -> str:
    """Hash the exact raw YAML value, including scalar singleton targets."""
    return hashlib.sha256(
        yaml.safe_dump(value, sort_keys=True, allow_unicode=True).encode("utf-8")
    ).hexdigest()


def _fail(message: str) -> None:
    raise QdsCompletenessError(f"QDS correction projection: {message}")


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{label} must be a non-empty string")
    return value


def _strings(value: Any, label: str, *, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list) or (nonempty and not value):
        _fail(f"{label} must be {'a non-empty' if nonempty else 'a'} list")
    for item in value:
        _text(item, label)
    if len(value) != len(set(value)):
        _fail(f"{label} contains duplicate references")
    return value


def _rows(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        _fail(f"{label} must be a list")
    seen: set[str] = set()
    for row in value:
        if not isinstance(row, dict):
            _fail(f"{label} contains a non-mapping row")
        row_id = _text(row.get("id"), f"{label} row id")
        if row_id in seen:
            _fail(f"{label} contains duplicate id {row_id!r}")
        seen.add(row_id)
    return value


def _date(value: Any, label: str) -> dt.date:
    if isinstance(value, dt.datetime):
        _fail(f"{label} must be a date, not a datetime")
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(_text(value, label))
    except ValueError:
        _fail(f"{label} is not an ISO date: {value!r}")


def _target_index(runs: list[dict[str, Any]]) -> dict[Target, Any]:
    index: dict[Target, Any] = {}
    for run in runs:
        run_id = _text(run.get("id"), "EvaluationRun id")
        index[("evaluation_run", run_id, run_id)] = run
        if "headline_verdict" in run:
            _text(run["headline_verdict"], f"{run_id} headline_verdict")
            index[("headline_verdict", run_id, run_id)] = run["headline_verdict"]
        for collection in RUN_ROW_COLLECTIONS:
            for row in _rows(run.get(collection, []), f"{run_id}.{collection}"):
                index[(collection, run_id, row["id"])] = row
        for collection, parent in NESTED_COLLECTIONS.items():
            for row in run.get(parent, []):
                for assumption in _rows(
                    row.get("assumptions", []), f"{run_id}.{parent}.{row['id']}.assumptions"
                ):
                    key = (collection, run_id, assumption["id"])
                    if key in index:
                        _fail(f"ambiguous nested assumption target {key!r}")
                    index[key] = assumption
    return index


def _legacy_targets(
    runs: list[dict[str, Any]], index: dict[Target, Any]
) -> set[Target]:
    """Translate the old assumption-only withdrawal form, validating raw lineage."""
    positions = {run["id"]: position for position, run in enumerate(runs)}
    suppressed: set[Target] = set()
    assumption_kinds = {"assumptions", *NESTED_COLLECTIONS}
    for run in runs:
        refs = _strings(
            run.get("superseded_assumption_refs", []),
            f"{run['id']} superseded_assumption_refs",
        )
        for ref in refs:
            candidates = [key for key in index if key[0] in assumption_kinds and key[2] == ref]
            earlier = [key for key in candidates if positions[key[1]] < positions[run["id"]]]
            if len(earlier) != 1:
                _fail(
                    f"{run['id']} legacy superseded assumption {ref!r} must resolve "
                    "unambiguously to one earlier input assumption (not self/future/dangling)"
                )
            if earlier[0] in suppressed:
                _fail(f"duplicate legacy assumption withdrawal {ref!r}")
            suppressed.add(earlier[0])
    return suppressed


def _check_replacement_identity(old: Any, new: Any, label: str) -> None:
    if not isinstance(old, dict) or not isinstance(new, dict):
        return
    for field in ("structure_ref", "candidate_ref"):
        if old.get(field) is not None and new.get(field) is not None and old[field] != new[field]:
            _fail(f"{label} crosses structures via {field}")


def _validated_corrections(
    runs: list[dict[str, Any]], index: dict[Target, Any], snapshot_owner: str,
    issued_at: str,
) -> tuple[list[dict[str, Any]], set[Target]]:
    run_dates = {run["id"]: _date(run["run_date"], f"{run['id']}.run_date") for run in runs}
    corrections: list[dict[str, Any]] = []
    withdrawn: set[Target] = set()
    successors: set[Target] = set()
    correction_ids: set[str] = set()
    graph: dict[Target, Target] = {}
    cutoff = dt.datetime.fromisoformat(issued_at)
    for owner in runs:
        owner_id = owner["id"]
        rows = _rows(owner.get("corrections", []), f"{owner_id}.corrections")
        for correction in sorted(rows, key=lambda row: row["id"]):
            correction_id = correction["id"]
            if correction_id in correction_ids:
                _fail(f"duplicate correction id {correction_id!r}")
            correction_ids.add(correction_id)
            unknown = set(correction) - CORRECTION_FIELDS
            missing = _REQUIRED_CORRECTION_FIELDS - set(correction)
            if unknown or missing:
                _fail(f"{correction_id} unknown fields {sorted(unknown, key=str)!r}; missing fields {sorted(missing)!r}")
            for field in _REQUIRED_CORRECTION_FIELDS - {"evidence_refs"}:
                _text(correction[field], f"{correction_id}.{field}")
            _strings(correction["evidence_refs"], f"{correction_id}.evidence_refs", nonempty=True)
            action = correction["action"]
            collection = correction["target_collection"]
            if action not in {"withdraw", "replace"}:
                _fail(f"{correction_id} unknown action {action!r}")
            if collection not in TARGET_COLLECTIONS:
                _fail(f"{correction_id} unknown target_collection {collection!r}")
            key = (collection, correction["target_evaluation_run_ref"], correction["target_ref"])
            if key not in index:
                _fail(f"{correction_id} dangling or wrong-kind target {key!r}")
            if key in withdrawn:
                _fail(f"{correction_id} duplicate correction target {key!r}")
            if collection in REGISTRY_COLLECTIONS:
                if owner_id != snapshot_owner or key[1] != snapshot_owner:
                    _fail(f"{correction_id} registry target and correction must belong to snapshot owner")
                if _v1._registry_row_activation(index[key], registry_name=collection) > cutoff:
                    _fail(f"{correction_id} targets a future registry row")
            elif run_dates[key[1]] >= run_dates[owner_id]:
                _fail(f"{correction_id} self/future or same-day target; target run must have an earlier calendar date")
            digest = correction["target_sha256"]
            if not re.fullmatch(r"[0-9a-f]{64}", digest) or digest != canonical_sha256(index[key]):
                _fail(f"{correction_id} target_sha256 does not match exact raw target {key!r}")
            if action == "withdraw":
                if "replacement_ref" in correction:
                    _fail(f"{correction_id} withdrawal forbids replacement_ref")
            else:
                if collection == "evaluation_run":
                    _fail(f"{correction_id} whole evaluation_run replacement is forbidden")
                replacement_ref = _text(correction.get("replacement_ref"), f"{correction_id}.replacement_ref")
                successor = (collection, owner_id, replacement_ref)
                if successor not in index:
                    _fail(f"{correction_id} replacement must be same-kind row in correction owner")
                if replacement_ref == key[2]:
                    _fail(f"{correction_id} replacement must have a new id")
                if any(
                    other != successor and other[0] == collection and other[2] == replacement_ref
                    for other in index
                ):
                    _fail(f"{correction_id} replacement id {replacement_ref!r} is already used by another source row")
                if successor in successors:
                    _fail(f"{correction_id} duplicate correction successor {successor!r}")
                if collection in REGISTRY_COLLECTIONS:
                    replacement_activation = _v1._registry_row_activation(index[successor], registry_name=collection)
                    if replacement_activation > cutoff:
                        _fail(f"{correction_id} replacement is a future registry row")
                    if replacement_activation < _v1._registry_row_activation(index[key], registry_name=collection):
                        _fail(f"{correction_id} replacement registry row activates before its target")
                _check_replacement_identity(index[key], index[successor], correction_id)
                successors.add(successor)
                graph[key] = successor
            withdrawn.add(key)
            corrections.append(correction)
    for start in graph:
        visited: set[Target] = set()
        cursor = start
        while cursor in graph:
            if cursor in visited:
                _fail(f"correction replacement cycle at {cursor!r}")
            visited.add(cursor)
            cursor = graph[cursor]
    return corrections, withdrawn


def validate_active_dependencies(
    runs: list[dict[str, Any]], raw_runs: list[dict[str, Any]] | None = None,
    *, registry_rows: list[dict[str, Any]] | None = None,
    registry_owner: str | None = None,
) -> None:
    """Fail if a surviving row depends on evidence absent from the active view.

    Call again after subject admission. Evidence citations are deliberately not
    active dependencies: withdrawn records remain legitimate audit evidence.
    ``raw_runs`` pins each dependency's original owner before filtering and also
    checks partial removal of coupled source bundles. A same-id row in another
    run must not silently satisfy a dependency on withdrawn local evidence.

    ``registry_rows`` contains only the registry assumptions selected for actual
    emission, after time slicing, supersession, tool applicability and explicit
    withdrawals. The caller keeps the complete registry snapshot unchanged.
    ``registry_owner`` names its raw snapshot/context owner, which may itself
    have no subject-eligible measurements. Registry references use that owner's
    local raw targets first, otherwise one unambiguous global raw target.
    """
    index = _target_index(runs)
    raw_index = _target_index(raw_runs) if raw_runs is not None else index
    active_runs = {run["id"] for run in runs}

    def reference(
        ref: Any, collections: tuple[str, ...], label: str,
        local_owner: str, explicit_owner: str | None = None,
    ) -> None:
        _text(ref, label)
        candidates = [key for key in raw_index if key[0] in collections and key[2] == ref]
        if explicit_owner is not None:
            _text(explicit_owner, f"{label} source owner")
            candidates = [key for key in candidates if key[1] == explicit_owner]
        else:
            local = [key for key in candidates if key[1] == local_owner]
            if local:
                candidates = local
        if len(candidates) > 1:
            _fail(f"{label} has ambiguous raw source owners for {collections!r} target {ref!r}")
        if not candidates or candidates[0] not in index:
            _fail(f"{label} depends on missing or withdrawn {collections!r} target {ref!r}")

    def walk(value: Any, run_id: str, path: str) -> None:
        if isinstance(value, list):
            for item in value:
                walk(item, run_id, path)
            return
        if not isinstance(value, dict):
            return
        row_path = f"{path}/{value.get('id', '<value>')}"
        for field, collection in (
            ("delta_from_measurement_ref", "measurements"),
            ("measurement_ref", "measurements"),
            ("source_measurement_ref", "measurements"),
            ("ligand_ref", "ligands"), ("site_ref", "sites"),
        ):
            if field in value:
                owner = run_id if field == "delta_from_measurement_ref" else None
                if field == "source_measurement_ref":
                    owner = value.get("source_evaluation_run_ref")
                reference(value[field], (collection,), f"{row_path}.{field}", run_id, owner)
        for field in ("derived_from_measurement_refs", "supporting_measurement_refs"):
            if field in value:
                refs = _strings(value[field], f"{row_path}.{field}")
                for ref in refs:
                    # Computational operands are explicitly same-run. A headline
                    # can also cite unchanged evidence from an earlier input;
                    # resolve its original owner rather than forcing a copy.
                    owner = run_id if field == "derived_from_measurement_refs" else None
                    reference(ref, ("measurements",), f"{row_path}.{field}", run_id, owner)
        for field in ("evaluation_run_ref", "source_evaluation_run_ref"):
            if field in value:
                _text(value[field], f"{row_path}.{field}")
                if value[field] not in active_runs:
                    _fail(f"{row_path}.{field} depends on missing or withdrawn EvaluationRun {value[field]!r}")
        scope_collections = {
            "site": ("sites",), "ligand": ("ligands",),
            "domain": ("domain_assignments",), "interface": ("interface_qualities",),
            "ensemble": ("nmr_ensemble_qualities", "prediction_ensemble_qualities"),
        }
        scope = value.get("scope")
        if scope is not None:
            _text(scope, f"{row_path}.scope")
        if scope in scope_collections and "scope_selector" in value:
            reference(value["scope_selector"], scope_collections[scope], f"{row_path}.scope_selector", run_id)
        for field, child in value.items():
            if field not in {"corrections", "evidence_refs", "superseded_assumption_refs"}:
                walk(child, run_id, row_path)

    for run in runs:
        walk(run, run["id"], run["id"])

    if registry_rows is not None:
        owner = _text(registry_owner, "selected registry snapshot owner")
        if ("evaluation_run", owner, owner) not in raw_index:
            _fail(f"selected registry snapshot owner {owner!r} is not a raw input EvaluationRun")
        for row in _rows(registry_rows, "selected registry rows"):
            walk(row, owner, f"registry snapshot {owner}")
    elif registry_owner is not None:
        _fail("registry_owner requires explicit selected registry_rows")

    # Scientific bundles are one invocation, not a pool of interchangeable rows.
    # Dropping some members cannot be repaired by relabelling a new invocation.
    if raw_runs is not None:
        for raw in raw_runs:
            bundles: dict[str, set[str]] = {}
            for row in raw.get("measurements", []):
                if row.get("bundle_ref"):
                    bundles.setdefault(row["bundle_ref"], set()).add(row["id"])
            for bundle, members in bundles.items():
                present = {ref for ref in members if ("measurements", raw["id"], ref) in index}
                if present and present != members:
                    _fail(f"{raw['id']} bundle {bundle!r} has missing or withdrawn members {sorted(members - present)!r}")

    # Explicit computational lineage must remain acyclic even across operations.
    for run in runs:
        edges = {
            row["id"]: list(row.get("derived_from_measurement_refs", []))
            + ([row["delta_from_measurement_ref"]] if row.get("delta_from_measurement_ref") else [])
            for row in run.get("measurements", [])
        }
        done: set[str] = set()
        visiting: set[str] = set()

        def visit(row_id: str) -> None:
            if row_id in visiting:
                _fail(f"{run['id']} active measurement dependency cycle at {row_id!r}")
            if row_id in done:
                return
            visiting.add(row_id)
            for dependency in edges.get(row_id, []):
                visit(dependency)
            visiting.remove(row_id)
            done.add(row_id)

        for row_id in edges:
            visit(row_id)


def project_sources(documents: list[dict[str, Any]], qds_id: str, structure_id: str) -> dict[str, Any]:
    """Validate all raw lineage, then return detached active and audit views.

    Neither subject filtering nor scientific judgement happens here. The context
    owns one complete registry snapshot; legacy carriers need no retroactive
    snapshot edits. All source runs, including withdrawn runs, remain in the
    ordered raw-source digest and the context's exact source list.
    """
    _text(qds_id, "qds_id")
    _text(structure_id, "structure_id")
    if not isinstance(documents, list) or not documents:
        _fail("documents must be a non-empty list")
    documents = copy.deepcopy(documents)
    raw_runs: list[dict[str, Any]] = []
    carriers: dict[str, dict[str, Any]] = {}
    matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for number, document in enumerate(documents):
        if not isinstance(document, dict):
            _fail(f"source document {number} must be a mapping")
        for run in _rows(document.get("evaluation_runs", []), f"source {number}.evaluation_runs"):
            run_id = run["id"]
            if run_id in carriers:
                _fail(f"duplicate EvaluationRun id {run_id!r} across source documents")
            if run.get("structure_ref") != structure_id:
                _fail(f"{run_id} belongs to another structure, not {structure_id!r}")
            _date(run.get("run_date"), f"{run_id}.run_date")
            carriers[run_id] = document
            raw_runs.append(run)
        for context in _rows(document.get("qds_emission_contexts", []), f"source {number}.qds_emission_contexts"):
            if context.get("qds_ref") == qds_id:
                matches.append((context, document))
    if len(matches) != 1:
        _fail(f"contract 4 requires exactly one source-owned context for {qds_id!r}; found {len(matches)}")
    raw_runs.sort(key=lambda run: (str(run["run_date"]), run["id"]))
    context, context_carrier = matches[0]
    for field in (*_v3._CONTEXT_REQUIRED_FIELDS, "snapshot_owner_evaluation_run_ref"):
        if field == "source_evaluation_run_refs":
            _strings(context.get(field), f"context.{field}", nonempty=True)
        elif field == "issued_at":
            context[field] = _v3._canonical_context_datetime(context.get(field), label="emission context issued_at")
        else:
            _text(context.get(field), f"context.{field}")
    if context["coverage_scope"] not in {"partial", "cumulative"}:
        _fail("context coverage_scope must be partial or cumulative")
    if context["structure_ref"] != structure_id:
        _fail("context structure_ref conflicts with requested structure")
    if context["source_evaluation_run_refs"] != [run["id"] for run in raw_runs]:
        _fail("context source_evaluation_run_refs must equal all raw source runs in deterministic run_date/id order")
    owner = context["owner_evaluation_run_ref"]
    if owner not in carriers or carriers[owner] is not context_carrier:
        _fail("context owner must exist in the context's own source carrier")
    if context["snapshot_owner_evaluation_run_ref"] != owner:
        _fail("snapshot owner must equal context owner")
    issued_date = dt.datetime.fromisoformat(context["issued_at"]).date()
    for run in raw_runs:
        if _date(run["run_date"], f"{run['id']}.run_date") > issued_date:
            _fail(f"source run {run['id']!r} is later than context issued_at")

    snapshots: dict[str, list[dict[str, Any]]] = {}
    for field in _SNAPSHOT_FIELDS:
        if field not in context_carrier:
            _fail(f"snapshot owner carrier lacks complete {field} snapshot")
        snapshots[field] = _rows(context_carrier[field], f"snapshot.{field}")
    if structure_id not in {row["id"] for row in snapshots["structures"]}:
        _fail(f"authoritative structures snapshot lacks {structure_id!r}")
    tool_ids = {row["id"] for row in snapshots["tools"]}
    active_registry: dict[str, list[dict[str, Any]]] = {}
    index = _target_index(raw_runs)
    for collection, (field, supersedes) in REGISTRY_COLLECTIONS.items():
        active_registry[collection] = _v1._active_registry_rows(
            snapshots[field], issued_at=context["issued_at"],
            registry_name=collection, supersedes_field=supersedes,
        )
        for row in snapshots[field]:
            if row.get("tool_ref") is not None:
                _text(row["tool_ref"], f"{collection} row {row['id']!r} tool_ref")
                if row["tool_ref"] not in tool_ids:
                    _fail(f"{collection} row {row['id']!r} references missing snapshot tool {row['tool_ref']!r}")
            index[(collection, owner, row["id"])] = row
    legacy = _legacy_targets(raw_runs, index)
    corrections, withdrawn = _validated_corrections(raw_runs, index, owner, context["issued_at"])
    if withdrawn & legacy:
        _fail("typed correction duplicates a legacy assumption withdrawal")
    suppressed = withdrawn | legacy
    runs = copy.deepcopy(raw_runs)
    runs = [run for run in runs if ("evaluation_run", run["id"], run["id"]) not in suppressed]
    if owner not in {run["id"] for run in runs}:
        _fail("context/snapshot owner cannot be withdrawn")
    for run in runs:
        run_id = run["id"]
        run.pop("superseded_assumption_refs", None)
        if ("headline_verdict", run_id, run_id) in suppressed:
            run.pop("headline_verdict", None)
        for collection in RUN_ROW_COLLECTIONS:
            if collection in run:
                run[collection] = [row for row in run[collection] if (collection, run_id, row["id"]) not in suppressed]
        for collection, parent in NESTED_COLLECTIONS.items():
            for row in run.get(parent, []):
                if "assumptions" in row:
                    row["assumptions"] = [a for a in row["assumptions"] if (collection, run_id, a["id"]) not in suppressed]
    validate_active_dependencies(runs, raw_runs)
    withdrawn_registry_ids = {
        collection: sorted(key[2] for key in withdrawn if key[0] == collection)
        for collection in REGISTRY_COLLECTIONS
    }
    raw_digest = canonical_sha256({"evaluation_runs": raw_runs})
    result = {
        "context": context, "raw_runs": raw_runs, "runs": runs,
        **snapshots, "corrections": corrections,
        "raw_source_sha256": raw_digest, "source_evaluation_runs_sha256": raw_digest,
        "withdrawn_registry_ids": withdrawn_registry_ids,
        "legacy_superseded_assumption_refs": sorted(key[2] for key in legacy),
        "active_evaluation_run_refs": [run["id"] for run in runs],
    }
    for collection, rows in active_registry.items():
        result[f"active_registry_{collection}"] = [
            row for row in rows if row["id"] not in withdrawn_registry_ids[collection]
        ]
    # Output branches are detached as well: mutating a projected row or returned
    # correction must not silently alter the raw audit view in the same result.
    return {key: copy.deepcopy(value) for key, value in result.items()}
