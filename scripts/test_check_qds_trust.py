#!/usr/bin/env python3
"""Unit tests for the QDS trust-invariant gate (#315).

Fixture-driven: post-cutover sheets with unwaived cctbx-only rows must fail;
waived rows and pre-cutover history must pass (history is listed, not silent).
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
GUARD = REPO / "scripts" / "check_qds_trust_invariant.py"
PASSED = 0


def check(label: str, got, want) -> None:
    global PASSED
    if got != want:
        print(f"FAIL  {label}: got {got!r}, want {want!r}")
        sys.exit(1)
    PASSED += 1
    print(f"PASS  {label}")


def run_guard(root: Path) -> tuple[int, str]:
    proc = subprocess.run([sys.executable, str(GUARD), "--root", str(root)],
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def coverage_row(row_id="r", gap="open — cctbx only", task="T06", **qualifiers):
    return {"id": row_id, "catalog_task_ref": task, "gap_status": gap,
            **qualifiers}


def waiver(waiver_id="w", task="T06", **qualifiers):
    return {"id": waiver_id, "catalog_task_ref": task,
            "reason": "x", "as_of_date": "2026-08-13", **qualifiers}


def sheet(issued, gap=None, waived=False, rows=None, waivers=None):
    if rows is None:
        rows = [coverage_row(gap=gap or "open — cctbx only")]
    q = {"id": "QDS_x", "issued_at": issued,
         "cross_tool_coverage": {"id": "c", "task_coverage": rows}}
    if waived:
        q["cross_tool_waivers"] = [waiver()]
    if waivers is not None:
        q["cross_tool_waivers"] = waivers
    return {"quality_data_sheets": [q]}


def write(root: Path, doc):
    d = root / "data" / "x"
    d.mkdir(parents=True, exist_ok=True)
    (d / "QDS_fixture.yaml").write_text(yaml.safe_dump(doc, sort_keys=False))


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    write(root, sheet("2026-09-01", "open — cctbx only"))
    code, out = run_guard(root)
    check("post-cutover unwaived cctbx-only fails", code, 1)
    check("failure names task and rule", "T06" in out and "#315" in out, True)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    write(root, sheet("2026-09-01",
                      "open — cctbx only — WAIVED 2026-08-13: no gemmi path",
                      waived=True))
    code, out = run_guard(root)
    check("waived row passes", code, 0)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    write(root, sheet("2026-09-01",
                      "open — cctbx only — WAIVED 2026-08-13: annotation only"))
    code, out = run_guard(root)
    check("WAIVED annotation without the waiver block fails", code, 1)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    rows = [
        coverage_row("work", "open — cctbx only — WAIVED legacy", metric_definition_ref="T06_r-work"),
        coverage_row("free", "open — cctbx only — WAIVED legacy", metric_definition_ref="T06_r-free"),
    ]
    write(root, sheet("2026-09-01", rows=rows, waivers=[waiver()]))
    code, out = run_guard(root)
    check("task-only waiver cannot cover multiple gated claims", code, 1)
    check("ambiguous legacy waiver is diagnosed", "task-only" in out and "2 gated claims" in out,
          True)

claim = {
    "metric_definition_ref": "T06_r-work",
    "subject_ref": "artifact:model",
    "reference_subject_ref": "pdb:1abc",
    "stage": "final",
    "scope": "complex",
    "scope_selector": "whole model",
}
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    row = coverage_row(gap="open — cctbx only — WAIVED 2026-08-13: x", **claim)
    write(root, sheet("2026-09-01", rows=[row], waivers=[waiver(**claim)]))
    code, _ = run_guard(root)
    check("fully claim-scoped waiver passes", code, 0)

mismatch_values = {
    "metric_definition_ref": "T06_r-free",
    "subject_ref": "artifact:other",
    "reference_subject_ref": "pdb:other",
    "stage": "start",
    "scope": "chain",
    "scope_selector": "chain A",
}
for field, mismatch in mismatch_values.items():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        row = coverage_row(gap="open — cctbx only — WAIVED annotation only", **claim)
        wrong = dict(claim)
        wrong[field] = mismatch
        write(root, sheet("2026-09-01", rows=[row], waivers=[waiver(**wrong)]))
        code, out = run_guard(root)
        check(f"{field} mismatch is not waived by annotation", code, 1)
        check(f"{field} mismatch reports no matching waiver",
              "no unambiguous matching waiver" in out, True)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    row = coverage_row(**claim)
    write(root, sheet("2026-09-01", rows=[row], waivers=[waiver(**claim)]))
    code, out = run_guard(root)
    check("matching waiver block without annotation fails", code, 1)
    check("missing annotation is diagnosed", "lacks the WAIVED annotation" in out, True)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    write(root, sheet("2026-05-01", "open — cctbx only"))
    code, out = run_guard(root)
    check("pre-cutover history passes", code, 0)
    check("history is listed, not silent", "grandfathered" in out, True)

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    write(root, sheet("2026-09-01", "non-cctbx only"))
    code, out = run_guard(root)
    check("non-cctbx-only is not gated (nothing to distrust)", code, 0)

print(f"\n{PASSED} checks passed")
