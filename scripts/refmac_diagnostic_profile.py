#!/usr/bin/env python3
"""Primitive types, file/environment guards, outer profile validation, and inner receipt admission.

Bounded slices (Tasks 653, 657, 663, 658, 668, 673, 677, 681, 685, and 661):
- Defines the frozen public dataclasses :class:`FilePin`,
  :class:`RefmacDiagnosticProfile`, :class:`FileObservation`,
  :class:`RootObservation`, and :class:`ValidatedProfile`, and the public
  validation failure exception :class:`ProfileValidationError`.
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
- Provides scoped inner source/build/runtime receipt joins and public
  :func:`validate_profile` admission returning a deeply immutable
  :class:`ValidatedProfile` with detached :meth:`ValidatedProfile.to_provenance`
  snapshots and partial-observation failure retention via
  :class:`ProfileValidationError`.

Scope note:
- Public ``recheck_profile`` and collector wiring remain deliberately absent in
  this slice and will be added in Task 662 / Task 639; no collector imports this
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

    def __getitem__(self, key: str) -> str:
        if key == "path":
            return self.path
        if key == "target":
            return self.target
        raise KeyError(key)

    def keys(self) -> tuple[str, str]:
        return ("path", "target")

    def __contains__(self, item: object) -> bool:
        return item in ("path", "target")

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
        if (self.dev, self.ino, self.mode) == (0, 0, 0) or self.dev <= 0 or self.ino <= 0:
            raise ValueError(
                "_ObservedDirectoryIdentity cannot use fabricated zero or non-positive dev/ino identity"
            )

    @property
    def identity_tuple(self) -> tuple[int, int, int, int, int]:
        return (self.dev, self.ino, self.mode, self.uid, self.gid)

    def __getitem__(self, key: str) -> Any:
        if key in ("path", "resolved_path", "dev", "ino", "mode", "uid", "gid"):
            return getattr(self, key)
        raise KeyError(key)

    def keys(self) -> tuple[str, ...]:
        return ("path", "resolved_path", "dev", "ino", "mode", "uid", "gid")

    def __contains__(self, item: object) -> bool:
        return item in ("path", "resolved_path", "dev", "ino", "mode", "uid", "gid")

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
        if (self.dev, self.ino, self.mode) == (0, 0, 0) or self.dev <= 0 or self.ino <= 0:
            raise ValueError(
                "_ObservedSymlinkIdentity cannot use fabricated zero or non-positive dev/ino identity"
            )

    @property
    def identity_tuple(self) -> tuple[int, int, int, int, int]:
        return (self.dev, self.ino, self.mode, self.uid, self.gid)

    def __getitem__(self, key: str) -> Any:
        if key in ("path", "target", "dev", "ino", "mode", "uid", "gid"):
            return getattr(self, key)
        raise KeyError(key)

    def keys(self) -> tuple[str, ...]:
        return ("path", "target", "dev", "ino", "mode", "uid", "gid")

    def __contains__(self, item: object) -> bool:
        return item in ("path", "target", "dev", "ino", "mode", "uid", "gid")

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
    traversed_directory_identities: tuple[_ObservedDirectoryIdentity, ...] = field(
        default=(), repr=False, compare=False
    )

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
        if type(self.traversed_directory_identities) is not tuple or not all(
            type(d) is _ObservedDirectoryIdentity
            for d in self.traversed_directory_identities
        ):
            raise ValueError(
                "_ObservedRegularFilePin.traversed_directory_identities must be a tuple of _ObservedDirectoryIdentity"
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


_MUTABLE_EXCEPTION_ATTRS: frozenset[str] = frozenset(
    {
        "__traceback__",
        "__cause__",
        "__context__",
        "__suppress_context__",
        "__notes__",
        "args",
    }
)


class _ObservedFilePinError(ValueError):
    """ValueError subclass carrying an already-obtained :class:`_ObservedRegularFilePin`."""

    def __init__(
        self,
        message: str,
        *,
        observation: _ObservedRegularFilePin,
        stage: str = "file_pin",
    ) -> None:
        super().__init__(message)
        object.__setattr__(self, "observation", observation)
        object.__setattr__(self, "stage", stage)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in _MUTABLE_EXCEPTION_ATTRS:
            super().__setattr__(name, value)
            return
        raise AttributeError(
            f"_ObservedFilePinError attribute {name!r} is read-only"
        )

    def __delattr__(self, name: str) -> None:
        if name in _MUTABLE_EXCEPTION_ATTRS:
            super().__delattr__(name)
            return
        raise AttributeError(
            f"_ObservedFilePinError attribute {name!r} is read-only"
        )


@dataclass(frozen=True)
class PartialFileReadObservation:
    """Immutable partial file-read observation retained when a regular-file read fails after lookup/fstat."""

    path: str
    resolved_path: str | None
    sha256: None = None
    size_bytes: None = None
    stat_size_bytes: int | None = None
    streamed_size_bytes: int = 0
    read_complete: bool = False
    dev: int | None = None
    ino: int | None = None
    mode: int | None = None
    uid: int | None = None
    gid: int | None = None
    symlinks: tuple[_SymlinkEdge, ...] = ()
    symlink_identities: tuple[_ObservedSymlinkIdentity, ...] = ()
    ancestors: tuple[_ObservedDirectoryIdentity, ...] = ()
    dependencies_complete: bool = False
    verified: bool = False
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_lexical_abs_path(
            self.path, field_name="PartialFileReadObservation.path"
        )
        if self.resolved_path is not None:
            _validate_lexical_abs_path(
                self.resolved_path,
                field_name="PartialFileReadObservation.resolved_path",
            )
            if ".." in Path(self.resolved_path).parts:
                raise ValueError(
                    f"PartialFileReadObservation.resolved_path must not contain '..': {self.resolved_path!r}"
                )
        if self.sha256 is not None:
            raise ValueError(
                "PartialFileReadObservation.sha256 must be None when full stream was not established"
            )
        if self.size_bytes is not None:
            raise ValueError(
                "PartialFileReadObservation.size_bytes must be None when full stream was not established"
            )
        if self.stat_size_bytes is not None:
            _validate_nonnegative_int(
                self.stat_size_bytes,
                field_name="PartialFileReadObservation.stat_size_bytes",
            )
        _validate_nonnegative_int(
            self.streamed_size_bytes,
            field_name="PartialFileReadObservation.streamed_size_bytes",
        )
        if self.read_complete is not False:
            raise ValueError(
                "PartialFileReadObservation.read_complete must be False"
            )

        id_fields = (self.dev, self.ino, self.mode, self.uid, self.gid)
        if any(v is not None for v in id_fields):
            if not all(type(v) is int for v in id_fields):
                raise ValueError(
                    "PartialFileReadObservation.(dev, ino, mode, uid, gid) must be all non-boolean ints when measured"
                )
            assert (
                self.dev is not None
                and self.ino is not None
                and self.mode is not None
                and self.uid is not None
                and self.gid is not None
            )
            if (
                (self.dev, self.ino, self.mode) == (0, 0, 0)
                or self.dev <= 0
                or self.ino <= 0
            ):
                raise ValueError(
                    "PartialFileReadObservation cannot use fabricated zero or non-positive dev/ino identity"
                )
            if self.mode < 0 or self.uid < 0 or self.gid < 0:
                raise ValueError(
                    "PartialFileReadObservation mode/uid/gid must be non-negative"
                )
            if self.stat_size_bytes is None:
                raise ValueError(
                    "PartialFileReadObservation.stat_size_bytes must be present when fstat identity is measured"
                )

        if not isinstance(self.symlinks, tuple) or not all(
            type(e) is _SymlinkEdge for e in self.symlinks
        ):
            raise ValueError(
                "PartialFileReadObservation.symlinks must be a tuple of _SymlinkEdge"
            )
        edge_paths = [e.path for e in self.symlinks]
        if edge_paths != sorted(set(edge_paths)):
            raise ValueError(
                "PartialFileReadObservation.symlinks must be strictly sorted by unique edge.path"
            )
        if not isinstance(self.symlink_identities, tuple) or not all(
            type(s) is _ObservedSymlinkIdentity for s in self.symlink_identities
        ):
            raise ValueError(
                "PartialFileReadObservation.symlink_identities must be a tuple of _ObservedSymlinkIdentity"
            )
        expected_pairs = [(e.path, e.target) for e in self.symlinks]
        observed_pairs = [(s.path, s.target) for s in self.symlink_identities]
        it = iter(expected_pairs)
        if not all(pair in it for pair in observed_pairs):
            raise ValueError(
                "PartialFileReadObservation.symlink_identities must be an ordered subset of symlinks"
            )
        if not isinstance(self.ancestors, tuple) or not all(
            type(anc) is _ObservedDirectoryIdentity for anc in self.ancestors
        ):
            raise ValueError(
                "PartialFileReadObservation.ancestors must be a tuple of _ObservedDirectoryIdentity"
            )
        anc_paths = [anc.path for anc in self.ancestors]
        if len(anc_paths) != len(set(anc_paths)):
            raise ValueError(
                "PartialFileReadObservation.ancestors must have unique paths"
            )
        if type(self.dependencies_complete) is not bool:
            raise ValueError(
                "PartialFileReadObservation.dependencies_complete must be a bool"
            )
        if self.dependencies_complete:
            if len(self.ancestors) == 0 or observed_pairs != expected_pairs:
                raise ValueError(
                    "PartialFileReadObservation.dependencies_complete=True requires non-empty ancestors and complete symlink_identities"
                )
        if self.verified is not False:
            raise ValueError("PartialFileReadObservation.verified must be False")
        if (
            not isinstance(self.errors, tuple)
            or len(self.errors) == 0
            or not all(type(e) is str and e for e in self.errors)
        ):
            raise ValueError(
                "PartialFileReadObservation.errors must be a non-empty tuple of non-empty str"
            )

    @property
    def complete(self) -> bool:
        return False

    @property
    def unavailable_symlinks(self) -> tuple[_SymlinkEdge, ...]:
        observed_paths = {s.path for s in self.symlink_identities}
        return tuple(e for e in self.symlinks if e.path not in observed_paths)

    @property
    def identity_tuple(self) -> tuple[int, int, int, int, int] | None:
        if (
            self.dev is not None
            and self.ino is not None
            and self.mode is not None
            and self.uid is not None
            and self.gid is not None
        ):
            return (self.dev, self.ino, self.mode, self.uid, self.gid)
        return None

    def as_file_pin(self) -> FilePin:
        raise ValueError(
            "PartialFileReadObservation cannot be converted to a FilePin because full stream read did not complete"
        )

    def __getitem__(self, key: str) -> Any:
        d = self.to_dict()
        if key in d:
            return d[key]
        raise KeyError(key)

    def keys(self):
        return self.to_dict().keys()

    def __contains__(self, item: object) -> bool:
        return item in self.to_dict()

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "resolved_path": self.resolved_path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "stat_size_bytes": self.stat_size_bytes,
            "streamed_size_bytes": self.streamed_size_bytes,
            "read_complete": self.read_complete,
            "dev": self.dev,
            "ino": self.ino,
            "mode": self.mode,
            "uid": self.uid,
            "gid": self.gid,
            "symlinks": [edge.to_dict() for edge in self.symlinks],
            "symlink_identities": [
                sym.to_dict() for sym in self.symlink_identities
            ],
            "ancestors": [anc.to_dict() for anc in self.ancestors],
            "dependencies_complete": self.dependencies_complete,
            "verified": self.verified,
            "errors": list(self.errors),
        }

    def to_provenance(self) -> dict[str, Any]:
        return self.to_dict()


class _PartialFileReadError(ValueError):
    """ValueError subclass carrying an immutable :class:`PartialFileReadObservation`."""

    def __init__(
        self,
        message: str,
        *,
        observation: PartialFileReadObservation,
        stage: str = "file_pin",
    ) -> None:
        super().__init__(message)
        if type(observation) is not PartialFileReadObservation:
            raise ValueError(
                "_PartialFileReadError.observation must be a PartialFileReadObservation"
            )
        object.__setattr__(self, "observation", observation)
        object.__setattr__(self, "stage", stage)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in _MUTABLE_EXCEPTION_ATTRS:
            super().__setattr__(name, value)
            return
        raise AttributeError(
            f"_PartialFileReadError attribute {name!r} is read-only"
        )

    def __delattr__(self, name: str) -> None:
        if name in _MUTABLE_EXCEPTION_ATTRS:
            super().__delattr__(name)
            return
        raise AttributeError(
            f"_PartialFileReadError attribute {name!r} is read-only"
        )


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
    directory_identities: tuple[_ObservedDirectoryIdentity, ...] = ()


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

    try:
        root_st = os.lstat("/")
    except OSError as exc:
        raise ValueError(
            f"Cannot inspect path component '/' ({type(exc).__name__}): {exc}"
        ) from exc
    if stat.S_ISLNK(root_st.st_mode) or not stat.S_ISDIR(root_st.st_mode):
        raise ValueError("Root '/' is not a canonical directory")
    root_dir_obs = _ObservedDirectoryIdentity(
        path="/",
        resolved_path="/",
        dev=int(root_st.st_dev),
        ino=int(root_st.st_ino),
        mode=int(stat.S_IMODE(root_st.st_mode)),
        uid=int(root_st.st_uid),
        gid=int(root_st.st_gid),
    )

    dir_paths_seen: dict[str, None] = {"/": None}
    dir_identities_seen: dict[str, _ObservedDirectoryIdentity] = {
        "/": root_dir_obs
    }
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
            cand_dir_obs = _ObservedDirectoryIdentity(
                path=cand_path,
                resolved_path=cand_path,
                dev=int(st.st_dev),
                ino=int(st.st_ino),
                mode=int(stat.S_IMODE(st.st_mode)),
                uid=int(st.st_uid),
                gid=int(st.st_gid),
            )
            prev_dir_obs = dir_identities_seen.get(cand_path)
            if prev_dir_obs is not None and prev_dir_obs != cand_dir_obs:
                raise ValueError(
                    f"Directory identity changed during traversal at {cand_path!r}: "
                    f"before={prev_dir_obs.to_dict()}, after={cand_dir_obs.to_dict()}"
                )
            current_parts.append(comp)
            dir_paths_seen[cand_path] = None
            dir_identities_seen[cand_path] = cand_dir_obs
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

    ordered_dir_identities: dict[str, _ObservedDirectoryIdentity] = {}
    for anc in Path(resolved_path).parents:
        anc_str = str(anc)
        if anc_str in dir_identities_seen:
            ordered_dir_identities[anc_str] = dir_identities_seen[anc_str]
    for d_path in dir_paths_seen:
        if d_path in dir_identities_seen:
            ordered_dir_identities.setdefault(
                d_path, dir_identities_seen[d_path]
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
        directory_identities=tuple(ordered_dir_identities.values()),
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
    traversal_before = _traverse_path_components(raw_lexical)
    symlinks_before = traversal_before.symlink_edges
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

    fstat_before: os.stat_result | None = None
    pre_eof_after_fstat = False

    def _build_partial_read_obs(
        err_msg: str,
        *,
        fstat_st: os.stat_result,
        streamed_bytes: int,
    ) -> PartialFileReadObservation:
        anc_tuple = traversal_before.directory_identities
        deps_complete = len(anc_tuple) > 0 and len(symlinks_before) == 0
        return PartialFileReadObservation(
            path=raw_lexical,
            resolved_path=resolved_before,
            sha256=None,
            size_bytes=None,
            stat_size_bytes=int(fstat_st.st_size),
            streamed_size_bytes=streamed_bytes,
            read_complete=False,
            dev=int(fstat_st.st_dev),
            ino=int(fstat_st.st_ino),
            mode=int(stat.S_IMODE(fstat_st.st_mode)),
            uid=int(fstat_st.st_uid),
            gid=int(fstat_st.st_gid),
            symlinks=symlinks_before,
            symlink_identities=(),
            ancestors=anc_tuple,
            dependencies_complete=deps_complete,
            verified=False,
            errors=(err_msg,),
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
        pre_eof_after_fstat = True
        if max_allowed_bytes is not None and int(fstat_before.st_size) != max_allowed_bytes:
            label = "Pinned JSON size mismatch" if retain_bytes else "Size mismatch"
            suffix = " before parse" if retain_bytes else ""
            err_msg = (
                f"{label} for {raw_lexical!r}{suffix}: "
                f"expected {max_allowed_bytes} bytes, observed {int(fstat_before.st_size)} bytes"
            )
            size_err = ValueError(err_msg)
            raise _PartialFileReadError(
                err_msg,
                observation=_build_partial_read_obs(
                    err_msg,
                    fstat_st=fstat_before,
                    streamed_bytes=0,
                ),
            ) from size_err
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
                    err_msg = (
                        f"{label} for {raw_lexical!r}{suffix}: "
                        f"streamed bytes exceeded expected {max_allowed_bytes} bytes"
                    )
                    overflow_err = ValueError(err_msg)
                    raise _PartialFileReadError(
                        err_msg,
                        observation=_build_partial_read_obs(
                            err_msg,
                            fstat_st=fstat_before,
                            streamed_bytes=total_bytes,
                        ),
                    ) from overflow_err
                hasher.update(chunk)
                if retain_bytes:
                    chunks.append(chunk)
            pre_eof_after_fstat = False
            fstat_after = os.fstat(handle.fileno())
    except _PartialFileReadError:
        raise
    except Exception as exc:
        if not pre_eof_after_fstat and isinstance(exc, ValueError):
            raise
        err_msg = (
            f"Failed reading regular file {raw_lexical!r} ({type(exc).__name__}): {exc}"
        )
        if pre_eof_after_fstat and fstat_before is not None:
            raise _PartialFileReadError(
                err_msg,
                observation=_build_partial_read_obs(
                    err_msg,
                    fstat_st=fstat_before,
                    streamed_bytes=total_bytes,
                ),
            ) from exc
        raise ValueError(err_msg) from exc
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
    traversal_after = _traverse_path_components(raw_lexical)
    symlinks_after = traversal_after.symlink_edges
    resolved_after, target_lstat_after = _resolve_regular_target_strict(raw_lexical)

    if _stat_identity_tuple(lex_lstat_after) != _stat_identity_tuple(lex_lstat_before):
        raise ValueError(
            f"Lexical path identity changed during read for {raw_lexical!r}"
        )
    if symlinks_after != symlinks_before:
        raise ValueError(
            f"Symlink edges changed during read for {raw_lexical!r}"
        )
    if traversal_after.directory_identities != traversal_before.directory_identities:
        raise ValueError(
            f"Traversed directory identities changed during read for {raw_lexical!r}"
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
        traversed_directory_identities=traversal_after.directory_identities,
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
        raise _ObservedFilePinError(
            str(exc), observation=observation, stage="manifest_json"
        ) from exc
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
        causes: tuple[BaseException, ...] = (),
    ) -> None:
        super().__init__(message)
        object.__setattr__(self, "root_inventory", root_inventory)
        object.__setattr__(self, "errors", tuple(errors))
        object.__setattr__(self, "causes", tuple(causes))

    def __setattr__(self, name: str, value: Any) -> None:
        if name in _MUTABLE_EXCEPTION_ATTRS:
            super().__setattr__(name, value)
            return
        raise AttributeError(
            f"_ControlledRootObservationError attribute {name!r} is read-only"
        )

    def __delattr__(self, name: str) -> None:
        if name in _MUTABLE_EXCEPTION_ATTRS:
            super().__delattr__(name)
            return
        raise AttributeError(
            f"_ControlledRootObservationError attribute {name!r} is read-only"
        )


@dataclass(frozen=True)
class _ObservedFileDependencies:
    """Immutable per-file ancestor and symlink dependency snapshot."""

    ancestors: tuple[_ObservedDirectoryIdentity, ...]
    symlink_identities: tuple[_ObservedSymlinkIdentity, ...]
    complete: bool = True
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.ancestors, tuple) or not all(
            type(a) is _ObservedDirectoryIdentity for a in self.ancestors
        ):
            raise ValueError(
                "_ObservedFileDependencies.ancestors must be a tuple of _ObservedDirectoryIdentity"
            )
        if not isinstance(self.symlink_identities, tuple) or not all(
            type(s) is _ObservedSymlinkIdentity for s in self.symlink_identities
        ):
            raise ValueError(
                "_ObservedFileDependencies.symlink_identities must be a tuple of _ObservedSymlinkIdentity"
            )
        if type(self.complete) is not bool:
            raise ValueError("_ObservedFileDependencies.complete must be a bool")
        if not isinstance(self.errors, tuple) or not all(
            type(e) is str for e in self.errors
        ):
            raise ValueError(
                "_ObservedFileDependencies.errors must be a tuple of str"
            )
        if self.complete and (len(self.ancestors) == 0 or len(self.errors) > 0):
            raise ValueError(
                "_ObservedFileDependencies cannot be complete when ancestors is empty or errors are present"
            )


class _FileDependencyObservationError(ValueError):
    """ValueError subclass carrying partial :class:`_ObservedFileDependencies` and underlying causes."""

    def __init__(
        self,
        message: str,
        *,
        dependencies: _ObservedFileDependencies,
        errors: tuple[str, ...],
        causes: tuple[BaseException, ...] = (),
    ) -> None:
        super().__init__(message)
        object.__setattr__(self, "dependencies", dependencies)
        object.__setattr__(self, "errors", tuple(errors))
        object.__setattr__(self, "causes", tuple(causes))

    def __setattr__(self, name: str, value: Any) -> None:
        if name in _MUTABLE_EXCEPTION_ATTRS:
            super().__setattr__(name, value)
            return
        raise AttributeError(
            f"_FileDependencyObservationError attribute {name!r} is read-only"
        )

    def __delattr__(self, name: str) -> None:
        if name in _MUTABLE_EXCEPTION_ATTRS:
            super().__delattr__(name)
            return
        raise AttributeError(
            f"_FileDependencyObservationError attribute {name!r} is read-only"
        )


@dataclass(frozen=True)
class _RecordedObservationError:
    """Structured stage-tagged error record preserving the actual caught exception object."""

    stage: str
    message: str
    exception: BaseException
    error_type: str = ""
    error_errno: int | None = None

    def __post_init__(self) -> None:
        if type(self.stage) is not str or not self.stage:
            raise ValueError(
                "_RecordedObservationError.stage must be a non-empty str"
            )
        if type(self.message) is not str or not self.message:
            raise ValueError(
                "_RecordedObservationError.message must be a non-empty str"
            )
        if not isinstance(self.exception, BaseException):
            raise ValueError(
                "_RecordedObservationError.exception must be a BaseException"
            )
        selected = _select_original_cause_exception(self.exception)
        resolved_type = (
            self.error_type
            if type(self.error_type) is str and self.error_type
            else type(selected).__name__
        )
        resolved_errno = (
            self.error_errno
            if self.error_errno is not None
            else getattr(selected, "errno", None)
        )
        object.__setattr__(self, "error_type", resolved_type)
        object.__setattr__(self, "error_errno", resolved_errno)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "message": self.message,
            "type": self.error_type,
            "errno": self.error_errno,
        }


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
    manifest_dependencies: _ObservedFileDependencies | None = None
    file_dependencies: Mapping[str, _ObservedFileDependencies] = field(
        default_factory=_empty_mapping_proxy
    )
    partial_manifest_observation: PartialFileReadObservation | None = None
    partial_files: Mapping[str, PartialFileReadObservation] = field(
        default_factory=_empty_mapping_proxy
    )
    manifest_file_observation: FileObservation | PartialFileReadObservation | None = None
    file_observations: Mapping[str, FileObservation | PartialFileReadObservation] = field(
        default_factory=_empty_mapping_proxy
    )
    error_records: tuple[_RecordedObservationError, ...] = ()

    def __post_init__(self) -> None:
        if type(self.profile) is not RefmacDiagnosticProfile:
            raise ValueError(
                "_PartialProfileObservation.profile must be RefmacDiagnosticProfile"
            )
        if (
            self.partial_manifest_observation is not None
            and type(self.partial_manifest_observation)
            is not PartialFileReadObservation
        ):
            raise ValueError(
                "_PartialProfileObservation.partial_manifest_observation must be PartialFileReadObservation or None"
            )
        if (
            self.manifest_observation is not None
            and self.partial_manifest_observation is not None
        ):
            raise ValueError(
                "_PartialProfileObservation cannot have both complete and partial manifest observations"
            )
        sorted_roots = dict(sorted(self.observed_roots.items()))
        sorted_files = dict(sorted(self.observed_files.items()))
        sorted_partial_files = dict(sorted(self.partial_files.items()))
        for fid, pobs in sorted_partial_files.items():
            if type(pobs) is not PartialFileReadObservation:
                raise ValueError(
                    f"_PartialProfileObservation.partial_files[{fid!r}] must be PartialFileReadObservation"
                )
        if not set(sorted_files.keys()).isdisjoint(
            set(sorted_partial_files.keys())
        ):
            raise ValueError(
                "_PartialProfileObservation.observed_files and partial_files must be disjoint"
            )
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
            "partial_files",
            MappingProxyType(sorted_partial_files),
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
        object.__setattr__(
            self,
            "file_dependencies",
            MappingProxyType(dict(sorted(self.file_dependencies.items()))),
        )
        object.__setattr__(
            self,
            "file_observations",
            MappingProxyType(dict(sorted(self.file_observations.items()))),
        )
        object.__setattr__(
            self,
            "error_records",
            tuple(self.error_records),
        )


class _ProfileObservationError(ValueError):
    """ValueError subclass carrying an immutable :class:`_PartialProfileObservation`."""

    def __init__(
        self,
        message: str,
        *,
        partial_observation: _PartialProfileObservation,
        errors: tuple[str, ...] | None = None,
        failed_check: str | None = None,
        error_records: tuple[_RecordedObservationError, ...] | None = None,
        primary_exception: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        if type(partial_observation) is not _PartialProfileObservation:
            raise ValueError(
                "partial_observation must be a _PartialProfileObservation instance"
            )
        object.__setattr__(self, "partial_observation", partial_observation)
        object.__setattr__(
            self,
            "errors",
            tuple(errors) if errors is not None else partial_observation.errors,
        )
        records = (
            tuple(error_records)
            if error_records is not None
            else partial_observation.error_records
        )
        object.__setattr__(self, "error_records", records)
        if failed_check is not None:
            resolved_check = failed_check
        elif records:
            resolved_check = records[0].stage
        else:
            resolved_check = "outer_profile_files_and_roots"
        object.__setattr__(self, "failed_check", resolved_check)
        object.__setattr__(
            self,
            "primary_exception",
            primary_exception
            if primary_exception is not None
            else (records[0].exception if records else None),
        )

    def __setattr__(self, name: str, value: Any) -> None:
        if name in _MUTABLE_EXCEPTION_ATTRS:
            super().__setattr__(name, value)
            return
        raise AttributeError(
            f"_ProfileObservationError attribute {name!r} is read-only"
        )

    def __delattr__(self, name: str) -> None:
        if name in _MUTABLE_EXCEPTION_ATTRS:
            super().__delattr__(name)
            return
        raise AttributeError(
            f"_ProfileObservationError attribute {name!r} is read-only"
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
    manifest_dependencies: _ObservedFileDependencies | None = None
    file_dependencies: Mapping[str, _ObservedFileDependencies] = field(
        default_factory=_empty_mapping_proxy
    )
    manifest_file_observation: FileObservation | None = None
    file_observations: Mapping[str, FileObservation] = field(
        default_factory=_empty_mapping_proxy
    )

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
        if self.manifest_dependencies is not None and (
            not self.manifest_dependencies.complete
            or self.manifest_dependencies.errors
        ):
            raise ValueError(
                "_CheckedOuterProfileState cannot accept incomplete manifest_dependencies"
            )
        for fid, fdeps in self.file_dependencies.items():
            if not fdeps.complete or fdeps.errors:
                raise ValueError(
                    f"_CheckedOuterProfileState cannot accept incomplete file_dependencies[{fid!r}]"
                )
        for fid, fpin_obs in self.observed_files.items():
            if type(fpin_obs) is not _ObservedRegularFilePin:
                raise ValueError(
                    f"_CheckedOuterProfileState.observed_files[{fid!r}] must be _ObservedRegularFilePin"
                )
        if self.manifest_file_observation is not None:
            if type(self.manifest_file_observation) is not FileObservation:
                raise ValueError(
                    "_CheckedOuterProfileState.manifest_file_observation must be FileObservation"
                )
            if (
                not self.manifest_file_observation.dependencies_complete
                or not self.manifest_file_observation.verified
                or self.manifest_file_observation.errors
            ):
                raise ValueError(
                    "_CheckedOuterProfileState cannot accept unverified manifest_file_observation"
                )
        for fid, fobs in self.file_observations.items():
            if type(fobs) is not FileObservation:
                raise ValueError(
                    f"_CheckedOuterProfileState.file_observations[{fid!r}] must be FileObservation"
                )
            if (
                not fobs.dependencies_complete
                or not fobs.verified
                or fobs.errors
            ):
                raise ValueError(
                    f"_CheckedOuterProfileState cannot accept unverified file_observations[{fid!r}]"
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
        object.__setattr__(
            self,
            "file_dependencies",
            MappingProxyType(dict(sorted(self.file_dependencies.items()))),
        )
        object.__setattr__(
            self,
            "file_observations",
            MappingProxyType(dict(sorted(self.file_observations.items()))),
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


def _collect_file_dependencies(
    file_obs: _ObservedRegularFilePin,
    *,
    ancestors_out: dict[str, _ObservedDirectoryIdentity],
    symlinks_out: dict[str, _ObservedSymlinkIdentity],
) -> _ObservedFileDependencies:
    """Collect per-file ancestors and symlink identities, retaining partial observations on failure."""
    per_file_ancestors: dict[str, _ObservedDirectoryIdentity] = {}
    dep_errors: list[str] = []
    dep_causes: list[BaseException] = []

    if file_obs.traversed_directory_identities:
        for dir_obs in file_obs.traversed_directory_identities:
            if dir_obs.path != dir_obs.resolved_path:
                err_msg = (
                    f"Traversed directory dependency {dir_obs.path!r} is not canonical "
                    f"({dir_obs.resolved_path!r})"
                )
                dep_errors.append(err_msg)
                dep_causes.append(ValueError(err_msg))
                continue
            try:
                _record_directory_identity(ancestors_out, dir_obs)
            except ValueError as exc:
                dep_errors.append(str(exc))
                dep_causes.append(exc)
            per_file_ancestors[dir_obs.path] = dir_obs
    else:
        for anc in Path(file_obs.resolved_path).parents:
            anc_str = str(anc)
            try:
                anc_obs = _observe_directory_identity(
                    anc_str, require_no_symlink_ancestors=False
                )
                if anc_obs.path != anc_obs.resolved_path:
                    raise ValueError(
                        f"Resolved ancestor {anc} is not canonical ({anc_obs.resolved_path!r})"
                    )
                per_file_ancestors[anc_obs.path] = anc_obs
                _record_directory_identity(ancestors_out, anc_obs)
            except ValueError as exc:
                dep_errors.append(str(exc))
                dep_causes.append(exc)
                if anc_str not in per_file_ancestors and anc_str in ancestors_out:
                    per_file_ancestors[anc_str] = ancestors_out[anc_str]

        try:
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
            for dir_obs in traversal.directory_identities:
                if dir_obs.path != dir_obs.resolved_path:
                    raise ValueError(
                        f"Traversed directory dependency {dir_obs.path!r} is not canonical "
                        f"({dir_obs.resolved_path!r})"
                    )
                per_file_ancestors[dir_obs.path] = dir_obs
                try:
                    _record_directory_identity(ancestors_out, dir_obs)
                except ValueError as exc:
                    dep_errors.append(str(exc))
                    dep_causes.append(exc)
        except ValueError as exc:
            dep_errors.append(str(exc))
            dep_causes.append(exc)

    per_file_symlinks: list[_ObservedSymlinkIdentity] = []
    for edge in file_obs.symlinks:
        try:
            sym_obs = _observe_symlink_identity(edge)
            per_file_symlinks.append(sym_obs)
            _record_symlink_identity(symlinks_out, sym_obs)
        except ValueError as exc:
            dep_errors.append(str(exc))
            dep_causes.append(exc)

    complete = (
        len(dep_errors) == 0
        and len(per_file_ancestors) > 0
        and len(per_file_symlinks) == len(file_obs.symlinks)
    )
    deps = _ObservedFileDependencies(
        ancestors=tuple(per_file_ancestors.values()),
        symlink_identities=tuple(per_file_symlinks),
        complete=complete,
        errors=tuple(dep_errors),
    )
    if not complete:
        err_msg = (
            dep_errors[0]
            if dep_errors
            else f"Incomplete dependency observation for {file_obs.path!r}"
        )
        if dep_causes:
            raise _FileDependencyObservationError(
                err_msg,
                dependencies=deps,
                errors=tuple(dep_errors) if dep_errors else (err_msg,),
                causes=tuple(dep_causes),
            ) from dep_causes[0]
        raise _FileDependencyObservationError(
            err_msg,
            dependencies=deps,
            errors=(err_msg,),
            causes=(),
        )
    return deps


def _observe_file_ancestors_and_symlinks(
    file_obs: _ObservedRegularFilePin,
    *,
    ancestors_out: dict[str, _ObservedDirectoryIdentity],
    symlinks_out: dict[str, _ObservedSymlinkIdentity],
) -> tuple[tuple[_ObservedDirectoryIdentity, ...], tuple[_ObservedSymlinkIdentity, ...]]:
    """Observe resolved ancestors, raw/traversed directory dependencies, and literal symlink edges."""
    deps = _collect_file_dependencies(
        file_obs,
        ancestors_out=ancestors_out,
        symlinks_out=symlinks_out,
    )
    return deps.ancestors, deps.symlink_identities


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
            causes=(exc,),
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
            causes=tuple(ValueError(m) for m in root_errors),
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
    manifest_dependencies: _ObservedFileDependencies | None = None
    file_dependencies: dict[str, _ObservedFileDependencies] = {}
    partial_manifest_observation: PartialFileReadObservation | None = None
    partial_files: dict[str, PartialFileReadObservation] = {}
    per_file_error_messages: dict[str, list[str]] = {}
    manifest_error_messages: list[str] = []
    errors: list[str] = []
    error_records: list[_RecordedObservationError] = []
    manifest_observation: _ObservedRegularFilePin | None = None
    outer_manifest: _CheckedOuterManifest | None = None
    raw_evidence_root: str | None = None
    ev_ancestors: tuple[_ObservedDirectoryIdentity, ...] = ()

    def _record_err(
        stage: str,
        exc: BaseException,
        *,
        message: str | None = None,
    ) -> str:
        msg = message if message is not None else str(exc)
        errors.append(msg)
        error_records.append(
            _RecordedObservationError(
                stage=stage,
                message=msg,
                exception=exc,
            )
        )
        return msg

    def _project_manifest_file_observation(
        *, verified_flag: bool
    ) -> FileObservation | PartialFileReadObservation | None:
        if manifest_observation is not None:
            return _build_file_observation(
                manifest_observation,
                observed_ancestors=observed_ancestors,
                observed_symlinks=observed_symlinks,
                file_dependencies=manifest_dependencies,
                verified=(verified_flag and len(manifest_error_messages) == 0),
                errors=tuple(manifest_error_messages),
            )
        if partial_manifest_observation is not None:
            return partial_manifest_observation
        return None

    def _project_file_observations() -> dict[str, FileObservation]:
        return {
            fid: _build_file_observation(
                fobs,
                observed_ancestors=observed_ancestors,
                observed_symlinks=observed_symlinks,
                file_dependencies=file_dependencies.get(fid),
                verified=(fid in verified_files),
                errors=tuple(per_file_error_messages.get(fid, ())),
            )
            for fid, fobs in sorted(observed_files.items())
        }

    def _project_failure_file_observations() -> dict[
        str, FileObservation | PartialFileReadObservation
    ]:
        merged: dict[str, FileObservation | PartialFileReadObservation] = dict(
            _project_file_observations()
        )
        for fid, pobs in partial_files.items():
            merged[fid] = pobs
        return dict(sorted(merged.items()))

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
            manifest_dependencies=manifest_dependencies,
            file_dependencies=file_dependencies,
            partial_manifest_observation=partial_manifest_observation,
            partial_files=partial_files,
            manifest_file_observation=_project_manifest_file_observation(
                verified_flag=False
            ),
            file_observations=_project_failure_file_observations(),
            error_records=tuple(error_records),
        )

    def _raise_observation_error() -> None:
        partial = _make_partial(errors)
        primary_rec = error_records[0]
        raise _ProfileObservationError(
            primary_rec.message,
            partial_observation=partial,
            errors=tuple(errors),
            failed_check=primary_rec.stage,
            error_records=tuple(error_records),
            primary_exception=primary_rec.exception,
        ) from primary_rec.exception

    if evidence_root is not None:
        try:
            raw_evidence_root, ev_ancestors = _validate_and_observe_evidence_root(
                evidence_root
            )
            for anc_obs in ev_ancestors:
                _record_directory_identity(observed_ancestors, anc_obs)
        except ValueError as exc:
            _record_err("evidence_root", exc)

    try:
        manifest_doc = _read_pinned_json(profile.manifest, chunk_size=chunk_size)
        manifest_observation = manifest_doc.observation
    except _ObservedFilePinError as exc:
        manifest_observation = exc.observation
        manifest_stage = (
            "manifest_json" if exc.stage == "manifest_json" else "manifest_pin"
        )
        manifest_error_messages.append(str(exc))
        _record_err(manifest_stage, exc)
        try:
            manifest_dependencies = _collect_file_dependencies(
                manifest_observation,
                ancestors_out=observed_ancestors,
                symlinks_out=observed_symlinks,
            )
        except _FileDependencyObservationError as anc_exc:
            manifest_dependencies = anc_exc.dependencies
            for idx, d_err in enumerate(anc_exc.errors):
                c_exc = (
                    anc_exc.causes[idx]
                    if idx < len(anc_exc.causes)
                    else (anc_exc.causes[-1] if anc_exc.causes else anc_exc)
                )
                manifest_error_messages.append(d_err)
                _record_err("manifest_pin", c_exc, message=d_err)
        except ValueError as anc_exc:
            manifest_error_messages.append(str(anc_exc))
            _record_err("manifest_pin", anc_exc)
        _raise_observation_error()
    except _PartialFileReadError as exc:
        partial_manifest_observation = exc.observation
        manifest_error_messages.append(str(exc))
        _record_err("manifest_pin", exc)
        _raise_observation_error()
    except ValueError as exc:
        manifest_error_messages.append(str(exc))
        _record_err("manifest_pin", exc)
        _raise_observation_error()

    try:
        manifest_dependencies = _collect_file_dependencies(
            manifest_observation,
            ancestors_out=observed_ancestors,
            symlinks_out=observed_symlinks,
        )
    except _FileDependencyObservationError as exc:
        manifest_dependencies = exc.dependencies
        for idx, d_err in enumerate(exc.errors):
            c_exc = (
                exc.causes[idx]
                if idx < len(exc.causes)
                else (exc.causes[-1] if exc.causes else exc)
            )
            manifest_error_messages.append(d_err)
            _record_err("manifest_pin", c_exc, message=d_err)
    except ValueError as exc:
        manifest_error_messages.append(str(exc))
        _record_err("manifest_pin", exc)

    if raw_evidence_root is not None:
        if _paths_overlap(manifest_observation.path, raw_evidence_root) or _paths_overlap(
            manifest_observation.resolved_path, raw_evidence_root
        ):
            err_msg = (
                f"Profile manifest {manifest_observation.path!r} overlaps evidence_root "
                f"{raw_evidence_root!r}"
            )
            manifest_error_messages.append(err_msg)
            _record_err("evidence_root", ValueError(err_msg), message=err_msg)

    try:
        outer_manifest = _validate_outer_manifest_shape(
            manifest_doc.payload,
            expected_profile_id=profile.profile_id,
            expected_executable_pin=profile.executable,
        )
    except ValueError as exc:
        _record_err("outer_manifest_shape", exc)
        _raise_observation_error()

    # Check root/evidence_root and manifest-in-controlled-roots disjointness
    for root_name in EXPECTED_ROOT_NAMES:
        root_path_str = outer_manifest.roots[root_name]["path"]
        if _paths_overlap(manifest_observation.path, root_path_str) or _paths_overlap(
            manifest_observation.resolved_path, root_path_str
        ):
            err_msg = (
                f"Profile manifest {manifest_observation.path!r} must be outside controlled root "
                f"{root_name!r} ({root_path_str!r})"
            )
            manifest_error_messages.append(err_msg)
            _record_err(
                "outer_profile_files_and_roots",
                ValueError(err_msg),
                message=err_msg,
            )
        if raw_evidence_root is not None and _paths_overlap(
            root_path_str, raw_evidence_root
        ):
            err_msg = (
                f"Controlled root {root_name!r} ({root_path_str!r}) overlaps evidence_root "
                f"{raw_evidence_root!r}"
            )
            _record_err("evidence_root", ValueError(err_msg), message=err_msg)

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
            _record_err("outer_profile_files_and_roots", anc_exc)

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
            causes = (
                exc.causes
                if exc.causes
                else tuple(ValueError(m) for m in exc.errors)
            )
            for idx, r_err in enumerate(exc.errors):
                c_exc = causes[idx] if idx < len(causes) else causes[-1]
                _record_err(
                    "outer_profile_files_and_roots", c_exc, message=r_err
                )
        except ValueError as exc:
            _record_err("outer_profile_files_and_roots", exc)

    # Check distinct device/inode across observed roots
    root_dev_inos: dict[tuple[int, int], str] = {}
    for root_name, root_inv in observed_roots.items():
        dev_ino = (
            root_inv.directory_identity.dev,
            root_inv.directory_identity.ino,
        )
        prev_root = root_dev_inos.get(dev_ino)
        if prev_root is not None:
            err_msg = (
                f"Controlled roots {prev_root!r} and {root_name!r} share directory inode {dev_ino}"
            )
            _record_err(
                "outer_profile_files_and_roots",
                ValueError(err_msg),
                message=err_msg,
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
        obtained_partial_obs: PartialFileReadObservation | None = None
        file_err_records: list[tuple[str, str, BaseException]] = []
        try:
            obtained_file_obs = _observe_regular_file_pin(
                declared_row["path"],
                expected_pin=expected_pin,
                chunk_size=chunk_size,
            )
        except _ObservedFilePinError as exc:
            obtained_file_obs = exc.observation
            file_err_records.append(
                ("outer_profile_files_and_roots", str(exc), exc)
            )
        except _PartialFileReadError as exc:
            obtained_partial_obs = exc.observation
            file_err_records.append(
                ("outer_profile_files_and_roots", str(exc), exc)
            )
        except ValueError as exc:
            file_err_records.append(
                ("outer_profile_files_and_roots", str(exc), exc)
            )

        if obtained_file_obs is not None:
            observed_files[file_id] = obtained_file_obs
            try:
                file_dependencies[file_id] = _collect_file_dependencies(
                    obtained_file_obs,
                    ancestors_out=observed_ancestors,
                    symlinks_out=observed_symlinks,
                )
            except _FileDependencyObservationError as exc:
                file_dependencies[file_id] = exc.dependencies
                for idx, d_err in enumerate(exc.errors):
                    c_exc = (
                        exc.causes[idx]
                        if idx < len(exc.causes)
                        else (exc.causes[-1] if exc.causes else exc)
                    )
                    file_err_records.append(
                        ("outer_profile_files_and_roots", d_err, c_exc)
                    )
            except ValueError as exc:
                file_err_records.append(
                    ("outer_profile_files_and_roots", str(exc), exc)
                )

            if obtained_file_obs.resolved_path != declared_row["resolved_path"]:
                err_msg = (
                    f"files[{file_id!r}] resolved_path mismatch for {declared_row['path']!r}: "
                    f"expected {declared_row['resolved_path']!r}, observed {obtained_file_obs.resolved_path!r}"
                )
                file_err_records.append(
                    (
                        "outer_profile_files_and_roots",
                        err_msg,
                        ValueError(err_msg),
                    )
                )
            if obtained_file_obs.symlinks != declared_row["symlinks"]:
                err_msg = (
                    f"files[{file_id!r}] symlink edges mismatch for {declared_row['path']!r}: "
                    f"expected {[e.to_dict() for e in declared_row['symlinks']]}, "
                    f"observed {[e.to_dict() for e in obtained_file_obs.symlinks]}"
                )
                file_err_records.append(
                    (
                        "outer_profile_files_and_roots",
                        err_msg,
                        ValueError(err_msg),
                    )
                )
            if raw_evidence_root is not None and (
                _paths_overlap(obtained_file_obs.path, raw_evidence_root)
                or _paths_overlap(obtained_file_obs.resolved_path, raw_evidence_root)
            ):
                err_msg = (
                    f"files[{file_id!r}] ({obtained_file_obs.path!r}) overlaps evidence_root {raw_evidence_root!r}"
                )
                file_err_records.append(
                    ("evidence_root", err_msg, ValueError(err_msg))
                )

            if file_id in outer_manifest.tree_member_ids:
                if (
                    obtained_file_obs.path != obtained_file_obs.resolved_path
                    or obtained_file_obs.symlinks
                ):
                    err_msg = (
                        f"Controlled root member {file_id!r} ({obtained_file_obs.path!r}) must not use symlinks"
                    )
                    file_err_records.append(
                        (
                            "outer_profile_files_and_roots",
                            err_msg,
                            ValueError(err_msg),
                        )
                    )
            else:
                for r_name in EXPECTED_ROOT_NAMES:
                    r_path = outer_manifest.roots[r_name]["path"]
                    r_member_paths = {
                        outer_manifest.files[fid]["path"]
                        for fid in outer_manifest.roots[r_name]["file_ids"]
                    }
                    if Path(obtained_file_obs.path).is_relative_to(Path(r_path)):
                        err_msg = (
                            f"External file {file_id!r} has lexical path {obtained_file_obs.path!r} "
                            f"inside controlled root {r_name!r} ({r_path!r})"
                        )
                        file_err_records.append(
                            (
                                "outer_profile_files_and_roots",
                                err_msg,
                                ValueError(err_msg),
                            )
                        )
                    elif (
                        _paths_overlap(obtained_file_obs.resolved_path, r_path)
                        and obtained_file_obs.resolved_path not in r_member_paths
                    ):
                        err_msg = (
                            f"External file {file_id!r} ({obtained_file_obs.path!r} -> {obtained_file_obs.resolved_path!r}) "
                            f"resolves to unlisted path inside controlled root {r_name!r} ({r_path!r})"
                        )
                        file_err_records.append(
                            (
                                "outer_profile_files_and_roots",
                                err_msg,
                                ValueError(err_msg),
                            )
                        )

            full_target_sig = (
                *obtained_file_obs.identity_tuple,
                obtained_file_obs.sha256,
                obtained_file_obs.size_bytes,
            )
            prev_sig = resolved_identities.get(obtained_file_obs.resolved_path)
            if prev_sig is not None and prev_sig != full_target_sig:
                err_msg = (
                    f"Inconsistent observed target identity for aliases sharing "
                    f"{obtained_file_obs.resolved_path!r}"
                )
                file_err_records.append(
                    (
                        "outer_profile_files_and_roots",
                        err_msg,
                        ValueError(err_msg),
                    )
                )
            else:
                resolved_identities[obtained_file_obs.resolved_path] = full_target_sig

            if file_err_records:
                unverified_files[file_id] = obtained_file_obs
                per_file_error_messages[file_id] = [
                    m for _s, m, _e in file_err_records
                ]
                for st_name, m_str, exc_obj in file_err_records:
                    _record_err(st_name, exc_obj, message=m_str)
            else:
                verified_files[file_id] = obtained_file_obs
        else:
            if obtained_partial_obs is not None:
                partial_files[file_id] = obtained_partial_obs
                per_file_error_messages[file_id] = [
                    m for _s, m, _e in file_err_records
                ]
            for st_name, m_str, exc_obj in file_err_records:
                _record_err(st_name, exc_obj, message=m_str)

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
            per_file_error_messages.setdefault(diag_id, []).extend(
                diag_role_errors
            )
            for d_msg in diag_role_errors:
                _record_err(
                    "outer_profile_files_and_roots",
                    ValueError(d_msg),
                    message=d_msg,
                )

    # Re-verify that the original manifest pin was not replaced or mutated during observation
    try:
        manifest_after = _observe_regular_file_pin(
            profile.manifest.path,
            expected_pin=profile.manifest,
            chunk_size=chunk_size,
        )
        if manifest_after != manifest_observation:
            err_msg = (
                f"Profile manifest {profile.manifest.path!r} changed during profile observation"
            )
            manifest_error_messages.append(err_msg)
            _record_err("manifest_pin", ValueError(err_msg), message=err_msg)
    except ValueError as exc:
        err_msg = (
            f"Profile manifest {profile.manifest.path!r} failed post-observation recheck: {exc}"
        )
        manifest_error_messages.append(err_msg)
        recheck_exc = ValueError(err_msg)
        recheck_exc.__cause__ = exc
        _record_err("manifest_pin", recheck_exc, message=err_msg)

    if error_records:
        _raise_observation_error()

    manifest_file_obs = _project_manifest_file_observation(verified_flag=True)
    assert isinstance(manifest_file_obs, FileObservation)
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
        manifest_dependencies=manifest_dependencies,
        file_dependencies=file_dependencies,
        manifest_file_observation=manifest_file_obs,
        file_observations=_project_file_observations(),
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


SOURCE_MANIFEST_SCHEMA_ID = "protstruct_refmac_diagnostic_source_manifest_v1"
SOURCE_MANIFEST_VERIFIED_STATUS = "verified_upstream_commit_tree"
SOURCE_AUDIT_CONTRACT = "primary_refmac_source_audit_v1"
BUILD_RECEIPT_CONTRACT = "protstruct_instrumented_build_receipt_v2"
RUNTIME_OBSERVATION_CONTRACT = "primary_ccp4_runtime_configuration_observation_v1"


@dataclass(frozen=True)
class _RootMember:
    """Immutable ``(relative_path, file_id)`` root member entry supporting attribute, tuple, and dict access."""

    relative_path: str
    file_id: str

    def __post_init__(self) -> None:
        if type(self.relative_path) is not str or not self.relative_path:
            raise ValueError("_RootMember.relative_path must be a non-empty str")
        if type(self.file_id) is not str or not self.file_id:
            raise ValueError("_RootMember.file_id must be a non-empty str")

    def __iter__(self):
        yield self.relative_path
        yield self.file_id

    def __len__(self) -> int:
        return 2

    def __getitem__(self, key: int | str) -> str:
        if type(key) is int:
            if key in (0, -2):
                return self.relative_path
            if key in (1, -1):
                return self.file_id
            raise IndexError(key)
        if key == "relative_path":
            return self.relative_path
        if key == "file_id":
            return self.file_id
        raise KeyError(key)

    def keys(self) -> tuple[str, str]:
        return ("relative_path", "file_id")

    def __contains__(self, item: object) -> bool:
        return item in (
            "relative_path",
            "file_id",
            self.relative_path,
            self.file_id,
        )

    def __eq__(self, other: object) -> bool:
        if isinstance(other, _RootMember):
            return (self.relative_path, self.file_id) == (
                other.relative_path,
                other.file_id,
            )
        if isinstance(other, tuple) and len(other) == 2:
            return (self.relative_path, self.file_id) == other
        if isinstance(other, Mapping):
            return dict(other) == {
                "relative_path": self.relative_path,
                "file_id": self.file_id,
            }
        return NotImplemented

    def __hash__(self) -> int:
        return hash((self.relative_path, self.file_id))

    def to_dict(self) -> dict[str, str]:
        return {
            "relative_path": self.relative_path,
            "file_id": self.file_id,
        }


class _FrozenMemberTuple(tuple[_RootMember, ...]):
    """Immutable tuple of :class:`_RootMember` entries supporting both positional and ``relative_path`` lookup."""

    __slots__ = ()

    def __new__(cls, items) -> _FrozenMemberTuple:
        normalized: list[_RootMember] = []
        seen_rels: set[str] = set()
        for item in items:
            if isinstance(item, _RootMember):
                member = item
            elif (
                isinstance(item, tuple)
                and len(item) == 2
                and type(item[0]) is str
                and type(item[1]) is str
            ):
                member = _RootMember(relative_path=item[0], file_id=item[1])
            elif (
                isinstance(item, Mapping)
                and "relative_path" in item
                and "file_id" in item
            ):
                member = _RootMember(
                    relative_path=item["relative_path"],
                    file_id=item["file_id"],
                )
            else:
                raise ValueError(f"Invalid root member entry: {item!r}")
            if member.relative_path in seen_rels:
                raise ValueError(
                    f"Duplicate root member relative_path: {member.relative_path!r}"
                )
            seen_rels.add(member.relative_path)
            normalized.append(member)
        return super().__new__(cls, normalized)

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, (int, slice)):
            return super().__getitem__(key)
        if type(key) is str:
            for member in super().__iter__():
                if member.relative_path == key:
                    return member.file_id
            raise KeyError(key)
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        if type(key) is str:
            for member in super().__iter__():
                if member.relative_path == key:
                    return member.file_id
        return default

    def keys(self) -> tuple[str, ...]:
        return tuple(member.relative_path for member in super().__iter__())

    def values(self) -> tuple[str, ...]:
        return tuple(member.file_id for member in super().__iter__())

    def items(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (member.relative_path, member.file_id)
            for member in super().__iter__()
        )

    def __contains__(self, item: object) -> bool:
        if type(item) is str and any(
            member.relative_path == item for member in super().__iter__()
        ):
            return True
        return super().__contains__(item)

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("_FrozenMemberTuple is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("_FrozenMemberTuple is immutable")


class _FrozenPairTable(tuple[tuple[str, Any], ...]):
    """Immutable tuple of ``(key, value)`` pairs supporting both tuple iteration/indexing and read-only key lookup."""

    __slots__ = ()

    def __new__(cls, pairs) -> _FrozenPairTable:
        normalized: list[tuple[str, Any]] = []
        seen_keys: set[str] = set()
        source_pairs = pairs.items() if isinstance(pairs, Mapping) else pairs
        for item in source_pairs:
            if (
                not isinstance(item, tuple)
                or len(item) != 2
                or type(item[0]) is not str
                or not item[0]
            ):
                raise ValueError(
                    f"_FrozenPairTable entries must be (non-empty str, value) pairs, got {item!r}"
                )
            k, v = item
            if k in seen_keys:
                raise ValueError(f"Duplicate key in _FrozenPairTable: {k!r}")
            seen_keys.add(k)
            normalized.append((k, v))
        return super().__new__(cls, normalized)

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, (int, slice)):
            return super().__getitem__(key)
        if type(key) is str:
            for k, v in super().__iter__():
                if k == key:
                    return v
            raise KeyError(key)
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        if type(key) is str:
            for k, v in super().__iter__():
                if k == key:
                    return v
        return default

    def keys(self) -> tuple[str, ...]:
        return tuple(k for k, _v in super().__iter__())

    def values(self) -> tuple[Any, ...]:
        return tuple(v for _k, v in super().__iter__())

    def items(self) -> tuple[tuple[str, Any], ...]:
        return tuple(super().__iter__())

    def __contains__(self, item: object) -> bool:
        if type(item) is str and any(k == item for k, _v in super().__iter__()):
            return True
        return super().__contains__(item)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, tuple):
            return super().__eq__(other)
        if isinstance(other, Mapping):
            return dict(super().__iter__()) == dict(other)
        return NotImplemented

    def __hash__(self) -> int:
        return super().__hash__()

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError("_FrozenPairTable is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("_FrozenPairTable is immutable")


@dataclass(frozen=True)
class FileObservation:
    """Concrete immutable observation of a regular file, its symlink chain, and its directory ancestors."""

    path: str
    resolved_path: str
    sha256: str
    size_bytes: int
    dev: int
    ino: int
    mode: int
    uid: int
    gid: int
    symlinks: tuple[_SymlinkEdge, ...]
    symlink_identities: tuple[_ObservedSymlinkIdentity, ...]
    ancestors: tuple[_ObservedDirectoryIdentity, ...]
    dependencies_complete: bool = True
    verified: bool = True
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_lexical_abs_path(self.path, field_name="FileObservation.path")
        _validate_canonical_no_traversal_abs_path(
            self.resolved_path,
            field_name="FileObservation.resolved_path",
            allow_root=False,
        )
        _validate_sha256_digest(self.sha256, field_name="FileObservation.sha256")
        _validate_nonnegative_int(
            self.size_bytes, field_name="FileObservation.size_bytes"
        )
        for attr_name in ("dev", "ino", "mode", "uid", "gid"):
            val = getattr(self, attr_name)
            if type(val) is not int:
                raise ValueError(
                    f"FileObservation.{attr_name} must be a non-boolean int"
                )
        if (self.dev, self.ino, self.mode) == (0, 0, 0) or self.dev <= 0 or self.ino <= 0:
            raise ValueError(
                "FileObservation cannot use fabricated zero or non-positive dev/ino identity"
            )
        if not isinstance(self.symlinks, tuple) or not all(
            type(edge) is _SymlinkEdge for edge in self.symlinks
        ):
            raise ValueError(
                "FileObservation.symlinks must be a tuple of _SymlinkEdge"
            )
        edge_paths = [edge.path for edge in self.symlinks]
        if edge_paths != sorted(set(edge_paths)):
            raise ValueError(
                "FileObservation.symlinks must be strictly sorted by unique edge.path"
            )
        if not isinstance(self.symlink_identities, tuple) or not all(
            type(sym) is _ObservedSymlinkIdentity for sym in self.symlink_identities
        ):
            raise ValueError(
                "FileObservation.symlink_identities must be a tuple of _ObservedSymlinkIdentity"
            )
        if not isinstance(self.ancestors, tuple) or not all(
            type(anc) is _ObservedDirectoryIdentity for anc in self.ancestors
        ):
            raise ValueError(
                "FileObservation.ancestors must be a tuple of _ObservedDirectoryIdentity"
            )
        if type(self.dependencies_complete) is not bool:
            raise ValueError(
                "FileObservation.dependencies_complete must be a bool"
            )
        if type(self.verified) is not bool:
            raise ValueError("FileObservation.verified must be a bool")
        if not isinstance(self.errors, tuple) or not all(
            type(e) is str and e for e in self.errors
        ):
            raise ValueError(
                "FileObservation.errors must be a tuple of non-empty str"
            )

        expected_pairs = [(e.path, e.target) for e in self.symlinks]
        observed_pairs = [(s.path, s.target) for s in self.symlink_identities]
        if self.dependencies_complete:
            if observed_pairs != expected_pairs:
                raise ValueError(
                    "FileObservation.symlink_identities must match FileObservation.symlinks in exact order"
                )
            if len(self.ancestors) == 0:
                raise ValueError(
                    "FileObservation.ancestors must be a non-empty tuple of _ObservedDirectoryIdentity"
                )
        else:
            it = iter(expected_pairs)
            if not all(pair in it for pair in observed_pairs):
                raise ValueError(
                    "FileObservation.symlink_identities must be an ordered subset of FileObservation.symlinks"
                )
            if self.verified:
                raise ValueError(
                    "FileObservation cannot have verified=True when dependencies_complete=False"
                )
            if len(self.errors) == 0:
                raise ValueError(
                    "FileObservation with dependencies_complete=False must record non-empty errors"
                )
        if self.verified and len(self.errors) > 0:
            raise ValueError(
                "FileObservation cannot have verified=True when errors are present"
            )

    @property
    def complete(self) -> bool:
        return self.dependencies_complete

    @property
    def unavailable_symlinks(self) -> tuple[_SymlinkEdge, ...]:
        observed_paths = {s.path for s in self.symlink_identities}
        return tuple(e for e in self.symlinks if e.path not in observed_paths)

    @property
    def identity_tuple(self) -> tuple[int, int, int, int, int]:
        return (self.dev, self.ino, self.mode, self.uid, self.gid)

    def as_file_pin(self) -> FilePin:
        return FilePin(
            path=self.path,
            sha256=self.sha256,
            size_bytes=self.size_bytes,
        )

    def __getitem__(self, key: str) -> Any:
        d = self.to_dict()
        if key in d:
            return d[key]
        raise KeyError(key)

    def keys(self):
        return self.to_dict().keys()

    def __contains__(self, item: object) -> bool:
        return item in self.to_dict()

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "path": self.path,
            "resolved_path": self.resolved_path,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "dev": self.dev,
            "ino": self.ino,
            "mode": self.mode,
            "uid": self.uid,
            "gid": self.gid,
            "symlinks": [edge.to_dict() for edge in self.symlinks],
            "symlink_identities": [
                sym.to_dict() for sym in self.symlink_identities
            ],
            "ancestors": [anc.to_dict() for anc in self.ancestors],
            "dependencies_complete": self.dependencies_complete,
            "verified": self.verified,
        }
        if self.errors:
            result["errors"] = list(self.errors)
        return result

    def to_provenance(self) -> dict[str, Any]:
        return self.to_dict()


@dataclass(frozen=True)
class RootObservation:
    """Concrete immutable observation of a controlled root directory, its ancestors, and its ordered members."""

    name: str
    path: str
    resolved_path: str
    dev: int
    ino: int
    mode: int
    uid: int
    gid: int
    ancestors: tuple[_ObservedDirectoryIdentity, ...]
    members: tuple[_RootMember, ...]
    file_ids: tuple[str, ...] = ()
    subdirectories: tuple[_ObservedDirectoryIdentity, ...] = ()
    excluded_root_git_present: bool = False
    scan_complete: bool = True
    verified: bool = True
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.name not in EXPECTED_ROOT_NAMES:
            raise ValueError(f"RootObservation.name invalid: {self.name!r}")
        _validate_canonical_no_traversal_abs_path(
            self.path, field_name="RootObservation.path"
        )
        _validate_canonical_no_traversal_abs_path(
            self.resolved_path, field_name="RootObservation.resolved_path"
        )
        if self.path != self.resolved_path:
            raise ValueError(
                f"RootObservation {self.name!r} path {self.path!r} != resolved_path {self.resolved_path!r}"
            )
        for attr_name in ("dev", "ino", "mode", "uid", "gid"):
            val = getattr(self, attr_name)
            if type(val) is not int:
                raise ValueError(
                    f"RootObservation.{attr_name} must be a non-boolean int"
                )
        if (
            not isinstance(self.ancestors, tuple)
            or len(self.ancestors) == 0
            or not all(
                type(anc) is _ObservedDirectoryIdentity for anc in self.ancestors
            )
        ):
            raise ValueError(
                "RootObservation.ancestors must be a non-empty tuple of _ObservedDirectoryIdentity"
            )
        frozen_members = _FrozenMemberTuple(self.members)
        object.__setattr__(self, "members", frozen_members)
        if not isinstance(self.file_ids, tuple) or not all(
            type(fid) is str and fid for fid in self.file_ids
        ):
            raise ValueError("RootObservation.file_ids must be a tuple of str")
        if not isinstance(self.subdirectories, tuple) or not all(
            type(sub) is _ObservedDirectoryIdentity for sub in self.subdirectories
        ):
            raise ValueError(
                "RootObservation.subdirectories must be a tuple of _ObservedDirectoryIdentity"
            )
        if type(self.excluded_root_git_present) is not bool:
            raise ValueError(
                "RootObservation.excluded_root_git_present must be a bool"
            )
        if type(self.scan_complete) is not bool:
            raise ValueError("RootObservation.scan_complete must be a bool")
        if type(self.verified) is not bool:
            raise ValueError("RootObservation.verified must be a bool")
        if not isinstance(self.errors, tuple) or not all(
            type(e) is str for e in self.errors
        ):
            raise ValueError("RootObservation.errors must be a tuple of str")

    @property
    def identity_tuple(self) -> tuple[int, int, int, int, int]:
        return (self.dev, self.ino, self.mode, self.uid, self.gid)

    def __getitem__(self, key: str) -> Any:
        d = self.to_dict()
        if key in d:
            return d[key]
        raise KeyError(key)

    def keys(self):
        return self.to_dict().keys()

    def __contains__(self, item: object) -> bool:
        return item in self.to_dict()

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": self.name,
            "path": self.path,
            "resolved_path": self.resolved_path,
            "dev": self.dev,
            "ino": self.ino,
            "mode": self.mode,
            "uid": self.uid,
            "gid": self.gid,
            "ancestors": [anc.to_dict() for anc in self.ancestors],
            "members": [m.to_dict() for m in self.members],
            "file_ids": list(self.file_ids),
            "subdirectories": [sub.to_dict() for sub in self.subdirectories],
            "excluded_root_git_present": self.excluded_root_git_present,
            "scan_complete": self.scan_complete,
            "verified": self.verified,
        }
        if self.errors:
            result["errors"] = list(self.errors)
        return result

    def to_provenance(self) -> dict[str, Any]:
        return self.to_dict()


@dataclass(frozen=True)
class ValidatedProfile:
    """Deeply immutable validated diagnostic profile baseline and provenance emitter."""

    request: RefmacDiagnosticProfile
    manifest_identity: FileObservation
    files: tuple[tuple[str, FileObservation], ...]
    roots: tuple[tuple[str, RootObservation], ...]
    roles: tuple[tuple[str, tuple[str, ...]], ...]
    installed_reference: FilePin
    selected_executable: FilePin
    installed_record_json: str
    expected_environment: tuple[tuple[str, str], ...]
    requested_absences: tuple[str, ...]
    evidence_root: str
    _outer_state: _CheckedOuterProfileState | None = field(
        default=None, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if type(self.request) is not RefmacDiagnosticProfile:
            raise ValueError(
                "ValidatedProfile.request must be a RefmacDiagnosticProfile"
            )
        if type(self.manifest_identity) is not FileObservation:
            raise ValueError(
                "ValidatedProfile.manifest_identity must be a FileObservation"
            )
        if (
            not self.manifest_identity.dependencies_complete
            or not self.manifest_identity.verified
            or self.manifest_identity.errors
        ):
            raise ValueError(
                "ValidatedProfile.manifest_identity must have dependencies_complete=True, verified=True, and no errors"
            )
        if type(self.installed_reference) is not FilePin:
            raise ValueError(
                "ValidatedProfile.installed_reference must be a FilePin"
            )
        if type(self.selected_executable) is not FilePin:
            raise ValueError(
                "ValidatedProfile.selected_executable must be a FilePin"
            )
        if self.selected_executable != self.request.executable:
            raise ValueError(
                "ValidatedProfile.selected_executable must match request.executable"
            )
        if (
            self.installed_reference.path == self.selected_executable.path
            or self.installed_reference.sha256 == self.selected_executable.sha256
        ):
            raise ValueError(
                "ValidatedProfile.installed_reference must be distinct from selected_executable"
            )
        if type(self.installed_record_json) is not str or not self.installed_record_json:
            raise ValueError(
                "ValidatedProfile.installed_record_json must be a non-empty JSON str"
            )
        _parse_in_memory_json_object(
            self.installed_record_json,
            label="ValidatedProfile.installed_record_json",
        )
        _validate_canonical_no_traversal_abs_path(
            self.evidence_root, field_name="ValidatedProfile.evidence_root"
        )

        frozen_files = _FrozenPairTable(self.files)
        for fid, fobs in frozen_files:
            _validate_opaque_id(fid, field_name="ValidatedProfile.files key")
            if type(fobs) is not FileObservation:
                raise ValueError(
                    f"ValidatedProfile.files[{fid!r}] must be a FileObservation"
                )
            if (
                not fobs.dependencies_complete
                or not fobs.verified
                or fobs.errors
            ):
                raise ValueError(
                    f"ValidatedProfile.files[{fid!r}] must have dependencies_complete=True, verified=True, and no errors"
                )
        object.__setattr__(self, "files", frozen_files)

        frozen_roots = _FrozenPairTable(self.roots)
        for rid, robs in frozen_roots:
            if rid not in EXPECTED_ROOT_NAMES or type(robs) is not RootObservation:
                raise ValueError(
                    f"ValidatedProfile.roots[{rid!r}] must be a valid RootObservation"
                )
            if not robs.scan_complete or not robs.verified or robs.errors:
                raise ValueError(
                    f"ValidatedProfile.roots[{rid!r}] must be scan_complete and verified"
                )
        object.__setattr__(self, "roots", frozen_roots)

        normalized_roles: list[tuple[str, tuple[str, ...]]] = []
        source_roles = (
            self.roles.items() if isinstance(self.roles, Mapping) else self.roles
        )
        for item in source_roles:
            if not isinstance(item, tuple) or len(item) != 2:
                raise ValueError(f"Invalid role entry in ValidatedProfile: {item!r}")
            rname, rids = item
            if (
                type(rname) is not str
                or not isinstance(rids, (tuple, list))
                or len(rids) == 0
                or not all(type(x) is str and x for x in rids)
            ):
                raise ValueError(
                    f"ValidatedProfile.roles[{rname!r}] must be a non-empty tuple of str"
                )
            normalized_roles.append((rname, tuple(rids)))
        object.__setattr__(self, "roles", _FrozenPairTable(normalized_roles))

        frozen_env = _FrozenPairTable(self.expected_environment)
        for env_k, env_v in frozen_env:
            if type(env_k) is not str or type(env_v) is not str:
                raise ValueError(
                    "ValidatedProfile.expected_environment entries must be (str, str)"
                )
        object.__setattr__(self, "expected_environment", frozen_env)

        if not isinstance(self.requested_absences, tuple) or not all(
            type(k) is str and k for k in self.requested_absences
        ):
            raise ValueError(
                "ValidatedProfile.requested_absences must be a tuple of non-empty str"
            )

    @property
    def profile_id(self) -> str:
        return self.request.profile_id

    @property
    def subject_id(self) -> str:
        return PROFILE_SUBJECT_ID

    @property
    def profile_files_verified(self) -> bool:
        return True

    @property
    def runtime_image_coverage(self) -> str:
        return "not_assessed"

    def to_provenance(self) -> dict[str, Any]:
        """Return a fresh detached JSON-safe provenance dictionary on every call."""
        return {
            "profile_id": self.profile_id,
            "subject_id": self.subject_id,
            "requested": {
                "manifest": self.request.manifest.to_dict(),
                "executable": self.request.executable.to_dict(),
            },
            "profile_files_verified": True,
            "runtime_image_coverage": "not_assessed",
            "selected_executable": self.selected_executable.to_dict(),
            "installed_reference": self.installed_reference.to_dict(),
            "installed_record": _parse_in_memory_json_object(
                self.installed_record_json,
                label="ValidatedProfile.installed_record_json",
            ),
            "evidence_root": self.evidence_root,
            "manifest": self.manifest_identity.to_dict(),
            "files": {
                file_id: file_obs.to_dict() for file_id, file_obs in self.files
            },
            "roots": {
                root_id: root_obs.to_dict() for root_id, root_obs in self.roots
            },
            "roles": {
                role_name: list(file_ids) for role_name, file_ids in self.roles
            },
            "expected_environment": {
                key: value for key, value in self.expected_environment
            },
            "requested_absences": list(self.requested_absences),
        }


def _walk_exception_cause_chain(
    exc: BaseException,
) -> tuple[BaseException, ...]:
    """Walk ``exc`` and its explicit ``__cause__`` links without cycles."""
    chain: list[BaseException] = []
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        chain.append(cur)
        if cur.__cause__ is not None:
            cur = cur.__cause__
        elif (
            isinstance(cur, _ProfileObservationError)
            and cur.primary_exception is not None
        ):
            cur = cur.primary_exception
        elif (
            isinstance(
                cur,
                (
                    _ControlledRootObservationError,
                    _FileDependencyObservationError,
                ),
            )
            and cur.causes
        ):
            cur = cur.causes[0]
        else:
            cur = None
    return tuple(chain)


def _select_original_cause_exception(exc: BaseException) -> BaseException:
    """Select the single underlying cause exception from ``exc`` and its ``__cause__`` chain."""
    chain = _walk_exception_cause_chain(exc)
    carrier_types = (
        _ProfileObservationError,
        _ControlledRootObservationError,
        _ObservedFilePinError,
        _PartialFileReadError,
        _FileDependencyObservationError,
    )
    non_carriers = [c for c in chain if not isinstance(c, carrier_types)]
    candidates = non_carriers if non_carriers else list(chain)

    errno_bearing = [
        c
        for c in candidates
        if isinstance(c, OSError) or getattr(c, "errno", None) is not None
    ]
    if errno_bearing:
        return errno_bearing[-1]

    non_value_causes = [c for c in candidates if type(c) is not ValueError]
    if non_value_causes:
        return non_value_causes[-1]

    return candidates[0]


@dataclass(frozen=True)
class _ProfileValidationFailurePayload:
    """Deeply immutable payload storing all request, observation, configuration, and error evidence for :class:`ProfileValidationError`."""

    failed_check: str
    request: RefmacDiagnosticProfile | None
    manifest_identity: FileObservation | PartialFileReadObservation | None
    files: _FrozenPairTable
    roots: _FrozenPairTable
    roles: _FrozenPairTable
    installed_reference: FilePin | None
    installed_record_json: str | None
    installed_record: Mapping[str, Any] | None
    expected_environment: _FrozenPairTable
    requested_absences: tuple[str, ...]
    evidence_root: str | None
    cause_exception: BaseException | None
    wrapper_message: str
    error_type: str
    error_message: str
    error_errno: int | None
    errors: tuple[str, ...]
    error_records: tuple[_RecordedObservationError, ...]
    partial_observation: _PartialProfileObservation | None


class ProfileValidationError(ValueError):
    """Public exception raised when :func:`validate_profile` rejects a profile or runtime input.

    Retains all obtainable :class:`FileObservation` and :class:`RootObservation` records
    in a deeply immutable payload without ever masquerading as a validated baseline
    (``profile_files_verified`` is always ``False`` and ``selected_executable`` is always ``None``).
    """

    __slots__ = ("_payload",)

    def __init__(
        self,
        message: str,
        *,
        failed_check: str,
        request: RefmacDiagnosticProfile | None = None,
        manifest_identity: FileObservation | PartialFileReadObservation | None = None,
        files: tuple[
            tuple[str, FileObservation | PartialFileReadObservation], ...
        ]
        | Mapping[str, FileObservation | PartialFileReadObservation] = (),
        roots: tuple[tuple[str, RootObservation], ...]
        | Mapping[str, RootObservation] = (),
        roles: tuple[tuple[str, tuple[str, ...]], ...]
        | Mapping[str, Any] = (),
        installed_reference: FilePin | None = None,
        installed_record_json: str | None = None,
        expected_environment: tuple[tuple[str, str], ...]
        | Mapping[str, str] = (),
        requested_absences: tuple[str, ...] = EXPECTED_RUNTIME_ABSENT_KEYS,
        evidence_root: str | None = None,
        cause_exception: BaseException | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        error_errno: int | None = None,
        errors: tuple[str, ...] = (),
        error_records: tuple[_RecordedObservationError, ...] = (),
        partial_observation: _PartialProfileObservation | None = None,
    ) -> None:
        if type(message) is not str:
            raise ValueError("ProfileValidationError message must be a str")
        super().__init__(message)
        if type(failed_check) is not str or not failed_check:
            raise ValueError(
                "ProfileValidationError.failed_check must be a non-empty str"
            )
        checked_request: RefmacDiagnosticProfile | None = (
            request if type(request) is RefmacDiagnosticProfile else None
        )
        if manifest_identity is not None and type(manifest_identity) not in (
            FileObservation,
            PartialFileReadObservation,
        ):
            raise ValueError(
                "ProfileValidationError.manifest_identity must be FileObservation, PartialFileReadObservation, or None"
            )
        frozen_files = _FrozenPairTable(files)
        for fid, fobs in frozen_files:
            if type(fobs) not in (FileObservation, PartialFileReadObservation):
                raise ValueError(
                    f"ProfileValidationError.files[{fid!r}] must be FileObservation or PartialFileReadObservation"
                )
        frozen_roots = _FrozenPairTable(roots)
        for rid, robs in frozen_roots:
            if type(robs) is not RootObservation:
                raise ValueError(
                    f"ProfileValidationError.roots[{rid!r}] must be RootObservation"
                )
        raw_roles = (
            roles.items() if isinstance(roles, Mapping) else roles
        )
        normalized_roles: list[tuple[str, tuple[str, ...]]] = []
        for item in raw_roles:
            if not isinstance(item, tuple) or len(item) != 2:
                raise ValueError(
                    f"ProfileValidationError.roles entries must be (role_name, file_ids) pairs, got {item!r}"
                )
            rname, rids = item
            if (
                type(rname) is not str
                or not rname
                or not isinstance(rids, (tuple, list))
                or not all(type(x) is str and x for x in rids)
            ):
                raise ValueError(
                    f"ProfileValidationError.roles[{rname!r}] must be a sequence of non-empty str"
                )
            normalized_roles.append((rname, tuple(rids)))
        frozen_roles = _FrozenPairTable(normalized_roles)
        if installed_reference is not None and type(installed_reference) is not FilePin:
            raise ValueError(
                "ProfileValidationError.installed_reference must be FilePin or None"
            )
        frozen_installed_record: Mapping[str, Any] | None = None
        if installed_record_json is not None:
            parsed_inst = _parse_in_memory_json_object(
                installed_record_json,
                label="ProfileValidationError.installed_record_json",
            )
            frozen_installed_record = _deep_freeze_json_value(parsed_inst)
        frozen_env = _FrozenPairTable(expected_environment)
        for env_k, env_v in frozen_env:
            if type(env_k) is not str or type(env_v) is not str:
                raise ValueError(
                    "ProfileValidationError.expected_environment entries must be (str, str)"
                )
        frozen_absences = tuple(requested_absences)
        if not all(type(k) is str and k for k in frozen_absences):
            raise ValueError(
                "ProfileValidationError.requested_absences must contain non-empty str entries"
            )
        if evidence_root is not None and type(evidence_root) is not str:
            raise ValueError(
                "ProfileValidationError.evidence_root must be str or None"
            )

        selected_cause = (
            _select_original_cause_exception(cause_exception)
            if cause_exception is not None
            else None
        )
        if selected_cause is not None:
            resolved_error_type: str = (
                error_type
                if error_type is not None
                else type(selected_cause).__name__
            )
            resolved_error_message: str = (
                error_message
                if error_message is not None
                else str(selected_cause)
            )
            resolved_error_errno: int | None = (
                error_errno
                if error_errno is not None
                else getattr(selected_cause, "errno", None)
            )
        else:
            resolved_error_type = (
                error_type
                if error_type is not None
                else "ProfileValidationError"
            )
            resolved_error_message = (
                error_message if error_message is not None else message
            )
            resolved_error_errno = error_errno
        if type(resolved_error_type) is not str or not resolved_error_type:
            raise ValueError(
                "ProfileValidationError.error_type must be a non-empty str"
            )
        if type(resolved_error_message) is not str:
            raise ValueError(
                "ProfileValidationError.error_message must be a str"
            )
        if resolved_error_errno is not None and type(resolved_error_errno) is not int:
            raise ValueError(
                "ProfileValidationError.error_errno must be an int or None"
            )
        frozen_errors: tuple[str, ...] = (
            tuple(errors) if errors else (message,)
        )
        if not all(type(e) is str and e for e in frozen_errors):
            raise ValueError(
                "ProfileValidationError.errors must be a tuple of non-empty str"
            )
        frozen_error_records: tuple[_RecordedObservationError, ...] = tuple(
            error_records
        )
        if not all(
            type(rec) is _RecordedObservationError
            for rec in frozen_error_records
        ):
            raise ValueError(
                "ProfileValidationError.error_records must be a tuple of _RecordedObservationError"
            )
        if (
            partial_observation is not None
            and type(partial_observation) is not _PartialProfileObservation
        ):
            raise ValueError(
                "ProfileValidationError.partial_observation must be _PartialProfileObservation or None"
            )

        payload = _ProfileValidationFailurePayload(
            failed_check=failed_check,
            request=checked_request,
            manifest_identity=manifest_identity,
            files=frozen_files,
            roots=frozen_roots,
            roles=frozen_roles,
            installed_reference=installed_reference,
            installed_record_json=installed_record_json,
            installed_record=frozen_installed_record,
            expected_environment=frozen_env,
            requested_absences=frozen_absences,
            evidence_root=evidence_root,
            cause_exception=selected_cause,
            wrapper_message=message,
            error_type=resolved_error_type,
            error_message=resolved_error_message,
            error_errno=resolved_error_errno,
            errors=frozen_errors,
            error_records=frozen_error_records,
            partial_observation=partial_observation,
        )
        object.__setattr__(self, "_payload", payload)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in _MUTABLE_EXCEPTION_ATTRS:
            super().__setattr__(name, value)
            return
        raise AttributeError(
            f"ProfileValidationError attribute {name!r} is read-only"
        )

    def __delattr__(self, name: str) -> None:
        if name in _MUTABLE_EXCEPTION_ATTRS:
            super().__delattr__(name)
            return
        raise AttributeError(
            f"ProfileValidationError attribute {name!r} is read-only"
        )

    @property
    def failed_check(self) -> str:
        return self._payload.failed_check

    @property
    def request(self) -> RefmacDiagnosticProfile | None:
        return self._payload.request

    @property
    def profile_id(self) -> str | None:
        return (
            self._payload.request.profile_id
            if self._payload.request is not None
            else None
        )

    @property
    def subject_id(self) -> str:
        return PROFILE_SUBJECT_ID

    @property
    def manifest_identity(
        self,
    ) -> FileObservation | PartialFileReadObservation | None:
        return self._payload.manifest_identity

    @property
    def files(self) -> _FrozenPairTable:
        return self._payload.files

    @property
    def roots(self) -> _FrozenPairTable:
        return self._payload.roots

    @property
    def roles(self) -> _FrozenPairTable:
        return self._payload.roles

    @property
    def installed_reference(self) -> FilePin | None:
        return self._payload.installed_reference

    @property
    def selected_executable(self) -> None:
        return None

    @property
    def profile_files_verified(self) -> bool:
        return False

    @property
    def runtime_image_coverage(self) -> str:
        return "not_assessed"

    @property
    def installed_record_json(self) -> str | None:
        return self._payload.installed_record_json

    @property
    def installed_record(self) -> Mapping[str, Any] | None:
        return self._payload.installed_record

    @property
    def expected_environment(self) -> _FrozenPairTable:
        return self._payload.expected_environment

    @property
    def requested_absences(self) -> tuple[str, ...]:
        return self._payload.requested_absences

    @property
    def evidence_root(self) -> str | None:
        return self._payload.evidence_root

    @property
    def cause_exception(self) -> BaseException | None:
        return self._payload.cause_exception

    @property
    def wrapper_message(self) -> str:
        return self._payload.wrapper_message

    @property
    def error_type(self) -> str:
        return self._payload.error_type

    @property
    def error_message(self) -> str:
        return self._payload.error_message

    @property
    def error_errno(self) -> int | None:
        return self._payload.error_errno

    @property
    def errors(self) -> tuple[str, ...]:
        return self._payload.errors

    @property
    def error_records(self) -> tuple[_RecordedObservationError, ...]:
        return self._payload.error_records

    @property
    def partial_observation(self) -> _PartialProfileObservation | None:
        return self._payload.partial_observation

    def to_provenance(self) -> dict[str, Any]:
        """Return a fresh JSON-safe failure provenance dictionary retaining obtained observations."""
        p = self._payload
        error_dict: dict[str, Any] = {
            "type": p.error_type,
            "message": p.error_message,
            "errno": p.error_errno,
        }
        if p.wrapper_message != p.error_message:
            error_dict["wrapper_message"] = p.wrapper_message
        return {
            "profile_id": (
                p.request.profile_id if p.request is not None else None
            ),
            "subject_id": PROFILE_SUBJECT_ID,
            "requested": (
                {
                    "manifest": p.request.manifest.to_dict(),
                    "executable": p.request.executable.to_dict(),
                }
                if p.request is not None
                else None
            ),
            "profile_files_verified": False,
            "runtime_image_coverage": "not_assessed",
            "selected_executable": None,
            "installed_reference": (
                p.installed_reference.to_dict()
                if p.installed_reference is not None
                else None
            ),
            "installed_record": (
                _parse_in_memory_json_object(
                    p.installed_record_json,
                    label="ProfileValidationError.installed_record_json",
                )
                if p.installed_record_json is not None
                else None
            ),
            "evidence_root": p.evidence_root,
            "manifest": (
                p.manifest_identity.to_dict()
                if p.manifest_identity is not None
                else None
            ),
            "files": {
                file_id: file_obs.to_dict() for file_id, file_obs in p.files
            },
            "roots": {
                root_id: root_obs.to_dict() for root_id, root_obs in p.roots
            },
            "roles": {
                role_name: list(file_ids) for role_name, file_ids in p.roles
            },
            "expected_environment": {
                key: value for key, value in p.expected_environment
            },
            "requested_absences": list(p.requested_absences),
            "failed_check": p.failed_check,
            "error": error_dict,
            "errors": list(p.errors),
        }


def _build_file_observation(
    file_obs: _ObservedRegularFilePin,
    *,
    observed_ancestors: Mapping[str, _ObservedDirectoryIdentity],
    observed_symlinks: Mapping[str, _ObservedSymlinkIdentity],
    file_dependencies: _ObservedFileDependencies | None = None,
    verified: bool = True,
    errors: tuple[str, ...] = (),
) -> FileObservation:
    """Project a concrete :class:`FileObservation` purely in memory from retained observations."""
    err_list: list[str] = list(errors)
    if file_dependencies is not None:
        file_ancs = file_dependencies.ancestors
        file_syms = file_dependencies.symlink_identities
        deps_complete = file_dependencies.complete
        for d_err in file_dependencies.errors:
            if d_err not in err_list:
                err_list.append(d_err)
    else:
        anc_map: dict[str, _ObservedDirectoryIdentity] = {}
        for parent in Path(file_obs.resolved_path).parents:
            p_str = str(parent)
            if p_str in observed_ancestors:
                anc_map[p_str] = observed_ancestors[p_str]
        for dir_obs in file_obs.traversed_directory_identities:
            if dir_obs.path in observed_ancestors:
                anc_map.setdefault(dir_obs.path, observed_ancestors[dir_obs.path])
            else:
                anc_map.setdefault(dir_obs.path, dir_obs)
        file_ancs = tuple(anc_map.values())

        sym_list: list[_ObservedSymlinkIdentity] = []
        missing_edges: list[_SymlinkEdge] = []
        for edge in file_obs.symlinks:
            sym_obs = observed_symlinks.get(edge.path)
            if sym_obs is not None and sym_obs.target == edge.target:
                sym_list.append(sym_obs)
            else:
                missing_edges.append(edge)
        file_syms = tuple(sym_list)

        resolved_parents_present = all(
            str(p) in anc_map for p in Path(file_obs.resolved_path).parents
        )
        traversed_dirs_present = all(
            d.path in anc_map for d in file_obs.traversed_directory_identities
        )
        deps_complete = (
            len(file_ancs) > 0
            and resolved_parents_present
            and traversed_dirs_present
            and len(missing_edges) == 0
        )
        if not deps_complete and not err_list:
            if missing_edges:
                err_list.append(
                    f"Unavailable symlink identity observation(s) for {file_obs.path!r}: "
                    f"{[e.path for e in missing_edges]}"
                )
            else:
                err_list.append(
                    f"Incomplete directory ancestor observation(s) for {file_obs.path!r}"
                )

    effective_verified = bool(verified and deps_complete and len(err_list) == 0)
    return FileObservation(
        path=file_obs.path,
        resolved_path=file_obs.resolved_path,
        sha256=file_obs.sha256,
        size_bytes=file_obs.size_bytes,
        dev=file_obs.dev,
        ino=file_obs.ino,
        mode=file_obs.mode,
        uid=file_obs.uid,
        gid=file_obs.gid,
        symlinks=file_obs.symlinks,
        symlink_identities=file_syms,
        ancestors=file_ancs,
        dependencies_complete=deps_complete,
        verified=effective_verified,
        errors=tuple(err_list),
    )


def _build_root_observation(
    root_inv: _ObservedRootInventory,
    outer_manifest: _CheckedOuterManifest | None,
) -> RootObservation:
    """Construct a concrete :class:`RootObservation` from an observed root inventory."""
    rel_to_fid: dict[str, str] = {}
    root_path_obj = Path(root_inv.path)
    if outer_manifest is not None:
        for fid in root_inv.file_ids:
            if fid in outer_manifest.files:
                frow = outer_manifest.files[fid]
                try:
                    rel_posix = (
                        Path(frow["path"]).relative_to(root_path_obj).as_posix()
                    )
                    rel_to_fid[rel_posix] = fid
                except ValueError:
                    continue

    members_list: list[_RootMember] = []
    for rel_posix in sorted(root_inv.member_pins.keys()):
        fid = rel_to_fid.get(rel_posix, f"<unregistered:{rel_posix}>")
        members_list.append(_RootMember(relative_path=rel_posix, file_id=fid))

    return RootObservation(
        name=root_inv.name,
        path=root_inv.path,
        resolved_path=root_inv.resolved_path,
        dev=root_inv.directory_identity.dev,
        ino=root_inv.directory_identity.ino,
        mode=root_inv.directory_identity.mode,
        uid=root_inv.directory_identity.uid,
        gid=root_inv.directory_identity.gid,
        ancestors=root_inv.ancestor_identities,
        members=tuple(members_list),
        file_ids=root_inv.file_ids,
        subdirectories=tuple(root_inv.subdirectory_identities.values()),
        excluded_root_git_present=root_inv.excluded_root_git_present,
        scan_complete=root_inv.scan_complete,
        verified=root_inv.verified,
        errors=root_inv.errors,
    )


def _parse_in_memory_json_object(
    json_text: str,
    *,
    label: str,
) -> dict[str, Any]:
    """Parse an in-memory JSON string strictly (rejecting duplicate keys and NaN/Infinity) into a detached dict."""
    if type(json_text) is not str or not json_text:
        raise ValueError(f"{label} must be a non-empty JSON str")
    try:
        parsed = json.loads(
            json_text,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_nonstandard_json_constant,
        )
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON syntax in {label}: {exc}") from exc
    except ValueError as exc:
        raise ValueError(f"Invalid JSON in {label}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{label} must decode to a JSON object")
    return parsed


def _serialize_detached_installed_record(installed_record: Any) -> tuple[str, Mapping[str, Any]]:
    """Serialize ``installed_record`` into canonical JSON and re-parse a detached mapping."""
    if not isinstance(installed_record, Mapping):
        raise ValueError(
            f"installed_record must be a Mapping, got {type(installed_record).__name__}"
        )
    try:
        canonical_json = json.dumps(
            dict(installed_record), sort_keys=True, allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"installed_record must be JSON-serializable without NaN/Infinity: {exc}"
        ) from exc
    detached = _parse_in_memory_json_object(
        canonical_json,
        label="installed_record",
    )
    return canonical_json, _deep_freeze_json_value(detached)


def _extract_installed_record_projection(
    record: Any,
    *,
    label: str,
) -> dict[str, Any]:
    """Validate and extract the required projection from ``installed_record`` or ``resolver_record``."""
    if not isinstance(record, Mapping):
        raise ValueError(f"{label} must be a JSON object")

    prefix = _validate_canonical_no_traversal_abs_path(
        record.get("configured_installation_prefix"),
        field_name=f"{label}.configured_installation_prefix",
    )

    setup = record.get("setup_script")
    if not isinstance(setup, Mapping):
        raise ValueError(f"{label}.setup_script must be a JSON object")
    setup_cfg_path = _validate_lexical_abs_path(
        setup.get("configured_path"),
        field_name=f"{label}.setup_script.configured_path",
    )
    setup_res_path = _validate_canonical_no_traversal_abs_path(
        setup.get("resolved_path"),
        field_name=f"{label}.setup_script.resolved_path",
    )
    setup_is_sym = setup.get("is_symlink")
    if type(setup_is_sym) is not bool:
        raise ValueError(f"{label}.setup_script.is_symlink must be a strict bool")
    if setup_is_sym != (setup_cfg_path != setup_res_path):
        raise ValueError(
            f"{label}.setup_script.is_symlink ({setup_is_sym}) contradicts "
            f"configured_path={setup_cfg_path!r} vs resolved_path={setup_res_path!r}"
        )
    setup_within = setup.get("within_prefix")
    if type(setup_within) is not bool or setup_within is not True:
        raise ValueError(
            f"{label}.setup_script.within_prefix must be strict bool True"
        )
    if not Path(setup_res_path).is_relative_to(Path(prefix)):
        raise ValueError(
            f"{label}.setup_script.resolved_path {setup_res_path!r} is outside "
            f"configured_installation_prefix {prefix!r}"
        )
    setup_sha = _validate_sha256_digest(
        setup.get("sha256"),
        field_name=f"{label}.setup_script.sha256",
    )
    setup_size = _validate_nonnegative_int(
        setup.get("size_bytes"),
        field_name=f"{label}.setup_script.size_bytes",
    )

    ref_bin = record.get("refmac5_binary")
    if not isinstance(ref_bin, Mapping):
        raise ValueError(f"{label}.refmac5_binary must be a JSON object")
    bin_disc_path = _validate_lexical_abs_path(
        ref_bin.get("discovered_path"),
        field_name=f"{label}.refmac5_binary.discovered_path",
    )
    bin_res_path = _validate_canonical_no_traversal_abs_path(
        ref_bin.get("resolved_path"),
        field_name=f"{label}.refmac5_binary.resolved_path",
    )
    bin_is_sym = ref_bin.get("is_symlink")
    if type(bin_is_sym) is not bool:
        raise ValueError(
            f"{label}.refmac5_binary.is_symlink must be a strict bool"
        )
    if bin_is_sym != (bin_disc_path != bin_res_path):
        raise ValueError(
            f"{label}.refmac5_binary.is_symlink ({bin_is_sym}) contradicts "
            f"discovered_path={bin_disc_path!r} vs resolved_path={bin_res_path!r}"
        )
    bin_within = ref_bin.get("within_prefix")
    if type(bin_within) is not bool or bin_within is not True:
        raise ValueError(
            f"{label}.refmac5_binary.within_prefix must be strict bool True"
        )
    if not Path(bin_res_path).is_relative_to(Path(prefix)):
        raise ValueError(
            f"{label}.refmac5_binary.resolved_path {bin_res_path!r} is outside "
            f"configured_installation_prefix {prefix!r}"
        )
    bin_exec = ref_bin.get("executable")
    if type(bin_exec) is not bool or bin_exec is not True:
        raise ValueError(
            f"{label}.refmac5_binary.executable must be strict bool True"
        )
    bin_sha = _validate_sha256_digest(
        ref_bin.get("sha256"),
        field_name=f"{label}.refmac5_binary.sha256",
    )
    bin_size = _validate_nonnegative_int(
        ref_bin.get("size_bytes"),
        field_name=f"{label}.refmac5_binary.size_bytes",
    )

    bound_cfg = record.get("bound_ccp4_configuration")
    if not isinstance(bound_cfg, Mapping) or len(bound_cfg) == 0:
        raise ValueError(
            f"{label}.bound_ccp4_configuration must be a non-empty JSON object"
        )
    clean_bound: dict[str, str] = {}
    for k, v in sorted(bound_cfg.items()):
        if type(k) is not str or not k or type(v) is not str or not v:
            raise ValueError(
                f"{label}.bound_ccp4_configuration entries must be non-empty str -> str"
            )
        clean_bound[k] = v

    return {
        "configured_installation_prefix": prefix,
        "setup_script": {
            "configured_path": setup_cfg_path,
            "resolved_path": setup_res_path,
            "is_symlink": setup_is_sym,
            "within_prefix": setup_within,
            "sha256": setup_sha,
            "size_bytes": setup_size,
        },
        "refmac5_binary": {
            "discovered_path": bin_disc_path,
            "resolved_path": bin_res_path,
            "is_symlink": bin_is_sym,
            "within_prefix": bin_within,
            "executable": bin_exec,
            "sha256": bin_sha,
            "size_bytes": bin_size,
        },
        "bound_ccp4_configuration": clean_bound,
    }


def _validate_inner_pin_resolved_path_dialect(
    obj: Any,
    *,
    field_name: str,
) -> tuple[str, str, str, int]:
    """Validate an inner file pin using the ``{path, resolved_path, sha256, size_bytes}`` dialect."""
    if not isinstance(obj, Mapping):
        raise ValueError(f"{field_name} must be an object")
    if any(type(k) is not str for k in obj.keys()):
        raise ValueError(f"{field_name} keys must be strings")
    required_keys = {"path", "resolved_path", "sha256", "size_bytes"}
    actual_keys = set(obj.keys())
    if not required_keys.issubset(actual_keys):
        missing_keys = sorted(required_keys - actual_keys)
        raise ValueError(
            f"{field_name} must contain required keys {sorted(required_keys)}, missing {missing_keys}"
        )
    path_str = _validate_lexical_abs_path(
        obj["path"], field_name=f"{field_name}.path"
    )
    resolved_str = _validate_canonical_no_traversal_abs_path(
        obj["resolved_path"], field_name=f"{field_name}.resolved_path"
    )
    if "resolved" in obj:
        if type(obj["resolved"]) is not str or obj["resolved"] != resolved_str:
            raise ValueError(
                f"{field_name}.resolved contradicts resolved_path: "
                f"{obj['resolved']!r} != {resolved_str!r}"
            )
    sha_str = _validate_sha256_digest(
        obj["sha256"], field_name=f"{field_name}.sha256"
    )
    size_int = _validate_nonnegative_int(
        obj["size_bytes"], field_name=f"{field_name}.size_bytes"
    )
    return path_str, resolved_str, sha_str, size_int


def _validate_inner_pin_resolved_dialect(
    obj: Any,
    *,
    field_name: str,
) -> tuple[str, str, str, int]:
    """Validate an inner file pin using the ``{path, resolved, sha256, size_bytes}`` dialect."""
    if not isinstance(obj, Mapping):
        raise ValueError(f"{field_name} must be an object")
    if any(type(k) is not str for k in obj.keys()):
        raise ValueError(f"{field_name} keys must be strings")
    required_keys = {"path", "resolved", "sha256", "size_bytes"}
    actual_keys = set(obj.keys())
    if not required_keys.issubset(actual_keys):
        missing_keys = sorted(required_keys - actual_keys)
        raise ValueError(
            f"{field_name} must contain required keys {sorted(required_keys)}, missing {missing_keys}"
        )
    path_str = _validate_lexical_abs_path(
        obj["path"], field_name=f"{field_name}.path"
    )
    resolved_str = _validate_canonical_no_traversal_abs_path(
        obj["resolved"], field_name=f"{field_name}.resolved"
    )
    if "resolved_path" in obj:
        if (
            type(obj["resolved_path"]) is not str
            or obj["resolved_path"] != resolved_str
        ):
            raise ValueError(
                f"{field_name}.resolved_path contradicts resolved: "
                f"{obj['resolved_path']!r} != {resolved_str!r}"
            )
    sha_str = _validate_sha256_digest(
        obj["sha256"], field_name=f"{field_name}.sha256"
    )
    size_int = _validate_nonnegative_int(
        obj["size_bytes"], field_name=f"{field_name}.size_bytes"
    )
    return path_str, resolved_str, sha_str, size_int


def _read_and_verify_role_json(
    role_obs: FileObservation,
    *,
    role_name: str,
    chunk_size: int = STREAM_CHUNK_BYTES,
) -> Mapping[str, Any]:
    """Load an inner receipt JSON file via :func:`_read_pinned_json` and verify observation consistency."""
    doc = _read_pinned_json(role_obs.as_file_pin(), chunk_size=chunk_size)
    if (
        doc.observation.identity_tuple != role_obs.identity_tuple
        or doc.observation.resolved_path != role_obs.resolved_path
        or doc.observation.symlinks != role_obs.symlinks
    ):
        raise ValueError(
            f"Inner receipt {role_name!r} at {role_obs.path!r} changed on disk during validation"
        )
    if not isinstance(doc.payload, Mapping):
        raise ValueError(
            f"Inner receipt {role_name!r} at {role_obs.path!r} must decode to a JSON object"
        )
    return doc.payload


def _validate_source_manifest_join(
    outer_manifest: _CheckedOuterManifest,
    files_by_id: Mapping[str, FileObservation],
    roots_by_name: Mapping[str, RootObservation],
    *,
    chunk_size: int = STREAM_CHUNK_BYTES,
) -> None:
    """Validate the scoped ``source_manifest`` inner receipt join."""
    sm_id = outer_manifest.roles["source_manifest"][0]
    sm_obs = files_by_id[sm_id]
    expected_sm_path = (
        f"{roots_by_name['prepared'].path}/refmac_diagnostic_source_manifest.json"
    )
    if sm_obs.path != expected_sm_path or sm_obs.resolved_path != expected_sm_path:
        raise ValueError(
            f"source_manifest must be at {expected_sm_path!r}, got {sm_obs.path!r}"
        )

    payload = _read_and_verify_role_json(
        sm_obs, role_name="source_manifest", chunk_size=chunk_size
    )
    if payload.get("schema_id") != SOURCE_MANIFEST_SCHEMA_ID:
        raise ValueError(
            f"source_manifest.schema_id must be {SOURCE_MANIFEST_SCHEMA_ID!r}, "
            f"got {payload.get('schema_id')!r}"
        )
    if "source_verification_status" in payload:
        if (
            type(payload["source_verification_status"]) is not str
            or payload["source_verification_status"]
            != SOURCE_MANIFEST_VERIFIED_STATUS
        ):
            raise ValueError(
                f"source_manifest.source_verification_status must be "
                f"{SOURCE_MANIFEST_VERIFIED_STATUS!r}, got {payload['source_verification_status']!r}"
            )
    upstream_src = payload.get("upstream_source")
    if not isinstance(upstream_src, Mapping):
        raise ValueError("source_manifest.upstream_source must be a JSON object")
    if upstream_src.get("expected_commit") != outer_manifest.upstream_commit:
        raise ValueError(
            "source_manifest.upstream_source.expected_commit must equal "
            f"{outer_manifest.upstream_commit!r}, got {upstream_src.get('expected_commit')!r}"
        )
    if upstream_src.get("expected_tag") != outer_manifest.upstream_tag:
        raise ValueError(
            "source_manifest.upstream_source.expected_tag must equal "
            f"{outer_manifest.upstream_tag!r}, got {upstream_src.get('expected_tag')!r}"
        )
    if (
        "git_commit" in upstream_src
        and upstream_src["git_commit"] != outer_manifest.upstream_commit
    ):
        raise ValueError(
            "source_manifest.upstream_source.git_commit must equal "
            f"{outer_manifest.upstream_commit!r}, got {upstream_src['git_commit']!r}"
        )
    if (
        "git_tag" in upstream_src
        and upstream_src["git_tag"] != outer_manifest.upstream_tag
    ):
        raise ValueError(
            "source_manifest.upstream_source.git_tag must equal "
            f"{outer_manifest.upstream_tag!r}, got {upstream_src['git_tag']!r}"
        )


def _validate_source_audit_join(
    outer_state: _CheckedOuterProfileState,
    files_by_id: Mapping[str, FileObservation],
    roots_by_name: Mapping[str, RootObservation],
    *,
    chunk_size: int = STREAM_CHUNK_BYTES,
) -> None:
    """Validate the scoped ``source_audit`` inner receipt join."""
    outer_manifest = outer_state.outer_manifest
    sa_id = outer_manifest.roles["source_audit"][0]
    sa_obs = files_by_id[sa_id]
    payload = _read_and_verify_role_json(
        sa_obs, role_name="source_audit", chunk_size=chunk_size
    )

    if payload.get("contract") != SOURCE_AUDIT_CONTRACT:
        raise ValueError(
            f"source_audit.contract must be {SOURCE_AUDIT_CONTRACT!r}, "
            f"got {payload.get('contract')!r}"
        )
    passed_val = payload.get("passed")
    if type(passed_val) is not bool or passed_val is not True:
        raise ValueError(
            f"source_audit.passed must be strict bool True, got {passed_val!r}"
        )
    if payload.get("source_root") != roots_by_name["vendor"].path:
        raise ValueError(
            f"source_audit.source_root must equal vendor root {roots_by_name['vendor'].path!r}, "
            f"got {payload.get('source_root')!r}"
        )
    if payload.get("prepared_root") != roots_by_name["prepared"].path:
        raise ValueError(
            f"source_audit.prepared_root must equal prepared root {roots_by_name['prepared'].path!r}, "
            f"got {payload.get('prepared_root')!r}"
        )
    if payload.get("upstream_commit") != outer_manifest.upstream_commit:
        raise ValueError(
            f"source_audit.upstream_commit must equal {outer_manifest.upstream_commit!r}, "
            f"got {payload.get('upstream_commit')!r}"
        )

    py_opt = payload.get("python_optimization")
    if type(py_opt) is not int or py_opt != 0:
        raise ValueError(
            f"source_audit.python_optimization must be non-boolean int 0, got {py_opt!r}"
        )
    lit_git = payload.get("literal_git_objects")
    if type(lit_git) is not bool or lit_git is not True:
        raise ValueError(
            f"source_audit.literal_git_objects must be strict bool True, got {lit_git!r}"
        )

    sm_obs = files_by_id[outer_manifest.roles["source_manifest"][0]]
    if payload.get("manifest_sha256") != sm_obs.sha256:
        raise ValueError(
            f"source_audit.manifest_sha256 mismatch: expected {sm_obs.sha256!r}, "
            f"got {payload.get('manifest_sha256')!r}"
        )

    auditor_obs = files_by_id[outer_manifest.roles["source_auditor"][0]]
    if payload.get("auditor_sha256") != auditor_obs.sha256:
        raise ValueError(
            f"source_audit.auditor_sha256 mismatch: expected {auditor_obs.sha256!r}, "
            f"got {payload.get('auditor_sha256')!r}"
        )
    if payload.get("auditor_path") != auditor_obs.path:
        raise ValueError(
            f"source_audit.auditor_path mismatch: expected {auditor_obs.path!r}, "
            f"got {payload.get('auditor_path')!r}"
        )

    prepared_member_pins = outer_state.observed_roots["prepared"].member_pins
    if "refmac_diagnostic_hooks.patch" not in prepared_member_pins:
        raise ValueError(
            "prepared root is missing required member 'refmac_diagnostic_hooks.patch'"
        )
    expected_patch_sha = prepared_member_pins[
        "refmac_diagnostic_hooks.patch"
    ].sha256
    if payload.get("patch_sha256") != expected_patch_sha:
        raise ValueError(
            f"source_audit.patch_sha256 mismatch: expected {expected_patch_sha!r}, "
            f"got {payload.get('patch_sha256')!r}"
        )

    interp_obs = files_by_id[outer_manifest.roles["source_audit_interpreter"][0]]
    i_path, i_res, i_sha, i_size = _validate_inner_pin_resolved_path_dialect(
        payload.get("interpreter"),
        field_name="source_audit.interpreter",
    )
    if (i_path, i_res, i_sha, i_size) != (
        interp_obs.path,
        interp_obs.resolved_path,
        interp_obs.sha256,
        interp_obs.size_bytes,
    ):
        raise ValueError(
            "source_audit.interpreter does not match roles['source_audit_interpreter']: "
            f"receipt={(i_path, i_res, i_sha, i_size)} vs "
            f"role={(interp_obs.path, interp_obs.resolved_path, interp_obs.sha256, interp_obs.size_bytes)}"
        )

    vendor_member_pins = outer_state.observed_roots["vendor"].member_pins
    orig_inv = payload.get("original_git_blob_inventory")
    if not isinstance(orig_inv, Mapping):
        raise ValueError(
            "source_audit.original_git_blob_inventory must be a JSON object"
        )
    if set(orig_inv.keys()) != set(vendor_member_pins.keys()):
        missing_v = sorted(set(vendor_member_pins.keys()) - set(orig_inv.keys()))
        extra_v = sorted(set(orig_inv.keys()) - set(vendor_member_pins.keys()))
        raise ValueError(
            f"source_audit.original_git_blob_inventory keys mismatch vendor root members: "
            f"missing={missing_v}, extra={extra_v}"
        )
    for rel_path, v_pin in sorted(vendor_member_pins.items()):
        row = orig_inv[rel_path]
        if not isinstance(row, Mapping):
            raise ValueError(
                f"source_audit.original_git_blob_inventory[{rel_path!r}] must be an object"
            )
        row_sha = _validate_sha256_digest(
            row.get("sha256"),
            field_name=f"source_audit.original_git_blob_inventory[{rel_path!r}].sha256",
        )
        row_size = _validate_nonnegative_int(
            row.get("size_bytes"),
            field_name=f"source_audit.original_git_blob_inventory[{rel_path!r}].size_bytes",
        )
        if row_sha != v_pin.sha256 or row_size != v_pin.size_bytes:
            raise ValueError(
                f"source_audit.original_git_blob_inventory[{rel_path!r}] pin mismatch: "
                f"receipt=({row_sha}, {row_size}) vs vendor=({v_pin.sha256}, {v_pin.size_bytes})"
            )

    prep_inv = payload.get("complete_prepared_inventory")
    if not isinstance(prep_inv, Mapping):
        raise ValueError(
            "source_audit.complete_prepared_inventory must be a JSON object"
        )
    if set(prep_inv.keys()) != set(prepared_member_pins.keys()):
        missing_p = sorted(set(prepared_member_pins.keys()) - set(prep_inv.keys()))
        extra_p = sorted(set(prep_inv.keys()) - set(prepared_member_pins.keys()))
        raise ValueError(
            f"source_audit.complete_prepared_inventory keys mismatch prepared root members: "
            f"missing={missing_p}, extra={extra_p}"
        )
    for rel_path, p_pin in sorted(prepared_member_pins.items()):
        row = prep_inv[rel_path]
        if not isinstance(row, Mapping):
            raise ValueError(
                f"source_audit.complete_prepared_inventory[{rel_path!r}] must be an object"
            )
        row_sha = _validate_sha256_digest(
            row.get("sha256"),
            field_name=f"source_audit.complete_prepared_inventory[{rel_path!r}].sha256",
        )
        row_size = _validate_nonnegative_int(
            row.get("size_bytes"),
            field_name=f"source_audit.complete_prepared_inventory[{rel_path!r}].size_bytes",
        )
        if row_sha != p_pin.sha256 or row_size != p_pin.size_bytes:
            raise ValueError(
                f"source_audit.complete_prepared_inventory[{rel_path!r}] pin mismatch: "
                f"receipt=({row_sha}, {row_size}) vs prepared=({p_pin.sha256}, {p_pin.size_bytes})"
            )


def _validate_build_receipt_join(
    outer_state: _CheckedOuterProfileState,
    files_by_id: Mapping[str, FileObservation],
    roots_by_name: Mapping[str, RootObservation],
    *,
    chunk_size: int = STREAM_CHUNK_BYTES,
) -> None:
    """Validate the scoped ``build_receipt`` inner receipt join."""
    outer_manifest = outer_state.outer_manifest
    br_id = outer_manifest.roles["build_receipt"][0]
    br_obs = files_by_id[br_id]
    expected_br_path = f"{roots_by_name['build'].path}/build-receipt.json"
    if br_obs.path != expected_br_path or br_obs.resolved_path != expected_br_path:
        raise ValueError(
            f"build_receipt must be at {expected_br_path!r}, got {br_obs.path!r}"
        )

    payload = _read_and_verify_role_json(
        br_obs, role_name="build_receipt", chunk_size=chunk_size
    )
    if payload.get("contract") != BUILD_RECEIPT_CONTRACT:
        raise ValueError(
            f"build_receipt.contract must be {BUILD_RECEIPT_CONTRACT!r}, "
            f"got {payload.get('contract')!r}"
        )
    passed_val = payload.get("passed")
    if type(passed_val) is not bool or passed_val is not True:
        raise ValueError(
            f"build_receipt.passed must be strict bool True, got {passed_val!r}"
        )
    if payload.get("source") != roots_by_name["prepared"].path:
        raise ValueError(
            f"build_receipt.source must equal prepared root {roots_by_name['prepared'].path!r}, "
            f"got {payload.get('source')!r}"
        )
    if payload.get("output") != roots_by_name["build"].path:
        raise ValueError(
            f"build_receipt.output must equal build root {roots_by_name['build'].path!r}, "
            f"got {payload.get('output')!r}"
        )

    exec_obj = payload.get("executable")
    if not isinstance(exec_obj, Mapping):
        raise ValueError("build_receipt.executable must be an object")
    if any(type(k) is not str for k in exec_obj.keys()):
        raise ValueError("build_receipt.executable keys must be strings")
    required_exec_keys = {"path", "sha256", "size_bytes"}
    if not required_exec_keys.issubset(exec_obj.keys()):
        missing_exec_keys = sorted(required_exec_keys - set(exec_obj.keys()))
        raise ValueError(
            "build_receipt.executable must contain required keys "
            f"{sorted(required_exec_keys)}, missing {missing_exec_keys}"
        )
    exec_path = _validate_lexical_abs_path(
        exec_obj["path"], field_name="build_receipt.executable.path"
    )
    exec_sha = _validate_sha256_digest(
        exec_obj["sha256"], field_name="build_receipt.executable.sha256"
    )
    exec_size = _validate_nonnegative_int(
        exec_obj["size_bytes"], field_name="build_receipt.executable.size_bytes"
    )
    diag_obs = files_by_id[outer_manifest.roles["diagnostic_executable"][0]]
    for alias_key in ("resolved_path", "resolved"):
        if alias_key in exec_obj:
            if (
                type(exec_obj[alias_key]) is not str
                or exec_obj[alias_key] != diag_obs.resolved_path
            ):
                raise ValueError(
                    f"build_receipt.executable.{alias_key} contradicts "
                    f"diagnostic_executable resolved_path: "
                    f"{exec_obj[alias_key]!r} != {diag_obs.resolved_path!r}"
                )
    if (exec_path, exec_sha, exec_size) != (
        diag_obs.path,
        diag_obs.sha256,
        diag_obs.size_bytes,
    ) or (exec_path, exec_sha, exec_size) != (
        outer_state.profile.executable.path,
        outer_state.profile.executable.sha256,
        outer_state.profile.executable.size_bytes,
    ):
        raise ValueError(
            "build_receipt.executable does not match diagnostic_executable and caller executable pin"
        )

    for role_name, receipt_sha_key in (
        ("build_driver", "driver_sha256"),
        ("build_journal", "journal_sha256"),
        ("build_runtime_config", "runtime_config_sha256"),
    ):
        orig_id, copy_id = outer_manifest.roles[role_name]
        orig_obs = files_by_id[orig_id]
        copy_obs = files_by_id[copy_id]
        receipt_sha = _validate_sha256_digest(
            payload.get(receipt_sha_key),
            field_name=f"build_receipt.{receipt_sha_key}",
        )
        if orig_obs.sha256 != copy_obs.sha256 or orig_obs.sha256 != receipt_sha:
            raise ValueError(
                f"build_receipt.{receipt_sha_key} ({receipt_sha}) does not match "
                f"{role_name} original ({orig_obs.sha256}) and copy ({copy_obs.sha256})"
            )
        if orig_obs.size_bytes != copy_obs.size_bytes:
            raise ValueError(
                f"{role_name} original and copy size_bytes mismatch"
            )

    linked_obs = files_by_id[outer_manifest.roles["linked_executable"][0]]
    linked_sha = _validate_sha256_digest(
        payload.get("linked_executable_sha256"),
        field_name="build_receipt.linked_executable_sha256",
    )
    if linked_sha != linked_obs.sha256:
        raise ValueError(
            f"build_receipt.linked_executable_sha256 ({linked_sha}) does not match "
            f"roles['linked_executable'] ({linked_obs.sha256})"
        )


def _validate_runtime_observation_join(
    outer_state: _CheckedOuterProfileState,
    files_by_id: Mapping[str, FileObservation],
    roots_by_name: Mapping[str, RootObservation],
    *,
    installed_record_projection: Mapping[str, Any],
    ccp4_env: Mapping[str, str],
    chunk_size: int = STREAM_CHUNK_BYTES,
) -> None:
    """Validate the scoped ``runtime_observation`` inner receipt join against ``installed_record`` and ``ccp4_env``."""
    outer_manifest = outer_state.outer_manifest
    rt_id = outer_manifest.roles["runtime_observation"][0]
    if outer_manifest.runtime_environment.observation_file_id != rt_id:
        raise ValueError(
            "runtime_environment.observation_file_id must equal roles['runtime_observation'][0]"
        )
    rt_obs = files_by_id[rt_id]
    payload = _read_and_verify_role_json(
        rt_obs, role_name="runtime_observation", chunk_size=chunk_size
    )

    if payload.get("contract") != RUNTIME_OBSERVATION_CONTRACT:
        raise ValueError(
            f"runtime_observation.contract must be {RUNTIME_OBSERVATION_CONTRACT!r}, "
            f"got {payload.get('contract')!r}"
        )

    sel_env = payload.get("selected_nonsecret_environment")
    if not isinstance(sel_env, Mapping):
        raise ValueError(
            "runtime_observation.selected_nonsecret_environment must be a JSON object"
        )
    if set(sel_env.keys()) != EXPECTED_RUNTIME_ENV_KEYS:
        missing_e = sorted(EXPECTED_RUNTIME_ENV_KEYS - set(sel_env.keys()))
        extra_e = sorted(set(sel_env.keys()) - EXPECTED_RUNTIME_ENV_KEYS)
        raise ValueError(
            f"runtime_observation.selected_nonsecret_environment keys mismatch: "
            f"missing={missing_e}, extra={extra_e}"
        )
    expected_outer_env = dict(outer_manifest.runtime_environment.expected_values)
    for k in sorted(EXPECTED_RUNTIME_ENV_KEYS):
        val = sel_env[k]
        if type(val) is not str or val != expected_outer_env[k]:
            raise ValueError(
                f"runtime_observation.selected_nonsecret_environment[{k!r}] mismatch: "
                f"receipt={val!r} vs outer_manifest={expected_outer_env[k]!r}"
            )
        if k not in ccp4_env or ccp4_env[k] != expected_outer_env[k]:
            raise ValueError(
                f"ccp4_env[{k!r}] mismatch: ccp4_env={ccp4_env.get(k)!r} vs "
                f"expected={expected_outer_env[k]!r}"
            )

    resolver_proj = _extract_installed_record_projection(
        payload.get("resolver_record"),
        label="runtime_observation.resolver_record",
    )
    if resolver_proj != installed_record_projection:
        raise ValueError(
            "runtime_observation.resolver_record projection does not match supplied installed_record"
        )

    prefix = resolver_proj["configured_installation_prefix"]
    for rname, robs in roots_by_name.items():
        if _paths_overlap(prefix, robs.path):
            raise ValueError(
                f"configured_installation_prefix {prefix!r} overlaps controlled root "
                f"{rname!r} ({robs.path!r})"
            )
    if outer_state.evidence_root is not None and _paths_overlap(
        prefix, outer_state.evidence_root
    ):
        raise ValueError(
            f"configured_installation_prefix {prefix!r} overlaps evidence_root "
            f"{outer_state.evidence_root!r}"
        )

    ccp4_setup_obs = files_by_id[outer_manifest.roles["ccp4_setup"][0]]
    setup_proj = resolver_proj["setup_script"]
    if (
        setup_proj["configured_path"]
        not in {ccp4_setup_obs.path, ccp4_setup_obs.resolved_path}
        or setup_proj["resolved_path"] != ccp4_setup_obs.resolved_path
        or setup_proj["sha256"] != ccp4_setup_obs.sha256
        or setup_proj["size_bytes"] != ccp4_setup_obs.size_bytes
    ):
        raise ValueError(
            "resolver_record.setup_script does not match roles['ccp4_setup']"
        )

    inst_ref_obs = files_by_id[outer_manifest.roles["installed_reference"][0]]
    diag_obs = files_by_id[outer_manifest.roles["diagnostic_executable"][0]]
    bin_proj = resolver_proj["refmac5_binary"]
    if (
        bin_proj["discovered_path"]
        not in {inst_ref_obs.path, inst_ref_obs.resolved_path}
        or bin_proj["resolved_path"] != inst_ref_obs.resolved_path
        or bin_proj["sha256"] != inst_ref_obs.sha256
        or bin_proj["size_bytes"] != inst_ref_obs.size_bytes
    ):
        raise ValueError(
            "resolver_record.refmac5_binary does not match roles['installed_reference']"
        )
    if (inst_ref_obs.mode & 0o111) == 0 or not os.access(
        inst_ref_obs.resolved_path, os.X_OK
    ):
        raise ValueError(
            f"installed_reference is not executable on disk: {inst_ref_obs.resolved_path!r}"
        )
    if (
        bin_proj["resolved_path"] == diag_obs.resolved_path
        or bin_proj["sha256"] == diag_obs.sha256
    ):
        raise ValueError(
            "resolver_record.refmac5_binary must differ from diagnostic_executable"
        )

    for cfg_k, cfg_v in resolver_proj["bound_ccp4_configuration"].items():
        if cfg_k not in sel_env or sel_env[cfg_k] != cfg_v:
            raise ValueError(
                f"resolver_record.bound_ccp4_configuration[{cfg_k!r}]={cfg_v!r} "
                f"disagrees with selected_nonsecret_environment ({sel_env.get(cfg_k)!r})"
            )

    rt_observer_obs = files_by_id[outer_manifest.roles["runtime_observer"][0]]
    o_path, o_res, o_sha, o_size = _validate_inner_pin_resolved_dialect(
        payload.get("observation_script"),
        field_name="runtime_observation.observation_script",
    )
    if (o_path, o_res, o_sha, o_size) != (
        rt_observer_obs.path,
        rt_observer_obs.resolved_path,
        rt_observer_obs.sha256,
        rt_observer_obs.size_bytes,
    ):
        raise ValueError(
            "runtime_observation.observation_script does not match roles['runtime_observer']"
        )

    files_by_lexical_path: dict[str, tuple[str, FileObservation]] = {
        fobs.path: (fid, fobs) for fid, fobs in files_by_id.items()
    }

    setup_source_files = payload.get("setup_source_files")
    if not isinstance(setup_source_files, (list, tuple)) or len(setup_source_files) == 0:
        raise ValueError(
            "runtime_observation.setup_source_files must be a non-empty list"
        )
    matched_setup_fids: set[str] = set()
    for idx, entry in enumerate(setup_source_files):
        s_path, s_res, s_sha, s_size = _validate_inner_pin_resolved_dialect(
            entry,
            field_name=f"runtime_observation.setup_source_files[{idx}]",
        )
        if s_path not in files_by_lexical_path:
            raise ValueError(
                f"runtime_observation.setup_source_files[{idx}] path {s_path!r} "
                "is not declared in outer manifest files"
            )
        fid, fobs = files_by_lexical_path[s_path]
        if (s_path, s_res, s_sha, s_size) != (
            fobs.path,
            fobs.resolved_path,
            fobs.sha256,
            fobs.size_bytes,
        ):
            raise ValueError(
                f"runtime_observation.setup_source_files[{idx}] pin mismatch against "
                f"outer file {fid!r} ({fobs.path!r})"
            )
        matched_setup_fids.add(fid)

    ccp4_setup_fid = outer_manifest.roles["ccp4_setup"][0]
    if ccp4_setup_fid not in matched_setup_fids:
        raise ValueError(
            "runtime_observation.setup_source_files does not include roles['ccp4_setup']"
        )
    expected_setup_deps = outer_manifest.roles["ccp4_setup_dependencies"]
    actual_setup_deps = tuple(sorted(matched_setup_fids - {ccp4_setup_fid}))
    if actual_setup_deps != expected_setup_deps:
        raise ValueError(
            "runtime_observation.setup_source_files unique IDs minus ccp4_setup "
            f"({actual_setup_deps}) do not equal roles['ccp4_setup_dependencies'] "
            f"({expected_setup_deps})"
        )

    load_cmds = payload.get("static_library_load_commands")
    if not isinstance(load_cmds, (list, tuple)) or len(load_cmds) == 0:
        raise ValueError(
            "runtime_observation.static_library_load_commands must be a non-empty list"
        )
    matched_lib_fids: set[str] = set()
    for idx, cmd in enumerate(load_cmds):
        if not isinstance(cmd, Mapping) or "library" not in cmd:
            raise ValueError(
                f"runtime_observation.static_library_load_commands[{idx}] must contain 'library'"
            )
        l_path, l_res, l_sha, l_size = _validate_inner_pin_resolved_dialect(
            cmd["library"],
            field_name=f"runtime_observation.static_library_load_commands[{idx}].library",
        )
        if l_path not in files_by_lexical_path:
            raise ValueError(
                f"runtime_observation.static_library_load_commands[{idx}].library path "
                f"{l_path!r} is not declared in outer manifest files"
            )
        fid, fobs = files_by_lexical_path[l_path]
        if (l_path, l_res, l_sha, l_size) != (
            fobs.path,
            fobs.resolved_path,
            fobs.sha256,
            fobs.size_bytes,
        ):
            raise ValueError(
                f"runtime_observation.static_library_load_commands[{idx}].library pin mismatch "
                f"against outer file {fid!r} ({fobs.path!r})"
            )
        matched_lib_fids.add(fid)

    expected_rt_images = outer_manifest.roles["runtime_images"]
    actual_rt_images = tuple(sorted(matched_lib_fids))
    if actual_rt_images != expected_rt_images:
        raise ValueError(
            "runtime_observation.static_library_load_commands library IDs "
            f"({actual_rt_images}) do not equal roles['runtime_images'] "
            f"({expected_rt_images})"
        )


def validate_profile(
    profile: RefmacDiagnosticProfile,
    installed_record: Mapping[str, Any],
    ccp4_env: Mapping[str, str],
    evidence_root: Path | str,
    *,
    chunk_size: int = STREAM_CHUNK_BYTES,
) -> ValidatedProfile:
    """Validate outer profile, on-disk files/roots, inner receipts, ``installed_record``, and ``ccp4_env``.

    Returns a deeply immutable :class:`ValidatedProfile` on success or raises
    :class:`ProfileValidationError` (a :class:`ValueError` subclass) retaining all
    obtainable :class:`FileObservation` and :class:`RootObservation` records on failure.
    """
    # Detach-snapshot installed_record and ccp4_env immediately so caller mutations
    # during or after validation cannot affect validated state.
    installed_record_json: str | None = None
    detached_installed_record: Mapping[str, Any] | None = None
    installed_record_err: Exception | None = None
    try:
        installed_record_json, detached_installed_record = (
            _serialize_detached_installed_record(installed_record)
        )
    except ValueError as exc:
        installed_record_err = exc

    detached_ccp4_env: dict[str, Any] | None = (
        dict(ccp4_env) if isinstance(ccp4_env, Mapping) else None
    )

    if type(profile) is not RefmacDiagnosticProfile:
        raise ProfileValidationError(
            f"profile must be a RefmacDiagnosticProfile, got {type(profile).__name__}",
            failed_check="request_shape",
            request=None,
            installed_record_json=installed_record_json,
        )
    if type(chunk_size) is not int or chunk_size <= 0:
        raise ProfileValidationError(
            f"chunk_size must be a positive non-boolean int, got {chunk_size!r}",
            failed_check="request_shape",
            request=profile,
            installed_record_json=installed_record_json,
        )

    if evidence_root is None:
        ev_arg_for_outer: str | os.PathLike[str] | None = None
    else:
        ev_arg_for_outer = evidence_root

    try:
        outer_state = _validate_and_observe_outer_profile(
            profile,
            evidence_root=ev_arg_for_outer,
            chunk_size=chunk_size,
        )
    except _ProfileObservationError as exc:
        partial = exc.partial_observation
        manifest_obs_public: (
            FileObservation | PartialFileReadObservation | None
        ) = partial.manifest_file_observation
        if manifest_obs_public is None:
            if partial.manifest_observation is not None:
                manifest_obs_public = _build_file_observation(
                    partial.manifest_observation,
                    observed_ancestors=partial.observed_ancestors,
                    observed_symlinks=partial.observed_symlinks,
                    file_dependencies=partial.manifest_dependencies,
                    verified=False,
                )
            elif partial.partial_manifest_observation is not None:
                manifest_obs_public = partial.partial_manifest_observation
        merged_files_public: dict[
            str, FileObservation | PartialFileReadObservation
        ] = {}
        if partial.file_observations:
            merged_files_public.update(partial.file_observations)
        else:
            for fid, fobs in sorted(partial.observed_files.items()):
                merged_files_public[fid] = _build_file_observation(
                    fobs,
                    observed_ancestors=partial.observed_ancestors,
                    observed_symlinks=partial.observed_symlinks,
                    file_dependencies=partial.file_dependencies.get(fid),
                    verified=(fid in partial.verified_files),
                )
        for fid, pobs in sorted(partial.partial_files.items()):
            merged_files_public.setdefault(fid, pobs)
        partial_files_public = tuple(sorted(merged_files_public.items()))
        partial_roots_public = tuple(
            (
                rname,
                _build_root_observation(rinv, partial.outer_manifest),
            )
            for rname, rinv in sorted(partial.observed_roots.items())
        )
        partial_roles: tuple[tuple[str, tuple[str, ...]], ...] = ()
        partial_expected_env: tuple[tuple[str, str], ...] = ()
        partial_absences: tuple[str, ...] = EXPECTED_RUNTIME_ABSENT_KEYS
        partial_inst_ref: FilePin | None = None
        if partial.outer_manifest is not None:
            partial_roles = tuple(
                (rname, tuple(rids))
                for rname, rids in sorted(partial.outer_manifest.roles.items())
            )
            partial_expected_env = tuple(
                sorted(
                    partial.outer_manifest.runtime_environment.expected_values.items()
                )
            )
            partial_absences = (
                partial.outer_manifest.runtime_environment.expected_absent
            )
            ref_id = partial.outer_manifest.roles["installed_reference"][0]
            if ref_id in partial.observed_files:
                partial_inst_ref = partial.observed_files[ref_id].as_file_pin()

        raise ProfileValidationError(
            str(exc),
            failed_check=exc.failed_check,
            request=profile,
            manifest_identity=manifest_obs_public,
            files=partial_files_public,
            roots=partial_roots_public,
            roles=partial_roles,
            installed_reference=partial_inst_ref,
            installed_record_json=installed_record_json,
            expected_environment=partial_expected_env,
            requested_absences=partial_absences,
            evidence_root=partial.evidence_root,
            cause_exception=exc,
            errors=exc.errors,
            error_records=exc.error_records,
            partial_observation=partial,
        ) from exc

    manifest_identity = outer_state.manifest_file_observation or _build_file_observation(
        outer_state.manifest_observation,
        observed_ancestors=outer_state.observed_ancestors,
        observed_symlinks=outer_state.observed_symlinks,
        file_dependencies=outer_state.manifest_dependencies,
        verified=True,
    )
    if outer_state.file_observations:
        files_by_id: dict[str, FileObservation] = dict(
            sorted(outer_state.file_observations.items())
        )
    else:
        files_by_id = {
            fid: _build_file_observation(
                fobs,
                observed_ancestors=outer_state.observed_ancestors,
                observed_symlinks=outer_state.observed_symlinks,
                file_dependencies=outer_state.file_dependencies.get(fid),
                verified=True,
            )
            for fid, fobs in sorted(outer_state.observed_files.items())
        }
    roots_by_name: dict[str, RootObservation] = {
        rname: _build_root_observation(rinv, outer_state.outer_manifest)
        for rname, rinv in sorted(outer_state.observed_roots.items())
    }
    files_tuple = tuple(sorted(files_by_id.items()))
    roots_tuple = tuple(
        (rname, roots_by_name[rname]) for rname in EXPECTED_ROOT_NAMES
    )
    roles_tuple = tuple(
        (rname, tuple(rids))
        for rname, rids in sorted(outer_state.outer_manifest.roles.items())
    )
    expected_env_tuple = tuple(
        sorted(
            outer_state.outer_manifest.runtime_environment.expected_values.items()
        )
    )
    requested_absences = (
        outer_state.outer_manifest.runtime_environment.expected_absent
    )
    inst_ref_id = outer_state.outer_manifest.roles["installed_reference"][0]
    installed_reference_pin = files_by_id[inst_ref_id].as_file_pin()

    def _raise_post_outer_failure(
        exc: Exception, *, failed_check: str
    ) -> ProfileValidationError:
        rec = _RecordedObservationError(
            stage=failed_check,
            message=str(exc),
            exception=exc,
        )
        return ProfileValidationError(
            str(exc),
            failed_check=failed_check,
            request=profile,
            manifest_identity=manifest_identity,
            files=files_tuple,
            roots=roots_tuple,
            roles=roles_tuple,
            installed_reference=installed_reference_pin,
            installed_record_json=installed_record_json,
            expected_environment=expected_env_tuple,
            requested_absences=requested_absences,
            evidence_root=outer_state.evidence_root,
            cause_exception=exc,
            errors=(str(exc),),
            error_records=(rec,),
        )

    if outer_state.evidence_root is None:
        err = ValueError("evidence_root must be a non-empty canonical path")
        raise _raise_post_outer_failure(err, failed_check="evidence_root")

    if installed_record_err is not None or detached_installed_record is None or installed_record_json is None:
        err = installed_record_err or ValueError("installed_record is missing")
        raise _raise_post_outer_failure(
            err, failed_check="installed_record"
        ) from installed_record_err

    try:
        installed_proj = _extract_installed_record_projection(
            detached_installed_record,
            label="installed_record",
        )
    except ValueError as exc:
        raise _raise_post_outer_failure(
            exc, failed_check="installed_record"
        ) from exc

    try:
        if detached_ccp4_env is None:
            raise ValueError(
                f"ccp4_env must be a Mapping, got {type(ccp4_env).__name__}"
            )
        reject_conflicting_environment(detached_ccp4_env)
        for absent_key in requested_absences:
            if absent_key in detached_ccp4_env:
                raise ValueError(
                    f"ccp4_env must not contain expected_absent variable {absent_key!r}"
                )
        for exp_k, exp_v in expected_env_tuple:
            if exp_k not in detached_ccp4_env:
                raise ValueError(
                    f"ccp4_env is missing required variable {exp_k!r}"
                )
            if detached_ccp4_env[exp_k] != exp_v:
                raise ValueError(
                    f"ccp4_env[{exp_k!r}] mismatch: expected {exp_v!r}, "
                    f"got {detached_ccp4_env[exp_k]!r}"
                )
    except ValueError as exc:
        raise _raise_post_outer_failure(exc, failed_check="ccp4_env") from exc

    try:
        _validate_source_manifest_join(
            outer_state.outer_manifest,
            files_by_id,
            roots_by_name,
            chunk_size=chunk_size,
        )
    except ValueError as exc:
        raise _raise_post_outer_failure(
            exc, failed_check="source_manifest_join"
        ) from exc

    try:
        _validate_source_audit_join(
            outer_state,
            files_by_id,
            roots_by_name,
            chunk_size=chunk_size,
        )
    except ValueError as exc:
        raise _raise_post_outer_failure(
            exc, failed_check="source_audit_join"
        ) from exc

    try:
        _validate_build_receipt_join(
            outer_state,
            files_by_id,
            roots_by_name,
            chunk_size=chunk_size,
        )
    except ValueError as exc:
        raise _raise_post_outer_failure(
            exc, failed_check="build_receipt_join"
        ) from exc

    try:
        _validate_runtime_observation_join(
            outer_state,
            files_by_id,
            roots_by_name,
            installed_record_projection=installed_proj,
            ccp4_env=detached_ccp4_env,
            chunk_size=chunk_size,
        )
    except ValueError as exc:
        raise _raise_post_outer_failure(
            exc, failed_check="runtime_observation_join"
        ) from exc

    return ValidatedProfile(
        request=profile,
        manifest_identity=manifest_identity,
        files=files_tuple,
        roots=roots_tuple,
        roles=roles_tuple,
        installed_reference=installed_reference_pin,
        selected_executable=profile.executable,
        installed_record_json=installed_record_json,
        expected_environment=expected_env_tuple,
        requested_absences=requested_absences,
        evidence_root=outer_state.evidence_root,
        _outer_state=outer_state,
    )
