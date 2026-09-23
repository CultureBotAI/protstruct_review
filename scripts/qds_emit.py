#!/usr/bin/env python3
"""Emit a QualityDataSheet YAML from one or more EvaluationRun YAMLs.

A QDS is the citable, dated, immutable snapshot of cross-tool findings for one
structure. It joins headline-level facts (R-factors, geometry, map quality)
across the EvaluationRuns it derives from, plus a `cross_tool_coverage`
section, plus per-residue / site / ligand / pairwise / predicted-confidence /
tool-recommendations blocks when the source eval carries that content.

Routing is driven by a single explicit `METRIC_TO_QDS_SLOT` table keyed on
the canonical metric ids declared in `ref/catalog.yaml`. Substring matching
is not used. Selection is subject-aware and deterministic: explicit subject,
substantive numeric value, independent family, source date, and stable ids are
considered in that order. Coupled R-work/R-free/gap values remain on one code path.

After building, a fail-hard consistency pass rejects QDS that would hide
load-bearing local content: a scope=site measurement implies a
SiteQuality block, a residue_outliers/density_peaks/per_residue_values
list on the eval implies a PerResidueQuality block, etc.

Usage:
    python scripts/qds_emit.py \\
        data/examples/eval/EVAL_1sar_cdba2c07_2026-04-24.yaml \\
        --qds-id QDS_1sar_cdba2c07_2026-04-26 \\
        --structure-id 1sar \\
        --coverage-scope cumulative \\
        --issued-at 2026-04-26T00:00:00Z \\
        -o data/examples/qds/QDS_1sar_cdba2c07_2026-04-26.yaml
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import math
import re
import statistics
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

import qds_emit_contract_v1
import qds_emit_contract_v3
import qds_emit_contract_v4

try:
    from strict_yaml import strict_yaml_load
except ModuleNotFoundError:  # imported as scripts.qds_emit
    from scripts.strict_yaml import strict_yaml_load


REPO = Path(__file__).resolve().parent.parent
CATALOG_PATH = REPO / "ref" / "catalog.yaml"
TOOL_RECS_PATH = REPO / "ref" / "tool_recommendations.yaml"
TOOL_ASSUMPTIONS_PATH = REPO / "ref" / "tool_assumptions.yaml"
QDS_EMITTER_CONTRACT_VERSION = "4"
SUPPORTED_QDS_EMITTER_CONTRACT_VERSIONS = frozenset({"1", "2", "3", "4"})


# ---------------------------------------------------------------------------
# Metric-id → QDS-block routing table
#
# Every metric_definition_ref the harness records routes through this table.
# Adding a new metric ⇒ add a new row here. Validated against the catalog
# at startup so a typo is caught before a QDS is emitted.
#
# A row's value is one `(block, slot)` pair, or a list of them when a metric
# deliberately lands in more than one block (a headline summary plus a newer
# specialized block). The value is then emitted once per listed slot.
# ---------------------------------------------------------------------------

QdsSlot = tuple[str, str]

METRIC_TO_QDS_SLOT: dict[str, QdsSlot | list[QdsSlot]] = {
    # Geometry summary
    "T05_clashscore":              ("geometry_summary", "clashscore"),
    "T05_ramachandran_outlier":    ("geometry_summary", "ramachandran_outliers_pct"),
    "T05_ramachandran_favored":    ("geometry_summary", "ramachandran_favored_pct"),
    "T05_rotamer_outlier":         ("geometry_summary", "rotamer_outliers_pct"),
    "T05_molprobity_composite":    ("geometry_summary", "molprobity_score"),
    "T05_bond-length_rmsd":        ("geometry_summary", "bond_rmsd_a"),
    "T05_bond-angle_rmsd":         ("geometry_summary", "angle_rmsd_deg"),
    "T05_bond-length_rmsz":        ("geometry_summary", "bond_rmsz"),
    "T05_bond-angle_rmsz":         ("geometry_summary", "angle_rmsz"),
    "T05_cbeta_outliers":          ("geometry_summary", "cbeta_deviations_count"),
    "T05_rama_z_score":            ("geometry_summary", "ramachandran_z_score"),
    "T05_packing_z_score":         [
        ("geometry_summary", "packing_z_score"),
        ("packing_summary", "packing_z_score"),
    ],
    "T05_unsatisfied_buried_hbond_count": [
        ("geometry_summary", "unsatisfied_buried_hbond_count"),
        ("packing_summary", "unsatisfied_buried_hbond_count"),
    ],
    "T05_b_factor_outlier_z":      ("packing_summary", "b_factor_outlier_z"),

    # Refinement summary (X-ray)
    "T03_r-work":                  ("refinement_summary", "r_work"),
    "T03_r-free":                  ("refinement_summary", "r_free"),
    "T03_r-free_r-work_gap":       ("refinement_summary", "r_free_gap"),
    "T06_r-work":                  ("refinement_summary", "r_work"),
    "T06_r-free":                  ("refinement_summary", "r_free"),
    "T06_diffraction_precision_index": ("refinement_summary", "diffraction_precision_index"),

    # Data-quality summary (X-ray)
    "T13_completeness_overall_outer": ("data_quality_summary", "completeness_overall_pct"),
    "T13_i_σ_i":                      ("data_quality_summary", "mean_i_over_sigma_outer"),
    "T13_cc½":                        ("data_quality_summary", "cc_half_outer"),
    "T13_r-merge_r-meas":             ("data_quality_summary", "r_merge"),
    "T13_wilson_b":                   ("data_quality_summary", "wilson_b"),

    # Map summary (cryo-EM)
    "T06_d_fsc_model":             ("map_summary", "d_fsc_model_a"),
    "T12_cc_box":                  ("map_summary", "cc_box"),
    "T12_cc_volume":               ("map_summary", "cc_volume"),
    "T12_emringer":                ("map_summary", "emringer_score"),
    "T12_q_score":                 ("map_summary", "mean_q_score"),
    "T12_global_fsc_0143":         ("map_summary", "global_fsc_0143_a"),
    "T12_local_resolution_mean":   ("map_summary", "local_resolution_mean_a"),
    "T12_local_resolution_std":    ("map_summary", "local_resolution_std_a"),
    "T12_directional_resolution_anisotropy": ("map_summary", "directional_resolution_anisotropy"),
    "T12_local_model_map_fsc_q":   ("map_summary", "local_model_map_fsc_q"),
    "T06_rscc_outlier_fraction":   ("map_summary", "rscc_outlier_fraction"),

    # Predicted confidence summary
    "T07_predicted_tm_score":      ("predicted_confidence_summary", "predicted_tm_score"),
    "T07_interface_predicted_tm_score": ("predicted_confidence_summary", "interface_predicted_tm_score"),
    "T07_prediction_ensemble_convergence": [
        ("predicted_confidence_summary", "prediction_ensemble_convergence"),
        ("prediction_ensemble_summary", "prediction_ensemble_convergence"),
    ],

    # Structured optional summary blocks
    "T15_secondary_structure_agreement": ("classification_summary", "secondary_structure_agreement"),
    "T15_secondary_structure_content": ("classification_summary", "secondary_structure_content"),
    "T15_secondary_structure_assignment": ("classification_summary", "secondary_structure_assignment"),
    "T15_structural_domain_assignment": ("classification_summary", "structural_domain_assignment"),
    "T15_fold_classification":     ("classification_summary", "fold_classification"),
    "T16_interface_buried_surface_area": ("interface_quality_summary", "interface_buried_surface_area"),
    "T16_interface_dockq_score":   ("interface_quality_summary", "interface_dockq_score"),
    "T16_capri_interface_quality_class": ("interface_quality_summary", "capri_interface_quality_class"),
    "T17_nmr_restraint_violation_summary": ("nmr_validation_summary", "nmr_restraint_violation_summary"),
    "T17_nmr_ensemble_precision_rmsd": ("nmr_validation_summary", "nmr_ensemble_precision_rmsd"),
}

# These contract-2 metrics intentionally remain coverage-only: QualityDataSheet
# has no T14 headline-summary scalar, and mapping either candidate inventory or
# their derived conflict count into an unrelated block would misrepresent it.
# Listing them explicitly makes omission from METRIC_TO_QDS_SLOT a versioned
# disposition rather than an accidental unknown-metric drop.
COVERAGE_ONLY_METRIC_IDS = frozenset(
    {
        "T14_asn_gln_his_flip_candidates_scored",
        "T14_asn_gln_his_flip_set_conflicts",
    }
)


# Metric ids that, when a measurement carries them, force the QDS to populate
# `predicted_confidence_summary`. Predicted-model evals also typically have
# `Structure.method == predicted_model`; either trigger fires the block.
PREDICTED_MARKER_METRIC_IDS: set[str] = {
    "T07_predicted_tm_score",
    "T07_interface_predicted_tm_score",
    "T07_prediction_ensemble_convergence",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def yaml_dump(obj: Any) -> str:
    return yaml.safe_dump(obj, sort_keys=False, default_flow_style=False, allow_unicode=True)


def _load_yaml_document(path: Path, *, label: str) -> dict[str, Any]:
    """Load one authoritative YAML document without last-key-wins ambiguity."""
    try:
        doc = strict_yaml_load(path.read_text()) or {}
    except (yaml.YAMLError, OSError, UnicodeError) as exc:
        raise QdsCompletenessError(
            f"QDS {label} is unreadable: {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(doc, dict):
        raise QdsCompletenessError(f"QDS {label} must be a YAML mapping")
    return doc


def _load_catalog_metric_ids() -> set[str]:
    doc = _load_yaml_document(CATALOG_PATH, label="catalog")
    return {m["id"] for m in doc.get("metric_definitions", [])}


def _tool_families_from_rows(
    tools: list[dict[str, Any]], *, source_name: str
) -> dict[str, str]:
    """Validate and index one authoritative Tool-family snapshot."""
    families: dict[str, str] = {}
    errors: list[str] = []
    for tool in tools:
        tool_id = str(tool.get("id") or "").strip()
        family = str(tool.get("family") or "").strip()
        if not tool_id:
            errors.append(f"{source_name} Tool has no id")
            continue
        if family not in {"cctbx", "non_cctbx"}:
            errors.append(
                f"{source_name} Tool {tool_id!r} has no canonical "
                "cctbx/non_cctbx family"
            )
            continue
        previous = families.get(tool_id)
        if previous is not None and previous != family:
            errors.append(
                f"catalog Tool {tool_id!r} has conflicting families "
                f"{previous!r} and {family!r}"
            )
        families[tool_id] = family
    if errors:
        raise QdsCompletenessError(
            "QDS canonical-tool integrity failed:\n  - " + "\n  - ".join(errors)
        )
    return families


def _load_catalog_tool_families() -> dict[str, str]:
    """Return the live catalog Tool.id -> Tool.family mapping."""
    doc = _load_yaml_document(CATALOG_PATH, label="catalog")
    return _tool_families_from_rows(
        doc.get("tools", []) or [], source_name="catalog"
    )


def _has_oracle_payload(measurement: dict[str, Any]) -> bool:
    """Whether a row claims any oracle result, including a failed attempt."""
    value = measurement.get("oracle_measure") or {}
    return any(
        (
            value.get("value_numeric") is not None,
            bool(str(value.get("value_text") or "").strip()),
            value.get("is_not_applicable") is True,
        )
    )


def _canonicalize_measurement_tools(
    measurements: list[dict[str, Any]],
    *,
    context: str,
    tool_families: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Validate named tools and replace asserted families with catalog truth."""
    families = (
        _load_catalog_tool_families()
        if tool_families is None
        else tool_families
    )
    out: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, source in enumerate(measurements):
        measurement = dict(source)
        measurement_id = str(measurement.get("id") or f"row {index + 1}")
        tool_id = str(measurement.get("oracle_tool_ref") or "").strip()
        asserted_family = measurement.get("oracle_family")
        has_payload = _has_oracle_payload(measurement)

        if not tool_id:
            if has_payload:
                errors.append(
                    f"{context} measurement {measurement_id!r} has an oracle result "
                    "but no oracle_tool_ref"
                )
            elif asserted_family not in (None, ""):
                errors.append(
                    f"{context} measurement {measurement_id!r} asserts oracle_family "
                    "without naming an oracle_tool_ref"
                )
            out.append(measurement)
            continue

        canonical_family = families.get(tool_id)
        if canonical_family is None:
            if has_payload or asserted_family not in (None, ""):
                errors.append(
                    f"{context} measurement {measurement_id!r} names unknown catalog "
                    f"Tool {tool_id!r}"
                )
            out.append(measurement)
            continue
        if asserted_family not in (None, "", canonical_family):
            errors.append(
                f"{context} measurement {measurement_id!r} labels catalog Tool "
                f"{tool_id!r} as {asserted_family!r}; canonical family is "
                f"{canonical_family!r}"
            )
        measurement["oracle_family"] = canonical_family
        out.append(measurement)

    if errors:
        raise QdsCompletenessError(
            "QDS canonical-tool integrity failed:\n  - " + "\n  - ".join(errors)
        )
    return out


def _validate_routing_table() -> None:
    """Every routed/coverage-only contract metric must exist in the catalog."""
    catalog_ids = _load_catalog_metric_ids()
    bad = [mid for mid in METRIC_TO_QDS_SLOT if mid not in catalog_ids]
    bad.extend(mid for mid in COVERAGE_ONLY_METRIC_IDS if mid not in catalog_ids)
    overlap = sorted(COVERAGE_ONLY_METRIC_IDS.intersection(METRIC_TO_QDS_SLOT))
    if overlap:
        raise SystemExit(
            "qds_emit: metrics cannot be both scalar-routed and coverage-only:\n  "
            + "\n  ".join(overlap)
        )
    if bad:
        raise SystemExit(
            "qds_emit: QDS metric disposition references ids not in ref/catalog.yaml:\n  "
            + "\n  ".join(bad)
        )


def _final_or_all_measurements(eval_run: dict[str, Any]) -> list[dict[str, Any]]:
    """Return final/dataset rows annotated with their source run.

    The private keys never leave the emitter. They make recency a deterministic
    tie-breaker and let a wrapped QDS scalar name the EvaluationRun that actually
    supplied it, rather than merely listing every input run at sheet level.
    """
    out: list[dict[str, Any]] = []
    for measurement in eval_run.get("measurements", []):
        if measurement.get("stage") not in ("final", "all"):
            continue
        annotated = dict(measurement)
        annotated["_source_evaluation_run_ref"] = eval_run.get("id")
        annotated["_source_run_date"] = str(eval_run.get("run_date") or "")
        out.append(annotated)
    return out


SUBJECT_ROW_KEYS = (
    "residue_outliers",
    "density_peaks",
    "flagged_regions",
    "per_residue_values",
    "secondary_structure_assignments",
    "domain_assignments",
    "sites",
    "ligands",
    "interface_qualities",
    "prediction_ensemble_qualities",
    "nmr_ensemble_qualities",
    "pairwise_comparisons",
)

# These EvaluationRun rows are copied directly into QDS summary/list fields.
# The emitted copy must name its exact source so the committed-corpus guard can
# reconstruct and compare the complete payload rather than trusting the copy.
COPIED_STRUCTURED_ROW_KEYS = {
    "residue_outliers",
    "density_peaks",
    "flagged_regions",
    "per_residue_values",
    "secondary_structure_assignments",
    "domain_assignments",
    "interface_qualities",
    "prediction_ensemble_qualities",
    "nmr_ensemble_qualities",
    "pairwise_comparisons",
}

# TypedMeasurementValue slots nested inside the structured rows copied into a
# QDS. Keep this explicit so an ordinary prose/number field is never mistaken
# for a typed carrier merely because it has a generic name such as ``value``.
COPIED_STRUCTURED_TYPED_VALUE_FIELDS: dict[str, tuple[str, ...]] = {
    "residue_outliers": ("metric_value",),
    "density_peaks": (),
    "flagged_regions": (),
    "per_residue_values": ("value",),
    "secondary_structure_assignments": ("confidence",),
    "domain_assignments": ("confidence",),
    "interface_qualities": (
        "buried_surface_area",
        "dockq_score",
        "capri_quality_class",
    ),
    "prediction_ensemble_qualities": ("convergence", "diversity"),
    "nmr_ensemble_qualities": (
        "restraint_violation_summary",
        "ensemble_precision_rmsd",
    ),
    "pairwise_comparisons": (
        "tm_score",
        "lddt",
        "gdt_ts",
        "gdt_ha",
        "ca_rmsd_a",
        "per_residue_max_displacement_a",
        "delta_r_free",
        "delta_cc_mask",
    ),
}


def _annotated_runs(
    runs: list[dict[str, Any]], subject_ref: str | None
) -> list[dict[str, Any]]:
    """Return one copied evidence view shared by every QDS builder.

    Explicit non-matching measurements/structured rows are removed. Legacy rows
    without a subject remain available as fallback evidence; scalar selection
    still makes an exact subject win within its metric/context. A run containing
    subject-labelled evidence for only other subjects is omitted entirely so its
    headline, assumptions, recommendations, and waivers cannot leak into the QDS.
    """
    out: list[dict[str, Any]] = []
    for source in runs:
        run = copy.deepcopy(source)
        measurements = run.get("measurements", []) or []
        labelled_measurements = [m for m in measurements if m.get("subject_ref")]
        exact_measurements = [m for m in labelled_measurements if m.get("subject_ref") == subject_ref]
        legacy_measurements = [m for m in measurements if not m.get("subject_ref")]

        if subject_ref is None:
            kept_measurements = measurements
        else:
            kept_measurements = exact_measurements + legacy_measurements

        annotated: list[dict[str, Any]] = []
        for measurement in kept_measurements:
            row = dict(measurement)
            row["_source_evaluation_run_ref"] = run.get("id")
            row["_source_run_date"] = str(run.get("run_date") or "")
            annotated.append(row)
        run["measurements"] = annotated

        exact_structured = False
        labelled_structured = False
        for key in SUBJECT_ROW_KEYS:
            rows = run.get(key, []) or []
            if key in COPIED_STRUCTURED_ROW_KEYS:
                for index, row in enumerate(rows):
                    row_id = row.get("id") if isinstance(row, dict) else None
                    _validate_structured_row_value_carriers(
                        row,
                        collection=key,
                        where=(
                            f"EvaluationRun {run.get('id')!r}.{key}[{index}] "
                            f"row {row_id!r}"
                        ),
                    )
                rows = [
                    {
                        **row,
                        "source_evaluation_run_ref": run.get("id"),
                        "source_row_ref": row.get("id"),
                    }
                    for row in rows
                ]
                run[key] = rows
            if subject_ref is None:
                continue
            exact = [row for row in rows if row.get("subject_ref") == subject_ref]
            legacy = [row for row in rows if not row.get("subject_ref")]
            labelled_structured = labelled_structured or any(row.get("subject_ref") for row in rows)
            exact_structured = exact_structured or bool(exact)
            run[key] = exact or legacy

        has_labelled = bool(labelled_measurements) or labelled_structured
        has_exact = bool(exact_measurements) or exact_structured
        # Once a run names a different concrete subject, its unlabelled rows and
        # run-level prose are not a safe fallback for this QDS.  Legacy-only runs
        # remain usable, but a mixed explicit/legacy run cannot lend its headline,
        # waiver, assumptions, or auxiliary rows to a subject it did not measure.
        if subject_ref is not None and has_labelled and not has_exact:
            continue
        out.append(run)
    return out


def _explicit_subjects(runs: list[dict[str, Any]]) -> set[str]:
    """Collect subjects from scalar measurements and structured summary rows."""
    subjects: set[str] = set()
    for run in runs:
        for measurement in run.get("measurements", []) or []:
            if measurement.get("subject_ref"):
                subjects.add(str(measurement["subject_ref"]))
        for key in SUBJECT_ROW_KEYS:
            for row in run.get(key, []) or []:
                if row.get("subject_ref"):
                    subjects.add(str(row["subject_ref"]))
    return subjects


def _eligible_for_subject(
    measurements: list[dict[str, Any]], subject_ref: str | None
) -> list[dict[str, Any]]:
    """Exclude explicit non-matches while retaining legacy unlabelled rows."""
    if subject_ref is None:
        return list(measurements)
    return [
        m for m in measurements
        if m.get("subject_ref") in (None, "", subject_ref)
    ]


TEXTUAL_SUMMARY_METRIC_IDS: set[str] = {
    "T10_ligand_element_identity",
    "T15_secondary_structure_assignment",
    "T15_structural_domain_assignment",
    "T15_fold_classification",
    "T16_capri_interface_quality_class",
    "T17_nmr_restraint_violation_summary",
}


def _finite_numeric_value(measurement: dict[str, Any]) -> float | None:
    value = (measurement.get("oracle_measure") or {}).get("value_numeric")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


TYPED_VALUE_FIELDS = ("agent_claim", "oracle_measure", "delta")


def _validate_typed_value_carrier(value: Any, *, where: str) -> None:
    """Enforce the schema's exactly-one typed-value carrier contract.

    LinkML 1.9 does not reliably enforce cross-slot cardinality rules, so a
    hand-authored YAML row can otherwise carry contradictory numeric, textual,
    and not-applicable values at once. Presence is deliberately strict here:
    an explicitly false ``is_not_applicable`` or an empty/null carrier is not a
    second way to say "absent".
    """
    if not isinstance(value, dict):
        raise QdsCompletenessError(
            f"QDS typed value-carrier integrity failed: {where} must be an object"
        )

    carriers: list[str] = []
    errors: list[str] = []
    if "value_numeric" in value:
        numeric = value.get("value_numeric")
        if (
            isinstance(numeric, bool)
            or not isinstance(numeric, (int, float))
            or not math.isfinite(float(numeric))
        ):
            errors.append("value_numeric must be a finite non-boolean number")
        else:
            carriers.append("value_numeric")
    if "value_text" in value:
        text = value.get("value_text")
        if not isinstance(text, str) or not text.strip():
            errors.append("value_text must be a non-empty string")
        else:
            carriers.append("value_text")
    if "is_not_applicable" in value:
        if value.get("is_not_applicable") is not True:
            errors.append("is_not_applicable must be literal true when present")
        else:
            carriers.append("is_not_applicable")

    if len(carriers) != 1:
        errors.append(
            "exactly one of value_numeric, value_text, or "
            "is_not_applicable=true is required"
        )
    if errors:
        raise QdsCompletenessError(
            f"QDS typed value-carrier integrity failed for {where}: "
            + "; ".join(errors)
        )


def _validate_measurement_value_carriers(
    measurement: dict[str, Any], *, require_oracle: bool
) -> None:
    """Validate every typed value attached to a publishable measurement."""
    measurement_id = str(measurement.get("id") or "<missing id>")
    if require_oracle and "oracle_measure" not in measurement:
        raise QdsCompletenessError(
            "QDS typed value-carrier integrity failed for measurement "
            f"{measurement_id!r}.oracle_measure: a typed oracle value is required"
        )
    for field in TYPED_VALUE_FIELDS:
        if field in measurement:
            _validate_typed_value_carrier(
                measurement[field], where=f"measurement {measurement_id!r}.{field}"
            )


def _validate_structured_row_value_carriers(
    row: Any, *, collection: str, where: str
) -> None:
    """Validate every TypedMeasurementValue slot on one copied source row."""
    if not isinstance(row, dict):
        raise QdsCompletenessError(
            f"QDS structured-row integrity failed: {where} must be an object"
        )
    for field in COPIED_STRUCTURED_TYPED_VALUE_FIELDS.get(collection, ()):
        if field in row:
            _validate_typed_value_carrier(row[field], where=f"{where}.{field}")


def _is_selectable_summary_measurement(measurement: dict[str, Any]) -> bool:
    """Only a real value of the metric's expected kind may populate a summary.

    In particular, prose such as ``tool aborted`` on a numeric metric is useful
    attempt metadata but is not a scientific result and cannot outrank a numeric
    value from another family.
    """
    _validate_measurement_value_carriers(measurement, require_oracle=True)
    metric_id = measurement.get("metric_definition_ref")
    value = measurement.get("oracle_measure") or {}
    numeric = _finite_numeric_value(measurement)
    text = str(value.get("value_text") or "")

    # A label-valued metric cannot become a gradeable numeric result merely by
    # adding a dummy value_numeric alongside (or instead of) its label.  LinkML
    # does not enforce TypedMeasurementValue's exactly-one carrier contract, so
    # the emitter must enforce the scientific type at the point of selection.
    if metric_id in TEXTUAL_SUMMARY_METRIC_IDS:
        if numeric is not None:
            raise QdsCompletenessError(
                "QDS label-valued measurements must use value_text only; "
                f"measurement {measurement.get('id')!r} carries value_numeric"
            )
        if not text.strip():
            return False
        failed_attempt_markers = (
            "abort",
            "unavailable",
            "not run",
            "failed to",
            "failure:",
            "error:",
            "could not",
            "unable to",
            "no result",
        )
        if any(marker in text.casefold() for marker in failed_attempt_markers):
            return False
        if measurement.get("pass_status") != "informational":
            raise QdsCompletenessError(
                "QDS label-valued measurements are descriptive only and must carry "
                f"pass_status=informational; measurement {measurement.get('id')!r} "
                f"has {measurement.get('pass_status')!r}"
            )
        return True

    if numeric is not None:
        return True
    if metric_id not in TEXTUAL_SUMMARY_METRIC_IDS:
        return False
    return False


def _candidate_priority(m: dict[str, Any], subject_ref: str | None) -> tuple[Any, ...]:
    """Only policy-backed preferences; scientific context is not a tie-breaker."""
    explicit_subject = m.get("subject_ref")
    subject_score = 0 if subject_ref is not None and explicit_subject == subject_ref else 1
    type_score = 0 if _finite_numeric_value(m) is not None else 1
    fam_score = {"non_cctbx": 0, "cctbx": 1}.get(m.get("oracle_family"), 2)
    run_date = str(m.get("_source_run_date") or "").replace("-", "")
    recency_score = -int(run_date) if run_date.isdigit() else 0
    return (subject_score, type_score, fam_score, recency_score)


_SEMANTIC_SET_FIELDS = frozenset({
    "assumptions", "criterion_preconditions", "derived_from_measurement_refs",
    "evidence_refs",
})


def _canonical_semantic_value(field: str, value: Any) -> Any:
    """Normalize order-insensitive semantics without trusting prose notes."""
    if isinstance(value, dict):
        return {
            key: _canonical_semantic_value(key, child)
            for key, child in sorted(value.items())
            if key != "notes" and child not in (None, "", [])
        }
    if isinstance(value, list):
        normalized = [_canonical_semantic_value("", child) for child in value]
        if field not in _SEMANTIC_SET_FIELDS:
            return normalized
        keyed = {
            yaml.safe_dump(item, sort_keys=True, allow_unicode=True): item
            for item in normalized
        }
        return [keyed[key] for key in sorted(keyed)]
    return value


def _scientific_payload(m: dict[str, Any]) -> str:
    """Canonical scientific payload used to distinguish duplicates from conflicts.

    Notes and agent claims do not decide which oracle value wins.  Status,
    criterion, metric/context, tool family, and provenance do: silently choosing
    between equal-priority rows that differ in any of those fields would change
    the scientific meaning of the emitted scalar.
    """
    semantic_fields = (
        "catalog_task_ref",
        "metric_definition_ref",
        "subject_ref",
        "reference_subject_ref",
        "stage",
        "scope",
        "scope_selector",
        "oracle_tool_ref",
        "oracle_family",
        "agent_claim",
        "oracle_measure",
        "delta",
        "delta_from_measurement_ref",
        "derived_from_measurement_refs",
        "pass_status",
        "pass_criterion",
        "pass_criterion_ref",
        "criterion_preconditions",
        "provenance_ref",
        "evidence_refs",
        "bundle_ref",
        "assumptions",
        "_source_evaluation_run_ref",
    )
    return yaml.safe_dump(
        {
            key: _canonical_semantic_value(key, m.get(key))
            for key in semantic_fields if m.get(key) not in (None, "", [])
        },
        sort_keys=True,
        allow_unicode=True,
    )


def _strongest(
    measurements: list[dict[str, Any]], subject_ref: str | None = None
) -> dict[str, Any] | None:
    """Pick deterministically by subject, value type, family, date, then id."""
    eligible = [
        measurement
        for measurement in _eligible_for_subject(measurements, subject_ref)
        if _is_selectable_summary_measurement(measurement)
    ]
    if not eligible:
        return None
    ordered = sorted(
        eligible,
        key=lambda m: (_candidate_priority(m, subject_ref), str(m.get("id") or "")),
    )
    winner = ordered[0]
    priority = _candidate_priority(winner, subject_ref)
    tied = [m for m in ordered if _candidate_priority(m, subject_ref) == priority]
    distinct_payloads = {_scientific_payload(m) for m in tied}
    if len(distinct_payloads) > 1:
        ids = ", ".join(str(m.get("id") or "<missing id>") for m in tied)
        raise QdsCompletenessError(
            "QDS selection is scientifically ambiguous: equally ranked measurements "
            f"differ in value, tool, status, criterion, or context ({ids}). "
            "Name the QDS subject or make the comparison context explicit."
        )
    return winner


_SOURCE_TYPED_VALUE_FIELDS = frozenset({
    "value_numeric", "value_text", "unit", "is_not_applicable", "percentile",
    "mean", "std_dev", "min_value", "max_value", "count",
})


def _wrap_value(m: dict[str, Any] | None) -> dict[str, Any] | None:
    if m is None:
        return None
    source_value = m.get("oracle_measure") or {}
    v = {
        key: value for key, value in source_value.items()
        if key in _SOURCE_TYPED_VALUE_FIELDS
    }
    provenance_fields = {
        "source_measurement_ref": "id",
        "source_evaluation_run_ref": "_source_evaluation_run_ref",
        "metric_definition_ref": "metric_definition_ref",
        "oracle_tool_ref": "oracle_tool_ref",
        "oracle_family": "oracle_family",
        "pass_status": "pass_status",
        "pass_criterion": "pass_criterion",
        "subject_ref": "subject_ref",
        "reference_subject_ref": "reference_subject_ref",
        "evidence_refs": "evidence_refs",
        "bundle_ref": "bundle_ref",
        "stage": "stage",
        "scope": "scope",
        "scope_selector": "scope_selector",
        "notes": "notes",
    }
    for output_key, source_key in provenance_fields.items():
        value = m.get(source_key)
        if value not in (None, ""):
            v[output_key] = value
    return v or None


# ---------------------------------------------------------------------------
# Routing: walk every measurement once, deposit each at its QDS slot
# ---------------------------------------------------------------------------


def _slots_for(metric_id: str) -> list[QdsSlot]:
    """Every (block, slot) this metric id routes to, in table order."""
    entry = METRIC_TO_QDS_SLOT[metric_id]
    return [entry] if isinstance(entry, tuple) else list(entry)


def _route_measurements(
    measurements: list[dict[str, Any]], subject_ref: str | None = None
) -> dict[str, dict[str, dict[str, Any]]]:
    """Return {block_name: {slot_name: <strongest measurement>}}.

    The strongest measurement for a (block, slot) pair is the one
    `_strongest` selects across all measurements that route to the same
    slot via METRIC_TO_QDS_SLOT.
    """
    by_slot: dict[QdsSlot, list[dict[str, Any]]] = {}
    for m in measurements:
        # Local rows have dedicated SiteQuality/LigandQuality/per-residue
        # builders.  Letting one compete for a global headline scalar either
        # hides the local regression or makes unlike contexts ambiguous.
        if m.get("scope") in {"site", "ligand", "atom"}:
            continue
        mid = m.get("metric_definition_ref")
        if mid not in METRIC_TO_QDS_SLOT:
            continue
        for slot in _slots_for(mid):
            by_slot.setdefault(slot, []).append(m)

    out: dict[str, dict[str, dict[str, Any]]] = {}
    for (block, slot), candidates in by_slot.items():
        if block == "refinement_summary" and slot in REFINEMENT_SLOTS:
            # Coupled below as a single provenance/context bundle; selecting a
            # scalar first can raise or, worse, mix otherwise coherent triples.
            continue
        if block == "classification_summary" and slot in T15_BUNDLE_SLOTS:
            continue
        if block == "interface_quality_summary" and slot in T16_BUNDLE_SLOTS:
            continue
        winner = _strongest(candidates, subject_ref)
        if winner is None:
            continue
        out.setdefault(block, {})[slot] = winner

    _enforce_coherent_refinement_bundle(out, by_slot, subject_ref)
    _enforce_coherent_t15_bundle(out, by_slot, subject_ref)
    _enforce_coherent_t16_bundle(out, by_slot, subject_ref)
    return out


REFINEMENT_SLOTS = ("r_work", "r_free", "r_free_gap")
REFINEMENT_BUNDLE_FIELDS = (
    "_source_evaluation_run_ref",
    "catalog_task_ref",
    "stage",
    "scope",
    "scope_selector",
    "subject_ref",
    "reference_subject_ref",
    "oracle_tool_ref",
    "oracle_family",
    "provenance_ref",
    "evidence_refs",
)


def _context_token(value: Any) -> str:
    """Stable token for possibly structured provenance/context fields."""
    dumped = yaml.safe_dump(value, sort_keys=True, allow_unicode=True)
    if dumped.endswith("...\n"):
        dumped = dumped[:-4]
    return dumped.strip()


def _measurement_bundle_key(m: dict[str, Any]) -> tuple[str, ...]:
    """Full scientific code path required for a coherent refinement bundle."""
    return tuple(_context_token(m.get(field)) for field in REFINEMENT_BUNDLE_FIELDS)


def _refinement_bundle_payload(selected: dict[str, dict[str, Any]]) -> str:
    return yaml.safe_dump(
        {slot: _scientific_payload(row) for slot, row in sorted(selected.items())},
        sort_keys=True,
        allow_unicode=True,
    )


def _r_unit(unit: Any) -> str:
    normalized = str(unit or "").strip().casefold()
    if normalized in {"", "1", "fraction", "unitless", "dimensionless"}:
        return "fraction"
    if normalized in {"%", "percent", "percentage"}:
        return "percent"
    return normalized


def _rounding_increment(value: float) -> float:
    exponent = Decimal(str(value)).as_tuple().exponent
    return float(Decimal(10) ** exponent) if exponent < 0 else 1.0


def _validate_refinement_arithmetic(selected: dict[str, dict[str, Any]]) -> None:
    """Validate R-free − R-work against the recorded gap and its units."""
    if not all(slot in selected for slot in REFINEMENT_SLOTS):
        return
    measures = {
        slot: selected[slot].get("oracle_measure") or {} for slot in REFINEMENT_SLOTS
    }
    values = {slot: measures[slot].get("value_numeric") for slot in REFINEMENT_SLOTS}
    if any(
        not isinstance(value, (int, float)) or isinstance(value, bool)
        for value in values.values()
    ):
        raise QdsCompletenessError(
            "QDS refinement-summary arithmetic failed: R-work, R-free, and "
            "R-free gap must all be numeric"
        )
    units = {slot: _r_unit(measures[slot].get("unit")) for slot in REFINEMENT_SLOTS}
    if len(set(units.values())) != 1:
        raise QdsCompletenessError(
            "QDS refinement-summary arithmetic failed: incompatible R-factor "
            f"units {units}"
        )
    expected = float(values["r_free"]) - float(values["r_work"])
    observed = float(values["r_free_gap"])
    tolerance = sum(
        0.5 * _rounding_increment(float(value)) for value in values.values()
    ) + 1e-12
    if abs(expected - observed) > tolerance:
        raise QdsCompletenessError(
            "QDS refinement-summary arithmetic failed: recorded R-free gap "
            f"{observed:g} does not equal R-free {float(values['r_free']):g} minus "
            f"R-work {float(values['r_work']):g} within rounding tolerance "
            f"{tolerance:g}"
        )


def _enforce_coherent_refinement_bundle(
    routed: dict[str, dict[str, dict[str, Any]]],
    by_slot: dict[QdsSlot, list[dict[str, Any]]],
    subject_ref: str | None,
) -> None:
    """Keep R-work, R-free, and their gap on one run/tool/family code path.

    Selecting the three slots independently can create an arithmetically plausible
    but scientifically fictitious triple. When at least two refinement slots are
    available, choose one bundle covering all available slots. If no such bundle
    exists and the independent winners disagree on provenance, fail loudly.
    """
    block = "refinement_summary"
    all_candidates = {
        slot: _eligible_for_subject(by_slot.get((block, slot), []), subject_ref)
        for slot in REFINEMENT_SLOTS
    }

    # An explicit match makes every legacy refinement row ineligible for this
    # *bundle*, not merely for whichever individual slots it happens to cover.
    # Otherwise a partial exact-subject result could be silently completed with
    # R values from an unlabelled/different artefact.
    exact_exists = subject_ref is not None and any(
        row.get("subject_ref") == subject_ref
        for rows in all_candidates.values()
        for row in rows
    )
    if exact_exists:
        all_candidates = {
            slot: [row for row in rows if row.get("subject_ref") == subject_ref]
            for slot, rows in all_candidates.items()
        }

    present = [slot for slot in REFINEMENT_SLOTS if all_candidates[slot]]
    for slot in REFINEMENT_SLOTS:
        (routed.get(block) or {}).pop(slot, None)
    if not (routed.get(block) or {}):
        routed.pop(block, None)
    if len(present) < 2:
        for slot in present:
            winner = _strongest(all_candidates[slot], subject_ref)
            if winner is not None:
                routed.setdefault(block, {})[slot] = winner
        return

    bundles: dict[tuple[str, ...], dict[str, list[dict[str, Any]]]] = {}
    for slot in present:
        for measurement in all_candidates[slot]:
            bundles.setdefault(_measurement_bundle_key(measurement), {}).setdefault(
                slot, []
            ).append(measurement)

    complete: list[tuple[tuple[Any, ...], dict[str, dict[str, Any]]]] = []
    for candidates_by_slot in bundles.values():
        if any(slot not in candidates_by_slot for slot in present):
            continue
        selected = {
            slot: _strongest(candidates_by_slot[slot], subject_ref)
            for slot in present
        }
        if any(value is None for value in selected.values()):
            continue
        rows = [value for value in selected.values() if value is not None]
        # A bundle is only as strong as its weakest member.  No tool name,
        # measurement id, or other lexical property is a scientific preference.
        complete.append((max(_candidate_priority(row, subject_ref) for row in rows), selected))

    if complete:
        best_priority = min(priority for priority, _ in complete)
        tied = [selected for priority, selected in complete if priority == best_priority]
        payloads = {_refinement_bundle_payload(selected) for selected in tied}
        if len(payloads) > 1:
            ids = "; ".join(
                ",".join(str(row.get("id") or "<missing id>") for row in selected.values())
                for selected in tied
            )
            raise QdsCompletenessError(
                "QDS refinement-summary selection is scientifically ambiguous: "
                f"equally ranked coherent bundles differ in value, status, or context ({ids})."
            )
        # Payloads are identical; ids merely make duplicate selection reproducible.
        selected = min(
            tied,
            key=lambda bundle: tuple(
                str(bundle[slot].get("id") or "") for slot in sorted(bundle)
            ),
        )
        _validate_refinement_arithmetic(selected)
        routed.setdefault(block, {}).update(selected)
        return

    winners = {
        slot: winner
        for slot in present
        if (winner := _strongest(all_candidates[slot], subject_ref)) is not None
    }
    winner_keys = {
        _measurement_bundle_key(winners[slot])
        for slot in present if slot in winners
    }
    detail = ", ".join(
        f"{slot}={winners[slot].get('id')}" for slot in present if slot in winners
    )
    raise QdsCompletenessError(
        "QDS refinement-summary coherence failed: no single evaluation run/tool/"
        "family/subject/task/stage/scope/selector/provenance/reference supplies "
        f"{', '.join(present)}; independent winners were {detail}; "
        f"distinct code paths={len(winner_keys)}."
    )


T15_BUNDLE_SLOTS = (
    "secondary_structure_content",
    "secondary_structure_agreement",
)
T15_BUNDLE_FIELDS = (
    "_source_evaluation_run_ref",
    "bundle_ref",
    "catalog_task_ref",
    "subject_ref",
    "stage",
    "scope",
    "scope_selector",
)
PASSING_STATUSES = {"pass", "pass_with_caveat", "pass_criterion_fail_headline"}


def _bundle_key(
    measurement: dict[str, Any], fields: tuple[str, ...]
) -> tuple[str, ...]:
    return tuple(_context_token(measurement.get(field)) for field in fields)


def _bundle_payload(selected: dict[str, dict[str, Any]]) -> str:
    return yaml.safe_dump(
        {slot: _scientific_payload(row) for slot, row in sorted(selected.items())},
        sort_keys=True,
        allow_unicode=True,
    )


def _select_unique_best_bundle(
    complete: list[tuple[tuple[Any, ...], dict[str, dict[str, Any]]]],
    *,
    label: str,
) -> dict[str, dict[str, Any]]:
    """Choose a bundle by policy and fail when science, rather than ids, ties."""
    best_priority = min(priority for priority, _ in complete)
    tied = [selected for priority, selected in complete if priority == best_priority]
    payloads = {_bundle_payload(selected) for selected in tied}
    if len(payloads) > 1:
        ids = "; ".join(
            ",".join(str(row.get("id") or "<missing id>") for row in bundle.values())
            for bundle in tied
        )
        raise QdsCompletenessError(
            f"QDS {label} selection is scientifically ambiguous: equally ranked "
            f"coherent bundles differ in value, status, or context ({ids})."
        )
    return min(
        tied,
        key=lambda bundle: tuple(
            str(bundle[slot].get("id") or "") for slot in sorted(bundle)
        ),
    )


def _fraction_measurement_value(measurement: dict[str, Any], *, label: str) -> float:
    value = _finite_numeric_value(measurement)
    if value is None:
        raise QdsCompletenessError(f"QDS {label} requires a finite numeric value")
    unit = str((measurement.get("oracle_measure") or {}).get("unit") or "").strip()
    if unit.casefold() in {"%", "percent", "percentage"}:
        return value / 100.0
    if unit.casefold() not in {"", "1", "fraction", "unitless", "dimensionless"}:
        raise QdsCompletenessError(
            f"QDS {label} has unsupported unit {unit!r}; expected fraction or percent"
        )
    return value


def _validate_t15_informational_row(
    row: dict[str, Any], *, label: str, context: str = "bundle"
) -> float:
    """Enforce non-gradeable T15 semantics even when only content is present."""
    value = _fraction_measurement_value(row, label=f"T15 {label}")
    if not 0.0 <= value <= 1.0:
        raise QdsCompletenessError(
            f"QDS T15 {context} is inconsistent: {label} must lie in [0, 1], "
            f"got {value:.6g}"
        )
    if row.get("pass_status") != "informational":
        raise QdsCompletenessError(
            f"QDS T15 {context} is inconsistent: {label} is non-gradeable and must carry "
            "pass_status=informational"
        )
    if row.get("pass_criterion") not in (None, ""):
        raise QdsCompletenessError(
            f"QDS T15 {context} is inconsistent: informational {label} must not "
            "carry pass_criterion"
        )
    return value


def _validate_t15_bundle(selected: dict[str, dict[str, Any]]) -> None:
    content = selected["secondary_structure_content"]
    agreement = selected["secondary_structure_agreement"]
    bundle_refs = {row.get("bundle_ref") for row in selected.values()}
    if None in bundle_refs or "" in bundle_refs or len(bundle_refs) != 1:
        raise QdsCompletenessError(
            "QDS T15 bundle is inconsistent: agreement and content-diagnostic rows "
            "must carry one shared non-empty bundle_ref"
        )
    _validate_t15_informational_row(
        content, label="secondary-structure content diagnostic"
    )
    _validate_t15_informational_row(
        agreement, label="secondary-structure agreement"
    )


def _enforce_coherent_t15_bundle(
    routed: dict[str, dict[str, dict[str, Any]]],
    by_slot: dict[QdsSlot, list[dict[str, Any]]],
    subject_ref: str | None,
) -> None:
    block = "classification_summary"
    candidates = {
        slot: [
            row
            for row in by_slot.get((block, slot), [])
            if _is_selectable_summary_measurement(row)
        ]
        for slot in T15_BUNDLE_SLOTS
    }
    content_rows = candidates["secondary_structure_content"]
    agreement_rows = candidates["secondary_structure_agreement"]
    if not agreement_rows:
        winner = _strongest(content_rows, subject_ref)
        if winner is not None:
            _validate_t15_informational_row(
                winner,
                label="secondary-structure content diagnostic",
                context="content-only row",
            )
            routed.setdefault(block, {})["secondary_structure_content"] = winner
        return

    bundles: dict[tuple[str, ...], dict[str, list[dict[str, Any]]]] = {}
    for slot, rows in candidates.items():
        for row in _eligible_for_subject(rows, subject_ref):
            bundles.setdefault(_bundle_key(row, T15_BUNDLE_FIELDS), {}).setdefault(
                slot, []
            ).append(row)

    complete: list[tuple[tuple[Any, ...], dict[str, dict[str, Any]]]] = []
    for rows_by_slot in bundles.values():
        if any(slot not in rows_by_slot for slot in T15_BUNDLE_SLOTS):
            continue
        selected = {
            slot: _strongest(rows_by_slot[slot], subject_ref)
            for slot in T15_BUNDLE_SLOTS
        }
        if any(row is None for row in selected.values()):
            continue
        concrete = {slot: row for slot, row in selected.items() if row is not None}
        priority = max(_candidate_priority(row, subject_ref) for row in concrete.values())
        complete.append((priority, concrete))

    if not complete:
        agreement_ids = ", ".join(
            str(row.get("id") or "<missing id>") for row in agreement_rows
        )
        raise QdsCompletenessError(
            "QDS T15 coherence failed: secondary-structure agreement requires "
            "a content-diagnostic measurement from the same run, subject, stage, scope, "
            f"and selector; agreement rows were {agreement_ids}."
        )
    selected = _select_unique_best_bundle(complete, label="T15 bundle")
    _validate_t15_bundle(selected)
    routed.setdefault(block, {}).update(selected)


T16_BUNDLE_SLOTS = (
    "interface_buried_surface_area",
    "interface_dockq_score",
    "capri_interface_quality_class",
)
T16_BUNDLE_FIELDS = (
    "_source_evaluation_run_ref",
    "catalog_task_ref",
    "subject_ref",
    "stage",
    "scope",
    "scope_selector",
)
T16_COMPARISON_FIELDS = (
    "reference_subject_ref",
    "oracle_tool_ref",
    "provenance_ref",
    "evidence_refs",
)


def _expected_capri_class(dockq_score: float) -> str:
    if dockq_score >= 0.80:
        return "high"
    if dockq_score >= 0.49:
        return "medium"
    if dockq_score >= 0.23:
        return "acceptable"
    return "incorrect"


def _validate_t16_bundle(selected: dict[str, dict[str, Any]]) -> None:
    dockq = selected.get("interface_dockq_score")
    capri = selected.get("capri_interface_quality_class")
    if capri is not None and dockq is None:
        raise QdsCompletenessError(
            "QDS T16 coherence failed: CAPRI class cannot be verified without "
            "a same-comparison DockQ score"
        )
    if dockq is None or capri is None:
        return
    score = _finite_numeric_value(dockq)
    if score is None or not 0.0 <= score <= 1.0:
        raise QdsCompletenessError(
            "QDS T16 CAPRI consistency failed: DockQ must be a finite value in [0, 1]"
        )
    observed = str((capri.get("oracle_measure") or {}).get("value_text") or "").strip()
    normalized = re.sub(r"[\s_-]+", " ", observed.casefold()).strip()
    normalized = normalized.removesuffix(" quality")
    expected = _expected_capri_class(score)
    if normalized != expected:
        raise QdsCompletenessError(
            "QDS T16 CAPRI consistency failed: "
            f"DockQ {score:.6g} implies {expected!r}, not {observed!r}"
        )


def _enforce_coherent_t16_bundle(
    routed: dict[str, dict[str, dict[str, Any]]],
    by_slot: dict[QdsSlot, list[dict[str, Any]]],
    subject_ref: str | None,
) -> None:
    block = "interface_quality_summary"
    candidates = {
        slot: [
            row
            for row in by_slot.get((block, slot), [])
            if _is_selectable_summary_measurement(row)
        ]
        for slot in T16_BUNDLE_SLOTS
    }
    present = tuple(slot for slot in T16_BUNDLE_SLOTS if candidates[slot])
    if not present:
        return
    if "capri_interface_quality_class" in present and "interface_dockq_score" not in present:
        raise QdsCompletenessError(
            "QDS T16 coherence failed: CAPRI class is present without a DockQ score"
        )

    by_core: dict[tuple[str, ...], dict[str, list[dict[str, Any]]]] = {}
    for slot in present:
        for row in _eligible_for_subject(candidates[slot], subject_ref):
            by_core.setdefault(_bundle_key(row, T16_BUNDLE_FIELDS), {}).setdefault(
                slot, []
            ).append(row)

    complete: list[tuple[tuple[Any, ...], dict[str, dict[str, Any]]]] = []
    for rows_by_slot in by_core.values():
        if any(slot not in rows_by_slot for slot in present):
            continue

        # DockQ and its derived CAPRI class must name the exact same native,
        # tool/provenance path, and retained raw evidence. The interface mapping
        # itself is represented by the shared scope_selector in the core key.
        comparison_slots = tuple(
            slot
            for slot in ("interface_dockq_score", "capri_interface_quality_class")
            if slot in present
        )
        comparison_groups: dict[
            tuple[str, ...], dict[str, list[dict[str, Any]]]
        ] = {}
        for slot in comparison_slots:
            for row in rows_by_slot[slot]:
                comparison_groups.setdefault(
                    _bundle_key(row, T16_COMPARISON_FIELDS), {}
                ).setdefault(slot, []).append(row)

        comparison_options: list[dict[str, dict[str, Any]]] = []
        if comparison_slots:
            for rows_by_comparison_slot in comparison_groups.values():
                if any(slot not in rows_by_comparison_slot for slot in comparison_slots):
                    continue
                selected_comparison = {
                    slot: _strongest(rows_by_comparison_slot[slot], subject_ref)
                    for slot in comparison_slots
                }
                if all(row is not None for row in selected_comparison.values()):
                    comparison_options.append(
                        {
                            slot: row
                            for slot, row in selected_comparison.items()
                            if row is not None
                        }
                    )
        else:
            comparison_options.append({})

        for comparison in comparison_options:
            selected = dict(comparison)
            if "interface_buried_surface_area" in present:
                bsa = _strongest(
                    rows_by_slot["interface_buried_surface_area"], subject_ref
                )
                if bsa is None:
                    continue
                # An explicitly comparative BSA must not contradict the selected
                # native path. Candidate-only BSA may and should retain its own
                # calculation evidence, distinct from the DockQ evidence.
                anchor = comparison.get("interface_dockq_score") or comparison.get(
                    "capri_interface_quality_class"
                )
                if anchor is not None:
                    for field in ("reference_subject_ref",):
                        bsa_value = bsa.get(field)
                        if bsa_value not in (None, "", []) and bsa_value != anchor.get(field):
                            break
                    else:
                        selected["interface_buried_surface_area"] = bsa
                        anchor = None
                    if anchor is not None:
                        continue
                else:
                    selected["interface_buried_surface_area"] = bsa
            if any(slot not in selected for slot in present):
                continue
            priority = max(_candidate_priority(row, subject_ref) for row in selected.values())
            complete.append((priority, selected))

    if not complete:
        details = ", ".join(
            f"{slot}={','.join(str(row.get('id') or '<missing id>') for row in candidates[slot])}"
            for slot in present
        )
        raise QdsCompletenessError(
            "QDS T16 coherence failed: no single run/subject/interface and "
            "reference/mapping/evidence comparison supplies the published slots; "
            + details
        )
    selected = _select_unique_best_bundle(complete, label="T16 interface bundle")
    _validate_t16_bundle(selected)
    routed.setdefault(block, {}).update(selected)


def _validate_t16_interface_contexts(eval_runs: list[dict[str, Any]]) -> None:
    """Resolve every headline T16 selector to its declared mapping/evidence row."""
    metric_fields = {
        "T16_interface_buried_surface_area": "buried_surface_area",
        "T16_interface_dockq_score": "dockq_score",
        "T16_capri_interface_quality_class": "capri_quality_class",
    }
    comparative_ids = {
        "T16_interface_dockq_score",
        "T16_capri_interface_quality_class",
    }
    errors: list[str] = []
    for run in eval_runs:
        run_id = str(run.get("id") or "<missing id>")
        index: dict[str, dict[str, Any]] = {}
        for interface in run.get("interface_qualities", []) or []:
            interface_id = str(interface.get("id") or "").strip()
            if not interface_id:
                errors.append(f"{run_id}: InterfaceQuality row has no id")
            elif interface_id in index:
                errors.append(
                    f"{run_id}: duplicate InterfaceQuality id {interface_id!r}"
                )
            else:
                index[interface_id] = interface

        for measurement in run.get("measurements", []) or []:
            metric_id = measurement.get("metric_definition_ref")
            if metric_id not in metric_fields or measurement.get("stage") not in (
                "final",
                "all",
            ):
                continue
            measurement_id = str(measurement.get("id") or "<missing id>")
            if measurement.get("scope") != "interface":
                errors.append(
                    f"{run_id}/{measurement_id}: {metric_id} must use scope=interface"
                )
                continue
            selector = str(measurement.get("scope_selector") or "").strip()
            interface = index.get(selector)
            if interface is None:
                errors.append(
                    f"{run_id}/{measurement_id}: interface selector {selector!r} "
                    "does not resolve to a unique InterfaceQuality row"
                )
                continue
            measurement_subject = measurement.get("subject_ref") or None
            interface_subject = interface.get("subject_ref") or None
            # Preserve historical all-unlabelled runs, but never let one
            # half-labelled pair turn an unbound scalar or structured row into
            # evidence for the other side's concrete subject.
            if measurement_subject != interface_subject:
                errors.append(
                    f"{run_id}/{measurement_id}: subject_ref does not exactly match "
                    f"InterfaceQuality {selector!r} (measurement={measurement_subject!r}, "
                    f"interface={interface_subject!r})"
                )
            interface_field = metric_fields[metric_id]
            observed_payload = measurement.get("oracle_measure")
            structured_payload = interface.get(interface_field)
            if (
                not isinstance(observed_payload, dict)
                or not isinstance(structured_payload, dict)
                or _context_token(observed_payload) != _context_token(structured_payload)
            ):
                errors.append(
                    f"{run_id}/{measurement_id}: oracle_measure does not exactly match "
                    f"InterfaceQuality {selector!r} field {interface_field!r} "
                    f"(measurement={observed_payload!r}, interface={structured_payload!r})"
                )
            measurement_evidence = measurement.get("evidence_refs") or []
            interface_evidence = interface.get("evidence_refs") or []
            if not measurement_evidence:
                errors.append(
                    f"{run_id}/{measurement_id}: T16 measurement has no retained "
                    "evidence_refs"
                )
            elif not set(measurement_evidence).issubset(set(interface_evidence)):
                errors.append(
                    f"{run_id}/{measurement_id}: evidence_refs are not retained by "
                    f"InterfaceQuality {selector!r}"
                )
            if metric_id not in comparative_ids:
                continue
            reference = measurement.get("reference_subject_ref")
            interface_reference = interface.get("reference_subject_ref")
            if not reference:
                errors.append(
                    f"{run_id}/{measurement_id}: comparative T16 measurement has no "
                    "reference_subject_ref"
                )
            elif reference != interface_reference:
                errors.append(
                    f"{run_id}/{measurement_id}: reference_subject_ref does not match "
                    f"InterfaceQuality {selector!r}"
                )
            if not interface.get("model_to_native_chain_mapping"):
                errors.append(
                    f"{run_id}/{measurement_id}: InterfaceQuality {selector!r} has no "
                    "model_to_native_chain_mapping"
                )
    if errors:
        raise QdsCompletenessError(
            "QDS T16 interface-context integrity failed:\n  - "
            + "\n  - ".join(errors)
        )


# ---------------------------------------------------------------------------
# Block builders driven by the routing table
# ---------------------------------------------------------------------------


def _build_block_from_routed(qds_id: str, slot: str, routed: dict[str, dict[str, Any]] | None) -> dict[str, Any] | None:
    if not routed:
        return None
    populated: dict[str, Any] = {}
    for slot_name, meas in routed.items():
        v = _wrap_value(meas)
        if v:
            populated[slot_name] = v
    if not populated:
        return None
    return {"id": f"{qds_id}_{slot}", **populated}


# ---------------------------------------------------------------------------
# Identity, cross-tool coverage
# ---------------------------------------------------------------------------


def build_identity_block(
    qds_id: str,
    structure_id: str,
    structure_method: str | None = None,
    resolution_a: float | None = None,
    space_group: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    block: dict[str, Any] = {"id": f"{qds_id}_identity"}
    sid = structure_id.lower()
    if sid.startswith("emdb"):
        block["emdb_id"] = structure_id
    elif sid.startswith("af-") or sid.startswith("af_"):
        block["alphafold_id"] = structure_id
    else:
        block["pdb_id"] = structure_id
    if structure_method is not None:
        block["method"] = structure_method
    if resolution_a is not None:
        block["resolution_a"] = resolution_a
    if space_group is not None:
        block["space_group"] = space_group
    if description is not None:
        block["description"] = description
    return block


STRUCTURE_IDENTITY_FIELDS = (
    "method",
    "resolution_a",
    "space_group",
    "description",
)


def _resolve_structure_identity_metadata(
    structures: list[dict[str, Any]],
    structure_id: str,
    *,
    structure_method: str | None,
    resolution_a: float | None,
    space_group: str | None,
    structure_description: str | None,
) -> tuple[str | None, float | None, str | None, str | None]:
    """Resolve identity metadata from a pinned input Structure when present.

    Older callers without ``structures`` retain the explicit-argument API. Once
    an input supplies Structure records, the matching record is authoritative:
    arguments may confirm it but cannot add to or override it. This gives QDS
    replay a source independent of the committed identity block itself.
    """
    explicit = {
        "method": structure_method,
        "resolution_a": resolution_a,
        "space_group": space_group,
        "description": structure_description,
    }
    if not structures:
        return (
            structure_method,
            resolution_a,
            space_group,
            structure_description,
        )

    malformed = [
        index for index, row in enumerate(structures) if not isinstance(row, dict)
    ]
    if malformed:
        raise QdsCompletenessError(
            "QDS structure identity source failed: top-level structures entries "
            f"must be mappings (invalid indices: {malformed})"
        )
    matches = [row for row in structures if row.get("id") == structure_id]
    if not matches:
        declared = sorted(
            str(row.get("id")) for row in structures if row.get("id") is not None
        )
        raise QdsCompletenessError(
            "QDS structure identity source failed: input structures do not declare "
            f"requested structure_id {structure_id!r} (declared: {declared})"
        )
    canonical = {
        yaml.safe_dump(row, sort_keys=True, allow_unicode=True) for row in matches
    }
    if len(canonical) != 1:
        raise QdsCompletenessError(
            "QDS structure identity source failed: conflicting top-level Structure "
            f"records declare id {structure_id!r}"
        )
    source = matches[0]
    mismatches = [
        field
        for field in STRUCTURE_IDENTITY_FIELDS
        if explicit[field] is not None and explicit[field] != source.get(field)
    ]
    if mismatches:
        details = ", ".join(
            f"{field}: argument={explicit[field]!r}, source={source.get(field)!r}"
            for field in mismatches
        )
        raise QdsCompletenessError(
            "QDS structure identity source failed: explicit identity metadata "
            f"conflicts with Structure {structure_id!r} ({details})"
        )
    return (
        source.get("method"),
        source.get("resolution_a"),
        source.get("space_group"),
        source.get("description"),
    )


COVERAGE_CONTEXT_FIELDS = (
    "catalog_task_ref",
    "metric_definition_ref",
    "stage",
    "scope",
    "scope_selector",
    "reference_subject_ref",
)

# A composite row cannot gain independent-family credit merely by naming an
# arbitrary non-cctbx measurement in ``derived_from_measurement_refs``.  Each
# metric whose value genuinely combines tool families needs an explicit
# coverage contract.  The T14 conflict count is currently the only such metric:
# it is jointly derived from the two candidate inventories named below.
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


def _coverage_context_key(measurement: dict[str, Any]) -> tuple[str, ...]:
    """Claim context excluding subject, which is resolved within each group."""
    return tuple(_context_token(measurement.get(field)) for field in COVERAGE_CONTEXT_FIELDS)


def _has_numeric_oracle_value(measurement: dict[str, Any]) -> bool:
    return _finite_numeric_value(measurement) is not None


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
    """Keep T14 opportunity counts and structure results non-gradeable."""
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
    """Return the tools/families that actually participate in each numeric row.

    Direct measurements contribute their own canonical tool family.  A composite
    may additionally inherit its direct sources only through an explicit contract
    above.  The contract and same-run/context checks are deliberately repeated in
    the emitter: QDS emission is a public API and must not rely on callers having
    run the repository-wide referential-integrity gate first.
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
            # Generic lineage remains useful provenance, but it is not enough to
            # confer independent-family trust coverage without a metric-specific
            # contract that prevents unrelated-oracle laundering.
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


def _coverage_id(qds_id: str, context: tuple[str, ...]) -> str:
    task = re.sub(r"[^A-Za-z0-9]+", "_", context[0]).strip("_") or "task"
    metric = re.sub(r"[^A-Za-z0-9]+", "_", context[1]).strip("_") or "metric"
    digest = hashlib.sha256("\x1f".join(context).encode()).hexdigest()[:12]
    return f"{qds_id}_coverage_{task}_{metric}_{digest}"


def build_cross_tool_coverage(
    qds_id: str,
    measurements: list[dict[str, Any]],
    subject_ref: str | None = None,
    tool_families: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Report independent-family coverage per metric and comparison context.

    A task-level union is scientifically unsafe: a non-cctbx oracle for one
    metric cannot validate a cctbx-only claim about another.  Text-only attempts
    (including an aborted tool invocation) are retained as informational context
    but never close quantitative coverage.
    """
    canonical_measurements = _canonicalize_measurement_tools(
        measurements,
        context="cross-tool coverage",
        tool_families=tool_families,
    )
    participants_by_row = _derived_coverage_participants(canonical_measurements)
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for measurement in canonical_measurements:
        if not measurement.get("catalog_task_ref"):
            continue
        _validate_measurement_value_carriers(measurement, require_oracle=True)
        grouped.setdefault(_coverage_context_key(measurement), []).append(measurement)

    rows: list[dict[str, Any]] = []
    for context in sorted(grouped):
        candidates = _eligible_for_subject(grouped[context], subject_ref)
        exact = [row for row in candidates if row.get("subject_ref") == subject_ref]
        if subject_ref is not None and exact:
            candidates = exact

        numeric = [row for row in candidates if _has_numeric_oracle_value(row)]
        text_only = [
            row
            for row in candidates
            if not _has_numeric_oracle_value(row) and _has_oracle_payload(row)
        ]
        # Validate every categorical row before splitting numeric from text.
        # Otherwise {value_numeric, value_text} (or numeric-only categorical
        # data) would enter the numeric bucket and skip the informational-only
        # rule entirely.
        for measurement in candidates:
            if measurement.get("metric_definition_ref") in TEXTUAL_SUMMARY_METRIC_IDS:
                _is_selectable_summary_measurement(measurement)
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
                if status in PASSING_STATUSES:
                    classes.add("pass")
                elif status == "fail_criterion" or status.startswith("fail_by_oracle"):
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
            {str(row.get("oracle_tool_ref") or "<unnamed oracle>") for row in text_only}
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
            "id": _coverage_id(qds_id, context),
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


# ---------------------------------------------------------------------------
# Per-residue, site, ligand, pairwise, predicted, tool-recs
# ---------------------------------------------------------------------------


def _summary_stats(values: list[float]) -> dict[str, Any] | None:
    if not values:
        return None
    return {
        "value_numeric": statistics.fmean(values),
        "mean": statistics.fmean(values),
        "std_dev": statistics.pstdev(values) if len(values) > 1 else 0.0,
        "min_value": min(values),
        "max_value": max(values),
        "count": len(values),
    }


def _per_residue_values_by_metric(eval_runs: list[dict[str, Any]]) -> dict[str, list[float]]:
    """Group EvaluationRun.per_residue_values[] by underlying metric id."""
    out: dict[str, list[float]] = {}
    for r in eval_runs:
        for prv in r.get("per_residue_values", []) or []:
            mid = (prv.get("value") or {}).get("metric_definition_ref") or prv.get("metric_definition_ref")
            v = (prv.get("value") or {}).get("value_numeric")
            if mid is None or v is None:
                continue
            out.setdefault(mid, []).append(v)
    return out


PER_RESIDUE_METRIC_TO_SLOT: dict[str, str] = {
    "T01_per_residue_lddt":         "lddt_per_residue",
    "T01_per_residue_displacement": "displacement_per_residue_a",
    "T05_per_residue_rsrz":         "rsrz_per_residue",
    "T05_ramachandran_z_per_residue": "ramachandran_z_per_residue",
    "T06_residue_rscc":             "rscc_per_residue",
    "T05_b_factor_outlier_z":       "b_factor_z_per_residue",
    "T15_secondary_structure_assignment": "secondary_structure_per_residue",
    "T12_local_model_map_fsc_q":    "fsc_q_per_residue",
}


def build_per_residue_quality(qds_id: str, eval_runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Aggregate per-residue content from all eval_runs into one block.

    Source: EvaluationRun.{residue_outliers, density_peaks, flagged_regions,
    per_residue_values}. The PerResidueValue.metric_definition_ref routes
    each value to its array via PER_RESIDUE_METRIC_TO_SLOT — no substring
    matching.
    """
    outliers: list[dict[str, Any]] = []
    density_peaks: list[dict[str, Any]] = []
    flagged_regions: list[dict[str, Any]] = []
    arrays: dict[str, list[dict[str, Any]]] = {slot: [] for slot in PER_RESIDUE_METRIC_TO_SLOT.values()}

    for r in eval_runs:
        outliers.extend(r.get("residue_outliers", []) or [])
        density_peaks.extend(r.get("density_peaks", []) or [])
        flagged_regions.extend(r.get("flagged_regions", []) or [])

        for prv in r.get("per_residue_values", []) or []:
            mid = prv.get("metric_definition_ref")
            slot = PER_RESIDUE_METRIC_TO_SLOT.get(mid or "")
            if slot:
                arrays[slot].append(prv)

    has_arrays = any(arrays[slot] for slot in arrays)
    if not any([outliers, density_peaks, flagged_regions, has_arrays]):
        return None

    block: dict[str, Any] = {"id": f"{qds_id}_per_residue"}
    for slot, items in arrays.items():
        if items:
            block[slot] = items
    if outliers:
        block["outliers"] = outliers
    if density_peaks:
        block["density_peaks"] = density_peaks
    if flagged_regions:
        block["flagged_regions"] = flagged_regions
    return block


def build_site_qualities(
    qds_id: str,
    eval_runs: list[dict[str, Any]],
    subject_ref: str | None = None,
) -> list[dict[str, Any]]:
    """For each Site declared on any eval run, build a SiteQuality.

    Site-scoped measurements (scope=site, scope_selector matching the
    site id) populate site_clashscore, site_ramachandran_outlier_count,
    site_rmsd_to_reference_a, mean_per_residue_lddt, mean_b_factor.
    Ligand-scoped measurements via the bound ligand populate
    ligand_quality.
    """
    site_metric_to_slot: dict[str, str] = {
        "T05_clashscore": "site_clashscore",
        "T05_ramachandran_outlier": "site_ramachandran_outlier_count",
        # Per-pair RMSD for sites uses the shared T01 metric ids.
        "T01_ca_rmsd_å": "site_rmsd_to_reference_a",
    }
    ligand_metric_to_slot: dict[str, str] = {
        "T10_ligand_rscc":                  "rscc",
        "T10_ligand_rsr":                   "rsr",
        "T10_ligand_b_vs_surroundings":     "ligand_b_factor_vs_surroundings",
        "T10_protein-ligand_hbond_count":   "protein_ligand_hbond_count",
        "T10_rmsd_to_deposited_ligand_pose": "pose_rmsd_to_deposited_a",
        "T10_ligand_element_identity":       "element_identity",
    }

    sites: list[dict[str, Any]] = [s for r in eval_runs for s in (r.get("sites") or [])]
    ligand_rows: list[dict[str, Any]] = [
        lig for r in eval_runs for lig in (r.get("ligands") or [])
    ]
    errors: list[str] = []

    def index_unique(rows: list[dict[str, Any]], kind: str) -> dict[str, dict[str, Any]]:
        indexed: dict[str, dict[str, Any]] = {}
        for row in rows:
            row_id = row.get("id")
            if not row_id:
                errors.append(f"{kind} declaration has no id")
                continue
            if row_id in indexed:
                errors.append(f"duplicate {kind} id {row_id!r}")
                continue
            indexed[row_id] = row
        return indexed

    site_index = index_unique(sites, "Site")
    ligand_index = index_unique(ligand_rows, "Ligand")
    ligand_to_sites: dict[str, list[str]] = {}
    for site in sites:
        lig_ref = site.get("ligand_ref")
        if not lig_ref:
            continue
        if lig_ref not in ligand_index:
            errors.append(
                f"Site {site.get('id')!r} has ligand_ref {lig_ref!r}, but that Ligand is not declared"
            )
        ligand_to_sites.setdefault(lig_ref, []).append(site.get("id") or "<missing id>")

    # Index and validate every local-scope measurement before emitting any block.
    # This is deliberately selector-specific: the old completeness check only
    # proved that *some* SiteQuality/LigandQuality existed, allowing a sibling
    # measurement with a bad selector to disappear silently (#392).
    site_measurements: dict[str, list[dict[str, Any]]] = {}
    ligand_measurements: dict[str, list[dict[str, Any]]] = {}
    for r in eval_runs:
        for m in r.get("measurements", []) or []:
            if m.get("stage") not in ("final", "all"):
                continue
            scope = m.get("scope")
            if scope not in ("site", "ligand"):
                continue
            selector = m.get("scope_selector") or ""
            measurement_id = m.get("id") or "<missing id>"
            metric_id = m.get("metric_definition_ref") or "<missing metric>"
            if scope == "site":
                if selector not in site_index:
                    errors.append(
                        f"measurement {measurement_id!r} has scope=site selector "
                        f"{selector!r}, which does not resolve to a declared Site"
                    )
                if metric_id not in site_metric_to_slot:
                    errors.append(
                        f"unconsumed scope=site measurement {measurement_id!r}: "
                        f"metric {metric_id!r} has no SiteQuality slot"
                    )
                site_measurements.setdefault(selector, []).append(m)
                continue

            if selector not in ligand_index:
                errors.append(
                    f"measurement {measurement_id!r} has scope=ligand selector "
                    f"{selector!r}, which does not resolve to a declared Ligand"
                )
            bound_sites = ligand_to_sites.get(selector, [])
            if len(bound_sites) != 1:
                errors.append(
                    f"measurement {measurement_id!r} selects Ligand {selector!r}, "
                    f"which must be bound to exactly one Site; found {bound_sites!r}"
                )
            if metric_id not in ligand_metric_to_slot:
                errors.append(
                    f"unconsumed scope=ligand measurement {measurement_id!r}: "
                    f"metric {metric_id!r} has no LigandQuality slot"
                )
            ligand_measurements.setdefault(selector, []).append(m)

    if errors:
        raise QdsCompletenessError(
            "QDS scoped-measurement integrity failed:\n  - " + "\n  - ".join(errors)
        )

    if not sites:
        return []

    out: list[dict[str, Any]] = []
    for site in sites:
        sq: dict[str, Any] = {
            "id": f"{qds_id}_site_quality_{site['id']}",
            "site_ref": site["id"],
        }
        # Site-scoped measurements.
        site_by_slot: dict[str, list[dict[str, Any]]] = {}
        for measurement in site_measurements.get(site["id"], []):
            slot = site_metric_to_slot.get(measurement.get("metric_definition_ref") or "")
            if slot:
                site_by_slot.setdefault(slot, []).append(measurement)
        for slot, candidates in site_by_slot.items():
            winner = _strongest(candidates, subject_ref)
            value = _wrap_value(winner)
            if value:
                sq[slot] = value
            else:
                raise QdsCompletenessError(
                    "QDS scoped-measurement integrity failed: selected site "
                    f"measurement for {site['id']!r}/{slot!r} has no value to emit"
                )

        # Ligand quality (when the site has a bound ligand).
        lig_ref = site.get("ligand_ref")
        if lig_ref and lig_ref in ligand_measurements:
            lq: dict[str, Any] = {
                "id": f"{qds_id}_ligand_quality_{lig_ref}",
                "ligand_ref": lig_ref,
            }
            ligand_by_slot: dict[str, list[dict[str, Any]]] = {}
            for measurement in ligand_measurements[lig_ref]:
                slot = ligand_metric_to_slot.get(
                    measurement.get("metric_definition_ref") or ""
                )
                if slot:
                    ligand_by_slot.setdefault(slot, []).append(measurement)
            for slot, candidates in ligand_by_slot.items():
                winner = _strongest(candidates, subject_ref)
                value = _wrap_value(winner)
                if value:
                    lq[slot] = value
                else:
                    raise QdsCompletenessError(
                        "QDS scoped-measurement integrity failed: selected ligand "
                        f"measurement for {lig_ref!r}/{slot!r} has no value to emit"
                    )
            if len(lq) > 2:  # more than just id + ligand_ref
                sq["ligand_quality"] = lq

        out.append(sq)
    return out


def build_pairwise_comparisons(eval_runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pass-through any PairwiseComparison records on the eval runs."""
    return [pc for r in eval_runs for pc in (r.get("pairwise_comparisons") or [])]


def build_predicted_confidence_summary(
    qds_id: str,
    eval_runs: list[dict[str, Any]],
    structure_method: str | None = None,
    subject_ref: str | None = None,
) -> dict[str, Any] | None:
    """Emit when method is `predicted_model` or pLDDT/PAE metrics appear.

    The catalog now declares pTM/ipTM/convergence metric ids, so populate
    those fields directly from final/all measurements instead of emitting an
    id-only placeholder.
    """
    measurements = [
        m
        for r in eval_runs
        for m in r.get("measurements", []) or []
        if m.get("stage") in ("final", "all")
        and m.get("metric_definition_ref") in PREDICTED_MARKER_METRIC_IDS
    ]
    has_predicted_metrics = bool(measurements)
    if structure_method != "predicted_model" and not has_predicted_metrics:
        return None
    routed = _route_measurements(measurements, subject_ref).get(
        "predicted_confidence_summary"
    )
    block = _build_block_from_routed(qds_id, "predicted_confidence", routed)
    if block:
        return block
    if structure_method == "predicted_model":
        return {"id": f"{qds_id}_predicted_confidence"}
    return None


# NOTE: a block's (name, rows-key) association is repeated across three tables
# below — this one (build), SCOPE_IMPLIED_ROWS (scope->block check), and
# EVAL_ROWS_IMPLIED_BLOCKS (eval-rows check). They are deliberately kept
# separate: each serves a different consumer with different fields, and the
# `ensemble` scope is special-cased inline, so a single master table would be a
# wide sparse config every consumer mostly ignores (see issue #5). If you rename
# a block or its rows key, update all three tables together.
#
# Optional summary blocks that carry both routed scalar slots and row lists
# copied straight off the eval runs: (QDS block name, block-id suffix,
# row keys — same name on the EvaluationRun and on the QDS block).
ROW_BEARING_SUMMARY_BLOCKS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "classification_summary",
        "classification",
        ("secondary_structure_assignments", "domain_assignments"),
    ),
    ("interface_quality_summary", "interface_quality", ("interface_qualities",)),
    (
        "prediction_ensemble_summary",
        "prediction_ensemble",
        ("prediction_ensemble_qualities",),
    ),
    ("nmr_validation_summary", "nmr_validation", ("nmr_ensemble_qualities",)),
)


def build_row_bearing_summary(
    qds_id: str,
    id_suffix: str,
    routed: dict[str, dict[str, Any]] | None,
    eval_runs: list[dict[str, Any]],
    row_keys: tuple[str, ...],
    subject_ref: str | None = None,
) -> dict[str, Any] | None:
    """Build one optional summary block: routed scalar slots plus row lists.

    `row_keys` are gathered from every eval run under the same key they take
    on the QDS block. Returns None when neither a routed slot nor a row list
    is present, so the block is omitted rather than emitted id-only.
    """
    block = _build_block_from_routed(qds_id, id_suffix, routed) or {
        "id": f"{qds_id}_{id_suffix}"
    }
    for key in row_keys:
        rows = [x for r in eval_runs for x in (r.get(key) or [])]
        if subject_ref is not None:
            exact = [row for row in rows if row.get("subject_ref") == subject_ref]
            rows = exact or [row for row in rows if not row.get("subject_ref")]
        if rows:
            block[key] = rows
    return block if len(block) > 1 else None


def _input_assumptions(run: dict[str, Any]) -> list[dict[str, Any]]:
    assumptions = list(run.get("assumptions", []) or [])
    for measurement in run.get("measurements", []) or []:
        assumptions.extend(measurement.get("assumptions", []) or [])
    return assumptions


def _validate_assumption_supersessions(eval_runs: list[dict[str, Any]]) -> None:
    """Require every supersession to resolve to an earlier input assumption."""
    occurrences: dict[str, list[int]] = {}
    for index, run in enumerate(eval_runs):
        for assumption in _input_assumptions(run):
            assumption_id = assumption.get("id")
            if assumption_id:
                occurrences.setdefault(str(assumption_id), []).append(index)

    errors: list[str] = []
    for index, run in enumerate(eval_runs):
        refs = run.get("superseded_assumption_refs", []) or []
        run_id = str(run.get("id") or f"input run {index + 1}")
        duplicate_refs = sorted(
            {str(ref) for ref in refs if refs.count(ref) > 1}
        )
        for ref in duplicate_refs:
            errors.append(f"{run_id}: duplicate superseded assumption ref {ref!r}")
        for ref_value in dict.fromkeys(refs):
            ref = str(ref_value)
            positions = occurrences.get(ref, [])
            if any(position < index for position in positions):
                continue
            if index in positions:
                errors.append(
                    f"{run_id}: superseded assumption ref {ref!r} is self-referential; "
                    "only assumptions from earlier input runs may be withdrawn"
                )
            elif positions:
                errors.append(
                    f"{run_id}: superseded assumption ref {ref!r} points to a future "
                    "input run"
                )
            else:
                errors.append(
                    f"{run_id}: superseded assumption ref {ref!r} is dangling"
                )
    if errors:
        raise QdsCompletenessError(
            "QDS assumption-supersession integrity failed:\n  - "
            + "\n  - ".join(errors)
        )


def _timezone_aware_datetime(value: Any, *, label: str) -> dt.datetime:
    """Parse one exact instant and reject timezone-ambiguous timestamps."""
    if isinstance(value, dt.datetime):
        parsed = value
    else:
        try:
            parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise QdsCompletenessError(
                f"{label} {value!r} is not a valid ISO-8601 timestamp"
            ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise QdsCompletenessError(
            f"{label} {value!r} must include an explicit timezone offset"
        )
    return parsed.astimezone(dt.timezone.utc)


def _registry_cutoff_instant(issued_at: Any) -> dt.datetime | None:
    """Return the precise instant governing one immutable registry snapshot."""
    if issued_at is None:
        return None
    return _timezone_aware_datetime(issued_at, label="QDS issued_at")


def _registry_row_date(row: dict[str, Any], *, registry_name: str) -> dt.date:
    """Read the activation date required for immutable registry selection."""
    row_id = str(row.get("id") or "<missing id>")
    raw_date = row.get("as_of_date")
    if raw_date is None:
        raise QdsCompletenessError(
            f"{registry_name} row {row_id!r} has no as_of_date; immutable QDS "
            "emission requires dated registry rows"
        )
    if isinstance(raw_date, dt.datetime):
        row_date = raw_date.date()
    elif isinstance(raw_date, dt.date):
        row_date = raw_date
    else:
        try:
            row_date = dt.date.fromisoformat(str(raw_date))
        except ValueError as exc:
            raise QdsCompletenessError(
                f"{registry_name} row {row_id!r} has invalid as_of_date "
                f"{raw_date!r}"
            ) from exc
    return row_date


def _registry_row_activation(
    row: dict[str, Any], *, registry_name: str
) -> dt.datetime:
    """Read and cross-check the exact activation instant for one registry row."""
    row_id = str(row.get("id") or "<missing id>")
    declared_date = _registry_row_date(row, registry_name=registry_name)
    raw_instant = row.get("effective_at")
    if raw_instant is None:
        raise QdsCompletenessError(
            f"{registry_name} row {row_id!r} has no effective_at; immutable QDS "
            "emission requires an exact activation timestamp"
        )
    activation = _timezone_aware_datetime(
        raw_instant, label=f"{registry_name} row {row_id!r} effective_at"
    )
    local_value = (
        raw_instant
        if isinstance(raw_instant, dt.datetime)
        else dt.datetime.fromisoformat(str(raw_instant).replace("Z", "+00:00"))
    )
    if local_value.date() != declared_date:
        raise QdsCompletenessError(
            f"{registry_name} row {row_id!r} has as_of_date {declared_date} but "
            f"effective_at falls on {local_value.date()}"
        )
    return activation


def _active_registry_rows(
    rows: list[dict[str, Any]],
    *,
    issued_at: Any,
    registry_name: str,
    supersedes_field: str,
) -> list[dict[str, Any]]:
    """Time-slice a versioned registry and retire active predecessors.

    Revisions are append-only: a new dated id names the row it supersedes,
    leaving the predecessor available to sheets issued before that date.
    """
    by_id: dict[str, dict[str, Any]] = {}
    activations: dict[str, dt.datetime] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise QdsCompletenessError(
                f"{registry_name} row {index} must be an object"
            )
        row_id = str(row.get("id") or "").strip()
        if not row_id:
            raise QdsCompletenessError(f"{registry_name} row {index} has no id")
        if row_id in by_id:
            raise QdsCompletenessError(
                f"{registry_name} contains duplicate id {row_id!r}"
            )
        by_id[row_id] = row
        activations[row_id] = _registry_row_activation(
            row, registry_name=registry_name
        )

    cutoff = _registry_cutoff_instant(issued_at)
    active_ids = {
        row_id
        for row_id, activation in activations.items()
        if cutoff is None or activation <= cutoff
    }
    predecessor_to_successor: dict[str, str] = {}
    superseded: set[str] = set()
    lineage: dict[str, str] = {}
    # Validate the complete append-only graph before the issue-time slice.
    # Otherwise a malformed future revision could sit undetected until the
    # day it activates and retroactively break every repository validation.
    for row_id in by_id:
        predecessor_value = by_id[row_id].get(supersedes_field)
        if predecessor_value is None:
            continue
        predecessor = str(predecessor_value).strip()
        if not predecessor or predecessor not in by_id:
            raise QdsCompletenessError(
                f"{registry_name} row {row_id!r} has dangling "
                f"{supersedes_field} {predecessor_value!r}"
            )
        if predecessor == row_id:
            raise QdsCompletenessError(
                f"{registry_name} row {row_id!r} supersedes itself"
            )
        if activations[predecessor] > activations[row_id]:
            raise QdsCompletenessError(
                f"{registry_name} row {row_id!r} supersedes later-dated row "
                f"{predecessor!r}"
            )
        prior_successor = predecessor_to_successor.get(predecessor)
        if prior_successor is not None and prior_successor != row_id:
            raise QdsCompletenessError(
                f"{registry_name} row {predecessor!r} has multiple active "
                f"successors: {prior_successor!r}, {row_id!r}"
            )
        predecessor_to_successor[predecessor] = row_id
        lineage[row_id] = predecessor
        if row_id in active_ids and predecessor in active_ids:
            superseded.add(predecessor)

    for start in lineage:
        seen: set[str] = set()
        current = start
        while current in lineage:
            if current in seen:
                raise QdsCompletenessError(
                    f"{registry_name} contains a supersession cycle at {current!r}"
                )
            seen.add(current)
            current = lineage[current]

    return [
        row
        for row in rows
        if str(row.get("id")) in active_ids and str(row.get("id")) not in superseded
    ]


def build_assumptions_report(
    eval_runs: list[dict[str, Any]],
    issued_at: Any = None,
    registry_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Aggregate per-tool, per-measurement, per-run assumptions into a flat list.

    Source order (and the order surfaced in the QDS):
      1. Tool-level: every distinct oracle_tool_ref in the eval's measurements
         is looked up in ref/tool_assumptions.yaml; the matching tool's
         assumptions[] are emitted.
      2. Measurement-level: assumptions[] attached directly to a
         MeasurementValue (or HeadlineFinding).
      3. Run-level: EvaluationRun.assumptions[] (typically the agentic-
         framework's reporting / interpretation / aggregation conventions).

    Duplicate assumption ids are dropped on the second-and-later occurrence
    so the QDS doesn't repeat a tool-level assumption per measurement.
    """
    _validate_assumption_supersessions(eval_runs)
    out: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    superseded_ids = {
        assumption_id
        for run in eval_runs
        for assumption_id in (run.get("superseded_assumption_refs") or [])
    }

    def keep(assumption: dict[str, Any]) -> bool:
        return assumption.get("id") not in superseded_ids

    # Load tool_assumptions.yaml once and index by tool_ref.
    tool_assumptions_by_tool: dict[str, list[dict[str, Any]]] = {}
    if registry_rows is not None:
        active_assumptions = _active_registry_rows(
            registry_rows,
            issued_at=issued_at,
            registry_name="source tool-assumption snapshot",
            supersedes_field="supersedes_assumption_ref",
        )
    elif TOOL_ASSUMPTIONS_PATH.exists():
        ta_doc = _load_yaml_document(
            TOOL_ASSUMPTIONS_PATH, label="tool-assumption registry"
        )
        active_assumptions = _active_registry_rows(
            ta_doc.get("assumptions", []) or [],
            issued_at=issued_at,
            registry_name="tool-assumption registry",
            supersedes_field="supersedes_assumption_ref",
        )
    else:
        active_assumptions = []
    for a in active_assumptions:
        tref = a.get("tool_ref")
        if tref:
            tool_assumptions_by_tool.setdefault(tref, []).append(a)

    # 1. Tool-level (distinct oracle_tool_ref values used in the eval).
    distinct_tools: list[str] = []
    seen_tools: set[str] = set()
    for r in eval_runs:
        for m in r.get("measurements", []) or []:
            t = m.get("oracle_tool_ref")
            if t and t not in seen_tools:
                seen_tools.add(t)
                distinct_tools.append(t)
    for t in distinct_tools:
        for a in tool_assumptions_by_tool.get(t, []):
            if not keep(a):
                continue
            if a["id"] in seen_ids:
                continue
            seen_ids.add(a["id"])
            out.append(a)

    # 2. Measurement-level assumptions.
    for r in eval_runs:
        for m in r.get("measurements", []) or []:
            for a in m.get("assumptions", []) or []:
                if not keep(a):
                    continue
                if a["id"] in seen_ids:
                    continue
                seen_ids.add(a["id"])
                out.append(a)

    # 3. Run-level (agent-framework) assumptions.
    for r in eval_runs:
        for a in r.get("assumptions", []) or []:
            if not keep(a):
                continue
            if a["id"] in seen_ids:
                continue
            seen_ids.add(a["id"])
            out.append(a)

    return out


def build_tool_recommendations_applied(
    eval_runs: list[dict[str, Any]],
    issued_at: Any = None,
    registry_rows: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Snapshot of recommendations whose metric was actually measured here.

    Loaded from ref/tool_recommendations.yaml. The QDS embeds them inline
    so the published artifact is self-contained — recommendations evolve
    over time, this freezes the ones active at QDS issue time.
    """
    if registry_rows is None:
        if not TOOL_RECS_PATH.exists():
            return []
        doc = _load_yaml_document(
            TOOL_RECS_PATH, label="tool-recommendation registry"
        )
        registry_rows = doc.get("tool_recommendations", []) or []
    recs = _active_registry_rows(
        registry_rows,
        issued_at=issued_at,
        registry_name="tool-recommendation registry",
        supersedes_field="supersedes_recommendation_ref",
    )
    measured_ids: set[str] = set()
    for r in eval_runs:
        for m in r.get("measurements", []) or []:
            mid = m.get("metric_definition_ref")
            if mid:
                measured_ids.add(mid)
    return [
        rec
        for rec in recs
        if rec.get("metric_definition_ref") in measured_ids
    ]


# ---------------------------------------------------------------------------
# Fail-hard implied-content check
# ---------------------------------------------------------------------------


class QdsCompletenessError(SystemExit):
    pass


# A measurement carrying this scope implies the named rows list is populated
# on the named QDS block: (scope, QDS block, rows key, row class name).
SCOPE_IMPLIED_ROWS: tuple[tuple[str, str, str, str], ...] = (
    ("domain", "classification_summary", "domain_assignments", "DomainAssignment"),
    ("interface", "interface_quality_summary", "interface_qualities", "InterfaceQuality"),
)

# Row lists declared on an EvaluationRun that imply a QDS block:
# (eval keys, QDS block, label used in the error message).
EVAL_ROWS_IMPLIED_BLOCKS: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (
        ("secondary_structure_assignments", "domain_assignments"),
        "classification_summary",
        "classification rows",
    ),
    (("interface_qualities",), "interface_quality_summary", "interface_qualities"),
    (
        ("prediction_ensemble_qualities",),
        "prediction_ensemble_summary",
        "prediction_ensemble_qualities",
    ),
    (("nmr_ensemble_qualities",), "nmr_validation_summary", "nmr_ensemble_qualities"),
)


def _rows_present(qds: dict[str, Any], block: str, rows_key: str) -> bool:
    return bool((qds.get(block) or {}).get(rows_key))


def _check_implied_blocks(qds: dict[str, Any], eval_runs: list[dict[str, Any]]) -> None:
    """Reject QDS that hide content the source eval implies must be present."""
    errors: list[str] = []

    for r in eval_runs:
        published_measurements = [
            m
            for m in (r.get("measurements") or [])
            if m.get("stage") in ("final", "all")
        ]
        # scope=site implies SiteQuality.
        site_scope_ms = [m for m in published_measurements if m.get("scope") == "site"]
        if site_scope_ms and not qds.get("site_qualities"):
            errors.append(
                f"eval {r['id']}: {len(site_scope_ms)} measurement(s) have scope=site "
                f"but the QDS has no site_qualities. Declare Sites on the eval or "
                f"correct the scope."
            )
        # scope=ligand implies LigandQuality nested inside a SiteQuality.
        ligand_scope_ms = [m for m in published_measurements if m.get("scope") == "ligand"]
        ligand_qualities_present = any(
            sq.get("ligand_quality") for sq in qds.get("site_qualities", []) or []
        )
        if ligand_scope_ms and not ligand_qualities_present:
            errors.append(
                f"eval {r['id']}: {len(ligand_scope_ms)} measurement(s) have scope=ligand "
                f"but no LigandQuality is present in any SiteQuality. Declare Ligands "
                f"on the eval and bind them to a Site."
            )
        # scope=residue implies PerResidueQuality.
        residue_scope_ms = [m for m in published_measurements if m.get("scope") == "residue"]
        if residue_scope_ms and not qds.get("per_residue_quality"):
            errors.append(
                f"eval {r['id']}: {len(residue_scope_ms)} measurement(s) have scope=residue "
                f"but the QDS has no per_residue_quality."
            )
        # A scope implies the matching rows list on the matching QDS block.
        for scope, block, rows_key, row_class in SCOPE_IMPLIED_ROWS:
            scoped_ms = [m for m in published_measurements if m.get("scope") == scope]
            if scoped_ms and not _rows_present(qds, block, rows_key):
                errors.append(
                    f"eval {r['id']}: {len(scoped_ms)} measurement(s) have scope={scope} "
                    f"but {block}.{rows_key} is absent. Declare "
                    f"{row_class} rows or correct the scope."
                )
        # scope=ensemble implies an NMR or prediction ensemble row.
        ensemble_scope_ms = [
            m for m in published_measurements if m.get("scope") == "ensemble"
        ]
        prediction_ensemble_ms = [
            m for m in ensemble_scope_ms if m.get("catalog_task_ref") == "T07"
        ]
        nmr_ensemble_ms = [
            m for m in ensemble_scope_ms if m.get("catalog_task_ref") == "T17"
        ]
        other_ensemble_ms = [
            m for m in ensemble_scope_ms if m.get("catalog_task_ref") not in ("T07", "T17")
        ]
        prediction_rows_present = _rows_present(
            qds, "prediction_ensemble_summary", "prediction_ensemble_qualities"
        )
        nmr_rows_present = _rows_present(
            qds, "nmr_validation_summary", "nmr_ensemble_qualities"
        )
        if prediction_ensemble_ms and not prediction_rows_present:
            errors.append(
                f"eval {r['id']}: {len(prediction_ensemble_ms)} T07 measurement(s) have "
                f"scope=ensemble but prediction_ensemble_qualities is absent."
            )
        if nmr_ensemble_ms and not nmr_rows_present:
            errors.append(
                f"eval {r['id']}: {len(nmr_ensemble_ms)} T17 measurement(s) have "
                f"scope=ensemble but nmr_ensemble_qualities is absent."
            )
        if other_ensemble_ms and not (prediction_rows_present or nmr_rows_present):
            errors.append(
                f"eval {r['id']}: {len(other_ensemble_ms)} measurement(s) have "
                f"scope=ensemble but no ensemble quality row is present."
            )
        # Residue-level lists on the eval imply PerResidueQuality.
        residue_content_present = any([
            r.get("residue_outliers"),
            r.get("density_peaks"),
            r.get("flagged_regions"),
            r.get("per_residue_values"),
        ])
        if residue_content_present and not qds.get("per_residue_quality"):
            errors.append(
                f"eval {r['id']}: residue-level lists present (residue_outliers / "
                f"density_peaks / flagged_regions / per_residue_values) but the QDS "
                f"has no per_residue_quality. Emitter is silently dropping content."
            )
        # pairwise_comparisons on eval imply pairwise_comparisons on QDS.
        if r.get("pairwise_comparisons") and not qds.get("pairwise_comparisons"):
            errors.append(
                f"eval {r['id']}: pairwise_comparisons declared but absent from QDS."
            )
        # sites on eval but no site_qualities.
        if r.get("sites") and not qds.get("site_qualities"):
            errors.append(
                f"eval {r['id']}: sites declared ({[s['id'] for s in r['sites']]}) "
                f"but the QDS has no site_qualities."
            )
        # Row lists on the eval imply the QDS block that carries them.
        for eval_keys, block, label in EVAL_ROWS_IMPLIED_BLOCKS:
            if any(r.get(k) for k in eval_keys) and not qds.get(block):
                errors.append(
                    f"eval {r['id']}: {label} declared but absent from QDS."
                )

    if errors:
        msg = "QDS completeness check failed:\n  - " + "\n  - ".join(errors)
        raise QdsCompletenessError(msg)


def _check_trust_invariant(qds: dict[str, Any], waivers: list[dict[str, Any]]) -> None:
    """No gradeable applied task rests on cctbx-only or unclassifiable
    evidence without a named waiver (#315).

    The 2026-08-12 Codex review's top finding: the trust model's central rule
    was representable as unmet metadata — a schema-valid QDS could carry
    "open — cctbx only" and still publish. The DIRECTION matters: non-cctbx-
    only coverage violates nothing (there is no PHENIX self-grading to
    distrust), so only cctbx-only and unknown-family rows are gated. A waiver
    annotates the row it excuses so the QDS reads honestly.
    """
    coverage_rows = qds.get("cross_tool_coverage", {}).get("task_coverage", [])
    gated_rows = [
        row
        for row in coverage_rows
        if str(row.get("gap_status", "")).startswith(
            ("open — cctbx only", "unknown")
        )
    ]
    qualifiers = (
        "metric_definition_ref",
        "subject_ref",
        "reference_subject_ref",
        "stage",
        "scope",
        "scope_selector",
    )
    matching_waivers: dict[str, list[dict[str, Any]]] = {
        str(row.get("id")): [] for row in gated_rows
    }
    errors: list[str] = []
    for waiver in waivers:
        task_rows = [
            row
            for row in gated_rows
            if row.get("catalog_task_ref") == waiver.get("catalog_task_ref")
        ]
        specified = [field for field in qualifiers if waiver.get(field) not in (None, "")]
        matches = [
            row
            for row in task_rows
            if all(row.get(field) == waiver.get(field) for field in specified)
        ]
        if not specified and len(task_rows) > 1:
            errors.append(
                f"waiver {waiver.get('id')!r} is task-only but task "
                f"{waiver.get('catalog_task_ref')} has {len(task_rows)} gated claims; "
                "add metric/context qualifiers"
            )
            continue
        if specified and len(matches) > 1:
            errors.append(
                f"waiver {waiver.get('id')!r} ambiguously matches {len(matches)} "
                "gated claims; add enough metric/context qualifiers"
            )
            continue
        if len(matches) == 1:
            matching_waivers[str(matches[0].get("id"))].append(waiver)

    for row in gated_rows:
        gap = row.get("gap_status", "")
        task = row.get("catalog_task_ref")
        row_waivers = matching_waivers[str(row.get("id"))]
        if not row_waivers:
            errors.append(
                f"task {task}, metric {row.get('metric_definition_ref')}, context "
                f"{row.get('scope_selector')!r}: {gap!r} with no unambiguous "
                "cross_tool_waiver — add a "
                f"non-cctbx oracle or declare a waiver naming what is "
                f"missing (#315)")
        elif len(row_waivers) > 1:
            errors.append(
                f"task {task}, metric {row.get('metric_definition_ref')}: multiple "
                f"waivers match ({', '.join(str(w.get('id')) for w in row_waivers)})"
            )
        else:
            waiver = row_waivers[0]
            row["gap_status"] = (f"{gap} — WAIVED {waiver.get('as_of_date')}: "
                                 f"{waiver.get('reason')}")
    if errors:
        raise QdsCompletenessError(
            "QDS trust-invariant check failed:\n  - " + "\n  - ".join(errors))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _write_immutable_output(path: Path, content: str) -> bool:
    """Create a QDS once; permit byte-identical reruns, reject mutation.

    Returns True when a new file was written and False for an identical no-op.
    """
    encoded = content.encode("utf-8")
    if path.exists():
        if path.read_bytes() == encoded:
            return False
        raise QdsCompletenessError(
            f"QDS output {path} already exists with different content; "
            "quality data sheets are immutable, so choose a new id/output path"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return True


def _validate_cli_emission_contract(
    *, qds_id: str, coverage_scope: str | None, scope_notes: str | None,
    output: Path | None, issued_at: str | None,
) -> None:
    """Require enough pinned scope/time metadata for a file artifact."""
    errors: list[str] = []
    if not qds_id.startswith("QDS_"):
        errors.append("--qds-id must begin with 'QDS_'")
    if coverage_scope is None:
        errors.append("--coverage-scope is required for QDS emission")
    if coverage_scope == "partial" and not str(scope_notes or "").strip():
        errors.append("--coverage-scope partial requires non-empty --scope-notes")
    if output is not None and not issued_at:
        errors.append("--issued-at is required when --output is used")
    if output is not None and output.name != f"{qds_id}.yaml":
        errors.append(
            f"--output filename must be exactly {qds_id}.yaml so repository "
            "QDS discovery cannot miss the artifact"
        )
    if errors:
        raise QdsCompletenessError(
            "QDS emission contract failed:\n  - " + "\n  - ".join(errors)
        )


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
    # Contract-1 routing is code-owned. Ordinary emission still checks it
    # against the live catalog; immutable replay uses source-pinned Tool rows
    # below and must not acquire new dependencies on later catalog edits.
    if not require_pinned_tool_snapshot:
        _validate_routing_table()
    if not qds_id.startswith("QDS_"):
        raise QdsCompletenessError(
            "QDS emission contract failed: qds_id must begin with 'QDS_'"
        )
    if coverage_scope not in {"cumulative", "partial"}:
        raise QdsCompletenessError(
            "QDS emission contract failed: coverage_scope is required and must be "
            "'cumulative' or 'partial'"
        )
    if coverage_scope == "partial" and not str(scope_notes or "").strip():
        raise QdsCompletenessError(
            "QDS emission contract failed: coverage_scope=partial requires "
            "non-empty scope_notes"
        )

    source_runs: list[dict[str, Any]] = []
    source_structures: list[dict[str, Any]] = []
    source_tools: list[dict[str, Any]] = []
    source_recommendations: list[dict[str, Any]] = []
    source_assumptions: list[dict[str, Any]] = []
    has_recommendation_snapshot = True
    has_assumption_snapshot = True
    for path in eval_paths:
        doc = _load_yaml_document(path, label=f"EvaluationRun source {path}")
        source_structures.extend(doc.get("structures", []) or [])
        source_tools.extend(doc.get("tools", []) or [])
        has_recommendation_snapshot &= "tool_recommendations" in doc
        has_assumption_snapshot &= "assumptions" in doc
        source_recommendations.extend(doc.get("tool_recommendations", []) or [])
        source_assumptions.extend(doc.get("assumptions", []) or [])
        for r in doc.get("evaluation_runs", []):
            source_runs.append(r)

    def merge_source_rows(
        rows: list[dict[str, Any]], *, label: str
    ) -> list[dict[str, Any]]:
        """De-duplicate identical per-document snapshots, reject conflicts."""
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
                merged.append(row)
            elif prior != canonical:
                errors.append(f"{label} has conflicting duplicate id {row_id!r}")
        if errors:
            raise QdsCompletenessError(
                "QDS source-snapshot integrity failed:\n  - "
                + "\n  - ".join(errors)
            )
        return merged

    source_structures = merge_source_rows(
        source_structures, label="source Structure snapshot"
    )
    source_tools = merge_source_rows(source_tools, label="source Tool snapshot")
    source_recommendations = merge_source_rows(
        source_recommendations, label="source tool-recommendation snapshot"
    )
    source_assumptions = merge_source_rows(
        source_assumptions, label="source tool-assumption snapshot"
    )
    run_ids: set[str] = set()
    source_errors: list[str] = []
    for index, run in enumerate(source_runs, start=1):
        run_id = str(run.get("id") or "").strip()
        if not run_id:
            source_errors.append(f"input evaluation run {index} has no id")
        elif run_id in run_ids:
            source_errors.append(f"duplicate input EvaluationRun id {run_id!r}")
        else:
            run_ids.add(run_id)
        run_structure = run.get("structure_ref")
        if run_structure != structure_id:
            source_errors.append(
                f"EvaluationRun {run_id or index!r} has structure_ref "
                f"{run_structure!r}, not requested structure_id {structure_id!r}"
            )
    if not source_runs:
        source_errors.append("input files contain no evaluation_runs")
    if source_errors:
        raise QdsCompletenessError(
            "QDS source-run integrity failed:\n  - " + "\n  - ".join(source_errors)
        )

    if require_pinned_tool_snapshot and not source_tools:
        raise QdsCompletenessError(
            "QDS contract-1 replay requires top-level Tool rows in the source "
            "EvaluationRun document; refusing the mutable live catalog"
        )
    if require_pinned_tool_snapshot and not has_recommendation_snapshot:
        raise QdsCompletenessError(
            "QDS contract-1 replay requires top-level tool_recommendations in "
            "every source EvaluationRun document; use [] for an empty snapshot"
        )
    if require_pinned_tool_snapshot and not has_assumption_snapshot:
        raise QdsCompletenessError(
            "QDS contract-1 replay requires top-level assumptions in every source "
            "EvaluationRun document; use [] for an empty snapshot"
        )
    if source_tools:
        tool_families = _tool_families_from_rows(
            source_tools, source_name="source Tool snapshot"
        )
        if not require_pinned_tool_snapshot:
            live_families = _load_catalog_tool_families()
            drift = [
                f"{tool_id!r}: source={family!r}, catalog={live_families.get(tool_id)!r}"
                for tool_id, family in tool_families.items()
                if live_families.get(tool_id) != family
            ]
            if drift:
                raise QdsCompletenessError(
                    "QDS source Tool snapshot disagrees with the live catalog:\n  - "
                    + "\n  - ".join(drift)
                )
    else:
        tool_families = _load_catalog_tool_families()

    (
        effective_structure_method,
        effective_resolution_a,
        effective_space_group,
        effective_structure_description,
    ) = _resolve_structure_identity_metadata(
        source_structures,
        structure_id,
        structure_method=structure_method,
        resolution_a=resolution_a,
        space_group=space_group,
        structure_description=structure_description,
    )

    for run in source_runs:
        run_id = str(run.get("id") or "<missing id>")
        run["measurements"] = _canonicalize_measurement_tools(
            run.get("measurements", []) or [],
            context=f"EvaluationRun {run_id}",
            tool_families=tool_families,
        )
    source_runs.sort(
        key=lambda run: (str(run.get("run_date") or ""), str(run.get("id") or ""))
    )

    explicit_subjects = _explicit_subjects(source_runs)
    effective_subject = subject_ref
    if effective_subject is None and len(explicit_subjects) == 1:
        effective_subject = next(iter(explicit_subjects))
    elif effective_subject is None and len(explicit_subjects) > 1:
        raise QdsCompletenessError(
            "QDS inputs contain multiple explicit measurement or structured-row subjects "
            f"({', '.join(sorted(explicit_subjects))}); pass --subject-ref."
        )
    elif (
        effective_subject is not None
        and explicit_subjects
        and effective_subject not in explicit_subjects
    ):
        raise QdsCompletenessError(
            f"QDS subject {effective_subject!r} has no exact evidence in the inputs; "
            "explicit evidence exists only for "
            f"{', '.join(sorted(explicit_subjects))}. Refusing legacy fallback."
        )

    # Every downstream builder consumes this one copied, annotated view.  This
    # prevents a wrong-subject run from re-entering through structured rows,
    # waivers, recommendations, assumptions, or headline prose after scalar
    # routing has correctly filtered it.
    runs = _annotated_runs(source_runs, effective_subject)
    if not runs:
        raise QdsCompletenessError(
            f"QDS subject {effective_subject!r} left no applicable evaluation runs"
        )
    _validate_t16_interface_contexts(runs)

    qds_measurements = [m for r in runs for m in _final_or_all_measurements(r)]
    final_only = [m for m in qds_measurements if m.get("stage") == "final"]
    all_only = [m for m in qds_measurements if m.get("stage") == "all"]

    # Route every measurement once via METRIC_TO_QDS_SLOT.
    routed_final = _route_measurements(final_only, effective_subject)
    routed_all = _route_measurements(all_only, effective_subject)
    routed_qds = _route_measurements(qds_measurements, effective_subject)

    effective_issued_at = issued_at or dt.datetime.now(dt.timezone.utc).replace(
        microsecond=0
    ).isoformat()
    qds: dict[str, Any] = {
        "id": qds_id,
        "structure_ref": structure_id,
        "derived_from_evaluation_run_refs": [r["id"] for r in runs],
        "issued_at": effective_issued_at,
        "emitter_contract_version": "2",
        "identity_block": build_identity_block(
            qds_id,
            structure_id,
            effective_structure_method,
            effective_resolution_a,
            effective_space_group,
            effective_structure_description,
        ),
    }
    if effective_subject is not None:
        qds["subject_ref"] = effective_subject
    qds["coverage_scope"] = coverage_scope
    if scope_notes is not None:
        qds["scope_notes"] = scope_notes

    # Routed blocks — final-stage measurements.
    geom = _build_block_from_routed(qds_id, "geometry", routed_final.get("geometry_summary"))
    if geom:
        qds["geometry_summary"] = geom
    refn = _build_block_from_routed(qds_id, "refinement", routed_final.get("refinement_summary"))
    if refn:
        qds["refinement_summary"] = refn
    mp = _build_block_from_routed(qds_id, "map", routed_final.get("map_summary"))
    if mp:
        qds["map_summary"] = mp

    packing = _build_block_from_routed(qds_id, "packing", routed_qds.get("packing_summary"))
    if packing:
        qds["packing_summary"] = packing

    for block_name, id_suffix, row_keys in ROW_BEARING_SUMMARY_BLOCKS:
        block = build_row_bearing_summary(
            qds_id,
            id_suffix,
            routed_qds.get(block_name),
            runs,
            row_keys,
            effective_subject,
        )
        if block:
            qds[block_name] = block

    # Data-quality summary — dataset-wide measurements (stage=all).
    dq = _build_block_from_routed(qds_id, "data_quality", routed_all.get("data_quality_summary"))
    if dq:
        qds["data_quality_summary"] = dq

    # Pairwise comparisons.
    pcs = build_pairwise_comparisons(runs)
    if pcs:
        qds["pairwise_comparisons"] = pcs

    # Per-residue quality.
    prq = build_per_residue_quality(qds_id, runs)
    if prq:
        qds["per_residue_quality"] = prq

    # Site qualities.
    sqs = build_site_qualities(qds_id, runs, effective_subject)
    if sqs:
        qds["site_qualities"] = sqs

    # Predicted-confidence summary.
    pcs_block = build_predicted_confidence_summary(
        qds_id, runs, effective_structure_method, effective_subject
    )
    if pcs_block:
        qds["predicted_confidence_summary"] = pcs_block

    # Cross-tool coverage uses every measurement that informed the QDS.
    qds["cross_tool_coverage"] = build_cross_tool_coverage(
        qds_id,
        qds_measurements,
        effective_subject,
        tool_families=tool_families,
    )

    # Waivers travel from the evals to the QDS verbatim (#315), and the trust
    # invariant is enforced against the coverage just built: a cctbx-only or
    # unclassifiable task with no waiver is a hard error, not a labeled gap.
    waivers = []
    seen_waiver_ids = set()
    measured_tasks = {
        measurement.get("catalog_task_ref") for measurement in qds_measurements
    }
    for r in runs:
        for w in r.get("cross_tool_waivers", []) or []:
            if w.get("catalog_task_ref") not in measured_tasks:
                continue
            if w.get("id") not in seen_waiver_ids:
                seen_waiver_ids.add(w.get("id"))
                waivers.append(w)
    if waivers:
        qds["cross_tool_waivers"] = waivers
    _check_trust_invariant(qds, waivers)

    # Snapshot of recommendations active at issue time.
    recs = build_tool_recommendations_applied(
        runs,
        effective_issued_at,
        source_recommendations if require_pinned_tool_snapshot else None,
    )
    if recs:
        qds["tool_recommendations_applied"] = recs

    # Aggregated tool / measurement / framework assumptions.
    assumptions = build_assumptions_report(
        runs,
        effective_issued_at,
        source_assumptions if require_pinned_tool_snapshot else None,
    )
    if assumptions:
        qds["assumptions_report"] = assumptions

    # Headline verdict — stitch together any per-run verdicts.
    headline_lines = [r["headline_verdict"] for r in runs if r.get("headline_verdict")]
    if headline_lines:
        qds["headline_verdict"] = "\n\n".join(headline_lines)

    # Fail-hard implied-content check.
    _check_implied_blocks(qds, runs)

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
    """Dispatch emission through a retained, explicit contract implementation.

    Contract versions are append-only. A future output-affecting change adds a
    new implementation and dispatch branch; it must not repurpose contract 1.
    Committed-sheet validation uses a retained contract module plus source-owned
    registry snapshots and canonical byte pin rather than asking the latest
    emitter or live registries to reinterpret an earlier contract.
    """
    if emitter_contract_version == "1":
        # Keep the retained implementation byte-stable while applying today's
        # input-integrity boundary before its historical loader sees the source.
        # Contract 1 must not silently accept duplicate YAML mapping keys.
        for path in eval_paths:
            _load_yaml_document(path, label=f"EvaluationRun source {path}")
        if not require_pinned_tool_snapshot:
            _load_yaml_document(
                qds_emit_contract_v1.CATALOG_PATH,
                label="contract-1 catalog",
            )
            for registry_path, registry_label in (
                (
                    qds_emit_contract_v1.TOOL_RECS_PATH,
                    "contract-1 tool-recommendation registry",
                ),
                (
                    qds_emit_contract_v1.TOOL_ASSUMPTIONS_PATH,
                    "contract-1 tool-assumption registry",
                ),
            ):
                if registry_path.exists():
                    _load_yaml_document(registry_path, label=registry_label)
        return qds_emit_contract_v1._emit_qds_contract_1(
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
    if emitter_contract_version == "2":
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
    if emitter_contract_version == "3":
        # Contract 3 retains contract 2's scientific projection and adds a
        # source-owned sheet context. Keep duplicate-key rejection at the live
        # boundary before the frozen adapter reads any source or registry.
        for path in eval_paths:
            _load_yaml_document(path, label=f"EvaluationRun source {path}")
        if not require_pinned_tool_snapshot:
            _load_yaml_document(CATALOG_PATH, label="contract-3 catalog")
            for registry_path, registry_label in (
                (TOOL_RECS_PATH, "contract-3 tool-recommendation registry"),
                (TOOL_ASSUMPTIONS_PATH, "contract-3 tool-assumption registry"),
            ):
                if registry_path.exists():
                    _load_yaml_document(registry_path, label=registry_label)
        try:
            return qds_emit_contract_v3._emit_qds_contract_3(
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
        except qds_emit_contract_v3.QdsCompletenessError as exc:
            raise QdsCompletenessError(str(exc)) from None
    if emitter_contract_version == "4":
        try:
            return qds_emit_contract_v4.emit_qds(
                eval_paths, qds_id, structure_id, structure_method, subject_ref,
                coverage_scope, scope_notes, resolution_a, space_group, issued_at,
                structure_description, emitter_contract_version="4",
                require_pinned_tool_snapshot=require_pinned_tool_snapshot,
            )
        except qds_emit_contract_v4.QdsCompletenessError as exc:
            raise QdsCompletenessError(str(exc)) from None
    supported = ", ".join(sorted(SUPPORTED_QDS_EMITTER_CONTRACT_VERSIONS))
    raise QdsCompletenessError(
        "unsupported QDS emitter contract version "
        f"{emitter_contract_version!r}; supported: {supported}"
    )


def main() -> int:
    p = argparse.ArgumentParser(description="EvaluationRun → QualityDataSheet emitter.")
    p.add_argument("eval_yaml", type=Path, nargs="+", help="One or more EvaluationRun YAML files.")
    p.add_argument("--qds-id", required=True)
    p.add_argument("--structure-id", required=True)
    p.add_argument(
        "--structure-method",
        choices=["xray", "cryo_em", "predicted_model", "nmr"],
        default=None,
        help="Set the structure's method to enable modality-specific block emission.",
    )
    p.add_argument(
        "--subject-ref",
        default=None,
        help="Concrete model/artefact to prefer; explicit non-matching rows are excluded.",
    )
    p.add_argument(
        "--coverage-scope",
        choices=["cumulative", "partial"],
        default=None,
        help="Declare whether the emitted sheet is cumulative or a bounded partial update.",
    )
    p.add_argument("--scope-notes", default=None, help="Coverage boundary or carry-forward note.")
    p.add_argument("--resolution-a", type=float, default=None)
    p.add_argument("--space-group", default=None)
    p.add_argument("--structure-description", default=None)
    p.add_argument(
        "--issued-at",
        default=None,
        help="Pinned ISO-8601 issue timestamp for reproducible immutable output.",
    )
    p.add_argument("-o", "--output", type=Path)
    args = p.parse_args()

    _validate_cli_emission_contract(
        qds_id=args.qds_id,
        coverage_scope=args.coverage_scope,
        scope_notes=args.scope_notes,
        output=args.output,
        issued_at=args.issued_at,
    )

    qds = emit_qds(
        args.eval_yaml,
        args.qds_id,
        args.structure_id,
        args.structure_method,
        args.subject_ref,
        args.coverage_scope,
        args.scope_notes,
        args.resolution_a,
        args.space_group,
        args.issued_at,
        args.structure_description,
    )
    container = {"quality_data_sheets": [qds]}
    out_text = yaml_dump(container)
    if args.output:
        if _write_immutable_output(args.output, out_text):
            sys.stderr.write(f"wrote {args.output}\n")
        else:
            sys.stderr.write(f"unchanged {args.output}\n")
    else:
        sys.stdout.write(out_text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
