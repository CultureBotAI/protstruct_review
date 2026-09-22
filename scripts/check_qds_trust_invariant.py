#!/usr/bin/env python3
"""Gate committed QDS trust claims against their source EvaluationRuns.

For every non-legacy QDS, rebuild cross-tool coverage from the referenced
EvaluationRuns using their source-pinned Tool families. Neither editable
``gap_status`` prose nor self-asserted ``oracle_family`` metadata is
authoritative. The complete sheet is replayed with a retained emitter-contract
module and source-owned Tool/recommendation/assumption snapshots, then checked
against a source-owned canonical byte pin. Later emitter, catalog, or registry
changes therefore cannot reinterpret it.
Historical sheets are exempt only when their repository path, QDS id, exact
issue timestamp, and full-file digest match the frozen allowlist below; an
arbitrary backdated or edited file is not history.

Network-free. ``--root`` exists for the tests.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

import qds_emit_contract_v1
import qds_emit_contract_v2

try:
    from strict_yaml import strict_yaml_load
except ModuleNotFoundError:  # imported as scripts.check_qds_trust_invariant
    from scripts.strict_yaml import strict_yaml_load


# These immutable artifacts predate source-derived committed-QDS enforcement.
# Each exemption is pinned to the full committed file bytes as well as its
# identity.  A scientific-value, provenance, or formatting change therefore
# creates a new artifact that must satisfy the current guard.
LEGACY_QDS: dict[str, tuple[str, str, str]] = {
    "data/coscientists/openscientist/QDS_1sar_cdba2c07_2026-04-24.yaml": (
        "QDS_1sar_cdba2c07_2026-04-24",
        "2026-04-26T04:41:16+00:00",
        "5e852ba56031cfe17571bacaa2330e1cb141fc0497a084cc1c2338ff6dfcdafa",
    ),
    "data/coscientists/openscientist/QDS_1sar_cdba2c07_2026-04-26.yaml": (
        "QDS_1sar_cdba2c07_2026-04-26",
        "2026-04-26T09:12:19+00:00",
        "83a10cd12ec24a5af5ae0d70e37b8515d8a5f11cfc0ca4a238582b2fa4c7c76c",
    ),
    "data/coscientists/openscientist/QDS_1sar_cdba2c07_2026-04-30.yaml": (
        "QDS_1sar_cdba2c07_2026-04-30",
        "2026-05-01T04:17:12+00:00",
        "25ea923cb19803dabd7ae092eeaf597e7a042b7e9cdfe40c497f57686757f6f4",
    ),
    "data/coscientists/openscientist/QDS_1sar_cdba2c07_2026-05-01.yaml": (
        "QDS_1sar_cdba2c07_2026-05-01",
        "2026-05-01T07:09:51+00:00",
        "601cabe3d12bc8ab3014b7cfe2c8e2a419046302258bc65a6b99eae73c40e840",
    ),
    "data/coscientists/openscientist/QDS_1sar_cdba2c07_2026-05-04.yaml": (
        "QDS_1sar_cdba2c07_2026-05-04",
        "2026-05-05T04:27:11+00:00",
        "6be732d455b91c1a81741cca845f7d3cdc31af4311a29c1f7e7dc1e430d97136",
    ),
    "data/coscientists/openscientist/QDS_1sar_cdba2c07_2026-05-05.yaml": (
        "QDS_1sar_cdba2c07_2026-05-05",
        "2026-05-05T07:54:30+00:00",
        "07243f889da2801004822531eb6900d2192f1a713a412c208adebd873a563319",
    ),
    "data/coscientists/openscientist/QDS_1sar_cdba2c07_2026-09-07.yaml": (
        "QDS_1sar_cdba2c07_2026-09-07",
        "2026-09-10T04:11:37+00:00",
        "f0c72a90d421fb13c0bac534a3247c489ef0c058e83c0d5fe44c1398c167f439",
    ),
    "data/examples/qds/QDS_synth_active_site_2026-04-26.yaml": (
        "QDS_synth_active_site_2026-04-26",
        "2026-04-26T08:50:58+00:00",
        "bc46cb206d95e56f2b29ff1c7c4969b2bc2bddbcfcc0872ede39d55dbedd35d6",
    ),
}


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _is_frozen_legacy(path: Path, root: Path, qds: dict[str, Any]) -> bool:
    expected = LEGACY_QDS.get(_relative(path, root))
    if expected is None:
        return False
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return False
    return expected == (
        str(qds.get("id") or ""),
        str(qds.get("issued_at") or ""),
        digest,
    )


def _yaml_paths(root: Path, pattern: str = "*") -> list[Path]:
    """Discover both accepted YAML suffixes without double-counting paths."""
    return sorted(
        set(root.rglob(f"{pattern}.yaml")) | set(root.rglob(f"{pattern}.yml"))
    )


@dataclass(frozen=True)
class EvalRunSource:
    """An EvaluationRun plus pinned source metadata from its document."""

    run: dict[str, Any]
    structures: tuple[dict[str, Any], ...]
    tools: tuple[dict[str, Any], ...]
    tool_recommendations: tuple[dict[str, Any], ...]
    assumptions: tuple[dict[str, Any], ...]
    has_tool_recommendations: bool
    has_assumptions: bool
    qds_replay_pins: tuple[dict[str, Any], ...]


def _load_eval_runs(root: Path, failures: list[str]) -> dict[str, list[EvalRunSource]]:
    runs: dict[str, list[EvalRunSource]] = {}
    # Evaluation sources are admitted only through the canonical filename route.
    # Path.rglob is deliberately ignore-independent: ignored EVAL files remain
    # visible, while an arbitrary YAML carrier cannot become a trusted source.
    for path in sorted((root / "data").rglob("EVAL_*.yaml")):
        try:
            doc = strict_yaml_load(path.read_text()) or {}
        except (yaml.YAMLError, OSError, UnicodeError) as exc:
            failures.append(
                f"{path.name}: unreadable ({type(exc).__name__}): {exc}"
            )
            continue
        for run in doc.get("evaluation_runs", []) or []:
            run_id = str(run.get("id") or "").strip()
            if run_id:
                runs.setdefault(run_id, []).append(
                    EvalRunSource(
                        run=run,
                        structures=tuple(doc.get("structures", []) or []),
                        tools=tuple(doc.get("tools", []) or []),
                        tool_recommendations=tuple(
                            doc.get("tool_recommendations", []) or []
                        ),
                        assumptions=tuple(doc.get("assumptions", []) or []),
                        has_tool_recommendations="tool_recommendations" in doc,
                        has_assumptions="assumptions" in doc,
                        qds_replay_pins=tuple(doc.get("qds_replay_pins", []) or []),
                    )
                )
    for run_id, matches in sorted(runs.items()):
        if len(matches) > 1:
            failures.append(
                f"EvaluationRun {run_id!r} is duplicated {len(matches)} times; "
                "QDS coverage cannot be reconstructed unambiguously"
            )
    return runs


def _canonical_row_errors(
    path: Path,
    rows: list[dict[str, Any]],
    tool_families: dict[str, str] | None,
) -> list[str]:
    errors: list[str] = []
    for row in rows:
        row_id = str(row.get("id") or "<missing id>")
        cctbx = row.get("cctbx_oracles")
        non_cctbx = row.get("non_cctbx_oracles")
        if not isinstance(cctbx, list) or not isinstance(non_cctbx, list):
            errors.append(
                f"{path.name}: coverage row {row_id} must carry both oracle lists"
            )
            continue
        if len(cctbx) != len(set(cctbx)) or len(non_cctbx) != len(set(non_cctbx)):
            errors.append(f"{path.name}: coverage row {row_id} repeats an oracle")
        overlap = sorted(set(cctbx) & set(non_cctbx))
        if overlap:
            errors.append(
                f"{path.name}: coverage row {row_id} places oracle(s) in both "
                f"families: {', '.join(overlap)}"
            )
        for claimed_family, tool_ids in (
            ("cctbx", cctbx),
            ("non_cctbx", non_cctbx),
        ):
            for tool_id in tool_ids:
                if tool_families is None:
                    continue
                canonical = tool_families.get(str(tool_id))
                if canonical is None:
                    errors.append(
                        f"{path.name}: coverage row {row_id} names unknown catalog "
                        f"Tool {tool_id!r}"
                    )
                elif canonical != claimed_family:
                    errors.append(
                        f"{path.name}: coverage row {row_id} puts Tool {tool_id!r} "
                        f"in {claimed_family}; catalog family is {canonical}"
                    )
    return errors


_PIN_DIGEST_FIELDS = (
    "canonical_qds_sha256",
    "emitter_source_sha256",
    "source_tools_sha256",
    "source_tool_recommendations_sha256",
    "source_tool_assumptions_sha256",
)


def _snapshot_digest(key: str, rows: list[dict[str, Any]]) -> str:
    """Hash one source snapshot independently of emitter serialization."""
    payload = yaml.safe_dump(
        {key: rows}, sort_keys=True, allow_unicode=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _deduplicate_snapshot_rows(
    rows: list[dict[str, Any]], *, label: str
) -> tuple[list[dict[str, Any]], list[str]]:
    """Merge identical snapshots while rejecting conflicting duplicate ids."""
    merged: list[dict[str, Any]] = []
    by_id: dict[str, str] = {}
    errors: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"{label} row {index} is not an object")
            continue
        row_id = str(row.get("id") or "").strip()
        if not row_id:
            errors.append(f"{label} row {index} has no id")
            continue
        canonical = yaml.safe_dump(row, sort_keys=True, allow_unicode=True)
        prior = by_id.get(row_id)
        if prior is None:
            by_id[row_id] = canonical
            merged.append(copy.deepcopy(row))
        elif prior != canonical:
            errors.append(f"{label} has conflicting duplicate id {row_id!r}")
    return merged, errors


def _canonical_qds_text(qds: dict[str, Any]) -> str:
    """Serialize independently of qds_emit's mutable implementation."""
    return yaml.safe_dump(
        {"quality_data_sheets": [qds]},
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )


_RETAINED_SEMANTIC_FIELDS = (
    "agent_claim", "delta", "delta_from_measurement_ref",
    "derived_from_measurement_refs", "pass_criterion_ref",
    "criterion_preconditions", "assumptions",
)
_RETAINED_SET_FIELDS = frozenset({
    "assumptions", "criterion_preconditions", "derived_from_measurement_refs",
    "evidence_refs",
})
_NESTED_SOURCE_LINEAGE_FIELDS = frozenset({
    "source_measurement_ref", "source_evaluation_run_ref",
    "metric_definition_ref", "oracle_tool_ref", "oracle_family",
    "pass_status", "pass_criterion", "subject_ref", "reference_subject_ref",
    "stage", "scope", "scope_selector", "evidence_refs", "bundle_ref",
})


def _canonical_retained_semantics(field: str, value: Any) -> Any:
    """Canonicalize source-only semantics omitted by historical contracts."""
    if isinstance(value, dict):
        return {
            key: _canonical_retained_semantics(key, child)
            for key, child in sorted(value.items())
            if key != "notes" and child not in (None, "", [])
        }
    if isinstance(value, list):
        normalized = [_canonical_retained_semantics("", child) for child in value]
        if field not in _RETAINED_SET_FIELDS:
            return normalized
        keyed = {
            yaml.safe_dump(item, sort_keys=True, allow_unicode=True): item
            for item in normalized
        }
        return [keyed[key] for key in sorted(keyed)]
    return value


def _retained_selection_semantic_errors(
    path: Path,
    measurements: list[dict[str, Any]],
    subject_ref: str | None,
    contract_emitter: Any,
) -> list[str]:
    """Fail before replay when a frozen selector would collapse newer semantics."""
    errors: list[str] = []
    for row in measurements:
        for carrier_name in ("agent_claim", "oracle_measure", "delta"):
            carrier = row.get(carrier_name)
            if not isinstance(carrier, dict):
                continue
            nested = sorted(set(carrier) & _NESTED_SOURCE_LINEAGE_FIELDS)
            if nested:
                errors.append(
                    f"{path.name}: source measurement {row.get('id')!r} "
                    f"{carrier_name} carries nested QDS lineage/verdict field(s): "
                    + ", ".join(nested)
                )
    selector = (
        contract_emitter
        if hasattr(contract_emitter, "_eligible_for_subject")
        else getattr(contract_emitter, "_v1", contract_emitter)
    )
    eligible = [
        row
        for row in selector._eligible_for_subject(measurements, subject_ref)
        if selector._is_selectable_summary_measurement(row)
    ]
    groups: dict[tuple[Any, str], list[dict[str, Any]]] = {}
    for row in eligible:
        key = (
            selector._candidate_priority(row, subject_ref),
            selector._scientific_payload(row),
        )
        groups.setdefault(key, []).append(row)
    for rows in groups.values():
        if len(rows) < 2:
            continue
        payloads = {
            yaml.safe_dump(
                {
                    field: _canonical_retained_semantics(field, row.get(field))
                    for field in _RETAINED_SEMANTIC_FIELDS
                    if row.get(field) not in (None, "", [])
                },
                sort_keys=True,
                allow_unicode=True,
            )
            for row in rows
        }
        if len(payloads) > 1:
            ids = ", ".join(str(row.get("id") or "<missing id>") for row in rows)
            errors.append(
                f"{path.name}: retained contract selection cannot safely choose "
                "between equally ranked source measurements whose binding, "
                f"preconditions, claim/delta lineage, or assumptions differ ({ids})"
            )
    return errors


def _validate_contract_pin(
    path: Path,
    qds: dict[str, Any],
    refs: list[Any],
    source_pins: list[dict[str, Any]],
    source_structures: list[dict[str, Any]],
    source_tools: list[dict[str, Any]],
    source_recommendations: list[dict[str, Any]],
    source_assumptions: list[dict[str, Any]],
    source_runs: list[dict[str, Any]],
    *,
    contract_version: str,
    contract_emitter: Any,
) -> list[str]:
    """Validate one retained contract at its content-addressed boundary.

    The output digest protects the complete canonical sheet. The other digests
    bind the frozen implementation and source-owned snapshots. Full replay proves
    that the output is derived from those sources rather than merely self-attested
    by a matching byte hash.
    """
    errors: list[str] = []
    qds_id = str(qds.get("id") or "")
    matches = [pin for pin in source_pins if pin.get("qds_ref") == qds_id]
    unique = {
        yaml.safe_dump(pin, sort_keys=True, allow_unicode=True): pin for pin in matches
    }
    if len(unique) != 1:
        return [
            f"{path.name}: contract {contract_version} requires exactly one "
            "source-owned replay "
            f"pin for {qds_id!r}; found {len(unique)}"
        ]
    pin = next(iter(unique.values()))
    if str(pin.get("emitter_contract_version") or "") != contract_version:
        errors.append(
            f"{path.name}: replay pin contract version does not match QDS "
            f"contract {contract_version}"
        )
    if [str(ref) for ref in pin.get("source_evaluation_run_refs", []) or []] != [
        str(ref) for ref in refs
    ]:
        errors.append(
            f"{path.name}: replay pin source EvaluationRun refs differ from the QDS"
        )
    for field in _PIN_DIGEST_FIELDS:
        value = str(pin.get(field) or "")
        if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            errors.append(
                f"{path.name}: replay pin {field} must be a lowercase SHA-256 digest"
            )

    actual_inputs = {
        "emitter_source_sha256": hashlib.sha256(
            Path(contract_emitter.__file__).read_bytes()
        ).hexdigest(),
        "source_tools_sha256": _snapshot_digest("tools", source_tools),
        "source_tool_recommendations_sha256": _snapshot_digest(
            "tool_recommendations", source_recommendations
        ),
        "source_tool_assumptions_sha256": _snapshot_digest(
            "assumptions", source_assumptions
        ),
    }
    for field, actual in actual_inputs.items():
        if pin.get(field) != actual:
            errors.append(
                f"{path.name}: replay pin {field} differs from the retained "
                "contract/source snapshot"
            )

    canonical_text = _canonical_qds_text(qds)
    if path.read_text() != canonical_text:
        errors.append(
            f"{path.name}: committed QDS is not independently canonical YAML; "
            "regenerate the immutable artifact"
        )
    actual_digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if pin.get("canonical_qds_sha256") != actual_digest:
        errors.append(
            f"{path.name}: committed QDS differs from its source-owned canonical "
            "byte pin"
        )

    replay_doc = {
        "structures": source_structures,
        "tools": source_tools,
        "tool_recommendations": source_recommendations,
        "assumptions": source_assumptions,
        "evaluation_runs": source_runs,
    }
    try:
        with tempfile.TemporaryDirectory() as tmp:
            eval_path = Path(tmp) / "source.yaml"
            eval_path.write_text(
                yaml.safe_dump(replay_doc, sort_keys=False, allow_unicode=True)
            )
            replayed = contract_emitter.emit_qds(
                [eval_path],
                qds_id=str(qds.get("id") or ""),
                structure_id=str(qds.get("structure_ref") or ""),
                subject_ref=qds.get("subject_ref"),
                coverage_scope=qds.get("coverage_scope"),
                scope_notes=qds.get("scope_notes"),
                issued_at=qds.get("issued_at"),
                emitter_contract_version=contract_version,
                require_pinned_tool_snapshot=True,
            )
        if replayed != qds:
            errors.append(
                f"{path.name}: committed QDS differs from deterministic frozen "
                f"contract-{contract_version} replay of its source snapshots"
            )
    except (contract_emitter.QdsCompletenessError, SystemExit) as exc:
        errors.append(
            f"{path.name}: frozen contract-{contract_version} replay failed: {exc}"
        )
    return errors


def _validate_contract_1_pin(*args: Any) -> list[str]:
    return _validate_contract_pin(
        *args,
        contract_version="1",
        contract_emitter=qds_emit_contract_v1,
    )


def _validate_contract_2_pin(*args: Any) -> list[str]:
    return _validate_contract_pin(
        *args,
        contract_version="2",
        contract_emitter=qds_emit_contract_v2,
    )


REPLAY_CONTRACT_VALIDATORS = {
    "1": _validate_contract_1_pin,
    "2": _validate_contract_2_pin,
}
REPLAY_CONTRACT_EMITTERS = {
    "1": qds_emit_contract_v1,
    "2": qds_emit_contract_v2,
}


def _rebuild_coverage(
    path: Path,
    qds: dict[str, Any],
    eval_runs: dict[str, list[EvalRunSource]],
) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    refs = qds.get("derived_from_evaluation_run_refs") or []
    if not isinstance(refs, list) or not refs:
        return None, [f"{path.name}: QDS has no source EvaluationRun refs"]
    if len(refs) != len(set(refs)):
        errors.append(f"{path.name}: QDS repeats a source EvaluationRun ref")

    source_runs: list[dict[str, Any]] = []
    source_structures: list[dict[str, Any]] = []
    source_tools: list[dict[str, Any]] = []
    source_recommendations: list[dict[str, Any]] = []
    source_assumptions: list[dict[str, Any]] = []
    source_pins: list[dict[str, Any]] = []
    for ref in refs:
        matches = eval_runs.get(str(ref), [])
        if len(matches) != 1:
            errors.append(
                f"{path.name}: source EvaluationRun {ref!r} resolves "
                f"{len(matches)} times, expected exactly once"
            )
        else:
            source_runs.append(copy.deepcopy(matches[0].run))
            source_structures.extend(copy.deepcopy(matches[0].structures))
            source_tools.extend(copy.deepcopy(matches[0].tools))
            source_recommendations.extend(
                copy.deepcopy(matches[0].tool_recommendations)
            )
            source_assumptions.extend(copy.deepcopy(matches[0].assumptions))
            source_pins.extend(copy.deepcopy(matches[0].qds_replay_pins))
            if not matches[0].has_tool_recommendations:
                errors.append(
                    f"{path.name}: source EvaluationRun {ref!r} document has no "
                    "top-level tool_recommendations snapshot"
                )
            if not matches[0].has_assumptions:
                errors.append(
                    f"{path.name}: source EvaluationRun {ref!r} document has no "
                    "top-level assumptions snapshot"
                )
    for rows, label, assign in (
        (source_structures, "source Structure snapshot", "structures"),
        (source_tools, "source Tool snapshot", "tools"),
        (
            source_recommendations,
            "source tool-recommendation snapshot",
            "recommendations",
        ),
        (source_assumptions, "source tool-assumption snapshot", "assumptions"),
    ):
        merged, merge_errors = _deduplicate_snapshot_rows(rows, label=label)
        errors.extend(f"{path.name}: {error}" for error in merge_errors)
        if assign == "structures":
            source_structures = merged
        elif assign == "tools":
            source_tools = merged
        elif assign == "recommendations":
            source_recommendations = merged
        else:
            source_assumptions = merged
    if errors:
        return None, errors

    replay_source_runs = copy.deepcopy(source_runs)

    try:
        contract_version = str(qds.get("emitter_contract_version") or "")
        contract_validator = REPLAY_CONTRACT_VALIDATORS.get(contract_version)
        contract_emitter = REPLAY_CONTRACT_EMITTERS.get(contract_version)
        if contract_validator is None or contract_emitter is None:
            errors.append(
                f"{path.name}: QDS declares unsupported or missing "
                f"emitter_contract_version {contract_version!r}"
            )
            return None, errors
        if not source_tools:
            raise contract_emitter.QdsCompletenessError(
                f"QDS contract-{contract_version} replay requires a source-pinned "
                "Tool snapshot"
            )
        tool_families = contract_emitter._tool_families_from_rows(
            source_tools, source_name="source Tool snapshot"
        )
        for run in source_runs:
            run_id = str(run.get("id") or "<missing id>")
            run["measurements"] = contract_emitter._canonicalize_measurement_tools(
                run.get("measurements", []) or [],
                context=f"EvaluationRun {run_id}",
                tool_families=tool_families,
            )
        source_runs.sort(
            key=lambda run: (str(run.get("run_date") or ""), str(run.get("id") or ""))
        )

        explicit_subjects = contract_emitter._explicit_subjects(source_runs)
        committed_subject = qds.get("subject_ref")
        effective_subject = committed_subject
        if effective_subject is None and len(explicit_subjects) == 1:
            effective_subject = next(iter(explicit_subjects))
            errors.append(
                f"{path.name}: QDS omits subject_ref, but source evidence resolves "
                f"to {effective_subject!r}"
            )
        elif effective_subject is None and len(explicit_subjects) > 1:
            raise contract_emitter.QdsCompletenessError(
                "QDS inputs contain multiple explicit measurement or structured-row "
                f"subjects ({', '.join(sorted(explicit_subjects))}); QDS subject_ref "
                "is required"
            )
        elif (
            effective_subject is not None
            and explicit_subjects
            and effective_subject not in explicit_subjects
        ):
            raise contract_emitter.QdsCompletenessError(
                f"QDS subject {effective_subject!r} has no exact evidence in the "
                "inputs; explicit evidence exists only for "
                f"{', '.join(sorted(explicit_subjects))}"
            )

        filtered = contract_emitter._annotated_runs(source_runs, effective_subject)
        if not filtered:
            raise contract_emitter.QdsCompletenessError(
                f"QDS subject {effective_subject!r} left no applicable evaluation runs"
            )
        retained_refs = [str(run.get("id") or "") for run in filtered]
        if retained_refs != [str(ref) for ref in refs]:
            errors.append(
                f"{path.name}: source EvaluationRun refs differ from the runs retained "
                "by subject admission"
            )
        measurements = [
            measurement
            for run in filtered
            for measurement in contract_emitter._final_or_all_measurements(run)
        ]
        errors.extend(_retained_selection_semantic_errors(
            path, measurements, effective_subject, contract_emitter
        ))
        expected = contract_emitter.build_cross_tool_coverage(
            str(qds.get("id") or ""),
            measurements,
            effective_subject,
            tool_families=tool_families,
        )

        measured_tasks = {
            measurement.get("catalog_task_ref") for measurement in measurements
        }
        rebuilt_waivers: list[dict[str, Any]] = []
        seen_waiver_ids: set[Any] = set()
        for run in filtered:
            for waiver in run.get("cross_tool_waivers", []) or []:
                if waiver.get("catalog_task_ref") not in measured_tasks:
                    continue
                if waiver.get("id") in seen_waiver_ids:
                    continue
                seen_waiver_ids.add(waiver.get("id"))
                rebuilt_waivers.append(copy.deepcopy(waiver))
        committed_waivers = qds.get("cross_tool_waivers", []) or []
        if committed_waivers != rebuilt_waivers:
            errors.append(
                f"{path.name}: committed cross_tool_waivers differ from waivers "
                "rebuilt from retained source EvaluationRuns"
            )
        contract_emitter._check_trust_invariant(
            {"cross_tool_coverage": expected},
            rebuilt_waivers,
        )
        # Full-sheet derivation is replayed through the retained contract module
        # using only source-owned snapshots; today's emitter/catalog/registries
        # cannot redefine an already-issued sheet.
        errors.extend(
            contract_validator(
                path,
                qds,
                refs,
                source_pins,
                source_structures,
                source_tools,
                source_recommendations,
                source_assumptions,
                replay_source_runs,
            )
        )
    except SystemExit as exc:
        errors.append(f"{path.name}: source-derived trust check failed: {exc}")
        return None, errors
    return expected, errors


def check_sheet(
    path: Path,
    root: Path,
    qds: dict[str, Any],
    eval_runs: dict[str, list[EvalRunSource]],
    failures: list[str],
    grandfathered: list[str],
) -> None:
    if _is_frozen_legacy(path, root, qds):
        grandfathered.append(
            f"{_relative(path, root)}: {qds.get('id')} "
            "(frozen path/id/timestamp/SHA-256)"
        )
        return

    qds_id = str(qds.get("id") or "<missing id>")
    coverage_scope = qds.get("coverage_scope")
    if coverage_scope not in {"cumulative", "partial"}:
        failures.append(
            f"{path.name}: {qds_id} must declare coverage_scope cumulative or partial"
        )
    if coverage_scope == "partial" and not str(qds.get("scope_notes") or "").strip():
        failures.append(f"{path.name}: partial QDS must carry non-empty scope_notes")

    actual = qds.get("cross_tool_coverage")
    if not isinstance(actual, dict):
        failures.append(f"{path.name}: {qds_id} has no cross_tool_coverage block")
        return
    rows = actual.get("task_coverage")
    if not isinstance(rows, list) or not rows:
        failures.append(f"{path.name}: {qds_id} has no task_coverage rows")
        return
    # Exact source-snapshot reconstruction below is the family authority for modern
    # immutable sheets; the live catalog must not redefine an old artifact.
    failures.extend(_canonical_row_errors(path, rows, None))

    expected, rebuild_errors = _rebuild_coverage(path, qds, eval_runs)
    failures.extend(rebuild_errors)
    if expected is not None and actual != expected:
        failures.append(
            f"{path.name}: committed cross_tool_coverage differs from coverage "
            "rebuilt from its source EvaluationRuns"
        )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    args = ap.parse_args()
    root = Path(args.root)
    failures: list[str] = []
    grandfathered: list[str] = []

    eval_runs = _load_eval_runs(root, failures)
    for path in _yaml_paths(root / "data", "QDS_*"):
        try:
            doc = strict_yaml_load(path.read_text()) or {}
        except (yaml.YAMLError, OSError, UnicodeError) as exc:
            failures.append(
                f"{path.name}: unreadable ({type(exc).__name__}): {exc}"
            )
            continue
        sheets = doc.get("quality_data_sheets", []) or []
        if not sheets:
            failures.append(f"{path.name}: contains no QualityDataSheet")
        for qds in sheets:
            check_sheet(
                path,
                root,
                qds,
                eval_runs,
                failures,
                grandfathered,
            )

    for note in grandfathered:
        print(f"  grandfathered: {note}")
    if failures:
        for failure in failures:
            print(f"FAIL  {failure}")
        print(f"{len(failures)} trust-invariant failure(s)")
        return 1
    print(
        "QDS trust invariant holds "
        f"({len(grandfathered)} frozen legacy artifact(s) listed above)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
