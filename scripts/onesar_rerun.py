#!/usr/bin/env python3
"""Input admission, observation-only MTZ projection, and PHENIX R-factor worker for 1SAR.

This module implements Phase 1 of the preregistered 1SAR rerun harness:
1. Exact archive and member SHA-256 admission for the four allowed trajectory
   subjects (``start``, ``R4``, ``R5``, ``R6``) and shared ``data/1sar.mtz``,
   while rejecting ``R7`` and any unlisted subject.
2. Fresh repository-local evidence-root creation that rejects symlinks and
   pre-existing directories so prior logs or outputs cannot be reused.
3. Projection of ``data/1sar.mtz`` to the six observation columns
   ``H, K, L, F-obs, SIGF-obs, R-free-flags`` while preserving all 7,248 raw
   rows, cell, symmetry, ``VALM NAN``, and exact IEEE-754 4-byte words, and
   excluding all archived model/map columns.
4. Construction of the raw and input-policy-eligible HKL ledger (where finite
   zero or negative ``F-obs`` with finite positive ``SIGF-obs`` are eligible,
   excluded padding rows with NaN ``R-free-flags`` are retained as unassigned,
   and duplicate HKLs or invalid/NaN ``R-free-flags`` on eligible observations
   fail closed).
5. Execution of the public first-block ``mmtbx.model_vs_data`` R-factor helper
   through :func:`refinement_cache.cached_phenix_operation` and full-precision
   arithmetic, HKL-set, scatterer-snapshot, and map-MTZ reconciliation.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import stat
import struct
import sys
import zipfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import onesar_phenix_measure  # noqa: E402
import refinement_cache  # noqa: E402
import toolchain  # noqa: E402
from audit_1sar_retained_evidence import (  # noqa: E402
    _mtz_headers,
    mtz_crystallographic_context,
)
from t03_reflection_retention import (  # noqa: E402
    _column_bindings,
    _require_supported_mtz,
    audit_mtz_retention,
)


REPO_ROOT = _SCRIPTS_DIR.parent

ARCHIVE_ID = "cdba2c07-daff-4f60-ae96-12452b3a5fbb"
ARCHIVE_REL_PATH = Path(
    "data/coscientists/openscientist/cdba2c07-daff-4f60-ae96-12452b3a5fbb_artifacts.zip"
)
ARCHIVE_SHA256 = "9fc5352284b7ffa7763c633a3eb4d3d0db96b8c25a1be9bcea361722d2c53054"

MTZ_MEMBER = "data/1sar.mtz"
MTZ_SHA256 = "f36d5fe685a3e524e8809d17d19ce12073acdf339eba2cfd3b0347a818850ab2"
MTZ_SUBJECT_REF = f"mtz:sha256:{MTZ_SHA256}"

OBSERVATION_LABELS: tuple[str, str, str] = ("F-obs", "SIGF-obs", "R-free-flags")
PROJECTED_MTZ_COLUMNS: tuple[str, ...] = (
    "H",
    "K",
    "L",
    "F-obs",
    "SIGF-obs",
    "R-free-flags",
)
FORBIDDEN_ARCHIVED_MTZ_COLUMNS: frozenset[str] = frozenset(
    {
        "F-obs-filtered",
        "SIGF-obs-filtered",
        "F-model",
        "PHIF-model",
        "2FOFCWT",
        "PH2FOFCWT",
        "2FOFCWT_no_fill",
        "PH2FOFCWT_no_fill",
        "FOFCWT",
        "PHFOFCWT",
    }
)

DECLARED_FLAG_VALUES: frozenset[int] = frozenset({0, 1})
WORK_FLAG_VALUE = 0
FREE_FLAG_VALUE = 1

ALLOWED_SUBJECTS: dict[str, dict[str, str]] = {
    "start": {
        "subject_id": "start",
        "stage": "start",
        "member": "data/1sar.pdb",
        "sha256": "6b34c5d0dec6647df20eae9021ff7d511d6dedc03b4349c0b634d8e5b1f869e4",
        "subject_ref": f"artifact:{ARCHIVE_ID}#data/1sar.pdb",
    },
    "R4": {
        "subject_id": "R4",
        "stage": "final",
        "member": "data/1sar_final.pdb",
        "sha256": "8cbc1650f8be5a3833f98833fa514ec7d490c2c3bb9aa930413abac05e2a510b",
        "subject_ref": f"artifact:{ARCHIVE_ID}#data/1sar_final.pdb",
    },
    "R5": {
        "subject_id": "R5",
        "stage": "intermediate",
        "member": "data/1sar_round5.pdb",
        "sha256": "25c140b46e18a1d1ec211d985868894f227c827ea0c76f7187d41e1f75c03733",
        "subject_ref": f"artifact:{ARCHIVE_ID}#data/1sar_round5.pdb",
    },
    "R6": {
        "subject_id": "R6",
        "stage": "intermediate",
        "member": "data/1sar_round6.pdb",
        "sha256": "5d01ce3645d1295a42f620987785fd8368441418e82a0b6d6992d7f79500c110",
        "subject_ref": f"artifact:{ARCHIVE_ID}#data/1sar_round6.pdb",
    },
}

FORBIDDEN_SUBJECTS: frozenset[str] = frozenset(
    {
        "R7",
        "round7",
        "1sar_round7",
        "data/1sar_round7.pdb",
        "deposited",
        "1sar_deposited",
    }
)

PHENIX_VENDOR_SOURCE_RELPATHS: dict[str, Path] = {
    "vendor_mmtbx_model_vs_data": Path("mmtbx/model_vs_data.py"),
    "vendor_iotbx_extract_xtal_data": Path("iotbx/extract_xtal_data.py"),
    "vendor_iotbx_reflection_file_utils": Path("iotbx/reflection_file_utils.py"),
    "vendor_mmtbx_f_model": Path("mmtbx/f_model/f_model.py"),
    "vendor_mmtbx_map_tools": Path("mmtbx/map_tools.py"),
    "vendor_iotbx_mtz": Path("iotbx/mtz/__init__.py"),
}


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_regular_file(path: Path) -> str:
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise ValueError(f"Regular non-symlink file required: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_subject_spec(subject_id: str) -> dict[str, str]:
    """Return a copy of the preregistered subject specification or fail closed."""
    if not isinstance(subject_id, str) or not subject_id:
        raise ValueError("subject_id must be a non-empty string")
    if subject_id in FORBIDDEN_SUBJECTS:
        raise ValueError(
            f"Subject {subject_id!r} is excluded from the 1SAR trajectory rerun contract"
        )
    if subject_id not in ALLOWED_SUBJECTS:
        allowed = ", ".join(sorted(ALLOWED_SUBJECTS))
        raise ValueError(
            f"Unknown 1SAR subject {subject_id!r}; allowed subjects are: {allowed}"
        )
    return dict(ALLOWED_SUBJECTS[subject_id])


def _validate_archive_member_name(member_name: str) -> None:
    if not isinstance(member_name, str) or not member_name:
        raise ValueError("Archive member name must be a non-empty string")
    if member_name.startswith("/") or "\\" in member_name or "\x00" in member_name:
        raise ValueError(f"Unsafe archive member path: {member_name!r}")
    parts = member_name.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"Unsafe archive member path segments: {member_name!r}")


def read_verified_archive_member(
    archive_path: Path,
    member_name: str,
    *,
    expected_archive_sha256: str = ARCHIVE_SHA256,
    expected_member_sha256: str,
) -> bytes:
    """Safely read one exact member from a hash-verified ZIP archive in memory.

    Never calls ``extractall``; rejects symlinks, missing/duplicate central-directory
    entries, directories, and archive or member SHA-256 mismatches.
    """
    _validate_archive_member_name(member_name)
    if not isinstance(expected_archive_sha256, str) or not expected_archive_sha256:
        raise ValueError("expected_archive_sha256 must be a non-empty hex digest")
    if not isinstance(expected_member_sha256, str) or not expected_member_sha256:
        raise ValueError("expected_member_sha256 must be a non-empty hex digest")

    archive_candidate = Path(archive_path)
    if not archive_candidate.exists() and not archive_candidate.is_symlink():
        raise FileNotFoundError(f"Archive not found: {archive_candidate}")
    actual_archive_sha256 = _sha256_regular_file(archive_candidate)
    if actual_archive_sha256 != expected_archive_sha256:
        raise ValueError(
            f"Archive SHA-256 mismatch for {archive_candidate}: "
            f"expected {expected_archive_sha256}, got {actual_archive_sha256}"
        )

    with zipfile.ZipFile(archive_candidate, "r") as zf:
        matches = [info for info in zf.infolist() if info.filename == member_name]
        if not matches:
            raise KeyError(
                f"Member {member_name!r} not found in archive {archive_candidate}"
            )
        if len(matches) != 1:
            raise ValueError(
                f"Archive {archive_candidate} contains {len(matches)} duplicate entries "
                f"for {member_name!r}"
            )
        info = matches[0]
        if info.is_dir():
            raise ValueError(
                f"Archive member {member_name!r} in {archive_candidate} is a directory"
            )
        unix_mode = (info.external_attr >> 16) & 0o170000
        if unix_mode == stat.S_IFLNK:
            raise ValueError(
                f"Archive member {member_name!r} in {archive_candidate} is a symlink"
            )
        data = zf.read(info.filename)

    actual_member_sha256 = _sha256_bytes(data)
    if actual_member_sha256 != expected_member_sha256:
        raise ValueError(
            f"Archive member {member_name!r} SHA-256 mismatch: "
            f"expected {expected_member_sha256}, got {actual_member_sha256}"
        )
    return data


def prepare_fresh_evidence_root(
    evidence_root: Path, *, repo_root: Path = REPO_ROOT
) -> Path:
    """Create a fresh repository-local directory, rejecting symlinks and existing paths."""
    repo_candidate = Path(repo_root)
    if repo_candidate.is_symlink():
        raise ValueError(f"Repository root must not be a symlink: {repo_candidate}")
    resolved_repo = repo_candidate.resolve(strict=True)
    if not resolved_repo.is_dir():
        raise ValueError(f"Repository root is not a directory: {resolved_repo}")

    raw_target = Path(evidence_root)
    if not raw_target.is_absolute():
        raw_target = resolved_repo / raw_target

    # Normalize lexical "." and ".." without resolving symlinks along the suffix.
    normalized_target = Path(os.path.abspath(os.fspath(raw_target)))
    if (
        normalized_target == resolved_repo
        or not normalized_target.is_relative_to(resolved_repo)
    ):
        raise ValueError(
            f"Evidence root {evidence_root} must be a strict subdirectory inside "
            f"repository root {resolved_repo}"
        )

    rel_parts = normalized_target.relative_to(resolved_repo).parts
    current = resolved_repo
    for index, part in enumerate(rel_parts):
        current = current / part
        is_last = index == len(rel_parts) - 1
        try:
            st = os.lstat(current)
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(st.st_mode):
            raise ValueError(
                f"Evidence path component must not be a symlink: {current}"
            )
        if is_last:
            raise FileExistsError(
                f"Fresh evidence root required; destination already exists: {current}"
            )
        if not stat.S_ISDIR(st.st_mode):
            raise ValueError(
                f"Evidence ancestor is not a directory: {current}"
            )

    normalized_target.mkdir(parents=True, exist_ok=False)
    return normalized_target


def _format_mtz_card(text: str) -> bytes:
    if len(text) > 80:
        raise ValueError(f"MTZ header card exceeds 80 characters: {text!r}")
    return text.ljust(80).encode("ascii")


def _integral_value(value: float) -> int | None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    fval = float(value)
    if not math.isfinite(fval) or fval != int(fval):
        return None
    return int(fval)


def _usable_observation(f_val: float, sigf_val: float) -> bool:
    return (
        math.isfinite(f_val)
        and math.isfinite(sigf_val)
        and sigf_val > 0.0
    )


def _inspect_mtz_layout(
    mtz_bytes: bytes, labels: tuple[str, str, str]
) -> dict[str, Any]:
    _require_supported_mtz(mtz_bytes)
    header_byte_offset, headers = _mtz_headers(mtz_bytes)
    context = mtz_crystallographic_context(mtz_bytes)
    bindings = _column_bindings(mtz_bytes, labels)
    count_rows = [line.split() for line in headers if line.startswith("NCOL ")]
    if len(count_rows) != 1:
        raise ValueError("MTZ requires exactly one NCOL header")
    ncols, nrows, nbatches = map(int, count_rows[0][1:4])
    column_records = [
        line.split() for line in headers if line.startswith("COLUMN ")
    ]
    columns = [parts[1] for parts in column_records]
    col_types = [parts[2] for parts in column_records]
    if (
        ncols != len(columns)
        or len(set(columns)) != ncols
        or columns[:3] != ["H", "K", "L"]
        or col_types[:3] != ["H", "H", "H"]
        or nrows <= 0
        or nbatches != 0
        or header_byte_offset != 80 + 4 * ncols * nrows
    ):
        raise ValueError(
            "MTZ table dimensions, column identities, or header offset are inconsistent"
        )
    required_names = ("H", "K", "L", *labels)
    col_indices = {name: columns.index(name) for name in required_names}
    return {
        "header_byte_offset": header_byte_offset,
        "headers": headers,
        "ncols": ncols,
        "nrows": nrows,
        "columns": columns,
        "col_indices": col_indices,
        "bindings": bindings,
        "context": context,
    }


def project_observation_mtz(
    mtz_bytes: bytes,
    *,
    labels: tuple[str, str, str] = OBSERVATION_LABELS,
    flag_values: set[int] | frozenset[int] = DECLARED_FLAG_VALUES,
    free_value: int = FREE_FLAG_VALUE,
) -> tuple[bytes, dict[str, Any]]:
    """Project an MTZ byte stream to ``H, K, L, F-obs, SIGF-obs, R-free-flags``.

    Preserves all raw rows in exact row order, exact 4-byte IEEE-754 words, cell,
    symmetry, resolution, ``VALM NAN``, and dataset metadata for the retained
    observation dataset while stripping all archived model and map columns.
    Verifies retention via :func:`t03_reflection_retention.audit_mtz_retention`.
    """
    layout = _inspect_mtz_layout(mtz_bytes, labels)
    header = layout["headers"]
    header_byte_offset = layout["header_byte_offset"]
    ncols = layout["ncols"]
    nrows = layout["nrows"]
    input_context = layout["context"]
    f_label, sigf_label, flag_label = labels
    retained_names = ("H", "K", "L", f_label, sigf_label, flag_label)
    if retained_names != PROJECTED_MTZ_COLUMNS:
        raise ValueError(
            f"Projected column order {retained_names} does not match "
            f"required {PROJECTED_MTZ_COLUMNS}"
        )

    col_indices = [layout["col_indices"][name] for name in retained_names]
    data_start = 80
    row_stride = ncols * 4
    expected_data_end = data_start + nrows * row_stride
    if expected_data_end != header_byte_offset:
        raise ValueError("Input MTZ data block does not end at header byte offset")

    projected_chunks: list[bytes] = []
    for row_idx in range(nrows):
        row_base = data_start + row_idx * row_stride
        for col_idx in col_indices:
            word_start = row_base + col_idx * 4
            projected_chunks.append(mtz_bytes[word_start : word_start + 4])
    projected_data = b"".join(projected_chunks)

    # Identify the COLUMN cards and dataset IDs for the six retained columns.
    column_cards_by_name: dict[str, str] = {}
    retained_dataset_ids: set[str] = set()
    for rec in header:
        if rec.startswith("COLUMN "):
            tokens = rec.split()
            if len(tokens) == 6 and tokens[1] in retained_names:
                column_cards_by_name[tokens[1]] = rec
                retained_dataset_ids.add(tokens[5])
    if set(column_cards_by_name) != set(retained_names):
        raise ValueError(
            f"Could not locate all retained COLUMN cards {retained_names} in MTZ header"
        )

    dataset_card_prefixes = ("PROJECT", "CRYSTAL", "DATASET", "DCELL", "DWAVEL", "DWAV")
    projected_cards: list[bytes] = []
    emitted_columns = False
    for rec in header:
        stripped = rec.strip()
        if not stripped:
            continue
        tokens = stripped.split()
        keyword = tokens[0]
        if keyword == "NCOL":
            projected_cards.append(
                _format_mtz_card(f"NCOL {len(retained_names):8d} {nrows:12d} {0:8d}")
            )
        elif keyword == "NDIF" and retained_dataset_ids:
            projected_cards.append(
                _format_mtz_card(f"NDIF {len(retained_dataset_ids):8d}")
            )
        elif keyword in dataset_card_prefixes and retained_dataset_ids:
            if len(tokens) >= 2 and tokens[1] in retained_dataset_ids:
                projected_cards.append(_format_mtz_card(rec))
        elif keyword == "COLUMN":
            if not emitted_columns:
                for col_name in retained_names:
                    projected_cards.append(_format_mtz_card(column_cards_by_name[col_name]))
                emitted_columns = True
        else:
            projected_cards.append(_format_mtz_card(rec))
    projected_cards.append(_format_mtz_card("END"))

    projected_header_bytes = b"".join(projected_cards)
    new_header_offset = (80 + len(projected_data)) // 4 + 1
    projected_bytes = (
        b"MTZ "
        + struct.pack("<I", new_header_offset)
        + mtz_bytes[8:80]
        + projected_data
        + projected_header_bytes
    )

    proj_layout = _inspect_mtz_layout(projected_bytes, labels)
    proj_ncols = proj_layout["ncols"]
    proj_nrows = proj_layout["nrows"]
    proj_context = proj_layout["context"]
    if proj_ncols != 6 or proj_nrows != nrows:
        raise ValueError(
            f"Projected MTZ shape ({proj_ncols}, {proj_nrows}) does not match "
            f"(6, {nrows})"
        )
    if proj_context != input_context:
        raise ValueError(
            "Projected MTZ crystallographic context drifted from input MTZ"
        )

    proj_columns = proj_layout["columns"]
    if tuple(proj_columns) != PROJECTED_MTZ_COLUMNS:
        raise ValueError(
            f"Projected MTZ columns {proj_columns} do not match "
            f"{list(PROJECTED_MTZ_COLUMNS)}"
        )
    forbidden_present = FORBIDDEN_ARCHIVED_MTZ_COLUMNS.intersection(proj_columns)
    if forbidden_present:
        raise ValueError(
            f"Projected MTZ retained forbidden archived columns: {sorted(forbidden_present)}"
        )

    retention_audit = audit_mtz_retention(
        mtz_bytes,
        projected_bytes,
        input_labels=labels,
        output_labels=labels,
        flag_values=set(flag_values),
        free_value=free_value,
    )
    if (
        retention_audit["audit_status"] != "preserved"
        or retention_audit["added_raw_rows"] != 0
        or retention_audit["added_all_nan_rows"] != 0
        or retention_audit["missing_input_hkls"]
        or retention_audit["invalidated_input_hkls"]
        or retention_audit["new_usable_output_hkls"]
        or retention_audit["changed_flags"]
        or retention_audit["changed_observations"]
        or retention_audit["invalid_output_flags"]
    ):
        raise ValueError(
            f"Projected MTZ failed reflection-retention audit: {retention_audit}"
        )

    summary = {
        "input_sha256": _sha256_bytes(mtz_bytes),
        "projected_sha256": _sha256_bytes(projected_bytes),
        "input_ncols": ncols,
        "projected_ncols": proj_ncols,
        "nrows": nrows,
        "projected_columns": list(PROJECTED_MTZ_COLUMNS),
        "retained_dataset_ids": sorted(retained_dataset_ids),
        "crystallographic_context": copy.deepcopy(proj_context),
        "retention_audit": retention_audit,
    }
    return projected_bytes, summary


def build_input_hkl_ledger(
    mtz_bytes: bytes,
    *,
    labels: tuple[str, str, str] = OBSERVATION_LABELS,
    flag_values: set[int] | frozenset[int] = DECLARED_FLAG_VALUES,
    free_value: int = FREE_FLAG_VALUE,
) -> dict[str, Any]:
    """Build the exact raw and input-policy-eligible reflection ledger from an MTZ.

    Input-policy eligibility requires finite ``F-obs`` (including zero or negative
    ``F-obs``) and finite positive ``SIGF-obs``.  Every eligible observation must
    carry a finite integral ``R-free-flags`` value in ``flag_values``.  Excluded
    observations (e.g. ``VALM NAN`` padding rows) are retained in ``ineligible_rows``
    and ``raw_rows`` with their exact 4-byte IEEE-754 words; if their flag is NaN,
    ``r_free_flag`` is ``None`` and ``partition`` is ``"unassigned"``.  Duplicate
    HKLs, non-integral Miller indices, or non-integral/undeclared finite
    ``R-free-flags`` fail closed.
    """
    if free_value not in flag_values:
        raise ValueError(f"free_value {free_value} not in declared flag_values {flag_values}")

    layout = _inspect_mtz_layout(mtz_bytes, labels)
    ncols = layout["ncols"]
    nrows = layout["nrows"]
    context = layout["context"]
    col_indices = layout["col_indices"]
    f_label, sigf_label, flag_label = labels
    idx_h = col_indices["H"]
    idx_k = col_indices["K"]
    idx_l = col_indices["L"]
    idx_f = col_indices[f_label]
    idx_sigf = col_indices[sigf_label]
    idx_flag = col_indices[flag_label]

    raw_floats = struct.unpack_from(f"<{nrows * ncols}f", mtz_bytes, 80)
    raw_words = struct.unpack_from(f"<{nrows * ncols}I", mtz_bytes, 80)

    seen_hkls: set[tuple[int, int, int]] = set()
    raw_rows: list[dict[str, Any]] = []
    eligible_by_hkl: dict[str, dict[str, Any]] = {}
    ineligible_rows: list[dict[str, Any]] = []

    raw_work_count = 0
    raw_free_count = 0
    raw_unassigned_count = 0
    eligible_work_count = 0
    eligible_free_count = 0
    eligible_zero_f_count = 0
    eligible_negative_f_count = 0
    ineligible_nonfinite_f_count = 0
    ineligible_nonpositive_or_nonfinite_sigf_count = 0
    ineligible_unassigned_flag_count = 0

    for row_index in range(nrows):
        base = row_index * ncols
        h_val = raw_floats[base + idx_h]
        k_val = raw_floats[base + idx_k]
        l_val = raw_floats[base + idx_l]
        h_i = _integral_value(h_val)
        k_i = _integral_value(k_val)
        l_i = _integral_value(l_val)
        if h_i is None or k_i is None or l_i is None:
            raise ValueError(
                f"Non-integral Miller index at row {row_index}: {(h_val, k_val, l_val)}"
            )
        hkl = (h_i, k_i, l_i)
        if hkl in seen_hkls:
            raise ValueError(f"Duplicate Miller index in MTZ at row {row_index}: {hkl}")
        seen_hkls.add(hkl)

        f_val = float(raw_floats[base + idx_f])
        sigf_val = float(raw_floats[base + idx_sigf])
        flag_raw = float(raw_floats[base + idx_flag])
        f_word = f"{raw_words[base + idx_f]:08x}"
        sigf_word = f"{raw_words[base + idx_sigf]:08x}"
        flag_word = f"{raw_words[base + idx_flag]:08x}"

        eligible = _usable_observation(f_val, sigf_val)
        flag_int = _integral_value(flag_raw)
        hkl_key = f"{h_i},{k_i},{l_i}"

        if eligible:
            if flag_int is None or flag_int not in flag_values:
                raise ValueError(
                    f"Invalid R-free flag value {flag_raw!r} at HKL {hkl} (row {row_index}); "
                    f"declared values are {sorted(flag_values)}"
                )
            is_free: bool | None = flag_int == free_value
            r_free_flag: int | None = flag_int
            partition = "free" if is_free else "work"
            if is_free:
                raw_free_count += 1
                eligible_free_count += 1
            else:
                raw_work_count += 1
                eligible_work_count += 1

            eligibility_status = "eligible"
            if f_val == 0.0:
                eligible_zero_f_count += 1
            elif f_val < 0.0:
                eligible_negative_f_count += 1

            eligible_by_hkl[hkl_key] = {
                "row_index": row_index,
                "hkl": [h_i, k_i, l_i],
                "f_obs": f_val,
                "sigf_obs": sigf_val,
                "f_obs_word_hex": f_word,
                "sigf_obs_word_hex": sigf_word,
                "r_free_flag": flag_int,
                "r_free_flag_word_hex": flag_word,
                "is_free": bool(is_free),
                "partition": partition,
                "is_zero_f": f_val == 0.0,
                "is_negative_f": f_val < 0.0,
            }
        else:
            if flag_int is not None and flag_int in flag_values:
                r_free_flag = flag_int
                is_free = flag_int == free_value
                partition = "free" if is_free else "work"
                if is_free:
                    raw_free_count += 1
                else:
                    raw_work_count += 1
            elif not math.isfinite(flag_raw):
                r_free_flag = None
                is_free = None
                partition = "unassigned"
                raw_unassigned_count += 1
                ineligible_unassigned_flag_count += 1
            else:
                raise ValueError(
                    f"Invalid R-free flag value {flag_raw!r} at HKL {hkl} (row {row_index}); "
                    f"declared values are {sorted(flag_values)}"
                )

            if not math.isfinite(f_val):
                eligibility_status = "excluded_nonfinite_f"
                ineligible_nonfinite_f_count += 1
            else:
                eligibility_status = "excluded_nonpositive_or_nonfinite_sigf"
                ineligible_nonpositive_or_nonfinite_sigf_count += 1
            ineligible_rows.append(
                {
                    "row_index": row_index,
                    "hkl": [h_i, k_i, l_i],
                    "f_obs": None if not math.isfinite(f_val) else f_val,
                    "sigf_obs": None if not math.isfinite(sigf_val) else sigf_val,
                    "f_obs_word_hex": f_word,
                    "sigf_obs_word_hex": sigf_word,
                    "r_free_flag": r_free_flag,
                    "r_free_flag_word_hex": flag_word,
                    "is_free": is_free,
                    "partition": partition,
                    "reason": eligibility_status,
                }
            )

        raw_rows.append(
            {
                "row_index": row_index,
                "hkl": [h_i, k_i, l_i],
                "f_obs": None if not math.isfinite(f_val) else f_val,
                "sigf_obs": None if not math.isfinite(sigf_val) else sigf_val,
                "f_obs_word_hex": f_word,
                "sigf_obs_word_hex": sigf_word,
                "r_free_flag": r_free_flag,
                "r_free_flag_word_hex": flag_word,
                "is_free": is_free,
                "partition": partition,
                "eligible": eligible,
                "eligibility_status": eligibility_status,
            }
        )

    if eligible_work_count == 0 or eligible_free_count == 0:
        raise ValueError(
            f"Input MTZ must contain non-empty eligible work and free sets; "
            f"got work={eligible_work_count}, free={eligible_free_count}"
        )

    return {
        "mtz_sha256": _sha256_bytes(mtz_bytes),
        "labels": {
            "f_obs": f_label,
            "sigf_obs": sigf_label,
            "r_free_flags": flag_label,
        },
        "declared_flag_values": sorted(flag_values),
        "work_flag_value": WORK_FLAG_VALUE,
        "free_flag_value": free_value,
        "crystallographic_context": copy.deepcopy(context),
        "counts": {
            "raw_total": nrows,
            "raw_work": raw_work_count,
            "raw_free": raw_free_count,
            "raw_unassigned": raw_unassigned_count,
            "eligible_total": len(eligible_by_hkl),
            "eligible_work": eligible_work_count,
            "eligible_free": eligible_free_count,
            "eligible_zero_f": eligible_zero_f_count,
            "eligible_negative_f": eligible_negative_f_count,
            "ineligible_total": len(ineligible_rows),
            "ineligible_nonfinite_f": ineligible_nonfinite_f_count,
            "ineligible_nonpositive_or_nonfinite_sigf": (
                ineligible_nonpositive_or_nonfinite_sigf_count
            ),
            "ineligible_unassigned_flag": ineligible_unassigned_flag_count,
        },
        "eligible_by_hkl": eligible_by_hkl,
        "ineligible_rows": ineligible_rows,
        "raw_rows": raw_rows,
    }


def stage_subject_inputs(
    evidence_root: Path,
    subject_id: str = "R4",
    *,
    repo_root: Path = REPO_ROOT,
    archive_path: Path | None = None,
) -> dict[str, Any]:
    """Stage hash-verified PDB and MTZ inputs into a fresh repository-local root."""
    subject_spec = resolve_subject_spec(subject_id)
    fresh_root = prepare_fresh_evidence_root(evidence_root, repo_root=repo_root)
    resolved_archive = (
        Path(repo_root).resolve(strict=True) / ARCHIVE_REL_PATH
        if archive_path is None
        else Path(archive_path)
    )

    pdb_bytes = read_verified_archive_member(
        resolved_archive,
        subject_spec["member"],
        expected_archive_sha256=ARCHIVE_SHA256,
        expected_member_sha256=subject_spec["sha256"],
    )
    mtz_bytes = read_verified_archive_member(
        resolved_archive,
        MTZ_MEMBER,
        expected_archive_sha256=ARCHIVE_SHA256,
        expected_member_sha256=MTZ_SHA256,
    )

    projected_mtz_bytes, projection_summary = project_observation_mtz(mtz_bytes)
    input_ledger = build_input_hkl_ledger(projected_mtz_bytes)

    inputs_dir = fresh_root / "inputs"
    inputs_dir.mkdir(parents=True, exist_ok=False)
    original_pdb_path = inputs_dir / "original_model.pdb"
    original_mtz_path = inputs_dir / "original_data.mtz"
    projected_mtz_path = inputs_dir / "projected_observations.mtz"
    input_ledger_path = inputs_dir / "input_hkl_ledger.json"
    admission_json_path = inputs_dir / "input_admission.json"

    original_pdb_path.write_bytes(pdb_bytes)
    original_mtz_path.write_bytes(mtz_bytes)
    projected_mtz_path.write_bytes(projected_mtz_bytes)
    input_ledger_path.write_text(
        json.dumps(input_ledger, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    admission_record = {
        "schema_version": 1,
        "archive": {
            "archive_id": ARCHIVE_ID,
            "archive_path": str(resolved_archive),
            "archive_sha256": ARCHIVE_SHA256,
        },
        "subject": subject_spec,
        "mtz": {
            "member": MTZ_MEMBER,
            "sha256": MTZ_SHA256,
            "subject_ref": MTZ_SUBJECT_REF,
        },
        "staged_files": {
            "original_model_pdb": str(original_pdb_path),
            "original_model_pdb_sha256": _sha256_regular_file(original_pdb_path),
            "original_data_mtz": str(original_mtz_path),
            "original_data_mtz_sha256": _sha256_regular_file(original_mtz_path),
            "projected_observations_mtz": str(projected_mtz_path),
            "projected_observations_mtz_sha256": _sha256_regular_file(
                projected_mtz_path
            ),
            "input_hkl_ledger_json": str(input_ledger_path),
            "input_hkl_ledger_json_sha256": _sha256_regular_file(input_ledger_path),
        },
        "projection": projection_summary,
        "input_ledger_counts": input_ledger["counts"],
    }
    admission_json_path.write_text(
        json.dumps(admission_record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "evidence_root": fresh_root,
        "inputs_dir": inputs_dir,
        "original_pdb_path": original_pdb_path,
        "original_mtz_path": original_mtz_path,
        "projected_mtz_path": projected_mtz_path,
        "input_ledger_path": input_ledger_path,
        "admission_json_path": admission_json_path,
        "admission_record": admission_record,
        "input_ledger": input_ledger,
    }


def validate_measured_phenix_build(
    build_info: Mapping[str, Any],
    *,
    expected_version: str = toolchain.PHENIX_VERSION,
) -> dict[str, Any]:
    """Validate that a PHENIX build record satisfies #957 and matches ``expected_version``."""
    if not isinstance(build_info, Mapping):
        raise ValueError("PHENIX build_info must be a mapping")
    if not isinstance(expected_version, str) or not expected_version:
        raise ValueError("expected_version must be a non-empty string")
    if (
        not refinement_cache._build_is_measured(build_info)
        or build_info.get("reported_version_source") != "vendor_setup_environment"
    ):
        raise ValueError(
            "PHENIX vendor-setup build measurement failed #957 admission gate"
        )
    version_probe = build_info.get("version_probe")
    if not isinstance(version_probe, Mapping):
        raise ValueError("Measured PHENIX build missing version_probe mapping")
    resolved_prefix = version_probe.get("resolved_prefix")
    setup_resolved = version_probe.get("setup_resolved_path")
    dispatcher_resolved = version_probe.get("resolved_path")
    if (
        not isinstance(resolved_prefix, str)
        or not resolved_prefix
        or not Path(resolved_prefix).is_absolute()
    ):
        raise ValueError(
            f"Measured PHENIX build missing absolute resolved_prefix: {resolved_prefix!r}"
        )
    if (
        not isinstance(setup_resolved, str)
        or not isinstance(dispatcher_resolved, str)
        or not Path(setup_resolved).is_relative_to(Path(resolved_prefix))
        or not Path(dispatcher_resolved).is_relative_to(Path(resolved_prefix))
    ):
        raise ValueError(
            "Measured PHENIX setup/dispatcher paths do not belong to resolved_prefix"
        )

    top_parsed = build_info.get("parsed_build")
    probe_parsed = version_probe.get("parsed_build")
    setup_parsed = version_probe.get("setup_parsed_build")
    banner_parsed = toolchain.parse_phenix_build(
        str(build_info.get("reported_version", ""))
    )
    if (
        top_parsed != expected_version
        or probe_parsed != expected_version
        or setup_parsed != expected_version
        or banner_parsed != expected_version
    ):
        raise ValueError(
            f"PHENIX build version mismatch: expected {expected_version!r}, got "
            f"parsed_build={top_parsed!r}, probe.parsed_build={probe_parsed!r}, "
            f"probe.setup_parsed_build={setup_parsed!r}, banner={banner_parsed!r}"
        )

    normalized_build = json.loads(
        json.dumps(dict(build_info), sort_keys=True, allow_nan=False)
    )
    return {
        "expected_version": expected_version,
        "parsed_build": expected_version,
        "resolved_prefix": str(Path(resolved_prefix)),
        "setup_resolved_path": str(Path(setup_resolved)),
        "dispatcher_resolved_path": str(Path(dispatcher_resolved)),
        "build_info": normalized_build,
    }


def inspect_map_mtz_bytes(
    mtz_bytes: bytes,
    *,
    expected_columns: Sequence[str],
    expected_column_types: Sequence[str],
) -> dict[str, Any]:
    """Parse and validate a binary map-coefficient MTZ byte stream in pure Python."""
    _require_supported_mtz(mtz_bytes)
    header_byte_offset, headers = _mtz_headers(mtz_bytes)
    context = mtz_crystallographic_context(mtz_bytes)
    count_rows = [line.split() for line in headers if line.startswith("NCOL ")]
    if len(count_rows) != 1:
        raise ValueError("Map MTZ requires exactly one NCOL header")
    ncols, nrows, nbatches = map(int, count_rows[0][1:4])
    column_records = [
        line.split() for line in headers if line.startswith("COLUMN ")
    ]
    columns = [parts[1] for parts in column_records]
    col_types = [parts[2] for parts in column_records]
    if (
        ncols != len(columns)
        or len(set(columns)) != ncols
        or nrows <= 0
        or nbatches != 0
        or header_byte_offset != 80 + 4 * ncols * nrows
    ):
        raise ValueError(
            "Map MTZ table dimensions, column identities, or header offset are inconsistent"
        )
    if columns != list(expected_columns):
        raise ValueError(
            f"Map MTZ column labels {columns} do not match expected {list(expected_columns)}"
        )
    if col_types != list(expected_column_types):
        raise ValueError(
            f"Map MTZ column types {col_types} do not match expected {list(expected_column_types)}"
        )

    raw_floats = struct.unpack_from(f"<{nrows * ncols}f", mtz_bytes, 80)
    raw_words = struct.unpack_from(f"<{nrows * ncols}I", mtz_bytes, 80)
    rows_by_hkl: dict[str, dict[str, Any]] = {}
    for row_index in range(nrows):
        base = row_index * ncols
        h_i = _integral_value(raw_floats[base])
        k_i = _integral_value(raw_floats[base + 1])
        l_i = _integral_value(raw_floats[base + 2])
        if h_i is None or k_i is None or l_i is None:
            raise ValueError(
                f"Non-integral Miller index in map MTZ at row {row_index}: "
                f"{(raw_floats[base], raw_floats[base + 1], raw_floats[base + 2])}"
            )
        key = f"{h_i},{k_i},{l_i}"
        if key in rows_by_hkl:
            raise ValueError(f"Duplicate Miller index in map MTZ at row {row_index}: {key}")
        values: dict[str, float] = {}
        words: dict[str, str] = {}
        for col_idx in range(3, ncols):
            col_name = columns[col_idx]
            val = float(raw_floats[base + col_idx])
            if not math.isfinite(val):
                raise ValueError(
                    f"Non-finite value {val!r} in map MTZ column {col_name!r} at HKL {key}"
                )
            values[col_name] = val
            words[col_name] = f"{raw_words[base + col_idx]:08x}"
        rows_by_hkl[key] = {
            "row_index": row_index,
            "hkl": [h_i, k_i, l_i],
            "values": values,
            "words": words,
        }

    return {
        "sha256": _sha256_bytes(mtz_bytes),
        "ncols": ncols,
        "nrows": nrows,
        "columns": columns,
        "column_types": col_types,
        "crystallographic_context": context,
        "rows_by_hkl": rows_by_hkl,
    }


def _circular_phase_diff_deg(phase_a: float, phase_b: float) -> float:
    return abs((phase_a - phase_b + 180.0) % 360.0 - 180.0)


def resolve_phenix_vendor_source_files(resolved_prefix: Path) -> dict[str, Path]:
    """Locate and verify the installed PHENIX Python source modules under ``resolved_prefix``."""
    prefix = Path(resolved_prefix)
    if prefix.is_symlink():
        raise ValueError(f"PHENIX installation prefix must not be a symlink: {prefix}")
    strict_prefix = prefix.resolve(strict=True)
    lib_dir = strict_prefix / "lib"
    if not lib_dir.is_dir():
        raise FileNotFoundError(f"PHENIX lib directory not found: {lib_dir}")

    site_packages_candidates = sorted(
        path
        for path in lib_dir.glob("python*/site-packages")
        if path.is_dir() and not path.is_symlink()
    )
    if len(site_packages_candidates) != 1:
        raise ValueError(
            f"Expected exactly one python*/site-packages directory under {lib_dir}; "
            f"found {[str(p) for p in site_packages_candidates]}"
        )
    site_packages = site_packages_candidates[0].resolve(strict=True)
    if not site_packages.is_relative_to(strict_prefix):
        raise ValueError(
            f"PHENIX site-packages escapes installation prefix: {site_packages}"
        )

    resolved_sources: dict[str, Path] = {}
    for key, rel_path in PHENIX_VENDOR_SOURCE_RELPATHS.items():
        candidate = site_packages / rel_path
        if candidate.is_symlink():
            raise ValueError(f"PHENIX vendor source must not be a symlink: {candidate}")
        resolved_candidate = candidate.resolve(strict=True)
        if not resolved_candidate.is_relative_to(strict_prefix):
            raise ValueError(
                f"PHENIX vendor source escapes installation prefix: {resolved_candidate}"
            )
        _sha256_regular_file(resolved_candidate)
        resolved_sources[key] = resolved_candidate
    return resolved_sources


def _hkl_key(hkl: list[int] | tuple[int, int, int]) -> str:
    if (
        not isinstance(hkl, (list, tuple))
        or len(hkl) != 3
        or any(type(v) is not int for v in hkl)
    ):
        raise ValueError(f"Invalid HKL triplet: {hkl!r}")
    return f"{hkl[0]},{hkl[1]},{hkl[2]}"


def _verify_finite_positive(value: Any, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        raise ValueError(f"{label} must be a finite number, got {value!r}")
    fval = float(value)
    if fval <= 0.0:
        raise ValueError(f"{label} must be positive, got {fval!r}")
    return fval


def _verify_finite_nonnegative(value: Any, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        raise ValueError(f"{label} must be a finite number, got {value!r}")
    fval = float(value)
    if fval < 0.0:
        raise ValueError(f"{label} must be non-negative, got {fval!r}")
    return fval


def _verify_finite(value: Any, label: str) -> float:
    if type(value) not in (int, float) or not math.isfinite(float(value)):
        raise ValueError(f"{label} must be a finite number, got {value!r}")
    return float(value)


def _verify_int_count(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{label} must be a positive int, got {value!r}")
    return value


def _verify_nonnegative_int_count(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} must be a non-negative int, got {value!r}")
    return value


EXPECTED_RESOLUTION_STAGES: tuple[str, str, str, str] = (
    "extracted_pre_fmodel",
    "final_effective",
    "actual_work",
    "actual_free",
)

_DECIMAL_CELL_TOKEN_RE = re.compile(
    r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
)


def _normalize_unit_cell_token(value: Any, label: str) -> float:
    """Normalize an admitted unit-cell parameter token (exact decimal string or int/float)."""
    if type(value) in (int, float):
        return _verify_finite_positive(value, label)
    if type(value) is not str:
        raise ValueError(f"{label} must be a finite number, got {value!r}")
    if not value or value != value.strip() or "_" in value or not value.isascii():
        raise ValueError(
            f"{label} must be a valid decimal unit-cell token, got {value!r}"
        )
    try:
        dec = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(
            f"{label} must be a valid decimal unit-cell token, got {value!r}"
        ) from exc
    if not dec.is_finite():
        raise ValueError(f"{label} must be a finite number, got {value!r}")
    if _DECIMAL_CELL_TOKEN_RE.fullmatch(value) is None:
        raise ValueError(
            f"{label} must be a valid decimal unit-cell token, got {value!r}"
        )
    fval = float(dec)
    if not math.isfinite(fval):
        raise ValueError(f"{label} must be a finite number, got {value!r}")
    if dec <= 0 or fval <= 0.0:
        raise ValueError(f"{label} must be positive, got {fval!r}")
    return fval


def validate_unit_cell_parameters(
    cell: Any, *, label: str = "cell_a_b_c_alpha_beta_gamma"
) -> tuple[float, float, float, float, float, float]:
    """Validate crystallographic unit cell ``(a, b, c, alpha, beta, gamma)``."""
    if not isinstance(cell, (list, tuple)) or len(cell) != 6:
        raise ValueError(
            f"{label} must be a 6-element sequence (a, b, c, alpha, beta, gamma), "
            f"got {cell!r}"
        )
    a = _normalize_unit_cell_token(cell[0], f"{label}[0] (a)")
    b = _normalize_unit_cell_token(cell[1], f"{label}[1] (b)")
    c = _normalize_unit_cell_token(cell[2], f"{label}[2] (c)")
    alpha = _normalize_unit_cell_token(cell[3], f"{label}[3] (alpha)")
    beta = _normalize_unit_cell_token(cell[4], f"{label}[4] (beta)")
    gamma = _normalize_unit_cell_token(cell[5], f"{label}[5] (gamma)")
    for angle_name, angle_val in (
        ("alpha", alpha),
        ("beta", beta),
        ("gamma", gamma),
    ):
        if angle_val >= 180.0:
            raise ValueError(
                f"{label} angle {angle_name} must be in (0, 180) degrees, got {angle_val!r}"
            )
    if (
        alpha + beta + gamma >= 360.0
        or alpha + beta <= gamma
        or alpha + gamma <= beta
        or beta + gamma <= alpha
    ):
        raise ValueError(
            f"{label} angles ({alpha}, {beta}, {gamma}) violate crystallographic "
            "cone inequalities"
        )
    cos_a = 0.0 if alpha == 90.0 else math.cos(math.radians(alpha))
    cos_b = 0.0 if beta == 90.0 else math.cos(math.radians(beta))
    cos_g = 0.0 if gamma == 90.0 else math.cos(math.radians(gamma))
    omega = (
        1.0
        - cos_a * cos_a
        - cos_b * cos_b
        - cos_g * cos_g
        + 2.0 * cos_a * cos_b * cos_g
    )
    if not math.isfinite(omega) or omega <= 1e-12:
        raise ValueError(
            f"{label} defines a singular or non-positive metric tensor (omega={omega!r})"
        )
    return (a, b, c, alpha, beta, gamma)


def ccp4_mtz_float32_unit_cell(
    cell: Any, *, label: str = "cell_a_b_c_alpha_beta_gamma"
) -> tuple[float, float, float, float, float, float]:
    """Return the installed CCP4/iotbx MTZ reader's float32->float64 unit-cell conversion.

    In PHENIX 2.0-5936, ``ccp4io/libccp4/ccp4/mtzdata.h:86`` and
    ``cmtzlib.c:476,549-551`` store MTZ ``CELL``/``DCELL`` header tokens in
    IEEE-754 binary32 (``float cell[6]``), and ``iotbx/mtz/crystal.cpp:61-67``
    promotes those 32-bit floats to ``double`` when constructing Miller-array
    crystal symmetries.
    """
    validated = validate_unit_cell_parameters(cell, label=label)
    f32_tuple = struct.unpack("<6f", struct.pack("<6f", *validated))
    return validate_unit_cell_parameters(
        f32_tuple, label=f"{label} (ccp4_mtz_float32)"
    )


def reciprocal_metric_tensor_from_cell(
    cell: Any, *, label: str = "cell_a_b_c_alpha_beta_gamma"
) -> tuple[
    tuple[float, float, float],
    tuple[float, float, float],
    tuple[float, float, float],
]:
    """Compute the inverse direct metric tensor ``G^-1`` for ``d = 1 / sqrt(h^T G^-1 h)``."""
    a, b, c, alpha, beta, gamma = validate_unit_cell_parameters(
        cell, label=label
    )
    cos_a = 0.0 if alpha == 90.0 else math.cos(math.radians(alpha))
    cos_b = 0.0 if beta == 90.0 else math.cos(math.radians(beta))
    cos_g = 0.0 if gamma == 90.0 else math.cos(math.radians(gamma))
    g11 = a * a
    g22 = b * b
    g33 = c * c
    g12 = a * b * cos_g
    g13 = a * c * cos_b
    g23 = b * c * cos_a

    c11 = g22 * g33 - g23 * g23
    c22 = g11 * g33 - g13 * g13
    c33 = g11 * g22 - g12 * g12
    c12 = g13 * g23 - g12 * g33
    c13 = g12 * g23 - g13 * g22
    c23 = g12 * g13 - g11 * g23
    det_g = g11 * c11 + g12 * c12 + g13 * c13
    if not math.isfinite(det_g) or det_g <= 0.0:
        raise ValueError(
            f"{label} direct metric tensor determinant must be positive, got {det_g!r}"
        )
    gi11 = c11 / det_g
    gi22 = c22 / det_g
    gi33 = c33 / det_g
    gi12 = c12 / det_g
    gi13 = c13 / det_g
    gi23 = c23 / det_g
    return (
        (gi11, gi12, gi13),
        (gi12, gi22, gi23),
        (gi13, gi23, gi33),
    )


def compute_hkl_d_spacing(
    hkl: Any,
    cell: Any,
    *,
    g_inv: tuple[
        tuple[float, float, float],
        tuple[float, float, float],
        tuple[float, float, float],
    ]
    | None = None,
) -> float:
    """Compute crystallographic d-spacing ``d = 1 / sqrt(h^T G^-1 h)`` for a Miller index."""
    _hkl_key(hkl)
    h, k, l = int(hkl[0]), int(hkl[1]), int(hkl[2])
    if h == 0 and k == 0 and l == 0:
        raise ValueError("Miller index (0, 0, 0) has undefined d-spacing")
    if g_inv is None:
        g_inv = reciprocal_metric_tensor_from_cell(cell)
    gi11, gi12, gi13 = g_inv[0]
    _, gi22, gi23 = g_inv[1]
    _, _, gi33 = g_inv[2]
    inv_d_sq = (
        gi11 * h * h
        + gi22 * k * k
        + gi33 * l * l
        + 2.0 * (gi12 * h * k + gi13 * h * l + gi23 * k * l)
    )
    if not math.isfinite(inv_d_sq) or inv_d_sq <= 0.0:
        raise ValueError(
            f"Non-positive reciprocal metric norm for HKL {(h, k, l)!r}: {inv_d_sq!r}"
        )
    return 1.0 / math.sqrt(inv_d_sq)


def compute_stage_resolution_range(
    hkls: Sequence[Any],
    cell: Any,
    *,
    stage_label: str = "stage",
) -> dict[str, float]:
    """Recompute ``{"d_max": ..., "d_min": ...}`` from a stage's reflection HKLs and cell."""
    if not isinstance(hkls, (list, tuple)) or not hkls:
        raise ValueError(
            f"{stage_label} reflection list must be non-empty for resolution range computation"
        )
    g_inv = reciprocal_metric_tensor_from_cell(cell)
    d_values = [compute_hkl_d_spacing(hkl, cell, g_inv=g_inv) for hkl in hkls]
    return {
        "d_max": max(d_values),
        "d_min": min(d_values),
    }


SYMMETRY_OPERATOR_NORMALIZATION_POLICY = (
    "cctbx_rt_mx_as_xyz_to_mtz_symm_uppercase_v1"
)
_SYMMETRY_COMPONENT_RE = re.compile(
    r"^(?P<axis>-?[XYZ])(?P<trans>[+-](?P<num>[1-9]\d*)/(?P<den>[1-9]\d*))?$"
)
_SPACE_GROUP_SYMBOL_AND_NUMBER_RE = re.compile(
    r"^(?P<lookup_symbol>[A-Za-z0-9_/\-\s]+?)\s+\(No\.\s*(?P<number>[1-9]\d*)\)$"
)


def normalize_symmetry_operator_xyz(
    operator: Any,
    *,
    label: str = "operator_xyz",
) -> str:
    """Normalize an inspected cctbx ``rt_mx.as_xyz()`` or MTZ ``SYMM`` operator string.

    Policy ``cctbx_rt_mx_as_xyz_to_mtz_symm_uppercase_v1``:
    - Accepts only the inspected ``cctbx.sgtbx.rt_mx.as_xyz(decimal=False,
      t_first=False, symbol_letters="xyz", separator=",")`` and MTZ ``SYMM``
      3-component axial-first rational grammar (e.g. ``x,y,z``,
      ``-x+1/2,-y,z+1/2``, ``X,Y,Z``).
    - Removes ASCII spaces and uppercases ``xyz -> XYZ``.
    - Requires 3 comma-separated components, each with a signed single axis
      term (``X``, ``Y``, ``Z``, ``-X``, ``-Y``, ``-Z``; no leading ``+``) and
      an optional reduced proper rational translation ``[+-]n/d`` with
      ``0 < n < d`` and ``gcd(n, d) == 1``, covering all three axes ``X, Y, Z``.
    - Fails closed on unsupported alternate spellings (decimal translations,
      translation-first order, unreduced fractions, non-XYZ variable symbols,
      or control characters).
    """
    if (
        type(operator) is not str
        or not operator.strip()
        or not operator.isascii()
        or any(ord(ch) < 32 or ord(ch) > 126 for ch in operator)
    ):
        raise ValueError(
            f"{label} must be a non-empty printable ASCII operator string, got {operator!r}"
        )
    compact = operator.replace(" ", "").upper()
    components = compact.split(",")
    if len(components) != 3:
        raise ValueError(
            f"{label} must have 3 comma-separated XYZ components, got {operator!r}"
        )
    for comp in components:
        m = _SYMMETRY_COMPONENT_RE.fullmatch(comp)
        if m is None:
            raise ValueError(
                f"{label} uses unsupported or malformed symmetry operator spelling {operator!r}"
            )
        if m.group("trans") is not None:
            num = int(m.group("num"))
            den = int(m.group("den"))
            if not (0 < num < den) or math.gcd(num, den) != 1:
                raise ValueError(
                    f"{label} has non-canonical or unreduced translation in {operator!r}"
                )
    if sorted(re.findall(r"[XYZ]", compact)) != ["X", "Y", "Z"]:
        raise ValueError(
            f"{label} must reference each axis X, Y, Z exactly once, got {operator!r}"
        )
    return compact


def validate_runtime_space_group(
    crystal_symmetry: Mapping[str, Any],
    input_symmetry: Any,
    *,
    maps_symmetry: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate runtime space-group number, operators, and display symbol against input/map MTZ symmetry."""
    if not isinstance(crystal_symmetry, Mapping):
        raise ValueError("phenix_payload missing crystal_symmetry section")
    if not isinstance(input_symmetry, Mapping):
        raise ValueError(
            "input_ledger.crystallographic_context missing symmetry mapping"
        )

    space_group_symbol = crystal_symmetry.get("space_group_symbol")
    if type(space_group_symbol) is not str or not space_group_symbol.strip():
        raise ValueError(
            "phenix_payload.crystal_symmetry.space_group_symbol must be a non-empty string"
        )
    if (
        space_group_symbol != space_group_symbol.strip()
        or not space_group_symbol.isascii()
        or any(ord(ch) < 32 or ord(ch) > 126 for ch in space_group_symbol)
    ):
        raise ValueError(
            "phenix_payload.crystal_symmetry.space_group_symbol must be trimmed printable ASCII, "
            f"got {space_group_symbol!r}"
        )

    raw_sg_number = crystal_symmetry.get("space_group_number")
    if type(raw_sg_number) is not int or not (1 <= raw_sg_number <= 230):
        raise ValueError(
            "phenix_payload.crystal_symmetry.space_group_number must be an int in 1..230, "
            f"got {raw_sg_number!r}"
        )
    expected_sg_number = input_symmetry.get("space_group_number")
    if type(expected_sg_number) is not int or not (1 <= expected_sg_number <= 230):
        raise ValueError(
            "input_ledger.crystallographic_context.symmetry.space_group_number must be an int in 1..230, "
            f"got {expected_sg_number!r}"
        )
    if raw_sg_number != expected_sg_number:
        raise ValueError(
            f"phenix_payload.crystal_symmetry.space_group_number {raw_sg_number} "
            f"disagrees with input_ledger space_group_number {expected_sg_number}"
        )

    raw_operators = crystal_symmetry.get("space_group_operators_xyz")
    if not isinstance(raw_operators, (list, tuple)) or not raw_operators:
        raise ValueError(
            "phenix_payload.crystal_symmetry.space_group_operators_xyz must be a non-empty "
            f"sequence of operator strings, got {raw_operators!r}"
        )
    preserved_raw_operators: list[str] = []
    normalized_runtime_ops: list[str] = []
    for idx, op in enumerate(raw_operators):
        norm_op = normalize_symmetry_operator_xyz(
            op,
            label=f"phenix_payload.crystal_symmetry.space_group_operators_xyz[{idx}]",
        )
        preserved_raw_operators.append(op)
        normalized_runtime_ops.append(norm_op)
    if len(set(normalized_runtime_ops)) != len(normalized_runtime_ops):
        raise ValueError(
            "phenix_payload.crystal_symmetry.space_group_operators_xyz contains duplicate "
            f"normalized symmetry operators: {normalized_runtime_ops!r}"
        )

    input_ops_raw = input_symmetry.get("operators_xyz")
    input_op_count = input_symmetry.get("operator_count")
    if (
        type(input_op_count) is not int
        or input_op_count <= 0
        or not isinstance(input_ops_raw, (list, tuple))
        or len(input_ops_raw) != input_op_count
    ):
        raise ValueError(
            "input_ledger.crystallographic_context.symmetry has invalid operator_count / operators_xyz"
        )
    normalized_input_ops = sorted(
        normalize_symmetry_operator_xyz(
            op,
            label=f"input_ledger.crystallographic_context.symmetry.operators_xyz[{idx}]",
        )
        for idx, op in enumerate(input_ops_raw)
    )
    sorted_runtime_ops = sorted(normalized_runtime_ops)
    if (
        len(sorted_runtime_ops) != input_op_count
        or sorted_runtime_ops != normalized_input_ops
    ):
        raise ValueError(
            "phenix_payload.crystal_symmetry.space_group_operators_xyz "
            f"(normalized={sorted_runtime_ops!r}) disagrees with input_ledger "
            f"symmetry.operators_xyz {normalized_input_ops!r}"
        )

    m_sym = _SPACE_GROUP_SYMBOL_AND_NUMBER_RE.fullmatch(space_group_symbol)
    if m_sym is None:
        raise ValueError(
            "phenix_payload.crystal_symmetry.space_group_symbol "
            f"{space_group_symbol!r} must match installed "
            "cctbx.sgtbx.space_group_info.symbol_and_number() format "
            "'<lookup_symbol> (No. <number>)'"
        )
    symbol_number = int(m_sym.group("number"))
    if symbol_number != raw_sg_number:
        raise ValueError(
            f"phenix_payload.crystal_symmetry.space_group_symbol {space_group_symbol!r} "
            f"declares space-group number {symbol_number}, which disagrees with "
            f"space_group_number {raw_sg_number}"
        )
    normalized_lookup_symbol = "".join(m_sym.group("lookup_symbol").upper().split())
    expected_input_symbol = input_symmetry.get("space_group_symbol")
    if type(expected_input_symbol) is not str or not expected_input_symbol.strip():
        raise ValueError(
            "input_ledger.crystallographic_context.symmetry.space_group_symbol must be a non-empty string"
        )
    normalized_expected_symbol = "".join(expected_input_symbol.upper().split())
    if normalized_lookup_symbol != normalized_expected_symbol:
        raise ValueError(
            f"phenix_payload.crystal_symmetry.space_group_symbol {space_group_symbol!r} "
            f"(normalized symbol {normalized_lookup_symbol!r}) disagrees with "
            f"input_ledger space_group_symbol {normalized_expected_symbol!r}"
        )
    expected_lattice = input_symmetry.get("lattice")
    if (
        type(expected_lattice) is not str
        or not expected_lattice.strip()
        or not normalized_lookup_symbol.startswith(expected_lattice.strip().upper())
    ):
        raise ValueError(
            f"phenix_payload.crystal_symmetry.space_group_symbol {space_group_symbol!r} "
            f"lattice disagrees with input_ledger lattice {expected_lattice!r}"
        )

    if maps_symmetry is not None:
        if not isinstance(maps_symmetry, Mapping):
            raise ValueError("map_mtz.crystallographic_context missing symmetry mapping")
        maps_sg_number = maps_symmetry.get("space_group_number")
        if maps_sg_number != raw_sg_number:
            raise ValueError(
                f"phenix_payload.crystal_symmetry.space_group_number {raw_sg_number} "
                f"disagrees with map MTZ space_group_number {maps_sg_number!r}"
            )
        maps_ops_raw = maps_symmetry.get("operators_xyz")
        if not isinstance(maps_ops_raw, (list, tuple)):
            raise ValueError("map_mtz.crystallographic_context.symmetry missing operators_xyz")
        normalized_maps_ops = sorted(
            normalize_symmetry_operator_xyz(
                op,
                label=f"map_mtz.crystallographic_context.symmetry.operators_xyz[{idx}]",
            )
            for idx, op in enumerate(maps_ops_raw)
        )
        if sorted_runtime_ops != normalized_maps_ops:
            raise ValueError(
                "phenix_payload.crystal_symmetry.space_group_operators_xyz "
                f"(normalized={sorted_runtime_ops!r}) disagrees with map MTZ "
                f"symmetry.operators_xyz {normalized_maps_ops!r}"
            )
        maps_symbol = maps_symmetry.get("space_group_symbol")
        if (
            type(maps_symbol) is not str
            or "".join(maps_symbol.upper().split()) != normalized_lookup_symbol
        ):
            raise ValueError(
                f"phenix_payload.crystal_symmetry.space_group_symbol {space_group_symbol!r} "
                f"disagrees with map MTZ space_group_symbol {maps_symbol!r}"
            )

    return {
        "space_group_symbol": space_group_symbol,
        "space_group_number": raw_sg_number,
        "raw_space_group_operators_xyz": preserved_raw_operators,
        "normalized_space_group_operators_xyz": sorted_runtime_ops,
        "normalized_lookup_symbol": normalized_lookup_symbol,
        "symmetry_normalization_policy": SYMMETRY_OPERATOR_NORMALIZATION_POLICY,
    }


def reconcile_phenix_rfactor_output(
    phenix_payload: Mapping[str, Any],
    input_ledger: Mapping[str, Any],
    *,
    expected_vendor_source_sha256: Mapping[str, str] | None = None,
    expected_vendor_module_paths: Mapping[str, str | Path] | None = None,
    expected_resolved_prefix: str | Path | None = None,
    expected_phenix_version: str = toolchain.PHENIX_VERSION,
    measured_build: Mapping[str, Any] | None = None,
    phx_maps_mtz_path: Path | None = None,
    phx_maps_mtz_bytes: bytes | None = None,
    phx_obs_pair_only_mtz_path: Path | None = None,
    phx_obs_pair_only_mtz_bytes: bytes | None = None,
    phenix_diagnostics_path: Path | None = None,
    phenix_diagnostics_payload: Mapping[str, Any] | None = None,
    cache_manifest_artifacts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate and reconcile the full-precision PHENIX helper payload against input ledger.

    Enforces:
    - Exact PHENIX version pin (``2.0-5936``), installation prefix, and runtime
      vendor module provenance under the admitted ``resolved_prefix``.
    - Recomputed canonical SHA-256 digests and zero per-scatterer diffs from the
      full retained ``before``, ``after_model``, and ``after_fmodel`` scatterer
      snapshots.
    - Retained ``extract_xtal_data``, ``mmtbx.model.manager``, and
      ``fmodel.update_all_scales`` diagnostic logs.
    - Exact 1-to-1 HKL tracking and per-HKL ``f_obs`` / ``sigf_obs`` / ``is_free``
      agreement across ``extracted_pre_fmodel``, ``final_effective``,
      ``actual_work``, and ``actual_free``.
    - Full-precision float64 replay of ``r_work``, ``r_free``, ``r_all``, gap,
      and reported reflection counts and numerator/denominator sums.
    - Stage-by-stage ``d_max`` and ``d_min`` resolution extrema recomputed from
      each stage's reconciled reflection HKLs and the admitted input unit cell
      via the general crystallographic reciprocal metric tensor.
    - Internal consistency of ``2mFo-DFc`` and ``mFo-DFc`` JSON map coefficients
      and binary verification of ``phx_maps.mtz`` and ``PHX_OBS_PAIR_ONLY.mtz``.
    """
    if not isinstance(phenix_payload, Mapping):
        raise ValueError("phenix_payload must be a mapping")
    if not isinstance(input_ledger, Mapping):
        raise ValueError("input_ledger must be a mapping")

    eligible_by_hkl = input_ledger.get("eligible_by_hkl")
    raw_rows = input_ledger.get("raw_rows")
    input_context = input_ledger.get("crystallographic_context")
    if not isinstance(eligible_by_hkl, Mapping) or not eligible_by_hkl:
        raise ValueError("input_ledger missing non-empty eligible_by_hkl mapping")
    if not isinstance(raw_rows, list) or not raw_rows:
        raise ValueError("input_ledger missing non-empty raw_rows list")
    if not isinstance(input_context, Mapping):
        raise ValueError("input_ledger missing crystallographic_context")
    validated_input_cell = validate_unit_cell_parameters(
        input_context.get("cell_a_b_c_alpha_beta_gamma"),
        label="input_ledger.crystallographic_context.cell_a_b_c_alpha_beta_gamma",
    )

    raw_by_hkl: dict[str, Mapping[str, Any]] = {}
    for row in raw_rows:
        key = _hkl_key(row["hkl"])
        if key in raw_by_hkl:
            raise ValueError(f"Duplicate HKL {key} in input_ledger raw_rows")
        raw_by_hkl[key] = row

    # 1. Verify PHENIX version pin, prefix binding, and runtime module provenance.
    if (
        phenix_payload.get("artifact_role")
        == "partial_unverified_phenix_evidence"
        or phenix_payload.get("reusable_cache_output") is False
        or phenix_payload.get("canonical_eval_qds_eligible") is False
    ):
        raise ValueError(
            "Partial/unverified PHENIX evidence artifact cannot be reconciled "
            "as a completed payload or admitted into canonical EVAL/QDS"
        )
    if expected_phenix_version != toolchain.PHENIX_VERSION:
        raise ValueError(
            f"expected_phenix_version {expected_phenix_version!r} does not match "
            f"repository pin {toolchain.PHENIX_VERSION!r}"
        )
    if measured_build is not None:
        validated_build = validate_measured_phenix_build(
            measured_build, expected_version=expected_phenix_version
        )
        if expected_resolved_prefix is None:
            expected_resolved_prefix = validated_build["resolved_prefix"]
        elif str(Path(expected_resolved_prefix)) != validated_build["resolved_prefix"]:
            raise ValueError(
                f"expected_resolved_prefix {expected_resolved_prefix!r} disagrees with "
                f"measured_build resolved_prefix {validated_build['resolved_prefix']!r}"
            )

    payload_version = phenix_payload.get("expected_phenix_version")
    if payload_version != expected_phenix_version:
        raise ValueError(
            f"phenix_payload expected_phenix_version {payload_version!r} != "
            f"{expected_phenix_version!r}"
        )
    payload_prefix = phenix_payload.get("expected_resolved_prefix")
    if (
        not isinstance(payload_prefix, str)
        or not payload_prefix
        or not Path(payload_prefix).is_absolute()
    ):
        raise ValueError(
            f"phenix_payload missing absolute expected_resolved_prefix: {payload_prefix!r}"
        )

    runtime_env = phenix_payload.get("runtime_environment")
    if not isinstance(runtime_env, Mapping):
        raise ValueError("phenix_payload missing runtime_environment")
    sys_prefix = runtime_env.get("sys_prefix")
    resolved_sys_prefix = runtime_env.get("resolved_sys_prefix")
    sys_executable = runtime_env.get("sys_executable")
    resolved_sys_executable = runtime_env.get("resolved_sys_executable", sys_executable)
    if (
        not isinstance(sys_prefix, str)
        or not sys_prefix
        or not isinstance(resolved_sys_prefix, str)
        or not resolved_sys_prefix
    ):
        raise ValueError("runtime_environment missing sys_prefix / resolved_sys_prefix")
    prefix_path = Path(resolved_sys_prefix)
    if not prefix_path.is_absolute():
        raise ValueError(f"resolved_sys_prefix must be absolute: {resolved_sys_prefix}")
    if resolved_sys_prefix != str(Path(payload_prefix)):
        raise ValueError(
            f"runtime_environment.resolved_sys_prefix {resolved_sys_prefix!r} != "
            f"payload expected_resolved_prefix {payload_prefix!r}"
        )
    if expected_resolved_prefix is not None and resolved_sys_prefix != str(
        Path(expected_resolved_prefix)
    ):
        raise ValueError(
            f"runtime_environment.resolved_sys_prefix {resolved_sys_prefix!r} != "
            f"expected_resolved_prefix {str(Path(expected_resolved_prefix))!r}"
        )
    for exec_label, exec_val in (
        ("sys_executable", sys_executable),
        ("resolved_sys_executable", resolved_sys_executable),
    ):
        if (
            not isinstance(exec_val, str)
            or not exec_val
            or not Path(exec_val).is_absolute()
            or not Path(exec_val).is_relative_to(prefix_path)
        ):
            raise ValueError(
                f"runtime_environment.{exec_label} {exec_val!r} is not inside "
                f"resolved_sys_prefix {prefix_path}"
            )

    modules = runtime_env.get("vendor_modules")
    if not isinstance(modules, Mapping) or set(modules) != set(
        PHENIX_VENDOR_SOURCE_RELPATHS
    ):
        raise ValueError(
            f"runtime_environment.vendor_modules keys must match "
            f"{sorted(PHENIX_VENDOR_SOURCE_RELPATHS)}"
        )
    for mod_key, mod_info in modules.items():
        if not isinstance(mod_info, Mapping):
            raise ValueError(f"vendor_modules[{mod_key!r}] must be a mapping")
        mod_path_str = mod_info.get("resolved_path")
        mod_sha = mod_info.get("sha256")
        if not isinstance(mod_path_str, str) or not mod_path_str:
            raise ValueError(f"vendor_modules[{mod_key!r}] missing resolved_path")
        if not isinstance(mod_sha, str) or len(mod_sha) != 64:
            raise ValueError(f"vendor_modules[{mod_key!r}] missing valid sha256")
        mod_path = Path(mod_path_str)
        if not mod_path.is_absolute() or not mod_path.is_relative_to(prefix_path):
            raise ValueError(
                f"Vendor module {mod_key} at {mod_path} escapes resolved_sys_prefix "
                f"{prefix_path}"
            )
        rel_parts = mod_path.relative_to(prefix_path).parts
        expected_rel = PHENIX_VENDOR_SOURCE_RELPATHS[mod_key]
        if (
            len(rel_parts) != 3 + len(expected_rel.parts)
            or rel_parts[0] != "lib"
            or not rel_parts[1].startswith("python")
            or rel_parts[2] != "site-packages"
            or Path(*rel_parts[3:]) != expected_rel
        ):
            raise ValueError(
                f"Vendor module {mod_key} path {mod_path} does not match canonical "
                f"lib/python*/site-packages/{expected_rel} under {prefix_path}"
            )
        if expected_vendor_module_paths is not None:
            expected_mod_path = expected_vendor_module_paths.get(mod_key)
            if expected_mod_path is None or str(mod_path) != str(
                Path(expected_mod_path)
            ):
                raise ValueError(
                    f"Vendor module {mod_key} resolved_path mismatch: expected "
                    f"{expected_mod_path}, runtime loaded {mod_path}"
                )
        if expected_vendor_source_sha256 is not None:
            expected_sha = expected_vendor_source_sha256.get(mod_key)
            if expected_sha != mod_sha:
                raise ValueError(
                    f"Vendor module {mod_key} SHA-256 mismatch: expected "
                    f"{expected_sha}, runtime loaded {mod_sha}"
                )

    # 2. Verify extraction parameters, absence of second-block cutoff, and retained logs.
    extraction_info = phenix_payload.get("extraction")
    if not isinstance(extraction_info, Mapping):
        raise ValueError("phenix_payload missing extraction section")
    if extraction_info.get("labels") != ["F-obs", "SIGF-obs"]:
        raise ValueError(
            f"Unexpected extraction labels: {extraction_info.get('labels')!r}"
        )
    if extraction_info.get("r_free_flags_label") != "R-free-flags":
        raise ValueError(
            f"Unexpected R-free label: {extraction_info.get('r_free_flags_label')!r}"
        )
    if (
        type(extraction_info.get("test_flag_value")) is not int
        or extraction_info.get("test_flag_value") != FREE_FLAG_VALUE
    ):
        raise ValueError(
            f"Expected test_flag_value == {FREE_FLAG_VALUE}, got "
            f"{extraction_info.get('test_flag_value')!r}"
        )
    if extraction_info.get("keep_going") is not False:
        raise ValueError("extract_xtal_data must run with keep_going=False")
    if extraction_info.get("err"):
        raise ValueError(
            f"extract_xtal_data reported errors: {extraction_info.get('err')!r}"
        )
    if extraction_info.get("applied_pdb_header_resolution_cut") is not False:
        raise ValueError(
            "Second-block PDB header resolution cutoff must not be applied"
        )
    if not isinstance(extraction_info.get("log_text"), str):
        raise ValueError("extraction.log_text must be a string")

    diagnostics = phenix_payload.get("diagnostics")
    if not isinstance(diagnostics, Mapping):
        raise ValueError("phenix_payload missing diagnostics section")
    for log_key in (
        "extract_xtal_data_log",
        "model_manager_log",
        "fmodel_update_all_scales_log",
    ):
        if not isinstance(diagnostics.get(log_key), str):
            raise ValueError(f"diagnostics[{log_key!r}] must be a string")
    if diagnostics.get("failure") is not None:
        raise ValueError(
            f"diagnostics.failure must be None on success, got {diagnostics.get('failure')!r}"
        )
    if diagnostics["extract_xtal_data_log"] != extraction_info["log_text"]:
        raise ValueError(
            "diagnostics.extract_xtal_data_log disagrees with extraction.log_text"
        )

    if phenix_diagnostics_path is not None or phenix_diagnostics_payload is not None:
        if phenix_diagnostics_path is not None:
            diag_sha = _sha256_regular_file(Path(phenix_diagnostics_path))
            if (
                cache_manifest_artifacts is not None
                and "phenix_diagnostics_json" in cache_manifest_artifacts
            ):
                expected_diag_sha = cache_manifest_artifacts["phenix_diagnostics_json"][
                    "sha256"
                ]
                if diag_sha != expected_diag_sha:
                    raise ValueError(
                        f"phenix_diagnostics.json SHA-256 {diag_sha} != "
                        f"manifest {expected_diag_sha}"
                    )
            loaded_diag = json.loads(
                Path(phenix_diagnostics_path).read_text(encoding="utf-8")
            )
            if (
                phenix_diagnostics_payload is not None
                and dict(loaded_diag) != dict(phenix_diagnostics_payload)
            ):
                raise ValueError(
                    "phenix_diagnostics_path content disagrees with phenix_diagnostics_payload"
                )
            diag_doc: Mapping[str, Any] = loaded_diag
        else:
            assert phenix_diagnostics_payload is not None
            diag_doc = phenix_diagnostics_payload
        if (
            not isinstance(diag_doc, Mapping)
            or diag_doc.get("status") != "succeeded"
            or diag_doc.get("failure") is not None
            or diag_doc.get("extract_xtal_data_log")
            != diagnostics["extract_xtal_data_log"]
            or diag_doc.get("model_manager_log") != diagnostics["model_manager_log"]
            or diag_doc.get("fmodel_update_all_scales_log")
            != diagnostics["fmodel_update_all_scales_log"]
        ):
            raise ValueError(
                "Standalone phenix_diagnostics.json disagrees with phenix_payload.diagnostics"
            )

    # 3. Recompute canonical scatterer snapshot digests and verify zero mutation.
    xrs_check = phenix_payload.get("xray_structure_invariance")
    if not isinstance(xrs_check, Mapping):
        raise ValueError("phenix_payload missing xray_structure_invariance")
    snapshots = xrs_check.get("snapshots")
    if not isinstance(snapshots, Mapping) or set(snapshots) != {
        "before",
        "after_model",
        "after_fmodel",
    }:
        raise ValueError(
            "xray_structure_invariance must contain snapshots.{before,after_model,after_fmodel}"
        )
    recomputed_xrs = onesar_phenix_measure.compare_scatterer_snapshots(
        snapshots["before"],
        snapshots["after_model"],
        snapshots["after_fmodel"],
    )
    if (
        type(xrs_check.get("n_scatterers")) is not int
        or xrs_check["n_scatterers"] <= 0
        or xrs_check["n_scatterers"] != recomputed_xrs["n_scatterers"]
    ):
        raise ValueError(
            "xray_structure_invariance n_scatterers disagrees with recomputed snapshots"
        )
    before_sha = xrs_check.get("before_sha256")
    after_model_sha = xrs_check.get("after_model_sha256")
    after_fmodel_sha = xrs_check.get("after_fmodel_sha256")
    if (
        before_sha != recomputed_xrs["before_sha256"]
        or after_model_sha != recomputed_xrs["after_model_sha256"]
        or after_fmodel_sha != recomputed_xrs["after_fmodel_sha256"]
    ):
        raise ValueError(
            "xray_structure_invariance snapshot SHA-256 fields disagree with "
            "recomputed scatterer records"
        )
    if (
        not isinstance(before_sha, str)
        or not before_sha
        or before_sha != after_model_sha
        or before_sha != after_fmodel_sha
        or xrs_check.get("identical_before_vs_after_model") is not True
        or xrs_check.get("identical_before_vs_after_fmodel") is not True
        or recomputed_xrs["identical_before_vs_after_model"] is not True
        or recomputed_xrs["identical_before_vs_after_fmodel"] is not True
    ):
        raise ValueError(
            "Model xray_structure mutated during f_model construction or scaling: "
            f"before={before_sha!r}, after_model={after_model_sha!r}, "
            f"after_fmodel={after_fmodel_sha!r}"
        )
    for diff_key in (
        "max_abs_site_cart_diff",
        "max_abs_occupancy_diff",
        "max_abs_u_iso_diff",
        "max_abs_u_star_diff",
    ):
        diff_val = _verify_finite_nonnegative(xrs_check.get(diff_key), diff_key)
        recomputed_diff = float(recomputed_xrs[diff_key])
        if diff_val != 0.0 or recomputed_diff != 0.0:
            raise ValueError(
                f"Non-zero {diff_key} across scaling: reported={diff_val}, "
                f"recomputed={recomputed_diff}"
            )

    # 4. Reconcile extracted pre-fmodel and final effective reflection sets.
    extracted_rows = phenix_payload.get("extracted_pre_fmodel")
    final_rows = phenix_payload.get("final_effective")
    work_rows = phenix_payload.get("actual_work")
    free_rows = phenix_payload.get("actual_free")
    if (
        not isinstance(extracted_rows, list)
        or not isinstance(final_rows, list)
        or not isinstance(work_rows, list)
        or not isinstance(free_rows, list)
    ):
        raise ValueError(
            "phenix_payload must contain list arrays for extracted_pre_fmodel, "
            "final_effective, actual_work, and actual_free"
        )
    if not extracted_rows or not final_rows or not work_rows or not free_rows:
        raise ValueError(
            "extracted_pre_fmodel, final_effective, actual_work, and actual_free "
            "must all be non-empty"
        )

    extracted_by_hkl: dict[str, Mapping[str, Any]] = {}
    for entry in extracted_rows:
        key = _hkl_key(entry.get("hkl"))
        if key in extracted_by_hkl:
            raise ValueError(
                f"Duplicate HKL {key} in extracted_pre_fmodel (many-to-one collision)"
            )
        if key not in raw_by_hkl:
            raise ValueError(
                f"Extracted HKL {key} is absent from input MTZ raw ledger "
                "(unexpected symmetry/reindexing transformation)"
            )
        if key not in eligible_by_hkl:
            raise ValueError(
                f"Extracted HKL {key} was not input-eligible in input MTZ ledger"
            )
        f_obs_val = _verify_finite_positive(
            entry.get("f_obs"), f"extracted_pre_fmodel[{key}].f_obs"
        )
        sigf_val = _verify_finite_positive(
            entry.get("sigf_obs"), f"extracted_pre_fmodel[{key}].sigf_obs"
        )
        is_free = entry.get("is_free")
        if type(is_free) is not bool:
            raise ValueError(f"extracted_pre_fmodel[{key}].is_free must be bool")
        orig_entry = eligible_by_hkl[key]
        if is_free != bool(orig_entry["is_free"]):
            raise ValueError(
                f"Flag mismatch at extracted HKL {key}: PHENIX is_free={is_free}, "
                f"input ledger is_free={orig_entry['is_free']}"
            )
        if not math.isclose(
            f_obs_val, float(orig_entry["f_obs"]), rel_tol=0.0, abs_tol=1e-6
        ) or not math.isclose(
            sigf_val, float(orig_entry["sigf_obs"]), rel_tol=0.0, abs_tol=1e-6
        ):
            raise ValueError(
                f"Pre-scaling extracted F/SIGF drifted from input MTZ at {key}: "
                f"extracted=({f_obs_val}, {sigf_val}), "
                f"input=({orig_entry['f_obs']}, {orig_entry['sigf_obs']})"
            )
        extracted_by_hkl[key] = entry

    final_by_hkl: dict[str, Mapping[str, Any]] = {}
    for entry in final_rows:
        key = _hkl_key(entry.get("hkl"))
        if key in final_by_hkl:
            raise ValueError(f"Duplicate HKL {key} in final_effective")
        if key not in extracted_by_hkl:
            raise ValueError(
                f"Final effective HKL {key} was not in extracted_pre_fmodel"
            )
        f_final = _verify_finite_positive(
            entry.get("f_obs"), f"final_effective[{key}].f_obs"
        )
        sigf_final = _verify_finite_positive(
            entry.get("sigf_obs"), f"final_effective[{key}].sigf_obs"
        )
        is_free = entry.get("is_free")
        if type(is_free) is not bool or is_free != bool(eligible_by_hkl[key]["is_free"]):
            raise ValueError(
                f"Flag mismatch at final_effective HKL {key}: {is_free!r}"
            )
        final_by_hkl[key] = {
            "hkl": list(entry["hkl"]),
            "f_obs": f_final,
            "sigf_obs": sigf_final,
            "is_free": is_free,
        }

    # 5. Reconcile actual_work and actual_free sets and replay R_work / R_free / R_all in float64.
    scales = phenix_payload.get("scales_and_rfactors")
    if not isinstance(scales, Mapping):
        raise ValueError("phenix_payload missing scales_and_rfactors")
    scale_k1_w = _verify_finite_positive(scales.get("scale_k1_w"), "scale_k1_w")
    scale_k1_t = _verify_finite_positive(scales.get("scale_k1_t"), "scale_k1_t")
    scale_k1 = _verify_finite_positive(scales.get("scale_k1"), "scale_k1")
    reported_r_work = _verify_finite_nonnegative(scales.get("r_work"), "r_work")
    reported_r_free = _verify_finite_nonnegative(scales.get("r_free"), "r_free")
    reported_r_all = _verify_finite_nonnegative(scales.get("r_all"), "r_all")
    reported_gap = _verify_finite(
        scales.get("r_free_r_work_gap"), "r_free_r_work_gap"
    )
    reported_extracted_count = _verify_int_count(
        scales.get("extracted_pre_fmodel_count"),
        "scales_and_rfactors.extracted_pre_fmodel_count",
    )
    reported_final_count = _verify_int_count(
        scales.get("final_effective_count"),
        "scales_and_rfactors.final_effective_count",
    )
    reported_work_count = _verify_int_count(
        scales.get("work_count"), "scales_and_rfactors.work_count"
    )
    reported_free_count = _verify_int_count(
        scales.get("free_count"), "scales_and_rfactors.free_count"
    )
    reported_work_num = _verify_finite_nonnegative(
        scales.get("work_numerator"), "scales_and_rfactors.work_numerator"
    )
    reported_work_den = _verify_finite_positive(
        scales.get("work_denominator"), "scales_and_rfactors.work_denominator"
    )
    reported_free_num = _verify_finite_nonnegative(
        scales.get("free_numerator"), "scales_and_rfactors.free_numerator"
    )
    reported_free_den = _verify_finite_positive(
        scales.get("free_denominator"), "scales_and_rfactors.free_denominator"
    )

    work_by_hkl: dict[str, dict[str, Any]] = {}
    work_num = 0.0
    work_den = 0.0
    all_num = 0.0
    all_den = 0.0
    max_f_obs_scale_diff = 0.0

    for entry in work_rows:
        key = _hkl_key(entry.get("hkl"))
        if key in work_by_hkl:
            raise ValueError(f"Duplicate HKL {key} in actual_work")
        if key not in final_by_hkl:
            raise ValueError(f"actual_work HKL {key} not in final_effective")
        orig = eligible_by_hkl[key]
        if orig["is_free"] or orig["r_free_flag"] != WORK_FLAG_VALUE:
            raise ValueError(
                f"actual_work HKL {key} has free flag {orig['r_free_flag']} in input MTZ"
            )
        final_entry = final_by_hkl[key]
        if final_entry["is_free"] is not False:
            raise ValueError(
                f"actual_work HKL {key} has is_free={final_entry['is_free']!r} in final_effective"
            )
        fo = _verify_finite_positive(entry.get("f_obs"), f"actual_work[{key}].f_obs")
        sigfo = _verify_finite_positive(
            entry.get("sigf_obs"), f"actual_work[{key}].sigf_obs"
        )
        if not math.isclose(
            fo, float(final_entry["f_obs"]), rel_tol=1e-15, abs_tol=1e-15
        ) or not math.isclose(
            sigfo, float(final_entry["sigf_obs"]), rel_tol=1e-15, abs_tol=1e-15
        ):
            raise ValueError(
                f"actual_work[{key}] F/SIGF ({fo}, {sigfo}) disagrees with "
                f"final_effective[{key}] ({final_entry['f_obs']}, {final_entry['sigf_obs']})"
            )
        fm_raw_re = _verify_finite(
            entry.get("f_model_real"), f"actual_work[{key}].f_model_real"
        )
        fm_raw_im = _verify_finite(
            entry.get("f_model_imag"), f"actual_work[{key}].f_model_imag"
        )
        fm_raw_amp = _verify_finite_nonnegative(
            entry.get("f_model_amplitude"), f"actual_work[{key}].f_model_amplitude"
        )
        fm_scaled_re = _verify_finite(
            entry.get("f_model_scaled_with_k1_w_real"),
            f"actual_work[{key}].f_model_scaled_with_k1_w_real",
        )
        fm_scaled_im = _verify_finite(
            entry.get("f_model_scaled_with_k1_w_imag"),
            f"actual_work[{key}].f_model_scaled_with_k1_w_imag",
        )
        fm_scaled_amp = _verify_finite_nonnegative(
            entry.get("f_model_scaled_with_k1_w_amplitude"),
            f"actual_work[{key}].f_model_scaled_with_k1_w_amplitude",
        )
        calc_raw_amp = math.hypot(fm_raw_re, fm_raw_im)
        calc_scaled_amp = math.hypot(fm_scaled_re, fm_scaled_im)
        if not math.isclose(calc_raw_amp, fm_raw_amp, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError(
                f"actual_work[{key}] raw amplitude {fm_raw_amp} != hypot {calc_raw_amp}"
            )
        if not math.isclose(
            calc_scaled_amp, fm_scaled_amp, rel_tol=1e-12, abs_tol=1e-12
        ):
            raise ValueError(
                f"actual_work[{key}] scaled amplitude {fm_scaled_amp} != hypot "
                f"{calc_scaled_amp}"
            )
        if not math.isclose(
            fm_scaled_amp, scale_k1_w * fm_raw_amp, rel_tol=1e-12, abs_tol=1e-12
        ):
            raise ValueError(
                f"actual_work[{key}] f_model_scaled_with_k1_w amplitude {fm_scaled_amp} "
                f"disagrees with scale_k1_w * |f_model_work| = {scale_k1_w * fm_raw_amp}"
            )
        if not math.isclose(
            fm_scaled_re, scale_k1_w * fm_raw_re, rel_tol=1e-12, abs_tol=1e-12
        ) or not math.isclose(
            fm_scaled_im, scale_k1_w * fm_raw_im, rel_tol=1e-12, abs_tol=1e-12
        ):
            raise ValueError(
                f"actual_work[{key}] f_model_scaled_with_k1_w complex components "
                f"({fm_scaled_re}, {fm_scaled_im}) disagree with "
                f"scale_k1_w * f_model_work = "
                f"({scale_k1_w * fm_raw_re}, {scale_k1_w * fm_raw_im})"
            )

        work_num += abs(fo - fm_scaled_amp)
        work_den += fo
        all_num += abs(fo - scale_k1 * fm_raw_amp)
        all_den += fo
        max_f_obs_scale_diff = max(
            max_f_obs_scale_diff, abs(fo - float(orig["f_obs"]))
        )
        work_by_hkl[key] = {
            "hkl": list(entry["hkl"]),
            "original_f_obs": float(orig["f_obs"]),
            "original_sigf_obs": float(orig["sigf_obs"]),
            "final_f_obs": fo,
            "final_sigf_obs": sigfo,
            "r_free_flag": WORK_FLAG_VALUE,
            "f_model_amplitude": fm_raw_amp,
            "f_model_scaled_with_k1_w_amplitude": fm_scaled_amp,
        }

    free_by_hkl: dict[str, dict[str, Any]] = {}
    free_num = 0.0
    free_den = 0.0

    for entry in free_rows:
        key = _hkl_key(entry.get("hkl"))
        if key in free_by_hkl:
            raise ValueError(f"Duplicate HKL {key} in actual_free")
        if key in work_by_hkl:
            raise ValueError(
                f"HKL {key} appears in both actual_work and actual_free (non-disjoint)"
            )
        if key not in final_by_hkl:
            raise ValueError(f"actual_free HKL {key} not in final_effective")
        orig = eligible_by_hkl[key]
        if not orig["is_free"] or orig["r_free_flag"] != FREE_FLAG_VALUE:
            raise ValueError(
                f"actual_free HKL {key} has work flag {orig['r_free_flag']} in input MTZ"
            )
        final_entry = final_by_hkl[key]
        if final_entry["is_free"] is not True:
            raise ValueError(
                f"actual_free HKL {key} has is_free={final_entry['is_free']!r} in final_effective"
            )
        fo = _verify_finite_positive(entry.get("f_obs"), f"actual_free[{key}].f_obs")
        sigfo = _verify_finite_positive(
            entry.get("sigf_obs"), f"actual_free[{key}].sigf_obs"
        )
        if not math.isclose(
            fo, float(final_entry["f_obs"]), rel_tol=1e-15, abs_tol=1e-15
        ) or not math.isclose(
            sigfo, float(final_entry["sigf_obs"]), rel_tol=1e-15, abs_tol=1e-15
        ):
            raise ValueError(
                f"actual_free[{key}] F/SIGF ({fo}, {sigfo}) disagrees with "
                f"final_effective[{key}] ({final_entry['f_obs']}, {final_entry['sigf_obs']})"
            )
        fm_raw_re = _verify_finite(
            entry.get("f_model_real"), f"actual_free[{key}].f_model_real"
        )
        fm_raw_im = _verify_finite(
            entry.get("f_model_imag"), f"actual_free[{key}].f_model_imag"
        )
        fm_raw_amp = _verify_finite_nonnegative(
            entry.get("f_model_amplitude"), f"actual_free[{key}].f_model_amplitude"
        )
        fm_scaled_re = _verify_finite(
            entry.get("f_model_scaled_with_k1_t_real"),
            f"actual_free[{key}].f_model_scaled_with_k1_t_real",
        )
        fm_scaled_im = _verify_finite(
            entry.get("f_model_scaled_with_k1_t_imag"),
            f"actual_free[{key}].f_model_scaled_with_k1_t_imag",
        )
        fm_scaled_amp = _verify_finite_nonnegative(
            entry.get("f_model_scaled_with_k1_t_amplitude"),
            f"actual_free[{key}].f_model_scaled_with_k1_t_amplitude",
        )
        calc_raw_amp = math.hypot(fm_raw_re, fm_raw_im)
        calc_scaled_amp = math.hypot(fm_scaled_re, fm_scaled_im)
        if not math.isclose(calc_raw_amp, fm_raw_amp, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError(
                f"actual_free[{key}] raw amplitude {fm_raw_amp} != hypot {calc_raw_amp}"
            )
        if not math.isclose(
            calc_scaled_amp, fm_scaled_amp, rel_tol=1e-12, abs_tol=1e-12
        ):
            raise ValueError(
                f"actual_free[{key}] scaled amplitude {fm_scaled_amp} != hypot "
                f"{calc_scaled_amp}"
            )
        if not math.isclose(
            fm_scaled_amp, scale_k1_t * fm_raw_amp, rel_tol=1e-12, abs_tol=1e-12
        ):
            raise ValueError(
                f"actual_free[{key}] f_model_scaled_with_k1_t amplitude {fm_scaled_amp} "
                f"disagrees with scale_k1_t * |f_model_free| = {scale_k1_t * fm_raw_amp}"
            )
        if not math.isclose(
            fm_scaled_re, scale_k1_t * fm_raw_re, rel_tol=1e-12, abs_tol=1e-12
        ) or not math.isclose(
            fm_scaled_im, scale_k1_t * fm_raw_im, rel_tol=1e-12, abs_tol=1e-12
        ):
            raise ValueError(
                f"actual_free[{key}] f_model_scaled_with_k1_t complex components "
                f"({fm_scaled_re}, {fm_scaled_im}) disagree with "
                f"scale_k1_t * f_model_free = "
                f"({scale_k1_t * fm_raw_re}, {scale_k1_t * fm_raw_im})"
            )

        free_num += abs(fo - fm_scaled_amp)
        free_den += fo
        all_num += abs(fo - scale_k1 * fm_raw_amp)
        all_den += fo
        max_f_obs_scale_diff = max(
            max_f_obs_scale_diff, abs(fo - float(orig["f_obs"]))
        )
        free_by_hkl[key] = {
            "hkl": list(entry["hkl"]),
            "original_f_obs": float(orig["f_obs"]),
            "original_sigf_obs": float(orig["sigf_obs"]),
            "final_f_obs": fo,
            "final_sigf_obs": sigfo,
            "r_free_flag": FREE_FLAG_VALUE,
            "f_model_amplitude": fm_raw_amp,
            "f_model_scaled_with_k1_t_amplitude": fm_scaled_amp,
        }

    if set(work_by_hkl) | set(free_by_hkl) != set(final_by_hkl):
        raise ValueError(
            "Union of actual_work and actual_free HKLs does not equal final_effective"
        )
    if (
        reported_extracted_count != len(extracted_by_hkl)
        or reported_final_count != len(final_by_hkl)
        or reported_work_count != len(work_by_hkl)
        or reported_free_count != len(free_by_hkl)
    ):
        raise ValueError(
            "Reported scales_and_rfactors counts disagree with reflection arrays: "
            f"reported=({reported_extracted_count}, {reported_final_count}, "
            f"{reported_work_count}, {reported_free_count}), "
            f"actual=({len(extracted_by_hkl)}, {len(final_by_hkl)}, "
            f"{len(work_by_hkl)}, {len(free_by_hkl)})"
        )
    if work_den <= 0.0 or free_den <= 0.0 or all_den <= 0.0:
        raise ValueError("Work, free, and all denominators must be strictly positive")

    if not math.isclose(reported_work_num, work_num, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError(
            f"Reported work_numerator {reported_work_num} != recomputed {work_num}"
        )
    if not math.isclose(reported_work_den, work_den, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError(
            f"Reported work_denominator {reported_work_den} != recomputed {work_den}"
        )
    if not math.isclose(reported_free_num, free_num, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError(
            f"Reported free_numerator {reported_free_num} != recomputed {free_num}"
        )
    if not math.isclose(reported_free_den, free_den, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError(
            f"Reported free_denominator {reported_free_den} != recomputed {free_den}"
        )
    if "all_numerator" in scales:
        reported_all_num = _verify_finite_nonnegative(
            scales.get("all_numerator"), "scales_and_rfactors.all_numerator"
        )
        if not math.isclose(reported_all_num, all_num, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError(
                f"Reported all_numerator {reported_all_num} != recomputed {all_num}"
            )
    if "all_denominator" in scales:
        reported_all_den = _verify_finite_positive(
            scales.get("all_denominator"), "scales_and_rfactors.all_denominator"
        )
        if not math.isclose(reported_all_den, all_den, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError(
                f"Reported all_denominator {reported_all_den} != recomputed {all_den}"
            )

    replayed_r_work = work_num / work_den
    replayed_r_free = free_num / free_den
    replayed_r_all = all_num / all_den
    replayed_gap = replayed_r_free - replayed_r_work

    if not math.isclose(replayed_r_work, reported_r_work, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError(
            f"Replayed r_work {replayed_r_work:.15f} disagrees with native "
            f"fmodel.r_work() {reported_r_work:.15f}"
        )
    if not math.isclose(replayed_r_free, reported_r_free, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError(
            f"Replayed r_free {replayed_r_free:.15f} disagrees with native "
            f"fmodel.r_free() {reported_r_free:.15f}"
        )
    if not math.isclose(replayed_r_all, reported_r_all, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError(
            f"Replayed r_all {replayed_r_all:.15f} disagrees with native "
            f"fmodel.r_all() {reported_r_all:.15f}"
        )
    if not math.isclose(replayed_gap, reported_gap, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError(
            f"Replayed r_free - r_work gap {replayed_gap:.15f} disagrees with "
            f"reported {reported_gap:.15f}"
        )

    # 5b. Validate retained runtime unit cell against installed CCP4/iotbx float32
    # conversion of the admitted input cell, then replay stage resolution ranges (#1020).
    expected_runtime_float32_cell = ccp4_mtz_float32_unit_cell(
        validated_input_cell,
        label="input_ledger.crystallographic_context.cell_a_b_c_alpha_beta_gamma",
    )
    crystal_symmetry = phenix_payload.get("crystal_symmetry")
    if not isinstance(crystal_symmetry, Mapping):
        raise ValueError("phenix_payload missing crystal_symmetry section")
    space_group_symbol = crystal_symmetry.get("space_group_symbol")
    if not isinstance(space_group_symbol, str) or not space_group_symbol.strip():
        raise ValueError(
            "phenix_payload.crystal_symmetry.space_group_symbol must be a non-empty string"
        )
    raw_runtime_cell = crystal_symmetry.get("unit_cell")
    if not isinstance(raw_runtime_cell, (list, tuple)) or len(raw_runtime_cell) != 6:
        raise ValueError(
            "phenix_payload.crystal_symmetry.unit_cell must be a 6-element numeric sequence, "
            f"got {raw_runtime_cell!r}"
        )
    for idx, val in enumerate(raw_runtime_cell):
        _verify_finite_positive(
            val, f"phenix_payload.crystal_symmetry.unit_cell[{idx}]"
        )
    validated_runtime_cell = validate_unit_cell_parameters(
        raw_runtime_cell, label="phenix_payload.crystal_symmetry.unit_cell"
    )
    for idx, (param_name, rt_val, exp_val) in enumerate(
        zip(
            ("a", "b", "c", "alpha", "beta", "gamma"),
            validated_runtime_cell,
            expected_runtime_float32_cell,
        )
    ):
        if not math.isclose(rt_val, exp_val, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError(
                f"phenix_payload.crystal_symmetry.unit_cell[{idx}] ({param_name}) "
                f"{rt_val:.15f} disagrees with installed CCP4/iotbx float32 "
                f"conversion {exp_val:.15f} of admitted input cell "
                f"{validated_input_cell[idx]:.15f}"
            )
    validated_runtime_space_group = validate_runtime_space_group(
        crystal_symmetry,
        input_context.get("symmetry"),
    )

    resolution_ranges = phenix_payload.get("resolution_ranges")
    if not isinstance(resolution_ranges, Mapping) or set(
        resolution_ranges
    ) != set(EXPECTED_RESOLUTION_STAGES):
        raise ValueError(
            "phenix_payload.resolution_ranges must be a mapping with exact keys "
            f"{list(EXPECTED_RESOLUTION_STAGES)!r}, got "
            f"{list(resolution_ranges) if isinstance(resolution_ranges, Mapping) else resolution_ranges!r}"
        )
    stage_hkls_by_name: dict[str, list[Any]] = {
        "extracted_pre_fmodel": [
            entry["hkl"] for entry in extracted_by_hkl.values()
        ],
        "final_effective": [entry["hkl"] for entry in final_by_hkl.values()],
        "actual_work": [entry["hkl"] for entry in work_by_hkl.values()],
        "actual_free": [entry["hkl"] for entry in free_by_hkl.values()],
    }
    reconciled_resolution_ranges: dict[str, dict[str, float]] = {}
    for stage_name in EXPECTED_RESOLUTION_STAGES:
        stage_range = resolution_ranges.get(stage_name)
        if not isinstance(stage_range, Mapping) or set(stage_range) != {
            "d_max",
            "d_min",
        }:
            raise ValueError(
                f"resolution_ranges[{stage_name!r}] must be a mapping with exact keys "
                f"['d_max', 'd_min'], got "
                f"{list(stage_range) if isinstance(stage_range, Mapping) else stage_range!r}"
            )
        reported_d_max = _verify_finite_positive(
            stage_range.get("d_max"), f"resolution_ranges[{stage_name!r}].d_max"
        )
        reported_d_min = _verify_finite_positive(
            stage_range.get("d_min"), f"resolution_ranges[{stage_name!r}].d_min"
        )
        if reported_d_max < reported_d_min:
            raise ValueError(
                f"resolution_ranges[{stage_name!r}] has inverted bounds: "
                f"d_max={reported_d_max} < d_min={reported_d_min}"
            )
        recomputed_range = compute_stage_resolution_range(
            stage_hkls_by_name[stage_name],
            validated_runtime_cell,
            stage_label=stage_name,
        )
        recomputed_d_max = recomputed_range["d_max"]
        recomputed_d_min = recomputed_range["d_min"]
        if not math.isclose(
            reported_d_max, recomputed_d_max, rel_tol=1e-12, abs_tol=1e-12
        ):
            raise ValueError(
                f"resolution_ranges[{stage_name!r}].d_max {reported_d_max:.15f} "
                f"disagrees with recomputed {recomputed_d_max:.15f}"
            )
        if not math.isclose(
            reported_d_min, recomputed_d_min, rel_tol=1e-12, abs_tol=1e-12
        ):
            raise ValueError(
                f"resolution_ranges[{stage_name!r}].d_min {reported_d_min:.15f} "
                f"disagrees with recomputed {recomputed_d_min:.15f}"
            )
        reconciled_resolution_ranges[stage_name] = {
            "d_max": reported_d_max,
            "d_min": reported_d_min,
            "recomputed_d_max": recomputed_d_max,
            "recomputed_d_min": recomputed_d_min,
            "d_max_abs_diff": abs(recomputed_d_max - reported_d_max),
            "d_min_abs_diff": abs(recomputed_d_min - reported_d_min),
        }

    # 6. Validate fresh complex map-coefficient export metadata, JSON records, and MTZ files.
    map_coeffs = phenix_payload.get("map_coefficients")
    if not isinstance(map_coeffs, Mapping):
        raise ValueError("phenix_payload missing map_coefficients section")
    expected_maps = {
        "2mFo-DFc": ("2FOFCWT", "PH2FOFCWT"),
        "mFo-DFc": ("FOFCWT", "PHFOFCWT"),
    }
    map_summary: dict[str, Any] = {}
    map_records_by_hkl: dict[str, dict[str, Mapping[str, Any]]] = {}
    for map_key, (amp_label, phase_label) in expected_maps.items():
        mdata = map_coeffs.get(map_key)
        if not isinstance(mdata, Mapping):
            raise ValueError(f"map_coefficients missing {map_key!r}")
        if (
            mdata.get("map_type") != map_key
            or mdata.get("amplitude_label") != amp_label
            or mdata.get("phase_label") != phase_label
        ):
            raise ValueError(f"Invalid labels for map_coefficients[{map_key!r}]")
        params = mdata.get("parameters")
        if not isinstance(params, Mapping):
            raise ValueError(f"map_coefficients[{map_key!r}] missing parameters")
        if (
            params.get("acentrics_scale") != 2.0
            or params.get("centrics_pre_scale") != 1.0
            or params.get("exclude_free_r_reflections") is not False
            or params.get("fill_missing") is not False
            or params.get("isotropize") is not True
            or params.get("sharp") is not False
        ):
            raise ValueError(
                f"map_coefficients[{map_key!r}] parameters violate preregistered "
                f"contract: {params!r}"
            )
        records = mdata.get("records")
        if not isinstance(records, list) or len(records) != len(final_by_hkl):
            raise ValueError(
                f"map_coefficients[{map_key!r}] record count must equal "
                f"final_effective count ({len(final_by_hkl)})"
            )
        reported_n_refl = _verify_int_count(
            mdata.get("n_reflections"), f"map_coefficients[{map_key!r}].n_reflections"
        )
        reported_centric_count = _verify_nonnegative_int_count(
            mdata.get("centric_count"), f"map_coefficients[{map_key!r}].centric_count"
        )
        reported_acentric_count = _verify_nonnegative_int_count(
            mdata.get("acentric_count"),
            f"map_coefficients[{map_key!r}].acentric_count",
        )
        if reported_n_refl != len(records):
            raise ValueError(
                f"map_coefficients[{map_key!r}].n_reflections {reported_n_refl} != "
                f"len(records) {len(records)}"
            )
        by_hkl: dict[str, Mapping[str, Any]] = {}
        centric_count = 0
        for rec in records:
            rkey = _hkl_key(rec.get("hkl"))
            if rkey in by_hkl:
                raise ValueError(
                    f"Duplicate HKL {rkey} in map_coefficients[{map_key!r}]"
                )
            if rkey not in final_by_hkl:
                raise ValueError(
                    f"Unexpected HKL {rkey} in map_coefficients[{map_key!r}]"
                )
            re_val = _verify_finite(rec.get("real"), f"{map_key}[{rkey}].real")
            im_val = _verify_finite(rec.get("imag"), f"{map_key}[{rkey}].imag")
            amp_val = _verify_finite_nonnegative(
                rec.get("amplitude"), f"{map_key}[{rkey}].amplitude"
            )
            phase_val = _verify_finite(
                rec.get("phase_deg"), f"{map_key}[{rkey}].phase_deg"
            )
            if type(rec.get("is_centric")) is not bool:
                raise ValueError(f"{map_key}[{rkey}].is_centric must be bool")
            calc_amp = math.hypot(re_val, im_val)
            if not math.isclose(calc_amp, amp_val, rel_tol=1e-12, abs_tol=1e-12):
                raise ValueError(
                    f"{map_key}[{rkey}] amplitude {amp_val} != hypot(real, imag) {calc_amp}"
                )
            if calc_amp > 1e-12:
                calc_phase = math.degrees(math.atan2(im_val, re_val))
                if _circular_phase_diff_deg(calc_phase, phase_val) > 1e-9:
                    raise ValueError(
                        f"{map_key}[{rkey}] phase_deg {phase_val} disagrees with "
                        f"atan2(imag, real) {calc_phase}"
                    )
            if rec["is_centric"]:
                centric_count += 1
            by_hkl[rkey] = rec
        acentric_count = len(records) - centric_count
        if (
            reported_centric_count != centric_count
            or reported_acentric_count != acentric_count
        ):
            raise ValueError(
                f"map_coefficients[{map_key!r}] centric/acentric counts "
                f"({reported_centric_count}, {reported_acentric_count}) != "
                f"({centric_count}, {acentric_count})"
            )
        map_records_by_hkl[map_key] = by_hkl
        map_summary[map_key] = {
            "amplitude_label": amp_label,
            "phase_label": phase_label,
            "n_reflections": len(records),
            "centric_count": centric_count,
            "acentric_count": acentric_count,
            "parameters": dict(params),
            "coefficient_semantics": mdata.get("coefficient_semantics"),
        }

    mtz_supplements = map_coeffs.get("mtz_supplements")
    if not isinstance(mtz_supplements, Mapping):
        raise ValueError("map_coefficients missing mtz_supplements")
    expected_maps_columns = [
        "H",
        "K",
        "L",
        "2FOFCWT",
        "PH2FOFCWT",
        "FOFCWT",
        "PHFOFCWT",
    ]
    expected_obs_pair_columns = [
        "H",
        "K",
        "L",
        "2FOFCWT",
        "PH2FOFCWT",
    ]
    if mtz_supplements.get("phx_maps_columns") != expected_maps_columns:
        raise ValueError(
            f"Unexpected phx_maps.mtz columns: {mtz_supplements.get('phx_maps_columns')!r}"
        )
    if mtz_supplements.get("obs_pair_only_columns") != expected_obs_pair_columns:
        raise ValueError(
            "Unexpected PHX_OBS_PAIR_ONLY.mtz columns: "
            f"{mtz_supplements.get('obs_pair_only_columns')!r}"
        )

    if phx_maps_mtz_path is not None:
        _sha256_regular_file(Path(phx_maps_mtz_path))
        loaded_maps_bytes = Path(phx_maps_mtz_path).read_bytes()
        if phx_maps_mtz_bytes is not None and phx_maps_mtz_bytes != loaded_maps_bytes:
            raise ValueError("phx_maps_mtz_path bytes disagree with phx_maps_mtz_bytes")
        maps_bytes = loaded_maps_bytes
    elif phx_maps_mtz_bytes is not None:
        maps_bytes = bytes(phx_maps_mtz_bytes)
    else:
        raise ValueError(
            "reconcile_phenix_rfactor_output requires phx_maps_mtz_path or phx_maps_mtz_bytes"
        )

    if phx_obs_pair_only_mtz_path is not None:
        _sha256_regular_file(Path(phx_obs_pair_only_mtz_path))
        loaded_pair_bytes = Path(phx_obs_pair_only_mtz_path).read_bytes()
        if (
            phx_obs_pair_only_mtz_bytes is not None
            and phx_obs_pair_only_mtz_bytes != loaded_pair_bytes
        ):
            raise ValueError(
                "phx_obs_pair_only_mtz_path bytes disagree with phx_obs_pair_only_mtz_bytes"
            )
        obs_pair_bytes = loaded_pair_bytes
    elif phx_obs_pair_only_mtz_bytes is not None:
        obs_pair_bytes = bytes(phx_obs_pair_only_mtz_bytes)
    else:
        raise ValueError(
            "reconcile_phenix_rfactor_output requires phx_obs_pair_only_mtz_path or "
            "phx_obs_pair_only_mtz_bytes"
        )

    maps_sha = _sha256_bytes(maps_bytes)
    obs_pair_sha = _sha256_bytes(obs_pair_bytes)
    if mtz_supplements.get("phx_maps_sha256") != maps_sha:
        raise ValueError(
            f"phx_maps.mtz SHA-256 {maps_sha} disagrees with "
            f"mtz_supplements.phx_maps_sha256 {mtz_supplements.get('phx_maps_sha256')!r}"
        )
    if mtz_supplements.get("obs_pair_only_sha256") != obs_pair_sha:
        raise ValueError(
            f"PHX_OBS_PAIR_ONLY.mtz SHA-256 {obs_pair_sha} disagrees with "
            f"mtz_supplements.obs_pair_only_sha256 {mtz_supplements.get('obs_pair_only_sha256')!r}"
        )
    if cache_manifest_artifacts is not None:
        if cache_manifest_artifacts.get("phx_maps_mtz", {}).get("sha256") != maps_sha:
            raise ValueError(
                "phx_maps.mtz SHA-256 disagrees with cache manifest artifacts"
            )
        if (
            cache_manifest_artifacts.get("phx_obs_pair_only_mtz", {}).get("sha256")
            != obs_pair_sha
        ):
            raise ValueError(
                "PHX_OBS_PAIR_ONLY.mtz SHA-256 disagrees with cache manifest artifacts"
            )

    maps_mtz = inspect_map_mtz_bytes(
        maps_bytes,
        expected_columns=expected_maps_columns,
        expected_column_types=["H", "H", "H", "F", "P", "F", "P"],
    )
    obs_pair_mtz = inspect_map_mtz_bytes(
        obs_pair_bytes,
        expected_columns=expected_obs_pair_columns,
        expected_column_types=["H", "H", "H", "F", "P"],
    )
    if maps_mtz["crystallographic_context"] != obs_pair_mtz["crystallographic_context"]:
        raise ValueError(
            "PHX_OBS_PAIR_ONLY.mtz crystallographic context differs from phx_maps.mtz"
        )
    maps_ctx = maps_mtz["crystallographic_context"]
    input_cell = list(validated_input_cell)
    maps_cell = list(
        validate_unit_cell_parameters(
            maps_ctx.get("cell_a_b_c_alpha_beta_gamma"),
            label="map_mtz.crystallographic_context.cell_a_b_c_alpha_beta_gamma",
        )
    )
    if len(maps_cell) != 6 or any(
        not math.isclose(a, b, rel_tol=0.0, abs_tol=1e-3)
        for a, b in zip(input_cell, maps_cell)
    ):
        raise ValueError(
            f"Map MTZ cell {maps_cell} disagrees with input MTZ cell {input_cell}"
        )
    input_symm = input_context["symmetry"]
    maps_symm = maps_ctx["symmetry"]
    for symm_key in (
        "operator_count",
        "primitive_operator_count",
        "lattice",
        "space_group_number",
        "space_group_symbol",
        "operators_xyz",
    ):
        if maps_symm.get(symm_key) != input_symm.get(symm_key):
            raise ValueError(
                f"Map MTZ symmetry.{symm_key} {maps_symm.get(symm_key)!r} != "
                f"input MTZ {input_symm.get(symm_key)!r}"
            )
    validated_runtime_space_group = validate_runtime_space_group(
        crystal_symmetry,
        input_symm,
        maps_symmetry=maps_symm,
    )

    if set(maps_mtz["rows_by_hkl"]) != set(final_by_hkl) or set(
        obs_pair_mtz["rows_by_hkl"]
    ) != set(final_by_hkl):
        raise ValueError(
            "Map MTZ HKL sets do not match final_effective HKL set"
        )

    for rkey in final_by_hkl:
        rec_2fofc = map_records_by_hkl["2mFo-DFc"][rkey]
        rec_fofc = map_records_by_hkl["mFo-DFc"][rkey]
        m_row = maps_mtz["rows_by_hkl"][rkey]
        p_row = obs_pair_mtz["rows_by_hkl"][rkey]
        if (
            p_row["hkl"] != m_row["hkl"]
            or p_row["words"]["2FOFCWT"] != m_row["words"]["2FOFCWT"]
            or p_row["words"]["PH2FOFCWT"] != m_row["words"]["PH2FOFCWT"]
        ):
            raise ValueError(
                f"PHX_OBS_PAIR_ONLY.mtz 2FOFCWT/PH2FOFCWT words differ from "
                f"phx_maps.mtz at HKL {rkey}"
            )
        amp_2fofc = float(rec_2fofc["amplitude"])
        ph_2fofc = float(rec_2fofc["phase_deg"])
        amp_fofc = float(rec_fofc["amplitude"])
        ph_fofc = float(rec_fofc["phase_deg"])
        if not math.isclose(
            m_row["values"]["2FOFCWT"], amp_2fofc, rel_tol=1e-5, abs_tol=1e-5
        ):
            raise ValueError(
                f"phx_maps.mtz 2FOFCWT {m_row['values']['2FOFCWT']} disagrees with "
                f"JSON amplitude {amp_2fofc} at HKL {rkey}"
            )
        if amp_2fofc > 1e-6 and (
            _circular_phase_diff_deg(m_row["values"]["PH2FOFCWT"], ph_2fofc) > 5e-4
        ):
            raise ValueError(
                f"phx_maps.mtz PH2FOFCWT {m_row['values']['PH2FOFCWT']} disagrees with "
                f"JSON phase_deg {ph_2fofc} at HKL {rkey}"
            )
        if not math.isclose(
            m_row["values"]["FOFCWT"], amp_fofc, rel_tol=1e-5, abs_tol=1e-5
        ):
            raise ValueError(
                f"phx_maps.mtz FOFCWT {m_row['values']['FOFCWT']} disagrees with "
                f"JSON amplitude {amp_fofc} at HKL {rkey}"
            )
        if amp_fofc > 1e-6 and (
            _circular_phase_diff_deg(m_row["values"]["PHFOFCWT"], ph_fofc) > 5e-4
        ):
            raise ValueError(
                f"phx_maps.mtz PHFOFCWT {m_row['values']['PHFOFCWT']} disagrees with "
                f"JSON phase_deg {ph_fofc} at HKL {rkey}"
            )

    # 7. Compute exact stage-by-stage set differences without inventing per-reflection causes.
    raw_hkl_set = set(raw_by_hkl)
    eligible_hkl_set = set(eligible_by_hkl)
    extracted_hkl_set = set(extracted_by_hkl)
    final_hkl_set = set(final_by_hkl)

    raw_to_eligible_excluded = sorted(
        (list(raw_by_hkl[k]["hkl"]) for k in (raw_hkl_set - eligible_hkl_set)),
        key=tuple,
    )
    eligible_to_extracted_excluded = sorted(
        (list(eligible_by_hkl[k]["hkl"]) for k in (eligible_hkl_set - extracted_hkl_set)),
        key=tuple,
    )
    extracted_to_final_excluded = sorted(
        (list(extracted_by_hkl[k]["hkl"]) for k in (extracted_hkl_set - final_hkl_set)),
        key=tuple,
    )

    return {
        "reconciliation_status": "verified",
        "counts": {
            "raw_mtz_total": len(raw_hkl_set),
            "input_eligible_total": len(eligible_hkl_set),
            "extracted_pre_fmodel_total": len(extracted_hkl_set),
            "final_effective_total": len(final_hkl_set),
            "actual_work_total": len(work_by_hkl),
            "actual_free_total": len(free_by_hkl),
            "excluded_raw_to_input_eligible": len(raw_to_eligible_excluded),
            "excluded_input_eligible_to_extracted": len(eligible_to_extracted_excluded),
            "excluded_extracted_to_final_effective": len(extracted_to_final_excluded),
        },
        "set_differences": {
            "raw_to_input_eligible_excluded_hkls": raw_to_eligible_excluded,
            "input_eligible_to_extracted_excluded_hkls": eligible_to_extracted_excluded,
            "extracted_to_final_effective_excluded_hkls": extracted_to_final_excluded,
        },
        "rfactors": {
            "r_work": reported_r_work,
            "r_free": reported_r_free,
            "r_all": reported_r_all,
            "r_free_r_work_gap": reported_gap,
            "replayed_r_work": replayed_r_work,
            "replayed_r_free": replayed_r_free,
            "replayed_r_all": replayed_r_all,
            "replayed_r_free_r_work_gap": replayed_gap,
            "r_work_abs_diff": abs(replayed_r_work - reported_r_work),
            "r_free_abs_diff": abs(replayed_r_free - reported_r_free),
            "r_all_abs_diff": abs(replayed_r_all - reported_r_all),
            "work_numerator": work_num,
            "work_denominator": work_den,
            "free_numerator": free_num,
            "free_denominator": free_den,
            "all_numerator": all_num,
            "all_denominator": all_den,
            "scale_k1_w": scale_k1_w,
            "scale_k1_t": scale_k1_t,
            "scale_k1": scale_k1,
            "max_abs_f_obs_rescaling_diff": max_f_obs_scale_diff,
        },
        "resolution_ranges": reconciled_resolution_ranges,
        "crystal_symmetry": {
            "input_header_cell_tokens": list(
                input_context["cell_a_b_c_alpha_beta_gamma"]
            ),
            "input_header_cell_float64": list(validated_input_cell),
            "expected_ccp4_mtz_float32_cell": list(expected_runtime_float32_cell),
            "effective_runtime_unit_cell": list(validated_runtime_cell),
            "max_abs_runtime_vs_float32_diff": max(
                abs(rt - exp)
                for rt, exp in zip(
                    validated_runtime_cell, expected_runtime_float32_cell
                )
            ),
            "max_abs_runtime_vs_decimal_header_diff": max(
                abs(rt - dec)
                for rt, dec in zip(validated_runtime_cell, validated_input_cell)
            ),
            "space_group_symbol": validated_runtime_space_group[
                "space_group_symbol"
            ],
            "space_group_number": validated_runtime_space_group[
                "space_group_number"
            ],
            "raw_space_group_operators_xyz": validated_runtime_space_group[
                "raw_space_group_operators_xyz"
            ],
            "normalized_space_group_operators_xyz": validated_runtime_space_group[
                "normalized_space_group_operators_xyz"
            ],
            "normalized_lookup_symbol": validated_runtime_space_group[
                "normalized_lookup_symbol"
            ],
            "symmetry_normalization_policy": validated_runtime_space_group[
                "symmetry_normalization_policy"
            ],
            "precision_provenance": (
                "ccp4io/libccp4/ccp4/mtzdata.h:86 and cmtzlib.c:476,549-551 store "
                "MTZ CELL/DCELL header parameters as IEEE-754 float32 and "
                "iotbx/mtz/crystal.cpp:61-67 promotes them to float64; strict "
                "1e-12 stage resolution replay uses the validated effective "
                "runtime unit cell."
            ),
        },
        "xray_structure_invariance": dict(xrs_check),
        "map_coefficients_summary": map_summary,
        "mtz_supplements": dict(mtz_supplements),
    }


def _verify_no_protstruct_overrides() -> None:
    overrides = sorted(
        name for name in os.environ if name.startswith("PROTSTRUCT_")
    )
    if overrides:
        raise ValueError(
            "Canary measurement requires default repository toolchain resolution "
            f"with no PROTSTRUCT_* environment overrides; found {overrides}"
        )


def run_phenix_rfactor_operation(
    evidence_root: Path,
    subject_id: str = "R4",
    *,
    repo_root: Path = REPO_ROOT,
    archive_path: Path | None = None,
    timeout: float = 900.0,
    require_no_protstruct_overrides: bool = True,
    runner: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Stage ``subject_id`` inputs and run the cached PHENIX first-block R-factor worker.

    Uses :func:`refinement_cache.cached_phenix_operation` via the default
    toolchain resolver, binds the helper and installed PHENIX Python module
    sources into the operation identity, verifies that staged inputs remain
    byte-identical after execution, and reconciles the full-precision output.
    """
    if require_no_protstruct_overrides:
        _verify_no_protstruct_overrides()

    staged = stage_subject_inputs(
        evidence_root,
        subject_id=subject_id,
        repo_root=repo_root,
        archive_path=archive_path,
    )
    fresh_root: Path = staged["evidence_root"]
    original_pdb_path: Path = staged["original_pdb_path"]
    original_mtz_path: Path = staged["original_mtz_path"]
    projected_mtz_path: Path = staged["projected_mtz_path"]
    input_ledger_path: Path = staged["input_ledger_path"]
    input_ledger: dict[str, Any] = staged["input_ledger"]

    phenix_dir = fresh_root / "phenix"
    phenix_dir.mkdir(parents=True, exist_ok=False)
    preflight_build_json_path = (
        phenix_dir / "phenix_preflight_build_evidence.json"
    )
    admission_failure_json_path = (
        phenix_dir / "phenix_build_admission_failure.json"
    )
    operation_failure_json_path = (
        phenix_dir / "phenix_operation_failure.json"
    )
    params_path = phenix_dir / "phenix_operation_parameters.json"
    reconciled_json_path = phenix_dir / "phenix_reconciled_manifest.json"
    cache_dir = phenix_dir / "cache"

    raw_build_evidence = toolchain.phenix_build_evidence()
    build_info: Any = (
        dict(raw_build_evidence)
        if isinstance(raw_build_evidence, Mapping)
        else raw_build_evidence
    )
    onesar_phenix_measure._atomic_write_json_checkpoint(
        build_info, preflight_build_json_path
    )
    preflight_build_sha256 = _sha256_regular_file(preflight_build_json_path)

    preflight_stage = "validate_measured_phenix_build"
    try:
        validated_preflight = validate_measured_phenix_build(
            build_info, expected_version=toolchain.PHENIX_VERSION
        )
        expected_resolved_prefix = validated_preflight["resolved_prefix"]

        preflight_stage = "resolve_phenix_vendor_source_files"
        vendor_sources = resolve_phenix_vendor_source_files(
            Path(expected_resolved_prefix)
        )
        vendor_source_sha256 = {
            key: _sha256_regular_file(path)
            for key, path in vendor_sources.items()
        }
    except Exception as exc:
        admission_failure_record = {
            "schema_version": 1,
            "status": "rejected",
            "subject_id": subject_id,
            "expected_phenix_version": toolchain.PHENIX_VERSION,
            "preflight_build_evidence_json_path": str(
                preflight_build_json_path
            ),
            "preflight_build_evidence_sha256": preflight_build_sha256,
            "measured_build": copy.deepcopy(build_info),
            "failure": {
                "failed_stage": preflight_stage,
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
            },
            "worker_launched": False,
        }
        onesar_phenix_measure._atomic_write_json_checkpoint(
            admission_failure_record, admission_failure_json_path
        )
        raise

    helper_script = (_SCRIPTS_DIR / "onesar_phenix_measure.py").resolve(strict=True)
    _sha256_regular_file(helper_script)

    operation_parameters = {
        "schema_version": 1,
        "algorithm": "mmtbx.model_vs_data.first_block_public_api",
        "subject_id": subject_id,
        "expected_resolved_prefix": expected_resolved_prefix,
        "expected_phenix_version": toolchain.PHENIX_VERSION,
        "labels": list(OBSERVATION_LABELS[:2]),
        "r_free_flags_label": OBSERVATION_LABELS[2],
        "test_flag_value": FREE_FLAG_VALUE,
        "r_free_flags_generate": False,
        "ignore_r_free_flags": False,
        "keep_going": False,
        "scattering_table": "n_gaussian",
        "twin_law": None,
        "update_f_part1": True,
        "apply_pdb_header_resolution_cut": False,
        "map_coefficients": {
            "acentrics_scale": 2.0,
            "centrics_pre_scale": 1.0,
            "exclude_free_r_reflections": False,
            "fill_missing": False,
            "isotropize": True,
            "sharp": False,
            "phases_prefix": "PH",
        },
    }
    onesar_phenix_measure.validate_parameters_contract(operation_parameters)
    onesar_phenix_measure._atomic_write_json_checkpoint(
        operation_parameters, params_path
    )

    input_files: dict[str, Path] = {
        "model_pdb": original_pdb_path,
        "projected_observations_mtz": projected_mtz_path,
        "helper_script": helper_script,
        "parameters_json": params_path,
        **vendor_sources,
    }
    arguments: list[str | Path | refinement_cache.OutputTemplate] = [
        helper_script,
        "--pdb",
        original_pdb_path,
        "--mtz",
        projected_mtz_path,
        "--params-json",
        params_path,
        "--out-json",
        refinement_cache.OutputTemplate("{operation_dir}/phenix_rfactors.json"),
        "--out-maps-mtz",
        refinement_cache.OutputTemplate("{operation_dir}/phx_maps.mtz"),
        "--out-obs-pair-mtz",
        refinement_cache.OutputTemplate("{operation_dir}/PHX_OBS_PAIR_ONLY.mtz"),
        "--out-diagnostics-json",
        refinement_cache.OutputTemplate("{operation_dir}/phenix_diagnostics.json"),
        "--out-partial-json",
        refinement_cache.OutputTemplate(
            "{operation_dir}/phenix_rfactors_partial_evidence.json"
        ),
    ]
    required_outputs: dict[str, str] = {
        "phenix_rfactors_json": "phenix_rfactors.json",
        "phx_maps_mtz": "phx_maps.mtz",
        "phx_obs_pair_only_mtz": "PHX_OBS_PAIR_ONLY.mtz",
        "phenix_diagnostics_json": "phenix_diagnostics.json",
    }
    operation_name = f"onesar_phenix_first_block_rfactors_{subject_id}"

    def _retain_parent_operation_failure(
        attempt_dir: Path | None,
        exc: Exception,
        *,
        failed_stage: str,
    ) -> None:
        retained_artifacts: dict[str, dict[str, str]] = {}
        diagnostics_summary: dict[str, Any] | None = None
        partial_summary: dict[str, Any] | None = None
        if attempt_dir is not None and attempt_dir.is_dir():
            candidate_files = {
                "stdout_log": attempt_dir / "stdout.log",
                "invocation_json": attempt_dir / "invocation.json",
                "phenix_diagnostics_json": (
                    attempt_dir / "phenix_diagnostics.json"
                ),
                "phenix_partial_evidence_json": (
                    attempt_dir / "phenix_rfactors_partial_evidence.json"
                ),
                "phx_maps_mtz": attempt_dir / "phx_maps.mtz",
                "phx_obs_pair_only_mtz": attempt_dir / "PHX_OBS_PAIR_ONLY.mtz",
                "phenix_rfactors_json": attempt_dir / "phenix_rfactors.json",
                "manifest_json": attempt_dir / "success.json",
            }
            for label, cand_path in candidate_files.items():
                if cand_path.is_file() and not cand_path.is_symlink():
                    retained_artifacts[label] = {
                        "path": str(cand_path),
                        "sha256": _sha256_regular_file(cand_path),
                    }
            diag_cand = candidate_files["phenix_diagnostics_json"]
            if "phenix_diagnostics_json" in retained_artifacts:
                try:
                    diag_doc = json.loads(
                        diag_cand.read_text(encoding="utf-8")
                    )
                    if isinstance(diag_doc, Mapping):
                        diagnostics_summary = {
                            "status": diag_doc.get("status"),
                            "current_phase": diag_doc.get("current_phase"),
                            "completed_raw_stages": diag_doc.get(
                                "completed_raw_stages"
                            ),
                            "partial_evidence_status": diag_doc.get(
                                "partial_evidence_status"
                            ),
                            "failure": diag_doc.get("failure"),
                        }
                except Exception:
                    diagnostics_summary = None
            partial_cand = candidate_files["phenix_partial_evidence_json"]
            if "phenix_partial_evidence_json" in retained_artifacts:
                try:
                    partial_doc = json.loads(
                        partial_cand.read_text(encoding="utf-8")
                    )
                    if isinstance(partial_doc, Mapping):
                        partial_summary = {
                            "artifact_role": partial_doc.get("artifact_role"),
                            "status": partial_doc.get("status"),
                            "current_phase": partial_doc.get("current_phase"),
                            "completed_stages": partial_doc.get(
                                "completed_stages"
                            ),
                            "rfactor_replay_verified": partial_doc.get(
                                "rfactor_replay_verified"
                            ),
                            "map_export_verified": partial_doc.get(
                                "map_export_verified"
                            ),
                            "failure": partial_doc.get("failure"),
                        }
                except Exception:
                    partial_summary = None

        failure_manifest = {
            "schema_version": 1,
            "status": "failed",
            "reusable_cache_output": False,
            "canonical_eval_qds_eligible": False,
            "subject_id": subject_id,
            "failed_stage": failed_stage,
            "attempt_directory": (
                str(attempt_dir) if attempt_dir is not None else None
            ),
            "returncode": getattr(exc, "returncode", None),
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "preflight_build_evidence_json_path": str(
                preflight_build_json_path
            ),
            "preflight_build_evidence_sha256": preflight_build_sha256,
            "retained_attempt_artifacts": retained_artifacts,
            "diagnostics_summary": diagnostics_summary,
            "partial_evidence_summary": partial_summary,
        }
        onesar_phenix_measure._atomic_write_json_checkpoint(
            failure_manifest, operation_failure_json_path
        )

    try:
        try:
            artifact_paths = refinement_cache.cached_phenix_operation(
                cache_dir,
                operation_name,
                executable="phenix.python",
                inputs=input_files,
                arguments=arguments,
                required_outputs=required_outputs,
                timeout=timeout,
                runner=runner,
            )
        except Exception as exc:
            log_p = getattr(exc, "log_path", None)
            attempt_p = log_p.parent if isinstance(log_p, Path) else None
            _retain_parent_operation_failure(
                attempt_p, exc, failed_stage="cached_phenix_operation"
            )
            raise
    finally:
        # Verify staged inputs were never mutated during execution.
        if (
            _sha256_regular_file(original_pdb_path)
            != staged["admission_record"]["staged_files"]["original_model_pdb_sha256"]
        ):
            raise ValueError("Staged original_model.pdb mutated during PHENIX operation")
        if (
            _sha256_regular_file(original_mtz_path)
            != staged["admission_record"]["staged_files"]["original_data_mtz_sha256"]
        ):
            raise ValueError("Staged original_data.mtz mutated during PHENIX operation")
        if (
            _sha256_regular_file(projected_mtz_path)
            != staged["admission_record"]["staged_files"][
                "projected_observations_mtz_sha256"
            ]
        ):
            raise ValueError(
                "Staged projected_observations.mtz mutated during PHENIX operation"
            )
        if (
            _sha256_regular_file(input_ledger_path)
            != staged["admission_record"]["staged_files"][
                "input_hkl_ledger_json_sha256"
            ]
        ):
            raise ValueError(
                "Staged input_hkl_ledger.json mutated during PHENIX operation"
            )

    manifest_path = artifact_paths["manifest"]
    output_json_path = artifact_paths["phenix_rfactors_json"]
    output_maps_mtz_path = artifact_paths["phx_maps_mtz"]
    output_obs_pair_mtz_path = artifact_paths["phx_obs_pair_only_mtz"]
    output_diagnostics_json_path = artifact_paths["phenix_diagnostics_json"]
    stdout_log_path = artifact_paths["stdout"]
    bundle_partial_json_path = (
        output_diagnostics_json_path.parent
        / "phenix_rfactors_partial_evidence.json"
    )

    try:
        manifest_record = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            not isinstance(manifest_record, Mapping)
            or type(manifest_record.get("returncode")) is not int
            or manifest_record["returncode"] != 0
            or manifest_record.get("reusable") is not True
            or not output_json_path.is_file()
        ):
            raise RuntimeError(
                f"PHENIX R-factor operation manifest reported invalid/non-reusable status: "
                f"returncode={manifest_record.get('returncode')!r}, "
                f"reusable={manifest_record.get('reusable')!r} at {manifest_path}"
            )

        invocation = manifest_record.get("invocation")
        if not isinstance(invocation, Mapping):
            raise ValueError("Cache manifest missing invocation record")
        validated_manifest_build = validate_measured_phenix_build(
            invocation.get("measured_build", {}),
            expected_version=toolchain.PHENIX_VERSION,
        )
        if (
            validated_manifest_build["build_info"]
            != validated_preflight["build_info"]
            or validated_manifest_build["resolved_prefix"]
            != expected_resolved_prefix
        ):
            raise ValueError(
                "Cache manifest measured_build drifted from preflight PHENIX build evidence"
            )
        launcher_info = invocation.get("launcher")
        if (
            not isinstance(launcher_info, Mapping)
            or not isinstance(launcher_info.get("path"), str)
            or not Path(launcher_info["path"]).is_relative_to(
                Path(expected_resolved_prefix)
            )
        ):
            raise ValueError(
                f"Cache manifest launcher {launcher_info!r} is not inside "
                f"{expected_resolved_prefix}"
            )
        invocation_inputs = invocation.get("inputs")
        if not isinstance(invocation_inputs, Mapping):
            raise ValueError("Cache manifest invocation missing inputs")
        for mod_key, mod_path in vendor_sources.items():
            if invocation_inputs.get(mod_key) != {
                "path": str(mod_path),
                "sha256": vendor_source_sha256[mod_key],
            }:
                raise ValueError(
                    f"Cache manifest input {mod_key} does not match preflight vendor source"
                )

        manifest_artifacts = manifest_record.get("artifacts")
        if not isinstance(manifest_artifacts, Mapping):
            raise ValueError("Cache manifest missing artifacts mapping")
        if (
            _sha256_regular_file(output_json_path)
            != manifest_artifacts.get("phenix_rfactors_json", {}).get("sha256")
        ):
            raise ValueError(
                "phenix_rfactors.json SHA-256 disagrees with cache manifest"
            )

        phenix_payload = json.loads(
            output_json_path.read_text(encoding="utf-8")
        )
        reconciliation = reconcile_phenix_rfactor_output(
            phenix_payload,
            input_ledger,
            expected_vendor_source_sha256=vendor_source_sha256,
            expected_vendor_module_paths=vendor_sources,
            expected_resolved_prefix=expected_resolved_prefix,
            expected_phenix_version=toolchain.PHENIX_VERSION,
            measured_build=invocation["measured_build"],
            phx_maps_mtz_path=output_maps_mtz_path,
            phx_obs_pair_only_mtz_path=output_obs_pair_mtz_path,
            phenix_diagnostics_path=output_diagnostics_json_path,
            cache_manifest_artifacts=manifest_artifacts,
        )
    except Exception as exc:
        _retain_parent_operation_failure(
            output_diagnostics_json_path.parent,
            exc,
            failed_stage="reconcile_phenix_rfactor_output",
        )
        raise

    reconciled_record: dict[str, Any] = {
        "schema_version": 1,
        "subject": staged["admission_record"]["subject"],
        "mtz": staged["admission_record"]["mtz"],
        "staged_files": staged["admission_record"]["staged_files"],
        "input_hkl_ledger_json_path": str(input_ledger_path),
        "input_hkl_ledger_json_sha256": staged["admission_record"]["staged_files"][
            "input_hkl_ledger_json_sha256"
        ],
        "preflight_build_evidence_json_path": str(preflight_build_json_path),
        "preflight_build_evidence_sha256": _sha256_regular_file(
            preflight_build_json_path
        ),
        "cache_artifacts": {
            key: str(path) for key, path in sorted(artifact_paths.items())
        },
        "manifest_path": str(manifest_path),
        "manifest_sha256": _sha256_regular_file(manifest_path),
        "stdout_log_path": str(stdout_log_path),
        "phenix_rfactors_json_path": str(output_json_path),
        "phenix_diagnostics_json_path": str(output_diagnostics_json_path),
        "phenix_partial_evidence_json_path": (
            str(bundle_partial_json_path)
            if bundle_partial_json_path.is_file()
            else None
        ),
        "phenix_partial_evidence_sha256": (
            _sha256_regular_file(bundle_partial_json_path)
            if bundle_partial_json_path.is_file()
            else None
        ),
        "phx_maps_mtz_path": str(output_maps_mtz_path),
        "phx_obs_pair_only_mtz_path": str(output_obs_pair_mtz_path),
        "operation_manifest": manifest_record,
        "reconciliation": reconciliation,
    }
    onesar_phenix_measure._atomic_write_json_checkpoint(
        reconciled_record, reconciled_json_path
    )
    return reconciled_record
