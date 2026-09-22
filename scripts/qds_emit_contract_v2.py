#!/usr/bin/env python3
"""Frozen QualityDataSheet emitter contract version 2.

Contract 2 retains every contract-1 emission rule and adds one narrowly scoped
trust rule: the T14 flip-set conflict count derives coverage from its validated
standalone-reduce and mmtbx.reduce2 candidate inventories.  The adapter is
intentionally pinned to the immutable contract-1 source below.  Do not change
output behavior in place; add another contract module/version instead.
"""
from __future__ import annotations

import hashlib
import re
import types
from decimal import Decimal
from pathlib import Path
from typing import Any

import qds_emit_contract_v1 as _v1


QDS_EMITTER_CONTRACT_VERSION = "2"
SUPPORTED_QDS_EMITTER_CONTRACT_VERSIONS = frozenset({"2"})

# Contract 2 reuses the frozen contract-1 machinery rather than copying three
# thousand lines.  Pin the dependency bytes so a change to v1 cannot silently
# change a contract-2 replay while leaving this module's own digest untouched.
CONTRACT_V1_DEPENDENCY_SHA256 = (
    "4f36031377783bc7e3859386f238b333c4615969f9bd6c77178b94f27234540d"
)
_actual_v1_digest = hashlib.sha256(Path(_v1.__file__).read_bytes()).hexdigest()
if _actual_v1_digest != CONTRACT_V1_DEPENDENCY_SHA256:
    raise RuntimeError(
        "qds_emit contract 2 cannot load: retained contract-1 dependency "
        f"digest is {_actual_v1_digest}, expected {CONTRACT_V1_DEPENDENCY_SHA256}"
    )


# Public/replay-facing names used by the trust and referential-integrity gates.
QdsCompletenessError = _v1.QdsCompletenessError
METRIC_TO_QDS_SLOT = dict(_v1.METRIC_TO_QDS_SLOT)
COVERAGE_ONLY_METRIC_IDS = frozenset(
    {
        "T14_asn_gln_his_flip_candidates_scored",
        "T14_asn_gln_his_flip_set_conflicts",
    }
)
_tool_families_from_rows = _v1._tool_families_from_rows
_canonicalize_measurement_tools = _v1._canonicalize_measurement_tools
_explicit_subjects = _v1._explicit_subjects
_annotated_runs = _v1._annotated_runs
_final_or_all_measurements = _v1._final_or_all_measurements
_check_trust_invariant = _v1._check_trust_invariant


def _validate_routing_table() -> None:
    """Validate v2's explicit routed and coverage-only metric dispositions."""
    catalog_ids = _v1._load_catalog_metric_ids()
    missing = sorted(
        metric_id
        for metric_id in set(METRIC_TO_QDS_SLOT) | set(COVERAGE_ONLY_METRIC_IDS)
        if metric_id not in catalog_ids
    )
    overlap = sorted(COVERAGE_ONLY_METRIC_IDS.intersection(METRIC_TO_QDS_SLOT))
    if overlap:
        raise SystemExit(
            "qds_emit contract 2: metrics cannot be both scalar-routed and "
            "coverage-only:\n  "
            + "\n  ".join(overlap)
        )
    if missing:
        raise SystemExit(
            "qds_emit contract 2: QDS metric disposition references ids not in "
            "ref/catalog.yaml:\n  "
            + "\n  ".join(missing)
        )


DERIVED_COVERAGE_CONTEXT_FIELDS = (
    "catalog_task_ref",
    "subject_ref",
    "reference_subject_ref",
    "stage",
    "scope",
    "scope_selector",
)
DERIVED_COVERAGE_CONTRACTS: dict[str, dict[str, Any]] = {
    "T14_asn_gln_his_flip_set_conflicts": {
        "catalog_task_ref": "T14",
        "carrier_tool": "mmtbx.reduce2",
        "source_metric": "T14_asn_gln_his_flip_candidates_scored",
        "source_tools": frozenset(
            {"reduce (standalone, Richardson)", "mmtbx.reduce2"}
        ),
    },
}


def _has_numeric_oracle_value(measurement: dict[str, Any]) -> bool:
    return _v1._finite_numeric_value(measurement) is not None


_NON_CRITERION_TEXT = {
    "",
    "n/a",
    "na",
    "-",
    "--",
    "none",
    "informational",
}


def _require_informational_coverage_source(
    measurement: dict[str, Any], *, location: str
) -> None:
    if measurement.get("pass_status") != "informational":
        raise QdsCompletenessError(
            "QDS derived-coverage integrity failed: "
            f"{location} must have pass_status 'informational'"
        )
    for carrier_name, carrier in (
        ("measurement", measurement),
        ("oracle_measure", measurement.get("oracle_measure")),
    ):
        if not isinstance(carrier, dict):
            continue
        status = carrier.get("pass_status")
        if carrier_name == "oracle_measure" and status not in (
            None,
            "",
            "informational",
        ):
            raise QdsCompletenessError(
                "QDS derived-coverage integrity failed: "
                f"{location} {carrier_name} carries grade {status!r}"
            )
        criterion = str(carrier.get("pass_criterion") or "").strip()
        if criterion.casefold() not in _NON_CRITERION_TEXT:
            raise QdsCompletenessError(
                "QDS derived-coverage integrity failed: "
                f"{location} {carrier_name} carries criterion {criterion!r}"
            )


def _is_t14_conflict_rate_criterion(value: Any) -> bool:
    text = str(value or "").strip().casefold().replace("≤", "<=")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*<=\s*", " <= ", text)
    text = re.sub(r"\s*%\s*", "%", text).strip()
    return text == "conflict rate <= 10%"


def _validate_t14_cohort_verdict(
    measurement: dict[str, Any],
    *,
    numerator: int,
    denominator: int,
    location: str,
) -> None:
    status = measurement.get("pass_status")
    if status == "informational":
        _require_informational_coverage_source(measurement, location=location)
        return
    passes = numerator * 10 <= denominator
    expected = {"pass", "pass_with_caveat"} if passes else {"fail_criterion"}
    if status not in expected:
        raise QdsCompletenessError(
            "QDS derived-coverage integrity failed: "
            f"{location} conflict rate {numerator}/{denominator} requires "
            f"pass_status in {sorted(expected)!r}, not {status!r}"
        )
    if not _is_t14_conflict_rate_criterion(measurement.get("pass_criterion")):
        raise QdsCompletenessError(
            "QDS derived-coverage integrity failed: "
            f"{location} requires an unambiguous pass_criterion naming "
            "conflict rate <= 10%"
        )
    nested = measurement.get("oracle_measure")
    if not isinstance(nested, dict):
        return
    nested_status = nested.get("pass_status")
    nested_criterion = str(nested.get("pass_criterion") or "").strip()
    if nested_status in (None, "") and not nested_criterion:
        return
    if nested_status not in expected:
        raise QdsCompletenessError(
            "QDS derived-coverage integrity failed: "
            f"{location} oracle_measure verdict does not match conflict rate "
            f"{numerator}/{denominator}; expected {sorted(expected)!r}, not "
            f"{nested_status!r}"
        )
    if not _is_t14_conflict_rate_criterion(nested.get("pass_criterion")):
        raise QdsCompletenessError(
            "QDS derived-coverage integrity failed: "
            f"{location} oracle_measure requires an unambiguous pass_criterion "
            "naming conflict rate <= 10%"
        )


def _integral_coverage_count(
    measurement: dict[str, Any],
    field: str,
    *,
    minimum: int,
    location: str,
) -> int:
    payload = measurement.get("oracle_measure")
    value = payload.get(field) if isinstance(payload, dict) else None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise QdsCompletenessError(
            "QDS derived-coverage integrity failed: "
            f"{location} oracle_measure.{field} must be an integral count"
        )
    decimal = Decimal(str(value))
    if (
        not decimal.is_finite()
        or decimal != decimal.to_integral_value()
        or decimal < minimum
    ):
        raise QdsCompletenessError(
            "QDS derived-coverage integrity failed: "
            f"{location} oracle_measure.{field} must be an integral count "
            f">= {minimum}"
        )
    unit = str(payload.get("unit") or "").strip().casefold()
    if unit != "count":
        raise QdsCompletenessError(
            "QDS derived-coverage integrity failed: "
            f"{location} requires oracle_measure.unit 'count'"
        )
    return int(decimal)


def _derived_coverage_participants(
    measurements: list[dict[str, Any]],
) -> dict[int, set[tuple[str, str]]]:
    """Resolve the exact tools participating in each numeric result.

    Generic provenance never grants trust coverage.  Only an explicit composite
    contract may inherit source families, and every source must be unique in the
    same EvaluationRun, match the complete claim context, carry a finite numeric
    value, and use the contracted metric/tool pair.
    """
    by_run_and_id: dict[tuple[str, str], list[dict[str, Any]]] = {}
    by_id: dict[str, list[dict[str, Any]]] = {}
    for measurement in measurements:
        measurement_id = str(measurement.get("id") or "").strip()
        owner_run_id = str(
            measurement.get("_source_evaluation_run_ref") or ""
        ).strip()
        if measurement_id:
            by_id.setdefault(measurement_id, []).append(measurement)
        if measurement_id and owner_run_id:
            by_run_and_id.setdefault((owner_run_id, measurement_id), []).append(
                measurement
            )

    participants: dict[int, set[tuple[str, str]]] = {}
    for measurement in measurements:
        own: set[tuple[str, str]] = set()
        if _has_numeric_oracle_value(measurement):
            family = str(measurement.get("oracle_family") or "unclassified")
            tool = str(measurement.get("oracle_tool_ref") or "<unnamed oracle>")
            own.add((family, tool))
        participants[id(measurement)] = own

        metric_id = str(measurement.get("metric_definition_ref") or "")
        contract = DERIVED_COVERAGE_CONTRACTS.get(metric_id)
        if contract is None:
            continue

        measurement_id = str(measurement.get("id") or "<missing id>")
        location = f"derived measurement {measurement_id!r}"
        refs = measurement.get("derived_from_measurement_refs")
        expected_tools = set(contract["source_tools"])
        if (
            not isinstance(refs, list)
            or len(refs) != len(expected_tools)
            or not all(isinstance(ref, str) and ref.strip() for ref in refs)
            or len(set(refs)) != len(refs)
        ):
            raise QdsCompletenessError(
                "QDS derived-coverage integrity failed: "
                f"{location} requires exactly {len(expected_tools)} distinct, "
                "non-empty derived_from_measurement_refs"
            )

        owner_run_id = str(
            measurement.get("_source_evaluation_run_ref") or ""
        ).strip()
        if not owner_run_id:
            raise QdsCompletenessError(
                "QDS derived-coverage integrity failed: "
                f"{location} has no source EvaluationRun identity"
            )
        if measurement.get("catalog_task_ref") != contract["catalog_task_ref"]:
            raise QdsCompletenessError(
                "QDS derived-coverage integrity failed: "
                f"{location} uses catalog_task_ref "
                f"{measurement.get('catalog_task_ref')!r}; expected "
                f"{contract['catalog_task_ref']!r}"
            )
        if measurement.get("oracle_tool_ref") != contract["carrier_tool"]:
            raise QdsCompletenessError(
                "QDS derived-coverage integrity failed: "
                f"{location} uses carrier tool "
                f"{measurement.get('oracle_tool_ref')!r}; expected "
                f"{contract['carrier_tool']!r}"
            )
        if not str(measurement.get("subject_ref") or "").strip():
            raise QdsCompletenessError(
                "QDS derived-coverage integrity failed: "
                f"{location} requires a non-empty subject_ref"
            )
        if measurement.get("scope") == "cohort":
            if not str(measurement.get("scope_selector") or "").strip():
                raise QdsCompletenessError(
                    "QDS derived-coverage integrity failed: "
                    f"{location} with scope 'cohort' requires a non-empty "
                    "scope_selector naming the preregistered cohort"
                )
        else:
            _require_informational_coverage_source(
                measurement, location=location
            )
        numerator = _integral_coverage_count(
            measurement,
            "value_numeric",
            minimum=0,
            location=location,
        )
        denominator = _integral_coverage_count(
            measurement,
            "count",
            minimum=1,
            location=location,
        )
        if numerator > denominator:
            raise QdsCompletenessError(
                "QDS derived-coverage integrity failed: "
                f"{location} conflict count {numerator} exceeds denominator "
                f"{denominator}"
            )
        if measurement.get("scope") == "cohort":
            _validate_t14_cohort_verdict(
                measurement,
                numerator=numerator,
                denominator=denominator,
                location=location,
            )

        sources: list[dict[str, Any]] = []
        source_candidate_counts: list[int] = []
        for ref in refs:
            targets = by_run_and_id.get((owner_run_id, ref), [])
            if len(targets) != 1:
                elsewhere = by_id.get(ref, [])
                detail = (
                    "belongs to another EvaluationRun"
                    if elsewhere and not targets
                    else "does not resolve uniquely in its owning EvaluationRun"
                )
                raise QdsCompletenessError(
                    "QDS derived-coverage integrity failed: "
                    f"{location} source ref {ref!r} {detail}"
                )
            source = targets[0]
            source_id = str(source.get("id") or ref)
            for field in DERIVED_COVERAGE_CONTEXT_FIELDS:
                if source.get(field) != measurement.get(field):
                    raise QdsCompletenessError(
                        "QDS derived-coverage integrity failed: "
                        f"{location} source {source_id!r} has mismatched {field} "
                        f"(derived={measurement.get(field)!r}, "
                        f"source={source.get(field)!r})"
                    )
            if source.get("metric_definition_ref") != contract["source_metric"]:
                raise QdsCompletenessError(
                    "QDS derived-coverage integrity failed: "
                    f"{location} source {source_id!r} measures "
                    f"{source.get('metric_definition_ref')!r}; expected "
                    f"{contract['source_metric']!r}"
                )
            if not _has_numeric_oracle_value(source):
                raise QdsCompletenessError(
                    "QDS derived-coverage integrity failed: "
                    f"{location} source {source_id!r} has no finite numeric oracle value"
                )
            _require_informational_coverage_source(
                source, location=f"{location} source {source_id!r}"
            )
            source_candidate_counts.append(
                _integral_coverage_count(
                    source,
                    "value_numeric",
                    minimum=1,
                    location=f"{location} source {source_id!r}",
                )
            )
            sources.append(source)

        source_tools = {
            str(source.get("oracle_tool_ref") or "") for source in sources
        }
        if source_tools != expected_tools:
            raise QdsCompletenessError(
                "QDS derived-coverage integrity failed: "
                f"{location} source tools are {sorted(source_tools)!r}; expected "
                f"{sorted(expected_tools)!r}"
            )
        if denominator > min(source_candidate_counts):
            raise QdsCompletenessError(
                "QDS derived-coverage integrity failed: "
                f"{location} denominator {denominator} exceeds a source candidate "
                f"count ({sorted(source_candidate_counts)!r})"
            )
        for source in sources:
            family = str(source.get("oracle_family") or "unclassified")
            tool = str(source.get("oracle_tool_ref") or "<unnamed oracle>")
            own.add((family, tool))

    return participants


def build_cross_tool_coverage(
    qds_id: str,
    measurements: list[dict[str, Any]],
    subject_ref: str | None = None,
    tool_families: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build metric/context-scoped coverage, including contracted composites."""
    canonical_measurements = _v1._canonicalize_measurement_tools(
        measurements,
        context="cross-tool coverage",
        tool_families=tool_families,
    )
    participants_by_row = _derived_coverage_participants(canonical_measurements)
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for measurement in canonical_measurements:
        if not measurement.get("catalog_task_ref"):
            continue
        _v1._validate_measurement_value_carriers(measurement, require_oracle=True)
        grouped.setdefault(_v1._coverage_context_key(measurement), []).append(
            measurement
        )

    rows: list[dict[str, Any]] = []
    for context in sorted(grouped):
        candidates = _v1._eligible_for_subject(grouped[context], subject_ref)
        exact = [row for row in candidates if row.get("subject_ref") == subject_ref]
        if subject_ref is not None and exact:
            candidates = exact

        numeric = [row for row in candidates if _has_numeric_oracle_value(row)]
        text_only = [
            row
            for row in candidates
            if not _has_numeric_oracle_value(row) and _v1._has_oracle_payload(row)
        ]
        for measurement in candidates:
            if (
                measurement.get("metric_definition_ref")
                in _v1.TEXTUAL_SUMMARY_METRIC_IDS
            ):
                _v1._is_selectable_summary_measurement(measurement)

        buckets: dict[str, set[str]] = {
            "cctbx": set(),
            "non_cctbx": set(),
            "unclassified": set(),
        }
        for measurement in numeric:
            for family, tool in participants_by_row[id(measurement)]:
                if family in ("cctbx", "non_cctbx"):
                    buckets[family].add(tool)
                else:
                    buckets["unclassified"].add(tool)

        def verdict_classes(family: str) -> set[str]:
            classes: set[str] = set()
            for measurement in numeric:
                if measurement.get("oracle_family") != family:
                    continue
                status = str(measurement.get("pass_status") or "")
                if status in _v1.PASSING_STATUSES:
                    classes.add("pass")
                elif status == "fail_criterion" or status.startswith(
                    "fail_by_oracle"
                ):
                    classes.add("fail")
            return classes

        cctbx_verdicts = verdict_classes("cctbx")
        non_cctbx_verdicts = verdict_classes("non_cctbx")
        if (
            cctbx_verdicts
            and non_cctbx_verdicts
            and len(cctbx_verdicts | non_cctbx_verdicts) > 1
        ):
            ids = ", ".join(
                str(row.get("id") or "<missing id>") for row in numeric
            )
            raise QdsCompletenessError(
                "QDS cross-tool coverage found contradictory cctbx/non-cctbx "
                f"pass-status classes for one claim context ({ids}); an explicit "
                "resolution or tiebreaker is required before publication"
            )

        cctbx = sorted(buckets["cctbx"])
        non_cctbx = sorted(buckets["non_cctbx"])
        unclassified = sorted(buckets["unclassified"])
        attempts = sorted(
            {
                str(row.get("oracle_tool_ref") or "<unnamed oracle>")
                for row in text_only
            }
        )
        if not numeric:
            gap = "informational — non-numeric measurement"
            if attempts:
                gap += f" (not counted as coverage: {', '.join(attempts)})"
        elif non_cctbx:
            gap = (
                "dual-family coverage — agreement not evaluated"
                if cctbx
                else "non-cctbx only"
            )
        elif cctbx:
            gap = "open — cctbx only"
        else:
            gap = "unknown — no oracle_family on numeric measurement"
        if unclassified:
            gap += f" (oracle_family missing on: {', '.join(unclassified)})"
        if numeric and attempts:
            gap += f" (non-numeric attempts excluded: {', '.join(attempts)})"

        first = candidates[0]
        row: dict[str, Any] = {
            "id": _v1._coverage_id(qds_id, context),
            "catalog_task_ref": first["catalog_task_ref"],
            "cctbx_oracles": cctbx,
            "non_cctbx_oracles": non_cctbx,
            "gap_status": gap,
        }
        for field in (
            "metric_definition_ref",
            "subject_ref",
            "reference_subject_ref",
            "stage",
            "scope",
            "scope_selector",
        ):
            value = first.get(field)
            if value not in (None, ""):
                row[field] = value
        rows.append(row)
    return {"id": f"{qds_id}_coverage", "task_coverage": rows}


# Clone the frozen contract-1 core with only the coverage builder rebound.  The
# base source is digest-pinned above; the clone avoids runtime mutation of the v1
# module and remains safe for concurrent v1/v2 replay in one process.
_contract_2_globals = dict(_v1._emit_qds_contract_1.__globals__)
_contract_2_globals["build_cross_tool_coverage"] = build_cross_tool_coverage
_contract_2_globals["_validate_routing_table"] = _validate_routing_table
_contract_2_base = types.FunctionType(
    _v1._emit_qds_contract_1.__code__,
    _contract_2_globals,
    "_contract_2_base",
    _v1._emit_qds_contract_1.__defaults__,
    _v1._emit_qds_contract_1.__closure__,
)
_contract_2_base.__kwdefaults__ = _v1._emit_qds_contract_1.__kwdefaults__


def _emit_qds_contract_2(
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
    try:
        qds = _contract_2_base(
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
    except QdsCompletenessError as exc:
        message = str(exc).replace("contract-1", "contract-2")
        raise QdsCompletenessError(message) from None
    qds["emitter_contract_version"] = "2"
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
    if emitter_contract_version != "2":
        raise QdsCompletenessError(
            "unsupported QDS emitter contract version "
            f"{emitter_contract_version!r}; supported: 2"
        )
    return _emit_qds_contract_2(
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
