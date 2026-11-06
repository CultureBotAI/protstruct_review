#!/usr/bin/env python3
"""Regression tests for benchmark version metadata."""

from __future__ import annotations

import ast
import io
import json
from pathlib import Path
from unittest import mock

import benchmark_environment as env
import toolchain


def check(label: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"PASS  {label}")


SYNTHETIC_EXTERNAL_TOOLS = {
    "PHENIX": {
        "expected_version": "2.0-5936",
        "configured_path": "/synthetic/phenix-2.0-5936/phenix_bin",
        "configured_version_hint": "2.0-5936",
        "resolved_executables": {
            "phenix.version": "/synthetic/phenix-2.0-5936/bin/phenix.version",
        },
        "available": True,
        "availability_probe": "executables",
        "reported_version": "2.0-5936",
        "reported_version_source": "vendor_setup_environment",
        "version_divergence": False,
    },
    "CCP4": {
        "expected_version": "9.0.015",
        "configured_path": "/synthetic/ccp4-9/bin/ccp4.setup-sh",
        "configured_version_hint": "9",
        "resolved_executables": {"refmac5": None},
        "available": True,
        "availability_probe": "configured_file",
        "reported_version": None,
        "reported_version_source": None,
        "version_divergence": False,
    },
}

with mock.patch.object(
    toolchain.subprocess,
    "run",
    side_effect=AssertionError("live subprocess forbidden in test_benchmark_environment"),
) as subprocess_tripwire:
    with mock.patch.object(
        env,
        "external_tool_report",
        return_value=SYNTHETIC_EXTERNAL_TOOLS,
    ) as mocked_default_report:
        metadata = env.benchmark_environment()
        check("Python version is recorded", bool(metadata["python"]["version"]))
        check("Python executable is recorded", bool(metadata["python"]["executable"]))
        check(
            "core dependency versions are recorded",
            all(
                metadata["python_packages"][name]
                for name in ("PyYAML", "pydantic", "linkml")
            ),
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
        check(
            "announcement is one parseable JSON record",
            record["benchmark_environment"] == returned,
        )
        check(
            "omitted external_tools dispatches through default external_tool_report route",
            mocked_default_report.call_count == 2
            and returned["external_tools"] == SYNTHETIC_EXTERNAL_TOOLS,
        )

    with mock.patch.object(
        env, "external_tool_report", side_effect=AssertionError("unrelated probe")
    ):
        for scoped in (
            {},
            {"reduce": {"reported_version": "synthetic captured evidence"}},
        ):
            scoped_output = io.StringIO()
            scoped_result = env.announce_benchmark_environment(
                scoped_output, external_tools=scoped
            )
            check(
                "explicit scoped evidence avoids all external probes",
                scoped_result["external_tools"] == scoped,
            )
            check(
                "scoped environment still records Python/packages and one announcement",
                bool(scoped_result["python"]["version"])
                and bool(scoped_result["python_packages"]["PyYAML"])
                and json.loads(scoped_output.getvalue())["benchmark_environment"]
                == scoped_result,
            )

    check(
        "no live subprocess was launched during metadata/announcement tests",
        subprocess_tripwire.call_count == 0,
    )
    tripwire_triggered = False
    with mock.patch.object(
        toolchain,
        "EXTERNAL_TOOL_SPECS",
        {
            "DSSP": {
                "expected_version": "4.4.0",
                "configured_path": Path(env.sys.executable),
                "executables": (Path(env.sys.executable).name,),
                "version_args": ("--version",),
            },
        },
    ):
        try:
            env.benchmark_environment()
        except AssertionError as exc:
            tripwire_triggered = "live subprocess forbidden" in str(exc)
    check(
        "no-live-subprocess tripwire blocks unmocked external_tool_report execution",
        tripwire_triggered and subprocess_tripwire.call_count == 1,
    )

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
