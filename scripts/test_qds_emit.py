#!/usr/bin/env python3
"""Regression tests for scripts/qds_emit.py.

Closes the regression hole Codex flagged: previously the QDS emitter used
substring matching that silently dropped half the geometry slots from the
1SAR example, and had no builders for per_residue_quality, site_qualities,
pairwise_comparisons, or tool_recommendations_applied.

Three tests:

  1. 1SAR example → assert all expected geometry slots are present (the
     specific regression Codex named).
  2. Synthetic eval (data/examples/eval/EVAL_synth_active_site_*.yaml) →
     assert per_residue_quality, site_qualities (with ligand_quality),
     pairwise_comparisons, and tool_recommendations_applied all populated.
  3. Negative test: mutate the synthetic eval to drop the Site declaration
     while keeping a scope=site measurement, assert the emitter raises a
     QdsCompletenessError with a clear message.

Exits non-zero on the first failure; prints PASS for each test that passes.
Wired into scripts/validate.sh.
"""
from __future__ import annotations

import copy
import hashlib
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import qds_emit  # noqa: E402
import qds_emit_contract_v1  # noqa: E402
import qds_emit_contract_v2  # noqa: E402


EVAL_1SAR = REPO / "data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-04-24.yaml"
EVAL_SYNTH = REPO / "data/examples/eval/EVAL_synth_active_site_2026-04-26.yaml"
EVAL_QUALITY = REPO / "data/examples/eval/EVAL_synth_quality_indicators_2026-05-04.yaml"

EXPECTED_GEOMETRY_SLOTS_1SAR = {
    "clashscore",
    "ramachandran_outliers_pct",
    "ramachandran_favored_pct",
    "rotamer_outliers_pct",
    "molprobity_score",
    "bond_rmsd_a",
    "angle_rmsd_deg",
}


def _quality_doc_with_governed_bundles() -> dict:
    """Upgrade the historical synthetic fixture for current bundle invariants."""
    doc = copy.deepcopy(yaml.safe_load(EVAL_QUALITY.read_text()))
    run = doc["evaluation_runs"][0]
    for row in run.get("measurements", []):
        if (
            row.get("metric_definition_ref") in qds_emit.TEXTUAL_SUMMARY_METRIC_IDS
            and (row.get("oracle_measure") or {}).get("value_text")
        ):
            row["pass_status"] = "informational"
    agreement = next(
        row
        for row in run["measurements"]
        if row.get("metric_definition_ref") == "T15_secondary_structure_agreement"
    )
    agreement["pass_status"] = "informational"
    agreement.pop("pass_criterion", None)
    agreement["bundle_ref"] = "EVAL_synth_quality_T15_SS_BUNDLE"
    content = copy.deepcopy(agreement)
    content.update(
        {
            "id": "EVAL_synth_quality_indicators_2026-05-04_M_010a",
            "metric_definition_ref": "T15_secondary_structure_content",
            "oracle_tool_ref": "DSSP",
            "oracle_measure": {"value_numeric": 0.40, "unit": "fraction"},
            "pass_status": "informational",
            "notes": "Synthetic DSSP H+E content interpretability diagnostic.",
        }
    )
    run["measurements"].append(content)
    capri = next(
        row
        for row in run["measurements"]
        if row.get("metric_definition_ref") == "T16_capri_interface_quality_class"
    )
    capri["oracle_measure"] = {"value_text": "Medium"}
    comparison_rows = [
        row
        for row in run["measurements"]
        if row.get("metric_definition_ref")
        in {"T16_interface_dockq_score", "T16_capri_interface_quality_class"}
    ]
    for row in comparison_rows:
        row["reference_subject_ref"] = "native:synth_quality"
        row["evidence_refs"] = ["raw:synth_quality_dockq"]
    bsa = next(
        row
        for row in run["measurements"]
        if row.get("metric_definition_ref")
        == "T16_interface_buried_surface_area"
    )
    bsa["evidence_refs"] = ["raw:synth_quality_bsa"]
    for interface in run.get("interface_qualities", []) or []:
        if (interface.get("dockq_score") or {}).get("value_numeric") == 0.73:
            interface["capri_quality_class"] = {"value_text": "Medium"}
            interface["reference_subject_ref"] = "native:synth_quality"
            interface["model_to_native_chain_mapping"] = "AB:AB"
            interface["evidence_refs"] = [
                "raw:synth_quality_dockq",
                "raw:synth_quality_bsa",
            ]
    return doc


def _check(condition: bool, msg: str) -> None:
    if not condition:
        print(f"FAIL: {msg}", file=sys.stderr)
        sys.exit(1)


def assert_raises_completeness(
    fn: Callable[[], object], expected_fragments: list[str], what: str
) -> None:
    """Run `fn` and assert it fails the completeness check with context.

    QdsCompletenessError subclasses SystemExit deliberately, so callers of the
    emitter that only catch SystemExit still stop. Accept either here, and
    require every fragment in `expected_fragments` to appear in the message.
    """
    try:
        fn()
    except SystemExit as e:  # covers QdsCompletenessError
        msg = str(e)
        for fragment in expected_fragments:
            _check(
                fragment in msg,
                f"emitter failed but message lacks {fragment!r} context: {msg!r}",
            )
        return
    _check(False, f"emit_qds did not fail when {what}")


def test_1sar_geometry_slots_all_present() -> None:
    qds = _emit_legacy_1sar("QDS_1sar_test")
    _check("geometry_summary" in qds, "geometry_summary missing from 1SAR QDS")
    geom = qds["geometry_summary"]
    present = set(geom.keys()) - {"id"}
    missing = EXPECTED_GEOMETRY_SLOTS_1SAR - present
    _check(
        not missing,
        f"1SAR geometry_summary missing slots: {sorted(missing)}. "
        f"Codex regression — substring matching dropped these silently.",
    )
    ca_site = next(
        sq for sq in qds.get("site_qualities", [])
        if sq.get("site_ref") == "1sar_ca_active_site"
    )
    ca_ligand = ca_site.get("ligand_quality") or {}
    _check(
        (ca_ligand.get("rscc") or {}).get("value_numeric") == 0.9716,
        "Ca ligand RSCC was overwritten or dropped by another ligand measurement",
    )
    _check(
        "Ca²⁺ — consistent" in (ca_ligand.get("element_identity") or {}).get("value_text", ""),
        "Ca element-identity summary missing from LigandQuality",
    )
    print(f"PASS  test_1sar_geometry_slots_all_present  ({len(present)} slots populated)")


def test_synth_local_blocks_present() -> None:
    qds = qds_emit.emit_qds(
        [EVAL_SYNTH], qds_id="QDS_synth_test", structure_id="synth1",
        coverage_scope="cumulative",
    )

    _check("per_residue_quality" in qds, "synthetic QDS missing per_residue_quality")
    prq = qds["per_residue_quality"]
    _check(prq.get("outliers"), "per_residue_quality.outliers empty (eval has 2 ResidueOutliers)")
    _check(prq.get("density_peaks"), "per_residue_quality.density_peaks empty (eval has 1 peak)")
    _check(prq.get("lddt_per_residue"), "per_residue_quality.lddt_per_residue empty (eval has 5 values)")

    _check("site_qualities" in qds and qds["site_qualities"], "synthetic QDS missing site_qualities")
    sq = qds["site_qualities"][0]
    _check(sq["site_ref"] == "synth1_active_site", f"site_ref != synth1_active_site, got {sq.get('site_ref')!r}")
    _check("ligand_quality" in sq, "SiteQuality.ligand_quality missing (eval has scope=ligand measurements)")
    lq = sq["ligand_quality"]
    _check("rscc" in lq, "ligand_quality.rscc missing")
    _check("protein_ligand_hbond_count" in lq, "ligand_quality.protein_ligand_hbond_count missing")

    _check("pairwise_comparisons" in qds and qds["pairwise_comparisons"], "synthetic QDS missing pairwise_comparisons")
    pc = qds["pairwise_comparisons"][0]
    _check(pc.get("reference_kind") == "starting_model", f"pairwise reference_kind unexpected: {pc.get('reference_kind')!r}")

    _check(
        "tool_recommendations_applied" in qds and qds["tool_recommendations_applied"],
        "synthetic QDS missing tool_recommendations_applied",
    )

    print("PASS  test_synth_local_blocks_present  (per_residue + sites + ligand + pairwise + tool_recs)")


def test_negative_site_scope_without_site_decl_fails() -> None:
    """Drop the Site declaration but keep a scope=site measurement; expect failure."""
    doc = yaml.safe_load(EVAL_SYNTH.read_text())
    bad = copy.deepcopy(doc)
    # Strip Site declarations and ligands; keep the measurements.
    for r in bad["evaluation_runs"]:
        r["sites"] = []
        r["ligands"] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        bad_path = Path(tmpdir) / "eval_bad_no_sites.yaml"
        bad_path.write_text(yaml.safe_dump(bad, sort_keys=False))

        assert_raises_completeness(
            lambda: qds_emit.emit_qds(
                [bad_path], qds_id="QDS_bad_test", structure_id="synth1",
                coverage_scope="cumulative",
            ),
            ["scope=site", "declared Site"],
            "site-scope measurement had no Site declared",
        )
    print("PASS  test_negative_site_scope_without_site_decl_fails")


def _emit_mutated_synth(mutator: Callable[[dict], None], name: str) -> None:
    """Write one mutated synthetic eval and attempt to emit it."""
    doc = copy.deepcopy(yaml.safe_load(EVAL_SYNTH.read_text()))
    mutator(doc["evaluation_runs"][0])
    with tempfile.TemporaryDirectory() as tmpdir:
        bad_path = Path(tmpdir) / f"{name}.yaml"
        bad_path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
        qds_emit.emit_qds(
            [bad_path], qds_id=f"QDS_{name}", structure_id="synth1",
            coverage_scope="cumulative",
        )


def test_negative_unknown_site_selector_fails() -> None:
    def mutate(run: dict) -> None:
        site_measurement = next(m for m in run["measurements"] if m.get("scope") == "site")
        site_measurement["scope_selector"] = "site_missing"

    assert_raises_completeness(
        lambda: _emit_mutated_synth(mutate, "unknown_site"),
        ["scope=site", "site_missing", "declared Site"],
        "a site measurement selected an unknown Site",
    )
    print("PASS  test_negative_unknown_site_selector_fails")


def test_negative_unknown_ligand_selector_fails() -> None:
    def mutate(run: dict) -> None:
        ligand_measurement = next(
            m for m in run["measurements"] if m.get("scope") == "ligand"
        )
        ligand_measurement["scope_selector"] = "ligand_missing"

    assert_raises_completeness(
        lambda: _emit_mutated_synth(mutate, "unknown_ligand"),
        ["scope=ligand", "ligand_missing", "declared Ligand"],
        "a ligand measurement selected an unknown Ligand",
    )
    print("PASS  test_negative_unknown_ligand_selector_fails")


def test_negative_missing_ligand_declaration_fails() -> None:
    def mutate(run: dict) -> None:
        run["ligands"] = []

    assert_raises_completeness(
        lambda: _emit_mutated_synth(mutate, "missing_ligand"),
        ["ligand_ref", "synth1:A:CA33", "not declared"],
        "a Site referred to an undeclared Ligand",
    )
    print("PASS  test_negative_missing_ligand_declaration_fails")


def test_negative_duplicate_site_and_ligand_ids_fail() -> None:
    for key, label in (("sites", "Site"), ("ligands", "Ligand")):
        def mutate(run: dict, rows_key: str = key) -> None:
            run[rows_key].append(copy.deepcopy(run[rows_key][0]))

        assert_raises_completeness(
            lambda mutate=mutate, key=key: _emit_mutated_synth(
                mutate, f"duplicate_{key}"
            ),
            ["duplicate", label, "id"],
            f"duplicate {label} ids were declared",
        )
    print("PASS  test_negative_duplicate_site_and_ligand_ids_fail")


def test_negative_mixed_valid_and_unconsumed_scoped_measurements_fail() -> None:
    def mutate(run: dict) -> None:
        extra = copy.deepcopy(
            next(m for m in run["measurements"] if m.get("scope") == "site")
        )
        extra["id"] = "EVAL_synth_active_site_unconsumed"
        extra["scope_selector"] = "site_missing_among_valid_measurements"
        run["measurements"].append(extra)

    assert_raises_completeness(
        lambda: _emit_mutated_synth(mutate, "unconsumed_site_measurement"),
        ["EVAL_synth_active_site_unconsumed", "scope=site", "site_missing_among_valid_measurements"],
        "one of several otherwise-valid scoped measurements selected no Site",
    )
    print("PASS  test_negative_mixed_valid_and_unconsumed_scoped_measurements_fail")


def test_quality_indicator_extensions_present() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "quality.yaml"
        path.write_text(
            yaml.safe_dump(_quality_doc_with_governed_bundles(), sort_keys=False)
        )
        qds = qds_emit.emit_qds(
            [path], qds_id="QDS_quality_test", structure_id="synth_quality",
            coverage_scope="cumulative",
        )

    geom = qds.get("geometry_summary") or {}
    _check("ramachandran_z_score" in geom, "Rama-Z missing from geometry_summary")
    _check("packing_z_score" in geom, "packing Z missing from geometry_summary")
    _check("unsatisfied_buried_hbond_count" in geom, "buried H-bond count missing from geometry_summary")

    packing = qds.get("packing_summary") or {}
    _check("packing_z_score" in packing, "packing_summary.packing_z_score missing")
    _check("unsatisfied_buried_hbond_count" in packing, "packing_summary.unsatisfied_buried_hbond_count missing")

    refn = qds.get("refinement_summary") or {}
    _check("diffraction_precision_index" in refn, "DPI missing from refinement_summary")

    mp = qds.get("map_summary") or {}
    _check("directional_resolution_anisotropy" in mp, "3DFSC anisotropy missing from map_summary")
    _check("local_model_map_fsc_q" in mp, "local FSC-Q missing from map_summary")
    _check("rscc_outlier_fraction" in mp, "RSCC outlier fraction missing from map_summary")

    pred = qds.get("predicted_confidence_summary") or {}
    _check("predicted_tm_score" in pred, "pTM missing from predicted_confidence_summary")
    _check("interface_predicted_tm_score" in pred, "ipTM missing from predicted_confidence_summary")
    _check("prediction_ensemble_convergence" in pred, "prediction convergence missing from predicted_confidence_summary")

    prq = qds.get("per_residue_quality") or {}
    _check(prq.get("rscc_per_residue"), "rscc_per_residue array missing")
    _check(prq.get("b_factor_z_per_residue"), "b_factor_z_per_residue array missing")
    _check(prq.get("secondary_structure_per_residue"), "secondary_structure_per_residue array missing")
    _check(prq.get("fsc_q_per_residue"), "fsc_q_per_residue array missing")

    cls = qds.get("classification_summary") or {}
    _check("secondary_structure_agreement" in cls,
           "secondary_structure_agreement missing from classification_summary")
    ssa = cls.get("secondary_structure_agreement") or {}
    _check(ssa.get("value_numeric") is not None,
           "secondary_structure_agreement must carry a numeric informational value")
    _check(cls.get("secondary_structure_assignments"), "secondary_structure_assignments missing")
    _check(cls.get("domain_assignments"), "domain_assignments missing")
    _check("fold_classification" in cls, "fold_classification missing")

    iface = qds.get("interface_quality_summary") or {}
    _check(iface.get("interface_qualities"), "interface_qualities missing")
    _check("interface_buried_surface_area" in iface, "interface BSA missing")
    _check("interface_dockq_score" in iface, "DockQ score missing")
    _check("capri_interface_quality_class" in iface, "CAPRI class missing")

    pens = qds.get("prediction_ensemble_summary") or {}
    _check(pens.get("prediction_ensemble_qualities"), "prediction ensemble rows missing")
    _check("prediction_ensemble_convergence" in pens, "prediction ensemble convergence missing")

    nmr = qds.get("nmr_validation_summary") or {}
    _check(nmr.get("nmr_ensemble_qualities"), "NMR ensemble rows missing")
    _check("nmr_restraint_violation_summary" in nmr, "NMR restraint summary missing")
    _check("nmr_ensemble_precision_rmsd" in nmr, "NMR precision RMSD missing")

    print("PASS  test_quality_indicator_extensions_present  (new scalar + structured blocks)")


def test_negative_structured_scopes_without_rows_fail() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        bad_path = Path(tmpdir) / "eval_bad_no_structured_scopes.yaml"
        missing_interface = _quality_doc_with_governed_bundles()
        missing_interface["evaluation_runs"][0]["interface_qualities"] = []
        bad_path.write_text(yaml.safe_dump(missing_interface, sort_keys=False))

        assert_raises_completeness(
            lambda: qds_emit.emit_qds(
                [bad_path], qds_id="QDS_bad_structured_test",
                structure_id="synth_quality", coverage_scope="cumulative",
            ),
            ["T16 interface-context integrity", "interface selector",
             "does not resolve"],
            "a T16 selector had no structured interface/mapping row",
        )

        missing_other_rows = _quality_doc_with_governed_bundles()
        for run in missing_other_rows["evaluation_runs"]:
            run["domain_assignments"] = []
            run["prediction_ensemble_qualities"] = []
            run["nmr_ensemble_qualities"] = []
        bad_path.write_text(yaml.safe_dump(missing_other_rows, sort_keys=False))
        assert_raises_completeness(
            lambda: qds_emit.emit_qds(
                [bad_path], qds_id="QDS_bad_structured_test",
                structure_id="synth_quality", coverage_scope="cumulative",
            ),
            ["scope=domain", "scope=ensemble"],
            "domain/ensemble measurements had no structured rows",
        )
    print("PASS  test_negative_structured_scopes_without_rows_fail")


def test_coverage_never_claims_an_absent_family() -> None:
    """Coverage derives Tool.family from the catalog; row metadata cannot spoof it."""
    def coverage(measurements):
        return qds_emit.build_cross_tool_coverage("QDS_x", measurements)["task_coverage"][0]

    cc = {"catalog_task_ref": "T06", "oracle_tool_ref": "phenix.fmodel",
          "oracle_measure": {"value_numeric": 1.0}}
    nc = {"catalog_task_ref": "T06", "oracle_tool_ref": "gemmi sfcalc",
          "oracle_measure": {"value_numeric": 1.0}}
    for measurements, want in [
        ([cc], "open — cctbx only"),
        ([nc], "non-cctbx only"),
        ([cc, nc], "dual-family coverage — agreement not evaluated"),
    ]:
        got = coverage(measurements)["gap_status"]
        if got != want:
            print(f"FAIL  gap_status changed for a classified case: {got!r} != {want!r}")
            raise SystemExit(1)

    spoofed = copy.deepcopy(cc)
    spoofed["oracle_family"] = "non_cctbx"
    assert_raises_completeness(
        lambda: coverage([spoofed]),
        ["canonical-tool integrity", "phenix.fmodel", "canonical family is 'cctbx'"],
        "PHENIX was allowed to masquerade as an independent tool",
    )
    assert_raises_completeness(
        lambda: coverage([{"catalog_task_ref": "T06", "oracle_family": "non_cctbx",
                           "oracle_measure": {"value_numeric": 1.0}}]),
        ["canonical-tool integrity", "no oracle_tool_ref"],
        "an unnamed substantive row contributed trust coverage",
    )
    assert_raises_completeness(
        lambda: coverage([{"catalog_task_ref": "T06", "oracle_tool_ref": "not-catalogued",
                           "oracle_family": "non_cctbx",
                           "oracle_measure": {"value_numeric": 1.0}}]),
        ["canonical-tool integrity", "unknown catalog Tool", "not-catalogued"],
        "an unknown tool contributed trust coverage",
    )
    print("PASS  coverage derives canonical families and rejects spoofed/unnamed tools")


def _t14_derived_coverage_rows() -> list[dict]:
    context = {
        "catalog_task_ref": "T14",
        "stage": "final",
        "scope": "complex",
        "scope_selector": "model",
        "subject_ref": "artifact:synth#model.pdb",
    }
    return [
        {
            "id": "T14_SOURCE_REDUCE",
            **context,
            "metric_definition_ref": "T14_asn_gln_his_flip_candidates_scored",
            "oracle_tool_ref": "reduce (standalone, Richardson)",
            "oracle_family": "non_cctbx",
            "oracle_measure": {"value_numeric": 14, "unit": "count"},
            "pass_status": "informational",
        },
        {
            "id": "T14_SOURCE_REDUCE2",
            **context,
            "metric_definition_ref": "T14_asn_gln_his_flip_candidates_scored",
            "oracle_tool_ref": "mmtbx.reduce2",
            "oracle_family": "cctbx",
            "oracle_measure": {"value_numeric": 18, "unit": "count"},
            "pass_status": "informational",
        },
        {
            "id": "T14_CONFLICTS",
            **context,
            "metric_definition_ref": "T14_asn_gln_his_flip_set_conflicts",
            "oracle_tool_ref": "mmtbx.reduce2",
            "oracle_family": "cctbx",
            "oracle_measure": {
                "value_numeric": 0,
                "unit": "count",
                "count": 14,
            },
            "derived_from_measurement_refs": [
                "T14_SOURCE_REDUCE",
                "T14_SOURCE_REDUCE2",
            ],
            "pass_status": "informational",
        },
    ]


def test_derived_coverage_uses_only_validated_source_families() -> None:
    """A joint result gets both families without enabling arbitrary laundering."""
    rows = _t14_derived_coverage_rows()
    run = {
        "id": "EVAL_T14_DERIVED",
        "structure_ref": "synth",
        "run_date": "2026-09-22",
        "catalog_tasks_applied": ["T14"],
        "measurements": rows,
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "derived.yaml"
        _write_eval(path, [run])
        qds = qds_emit.emit_qds(
            [path],
            qds_id="QDS_T14_DERIVED",
            structure_id="synth",
            subject_ref="artifact:synth#model.pdb",
            coverage_scope="partial",
            scope_notes="Synthetic T14 derived-coverage regression.",
            issued_at="2026-09-22T12:00:00+00:00",
        )
    conflict = next(
        row
        for row in qds["cross_tool_coverage"]["task_coverage"]
        if row.get("metric_definition_ref")
        == "T14_asn_gln_his_flip_set_conflicts"
    )
    _check(
        conflict["gap_status"] == "dual-family coverage — agreement not evaluated",
        "a validated T14 composite did not inherit both participating families",
    )
    _check(
        conflict["cctbx_oracles"] == ["mmtbx.reduce2"]
        and conflict["non_cctbx_oracles"]
        == ["reduce (standalone, Richardson)"],
        "derived coverage did not name the exact contributing tool pair",
    )
    _check(
        not qds.get("cross_tool_waivers"),
        "a genuinely dual-family composite should not need a cctbx-only waiver",
    )

    annotated = copy.deepcopy(rows)
    for row in annotated:
        row["_source_evaluation_run_ref"] = "EVAL_T14_DERIVED"

    wrong_metric = copy.deepcopy(annotated)
    wrong_metric[0]["metric_definition_ref"] = "T14_h_added"
    assert_raises_completeness(
        lambda: qds_emit.build_cross_tool_coverage("QDS_bad", wrong_metric),
        [
            "derived-coverage integrity",
            "T14_SOURCE_REDUCE",
            "T14_asn_gln_his_flip_candidates_scored",
        ],
        "an unrelated non-cctbx metric was used to launder composite coverage",
    )

    cross_run = copy.deepcopy(annotated)
    cross_run[0]["_source_evaluation_run_ref"] = "EVAL_OTHER"
    assert_raises_completeness(
        lambda: qds_emit.build_cross_tool_coverage("QDS_bad", cross_run),
        [
            "derived-coverage integrity",
            "T14_SOURCE_REDUCE",
            "belongs to another EvaluationRun",
        ],
        "a cross-run source conferred derived trust coverage",
    )

    mismatched_subject = copy.deepcopy(annotated)
    mismatched_subject[0]["subject_ref"] = "artifact:other#model.pdb"
    assert_raises_completeness(
        lambda: qds_emit.build_cross_tool_coverage("QDS_bad", mismatched_subject),
        ["derived-coverage integrity", "mismatched subject_ref"],
        "a different-subject source conferred derived trust coverage",
    )

    impossible_denominator = copy.deepcopy(annotated)
    impossible_denominator[2]["oracle_measure"]["count"] = 15
    for label, builder in (
        ("live", qds_emit.build_cross_tool_coverage),
        ("frozen v2", qds_emit_contract_v2.build_cross_tool_coverage),
    ):
        assert_raises_completeness(
            lambda builder=builder: builder("QDS_bad", impossible_denominator),
            ["derived-coverage integrity", "denominator 15", "candidate count"],
            f"{label} emitter gave dual-family credit to an impossible denominator",
        )

    graded_source = copy.deepcopy(annotated)
    graded_source[0]["pass_status"] = "pass"
    assert_raises_completeness(
        lambda: qds_emit.build_cross_tool_coverage("QDS_bad", graded_source),
        ["derived-coverage integrity", "T14_SOURCE_REDUCE", "informational"],
        "a gradeable candidate-count source conferred composite trust coverage",
    )

    unnamed_cohort = copy.deepcopy(annotated)
    for row in unnamed_cohort:
        row["scope"] = "cohort"
        row["scope_selector"] = ""
    spoofed_task = copy.deepcopy(annotated)
    for row in spoofed_task:
        row["catalog_task_ref"] = "T03"
    for label, builder in (
        ("live", qds_emit.build_cross_tool_coverage),
        ("frozen v2", qds_emit_contract_v2.build_cross_tool_coverage),
    ):
        assert_raises_completeness(
            lambda builder=builder: builder("QDS_bad", unnamed_cohort),
            ["derived-coverage integrity", "cohort", "scope_selector"],
            f"{label} emitter accepted an unnamed preregistered cohort",
        )
        assert_raises_completeness(
            lambda builder=builder: builder("QDS_bad", spoofed_task),
            ["derived-coverage integrity", "catalog_task_ref", "T14"],
            f"{label} emitter let T14 composite lineage launder another task",
        )

    def cohort_rows(
        numerator: int,
        denominator: int,
        status: str,
        criterion: str | None,
    ) -> list[dict]:
        cohort = copy.deepcopy(annotated)
        for row in cohort:
            row.update(
                {
                    "scope": "cohort",
                    "scope_selector": "round48-preregistered-cohort",
                    "subject_ref": "cohort:round48",
                }
            )
        composite = cohort[2]
        composite["oracle_measure"].update(
            {"value_numeric": numerator, "count": denominator}
        )
        composite["pass_status"] = status
        if criterion is None:
            composite.pop("pass_criterion", None)
        else:
            composite["pass_criterion"] = criterion
        return cohort

    for label, builder in (
        ("live", qds_emit.build_cross_tool_coverage),
        ("frozen v2", qds_emit_contract_v2.build_cross_tool_coverage),
    ):
        for numerator, denominator, status in (
            (0, 10, "pass_with_caveat"),
            (1, 10, "pass"),
            (2, 10, "fail_criterion"),
        ):
            coverage = builder(
                "QDS_cohort",
                cohort_rows(
                    numerator,
                    denominator,
                    status,
                    "conflict rate <= 10%",
                ),
            )
            _check(
                any(
                    row.get("metric_definition_ref")
                    == "T14_asn_gln_his_flip_set_conflicts"
                    for row in coverage["task_coverage"]
                ),
                f"{label} rejected a correct {numerator}/{denominator} cohort verdict",
            )
        # Informational cohort observations remain allowed without a criterion.
        builder(
            "QDS_cohort_info",
            cohort_rows(2, 10, "informational", None),
        )
        for numerator, status in ((1, "fail_criterion"), (2, "pass")):
            assert_raises_completeness(
                lambda builder=builder, numerator=numerator, status=status: builder(
                    "QDS_bad",
                    cohort_rows(
                        numerator,
                        10,
                        status,
                        "conflict rate <= 10%",
                    ),
                ),
                ["derived-coverage integrity", f"{numerator}/10", "pass_status"],
                f"{label} accepted an inverted cohort threshold verdict",
            )
        assert_raises_completeness(
            lambda builder=builder: builder(
                "QDS_bad",
                cohort_rows(
                    1,
                    10,
                    "pass",
                    "conflict rate <= 10% or <= 20%",
                ),
            ),
            ["derived-coverage integrity", "unambiguous", "<= 10%"],
            f"{label} accepted an ambiguous cohort threshold criterion",
        )
        assert_raises_completeness(
            lambda builder=builder: builder(
                "QDS_bad",
                cohort_rows(
                    1,
                    10,
                    "pass",
                    "not conflict rate <= 10%",
                ),
            ),
            ["derived-coverage integrity", "unambiguous", "<= 10%"],
            f"{label} accepted a negated cohort threshold criterion",
        )

    generic = copy.deepcopy(annotated)
    generic[2]["metric_definition_ref"] = "T14_h_added"
    generic_coverage = qds_emit.build_cross_tool_coverage("QDS_generic", generic)
    generic_row = next(
        row
        for row in generic_coverage["task_coverage"]
        if row.get("metric_definition_ref") == "T14_h_added"
    )
    _check(
        generic_row["gap_status"] == "open — cctbx only",
        "uncontracted generic lineage laundered a cctbx row into dual-family coverage",
    )
    print("PASS  derived coverage inherits only validated, contracted source families")


def test_contract_v2_replays_full_september_eval_and_preserves_v1() -> None:
    """The real audit, not a reduced proxy, must traverse the retained contract."""
    _check(
        hashlib.sha256(Path(qds_emit_contract_v1.__file__).read_bytes()).hexdigest()
        == "4f36031377783bc7e3859386f238b333c4615969f9bd6c77178b94f27234540d",
        "frozen contract-1 source changed while adding contract 2",
    )
    _check(
        qds_emit.QDS_EMITTER_CONTRACT_VERSION == "2"
        and qds_emit.SUPPORTED_QDS_EMITTER_CONTRACT_VERSIONS == {"1", "2"},
        "live emitter does not default to v2 while retaining explicit v1 dispatch",
    )

    subject = (
        "artifact:cdba2c07-daff-4f60-ae96-12452b3a5fbb#"
        "data/1sar_final.pdb"
    )
    kwargs = {
        "qds_id": "QDS_1sar_contract_v2_regression",
        "structure_id": "1sar",
        "subject_ref": subject,
        "coverage_scope": "partial",
        "scope_notes": "Full September audit contract-v2 regression.",
        "issued_at": "2026-09-22T00:00:00+00:00",
    }
    live = qds_emit.emit_qds([EVAL_1SAR.parent / "EVAL_1sar_cdba2c07_2026-09-07.yaml"], **kwargs)
    frozen = qds_emit_contract_v2.emit_qds(
        [EVAL_1SAR.parent / "EVAL_1sar_cdba2c07_2026-09-07.yaml"], **kwargs
    )
    _check(live == frozen, "live contract 2 diverges from its retained replay module")
    conflict = next(
        row
        for row in live["cross_tool_coverage"]["task_coverage"]
        if row.get("metric_definition_ref")
        == "T14_asn_gln_his_flip_set_conflicts"
    )
    _check(
        conflict["cctbx_oracles"] == ["mmtbx.reduce2"]
        and conflict["non_cctbx_oracles"]
        == ["reduce (standalone, Richardson)"]
        and conflict["gap_status"]
        == "dual-family coverage — agreement not evaluated",
        "full September emission did not preserve validated T14 composite coverage",
    )
    _check(
        not any(
            waiver.get("catalog_task_ref") == "T14"
            for waiver in live.get("cross_tool_waivers", [])
        ),
        "full September emission still depends on a T14 trust waiver",
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "v1.yaml"
        _write_eval(
            path,
            [
                {
                    "id": "EVAL_v1_stability",
                    "structure_ref": "synth",
                    "run_date": "2026-09-22",
                    "catalog_tasks_applied": [],
                    "measurements": [],
                }
            ],
        )
        v1_kwargs = {
            "qds_id": "QDS_v1_stability",
            "structure_id": "synth",
            "coverage_scope": "cumulative",
            "issued_at": "2026-09-22T00:00:00+00:00",
        }
        live_v1 = qds_emit.emit_qds(
            [path], emitter_contract_version="1", **v1_kwargs
        )
        frozen_v1 = qds_emit_contract_v1.emit_qds([path], **v1_kwargs)
    _check(
        live_v1 == frozen_v1 and live_v1["emitter_contract_version"] == "1",
        "explicit v1 dispatch no longer replays through the frozen v1 implementation",
    )
    print("PASS  full September eval replays through v2 and v1 remains frozen")


def test_trust_invariant_waiver_mechanics() -> None:
    """#315: cctbx-only coverage without a waiver refuses to emit; with a
    waiver it emits, surfaces the waiver block, and annotates the row. The
    1SAR eval is the live case (T06 was the Codex review's exhibit)."""
    qds = _emit_legacy_1sar("QDS_ti")
    t06 = next(r for r in qds["cross_tool_coverage"]["task_coverage"]
               if r["catalog_task_ref"] == "T06")
    _check("WAIVED" in t06["gap_status"],
           "T06 coverage row not annotated with its waiver")
    _check(any(w["catalog_task_ref"] == "T06"
               for w in qds.get("cross_tool_waivers", [])),
           "waiver block absent from the QDS")

    try:
        _emit_legacy_1sar("QDS_ti2", omit_waiver_tasks={"T06"})
        _check(False, "cctbx-only metric with no waiver emitted anyway")
    except qds_emit.QdsCompletenessError as exc:
        _check("T06" in str(exc) and "#315" in str(exc),
               "trust-invariant refusal does not name the task and rule")
    print("PASS  test_trust_invariant_waiver_mechanics")


def _write_eval(path: Path, runs: list[dict]) -> None:
    path.write_text(yaml.safe_dump({"evaluation_runs": runs}, sort_keys=False,
                                   allow_unicode=True))


def _emit_legacy_1sar(
    qds_id: str, omit_waiver_tasks: set[str] | None = None
) -> dict:
    """Exercise legacy local blocks without preserving known-invalid coverage.

    The April fixture contains several equal-priority R-factor bundles and used
    task-level coverage to let an unrelated oracle close cctbx-only metrics.  New
    tests cover those failures directly; this helper removes the ambiguous R
    triple and gives every remaining numeric cctbx task an explicit test waiver
    so geometry/site regression coverage can reach the builders it targets.
    """
    doc = copy.deepcopy(yaml.safe_load(EVAL_1SAR.read_text()))
    run = doc["evaluation_runs"][0]
    refinement_metrics = {
        metric
        for metric, target in qds_emit.METRIC_TO_QDS_SLOT.items()
        for block, slot in ([target] if isinstance(target, tuple) else target)
        if block == "refinement_summary" and slot in qds_emit.REFINEMENT_SLOTS
    }
    run["measurements"] = [
        measurement
        for measurement in run.get("measurements", [])
        if measurement.get("metric_definition_ref") not in refinement_metrics
    ]
    for measurement in run["measurements"]:
        # Historical rows predate the schema's exactly-one typed-value carrier
        # contract. Upgrade this in-memory fixture before exercising unrelated
        # legacy local-block builders; the adversarial test below proves that
        # real emission rejects the original dual-carrier form.
        for field in qds_emit.TYPED_VALUE_FIELDS:
            value = measurement.get(field)
            if not isinstance(value, dict):
                continue
            if value.get("value_numeric") is not None:
                value.pop("value_text", None)
                value.pop("is_not_applicable", None)
        if (
            measurement.get("metric_definition_ref")
            in qds_emit.TEXTUAL_SUMMARY_METRIC_IDS
            and (measurement.get("oracle_measure") or {}).get("value_text")
        ):
            # Historical fixture rows predate the label-only rule. This helper
            # upgrades them to the current contract before testing unrelated
            # builders; the dedicated adversarial test below proves rejection.
            measurement["pass_status"] = "informational"
    cctbx_claims = {
        tuple(measurement.get(field) for field in (
            "catalog_task_ref", "metric_definition_ref", "subject_ref",
            "reference_subject_ref", "stage", "scope", "scope_selector",
        ))
        for measurement in run["measurements"]
        if measurement.get("oracle_family") == "cctbx"
        and isinstance(
            (measurement.get("oracle_measure") or {}).get("value_numeric"),
            (int, float),
        )
    }
    omit = omit_waiver_tasks or set()
    waivers = []
    fields = (
        "catalog_task_ref", "metric_definition_ref", "subject_ref",
        "reference_subject_ref", "stage", "scope", "scope_selector",
    )
    for index, claim in enumerate(sorted(cctbx_claims, key=str), start=1):
        values = dict(zip(fields, claim, strict=True))
        task = values["catalog_task_ref"]
        if task in omit:
            continue
        waiver = {
            "id": f"TEST_WAIVER_{task}_{index}",
            "catalog_task_ref": task,
            "reason": "Synthetic waiver used only to isolate QDS builder regression tests.",
            "as_of_date": "2026-09-21",
        }
        waiver.update({key: value for key, value in values.items()
                       if key != "catalog_task_ref" and value not in (None, "")})
        waivers.append(waiver)
    run["cross_tool_waivers"] = waivers
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "legacy_1sar.yaml"
        path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
        return qds_emit.emit_qds(
            [path], qds_id=qds_id, structure_id="1sar", coverage_scope="cumulative",
            issued_at="2026-09-21T00:00:00+00:00",
        )


def _measurement(
    mid: str,
    metric: str,
    value: float,
    *,
    tool: str = "DSSP + biotite P-SEA",
    subject: str | None = None,
    selector: str = "whole model",
) -> dict:
    row = {
        "id": mid,
        "catalog_task_ref": metric[:3],
        "stage": "final",
        "scope": "complex",
        "scope_selector": selector,
        "metric_definition_ref": metric,
        "oracle_tool_ref": tool,
        "oracle_family": "non_cctbx",
        "oracle_measure": {"value_numeric": value},
        "pass_status": "informational",
        "notes": f"source note for {mid}",
    }
    if subject is not None:
        row["subject_ref"] = subject
    if metric in {
        "T15_secondary_structure_agreement",
        "T15_secondary_structure_content",
    }:
        row["bundle_ref"] = f"T15:{subject or 'unlabelled'}:{selector}"
    return row


def test_subject_selection_preserves_provenance_and_is_order_independent() -> None:
    package = "artifact:cdba2c07#data/1sar_final.pdb"
    deposited = "pdb:1sar"
    rows = [
        _measurement("M_dep", "T15_secondary_structure_agreement", 0.8646,
                     subject=deposited, selector="deposited model"),
        _measurement("M_pkg", "T15_secondary_structure_agreement", 0.8802,
                     subject=package, selector="packaged model"),
        _measurement("M_content", "T15_secondary_structure_content", 0.375,
                     tool="DSSP", subject=package, selector="packaged model"),
    ]
    run = {
        "id": "EVAL_subject_test",
        "structure_ref": "1sar",
        "run_date": "2026-09-21",
        "catalog_tasks_applied": ["T15"],
        "measurements": rows,
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        first = Path(tmpdir) / "first.yaml"
        reverse = Path(tmpdir) / "reverse.yaml"
        _write_eval(first, [run])
        reversed_run = copy.deepcopy(run)
        reversed_run["measurements"].reverse()
        _write_eval(reverse, [reversed_run])

        kwargs = dict(qds_id="QDS_subject", structure_id="1sar",
                      structure_method="xray", subject_ref=package,
                      coverage_scope="cumulative", resolution_a=2.5,
                      space_group="P 21 21 21", issued_at="2026-09-21T00:00:00+00:00")
        qds = qds_emit.emit_qds([first], **kwargs)
        qds_reversed = qds_emit.emit_qds([reverse], **kwargs)

        _check(qds == qds_reversed, "measurement order cannot change subject-selected QDS output")
        agreement = qds["classification_summary"]["secondary_structure_agreement"]
        _check(agreement["value_numeric"] == 0.8802,
               "named packaged subject wins over deposited baseline")
        for key, expected in {
            "source_evaluation_run_ref": "EVAL_subject_test",
            "source_measurement_ref": "M_pkg",
            "metric_definition_ref": "T15_secondary_structure_agreement",
            "oracle_tool_ref": "DSSP + biotite P-SEA",
            "oracle_family": "non_cctbx",
            "pass_status": "informational",
            "scope_selector": "packaged model",
            "subject_ref": package,
        }.items():
            _check(agreement.get(key) == expected,
                   f"wrapped value preserves {key} provenance")
        _check("source note" in agreement.get("notes", ""),
               "wrapped value preserves source caveat text")
        _check(qds["classification_summary"]["secondary_structure_content"]
               ["value_numeric"] == 0.375, "T15 DSSP content routes to the QDS")
        _check(qds["identity_block"] == {
            "id": "QDS_subject_identity", "pdb_id": "1sar", "method": "xray",
            "resolution_a": 2.5, "space_group": "P 21 21 21"
        }, "identity carries method, resolution, and space group")
        _check(qds["issued_at"] == "2026-09-21T00:00:00+00:00",
               "issued_at can be pinned for reproducible immutable output")

        assert_raises_completeness(
            lambda: qds_emit.emit_qds([first], qds_id="QDS_ambiguous",
                                      structure_id="1sar", coverage_scope="cumulative"),
            ["multiple explicit measurement or structured-row subjects", "--subject-ref"],
            "multiple explicit subjects were supplied without a QDS subject",
        )
    print("PASS  test_subject_selection_preserves_provenance_and_is_order_independent")


def test_refinement_triple_is_one_code_path() -> None:
    metrics = (
        ("T03_r-work", 0.1622),
        ("T03_r-free", 0.2136),
        ("T03_r-free_r-work_gap", 0.0515),
    )
    old = {
        "id": "EVAL_old", "structure_ref": "1sar", "run_date": "2026-04-24",
        "catalog_tasks_applied": ["T03"],
        "measurements": [
            _measurement(f"old_{i}", metric, value + 0.01, tool="Servalcat")
            for i, (metric, value) in enumerate(metrics)
        ],
    }
    new = {
        "id": "EVAL_new", "structure_ref": "1sar", "run_date": "2026-09-07",
        "catalog_tasks_applied": ["T03"],
        "measurements": [
            _measurement(f"new_{i}", metric, value, tool="gemmi sfcalc")
            for i, (metric, value) in enumerate(metrics)
        ],
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        p_old, p_new = Path(tmpdir) / "old.yaml", Path(tmpdir) / "new.yaml"
        _write_eval(p_old, [old])
        _write_eval(p_new, [new])
        qds = qds_emit.emit_qds([p_new, p_old], qds_id="QDS_bundle", structure_id="1sar",
                                coverage_scope="cumulative",
                                issued_at="2026-09-21T00:00:00+00:00")
        refn = qds["refinement_summary"]
        values = [refn[slot] for slot in ("r_work", "r_free", "r_free_gap")]
        _check({v["source_evaluation_run_ref"] for v in values} == {"EVAL_new"},
               "all refinement values come from one source run")
        _check({v["oracle_tool_ref"] for v in values} == {"gemmi sfcalc"},
               "all refinement values come from one tool code path")

        broken = copy.deepcopy(new)
        broken["id"] = "EVAL_broken"
        broken["measurements"] = [
            _measurement("broken_work", "T03_r-work", 0.16, tool="gemmi sfcalc"),
            _measurement("broken_free", "T03_r-free", 0.21, tool="Servalcat"),
        ]
        p_broken = Path(tmpdir) / "broken.yaml"
        _write_eval(p_broken, [broken])
        assert_raises_completeness(
            lambda: qds_emit.emit_qds([p_broken], qds_id="QDS_broken",
                                      structure_id="1sar", coverage_scope="cumulative"),
            ["refinement-summary coherence", "no single evaluation run/tool/family/subject"],
            "an R-factor summary required mixing code paths",
        )
    print("PASS  test_refinement_triple_is_one_code_path")


def test_superseded_assumptions_are_not_republished() -> None:
    old = {"id": "EVAL_old", "assumptions": [{"id": "A_withdrawn"}, {"id": "A_retained"}]}
    correction = {"id": "EVAL_correction", "superseded_assumption_refs": ["A_withdrawn"]}
    ids = {a["id"] for a in qds_emit.build_assumptions_report([old, correction])}
    _check(ids == {"A_retained"}, "later runs remove explicitly superseded assumptions")
    print("PASS  test_superseded_assumptions_are_not_republished")


def test_explicit_assumption_registry_snapshot_is_applied() -> None:
    assumption = {
        "id": "ASSUMPTION_snapshot_tool",
        "tool_ref": "Snapshot Tool",
        "as_of_date": "2026-09-21",
        "effective_at": "2026-09-21T12:00:00+00:00",
        "description": "Assumption retained in the source-owned snapshot.",
    }
    run = {
        "id": "EVAL_explicit_assumption_snapshot",
        "measurements": [
            {
                "id": "M_explicit_assumption_snapshot",
                "oracle_tool_ref": "Snapshot Tool",
            }
        ],
    }
    report = qds_emit.build_assumptions_report(
        [run],
        "2026-09-22T00:00:00+00:00",
        registry_rows=[assumption],
    )
    _check(
        report == [assumption],
        "an explicit source-owned assumption registry did not surface the "
        "assumption matching the measurement's oracle tool",
    )
    print("PASS  test_explicit_assumption_registry_snapshot_is_applied")


def test_pinned_source_snapshots_deduplicate_and_reject_conflicts() -> None:
    tool = {
        "id": "Snapshot Tool",
        "version": "1.0",
        "family": "non_cctbx",
        "catalog_tasks_served": [],
    }
    recommendation = {
        "id": "REC_snapshot",
        "metric_definition_ref": "T15_secondary_structure_content",
        "as_of_date": "2026-09-21",
        "effective_at": "2026-09-21T12:00:00+00:00",
        "recommendation": "Pinned recommendation snapshot.",
    }
    assumption = {
        "id": "ASSUMPTION_snapshot",
        "tool_ref": "Snapshot Tool",
        "as_of_date": "2026-09-21",
        "effective_at": "2026-09-21T12:00:00+00:00",
        "description": "Pinned assumption snapshot.",
    }

    def source_document(run_id: str) -> dict:
        return {
            "tools": [copy.deepcopy(tool)],
            "tool_recommendations": [copy.deepcopy(recommendation)],
            "assumptions": [copy.deepcopy(assumption)],
            "evaluation_runs": [
                {
                    "id": run_id,
                    "structure_ref": "synth",
                    "run_date": "2026-09-21",
                    "catalog_tasks_applied": [],
                    "measurements": [],
                }
            ],
        }

    with tempfile.TemporaryDirectory() as tmpdir:
        first = Path(tmpdir) / "first.yaml"
        second = Path(tmpdir) / "second.yaml"
        first.write_text(
            yaml.safe_dump(source_document("EVAL_snapshot_first"), sort_keys=False)
        )
        second.write_text(
            yaml.safe_dump(source_document("EVAL_snapshot_second"), sort_keys=False)
        )
        qds = qds_emit.emit_qds(
            [first, second],
            qds_id="QDS_snapshot_deduplication",
            structure_id="synth",
            coverage_scope="cumulative",
            issued_at="2026-09-22T00:00:00+00:00",
            emitter_contract_version="1",
            require_pinned_tool_snapshot=True,
        )
        _check(
            qds["derived_from_evaluation_run_refs"]
            == ["EVAL_snapshot_first", "EVAL_snapshot_second"],
            "contract-1 replay did not accept identical per-document source snapshots",
        )

        conflict_cases = (
            ("tools", "family", "cctbx", "source Tool snapshot"),
            (
                "tool_recommendations",
                "recommendation",
                "Conflicting recommendation snapshot.",
                "source tool-recommendation snapshot",
            ),
            (
                "assumptions",
                "description",
                "Conflicting assumption snapshot.",
                "source tool-assumption snapshot",
            ),
        )
        for field, changed_key, changed_value, expected_label in conflict_cases:
            conflicting = source_document("EVAL_snapshot_second")
            conflicting[field][0][changed_key] = changed_value
            second.write_text(yaml.safe_dump(conflicting, sort_keys=False))
            assert_raises_completeness(
                lambda: qds_emit.emit_qds(
                    [first, second],
                    qds_id="QDS_snapshot_conflict",
                    structure_id="synth",
                    coverage_scope="cumulative",
                    issued_at="2026-09-22T00:00:00+00:00",
                    emitter_contract_version="1",
                    require_pinned_tool_snapshot=True,
                ),
                [
                    "source-snapshot integrity failed",
                    expected_label,
                    "conflicting duplicate id",
                ],
                f"two source documents disagreed on {field!r} for one snapshot id",
            )

    print("PASS  test_pinned_source_snapshots_deduplicate_and_reject_conflicts")


def test_registry_snapshots_exclude_future_rows() -> None:
    run = {
        "id": "EVAL_registry_cutoff",
        "measurements": [
            {
                "id": "M_registry_cutoff",
                "metric_definition_ref": "T15_secondary_structure_content",
                "oracle_tool_ref": "DSSP",
            }
        ],
    }
    recommendations = {
        "tool_recommendations": [
            {
                "id": "REC_active",
                "metric_definition_ref": "T15_secondary_structure_content",
                "as_of_date": "2026-09-21",
                "effective_at": "2026-09-21T12:00:00+00:00",
            },
            {
                "id": "REC_later_same_day",
                "metric_definition_ref": "T15_secondary_structure_content",
                "as_of_date": "2026-09-22",
                "effective_at": "2026-09-22T20:00:00+00:00",
                "supersedes_recommendation_ref": "REC_active",
            },
            {
                "id": "REC_future",
                "metric_definition_ref": "T15_secondary_structure_content",
                "as_of_date": "2027-01-01",
                "effective_at": "2027-01-01T12:00:00+00:00",
                "supersedes_recommendation_ref": "REC_later_same_day",
            },
        ]
    }
    assumptions = {
        "assumptions": [
            {
                "id": "ASSUM_active",
                "tool_ref": "DSSP",
                "as_of_date": "2026-09-21",
                "effective_at": "2026-09-21T12:00:00+00:00",
            },
            {
                "id": "ASSUM_later_same_day",
                "tool_ref": "DSSP",
                "as_of_date": "2026-09-22",
                "effective_at": "2026-09-22T20:00:00+00:00",
                "supersedes_assumption_ref": "ASSUM_active",
            },
            {
                "id": "ASSUM_future",
                "tool_ref": "DSSP",
                "as_of_date": "2027-01-01",
                "effective_at": "2027-01-01T12:00:00+00:00",
                "supersedes_assumption_ref": "ASSUM_later_same_day",
            },
        ]
    }
    old_recs = qds_emit.TOOL_RECS_PATH
    old_assumptions = qds_emit.TOOL_ASSUMPTIONS_PATH
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            qds_emit.TOOL_RECS_PATH = Path(tmpdir) / "tool_recommendations.yaml"
            qds_emit.TOOL_ASSUMPTIONS_PATH = Path(tmpdir) / "tool_assumptions.yaml"
            qds_emit.TOOL_RECS_PATH.write_text(yaml.safe_dump(recommendations))
            qds_emit.TOOL_ASSUMPTIONS_PATH.write_text(yaml.safe_dump(assumptions))
            cutoff = "2026-09-22T00:18:11-07:00"
            rec_ids = {
                row["id"]
                for row in qds_emit.build_tool_recommendations_applied([run], cutoff)
            }
            assumption_ids = {
                row["id"]
                for row in qds_emit.build_assumptions_report([run], cutoff)
            }
            _check(rec_ids == {"REC_active"},
                   "a future recommendation leaked into a historical QDS snapshot")
            _check(assumption_ids == {"ASSUM_active"},
                   "a future tool assumption leaked into a historical QDS snapshot")

            later_same_day_cutoff = "2026-09-22T21:00:00+00:00"
            same_day_rec_ids = {
                row["id"]
                for row in qds_emit.build_tool_recommendations_applied(
                    [run], later_same_day_cutoff
                )
            }
            same_day_assumption_ids = {
                row["id"]
                for row in qds_emit.build_assumptions_report(
                    [run], later_same_day_cutoff
                )
            }
            _check(same_day_rec_ids == {"REC_later_same_day"},
                   "precise same-day recommendation activation was ignored")
            _check(same_day_assumption_ids == {"ASSUM_later_same_day"},
                   "precise same-day assumption activation was ignored")

            future_cutoff = "2027-01-02T00:00:00+00:00"
            future_rec_ids = {
                row["id"]
                for row in qds_emit.build_tool_recommendations_applied(
                    [run], future_cutoff
                )
            }
            future_assumption_ids = {
                row["id"]
                for row in qds_emit.build_assumptions_report([run], future_cutoff)
            }
            _check(future_rec_ids == {"REC_future"},
                   "an active recommendation revision did not retire its predecessor")
            _check(future_assumption_ids == {"ASSUM_future"},
                   "an active assumption revision did not retire its predecessor")

            broken_recommendations = copy.deepcopy(recommendations)
            broken_recommendations["tool_recommendations"][2][
                "supersedes_recommendation_ref"
            ] = "REC_missing"
            qds_emit.TOOL_RECS_PATH.write_text(
                yaml.safe_dump(broken_recommendations)
            )
            assert_raises_completeness(
                lambda: qds_emit.build_tool_recommendations_applied(
                    [run], cutoff
                ),
                ["tool-recommendation registry", "dangling", "REC_missing"],
                "an inactive future registry revision named a missing predecessor",
            )

            recommendations["tool_recommendations"][0].pop("as_of_date")
            qds_emit.TOOL_RECS_PATH.write_text(yaml.safe_dump(recommendations))
            assert_raises_completeness(
                lambda: qds_emit.build_tool_recommendations_applied([run], cutoff),
                ["tool-recommendation registry", "REC_active", "no as_of_date"],
                "an undated recommendation entered an immutable QDS snapshot",
            )
    finally:
        qds_emit.TOOL_RECS_PATH = old_recs
        qds_emit.TOOL_ASSUMPTIONS_PATH = old_assumptions
    print("PASS  test_registry_snapshots_exclude_future_rows")


def test_subject_inference_includes_structured_rows_and_rejects_typos() -> None:
    subject = "artifact:structured-only"
    run = {
        "id": "EVAL_structured_subject",
        "structure_ref": "synth",
        "run_date": "2026-09-21",
        "catalog_tasks_applied": ["T15"],
        "measurements": [],
        "secondary_structure_assignments": [
            {"id": "SSA_subject", "structure_ref": "synth", "subject_ref": subject}
        ],
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "structured.yaml"
        _write_eval(path, [run])
        qds = qds_emit.emit_qds(
            [path], qds_id="QDS_structured", structure_id="synth",
            coverage_scope="cumulative",
            issued_at="2026-09-21T00:00:00+00:00",
        )
        _check(qds.get("subject_ref") == subject,
               "sole structured-row subject is inferred and emitted")
        _check(
            qds["classification_summary"]["secondary_structure_assignments"][0]["id"]
            == "SSA_subject",
            "structured subject row survives the inferred filter",
        )
        assert_raises_completeness(
            lambda: qds_emit.emit_qds(
                [path], qds_id="QDS_typo", structure_id="synth",
                subject_ref="artifact:typo", coverage_scope="cumulative",
            ),
            ["has no exact evidence", "Refusing legacy fallback"],
            "a requested subject did not match explicit structured evidence",
        )
    print("PASS  test_subject_inference_includes_structured_rows_and_rejects_typos")


def test_subject_filter_reaches_every_downstream_builder() -> None:
    subject_a, subject_b = "artifact:A", "artifact:B"
    run_a = {
        "id": "EVAL_A", "structure_ref": "synth", "run_date": "2026-09-21",
        "catalog_tasks_applied": ["T05", "T07", "T15"],
        "measurements": [
            _measurement("A_site", "T05_clashscore", 4.0, tool="MolProbity (gold)",
                         subject=subject_a, selector="A_site")
            | {"scope": "site"},
            _measurement("legacy_site", "T05_clashscore", 9.0, tool="MolProbity (gold)",
                         selector="A_site") | {"scope": "site"},
            _measurement("A_ptm", "T07_predicted_tm_score", 0.9,
                         subject=subject_a),
            _measurement("legacy_ptm", "T07_predicted_tm_score", 0.1),
            _measurement("A_ss", "T15_secondary_structure_agreement", 0.8,
                         subject=subject_a),
            _measurement("A_ss_content", "T15_secondary_structure_content", 0.4,
                         tool="DSSP", subject=subject_a),
            _measurement("legacy_ss", "T15_secondary_structure_agreement", 0.2),
        ],
        "sites": [{"id": "A_site", "structure_ref": "synth"}],
        "secondary_structure_assignments": [
            {"id": "SSA_A", "structure_ref": "synth", "subject_ref": subject_a},
            {"id": "SSA_legacy", "structure_ref": "synth"},
        ],
        "assumptions": [{"id": "ASSUMPTION_A"}],
        "headline_verdict": "headline for A",
    }
    run_b = {
        "id": "EVAL_B", "structure_ref": "synth", "run_date": "2026-09-21",
        "catalog_tasks_applied": ["T01"],
        "measurements": [
            _measurement("B_rmsd", "T01_ca_rmsd_å", 7.0, subject=subject_b)
        ],
        "pairwise_comparisons": [{"id": "PAIR_B"}],
        "per_residue_values": [{"id": "PRV_B"}],
        "cross_tool_waivers": [{
            "id": "WAIVER_B", "catalog_task_ref": "T01",
            "reason": "belongs only to B", "as_of_date": "2026-09-21",
        }],
        "assumptions": [{"id": "ASSUMPTION_B"}],
        "headline_verdict": "headline for B",
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "subjects.yaml"
        _write_eval(path, [run_a, run_b])
        qds = qds_emit.emit_qds(
            [path], qds_id="QDS_A", structure_id="synth",
            structure_method="predicted_model", subject_ref=subject_a,
            coverage_scope="cumulative",
            issued_at="2026-09-21T00:00:00+00:00",
        )
    _check(qds["derived_from_evaluation_run_refs"] == ["EVAL_A"],
           "wrong-subject run is absent from QDS derivation")
    _check(qds.get("headline_verdict") == "headline for A",
           "wrong-subject headline cannot leak")
    _check({a["id"] for a in qds.get("assumptions_report", []) if a["id"].startswith("ASSUMPTION_")}
           == {"ASSUMPTION_A"}, "wrong-subject run assumption cannot leak")
    _check(not qds.get("cross_tool_waivers"), "wrong-subject waiver cannot leak")
    _check(not qds.get("pairwise_comparisons"), "wrong-subject pairwise row cannot leak")
    _check(not qds.get("per_residue_quality"), "wrong-subject residue row cannot leak")
    _check(all(rec.get("metric_definition_ref") != "T01_ca_rmsd_å"
               for rec in qds.get("tool_recommendations_applied", [])),
           "wrong-subject metric cannot pull in a recommendation")
    _check(qds["site_qualities"][0]["site_clashscore"]["value_numeric"] == 4.0,
           "site builder prefers exact subject over legacy value")
    _check(qds["site_qualities"][0]["site_clashscore"]["source_evaluation_run_ref"]
           == "EVAL_A", "site scalar preserves its source run")
    _check(qds["predicted_confidence_summary"]["predicted_tm_score"]["value_numeric"]
           == 0.9, "predicted builder honors exact subject")
    rows = qds["classification_summary"]["secondary_structure_assignments"]
    _check([row["id"] for row in rows] == ["SSA_A"],
           "structured-row builder drops legacy fallback when exact rows exist")
    print("PASS  test_subject_filter_reaches_every_downstream_builder")


def test_subject_filter_covers_every_structured_row_family() -> None:
    subject_a, subject_b = "artifact:A", "artifact:B"
    run = {
        "id": "EVAL_mixed_rows",
        "measurements": [
            _measurement("A_metric", "T05_clashscore", 1.0, subject=subject_a)
        ],
    }
    for key in qds_emit.SUBJECT_ROW_KEYS:
        run[key] = [
            {"id": f"{key}_A", "subject_ref": subject_a},
            {"id": f"{key}_B", "subject_ref": subject_b},
            {"id": f"{key}_legacy"},
        ]

    filtered = qds_emit._annotated_runs([run], subject_a)
    _check(len(filtered) == 1, "mixed-subject run remains for its exact subject")
    for key in qds_emit.SUBJECT_ROW_KEYS:
        _check(
            [row["id"] for row in filtered[0][key]] == [f"{key}_A"],
            f"{key} excludes explicit nonmatches and displaces legacy fallback",
        )
    print("PASS  test_subject_filter_covers_every_structured_row_family")


def test_metric_context_coverage_blocks_laundering() -> None:
    def row(mid: str, metric: str, family: str, tool: str,
            numeric: float | None, **extra: object) -> dict:
        value = {"value_numeric": numeric} if numeric is not None else {
            "value_text": "tool aborted"
        }
        return {
            "id": mid, "catalog_task_ref": "T03", "stage": "final",
            "scope": "complex", "metric_definition_ref": metric,
            "oracle_family": family, "oracle_tool_ref": tool,
            "oracle_measure": value, **extra,
        }

    measurements = [
        row("work_c", "T03_r-work", "cctbx", "phenix.fmodel", 0.15,
            provenance_ref="run:cctbx"),
        row("work_abort", "T03_r-work", "non_cctbx", "aimless", None,
            provenance_ref="run:aborted"),
        row("free_n", "T03_r-free", "non_cctbx", "gemmi sfcalc", 0.21),
    ]
    coverage = qds_emit.build_cross_tool_coverage("QDS_cov", measurements)
    by_metric = {item["metric_definition_ref"]: item
                 for item in coverage["task_coverage"]}
    _check(by_metric["T03_r-work"]["gap_status"].startswith("open — cctbx only"),
           "aborted nonnumeric oracle cannot close numeric R-work coverage")
    _check("aimless" in by_metric["T03_r-work"]["gap_status"],
           "excluded aborted attempt remains visible")
    _check(by_metric["T03_r-free"]["gap_status"] == "non-cctbx only",
           "unrelated R-free oracle does not close R-work")

    measurements.append(
        row("work_n", "T03_r-work", "non_cctbx", "gemmi sfcalc", 0.16,
            provenance_ref="run:independent", evidence_refs=["raw/gemmi.json"])
    )
    dual = qds_emit.build_cross_tool_coverage("QDS_cov", measurements)
    work = next(item for item in dual["task_coverage"]
                if item["metric_definition_ref"] == "T03_r-work")
    _check(work["gap_status"].startswith(
        "dual-family coverage — agreement not evaluated"
    ), "mere dual-family presence does not imply agreement was checked")

    exact = row("work_exact", "T03_r-work", "cctbx", "phenix.fmodel", 0.15,
                subject_ref="artifact:A")
    legacy = row("work_legacy", "T03_r-work", "non_cctbx", "gemmi sfcalc", 0.16)
    selected = qds_emit.build_cross_tool_coverage(
        "QDS_cov", [exact, legacy], subject_ref="artifact:A"
    )["task_coverage"][0]
    _check(selected["gap_status"] == "open — cctbx only",
           "legacy other/unknown-subject oracle cannot close exact-subject coverage")
    print("PASS  test_metric_context_coverage_blocks_laundering")


def test_claim_scoped_waivers_are_unambiguous() -> None:
    rows = [
        {"id": "C1", "catalog_task_ref": "T05", "metric_definition_ref": "m1",
         "stage": "final", "scope": "complex", "cctbx_oracles": ["p"],
         "non_cctbx_oracles": [], "gap_status": "open — cctbx only"},
        {"id": "C2", "catalog_task_ref": "T05", "metric_definition_ref": "m2",
         "stage": "final", "scope": "complex", "cctbx_oracles": ["p"],
         "non_cctbx_oracles": [], "gap_status": "open — cctbx only"},
    ]
    qds = {"cross_tool_coverage": {"task_coverage": copy.deepcopy(rows)}}
    task_only = [{"id": "W", "catalog_task_ref": "T05", "reason": "x",
                  "as_of_date": "2026-09-21"}]
    assert_raises_completeness(
        lambda: qds_emit._check_trust_invariant(qds, task_only),
        ["task-only", "2 gated claims", "metric/context qualifiers"],
        "one task-level waiver laundered multiple claims",
    )
    qualified = [
        {"id": f"W{i}", "catalog_task_ref": "T05",
         "metric_definition_ref": f"m{i}", "stage": "final", "scope": "complex",
         "reason": "claim-specific", "as_of_date": "2026-09-21"}
        for i in (1, 2)
    ]
    qds = {"cross_tool_coverage": {"task_coverage": copy.deepcopy(rows)}}
    qds_emit._check_trust_invariant(qds, qualified)
    _check(all("WAIVED" in row["gap_status"]
               for row in qds["cross_tool_coverage"]["task_coverage"]),
           "unique claim-scoped waivers annotate their exact rows")
    print("PASS  test_claim_scoped_waivers_are_unambiguous")


def test_equal_priority_semantic_conflicts_fail() -> None:
    rows = [
        _measurement("status_pass", "T15_secondary_structure_agreement", 0.8),
        _measurement("status_fail", "T15_secondary_structure_agreement", 0.8),
        _measurement(
            "status_content", "T15_secondary_structure_content", 0.4, tool="DSSP"
        ),
    ]
    rows[0]["pass_status"] = "pass"
    rows[1]["pass_status"] = "fail_by_oracle"
    run = {
        "id": "EVAL_status", "structure_ref": "synth", "run_date": "2026-09-21",
        "catalog_tasks_applied": ["T15"], "measurements": rows,
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "status.yaml"
        _write_eval(path, [run])
        assert_raises_completeness(
            lambda: qds_emit.emit_qds(
                [path], qds_id="QDS_status", structure_id="synth",
                coverage_scope="cumulative",
            ),
            ["scientifically ambiguous", "status_pass", "status_fail"],
            "equal-priority values differed in pass status",
        )
    print("PASS  test_equal_priority_semantic_conflicts_fail")


def test_refinement_exact_subject_context_and_arithmetic() -> None:
    subject = "artifact:A"
    exact = [
        _measurement("exact_work", "T03_r-work", 0.16, subject=subject),
        _measurement("exact_free", "T03_r-free", 0.21, subject=subject),
    ]
    legacy = [
        _measurement("legacy_work", "T03_r-work", 0.15),
        _measurement("legacy_free", "T03_r-free", 0.20),
        _measurement("legacy_gap", "T03_r-free_r-work_gap", 0.05),
    ]
    run = {
        "id": "EVAL_exact", "structure_ref": "synth", "run_date": "2026-09-21",
        "catalog_tasks_applied": ["T03"], "measurements": exact + legacy,
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "exact.yaml"
        _write_eval(path, [run])
        qds = qds_emit.emit_qds(
            [path], qds_id="QDS_exact", structure_id="synth", subject_ref=subject,
            coverage_scope="cumulative",
            issued_at="2026-09-21T00:00:00+00:00",
        )
        refn = qds["refinement_summary"]
        _check(set(refn) == {"id", "r_work", "r_free"},
               "legacy gap cannot complete a partial exact-subject R bundle")

        mismatch = copy.deepcopy(run)
        mismatch["id"] = "EVAL_context"
        mismatch["measurements"] = exact
        mismatch["measurements"][0]["scope_selector"] = "mapping A"
        mismatch["measurements"][1]["scope_selector"] = "mapping B"
        _write_eval(path, [mismatch])
        assert_raises_completeness(
            lambda: qds_emit.emit_qds(
                [path], qds_id="QDS_context", structure_id="synth",
                subject_ref=subject, coverage_scope="cumulative",
            ),
            ["refinement-summary coherence", "scope/selector/provenance/reference"],
            "R values from different selectors were bundled",
        )

        bad_gap = copy.deepcopy(run)
        bad_gap["id"] = "EVAL_gap"
        bad_gap["measurements"] = [
            _measurement("gap_work", "T03_r-work", 0.16, subject=subject),
            _measurement("gap_free", "T03_r-free", 0.21, subject=subject),
            _measurement("gap_wrong", "T03_r-free_r-work_gap", 0.5, subject=subject),
        ]
        _write_eval(path, [bad_gap])
        assert_raises_completeness(
            lambda: qds_emit.emit_qds(
                [path], qds_id="QDS_gap", structure_id="synth",
                subject_ref=subject, coverage_scope="cumulative",
            ),
            ["arithmetic failed", "does not equal R-free"],
            "recorded R gap contradicted R-free minus R-work",
        )

        bad_units = copy.deepcopy(bad_gap)
        bad_units["id"] = "EVAL_units"
        bad_units["measurements"][2]["oracle_measure"] = {
            "value_numeric": 0.05, "unit": "%"
        }
        _write_eval(path, [bad_units])
        assert_raises_completeness(
            lambda: qds_emit.emit_qds(
                [path], qds_id="QDS_units", structure_id="synth",
                subject_ref=subject, coverage_scope="cumulative",
            ),
            ["arithmetic failed", "incompatible R-factor units"],
            "R bundle mixed fraction and percent units",
        )
    print("PASS  test_refinement_exact_subject_context_and_arithmetic")


def test_assumption_supersession_integrity_failures() -> None:
    cases = [
        ([{"id": "self", "assumptions": [{"id": "A"}],
           "superseded_assumption_refs": ["A"]}], "self-referential"),
        ([{"id": "first", "superseded_assumption_refs": ["A"]},
          {"id": "later", "assumptions": [{"id": "A"}]}], "future input run"),
        ([{"id": "dangling", "superseded_assumption_refs": ["missing"]}], "dangling"),
        ([{"id": "old", "assumptions": [{"id": "A"}]},
          {"id": "dup", "superseded_assumption_refs": ["A", "A"]}], "duplicate"),
    ]
    for runs, fragment in cases:
        assert_raises_completeness(
            lambda runs=runs: qds_emit.build_assumptions_report(runs),
            ["assumption-supersession integrity", fragment],
            f"invalid supersession ({fragment}) was accepted",
        )
    print("PASS  test_assumption_supersession_integrity_failures")


def test_immutable_output_allows_only_identical_noop() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "qds.yaml"
        _check(qds_emit._write_immutable_output(path, "first\n"),
               "new immutable output was not written")
        _check(not qds_emit._write_immutable_output(path, "first\n"),
               "identical output should be an explicit no-op")
        assert_raises_completeness(
            lambda: qds_emit._write_immutable_output(path, "changed\n"),
            ["already exists with different content", "immutable"],
            "an existing QDS was overwritten with different bytes",
        )
        _check(path.read_text() == "first\n", "failed overwrite mutated existing QDS")
    print("PASS  test_immutable_output_allows_only_identical_noop")


def test_emission_contract_requires_scope_notes_and_pinned_file_time() -> None:
    assert_raises_completeness(
        lambda: qds_emit._validate_cli_emission_contract(
            qds_id="QDS_scope", coverage_scope=None, scope_notes=None,
            output=None, issued_at=None,
        ),
        ["--coverage-scope is required"],
        "CLI emission omitted its coverage scope",
    )
    assert_raises_completeness(
        lambda: qds_emit._validate_cli_emission_contract(
            qds_id="QDS_scope", coverage_scope="partial", scope_notes=" ", output=None,
            issued_at="2026-09-21T00:00:00+00:00",
        ),
        ["partial requires non-empty --scope-notes"],
        "a partial CLI sheet omitted its boundary note",
    )
    assert_raises_completeness(
        lambda: qds_emit._validate_cli_emission_contract(
            qds_id="QDS_scope", coverage_scope="cumulative", scope_notes=None,
            output=Path("QDS_scope.yaml"), issued_at=None,
        ),
        ["--issued-at is required when --output is used"],
        "a file output used a dynamic issue timestamp",
    )
    qds_emit._validate_cli_emission_contract(
        qds_id="QDS_scope", coverage_scope="partial", scope_notes="T15/T16 only",
        output=Path("QDS_scope.yaml"), issued_at="2026-09-21T00:00:00+00:00",
    )

    run = {
        "id": "EVAL_scope", "structure_ref": "synth", "run_date": "2026-09-21",
        "catalog_tasks_applied": [], "measurements": [],
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "scope.yaml"
        _write_eval(path, [run])
        assert_raises_completeness(
            lambda: qds_emit.emit_qds(
                [path], qds_id="QDS_scope", structure_id="synth",
                coverage_scope="partial", scope_notes="",
            ),
            ["coverage_scope=partial", "non-empty scope_notes"],
            "programmatic partial sheet omitted its boundary note",
        )
    print("PASS  test_emission_contract_requires_scope_notes_and_pinned_file_time")


def test_non_results_cannot_populate_summary_slots() -> None:
    numeric = _measurement(
        "numeric", "T05_clashscore", 7.0, tool="phenix.validation"
    )
    numeric.pop("oracle_family")  # the emitter must derive cctbx from the catalog
    aborted = _measurement(
        "aborted", "T05_clashscore", 0.0, tool="MolProbity (gold)"
    )
    aborted["oracle_measure"] = {"value_text": "tool aborted before producing a score"}
    not_applicable = _measurement(
        "not_applicable", "T05_clashscore", 0.0, tool="MolProbity (gold)"
    )
    not_applicable["oracle_measure"] = {"is_not_applicable": True}
    run = {
        "id": "EVAL_non_results",
        "structure_ref": "synth",
        "run_date": "2026-09-21",
        "catalog_tasks_applied": ["T05"],
        "measurements": [aborted, not_applicable, numeric],
        "cross_tool_waivers": [
            {
                "id": "WAIVER_numeric_cctbx",
                "catalog_task_ref": "T05",
                "metric_definition_ref": "T05_clashscore",
                "stage": "final",
                "scope": "complex",
                "scope_selector": "whole model",
                "reason": "Synthetic test isolates summary-result selection.",
                "as_of_date": "2026-09-21",
            }
        ],
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "non_results.yaml"
        _write_eval(path, [run])
        qds = qds_emit.emit_qds(
            [path], qds_id="QDS_non_results", structure_id="synth",
            coverage_scope="cumulative",
        )
    clashscore = qds["geometry_summary"]["clashscore"]
    _check(clashscore["value_numeric"] == 7.0,
           "an aborted/empty non-cctbx attempt displaced a numeric result")
    _check(clashscore["oracle_family"] == "cctbx",
           "wrapped value did not carry the catalog-derived family")
    _check("aborted" not in clashscore,
           "aborted attempt leaked into the selected scalar")
    print("PASS  test_non_results_cannot_populate_summary_slots")


def test_typed_value_carriers_are_exactly_one() -> None:
    numeric = _measurement(
        "M_bad_numeric_carrier", "T05_clashscore", 7.0,
        tool="MolProbity (gold)", selector="whole model",
    )
    categorical = {
        "id": "M_bad_categorical_carrier",
        "catalog_task_ref": "T15",
        "stage": "final",
        "scope": "complex",
        "metric_definition_ref": "T15_fold_classification",
        "oracle_tool_ref": "DSSP",
        "oracle_family": "non_cctbx",
        "oracle_measure": {"value_text": "alpha/beta"},
        "pass_status": "informational",
    }

    cases: list[tuple[str, dict, str, object, list[str]]] = [
        (
            "numeric plus text", numeric, "oracle_measure",
            {"value_numeric": 7.0, "value_text": "also seven"},
            ["exactly one", "value_numeric", "value_text"],
        ),
        (
            "numeric plus N/A", numeric, "oracle_measure",
            {"value_numeric": 7.0, "is_not_applicable": True},
            ["exactly one", "is_not_applicable"],
        ),
        (
            "boolean numeric", numeric, "oracle_measure",
            {"value_numeric": True},
            ["finite non-boolean"],
        ),
        (
            "non-finite numeric", numeric, "oracle_measure",
            {"value_numeric": float("nan")},
            ["finite non-boolean"],
        ),
        (
            "false N/A", numeric, "oracle_measure",
            {"is_not_applicable": False},
            ["literal true", "exactly one"],
        ),
        (
            "missing carrier", numeric, "oracle_measure", {},
            ["exactly one"],
        ),
        (
            "null payload", numeric, "oracle_measure", None,
            ["must be an object"],
        ),
        (
            "blank text", categorical, "oracle_measure",
            {"value_text": "  \t"},
            ["non-empty string", "exactly one"],
        ),
        (
            "categorical plus N/A", categorical, "oracle_measure",
            {"value_text": "alpha/beta", "is_not_applicable": True},
            ["exactly one", "value_text", "is_not_applicable"],
        ),
        (
            "categorical plus non-finite numeric", categorical, "oracle_measure",
            {"value_text": "alpha/beta", "value_numeric": float("inf")},
            ["finite non-boolean"],
        ),
        (
            "dual-carrier agent claim", numeric, "agent_claim",
            {"value_numeric": 7.0, "value_text": "approximately seven"},
            ["agent_claim", "exactly one"],
        ),
        (
            "invalid delta N/A", numeric, "delta",
            {"is_not_applicable": False},
            ["delta", "literal true"],
        ),
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "typed_carriers.yaml"
        for label, template, field, payload, fragments in cases:
            measurement = copy.deepcopy(template)
            measurement[field] = payload
            run = {
                "id": f"EVAL_{label.replace(' ', '_')}",
                "structure_ref": "synth",
                "run_date": "2026-09-21",
                "catalog_tasks_applied": [measurement["catalog_task_ref"]],
                "measurements": [measurement],
            }
            _write_eval(path, [run])
            assert_raises_completeness(
                lambda: qds_emit.emit_qds(
                    [path], qds_id="QDS_bad_typed_carrier",
                    structure_id="synth", coverage_scope="cumulative",
                ),
                ["typed value-carrier", measurement["id"], *fragments],
                f"{label} was accepted",
            )

        missing_oracle = copy.deepcopy(numeric)
        missing_oracle.pop("oracle_measure")
        _write_eval(path, [{
            "id": "EVAL_missing_oracle_payload",
            "structure_ref": "synth",
            "run_date": "2026-09-21",
            "catalog_tasks_applied": ["T05"],
            "measurements": [missing_oracle],
        }])
        assert_raises_completeness(
            lambda: qds_emit.emit_qds(
                [path], qds_id="QDS_missing_oracle_payload",
                structure_id="synth", coverage_scope="cumulative",
            ),
            ["typed value-carrier", missing_oracle["id"],
             "oracle_measure", "typed oracle value is required"],
            "a routed/coverage measurement omitted oracle_measure",
        )

        structured_cases = (
            (
                "interface_qualities",
                {
                    "id": "IFACE_dual_carrier",
                    "structure_ref": "synth",
                    "dockq_score": {
                        "value_numeric": 0.9,
                        "value_text": "High-like score",
                    },
                },
                "dockq_score",
            ),
            (
                "pairwise_comparisons",
                {
                    "id": "PAIR_dual_carrier",
                    "candidate_ref": "synth",
                    "reference_ref": "native",
                    "reference_kind": "deposited_model",
                    "alignment_method": "synthetic",
                    "tm_score": {
                        "value_numeric": 0.9,
                        "is_not_applicable": True,
                    },
                },
                "tm_score",
            ),
        )
        for collection, row, field in structured_cases:
            _write_eval(path, [{
                "id": f"EVAL_bad_{collection}",
                "structure_ref": "synth",
                "run_date": "2026-09-21",
                "catalog_tasks_applied": [],
                "measurements": [],
                collection: [row],
            }])
            assert_raises_completeness(
                lambda: qds_emit.emit_qds(
                    [path], qds_id=f"QDS_bad_{collection}",
                    structure_id="synth", coverage_scope="cumulative",
                ),
                ["typed value-carrier", collection, row["id"], field, "exactly one"],
                f"a copied {collection} row carried a dual {field} value",
            )
    print("PASS  test_typed_value_carriers_are_exactly_one")


def test_label_verdicts_and_cross_family_disagreements_fail() -> None:
    categorical = {
        "id": "M_categorical_verdict",
        "catalog_task_ref": "T15",
        "stage": "final",
        "scope": "complex",
        "metric_definition_ref": "T15_fold_classification",
        "oracle_tool_ref": "phenix.validation",
        "oracle_family": "cctbx",
        "oracle_measure": {"value_text": "alpha/beta"},
        "pass_criterion": "must be alpha/beta",
        "pass_status": "pass",
    }
    run = {
        "id": "EVAL_categorical_verdict",
        "structure_ref": "synth",
        "run_date": "2026-09-21",
        "catalog_tasks_applied": ["T15"],
        "measurements": [categorical],
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "categorical.yaml"
        _write_eval(path, [run])
        assert_raises_completeness(
            lambda: qds_emit.emit_qds(
                [path], qds_id="QDS_categorical", structure_id="synth",
                coverage_scope="cumulative",
            ),
            ["label-valued", "pass_status=informational"],
            "a cctbx-only categorical pass bypassed the trust model",
        )

        for payload in (
            {"value_numeric": 1.0},
            {"value_numeric": 1.0, "value_text": "alpha/beta"},
        ):
            categorical["oracle_measure"] = payload
            _write_eval(path, [run])
            expected = (
                ["typed value-carrier", "exactly one", "value_numeric", "value_text"]
                if "value_text" in payload
                else ["label-valued", "value_text only", "value_numeric"]
            )
            assert_raises_completeness(
                lambda: qds_emit.emit_qds(
                    [path], qds_id="QDS_categorical_numeric",
                    structure_id="synth", coverage_scope="cumulative",
                ),
                expected,
                f"categorical payload {payload!r} escaped through the numeric path",
            )

        cctbx = _measurement(
            "M_cctbx_fail", "T05_clashscore", 100.0,
            tool="phenix.validation", selector="whole model",
        )
        cctbx["oracle_family"] = "cctbx"
        cctbx["pass_status"] = "fail_by_oracle"
        independent = _measurement(
            "M_independent_pass", "T05_clashscore", 1.0,
            tool="MolProbity (gold)", selector="whole model",
        )
        independent["pass_status"] = "pass"
        run.update({
            "id": "EVAL_cross_family_disagreement",
            "catalog_tasks_applied": ["T05"],
            "measurements": [cctbx, independent],
        })
        _write_eval(path, [run])
        assert_raises_completeness(
            lambda: qds_emit.emit_qds(
                [path], qds_id="QDS_disagreement", structure_id="synth",
                coverage_scope="cumulative",
            ),
            ["contradictory cctbx/non-cctbx", "tiebreaker"],
            "opposite cross-family verdicts were silently reported as coverage",
        )
    print("PASS  test_label_verdicts_and_cross_family_disagreements_fail")


def test_t15_content_agreement_is_one_governed_bundle() -> None:
    def agreement(mid: str, *, status: str = "informational") -> dict:
        row = _measurement(mid, "T15_secondary_structure_agreement", 0.99)
        row["pass_status"] = status
        return row

    def content(mid: str, value: float, *, status: str = "informational") -> dict:
        row = _measurement(
            mid, "T15_secondary_structure_content", value, tool="DSSP"
        )
        row["pass_status"] = status
        if status != "informational":
            row["pass_criterion"] = "DSSP H+E content >= 0.20"
        return row

    def run(run_id: str, rows: list[dict]) -> dict:
        return {
            "id": run_id,
            "structure_ref": "synth",
            "run_date": "2026-09-21",
            "catalog_tasks_applied": ["T15"],
            "measurements": rows,
        }

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "t15.yaml"
        _write_eval(path, [run("EVAL_content_only", [content("content", 0.10)])])
        content_only_qds = qds_emit.emit_qds(
            [path], qds_id="QDS_t15_content_only", structure_id="synth",
            coverage_scope="cumulative",
        )
        content_only = content_only_qds["classification_summary"][
            "secondary_structure_content"
        ]
        _check(
            content_only["value_numeric"] == 0.10
            and content_only["pass_status"] == "informational"
            and "pass_criterion" not in content_only,
            "valid content-only T15 evidence remains informational below 0.20",
        )

        _write_eval(path, [run(
            "EVAL_graded_content_only",
            [content("content", 0.40, status="pass")],
        )])
        assert_raises_completeness(
            lambda: qds_emit.emit_qds(
                [path], qds_id="QDS_t15_graded_content_only", structure_id="synth",
                coverage_scope="cumulative",
            ),
            ["T15", "content diagnostic", "non-gradeable", "informational"],
            "a gradeable-looking content-only T15 row bypassed bundle validation",
        )

        criterion_only = content("criterion_only", 0.40)
        criterion_only["pass_criterion"] = "DSSP H+E content >= 0.20"
        _write_eval(path, [run("EVAL_content_criterion_only", [criterion_only])])
        assert_raises_completeness(
            lambda: qds_emit.emit_qds(
                [path], qds_id="QDS_t15_content_criterion_only", structure_id="synth",
                coverage_scope="cumulative",
            ),
            ["T15 content-only row", "content diagnostic", "pass_criterion"],
            "an informational content-only T15 row retained a pass criterion",
        )

        _write_eval(path, [run("EVAL_content_out_of_range", [
            content("content", 1.01)
        ])])
        assert_raises_completeness(
            lambda: qds_emit.emit_qds(
                [path], qds_id="QDS_t15_content_out_of_range", structure_id="synth",
                coverage_scope="cumulative",
            ),
            ["T15", "content diagnostic", "[0, 1]"],
            "an out-of-range content-only T15 fraction was routed",
        )

        _write_eval(path, [run("EVAL_agreement_only", [agreement("agreement")])])
        assert_raises_completeness(
            lambda: qds_emit.emit_qds(
                [path], qds_id="QDS_t15_missing", structure_id="synth",
                coverage_scope="cumulative",
            ),
            ["T15 coherence", "requires a content-diagnostic measurement", "same run"],
            "T15 agreement emitted without its content diagnostic",
        )

        _write_eval(
            path,
            [
                run("EVAL_agreement", [agreement("agreement")]),
                run("EVAL_unrelated_content", [content("content", 0.40)]),
            ],
        )
        assert_raises_completeness(
            lambda: qds_emit.emit_qds(
                [path], qds_id="QDS_t15_mixed", structure_id="synth",
                coverage_scope="cumulative",
            ),
            ["T15 coherence", "same run"],
            "T15 content and agreement from unrelated runs were mixed",
        )

        graded_agreement = agreement("agreement", status="pass")
        graded_agreement["pass_criterion"] = "agreement >= 0.65"
        _write_eval(path, [run("EVAL_invalid_agreement_grade", [
            graded_agreement,
            content("content", 0.40),
        ])])
        assert_raises_completeness(
            lambda: qds_emit.emit_qds(
                [path], qds_id="QDS_t15_failed", structure_id="synth",
                coverage_scope="cumulative",
            ),
            ["T15 bundle is inconsistent", "non-gradeable", "informational"],
            "a provisional T15 oracle-pair agreement was graded",
        )

        _write_eval(path, [run("EVAL_invalid_content_grade", [
            agreement("agreement"),
            content("content", 0.40, status="pass"),
        ])])
        assert_raises_completeness(
            lambda: qds_emit.emit_qds(
                [path], qds_id="QDS_t15_content_grade", structure_id="synth",
                coverage_scope="cumulative",
            ),
            ["T15 bundle is inconsistent", "content", "non-gradeable", "informational"],
            "the provisional T15 content diagnostic was graded",
        )

        _write_eval(
            path,
            [run("EVAL_consistent", [agreement("agreement"),
                                      content("content", 0.10)])],
        )
        qds = qds_emit.emit_qds(
            [path], qds_id="QDS_t15_consistent", structure_id="synth",
            coverage_scope="cumulative",
        )
        summary = qds["classification_summary"]
        sources = {
            summary[slot]["source_evaluation_run_ref"]
            for slot in ("secondary_structure_content", "secondary_structure_agreement")
        }
        _check(sources == {"EVAL_consistent"},
               "T15 summary did not retain one coherent source bundle")
        _check(
            summary["secondary_structure_content"]["value_numeric"] == 0.10
            and summary["secondary_structure_content"]["pass_status"] == "informational"
            and "pass_criterion" not in summary["secondary_structure_content"],
            "low T15 content remained an informational interpretability diagnostic",
        )

        mismatched_agreement = agreement("agreement_mismatched_bundle")
        mismatched_content = content("content_mismatched_bundle", 0.40)
        mismatched_agreement["bundle_ref"] = "bundle:agreement-invocation"
        mismatched_content["bundle_ref"] = "bundle:content-from-other-invocation"
        mismatched_agreement["provenance_ref"] = "run:dssp-on-A"
        mismatched_content["provenance_ref"] = "run:agreement-on-B"
        _write_eval(
            path,
            [run("EVAL_mismatched_bundle", [mismatched_agreement, mismatched_content])],
        )
        assert_raises_completeness(
            lambda: qds_emit.emit_qds(
                [path], qds_id="QDS_t15_mismatched_bundle", structure_id="synth",
                coverage_scope="cumulative",
            ),
            ["T15 coherence", "same run"],
            "T15 rows from different invocations were accepted as one bundle",
        )
    print("PASS  test_t15_content_agreement_is_one_governed_bundle")


def test_t16_interface_summary_is_one_consistent_bundle() -> None:
    def numeric(mid: str, metric: str, value: float, tool: str,
                selector: str, reference: str | None = None,
                evidence: str | None = None) -> dict:
        row = _measurement(mid, metric, value, tool=tool, selector=selector)
        row["scope"] = "interface"
        if reference is not None:
            row["reference_subject_ref"] = reference
        if evidence is not None:
            row["evidence_refs"] = [evidence]
        return row

    def capri(mid: str, label: str, selector: str, reference: str,
              evidence: str) -> dict:
        row = numeric(
            mid, "T16_capri_interface_quality_class", 0.0, "DockQ",
            selector, reference, evidence,
        )
        row["oracle_measure"] = {"value_text": label}
        return row

    def run(rows: list[dict], interfaces: list[dict] | None = None) -> dict:
        return {
            "id": "EVAL_t16",
            "structure_ref": "synth",
            "run_date": "2026-09-21",
            "catalog_tasks_applied": ["T16"],
            "measurements": rows,
            "interface_qualities": interfaces or [],
        }

    def interface(
        selector: str,
        reference: str,
        evidence: str | list[str],
        *,
        bsa_value: float | None = None,
        dockq_value: float | None = None,
        capri_value: str | None = None,
    ) -> dict:
        row = {
            "id": selector,
            "structure_ref": "synth",
            "reference_subject_ref": reference,
            "model_to_native_chain_mapping": "AB:AB",
            "evidence_refs": (
                list(evidence) if isinstance(evidence, list) else [evidence]
            ),
        }
        if bsa_value is not None:
            row["buried_surface_area"] = {
                "value_numeric": bsa_value,
            }
        if dockq_value is not None:
            row["dockq_score"] = {"value_numeric": dockq_value}
        if capri_value is not None:
            row["capri_quality_class"] = {"value_text": capri_value}
        return row

    bsa = numeric(
        "bsa", "T16_interface_buried_surface_area", 500.0,
        "biotite SASA", "IFACE_AB", evidence="raw:bsa",
    )
    dockq = numeric(
        "dockq", "T16_interface_dockq_score", 0.95,
        "DockQ", "IFACE_CD", "native:1", "raw:cd",
    )
    wrong_interface_capri = capri(
        "capri", "High", "IFACE_EF", "native:2", "raw:ef"
    )
    mixed_interfaces = [
        interface("IFACE_AB", "native:1", "raw:bsa", bsa_value=500.0),
        interface("IFACE_CD", "native:1", "raw:cd", dockq_value=0.95),
        interface("IFACE_EF", "native:2", "raw:ef", capri_value="High"),
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "t16.yaml"
        _write_eval(
            path, [run([bsa, dockq, wrong_interface_capri], mixed_interfaces)]
        )
        assert_raises_completeness(
            lambda: qds_emit.emit_qds(
                [path], qds_id="QDS_t16_mixed", structure_id="synth",
                coverage_scope="cumulative",
            ),
            ["T16 coherence", "no single run/subject/interface",
             "reference/mapping/evidence"],
            "unrelated interfaces/references were synthesized into one T16 summary",
        )

        dockq_same = copy.deepcopy(dockq)
        dockq_same["scope_selector"] = "IFACE_AB"
        capri_wrong = capri(
            "capri", "Incorrect", "IFACE_AB", "native:1", "raw:cd"
        )
        identity_interface = [interface(
            "IFACE_AB", "native:1", ["raw:cd", "raw:bsa"],
            bsa_value=500.0, dockq_value=0.95, capri_value="Incorrect",
        )]
        _write_eval(
            path, [run([bsa, dockq_same, capri_wrong], identity_interface)]
        )
        assert_raises_completeness(
            lambda: qds_emit.emit_qds(
                [path], qds_id="QDS_t16_capri", structure_id="synth",
                coverage_scope="cumulative",
            ),
            ["CAPRI consistency failed", "DockQ 0.95", "high", "Incorrect"],
            "CAPRI class contradicted the selected DockQ score",
        )

        capri_high = capri("capri", "High", "IFACE_AB", "native:1", "raw:cd")
        interfaces = [interface(
            "IFACE_AB", "native:1", ["raw:cd", "raw:bsa"],
            bsa_value=500.0, dockq_value=0.95, capri_value="High",
        )]
        for field, wrong_payload in (
            ("buried_surface_area", {"value_numeric": 999.0}),
            ("dockq_score", {"value_numeric": 0.01}),
            ("capri_quality_class", {"value_text": "Incorrect"}),
        ):
            contradictory_interfaces = copy.deepcopy(interfaces)
            contradictory_interfaces[0][field] = wrong_payload
            _write_eval(
                path,
                [run([bsa, dockq_same, capri_high], contradictory_interfaces)],
            )
            assert_raises_completeness(
                lambda: qds_emit.emit_qds(
                    [path], qds_id=f"QDS_t16_payload_{field}", structure_id="synth",
                    coverage_scope="cumulative",
                ),
                ["T16 interface-context integrity failed", "oracle_measure",
                 "does not exactly match", field],
                f"a T16 scalar contradicted InterfaceQuality.{field}",
            )
        missing_bsa_evidence = copy.deepcopy(bsa)
        missing_bsa_evidence.pop("evidence_refs")
        _write_eval(
            path,
            [run([missing_bsa_evidence, dockq_same, capri_high], interfaces)],
        )
        assert_raises_completeness(
            lambda: qds_emit.emit_qds(
                [path], qds_id="QDS_t16_bsa_no_evidence", structure_id="synth",
                coverage_scope="cumulative",
            ),
            ["T16 interface-context integrity failed", "bsa", "no retained",
             "evidence_refs"],
            "a BSA scalar had no retained evidence",
        )
        bsa_evidence_not_retained = copy.deepcopy(interfaces)
        bsa_evidence_not_retained[0]["evidence_refs"] = ["raw:cd"]
        _write_eval(
            path,
            [run([bsa, dockq_same, capri_high], bsa_evidence_not_retained)],
        )
        assert_raises_completeness(
            lambda: qds_emit.emit_qds(
                [path], qds_id="QDS_t16_bsa_evidence_not_retained",
                structure_id="synth", coverage_scope="cumulative",
            ),
            ["T16 interface-context integrity failed", "bsa", "evidence_refs",
             "not retained"],
            "a structured row omitted the BSA scalar's evidence",
        )
        _write_eval(path, [run([bsa, dockq_same, capri_high], interfaces)])
        qds = qds_emit.emit_qds(
            [path], qds_id="QDS_t16_consistent", structure_id="synth",
            coverage_scope="cumulative",
        )
        summary = qds["interface_quality_summary"]
        _check(
            summary["interface_dockq_score"]["scope_selector"]
            == summary["capri_interface_quality_class"]["scope_selector"]
            == "IFACE_AB",
            "T16 comparison rows did not retain one interface mapping",
        )

        half_labelled_rows = copy.deepcopy([bsa, dockq_same, capri_high])
        for row in half_labelled_rows:
            row["subject_ref"] = "artifact:model"
        _write_eval(path, [run(half_labelled_rows, interfaces)])
        assert_raises_completeness(
            lambda: qds_emit.emit_qds(
                [path], qds_id="QDS_t16_half_labelled", structure_id="synth",
                subject_ref="artifact:model", coverage_scope="cumulative",
            ),
            ["T16 interface-context integrity failed", "subject_ref",
             "does not exactly match", "interface=None"],
            "a subject-bound T16 scalar was paired with an unlabelled InterfaceQuality",
        )

        half_labelled_interfaces = copy.deepcopy(interfaces)
        half_labelled_interfaces[0]["subject_ref"] = "artifact:model"
        _write_eval(
            path,
            [run(copy.deepcopy([bsa, dockq_same, capri_high]), half_labelled_interfaces)],
        )
        assert_raises_completeness(
            lambda: qds_emit.emit_qds(
                [path], qds_id="QDS_t16_inverse_half_labelled",
                structure_id="synth", subject_ref="artifact:model",
                coverage_scope="cumulative",
            ),
            ["T16 interface-context integrity failed", "subject_ref",
             "does not exactly match", "measurement=None"],
            "an unlabelled T16 scalar was paired with a subject-bound InterfaceQuality",
        )
    print("PASS  test_t16_interface_summary_is_one_consistent_bundle")


def test_programmatic_source_admission_contract() -> None:
    base = {
        "id": "EVAL_source",
        "structure_ref": "synth",
        "run_date": "2026-09-21",
        "catalog_tasks_applied": [],
        "measurements": [],
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "source.yaml"
        _write_eval(path, [base])
        assert_raises_completeness(
            lambda: qds_emit.emit_qds(
                [path], qds_id="QDS_no_scope", structure_id="synth"
            ),
            ["coverage_scope is required"],
            "the API omitted its coverage scope",
        )
        assert_raises_completeness(
            lambda: qds_emit.emit_qds(
                [path, path], qds_id="QDS_duplicate_run", structure_id="synth",
                coverage_scope="cumulative",
            ),
            ["source-run integrity", "duplicate input EvaluationRun id", "EVAL_source"],
            "the same source run was admitted twice",
        )

        missing = copy.deepcopy(base)
        missing.pop("id")
        _write_eval(path, [missing])
        assert_raises_completeness(
            lambda: qds_emit.emit_qds(
                [path], qds_id="QDS_missing_run", structure_id="synth",
                coverage_scope="cumulative",
            ),
            ["source-run integrity", "has no id"],
            "an input EvaluationRun had no stable id",
        )

        mismatched = copy.deepcopy(base)
        mismatched["structure_ref"] = "other"
        _write_eval(path, [mismatched])
        assert_raises_completeness(
            lambda: qds_emit.emit_qds(
                [path], qds_id="QDS_wrong_structure", structure_id="synth",
                coverage_scope="cumulative",
            ),
            ["source-run integrity", "structure_ref 'other'",
             "requested structure_id 'synth'"],
            "a source run for another structure was admitted",
        )

    assert_raises_completeness(
        lambda: qds_emit._validate_cli_emission_contract(
            qds_id="QDS_named", coverage_scope="cumulative", scope_notes=None,
            output=Path("not_discoverable.yaml"),
            issued_at="2026-09-21T00:00:00+00:00",
        ),
        ["output filename must be exactly QDS_named.yaml", "discovery"],
        "a repository QDS could escape the QDS_ filename convention",
    )
    print("PASS  test_programmatic_source_admission_contract")


def test_structure_identity_comes_from_pinned_eval_source() -> None:
    run = {
        "id": "EVAL_identity_source",
        "structure_ref": "synth",
        "run_date": "2026-09-22",
        "catalog_tasks_applied": [],
        "measurements": [],
    }
    structure = {
        "id": "synth",
        "id_kind": "pdb",
        "method": "xray",
        "resolution_a": 2.0,
        "space_group": "P 1",
        "description": "Pinned source description.",
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "source.yaml"
        path.write_text(
            yaml.safe_dump(
                {"structures": [structure], "evaluation_runs": [run]},
                sort_keys=False,
            )
        )
        qds = qds_emit.emit_qds(
            [path],
            qds_id="QDS_identity_source",
            structure_id="synth",
            coverage_scope="cumulative",
            issued_at="2026-09-22T00:00:00+00:00",
        )
        _check(
            qds["identity_block"]
            == {
                "id": "QDS_identity_source_identity",
                "pdb_id": "synth",
                "method": "xray",
                "resolution_a": 2.0,
                "space_group": "P 1",
                "description": "Pinned source description.",
            },
            "identity metadata was not derived exactly from the input Structure",
        )

        assert_raises_completeness(
            lambda: qds_emit.emit_qds(
                [path],
                qds_id="QDS_identity_method_conflict",
                structure_id="synth",
                structure_method="nmr",
                coverage_scope="cumulative",
            ),
            ["structure identity source failed", "method", "nmr", "xray"],
            "an explicit method overrode the pinned Structure source",
        )
        assert_raises_completeness(
            lambda: qds_emit.emit_qds(
                [path],
                qds_id="QDS_identity_description_conflict",
                structure_id="synth",
                structure_description="QDS-only replacement.",
                coverage_scope="cumulative",
            ),
            [
                "structure identity source failed",
                "description",
                "QDS-only replacement.",
                "Pinned source description.",
            ],
            "an explicit description overrode the pinned Structure source",
        )
    print("PASS  test_structure_identity_comes_from_pinned_eval_source")


def main() -> int:
    test_coverage_never_claims_an_absent_family()
    test_derived_coverage_uses_only_validated_source_families()
    test_contract_v2_replays_full_september_eval_and_preserves_v1()
    test_1sar_geometry_slots_all_present()
    test_synth_local_blocks_present()
    test_negative_site_scope_without_site_decl_fails()
    test_negative_unknown_site_selector_fails()
    test_negative_unknown_ligand_selector_fails()
    test_negative_missing_ligand_declaration_fails()
    test_negative_duplicate_site_and_ligand_ids_fail()
    test_negative_mixed_valid_and_unconsumed_scoped_measurements_fail()
    test_quality_indicator_extensions_present()
    test_negative_structured_scopes_without_rows_fail()
    test_trust_invariant_waiver_mechanics()
    test_subject_selection_preserves_provenance_and_is_order_independent()
    test_refinement_triple_is_one_code_path()
    test_superseded_assumptions_are_not_republished()
    test_explicit_assumption_registry_snapshot_is_applied()
    test_pinned_source_snapshots_deduplicate_and_reject_conflicts()
    test_registry_snapshots_exclude_future_rows()
    test_subject_inference_includes_structured_rows_and_rejects_typos()
    test_subject_filter_reaches_every_downstream_builder()
    test_subject_filter_covers_every_structured_row_family()
    test_metric_context_coverage_blocks_laundering()
    test_claim_scoped_waivers_are_unambiguous()
    test_equal_priority_semantic_conflicts_fail()
    test_refinement_exact_subject_context_and_arithmetic()
    test_assumption_supersession_integrity_failures()
    test_immutable_output_allows_only_identical_noop()
    test_emission_contract_requires_scope_notes_and_pinned_file_time()
    test_non_results_cannot_populate_summary_slots()
    test_typed_value_carriers_are_exactly_one()
    test_label_verdicts_and_cross_family_disagreements_fail()
    test_t15_content_agreement_is_one_governed_bundle()
    test_t16_interface_summary_is_one_consistent_bundle()
    test_programmatic_source_admission_contract()
    test_structure_identity_comes_from_pinned_eval_source()
    print("\nall qds_emit regression tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
