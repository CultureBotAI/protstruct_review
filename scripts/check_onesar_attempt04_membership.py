#!/usr/bin/env python3
"""Retained Attempt 04 semantic consistency checker (#1110, #1111, #1102).

Verifies that the 11 pinned repository-relative retained Attempt 04 artifacts
under ``data/coscientists/openscientist/`` are byte-for-byte intact and mutually
consistent across:

1. Native trace envelope validity and closure via
   :func:`refmac_diagnostic_trace.inspect_native_trace_bytes` and IEEE-754
   binary32 word/decimal decoding via
   :func:`refmac_diagnostic_trace.decode_trace_real_object`.
2. Exact structural projection from ``R/refmac/refmac_native_trace.jsonl`` and
   ``R/inputs/input_hkl_ledger.json`` to the five retained analysis files in
   ``A/current/`` (``residual_members.json``, ``completeness_members.json``,
   ``native_bin_bounds.json``, ``native_slot_records.json``, and
   ``completeness_slot_records.json``), including ``C0`` vs. ``L0`` boundary
   identity across all 20 shells and overall slot 21.
3. Input-to-native-to-output MTZ reflection domain and 4-byte IEEE-754 word
   join across ``original_data.mtz``, ``projected_observations.mtz``,
   ``input_hkl_ledger.json``, ``refmac_native_trace.jsonl``,
   ``refmac_hklout.mtz``, and ``refmac_hklout_raw_export.json`` for the 7,217
   positive eligible rows (6,494 work + 723 free), the 11 finite zero-``F``
   eligible work rows, and the 20 originally unassigned ``VALM NAN`` padding
   rows (#1110), plus input vs. ``HKLOUT`` dataset-ID layout observations
   (#1102).
4. Cross-namespace HKL set relationships and captured shell index ``J``
   consistency between ``residual_lsq`` (7,248 rows) and
   ``reporting_completeness`` (7,262 rows = 7,248 shared + 14 extra ASU rows;
   7,217 active/observed + 45 missing = 31 shared excluded + 14 extra ASU rows)
   without re-evaluating ``SMINB <= RHO <= SMAXB`` or comparing ``RHO`` words
   (#1111).

This checker establishes offline diagnostic consistency only. It performs no
native execution, selects no scientific policy for #1102, #1110, or #1111, and
always reports ``scientific_admission = False``, ``batch_eligible = False``,
``effective_hkls_proven = False``, and ``native_bin_membership_proven = False``.
"""

from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import struct
import sys
from typing import Any, Mapping, Sequence

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import onesar_rerun  # noqa: E402
import refmac_diagnostic_trace  # noqa: E402


REPO_ROOT = _SCRIPTS_DIR.parent

R_REL = "data/coscientists/openscientist/retained_1sar_pr1007_R4_rfactors_attempt04"
A_REL = (
    "data/coscientists/openscientist/"
    "retained_1sar_pr1007_R4_rfactors_attempt04_analysis/current"
)

ORIGINAL_MTZ_REL = f"{R_REL}/inputs/original_data.mtz"
PROJECTED_MTZ_REL = f"{R_REL}/inputs/projected_observations.mtz"
INPUT_LEDGER_REL = f"{R_REL}/inputs/input_hkl_ledger.json"
NATIVE_TRACE_REL = f"{R_REL}/refmac/refmac_native_trace.jsonl"
HKLOUT_MTZ_REL = f"{R_REL}/refmac/refmac_hklout.mtz"
HKLOUT_RAW_EXPORT_REL = f"{R_REL}/refmac/refmac_hklout_raw_export.json"
RESIDUAL_MEMBERS_REL = f"{A_REL}/residual_members.json"
COMPLETENESS_MEMBERS_REL = f"{A_REL}/completeness_members.json"
NATIVE_BIN_BOUNDS_REL = f"{A_REL}/native_bin_bounds.json"
NATIVE_SLOT_RECORDS_REL = f"{A_REL}/native_slot_records.json"
COMPLETENESS_SLOT_RECORDS_REL = f"{A_REL}/completeness_slot_records.json"

PINS: dict[str, str] = {
    ORIGINAL_MTZ_REL: (
        "f36d5fe685a3e524e8809d17d19ce12073acdf339eba2cfd3b0347a818850ab2"
    ),
    PROJECTED_MTZ_REL: (
        "6edbe54b2ec7b815f30b6bd20a7264a7c978721189670e39e20d876d9b4fece7"
    ),
    INPUT_LEDGER_REL: (
        "35543c5821665de8f65b5fbd153669556dfef766ac8b156dc001a0c5b667a51e"
    ),
    NATIVE_TRACE_REL: (
        "4dd312bf512d32cdf4095f1e3ee0c5471cb2ad91deb602b2c60d4f210216505d"
    ),
    HKLOUT_MTZ_REL: (
        "e21ce039b11e8b83c5deebfa3059fafeef7906cf1d10a1d3cf20b57f56b578e2"
    ),
    HKLOUT_RAW_EXPORT_REL: (
        "a3eb72b40f029fe7f0219b63b58e53d29cf96525b3b21126134a0d6517a8aa22"
    ),
    RESIDUAL_MEMBERS_REL: (
        "8034bfc5a9ed2e64fd8c21298904263b6317260588341154d16ce65a2e7bcb82"
    ),
    COMPLETENESS_MEMBERS_REL: (
        "ce1a6c17334a8fd114c37da0841baae0d5805ad17b8358ef972837f6d57c773f"
    ),
    NATIVE_BIN_BOUNDS_REL: (
        "e339889022147a613a64dfbdd784a10e2c404c029a4dc2b84cb7bfee86da6be9"
    ),
    NATIVE_SLOT_RECORDS_REL: (
        "a01f979d0326f76e65776b0f7b43b82ced1feb6b387cd98910b3e5f5cec05efd"
    ),
    COMPLETENESS_SLOT_RECORDS_REL: (
        "76404a64df3cc9876794b7caf8acee66eab5eb3a29754fe47b50c90b0c9981ff"
    ),
}

DIAGNOSTIC_SCHEMA_ID = "protstruct_onesar_attempt04_membership_diagnostic_v1"
DIAGNOSTIC_SCHEMA_VERSION = "1.0.0"
DIAGNOSTIC_FIXTURE_SCOPE = (
    "fixed_retained_fixture:retained_1sar_pr1007_R4_rfactors_attempt04"
)

TRACE_EXPECTED_SIZE_BYTES = 68_015_529
TRACE_EXPECTED_RECORD_COUNT = 94_281
TRACE_EXPECTED_LINE_COUNT = 94_283

EXPECTED_ZERO_F_INPUT_ROW_INDICES: tuple[int, ...] = (
    283,
    306,
    319,
    770,
    3060,
    4175,
    4669,
    5469,
    5682,
    5835,
    6853,
)
EXPECTED_PADDING_INPUT_ROW_INDICES: tuple[int, ...] = tuple(range(7228, 7248))

LEDGER_ROW_DOMAIN_KEYS: tuple[str, ...] = (
    "counts",
    "crystallographic_context",
    "declared_flag_values",
    "eligible_by_hkl",
    "free_flag_value",
    "ineligible_rows",
    "labels",
    "raw_rows",
    "work_flag_value",
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _assert_canonical_json_equal(
    actual: Any, expected: Any, *, label: str
) -> None:
    if _canonical_json(actual) != _canonical_json(expected):
        if isinstance(actual, Sequence) and isinstance(expected, Sequence):
            if len(actual) != len(expected):
                raise ValueError(
                    f"{label} length mismatch: actual={len(actual)} vs expected={len(expected)}"
                )
            for idx, (act_item, exp_item) in enumerate(zip(actual, expected)):
                if _canonical_json(act_item) != _canonical_json(exp_item):
                    raise ValueError(
                        f"{label} mismatch at index {idx}: actual={act_item!r} vs expected={exp_item!r}"
                    )
        if isinstance(actual, Mapping) and isinstance(expected, Mapping):
            act_keys = set(actual.keys())
            exp_keys = set(expected.keys())
            if act_keys != exp_keys:
                raise ValueError(
                    f"{label} key mismatch: actual={sorted(act_keys)} vs expected={sorted(exp_keys)}"
                )
            for key in sorted(act_keys):
                if _canonical_json(actual[key]) != _canonical_json(expected[key]):
                    raise ValueError(
                        f"{label} mismatch at key {key!r}"
                    )
        raise ValueError(f"{label} structural mismatch")


def _decode_real(
    obj: Any, *, context: str
) -> refmac_diagnostic_trace.DecodedBinary32:
    try:
        decoded = refmac_diagnostic_trace.decode_trace_real_object(obj)
    except Exception as exc:
        raise ValueError(
            f"Invalid trace binary32 object at {context}: {obj!r}"
        ) from exc
    if not decoded.is_finite or decoded.exact_fraction is None:
        raise ValueError(
            f"Non-finite trace binary32 object at {context}: {obj!r}"
        )
    return decoded


def _require_nonbool_int(
    value: Any,
    *,
    event: str,
    field: str,
    call_id: Any,
    row_index: Any,
    line_no: int,
) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(
            f"Expected non-boolean integer for {event}.{field} at call_id={call_id!r}, "
            f"row_index={row_index!r}, line {line_no}, got {value!r}"
        )
    return value


def _require_exact_int_hkl_triplet(
    raw_hkl: Any, *, context: str
) -> tuple[int, int, int]:
    """Require a 3-element sequence of non-boolean integers without int() coercion."""
    if (
        not isinstance(raw_hkl, Sequence)
        or isinstance(raw_hkl, (str, bytes))
        or len(raw_hkl) != 3
        or any(
            not isinstance(coord, int) or isinstance(coord, bool)
            for coord in raw_hkl
        )
    ):
        raise ValueError(
            f"Expected 3-element non-boolean integer HKL triplet at {context}, got {raw_hkl!r}"
        )
    return (raw_hkl[0], raw_hkl[1], raw_hkl[2])


def _require_bound_slot(
    bounds_map: Mapping[int, tuple[int, Mapping[str, Any]]],
    *,
    namespace: str,
    hook_label: str,
    slot_idx: int,
    call_id: Any,
    row_index: Any,
    consuming_line: int,
    consuming_event: str,
) -> Mapping[str, Any]:
    """Look up a required C0/L0 boundary slot or raise a contextual ValueError."""
    entry = bounds_map.get(slot_idx)
    if entry is None:
        raise ValueError(
            f"Missing required {hook_label} bin boundary slot={slot_idx} in namespace={namespace!r} "
            f"for event={consuming_event!r} at call_id={call_id!r}, row_index={row_index!r}, "
            f"line {consuming_line}"
        )
    return entry[1]


def _read_pinned_regular_file(
    repo_root: Path, rel_path: str, expected_sha256: str
) -> tuple[bytes, dict[str, Any]]:
    path = Path(repo_root) / rel_path
    try:
        st = os.lstat(path)
    except FileNotFoundError as exc:
        raise ValueError(
            f"Missing pinned retained file {rel_path}: {path}"
        ) from exc
    if stat.S_ISLNK(st.st_mode):
        raise ValueError(
            f"Pinned retained file must not be a symlink ({rel_path}): {path}"
        )
    if not stat.S_ISREG(st.st_mode):
        raise ValueError(
            f"Pinned retained path is not a regular file ({rel_path}): {path}"
        )
    raw_bytes = path.read_bytes()
    actual_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ValueError(
            f"SHA-256 mismatch for {rel_path}: expected {expected_sha256}, got {actual_sha256}"
        )
    return raw_bytes, {
        "sha256": actual_sha256,
        "size_bytes": len(raw_bytes),
    }


def _derive_trace_record_metadata(
    trace_records: Sequence[tuple[int, Mapping[str, Any]]],
) -> dict[str, Any]:
    """Derive and validate physical line count and per-event counts from parsed trace records."""
    physical_line_count = len(trace_records)
    if physical_line_count != TRACE_EXPECTED_LINE_COUNT:
        raise ValueError(
            f"Expected {TRACE_EXPECTED_LINE_COUNT} physical trace records in {NATIVE_TRACE_REL}, "
            f"got {physical_line_count}"
        )

    header_record_count = 0
    writer_close_record_count = 0
    numbered_event_count = 0
    header_line_number: int | None = None
    writer_close_line_number: int | None = None
    writer_close_reported_record_count: int | None = None
    event_counts: dict[str, int] = {}

    for expected_line_no, (line_no, record) in enumerate(trace_records, 1):
        if line_no != expected_line_no:
            raise ValueError(
                f"Non-contiguous physical trace line number at index {expected_line_no}: got {line_no}"
            )
        if expected_line_no == 1:
            if (
                record.get("record_type") != "header"
                or "sequence" in record
                or "event" in record
            ):
                raise ValueError(
                    f"Physical trace line 1 must be an unnumbered header record, got {record!r}"
                )
            header_record_count += 1
            header_line_number = line_no
        elif expected_line_no == physical_line_count:
            if (
                record.get("record_type") != "writer_close"
                or record.get("event") != "writer_close"
                or "sequence" in record
                or record.get("record_count") != TRACE_EXPECTED_RECORD_COUNT
            ):
                raise ValueError(
                    f"Physical trace line {line_no} must be an unnumbered writer_close footer "
                    f"with record_count={TRACE_EXPECTED_RECORD_COUNT}, got {record!r}"
                )
            writer_close_record_count += 1
            writer_close_line_number = line_no
            writer_close_reported_record_count = int(record["record_count"])
        else:
            expected_seq = numbered_event_count + 1
            ev_name = record.get("event")
            if (
                "record_type" in record
                or record.get("sequence") != expected_seq
                or not isinstance(ev_name, str)
                or ev_name == ""
                or ev_name == "writer_close"
            ):
                raise ValueError(
                    f"Physical trace line {line_no} must be numbered event sequence={expected_seq}, "
                    f"got {record!r}"
                )
            numbered_event_count += 1
            event_counts[ev_name] = event_counts.get(ev_name, 0) + 1

    if (
        header_record_count != 1
        or writer_close_record_count != 1
        or numbered_event_count != TRACE_EXPECTED_RECORD_COUNT
        or writer_close_reported_record_count != numbered_event_count
        or (header_record_count + numbered_event_count + writer_close_record_count)
        != physical_line_count
        or sum(event_counts.values()) != numbered_event_count
    ):
        raise ValueError(
            f"Derived trace record metadata mismatch: physical_line_count={physical_line_count}, "
            f"header_record_count={header_record_count}, numbered_event_count={numbered_event_count}, "
            f"writer_close_record_count={writer_close_record_count}"
        )

    return {
        "source": "parsed_verified_trace_bytes_snapshot",
        "physical_line_count": physical_line_count,
        "header_record_count": header_record_count,
        "numbered_event_count": numbered_event_count,
        "writer_close_record_count": writer_close_record_count,
        "header_line_number": header_line_number,
        "first_numbered_event_line_number": 2,
        "last_numbered_event_line_number": physical_line_count - 1,
        "writer_close_line_number": writer_close_line_number,
        "writer_close_record_count_field": writer_close_reported_record_count,
        "event_counts": event_counts,
    }


def _load_pinned_attempt04_bundle(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """Load and pin-verify all 11 retained Attempt 04 inputs into memory."""
    root = Path(repo_root)
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Repository root does not exist or is not a directory: {root}")

    raw_by_rel: dict[str, bytes] = {}
    verified_pins: dict[str, dict[str, Any]] = {}
    for rel_path, expected_sha in PINS.items():
        raw_bytes, pin_info = _read_pinned_regular_file(root, rel_path, expected_sha)
        raw_by_rel[rel_path] = raw_bytes
        verified_pins[rel_path] = pin_info

    trace_path = root / NATIVE_TRACE_REL
    trace_bytes = raw_by_rel[NATIVE_TRACE_REL]
    envelope = refmac_diagnostic_trace.inspect_native_trace_bytes(
        trace_path,
        trace_bytes,
        expected_sha256=PINS[NATIVE_TRACE_REL],
        expected_size_bytes=TRACE_EXPECTED_SIZE_BYTES,
    )
    if (
        envelope.get("valid") is not True
        or envelope.get("closed") is not True
        or envelope.get("sha256_match") is not True
        or envelope.get("size_bytes_match") is not True
        or envelope.get("record_count") != TRACE_EXPECTED_RECORD_COUNT
        or envelope.get("event_count") != TRACE_EXPECTED_RECORD_COUNT
        or envelope.get("footer_record_count") != TRACE_EXPECTED_RECORD_COUNT
    ):
        raise ValueError(
            f"Native trace envelope verification failed for {NATIVE_TRACE_REL}: "
            f"valid={envelope.get('valid')!r}, closed={envelope.get('closed')!r}, "
            f"sha256_match={envelope.get('sha256_match')!r}, "
            f"size_bytes_match={envelope.get('size_bytes_match')!r}, "
            f"record_count={envelope.get('record_count')!r}, "
            f"event_count={envelope.get('event_count')!r}, "
            f"footer_record_count={envelope.get('footer_record_count')!r}, "
            f"errors={envelope.get('errors')!r}"
        )

    trace_records: list[tuple[int, dict[str, Any]]] = []
    for line_no, raw_line in enumerate(
        trace_bytes.decode("utf-8").splitlines(), 1
    ):
        trace_records.append((line_no, json.loads(raw_line)))
    trace_record_metadata = _derive_trace_record_metadata(trace_records)

    return {
        "repo_root": root,
        "verified_pins": verified_pins,
        "envelope": {
            "valid": bool(envelope["valid"]),
            "closed": bool(envelope["closed"]),
            "sha256_match": bool(envelope["sha256_match"]),
            "size_bytes_match": bool(envelope["size_bytes_match"]),
            "record_count": int(envelope["record_count"]),
            "event_count": int(envelope["event_count"]),
            "footer_record_count": int(envelope["footer_record_count"]),
        },
        "trace_record_metadata": trace_record_metadata,
        "original_mtz_bytes": raw_by_rel[ORIGINAL_MTZ_REL],
        "projected_mtz_bytes": raw_by_rel[PROJECTED_MTZ_REL],
        "hklout_mtz_bytes": raw_by_rel[HKLOUT_MTZ_REL],
        "trace_bytes": trace_bytes,
        "trace_records": trace_records,
        "input_hkl_ledger": json.loads(
            raw_by_rel[INPUT_LEDGER_REL].decode("utf-8")
        ),
        "hklout_raw_export": json.loads(
            raw_by_rel[HKLOUT_RAW_EXPORT_REL].decode("utf-8")
        ),
        "residual_members": json.loads(
            raw_by_rel[RESIDUAL_MEMBERS_REL].decode("utf-8")
        ),
        "completeness_members": json.loads(
            raw_by_rel[COMPLETENESS_MEMBERS_REL].decode("utf-8")
        ),
        "native_bin_bounds": json.loads(
            raw_by_rel[NATIVE_BIN_BOUNDS_REL].decode("utf-8")
        ),
        "native_slot_records": json.loads(
            raw_by_rel[NATIVE_SLOT_RECORDS_REL].decode("utf-8")
        ),
        "completeness_slot_records": json.loads(
            raw_by_rel[COMPLETENESS_SLOT_RECORDS_REL].decode("utf-8")
        ),
    }


def _project_retained_products(
    trace_records_or_bundle: Sequence[tuple[int, Mapping[str, Any]]] | Mapping[str, Any],
    *,
    retained_ledger: Mapping[str, Any] | None = None,
    retained_residual_members: Sequence[Mapping[str, Any]] | None = None,
    retained_completeness_members: Sequence[Mapping[str, Any]] | None = None,
    retained_native_bin_bounds: Sequence[Mapping[str, Any]] | None = None,
    retained_native_slot_records: Sequence[Mapping[str, Any]] | None = None,
    retained_completeness_slot_records: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Re-project retained analysis JSON files from raw trace records and verify identity."""
    if isinstance(trace_records_or_bundle, Mapping):
        bundle = trace_records_or_bundle
        trace_records: Sequence[tuple[int, Mapping[str, Any]]] = bundle["trace_records"]
        if retained_ledger is None:
            retained_ledger = bundle["input_hkl_ledger"]
        if retained_residual_members is None:
            retained_residual_members = bundle["residual_members"]
        if retained_completeness_members is None:
            retained_completeness_members = bundle["completeness_members"]
        if retained_native_bin_bounds is None:
            retained_native_bin_bounds = bundle["native_bin_bounds"]
        if retained_native_slot_records is None:
            retained_native_slot_records = bundle["native_slot_records"]
        if retained_completeness_slot_records is None:
            retained_completeness_slot_records = bundle["completeness_slot_records"]
    else:
        trace_records = trace_records_or_bundle

    if (
        retained_ledger is None
        or retained_residual_members is None
        or retained_completeness_members is None
        or retained_native_bin_bounds is None
        or retained_native_slot_records is None
        or retained_completeness_slot_records is None
    ):
        raise ValueError(
            "_project_retained_products requires trace_records and all retained analysis/ledger structures"
        )

    raw_rows = retained_ledger.get("raw_rows")
    if not isinstance(raw_rows, Sequence) or len(raw_rows) != 7248:
        raise ValueError(
            f"Expected 7,248 raw_rows in input_hkl_ledger.json, got {len(raw_rows) if isinstance(raw_rows, Sequence) else type(raw_rows).__name__}"
        )
    inputs_by_hkl: dict[tuple[int, int, int], Mapping[str, Any]] = {}
    for row_idx_in_ledger, row in enumerate(raw_rows):
        hkl = _require_exact_int_hkl_triplet(
            row.get("hkl"),
            context=f"input_hkl_ledger.raw_rows[{row_idx_in_ledger}].hkl",
        )
        if hkl in inputs_by_hkl:
            raise ValueError(f"Duplicate HKL in input_hkl_ledger: {hkl}")
        inputs_by_hkl[hkl] = row

    lsq_calls: dict[int, Mapping[str, Any]] = {}
    comp_calls: dict[int, Mapping[str, Any]] = {}
    c0_bounds: dict[int, tuple[int, Mapping[str, Any]]] = {}
    l0_bounds: dict[int, tuple[int, Mapping[str, Any]]] = {}
    projected_bounds: list[dict[str, Any]] = []
    open_lsq_rows: dict[tuple[int, int], dict[str, Any]] = {}
    open_comp_rows: dict[tuple[int, int], dict[str, Any]] = {}
    projected_residual_members: list[dict[str, Any]] = []
    projected_completeness_members: list[dict[str, Any]] = []
    raw_slots: dict[tuple[int, int, int], Mapping[str, Any]] = {}
    projected_comp_slots: list[dict[str, Any]] = []

    lsq_accum: dict[tuple[int, int, int], tuple[int, str, str]] = {}
    lsq_before: dict[tuple[int, int, int], tuple[int, str, str]] = {}
    comp_accum: dict[tuple[int, int, int], tuple[int, int]] = {}
    lsq_end_seen = False
    comp_end_seen = False
    termination_seen = False

    for line_no, record in trace_records:
        ev = record.get("event", record.get("record_type"))
        ns = record.get("namespace")
        call_id = record.get("call_id")
        if ns in ("residual_lsq", "reporting_completeness") and call_id != 1:
            raise ValueError(
                f"Expected single call_id=1 in {ns} at line {line_no}, got {call_id!r}"
            )

        if ev == "completeness_begin":
            if call_id in comp_calls:
                raise ValueError(f"Duplicate completeness_begin for call_id={call_id} at line {line_no}")
            comp_calls[int(call_id)] = record
            res_max = _decode_real(
                record.get("RES_MAX"), context=f"completeness_begin.RES_MAX line {line_no}"
            )
            if (
                record.get("NSYM") != 4
                or record.get("NASYM") != 7262
                or record.get("NREF") != 7248
                or record.get("NBIN") != 20
                or record.get("NB1") != 21
                or record.get("FREER_FLAG") is not True
                or res_max.bits_hex != "3E4CCC57"
            ):
                raise ValueError(
                    f"Unexpected completeness_begin header fields at line {line_no}: {record!r}"
                )

        elif ev == "completeness_bin_bounds":
            slot_idx = int(record["slot_index"])
            if slot_idx in c0_bounds or not (1 <= slot_idx <= 21):
                raise ValueError(
                    f"Invalid or duplicate C0 slot_index={slot_idx} at line {line_no}"
                )
            if (
                record.get("NBIN") != 20
                or record.get("NB1") != 21
                or record.get("is_overall_slot") != (slot_idx == 21)
            ):
                raise ValueError(
                    f"Malformed C0 bin bound metadata at line {line_no}: {record!r}"
                )
            _decode_real(record.get("SMINB"), context=f"C0 SMINB slot {slot_idx}")
            _decode_real(record.get("SMAXB"), context=f"C0 SMAXB slot {slot_idx}")
            c0_bounds[slot_idx] = (line_no, record)

        elif ev == "lsq_coef_begin":
            if call_id in lsq_calls:
                raise ValueError(f"Duplicate lsq_coef_begin for call_id={call_id} at line {line_no}")
            lsq_calls[int(call_id)] = record
            if (
                record.get("REFS") != "MLKF"
                or record.get("LREFIN") is not False
                or record.get("IMODE") != 0
                or record.get("DataSource") != "XR"
                or record.get("FREER_FLAG") is not True
                or record.get("LFreeRexcludeVal") != 1
                or record.get("NPART") != 1
                or record.get("NDENS") != 1
                or record.get("NBIN") != 20
                or record.get("NB1") != 21
                or record.get("NREF") != 7248
                or record.get("NOBS") != 7248
                or record.get("PHASE_FLAG") is not False
                or record.get("MIR_FLAG") is not False
            ):
                raise ValueError(
                    f"Unexpected lsq_coef_begin mode fields at line {line_no}: {record!r}"
                )

        elif ev == "lsq_coef_bin_bounds":
            slot_idx = int(record["slot_index"])
            if slot_idx in l0_bounds or not (1 <= slot_idx <= 21):
                raise ValueError(
                    f"Invalid or duplicate L0 slot_index={slot_idx} at line {line_no}"
                )
            if (
                record.get("NBIN") != 20
                or record.get("NB1") != 21
                or record.get("is_overall_slot") != (slot_idx == 21)
            ):
                raise ValueError(
                    f"Malformed L0 bin bound metadata at line {line_no}: {record!r}"
                )
            _decode_real(record.get("SMINB"), context=f"L0 SMINB slot {slot_idx}")
            _decode_real(record.get("SMAXB"), context=f"L0 SMAXB slot {slot_idx}")
            l0_bounds[slot_idx] = (line_no, record)
            projected_bounds.append({"line": line_no, "record": dict(record)})

        elif ev == "lsq_row_input":
            row_idx = _require_nonbool_int(
                record.get("row_index"),
                event=ev,
                field="row_index",
                call_id=call_id,
                row_index=record.get("row_index"),
                line_no=line_no,
            )
            key = (int(call_id), row_idx)
            if key in open_lsq_rows:
                raise ValueError(f"Duplicate open lsq_row_input for {key} at line {line_no}")
            hkl = (
                _require_nonbool_int(
                    record.get("H"),
                    event=ev,
                    field="H",
                    call_id=call_id,
                    row_index=row_idx,
                    line_no=line_no,
                ),
                _require_nonbool_int(
                    record.get("K"),
                    event=ev,
                    field="K",
                    call_id=call_id,
                    row_index=row_idx,
                    line_no=line_no,
                ),
                _require_nonbool_int(
                    record.get("L"),
                    event=ev,
                    field="L",
                    call_id=call_id,
                    row_index=row_idx,
                    line_no=line_no,
                ),
            )
            _require_nonbool_int(
                record.get("IFREE"),
                event=ev,
                field="IFREE",
                call_id=call_id,
                row_index=row_idx,
                line_no=line_no,
            )
            if hkl not in inputs_by_hkl:
                raise ValueError(
                    f"Native lsq_row_input HKL {hkl} at line {line_no} not found in input_hkl_ledger.json"
                )
            _decode_real(record.get("YO"), context=f"L2 YO line {line_no}")
            _decode_real(record.get("SO"), context=f"L2 SO line {line_no}")
            _decode_real(
                record.get("native_FREER_value"),
                context=f"L2 native_FREER_value line {line_no}",
            )
            _decode_real(record.get("RSQ"), context=f"L2 RSQ line {line_no}")
            _decode_real(record.get("RHO"), context=f"L2 RHO line {line_no}")
            open_lsq_rows[key] = {
                "input": record,
                "input_line": line_no,
                "hkl": [hkl[0], hkl[1], hkl[2]],
                "shells": [],
                "overall": False,
            }

        elif ev == "sumsfs_ls_deriv_row":
            key = (int(call_id), int(record["row_index"]))
            if key not in open_lsq_rows or "s0" in open_lsq_rows[key]:
                raise ValueError(f"Unexpected sumsfs_ls_deriv_row for {key} at line {line_no}")
            open_lsq_rows[key]["s0"] = record

        elif ev == "lsq_row_operands":
            key = (int(call_id), int(record["row_index"]))
            if key not in open_lsq_rows or "operands" in open_lsq_rows[key]:
                raise ValueError(f"Unexpected lsq_row_operands for {key} at line {line_no}")
            row_state = open_lsq_rows[key]
            s0 = row_state.get("s0")
            if s0 is None:
                raise ValueError(
                    f"lsq_row_operands at line {line_no} missing preceding sumsfs_ls_deriv_row"
                )
            for l3_field, s0_field in (
                ("YOS", "YOS"),
                ("YC_ALL", "YC_ALL"),
                ("SIGOS", "SIGOS"),
                ("DY", "DELTA"),
            ):
                l3_dec = _decode_real(
                    record.get(l3_field), context=f"L3 {l3_field} line {line_no}"
                )
                s0_dec = _decode_real(
                    s0.get(s0_field), context=f"S0 {s0_field} line {line_no}"
                )
                if l3_dec.bits_hex != s0_dec.bits_hex:
                    raise ValueError(
                        f"Callee/caller operand mismatch at line {line_no} for {l3_field} vs {s0_field}: "
                        f"{l3_dec.bits_hex} != {s0_dec.bits_hex}"
                    )
            row_state["operands"] = record

        elif ev in ("lsq_shell_match_before", "lsq_overall_accum_before"):
            row_idx = _require_nonbool_int(
                record.get("row_index"),
                event=ev,
                field="row_index",
                call_id=call_id,
                row_index=record.get("row_index"),
                line_no=line_no,
            )
            key = (int(call_id), row_idx)
            if key not in open_lsq_rows:
                raise ValueError(
                    f"Unmatched {ev} without open L2 row at call_id={call_id}, "
                    f"row_index={row_idx}, line {line_no}"
                )
            slot_field = "J" if ev == "lsq_shell_match_before" else "NB1"
            slot_idx = _require_nonbool_int(
                record.get(slot_field),
                event=ev,
                field=slot_field,
                call_id=call_id,
                row_index=row_idx,
                line_no=line_no,
            )
            part = _require_nonbool_int(
                record.get("IFREE"),
                event=ev,
                field="IFREE",
                call_id=call_id,
                row_index=row_idx,
                line_no=line_no,
            )
            l2_inp = open_lsq_rows[key]["input"]
            l2_line = open_lsq_rows[key]["input_line"]
            if part != l2_inp.get("IFREE"):
                raise ValueError(
                    f"{ev} field 'IFREE' contradicts open L2 row at call_id={call_id}, "
                    f"row_index={row_idx}, line {line_no} (L2 line {l2_line}): "
                    f"got {part!r}, L2 IFREE={l2_inp.get('IFREE')!r}"
                )
            bound_rec = _require_bound_slot(
                l0_bounds,
                namespace="residual_lsq",
                hook_label="L0",
                slot_idx=slot_idx,
                call_id=call_id,
                row_index=row_idx,
                consuming_line=line_no,
                consuming_event=ev,
            )
            acc_key = (int(call_id), part, slot_idx)
            afomfc_b = _decode_real(
                record.get("AFOMFC_before"), context=f"{ev} AFOMFC_before line {line_no}"
            )
            afo_b = _decode_real(
                record.get("AFO_before"), context=f"{ev} AFO_before line {line_no}"
            )
            state = (int(record["nrefa_this_before"]), afomfc_b.bits_hex, afo_b.bits_hex)
            expected_prev = lsq_accum.get(acc_key, (0, "00000000", "00000000"))
            if state != expected_prev:
                raise ValueError(
                    f"Accumulator prestate discontinuity at line {line_no} for {acc_key}: "
                    f"got {state}, expected {expected_prev}"
                )
            lsq_before[acc_key] = state
            if ev == "lsq_shell_match_before":
                smin_j = _decode_real(record.get("SMINB_J"), context=f"L4 SMINB_J line {line_no}")
                smax_j = _decode_real(record.get("SMAXB_J"), context=f"L4 SMAXB_J line {line_no}")
                if (
                    smin_j.bits_hex != bound_rec["SMINB"]["bits_hex"]
                    or smax_j.bits_hex != bound_rec["SMAXB"]["bits_hex"]
                ):
                    raise ValueError(
                        f"L4 shell bound mismatch at line {line_no} for J={slot_idx}"
                    )

        elif ev in ("lsq_shell_accum_after", "lsq_overall_accum_after"):
            row_idx = _require_nonbool_int(
                record.get("row_index"),
                event=ev,
                field="row_index",
                call_id=call_id,
                row_index=record.get("row_index"),
                line_no=line_no,
            )
            key = (int(call_id), row_idx)
            if key not in open_lsq_rows:
                raise ValueError(
                    f"Unmatched {ev} without open L2 row at call_id={call_id}, "
                    f"row_index={row_idx}, line {line_no}"
                )
            slot_field = "J" if ev == "lsq_shell_accum_after" else "NB1"
            slot_idx = _require_nonbool_int(
                record.get(slot_field),
                event=ev,
                field=slot_field,
                call_id=call_id,
                row_index=row_idx,
                line_no=line_no,
            )
            part = _require_nonbool_int(
                record.get("IFREE"),
                event=ev,
                field="IFREE",
                call_id=call_id,
                row_index=row_idx,
                line_no=line_no,
            )
            l2_inp = open_lsq_rows[key]["input"]
            l2_line = open_lsq_rows[key]["input_line"]
            if part != l2_inp.get("IFREE"):
                raise ValueError(
                    f"{ev} field 'IFREE' contradicts open L2 row at call_id={call_id}, "
                    f"row_index={row_idx}, line {line_no} (L2 line {l2_line}): "
                    f"got {part!r}, L2 IFREE={l2_inp.get('IFREE')!r}"
                )
            _require_bound_slot(
                l0_bounds,
                namespace="residual_lsq",
                hook_label="L0",
                slot_idx=slot_idx,
                call_id=call_id,
                row_index=row_idx,
                consuming_line=line_no,
                consuming_event=ev,
            )
            acc_key = (int(call_id), part, slot_idx)
            if acc_key not in lsq_before:
                raise ValueError(
                    f"Missing preceding before-record for {ev} at call_id={call_id}, "
                    f"row_index={row_idx}, slot={slot_idx}, IFREE={part}, line {line_no}"
                )
            old_count, _, _ = lsq_before[acc_key]
            new_count = int(record["nrefa_this_after"])
            if new_count != old_count + 1:
                raise ValueError(
                    f"Expected nrefa_this_after={old_count + 1} at line {line_no}, got {new_count}"
                )
            afomfc_a = _decode_real(
                record.get("AFOMFC_after"), context=f"{ev} AFOMFC_after line {line_no}"
            )
            afo_a = _decode_real(
                record.get("AFO_after"), context=f"{ev} AFO_after line {line_no}"
            )
            lsq_accum[acc_key] = (new_count, afomfc_a.bits_hex, afo_a.bits_hex)
            row_state = open_lsq_rows[key]
            if ev == "lsq_shell_accum_after":
                row_state["shells"].append(slot_idx)
            else:
                row_state["overall"] = True

        elif ev == "lsq_row_terminal":
            key = (int(call_id), int(record["row_index"]))
            if key not in open_lsq_rows:
                raise ValueError(f"Unmatched lsq_row_terminal for {key} at line {line_no}")
            row_state = open_lsq_rows.pop(key)
            inp = row_state["input"]
            hkl_list = row_state["hkl"]
            hkl_tuple = (hkl_list[0], hkl_list[1], hkl_list[2])
            orig = inputs_by_hkl[hkl_tuple]
            op = row_state.get("operands")

            so_dec = _decode_real(inp["SO"], context=f"L2 SO row {key[1]}")
            so_positive = so_dec.exact_fraction > 0
            included = bool(record["overall_added"])
            shell_added = bool(record["shell_added"])
            l3_ran = bool(record["l3_operands_ran"])
            matched_bin = int(record["matched_bin_index"])
            if not (1 <= matched_bin <= 20):
                raise ValueError(
                    f"Invalid matched_bin_index={matched_bin} at line {line_no}"
                )
            bound_rec = _require_bound_slot(
                l0_bounds,
                namespace="residual_lsq",
                hook_label="L0",
                slot_idx=matched_bin,
                call_id=call_id,
                row_index=key[1],
                consuming_line=line_no,
                consuming_event=ev,
            )
            m_smin = _decode_real(
                record.get("matched_SMINB"), context=f"L7 matched_SMINB line {line_no}"
            )
            m_smax = _decode_real(
                record.get("matched_SMAXB"), context=f"L7 matched_SMAXB line {line_no}"
            )
            if (
                m_smin.bits_hex != bound_rec["SMINB"]["bits_hex"]
                or m_smax.bits_hex != bound_rec["SMAXB"]["bits_hex"]
            ):
                raise ValueError(
                    f"L7 matched_SMINB/SMAXB mismatch against L0 slot {matched_bin} at line {line_no}"
                )

            if (
                so_positive != (op is not None)
                or l3_ran != (op is not None)
                or shell_added != included
                or included != so_positive
                or row_state["overall"] != included
                or (row_state["shells"] != ([matched_bin] if included else []))
            ):
                raise ValueError(
                    f"Inconsistent SO>0 / operand / shell_added / overall_added branch at line {line_no}: "
                    f"so_positive={so_positive}, has_op={op is not None}, l3_ran={l3_ran}, "
                    f"shell_added={shell_added}, overall_added={included}, shells={row_state['shells']}"
                )
            expected_outcome = (
                "included_shell_and_overall"
                if included
                else "excluded_sigma_guard_in_shell"
            )
            if record.get("row_outcome") != expected_outcome:
                raise ValueError(
                    f"Unexpected lsq_row_terminal row_outcome at line {line_no}: "
                    f"got {record.get('row_outcome')!r}, expected {expected_outcome!r}"
                )

            flag_dec = _decode_real(
                inp["native_FREER_value"], context=f"L2 native_FREER_value row {key[1]}"
            )
            if flag_dec.exact_fraction not in (Fraction(0, 1), Fraction(1, 1)):
                raise ValueError(
                    f"Non-binary native_FREER_value at line {line_no}: {inp['native_FREER_value']!r}"
                )
            expected_ifree = (
                2
                if inp.get("FREER_FLAG")
                and flag_dec.exact_fraction == lsq_calls[int(call_id)]["LFreeRexcludeVal"]
                else 1
            )
            if int(record["IFREE"]) != expected_ifree or int(inp["IFREE"]) != expected_ifree:
                raise ValueError(
                    f"IFREE partition mismatch at line {line_no}: got {record['IFREE']}, expected {expected_ifree}"
                )

            projected_residual_members.append(
                {
                    "call_id": int(call_id),
                    "row_index": int(record["row_index"]),
                    "hkl": hkl_list,
                    "input_line": row_state["input_line"],
                    "terminal_line": line_no,
                    "native_free_flag": inp["native_FREER_value"],
                    "IFREE": int(record["IFREE"]),
                    "SO": inp["SO"],
                    "YO": inp["YO"],
                    "source_input_eligible": orig["eligible"],
                    "source_input_partition": orig["partition"],
                    "source_input_F_word": orig["f_obs_word_hex"],
                    "source_input_flag_word": orig["r_free_flag_word_hex"],
                    "matched_bin_index": matched_bin,
                    "shell_added": shell_added,
                    "overall_added": included,
                    "row_outcome": record["row_outcome"],
                    "YOS": op["YOS"] if op is not None else None,
                    "YC_ALL": op["YC_ALL"] if op is not None else None,
                    "DY": op["DY"] if op is not None else None,
                }
            )

        elif ev == "lsq_raw_accumulator_slot":
            slot_idx = _require_nonbool_int(
                record.get("slot_index"),
                event=ev,
                field="slot_index",
                call_id=call_id,
                row_index=None,
                line_no=line_no,
            )
            part = _require_nonbool_int(
                record.get("IFREE"),
                event=ev,
                field="IFREE",
                call_id=call_id,
                row_index=None,
                line_no=line_no,
            )
            _require_bound_slot(
                l0_bounds,
                namespace="residual_lsq",
                hook_label="L0",
                slot_idx=slot_idx,
                call_id=call_id,
                row_index=None,
                consuming_line=line_no,
                consuming_event=ev,
            )
            acc_key = (int(call_id), part, slot_idx)
            if acc_key in raw_slots:
                raise ValueError(
                    f"Duplicate lsq_raw_accumulator_slot for {acc_key} at line {line_no}"
                )
            afomfc_r = _decode_real(
                record.get("AFOMFC_raw"), context=f"L8 AFOMFC_raw line {line_no}"
            )
            afo_r = _decode_real(
                record.get("AFO_raw"), context=f"L8 AFO_raw line {line_no}"
            )
            state = (
                int(record["nrefa_this"]),
                afomfc_r.bits_hex,
                afo_r.bits_hex,
            )
            expected_state = lsq_accum.get(acc_key, (0, "00000000", "00000000"))
            if state != expected_state or int(record["NREFA"]) != state[0]:
                raise ValueError(
                    f"L8 raw accumulator slot mismatch at line {line_no} for {acc_key}: "
                    f"got {state} (NREFA={record.get('NREFA')}), expected {expected_state}"
                )
            raw_slots[acc_key] = dict(record)

        elif ev == "lsq_coef_end":
            lsq_end_seen = True
            if (
                record.get("expected_rows") != 7248
                or record.get("emitted_rows") != 7248
                or record.get("row_count_matches") is not True
                or record.get("defect_count") != 0
                or len(projected_residual_members) != 7248
                or {m["row_index"] for m in projected_residual_members}
                != set(range(1, 7249))
            ):
                raise ValueError(
                    f"lsq_coef_end coverage check failed at line {line_no}: {record!r}"
                )

        elif ev == "completeness_row_input":
            row_idx = _require_nonbool_int(
                record.get("row_index"),
                event=ev,
                field="row_index",
                call_id=call_id,
                row_index=record.get("row_index"),
                line_no=line_no,
            )
            key = (int(call_id), row_idx)
            if key in open_comp_rows:
                raise ValueError(
                    f"Duplicate open completeness_row_input for {key} at line {line_no}"
                )
            c1_obs_code = _require_nonbool_int(
                record.get("completeness_observed_code"),
                event=ev,
                field="completeness_observed_code",
                call_id=call_id,
                row_index=row_idx,
                line_no=line_no,
            )
            if c1_obs_code not in (0, 1):
                raise ValueError(
                    f"{ev} field 'completeness_observed_code' must be 0 or 1 at "
                    f"call_id={call_id}, row_index={row_idx}, line {line_no}, got {c1_obs_code!r}"
                )
            c1_part_code = _require_nonbool_int(
                record.get("completeness_partition_code"),
                event=ev,
                field="completeness_partition_code",
                call_id=call_id,
                row_index=row_idx,
                line_no=line_no,
            )
            c1_ifree = _require_nonbool_int(
                record.get("IFREE"),
                event=ev,
                field="IFREE",
                call_id=call_id,
                row_index=row_idx,
                line_no=line_no,
            )
            expected_c1_ifree = 2 if c1_part_code == 0 else 1
            if c1_ifree not in (1, 2) or c1_ifree != expected_c1_ifree:
                raise ValueError(
                    f"{ev} field 'IFREE'/'completeness_partition_code' contradiction at "
                    f"call_id={call_id}, row_index={row_idx}, line {line_no}: "
                    f"IFREE={c1_ifree!r}, completeness_partition_code={c1_part_code!r} "
                    f"(expected IFREE={expected_c1_ifree})"
                )
            c1_hkl = [
                _require_nonbool_int(
                    record.get("asu_H"),
                    event=ev,
                    field="asu_H",
                    call_id=call_id,
                    row_index=row_idx,
                    line_no=line_no,
                ),
                _require_nonbool_int(
                    record.get("asu_K"),
                    event=ev,
                    field="asu_K",
                    call_id=call_id,
                    row_index=row_idx,
                    line_no=line_no,
                ),
                _require_nonbool_int(
                    record.get("asu_L"),
                    event=ev,
                    field="asu_L",
                    call_id=call_id,
                    row_index=row_idx,
                    line_no=line_no,
                ),
            ]
            _decode_real(record.get("RSQ"), context=f"C1 RSQ line {line_no}")
            _decode_real(record.get("RHO"), context=f"C1 RHO line {line_no}")
            open_comp_rows[key] = {
                "input": record,
                "line": line_no,
                "hkl": c1_hkl,
                "shells": [],
                "overall": False,
            }

        elif ev in ("completeness_shell_increment", "completeness_overall_increment"):
            row_idx = _require_nonbool_int(
                record.get("row_index"),
                event=ev,
                field="row_index",
                call_id=call_id,
                row_index=record.get("row_index"),
                line_no=line_no,
            )
            key = (int(call_id), row_idx)
            if key not in open_comp_rows:
                raise ValueError(
                    f"Unmatched {ev} without open C1 row at call_id={call_id}, "
                    f"row_index={row_idx}, line {line_no}"
                )
            row_state = open_comp_rows[key]
            inp = row_state["input"]
            c1_line = row_state["line"]
            slot_field = "J" if ev == "completeness_shell_increment" else "NB1"
            slot_idx = _require_nonbool_int(
                record.get(slot_field),
                event=ev,
                field=slot_field,
                call_id=call_id,
                row_index=row_idx,
                line_no=line_no,
            )
            part = _require_nonbool_int(
                record.get("IFREE"),
                event=ev,
                field="IFREE",
                call_id=call_id,
                row_index=row_idx,
                line_no=line_no,
            )
            rec_obs_code = _require_nonbool_int(
                record.get("completeness_observed_code"),
                event=ev,
                field="completeness_observed_code",
                call_id=call_id,
                row_index=row_idx,
                line_no=line_no,
            )
            if part != inp["IFREE"]:
                raise ValueError(
                    f"{ev} field 'IFREE' contradicts open C1 row at call_id={call_id}, "
                    f"row_index={row_idx}, line {line_no} (C1 line {c1_line}): "
                    f"got {part!r}, C1 IFREE={inp['IFREE']!r}"
                )
            if rec_obs_code != inp["completeness_observed_code"]:
                raise ValueError(
                    f"{ev} field 'completeness_observed_code' contradicts open C1 row at "
                    f"call_id={call_id}, row_index={row_idx}, line {line_no} (C1 line {c1_line}): "
                    f"got {rec_obs_code!r}, C1 completeness_observed_code={inp['completeness_observed_code']!r}"
                )
            inc_obs_raw = record.get("incremented_observed")
            if not isinstance(inc_obs_raw, bool) or inc_obs_raw != (rec_obs_code == 1):
                raise ValueError(
                    f"{ev} field 'incremented_observed' contradicts completeness_observed_code "
                    f"at call_id={call_id}, row_index={row_idx}, line {line_no} (C1 line {c1_line}): "
                    f"got {inc_obs_raw!r}, completeness_observed_code={rec_obs_code!r}"
                )
            bound_rec = _require_bound_slot(
                c0_bounds,
                namespace="reporting_completeness",
                hook_label="C0",
                slot_idx=slot_idx,
                call_id=call_id,
                row_index=row_idx,
                consuming_line=line_no,
                consuming_event=ev,
            )
            acc_key = (int(call_id), part, slot_idx)
            old_obs, old_miss = comp_accum.get(acc_key, (0, 0))
            inc_obs = inc_obs_raw
            expected_counts = (old_obs + int(inc_obs), old_miss + int(not inc_obs))
            actual_counts = (
                (int(record["NREFA_after"]), int(record["NREFM_after"]))
                if ev == "completeness_shell_increment"
                else (int(record["NREFA_NB1_after"]), int(record["NREFM_NB1_after"]))
            )
            if actual_counts != expected_counts:
                raise ValueError(
                    f"{ev} integer counter mismatch at line {line_no} for {acc_key}: "
                    f"got {actual_counts}, expected {expected_counts}"
                )
            comp_accum[acc_key] = actual_counts
            if ev == "completeness_shell_increment":
                smin_j = _decode_real(
                    record.get("SMINB_J"), context=f"C2 SMINB_J line {line_no}"
                )
                smax_j = _decode_real(
                    record.get("SMAXB_J"), context=f"C2 SMAXB_J line {line_no}"
                )
                if (
                    smin_j.bits_hex != bound_rec["SMINB"]["bits_hex"]
                    or smax_j.bits_hex != bound_rec["SMAXB"]["bits_hex"]
                ):
                    raise ValueError(
                        f"C2 shell bound mismatch at line {line_no} for J={slot_idx}"
                    )
                row_state["shells"].append(slot_idx)
            else:
                row_state["overall"] = True

        elif ev == "completeness_row_terminal":
            row_idx = _require_nonbool_int(
                record.get("row_index"),
                event=ev,
                field="row_index",
                call_id=call_id,
                row_index=record.get("row_index"),
                line_no=line_no,
            )
            key = (int(call_id), row_idx)
            if key not in open_comp_rows:
                raise ValueError(
                    f"Unmatched completeness_row_terminal for {key} at line {line_no}"
                )
            row_state = open_comp_rows.pop(key)
            inp = row_state["input"]
            c1_line = row_state["line"]
            shells = row_state["shells"]
            c4_ifree = _require_nonbool_int(
                record.get("IFREE"),
                event=ev,
                field="IFREE",
                call_id=call_id,
                row_index=row_idx,
                line_no=line_no,
            )
            obs_code = _require_nonbool_int(
                record.get("completeness_observed_code"),
                event=ev,
                field="completeness_observed_code",
                call_id=call_id,
                row_index=row_idx,
                line_no=line_no,
            )
            if c4_ifree != inp["IFREE"]:
                raise ValueError(
                    f"{ev} field 'IFREE' contradicts open C1 row at call_id={call_id}, "
                    f"row_index={row_idx}, line {line_no} (C1 line {c1_line}): "
                    f"got {c4_ifree!r}, C1 IFREE={inp['IFREE']!r}"
                )
            if obs_code != inp["completeness_observed_code"]:
                raise ValueError(
                    f"{ev} field 'completeness_observed_code' contradicts open C1 row at "
                    f"call_id={call_id}, row_index={row_idx}, line {line_no} (C1 line {c1_line}): "
                    f"got {obs_code!r}, C1 completeness_observed_code={inp['completeness_observed_code']!r}"
                )
            expected_outcome = (
                "observed_shell_and_overall"
                if obs_code == 1
                else "missing_shell_and_overall"
            )
            if (
                len(shells) != 1
                or int(record["matched_shell_count"]) != 1
                or int(record["first_matched_bin"]) != shells[0]
                or int(record["last_matched_bin"]) != shells[0]
                or record.get("overall_incremented") is not True
                or row_state["overall"] is not True
                or obs_code not in (0, 1)
                or bool(record["observed_incremented"]) != (obs_code == 1)
                or bool(record["missing_incremented"]) != (obs_code == 0)
                or record.get("row_outcome") != expected_outcome
            ):
                raise ValueError(
                    f"Inconsistent completeness_row_terminal at line {line_no}: {record!r}"
                )
            _require_bound_slot(
                c0_bounds,
                namespace="reporting_completeness",
                hook_label="C0",
                slot_idx=shells[0],
                call_id=call_id,
                row_index=row_idx,
                consuming_line=line_no,
                consuming_event=ev,
            )
            projected_completeness_members.append(
                {
                    "call_id": int(call_id),
                    "row_index": row_idx,
                    "input_line": c1_line,
                    "terminal_line": line_no,
                    "hkl": list(row_state["hkl"]),
                    "IFREE": c4_ifree,
                    "observed_code": obs_code,
                    "matched_bins": list(shells),
                    "row_outcome": record["row_outcome"],
                }
            )

        elif ev == "completeness_summary_slot":
            slot_idx = _require_nonbool_int(
                record.get("slot_index"),
                event=ev,
                field="slot_index",
                call_id=call_id,
                row_index=None,
                line_no=line_no,
            )
            _require_bound_slot(
                c0_bounds,
                namespace="reporting_completeness",
                hook_label="C0",
                slot_idx=slot_idx,
                call_id=call_id,
                row_index=None,
                consuming_line=line_no,
                consuming_event=ev,
            )
            work_counts = comp_accum.get((int(call_id), 1, slot_idx), (0, 0))
            free_counts = comp_accum.get((int(call_id), 2, slot_idx), (0, 0))
            nrefa_w = int(record["NREFA_work"])
            nrefm_w = int(record["NREFM_work"])
            nrefa_f = int(record["NREFA_free"])
            nrefm_f = int(record["NREFM_free"])
            if (
                (nrefa_w, nrefm_w) != work_counts
                or (nrefa_f, nrefm_f) != free_counts
                or nrefm_f != 0
                or int(record["HNREF_SHELL_WORK"]) != nrefa_w
                or int(record["HNREF_SHELL_FREE"]) != nrefa_f
                or int(record["HNREF_SHELL_OBS"]) != nrefa_w + nrefa_f
                or int(record["HNREF_SHELL_ALL"]) != nrefa_w + nrefa_f + nrefm_w + nrefm_f
            ):
                raise ValueError(
                    f"completeness_summary_slot mismatch at line {line_no} for slot {slot_idx}: {record!r}"
                )
            _decode_real(
                record.get("HPERC_SHELL_REFL"),
                context=f"C5 HPERC_SHELL_REFL line {line_no}",
            )
            projected_comp_slots.append({"line": line_no, "record": dict(record)})

        elif ev == "completeness_end":
            comp_end_seen = True
            if (
                record.get("expected_rows") != 7262
                or record.get("emitted_rows") != 7262
                or record.get("row_count_matches") is not True
                or record.get("defect_count") != 0
                or len(projected_completeness_members) != 7262
                or {m["row_index"] for m in projected_completeness_members}
                != set(range(1, 7263))
            ):
                raise ValueError(
                    f"completeness_end coverage check failed at line {line_no}: {record!r}"
                )

        elif ev == "refmac_normal_termination":
            termination_seen = True
            if (
                record.get("lsq_call_count") != 1
                or record.get("completeness_call_count") != 1
                or record.get("lsq_call_left_open") is not False
                or record.get("completeness_call_left_open") is not False
            ):
                raise ValueError(
                    f"Unexpected refmac_normal_termination fields at line {line_no}: {record!r}"
                )

    if (
        set(lsq_calls.keys()) != {1}
        or set(comp_calls.keys()) != {1}
        or not lsq_end_seen
        or not comp_end_seen
        or not termination_seen
        or open_lsq_rows
        or open_comp_rows
    ):
        raise ValueError(
            "Incomplete trace call lifecycle or dangling open row state"
        )

    if set(c0_bounds.keys()) != set(range(1, 22)) or set(l0_bounds.keys()) != set(
        range(1, 22)
    ):
        raise ValueError("Missing C0 or L0 bin boundary slots (expected 1..21)")

    for slot_idx in range(1, 22):
        _, c0_rec = c0_bounds[slot_idx]
        _, l0_rec = l0_bounds[slot_idx]
        c0_smin = _decode_real(c0_rec["SMINB"], context=f"C0 SMINB[{slot_idx}]")
        c0_smax = _decode_real(c0_rec["SMAXB"], context=f"C0 SMAXB[{slot_idx}]")
        l0_smin = _decode_real(l0_rec["SMINB"], context=f"L0 SMINB[{slot_idx}]")
        l0_smax = _decode_real(l0_rec["SMAXB"], context=f"L0 SMAXB[{slot_idx}]")
        if (
            c0_smin.bits_hex != l0_smin.bits_hex
            or c0_smin.decimal_str != l0_smin.decimal_str
            or c0_smax.bits_hex != l0_smax.bits_hex
            or c0_smax.decimal_str != l0_smax.decimal_str
        ):
            raise ValueError(
                f"C0 vs L0 boundary mismatch at slot {slot_idx}: C0=({c0_smin.bits_hex}, {c0_smax.bits_hex}) "
                f"vs L0=({l0_smin.bits_hex}, {l0_smax.bits_hex})"
            )
        if slot_idx < 20:
            next_l0_smin = _decode_real(
                l0_bounds[slot_idx + 1][1]["SMINB"],
                context=f"L0 SMINB[{slot_idx + 1}]",
            )
            if l0_smax.bits_hex != next_l0_smin.bits_hex:
                raise ValueError(
                    f"Adjacent shell endpoint mismatch between slot {slot_idx} SMAXB "
                    f"({l0_smax.bits_hex}) and slot {slot_idx + 1} SMINB ({next_l0_smin.bits_hex})"
                )

    smin_1 = _decode_real(l0_bounds[1][1]["SMINB"], context="L0 SMINB[1]")
    smax_20 = _decode_real(l0_bounds[20][1]["SMAXB"], context="L0 SMAXB[20]")
    smin_21 = _decode_real(l0_bounds[21][1]["SMINB"], context="L0 SMINB[21]")
    smax_21 = _decode_real(l0_bounds[21][1]["SMAXB"], context="L0 SMAXB[21]")
    if (
        smin_21.bits_hex != smin_1.bits_hex
        or smax_21.bits_hex != smax_20.bits_hex
        or smin_21.bits_hex != "3C23EEAD"
        or smax_21.bits_hex != "3E4CCC57"
    ):
        raise ValueError(
            f"Overall slot 21 bounds ({smin_21.bits_hex}, {smax_21.bits_hex}) do not span "
            f"slot 1..20 bounds ({smin_1.bits_hex}, {smax_20.bits_hex})"
        )

    projected_native_slots = [
        {"call_id": k[0], "IFREE": k[1], "slot": k[2], "record": v}
        for k, v in raw_slots.items()
    ]
    if len(projected_native_slots) != 42 or len(projected_comp_slots) != 21:
        raise ValueError(
            f"Unexpected slot record counts: native={len(projected_native_slots)}, completeness={len(projected_comp_slots)}"
        )

    _assert_canonical_json_equal(
        projected_bounds, retained_native_bin_bounds, label="native_bin_bounds.json"
    )
    _assert_canonical_json_equal(
        projected_residual_members,
        retained_residual_members,
        label="residual_members.json",
    )
    _assert_canonical_json_equal(
        projected_completeness_members,
        retained_completeness_members,
        label="completeness_members.json",
    )
    _assert_canonical_json_equal(
        projected_native_slots,
        retained_native_slot_records,
        label="native_slot_records.json",
    )
    _assert_canonical_json_equal(
        projected_comp_slots,
        retained_completeness_slot_records,
        label="completeness_slot_records.json",
    )

    # Also cross-check retained slot summaries against retained member arrays so
    # mutations to retained slot JSON or member JSON fail even if checked directly.
    for slot_idx in range(1, 22):
        c_slot = retained_completeness_slot_records[slot_idx - 1]["record"]
        for part, suffix in ((1, "work"), (2, "free")):
            r_slot = raw_slots[(1, part, slot_idx)]
            if slot_idx < 21:
                member_active = sum(
                    1
                    for m in retained_residual_members
                    if m["IFREE"] == part
                    and m["shell_added"]
                    and m["matched_bin_index"] == slot_idx
                )
                comp_obs = sum(
                    1
                    for m in retained_completeness_members
                    if m["IFREE"] == part
                    and m["observed_code"] == 1
                    and m["matched_bins"] == [slot_idx]
                )
                comp_miss = sum(
                    1
                    for m in retained_completeness_members
                    if m["IFREE"] == part
                    and m["observed_code"] == 0
                    and m["matched_bins"] == [slot_idx]
                )
            else:
                member_active = sum(
                    1
                    for m in retained_residual_members
                    if m["IFREE"] == part and m["overall_added"]
                )
                comp_obs = sum(
                    1
                    for m in retained_completeness_members
                    if m["IFREE"] == part and m["observed_code"] == 1
                )
                comp_miss = sum(
                    1
                    for m in retained_completeness_members
                    if m["IFREE"] == part and m["observed_code"] == 0
                )
            if (
                int(r_slot["nrefa_this"]) != member_active
                or int(r_slot["NREFA"]) != member_active
                or int(c_slot[f"NREFA_{suffix}"]) != member_active
                or comp_obs != member_active
                or int(r_slot["NREFM"]) != comp_miss
                or int(c_slot[f"NREFM_{suffix}"]) != comp_miss
            ):
                raise ValueError(
                    f"Slot/member count mismatch at slot={slot_idx}, IFREE={part}: "
                    f"r_slot=({r_slot['nrefa_this']}, {r_slot['NREFM']}), "
                    f"c_slot=({c_slot[f'NREFA_{suffix}']}, {c_slot[f'NREFM_{suffix}']}), "
                    f"member_active={member_active}, comp_obs={comp_obs}, comp_miss={comp_miss}"
                )

    lsq_begin = lsq_calls[1]
    return {
        "mode": {
            "REFS": lsq_begin["REFS"],
            "LREFIN": lsq_begin["LREFIN"],
            "IMODE": lsq_begin["IMODE"],
            "DataSource": lsq_begin["DataSource"],
            "FREER_FLAG": lsq_begin["FREER_FLAG"],
            "LFreeRexcludeVal": lsq_begin["LFreeRexcludeVal"],
            "NPART": lsq_begin["NPART"],
            "NDENS": lsq_begin["NDENS"],
            "NBIN": lsq_begin["NBIN"],
            "NB1": lsq_begin["NB1"],
            "NREF": lsq_begin["NREF"],
            "NOBS": lsq_begin["NOBS"],
            "NASYM": comp_calls[1]["NASYM"],
            "NSYM": comp_calls[1]["NSYM"],
            "RES_MAX_bits_hex": comp_calls[1]["RES_MAX"]["bits_hex"],
            "residual_call_ids": [1],
            "completeness_call_ids": [1],
        },
        "retained_projections": {
            "native_bin_bounds_matches": True,
            "native_bin_bounds_count": len(projected_bounds),
            "c0_l0_bounds_identical": True,
            "shared_internal_endpoints_count": 19,
            "residual_members_matches": True,
            "residual_members_count": len(projected_residual_members),
            "completeness_members_matches": True,
            "completeness_members_count": len(projected_completeness_members),
            "native_slot_records_matches": True,
            "native_slot_records_count": len(projected_native_slots),
            "completeness_slot_records_matches": True,
            "completeness_slot_records_count": len(projected_comp_slots),
        },
    }


def _extract_column_datasets(headers: Sequence[str]) -> dict[str, int]:
    datasets: dict[str, int] = {}
    for line in headers:
        if line.startswith("COLUMN "):
            parts = line.split()
            if len(parts) != 6:
                raise ValueError(f"Malformed COLUMN card in MTZ headers: {line!r}")
            datasets[parts[1]] = int(parts[5])
    return datasets


def _decode_uint32_word_hex_float(word_hex: str) -> float:
    """Decode an 8-character canonical uint32 bit-word hex string as an IEEE-754 binary32 float."""
    if not isinstance(word_hex, str) or len(word_hex) != 8:
        raise ValueError(f"Expected 8-char uint32 word hex string, got {word_hex!r}")
    word_u32 = int(word_hex, 16)
    return float(struct.unpack("<f", struct.pack("<I", word_u32))[0])


def _decode_mtz_integral_hkl_words(
    h_word_u32: int,
    k_word_u32: int,
    l_word_u32: int,
    *,
    row_idx: int,
) -> tuple[int, int, int]:
    """Decode IEEE-754 binary32 MTZ H/K/L words and require finite integral coordinates."""
    coords: list[int] = []
    for axis_label, word_u32 in (
        ("H", h_word_u32),
        ("K", k_word_u32),
        ("L", l_word_u32),
    ):
        val = float(struct.unpack("<f", struct.pack("<I", word_u32))[0])
        if not math.isfinite(val) or not val.is_integer():
            raise ValueError(
                f"Non-finite or non-integral HKLOUT {axis_label} word 0x{word_u32:08x} "
                f"(decoded={val!r}) at row_index={row_idx}"
            )
        coords.append(int(val))
    return (coords[0], coords[1], coords[2])


def _check_mtz_word_join(
    bundle_or_original_mtz_bytes: Mapping[str, Any] | bytes,
    projected_mtz_bytes: bytes | None = None,
    hklout_mtz_bytes: bytes | None = None,
    *,
    retained_ledger: Mapping[str, Any] | None = None,
    retained_raw_export: Mapping[str, Any] | None = None,
    residual_members: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Verify input/projected/output MTZ words, raw export slices, and 3 reflection populations."""
    if isinstance(bundle_or_original_mtz_bytes, Mapping):
        bundle = bundle_or_original_mtz_bytes
        original_mtz_bytes: bytes = bundle["original_mtz_bytes"]
        if projected_mtz_bytes is None:
            projected_mtz_bytes = bundle["projected_mtz_bytes"]
        if hklout_mtz_bytes is None:
            hklout_mtz_bytes = bundle["hklout_mtz_bytes"]
        if retained_ledger is None:
            retained_ledger = bundle["input_hkl_ledger"]
        if retained_raw_export is None:
            retained_raw_export = bundle["hklout_raw_export"]
        if residual_members is None:
            residual_members = bundle["residual_members"]
    else:
        original_mtz_bytes = bundle_or_original_mtz_bytes

    if (
        projected_mtz_bytes is None
        or hklout_mtz_bytes is None
        or retained_ledger is None
        or retained_raw_export is None
        or residual_members is None
    ):
        raise ValueError(
            "_check_mtz_word_join requires original/projected/hklout MTZ bytes, retained_ledger, retained_raw_export, and residual_members"
        )

    orig_ledger = onesar_rerun.build_input_hkl_ledger(original_mtz_bytes)
    proj_ledger = onesar_rerun.build_input_hkl_ledger(projected_mtz_bytes)

    for key in LEDGER_ROW_DOMAIN_KEYS:
        _assert_canonical_json_equal(
            orig_ledger.get(key),
            proj_ledger.get(key),
            label=f"original_vs_projected_ledger.{key}",
        )
        _assert_canonical_json_equal(
            proj_ledger.get(key),
            retained_ledger.get(key),
            label=f"projected_vs_retained_ledger.{key}",
        )
    if proj_ledger.get("mtz_sha256") != retained_ledger.get("mtz_sha256"):
        raise ValueError(
            f"Retained input_hkl_ledger.json mtz_sha256 mismatch: "
            f"{retained_ledger.get('mtz_sha256')!r} != {proj_ledger.get('mtz_sha256')!r}"
        )

    expected_counts = {
        "raw_total": 7248,
        "raw_work": 6505,
        "raw_free": 723,
        "raw_unassigned": 20,
        "eligible_total": 7228,
        "eligible_work": 6505,
        "eligible_free": 723,
        "eligible_zero_f": 11,
        "eligible_negative_f": 0,
        "ineligible_total": 20,
        "ineligible_nonfinite_f": 20,
        "ineligible_nonpositive_or_nonfinite_sigf": 0,
        "ineligible_unassigned_flag": 20,
    }
    _assert_canonical_json_equal(
        retained_ledger.get("counts"), expected_counts, label="input_hkl_ledger.counts"
    )

    labels = ("F-obs", "SIGF-obs", "R-free-flags")
    orig_layout = onesar_rerun._inspect_mtz_layout(original_mtz_bytes, labels)
    proj_layout = onesar_rerun._inspect_mtz_layout(projected_mtz_bytes, labels)
    out_layout = onesar_rerun._inspect_mtz_layout(hklout_mtz_bytes, labels)

    if (
        orig_layout["nrows"] != 7248
        or proj_layout["nrows"] != 7248
        or out_layout["nrows"] != 7248
        or orig_layout["ncols"] != 16
        or proj_layout["ncols"] != 6
        or out_layout["ncols"] != 17
    ):
        raise ValueError(
            f"Unexpected MTZ dimensions: orig=({orig_layout['ncols']}, {orig_layout['nrows']}), "
            f"proj=({proj_layout['ncols']}, {proj_layout['nrows']}), "
            f"out=({out_layout['ncols']}, {out_layout['nrows']})"
        )

    orig_ds = _extract_column_datasets(orig_layout["headers"])
    proj_ds = _extract_column_datasets(proj_layout["headers"])
    out_ds = _extract_column_datasets(out_layout["headers"])
    six_obs_cols = ("H", "K", "L", "F-obs", "SIGF-obs", "R-free-flags")
    for col_name in six_obs_cols:
        if orig_ds.get(col_name) != 1 or proj_ds.get(col_name) != 1:
            raise ValueError(
                f"Expected dataset_id=1 for {col_name} in original/projected MTZ, "
                f"got orig={orig_ds.get(col_name)}, proj={proj_ds.get(col_name)}"
            )
    expected_out_ds = {
        "H": 0,
        "K": 0,
        "L": 0,
        "R-free-flags": 0,
        "F-obs": 1,
        "SIGF-obs": 1,
        "FC": 1,
        "PHIC": 1,
        "FC_ALL": 1,
        "PHIC_ALL": 1,
        "FWT": 1,
        "PHWT": 1,
        "DELFWT": 1,
        "PHDELWT": 1,
        "FOM": 1,
        "FC_ALL_LS": 1,
        "PHIC_ALL_LS": 1,
    }
    if out_ds != expected_out_ds:
        raise ValueError(
            f"Unexpected HKLOUT column dataset allocation: got {out_ds}, expected {expected_out_ds}"
        )

    # Bind refmac_hklout_raw_export.json directly to refmac_hklout.mtz bytes.
    header_offset = int(out_layout["header_byte_offset"])
    if (
        retained_raw_export.get("byte_length") != len(hklout_mtz_bytes)
        or len(hklout_mtz_bytes) != 497664
        or retained_raw_export.get("data_start_byte_offset") != 80
        or retained_raw_export.get("header_byte_offset") != header_offset
        or header_offset != 492944
        or retained_raw_export.get("data_region_byte_length") != 492864
        or retained_raw_export.get("data_word_count") != 123216
        or retained_raw_export.get("row_count_exported") != 7248
    ):
        raise ValueError("refmac_hklout_raw_export.json byte/word layout metadata mismatch")

    primary_cards = retained_raw_export.get("primary_header_cards")
    if not isinstance(primary_cards, Sequence) or len(primary_cards) < 2:
        raise ValueError("Missing primary_header_cards in refmac_hklout_raw_export.json")
    if primary_cards[-1] != "END".ljust(80):
        raise ValueError(
            f"Expected final primary_header_card to be 80-char END card, got {primary_cards[-1]!r}"
        )
    for card_idx, card_str in enumerate(primary_cards):
        if not isinstance(card_str, str) or len(card_str) != 80:
            raise ValueError(
                f"primary_header_cards[{card_idx}] is not an 80-char string: {card_str!r}"
            )
        slice_start = header_offset + 80 * card_idx
        slice_bytes = hklout_mtz_bytes[slice_start : slice_start + 80]
        if slice_bytes.decode("ascii") != card_str:
            raise ValueError(
                f"primary_header_cards[{card_idx}] does not match refmac_hklout.mtz at byte offset {slice_start}"
            )
    if [c.strip() for c in primary_cards[:-1]] != out_layout["headers"]:
        raise ValueError(
            "Stripped primary_header_cards do not match _inspect_mtz_layout headers"
        )

    header_parse = retained_raw_export.get("header_parse", {})
    export_cols = header_parse.get("columns")
    if (
        header_parse.get("ncol") != 17
        or header_parse.get("nrows") != 7248
        or header_parse.get("nbatches") != 0
        or not isinstance(export_cols, Sequence)
        or len(export_cols) != 17
    ):
        raise ValueError("Malformed header_parse in refmac_hklout_raw_export.json")

    col_labels: list[str] = []
    for col_idx, col_desc in enumerate(export_cols):
        label = col_desc.get("label")
        col_key = col_desc.get("column_key")
        ds_str = col_desc.get("dataset_id")
        raw_col_idx = col_desc.get("column_index")
        if (
            not isinstance(raw_col_idx, int)
            or isinstance(raw_col_idx, bool)
            or raw_col_idx != col_idx
            or label != col_key
            or label != out_layout["columns"][col_idx]
            or ds_str != str(expected_out_ds[label])
        ):
            raise ValueError(
                f"Column descriptor mismatch at index {col_idx}: {col_desc!r}"
            )
        col_labels.append(str(label))

    export_rows = retained_raw_export.get("rows")
    if not isinstance(export_rows, Sequence) or len(export_rows) != 7248:
        raise ValueError("Expected 7,248 rows in refmac_hklout_raw_export.json")

    try:
        h_col_idx = col_labels.index("H")
        k_col_idx = col_labels.index("K")
        l_col_idx = col_labels.index("L")
    except ValueError as exc:
        raise ValueError(
            f"Validated HKLOUT column layout is missing H/K/L columns: {col_labels!r}"
        ) from exc

    hklout_words = struct.unpack_from("<123216I", hklout_mtz_bytes, 80)
    export_by_hkl: dict[tuple[int, int, int], Mapping[str, Any]] = {}
    for row_idx, exp_row in enumerate(export_rows):
        raw_row_idx = exp_row.get("row_index")
        if (
            not isinstance(raw_row_idx, int)
            or isinstance(raw_row_idx, bool)
            or raw_row_idx != row_idx
            or exp_row.get("is_integral_hkl") is not True
        ):
            raise ValueError(
                f"Malformed raw export row metadata at row_index={row_idx}: "
                f"got row_index={raw_row_idx!r}, is_integral_hkl={exp_row.get('is_integral_hkl')!r}"
            )
        words_hex = exp_row.get("column_words_hex", {})
        base = row_idx * 17
        for col_idx, col_label in enumerate(col_labels):
            mtz_word_hex = f"{hklout_words[base + col_idx]:08x}"
            exp_word_hex = str(words_hex.get(col_label, "")).lower()
            if exp_word_hex != mtz_word_hex:
                raise ValueError(
                    f"HKLOUT word mismatch at row {row_idx}, column {col_label}: "
                    f"raw_export={exp_word_hex!r} vs mtz_bytes={mtz_word_hex!r}"
                )
        decoded_hkl = _decode_mtz_integral_hkl_words(
            hklout_words[base + h_col_idx],
            hklout_words[base + k_col_idx],
            hklout_words[base + l_col_idx],
            row_idx=row_idx,
        )
        recorded_hkl = _require_exact_int_hkl_triplet(
            exp_row.get("hkl"),
            context=f"refmac_hklout_raw_export.rows[{row_idx}].hkl",
        )
        _assert_canonical_json_equal(
            list(exp_row.get("hkl")),
            [decoded_hkl[0], decoded_hkl[1], decoded_hkl[2]],
            label=f"refmac_hklout_raw_export.rows[{row_idx}].hkl",
        )
        if recorded_hkl != decoded_hkl:
            raise ValueError(
                f"HKLOUT row {row_idx} exported hkl metadata {recorded_hkl} does not match "
                f"decoded MTZ H/K/L words {decoded_hkl}"
            )
        if decoded_hkl in export_by_hkl:
            raise ValueError(
                f"Duplicate decoded HKL {decoded_hkl} in refmac_hklout.mtz / "
                f"refmac_hklout_raw_export.json at row {row_idx}"
            )
        export_by_hkl[decoded_hkl] = exp_row

    if len(residual_members) != 7248:
        raise ValueError(
            f"Expected 7,248 residual_members entries, got {len(residual_members)}"
        )
    residual_by_hkl: dict[tuple[int, int, int], Mapping[str, Any]] = {}
    for member_idx, member in enumerate(residual_members):
        hkl = _require_exact_int_hkl_triplet(
            member.get("hkl"),
            context=f"residual_members[{member_idx}].hkl",
        )
        if hkl in residual_by_hkl:
            raise ValueError(f"Duplicate HKL {hkl} in residual_members.json")
        residual_by_hkl[hkl] = member

    ledger_rows = retained_ledger["raw_rows"]
    if len(ledger_rows) != 7248:
        raise ValueError(f"Expected 7,248 ledger raw_rows, got {len(ledger_rows)}")

    positive_work_count = 0
    positive_free_count = 0
    zero_f_row_indices: list[int] = []
    padding_row_indices: list[int] = []

    for row_idx, in_row in enumerate(ledger_rows):
        in_row_idx = in_row.get("row_index")
        if (
            not isinstance(in_row_idx, int)
            or isinstance(in_row_idx, bool)
            or in_row_idx != row_idx
        ):
            raise ValueError(f"Ledger row_index mismatch at {row_idx}")
        hkl = _require_exact_int_hkl_triplet(
            in_row.get("hkl"),
            context=f"input_hkl_ledger.raw_rows[{row_idx}].hkl",
        )
        if hkl not in residual_by_hkl or hkl not in export_by_hkl:
            raise ValueError(
                f"Input HKL {hkl} (row {row_idx}) missing from residual_members or HKLOUT"
            )
        res_row = residual_by_hkl[hkl]
        out_row = export_by_hkl[hkl]
        out_row_idx = out_row.get("row_index")
        if (
            not isinstance(out_row_idx, int)
            or isinstance(out_row_idx, bool)
            or out_row_idx != row_idx
        ):
            raise ValueError(
                f"HKLOUT row order drifted from input MTZ at HKL {hkl}: "
                f"input={row_idx} vs hklout={out_row['row_index']}"
            )

        in_f_hex = str(in_row["f_obs_word_hex"]).lower()
        in_sigf_hex = str(in_row["sigf_obs_word_hex"]).lower()
        in_flag_hex = str(in_row["r_free_flag_word_hex"]).lower()

        yo_dec = _decode_real(res_row["YO"], context=f"residual YO {hkl}")
        so_dec = _decode_real(res_row["SO"], context=f"residual SO {hkl}")
        flag_dec = _decode_real(
            res_row["native_free_flag"], context=f"residual native_free_flag {hkl}"
        )

        out_words = out_row["column_words_hex"]
        out_f_hex = str(out_words["F-obs"]).lower()
        out_sigf_hex = str(out_words["SIGF-obs"]).lower()
        out_flag_hex = str(out_words["R-free-flags"]).lower()

        if in_row["eligible"] is True:
            f_val = in_row["f_obs"]
            sigf_val = in_row["sigf_obs"]
            if (
                f_val is None
                or sigf_val is None
                or not math.isfinite(float(f_val))
                or not math.isfinite(float(sigf_val))
                or float(sigf_val) <= 0.0
            ):
                raise ValueError(f"Invalid eligible input observation at {hkl}: {in_row!r}")

            if float(f_val) == 0.0:
                zero_f_row_indices.append(row_idx)
                if (
                    in_f_hex != "00000000"
                    or in_row["partition"] != "work"
                    or in_row["r_free_flag"] != 0
                    or in_flag_hex != "00000000"
                    or yo_dec.bits_hex != "00000000"
                    or so_dec.bits_hex != "BC23D70A"
                    or flag_dec.bits_hex != "00000000"
                    or res_row["IFREE"] != 1
                    or res_row["overall_added"] is not False
                    or res_row["shell_added"] is not False
                    or res_row["row_outcome"] != "excluded_sigma_guard_in_shell"
                    or res_row["YOS"] is not None
                    or res_row["YC_ALL"] is not None
                    or res_row["DY"] is not None
                    or out_f_hex != "fffa5a5a"
                    or out_sigf_hex != "fffa5a5a"
                    or out_flag_hex != "00000000"
                ):
                    raise ValueError(
                        f"Zero-F eligible work row contract violated at HKL {hkl} (row {row_idx})"
                    )
            else:
                if float(f_val) <= 0.0:
                    raise ValueError(f"Unexpected negative F-obs at HKL {hkl}")
                is_free = in_row["partition"] == "free"
                expected_flag_hex = "3f800000" if is_free else "00000000"
                expected_ifree = 2 if is_free else 1
                if is_free:
                    positive_free_count += 1
                else:
                    positive_work_count += 1

                if (
                    in_flag_hex != expected_flag_hex
                    or yo_dec.bits_hex.lower() != in_f_hex
                    or so_dec.bits_hex.lower() != in_sigf_hex
                    or flag_dec.bits_hex.lower() != expected_flag_hex
                    or res_row["IFREE"] != expected_ifree
                    or res_row["overall_added"] is not True
                    or res_row["shell_added"] is not True
                    or res_row["row_outcome"] != "included_shell_and_overall"
                    or res_row["YOS"] is None
                    or res_row["YC_ALL"] is None
                    or res_row["DY"] is None
                    or out_flag_hex != expected_flag_hex
                    or out_f_hex == "fffa5a5a"
                    or out_sigf_hex == "fffa5a5a"
                ):
                    raise ValueError(
                        f"Positive eligible row contract violated at HKL {hkl} (row {row_idx})"
                    )
                _decode_real(res_row["YOS"], context=f"residual YOS {hkl}")
                _decode_real(res_row["YC_ALL"], context=f"residual YC_ALL {hkl}")
                _decode_real(res_row["DY"], context=f"residual DY {hkl}")
                out_f_val = _decode_uint32_word_hex_float(out_f_hex)
                out_sigf_val = _decode_uint32_word_hex_float(out_sigf_hex)
                if (
                    not math.isfinite(out_f_val)
                    or out_f_val <= 0.0
                    or not math.isfinite(out_sigf_val)
                    or out_sigf_val <= 0.0
                ):
                    raise ValueError(
                        f"Non-positive or non-finite HKLOUT F-obs/SIGF-obs for active row {hkl}"
                    )
        else:
            padding_row_indices.append(row_idx)
            if (
                in_row["partition"] != "unassigned"
                or in_row["eligibility_status"] != "excluded_nonfinite_f"
                or in_row["f_obs"] is not None
                or in_row["sigf_obs"] is not None
                or in_row["r_free_flag"] is not None
                or in_f_hex != "fffa5a5a"
                or in_sigf_hex != "fffa5a5a"
                or in_flag_hex != "fffa5a5a"
                or yo_dec.bits_hex != "00000000"
                or so_dec.bits_hex != "BC23D70A"
                or flag_dec.bits_hex != "80000000"
                or res_row["IFREE"] != 1
                or res_row["overall_added"] is not False
                or res_row["shell_added"] is not False
                or res_row["row_outcome"] != "excluded_sigma_guard_in_shell"
                or res_row["YOS"] is not None
                or res_row["YC_ALL"] is not None
                or res_row["DY"] is not None
                or out_f_hex != "fffa5a5a"
                or out_sigf_hex != "fffa5a5a"
                or out_flag_hex != "00000000"
            ):
                raise ValueError(
                    f"Unassigned padding row contract violated at HKL {hkl} (row {row_idx})"
                )

    if (
        positive_work_count != 6494
        or positive_free_count != 723
        or tuple(zero_f_row_indices) != EXPECTED_ZERO_F_INPUT_ROW_INDICES
        or tuple(padding_row_indices) != EXPECTED_PADDING_INPUT_ROW_INDICES
    ):
        raise ValueError(
            f"Population count/index mismatch: positive_work={positive_work_count}, "
            f"positive_free={positive_free_count}, zero_f_indices={zero_f_row_indices}, "
            f"padding_count={len(padding_row_indices)}"
        )

    return {
        "raw_total": 7248,
        "eligible_total": 7228,
        "eligible_work": 6505,
        "eligible_free": 723,
        "positive_eligible_total": 7217,
        "positive_eligible_work": positive_work_count,
        "positive_eligible_free": positive_free_count,
        "eligible_zero_f_work_count": len(zero_f_row_indices),
        "eligible_zero_f_input_row_indices": list(zero_f_row_indices),
        "unassigned_padding_count": len(padding_row_indices),
        "unassigned_padding_input_row_range": [
            padding_row_indices[0],
            padding_row_indices[-1],
        ],
        "native_excluded_so_le_zero_total": 31,
        "hklout_nan_f_sigf_total": 31,
        "hklout_padding_nan_to_free_zero_total": 20,
        "dataset_allocation": {
            "original_data_mtz": {col: orig_ds[col] for col in six_obs_cols},
            "projected_observations_mtz": {col: proj_ds[col] for col in six_obs_cols},
            "refmac_hklout_mtz": dict(out_ds),
            "hklout_split_base_and_observation_datasets": True,
        },
        "raw_export_verified": True,
    }


def _check_shared_hkls(
    residual_members_or_bundle: Sequence[Mapping[str, Any]] | Mapping[str, Any],
    completeness_members: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Verify cross-namespace HKL set relationships and captured J without RHO math."""
    if isinstance(residual_members_or_bundle, Mapping):
        bundle = residual_members_or_bundle
        residual_members: Sequence[Mapping[str, Any]] = bundle["residual_members"]
        if completeness_members is None:
            completeness_members = bundle["completeness_members"]
    else:
        residual_members = residual_members_or_bundle

    if completeness_members is None:
        raise ValueError(
            "_check_shared_hkls requires both residual_members and completeness_members"
        )

    if len(residual_members) != 7248 or len(completeness_members) != 7262:
        raise ValueError(
            f"Unexpected member array lengths: residual={len(residual_members)} (expected 7248), "
            f"completeness={len(completeness_members)} (expected 7262)"
        )

    res_by_hkl: dict[tuple[int, int, int], Mapping[str, Any]] = {}
    for row_idx, row in enumerate(residual_members):
        hkl = _require_exact_int_hkl_triplet(
            row.get("hkl"),
            context=f"residual_members[{row_idx}].hkl",
        )
        if hkl in res_by_hkl:
            raise ValueError(f"Duplicate HKL {hkl} in residual_members")
        res_by_hkl[hkl] = row

    comp_by_hkl: dict[tuple[int, int, int], Mapping[str, Any]] = {}
    for row_idx, row in enumerate(completeness_members):
        hkl = _require_exact_int_hkl_triplet(
            row.get("hkl"),
            context=f"completeness_members[{row_idx}].hkl",
        )
        if hkl in comp_by_hkl:
            raise ValueError(f"Duplicate HKL {hkl} in completeness_members")
        comp_by_hkl[hkl] = row

    res_hkls = set(res_by_hkl.keys())
    comp_hkls = set(comp_by_hkl.keys())
    if not (res_hkls < comp_hkls):
        missing_from_comp = sorted(res_hkls - comp_hkls)
        raise ValueError(
            f"residual_members HKLs are not a strict subset of completeness_members HKLs; "
            f"missing={missing_from_comp[:5]}"
        )

    extra_asu_hkls = comp_hkls - res_hkls
    if len(extra_asu_hkls) != 14:
        raise ValueError(
            f"Expected 14 extra ASU HKLs in completeness_members, got {len(extra_asu_hkls)}"
        )

    for hkl in sorted(res_hkls):
        r_row = res_by_hkl[hkl]
        c_row = comp_by_hkl[hkl]
        c_bins = c_row.get("matched_bins")
        r_bin = r_row.get("matched_bin_index")
        if (
            not isinstance(c_bins, Sequence)
            or len(c_bins) != 1
            or not isinstance(r_bin, int)
            or not (1 <= r_bin <= 20)
            or int(c_bins[0]) != r_bin
        ):
            raise ValueError(
                f"Cross-namespace captured J mismatch at shared HKL {hkl}: "
                f"residual matched_bin_index={r_bin!r} vs completeness matched_bins={c_bins!r}"
            )
        if int(c_row["IFREE"]) != int(r_row["IFREE"]):
            raise ValueError(
                f"Cross-namespace IFREE mismatch at shared HKL {hkl}: "
                f"residual={r_row['IFREE']} vs completeness={c_row['IFREE']}"
            )

    active_res_hkls = {
        hkl for hkl, r in res_by_hkl.items() if r.get("overall_added") is True
    }
    excluded_res_hkls = {
        hkl for hkl, r in res_by_hkl.items() if r.get("overall_added") is False
    }
    observed_comp_hkls = {
        hkl
        for hkl, c in comp_by_hkl.items()
        if c.get("observed_code") == 1
        and c.get("row_outcome") == "observed_shell_and_overall"
    }
    missing_comp_hkls = {
        hkl
        for hkl, c in comp_by_hkl.items()
        if c.get("observed_code") == 0
        and c.get("row_outcome") == "missing_shell_and_overall"
    }

    if (
        len(active_res_hkls) != 7217
        or len(excluded_res_hkls) != 31
        or active_res_hkls != observed_comp_hkls
        or len(missing_comp_hkls) != 45
        or missing_comp_hkls != (excluded_res_hkls | extra_asu_hkls)
        or (observed_comp_hkls | missing_comp_hkls) != comp_hkls
    ):
        raise ValueError(
            f"Cross-namespace partition mismatch: active_res={len(active_res_hkls)}, "
            f"observed_comp={len(observed_comp_hkls)}, excluded_res={len(excluded_res_hkls)}, "
            f"extra_asu={len(extra_asu_hkls)}, missing_comp={len(missing_comp_hkls)}"
        )

    for hkl in sorted(missing_comp_hkls):
        c_row = comp_by_hkl[hkl]
        c_bins = c_row.get("matched_bins")
        if (
            int(c_row["IFREE"]) != 1
            or not isinstance(c_bins, Sequence)
            or len(c_bins) != 1
            or not (1 <= int(c_bins[0]) <= 20)
        ):
            raise ValueError(
                f"Invalid missing completeness row at HKL {hkl}: {c_row!r}"
            )

    return {
        "residual_hkl_count": len(res_hkls),
        "completeness_hkl_count": len(comp_hkls),
        "shared_hkl_count": len(res_hkls),
        "shared_captured_j_identical": True,
        "shared_ifree_identical": True,
        "active_residual_equals_observed_completeness": True,
        "active_observed_hkl_count": len(active_res_hkls),
        "shared_excluded_hkl_count": len(excluded_res_hkls),
        "extra_asu_hkl_count": len(extra_asu_hkls),
        "missing_completeness_hkl_count": len(missing_comp_hkls),
    }


def _verify_loaded_attempt04_bundle(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Run all retained Attempt 04 semantic consistency checks on an in-memory bundle."""
    derived_trace_meta = _derive_trace_record_metadata(bundle["trace_records"])
    if "trace_record_metadata" in bundle:
        _assert_canonical_json_equal(
            bundle["trace_record_metadata"],
            derived_trace_meta,
            label="trace_record_metadata",
        )
    proj_res = _project_retained_products(bundle)
    mtz_res = _check_mtz_word_join(bundle)
    cross_res = _check_shared_hkls(bundle)
    return {
        "schema_id": DIAGNOSTIC_SCHEMA_ID,
        "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "fixture_scope": DIAGNOSTIC_FIXTURE_SCOPE,
        "diagnostic_consistency": True,
        "scientific_admission": False,
        "batch_eligible": False,
        "effective_hkls_proven": False,
        "native_bin_membership_proven": False,
        "verified_pins": dict(bundle["verified_pins"]),
        "envelope": dict(bundle["envelope"]),
        "trace_record_metadata": derived_trace_meta,
        "mode": proj_res["mode"],
        "retained_projections": proj_res["retained_projections"],
        "mtz_word_join": mtz_res,
        "cross_namespace": cross_res,
    }


def verify_retained_attempt04(repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """Verify the 11 pinned retained Attempt 04 artifacts and return a summary dict."""
    bundle = _load_pinned_attempt04_bundle(repo_root)
    return _verify_loaded_attempt04_bundle(bundle)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only semantic consistency checker for the 11 pinned retained "
            "Attempt 04 artifacts (#1110, #1111, #1102)."
        )
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root containing data/coscientists/openscientist/.",
    )
    args = parser.parse_args(argv)
    summary = verify_retained_attempt04(args.repo_root)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
