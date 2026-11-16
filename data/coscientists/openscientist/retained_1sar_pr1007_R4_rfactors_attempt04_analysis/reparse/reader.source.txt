#!/usr/bin/env python3
"""Streaming envelope and encoding verifier for REFMAC 5.8.0431 native diagnostic traces.

Verifies byte-level, JSON-encoding, representation-header, sequence/footer, and
IEEE 754 binary32 exact decimal consistency for JSONL traces produced by the
accepted ``scripts/refmac_diagnostic/trace_writer.f90`` module
(``protstruct_refmac_native_trace_v1``).

Scope boundary:
- This module establishes raw byte identity and wire-envelope / binary32
  encoding consistency only.
- It never establishes scientific capture completeness, run eligibility, or
  EVAL/QDS publication.
- It uses the Python standard library only, invokes no subprocesses, reads no
  environment variables, and writes no files.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import stat
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping


TRACE_SCHEMA_ID = "protstruct_refmac_native_trace_v1"
TRACE_DECIMAL_ENCODING = "exact_from_captured_binary32_bits"

READ_CHUNK_BYTES = 65536
MAX_RECORD_BYTES = 65536
MAX_NAME_CHARS = 256
MAX_STRING_CHARS = 4096
MAX_FIELDS_PER_RECORD = 256
MAX_DECIMAL_DIGITS = 160
MAX_DECIMAL_CHARS = 200
MAX_NUMBER_TOKEN_CHARS = 32

INT32_MIN = -2_147_483_648
INT32_MAX = 2_147_483_647
INT64_MAX = 9_223_372_036_854_775_807

MIN_DECIMAL_EXPONENT = -149
MAX_DECIMAL_EXPONENT = 128

UPPER_HEX_CHARS = frozenset("0123456789ABCDEF")
LOWER_HEX_CHARS = frozenset("0123456789abcdef")
ASCII_DIGIT_CHARS = frozenset("0123456789")

RESERVED_FIELD_NAMES = frozenset(
    {
        "event",
        "sequence",
        "record_type",
        "schema_id",
        "record_count",
        "decimal_encoding",
    }
)

EXPECTED_HEADER_KEYS = frozenset(
    {
        "record_type",
        "schema_id",
        "decimal_encoding",
        "default_real_kind",
        "default_integer_kind",
        "default_real_storage_size",
        "default_integer_storage_size",
        "radix",
        "digits",
        "minexponent",
        "maxexponent",
        "default_real_radix",
        "default_real_digits",
        "default_real_minexponent",
        "default_real_maxexponent",
        "default_integer_radix",
        "default_integer_digits",
    }
)

EXPECTED_HEADER_FIXED_INTS: Mapping[str, int] = {
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

EXPECTED_WRITER_CLOSE_KEYS = frozenset(
    {
        "record_type",
        "schema_id",
        "event",
        "record_count",
    }
)

EXPECTED_REAL_OBJECT_KEYS = frozenset({"bits_hex", "decimal"})


@dataclass(frozen=True)
class DecodedBinary32:
    """Exact decoded representation of one trace_real {bits_hex, decimal} object."""

    bits_hex: str
    bits_u32: int
    sign_bit: int
    exp_bits: int
    frac_bits: int
    classification: str
    is_finite: bool
    is_zero: bool
    is_negative: bool
    exact_fraction: Fraction | None
    decimal_str: str


class _DuplicateKeyError(ValueError):
    """Raised when a JSON object contains duplicate keys at any nesting level."""


class _ForbiddenJsonTokenError(ValueError):
    """Raised when a JSON line contains raw float tokens or NaN/Infinity constants."""


class _OverlongNumberTokenError(ValueError):
    """Raised when a JSON integer token exceeds MAX_NUMBER_TOKEN_CHARS."""


def _is_nonbool_int(val: Any) -> bool:
    return isinstance(val, int) and not isinstance(val, bool)


def _is_int32_nonbool(val: Any) -> bool:
    return _is_nonbool_int(val) and INT32_MIN <= val <= INT32_MAX


def _is_fortran_nonblank_ascii_identifier(text: Any, *, max_chars: int = MAX_NAME_CHARS) -> bool:
    """Check trace_writer.f90 identifier rules: 1..max_chars ASCII (<127) with >=1 non-space char."""
    if not isinstance(text, str):
        return False
    if len(text) < 1 or len(text) > max_chars:
        return False
    if text.rstrip(" ") == "":
        return False
    return all(0 <= ord(ch) < 127 for ch in text)


def _is_reserved_user_field_name(name: str) -> bool:
    """Match trace_writer.f90 register_field_name reserved-key checks."""
    return name in RESERVED_FIELD_NAMES or name.strip(" ") in RESERVED_FIELD_NAMES


def _strict_object_pairs_hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    obj: dict[str, Any] = {}
    for key, val in pairs:
        if key in obj:
            raise _DuplicateKeyError(f"Duplicate JSON object key {key!r}")
        obj[key] = val
    return obj


def _reject_json_float(token: str) -> Any:
    raise _ForbiddenJsonTokenError(
        f"Raw JSON floating-point token {token!r} is forbidden in native trace records"
    )


def _reject_json_constant(token: str) -> Any:
    raise _ForbiddenJsonTokenError(
        f"Nonstandard JSON constant {token!r} is forbidden in native trace records"
    )


def _parse_bounded_json_int(token: str) -> int:
    if len(token) > MAX_NUMBER_TOKEN_CHARS:
        raise _OverlongNumberTokenError(
            f"JSON integer token length ({len(token)}) exceeds maximum {MAX_NUMBER_TOKEN_CHARS}"
        )
    return int(token)


def _binary32_bits_to_fraction(
    sign_bit: int, exp_bits: int, frac_bits: int
) -> Fraction:
    """Compute the exact rational value of a finite IEEE 754 binary32 word."""
    if exp_bits == 0 and frac_bits == 0:
        return Fraction(0, 1)
    if exp_bits == 0:
        mantissa = frac_bits
        bin_exp = -149
    else:
        mantissa = (1 << 23) + frac_bits
        bin_exp = exp_bits - 150

    if bin_exp >= 0:
        abs_val = Fraction(mantissa << bin_exp, 1)
    else:
        abs_val = Fraction(mantissa, 1 << (-bin_exp))
    return -abs_val if sign_bit else abs_val


def _parse_bounded_decimal_to_fraction(
    decimal_str: str, *, expected_negative: bool
) -> Fraction:
    """Parse a bounded finite non-zero decimal string into an exact Fraction."""
    if len(decimal_str) < 1 or len(decimal_str) > MAX_DECIMAL_CHARS:
        raise ValueError(
            f"Decimal string length ({len(decimal_str)}) outside 1..{MAX_DECIMAL_CHARS}"
        )
    if not all(32 < ord(ch) < 127 for ch in decimal_str):
        raise ValueError(
            "Decimal string contains whitespace, control, DEL, or non-ASCII characters"
        )
    if decimal_str.startswith("+"):
        raise ValueError("Leading '+' sign is not allowed in trace_real decimal string")

    is_negative = decimal_str.startswith("-")
    if is_negative != expected_negative:
        raise ValueError(
            f"Decimal sign ({'-' if is_negative else '+'}) does not match binary32 sign bit "
            f"({'-' if expected_negative else '+'})"
        )

    body = decimal_str[1:] if is_negative else decimal_str
    if not body:
        raise ValueError("Empty decimal significand")

    if "e" in body:
        raise ValueError("Lowercase 'e' exponent is not allowed in trace_real decimal string")

    if "E" in body:
        if body.count("E") > 1:
            raise ValueError("Multiple 'E' exponent markers in decimal string")
        coeff_str, exp_str = body.split("E", 1)
        if not exp_str or exp_str.startswith("+"):
            raise ValueError(f"Malformed decimal exponent {exp_str!r}")
        exp_neg = exp_str.startswith("-")
        exp_digits = exp_str[1:] if exp_neg else exp_str
        if (
            not exp_digits
            or len(exp_digits) > 4
            or not all(ch in ASCII_DIGIT_CHARS for ch in exp_digits)
        ):
            raise ValueError(f"Invalid decimal exponent digits {exp_str!r}")
        if len(exp_digits) > 1 and exp_digits.startswith("0"):
            raise ValueError(f"Leading zero in decimal exponent {exp_str!r}")
        exp_val = -int(exp_digits) if exp_neg else int(exp_digits)
        if exp_val < MIN_DECIMAL_EXPONENT or exp_val > MAX_DECIMAL_EXPONENT:
            raise ValueError(
                f"Decimal exponent {exp_val} outside bounded range "
                f"[{MIN_DECIMAL_EXPONENT}, {MAX_DECIMAL_EXPONENT}]"
            )
    else:
        coeff_str = body
        exp_val = 0

    if not coeff_str:
        raise ValueError("Missing decimal coefficient before exponent")

    if "." in coeff_str:
        if coeff_str.count(".") > 1:
            raise ValueError("Multiple decimal points in decimal coefficient")
        int_part, frac_part = coeff_str.split(".", 1)
        if not int_part or not frac_part:
            raise ValueError("Empty integer or fractional part in decimal string")
        if not all(ch in ASCII_DIGIT_CHARS for ch in int_part) or not all(
            ch in ASCII_DIGIT_CHARS for ch in frac_part
        ):
            raise ValueError("Non-digit characters in decimal significand")
        if len(int_part) > 1 and int_part.startswith("0"):
            raise ValueError("Leading zeros not allowed in decimal integer part")
        digits_str = int_part + frac_part
        effective_exp = exp_val - len(frac_part)
    else:
        if not all(ch in ASCII_DIGIT_CHARS for ch in coeff_str):
            raise ValueError("Non-digit characters in integer decimal coefficient")
        if coeff_str.startswith("0"):
            raise ValueError("Leading zero not allowed in integer decimal coefficient")
        if exp_val > -1 and "E" in body:
            raise ValueError(
                f"Writer integer-coefficient format only uses E exponent in [-149, -1], got E{exp_val}"
            )
        digits_str = coeff_str
        effective_exp = exp_val

    if len(digits_str) < 1 or len(digits_str) > MAX_DECIMAL_DIGITS:
        raise ValueError(
            f"Decimal significand digit count ({len(digits_str)}) exceeds {MAX_DECIMAL_DIGITS}"
        )

    coeff_int = int(digits_str)
    if coeff_int <= 0:
        raise ValueError("Finite non-zero binary32 cannot have zero decimal significand")

    if effective_exp >= 0:
        abs_frac = Fraction(coeff_int * (10 ** effective_exp), 1)
    else:
        abs_frac = Fraction(coeff_int, 10 ** (-effective_exp))

    return -abs_frac if is_negative else abs_frac


def _decode_binary32_exact(bits_hex: str, decimal_str: str) -> DecodedBinary32:
    """Decode and cross-verify a binary32 {bits_hex, decimal} pair using exact Fraction algebra."""
    if not isinstance(bits_hex, str):
        raise ValueError("bits_hex must be a string")
    if len(bits_hex) != 8 or not all(ch in UPPER_HEX_CHARS for ch in bits_hex):
        raise ValueError(
            f"bits_hex must be exactly 8 uppercase hex digits, got {bits_hex!r}"
        )

    if not isinstance(decimal_str, str):
        raise ValueError("decimal must be a string")
    if len(decimal_str) < 1 or len(decimal_str) > MAX_DECIMAL_CHARS:
        raise ValueError(
            f"decimal length ({len(decimal_str)}) must be in 1..{MAX_DECIMAL_CHARS}"
        )
    if not all(0 <= ord(ch) < 127 for ch in decimal_str):
        raise ValueError("decimal contains non-ASCII or DEL characters")

    bits_u32 = int(bits_hex, 16)
    sign_bit = (bits_u32 >> 31) & 0x1
    exp_bits = (bits_u32 >> 23) & 0xFF
    frac_bits = bits_u32 & 0x7FFFFF
    is_negative = sign_bit == 1

    if exp_bits == 255:
        if frac_bits != 0:
            if decimal_str != "NaN":
                raise ValueError(
                    f"NaN binary32 word {bits_hex} requires decimal 'NaN', got {decimal_str!r}"
                )
            return DecodedBinary32(
                bits_hex=bits_hex,
                bits_u32=bits_u32,
                sign_bit=sign_bit,
                exp_bits=exp_bits,
                frac_bits=frac_bits,
                classification="nan",
                is_finite=False,
                is_zero=False,
                is_negative=is_negative,
                exact_fraction=None,
                decimal_str=decimal_str,
            )
        expected_inf = "-Inf" if is_negative else "Inf"
        if decimal_str != expected_inf:
            raise ValueError(
                f"Infinity binary32 word {bits_hex} requires decimal {expected_inf!r}, got {decimal_str!r}"
            )
        return DecodedBinary32(
            bits_hex=bits_hex,
            bits_u32=bits_u32,
            sign_bit=sign_bit,
            exp_bits=exp_bits,
            frac_bits=frac_bits,
            classification="infinity",
            is_finite=False,
            is_zero=False,
            is_negative=is_negative,
            exact_fraction=None,
            decimal_str=decimal_str,
        )

    if decimal_str in ("NaN", "Inf", "-Inf"):
        raise ValueError(
            f"Finite binary32 word {bits_hex} cannot have non-finite decimal {decimal_str!r}"
        )

    if exp_bits == 0 and frac_bits == 0:
        expected_zero = "-0.0" if is_negative else "0.0"
        if decimal_str != expected_zero:
            raise ValueError(
                f"Signed zero binary32 word {bits_hex} requires decimal {expected_zero!r}, got {decimal_str!r}"
            )
        return DecodedBinary32(
            bits_hex=bits_hex,
            bits_u32=bits_u32,
            sign_bit=sign_bit,
            exp_bits=exp_bits,
            frac_bits=frac_bits,
            classification="zero",
            is_finite=True,
            is_zero=True,
            is_negative=is_negative,
            exact_fraction=Fraction(0, 1),
            decimal_str=decimal_str,
        )

    if decimal_str in ("0.0", "-0.0"):
        raise ValueError(
            f"Non-zero binary32 word {bits_hex} cannot have zero decimal {decimal_str!r}"
        )

    bits_fraction = _binary32_bits_to_fraction(sign_bit, exp_bits, frac_bits)
    decimal_fraction = _parse_bounded_decimal_to_fraction(
        decimal_str, expected_negative=is_negative
    )
    if decimal_fraction != bits_fraction:
        raise ValueError(
            f"Exact binary32/decimal mismatch for {bits_hex}: "
            f"bits rational={bits_fraction} != decimal rational={decimal_fraction} ({decimal_str!r})"
        )

    classification = "subnormal" if exp_bits == 0 else "normal"
    return DecodedBinary32(
        bits_hex=bits_hex,
        bits_u32=bits_u32,
        sign_bit=sign_bit,
        exp_bits=exp_bits,
        frac_bits=frac_bits,
        classification=classification,
        is_finite=True,
        is_zero=False,
        is_negative=is_negative,
        exact_fraction=bits_fraction,
        decimal_str=decimal_str,
    )


def decode_trace_real_object(real_obj: Mapping[str, Any]) -> DecodedBinary32:
    """Validate and decode a trace_real JSON object {'bits_hex': ..., 'decimal': ...}."""
    if not isinstance(real_obj, Mapping):
        raise ValueError("trace_real value must be a JSON object")
    if set(real_obj.keys()) != EXPECTED_REAL_OBJECT_KEYS:
        raise ValueError(
            f"trace_real object must contain exact keys {sorted(EXPECTED_REAL_OBJECT_KEYS)}, "
            f"got {sorted(real_obj.keys())}"
        )
    return _decode_binary32_exact(real_obj["bits_hex"], real_obj["decimal"])


def validate_expected_trace_pins(
    expected_sha256: Any, expected_size_bytes: Any
) -> tuple[str, int]:
    """Validate expected SHA-256 and byte-size pins, raising ValueError on malformed inputs."""
    if not isinstance(expected_sha256, str):
        raise ValueError(
            f"expected_sha256 must be a 64-character lowercase hex string, got {type(expected_sha256).__name__}"
        )
    if len(expected_sha256) != 64 or not all(
        ch in LOWER_HEX_CHARS for ch in expected_sha256
    ):
        raise ValueError(
            f"expected_sha256 must be exactly 64 lowercase hexadecimal characters, got {expected_sha256!r}"
        )

    if not _is_nonbool_int(expected_size_bytes):
        raise ValueError(
            f"expected_size_bytes must be a non-boolean integer, got {type(expected_size_bytes).__name__}"
        )
    if expected_size_bytes < 0:
        raise ValueError(
            f"expected_size_bytes must be non-negative, got {expected_size_bytes}"
        )

    return expected_sha256, int(expected_size_bytes)


_MACOS_SYSTEM_ROOT_SYMLINKS = frozenset({Path("/var"), Path("/tmp"), Path("/etc")})


def _check_non_symlink_regular_path(
    path_obj: Path, *, has_trailing_sep: bool = False
) -> tuple[Path, os.stat_result]:
    """Walk path components with lstat to reject symlinks and non-regular target files."""
    expanded = path_obj.expanduser()
    if not expanded.is_absolute():
        expanded = Path.cwd() / expanded
    current = Path(expanded.root)
    parts = [p for p in expanded.parts[1:] if p not in ("", ".")]
    if not parts:
        raise ValueError(f"Trace path does not name a file: {path_obj}")

    last_info: os.stat_result | None = None
    for idx, part in enumerate(parts):
        if part == "..":
            raise ValueError(f"Parent traversal '..' not allowed in trace path: {path_obj}")
        current = current / part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            raise FileNotFoundError(f"Trace path does not exist: {current}") from None
        if stat.S_ISLNK(info.st_mode):
            if idx == 0 and current in _MACOS_SYSTEM_ROOT_SYMLINKS and idx < len(parts) - 1:
                current = current.resolve(strict=True)
                info = os.lstat(current)
            else:
                raise ValueError(f"Symlink rejected in trace path: {current}")
        if idx < len(parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise NotADirectoryError(
                errno.ENOTDIR,
                f"Intermediate path component is not a directory: {current}",
                str(current),
            )
        last_info = info

    if last_info is None:
        raise ValueError(f"Trace path does not name a file: {current}")
    if has_trailing_sep and not stat.S_ISDIR(last_info.st_mode):
        raise NotADirectoryError(
            errno.ENOTDIR,
            f"Trailing directory separator on non-directory path: {current}",
            str(current),
        )
    if not stat.S_ISREG(last_info.st_mode):
        raise ValueError(f"Trace path is not a regular file: {current}")
    return current, last_info


def inspect_native_trace_envelope(
    path: Path | str,
    *,
    expected_sha256: str,
    expected_size_bytes: int,
) -> dict[str, Any]:
    """Stream, hash, and verify a native diagnostic trace JSONL file against its envelope contract.

    Returns a JSON-safe dictionary containing:
    - ``valid``: True iff pins, file identity, header, all records, writer_close,
      and raw SHA-256 / byte size all pass.
    - ``closed``: True iff header, 0..N valid data records, and writer_close at
      EOF are all structurally valid with no trailing data.
    - ``read_complete``: True iff the opened regular file was read through EOF.
    - ``observed_sha256`` / ``observed_size_bytes``: Streaming SHA-256 and byte
      count across the entire regular file through EOF (or None if EOF was not
      reached).
    - ``bytes_read`` / ``partial_sha256`` / ``partial_size_bytes``: Explicit byte
      progress and prefix SHA-256 when a read or descriptor failure prevents
      reaching EOF.
    - ``event_count`` / ``record_count``: Number of valid data event records
      observed before ``writer_close``.
    - ``representation_header``: Validated header record dictionary (or None).
    - ``first_failure`` and ``errors``: Explicit failure locations, stages, and reasons.
    """
    errors: list[dict[str, Any]] = []

    def add_error(
        code: str,
        message: str,
        *,
        line_number: int | None = None,
        byte_offset: int | None = None,
        field: str | None = None,
        stage: str = "envelope_parse",
        errno_value: int | None = None,
        exception_type: str | None = None,
    ) -> None:
        errors.append(
            {
                "code": code,
                "message": message,
                "stage": stage,
                "line_number": line_number,
                "byte_offset": byte_offset,
                "field": field,
                "errno": errno_value,
                "exception_type": exception_type,
            }
        )

    sanitized_expected_sha256: str | None = None
    sanitized_expected_size: int | None = None
    pins_valid = False
    try:
        sanitized_expected_sha256, sanitized_expected_size = validate_expected_trace_pins(
            expected_sha256, expected_size_bytes
        )
        pins_valid = True
    except ValueError as exc:
        if isinstance(expected_sha256, str):
            sanitized_expected_sha256 = expected_sha256
        if _is_nonbool_int(expected_size_bytes):
            sanitized_expected_size = int(expected_size_bytes)
        add_error(
            "malformed_expected_pin",
            str(exc),
            line_number=None,
            byte_offset=0,
            stage="pin_validation",
            exception_type=type(exc).__name__,
        )

    def _early_failure_result(path_repr: str) -> dict[str, Any]:
        return _build_result(
            path_str=path_repr,
            valid=False,
            closed=False,
            event_count=0,
            footer_record_count=None,
            expected_sha256=sanitized_expected_sha256,
            observed_sha256=None,
            sha256_match=False,
            expected_size_bytes=sanitized_expected_size,
            observed_size_bytes=None,
            size_bytes_match=False,
            read_complete=False,
            bytes_read=0,
            partial_sha256=None,
            partial_size_bytes=0,
            representation_header=None,
            errors=errors,
        )

    if not isinstance(path, (str, os.PathLike)) or str(path) == "":
        add_error(
            "invalid_trace_path",
            f"path must be a non-empty path or string, got {path!r}",
            line_number=None,
            byte_offset=0,
            stage="path_inspection",
        )
        return _early_failure_result(repr(path))

    raw_fspath = os.fspath(path)
    if isinstance(raw_fspath, bytes):
        raw_path_text = raw_fspath.decode("utf-8", errors="surrogateescape")
    else:
        raw_path_text = str(raw_fspath)
    has_trailing_sep = len(raw_path_text) > 1 and raw_path_text.endswith(
        tuple(sep for sep in (os.sep, os.altsep) if sep)
    )
    path_obj = Path(raw_path_text)
    path_str = str(path_obj)

    try:
        checked_path, lstat_pre = _check_non_symlink_regular_path(
            path_obj, has_trailing_sep=has_trailing_sep
        )
    except FileNotFoundError as exc:
        add_error(
            "trace_file_not_found",
            str(exc),
            line_number=None,
            byte_offset=0,
            stage="path_inspection",
            errno_value=exc.errno,
            exception_type=type(exc).__name__,
        )
        return _early_failure_result(path_str)
    except NotADirectoryError as exc:
        add_error(
            "not_a_directory",
            f"Trace path traverses a non-directory component: {exc}",
            line_number=None,
            byte_offset=0,
            stage="path_inspection",
            errno_value=exc.errno,
            exception_type=type(exc).__name__,
        )
        return _early_failure_result(path_str)
    except PermissionError as exc:
        add_error(
            "permission_denied",
            f"Permission denied while inspecting trace path: {exc}",
            line_number=None,
            byte_offset=0,
            stage="path_inspection",
            errno_value=exc.errno,
            exception_type=type(exc).__name__,
        )
        return _early_failure_result(path_str)
    except OSError as exc:
        err_code = (
            "symlink_rejected"
            if exc.errno == getattr(errno, "ELOOP", -1)
            else "path_inspection_os_error"
        )
        add_error(
            err_code,
            f"OS error while inspecting trace path: {exc}",
            line_number=None,
            byte_offset=0,
            stage="path_inspection",
            errno_value=exc.errno,
            exception_type=type(exc).__name__,
        )
        return _early_failure_result(path_str)
    except ValueError as exc:
        msg = str(exc)
        err_code = "symlink_rejected" if "Symlink" in msg else "not_regular_file"
        add_error(
            err_code,
            msg,
            line_number=None,
            byte_offset=0,
            stage="path_inspection",
            exception_type=type(exc).__name__,
        )
        return _early_failure_result(path_str)

    open_flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        open_flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        open_flags |= os.O_NOFOLLOW

    try:
        fd = os.open(checked_path, open_flags)
    except PermissionError as exc:
        add_error(
            "permission_denied",
            f"Permission denied opening trace file: {exc}",
            line_number=None,
            byte_offset=0,
            stage="open",
            errno_value=exc.errno,
            exception_type=type(exc).__name__,
        )
        return _early_failure_result(path_str)
    except FileNotFoundError as exc:
        add_error(
            "trace_file_not_found",
            f"Trace file disappeared before open: {exc}",
            line_number=None,
            byte_offset=0,
            stage="open",
            errno_value=exc.errno,
            exception_type=type(exc).__name__,
        )
        return _early_failure_result(path_str)
    except NotADirectoryError as exc:
        add_error(
            "not_a_directory",
            f"Not a directory opening trace file: {exc}",
            line_number=None,
            byte_offset=0,
            stage="open",
            errno_value=exc.errno,
            exception_type=type(exc).__name__,
        )
        return _early_failure_result(path_str)
    except OSError as exc:
        err_code = (
            "symlink_rejected"
            if exc.errno == getattr(errno, "ELOOP", -1)
            else "open_failed"
        )
        add_error(
            err_code,
            f"Failed to open trace file: {exc}",
            line_number=None,
            byte_offset=0,
            stage="open",
            errno_value=exc.errno,
            exception_type=type(exc).__name__,
        )
        return _early_failure_result(path_str)

    hasher = hashlib.sha256()
    bytes_read = 0
    read_complete = False
    descriptor_ok = False
    representation_header: dict[str, Any] | None = None
    event_count = 0
    footer_record_count: int | None = None
    header_seen = False
    close_seen = False
    parse_aborted = False

    def validate_header(
        obj: dict[str, Any], line_no: int, line_offset: int
    ) -> bool:
        nonlocal representation_header, header_seen
        if obj.get("record_type") != "header":
            add_error(
                "missing_header_record",
                f"First record must have record_type='header', got {obj.get('record_type')!r}",
                line_number=line_no,
                byte_offset=line_offset,
                field="record_type",
            )
            return False

        obj_keys = set(obj.keys())
        missing_keys = sorted(EXPECTED_HEADER_KEYS - obj_keys)
        extra_keys = sorted(obj_keys - EXPECTED_HEADER_KEYS)
        if missing_keys or extra_keys:
            add_error(
                "invalid_header_fields",
                f"Header record field mismatch: missing={missing_keys}, unknown={extra_keys}",
                line_number=line_no,
                byte_offset=line_offset,
            )
            return False

        if obj["schema_id"] != TRACE_SCHEMA_ID:
            add_error(
                "invalid_schema_id",
                f"Header schema_id must be {TRACE_SCHEMA_ID!r}, got {obj['schema_id']!r}",
                line_number=line_no,
                byte_offset=line_offset,
                field="schema_id",
            )
            return False

        if obj["decimal_encoding"] != TRACE_DECIMAL_ENCODING:
            add_error(
                "invalid_decimal_encoding",
                f"Header decimal_encoding must be {TRACE_DECIMAL_ENCODING!r}, got {obj['decimal_encoding']!r}",
                line_number=line_no,
                byte_offset=line_offset,
                field="decimal_encoding",
            )
            return False

        for kind_field in ("default_real_kind", "default_integer_kind"):
            kind_val = obj[kind_field]
            if not _is_int32_nonbool(kind_val) or kind_val <= 0:
                add_error(
                    "invalid_header_kind",
                    f"Header {kind_field} must be a positive int32 (non-bool), got {kind_val!r}",
                    line_number=line_no,
                    byte_offset=line_offset,
                    field=kind_field,
                )
                return False

        for field_name in EXPECTED_HEADER_FIXED_INTS:
            val = obj[field_name]
            if not _is_int32_nonbool(val):
                add_error(
                    "invalid_header_model_type",
                    f"Header {field_name} must be an int32 (non-bool), got {val!r}",
                    line_number=line_no,
                    byte_offset=line_offset,
                    field=field_name,
                )
                return False

        duplicate_model_pairs = (
            ("radix", "default_real_radix"),
            ("digits", "default_real_digits"),
            ("minexponent", "default_real_minexponent"),
            ("maxexponent", "default_real_maxexponent"),
        )
        for short_key, full_key in duplicate_model_pairs:
            if obj[short_key] != obj[full_key]:
                add_error(
                    "conflicting_header_model_metadata",
                    f"Conflicting duplicate header model metadata: {short_key}={obj[short_key]!r} != {full_key}={obj[full_key]!r}",
                    line_number=line_no,
                    byte_offset=line_offset,
                    field=full_key,
                )
                return False

        for field_name, expected_val in EXPECTED_HEADER_FIXED_INTS.items():
            actual_val = obj[field_name]
            if actual_val != expected_val:
                add_error(
                    "invalid_header_model_value",
                    f"Header {field_name} must be {expected_val}, got {actual_val!r}",
                    line_number=line_no,
                    byte_offset=line_offset,
                    field=field_name,
                )
                return False

        representation_header = dict(obj)
        header_seen = True
        return True

    def validate_writer_close(
        obj: dict[str, Any], line_no: int, line_offset: int
    ) -> bool:
        nonlocal close_seen, footer_record_count
        if "sequence" in obj:
            add_error(
                "writer_close_has_sequence",
                "writer_close record must not contain a 'sequence' field",
                line_number=line_no,
                byte_offset=line_offset,
                field="sequence",
            )
            return False

        obj_keys = set(obj.keys())
        if obj_keys != EXPECTED_WRITER_CLOSE_KEYS:
            missing_keys = sorted(EXPECTED_WRITER_CLOSE_KEYS - obj_keys)
            extra_keys = sorted(obj_keys - EXPECTED_WRITER_CLOSE_KEYS)
            add_error(
                "invalid_writer_close_fields",
                f"writer_close field mismatch: missing={missing_keys}, unknown={extra_keys}",
                line_number=line_no,
                byte_offset=line_offset,
            )
            return False

        if obj["record_type"] != "writer_close":
            add_error(
                "invalid_record_type",
                f"Expected record_type='writer_close', got {obj['record_type']!r}",
                line_number=line_no,
                byte_offset=line_offset,
                field="record_type",
            )
            return False

        if obj["schema_id"] != TRACE_SCHEMA_ID:
            add_error(
                "invalid_writer_close_schema_id",
                f"writer_close schema_id must be {TRACE_SCHEMA_ID!r}, got {obj['schema_id']!r}",
                line_number=line_no,
                byte_offset=line_offset,
                field="schema_id",
            )
            return False

        if obj["event"] != "writer_close":
            add_error(
                "invalid_writer_close_event",
                f"writer_close event must be 'writer_close', got {obj['event']!r}",
                line_number=line_no,
                byte_offset=line_offset,
                field="event",
            )
            return False

        rec_count = obj["record_count"]
        if not _is_nonbool_int(rec_count) or rec_count < 0 or rec_count > INT64_MAX:
            add_error(
                "invalid_writer_close_record_count_type",
                f"writer_close record_count must be a non-negative int64 (non-bool), got {rec_count!r}",
                line_number=line_no,
                byte_offset=line_offset,
                field="record_count",
            )
            return False

        footer_record_count = int(rec_count)
        if footer_record_count != event_count:
            add_error(
                "writer_close_record_count_mismatch",
                f"writer_close record_count ({footer_record_count}) does not match observed event count ({event_count})",
                line_number=line_no,
                byte_offset=line_offset,
                field="record_count",
            )
            return False

        close_seen = True
        return True

    def validate_data_record(
        obj: dict[str, Any], line_no: int, line_offset: int
    ) -> bool:
        nonlocal event_count
        if "sequence" not in obj or "event" not in obj:
            add_error(
                "missing_data_record_envelope_key",
                "Data record must contain both 'sequence' and 'event'",
                line_number=line_no,
                byte_offset=line_offset,
            )
            return False

        seq_val = obj["sequence"]
        if not _is_nonbool_int(seq_val) or seq_val < 1 or seq_val > INT64_MAX:
            add_error(
                "invalid_sequence_type",
                f"Data record sequence must be a positive int64 (non-bool), got {seq_val!r}",
                line_number=line_no,
                byte_offset=line_offset,
                field="sequence",
            )
            return False

        expected_seq = event_count + 1
        if seq_val != expected_seq:
            add_error(
                "sequence_mismatch",
                f"Expected contiguous sequence {expected_seq}, got {seq_val}",
                line_number=line_no,
                byte_offset=line_offset,
                field="sequence",
            )
            return False

        event_val = obj["event"]
        if not _is_fortran_nonblank_ascii_identifier(event_val, max_chars=MAX_NAME_CHARS):
            add_error(
                "invalid_event_name",
                f"Invalid event name {event_val!r}: must be 1..{MAX_NAME_CHARS} ASCII (<127) chars with >=1 non-space char",
                line_number=line_no,
                byte_offset=line_offset,
                field="event",
            )
            return False

        user_items = [
            (k, v) for k, v in obj.items() if k not in ("sequence", "event")
        ]
        if len(user_items) > MAX_FIELDS_PER_RECORD:
            add_error(
                "too_many_fields",
                f"Data record has {len(user_items)} user fields, exceeding maximum {MAX_FIELDS_PER_RECORD}",
                line_number=line_no,
                byte_offset=line_offset,
            )
            return False

        for field_name, field_val in user_items:
            if not _is_fortran_nonblank_ascii_identifier(
                field_name, max_chars=MAX_NAME_CHARS
            ):
                add_error(
                    "invalid_field_name",
                    f"Invalid field name {field_name!r}: must be 1..{MAX_NAME_CHARS} ASCII (<127) chars with >=1 non-space char",
                    line_number=line_no,
                    byte_offset=line_offset,
                    field=field_name if isinstance(field_name, str) else None,
                )
                return False

            if _is_reserved_user_field_name(field_name):
                add_error(
                    "reserved_field_name",
                    f"User field name {field_name!r} conflicts with reserved envelope identifier",
                    line_number=line_no,
                    byte_offset=line_offset,
                    field=field_name,
                )
                return False

            if isinstance(field_val, bool):
                continue

            if _is_nonbool_int(field_val):
                if not _is_int32_nonbool(field_val):
                    add_error(
                        "integer_out_of_int32_range",
                        f"Field {field_name!r} integer {field_val} is outside int32 range [{INT32_MIN}, {INT32_MAX}]",
                        line_number=line_no,
                        byte_offset=line_offset,
                        field=field_name,
                    )
                    return False
                continue

            if isinstance(field_val, str):
                if len(field_val) > MAX_STRING_CHARS:
                    add_error(
                        "string_too_long",
                        f"Field {field_name!r} string length ({len(field_val)}) exceeds maximum {MAX_STRING_CHARS}",
                        line_number=line_no,
                        byte_offset=line_offset,
                        field=field_name,
                    )
                    return False
                if not all(0 <= ord(ch) < 127 for ch in field_val):
                    add_error(
                        "non_ascii_or_del_string",
                        f"Field {field_name!r} string contains non-ASCII or DEL character",
                        line_number=line_no,
                        byte_offset=line_offset,
                        field=field_name,
                    )
                    return False
                continue

            if isinstance(field_val, dict):
                try:
                    decode_trace_real_object(field_val)
                except ValueError as exc:
                    add_error(
                        "invalid_real_object",
                        f"Field {field_name!r} real encoding error: {exc}",
                        line_number=line_no,
                        byte_offset=line_offset,
                        field=field_name,
                    )
                    return False
                continue

            add_error(
                "unsupported_field_value_type",
                f"Field {field_name!r} has unsupported JSON value type {type(field_val).__name__}",
                line_number=line_no,
                byte_offset=line_offset,
                field=field_name,
            )
            return False

        event_count += 1
        return True

    def inspect_single_line(
        raw_line: bytes, line_no: int, line_offset: int
    ) -> bool:
        if close_seen:
            add_error(
                "trailing_record_after_close",
                "Unexpected trailing record after writer_close",
                line_number=line_no,
                byte_offset=line_offset,
            )
            return False

        if raw_line.strip(b" \t\r") == b"":
            add_error(
                "blank_line",
                "Blank or whitespace-only line is forbidden in native trace JSONL",
                line_number=line_no,
                byte_offset=line_offset,
            )
            return False

        if not all(32 <= b <= 126 for b in raw_line):
            add_error(
                "non_ascii_or_control_byte",
                "Raw line contains unescaped control, CR, DEL, or non-ASCII byte",
                line_number=line_no,
                byte_offset=line_offset,
            )
            return False

        if not (raw_line.startswith(b"{") and raw_line.endswith(b"}")):
            add_error(
                "malformed_json",
                "Trace line must be a single JSON object starting with '{' and ending with '}'",
                line_number=line_no,
                byte_offset=line_offset,
            )
            return False

        line_text = raw_line.decode("ascii")
        try:
            parsed = json.loads(
                line_text,
                object_pairs_hook=_strict_object_pairs_hook,
                parse_float=_reject_json_float,
                parse_constant=_reject_json_constant,
                parse_int=_parse_bounded_json_int,
            )
        except _DuplicateKeyError as exc:
            add_error(
                "duplicate_json_key",
                str(exc),
                line_number=line_no,
                byte_offset=line_offset,
            )
            return False
        except _ForbiddenJsonTokenError as exc:
            add_error(
                "forbidden_json_number_token",
                str(exc),
                line_number=line_no,
                byte_offset=line_offset,
            )
            return False
        except _OverlongNumberTokenError as exc:
            add_error(
                "overlong_number_token",
                str(exc),
                line_number=line_no,
                byte_offset=line_offset,
                stage="envelope_parse",
                exception_type=type(exc).__name__,
            )
            return False
        except RecursionError as exc:
            add_error(
                "json_recursion_depth_exceeded",
                f"JSON decoding exceeded maximum recursion depth: {exc}",
                line_number=line_no,
                byte_offset=line_offset,
                stage="envelope_parse",
                exception_type=type(exc).__name__,
            )
            return False
        except json.JSONDecodeError as exc:
            add_error(
                "malformed_json",
                f"Malformed JSON record: {exc.msg}",
                line_number=line_no,
                byte_offset=line_offset,
                stage="envelope_parse",
                exception_type=type(exc).__name__,
            )
            return False

        if not isinstance(parsed, dict):
            add_error(
                "malformed_json",
                "Top-level JSON value must be an object",
                line_number=line_no,
                byte_offset=line_offset,
            )
            return False

        if line_no == 1:
            return validate_header(parsed, line_no, line_offset)

        rec_type = parsed.get("record_type")
        if rec_type == "header":
            add_error(
                "duplicate_header_record",
                "Duplicate header record is forbidden after line 1",
                line_number=line_no,
                byte_offset=line_offset,
                field="record_type",
            )
            return False

        if (
            "record_type" in parsed
            or (
                "sequence" not in parsed
                and (
                    parsed.get("event") == "writer_close"
                    or "record_count" in parsed
                )
            )
        ):
            return validate_writer_close(parsed, line_no, line_offset)

        return validate_data_record(parsed, line_no, line_offset)

    last_byte_was_lf = False
    try:
        fstat_pre: os.stat_result | None = None
        can_stream_fd = False
        try:
            fstat_pre = os.fstat(fd)
        except OSError as exc:
            add_error(
                "pre_read_fstat_failed",
                f"Failed to fstat opened trace descriptor before reading: {exc}",
                line_number=None,
                byte_offset=0,
                stage="pre_read_fstat",
                errno_value=exc.errno,
                exception_type=type(exc).__name__,
            )
            parse_aborted = True
        else:
            if not stat.S_ISREG(fstat_pre.st_mode):
                add_error(
                    "not_regular_file",
                    "Opened descriptor is not a regular file",
                    line_number=None,
                    byte_offset=0,
                    stage="pre_read_fstat",
                )
                parse_aborted = True
            elif (fstat_pre.st_dev, fstat_pre.st_ino) != (
                lstat_pre.st_dev,
                lstat_pre.st_ino,
            ):
                add_error(
                    "descriptor_or_path_changed",
                    "Opened descriptor inode/device did not match pre-open lstat identity",
                    line_number=None,
                    byte_offset=0,
                    stage="pre_read_fstat",
                )
                parse_aborted = True
            else:
                can_stream_fd = True

        if can_stream_fd:
            pending = bytearray()
            line_number = 0
            current_line_start_offset = 0

            while True:
                try:
                    chunk = os.read(fd, READ_CHUNK_BYTES)
                except OSError as exc:
                    add_error(
                        "descriptor_read_failed",
                        f"Failed while reading trace file descriptor at byte offset {bytes_read}: {exc}",
                        line_number=line_number + 1 if not parse_aborted else None,
                        byte_offset=bytes_read,
                        stage="read",
                        errno_value=exc.errno,
                        exception_type=type(exc).__name__,
                    )
                    pending.clear()
                    parse_aborted = True
                    break

                if not chunk:
                    read_complete = True
                    break
                hasher.update(chunk)
                bytes_read += len(chunk)
                last_byte_was_lf = chunk[-1] == 0x0A

                if parse_aborted:
                    continue

                start = 0
                chunk_len = len(chunk)
                while start < chunk_len:
                    nl_pos = chunk.find(b"\n", start)
                    if nl_pos == -1:
                        remaining = chunk[start:]
                        if len(pending) + len(remaining) > MAX_RECORD_BYTES:
                            line_number += 1
                            add_error(
                                "record_too_long",
                                f"Line {line_number} exceeds maximum record length of {MAX_RECORD_BYTES} bytes before newline",
                                line_number=line_number,
                                byte_offset=current_line_start_offset,
                            )
                            pending.clear()
                            parse_aborted = True
                        else:
                            pending.extend(remaining)
                        break

                    segment = chunk[start:nl_pos]
                    line_number += 1
                    line_byte_len = len(pending) + len(segment)
                    if line_byte_len > MAX_RECORD_BYTES:
                        add_error(
                            "record_too_long",
                            f"Line {line_number} length ({line_byte_len} bytes) exceeds maximum record length of {MAX_RECORD_BYTES} bytes",
                            line_number=line_number,
                            byte_offset=current_line_start_offset,
                        )
                        pending.clear()
                        parse_aborted = True
                        break

                    if pending:
                        pending.extend(segment)
                        raw_line = bytes(pending)
                        pending.clear()
                    else:
                        raw_line = segment

                    line_offset = current_line_start_offset
                    current_line_start_offset = line_offset + line_byte_len + 1
                    if not inspect_single_line(raw_line, line_number, line_offset):
                        parse_aborted = True
                        break
                    start = nl_pos + 1

            if read_complete:
                if bytes_read == 0:
                    add_error(
                        "empty_trace_file",
                        "Trace file is empty (0 bytes)",
                        line_number=1,
                        byte_offset=0,
                        stage="eof_validation",
                    )
                else:
                    if not last_byte_was_lf:
                        trunc_line = line_number + 1 if not parse_aborted else None
                        trunc_offset = (
                            current_line_start_offset
                            if not parse_aborted
                            else bytes_read
                        )
                        add_error(
                            "missing_final_newline",
                            "Trace output is truncated: missing final newline ('\\n')",
                            line_number=trunc_line,
                            byte_offset=trunc_offset,
                            stage="eof_validation",
                        )
                    elif not parse_aborted and not close_seen:
                        add_error(
                            "missing_writer_close",
                            "Trace output is truncated or unclosed: missing final writer_close record",
                            line_number=line_number + 1,
                            byte_offset=bytes_read,
                            stage="eof_validation",
                        )

            assert fstat_pre is not None
            try:
                fstat_post = os.fstat(fd)
            except OSError as exc:
                add_error(
                    "post_read_fstat_failed",
                    f"Post-read fstat failed on trace descriptor: {exc}",
                    line_number=None,
                    byte_offset=bytes_read,
                    stage="post_read_fstat",
                    errno_value=exc.errno,
                    exception_type=type(exc).__name__,
                )
            else:
                try:
                    lstat_post = os.lstat(checked_path)
                except OSError as exc:
                    add_error(
                        "descriptor_or_path_changed",
                        f"Post-read lstat failed on trace path: {exc}",
                        line_number=None,
                        byte_offset=bytes_read,
                        stage="post_read_lstat",
                        errno_value=exc.errno,
                        exception_type=type(exc).__name__,
                    )
                else:
                    if (
                        not stat.S_ISREG(fstat_post.st_mode)
                        or not stat.S_ISREG(lstat_post.st_mode)
                        or stat.S_ISLNK(lstat_post.st_mode)
                        or (fstat_post.st_dev, fstat_post.st_ino)
                        != (fstat_pre.st_dev, fstat_pre.st_ino)
                        or (lstat_post.st_dev, lstat_post.st_ino)
                        != (fstat_pre.st_dev, fstat_pre.st_ino)
                        or (read_complete and fstat_post.st_size != bytes_read)
                        or (read_complete and lstat_post.st_size != bytes_read)
                        or (read_complete and fstat_pre.st_size != bytes_read)
                        or fstat_post.st_mtime_ns != fstat_pre.st_mtime_ns
                    ):
                        add_error(
                            "descriptor_or_path_changed",
                            "Trace file descriptor or path identity/size/mtime changed during inspection",
                            line_number=None,
                            byte_offset=bytes_read,
                            stage="post_read_identity",
                        )
                    else:
                        descriptor_ok = True
    finally:
        try:
            os.close(fd)
        except OSError as exc:
            descriptor_ok = False
            add_error(
                "close_failed",
                f"Failed to close trace file descriptor: {exc}",
                line_number=None,
                byte_offset=bytes_read,
                stage="close",
                errno_value=exc.errno,
                exception_type=type(exc).__name__,
            )

    if read_complete:
        observed_sha256: str | None = hasher.hexdigest()
        observed_size_bytes: int | None = bytes_read
        partial_sha256: str | None = None
        partial_size_bytes: int | None = None
        sha256_match = bool(
            pins_valid and observed_sha256 == sanitized_expected_sha256
        )
        size_bytes_match = bool(
            pins_valid and observed_size_bytes == sanitized_expected_size
        )

        if pins_valid and not size_bytes_match:
            add_error(
                "size_bytes_mismatch",
                f"Observed byte size ({observed_size_bytes}) does not match expected_size_bytes ({sanitized_expected_size})",
                line_number=None,
                byte_offset=observed_size_bytes,
                field="expected_size_bytes",
                stage="pin_comparison",
            )

        if pins_valid and not sha256_match:
            add_error(
                "sha256_mismatch",
                f"Observed SHA-256 ({observed_sha256}) does not match expected_sha256 ({sanitized_expected_sha256})",
                line_number=None,
                byte_offset=observed_size_bytes,
                field="expected_sha256",
                stage="pin_comparison",
            )
    else:
        observed_sha256 = None
        observed_size_bytes = None
        partial_sha256 = hasher.hexdigest() if bytes_read > 0 else None
        partial_size_bytes = bytes_read
        sha256_match = False
        size_bytes_match = False

    envelope_closed = bool(
        read_complete
        and descriptor_ok
        and header_seen
        and close_seen
        and not parse_aborted
        and last_byte_was_lf
    )
    valid = bool(
        envelope_closed
        and pins_valid
        and sha256_match
        and size_bytes_match
        and not errors
    )

    return _build_result(
        path_str=path_str,
        valid=valid,
        closed=envelope_closed,
        event_count=event_count,
        footer_record_count=footer_record_count,
        expected_sha256=sanitized_expected_sha256,
        observed_sha256=observed_sha256,
        sha256_match=sha256_match,
        expected_size_bytes=sanitized_expected_size,
        observed_size_bytes=observed_size_bytes,
        size_bytes_match=size_bytes_match,
        read_complete=read_complete,
        bytes_read=bytes_read,
        partial_sha256=partial_sha256,
        partial_size_bytes=partial_size_bytes,
        representation_header=representation_header,
        errors=errors,
    )


def _build_result(
    *,
    path_str: str,
    valid: bool,
    closed: bool,
    event_count: int,
    footer_record_count: int | None,
    expected_sha256: str | None,
    observed_sha256: str | None,
    sha256_match: bool,
    expected_size_bytes: int | None,
    observed_size_bytes: int | None,
    size_bytes_match: bool,
    read_complete: bool,
    bytes_read: int,
    partial_sha256: str | None,
    partial_size_bytes: int | None,
    representation_header: dict[str, Any] | None,
    errors: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_id": TRACE_SCHEMA_ID,
        "envelope_only": True,
        "scientific_capture_established": False,
        "scientific_eligibility_established": False,
        "descriptor_binding_note": (
            "Opened with O_RDONLY (+ O_NOFOLLOW when available) and bound via pre/post "
            "fstat/lstat inode/device/size/mtime comparison; detects path replacement across "
            "the inspection window without claiming kernel-atomic protection against transient swaps."
        ),
        "path": path_str,
        "valid": valid,
        "closed": closed,
        "has_events": bool(closed and event_count > 0),
        "event_count": event_count,
        "record_count": event_count,
        "footer_record_count": footer_record_count,
        "expected_sha256": expected_sha256,
        "observed_sha256": observed_sha256,
        "sha256_match": sha256_match,
        "expected_size_bytes": expected_size_bytes,
        "observed_size_bytes": observed_size_bytes,
        "size_bytes_match": size_bytes_match,
        "read_complete": read_complete,
        "bytes_read": bytes_read,
        "partial_sha256": partial_sha256,
        "partial_size_bytes": partial_size_bytes,
        "representation_header": representation_header,
        "header": representation_header,
        "first_failure": errors[0] if errors else None,
        "errors": errors,
    }
