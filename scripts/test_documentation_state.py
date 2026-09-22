#!/usr/bin/env python3
"""Regression tests for the catalog-derived documentation-state guard."""

from __future__ import annotations

import tempfile
from pathlib import Path

import yaml

import check_documentation_state as cds


def make_repo(root: Path, task_ids: tuple[str, ...] = ("T01", "T02")) -> None:
    (root / "ref").mkdir(parents=True)
    (root / "schemas").mkdir()
    (root / ".claude/skills/protstruct-eval").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "ref/catalog.yaml").write_text(
        yaml.safe_dump({
            "catalog_tasks": [
                {
                    "id": task_id,
                    "task_name": f"Task {task_id}",
                    "phenix_tool_refs": [f"phenix.{task_id.lower()}"],
                }
                for task_id in task_ids
            ]
        })
    )
    (root / "ref/tasks_and_evaluations.md").write_text(
        "\n\n".join(
            f"### {task_id} — Task {task_id}\n\n"
            f"- **PHENIX tool(s):** `phenix.{task_id.lower()}`"
            for task_id in task_ids
        )
        + "\n"
    )
    for task_id in task_ids:
        (root / f"ref/driving_example_{task_id}.md").write_text("driver\n")

    state = (
        f"catalog-state: tasks={task_ids[0]}–{task_ids[-1]}; "
        f"count={len(task_ids)}; drivers={len(task_ids)}"
    )
    wrapper_text = "\n".join(
        wrapper
        for task_id, wrappers in cds.RUNNABLE_WRAPPERS.items()
        if task_id in task_ids
        for wrapper in wrappers
    )
    for relative_path in cds.STATE_DOCUMENTS:
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{state}\n{wrapper_text}\n")
    for task_id, wrappers in cds.RUNNABLE_WRAPPERS.items():
        if task_id in task_ids:
            for wrapper in wrappers:
                (root / wrapper).write_text("wrapper\n")


def check(label: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"PASS  {label}")


with tempfile.TemporaryDirectory() as tmp:
    repo = Path(tmp)
    make_repo(repo)
    check("consistent catalog, drivers, and markers pass", not cds.collect_problems(repo))

with tempfile.TemporaryDirectory() as tmp:
    repo = Path(tmp)
    make_repo(repo)
    (repo / "ref/driving_example_T02.md").unlink()
    problems = cds.collect_problems(repo)
    check("a catalog task without a driver fails", any("missing drivers: T02" in p for p in problems))

with tempfile.TemporaryDirectory() as tmp:
    repo = Path(tmp)
    make_repo(repo)
    path = repo / "schemas/README.md"
    path.write_text(path.read_text().replace("count=2", "count=1"))
    problems = cds.collect_problems(repo)
    check("a stale documented task count fails", any("schemas/README.md" in p for p in problems))

with tempfile.TemporaryDirectory() as tmp:
    repo = Path(tmp)
    make_repo(repo, ("T01", "T02", "T03"))
    (repo / "ref/driving_example_T03.md").unlink()
    problems = cds.collect_problems(repo)
    check(
        "adding a catalog task without its documentation state is caught",
        any("missing drivers: T03" in p for p in problems)
        and any("catalog-state marker" in p for p in problems),
    )

with tempfile.TemporaryDirectory() as tmp:
    repo = Path(tmp)
    make_repo(repo)
    path = repo / "ref/tasks_and_evaluations.md"
    path.write_text(path.read_text().replace("`phenix.t02`", "`different.tool`"))
    problems = cds.collect_problems(repo)
    check(
        "a task section missing its catalog PHENIX tool is caught",
        any("T02" in problem and "phenix.t02" in problem for problem in problems),
    )

print("\nall documentation-state unit tests passed")
