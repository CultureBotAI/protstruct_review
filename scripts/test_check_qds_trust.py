#!/usr/bin/env python3
"""Regression tests for source-derived committed-QDS trust enforcement."""
from __future__ import annotations

import copy
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

import yaml

import qds_emit


REPO = Path(__file__).resolve().parent.parent
GUARD = REPO / "scripts" / "check_qds_trust_invariant.py"
PASSED = 0


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
    path = root / "ref" / "catalog.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "tools": [
                    {"id": "phenix.model_vs_data", "family": "cctbx"},
                    {"id": "gemmi validate", "family": "non_cctbx"},
                ]
            },
            sort_keys=False,
        )
    )


def write_fixture(
    root: Path,
    measurements: list[dict[str, Any]],
    *,
    issued_at: str = "2026-09-22T12:00:00+00:00",
    waivers: list[dict[str, Any]] | None = None,
    mutate_qds: Callable[[dict[str, Any]], None] | None = None,
    coverage_scope: str = "cumulative",
    scope_notes: str | None = None,
) -> tuple[Path, Path]:
    write_catalog(root)
    eval_run = {
        "id": "EVAL_fixture",
        "structure_ref": "1abc",
        "run_date": "2026-09-22",
        "measurements": copy.deepcopy(measurements),
    }
    eval_path = root / "data" / "x" / "EVAL_fixture.yaml"
    eval_path.parent.mkdir(parents=True, exist_ok=True)
    eval_path.write_text(
        yaml.safe_dump({"evaluation_runs": [eval_run]}, sort_keys=False)
    )

    old_catalog = qds_emit.CATALOG_PATH
    qds_emit.CATALOG_PATH = root / "ref" / "catalog.yaml"
    try:
        coverage = qds_emit.build_cross_tool_coverage(
            "QDS_fixture", copy.deepcopy(measurements), "artifact:test-model"
        )
        waiver_rows = copy.deepcopy(waivers or [])
        if waiver_rows:
            qds_emit._check_trust_invariant(
                {"cross_tool_coverage": coverage}, waiver_rows
            )
    finally:
        qds_emit.CATALOG_PATH = old_catalog

    qds: dict[str, Any] = {
        "id": "QDS_fixture",
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
    if mutate_qds:
        mutate_qds(qds)
    qds_path = root / "data" / "x" / "QDS_fixture.yaml"
    qds_path.write_text(
        yaml.safe_dump({"quality_data_sheets": [qds]}, sort_keys=False)
    )
    return eval_path, qds_path


CCTBX = oracle_measurement("M_cctbx", "phenix.model_vs_data", "cctbx")
NON_CCTBX = oracle_measurement("M_gemmi", "gemmi validate", "non_cctbx")


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
    path.write_text(
        yaml.safe_dump(
            {
                "quality_data_sheets": [
                    {
                        "id": "QDS_1sar_cdba2c07_2026-04-24",
                        "issued_at": "2026-04-26T04:41:16+00:00",
                    }
                ]
            },
            sort_keys=False,
        )
    )
    code, out = run_guard(root)
    check("exact frozen historical identity passes", code, 0)
    check("historical exemption is printed", "grandfathered" in out, True)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    write_fixture(root, [NON_CCTBX])
    code, _ = run_guard(root)
    check("source-derived non-cctbx-only coverage passes", code, 0)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    write_fixture(root, [CCTBX, NON_CCTBX])
    code, out = run_guard(root)
    check("dual-family source evidence passes", code, 0)
    check("passing dual-family fixture has no failures", "FAIL" not in out, True)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    write_fixture(root, [NON_CCTBX], coverage_scope="partial")
    code, out = run_guard(root)
    check("partial QDS without scope notes fails", code, 1)
    check("partial-scope diagnostic is explicit", "scope_notes" in out, True)

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

print(f"\n{PASSED} checks passed")
