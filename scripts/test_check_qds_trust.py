#!/usr/bin/env python3
"""Regression tests for source-derived committed-QDS trust enforcement."""
from __future__ import annotations

import copy
import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

import yaml

import qds_emit
import qds_emit_contract_v1
import qds_emit_contract_v2
import qds_emit_contract_v3
import check_qds_trust_invariant as trust_guard


REPO = Path(__file__).resolve().parent.parent
GUARD = REPO / "scripts" / "check_qds_trust_invariant.py"
PASSED = 0


def snapshot_digest(key: str, rows: list[dict[str, Any]]) -> str:
    payload = yaml.safe_dump(
        {key: rows}, sort_keys=True, allow_unicode=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def check(label: str, got: Any, want: Any) -> None:
    global PASSED
    if got != want:
        print(f"FAIL  {label}: got {got!r}, want {want!r}")
        sys.exit(1)
    PASSED += 1
    print(f"PASS  {label}")


def run_guard(root: Path) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(GUARD), "--root", str(root)],
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout + proc.stderr


def oracle_measurement(
    row_id: str,
    tool: str,
    family: str,
    metric: str = "T06_r-free",
) -> dict[str, Any]:
    return {
        "id": row_id,
        "catalog_task_ref": "T06",
        "metric_definition_ref": metric,
        "oracle_tool_ref": tool,
        "oracle_family": family,
        "oracle_measure": {"value_numeric": 0.2},
        "stage": "final",
        "scope": "complex",
        "subject_ref": "artifact:test-model",
    }


def waiver() -> dict[str, Any]:
    return {
        "id": "WAIVER_T06",
        "catalog_task_ref": "T06",
        "reason": "no independent route in this fixture",
        "as_of_date": "2026-09-22",
        "metric_definition_ref": "T06_r-free",
        "subject_ref": "artifact:test-model",
        "stage": "final",
        "scope": "complex",
    }


def write_catalog(root: Path) -> None:
    ref_dir = root / "ref"
    ref_dir.mkdir(parents=True, exist_ok=True)
    for filename in (
        "catalog.yaml",
        "tool_recommendations.yaml",
        "tool_assumptions.yaml",
    ):
        shutil.copy2(REPO / "ref" / filename, ref_dir / filename)


def write_fixture(
    root: Path,
    measurements: list[dict[str, Any]],
    *,
    issued_at: str = "2026-09-22T12:00:00+00:00",
    waivers: list[dict[str, Any]] | None = None,
    mutate_qds: Callable[[dict[str, Any]], None] | None = None,
    coverage_scope: str = "cumulative",
    scope_notes: str | None = None,
    with_context: bool = False,
    contract_version: str = qds_emit.QDS_EMITTER_CONTRACT_VERSION,
) -> tuple[Path, Path]:
    write_catalog(root)
    eval_run = {
        "id": "EVAL_fixture",
        "eval_filename_stem": "EVAL_fixture",
        "structure_ref": "1abc",
        "run_date": "2026-09-22",
        "catalog_tasks_applied": sorted(
            {
                str(row.get("catalog_task_ref"))
                for row in measurements
                if row.get("catalog_task_ref")
            }
        ),
        "measurements": copy.deepcopy(measurements),
    }
    if waivers:
        eval_run["cross_tool_waivers"] = copy.deepcopy(waivers)
    catalog_doc = yaml.safe_load((root / "ref" / "catalog.yaml").read_text())
    used_tools = {
        str(row.get("oracle_tool_ref"))
        for row in measurements
        if row.get("oracle_tool_ref")
    }
    tool_snapshot = [
        copy.deepcopy(tool)
        for tool in catalog_doc.get("tools", []) or []
        if tool.get("id") in used_tools
    ]
    eval_path = root / "data" / "x" / "EVAL_fixture.yaml"
    eval_path.parent.mkdir(parents=True, exist_ok=True)
    source_document = {
        "structures": [
            {
                "id": "1abc",
                "id_kind": "pdb",
                "method": "xray",
                "description": "Pinned fixture structure.",
            }
        ],
        "tools": tool_snapshot,
        "evaluation_runs": [eval_run],
    }
    if with_context:
        source_document["qds_emission_contexts"] = [{
            "id": "QDS_fixture_emission_context",
            "qds_ref": "QDS_fixture",
            "owner_evaluation_run_ref": "EVAL_fixture",
            "structure_ref": "1abc",
            "subject_ref": "artifact:test-model",
            "source_evaluation_run_refs": ["EVAL_fixture"],
            "issued_at": issued_at,
            "coverage_scope": coverage_scope,
            "scope_notes": scope_notes,
            "identity_description": "Pinned fixture context identity.",
            "headline_verdict": "Pinned fixture context headline.",
        }]
    measured_ids = {
        str(row.get("metric_definition_ref"))
        for row in measurements
        if row.get("metric_definition_ref")
    }
    recommendations_doc = yaml.safe_load(
        (root / "ref" / "tool_recommendations.yaml").read_text()
    ) or {}
    source_document["tool_recommendations"] = [
        copy.deepcopy(row)
        for row in recommendations_doc.get("tool_recommendations", []) or []
        if row.get("metric_definition_ref") in measured_ids
    ]
    assumptions_doc = yaml.safe_load(
        (root / "ref" / "tool_assumptions.yaml").read_text()
    ) or {}
    source_document["assumptions"] = [
        copy.deepcopy(row)
        for row in assumptions_doc.get("assumptions", []) or []
        if row.get("tool_ref") in used_tools
    ]
    eval_path.write_text(yaml.safe_dump(source_document, sort_keys=False))

    old_catalog = qds_emit.CATALOG_PATH
    old_recommendations = qds_emit.TOOL_RECS_PATH
    old_assumptions = qds_emit.TOOL_ASSUMPTIONS_PATH
    qds_emit.CATALOG_PATH = root / "ref" / "catalog.yaml"
    qds_emit.TOOL_RECS_PATH = root / "ref" / "tool_recommendations.yaml"
    qds_emit.TOOL_ASSUMPTIONS_PATH = root / "ref" / "tool_assumptions.yaml"
    try:
        try:
            qds = qds_emit.emit_qds(
                [eval_path],
                qds_id="QDS_fixture",
                structure_id="1abc",
                subject_ref="artifact:test-model",
                coverage_scope=coverage_scope,
                scope_notes=scope_notes,
                issued_at=issued_at,
                emitter_contract_version=contract_version,
            )
        except qds_emit.QdsCompletenessError:
            # Some tests deliberately construct an invalid source (for example
            # an unwaived cctbx-only claim or a partial sheet without notes).
            # Give the committed guard that invalid artifact to diagnose; valid
            # fixtures use the canonical emitter so the source-owned byte pin is
            # grounded in a real emission even for deliberately invalid inputs.
            coverage = qds_emit.build_cross_tool_coverage(
                "QDS_fixture", copy.deepcopy(measurements), "artifact:test-model"
            )
            waiver_rows = copy.deepcopy(waivers or [])
            if waiver_rows:
                qds_emit._check_trust_invariant(
                    {"cross_tool_coverage": coverage}, waiver_rows
                )
            qds = {
                "id": "QDS_fixture",
                "emitter_contract_version": contract_version,
                "structure_ref": "1abc",
                "derived_from_evaluation_run_refs": ["EVAL_fixture"],
                "issued_at": issued_at,
                "subject_ref": "artifact:test-model",
                "coverage_scope": coverage_scope,
                "cross_tool_coverage": coverage,
            }
            if scope_notes is not None:
                qds["scope_notes"] = scope_notes
            if waivers:
                qds["cross_tool_waivers"] = copy.deepcopy(waivers)
    finally:
        qds_emit.CATALOG_PATH = old_catalog
        qds_emit.TOOL_RECS_PATH = old_recommendations
        qds_emit.TOOL_ASSUMPTIONS_PATH = old_assumptions
    qds_path = root / "data" / "x" / "QDS_fixture.yaml"
    canonical_text = qds_emit.yaml_dump({"quality_data_sheets": [qds]})
    replay_pin = {
            "id": "QDS_fixture_replay_pin",
            "qds_ref": "QDS_fixture",
            "source_evaluation_run_refs": ["EVAL_fixture"],
            "emitter_contract_version": contract_version,
            "canonical_qds_sha256": hashlib.sha256(
                canonical_text.encode("utf-8")
            ).hexdigest(),
            "emitter_source_sha256": hashlib.sha256(
                Path(
                    trust_guard.REPLAY_CONTRACT_EMITTERS[contract_version].__file__
                ).read_bytes()
            ).hexdigest(),
            "source_tools_sha256": snapshot_digest("tools", tool_snapshot),
            "source_tool_recommendations_sha256": snapshot_digest(
                "tool_recommendations", source_document["tool_recommendations"]
            ),
            "source_tool_assumptions_sha256": snapshot_digest(
                "assumptions", source_document["assumptions"]
            ),
        }
    if with_context:
        replay_pin.update({
            "qds_emission_context_ref": "QDS_fixture_emission_context",
            "source_qds_emission_context_sha256": snapshot_digest(
                "qds_emission_contexts",
                source_document["qds_emission_contexts"],
            ),
        })
    source_document["qds_replay_pins"] = [replay_pin]
    eval_path.write_text(yaml.safe_dump(source_document, sort_keys=False))
    if mutate_qds:
        mutate_qds(qds)
    qds_path.write_text(qds_emit.yaml_dump({"quality_data_sheets": [qds]}))
    return eval_path, qds_path


CCTBX = oracle_measurement("M_cctbx", "phenix.model_vs_data", "cctbx")
NON_CCTBX = oracle_measurement("M_gemmi", "gemmi validate", "non_cctbx")
T14_DERIVED = [
    {
        "id": "M_t14_reduce",
        "catalog_task_ref": "T14",
        "metric_definition_ref": "T14_asn_gln_his_flip_candidates_scored",
        "oracle_tool_ref": "reduce (standalone, Richardson)",
        "oracle_family": "non_cctbx",
        "oracle_measure": {"value_numeric": 14, "unit": "count"},
        "pass_status": "informational",
        "stage": "final",
        "scope": "complex",
        "scope_selector": "model",
        "subject_ref": "artifact:test-model",
    },
    {
        "id": "M_t14_reduce2",
        "catalog_task_ref": "T14",
        "metric_definition_ref": "T14_asn_gln_his_flip_candidates_scored",
        "oracle_tool_ref": "mmtbx.reduce2",
        "oracle_family": "cctbx",
        "oracle_measure": {"value_numeric": 18, "unit": "count"},
        "pass_status": "informational",
        "stage": "final",
        "scope": "complex",
        "scope_selector": "model",
        "subject_ref": "artifact:test-model",
    },
    {
        "id": "M_t14_conflicts",
        "catalog_task_ref": "T14",
        "metric_definition_ref": "T14_asn_gln_his_flip_set_conflicts",
        "oracle_tool_ref": "mmtbx.reduce2",
        "oracle_family": "cctbx",
        "oracle_measure": {"value_numeric": 0, "unit": "count", "count": 14},
        "derived_from_measurement_refs": ["M_t14_reduce", "M_t14_reduce2"],
        "pass_status": "informational",
        "stage": "final",
        "scope": "complex",
        "scope_selector": "model",
        "subject_ref": "artifact:test-model",
    },
]


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    write_fixture(root, [NON_CCTBX])
    rec_path = root / "ref" / "tool_recommendations.yaml"
    rec_doc = yaml.safe_load(rec_path.read_text())
    rec_doc["tool_recommendations"].append(
        {
            "id": "REC_future_fixture",
            "metric_definition_ref": "T06_r-free",
            "tool_ref": "gemmi validate",
            "role": "alternative",
            "rank": 99,
            "as_of_date": "2027-01-01",
            "effective_at": "2027-01-01T00:00:00+00:00",
        }
    )
    rec_path.write_text(yaml.safe_dump(rec_doc, sort_keys=False))
    assumption_path = root / "ref" / "tool_assumptions.yaml"
    assumption_doc = yaml.safe_load(assumption_path.read_text())
    assumption_doc["assumptions"].append(
        {
            "id": "ASSUM_future_fixture",
            "as_of_date": "2027-01-01",
            "effective_at": "2027-01-01T00:00:00+00:00",
            "kind": "explicit",
            "scope": "tool",
            "title": "Future fixture assumption",
            "description": "Must not enter an already-issued QDS.",
            "tool_ref": "gemmi validate",
        }
    )
    assumption_path.write_text(yaml.safe_dump(assumption_doc, sort_keys=False))
    code, out = run_guard(root)
    check("future registry rows do not rewrite a historical QDS", code, 0)
    check("isolated future-row replay remains clean", "FAIL" in out, False)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    write_fixture(root, [NON_CCTBX])
    rec_path = root / "ref" / "tool_recommendations.yaml"
    rec_doc = yaml.safe_load(rec_path.read_text())
    rec_doc["tool_recommendations"].append(
        {
            "id": "REC_past_fixture",
            "metric_definition_ref": "T06_r-free",
            "tool_ref": "gemmi validate",
            "role": "alternative",
            "rank": 99,
            "as_of_date": "2026-09-21",
            "effective_at": "2026-09-21T00:00:00+00:00",
        }
    )
    rec_path.write_text(yaml.safe_dump(rec_doc, sort_keys=False))
    code, out = run_guard(root)
    check("backdated live registry edits cannot redefine a pinned QDS", code, 0)
    check("pinned replay ignores isolated registry drift", "FAIL" in out, False)


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    write_fixture(root, [CCTBX])
    code, out = run_guard(root)
    check("unwaived cctbx-only source evidence fails", code, 1)
    check("failure names source-derived trust check", "source-derived" in out, True)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    write_fixture(root, [CCTBX], waivers=[waiver()])
    code, _ = run_guard(root)
    check("claim-scoped cctbx-only waiver passes", code, 0)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    _, qds_path = write_fixture(root, [NON_CCTBX])
    qds_path.write_text("# semantically inert manual edit\n" + qds_path.read_text())
    code, out = run_guard(root)
    check("noncanonical modern QDS serialization fails", code, 1)
    check("byte drift is diagnosed", "not independently canonical" in out, True)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    eval_path, _ = write_fixture(root, [CCTBX], waivers=[waiver()])
    doc = yaml.safe_load(eval_path.read_text())
    del doc["evaluation_runs"][0]["cross_tool_waivers"]
    eval_path.write_text(yaml.safe_dump(doc, sort_keys=False))
    code, out = run_guard(root)
    check("QDS-only fabricated waiver fails", code, 1)
    check("fabricated waiver drift is diagnosed", "waivers rebuilt" in out, True)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    eval_path, qds_path = write_fixture(root, [CCTBX], waivers=[waiver()])
    doc = yaml.safe_load(qds_path.read_text())
    del doc["quality_data_sheets"][0]["cross_tool_waivers"]
    qds_path.write_text(yaml.safe_dump(doc, sort_keys=False))
    code, out = run_guard(root)
    check("omitted source-owned waiver fails", code, 1)
    check("omitted waiver drift is diagnosed", "waivers rebuilt" in out, True)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)

    def claim_closed(qds: dict[str, Any]) -> None:
        qds["cross_tool_coverage"]["task_coverage"][0]["gap_status"] = "closed"

    write_fixture(root, [CCTBX], mutate_qds=claim_closed)
    code, out = run_guard(root)
    check("editable closed prose cannot hide cctbx-only evidence", code, 1)
    check("cctbx-only diagnosis survives forged prose", "cctbx only" in out, True)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    eval_path, _ = write_fixture(root, [CCTBX], waivers=[waiver()])
    doc = yaml.safe_load(eval_path.read_text())
    doc["evaluation_runs"][0]["measurements"][0]["oracle_family"] = "non_cctbx"
    eval_path.write_text(yaml.safe_dump(doc, sort_keys=False))
    code, out = run_guard(root)
    check("PHENIX cannot self-label as non-cctbx", code, 1)
    check("canonical-family mismatch is diagnosed", "canonical family" in out, True)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)

    def overlap(qds: dict[str, Any]) -> None:
        row = qds["cross_tool_coverage"]["task_coverage"][0]
        row["non_cctbx_oracles"] = ["phenix.model_vs_data"]

    write_fixture(root, [CCTBX], waivers=[waiver()], mutate_qds=overlap)
    code, out = run_guard(root)
    check("one oracle in both families fails", code, 1)
    check("family overlap is diagnosed", "both families" in out, True)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)

    def remove_coverage(qds: dict[str, Any]) -> None:
        del qds["cross_tool_coverage"]

    write_fixture(root, [NON_CCTBX], mutate_qds=remove_coverage)
    code, out = run_guard(root)
    check("missing coverage block fails", code, 1)
    check("missing coverage is diagnosed", "no cross_tool_coverage" in out, True)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    write_fixture(root, [CCTBX], issued_at="2026-01-01T00:00:00+00:00")
    code, _ = run_guard(root)
    check("unknown backdated QDS is not grandfathered", code, 1)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    write_catalog(root)
    path = (
        root
        / "data/coscientists/openscientist/"
        "QDS_1sar_cdba2c07_2026-04-24.yaml"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    frozen_source = (
        REPO
        / "data/coscientists/openscientist/"
        "QDS_1sar_cdba2c07_2026-04-24.yaml"
    )
    shutil.copy2(frozen_source, path)
    code, out = run_guard(root)
    check("exact frozen historical identity passes", code, 0)
    check("historical exemption is printed", "grandfathered" in out, True)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    write_catalog(root)
    path = (
        root
        / "data/coscientists/openscientist/"
        "QDS_1sar_cdba2c07_2026-04-24.yaml"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    frozen_source = (
        REPO
        / "data/coscientists/openscientist/"
        "QDS_1sar_cdba2c07_2026-04-24.yaml"
    )
    shutil.copy2(frozen_source, path)
    doc = yaml.safe_load(path.read_text())
    doc["quality_data_sheets"][0]["geometry_summary"]["clashscore"][
        "value_numeric"
    ] = 999.0
    path.write_text(yaml.safe_dump(doc, sort_keys=False))
    code, out = run_guard(root)
    check("mutated historical scientific value loses exemption", code, 1)
    check(
        "mutated historical sheet is not grandfathered",
        "grandfathered:" in out,
        False,
    )

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    write_fixture(root, [NON_CCTBX])
    code, _ = run_guard(root)
    check("source-derived non-cctbx-only coverage passes", code, 0)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    first = copy.deepcopy(NON_CCTBX)
    second = copy.deepcopy(NON_CCTBX)
    first.update({
        "id": "M_binding_a", "pass_status": "pass",
        "pass_criterion": "pass when < 0.25",
        "pass_criterion_ref": "CRIT_a",
    })
    second.update({
        "id": "M_binding_b", "pass_status": "pass",
        "pass_criterion": "pass when < 0.25",
        "pass_criterion_ref": "CRIT_b",
    })
    write_fixture(root, [first, second])
    code, out = run_guard(root)
    check("retained replay rejects collapsed criterion bindings", code, 1)
    check(
        "retained semantic conflict is diagnosed before replay",
        "retained contract selection cannot safely choose" in out,
        True,
    )

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    nested = copy.deepcopy(NON_CCTBX)
    nested["oracle_measure"]["pass_status"] = "pass"
    write_fixture(root, [nested])
    code, out = run_guard(root)
    check("retained replay rejects nested source verdict metadata", code, 1)
    check("nested source verdict is diagnosed",
          "nested QDS lineage/verdict" in out, True)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    eval_path, _ = write_fixture(root, [NON_CCTBX])
    eval_path.rename(eval_path.with_name("not_an_eval.yaml"))
    code, out = run_guard(root)
    check("a noncanonical EvaluationRun carrier is not trusted", code, 1)
    check(
        "the renamed trust source resolves zero times",
        "source EvaluationRun 'EVAL_fixture' resolves 0 times" in out,
        True,
    )

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    write_fixture(root, [CCTBX, NON_CCTBX])
    code, out = run_guard(root)
    check("dual-family source evidence passes", code, 0)
    check("passing dual-family fixture has no failures", "FAIL" not in out, True)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    _eval_path, qds_path = write_fixture(root, T14_DERIVED)
    code, out = run_guard(root)
    check("contract-2 derived T14 coverage passes full pinned replay", code, 0)
    check("derived T14 replay has no trust failure", "FAIL" not in out, True)
    qds = yaml.safe_load(qds_path.read_text())["quality_data_sheets"][0]
    conflict_coverage = next(
        row
        for row in qds["cross_tool_coverage"]["task_coverage"]
        if row.get("metric_definition_ref")
        == "T14_asn_gln_his_flip_set_conflicts"
    )
    check(
        "pinned T14 replay derives both participating families",
        (
            conflict_coverage["cctbx_oracles"],
            conflict_coverage["non_cctbx_oracles"],
        ),
        (["mmtbx.reduce2"], ["reduce (standalone, Richardson)"]),
    )

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    write_fixture(root, [NON_CCTBX], coverage_scope="partial")
    code, out = run_guard(root)
    check("partial QDS without scope notes fails", code, 1)
    check("partial-scope diagnostic is explicit", "scope_notes" in out, True)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    eval_path, _ = write_fixture(
        root,
        [NON_CCTBX],
        coverage_scope="partial",
        scope_notes="Only the fixture T06 measurement.",
        with_context=True,
    )
    code, out = run_guard(root)
    check("typed partial contract-3 context passes pinned replay", code, 0)
    check("typed context replay is clean", "FAIL" not in out, True)

    eval_doc = yaml.safe_load(eval_path.read_text())
    eval_doc["qds_emission_contexts"][0]["headline_verdict"] = (
        "Mutated source context headline."
    )
    eval_path.write_text(yaml.safe_dump(eval_doc, sort_keys=False))
    code, out = run_guard(root)
    check("source context drift invalidates its replay pin", code, 1)
    check(
        "source context digest drift is diagnosed",
        "source_qds_emission_context_sha256" in out,
        True,
    )

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    eval_path, _ = write_fixture(
        root,
        [NON_CCTBX],
        coverage_scope="partial",
        scope_notes="Only the fixture T06 measurement.",
        with_context=True,
    )
    eval_doc = yaml.safe_load(eval_path.read_text())
    eval_doc["qds_emission_contexts"][0]["headline_verdict"] = (
        "Mutated but freshly pinned context headline."
    )
    eval_doc["qds_replay_pins"][0][
        "source_qds_emission_context_sha256"
    ] = snapshot_digest(
        "qds_emission_contexts", eval_doc["qds_emission_contexts"]
    )
    eval_path.write_text(yaml.safe_dump(eval_doc, sort_keys=False))
    code, out = run_guard(root)
    check("repinned context drift still fails deterministic replay", code, 1)
    check(
        "repinned context drift is diagnosed as replay divergence",
        "frozen contract-3 replay" in out,
        True,
    )

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    eval_path, _ = write_fixture(
        root,
        [NON_CCTBX],
        coverage_scope="partial",
        scope_notes="Only the fixture T06 measurement.",
        with_context=True,
    )
    eval_doc = yaml.safe_load(eval_path.read_text())
    del eval_doc["qds_replay_pins"][0]["source_qds_emission_context_sha256"]
    eval_path.write_text(yaml.safe_dump(eval_doc, sort_keys=False))
    code, out = run_guard(root)
    check("contract-3 partial pin requires a context digest", code, 1)
    check(
        "missing context digest is explicit",
        "source_qds_emission_context_sha256" in out,
        True,
    )

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)

    def omit_row(qds: dict[str, Any]) -> None:
        qds["cross_tool_coverage"]["task_coverage"].pop()

    second = oracle_measurement(
        "M_gemmi_work", "gemmi validate", "non_cctbx", "T06_r-work"
    )
    write_fixture(root, [NON_CCTBX, second], mutate_qds=omit_row)
    code, out = run_guard(root)
    check("omitting a source-derived coverage claim fails", code, 1)
    check("coverage drift is diagnosed", "differs from coverage rebuilt" in out, True)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    _, qds_path = write_fixture(root, [CCTBX])
    yml_path = qds_path.with_suffix(".yml")
    qds_path.rename(yml_path)
    code, out = run_guard(root)
    check(".yml QDS cannot bypass trust enforcement", code, 1)
    check(".yml trust failure is diagnosed", "source-derived" in out, True)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    measurements = [
        oracle_measurement("M_subject_a", "phenix.model_vs_data", "cctbx"),
        oracle_measurement("M_subject_b", "gemmi validate", "non_cctbx"),
    ]
    measurements[1]["subject_ref"] = "artifact:other-model"

    def omit_subject(qds: dict[str, Any]) -> None:
        del qds["subject_ref"]

    write_fixture(root, measurements, mutate_qds=omit_subject)
    code, out = run_guard(root)
    check("multi-subject QDS cannot omit subject_ref", code, 1)
    check("multi-subject ambiguity is diagnosed", "multiple explicit" in out, True)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)

    def omit_inferred_subject(qds: dict[str, Any]) -> None:
        del qds["subject_ref"]

    write_fixture(root, [NON_CCTBX], mutate_qds=omit_inferred_subject)
    code, out = run_guard(root)
    check("inferred source subject must be committed", code, 1)
    check("omitted inferred subject is diagnosed", "omits subject_ref" in out, True)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)

    def mismatch_subject(qds: dict[str, Any]) -> None:
        qds["subject_ref"] = "artifact:other-model"

    write_fixture(root, [NON_CCTBX], mutate_qds=mismatch_subject)
    code, out = run_guard(root)
    check("QDS subject must have exact source evidence", code, 1)
    check("subject mismatch is diagnosed", "has no exact evidence" in out, True)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)

    def omit_contract_version(qds: dict[str, Any]) -> None:
        qds.pop("emitter_contract_version")

    write_fixture(root, [NON_CCTBX], mutate_qds=omit_contract_version)
    code, out = run_guard(root)
    check("modern QDS must pin an emitter contract version", code, 1)
    check(
        "missing emitter contract version is diagnosed",
        "emitter_contract_version" in out,
        True,
    )

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    eval_path, _ = write_fixture(root, [NON_CCTBX])
    eval_doc = yaml.safe_load(eval_path.read_text())
    eval_doc.pop("tools")
    eval_path.write_text(yaml.safe_dump(eval_doc, sort_keys=False))
    code, out = run_guard(root)
    check("modern replay requires a source-pinned Tool snapshot", code, 1)
    check("missing Tool snapshot is diagnosed", "Tool snapshot" in out, True)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    eval_path, _ = write_fixture(root, [NON_CCTBX])
    eval_doc = yaml.safe_load(eval_path.read_text())
    eval_doc.pop("qds_replay_pins")
    eval_path.write_text(yaml.safe_dump(eval_doc, sort_keys=False))
    code, out = run_guard(root)
    check("modern QDS requires a source-owned replay pin", code, 1)
    check("missing replay pin is diagnosed", "source-owned replay pin" in out, True)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    write_fixture(root, [NON_CCTBX])
    catalog_path = root / "ref" / "catalog.yaml"
    catalog_doc = yaml.safe_load(catalog_path.read_text())
    gemmi = next(
        tool for tool in catalog_doc["tools"] if tool["id"] == "gemmi validate"
    )
    gemmi["family"] = "cctbx"
    catalog_path.write_text(yaml.safe_dump(catalog_doc, sort_keys=False))
    code, out = run_guard(root)
    check("live catalog family drift cannot redefine a pinned QDS", code, 0)
    check("pinned-family replay stays clean after catalog drift", "FAIL" in out, False)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    eval_path, _ = write_fixture(root, [NON_CCTBX])
    eval_doc = yaml.safe_load(eval_path.read_text())
    eval_doc["tool_recommendations"][0]["justification"] = "mutated source snapshot"
    eval_path.write_text(yaml.safe_dump(eval_doc, sort_keys=False))
    code, out = run_guard(root)
    check("source recommendation drift invalidates its replay pin", code, 1)
    check(
        "source recommendation digest drift is diagnosed",
        "source_tool_recommendations_sha256" in out,
        True,
    )

check(
    "contract 1 is retained in a module distinct from the current emitter",
    Path(qds_emit_contract_v1.__file__).resolve()
    != Path(qds_emit.__file__).resolve(),
    True,
)
check(
    "contract 2 is retained in a module distinct from the current emitter",
    Path(qds_emit_contract_v2.__file__).resolve()
    != Path(qds_emit.__file__).resolve(),
    True,
)
check(
    "contract 3 is retained in a module distinct from the current emitter",
    Path(qds_emit_contract_v3.__file__).resolve()
    != Path(qds_emit.__file__).resolve(),
    True,
)
check(
    "trust guard registers all retained emitter contracts",
    set(trust_guard.REPLAY_CONTRACT_EMITTERS),
    {"1", "2", "3"},
)

_retained_qds_rel = Path(
    "data/coscientists/openscientist/QDS_1sar_cdba2c07_2026-09-21.yaml"
)
_retained_qds_source = REPO / _retained_qds_rel
_retained_qds_doc = yaml.safe_load(_retained_qds_source.read_text())
_retained_qds = _retained_qds_doc["quality_data_sheets"][0]
check(
    "the exact September 21 sheet retains its historical contract",
    trust_guard._is_frozen_retained_contract(
        _retained_qds_source, REPO, _retained_qds
    ),
    True,
)
check(
    "a renamed historical sheet cannot inherit its retained contract",
    trust_guard._is_frozen_retained_contract(
        REPO / "data/x/QDS_renamed_history.yaml", REPO, _retained_qds
    ),
    False,
)
_wrong_retained_identity = copy.deepcopy(_retained_qds)
_wrong_retained_identity["id"] = "QDS_backdated_copy"
check(
    "a changed QDS identity cannot inherit a retained contract",
    trust_guard._is_frozen_retained_contract(
        _retained_qds_source, REPO, _wrong_retained_identity
    ),
    False,
)
with tempfile.TemporaryDirectory() as tmp:
    _history_root = Path(tmp)
    _history_copy = _history_root / _retained_qds_rel
    _history_copy.parent.mkdir(parents=True)
    shutil.copy2(_retained_qds_source, _history_copy)
    _history_copy.write_bytes(_history_copy.read_bytes() + b"\n")
    _tampered_history_allowed = trust_guard._is_frozen_retained_contract(
        _history_copy, _history_root, _retained_qds
    )
check(
    "a byte change invalidates the retained-contract authorization",
    _tampered_history_allowed,
    False,
)

for retained_version in ("1", "2"):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_fixture(
            root,
            [NON_CCTBX],
            coverage_scope="partial",
            scope_notes="Bounded downgrade-regression fixture.",
            contract_version=retained_version,
        )
        code, out = run_guard(root)
    check(
        f"new contract-{retained_version} QDS is rejected despite a valid replay pin",
        code,
        1,
    )
    check(
        f"contract-{retained_version} downgrade has a replay-only diagnostic",
        "retained contracts are replay-only" in out
        and "must use current emitter contract 3" in out,
        True,
    )

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    _eval_path, qds_path = write_fixture(root, [NON_CCTBX])
    helper_names = (
        "_tool_families_from_rows",
        "_canonicalize_measurement_tools",
        "_explicit_subjects",
        "_annotated_runs",
        "_final_or_all_measurements",
        "build_cross_tool_coverage",
        "_check_trust_invariant",
    )
    originals = {name: getattr(qds_emit, name) for name in helper_names}

    def mutable_emitter_must_not_run(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("mutable current-emitter helper was called")

    try:
        for name in helper_names:
            setattr(qds_emit, name, mutable_emitter_must_not_run)
        load_failures: list[str] = []
        eval_runs = trust_guard._load_eval_runs(root, load_failures)
        failures = list(load_failures)
        grandfathered: list[str] = []
        sheet = yaml.safe_load(qds_path.read_text())["quality_data_sheets"][0]
        trust_guard.check_sheet(
            qds_path, root, sheet, eval_runs, failures, grandfathered
        )
    finally:
        for name, implementation in originals.items():
            setattr(qds_emit, name, implementation)
    check(
        "retained-contract validation ignores divergent current-emitter helpers",
        failures,
        [],
    )


def run_projection_mutation(
    mutate: Callable[[dict[str, Any], dict[str, Any]], None] | None,
) -> tuple[int, str]:
    """Run the guard on the live modern fixture after an in-memory mutation."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_catalog(root)
        # Preserve the exact historical path: its retained contract is admitted
        # only when path, identity, timestamp, and complete file bytes match.
        data_dir = root / "data" / "coscientists" / "openscientist"
        data_dir.mkdir(parents=True, exist_ok=True)
        eval_source = (
            REPO
            / "data/coscientists/openscientist/"
            "EVAL_1sar_cdba2c07_2026-09-21.yaml"
        )
        qds_source = (
            REPO
            / "data/coscientists/openscientist/"
            "QDS_1sar_cdba2c07_2026-09-21.yaml"
        )
        eval_doc = yaml.safe_load(eval_source.read_text())
        qds_doc = yaml.safe_load(qds_source.read_text())
        if mutate is not None:
            mutate(qds_doc["quality_data_sheets"][0], eval_doc["evaluation_runs"][0])
        (data_dir / eval_source.name).write_text(
            yaml.safe_dump(eval_doc, sort_keys=False, allow_unicode=True)
        )
        (data_dir / qds_source.name).write_text(qds_emit.yaml_dump(qds_doc))
        return run_guard(root)


code, out = run_projection_mutation(None)
check("source-owned projection accepts the unmodified modern QDS", code, 0)
check("unmodified source projection has no failure", "FAIL" not in out, True)


def drop_source_projection(qds: dict[str, Any], _run: dict[str, Any]) -> None:
    qds.pop("interface_quality_summary")


def omit_mapping_control(qds: dict[str, Any], _run: dict[str, Any]) -> None:
    qds["interface_quality_summary"]["interface_qualities"].pop()


def duplicate_mapping_control(qds: dict[str, Any], _run: dict[str, Any]) -> None:
    rows = qds["interface_quality_summary"]["interface_qualities"]
    rows.append(copy.deepcopy(rows[0]))


def strip_scalar_identity(qds: dict[str, Any], _run: dict[str, Any]) -> None:
    scalar = qds["interface_quality_summary"]["interface_dockq_score"]
    for key in (
        "source_measurement_ref",
        "source_evaluation_run_ref",
        "metric_definition_ref",
    ):
        scalar.pop(key)
    scalar["value_numeric"] = 0.9999


def forge_identity_method(qds: dict[str, Any], _run: dict[str, Any]) -> None:
    qds["identity_block"]["method"] = "nmr"


def forge_identity_description(qds: dict[str, Any], _run: dict[str, Any]) -> None:
    qds["identity_block"]["description"] = "Forged QDS-only identity prose."


def wrapped_source(run: dict[str, Any], suffix: str) -> dict[str, Any]:
    measurement = next(
        row for row in run["measurements"] if str(row.get("id", "")).endswith(suffix)
    )
    annotated = copy.deepcopy(measurement)
    annotated["_source_evaluation_run_ref"] = run["id"]
    annotated["_source_run_date"] = str(run.get("run_date") or "")
    return qds_emit._wrap_value(annotated) or {}


def forge_scalar_subject(qds: dict[str, Any], _run: dict[str, Any]) -> None:
    qds["interface_quality_summary"]["interface_dockq_score"]["subject_ref"] = (
        "artifact:wrong-subject"
    )


def route_wrong_metric(qds: dict[str, Any], run: dict[str, Any]) -> None:
    qds["interface_quality_summary"]["interface_dockq_score"] = wrapped_source(
        run, "_M_005"
    )


for label, mutation in (
    ("omitted source-derived summary", drop_source_projection),
    ("omitted mapping-control row", omit_mapping_control),
    ("duplicated mapping-control row", duplicate_mapping_control),
    ("stripped scalar identity", strip_scalar_identity),
    ("QDS-only identity method", forge_identity_method),
    ("QDS-only identity description", forge_identity_description),
    ("wrong-subject scalar", forge_scalar_subject),
    ("wrong-slot exact source scalar", route_wrong_metric),
):
    code, out = run_projection_mutation(mutation)
    check(f"{label} fails the canonical byte projection", code, 1)
    check(
        f"{label} has a source-pin diagnostic",
        "source-owned canonical byte pin" in out,
        True,
    )

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    data_dir = root / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "QDS_duplicate.yaml").write_text(
        "quality_data_sheets: []\n"
        "quality_data_sheets: []\n"
    )
    code, out = run_guard(root)
check("duplicate QDS YAML mapping keys fail trust validation", code, 1)
check("duplicate QDS YAML diagnostic names the repeated key",
      "duplicate YAML mapping key 'quality_data_sheets'" in out, True)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    data_dir = root / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "QDS_invalid_utf8.yaml").write_bytes(
        b"quality_data_sheets:\n\xff"
    )
    code, out = run_guard(root)
check("invalid-UTF-8 QDS fails trust validation", code, 1)
check("invalid-UTF-8 QDS has no traceback", "Traceback" in out, False)
check("invalid-UTF-8 QDS has a contextual diagnostic",
      "UnicodeDecodeError" in out and "QDS_invalid_utf8.yaml" in out, True)

print(f"\n{PASSED} checks passed")
