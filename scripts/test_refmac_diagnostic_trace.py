#!/usr/bin/env python3
"""Focused hermetic unit tests for scripts/refmac_diagnostic_trace.py."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import refmac_diagnostic_trace as rdt  # noqa: E402


def _make_header_line(
    *,
    real_kind: int = 4,
    int_kind: int = 4,
    overrides: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
    drop_keys: tuple[str, ...] = (),
) -> str:
    payload: dict[str, Any] = {
        "record_type": "header",
        "schema_id": rdt.TRACE_SCHEMA_ID,
        "decimal_encoding": rdt.TRACE_DECIMAL_ENCODING,
        "default_real_kind": real_kind,
        "default_integer_kind": int_kind,
        "default_real_storage_size": 32,
        "default_integer_storage_size": 32,
        "radix": 2,
        "digits": 24,
        "minexponent": -125,
        "maxexponent": 128,
        "default_real_radix": 2,
        "default_real_digits": 24,
        "default_real_minexponent": -125,
        "default_real_maxexponent": 128,
        "default_integer_radix": 2,
        "default_integer_digits": 31,
    }
    if overrides:
        payload.update(overrides)
    if extra:
        payload.update(extra)
    for k in drop_keys:
        payload.pop(k, None)
    return json.dumps(payload, separators=(",", ":"))


def _make_close_line(
    record_count: Any = 0,
    *,
    overrides: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    payload: dict[str, Any] = {
        "record_type": "writer_close",
        "schema_id": rdt.TRACE_SCHEMA_ID,
        "event": "writer_close",
        "record_count": record_count,
    }
    if overrides:
        payload.update(overrides)
    if extra:
        payload.update(extra)
    return json.dumps(payload, separators=(",", ":"))


def _writer_exact_real_obj(bits_u32: int) -> dict[str, str]:
    """Independently compute the exact trace_writer.f90 {bits_hex, decimal} representation."""
    bits_hex = f"{bits_u32 & 0xFFFFFFFF:08X}"
    sign_bit = (bits_u32 >> 31) & 1
    exp_bits = (bits_u32 >> 23) & 0xFF
    frac_bits = bits_u32 & 0x7FFFFF

    if exp_bits == 255:
        if frac_bits != 0:
            dec = "NaN"
        else:
            dec = "-Inf" if sign_bit else "Inf"
        return {"bits_hex": bits_hex, "decimal": dec}

    if exp_bits == 0 and frac_bits == 0:
        return {"bits_hex": bits_hex, "decimal": "-0.0" if sign_bit else "0.0"}

    if exp_bits == 0:
        mantissa = frac_bits
        bin_exp = -149
    else:
        mantissa = (1 << 23) + frac_bits
        bin_exp = exp_bits - 150

    sign_prefix = "-" if sign_bit else ""
    if bin_exp >= 0:
        coeff = mantissa * (2 ** bin_exp)
        dec = f"{sign_prefix}{coeff}"
    else:
        coeff = mantissa * (5 ** (-bin_exp))
        dec = f"{sign_prefix}{coeff}E{bin_exp}"
    return {"bits_hex": bits_hex, "decimal": dec}


def _write_and_pin(path: Path, raw_bytes: bytes) -> tuple[str, int]:
    path.write_bytes(raw_bytes)
    return hashlib.sha256(raw_bytes).hexdigest(), len(raw_bytes)


class TestRefmacDiagnosticTraceReader(unittest.TestCase):
    def test_valid_zero_event_closed_envelope_and_compiler_specific_kinds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # Intentionally test both unresolved and resolved temporary paths
            tmp_dir = Path(tmp)
            trace_path = tmp_dir / "zero_event.jsonl"
            content = (_make_header_line(real_kind=101, int_kind=202) + "\n" + _make_close_line(0) + "\n").encode("ascii")
            sha256_pin, size_pin = _write_and_pin(trace_path, content)

            result = rdt.inspect_native_trace_envelope(
                trace_path,
                expected_sha256=sha256_pin,
                expected_size_bytes=size_pin,
            )
            self.assertTrue(result["valid"])
            self.assertTrue(result["closed"])
            self.assertFalse(result["has_events"])
            self.assertEqual(result["event_count"], 0)
            self.assertEqual(result["record_count"], 0)
            self.assertEqual(result["footer_record_count"], 0)
            self.assertTrue(result["envelope_only"])
            self.assertFalse(result["scientific_capture_established"])
            self.assertFalse(result["scientific_eligibility_established"])
            self.assertEqual(result["observed_sha256"], sha256_pin)
            self.assertEqual(result["observed_size_bytes"], size_pin)
            self.assertTrue(result["sha256_match"])
            self.assertTrue(result["size_bytes_match"])
            self.assertIsNone(result["first_failure"])
            self.assertEqual(result["errors"], [])
            self.assertEqual(result["representation_header"]["default_real_kind"], 101)
            self.assertEqual(result["representation_header"]["default_integer_kind"], 202)
            # Result must be strictly JSON-serializable and preserve original file bytes
            json.dumps(result)
            self.assertEqual(trace_path.read_bytes(), content)

    def test_valid_typed_records_binary32_classes_and_tab_identifiers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            trace_path = tmp_path / "typed_trace.jsonl"

            # All 5 binary32 classes: +0.0, -0.0, subnormals, normals (bin_exp < 0, == 0, > 0), +-Inf, NaNs
            pos_zero = _writer_exact_real_obj(0x00000000)
            neg_zero = _writer_exact_real_obj(0x80000000)
            min_subnormal = _writer_exact_real_obj(0x00000001)
            max_neg_subnormal = _writer_exact_real_obj(0x807FFFFF)
            normal_0p2 = _writer_exact_real_obj(0x3E4CCCCD)
            normal_exact_int = _writer_exact_real_obj(0x4B7FFFFF)  # 16777215.0 (bin_exp == 0)
            normal_pos_bin_exp = _writer_exact_real_obj(0xCC000000)  # -33554432.0 (bin_exp == 2)
            max_normal = _writer_exact_real_obj(0x7F7FFFFF)
            pos_inf = _writer_exact_real_obj(0x7F800000)
            neg_inf = _writer_exact_real_obj(0xFF800000)
            qnan_pos = _writer_exact_real_obj(0x7FC00000)
            snan_neg = _writer_exact_real_obj(0xFF800001)

            # Verify direct decoder rational values and NaN payload retention
            self.assertEqual(rdt.decode_trace_real_object(pos_zero).exact_fraction, Fraction(0, 1))
            self.assertFalse(rdt.decode_trace_real_object(pos_zero).is_negative)
            self.assertTrue(rdt.decode_trace_real_object(neg_zero).is_negative)
            self.assertEqual(
                rdt.decode_trace_real_object(min_subnormal).exact_fraction,
                Fraction(1, 1 << 149),
            )
            self.assertEqual(
                rdt.decode_trace_real_object(max_neg_subnormal).exact_fraction,
                -Fraction(0x7FFFFF, 1 << 149),
            )
            self.assertEqual(
                rdt.decode_trace_real_object(normal_0p2).exact_fraction,
                Fraction(13421773, 1 << 26),
            )
            self.assertEqual(
                rdt.decode_trace_real_object(normal_exact_int).exact_fraction,
                Fraction(16777215, 1),
            )
            self.assertEqual(
                rdt.decode_trace_real_object(normal_pos_bin_exp).exact_fraction,
                Fraction(-33554432, 1),
            )
            self.assertEqual(
                rdt.decode_trace_real_object(max_normal).exact_fraction,
                Fraction(0xFFFFFF << 104, 1),
            )
            decoded_snan = rdt.decode_trace_real_object(snan_neg)
            self.assertEqual(decoded_snan.classification, "nan")
            self.assertEqual(decoded_snan.sign_bit, 1)
            self.assertEqual(decoded_snan.frac_bits, 1)

            rec1 = {
                "sequence": 1,
                "event": "lsq_coef_entry",
                "int_min": rdt.INT32_MIN,
                "int_max": rdt.INT32_MAX,
                "flag_true": True,
                "flag_false": False,
                "empty_str": "",
                "spaces_str": "   leading and trailing   ",
                "ctrl_str": "\x00\x08\t\n\x0c\r\"\\~",
                "max_str": "A" * rdt.MAX_STRING_CHARS,
                "r_pos_zero": pos_zero,
                "r_neg_zero": neg_zero,
                "r_min_sub": min_subnormal,
                "r_max_neg_sub": max_neg_subnormal,
                "r_0p2": normal_0p2,
                "r_int": normal_exact_int,
                "r_pos_exp": normal_pos_bin_exp,
                "r_max_norm": max_normal,
                "r_pos_inf": pos_inf,
                "r_neg_inf": neg_inf,
                "r_qnan": qnan_pos,
                "r_snan": snan_neg,
            }
            # Fortran non-blank allows tab-only event and field names
            rec2 = {
                "sequence": 2,
                "event": "\t",
                "\t": 42,
            }

            raw_bytes = (
                _make_header_line()
                + "\n"
                + json.dumps(rec1, separators=(",", ":"))
                + "\n"
                + json.dumps(rec2, separators=(",", ":"))
                + "\n"
                + _make_close_line(2)
                + "\n"
            ).encode("ascii")
            sha256_pin, size_pin = _write_and_pin(trace_path, raw_bytes)

            result = rdt.inspect_native_trace_envelope(
                trace_path,
                expected_sha256=sha256_pin,
                expected_size_bytes=size_pin,
            )
            self.assertTrue(result["valid"])
            self.assertTrue(result["closed"])
            self.assertTrue(result["has_events"])
            self.assertEqual(result["event_count"], 2)
            self.assertEqual(result["footer_record_count"], 2)
            self.assertEqual(result["errors"], [])
            self.assertEqual(trace_path.read_bytes(), raw_bytes)

    def test_binary32_one_bit_one_digit_sign_and_float_rounding_mismatches(self) -> None:
        valid_0p2 = _writer_exact_real_obj(0x3E4CCCCD)
        invalid_real_cases = [
            # 1-bit flip in bits_hex against 0.2 decimal
            {"bits_hex": "3E4CCCCE", "decimal": valid_0p2["decimal"]},
            # 1-unit change in last decimal digit
            {"bits_hex": "3E4CCCCD", "decimal": "20000000298023223876953126E-26"},
            # Rounded float "0.2" (Fraction 1/5 != 13421773/2^26)
            {"bits_hex": "3E4CCCCD", "decimal": "0.2"},
            # Signed zero mismatches and non-writer "0"
            {"bits_hex": "00000000", "decimal": "-0.0"},
            {"bits_hex": "80000000", "decimal": "0.0"},
            {"bits_hex": "00000000", "decimal": "0"},
            {"bits_hex": "80000000", "decimal": "-0"},
            # Finite sign mismatch
            {"bits_hex": "3F800000", "decimal": "-100000000000000000000000E-23"},
            {"bits_hex": "BF800000", "decimal": "100000000000000000000000E-23"},
            # Infinity sign and class mismatches
            {"bits_hex": "7F800000", "decimal": "-Inf"},
            {"bits_hex": "FF800000", "decimal": "Inf"},
            {"bits_hex": "7F800000", "decimal": "NaN"},
            {"bits_hex": "7FC00000", "decimal": "Inf"},
            {"bits_hex": "7FC00000", "decimal": "0.0"},
            {"bits_hex": "3F800000", "decimal": "NaN"},
            {"bits_hex": "3F800000", "decimal": "Inf"},
            # Lowercase hex or wrong hex length
            {"bits_hex": "3e4ccccd", "decimal": valid_0p2["decimal"]},
            {"bits_hex": "3E4CCCC", "decimal": valid_0p2["decimal"]},
            # Out-of-bounds exponents (rejected before big integer exponentiation)
            {"bits_hex": "3F800000", "decimal": "1E99999999"},
            {"bits_hex": "3F800000", "decimal": "1E-99999999"},
            {"bits_hex": "00000001", "decimal": "1E-150"},
            # Overlong decimal string (> 200 chars) and overlong significand (> 160 digits)
            {"bits_hex": "3F800000", "decimal": "1" * 201},
            {"bits_hex": "3F800000", "decimal": ("1" * 161) + "E-23"},
        ]

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            for idx, bad_real in enumerate(invalid_real_cases):
                with self.subTest(case_index=idx, bad_real=bad_real):
                    trace_path = tmp_path / f"bad_real_{idx}.jsonl"
                    rec = {"sequence": 1, "event": "e", "val": bad_real}
                    raw = (
                        _make_header_line()
                        + "\n"
                        + json.dumps(rec, separators=(",", ":"))
                        + "\n"
                        + _make_close_line(1)
                        + "\n"
                    ).encode("ascii")
                    sha256_pin, size_pin = _write_and_pin(trace_path, raw)
                    res = rdt.inspect_native_trace_envelope(
                        trace_path,
                        expected_sha256=sha256_pin,
                        expected_size_bytes=size_pin,
                    )
                    self.assertFalse(res["valid"])
                    self.assertFalse(res["closed"])
                    self.assertEqual(res["first_failure"]["code"], "invalid_real_object")
                    self.assertEqual(res["first_failure"]["line_number"], 2)
                    self.assertEqual(res["first_failure"]["field"], "val")
                    self.assertEqual(res["observed_sha256"], sha256_pin)
                    self.assertEqual(res["observed_size_bytes"], size_pin)
                    self.assertEqual(trace_path.read_bytes(), raw)

    def test_duplicate_keys_floats_nonstandard_numbers_and_malformed_types(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()

            bad_lines: list[tuple[str, str]] = [
                # Duplicate top-level key
                ('{"sequence":1,"event":"e","x":1,"x":2}', "duplicate_json_key"),
                # Duplicate nested key inside real object
                (
                    '{"sequence":1,"event":"e","x":{"bits_hex":"00000000","bits_hex":"00000000","decimal":"0.0"}}',
                    "duplicate_json_key",
                ),
                # Raw float token
                ('{"sequence":1,"event":"e","x":0.25}', "forbidden_json_number_token"),
                ('{"sequence":1,"event":"e","x":1e5}', "forbidden_json_number_token"),
                # Nonstandard JSON constants
                ('{"sequence":1,"event":"e","x":NaN}', "forbidden_json_number_token"),
                ('{"sequence":1,"event":"e","x":Infinity}', "forbidden_json_number_token"),
                ('{"sequence":1,"event":"e","x":-Infinity}', "forbidden_json_number_token"),
                # Boolean as sequence
                ('{"sequence":true,"event":"e"}', "invalid_sequence_type"),
                # Integer out of int32 range
                ('{"sequence":1,"event":"e","x":2147483648}', "integer_out_of_int32_range"),
                ('{"sequence":1,"event":"e","x":-2147483649}', "integer_out_of_int32_range"),
                # Array, null, arbitrary nested object
                ('{"sequence":1,"event":"e","x":[1,2]}', "unsupported_field_value_type"),
                ('{"sequence":1,"event":"e","x":null}', "unsupported_field_value_type"),
                ('{"sequence":1,"event":"e","x":{"a":1}}', "invalid_real_object"),
                # Reserved field names (exact and space-padded)
                ('{"sequence":1,"event":"e","record_count":1}', "reserved_field_name"),
                ('{"sequence":1,"event":"e"," schema_id ":"x"}', "reserved_field_name"),
                # Blank (space-only) event or field name
                ('{"sequence":1,"event":"   "}', "invalid_event_name"),
                ('{"sequence":1,"event":"e","   ":1}', "invalid_field_name"),
                # Escaped DEL (\u007f) and non-ASCII (\u00e9) in string or identifier
                ('{"sequence":1,"event":"e","s":"\\u007f"}', "non_ascii_or_del_string"),
                ('{"sequence":1,"event":"e","s":"\\u00e9"}', "non_ascii_or_del_string"),
                ('{"sequence":1,"event":"\\u007f"}', "invalid_event_name"),
                ('{"sequence":1,"event":"e","\\u00e9":1}', "invalid_field_name"),
            ]

            for idx, (data_line, expected_code) in enumerate(bad_lines):
                with self.subTest(case_index=idx, expected_code=expected_code):
                    trace_path = tmp_path / f"bad_line_{idx}.jsonl"
                    raw = (
                        _make_header_line()
                        + "\n"
                        + data_line
                        + "\n"
                        + _make_close_line(1)
                        + "\n"
                    ).encode("ascii")
                    sha256_pin, size_pin = _write_and_pin(trace_path, raw)
                    res = rdt.inspect_native_trace_envelope(
                        trace_path,
                        expected_sha256=sha256_pin,
                        expected_size_bytes=size_pin,
                    )
                    self.assertFalse(res["valid"])
                    self.assertEqual(res["first_failure"]["code"], expected_code)
                    self.assertEqual(res["first_failure"]["line_number"], 2)
                    self.assertEqual(res["observed_sha256"], sha256_pin)
                    self.assertEqual(res["observed_size_bytes"], size_pin)
                    self.assertEqual(trace_path.read_bytes(), raw)

    def test_bad_header_metadata_and_conflicting_duplicate_model_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()

            header_cases: list[tuple[str, str]] = [
                (
                    _make_header_line(overrides={"record_type": "event"}),
                    "missing_header_record",
                ),
                (
                    _make_header_line(extra={"extra_field": 1}),
                    "invalid_header_fields",
                ),
                (
                    _make_header_line(drop_keys=("default_integer_digits",)),
                    "invalid_header_fields",
                ),
                (
                    _make_header_line(overrides={"schema_id": "wrong_schema"}),
                    "invalid_schema_id",
                ),
                (
                    _make_header_line(overrides={"decimal_encoding": "float64"}),
                    "invalid_decimal_encoding",
                ),
                (
                    _make_header_line(real_kind=0),
                    "invalid_header_kind",
                ),
                (
                    _make_header_line(int_kind=-1),
                    "invalid_header_kind",
                ),
                (
                    _make_header_line(overrides={"default_real_kind": True}),
                    "invalid_header_kind",
                ),
                (
                    _make_header_line(overrides={"default_real_storage_size": False}),
                    "invalid_header_model_type",
                ),
                (
                    _make_header_line(overrides={"default_real_radix": 10}),
                    "conflicting_header_model_metadata",
                ),
                (
                    _make_header_line(overrides={"default_real_digits": 53}),
                    "conflicting_header_model_metadata",
                ),
                (
                    _make_header_line(overrides={"default_real_minexponent": -1021}),
                    "conflicting_header_model_metadata",
                ),
                (
                    _make_header_line(overrides={"default_real_maxexponent": 1024}),
                    "conflicting_header_model_metadata",
                ),
                (
                    _make_header_line(overrides={"default_real_storage_size": 64}),
                    "invalid_header_model_value",
                ),
                (
                    _make_header_line(overrides={"default_integer_digits": 63}),
                    "invalid_header_model_value",
                ),
            ]

            for idx, (hdr_line, expected_code) in enumerate(header_cases):
                with self.subTest(case_index=idx, expected_code=expected_code):
                    trace_path = tmp_path / f"bad_hdr_{idx}.jsonl"
                    raw = (hdr_line + "\n" + _make_close_line(0) + "\n").encode("ascii")
                    sha256_pin, size_pin = _write_and_pin(trace_path, raw)
                    res = rdt.inspect_native_trace_envelope(
                        trace_path,
                        expected_sha256=sha256_pin,
                        expected_size_bytes=size_pin,
                    )
                    self.assertFalse(res["valid"])
                    self.assertEqual(res["first_failure"]["code"], expected_code)
                    self.assertEqual(res["first_failure"]["line_number"], 1)
                    self.assertEqual(res["observed_sha256"], sha256_pin)

            # Duplicate header on line 2
            dup_hdr_path = tmp_path / "dup_hdr.jsonl"
            dup_raw = (
                _make_header_line()
                + "\n"
                + _make_header_line()
                + "\n"
                + _make_close_line(0)
                + "\n"
            ).encode("ascii")
            sha_pin, sz_pin = _write_and_pin(dup_hdr_path, dup_raw)
            dup_res = rdt.inspect_native_trace_envelope(
                dup_hdr_path, expected_sha256=sha_pin, expected_size_bytes=sz_pin
            )
            self.assertFalse(dup_res["valid"])
            self.assertEqual(dup_res["first_failure"]["code"], "duplicate_header_record")
            self.assertEqual(dup_res["first_failure"]["line_number"], 2)

    def test_bad_sequence_footer_and_trailing_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()

            # Sequence gap (1 then 3)
            gap_path = tmp_path / "seq_gap.jsonl"
            gap_raw = (
                _make_header_line()
                + '\n{"sequence":1,"event":"a"}\n{"sequence":3,"event":"b"}\n'
                + _make_close_line(2)
                + "\n"
            ).encode("ascii")
            sha_pin, sz_pin = _write_and_pin(gap_path, gap_raw)
            gap_res = rdt.inspect_native_trace_envelope(
                gap_path, expected_sha256=sha_pin, expected_size_bytes=sz_pin
            )
            self.assertFalse(gap_res["valid"])
            self.assertEqual(gap_res["first_failure"]["code"], "sequence_mismatch")
            self.assertEqual(gap_res["first_failure"]["line_number"], 3)

            # writer_close with sequence field
            close_seq_path = tmp_path / "close_seq.jsonl"
            close_seq_raw = (
                _make_header_line()
                + "\n"
                + _make_close_line(0, extra={"sequence": 1})
                + "\n"
            ).encode("ascii")
            sha_pin, sz_pin = _write_and_pin(close_seq_path, close_seq_raw)
            close_seq_res = rdt.inspect_native_trace_envelope(
                close_seq_path, expected_sha256=sha_pin, expected_size_bytes=sz_pin
            )
            self.assertFalse(close_seq_res["valid"])
            self.assertEqual(
                close_seq_res["first_failure"]["code"], "writer_close_has_sequence"
            )

            # writer_close with bool record_count
            close_bool_path = tmp_path / "close_bool.jsonl"
            close_bool_raw = (
                _make_header_line() + "\n" + _make_close_line(False) + "\n"
            ).encode("ascii")
            sha_pin, sz_pin = _write_and_pin(close_bool_path, close_bool_raw)
            close_bool_res = rdt.inspect_native_trace_envelope(
                close_bool_path, expected_sha256=sha_pin, expected_size_bytes=sz_pin
            )
            self.assertFalse(close_bool_res["valid"])
            self.assertEqual(
                close_bool_res["first_failure"]["code"],
                "invalid_writer_close_record_count_type",
            )

            # writer_close record_count mismatch
            close_cnt_path = tmp_path / "close_cnt.jsonl"
            close_cnt_raw = (
                _make_header_line()
                + '\n{"sequence":1,"event":"a"}\n'
                + _make_close_line(5)
                + "\n"
            ).encode("ascii")
            sha_pin, sz_pin = _write_and_pin(close_cnt_path, close_cnt_raw)
            close_cnt_res = rdt.inspect_native_trace_envelope(
                close_cnt_path, expected_sha256=sha_pin, expected_size_bytes=sz_pin
            )
            self.assertFalse(close_cnt_res["valid"])
            self.assertEqual(
                close_cnt_res["first_failure"]["code"],
                "writer_close_record_count_mismatch",
            )

            # Trailing record after writer_close
            trailing_path = tmp_path / "trailing.jsonl"
            trailing_raw = (
                _make_header_line()
                + "\n"
                + _make_close_line(0)
                + '\n{"sequence":1,"event":"after_close"}\n'
            ).encode("ascii")
            sha_pin, sz_pin = _write_and_pin(trailing_path, trailing_raw)
            trailing_res = rdt.inspect_native_trace_envelope(
                trailing_path, expected_sha256=sha_pin, expected_size_bytes=sz_pin
            )
            self.assertFalse(trailing_res["valid"])
            self.assertFalse(trailing_res["closed"])
            self.assertEqual(
                trailing_res["first_failure"]["code"], "trailing_record_after_close"
            )
            self.assertEqual(trailing_res["first_failure"]["line_number"], 3)

    def test_overlong_line_field_count_name_string_and_number_token_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()

            # 1. Overlong line (> 65536 bytes before newline) still hashes through EOF
            overlong_line_path = tmp_path / "overlong_line.jsonl"
            big_line = b'{"sequence":1,"event":"e","pad":"' + (b"X" * 66000) + b'"}\n'
            overlong_raw = (
                (_make_header_line() + "\n").encode("ascii")
                + big_line
                + (_make_close_line(1) + "\n").encode("ascii")
            )
            sha_pin, sz_pin = _write_and_pin(overlong_line_path, overlong_raw)
            overlong_res = rdt.inspect_native_trace_envelope(
                overlong_line_path, expected_sha256=sha_pin, expected_size_bytes=sz_pin
            )
            self.assertFalse(overlong_res["valid"])
            self.assertEqual(overlong_res["first_failure"]["code"], "record_too_long")
            self.assertEqual(overlong_res["first_failure"]["line_number"], 2)
            self.assertEqual(overlong_res["observed_sha256"], sha_pin)
            self.assertEqual(overlong_res["observed_size_bytes"], sz_pin)

            # 2. Too many user fields (257 > 256)
            many_fields_path = tmp_path / "many_fields.jsonl"
            rec_257: dict[str, Any] = {"sequence": 1, "event": "e"}
            for i in range(257):
                rec_257[f"f_{i}"] = i
            many_raw = (
                _make_header_line()
                + "\n"
                + json.dumps(rec_257, separators=(",", ":"))
                + "\n"
                + _make_close_line(1)
                + "\n"
            ).encode("ascii")
            sha_pin, sz_pin = _write_and_pin(many_fields_path, many_raw)
            many_res = rdt.inspect_native_trace_envelope(
                many_fields_path, expected_sha256=sha_pin, expected_size_bytes=sz_pin
            )
            self.assertFalse(many_res["valid"])
            self.assertEqual(many_res["first_failure"]["code"], "too_many_fields")

            # 3. Overlong event name (257 chars) and overlong field name (257 chars)
            long_event_path = tmp_path / "long_event.jsonl"
            long_event_raw = (
                _make_header_line()
                + "\n"
                + json.dumps({"sequence": 1, "event": "e" * 257}, separators=(",", ":"))
                + "\n"
                + _make_close_line(1)
                + "\n"
            ).encode("ascii")
            sha_pin, sz_pin = _write_and_pin(long_event_path, long_event_raw)
            self.assertEqual(
                rdt.inspect_native_trace_envelope(
                    long_event_path, expected_sha256=sha_pin, expected_size_bytes=sz_pin
                )["first_failure"]["code"],
                "invalid_event_name",
            )

            long_field_path = tmp_path / "long_field.jsonl"
            long_field_raw = (
                _make_header_line()
                + "\n"
                + json.dumps(
                    {"sequence": 1, "event": "e", "k" * 257: 1}, separators=(",", ":")
                )
                + "\n"
                + _make_close_line(1)
                + "\n"
            ).encode("ascii")
            sha_pin, sz_pin = _write_and_pin(long_field_path, long_field_raw)
            self.assertEqual(
                rdt.inspect_native_trace_envelope(
                    long_field_path, expected_sha256=sha_pin, expected_size_bytes=sz_pin
                )["first_failure"]["code"],
                "invalid_field_name",
            )

            # 4. Overlong string value (4097 chars > 4096)
            long_str_path = tmp_path / "long_str.jsonl"
            long_str_raw = (
                _make_header_line()
                + "\n"
                + json.dumps(
                    {"sequence": 1, "event": "e", "s": "a" * 4097},
                    separators=(",", ":"),
                )
                + "\n"
                + _make_close_line(1)
                + "\n"
            ).encode("ascii")
            sha_pin, sz_pin = _write_and_pin(long_str_path, long_str_raw)
            self.assertEqual(
                rdt.inspect_native_trace_envelope(
                    long_str_path, expected_sha256=sha_pin, expected_size_bytes=sz_pin
                )["first_failure"]["code"],
                "string_too_long",
            )

            # 5. Overlong integer token (> 32 chars)
            long_num_path = tmp_path / "long_num.jsonl"
            long_num_raw = (
                _make_header_line()
                + '\n{"sequence":1,"event":"e","n":'
                + ("9" * 33)
                + "}\n"
                + _make_close_line(1)
                + "\n"
            ).encode("ascii")
            sha_pin, sz_pin = _write_and_pin(long_num_path, long_num_raw)
            self.assertEqual(
                rdt.inspect_native_trace_envelope(
                    long_num_path, expected_sha256=sha_pin, expected_size_bytes=sz_pin
                )["first_failure"]["code"],
                "overlong_number_token",
            )

    def test_truncation_missing_newline_wrong_pins_and_symlink_regular_file_boundary(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()

            # 1. Empty file
            empty_path = tmp_path / "empty.jsonl"
            sha_pin, sz_pin = _write_and_pin(empty_path, b"")
            empty_res = rdt.inspect_native_trace_envelope(
                empty_path, expected_sha256=sha_pin, expected_size_bytes=sz_pin
            )
            self.assertFalse(empty_res["valid"])
            self.assertEqual(empty_res["first_failure"]["code"], "empty_trace_file")

            # 2. Missing final newline (truncated output)
            no_nl_path = tmp_path / "no_nl.jsonl"
            no_nl_raw = (_make_header_line() + "\n" + _make_close_line(0)).encode("ascii")
            sha_pin, sz_pin = _write_and_pin(no_nl_path, no_nl_raw)
            no_nl_res = rdt.inspect_native_trace_envelope(
                no_nl_path, expected_sha256=sha_pin, expected_size_bytes=sz_pin
            )
            self.assertFalse(no_nl_res["valid"])
            self.assertFalse(no_nl_res["closed"])
            self.assertEqual(
                no_nl_res["first_failure"]["code"], "missing_final_newline"
            )
            self.assertEqual(no_nl_res["observed_sha256"], sha_pin)
            self.assertEqual(no_nl_res["observed_size_bytes"], sz_pin)

            # 3. Missing writer_close record
            unclosed_path = tmp_path / "unclosed.jsonl"
            unclosed_raw = (
                _make_header_line() + '\n{"sequence":1,"event":"e"}\n'
            ).encode("ascii")
            sha_pin, sz_pin = _write_and_pin(unclosed_path, unclosed_raw)
            unclosed_res = rdt.inspect_native_trace_envelope(
                unclosed_path, expected_sha256=sha_pin, expected_size_bytes=sz_pin
            )
            self.assertFalse(unclosed_res["valid"])
            self.assertFalse(unclosed_res["closed"])
            self.assertEqual(
                unclosed_res["first_failure"]["code"], "missing_writer_close"
            )

            # 4. Wrong raw hash or size on otherwise valid closed envelope
            valid_path = tmp_path / "valid.jsonl"
            valid_raw = (_make_header_line() + "\n" + _make_close_line(0) + "\n").encode(
                "ascii"
            )
            sha_pin, sz_pin = _write_and_pin(valid_path, valid_raw)

            wrong_hash_res = rdt.inspect_native_trace_envelope(
                valid_path, expected_sha256="0" * 64, expected_size_bytes=sz_pin
            )
            self.assertFalse(wrong_hash_res["valid"])
            self.assertTrue(wrong_hash_res["closed"])
            self.assertFalse(wrong_hash_res["sha256_match"])
            self.assertTrue(wrong_hash_res["size_bytes_match"])
            self.assertEqual(wrong_hash_res["observed_sha256"], sha_pin)
            self.assertEqual(
                wrong_hash_res["first_failure"]["code"], "sha256_mismatch"
            )

            wrong_size_res = rdt.inspect_native_trace_envelope(
                valid_path, expected_sha256=sha_pin, expected_size_bytes=sz_pin + 10
            )
            self.assertFalse(wrong_size_res["valid"])
            self.assertTrue(wrong_size_res["closed"])
            self.assertTrue(wrong_size_res["sha256_match"])
            self.assertFalse(wrong_size_res["size_bytes_match"])
            self.assertEqual(wrong_size_res["observed_size_bytes"], sz_pin)
            self.assertEqual(
                wrong_size_res["first_failure"]["code"], "size_bytes_mismatch"
            )

            # 5. Malformed expected pins/types (including bool integer) still report raw identity
            for bad_sha, bad_sz in (
                ("NOT_HEX", sz_pin),
                ("A" * 64, sz_pin),
                (12345, sz_pin),
                (sha_pin, True),
                (sha_pin, -1),
                (sha_pin, "100"),
            ):
                bad_pin_res = rdt.inspect_native_trace_envelope(
                    valid_path,
                    expected_sha256=bad_sha,  # type: ignore[arg-type]
                    expected_size_bytes=bad_sz,  # type: ignore[arg-type]
                )
                self.assertFalse(bad_pin_res["valid"])
                self.assertEqual(
                    bad_pin_res["first_failure"]["code"], "malformed_expected_pin"
                )
                self.assertEqual(bad_pin_res["observed_sha256"], sha_pin)
                self.assertEqual(bad_pin_res["observed_size_bytes"], sz_pin)
                json.dumps(bad_pin_res)

            # 6. Symlink file, symlink directory, directory, and missing file
            sym_file = tmp_path / "sym_trace.jsonl"
            sym_file.symlink_to(valid_path)
            sym_res = rdt.inspect_native_trace_envelope(
                sym_file, expected_sha256=sha_pin, expected_size_bytes=sz_pin
            )
            self.assertFalse(sym_res["valid"])
            self.assertEqual(sym_res["first_failure"]["code"], "symlink_rejected")

            real_sub = tmp_path / "real_sub"
            real_sub.mkdir()
            sub_trace = real_sub / "trace.jsonl"
            _write_and_pin(sub_trace, valid_raw)
            sym_dir = tmp_path / "sym_dir"
            sym_dir.symlink_to(real_sub)
            sym_dir_res = rdt.inspect_native_trace_envelope(
                sym_dir / "trace.jsonl",
                expected_sha256=sha_pin,
                expected_size_bytes=sz_pin,
            )
            self.assertFalse(sym_dir_res["valid"])
            self.assertEqual(sym_dir_res["first_failure"]["code"], "symlink_rejected")

            dir_res = rdt.inspect_native_trace_envelope(
                real_sub, expected_sha256=sha_pin, expected_size_bytes=sz_pin
            )
            self.assertFalse(dir_res["valid"])
            self.assertEqual(dir_res["first_failure"]["code"], "not_regular_file")

            missing_res = rdt.inspect_native_trace_envelope(
                tmp_path / "does_not_exist.jsonl",
                expected_sha256=sha_pin,
                expected_size_bytes=sz_pin,
            )
            self.assertFalse(missing_res["valid"])
            self.assertEqual(
                missing_res["first_failure"]["code"], "trace_file_not_found"
            )

            # 7. Multi-chunk (> 150 KiB) trace with early failure on line 2 still hashes to EOF
            multi_chunk_path = tmp_path / "multi_chunk_early_fail.jsonl"
            valid_tail_line = (
                json.dumps(
                    {"sequence": 3, "event": "pad", "s": "Z" * 1024},
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("ascii")
            multi_raw = (
                (_make_header_line() + "\n").encode("ascii")
                + b'{"sequence":1,"event":"bad","flt":1.23}\n'
                + (valid_tail_line * 160)
                + (_make_close_line(161) + "\n").encode("ascii")
            )
            self.assertGreater(len(multi_raw), 2 * rdt.READ_CHUNK_BYTES)
            mc_sha, mc_sz = _write_and_pin(multi_chunk_path, multi_raw)
            mc_res = rdt.inspect_native_trace_envelope(
                multi_chunk_path, expected_sha256=mc_sha, expected_size_bytes=mc_sz
            )
            self.assertFalse(mc_res["valid"])
            self.assertEqual(
                mc_res["first_failure"]["code"], "forbidden_json_number_token"
            )
            self.assertEqual(mc_res["first_failure"]["line_number"], 2)
            self.assertEqual(mc_res["observed_sha256"], mc_sha)
            self.assertEqual(mc_res["observed_size_bytes"], mc_sz)
            self.assertTrue(mc_res["sha256_match"])
            self.assertTrue(mc_res["size_bytes_match"])
            self.assertEqual(multi_chunk_path.read_bytes(), multi_raw)

    def test_deeply_nested_json_recursion_error_caught_and_drained_through_eof(
        self,
    ) -> None:
        """Verify #1137: bounded deeply nested JSON line (<65536 bytes) is rejected without escaping and hashes through EOF."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            deep_path = tmp_path / "deep_recursion.jsonl"

            header_bytes = (_make_header_line() + "\n").encode("ascii")
            # Construct a <65536-byte JSON object line with 2500 nested arrays
            depth = 2500
            deep_line = (
                b'{"sequence":1,"event":"deep","x":'
                + (b"[" * depth)
                + b"0"
                + (b"]" * depth)
                + b"}\n"
            )
            self.assertLess(len(deep_line), rdt.MAX_RECORD_BYTES)

            # Readable suffix beyond one 65536-byte chunk
            suffix_line = (
                json.dumps(
                    {"sequence": 2, "event": "suffix", "pad": "S" * 1024},
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("ascii")
            suffix_bytes = (suffix_line * 80) + (_make_close_line(81) + "\n").encode(
                "ascii"
            )
            self.assertGreater(len(suffix_bytes), rdt.READ_CHUNK_BYTES)

            full_raw = header_bytes + deep_line + suffix_bytes
            sha_pin, sz_pin = _write_and_pin(deep_path, full_raw)

            res = rdt.inspect_native_trace_envelope(
                deep_path,
                expected_sha256=sha_pin,
                expected_size_bytes=sz_pin,
            )
            self.assertFalse(res["valid"])
            self.assertFalse(res["closed"])
            self.assertTrue(res["read_complete"])
            self.assertIsNotNone(res["representation_header"])
            self.assertEqual(res["representation_header"]["record_type"], "header")
            self.assertIsNotNone(res["first_failure"])
            # Under Python 3.12's C-stack scanner, depth-2500 nested lists may either
            # parse and be rejected as unsupported_field_value_type or exceed recursion
            # depth on constrained stacks; neither may escape and both must drain to EOF.
            self.assertIn(
                res["first_failure"]["code"],
                ("unsupported_field_value_type", "json_recursion_depth_exceeded"),
            )
            self.assertEqual(res["first_failure"]["stage"], "envelope_parse")
            self.assertEqual(res["first_failure"]["line_number"], 2)
            self.assertEqual(res["first_failure"]["byte_offset"], len(header_bytes))
            if res["first_failure"]["code"] == "json_recursion_depth_exceeded":
                self.assertEqual(
                    res["first_failure"]["exception_type"], "RecursionError"
                )
            else:
                self.assertEqual(res["first_failure"]["field"], "x")
            self.assertEqual(res["observed_sha256"], sha_pin)
            self.assertEqual(res["observed_size_bytes"], sz_pin)
            self.assertEqual(res["bytes_read"], sz_pin)
            self.assertIsNone(res["partial_sha256"])
            self.assertIsNone(res["partial_size_bytes"])
            self.assertTrue(res["sha256_match"])
            self.assertTrue(res["size_bytes_match"])
            json.dumps(res)
            self.assertEqual(deep_path.read_bytes(), full_raw)

    def test_deterministic_data_record_recursion_error_drains_through_eof(
        self,
    ) -> None:
        """Verify #1137: deterministic decoder RecursionError on a data record after header records located failure and drains to EOF."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            trace_path = tmp_path / "deterministic_recursion.jsonl"

            header_bytes = (_make_header_line() + "\n").encode("ascii")
            rec1_bytes = (
                json.dumps(
                    {"sequence": 1, "event": "ok_before_recursion", "k": 7},
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("ascii")
            rec2_bytes = (
                json.dumps(
                    {"sequence": 2, "event": "trigger_recursion", "k": 8},
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("ascii")
            suffix_line = (
                json.dumps(
                    {"sequence": 3, "event": "suffix", "pad": "R" * 1024},
                    separators=(",", ":"),
                )
                + "\n"
            ).encode("ascii")
            suffix_bytes = (suffix_line * 80) + (_make_close_line(82) + "\n").encode(
                "ascii"
            )
            self.assertGreater(len(suffix_bytes), rdt.READ_CHUNK_BYTES)

            full_raw = header_bytes + rec1_bytes + rec2_bytes + suffix_bytes
            sha_pin, sz_pin = _write_and_pin(trace_path, full_raw)

            real_loads = json.loads

            def loads_failing_on_target_data_record(s: str, **kwargs: Any) -> Any:
                parsed = real_loads(s, **kwargs)
                if (
                    isinstance(parsed, dict)
                    and parsed.get("sequence") == 2
                    and parsed.get("event") == "trigger_recursion"
                ):
                    raise RecursionError(
                        "deterministic recursion limit reached on data record"
                    )
                return parsed

            with mock.patch.object(
                rdt.json, "loads", side_effect=loads_failing_on_target_data_record
            ):
                res = rdt.inspect_native_trace_envelope(
                    trace_path,
                    expected_sha256=sha_pin,
                    expected_size_bytes=sz_pin,
                )

            self.assertFalse(res["valid"])
            self.assertFalse(res["closed"])
            self.assertTrue(res["read_complete"])
            self.assertIsNotNone(res["representation_header"])
            self.assertEqual(res["representation_header"]["record_type"], "header")
            self.assertEqual(res["event_count"], 1)
            self.assertIsNotNone(res["first_failure"])
            self.assertEqual(
                res["first_failure"]["code"], "json_recursion_depth_exceeded"
            )
            self.assertEqual(res["first_failure"]["stage"], "envelope_parse")
            self.assertEqual(res["first_failure"]["line_number"], 3)
            self.assertEqual(
                res["first_failure"]["byte_offset"],
                len(header_bytes) + len(rec1_bytes),
            )
            self.assertEqual(res["first_failure"]["exception_type"], "RecursionError")
            self.assertEqual(res["observed_sha256"], sha_pin)
            self.assertEqual(res["observed_size_bytes"], sz_pin)
            self.assertEqual(res["bytes_read"], sz_pin)
            self.assertIsNone(res["partial_sha256"])
            self.assertIsNone(res["partial_size_bytes"])
            self.assertTrue(res["sha256_match"])
            self.assertTrue(res["size_bytes_match"])
            json.dumps(res)
            self.assertEqual(trace_path.read_bytes(), full_raw)

    def test_oserror_normalization_and_incomplete_read_identity_separation(
        self,
    ) -> None:
        """Verify #1138: NotADirectoryError, PermissionError, fstat/read/close OSErrors, and partial vs complete identity."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            valid_path = tmp_path / "nested.jsonl"
            chunk1 = (_make_header_line() + "\n").encode("ascii")
            chunk2 = (
                json.dumps({"sequence": 1, "event": "e", "k": 1}, separators=(",", ":"))
                + "\n"
                + _make_close_line(1)
                + "\n"
            ).encode("ascii")
            valid_raw = chunk1 + chunk2
            sha_pin, sz_pin = _write_and_pin(valid_path, valid_raw)

            # 1. Deterministic NotADirectoryError: existing regular file + child component
            child_under_file = valid_path / "child"
            not_dir_res = rdt.inspect_native_trace_envelope(
                child_under_file,
                expected_sha256=sha_pin,
                expected_size_bytes=sz_pin,
            )
            self.assertFalse(not_dir_res["valid"])
            self.assertFalse(not_dir_res["closed"])
            self.assertFalse(not_dir_res["read_complete"])
            self.assertIsNone(not_dir_res["observed_sha256"])
            self.assertIsNone(not_dir_res["observed_size_bytes"])
            self.assertFalse(not_dir_res["sha256_match"])
            self.assertFalse(not_dir_res["size_bytes_match"])
            self.assertEqual(not_dir_res["bytes_read"], 0)
            self.assertIsNone(not_dir_res["partial_sha256"])
            self.assertEqual(not_dir_res["partial_size_bytes"], 0)
            self.assertEqual(not_dir_res["expected_sha256"], sha_pin)
            self.assertEqual(not_dir_res["expected_size_bytes"], sz_pin)
            self.assertEqual(not_dir_res["first_failure"]["code"], "not_a_directory")
            self.assertEqual(not_dir_res["first_failure"]["stage"], "path_inspection")
            self.assertEqual(
                not_dir_res["first_failure"]["exception_type"], "NotADirectoryError"
            )
            json.dumps(not_dir_res)

            # Trailing slash on regular file also normalizes to not_a_directory
            trailing_sep_res = rdt.inspect_native_trace_envelope(
                f"{valid_path}/",
                expected_sha256=sha_pin,
                expected_size_bytes=sz_pin,
            )
            self.assertFalse(trailing_sep_res["valid"])
            self.assertEqual(
                trailing_sep_res["first_failure"]["code"], "not_a_directory"
            )

            # 2. Mocked PermissionError during path inspection (lstat) and during open
            with mock.patch.object(
                rdt.os,
                "lstat",
                side_effect=PermissionError(
                    errno.EACCES, "Permission denied", str(valid_path)
                ),
            ):
                perm_lstat_res = rdt.inspect_native_trace_envelope(
                    valid_path,
                    expected_sha256=sha_pin,
                    expected_size_bytes=sz_pin,
                )
            self.assertFalse(perm_lstat_res["valid"])
            self.assertFalse(perm_lstat_res["read_complete"])
            self.assertIsNone(perm_lstat_res["observed_sha256"])
            self.assertIsNone(perm_lstat_res["observed_size_bytes"])
            self.assertEqual(perm_lstat_res["expected_sha256"], sha_pin)
            self.assertEqual(perm_lstat_res["expected_size_bytes"], sz_pin)
            self.assertEqual(
                perm_lstat_res["first_failure"]["code"], "permission_denied"
            )
            self.assertEqual(
                perm_lstat_res["first_failure"]["stage"], "path_inspection"
            )
            self.assertEqual(
                perm_lstat_res["first_failure"]["exception_type"], "PermissionError"
            )

            with mock.patch.object(
                rdt.os,
                "open",
                side_effect=PermissionError(
                    errno.EACCES, "Permission denied on open", str(valid_path)
                ),
            ):
                perm_open_res = rdt.inspect_native_trace_envelope(
                    valid_path,
                    expected_sha256=sha_pin,
                    expected_size_bytes=sz_pin,
                )
            self.assertFalse(perm_open_res["valid"])
            self.assertFalse(perm_open_res["read_complete"])
            self.assertIsNone(perm_open_res["observed_sha256"])
            self.assertIsNone(perm_open_res["observed_size_bytes"])
            self.assertEqual(
                perm_open_res["first_failure"]["code"], "permission_denied"
            )
            self.assertEqual(perm_open_res["first_failure"]["stage"], "open")

            # 3. Mocked pre-read fstat failure closes descriptor and keeps complete identity None
            closed_fds: list[int] = []
            real_close = os.close

            def tracking_close(fd: int) -> None:
                closed_fds.append(fd)
                real_close(fd)

            with (
                mock.patch.object(
                    rdt.os,
                    "fstat",
                    side_effect=OSError(errno.EIO, "fstat pre-read I/O error"),
                ),
                mock.patch.object(rdt.os, "close", side_effect=tracking_close),
            ):
                pre_fstat_res = rdt.inspect_native_trace_envelope(
                    valid_path,
                    expected_sha256=sha_pin,
                    expected_size_bytes=sz_pin,
                )
            self.assertEqual(len(closed_fds), 1)
            self.assertFalse(pre_fstat_res["valid"])
            self.assertFalse(pre_fstat_res["closed"])
            self.assertFalse(pre_fstat_res["read_complete"])
            self.assertIsNone(pre_fstat_res["observed_sha256"])
            self.assertIsNone(pre_fstat_res["observed_size_bytes"])
            self.assertEqual(pre_fstat_res["bytes_read"], 0)
            self.assertIsNone(pre_fstat_res["partial_sha256"])
            self.assertEqual(
                pre_fstat_res["first_failure"]["code"], "pre_read_fstat_failed"
            )
            self.assertEqual(
                pre_fstat_res["first_failure"]["stage"], "pre_read_fstat"
            )

            # 4. Mocked read failure AFTER SOME BYTES: prefix digest must NOT be reported as observed_sha256
            prefix_sha = hashlib.sha256(chunk1).hexdigest()
            prefix_len = len(chunk1)
            closed_fds.clear()
            read_calls = 0

            def failing_after_first_chunk_read(fd: int, n: int) -> bytes:
                nonlocal read_calls
                read_calls += 1
                if read_calls == 1:
                    return chunk1
                raise OSError(errno.EIO, "read failed after first chunk")

            # Even if caller passes expected pins matching the prefix, observed_sha256/sha256_match must stay None/False
            with (
                mock.patch.object(
                    rdt.os, "read", side_effect=failing_after_first_chunk_read
                ),
                mock.patch.object(rdt.os, "close", side_effect=tracking_close),
            ):
                partial_read_res = rdt.inspect_native_trace_envelope(
                    valid_path,
                    expected_sha256=prefix_sha,
                    expected_size_bytes=prefix_len,
                )
            self.assertEqual(len(closed_fds), 1)
            self.assertFalse(partial_read_res["valid"])
            self.assertFalse(partial_read_res["closed"])
            self.assertFalse(partial_read_res["read_complete"])
            self.assertIsNone(partial_read_res["observed_sha256"])
            self.assertIsNone(partial_read_res["observed_size_bytes"])
            self.assertFalse(partial_read_res["sha256_match"])
            self.assertFalse(partial_read_res["size_bytes_match"])
            self.assertEqual(partial_read_res["bytes_read"], prefix_len)
            self.assertEqual(partial_read_res["partial_size_bytes"], prefix_len)
            self.assertEqual(partial_read_res["partial_sha256"], prefix_sha)
            self.assertEqual(partial_read_res["expected_sha256"], prefix_sha)
            self.assertEqual(partial_read_res["expected_size_bytes"], prefix_len)
            self.assertEqual(
                partial_read_res["first_failure"]["code"], "descriptor_read_failed"
            )
            self.assertEqual(partial_read_res["first_failure"]["stage"], "read")
            self.assertEqual(
                partial_read_res["first_failure"]["byte_offset"], prefix_len
            )
            json.dumps(partial_read_res)

            # 5. Mocked post-read fstat failure and close failure return structured invalid results
            real_fstat = os.fstat
            fstat_calls = 0

            def failing_post_fstat(fd: int) -> os.stat_result:
                nonlocal fstat_calls
                fstat_calls += 1
                if fstat_calls == 1:
                    return real_fstat(fd)
                raise OSError(errno.EIO, "fstat post-read I/O error")

            closed_fds.clear()
            with (
                mock.patch.object(rdt.os, "fstat", side_effect=failing_post_fstat),
                mock.patch.object(rdt.os, "close", side_effect=tracking_close),
            ):
                post_fstat_res = rdt.inspect_native_trace_envelope(
                    valid_path,
                    expected_sha256=sha_pin,
                    expected_size_bytes=sz_pin,
                )
            self.assertEqual(len(closed_fds), 1)
            self.assertFalse(post_fstat_res["valid"])
            self.assertFalse(post_fstat_res["closed"])
            self.assertTrue(post_fstat_res["read_complete"])
            self.assertEqual(post_fstat_res["observed_sha256"], sha_pin)
            self.assertEqual(post_fstat_res["observed_size_bytes"], sz_pin)
            self.assertEqual(
                post_fstat_res["first_failure"]["code"], "post_read_fstat_failed"
            )
            self.assertEqual(
                post_fstat_res["first_failure"]["stage"], "post_read_fstat"
            )

            def failing_close(fd: int) -> None:
                real_close(fd)
                raise OSError(errno.EIO, "descriptor close failed")

            with mock.patch.object(rdt.os, "close", side_effect=failing_close):
                close_fail_res = rdt.inspect_native_trace_envelope(
                    valid_path,
                    expected_sha256=sha_pin,
                    expected_size_bytes=sz_pin,
                )
            self.assertFalse(close_fail_res["valid"])
            self.assertFalse(close_fail_res["closed"])
            self.assertEqual(close_fail_res["first_failure"]["code"], "close_failed")
            self.assertEqual(close_fail_res["first_failure"]["stage"], "close")

            self.assertEqual(valid_path.read_bytes(), valid_raw)

    def test_retained_bytes_snapshot_mode_provenance_parity_and_missing_snapshot_contract(
        self,
    ) -> None:
        """Verify #1050 comment 6758720832 and #1213: byte-mode vs pathname-mode parity, poisoned-FS provenance, unavailable snapshot refusal, and nested scope restoration."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            refmac_dir = tmp_path / "refmac"
            refmac_dir.mkdir(parents=True)
            trace_path = refmac_dir / "refmac_native_trace.jsonl"

            rec1 = {
                "sequence": 1,
                "event": "lsq_coef_entry",
                "ncyc": 0,
                "r_val": _writer_exact_real_obj(0x3E4CCCCD),
            }
            valid_raw = (
                _make_header_line()
                + "\n"
                + json.dumps(rec1, separators=(",", ":"))
                + "\n"
                + _make_close_line(1)
                + "\n"
            ).encode("ascii")
            sha_pin, sz_pin = _write_and_pin(trace_path, valid_raw)

            # 1. Legacy pathname-mode baseline
            fs_res = rdt.inspect_native_trace_envelope(
                trace_path,
                expected_sha256=sha_pin,
                expected_size_bytes=sz_pin,
            )
            self.assertTrue(fs_res["valid"])
            self.assertTrue(fs_res["closed"])
            self.assertEqual(
                fs_res["input_mode"], rdt.TRACE_INPUT_MODE_FILESYSTEM_PATH
            )
            self.assertTrue(fs_res["filesystem_descriptor_opened"])
            self.assertTrue(fs_res["filesystem_identity_verified_by_trace_reader"])
            self.assertEqual(
                fs_res["descriptor_binding_note"],
                rdt._FILESYSTEM_VERIFIED_BINDING_NOTE,
            )

            # 2. Poisoned-filesystem supplied-byte mode (direct keyword, inspect_native_trace_bytes, and scope)
            calls = {"open": 0, "read": 0, "lstat": 0, "fstat": 0}

            def poison(name: str):
                def _fn(*args: Any, **kwargs: Any) -> Any:
                    calls[name] += 1
                    raise AssertionError(f"unexpected os.{name}")

                return _fn

            with (
                mock.patch.object(rdt.os, "open", side_effect=poison("open")),
                mock.patch.object(rdt.os, "read", side_effect=poison("read")),
                mock.patch.object(rdt.os, "lstat", side_effect=poison("lstat")),
                mock.patch.object(rdt.os, "fstat", side_effect=poison("fstat")),
            ):
                kw_res = rdt.inspect_native_trace_envelope(
                    trace_path,
                    expected_sha256=sha_pin,
                    expected_size_bytes=sz_pin,
                    raw_bytes=valid_raw,
                )
                bytes_fn_res = rdt.inspect_native_trace_bytes(
                    trace_path,
                    valid_raw,
                    expected_sha256=sha_pin,
                    expected_size_bytes=sz_pin,
                )
                with rdt._preverified_trace_bytes_scope(trace_path, valid_raw):
                    scope_res = rdt.inspect_native_trace_envelope(
                        trace_path,
                        expected_sha256=sha_pin,
                        expected_size_bytes=sz_pin,
                    )

            self.assertEqual(calls, {"open": 0, "read": 0, "lstat": 0, "fstat": 0})
            self.assertEqual(kw_res, bytes_fn_res)
            self.assertEqual(kw_res, scope_res)

            # Parity across all envelope/header/content/hash/size keys
            provenance_keys = {
                "input_mode",
                "filesystem_descriptor_opened",
                "filesystem_identity_verified_by_trace_reader",
                "descriptor_binding_note",
            }
            self.assertEqual(
                {k: v for k, v in kw_res.items() if k not in provenance_keys},
                {k: v for k, v in fs_res.items() if k not in provenance_keys},
            )
            self.assertEqual(
                kw_res["input_mode"],
                rdt.TRACE_INPUT_MODE_RETAINED_BYTES_SNAPSHOT,
            )
            self.assertFalse(kw_res["filesystem_descriptor_opened"])
            self.assertFalse(
                kw_res["filesystem_identity_verified_by_trace_reader"]
            )
            self.assertEqual(
                kw_res["descriptor_binding_note"],
                rdt._RETAINED_SNAPSHOT_PARSED_BINDING_NOTE,
            )
            self.assertNotIn(
                "Opened with O_RDONLY", kw_res["descriptor_binding_note"]
            )
            json.dumps(kw_res)

            # 3. Missing snapshot (None) in retained mode with replacement directory/file on disk
            displaced_dir = tmp_path / "refmac_displaced"
            refmac_dir.rename(displaced_dir)
            refmac_dir.mkdir(parents=True)
            trace_path.write_bytes(valid_raw)

            open_calls = 0
            real_open = os.open

            def count_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
                nonlocal open_calls
                open_calls += 1
                return real_open(path, flags, *args, **kwargs)

            with (
                mock.patch.object(rdt.os, "open", side_effect=count_open),
                mock.patch.object(
                    rdt.os,
                    "lstat",
                    side_effect=AssertionError("unexpected os.lstat in retained mode"),
                ),
            ):
                with rdt._preverified_trace_bytes_scope(trace_path, None):
                    unavail_scope_res = rdt.inspect_native_trace_envelope(
                        trace_path,
                        expected_sha256=sha_pin,
                        expected_size_bytes=sz_pin,
                    )
                unavail_kw_res = rdt.inspect_native_trace_envelope(
                    trace_path,
                    expected_sha256=sha_pin,
                    expected_size_bytes=sz_pin,
                    raw_bytes=None,
                )
                unavail_fn_res = rdt.inspect_native_trace_bytes(
                    trace_path,
                    None,
                    expected_sha256=sha_pin,
                    expected_size_bytes=sz_pin,
                )

            self.assertEqual(open_calls, 0)
            for unavail_res in (
                unavail_scope_res,
                unavail_kw_res,
                unavail_fn_res,
            ):
                self.assertFalse(unavail_res["valid"])
                self.assertFalse(unavail_res["closed"])
                self.assertFalse(unavail_res["read_complete"])
                self.assertIsNone(unavail_res["observed_sha256"])
                self.assertIsNone(unavail_res["observed_size_bytes"])
                self.assertEqual(
                    unavail_res["input_mode"],
                    rdt.TRACE_INPUT_MODE_RETAINED_BYTES_SNAPSHOT,
                )
                self.assertFalse(unavail_res["filesystem_descriptor_opened"])
                self.assertFalse(
                    unavail_res["filesystem_identity_verified_by_trace_reader"]
                )
                self.assertEqual(
                    unavail_res["descriptor_binding_note"],
                    rdt._RETAINED_SNAPSHOT_UNAVAILABLE_BINDING_NOTE,
                )
                self.assertEqual(
                    unavail_res["first_failure"]["code"],
                    "retained_trace_snapshot_unavailable",
                )
                self.assertEqual(
                    unavail_res["first_failure"]["stage"], "snapshot_binding"
                )
                json.dumps(unavail_res)

            # 4. Nested scope: inner unavailable scope fails closed without inheriting outer bytes,
            #    and exiting the inner scope restores the outer valid snapshot scope.
            other_trace_path = refmac_dir / "other_trace.jsonl"
            other_trace_path.write_bytes(valid_raw)
            with (
                mock.patch.object(rdt.os, "open", side_effect=count_open),
                mock.patch.object(
                    rdt.os,
                    "lstat",
                    side_effect=AssertionError("unexpected os.lstat in nested scope"),
                ),
            ):
                with rdt._preverified_trace_bytes_scope(trace_path, valid_raw):
                    outer_before = rdt.inspect_native_trace_envelope(
                        trace_path,
                        expected_sha256=sha_pin,
                        expected_size_bytes=sz_pin,
                    )
                    mismatch_path_res = rdt.inspect_native_trace_envelope(
                        other_trace_path,
                        expected_sha256=sha_pin,
                        expected_size_bytes=sz_pin,
                    )
                    with rdt._preverified_trace_bytes_scope(trace_path, None):
                        inner_unavail = rdt.inspect_native_trace_envelope(
                            trace_path,
                            expected_sha256=sha_pin,
                            expected_size_bytes=sz_pin,
                        )
                    outer_after = rdt.inspect_native_trace_envelope(
                        trace_path,
                        expected_sha256=sha_pin,
                        expected_size_bytes=sz_pin,
                    )

            self.assertEqual(open_calls, 0)
            self.assertIsNone(rdt._PREVERIFIED_TRACE_BYTES_CTX.get())
            self.assertTrue(outer_before["valid"])
            self.assertFalse(mismatch_path_res["valid"])
            self.assertEqual(
                mismatch_path_res["first_failure"]["code"],
                "retained_trace_snapshot_path_mismatch",
            )
            self.assertEqual(
                mismatch_path_res["first_failure"]["stage"], "snapshot_binding"
            )
            self.assertFalse(inner_unavail["valid"])
            self.assertEqual(
                inner_unavail["first_failure"]["code"],
                "retained_trace_snapshot_unavailable",
            )
            self.assertTrue(outer_after["valid"])
            self.assertEqual(outer_after, outer_before)


if __name__ == "__main__":
    unittest.main()
