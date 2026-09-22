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
        any("T02" in problem and "missing catalog tool(s): phenix.t02" in problem for problem in problems),
    )

with tempfile.TemporaryDirectory() as tmp:
    repo = Path(tmp)
    make_repo(repo)
    path = repo / "ref/tasks_and_evaluations.md"
    path.write_text(
        path.read_text().replace(
            "- **PHENIX tool(s):** `phenix.t02`",
            "- **PHENIX tool(s):** `wrong.tool`\n\n"
            "The prose below mentions `phenix.t02`, but that does not repair the field.",
        )
    )
    problems = cds.collect_problems(repo)
    check(
        "correct tool mentioned outside an incorrect PHENIX field does not pass",
        any("T02" in problem and "missing catalog tool(s): phenix.t02" in problem for problem in problems)
        and any("T02" in problem and "absent from the catalog: wrong.tool" in problem for problem in problems),
    )

with tempfile.TemporaryDirectory() as tmp:
    repo = Path(tmp)
    make_repo(repo)
    path = repo / "ref/tasks_and_evaluations.md"
    path.write_text(
        path.read_text().replace(
            "- **PHENIX tool(s):** `phenix.t02`",
            "- **PHENIX tool(s):** `phenix.t02`, `wrong.tool`",
        )
    )
    problems = cds.collect_problems(repo)
    check(
        "an extra tool in the PHENIX field is caught",
        any("T02" in problem and "absent from the catalog: wrong.tool" in problem for problem in problems),
    )

with tempfile.TemporaryDirectory() as tmp:
    repo = Path(tmp)
    make_repo(repo)
    path = repo / "ref/tasks_and_evaluations.md"
    path.write_text(
        path.read_text().replace(
            "- **PHENIX tool(s):** `phenix.t02`",
            "- **PHENIX tool(s):** `phenix.t02`, phenix.wrong",
        )
    )
    problems = cds.collect_problems(repo)
    check(
        "an unquoted extra tool in the PHENIX field is caught",
        any("T02" in problem and "unquoted tool token(s): phenix.wrong" in problem
            for problem in problems),
    )

with tempfile.TemporaryDirectory() as tmp:
    repo = Path(tmp)
    make_repo(repo)
    path = repo / "ref/tasks_and_evaluations.md"
    path.write_text(
        path.read_text().replace(
            "- **PHENIX tool(s):** `phenix.t02`",
            "- **PHENIX tool(s):** `phenix.t02`, wrong",
        )
    )
    problems = cds.collect_problems(repo)
    check(
        "arbitrary residual text after the correct PHENIX tool is caught",
        any(
            "T02" in problem
            and "must contain only comma-separated backticked tools" in problem
            for problem in problems
        ),
    )

with tempfile.TemporaryDirectory() as tmp:
    repo = Path(tmp)
    make_repo(repo)
    path = repo / "ref/tasks_and_evaluations.md"
    path.write_text(
        path.read_text()
        + "\nwith matched 1.4 Å probe and protein-only atom selection\n"
    )
    problems = cds.collect_problems(repo)
    check(
        "the retired matched-protein-only BSA claim is caught",
        any("stale BSA claim" in problem for problem in problems),
    )

with tempfile.TemporaryDirectory() as tmp:
    repo = Path(tmp)
    make_repo(repo)
    path = repo / "ref/research/template_tolerance_review.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "Two provisional values now stand (interface BSA, Wilson B)\n"
    )
    problems = cds.collect_problems(repo)
    check(
        "the superseded provisional-BSA template claim is caught",
        any("template_tolerance_review.md" in problem and "stale BSA claim" in problem
            for problem in problems),
    )

with tempfile.TemporaryDirectory() as tmp:
    repo = Path(tmp)
    make_repo(repo)
    (repo / "ref/tool_recommendations.yaml").write_text(
        yaml.safe_dump({"tool_recommendations": [{"id": "REC_missing_date"}]})
    )
    problems = cds.collect_problems(repo)
    check(
        "a canonical recommendation without as_of_date is caught",
        any("REC_missing_date has no as_of_date" in problem for problem in problems),
    )
    check(
        "a canonical recommendation without effective_at is caught",
        any("REC_missing_date has no effective_at" in problem for problem in problems),
    )

with tempfile.TemporaryDirectory() as tmp:
    repo = Path(tmp)
    make_repo(repo)
    (repo / "ref/tool_assumptions.yaml").write_text(
        yaml.safe_dump({"assumptions": [{"id": "ASSUM_missing_date"}]})
    )
    problems = cds.collect_problems(repo)
    check(
        "a canonical tool assumption without as_of_date is caught",
        any("ASSUM_missing_date has no as_of_date" in problem for problem in problems),
    )
    check(
        "a canonical tool assumption without effective_at is caught",
        any("ASSUM_missing_date has no effective_at" in problem for problem in problems),
    )

print("\nall documentation-state unit tests passed")
