#!/usr/bin/env python3
"""Diagnose #906's retention snapshot race (2026-10-16).

Inputs: the existing disposable retention fixture/recipe, Git on PATH, optional
setup-only Git configuration, and an iteration limit. Output: JSON on stdout with
full changed-path tuples and Git Trace2 events. No real repository is modified.
"""
from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import unittest
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_inventory_storage import FixtureTests, Tree, snapshot  # noqa: E402
from test_retention_skill_commands import PACK_RECIPE, SkillCommandTests  # noqa: E402


def diagnose(configs: list[str]) -> dict:
    """Run the documented recipe once and retain diagnostics before fixture cleanup."""
    original_git = Tree.git
    config_args = [arg for setting in configs for arg in ("-c", setting)]

    def traced_git(tree, *args, cwd=None):
        trace = tree.outside / "git-trace.jsonl"
        with mock.patch.dict(os.environ, GIT_TRACE2_EVENT=str(trace)):
            return original_git(tree, *config_args, *args, cwd=cwd)

    case = SkillCommandTests("test_pack_recipe_measures_without_writing_objects")
    record = {}
    try:
        with mock.patch.object(Tree, "git", traced_git):
            case.setUp()
        trace = case.tree.outside / "git-trace.jsonl"
        before = snapshot(case.tree.root)
        with mock.patch.dict(os.environ, GIT_TRACE2_EVENT=str(trace)):
            result = case.shell(PACK_RECIPE)
        after = snapshot(case.tree.root)
        record.update(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr,
                      changes={path: {"before": before.get(path), "after": after.get(path)}
                               for path in sorted(before.keys() | after.keys())
                               if before.get(path) != after.get(path)})
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if hasattr(case, "tree"):
            trace = case.tree.outside / "git-trace.jsonl"
            if trace.exists():
                record["trace2"] = trace.read_text().splitlines()
        case.doCleanups()
    return record


def check_regression() -> dict:
    """Run the new behavioral guard against current and pre-#906 setup in memory."""
    def historical_git(tree, *args, cwd=None):
        # Exact setup invocation from e59578f; never change the reviewed worktree.
        return subprocess.run(["git", "-C", str(cwd or tree.root), *args], check=True,
                              capture_output=True, text=True, timeout=60).stdout

    records = {}
    for name, implementation in (("current", Tree.git), ("historical", historical_git)):
        output = io.StringIO()
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(FixtureTests)
        with mock.patch.object(Tree, "git", implementation):
            result = unittest.TextTestRunner(stream=output).run(suite)
        output_text = output.getvalue().replace(str(Path(__file__).resolve().parents[2]), "<repo>")
        records[name] = {"successful": result.wasSuccessful(), "output": output_text,
                         "errors": len(result.errors), "failures": len(result.failures)}
    records["expected_regression_detected"] = (
        records["current"]["successful"] and records["historical"]["errors"] == 0
        and records["historical"]["failures"] == 2
        and "fixture setup launched automatic maintenance" in records["historical"]["output"])
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=5)
    parser.add_argument("--setup-config", action="append", default=[], metavar="KEY=VALUE",
                        help="Git -c setting for fixture setup only; recipe is unchanged")
    parser.add_argument("--check-regression", action="store_true",
                        help="verify the new guard fails against pre-#906 setup in memory")
    args = parser.parse_args()
    if not 1 <= args.iterations <= 100:
        parser.error("--iterations must be between 1 and 100")
    version = subprocess.run(["git", "--version"], check=True, capture_output=True,
                             text=True, timeout=10).stdout.strip()
    if args.check_regression:
        record = check_regression()
        print(json.dumps({"git_version": version, **record}, indent=2))
        return int(not record["expected_regression_detected"])
    records = [diagnose(args.setup_config) for _ in range(args.iterations)]
    print(json.dumps({"git_version": version, "platform": platform.platform(),
                      "setup_config": args.setup_config,
                      "snapshot_fields": ["type", "mode", "size", "mtime_ns", "inode", "links",
                                          "optional content sha256 or symlink target"],
                      "iterations": records}, indent=2))
    return int(any("error" in row or row.get("returncode") != 0 for row in records))


if __name__ == "__main__":
    raise SystemExit(main())
