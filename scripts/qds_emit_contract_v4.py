#!/usr/bin/env python3
"""Correction-aware QualityDataSheet contract 4.

Original evidence remains immutable. A source-owned recipe selects a validated
active view before any builder; audit lineage includes withdrawn inputs. Dataset
associations admit exact T13 reflection-data subjects without relabelling them as
coordinate models. Retained contracts 1–3 are never mutated by this adapter.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
from pathlib import Path, PurePosixPath
import re
import types
from typing import Any

import yaml

import qds_emit_contract_v3 as _v3
from strict_yaml import strict_yaml_load


QDS_EMITTER_CONTRACT_VERSION = "4"
SUPPORTED_QDS_EMITTER_CONTRACT_VERSIONS = frozenset({"4"})
QdsCompletenessError = _v3.QdsCompletenessError
_v2 = _v3._v2
_v1 = _v2._v1
REPO = Path(__file__).resolve().parent.parent
METRIC_TO_QDS_SLOT = dict(_v3.METRIC_TO_QDS_SLOT)
COVERAGE_ONLY_METRIC_IDS = _v3.COVERAGE_ONLY_METRIC_IDS
CONTRACT_V3_DEPENDENCY_SHA256 = "482395d25551a79803b8addb506d0115161b9500058cfae6593a7419d632e2d4"
if hashlib.sha256(Path(_v3.__file__).read_bytes()).hexdigest() != CONTRACT_V3_DEPENDENCY_SHA256:
    raise RuntimeError("contract 4 retained contract-3 dependency digest changed")

# Pin the correction/dependency policy as part of this retained contract.
PROJECTION_DEPENDENCY_SHA256 = "25a0cb025ef263153e4e1e6467d6ba0c6ef3d27409879d18f72e300f4a429859"


def _projection_module() -> Any:
    import qds_correction_projection as projection

    actual = hashlib.sha256(Path(projection.__file__).read_bytes()).hexdigest()
    if actual != PROJECTION_DEPENDENCY_SHA256:
        raise QdsCompletenessError("contract 4 correction projection dependency digest changed")
    return projection


def _fail(message: str) -> None:
    raise QdsCompletenessError(f"QDS contract-4 integrity failed: {message}")


def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{label} must be a non-empty string")
    return value


def _list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        _fail(f"{label} must be a list")
    return value


def _read_documents(paths: list[Path]) -> list[dict[str, Any]]:
    documents = []
    for path in paths:
        try:
            doc = strict_yaml_load(path.read_text())
        except (OSError, UnicodeError, yaml.YAMLError, ValueError) as exc:
            _fail(f"cannot load source {path}: {exc}")
        if not isinstance(doc, dict):
            _fail(f"source {path} must be a mapping")
        documents.append(doc)
    return documents


def _dataset_associations(
    context: dict[str, Any], runs: list[dict[str, Any]], repo_root: Path,
) -> list[dict[str, Any]]:
    associations = _list(context.get("dataset_associations", []), "dataset_associations")
    required = {
        "id", "model_subject_ref", "dataset_subject_ref", "dataset_path",
        "dataset_sha256", "owner_evaluation_run_ref", "catalog_task_ref", "stage",
        "scope", "scope_selectors", "evidence_refs",
    }
    run_map = {run["id"]: run for run in runs}
    ids: set[str] = set()
    bindings: set[tuple[str, str]] = set()
    out = []
    for row in associations:
        if not isinstance(row, dict) or set(row) != required:
            _fail("dataset association must carry exactly its typed binding fields")
        for field in required - {"scope_selectors", "evidence_refs"}:
            _nonempty(row[field], f"dataset association {field}")
        if row["id"] in ids:
            _fail(f"duplicate dataset association {row['id']!r}")
        ids.add(row["id"])
        if row["model_subject_ref"] != context["subject_ref"]:
            _fail("dataset association names a different model subject")
        digest = row["dataset_sha256"]
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            _fail("dataset_sha256 must be a lowercase SHA-256")
        if row["dataset_subject_ref"] != f"mtz:sha256:{digest}":
            _fail("dataset subject must equal mtz:sha256:<dataset_sha256>")
        if (row["catalog_task_ref"], row["stage"], row["scope"]) != ("T13", "all", "dataset"):
            _fail("dataset admission is restricted to T13/all/dataset evidence")
        selectors = _list(row["scope_selectors"], "dataset scope_selectors")
        evidence = _list(row["evidence_refs"], "dataset evidence_refs")
        if not selectors or not evidence:
            _fail("dataset association requires explicit selectors and evidence refs")
        for value in selectors + evidence:
            _nonempty(value, "dataset selector/evidence ref")
        if len(selectors) != len(set(selectors)) or len(evidence) != len(set(evidence)):
            _fail("dataset association repeats a selector/evidence ref")
        owner = row["owner_evaluation_run_ref"]
        if owner not in run_map:
            _fail("dataset association owner is not a raw input EvaluationRun")
        binding = (owner, row["dataset_subject_ref"])
        if binding in bindings:
            _fail("duplicate dataset/owner association")
        bindings.add(binding)
        path_text = row["dataset_path"]
        path = PurePosixPath(path_text)
        if (path.is_absolute() or ".." in path.parts or "\\" in path_text
                or path.as_posix() != path_text or path.suffix.lower() != ".mtz"):
            _fail("dataset_path must be a normalized repository-relative MTZ path")
        local = repo_root / path_text
        try:
            local.resolve().relative_to(repo_root.resolve())
            if local.is_symlink() or not local.is_file():
                _fail("dataset_path must resolve to a retained non-symlink file")
            actual = hashlib.sha256(local.read_bytes()).hexdigest()
        except (OSError, ValueError) as exc:
            _fail(f"dataset_path is unavailable or escapes the repository: {exc}")
        if actual != digest:
            _fail("dataset_path bytes do not match dataset_sha256")
        # Historical applicability is exact positive evidence, not a veto by
        # every same-dataset raw row. A retired mislabelled row may be the very
        # reason for the correction; it cannot anchor an assumption (#759).
        measured = [m for m in run_map[owner].get("measurements", [])
                    if _association_admits(row, m, owner)]
        if not measured:
            _fail("dataset association has no exact raw evidence in its owner")
        if not set(selectors).issubset({m.get("scope_selector") for m in measured}):
            _fail("dataset association declares an unused selector")
        out.append(copy.deepcopy(row))
    return sorted(out, key=lambda row: row["id"])


def _active_dataset_associations(
    associations: list[dict[str, Any]], runs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Validate surviving evidence strictly, then publish only active bindings."""
    run_map = {run["id"]: run for run in runs}
    active = []
    for association in associations:
        owner = association["owner_evaluation_run_ref"]
        measured = [row for row in run_map.get(owner, {}).get("measurements", [])
                    if row.get("subject_ref") == association["dataset_subject_ref"]]
        for row in measured:
            if not _association_admits(association, row, owner):
                _fail(f"active dataset evidence {row.get('id')!r} falls outside its association")
        if measured:
            selectors = {row["scope_selector"] for row in measured}
            active.append({**copy.deepcopy(association), "scope_selectors": [
                selector for selector in association["scope_selectors"] if selector in selectors
            ]})
    return active


def _association_admits(association: dict[str, Any], row: dict[str, Any], owner: str) -> bool:
    return (
        owner == association["owner_evaluation_run_ref"]
        and row.get("subject_ref") == association["dataset_subject_ref"]
        and row.get("catalog_task_ref") == association["catalog_task_ref"]
        and row.get("stage") == association["stage"]
        and row.get("scope") == association["scope"]
        and row.get("scope_selector") in association["scope_selectors"]
    )


def _subject_evidence(
    original: dict[str, Any], subject: str, associations: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Apply the same subject rule to active evidence and raw ancestry anchors."""
    run = copy.deepcopy(original)
    owned = [a for a in associations if a["owner_evaluation_run_ref"] == run["id"]]
    measurements = run.get("measurements", []) or []
    exact = [m for m in measurements if m.get("subject_ref") == subject
             or any(_association_admits(a, m, run["id"]) for a in owned)]
    legacy = [m for m in measurements if not m.get("subject_ref")]
    has_labelled = any(m.get("subject_ref") for m in measurements)
    has_exact = bool(exact)
    run["measurements"] = exact + legacy
    for key in _v1.SUBJECT_ROW_KEYS:
        rows = run.get(key, []) or []
        matched = [r for r in rows if r.get("subject_ref") == subject]
        has_labelled |= any(r.get("subject_ref") for r in rows)
        has_exact |= bool(matched)
        run[key] = matched or [r for r in rows if not r.get("subject_ref")]
    if has_labelled and not has_exact:
        return None
    if not run["measurements"] and not any(run.get(k) for k in _v1.SUBJECT_ROW_KEYS):
        return None
    return run


def _headline_support_anchors(
    raw_runs: list[dict[str, Any]], subject: str, associations: list[dict[str, Any]],
    successors: set[tuple[str, str, str]],
) -> tuple[set[tuple[str, str, str]], set[tuple[str, str, str]]]:
    """Resolve original headline support to exact, raw subject-scoped evidence.

    These are historical applicability anchors, not current support validation:
    a corrected original may have retired operands, while every surviving
    headline still passes the projection's active-dependency check. A successor
    cannot establish its own ancestry by borrowing its carrier's other data.
    """
    raw_by_id: dict[str, list[tuple[str, str]]] = {}
    eligible: set[tuple[str, str]] = set()
    for run in raw_runs:
        for measurement in run.get("measurements", []):
            raw_by_id.setdefault(measurement["id"], []).append((run["id"], measurement["id"]))
        admitted = _subject_evidence(run, subject, associations)
        if admitted is not None:
            eligible.update((run["id"], measurement["id"]) for measurement in admitted["measurements"])
    declared: set[tuple[str, str, str]] = set()
    anchored: set[tuple[str, str, str]] = set()
    for run in raw_runs:
        for finding in run.get("headline_findings", []):
            key = ("headline_findings", run["id"], finding["id"])
            refs = finding.get("supporting_measurement_refs")
            if not refs:
                continue
            declared.add(key)
            if key in successors or not isinstance(refs, list) or not all(isinstance(ref, str) for ref in refs):
                continue
            resolved: set[tuple[str, str]] = set()
            for ref in refs:
                candidates = raw_by_id.get(ref, [])
                local = [candidate for candidate in candidates if candidate[0] == run["id"]]
                candidates = local or candidates
                if len(candidates) != 1 or candidates[0] not in eligible:
                    break
                resolved.add(candidates[0])
            else:
                if len(resolved) == len(refs):
                    anchored.add(key)
    return anchored, declared


def _assumption_reference_anchors(
    raw_runs: list[dict[str, Any]], subject: str, associations: list[dict[str, Any]],
    registry_rows: list[dict[str, Any]] | None = None, registry_owner: str | None = None,
) -> tuple[set[tuple[str, str, str]], set[tuple[str, str, str]]]:
    """Explicit references constrain historical applicability, not just survival.

    Resolve the raw binding local-first, otherwise globally unique, exactly as
    active dependency validation does. A selected sibling or a successor's new
    reference cannot supply missing/foreign/ambiguous original evidence.
    """
    raw_by_id: dict[str, list[tuple[str, str]]] = {}
    eligible: set[tuple[str, str]] = set()
    entries = []
    for run in raw_runs:
        owner = run["id"]
        for measurement in run.get("measurements", []):
            raw_by_id.setdefault(measurement["id"], []).append((owner, measurement["id"]))
        admitted = _subject_evidence(run, subject, associations)
        if admitted is not None:
            eligible.update((owner, m["id"]) for m in admitted["measurements"])
        entries.extend((("assumptions", owner, row["id"]), row)
                       for row in run.get("assumptions", []))
        for collection, parent in (("measurement_assumptions", "measurements"),
                                   ("headline_assumptions", "headline_findings")):
            entries.extend(((collection, owner, row["id"]), row)
                           for container in run.get(parent, []) for row in container.get("assumptions", []))
    entries.extend((("tool_assumptions", registry_owner, row["id"]), row)
                   for row in registry_rows or [])
    declared, anchored = set(), set()
    for key, row in entries:
        if not row.get("measurement_ref"):
            continue
        declared.add(key)
        candidates = raw_by_id.get(row["measurement_ref"], [])
        local = [candidate for candidate in candidates if candidate[0] == key[1]]
        candidates = local or candidates
        if len(candidates) == 1 and candidates[0] in eligible:
            anchored.add(key)
    return declared, anchored


def _admit_runs(
    runs: list[dict[str, Any]], subject: str, associations: list[dict[str, Any]],
    raw_runs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Preserve applicable terminal replacements, even across retired owners."""
    active = {run["id"]: admitted for run in runs
              if (admitted := _subject_evidence(run, subject, associations)) is not None}
    raw_admitted = {run["id"]: admitted for run in raw_runs
                    if (admitted := _subject_evidence(run, subject, associations)) is not None}
    raw_owners = set(raw_admitted)
    measurement_anchors = {("measurements", owner, row["id"])
                           for owner, run in raw_admitted.items() for row in run["measurements"]}
    reference_declared, reference_anchors = _assumption_reference_anchors(
        raw_runs, subject, associations,
    )
    # Follow exact successor identities back to original evidence. Intermediate
    # correction-only owners may correctly have no surviving evidence of their
    # own; using active-owner membership here would lose the terminal successor.
    predecessors = {
        (c["target_collection"], owner["id"], c["replacement_ref"]):
        (c["target_collection"], c["target_evaluation_run_ref"], c["target_ref"])
        for owner in raw_runs for c in owner.get("corrections", [])
        if c.get("action") == "replace"
    }
    parents = {
        ("headline_assumptions", run["id"], a["id"]): ("headline_findings", run["id"], f["id"])
        for run in raw_runs for f in run.get("headline_findings", []) for a in f.get("assumptions", [])
    }
    parents.update({
        ("measurement_assumptions", run["id"], a["id"]): ("measurements", run["id"], m["id"])
        for run in raw_runs for m in run.get("measurements", []) for a in m.get("assumptions", [])
    })
    support_anchors, support_declared = _headline_support_anchors(
        raw_runs, subject, associations, set(predecessors),
    )

    def original_support_allows(key: tuple[str, str, str]) -> bool:
        parent = parents.get(key, key)
        return parent not in support_declared or parent in support_anchors

    def original_subject_allows(key: tuple[str, str, str]) -> bool:
        if key in reference_declared and key not in reference_anchors:
            return False
        parent = parents.get(key, key)
        if parent[0] == "measurements":
            # A matching sibling in the same run is not evidence about this
            # measurement or its embedded assumptions (#755).
            return parent in measurement_anchors
        return key[1] in raw_owners and original_support_allows(key)

    # Whole/nested replacements can alternate in either direction. A fixed
    # point handles container/descendant ownership without recursive cycles or
    # requiring an intermediate correction-only run to contribute current data.
    keys = set(predecessors) | set(predecessors.values()) | set(parents) | set(parents.values())
    derived_containers = {parent for child, parent in parents.items() if child in predecessors}
    applicable = {key for key in keys if original_subject_allows(key)
                  and key not in predecessors and parents.get(key) not in predecessors
                  and (key not in derived_containers or key in measurement_anchors)}
    applicable.update(support_anchors)
    while True:
        before = len(applicable)
        for successor, target in predecessors.items():
            if target in applicable:
                applicable.add(successor)
        for child, parent in parents.items():
            if (child in applicable and parent not in predecessors
                    and (parent[0] != "measurements" or parent in measurement_anchors)):
                applicable.add(parent)
            if ((parent in predecessors or parent in support_anchors or parent in measurement_anchors)
                    and parent in applicable and child not in predecessors
                    and (child not in reference_declared or child in reference_anchors)):
                # Explicit child corrections retain their own ancestry; a
                # container cannot relabel an unrelated-subject replacement.
                applicable.add(child)
        if len(applicable) == before:
            break

    def applies(key: tuple[str, str, str]) -> bool:
        return key in predecessors and key in applicable

    for source in runs:
        owner = source["id"]
        substantive = owner in active
        auxiliary = active.get(owner) or {k: copy.deepcopy(source[k]) for k in
                     ("id", "run_date", "structure_ref", "catalog_tasks_applied") if k in source}
        for measurement in auxiliary.get("measurements", []):
            if "assumptions" not in measurement:
                continue
            parent = ("measurements", owner, measurement["id"])
            original_parent = parent in measurement_anchors and parent not in predecessors
            measurement["assumptions"] = [
                copy.deepcopy(row) for row in measurement["assumptions"]
                if applies(("measurement_assumptions", owner, row["id"]))
                or ((original_parent or parent in applicable)
                    and ("measurement_assumptions", owner, row["id"]) not in predecessors
                    and original_subject_allows(("measurement_assumptions", owner, row["id"])))
            ]
        for collection in ("assumptions", "cross_tool_waivers"):
            auxiliary[collection] = [copy.deepcopy(row) for row in source.get(collection, [])
                                     if applies((collection, owner, row["id"]))
                                     or (substantive and (collection, owner, row["id"]) not in predecessors
                                         and original_subject_allows((collection, owner, row["id"])))]
        headlines = []
        for finding in source.get("headline_findings", []):
            parent = ("headline_findings", owner, finding["id"])
            whole_applies = (applies(parent) or parent in support_anchors
                             or (substantive and parent not in predecessors and original_support_allows(parent)))
            kept = [copy.deepcopy(a) for a in finding.get("assumptions", [])
                    if applies(("headline_assumptions", owner, a["id"]))
                    or (whole_applies and ("headline_assumptions", owner, a["id"]) not in predecessors
                        and (("headline_assumptions", owner, a["id"]) not in reference_declared
                             or ("headline_assumptions", owner, a["id"]) in reference_anchors))]
            if whole_applies or kept:
                headlines.append({**copy.deepcopy(finding), "assumptions": kept})
        auxiliary["headline_findings"] = headlines
        if substantive or any(auxiliary.get(k) for k in ("assumptions", "cross_tool_waivers", "headline_findings")):
            active[owner] = auxiliary
    return [active[run["id"]] for run in runs if run["id"] in active]


def prepare_projection(
    documents: list[dict[str, Any]], qds_id: str, structure_id: str,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    projection = _projection_module().project_sources(documents, qds_id, structure_id)
    context = projection["context"]
    associations = _dataset_associations(context, projection["raw_runs"], repo_root or REPO)
    # Validate before subject filtering could silently drop a bad surviving row.
    active_associations = _active_dataset_associations(associations, projection["runs"])
    runs = _admit_runs(projection["runs"], context["subject_ref"], associations, projection["raw_runs"])
    _projection_module().validate_active_dependencies(runs, projection["raw_runs"])
    families = _v1._tool_families_from_rows(projection["tools"], source_name="v4 snapshot")
    for run in runs:
        run["measurements"] = _v1._canonicalize_measurement_tools(
            run.get("measurements", []), context=f"EvaluationRun {run['id']}",
            tool_families=families,
        )
        _validate_active_measurements(run)
    projection["runs"] = _v1._annotated_runs(runs, None)
    projection["dataset_associations"] = active_associations
    projection["historical_dataset_associations"] = associations
    projection["tool_families"] = families
    projection["measurement_evidence_origins"] = _measurement_evidence_origins(projection)
    return projection


def _measurement_evidence_origins(projection: dict[str, Any]) -> list[dict[str, str]]:
    """Keep evidence age distinct from a correction's publication/carrier date.

    A typed replacement corrects an existing observation, including a numeric
    transcription error; it does not assert a fresh execution. Follow exact
    validated raw ownership through the whole replacement chain. The original
    carrier's declared date is an ordering proxy, not a verified execution time.
    A genuinely new observation has its own row, with an optional withdrawal of
    obsolete evidence, rather than a replacement pretending to refresh its age.
    """
    raw_runs = {run["id"]: run for run in projection["raw_runs"]}
    predecessors: dict[tuple[str, str], tuple[str, str]] = {}
    for run in raw_runs.values():
        for correction in run.get("corrections", []):
            if (correction["target_collection"], correction["action"]) == ("measurements", "replace"):
                predecessors[(run["id"], correction["replacement_ref"])] = (
                    correction["target_evaluation_run_ref"], correction["target_ref"],
                )
    origins = []
    for run in projection["runs"]:
        for row in run.get("measurements", []):
            origin = (run["id"], row["id"])
            # Projection already validates unique successors, exact targets and
            # acyclic strictly-earlier replacement ancestry, including retirees.
            while origin in predecessors:
                origin = predecessors[origin]
            origins.append({
                "source_evaluation_run_ref": run["id"], "source_measurement_ref": row["id"],
                "origin_evaluation_run_ref": origin[0], "origin_measurement_ref": origin[1],
                "origin_run_date": dt.date.fromisoformat(str(raw_runs[origin[0]]["run_date"])).isoformat(),
            })
    return sorted(origins, key=lambda row: (row["source_evaluation_run_ref"], row["source_measurement_ref"]))


_NESTED_LINEAGE = frozenset({
    "source_measurement_ref", "source_evaluation_run_ref", "metric_definition_ref",
    "oracle_tool_ref", "oracle_family", "pass_status", "pass_criterion", "subject_ref",
    "reference_subject_ref", "stage", "scope", "scope_selector", "evidence_refs", "bundle_ref",
})


def _validate_active_measurements(run: dict[str, Any]) -> None:
    for row in run.get("measurements", []):
        _v1._validate_measurement_value_carriers(row, require_oracle=True)
        for field in ("agent_claim", "oracle_measure", "delta"):
            nested = row.get(field, {})
            if set(nested) & _NESTED_LINEAGE:
                _fail(f"measurement {row.get('id')!r} carries nested QDS lineage/verdict fields")
        status = row.get("pass_status")
        if status == "informational":
            if {"pass_criterion", "pass_criterion_ref", "criterion_preconditions"} & row.keys():
                _fail(f"active informational measurement {row.get('id')!r} carries criterion fields")
        elif status in {"pass", "fail_criterion", "fail_by_oracle", "pass_with_caveat",
                        "pass_criterion_fail_headline", "fail_by_oracle_within_cctbx",
                        "criterion_inapplicable"}:
            if not row.get("pass_criterion_ref") or not row.get("pass_criterion"):
                _fail(f"active verdict {row.get('id')!r} lacks a registered criterion binding")
        else:
            _fail(f"active measurement {row.get('id')!r} has unsupported pass_status {status!r}")


_SEMANTIC_SET_FIELDS = frozenset({
    "assumptions", "criterion_preconditions", "derived_from_measurement_refs", "evidence_refs",
})


def _canonical_semantics(field: str, value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _canonical_semantics(k, v) for k, v in sorted(value.items())
                if k != "notes" and v not in (None, "", [])}
    if isinstance(value, list):
        rows = [_canonical_semantics("", v) for v in value]
        if field in _SEMANTIC_SET_FIELDS:
            keyed = {yaml.safe_dump(v, sort_keys=True, allow_unicode=True): v for v in rows}
            return [keyed[k] for k in sorted(keyed)]
        return rows
    return value


def _scientific_payload(row: dict[str, Any]) -> str:
    baseline = yaml.safe_load(_v1._scientific_payload(row))
    for field in ("agent_claim", "delta", "delta_from_measurement_ref",
                  "derived_from_measurement_refs", "pass_criterion_ref",
                  "criterion_preconditions", "assumptions"):
        if row.get(field) not in (None, "", []):
            baseline[field] = row[field]
    return yaml.safe_dump(_canonical_semantics("", baseline), sort_keys=True, allow_unicode=True)


def _clone_functions(module: Any, namespace: dict[str, Any]) -> None:
    """Bind all helper-to-helper calls to one isolated per-emission policy."""
    for name, value in vars(module).items():
        if isinstance(value, types.FunctionType) and value.__globals__ is vars(module):
            cloned = types.FunctionType(value.__code__, namespace, name, value.__defaults__, value.__closure__)
            cloned.__kwdefaults__ = value.__kwdefaults__
            namespace[name] = cloned


def _builders(projection: dict[str, Any]) -> types.SimpleNamespace:
    subject = projection["context"]["subject_ref"]
    associations = projection["dataset_associations"]
    origins = {(row["source_evaluation_run_ref"], row["source_measurement_ref"]): row
               for row in projection["measurement_evidence_origins"]}

    def origin(row: dict[str, Any]) -> dict[str, str]:
        key = (row.get("_source_evaluation_run_ref"), row.get("id"))
        if key not in origins:
            _fail(f"measurement {key!r} lacks its validated evidence origin")
        return origins[key]

    def scientific_payload(row: dict[str, Any]) -> str:
        payload = yaml.safe_load(_scientific_payload(row))
        source = origin(row)
        payload["_origin_evaluation_run_ref"] = source["origin_evaluation_run_ref"]
        payload["_origin_run_date"] = source["origin_run_date"]
        return yaml.safe_dump(payload, sort_keys=True, allow_unicode=True)

    def measurement_bundle_key(row: dict[str, Any]) -> tuple[str, ...]:
        return (*_v1._measurement_bundle_key(row), origin(row)["origin_evaluation_run_ref"])

    def bundle_key(row: dict[str, Any], fields: tuple[str, ...]) -> tuple[str, ...]:
        return (*_v1._bundle_key(row, fields), origin(row)["origin_evaluation_run_ref"])

    def eligible(rows: list[dict[str, Any]], requested: str | None) -> list[dict[str, Any]]:
        if requested != subject:
            return _v1._eligible_for_subject(rows, requested)
        return [r for r in rows if r.get("subject_ref") in (None, "", subject)
                or any(_association_admits(a, r, r.get("_source_evaluation_run_ref", ""))
                       for a in associations)]

    globals1 = dict(vars(_v1))
    _clone_functions(_v1, globals1)
    globals1["_eligible_for_subject"] = eligible
    globals1["_scientific_payload"] = scientific_payload
    globals1["_measurement_bundle_key"] = measurement_bundle_key
    globals1["_bundle_key"] = bundle_key
    def priority(row: dict[str, Any], requested: str | None) -> tuple[Any, ...]:
        original = list(_v1._candidate_priority(row, requested))
        original[-1] = -int(origin(row)["origin_run_date"].replace("-", ""))
        if requested == subject and any(
            _association_admits(a, row, row.get("_source_evaluation_run_ref", ""))
            for a in associations
        ):
            original[0] = 0
        return tuple(original)
    globals1["_candidate_priority"] = priority
    helper = types.SimpleNamespace(**globals1)
    globals2 = dict(vars(_v2))
    _clone_functions(_v2, globals2)
    globals2["_v1"] = helper
    helper.build_cross_tool_coverage = globals2["build_cross_tool_coverage"]
    return helper


def _collect_assumptions_report(projection: dict[str, Any]) -> list[dict[str, Any]]:
    """Aggregate selected assumptions without conflating distinct identities.

    Registry retirement applies only to the exact registry row, not every run
    assumption that happens to share its id. Check collisions before deduping;
    the frozen builder's first-id-wins behavior would conceal a correction's
    replacement payload behind an unrelated registry or measurement assumption.
    """
    runs = projection["runs"]
    tools = {m.get("oracle_tool_ref") for run in runs for m in run.get("measurements", [])}
    withdrawn = set(projection.get("withdrawn_registry_ids", {}).get("tool_assumptions", []))
    snapshot_owner = projection["context"]["snapshot_owner_evaluation_run_ref"]
    declared, anchored = _assumption_reference_anchors(
        projection["raw_runs"], projection["context"]["subject_ref"],
        projection["historical_dataset_associations"], projection["assumptions"], snapshot_owner,
    )
    predecessors = {
        c["replacement_ref"]: c["target_ref"] for c in projection["corrections"]
        if c["target_collection"] == "tool_assumptions" and c["action"] == "replace"
    }

    def registry_origin_allows(row: dict[str, Any]) -> bool:
        origin = row["id"]
        while origin in predecessors:
            origin = predecessors[origin]
        key = ("tool_assumptions", snapshot_owner, origin)
        return key not in declared or key in anchored

    selected_registry = [
        row for row in projection["active_registry_tool_assumptions"]
        if row.get("tool_ref") and row["tool_ref"] in tools and row["id"] not in withdrawn
        and registry_origin_allows(row)
    ]
    entries: list[tuple[dict[str, Any], str]] = [
        (row, f"registry snapshot {snapshot_owner}") for row in selected_registry
    ]
    for run in runs:
        for measurement in run.get("measurements", []):
            entries.extend(
                (row, f"{run['id']}.measurements[{measurement['id']}].assumptions")
                for row in measurement.get("assumptions", [])
            )
        entries.extend((row, f"{run['id']}.assumptions") for row in run.get("assumptions", []))
        for finding in run.get("headline_findings", []):
            entries.extend(
                (row, f"{run['id']}.headline_findings[{finding['id']}].assumptions")
                for row in finding.get("assumptions", [])
            )
    seen: dict[str, tuple[str, str]] = {}
    out: list[dict[str, Any]] = []
    for row, origin in entries:
        if not isinstance(row, dict):
            _fail(f"{origin} contains a non-mapping assumption")
        row_id = _nonempty(row.get("id"), f"{origin} assumption id")
        payload = yaml.safe_dump(row, sort_keys=True, allow_unicode=True)
        if row_id in seen:
            previous_payload, previous_origin = seen[row_id]
            if payload != previous_payload:
                _fail(f"conflicting active assumption id {row_id!r}: {previous_origin} versus {origin}")
            continue
        seen[row_id] = (payload, origin)
        out.append(copy.deepcopy(row))
    _projection_module().validate_active_dependencies(
        runs, projection["raw_runs"], registry_rows=selected_registry,
        registry_owner=snapshot_owner,
    )
    return out


def emit_projection(projection: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """Build only from the already validated active view and pinned snapshots."""
    context = projection["context"]
    for field, source_field in (("subject_ref", "subject_ref"), ("coverage_scope", "coverage_scope"),
                                ("scope_notes", "scope_notes"), ("issued_at", "issued_at"),
                                ("structure_description", "identity_description")):
        explicit = overrides.get(field)
        expected = context[source_field]
        if field == "issued_at" and explicit is not None:
            explicit = _v3._canonical_context_datetime(explicit, label="issued_at")
            expected = _v3._canonical_context_datetime(expected, label="context issued_at")
        if explicit is not None and explicit != expected:
            _fail(f"argument {field} conflicts with source-owned emission context")
    qds_id, structure = context["qds_ref"], context["structure_ref"]
    subject = context["subject_ref"]
    b = _builders(projection)
    method, resolution, space_group, _ = b._resolve_structure_identity_metadata(
        projection["structures"], structure,
        structure_method=overrides.get("structure_method"),
        resolution_a=overrides.get("resolution_a"), space_group=overrides.get("space_group"),
        structure_description=None,
    )
    runs = projection["runs"]
    measurements = [m for run in runs for m in b._final_or_all_measurements(run)]
    if not measurements and not any(run.get(k) for run in runs for k in b.SUBJECT_ROW_KEYS):
        _fail("no active evidence remains for the requested subject")
    b._validate_t16_interface_contexts(runs)
    routed = b._route_measurements(measurements, subject)
    final = b._route_measurements([m for m in measurements if m.get("stage") == "final"], subject)
    all_stage = b._route_measurements([m for m in measurements if m.get("stage") == "all"], subject)
    qds = {
        "id": qds_id, "structure_ref": structure, "subject_ref": subject,
        "derived_from_evaluation_run_refs": [r["id"] for r in projection["raw_runs"]],
        "active_evaluation_run_refs": [r["id"] for r in runs],
        "issued_at": _v3._canonical_context_datetime(context["issued_at"], label="issued_at"),
        "emitter_contract_version": "4", "emission_context_ref": context["id"],
        "coverage_scope": context["coverage_scope"], "scope_notes": context["scope_notes"],
        "identity_block": b.build_identity_block(qds_id, structure, method, resolution,
                                                 space_group, context["identity_description"]),
    }
    for name, suffix, source in (("geometry_summary", "geometry", final),
                                 ("refinement_summary", "refinement", final),
                                 ("map_summary", "map", final),
                                 ("packing_summary", "packing", routed),
                                 ("data_quality_summary", "data_quality", all_stage)):
        block = b._build_block_from_routed(qds_id, suffix, source.get(name))
        if block:
            qds[name] = block
    for name, suffix, keys in b.ROW_BEARING_SUMMARY_BLOCKS:
        block = b.build_row_bearing_summary(qds_id, suffix, routed.get(name), runs, keys, subject)
        if block:
            qds[name] = block
    for name, value in (
        ("pairwise_comparisons", b.build_pairwise_comparisons(runs)),
        ("per_residue_quality", b.build_per_residue_quality(qds_id, runs)),
        ("site_qualities", b.build_site_qualities(qds_id, runs, subject)),
        ("predicted_confidence_summary", b.build_predicted_confidence_summary(qds_id, runs, method, subject)),
    ):
        if value:
            qds[name] = value
    diagnostics = [b._wrap_value(m) for m in measurements
                   if (m.get("catalog_task_ref"), m.get("stage"), m.get("scope"))
                   == ("T13", "all", "dataset")]
    if diagnostics:
        block = qds.setdefault("data_quality_summary", {"id": f"{qds_id}_data_quality"})
        block["diagnostics"] = diagnostics
    qds["cross_tool_coverage"] = b.build_cross_tool_coverage(
        qds_id, measurements, subject, tool_families=projection["tool_families"],
    )
    tasks = {m.get("catalog_task_ref") for m in measurements}
    waivers = [w for run in runs for w in run.get("cross_tool_waivers", [])
               if w.get("catalog_task_ref") in tasks]
    if waivers:
        qds["cross_tool_waivers"] = waivers
    b._check_trust_invariant(qds, waivers)
    withdrawn = projection.get("withdrawn_registry_ids", {})
    recs = b.build_tool_recommendations_applied(runs, qds["issued_at"], projection["tool_recommendations"])
    recs = [r for r in recs if r["id"] not in withdrawn.get("tool_recommendations", [])]
    assumptions = _collect_assumptions_report(projection)
    if recs:
        qds["tool_recommendations_applied"] = recs
    if assumptions:
        qds["assumptions_report"] = assumptions
    if projection["corrections"]:
        qds["applied_corrections"] = copy.deepcopy(projection["corrections"])
    if projection["measurement_evidence_origins"]:
        qds["measurement_evidence_origins"] = copy.deepcopy(projection["measurement_evidence_origins"])
    if projection["dataset_associations"]:
        qds["dataset_associations"] = copy.deepcopy(projection["dataset_associations"])
    if context.get("corrected_qds_refs"):
        qds["corrected_qds_refs"] = list(context["corrected_qds_refs"])
    qds["headline_verdict"] = context["headline_verdict"]
    _v3._canonicalize_presentation_lists(qds)
    b._check_implied_blocks(qds, runs)
    return qds


def _load_live_registry_rows(
    repo_root: Path, filename: str, field: str,
) -> list[dict[str, Any]]:
    """Read authoring authority; replay never calls this live-only loader."""
    path = repo_root / "ref" / filename
    try:
        document = strict_yaml_load(path.read_text())
    except (OSError, UnicodeError, yaml.YAMLError, ValueError) as exc:
        _fail(f"cannot load live {field} registry {path}: {exc}")
    if not isinstance(document, dict):
        _fail(f"live {field} registry must be a mapping")
    return _list(document.get(field), f"live {field} registry rows")


def _validate_live_registry_snapshots(
    projection: dict[str, Any], repo_root: Path,
) -> None:
    """Require applicable authoring guidance without consulting it during replay.

    Relevant curated subsets are sufficient. Every applicable issue-time live
    row and its supersession ancestors must occur unchanged in the raw owner
    snapshot. Check before explicit registry withdrawals: a correction may
    retire admitted guidance, but omitting its source is not a correction.
    Source-only supersession edges cannot silently retire an applicable live
    row either; that retirement requires its exact typed correction authority.
    Extra source-owned rows remain governed by the projection's ordinary
    identity, activation, dependency and correction checks.
    """
    measurements = [row for run in projection["runs"]
                    for row in run.get("measurements", [])]
    measured_metrics = {row.get("metric_definition_ref") for row in measurements}
    measured_tools = {row.get("oracle_tool_ref") for row in measurements}
    for filename, field, collection, supersedes, applies_to, applicable in (
        ("tool_recommendations.yaml", "tool_recommendations", "tool_recommendations",
         "supersedes_recommendation_ref", "metric_definition_ref", measured_metrics),
        ("tool_assumptions.yaml", "assumptions", "tool_assumptions",
         "supersedes_assumption_ref", "tool_ref", measured_tools),
    ):
        rows = _load_live_registry_rows(repo_root, filename, field)
        active = _v1._active_registry_rows(
            rows, issued_at=projection["context"]["issued_at"],
            registry_name=f"live {field} registry", supersedes_field=supersedes,
        )
        live_by_id = {row["id"]: row for row in rows}
        applicable_ids = {row["id"] for row in active if row.get(applies_to) in applicable}
        required: set[str] = set()
        for row in active:
            if row["id"] not in applicable_ids:
                continue
            cursor = row["id"]
            while cursor not in required:
                required.add(cursor)
                predecessor = live_by_id[cursor].get(supersedes)
                if predecessor is None:
                    break
                cursor = predecessor
        source_by_id = {row["id"]: row for row in projection[field]}
        for row_id in sorted(required):
            source = source_by_id.get(row_id)
            if source is None:
                _fail(f"live {field} snapshot omits applicable registry row or ancestor {row_id!r}")
            if yaml.safe_dump(source, sort_keys=True, allow_unicode=True) != yaml.safe_dump(
                live_by_id[row_id], sort_keys=True, allow_unicode=True,
            ):
                _fail(f"live {field} snapshot row {row_id!r} differs from its exact registry source")
        source_active_ids = {
            row["id"] for row in _v1._active_registry_rows(
                projection[field], issued_at=projection["context"]["issued_at"],
                registry_name=f"source {field} snapshot", supersedes_field=supersedes,
            )
        }
        for row_id in sorted(applicable_ids - source_active_ids):
            digest = hashlib.sha256(yaml.safe_dump(
                live_by_id[row_id], sort_keys=True, allow_unicode=True,
            ).encode("utf-8")).hexdigest()
            authorized = any(
                correction.get("action") in {"withdraw", "replace"}
                and correction.get("target_collection") == collection
                and correction.get("target_evaluation_run_ref")
                == projection["context"]["snapshot_owner_evaluation_run_ref"]
                and correction.get("target_ref") == row_id
                and correction.get("target_sha256") == digest
                for correction in projection.get("corrections", [])
            )
            if not authorized:
                _fail(f"source-only {field} supersession retires applicable live row {row_id!r} "
                      "without its exact typed registry correction")


def emit_qds(
    eval_paths: list[Path], qds_id: str, structure_id: str,
    structure_method: str | None = None, subject_ref: str | None = None,
    coverage_scope: str | None = None, scope_notes: str | None = None,
    resolution_a: float | None = None, space_group: str | None = None,
    issued_at: str | None = None, structure_description: str | None = None,
    emitter_contract_version: str = "4", require_pinned_tool_snapshot: bool = False,
) -> dict[str, Any]:
    if emitter_contract_version != "4":
        _fail("unsupported emitter contract version")
    projection = prepare_projection(_read_documents(eval_paths), qds_id, structure_id)
    # Contract 4 always uses explicit owner snapshots, even for live emission.
    # Today's catalog is only an admission check, never a replacement snapshot.
    if not require_pinned_tool_snapshot:
        catalog = strict_yaml_load((REPO / "ref/catalog.yaml").read_text())
        live = _v1._tool_families_from_rows(catalog["tools"], source_name="live catalog")
        for tool, family in projection["tool_families"].items():
            if live.get(tool) != family:
                _fail(f"source Tool {tool!r} disagrees with live catalog family")
        _validate_live_registry_snapshots(projection, REPO)
    return emit_projection(
        projection, structure_method=structure_method, subject_ref=subject_ref,
        coverage_scope=coverage_scope, scope_notes=scope_notes, resolution_a=resolution_a,
        space_group=space_group, issued_at=issued_at, structure_description=structure_description,
    )
