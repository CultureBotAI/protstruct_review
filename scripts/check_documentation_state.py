#!/usr/bin/env python3
"""Check catalog-derived task, driver, wrapper, and documentation state."""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

import yaml


STATE_DOCUMENTS = (
    "CODING_STANDARDS.md",
    ".claude/skills/protstruct-eval/SKILL.md",
    "ref/README.md",
    "ref/oracle_tools.md",
    "schemas/README.md",
    "schemas/protstruct_review.yaml",
)
STATE_RE = re.compile(
    r"catalog-state:\s*tasks=(T\d{2})–(T\d{2});\s*"
    r"count=(\d+);\s*drivers=(\d+)"
)
TASK_RE = re.compile(r"T\d{2}")
DRIVER_RE = re.compile(r"driving_example_(T\d{2})\.md")
TASK_SECTION_RE = re.compile(r"^### (T\d{2}) — (.+)$", re.MULTILINE)

RUNNABLE_WRAPPERS = {
    "T15": ("scripts/t15_ss_agreement.py",),
    "T16": ("scripts/t16_interface_quality.py",),
    "T17": (
        "scripts/t17_nmr_ensemble.py",
        "scripts/t17_restraint_summary.py",
    ),
}
WRAPPER_DOCUMENTS = (
    ".claude/skills/protstruct-eval/SKILL.md",
    "ref/oracle_tools.md",
)

STALE_TEXT = {
    "CODING_STANDARDS.md": (
        "present for T01, T05, T13",
        "For a task that has no driver yet",
    ),
    ".claude/skills/protstruct-eval/SKILL.md": (
        "T15–T17 drivers wait",
        "declared-but-not-yet-runnable",
        "no PHENIX implementation and no oracle installed yet",
    ),
    "schemas/README.md": ("T01–T14",),
    "schemas/protstruct_review.yaml": ("T01..T14",),
}


def catalog_task_ids(catalog_path: Path) -> list[str]:
    """Return catalog IDs, retaining order so sequence drift is detectable."""
    document = yaml.safe_load(catalog_path.read_text()) or {}
    tasks = document.get("catalog_tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("ref/catalog.yaml has no non-empty catalog_tasks list")
    ids = [task.get("id") if isinstance(task, dict) else None for task in tasks]
    if any(not isinstance(task_id, str) for task_id in ids):
        raise ValueError("every catalog task must have a string id")
    return ids


def expected_task_sequence(task_ids: list[str]) -> list[str]:
    """Build the contiguous T01..TNN sequence implied by the catalog length."""
    return [f"T{number:02d}" for number in range(1, len(task_ids) + 1)]


def markdown_task_sections(text: str) -> dict[str, tuple[str, str]]:
    """Return task id -> (heading name, complete section text)."""
    headings = list(TASK_SECTION_RE.finditer(text))
    return {
        match.group(1): (
            match.group(2).strip(),
            text[match.start() : headings[index + 1].start()]
            if index + 1 < len(headings)
            else text[match.start() :],
        )
        for index, match in enumerate(headings)
    }


def collect_problems(repo_root: Path) -> list[str]:
    problems: list[str] = []
    try:
        catalog_path = repo_root / "ref/catalog.yaml"
        task_ids = catalog_task_ids(catalog_path)
        catalog_document = yaml.safe_load(catalog_path.read_text()) or {}
        catalog_tasks = catalog_document.get("catalog_tasks") or []
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return [str(exc)]

    duplicate_ids = sorted(
        task_id for task_id, count in Counter(task_ids).items() if count > 1
    )
    if duplicate_ids:
        problems.append("duplicate catalog task ids: " + ", ".join(duplicate_ids))
    malformed_ids = sorted(task_id for task_id in task_ids if not TASK_RE.fullmatch(task_id))
    if malformed_ids:
        problems.append("malformed catalog task ids: " + ", ".join(malformed_ids))
    expected_sequence = expected_task_sequence(task_ids)
    if task_ids != expected_sequence:
        problems.append(
            "catalog task ids must be contiguous and ordered: expected "
            + ", ".join(expected_sequence)
        )

    driver_ids = sorted(
        match.group(1)
        for path in (repo_root / "ref").glob("driving_example_T*.md")
        if (match := DRIVER_RE.fullmatch(path.name))
    )
    missing_drivers = sorted(set(task_ids) - set(driver_ids))
    extra_drivers = sorted(set(driver_ids) - set(task_ids))
    if missing_drivers:
        problems.append("catalog tasks missing drivers: " + ", ".join(missing_drivers))
    if extra_drivers:
        problems.append("drivers without catalog tasks: " + ", ".join(extra_drivers))

    markdown_path = repo_root / "ref/tasks_and_evaluations.md"
    try:
        markdown_sections = markdown_task_sections(markdown_path.read_text())
    except OSError as exc:
        problems.append(f"ref/tasks_and_evaluations.md: cannot read: {exc}")
        markdown_sections = {}
    for task in catalog_tasks:
        if not isinstance(task, dict) or not isinstance(task.get("id"), str):
            continue
        task_id = task["id"]
        section = markdown_sections.get(task_id)
        if section is None:
            problems.append(f"ref/tasks_and_evaluations.md: missing section for {task_id}")
            continue
        heading_name, section_text = section
        expected_name = task.get("task_name")
        if isinstance(expected_name, str) and heading_name != expected_name:
            problems.append(
                f"ref/tasks_and_evaluations.md: {task_id} heading {heading_name!r} "
                f"does not match catalog task_name {expected_name!r}"
            )
        for tool_ref in task.get("phenix_tool_refs") or []:
            if isinstance(tool_ref, str) and tool_ref not in section_text:
                problems.append(
                    f"ref/tasks_and_evaluations.md: {task_id} does not name "
                    f"catalog PHENIX tool {tool_ref!r}"
                )

    first_id, last_id = task_ids[0], task_ids[-1]
    expected_state = (first_id, last_id, len(task_ids), len(driver_ids))
    document_text: dict[str, str] = {}
    for relative_path in STATE_DOCUMENTS:
        path = repo_root / relative_path
        try:
            text = path.read_text()
        except OSError as exc:
            problems.append(f"{relative_path}: cannot read: {exc}")
            continue
        document_text[relative_path] = text
        markers = STATE_RE.findall(text)
        if len(markers) != 1:
            problems.append(
                f"{relative_path}: expected exactly one catalog-state marker, found {len(markers)}"
            )
        else:
            actual_state = (
                markers[0][0],
                markers[0][1],
                int(markers[0][2]),
                int(markers[0][3]),
            )
            if actual_state != expected_state:
                problems.append(
                    f"{relative_path}: catalog-state marker {actual_state!r} does not match "
                    f"catalog/drivers {expected_state!r}"
                )
        for stale in STALE_TEXT.get(relative_path, ()):
            if stale in text:
                problems.append(f"{relative_path}: stale claim remains: {stale!r}")

    for task_id, wrappers in RUNNABLE_WRAPPERS.items():
        if task_id not in task_ids:
            continue
        for wrapper in wrappers:
            if not (repo_root / wrapper).is_file():
                problems.append(f"{task_id}: runnable wrapper is missing: {wrapper}")
            for relative_path in WRAPPER_DOCUMENTS:
                text = document_text.get(relative_path, "")
                if wrapper not in text:
                    problems.append(
                        f"{relative_path}: does not name runnable {task_id} wrapper {wrapper}"
                    )

    return problems


def main() -> int:
    repo_root = Path(__file__).resolve().parent.parent
    problems = collect_problems(repo_root)
    if problems:
        print("documentation state is inconsistent:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("documentation state matches ref/catalog.yaml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
