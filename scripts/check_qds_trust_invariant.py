#!/usr/bin/env python3
"""Gate committed QDS trust claims against their source EvaluationRuns.

For every non-legacy QDS, rebuild cross-tool coverage from the referenced
EvaluationRuns with the emitter itself, using the catalog's canonical Tool
families. Neither editable ``gap_status`` prose nor self-asserted
``oracle_family`` metadata is authoritative. Historical sheets are exempt only
when their repository path, QDS id, and exact issue timestamp match the frozen
allowlist below; an arbitrary backdated file is not history.

Network-free. ``--root`` exists for the tests.
"""
from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path
from typing import Any

import yaml

import qds_emit


# These immutable artifacts predate source-derived committed-QDS enforcement.
# The tuple is deliberately stronger than a date cutover: changing the path,
# id, or timestamp removes the exemption.
LEGACY_QDS: dict[str, tuple[str, str]] = {
    "data/coscientists/openscientist/QDS_1sar_cdba2c07_2026-04-24.yaml": (
        "QDS_1sar_cdba2c07_2026-04-24",
        "2026-04-26T04:41:16+00:00",
    ),
    "data/coscientists/openscientist/QDS_1sar_cdba2c07_2026-04-26.yaml": (
        "QDS_1sar_cdba2c07_2026-04-26",
        "2026-04-26T09:12:19+00:00",
    ),
    "data/coscientists/openscientist/QDS_1sar_cdba2c07_2026-04-30.yaml": (
        "QDS_1sar_cdba2c07_2026-04-30",
        "2026-05-01T04:17:12+00:00",
    ),
    "data/coscientists/openscientist/QDS_1sar_cdba2c07_2026-05-01.yaml": (
        "QDS_1sar_cdba2c07_2026-05-01",
        "2026-05-01T07:09:51+00:00",
    ),
    "data/coscientists/openscientist/QDS_1sar_cdba2c07_2026-05-04.yaml": (
        "QDS_1sar_cdba2c07_2026-05-04",
        "2026-05-05T04:27:11+00:00",
    ),
    "data/coscientists/openscientist/QDS_1sar_cdba2c07_2026-05-05.yaml": (
        "QDS_1sar_cdba2c07_2026-05-05",
        "2026-05-05T07:54:30+00:00",
    ),
    "data/coscientists/openscientist/QDS_1sar_cdba2c07_2026-09-07.yaml": (
        "QDS_1sar_cdba2c07_2026-09-07",
        "2026-09-10T04:11:37+00:00",
    ),
    "data/examples/qds/QDS_synth_active_site_2026-04-26.yaml": (
        "QDS_synth_active_site_2026-04-26",
        "2026-04-26T08:50:58+00:00",
    ),
}


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _is_frozen_legacy(path: Path, root: Path, qds: dict[str, Any]) -> bool:
    expected = LEGACY_QDS.get(_relative(path, root))
    return expected == (str(qds.get("id") or ""), str(qds.get("issued_at") or ""))


def _load_eval_runs(root: Path, failures: list[str]) -> dict[str, list[dict[str, Any]]]:
    runs: dict[str, list[dict[str, Any]]] = {}
    for path in sorted((root / "data").rglob("*.yaml")):
        try:
            doc = yaml.safe_load(path.read_text()) or {}
        except (yaml.YAMLError, OSError):
            # General YAML readability is owned by the schema/record guards.
            continue
        for run in doc.get("evaluation_runs", []) or []:
            run_id = str(run.get("id") or "").strip()
            if run_id:
                runs.setdefault(run_id, []).append(run)
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
    tool_families: dict[str, str],
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


def _rebuild_coverage(
    path: Path,
    qds: dict[str, Any],
    eval_runs: dict[str, list[dict[str, Any]]],
) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    refs = qds.get("derived_from_evaluation_run_refs") or []
    if not isinstance(refs, list) or not refs:
        return None, [f"{path.name}: QDS has no source EvaluationRun refs"]
    if len(refs) != len(set(refs)):
        errors.append(f"{path.name}: QDS repeats a source EvaluationRun ref")

    source_runs: list[dict[str, Any]] = []
    for ref in refs:
        matches = eval_runs.get(str(ref), [])
        if len(matches) != 1:
            errors.append(
                f"{path.name}: source EvaluationRun {ref!r} resolves "
                f"{len(matches)} times, expected exactly once"
            )
        else:
            source_runs.append(copy.deepcopy(matches[0]))
    if errors:
        return None, errors

    try:
        for run in source_runs:
            run_id = str(run.get("id") or "<missing id>")
            run["measurements"] = qds_emit._canonicalize_measurement_tools(
                run.get("measurements", []) or [], context=f"EvaluationRun {run_id}"
            )
        filtered = qds_emit._annotated_runs(source_runs, qds.get("subject_ref"))
        measurements = [
            measurement
            for run in filtered
            for measurement in qds_emit._final_or_all_measurements(run)
        ]
        expected = qds_emit.build_cross_tool_coverage(
            str(qds.get("id") or ""), measurements, qds.get("subject_ref")
        )
        qds_emit._check_trust_invariant(
            {"cross_tool_coverage": expected},
            qds.get("cross_tool_waivers", []) or [],
        )
    except (qds_emit.QdsCompletenessError, SystemExit) as exc:
        errors.append(f"{path.name}: source-derived trust check failed: {exc}")
        return None, errors
    return expected, errors


def check_sheet(
    path: Path,
    root: Path,
    qds: dict[str, Any],
    eval_runs: dict[str, list[dict[str, Any]]],
    tool_families: dict[str, str],
    failures: list[str],
    grandfathered: list[str],
) -> None:
    if _is_frozen_legacy(path, root, qds):
        grandfathered.append(
            f"{_relative(path, root)}: {qds.get('id')} (frozen path/id/timestamp)"
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
    failures.extend(_canonical_row_errors(path, rows, tool_families))

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

    catalog_path = root / "ref" / "catalog.yaml"
    qds_emit.CATALOG_PATH = catalog_path
    try:
        tool_families = qds_emit._load_catalog_tool_families()
    except (qds_emit.QdsCompletenessError, OSError, yaml.YAMLError) as exc:
        print(f"FAIL  cannot load canonical Tool families: {exc}")
        return 1

    eval_runs = _load_eval_runs(root, failures)
    for path in sorted((root / "data").rglob("QDS_*.yaml")):
        try:
            doc = yaml.safe_load(path.read_text()) or {}
        except (yaml.YAMLError, OSError) as exc:
            failures.append(f"{path.name}: unreadable ({type(exc).__name__})")
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
                tool_families,
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
