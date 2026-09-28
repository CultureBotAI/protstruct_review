#!/usr/bin/env python3
"""Version metadata emitted before every benchmark run."""

from __future__ import annotations

import importlib.metadata
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from toolchain import external_tool_report


PYTHON_DISTRIBUTIONS = (
    "PyYAML",
    "pydantic",
    "linkml",
    "numpy",
    "scipy",
    "gemmi",
    "biotite",
    "DockQ",
)

def _distribution_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for distribution in PYTHON_DISTRIBUTIONS:
        try:
            versions[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            versions[distribution] = None
    return versions


def benchmark_environment() -> dict[str, object]:
    """Return actual Python versions and pinned/discovered external tool state."""
    return {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable": sys.executable,
        },
        "python_packages": _distribution_versions(),
        "external_tools": external_tool_report(),
    }


def announce_benchmark_environment(stream: TextIO = sys.stderr) -> dict[str, object]:
    """Write one JSON metadata record before measurements and return it."""
    metadata = benchmark_environment()
    print(json.dumps({"benchmark_environment": metadata}, sort_keys=True), file=stream)
    return metadata


if __name__ == "__main__":
    announce_benchmark_environment(sys.stdout)
