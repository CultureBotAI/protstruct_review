#!/usr/bin/env python3
"""Primitive types, file/environment guards, and closed outer profile validation.

Bounded slices (Tasks 653, 657, 663, and 658):
- Defines the frozen public dataclasses :class:`FilePin` and
  :class:`RefmacDiagnosticProfile`.
- Provides :func:`reject_conflicting_environment` to reject conflicting
  inherited or sourced environment variables without mutating the input mapping
  or ambient environment.
- Provides private streaming regular-file pin observation
  (:func:`_observe_regular_file_pin`) that validates the original lexical path
  with kernel lookup semantics, opens targets with non-blocking no-follow
  read-only flags so a regular-to-FIFO replacement cannot block, closes owned
  file descriptors on every error path before or during ``os.fdopen``,
  re-observes literal symlink edges and target identity after reading for
  pre/post consistency (without claiming atomic protection against transient
  swaps), and preserves caller lexical aliases (including legitimate external
  symlinks and ``bin/../libexec`` segments).
- Provides private hash-before-parse JSON loading (:func:`_read_pinned_json`)
  that verifies exact byte size and SHA-256 against an independent
  :class:`FilePin` before invoking the JSON parser, rejects duplicate JSON keys
  and non-standard numeric constants (``NaN``, ``Infinity``, ``-Infinity``), and
  ties the parsed payload to the verified file observation.
- Provides closed OUTER manifest validation (:func:`_validate_outer_manifest_shape`)
  and full file/root/ancestor/symlink observation
  (:func:`_validate_and_observe_outer_profile` and
  :func:`_reobserve_outer_profile_state`) returning deeply immutable private
  state while retaining obtainable partial observations on failure via
  :class:`_ProfileObservationError`.

Scope note:
- Inner source/build/runtime receipt joins, public ``validate_profile`` and
  ``recheck_profile``, and collector wiring are deliberately absent in this
  slice and will be added in the next bounded slice; no collector imports this
  module yet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]
import hashlib
import json
import os
from pathlib import Path
import stat
from types import MappingProxyType
from typing import Any, Mapping


PROFILE_SCHEMA_ID = "protstruct_refmac_diagnostic_profile_v1"
SUPPORTED_PROFILE_ID = "refmac_5_8_0431_instrumented_attempt4_v1"
PROFILE_SUBJECT_ID = "R4"
UPSTREAM_COMMIT = "be25e793829952f4f177d7dfd0c10a1eb6bbd180"
UPSTREAM_TAG = "5.8.0431"

FORBIDDEN_ENV_KEYS: frozenset[str] = frozenset(
    {
        "BASH_ENV",
        "ENV",
        "REFMAC_DIAGNOSTIC_TRACE",
        "SFOUT",
        "FCFOUT",
    }
)
FORBIDDEN_ENV_PREFIXES: tuple[str, str] = ("DYLD_", "LD_")

EXPECTED_TOP_LEVEL_KEYS: frozenset[str] = frozenset(
    {
        "schema_id",
        "profile_id",
        "subject_id",
        "upstream",
        "roots",
        "files",
        "roles",
        "runtime_environment",
    }
)
EXPECTED_UPSTREAM_KEYS: frozenset[str] = frozenset({"commit", "tag"})
EXPECTED_ROOT_NAMES: tuple[str, str, str] = ("vendor", "prepared", "build")
EXPECTED_ROOT_ROW_KEYS: frozenset[str] = frozenset({"path", "file_ids"})
EXPECTED_FILE_ROW_KEYS: frozenset[str] = frozenset(
    {"path", "resolved_path", "sha256", "size_bytes", "symlinks"}
)
EXPECTED_SYMLINK_EDGE_KEYS: frozenset[str] = frozenset({"path", "target"})
EXPECTED_RUNTIME_ENV_OUTER_KEYS: frozenset[str] = frozenset(
    {"observation_file_id", "expected_values", "expected_absent"}
)

EXPECTED_RUNTIME_ENV_KEYS: frozenset[str] = frozenset(
    {
        "CBIN",
        "CCP4",
        "CCP4_MASTER",
        "CCP4_OPEN",
        "CCP4_SCR",
        "CETC",
        "CINCL",
        "CLIB",
        "CLIBD",
        "CLIBD_MON",
        "GFORTRAN_UNBUFFERED_PRECONNECTED",
        "MMCIFDIC",
        "PATH",
        "warpbin",
        "warpdoc",
    }
)
EXPECTED_RUNTIME_ABSENT_KEYS: tuple[str, ...] = (
    "BASH_ENV",
    "ENV",
    "FCFOUT",
    "LD_LIBRARY_PATH",
    "REFMAC_DIAGNOSTIC_TRACE",
    "SFOUT",
)

SINGLE_ROLES: frozenset[str] = frozenset(
    {
        "source_manifest",
        "preparation_receipt",
        "preparer",
        "preparation_interpreter",
        "writer_input",
        "hooks_input",
        "source_auditor",
        "source_audit",
        "source_audit_interpreter",
        "build_receipt",
        "build_launch",
        "build_interpreter",
        "build_qc",
        "build_qc_implementation",
        "linked_executable",
        "diagnostic_executable",
        "runtime_observation",
        "runtime_observer",
        "installed_reference",
        "ccp4_setup",
        "launcher",
        "collection_interpreter",
    }
)
PAIR_ROLES: frozenset[str] = frozenset(
    {"build_driver", "build_journal", "build_runtime_config"}
)
EXPECTED_PAIR_ROLE_BASENAMES: Mapping[str, tuple[str, str]] = MappingProxyType(
    {
        "build_driver": ("build-instrumented-v2.py", "build-driver.py"),
        "build_journal": ("build-journal.py", "build-journal.py"),
        "build_runtime_config": (
            "installed-runtime.cmake",
            "installed-runtime.cmake",
        ),
    }
)
VARIABLE_ROLES: frozenset[str] = frozenset(
    {
        "build_external_inputs",
        "ccp4_setup_dependencies",
        "runtime_images",
        "qc_evidence",
    }
)
EXPECTED_BUILD_INVENTORY_BASENAME_PAIRS: tuple[str, ...] = (
    "toolchain-inventory.json",
    "effective-build-tools.json",
    "assembler-tool.json",
    "post-link-tools.json",
)
EXPECTED_COLLECTOR_HELPER_NAMES: tuple[str, ...] = (
    "audit_1sar_retained_evidence.py",
    "onesar_refmac.py",
    "onesar_refmac_log.py",
    "onesar_rerun.py",
    "t03_reflection_retention.py",
    "toolchain.py",
    "refmac_diagnostic_profile.py",
    "refmac_diagnostic_trace.py",
)
EXPECTED_ALL_ROLES: frozenset[str] = (
    SINGLE_ROLES
    | PAIR_ROLES
    | VARIABLE_ROLES
    | {"build_inventories", "collector_helpers"}
)

STREAM_CHUNK_BYTES: int = 1024 * 1024
_LOWER_HEX_CHARS: frozenset[str] = frozenset("0123456789abcdef")
_MAX_SYMLINK_EXPANSIONS: int = 64


def _deep_freeze_json_value(value: Any) -> Any:
    """Recursively freeze dicts into :class:`MappingProxyType` and lists into ``tuple``."""
    if isinstance(value, Mapping):
        return MappingProxyType(
            {k: _deep_freeze_json_value(v) for k, v in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze_json_value(item) for item in value)
    return value


def _validate_lexical_abs_path(value: Any, *, field_name: str) -> str:
    """Validate that ``value`` is a non-empty absolute path string without normalizing it."""
    if type(value) is not str:
        raise ValueError(f"{field_name} must be a str, got {type(value).__name__}")
    if not value or value.isspace():
        raise ValueError(f"{field_name} must be a non-empty path string")
    if "\x00" in value:
        raise ValueError(f"{field_name} must not contain NUL bytes")
    if not os.path.isabs(value) or not Path(value).is_absolute():
        raise ValueError(f"{field_name} must be an absolute path: {value!r}")
    return value


def _validate_canonical_no_traversal_abs_path(
    value: Any,
    *,
    field_name: str,
    allow_root: bool = False,
) -> str:
    """Validate an absolute path string that must not contain ``.``, ``..``, or trailing slashes.

    When ``allow_root=True``, the canonical POSIX root ``'/'`` is admitted for
    directory/ancestor observations while non-root trailing slashes remain rejected.
    """
    raw = _validate_lexical_abs_path(value, field_name=field_name)
    if raw == "/":
        if allow_root:
            return "/"
        raise ValueError(
            f"{field_name} must not end with '/', '/.', or '/..': {raw!r}"
        )
    if raw.endswith(("/", "/.", "/..")):
        raise ValueError(
            f"{field_name} must not end with '/', '/.', or '/..': {raw!r}"
        )
    if ".." in Path(raw).parts or "/./" in raw or "/../" in raw or "//" in raw:
        raise ValueError(
            f"{field_name} must be a canonical path without '.', '..', or '//': {raw!r}"
        )
    if os.path.normpath(raw) != raw:
        raise ValueError(
            f"{field_name} is not in normalized canonical form: {raw!r}"
        )
    return raw


def _validate_sha256_digest(value: Any, *, field_name: str) -> str:
    """Validate that ``value`` is a 64-character lowercase hexadecimal SHA-256 string."""
    if type(value) is not str:
        raise ValueError(f"{field_name} must be a str, got {type(value).__name__}")
    if len(value) != 64 or not all(ch in _LOWER_HEX_CHARS for ch in value):
        raise ValueError(
            f"{field_name} must be a 64-character lowercase hex SHA-256 digest, got {value!r}"
        )
    return value


def _validate_nonnegative_int(value: Any, *, field_name: str) -> int:
    """Validate that ``value`` is a non-boolean integer ``>= 0``."""
    if type(value) is not int:
        raise ValueError(
            f"{field_name} must be a non-boolean int, got {type(value).__name__}"
        )
    if value < 0:
        raise ValueError(f"{field_name} must be >= 0, got {value}")
    return value


def _validate_opaque_id(value: Any, *, field_name: str) -> str:
    """Validate that ``value`` is a non-empty opaque ID string without NUL bytes."""
    if type(value) is not str or not value or value.isspace() or "\x00" in value:
        raise ValueError(
            f"{field_name} must be a non-empty str without NUL bytes, got {value!r}"
        )
    return value



def _stat_identity_tuple(st: os.stat_result) -> tuple[int, int, int, int, int]:
    """Return the mtime-free ``(dev, ino, mode, uid, gid)`` identity tuple."""
    return (
        int(st.st_dev),
        int(st.st_ino),
        int(stat.S_IMODE(st.st_mode)),
        int(st.st_uid),
        int(st.st_gid),
    )


def _paths_overlap(path_a: str | Path, path_b: str | Path) -> bool:
    """Return True if ``path_a`` and ``path_b`` are equal or one is inside the other."""
    pa = Path(path_a)
    pb = Path(path_b)
    return pa == pb or pa.is_relative_to(pb) or pb.is_relative_to(pa)


@dataclass(frozen=True)
class FilePin:
    """Immutable caller-held pin for a regular file's lexical path, SHA-256, and byte size."""

    path: str
    sha256: str
    size_bytes: int

    def __post_init__(self) -> None:
        _validate_lexical_abs_path(self.path, field_name="FilePin.path")
        _validate_sha256_digest(self.sha256, field_name="FilePin.sha256")
        _validate_nonnegative_int(self.size_bytes, field_name="FilePin.size_bytes")

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True)
class RefmacDiagnosticProfile:
    """Immutable caller-held binding of the diagnostic profile ID and independent pins."""

    profile_id: str
    manifest: FilePin
    executable: FilePin

    def __post_init__(self) -> None:
        if type(self.profile_id) is not str or not self.profile_id:
            raise ValueError(
                f"RefmacDiagnosticProfile.profile_id must be a non-empty str, got {self.profile_id!r}"
            )
        if self.profile_id != SUPPORTED_PROFILE_ID:
            raise ValueError(
                f"Unsupported RefmacDiagnosticProfile.profile_id {self.profile_id!r}; "
                f"only {SUPPORTED_PROFILE_ID!r} is supported"
            )
        if type(self.manifest) is not FilePin:
            raise ValueError(
                "RefmacDiagnosticProfile.manifest must be a FilePin instance, "
                f"got {type(self.manifest).__name__}"
            )
        if type(self.executable) is not FilePin:
            raise ValueError(
                "RefmacDiagnosticProfile.executable must be a FilePin instance, "
                f"got {type(self.executable).__name__}"
            )
        if self.manifest.path == self.executable.path:
            raise ValueError(
                "RefmacDiagnosticProfile.manifest and executable pins must be distinct paths"
            )


def reject_conflicting_environment(mapping: Mapping[str, Any]) -> None:
    """Reject forbidden inherited or sourced environment variables without mutating ``mapping``.

    Rejects the presence of ``BASH_ENV``, ``ENV``, ``REFMAC_DIAGNOSTIC_TRACE``,
    ``SFOUT``, ``FCFOUT``, and any ``DYLD_*`` or ``LD_*`` variable name even when
    mapped to an empty string.
    """
    if not isinstance(mapping, Mapping):
        raise ValueError(
            f"environment must be a Mapping, got {type(mapping).__name__}"
        )

    conflicting: list[str] = []
    for key, value in mapping.items():
        if type(key) is not str or not key:
            raise ValueError(
                f"environment keys must be non-empty str, got {key!r} ({type(key).__name__})"
            )
        if type(value) is not str:
            raise ValueError(
                f"environment value for {key!r} must be a str, got {type(value).__name__}"
            )
        if key in FORBIDDEN_ENV_KEYS or key.startswith(FORBIDDEN_ENV_PREFIXES):
            conflicting.append(key)

    if conflicting:
        joined = ", ".join(sorted(set(conflicting)))
        raise ValueError(
            f"Conflicting environment variable(s) present: {joined}"
        )


@dataclass(frozen=True)
class _SymlinkEdge:
    """One literal symlink edge encountered along a lexical path or its symlink targets."""

    path: str
    target: str

    def __post_init__(self) -> None:
        _validate_lexical_abs_path(self.path, field_name="_SymlinkEdge.path")
        if type(self.target) is not str or not self.target or "\x00" in self.target:
            raise ValueError(
                f"_SymlinkEdge.target must be a non-empty str without NUL bytes, got {self.target!r}"
            )

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "target": self.target}


@dataclass(frozen=True)
class _ObservedDirectoryIdentity:
    """Immutable mtime-free ``(dev, ino, mode, uid, gid)`` observation of a directory."""

    path: str
    resolved_path: str
    dev: int
    ino: int
    mode: int
    uid: int
    gid: int

    def __post_init__(self) -> None:
        _validate_lexical_abs_path(
            self.path, field_name="_ObservedDirectoryIdentity.path"
        )
        _validate_canonical_no_traversal_abs_path(
            self.resolved_path,
            field_name="_ObservedDirectoryIdentity.resolved_path",
            allow_root=True,
        )
        for attr_name in ("dev", "ino", "mode", "uid", "gid"):
            val = getattr(self, attr_name)
            if type(val) is not int:
                raise ValueError(
                    f"_ObservedDirectoryIdentity.{attr_name} must be a non-boolean int"
                )

    @property
    def identity_tuple(self) -> tuple[int, int, int, int, int]:
        return (self.dev, self.ino, self.mode, self.uid, self.gid)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "resolved_path": self.resolved_path,
            "dev": self.dev,
            "ino": self.ino,
            "mode": self.mode,
            "uid": self.uid,
            "gid": self.gid,
        }


@dataclass(frozen=True)
class _ObservedSymlinkIdentity:
    """Immutable mtime-free ``(dev, ino, mode, uid, gid)`` observation of a literal symlink."""

    path: str
    target: str
    dev: int
    ino: int
    mode: int
    uid: int
    gid: int

    def __post_init__(self) -> None:
        _validate_lexical_abs_path(
            self.path, field_name="_ObservedSymlinkIdentity.path"
        )
        if type(self.target) is not str or not self.target or "\x00" in self.target:
            raise ValueError(
                "_ObservedSymlinkIdentity.target must be a non-empty str without NUL bytes"
            )
        for attr_name in ("dev", "ino", "mode", "uid", "gid"):
            val = getattr(self, attr_name)
            if type(val) is not int:
                raise ValueError(
                    f"_ObservedSymlinkIdentity.{attr_name} must be a non-boolean int"
                )

    @property
    def identity_tuple(self) -> tuple[int, int, int, int, int]:
        return (self.dev, self.ino, self.mode, self.uid, self.gid)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "target": self.target,
            "dev": self.dev,
            "ino": self.ino,
            "mode": self.mode,
            "uid": self.uid,
            "gid": self.gid,
        }


@dataclass(frozen=True)
class _ObservedRegularFilePin:
    """Immutable observation of a regular file on disk, preserving its lexical alias."""

    path: str
    resolved_path: str
    sha256: str
    size_bytes: int
    symlinks: tuple[_SymlinkEdge, ...]
    dev: int
    ino: int
    mode: int
    uid: int
    gid: int

    def __post_init__(self) -> None:
        _validate_lexical_abs_path(self.path, field_name="_ObservedRegularFilePin.path")
        _validate_lexical_abs_path(
            self.resolved_path, field_name="_ObservedRegularFilePin.resolved_path"
        )
        if ".." in Path(self.resolved_path).parts:
            raise ValueError(
                f"_ObservedRegularFilePin.resolved_path must not contain '..': {self.resolved_path!r}"
            )
        _validate_sha256_digest(
            self.sha256, field_name="_ObservedRegularFilePin.sha256"
        )
        _validate_nonnegative_int(
            self.size_bytes, field_name="_ObservedRegularFilePin.size_bytes"
        )
        if type(self.symlinks) is not tuple or not all(
            type(edge) is _SymlinkEdge for edge in self.symlinks
        ):
            raise ValueError(
                "_ObservedRegularFilePin.symlinks must be a tuple of _SymlinkEdge"
            )
        edge_paths = [edge.path for edge in self.symlinks]
        if edge_paths != sorted(set(edge_paths)):
            raise ValueError(
                "_ObservedRegularFilePin.symlinks must be strictly sorted by unique edge.path"
            )
        for attr_name in ("dev", "ino", "mode", "uid", "gid"):
            val = getattr(self, attr_name)
            if type(val) is not int:
                raise ValueError(
                    f"_ObservedRegularFilePin.{attr_name} must be a non-boolean int"
                )

    @property
    def identity_tuple(self) -> tuple[int, int, int, int, int]:
        """Return the mtime-free ``(dev, ino, mode, uid, gid)`` identity tuple."""
        return (self.dev, self.ino, self.mode, self.uid, self.gid)

    def as_file_pin(self) -> FilePin:
        """Return a :class:`FilePin` preserving the caller's lexical ``path``."""
        return FilePin(
            path=self.path,
            sha256=self.sha256,
            size_bytes=self.size_bytes,
        )

    def to_manifest_row(self) -> dict[str, Any]:
        """Return the closed manifest file-row dictionary representation."""
        return {
            "path": self.path,
            "resolved_path": self.resolved_path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "symlinks": [edge.to_dict() for edge in self.symlinks],
        }


class _ObservedFilePinError(ValueError):
    """ValueError subclass carrying an already-obtained :class:`_ObservedRegularFilePin`."""

    def __init__(
        self,
        message: str,
        *,
        observation: _ObservedRegularFilePin,
    ) -> None:
        super().__init__(message)
        self.observation = observation


def _validate_kernel_regular_lookup(
    raw_lexical: str,
) -> tuple[os.stat_result, os.stat_result]:
    """Validate ``raw_lexical`` using un-normalized kernel lookup semantics."""
    if raw_lexical.endswith(("/", "/.", "/..")):
        raise ValueError(
            f"Regular-file path must not end with a directory suffix ('/', '/.', or '/..'): {raw_lexical!r}"
        )
    try:
        lex_lstat = os.lstat(raw_lexical)
        lex_stat = os.stat(raw_lexical)
    except OSError as exc:
        raise ValueError(
            f"Kernel path lookup failed for {raw_lexical!r} ({type(exc).__name__}): {exc}"
        ) from exc
    if not stat.S_ISREG(lex_stat.st_mode):
        raise ValueError(
            f"Target is not a regular file: {raw_lexical!r}"
        )
    return lex_lstat, lex_stat


@dataclass(frozen=True)
class _PathTraversalResult:
    """Bounded left-to-right component-by-component resolution result for a regular-file path."""

    lexical_path: str
    resolved_path: str
    symlink_edges: tuple[_SymlinkEdge, ...]
    directory_paths: tuple[str, ...]
    target_lstat: os.stat_result


def _traverse_path_components(raw_lexical: str) -> _PathTraversalResult:
    """Resolve ``raw_lexical`` left-to-right component by component within ``_MAX_SYMLINK_EXPANSIONS``.

    Counts actual symlink traversals (capped at ``_MAX_SYMLINK_EXPANSIONS``), retains literal
    symlink targets and all traversed directory dependencies (including directories entered
    before ``..`` removes them), and rejects directory suffixes on regular files or leaf
    symlink targets as well as non-directory intermediate components (e.g. ``regular_file/..``).
    """
    raw_lexical = _validate_lexical_abs_path(raw_lexical, field_name="path")
    _lex_lstat, lex_stat = _validate_kernel_regular_lookup(raw_lexical)

    current_parts: list[str] = []
    remaining: list[str] = [
        comp for comp in reversed(raw_lexical.split("/")) if comp
    ]
    if not remaining:
        raise ValueError(
            f"Expected regular file at {raw_lexical!r}, got root directory"
        )

    dir_paths_seen: dict[str, None] = {"/": None}
    edges: dict[str, str] = {}
    symlink_traversals = 0
    resolved_path: str | None = None
    target_lstat: os.stat_result | None = None

    while remaining:
        comp = remaining.pop()
        is_last_component = len(remaining) == 0

        if comp == ".":
            if is_last_component:
                raise ValueError(
                    f"Regular-file path or symlink target must not end with '.': {raw_lexical!r}"
                )
            cur_dir = "/" + "/".join(current_parts) if current_parts else "/"
            dir_paths_seen[cur_dir] = None
            continue

        if comp == "..":
            if is_last_component:
                raise ValueError(
                    f"Regular-file path or symlink target must not end with '..': {raw_lexical!r}"
                )
            cur_dir = "/" + "/".join(current_parts) if current_parts else "/"
            dir_paths_seen[cur_dir] = None
            if current_parts:
                current_parts.pop()
            parent_dir = "/" + "/".join(current_parts) if current_parts else "/"
            dir_paths_seen[parent_dir] = None
            continue

        cand_path = "/" + "/".join([*current_parts, comp])
        try:
            st = os.lstat(cand_path)
        except OSError as exc:
            raise ValueError(
                f"Cannot inspect path component {cand_path!r} ({type(exc).__name__}): {exc}"
            ) from exc

        if stat.S_ISLNK(st.st_mode):
            symlink_traversals += 1
            if symlink_traversals > _MAX_SYMLINK_EXPANSIONS:
                raise ValueError(
                    f"Symlink expansion limit ({_MAX_SYMLINK_EXPANSIONS}) exceeded at {cand_path!r}"
                )
            try:
                target = os.readlink(cand_path)
            except OSError as exc:
                raise ValueError(
                    f"Cannot read symlink target at {cand_path!r} ({type(exc).__name__}): {exc}"
                ) from exc
            if not target or "\x00" in target:
                raise ValueError(
                    f"Invalid symlink target at {cand_path!r}: {target!r}"
                )
            if is_last_component and target.endswith(("/", "/.", "/..")):
                raise ValueError(
                    f"Regular-file target path must not end with a directory suffix: {target!r}"
                )
            prev_target = edges.get(cand_path)
            if prev_target is not None and prev_target != target:
                raise ValueError(
                    f"Symlink target changed during traversal at {cand_path!r}: "
                    f"before={prev_target!r}, after={target!r}"
                )
            edges[cand_path] = target
            if target.startswith("/"):
                current_parts = []
                dir_paths_seen["/"] = None
            target_comps = [c for c in reversed(target.split("/")) if c]
            if not target_comps and is_last_component:
                raise ValueError(
                    f"Symlink target at {cand_path!r} resolves to root directory, not a regular file"
                )
            remaining.extend(target_comps)
        elif stat.S_ISDIR(st.st_mode):
            if is_last_component:
                raise ValueError(
                    f"Target is not a regular file: {raw_lexical!r} (resolved to directory {cand_path!r})"
                )
            current_parts.append(comp)
            dir_paths_seen[cand_path] = None
        elif stat.S_ISREG(st.st_mode):
            if not is_last_component:
                raise ValueError(
                    f"Non-leaf component {cand_path!r} is a regular file, not a directory"
                )
            resolved_path = cand_path
            target_lstat = st
        else:
            raise ValueError(
                f"Path component {cand_path!r} is neither a regular file, directory, nor symlink"
            )

    if resolved_path is None or target_lstat is None:
        raise ValueError(
            f"Path {raw_lexical!r} did not resolve to a regular file"
        )
    if _stat_identity_tuple(lex_stat) != _stat_identity_tuple(target_lstat):
        raise ValueError(
            f"Target identity changed during component traversal for {raw_lexical!r}"
        )
    if int(lex_stat.st_size) != int(target_lstat.st_size):
        raise ValueError(
            f"Target size changed during component traversal for {raw_lexical!r}"
        )

    symlink_edges = tuple(
        _SymlinkEdge(path=edge_path, target=edges[edge_path])
        for edge_path in sorted(edges)
    )
    return _PathTraversalResult(
        lexical_path=raw_lexical,
        resolved_path=resolved_path,
        symlink_edges=symlink_edges,
        directory_paths=tuple(dir_paths_seen.keys()),
        target_lstat=target_lstat,
    )


def _discover_symlink_edges(raw_lexical: str) -> tuple[_SymlinkEdge, ...]:
    """Collect literal symlink edges along ``raw_lexical`` via bounded component traversal."""
    return _traverse_path_components(raw_lexical).symlink_edges


def _resolve_regular_target_strict(raw_lexical: str) -> tuple[str, os.stat_result]:
    """Resolve ``raw_lexical`` strictly and verify the resolved path is a regular non-symlink file."""
    lexical_path_obj = Path(raw_lexical)
    try:
        resolved_path_obj = lexical_path_obj.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError(
            f"Failed to resolve path {raw_lexical!r} ({type(exc).__name__}): {exc}"
        ) from exc

    resolved_str = str(resolved_path_obj)
    if ".." in resolved_path_obj.parts:
        raise ValueError(
            f"Resolved path must not contain '..': {resolved_str!r}"
        )
    for anc in (resolved_path_obj, *resolved_path_obj.parents):
        try:
            anc_st = os.lstat(str(anc))
        except OSError as exc:
            raise ValueError(
                f"Failed to lstat resolved component {anc} ({type(exc).__name__}): {exc}"
            ) from exc
        if stat.S_ISLNK(anc_st.st_mode):
            raise ValueError(
                f"Resolved path still contains a symlink component at {anc}"
            )
        if anc != resolved_path_obj and not stat.S_ISDIR(anc_st.st_mode):
            raise ValueError(
                f"Resolved ancestor is not a directory at {anc}"
            )

    try:
        target_lstat = os.lstat(resolved_str)
    except OSError as exc:
        raise ValueError(
            f"Failed to lstat resolved target {resolved_str!r} ({type(exc).__name__}): {exc}"
        ) from exc

    if stat.S_ISLNK(target_lstat.st_mode) or not stat.S_ISREG(target_lstat.st_mode):
        raise ValueError(
            f"Target is not a regular file: {raw_lexical!r} (resolved to {resolved_str!r})"
        )
    return resolved_str, target_lstat


def _clear_nonblock_flag(fd: int) -> None:
    """Clear ``O_NONBLOCK`` on a verified regular-file descriptor before buffered reading."""
    if fcntl is None or not hasattr(os, "O_NONBLOCK"):
        return
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    if flags & os.O_NONBLOCK:
        fcntl.fcntl(fd, fcntl.F_SETFL, flags & ~os.O_NONBLOCK)


def _stream_observe_regular_file(
    raw_lexical: str,
    *,
    expected_pin: FilePin | None = None,
    chunk_size: int = STREAM_CHUNK_BYTES,
    retain_bytes: bool = False,
) -> tuple[_ObservedRegularFilePin, bytes | None]:
    """Shared implementation for streaming regular-file observation and pinned byte loading."""
    lex_lstat_before, lex_stat_before = _validate_kernel_regular_lookup(raw_lexical)
    symlinks_before = _discover_symlink_edges(raw_lexical)
    resolved_before, target_lstat_before = _resolve_regular_target_strict(raw_lexical)

    if _stat_identity_tuple(lex_stat_before) != _stat_identity_tuple(target_lstat_before):
        raise ValueError(
            f"Target identity changed during pre-open resolution for {raw_lexical!r}"
        )
    if int(lex_stat_before.st_size) != int(target_lstat_before.st_size):
        raise ValueError(
            f"Target size changed during pre-open resolution for {raw_lexical!r}"
        )

    open_flags = (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    fd = -1
    fd_owned_by_fileobj = False
    hasher = hashlib.sha256()
    chunks: list[bytes] = []
    total_bytes = 0
    max_allowed_bytes = (
        expected_pin.size_bytes if expected_pin is not None else None
    )

    try:
        fd = os.open(resolved_before, open_flags)
        fstat_before = os.fstat(fd)
        if not stat.S_ISREG(fstat_before.st_mode):
            raise ValueError(
                f"Opened descriptor is not a regular file: {resolved_before!r}"
            )
        if _stat_identity_tuple(fstat_before) != _stat_identity_tuple(
            target_lstat_before
        ):
            raise ValueError(
                f"File identity changed between lstat and open at {resolved_before!r}"
            )
        if max_allowed_bytes is not None and int(fstat_before.st_size) != max_allowed_bytes:
            label = "Pinned JSON size mismatch" if retain_bytes else "Size mismatch"
            suffix = " before parse" if retain_bytes else ""
            raise ValueError(
                f"{label} for {raw_lexical!r}{suffix}: "
                f"expected {max_allowed_bytes} bytes, observed {int(fstat_before.st_size)} bytes"
            )
        _clear_nonblock_flag(fd)
        handle = os.fdopen(fd, "rb")
        fd_owned_by_fileobj = True
        with handle:
            while True:
                read_len = (
                    min(chunk_size, max(1, max_allowed_bytes - total_bytes + 1))
                    if max_allowed_bytes is not None
                    else chunk_size
                )
                chunk = handle.read(read_len)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if max_allowed_bytes is not None and total_bytes > max_allowed_bytes:
                    label = "Pinned JSON size mismatch" if retain_bytes else "Size mismatch"
                    suffix = " before parse" if retain_bytes else ""
                    raise ValueError(
                        f"{label} for {raw_lexical!r}{suffix}: "
                        f"streamed bytes exceeded expected {max_allowed_bytes} bytes"
                    )
                hasher.update(chunk)
                if retain_bytes:
                    chunks.append(chunk)
            fstat_after = os.fstat(handle.fileno())
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(
            f"Failed reading regular file {raw_lexical!r} ({type(exc).__name__}): {exc}"
        ) from exc
    finally:
        if fd >= 0 and not fd_owned_by_fileobj:
            try:
                os.close(fd)
            except OSError:
                pass

    if _stat_identity_tuple(fstat_after) != _stat_identity_tuple(fstat_before):
        raise ValueError(
            f"File identity changed during read at {resolved_before!r}"
        )
    if total_bytes != int(fstat_before.st_size) or total_bytes != int(
        fstat_after.st_size
    ):
        raise ValueError(
            f"File size changed during streaming read at {resolved_before!r}: "
            f"stat_before={int(fstat_before.st_size)}, streamed={total_bytes}, "
            f"stat_after={int(fstat_after.st_size)}"
        )

    lex_lstat_after, lex_stat_after = _validate_kernel_regular_lookup(raw_lexical)
    symlinks_after = _discover_symlink_edges(raw_lexical)
    resolved_after, target_lstat_after = _resolve_regular_target_strict(raw_lexical)

    if _stat_identity_tuple(lex_lstat_after) != _stat_identity_tuple(lex_lstat_before):
        raise ValueError(
            f"Lexical path identity changed during read for {raw_lexical!r}"
        )
    if symlinks_after != symlinks_before:
        raise ValueError(
            f"Symlink edges changed during read for {raw_lexical!r}"
        )
    if resolved_after != resolved_before:
        raise ValueError(
            f"Resolved target path changed during read for {raw_lexical!r}: "
            f"before={resolved_before!r}, after={resolved_after!r}"
        )
    if _stat_identity_tuple(target_lstat_after) != _stat_identity_tuple(fstat_after):
        raise ValueError(
            f"Resolved target identity changed after read for {raw_lexical!r}"
        )
    if int(target_lstat_after.st_size) != total_bytes:
        raise ValueError(
            f"Resolved target size changed after read for {raw_lexical!r}"
        )
    if _stat_identity_tuple(lex_stat_after) != _stat_identity_tuple(fstat_after):
        raise ValueError(
            f"Lexical target identity changed after read for {raw_lexical!r}"
        )
    if int(lex_stat_after.st_size) != total_bytes:
        raise ValueError(
            f"Lexical target size changed after read for {raw_lexical!r}"
        )

    digest = hasher.hexdigest()
    observation = _ObservedRegularFilePin(
        path=raw_lexical,
        resolved_path=resolved_after,
        sha256=digest,
        size_bytes=total_bytes,
        symlinks=symlinks_after,
        dev=int(fstat_after.st_dev),
        ino=int(fstat_after.st_ino),
        mode=int(stat.S_IMODE(fstat_after.st_mode)),
        uid=int(fstat_after.st_uid),
        gid=int(fstat_after.st_gid),
    )
    if expected_pin is not None:
        if total_bytes != expected_pin.size_bytes:
            label = "Pinned JSON size mismatch" if retain_bytes else "Size mismatch"
            suffix = " before parse" if retain_bytes else ""
            raise _ObservedFilePinError(
                f"{label} for {raw_lexical!r}{suffix}: expected {expected_pin.size_bytes} bytes, "
                f"observed {total_bytes} bytes",
                observation=observation,
            )
        if digest != expected_pin.sha256:
            label = "Pinned JSON SHA-256 mismatch" if retain_bytes else "SHA-256 mismatch"
            suffix = " before parse" if retain_bytes else ""
            raise _ObservedFilePinError(
                f"{label} for {raw_lexical!r}{suffix}: expected {expected_pin.sha256}, "
                f"observed {digest}",
                observation=observation,
            )

    raw_bytes = b"".join(chunks) if retain_bytes else None
    return observation, raw_bytes


def _observe_regular_file_pin(
    path: str | os.PathLike[str],
    *,
    expected_pin: FilePin | None = None,
    chunk_size: int = STREAM_CHUNK_BYTES,
) -> _ObservedRegularFilePin:
    """Stream-hash and observe a regular file while preserving its lexical alias."""
    if isinstance(path, bool) or not isinstance(path, (str, os.PathLike)):
        raise ValueError(
            f"path must be a str or os.PathLike, got {type(path).__name__}"
        )
    raw_lexical = path if type(path) is str else os.fspath(path)
    _validate_lexical_abs_path(raw_lexical, field_name="path")

    if expected_pin is not None:
        if type(expected_pin) is not FilePin:
            raise ValueError(
                f"expected_pin must be a FilePin, got {type(expected_pin).__name__}"
            )
        if raw_lexical != expected_pin.path:
            raise ValueError(
                f"Lexical path {raw_lexical!r} does not match expected_pin.path {expected_pin.path!r}"
            )

    if type(chunk_size) is not int or chunk_size <= 0:
        raise ValueError(
            f"chunk_size must be a positive int, got {chunk_size!r}"
        )

    observation, _ = _stream_observe_regular_file(
        raw_lexical,
        expected_pin=expected_pin,
        chunk_size=chunk_size,
        retain_bytes=False,
    )
    return observation


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """JSON ``object_pairs_hook`` that rejects duplicate keys in any object."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON object key rejected: {key!r}")
        result[key] = value
    return result


def _reject_nonstandard_json_constant(token: str) -> Any:
    """JSON ``parse_constant`` hook that rejects ``NaN``, ``Infinity``, and ``-Infinity``."""
    raise ValueError(f"Non-standard JSON numeric constant rejected: {token!r}")


@dataclass(frozen=True)
class _PinnedJsonDocument:
    """Immutable result tying a parsed JSON value to the verified file observation and pin."""

    pin: FilePin
    observation: _ObservedRegularFilePin
    payload: Any

    def __post_init__(self) -> None:
        if type(self.pin) is not FilePin:
            raise ValueError("_PinnedJsonDocument.pin must be a FilePin")
        if type(self.observation) is not _ObservedRegularFilePin:
            raise ValueError(
                "_PinnedJsonDocument.observation must be an _ObservedRegularFilePin"
            )
        if (
            self.observation.path != self.pin.path
            or self.observation.sha256 != self.pin.sha256
            or self.observation.size_bytes != self.pin.size_bytes
        ):
            raise ValueError(
                "_PinnedJsonDocument observation does not match its FilePin"
            )
        object.__setattr__(self, "payload", _deep_freeze_json_value(self.payload))


def _parse_verified_json_bytes(
    raw_bytes: bytes,
    *,
    expected_pin: FilePin,
) -> Any:
    """Verify ``raw_bytes`` size and SHA-256 against ``expected_pin`` BEFORE JSON parsing."""
    if type(expected_pin) is not FilePin:
        raise ValueError(
            f"expected_pin must be a FilePin, got {type(expected_pin).__name__}"
        )
    if type(raw_bytes) is not bytes:
        raise ValueError(
            f"raw_bytes must be bytes, got {type(raw_bytes).__name__}"
        )

    actual_size = len(raw_bytes)
    actual_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    if actual_size != expected_pin.size_bytes:
        raise ValueError(
            f"Pinned JSON size mismatch for {expected_pin.path!r} before parse: "
            f"expected {expected_pin.size_bytes} bytes, observed {actual_size} bytes"
        )
    if actual_sha256 != expected_pin.sha256:
        raise ValueError(
            f"Pinned JSON SHA-256 mismatch for {expected_pin.path!r} before parse: "
            f"expected {expected_pin.sha256}, observed {actual_sha256}"
        )

    try:
        text = raw_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"Pinned JSON file {expected_pin.path!r} is not valid UTF-8: {exc}"
        ) from exc

    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_nonstandard_json_constant,
        )
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid JSON syntax in {expected_pin.path!r}: {exc}"
        ) from exc


def _read_pinned_json(
    pin: FilePin,
    *,
    chunk_size: int = STREAM_CHUNK_BYTES,
) -> _PinnedJsonDocument:
    """Stream-read a regular file, verify ``pin`` size and SHA-256 before parsing, and parse strict JSON."""
    if type(pin) is not FilePin:
        raise ValueError(f"pin must be a FilePin, got {type(pin).__name__}")
    if type(chunk_size) is not int or chunk_size <= 0:
        raise ValueError(
            f"chunk_size must be a positive int, got {chunk_size!r}"
        )

    observation, raw_bytes = _stream_observe_regular_file(
        pin.path,
        expected_pin=pin,
        chunk_size=chunk_size,
        retain_bytes=True,
    )
    assert raw_bytes is not None
    try:
        payload = _parse_verified_json_bytes(raw_bytes, expected_pin=pin)
    except ValueError as exc:
        raise _ObservedFilePinError(str(exc), observation=observation) from exc
    return _PinnedJsonDocument(
        pin=pin,
        observation=observation,
        payload=payload,
    )



@dataclass(frozen=True)
class _CheckedRuntimeEnvironmentOuter:
    """Immutable validated outer ``runtime_environment`` block from a profile manifest."""

    observation_file_id: str
    expected_values: Mapping[str, str]
    expected_absent: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_opaque_id(
            self.observation_file_id,
            field_name="_CheckedRuntimeEnvironmentOuter.observation_file_id",
        )
        if not isinstance(self.expected_values, Mapping):
            raise ValueError(
                "_CheckedRuntimeEnvironmentOuter.expected_values must be a Mapping"
            )
        if set(self.expected_values.keys()) != EXPECTED_RUNTIME_ENV_KEYS:
            raise ValueError(
                "_CheckedRuntimeEnvironmentOuter.expected_values must match the 15 fixed keys"
            )
        frozen_vals: dict[str, str] = {}
        for k, v in sorted(self.expected_values.items()):
            if type(k) is not str or type(v) is not str:
                raise ValueError(
                    "_CheckedRuntimeEnvironmentOuter.expected_values keys and values must be str"
                )
            frozen_vals[k] = v
        object.__setattr__(self, "expected_values", MappingProxyType(frozen_vals))
        if (
            type(self.expected_absent) is not tuple
            or self.expected_absent != EXPECTED_RUNTIME_ABSENT_KEYS
        ):
            raise ValueError(
                "_CheckedRuntimeEnvironmentOuter.expected_absent must equal EXPECTED_RUNTIME_ABSENT_KEYS"
            )


@dataclass(frozen=True)
class _CheckedOuterManifest:
    """Deeply immutable validated outer profile manifest structure."""

    schema_id: str
    profile_id: str
    subject_id: str
    upstream_commit: str
    upstream_tag: str
    roots: Mapping[str, Mapping[str, Any]]
    files: Mapping[str, Mapping[str, Any]]
    roles: Mapping[str, tuple[str, ...]]
    runtime_environment: _CheckedRuntimeEnvironmentOuter
    tree_member_ids: frozenset[str]
    role_used_ids: frozenset[str]

    def __post_init__(self) -> None:
        if self.schema_id != PROFILE_SCHEMA_ID:
            raise ValueError(f"Unsupported schema_id: {self.schema_id!r}")
        if self.profile_id != SUPPORTED_PROFILE_ID:
            raise ValueError(f"Unsupported profile_id: {self.profile_id!r}")
        if self.subject_id != PROFILE_SUBJECT_ID:
            raise ValueError(f"Unsupported subject_id: {self.subject_id!r}")
        if self.upstream_commit != UPSTREAM_COMMIT:
            raise ValueError(f"Unsupported upstream_commit: {self.upstream_commit!r}")
        if self.upstream_tag != UPSTREAM_TAG:
            raise ValueError(f"Unsupported upstream_tag: {self.upstream_tag!r}")
        if type(self.runtime_environment) is not _CheckedRuntimeEnvironmentOuter:
            raise ValueError(
                "_CheckedOuterManifest.runtime_environment must be _CheckedRuntimeEnvironmentOuter"
            )
        object.__setattr__(self, "roots", _deep_freeze_json_value(self.roots))
        object.__setattr__(self, "files", _deep_freeze_json_value(self.files))
        object.__setattr__(self, "roles", _deep_freeze_json_value(self.roles))
        object.__setattr__(
            self, "tree_member_ids", frozenset(self.tree_member_ids)
        )
        object.__setattr__(
            self, "role_used_ids", frozenset(self.role_used_ids)
        )


def _validate_outer_manifest_shape(
    payload: Any,
    *,
    expected_profile_id: str = SUPPORTED_PROFILE_ID,
    expected_executable_pin: FilePin | None = None,
) -> _CheckedOuterManifest:
    """Validate the closed outer manifest JSON schema, roots, files, 31 roles, and runtime_environment."""
    if not isinstance(payload, Mapping) or isinstance(payload, (list, tuple)):
        raise ValueError(
            f"Profile manifest must be a JSON object, got {type(payload).__name__}"
        )

    actual_top_keys = set(payload.keys())
    if actual_top_keys != EXPECTED_TOP_LEVEL_KEYS:
        missing = sorted(EXPECTED_TOP_LEVEL_KEYS - actual_top_keys)
        extra = sorted(actual_top_keys - EXPECTED_TOP_LEVEL_KEYS)
        raise ValueError(
            f"Profile manifest top-level keys mismatch: missing={missing}, extra={extra}"
        )

    schema_id = payload["schema_id"]
    if type(schema_id) is not str or schema_id != PROFILE_SCHEMA_ID:
        raise ValueError(
            f"Profile manifest schema_id must be {PROFILE_SCHEMA_ID!r}, got {schema_id!r}"
        )

    profile_id = payload["profile_id"]
    if (
        type(profile_id) is not str
        or profile_id != SUPPORTED_PROFILE_ID
        or profile_id != expected_profile_id
    ):
        raise ValueError(
            f"Profile manifest profile_id must be {expected_profile_id!r}, got {profile_id!r}"
        )

    subject_id = payload["subject_id"]
    if type(subject_id) is not str or subject_id != PROFILE_SUBJECT_ID:
        raise ValueError(
            f"Profile manifest subject_id must be {PROFILE_SUBJECT_ID!r}, got {subject_id!r}"
        )

    upstream = payload["upstream"]
    if not isinstance(upstream, Mapping) or set(upstream.keys()) != EXPECTED_UPSTREAM_KEYS:
        raise ValueError(
            "Profile manifest upstream must be an object with exact keys {'commit', 'tag'}"
        )
    commit = upstream["commit"]
    tag = upstream["tag"]
    if type(commit) is not str or commit != UPSTREAM_COMMIT:
        raise ValueError(
            f"Profile manifest upstream.commit must be {UPSTREAM_COMMIT!r}, got {commit!r}"
        )
    if type(tag) is not str or tag != UPSTREAM_TAG:
        raise ValueError(
            f"Profile manifest upstream.tag must be {UPSTREAM_TAG!r}, got {tag!r}"
        )

    raw_files = payload["files"]
    if not isinstance(raw_files, Mapping) or len(raw_files) == 0:
        raise ValueError("Profile manifest files must be a non-empty object")

    checked_files: dict[str, Mapping[str, Any]] = {}
    seen_lexical_paths: set[str] = set()
    resolved_target_pins: dict[str, tuple[str, int]] = {}

    for raw_id, raw_row in raw_files.items():
        file_id = _validate_opaque_id(raw_id, field_name="files key")
        if not isinstance(raw_row, Mapping) or set(raw_row.keys()) != EXPECTED_FILE_ROW_KEYS:
            raise ValueError(
                f"File row {file_id!r} must have exact keys {sorted(EXPECTED_FILE_ROW_KEYS)}"
            )
        row_path = _validate_lexical_abs_path(
            raw_row["path"], field_name=f"files[{file_id!r}].path"
        )
        if row_path.endswith(("/", "/.", "/..")):
            raise ValueError(
                f"files[{file_id!r}].path must not end with '/', '/.', or '/..': {row_path!r}"
            )
        if row_path in seen_lexical_paths:
            raise ValueError(
                f"Duplicate lexical file path in manifest files: {row_path!r}"
            )
        seen_lexical_paths.add(row_path)

        row_resolved = _validate_canonical_no_traversal_abs_path(
            raw_row["resolved_path"],
            field_name=f"files[{file_id!r}].resolved_path",
        )
        row_sha256 = _validate_sha256_digest(
            raw_row["sha256"], field_name=f"files[{file_id!r}].sha256"
        )
        row_size = _validate_nonnegative_int(
            raw_row["size_bytes"], field_name=f"files[{file_id!r}].size_bytes"
        )

        target_pin = (row_sha256, row_size)
        prev_target_pin = resolved_target_pins.get(row_resolved)
        if prev_target_pin is not None and prev_target_pin != target_pin:
            raise ValueError(
                f"Conflicting sha256/size_bytes pins for resolved target {row_resolved!r}: "
                f"{prev_target_pin} vs {target_pin}"
            )
        resolved_target_pins[row_resolved] = target_pin

        raw_symlinks = raw_row["symlinks"]
        if not isinstance(raw_symlinks, (list, tuple)):
            raise ValueError(
                f"files[{file_id!r}].symlinks must be a list, got {type(raw_symlinks).__name__}"
            )
        parsed_edges: list[_SymlinkEdge] = []
        edge_paths: list[str] = []
        for idx, raw_edge in enumerate(raw_symlinks):
            if (
                not isinstance(raw_edge, Mapping)
                or set(raw_edge.keys()) != EXPECTED_SYMLINK_EDGE_KEYS
            ):
                raise ValueError(
                    f"files[{file_id!r}].symlinks[{idx}] must have exact keys {{'path', 'target'}}"
                )
            edge_path = _validate_lexical_abs_path(
                raw_edge["path"],
                field_name=f"files[{file_id!r}].symlinks[{idx}].path",
            )
            if edge_path.endswith(("/", "/.", "/..")):
                raise ValueError(
                    f"files[{file_id!r}].symlinks[{idx}].path must not end with directory suffix: {edge_path!r}"
                )
            edge_target = raw_edge["target"]
            if (
                type(edge_target) is not str
                or not edge_target
                or edge_target.isspace()
                or "\x00" in edge_target
            ):
                raise ValueError(
                    f"files[{file_id!r}].symlinks[{idx}].target must be a non-empty str"
                )
            parsed_edges.append(_SymlinkEdge(path=edge_path, target=edge_target))
            edge_paths.append(edge_path)

        if edge_paths != sorted(set(edge_paths)):
            raise ValueError(
                f"files[{file_id!r}].symlinks must have unique edge paths in sorted lexical order"
            )

        if not parsed_edges and os.path.normpath(row_path) != row_resolved:
            raise ValueError(
                f"files[{file_id!r}] declares no symlinks but normalized path "
                f"{os.path.normpath(row_path)!r} != resolved_path {row_resolved!r}"
            )
        if parsed_edges:
            if row_path == row_resolved:
                raise ValueError(
                    f"files[{file_id!r}] declares symlinks but path == resolved_path ({row_path!r})"
                )
            if any(edge.path == row_resolved for edge in parsed_edges):
                raise ValueError(
                    f"files[{file_id!r}] resolved_path {row_resolved!r} cannot be a symlink edge"
                )
            lexical_chain = {
                str(p) for p in (Path(row_path), *Path(row_path).parents)
            }
            lex_stack: list[str] = []
            for seg in row_path.split("/"):
                if not seg or seg == ".":
                    continue
                if seg == "..":
                    if lex_stack:
                        lex_stack.pop()
                else:
                    lex_stack.append(seg)
                lexical_chain.add("/" + "/".join(lex_stack) if lex_stack else "/")
            if not any(edge.path in lexical_chain for edge in parsed_edges):
                raise ValueError(
                    f"files[{file_id!r}] symlinks do not include any component along path {row_path!r}"
                )

        checked_files[file_id] = MappingProxyType(
            {
                "path": row_path,
                "resolved_path": row_resolved,
                "sha256": row_sha256,
                "size_bytes": row_size,
                "symlinks": tuple(parsed_edges),
            }
        )

    raw_roots = payload["roots"]
    if not isinstance(raw_roots, Mapping) or set(raw_roots.keys()) != set(EXPECTED_ROOT_NAMES):
        raise ValueError(
            f"Profile manifest roots must have exact keys {list(EXPECTED_ROOT_NAMES)}"
        )

    checked_roots: dict[str, Mapping[str, Any]] = {}
    root_paths_by_name: dict[str, Path] = {}
    tree_member_ids: set[str] = set()

    for root_name in EXPECTED_ROOT_NAMES:
        raw_root = raw_roots[root_name]
        if (
            not isinstance(raw_root, Mapping)
            or set(raw_root.keys()) != EXPECTED_ROOT_ROW_KEYS
        ):
            raise ValueError(
                f"roots[{root_name!r}] must have exact keys {{'path', 'file_ids'}}"
            )
        root_path_str = _validate_canonical_no_traversal_abs_path(
            raw_root["path"], field_name=f"roots[{root_name!r}].path"
        )
        root_path_obj = Path(root_path_str)
        for prev_name, prev_path_obj in root_paths_by_name.items():
            if _paths_overlap(root_path_obj, prev_path_obj):
                raise ValueError(
                    f"Controlled roots {prev_name!r} ({prev_path_obj}) and "
                    f"{root_name!r} ({root_path_obj}) must be distinct and disjoint"
                )
        root_paths_by_name[root_name] = root_path_obj

        raw_fids = raw_root["file_ids"]
        if not isinstance(raw_fids, (list, tuple)) or len(raw_fids) == 0:
            raise ValueError(
                f"roots[{root_name!r}].file_ids must be a non-empty list of file IDs"
            )
        fids: list[str] = []
        for idx, fid in enumerate(raw_fids):
            valid_fid = _validate_opaque_id(
                fid, field_name=f"roots[{root_name!r}].file_ids[{idx}]"
            )
            if valid_fid not in checked_files:
                raise ValueError(
                    f"roots[{root_name!r}].file_ids references unknown file ID {valid_fid!r}"
                )
            fids.append(valid_fid)
        if len(fids) != len(set(fids)):
            raise ValueError(
                f"roots[{root_name!r}].file_ids contains duplicate file IDs"
            )
        fid_set = set(fids)
        if fid_set & tree_member_ids:
            raise ValueError(
                f"roots[{root_name!r}].file_ids overlaps another controlled root's file_ids"
            )

        for fid, frow in checked_files.items():
            if root_path_obj.is_relative_to(Path(frow["path"])) or root_path_obj.is_relative_to(
                Path(frow["resolved_path"])
            ):
                raise ValueError(
                    f"Controlled root {root_name!r} ({root_path_str!r}) overlaps file row {fid!r} ({frow['path']!r})"
                )

        expected_root_fids = {
            fid
            for fid, frow in checked_files.items()
            if Path(frow["path"]).is_relative_to(root_path_obj)
        }
        if fid_set != expected_root_fids:
            missing_in_root = sorted(expected_root_fids - fid_set)
            extra_in_root = sorted(fid_set - expected_root_fids)
            raise ValueError(
                f"roots[{root_name!r}].file_ids does not match files under {root_path_str!r}: "
                f"missing={missing_in_root}, extra={extra_in_root}"
            )

        for fid in fids:
            frow = checked_files[fid]
            if frow["path"] != frow["resolved_path"]:
                raise ValueError(
                    f"Controlled root {root_name!r} member {fid!r} must have path == resolved_path: "
                    f"{frow['path']!r} != {frow['resolved_path']!r}"
                )
            if frow["symlinks"]:
                raise ValueError(
                    f"Controlled root {root_name!r} member {fid!r} must not declare symlinks"
                )
            _validate_canonical_no_traversal_abs_path(
                frow["path"], field_name=f"roots[{root_name!r}] member {fid!r}.path"
            )
            if Path(frow["path"]) == root_path_obj or not Path(
                frow["path"]
            ).is_relative_to(root_path_obj):
                raise ValueError(
                    f"Controlled root {root_name!r} member {fid!r} is not inside {root_path_str!r}"
                )

        root_member_paths = {checked_files[fid]["path"] for fid in fids}
        for fid, frow in checked_files.items():
            if fid not in fid_set and Path(frow["resolved_path"]).is_relative_to(
                root_path_obj
            ):
                if frow["resolved_path"] not in root_member_paths:
                    raise ValueError(
                        f"External alias {fid!r} ({frow['path']!r}) resolves inside controlled root "
                        f"{root_name!r} to unlisted target {frow['resolved_path']!r}"
                    )

        tree_member_ids.update(fid_set)
        checked_roots[root_name] = MappingProxyType(
            {
                "path": root_path_str,
                "file_ids": tuple(fids),
            }
        )

    raw_roles = payload["roles"]
    if not isinstance(raw_roles, Mapping):
        raise ValueError("Profile manifest roles must be an object")
    actual_role_names = set(raw_roles.keys())
    if actual_role_names != EXPECTED_ALL_ROLES:
        missing_roles = sorted(EXPECTED_ALL_ROLES - actual_role_names)
        extra_roles = sorted(actual_role_names - EXPECTED_ALL_ROLES)
        raise ValueError(
            f"Profile manifest roles mismatch (expected 31 fixed roles): "
            f"missing={missing_roles}, extra={extra_roles}"
        )

    checked_roles: dict[str, tuple[str, ...]] = {}
    role_used_ids: set[str] = set()

    for role_name in sorted(EXPECTED_ALL_ROLES):
        raw_role_ids = raw_roles[role_name]
        if not isinstance(raw_role_ids, (list, tuple)) or len(raw_role_ids) == 0:
            raise ValueError(f"roles[{role_name!r}] must be a non-empty list of IDs")
        role_ids: list[str] = []
        for idx, fid in enumerate(raw_role_ids):
            valid_fid = _validate_opaque_id(
                fid, field_name=f"roles[{role_name!r}][{idx}]"
            )
            if valid_fid not in checked_files:
                raise ValueError(
                    f"roles[{role_name!r}] references unknown file ID {valid_fid!r}"
                )
            role_ids.append(valid_fid)
        if len(role_ids) != len(set(role_ids)):
            raise ValueError(f"roles[{role_name!r}] contains duplicate file IDs")

        if role_name in SINGLE_ROLES:
            if len(role_ids) != 1:
                raise ValueError(
                    f"Single-file role {role_name!r} must have exactly 1 ID, got {len(role_ids)}"
                )
        elif role_name in PAIR_ROLES:
            if len(role_ids) != 2:
                raise ValueError(
                    f"Pair role {role_name!r} must have exactly 2 IDs, got {len(role_ids)}"
                )
            orig_id, copy_id = role_ids
            orig_row = checked_files[orig_id]
            copy_row = checked_files[copy_id]
            if (
                orig_row["sha256"] != copy_row["sha256"]
                or orig_row["size_bytes"] != copy_row["size_bytes"]
            ):
                raise ValueError(
                    f"Pair role {role_name!r} original {orig_id!r} and copy {copy_id!r} "
                    "must have identical sha256 and size_bytes"
                )
            expected_orig_name, expected_copy_name = EXPECTED_PAIR_ROLE_BASENAMES[
                role_name
            ]
            actual_pair_names = (
                Path(orig_row["path"]).name,
                Path(copy_row["path"]).name,
            )
            if actual_pair_names != (expected_orig_name, expected_copy_name):
                raise ValueError(
                    f"Pair role {role_name!r} basenames must be "
                    f"{(expected_orig_name, expected_copy_name)}, got {actual_pair_names}"
                )
            build_root_str = checked_roots["build"]["path"]
            build_fids = set(checked_roots["build"]["file_ids"])
            if copy_id not in build_fids or copy_row["path"] != f"{build_root_str}/{expected_copy_name}":
                raise ValueError(
                    f"Pair role {role_name!r} copy must be {build_root_str}/{expected_copy_name}"
                )
            if orig_id in tree_member_ids:
                raise ValueError(
                    f"Pair role {role_name!r} original {orig_id!r} must be outside controlled roots"
                )
        elif role_name in VARIABLE_ROLES:
            if role_ids != sorted(role_ids):
                raise ValueError(
                    f"Variable role {role_name!r} IDs must be sorted lexically"
                )
        elif role_name == "build_inventories":
            if len(role_ids) != 8:
                raise ValueError(
                    f"roles['build_inventories'] must have 8 IDs, got {len(role_ids)}"
                )
            build_root_str = checked_roots["build"]["path"]
            build_fids = set(checked_roots["build"]["file_ids"])
            for pair_idx, inv_name in enumerate(EXPECTED_BUILD_INVENTORY_BASENAME_PAIRS):
                orig_id = role_ids[2 * pair_idx]
                copy_id = role_ids[2 * pair_idx + 1]
                orig_row = checked_files[orig_id]
                copy_row = checked_files[copy_id]
                if (
                    Path(orig_row["path"]).name != inv_name
                    or Path(copy_row["path"]).name != inv_name
                ):
                    raise ValueError(
                        f"roles['build_inventories'] pair {pair_idx} must be for {inv_name!r}"
                    )
                if (
                    orig_row["sha256"] != copy_row["sha256"]
                    or orig_row["size_bytes"] != copy_row["size_bytes"]
                ):
                    raise ValueError(
                        f"roles['build_inventories'] pair for {inv_name!r} must have matching sha256/size_bytes"
                    )
                if copy_id not in build_fids or copy_row["path"] != f"{build_root_str}/{inv_name}":
                    raise ValueError(
                        f"roles['build_inventories'] copy for {inv_name!r} must be {build_root_str}/{inv_name}"
                    )
                if orig_id in tree_member_ids:
                    raise ValueError(
                        f"roles['build_inventories'] original for {inv_name!r} must be outside controlled roots"
                    )
        elif role_name == "collector_helpers":
            if len(role_ids) != 8:
                raise ValueError(
                    f"roles['collector_helpers'] must have 8 IDs, got {len(role_ids)}"
                )
            actual_helper_names = tuple(
                Path(checked_files[fid]["path"]).name for fid in role_ids
            )
            if actual_helper_names != EXPECTED_COLLECTOR_HELPER_NAMES:
                raise ValueError(
                    "roles['collector_helpers'] basenames must match exact ordered "
                    f"{EXPECTED_COLLECTOR_HELPER_NAMES}, got {actual_helper_names}"
                )
            for fid in role_ids:
                if fid in tree_member_ids:
                    raise ValueError(
                        f"Collector helper {fid!r} must not be inside a controlled vendor/prepared/build root"
                    )

        checked_roles[role_name] = tuple(role_ids)
        role_used_ids.update(role_ids)

    # Check fixed root-bound role locations and meanings
    prepared_root_str = checked_roots["prepared"]["path"]
    prepared_fids = set(checked_roots["prepared"]["file_ids"])
    build_root_str = checked_roots["build"]["path"]
    build_fids = set(checked_roots["build"]["file_ids"])

    source_manifest_id = checked_roles["source_manifest"][0]
    if (
        source_manifest_id not in prepared_fids
        or checked_files[source_manifest_id]["path"]
        != f"{prepared_root_str}/refmac_diagnostic_source_manifest.json"
    ):
        raise ValueError(
            "roles['source_manifest'] must point to "
            f"{prepared_root_str}/refmac_diagnostic_source_manifest.json"
        )

    build_receipt_id = checked_roles["build_receipt"][0]
    if (
        build_receipt_id not in build_fids
        or checked_files[build_receipt_id]["path"]
        != f"{build_root_str}/build-receipt.json"
    ):
        raise ValueError(
            f"roles['build_receipt'] must point to {build_root_str}/build-receipt.json"
        )

    linked_exe_id = checked_roles["linked_executable"][0]
    if (
        linked_exe_id not in build_fids
        or checked_files[linked_exe_id]["path"]
        != f"{build_root_str}/refmac5.linked-unrelocated"
    ):
        raise ValueError(
            "roles['linked_executable'] must point to "
            f"{build_root_str}/refmac5.linked-unrelocated"
        )

    diag_exe_id = checked_roles["diagnostic_executable"][0]
    diag_exe_row = checked_files[diag_exe_id]
    if diag_exe_id not in build_fids or not Path(diag_exe_row["path"]).is_relative_to(
        Path(build_root_str)
    ):
        raise ValueError(
            f"roles['diagnostic_executable'] must be a member of build root {build_root_str!r}"
        )
    if diag_exe_id == linked_exe_id or diag_exe_row["path"] == checked_files[linked_exe_id]["path"]:
        raise ValueError(
            "roles['diagnostic_executable'] must be distinct from roles['linked_executable']"
        )

    installed_ref_id = checked_roles["installed_reference"][0]
    installed_ref_row = checked_files[installed_ref_id]
    if installed_ref_id in tree_member_ids:
        raise ValueError(
            "roles['installed_reference'] must be outside the controlled vendor/prepared/build roots"
        )
    if (
        diag_exe_id == installed_ref_id
        or diag_exe_row["path"] == installed_ref_row["path"]
        or diag_exe_row["resolved_path"] == installed_ref_row["resolved_path"]
    ):
        raise ValueError(
            "roles['diagnostic_executable'] must be distinct from roles['installed_reference']"
        )

    if expected_executable_pin is not None:
        if type(expected_executable_pin) is not FilePin:
            raise ValueError("expected_executable_pin must be a FilePin")
        if (
            diag_exe_row["path"] != expected_executable_pin.path
            or diag_exe_row["sha256"] != expected_executable_pin.sha256
            or diag_exe_row["size_bytes"] != expected_executable_pin.size_bytes
        ):
            raise ValueError(
                "roles['diagnostic_executable'] does not match caller-held executable FilePin: "
                f"manifest=({diag_exe_row['path']!r}, {diag_exe_row['sha256']}, {diag_exe_row['size_bytes']}) "
                f"vs caller=({expected_executable_pin.path!r}, {expected_executable_pin.sha256}, {expected_executable_pin.size_bytes})"
            )
        if diag_exe_row["sha256"] == installed_ref_row["sha256"]:
            raise ValueError(
                "roles['diagnostic_executable'] sha256 must differ from roles['installed_reference'] sha256"
            )

    # Every file row in files must be either a controlled root member or referenced by a role.
    unclassified_ids = sorted(set(checked_files.keys()) - (tree_member_ids | role_used_ids))
    if unclassified_ids:
        raise ValueError(
            f"Manifest contains unused external file row(s) with no role and outside roots: {unclassified_ids}"
        )

    raw_rt = payload["runtime_environment"]
    if (
        not isinstance(raw_rt, Mapping)
        or set(raw_rt.keys()) != EXPECTED_RUNTIME_ENV_OUTER_KEYS
    ):
        raise ValueError(
            "runtime_environment must have exact keys "
            "{'observation_file_id', 'expected_values', 'expected_absent'}"
        )
    obs_fid = _validate_opaque_id(
        raw_rt["observation_file_id"],
        field_name="runtime_environment.observation_file_id",
    )
    if obs_fid != checked_roles["runtime_observation"][0]:
        raise ValueError(
            "runtime_environment.observation_file_id must equal roles['runtime_observation'][0]"
        )

    raw_expected_values = raw_rt["expected_values"]
    if not isinstance(raw_expected_values, Mapping):
        raise ValueError("runtime_environment.expected_values must be an object")
    if set(raw_expected_values.keys()) != EXPECTED_RUNTIME_ENV_KEYS:
        missing_env = sorted(EXPECTED_RUNTIME_ENV_KEYS - set(raw_expected_values.keys()))
        extra_env = sorted(set(raw_expected_values.keys()) - EXPECTED_RUNTIME_ENV_KEYS)
        raise ValueError(
            f"runtime_environment.expected_values keys mismatch: missing={missing_env}, extra={extra_env}"
        )
    checked_env_values: dict[str, str] = {}
    for k, v in sorted(raw_expected_values.items()):
        if type(k) is not str or type(v) is not str:
            raise ValueError(
                f"runtime_environment.expected_values[{k!r}] must be a str, got {type(v).__name__}"
            )
        checked_env_values[k] = v

    raw_expected_absent = raw_rt["expected_absent"]
    if (
        not isinstance(raw_expected_absent, (list, tuple))
        or tuple(raw_expected_absent) != EXPECTED_RUNTIME_ABSENT_KEYS
    ):
        raise ValueError(
            f"runtime_environment.expected_absent must equal {list(EXPECTED_RUNTIME_ABSENT_KEYS)}"
        )

    checked_rt = _CheckedRuntimeEnvironmentOuter(
        observation_file_id=obs_fid,
        expected_values=checked_env_values,
        expected_absent=EXPECTED_RUNTIME_ABSENT_KEYS,
    )

    return _CheckedOuterManifest(
        schema_id=schema_id,
        profile_id=profile_id,
        subject_id=subject_id,
        upstream_commit=commit,
        upstream_tag=tag,
        roots=checked_roots,
        files=checked_files,
        roles=checked_roles,
        runtime_environment=checked_rt,
        tree_member_ids=frozenset(tree_member_ids),
        role_used_ids=frozenset(role_used_ids),
    )



def _empty_mapping_proxy() -> Mapping[Any, Any]:
    """Return an empty immutable :class:`MappingProxyType` for dataclass ``default_factory``."""
    return MappingProxyType({})


@dataclass(frozen=True)
class _ObservedRootInventory:
    """Immutable observation of a controlled root directory and its physical inventory."""

    name: str
    path: str
    resolved_path: str
    file_ids: tuple[str, ...]
    directory_identity: _ObservedDirectoryIdentity
    ancestor_identities: tuple[_ObservedDirectoryIdentity, ...]
    subdirectory_identities: Mapping[str, _ObservedDirectoryIdentity]
    member_pins: Mapping[str, FilePin]
    excluded_root_git_present: bool
    member_observations: Mapping[str, _ObservedRegularFilePin] = field(
        default_factory=_empty_mapping_proxy
    )
    scan_complete: bool = True
    verified: bool = True
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.name not in EXPECTED_ROOT_NAMES:
            raise ValueError(f"Invalid controlled root name: {self.name!r}")
        _validate_canonical_no_traversal_abs_path(
            self.path, field_name="_ObservedRootInventory.path"
        )
        _validate_canonical_no_traversal_abs_path(
            self.resolved_path, field_name="_ObservedRootInventory.resolved_path"
        )
        if self.path != self.resolved_path:
            raise ValueError(
                f"Controlled root {self.name!r} path {self.path!r} != resolved_path {self.resolved_path!r}"
            )
        if type(self.file_ids) is not tuple or not all(
            type(fid) is str and fid for fid in self.file_ids
        ):
            raise ValueError("_ObservedRootInventory.file_ids must be a tuple of str")
        if type(self.directory_identity) is not _ObservedDirectoryIdentity:
            raise ValueError(
                "_ObservedRootInventory.directory_identity must be _ObservedDirectoryIdentity"
            )
        if type(self.ancestor_identities) is not tuple or not all(
            type(anc) is _ObservedDirectoryIdentity for anc in self.ancestor_identities
        ):
            raise ValueError(
                "_ObservedRootInventory.ancestor_identities must be a tuple of _ObservedDirectoryIdentity"
            )
        if not isinstance(self.subdirectory_identities, Mapping) or not all(
            type(k) is str and type(v) is _ObservedDirectoryIdentity
            for k, v in self.subdirectory_identities.items()
        ):
            raise ValueError(
                "_ObservedRootInventory.subdirectory_identities must map rel_posix -> _ObservedDirectoryIdentity"
            )
        if not isinstance(self.member_pins, Mapping) or not all(
            type(k) is str and type(v) is FilePin
            for k, v in self.member_pins.items()
        ):
            raise ValueError(
                "_ObservedRootInventory.member_pins must map rel_posix -> FilePin"
            )
        if not isinstance(self.member_observations, Mapping) or not all(
            type(k) is str and type(v) is _ObservedRegularFilePin
            for k, v in self.member_observations.items()
        ):
            raise ValueError(
                "_ObservedRootInventory.member_observations must map rel_posix -> _ObservedRegularFilePin"
            )
        if type(self.excluded_root_git_present) is not bool:
            raise ValueError(
                "_ObservedRootInventory.excluded_root_git_present must be a bool"
            )
        if type(self.scan_complete) is not bool:
            raise ValueError("_ObservedRootInventory.scan_complete must be a bool")
        if type(self.verified) is not bool:
            raise ValueError("_ObservedRootInventory.verified must be a bool")
        if type(self.errors) is not tuple or not all(
            type(e) is str for e in self.errors
        ):
            raise ValueError("_ObservedRootInventory.errors must be a tuple of str")
        if self.verified and (not self.scan_complete or len(self.errors) > 0):
            raise ValueError(
                "_ObservedRootInventory cannot be verified when scan_complete is False or errors are present"
            )
        object.__setattr__(
            self,
            "subdirectory_identities",
            MappingProxyType(dict(sorted(self.subdirectory_identities.items()))),
        )
        object.__setattr__(
            self,
            "member_pins",
            MappingProxyType(dict(sorted(self.member_pins.items()))),
        )
        object.__setattr__(
            self,
            "member_observations",
            MappingProxyType(dict(sorted(self.member_observations.items()))),
        )
        object.__setattr__(self, "errors", tuple(self.errors))


class _ControlledRootObservationError(ValueError):
    """ValueError subclass carrying an incomplete or unverified :class:`_ObservedRootInventory`."""

    def __init__(
        self,
        message: str,
        *,
        root_inventory: _ObservedRootInventory | None,
        errors: tuple[str, ...],
    ) -> None:
        super().__init__(message)
        self.root_inventory = root_inventory
        self.errors = tuple(errors)


@dataclass(frozen=True)
class _PartialProfileObservation:
    """Immutable snapshot of obtainable observations retained when outer validation fails."""

    profile: RefmacDiagnosticProfile
    evidence_root: str | None
    evidence_root_ancestor_identities: tuple[_ObservedDirectoryIdentity, ...]
    manifest_observation: _ObservedRegularFilePin | None
    outer_manifest: _CheckedOuterManifest | None
    observed_roots: Mapping[str, _ObservedRootInventory]
    observed_files: Mapping[str, _ObservedRegularFilePin]
    observed_ancestors: Mapping[str, _ObservedDirectoryIdentity]
    observed_symlinks: Mapping[str, _ObservedSymlinkIdentity]
    errors: tuple[str, ...]
    verified_roots: Mapping[str, _ObservedRootInventory] = field(
        default_factory=_empty_mapping_proxy
    )
    failed_roots: Mapping[str, _ObservedRootInventory] = field(
        default_factory=_empty_mapping_proxy
    )
    incomplete_roots: Mapping[str, _ObservedRootInventory] = field(
        default_factory=_empty_mapping_proxy
    )
    verified_files: Mapping[str, _ObservedRegularFilePin] = field(
        default_factory=_empty_mapping_proxy
    )
    unverified_files: Mapping[str, _ObservedRegularFilePin] = field(
        default_factory=_empty_mapping_proxy
    )

    def __post_init__(self) -> None:
        if type(self.profile) is not RefmacDiagnosticProfile:
            raise ValueError(
                "_PartialProfileObservation.profile must be RefmacDiagnosticProfile"
            )
        sorted_roots = dict(sorted(self.observed_roots.items()))
        sorted_files = dict(sorted(self.observed_files.items()))
        object.__setattr__(
            self,
            "evidence_root_ancestor_identities",
            tuple(self.evidence_root_ancestor_identities),
        )
        object.__setattr__(
            self,
            "observed_roots",
            MappingProxyType(sorted_roots),
        )
        object.__setattr__(
            self,
            "observed_files",
            MappingProxyType(sorted_files),
        )
        object.__setattr__(
            self,
            "observed_ancestors",
            MappingProxyType(dict(sorted(self.observed_ancestors.items()))),
        )
        object.__setattr__(
            self,
            "observed_symlinks",
            MappingProxyType(dict(sorted(self.observed_symlinks.items()))),
        )
        object.__setattr__(self, "errors", tuple(self.errors))
        object.__setattr__(
            self,
            "verified_roots",
            MappingProxyType(
                {
                    k: v
                    for k, v in sorted_roots.items()
                    if v.scan_complete and v.verified
                }
            ),
        )
        object.__setattr__(
            self,
            "failed_roots",
            MappingProxyType(
                {k: v for k, v in sorted_roots.items() if not v.verified}
            ),
        )
        object.__setattr__(
            self,
            "incomplete_roots",
            MappingProxyType(
                {k: v for k, v in sorted_roots.items() if not v.scan_complete}
            ),
        )
        if not set(self.verified_files.keys()).isdisjoint(
            set(self.unverified_files.keys())
        ):
            raise ValueError(
                "_PartialProfileObservation.verified_files and unverified_files must be disjoint"
            )
        object.__setattr__(
            self,
            "verified_files",
            MappingProxyType(dict(sorted(self.verified_files.items()))),
        )
        object.__setattr__(
            self,
            "unverified_files",
            MappingProxyType(dict(sorted(self.unverified_files.items()))),
        )


class _ProfileObservationError(ValueError):
    """ValueError subclass carrying an immutable :class:`_PartialProfileObservation`."""

    def __init__(
        self,
        message: str,
        *,
        partial_observation: _PartialProfileObservation,
        errors: tuple[str, ...] | None = None,
    ) -> None:
        super().__init__(message)
        if type(partial_observation) is not _PartialProfileObservation:
            raise ValueError(
                "partial_observation must be a _PartialProfileObservation instance"
            )
        self.partial_observation: _PartialProfileObservation = partial_observation
        self.errors: tuple[str, ...] = (
            tuple(errors) if errors is not None else partial_observation.errors
        )


@dataclass(frozen=True)
class _CheckedOuterProfileState:
    """Deeply immutable private state of a verified outer profile and its on-disk files/roots.

    Note: This represents outer manifest and file/root verification only, not
    inner receipt joins, public profile admission, or scientific eligibility.
    """

    profile: RefmacDiagnosticProfile
    selected_executable: FilePin
    evidence_root: str | None
    evidence_root_ancestor_identities: tuple[_ObservedDirectoryIdentity, ...]
    manifest_observation: _ObservedRegularFilePin
    outer_manifest: _CheckedOuterManifest
    observed_roots: Mapping[str, _ObservedRootInventory]
    observed_files: Mapping[str, _ObservedRegularFilePin]
    observed_ancestors: Mapping[str, _ObservedDirectoryIdentity]
    observed_symlinks: Mapping[str, _ObservedSymlinkIdentity]
    outer_files_verified: bool = True
    inner_receipt_joins_status: str = "deferred_to_next_slice"
    runtime_image_coverage: str = "not_assessed"

    def __post_init__(self) -> None:
        if type(self.profile) is not RefmacDiagnosticProfile:
            raise ValueError(
                "_CheckedOuterProfileState.profile must be RefmacDiagnosticProfile"
            )
        if type(self.selected_executable) is not FilePin:
            raise ValueError(
                "_CheckedOuterProfileState.selected_executable must be FilePin"
            )
        if self.selected_executable != self.profile.executable:
            raise ValueError(
                "_CheckedOuterProfileState.selected_executable must match profile.executable"
            )
        if type(self.manifest_observation) is not _ObservedRegularFilePin:
            raise ValueError(
                "_CheckedOuterProfileState.manifest_observation must be _ObservedRegularFilePin"
            )
        if type(self.outer_manifest) is not _CheckedOuterManifest:
            raise ValueError(
                "_CheckedOuterProfileState.outer_manifest must be _CheckedOuterManifest"
            )
        if self.outer_files_verified is not True:
            raise ValueError(
                "_CheckedOuterProfileState requires outer_files_verified=True"
            )
        for r_name, r_inv in self.observed_roots.items():
            if not r_inv.scan_complete or not r_inv.verified or r_inv.errors:
                raise ValueError(
                    f"_CheckedOuterProfileState cannot accept unverified or incomplete root {r_name!r}"
                )
        object.__setattr__(
            self,
            "evidence_root_ancestor_identities",
            tuple(self.evidence_root_ancestor_identities),
        )
        object.__setattr__(
            self,
            "observed_roots",
            MappingProxyType(dict(sorted(self.observed_roots.items()))),
        )
        object.__setattr__(
            self,
            "observed_files",
            MappingProxyType(dict(sorted(self.observed_files.items()))),
        )
        object.__setattr__(
            self,
            "observed_ancestors",
            MappingProxyType(dict(sorted(self.observed_ancestors.items()))),
        )
        object.__setattr__(
            self,
            "observed_symlinks",
            MappingProxyType(dict(sorted(self.observed_symlinks.items()))),
        )


@dataclass(frozen=True)
class _OuterProfileRecheckResult:
    """Immutable result of re-observing files, roots, and manifest against an original baseline."""

    verified: bool
    manifest_observation: _ObservedRegularFilePin | None
    observed_roots: Mapping[str, _ObservedRootInventory]
    observed_files: Mapping[str, _ObservedRegularFilePin]
    observed_ancestors: Mapping[str, _ObservedDirectoryIdentity]
    observed_symlinks: Mapping[str, _ObservedSymlinkIdentity]
    errors: tuple[str, ...]
    verified_roots: Mapping[str, _ObservedRootInventory] = field(
        default_factory=_empty_mapping_proxy
    )
    failed_roots: Mapping[str, _ObservedRootInventory] = field(
        default_factory=_empty_mapping_proxy
    )
    incomplete_roots: Mapping[str, _ObservedRootInventory] = field(
        default_factory=_empty_mapping_proxy
    )
    verified_files: Mapping[str, _ObservedRegularFilePin] = field(
        default_factory=_empty_mapping_proxy
    )
    unverified_files: Mapping[str, _ObservedRegularFilePin] = field(
        default_factory=_empty_mapping_proxy
    )

    def __post_init__(self) -> None:
        if type(self.verified) is not bool:
            raise ValueError("_OuterProfileRecheckResult.verified must be a bool")
        sorted_roots = dict(sorted(self.observed_roots.items()))
        sorted_files = dict(sorted(self.observed_files.items()))
        object.__setattr__(
            self,
            "observed_roots",
            MappingProxyType(sorted_roots),
        )
        object.__setattr__(
            self,
            "observed_files",
            MappingProxyType(sorted_files),
        )
        object.__setattr__(
            self,
            "observed_ancestors",
            MappingProxyType(dict(sorted(self.observed_ancestors.items()))),
        )
        object.__setattr__(
            self,
            "observed_symlinks",
            MappingProxyType(dict(sorted(self.observed_symlinks.items()))),
        )
        object.__setattr__(self, "errors", tuple(self.errors))
        object.__setattr__(
            self,
            "verified_roots",
            MappingProxyType(
                {
                    k: v
                    for k, v in sorted_roots.items()
                    if v.scan_complete and v.verified
                }
            ),
        )
        object.__setattr__(
            self,
            "failed_roots",
            MappingProxyType(
                {k: v for k, v in sorted_roots.items() if not v.verified}
            ),
        )
        object.__setattr__(
            self,
            "incomplete_roots",
            MappingProxyType(
                {k: v for k, v in sorted_roots.items() if not v.scan_complete}
            ),
        )
        if not set(self.verified_files.keys()).isdisjoint(
            set(self.unverified_files.keys())
        ):
            raise ValueError(
                "_PartialProfileObservation.verified_files and unverified_files must be disjoint"
            )
        object.__setattr__(
            self,
            "verified_files",
            MappingProxyType(dict(sorted(self.verified_files.items()))),
        )
        object.__setattr__(
            self,
            "unverified_files",
            MappingProxyType(dict(sorted(self.unverified_files.items()))),
        )


def _observe_directory_identity(
    dir_path_str: str,
    *,
    require_no_symlink_ancestors: bool = False,
) -> _ObservedDirectoryIdentity:
    """Observe a directory's mtime-free ``(dev, ino, mode, uid, gid)`` identity."""
    _validate_lexical_abs_path(dir_path_str, field_name="directory path")
    try:
        st = os.lstat(dir_path_str)
    except OSError as exc:
        raise ValueError(
            f"Cannot lstat directory {dir_path_str!r} ({type(exc).__name__}): {exc}"
        ) from exc
    if stat.S_ISLNK(st.st_mode):
        raise ValueError(f"Expected directory but found symlink at {dir_path_str!r}")
    if not stat.S_ISDIR(st.st_mode):
        raise ValueError(f"Expected directory at {dir_path_str!r}")

    try:
        resolved_obj = Path(dir_path_str).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError(
            f"Cannot resolve directory {dir_path_str!r} ({type(exc).__name__}): {exc}"
        ) from exc
    resolved_str = str(resolved_obj)

    if require_no_symlink_ancestors:
        _validate_canonical_no_traversal_abs_path(
            dir_path_str,
            field_name="controlled directory path",
            allow_root=True,
        )
        if resolved_str != dir_path_str:
            raise ValueError(
                f"Controlled directory {dir_path_str!r} resolved to different path {resolved_str!r}"
            )
        for anc in (resolved_obj, *resolved_obj.parents):
            try:
                anc_st = os.lstat(str(anc))
            except OSError as exc:
                raise ValueError(
                    f"Cannot lstat ancestor {anc} ({type(exc).__name__}): {exc}"
                ) from exc
            if stat.S_ISLNK(anc_st.st_mode) or not stat.S_ISDIR(anc_st.st_mode):
                raise ValueError(
                    f"Ancestor {anc} of {dir_path_str!r} is not a non-symlink directory"
                )

    return _ObservedDirectoryIdentity(
        path=dir_path_str,
        resolved_path=resolved_str,
        dev=int(st.st_dev),
        ino=int(st.st_ino),
        mode=int(stat.S_IMODE(st.st_mode)),
        uid=int(st.st_uid),
        gid=int(st.st_gid),
    )


def _observe_symlink_identity(
    edge: _SymlinkEdge,
) -> _ObservedSymlinkIdentity:
    """Observe a literal symlink's mtime-free ``(dev, ino, mode, uid, gid)`` identity and target."""
    try:
        st = os.lstat(edge.path)
        actual_target = os.readlink(edge.path)
    except OSError as exc:
        raise ValueError(
            f"Cannot inspect symlink {edge.path!r} ({type(exc).__name__}): {exc}"
        ) from exc
    if not stat.S_ISLNK(st.st_mode):
        raise ValueError(f"Expected symlink at {edge.path!r}")
    if actual_target != edge.target:
        raise ValueError(
            f"Symlink target changed at {edge.path!r}: expected {edge.target!r}, got {actual_target!r}"
        )
    return _ObservedSymlinkIdentity(
        path=edge.path,
        target=actual_target,
        dev=int(st.st_dev),
        ino=int(st.st_ino),
        mode=int(stat.S_IMODE(st.st_mode)),
        uid=int(st.st_uid),
        gid=int(st.st_gid),
    )


def _record_directory_identity(
    store: dict[str, _ObservedDirectoryIdentity],
    obs: _ObservedDirectoryIdentity,
) -> None:
    prev = store.get(obs.path)
    if prev is not None and prev != obs:
        raise ValueError(
            f"Directory identity changed during observation at {obs.path!r}: "
            f"before={prev.to_dict()}, after={obs.to_dict()}"
        )
    store[obs.path] = obs


def _record_symlink_identity(
    store: dict[str, _ObservedSymlinkIdentity],
    obs: _ObservedSymlinkIdentity,
) -> None:
    prev = store.get(obs.path)
    if prev is not None and prev != obs:
        raise ValueError(
            f"Symlink identity changed during observation at {obs.path!r}: "
            f"before={prev.to_dict()}, after={obs.to_dict()}"
        )
    store[obs.path] = obs


def _observe_file_ancestors_and_symlinks(
    file_obs: _ObservedRegularFilePin,
    *,
    ancestors_out: dict[str, _ObservedDirectoryIdentity],
    symlinks_out: dict[str, _ObservedSymlinkIdentity],
) -> None:
    """Observe resolved ancestors, raw/traversed directory dependencies, and literal symlink edges."""
    traversal = _traverse_path_components(file_obs.path)
    if traversal.resolved_path != file_obs.resolved_path:
        raise ValueError(
            f"Resolved target path changed during ancestor/symlink observation for {file_obs.path!r}: "
            f"expected {file_obs.resolved_path!r}, observed {traversal.resolved_path!r}"
        )
    if traversal.symlink_edges != file_obs.symlinks:
        raise ValueError(
            f"Symlink edges changed during ancestor/symlink observation for {file_obs.path!r}"
        )

    resolved_path_obj = Path(file_obs.resolved_path)
    for anc in resolved_path_obj.parents:
        anc_obs = _observe_directory_identity(
            str(anc), require_no_symlink_ancestors=False
        )
        if anc_obs.path != anc_obs.resolved_path:
            raise ValueError(
                f"Resolved ancestor {anc} is not canonical ({anc_obs.resolved_path!r})"
            )
        _record_directory_identity(ancestors_out, anc_obs)

    for dir_path in traversal.directory_paths:
        dir_obs = _observe_directory_identity(
            dir_path, require_no_symlink_ancestors=False
        )
        if dir_obs.path != dir_obs.resolved_path:
            raise ValueError(
                f"Traversed directory dependency {dir_path!r} is not canonical ({dir_obs.resolved_path!r})"
            )
        _record_directory_identity(ancestors_out, dir_obs)

    for edge in traversal.symlink_edges:
        sym_obs = _observe_symlink_identity(edge)
        _record_symlink_identity(symlinks_out, sym_obs)


def _validate_and_observe_evidence_root(
    evidence_root: str | os.PathLike[str],
) -> tuple[str, tuple[_ObservedDirectoryIdentity, ...]]:
    """Validate ``evidence_root`` without requiring it to exist yet; observe existing ancestors."""
    if isinstance(evidence_root, bool) or not isinstance(
        evidence_root, (str, os.PathLike)
    ):
        raise ValueError(
            f"evidence_root must be a str or os.PathLike, got {type(evidence_root).__name__}"
        )
    raw_ev = evidence_root if type(evidence_root) is str else os.fspath(evidence_root)
    _validate_canonical_no_traversal_abs_path(raw_ev, field_name="evidence_root")

    ev_path = Path(raw_ev)
    existing_ancestors: list[_ObservedDirectoryIdentity] = []
    missing_seen = False

    for candidate in (ev_path, *ev_path.parents):
        cand_str = str(candidate)
        try:
            st = os.lstat(cand_str)
        except FileNotFoundError:
            missing_seen = True
            continue
        except OSError as exc:
            raise ValueError(
                f"Cannot inspect evidence_root component {cand_str!r} ({type(exc).__name__}): {exc}"
            ) from exc

        if stat.S_ISLNK(st.st_mode):
            raise ValueError(
                f"evidence_root or its ancestor must not be a symlink: {cand_str!r}"
            )
        if not stat.S_ISDIR(st.st_mode):
            raise ValueError(
                f"Existing evidence_root component is not a directory: {cand_str!r}"
            )
        obs = _observe_directory_identity(
            cand_str, require_no_symlink_ancestors=True
        )
        existing_ancestors.append(obs)
        if missing_seen:
            # Once an existing ancestor is verified with require_no_symlink_ancestors=True,
            # continue collecting remaining ancestors up to '/'.
            pass

    if not existing_ancestors:
        raise ValueError(
            f"No existing ancestor directory found for evidence_root {raw_ev!r}"
        )
    return raw_ev, tuple(existing_ancestors)


def _observe_controlled_root(
    root_name: str,
    root_path: str,
    declared_file_ids: tuple[str, ...],
    *,
    declared_files: Mapping[str, Mapping[str, Any]],
    exclude_root_git: bool = False,
    chunk_size: int = STREAM_CHUNK_BYTES,
) -> _ObservedRootInventory:
    """Validate and enumerate a controlled root (``vendor``, ``prepared``, or ``build``)."""
    _validate_canonical_no_traversal_abs_path(
        root_path, field_name=f"roots[{root_name!r}].path"
    )
    root_dir_obs = _observe_directory_identity(
        root_path, require_no_symlink_ancestors=True
    )
    root_path_obj = Path(root_path)
    ancestor_list: list[_ObservedDirectoryIdentity] = []
    for anc in (root_path_obj, *root_path_obj.parents):
        ancestor_list.append(
            _observe_directory_identity(
                str(anc), require_no_symlink_ancestors=True
            )
        )

    def _raise_walk_error(exc: OSError) -> None:
        raise ValueError(
            f"Incomplete controlled root enumeration for {root_name!r} at {root_path!r} "
            f"({type(exc).__name__}): {exc}"
        ) from exc

    subdir_identities: dict[str, _ObservedDirectoryIdentity] = {}
    member_pins: dict[str, FilePin] = {}
    member_observations: dict[str, _ObservedRegularFilePin] = {}
    excluded_git_present = False

    try:
        for base, dirs, files in os.walk(
            root_path, topdown=True, followlinks=False, onerror=_raise_walk_error
        ):
            base_path = Path(base)
            if exclude_root_git and base_path == root_path_obj:
                if ".git" in dirs or ".git" in files:
                    excluded_git_present = True
                dirs[:] = sorted(d for d in dirs if d != ".git")
                files = sorted(f for f in files if f != ".git")
            else:
                dirs.sort()
                files = sorted(files)

            for entry_name in [*dirs, *files]:
                entry_path = base_path / entry_name
                entry_str = str(entry_path)
                try:
                    entry_lstat = os.lstat(entry_str)
                except OSError as exc:
                    raise ValueError(
                        f"Cannot lstat controlled root member {entry_str!r} in {root_name!r} "
                        f"({type(exc).__name__}): {exc}"
                    ) from exc
                if stat.S_ISLNK(entry_lstat.st_mode):
                    raise ValueError(
                        f"Controlled root {root_name!r} contains forbidden symlink: {entry_str!r}"
                    )

            for dname in dirs:
                dpath = base_path / dname
                dstr = str(dpath)
                rel_dir = dpath.relative_to(root_path_obj).as_posix()
                d_obs = _observe_directory_identity(
                    dstr, require_no_symlink_ancestors=False
                )
                if d_obs.path != d_obs.resolved_path:
                    raise ValueError(
                        f"Controlled root {root_name!r} subdirectory {dstr!r} resolved to {d_obs.resolved_path!r}"
                    )
                subdir_identities[rel_dir] = d_obs

            for fname in files:
                fpath = base_path / fname
                fstr = str(fpath)
                try:
                    flstat = os.lstat(fstr)
                except OSError as exc:
                    raise ValueError(
                        f"Cannot lstat controlled root file {fstr!r} in {root_name!r}: {exc}"
                    ) from exc
                if not stat.S_ISREG(flstat.st_mode):
                    raise ValueError(
                        f"Controlled root {root_name!r} contains non-regular member: {fstr!r}"
                    )
                f_obs = _observe_regular_file_pin(fstr, chunk_size=chunk_size)
                rel_file = fpath.relative_to(root_path_obj).as_posix()
                member_pins[rel_file] = f_obs.as_file_pin()
                member_observations[rel_file] = f_obs
                if f_obs.path != f_obs.resolved_path or f_obs.symlinks:
                    raise ValueError(
                        f"Controlled root {root_name!r} member {fstr!r} must not use symlinks"
                    )

        root_dir_after = _observe_directory_identity(
            root_path, require_no_symlink_ancestors=True
        )
        if root_dir_after != root_dir_obs:
            raise ValueError(
                f"Controlled root {root_name!r} directory identity changed during enumeration"
            )
    except ValueError as exc:
        err_msg = str(exc)
        incomplete_inv = _ObservedRootInventory(
            name=root_name,
            path=root_path,
            resolved_path=root_dir_obs.resolved_path,
            file_ids=declared_file_ids,
            directory_identity=root_dir_obs,
            ancestor_identities=tuple(ancestor_list),
            subdirectory_identities=subdir_identities,
            member_pins=member_pins,
            excluded_root_git_present=excluded_git_present,
            member_observations=member_observations,
            scan_complete=False,
            verified=False,
            errors=(err_msg,),
        )
        raise _ControlledRootObservationError(
            err_msg,
            root_inventory=incomplete_inv,
            errors=(err_msg,),
        ) from exc

    declared_by_rel: dict[str, FilePin] = {}
    for fid in declared_file_ids:
        frow = declared_files[fid]
        rel_posix = Path(frow["path"]).relative_to(root_path_obj).as_posix()
        declared_by_rel[rel_posix] = FilePin(
            path=frow["path"],
            sha256=frow["sha256"],
            size_bytes=frow["size_bytes"],
        )

    root_errors: list[str] = []
    actual_rels = set(member_pins.keys())
    expected_rels = set(declared_by_rel.keys())
    if actual_rels != expected_rels:
        missing_rels = sorted(expected_rels - actual_rels)
        extra_rels = sorted(actual_rels - expected_rels)
        root_errors.append(
            f"Controlled root {root_name!r} member set mismatch under {root_path!r}: "
            f"missing_on_disk={missing_rels}, extra_on_disk={extra_rels}"
        )

    for rel_posix in sorted(expected_rels & actual_rels):
        expected_pin = declared_by_rel[rel_posix]
        actual_pin = member_pins[rel_posix]
        if actual_pin != expected_pin:
            root_errors.append(
                f"Controlled root {root_name!r} member {rel_posix!r} pin mismatch: "
                f"expected={expected_pin.to_dict()}, observed={actual_pin.to_dict()}"
            )

    if root_errors:
        failed_inv = _ObservedRootInventory(
            name=root_name,
            path=root_path,
            resolved_path=root_dir_obs.resolved_path,
            file_ids=declared_file_ids,
            directory_identity=root_dir_obs,
            ancestor_identities=tuple(ancestor_list),
            subdirectory_identities=subdir_identities,
            member_pins=member_pins,
            excluded_root_git_present=excluded_git_present,
            member_observations=member_observations,
            scan_complete=True,
            verified=False,
            errors=tuple(root_errors),
        )
        raise _ControlledRootObservationError(
            root_errors[0],
            root_inventory=failed_inv,
            errors=tuple(root_errors),
        )

    return _ObservedRootInventory(
        name=root_name,
        path=root_path,
        resolved_path=root_dir_obs.resolved_path,
        file_ids=declared_file_ids,
        directory_identity=root_dir_obs,
        ancestor_identities=tuple(ancestor_list),
        subdirectory_identities=subdir_identities,
        member_pins=member_pins,
        excluded_root_git_present=excluded_git_present,
        member_observations=member_observations,
        scan_complete=True,
        verified=True,
        errors=(),
    )


def _validate_and_observe_outer_profile(
    profile: RefmacDiagnosticProfile,
    *,
    evidence_root: str | os.PathLike[str] | None = None,
    chunk_size: int = STREAM_CHUNK_BYTES,
) -> _CheckedOuterProfileState:
    """Validate the closed outer manifest and observe all controlled roots, files, ancestors, and symlinks.

    Retains obtainable partial observations on failure via :class:`_ProfileObservationError`
    (a :class:`ValueError` subclass).
    """
    if type(profile) is not RefmacDiagnosticProfile:
        raise ValueError(
            f"profile must be a RefmacDiagnosticProfile, got {type(profile).__name__}"
        )
    if type(chunk_size) is not int or chunk_size <= 0:
        raise ValueError(f"chunk_size must be a positive int, got {chunk_size!r}")

    observed_roots: dict[str, _ObservedRootInventory] = {}
    observed_files: dict[str, _ObservedRegularFilePin] = {}
    verified_files: dict[str, _ObservedRegularFilePin] = {}
    unverified_files: dict[str, _ObservedRegularFilePin] = {}
    observed_ancestors: dict[str, _ObservedDirectoryIdentity] = {}
    observed_symlinks: dict[str, _ObservedSymlinkIdentity] = {}
    errors: list[str] = []
    manifest_observation: _ObservedRegularFilePin | None = None
    outer_manifest: _CheckedOuterManifest | None = None
    raw_evidence_root: str | None = None
    ev_ancestors: tuple[_ObservedDirectoryIdentity, ...] = ()

    def _make_partial(errs: list[str]) -> _PartialProfileObservation:
        return _PartialProfileObservation(
            profile=profile,
            evidence_root=raw_evidence_root,
            evidence_root_ancestor_identities=ev_ancestors,
            manifest_observation=manifest_observation,
            outer_manifest=outer_manifest,
            observed_roots=observed_roots,
            observed_files=observed_files,
            observed_ancestors=observed_ancestors,
            observed_symlinks=observed_symlinks,
            errors=tuple(errs),
            verified_files=verified_files,
            unverified_files=unverified_files,
        )

    if evidence_root is not None:
        try:
            raw_evidence_root, ev_ancestors = _validate_and_observe_evidence_root(
                evidence_root
            )
            for anc_obs in ev_ancestors:
                _record_directory_identity(observed_ancestors, anc_obs)
        except ValueError as exc:
            err_msg = str(exc)
            errors.append(err_msg)
            raise _ProfileObservationError(
                err_msg, partial_observation=_make_partial(errors)
            ) from exc

    try:
        manifest_doc = _read_pinned_json(profile.manifest, chunk_size=chunk_size)
        manifest_observation = manifest_doc.observation
        _observe_file_ancestors_and_symlinks(
            manifest_observation,
            ancestors_out=observed_ancestors,
            symlinks_out=observed_symlinks,
        )
    except _ObservedFilePinError as exc:
        manifest_observation = exc.observation
        try:
            _observe_file_ancestors_and_symlinks(
                manifest_observation,
                ancestors_out=observed_ancestors,
                symlinks_out=observed_symlinks,
            )
        except ValueError as anc_exc:
            errors.append(str(anc_exc))
        err_msg = str(exc)
        errors.append(err_msg)
        raise _ProfileObservationError(
            err_msg, partial_observation=_make_partial(errors)
        ) from exc
    except ValueError as exc:
        err_msg = str(exc)
        errors.append(err_msg)
        raise _ProfileObservationError(
            err_msg, partial_observation=_make_partial(errors)
        ) from exc

    if raw_evidence_root is not None:
        if _paths_overlap(manifest_observation.path, raw_evidence_root) or _paths_overlap(
            manifest_observation.resolved_path, raw_evidence_root
        ):
            err_msg = (
                f"Profile manifest {manifest_observation.path!r} overlaps evidence_root "
                f"{raw_evidence_root!r}"
            )
            errors.append(err_msg)
            raise _ProfileObservationError(
                err_msg, partial_observation=_make_partial(errors)
            )

    try:
        outer_manifest = _validate_outer_manifest_shape(
            manifest_doc.payload,
            expected_profile_id=profile.profile_id,
            expected_executable_pin=profile.executable,
        )
    except ValueError as exc:
        err_msg = str(exc)
        errors.append(err_msg)
        raise _ProfileObservationError(
            err_msg, partial_observation=_make_partial(errors)
        ) from exc

    # Check root/evidence_root and manifest-in-controlled-roots disjointness
    for root_name in EXPECTED_ROOT_NAMES:
        root_path_str = outer_manifest.roots[root_name]["path"]
        if _paths_overlap(manifest_observation.path, root_path_str) or _paths_overlap(
            manifest_observation.resolved_path, root_path_str
        ):
            errors.append(
                f"Profile manifest {manifest_observation.path!r} must be outside controlled root "
                f"{root_name!r} ({root_path_str!r})"
            )
        if raw_evidence_root is not None and _paths_overlap(
            root_path_str, raw_evidence_root
        ):
            errors.append(
                f"Controlled root {root_name!r} ({root_path_str!r}) overlaps evidence_root "
                f"{raw_evidence_root!r}"
            )

    def _record_root_inventory(
        r_name: str, r_inv: _ObservedRootInventory
    ) -> None:
        observed_roots[r_name] = r_inv
        try:
            _record_directory_identity(
                observed_ancestors, r_inv.directory_identity
            )
            for anc_obs in r_inv.ancestor_identities:
                _record_directory_identity(observed_ancestors, anc_obs)
            for sub_obs in r_inv.subdirectory_identities.values():
                _record_directory_identity(observed_ancestors, sub_obs)
        except ValueError as anc_exc:
            errors.append(str(anc_exc))

    # Observe all 3 controlled roots (retaining complete or incomplete root inventories across errors)
    for root_name in EXPECTED_ROOT_NAMES:
        root_info = outer_manifest.roots[root_name]
        try:
            root_inv = _observe_controlled_root(
                root_name,
                root_info["path"],
                root_info["file_ids"],
                declared_files=outer_manifest.files,
                exclude_root_git=(root_name == "vendor"),
                chunk_size=chunk_size,
            )
            _record_root_inventory(root_name, root_inv)
        except _ControlledRootObservationError as exc:
            if exc.root_inventory is not None:
                _record_root_inventory(root_name, exc.root_inventory)
            errors.extend(exc.errors)
        except ValueError as exc:
            errors.append(str(exc))

    # Check distinct device/inode across observed roots
    root_dev_inos: dict[tuple[int, int], str] = {}
    for root_name, root_inv in observed_roots.items():
        dev_ino = (
            root_inv.directory_identity.dev,
            root_inv.directory_identity.ino,
        )
        prev_root = root_dev_inos.get(dev_ino)
        if prev_root is not None:
            errors.append(
                f"Controlled roots {prev_root!r} and {root_name!r} share directory inode {dev_ino}"
            )
        else:
            root_dev_inos[dev_ino] = root_name

    # Observe every declared file row (retaining all obtainable observations before comparisons)
    resolved_identities: dict[str, tuple[int, int, int, int, int, str, int]] = {}
    for file_id in sorted(outer_manifest.files.keys()):
        declared_row = outer_manifest.files[file_id]
        expected_pin = FilePin(
            path=declared_row["path"],
            sha256=declared_row["sha256"],
            size_bytes=declared_row["size_bytes"],
        )
        obtained_file_obs: _ObservedRegularFilePin | None = None
        file_errors: list[str] = []
        try:
            obtained_file_obs = _observe_regular_file_pin(
                declared_row["path"],
                expected_pin=expected_pin,
                chunk_size=chunk_size,
            )
        except _ObservedFilePinError as exc:
            obtained_file_obs = exc.observation
            file_errors.append(str(exc))
        except ValueError as exc:
            file_errors.append(str(exc))

        if obtained_file_obs is not None:
            observed_files[file_id] = obtained_file_obs
            try:
                _observe_file_ancestors_and_symlinks(
                    obtained_file_obs,
                    ancestors_out=observed_ancestors,
                    symlinks_out=observed_symlinks,
                )
            except ValueError as exc:
                file_errors.append(str(exc))

            if obtained_file_obs.resolved_path != declared_row["resolved_path"]:
                file_errors.append(
                    f"files[{file_id!r}] resolved_path mismatch for {declared_row['path']!r}: "
                    f"expected {declared_row['resolved_path']!r}, observed {obtained_file_obs.resolved_path!r}"
                )
            if obtained_file_obs.symlinks != declared_row["symlinks"]:
                file_errors.append(
                    f"files[{file_id!r}] symlink edges mismatch for {declared_row['path']!r}: "
                    f"expected {[e.to_dict() for e in declared_row['symlinks']]}, "
                    f"observed {[e.to_dict() for e in obtained_file_obs.symlinks]}"
                )
            if raw_evidence_root is not None and (
                _paths_overlap(obtained_file_obs.path, raw_evidence_root)
                or _paths_overlap(obtained_file_obs.resolved_path, raw_evidence_root)
            ):
                file_errors.append(
                    f"files[{file_id!r}] ({obtained_file_obs.path!r}) overlaps evidence_root {raw_evidence_root!r}"
                )

            if file_id in outer_manifest.tree_member_ids:
                if (
                    obtained_file_obs.path != obtained_file_obs.resolved_path
                    or obtained_file_obs.symlinks
                ):
                    file_errors.append(
                        f"Controlled root member {file_id!r} ({obtained_file_obs.path!r}) must not use symlinks"
                    )
            else:
                for r_name in EXPECTED_ROOT_NAMES:
                    r_path = outer_manifest.roots[r_name]["path"]
                    r_member_paths = {
                        outer_manifest.files[fid]["path"]
                        for fid in outer_manifest.roots[r_name]["file_ids"]
                    }
                    if Path(obtained_file_obs.path).is_relative_to(Path(r_path)):
                        file_errors.append(
                            f"External file {file_id!r} has lexical path {obtained_file_obs.path!r} "
                            f"inside controlled root {r_name!r} ({r_path!r})"
                        )
                    elif (
                        _paths_overlap(obtained_file_obs.resolved_path, r_path)
                        and obtained_file_obs.resolved_path not in r_member_paths
                    ):
                        file_errors.append(
                            f"External file {file_id!r} ({obtained_file_obs.path!r} -> {obtained_file_obs.resolved_path!r}) "
                            f"resolves to unlisted path inside controlled root {r_name!r} ({r_path!r})"
                        )

            full_target_sig = (
                *obtained_file_obs.identity_tuple,
                obtained_file_obs.sha256,
                obtained_file_obs.size_bytes,
            )
            prev_sig = resolved_identities.get(obtained_file_obs.resolved_path)
            if prev_sig is not None and prev_sig != full_target_sig:
                file_errors.append(
                    f"Inconsistent observed target identity for aliases sharing "
                    f"{obtained_file_obs.resolved_path!r}"
                )
            else:
                resolved_identities[obtained_file_obs.resolved_path] = full_target_sig

            if file_errors:
                unverified_files[file_id] = obtained_file_obs
                errors.extend(file_errors)
            else:
                verified_files[file_id] = obtained_file_obs
        else:
            errors.extend(file_errors)

    # Verify diagnostic_executable on-disk executability and distinctness from installed_reference
    diag_id = outer_manifest.roles["diagnostic_executable"][0]
    ref_id = outer_manifest.roles["installed_reference"][0]
    linked_id = outer_manifest.roles["linked_executable"][0]

    diag_obs = observed_files.get(diag_id)
    if diag_obs is not None:
        diag_role_errors: list[str] = []
        if diag_obs.as_file_pin() != profile.executable:
            diag_role_errors.append(
                f"Observed diagnostic_executable {diag_obs.as_file_pin().to_dict()} "
                f"does not match caller executable pin {profile.executable.to_dict()}"
            )
        if (diag_obs.mode & 0o111) == 0 or not os.access(
            diag_obs.resolved_path, os.X_OK
        ):
            diag_role_errors.append(
                f"diagnostic_executable is not executable on disk: {diag_obs.resolved_path!r} "
                f"(mode={ oct(diag_obs.mode) })"
            )
        ref_obs = observed_files.get(ref_id)
        if ref_obs is not None:
            if (
                diag_obs.sha256 == ref_obs.sha256
                or (diag_obs.dev, diag_obs.ino) == (ref_obs.dev, ref_obs.ino)
                or diag_obs.resolved_path == ref_obs.resolved_path
            ):
                diag_role_errors.append(
                    "diagnostic_executable must be distinct on disk from installed_reference"
                )
        linked_obs = observed_files.get(linked_id)
        if linked_obs is not None:
            if (diag_obs.dev, diag_obs.ino) == (linked_obs.dev, linked_obs.ino):
                diag_role_errors.append(
                    "diagnostic_executable must not share the same inode as linked_executable"
                )
        if diag_role_errors:
            verified_files.pop(diag_id, None)
            unverified_files[diag_id] = diag_obs
            errors.extend(diag_role_errors)

    # Re-verify that the original manifest pin was not replaced or mutated during observation
    try:
        manifest_after = _observe_regular_file_pin(
            profile.manifest.path,
            expected_pin=profile.manifest,
            chunk_size=chunk_size,
        )
        if manifest_after != manifest_observation:
            errors.append(
                f"Profile manifest {profile.manifest.path!r} changed during profile observation"
            )
    except ValueError as exc:
        errors.append(
            f"Profile manifest {profile.manifest.path!r} failed post-observation recheck: {exc}"
        )

    if errors:
        raise _ProfileObservationError(
            errors[0],
            partial_observation=_make_partial(errors),
            errors=tuple(errors),
        )

    return _CheckedOuterProfileState(
        profile=profile,
        selected_executable=profile.executable,
        evidence_root=raw_evidence_root,
        evidence_root_ancestor_identities=ev_ancestors,
        manifest_observation=manifest_observation,
        outer_manifest=outer_manifest,
        observed_roots=observed_roots,
        observed_files=observed_files,
        observed_ancestors=observed_ancestors,
        observed_symlinks=observed_symlinks,
    )


def _reobserve_outer_profile_state(
    state: _CheckedOuterProfileState,
    *,
    chunk_size: int = STREAM_CHUNK_BYTES,
) -> _OuterProfileRecheckResult:
    """Re-observe manifest, controlled roots, files, ancestors, and symlinks against ``state``.

    Continues after individual errors so all obtainable post-run observations are
    retained against the original baseline authority (a replaced manifest on disk
    never redefines expected file/root pins).
    """
    if type(state) is not _CheckedOuterProfileState:
        raise ValueError(
            f"state must be a _CheckedOuterProfileState, got {type(state).__name__}"
        )
    if type(chunk_size) is not int or chunk_size <= 0:
        raise ValueError(f"chunk_size must be a positive int, got {chunk_size!r}")

    errors: list[str] = []
    manifest_after: _ObservedRegularFilePin | None = None
    roots_after: dict[str, _ObservedRootInventory] = {}
    files_after: dict[str, _ObservedRegularFilePin] = {}
    verified_files_after: dict[str, _ObservedRegularFilePin] = {}
    unverified_files_after: dict[str, _ObservedRegularFilePin] = {}
    ancestors_after: dict[str, _ObservedDirectoryIdentity] = {}
    symlinks_after: dict[str, _ObservedSymlinkIdentity] = {}

    # 1. Re-observe original manifest pin against state.manifest_observation
    try:
        manifest_after = _observe_regular_file_pin(
            state.profile.manifest.path,
            expected_pin=state.profile.manifest,
            chunk_size=chunk_size,
        )
        if manifest_after != state.manifest_observation:
            errors.append(
                f"Manifest observation changed at {state.profile.manifest.path!r}: "
                f"expected={state.manifest_observation}, observed={manifest_after}"
            )
    except _ObservedFilePinError as exc:
        manifest_after = exc.observation
        errors.append(f"Manifest recheck failed: {exc}")
    except ValueError as exc:
        errors.append(f"Manifest recheck failed: {exc}")

    # 2. Re-observe controlled roots against state.observed_roots
    for root_name in EXPECTED_ROOT_NAMES:
        expected_root = state.observed_roots[root_name]
        try:
            actual_root = _observe_controlled_root(
                root_name,
                expected_root.path,
                expected_root.file_ids,
                declared_files=state.outer_manifest.files,
                exclude_root_git=(root_name == "vendor"),
                chunk_size=chunk_size,
            )
            if actual_root != expected_root:
                mut_err = (
                    f"Controlled root {root_name!r} mutated since baseline at {expected_root.path!r}"
                )
                actual_root = _ObservedRootInventory(
                    name=actual_root.name,
                    path=actual_root.path,
                    resolved_path=actual_root.resolved_path,
                    file_ids=actual_root.file_ids,
                    directory_identity=actual_root.directory_identity,
                    ancestor_identities=actual_root.ancestor_identities,
                    subdirectory_identities=actual_root.subdirectory_identities,
                    member_pins=actual_root.member_pins,
                    excluded_root_git_present=actual_root.excluded_root_git_present,
                    member_observations=actual_root.member_observations,
                    scan_complete=actual_root.scan_complete,
                    verified=False,
                    errors=(mut_err,),
                )
                errors.append(mut_err)
            roots_after[root_name] = actual_root
        except _ControlledRootObservationError as exc:
            if exc.root_inventory is not None:
                roots_after[root_name] = exc.root_inventory
            for r_err in exc.errors:
                errors.append(
                    f"Controlled root {root_name!r} recheck failed: {r_err}"
                )
        except ValueError as exc:
            errors.append(f"Controlled root {root_name!r} recheck failed: {exc}")

    # 3. Re-observe all files against state.observed_files (original baseline authority)
    diag_id = state.outer_manifest.roles["diagnostic_executable"][0]
    for file_id, expected_file_obs in sorted(state.observed_files.items()):
        actual_file_obs: _ObservedRegularFilePin | None = None
        file_recheck_errors: list[str] = []
        try:
            actual_file_obs = _observe_regular_file_pin(
                expected_file_obs.path,
                expected_pin=expected_file_obs.as_file_pin(),
                chunk_size=chunk_size,
            )
        except _ObservedFilePinError as exc:
            actual_file_obs = exc.observation
            file_recheck_errors.append(
                f"File {file_id!r} ({expected_file_obs.path!r}) recheck failed: {exc}"
            )
        except ValueError as exc:
            file_recheck_errors.append(
                f"File {file_id!r} ({expected_file_obs.path!r}) recheck failed: {exc}"
            )

        if actual_file_obs is not None:
            files_after[file_id] = actual_file_obs
            if actual_file_obs != expected_file_obs:
                file_recheck_errors.append(
                    f"File {file_id!r} ({expected_file_obs.path!r}) identity or symlink edges changed since baseline"
                )
            if file_id == diag_id and (
                (actual_file_obs.mode & 0o111) == 0
                or not os.access(actual_file_obs.resolved_path, os.X_OK)
            ):
                file_recheck_errors.append(
                    f"diagnostic_executable {actual_file_obs.resolved_path!r} is no longer executable"
                )
            if file_recheck_errors:
                unverified_files_after[file_id] = actual_file_obs
                errors.extend(file_recheck_errors)
            else:
                verified_files_after[file_id] = actual_file_obs
        else:
            errors.extend(file_recheck_errors)

    # 4. Re-observe all recorded ancestor directories against state.observed_ancestors
    for anc_path, expected_anc in sorted(state.observed_ancestors.items()):
        try:
            actual_anc = _observe_directory_identity(
                anc_path, require_no_symlink_ancestors=False
            )
            ancestors_after[anc_path] = actual_anc
            if actual_anc != expected_anc:
                errors.append(
                    f"Ancestor directory {anc_path!r} identity changed since baseline"
                )
        except ValueError as exc:
            errors.append(f"Ancestor directory {anc_path!r} recheck failed: {exc}")

    # 5. Re-observe all recorded symlink edges against state.observed_symlinks
    for sym_path, expected_sym in sorted(state.observed_symlinks.items()):
        try:
            actual_sym = _observe_symlink_identity(
                _SymlinkEdge(path=sym_path, target=expected_sym.target)
            )
            symlinks_after[sym_path] = actual_sym
            if actual_sym != expected_sym:
                errors.append(
                    f"Symlink {sym_path!r} identity changed since baseline"
                )
        except ValueError as exc:
            errors.append(f"Symlink {sym_path!r} recheck failed: {exc}")

    return _OuterProfileRecheckResult(
        verified=(len(errors) == 0),
        manifest_observation=manifest_after,
        observed_roots=roots_after,
        observed_files=files_after,
        observed_ancestors=ancestors_after,
        observed_symlinks=symlinks_after,
        errors=tuple(errors),
        verified_files=verified_files_after,
        unverified_files=unverified_files_after,
    )
