#!/usr/bin/env python3
"""Shared external-tool configuration and shell-free subprocess adapters.

All scientific inputs are passed as argument-vector elements.  The only shell
boundaries are :func:`ccp4_environment` and the version-only PHENIX setup probe
inside :func:`phenix_build_evidence`, because both vendors distribute setup
scripts that must be sourced.  Their commands are fixed; setup paths are passed
as positional data, never interpolated into shell syntax.  For PHENIX, only the
two setup-derived version variables (``PHENIX_VERSION`` and
``PHENIX_RELEASE_TAG``) are transferred to the ``phenix.version`` child process,
not the full sourced setup environment or scientific runner environments.
"""

from __future__ import annotations

import hashlib
import os
import re
import shlex
import shutil
import stat
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
REDUCE_HET_DICT = _configured_path(
    "PROTSTRUCT_REDUCE_HET_DICT",
    Path.home() / "tools" / "reduce-src" / "reduce_wwPDB_het_dict.txt",
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


_PHENIX_VERSION_VARIABLES = ("PHENIX_VERSION", "PHENIX_RELEASE_TAG")
_SHELL_HOOK_VARIABLES = (
    "BASH_ENV",
    "ENV",
    "SHELLOPTS",
    "BASHOPTS",
    "POSIXLY_CORRECT",
    "CDPATH",
    "GLOBIGNORE",
    "PROMPT_COMMAND",
    "PS4",
)
_PHENIX_SETUP_SCRIPT = (
    "builtin unset -f export unset printf . exit 2>/dev/null || true; "
    "builtin unset PHENIX_VERSION PHENIX_RELEASE_TAG BASH_ENV ENV; "
    'builtin . "$1"; '
    "status=$?; "
    'if [ "$status" -ne 0 ]; then builtin exit "$status"; fi; '
    'builtin printf "\\0PHENIX_VERSION=%s\\0PHENIX_RELEASE_TAG=%s\\0" '
    '"${PHENIX_VERSION+set}:${PHENIX_VERSION-}" '
    '"${PHENIX_RELEASE_TAG+set}:${PHENIX_RELEASE_TAG-}"'
)
_SETUP_OUTPUT_RE = re.compile(
    r"\0PHENIX_VERSION=(set:|:)([^\0]*)\0PHENIX_RELEASE_TAG=(set:|:)([^\0]*)\0\Z",
    re.S,
)


def phenix(executable: str) -> Path:
    """Return one executable from the configured, version-pinned PHENIX tree."""
    return PHENIX_BIN / executable


def phenix_setup_argv(setup_path: str | os.PathLike[str]) -> list[str]:
    """Return the fixed argument vector for the isolated PHENIX setup probe."""
    return [
        "/bin/bash",
        "--noprofile",
        "--norc",
        "-c",
        _PHENIX_SETUP_SCRIPT,
        "protstruct-phenix-setup",
        os.fspath(setup_path),
    ]


def parse_phenix_setup_build(fields: Mapping[str, object]) -> str | None:
    """Normalize setup-supplied PHENIX_VERSION / PHENIX_RELEASE_TAG fields."""
    if not isinstance(fields, Mapping):
        return None
    if set(fields) != set(_PHENIX_VERSION_VARIABLES):
        return None
    raw_version = fields.get("PHENIX_VERSION")
    raw_release = fields.get("PHENIX_RELEASE_TAG")
    if (
        not isinstance(raw_version, str)
        or not raw_version
        or raw_version != raw_version.strip()
        or any(char in raw_version for char in ("\n", "\r", "\0"))
    ):
        return None
    if raw_release is not None and (
        not isinstance(raw_release, str)
        or not raw_release
        or raw_release != raw_release.strip()
        or any(char in raw_release for char in ("\n", "\r", "\0"))
        or not re.fullmatch(r"\d+", raw_release)
    ):
        return None
    match = re.fullmatch(r"(\d+\.\d+(?:\.\d+)?)(?:-(\d+))?", raw_version)
    if not match:
        return None
    version, embedded_release = match.groups()
    release = raw_release if raw_release is not None else embedded_release
    if not release or not re.fullmatch(r"\d+", release):
        return None
    if embedded_release and embedded_release != release:
        return None
    return f"{version}-{release}"


def parse_phenix_build(output: str) -> str | None:
    """Parse PHENIX's own single-banner version fields, never a warning/cctbx token.

    The vendor banner prints Version and Release tag separately when its supplied
    environment is sourced; without that split, Version may contain the full tag.
    Unknown, duplicate, contradictory, multi-banner and development-tagged fields
    are not pins.
    """
    if not isinstance(output, str):
        return None
    lines = [line.strip() for line in output.splitlines()]
    compact = [
        (index, match.group(1).strip())
        for index, line in enumerate(lines)
        if (match := re.fullmatch(r"PHENIX(?: version:)? (.+)", line, re.IGNORECASE))
    ]
    headers = [
        index for index, line in enumerate(lines) if line.lower().startswith("phenix:")
    ]
    versions = [
        (index, line.partition(":")[2].strip())
        for index, line in enumerate(lines)
        if line.lower().startswith("version:")
    ]
    releases = [
        (index, line.partition(":")[2].strip())
        for index, line in enumerate(lines)
        if line.lower().startswith("release tag:")
    ]
    if compact:
        if len(compact) != 1 or headers or versions or releases:
            return None
        _, token = compact[0]
        return token if re.fullmatch(r"\d+\.\d+(?:\.\d+)?-\d+", token) else None
    if len(headers) != 1 or len(versions) != 1 or len(releases) > 1:
        return None
    header_index = headers[0]
    version_index, raw_version = versions[0]
    if version_index <= header_index:
        return None
    last_field_index = version_index
    if releases:
        release_index, raw_release = releases[0]
        if release_index <= version_index:
            return None
        last_field_index = release_index
    else:
        raw_release = None
    if any(
        re.fullmatch(r"-{3,}", line)
        for line in lines[header_index + 1 : last_field_index + 1]
    ):
        return None
    return parse_phenix_setup_build(
        {"PHENIX_VERSION": raw_version, "PHENIX_RELEASE_TAG": raw_release}
    )


def _is_shell_hook_variable(name: str, value: object) -> bool:
    if name in _PHENIX_VERSION_VARIABLES:
        return False
    return (
        name in _SHELL_HOOK_VARIABLES
        or name.startswith("BASH_FUNC_")
        or (isinstance(value, str) and value.lstrip().startswith("() {"))
    )


def _has_phenix_banner_fragment(text: str) -> bool:
    if not isinstance(text, str):
        return True
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if (
            line.lower().startswith(("phenix:", "version:", "release tag:", "cctbx tag:"))
            or re.fullmatch(r"PHENIX(?: version:)? .+", line, re.IGNORECASE)
            or re.fullmatch(r"-{3,}", line)
        ):
            return True
    return False


def _coerce_timeout_stream(stream: str | bytes | None) -> str:
    if stream is None:
        return ""
    if isinstance(stream, bytes):
        return stream.decode("utf-8", errors="replace")
    return str(stream)


def _strict_resolve(path: Path) -> Path:
    try:
        return path.resolve(strict=True)
    except RuntimeError as error:
        raise ValueError(str(error)) from error


def _phenix_configured_prefix(configured_bin: Path) -> Path:
    return (
        configured_bin.parent
        if configured_bin.name in {"phenix_bin", "bin"}
        else configured_bin
    )


def _regular_file_sha256(path: Path) -> str:
    info = os.stat(path)
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"Regular file required: {path}")
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _resolve_within_prefix(
    base_dir: Path,
    target: Path,
    configured_prefix: Path,
    resolved_prefix: Path,
    active_links: frozenset[Path] = frozenset(),
    hops: int = 0,
) -> Path:
    if hops > 40:
        raise ValueError(f"Symlink loop in PHENIX dispatcher: {target}")
    if target.is_absolute():
        if target.is_relative_to(resolved_prefix):
            parts = target.relative_to(resolved_prefix).parts
        elif target.is_relative_to(configured_prefix):
            parts = target.relative_to(configured_prefix).parts
        else:
            raise ValueError(
                f"PHENIX dispatcher symlink escapes installation prefix: {target}"
            )
        current = resolved_prefix
    else:
        if not base_dir.is_relative_to(resolved_prefix):
            raise ValueError(
                f"PHENIX dispatcher base directory escapes installation prefix: {base_dir}"
            )
        current = base_dir
        parts = target.parts
    for part in parts:
        if part in ("", "."):
            continue
        if part == "..":
            current = current.parent
            if not current.is_relative_to(resolved_prefix):
                raise ValueError(
                    f"PHENIX dispatcher path escapes installation prefix: {target}"
                )
            continue
        candidate = current / part
        if not candidate.is_relative_to(resolved_prefix):
            raise ValueError(
                f"PHENIX dispatcher path escapes installation prefix: {candidate}"
            )
        info = os.lstat(candidate)
        if stat.S_ISLNK(info.st_mode):
            if candidate in active_links:
                raise ValueError(
                    f"Symlink loop in PHENIX dispatcher: {candidate}"
                )
            link_target = Path(os.readlink(candidate))
            current = _resolve_within_prefix(
                current,
                link_target,
                configured_prefix,
                resolved_prefix,
                active_links | {candidate},
                hops + 1,
            )
        else:
            current = candidate
    if not current.is_relative_to(resolved_prefix):
        raise ValueError(
            f"PHENIX dispatcher path escapes installation prefix: {current}"
        )
    return current


def _resolve_phenix_dispatcher(configured_bin: Path) -> tuple[Path, Path, Path]:
    if not configured_bin.is_absolute():
        raise ValueError(f"PHENIX binary directory must be absolute: {configured_bin}")
    configured_prefix = _phenix_configured_prefix(configured_bin)
    if configured_bin.is_symlink() or configured_prefix.is_symlink():
        raise ValueError(
            f"PHENIX binary directory or prefix must not be a symlink: {configured_bin}"
        )
    resolved_prefix = _strict_resolve(configured_prefix)
    resolved_bin = _strict_resolve(configured_bin)
    if not resolved_prefix.is_dir() or not resolved_bin.is_dir():
        raise FileNotFoundError(f"PHENIX directory not found: {configured_bin}")
    if configured_bin == configured_prefix:
        if resolved_bin != resolved_prefix:
            raise ValueError(f"PHENIX prefix resolution mismatch: {configured_bin}")
    elif resolved_bin.parent != resolved_prefix or resolved_bin.name != configured_bin.name:
        raise ValueError(
            f"PHENIX binary directory escapes installation prefix: {configured_bin}"
        )
    configured_dispatcher = configured_bin / "phenix.version"
    walked_dispatcher = _resolve_within_prefix(
        resolved_bin,
        Path("phenix.version"),
        configured_prefix,
        resolved_prefix,
    )
    resolved_dispatcher = _strict_resolve(walked_dispatcher)
    if resolved_dispatcher != walked_dispatcher or not stat.S_ISREG(
        os.lstat(resolved_dispatcher).st_mode
    ):
        raise ValueError(
            f"PHENIX dispatcher must be a regular file: {configured_dispatcher}"
        )
    if (
        not resolved_dispatcher.is_relative_to(resolved_prefix)
        or resolved_dispatcher.name != "phenix.version"
        or resolved_dispatcher.parent
        not in {resolved_prefix, resolved_prefix / "bin", resolved_prefix / "phenix_bin"}
    ):
        raise ValueError(
            f"PHENIX dispatcher escapes installation prefix: {configured_dispatcher}"
        )
    return resolved_prefix, configured_dispatcher, resolved_dispatcher


def _resolve_phenix_setup(
    configured_prefix: Path, resolved_prefix: Path
) -> tuple[Path, Path]:
    configured_setup = configured_prefix / "phenix_env.sh"
    if configured_setup.is_symlink():
        raise ValueError(
            f"PHENIX setup script must not be a symlink: {configured_setup}"
        )
    resolved_setup = _strict_resolve(configured_setup)
    if not stat.S_ISREG(os.lstat(configured_setup).st_mode) or not stat.S_ISREG(
        os.lstat(resolved_setup).st_mode
    ):
        raise ValueError(
            f"PHENIX setup script must be a regular file: {configured_setup}"
        )
    if (
        resolved_setup.parent != resolved_prefix
        or resolved_setup.name != "phenix_env.sh"
        or not resolved_setup.is_relative_to(resolved_prefix)
    ):
        raise ValueError(
            f"PHENIX setup script escapes installation prefix: {configured_setup}"
        )
    return configured_setup, resolved_setup


def _run_phenix_setup(
    setup_argv: Sequence[str], *, env: Mapping[str, str], timeout: float = 10
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        _argv(setup_argv),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=dict(env),
        check=False,
    )


def _split_phenix_setup_output(
    raw_stdout: str,
) -> tuple[str, dict[str, str | None] | None]:
    match = _SETUP_OUTPUT_RE.search(raw_stdout)
    if not match:
        return raw_stdout, None
    chatter = raw_stdout[: match.start()]
    version_state, version_value, release_state, release_value = match.groups()
    fields: dict[str, str | None] = {
        "PHENIX_VERSION": version_value if version_state == "set:" else None,
        "PHENIX_RELEASE_TAG": release_value if release_state == "set:" else None,
    }
    return chatter, fields


def phenix_version_environment() -> dict[str, str]:
    """Ignore inherited banner overrides and shell startup hooks in version probes.

    Preserve the rest of the launch environment and never mutate the caller's.
    """
    environment: dict[str, str] = {}
    for name, value in os.environ.items():
        if name in _PHENIX_VERSION_VARIABLES or _is_shell_hook_variable(name, value):
            continue
        environment[name] = value
    return environment


def phenix_bare_build_evidence(*, configured_bin: Path | None = None) -> dict:
    """Probe the configured PHENIX dispatcher directly without sourcing phenix_env.sh."""
    return phenix_build_evidence(configured_bin=configured_bin, use_vendor_setup=False)


def phenix_build_evidence(
    *, configured_bin: Path | None = None, use_vendor_setup: bool = True
) -> dict:
    """Measure only this configured installation's version, without PATH fallback.

    Default build admission sources the configured installation's own
    ``phenix_env.sh`` in an isolated child process with inherited version
    overrides and shell startup hooks removed, extracts only ``PHENIX_VERSION``
    and ``PHENIX_RELEASE_TAG`` (never transferring ``PATH``, ``PHENIX``, or
    library environment variables from ``phenix_env.sh`` to ``phenix.version``
    or scientific runners), passes only those two version fields to the
    installation's resolved ``phenix.version`` dispatcher, and requires
    independent agreement between the setup-supplied version fields and the
    dispatcher banner.  While ``phenix_info.py`` includes a ``TAG`` fallback when
    those environment variables are unset, the checked ``2.0-5936`` installation
    ships no ``TAG`` file and supplies ``PHENIX_VERSION`` via ``phenix_env.sh``.
    Explicit bare probing remains available via ``use_vendor_setup=False`` (or
    :func:`phenix_bare_build_evidence`).

    Retain the complete command evidence. A path hint or configured expected version
    cannot authorize refinement-cache reuse. Hashes identify the setup script and
    version dispatcher, not every imported PHENIX library or the complete installed
    software tree.
    """
    bin_dir = PHENIX_BIN if configured_bin is None else Path(configured_bin)
    configured_dispatcher = bin_dir / "phenix.version"
    configured_prefix = _phenix_configured_prefix(bin_dir)
    configured_setup = configured_prefix / "phenix_env.sh"
    ignored_vars = sorted(
        name for name in _PHENIX_VERSION_VARIABLES if name in os.environ
    )
    ignored_hooks = sorted(
        name
        for name, value in os.environ.items()
        if _is_shell_hook_variable(name, value)
    )
    if use_vendor_setup:
        probe: dict[str, object] = {
            "probe_mode": "vendor_setup_environment",
            "configured_prefix": str(configured_prefix),
            "resolved_prefix": None,
            "setup_configured_path": str(configured_setup),
            "setup_resolved_path": None,
            "setup_sha256": None,
            "setup_argv": None,
            "setup_returncode": None,
            "setup_stdout": "",
            "setup_stderr": "",
            "setup_version_fields": None,
            "setup_parsed_build": None,
            "configured_path": str(configured_dispatcher),
            "resolved_path": None,
            "sha256": None,
            "argv": None,
            "returncode": None,
            "stdout": "",
            "stderr": "",
            "parsed_build": None,
            "ignored_inherited_version_variables": ignored_vars,
            "ignored_inherited_shell_hooks": ignored_hooks,
        }
    else:
        probe = {
            "probe_mode": "command_output",
            "configured_path": str(configured_dispatcher),
            "resolved_path": None,
            "sha256": None,
            "argv": None,
            "returncode": None,
            "stdout": "",
            "stderr": "",
            "parsed_build": None,
            "ignored_inherited_version_variables": ignored_vars,
            "ignored_inherited_shell_hooks": ignored_hooks,
        }
    result: dict[str, object] = {
        "reported_version_source": None,
        "reported_version": None,
        "parsed_build": None,
        "version_probe": probe,
    }
    try:
        resolved_prefix, _, resolved_dispatcher = _resolve_phenix_dispatcher(bin_dir)
        if use_vendor_setup:
            probe["resolved_prefix"] = str(resolved_prefix)
        probe["resolved_path"] = str(resolved_dispatcher)
        probe["sha256"] = _regular_file_sha256(resolved_dispatcher)
        if not use_vendor_setup:
            probe["argv"] = [str(resolved_dispatcher)]
            try:
                process = run_capture(
                    [resolved_dispatcher], timeout=10, env=phenix_version_environment()
                )
            except subprocess.TimeoutExpired as error:
                probe.update(
                    returncode=None,
                    stdout=_coerce_timeout_stream(error.stdout),
                    stderr=_coerce_timeout_stream(error.stderr),
                    error=f"{type(error).__name__}: {error}",
                )
                return result
            probe.update(
                returncode=process.returncode,
                stdout=process.stdout,
                stderr=process.stderr,
            )
            after_prefix, _, after_dispatcher = _resolve_phenix_dispatcher(bin_dir)
            unchanged = (
                after_prefix == resolved_prefix
                and after_dispatcher == resolved_dispatcher
                and probe["sha256"] == _regular_file_sha256(after_dispatcher)
            )
            if not unchanged:
                probe["error"] = "version executable changed during measurement"
            elif type(process.returncode) is not int or process.returncode != 0:
                probe["error"] = (
                    f"version executable exited with status {process.returncode}"
                )
            elif _has_phenix_banner_fragment(process.stderr):
                probe["error"] = "version banner fields split across stdout and stderr"
            else:
                parsed = parse_phenix_build(process.stdout)
                probe["parsed_build"] = parsed
                if parsed is not None:
                    result.update(
                        reported_version_source="command_output",
                        reported_version=process.stdout.strip(),
                        parsed_build=parsed,
                    )
                else:
                    probe["error"] = (
                        "version output did not contain a valid PHENIX build"
                    )
            return result

        _, resolved_setup = _resolve_phenix_setup(configured_prefix, resolved_prefix)
        probe["setup_resolved_path"] = str(resolved_setup)
        probe["setup_sha256"] = _regular_file_sha256(resolved_setup)
        setup_argv = phenix_setup_argv(resolved_setup)
        probe["setup_argv"] = setup_argv
        base_env = phenix_version_environment()
        try:
            setup_process = _run_phenix_setup(setup_argv, env=base_env, timeout=10)
        except subprocess.TimeoutExpired as error:
            probe.update(
                setup_returncode=None,
                setup_stdout=_coerce_timeout_stream(error.stdout),
                setup_stderr=_coerce_timeout_stream(error.stderr),
                setup_version_fields=None,
                setup_parsed_build=None,
                error=f"{type(error).__name__}: {error}",
            )
            return result
        probe["setup_returncode"] = setup_process.returncode
        probe["setup_stderr"] = setup_process.stderr
        if type(setup_process.returncode) is int and setup_process.returncode == 0:
            setup_chatter, setup_fields = _split_phenix_setup_output(
                setup_process.stdout
            )
            probe["setup_stdout"] = setup_chatter
            probe["setup_version_fields"] = setup_fields
        else:
            probe["setup_stdout"] = setup_process.stdout
            setup_fields = None
        setup_build = (
            parse_phenix_setup_build(setup_fields)
            if setup_fields is not None
            else None
        )
        probe["setup_parsed_build"] = setup_build
        if (
            type(setup_process.returncode) is int
            and setup_process.returncode == 0
            and setup_fields is not None
            and probe["setup_stdout"] == ""
            and probe["setup_stderr"] == ""
            and setup_build is not None
        ):
            dispatcher_env = dict(base_env)
            for key in _PHENIX_VERSION_VARIABLES:
                value = setup_fields.get(key)
                if value is not None:
                    dispatcher_env[key] = value
            probe["argv"] = [str(resolved_dispatcher)]
            try:
                process = run_capture(
                    [resolved_dispatcher], timeout=10, env=dispatcher_env
                )
            except subprocess.TimeoutExpired as error:
                probe.update(
                    returncode=None,
                    stdout=_coerce_timeout_stream(error.stdout),
                    stderr=_coerce_timeout_stream(error.stderr),
                    error=f"{type(error).__name__}: {error}",
                )
                return result
            probe.update(
                returncode=process.returncode,
                stdout=process.stdout,
                stderr=process.stderr,
            )
        after_prefix, _, after_dispatcher = _resolve_phenix_dispatcher(bin_dir)
        _, after_setup = _resolve_phenix_setup(configured_prefix, after_prefix)
        unchanged = (
            after_prefix == resolved_prefix
            and after_dispatcher == resolved_dispatcher
            and after_setup == resolved_setup
            and probe["sha256"] == _regular_file_sha256(after_dispatcher)
            and probe["setup_sha256"] == _regular_file_sha256(after_setup)
        )
        if not unchanged:
            probe["error"] = "setup or version executable changed during measurement"
        elif type(setup_process.returncode) is not int or setup_process.returncode != 0:
            probe["error"] = (
                f"vendor setup exited with status {setup_process.returncode}"
            )
        elif setup_fields is None:
            probe["error"] = (
                "vendor setup exited before reporting version variables"
            )
        elif probe["setup_stdout"] != "" or probe["setup_stderr"] != "":
            probe["error"] = "vendor setup produced unexpected output"
        elif setup_build is None:
            probe["error"] = "vendor setup did not supply a valid PHENIX version"
        elif type(probe["returncode"]) is not int or probe["returncode"] != 0:
            probe["error"] = (
                f"version executable exited with status {probe['returncode']}"
            )
        elif _has_phenix_banner_fragment(str(probe["stderr"])):
            probe["error"] = "version banner fields split across stdout and stderr"
        else:
            banner_build = parse_phenix_build(str(probe["stdout"]))
            probe["parsed_build"] = banner_build
            if banner_build is None:
                probe["error"] = (
                    "version output did not contain a valid PHENIX build"
                )
            elif banner_build != setup_build:
                probe["error"] = (
                    f"vendor setup build {setup_build!r} disagrees with "
                    f"banner build {banner_build!r}"
                )
            else:
                result.update(
                    reported_version_source="vendor_setup_environment",
                    reported_version=str(probe["stdout"]).strip(),
                    parsed_build=banner_build,
                )
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        probe["error"] = f"{type(error).__name__}: {error}"
    return result


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


def _version_output(
    executable: Path, arguments: tuple[str, ...], *, env: Mapping[str, str] | None = None,
) -> str | None:
    try:
        process = subprocess.run(
            [str(executable), *arguments],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
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
        configured = Path(specification["configured_path"])
        expected_version = specification["expected_version"]
        path_version_hint = (
            expected_version if expected_version in str(configured) else None
        )
        availability_probe = specification.get("availability_probe", "executable")
        if name == "PHENIX":
            evidence = phenix_build_evidence(configured_bin=configured)
            probe = evidence["version_probe"]
            discovered = probe.get("resolved_path")
            available = (
                isinstance(discovered, str)
                and bool(discovered)
                and Path(discovered).is_file()
                and os.access(discovered, os.X_OK)
            )
            reported_version = evidence.get("reported_version")
            reported_version_source = evidence.get("reported_version_source")
            parsed_build = evidence.get("parsed_build")
            if not available:
                version_divergence = None
            elif isinstance(parsed_build, str):
                version_divergence = parsed_build != expected_version
            else:
                version_divergence = True
            report[name] = {
                "expected_version": expected_version,
                "configured_path": str(configured),
                "availability_probe": availability_probe,
                "discovered_executable": discovered if available else None,
                "reported_version": (
                    reported_version if isinstance(reported_version, str) else None
                ),
                "reported_version_source": (
                    reported_version_source
                    if isinstance(reported_version_source, str)
                    else None
                ),
                "configured_path_version_hint": path_version_hint,
                "version_divergence": version_divergence,
                "available": available,
            }
            continue
        executable = _discover_executable(configured, specification["executables"])
        version_args = specification["version_args"]
        reported_version = (
            _version_output(executable, version_args)
            if executable is not None and version_args is not None
            else None
        )
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
    environment = ccp4_environment() if ccp4 else (dict(env) if env is not None else None)
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
    environment = ccp4_environment() if ccp4 else (dict(env) if env is not None else None)
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
    environment = ccp4_environment() if ccp4 else (dict(env) if env is not None else None)
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
