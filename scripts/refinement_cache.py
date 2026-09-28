"""Content/build-bound caches for opt-in refinement benchmarks (#777).

The caller supplies freshly measured PHENIX build evidence and a runner adapter.
Arguments are exact argv elements, without argv[0]. Only explicitly typed
OutputTemplate elements expand {operation_dir}; ordinary strings and Paths are literal.
Declare every scientific input, and every artifact needed to interpret results.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Mapping, NamedTuple, Sequence

import toolchain


class CacheEvidenceError(RuntimeError):
    """Evidence is absent, incomplete, changed or incompatible."""


class OperationFailed(CacheEvidenceError):
    """A fresh command failed; its retained log may explain an operational skip."""

    def __init__(self, message: str, log_path: Path):
        super().__init__(message)
        self.log_path = log_path


class OutputTemplate(NamedTuple):
    """An explicitly templated output argument; never use for scientific inputs."""

    value: str


def _argument_identity(value: str | Path | OutputTemplate) -> dict[str, str]:
    if isinstance(value, OutputTemplate):
        return {"output_template": value.value}
    if isinstance(value, Path):
        return {"literal": str(value.resolve())}
    if isinstance(value, str):
        return {"literal": value}
    raise TypeError("Arguments must be strings, Paths or explicit OutputTemplates")


def sha256(path: Path) -> str:
    """Stream large maps rather than loading them into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as source:
        before = os.fstat(source.fileno())
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
        after_stream = os.fstat(source.fileno())
        after = path.stat()
    signatures = [(item.st_size, item.st_mtime_ns, item.st_ino)
                  for item in (before, after_stream, after)]
    if len(set(signatures)) != 1:
        raise CacheEvidenceError(f"File changed while hashing: {path}")
    return digest.hexdigest()


def file_identity(path: Path) -> dict:
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or not resolved.stat().st_size:
        raise CacheEvidenceError(f"Nonempty input file required: {path}")
    return {"path": str(resolved), "sha256": sha256(resolved)}


def _build_is_measured(build: Mapping) -> bool:
    return (
        build.get("reported_version_source") == "command_output"
        and isinstance(build.get("reported_version"), str)
        and toolchain.parse_phenix_build(build["reported_version"]) is not None
    )


def _artifact(root: Path, relative: str) -> Path:
    path = root / relative
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise CacheEvidenceError(f"Invalid cached artifact: {path}")
    return path


def _read_success(destination: Path, invocation: dict) -> dict[str, Path]:
    """Never adopt an old filename-only cache or silently repair damaged evidence."""
    try:
        if destination.is_symlink() or not destination.is_dir():
            raise CacheEvidenceError(f"Invalid operation directory: {destination}")
        bundle = destination / "bundle"
        if bundle.is_symlink():
            raise CacheEvidenceError(f"Invalid operation bundle: {bundle}")
        record = json.loads(_artifact(bundle, "success.json").read_text())
        if (not isinstance(record, dict) or record.get("invocation") != invocation
                or type(record.get("returncode")) is not int or record["returncode"] != 0
                or record.get("reusable") is not True
                or not _build_is_measured(invocation["measured_build"])):
            raise CacheEvidenceError(f"Incompatible success evidence: {destination}")
        if json.loads(_artifact(bundle, "invocation.json").read_text()) != invocation:
            raise CacheEvidenceError(f"Contradictory invocation evidence: {destination}")
        original_cwd = record.get("execution_directory")
        if (not isinstance(original_cwd, str) or not Path(original_cwd).is_absolute()
                or str(Path(original_cwd).resolve()) != original_cwd
                or Path(original_cwd).parent != destination.parent
                or not Path(original_cwd).name.startswith(f".attempt-{destination.name[:16]}-")):
            raise CacheEvidenceError(f"Invalid execution directory: {destination}")
        expected_argv = _expand_arguments(invocation["argv_template"], original_cwd)
        if record.get("executed_argv") != expected_argv:
            raise CacheEvidenceError(f"Contradictory executed command: {destination}")
        artifacts = record.get("artifacts")
        expected = {"stdout", *invocation["required_outputs"]}
        if not isinstance(artifacts, dict) or set(artifacts) != expected:
            raise CacheEvidenceError(f"Incomplete output set: {destination}")
        paths = {}
        for name, entry in artifacts.items():
            path = _artifact(bundle, entry["path"])
            pattern = "stdout.log" if name == "stdout" else invocation["required_outputs"][name]
            if sorted(bundle.glob(pattern)) != [path] or (name != "stdout" and not path.stat().st_size):
                raise CacheEvidenceError(f"Output does not match its declared role: {path}")
            if sha256(path) != entry["sha256"]:
                raise CacheEvidenceError(f"Changed cached artifact: {path}")
            paths[name] = path
        return {**paths, "manifest": bundle / "success.json"}
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise CacheEvidenceError(f"Invalid cache evidence at {destination}: {error}") from error


def _expand_arguments(template: list[dict[str, str]], directory: str) -> list[str]:
    return [element["literal"] if "literal" in element else
            element["output_template"].replace("{operation_dir}", directory)
            for element in template]


def cached_operation(
    work: Path,
    name: str,
    *,
    inputs: Mapping[str, Path],
    launcher: Path,
    measured_build: Mapping,
    arguments: Sequence[str | Path | OutputTemplate],
    required_outputs: Mapping[str, str],
    execute: Callable[[list[str], Path, Path], int],
) -> dict[str, Path]:
    """Run/reuse one operation, returning named artifacts, stdout, and manifest.

    ``execute(argv, operation_dir, stdout_log)`` must return the process status;
    it must retain the complete combined log at stdout_log. Timeouts propagate.
    Each output glob must identify exactly one nonempty file in the fresh directory.
    Unknown/unmeasured build evidence permits a fresh run, never cache reuse.
    Malformed existing success evidence fails hard, without overwriting history.
    """
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
        raise ValueError("Operation name must be a simple filename")
    if {"stdout", "manifest"} & set(required_outputs):
        raise ValueError("stdout and manifest are reserved evidence names")
    for pattern in required_outputs.values():
        if not pattern or Path(pattern).is_absolute() or ".." in Path(pattern).parts:
            raise ValueError(f"Output pattern must stay inside the operation: {pattern}")
    launcher_id = file_identity(launcher)
    invocation = {
        "contract": 1,
        "name": name,
        "inputs": {key: file_identity(path) for key, path in inputs.items()},
        "launcher": {"configured_path": str(launcher), **launcher_id},
        "measured_build": dict(measured_build),
        "argv_template": [{"literal": launcher_id["path"]}, *(
            _argument_identity(value) for value in arguments
        )],
        "required_outputs": dict(required_outputs),
    }
    serialized = json.dumps(invocation, sort_keys=True, allow_nan=False)
    invocation = json.loads(serialized)  # Normalize caller tuples to their JSON form.
    key = hashlib.sha256(serialized.encode()).hexdigest()
    family = work.resolve() / "refinement_cache_v1" / name
    destination = family / key
    reusable = _build_is_measured(measured_build)
    if reusable and (destination.exists() or destination.is_symlink()):
        return _read_success(destination, invocation)

    family.mkdir(parents=True, exist_ok=True)
    attempt = Path(tempfile.mkdtemp(prefix=f".attempt-{key[:16]}-", dir=family))
    argv = _expand_arguments(invocation["argv_template"], str(attempt))
    log = attempt / "stdout.log"
    # Retain invocation identity even when the process times out or is killed.
    (attempt / "invocation.json").write_text(json.dumps(invocation, indent=2) + "\n")
    status = execute(argv, attempt, log)
    if type(status) is not int or status != 0:
        raise OperationFailed(f"Operation failed ({status}); retained attempt: {attempt}", log)
    try:
        paths = {"stdout": _artifact(attempt, "stdout.log")}
    except CacheEvidenceError as error:
        raise OperationFailed(f"Missing process log; retained attempt: {attempt}", log) from error
    for label, pattern in required_outputs.items():
        matches = sorted(attempt.glob(pattern))
        if len(matches) != 1:
            raise OperationFailed(f"Expected one {label} ({pattern}); retained attempt: {attempt}", log)
        try:
            path = _artifact(attempt, str(matches[0].relative_to(attempt)))
        except CacheEvidenceError as error:
            raise OperationFailed(f"Invalid {label}; retained attempt: {attempt}", log) from error
        if not path.stat().st_size:
            raise OperationFailed(f"Empty {label}; retained attempt: {attempt}", log)
        paths[label] = path
    for item in [*invocation["inputs"].values(), launcher_id]:
        if file_identity(Path(item["path"])) != item:
            raise CacheEvidenceError(f"Input changed during execution; retained attempt: {attempt}")
    record = {
        "invocation": invocation, "execution_directory": str(attempt),
        "executed_argv": argv, "returncode": status,
        "reusable": reusable,
        "artifacts": {name: {"path": str(path.relative_to(attempt)), "sha256": sha256(path)}
                      for name, path in paths.items()},
    }
    if not reusable:
        manifest = attempt / "uncached_success.json"
        manifest.write_text(json.dumps(record, indent=2) + "\n")
        return {**paths, "manifest": manifest}
    (attempt / "success.json").write_text(json.dumps(record, indent=2) + "\n")
    # Exclusive reservation prevents even an empty historical directory from being
    # replaced. A crash after mkdir leaves an invalid cache, never a reusable one.
    try:
        destination.mkdir()
    except FileExistsError:
        return _read_success(destination, invocation)
    attempt.rename(destination / "bundle")
    return _read_success(destination, invocation)


def cached_phenix_operation(
    work: Path,
    name: str,
    *,
    executable: str,
    inputs: Mapping[str, Path],
    arguments: Sequence[str | Path | OutputTemplate],
    required_outputs: Mapping[str, str],
    timeout: float,
    runner=None,
) -> dict[str, Path]:
    """Use the configured PHENIX executable and same-tree measured build record.

    A dispatcher hash plus measured release/build is not a hash of the entire
    installation: unversioned modifications to imported libraries are not detected.
    The version command is never resolved through PATH. If its evidence is absent,
    failing or unrecognized, the scientific run is retained but never cache-reused.
    """
    launcher = toolchain.phenix(executable)
    build = toolchain.phenix_build_evidence()
    if toolchain.phenix(executable) != launcher:
        raise CacheEvidenceError("PHENIX configuration changed during build measurement")
    run = runner if runner is not None else toolchain.run_logged

    def execute(argv: list[str], directory: Path, log: Path) -> int:
        try:
            return run(argv, log, cwd=directory, timeout=timeout).returncode
        except subprocess.TimeoutExpired as error:
            raise OperationFailed(f"PHENIX operation timed out; retained log: {log}", log) from error

    return cached_operation(work, name, inputs=inputs, launcher=launcher,
                            measured_build=build, arguments=arguments,
                            required_outputs=required_outputs, execute=execute)
