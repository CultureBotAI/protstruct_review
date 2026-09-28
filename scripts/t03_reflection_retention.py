#!/usr/bin/env python3
"""Input-led T03 retained-byte audit; no refinement, reindexing, or QDS grading.

The narrow little-endian merged-amplitude MTZ reader is reused from the retained
1SAR audit. Unsupported formats/ambiguous identities fail closed. This helper
reports policy diagnostics; it does not reinterpret any issued EVAL/QDS.
Admission requires explicit VALM NAN, complete zero-batch NCOL, and no unmerged
column/header markers; finite missing-value sentinels are not supported.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
from typing import Any

from audit_1sar_retained_evidence import (
    _mtz_headers, mtz_crystallographic_context, mtz_observations,
)


def deposition_applicability(deposited_rfree: Any, refmac_rfree: Any = None) -> dict[str, str]:
    """REFMAC availability cannot supply a missing deposited R-free reference."""
    def available(value: Any) -> bool:
        return (isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value) and value >= 0)
    return {
        "deposited_reference": "available" if available(deposited_rfree) else "unavailable",
        "refmac_reference": "available" if available(refmac_rfree) else "unavailable",
        "deposition_clause": "evaluable" if available(deposited_rfree) else "unevaluable",
    }


def _column_bindings(blob: bytes, labels: tuple[str, str, str]) -> list[dict[str, Any]]:
    if len(labels) != 3 or len(set(labels)) != 3:
        raise ValueError("explicit distinct F, SIGF, and flag labels are required")
    _, headers = _mtz_headers(blob)
    columns = {parts[1]: {"label": parts[1], "type": parts[2], "dataset_id": int(parts[5])}
               for line in headers if line.startswith("COLUMN ") for parts in [line.split()]}
    if [columns.get(label, {}).get("type") for label in labels] != ["F", "Q", "I"]:
        raise ValueError("selected MTZ columns must have F/Q/I types")
    if columns[labels[0]]["dataset_id"] != columns[labels[1]]["dataset_id"]:
        raise ValueError("selected F/SIGF columns have different dataset associations")
    return [columns[label] for label in labels]


def _require_supported_mtz(blob: bytes) -> None:
    """Reject unsupported missing-value and unmerged semantics before selection."""
    _, headers = _mtz_headers(blob)
    records = [line.split() for line in headers if line.split()]
    missing = [parts for parts in records if parts[0].upper() == "VALM"]
    if missing != [["VALM", "NAN"]]:
        raise ValueError("MTZ requires exactly one explicit VALM NAN record")
    dimensions = [parts for parts in records if parts[0].upper() == "NCOL"]
    if len(dimensions) != 1 or len(dimensions[0]) != 4:
        raise ValueError("MTZ requires exactly one complete NCOL ncols nrows nbatches record")
    if dimensions[0][0] != "NCOL" or any(
        not token.isascii() or not token.isdecimal() for token in dimensions[0][1:]
    ):
        raise ValueError("MTZ NCOL dimensions must be nonnegative decimal integers")
    ncols, nrows, nbatches = map(int, dimensions[0][1:])
    if ncols < 3 or nrows <= 0 or nbatches != 0:
        raise ValueError("MTZ NCOL requires positive dimensions and zero batches")
    for parts in records:
        keyword = parts[0].upper()
        if keyword == "BATCH":
            raise ValueError("MTZ unmerged BATCH records are unsupported")
        if keyword == "COLUMN":
            if parts[0] != "COLUMN" or len(parts) != 6:
                raise ValueError("MTZ requires complete COLUMN records")
            if parts[1].upper() in {"M/ISYM", "BATCH"} or parts[2].upper() in {"Y", "B"}:
                raise ValueError("MTZ unmerged column names/types are unsupported")


def _rows(blob: bytes, labels: tuple[str, str, str]) -> dict[tuple[int, ...], tuple[float, ...]]:
    _column_bindings(blob, labels)
    observations = mtz_observations(blob, labels[:2])
    flags = mtz_observations(blob, (labels[0], labels[2]))
    return {
        key: tuple(struct.unpack("<f", value)[0] for value in (*values, flags[key][1]))
        for key, values in observations.items()
    }


def _selection(rows: dict, flag_values: set[int], free_value: int) -> tuple[set, list, dict]:
    eligible, malformed_flags = set(), []
    counts = {
        "raw_rows": len(rows), "eligible_rows": 0,
        "excluded_nonfinite_f": 0, "excluded_nonpositive_or_nonfinite_sigf": 0,
        "observed_rows_with_invalid_flags": 0, "zero_f": 0, "negative_f": 0,
        "free_rows": 0, "work_rows": 0,
    }
    for key, (f, sigf, flag) in rows.items():
        if not math.isfinite(f):
            counts["excluded_nonfinite_f"] += 1
            continue
        if not math.isfinite(sigf) or sigf <= 0:
            counts["excluded_nonpositive_or_nonfinite_sigf"] += 1
            continue
        counts["zero_f"] += f == 0
        counts["negative_f"] += f < 0
        if not math.isfinite(flag) or flag != int(flag) or int(flag) not in flag_values:
            malformed_flags.append(key)
            counts["observed_rows_with_invalid_flags"] += 1
            continue
        eligible.add(key)
        counts["free_rows" if int(flag) == free_value else "work_rows"] += 1
    counts["eligible_rows"] = len(eligible)
    return eligible, sorted(malformed_flags), counts


def audit_mtz_retention(
    input_bytes: bytes,
    output_bytes: bytes,
    *,
    input_labels: tuple[str, str, str],
    output_labels: tuple[str, str, str],
    flag_values: set[int],
    free_value: int,
) -> dict[str, Any]:
    """Report full input-domain retention; invalid input/context raises ValueError.

    Missing/malformed input flags on finite F and positive finite SIGF are NOT
    excluded into a passing remainder. Output corruption, losses, replacements,
    and newly usable keys give 'not_preserved'; padding alone does not.
    Exact F/SIGF numeric equality is required for this unchanged-input audit.
    Different processing/indexing needs a separately declared matched comparison.
    """
    if (not isinstance(flag_values, set) or len(flag_values) < 2
            or any(type(value) is not int for value in flag_values)
            or type(free_value) is not int or free_value not in flag_values):
        raise ValueError("declare integral flag encoding and its free value explicitly")
    _require_supported_mtz(input_bytes)
    _require_supported_mtz(output_bytes)
    before_context = mtz_crystallographic_context(input_bytes)
    after_context = mtz_crystallographic_context(output_bytes)
    if before_context != after_context:
        raise ValueError("unevaluable: crystallographic/indexing context differs; no implicit reindexing")
    before = _rows(input_bytes, input_labels)
    after = _rows(output_bytes, output_labels)
    input_set, bad_input_flags, input_counts = _selection(before, flag_values, free_value)
    output_set, bad_output_flags, output_counts = _selection(after, flag_values, free_value)
    if bad_input_flags:
        raise ValueError(f"unevaluable: usable input observations have invalid flags: {bad_input_flags}")
    if not input_set or not input_counts["free_rows"] or not input_counts["work_rows"]:
        raise ValueError("unevaluable: input requires nonempty observed work and free sets")
    shared = input_set & after.keys()
    missing = sorted(input_set - after.keys())
    invalidated = sorted(shared - output_set)
    new_usable = sorted(output_set - input_set)
    flag_changes = sorted(key for key in shared if before[key][2] != after[key][2])
    observation_changes = sorted(
        key for key in input_set & output_set if before[key][:2] != after[key][:2]
    )
    extras = after.keys() - before.keys()
    defects = [missing, invalidated, new_usable, flag_changes, observation_changes, bad_output_flags]
    return {
        "audit_status": "not_preserved" if any(defects) else "preserved",
        "scope": "retained selected input observations; not a new refinement or a QDS verdict",
        "input_sha256": hashlib.sha256(input_bytes).hexdigest(),
        "output_sha256": hashlib.sha256(output_bytes).hexdigest(),
        "input_labels": list(input_labels), "output_labels": list(output_labels),
        "input_column_bindings": _column_bindings(input_bytes, input_labels),
        "output_column_bindings": _column_bindings(output_bytes, output_labels),
        "flag_values": sorted(flag_values), "free_value": free_value,
        "input": input_counts, "output": output_counts,
        "missing_input_hkls": missing, "invalidated_input_hkls": invalidated,
        "new_usable_output_hkls": new_usable, "changed_flags": flag_changes,
        "changed_observations": observation_changes, "invalid_output_flags": bad_output_flags,
        "added_raw_rows": len(extras),
        "added_all_nan_rows": sum(all(math.isnan(value) for value in after[key]) for key in extras),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_mtz", type=Path)
    parser.add_argument("output_mtz", type=Path)
    parser.add_argument("--input-columns", required=True, help="explicit F,SIGF,flag labels")
    parser.add_argument("--output-columns", required=True, help="explicit F,SIGF,flag labels")
    parser.add_argument("--flag-values", required=True, help="declared integral encoding, e.g. 0,1")
    parser.add_argument("--free-value", required=True, type=int)
    args = parser.parse_args()
    try:
        result = audit_mtz_retention(
            args.input_mtz.read_bytes(), args.output_mtz.read_bytes(),
            input_labels=tuple(part.strip() for part in args.input_columns.split(",")),
            output_labels=tuple(part.strip() for part in args.output_columns.split(",")),
            flag_values={int(part) for part in args.flag_values.split(",")},
            free_value=args.free_value,
        )
    except (OSError, ValueError, UnicodeError, struct.error) as exc:
        parser.exit(2, f"unevaluable: {exc}\n")
    print(json.dumps(result, sort_keys=True, indent=2, allow_nan=False))
    return 0 if result["audit_status"] == "preserved" else 1


if __name__ == "__main__":
    raise SystemExit(main())
