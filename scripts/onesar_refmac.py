#!/usr/bin/env python3
"""CCP4 REFMAC5 zero-cycle (`NCYC 0`) R-factor collector and native output auditor for 1SAR.

Implementation scope (Tasks 163 & 165):
- Stages hash-verified 1SAR subject inputs once via :func:`onesar_rerun.stage_subject_inputs`
  under a fresh repository-local evidence root.
- Hashes all staged immutable inputs (including ``input_admission.json``) and
  all 6 helper/source modules into an in-memory baseline before launching REFMAC5,
  and re-verifies them after child execution across both success and failure paths.
- Resolves the configured ``CCP4_SETUP`` script realpath and SHA-256, loads the
  CCP4 environment once via :func:`toolchain.ccp4_environment` with explicit
  ``setup_path``, copies the returned mapping, resolves the absolute ``refmac5``
  binary from that mapping's ``PATH``, verifies it is a regular executable file
  inside the configured CCP4 installation prefix, and records only resolved
  binary/setup file identities and non-secret CCP4 configuration keys.
- Invokes :func:`toolchain.run_refmac` (or an injected ``runner`` with the same
  wrapper signature) using the exact preregistered 7-line ``NCYC 0`` keyword
  block, explicit ``env``, ``executable``, ``xml_output``, and ``ccp4=False``.
- Retains raw execution metadata, created raw outputs and their SHA-256 digests
  (without following escaped or unexpected symlinks), and parses the on-disk
  combined log via :func:`onesar_refmac_log.parse_refmac_log`.
- Exports and audits optional ``XMLOUT`` (``refmac_xmlout_audit.json``), raw and
  one-to-one ``HKLOUT`` MTZ observations/flags/populations/``FC_ALL_LS``
  (``refmac_hklout_raw_export.json`` and ``refmac_hklout_audit.json``), and
  supplemented ``XYZOUT`` PDB coordinates/B-factors/H-D/ANISOU records
  (``refmac_xyzout_audit.json``).
- Persists deterministic parsed-log, output-audit, diagnostics, and
  operation-manifest JSON files before raising on any preflight, execution,
  output, parse, audit, or input-immutability failure.
"""

from __future__ import annotations

import copy
import datetime as dt
import errno
import hashlib
import json
import math
import os
import re
import shutil
import stat
import struct
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import audit_1sar_retained_evidence  # noqa: E402
import onesar_refmac_log  # noqa: E402
import onesar_rerun  # noqa: E402
import t03_reflection_retention  # noqa: E402
import toolchain  # noqa: E402


REPO_ROOT = _SCRIPTS_DIR.parent

COLLECTOR_STAGE = "stage2_invocation_raw_retention_log_parse_and_output_audits"

REFMAC_KEYWORDS_LINES: tuple[str, ...] = (
    "LABIN FP=F-obs SIGFP=SIGF-obs FREE=R-free-flags",
    "FREE 1",
    "REFI BREF MIXED",
    "NCYC 0",
    "MONI MANY",
    "LABOUT FC=FC PHIC=PHIC FWT=FWT PHWT=PHWT DELFWT=DELFWT PHDELWT=PHDELWT FOM=FOM",
    "END",
)
REFMAC_KEYWORDS: str = "\n".join(REFMAC_KEYWORDS_LINES) + "\n"

EXPECTED_REQUESTED_NCYC: int = 0
EXPECTED_FREE_FLAG_VALUE: int = 1
PRESELECTED_NATIVE_LS_FC_COLUMN: str = "FC_ALL_LS"
FORBIDDEN_FALLBACK_FC_COLUMNS: tuple[str, str] = ("FC", "FC_ALL")
MTZ_WORD_HEX_CONVENTION: str = "uint32_le_hex_8char"
HKLOUT_OBSERVATION_ROLE_TO_LABEL: Mapping[str, str] = MappingProxyType(
    {
        "FP": "F-obs",
        "SIGFP": "SIGF-obs",
        "FREE": "R-free-flags",
    }
)
HKLOUT_OBSERVATION_LABELS: tuple[str, str, str] = (
    HKLOUT_OBSERVATION_ROLE_TO_LABEL["FP"],
    HKLOUT_OBSERVATION_ROLE_TO_LABEL["SIGFP"],
    HKLOUT_OBSERVATION_ROLE_TO_LABEL["FREE"],
)

NON_SECRET_CCP4_ENV_KEYS: tuple[str, ...] = (
    "CCP4_MASTER",
    "CCP4",
    "CBIN",
    "CLIB",
    "CLIBD",
    "CLIBD_MON",
    "CINCL",
)

REQUIRED_RAW_OUTPUT_KEYS: tuple[str, ...] = (
    "log",
    "xyzout",
    "hklout",
)

UNPROVEN_GATE_REASONS: dict[str, str] = {
    "effective_hkls_proven": (
        "Unproven in Stage 1 partial collector: raw XMLOUT/HKLOUT retained only; "
        "effective HKL retention and observation eligibility audit not yet implemented."
    ),
    "native_bin_membership_proven": (
        "Unproven in Stage 1 partial collector: parsed log resolution bins retained only; "
        "independent HKL-to-bin membership audit not yet implemented."
    ),
    "native_residual_reconstruction_proven": (
        "Unproven in Stage 1 partial collector: raw HKLOUT retained only; "
        "independent structure-factor residual reconstruction audit not yet implemented."
    ),
    "model_preservation_proven": (
        "Unproven in Stage 1 partial collector: raw XYZOUT retained only; "
        "independent coordinate/occupancy/B-factor/atom preservation audit not yet implemented."
    ),
}

_LOG_BANNER_RE = re.compile(
    r"###\s*(CCP4\s+\S+)\s*:\s*(Refmac_\S+)\s+version\s+(\S+)\s*:"
)
_LOG_RUN_DATE_RE = re.compile(
    r"Run date:\s*(\d{1,2}/\s*\d{1,2}/\d{4})(?:\s+Run time:\s*(\S+))?"
)
_LOG_DATA_LINE_RE = re.compile(r"^\s*Data line---\s*(.*)$")
_LOG_DATA_NCYC_RE = re.compile(r"^\s*Data line---\s+NCYC\s+(\S+)(?:\s+(.*))?$")
_LOG_REFINEMENT_CYCLES_RE = re.compile(
    r"^\s*Refinement cycles\s*:\s*(\S+)(?:\s+(.*))?$"
)
_LOG_END_OF_REFMAC_RE = re.compile(r"^\s*REFMAC5?\s*:\s*End of Refmac_\S+\s*.*$")
_LOG_NORMAL_TERMINATION_RE = re.compile(
    r"^\s*(?:Refmac_\S+:\s*Normal termination|Normal termination)\b.*$",
    re.IGNORECASE,
)
_LOG_TIMES_RE = re.compile(r"^\s*Times:\s*User:\s*.*$")
_LOG_WARNING_RE = re.compile(
    r"(?:^\s*===>\s*Warning\b|\bWARNING\s*:|\bWarning\s*:)",
    re.IGNORECASE,
)
_LOG_ERROR_RE = re.compile(
    r"(?:^\s*===>\s*Error\b|\bFATAL ERROR\b|\bError\s*:\s*)",
    re.IGNORECASE,
)


class RefmacCollectorError(RuntimeError):
    """Raised when the REFMAC5 collector fails any preflight, execution, or verification check."""

    def __init__(
        self,
        message: str,
        *,
        failed_stage: str,
        manifest_path: Path | None = None,
        diagnostics_path: Path | None = None,
        returncode: int | None = None,
        manifest_payload: dict[str, Any] | None = None,
        diagnostics_payload: dict[str, Any] | None = None,
        unpersisted_reason: str | None = None,
        primary_cause: Exception | None = None,
        terminal_cause: Exception | None = None,
        publication_history: list[dict[str, Any]] | None = None,
        publication_pair_complete: bool | None = None,
        publication_terminal_failure: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.failed_stage = failed_stage
        self.manifest_path = manifest_path
        self.diagnostics_path = diagnostics_path
        self.returncode = returncode
        self.manifest_payload = manifest_payload
        self.diagnostics_payload = diagnostics_payload
        self.unpersisted_reason = unpersisted_reason
        self.primary_cause = primary_cause
        self.terminal_cause = terminal_cause
        self.publication_history = (
            list(publication_history) if publication_history is not None else []
        )
        self.publication_pair_complete = publication_pair_complete
        self.publication_terminal_failure = publication_terminal_failure


def _utc_timestamp_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_regular_file(path: Path) -> str:
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise ValueError(f"Regular non-symlink file required: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ensure_no_symlink_components_under_root(
    path: Path,
    root: Path,
    *,
    check_leaf: bool = True,
) -> None:
    """Verify ``path`` is lexically inside ``root`` and has no symlinked intermediate components."""
    normalized_root = Path(os.path.abspath(os.fspath(root)))
    try:
        root_st = os.lstat(normalized_root)
    except OSError as exc:
        raise ValueError(
            f"Evidence root directory cannot be inspected at {normalized_root} "
            f"({type(exc).__name__}): {exc}"
        ) from exc
    if stat.S_ISLNK(root_st.st_mode):
        raise ValueError(
            f"Symlink component rejected at root directory: {normalized_root}"
        )
    if not stat.S_ISDIR(root_st.st_mode):
        raise ValueError(
            f"Root component is not a directory: {normalized_root}"
        )
    resolved_root = normalized_root.resolve(strict=True)
    normalized_path = Path(os.path.abspath(os.fspath(path)))
    if normalized_path == resolved_root or not normalized_path.is_relative_to(resolved_root):
        raise ValueError(f"Path {path} is not a strict descendant of {resolved_root}")
    current = resolved_root
    rel_parts = normalized_path.relative_to(resolved_root).parts
    for index, part in enumerate(rel_parts):
        current = current / part
        is_last = index == len(rel_parts) - 1
        if is_last and not check_leaf:
            continue
        try:
            st = os.lstat(current)
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(st.st_mode):
            raise ValueError(f"Symlink component rejected under evidence root: {current}")
        if not is_last and not stat.S_ISDIR(st.st_mode):
            raise ValueError(f"Ancestor component is not a directory: {current}")


def _capture_directory_identity_baseline(
    directory: Path,
    *,
    evidence_root: Path | None = None,
) -> dict[str, Any]:
    """Capture pre-launch directory identity without following a symlink at the directory or root."""
    normalized_dir = Path(os.path.abspath(os.fspath(directory)))
    st = os.lstat(normalized_dir)
    if stat.S_ISLNK(st.st_mode):
        raise ValueError(f"Refusing symlink directory baseline: {normalized_dir}")
    if not stat.S_ISDIR(st.st_mode):
        raise ValueError(f"Refusing non-directory baseline: {normalized_dir}")
    resolved_dir = normalized_dir.resolve(strict=True)
    record: dict[str, Any] = {
        "path": str(normalized_dir),
        "resolved_path": str(resolved_dir),
        "dev": int(st.st_dev),
        "ino": int(st.st_ino),
        "mode": int(stat.S_IMODE(st.st_mode)),
        "uid": int(st.st_uid),
    }
    if evidence_root is not None:
        normalized_root = Path(os.path.abspath(os.fspath(evidence_root)))
        root_st = os.lstat(normalized_root)
        if stat.S_ISLNK(root_st.st_mode):
            raise ValueError(
                f"Refusing symlink evidence root baseline: {normalized_root}"
            )
        if not stat.S_ISDIR(root_st.st_mode):
            raise ValueError(
                f"Refusing non-directory evidence root baseline: {normalized_root}"
            )
        resolved_root = normalized_root.resolve(strict=True)
        record["evidence_root"] = str(normalized_root)
        record["evidence_root_resolved_path"] = str(resolved_root)
        record["evidence_root_dev"] = int(root_st.st_dev)
        record["evidence_root_ino"] = int(root_st.st_ino)
        record["evidence_root_mode"] = int(stat.S_IMODE(root_st.st_mode))
    return record


def _build_file_ancestor_chain_baseline(
    file_path: Path,
    *,
    evidence_root: Path,
) -> dict[str, Any]:
    """Capture pre-launch (dev, ino) and resolved_path for ``evidence_root``, intermediate dirs, and ``file_path``."""
    normalized_root = Path(os.path.abspath(os.fspath(evidence_root)))
    normalized_file = Path(os.path.abspath(os.fspath(file_path)))
    root_st = os.lstat(normalized_root)
    if stat.S_ISLNK(root_st.st_mode) or not stat.S_ISDIR(root_st.st_mode):
        raise ValueError(
            f"Admitted evidence root is not a non-symlink directory: {normalized_root}"
        )
    resolved_root = normalized_root.resolve(strict=True)
    if normalized_file == normalized_root or not normalized_file.is_relative_to(
        normalized_root
    ):
        raise ValueError(
            f"File {normalized_file} is not a strict descendant of {normalized_root}"
        )

    ancestor_chain: list[dict[str, Any]] = [
        {
            "path": str(normalized_root),
            "resolved_path": str(resolved_root),
            "dev": int(root_st.st_dev),
            "ino": int(root_st.st_ino),
            "mode": int(stat.S_IMODE(root_st.st_mode)),
        }
    ]
    current = normalized_root
    rel_parts = normalized_file.relative_to(normalized_root).parts
    for part in rel_parts[:-1]:
        current = current / part
        anc_st = os.lstat(current)
        if stat.S_ISLNK(anc_st.st_mode) or not stat.S_ISDIR(anc_st.st_mode):
            raise ValueError(
                f"Admitted ancestor component is not a non-symlink directory: {current}"
            )
        ancestor_chain.append(
            {
                "path": str(current),
                "resolved_path": str(current.resolve(strict=True)),
                "dev": int(anc_st.st_dev),
                "ino": int(anc_st.st_ino),
                "mode": int(stat.S_IMODE(anc_st.st_mode)),
            }
        )

    leaf_st = os.lstat(normalized_file)
    if stat.S_ISLNK(leaf_st.st_mode) or not stat.S_ISREG(leaf_st.st_mode):
        raise ValueError(
            f"Admitted baseline file is not a regular non-symlink file: {normalized_file}"
        )
    parent_entry = ancestor_chain[-1]
    return {
        "resolved_path": str(normalized_file.resolve(strict=True)),
        "dev": int(leaf_st.st_dev),
        "ino": int(leaf_st.st_ino),
        "parent_dir_path": parent_entry["path"],
        "parent_dir_resolved_path": parent_entry["resolved_path"],
        "parent_dir_dev": parent_entry["dev"],
        "parent_dir_ino": parent_entry["ino"],
        "evidence_root_path": ancestor_chain[0]["path"],
        "evidence_root_resolved_path": ancestor_chain[0]["resolved_path"],
        "evidence_root_dev": ancestor_chain[0]["dev"],
        "evidence_root_ino": ancestor_chain[0]["ino"],
        "ancestor_chain_baseline": ancestor_chain,
    }


def _verify_admitted_ancestor_chain(
    target_path: Path,
    expected_baseline: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate that all ancestor directories of ``target_path`` remain non-symlink directories with admitted (dev, ino)."""
    normalized_target = Path(os.path.abspath(os.fspath(target_path)))
    raw_chain = expected_baseline.get("ancestor_chain_baseline")
    if isinstance(raw_chain, list) and raw_chain:
        expected_chain: list[dict[str, Any]] = [
            dict(item) for item in raw_chain if isinstance(item, Mapping)
        ]
    else:
        parent_dir = normalized_target.parent
        expected_chain = []
        if expected_baseline.get("evidence_root_path") is not None:
            expected_chain.append(
                {
                    "path": str(expected_baseline["evidence_root_path"]),
                    "resolved_path": expected_baseline.get(
                        "evidence_root_resolved_path"
                    ),
                    "dev": expected_baseline.get("evidence_root_dev"),
                    "ino": expected_baseline.get("evidence_root_ino"),
                }
            )
        elif parent_dir.parent != parent_dir:
            expected_chain.append(
                {
                    "path": str(parent_dir.parent),
                    "resolved_path": None,
                    "dev": None,
                    "ino": None,
                }
            )
        expected_chain.append(
            {
                "path": str(expected_baseline.get("parent_dir_path") or parent_dir),
                "resolved_path": expected_baseline.get("parent_dir_resolved_path"),
                "dev": expected_baseline.get("parent_dir_dev"),
                "ino": expected_baseline.get("parent_dir_ino"),
            }
        )

    verified_ancestors: list[dict[str, Any]] = []
    for anc_expected in expected_chain:
        anc_path = Path(str(anc_expected["path"]))
        exp_dev = anc_expected.get("dev")
        exp_ino = anc_expected.get("ino")
        exp_resolved = anc_expected.get("resolved_path")
        try:
            anc_st = os.lstat(anc_path)
        except OSError as exc:
            return {
                "verified": False,
                "damaged_ancestor_path": str(anc_path),
                "damaged_ancestor_exists": False,
                "damaged_ancestor_is_symlink": False,
                "damaged_ancestor_is_directory": False,
                "damaged_ancestor_symlink_target": None,
                "expected_ancestor_dev": exp_dev,
                "expected_ancestor_ino": exp_ino,
                "expected_ancestor_resolved_path": exp_resolved,
                "observed_ancestor_dev": None,
                "observed_ancestor_ino": None,
                "error": (
                    f"Ancestor directory missing or unreadable at {anc_path} "
                    f"({type(exc).__name__}): {exc}"
                ),
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
                "errno": getattr(exc, "errno", None),
                "exception": exc,
                "verified_ancestors": verified_ancestors,
            }

        obs_dev = int(anc_st.st_dev)
        obs_ino = int(anc_st.st_ino)
        is_symlink = bool(stat.S_ISLNK(anc_st.st_mode))
        is_dir = bool(stat.S_ISDIR(anc_st.st_mode))

        if is_symlink:
            try:
                symlink_target = os.readlink(anc_path)
            except OSError:
                symlink_target = None
            err_msg = (
                f"Ancestor directory was replaced by a symlink: {anc_path}"
                + (f" -> {symlink_target!r}" if symlink_target is not None else "")
            )
            return {
                "verified": False,
                "damaged_ancestor_path": str(anc_path),
                "damaged_ancestor_exists": True,
                "damaged_ancestor_is_symlink": True,
                "damaged_ancestor_is_directory": False,
                "damaged_ancestor_symlink_target": symlink_target,
                "expected_ancestor_dev": exp_dev,
                "expected_ancestor_ino": exp_ino,
                "expected_ancestor_resolved_path": exp_resolved,
                "observed_ancestor_dev": obs_dev,
                "observed_ancestor_ino": obs_ino,
                "error": err_msg,
                "exception_type": "ValueError",
                "exception_message": err_msg,
                "errno": None,
                "exception": ValueError(err_msg),
                "verified_ancestors": verified_ancestors,
            }

        if not is_dir:
            err_msg = f"Ancestor path is no longer a directory: {anc_path}"
            return {
                "verified": False,
                "damaged_ancestor_path": str(anc_path),
                "damaged_ancestor_exists": True,
                "damaged_ancestor_is_symlink": False,
                "damaged_ancestor_is_directory": False,
                "damaged_ancestor_symlink_target": None,
                "expected_ancestor_dev": exp_dev,
                "expected_ancestor_ino": exp_ino,
                "expected_ancestor_resolved_path": exp_resolved,
                "observed_ancestor_dev": obs_dev,
                "observed_ancestor_ino": obs_ino,
                "error": err_msg,
                "exception_type": "ValueError",
                "exception_message": err_msg,
                "errno": None,
                "exception": ValueError(err_msg),
                "verified_ancestors": verified_ancestors,
            }

        if exp_dev is not None and exp_ino is not None:
            if (obs_dev, obs_ino) != (int(exp_dev), int(exp_ino)):
                err_msg = (
                    f"Ancestor directory inode changed at {anc_path}: "
                    f"expected (dev={exp_dev}, ino={exp_ino}), "
                    f"observed (dev={obs_dev}, ino={obs_ino})"
                )
                return {
                    "verified": False,
                    "damaged_ancestor_path": str(anc_path),
                    "damaged_ancestor_exists": True,
                    "damaged_ancestor_is_symlink": False,
                    "damaged_ancestor_is_directory": True,
                    "damaged_ancestor_symlink_target": None,
                    "expected_ancestor_dev": exp_dev,
                    "expected_ancestor_ino": exp_ino,
                    "expected_ancestor_resolved_path": exp_resolved,
                    "observed_ancestor_dev": obs_dev,
                    "observed_ancestor_ino": obs_ino,
                    "error": err_msg,
                    "exception_type": "ValueError",
                    "exception_message": err_msg,
                    "errno": None,
                    "exception": ValueError(err_msg),
                    "verified_ancestors": verified_ancestors,
                }

        try:
            obs_resolved = str(anc_path.resolve(strict=True))
        except OSError as exc:
            return {
                "verified": False,
                "damaged_ancestor_path": str(anc_path),
                "damaged_ancestor_exists": True,
                "damaged_ancestor_is_symlink": False,
                "damaged_ancestor_is_directory": True,
                "damaged_ancestor_symlink_target": None,
                "expected_ancestor_dev": exp_dev,
                "expected_ancestor_ino": exp_ino,
                "expected_ancestor_resolved_path": exp_resolved,
                "observed_ancestor_dev": obs_dev,
                "observed_ancestor_ino": obs_ino,
                "error": (
                    f"Failed to resolve ancestor directory {anc_path} "
                    f"({type(exc).__name__}): {exc}"
                ),
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
                "errno": getattr(exc, "errno", None),
                "exception": exc,
                "verified_ancestors": verified_ancestors,
            }

        if exp_resolved is not None and obs_resolved != str(exp_resolved):
            err_msg = (
                f"Ancestor directory resolved path changed at {anc_path}: "
                f"expected {exp_resolved!r}, observed {obs_resolved!r}"
            )
            return {
                "verified": False,
                "damaged_ancestor_path": str(anc_path),
                "damaged_ancestor_exists": True,
                "damaged_ancestor_is_symlink": False,
                "damaged_ancestor_is_directory": True,
                "damaged_ancestor_symlink_target": None,
                "expected_ancestor_dev": exp_dev,
                "expected_ancestor_ino": exp_ino,
                "expected_ancestor_resolved_path": exp_resolved,
                "observed_ancestor_dev": obs_dev,
                "observed_ancestor_ino": obs_ino,
                "error": err_msg,
                "exception_type": "ValueError",
                "exception_message": err_msg,
                "errno": None,
                "exception": ValueError(err_msg),
                "verified_ancestors": verified_ancestors,
            }

        verified_ancestors.append(
            {
                "path": str(anc_path),
                "resolved_path": obs_resolved,
                "dev": obs_dev,
                "ino": obs_ino,
                "mode": int(stat.S_IMODE(anc_st.st_mode)),
            }
        )

    return {
        "verified": True,
        "damaged_ancestor_path": None,
        "damaged_ancestor_exists": True,
        "damaged_ancestor_is_symlink": False,
        "damaged_ancestor_is_directory": True,
        "damaged_ancestor_symlink_target": None,
        "expected_ancestor_dev": expected_baseline.get("parent_dir_dev"),
        "expected_ancestor_ino": expected_baseline.get("parent_dir_ino"),
        "expected_ancestor_resolved_path": expected_baseline.get(
            "parent_dir_resolved_path"
        ),
        "observed_ancestor_dev": (
            verified_ancestors[-1]["dev"] if verified_ancestors else None
        ),
        "observed_ancestor_ino": (
            verified_ancestors[-1]["ino"] if verified_ancestors else None
        ),
        "error": None,
        "exception_type": None,
        "exception_message": None,
        "errno": None,
        "exception": None,
        "verified_ancestors": verified_ancestors,
    }


def _verify_and_read_admitted_input_file(
    file_path: Path,
    input_baseline: Mapping[str, Any] | None = None,
    *,
    label: str = "input",
) -> dict[str, Any]:
    """Verify admitted ancestor chain and leaf identity before opening or reading ``file_path``."""
    normalized_path = Path(os.path.abspath(os.fspath(file_path)))
    baseline_sha256 = (
        input_baseline.get("sha256")
        if isinstance(input_baseline, Mapping)
        and isinstance(input_baseline.get("sha256"), str)
        else None
    )
    baseline_size_bytes = (
        int(input_baseline["size_bytes"])
        if isinstance(input_baseline, Mapping)
        and isinstance(input_baseline.get("size_bytes"), int)
        and not isinstance(input_baseline.get("size_bytes"), bool)
        else None
    )
    baseline_dev = (
        int(input_baseline["dev"])
        if isinstance(input_baseline, Mapping)
        and isinstance(input_baseline.get("dev"), int)
        and not isinstance(input_baseline.get("dev"), bool)
        else None
    )
    baseline_ino = (
        int(input_baseline["ino"])
        if isinstance(input_baseline, Mapping)
        and isinstance(input_baseline.get("ino"), int)
        and not isinstance(input_baseline.get("ino"), bool)
        else None
    )
    baseline_resolved_path = (
        str(input_baseline["resolved_path"])
        if isinstance(input_baseline, Mapping)
        and isinstance(input_baseline.get("resolved_path"), str)
        else None
    )

    if isinstance(input_baseline, Mapping) and any(
        k in input_baseline
        for k in (
            "ancestor_chain_baseline",
            "parent_dir_path",
            "parent_dir_dev",
            "parent_dir_ino",
            "evidence_root_path",
            "evidence_root_dev",
            "evidence_root_ino",
        )
    ):
        anc_check = _verify_admitted_ancestor_chain(normalized_path, input_baseline)
        if not anc_check["verified"]:
            err_msg = (
                f"{label} ancestor chain verification failed before read "
                f"({anc_check.get('exception_type') or 'ValueError'}): {anc_check.get('error')}"
            )
            return {
                "verified": False,
                "bytes": None,
                "path": str(normalized_path),
                "baseline_sha256": baseline_sha256,
                "baseline_size_bytes": baseline_size_bytes,
                "post_run_sha256": None,
                "post_run_size_bytes": None,
                "ancestor_chain_verified": False,
                "ancestor_check": anc_check,
                "error": err_msg,
                "exception_type": str(anc_check.get("exception_type") or "ValueError"),
                "exception_message": str(anc_check.get("error") or err_msg),
            }
    else:
        anc_dirs: list[Path] = []
        parent_dir = normalized_path.parent
        if parent_dir.parent != parent_dir:
            anc_dirs.append(parent_dir.parent)
        anc_dirs.append(parent_dir)
        for anc_dir in anc_dirs:
            try:
                anc_st = os.lstat(anc_dir)
                if stat.S_ISLNK(anc_st.st_mode) or not stat.S_ISDIR(anc_st.st_mode):
                    raise ValueError(
                        f"Ancestor directory is not a non-symlink directory: {anc_dir}"
                    )
            except Exception as exc:
                err_msg = (
                    f"{label} ancestor directory verification failed before read at {anc_dir} "
                    f"({type(exc).__name__}): {exc}"
                )
                return {
                    "verified": False,
                    "bytes": None,
                    "path": str(normalized_path),
                    "baseline_sha256": baseline_sha256,
                    "baseline_size_bytes": baseline_size_bytes,
                    "post_run_sha256": None,
                    "post_run_size_bytes": None,
                    "ancestor_chain_verified": False,
                    "ancestor_check": None,
                    "error": err_msg,
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                }

    try:
        leaf_st = os.lstat(normalized_path)
    except OSError as exc:
        err_msg = (
            f"{label} missing or unreadable post-run at {normalized_path} "
            f"({type(exc).__name__}): {exc}"
        )
        return {
            "verified": False,
            "bytes": None,
            "path": str(normalized_path),
            "baseline_sha256": baseline_sha256,
            "baseline_size_bytes": baseline_size_bytes,
            "post_run_sha256": None,
            "post_run_size_bytes": None,
            "ancestor_chain_verified": True,
            "ancestor_check": None,
            "error": err_msg,
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
        }

    if stat.S_ISLNK(leaf_st.st_mode) or not stat.S_ISREG(leaf_st.st_mode):
        err_msg = (
            f"{label} is not a regular non-symlink file post-run: {normalized_path}"
        )
        return {
            "verified": False,
            "bytes": None,
            "path": str(normalized_path),
            "baseline_sha256": baseline_sha256,
            "baseline_size_bytes": baseline_size_bytes,
            "post_run_sha256": None,
            "post_run_size_bytes": None,
            "ancestor_chain_verified": True,
            "ancestor_check": None,
            "error": err_msg,
            "exception_type": "ValueError",
            "exception_message": err_msg,
        }

    obs_dev = int(leaf_st.st_dev)
    obs_ino = int(leaf_st.st_ino)
    if baseline_dev is not None and baseline_ino is not None:
        if (obs_dev, obs_ino) != (baseline_dev, baseline_ino):
            err_msg = (
                f"{label} inode changed post-run at {normalized_path}: "
                f"expected (dev={baseline_dev}, ino={baseline_ino}), "
                f"observed (dev={obs_dev}, ino={obs_ino})"
            )
            return {
                "verified": False,
                "bytes": None,
                "path": str(normalized_path),
                "baseline_sha256": baseline_sha256,
                "baseline_size_bytes": baseline_size_bytes,
                "post_run_sha256": None,
                "post_run_size_bytes": None,
                "ancestor_chain_verified": True,
                "ancestor_check": None,
                "error": err_msg,
                "exception_type": "ValueError",
                "exception_message": err_msg,
            }

    try:
        obs_resolved = str(normalized_path.resolve(strict=True))
    except OSError as exc:
        err_msg = (
            f"{label} failed strict path resolution before read at {normalized_path} "
            f"({type(exc).__name__}): {exc}"
        )
        return {
            "verified": False,
            "bytes": None,
            "path": str(normalized_path),
            "baseline_sha256": baseline_sha256,
            "baseline_size_bytes": baseline_size_bytes,
            "post_run_sha256": None,
            "post_run_size_bytes": None,
            "ancestor_chain_verified": True,
            "ancestor_check": None,
            "error": err_msg,
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
        }

    if baseline_resolved_path is not None and obs_resolved != baseline_resolved_path:
        err_msg = (
            f"{label} resolved path changed post-run at {normalized_path}: "
            f"expected {baseline_resolved_path!r}, observed {obs_resolved!r}"
        )
        return {
            "verified": False,
            "bytes": None,
            "path": str(normalized_path),
            "baseline_sha256": baseline_sha256,
            "baseline_size_bytes": baseline_size_bytes,
            "post_run_sha256": None,
            "post_run_size_bytes": None,
            "ancestor_chain_verified": True,
            "ancestor_check": None,
            "error": err_msg,
            "exception_type": "ValueError",
            "exception_message": err_msg,
        }

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    fd_owned_by_fileobj = False
    fd = -1
    try:
        fd = os.open(normalized_path, flags)
        fd_st = os.fstat(fd)
        if not stat.S_ISREG(fd_st.st_mode):
            raise ValueError(
                f"{label} opened descriptor is not a regular file: {normalized_path}"
            )
        if (int(fd_st.st_dev), int(fd_st.st_ino)) != (obs_dev, obs_ino):
            raise ValueError(
                f"{label} inode changed between lstat and open at {normalized_path}"
            )
        fd_owned_by_fileobj = True
        with os.fdopen(fd, "rb") as handle:
            raw_bytes = handle.read()
    except Exception as exc:
        if fd >= 0 and not fd_owned_by_fileobj:
            try:
                os.close(fd)
            except OSError:
                pass
        err_msg = (
            f"{label} failed verified open/read at {normalized_path} "
            f"({type(exc).__name__}): {exc}"
        )
        return {
            "verified": False,
            "bytes": None,
            "path": str(normalized_path),
            "baseline_sha256": baseline_sha256,
            "baseline_size_bytes": baseline_size_bytes,
            "post_run_sha256": None,
            "post_run_size_bytes": None,
            "ancestor_chain_verified": True,
            "ancestor_check": None,
            "error": err_msg,
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
        }

    post_run_sha256 = _sha256_bytes(raw_bytes)
    post_run_size = len(raw_bytes)
    if (
        (baseline_sha256 is not None and post_run_sha256 != baseline_sha256)
        or (baseline_size_bytes is not None and post_run_size != baseline_size_bytes)
    ):
        err_msg = (
            f"{label} mutated post-run: current sha256={post_run_sha256} size={post_run_size} "
            f"!= baseline sha256={baseline_sha256} size={baseline_size_bytes}"
        )
        return {
            "verified": False,
            "bytes": None,
            "path": str(normalized_path),
            "baseline_sha256": baseline_sha256,
            "baseline_size_bytes": baseline_size_bytes,
            "post_run_sha256": post_run_sha256,
            "post_run_size_bytes": post_run_size,
            "ancestor_chain_verified": True,
            "ancestor_check": None,
            "error": err_msg,
            "exception_type": "ValueError",
            "exception_message": err_msg,
        }

    return {
        "verified": True,
        "bytes": raw_bytes,
        "path": str(normalized_path),
        "baseline_sha256": baseline_sha256 or post_run_sha256,
        "baseline_size_bytes": (
            baseline_size_bytes if baseline_size_bytes is not None else post_run_size
        ),
        "post_run_sha256": post_run_sha256,
        "post_run_size_bytes": post_run_size,
        "ancestor_chain_verified": True,
        "ancestor_check": None,
        "error": None,
        "exception_type": None,
        "exception_message": None,
    }


def _verify_refmac_directory_post_run(
    refmac_dir: Path,
    *,
    refmac_dir_baseline: Mapping[str, Any],
    caught_exceptions: list[Exception] | None = None,
) -> dict[str, Any]:
    """Verify that ``refmac_dir`` still matches its pre-launch directory identity without following symlinks."""
    normalized_dir = Path(os.path.abspath(os.fspath(refmac_dir)))
    expected_dev = (
        int(refmac_dir_baseline["dev"])
        if refmac_dir_baseline.get("dev") is not None
        else None
    )
    expected_ino = (
        int(refmac_dir_baseline["ino"])
        if refmac_dir_baseline.get("ino") is not None
        else None
    )
    expected_resolved = (
        str(refmac_dir_baseline["resolved_path"])
        if refmac_dir_baseline.get("resolved_path") is not None
        else None
    )
    expected_mode = (
        int(refmac_dir_baseline["mode"])
        if refmac_dir_baseline.get("mode") is not None
        else None
    )

    if refmac_dir_baseline.get("evidence_root") is not None:
        root_path = Path(
            os.path.abspath(os.fspath(str(refmac_dir_baseline["evidence_root"])))
        )
        try:
            root_st = os.lstat(root_path)
            if stat.S_ISLNK(root_st.st_mode) or not stat.S_ISDIR(root_st.st_mode):
                raise ValueError(
                    f"Evidence root is no longer a non-symlink directory: {root_path}"
                )
            if (
                refmac_dir_baseline.get("evidence_root_dev") is not None
                and refmac_dir_baseline.get("evidence_root_ino") is not None
                and (int(root_st.st_dev), int(root_st.st_ino))
                != (
                    int(refmac_dir_baseline["evidence_root_dev"]),
                    int(refmac_dir_baseline["evidence_root_ino"]),
                )
            ):
                raise ValueError(
                    f"Evidence root inode changed at {root_path}"
                )
            if refmac_dir_baseline.get("evidence_root_resolved_path") is not None:
                obs_root_resolved = str(root_path.resolve(strict=True))
                if obs_root_resolved != str(
                    refmac_dir_baseline["evidence_root_resolved_path"]
                ):
                    raise ValueError(
                        f"Evidence root resolved path changed at {root_path}"
                    )
            if normalized_dir != root_path and normalized_dir.is_relative_to(root_path):
                inter_cur = root_path
                for part in normalized_dir.relative_to(root_path).parts[:-1]:
                    inter_cur = inter_cur / part
                    inter_st = os.lstat(inter_cur)
                    if stat.S_ISLNK(inter_st.st_mode) or not stat.S_ISDIR(
                        inter_st.st_mode
                    ):
                        raise ValueError(
                            f"Intermediate ancestor is not a non-symlink directory: {inter_cur}"
                        )
        except Exception as exc:
            if caught_exceptions is not None:
                caught_exceptions.append(exc)
            return {
                "path": str(normalized_dir),
                "resolved_path": None,
                "exists": False,
                "is_symlink": False,
                "is_directory": False,
                "symlink_target": None,
                "dev": None,
                "ino": None,
                "mode": None,
                "expected_dev": expected_dev,
                "expected_ino": expected_ino,
                "expected_resolved_path": expected_resolved,
                "expected_mode": expected_mode,
                "mode_changed": None,
                "identity_verified": False,
                "writable_post_run": False,
                "error": f"Evidence root check failed ({type(exc).__name__}): {exc}",
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
                "errno": getattr(exc, "errno", None),
            }
    elif normalized_dir.parent != normalized_dir:
        parent_dir = normalized_dir.parent
        try:
            parent_st = os.lstat(parent_dir)
            if stat.S_ISLNK(parent_st.st_mode) or not stat.S_ISDIR(parent_st.st_mode):
                raise ValueError(
                    f"Parent directory is not a non-symlink directory: {parent_dir}"
                )
        except Exception as exc:
            if caught_exceptions is not None:
                caught_exceptions.append(exc)
            return {
                "path": str(normalized_dir),
                "resolved_path": None,
                "exists": False,
                "is_symlink": False,
                "is_directory": False,
                "symlink_target": None,
                "dev": None,
                "ino": None,
                "mode": None,
                "expected_dev": expected_dev,
                "expected_ino": expected_ino,
                "expected_resolved_path": expected_resolved,
                "expected_mode": expected_mode,
                "mode_changed": None,
                "identity_verified": False,
                "writable_post_run": False,
                "error": f"Evidence root check failed ({type(exc).__name__}): {exc}",
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
                "errno": getattr(exc, "errno", None),
            }

    try:
        st = os.lstat(normalized_dir)
    except OSError as exc:
        if caught_exceptions is not None:
            caught_exceptions.append(exc)
        return {
            "path": str(normalized_dir),
            "resolved_path": None,
            "exists": False,
            "is_symlink": False,
            "is_directory": False,
            "symlink_target": None,
            "dev": None,
            "ino": None,
            "mode": None,
            "expected_dev": expected_dev,
            "expected_ino": expected_ino,
            "expected_resolved_path": expected_resolved,
            "expected_mode": expected_mode,
            "mode_changed": None,
            "identity_verified": False,
            "writable_post_run": False,
            "error": (
                f"Refmac working directory missing or unreadable at {normalized_dir} "
                f"({type(exc).__name__}): {exc}"
            ),
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "errno": getattr(exc, "errno", None),
        }

    obs_dev = int(st.st_dev)
    obs_ino = int(st.st_ino)
    obs_mode = int(stat.S_IMODE(st.st_mode))
    is_symlink = bool(stat.S_ISLNK(st.st_mode))
    is_dir = bool(stat.S_ISDIR(st.st_mode))
    mode_changed = (obs_mode != expected_mode) if expected_mode is not None else False

    if is_symlink:
        try:
            symlink_target = os.readlink(normalized_dir)
        except OSError:
            symlink_target = None
        err_msg = (
            f"Refmac working directory was replaced by a symlink: {normalized_dir}"
            + (f" -> {symlink_target!r}" if symlink_target is not None else "")
        )
        exc_obj = ValueError(err_msg)
        if caught_exceptions is not None:
            caught_exceptions.append(exc_obj)
        return {
            "path": str(normalized_dir),
            "resolved_path": None,
            "exists": True,
            "is_symlink": True,
            "is_directory": False,
            "symlink_target": symlink_target,
            "dev": obs_dev,
            "ino": obs_ino,
            "mode": obs_mode,
            "expected_dev": expected_dev,
            "expected_ino": expected_ino,
            "expected_resolved_path": expected_resolved,
            "expected_mode": expected_mode,
            "mode_changed": mode_changed,
            "identity_verified": False,
            "writable_post_run": False,
            "error": err_msg,
            "exception_type": "ValueError",
            "exception_message": err_msg,
            "errno": None,
        }

    if not is_dir:
        err_msg = f"Refmac working directory path is not a directory: {normalized_dir}"
        exc_obj = ValueError(err_msg)
        if caught_exceptions is not None:
            caught_exceptions.append(exc_obj)
        return {
            "path": str(normalized_dir),
            "resolved_path": None,
            "exists": True,
            "is_symlink": False,
            "is_directory": False,
            "symlink_target": None,
            "dev": obs_dev,
            "ino": obs_ino,
            "mode": obs_mode,
            "expected_dev": expected_dev,
            "expected_ino": expected_ino,
            "expected_resolved_path": expected_resolved,
            "expected_mode": expected_mode,
            "mode_changed": mode_changed,
            "identity_verified": False,
            "writable_post_run": False,
            "error": err_msg,
            "exception_type": "ValueError",
            "exception_message": err_msg,
            "errno": None,
        }

    if (
        expected_dev is not None
        and expected_ino is not None
        and (obs_dev, obs_ino) != (expected_dev, expected_ino)
    ):
        err_msg = (
            f"Refmac working directory inode changed at {normalized_dir}: "
            f"expected (dev={expected_dev}, ino={expected_ino}), "
            f"observed (dev={obs_dev}, ino={obs_ino})"
        )
        exc_obj = ValueError(err_msg)
        if caught_exceptions is not None:
            caught_exceptions.append(exc_obj)
        return {
            "path": str(normalized_dir),
            "resolved_path": None,
            "exists": True,
            "is_symlink": False,
            "is_directory": True,
            "symlink_target": None,
            "dev": obs_dev,
            "ino": obs_ino,
            "mode": obs_mode,
            "expected_dev": expected_dev,
            "expected_ino": expected_ino,
            "expected_resolved_path": expected_resolved,
            "expected_mode": expected_mode,
            "mode_changed": mode_changed,
            "identity_verified": False,
            "writable_post_run": False,
            "error": err_msg,
            "exception_type": "ValueError",
            "exception_message": err_msg,
            "errno": None,
        }

    try:
        obs_resolved = str(normalized_dir.resolve(strict=True))
    except OSError as exc:
        if caught_exceptions is not None:
            caught_exceptions.append(exc)
        return {
            "path": str(normalized_dir),
            "resolved_path": None,
            "exists": True,
            "is_symlink": False,
            "is_directory": True,
            "symlink_target": None,
            "dev": obs_dev,
            "ino": obs_ino,
            "mode": obs_mode,
            "expected_dev": expected_dev,
            "expected_ino": expected_ino,
            "expected_resolved_path": expected_resolved,
            "expected_mode": expected_mode,
            "mode_changed": mode_changed,
            "identity_verified": False,
            "writable_post_run": False,
            "error": (
                f"Failed to resolve refmac working directory {normalized_dir} "
                f"({type(exc).__name__}): {exc}"
            ),
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "errno": getattr(exc, "errno", None),
        }

    if expected_resolved is not None and obs_resolved != expected_resolved:
        err_msg = (
            f"Refmac working directory resolved path changed at {normalized_dir}: "
            f"expected {expected_resolved!r}, observed {obs_resolved!r}"
        )
        exc_obj = ValueError(err_msg)
        if caught_exceptions is not None:
            caught_exceptions.append(exc_obj)
        return {
            "path": str(normalized_dir),
            "resolved_path": obs_resolved,
            "exists": True,
            "is_symlink": False,
            "is_directory": True,
            "symlink_target": None,
            "dev": obs_dev,
            "ino": obs_ino,
            "mode": obs_mode,
            "expected_dev": expected_dev,
            "expected_ino": expected_ino,
            "expected_resolved_path": expected_resolved,
            "expected_mode": expected_mode,
            "mode_changed": mode_changed,
            "identity_verified": False,
            "writable_post_run": False,
            "error": err_msg,
            "exception_type": "ValueError",
            "exception_message": err_msg,
            "errno": None,
        }

    return {
        "path": str(normalized_dir),
        "resolved_path": obs_resolved,
        "exists": True,
        "is_symlink": False,
        "is_directory": True,
        "symlink_target": None,
        "dev": obs_dev,
        "ino": obs_ino,
        "mode": obs_mode,
        "expected_dev": expected_dev,
        "expected_ino": expected_ino,
        "expected_resolved_path": expected_resolved,
        "expected_mode": expected_mode,
        "mode_changed": mode_changed,
        "identity_verified": True,
        "writable_post_run": True,
        "error": None,
        "exception_type": None,
        "exception_message": None,
        "errno": None,
    }


def _write_new_regular_file_text(path: Path, content: str, *, root: Path) -> dict[str, Any]:
    """Create a brand-new regular UTF-8 file without overwriting or following symlinks."""
    _ensure_no_symlink_components_under_root(path, root, check_leaf=False)
    try:
        os.lstat(path)
    except FileNotFoundError:
        pass
    else:
        raise FileExistsError(f"Refusing to overwrite existing file or symlink: {path}")

    raw_bytes = content.encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    created_file = False
    try:
        fd = os.open(path, flags, 0o644)
        created_file = True
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw_bytes)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError as exc:
                if exc.errno not in (errno.EINVAL, errno.ENOTSUP):
                    raise
    except BaseException:
        if created_file:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise

    digest = _sha256_regular_file(path)
    if digest != _sha256_bytes(raw_bytes):
        raise ValueError(f"Written file digest mismatch for {path}")
    return {
        "path": str(path),
        "sha256": digest,
        "size_bytes": len(raw_bytes),
    }


def _materialize_json_payload(
    payload: (
        Mapping[str, Any]
        | Callable[[Path], Mapping[str, Any]]
        | Callable[[Path | None], Mapping[str, Any]]
    ),
    destination_path: Path,
) -> Mapping[str, Any]:
    """Materialize ``payload`` at the selected ``destination_path`` before JSON serialization."""
    resolved = payload(destination_path) if callable(payload) else payload
    if not isinstance(resolved, Mapping):
        raise TypeError(
            f"JSON payload must materialize to a Mapping, got {type(resolved).__name__}"
        )
    return resolved


def _atomic_write_new_json_file(
    payload: (
        Mapping[str, Any]
        | Callable[[Path], Mapping[str, Any]]
        | Callable[[Path | None], Mapping[str, Any]]
    ),
    target_path: Path,
    *,
    root: Path,
) -> dict[str, Any]:
    """Atomically write a new JSON file without overwriting an existing destination or following symlinks."""
    _ensure_no_symlink_components_under_root(target_path, root, check_leaf=False)
    try:
        os.lstat(target_path)
    except FileNotFoundError:
        pass
    else:
        raise FileExistsError(
            f"Refusing to overwrite existing JSON artifact or symlink: {target_path}"
        )

    tmp_path = target_path.parent / f".{target_path.name}.tmp.{os.getpid()}"
    _ensure_no_symlink_components_under_root(tmp_path, root, check_leaf=False)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    created_tmp = False
    try:
        fd = os.open(tmp_path, flags, 0o644)
        created_tmp = True
        with os.fdopen(fd, "wb") as handle:
            materialized_payload = _materialize_json_payload(payload, target_path)
            serialized = (
                json.dumps(
                    materialized_payload,
                    indent=2,
                    sort_keys=True,
                    allow_nan=False,
                )
                + "\n"
            )
            raw_bytes = serialized.encode("utf-8")
            handle.write(raw_bytes)
            handle.flush()
            try:
                os.fsync(handle.fileno())
            except OSError as exc:
                if exc.errno not in (errno.EINVAL, errno.ENOTSUP):
                    raise
        try:
            os.lstat(target_path)
        except FileNotFoundError:
            pass
        else:
            raise FileExistsError(
                f"Destination appeared before atomic move: {target_path}"
            )
        os.replace(tmp_path, target_path)
        created_tmp = False
    except BaseException:
        if created_tmp:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise

    digest = _sha256_regular_file(target_path)
    return {
        "path": str(target_path),
        "sha256": digest,
        "size_bytes": len(raw_bytes),
    }


def _write_json_with_sibling_collision_fallback(
    payload: (
        Mapping[str, Any]
        | Callable[[Path], Mapping[str, Any]]
        | Callable[[Path | None], Mapping[str, Any]]
    ),
    target_path: Path,
    *,
    root: Path,
) -> dict[str, Any]:
    """Write ``payload`` to ``target_path`` under ``root``, using a ``.parent.<pid>`` sibling on ``FileExistsError``."""
    try:
        return _atomic_write_new_json_file(payload, target_path, root=root)
    except FileExistsError:
        attempt = 0
        while True:
            suffix_tag = (
                f".parent.{os.getpid()}"
                if attempt == 0
                else f".parent.{os.getpid()}.{attempt}"
            )
            fallback_path = (
                target_path.parent
                / f"{target_path.stem}{suffix_tag}{target_path.suffix}"
            )
            try:
                artifact = _atomic_write_new_json_file(
                    payload, fallback_path, root=root
                )
            except FileExistsError:
                attempt += 1
                continue
            artifact["fallback_for_preexisting_path"] = str(target_path)
            return artifact


def _ensure_verified_root_exclusive_fallback_dir(
    *,
    parent_retention_dir: Path,
    parent_retention_dir_baseline: Mapping[str, Any] | None,
    parent_dir_unusable_reason: str,
    verified_root_fallback_state: dict[str, Any],
    caught_persistence_exceptions: list[Exception] | None = None,
) -> tuple[Path | None, dict[str, Any] | None, str | None]:
    """Verify original admitted ``evidence_root`` and create or reuse an exclusive parent-owned error-record directory."""
    if (
        parent_retention_dir_baseline is None
        or parent_retention_dir_baseline.get("evidence_root") is None
        or parent_retention_dir_baseline.get("evidence_root_dev") is None
        or parent_retention_dir_baseline.get("evidence_root_ino") is None
    ):
        ev_err = (
            "No admitted evidence_root baseline identity available to anchor fallback "
            f"after parent_retention_dir failure ({parent_retention_dir})"
        )
        if caught_persistence_exceptions is not None:
            caught_persistence_exceptions.append(ValueError(ev_err))
        verified_root_fallback_state.update(
            {
                "used": False,
                "no_verified_anchor_available": True,
                "failed_intended_parent_retention_dir": str(parent_retention_dir),
                "parent_retention_dir_failure_reason": parent_dir_unusable_reason,
                "evidence_root_verified": False,
                "evidence_root_failure_reason": ev_err,
                "actual_anchor_dir": None,
                "actual_anchor_kind": None,
                "actual_anchor_baseline": None,
            }
        )
        return None, None, ev_err

    ev_root_path = Path(
        os.path.abspath(os.fspath(str(parent_retention_dir_baseline["evidence_root"])))
    )
    expected_ev_dev = int(parent_retention_dir_baseline["evidence_root_dev"])
    expected_ev_ino = int(parent_retention_dir_baseline["evidence_root_ino"])
    expected_ev_resolved = (
        str(parent_retention_dir_baseline["evidence_root_resolved_path"])
        if parent_retention_dir_baseline.get("evidence_root_resolved_path") is not None
        else None
    )

    try:
        ev_st = os.lstat(ev_root_path)
        if stat.S_ISLNK(ev_st.st_mode) or not stat.S_ISDIR(ev_st.st_mode):
            raise ValueError(
                f"Admitted evidence_root is no longer a non-symlink directory: {ev_root_path}"
            )
        if (int(ev_st.st_dev), int(ev_st.st_ino)) != (expected_ev_dev, expected_ev_ino):
            raise ValueError(
                f"Admitted evidence_root inode changed at {ev_root_path}: "
                f"expected (dev={expected_ev_dev}, ino={expected_ev_ino}), "
                f"observed (dev={int(ev_st.st_dev)}, ino={int(ev_st.st_ino)})"
            )
        obs_ev_resolved = str(ev_root_path.resolve(strict=True))
        if expected_ev_resolved is not None and obs_ev_resolved != expected_ev_resolved:
            raise ValueError(
                f"Admitted evidence_root resolved path changed at {ev_root_path}: "
                f"expected {expected_ev_resolved!r}, observed {obs_ev_resolved!r}"
            )
    except Exception as exc:
        if caught_persistence_exceptions is not None:
            caught_persistence_exceptions.append(exc)
        ev_err = f"{type(exc).__name__}: {exc}"
        verified_root_fallback_state.update(
            {
                "used": False,
                "no_verified_anchor_available": True,
                "failed_intended_parent_retention_dir": str(parent_retention_dir),
                "parent_retention_dir_failure_reason": parent_dir_unusable_reason,
                "evidence_root_verified": False,
                "evidence_root_failure_reason": ev_err,
                "actual_anchor_dir": None,
                "actual_anchor_kind": None,
                "actual_anchor_baseline": None,
            }
        )
        return None, None, ev_err

    existing_anchor_str = verified_root_fallback_state.get("actual_anchor_dir")
    existing_anchor_baseline = verified_root_fallback_state.get("actual_anchor_baseline")
    if (
        isinstance(existing_anchor_str, str)
        and isinstance(existing_anchor_baseline, Mapping)
    ):
        existing_anchor_path = Path(existing_anchor_str)
        existing_check = _verify_refmac_directory_post_run(
            existing_anchor_path,
            refmac_dir_baseline=existing_anchor_baseline,
            caught_exceptions=caught_persistence_exceptions,
        )
        if bool(existing_check.get("identity_verified", False)):
            return existing_anchor_path, dict(existing_anchor_baseline), None

    attempt = 0
    while True:
        suffix = (
            f"refmac_parent_retention.verified_root_fallback.{os.getpid()}"
            if attempt == 0
            else f"refmac_parent_retention.verified_root_fallback.{os.getpid()}.{attempt}"
        )
        candidate_dir = ev_root_path / suffix
        try:
            _ensure_no_symlink_components_under_root(
                candidate_dir, ev_root_path, check_leaf=False
            )
            ev_st_check = os.lstat(ev_root_path)
            if (
                stat.S_ISLNK(ev_st_check.st_mode)
                or not stat.S_ISDIR(ev_st_check.st_mode)
                or (int(ev_st_check.st_dev), int(ev_st_check.st_ino))
                != (expected_ev_dev, expected_ev_ino)
            ):
                raise ValueError(
                    f"Admitted evidence_root failed re-verification before mkdir: {ev_root_path}"
                )
            try:
                os.lstat(candidate_dir)
            except FileNotFoundError:
                pass
            else:
                attempt += 1
                continue
            os.mkdir(candidate_dir, 0o755)
            anchor_baseline = _capture_directory_identity_baseline(
                candidate_dir,
                evidence_root=ev_root_path,
            )
        except FileExistsError:
            attempt += 1
            continue
        except Exception as exc:
            if caught_persistence_exceptions is not None:
                caught_persistence_exceptions.append(exc)
            ev_err = f"{type(exc).__name__}: {exc}"
            verified_root_fallback_state.update(
                {
                    "used": False,
                    "no_verified_anchor_available": True,
                    "failed_intended_parent_retention_dir": str(parent_retention_dir),
                    "parent_retention_dir_failure_reason": parent_dir_unusable_reason,
                    "evidence_root_verified": False,
                    "evidence_root_failure_reason": ev_err,
                    "actual_anchor_dir": None,
                    "actual_anchor_kind": None,
                    "actual_anchor_baseline": None,
                }
            )
            return None, None, ev_err

        verified_root_fallback_state.update(
            {
                "used": True,
                "no_verified_anchor_available": False,
                "failed_intended_parent_retention_dir": str(parent_retention_dir),
                "parent_retention_dir_failure_reason": parent_dir_unusable_reason,
                "evidence_root_verified": True,
                "evidence_root_failure_reason": None,
                "actual_anchor_dir": str(candidate_dir),
                "actual_anchor_kind": "verified_evidence_root_exclusive_dir",
                "actual_anchor_baseline": copy.deepcopy(anchor_baseline),
            }
        )
        return candidate_dir, anchor_baseline, None


def _persist_collector_json_with_fallback(
    payload: (
        Mapping[str, Any]
        | Callable[[Path], Mapping[str, Any]]
        | Callable[[Path | None], Mapping[str, Any]]
    ),
    target_path: Path,
    *,
    root: Path,
    parent_retention_dir: Path | None = None,
    parent_retention_dir_baseline: Mapping[str, Any] | None = None,
    parent_retention_dir_status: dict[str, Any] | None = None,
    verified_root_fallback_state: dict[str, Any] | None = None,
    allow_unpersisted_on_no_verified_anchor: bool = False,
    refmac_dir_status: dict[str, Any] | None = None,
    child_dir_persistence_failures: list[dict[str, Any]] | None = None,
    caught_persistence_exceptions: list[Exception] | None = None,
    on_child_dir_failure_transform: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
    retained_payload_sink: list[dict[str, Any]] | None = None,
    child_dir_persistence_causes: list[Exception | None] | None = None,
    parent_retention_dir_cause_sink: list[Exception | None] | None = None,
) -> dict[str, Any]:
    """Write a parent-owned collector JSON artifact, falling back to a sibling on collision or to a verified parent anchor when ``root`` is unwritable or damaged."""
    def _record_retained_payload(
        materialized: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if retained_payload_sink is not None:
            retained_payload_sink.clear()
            retained_payload_sink.append(copy.deepcopy(dict(materialized)))
        return materialized

    child_dir_usable = True
    child_dir_unusable_reason: str | None = None
    child_dir_exc_type: str | None = None
    child_dir_exc_msg: str | None = None
    child_dir_errno: int | None = None

    if refmac_dir_status is not None:
        if not bool(refmac_dir_status.get("identity_verified", True)):
            child_dir_usable = False
            child_dir_unusable_reason = str(
                refmac_dir_status.get("error")
                or f"Child refmac directory identity verification failed: {root}"
            )
            child_dir_exc_type = str(
                refmac_dir_status.get("exception_type") or "ValueError"
            )
            child_dir_exc_msg = str(
                refmac_dir_status.get("exception_message")
                or child_dir_unusable_reason
            )
            child_dir_errno = refmac_dir_status.get("errno")
        elif not bool(refmac_dir_status.get("writable_post_run", True)):
            child_dir_usable = False
            child_dir_unusable_reason = str(
                refmac_dir_status.get("write_error")
                or refmac_dir_status.get("error")
                or f"Child refmac directory is not writable post-run: {root}"
            )
            child_dir_exc_type = str(
                refmac_dir_status.get("write_exception_type")
                or refmac_dir_status.get("exception_type")
                or "PermissionError"
            )
            child_dir_exc_msg = str(
                refmac_dir_status.get("write_exception_message")
                or refmac_dir_status.get("exception_message")
                or child_dir_unusable_reason
            )
            child_dir_errno = (
                refmac_dir_status.get("write_errno")
                if refmac_dir_status.get("write_errno") is not None
                else refmac_dir_status.get("errno")
            )

    if child_dir_usable:
        child_payload: (
            Mapping[str, Any]
            | Callable[[Path], Mapping[str, Any]]
            | Callable[[Path | None], Mapping[str, Any]]
        )
        if retained_payload_sink is not None:
            def _child_factory_for_destination(
                destination_path: Path,
            ) -> Mapping[str, Any]:
                return _record_retained_payload(
                    _materialize_json_payload(payload, destination_path)
                )

            child_payload = _child_factory_for_destination
        else:
            child_payload = payload
        try:
            return _write_json_with_sibling_collision_fallback(
                child_payload, target_path, root=root
            )
        except (OSError, ValueError) as exc:
            if parent_retention_dir is None:
                raise
            if caught_persistence_exceptions is not None:
                caught_persistence_exceptions.append(exc)
            child_dir_usable = False
            child_dir_unusable_reason = f"{type(exc).__name__}: {exc}"
            child_dir_exc_type = type(exc).__name__
            child_dir_exc_msg = str(exc)
            child_dir_errno = getattr(exc, "errno", None)
            if refmac_dir_status is not None:
                refmac_dir_status["writable_post_run"] = False
                refmac_dir_status["write_error"] = child_dir_unusable_reason
                refmac_dir_status["write_exception_type"] = child_dir_exc_type
                refmac_dir_status["write_exception_message"] = child_dir_exc_msg
                refmac_dir_status["write_errno"] = child_dir_errno
            if child_dir_persistence_failures is not None:
                child_dir_persistence_failures.append(
                    {
                        "intended_path": str(target_path),
                        "artifact_name": target_path.name,
                        "exception_type": child_dir_exc_type,
                        "exception_message": child_dir_exc_msg,
                        "errno": child_dir_errno,
                        "attempted_write_in_child_dir": True,
                    }
                )
            if child_dir_persistence_causes is not None:
                child_dir_persistence_causes.append(exc)
    else:
        if parent_retention_dir is None:
            raise ValueError(
                child_dir_unusable_reason
                or f"Child refmac directory unavailable for persistence: {root}"
            )
        if child_dir_persistence_failures is not None:
            child_dir_persistence_failures.append(
                {
                    "intended_path": str(target_path),
                    "artifact_name": target_path.name,
                    "exception_type": child_dir_exc_type or "ValueError",
                    "exception_message": child_dir_exc_msg
                    or child_dir_unusable_reason
                    or f"Child refmac directory unavailable: {root}",
                    "errno": child_dir_errno,
                    "attempted_write_in_child_dir": False,
                }
            )
        if child_dir_persistence_causes is not None:
            child_dir_persistence_causes.append(
                child_dir_persistence_causes[0]
                if child_dir_persistence_causes
                else None
            )

    def _compose_child_failure_payload(
        extra_transform: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None,
    ) -> Mapping[str, Any] | Callable[[Path], Mapping[str, Any]]:
        if not callable(payload) and retained_payload_sink is None:
            transformed: Mapping[str, Any] = (
                on_child_dir_failure_transform(payload)
                if on_child_dir_failure_transform is not None
                else payload
            )
            if not isinstance(transformed, Mapping):
                raise TypeError(
                    f"JSON payload must materialize to a Mapping, got {type(transformed).__name__}"
                )
            if extra_transform is not None:
                transformed = extra_transform(transformed)
            return transformed

        def _factory_for_destination(destination_path: Path) -> Mapping[str, Any]:
            materialized = _materialize_json_payload(payload, destination_path)
            if on_child_dir_failure_transform is not None:
                materialized = on_child_dir_failure_transform(materialized)
                if not isinstance(materialized, Mapping):
                    raise TypeError(
                        "on_child_dir_failure_transform must return a Mapping, "
                        f"got {type(materialized).__name__}"
                    )
            if extra_transform is not None:
                materialized = extra_transform(materialized)
            return _record_retained_payload(materialized)

        return _factory_for_destination

    parent_dir_usable = True
    parent_dir_unusable_reason: str | None = None
    if parent_retention_dir_baseline is not None:
        live_parent_causes: list[Exception] = []
        live_parent_check = _verify_refmac_directory_post_run(
            parent_retention_dir,
            refmac_dir_baseline=parent_retention_dir_baseline,
            caught_exceptions=live_parent_causes,
        )
        if caught_persistence_exceptions is not None:
            caught_persistence_exceptions.extend(live_parent_causes)
        if parent_retention_dir_status is not None:
            prev_writable = parent_retention_dir_status.get("writable_post_run", True)
            prev_write_err = parent_retention_dir_status.get("write_error")
            prev_write_exc_type = parent_retention_dir_status.get("write_exception_type")
            prev_write_exc_msg = parent_retention_dir_status.get("write_exception_message")
            prev_write_errno = parent_retention_dir_status.get("write_errno")
            parent_retention_dir_status.clear()
            parent_retention_dir_status.update(live_parent_check)
            if not prev_writable and prev_write_err is not None:
                parent_retention_dir_status["writable_post_run"] = False
                parent_retention_dir_status["write_error"] = prev_write_err
                parent_retention_dir_status["write_exception_type"] = prev_write_exc_type
                parent_retention_dir_status["write_exception_message"] = prev_write_exc_msg
                parent_retention_dir_status["write_errno"] = prev_write_errno
            elif parent_retention_dir_cause_sink is not None:
                parent_retention_dir_cause_sink.clear()
                parent_retention_dir_cause_sink.append(
                    live_parent_causes[0] if live_parent_causes else None
                )
        elif parent_retention_dir_cause_sink is not None and live_parent_causes:
            parent_retention_dir_cause_sink.clear()
            parent_retention_dir_cause_sink.append(live_parent_causes[0])
        if not bool(live_parent_check.get("identity_verified", False)):
            parent_dir_usable = False
            parent_dir_unusable_reason = str(
                live_parent_check.get("error")
                or f"Parent retention directory identity verification failed: {parent_retention_dir}"
            )
        elif parent_retention_dir_status is not None and not bool(
            parent_retention_dir_status.get("writable_post_run", True)
        ):
            parent_dir_usable = False
            parent_dir_unusable_reason = str(
                parent_retention_dir_status.get("write_error")
                or parent_retention_dir_status.get("error")
                or f"Parent retention directory is not writable: {parent_retention_dir}"
            )
    elif parent_retention_dir_status is not None:
        if not bool(parent_retention_dir_status.get("identity_verified", True)):
            parent_dir_usable = False
            parent_dir_unusable_reason = str(
                parent_retention_dir_status.get("error")
                or f"Parent retention directory identity verification failed: {parent_retention_dir}"
            )
        elif not bool(parent_retention_dir_status.get("writable_post_run", True)):
            parent_dir_usable = False
            parent_dir_unusable_reason = str(
                parent_retention_dir_status.get("write_error")
                or parent_retention_dir_status.get("error")
                or f"Parent retention directory is not writable: {parent_retention_dir}"
            )

    if parent_dir_usable:
        effective_payload = _compose_child_failure_payload()
        parent_target_path = parent_retention_dir / target_path.name
        try:
            artifact = _write_json_with_sibling_collision_fallback(
                effective_payload,
                parent_target_path,
                root=parent_retention_dir,
            )
            artifact["fallback_for_unwritable_or_damaged_child_dir"] = True
            artifact["intended_child_dir_path"] = str(target_path)
            artifact["intended_parent_retention_dir"] = str(parent_retention_dir)
            artifact["parent_retention_dir"] = str(parent_retention_dir)
            artifact["actual_retention_anchor_dir"] = str(parent_retention_dir)
            artifact["actual_retention_anchor_kind"] = "parent_retention_dir"
            artifact["child_dir_persistence_error"] = child_dir_unusable_reason
            return artifact
        except (OSError, ValueError) as exc:
            if caught_persistence_exceptions is not None:
                caught_persistence_exceptions.append(exc)
            parent_dir_usable = False
            parent_dir_unusable_reason = f"{type(exc).__name__}: {exc}"
            if parent_retention_dir_status is not None:
                parent_retention_dir_status["writable_post_run"] = False
                parent_retention_dir_status["write_error"] = parent_dir_unusable_reason
                parent_retention_dir_status["write_exception_type"] = type(exc).__name__
                parent_retention_dir_status["write_exception_message"] = str(exc)
                parent_retention_dir_status["write_errno"] = getattr(exc, "errno", None)
            if parent_retention_dir_cause_sink is not None:
                parent_retention_dir_cause_sink.clear()
                parent_retention_dir_cause_sink.append(exc)

    fallback_state = (
        verified_root_fallback_state
        if verified_root_fallback_state is not None
        else {}
    )
    anchor_dir, anchor_baseline, ev_err = _ensure_verified_root_exclusive_fallback_dir(
        parent_retention_dir=parent_retention_dir,
        parent_retention_dir_baseline=parent_retention_dir_baseline,
        parent_dir_unusable_reason=str(
            parent_dir_unusable_reason
            or f"Parent retention directory unavailable: {parent_retention_dir}"
        ),
        verified_root_fallback_state=fallback_state,
        caught_persistence_exceptions=caught_persistence_exceptions,
    )

    if anchor_dir is not None and anchor_baseline is not None:
        def _patch_verified_root_anchor_payload(
            materialized: Mapping[str, Any],
        ) -> Mapping[str, Any]:
            if not (
                "parent_retention_directory_baseline" in materialized
                or "parent_retention_dir" in materialized
                or "paths" in materialized
            ):
                return materialized
            patched_payload = dict(materialized)
            patched_payload["intended_parent_retention_dir"] = str(parent_retention_dir)
            patched_payload["actual_parent_retention_anchor_dir"] = str(anchor_dir)
            patched_payload["actual_parent_retention_anchor_kind"] = (
                "verified_evidence_root_exclusive_dir"
            )
            patched_payload["actual_parent_retention_anchor_baseline"] = copy.deepcopy(
                anchor_baseline
            )
            if parent_retention_dir_status is not None:
                patched_payload["parent_retention_directory_post_run"] = copy.deepcopy(
                    parent_retention_dir_status
                )
            patched_payload["parent_retention_fallback_anchor"] = copy.deepcopy(
                fallback_state
            )
            if isinstance(patched_payload.get("paths"), Mapping):
                patched_paths = dict(patched_payload["paths"])
                patched_paths["intended_parent_retention_dir"] = str(parent_retention_dir)
                patched_paths["actual_parent_retention_anchor_dir"] = str(anchor_dir)
                patched_paths["actual_parent_retention_anchor_kind"] = (
                    "verified_evidence_root_exclusive_dir"
                )
                patched_paths["parent_retention_dir"] = str(anchor_dir)
                patched_payload["paths"] = patched_paths
            return patched_payload

        effective_payload = _compose_child_failure_payload(
            _patch_verified_root_anchor_payload
        )
        try:
            anchor_target_path = anchor_dir / target_path.name
            artifact = _write_json_with_sibling_collision_fallback(
                effective_payload,
                anchor_target_path,
                root=anchor_dir,
            )
            artifact["fallback_for_unwritable_or_damaged_child_dir"] = True
            artifact["fallback_for_damaged_or_replaced_parent_retention_dir"] = True
            artifact["intended_child_dir_path"] = str(target_path)
            artifact["intended_parent_retention_dir"] = str(parent_retention_dir)
            artifact["parent_retention_dir"] = str(anchor_dir)
            artifact["actual_retention_anchor_dir"] = str(anchor_dir)
            artifact["actual_retention_anchor_kind"] = (
                "verified_evidence_root_exclusive_dir"
            )
            artifact["actual_retention_anchor_baseline"] = copy.deepcopy(anchor_baseline)
            artifact["child_dir_persistence_error"] = child_dir_unusable_reason
            artifact["parent_retention_dir_persistence_error"] = (
                parent_dir_unusable_reason
            )
            return artifact
        except (OSError, ValueError) as exc:
            if caught_persistence_exceptions is not None:
                caught_persistence_exceptions.append(exc)
            ev_err = f"{type(exc).__name__}: {exc}"
            fallback_state.update(
                {
                    "used": False,
                    "no_verified_anchor_available": True,
                    "failed_intended_parent_retention_dir": str(parent_retention_dir),
                    "parent_retention_dir_failure_reason": parent_dir_unusable_reason,
                    "evidence_root_verified": False,
                    "evidence_root_failure_reason": ev_err,
                    "actual_anchor_dir": None,
                    "actual_anchor_kind": None,
                    "actual_anchor_baseline": None,
                }
            )

    unpersisted_msg = (
        f"No verified writable retention anchor available for {target_path.name}: "
        f"child_dir_error={child_dir_unusable_reason!r}; "
        f"parent_retention_dir_error={parent_dir_unusable_reason!r}; "
        f"evidence_root_error={ev_err!r}"
    )
    fallback_state["unpersisted_reason"] = unpersisted_msg
    if not allow_unpersisted_on_no_verified_anchor:
        err_exc = ValueError(unpersisted_msg)
        if caught_persistence_exceptions is not None:
            caught_persistence_exceptions.append(err_exc)
        raise err_exc

    materialization_error: str | None = None
    unavailable_memory_evidence: dict[str, Any] | None = None
    if callable(payload):
        try:
            materialized_no_anchor = payload(None)  # type: ignore[arg-type]
            if not isinstance(materialized_no_anchor, Mapping):
                raise TypeError(
                    "Destination-aware JSON payload factory must return a Mapping, "
                    f"got {type(materialized_no_anchor).__name__}"
                )
            no_anchor_payload: Mapping[str, Any] = (
                on_child_dir_failure_transform(materialized_no_anchor)
                if on_child_dir_failure_transform is not None
                else materialized_no_anchor
            )
            if not isinstance(no_anchor_payload, Mapping):
                raise TypeError(
                    "on_child_dir_failure_transform must return a Mapping, "
                    f"got {type(no_anchor_payload).__name__}"
                )
        except Exception as exc:
            materialization_error = f"{type(exc).__name__}: {exc}"
            unavailable_memory_evidence = {
                "persisted": False,
                "path": None,
                "no_verified_anchor_available": True,
                "payload_materialized": False,
                "payload_materialization_error": materialization_error,
                "intended_child_dir_path": str(target_path),
                "intended_parent_retention_dir": (
                    str(parent_retention_dir)
                    if parent_retention_dir is not None
                    else None
                ),
                "unpersisted_reason": unpersisted_msg,
            }
            no_anchor_payload = unavailable_memory_evidence
    else:
        no_anchor_payload = (
            on_child_dir_failure_transform(payload)
            if on_child_dir_failure_transform is not None
            else payload
        )
    _record_retained_payload(no_anchor_payload)
    serialized = (
        json.dumps(no_anchor_payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")
    unpersisted_record: dict[str, Any] = {
        "path": None,
        "persisted": False,
        "no_verified_anchor_available": True,
        "sha256": _sha256_bytes(serialized),
        "size_bytes": len(serialized),
        "fallback_for_unwritable_or_damaged_child_dir": True,
        "fallback_for_damaged_or_replaced_parent_retention_dir": True,
        "intended_child_dir_path": str(target_path),
        "intended_parent_retention_dir": str(parent_retention_dir),
        "parent_retention_dir": None,
        "actual_retention_anchor_dir": None,
        "actual_retention_anchor_kind": None,
        "actual_retention_anchor_baseline": None,
        "child_dir_persistence_error": child_dir_unusable_reason,
        "parent_retention_dir_persistence_error": parent_dir_unusable_reason,
        "evidence_root_persistence_error": ev_err,
        "unpersisted_reason": unpersisted_msg,
    }
    if unavailable_memory_evidence is not None:
        unpersisted_record["payload_materialized"] = False
        unpersisted_record["payload_materialization_error"] = materialization_error
        unpersisted_record["unpersisted_memory_evidence"] = dict(
            unavailable_memory_evidence
        )
    return unpersisted_record


def _inspect_output_artifact(
    path: Path,
    *,
    root: Path,
    caught_exceptions: list[Exception] | None = None,
    expected_root_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Inspect an output path under ``root`` without following symlinks at ``root`` or any descendant."""
    normalized_root = Path(os.path.abspath(os.fspath(root)))
    normalized_path = Path(os.path.abspath(os.fspath(path)))

    if (
        expected_root_identity is not None
        and expected_root_identity.get("evidence_root") is not None
    ):
        ev_root_path = Path(
            os.path.abspath(os.fspath(str(expected_root_identity["evidence_root"])))
        )
        try:
            ev_st = os.lstat(ev_root_path)
            if stat.S_ISLNK(ev_st.st_mode) or not stat.S_ISDIR(ev_st.st_mode):
                raise ValueError(
                    f"Evidence root is not a non-symlink directory: {ev_root_path}"
                )
            if (
                expected_root_identity.get("evidence_root_dev") is not None
                and expected_root_identity.get("evidence_root_ino") is not None
                and (int(ev_st.st_dev), int(ev_st.st_ino))
                != (
                    int(expected_root_identity["evidence_root_dev"]),
                    int(expected_root_identity["evidence_root_ino"]),
                )
            ):
                raise ValueError(
                    f"Evidence root inode changed at {ev_root_path}"
                )
            if expected_root_identity.get("evidence_root_resolved_path") is not None:
                obs_ev_resolved = str(ev_root_path.resolve(strict=True))
                if obs_ev_resolved != str(
                    expected_root_identity["evidence_root_resolved_path"]
                ):
                    raise ValueError(
                        f"Evidence root resolved path changed at {ev_root_path}"
                    )
            if normalized_root != ev_root_path and normalized_root.is_relative_to(
                ev_root_path
            ):
                inter_cur = ev_root_path
                for part in normalized_root.relative_to(ev_root_path).parts[:-1]:
                    inter_cur = inter_cur / part
                    inter_st = os.lstat(inter_cur)
                    if stat.S_ISLNK(inter_st.st_mode) or not stat.S_ISDIR(
                        inter_st.st_mode
                    ):
                        raise ValueError(
                            f"Intermediate ancestor is not a non-symlink directory: {inter_cur}"
                        )
        except Exception as exc:
            if caught_exceptions is not None:
                caught_exceptions.append(exc)
            return {
                "path": str(normalized_path),
                "exists": False,
                "is_symlink": False,
                "is_regular_file": False,
                "within_refmac_dir": False,
                "resolved_path": None,
                "sha256": None,
                "size_bytes": None,
                "error": (
                    f"Evidence root verification failed at {ev_root_path} "
                    f"({type(exc).__name__}): {exc}"
                ),
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
                "errno": getattr(exc, "errno", None),
            }

    try:
        root_st = os.lstat(normalized_root)
    except OSError as exc:
        if caught_exceptions is not None:
            caught_exceptions.append(exc)
        return {
            "path": str(normalized_path),
            "exists": False,
            "is_symlink": False,
            "is_regular_file": False,
            "within_refmac_dir": False,
            "resolved_path": None,
            "sha256": None,
            "size_bytes": None,
            "error": (
                f"Refmac directory unavailable at {normalized_root} "
                f"({type(exc).__name__}): {exc}"
            ),
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "errno": getattr(exc, "errno", None),
        }

    if stat.S_ISLNK(root_st.st_mode):
        err_msg = (
            f"Refusing to inspect output under symlinked refmac directory: {normalized_root}"
        )
        exc_obj = ValueError(err_msg)
        if caught_exceptions is not None:
            caught_exceptions.append(exc_obj)
        return {
            "path": str(normalized_path),
            "exists": False,
            "is_symlink": True,
            "is_regular_file": False,
            "within_refmac_dir": False,
            "resolved_path": None,
            "sha256": None,
            "size_bytes": None,
            "error": err_msg,
            "exception_type": "ValueError",
            "exception_message": err_msg,
            "errno": None,
        }

    if not stat.S_ISDIR(root_st.st_mode):
        err_msg = f"Refmac root path is not a directory: {normalized_root}"
        exc_obj = ValueError(err_msg)
        if caught_exceptions is not None:
            caught_exceptions.append(exc_obj)
        return {
            "path": str(normalized_path),
            "exists": False,
            "is_symlink": False,
            "is_regular_file": False,
            "within_refmac_dir": False,
            "resolved_path": None,
            "sha256": None,
            "size_bytes": None,
            "error": err_msg,
            "exception_type": "ValueError",
            "exception_message": err_msg,
            "errno": None,
        }

    if (
        expected_root_identity is not None
        and expected_root_identity.get("dev") is not None
        and expected_root_identity.get("ino") is not None
    ):
        exp_dev = int(expected_root_identity["dev"])
        exp_ino = int(expected_root_identity["ino"])
        if (int(root_st.st_dev), int(root_st.st_ino)) != (exp_dev, exp_ino):
            err_msg = (
                f"Refmac directory inode changed at {normalized_root}: "
                f"expected (dev={exp_dev}, ino={exp_ino}), "
                f"observed (dev={int(root_st.st_dev)}, ino={int(root_st.st_ino)})"
            )
            exc_obj = ValueError(err_msg)
            if caught_exceptions is not None:
                caught_exceptions.append(exc_obj)
            return {
                "path": str(normalized_path),
                "exists": False,
                "is_symlink": False,
                "is_regular_file": False,
                "within_refmac_dir": False,
                "resolved_path": None,
                "sha256": None,
                "size_bytes": None,
                "error": err_msg,
                "exception_type": "ValueError",
                "exception_message": err_msg,
                "errno": None,
            }

    resolved_root = normalized_root.resolve(strict=True)
    if normalized_path == resolved_root or not normalized_path.is_relative_to(resolved_root):
        return {
            "path": str(path),
            "exists": False,
            "is_symlink": False,
            "is_regular_file": False,
            "within_refmac_dir": False,
            "resolved_path": None,
            "sha256": None,
            "size_bytes": None,
            "error": f"Output path {path} is outside refmac directory {resolved_root}",
        }

    current = resolved_root
    rel_parts = normalized_path.relative_to(resolved_root).parts
    for part in rel_parts[:-1]:
        current = current / part
        try:
            anc_st = os.lstat(current)
        except FileNotFoundError:
            return {
                "path": str(normalized_path),
                "exists": False,
                "is_symlink": False,
                "is_regular_file": False,
                "within_refmac_dir": True,
                "resolved_path": None,
                "sha256": None,
                "size_bytes": None,
                "error": None,
            }
        except OSError as exc:
            if caught_exceptions is not None:
                caught_exceptions.append(exc)
            return {
                "path": str(normalized_path),
                "exists": False,
                "is_symlink": False,
                "is_regular_file": False,
                "within_refmac_dir": False,
                "resolved_path": None,
                "sha256": None,
                "size_bytes": None,
                "error": (
                    f"Ancestor path inspection failed at {current} "
                    f"({type(exc).__name__}): {exc}"
                ),
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
                "errno": getattr(exc, "errno", None),
            }
        if stat.S_ISLNK(anc_st.st_mode):
            return {
                "path": str(normalized_path),
                "exists": True,
                "is_symlink": True,
                "is_regular_file": False,
                "within_refmac_dir": False,
                "resolved_path": None,
                "sha256": None,
                "size_bytes": None,
                "error": f"Ancestor directory was replaced by symlink: {current}",
            }
        if not stat.S_ISDIR(anc_st.st_mode):
            return {
                "path": str(normalized_path),
                "exists": False,
                "is_symlink": False,
                "is_regular_file": False,
                "within_refmac_dir": False,
                "resolved_path": None,
                "sha256": None,
                "size_bytes": None,
                "error": f"Ancestor component is not a directory: {current}",
            }

    try:
        st = os.lstat(normalized_path)
    except FileNotFoundError:
        return {
            "path": str(normalized_path),
            "exists": False,
            "is_symlink": False,
            "is_regular_file": False,
            "within_refmac_dir": True,
            "resolved_path": None,
            "sha256": None,
            "size_bytes": None,
            "error": None,
        }
    except OSError as exc:
        if caught_exceptions is not None:
            caught_exceptions.append(exc)
        return {
            "path": str(normalized_path),
            "exists": False,
            "is_symlink": False,
            "is_regular_file": False,
            "within_refmac_dir": True,
            "resolved_path": None,
            "sha256": None,
            "size_bytes": None,
            "error": (
                f"Failed to stat output path {normalized_path} "
                f"({type(exc).__name__}): {exc}"
            ),
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "errno": getattr(exc, "errno", None),
        }

    if stat.S_ISLNK(st.st_mode):
        return {
            "path": str(normalized_path),
            "exists": True,
            "is_symlink": True,
            "is_regular_file": False,
            "within_refmac_dir": False,
            "resolved_path": None,
            "sha256": None,
            "size_bytes": None,
            "error": f"Refusing to follow symlink at output path: {normalized_path}",
        }

    if not stat.S_ISREG(st.st_mode):
        return {
            "path": str(normalized_path),
            "exists": True,
            "is_symlink": False,
            "is_regular_file": False,
            "within_refmac_dir": True,
            "resolved_path": None,
            "sha256": None,
            "size_bytes": None,
            "error": f"Output path is not a regular file: {normalized_path}",
        }

    try:
        resolved_target = normalized_path.resolve(strict=True)
    except OSError as exc:
        if caught_exceptions is not None:
            caught_exceptions.append(exc)
        return {
            "path": str(normalized_path),
            "exists": True,
            "is_symlink": False,
            "is_regular_file": True,
            "within_refmac_dir": False,
            "resolved_path": None,
            "sha256": None,
            "size_bytes": int(st.st_size),
            "error": (
                f"Failed to resolve regular file path {normalized_path} "
                f"({type(exc).__name__}): {exc}"
            ),
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "errno": getattr(exc, "errno", None),
        }

    if not resolved_target.is_relative_to(resolved_root):
        return {
            "path": str(normalized_path),
            "exists": True,
            "is_symlink": False,
            "is_regular_file": True,
            "within_refmac_dir": False,
            "resolved_path": str(resolved_target),
            "sha256": None,
            "size_bytes": None,
            "error": f"Resolved output path escaped refmac directory: {resolved_target}",
        }

    try:
        data = normalized_path.read_bytes()
    except OSError as exc:
        if caught_exceptions is not None:
            caught_exceptions.append(exc)
        return {
            "path": str(normalized_path),
            "exists": True,
            "is_symlink": False,
            "is_regular_file": True,
            "within_refmac_dir": True,
            "resolved_path": str(resolved_target),
            "sha256": None,
            "size_bytes": int(st.st_size),
            "error": (
                f"Failed to read regular file {normalized_path} "
                f"({type(exc).__name__}): {exc}"
            ),
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "errno": getattr(exc, "errno", None),
        }

    return {
        "path": str(normalized_path),
        "exists": True,
        "is_symlink": False,
        "is_regular_file": True,
        "within_refmac_dir": True,
        "resolved_path": str(resolved_target),
        "sha256": _sha256_bytes(data),
        "size_bytes": len(data),
        "error": None,
    }


def _build_helper_source_baseline() -> dict[str, dict[str, Any]]:
    """Hash this collector and its imported repository helper modules."""
    module_candidates = {
        "audit_1sar_retained_evidence_py": Path(
            audit_1sar_retained_evidence.__file__
        ),
        "onesar_refmac_py": Path(__file__),
        "onesar_refmac_log_py": Path(onesar_refmac_log.__file__),
        "onesar_rerun_py": Path(onesar_rerun.__file__),
        "t03_reflection_retention_py": Path(t03_reflection_retention.__file__),
        "toolchain_py": Path(toolchain.__file__),
    }
    baseline: dict[str, dict[str, Any]] = {}
    for label, mod_path in sorted(module_candidates.items()):
        resolved_path = mod_path.resolve(strict=True)
        digest = _sha256_regular_file(resolved_path)
        size_bytes = resolved_path.stat().st_size
        baseline[label] = {
            "path": str(resolved_path),
            "sha256": digest,
            "size_bytes": int(size_bytes),
        }
    return baseline


def _build_staged_input_baseline(staged: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Hash all staged immutable input files (including ``input_admission.json``) into an in-memory baseline."""
    admission_record = staged.get("admission_record")
    if not isinstance(admission_record, Mapping):
        raise ValueError("stage_subject_inputs did not return an admission_record mapping")
    staged_files_meta = admission_record.get("staged_files")
    if not isinstance(staged_files_meta, Mapping):
        raise ValueError("admission_record missing staged_files mapping")

    file_specs: tuple[tuple[str, Path, str | None], ...] = (
        (
            "original_model_pdb",
            Path(staged["original_pdb_path"]),
            staged_files_meta.get("original_model_pdb_sha256"),
        ),
        (
            "original_data_mtz",
            Path(staged["original_mtz_path"]),
            staged_files_meta.get("original_data_mtz_sha256"),
        ),
        (
            "projected_observations_mtz",
            Path(staged["projected_mtz_path"]),
            staged_files_meta.get("projected_observations_mtz_sha256"),
        ),
        (
            "input_hkl_ledger_json",
            Path(staged["input_ledger_path"]),
            staged_files_meta.get("input_hkl_ledger_json_sha256"),
        ),
        (
            "input_admission_json",
            Path(staged["admission_json_path"]),
            None,
        ),
    )

    evidence_root_for_inputs = (
        Path(staged["evidence_root"])
        if staged.get("evidence_root") is not None
        else None
    )
    baseline: dict[str, dict[str, Any]] = {}
    for key, file_path, expected_sha256 in file_specs:
        resolved_path = file_path.resolve(strict=True)
        digest = _sha256_regular_file(file_path)
        if expected_sha256 is not None and digest != expected_sha256:
            raise ValueError(
                f"Staged input {key} at {file_path} SHA-256 {digest} does not match "
                f"admission_record {expected_sha256}"
            )
        size_bytes = file_path.stat().st_size
        entry: dict[str, Any] = {
            "path": str(file_path),
            "resolved_path": str(resolved_path),
            "sha256": digest,
            "size_bytes": int(size_bytes),
        }
        if evidence_root_for_inputs is not None:
            entry.update(
                _build_file_ancestor_chain_baseline(
                    file_path, evidence_root=evidence_root_for_inputs
                )
            )
        baseline[key] = entry

    on_disk_admission = json.loads(
        Path(staged["admission_json_path"]).read_text(encoding="utf-8")
    )
    if on_disk_admission != admission_record:
        raise ValueError(
            "Staged input_admission.json content does not match returned admission_record"
        )
    return baseline


def _verify_immutable_baselines_post_run(
    staged_input_baseline: Mapping[str, Mapping[str, Any]],
    helper_source_baseline: Mapping[str, Mapping[str, Any]],
    keywords_baseline: Mapping[str, Any],
    *,
    pre_execution_checkpoint_baseline: Mapping[str, Any] | None = None,
    caught_exceptions: list[Exception] | None = None,
    mutation_causes_out: list[Exception | None] | None = None,
    pre_checkpoint_cause_out: list[Exception | None] | None = None,
) -> dict[str, Any]:
    """Re-hash staged inputs, helper sources, keywords file, and pre-execution checkpoint after child execution."""
    mutations: list[dict[str, Any]] = []
    post_staged_inputs: dict[str, dict[str, Any]] = {}
    post_helper_sources: dict[str, dict[str, Any]] = {}

    for key, expected in sorted(staged_input_baseline.items()):
        path = Path(expected["path"])
        anc_check = _verify_admitted_ancestor_chain(path, expected)
        if not anc_check["verified"]:
            anc_exc = anc_check.get("exception")
            if caught_exceptions is not None and isinstance(anc_exc, Exception):
                caught_exceptions.append(anc_exc)
            err_msg = str(anc_check["error"])
            post_staged_inputs[key] = {
                "path": str(path),
                "resolved_path": None,
                "sha256": None,
                "size_bytes": None,
                "ancestor_chain_verified": False,
                "damaged_ancestor_path": anc_check["damaged_ancestor_path"],
                "damaged_ancestor_is_symlink": bool(
                    anc_check["damaged_ancestor_is_symlink"]
                ),
                "matches_baseline": False,
                "error": err_msg,
            }
            mutations.append(
                {
                    "category": "staged_input",
                    "key": key,
                    "path": str(path),
                    "expected_sha256": expected["sha256"],
                    "actual_sha256": None,
                    "ancestor_chain_verified": False,
                    "damaged_ancestor_path": anc_check["damaged_ancestor_path"],
                    "reason": (
                        f"Staged input file ancestor chain invalid after REFMAC operation: {err_msg}"
                    ),
                }
            )
            if mutation_causes_out is not None:
                mutation_causes_out.append(
                    anc_exc if isinstance(anc_exc, Exception) else None
                )
            continue
        try:
            st = os.lstat(path)
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
                raise ValueError(f"Staged input path is not a regular non-symlink file: {path}")
            actual_sha256 = _sha256_regular_file(path)
            actual_resolved = str(path.resolve(strict=True))
            actual_size = int(st.st_size)
            inode_ok = (
                expected.get("dev") is None
                or expected.get("ino") is None
                or (int(st.st_dev), int(st.st_ino))
                == (int(expected["dev"]), int(expected["ino"]))
            )
            matches = (
                actual_sha256 == expected["sha256"]
                and actual_resolved == expected["resolved_path"]
                and actual_size == expected["size_bytes"]
                and inode_ok
            )
            post_staged_inputs[key] = {
                "path": str(path),
                "resolved_path": actual_resolved,
                "sha256": actual_sha256,
                "size_bytes": actual_size,
                "ancestor_chain_verified": True,
                "matches_baseline": matches,
                "error": None,
            }
            if not matches:
                mutations.append(
                    {
                        "category": "staged_input",
                        "key": key,
                        "path": str(path),
                        "expected_sha256": expected["sha256"],
                        "actual_sha256": actual_sha256,
                        "reason": "Staged input file mutated during REFMAC operation",
                    }
                )
                if mutation_causes_out is not None:
                    mutation_causes_out.append(None)
        except Exception as exc:
            if caught_exceptions is not None:
                caught_exceptions.append(exc)
            post_staged_inputs[key] = {
                "path": str(path),
                "resolved_path": None,
                "sha256": None,
                "size_bytes": None,
                "ancestor_chain_verified": True,
                "matches_baseline": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
            mutations.append(
                {
                    "category": "staged_input",
                    "key": key,
                    "path": str(path),
                    "expected_sha256": expected["sha256"],
                    "actual_sha256": None,
                    "reason": f"Staged input file missing or invalid after REFMAC operation: {exc}",
                }
            )
            if mutation_causes_out is not None:
                mutation_causes_out.append(exc)

    for key, expected in sorted(helper_source_baseline.items()):
        path = Path(expected["path"])
        try:
            actual_sha256 = _sha256_regular_file(path)
            actual_size = int(path.stat().st_size)
            matches = (
                actual_sha256 == expected["sha256"]
                and actual_size == expected["size_bytes"]
            )
            post_helper_sources[key] = {
                "path": str(path),
                "sha256": actual_sha256,
                "size_bytes": actual_size,
                "matches_baseline": matches,
                "error": None,
            }
            if not matches:
                mutations.append(
                    {
                        "category": "helper_source",
                        "key": key,
                        "path": str(path),
                        "expected_sha256": expected["sha256"],
                        "actual_sha256": actual_sha256,
                        "reason": "Helper/source file mutated during REFMAC operation",
                    }
                )
                if mutation_causes_out is not None:
                    mutation_causes_out.append(None)
        except Exception as exc:
            if caught_exceptions is not None:
                caught_exceptions.append(exc)
            post_helper_sources[key] = {
                "path": str(path),
                "sha256": None,
                "size_bytes": None,
                "matches_baseline": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
            mutations.append(
                {
                    "category": "helper_source",
                    "key": key,
                    "path": str(path),
                    "expected_sha256": expected["sha256"],
                    "actual_sha256": None,
                    "reason": f"Helper/source file missing or invalid after REFMAC operation: {exc}",
                }
            )
            if mutation_causes_out is not None:
                mutation_causes_out.append(exc)

    kw_path = Path(keywords_baseline["path"])
    kw_anc_check = _verify_admitted_ancestor_chain(kw_path, keywords_baseline)
    if not kw_anc_check["verified"]:
        kw_anc_exc = kw_anc_check.get("exception")
        if caught_exceptions is not None and isinstance(kw_anc_exc, Exception):
            caught_exceptions.append(kw_anc_exc)
        kw_err = str(kw_anc_check["error"])
        keywords_post: dict[str, Any] = {
            "path": str(kw_path),
            "resolved_path": None,
            "sha256": None,
            "size_bytes": None,
            "ancestor_chain_verified": False,
            "damaged_ancestor_path": kw_anc_check["damaged_ancestor_path"],
            "damaged_ancestor_is_symlink": bool(
                kw_anc_check["damaged_ancestor_is_symlink"]
            ),
            "damaged_ancestor_symlink_target": kw_anc_check[
                "damaged_ancestor_symlink_target"
            ],
            "matches_baseline": False,
            "error": kw_err,
        }
        mutations.append(
            {
                "category": "keywords_file",
                "key": "refmac_keywords_txt",
                "path": str(kw_path),
                "expected_sha256": keywords_baseline["sha256"],
                "actual_sha256": None,
                "ancestor_chain_verified": False,
                "damaged_ancestor_path": kw_anc_check["damaged_ancestor_path"],
                "damaged_ancestor_is_symlink": bool(
                    kw_anc_check["damaged_ancestor_is_symlink"]
                ),
                "reason": (
                    f"Staged refmac_keywords.txt ancestor chain invalid after REFMAC operation: {kw_err}"
                ),
            }
        )
        if mutation_causes_out is not None:
            mutation_causes_out.append(
                kw_anc_exc if isinstance(kw_anc_exc, Exception) else None
            )
    else:
        try:
            kw_st = os.lstat(kw_path)
            if stat.S_ISLNK(kw_st.st_mode):
                raise ValueError(f"Refusing symlink keywords file: {kw_path}")
            if not stat.S_ISREG(kw_st.st_mode):
                raise ValueError(f"Keywords file is not a regular file: {kw_path}")
            kw_resolved = str(kw_path.resolve(strict=True))
            kw_sha256 = _sha256_regular_file(kw_path)
            kw_size = int(kw_st.st_size)
            kw_resolved_ok = (
                keywords_baseline.get("resolved_path") is None
                or kw_resolved == str(keywords_baseline["resolved_path"])
            )
            kw_inode_ok = (
                keywords_baseline.get("dev") is None
                or keywords_baseline.get("ino") is None
                or (int(kw_st.st_dev), int(kw_st.st_ino))
                == (
                    int(keywords_baseline["dev"]),
                    int(keywords_baseline["ino"]),
                )
            )
            kw_matches = (
                kw_sha256 == keywords_baseline["sha256"]
                and kw_size == keywords_baseline["size_bytes"]
                and kw_resolved_ok
                and kw_inode_ok
            )
            keywords_post = {
                "path": str(kw_path),
                "resolved_path": kw_resolved,
                "sha256": kw_sha256,
                "size_bytes": kw_size,
                "ancestor_chain_verified": True,
                "matches_baseline": kw_matches,
                "error": None,
            }
            if not kw_matches:
                mutations.append(
                    {
                        "category": "keywords_file",
                        "key": "refmac_keywords_txt",
                        "path": str(kw_path),
                        "expected_sha256": keywords_baseline["sha256"],
                        "actual_sha256": kw_sha256,
                        "reason": "Staged refmac_keywords.txt mutated during REFMAC operation",
                    }
                )
                if mutation_causes_out is not None:
                    mutation_causes_out.append(None)
        except Exception as exc:
            if caught_exceptions is not None:
                caught_exceptions.append(exc)
            keywords_post = {
                "path": str(kw_path),
                "resolved_path": None,
                "sha256": None,
                "size_bytes": None,
                "ancestor_chain_verified": True,
                "matches_baseline": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
            mutations.append(
                {
                    "category": "keywords_file",
                    "key": "refmac_keywords_txt",
                    "path": str(kw_path),
                    "expected_sha256": keywords_baseline["sha256"],
                    "actual_sha256": None,
                    "reason": f"Staged refmac_keywords.txt missing or invalid after REFMAC operation: {exc}",
                }
            )
            if mutation_causes_out is not None:
                mutation_causes_out.append(exc)

    report: dict[str, Any] = {
        "verified": len(mutations) == 0,
        "staged_inputs_baseline": copy.deepcopy(dict(staged_input_baseline)),
        "staged_inputs_post_run": post_staged_inputs,
        "helper_sources_baseline": copy.deepcopy(dict(helper_source_baseline)),
        "helper_sources_post_run": post_helper_sources,
        "keywords_file_baseline": copy.deepcopy(dict(keywords_baseline)),
        "keywords_file_post_run": keywords_post,
        "mutations": mutations,
    }

    if pre_execution_checkpoint_baseline is not None:
        cp_path = Path(pre_execution_checkpoint_baseline["path"])
        expected_cp_sha256 = pre_execution_checkpoint_baseline["sha256"]
        expected_cp_size = int(pre_execution_checkpoint_baseline["size_bytes"])
        cp_anc_check = _verify_admitted_ancestor_chain(
            cp_path, pre_execution_checkpoint_baseline
        )
        if not cp_anc_check["verified"]:
            cp_anc_exc = cp_anc_check.get("exception")
            cp_bound_anc_exc = (
                cp_anc_exc if isinstance(cp_anc_exc, Exception) else None
            )
            if caught_exceptions is not None and cp_bound_anc_exc is not None:
                caught_exceptions.append(cp_bound_anc_exc)
            if pre_checkpoint_cause_out is not None:
                pre_checkpoint_cause_out.append(cp_bound_anc_exc)
            if mutation_causes_out is not None:
                mutation_causes_out.append(cp_bound_anc_exc)
            cp_err = str(cp_anc_check["error"])
            cp_reason = (
                "Pre-execution checkpoint refmac_pre_execution_checkpoint.json "
                f"ancestor chain invalid after REFMAC operation: {cp_err}"
            )
            pre_checkpoint_post: dict[str, Any] = {
                "path": str(cp_path),
                "resolved_path": None,
                "exists": False,
                "is_symlink": bool(cp_anc_check["damaged_ancestor_is_symlink"]),
                "is_regular_file": False,
                "sha256": None,
                "size_bytes": None,
                "expected_sha256": expected_cp_sha256,
                "expected_size_bytes": expected_cp_size,
                "expected_resolved_path": pre_execution_checkpoint_baseline.get(
                    "resolved_path"
                ),
                "expected_parent_dir_dev": cp_anc_check["expected_ancestor_dev"],
                "expected_parent_dir_ino": cp_anc_check["expected_ancestor_ino"],
                "ancestor_chain_verified": False,
                "damaged_ancestor_path": cp_anc_check["damaged_ancestor_path"],
                "damaged_ancestor_is_symlink": bool(
                    cp_anc_check["damaged_ancestor_is_symlink"]
                ),
                "damaged_ancestor_symlink_target": cp_anc_check[
                    "damaged_ancestor_symlink_target"
                ],
                "observed_ancestor_dev": cp_anc_check["observed_ancestor_dev"],
                "observed_ancestor_ino": cp_anc_check["observed_ancestor_ino"],
                "matches_baseline": False,
                "error": cp_err,
                "exception_type": str(
                    cp_anc_check["exception_type"] or "ValueError"
                ),
                "exception_message": str(
                    cp_anc_check["exception_message"] or cp_err
                ),
                "errno": cp_anc_check["errno"],
                "reason": cp_reason,
            }
            mutations.append(
                {
                    "category": "pre_execution_checkpoint",
                    "key": "refmac_pre_execution_checkpoint_json",
                    "path": str(cp_path),
                    "expected_sha256": expected_cp_sha256,
                    "expected_size_bytes": expected_cp_size,
                    "actual_sha256": None,
                    "actual_size_bytes": None,
                    "exists_post_run": False,
                    "is_symlink_post_run": bool(
                        cp_anc_check["damaged_ancestor_is_symlink"]
                    ),
                    "is_regular_file_post_run": False,
                    "ancestor_chain_verified": False,
                    "damaged_ancestor_path": cp_anc_check["damaged_ancestor_path"],
                    "damaged_ancestor_is_symlink": bool(
                        cp_anc_check["damaged_ancestor_is_symlink"]
                    ),
                    "damaged_ancestor_symlink_target": cp_anc_check[
                        "damaged_ancestor_symlink_target"
                    ],
                    "error": cp_err,
                    "exception_type": str(
                        cp_anc_check["exception_type"] or "ValueError"
                    ),
                    "exception_message": str(
                        cp_anc_check["exception_message"] or cp_err
                    ),
                    "reason": cp_reason,
                }
            )
        else:
            try:
                cp_st = os.lstat(cp_path)
                cp_is_symlink = bool(stat.S_ISLNK(cp_st.st_mode))
                cp_is_regular = bool(stat.S_ISREG(cp_st.st_mode))
                if cp_is_symlink:
                    cp_err = (
                        f"Pre-execution checkpoint path was replaced by a symlink: {cp_path}"
                    )
                    cp_reason = (
                        "Pre-execution checkpoint refmac_pre_execution_checkpoint.json "
                        "was replaced by a symlink during REFMAC operation"
                    )
                    cp_sym_exc = ValueError(cp_err)
                    if caught_exceptions is not None:
                        caught_exceptions.append(cp_sym_exc)
                    if pre_checkpoint_cause_out is not None:
                        pre_checkpoint_cause_out.append(cp_sym_exc)
                    if mutation_causes_out is not None:
                        mutation_causes_out.append(cp_sym_exc)
                    pre_checkpoint_post = {
                        "path": str(cp_path),
                        "resolved_path": None,
                        "exists": True,
                        "is_symlink": True,
                        "is_regular_file": False,
                        "sha256": None,
                        "size_bytes": int(cp_st.st_size),
                        "expected_sha256": expected_cp_sha256,
                        "expected_size_bytes": expected_cp_size,
                        "ancestor_chain_verified": True,
                        "matches_baseline": False,
                        "error": cp_err,
                        "exception_type": "ValueError",
                        "exception_message": cp_err,
                        "errno": None,
                        "reason": cp_reason,
                    }
                    mutations.append(
                        {
                            "category": "pre_execution_checkpoint",
                            "key": "refmac_pre_execution_checkpoint_json",
                            "path": str(cp_path),
                            "expected_sha256": expected_cp_sha256,
                            "expected_size_bytes": expected_cp_size,
                            "actual_sha256": None,
                            "actual_size_bytes": int(cp_st.st_size),
                            "exists_post_run": True,
                            "is_symlink_post_run": True,
                            "is_regular_file_post_run": False,
                            "ancestor_chain_verified": True,
                            "error": cp_err,
                            "exception_type": "ValueError",
                            "exception_message": cp_err,
                            "reason": cp_reason,
                        }
                    )
                elif not cp_is_regular:
                    cp_err = (
                        f"Pre-execution checkpoint path is not a regular file: {cp_path}"
                    )
                    cp_reason = (
                        "Pre-execution checkpoint refmac_pre_execution_checkpoint.json "
                        "is not a regular file after REFMAC operation"
                    )
                    cp_reg_exc = ValueError(cp_err)
                    if caught_exceptions is not None:
                        caught_exceptions.append(cp_reg_exc)
                    if pre_checkpoint_cause_out is not None:
                        pre_checkpoint_cause_out.append(cp_reg_exc)
                    if mutation_causes_out is not None:
                        mutation_causes_out.append(cp_reg_exc)
                    pre_checkpoint_post = {
                        "path": str(cp_path),
                        "resolved_path": None,
                        "exists": True,
                        "is_symlink": False,
                        "is_regular_file": False,
                        "sha256": None,
                        "size_bytes": int(cp_st.st_size),
                        "expected_sha256": expected_cp_sha256,
                        "expected_size_bytes": expected_cp_size,
                        "ancestor_chain_verified": True,
                        "matches_baseline": False,
                        "error": cp_err,
                        "exception_type": "ValueError",
                        "exception_message": cp_err,
                        "errno": None,
                        "reason": cp_reason,
                    }
                    mutations.append(
                        {
                            "category": "pre_execution_checkpoint",
                            "key": "refmac_pre_execution_checkpoint_json",
                            "path": str(cp_path),
                            "expected_sha256": expected_cp_sha256,
                            "expected_size_bytes": expected_cp_size,
                            "actual_sha256": None,
                            "actual_size_bytes": int(cp_st.st_size),
                            "exists_post_run": True,
                            "is_symlink_post_run": False,
                            "is_regular_file_post_run": False,
                            "ancestor_chain_verified": True,
                            "error": cp_err,
                            "exception_type": "ValueError",
                            "exception_message": cp_err,
                            "reason": cp_reason,
                        }
                    )
                else:
                    try:
                        cp_resolved = str(cp_path.resolve(strict=True))
                        cp_bytes = cp_path.read_bytes()
                    except OSError as exc:
                        if caught_exceptions is not None:
                            caught_exceptions.append(exc)
                        if pre_checkpoint_cause_out is not None:
                            pre_checkpoint_cause_out.append(exc)
                        if mutation_causes_out is not None:
                            mutation_causes_out.append(exc)
                        cp_err = f"{type(exc).__name__}: {exc}"
                        cp_reason = (
                            "Pre-execution checkpoint refmac_pre_execution_checkpoint.json "
                            f"unreadable after REFMAC operation: {exc}"
                        )
                        pre_checkpoint_post = {
                            "path": str(cp_path),
                            "resolved_path": None,
                            "exists": True,
                            "is_symlink": False,
                            "is_regular_file": True,
                            "sha256": None,
                            "size_bytes": int(cp_st.st_size),
                            "expected_sha256": expected_cp_sha256,
                            "expected_size_bytes": expected_cp_size,
                            "ancestor_chain_verified": True,
                            "matches_baseline": False,
                            "error": cp_err,
                            "exception_type": type(exc).__name__,
                            "exception_message": str(exc),
                            "errno": getattr(exc, "errno", None),
                            "reason": cp_reason,
                        }
                        mutations.append(
                            {
                                "category": "pre_execution_checkpoint",
                                "key": "refmac_pre_execution_checkpoint_json",
                                "path": str(cp_path),
                                "expected_sha256": expected_cp_sha256,
                                "expected_size_bytes": expected_cp_size,
                                "actual_sha256": None,
                                "actual_size_bytes": int(cp_st.st_size),
                                "exists_post_run": True,
                                "is_symlink_post_run": False,
                                "is_regular_file_post_run": True,
                                "ancestor_chain_verified": True,
                                "error": cp_err,
                                "exception_type": type(exc).__name__,
                                "exception_message": str(exc),
                                "reason": cp_reason,
                            }
                        )
                    else:
                        cp_sha256 = _sha256_bytes(cp_bytes)
                        cp_size = len(cp_bytes)
                        expected_cp_resolved = pre_execution_checkpoint_baseline.get(
                            "resolved_path"
                        )
                        expected_cp_dev = pre_execution_checkpoint_baseline.get("dev")
                        expected_cp_ino = pre_execution_checkpoint_baseline.get("ino")
                        cp_resolved_ok = (
                            expected_cp_resolved is None
                            or cp_resolved == str(expected_cp_resolved)
                        )
                        cp_inode_ok = (
                            expected_cp_dev is None
                            or expected_cp_ino is None
                            or (int(cp_st.st_dev), int(cp_st.st_ino))
                            == (int(expected_cp_dev), int(expected_cp_ino))
                        )
                        cp_matches = (
                            cp_sha256 == expected_cp_sha256
                            and cp_size == expected_cp_size
                            and cp_resolved_ok
                            and cp_inode_ok
                        )
                        cp_err = (
                            None
                            if cp_matches
                            else (
                                f"Pre-execution checkpoint {cp_path} mutated during REFMAC operation: "
                                f"expected sha256={expected_cp_sha256} (size={expected_cp_size}), "
                                f"observed sha256={cp_sha256} (size={cp_size})"
                            )
                        )
                        cp_reason = (
                            None
                            if cp_matches
                            else (
                                "Pre-execution checkpoint refmac_pre_execution_checkpoint.json "
                                "mutated during REFMAC operation"
                            )
                        )
                        cp_mut_exc = (
                            ValueError(cp_err)
                            if (not cp_matches and cp_err is not None)
                            else None
                        )
                        if cp_mut_exc is not None and caught_exceptions is not None:
                            caught_exceptions.append(cp_mut_exc)
                        pre_checkpoint_post = {
                            "path": str(cp_path),
                            "resolved_path": cp_resolved,
                            "exists": True,
                            "is_symlink": False,
                            "is_regular_file": True,
                            "sha256": cp_sha256,
                            "size_bytes": cp_size,
                            "expected_sha256": expected_cp_sha256,
                            "expected_size_bytes": expected_cp_size,
                            "ancestor_chain_verified": True,
                            "matches_baseline": cp_matches,
                            "error": cp_err,
                            "exception_type": None if cp_matches else "ValueError",
                            "exception_message": cp_err,
                            "errno": None,
                            "reason": cp_reason,
                        }
                        if not cp_matches:
                            if pre_checkpoint_cause_out is not None:
                                pre_checkpoint_cause_out.append(cp_mut_exc)
                            if mutation_causes_out is not None:
                                mutation_causes_out.append(cp_mut_exc)
                            mutations.append(
                                {
                                    "category": "pre_execution_checkpoint",
                                    "key": "refmac_pre_execution_checkpoint_json",
                                    "path": str(cp_path),
                                    "expected_sha256": expected_cp_sha256,
                                    "expected_size_bytes": expected_cp_size,
                                    "actual_sha256": cp_sha256,
                                    "actual_size_bytes": cp_size,
                                    "exists_post_run": True,
                                    "is_symlink_post_run": False,
                                    "is_regular_file_post_run": True,
                                    "ancestor_chain_verified": True,
                                    "error": cp_err,
                                    "exception_type": "ValueError",
                                    "exception_message": cp_err,
                                    "reason": cp_reason,
                                }
                            )
            except Exception as exc:
                if caught_exceptions is not None:
                    caught_exceptions.append(exc)
                if pre_checkpoint_cause_out is not None:
                    pre_checkpoint_cause_out.append(exc)
                if mutation_causes_out is not None:
                    mutation_causes_out.append(exc)
                cp_err = f"{type(exc).__name__}: {exc}"
                cp_reason = (
                    "Pre-execution checkpoint refmac_pre_execution_checkpoint.json "
                    f"missing or invalid after REFMAC operation: {exc}"
                )
                pre_checkpoint_post = {
                    "path": str(cp_path),
                    "resolved_path": None,
                    "exists": False,
                    "is_symlink": False,
                    "is_regular_file": False,
                    "sha256": None,
                    "size_bytes": None,
                    "expected_sha256": expected_cp_sha256,
                    "expected_size_bytes": expected_cp_size,
                    "ancestor_chain_verified": True,
                    "matches_baseline": False,
                    "error": cp_err,
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                    "errno": getattr(exc, "errno", None),
                    "reason": cp_reason,
                }
                mutations.append(
                    {
                        "category": "pre_execution_checkpoint",
                        "key": "refmac_pre_execution_checkpoint_json",
                        "path": str(cp_path),
                        "expected_sha256": expected_cp_sha256,
                        "expected_size_bytes": expected_cp_size,
                        "actual_sha256": None,
                        "actual_size_bytes": None,
                        "exists_post_run": False,
                        "is_symlink_post_run": False,
                        "is_regular_file_post_run": False,
                        "ancestor_chain_verified": True,
                        "error": cp_err,
                        "exception_type": type(exc).__name__,
                        "exception_message": str(exc),
                        "reason": cp_reason,
                    }
                )

        report["pre_execution_checkpoint_baseline"] = copy.deepcopy(
            dict(pre_execution_checkpoint_baseline)
        )
        report["pre_execution_checkpoint_post_run"] = pre_checkpoint_post
        report["pre_execution_checkpoint_verified"] = bool(
            pre_checkpoint_post["matches_baseline"]
        )
        report["verified"] = len(mutations) == 0

    return report


def _resolve_ccp4_refmac_toolchain() -> tuple[dict[str, Any], dict[str, str], Path]:
    """Resolve CCP4_SETUP and refmac5 binary identity and load the CCP4 environment once."""
    configured_setup = toolchain._configured_path(
        "PROTSTRUCT_CCP4_SETUP", toolchain.CCP4_SETUP
    )
    try:
        setup_lstat = os.lstat(configured_setup)
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"Configured CCP4 setup script not found: {configured_setup}"
        ) from exc

    setup_is_symlink = stat.S_ISLNK(setup_lstat.st_mode)
    resolved_setup = configured_setup.resolve(strict=True)
    setup_sha256 = _sha256_regular_file(resolved_setup)
    setup_size_bytes = int(resolved_setup.stat().st_size)

    if resolved_setup.parent.name == "bin":
        configured_prefix = resolved_setup.parent.parent.resolve(strict=True)
    else:
        configured_prefix = resolved_setup.parent.resolve(strict=True)
    if not configured_prefix.is_dir():
        raise ValueError(
            f"Derived CCP4 installation prefix is not a directory: {configured_prefix}"
        )
    if not resolved_setup.is_relative_to(configured_prefix):
        raise ValueError(
            f"Resolved CCP4 setup script {resolved_setup} is not inside prefix {configured_prefix}"
        )

    raw_ccp4_env = toolchain.ccp4_environment(setup_path=resolved_setup)
    if not isinstance(raw_ccp4_env, Mapping):
        raise ValueError("toolchain.ccp4_environment did not return a mapping")
    ccp4_env: dict[str, str] = {
        str(k): str(v) for k, v in dict(raw_ccp4_env).items()
    }

    env_ccp4_raw = ccp4_env.get("CCP4")
    resolved_env_ccp4_prefix: Path | None = None
    if isinstance(env_ccp4_raw, str) and env_ccp4_raw.strip():
        resolved_env_ccp4_prefix = (
            Path(env_ccp4_raw).expanduser().resolve(strict=True)
        )
        if resolved_env_ccp4_prefix != configured_prefix:
            raise ValueError(
                f"Sourced CCP4 variable {resolved_env_ccp4_prefix} disagrees with setup-derived "
                f"installation prefix {configured_prefix}"
            )

    env_path_value = ccp4_env.get("PATH", "")
    if not isinstance(env_path_value, str) or not env_path_value.strip():
        raise ValueError("Sourced CCP4 environment has an empty PATH")

    which_refmac = shutil.which("refmac5", path=env_path_value)
    if which_refmac is None:
        raise FileNotFoundError(
            "refmac5 executable not found on sourced CCP4 environment PATH"
        )

    discovered_refmac = Path(os.path.abspath(os.fspath(Path(which_refmac))))
    refmac_lstat = os.lstat(discovered_refmac)
    refmac_is_symlink = stat.S_ISLNK(refmac_lstat.st_mode)
    resolved_refmac = discovered_refmac.resolve(strict=True)
    refmac_sha256 = _sha256_regular_file(resolved_refmac)
    refmac_size_bytes = int(resolved_refmac.stat().st_size)

    if not os.access(resolved_refmac, os.X_OK):
        raise ValueError(
            f"Resolved refmac5 binary is not executable: {resolved_refmac}"
        )
    if not discovered_refmac.is_relative_to(configured_prefix):
        raise ValueError(
            f"Discovered refmac5 path {discovered_refmac} is outside configured CCP4 prefix {configured_prefix}"
        )
    if not resolved_refmac.is_relative_to(configured_prefix):
        raise ValueError(
            f"Resolved refmac5 binary {resolved_refmac} is outside configured CCP4 prefix {configured_prefix}"
        )

    bound_config: dict[str, str] = {}
    for key in NON_SECRET_CCP4_ENV_KEYS:
        val = ccp4_env.get(key)
        if isinstance(val, str):
            bound_config[key] = val

    prefix_path_entries: list[str] = []
    for raw_entry in env_path_value.split(os.pathsep):
        if not raw_entry:
            continue
        try:
            resolved_entry = Path(raw_entry).expanduser().resolve(strict=True)
        except Exception:
            continue
        if resolved_entry.is_relative_to(configured_prefix):
            prefix_path_entries.append(str(resolved_entry))

    toolchain_record: dict[str, Any] = {
        "expected_ccp4_version": toolchain.CCP4_VERSION,
        "configured_installation_prefix": str(configured_prefix),
        "setup_script": {
            "configured_path": str(configured_setup),
            "resolved_path": str(resolved_setup),
            "is_symlink": bool(setup_is_symlink),
            "within_prefix": True,
            "sha256": setup_sha256,
            "size_bytes": setup_size_bytes,
        },
        "refmac5_binary": {
            "discovered_path": str(discovered_refmac),
            "resolved_path": str(resolved_refmac),
            "is_symlink": bool(refmac_is_symlink),
            "within_prefix": True,
            "executable": True,
            "sha256": refmac_sha256,
            "size_bytes": refmac_size_bytes,
        },
        "bound_ccp4_configuration": bound_config,
        "prefix_path_entries": prefix_path_entries,
    }
    return toolchain_record, ccp4_env, resolved_refmac


def _extract_native_log_diagnostics(log_text: str) -> dict[str, Any]:
    """Extract banner identity, echoed keywords, completion markers, and warnings from raw REFMAC log text."""
    lines = log_text.splitlines()
    reported_suite: str | None = None
    reported_program: str | None = None
    reported_version: str | None = None
    reported_run_date: str | None = None
    reported_run_time: str | None = None
    echoed_data_lines: list[dict[str, Any]] = []
    echoed_ncyc_lines: list[dict[str, Any]] = []
    refinement_cycles_lines: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    error_lines: list[dict[str, Any]] = []
    end_of_refmac_lines: list[dict[str, Any]] = []
    normal_termination_lines: list[dict[str, Any]] = []
    times_lines: list[dict[str, Any]] = []

    for idx, raw_line in enumerate(lines):
        line_no = idx + 1
        banner_match = _LOG_BANNER_RE.search(raw_line)
        if banner_match and reported_version is None:
            reported_suite = banner_match.group(1)
            reported_program = banner_match.group(2)
            reported_version = banner_match.group(3)

        date_match = _LOG_RUN_DATE_RE.search(raw_line)
        if date_match and reported_run_date is None:
            reported_run_date = date_match.group(1)
            reported_run_time = date_match.group(2)

        data_match = _LOG_DATA_LINE_RE.match(raw_line)
        if data_match:
            echoed_data_lines.append(
                {
                    "line": line_no,
                    "content": data_match.group(1).strip(),
                    "raw_line": raw_line,
                }
            )

        ncyc_match = _LOG_DATA_NCYC_RE.match(raw_line)
        if ncyc_match:
            echoed_ncyc_lines.append(
                {
                    "line": line_no,
                    "token": ncyc_match.group(1),
                    "trailing": ncyc_match.group(2),
                    "raw_line": raw_line,
                }
            )

        ref_cyc_match = _LOG_REFINEMENT_CYCLES_RE.match(raw_line)
        if ref_cyc_match:
            refinement_cycles_lines.append(
                {
                    "line": line_no,
                    "token": ref_cyc_match.group(1),
                    "trailing": ref_cyc_match.group(2),
                    "raw_line": raw_line,
                }
            )

        if _LOG_WARNING_RE.search(raw_line):
            warnings.append({"line": line_no, "text": raw_line})

        if _LOG_ERROR_RE.search(raw_line):
            error_lines.append({"line": line_no, "text": raw_line})

        if _LOG_END_OF_REFMAC_RE.match(raw_line):
            end_of_refmac_lines.append({"line": line_no, "text": raw_line})

        if _LOG_NORMAL_TERMINATION_RE.match(raw_line):
            normal_termination_lines.append({"line": line_no, "text": raw_line})

        if _LOG_TIMES_RE.match(raw_line):
            times_lines.append({"line": line_no, "text": raw_line})

    return {
        "line_count": len(lines),
        "reported_suite": reported_suite,
        "reported_program": reported_program,
        "reported_version": reported_version,
        "reported_run_date": reported_run_date,
        "reported_run_time": reported_run_time,
        "echoed_data_lines": echoed_data_lines,
        "echoed_ncyc_lines": echoed_ncyc_lines,
        "refinement_cycles_lines": refinement_cycles_lines,
        "completion_markers": {
            "has_end_of_refmac_marker": len(end_of_refmac_lines) > 0,
            "has_normal_termination_marker": len(normal_termination_lines) > 0,
            "has_times_summary": len(times_lines) > 0,
            "end_of_refmac_lines": end_of_refmac_lines,
            "normal_termination_lines": normal_termination_lines,
            "times_lines": times_lines,
        },
        "warning_count": len(warnings),
        "warnings": warnings,
        "error_line_count": len(error_lines),
        "error_lines": error_lines,
    }


def _evaluate_ncyc_zero_operation_check(
    *,
    keywords_text: str,
    native_log_diagnostics: Mapping[str, Any] | None,
    parsed_log: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Verify requested and echoed ``NCYC 0`` as a distinct operation check."""
    requested_lines = [
        line.strip()
        for line in keywords_text.splitlines()
        if line.strip().upper().startswith("NCYC")
    ]
    requested_is_ncyc_zero = requested_lines == ["NCYC 0"]

    if native_log_diagnostics is None or parsed_log is None:
        return {
            "passed": False,
            "requested_keyword_lines": requested_lines,
            "requested_is_ncyc_zero": requested_is_ncyc_zero,
            "echoed_data_ncyc_tokens": [],
            "echoed_refinement_cycles_tokens": [],
            "parsed_requested_ncyc": None,
            "summary_cycle_min": None,
            "summary_cycle_max": None,
            "summary_row_count": None,
            "detailed_cycle_count": None,
            "cgmat_cycle_marker_count": None,
            "reason": "Parsed REFMAC log unavailable for echoed NCYC 0 verification",
        }

    echoed_ncyc_entries = list(native_log_diagnostics.get("echoed_ncyc_lines", []))
    ref_cyc_entries = list(native_log_diagnostics.get("refinement_cycles_lines", []))
    echoed_ncyc_tokens = [
        entry.get("token")
        for entry in echoed_ncyc_entries
        if isinstance(entry, Mapping)
    ]
    ref_cyc_tokens = [
        entry.get("token")
        for entry in ref_cyc_entries
        if isinstance(entry, Mapping)
    ]

    source_meta = parsed_log.get("source_metadata", {})
    parsed_requested_ncyc = (
        source_meta.get("requested_ncyc")
        if isinstance(source_meta, Mapping)
        else None
    )
    cycle_summary = parsed_log.get("cycle_summary", {})
    summary_min = (
        cycle_summary.get("summary_cycle_min")
        if isinstance(cycle_summary, Mapping)
        else None
    )
    summary_max = (
        cycle_summary.get("summary_cycle_max")
        if isinstance(cycle_summary, Mapping)
        else None
    )
    summary_rows = (
        cycle_summary.get("rows", [])
        if isinstance(cycle_summary, Mapping)
        else []
    )
    summary_row_count = len(summary_rows) if isinstance(summary_rows, list) else None
    detailed_cycles = parsed_log.get("detailed_cycles", [])
    detailed_cycle_count = (
        len(detailed_cycles) if isinstance(detailed_cycles, list) else None
    )
    cgmat_markers = parsed_log.get("cgmat_cycle_markers", [])
    cgmat_marker_count = (
        len(cgmat_markers) if isinstance(cgmat_markers, list) else None
    )

    reconciled_init = parsed_log.get("reconciled_initial_cycle", {})
    reconciled_final = parsed_log.get("reconciled_final_cycle", {})
    init_ncyc = (
        reconciled_init.get("summary_ncyc")
        if isinstance(reconciled_init, Mapping)
        else None
    )
    final_ncyc = (
        reconciled_final.get("summary_ncyc")
        if isinstance(reconciled_final, Mapping)
        else None
    )

    has_echoed_ncyc_zero = (
        len(echoed_ncyc_tokens) > 0
        and all(tok == "0" for tok in echoed_ncyc_tokens)
        and all(
            entry.get("trailing") in (None, "")
            for entry in echoed_ncyc_entries
            if isinstance(entry, Mapping)
        )
    )
    ref_cyc_ok = all(
        tok == "0" for tok in ref_cyc_tokens
    ) and all(
        entry.get("trailing") in (None, "")
        for entry in ref_cyc_entries
        if isinstance(entry, Mapping)
    )

    passed = bool(
        requested_is_ncyc_zero
        and has_echoed_ncyc_zero
        and ref_cyc_ok
        and parsed_requested_ncyc == EXPECTED_REQUESTED_NCYC
        and summary_min == 0
        and summary_max == 0
        and summary_row_count == 1
        and detailed_cycle_count == 1
        and cgmat_marker_count == 0
        and init_ncyc == 0
        and final_ncyc == 0
    )

    reason: str | None = None
    if not passed:
        reason = (
            f"NCYC 0 operation check failed: requested_lines={requested_lines!r}, "
            f"echoed_ncyc_tokens={echoed_ncyc_tokens!r}, "
            f"refinement_cycles_tokens={ref_cyc_tokens!r}, "
            f"parsed_requested_ncyc={parsed_requested_ncyc!r}, "
            f"summary_cycle_min={summary_min!r}, summary_cycle_max={summary_max!r}, "
            f"summary_row_count={summary_row_count!r}, "
            f"detailed_cycle_count={detailed_cycle_count!r}, "
            f"cgmat_marker_count={cgmat_marker_count!r}"
        )

    return {
        "passed": passed,
        "requested_keyword_lines": requested_lines,
        "requested_is_ncyc_zero": requested_is_ncyc_zero,
        "echoed_data_ncyc_tokens": echoed_ncyc_tokens,
        "echoed_refinement_cycles_tokens": ref_cyc_tokens,
        "parsed_requested_ncyc": parsed_requested_ncyc,
        "summary_cycle_min": summary_min,
        "summary_cycle_max": summary_max,
        "summary_row_count": summary_row_count,
        "detailed_cycle_count": detailed_cycle_count,
        "cgmat_cycle_marker_count": cgmat_marker_count,
        "reason": reason,
    }


def _scan_refmac_directory_entries(
    refmac_dir: Path,
    *,
    known_paths: Mapping[str, Path],
    caught_exceptions: list[Exception] | None = None,
    expected_root_identity: Mapping[str, Any] | None = None,
    refmac_dir_status: Mapping[str, Any] | None = None,
    refmac_dir_initial_cause: Exception | None = None,
    scandir_cause_out: list[Exception | None] | None = None,
    additional_file_causes_out: dict[str, Exception | None] | None = None,
) -> dict[str, Any]:
    """Scan ``refmac_dir`` without following symlinks to inventory all created entries."""
    known_by_abspath = {
        os.path.abspath(os.fspath(p)): label for label, p in known_paths.items()
    }
    additional_files: dict[str, dict[str, Any]] = {}
    unexpected_symlinks: list[str] = []
    inspection_errors: list[dict[str, Any]] = []
    scandir_error: dict[str, Any] | None = None
    normalized_refmac_dir = Path(os.path.abspath(os.fspath(refmac_dir)))

    if refmac_dir_status is not None and not bool(
        refmac_dir_status.get("identity_verified", True)
    ):
        err_msg = str(
            refmac_dir_status.get("error")
            or f"Refmac working directory identity verification failed: {refmac_dir}"
        )
        is_sym = bool(refmac_dir_status.get("is_symlink", False))
        scandir_error = {
            "output_key": "refmac_dir_scan",
            "path": str(refmac_dir),
            "exists": bool(refmac_dir_status.get("exists", False)),
            "is_symlink": is_sym,
            "is_regular_file": False,
            "within_refmac_dir": False,
            "size_bytes": None,
            "error": err_msg,
            "exception_type": str(
                refmac_dir_status.get("exception_type") or "ValueError"
            ),
            "exception_message": str(
                refmac_dir_status.get("exception_message") or err_msg
            ),
            "errno": refmac_dir_status.get("errno"),
        }
        if scandir_cause_out is not None:
            scandir_cause_out.append(refmac_dir_initial_cause)
        return {
            "additional_files": additional_files,
            "unexpected_symlinks": [str(refmac_dir)] if is_sym else [],
            "inspection_errors": [scandir_error],
            "scandir_error": scandir_error,
        }

    if expected_root_identity is not None:
        chain_causes: list[Exception] = []
        chain_check = _verify_refmac_directory_post_run(
            refmac_dir,
            refmac_dir_baseline=expected_root_identity,
            caught_exceptions=chain_causes,
        )
        if caught_exceptions is not None:
            caught_exceptions.extend(chain_causes)
        if not bool(chain_check.get("identity_verified", False)):
            err_msg = str(
                chain_check.get("error")
                or f"Refmac working directory chain verification failed: {refmac_dir}"
            )
            is_sym = bool(chain_check.get("is_symlink", False))
            scandir_error = {
                "output_key": "refmac_dir_scan",
                "path": str(refmac_dir),
                "exists": bool(chain_check.get("exists", False)),
                "is_symlink": is_sym,
                "is_regular_file": False,
                "within_refmac_dir": False,
                "size_bytes": None,
                "error": err_msg,
                "exception_type": str(
                    chain_check.get("exception_type") or "ValueError"
                ),
                "exception_message": str(
                    chain_check.get("exception_message") or err_msg
                ),
                "errno": chain_check.get("errno"),
            }
            if scandir_cause_out is not None:
                scandir_cause_out.append(
                    chain_causes[0] if chain_causes else None
                )
            return {
                "additional_files": additional_files,
                "unexpected_symlinks": [str(refmac_dir)] if is_sym else [],
                "inspection_errors": [scandir_error],
                "scandir_error": scandir_error,
            }
    else:
        if normalized_refmac_dir.parent != normalized_refmac_dir:
            try:
                parent_st = os.lstat(normalized_refmac_dir.parent)
                if stat.S_ISLNK(parent_st.st_mode) or not stat.S_ISDIR(
                    parent_st.st_mode
                ):
                    raise ValueError(
                        f"Evidence root directory is not a non-symlink directory: {normalized_refmac_dir.parent}"
                    )
            except Exception as exc:
                if caught_exceptions is not None:
                    caught_exceptions.append(exc)
                if scandir_cause_out is not None:
                    scandir_cause_out.append(exc)
                scandir_error = {
                    "output_key": "refmac_dir_scan",
                    "path": str(refmac_dir),
                    "exists": False,
                    "is_symlink": False,
                    "is_regular_file": False,
                    "within_refmac_dir": False,
                    "size_bytes": None,
                    "error": f"Evidence root check failed before refmac_dir scan ({type(exc).__name__}): {exc}",
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                    "errno": getattr(exc, "errno", None),
                }
                return {
                    "additional_files": additional_files,
                    "unexpected_symlinks": [],
                    "inspection_errors": [scandir_error],
                    "scandir_error": scandir_error,
                }

        try:
            refmac_st = os.lstat(refmac_dir)
        except OSError as exc:
            if caught_exceptions is not None:
                caught_exceptions.append(exc)
            if scandir_cause_out is not None:
                scandir_cause_out.append(exc)
            scandir_error = {
                "output_key": "refmac_dir_scan",
                "path": str(refmac_dir),
                "exists": False,
                "is_symlink": False,
                "is_regular_file": False,
                "within_refmac_dir": False,
                "size_bytes": None,
                "error": f"Failed to stat refmac directory {refmac_dir} ({type(exc).__name__}): {exc}",
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
                "errno": getattr(exc, "errno", None),
            }
            return {
                "additional_files": additional_files,
                "unexpected_symlinks": unexpected_symlinks,
                "inspection_errors": [scandir_error],
                "scandir_error": scandir_error,
            }

        if stat.S_ISLNK(refmac_st.st_mode):
            err_msg = f"Refmac working directory was replaced by a symlink: {refmac_dir}"
            if scandir_cause_out is not None:
                scandir_cause_out.append(None)
            scandir_error = {
                "output_key": "refmac_dir_scan",
                "path": str(refmac_dir),
                "exists": True,
                "is_symlink": True,
                "is_regular_file": False,
                "within_refmac_dir": False,
                "size_bytes": None,
                "error": err_msg,
                "exception_type": "ValueError",
                "exception_message": err_msg,
                "errno": None,
            }
            return {
                "additional_files": additional_files,
                "unexpected_symlinks": [str(refmac_dir)],
                "inspection_errors": [scandir_error],
                "scandir_error": scandir_error,
            }

        if not stat.S_ISDIR(refmac_st.st_mode):
            err_msg = f"Refmac working directory path is not a directory: {refmac_dir}"
            if scandir_cause_out is not None:
                scandir_cause_out.append(None)
            scandir_error = {
                "output_key": "refmac_dir_scan",
                "path": str(refmac_dir),
                "exists": True,
                "is_symlink": False,
                "is_regular_file": False,
                "within_refmac_dir": False,
                "size_bytes": None,
                "error": err_msg,
                "exception_type": "ValueError",
                "exception_message": err_msg,
                "errno": None,
            }
            return {
                "additional_files": additional_files,
                "unexpected_symlinks": [],
                "inspection_errors": [scandir_error],
                "scandir_error": scandir_error,
            }

    try:
        with os.scandir(refmac_dir) as it:
            entries = sorted(list(it), key=lambda e: e.name)
    except OSError as exc:
        if caught_exceptions is not None:
            caught_exceptions.append(exc)
        if scandir_cause_out is not None:
            scandir_cause_out.append(exc)
        scandir_error = {
            "output_key": "refmac_dir_scan",
            "path": str(refmac_dir),
            "exists": True,
            "is_symlink": False,
            "is_regular_file": False,
            "within_refmac_dir": True,
            "size_bytes": None,
            "error": f"Failed to scan refmac directory {refmac_dir} ({type(exc).__name__}): {exc}",
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "errno": getattr(exc, "errno", None),
        }
        return {
            "additional_files": additional_files,
            "unexpected_symlinks": unexpected_symlinks,
            "inspection_errors": [scandir_error],
            "scandir_error": scandir_error,
        }

    for entry in entries:
        entry_path = refmac_dir / entry.name
        abs_entry = os.path.abspath(os.fspath(entry_path))
        entry_causes: list[Exception] = []
        info = _inspect_output_artifact(
            entry_path,
            root=refmac_dir,
            caught_exceptions=entry_causes,
            expected_root_identity=expected_root_identity,
        )
        if caught_exceptions is not None:
            caught_exceptions.extend(entry_causes)
        if info["is_symlink"] or not info["within_refmac_dir"]:
            unexpected_symlinks.append(str(entry_path))
        if info.get("error") is not None:
            inspection_errors.append(
                {
                    "entry_name": entry.name,
                    **info,
                }
            )
        if abs_entry not in known_by_abspath:
            additional_files[entry.name] = info
            if additional_file_causes_out is not None:
                additional_file_causes_out[entry.name] = (
                    entry_causes[0] if entry_causes else None
                )

    return {
        "additional_files": additional_files,
        "unexpected_symlinks": unexpected_symlinks,
        "inspection_errors": inspection_errors,
        "scandir_error": scandir_error,
    }


_OPTIONAL_DIAGNOSTIC_MAX_EXPANDED_DIGITS = 4096


def _preflight_optional_decimal_diagnostic(
    value: Decimal,
    *,
    requested_scale: int = 0,
    label: str = "value",
) -> tuple[bool, str | None]:
    """Check whether optional exact Decimal/Fraction expansion stays within the 4096-digit resource budget."""
    sign, digits, exponent = value.as_tuple()
    _ = sign
    if not isinstance(exponent, int):
        return (
            False,
            f"{label} is non-finite ({value!r}); optional exact rational diagnostic unavailable",
        )
    if (
        requested_scale < 0
        or requested_scale > _OPTIONAL_DIAGNOSTIC_MAX_EXPANDED_DIGITS
    ):
        return (
            False,
            f"{label} requested decimal scale ({requested_scale}) exceeds optional diagnostic resource budget ({_OPTIONAL_DIAGNOSTIC_MAX_EXPANDED_DIGITS} expanded digits)",
        )
    coeff_digits = max(len(digits), 1)
    if coeff_digits > _OPTIONAL_DIAGNOSTIC_MAX_EXPANDED_DIGITS:
        return (
            False,
            f"{label} coefficient length ({coeff_digits} digits) exceeds optional diagnostic resource budget ({_OPTIONAL_DIAGNOSTIC_MAX_EXPANDED_DIGITS} expanded digits)",
        )
    if abs(exponent) > _OPTIONAL_DIAGNOSTIC_MAX_EXPANDED_DIGITS:
        return (
            False,
            f"{label} decimal exponent ({exponent}) exceeds optional diagnostic resource budget ({_OPTIONAL_DIAGNOSTIC_MAX_EXPANDED_DIGITS} expanded digits)",
        )
    if exponent >= 0:
        int_digits = coeff_digits + exponent
        frac_scale = 0
    else:
        frac_scale = -exponent
        int_digits = max(coeff_digits - frac_scale, 1)
    target_scale = max(frac_scale, int(requested_scale), 0)
    # Include dp + 1 half-ULP and carry/alignment overhead (+2 digits) in projected expansion size.
    projected_expanded_digits = int_digits + target_scale + 2
    if projected_expanded_digits > _OPTIONAL_DIAGNOSTIC_MAX_EXPANDED_DIGITS:
        return (
            False,
            f"{label} projected expanded length ({projected_expanded_digits} digits at scale {target_scale}) exceeds optional diagnostic resource budget ({_OPTIONAL_DIAGNOSTIC_MAX_EXPANDED_DIGITS} expanded digits)",
        )
    return True, None


def _exact_int_to_decimal_str(value: int) -> str:
    """Format an integer as exact base-10 text via ``Decimal(int)`` without ``int``-to-``str`` conversion."""
    return str(Decimal(value))


def _exact_fraction_to_str(value: Fraction) -> str:
    """Format a ``Fraction`` as ``'num'`` or ``'num/den'`` via ``Decimal(int)`` without ``str(Fraction)``."""
    num_str = _exact_int_to_decimal_str(value.numerator)
    if value.denominator == 1:
        return num_str
    den_str = _exact_int_to_decimal_str(value.denominator)
    return f"{num_str}/{den_str}"


def _decimal_to_exact_fraction_and_scale(value: Decimal) -> tuple[Fraction, int]:
    """Convert a finite ``Decimal`` to ``(Fraction, fractional_scale)`` without touching ``decimal.getcontext()``."""
    ok, reason = _preflight_optional_decimal_diagnostic(
        value, requested_scale=0, label="Decimal operand"
    )
    if not ok:
        raise ValueError(reason)
    sign, digits, exponent = value.as_tuple()
    assert isinstance(exponent, int)
    int_val = 0
    for digit in digits:
        int_val = int_val * 10 + int(digit)
    if sign:
        int_val = -int_val
    if exponent >= 0:
        return Fraction(int_val * (10**exponent), 1), 0
    scale = -exponent
    return Fraction(int_val, 10**scale), scale


def _format_exact_power_of_ten_fraction(
    value: Fraction,
    max_scale: int,
    *,
    min_frac_digits: int = 0,
) -> str:
    """Format a terminating decimal ``Fraction`` (with denominator dividing ``10**max_scale``) using pure integer math."""
    scale = max(int(max_scale), int(min_frac_digits), 0)
    ten_pow = 10**scale
    num = value.numerator
    den = value.denominator
    if (abs(num) * ten_pow) % den != 0:
        raise ValueError(
            f"Fraction {_exact_fraction_to_str(value)} does not terminate at decimal scale 10**-{scale}"
        )
    scaled_int = (abs(num) * ten_pow) // den
    if scaled_int == 0 and min_frac_digits <= 0:
        return "0"
    cur_scale = scale
    while cur_scale > min_frac_digits and cur_scale > 0 and scaled_int % 10 == 0:
        scaled_int //= 10
        cur_scale -= 1
    sign_prefix = "-" if (num < 0 and scaled_int != 0) else ""
    scaled_digits = _exact_int_to_decimal_str(scaled_int)
    if cur_scale == 0:
        return f"{sign_prefix}{scaled_digits}"
    digits_str = scaled_digits.rjust(cur_scale + 1, "0")
    return f"{sign_prefix}{digits_str[:-cur_scale]}.{digits_str[-cur_scale:]}"


def _is_minus_999_sentinel(token: str) -> bool:
    """Return True if ``token`` encodes REFMAC's documented ``-999`` missing-value sentinel."""
    stripped = token.strip()
    if not stripped:
        return False
    if stripped.startswith("-999"):
        return True
    try:
        dec = Decimal(stripped)
    except InvalidOperation:
        return False
    if not dec.is_finite():
        return False
    return dec <= Decimal("-999")


def _parse_xml_r_value_token(
    token: str,
    *,
    field_name: str,
    cycle_index: int | None,
) -> tuple[Decimal | None, int | None, str | None]:
    """Validate an XML R-factor token as a finite nonnegative decimal, retaining raw token and precision.

    Aligns with :func:`onesar_refmac_log._parse_r_token` (issue #1030): crystallographic
    R-factors are finite nonnegative ratios ``>= 0`` and have no upper bound at ``1.0``
    (or ``99.0``). Rejects empty tokens, documented ``-999`` missing-value sentinels,
    malformed tokens, non-finite values, and negative values.
    """
    stripped = token.strip()
    loc = f"{field_name} (cycle={cycle_index})" if cycle_index is not None else field_name
    if not stripped:
        return None, None, f"Empty XML token for {loc}"
    if _is_minus_999_sentinel(stripped):
        return (
            None,
            None,
            f"Documented -999 missing-value sentinel in supported XML field {loc}: {stripped!r}",
        )
    try:
        dec_probe = Decimal(stripped)
    except InvalidOperation:
        dec_probe = None
    if dec_probe is not None:
        if not dec_probe.is_finite():
            return (
                None,
                None,
                f"Non-finite XML R-factor value {stripped!r} for {loc}; must be a finite non-negative decimal",
            )
        if dec_probe < Decimal("0"):
            return (
                None,
                None,
                f"Negative XML R-factor value {stripped!r} for {loc}; must be >= 0",
            )
    if not re.fullmatch(r"[0-9]+\.[0-9]+", stripped):
        return (
            None,
            None,
            f"Invalid XML R-factor token {stripped!r} for {loc}; expected non-negative decimal token",
        )
    try:
        dec = Decimal(stripped)
    except InvalidOperation:
        return None, None, f"Unparseable or non-finite Decimal token {stripped!r} for {loc}"
    if not dec.is_finite() or dec < Decimal("0"):
        return (
            None,
            None,
            f"Out-of-domain XML R-factor value {stripped!r} for {loc}; must be a finite non-negative decimal (>= 0)",
        )
    decimal_places = len(stripped.split(".", 1)[1])
    return dec, decimal_places, None


def _compare_r_decimal_with_log_precision(
    xml_dec: Decimal,
    xml_dp: int,
    log_token: str,
    *,
    xml_token: str | None = None,
) -> dict[str, Any]:
    """Compare two printed R-factor decimal tokens without double-rounding or ambient context rounding.

    Per issues #1042, #1037, and #1051:
    - Never re-quantizes an already-rounded decimal token with ``ROUND_HALF_UP`` or
      ``ROUND_HALF_EVEN``.
    - Preflights both operands and requested reporting scales against the explicit
      4096-expanded-digit implementation resource budget before constructing powers of
      ten, ``Fraction`` values, or fixed-point strings.
    - When within budget, uses exact arbitrary-precision ``Fraction`` and integer
      arithmetic for all differences, conditional ``[d - 10**(-p)/2, d + 10**(-p)/2]``
      interval bounds, overlap widths, and positive separation gaps so results never
      depend on or mutate ``decimal.getcontext()`` or ``sys.get_int_max_str_digits()``.
    - When optional arithmetic exceeds the resource budget, preserves raw tokens,
      compact exact ``Decimal`` values, and exact ``Decimal`` equality while marking
      derived interval/difference fields ``None`` with an explicit reason.
    - Preserves raw ``xml_token`` identity separately from ``xml_reconstructed_fixed_token``;
      when ``xml_token`` is omitted by a 3-argument caller, ``xml_token`` and
      ``exact_token_equal`` are recorded as ``None`` rather than fabricated from
      ``f"{xml_dec:.{xml_dp}f}"``.
    - Keeps source-level rounding/tie-break and shared-scalar provenance explicitly
      unproven (``precision_association_proven = False``,
      ``compatible_at_source_precision = None``,
      ``contradicts_at_source_precision = None``).
    """
    log_stripped = log_token.strip()
    log_dec = Decimal(log_stripped)
    log_dp = len(log_stripped.split(".", 1)[1]) if "." in log_stripped else 0
    xml_dp_int = int(xml_dp)

    if xml_token is not None:
        xml_raw_token: str | None = xml_token.strip()
        raw_xml_token_supplied = True
        reported_xml_token: str | None = xml_raw_token
        exact_token_equal: bool | None = xml_raw_token == log_stripped
    else:
        xml_raw_token = None
        raw_xml_token_supplied = False
        reported_xml_token = None
        exact_token_equal = None

    same_dp = xml_dp_int == log_dp
    shared_dp = min(xml_dp_int, log_dp)
    exact_equal = bool(xml_dec == log_dec)

    xml_ok, xml_unavail_reason = _preflight_optional_decimal_diagnostic(
        xml_dec, requested_scale=xml_dp_int + 1, label="xml_dec"
    )
    log_ok, log_unavail_reason = _preflight_optional_decimal_diagnostic(
        log_dec, requested_scale=log_dp + 1, label="log_dec"
    )
    unavail_reason: str | None = xml_unavail_reason or log_unavail_reason
    if unavail_reason is None:
        xml_exp = xml_dec.as_tuple().exponent
        log_exp = log_dec.as_tuple().exponent
        assert isinstance(xml_exp, int) and isinstance(log_exp, int)
        xml_scale_est = max(-xml_exp, 0)
        log_scale_est = max(-log_exp, 0)
        common_scale_est = max(
            xml_scale_est, xml_dp_int + 1, log_scale_est, log_dp + 1
        )
        _, xml_align_reason = _preflight_optional_decimal_diagnostic(
            xml_dec,
            requested_scale=common_scale_est,
            label="xml_dec aligned",
        )
        _, log_align_reason = _preflight_optional_decimal_diagnostic(
            log_dec,
            requested_scale=common_scale_est,
            label="log_dec aligned",
        )
        unavail_reason = xml_align_reason or log_align_reason

    if unavail_reason is not None:
        if same_dp:
            comparison_status = (
                "exact_same_precision_match"
                if exact_equal
                else "same_precision_mismatch_source_association_unproven"
            )
            rounding_mode_matched: str | None = (
                "exact_same_precision" if exact_equal else None
            )
        else:
            comparison_status = (
                "optional_interval_diagnostics_unavailable_source_association_unproven"
            )
            rounding_mode_matched = None
        return {
            "raw_xml_token_supplied": raw_xml_token_supplied,
            "xml_raw_token": xml_raw_token,
            "xml_token": reported_xml_token,
            "xml_reconstructed_fixed_token": None,
            "xml_value": str(xml_dec),
            "xml_decimal_places": xml_dp_int,
            "xml_half_ulp": None,
            "xml_reporting_interval": None,
            "log_raw_token": log_stripped,
            "log_token": log_stripped,
            "log_value": str(log_dec),
            "log_decimal_places": log_dp,
            "log_half_ulp": None,
            "log_reporting_interval": None,
            "shared_decimal_places": shared_dp,
            "same_decimal_places": same_dp,
            "exact_token_equal": exact_token_equal,
            "reconstructed_fixed_token_equal": None,
            "exact_decimal_equal": exact_equal,
            "abs_difference": None,
            "combined_half_ulp": None,
            "reporting_interval_overlap": None,
            "reporting_interval_overlap_width": None,
            "positive_separation": None,
            "positive_separation_fraction": None,
            "interval_interior_overlap": None,
            "interval_boundary_touch_only": None,
            "intervals_disjoint": None,
            "optional_interval_diagnostics_available": False,
            "optional_interval_diagnostics_unavailable_reason": unavail_reason,
            "optional_diagnostic_max_expanded_digits": (
                _OPTIONAL_DIAGNOSTIC_MAX_EXPANDED_DIGITS
            ),
            "conditional_nearest_rounding_model": True,
            "conditional_nearest_rounding_assumption": (
                "Intervals [d - 10**(-p)/2, d + 10**(-p)/2] are conditional on "
                "hypothetical half-ULP nearest rounding; producer rounding/tie "
                "rules and shared unrounded scalar provenance are unproven."
            ),
            "double_rounding_performed": False,
            "precision_association_proven": False,
            "precision_association_unproven_reason": (
                "Supplied CCP4 consumer sources "
                "(ccp4i2/wrappers/refmac_i2/script/refmac_report.py:104-127, 648-649; "
                "ccp4-9/share/smartie/qtrview_Smartie.py:130-169) do not establish "
                "native REFMAC XML/log producer rounding, tie-breaking rules, or "
                "shared unrounded scalar provenance."
            ),
            "comparison_status": comparison_status,
            "compatible_at_source_precision": None,
            "contradicts_at_source_precision": None,
            "rounding_mode_matched": rounding_mode_matched,
        }

    xml_frac, xml_scale = _decimal_to_exact_fraction_and_scale(xml_dec)
    log_frac, log_scale = _decimal_to_exact_fraction_and_scale(log_dec)

    xml_value_str = _format_exact_power_of_ten_fraction(
        xml_frac, max(xml_scale, xml_dp_int), min_frac_digits=xml_scale
    )
    log_value_str = _format_exact_power_of_ten_fraction(
        log_frac, max(log_scale, log_dp), min_frac_digits=log_scale
    )
    xml_reconstructed_fixed_token = _format_exact_power_of_ten_fraction(
        xml_frac, max(xml_scale, xml_dp_int), min_frac_digits=xml_dp_int
    )

    reconstructed_fixed_token_equal = xml_reconstructed_fixed_token == log_stripped
    abs_diff_frac = abs(xml_frac - log_frac)

    xml_half_ulp_frac = Fraction(1, 2 * (10**xml_dp_int))
    log_half_ulp_frac = Fraction(1, 2 * (10**log_dp))
    combined_half_ulp_frac = xml_half_ulp_frac + log_half_ulp_frac
    xml_low_frac = xml_frac - xml_half_ulp_frac
    xml_high_frac = xml_frac + xml_half_ulp_frac
    log_low_frac = log_frac - log_half_ulp_frac
    log_high_frac = log_frac + log_half_ulp_frac

    overlap_low_frac = max(xml_low_frac, log_low_frac)
    overlap_high_frac = min(xml_high_frac, log_high_frac)
    interval_interior_overlap = bool(overlap_low_frac < overlap_high_frac)
    interval_boundary_touch_only = bool(overlap_low_frac == overlap_high_frac)
    intervals_disjoint = bool(overlap_low_frac > overlap_high_frac)
    positive_separation_frac = (
        (overlap_low_frac - overlap_high_frac)
        if intervals_disjoint
        else Fraction(0, 1)
    )

    xml_ulp_scale = max(xml_scale, xml_dp_int + 1)
    log_ulp_scale = max(log_scale, log_dp + 1)
    common_scale = max(xml_ulp_scale, log_ulp_scale)

    if same_dp:
        comparison_status = (
            "exact_same_precision_match"
            if exact_equal
            else "same_precision_mismatch_source_association_unproven"
        )
        rounding_mode_matched = (
            "exact_same_precision" if exact_equal else None
        )
    else:
        if interval_interior_overlap:
            comparison_status = (
                "conditional_interval_interior_overlap_source_association_unproven"
            )
            rounding_mode_matched = None
        elif interval_boundary_touch_only:
            comparison_status = (
                "conditional_interval_boundary_touch_only_source_association_unproven"
            )
            rounding_mode_matched = None
        else:
            comparison_status = (
                "conditional_intervals_disjoint_source_association_unproven"
            )
            rounding_mode_matched = None

    return {
        "raw_xml_token_supplied": raw_xml_token_supplied,
        "xml_raw_token": xml_raw_token,
        "xml_token": reported_xml_token,
        "xml_reconstructed_fixed_token": xml_reconstructed_fixed_token,
        "xml_value": xml_value_str,
        "xml_decimal_places": xml_dp_int,
        "xml_half_ulp": _format_exact_power_of_ten_fraction(
            xml_half_ulp_frac, xml_ulp_scale
        ),
        "xml_reporting_interval": [
            _format_exact_power_of_ten_fraction(xml_low_frac, xml_ulp_scale),
            _format_exact_power_of_ten_fraction(xml_high_frac, xml_ulp_scale),
        ],
        "log_raw_token": log_stripped,
        "log_token": log_stripped,
        "log_value": log_value_str,
        "log_decimal_places": log_dp,
        "log_half_ulp": _format_exact_power_of_ten_fraction(
            log_half_ulp_frac, log_ulp_scale
        ),
        "log_reporting_interval": [
            _format_exact_power_of_ten_fraction(log_low_frac, log_ulp_scale),
            _format_exact_power_of_ten_fraction(log_high_frac, log_ulp_scale),
        ],
        "shared_decimal_places": shared_dp,
        "same_decimal_places": same_dp,
        "exact_token_equal": exact_token_equal,
        "reconstructed_fixed_token_equal": reconstructed_fixed_token_equal,
        "exact_decimal_equal": exact_equal,
        "abs_difference": _format_exact_power_of_ten_fraction(
            abs_diff_frac, common_scale
        ),
        "combined_half_ulp": _format_exact_power_of_ten_fraction(
            combined_half_ulp_frac, common_scale
        ),
        "reporting_interval_overlap": (
            [
                _format_exact_power_of_ten_fraction(
                    overlap_low_frac, common_scale
                ),
                _format_exact_power_of_ten_fraction(
                    overlap_high_frac, common_scale
                ),
            ]
            if overlap_low_frac <= overlap_high_frac
            else None
        ),
        "reporting_interval_overlap_width": (
            _format_exact_power_of_ten_fraction(
                overlap_high_frac - overlap_low_frac, common_scale
            )
            if overlap_low_frac <= overlap_high_frac
            else "0"
        ),
        "positive_separation": (
            _format_exact_power_of_ten_fraction(
                positive_separation_frac, common_scale
            )
            if intervals_disjoint
            else "0"
        ),
        "positive_separation_fraction": _exact_fraction_to_str(
            positive_separation_frac
        ),
        "interval_interior_overlap": interval_interior_overlap,
        "interval_boundary_touch_only": interval_boundary_touch_only,
        "intervals_disjoint": intervals_disjoint,
        "optional_interval_diagnostics_available": True,
        "optional_interval_diagnostics_unavailable_reason": None,
        "optional_diagnostic_max_expanded_digits": (
            _OPTIONAL_DIAGNOSTIC_MAX_EXPANDED_DIGITS
        ),
        "conditional_nearest_rounding_model": True,
        "conditional_nearest_rounding_assumption": (
            "Intervals [d - 10**(-p)/2, d + 10**(-p)/2] are conditional on "
            "hypothetical half-ULP nearest rounding; producer rounding/tie "
            "rules and shared unrounded scalar provenance are unproven."
        ),
        "double_rounding_performed": False,
        "precision_association_proven": False,
        "precision_association_unproven_reason": (
            "Supplied CCP4 consumer sources "
            "(ccp4i2/wrappers/refmac_i2/script/refmac_report.py:104-127, 648-649; "
            "ccp4-9/share/smartie/qtrview_Smartie.py:130-169) do not establish "
            "native REFMAC XML/log producer rounding, tie-breaking rules, or "
            "shared unrounded scalar provenance."
        ),
        "comparison_status": comparison_status,
        "compatible_at_source_precision": None,
        "contradicts_at_source_precision": None,
        "rounding_mode_matched": rounding_mode_matched,
    }


def _audit_refmac_xmlout(
    xmlout_path: Path,
    *,
    xmlout_info: Mapping[str, Any],
    parsed_log: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Audit optional native REFMAC ``XMLOUT`` while retaining raw bytes/hash across all states."""
    precision_unproven_reason = (
        "Supplied CCP4 consumer sources "
        "(ccp4i2/wrappers/refmac_i2/script/refmac_report.py:73-81, 104-127, 648-649; "
        "ccp4-9/share/smartie/qtrview_Smartie.py:130-169) do not establish "
        "native REFMAC XML/log producer rounding, tie-breaking rules, or "
        "shared unrounded scalar provenance between top-level <Overall_stats> "
        "and <new_cycle> or log R-factor fields."
    )
    top_vs_final_unproven_reason = (
        "ccp4i2/wrappers/refmac_i2/script/refmac_report.py:104-127, 648-649 "
        "reads .//Overall_stats/stats_vs_cycle/new_cycle and "
        ".//Overall_stats/stats_vs_cycle/new_cycle[last()]/r_factor & r_free only; "
        "it does not establish that top-level <Overall_stats>/<r_factor> or <r_free> "
        "shares the same unrounded scalar or formatting rule as final <new_cycle>."
    )
    base_record: dict[str, Any] = {
        "schema_version": 1,
        "path": str(xmlout_path),
        "present": bool(xmlout_info.get("exists")),
        "is_symlink": bool(xmlout_info.get("is_symlink")),
        "is_regular_file": bool(xmlout_info.get("is_regular_file")),
        "within_refmac_dir": bool(xmlout_info.get("within_refmac_dir")),
        "sha256": xmlout_info.get("sha256"),
        "size_bytes": xmlout_info.get("size_bytes"),
        "utf8_exact": None,
        "raw_text": None,
        "raw_bytes_hex": None,
        "status": "absent",
        "well_formed_xml": None,
        "supported_shape": False,
        "valid": True,
        "reconciled_with_log": None,
        "cycle_association_proven": False,
        "cycle_association_unproven_reason": None,
        "precision_association_proven": False,
        "precision_association_unproven_reason": precision_unproven_reason,
        "top_vs_final_shared_scalar_proven": False,
        "top_vs_final_shared_scalar_unproven_reason": top_vs_final_unproven_reason,
        "smartie_graphs_present": False,
        "smartie_graphs_required": False,
        "root_tag": None,
        "top_level_child_tags": [],
        "cycle_indexing_convention": None,
        "observed_cycle_numbers": [],
        "overall_stats_top_level": None,
        "new_cycle_rows": [],
        "other_new_cycle_sentinel_tags": [],
        "log_reconciliation": None,
        "unsupported_shape_reason": None,
        "errors": [],
    }

    if (
        xmlout_info.get("is_symlink")
        or not xmlout_info.get("within_refmac_dir")
        or xmlout_info.get("error") is not None
        or (xmlout_info.get("exists") and not xmlout_info.get("is_regular_file"))
    ):
        base_record["status"] = "rejected_invalid_artifact"
        base_record["well_formed_xml"] = False
        base_record["valid"] = False
        base_record["reconciled_with_log"] = False
        base_record["errors"] = [
            str(xmlout_info.get("error") or f"Invalid XMLOUT artifact: {xmlout_path}")
        ]
        return base_record

    if not xmlout_info.get("exists"):
        base_record["unsupported_shape_reason"] = (
            "XMLOUT file is absent; absence preserved explicitly."
        )
        return base_record

    raw_bytes = xmlout_path.read_bytes()
    base_record["sha256"] = _sha256_bytes(raw_bytes)
    base_record["size_bytes"] = len(raw_bytes)
    try:
        base_record["raw_text"] = raw_bytes.decode("utf-8", errors="strict")
        base_record["utf8_exact"] = True
    except UnicodeDecodeError:
        base_record["raw_text"] = raw_bytes.decode("utf-8", errors="replace")
        base_record["utf8_exact"] = False
    base_record["raw_bytes_hex"] = raw_bytes.hex()

    if len(raw_bytes) == 0:
        base_record["status"] = "rejected_empty_xml"
        base_record["well_formed_xml"] = False
        base_record["valid"] = False
        base_record["reconciled_with_log"] = False
        base_record["errors"] = ["XMLOUT file is empty (0 bytes)"]
        return base_record

    try:
        root = ET.fromstring(raw_bytes)
    except ET.ParseError as exc:
        base_record["status"] = "rejected_malformed_xml"
        base_record["well_formed_xml"] = False
        base_record["valid"] = False
        base_record["reconciled_with_log"] = False
        base_record["errors"] = [f"Malformed XMLOUT syntax: {exc}"]
        return base_record

    base_record["well_formed_xml"] = True
    base_record["root_tag"] = root.tag
    base_record["top_level_child_tags"] = [child.tag for child in root]
    base_record["smartie_graphs_present"] = any(
        elem.tag == "SmartieGraphs" for elem in root.iter()
    )

    all_overall_nodes = [elem for elem in root.iter() if elem.tag == "Overall_stats"]
    all_stats_vs_cycle_nodes = [
        elem for elem in root.iter() if elem.tag == "stats_vs_cycle"
    ]
    all_new_cycle_nodes = [elem for elem in root.iter() if elem.tag == "new_cycle"]

    if (
        not all_overall_nodes
        and not all_stats_vs_cycle_nodes
        and not all_new_cycle_nodes
    ):
        base_record["status"] = "unsupported_shape"
        base_record["supported_shape"] = False
        base_record["valid"] = True
        base_record["reconciled_with_log"] = None
        base_record["unsupported_shape_reason"] = (
            f"XMLOUT root <{root.tag}> has no Overall_stats/stats_vs_cycle/new_cycle "
            "elements; unsupported XML shape preserved explicitly without inventing associations."
        )
        return base_record

    base_record["supported_shape"] = True
    errors: list[str] = []

    direct_overall = [child for child in root if child.tag == "Overall_stats"]
    if root.tag == "Overall_stats":
        overall_node = root
        if len(all_overall_nodes) != 1:
            errors.append(
                f"Expected single Overall_stats element, found {len(all_overall_nodes)}"
            )
    elif len(direct_overall) == 1 and len(all_overall_nodes) == 1:
        overall_node = direct_overall[0]
    else:
        overall_node = all_overall_nodes[0] if all_overall_nodes else None
        errors.append(
            f"Expected exactly one direct <Overall_stats> child under <{root.tag}>, "
            f"found {len(direct_overall)} direct and {len(all_overall_nodes)} total"
        )

    stats_vs_cycle_node = None
    if overall_node is not None:
        top_r_work_nodes = [c for c in overall_node if c.tag == "r_factor"]
        top_r_free_nodes = [c for c in overall_node if c.tag == "r_free"]
        if len(top_r_work_nodes) > 1 or len(top_r_free_nodes) > 1:
            errors.append(
                "Duplicate top-level <r_factor> or <r_free> under <Overall_stats>"
            )
        top_level_info: dict[str, Any] = {}
        if top_r_work_nodes:
            raw_tok = (top_r_work_nodes[0].text or "").strip()
            dec, dp, err = _parse_xml_r_value_token(
                raw_tok, field_name="Overall_stats/r_factor", cycle_index=None
            )
            top_level_info["r_factor_token"] = raw_tok
            top_level_info["r_factor"] = (
                str(dec) if (dec is not None and dp is not None) else None
            )
            top_level_info["r_factor_decimal_places"] = dp
            if err is not None:
                errors.append(err)
        if top_r_free_nodes:
            raw_tok = (top_r_free_nodes[0].text or "").strip()
            dec, dp, err = _parse_xml_r_value_token(
                raw_tok, field_name="Overall_stats/r_free", cycle_index=None
            )
            top_level_info["r_free_token"] = raw_tok
            top_level_info["r_free"] = (
                str(dec) if (dec is not None and dp is not None) else None
            )
            top_level_info["r_free_decimal_places"] = dp
            if err is not None:
                errors.append(err)
        if top_level_info:
            base_record["overall_stats_top_level"] = top_level_info

        direct_svc = [c for c in overall_node if c.tag == "stats_vs_cycle"]
        if len(direct_svc) == 1 and len(all_stats_vs_cycle_nodes) == 1:
            stats_vs_cycle_node = direct_svc[0]
        else:
            errors.append(
                f"Expected exactly one <stats_vs_cycle> child under <Overall_stats>, "
                f"found {len(direct_svc)} direct and {len(all_stats_vs_cycle_nodes)} total"
            )

    new_cycle_rows: list[dict[str, Any]] = []
    other_sentinels: list[dict[str, Any]] = []
    if stats_vs_cycle_node is not None:
        direct_new_cycles = [
            c for c in stats_vs_cycle_node if c.tag == "new_cycle"
        ]
        non_new_cycle_children = [
            c.tag for c in stats_vs_cycle_node if c.tag != "new_cycle"
        ]
        if non_new_cycle_children:
            errors.append(
                f"Unexpected child tags under <stats_vs_cycle>: {non_new_cycle_children!r}"
            )
        if len(direct_new_cycles) != len(all_new_cycle_nodes):
            errors.append(
                "Stray <new_cycle> elements found outside <stats_vs_cycle>"
            )
        if not direct_new_cycles:
            errors.append("<stats_vs_cycle> contains zero <new_cycle> elements")

        for ordinal, nc_elem in enumerate(direct_new_cycles):
            cyc_children = [c for c in nc_elem if c.tag == "cycle"]
            rf_children = [c for c in nc_elem if c.tag == "r_factor"]
            rfree_children = [c for c in nc_elem if c.tag == "r_free"]

            if len(cyc_children) != 1:
                errors.append(
                    f"<new_cycle> ordinal {ordinal} has {len(cyc_children)} <cycle> elements (expected 1)"
                )
            if len(rf_children) != 1:
                errors.append(
                    f"<new_cycle> ordinal {ordinal} has {len(rf_children)} <r_factor> elements (expected 1)"
                )
            if len(rfree_children) != 1:
                errors.append(
                    f"<new_cycle> ordinal {ordinal} has {len(rfree_children)} <r_free> elements (expected 1)"
                )

            cyc_token = (
                (cyc_children[0].text or "").strip() if len(cyc_children) == 1 else ""
            )
            rf_token = (
                (rf_children[0].text or "").strip() if len(rf_children) == 1 else ""
            )
            rfree_token = (
                (rfree_children[0].text or "").strip()
                if len(rfree_children) == 1
                else ""
            )

            cyc_int: int | None = None
            if not cyc_token:
                errors.append(f"<new_cycle> ordinal {ordinal} has empty <cycle> token")
            elif _is_minus_999_sentinel(cyc_token):
                errors.append(
                    f"Documented -999 missing-value sentinel in <new_cycle><cycle> at ordinal {ordinal}: {cyc_token!r}"
                )
            elif not re.fullmatch(r"[0-9]+", cyc_token):
                errors.append(
                    f"Invalid non-negative integer <cycle> token {cyc_token!r} at ordinal {ordinal}"
                )
            else:
                cyc_int = int(cyc_token)

            rf_dec, rf_dp, rf_err = _parse_xml_r_value_token(
                rf_token, field_name="new_cycle/r_factor", cycle_index=cyc_int
            )
            if rf_err is not None:
                errors.append(rf_err)

            rfree_dec, rfree_dp, rfree_err = _parse_xml_r_value_token(
                rfree_token, field_name="new_cycle/r_free", cycle_index=cyc_int
            )
            if rfree_err is not None:
                errors.append(rfree_err)

            for other_child in nc_elem:
                if other_child.tag in {"cycle", "r_factor", "r_free"}:
                    continue
                other_text = (other_child.text or "").strip()
                if _is_minus_999_sentinel(other_text):
                    other_sentinels.append(
                        {
                            "new_cycle_ordinal": ordinal,
                            "cycle": cyc_int,
                            "tag": other_child.tag,
                            "token": other_text,
                        }
                    )

            rf_val_str: str | None = (
                str(rf_dec) if (rf_dec is not None and rf_dp is not None) else None
            )
            rfree_val_str: str | None = (
                str(rfree_dec)
                if (rfree_dec is not None and rfree_dp is not None)
                else None
            )

            new_cycle_rows.append(
                {
                    "ordinal": ordinal,
                    "cycle_token": cyc_token,
                    "cycle": cyc_int,
                    "r_factor_token": rf_token,
                    "r_factor": rf_val_str,
                    "r_factor_decimal_places": rf_dp,
                    "r_free_token": rfree_token,
                    "r_free": rfree_val_str,
                    "r_free_decimal_places": rfree_dp,
                }
            )

    base_record["new_cycle_rows"] = new_cycle_rows
    base_record["other_new_cycle_sentinel_tags"] = other_sentinels

    cycle_unproven_reason = (
        "Installed CCP4 XML consumer "
        "(ccp4i2/wrappers/refmac_i2/script/refmac_report.py:104-127, 648-649) "
        "parses <new_cycle><cycle> only via int(cycleNode.findall('cycle')[0].text) "
        "and does not establish whether XML <cycle> is 0-based or 1-based or "
        "how XML <new_cycle> elements map to log summary Ncyc or detailed-cycle indices."
    )
    base_record["cycle_indexing_convention"] = None
    base_record["cycle_association_proven"] = False
    base_record["cycle_association_unproven_reason"] = cycle_unproven_reason
    if new_cycle_rows and all(row["cycle"] is not None for row in new_cycle_rows):
        cycle_numbers = [int(row["cycle"]) for row in new_cycle_rows]
        base_record["observed_cycle_numbers"] = cycle_numbers
        if len(set(cycle_numbers)) != len(cycle_numbers):
            errors.append(
                f"Duplicate XML <new_cycle><cycle> values: {cycle_numbers!r}"
            )

    if (
        base_record["overall_stats_top_level"] is not None
        and new_cycle_rows
        and not errors
    ):
        top_info = base_record["overall_stats_top_level"]
        top_info["top_vs_final_shared_scalar_proven"] = False
        top_info["top_vs_final_shared_scalar_unproven_reason"] = (
            top_vs_final_unproven_reason
        )
        last_row = new_cycle_rows[-1]
        if (
            "r_factor" in top_info
            and top_info["r_factor"] is not None
            and top_info.get("r_factor_decimal_places") is not None
            and last_row["r_factor"] is not None
        ):
            rf_top_cmp = _compare_r_decimal_with_log_precision(
                Decimal(str(top_info["r_factor_token"])),
                int(top_info["r_factor_decimal_places"]),
                str(last_row["r_factor_token"]),
                xml_token=str(top_info["r_factor_token"]),
            )
            top_info["final_new_cycle_r_factor_comparison"] = rf_top_cmp
        if (
            "r_free" in top_info
            and top_info["r_free"] is not None
            and top_info.get("r_free_decimal_places") is not None
            and last_row["r_free"] is not None
        ):
            rfree_top_cmp = _compare_r_decimal_with_log_precision(
                Decimal(str(top_info["r_free_token"])),
                int(top_info["r_free_decimal_places"]),
                str(last_row["r_free_token"]),
                xml_token=str(top_info["r_free_token"]),
            )
            top_info["final_new_cycle_r_free_comparison"] = rfree_top_cmp

    if parsed_log is not None and not errors:
        log_summary_rows = (
            parsed_log.get("cycle_summary", {}).get("rows", [])
            if isinstance(parsed_log.get("cycle_summary"), Mapping)
            else []
        )
        base_record["log_reconciliation"] = {
            "reconciled": False,
            "cycle_association_proven": False,
            "cycle_association_unproven_reason": cycle_unproven_reason,
            "ordinal_pairing_performed": False,
            "xml_new_cycle_count": len(new_cycle_rows),
            "xml_cycles": [
                {
                    "ordinal": row["ordinal"],
                    "cycle_token": row["cycle_token"],
                    "cycle": row["cycle"],
                    "r_factor_token": row["r_factor_token"],
                    "r_factor": row["r_factor"],
                    "r_factor_decimal_places": row["r_factor_decimal_places"],
                    "r_free_token": row["r_free_token"],
                    "r_free": row["r_free"],
                    "r_free_decimal_places": row["r_free_decimal_places"],
                }
                for row in new_cycle_rows
            ],
            "log_summary_row_count": (
                len(log_summary_rows) if isinstance(log_summary_rows, list) else None
            ),
            "log_summary_ncyc_values": (
                [
                    row.get("ncyc")
                    for row in log_summary_rows
                    if isinstance(row, Mapping)
                ]
                if isinstance(log_summary_rows, list)
                else []
            ),
        }

    if errors:
        base_record["status"] = "rejected_invalid_or_contradictory"
        base_record["valid"] = False
        base_record["reconciled_with_log"] = False
        base_record["errors"] = errors
    else:
        base_record["status"] = (
            "supported_cycle_association_unproven"
            if parsed_log is not None
            else "supported_parsed_log_unavailable"
        )
        base_record["valid"] = True
        base_record["reconciled_with_log"] = (
            False if parsed_log is not None else None
        )

    return base_record


def _classify_mtz_float32_word(
    val: float, u32_word: int
) -> tuple[float | None, str, str]:
    """Classify an IEEE-754 float32 word into JSON value, 8-hex uint32 string, and value_class."""
    word_hex = f"{u32_word:08x}"
    if math.isnan(val):
        return None, word_hex, "nan"
    if math.isinf(val):
        return None, word_hex, ("pos_inf" if val > 0.0 else "neg_inf")
    if val == 0.0:
        is_neg_zero = (u32_word & 0x80000000) != 0
        return 0.0, word_hex, ("neg_zero" if is_neg_zero else "zero")
    if val > 0.0:
        return float(val), word_hex, "positive_finite"
    return float(val), word_hex, "negative_finite"


def _raw_export_mtz_file(
    mtz_path: Path,
    *,
    mtz_info: dict[str, Any],
) -> tuple[dict[str, Any], bytes | None]:
    """Extract raw binary layout, header cards, column descriptors, and float32 words from MTZ.

    Runs before strict crystallographic-context or HKL-domain validation so
    unsupported ``VALM``, ``NBATCHES``, dimensions, or headers are still
    retained in ``refmac_hklout_raw_export.json``.
    """
    export: dict[str, Any] = {
        "schema_version": 1,
        "path": str(mtz_path),
        "word_hex_convention": MTZ_WORD_HEX_CONVENTION,
        "exists": bool(mtz_info["exists"]),
        "is_symlink": bool(mtz_info["is_symlink"]),
        "is_regular_file": bool(mtz_info["is_regular_file"]),
        "within_refmac_dir": bool(mtz_info["within_refmac_dir"]),
        "byte_length": mtz_info["size_bytes"],
        "sha256": mtz_info["sha256"],
        "stamp_ascii": None,
        "header_location_words": None,
        "header_byte_offset": None,
        "data_start_byte_offset": 80,
        "data_region_byte_length": None,
        "data_word_count": None,
        "trailer_byte_length": None,
        "primary_header_cards": [],
        "keyword_records": {},
        "header_parse": {
            "ncol": None,
            "nrows": None,
            "nbatches": None,
            "valm_tokens": [],
            "columns": [],
            "datasets": {},
        },
        "row_count_exported": 0,
        "rows": [],
        "raw_export_warnings": [],
        "raw_export_error": None,
    }
    if (
        not mtz_info["exists"]
        or mtz_info["is_symlink"]
        or not mtz_info["is_regular_file"]
        or not mtz_info["within_refmac_dir"]
        or mtz_info["error"] is not None
    ):
        export["raw_export_error"] = (
            mtz_info["error"]
            or "HKLOUT file is missing, symlinked, or outside refmac_dir"
        )
        return export, None

    try:
        mtz_bytes = mtz_path.read_bytes()
    except OSError as exc:
        export["raw_export_error"] = f"Failed to read HKLOUT bytes: {exc}"
        return export, None

    export["byte_length"] = len(mtz_bytes)
    export["sha256"] = hashlib.sha256(mtz_bytes).hexdigest()
    if len(mtz_bytes) < 80:
        export["raw_export_error"] = (
            f"HKLOUT file shorter than 80-byte MTZ preamble ({len(mtz_bytes)} bytes)"
        )
        return export, mtz_bytes

    stamp_bytes = mtz_bytes[:4]
    export["stamp_ascii"] = stamp_bytes.decode("ascii", errors="replace")
    (hdr_loc_words,) = struct.unpack_from("<I", mtz_bytes, 4)
    hdr_byte_offset = (hdr_loc_words - 1) * 4
    export["header_location_words"] = int(hdr_loc_words)
    export["header_byte_offset"] = int(hdr_byte_offset)

    if stamp_bytes != b"MTZ ":
        export["raw_export_warnings"].append(
            f"Unexpected MTZ file stamp {export['stamp_ascii']!r}"
        )
    if hdr_byte_offset < 80 or hdr_byte_offset >= len(mtz_bytes):
        export["raw_export_error"] = (
            f"Invalid MTZ header byte offset {hdr_byte_offset} for file of length {len(mtz_bytes)}"
        )
        return export, mtz_bytes

    data_region_bytes = hdr_byte_offset - 80
    export["data_region_byte_length"] = int(data_region_bytes)
    export["data_word_count"] = int(data_region_bytes // 4)

    cards: list[str] = []
    keyword_records: dict[str, list[str]] = {}
    tracked_keywords = {
        "VALM",
        "NCOL",
        "CELL",
        "RESO",
        "SYMINF",
        "SYMM",
        "NDIF",
        "PROJECT",
        "CRYSTAL",
        "DATASET",
        "DCELL",
        "DWAVEL",
        "DWAV",
        "COLUMN",
        "SORT",
    }
    pos = hdr_byte_offset
    end_card_offset: int | None = None
    while pos + 80 <= len(mtz_bytes):
        card = mtz_bytes[pos : pos + 80].decode("ascii", errors="replace")
        cards.append(card)
        stripped = card.strip()
        if stripped:
            kw = stripped.split(maxsplit=1)[0]
            if kw in tracked_keywords:
                keyword_records.setdefault(kw, []).append(stripped)
        pos += 80
        if stripped.startswith("END"):
            end_card_offset = pos
            break

    export["primary_header_cards"] = cards
    export["keyword_records"] = keyword_records
    export["trailer_byte_length"] = (
        len(mtz_bytes) - end_card_offset if end_card_offset is not None else len(mtz_bytes) - pos
    )

    datasets: dict[str, dict[str, Any]] = {}
    for proj_rec in keyword_records.get("PROJECT", []):
        parts = proj_rec.split(maxsplit=2)
        if len(parts) >= 2:
            ds_id = parts[1]
            datasets.setdefault(ds_id, {})["project"] = parts[2] if len(parts) > 2 else ""
    for crys_rec in keyword_records.get("CRYSTAL", []):
        parts = crys_rec.split(maxsplit=2)
        if len(parts) >= 2:
            ds_id = parts[1]
            datasets.setdefault(ds_id, {})["crystal"] = parts[2] if len(parts) > 2 else ""
    for ds_rec in keyword_records.get("DATASET", []):
        parts = ds_rec.split(maxsplit=2)
        if len(parts) >= 2:
            ds_id = parts[1]
            datasets.setdefault(ds_id, {})["dataset"] = parts[2] if len(parts) > 2 else ""
    for dcell_rec in keyword_records.get("DCELL", []):
        parts = dcell_rec.split()
        if len(parts) >= 2:
            ds_id = parts[1]
            datasets.setdefault(ds_id, {})["dcell_tokens"] = parts[2:]
    for ds_entry in datasets.values():
        ds_entry.setdefault("dwav_tokens", [])
        ds_entry.setdefault("dwavel_tokens", [])
        ds_entry.setdefault("dwav_keyword", None)
        ds_entry.setdefault("dwav_raw_record", None)
        ds_entry.setdefault("wavelength_present", False)
    for card in cards:
        stripped = card.strip()
        if not stripped:
            continue
        parts = stripped.split()
        if len(parts) >= 2 and parts[0] in ("DWAVEL", "DWAV"):
            ds_id = parts[1]
            wav_tokens = parts[2:]
            ds_entry = datasets.setdefault(ds_id, {})
            ds_entry["dwav_tokens"] = list(wav_tokens)
            ds_entry["dwavel_tokens"] = list(wav_tokens)
            ds_entry["dwav_keyword"] = parts[0]
            ds_entry["dwav_raw_record"] = stripped
            ds_entry["wavelength_present"] = len(wav_tokens) > 0

    ncol: int | None = None
    nrows: int | None = None
    nbatches: int | None = None
    if keyword_records.get("NCOL"):
        ncol_parts = keyword_records["NCOL"][0].split()
        if len(ncol_parts) >= 3:
            try:
                ncol = int(ncol_parts[1])
                nrows = int(ncol_parts[2])
                nbatches = int(ncol_parts[3]) if len(ncol_parts) > 3 else 0
            except ValueError as exc:
                export["raw_export_warnings"].append(
                    f"Malformed NCOL header tokens {ncol_parts!r}: {exc}"
                )

    valm_tokens: list[str] = []
    if keyword_records.get("VALM"):
        valm_tokens = keyword_records["VALM"][0].split()[1:]

    col_descriptors: list[dict[str, Any]] = []
    label_counts: dict[str, int] = {}
    for col_idx, col_rec in enumerate(keyword_records.get("COLUMN", [])):
        parts = col_rec.split()
        label = parts[1] if len(parts) > 1 else f"COL_{col_idx}"
        col_type = parts[2] if len(parts) > 2 else None
        min_tok = parts[3] if len(parts) > 3 else None
        max_tok = parts[4] if len(parts) > 4 else None
        ds_id = parts[5] if len(parts) > 5 else None
        label_counts[label] = label_counts.get(label, 0) + 1
        col_key = (
            label if label_counts[label] == 1 else f"{label}__dup{label_counts[label]}"
        )
        col_descriptors.append(
            {
                "column_index": col_idx,
                "label": label,
                "column_key": col_key,
                "type": col_type,
                "min_token": min_tok,
                "max_token": max_tok,
                "dataset_id": ds_id,
                "dataset_name": (
                    datasets.get(ds_id, {}).get("dataset") if ds_id is not None else None
                ),
                "raw_record": col_rec,
            }
        )

    export["header_parse"] = {
        "ncol": ncol,
        "nrows": nrows,
        "nbatches": nbatches,
        "valm_tokens": valm_tokens,
        "columns": col_descriptors,
        "datasets": datasets,
    }

    if ncol is None or nrows is None or ncol <= 0 or nrows < 0:
        export["raw_export_warnings"].append(
            f"Cannot export reflection rows with ncol={ncol!r}, nrows={nrows!r}"
        )
        return export, mtz_bytes

    expected_data_bytes = ncol * nrows * 4
    if 80 + expected_data_bytes > hdr_byte_offset:
        export["raw_export_warnings"].append(
            f"MTZ data block (80 + {expected_data_bytes}) exceeds header offset {hdr_byte_offset}"
        )
        max_complete_rows = max(0, (hdr_byte_offset - 80) // (ncol * 4))
    else:
        max_complete_rows = nrows

    col_keys = [
        (
            col_descriptors[idx]["column_key"]
            if idx < len(col_descriptors)
            else f"COL_{idx}"
        )
        for idx in range(ncol)
    ]
    float_fmt = f"<{ncol}f"
    u32_fmt = f"<{ncol}I"
    rows_out: list[dict[str, Any]] = []
    for row_idx in range(max_complete_rows):
        row_offset = 80 + row_idx * ncol * 4
        floats = struct.unpack_from(float_fmt, mtz_bytes, row_offset)
        u32s = struct.unpack_from(u32_fmt, mtz_bytes, row_offset)
        col_values: dict[str, float | None] = {}
        col_words_hex: dict[str, str] = {}
        col_classes: dict[str, str] = {}
        for idx in range(ncol):
            key = col_keys[idx]
            j_val, w_hex, v_cls = _classify_mtz_float32_word(floats[idx], u32s[idx])
            col_values[key] = j_val
            col_words_hex[key] = w_hex
            col_classes[key] = v_cls

        hkl_floats: list[float | None] = []
        hkl_ints: list[int] | None = []
        for idx in range(min(3, ncol)):
            f_val = floats[idx]
            hkl_floats.append(float(f_val) if math.isfinite(f_val) else None)
            int_val = onesar_rerun._integral_value(f_val)
            if int_val is None:
                hkl_ints = None
            elif hkl_ints is not None:
                hkl_ints.append(int_val)
        if ncol < 3:
            hkl_ints = None

        rows_out.append(
            {
                "row_index": row_idx,
                "hkl": hkl_ints,
                "hkl_floats": hkl_floats,
                "is_integral_hkl": hkl_ints is not None,
                "column_values": col_values,
                "column_words_hex": col_words_hex,
                "column_value_classes": col_classes,
            }
        )

    export["row_count_exported"] = len(rows_out)
    export["rows"] = rows_out
    return export, mtz_bytes


def _unit_cell_d_spacing(
    cell: Sequence[float], h: int, k: int, l: int
) -> float | None:
    """Compute crystallographic d-spacing (Å) for Miller index (h, k, l) and cell (a, b, c, alpha, beta, gamma)."""
    if h == 0 and k == 0 and l == 0:
        return None
    a, b, c, alpha_deg, beta_deg, gamma_deg = (float(x) for x in cell)
    if a <= 0.0 or b <= 0.0 or c <= 0.0:
        return None
    ca = math.cos(math.radians(alpha_deg))
    cb = math.cos(math.radians(beta_deg))
    cg = math.cos(math.radians(gamma_deg))
    sa = math.sin(math.radians(alpha_deg))
    sb = math.sin(math.radians(beta_deg))
    sg = math.sin(math.radians(gamma_deg))
    vol_factor = 1.0 - ca * ca - cb * cb - cg * cg + 2.0 * ca * cb * cg
    if vol_factor <= 0.0:
        return None
    s11 = (sa * sa) / (a * a * vol_factor)
    s22 = (sb * sb) / (b * b * vol_factor)
    s33 = (sg * sg) / (c * c * vol_factor)
    s12 = (ca * cb - cg) / (a * b * vol_factor)
    s23 = (cb * cg - ca) / (b * c * vol_factor)
    s13 = (cg * ca - cb) / (c * a * vol_factor)
    inv_d_sq = (
        s11 * h * h
        + s22 * k * k
        + s33 * l * l
        + 2.0 * s12 * h * k
        + 2.0 * s23 * k * l
        + 2.0 * s13 * h * l
    )
    if inv_d_sq <= 0.0:
        return None
    return 1.0 / math.sqrt(inv_d_sq)


def _validate_and_index_input_hkl_ledger(
    input_ledger: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate and index the actual ``onesar_rerun.build_input_hkl_ledger`` schema.

    Requires the documented top-level keys (``raw_rows``, ``eligible_by_hkl``,
    ``ineligible_rows``, ``declared_flag_values``, ``work_flag_value``,
    ``free_flag_value``, ``counts``) and per-row keys (``row_index``, ``hkl``,
    ``f_obs``, ``sigf_obs``, ``f_obs_word_hex``, ``sigf_obs_word_hex``,
    ``r_free_flag``, ``r_free_flag_word_hex``, ``is_free``, ``partition``,
    ``eligible``, ``eligibility_status``), and enforces the single explicit
    partition rule ``free_flag_value == EXPECTED_FREE_FLAG_VALUE == 1``
    (``1 = free/test``, ``0 = work``).
    """
    ledger_errors: list[str] = []
    input_rows_list: list[dict[str, Any]] = []
    input_by_hkl: dict[tuple[int, int, int], dict[str, Any]] = {}
    input_hkl_order: list[tuple[int, int, int]] = []
    input_observed_domain_keys: set[tuple[int, int, int]] = set()
    input_positive_amplitude_keys: set[tuple[int, int, int]] = set()
    input_zero_or_negative_f_keys: set[tuple[int, int, int]] = set()
    input_padding_keys: set[tuple[int, int, int]] = set()
    input_work_observed_count = 0
    input_free_observed_count = 0
    input_work_positive_count = 0
    input_free_positive_count = 0

    if not isinstance(input_ledger, Mapping):
        ledger_errors.append(
            f"input_ledger must be a Mapping, got {type(input_ledger).__name__}"
        )
        return {
            "valid": False,
            "errors": ledger_errors,
            "work_flag_value": 0,
            "free_flag_value": EXPECTED_FREE_FLAG_VALUE,
            "declared_flag_values": [0, EXPECTED_FREE_FLAG_VALUE],
            "raw_rows": input_rows_list,
            "input_by_hkl": input_by_hkl,
            "input_hkl_order": input_hkl_order,
            "input_observed_domain_keys": input_observed_domain_keys,
            "input_positive_amplitude_keys": input_positive_amplitude_keys,
            "input_zero_or_negative_f_keys": input_zero_or_negative_f_keys,
            "input_padding_keys": input_padding_keys,
            "input_work_observed_count": input_work_observed_count,
            "input_free_observed_count": input_free_observed_count,
            "input_work_positive_count": input_work_positive_count,
            "input_free_positive_count": input_free_positive_count,
        }

    required_top_keys = (
        "raw_rows",
        "eligible_by_hkl",
        "ineligible_rows",
        "declared_flag_values",
        "work_flag_value",
        "free_flag_value",
        "counts",
    )
    missing_top_keys = [k for k in required_top_keys if k not in input_ledger]
    if missing_top_keys:
        ledger_errors.append(
            f"input_ledger missing required top-level key(s): {missing_top_keys}"
        )

    raw_free_flag_val = input_ledger.get("free_flag_value")
    raw_work_flag_val = input_ledger.get("work_flag_value")
    raw_declared_flags = input_ledger.get("declared_flag_values")
    if (
        isinstance(raw_free_flag_val, bool)
        or not isinstance(raw_free_flag_val, int)
        or raw_free_flag_val != EXPECTED_FREE_FLAG_VALUE
    ):
        ledger_errors.append(
            f"input_ledger free_flag_value must be int {EXPECTED_FREE_FLAG_VALUE}, got {raw_free_flag_val!r}"
        )
        free_flag_value = EXPECTED_FREE_FLAG_VALUE
    else:
        free_flag_value = raw_free_flag_val

    if (
        isinstance(raw_work_flag_val, bool)
        or not isinstance(raw_work_flag_val, int)
        or raw_work_flag_val != 0
    ):
        ledger_errors.append(
            f"input_ledger work_flag_value must be int 0, got {raw_work_flag_val!r}"
        )
        work_flag_value = 0
    else:
        work_flag_value = raw_work_flag_val

    if (
        not isinstance(raw_declared_flags, list)
        or any(isinstance(v, bool) or not isinstance(v, int) for v in raw_declared_flags)
        or raw_declared_flags != [work_flag_value, free_flag_value]
    ):
        ledger_errors.append(
            f"input_ledger declared_flag_values must be {[work_flag_value, free_flag_value]!r}, "
            f"got {raw_declared_flags!r}"
        )
        declared_flag_values = [work_flag_value, free_flag_value]
    else:
        declared_flag_values = list(raw_declared_flags)

    raw_rows_obj = input_ledger.get("raw_rows")
    eligible_by_hkl_obj = input_ledger.get("eligible_by_hkl")
    ineligible_rows_obj = input_ledger.get("ineligible_rows")
    counts_obj = input_ledger.get("counts")

    if not isinstance(raw_rows_obj, list) or len(raw_rows_obj) == 0:
        ledger_errors.append("input_ledger['raw_rows'] must be a non-empty list")
        raw_rows_seq: list[Any] = []
    else:
        raw_rows_seq = raw_rows_obj

    if not isinstance(eligible_by_hkl_obj, Mapping) or len(eligible_by_hkl_obj) == 0:
        ledger_errors.append(
            "input_ledger['eligible_by_hkl'] must be a non-empty mapping"
        )
        eligible_by_hkl_map: Mapping[str, Any] = {}
    else:
        eligible_by_hkl_map = eligible_by_hkl_obj

    if not isinstance(ineligible_rows_obj, list):
        ledger_errors.append("input_ledger['ineligible_rows'] must be a list")
        ineligible_rows_seq: list[Any] = []
    else:
        ineligible_rows_seq = ineligible_rows_obj

    if not isinstance(counts_obj, Mapping):
        ledger_errors.append("input_ledger['counts'] must be a mapping")
        counts_map: Mapping[str, Any] = {}
    else:
        counts_map = counts_obj

    required_row_keys = (
        "row_index",
        "hkl",
        "f_obs",
        "sigf_obs",
        "f_obs_word_hex",
        "sigf_obs_word_hex",
        "r_free_flag",
        "r_free_flag_word_hex",
        "is_free",
        "partition",
        "eligible",
        "eligibility_status",
    )

    for idx, in_row in enumerate(raw_rows_seq):
        if not isinstance(in_row, Mapping):
            ledger_errors.append(
                f"input_ledger['raw_rows'][{idx}] must be a Mapping, got {type(in_row).__name__}"
            )
            continue
        missing_rk = [k for k in required_row_keys if k not in in_row]
        if missing_rk:
            ledger_errors.append(
                f"input_ledger['raw_rows'][{idx}] missing required key(s): {missing_rk}"
            )
            continue
        hkl_seq = in_row.get("hkl")
        if (
            not isinstance(hkl_seq, (list, tuple))
            or len(hkl_seq) != 3
            or any(isinstance(c, bool) or not isinstance(c, int) for c in hkl_seq)
        ):
            ledger_errors.append(
                f"input_ledger['raw_rows'][{idx}] has invalid hkl: {hkl_seq!r}"
            )
            continue
        key = (int(hkl_seq[0]), int(hkl_seq[1]), int(hkl_seq[2]))
        if key in input_by_hkl:
            ledger_errors.append(
                f"input_ledger['raw_rows'] contains duplicate HKL key {list(key)}"
            )
            continue
        row_copy = dict(in_row)
        input_rows_list.append(row_copy)
        input_by_hkl[key] = row_copy
        input_hkl_order.append(key)

        f_obs = row_copy["f_obs"]
        sigf_obs = row_copy["sigf_obs"]
        r_free_flag = row_copy["r_free_flag"]
        is_free = row_copy["is_free"]
        partition = row_copy["partition"]
        eligible = row_copy["eligible"]

        has_finite_f = (
            isinstance(f_obs, (int, float))
            and not isinstance(f_obs, bool)
            and math.isfinite(float(f_obs))
        )
        has_positive_sigf = (
            isinstance(sigf_obs, (int, float))
            and not isinstance(sigf_obs, bool)
            and math.isfinite(float(sigf_obs))
            and float(sigf_obs) > 0.0
        )
        has_valid_flag = (
            isinstance(r_free_flag, int)
            and not isinstance(r_free_flag, bool)
            and r_free_flag in (work_flag_value, free_flag_value)
        )

        if r_free_flag is None:
            if is_free is not None or partition != "unassigned":
                ledger_errors.append(
                    f"input_ledger row {list(key)} with r_free_flag=None has inconsistent "
                    f"is_free={is_free!r}, partition={partition!r}"
                )
        elif has_valid_flag:
            expected_is_free = r_free_flag == free_flag_value
            expected_partition = "free" if expected_is_free else "work"
            if is_free is not expected_is_free or partition != expected_partition:
                ledger_errors.append(
                    f"input_ledger row {list(key)} with r_free_flag={r_free_flag} has inconsistent "
                    f"is_free={is_free!r} (expected {expected_is_free}), "
                    f"partition={partition!r} (expected {expected_partition!r})"
                )
        else:
            ledger_errors.append(
                f"input_ledger row {list(key)} has undeclared r_free_flag={r_free_flag!r}"
            )

        expected_eligible = bool(has_finite_f and has_positive_sigf and has_valid_flag)
        if not isinstance(eligible, bool) or eligible is not expected_eligible:
            ledger_errors.append(
                f"input_ledger row {list(key)} eligible={eligible!r} contradicts "
                f"computed eligibility {expected_eligible}"
            )

        hkl_str = f"{key[0]},{key[1]},{key[2]}"
        if expected_eligible:
            if hkl_str not in eligible_by_hkl_map:
                ledger_errors.append(
                    f"Eligible input_ledger row {hkl_str!r} is missing from eligible_by_hkl"
                )
            input_observed_domain_keys.add(key)
            if r_free_flag == free_flag_value:
                input_free_observed_count += 1
            else:
                input_work_observed_count += 1
            if float(f_obs) > 0.0:
                input_positive_amplitude_keys.add(key)
                if r_free_flag == free_flag_value:
                    input_free_positive_count += 1
                else:
                    input_work_positive_count += 1
            else:
                input_zero_or_negative_f_keys.add(key)
        else:
            if hkl_str in eligible_by_hkl_map:
                ledger_errors.append(
                    f"Ineligible input_ledger row {hkl_str!r} unexpectedly present in eligible_by_hkl"
                )
            input_padding_keys.add(key)

    if eligible_by_hkl_map and len(eligible_by_hkl_map) != len(
        input_observed_domain_keys
    ):
        ledger_errors.append(
            f"input_ledger eligible_by_hkl count ({len(eligible_by_hkl_map)}) != "
            f"indexed eligible rows ({len(input_observed_domain_keys)})"
        )
    if len(ineligible_rows_seq) != len(input_padding_keys):
        ledger_errors.append(
            f"input_ledger ineligible_rows count ({len(ineligible_rows_seq)}) != "
            f"indexed ineligible rows ({len(input_padding_keys)})"
        )
    if isinstance(counts_obj, Mapping):
        expected_counts_checks = (
            ("raw_total", len(input_rows_list)),
            ("eligible_total", len(input_observed_domain_keys)),
            ("eligible_work", input_work_observed_count),
            ("eligible_free", input_free_observed_count),
            ("ineligible_total", len(input_padding_keys)),
        )
        for c_key, expected_val in expected_counts_checks:
            if c_key not in counts_map:
                ledger_errors.append(
                    f"input_ledger counts missing required key {c_key!r}"
                )
                continue
            actual_val = counts_map[c_key]
            if (
                isinstance(actual_val, bool)
                or not isinstance(actual_val, int)
                or actual_val < 0
            ):
                ledger_errors.append(
                    f"input_ledger counts[{c_key!r}] must be a non-negative int, got {actual_val!r}"
                )
            elif actual_val != expected_val:
                ledger_errors.append(
                    f"input_ledger counts[{c_key!r}]={actual_val!r} != indexed count {expected_val}"
                )
        for c_key, actual_val in counts_map.items():
            if c_key in {k for k, _ in expected_counts_checks}:
                continue
            if (
                isinstance(actual_val, bool)
                or not isinstance(actual_val, int)
                or actual_val < 0
            ):
                ledger_errors.append(
                    f"input_ledger counts[{c_key!r}] must be a non-negative int, got {actual_val!r}"
                )

    return {
        "valid": len(ledger_errors) == 0,
        "errors": ledger_errors,
        "work_flag_value": work_flag_value,
        "free_flag_value": free_flag_value,
        "declared_flag_values": declared_flag_values,
        "raw_rows": input_rows_list,
        "input_by_hkl": input_by_hkl,
        "input_hkl_order": input_hkl_order,
        "input_observed_domain_keys": input_observed_domain_keys,
        "input_positive_amplitude_keys": input_positive_amplitude_keys,
        "input_zero_or_negative_f_keys": input_zero_or_negative_f_keys,
        "input_padding_keys": input_padding_keys,
        "input_work_observed_count": input_work_observed_count,
        "input_free_observed_count": input_free_observed_count,
        "input_work_positive_count": input_work_positive_count,
        "input_free_positive_count": input_free_positive_count,
    }


_MTZ_CELL_PARAMETER_NAMES: tuple[str, ...] = (
    "a",
    "b",
    "c",
    "alpha",
    "beta",
    "gamma",
)


def _normalize_exact_decimal_token(value: Decimal) -> str:
    """Return canonical normalized exact-decimal text (matching mtz_crystallographic_context)."""
    sign, digits, exponent = value.as_tuple()
    if not isinstance(exponent, int):
        raise ValueError(f"Non-finite decimal cannot be normalized: {value!r}")
    digits_list = list(digits)
    while len(digits_list) > 1 and digits_list[-1] == 0:
        digits_list.pop()
        exponent += 1
    if digits_list == [0]:
        exponent = 0
        sign = 0
    return str(Decimal((sign, tuple(digits_list), exponent)))


def _analyze_mtz_cell_parameter_token(
    token: str,
    *,
    parameter_name: str,
) -> dict[str, Any]:
    """Compute exact-decimal, IEEE-754 float32 (`mtzdata.h:82-90`), and `%.4f` (`cmtzlib.c:451-453, 526-537, 2671-2697, 2838-2856`) representations."""
    if not isinstance(token, str):
        return {
            "parameter": parameter_name,
            "raw_token": token,
            "valid": False,
            "error": f"Expected str cell parameter token for {parameter_name}, got {type(token).__name__}",
        }
    raw = token.strip()
    if not raw or any(ch.isspace() for ch in raw) or "_" in raw:
        return {
            "parameter": parameter_name,
            "raw_token": token,
            "valid": False,
            "error": f"Empty or malformed cell parameter token for {parameter_name}: {token!r}",
        }
    try:
        exact_dec = Decimal(raw)
    except InvalidOperation as exc:
        return {
            "parameter": parameter_name,
            "raw_token": raw,
            "valid": False,
            "error": f"Non-decimal cell parameter token for {parameter_name} {raw!r}: {exc}",
        }
    if not exact_dec.is_finite() or exact_dec <= Decimal("0"):
        return {
            "parameter": parameter_name,
            "raw_token": raw,
            "valid": False,
            "error": f"Non-finite or non-positive cell parameter token for {parameter_name}: {raw!r}",
        }
    normalized_dec_str = _normalize_exact_decimal_token(exact_dec)
    try:
        packed_f32 = struct.pack("<f", float(exact_dec))
    except (OverflowError, ValueError) as exc:
        return {
            "parameter": parameter_name,
            "raw_token": raw,
            "valid": False,
            "error": f"Failed to pack {parameter_name} token {raw!r} to IEEE-754 binary32: {exc}",
        }
    (f32_val,) = struct.unpack("<f", packed_f32)
    (f32_word_u32,) = struct.unpack("<I", packed_f32)
    if not math.isfinite(f32_val) or f32_val <= 0.0:
        return {
            "parameter": parameter_name,
            "raw_token": raw,
            "valid": False,
            "error": f"Packed IEEE-754 binary32 for {parameter_name} token {raw!r} is non-finite or non-positive",
        }
    f32_word_hex = f"0x{f32_word_u32:08x}"
    f32_exact_dec = Decimal.from_float(f32_val)

    # Exact 10^-4 (`%.4f` / `%9.4f` / `%10.4f`, cmtzlib.c:451-453, 526-537, 2671-2697, 2838-2856)
    # grid analysis around the IEEE-754 binary32 value (`float cell[6]`, mtzdata.h:82-90)
    # using exact rational arithmetic without mutating decimal.getcontext() flags.
    f32_exact_frac = Fraction(f32_val)
    scaled_1e4_frac = f32_exact_frac * 10000
    floor_int = math.floor(scaled_1e4_frac)
    rem_frac = scaled_1e4_frac - floor_int
    lower_4dp_token = _format_exact_power_of_ten_fraction(
        Fraction(floor_int, 10000), 4, min_frac_digits=4
    )
    upper_4dp_token = _format_exact_power_of_ten_fraction(
        Fraction(floor_int + 1, 10000), 4, min_frac_digits=4
    )
    lower_4dp_dec = Decimal(lower_4dp_token)
    upper_4dp_dec = Decimal(upper_4dp_token)
    if rem_frac < Fraction(1, 2):
        is_halfway_tie = False
        nearest_4dp_dec: Decimal | None = lower_4dp_dec
        nearest_4dp_token: str | None = lower_4dp_token
    elif rem_frac > Fraction(1, 2):
        is_halfway_tie = False
        nearest_4dp_dec = upper_4dp_dec
        nearest_4dp_token = upper_4dp_token
    else:
        is_halfway_tie = True
        nearest_4dp_dec = None
        nearest_4dp_token = None

    c_printf_4f_token = f"{f32_val:.4f}"
    c_printf_4f_dec = Decimal(c_printf_4f_token)
    repacked_4f_bytes = struct.pack("<f", float(c_printf_4f_dec))
    (repacked_4f_u32,) = struct.unpack("<I", repacked_4f_bytes)
    repacked_4f_word_hex = f"0x{repacked_4f_u32:08x}"

    return {
        "parameter": parameter_name,
        "raw_token": raw,
        "valid": True,
        "error": None,
        "exact_decimal": exact_dec,
        "exact_decimal_str": str(exact_dec),
        "normalized_exact_decimal": normalized_dec_str,
        "float32_value": float(f32_val),
        "float32_word_hex": f32_word_hex,
        "float32_exact_decimal": f32_exact_dec,
        "float32_exact_decimal_str": str(f32_exact_dec),
        "float32_lower_4dp_decimal": lower_4dp_dec,
        "float32_lower_4dp_token": lower_4dp_token,
        "float32_upper_4dp_decimal": upper_4dp_dec,
        "float32_upper_4dp_token": upper_4dp_token,
        "float32_4dp_is_halfway_tie": is_halfway_tie,
        "float32_nearest_4dp_decimal": nearest_4dp_dec,
        "float32_nearest_4dp_token": nearest_4dp_token,
        "c_printf_4f_token": c_printf_4f_token,
        "c_printf_4f_decimal": c_printf_4f_dec,
        "c_printf_4f_normalized_exact_decimal": _normalize_exact_decimal_token(
            c_printf_4f_dec
        ),
        "c_printf_4f_repacked_word_hex": repacked_4f_word_hex,
    }


def _serialize_mtz_cell_parameter_analysis(
    analysis: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a JSON-serializable copy of an `_analyze_mtz_cell_parameter_token` dict."""
    if not analysis.get("valid"):
        return {
            "parameter": analysis.get("parameter"),
            "raw_token": analysis.get("raw_token"),
            "valid": False,
            "error": analysis.get("error"),
        }
    return {
        "parameter": analysis["parameter"],
        "raw_token": analysis["raw_token"],
        "valid": True,
        "exact_decimal_str": analysis["exact_decimal_str"],
        "normalized_exact_decimal": analysis["normalized_exact_decimal"],
        "float32_value": analysis["float32_value"],
        "float32_word_hex": analysis["float32_word_hex"],
        "float32_exact_decimal_str": analysis["float32_exact_decimal_str"],
        "float32_lower_4dp_token": analysis["float32_lower_4dp_token"],
        "float32_upper_4dp_token": analysis["float32_upper_4dp_token"],
        "float32_4dp_is_halfway_tie": analysis["float32_4dp_is_halfway_tie"],
        "float32_nearest_4dp_token": analysis["float32_nearest_4dp_token"],
        "c_printf_4f_token": analysis["c_printf_4f_token"],
        "c_printf_4f_normalized_exact_decimal": analysis[
            "c_printf_4f_normalized_exact_decimal"
        ],
        "c_printf_4f_repacked_word_hex": analysis["c_printf_4f_repacked_word_hex"],
    }


def _project_exact_decimal_to_finite_float(
    dec_str: str,
    *,
    label: str,
) -> tuple[float | None, str | None]:
    """Project an exact finite decimal string to an IEEE-754 binary64 float if finite."""
    try:
        projected = float(Decimal(dec_str))
    except (InvalidOperation, OverflowError, ValueError) as exc:
        return (
            None,
            f"{label} exact decimal value ({dec_str}) cannot be represented as a finite IEEE-754 binary64 float ({exc})",
        )
    if not math.isfinite(projected):
        return (
            None,
            f"{label} exact decimal value ({dec_str}) overflows finite IEEE-754 binary64 float range",
        )
    return projected, None


def _compute_optional_exact_decimal_abs_diff(
    in_dec: Decimal,
    out_dec: Decimal,
    *,
    label: str,
) -> tuple[Fraction | None, str | None, float | None, str | None]:
    """Compute optional exact ``abs(out_dec - in_dec)`` if within the 4096-digit resource budget, and project to finite binary64 float."""
    in_ok, in_reason = _preflight_optional_decimal_diagnostic(
        in_dec, requested_scale=0, label=f"{label} input"
    )
    out_ok, out_reason = _preflight_optional_decimal_diagnostic(
        out_dec, requested_scale=0, label=f"{label} output"
    )
    unavail_reason = in_reason or out_reason
    if unavail_reason is None:
        in_exp = in_dec.as_tuple().exponent
        out_exp = out_dec.as_tuple().exponent
        assert isinstance(in_exp, int) and isinstance(out_exp, int)
        diff_scale_est = max(-in_exp, -out_exp, 0)
        _, in_align_reason = _preflight_optional_decimal_diagnostic(
            in_dec,
            requested_scale=diff_scale_est,
            label=f"{label} input aligned",
        )
        _, out_align_reason = _preflight_optional_decimal_diagnostic(
            out_dec,
            requested_scale=diff_scale_est,
            label=f"{label} output aligned",
        )
        unavail_reason = in_align_reason or out_align_reason
    if unavail_reason is not None:
        return None, None, None, unavail_reason
    in_frac, in_scale = _decimal_to_exact_fraction_and_scale(in_dec)
    out_frac, out_scale = _decimal_to_exact_fraction_and_scale(out_dec)
    diff_scale = max(in_scale, out_scale)
    abs_diff_frac = abs(out_frac - in_frac)
    abs_diff_str = _format_exact_power_of_ten_fraction(
        abs_diff_frac, diff_scale
    )
    abs_diff_float, float_unavail_reason = (
        _project_exact_decimal_to_finite_float(
            abs_diff_str, label=f"{label} difference"
        )
    )
    return abs_diff_frac, abs_diff_str, abs_diff_float, float_unavail_reason


def _compare_mtz_cell_parameter_representations(
    in_token: str,
    out_token: str,
    *,
    parameter_name: str,
) -> dict[str, Any]:
    """Compare one HKLIN vs HKLOUT cell parameter token under the source-backed MTZ representation contract.

    Grounded in ``ccp4/mtzdata.h:82-90`` (``float cell[6]``) and
    ``ccp4/cmtzlib.c:451-453, 526-537, 2671-2697, 2838-2856``
    (``MtzGet`` assignment/cast of parsed ``DCELL``/``CELL`` token values into
    ``float`` storage and ``MtzPut`` formatting of ``CELL  %9.4f ...`` and
    ``DCELL   %7d %10.4f...``).
    Accepts:
    - exact decimal equivalence (``Decimal(in_token) == Decimal(out_token)``), which
      includes identical tokens and equivalent exponent spellings such as
      ``64.8970`` vs ``6.48970E1`` while preserving both raw tokens and normalized
      exact decimals separately; or
    - exact match of ``Decimal(out_token)`` to the unique nearest 4-decimal-place
      (``%.4f``) emission of the IEEE-754 binary32 ``float cell[6]`` value packed
      from ``in_token`` (when not an exact half-way tie and with matching binary32 word).
    Rejects any parameter drift such as ``64.8970 -> 64.8971`` without fixed
    floating-point tolerances.
    """
    in_rep = _analyze_mtz_cell_parameter_token(
        in_token, parameter_name=parameter_name
    )
    out_rep = _analyze_mtz_cell_parameter_token(
        out_token, parameter_name=parameter_name
    )
    if not in_rep["valid"] or not out_rep["valid"]:
        err_parts = [
            str(r["error"]) for r in (in_rep, out_rep) if not r.get("valid")
        ]
        err_joined = "; ".join(err_parts)
        return {
            "parameter": parameter_name,
            "input_raw_token": in_token,
            "output_raw_token": out_token,
            "abs_exact_decimal_diff_str": None,
            "abs_exact_decimal_diff_str_available": False,
            "abs_exact_decimal_diff_str_unavailable_reason": err_joined,
            "abs_exact_decimal_diff": None,
            "abs_exact_decimal_diff_available": False,
            "abs_exact_decimal_diff_unavailable_reason": err_joined,
            "valid": False,
            "representation_status": "invalid_token",
            "error": err_joined,
            "input_representation": _serialize_mtz_cell_parameter_analysis(in_rep),
            "output_representation": _serialize_mtz_cell_parameter_analysis(out_rep),
        }

    in_dec: Decimal = in_rep["exact_decimal"]
    out_dec: Decimal = out_rep["exact_decimal"]
    _, abs_dec_diff_str, abs_dec_diff_float, diff_unavail_reason = (
        _compute_optional_exact_decimal_abs_diff(
            in_dec, out_dec, label=f"CELL.{parameter_name}"
        )
    )
    exact_token_match = in_rep["raw_token"] == out_rep["raw_token"]
    exact_decimal_match = bool(in_dec == out_dec)
    normalized_exact_decimal_match = (
        in_rep["normalized_exact_decimal"] == out_rep["normalized_exact_decimal"]
    )
    float32_word_match = in_rep["float32_word_hex"] == out_rep["float32_word_hex"]
    output_matches_input_float32_4f_emission = bool(
        not in_rep["float32_4dp_is_halfway_tie"]
        and in_rep["float32_nearest_4dp_decimal"] is not None
        and out_dec == in_rep["float32_nearest_4dp_decimal"]
        and out_dec == in_rep["c_printf_4f_decimal"]
        and out_rep["float32_word_hex"] == in_rep["c_printf_4f_repacked_word_hex"]
    )

    if exact_decimal_match:
        valid = True
        rep_status = (
            "exact_token_match"
            if exact_token_match
            else "equivalent_exact_decimal_representation"
        )
        err_msg: str | None = None
    elif output_matches_input_float32_4f_emission:
        valid = True
        rep_status = "float32_to_4f_header_emission_match"
        err_msg = None
    elif in_rep["float32_4dp_is_halfway_tie"] and out_dec in (
        in_rep["float32_lower_4dp_decimal"],
        in_rep["float32_upper_4dp_decimal"],
    ):
        valid = False
        rep_status = "halfway_tie_unproven"
        err_msg = (
            f"Cell parameter {parameter_name} input {in_rep['raw_token']!r} packs to "
            f"float32 {in_rep['float32_word_hex']} ({in_rep['float32_exact_decimal_str']}) "
            f"at an exact 10^-4 half-way tie between {in_rep['float32_lower_4dp_token']!r} "
            f"and {in_rep['float32_upper_4dp_token']!r}; output {out_rep['raw_token']!r} "
            f"tie-break is unproven"
        )
    else:
        valid = False
        rep_status = "rejected_representation_mismatch"
        err_msg = (
            f"Cell parameter {parameter_name} output token {out_rep['raw_token']!r} "
            f"(exact_decimal={out_rep['exact_decimal_str']}, float32={out_rep['float32_word_hex']}) "
            f"is incompatible with input token {in_rep['raw_token']!r} "
            f"(exact_decimal={in_rep['exact_decimal_str']}, float32={in_rep['float32_word_hex']}, "
            f"float32_%.4f={in_rep['c_printf_4f_token']!r})"
        )

    return {
        "parameter": parameter_name,
        "input_raw_token": in_rep["raw_token"],
        "output_raw_token": out_rep["raw_token"],
        "input_normalized_exact_decimal": in_rep["normalized_exact_decimal"],
        "output_normalized_exact_decimal": out_rep["normalized_exact_decimal"],
        "exact_token_match": exact_token_match,
        "exact_decimal_match": exact_decimal_match,
        "normalized_exact_decimal_match": normalized_exact_decimal_match,
        "float32_word_match": float32_word_match,
        "output_matches_input_float32_4f_emission": (
            output_matches_input_float32_4f_emission
        ),
        "abs_exact_decimal_diff_str": abs_dec_diff_str,
        "abs_exact_decimal_diff_str_available": abs_dec_diff_str is not None,
        "abs_exact_decimal_diff_str_unavailable_reason": (
            None if abs_dec_diff_str is not None else diff_unavail_reason
        ),
        "abs_exact_decimal_diff": abs_dec_diff_float,
        "abs_exact_decimal_diff_available": (
            abs_dec_diff_float is not None and diff_unavail_reason is None
        ),
        "abs_exact_decimal_diff_unavailable_reason": diff_unavail_reason,
        "valid": valid,
        "representation_status": rep_status,
        "error": err_msg,
        "input_representation": _serialize_mtz_cell_parameter_analysis(in_rep),
        "output_representation": _serialize_mtz_cell_parameter_analysis(out_rep),
    }


def _compare_mtz_cell_tuple_representations(
    in_tokens: Sequence[str],
    out_tokens: Sequence[str],
    *,
    label: str,
) -> dict[str, Any]:
    """Compare a 6-parameter MTZ cell tuple (`a, b, c, alpha, beta, gamma`) under the source-backed policy."""
    if len(in_tokens) != 6 or len(out_tokens) != 6:
        err = (
            f"{label}: expected 6 input and 6 output cell tokens, got "
            f"{len(in_tokens)} and {len(out_tokens)}"
        )
        return {
            "label": label,
            "input_raw_tokens": list(in_tokens),
            "output_raw_tokens": list(out_tokens),
            "max_abs_exact_decimal_diff_str": None,
            "max_abs_exact_decimal_diff_str_available": False,
            "max_abs_exact_decimal_diff_str_unavailable_reason": err,
            "max_abs_exact_decimal_diff": None,
            "max_abs_exact_decimal_diff_available": False,
            "max_abs_exact_decimal_diff_unavailable_reason": err,
            "valid": False,
            "errors": [err],
            "parameter_comparisons": [],
        }

    param_comparisons: list[dict[str, Any]] = []
    tuple_errors: list[str] = []
    max_abs_diff_frac = Fraction(0)
    max_abs_dec_diff_str = "0"
    str_unavail_reasons: list[str] = []
    float_unavail_reasons: list[str] = []
    for idx, param_name in enumerate(_MTZ_CELL_PARAMETER_NAMES):
        comp = _compare_mtz_cell_parameter_representations(
            in_tokens[idx],
            out_tokens[idx],
            parameter_name=param_name,
        )
        param_comparisons.append(comp)
        if not comp["valid"]:
            tuple_errors.append(f"{label}: {comp['error']}")
        comp_diff_str = comp.get("abs_exact_decimal_diff_str")
        if (
            comp_diff_str is None
            or comp.get("abs_exact_decimal_diff_str_available") is False
        ):
            reason = (
                comp.get("abs_exact_decimal_diff_str_unavailable_reason")
                or comp.get("abs_exact_decimal_diff_unavailable_reason")
                or f"{param_name} exact decimal difference unavailable"
            )
            str_unavail_reasons.append(f"{param_name}: {reason}")
            float_unavail_reasons.append(f"{param_name}: {reason}")
            continue
        diff_dec = Decimal(str(comp_diff_str))
        diff_ok, diff_reason = _preflight_optional_decimal_diagnostic(
            diff_dec, requested_scale=0, label=f"{label}.{param_name} diff"
        )
        if not diff_ok:
            str_unavail_reasons.append(f"{param_name}: {diff_reason}")
            float_unavail_reasons.append(f"{param_name}: {diff_reason}")
            continue
        diff_frac, _ = _decimal_to_exact_fraction_and_scale(diff_dec)
        if diff_frac > max_abs_diff_frac:
            max_abs_diff_frac = diff_frac
            max_abs_dec_diff_str = str(comp_diff_str)
        if (
            comp.get("abs_exact_decimal_diff") is None
            or comp.get("abs_exact_decimal_diff_available") is False
        ):
            f_reason = comp.get("abs_exact_decimal_diff_unavailable_reason") or (
                f"{param_name} float projection unavailable"
            )
            float_unavail_reasons.append(f"{param_name}: {f_reason}")

    if str_unavail_reasons:
        tuple_max_diff_str: str | None = None
        tuple_max_diff_str_available = False
        tuple_max_diff_str_unavail_reason: str | None = "; ".join(
            str_unavail_reasons
        )
    else:
        tuple_max_diff_str = max_abs_dec_diff_str
        tuple_max_diff_str_available = True
        tuple_max_diff_str_unavail_reason = None

    if float_unavail_reasons:
        tuple_max_diff_float: float | None = None
        tuple_max_diff_available = False
        tuple_max_diff_unavail_reason: str | None = "; ".join(
            float_unavail_reasons
        )
    else:
        proj_float, proj_reason = _project_exact_decimal_to_finite_float(
            max_abs_dec_diff_str, label=f"{label}.max_abs_exact_decimal_diff"
        )
        if proj_float is not None and proj_reason is None:
            tuple_max_diff_float = proj_float
            tuple_max_diff_available = True
            tuple_max_diff_unavail_reason = None
        else:
            tuple_max_diff_float = None
            tuple_max_diff_available = False
            tuple_max_diff_unavail_reason = proj_reason

    exact_token_tuple_match = all(
        bool(c.get("exact_token_match")) for c in param_comparisons
    )
    exact_decimal_tuple_match = all(
        bool(c.get("exact_decimal_match")) for c in param_comparisons
    )
    normalized_exact_decimal_tuple_match = all(
        bool(c.get("normalized_exact_decimal_match")) for c in param_comparisons
    )
    float32_word_tuple_match = all(
        bool(c.get("float32_word_match")) for c in param_comparisons
    )

    return {
        "label": label,
        "input_raw_tokens": list(in_tokens),
        "output_raw_tokens": list(out_tokens),
        "input_normalized_exact_decimals": [
            c.get("input_normalized_exact_decimal") for c in param_comparisons
        ],
        "output_normalized_exact_decimals": [
            c.get("output_normalized_exact_decimal") for c in param_comparisons
        ],
        "exact_token_tuple_match": exact_token_tuple_match,
        "exact_decimal_tuple_match": exact_decimal_tuple_match,
        "normalized_exact_decimal_tuple_match": (
            normalized_exact_decimal_tuple_match
        ),
        "float32_word_tuple_match": float32_word_tuple_match,
        "max_abs_exact_decimal_diff_str": tuple_max_diff_str,
        "max_abs_exact_decimal_diff_str_available": (
            tuple_max_diff_str_available
        ),
        "max_abs_exact_decimal_diff_str_unavailable_reason": (
            tuple_max_diff_str_unavail_reason
        ),
        "max_abs_exact_decimal_diff": tuple_max_diff_float,
        "max_abs_exact_decimal_diff_available": tuple_max_diff_available,
        "max_abs_exact_decimal_diff_unavailable_reason": (
            tuple_max_diff_unavail_reason
        ),
        "valid": len(tuple_errors) == 0,
        "errors": tuple_errors,
        "parameter_comparisons": param_comparisons,
    }


def _extract_mtz_raw_header_cell_context(
    mtz_bytes: bytes,
    *,
    label: str,
) -> dict[str, Any]:
    """Extract raw MTZ `CELL`, `DCELL`, `DWAVEL`/`DWAV`, and `RESO` header records (`cmtzlib.c:451-453, 526-537, 2671-2697, 2838-2857`)."""
    header_errors: list[str] = []
    try:
        header_byte_offset, header_cards = (
            audit_1sar_retained_evidence._mtz_headers(mtz_bytes)
        )
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
        return {
            "label": label,
            "valid": False,
            "errors": [f"{label} failed _mtz_headers: {err}"],
            "header_byte_offset": None,
            "cell_raw_record": None,
            "cell_raw_tokens": [],
            "cell_normalized_exact_decimals": [],
            "dcell_records": [],
            "dwav_records": [],
            "internal_dcell_matches_cell": False,
            "header_order_dcell_observation": None,
            "reso_raw_record": None,
            "reso_raw_tokens": [],
        }

    projects_by_setid: dict[str, str] = {}
    crystals_by_setid: dict[str, str] = {}
    datasets_by_setid: dict[str, str] = {}
    dwav_by_setid: dict[str, list[str]] = {}
    dwav_keyword_by_setid: dict[str, str] = {}
    dwav_raw_record_by_setid: dict[str, str] = {}
    dwav_records: list[dict[str, Any]] = []
    for card in header_cards:
        stripped = card.strip()
        if stripped.startswith("PROJECT "):
            parts = stripped.split(maxsplit=2)
            if len(parts) >= 2:
                projects_by_setid[parts[1]] = parts[2] if len(parts) > 2 else ""
        elif stripped.startswith("CRYSTAL "):
            parts = stripped.split(maxsplit=2)
            if len(parts) >= 2:
                crystals_by_setid[parts[1]] = parts[2] if len(parts) > 2 else ""
        elif stripped.startswith("DATASET "):
            parts = stripped.split(maxsplit=2)
            if len(parts) >= 2:
                datasets_by_setid[parts[1]] = parts[2] if len(parts) > 2 else ""
        elif stripped.startswith(("DWAVEL ", "DWAV ")) or stripped in (
            "DWAVEL",
            "DWAV",
        ):
            parts = stripped.split()
            if len(parts) >= 2 and parts[0] in ("DWAVEL", "DWAV"):
                ds_id = parts[1]
                wav_tokens = parts[2:]
                dwav_by_setid[ds_id] = list(wav_tokens)
                dwav_keyword_by_setid[ds_id] = parts[0]
                dwav_raw_record_by_setid[ds_id] = stripped
                dwav_records.append(
                    {
                        "ordinal": len(dwav_records),
                        "keyword": parts[0],
                        "dataset_setid": ds_id,
                        "dwav_tokens": list(wav_tokens),
                        "dwavel_tokens": list(wav_tokens),
                        "wavelength_present": len(wav_tokens) > 0,
                        "raw_record": stripped,
                    }
                )

    cell_cards = [
        card for card in header_cards if card.startswith("CELL ") or card == "CELL"
    ]
    cell_raw_record: str | None = None
    cell_raw_tokens: list[str] = []
    cell_decimals: list[Decimal] = []
    cell_normalized_decimals: list[str] = []
    if len(cell_cards) != 1:
        header_errors.append(
            f"{label}: expected exactly 1 CELL header, found {len(cell_cards)}"
        )
    else:
        cell_raw_record = cell_cards[0].strip()
        cell_parts = cell_raw_record.split()
        if len(cell_parts) != 7:
            header_errors.append(
                f"{label}: malformed CELL header {cell_raw_record!r} (expected 6 parameter tokens)"
            )
        else:
            cell_raw_tokens = cell_parts[1:]
            for idx, tok in enumerate(cell_raw_tokens):
                param_name = _MTZ_CELL_PARAMETER_NAMES[idx]
                analysis = _analyze_mtz_cell_parameter_token(
                    tok, parameter_name=param_name
                )
                if not analysis["valid"]:
                    header_errors.append(
                        f"{label} CELL.{param_name}: {analysis['error']}"
                    )
                else:
                    cell_decimals.append(analysis["exact_decimal"])
                    cell_normalized_decimals.append(
                        analysis["normalized_exact_decimal"]
                    )

    dcell_cards = [
        card
        for card in header_cards
        if card.startswith("DCELL ") or card == "DCELL"
    ]
    dcell_records: list[dict[str, Any]] = []
    internal_dcell_matches_cell = len(cell_decimals) == 6 and len(dcell_cards) > 0
    if not dcell_cards:
        header_errors.append(f"{label}: missing DCELL header in MTZ")
        internal_dcell_matches_cell = False
    for dcell_idx, dcell_card in enumerate(dcell_cards):
        raw_dcell = dcell_card.strip()
        parts = raw_dcell.split()
        if len(parts) != 8:
            header_errors.append(
                f"{label}: malformed DCELL header {raw_dcell!r} (expected dataset_setid + 6 cell tokens)"
            )
            internal_dcell_matches_cell = False
            continue
        dataset_setid = parts[1]
        dcell_tokens = parts[2:]
        dcell_decs: list[Decimal] = []
        dcell_norm_decs: list[str] = []
        dcell_valid = True
        for idx, tok in enumerate(dcell_tokens):
            param_name = _MTZ_CELL_PARAMETER_NAMES[idx]
            analysis = _analyze_mtz_cell_parameter_token(
                tok, parameter_name=param_name
            )
            if not analysis["valid"]:
                header_errors.append(
                    f"{label} DCELL[{dataset_setid}].{param_name}: {analysis['error']}"
                )
                dcell_valid = False
            else:
                dcell_decs.append(analysis["exact_decimal"])
                dcell_norm_decs.append(analysis["normalized_exact_decimal"])
        matches_primary_cell = (
            dcell_valid
            and len(cell_decimals) == 6
            and dcell_decs == cell_decimals
        )
        if not matches_primary_cell:
            internal_dcell_matches_cell = False
            header_errors.append(
                f"{label}: DCELL record for dataset setid {dataset_setid!r} ({dcell_tokens}) "
                f"does not match primary CELL ({cell_raw_tokens})"
            )
        ds_dwav_tokens = list(dwav_by_setid.get(dataset_setid, []))
        dcell_records.append(
            {
                "ordinal": dcell_idx,
                "dataset_setid": dataset_setid,
                "project": projects_by_setid.get(dataset_setid),
                "crystal": crystals_by_setid.get(dataset_setid),
                "dataset": datasets_by_setid.get(dataset_setid),
                "dwav_tokens": ds_dwav_tokens,
                "dwavel_tokens": list(ds_dwav_tokens),
                "dwav_keyword": dwav_keyword_by_setid.get(dataset_setid),
                "dwav_raw_record": dwav_raw_record_by_setid.get(dataset_setid),
                "wavelength_present": len(ds_dwav_tokens) > 0,
                "raw_record": raw_dcell,
                "dcell_raw_tokens": dcell_tokens,
                "dcell_normalized_exact_decimals": dcell_norm_decs,
                "matches_primary_cell_exact_decimal": matches_primary_cell,
            }
        )

    # Record header-order DCELL observations without claiming native active crystal/dataset
    # selection or executable linkage to cmtzlib.c. In cmtzlib.c:1240-1249, ccp4_lrcell simply
    # copies xtl->cell[i] from a caller-supplied MTZXTAL *xtl, and MtzPut (cmtzlib.c:2838-2856)
    # keys PROJECT/CRYSTAL/DATASET/DCELL by dataset setid rather than crystal index.
    non_zero_setid_dcells = [
        rec for rec in dcell_records if rec["dataset_setid"] != "0"
    ]
    header_order_dcell_observation: dict[str, Any] = {
        "dcell_record_count": len(dcell_records),
        "dataset_setids_in_header_order": [
            rec["dataset_setid"] for rec in dcell_records
        ],
        "first_dcell_dataset_setid": (
            dcell_records[0]["dataset_setid"] if dcell_records else None
        ),
        "first_non_zero_setid_dcell_dataset_setid": (
            non_zero_setid_dcells[0]["dataset_setid"]
            if non_zero_setid_dcells
            else None
        ),
        "all_dcell_records_match_primary_cell_exact_decimal": (
            internal_dcell_matches_cell
        ),
        "native_crystal_or_dataset_selection_proven": False,
        "executable_cmtzlib_linkage_proven": False,
        "selection_boundary_note": (
            "ccp4/cmtzlib.c:1240-1249 (ccp4_lrcell) copies xtl->cell[i] for a caller-supplied "
            "MTZXTAL *xtl rather than selecting a crystal or dataset from MTZ headers; "
            "ccp4/cmtzlib.c:2838-2856 (MtzPut) writes PROJECT/CRYSTAL/DATASET/DCELL keyed by "
            "dataset setid. Which crystal/dataset cell a native consumer selects is not proven "
            "from header order alone."
        ),
    }

    reso_cards = [
        card for card in header_cards if card.startswith("RESO ") or card == "RESO"
    ]
    reso_raw_record: str | None = None
    reso_raw_tokens: list[str] = []
    if len(reso_cards) != 1:
        header_errors.append(
            f"Expected exactly 1 RESO header in {label}, found {len(reso_cards)}"
        )
    else:
        reso_raw_record = reso_cards[0].strip()
        reso_raw_tokens = reso_raw_record.split()[1:]
        if len(reso_raw_tokens) != 2:
            header_errors.append(
                f"Expected 2 RESO tokens in {label}, found {reso_raw_tokens!r}"
            )

    return {
        "label": label,
        "valid": len(header_errors) == 0,
        "errors": header_errors,
        "header_byte_offset": int(header_byte_offset),
        "cell_raw_record": cell_raw_record,
        "cell_raw_tokens": cell_raw_tokens,
        "cell_normalized_exact_decimals": cell_normalized_decimals,
        "dcell_records": dcell_records,
        "dwav_records": dwav_records,
        "internal_dcell_matches_cell": internal_dcell_matches_cell,
        "header_order_dcell_observation": header_order_dcell_observation,
        "reso_raw_record": reso_raw_record,
        "reso_raw_tokens": reso_raw_tokens,
    }


def _evaluate_mtz_cell_representation_policy(
    in_raw_ctx: Mapping[str, Any] | None,
    out_raw_ctx: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Evaluate the source-grounded MTZ `CELL`/`DCELL` representation policy (#1046).

    Tied to ``ccp4/mtzdata.h:82-90`` (``float cell[6]``) and
    ``ccp4/cmtzlib.c:451-453, 526-537, 1240-1249, 2671-2697, 2838-2856``
    (``MtzGet`` assignment/cast of parsed ``DCELL`` and ``CELL`` token values
    into ``float`` storage, ``ccp4_lrcell`` copying ``xtl->cell[i]`` for a
    caller-supplied ``MTZXTAL *xtl``, and ``MtzPut`` formatting of
    ``CELL  %9.4f ...`` and ``DCELL   %7d %10.4f...`` keyed by dataset
    ``setid``). Uses no fixed floating-point tolerance (neither ``0.00015``
    nor ``1e-4``) and makes no unproven claim about native active
    crystal/dataset selection or executable linkage.
    """
    source_citations = [
        "ccp4/mtzdata.h:82-90 (MTZXTAL float cell[6])",
        "ccp4/cmtzlib.c:451-453 (MtzGet DCELL assigns/casts (float) token[i+2].value into mtz->xtal[jxtalin[iiset]]->cell[i])",
        "ccp4/cmtzlib.c:526-537 (MtzGet CELL assigns/casts (float) token[i+1].value into totcell[i] and copies to mtz->xtal[i]->cell when cell[0] < 0.01)",
        "ccp4/cmtzlib.c:1240-1249 (ccp4_lrcell copies xtl->cell[i] for caller-supplied MTZXTAL *xtl)",
        "ccp4/cmtzlib.c:2671-2697 (MtzPut CELL %9.4f header formatting)",
        "ccp4/cmtzlib.c:2838-2856 (MtzPut PROJECT/CRYSTAL/DATASET/DCELL %7d %10.4f formatting keyed by dataset setid)",
    ]
    policy_errors: list[str] = []
    if in_raw_ctx is None or out_raw_ctx is None:
        policy_errors.append(
            "Cannot evaluate MTZ CELL/DCELL representation policy: raw HKLIN or HKLOUT header context is unavailable"
        )
        return {
            "policy_id": "ccp4_mtz_float32_cell_and_4f_header_representation_v1",
            "source_citations": source_citations,
            "fixed_tolerance_removed": True,
            "native_crystal_or_dataset_selection_proven": False,
            "executable_cmtzlib_linkage_proven": False,
            "valid": False,
            "errors": policy_errors,
            "input_dcell_matches_input_cell": False,
            "output_dcell_matches_output_cell": False,
            "primary_cell_comparison": None,
            "dcell_comparisons": [],
        }

    in_dcell_ok = bool(in_raw_ctx.get("internal_dcell_matches_cell"))
    out_dcell_ok = bool(out_raw_ctx.get("internal_dcell_matches_cell"))
    if not in_dcell_ok:
        policy_errors.append(
            "HKLIN dataset DCELL records do not match HKLIN primary CELL"
        )
    if not out_dcell_ok:
        policy_errors.append(
            "HKLOUT dataset DCELL records do not match HKLOUT primary CELL"
        )
    for err in in_raw_ctx.get("errors", []):
        if err not in policy_errors:
            policy_errors.append(str(err))
    for err in out_raw_ctx.get("errors", []):
        if err not in policy_errors:
            policy_errors.append(str(err))

    primary_cell_comp = _compare_mtz_cell_tuple_representations(
        in_raw_ctx.get("cell_raw_tokens", []),
        out_raw_ctx.get("cell_raw_tokens", []),
        label="primary_CELL (cmtzlib.c:526-537, 2671-2697)",
    )
    if not primary_cell_comp["valid"]:
        policy_errors.extend(primary_cell_comp["errors"])

    in_dcell_by_setid: dict[str, Mapping[str, Any]] = {
        str(rec["dataset_setid"]): rec
        for rec in in_raw_ctx.get("dcell_records", [])
        if isinstance(rec, Mapping) and "dataset_setid" in rec
    }
    out_dcell_records = [
        rec
        for rec in out_raw_ctx.get("dcell_records", [])
        if isinstance(rec, Mapping) and "dataset_setid" in rec
    ]
    dcell_comparisons: list[dict[str, Any]] = []
    in_primary_tokens = in_raw_ctx.get("cell_raw_tokens", [])
    for out_rec in out_dcell_records:
        dataset_setid = str(out_rec["dataset_setid"])
        if dataset_setid in in_dcell_by_setid:
            in_ref_rec = in_dcell_by_setid[dataset_setid]
            in_ref_tokens = in_ref_rec.get("dcell_raw_tokens", [])
            ref_source = f"HKLIN DCELL[{dataset_setid}]"
        else:
            in_ref_tokens = in_primary_tokens
            ref_source = "HKLIN primary_CELL"
        d_comp = _compare_mtz_cell_tuple_representations(
            in_ref_tokens,
            out_rec.get("dcell_raw_tokens", []),
            label=(
                f"DCELL[{dataset_setid}] vs {ref_source} "
                f"(cmtzlib.c:451-453, 2838-2856)"
            ),
        )
        d_comp["dataset_setid"] = dataset_setid
        d_comp["reference_source"] = ref_source
        d_comp["matches_output_primary_cell_exact_decimal"] = bool(
            out_rec.get("matches_primary_cell_exact_decimal")
        )
        dcell_comparisons.append(d_comp)
        if not d_comp["valid"]:
            policy_errors.extend(d_comp["errors"])

    out_dcell_setids = {str(rec["dataset_setid"]) for rec in out_dcell_records}
    out_primary_tokens = out_raw_ctx.get("cell_raw_tokens", [])
    for dataset_setid, in_rec in in_dcell_by_setid.items():
        if dataset_setid in out_dcell_setids:
            continue
        d_comp = _compare_mtz_cell_tuple_representations(
            in_rec.get("dcell_raw_tokens", []),
            out_primary_tokens,
            label=(
                f"HKLIN DCELL[{dataset_setid}] vs HKLOUT primary_CELL "
                f"(cmtzlib.c:451-453, 2838-2856)"
            ),
        )
        d_comp["dataset_setid"] = dataset_setid
        d_comp["reference_source"] = "HKLOUT primary_CELL"
        dcell_comparisons.append(d_comp)
        if not d_comp["valid"]:
            policy_errors.extend(d_comp["errors"])

    return {
        "policy_id": "ccp4_mtz_float32_cell_and_4f_header_representation_v1",
        "source_citations": source_citations,
        "fixed_tolerance_removed": True,
        "native_crystal_or_dataset_selection_proven": False,
        "executable_cmtzlib_linkage_proven": False,
        "valid": len(policy_errors) == 0,
        "errors": policy_errors,
        "input_dcell_matches_input_cell": in_dcell_ok,
        "output_dcell_matches_output_cell": out_dcell_ok,
        "primary_cell_exact_token_tuple_match": bool(
            primary_cell_comp.get("exact_token_tuple_match")
        ),
        "primary_cell_exact_decimal_tuple_match": bool(
            primary_cell_comp.get("exact_decimal_tuple_match")
        ),
        "primary_cell_float32_word_tuple_match": bool(
            primary_cell_comp.get("float32_word_tuple_match")
        ),
        "primary_cell_comparison": primary_cell_comp,
        "dcell_comparisons": dcell_comparisons,
    }


def _export_and_audit_refmac_hklout(
    *,
    projected_mtz_path: Path,
    hklout_path: Path,
    hklout_info: dict[str, Any],
    input_ledger: dict[str, Any],
    parsed_log: dict[str, Any] | None,
    native_log_diagnostics: dict[str, Any] | None,
    raw_export_json_path: Path,
    refmac_dir: Path,
    hklin_baseline: Mapping[str, Any] | None = None,
    retained_raw_export_holder: list[dict[str, Any]] | None = None,
    parent_retention_dir: Path | None = None,
    parent_retention_dir_baseline: Mapping[str, Any] | None = None,
    parent_retention_dir_status: dict[str, Any] | None = None,
    verified_root_fallback_state: dict[str, Any] | None = None,
    allow_unpersisted_on_no_verified_anchor: bool = False,
    refmac_dir_status: dict[str, Any] | None = None,
    child_dir_persistence_failures: list[dict[str, Any]] | None = None,
    caught_persistence_exceptions: list[Exception] | None = None,
    child_dir_persistence_causes: list[Exception | None] | None = None,
    parent_retention_dir_cause_sink: list[Exception | None] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Export raw HKLOUT MTZ contents first, then audit crystallographic context, 1-to-1 HKLs, and FC_ALL_LS."""
    raw_export, hklout_bytes = _raw_export_mtz_file(hklout_path, mtz_info=hklout_info)
    raw_export_artifact = _persist_collector_json_with_fallback(
        raw_export,
        raw_export_json_path,
        root=refmac_dir,
        parent_retention_dir=parent_retention_dir,
        parent_retention_dir_baseline=parent_retention_dir_baseline,
        parent_retention_dir_status=parent_retention_dir_status,
        verified_root_fallback_state=verified_root_fallback_state,
        allow_unpersisted_on_no_verified_anchor=allow_unpersisted_on_no_verified_anchor,
        refmac_dir_status=refmac_dir_status,
        child_dir_persistence_failures=child_dir_persistence_failures,
        caught_persistence_exceptions=caught_persistence_exceptions,
        child_dir_persistence_causes=child_dir_persistence_causes,
        parent_retention_dir_cause_sink=parent_retention_dir_cause_sink,
    )
    if retained_raw_export_holder is not None:
        retained_raw_export_holder.append(raw_export_artifact)

    errors: list[str] = []
    if raw_export["raw_export_error"] is not None:
        errors.append(str(raw_export["raw_export_error"]))

    hklin_check = _verify_and_read_admitted_input_file(
        projected_mtz_path,
        hklin_baseline,
        label="HKLIN",
    )
    hklin_bytes: bytes | None = hklin_check["bytes"]
    input_context: dict[str, Any] | None = None
    input_context_error: str | None = None
    if not hklin_check["verified"] or hklin_bytes is None:
        input_context_error = str(
            hklin_check["error"] or f"HKLIN verification failed: {projected_mtz_path}"
        )
        errors.append(
            f"Failed to read HKLIN crystallographic context: {input_context_error}"
        )
    else:
        try:
            raw_in_ctx = audit_1sar_retained_evidence.mtz_crystallographic_context(
                hklin_bytes
            )
            input_context = {
                "cell_a_b_c_alpha_beta_gamma": list(
                    raw_in_ctx["cell_a_b_c_alpha_beta_gamma"]
                ),
                "resolution_limits_inverse_a2": list(
                    raw_in_ctx["resolution_limits_inverse_a2"]
                ),
                "symmetry": copy.deepcopy(raw_in_ctx["symmetry"]),
            }
        except Exception as exc:
            input_context_error = f"{type(exc).__name__}: {exc}"
            errors.append(
                f"Failed to read HKLIN crystallographic context: {input_context_error}"
            )

    output_context: dict[str, Any] | None = None
    output_context_error: str | None = None
    if hklout_bytes is None:
        output_context_error = str(
            raw_export["raw_export_error"] or "HKLOUT bytes unavailable"
        )
        errors.append(
            f"HKLOUT failed strict crystallographic context validation: {output_context_error}"
        )
    else:
        try:
            raw_out_ctx = audit_1sar_retained_evidence.mtz_crystallographic_context(
                hklout_bytes
            )
            output_context = {
                "cell_a_b_c_alpha_beta_gamma": list(
                    raw_out_ctx["cell_a_b_c_alpha_beta_gamma"]
                ),
                "resolution_limits_inverse_a2": list(
                    raw_out_ctx["resolution_limits_inverse_a2"]
                ),
                "symmetry": copy.deepcopy(raw_out_ctx["symmetry"]),
            }
        except Exception as exc:
            output_context_error = f"{type(exc).__name__}: {exc}"
            errors.append(
                f"HKLOUT failed strict crystallographic context validation: {output_context_error}"
            )

    output_layout_summary: dict[str, Any] | None = None
    output_layout_error: str | None = None
    if hklout_bytes is None:
        output_layout_error = str(
            raw_export["raw_export_error"]
            or "HKLOUT bytes unavailable for layout inspection"
        )
        errors.append(
            f"HKLOUT failed strict MTZ layout/dataset inspection: {output_layout_error}"
        )
    else:
        try:
            layout = onesar_rerun._inspect_mtz_layout(
                hklout_bytes, HKLOUT_OBSERVATION_LABELS
            )
            output_layout_summary = {
                "header_byte_offset": int(layout["header_byte_offset"]),
                "ncols": int(layout["ncols"]),
                "nrows": int(layout["nrows"]),
                "columns": list(layout["columns"]),
                "col_indices": {
                    str(k): int(v) for k, v in layout["col_indices"].items()
                },
                "bindings": copy.deepcopy(layout["bindings"]),
                "datasets": copy.deepcopy(raw_export["header_parse"]["datasets"]),
            }
        except Exception as exc:
            output_layout_error = f"{type(exc).__name__}: {exc}"
            errors.append(
                f"HKLOUT failed strict MTZ layout/dataset inspection: {output_layout_error}"
            )

    input_raw_header_context: dict[str, Any] | None = None
    in_reso_tokens: list[str] = []
    input_headers_error: str | None = None
    in_header_byte_offset: int | None = None
    if hklin_check["verified"] and hklin_bytes is not None:
        input_raw_header_context = _extract_mtz_raw_header_cell_context(
            hklin_bytes, label="HKLIN"
        )
        in_header_byte_offset = input_raw_header_context["header_byte_offset"]
        in_reso_tokens = list(input_raw_header_context["reso_raw_tokens"])
        if not input_raw_header_context["valid"]:
            input_headers_error = "; ".join(input_raw_header_context["errors"])
            errors.append(
                f"Failed to read HKLIN MTZ headers via _mtz_headers: {input_headers_error}"
            )
    else:
        input_headers_error = input_context_error or "HKLIN bytes unavailable"
        errors.append(
            f"Failed to read HKLIN MTZ headers via _mtz_headers: {input_headers_error}"
        )

    output_raw_header_context: dict[str, Any] | None = None
    if hklout_bytes is not None:
        output_raw_header_context = _extract_mtz_raw_header_cell_context(
            hklout_bytes, label="HKLOUT"
        )

    cell_representation_policy = _evaluate_mtz_cell_representation_policy(
        input_raw_header_context,
        output_raw_header_context,
    )
    if not cell_representation_policy["valid"]:
        for pol_err in cell_representation_policy["errors"]:
            if pol_err not in errors:
                errors.append(pol_err)

    symmetry_exact_match = False
    exact_context_dict_equality = False
    exact_cell_tuple_match = False
    max_abs_cell_diff_str: str | None = None
    max_abs_cell_diff_str_available: bool | None = None
    max_abs_cell_diff_str_unavailable_reason: str | None = None
    max_abs_cell_diff: float | None = None
    max_abs_cell_diff_available: bool | None = None
    max_abs_cell_diff_unavailable_reason: str | None = None
    cell_representation_valid = bool(cell_representation_policy["valid"])
    output_dcell_matches_output_cell = bool(
        cell_representation_policy["output_dcell_matches_output_cell"]
    )
    if input_context is not None and output_context is not None:
        exact_context_dict_equality = input_context == output_context
        symmetry_exact_match = (
            input_context["symmetry"] == output_context["symmetry"]
        )
        if not symmetry_exact_match:
            errors.append(
                "HKLOUT crystallographic symmetry does not exactly match HKLIN symmetry"
            )
        in_cell = input_context["cell_a_b_c_alpha_beta_gamma"]
        out_cell = output_context["cell_a_b_c_alpha_beta_gamma"]
        exact_cell_tuple_match = in_cell == out_cell
        if len(in_cell) == 6 and len(out_cell) == 6:
            max_cell_diff_frac = Fraction(0)
            max_cell_diff_str = "0"
            cell_str_unavail_reasons: list[str] = []
            cell_float_unavail_reasons: list[str] = []
            for idx, (a, b) in enumerate(zip(in_cell, out_cell)):
                p_name = _MTZ_CELL_PARAMETER_NAMES[idx]
                try:
                    a_dec = Decimal(str(a))
                    b_dec = Decimal(str(b))
                except (InvalidOperation, ValueError) as exc:
                    cell_str_unavail_reasons.append(
                        f"context_cell.{p_name}: {exc}"
                    )
                    cell_float_unavail_reasons.append(
                        f"context_cell.{p_name}: {exc}"
                    )
                    continue
                d_frac, d_str, d_float, d_reason = (
                    _compute_optional_exact_decimal_abs_diff(
                        a_dec, b_dec, label=f"context_cell.{p_name}"
                    )
                )
                if d_frac is None or d_str is None:
                    cell_str_unavail_reasons.append(
                        f"context_cell.{p_name}: {d_reason}"
                    )
                    cell_float_unavail_reasons.append(
                        f"context_cell.{p_name}: {d_reason}"
                    )
                else:
                    if d_frac > max_cell_diff_frac:
                        max_cell_diff_frac = d_frac
                        max_cell_diff_str = d_str
                    if d_float is None or d_reason is not None:
                        cell_float_unavail_reasons.append(
                            f"context_cell.{p_name}: {d_reason}"
                        )
            if cell_str_unavail_reasons:
                max_abs_cell_diff_str = None
                max_abs_cell_diff_str_available = False
                max_abs_cell_diff_str_unavailable_reason = "; ".join(
                    cell_str_unavail_reasons
                )
            else:
                max_abs_cell_diff_str = max_cell_diff_str
                max_abs_cell_diff_str_available = True
                max_abs_cell_diff_str_unavailable_reason = None
            if cell_float_unavail_reasons:
                max_abs_cell_diff = None
                max_abs_cell_diff_available = False
                max_abs_cell_diff_unavailable_reason = "; ".join(
                    cell_float_unavail_reasons
                )
            else:
                proj_cell_float, proj_cell_reason = (
                    _project_exact_decimal_to_finite_float(
                        max_cell_diff_str,
                        label="context_cell.max_abs_cell_parameter_diff",
                    )
                )
                if proj_cell_float is not None and proj_cell_reason is None:
                    max_abs_cell_diff = proj_cell_float
                    max_abs_cell_diff_available = True
                    max_abs_cell_diff_unavailable_reason = None
                else:
                    max_abs_cell_diff = None
                    max_abs_cell_diff_available = False
                    max_abs_cell_diff_unavailable_reason = proj_cell_reason
    elif cell_representation_policy["primary_cell_comparison"] is not None:
        primary_comp = cell_representation_policy["primary_cell_comparison"]
        primary_max_str = primary_comp.get("max_abs_exact_decimal_diff_str")
        if (
            primary_max_str is not None
            and primary_comp.get("max_abs_exact_decimal_diff_str_available")
            is not False
        ):
            max_abs_cell_diff_str = str(primary_max_str)
            max_abs_cell_diff_str_available = True
            max_abs_cell_diff_str_unavailable_reason = None
        else:
            max_abs_cell_diff_str = None
            max_abs_cell_diff_str_available = False
            max_abs_cell_diff_str_unavailable_reason = (
                primary_comp.get(
                    "max_abs_exact_decimal_diff_str_unavailable_reason"
                )
                or primary_comp.get(
                    "max_abs_exact_decimal_diff_unavailable_reason"
                )
            )
        primary_max_diff = primary_comp.get("max_abs_exact_decimal_diff")
        if (
            primary_max_diff is not None
            and primary_comp.get("max_abs_exact_decimal_diff_available")
            is not False
        ):
            proj_primary_float, proj_primary_reason = (
                _project_exact_decimal_to_finite_float(
                    str(primary_max_str or primary_max_diff),
                    label="primary_cell_comparison.max_abs_exact_decimal_diff",
                )
            )
            if proj_primary_float is not None and proj_primary_reason is None:
                max_abs_cell_diff = proj_primary_float
                max_abs_cell_diff_available = True
                max_abs_cell_diff_unavailable_reason = None
            else:
                max_abs_cell_diff = None
                max_abs_cell_diff_available = False
                max_abs_cell_diff_unavailable_reason = proj_primary_reason
        else:
            max_abs_cell_diff = None
            max_abs_cell_diff_available = False
            max_abs_cell_diff_unavailable_reason = primary_comp.get(
                "max_abs_exact_decimal_diff_unavailable_reason"
            )

    out_reso_tokens = (
        list(output_raw_header_context["reso_raw_tokens"])
        if output_raw_header_context is not None
        and output_raw_header_context["reso_raw_tokens"]
        else (
            raw_export["keyword_records"].get("RESO", [""])[0].split()[1:]
            if raw_export["keyword_records"].get("RESO")
            else []
        )
    )
    max_abs_reso_diff_str: str | None = None
    max_abs_reso_diff_str_available: bool | None = None
    max_abs_reso_diff_str_unavailable_reason: str | None = None
    max_abs_reso_diff: float | None = None
    max_abs_reso_diff_available: bool | None = None
    max_abs_reso_diff_unavailable_reason: str | None = None
    if len(in_reso_tokens) == 2 and len(out_reso_tokens) == 2:
        max_reso_diff_frac = Fraction(0)
        max_reso_diff_str = "0"
        reso_str_unavail_reasons: list[str] = []
        reso_float_unavail_reasons: list[str] = []
        for i in range(2):
            try:
                in_r_dec = Decimal(str(in_reso_tokens[i]))
                out_r_dec = Decimal(str(out_reso_tokens[i]))
            except (InvalidOperation, ValueError) as exc:
                reso_str_unavail_reasons.append(f"RESO[{i}]: {exc}")
                reso_float_unavail_reasons.append(f"RESO[{i}]: {exc}")
                continue
            r_frac, r_str, r_float, r_reason = (
                _compute_optional_exact_decimal_abs_diff(
                    in_r_dec, out_r_dec, label=f"RESO[{i}]"
                )
            )
            if r_frac is None or r_str is None:
                reso_str_unavail_reasons.append(f"RESO[{i}]: {r_reason}")
                reso_float_unavail_reasons.append(f"RESO[{i}]: {r_reason}")
            else:
                if r_frac > max_reso_diff_frac:
                    max_reso_diff_frac = r_frac
                    max_reso_diff_str = r_str
                if r_float is None or r_reason is not None:
                    reso_float_unavail_reasons.append(f"RESO[{i}]: {r_reason}")
        if reso_str_unavail_reasons:
            max_abs_reso_diff_str = None
            max_abs_reso_diff_str_available = False
            max_abs_reso_diff_str_unavailable_reason = "; ".join(
                reso_str_unavail_reasons
            )
        else:
            max_abs_reso_diff_str = max_reso_diff_str
            max_abs_reso_diff_str_available = True
            max_abs_reso_diff_str_unavailable_reason = None
        if reso_float_unavail_reasons:
            max_abs_reso_diff = None
            max_abs_reso_diff_available = False
            max_abs_reso_diff_unavailable_reason = "; ".join(
                reso_float_unavail_reasons
            )
        else:
            proj_reso_float, proj_reso_reason = (
                _project_exact_decimal_to_finite_float(
                    max_reso_diff_str, label="RESO.max_abs_reso_diff"
                )
            )
            if proj_reso_float is not None and proj_reso_reason is None:
                max_abs_reso_diff = proj_reso_float
                max_abs_reso_diff_available = True
                max_abs_reso_diff_unavailable_reason = None
            else:
                max_abs_reso_diff = None
                max_abs_reso_diff_available = False
                max_abs_reso_diff_unavailable_reason = proj_reso_reason

    crystallographic_context_audit: dict[str, Any] = {
        "hklin_verified_post_run": bool(hklin_check["verified"]),
        "hklin_ancestor_chain_verified": bool(hklin_check["ancestor_chain_verified"]),
        "hklin_baseline_sha256": hklin_check["baseline_sha256"],
        "hklin_baseline_size_bytes": hklin_check["baseline_size_bytes"],
        "hklin_post_run_sha256": hklin_check["post_run_sha256"],
        "hklin_post_run_size_bytes": hklin_check["post_run_size_bytes"],
        "hklin_verification_error": hklin_check["error"],
        "input_context": input_context,
        "input_context_error": input_context_error,
        "input_raw_header_context": input_raw_header_context,
        "input_header_byte_offset": in_header_byte_offset,
        "input_headers_error": input_headers_error,
        "output_context": output_context,
        "output_context_error": output_context_error,
        "output_raw_header_context": output_raw_header_context,
        "output_layout_error": output_layout_error,
        "exact_context_dictionary_equality": exact_context_dict_equality,
        "exact_context_equality_note": (
            "Original HKLIN/HKLOUT header tokens (input_raw_header_context / "
            "output_raw_header_context) and normalized exact-decimal crystallographic "
            "contexts (input_context / output_context) are preserved separately and "
            "evaluated via the explicit mtzdata.h:82-90 float cell[6] and "
            "cmtzlib.c:451-453, 526-537, 1240-1249, 2671-2697, 2838-2856 %.4f representation policy."
        ),
        "symmetry_exact_match": symmetry_exact_match,
        "exact_raw_cell_token_tuple_match": bool(
            cell_representation_policy.get("primary_cell_exact_token_tuple_match")
        ),
        "exact_cell_tuple_match": exact_cell_tuple_match,
        "max_abs_cell_parameter_diff_str": max_abs_cell_diff_str,
        "max_abs_cell_parameter_diff_str_available": (
            max_abs_cell_diff_str_available
        ),
        "max_abs_cell_parameter_diff_str_unavailable_reason": (
            max_abs_cell_diff_str_unavailable_reason
        ),
        "max_abs_cell_parameter_diff": max_abs_cell_diff,
        "max_abs_cell_parameter_diff_available": max_abs_cell_diff_available,
        "max_abs_cell_parameter_diff_unavailable_reason": (
            max_abs_cell_diff_unavailable_reason
        ),
        "cell_representation_valid": cell_representation_valid,
        "cell_representation_policy": cell_representation_policy,
        "output_dcell_matches_output_cell": output_dcell_matches_output_cell,
        "input_reso_tokens": in_reso_tokens,
        "output_reso_tokens": out_reso_tokens,
        "max_abs_reso_diff_str": max_abs_reso_diff_str,
        "max_abs_reso_diff_str_available": max_abs_reso_diff_str_available,
        "max_abs_reso_diff_str_unavailable_reason": (
            max_abs_reso_diff_str_unavailable_reason
        ),
        "max_abs_reso_diff": max_abs_reso_diff,
        "max_abs_reso_diff_available": max_abs_reso_diff_available,
        "max_abs_reso_diff_unavailable_reason": (
            max_abs_reso_diff_unavailable_reason
        ),
    }

    # Validate and index the actual onesar_rerun.build_input_hkl_ledger schema.
    ledger_index = _validate_and_index_input_hkl_ledger(input_ledger)
    if not ledger_index["valid"]:
        errors.extend(ledger_index["errors"])
    work_flag_value: int = ledger_index["work_flag_value"]
    free_flag_value: int = ledger_index["free_flag_value"]
    input_rows_list: list[dict[str, Any]] = ledger_index["raw_rows"]
    input_by_hkl: dict[tuple[int, int, int], dict[str, Any]] = ledger_index[
        "input_by_hkl"
    ]
    input_hkl_order: list[tuple[int, int, int]] = ledger_index["input_hkl_order"]
    input_observed_domain_keys: set[tuple[int, int, int]] = ledger_index[
        "input_observed_domain_keys"
    ]
    input_positive_amplitude_keys: set[tuple[int, int, int]] = ledger_index[
        "input_positive_amplitude_keys"
    ]
    input_zero_or_negative_f_keys: set[tuple[int, int, int]] = ledger_index[
        "input_zero_or_negative_f_keys"
    ]
    input_padding_keys: set[tuple[int, int, int]] = ledger_index[
        "input_padding_keys"
    ]
    input_work_observed_count: int = ledger_index["input_work_observed_count"]
    input_free_observed_count: int = ledger_index["input_free_observed_count"]
    input_work_positive_count: int = ledger_index["input_work_positive_count"]
    input_free_positive_count: int = ledger_index["input_free_positive_count"]

    # Verify required output columns (H, K, L, and declared HKLOUT observation labels) and check FC_ALL_LS.
    out_columns_meta = raw_export["header_parse"]["columns"]
    out_col_by_label: dict[str, list[dict[str, Any]]] = {}
    for col_meta in out_columns_meta:
        out_col_by_label.setdefault(col_meta["label"], []).append(col_meta)

    duplicate_column_labels = sorted(
        label for label, items in out_col_by_label.items() if len(items) > 1
    )
    if duplicate_column_labels:
        errors.append(
            f"HKLOUT contains duplicate column label(s): {duplicate_column_labels}"
        )

    if len(out_columns_meta) < 3 or [
        c["label"] for c in out_columns_meta[:3]
    ] != ["H", "K", "L"] or any(c["type"] != "H" for c in out_columns_meta[:3]):
        errors.append(
            "HKLOUT first three columns must be ('H', 'K', 'L') with MTZ column type 'H'"
        )

    fp_label = HKLOUT_OBSERVATION_ROLE_TO_LABEL["FP"]
    sigfp_label = HKLOUT_OBSERVATION_ROLE_TO_LABEL["SIGFP"]
    free_label = HKLOUT_OBSERVATION_ROLE_TO_LABEL["FREE"]
    expected_obs_types = {
        fp_label: "F",
        sigfp_label: "Q",
        free_label: "I",
    }
    obs_dataset_ids: set[str | None] = set()
    for req_label, req_type in expected_obs_types.items():
        matches = out_col_by_label.get(req_label, [])
        if len(matches) != 1:
            errors.append(
                f"HKLOUT missing unique required column {req_label!r} (found {len(matches)})"
            )
        else:
            col_entry = matches[0]
            if col_entry["type"] != req_type:
                errors.append(
                    f"HKLOUT column {req_label!r} has type {col_entry['type']!r}, expected {req_type!r}"
                )
            obs_dataset_ids.add(col_entry["dataset_id"])
    if len(obs_dataset_ids) > 1:
        errors.append(
            f"HKLOUT observation columns {HKLOUT_OBSERVATION_LABELS!r} span multiple dataset IDs: {sorted(str(x) for x in obs_dataset_ids)}"
        )

    fc_all_ls_meta = (
        out_col_by_label["FC_ALL_LS"][0]
        if len(out_col_by_label.get("FC_ALL_LS", [])) == 1
        else None
    )
    phic_all_ls_meta = (
        out_col_by_label["PHIC_ALL_LS"][0]
        if len(out_col_by_label.get("PHIC_ALL_LS", [])) == 1
        else None
    )
    if fc_all_ls_meta is not None and fc_all_ls_meta["type"] != "F":
        errors.append(
            f"HKLOUT preselected column 'FC_ALL_LS' has type {fc_all_ls_meta['type']!r}, expected 'F'"
        )

    output_nonintegral_hkl_rows: list[dict[str, Any]] = []
    output_duplicate_hkl_keys: list[list[int]] = []
    output_by_hkl: dict[tuple[int, int, int], dict[str, Any]] = {}
    output_hkl_order: list[tuple[int, int, int]] = []

    for row in raw_export["rows"]:
        if not row["is_integral_hkl"] or row["hkl"] is None:
            output_nonintegral_hkl_rows.append(
                {
                    "row_index": row["row_index"],
                    "hkl_floats": row["hkl_floats"],
                }
            )
            continue
        key = (int(row["hkl"][0]), int(row["hkl"][1]), int(row["hkl"][2]))
        output_hkl_order.append(key)
        if key in output_by_hkl:
            output_duplicate_hkl_keys.append(list(key))
        else:
            output_by_hkl[key] = row

    if output_nonintegral_hkl_rows:
        errors.append(
            f"HKLOUT contains {len(output_nonintegral_hkl_rows)} non-integral HKL row(s)"
        )
    if output_duplicate_hkl_keys:
        errors.append(
            f"HKLOUT contains {len(output_duplicate_hkl_keys)} duplicate HKL key(s)"
        )

    output_keys_set = set(output_by_hkl.keys())
    input_keys_set = set(input_by_hkl.keys())

    missing_observed_domain_hkl_keys = [
        list(k) for k in sorted(input_observed_domain_keys - output_keys_set)
    ]
    missing_eligible_hkl_keys = [
        list(k) for k in sorted(input_positive_amplitude_keys - output_keys_set)
    ]
    missing_ineligible_padding_hkl_keys = [
        list(k) for k in sorted(input_padding_keys - output_keys_set)
    ]
    unexpected_extra_output_hkl_keys = [
        list(k) for k in sorted(output_keys_set - input_keys_set)
    ]
    row_order_preserved = (
        len(output_nonintegral_hkl_rows) == 0
        and len(output_duplicate_hkl_keys) == 0
        and output_hkl_order == input_hkl_order
    )

    if missing_observed_domain_hkl_keys:
        errors.append(
            f"HKLOUT is missing {len(missing_observed_domain_hkl_keys)} observed-domain HKL key(s)"
        )
    if missing_ineligible_padding_hkl_keys:
        errors.append(
            f"HKLOUT is missing {len(missing_ineligible_padding_hkl_keys)} padding HKL key(s)"
        )
    if unexpected_extra_output_hkl_keys:
        errors.append(
            f"HKLOUT contains {len(unexpected_extra_output_hkl_keys)} unexpected extra HKL key(s)"
        )

    dropped_or_invalidated_eligible_observations: list[dict[str, Any]] = []
    missing_or_invalid_usable_flags: list[dict[str, Any]] = []
    usable_flag_flips: list[dict[str, Any]] = []
    unexpected_new_finite_observations: list[dict[str, Any]] = []
    padding_nan_preserved_keys: list[list[int]] = []
    padding_nan_to_free_zero_keys: list[list[int]] = []
    padding_nan_to_unexpected_free_values: list[dict[str, Any]] = []

    usable_fp_word_unchanged_count = 0
    usable_fp_rescaled_count = 0
    usable_sigfp_word_unchanged_count = 0
    usable_sigfp_rescaled_count = 0
    usable_free_word_unchanged_count = 0
    usable_free_word_changed_count = 0
    fp_scale_ratios: list[float] = []
    sigfp_scale_ratios: list[float] = []

    out_observed_domain_count = 0
    out_positive_fp_sigfp_count = 0
    out_zero_or_negative_fp_count = 0
    out_work_positive_count = 0
    out_free_positive_count = 0
    out_nan_fp_sigfp_count = 0

    fc_all_ls_finite_total_count = 0
    fc_all_ls_finite_on_eligible_count = 0
    fc_all_ls_finite_on_padding_count = 0
    fwt_finite_total_count = 0

    can_inspect_obs_cols = all(
        len(out_col_by_label.get(lbl, [])) == 1 for lbl in HKLOUT_OBSERVATION_LABELS
    )
    has_fc_all_ls = fc_all_ls_meta is not None
    has_fwt = len(out_col_by_label.get("FWT", [])) == 1

    if can_inspect_obs_cols:
        for key in input_hkl_order:
            out_row = output_by_hkl.get(key)
            if out_row is None:
                continue
            in_row = input_by_hkl[key]
            c_vals = out_row["column_values"]
            c_hex = out_row["column_words_hex"]
            c_cls = out_row["column_value_classes"]

            out_fp = c_vals.get(fp_label)
            out_sigfp = c_vals.get(sigfp_label)
            out_free = c_vals.get(free_label)
            out_fp_cls = c_cls.get(fp_label)
            out_sigfp_cls = c_cls.get(sigfp_label)
            out_free_cls = c_cls.get(free_label)

            if has_fc_all_ls and c_vals.get("FC_ALL_LS") is not None:
                fc_all_ls_finite_total_count += 1
                if key in input_observed_domain_keys:
                    fc_all_ls_finite_on_eligible_count += 1
                else:
                    fc_all_ls_finite_on_padding_count += 1
            if has_fwt and c_vals.get("FWT") is not None:
                fwt_finite_total_count += 1

            if out_fp is not None and out_sigfp is not None and out_sigfp > 0.0:
                out_observed_domain_count += 1
                if out_fp > 0.0:
                    out_positive_fp_sigfp_count += 1
                    free_int_check = (
                        onesar_rerun._integral_value(out_free)
                        if out_free is not None
                        else None
                    )
                    if free_int_check == free_flag_value:
                        out_free_positive_count += 1
                    elif free_int_check == work_flag_value:
                        out_work_positive_count += 1
                else:
                    out_zero_or_negative_fp_count += 1
            elif out_fp_cls == "nan" and out_sigfp_cls == "nan":
                out_nan_fp_sigfp_count += 1

            if key in input_observed_domain_keys:
                in_f = float(in_row["f_obs"])
                in_sigf = float(in_row["sigf_obs"])
                in_flag = int(in_row["r_free_flag"])
                fp_valid = (
                    out_fp is not None
                    and math.isfinite(out_fp)
                    and (out_fp > 0.0 if in_f > 0.0 else True)
                )
                sigfp_valid = (
                    out_sigfp is not None
                    and math.isfinite(out_sigfp)
                    and out_sigfp > 0.0
                )
                if not (fp_valid and sigfp_valid):
                    dropped_or_invalidated_eligible_observations.append(
                        {
                            "hkl": list(key),
                            "input_f_obs": in_f,
                            "input_sigf_obs": in_sigf,
                            "output_fp": out_fp,
                            "output_fp_word_hex": c_hex.get(fp_label),
                            "output_fp_class": out_fp_cls,
                            "output_sigfp": out_sigfp,
                            "output_sigfp_word_hex": c_hex.get(sigfp_label),
                            "output_sigfp_class": out_sigfp_cls,
                        }
                    )
                else:
                    if c_hex.get(fp_label) == in_row.get("f_obs_word_hex"):
                        usable_fp_word_unchanged_count += 1
                    else:
                        usable_fp_rescaled_count += 1
                    if c_hex.get(sigfp_label) == in_row.get("sigf_obs_word_hex"):
                        usable_sigfp_word_unchanged_count += 1
                    else:
                        usable_sigfp_rescaled_count += 1
                    if c_hex.get(free_label) == in_row.get("r_free_flag_word_hex"):
                        usable_free_word_unchanged_count += 1
                    else:
                        usable_free_word_changed_count += 1
                    if in_f != 0.0 and out_fp is not None:
                        fp_scale_ratios.append(float(out_fp) / in_f)
                    if in_sigf > 0.0 and out_sigfp is not None:
                        sigfp_scale_ratios.append(float(out_sigfp) / in_sigf)

                out_free_int = (
                    onesar_rerun._integral_value(out_free)
                    if out_free is not None
                    else None
                )
                if out_free_int is None:
                    missing_or_invalid_usable_flags.append(
                        {
                            "hkl": list(key),
                            "input_r_free_flag": in_flag,
                            "output_free": out_free,
                            "output_free_word_hex": c_hex.get(free_label),
                            "output_free_class": out_free_cls,
                        }
                    )
                elif out_free_int != in_flag:
                    usable_flag_flips.append(
                        {
                            "hkl": list(key),
                            "input_r_free_flag": in_flag,
                            "output_free_flag": out_free_int,
                            "output_free_word_hex": c_hex.get(free_label),
                        }
                    )
            else:
                # Input row was ineligible padding (NaN in HKLIN).
                if out_fp_cls != "nan" or out_sigfp_cls != "nan":
                    unexpected_new_finite_observations.append(
                        {
                            "hkl": list(key),
                            "output_fp": out_fp,
                            "output_fp_word_hex": c_hex.get(fp_label),
                            "output_fp_class": out_fp_cls,
                            "output_sigfp": out_sigfp,
                            "output_sigfp_word_hex": c_hex.get(sigfp_label),
                            "output_sigfp_class": out_sigfp_cls,
                        }
                    )
                if out_free_cls == "nan":
                    padding_nan_preserved_keys.append(list(key))
                else:
                    out_free_int = (
                        onesar_rerun._integral_value(out_free)
                        if out_free is not None
                        else None
                    )
                    if (
                        out_free_int == 0
                        and out_fp_cls == "nan"
                        and out_sigfp_cls == "nan"
                    ):
                        padding_nan_to_free_zero_keys.append(list(key))
                    else:
                        padding_nan_to_unexpected_free_values.append(
                            {
                                "hkl": list(key),
                                "output_free": out_free,
                                "output_free_word_hex": c_hex.get(free_label),
                                "output_free_class": out_free_cls,
                            }
                        )

    if dropped_or_invalidated_eligible_observations:
        errors.append(
            f"HKLOUT dropped or invalidated {len(dropped_or_invalidated_eligible_observations)} eligible observation(s)"
        )
    if missing_or_invalid_usable_flags:
        errors.append(
            f"HKLOUT has {len(missing_or_invalid_usable_flags)} missing or non-integral FREE flag(s) on eligible observations"
        )
    if usable_flag_flips:
        errors.append(
            f"HKLOUT flipped {len(usable_flag_flips)} usable FREE flag(s) on eligible observations"
        )
    if unexpected_new_finite_observations:
        errors.append(
            f"HKLOUT introduced {len(unexpected_new_finite_observations)} unexpected finite/Inf FP or SIGFP value(s) on input padding rows"
        )
    if padding_nan_to_unexpected_free_values:
        errors.append(
            f"HKLOUT wrote {len(padding_nan_to_unexpected_free_values)} unexpected non-zero/non-NaN FREE value(s) on input padding rows"
        )

    fp_scaling_summary: dict[str, Any] = {
        "usable_fp_word_unchanged_count": usable_fp_word_unchanged_count,
        "usable_fp_rescaled_count": usable_fp_rescaled_count,
        "usable_sigfp_word_unchanged_count": usable_sigfp_word_unchanged_count,
        "usable_sigfp_rescaled_count": usable_sigfp_rescaled_count,
        "usable_free_word_unchanged_count": usable_free_word_unchanged_count,
        "usable_free_word_changed_count": usable_free_word_changed_count,
        "fp_ratio_min": min(fp_scale_ratios) if fp_scale_ratios else None,
        "fp_ratio_max": max(fp_scale_ratios) if fp_scale_ratios else None,
        "fp_ratio_mean": (
            sum(fp_scale_ratios) / len(fp_scale_ratios) if fp_scale_ratios else None
        ),
        "sigfp_ratio_min": min(sigfp_scale_ratios) if sigfp_scale_ratios else None,
        "sigfp_ratio_max": max(sigfp_scale_ratios) if sigfp_scale_ratios else None,
        "sigfp_ratio_mean": (
            sum(sigfp_scale_ratios) / len(sigfp_scale_ratios)
            if sigfp_scale_ratios
            else None
        ),
    }

    # Separate population accounting: input_mtz vs read_eligible vs log_reported vs output_mtz.
    input_mtz_population: dict[str, Any] = {
        "free_flag_value": free_flag_value,
        "work_flag_value": work_flag_value,
        "total_rows": len(input_rows_list),
        "observed_domain_rows": len(input_observed_domain_keys),
        "positive_amplitude_rows": len(input_positive_amplitude_keys),
        "zero_or_negative_f_rows": len(input_zero_or_negative_f_keys),
        "work_observed_rows": input_work_observed_count,
        "free_observed_rows": input_free_observed_count,
        "work_positive_rows": input_work_positive_count,
        "free_positive_rows": input_free_positive_count,
        "ineligible_all_nan_padding_rows": len(input_padding_keys),
    }
    read_eligible_population: dict[str, Any] = {
        "free_flag_value": free_flag_value,
        "work_flag_value": work_flag_value,
        "observed_domain_total": len(input_observed_domain_keys),
        "positive_amplitude_total": len(input_positive_amplitude_keys),
        "zero_or_negative_f_total": len(input_zero_or_negative_f_keys),
        "work_read_eligible": input_work_positive_count,
        "free_read_eligible": input_free_positive_count,
    }

    log_reported_population: dict[str, Any] | None = None
    if parsed_log is not None:
        reconciled_final = parsed_log.get("reconciled_final_cycle", {})
        final_res_bins = parsed_log.get("final_resolution_bins", {})
        detailed_cycles = parsed_log.get("detailed_cycles", [])
        detail_used_reflections = (
            detailed_cycles[-1].get("number_of_used_reflections")
            if detailed_cycles and isinstance(detailed_cycles[-1], Mapping)
            else None
        )
        log_used = int(
            reconciled_final.get(
                "nr_used_sum", final_res_bins.get("nr_used_sum", 0)
            )
        )
        log_free = int(
            reconciled_final.get(
                "nr_free_sum", final_res_bins.get("nr_free_sum", 0)
            )
        )
        log_total = int(
            reconciled_final.get(
                "combined_reported_count",
                final_res_bins.get("combined_reported_count", log_used + log_free),
            )
        )
        bin_work_sum: int | None = None
        bin_free_sum: int | None = None
        if isinstance(final_res_bins.get("bins"), list):
            bins_list = final_res_bins["bins"]
            bin_work_sum = sum(int(b.get("nr_used", 0)) for b in bins_list)
            bin_free_sum = sum(int(b.get("nr_free", 0)) for b in bins_list)
        log_reported_population = {
            "detail_number_of_used_reflections": detail_used_reflections,
            "final_nr_used_sum": log_used,
            "final_nr_free_sum": log_free,
            "final_combined_reported_count": log_total,
            "final_bin_sum_reflections_work": bin_work_sum,
            "final_bin_sum_reflections_free": bin_free_sum,
            "final_bin_sum_total_active": (
                (bin_work_sum + bin_free_sum)
                if bin_work_sum is not None and bin_free_sum is not None
                else None
            ),
            "deficit_vs_read_eligible_positive": {
                "total_deficit": len(input_positive_amplitude_keys) - log_total,
                "work_deficit": input_work_positive_count - log_used,
                "free_deficit": input_free_positive_count - log_free,
            },
        }

    output_mtz_population: dict[str, Any] = {
        "free_flag_value": free_flag_value,
        "work_flag_value": work_flag_value,
        "total_rows": raw_export["row_count_exported"],
        "integral_unique_hkl_rows": len(output_by_hkl),
        "observed_domain_fp_sigfp_rows": out_observed_domain_count,
        "positive_fp_sigfp_rows": out_positive_fp_sigfp_count,
        "zero_or_negative_fp_rows": out_zero_or_negative_fp_count,
        "work_positive_fp_sigfp_rows": out_work_positive_count,
        "free_positive_fp_sigfp_rows": out_free_positive_count,
        "nan_fp_sigfp_rows": out_nan_fp_sigfp_count,
        "padding_nan_preserved_rows": len(padding_nan_preserved_keys),
        "padding_nan_to_free_zero_rows": len(padding_nan_to_free_zero_keys),
        "fc_all_ls_present": has_fc_all_ls,
        "fc_all_ls_finite_total_rows": fc_all_ls_finite_total_count,
        "fc_all_ls_finite_on_eligible_rows": fc_all_ls_finite_on_eligible_count,
        "fc_all_ls_finite_on_padding_rows": fc_all_ls_finite_on_padding_count,
        "fwt_present": has_fwt,
        "fwt_finite_total_rows": fwt_finite_total_count,
    }

    reconciled_final_cycle = (
        parsed_log.get("reconciled_final_cycle", {})
        if parsed_log is not None
        else {}
    )
    # Diagnostic evaluation of preselected FC_ALL_LS column (never searching FC or FC_ALL).
    fc_all_ls_audit: dict[str, Any] = {
        "preselected_column": PRESELECTED_NATIVE_LS_FC_COLUMN,
        "preselected_phase_column": "PHIC_ALL_LS",
        "forbidden_fallback_columns": list(FORBIDDEN_FALLBACK_FC_COLUMNS),
        "free_flag_value": free_flag_value,
        "work_flag_value": work_flag_value,
        "fc_all_ls_present": has_fc_all_ls,
        "phic_all_ls_present": phic_all_ls_meta is not None,
        "fc_all_ls_column_descriptor": fc_all_ls_meta,
        "phic_all_ls_column_descriptor": phic_all_ls_meta,
        "candidate_overall_work_count": 0,
        "candidate_overall_free_count": 0,
        "candidate_overall_r_work": None,
        "candidate_overall_r_free": None,
        "log_final_r_work": reconciled_final_cycle.get("r_work"),
        "log_final_r_free": reconciled_final_cycle.get("r_free"),
        "candidate_overall_r_work_abs_diff": None,
        "candidate_overall_r_free_abs_diff": None,
        "candidate_resolution_bins": [],
    }

    if has_fc_all_ls and can_inspect_obs_cols:
        work_num = 0.0
        work_den = 0.0
        work_num_frac = Fraction(0)
        work_den_frac = Fraction(0)
        work_cnt = 0
        free_num = 0.0
        free_den = 0.0
        free_num_frac = Fraction(0)
        free_den_frac = Fraction(0)
        free_cnt = 0
        eligible_obs_records: list[dict[str, Any]] = []
        active_cell_tokens = (
            output_context["cell_a_b_c_alpha_beta_gamma"]
            if output_context is not None
            else (
                input_context["cell_a_b_c_alpha_beta_gamma"]
                if input_context is not None
                else None
            )
        )
        active_cell = (
            [float(x) for x in active_cell_tokens]
            if active_cell_tokens is not None and len(active_cell_tokens) == 6
            else None
        )
        for key in input_hkl_order:
            if key not in input_positive_amplitude_keys:
                continue
            out_row = output_by_hkl.get(key)
            if out_row is None:
                continue
            c_vals = out_row["column_values"]
            fp_v = c_vals.get(fp_label)
            fc_v = c_vals.get("FC_ALL_LS")
            free_v = c_vals.get(free_label)
            if (
                fp_v is None
                or fc_v is None
                or free_v is None
                or not math.isfinite(fp_v)
                or not math.isfinite(fc_v)
                or fp_v <= 0.0
            ):
                continue
            free_int = onesar_rerun._integral_value(free_v)
            if free_int is None or free_int not in (work_flag_value, free_flag_value):
                continue
            fp_float = float(fp_v)
            fc_float = float(fc_v)
            diff = abs(fp_float - fc_float)
            fp_frac = Fraction(fp_float)
            fc_frac = Fraction(fc_float)
            diff_frac = abs(fp_frac - fc_frac)
            if free_int == free_flag_value:
                free_num += diff
                free_den += fp_float
                free_num_frac += diff_frac
                free_den_frac += fp_frac
                free_cnt += 1
            else:
                work_num += diff
                work_den += fp_float
                work_num_frac += diff_frac
                work_den_frac += fp_frac
                work_cnt += 1
            d_val = (
                _unit_cell_d_spacing(active_cell, key[0], key[1], key[2])
                if active_cell is not None
                else None
            )
            four_stl_sq = (
                (1.0 / (d_val * d_val)) if (d_val is not None and d_val > 0.0) else None
            )
            eligible_obs_records.append(
                {
                    "hkl": key,
                    "fp": fp_float,
                    "fc_all_ls": fc_float,
                    "free_int": free_int,
                    "d_spacing": d_val,
                    "four_sin_theta_over_lambda_sq": four_stl_sq,
                }
            )

        cand_rw = (work_num / work_den) if work_den > 0.0 else None
        cand_rf = (free_num / free_den) if free_den > 0.0 else None
        cand_rw_frac = (work_num_frac / work_den_frac) if work_den_frac > 0 else None
        cand_rf_frac = (free_num_frac / free_den_frac) if free_den_frac > 0 else None
        fc_all_ls_audit["candidate_overall_work_count"] = work_cnt
        fc_all_ls_audit["candidate_overall_free_count"] = free_cnt
        fc_all_ls_audit["candidate_overall_r_work"] = cand_rw
        fc_all_ls_audit["candidate_overall_r_free"] = cand_rf
        if parsed_log is not None:
            log_final_results = parsed_log.get("final_results", {})
            log_rw_raw = reconciled_final_cycle.get("r_work")
            log_rf_raw = reconciled_final_cycle.get("r_free")
            log_rw_tok = reconciled_final_cycle.get(
                "r_work_token", log_final_results.get("r_work_token")
            )
            log_rf_tok = reconciled_final_cycle.get(
                "r_free_token", log_final_results.get("r_free_token")
            )
            log_rw_dp = reconciled_final_cycle.get(
                "r_work_decimal_places",
                log_final_results.get("r_work_decimal_places", 4),
            )
            log_rf_dp = reconciled_final_cycle.get(
                "r_free_decimal_places",
                log_final_results.get("r_free_decimal_places", 4),
            )
            if cand_rw is not None and cand_rw_frac is not None and log_rw_raw is not None:
                fc_all_ls_audit["candidate_overall_r_work_abs_diff"] = abs(
                    cand_rw - float(log_rw_raw)
                )
                rw_dec = Decimal(
                    str(log_rw_tok) if log_rw_tok is not None else f"{float(log_rw_raw):.4f}"
                )
                rw_dp_int = int(log_rw_dp)
                rw_preflight_ok, rw_preflight_reason = (
                    _preflight_optional_decimal_diagnostic(
                        rw_dec,
                        requested_scale=rw_dp_int + 1,
                        label="log_rw_dec",
                    )
                )
                if rw_preflight_ok:
                    rw_frac, _ = _decimal_to_exact_fraction_and_scale(rw_dec)
                    rw_half_ulp_frac = Fraction(1, 2 * (10**rw_dp_int))
                    rw_low_frac = rw_frac - rw_half_ulp_frac
                    rw_high_frac = rw_frac + rw_half_ulp_frac
                    fc_all_ls_audit[
                        "candidate_overall_r_work_within_log_reporting_interval_interior"
                    ] = bool(rw_low_frac < cand_rw_frac < rw_high_frac)
                    fc_all_ls_audit[
                        "candidate_overall_r_work_interval_diagnostic_available"
                    ] = True
                    fc_all_ls_audit[
                        "candidate_overall_r_work_interval_diagnostic_unavailable_reason"
                    ] = None
                else:
                    fc_all_ls_audit[
                        "candidate_overall_r_work_within_log_reporting_interval_interior"
                    ] = None
                    fc_all_ls_audit[
                        "candidate_overall_r_work_interval_diagnostic_available"
                    ] = False
                    fc_all_ls_audit[
                        "candidate_overall_r_work_interval_diagnostic_unavailable_reason"
                    ] = rw_preflight_reason
            if cand_rf is not None and cand_rf_frac is not None and log_rf_raw is not None:
                fc_all_ls_audit["candidate_overall_r_free_abs_diff"] = abs(
                    cand_rf - float(log_rf_raw)
                )
                rf_dec = Decimal(
                    str(log_rf_tok) if log_rf_tok is not None else f"{float(log_rf_raw):.4f}"
                )
                rf_dp_int = int(log_rf_dp)
                rf_preflight_ok, rf_preflight_reason = (
                    _preflight_optional_decimal_diagnostic(
                        rf_dec,
                        requested_scale=rf_dp_int + 1,
                        label="log_rf_dec",
                    )
                )
                if rf_preflight_ok:
                    rf_frac, _ = _decimal_to_exact_fraction_and_scale(rf_dec)
                    rf_half_ulp_frac = Fraction(1, 2 * (10**rf_dp_int))
                    rf_low_frac = rf_frac - rf_half_ulp_frac
                    rf_high_frac = rf_frac + rf_half_ulp_frac
                    fc_all_ls_audit[
                        "candidate_overall_r_free_within_log_reporting_interval_interior"
                    ] = bool(rf_low_frac < cand_rf_frac < rf_high_frac)
                    fc_all_ls_audit[
                        "candidate_overall_r_free_interval_diagnostic_available"
                    ] = True
                    fc_all_ls_audit[
                        "candidate_overall_r_free_interval_diagnostic_unavailable_reason"
                    ] = None
                else:
                    fc_all_ls_audit[
                        "candidate_overall_r_free_within_log_reporting_interval_interior"
                    ] = None
                    fc_all_ls_audit[
                        "candidate_overall_r_free_interval_diagnostic_available"
                    ] = False
                    fc_all_ls_audit[
                        "candidate_overall_r_free_interval_diagnostic_unavailable_reason"
                    ] = rf_preflight_reason
            final_res_bins = parsed_log.get("final_resolution_bins", {})
            log_bins_list = final_res_bins.get("bins", [])
            if isinstance(log_bins_list, list) and len(log_bins_list) > 0:
                midpoints = [float(b["m_4ssq_ll"]) for b in log_bins_list]
                mid_edges = [
                    0.5 * (midpoints[i] + midpoints[i + 1])
                    for i in range(len(midpoints) - 1)
                ]
                cand_bins: list[dict[str, Any]] = []
                for bin_idx, log_bin in enumerate(log_bins_list):
                    b_w_num = 0.0
                    b_w_den = 0.0
                    b_w_cnt = 0
                    b_f_num = 0.0
                    b_f_den = 0.0
                    b_f_cnt = 0
                    boundary_ties = 0
                    low_edge = mid_edges[bin_idx - 1] if bin_idx > 0 else None
                    high_edge = (
                        mid_edges[bin_idx] if bin_idx < len(mid_edges) else None
                    )
                    for rec in eligible_obs_records:
                        s_val = rec["four_sin_theta_over_lambda_sq"]
                        if s_val is None:
                            continue
                        if (
                            low_edge is not None and abs(s_val - low_edge) <= 1e-5
                        ) or (
                            high_edge is not None and abs(s_val - high_edge) <= 1e-5
                        ):
                            boundary_ties += 1
                        in_low = True if low_edge is None else (s_val > low_edge)
                        in_high = (
                            True if high_edge is None else (s_val <= high_edge)
                        )
                        if not (in_low and in_high):
                            continue
                        if rec["free_int"] == free_flag_value:
                            b_f_num += abs(rec["fp"] - rec["fc_all_ls"])
                            b_f_den += rec["fp"]
                            b_f_cnt += 1
                        elif rec["free_int"] == work_flag_value:
                            b_w_num += abs(rec["fp"] - rec["fc_all_ls"])
                            b_w_den += rec["fp"]
                            b_w_cnt += 1
                    b_rw = (b_w_num / b_w_den) if b_w_den > 0.0 else None
                    b_rf = (b_f_num / b_f_den) if b_f_den > 0.0 else None
                    log_b_rw = log_bin.get("rf_used")
                    log_b_rf = log_bin.get("rf_free")
                    log_nr_used = log_bin.get("nr_used")
                    log_nr_free = log_bin.get("nr_free")
                    cand_bins.append(
                        {
                            "bin_index": bin_idx,
                            "bin_ordinal": log_bin.get("bin_ordinal", bin_idx + 1),
                            "m_4ssq_ll_token": log_bin.get("m_4ssq_ll_token"),
                            "m_4ssq_ll": log_bin.get("m_4ssq_ll"),
                            "candidate_midpoint_low_edge": low_edge,
                            "candidate_midpoint_high_edge": high_edge,
                            "log_nr_used": log_nr_used,
                            "candidate_nr_used": b_w_cnt,
                            "work_count_diff": (
                                b_w_cnt - int(log_nr_used)
                                if log_nr_used is not None
                                else None
                            ),
                            "log_nr_free": log_nr_free,
                            "candidate_nr_free": b_f_cnt,
                            "free_count_diff": (
                                b_f_cnt - int(log_nr_free)
                                if log_nr_free is not None
                                else None
                            ),
                            "boundary_near_tie_count": boundary_ties,
                            "log_rf_used": log_b_rw,
                            "candidate_r_work": b_rw,
                            "r_work_abs_diff": (
                                abs(b_rw - float(log_b_rw))
                                if (b_rw is not None and log_b_rw is not None)
                                else None
                            ),
                            "log_rf_free": log_b_rf,
                            "candidate_r_free": b_rf,
                            "r_free_abs_diff": (
                                abs(b_rf - float(log_b_rf))
                                if (b_rf is not None and log_b_rf is not None)
                                else None
                            ),
                        }
                    )
                fc_all_ls_audit["candidate_resolution_bins"] = cand_bins

    # Candidate output sets/counts in HKLOUT never prove effective REFMAC reflection
    # membership, native resolution-bin membership, or native residual denominators.
    eff_reasons: list[str] = [
        "Candidate HKLOUT columns/counts do not prove effective REFMAC internal reflection membership or active-mask exclusions"
    ]
    if log_reported_population is not None:
        deficits = log_reported_population["deficit_vs_read_eligible_positive"]
        if deficits["total_deficit"] != 0 or deficits["work_deficit"] != 0 or deficits["free_deficit"] != 0:
            eff_reasons.append(
                f"read-eligible positive observations ({len(input_positive_amplitude_keys)} total: "
                f"{input_work_positive_count} work, {input_free_positive_count} free) differ from "
                f"log-reported active reflections ({log_reported_population['final_combined_reported_count']} total: "
                f"{log_reported_population['final_nr_used_sum']} work, "
                f"{log_reported_population['final_nr_free_sum']} free)"
            )
    else:
        eff_reasons.append("parsed native REFMAC log is unavailable")
    if input_zero_or_negative_f_keys:
        eff_reasons.append(
            f"input observed domain contains {len(input_zero_or_negative_f_keys)} zero/negative F observation(s)"
        )
    effective_hkls_proven = False
    effective_hkls_unproven_reason = "; ".join(eff_reasons)

    bin_reasons: list[str] = [
        "HKLOUT does not emit native per-reflection resolution-bin assignments and candidate d-spacing bin counts do not prove REFMAC native bin membership or boundary conventions"
    ]
    if fc_all_ls_audit["candidate_resolution_bins"]:
        mismatched_bins = [
            b["bin_index"]
            for b in fc_all_ls_audit["candidate_resolution_bins"]
            if b["work_count_diff"] != 0 or b["free_count_diff"] != 0
        ]
        if mismatched_bins:
            bin_reasons.append(
                f"candidate 4*sin^2(theta)/lambda^2 bin counts differ from log table in bin(s) {mismatched_bins}"
            )
    native_bin_membership_proven = False
    native_bin_membership_unproven_reason = "; ".join(bin_reasons)

    res_reasons: list[str] = [
        "Native residual reconstruction requires proven effective HKL membership and proven native bin membership/denominators, which are unproven from candidate HKLOUT sets"
    ]
    if not has_fc_all_ls:
        res_reasons.append(
            f"preselected native LS column {PRESELECTED_NATIVE_LS_FC_COLUMN!r} is absent from HKLOUT"
        )
    else:
        if (
            fc_all_ls_audit.get(
                "candidate_overall_r_work_within_log_reporting_interval_interior"
            )
            is False
            or fc_all_ls_audit.get(
                "candidate_overall_r_free_within_log_reporting_interval_interior"
            )
            is False
        ):
            res_reasons.append(
                f"candidate unscaled FC_ALL_LS overall residuals (R_work={fc_all_ls_audit['candidate_overall_r_work']}, "
                f"R_free={fc_all_ls_audit['candidate_overall_r_free']}) differ from log final_results "
                f"(R_work={fc_all_ls_audit['log_final_r_work']}, R_free={fc_all_ls_audit['log_final_r_free']})"
            )
        fc_unavail_parts: list[str] = []
        if (
            fc_all_ls_audit.get(
                "candidate_overall_r_work_interval_diagnostic_available"
            )
            is False
        ):
            rw_unavail_reason = fc_all_ls_audit.get(
                "candidate_overall_r_work_interval_diagnostic_unavailable_reason"
            )
            fc_unavail_parts.append(f"R_work ({rw_unavail_reason})")
        if (
            fc_all_ls_audit.get(
                "candidate_overall_r_free_interval_diagnostic_available"
            )
            is False
        ):
            rf_unavail_reason = fc_all_ls_audit.get(
                "candidate_overall_r_free_interval_diagnostic_unavailable_reason"
            )
            fc_unavail_parts.append(f"R_free ({rf_unavail_reason})")
        if fc_unavail_parts:
            res_reasons.append(
                "candidate unscaled FC_ALL_LS overall residual log reporting interval comparison unavailable for "
                + ", ".join(fc_unavail_parts)
            )
    native_residual_reconstruction_proven = False
    native_residual_reconstruction_unproven_reason = "; ".join(res_reasons)

    audit_valid = len(errors) == 0
    hklout_audit: dict[str, Any] = {
        "schema_version": 1,
        "path": str(hklout_path),
        "raw_export_json": raw_export_artifact,
        "word_hex_convention": MTZ_WORD_HEX_CONVENTION,
        "status": "valid" if audit_valid else "rejected_invalid_or_inconsistent",
        "valid": audit_valid,
        "errors": errors,
        "crystallographic_context": crystallographic_context_audit,
        "output_layout_summary": output_layout_summary,
        "one_to_one_hkl_audit": {
            "input_total_rows": len(input_rows_list),
            "output_total_rows": raw_export["row_count_exported"],
            "row_order_preserved": row_order_preserved,
            "output_nonintegral_hkl_rows": output_nonintegral_hkl_rows,
            "output_duplicate_hkl_keys": output_duplicate_hkl_keys,
            "missing_observed_domain_hkl_keys": missing_observed_domain_hkl_keys,
            "missing_eligible_hkl_keys": missing_eligible_hkl_keys,
            "missing_ineligible_padding_hkl_keys": missing_ineligible_padding_hkl_keys,
            "unexpected_extra_output_hkl_keys": unexpected_extra_output_hkl_keys,
            "dropped_or_invalidated_eligible_observations": (
                dropped_or_invalidated_eligible_observations
            ),
            "missing_or_invalid_usable_flags": missing_or_invalid_usable_flags,
            "usable_flag_flips": usable_flag_flips,
            "unexpected_new_finite_observations": unexpected_new_finite_observations,
            "padding_nan_preserved_keys": padding_nan_preserved_keys,
            "padding_nan_to_free_zero_keys": padding_nan_to_free_zero_keys,
            "padding_nan_to_unexpected_free_values": (
                padding_nan_to_unexpected_free_values
            ),
            "fp_sigfp_scaling": fp_scaling_summary,
        },
        "populations": {
            "input_mtz_population": input_mtz_population,
            "read_eligible_population": read_eligible_population,
            "log_reported_population": log_reported_population,
            "output_mtz_population": output_mtz_population,
        },
        "fc_all_ls_audit": fc_all_ls_audit,
        "effective_hkls_proven": effective_hkls_proven,
        "effective_hkls_unproven_reason": effective_hkls_unproven_reason,
        "native_bin_membership_proven": native_bin_membership_proven,
        "native_bin_membership_unproven_reason": native_bin_membership_unproven_reason,
        "native_residual_reconstruction_proven": (
            native_residual_reconstruction_proven
        ),
        "native_residual_reconstruction_unproven_reason": (
            native_residual_reconstruction_unproven_reason
        ),
    }
    return hklout_audit, raw_export_artifact


def _is_hd_element_or_atom(element: str, atom_name: str) -> bool:
    """Return True if an atom record represents hydrogen or deuterium (matching pdb_atoms filter)."""
    elem = element.strip().upper()
    name = atom_name.strip().upper()
    return elem in {"H", "D"} or (not elem and name[:1] in {"H", "D"})


def _inspect_pdb_supplemented(
    pdb_path: Path,
    *,
    raw_text: str | None = None,
) -> dict[str, Any]:
    """Extract supplemented line-level PDB inventory (heavy atoms, raw field text, order, H/D, ANISOU)."""
    if raw_text is None:
        raw_text = pdb_path.read_text(encoding="utf-8", errors="strict")
    lines = raw_text.splitlines()
    record_counts: dict[str, int] = {}
    cryst1_lines: list[str] = []
    scale_lines: list[str] = []
    unexpected_structural_records: list[dict[str, Any]] = []
    hd_records: list[dict[str, Any]] = []
    anisou_records: list[dict[str, Any]] = []
    heavy_atom_records: list[dict[str, Any]] = []
    heavy_atom_by_key: dict[tuple[str, int, str, str, str, str], dict[str, Any]] = {}
    duplicate_heavy_keys: list[list[Any]] = []

    for line_no, raw_line in enumerate(lines, start=1):
        rec_prefix = raw_line[:6]
        rec_name = rec_prefix.strip() or "<BLANK>"
        record_counts[rec_name] = record_counts.get(rec_name, 0) + 1

        if raw_line.startswith("CRYST1"):
            cryst1_lines.append(raw_line)
        elif raw_line.startswith(("SCALE1", "SCALE2", "SCALE3")):
            scale_lines.append(raw_line)
        elif raw_line.startswith(("MODEL ", "ENDMDL")):
            unexpected_structural_records.append(
                {"line_number": line_no, "record": rec_name, "raw_line": raw_line}
            )
        elif raw_line.startswith("ANISOU"):
            atom_name = raw_line[12:16].strip()
            altloc = raw_line[16:17].strip()
            resname = raw_line[17:20].strip()
            chain_id = raw_line[21:22].strip()
            resseq_text = raw_line[22:26].strip()
            icode = raw_line[26:27].strip()
            element = raw_line[76:78].strip().upper()
            u_texts = [
                raw_line[28:35],
                raw_line[35:42],
                raw_line[42:49],
                raw_line[49:56],
                raw_line[56:63],
                raw_line[63:70],
            ]
            anisou_records.append(
                {
                    "line_number": line_no,
                    "serial_text": raw_line[6:11],
                    "chain_id": chain_id,
                    "resseq_text": resseq_text,
                    "icode": icode,
                    "resname": resname,
                    "atom_name": atom_name,
                    "altloc": altloc,
                    "element": element,
                    "u_ij_texts": u_texts,
                    "raw_line": raw_line,
                }
            )
        elif raw_line.startswith(("ATOM  ", "HETATM")):
            serial_text = raw_line[6:11]
            atom_name = raw_line[12:16].strip()
            altloc = raw_line[16:17].strip()
            resname = raw_line[17:20].strip()
            chain_id = raw_line[21:22].strip()
            resseq_text = raw_line[22:26]
            icode = raw_line[26:27].strip()
            x_text = raw_line[30:38]
            y_text = raw_line[38:46]
            z_text = raw_line[46:54]
            occ_text = raw_line[54:60]
            b_text = raw_line[60:66]
            segid = raw_line[72:76].strip()
            element_raw = raw_line[76:78].strip().upper()
            charge = raw_line[78:80].strip()

            if _is_hd_element_or_atom(element_raw, atom_name):
                hd_records.append(
                    {
                        "line_number": line_no,
                        "record_type": rec_prefix.strip(),
                        "serial_text": serial_text,
                        "chain_id": chain_id,
                        "resseq_text": resseq_text,
                        "icode": icode,
                        "resname": resname,
                        "atom_name": atom_name,
                        "altloc": altloc,
                        "element": element_raw or atom_name[:1].upper(),
                        "x_text": x_text,
                        "y_text": y_text,
                        "z_text": z_text,
                        "occupancy_text": occ_text,
                        "b_factor_text": b_text,
                        "raw_line": raw_line,
                    }
                )
            else:
                resseq = int(resseq_text)
                element = element_raw or "".join(
                    ch for ch in atom_name if ch.isalpha()
                )[:1].upper()
                key = (chain_id, resseq, icode, resname, atom_name, altloc)
                entry = {
                    "order_index": len(heavy_atom_records),
                    "line_number": line_no,
                    "key": list(key),
                    "record_type": rec_prefix.strip(),
                    "serial_text": serial_text,
                    "chain_id": chain_id,
                    "resseq": resseq,
                    "resseq_text": resseq_text,
                    "icode": icode,
                    "resname": resname,
                    "atom_name": atom_name,
                    "altloc": altloc,
                    "element": element,
                    "segid": segid,
                    "charge": charge,
                    "x": float(x_text),
                    "y": float(y_text),
                    "z": float(z_text),
                    "occupancy": float(occ_text),
                    "b_factor": float(b_text),
                    "x_text": x_text,
                    "y_text": y_text,
                    "z_text": z_text,
                    "occupancy_text": occ_text,
                    "b_factor_text": b_text,
                    "line_length": len(raw_line),
                }
                heavy_atom_records.append(entry)
                if key in heavy_atom_by_key:
                    duplicate_heavy_keys.append(list(key))
                else:
                    heavy_atom_by_key[key] = entry

    return {
        "line_count": len(lines),
        "record_counts": record_counts,
        "cryst1_lines": cryst1_lines,
        "scale_lines": scale_lines,
        "unexpected_structural_records": unexpected_structural_records,
        "hd_records": hd_records,
        "anisou_records": anisou_records,
        "heavy_atom_records": heavy_atom_records,
        "heavy_atom_by_key": heavy_atom_by_key,
        "duplicate_heavy_keys": duplicate_heavy_keys,
    }


def _adapt_pdb_atoms_records(
    raw_atoms: list[dict[str, Any]],
    *,
    label: str,
) -> dict[tuple[str, int, str, str, str, str], dict[str, Any]]:
    """Adapt ``audit_1sar_retained_evidence.pdb_atoms(text)`` output into a 6-tuple keyed dict.

    ``audit_1sar_retained_evidence.pdb_atoms(text)`` accepts exact PDB text and
    returns a ``list[dict[str, Any]]`` where each entry has a 5-tuple string key
    ``(chain, resseq_str, icode, resname, atom_name)`` after enforcing single-model,
    ``len(line) >= 78``, blank altloc (``line[16:17] == " "``), explicit non-H/D
    element, finite values, and unique 5-tuple keys. This adapter normalizes each
    record's key to the 6-tuple ``(chain_id, int(resseq_str), icode, resname,
    atom_name, "")`` used by :func:`_inspect_pdb_supplemented`.
    """
    if not isinstance(raw_atoms, list) or len(raw_atoms) == 0:
        raise ValueError(f"{label} pdb_atoms returned empty or non-list result")
    adapted: dict[tuple[str, int, str, str, str, str], dict[str, Any]] = {}
    for idx, item in enumerate(raw_atoms):
        if not isinstance(item, Mapping):
            raise ValueError(
                f"{label} pdb_atoms[{idx}] must be a Mapping, got {type(item).__name__}"
            )
        raw_key = item.get("key")
        if (
            not isinstance(raw_key, tuple)
            or len(raw_key) != 5
            or any(not isinstance(part, str) for part in raw_key)
        ):
            raise ValueError(
                f"{label} pdb_atoms[{idx}] key must be a 5-tuple of str, got {raw_key!r}"
            )
        chain_raw, resseq_str, icode_raw, resname_raw, atom_name_raw = raw_key
        resseq_int = int(resseq_str.strip())
        norm_key = (
            chain_raw.strip(),
            resseq_int,
            icode_raw.strip(),
            resname_raw.strip(),
            atom_name_raw.strip(),
            "",
        )
        if norm_key in adapted:
            raise ValueError(
                f"{label} pdb_atoms contains duplicate normalized key {list(norm_key)}"
            )
        xyz_raw = item.get("xyz")
        if not isinstance(xyz_raw, (list, tuple)) or len(xyz_raw) != 3:
            raise ValueError(
                f"{label} pdb_atoms[{idx}] xyz must be a 3-element sequence, got {xyz_raw!r}"
            )
        adapted[norm_key] = {
            "order_index": idx,
            "pdb_atoms_key": list(raw_key),
            "normalized_key": list(norm_key),
            "element": str(item["element"]),
            "xyz": [float(xyz_raw[0]), float(xyz_raw[1]), float(xyz_raw[2])],
            "occupancy": float(item["occupancy"]),
            "b_factor": float(item["b_factor"]),
        }
    return adapted


def _audit_refmac_xyzout(
    *,
    original_pdb_path: Path,
    xyzout_path: Path,
    xyzout_info: dict[str, Any],
    xyzin_baseline: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Audit REFMAC XYZOUT against XYZIN using pdb_atoms plus supplemented raw/H-D/ANISOU inventory."""
    errors: list[str] = []
    xyzin_check = _verify_and_read_admitted_input_file(
        original_pdb_path,
        xyzin_baseline,
        label="XYZIN",
    )
    baseline_sha256 = xyzin_check["baseline_sha256"]
    baseline_size = xyzin_check["baseline_size_bytes"]
    current_xyzin_sha256: str | None = xyzin_check["post_run_sha256"]
    current_xyzin_size: int | None = xyzin_check["post_run_size_bytes"]
    xyzin_readable_regular = bool(
        xyzin_check["verified"] and xyzin_check["bytes"] is not None
    )
    if not xyzin_readable_regular:
        errors.append(
            str(
                xyzin_check["error"]
                or f"XYZIN missing, symlinked, or unreadable post-run: {original_pdb_path}"
            )
        )

    xyzin_sha256 = (
        baseline_sha256 if baseline_sha256 is not None else current_xyzin_sha256
    )
    xyzin_size = (
        baseline_size if baseline_size is not None else current_xyzin_size
    )

    if (
        not xyzout_info["exists"]
        or xyzout_info["is_symlink"]
        or not xyzout_info["is_regular_file"]
        or not xyzout_info["within_refmac_dir"]
        or xyzout_info["error"] is not None
        or not isinstance(xyzout_info["size_bytes"], int)
        or xyzout_info["size_bytes"] <= 0
    ):
        errors.append(
            xyzout_info["error"]
            or "XYZOUT file is missing, empty, symlinked, or outside refmac_dir"
        )
        return {
            "schema_version": 1,
            "xyzin_path": str(original_pdb_path),
            "xyzin_sha256": xyzin_sha256,
            "xyzin_size_bytes": xyzin_size,
            "xyzin_post_run_sha256": current_xyzin_sha256,
            "xyzin_post_run_size_bytes": current_xyzin_size,
            "xyzin_verified_post_run": bool(xyzin_check["verified"]),
            "xyzin_ancestor_chain_verified": bool(
                xyzin_check["ancestor_chain_verified"]
            ),
            "xyzin_verification_error": xyzin_check["error"],
            "xyzout_path": str(xyzout_path),
            "xyzout_sha256": xyzout_info["sha256"],
            "xyzout_size_bytes": xyzout_info["size_bytes"],
            "status": "rejected_invalid_or_unreadable",
            "valid": False,
            "errors": errors,
            "model_preservation_proven": False,
            "model_preservation_unproven_reason": "; ".join(errors),
        }

    xyzin_text: str | None = None
    xyzin_pdb_atoms: dict[tuple[str, int, str, str, str, str], dict[str, Any]] | None = None
    xyzout_pdb_atoms: dict[tuple[str, int, str, str, str, str], dict[str, Any]] | None = None
    if xyzin_readable_regular and xyzin_check["bytes"] is not None:
        try:
            xyzin_text = xyzin_check["bytes"].decode("utf-8", errors="strict")
            raw_xyzin_atoms = audit_1sar_retained_evidence.pdb_atoms(xyzin_text)
            xyzin_pdb_atoms = _adapt_pdb_atoms_records(raw_xyzin_atoms, label="XYZIN")
        except Exception as exc:
            errors.append(f"XYZIN failed pdb_atoms helper: {type(exc).__name__}: {exc}")
    try:
        xyzout_text = xyzout_path.read_text(encoding="utf-8", errors="strict")
        raw_xyzout_atoms = audit_1sar_retained_evidence.pdb_atoms(xyzout_text)
        xyzout_pdb_atoms = _adapt_pdb_atoms_records(raw_xyzout_atoms, label="XYZOUT")
    except Exception as exc:
        errors.append(f"XYZOUT failed pdb_atoms helper: {type(exc).__name__}: {exc}")

    xyzin_supp: dict[str, Any] | None = None
    xyzout_supp: dict[str, Any] | None = None
    if xyzin_readable_regular and xyzin_text is not None:
        try:
            xyzin_supp = _inspect_pdb_supplemented(
                original_pdb_path,
                raw_text=xyzin_text,
            )
        except Exception as exc:
            errors.append(
                f"XYZIN failed supplemented PDB inspection: {type(exc).__name__}: {exc}"
            )
    try:
        xyzout_supp = _inspect_pdb_supplemented(
            xyzout_path,
            raw_text=xyzout_text if "xyzout_text" in locals() else None,
        )
    except Exception as exc:
        errors.append(
            f"XYZOUT failed supplemented PDB inspection: {type(exc).__name__}: {exc}"
        )

    if xyzin_supp is not None and xyzin_supp["duplicate_heavy_keys"]:
        errors.append(
            f"XYZIN contains duplicate supplemented heavy-atom keys: {xyzin_supp['duplicate_heavy_keys']}"
        )
    if xyzout_supp is not None and xyzout_supp["duplicate_heavy_keys"]:
        errors.append(
            f"XYZOUT contains duplicate supplemented heavy-atom keys: {xyzout_supp['duplicate_heavy_keys']}"
        )
    if (
        xyzin_pdb_atoms is not None
        and xyzin_supp is not None
        and set(xyzin_pdb_atoms.keys()) != set(xyzin_supp["heavy_atom_by_key"].keys())
    ):
        errors.append(
            "XYZIN adapted pdb_atoms key set disagrees with supplemented heavy-atom key set"
        )
    if (
        xyzout_pdb_atoms is not None
        and xyzout_supp is not None
        and set(xyzout_pdb_atoms.keys()) != set(xyzout_supp["heavy_atom_by_key"].keys())
    ):
        errors.append(
            "XYZOUT adapted pdb_atoms key set disagrees with supplemented heavy-atom key set"
        )

    if (
        errors
        or xyzin_pdb_atoms is None
        or xyzout_pdb_atoms is None
        or xyzin_supp is None
        or xyzout_supp is None
    ):
        return {
            "schema_version": 1,
            "xyzin_path": str(original_pdb_path),
            "xyzin_sha256": xyzin_sha256,
            "xyzin_size_bytes": xyzin_size,
            "xyzin_post_run_sha256": current_xyzin_sha256,
            "xyzin_post_run_size_bytes": current_xyzin_size,
            "xyzin_verified_post_run": bool(xyzin_check["verified"]),
            "xyzin_ancestor_chain_verified": bool(
                xyzin_check["ancestor_chain_verified"]
            ),
            "xyzin_verification_error": xyzin_check["error"],
            "xyzout_path": str(xyzout_path),
            "xyzout_sha256": xyzout_info["sha256"],
            "xyzout_size_bytes": xyzout_info["size_bytes"],
            "status": "rejected_invalid_or_unreadable",
            "valid": False,
            "errors": errors,
            "model_preservation_proven": False,
            "model_preservation_unproven_reason": "; ".join(errors),
        }

    in_keys_ordered = [tuple(r["key"]) for r in xyzin_supp["heavy_atom_records"]]
    out_keys_ordered = [tuple(r["key"]) for r in xyzout_supp["heavy_atom_records"]]
    in_keys_set = set(in_keys_ordered)
    out_keys_set = set(out_keys_ordered)

    added_heavy_atom_keys = [list(k) for k in sorted(out_keys_set - in_keys_set)]
    removed_heavy_atom_keys = [list(k) for k in sorted(in_keys_set - out_keys_set)]
    key_order_preserved = in_keys_ordered == out_keys_ordered
    reordered_heavy_atom_keys: list[dict[str, Any]] = []
    if not key_order_preserved and in_keys_set == out_keys_set:
        for idx, (in_k, out_k) in enumerate(zip(in_keys_ordered, out_keys_ordered)):
            if in_k != out_k:
                reordered_heavy_atom_keys.append(
                    {
                        "order_index": idx,
                        "xyzin_key": list(in_k),
                        "xyzout_key": list(out_k),
                    }
                )

    record_type_differences: list[dict[str, Any]] = []
    element_differences: list[dict[str, Any]] = []
    coordinate_differences: list[dict[str, Any]] = []
    occupancy_differences: list[dict[str, Any]] = []
    b_factor_differences: list[dict[str, Any]] = []
    serial_or_segment_differences: list[dict[str, Any]] = []

    max_abs_coord_diff = 0.0
    max_abs_occ_diff = 0.0
    b_deltas: list[float] = []

    for key in in_keys_ordered:
        if key not in xyzout_supp["heavy_atom_by_key"]:
            continue
        in_rec = xyzin_supp["heavy_atom_by_key"][key]
        out_rec = xyzout_supp["heavy_atom_by_key"][key]
        in_pa = xyzin_pdb_atoms[key]
        out_pa = xyzout_pdb_atoms[key]

        if in_rec["record_type"] != out_rec["record_type"]:
            record_type_differences.append(
                {
                    "key": list(key),
                    "xyzin_record_type": in_rec["record_type"],
                    "xyzout_record_type": out_rec["record_type"],
                }
            )
        if in_pa["element"] != out_pa["element"] or in_rec["element"] != out_rec["element"]:
            element_differences.append(
                {
                    "key": list(key),
                    "xyzin_element": in_rec["element"],
                    "xyzout_element": out_rec["element"],
                }
            )

        dx = abs(float(out_rec["x"]) - float(in_rec["x"]))
        dy = abs(float(out_rec["y"]) - float(in_rec["y"]))
        dz = abs(float(out_rec["z"]) - float(in_rec["z"]))
        atom_max_dxyz = max(dx, dy, dz)
        if atom_max_dxyz > max_abs_coord_diff:
            max_abs_coord_diff = atom_max_dxyz
        if (
            in_pa["xyz"] != out_pa["xyz"]
            or in_rec["x_text"] != out_rec["x_text"]
            or in_rec["y_text"] != out_rec["y_text"]
            or in_rec["z_text"] != out_rec["z_text"]
        ):
            coordinate_differences.append(
                {
                    "key": list(key),
                    "xyzin_xyz": list(in_pa["xyz"]),
                    "xyzout_xyz": list(out_pa["xyz"]),
                    "xyzin_xyz_text": [
                        in_rec["x_text"],
                        in_rec["y_text"],
                        in_rec["z_text"],
                    ],
                    "xyzout_xyz_text": [
                        out_rec["x_text"],
                        out_rec["y_text"],
                        out_rec["z_text"],
                    ],
                    "max_abs_diff": atom_max_dxyz,
                }
            )

        docc = abs(float(out_rec["occupancy"]) - float(in_rec["occupancy"]))
        if docc > max_abs_occ_diff:
            max_abs_occ_diff = docc
        if (
            in_pa["occupancy"] != out_pa["occupancy"]
            or in_rec["occupancy_text"] != out_rec["occupancy_text"]
        ):
            occupancy_differences.append(
                {
                    "key": list(key),
                    "xyzin_occupancy": in_pa["occupancy"],
                    "xyzout_occupancy": out_pa["occupancy"],
                    "xyzin_occupancy_text": in_rec["occupancy_text"],
                    "xyzout_occupancy_text": out_rec["occupancy_text"],
                    "abs_diff": docc,
                }
            )

        db = float(out_rec["b_factor"]) - float(in_rec["b_factor"])
        b_deltas.append(db)
        if (
            in_pa["b_factor"] != out_pa["b_factor"]
            or in_rec["b_factor_text"] != out_rec["b_factor_text"]
        ):
            b_factor_differences.append(
                {
                    "key": list(key),
                    "xyzin_b_factor": in_pa["b_factor"],
                    "xyzout_b_factor": out_pa["b_factor"],
                    "xyzin_b_factor_text": in_rec["b_factor_text"],
                    "xyzout_b_factor_text": out_rec["b_factor_text"],
                    "delta_b": round(db, 6),
                }
            )

        if (
            in_rec["serial_text"] != out_rec["serial_text"]
            or in_rec["segid"] != out_rec["segid"]
            or in_rec["charge"] != out_rec["charge"]
        ):
            serial_or_segment_differences.append(
                {
                    "key": list(key),
                    "xyzin_serial_text": in_rec["serial_text"],
                    "xyzout_serial_text": out_rec["serial_text"],
                    "xyzin_segid": in_rec["segid"],
                    "xyzout_segid": out_rec["segid"],
                    "xyzin_charge": in_rec["charge"],
                    "xyzout_charge": out_rec["charge"],
                }
            )

    unproven_reasons: list[str] = []
    if added_heavy_atom_keys:
        unproven_reasons.append(
            f"XYZOUT added {len(added_heavy_atom_keys)} heavy-atom key(s)"
        )
    if removed_heavy_atom_keys:
        unproven_reasons.append(
            f"XYZOUT removed {len(removed_heavy_atom_keys)} heavy-atom key(s)"
        )
    if not key_order_preserved:
        unproven_reasons.append(
            "XYZOUT heavy-atom key order differs from XYZIN"
        )
    if record_type_differences:
        unproven_reasons.append(
            f"XYZOUT changed record_type (ATOM/HETATM) on {len(record_type_differences)} heavy atom(s)"
        )
    if element_differences:
        unproven_reasons.append(
            f"XYZOUT changed element symbol on {len(element_differences)} heavy atom(s)"
        )
    if coordinate_differences:
        unproven_reasons.append(
            f"XYZOUT modified coordinates or coordinate text on {len(coordinate_differences)} heavy atom(s) "
            f"(max_abs_diff={max_abs_coord_diff:.6f})"
        )
    if occupancy_differences:
        unproven_reasons.append(
            f"XYZOUT modified occupancy or occupancy text on {len(occupancy_differences)} heavy atom(s) "
            f"(max_abs_diff={max_abs_occ_diff:.6f})"
        )
    if b_factor_differences:
        min_db = min(b_deltas) if b_deltas else 0.0
        max_db = max(b_deltas) if b_deltas else 0.0
        unproven_reasons.append(
            f"XYZOUT modified B-factor or B-factor text on {len(b_factor_differences)}/{len(in_keys_ordered)} "
            f"heavy atom(s) (delta_b range [{min_db:.4f}, {max_db:.4f}]; no blanket B-shift license)"
        )
    if xyzin_supp["hd_records"] or xyzout_supp["hd_records"]:
        unproven_reasons.append(
            f"H/D records present (XYZIN={len(xyzin_supp['hd_records'])}, XYZOUT={len(xyzout_supp['hd_records'])})"
        )
    if xyzin_supp["anisou_records"] or xyzout_supp["anisou_records"]:
        unproven_reasons.append(
            f"ANISOU records present (XYZIN={len(xyzin_supp['anisou_records'])}, "
            f"XYZOUT={len(xyzout_supp['anisou_records'])}); mixed/anisotropic ADP proof is unsupported"
        )
    if (
        xyzin_supp["unexpected_structural_records"]
        or xyzout_supp["unexpected_structural_records"]
    ):
        unproven_reasons.append(
            "Unexpected MODEL/ENDMDL structural records present"
        )

    model_preservation_proven = len(unproven_reasons) == 0
    model_preservation_unproven_reason = (
        None if model_preservation_proven else "; ".join(unproven_reasons)
    )

    return {
        "schema_version": 1,
        "xyzin_path": str(original_pdb_path),
        "xyzin_sha256": xyzin_sha256,
        "xyzin_size_bytes": xyzin_size,
        "xyzin_post_run_sha256": current_xyzin_sha256,
        "xyzin_post_run_size_bytes": current_xyzin_size,
        "xyzin_verified_post_run": bool(xyzin_check["verified"]),
        "xyzin_ancestor_chain_verified": bool(xyzin_check["ancestor_chain_verified"]),
        "xyzin_verification_error": xyzin_check["error"],
        "xyzout_path": str(xyzout_path),
        "xyzout_sha256": xyzout_info["sha256"],
        "xyzout_size_bytes": xyzout_info["size_bytes"],
        "byte_for_byte_identical": xyzin_sha256 == xyzout_info["sha256"],
        "status": (
            "valid_model_preserved"
            if model_preservation_proven
            else "valid_with_model_differences"
        ),
        "valid": True,
        "errors": [],
        "pdb_atoms_helper_limitations_note": (
            "audit_1sar_retained_evidence.pdb_atoms excludes H/D atoms, ignores ANISOU "
            "records, and discards record type (ATOM vs HETATM), atom ordering, and raw "
            "fixed-width numeric text; supplemented fields below retain all of these."
        ),
        "xyzin_inventory": {
            "line_count": xyzin_supp["line_count"],
            "record_counts": xyzin_supp["record_counts"],
            "cryst1_lines": xyzin_supp["cryst1_lines"],
            "scale_lines": xyzin_supp["scale_lines"],
            "heavy_atom_count": len(xyzin_supp["heavy_atom_records"]),
            "hd_atom_count": len(xyzin_supp["hd_records"]),
            "anisou_record_count": len(xyzin_supp["anisou_records"]),
            "unexpected_structural_records": xyzin_supp[
                "unexpected_structural_records"
            ],
            "hd_records": xyzin_supp["hd_records"],
            "anisou_records": xyzin_supp["anisou_records"],
        },
        "xyzout_inventory": {
            "line_count": xyzout_supp["line_count"],
            "record_counts": xyzout_supp["record_counts"],
            "cryst1_lines": xyzout_supp["cryst1_lines"],
            "scale_lines": xyzout_supp["scale_lines"],
            "heavy_atom_count": len(xyzout_supp["heavy_atom_records"]),
            "hd_atom_count": len(xyzout_supp["hd_records"]),
            "anisou_record_count": len(xyzout_supp["anisou_records"]),
            "unexpected_structural_records": xyzout_supp[
                "unexpected_structural_records"
            ],
            "hd_records": xyzout_supp["hd_records"],
            "anisou_records": xyzout_supp["anisou_records"],
        },
        "comparison": {
            "added_heavy_atom_keys": added_heavy_atom_keys,
            "removed_heavy_atom_keys": removed_heavy_atom_keys,
            "key_order_preserved": key_order_preserved,
            "reordered_heavy_atom_keys": reordered_heavy_atom_keys,
            "record_type_difference_count": len(record_type_differences),
            "record_type_differences": record_type_differences,
            "element_difference_count": len(element_differences),
            "element_differences": element_differences,
            "coordinate_difference_count": len(coordinate_differences),
            "max_abs_coordinate_diff": max_abs_coord_diff,
            "coordinate_differences": coordinate_differences,
            "occupancy_difference_count": len(occupancy_differences),
            "max_abs_occupancy_diff": max_abs_occ_diff,
            "occupancy_differences": occupancy_differences,
            "b_factor_difference_count": len(b_factor_differences),
            "b_factor_delta_min": min(b_deltas) if b_deltas else None,
            "b_factor_delta_max": max(b_deltas) if b_deltas else None,
            "b_factor_delta_mean": (
                sum(b_deltas) / len(b_deltas) if b_deltas else None
            ),
            "b_factor_differences": b_factor_differences,
            "serial_or_segment_difference_count": len(serial_or_segment_differences),
            "serial_or_segment_differences": serial_or_segment_differences,
        },
        "model_preservation_proven": model_preservation_proven,
        "model_preservation_unproven_reason": model_preservation_unproven_reason,
    }


def run_refmac_rfactor_operation(
    evidence_root: Path | str,
    subject_id: str = "R4",
    *,
    repo_root: Path | str = REPO_ROOT,
    archive_path: Path | str | None = None,
    timeout: float = 900.0,
    require_no_protstruct_overrides: bool = True,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> dict[str, Any]:
    """Stage ``subject_id`` inputs and execute the REFMAC5 ``NCYC 0`` collector and output audits.

    Stages inputs once through :func:`onesar_rerun.stage_subject_inputs`, hashes
    all immutable inputs (including ``input_admission.json``) and helper sources
    before launching REFMAC5, resolves the configured CCP4 setup script and
    ``refmac5`` binary inside the configured installation prefix, executes
    :func:`toolchain.run_refmac` (or ``runner``) with the exact preregistered
    ``NCYC 0`` keyword block, retains all raw outputs and execution metadata
    before parsing, parses the on-disk combined log via
    :func:`onesar_refmac_log.parse_refmac_log`, exports and audits ``XMLOUT``,
    ``HKLOUT``, and ``XYZOUT``, verifies post-run input immutability across all
    paths, and persists all audit, diagnostics, and manifest JSONs.
    """
    if not isinstance(require_no_protstruct_overrides, bool):
        raise ValueError("require_no_protstruct_overrides must be a boolean")
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(float(timeout))
        or float(timeout) <= 0.0
    ):
        raise ValueError(f"timeout must be a finite positive number, got {timeout!r}")
    timeout_seconds = float(timeout)

    if require_no_protstruct_overrides:
        onesar_rerun._verify_no_protstruct_overrides()

    staged = onesar_rerun.stage_subject_inputs(
        Path(evidence_root),
        subject_id=subject_id,
        repo_root=Path(repo_root),
        archive_path=Path(archive_path) if archive_path is not None else None,
    )
    fresh_root: Path = staged["evidence_root"]
    inputs_dir: Path = staged["inputs_dir"]
    original_pdb_path: Path = staged["original_pdb_path"]
    original_mtz_path: Path = staged["original_mtz_path"]
    projected_mtz_path: Path = staged["projected_mtz_path"]
    input_ledger_path: Path = staged["input_ledger_path"]
    admission_json_path: Path = staged["admission_json_path"]
    admission_record: dict[str, Any] = copy.deepcopy(staged["admission_record"])
    input_ledger: dict[str, Any] = copy.deepcopy(staged["input_ledger"])

    refmac_dir = fresh_root / "refmac"
    _ensure_no_symlink_components_under_root(refmac_dir, fresh_root)
    try:
        os.lstat(refmac_dir)
    except FileNotFoundError:
        pass
    else:
        raise FileExistsError(f"Refmac directory already exists: {refmac_dir}")
    refmac_dir.mkdir(parents=False, exist_ok=False)

    parent_retention_dir = fresh_root / "refmac_parent_retention"
    _ensure_no_symlink_components_under_root(parent_retention_dir, fresh_root)
    try:
        os.lstat(parent_retention_dir)
    except FileNotFoundError:
        pass
    else:
        raise FileExistsError(
            f"Parent retention directory already exists: {parent_retention_dir}"
        )
    parent_retention_dir.mkdir(parents=False, exist_ok=False)

    refmac_dir_baseline = _capture_directory_identity_baseline(
        refmac_dir, evidence_root=fresh_root
    )
    parent_retention_dir_baseline = _capture_directory_identity_baseline(
        parent_retention_dir, evidence_root=fresh_root
    )

    keywords_path = refmac_dir / "refmac_keywords.txt"
    pre_execution_checkpoint_json_path = (
        refmac_dir / "refmac_pre_execution_checkpoint.json"
    )
    post_execution_checkpoint_json_path = (
        refmac_dir / "refmac_post_execution_checkpoint.json"
    )
    log_path = refmac_dir / "refmac.log"
    xyzout_path = refmac_dir / "refmac_xyzout.pdb"
    hklout_path = refmac_dir / "refmac_hklout.mtz"
    xmlout_path = refmac_dir / "refmac_xmlout.xml"
    parsed_log_json_path = refmac_dir / "refmac_parsed_log.json"
    xmlout_audit_json_path = refmac_dir / "refmac_xmlout_audit.json"
    hklout_raw_export_json_path = refmac_dir / "refmac_hklout_raw_export.json"
    hklout_audit_json_path = refmac_dir / "refmac_hklout_audit.json"
    xyzout_audit_json_path = refmac_dir / "refmac_xyzout_audit.json"
    diagnostics_json_path = refmac_dir / "refmac_diagnostics.json"
    manifest_json_path = refmac_dir / "refmac_operation_manifest.json"

    staged_input_baseline = _build_staged_input_baseline(staged)
    helper_source_baseline = _build_helper_source_baseline()
    keywords_baseline = _write_new_regular_file_text(
        keywords_path, REFMAC_KEYWORDS, root=refmac_dir
    )
    keywords_baseline.update(
        _build_file_ancestor_chain_baseline(
            Path(keywords_baseline["path"]), evidence_root=fresh_root
        )
    )

    toolchain_record: dict[str, Any] | None = None
    ccp4_env: dict[str, str] | None = None
    resolved_refmac_path: Path | None = None
    preflight_error: dict[str, Any] | None = None
    preflight_exception: Exception | None = None

    try:
        toolchain_record, ccp4_env, resolved_refmac_path = (
            _resolve_ccp4_refmac_toolchain()
        )
    except Exception as exc:
        preflight_exception = exc
        preflight_error = {
            "failed_stage": "resolve_ccp4_refmac_toolchain",
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
        }

    worker_launched = False
    started_at_utc: str | None = None
    finished_at_utc: str | None = None
    elapsed_seconds: float | None = None
    returncode: int | None = None
    timed_out = False
    launch_or_timeout_failure: dict[str, Any] | None = None
    launch_or_timeout_exception: Exception | None = None
    expected_argv: list[str] | None = None
    completed_argv: list[str] | None = None

    active_runner = toolchain.run_refmac if runner is None else runner

    if preflight_error is None and resolved_refmac_path is not None and ccp4_env is not None:
        expected_argv = [
            str(resolved_refmac_path),
            "XYZIN",
            str(original_pdb_path),
            "HKLIN",
            str(projected_mtz_path),
            "XYZOUT",
            str(xyzout_path),
            "HKLOUT",
            str(hklout_path),
            "XMLOUT",
            str(xmlout_path),
        ]
        for out_candidate in (log_path, xyzout_path, hklout_path, xmlout_path):
            _ensure_no_symlink_components_under_root(out_candidate, refmac_dir)
            try:
                os.lstat(out_candidate)
            except FileNotFoundError:
                pass
            else:
                preflight_error = {
                    "failed_stage": "verify_fresh_output_paths",
                    "exception_type": "FileExistsError",
                    "exception_message": (
                        f"Output path already exists before REFMAC launch: {out_candidate}"
                    ),
                }
                break

    pre_execution_checkpoint_payload: dict[str, Any] = {
        "schema_version": 1,
        "checkpoint_stage": "pre_execution",
        "collector_stage": COLLECTOR_STAGE,
        "status": (
            "pre_execution_checkpointed"
            if preflight_error is None
            else "preflight_failed"
        ),
        "recorded_at_utc": _utc_timestamp_iso(),
        "subject_id": subject_id,
        "evidence_root": str(fresh_root),
        "inputs_dir": str(inputs_dir),
        "refmac_dir": str(refmac_dir),
        "parent_retention_dir": str(parent_retention_dir),
        "refmac_directory_baseline": copy.deepcopy(refmac_dir_baseline),
        "parent_retention_directory_baseline": copy.deepcopy(
            parent_retention_dir_baseline
        ),
        "subject": admission_record["subject"],
        "mtz": admission_record["mtz"],
        "staged_files": admission_record["staged_files"],
        "input_admission_json_path": str(admission_json_path),
        "input_admission_json_sha256": staged_input_baseline["input_admission_json"][
            "sha256"
        ],
        "input_hkl_ledger_json_path": str(input_ledger_path),
        "input_hkl_ledger_json_sha256": staged_input_baseline["input_hkl_ledger_json"][
            "sha256"
        ],
        "staged_inputs_baseline": copy.deepcopy(staged_input_baseline),
        "helper_sources": copy.deepcopy(helper_source_baseline),
        "helper_sources_baseline": copy.deepcopy(helper_source_baseline),
        "keywords_file_baseline": copy.deepcopy(keywords_baseline),
        "toolchain": toolchain_record,
        "preflight_error": preflight_error,
        "invocation": {
            "wrapper": "toolchain.run_refmac",
            "custom_runner_injected": runner is not None,
            "executable": (
                str(resolved_refmac_path)
                if resolved_refmac_path is not None
                else None
            ),
            "expected_argv": expected_argv,
            "cwd": str(refmac_dir),
            "stdin_keywords": REFMAC_KEYWORDS,
            "stdin_keywords_lines": list(REFMAC_KEYWORDS_LINES),
            "stdin_keywords_sha256": keywords_baseline["sha256"],
            "keywords_file_path": str(keywords_path),
            "xyzin_path": str(original_pdb_path),
            "hklin_path": str(projected_mtz_path),
            "xyzout_path": str(xyzout_path),
            "hklout_path": str(hklout_path),
            "xmlout_path": str(xmlout_path),
            "log_path": str(log_path),
            "ccp4_flag_passed_to_run_refmac": False,
            "explicit_env_passed": ccp4_env is not None,
            "timeout_seconds": timeout_seconds,
        },
    }
    pre_execution_checkpoint_initial_artifact = _persist_collector_json_with_fallback(
        pre_execution_checkpoint_payload,
        pre_execution_checkpoint_json_path,
        root=refmac_dir,
    )
    pre_execution_checkpoint_initial_artifact.update(
        _build_file_ancestor_chain_baseline(
            Path(pre_execution_checkpoint_initial_artifact["path"]),
            evidence_root=fresh_root,
        )
    )
    pre_execution_checkpoint_artifact: dict[str, Any] = dict(
        pre_execution_checkpoint_initial_artifact
    )

    if preflight_error is None and resolved_refmac_path is not None and ccp4_env is not None:
        worker_launched = True
        started_at_utc = _utc_timestamp_iso()
        t0 = time.monotonic()
        try:
            completed = active_runner(
                original_pdb_path,
                projected_mtz_path,
                xyzout_path,
                hklout_path,
                log_path,
                REFMAC_KEYWORDS,
                cwd=refmac_dir,
                timeout=timeout_seconds,
                xml_output=xmlout_path,
                executable=resolved_refmac_path,
                env=ccp4_env,
                ccp4=False,
            )
            if not isinstance(completed, subprocess.CompletedProcess):
                raise TypeError(
                    f"REFMAC runner must return subprocess.CompletedProcess, got {type(completed).__name__}"
                )
            if isinstance(completed.returncode, bool) or not isinstance(
                completed.returncode, int
            ):
                raise TypeError(
                    f"CompletedProcess.returncode must be an int, got {completed.returncode!r}"
                )
            returncode = completed.returncode
            if isinstance(completed.args, (list, tuple)):
                completed_argv = [str(item) for item in completed.args]
            elif completed.args is not None:
                completed_argv = [str(completed.args)]
        except subprocess.TimeoutExpired as exc:
            launch_or_timeout_exception = exc
            timed_out = True
            returncode = None
            launch_or_timeout_failure = {
                "failure_kind": "timeout",
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
                "timeout_seconds": timeout_seconds,
            }
        except Exception as exc:
            launch_or_timeout_exception = exc
            timed_out = False
            raw_rc = getattr(exc, "returncode", None)
            returncode = (
                raw_rc
                if isinstance(raw_rc, int) and not isinstance(raw_rc, bool)
                else None
            )
            launch_or_timeout_failure = {
                "failure_kind": "runner_exception",
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
            }
        finally:
            finished_at_utc = _utc_timestamp_iso()
            elapsed_seconds = round(time.monotonic() - t0, 6)

    caught_inspection_exceptions: list[Exception] = []
    caught_persistence_exceptions: list[Exception] = []
    child_dir_persistence_failures: list[dict[str, Any]] = []
    child_dir_persistence_causes: list[Exception | None] = []

    refmac_dir_initial_causes: list[Exception] = []
    refmac_dir_post_run = _verify_refmac_directory_post_run(
        refmac_dir,
        refmac_dir_baseline=refmac_dir_baseline,
        caught_exceptions=refmac_dir_initial_causes,
    )
    caught_inspection_exceptions.extend(refmac_dir_initial_causes)
    refmac_dir_initial_cause: Exception | None = (
        refmac_dir_initial_causes[0] if refmac_dir_initial_causes else None
    )

    parent_dir_initial_causes: list[Exception] = []
    parent_retention_dir_post_run = _verify_refmac_directory_post_run(
        parent_retention_dir,
        refmac_dir_baseline=parent_retention_dir_baseline,
        caught_exceptions=parent_dir_initial_causes,
    )
    caught_inspection_exceptions.extend(parent_dir_initial_causes)
    parent_retention_dir_cause_holder: list[Exception | None] = [
        parent_dir_initial_causes[0] if parent_dir_initial_causes else None
    ]
    verified_root_fallback_state: dict[str, Any] = {
        "used": False,
        "no_verified_anchor_available": False,
        "failed_intended_parent_retention_dir": None,
        "parent_retention_dir_failure_reason": None,
        "evidence_root_verified": None,
        "evidence_root_failure_reason": None,
        "actual_anchor_dir": None,
        "actual_anchor_kind": None,
        "actual_anchor_baseline": None,
        "unpersisted_reason": None,
    }

    # Always verify immutable inputs, helper sources, keywords, and pre-execution checkpoint immediately after child execution.
    immutability_mutation_causes: list[Exception | None] = []
    pre_checkpoint_causes: list[Exception | None] = []
    immutability_report = _verify_immutable_baselines_post_run(
        staged_input_baseline,
        helper_source_baseline,
        keywords_baseline,
        pre_execution_checkpoint_baseline=pre_execution_checkpoint_initial_artifact,
        caught_exceptions=caught_inspection_exceptions,
        mutation_causes_out=immutability_mutation_causes,
        pre_checkpoint_cause_out=pre_checkpoint_causes,
    )
    pre_checkpoint_cause: Exception | None = (
        pre_checkpoint_causes[0] if pre_checkpoint_causes else None
    )
    immutability_report["refmac_directory_baseline"] = copy.deepcopy(
        refmac_dir_baseline
    )
    immutability_report["refmac_directory_post_run"] = copy.deepcopy(
        refmac_dir_post_run
    )
    immutability_report["parent_retention_directory_baseline"] = copy.deepcopy(
        parent_retention_dir_baseline
    )
    immutability_report["parent_retention_directory_post_run"] = copy.deepcopy(
        parent_retention_dir_post_run
    )
    pre_checkpoint_post_run: dict[str, Any] = dict(
        immutability_report["pre_execution_checkpoint_post_run"]
    )
    pre_execution_checkpoint_verified = bool(
        immutability_report.get("pre_execution_checkpoint_verified", False)
    )

    # Retain raw output artifacts and their SHA-256 digests BEFORE any log parsing, audits, or parent recovery writes.
    raw_output_paths: dict[str, Path] = {
        "log": log_path,
        "xyzout": xyzout_path,
        "hklout": hklout_path,
        "xmlout": xmlout_path,
    }
    raw_outputs: dict[str, dict[str, Any]] = {}
    per_raw_output_causes: dict[str, Exception | None] = {}
    for key, path in raw_output_paths.items():
        key_causes: list[Exception] = []
        raw_outputs[key] = _inspect_output_artifact(
            path,
            root=refmac_dir,
            caught_exceptions=key_causes,
            expected_root_identity=refmac_dir_baseline,
        )
        caught_inspection_exceptions.extend(key_causes)
        per_raw_output_causes[key] = key_causes[0] if key_causes else None

    scandir_causes: list[Exception | None] = []
    additional_file_causes: dict[str, Exception | None] = {}
    dir_scan = _scan_refmac_directory_entries(
        refmac_dir,
        known_paths={
            **raw_output_paths,
            "keywords": Path(keywords_baseline["path"]),
            "pre_execution_checkpoint_json": Path(
                pre_execution_checkpoint_initial_artifact["path"]
            ),
        },
        caught_exceptions=caught_inspection_exceptions,
        expected_root_identity=refmac_dir_baseline,
        refmac_dir_status=refmac_dir_post_run,
        refmac_dir_initial_cause=refmac_dir_initial_cause,
        scandir_cause_out=scandir_causes,
        additional_file_causes_out=additional_file_causes,
    )

    pre_execution_checkpoint_recovery_artifact: dict[str, Any] | None = None
    if not pre_execution_checkpoint_verified:
        recovery_target_path = (
            refmac_dir
            / f"refmac_pre_execution_checkpoint.parent_recovery.{os.getpid()}.json"
        )
        pre_execution_checkpoint_recovery_artifact = (
            _persist_collector_json_with_fallback(
                pre_execution_checkpoint_payload,
                recovery_target_path,
                root=refmac_dir,
                parent_retention_dir=parent_retention_dir,
                parent_retention_dir_baseline=parent_retention_dir_baseline,
                parent_retention_dir_status=parent_retention_dir_post_run,
                verified_root_fallback_state=verified_root_fallback_state,
                allow_unpersisted_on_no_verified_anchor=True,
                refmac_dir_status=refmac_dir_post_run,
                child_dir_persistence_failures=child_dir_persistence_failures,
                caught_persistence_exceptions=caught_persistence_exceptions,
                child_dir_persistence_causes=child_dir_persistence_causes,
                parent_retention_dir_cause_sink=parent_retention_dir_cause_holder,
            )
        )
        pre_execution_checkpoint_artifact = {
            "path": pre_execution_checkpoint_recovery_artifact["path"],
            "sha256": pre_execution_checkpoint_recovery_artifact["sha256"],
            "size_bytes": pre_execution_checkpoint_recovery_artifact["size_bytes"],
            "verified_at_original_path": False,
            "recovered_for_damaged_checkpoint_path": str(
                pre_execution_checkpoint_initial_artifact["path"]
            ),
            "original_recorded_checkpoint": copy.deepcopy(
                pre_execution_checkpoint_initial_artifact
            ),
            "damaged_checkpoint_post_run": copy.deepcopy(pre_checkpoint_post_run),
        }
        for opt_key in (
            "fallback_for_unwritable_or_damaged_child_dir",
            "fallback_for_damaged_or_replaced_parent_retention_dir",
            "intended_child_dir_path",
            "intended_parent_retention_dir",
            "parent_retention_dir",
            "actual_retention_anchor_dir",
            "actual_retention_anchor_kind",
            "actual_retention_anchor_baseline",
            "child_dir_persistence_error",
            "parent_retention_dir_persistence_error",
            "evidence_root_persistence_error",
            "no_verified_anchor_available",
            "unpersisted_reason",
            "persisted",
            "fallback_for_preexisting_path",
        ):
            if opt_key in pre_execution_checkpoint_recovery_artifact:
                pre_execution_checkpoint_artifact[opt_key] = (
                    pre_execution_checkpoint_recovery_artifact[opt_key]
                )
        immutability_report["pre_execution_checkpoint_recovery_json"] = copy.deepcopy(
            pre_execution_checkpoint_recovery_artifact
        )
    else:
        pre_execution_checkpoint_artifact = {
            **pre_execution_checkpoint_initial_artifact,
            "verified_at_original_path": True,
        }
        immutability_report["pre_execution_checkpoint_recovery_json"] = None

    missing_or_invalid_outputs: list[dict[str, Any]] = []
    missing_or_invalid_output_causes: list[Exception | None] = []
    for reserved_label, reserved_path in (
        ("post_execution_checkpoint_json", post_execution_checkpoint_json_path),
        ("parsed_log_json", parsed_log_json_path),
        ("xmlout_audit_json", xmlout_audit_json_path),
        ("hklout_raw_export_json", hklout_raw_export_json_path),
        ("hklout_audit_json", hklout_audit_json_path),
        ("xyzout_audit_json", xyzout_audit_json_path),
        ("diagnostics_json", diagnostics_json_path),
        ("manifest_json", manifest_json_path),
    ):
        if reserved_path.name in dir_scan["additional_files"]:
            res_info = dir_scan["additional_files"][reserved_path.name]
            reserved_err = (
                f"Reserved collector JSON path was pre-created before parent write: {reserved_path}"
            )
            if res_info.get("error"):
                reserved_err = f"{reserved_err}; {res_info['error']}"
            reserved_item: dict[str, Any] = {
                "output_key": reserved_label,
                "path": str(reserved_path),
                "exists": res_info["exists"],
                "is_symlink": res_info["is_symlink"],
                "is_regular_file": res_info["is_regular_file"],
                "within_refmac_dir": res_info["within_refmac_dir"],
                "size_bytes": res_info["size_bytes"],
                "error": reserved_err,
            }
            if res_info.get("exception_type") is not None:
                reserved_item["exception_type"] = res_info["exception_type"]
                reserved_item["exception_message"] = res_info.get("exception_message")
                reserved_item["errno"] = res_info.get("errno")
            missing_or_invalid_outputs.append(reserved_item)
            missing_or_invalid_output_causes.append(
                additional_file_causes.get(reserved_path.name)
            )

    for key in REQUIRED_RAW_OUTPUT_KEYS:
        info = raw_outputs[key]
        if (
            not info["exists"]
            or info["is_symlink"]
            or not info["is_regular_file"]
            or not info["within_refmac_dir"]
            or info["error"] is not None
            or not isinstance(info["size_bytes"], int)
            or info["size_bytes"] <= 0
        ):
            raw_item: dict[str, Any] = {
                "output_key": key,
                "path": info["path"],
                "exists": info["exists"],
                "is_symlink": info["is_symlink"],
                "is_regular_file": info["is_regular_file"],
                "within_refmac_dir": info["within_refmac_dir"],
                "size_bytes": info["size_bytes"],
                "error": info["error"]
                or (
                    "empty_output_file"
                    if info["exists"] and info["size_bytes"] == 0
                    else "missing_output_file"
                ),
            }
            if info.get("exception_type") is not None:
                raw_item["exception_type"] = info["exception_type"]
                raw_item["exception_message"] = info.get("exception_message")
                raw_item["errno"] = info.get("errno")
            missing_or_invalid_outputs.append(raw_item)
            missing_or_invalid_output_causes.append(per_raw_output_causes.get(key))

    xml_info = raw_outputs["xmlout"]
    if (
        xml_info["is_symlink"]
        or not xml_info["within_refmac_dir"]
        or (
            xml_info["exists"]
            and (
                not xml_info["is_regular_file"]
                or xml_info["error"] is not None
                or not isinstance(xml_info["size_bytes"], int)
                or xml_info["size_bytes"] <= 0
            )
        )
        or xml_info["error"] is not None
    ):
        xml_item: dict[str, Any] = {
            "output_key": "xmlout",
            "path": xml_info["path"],
            "exists": xml_info["exists"],
            "is_symlink": xml_info["is_symlink"],
            "is_regular_file": xml_info["is_regular_file"],
            "within_refmac_dir": xml_info["within_refmac_dir"],
            "size_bytes": xml_info["size_bytes"],
            "error": xml_info["error"] or "invalid_or_symlinked_xmlout",
        }
        if xml_info.get("exception_type") is not None:
            xml_item["exception_type"] = xml_info["exception_type"]
            xml_item["exception_message"] = xml_info.get("exception_message")
            xml_item["errno"] = xml_info.get("errno")
        missing_or_invalid_outputs.append(xml_item)
        missing_or_invalid_output_causes.append(per_raw_output_causes.get("xmlout"))

    if dir_scan.get("scandir_error") is not None:
        missing_or_invalid_outputs.append(dict(dir_scan["scandir_error"]))
        missing_or_invalid_output_causes.append(
            scandir_causes[0] if scandir_causes else None
        )

    for extra_name, extra_info in sorted(dir_scan["additional_files"].items()):
        if (
            extra_info.get("error") is not None
            or extra_info["is_symlink"]
            or not extra_info["is_regular_file"]
            or not extra_info["within_refmac_dir"]
        ):
            extra_path_str = str(extra_info["path"])
            if not any(
                item.get("path") == extra_path_str
                for item in missing_or_invalid_outputs
            ):
                extra_item: dict[str, Any] = {
                    "output_key": f"additional_file:{extra_name}",
                    "path": extra_path_str,
                    "exists": extra_info["exists"],
                    "is_symlink": extra_info["is_symlink"],
                    "is_regular_file": extra_info["is_regular_file"],
                    "within_refmac_dir": extra_info["within_refmac_dir"],
                    "size_bytes": extra_info["size_bytes"],
                    "error": (
                        extra_info["error"]
                        or f"Invalid additional entry in refmac directory: {extra_path_str}"
                    ),
                }
                if extra_info.get("exception_type") is not None:
                    extra_item["exception_type"] = extra_info["exception_type"]
                    extra_item["exception_message"] = extra_info.get(
                        "exception_message"
                    )
                    extra_item["errno"] = extra_info.get("errno")
                missing_or_invalid_outputs.append(extra_item)
                missing_or_invalid_output_causes.append(
                    additional_file_causes.get(extra_name)
                )

    if dir_scan["unexpected_symlinks"]:
        for sym_path in dir_scan["unexpected_symlinks"]:
            if not any(
                item.get("path") == sym_path for item in missing_or_invalid_outputs
            ):
                missing_or_invalid_outputs.append(
                    {
                        "output_key": "unexpected_symlink_in_refmac_dir",
                        "path": sym_path,
                        "exists": True,
                        "is_symlink": True,
                        "is_regular_file": False,
                        "within_refmac_dir": False,
                        "size_bytes": None,
                        "error": f"Unexpected or escaped symlink in refmac directory: {sym_path}",
                    }
                )
                missing_or_invalid_output_causes.append(None)

    invocation_record: dict[str, Any] = {
        "wrapper": "toolchain.run_refmac",
        "custom_runner_injected": runner is not None,
        "executable": (
            str(resolved_refmac_path) if resolved_refmac_path is not None else None
        ),
        "expected_argv": expected_argv,
        "completed_argv": completed_argv,
        "completed_argv_available": completed_argv is not None,
        "argv_matches_expected": bool(
            completed_argv is not None
            and expected_argv is not None
            and completed_argv == expected_argv
        ),
        "cwd": str(refmac_dir),
        "stdin_keywords": REFMAC_KEYWORDS,
        "stdin_keywords_lines": list(REFMAC_KEYWORDS_LINES),
        "stdin_keywords_sha256": keywords_baseline["sha256"],
        "keywords_file_path": str(keywords_path),
        "xyzin_path": str(original_pdb_path),
        "hklin_path": str(projected_mtz_path),
        "xyzout_path": str(xyzout_path),
        "hklout_path": str(hklout_path),
        "xmlout_path": str(xmlout_path),
        "log_path": str(log_path),
        "ccp4_flag_passed_to_run_refmac": False,
        "explicit_env_passed": ccp4_env is not None,
        "timeout_seconds": timeout_seconds,
        "started_at_utc": started_at_utc,
        "finished_at_utc": finished_at_utc,
        "elapsed_seconds": elapsed_seconds,
        "returncode": returncode,
        "timed_out": timed_out,
        "launch_or_timeout_failure": launch_or_timeout_failure,
    }

    for pre_art_key, pre_art_obj in (
        ("pre_execution_checkpoint_json", pre_execution_checkpoint_initial_artifact),
        ("pre_execution_checkpoint_recovery_json", pre_execution_checkpoint_recovery_artifact),
    ):
        if isinstance(pre_art_obj, Mapping) and "fallback_for_preexisting_path" in pre_art_obj:
            collided_path = str(pre_art_obj["fallback_for_preexisting_path"])
            if not any(
                item.get("output_key") == pre_art_key and item.get("path") == collided_path
                for item in missing_or_invalid_outputs
            ):
                missing_or_invalid_outputs.append(
                    {
                        "output_key": pre_art_key,
                        "path": collided_path,
                        "exists": True,
                        "is_symlink": False,
                        "is_regular_file": False,
                        "within_refmac_dir": True,
                        "size_bytes": None,
                        "error": (
                            f"Reserved collector JSON path or temp path collided and required fallback: {collided_path}"
                        ),
                    }
                )
                missing_or_invalid_output_causes.append(None)

    completed_argv_available = completed_argv is not None
    checkpoint_argv_matches = bool(
        completed_argv is not None
        and expected_argv is not None
        and completed_argv == expected_argv
    )
    runner_returned_completed_process = (
        worker_launched and launch_or_timeout_failure is None
    )
    publication_terminal_failure: dict[str, Any] | None = None

    def _current_actual_parent_anchor_info() -> tuple[str | None, str | None, dict[str, Any] | None]:
        parent_used = bool(
            len(child_dir_persistence_failures) > 0
            or not bool(refmac_dir_post_run.get("identity_verified", True))
            or not bool(refmac_dir_post_run.get("writable_post_run", True))
        )
        if not parent_used or publication_terminal_failure is not None:
            return None, None, None
        if bool(verified_root_fallback_state.get("used")):
            return (
                str(verified_root_fallback_state["actual_anchor_dir"]),
                str(verified_root_fallback_state["actual_anchor_kind"]),
                copy.deepcopy(verified_root_fallback_state.get("actual_anchor_baseline")),
            )
        if bool(verified_root_fallback_state.get("no_verified_anchor_available")):
            return None, None, None
        if bool(parent_retention_dir_post_run.get("identity_verified", False)) and bool(
            parent_retention_dir_post_run.get("writable_post_run", True)
        ):
            return (
                str(parent_retention_dir),
                "parent_retention_dir",
                copy.deepcopy(parent_retention_dir_baseline),
            )
        return None, None, None

    def _build_checkpoint_stage_failures() -> list[dict[str, Any]]:
        stage_failures: list[dict[str, Any]] = []
        if preflight_error is not None:
            stage_failures.append(dict(preflight_error))
        if launch_or_timeout_failure is not None:
            stage_failures.append(
                {
                    "failed_stage": (
                        "refmac_timeout" if timed_out else "refmac_runner_invocation"
                    ),
                    **launch_or_timeout_failure,
                }
            )
        if worker_launched and launch_or_timeout_failure is None and returncode != 0:
            stage_failures.append(
                {
                    "failed_stage": "refmac_returncode",
                    "exception_type": "RuntimeError",
                    "exception_message": (
                        f"REFMAC5 exited with non-zero returncode {returncode}"
                    ),
                    "returncode": returncode,
                }
            )
        if runner_returned_completed_process and not checkpoint_argv_matches:
            stage_failures.append(
                {
                    "failed_stage": "refmac_argv_verification",
                    "exception_type": "ValueError",
                    "exception_message": (
                        f"CompletedProcess.args is None (unavailable); runner contract requires "
                        f"returned argv matching expected argv {expected_argv!r}"
                        if completed_argv is None
                        else (
                            f"CompletedProcess.args {completed_argv!r} did not match "
                            f"expected argv {expected_argv!r}"
                        )
                    ),
                }
            )
        if not pre_execution_checkpoint_verified:
            stage_failures.append(
                {
                    "failed_stage": "verify_pre_execution_checkpoint",
                    "exception_type": str(
                        pre_checkpoint_post_run.get("exception_type") or "ValueError"
                    ),
                    "exception_message": str(
                        pre_checkpoint_post_run.get("reason")
                        or pre_checkpoint_post_run.get("error")
                        or "Pre-execution checkpoint refmac_pre_execution_checkpoint.json mutated or missing after REFMAC operation"
                    ),
                    "original_recorded_checkpoint": copy.deepcopy(
                        pre_execution_checkpoint_initial_artifact
                    ),
                    "damaged_checkpoint_post_run": copy.deepcopy(
                        pre_checkpoint_post_run
                    ),
                    "recovery_checkpoint_json": copy.deepcopy(
                        pre_execution_checkpoint_recovery_artifact
                    ),
                }
            )
        if worker_launched and len(missing_or_invalid_outputs) > 0:
            first_out_exc = next(
                (
                    str(item["exception_type"])
                    for item in missing_or_invalid_outputs
                    if item.get("exception_type") is not None
                ),
                "RuntimeError",
            )
            stage_failures.append(
                {
                    "failed_stage": "refmac_raw_outputs",
                    "exception_type": first_out_exc,
                    "exception_message": (
                        "Missing, empty, unreadable, or symlinked REFMAC raw output or directory artifact(s): "
                        + ", ".join(
                            f"{item['output_key']} ({item['error']})"
                            for item in missing_or_invalid_outputs
                        )
                    ),
                    "missing_or_invalid_outputs": list(missing_or_invalid_outputs),
                }
            )
        if not bool(immutability_report["verified"]):
            stage_failures.append(
                {
                    "failed_stage": "verify_input_immutability",
                    "exception_type": "ValueError",
                    "exception_message": (
                        "Immutable input or helper/keywords/checkpoint baseline mutated during REFMAC operation: "
                        + "; ".join(
                            f"{m['key']}: {m['reason']}"
                            for m in immutability_report["mutations"]
                        )
                    ),
                    "mutations": immutability_report["mutations"],
                }
            )
        if not bool(parent_retention_dir_post_run.get("identity_verified", True)) or not bool(
            parent_retention_dir_post_run.get("writable_post_run", True)
        ):
            parent_exc_type = str(
                parent_retention_dir_post_run.get("write_exception_type")
                or parent_retention_dir_post_run.get("exception_type")
                or "ValueError"
            )
            parent_exc_msg = str(
                parent_retention_dir_post_run.get("write_exception_message")
                or parent_retention_dir_post_run.get("exception_message")
                or parent_retention_dir_post_run.get("error")
                or f"Parent retention directory failed identity/writability verification: {parent_retention_dir}"
            )
            stage_failures.append(
                {
                    "failed_stage": "verify_parent_retention_directory",
                    "exception_type": parent_exc_type,
                    "exception_message": parent_exc_msg,
                    "intended_parent_retention_dir": str(parent_retention_dir),
                    "parent_retention_directory_baseline": copy.deepcopy(
                        parent_retention_dir_baseline
                    ),
                    "parent_retention_directory_post_run": copy.deepcopy(
                        parent_retention_dir_post_run
                    ),
                    "parent_retention_fallback_anchor": copy.deepcopy(
                        verified_root_fallback_state
                    ),
                }
            )
        if (
            not bool(refmac_dir_post_run.get("identity_verified", True))
            or not bool(refmac_dir_post_run.get("writable_post_run", True))
            or len(child_dir_persistence_failures) > 0
        ):
            first_persist_exc_type = (
                str(child_dir_persistence_failures[0]["exception_type"])
                if child_dir_persistence_failures
                else str(
                    refmac_dir_post_run.get("write_exception_type")
                    or refmac_dir_post_run.get("exception_type")
                    or "PermissionError"
                )
            )
            first_persist_exc_msg = (
                str(child_dir_persistence_failures[0]["exception_message"])
                if child_dir_persistence_failures
                else str(
                    refmac_dir_post_run.get("write_exception_message")
                    or refmac_dir_post_run.get("exception_message")
                    or refmac_dir_post_run.get("error")
                    or f"Child refmac directory unavailable or unwritable: {refmac_dir}"
                )
            )
            actual_anchor_dir, actual_anchor_kind, actual_anchor_baseline = (
                _current_actual_parent_anchor_info()
            )
            retention_loc_desc = (
                f"retained under {actual_anchor_kind} {actual_anchor_dir}"
                if actual_anchor_dir is not None
                else "no verified retention anchor available on disk"
            )
            stage_failures.append(
                {
                    "failed_stage": "persist_collector_artifacts_in_refmac_dir",
                    "exception_type": first_persist_exc_type,
                    "exception_message": (
                        f"Unable to persist collector JSON artifacts in child refmac directory {refmac_dir} "
                        f"({first_persist_exc_type}: {first_persist_exc_msg}); "
                        f"{retention_loc_desc}"
                    ),
                    "parent_retention_dir": str(parent_retention_dir),
                    "intended_parent_retention_dir": str(parent_retention_dir),
                    "actual_parent_retention_anchor_dir": actual_anchor_dir,
                    "actual_parent_retention_anchor_kind": actual_anchor_kind,
                    "actual_parent_retention_anchor_baseline": actual_anchor_baseline,
                    "refmac_directory_post_run": copy.deepcopy(refmac_dir_post_run),
                    "parent_retention_directory_post_run": copy.deepcopy(
                        parent_retention_dir_post_run
                    ),
                    "parent_retention_fallback_anchor": copy.deepcopy(
                        verified_root_fallback_state
                    ),
                    "child_dir_persistence_failures": copy.deepcopy(
                        child_dir_persistence_failures
                    ),
                }
            )
        return stage_failures

    def _populate_post_checkpoint_status_fields(
        base_payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        updated = dict(base_payload)
        current_failures = _build_checkpoint_stage_failures()
        has_failures = len(current_failures) > 0
        immutability_report["refmac_directory_post_run"] = copy.deepcopy(
            refmac_dir_post_run
        )
        immutability_report["parent_retention_directory_post_run"] = copy.deepcopy(
            parent_retention_dir_post_run
        )
        actual_anchor_dir, actual_anchor_kind, actual_anchor_baseline = (
            _current_actual_parent_anchor_info()
        )
        updated["status"] = (
            "failed" if has_failures else "post_execution_checkpointed"
        )
        updated["failed_stage"] = (
            current_failures[0]["failed_stage"] if has_failures else None
        )
        updated["failures"] = current_failures
        updated["refmac_directory_post_run"] = copy.deepcopy(refmac_dir_post_run)
        updated["parent_retention_directory_post_run"] = copy.deepcopy(
            parent_retention_dir_post_run
        )
        updated["intended_parent_retention_dir"] = str(parent_retention_dir)
        updated["actual_parent_retention_anchor_dir"] = actual_anchor_dir
        updated["actual_parent_retention_anchor_kind"] = actual_anchor_kind
        updated["actual_parent_retention_anchor_baseline"] = actual_anchor_baseline
        updated["parent_retention_fallback_anchor"] = copy.deepcopy(
            verified_root_fallback_state
        )
        updated["parent_retention_used"] = bool(
            len(child_dir_persistence_failures) > 0
            or not bool(refmac_dir_post_run.get("identity_verified", True))
            or not bool(refmac_dir_post_run.get("writable_post_run", True))
        )
        updated["child_dir_persistence_failures"] = copy.deepcopy(
            child_dir_persistence_failures
        )
        updated["operation_checks"] = {
            "preflight_toolchain_resolved": preflight_error is None,
            "worker_launched": worker_launched,
            "process_returncode_zero": bool(
                preflight_error is None
                and worker_launched
                and launch_or_timeout_failure is None
                and not timed_out
                and returncode == 0
                and checkpoint_argv_matches
            ),
            "completed_argv_available": completed_argv_available,
            "argv_matches_expected": checkpoint_argv_matches,
            "pre_execution_checkpoint_verified": pre_execution_checkpoint_verified,
            "refmac_dir_identity_verified": bool(
                refmac_dir_post_run.get("identity_verified", False)
            ),
            "refmac_dir_writable_post_run": bool(
                refmac_dir_post_run.get("writable_post_run", False)
            ),
            "parent_retention_dir_identity_verified": bool(
                parent_retention_dir_post_run.get("identity_verified", False)
            ),
            "parent_retention_dir_writable_post_run": bool(
                parent_retention_dir_post_run.get("writable_post_run", False)
            ),
            "all_raw_outputs_present_and_regular": len(missing_or_invalid_outputs) == 0,
            "input_immutability_verified": bool(immutability_report["verified"]),
            "collector_succeeded": False if has_failures else None,
        }
        updated["scientific_admission_proven"] = False
        return updated

    post_execution_checkpoint_payload: dict[str, Any] = _populate_post_checkpoint_status_fields(
        {
            "schema_version": 1,
            "checkpoint_stage": "post_execution",
            "collector_stage": COLLECTOR_STAGE,
            "status": "post_execution_checkpointed",
            "recorded_at_utc": _utc_timestamp_iso(),
            "subject_id": subject_id,
            "evidence_root": str(fresh_root),
            "inputs_dir": str(inputs_dir),
            "refmac_dir": str(refmac_dir),
            "parent_retention_dir": str(parent_retention_dir),
            "refmac_directory_baseline": copy.deepcopy(refmac_dir_baseline),
            "parent_retention_directory_baseline": copy.deepcopy(
                parent_retention_dir_baseline
            ),
            "subject": admission_record["subject"],
            "mtz": admission_record["mtz"],
            "staged_files": admission_record["staged_files"],
            "staged_inputs_baseline": copy.deepcopy(staged_input_baseline),
            "helper_sources": copy.deepcopy(helper_source_baseline),
            "helper_sources_baseline": copy.deepcopy(helper_source_baseline),
            "keywords_file_baseline": copy.deepcopy(keywords_baseline),
            "toolchain": toolchain_record,
            "preflight_error": preflight_error,
            "pre_execution_checkpoint_json": pre_execution_checkpoint_artifact,
            "pre_execution_checkpoint_initial_json": pre_execution_checkpoint_initial_artifact,
            "pre_execution_checkpoint_post_run": pre_checkpoint_post_run,
            "pre_execution_checkpoint_recovery_json": pre_execution_checkpoint_recovery_artifact,
            "pre_execution_checkpoint_verified": pre_execution_checkpoint_verified,
            "invocation": invocation_record,
            "raw_outputs": raw_outputs,
            "additional_refmac_dir_files": dir_scan["additional_files"],
            "unexpected_symlinks": dir_scan["unexpected_symlinks"],
            "inspection_errors": dir_scan["inspection_errors"],
            "missing_or_invalid_outputs": list(missing_or_invalid_outputs),
            "input_immutability": immutability_report,
        }
    )
    post_execution_checkpoint_artifact = _persist_collector_json_with_fallback(
        post_execution_checkpoint_payload,
        post_execution_checkpoint_json_path,
        root=refmac_dir,
        parent_retention_dir=parent_retention_dir,
        parent_retention_dir_baseline=parent_retention_dir_baseline,
        parent_retention_dir_status=parent_retention_dir_post_run,
        verified_root_fallback_state=verified_root_fallback_state,
        allow_unpersisted_on_no_verified_anchor=True,
        refmac_dir_status=refmac_dir_post_run,
        child_dir_persistence_failures=child_dir_persistence_failures,
        caught_persistence_exceptions=caught_persistence_exceptions,
        on_child_dir_failure_transform=_populate_post_checkpoint_status_fields,
        child_dir_persistence_causes=child_dir_persistence_causes,
        parent_retention_dir_cause_sink=parent_retention_dir_cause_holder,
    )

    caught_audit_exceptions: list[Exception] = []

    # Read actual combined log on disk (run_logged redirects stdout/stderr to log_path).
    log_info = raw_outputs["log"]
    log_text: str | None = None
    log_utf8_exact: bool | None = None
    native_log_diagnostics: dict[str, Any] | None = None
    parsed_log: dict[str, Any] | None = None
    parsed_log_artifact: dict[str, Any] | None = None
    log_parse_error: dict[str, Any] | None = None
    log_parse_exception: Exception | None = None

    if (
        log_info["exists"]
        and log_info["is_regular_file"]
        and not log_info["is_symlink"]
        and log_info["within_refmac_dir"]
        and log_info["error"] is None
    ):
        try:
            raw_log_bytes = log_path.read_bytes()
            try:
                log_text = raw_log_bytes.decode("utf-8", errors="strict")
                log_utf8_exact = True
            except UnicodeDecodeError:
                log_text = raw_log_bytes.decode("utf-8", errors="replace")
                log_utf8_exact = False

            native_log_diagnostics = _extract_native_log_diagnostics(log_text)
            if isinstance(log_info["size_bytes"], int) and log_info["size_bytes"] > 0:
                parsed_log = onesar_refmac_log.parse_refmac_log(log_text)
                parsed_log_artifact = _persist_collector_json_with_fallback(
                    parsed_log,
                    parsed_log_json_path,
                    root=refmac_dir,
                    parent_retention_dir=parent_retention_dir,
                    parent_retention_dir_baseline=parent_retention_dir_baseline,
                    parent_retention_dir_status=parent_retention_dir_post_run,
                    verified_root_fallback_state=verified_root_fallback_state,
                    allow_unpersisted_on_no_verified_anchor=True,
                    refmac_dir_status=refmac_dir_post_run,
                    child_dir_persistence_failures=child_dir_persistence_failures,
                    caught_persistence_exceptions=caught_persistence_exceptions,
                    child_dir_persistence_causes=child_dir_persistence_causes,
                    parent_retention_dir_cause_sink=parent_retention_dir_cause_holder,
                )
            else:
                log_parse_error = {
                    "exception_type": "ValueError",
                    "exception_message": f"REFMAC log file on disk is empty: {log_path}",
                }
        except Exception as exc:
            log_parse_exception = exc
            parsed_log = None
            log_parse_error = {
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
            }
            caught_audit_exceptions.append(exc)
    elif worker_launched:
        log_parse_error = {
            "exception_type": "FileNotFoundError",
            "exception_message": (
                f"REFMAC combined log on disk is missing or invalid: {log_info.get('error') or log_path}"
            ),
        }

    native_r_pair_parsed = parsed_log is not None and parsed_log_artifact is not None
    ncyc_zero_exception: Exception | None = None
    try:
        ncyc_zero_check = _evaluate_ncyc_zero_operation_check(
            keywords_text=REFMAC_KEYWORDS,
            native_log_diagnostics=native_log_diagnostics,
            parsed_log=parsed_log,
        )
    except Exception as exc:
        ncyc_zero_exception = exc
        caught_audit_exceptions.append(exc)
        ncyc_zero_check = {
            "passed": False,
            "requested_keyword_lines": ["NCYC 0"],
            "requested_is_ncyc_zero": True,
            "echoed_data_ncyc_tokens": [],
            "echoed_refinement_cycles_tokens": [],
            "parsed_requested_ncyc": None,
            "summary_cycle_min": None,
            "summary_cycle_max": None,
            "summary_row_count": None,
            "detailed_cycle_count": None,
            "cgmat_cycle_marker_count": None,
            "reason": f"NCYC 0 verification raised {type(exc).__name__}: {exc}",
        }

    # Execute and persist all 3 output audits (XMLOUT, HKLOUT raw+audit, XYZOUT) inside isolated failure boundaries.
    xmlout_audit_exception: Exception | None = None
    try:
        xmlout_audit = _audit_refmac_xmlout(
            xmlout_path,
            xmlout_info=raw_outputs["xmlout"],
            parsed_log=parsed_log,
        )
    except Exception as exc:
        xmlout_audit_exception = exc
        caught_audit_exceptions.append(exc)
        xmlout_audit = {
            "schema_version": 1,
            "xmlout_path": str(xmlout_path),
            "present": bool(raw_outputs["xmlout"]["exists"]),
            "sha256": raw_outputs["xmlout"]["sha256"],
            "size_bytes": raw_outputs["xmlout"]["size_bytes"],
            "status": "audit_exception",
            "valid": False,
            "reconciled_with_log": None,
            "errors": [
                f"Unexpected exception during XMLOUT audit ({type(exc).__name__}): {exc}"
            ],
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
        }
    xmlout_audit_artifact = _persist_collector_json_with_fallback(
        xmlout_audit,
        xmlout_audit_json_path,
        root=refmac_dir,
        parent_retention_dir=parent_retention_dir,
        parent_retention_dir_baseline=parent_retention_dir_baseline,
        parent_retention_dir_status=parent_retention_dir_post_run,
        verified_root_fallback_state=verified_root_fallback_state,
        allow_unpersisted_on_no_verified_anchor=True,
        refmac_dir_status=refmac_dir_post_run,
        child_dir_persistence_failures=child_dir_persistence_failures,
        caught_persistence_exceptions=caught_persistence_exceptions,
        child_dir_persistence_causes=child_dir_persistence_causes,
        parent_retention_dir_cause_sink=parent_retention_dir_cause_holder,
    )

    hklout_audit_exception: Exception | None = None
    retained_raw_export_holder: list[dict[str, Any]] = []
    try:
        hklout_audit, hklout_raw_export_artifact = _export_and_audit_refmac_hklout(
            projected_mtz_path=projected_mtz_path,
            hklout_path=hklout_path,
            hklout_info=raw_outputs["hklout"],
            input_ledger=input_ledger,
            parsed_log=parsed_log,
            native_log_diagnostics=native_log_diagnostics,
            raw_export_json_path=hklout_raw_export_json_path,
            refmac_dir=refmac_dir,
            hklin_baseline=staged_input_baseline["projected_observations_mtz"],
            retained_raw_export_holder=retained_raw_export_holder,
            parent_retention_dir=parent_retention_dir,
            parent_retention_dir_baseline=parent_retention_dir_baseline,
            parent_retention_dir_status=parent_retention_dir_post_run,
            verified_root_fallback_state=verified_root_fallback_state,
            allow_unpersisted_on_no_verified_anchor=True,
            refmac_dir_status=refmac_dir_post_run,
            child_dir_persistence_failures=child_dir_persistence_failures,
            caught_persistence_exceptions=caught_persistence_exceptions,
            child_dir_persistence_causes=child_dir_persistence_causes,
            parent_retention_dir_cause_sink=parent_retention_dir_cause_holder,
        )
    except Exception as exc:
        hklout_audit_exception = exc
        caught_audit_exceptions.append(exc)
        if retained_raw_export_holder:
            hklout_raw_export_artifact = retained_raw_export_holder[0]
        else:
            fallback_raw_export = {
                "schema_version": 1,
                "path": str(hklout_path),
                "sha256": raw_outputs["hklout"]["sha256"],
                "size_bytes": raw_outputs["hklout"]["size_bytes"],
                "word_hex_convention": MTZ_WORD_HEX_CONVENTION,
                "raw_export_error": f"{type(exc).__name__}: {exc}",
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
                "header_parse": None,
                "row_count_exported": 0,
                "rows": [],
            }
            hklout_raw_export_artifact = _persist_collector_json_with_fallback(
                fallback_raw_export,
                hklout_raw_export_json_path,
                root=refmac_dir,
                parent_retention_dir=parent_retention_dir,
                parent_retention_dir_baseline=parent_retention_dir_baseline,
                parent_retention_dir_status=parent_retention_dir_post_run,
                verified_root_fallback_state=verified_root_fallback_state,
                allow_unpersisted_on_no_verified_anchor=True,
                refmac_dir_status=refmac_dir_post_run,
                child_dir_persistence_failures=child_dir_persistence_failures,
                caught_persistence_exceptions=caught_persistence_exceptions,
                child_dir_persistence_causes=child_dir_persistence_causes,
                parent_retention_dir_cause_sink=parent_retention_dir_cause_holder,
            )
        hklout_err_msg = f"Unexpected exception during HKLOUT audit ({type(exc).__name__}): {exc}"
        hklout_audit = {
            "schema_version": 1,
            "path": str(hklout_path),
            "raw_export_json": hklout_raw_export_artifact,
            "word_hex_convention": MTZ_WORD_HEX_CONVENTION,
            "status": "audit_exception",
            "valid": False,
            "errors": [hklout_err_msg],
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "effective_hkls_proven": False,
            "effective_hkls_unproven_reason": hklout_err_msg,
            "native_bin_membership_proven": False,
            "native_bin_membership_unproven_reason": hklout_err_msg,
            "native_residual_reconstruction_proven": False,
            "native_residual_reconstruction_unproven_reason": hklout_err_msg,
        }
    hklout_audit_artifact = _persist_collector_json_with_fallback(
        hklout_audit,
        hklout_audit_json_path,
        root=refmac_dir,
        parent_retention_dir=parent_retention_dir,
        parent_retention_dir_baseline=parent_retention_dir_baseline,
        parent_retention_dir_status=parent_retention_dir_post_run,
        verified_root_fallback_state=verified_root_fallback_state,
        allow_unpersisted_on_no_verified_anchor=True,
        refmac_dir_status=refmac_dir_post_run,
        child_dir_persistence_failures=child_dir_persistence_failures,
        caught_persistence_exceptions=caught_persistence_exceptions,
        child_dir_persistence_causes=child_dir_persistence_causes,
        parent_retention_dir_cause_sink=parent_retention_dir_cause_holder,
    )

    xyzout_audit_exception: Exception | None = None
    try:
        xyzout_audit = _audit_refmac_xyzout(
            original_pdb_path=original_pdb_path,
            xyzout_path=xyzout_path,
            xyzout_info=raw_outputs["xyzout"],
            xyzin_baseline=staged_input_baseline["original_model_pdb"],
        )
    except Exception as exc:
        xyzout_audit_exception = exc
        caught_audit_exceptions.append(exc)
        xyzout_err_msg = f"Unexpected exception during XYZOUT audit ({type(exc).__name__}): {exc}"
        xyzout_audit = {
            "schema_version": 1,
            "xyzin_path": str(original_pdb_path),
            "xyzin_sha256": staged_input_baseline["original_model_pdb"]["sha256"],
            "xyzin_size_bytes": staged_input_baseline["original_model_pdb"][
                "size_bytes"
            ],
            "xyzout_path": str(xyzout_path),
            "xyzout_sha256": raw_outputs["xyzout"]["sha256"],
            "xyzout_size_bytes": raw_outputs["xyzout"]["size_bytes"],
            "status": "audit_exception",
            "valid": False,
            "errors": [xyzout_err_msg],
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "model_preservation_proven": False,
            "model_preservation_unproven_reason": xyzout_err_msg,
        }
    xyzout_audit_artifact = _persist_collector_json_with_fallback(
        xyzout_audit,
        xyzout_audit_json_path,
        root=refmac_dir,
        parent_retention_dir=parent_retention_dir,
        parent_retention_dir_baseline=parent_retention_dir_baseline,
        parent_retention_dir_status=parent_retention_dir_post_run,
        verified_root_fallback_state=verified_root_fallback_state,
        allow_unpersisted_on_no_verified_anchor=True,
        refmac_dir_status=refmac_dir_post_run,
        child_dir_persistence_failures=child_dir_persistence_failures,
        caught_persistence_exceptions=caught_persistence_exceptions,
        child_dir_persistence_causes=child_dir_persistence_causes,
        parent_retention_dir_cause_sink=parent_retention_dir_cause_holder,
    )

    for art_key, art_obj in (
        ("pre_execution_checkpoint_json", pre_execution_checkpoint_initial_artifact),
        ("post_execution_checkpoint_json", post_execution_checkpoint_artifact),
        ("parsed_log_json", parsed_log_artifact),
        ("xmlout_audit_json", xmlout_audit_artifact),
        ("hklout_raw_export_json", hklout_raw_export_artifact),
        ("hklout_audit_json", hklout_audit_artifact),
        ("xyzout_audit_json", xyzout_audit_artifact),
    ):
        if isinstance(art_obj, Mapping) and "fallback_for_preexisting_path" in art_obj:
            collided_path = str(art_obj["fallback_for_preexisting_path"])
            if not any(
                item.get("output_key") == art_key and item.get("path") == collided_path
                for item in missing_or_invalid_outputs
            ):
                missing_or_invalid_outputs.append(
                    {
                        "output_key": art_key,
                        "path": collided_path,
                        "exists": True,
                        "is_symlink": False,
                        "is_regular_file": False,
                        "within_refmac_dir": True,
                        "size_bytes": None,
                        "error": (
                            f"Reserved collector JSON path or temp path collided and required fallback: {collided_path}"
                        ),
                    }
                )
                missing_or_invalid_output_causes.append(None)

    argv_matches_expected = bool(
        completed_argv is not None
        and expected_argv is not None
        and completed_argv == expected_argv
    )
    process_returncode_zero = (
        preflight_error is None
        and worker_launched
        and launch_or_timeout_failure is None
        and not timed_out
        and returncode == 0
        and argv_matches_expected
    )
    all_raw_outputs_valid = len(missing_or_invalid_outputs) == 0
    input_immutability_verified = bool(immutability_report["verified"])

    base_failures: list[dict[str, Any]] = []
    base_failure_causes: dict[str, Exception | None] = {}
    if preflight_error is not None:
        base_failures.append(dict(preflight_error))
        base_failure_causes[str(preflight_error["failed_stage"])] = preflight_exception
    if launch_or_timeout_failure is not None:
        launch_stage = (
            "refmac_timeout"
            if timed_out
            else "refmac_runner_invocation"
        )
        base_failures.append(
            {
                "failed_stage": launch_stage,
                **launch_or_timeout_failure,
            }
        )
        base_failure_causes[launch_stage] = launch_or_timeout_exception
    if (
        worker_launched
        and launch_or_timeout_failure is None
        and returncode != 0
    ):
        base_failures.append(
            {
                "failed_stage": "refmac_returncode",
                "exception_type": "RuntimeError",
                "exception_message": (
                    f"REFMAC5 exited with non-zero returncode {returncode}"
                ),
                "returncode": returncode,
            }
        )
        base_failure_causes["refmac_returncode"] = None
    if runner_returned_completed_process and not argv_matches_expected:
        base_failures.append(
            {
                "failed_stage": "refmac_argv_verification",
                "exception_type": "ValueError",
                "exception_message": (
                    f"CompletedProcess.args is None (unavailable); runner contract requires "
                    f"returned argv matching expected argv {expected_argv!r}"
                    if completed_argv is None
                    else (
                        f"CompletedProcess.args {completed_argv!r} did not match "
                        f"expected argv {expected_argv!r}"
                    )
                ),
            }
        )
        base_failure_causes["refmac_argv_verification"] = None
    if not pre_execution_checkpoint_verified:
        base_failures.append(
            {
                "failed_stage": "verify_pre_execution_checkpoint",
                "exception_type": str(
                    pre_checkpoint_post_run.get("exception_type") or "ValueError"
                ),
                "exception_message": (
                    str(
                        pre_checkpoint_post_run.get("reason")
                        or pre_checkpoint_post_run.get("error")
                        or "Pre-execution checkpoint refmac_pre_execution_checkpoint.json mutated or missing after REFMAC operation"
                    )
                ),
                "original_recorded_checkpoint": copy.deepcopy(
                    pre_execution_checkpoint_initial_artifact
                ),
                "damaged_checkpoint_post_run": copy.deepcopy(
                    pre_checkpoint_post_run
                ),
                "recovery_checkpoint_json": copy.deepcopy(
                    pre_execution_checkpoint_recovery_artifact
                ),
            }
        )
        base_failure_causes["verify_pre_execution_checkpoint"] = pre_checkpoint_cause
    if worker_launched and not all_raw_outputs_valid:
        first_output_exc_type = next(
            (
                str(item["exception_type"])
                for item in missing_or_invalid_outputs
                if item.get("exception_type") is not None
            ),
            "RuntimeError",
        )
        raw_outputs_primary_cause: Exception | None = next(
            (
                cause
                for item, cause in zip(
                    missing_or_invalid_outputs, missing_or_invalid_output_causes
                )
                if item.get("exception_type") is not None and cause is not None
            ),
            None,
        )
        base_failures.append(
            {
                "failed_stage": "refmac_raw_outputs",
                "exception_type": first_output_exc_type,
                "exception_message": (
                    "Missing, empty, unreadable, or symlinked REFMAC raw output or directory artifact(s): "
                    + ", ".join(
                        f"{item['output_key']} ({item['error']})"
                        for item in missing_or_invalid_outputs
                    )
                ),
                "missing_or_invalid_outputs": missing_or_invalid_outputs,
            }
        )
        base_failure_causes["refmac_raw_outputs"] = raw_outputs_primary_cause
    if worker_launched and log_parse_error is not None:
        base_failures.append(
            {
                "failed_stage": "parse_refmac_log",
                **log_parse_error,
            }
        )
        base_failure_causes["parse_refmac_log"] = log_parse_exception
    if worker_launched and log_parse_error is None and not ncyc_zero_check["passed"]:
        base_failures.append(
            {
                "failed_stage": "verify_ncyc_zero_operation",
                "exception_type": (
                    type(ncyc_zero_exception).__name__
                    if ncyc_zero_exception is not None
                    else "ValueError"
                ),
                "exception_message": (
                    str(ncyc_zero_exception)
                    if ncyc_zero_exception is not None
                    else str(ncyc_zero_check["reason"])
                ),
            }
        )
        base_failure_causes["verify_ncyc_zero_operation"] = ncyc_zero_exception
    if worker_launched and not xmlout_audit["valid"]:
        base_failures.append(
            {
                "failed_stage": "audit_refmac_xmlout",
                "exception_type": (
                    type(xmlout_audit_exception).__name__
                    if xmlout_audit_exception is not None
                    else "ValueError"
                ),
                "exception_message": (
                    str(xmlout_audit_exception)
                    if xmlout_audit_exception is not None
                    else ("; ".join(xmlout_audit["errors"]) or "XMLOUT audit failed")
                ),
                "xmlout_status": xmlout_audit["status"],
            }
        )
        base_failure_causes["audit_refmac_xmlout"] = xmlout_audit_exception
    if worker_launched and not hklout_audit["valid"]:
        base_failures.append(
            {
                "failed_stage": "audit_refmac_hklout",
                "exception_type": (
                    type(hklout_audit_exception).__name__
                    if hklout_audit_exception is not None
                    else "ValueError"
                ),
                "exception_message": (
                    str(hklout_audit_exception)
                    if hklout_audit_exception is not None
                    else (
                        "; ".join(hklout_audit["errors"])
                        or "HKLOUT MTZ audit failed"
                    )
                ),
                "hklout_status": hklout_audit["status"],
            }
        )
        base_failure_causes["audit_refmac_hklout"] = hklout_audit_exception
    if worker_launched and not xyzout_audit["valid"]:
        base_failures.append(
            {
                "failed_stage": "audit_refmac_xyzout",
                "exception_type": (
                    type(xyzout_audit_exception).__name__
                    if xyzout_audit_exception is not None
                    else "ValueError"
                ),
                "exception_message": (
                    str(xyzout_audit_exception)
                    if xyzout_audit_exception is not None
                    else (
                        "; ".join(xyzout_audit["errors"])
                        or "XYZOUT PDB audit failed"
                    )
                ),
                "xyzout_status": xyzout_audit["status"],
            }
        )
        base_failure_causes["audit_refmac_xyzout"] = xyzout_audit_exception
    if not input_immutability_verified:
        immutability_primary_cause: Exception | None = (
            immutability_mutation_causes[0]
            if len(immutability_report["mutations"]) == 1
            and len(immutability_mutation_causes) == 1
            else None
        )
        base_failures.append(
            {
                "failed_stage": "verify_input_immutability",
                "exception_type": "ValueError",
                "exception_message": (
                    "Immutable input or helper/keywords/checkpoint baseline mutated during REFMAC operation: "
                    + "; ".join(
                        f"{m['key']}: {m['reason']}"
                        for m in immutability_report["mutations"]
                    )
                ),
                "mutations": immutability_report["mutations"],
            }
        )
        base_failure_causes["verify_input_immutability"] = immutability_primary_cause

    audits_bundle: dict[str, Any] = {
        "xmlout_audit": xmlout_audit,
        "hklout_mtz_audit": hklout_audit,
        "xyzout_pdb_audit": xyzout_audit,
    }

    def _select_cause_for_stage(stage_name: str | None) -> Exception | None:
        if stage_name is None:
            return None
        if stage_name == "verify_parent_retention_directory":
            return (
                parent_retention_dir_cause_holder[0]
                if parent_retention_dir_cause_holder
                else None
            )
        if stage_name == "persist_collector_artifacts_in_refmac_dir":
            return next(
                (c for c in child_dir_persistence_causes if c is not None),
                refmac_dir_initial_cause,
            )
        return base_failure_causes.get(stage_name)

    final_artifact_collisions: list[dict[str, Any]] = []
    collision_latched_stage_prefix: list[str] = []
    collision_latched_stage_rows: dict[str, dict[str, Any]] = {}
    collision_latched_primary_stage: str | None = None
    collision_latched_primary_cause: Exception | None = None
    publication_history: list[dict[str, Any]] = []
    publication_pair_complete: bool = True
    publication_correction_count: int = 0
    terminal_caught_exception: Exception | None = None
    active_diagnostics_canonical_name: str = diagnostics_json_path.name
    active_manifest_canonical_name: str = manifest_json_path.name

    def _latch_current_failure_stages(
        *,
        include_pending_collision: bool = False,
    ) -> None:
        nonlocal collision_latched_primary_stage
        nonlocal collision_latched_primary_cause
        current_outcome = _derive_final_collection_outcome()
        for item in current_outcome["failures"]:
            if isinstance(item, Mapping) and item.get("failed_stage") is not None:
                stage_str = str(item["failed_stage"])
                if stage_str not in collision_latched_stage_prefix:
                    collision_latched_stage_prefix.append(stage_str)
                if stage_str not in collision_latched_stage_rows:
                    collision_latched_stage_rows[stage_str] = copy.deepcopy(
                        dict(item)
                    )
                if collision_latched_primary_stage is None:
                    collision_latched_primary_stage = stage_str
                    collision_latched_primary_cause = _select_cause_for_stage(
                        stage_str
                    )
        if include_pending_collision:
            if "refmac_raw_outputs" not in collision_latched_stage_prefix:
                collision_latched_stage_prefix.append("refmac_raw_outputs")
            if collision_latched_primary_stage is None:
                collision_latched_primary_stage = "refmac_raw_outputs"
                collision_latched_primary_cause = None

    def _record_final_artifact_collision_if_any(
        artifact_key: str,
        canonical_filename: str,
        selected_destination: Path | None,
    ) -> None:
        if selected_destination is None:
            return
        if selected_destination.name == canonical_filename:
            return
        if "refmac_raw_outputs" not in collision_latched_stage_prefix:
            _latch_current_failure_stages(include_pending_collision=True)
        collided_canonical_path = str(selected_destination.parent / canonical_filename)
        for existing in final_artifact_collisions:
            if (
                existing.get("output_key") == artifact_key
                and existing.get("path") == collided_canonical_path
            ):
                existing["selected_destination_path"] = str(selected_destination)
                return
        final_artifact_collisions.append(
            {
                "output_key": artifact_key,
                "path": collided_canonical_path,
                "selected_destination_path": str(selected_destination),
                "within_refmac_dir": selected_destination.parent == refmac_dir,
            }
        )

    def _derive_final_collection_outcome() -> dict[str, Any]:
        refmac_dir_post_run_snapshot = copy.deepcopy(refmac_dir_post_run)
        parent_retention_dir_post_run_snapshot = copy.deepcopy(
            parent_retention_dir_post_run
        )
        verified_root_fallback_snapshot = copy.deepcopy(
            verified_root_fallback_state
        )
        child_dir_failures_snapshot = copy.deepcopy(
            child_dir_persistence_failures
        )
        immutability_report["refmac_directory_post_run"] = copy.deepcopy(
            refmac_dir_post_run_snapshot
        )
        immutability_report["parent_retention_directory_post_run"] = copy.deepcopy(
            parent_retention_dir_post_run_snapshot
        )
        immutability_snapshot = copy.deepcopy(immutability_report)

        refmac_dir_identity_verified = bool(
            refmac_dir_post_run_snapshot.get("identity_verified", False)
        )
        refmac_dir_writable_post_run = bool(
            refmac_dir_post_run_snapshot.get("writable_post_run", False)
        )
        parent_retention_dir_identity_verified = bool(
            parent_retention_dir_post_run_snapshot.get("identity_verified", False)
        )
        parent_retention_dir_writable_post_run = bool(
            parent_retention_dir_post_run_snapshot.get("writable_post_run", False)
        )

        current_missing_or_invalid_outputs: list[dict[str, Any]] = [
            copy.deepcopy(item) for item in missing_or_invalid_outputs
        ]
        for collision in final_artifact_collisions:
            collided_key = str(collision["output_key"])
            collided_path = str(collision["path"])
            if not any(
                item.get("output_key") == collided_key
                and item.get("path") == collided_path
                for item in current_missing_or_invalid_outputs
            ):
                current_missing_or_invalid_outputs.append(
                    {
                        "output_key": collided_key,
                        "path": collided_path,
                        "exists": True,
                        "is_symlink": False,
                        "is_regular_file": False,
                        "within_refmac_dir": bool(
                            collision.get("within_refmac_dir", True)
                        ),
                        "size_bytes": None,
                        "error": (
                            f"Reserved collector JSON path or temp path collided and required fallback: {collided_path}"
                        ),
                    }
                )
        current_all_raw_outputs_valid = len(current_missing_or_invalid_outputs) == 0

        raw_failures: list[dict[str, Any]] = [
            copy.deepcopy(item) for item in base_failures
        ]
        pending_collision_raw_outputs_failure: dict[str, Any] | None = None
        if (worker_launched and not current_all_raw_outputs_valid) or len(
            final_artifact_collisions
        ) > 0:
            first_current_output_exc_type = next(
                (
                    str(item["exception_type"])
                    for item in current_missing_or_invalid_outputs
                    if item.get("exception_type") is not None
                ),
                "RuntimeError",
            )
            refreshed_raw_outputs_failure: dict[str, Any] = {
                "failed_stage": "refmac_raw_outputs",
                "exception_type": first_current_output_exc_type,
                "exception_message": (
                    "Missing, empty, unreadable, or symlinked REFMAC raw output or directory artifact(s): "
                    + ", ".join(
                        f"{item['output_key']} ({item['error']})"
                        for item in current_missing_or_invalid_outputs
                    )
                ),
                "missing_or_invalid_outputs": copy.deepcopy(
                    current_missing_or_invalid_outputs
                ),
            }
            existing_raw_failure_idx = next(
                (
                    idx
                    for idx, item in enumerate(raw_failures)
                    if item.get("failed_stage") == "refmac_raw_outputs"
                ),
                None,
            )
            if existing_raw_failure_idx is not None:
                raw_failures[existing_raw_failure_idx] = refreshed_raw_outputs_failure
            else:
                pending_collision_raw_outputs_failure = refreshed_raw_outputs_failure

        if (
            not parent_retention_dir_identity_verified
            or not parent_retention_dir_writable_post_run
        ):
            parent_exc_type = str(
                parent_retention_dir_post_run_snapshot.get("write_exception_type")
                or parent_retention_dir_post_run_snapshot.get("exception_type")
                or "ValueError"
            )
            parent_exc_msg = str(
                parent_retention_dir_post_run_snapshot.get("write_exception_message")
                or parent_retention_dir_post_run_snapshot.get("exception_message")
                or parent_retention_dir_post_run_snapshot.get("error")
                or f"Parent retention directory failed identity/writability verification: {parent_retention_dir}"
            )
            raw_failures.append(
                {
                    "failed_stage": "verify_parent_retention_directory",
                    "exception_type": parent_exc_type,
                    "exception_message": parent_exc_msg,
                    "intended_parent_retention_dir": str(parent_retention_dir),
                    "parent_retention_directory_baseline": copy.deepcopy(
                        parent_retention_dir_baseline
                    ),
                    "parent_retention_directory_post_run": copy.deepcopy(
                        parent_retention_dir_post_run_snapshot
                    ),
                    "parent_retention_fallback_anchor": copy.deepcopy(
                        verified_root_fallback_snapshot
                    ),
                }
            )
        parent_retention_used = bool(
            len(child_dir_failures_snapshot) > 0
            or not refmac_dir_identity_verified
            or not refmac_dir_writable_post_run
        )
        actual_anchor_dir, actual_anchor_kind, actual_anchor_baseline = (
            _current_actual_parent_anchor_info()
        )
        if parent_retention_used:
            first_persist_exc_type = (
                str(child_dir_failures_snapshot[0]["exception_type"])
                if child_dir_failures_snapshot
                else str(
                    refmac_dir_post_run_snapshot.get("write_exception_type")
                    or refmac_dir_post_run_snapshot.get("exception_type")
                    or "PermissionError"
                )
            )
            first_persist_exc_msg = (
                str(child_dir_failures_snapshot[0]["exception_message"])
                if child_dir_failures_snapshot
                else str(
                    refmac_dir_post_run_snapshot.get("write_exception_message")
                    or refmac_dir_post_run_snapshot.get("exception_message")
                    or refmac_dir_post_run_snapshot.get("error")
                    or f"Child refmac directory unavailable or unwritable: {refmac_dir}"
                )
            )
            if actual_anchor_dir is not None:
                retention_loc_desc = (
                    f"retained under {actual_anchor_kind} {actual_anchor_dir}"
                )
            elif publication_terminal_failure is not None:
                retention_loc_desc = (
                    "selected admitted correction directory failed during bounded pair "
                    f"publication ({publication_terminal_failure.get('exception_type')}: "
                    f"{publication_terminal_failure.get('exception_message')})"
                )
            else:
                retention_loc_desc = "no verified retention anchor available on disk"
            persist_failure_row: dict[str, Any] = {
                "failed_stage": "persist_collector_artifacts_in_refmac_dir",
                "exception_type": first_persist_exc_type,
                "exception_message": (
                    f"Unable to persist collector JSON artifacts in child refmac directory {refmac_dir} "
                    f"({first_persist_exc_type}: {first_persist_exc_msg}); "
                    f"{retention_loc_desc}"
                ),
                "parent_retention_dir": str(parent_retention_dir),
                "intended_parent_retention_dir": str(parent_retention_dir),
                "actual_parent_retention_anchor_dir": actual_anchor_dir,
                "actual_parent_retention_anchor_kind": actual_anchor_kind,
                "actual_parent_retention_anchor_baseline": copy.deepcopy(
                    actual_anchor_baseline
                ),
                "refmac_directory_post_run": copy.deepcopy(
                    refmac_dir_post_run_snapshot
                ),
                "parent_retention_directory_post_run": copy.deepcopy(
                    parent_retention_dir_post_run_snapshot
                ),
                "parent_retention_fallback_anchor": copy.deepcopy(
                    verified_root_fallback_snapshot
                ),
                "child_dir_persistence_failures": copy.deepcopy(
                    child_dir_failures_snapshot
                ),
            }
            if publication_terminal_failure is not None:
                persist_failure_row["publication_terminal_failure"] = copy.deepcopy(
                    publication_terminal_failure
                )
            raw_failures.append(persist_failure_row)
        if pending_collision_raw_outputs_failure is not None:
            raw_failures.append(pending_collision_raw_outputs_failure)
        if publication_terminal_failure is not None:
            raw_failures.append(
                {
                    "failed_stage": str(
                        publication_terminal_failure.get("stage")
                        or "bounded_pair_publication"
                    ),
                    "exception_type": str(
                        publication_terminal_failure.get("exception_type")
                        or "ValueError"
                    ),
                    "exception_message": str(
                        publication_terminal_failure.get("reason")
                        or publication_terminal_failure.get("exception_message")
                        or "Bounded pair publication terminated incomplete"
                    ),
                    "rejected_destination": publication_terminal_failure.get(
                        "rejected_destination"
                    ),
                    "publication_terminal_failure": copy.deepcopy(
                        publication_terminal_failure
                    ),
                }
            )

        if len(collision_latched_stage_prefix) > 0:
            present_stages = {
                str(item.get("failed_stage"))
                for item in raw_failures
                if item.get("failed_stage") is not None
            }
            for latched_stage in collision_latched_stage_prefix:
                if (
                    latched_stage not in present_stages
                    and latched_stage in collision_latched_stage_rows
                ):
                    raw_failures.append(
                        copy.deepcopy(collision_latched_stage_rows[latched_stage])
                    )
                    present_stages.add(latched_stage)
            prefix_rank = {
                stage_name: idx
                for idx, stage_name in enumerate(collision_latched_stage_prefix)
            }
            prefix_len = len(collision_latched_stage_prefix)
            failures: list[dict[str, Any]] = [
                item
                for _, item in sorted(
                    enumerate(raw_failures),
                    key=lambda pair: (
                        prefix_rank.get(
                            str(pair[1].get("failed_stage")), prefix_len
                        ),
                        pair[0],
                    ),
                )
            ]
        else:
            failures = raw_failures

        stage1_collection_succeeded = (
            preflight_error is None
            and process_returncode_zero
            and current_all_raw_outputs_valid
            and native_r_pair_parsed
            and bool(ncyc_zero_check["passed"])
            and input_immutability_verified
            and pre_execution_checkpoint_verified
            and refmac_dir_identity_verified
            and refmac_dir_writable_post_run
            and parent_retention_dir_identity_verified
            and parent_retention_dir_writable_post_run
            and not parent_retention_used
        )
        stage2_audits_succeeded = bool(
            xmlout_audit["valid"]
            and hklout_audit["valid"]
            and xyzout_audit["valid"]
            and len(caught_audit_exceptions) == 0
            and len(caught_inspection_exceptions) == 0
            and len(caught_persistence_exceptions) == 0
        )
        collector_succeeded = (
            len(failures) == 0
            and stage1_collection_succeeded
            and stage2_audits_succeeded
            and publication_pair_complete
            and publication_terminal_failure is None
        )

        primary_failed_stage = (
            failures[0]["failed_stage"] if failures else None
        )
        primary_failure_message = (
            str(failures[0].get("exception_message") or "").strip()
            if failures
            else ""
        )

        def _select_unproven_reason(
            *,
            public_proven: bool,
            audit_proven: bool,
            raw_audit_reason: Any,
            proof_name: str,
        ) -> str | None:
            if public_proven:
                return None
            audit_reason_str = (
                raw_audit_reason.strip()
                if isinstance(raw_audit_reason, str)
                else ""
            )
            if audit_reason_str and audit_reason_str.lower() != "none":
                return audit_reason_str
            if not collector_succeeded:
                stage_desc = (
                    f" at stage {primary_failed_stage}"
                    if primary_failed_stage is not None
                    else ""
                )
                detail_desc = (
                    f" ({primary_failure_message})"
                    if primary_failure_message
                    else ""
                )
                if audit_proven:
                    return (
                        f"{proof_name} audit check passed, but public proof is "
                        f"gated false by collector/publication failure{stage_desc}{detail_desc}"
                    )
                return (
                    f"{proof_name} is unproven and collector/publication "
                    f"failed{stage_desc}{detail_desc}"
                )
            return f"{proof_name} is unproven without a substantive audit reason"

        effective_hkls_proven = bool(
            collector_succeeded and hklout_audit["effective_hkls_proven"]
        )
        effective_hkls_unproven_reason = _select_unproven_reason(
            public_proven=effective_hkls_proven,
            audit_proven=bool(hklout_audit["effective_hkls_proven"]),
            raw_audit_reason=hklout_audit.get("effective_hkls_unproven_reason"),
            proof_name="effective_hkls_proven",
        )
        native_bin_membership_proven = bool(
            collector_succeeded and hklout_audit["native_bin_membership_proven"]
        )
        native_bin_membership_unproven_reason = _select_unproven_reason(
            public_proven=native_bin_membership_proven,
            audit_proven=bool(hklout_audit["native_bin_membership_proven"]),
            raw_audit_reason=hklout_audit.get("native_bin_membership_unproven_reason"),
            proof_name="native_bin_membership_proven",
        )
        native_residual_reconstruction_proven = bool(
            collector_succeeded
            and hklout_audit["native_residual_reconstruction_proven"]
        )
        native_residual_reconstruction_unproven_reason = _select_unproven_reason(
            public_proven=native_residual_reconstruction_proven,
            audit_proven=bool(hklout_audit["native_residual_reconstruction_proven"]),
            raw_audit_reason=hklout_audit.get(
                "native_residual_reconstruction_unproven_reason"
            ),
            proof_name="native_residual_reconstruction_proven",
        )
        model_preservation_proven = bool(
            collector_succeeded and xyzout_audit["model_preservation_proven"]
        )
        model_preservation_unproven_reason = _select_unproven_reason(
            public_proven=model_preservation_proven,
            audit_proven=bool(xyzout_audit["model_preservation_proven"]),
            raw_audit_reason=xyzout_audit.get("model_preservation_unproven_reason"),
            proof_name="model_preservation_proven",
        )

        preregistered_gates: dict[str, Any] = {
            "gate_1_immutable_input_and_toolchain_admission": {
                "proven": bool(
                    preflight_error is None
                    and process_returncode_zero
                    and bool(ncyc_zero_check["passed"])
                    and input_immutability_verified
                    and pre_execution_checkpoint_verified
                    and refmac_dir_identity_verified
                    and refmac_dir_writable_post_run
                    and parent_retention_dir_identity_verified
                    and parent_retention_dir_writable_post_run
                ),
                "reason": (
                    None
                    if (
                        preflight_error is None
                        and process_returncode_zero
                        and bool(ncyc_zero_check["passed"])
                        and input_immutability_verified
                        and pre_execution_checkpoint_verified
                        and refmac_dir_identity_verified
                        and refmac_dir_writable_post_run
                        and parent_retention_dir_identity_verified
                        and parent_retention_dir_writable_post_run
                    )
                    else "Preflight, returncode, NCYC 0, or input/checkpoint/directory immutability check failed"
                ),
            },
            "gate_2_native_log_extraction_and_internal_reconciliation": {
                "proven": bool(
                    native_r_pair_parsed
                    and ncyc_zero_check["passed"]
                    and xmlout_audit["valid"]
                ),
                "scope_note": (
                    "Establishes native log parsing, internal table reconciliation, and "
                    "non-contradiction with optional XMLOUT only; does not establish "
                    "scientific admission."
                ),
                "xmlout_status": xmlout_audit["status"],
                "xmlout_reconciled_with_log": xmlout_audit["reconciled_with_log"],
                "xmlout_cycle_association_proven": bool(
                    xmlout_audit.get("cycle_association_proven", False)
                ),
                "xmlout_precision_association_proven": bool(
                    xmlout_audit.get("precision_association_proven", False)
                ),
                "reason": (
                    None
                    if (
                        native_r_pair_parsed
                        and ncyc_zero_check["passed"]
                        and xmlout_audit["valid"]
                    )
                    else "Native log parsing, NCYC 0 verification, or XMLOUT audit failed"
                ),
            },
            "gate_3_effective_hkls_proven": {
                "proven": effective_hkls_proven,
                "status": "proven" if effective_hkls_proven else "unproven",
                "reason": effective_hkls_unproven_reason,
            },
            "gate_4_native_bin_membership_proven": {
                "proven": native_bin_membership_proven,
                "status": "proven" if native_bin_membership_proven else "unproven",
                "reason": native_bin_membership_unproven_reason,
            },
            "gate_5_native_residual_reconstruction_proven": {
                "proven": native_residual_reconstruction_proven,
                "status": (
                    "proven" if native_residual_reconstruction_proven else "unproven"
                ),
                "reason": native_residual_reconstruction_unproven_reason,
            },
            "gate_6_model_preservation_proven": {
                "proven": model_preservation_proven,
                "status": "proven" if model_preservation_proven else "unproven",
                "reason": model_preservation_unproven_reason,
            },
        }
        all_preregistered_gates_passed = bool(
            collector_succeeded
            and all(bool(g["proven"]) for g in preregistered_gates.values())
        )

        if not collector_succeeded:
            operation_status = "failed"
        elif all_preregistered_gates_passed:
            operation_status = "diagnostic_captured_all_gates_proven"
        else:
            operation_status = "diagnostic_captured_gates_unproven"

        operation_checks: dict[str, Any] = {
            "preflight_toolchain_resolved": preflight_error is None,
            "worker_launched": worker_launched,
            "process_returncode_zero": process_returncode_zero,
            "completed_argv_available": completed_argv_available,
            "argv_matches_expected": argv_matches_expected,
            "pre_execution_checkpoint_verified": pre_execution_checkpoint_verified,
            "refmac_dir_identity_verified": refmac_dir_identity_verified,
            "refmac_dir_writable_post_run": refmac_dir_writable_post_run,
            "parent_retention_dir_identity_verified": parent_retention_dir_identity_verified,
            "parent_retention_dir_writable_post_run": parent_retention_dir_writable_post_run,
            "parent_retention_used": parent_retention_used,
            "all_raw_outputs_present_and_regular": current_all_raw_outputs_valid,
            "native_r_pair_parsed": native_r_pair_parsed,
            "native_r_pair_parsed_scope_note": (
                "native_r_pair_parsed establishes log extraction and internal "
                "table/detail/final-results reconciliation only, never process "
                "success or scientific admission."
            ),
            "ncyc_zero_requested_and_echoed": bool(ncyc_zero_check["passed"]),
            "ncyc_zero_verification": ncyc_zero_check,
            "xmlout_audit_valid": bool(xmlout_audit["valid"]),
            "xmlout_audit_status": xmlout_audit["status"],
            "hklout_audit_valid": bool(hklout_audit["valid"]),
            "hklout_audit_status": hklout_audit["status"],
            "xyzout_audit_valid": bool(xyzout_audit["valid"]),
            "xyzout_audit_status": xyzout_audit["status"],
            "input_immutability_verified": input_immutability_verified,
            "stage1_collection_succeeded": stage1_collection_succeeded,
            "stage2_audits_succeeded": stage2_audits_succeeded,
            "collector_succeeded": collector_succeeded,
        }

        return {
            "status": operation_status,
            "failed_stage": primary_failed_stage,
            "failures": failures,
            "actual_parent_retention_anchor_dir": actual_anchor_dir,
            "actual_parent_retention_anchor_kind": actual_anchor_kind,
            "actual_parent_retention_anchor_baseline": actual_anchor_baseline,
            "parent_retention_used": parent_retention_used,
            "refmac_directory_post_run": refmac_dir_post_run_snapshot,
            "parent_retention_directory_post_run": (
                parent_retention_dir_post_run_snapshot
            ),
            "parent_retention_fallback_anchor": verified_root_fallback_snapshot,
            "child_dir_persistence_failures": child_dir_failures_snapshot,
            "publication_history": copy.deepcopy(publication_history),
            "publication_pair_complete": publication_pair_complete,
            "publication_terminal_failure": copy.deepcopy(publication_terminal_failure),
            "operation_checks": operation_checks,
            "input_immutability": immutability_snapshot,
            "effective_hkls_proven": effective_hkls_proven,
            "effective_hkls_unproven_reason": effective_hkls_unproven_reason,
            "native_bin_membership_proven": native_bin_membership_proven,
            "native_bin_membership_unproven_reason": (
                native_bin_membership_unproven_reason
            ),
            "native_residual_reconstruction_proven": (
                native_residual_reconstruction_proven
            ),
            "native_residual_reconstruction_unproven_reason": (
                native_residual_reconstruction_unproven_reason
            ),
            "model_preservation_proven": model_preservation_proven,
            "model_preservation_unproven_reason": model_preservation_unproven_reason,
            "preregistered_gates": preregistered_gates,
            "all_preregistered_gates_passed": all_preregistered_gates_passed,
            "collector_succeeded": collector_succeeded,
        }

    pair_child_route_resolved = False
    in_initial_d0_publication = True

    def _build_diagnostics_payload(
        selected_destination: Path | None,
    ) -> dict[str, Any]:
        nonlocal pair_child_route_resolved
        child_route_unusable_for_pair = bool(
            (
                selected_destination is not None
                and selected_destination.parent != refmac_dir
            )
            or len(child_dir_persistence_failures) > 0
            or not bool(refmac_dir_post_run.get("identity_verified", True))
            or not bool(refmac_dir_post_run.get("writable_post_run", True))
        )
        if (
            in_initial_d0_publication
            and child_route_unusable_for_pair
            and not pair_child_route_resolved
        ):
            pair_child_route_resolved = True
            if not any(
                item.get("intended_path") == str(manifest_json_path)
                for item in child_dir_persistence_failures
            ):
                prior_child_failure = (
                    child_dir_persistence_failures[-1]
                    if child_dir_persistence_failures
                    else {}
                )
                child_exc_type = str(
                    prior_child_failure.get("exception_type")
                    or refmac_dir_post_run.get("write_exception_type")
                    or refmac_dir_post_run.get("exception_type")
                    or "ValueError"
                )
                child_exc_msg = str(
                    prior_child_failure.get("exception_message")
                    or refmac_dir_post_run.get("write_exception_message")
                    or refmac_dir_post_run.get("exception_message")
                    or refmac_dir_post_run.get("write_error")
                    or refmac_dir_post_run.get("error")
                    or f"Child refmac directory unavailable: {refmac_dir}"
                )
                child_errno = prior_child_failure.get(
                    "errno",
                    refmac_dir_post_run.get(
                        "write_errno", refmac_dir_post_run.get("errno")
                    ),
                )
                child_dir_persistence_failures.append(
                    {
                        "intended_path": str(manifest_json_path),
                        "artifact_name": manifest_json_path.name,
                        "exception_type": child_exc_type,
                        "exception_message": child_exc_msg,
                        "errno": child_errno,
                        "attempted_write_in_child_dir": False,
                    }
                )
                child_dir_persistence_causes.append(
                    child_dir_persistence_causes[0]
                    if child_dir_persistence_causes
                    else None
                )
        _record_final_artifact_collision_if_any(
            "diagnostics_json",
            active_diagnostics_canonical_name,
            selected_destination,
        )
        outcome = _derive_final_collection_outcome()
        return {
            "schema_version": 1,
            "collector_stage": COLLECTOR_STAGE,
            "status": outcome["status"],
            "failed_stage": outcome["failed_stage"],
            "failures": outcome["failures"],
            "subject_id": subject_id,
            "evidence_root": str(fresh_root),
            "inputs_dir": str(inputs_dir),
            "refmac_dir": str(refmac_dir),
            "parent_retention_dir": str(parent_retention_dir),
            "intended_parent_retention_dir": str(parent_retention_dir),
            "actual_parent_retention_anchor_dir": outcome[
                "actual_parent_retention_anchor_dir"
            ],
            "actual_parent_retention_anchor_kind": outcome[
                "actual_parent_retention_anchor_kind"
            ],
            "actual_parent_retention_anchor_baseline": outcome[
                "actual_parent_retention_anchor_baseline"
            ],
            "parent_retention_used": outcome["parent_retention_used"],
            "refmac_directory_baseline": copy.deepcopy(refmac_dir_baseline),
            "refmac_directory_post_run": outcome["refmac_directory_post_run"],
            "parent_retention_directory_baseline": copy.deepcopy(
                parent_retention_dir_baseline
            ),
            "parent_retention_directory_post_run": outcome[
                "parent_retention_directory_post_run"
            ],
            "parent_retention_fallback_anchor": outcome[
                "parent_retention_fallback_anchor"
            ],
            "child_dir_persistence_failures": outcome[
                "child_dir_persistence_failures"
            ],
            "publication_history": outcome["publication_history"],
            "publication_pair_complete": outcome["publication_pair_complete"],
            "publication_terminal_failure": outcome["publication_terminal_failure"],
            "subject": admission_record["subject"],
            "mtz": admission_record["mtz"],
            "toolchain": toolchain_record,
            "invocation": invocation_record,
            "pre_execution_checkpoint_json": pre_execution_checkpoint_artifact,
            "pre_execution_checkpoint_initial_json": pre_execution_checkpoint_initial_artifact,
            "pre_execution_checkpoint_post_run": pre_checkpoint_post_run,
            "pre_execution_checkpoint_recovery_json": pre_execution_checkpoint_recovery_artifact,
            "pre_execution_checkpoint_verified": pre_execution_checkpoint_verified,
            "post_execution_checkpoint_json": post_execution_checkpoint_artifact,
            "parsed_log_json": parsed_log_artifact,
            "xmlout_audit_json": xmlout_audit_artifact,
            "hklout_raw_export_json": hklout_raw_export_artifact,
            "hklout_audit_json": hklout_audit_artifact,
            "xyzout_audit_json": xyzout_audit_artifact,
            "raw_outputs": raw_outputs,
            "additional_refmac_dir_files": dir_scan["additional_files"],
            "unexpected_symlinks": dir_scan["unexpected_symlinks"],
            "inspection_errors": dir_scan["inspection_errors"],
            "log_utf8_exact": log_utf8_exact,
            "native_log_diagnostics": native_log_diagnostics,
            "log_parse_error": log_parse_error,
            "operation_checks": outcome["operation_checks"],
            "input_immutability": outcome["input_immutability"],
            "audits": audits_bundle,
            "effective_hkls_proven": outcome["effective_hkls_proven"],
            "effective_hkls_unproven_reason": outcome[
                "effective_hkls_unproven_reason"
            ],
            "native_bin_membership_proven": outcome[
                "native_bin_membership_proven"
            ],
            "native_bin_membership_unproven_reason": outcome[
                "native_bin_membership_unproven_reason"
            ],
            "native_residual_reconstruction_proven": outcome[
                "native_residual_reconstruction_proven"
            ],
            "native_residual_reconstruction_unproven_reason": outcome[
                "native_residual_reconstruction_unproven_reason"
            ],
            "model_preservation_proven": outcome["model_preservation_proven"],
            "model_preservation_unproven_reason": outcome[
                "model_preservation_unproven_reason"
            ],
            "preregistered_gates": outcome["preregistered_gates"],
            "all_preregistered_gates_passed": outcome[
                "all_preregistered_gates_passed"
            ],
            "canonical_eval_qds_eligible": False,
            "eval_admission_eligible": False,
            "qds_admission_eligible": False,
            "canary_admission_eligible": False,
            "scientific_admission_proven": False,
        }

    def _build_manifest_payload(
        selected_destination: Path | None,
    ) -> dict[str, Any]:
        _record_final_artifact_collision_if_any(
            "manifest_json",
            active_manifest_canonical_name,
            selected_destination,
        )
        outcome = _derive_final_collection_outcome()
        current_diag_artifact = (
            None
            if outcome["publication_terminal_failure"] is not None
            else diagnostics_artifact
        )
        return {
            "schema_version": 1,
            "collector_stage": COLLECTOR_STAGE,
            "status": outcome["status"],
            "failed_stage": outcome["failed_stage"],
            "failures": outcome["failures"],
            "subject_id": subject_id,
            "evidence_root": str(fresh_root),
            "inputs_dir": str(inputs_dir),
            "refmac_dir": str(refmac_dir),
            "parent_retention_dir": str(parent_retention_dir),
            "intended_parent_retention_dir": str(parent_retention_dir),
            "actual_parent_retention_anchor_dir": outcome[
                "actual_parent_retention_anchor_dir"
            ],
            "actual_parent_retention_anchor_kind": outcome[
                "actual_parent_retention_anchor_kind"
            ],
            "actual_parent_retention_anchor_baseline": outcome[
                "actual_parent_retention_anchor_baseline"
            ],
            "parent_retention_used": outcome["parent_retention_used"],
            "refmac_directory_baseline": copy.deepcopy(refmac_dir_baseline),
            "refmac_directory_post_run": outcome["refmac_directory_post_run"],
            "parent_retention_directory_baseline": copy.deepcopy(
                parent_retention_dir_baseline
            ),
            "parent_retention_directory_post_run": outcome[
                "parent_retention_directory_post_run"
            ],
            "parent_retention_fallback_anchor": outcome[
                "parent_retention_fallback_anchor"
            ],
            "child_dir_persistence_failures": outcome[
                "child_dir_persistence_failures"
            ],
            "publication_history": outcome["publication_history"],
            "publication_pair_complete": outcome["publication_pair_complete"],
            "publication_terminal_failure": outcome["publication_terminal_failure"],
            "subject": admission_record["subject"],
            "mtz": admission_record["mtz"],
            "staged_files": admission_record["staged_files"],
            "input_admission_json_path": str(admission_json_path),
            "input_admission_json_sha256": staged_input_baseline[
                "input_admission_json"
            ]["sha256"],
            "input_hkl_ledger_json_path": str(input_ledger_path),
            "input_hkl_ledger_json_sha256": staged_input_baseline[
                "input_hkl_ledger_json"
            ]["sha256"],
            "helper_sources": helper_source_baseline,
            "toolchain": toolchain_record,
            "invocation": invocation_record,
            "paths": {
                "original_pdb_path": str(original_pdb_path),
                "original_mtz_path": str(original_mtz_path),
                "projected_mtz_path": str(projected_mtz_path),
                "input_ledger_path": str(input_ledger_path),
                "admission_json_path": str(admission_json_path),
                "keywords_path": str(keywords_path),
                "parent_retention_dir": str(parent_retention_dir),
                "intended_parent_retention_dir": str(parent_retention_dir),
                "actual_parent_retention_anchor_dir": outcome[
                    "actual_parent_retention_anchor_dir"
                ],
                "pre_execution_checkpoint_json_path": (
                    str(pre_execution_checkpoint_artifact["path"])
                    if isinstance(pre_execution_checkpoint_artifact.get("path"), str)
                    else None
                ),
                "pre_execution_checkpoint_initial_json_path": str(
                    pre_execution_checkpoint_initial_artifact["path"]
                ),
                "pre_execution_checkpoint_recovery_json_path": (
                    str(pre_execution_checkpoint_recovery_artifact["path"])
                    if pre_execution_checkpoint_recovery_artifact is not None
                    and isinstance(
                        pre_execution_checkpoint_recovery_artifact.get("path"), str
                    )
                    else None
                ),
                "post_execution_checkpoint_json_path": (
                    str(post_execution_checkpoint_artifact["path"])
                    if isinstance(post_execution_checkpoint_artifact.get("path"), str)
                    else None
                ),
                "log_path": str(log_path),
                "xyzout_path": str(xyzout_path),
                "hklout_path": str(hklout_path),
                "xmlout_path": str(xmlout_path),
                "parsed_log_json_path": (
                    str(parsed_log_artifact["path"])
                    if parsed_log_artifact is not None
                    and isinstance(parsed_log_artifact.get("path"), str)
                    else None
                ),
                "xmlout_audit_json_path": (
                    str(xmlout_audit_artifact["path"])
                    if isinstance(xmlout_audit_artifact.get("path"), str)
                    else None
                ),
                "hklout_raw_export_json_path": (
                    str(hklout_raw_export_artifact["path"])
                    if isinstance(hklout_raw_export_artifact.get("path"), str)
                    else None
                ),
                "hklout_audit_json_path": (
                    str(hklout_audit_artifact["path"])
                    if isinstance(hklout_audit_artifact.get("path"), str)
                    else None
                ),
                "xyzout_audit_json_path": (
                    str(xyzout_audit_artifact["path"])
                    if isinstance(xyzout_audit_artifact.get("path"), str)
                    else None
                ),
                "diagnostics_json_path": (
                    str(current_diag_artifact["path"])
                    if isinstance(current_diag_artifact, Mapping)
                    and isinstance(current_diag_artifact.get("path"), str)
                    else None
                ),
                "manifest_json_path": (
                    str(selected_destination)
                    if selected_destination is not None
                    and outcome["publication_terminal_failure"] is None
                    else None
                ),
            },
            "raw_outputs": raw_outputs,
            "additional_refmac_dir_files": dir_scan["additional_files"],
            "unexpected_symlinks": dir_scan["unexpected_symlinks"],
            "inspection_errors": dir_scan["inspection_errors"],
            "pre_execution_checkpoint_json": pre_execution_checkpoint_artifact,
            "pre_execution_checkpoint_initial_json": pre_execution_checkpoint_initial_artifact,
            "pre_execution_checkpoint_post_run": pre_checkpoint_post_run,
            "pre_execution_checkpoint_recovery_json": pre_execution_checkpoint_recovery_artifact,
            "pre_execution_checkpoint_verified": pre_execution_checkpoint_verified,
            "post_execution_checkpoint_json": post_execution_checkpoint_artifact,
            "parsed_log_json": parsed_log_artifact,
            "xmlout_audit_json": xmlout_audit_artifact,
            "hklout_raw_export_json": hklout_raw_export_artifact,
            "hklout_audit_json": hklout_audit_artifact,
            "xyzout_audit_json": xyzout_audit_artifact,
            "diagnostics_json": current_diag_artifact,
            "native_log_diagnostics": native_log_diagnostics,
            "parsed_log": parsed_log,
            "operation_checks": outcome["operation_checks"],
            "input_immutability": outcome["input_immutability"],
            "audits": audits_bundle,
            "effective_hkls_proven": outcome["effective_hkls_proven"],
            "effective_hkls_unproven_reason": outcome[
                "effective_hkls_unproven_reason"
            ],
            "native_bin_membership_proven": outcome[
                "native_bin_membership_proven"
            ],
            "native_bin_membership_unproven_reason": outcome[
                "native_bin_membership_unproven_reason"
            ],
            "native_residual_reconstruction_proven": outcome[
                "native_residual_reconstruction_proven"
            ],
            "native_residual_reconstruction_unproven_reason": outcome[
                "native_residual_reconstruction_unproven_reason"
            ],
            "model_preservation_proven": outcome["model_preservation_proven"],
            "model_preservation_unproven_reason": outcome[
                "model_preservation_unproven_reason"
            ],
            "preregistered_gates": outcome["preregistered_gates"],
            "all_preregistered_gates_passed": outcome[
                "all_preregistered_gates_passed"
            ],
            "canonical_eval_qds_eligible": False,
            "eval_admission_eligible": False,
            "qds_admission_eligible": False,
            "canary_admission_eligible": False,
            "scientific_admission_proven": False,
        }

    def _verify_saved_snapshot_on_disk(
        artifact_record: Mapping[str, Any] | None,
        *,
        snapshot_id: str,
        artifact_kind: str,
        admitted_roots: tuple[Path, ...],
        superseded_reason: str,
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "role": snapshot_id,
            "snapshot_id": snapshot_id,
            "artifact_kind": artifact_kind,
            "path": (
                str(artifact_record.get("path"))
                if isinstance(artifact_record, Mapping)
                and isinstance(artifact_record.get("path"), str)
                else None
            ),
            "sha256": (
                str(artifact_record.get("sha256"))
                if isinstance(artifact_record, Mapping)
                and isinstance(artifact_record.get("sha256"), str)
                else None
            ),
            "size_bytes": (
                int(artifact_record["size_bytes"])
                if isinstance(artifact_record, Mapping)
                and isinstance(artifact_record.get("size_bytes"), int)
                else None
            ),
            "verified_on_disk": False,
            "verification_error": None,
            "superseded_reason": superseded_reason,
        }
        if not isinstance(artifact_record, Mapping) or not isinstance(
            artifact_record.get("path"), str
        ):
            entry["verification_error"] = "Historical snapshot was not persisted to disk."
            return entry
        disk_path = Path(str(artifact_record["path"]))
        matched_root: Path | None = None
        for candidate_root in admitted_roots:
            try:
                disk_path.relative_to(candidate_root)
                matched_root = candidate_root
                break
            except ValueError:
                continue
        try:
            if matched_root is None:
                raise ValueError(
                    f"Historical snapshot {disk_path} is not under any admitted directory"
                )
            _ensure_no_symlink_components_under_root(
                disk_path, matched_root, check_leaf=True
            )
            st_disk = os.lstat(disk_path)
            if not stat.S_ISREG(st_disk.st_mode):
                raise ValueError(
                    f"Historical snapshot is not a regular file: {disk_path}"
                )
            observed_sha = _sha256_regular_file(disk_path)
            observed_size = int(st_disk.st_size)
            if entry["sha256"] is not None and observed_sha != entry["sha256"]:
                raise ValueError(
                    f"Historical snapshot sha256 mismatch at {disk_path}: "
                    f"expected {entry['sha256']}, observed {observed_sha}"
                )
            if (
                entry["size_bytes"] is not None
                and observed_size != entry["size_bytes"]
            ):
                raise ValueError(
                    f"Historical snapshot size_bytes mismatch at {disk_path}: "
                    f"expected {entry['size_bytes']}, observed {observed_size}"
                )
            entry["sha256"] = observed_sha
            entry["size_bytes"] = observed_size
            entry["verified_on_disk"] = True
        except Exception as exc:
            entry["verified_on_disk"] = False
            entry["verification_error"] = f"{type(exc).__name__}: {exc}"
        return entry

    def _write_to_selected_admitted_directory(
        payload_builder: Callable[[Path | None], dict[str, Any]],
        target_path: Path,
        *,
        retained_sink: list[dict[str, Any]],
    ) -> dict[str, Any]:
        target_dir = target_path.parent
        verified_anchor_dir_str = verified_root_fallback_state.get("actual_anchor_dir")
        verified_anchor_baseline = verified_root_fallback_state.get("actual_anchor_baseline")

        def _refresh_selected_child_dir_status() -> tuple[dict[str, Any], list[Exception]]:
            nonlocal refmac_dir_initial_cause
            live_refmac_causes: list[Exception] = []
            live_refmac = _verify_refmac_directory_post_run(
                refmac_dir,
                refmac_dir_baseline=refmac_dir_baseline,
                caught_exceptions=live_refmac_causes,
            )
            if live_refmac_causes:
                caught_persistence_exceptions.extend(live_refmac_causes)
                if refmac_dir_initial_cause is None:
                    refmac_dir_initial_cause = live_refmac_causes[0]
            prev_child_writable = refmac_dir_post_run.get("writable_post_run", True)
            prev_child_write_err = refmac_dir_post_run.get("write_error")
            prev_child_write_exc_type = refmac_dir_post_run.get("write_exception_type")
            prev_child_write_exc_msg = refmac_dir_post_run.get("write_exception_message")
            prev_child_write_errno = refmac_dir_post_run.get("write_errno")
            refmac_dir_post_run.clear()
            refmac_dir_post_run.update(live_refmac)
            if not prev_child_writable and prev_child_write_err is not None:
                refmac_dir_post_run["writable_post_run"] = False
                refmac_dir_post_run["write_error"] = prev_child_write_err
                refmac_dir_post_run["write_exception_type"] = prev_child_write_exc_type
                refmac_dir_post_run["write_exception_message"] = prev_child_write_exc_msg
                refmac_dir_post_run["write_errno"] = prev_child_write_errno
            return live_refmac, live_refmac_causes

        if target_dir == refmac_dir:
            live_refmac, live_refmac_causes = _refresh_selected_child_dir_status()
            if not bool(live_refmac.get("identity_verified", False)):
                if live_refmac_causes:
                    raise live_refmac_causes[0]
                raise ValueError(
                    str(
                        live_refmac.get("error")
                        or f"Child refmac directory identity verification failed: {refmac_dir}"
                    )
                )
            if not bool(refmac_dir_post_run.get("writable_post_run", True)):
                if (
                    child_dir_persistence_causes
                    and child_dir_persistence_causes[0] is not None
                ):
                    raise child_dir_persistence_causes[0]
                raise PermissionError(
                    str(
                        refmac_dir_post_run.get("write_error")
                        or refmac_dir_post_run.get("error")
                        or f"Child refmac directory is not writable: {refmac_dir}"
                    )
                )
        elif target_dir == parent_retention_dir:
            live_parent_causes: list[Exception] = []
            live_parent = _verify_refmac_directory_post_run(
                parent_retention_dir,
                refmac_dir_baseline=parent_retention_dir_baseline,
                caught_exceptions=live_parent_causes,
            )
            if live_parent_causes:
                caught_persistence_exceptions.extend(live_parent_causes)
            prev_writable = parent_retention_dir_post_run.get("writable_post_run", True)
            prev_write_err = parent_retention_dir_post_run.get("write_error")
            prev_write_exc_type = parent_retention_dir_post_run.get("write_exception_type")
            prev_write_exc_msg = parent_retention_dir_post_run.get("write_exception_message")
            prev_write_errno = parent_retention_dir_post_run.get("write_errno")
            parent_retention_dir_post_run.clear()
            parent_retention_dir_post_run.update(live_parent)
            if not prev_writable and prev_write_err is not None:
                parent_retention_dir_post_run["writable_post_run"] = False
                parent_retention_dir_post_run["write_error"] = prev_write_err
                parent_retention_dir_post_run["write_exception_type"] = prev_write_exc_type
                parent_retention_dir_post_run["write_exception_message"] = prev_write_exc_msg
                parent_retention_dir_post_run["write_errno"] = prev_write_errno
            else:
                parent_retention_dir_cause_holder.clear()
                parent_retention_dir_cause_holder.append(
                    live_parent_causes[0] if live_parent_causes else None
                )
            if not bool(live_parent.get("identity_verified", False)):
                if live_parent_causes:
                    raise live_parent_causes[0]
                raise ValueError(
                    str(
                        live_parent.get("error")
                        or f"Parent retention directory identity verification failed: {parent_retention_dir}"
                    )
                )
            if not bool(parent_retention_dir_post_run.get("writable_post_run", True)):
                if (
                    parent_retention_dir_cause_holder
                    and parent_retention_dir_cause_holder[0] is not None
                ):
                    raise parent_retention_dir_cause_holder[0]
                raise PermissionError(
                    str(
                        parent_retention_dir_post_run.get("write_error")
                        or parent_retention_dir_post_run.get("error")
                        or f"Parent retention directory is not writable: {parent_retention_dir}"
                    )
                )
        elif (
            isinstance(verified_anchor_dir_str, str)
            and target_dir == Path(verified_anchor_dir_str)
            and isinstance(verified_anchor_baseline, Mapping)
        ):
            live_anchor_causes: list[Exception] = []
            live_anchor = _verify_refmac_directory_post_run(
                target_dir,
                refmac_dir_baseline=verified_anchor_baseline,
                caught_exceptions=live_anchor_causes,
            )
            if not bool(live_anchor.get("identity_verified", False)):
                if live_anchor_causes:
                    caught_persistence_exceptions.extend(live_anchor_causes)
                    raise live_anchor_causes[0]
                raise ValueError(
                    str(
                        live_anchor.get("error")
                        or f"Verified evidence_root fallback directory identity verification failed: {target_dir}"
                    )
                )
        else:
            raise ValueError(
                f"Target directory is not a verified admitted retention directory: {target_dir}"
            )

        def _factory(dest: Path) -> Mapping[str, Any]:
            if target_dir == refmac_dir:
                try:
                    cur_child_mode = stat.S_IMODE(os.lstat(refmac_dir).st_mode)
                except OSError:
                    cur_child_mode = None
                if (
                    cur_child_mode is not None
                    and cur_child_mode != refmac_dir_post_run.get("mode")
                ):
                    _refresh_selected_child_dir_status()
            materialized = payload_builder(dest)
            if (
                isinstance(verified_anchor_dir_str, str)
                and target_dir == Path(verified_anchor_dir_str)
                and isinstance(verified_anchor_baseline, Mapping)
            ):
                patched_payload = dict(materialized)
                patched_payload["intended_parent_retention_dir"] = str(parent_retention_dir)
                patched_payload["actual_parent_retention_anchor_dir"] = str(target_dir)
                patched_payload["actual_parent_retention_anchor_kind"] = (
                    "verified_evidence_root_exclusive_dir"
                )
                patched_payload["actual_parent_retention_anchor_baseline"] = copy.deepcopy(
                    dict(verified_anchor_baseline)
                )
                patched_payload["parent_retention_directory_post_run"] = copy.deepcopy(
                    parent_retention_dir_post_run
                )
                patched_payload["parent_retention_fallback_anchor"] = copy.deepcopy(
                    verified_root_fallback_state
                )
                if isinstance(patched_payload.get("paths"), Mapping):
                    patched_paths = dict(patched_payload["paths"])
                    patched_paths["intended_parent_retention_dir"] = str(parent_retention_dir)
                    patched_paths["actual_parent_retention_anchor_dir"] = str(target_dir)
                    patched_paths["actual_parent_retention_anchor_kind"] = (
                        "verified_evidence_root_exclusive_dir"
                    )
                    patched_paths["parent_retention_dir"] = str(target_dir)
                    patched_payload["paths"] = patched_paths
                materialized = patched_payload
            retained_sink.clear()
            retained_sink.append(copy.deepcopy(materialized))
            return materialized

        try:
            written = _write_json_with_sibling_collision_fallback(
                _factory,
                target_path,
                root=target_dir,
            )
        except (OSError, ValueError) as exc:
            caught_persistence_exceptions.append(exc)
            if target_dir == parent_retention_dir:
                err_str = f"{type(exc).__name__}: {exc}"
                parent_retention_dir_post_run["writable_post_run"] = False
                parent_retention_dir_post_run["write_error"] = err_str
                parent_retention_dir_post_run["write_exception_type"] = type(exc).__name__
                parent_retention_dir_post_run["write_exception_message"] = str(exc)
                parent_retention_dir_post_run["write_errno"] = getattr(exc, "errno", None)
                parent_retention_dir_cause_holder.clear()
                parent_retention_dir_cause_holder.append(exc)
            elif target_dir == refmac_dir:
                err_str = f"{type(exc).__name__}: {exc}"
                refmac_dir_post_run["writable_post_run"] = False
                refmac_dir_post_run["write_error"] = err_str
                refmac_dir_post_run["write_exception_type"] = type(exc).__name__
                refmac_dir_post_run["write_exception_message"] = str(exc)
                refmac_dir_post_run["write_errno"] = getattr(exc, "errno", None)
                _refresh_selected_child_dir_status()
            raise
        if target_dir == parent_retention_dir:
            written["fallback_for_unwritable_or_damaged_child_dir"] = True
            written["intended_child_dir_path"] = str(refmac_dir / target_path.name)
            written["intended_parent_retention_dir"] = str(parent_retention_dir)
            written["parent_retention_dir"] = str(parent_retention_dir)
            written["actual_retention_anchor_dir"] = str(parent_retention_dir)
            written["actual_retention_anchor_kind"] = "parent_retention_dir"
        elif (
            isinstance(verified_anchor_dir_str, str)
            and target_dir == Path(verified_anchor_dir_str)
            and isinstance(verified_anchor_baseline, Mapping)
        ):
            written["fallback_for_unwritable_or_damaged_child_dir"] = True
            written["fallback_for_damaged_or_replaced_parent_retention_dir"] = True
            written["intended_child_dir_path"] = str(refmac_dir / target_path.name)
            written["intended_parent_retention_dir"] = str(parent_retention_dir)
            written["parent_retention_dir"] = str(target_dir)
            written["actual_retention_anchor_dir"] = str(target_dir)
            written["actual_retention_anchor_kind"] = (
                "verified_evidence_root_exclusive_dir"
            )
            written["actual_retention_anchor_baseline"] = copy.deepcopy(
                dict(verified_anchor_baseline)
            )
        return written

    retained_diagnostics_holder: list[dict[str, Any]] = []
    pre_d0_persistence_exc_len = len(caught_persistence_exceptions)
    diagnostics_artifact: dict[str, Any] | None = _persist_collector_json_with_fallback(
        _build_diagnostics_payload,
        diagnostics_json_path,
        root=refmac_dir,
        parent_retention_dir=parent_retention_dir,
        parent_retention_dir_baseline=parent_retention_dir_baseline,
        parent_retention_dir_status=parent_retention_dir_post_run,
        verified_root_fallback_state=verified_root_fallback_state,
        allow_unpersisted_on_no_verified_anchor=True,
        refmac_dir_status=refmac_dir_post_run,
        child_dir_persistence_failures=child_dir_persistence_failures,
        caught_persistence_exceptions=caught_persistence_exceptions,
        retained_payload_sink=retained_diagnostics_holder,
        child_dir_persistence_causes=child_dir_persistence_causes,
        parent_retention_dir_cause_sink=parent_retention_dir_cause_holder,
    )
    in_initial_d0_publication = False
    d0_persistence_exceptions = caught_persistence_exceptions[
        pre_d0_persistence_exc_len:
    ]
    diagnostics_payload: dict[str, Any] = (
        retained_diagnostics_holder[0]
        if retained_diagnostics_holder
        else _build_diagnostics_payload(None)
    )
    _latch_current_failure_stages()
    d0_artifact_record = copy.deepcopy(diagnostics_artifact)
    d0_outcome_fingerprint = (
        diagnostics_payload.get("status"),
        diagnostics_payload.get("failed_stage"),
        copy.deepcopy(diagnostics_payload.get("failures")),
        copy.deepcopy(diagnostics_payload.get("child_dir_persistence_failures")),
        copy.deepcopy(diagnostics_payload.get("refmac_directory_post_run")),
        copy.deepcopy(diagnostics_payload.get("parent_retention_directory_post_run")),
        diagnostics_payload.get("actual_parent_retention_anchor_dir"),
        diagnostics_payload.get("actual_parent_retention_anchor_kind"),
        diagnostics_payload.get("parent_retention_used"),
    )

    admitted_history_roots: tuple[Path, ...] = tuple(
        p
        for p in (
            refmac_dir,
            parent_retention_dir,
            (
                Path(str(verified_root_fallback_state["actual_anchor_dir"]))
                if isinstance(
                    verified_root_fallback_state.get("actual_anchor_dir"), str
                )
                else None
            ),
            fresh_root,
        )
        if p is not None
    )

    def _terminate_incomplete_publication(
        *,
        stage: str,
        reason: str,
        rejected_destination: str | None,
        exc: Exception | None,
    ) -> None:
        nonlocal publication_pair_complete, publication_terminal_failure
        nonlocal terminal_caught_exception, diagnostics_artifact, manifest_artifact
        nonlocal diagnostics_payload, manifest_payload
        _latch_current_failure_stages()
        publication_pair_complete = False
        if exc is not None:
            terminal_caught_exception = exc
        publication_terminal_failure = {
            "stage": stage,
            "reason": reason,
            "rejected_destination": rejected_destination,
            "exception_type": (
                type(exc).__name__ if exc is not None else "ValueError"
            ),
            "exception_message": str(exc) if exc is not None else reason,
            "errno": getattr(exc, "errno", None) if exc is not None else None,
        }
        verified_root_fallback_state["unpersisted_reason"] = reason
        diagnostics_artifact = None
        manifest_artifact = None
        diagnostics_payload = copy.deepcopy(_build_diagnostics_payload(None))
        manifest_payload = copy.deepcopy(_build_manifest_payload(None))

    def _run_bounded_pair_correction(
        *,
        superseded_reason: str,
        m0_artifact_record: Mapping[str, Any] | None,
    ) -> None:
        nonlocal publication_correction_count, publication_pair_complete
        nonlocal active_diagnostics_canonical_name, active_manifest_canonical_name
        nonlocal diagnostics_artifact, manifest_artifact
        nonlocal diagnostics_payload, manifest_payload
        _latch_current_failure_stages()
        d0_hist = _verify_saved_snapshot_on_disk(
            d0_artifact_record,
            snapshot_id="D0",
            artifact_kind="diagnostics_json",
            admitted_roots=admitted_history_roots,
            superseded_reason=superseded_reason,
        )
        if not any(
            item.get("snapshot_id") == "D0" for item in publication_history
        ):
            publication_history.append(d0_hist)
        if (
            isinstance(m0_artifact_record, Mapping)
            and isinstance(m0_artifact_record.get("path"), str)
            and not any(
                item.get("snapshot_id") == "M0" for item in publication_history
            )
        ):
            m0_hist = _verify_saved_snapshot_on_disk(
                m0_artifact_record,
                snapshot_id="M0",
                artifact_kind="manifest_json",
                admitted_roots=admitted_history_roots,
                superseded_reason=superseded_reason,
            )
            publication_history.append(m0_hist)
        if not bool(d0_hist.get("verified_on_disk", False)):
            _terminate_incomplete_publication(
                stage="verify_historical_d0",
                reason=(
                    f"Historical snapshot D0 failed on-disk verification before bounded "
                    f"correction: {d0_hist.get('verification_error')}"
                ),
                rejected_destination=d0_hist.get("path"),
                exc=ValueError(
                    str(
                        d0_hist.get("verification_error")
                        or "D0 verification failed"
                    )
                ),
            )
            return
        for hist_item in publication_history:
            if not bool(hist_item.get("verified_on_disk", False)):
                _terminate_incomplete_publication(
                    stage=f"verify_historical_{str(hist_item.get('snapshot_id', 'snapshot')).lower()}",
                    reason=(
                        f"Historical snapshot {hist_item.get('snapshot_id')} failed on-disk "
                        f"verification: {hist_item.get('verification_error')}"
                    ),
                    rejected_destination=hist_item.get("path"),
                    exc=ValueError(
                        str(
                            hist_item.get("verification_error")
                            or "Historical snapshot verification failed"
                        )
                    ),
                )
                return
        if publication_correction_count >= 1:
            _terminate_incomplete_publication(
                stage="bounded_pair_correction_limit",
                reason="Bounded publication correction limit (at most one correction D1/M1) exceeded.",
                rejected_destination=None,
                exc=RuntimeError("Bounded publication correction limit exceeded"),
            )
            return
        publication_correction_count += 1

        target_dir_raw = (
            m0_artifact_record.get("path")
            if isinstance(m0_artifact_record, Mapping)
            and isinstance(m0_artifact_record.get("path"), str)
            else (
                d0_artifact_record.get("path")
                if isinstance(d0_artifact_record, Mapping)
                and isinstance(d0_artifact_record.get("path"), str)
                else None
            )
        )
        if not isinstance(target_dir_raw, str):
            _terminate_incomplete_publication(
                stage="select_correction_destination",
                reason="No admitted destination directory available for bounded correction pair (D1, M1).",
                rejected_destination=None,
                exc=ValueError("No admitted destination directory available"),
            )
            return
        target_dir = Path(target_dir_raw).parent
        d1_name = "refmac_r_factor_diagnostics.corrected.json"
        m1_name = "refmac_operation_manifest.corrected.json"
        d1_target = target_dir / d1_name
        m1_target = target_dir / m1_name
        active_diagnostics_canonical_name = d1_name
        active_manifest_canonical_name = m1_name

        pre_d1_collision_count = len(final_artifact_collisions)
        retained_d1_holder: list[dict[str, Any]] = []
        try:
            d1_artifact = _write_to_selected_admitted_directory(
                _build_diagnostics_payload,
                d1_target,
                retained_sink=retained_d1_holder,
            )
        except Exception as exc:
            _terminate_incomplete_publication(
                stage="persist_corrected_diagnostics_d1",
                reason=(
                    f"Selected correction destination {target_dir} rejected or failed "
                    f"while writing D1 ({d1_name}): {type(exc).__name__}: {exc} "
                    f"(evidence_root {fresh_root} was not attempted as an unverified fallback)."
                ),
                rejected_destination=str(d1_target),
                exc=exc,
            )
            return
        if len(final_artifact_collisions) > pre_d1_collision_count:
            d1_hist = _verify_saved_snapshot_on_disk(
                d1_artifact,
                snapshot_id="D1",
                artifact_kind="diagnostics_json",
                admitted_roots=admitted_history_roots,
                superseded_reason="D1 collided during bounded correction; second correction is forbidden.",
            )
            publication_history.append(d1_hist)
            _terminate_incomplete_publication(
                stage="persist_corrected_diagnostics_d1",
                reason=(
                    f"Corrected diagnostics D1 collided at {d1_target} and was written to "
                    f"{d1_artifact.get('path')}; a second correction is forbidden."
                ),
                rejected_destination=str(d1_target),
                exc=FileExistsError(f"Collision on corrected diagnostics destination: {d1_target}"),
            )
            return

        diagnostics_artifact = d1_artifact
        diagnostics_payload = retained_d1_holder[0]
        d1_outcome_fingerprint = (
            diagnostics_payload.get("status"),
            diagnostics_payload.get("failed_stage"),
            copy.deepcopy(diagnostics_payload.get("failures")),
            copy.deepcopy(diagnostics_payload.get("child_dir_persistence_failures")),
            copy.deepcopy(diagnostics_payload.get("refmac_directory_post_run")),
            copy.deepcopy(diagnostics_payload.get("parent_retention_directory_post_run")),
            diagnostics_payload.get("actual_parent_retention_anchor_dir"),
            diagnostics_payload.get("actual_parent_retention_anchor_kind"),
            diagnostics_payload.get("parent_retention_used"),
        )

        pre_m1_collision_count = len(final_artifact_collisions)
        retained_m1_holder: list[dict[str, Any]] = []
        try:
            m1_artifact = _write_to_selected_admitted_directory(
                _build_manifest_payload,
                m1_target,
                retained_sink=retained_m1_holder,
            )
        except Exception as exc:
            d1_hist = _verify_saved_snapshot_on_disk(
                d1_artifact,
                snapshot_id="D1",
                artifact_kind="diagnostics_json",
                admitted_roots=admitted_history_roots,
                superseded_reason=(
                    f"M1 failed in {target_dir} after D1 was written; pair (D1, M1) is incomplete."
                ),
            )
            publication_history.append(d1_hist)
            _terminate_incomplete_publication(
                stage="persist_corrected_manifest_m1",
                reason=(
                    f"Selected correction destination {target_dir} rejected or failed "
                    f"while writing M1 ({m1_name}) after D1 was saved: {type(exc).__name__}: {exc} "
                    f"(evidence_root {fresh_root} was not attempted as an unverified fallback)."
                ),
                rejected_destination=str(m1_target),
                exc=exc,
            )
            return

        m1_payload = retained_m1_holder[0]
        m1_outcome_fingerprint = (
            m1_payload.get("status"),
            m1_payload.get("failed_stage"),
            copy.deepcopy(m1_payload.get("failures")),
            copy.deepcopy(m1_payload.get("child_dir_persistence_failures")),
            copy.deepcopy(m1_payload.get("refmac_directory_post_run")),
            copy.deepcopy(m1_payload.get("parent_retention_directory_post_run")),
            m1_payload.get("actual_parent_retention_anchor_dir"),
            m1_payload.get("actual_parent_retention_anchor_kind"),
            m1_payload.get("parent_retention_used"),
        )
        if (
            len(final_artifact_collisions) > pre_m1_collision_count
            or m1_outcome_fingerprint != d1_outcome_fingerprint
        ):
            d1_hist = _verify_saved_snapshot_on_disk(
                d1_artifact,
                snapshot_id="D1",
                artifact_kind="diagnostics_json",
                admitted_roots=admitted_history_roots,
                superseded_reason="M1 changed outcome or collided during bounded correction; second correction is forbidden.",
            )
            m1_hist = _verify_saved_snapshot_on_disk(
                m1_artifact,
                snapshot_id="M1",
                artifact_kind="manifest_json",
                admitted_roots=admitted_history_roots,
                superseded_reason="M1 changed outcome or collided during bounded correction; second correction is forbidden.",
            )
            publication_history.append(d1_hist)
            publication_history.append(m1_hist)
            _terminate_incomplete_publication(
                stage="persist_corrected_manifest_m1",
                reason=(
                    f"Corrected manifest M1 changed outcome or collided at {m1_target} "
                    f"(written to {m1_artifact.get('path')}); a second correction is forbidden."
                ),
                rejected_destination=str(m1_target),
                exc=FileExistsError(f"Collision or outcome drift on corrected manifest destination: {m1_target}"),
            )
            return

        manifest_artifact = m1_artifact
        manifest_payload = m1_payload
        publication_pair_complete = True

    manifest_artifact: dict[str, Any] | None = None
    manifest_payload: dict[str, Any]

    if (
        not isinstance(d0_artifact_record, Mapping)
        or not bool(d0_artifact_record.get("persisted", True))
        or not isinstance(d0_artifact_record.get("path"), str)
    ):
        d0_unpersisted_reason = str(
            (
                d0_artifact_record.get("unpersisted_reason")
                if isinstance(d0_artifact_record, Mapping)
                else None
            )
            or verified_root_fallback_state.get("unpersisted_reason")
            or "Diagnostics D0 could not be persisted in any verified retention anchor."
        )
        d0_terminal_exc: Exception | None = (
            d0_persistence_exceptions[-1]
            if d0_persistence_exceptions
            else None
        )
        _terminate_incomplete_publication(
            stage="persist_diagnostics_d0",
            reason=d0_unpersisted_reason,
            rejected_destination=str(diagnostics_json_path),
            exc=d0_terminal_exc,
        )
    elif publication_terminal_failure is None:
        d0_saved_path = Path(str(d0_artifact_record["path"]))
        d0_saved_dir = d0_saved_path.parent
        retained_manifest_holder: list[dict[str, Any]] = []
        m0_artifact: dict[str, Any] | None = None
        m0_persistence_exceptions: list[Exception] = []
        if d0_saved_dir != refmac_dir:
            m0_target_in_selected_dir = d0_saved_dir / manifest_json_path.name
            try:
                m0_artifact = _write_to_selected_admitted_directory(
                    _build_manifest_payload,
                    m0_target_in_selected_dir,
                    retained_sink=retained_manifest_holder,
                )
            except Exception as exc:
                d0_hist = _verify_saved_snapshot_on_disk(
                    d0_artifact_record,
                    snapshot_id="D0",
                    artifact_kind="diagnostics_json",
                    admitted_roots=admitted_history_roots,
                    superseded_reason=(
                        f"M0 failed in selected fallback directory {d0_saved_dir} after D0 was saved."
                    ),
                )
                publication_history.append(d0_hist)
                _terminate_incomplete_publication(
                    stage="persist_manifest_m0",
                    reason=(
                        f"Selected fallback directory {d0_saved_dir} rejected or failed "
                        f"while writing M0 ({manifest_json_path.name}) after D0 was saved: "
                        f"{type(exc).__name__}: {exc} "
                        f"(evidence_root {fresh_root} was not attempted as an unverified fallback)."
                    ),
                    rejected_destination=str(m0_target_in_selected_dir),
                    exc=exc,
                )
        else:
            pre_m0_persistence_exc_len = len(caught_persistence_exceptions)
            m0_artifact = _persist_collector_json_with_fallback(
                _build_manifest_payload,
                manifest_json_path,
                root=refmac_dir,
                parent_retention_dir=parent_retention_dir,
                parent_retention_dir_baseline=parent_retention_dir_baseline,
                parent_retention_dir_status=parent_retention_dir_post_run,
                verified_root_fallback_state=verified_root_fallback_state,
                allow_unpersisted_on_no_verified_anchor=True,
                refmac_dir_status=refmac_dir_post_run,
                child_dir_persistence_failures=child_dir_persistence_failures,
                caught_persistence_exceptions=caught_persistence_exceptions,
                retained_payload_sink=retained_manifest_holder,
                child_dir_persistence_causes=child_dir_persistence_causes,
                parent_retention_dir_cause_sink=parent_retention_dir_cause_holder,
            )
            m0_persistence_exceptions = caught_persistence_exceptions[
                pre_m0_persistence_exc_len:
            ]

        if publication_terminal_failure is None and m0_artifact is not None:
            admitted_history_roots = tuple(
                p
                for p in (
                    refmac_dir,
                    parent_retention_dir,
                    (
                        Path(str(verified_root_fallback_state["actual_anchor_dir"]))
                        if isinstance(
                            verified_root_fallback_state.get("actual_anchor_dir"), str
                        )
                        else None
                    ),
                    fresh_root,
                )
                if p is not None
            )
            if not bool(m0_artifact.get("persisted", True)) and not any(
                item.get("output_key") == "manifest_json"
                for item in final_artifact_collisions
            ):
                d0_hist = _verify_saved_snapshot_on_disk(
                    d0_artifact_record,
                    snapshot_id="D0",
                    artifact_kind="diagnostics_json",
                    admitted_roots=admitted_history_roots,
                    superseded_reason="M0 could not be persisted in any verified retention anchor after D0 was saved.",
                )
                publication_history.append(d0_hist)
                m0_reason = str(
                    m0_artifact.get("unpersisted_reason")
                    or verified_root_fallback_state.get("unpersisted_reason")
                    or "Manifest M0 could not be persisted in any verified retention anchor."
                )
                m0_terminal_exc: Exception | None = (
                    m0_persistence_exceptions[-1]
                    if m0_persistence_exceptions
                    else None
                )
                _terminate_incomplete_publication(
                    stage="persist_manifest_m0",
                    reason=m0_reason,
                    rejected_destination=str(manifest_json_path),
                    exc=m0_terminal_exc,
                )
            else:
                m0_payload = (
                    retained_manifest_holder[0]
                    if retained_manifest_holder
                    else _build_manifest_payload(None)
                )
                m0_outcome_fingerprint = (
                    m0_payload.get("status"),
                    m0_payload.get("failed_stage"),
                    copy.deepcopy(m0_payload.get("failures")),
                    copy.deepcopy(m0_payload.get("child_dir_persistence_failures")),
                    copy.deepcopy(m0_payload.get("refmac_directory_post_run")),
                    copy.deepcopy(m0_payload.get("parent_retention_directory_post_run")),
                    m0_payload.get("actual_parent_retention_anchor_dir"),
                    m0_payload.get("actual_parent_retention_anchor_kind"),
                    m0_payload.get("parent_retention_used"),
                )
                if m0_outcome_fingerprint != d0_outcome_fingerprint:
                    m0_saved_dir = (
                        Path(str(m0_artifact["path"])).parent
                        if isinstance(m0_artifact.get("path"), str)
                        else None
                    )
                    if m0_saved_dir != d0_saved_dir:
                        superseded_why = (
                            "Manifest persistence failed in refmac_dir after D0 was written "
                            "and switched to fallback retention directory."
                        )
                    else:
                        superseded_why = (
                            "Manifest persistence encountered a new failure or destination "
                            "collision after D0 was written."
                        )
                    _run_bounded_pair_correction(
                        superseded_reason=superseded_why,
                        m0_artifact_record=m0_artifact,
                    )
                else:
                    manifest_artifact = m0_artifact
                    manifest_payload = m0_payload
                    publication_pair_complete = True

    final_outcome = _derive_final_collection_outcome()
    if not bool(final_outcome["collector_succeeded"]):
        final_failures = final_outcome["failures"]
        first_failure = (
            final_failures[0]
            if final_failures
            else {
                "failed_stage": "unknown",
                "exception_type": "RuntimeError",
                "exception_message": "REFMAC collector failed",
            }
        )
        manifest_disk_path = (
            Path(manifest_artifact["path"])
            if publication_pair_complete
            and isinstance(manifest_artifact, Mapping)
            and isinstance(manifest_artifact.get("path"), str)
            else None
        )
        diagnostics_disk_path = (
            Path(diagnostics_artifact["path"])
            if publication_pair_complete
            and isinstance(diagnostics_artifact, Mapping)
            and isinstance(diagnostics_artifact.get("path"), str)
            else None
        )
        first_stage = str(first_failure.get("failed_stage"))
        if (
            collision_latched_primary_stage is not None
            and first_stage == collision_latched_primary_stage
        ):
            first_caught_exception: Exception | None = collision_latched_primary_cause
        else:
            first_caught_exception = _select_cause_for_stage(first_stage)
        err = RefmacCollectorError(
            f"REFMAC5 collector failed at {first_failure['failed_stage']} "
            f"({first_failure.get('exception_type', 'Error')}): "
            f"{first_failure.get('exception_message')}",
            failed_stage=str(first_failure["failed_stage"]),
            manifest_path=manifest_disk_path,
            diagnostics_path=diagnostics_disk_path,
            returncode=returncode,
            manifest_payload=manifest_payload,
            diagnostics_payload=diagnostics_payload,
            unpersisted_reason=verified_root_fallback_state.get("unpersisted_reason"),
            primary_cause=first_caught_exception,
            terminal_cause=terminal_caught_exception,
            publication_history=final_outcome["publication_history"],
            publication_pair_complete=bool(final_outcome["publication_pair_complete"]),
            publication_terminal_failure=final_outcome["publication_terminal_failure"],
        )
        if first_caught_exception is not None:
            raise err from first_caught_exception
        raise err from None

    result = dict(manifest_payload)
    result["manifest_json"] = manifest_artifact
    return result
