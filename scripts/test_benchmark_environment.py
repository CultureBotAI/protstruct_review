#!/usr/bin/env python3
"""Regression tests for benchmark version metadata."""

from __future__ import annotations

import io
import json
import ast
from pathlib import Path
from unittest import mock

import benchmark_environment as env


def check(label: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"PASS  {label}")


metadata = env.benchmark_environment()
check("Python version is recorded", bool(metadata["python"]["version"]))
check("Python executable is recorded", bool(metadata["python"]["executable"]))
check(
    "core dependency versions are recorded",
    all(metadata["python_packages"][name] for name in ("PyYAML", "pydantic", "linkml")),
)
check(
    "external tools carry expected versions and discovery state",
    all(
        tool["expected_version"] and isinstance(tool["available"], bool)
        for tool in metadata["external_tools"].values()
    ),
)

output = io.StringIO()
returned = env.announce_benchmark_environment(output)
record = json.loads(output.getvalue())
check("announcement is one parseable JSON record", record["benchmark_environment"] == returned)

with mock.patch.object(env, "external_tool_report", side_effect=AssertionError("unrelated probe")):
    for scoped in ({}, {"reduce": {"reported_version": "synthetic captured evidence"}}):
        scoped_output = io.StringIO()
        scoped_result = env.announce_benchmark_environment(scoped_output, external_tools=scoped)
        check("explicit scoped evidence avoids all external probes",
              scoped_result["external_tools"] == scoped)
        check("scoped environment still records Python/packages and one announcement",
              bool(scoped_result["python"]["version"])
              and bool(scoped_result["python_packages"]["PyYAML"])
              and json.loads(scoped_output.getvalue())["benchmark_environment"] == scoped_result)

scripts_dir = Path(__file__).resolve().parent
missing_announcements = []
for script in sorted(scripts_dir.glob("bench_*.py")):
    tree = ast.parse(script.read_text())
    main_function = next(
        (node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"),
        None,
    )
    calls = (
        [
            node
            for node in ast.walk(main_function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "announce_benchmark_environment"
        ]
        if main_function
        else []
    )
    if not calls:
        missing_announcements.append(script.name)
check("every benchmark runner announces versions first", not missing_announcements)

print("\nall benchmark-environment unit tests passed")
