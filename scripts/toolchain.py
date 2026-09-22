#!/usr/bin/env python3
"""Shared external-tool configuration and shell-free subprocess adapters.

All scientific inputs are passed as argument-vector elements.  The sole shell
boundary is :func:`ccp4_environment`, because CCP4 distributes a setup script
that must be sourced.  Its command is fixed; the setup path is positional data,
never interpolated shell syntax.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import IO, Mapping, Sequence


PHENIX_VERSION = "2.0-5936"
CCP4_VERSION = "9.0.015"
TMALIGN_VERSION = "20220412"
DSSP_VERSION = "4.6.1"
PROBE_VERSION = "2.26.021123"
REDUCE_VERSION = "4.16.250520"
GEMMI_VERSION = "0.7.5"


def _configured_path(environment_name: str, default: Path) -> Path:
    return Path(os.environ.get(environment_name, str(default))).expanduser()


PHENIX_BIN = _configured_path(
    "PROTSTRUCT_PHENIX_BIN", Path.home() / f"phenix-{PHENIX_VERSION}" / "phenix_bin"
)
CCP4_SETUP = _configured_path(
    "PROTSTRUCT_CCP4_SETUP",
    Path("/Applications")
    / f"ccp4-{CCP4_VERSION}-shelx-arpwarp-macosarm"
    / "ccp4-9"
    / "bin"
    / "ccp4.setup-sh",
)
TMALIGN = _configured_path(
    "PROTSTRUCT_TMALIGN", Path.home() / "tools" / "tmalign" / "TMalign"
)
REDUCE = _configured_path(
    "PROTSTRUCT_REDUCE",
    Path.home() / "tools" / "reduce-src" / "build" / "reduce_src" / "reduce",
)
PROBE = _configured_path(
    "PROTSTRUCT_PROBE", Path.home() / "tools" / "probe-src" / "probe"
)
DSSP = _configured_path("PROTSTRUCT_DSSP", Path("mkdssp"))
# The gemmi CLI is optional (the locked wheel ships the Python module only).
# Bare name => PATH discovery; set PROTSTRUCT_GEMMI to pin a binary (#496).
GEMMI = _configured_path("PROTSTRUCT_GEMMI", Path("gemmi"))

EXTERNAL_TOOL_SPECS = {
    "PHENIX": {
        "expected_version": PHENIX_VERSION,
        "configured_path": PHENIX_BIN,
        "executables": ("phenix.version", "phenix.refine"),
        "version_args": (),
    },
    "CCP4": {
        "expected_version": CCP4_VERSION,
        "configured_path": CCP4_SETUP,
        "executables": ("refmac5", "ctruncate"),
        "version_args": None,
        "availability_probe": "configured_file",
    },
    "TM-align": {
        "expected_version": TMALIGN_VERSION,
        "configured_path": TMALIGN,
        "executables": ("TMalign",),
        "version_args": (),
    },
    "DSSP": {
        "expected_version": DSSP_VERSION,
        "configured_path": DSSP,
        "executables": ("mkdssp",),
        "version_args": ("--version",),
    },
    "probe": {
        "expected_version": PROBE_VERSION,
        "configured_path": PROBE,
        "executables": ("probe",),
        "version_args": ("-version",),
    },
    "gemmi": {
        "expected_version": GEMMI_VERSION,
        "configured_path": GEMMI,
        "executables": ("gemmi",),
        "version_args": ("--version",),
    },
    "reduce": {
        "expected_version": REDUCE_VERSION,
        "configured_path": REDUCE,
        "executables": ("reduce",),
        "version_args": ("-version",),
    },
}


def phenix(executable: str) -> Path:
    """Return one executable from the configured, version-pinned PHENIX tree."""
    return PHENIX_BIN / executable


def _discover_executable(
    configured_path: Path, executable_names: tuple[str, ...]
) -> Path | None:
    candidates = []
    is_bare_name = not configured_path.is_absolute() and configured_path.parent == Path(".")
    if not is_bare_name:
        if configured_path.is_dir():
            candidates.extend(configured_path / name for name in executable_names)
        elif configured_path.is_file() and os.access(configured_path, os.X_OK):
            candidates.append(configured_path)
        for candidate in candidates:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate
    path_names = (
        (configured_path.name, *executable_names)
        if is_bare_name and configured_path.name not in executable_names
        else executable_names
    )
    for name in path_names:
        if discovered := shutil.which(name):
            return Path(discovered)
    return None


def gemmi_executable(required: bool = True) -> Path | None:
    """Resolve the gemmi CLI once, to an absolute path, from PROTSTRUCT_GEMMI or
    PATH. Callers pass the RESOLVED path in argv so a later environment rewrite
    (``ccp4=True``) cannot swap binaries between the manifest and the measurement
    (#496). ``required=False`` returns None when absent; otherwise the failure is
    named, never a bare FileNotFoundError from subprocess."""
    executable = _discover_executable(GEMMI, ("gemmi",))
    if executable is None:
        if required:
            raise FileNotFoundError(
                "gemmi CLI not found on PATH; install it or set PROTSTRUCT_GEMMI"
            )
        return None
    return executable.resolve()


def dssp_executable(required: bool = True) -> Path | None:
    """Resolve mkdssp from the configured PROTSTRUCT_DSSP path or PATH."""
    executable = _discover_executable(DSSP, ("mkdssp",))
    if executable is None:
        if required:
            raise FileNotFoundError(
                "mkdssp not found; install DSSP or set PROTSTRUCT_DSSP"
            )
        return None
    return executable.resolve()


def _version_output(executable: Path, arguments: tuple[str, ...]) -> str | None:
    try:
        process = subprocess.run(
            [str(executable), *arguments],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = (process.stdout + "\n" + process.stderr).strip().splitlines()
    return " | ".join(lines[:3])[:500] or None


def external_tool_report() -> dict[str, dict[str, str | bool | None]]:
    """Return configured paths and provenance-labeled version evidence.

    ``reported_version`` is reserved for output measured from an executable.
    Tools without a reliable version command may carry a weaker
    ``configured_path_version_hint``.  ``version_divergence`` makes a mismatch
    explicit in every benchmark environment record instead of silently
    treating an override as equivalent to the registered binary.
    """
    report: dict[str, dict[str, str | bool | None]] = {}
    for name, specification in EXTERNAL_TOOL_SPECS.items():
        configured = specification["configured_path"]
        executable = _discover_executable(configured, specification["executables"])
        version_args = specification["version_args"]
        reported_version = (
            _version_output(executable, version_args)
            if executable is not None and version_args is not None
            else None
        )
        expected_version = specification["expected_version"]
        path_version_hint = (
            expected_version if expected_version in str(configured) else None
        )
        availability_probe = specification.get("availability_probe", "executable")
        available = (
            configured.is_file()
            if availability_probe == "configured_file"
            else executable is not None
        )
        if not available:
            version_divergence = None
        elif reported_version is not None:
            version_divergence = expected_version not in reported_version
        else:
            version_divergence = path_version_hint is None
        report[name] = {
            "expected_version": expected_version,
            "configured_path": str(configured),
            "availability_probe": availability_probe,
            "discovered_executable": str(executable) if executable else None,
            "reported_version": reported_version,
            "reported_version_source": "command_output" if reported_version else None,
            "configured_path_version_hint": path_version_hint,
            "version_divergence": version_divergence,
            "available": available,
        }
    return report


def split_args(arguments: str) -> list[str]:
    """Split a trusted PHIL/options fragment without invoking a shell."""
    return shlex.split(arguments)


def _argv(arguments: Sequence[str | os.PathLike[str]]) -> list[str]:
    return [os.fspath(argument) for argument in arguments]


@lru_cache(maxsize=None)
def ccp4_environment(setup_path: str | os.PathLike[str] = CCP4_SETUP) -> dict[str, str]:
    """Return the environment produced by the configured CCP4 setup script.

    CCP4's vendor script can only be sourced.  The fixed adapter below passes
    its path as ``$1`` to a clean Bash process, so spaces/metacharacters in the
    path are not evaluated as shell syntax.  No benchmark argument crosses
    this boundary.
    """
    setup = Path(setup_path)
    if not setup.is_file():
        raise FileNotFoundError(
            f"CCP4 setup script not found: {setup}. Set PROTSTRUCT_CCP4_SETUP."
        )
    process = subprocess.run(
        [
            "/bin/bash",
            "--noprofile",
            "--norc",
            "-c",
            'set -a; . "$1" >/dev/null 2>&1; env -0',
            "protstruct-ccp4",
            str(setup),
        ],
        check=False,
        capture_output=True,
    )
    if process.returncode:
        diagnosis = process.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"CCP4 setup failed ({process.returncode}): {diagnosis}")
    environment = dict(os.environ)
    for entry in process.stdout.split(b"\0"):
        if not entry or b"=" not in entry:
            continue
        key, value = entry.split(b"=", 1)
        environment[key.decode(errors="surrogateescape")] = value.decode(
            errors="surrogateescape"
        )
    return environment


def run_logged(
    arguments: Sequence[str | os.PathLike[str]],
    log_path: str | os.PathLike[str],
    *,
    cwd: str | os.PathLike[str] | None = None,
    timeout: float | None = None,
    env: Mapping[str, str] | None = None,
    ccp4: bool = False,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run an argument vector with combined stdout/stderr written to a log."""
    environment = ccp4_environment() if ccp4 else (dict(env) if env else None)
    with Path(log_path).open("w") as log_handle:
        return subprocess.run(
            _argv(arguments),
            cwd=cwd,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
            input=input_text,
            timeout=timeout,
            env=environment,
            check=False,
        )


def run_to_file(
    arguments: Sequence[str | os.PathLike[str]],
    output_path: str | os.PathLike[str],
    *,
    cwd: str | os.PathLike[str] | None = None,
    timeout: float | None = None,
    env: Mapping[str, str] | None = None,
    ccp4: bool = False,
    stderr: int | IO[str] = subprocess.DEVNULL,
) -> subprocess.CompletedProcess[str]:
    """Run an argument vector with stdout written to a data/output file."""
    environment = ccp4_environment() if ccp4 else (dict(env) if env else None)
    with Path(output_path).open("w") as output_handle:
        return subprocess.run(
            _argv(arguments),
            cwd=cwd,
            stdout=output_handle,
            stderr=stderr,
            text=True,
            timeout=timeout,
            env=environment,
            check=False,
        )


def run_capture(
    arguments: Sequence[str | os.PathLike[str]],
    *,
    cwd: str | os.PathLike[str] | None = None,
    timeout: float | None = None,
    env: Mapping[str, str] | None = None,
    ccp4: bool = False,
    input_text: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run an argument vector and capture stdout/stderr as text."""
    environment = ccp4_environment() if ccp4 else (dict(env) if env else None)
    return subprocess.run(
        _argv(arguments),
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=environment,
        input=input_text,
        check=False,
    )


def run_refmac(
    model: str | os.PathLike[str],
    reflections: str | os.PathLike[str],
    xyz_output: str | os.PathLike[str],
    hkl_output: str | os.PathLike[str],
    log_path: str | os.PathLike[str],
    keywords: str,
    *,
    cwd: str | os.PathLike[str],
    timeout: float = 1800,
) -> subprocess.CompletedProcess[str]:
    """Run REFMAC with its keyword block on stdin, without a heredoc shell."""
    return run_logged(
        [
            "refmac5",
            "XYZIN",
            model,
            "HKLIN",
            reflections,
            "XYZOUT",
            xyz_output,
            "HKLOUT",
            hkl_output,
        ],
        log_path,
        cwd=cwd,
        timeout=timeout,
        ccp4=True,
        input_text=keywords,
    )
