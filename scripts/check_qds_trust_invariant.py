#!/usr/bin/env python3
"""Gate: no committed QDS rests a gradeable task on cctbx-only evidence (#315).

The emitter enforces this at emission time (`_check_trust_invariant`); this
check covers the other road into the repo — a hand-edited or historical QDS
file. For every committed `QDS_*.yaml`: a coverage row whose gap is cctbx-only
or unknown-family must either carry its WAIVED annotation (with the matching
waiver block present) or belong to a sheet issued before the invariant existed
(CUTOVER, printed as a named grandfather — history is history, but it is
listed, not silent).

Network-free. `--root` exists for the tests.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

CUTOVER = "2026-08-13"          # the date the invariant became enforceable
WAIVER_QUALIFIERS = (
    "metric_definition_ref",
    "subject_ref",
    "reference_subject_ref",
    "stage",
    "scope",
    "scope_selector",
)


def check_sheet(path: Path, qds: dict, failures: list[str],
                grandfathered: list[str]) -> None:
    issued = str(qds.get("issued_at", ""))[:10]
    before_cutover = bool(issued and issued < CUTOVER)
    coverage_rows = (qds.get("cross_tool_coverage") or {}).get("task_coverage", [])
    gated_rows = [
        row for row in coverage_rows
        if str(row.get("gap_status", "")).startswith(
            ("open — cctbx only", "unknown")
        )
    ]
    waivers = qds.get("cross_tool_waivers", []) or []
    matches_by_row: dict[int, list[dict]] = {
        index: [] for index in range(len(gated_rows))
    }
    waiver_errors: list[str] = []

    for waiver in waivers:
        task = waiver.get("catalog_task_ref")
        task_rows = [
            (index, row) for index, row in enumerate(gated_rows)
            if row.get("catalog_task_ref") == task
        ]
        specified = [
            field for field in WAIVER_QUALIFIERS
            if waiver.get(field) not in (None, "")
        ]
        matches = [
            (index, row) for index, row in task_rows
            if all(row.get(field) == waiver.get(field) for field in specified)
        ]
        if not specified and len(task_rows) > 1:
            waiver_errors.append(
                f"{path.name}: waiver {waiver.get('id')!r} is task-only but task "
                f"{task} has {len(task_rows)} gated claims; add metric/context qualifiers"
            )
            continue
        if specified and len(matches) > 1:
            waiver_errors.append(
                f"{path.name}: waiver {waiver.get('id')!r} ambiguously matches "
                f"{len(matches)} gated claims; add enough metric/context qualifiers"
            )
            continue
        if len(matches) == 1:
            matches_by_row[matches[0][0]].append(waiver)

    if not before_cutover:
        failures.extend(waiver_errors)

    for index, row in enumerate(gated_rows):
        gap = str(row.get("gap_status", ""))
        task = row.get("catalog_task_ref")
        matching = matches_by_row[index]
        if "WAIVED" in gap and len(matching) == 1:
            continue
        if before_cutover:
            grandfathered.append(f"{path.name}: {task} ({gap[:40]}…) — "
                                 f"issued {issued}, predates the invariant")
            continue
        context = ", ".join(
            f"{field}={row.get(field)!r}" for field in WAIVER_QUALIFIERS
            if row.get(field) not in (None, "")
        ) or "no qualifiers"
        if len(matching) > 1:
            waiver_ids = ", ".join(str(w.get("id")) for w in matching)
            failures.append(
                f"{path.name}: task {task} ({context}) has multiple matching "
                f"waivers ({waiver_ids}) (#315)"
            )
        elif len(matching) == 1:
            failures.append(
                f"{path.name}: task {task} ({context}) has a matching waiver block "
                "but its gap_status lacks the WAIVED annotation (#315)"
            )
        else:
            failures.append(
                f"{path.name}: task {task} ({context}) is {gap!r} with no "
                "unambiguous matching waiver (#315)"
            )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    args = ap.parse_args()
    root = Path(args.root)
    failures: list[str] = []
    grandfathered: list[str] = []

    for path in sorted((root / "data").rglob("QDS_*.yaml")):
        try:
            doc = yaml.safe_load(path.read_text()) or {}
        except (yaml.YAMLError, OSError) as exc:
            failures.append(f"{path.name}: unreadable ({type(exc).__name__})")
            continue
        for qds in doc.get("quality_data_sheets", []) or []:
            check_sheet(path, qds, failures, grandfathered)

    for note in grandfathered:
        print(f"  grandfathered: {note}")
    if failures:
        for f in failures:
            print(f"FAIL  {f}")
        print(f"{len(failures)} trust-invariant failure(s)")
        return 1
    print(f"QDS trust invariant holds "
          f"({len(grandfathered)} grandfathered row(s) listed above)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
