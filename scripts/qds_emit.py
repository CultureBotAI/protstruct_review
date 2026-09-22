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
independent family, numeric value, source date, and stable ids are considered
in that order. Coupled R-work/R-free/gap values remain on one code path.

After building, a fail-hard consistency pass rejects QDS that would hide
load-bearing local content: a scope=site measurement implies a
SiteQuality block, a residue_outliers/density_peaks/per_residue_values
list on the eval implies a PerResidueQuality block, etc.

Usage:
    python scripts/qds_emit.py \\
        data/examples/eval/EVAL_1sar_cdba2c07_2026-04-24.yaml \\
        --qds-id QDS_1sar_cdba2c07_2026-04-26 \\
        --structure-id 1sar \\
        -o data/examples/qds/QDS_1sar_cdba2c07_2026-04-26.yaml
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import re
import statistics
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml


REPO = Path(__file__).resolve().parent.parent
CATALOG_PATH = REPO / "ref" / "catalog.yaml"
TOOL_RECS_PATH = REPO / "ref" / "tool_recommendations.yaml"
TOOL_ASSUMPTIONS_PATH = REPO / "ref" / "tool_assumptions.yaml"


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


def _load_catalog_metric_ids() -> set[str]:
    doc = yaml.safe_load(CATALOG_PATH.read_text())
    return {m["id"] for m in doc.get("metric_definitions", [])}


def _validate_routing_table() -> None:
    """Every key in METRIC_TO_QDS_SLOT must exist in ref/catalog.yaml."""
    catalog_ids = _load_catalog_metric_ids()
    bad = [mid for mid in METRIC_TO_QDS_SLOT if mid not in catalog_ids]
    if bad:
        raise SystemExit(
            "qds_emit: QDS routing references metric ids not in ref/catalog.yaml:\n  "
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
    "secondary_structure_assignments",
    "domain_assignments",
    "interface_qualities",
    "prediction_ensemble_qualities",
    "nmr_ensemble_qualities",
)


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


def _candidate_priority(m: dict[str, Any], subject_ref: str | None) -> tuple[Any, ...]:
    """Only policy-backed preferences; scientific context is not a tie-breaker."""
    explicit_subject = m.get("subject_ref")
    subject_score = 0 if subject_ref is not None and explicit_subject == subject_ref else 1
    fam_score = {"non_cctbx": 0, "cctbx": 1}.get(m.get("oracle_family"), 2)
    oracle = m.get("oracle_measure") or {}
    type_score = 0 if oracle.get("value_numeric") is not None else 1
    run_date = str(m.get("_source_run_date") or "").replace("-", "")
    recency_score = -int(run_date) if run_date.isdigit() else 0
    return (subject_score, fam_score, type_score, recency_score)


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
        "oracle_measure",
        "pass_status",
        "pass_criterion",
        "provenance_ref",
        "evidence_refs",
        "_source_evaluation_run_ref",
    )
    return yaml.safe_dump(
        {key: m.get(key) for key in semantic_fields if m.get(key) not in (None, "")},
        sort_keys=True,
        allow_unicode=True,
    )


def _strongest(
    measurements: list[dict[str, Any]], subject_ref: str | None = None
) -> dict[str, Any] | None:
    """Pick deterministically by subject, family, value type, date, then id."""
    eligible = _eligible_for_subject(measurements, subject_ref)
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


def _wrap_value(m: dict[str, Any] | None) -> dict[str, Any] | None:
    if m is None:
        return None
    v = dict(m.get("oracle_measure") or {})
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
        winner = _strongest(candidates, subject_ref)
        if winner is None:
            continue
        out.setdefault(block, {})[slot] = winner

    _enforce_coherent_refinement_bundle(out, by_slot, subject_ref)
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


COVERAGE_CONTEXT_FIELDS = (
    "catalog_task_ref",
    "metric_definition_ref",
    "stage",
    "scope",
    "scope_selector",
    "reference_subject_ref",
)


def _coverage_context_key(measurement: dict[str, Any]) -> tuple[str, ...]:
    """Claim context excluding subject, which is resolved within each group."""
    return tuple(_context_token(measurement.get(field)) for field in COVERAGE_CONTEXT_FIELDS)


def _has_numeric_oracle_value(measurement: dict[str, Any]) -> bool:
    value = (measurement.get("oracle_measure") or {}).get("value_numeric")
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _coverage_id(qds_id: str, context: tuple[str, ...]) -> str:
    task = re.sub(r"[^A-Za-z0-9]+", "_", context[0]).strip("_") or "task"
    metric = re.sub(r"[^A-Za-z0-9]+", "_", context[1]).strip("_") or "metric"
    digest = hashlib.sha256("\x1f".join(context).encode()).hexdigest()[:12]
    return f"{qds_id}_coverage_{task}_{metric}_{digest}"


def build_cross_tool_coverage(
    qds_id: str,
    measurements: list[dict[str, Any]],
    subject_ref: str | None = None,
) -> dict[str, Any]:
    """Report independent-family coverage per metric and comparison context.

    A task-level union is scientifically unsafe: a non-cctbx oracle for one
    metric cannot validate a cctbx-only claim about another.  Text-only attempts
    (including an aborted tool invocation) are retained as informational context
    but never close quantitative coverage.
    """
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for measurement in measurements:
        if not measurement.get("catalog_task_ref"):
            continue
        grouped.setdefault(_coverage_context_key(measurement), []).append(measurement)

    rows: list[dict[str, Any]] = []
    for context in sorted(grouped):
        candidates = _eligible_for_subject(grouped[context], subject_ref)
        exact = [row for row in candidates if row.get("subject_ref") == subject_ref]
        if subject_ref is not None and exact:
            candidates = exact

        numeric = [row for row in candidates if _has_numeric_oracle_value(row)]
        text_only = [row for row in candidates if not _has_numeric_oracle_value(row)]
        buckets: dict[str, set[str]] = {
            "cctbx": set(),
            "non_cctbx": set(),
            "unclassified": set(),
        }
        for measurement in numeric:
            family = measurement.get("oracle_family") or ""
            tool = str(measurement.get("oracle_tool_ref") or "<unnamed oracle>")
            if family in ("cctbx", "non_cctbx"):
                buckets[family].add(tool)
            else:
                buckets["unclassified"].add(tool)

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
            gap = "closed" if cctbx else "non-cctbx only"
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


def build_assumptions_report(eval_runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
    if TOOL_ASSUMPTIONS_PATH.exists():
        ta_doc = yaml.safe_load(TOOL_ASSUMPTIONS_PATH.read_text()) or {}
        for a in ta_doc.get("assumptions", []) or []:
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


def build_tool_recommendations_applied(eval_runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Snapshot of recommendations whose metric was actually measured here.

    Loaded from ref/tool_recommendations.yaml. The QDS embeds them inline
    so the published artifact is self-contained — recommendations evolve
    over time, this freezes the ones active at QDS issue time.
    """
    if not TOOL_RECS_PATH.exists():
        return []
    doc = yaml.safe_load(TOOL_RECS_PATH.read_text()) or {}
    recs = doc.get("tool_recommendations", []) or []
    measured_ids: set[str] = set()
    for r in eval_runs:
        for m in r.get("measurements", []) or []:
            mid = m.get("metric_definition_ref")
            if mid:
                measured_ids.add(mid)
    return [rec for rec in recs if rec.get("metric_definition_ref") in measured_ids]


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
    *, coverage_scope: str | None, scope_notes: str | None,
    output: Path | None, issued_at: str | None,
) -> None:
    """Require enough pinned scope/time metadata for a file artifact."""
    errors: list[str] = []
    if coverage_scope is None:
        errors.append("--coverage-scope is required for QDS emission")
    if coverage_scope == "partial" and not str(scope_notes or "").strip():
        errors.append("--coverage-scope partial requires non-empty --scope-notes")
    if output is not None and not issued_at:
        errors.append("--issued-at is required when --output is used")
    if errors:
        raise QdsCompletenessError(
            "QDS emission contract failed:\n  - " + "\n  - ".join(errors)
        )


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
) -> dict[str, Any]:
    _validate_routing_table()
    if coverage_scope == "partial" and not str(scope_notes or "").strip():
        raise QdsCompletenessError(
            "QDS emission contract failed: coverage_scope=partial requires "
            "non-empty scope_notes"
        )

    source_runs: list[dict[str, Any]] = []
    for path in eval_paths:
        doc = yaml.safe_load(path.read_text())
        for r in doc.get("evaluation_runs", []):
            source_runs.append(r)
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

    qds_measurements = [m for r in runs for m in _final_or_all_measurements(r)]
    final_only = [m for m in qds_measurements if m.get("stage") == "final"]
    all_only = [m for m in qds_measurements if m.get("stage") == "all"]

    # Route every measurement once via METRIC_TO_QDS_SLOT.
    routed_final = _route_measurements(final_only, effective_subject)
    routed_all = _route_measurements(all_only, effective_subject)
    routed_qds = _route_measurements(qds_measurements, effective_subject)

    qds: dict[str, Any] = {
        "id": qds_id,
        "structure_ref": structure_id,
        "derived_from_evaluation_run_refs": [r["id"] for r in runs],
        "issued_at": issued_at or dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat(),
        "identity_block": build_identity_block(
            qds_id, structure_id, structure_method, resolution_a, space_group,
            structure_description,
        ),
    }
    if effective_subject is not None:
        qds["subject_ref"] = effective_subject
    if coverage_scope is not None:
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
        qds_id, runs, structure_method, effective_subject
    )
    if pcs_block:
        qds["predicted_confidence_summary"] = pcs_block

    # Cross-tool coverage uses every measurement that informed the QDS.
    qds["cross_tool_coverage"] = build_cross_tool_coverage(
        qds_id, qds_measurements, effective_subject
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
    recs = build_tool_recommendations_applied(runs)
    if recs:
        qds["tool_recommendations_applied"] = recs

    # Aggregated tool / measurement / framework assumptions.
    assumptions = build_assumptions_report(runs)
    if assumptions:
        qds["assumptions_report"] = assumptions

    # Headline verdict — stitch together any per-run verdicts.
    headline_lines = [r["headline_verdict"] for r in runs if r.get("headline_verdict")]
    if headline_lines:
        qds["headline_verdict"] = "\n\n".join(headline_lines)

    # Fail-hard implied-content check.
    _check_implied_blocks(qds, runs)

    return qds


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
