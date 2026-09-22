#!/usr/bin/env python3
"""Frozen QualityDataSheet emitter contract version 3.

Contract 3 retains contract 2 and adds one source-owned sheet recipe for
partial QDS artifacts.  A ``QdsEmissionContext`` binds the exact
ordered source runs, structure and subject, issue timestamp, partial-scope text,
identity description, and single current headline.  This prevents a new partial
sheet from concatenating stale run-level prose while keeping contracts 1 and 2
byte-stable.

Do not change output behavior in place; add another contract module/version.
"""
from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path
from typing import Any

import yaml

import qds_emit_contract_v2 as _v2


QDS_EMITTER_CONTRACT_VERSION = "3"
SUPPORTED_QDS_EMITTER_CONTRACT_VERSIONS = frozenset({"3"})

CONTRACT_V2_DEPENDENCY_SHA256 = (
    "06c054f2757fbd975cca8c7b1252cc6dc66b21a001eeb48e478d9e69152e668a"
)
_actual_v2_digest = hashlib.sha256(Path(_v2.__file__).read_bytes()).hexdigest()
if _actual_v2_digest != CONTRACT_V2_DEPENDENCY_SHA256:
    raise RuntimeError(
        "qds_emit contract 3 cannot load: retained contract-2 dependency "
        f"digest is {_actual_v2_digest}, expected {CONTRACT_V2_DEPENDENCY_SHA256}"
    )


QdsCompletenessError = _v2.QdsCompletenessError
METRIC_TO_QDS_SLOT = dict(_v2.METRIC_TO_QDS_SLOT)
COVERAGE_ONLY_METRIC_IDS = frozenset(_v2.COVERAGE_ONLY_METRIC_IDS)
_tool_families_from_rows = _v2._tool_families_from_rows
_canonicalize_measurement_tools = _v2._canonicalize_measurement_tools
_explicit_subjects = _v2._explicit_subjects
_annotated_runs = _v2._annotated_runs
_final_or_all_measurements = _v2._final_or_all_measurements
_check_trust_invariant = _v2._check_trust_invariant
build_cross_tool_coverage = _v2.build_cross_tool_coverage
_eligible_for_subject = _v2._v1._eligible_for_subject
_is_selectable_summary_measurement = _v2._v1._is_selectable_summary_measurement
_candidate_priority = _v2._v1._candidate_priority
_scientific_payload = _v2._v1._scientific_payload


_CONTEXT_REQUIRED_FIELDS = (
    "id",
    "qds_ref",
    "owner_evaluation_run_ref",
    "structure_ref",
    "subject_ref",
    "source_evaluation_run_refs",
    "issued_at",
    "coverage_scope",
    "scope_notes",
    "identity_description",
    "headline_verdict",
)


def _matching_contexts(
    eval_paths: list[Path], qds_id: str
) -> list[tuple[dict[str, Any], set[str], Path]]:
    matches: list[tuple[dict[str, Any], set[str], Path]] = []
    for path in eval_paths:
        try:
            document = yaml.safe_load(path.read_text()) or {}
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise QdsCompletenessError(
                f"QDS contract-3 could not read {path}: {exc}"
            ) from None
        if not isinstance(document, dict):
            raise QdsCompletenessError(
                f"QDS contract-3 source {path} must be a mapping"
            )
        local_run_ids = {
            str(run.get("id"))
            for run in document.get("evaluation_runs", []) or []
            if isinstance(run, dict) and run.get("id")
        }
        contexts = document.get("qds_emission_contexts", []) or []
        if not isinstance(contexts, list):
            raise QdsCompletenessError(
                f"QDS contract-3 source {path} qds_emission_contexts must be a list"
            )
        for context in contexts:
            if not isinstance(context, dict):
                raise QdsCompletenessError(
                    f"QDS contract-3 source {path} contains a non-mapping emission context"
                )
            if context.get("qds_ref") == qds_id:
                matches.append((context, local_run_ids, path))
    return matches


def _context_value(
    context: dict[str, Any], field: str, expected_type: type
) -> Any:
    value = context.get(field)
    if not isinstance(value, expected_type) or (
        expected_type is str and not value.strip()
    ):
        raise QdsCompletenessError(
            f"QDS contract-3 emission context field {field!r} must be a non-empty "
            f"{expected_type.__name__}"
        )
    return value


def _require_no_argument_conflict(
    field: str, explicit: Any, source_value: Any
) -> None:
    if explicit is not None and explicit != source_value:
        raise QdsCompletenessError(
            f"QDS contract-3 argument {field}={explicit!r} conflicts with "
            f"source-owned emission context value {source_value!r}"
        )


def _canonical_context_datetime(value: Any, *, label: str) -> str:
    """Return one timezone-aware context instant in canonical UTC form."""
    if isinstance(value, dt.datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            parsed = None
    else:
        parsed = None
    if parsed is None:
        raise QdsCompletenessError(
            f"QDS contract-3 {label} {value!r} must be an ISO datetime"
        )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise QdsCompletenessError(
            f"QDS contract-3 {label} {value!r} must include an explicit timezone offset"
        )
    try:
        return parsed.astimezone(dt.timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        raise QdsCompletenessError(
            f"QDS contract-3 {label} {value!r} must be representable as a UTC instant"
        ) from None


def _insert_after(
    mapping: dict[str, Any], after: str, key: str, value: Any
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    inserted = False
    for existing_key, existing_value in mapping.items():
        out[existing_key] = existing_value
        if existing_key == after:
            out[key] = value
            inserted = True
    if not inserted:
        out[key] = value
    return out


def _canonicalize_presentation_lists(qds: dict[str, Any]) -> None:
    """Remove registry/source-carrier ordering from contract-3 output bytes.

    Live emission reads complete registries, whereas immutable replay concatenates
    source-owned snapshots from the referenced run carriers.  Equivalent
    recommendation and assumption sets need not arrive in the same order when a
    sheet combines tasks from multiple runs.  Their ids are corpus-unique, so
    sorting by id gives both routes one content-preserving canonical projection.
    """
    for field in ("tool_recommendations_applied", "assumptions_report"):
        rows = qds.get(field)
        if isinstance(rows, list):
            rows.sort(key=lambda row: str((row or {}).get("id") or ""))


def _emit_qds_contract_3(
    eval_paths: list[Path],
    qds_id: str,
    structure_id: str,
    structure_method: str | None = None,
    subject_ref: str | None = None,
    coverage_scope: str | None = None,
    scope_notes: str | None = None,
    resolution_a: float | None = None,
    space_group: str | None = None,
    issued_at: str | None = None,
    structure_description: str | None = None,
    require_pinned_tool_snapshot: bool = False,
) -> dict[str, Any]:
    matches = _matching_contexts(eval_paths, qds_id)
    if len(matches) > 1:
        raise QdsCompletenessError(
            f"QDS contract-3 requires at most one source-owned emission context "
            f"for {qds_id!r}; found {len(matches)}"
        )

    context: dict[str, Any] | None = None
    if matches:
        context, local_run_ids, context_path = matches[0]
        missing = [field for field in _CONTEXT_REQUIRED_FIELDS if field not in context]
        if missing:
            raise QdsCompletenessError(
                f"QDS contract-3 emission context in {context_path} lacks required "
                f"field(s): {', '.join(missing)}"
            )
        context_id = _context_value(context, "id", str)
        context_qds = _context_value(context, "qds_ref", str)
        context_owner = _context_value(context, "owner_evaluation_run_ref", str)
        context_structure = _context_value(context, "structure_ref", str)
        context_subject = _context_value(context, "subject_ref", str)
        context_issued_at = _canonical_context_datetime(
            context.get("issued_at"), label="emission context issued_at"
        )
        context_scope = _context_value(context, "coverage_scope", str)
        context_scope_notes = _context_value(context, "scope_notes", str)
        identity_description = _context_value(
            context, "identity_description", str
        )
        context_headline = _context_value(context, "headline_verdict", str)
        context_refs = context.get("source_evaluation_run_refs")
        if not isinstance(context_refs, list) or not context_refs or not all(
            isinstance(ref, str) and ref.strip() for ref in context_refs
        ):
            raise QdsCompletenessError(
                "QDS contract-3 emission context source_evaluation_run_refs must "
                "be a non-empty list of ids"
            )
        if len(context_refs) != len(set(context_refs)):
            raise QdsCompletenessError(
                "QDS contract-3 emission context repeats a source EvaluationRun ref"
            )
        if context_owner not in context_refs:
            raise QdsCompletenessError(
                f"QDS contract-3 emission context {context_id!r} owner "
                f"{context_owner!r} is not one of its source EvaluationRuns"
            )
        if context_owner not in local_run_ids:
            raise QdsCompletenessError(
                f"QDS contract-3 emission context {context_id!r} owner "
                f"{context_owner!r} is not in the same source document"
            )
        if context_qds != qds_id:
            raise QdsCompletenessError(
                f"QDS contract-3 context qds_ref {context_qds!r} does not match {qds_id!r}"
            )
        if context_scope != "partial":
            raise QdsCompletenessError(
                "QDS contract-3 emission contexts are permitted only for partial "
                f"sheets, not coverage_scope {context_scope!r}"
            )
        _require_no_argument_conflict("structure_id", structure_id, context_structure)
        _require_no_argument_conflict("subject_ref", subject_ref, context_subject)
        _require_no_argument_conflict("coverage_scope", coverage_scope, context_scope)
        _require_no_argument_conflict("scope_notes", scope_notes, context_scope_notes)
        explicit_issued_at = (
            _canonical_context_datetime(issued_at, label="argument issued_at")
            if issued_at is not None
            else None
        )
        _require_no_argument_conflict(
            "issued_at", explicit_issued_at, context_issued_at
        )
        _require_no_argument_conflict(
            "structure_description", structure_description, identity_description
        )
        effective_subject = context_subject
        effective_scope = context_scope
        effective_scope_notes = context_scope_notes
        effective_issued_at = context_issued_at
    else:
        context_id = None
        context_refs = []
        identity_description = None
        context_headline = None
        effective_subject = subject_ref
        effective_scope = coverage_scope
        effective_scope_notes = scope_notes
        effective_issued_at = issued_at

    try:
        qds = _v2.emit_qds(
            eval_paths,
            qds_id,
            structure_id,
            structure_method,
            effective_subject,
            effective_scope,
            effective_scope_notes,
            resolution_a,
            space_group,
            effective_issued_at,
            None if context is not None else structure_description,
            emitter_contract_version="2",
            require_pinned_tool_snapshot=require_pinned_tool_snapshot,
        )
    except QdsCompletenessError as exc:
        message = str(exc).replace("contract-2", "contract-3")
        raise QdsCompletenessError(message) from None

    source_refs = qds.get("derived_from_evaluation_run_refs") or []
    emitted_scope = qds.get("coverage_scope")
    if context is None and emitted_scope == "partial":
        raise QdsCompletenessError(
            "QDS contract-3 partial emission requires exactly one "
            "source-owned QdsEmissionContext"
        )
    if context is not None and emitted_scope != "partial":
        raise QdsCompletenessError(
            "QDS contract-3 emission context cannot govern a non-partial sheet"
        )
    if context is not None:
        if context_refs != source_refs:
            raise QdsCompletenessError(
                "QDS contract-3 emission context source_evaluation_run_refs differ "
                "from the subject-admitted deterministic derivation order"
            )
        qds = _insert_after(qds, "emitter_contract_version", "emission_context_ref", context_id)
        identity = qds.get("identity_block")
        if not isinstance(identity, dict):
            raise QdsCompletenessError(
                "QDS contract-3 base emission produced no identity_block"
            )
        identity["description"] = identity_description
        qds["headline_verdict"] = context_headline
    _canonicalize_presentation_lists(qds)
    qds["emitter_contract_version"] = "3"
    return qds


def emit_qds(
    eval_paths: list[Path],
    qds_id: str,
    structure_id: str,
    structure_method: str | None = None,
    subject_ref: str | None = None,
    coverage_scope: str | None = None,
    scope_notes: str | None = None,
    resolution_a: float | None = None,
    space_group: str | None = None,
    issued_at: str | None = None,
    structure_description: str | None = None,
    emitter_contract_version: str = QDS_EMITTER_CONTRACT_VERSION,
    require_pinned_tool_snapshot: bool = False,
) -> dict[str, Any]:
    if emitter_contract_version != "3":
        raise QdsCompletenessError(
            "unsupported QDS emitter contract version "
            f"{emitter_contract_version!r}; supported: 3"
        )
    return _emit_qds_contract_3(
        eval_paths,
        qds_id,
        structure_id,
        structure_method,
        subject_ref,
        coverage_scope,
        scope_notes,
        resolution_a,
        space_group,
        issued_at,
        structure_description,
        require_pinned_tool_snapshot,
    )
