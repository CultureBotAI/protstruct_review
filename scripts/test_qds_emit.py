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
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import qds_emit  # noqa: E402


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
    agreement = next(
        row
        for row in run["measurements"]
        if row.get("metric_definition_ref") == "T15_secondary_structure_agreement"
    )
    content = copy.deepcopy(agreement)
    content.update(
        {
            "id": "EVAL_synth_quality_indicators_2026-05-04_M_010a",
            "metric_definition_ref": "T15_secondary_structure_content",
            "oracle_tool_ref": "DSSP",
            "oracle_measure": {"value_numeric": 0.40, "unit": "fraction"},
            "notes": "Synthetic DSSP H+E content for the governed T15 gate.",
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
    for interface in run.get("interface_qualities", []) or []:
        if (interface.get("dockq_score") or {}).get("value_numeric") == 0.73:
            interface["capri_quality_class"] = {"value_text": "Medium"}
            interface["reference_subject_ref"] = "native:synth_quality"
            interface["model_to_native_chain_mapping"] = "AB:AB"
            interface["evidence_refs"] = ["raw:synth_quality_dockq"]
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
           "secondary_structure_agreement (the gradeable T15 metric) missing from classification_summary")
    ssa = cls.get("secondary_structure_agreement") or {}
    _check(ssa.get("value_numeric") is not None,
           "secondary_structure_agreement must carry a numeric value — it is the gradeable T15 metric")
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
    empty = _measurement(
        "empty", "T05_clashscore", 0.0, tool="MolProbity (gold)"
    )
    empty["oracle_measure"] = {}
    run = {
        "id": "EVAL_non_results",
        "structure_ref": "synth",
        "run_date": "2026-09-21",
        "catalog_tasks_applied": ["T05"],
        "measurements": [aborted, empty, numeric],
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


def test_t15_content_agreement_is_one_governed_bundle() -> None:
    def agreement(mid: str, *, status: str = "pass") -> dict:
        row = _measurement(mid, "T15_secondary_structure_agreement", 0.99)
        row["pass_status"] = status
        return row

    def content(mid: str, value: float, *, status: str) -> dict:
        row = _measurement(
            mid, "T15_secondary_structure_content", value, tool="DSSP"
        )
        row["pass_status"] = status
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
        _write_eval(path, [run("EVAL_agreement_only", [agreement("agreement")])])
        assert_raises_completeness(
            lambda: qds_emit.emit_qds(
                [path], qds_id="QDS_t15_missing", structure_id="synth",
                coverage_scope="cumulative",
            ),
            ["T15 coherence", "requires a content-gate measurement", "same run"],
            "T15 agreement emitted without its content gate",
        )

        _write_eval(
            path,
            [
                run("EVAL_agreement", [agreement("agreement")]),
                run("EVAL_unrelated_content", [content("content", 0.40, status="pass")]),
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

        _write_eval(
            path,
            [run("EVAL_failed_gate", [agreement("agreement"),
                                       content("content", 0.10, status="fail_by_oracle")])],
        )
        assert_raises_completeness(
            lambda: qds_emit.emit_qds(
                [path], qds_id="QDS_t15_failed", structure_id="synth",
                coverage_scope="cumulative",
            ),
            ["T15 bundle is inconsistent", "below the governed 0.20 gate"],
            "a passing T15 agreement bypassed its failed content gate",
        )

        _write_eval(
            path,
            [run("EVAL_consistent", [agreement("agreement"),
                                      content("content", 0.40, status="pass")])],
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

    def interface(selector: str, reference: str, evidence: str) -> dict:
        return {
            "id": selector,
            "structure_ref": "synth",
            "reference_subject_ref": reference,
            "model_to_native_chain_mapping": "AB:AB",
            "evidence_refs": [evidence],
        }

    bsa = numeric(
        "bsa", "T16_interface_buried_surface_area", 500.0,
        "biotite SASA", "IFACE_AB",
    )
    dockq = numeric(
        "dockq", "T16_interface_dockq_score", 0.95,
        "DockQ", "IFACE_CD", "native:1", "raw:cd",
    )
    wrong_interface_capri = capri(
        "capri", "High", "IFACE_EF", "native:2", "raw:ef"
    )
    mixed_interfaces = [
        interface("IFACE_AB", "native:1", "raw:ab"),
        interface("IFACE_CD", "native:1", "raw:cd"),
        interface("IFACE_EF", "native:2", "raw:ef"),
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
        identity_interface = [interface("IFACE_AB", "native:1", "raw:cd")]
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
        interfaces = identity_interface
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


def main() -> int:
    test_coverage_never_claims_an_absent_family()
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
    test_t15_content_agreement_is_one_governed_bundle()
    test_t16_interface_summary_is_one_consistent_bundle()
    test_programmatic_source_admission_contract()
    print("\nall qds_emit regression tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
