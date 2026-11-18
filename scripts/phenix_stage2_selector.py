#!/usr/bin/env python3
"""Result-free Stage 2 PHENIX outer-loop candidate selector, holdout redactor, and trajectory verifier (U10/U08/U12).

Scope and epistemic boundary:
- Registration status remains ``selected_decisions_recorded`` (NOT ``frozen_result_free``).
- This module implements pure Python 3.12 standard-library validators and deterministic
  calculators for:
  1. Strict holdout-redacted public candidate and starting-model selection views
     (:func:`selection_view`, :func:`redact_candidate_for_selection`,
     :func:`redact_starting_geometry_for_selection`) that project a permissive private/audit
     envelope onto a fixed allowlist of typed non-holdout numeric measurements and
     holdout-independent provenance IDs/hashes before validating the public record.
     ``R_free`` and ``R_sleep`` (and any holdout aliases, raw logs, parameter blocks, or
     holdout-dependent raw log digests) are never part of the controller selection view.
  2. Outer-loop ``T05`` stereochemical guardrail eligibility (:func:`geometry_eligible`)
     using exact ``Decimal(str(value))`` arithmetic on the four approved ``U10`` formulas:
     - ``bond_rmsz <= max(start + 0.15, 1.0)``
     - ``angle_rmsz <= max(start + 0.20, 1.5)``
     - ``clashscore <= max(1.1 * start + 1, 15)``
     - ``rama_out_percent <= max(start + 0.5, 1.0)`` (explicit percent units in ``[0, 100]``).
     These guardrails govern study outer-loop candidate selection only and do NOT create
     registry-bound pass verdicts in ``ref/structural_criteria.yaml``.
  3. Deterministic permutation-invariant candidate selection (:func:`select_candidate`)
     over ``COMPLETED_COMMENSURABLE`` guard-passing moves by ``argmin R_work`` with
     ``<= 0.0005`` tie group broken by higher ``LLG_work`` and lower ``MolProbity`` score.
     Tie-group anchoring (``"anchored_at_min_r_work"``) and residual exact-tie handling
     (``"unresolved_tie"`` or ``"canonical_move_id_asc"``) are explicit implementation-policy
     parameters that the caller must bind; they remain unresolved study-policy slots and
     never default silently.
  4. Deterministic early-stopping evaluation (:func:`stop_decision`) checking U12 cumulative
     cap exhaustion alongside the two-consecutive-move stagnation rule
     (``delta_r_work > -0.0005`` and ``delta_clashscore >= -0.5``) under an explicit caller-bound
     reference convention (``"previous_move"``, ``"accepted_incumbent"``, or ``"start_model"``),
     recomputing deltas from bound source measurements without bridging failed moves or gaps.
  5. Offline trajectory receipt and replay verification (:func:`verify_trajectory`) checking
     contiguous move indexing, immutable target/flag/sleep/snapshot bindings, redacted-view
     canonical SHA-256 digests, mandatory U12 budget compliance and prefix cap-exhaustion
     checks via :mod:`phenix_stage2_runtime`, and deterministic selector/stop replay.
- Epistemic limits:
  - This module validates supplied data structures and receipts only; it does NOT prove
    OS/process isolation, whole-log text redaction outside the projected selection view,
    live admission-guard execution, or runtime correctness.
  - Runtime move-ledger completion fields describe moves only; scientific arm completion
    remains ``"not_assessed"``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import (
    Context,
    Decimal,
    DivisionByZero,
    Inexact,
    InvalidOperation,
    Overflow,
    ROUND_HALF_EVEN,
    Subnormal,
    Underflow,
)
import hashlib
import json
import math
import re
from typing import Any

from phenix_stage2_flags import (
    CANONICAL_SOURCE_LAYERS,
    COMMAND_SOURCE_LAYERS,
    verify_flag_generation_guard,
)
from phenix_stage2_runtime import (
    CONTROLLER_ARM_IDS,
    MAX_ELAPSED_SECONDS,
    MAX_MACRO_CYCLES,
    MAX_OUTER_MOVES,
    MAX_TOTAL_TOKENS,
    REGISTRATION_STATUS,
    U08_FAILURE_STATUS_CODES,
    U08_STATUS_CODES,
    UNAVAILABLE_EXECUTION_MARKERS,
    UNAVAILABLE_NOT_EXECUTED_MARKERS,
    verify_controller_budget,
)

STAGE2_SELECTOR_STATUS = "prospective_selector_contract_not_development_frozen"
EXECUTION_AUTHORIZED = False

COMPLETED_COMMENSURABLE_STATUS = U08_STATUS_CODES[0]
assert COMPLETED_COMMENSURABLE_STATUS == "COMPLETED_COMMENSURABLE"

CANDIDATE_METRIC_NAMES: tuple[str, ...] = (
    "r_work",
    "llg_work",
    "molprobity_score",
    "bond_rmsz",
    "angle_rmsz",
    "clashscore",
    "rama_out_percent",
)
GEOMETRY_METRIC_NAMES: tuple[str, ...] = (
    "bond_rmsz",
    "angle_rmsz",
    "clashscore",
    "rama_out_percent",
)
OPTIONAL_START_METRIC_NAMES: tuple[str, ...] = (
    "r_work",
    "llg_work",
    "molprobity_score",
)

EXPECTED_METRIC_UNITS: dict[str, str] = {
    "r_work": "fraction",
    "llg_work": "llg_units",
    "molprobity_score": "score",
    "bond_rmsz": "rmsz",
    "angle_rmsz": "rmsz",
    "clashscore": "clashes_per_1000_atoms",
    "rama_out_percent": "percent",
}

ALLOWED_TIE_GROUP_POLICIES: frozenset[str] = frozenset({"anchored_at_min_r_work"})
ALLOWED_RESIDUAL_TIE_POLICIES: frozenset[str] = frozenset(
    {"unresolved_tie", "canonical_move_id_asc"}
)
ALLOWED_STOP_REFERENCE_CONVENTIONS: frozenset[str] = frozenset(
    {"previous_move", "accepted_incumbent", "start_model"}
)

# Exact U10 decimal constants
BOND_RMSZ_DELTA_ALLOWANCE = Decimal("0.15")
BOND_RMSZ_FLOOR = Decimal("1.0")
ANGLE_RMSZ_DELTA_ALLOWANCE = Decimal("0.20")
ANGLE_RMSZ_FLOOR = Decimal("1.5")
CLASHSCORE_MULTIPLIER = Decimal("1.1")
CLASHSCORE_ADDEND = Decimal("1")
CLASHSCORE_FLOOR = Decimal("15")
RAMA_OUT_PERCENT_DELTA_ALLOWANCE = Decimal("0.5")
RAMA_OUT_PERCENT_FLOOR = Decimal("1.0")

R_WORK_TIE_TOLERANCE = Decimal("0.0005")
STOP_DELTA_R_WORK_STRICT_LOWER = Decimal("-0.0005")
STOP_DELTA_CLASHSCORE_LOWER = Decimal("-0.5")
STOP_CONSECUTIVE_MOVES_REQUIRED = 2

ALLOWED_METRIC_READOUT_KEYS: frozenset[str] = frozenset(
    {
        "value",
        "unit",
        "producer_id",
        "readout_id",
        "input_subject_sha256",
        "source_receipt_id",
    }
)

ALLOWED_READOUT_CONTRACT_SPEC_KEYS: frozenset[str] = frozenset(
    {
        "producer_id",
        "readout_id",
        "unit",
        "source_receipt_id",
    }
)

ALLOWED_PUBLIC_START_KEYS: frozenset[str] = frozenset(
    {
        "record_type",
        "subject_id",
        "target_id",
        "work_reflection_domain_sha256",
        "start_model_sha256",
        "metrics",
    }
)

ALLOWED_PUBLIC_CANDIDATE_KEYS: frozenset[str] = frozenset(
    {
        "record_type",
        "move_id",
        "move_index",
        "status",
        "subject_id",
        "target_id",
        "work_reflection_domain_sha256",
        "candidate_model_sha256",
        "metrics",
    }
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}\Z")
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_HOLDOUT_TOKEN_RE = re.compile(
    r"(?:r[_\-\s]*free|r[_\-\s]*sleep|free[_\-\s]*r|sleep[_\-\s]*r|holdout|test[_\-\s]*r)",
    re.IGNORECASE,
)
_RAW_AUDIT_METADATA_RE = re.compile(
    r"(?:^(?:audit|raw|log|private)[-_.:]|[0-9a-f]{16,})",
    re.IGNORECASE,
)


def _validate_sha256(value: Any, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or _SHA256_RE.fullmatch(value) is None
    ):
        raise ValueError(
            f"{field_name} must be an exact 64-character lowercase hex SHA-256 digest, "
            f"got {value!r}."
        )
    return value


def _validate_safe_id(value: Any, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or _SAFE_ID_RE.fullmatch(value) is None
    ):
        raise ValueError(
            f"{field_name} must be a restricted identifier matching {_SAFE_ID_RE.pattern!r} "
            f"(no whitespace or arbitrary prose), got {value!r}."
        )
    if _HOLDOUT_TOKEN_RE.search(value) is not None:
        raise ValueError(
            f"{field_name}={value!r} contains a forbidden holdout token (r_free / r_sleep / holdout)."
        )
    return value


def _validate_logical_metadata_id(value: Any, *, field_name: str) -> str:
    val = _validate_safe_id(value, field_name=field_name)
    if _RAW_AUDIT_METADATA_RE.search(val) is not None:
        raise ValueError(
            f"{field_name}={val!r} looks like a raw/audit receipt or embedded digest; "
            "public metric metadata must use fixed logical contract identifiers."
        )
    return val


def validate_readout_contract(
    readout_contract: Mapping[str, Any] | None = None,
) -> dict[str, dict[str, str]]:
    """Validate an explicit caller-bound out-of-band readout contract.

    Requires an explicit mapping supplied by the caller; ``None`` or implicit defaults
    are rejected. Binds declared metadata only (not actual measurement sourcing or
    frozen study/devfreeze policy).
    """
    if readout_contract is None or not isinstance(readout_contract, Mapping):
        raise ValueError(
            "readout_contract is an unresolved implementation-policy slot that must be "
            "explicitly bound out-of-band by the caller as a mapping; None/implicit defaults "
            "are forbidden."
        )
    source = readout_contract
    expected_metrics = set(CANDIDATE_METRIC_NAMES)
    unknown_metrics = sorted(set(source.keys()) - expected_metrics)
    if unknown_metrics:
        raise ValueError(
            f"readout_contract contains unknown metric keys: {unknown_metrics}."
        )
    missing_metrics = sorted(expected_metrics - set(source.keys()))
    if missing_metrics:
        raise ValueError(
            f"readout_contract is missing required metric keys: {missing_metrics}."
        )

    validated: dict[str, dict[str, str]] = {}
    for m_name in CANDIDATE_METRIC_NAMES:
        raw_spec = source[m_name]
        if not isinstance(raw_spec, Mapping):
            raise ValueError(
                f"readout_contract.{m_name} must be a mapping."
            )
        unknown_keys = sorted(
            set(raw_spec.keys()) - ALLOWED_READOUT_CONTRACT_SPEC_KEYS
        )
        if unknown_keys:
            raise ValueError(
                f"readout_contract.{m_name} contains unknown keys: {unknown_keys}."
            )
        missing_keys = sorted(
            ALLOWED_READOUT_CONTRACT_SPEC_KEYS - set(raw_spec.keys())
        )
        if missing_keys:
            raise ValueError(
                f"readout_contract.{m_name} is missing required keys: {missing_keys}."
            )
        expected_unit = EXPECTED_METRIC_UNITS[m_name]
        unit = raw_spec["unit"]
        if not isinstance(unit, str) or unit != expected_unit:
            raise ValueError(
                f"readout_contract.{m_name}.unit must be {expected_unit!r}, got {unit!r}."
            )
        producer_id = _validate_logical_metadata_id(
            raw_spec["producer_id"],
            field_name=f"readout_contract.{m_name}.producer_id",
        )
        readout_id = _validate_logical_metadata_id(
            raw_spec["readout_id"],
            field_name=f"readout_contract.{m_name}.readout_id",
        )
        source_receipt_id = _validate_logical_metadata_id(
            raw_spec["source_receipt_id"],
            field_name=f"readout_contract.{m_name}.source_receipt_id",
        )
        validated[m_name] = {
            "producer_id": producer_id,
            "readout_id": readout_id,
            "unit": unit,
            "source_receipt_id": source_receipt_id,
        }
    return validated


def _validate_strict_int(
    value: Any, *, field_name: str, min_value: int | None = None
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            f"{field_name} must be a strict int (not bool), got {value!r} ({type(value).__name__})."
        )
    if min_value is not None and value < min_value:
        raise ValueError(f"{field_name} must be >= {min_value}, got {value}.")
    return value


MAX_LOSSLESS_JSON_INT = 9_007_199_254_740_992  # 2**53 (exact IEEE-754 integer bound)

_ISOLATED_DECIMAL_CONTEXT = Context(
    prec=1200,
    rounding=ROUND_HALF_EVEN,
    Emax=999999,
    Emin=-999999,
    traps=[
        InvalidOperation,
        DivisionByZero,
        Overflow,
        Inexact,
        Subnormal,
        Underflow,
    ],
)


def _dec_add(a: Decimal, b: Decimal) -> Decimal:
    return _ISOLATED_DECIMAL_CONTEXT.add(a, b)


def _dec_sub(a: Decimal, b: Decimal) -> Decimal:
    return _ISOLATED_DECIMAL_CONTEXT.subtract(a, b)


def _dec_mul(a: Decimal, b: Decimal) -> Decimal:
    return _ISOLATED_DECIMAL_CONTEXT.multiply(a, b)


def _to_exact_decimal(
    value: Any,
    *,
    field_name: str,
    allow_negative: bool,
    max_value: Decimal | None = None,
) -> tuple[int | float, Decimal]:
    """Validate a finite numeric scalar in the lossless JSON numeric domain and convert via Decimal(str(public_value)).

    Lossless JSON numeric contract:
    - Rejects ``bool``, ``str``, ``None``, and non-finite numbers (``NaN``, ``inf``).
    - Ordinary ``int`` values must satisfy ``abs(value) <= 2**53`` (``MAX_LOSSLESS_JSON_INT``)
      so they never lose precision across IEEE-754 / JSON boundaries; their ``int`` type is
      preserved in ``MetricReadout.value`` and ``to_public_dict()``.
    - Ordinary finite ``float`` values are preserved as ``float`` (with ``-0.0`` normalized to
      ``0.0``) and interpreted as ``Decimal(str(public_val))``.
    - ``Decimal`` inputs are admitted ONLY when they are finite and round-trip losslessly
      through ``float(value)`` such that ``Decimal(str(float(value))) == value`` with
      identical decimal value; high-precision ``Decimal`` values that would round on
      ``to_public_dict()`` / JSON serialization are explicitly rejected.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(
            f"{field_name} must be a finite numeric value (not bool/str/None), "
            f"got {value!r} ({type(value).__name__})."
        )
    if isinstance(value, int):
        if abs(value) > MAX_LOSSLESS_JSON_INT:
            raise ValueError(
                f"{field_name}={value!r} exceeds MAX_LOSSLESS_JSON_INT ({MAX_LOSSLESS_JSON_INT}); "
                "large integers outside the lossless IEEE-754 / JSON domain are rejected."
            )
        public_val: int | float = 0 if value == 0 else int(value)
        dec_val = Decimal(str(public_val))
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{field_name} must be finite, got {value!r}.")
        public_val = 0.0 if value == 0.0 else float(value)
        dec_val = Decimal(str(public_val))
    else:
        if not value.is_finite():
            raise ValueError(f"{field_name} must be finite, got {value!r}.")
        try:
            f_val = float(value)
        except (OverflowError, ValueError) as exc:
            raise ValueError(
                f"{field_name}={value!r} cannot be represented as a finite JSON float."
            ) from exc
        if not math.isfinite(f_val):
            raise ValueError(
                f"{field_name}={value!r} overflows finite JSON float representation."
            )
        public_val = 0.0 if f_val == 0.0 else f_val
        roundtrip_dec = Decimal(str(public_val))
        if roundtrip_dec != value:
            raise ValueError(
                f"{field_name}={value!r} cannot round-trip losslessly through JSON float "
                f"representation (round-trip gave {roundtrip_dec!r}); unsupported high-precision "
                "Decimal inputs are rejected to preserve revalidation invariance."
            )
        dec_val = roundtrip_dec

    if not allow_negative and dec_val < Decimal("0"):
        raise ValueError(
            f"{field_name} must be non-negative (>= 0), got {value!r}."
        )
    if max_value is not None and dec_val > max_value:
        raise ValueError(
            f"{field_name} must be <= {max_value}, got {value!r}."
        )
    return public_val, dec_val


def canonical_json_bytes(record: Mapping[str, Any]) -> bytes:
    """Serialize a strict JSON mapping deterministically to UTF-8 bytes."""
    return json.dumps(
        record,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_json_sha256(record: Mapping[str, Any]) -> str:
    """Return the lowercase 64-hex SHA-256 digest of :func:`canonical_json_bytes`."""
    return hashlib.sha256(canonical_json_bytes(record)).hexdigest()


@dataclass(frozen=True)
class MetricReadout:
    """Typed public readout for a single non-holdout metric."""

    metric_name: str
    value: int | float
    decimal_value: Decimal
    unit: str
    producer_id: str
    readout_id: str
    input_subject_sha256: str
    source_receipt_id: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "unit": self.unit,
            "producer_id": self.producer_id,
            "readout_id": self.readout_id,
            "input_subject_sha256": self.input_subject_sha256,
            "source_receipt_id": self.source_receipt_id,
        }


@dataclass(frozen=True)
class StartingGeometryRecord:
    """Typed public starting-model measurement record for U10 eligibility and stopping."""

    subject_id: str
    target_id: str
    work_reflection_domain_sha256: str
    start_model_sha256: str
    metrics: dict[str, MetricReadout]

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "record_type": "starting_geometry_v1",
            "subject_id": self.subject_id,
            "target_id": self.target_id,
            "work_reflection_domain_sha256": self.work_reflection_domain_sha256,
            "start_model_sha256": self.start_model_sha256,
            "metrics": {
                k: self.metrics[k].to_public_dict()
                for k in sorted(self.metrics.keys())
            },
        }


@dataclass(frozen=True)
class CandidateSelectionRecord:
    """Typed public candidate-move selection record (holdout-free)."""

    move_id: str
    move_index: int
    status: str
    subject_id: str
    target_id: str
    work_reflection_domain_sha256: str
    candidate_model_sha256: str
    metrics: dict[str, MetricReadout]

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "record_type": "candidate_selection_v1",
            "move_id": self.move_id,
            "move_index": self.move_index,
            "status": self.status,
            "subject_id": self.subject_id,
            "target_id": self.target_id,
            "work_reflection_domain_sha256": self.work_reflection_domain_sha256,
            "candidate_model_sha256": self.candidate_model_sha256,
            "metrics": {
                k: self.metrics[k].to_public_dict()
                for k in sorted(self.metrics.keys())
            },
        }


def _validate_metric_readout(
    metric_name: str,
    raw_metric: Any,
    *,
    expected_subject_sha256: str,
    contract_spec: Mapping[str, str],
    field_prefix: str,
) -> MetricReadout:
    if not isinstance(raw_metric, Mapping):
        raise ValueError(f"{field_prefix}.{metric_name} must be a mapping.")
    unknown_keys = sorted(set(raw_metric.keys()) - ALLOWED_METRIC_READOUT_KEYS)
    if unknown_keys:
        raise ValueError(
            f"{field_prefix}.{metric_name} contains unknown or unredacted keys: {unknown_keys}."
        )
    missing_keys = sorted(ALLOWED_METRIC_READOUT_KEYS - set(raw_metric.keys()))
    if missing_keys:
        raise ValueError(
            f"{field_prefix}.{metric_name} is missing required keys: {missing_keys}."
        )

    expected_unit = EXPECTED_METRIC_UNITS[metric_name]
    raw_unit = raw_metric["unit"]
    if not isinstance(raw_unit, str) or raw_unit != expected_unit:
        raise ValueError(
            f"{field_prefix}.{metric_name}.unit must be {expected_unit!r}, got {raw_unit!r}."
        )
    if raw_unit != contract_spec["unit"]:
        raise ValueError(
            f"Readout contract mismatch on {field_prefix}.{metric_name}.unit: "
            f"got {raw_unit!r}, expected {contract_spec['unit']!r}."
        )

    allow_negative = metric_name == "llg_work"
    max_val = Decimal("100") if metric_name == "rama_out_percent" else None
    f_val, dec_val = _to_exact_decimal(
        raw_metric["value"],
        field_name=f"{field_prefix}.{metric_name}.value",
        allow_negative=allow_negative,
        max_value=max_val,
    )

    producer_id = _validate_safe_id(
        raw_metric["producer_id"],
        field_name=f"{field_prefix}.{metric_name}.producer_id",
    )
    if (
        producer_id != contract_spec["producer_id"]
        or _RAW_AUDIT_METADATA_RE.search(producer_id) is not None
    ):
        raise ValueError(
            f"Readout contract mismatch on {field_prefix}.{metric_name}.producer_id: "
            f"got {producer_id!r}, expected caller-bound contract value "
            f"{contract_spec['producer_id']!r} (unbound or raw/audit metadata identifiers are forbidden)."
        )

    readout_id = _validate_safe_id(
        raw_metric["readout_id"],
        field_name=f"{field_prefix}.{metric_name}.readout_id",
    )
    if (
        readout_id != contract_spec["readout_id"]
        or _RAW_AUDIT_METADATA_RE.search(readout_id) is not None
    ):
        raise ValueError(
            f"Readout contract mismatch on {field_prefix}.{metric_name}.readout_id: "
            f"got {readout_id!r}, expected caller-bound contract value "
            f"{contract_spec['readout_id']!r} (unbound or raw/audit metadata identifiers are forbidden)."
        )

    input_subject_sha = _validate_sha256(
        raw_metric["input_subject_sha256"],
        field_name=f"{field_prefix}.{metric_name}.input_subject_sha256",
    )
    if input_subject_sha != expected_subject_sha256:
        raise ValueError(
            f"{field_prefix}.{metric_name}.input_subject_sha256 ({input_subject_sha}) "
            f"does not match record model SHA-256 ({expected_subject_sha256})."
        )

    source_receipt_id = _validate_safe_id(
        raw_metric["source_receipt_id"],
        field_name=f"{field_prefix}.{metric_name}.source_receipt_id",
    )
    if (
        source_receipt_id != contract_spec["source_receipt_id"]
        or _RAW_AUDIT_METADATA_RE.search(source_receipt_id) is not None
    ):
        raise ValueError(
            f"Readout contract mismatch on {field_prefix}.{metric_name}.source_receipt_id: "
            f"got {source_receipt_id!r}, expected caller-bound contract value "
            f"{contract_spec['source_receipt_id']!r} (unbound or raw/audit metadata identifiers are forbidden)."
        )

    return MetricReadout(
        metric_name=metric_name,
        value=f_val,
        decimal_value=dec_val,
        unit=raw_unit,
        producer_id=producer_id,
        readout_id=readout_id,
        input_subject_sha256=input_subject_sha,
        source_receipt_id=source_receipt_id,
    )


def validate_starting_geometry_record(
    record: Mapping[str, Any] | StartingGeometryRecord,
    *,
    field_prefix: str = "start_record",
    readout_contract: Mapping[str, Any] | None = None,
) -> StartingGeometryRecord:
    """Strictly validate a public starting-model geometry/metric record (rejecting extra fields)."""
    validated_contract = validate_readout_contract(readout_contract)
    if isinstance(record, StartingGeometryRecord):
        return validate_starting_geometry_record(
            record.to_public_dict(),
            field_prefix=field_prefix,
            readout_contract=validated_contract,
        )
    if not isinstance(record, Mapping):
        raise ValueError(f"{field_prefix} must be a mapping.")

    unknown_keys = sorted(set(record.keys()) - ALLOWED_PUBLIC_START_KEYS)
    if unknown_keys:
        raise ValueError(
            f"{field_prefix} contains unknown or unredacted keys: {unknown_keys}."
        )
    required_top = {
        "subject_id",
        "target_id",
        "work_reflection_domain_sha256",
        "start_model_sha256",
        "metrics",
    }
    missing_top = sorted(required_top - set(record.keys()))
    if missing_top:
        raise ValueError(
            f"{field_prefix} is missing required keys: {missing_top}."
        )
    if (
        "record_type" in record
        and record["record_type"] != "starting_geometry_v1"
    ):
        raise ValueError(
            f"{field_prefix}.record_type must be 'starting_geometry_v1', "
            f"got {record['record_type']!r}."
        )

    subject_id = _validate_safe_id(
        record["subject_id"], field_name=f"{field_prefix}.subject_id"
    )
    target_id = _validate_safe_id(
        record["target_id"], field_name=f"{field_prefix}.target_id"
    )
    work_domain_sha = _validate_sha256(
        record["work_reflection_domain_sha256"],
        field_name=f"{field_prefix}.work_reflection_domain_sha256",
    )
    start_model_sha = _validate_sha256(
        record["start_model_sha256"],
        field_name=f"{field_prefix}.start_model_sha256",
    )

    raw_metrics = record["metrics"]
    if not isinstance(raw_metrics, Mapping):
        raise ValueError(f"{field_prefix}.metrics must be a mapping.")

    allowed_start_metrics = set(GEOMETRY_METRIC_NAMES) | set(
        OPTIONAL_START_METRIC_NAMES
    )
    unknown_metrics = sorted(set(raw_metrics.keys()) - allowed_start_metrics)
    if unknown_metrics:
        raise ValueError(
            f"{field_prefix}.metrics contains unknown or forbidden metric keys: {unknown_metrics}."
        )
    missing_geom = sorted(set(GEOMETRY_METRIC_NAMES) - set(raw_metrics.keys()))
    if missing_geom:
        raise ValueError(
            f"{field_prefix}.metrics is missing required U10 geometry metrics: {missing_geom}."
        )

    validated_metrics: dict[str, MetricReadout] = {}
    for m_name in sorted(raw_metrics.keys()):
        validated_metrics[m_name] = _validate_metric_readout(
            m_name,
            raw_metrics[m_name],
            expected_subject_sha256=start_model_sha,
            contract_spec=validated_contract[m_name],
            field_prefix=f"{field_prefix}.metrics",
        )

    return StartingGeometryRecord(
        subject_id=subject_id,
        target_id=target_id,
        work_reflection_domain_sha256=work_domain_sha,
        start_model_sha256=start_model_sha,
        metrics=validated_metrics,
    )


def validate_public_candidate_record(
    record: Mapping[str, Any] | CandidateSelectionRecord,
    *,
    field_prefix: str = "candidate_record",
    readout_contract: Mapping[str, Any] | None = None,
) -> CandidateSelectionRecord:
    """Strictly validate a public candidate selection record (rejecting any extra or holdout fields)."""
    validated_contract = validate_readout_contract(readout_contract)
    if isinstance(record, CandidateSelectionRecord):
        return validate_public_candidate_record(
            record.to_public_dict(),
            field_prefix=field_prefix,
            readout_contract=validated_contract,
        )
    if not isinstance(record, Mapping):
        raise ValueError(f"{field_prefix} must be a mapping.")

    unknown_keys = sorted(set(record.keys()) - ALLOWED_PUBLIC_CANDIDATE_KEYS)
    if unknown_keys:
        raise ValueError(
            f"{field_prefix} contains unknown or unredacted keys: {unknown_keys}."
        )
    required_top = {
        "move_id",
        "move_index",
        "status",
        "subject_id",
        "target_id",
        "work_reflection_domain_sha256",
        "candidate_model_sha256",
        "metrics",
    }
    missing_top = sorted(required_top - set(record.keys()))
    if missing_top:
        raise ValueError(
            f"{field_prefix} is missing required keys: {missing_top}."
        )
    if (
        "record_type" in record
        and record["record_type"] != "candidate_selection_v1"
    ):
        raise ValueError(
            f"{field_prefix}.record_type must be 'candidate_selection_v1', "
            f"got {record['record_type']!r}."
        )

    move_id = _validate_safe_id(
        record["move_id"], field_name=f"{field_prefix}.move_id"
    )
    move_index = _validate_strict_int(
        record["move_index"],
        field_name=f"{field_prefix}.move_index",
        min_value=1,
    )
    status = record["status"]
    if not isinstance(status, str) or status not in U08_STATUS_CODES:
        raise ValueError(
            f"{field_prefix}.status must be one of canonical U08_STATUS_CODES "
            f"{U08_STATUS_CODES}, got {status!r}."
        )
    if status != COMPLETED_COMMENSURABLE_STATUS:
        raise ValueError(
            f"{field_prefix} with status={status!r} cannot form a selectable public "
            f"CandidateSelectionRecord (requires {COMPLETED_COMMENSURABLE_STATUS!r})."
        )

    subject_id = _validate_safe_id(
        record["subject_id"], field_name=f"{field_prefix}.subject_id"
    )
    target_id = _validate_safe_id(
        record["target_id"], field_name=f"{field_prefix}.target_id"
    )
    work_domain_sha = _validate_sha256(
        record["work_reflection_domain_sha256"],
        field_name=f"{field_prefix}.work_reflection_domain_sha256",
    )
    candidate_model_sha = _validate_sha256(
        record["candidate_model_sha256"],
        field_name=f"{field_prefix}.candidate_model_sha256",
    )

    raw_metrics = record["metrics"]
    if not isinstance(raw_metrics, Mapping):
        raise ValueError(f"{field_prefix}.metrics must be a mapping.")
    expected_metrics = set(CANDIDATE_METRIC_NAMES)
    unknown_metrics = sorted(set(raw_metrics.keys()) - expected_metrics)
    if unknown_metrics:
        raise ValueError(
            f"{field_prefix}.metrics contains unknown or unredacted metric keys: {unknown_metrics}."
        )
    missing_metrics = sorted(expected_metrics - set(raw_metrics.keys()))
    if missing_metrics:
        raise ValueError(
            f"{field_prefix}.metrics is missing required candidate metrics: {missing_metrics}."
        )

    validated_metrics: dict[str, MetricReadout] = {}
    for m_name in CANDIDATE_METRIC_NAMES:
        validated_metrics[m_name] = _validate_metric_readout(
            m_name,
            raw_metrics[m_name],
            expected_subject_sha256=candidate_model_sha,
            contract_spec=validated_contract[m_name],
            field_prefix=f"{field_prefix}.metrics",
        )

    return CandidateSelectionRecord(
        move_id=move_id,
        move_index=move_index,
        status=status,
        subject_id=subject_id,
        target_id=target_id,
        work_reflection_domain_sha256=work_domain_sha,
        candidate_model_sha256=candidate_model_sha,
        metrics=validated_metrics,
    )


def _project_metric_slot(
    raw_metric: Any,
    *,
    contract_spec: Mapping[str, str],
    field_prefix: str,
) -> dict[str, Any]:
    if not isinstance(raw_metric, Mapping):
        raise ValueError(f"{field_prefix} must be a mapping.")
    required_envelope_keys = {"value", "input_subject_sha256"}
    missing = sorted(required_envelope_keys - set(raw_metric.keys()))
    if missing:
        raise ValueError(f"{field_prefix} is missing required keys: {missing}.")

    if "unit" in raw_metric and raw_metric["unit"] is not None:
        raw_unit = raw_metric["unit"]
        if not isinstance(raw_unit, str) or raw_unit != contract_spec["unit"]:
            raise ValueError(
                f"{field_prefix}.unit must be {contract_spec['unit']!r}, got {raw_unit!r}."
            )

    for meta_key in ("producer_id", "readout_id", "source_receipt_id"):
        if meta_key in raw_metric and raw_metric[meta_key] is not None:
            val = _validate_safe_id(
                raw_metric[meta_key],
                field_name=f"{field_prefix}.{meta_key}",
            )
            if (
                val != contract_spec[meta_key]
                or _RAW_AUDIT_METADATA_RE.search(val) is not None
            ):
                raise ValueError(
                    f"Readout contract mismatch on {field_prefix}.{meta_key}: "
                    f"got {val!r}, expected caller-bound contract value "
                    f"{contract_spec[meta_key]!r} (unbound or raw/audit metadata identifiers are forbidden)."
                )

    return {
        "value": raw_metric["value"],
        "unit": contract_spec["unit"],
        "producer_id": contract_spec["producer_id"],
        "readout_id": contract_spec["readout_id"],
        "input_subject_sha256": raw_metric["input_subject_sha256"],
        "source_receipt_id": contract_spec["source_receipt_id"],
    }


def redact_starting_geometry_for_selection(
    private_record: Mapping[str, Any],
    *,
    readout_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project a permissive private starting-model envelope to the allowlisted public view, then validate."""
    validated_contract = validate_readout_contract(readout_contract)
    if not isinstance(private_record, Mapping):
        raise ValueError("private_record must be a mapping.")
    for req_key in (
        "subject_id",
        "target_id",
        "work_reflection_domain_sha256",
        "start_model_sha256",
        "metrics",
    ):
        if req_key not in private_record:
            raise ValueError(
                f"private starting-model envelope is missing required field {req_key!r}."
            )
    raw_metrics = private_record["metrics"]
    if not isinstance(raw_metrics, Mapping):
        raise ValueError("private starting-model envelope 'metrics' must be a mapping.")

    projected_metrics: dict[str, dict[str, Any]] = {}
    for m_name in GEOMETRY_METRIC_NAMES:
        if m_name not in raw_metrics:
            raise ValueError(
                f"private starting-model envelope is missing required geometry metric {m_name!r}."
            )
        projected_metrics[m_name] = _project_metric_slot(
            raw_metrics[m_name],
            contract_spec=validated_contract[m_name],
            field_prefix=f"start_record.metrics.{m_name}",
        )
    for opt_name in OPTIONAL_START_METRIC_NAMES:
        if opt_name in raw_metrics and raw_metrics[opt_name] is not None:
            projected_metrics[opt_name] = _project_metric_slot(
                raw_metrics[opt_name],
                contract_spec=validated_contract[opt_name],
                field_prefix=f"start_record.metrics.{opt_name}",
            )

    projected = {
        "record_type": "starting_geometry_v1",
        "subject_id": private_record["subject_id"],
        "target_id": private_record["target_id"],
        "work_reflection_domain_sha256": private_record[
            "work_reflection_domain_sha256"
        ],
        "start_model_sha256": private_record["start_model_sha256"],
        "metrics": projected_metrics,
    }
    validated = validate_starting_geometry_record(
        projected, readout_contract=validated_contract
    )
    public_dict = validated.to_public_dict()
    return {
        "record": validated,
        "public_view": public_dict,
        "redacted_view_sha256": canonical_json_sha256(public_dict),
    }


def redact_candidate_for_selection(
    private_record: Mapping[str, Any],
    *,
    readout_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Project a permissive private candidate-move envelope onto the fixed allowlist, then validate.

    Extracts ONLY the allowlisted non-holdout fields first (dropping ``r_free``, ``r_sleep``,
    nested logs, arbitrary text, parameter blocks, and raw log digests), then strictly validates
    the projected public record against ``readout_contract``.
    """
    validated_contract = validate_readout_contract(readout_contract)
    if not isinstance(private_record, Mapping):
        raise ValueError("private_record must be a mapping.")
    for req_key in (
        "move_id",
        "move_index",
        "status",
        "subject_id",
        "target_id",
        "work_reflection_domain_sha256",
        "candidate_model_sha256",
        "metrics",
    ):
        if req_key not in private_record:
            raise ValueError(
                f"private candidate envelope is missing required field {req_key!r}."
            )
    raw_metrics = private_record["metrics"]
    if not isinstance(raw_metrics, Mapping):
        raise ValueError("private candidate envelope 'metrics' must be a mapping.")

    projected_metrics: dict[str, dict[str, Any]] = {}
    for m_name in CANDIDATE_METRIC_NAMES:
        if m_name not in raw_metrics:
            raise ValueError(
                f"private candidate envelope is missing required non-holdout metric {m_name!r}."
            )
        projected_metrics[m_name] = _project_metric_slot(
            raw_metrics[m_name],
            contract_spec=validated_contract[m_name],
            field_prefix=f"candidate_record.metrics.{m_name}",
        )

    projected = {
        "record_type": "candidate_selection_v1",
        "move_id": private_record["move_id"],
        "move_index": private_record["move_index"],
        "status": private_record["status"],
        "subject_id": private_record["subject_id"],
        "target_id": private_record["target_id"],
        "work_reflection_domain_sha256": private_record[
            "work_reflection_domain_sha256"
        ],
        "candidate_model_sha256": private_record["candidate_model_sha256"],
        "metrics": projected_metrics,
    }
    validated = validate_public_candidate_record(
        projected, readout_contract=validated_contract
    )
    public_dict = validated.to_public_dict()
    return {
        "record": validated,
        "public_view": public_dict,
        "redacted_view_sha256": canonical_json_sha256(public_dict),
    }


def selection_view(
    private_record: Mapping[str, Any],
    *,
    kind: str = "candidate",
    readout_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the holdout-redacted public selection view and its canonical JSON SHA-256 digest."""
    if kind == "candidate":
        return redact_candidate_for_selection(
            private_record, readout_contract=readout_contract
        )
    if kind == "start":
        return redact_starting_geometry_for_selection(
            private_record, readout_contract=readout_contract
        )
    raise ValueError(
        f"kind must be 'candidate' or 'start', got {kind!r}."
    )


def _assert_matching_metric_contract(
    m1: MetricReadout,
    m2: MetricReadout,
    *,
    context_label: str,
) -> None:
    if (
        m1.producer_id != m2.producer_id
        or m1.readout_id != m2.readout_id
        or m1.unit != m2.unit
        or m1.source_receipt_id != m2.source_receipt_id
    ):
        raise ValueError(
            f"Readout contract mismatch on metric {m1.metric_name!r} ({context_label}): "
            f"({m1.producer_id!r}, {m1.readout_id!r}, {m1.unit!r}, {m1.source_receipt_id!r}) vs "
            f"({m2.producer_id!r}, {m2.readout_id!r}, {m2.unit!r}, {m2.source_receipt_id!r})."
        )


def _assert_same_subject_lineage(
    cand: CandidateSelectionRecord,
    start: StartingGeometryRecord,
) -> None:
    if cand.target_id != start.target_id:
        raise ValueError(
            f"Candidate {cand.move_id!r} target_id ({cand.target_id!r}) does not match "
            f"start target_id ({start.target_id!r})."
        )
    if cand.subject_id != start.subject_id:
        raise ValueError(
            f"Candidate {cand.move_id!r} subject_id ({cand.subject_id!r}) does not match "
            f"start subject_id ({start.subject_id!r})."
        )
    if (
        cand.work_reflection_domain_sha256
        != start.work_reflection_domain_sha256
    ):
        raise ValueError(
            f"Candidate {cand.move_id!r} work_reflection_domain_sha256 "
            f"({cand.work_reflection_domain_sha256}) does not match start "
            f"({start.work_reflection_domain_sha256})."
        )


def geometry_eligible(
    candidate: Mapping[str, Any] | CandidateSelectionRecord,
    start: Mapping[str, Any] | StartingGeometryRecord,
    *,
    readout_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate U10 outer-loop T05 stereochemical guardrails in exact Decimal arithmetic.

    Guardrails relative to ``start``:
    - ``bond_rmsz <= max(start.bond_rmsz + 0.15, 1.0)``
    - ``angle_rmsz <= max(start.angle_rmsz + 0.20, 1.5)``
    - ``clashscore <= max(1.1 * start.clashscore + 1, 15)``
    - ``rama_out_percent <= max(start.rama_out_percent + 0.5, 1.0)``

    Requires matching ``target_id``, ``subject_id``, ``work_reflection_domain_sha256``, and
    matching ``(producer_id, readout_id, unit, source_receipt_id)`` bound to ``readout_contract``
    across all four geometry metrics between ``candidate`` and ``start``. Study selection only;
    not a registry verdict.
    """
    validated_contract = validate_readout_contract(readout_contract)
    start_rec = validate_starting_geometry_record(
        start, readout_contract=validated_contract
    )
    cand_rec = validate_public_candidate_record(
        candidate, readout_contract=validated_contract
    )
    _assert_same_subject_lineage(cand_rec, start_rec)

    for g_name in GEOMETRY_METRIC_NAMES:
        _assert_matching_metric_contract(
            cand_rec.metrics[g_name],
            start_rec.metrics[g_name],
            context_label=f"candidate {cand_rec.move_id!r} vs start",
        )
    for opt_name in OPTIONAL_START_METRIC_NAMES:
        if opt_name in start_rec.metrics:
            _assert_matching_metric_contract(
                cand_rec.metrics[opt_name],
                start_rec.metrics[opt_name],
                context_label=f"candidate {cand_rec.move_id!r} vs start",
            )

    s_bond = start_rec.metrics["bond_rmsz"].decimal_value
    s_angle = start_rec.metrics["angle_rmsz"].decimal_value
    s_clash = start_rec.metrics["clashscore"].decimal_value
    s_rama = start_rec.metrics["rama_out_percent"].decimal_value

    c_bond = cand_rec.metrics["bond_rmsz"].decimal_value
    c_angle = cand_rec.metrics["angle_rmsz"].decimal_value
    c_clash = cand_rec.metrics["clashscore"].decimal_value
    c_rama = cand_rec.metrics["rama_out_percent"].decimal_value

    bond_cap = max(_dec_add(s_bond, BOND_RMSZ_DELTA_ALLOWANCE), BOND_RMSZ_FLOOR)
    angle_cap = max(_dec_add(s_angle, ANGLE_RMSZ_DELTA_ALLOWANCE), ANGLE_RMSZ_FLOOR)
    clash_cap = max(
        _dec_add(_dec_mul(CLASHSCORE_MULTIPLIER, s_clash), CLASHSCORE_ADDEND),
        CLASHSCORE_FLOOR,
    )
    rama_cap = max(
        _dec_add(s_rama, RAMA_OUT_PERCENT_DELTA_ALLOWANCE),
        RAMA_OUT_PERCENT_FLOOR,
    )

    checks = {
        "bond_rmsz": {
            "candidate": str(c_bond),
            "start": str(s_bond),
            "cap": str(bond_cap),
            "passed": bool(c_bond <= bond_cap),
        },
        "angle_rmsz": {
            "candidate": str(c_angle),
            "start": str(s_angle),
            "cap": str(angle_cap),
            "passed": bool(c_angle <= angle_cap),
        },
        "clashscore": {
            "candidate": str(c_clash),
            "start": str(s_clash),
            "cap": str(clash_cap),
            "passed": bool(c_clash <= clash_cap),
        },
        "rama_out_percent": {
            "candidate": str(c_rama),
            "start": str(s_rama),
            "cap": str(rama_cap),
            "passed": bool(c_rama <= rama_cap),
        },
    }
    failed_guards = tuple(
        g_name for g_name in GEOMETRY_METRIC_NAMES if not checks[g_name]["passed"]
    )
    eligible = len(failed_guards) == 0

    return {
        "eligible": eligible,
        "move_id": cand_rec.move_id,
        "move_index": cand_rec.move_index,
        "status": cand_rec.status,
        "failed_guards": failed_guards,
        "guard_checks": checks,
        "scope_note": (
            "Study outer-loop U10 geometry guardrail evaluation only; "
            "does not create a registry-bound pass verdict."
        ),
    }


def _validate_policy_choice(
    value: Any, *, allowed: frozenset[str], field_name: str
) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(
            f"{field_name} is an unresolved implementation-policy slot that must be "
            f"explicitly bound by the caller to one of {sorted(allowed)}, got {value!r}."
        )
    return value


def _validate_candidate_header_and_lineage(
    raw_cand: Mapping[str, Any] | CandidateSelectionRecord,
    *,
    start_rec: StartingGeometryRecord,
    validated_contract: Mapping[str, Mapping[str, str]],
    field_prefix: str,
) -> tuple[str, int, str]:
    """Validate candidate header and supplied lineage fields uniformly for Mapping and CandidateSelectionRecord."""
    if isinstance(raw_cand, CandidateSelectionRecord):
        raw_move_id: Any = raw_cand.move_id
        raw_move_index: Any = raw_cand.move_index
        raw_status: Any = raw_cand.status
        raw_target_id: Any = raw_cand.target_id
        raw_subject_id: Any = raw_cand.subject_id
        raw_work_domain_sha: Any = raw_cand.work_reflection_domain_sha256
        raw_cand_model_sha: Any = raw_cand.candidate_model_sha256
        raw_metrics: Any = raw_cand.metrics
    elif isinstance(raw_cand, Mapping):
        unknown_keys = sorted(
            set(raw_cand.keys()) - ALLOWED_PUBLIC_CANDIDATE_KEYS
        )
        if unknown_keys:
            raise ValueError(
                f"{field_prefix} contains unknown or unredacted keys: {unknown_keys}."
            )
        if (
            "record_type" in raw_cand
            and raw_cand["record_type"] is not None
            and raw_cand["record_type"] != "candidate_selection_v1"
        ):
            raise ValueError(
                f"{field_prefix}.record_type must be 'candidate_selection_v1', "
                f"got {raw_cand['record_type']!r}."
            )
        if (
            "move_id" not in raw_cand
            or "move_index" not in raw_cand
            or "status" not in raw_cand
        ):
            raise ValueError(
                f"{field_prefix} must specify 'move_id', 'move_index', and 'status'."
            )
        raw_move_id = raw_cand["move_id"]
        raw_move_index = raw_cand["move_index"]
        raw_status = raw_cand["status"]
        raw_target_id = raw_cand.get("target_id")
        raw_subject_id = raw_cand.get("subject_id")
        raw_work_domain_sha = raw_cand.get("work_reflection_domain_sha256")
        raw_cand_model_sha = raw_cand.get("candidate_model_sha256")
        raw_metrics = raw_cand.get("metrics")
    else:
        raise ValueError(
            f"{field_prefix} must be a mapping or CandidateSelectionRecord."
        )

    move_id = _validate_safe_id(
        raw_move_id, field_name=f"{field_prefix}.move_id"
    )
    move_index = _validate_strict_int(
        raw_move_index, field_name=f"{field_prefix}.move_index", min_value=1
    )
    if not isinstance(raw_status, str) or raw_status not in U08_STATUS_CODES:
        raise ValueError(
            f"{field_prefix}.status must be one of {U08_STATUS_CODES}, got {raw_status!r}."
        )
    cand_status = raw_status

    if raw_target_id is not None:
        val_target_id = _validate_safe_id(
            raw_target_id, field_name=f"{field_prefix}.target_id"
        )
        if val_target_id != start_rec.target_id:
            raise ValueError(
                f"{field_prefix}.target_id ({val_target_id!r}) does not match "
                f"start target_id ({start_rec.target_id!r})."
            )
    if raw_subject_id is not None:
        val_subject_id = _validate_safe_id(
            raw_subject_id, field_name=f"{field_prefix}.subject_id"
        )
        if val_subject_id != start_rec.subject_id:
            raise ValueError(
                f"{field_prefix}.subject_id ({val_subject_id!r}) does not match "
                f"start subject_id ({start_rec.subject_id!r})."
            )
    if raw_work_domain_sha is not None:
        val_work_domain_sha = _validate_sha256(
            raw_work_domain_sha,
            field_name=f"{field_prefix}.work_reflection_domain_sha256",
        )
        if val_work_domain_sha != start_rec.work_reflection_domain_sha256:
            raise ValueError(
                f"{field_prefix}.work_reflection_domain_sha256 ({val_work_domain_sha!r}) "
                f"does not match start ({start_rec.work_reflection_domain_sha256!r})."
            )
    val_cand_model_sha: str | None = None
    if raw_cand_model_sha is not None:
        val_cand_model_sha = _validate_sha256(
            raw_cand_model_sha,
            field_name=f"{field_prefix}.candidate_model_sha256",
        )

    if cand_status != COMPLETED_COMMENSURABLE_STATUS and raw_metrics is not None:
        if not isinstance(raw_metrics, Mapping):
            raise ValueError(
                f"{field_prefix}.metrics must be a mapping or None when supplied on a failed move."
            )
        unknown_m = sorted(set(raw_metrics.keys()) - set(CANDIDATE_METRIC_NAMES))
        if unknown_m:
            raise ValueError(
                f"{field_prefix}.metrics contains unknown or unredacted metric keys: {unknown_m}."
            )
        for m_name, m_val in raw_metrics.items():
            if isinstance(m_val, MetricReadout):
                m_dict = m_val.to_public_dict()
            else:
                m_dict = m_val
            if val_cand_model_sha is None:
                raise ValueError(
                    f"{field_prefix} supplies metric {m_name!r} without candidate_model_sha256."
                )
            _validate_metric_readout(
                m_name,
                m_dict,
                expected_subject_sha256=val_cand_model_sha,
                contract_spec=validated_contract[m_name],
                field_prefix=f"{field_prefix}.metrics",
            )

    return move_id, move_index, cand_status


def select_candidate(
    candidates: Sequence[Mapping[str, Any] | CandidateSelectionRecord],
    start: Mapping[str, Any] | StartingGeometryRecord,
    *,
    tie_group_policy: str | None = None,
    residual_tie_policy: str | None = None,
    readout_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Deterministically select the best outer-loop candidate move under U10 rules.

    - Caller must explicitly bind ``tie_group_policy='anchored_at_min_r_work'`` and
      ``residual_tie_policy`` in ``{'unresolved_tie', 'canonical_move_id_asc'}``.
    - Non-``COMPLETED_COMMENSURABLE`` move records in ``candidates`` are recorded as
      ineligible by status and never fabricated into selectable candidates.
    - All ``COMPLETED_COMMENSURABLE`` candidates must share the same ``target_id``,
      ``subject_id``, ``work_reflection_domain_sha256``, and identical
      ``(producer_id, readout_id, unit, source_receipt_id)`` contracts across all 7
      candidate metrics bound to ``readout_contract``.
    - Selection is strictly permutation-invariant over the input sequence.
    """
    validated_tie_policy = _validate_policy_choice(
        tie_group_policy,
        allowed=ALLOWED_TIE_GROUP_POLICIES,
        field_name="tie_group_policy",
    )
    validated_residual_policy = _validate_policy_choice(
        residual_tie_policy,
        allowed=ALLOWED_RESIDUAL_TIE_POLICIES,
        field_name="residual_tie_policy",
    )
    validated_contract = validate_readout_contract(readout_contract)
    start_rec = validate_starting_geometry_record(
        start, readout_contract=validated_contract
    )

    if isinstance(candidates, (str, bytes, Mapping)) or not isinstance(
        candidates, Sequence
    ):
        raise ValueError("candidates must be a sequence of candidate move records.")

    seen_move_ids: set[str] = set()
    seen_move_indices: set[int] = set()
    commensurable_records: list[CandidateSelectionRecord] = []
    ineligible_by_status: list[dict[str, Any]] = []

    for idx, raw_cand in enumerate(candidates):
        prefix = f"candidates[{idx}]"
        move_id, move_index, cand_status = _validate_candidate_header_and_lineage(
            raw_cand,
            start_rec=start_rec,
            validated_contract=validated_contract,
            field_prefix=prefix,
        )

        if move_id in seen_move_ids:
            raise ValueError(f"Duplicate move_id {move_id!r} in candidates.")
        if move_index in seen_move_indices:
            raise ValueError(f"Duplicate move_index {move_index} in candidates.")
        seen_move_ids.add(move_id)
        seen_move_indices.add(move_index)

        if cand_status != COMPLETED_COMMENSURABLE_STATUS:
            ineligible_by_status.append(
                {
                    "move_id": move_id,
                    "move_index": move_index,
                    "status": cand_status,
                    "reason": f"status={cand_status!r} != {COMPLETED_COMMENSURABLE_STATUS!r}",
                }
            )
            continue

        cand_rec = validate_public_candidate_record(
            raw_cand,
            field_prefix=prefix,
            readout_contract=validated_contract,
        )
        _assert_same_subject_lineage(cand_rec, start_rec)
        commensurable_records.append(cand_rec)

    # Sort canonically by move_id so contract validation and evaluation are permutation-invariant
    commensurable_sorted = sorted(commensurable_records, key=lambda r: r.move_id)
    if commensurable_sorted:
        anchor_contract_rec = commensurable_sorted[0]
        for other_rec in commensurable_sorted[1:]:
            for m_name in CANDIDATE_METRIC_NAMES:
                _assert_matching_metric_contract(
                    other_rec.metrics[m_name],
                    anchor_contract_rec.metrics[m_name],
                    context_label=(
                        f"candidate {other_rec.move_id!r} vs {anchor_contract_rec.move_id!r}"
                    ),
                )

    eligible_records: list[CandidateSelectionRecord] = []
    ineligible_by_geometry: list[dict[str, Any]] = []
    eligibility_by_move_id: dict[str, dict[str, Any]] = {}

    for cand_rec in commensurable_sorted:
        elig_res = geometry_eligible(
            cand_rec, start_rec, readout_contract=validated_contract
        )
        eligibility_by_move_id[cand_rec.move_id] = elig_res
        if elig_res["eligible"]:
            eligible_records.append(cand_rec)
        else:
            ineligible_by_geometry.append(
                {
                    "move_id": cand_rec.move_id,
                    "move_index": cand_rec.move_index,
                    "failed_guards": elig_res["failed_guards"],
                }
            )

    ineligible_by_status_sorted = tuple(
        sorted(ineligible_by_status, key=lambda d: d["move_id"])
    )
    ineligible_by_geometry_sorted = tuple(
        sorted(ineligible_by_geometry, key=lambda d: d["move_id"])
    )

    if not eligible_records:
        return {
            "selection_state": "no_eligible_candidate",
            "selected_move_id": None,
            "selected_move_index": None,
            "selected_candidate": None,
            "tied_move_ids": (),
            "tie_group_move_ids": (),
            "eligible_move_ids": (),
            "ineligible_by_status": ineligible_by_status_sorted,
            "ineligible_by_geometry": ineligible_by_geometry_sorted,
            "eligibility_by_move_id": eligibility_by_move_id,
            "tie_group_policy": validated_tie_policy,
            "residual_tie_policy": validated_residual_policy,
            "policy_status_note": (
                "tie_group_policy and residual_tie_policy are caller-bound implementation "
                "parameters for testing/replay and do not establish frozen study policy."
            ),
            "registration_status": REGISTRATION_STATUS,
            "stage2_status": STAGE2_SELECTOR_STATUS,
            "executed": False,
        }

    min_r_work = min(
        c.metrics["r_work"].decimal_value for c in eligible_records
    )
    tie_group = [
        c
        for c in eligible_records
        if _dec_sub(c.metrics["r_work"].decimal_value, min_r_work)
        <= R_WORK_TIE_TOLERANCE
    ]
    tie_group_ids = tuple(c.move_id for c in tie_group)

    max_llg = max(c.metrics["llg_work"].decimal_value for c in tie_group)
    llg_winners = [
        c for c in tie_group if c.metrics["llg_work"].decimal_value == max_llg
    ]

    min_mp = min(
        c.metrics["molprobity_score"].decimal_value for c in llg_winners
    )
    final_tied = [
        c
        for c in llg_winners
        if c.metrics["molprobity_score"].decimal_value == min_mp
    ]
    final_tied_sorted = sorted(final_tied, key=lambda c: c.move_id)
    final_tied_ids = tuple(c.move_id for c in final_tied_sorted)

    if len(final_tied_sorted) == 1:
        chosen = final_tied_sorted[0]
        return {
            "selection_state": "selected_unique",
            "selected_move_id": chosen.move_id,
            "selected_move_index": chosen.move_index,
            "selected_candidate": chosen.to_public_dict(),
            "tied_move_ids": final_tied_ids,
            "tie_group_move_ids": tie_group_ids,
            "eligible_move_ids": tuple(c.move_id for c in eligible_records),
            "ineligible_by_status": ineligible_by_status_sorted,
            "ineligible_by_geometry": ineligible_by_geometry_sorted,
            "eligibility_by_move_id": eligibility_by_move_id,
            "tie_group_policy": validated_tie_policy,
            "residual_tie_policy": validated_residual_policy,
            "policy_status_note": (
                "tie_group_policy and residual_tie_policy are caller-bound implementation "
                "parameters for testing/replay and do not establish frozen study policy."
            ),
            "registration_status": REGISTRATION_STATUS,
            "stage2_status": STAGE2_SELECTOR_STATUS,
            "executed": False,
        }

    if validated_residual_policy == "unresolved_tie":
        return {
            "selection_state": "unresolved_exact_tie",
            "selected_move_id": None,
            "selected_move_index": None,
            "selected_candidate": None,
            "tied_move_ids": final_tied_ids,
            "tie_group_move_ids": tie_group_ids,
            "eligible_move_ids": tuple(c.move_id for c in eligible_records),
            "ineligible_by_status": ineligible_by_status_sorted,
            "ineligible_by_geometry": ineligible_by_geometry_sorted,
            "eligibility_by_move_id": eligibility_by_move_id,
            "tie_group_policy": validated_tie_policy,
            "residual_tie_policy": validated_residual_policy,
            "policy_status_note": (
                "Residual exact tie on (R_work tie group, LLG_work, MolProbity); "
                "no arbitrary scientific winner selected."
            ),
            "registration_status": REGISTRATION_STATUS,
            "stage2_status": STAGE2_SELECTOR_STATUS,
            "executed": False,
        }

    chosen = final_tied_sorted[0]
    return {
        "selection_state": "selected_by_canonical_id_tiebreak",
        "selected_move_id": chosen.move_id,
        "selected_move_index": chosen.move_index,
        "selected_candidate": chosen.to_public_dict(),
        "tied_move_ids": final_tied_ids,
        "tie_group_move_ids": tie_group_ids,
        "eligible_move_ids": tuple(c.move_id for c in eligible_records),
        "ineligible_by_status": ineligible_by_status_sorted,
        "ineligible_by_geometry": ineligible_by_geometry_sorted,
        "eligibility_by_move_id": eligibility_by_move_id,
        "tie_group_policy": validated_tie_policy,
        "residual_tie_policy": validated_residual_policy,
        "policy_status_note": (
            "Non-scientific canonical_move_id_asc tie-break applied by explicit caller policy."
        ),
        "registration_status": REGISTRATION_STATUS,
        "stage2_status": STAGE2_SELECTOR_STATUS,
        "executed": False,
    }


def _validate_budget_summary_mapping(
    budget_summary: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(budget_summary, Mapping):
        raise ValueError("budget_summary must be a mapping.")
    for req_b_key in (
        "budget_ok",
        "move_count",
        "total_observed_macro_cycles",
        "total_tokens",
        "elapsed_seconds",
    ):
        if req_b_key not in budget_summary:
            raise ValueError(
                f"budget_summary is missing required key {req_b_key!r}."
            )

    budget_ok = budget_summary["budget_ok"]
    if not isinstance(budget_ok, bool):
        raise ValueError(
            f"budget_summary.budget_ok must be a bool, got {type(budget_ok).__name__}."
        )
    move_count = _validate_strict_int(
        budget_summary["move_count"],
        field_name="budget_summary.move_count",
        min_value=0,
    )
    total_observed_macro_cycles = _validate_strict_int(
        budget_summary["total_observed_macro_cycles"],
        field_name="budget_summary.total_observed_macro_cycles",
        min_value=0,
    )
    total_tokens = _validate_strict_int(
        budget_summary["total_tokens"],
        field_name="budget_summary.total_tokens",
        min_value=0,
    )
    elapsed_val, elapsed_dec = _to_exact_decimal(
        budget_summary["elapsed_seconds"],
        field_name="budget_summary.elapsed_seconds",
        allow_negative=False,
    )

    violation_codes: tuple[str, ...] = ()
    if (
        "violation_codes" in budget_summary
        and budget_summary["violation_codes"] is not None
    ):
        raw_vc = budget_summary["violation_codes"]
        if isinstance(raw_vc, (str, bytes, Mapping)) or not isinstance(
            raw_vc, Sequence
        ):
            raise ValueError(
                "budget_summary.violation_codes must be a sequence of strings."
            )
        vc_list: list[str] = []
        for idx, code in enumerate(raw_vc):
            if not isinstance(code, str) or not code.strip():
                raise ValueError(
                    f"budget_summary.violation_codes[{idx}] must be a non-empty string."
                )
            vc_list.append(code)
        violation_codes = tuple(vc_list)

    violation_reasons: tuple[str, ...] = ()
    if (
        "violation_reasons" in budget_summary
        and budget_summary["violation_reasons"] is not None
    ):
        raw_vr = budget_summary["violation_reasons"]
        if isinstance(raw_vr, (str, bytes, Mapping)) or not isinstance(
            raw_vr, Sequence
        ):
            raise ValueError(
                "budget_summary.violation_reasons must be a sequence of strings."
            )
        vr_list: list[str] = []
        for idx, reason in enumerate(raw_vr):
            if not isinstance(reason, str) or not reason.strip():
                raise ValueError(
                    f"budget_summary.violation_reasons[{idx}] must be a non-empty string."
                )
            vr_list.append(reason)
        violation_reasons = tuple(vr_list)

    if budget_ok and violation_codes:
        raise ValueError(
            "budget_summary has budget_ok=True with non-empty violation_codes."
        )
    if budget_ok and (
        move_count > MAX_OUTER_MOVES
        or total_observed_macro_cycles > MAX_MACRO_CYCLES
        or total_tokens > MAX_TOTAL_TOKENS
        or elapsed_dec > Decimal(str(MAX_ELAPSED_SECONDS))
    ):
        raise ValueError(
            "budget_summary claims budget_ok=True while exceeding a U12 cumulative cap."
        )

    return {
        "budget_ok": budget_ok,
        "move_count": move_count,
        "total_observed_macro_cycles": total_observed_macro_cycles,
        "total_tokens": total_tokens,
        "elapsed_seconds": float(elapsed_val)
        if isinstance(elapsed_val, float)
        else elapsed_val,
        "elapsed_seconds_dec": elapsed_dec,
        "violation_codes": violation_codes,
        "violation_reasons": violation_reasons,
    }


def _evaluate_budget_cap_exhaustion(
    budget_summary: Mapping[str, Any],
) -> tuple[bool, list[str]]:
    cap_reasons: list[str] = []
    if budget_summary["move_count"] >= MAX_OUTER_MOVES:
        cap_reasons.append(
            f"cap_exhausted:outer_moves ({budget_summary['move_count']}/{MAX_OUTER_MOVES})"
        )
    if budget_summary["total_observed_macro_cycles"] >= MAX_MACRO_CYCLES:
        cap_reasons.append(
            "cap_exhausted:observed_macro_cycles "
            f"({budget_summary['total_observed_macro_cycles']}/{MAX_MACRO_CYCLES})"
        )
    if budget_summary["total_tokens"] >= MAX_TOTAL_TOKENS:
        cap_reasons.append(
            f"cap_exhausted:total_tokens ({budget_summary['total_tokens']}/{MAX_TOTAL_TOKENS})"
        )
    if budget_summary["elapsed_seconds"] >= MAX_ELAPSED_SECONDS:
        cap_reasons.append(
            f"cap_exhausted:elapsed_seconds ({budget_summary['elapsed_seconds']}/{MAX_ELAPSED_SECONDS})"
        )
    return len(cap_reasons) > 0, cap_reasons


def stop_decision(
    *,
    consecutive_delta_pairs: Sequence[Mapping[str, Any]],
    reference_convention: str | None = None,
    budget_summary: Mapping[str, Any] | None = None,
    arm: str | None = None,
    budget_ledger: Sequence[Mapping[str, Any]] | None = None,
    require_budget_evidence: bool = True,
    start_record: Mapping[str, Any] | StartingGeometryRecord | None = None,
    reference_records: (
        Mapping[
            Any,
            Mapping[str, Any]
            | CandidateSelectionRecord
            | StartingGeometryRecord,
        ]
        | Sequence[Mapping[str, Any] | CandidateSelectionRecord]
        | None
    ) = None,
    readout_contract: Mapping[str, Any] | None = None,
    require_reference_evidence: bool = False,
    tie_group_policy: str | None = None,
    residual_tie_policy: str | None = None,
) -> dict[str, Any]:
    """Evaluate U10 outer-loop early stopping from two consecutive move delta pairs and U12 budget state.

    - Requires explicit ``reference_convention`` in
      ``{'previous_move', 'accepted_incumbent', 'start_model'}``.
    - Each pair in ``consecutive_delta_pairs`` must supply ``move_id``, ``move_index``,
      ``move_status`` (must be ``COMPLETED_COMMENSURABLE``; failed moves cannot be bridged),
      ``reference_id``, ``candidate_r_work``, ``reference_r_work``, ``candidate_clashscore``,
      and ``reference_clashscore`` (plus optional ``delta_r_work`` and ``delta_clashscore``
      which, if supplied, must exactly equal the ``Decimal`` difference
      ``candidate - reference``).
    - When ``len(consecutive_delta_pairs) >= 2``, adjacent pairs must have strictly
      contiguous ``move_index`` (``pair[i].move_index == pair[i-1].move_index + 1``) with no
      bridged failed move or index gap. Under ``reference_convention='previous_move'``,
      ``pair[i].reference_id`` and reference metrics must equal ``pair[i-1].move_id`` and
      candidate metrics. Under ``reference_convention='start_model'``, every pair must have
      ``reference_id == 'start'`` and identical reference metrics.
    - When ``start_record`` / ``reference_records`` are supplied (or
      ``require_reference_evidence=True``), validates bound records against ``readout_contract``
      and verifies that all reference IDs and reference/candidate metrics match the bound
      source records without inferring missing references.
    - Stagnation triggers when BOTH latest consecutive pairs satisfy:
      ``delta_r_work > Decimal('-0.0005')`` AND ``delta_clashscore >= Decimal('-0.5')``.
    - Complete U10/U12 budget verification (``require_budget_evidence=True``) requires
      canonical ``(arm, budget_ledger)`` verified via :func:`verify_controller_budget`; if
      ``budget_summary`` is also passed, it must match the verified ledger summary.
      Summary-only evaluation is allowed only when ``require_budget_evidence=False`` and
      sets ``budget_evidence_verified=False``.
    """
    validated_ref_conv = _validate_policy_choice(
        reference_convention,
        allowed=ALLOWED_STOP_REFERENCE_CONVENTIONS,
        field_name="reference_convention",
    )
    if not isinstance(require_budget_evidence, bool):
        raise ValueError("require_budget_evidence must be a bool.")
    if not isinstance(require_reference_evidence, bool):
        raise ValueError("require_reference_evidence must be a bool.")

    resolved_budget: Mapping[str, Any] | None = None
    budget_evidence_verified = False
    validated_summary: dict[str, Any] | None = None
    ledger_moves_by_index: dict[int, Mapping[str, Any]] | None = None
    if budget_summary is not None:
        validated_summary = _validate_budget_summary_mapping(budget_summary)

    if budget_ledger is not None:
        if arm is None:
            raise ValueError(
                "arm is required when verifying budget_ledger in stop_decision."
            )
        ledger_budget = verify_controller_budget(arm=arm, ledger=budget_ledger)
        ledger_moves_by_index = {
            int(lm["move_index"]): lm for lm in ledger_budget["moves"]
        }
        if validated_summary is not None:
            _, ledger_elapsed_dec = _to_exact_decimal(
                ledger_budget["elapsed_seconds"],
                field_name="ledger_budget.elapsed_seconds",
                allow_negative=False,
            )
            if (
                validated_summary["budget_ok"] != ledger_budget["budget_ok"]
                or validated_summary["move_count"] != ledger_budget["move_count"]
                or validated_summary["total_observed_macro_cycles"]
                != ledger_budget["total_observed_macro_cycles"]
                or validated_summary["total_tokens"]
                != ledger_budget["total_tokens"]
                or validated_summary["elapsed_seconds_dec"] != ledger_elapsed_dec
            ):
                raise ValueError(
                    "budget_summary contradicts canonical verify_controller_budget(arm, budget_ledger) "
                    f"summary: summary={validated_summary!r} vs ledger={ledger_budget!r}."
                )
            if (
                "violation_codes" in budget_summary
                and budget_summary["violation_codes"] is not None
                and validated_summary["violation_codes"]
                != tuple(ledger_budget.get("violation_codes", ()))
            ):
                raise ValueError(
                    "budget_summary.violation_codes contradicts canonical "
                    "verify_controller_budget(arm, budget_ledger) violation_codes."
                )
            if (
                "arm" in budget_summary
                and budget_summary["arm"] is not None
                and budget_summary["arm"] != ledger_budget.get("arm")
            ):
                raise ValueError(
                    f"budget_summary.arm ({budget_summary['arm']!r}) contradicts "
                    f"verified arm ({ledger_budget.get('arm')!r})."
                )
        resolved_budget = ledger_budget
        budget_evidence_verified = True
    elif arm is not None:
        raise ValueError(
            "budget_ledger is required when arm is supplied to stop_decision."
        )
    elif validated_summary is not None:
        if require_budget_evidence:
            raise ValueError(
                "U10/U12 complete stop-policy verification (require_budget_evidence=True) "
                "requires canonical (arm, budget_ledger) evidence; summary-only budget_summary "
                "cannot establish budget_evidence_verified=True (supply arm and budget_ledger, "
                "or set require_budget_evidence=False for unverified formula-only evaluation)."
            )
        resolved_budget = validated_summary
        budget_evidence_verified = False
    elif require_budget_evidence:
        raise ValueError(
            "U10/U12 complete stop-policy verification requires (arm, budget_ledger) "
            "evidence; missing budget evidence cannot establish stop conformance."
        )

    if isinstance(consecutive_delta_pairs, (str, bytes, Mapping)) or not isinstance(
        consecutive_delta_pairs, Sequence
    ):
        raise ValueError("consecutive_delta_pairs must be a sequence of mappings.")

    allowed_pair_keys = {
        "move_id",
        "move_index",
        "move_status",
        "reference_id",
        "reference_convention",
        "candidate_r_work",
        "reference_r_work",
        "delta_r_work",
        "candidate_clashscore",
        "reference_clashscore",
        "delta_clashscore",
    }

    normalized_pairs: list[dict[str, Any]] = []
    pair_decimals: list[dict[str, Decimal]] = []
    seen_pair_move_ids: set[str] = set()
    for idx, raw_pair in enumerate(consecutive_delta_pairs):
        prefix = f"consecutive_delta_pairs[{idx}]"
        if not isinstance(raw_pair, Mapping):
            raise ValueError(f"{prefix} must be a mapping.")
        unknown_keys = sorted(set(raw_pair.keys()) - allowed_pair_keys)
        if unknown_keys:
            raise ValueError(
                f"{prefix} contains unknown keys: {unknown_keys}."
            )
        for req_k in (
            "move_id",
            "move_index",
            "move_status",
            "reference_id",
            "candidate_r_work",
            "reference_r_work",
            "candidate_clashscore",
            "reference_clashscore",
        ):
            if req_k not in raw_pair:
                raise ValueError(f"{prefix} is missing required key {req_k!r}.")

        if (
            "reference_convention" in raw_pair
            and raw_pair["reference_convention"] != validated_ref_conv
        ):
            raise ValueError(
                f"{prefix}.reference_convention ({raw_pair['reference_convention']!r}) "
                f"conflicts with declared reference_convention ({validated_ref_conv!r})."
            )

        move_id = _validate_safe_id(
            raw_pair["move_id"], field_name=f"{prefix}.move_id"
        )
        if move_id == "start":
            raise ValueError(
                f"{prefix}.move_id cannot be reserved identifier 'start'."
            )
        if move_id in seen_pair_move_ids:
            raise ValueError(
                f"Duplicate move_id {move_id!r} in consecutive_delta_pairs."
            )
        seen_pair_move_ids.add(move_id)

        move_index = _validate_strict_int(
            raw_pair["move_index"],
            field_name=f"{prefix}.move_index",
            min_value=1,
        )
        move_status = raw_pair["move_status"]
        if move_status != COMPLETED_COMMENSURABLE_STATUS:
            raise ValueError(
                f"{prefix} has move_status={move_status!r}; stop_decision delta pairs "
                f"require {COMPLETED_COMMENSURABLE_STATUS!r} moves and cannot bridge failed moves."
            )
        reference_id = _validate_safe_id(
            raw_pair["reference_id"], field_name=f"{prefix}.reference_id"
        )
        if reference_id == move_id:
            raise ValueError(
                f"{prefix}.reference_id ({reference_id!r}) cannot equal move_id ({move_id!r})."
            )
        if move_index == 1 and reference_id != "start":
            raise ValueError(
                f"{prefix} at move_index=1 under reference_convention={validated_ref_conv!r} "
                f"must have reference_id='start', got {reference_id!r}."
            )
        if validated_ref_conv == "previous_move" and move_index > 1 and reference_id == "start":
            raise ValueError(
                f"{prefix} at move_index={move_index} under reference_convention='previous_move' "
                f"must reference prior move_index={move_index - 1}, not 'start'."
            )
        if validated_ref_conv == "start_model" and reference_id != "start":
            raise ValueError(
                f"{prefix} under reference_convention='start_model' must have "
                f"reference_id='start', got {reference_id!r}."
            )

        _, cand_r = _to_exact_decimal(
            raw_pair["candidate_r_work"],
            field_name=f"{prefix}.candidate_r_work",
            allow_negative=False,
        )
        _, ref_r = _to_exact_decimal(
            raw_pair["reference_r_work"],
            field_name=f"{prefix}.reference_r_work",
            allow_negative=False,
        )
        computed_delta_r = _dec_sub(cand_r, ref_r)
        if "delta_r_work" in raw_pair and raw_pair["delta_r_work"] is not None:
            _, claimed_delta_r = _to_exact_decimal(
                raw_pair["delta_r_work"],
                field_name=f"{prefix}.delta_r_work",
                allow_negative=True,
            )
            if claimed_delta_r != computed_delta_r:
                raise ValueError(
                    f"{prefix}.delta_r_work ({claimed_delta_r}) does not match exact Decimal "
                    f"candidate_r_work - reference_r_work ({computed_delta_r})."
                )

        _, cand_clash = _to_exact_decimal(
            raw_pair["candidate_clashscore"],
            field_name=f"{prefix}.candidate_clashscore",
            allow_negative=False,
        )
        _, ref_clash = _to_exact_decimal(
            raw_pair["reference_clashscore"],
            field_name=f"{prefix}.reference_clashscore",
            allow_negative=False,
        )
        computed_delta_clash = _dec_sub(cand_clash, ref_clash)
        if (
            "delta_clashscore" in raw_pair
            and raw_pair["delta_clashscore"] is not None
        ):
            _, claimed_delta_clash = _to_exact_decimal(
                raw_pair["delta_clashscore"],
                field_name=f"{prefix}.delta_clashscore",
                allow_negative=True,
            )
            if claimed_delta_clash != computed_delta_clash:
                raise ValueError(
                    f"{prefix}.delta_clashscore ({claimed_delta_clash}) does not match exact "
                    f"Decimal candidate_clashscore - reference_clashscore ({computed_delta_clash})."
                )

        r_stagnant = bool(computed_delta_r > STOP_DELTA_R_WORK_STRICT_LOWER)
        clash_stagnant = bool(computed_delta_clash >= STOP_DELTA_CLASHSCORE_LOWER)
        move_stagnant = bool(r_stagnant and clash_stagnant)

        normalized_pairs.append(
            {
                "move_id": move_id,
                "move_index": move_index,
                "reference_id": reference_id,
                "delta_r_work": str(computed_delta_r),
                "delta_clashscore": str(computed_delta_clash),
                "r_work_stagnant": r_stagnant,
                "clashscore_stagnant": clash_stagnant,
                "move_stagnant": move_stagnant,
            }
        )
        pair_decimals.append(
            {
                "cand_r": cand_r,
                "ref_r": ref_r,
                "cand_clash": cand_clash,
                "ref_clash": ref_clash,
            }
        )

    for idx in range(1, len(normalized_pairs)):
        prev_pair = normalized_pairs[idx - 1]
        curr_pair = normalized_pairs[idx]
        prev_dec = pair_decimals[idx - 1]
        curr_dec = pair_decimals[idx]
        prev_idx = prev_pair["move_index"]
        curr_idx = curr_pair["move_index"]
        if curr_idx != prev_idx + 1:
            raise ValueError(
                f"Non-contiguous move_index in consecutive_delta_pairs: "
                f"index {prev_idx} followed by {curr_idx} (bridging failed moves or gaps is forbidden)."
            )
        if validated_ref_conv == "previous_move":
            if curr_pair["reference_id"] != prev_pair["move_id"]:
                raise ValueError(
                    f"previous_move reference_id continuity mismatch at consecutive_delta_pairs[{idx}]: "
                    f"expected prior move_id {prev_pair['move_id']!r}, got {curr_pair['reference_id']!r}."
                )
            if curr_dec["ref_r"] != prev_dec["cand_r"]:
                raise ValueError(
                    f"previous_move reference_r_work continuity mismatch at consecutive_delta_pairs[{idx}]: "
                    f"reference_r_work ({curr_dec['ref_r']}) != prior move candidate_r_work ({prev_dec['cand_r']})."
                )
            if curr_dec["ref_clash"] != prev_dec["cand_clash"]:
                raise ValueError(
                    f"previous_move reference_clashscore continuity mismatch at consecutive_delta_pairs[{idx}]: "
                    f"reference_clashscore ({curr_dec['ref_clash']}) != prior move candidate_clashscore ({prev_dec['cand_clash']})."
                )
        elif validated_ref_conv == "start_model":
            if (
                curr_dec["ref_r"] != pair_decimals[0]["ref_r"]
                or curr_dec["ref_clash"] != pair_decimals[0]["ref_clash"]
            ):
                raise ValueError(
                    f"start_model reference metrics mismatch at consecutive_delta_pairs[{idx}]: "
                    f"({curr_dec['ref_r']}, {curr_dec['ref_clash']}) != "
                    f"({pair_decimals[0]['ref_r']}, {pair_decimals[0]['ref_clash']})."
                )

    if ledger_moves_by_index is not None:
        for idx, pair in enumerate(normalized_pairs):
            m_idx = pair["move_index"]
            if m_idx not in ledger_moves_by_index:
                raise ValueError(
                    f"consecutive_delta_pairs[{idx}] move_index={m_idx} is absent from "
                    f"canonical budget_ledger (move_count={len(ledger_moves_by_index)})."
                )
            ledger_m_status = ledger_moves_by_index[m_idx].get("move_status")
            if ledger_m_status != "completed":
                raise ValueError(
                    f"consecutive_delta_pairs[{idx}] at move_index={m_idx} has "
                    f"move_status={COMPLETED_COMMENSURABLE_STATUS!r} but canonical "
                    f"budget_ledger move_status={ledger_m_status!r} (expected 'completed')."
                )
            if validated_ref_conv == "previous_move" and m_idx > 1:
                prev_l_idx = m_idx - 1
                prev_l_status = ledger_moves_by_index[prev_l_idx].get(
                    "move_status"
                )
                if prev_l_status != "completed":
                    raise ValueError(
                        f"consecutive_delta_pairs[{idx}] at move_index={m_idx} under "
                        f"reference_convention='previous_move' references prior "
                        f"move_index={prev_l_idx} with canonical budget_ledger "
                        f"move_status={prev_l_status!r} (expected 'completed')."
                    )

    reference_evidence_verified = False
    if (
        require_reference_evidence
        or start_record is not None
        or reference_records is not None
    ):
        validated_contract = validate_readout_contract(readout_contract)
        validated_start: StartingGeometryRecord | None = None
        ref_lineage: tuple[str, str, str] | None = None
        if start_record is not None:
            validated_start = validate_starting_geometry_record(
                start_record, readout_contract=validated_contract
            )
            ref_lineage = (
                validated_start.target_id,
                validated_start.subject_id,
                validated_start.work_reflection_domain_sha256,
            )

        bound_by_index: dict[int, CandidateSelectionRecord] = {}
        bound_by_id: dict[str, CandidateSelectionRecord] = {}
        if reference_records is not None:
            if isinstance(reference_records, Mapping):
                raw_ref_items: list[tuple[Any, Any]] = list(
                    reference_records.items()
                )
            elif not isinstance(reference_records, (str, bytes)) and isinstance(
                reference_records, Sequence
            ):
                raw_ref_items = [(None, item) for item in reference_records]
            else:
                raise ValueError(
                    "reference_records must be a mapping or sequence of candidate records."
                )

            for map_key, raw_rec in raw_ref_items:
                if isinstance(raw_rec, StartingGeometryRecord) or (
                    isinstance(raw_rec, Mapping)
                    and map_key == "start"
                    and "move_id" not in raw_rec
                ):
                    s_rec = validate_starting_geometry_record(
                        raw_rec, readout_contract=validated_contract
                    )
                    if validated_start is not None and s_rec != validated_start:
                        raise ValueError(
                            "Conflicting start_record supplied in reference_records['start']."
                        )
                    s_lineage = (
                        s_rec.target_id,
                        s_rec.subject_id,
                        s_rec.work_reflection_domain_sha256,
                    )
                    if ref_lineage is not None and s_lineage != ref_lineage:
                        raise ValueError(
                            f"reference_records['start'] lineage {s_lineage!r} "
                            f"mismatches expected {ref_lineage!r}."
                        )
                    validated_start = s_rec
                    ref_lineage = s_lineage
                    continue

                c_rec = validate_public_candidate_record(
                    raw_rec, readout_contract=validated_contract
                )
                if c_rec.status != COMPLETED_COMMENSURABLE_STATUS:
                    raise ValueError(
                        f"reference_records contains non-commensurable move {c_rec.move_id!r} "
                        f"with status={c_rec.status!r}."
                    )
                if isinstance(map_key, int) and not isinstance(map_key, bool):
                    if map_key != c_rec.move_index:
                        raise ValueError(
                            f"reference_records key {map_key} does not match record move_index {c_rec.move_index}."
                        )
                elif isinstance(map_key, str):
                    if map_key != c_rec.move_id:
                        raise ValueError(
                            f"reference_records key {map_key!r} does not match record move_id {c_rec.move_id!r}."
                        )
                elif map_key is not None:
                    raise ValueError(
                        f"Unsupported reference_records key {map_key!r}."
                    )

                rec_lineage = (
                    c_rec.target_id,
                    c_rec.subject_id,
                    c_rec.work_reflection_domain_sha256,
                )
                if ref_lineage is None:
                    ref_lineage = rec_lineage
                elif rec_lineage != ref_lineage:
                    raise ValueError(
                        f"reference_records move {c_rec.move_id!r} lineage {rec_lineage!r} "
                        f"mismatches expected {ref_lineage!r}."
                    )

                if (
                    c_rec.move_index in bound_by_index
                    and bound_by_index[c_rec.move_index] != c_rec
                ):
                    raise ValueError(
                        f"Conflicting duplicate move_index={c_rec.move_index} in reference_records."
                    )
                if (
                    c_rec.move_id in bound_by_id
                    and bound_by_id[c_rec.move_id] != c_rec
                ):
                    raise ValueError(
                        f"Conflicting duplicate move_id={c_rec.move_id!r} in reference_records."
                    )
                bound_by_index[c_rec.move_index] = c_rec
                bound_by_id[c_rec.move_id] = c_rec

        # Order-independent final lineage verification across start_record and all bound candidates
        if validated_start is not None:
            start_lineage = (
                validated_start.target_id,
                validated_start.subject_id,
                validated_start.work_reflection_domain_sha256,
            )
            if ref_lineage is not None and start_lineage != ref_lineage:
                raise ValueError(
                    f"start_record lineage {start_lineage!r} mismatches bound candidate lineage {ref_lineage!r}."
                )
            ref_lineage = start_lineage
        for c_rec in bound_by_index.values():
            rec_lineage = (
                c_rec.target_id,
                c_rec.subject_id,
                c_rec.work_reflection_domain_sha256,
            )
            if ref_lineage is not None and rec_lineage != ref_lineage:
                raise ValueError(
                    f"reference_records move {c_rec.move_id!r} lineage {rec_lineage!r} "
                    f"mismatches bound lineage {ref_lineage!r}."
                )

        for idx, pair in enumerate(normalized_pairs):
            dec = pair_decimals[idx]
            m_idx = pair["move_index"]
            m_id = pair["move_id"]
            ref_id = pair["reference_id"]

            cand_by_idx = bound_by_index.get(m_idx)
            cand_by_id = bound_by_id.get(m_id)
            if (
                cand_by_idx is None
                or cand_by_id is None
                or cand_by_idx != cand_by_id
            ):
                raise ValueError(
                    f"consecutive_delta_pairs[{idx}] candidate ({m_id!r}, move_index={m_idx}) "
                    "is missing from or contradicts bound reference_records; complete reference "
                    "evidence requires a bound candidate record for every evaluated pair."
                )
            _, bound_cand_r = _to_exact_decimal(
                cand_by_idx.metrics["r_work"].value,
                field_name=f"reference_records[{m_id}].r_work",
                allow_negative=False,
            )
            _, bound_cand_clash = _to_exact_decimal(
                cand_by_idx.metrics["clashscore"].value,
                field_name=f"reference_records[{m_id}].clashscore",
                allow_negative=False,
            )
            if (
                dec["cand_r"] != bound_cand_r
                or dec["cand_clash"] != bound_cand_clash
            ):
                raise ValueError(
                    f"consecutive_delta_pairs[{idx}] candidate metrics "
                    f"({dec['cand_r']}, {dec['cand_clash']}) contradict bound record "
                    f"({bound_cand_r}, {bound_cand_clash})."
                )

            if validated_ref_conv == "start_model" or m_idx == 1:
                if validated_start is None:
                    raise ValueError(
                        f"consecutive_delta_pairs[{idx}] references 'start', but no bound "
                        "start_record was supplied to stop_decision."
                    )
                if "r_work" not in validated_start.metrics:
                    raise ValueError(
                        "start_record.metrics must include 'r_work' to verify 'start' "
                        "reference deltas in stop_decision."
                    )
                _, start_r = _to_exact_decimal(
                    validated_start.metrics["r_work"].value,
                    field_name="start_record.metrics.r_work",
                    allow_negative=False,
                )
                _, start_clash = _to_exact_decimal(
                    validated_start.metrics["clashscore"].value,
                    field_name="start_record.metrics.clashscore",
                    allow_negative=False,
                )
                if (
                    ref_id != "start"
                    or dec["ref_r"] != start_r
                    or dec["ref_clash"] != start_clash
                ):
                    raise ValueError(
                        f"consecutive_delta_pairs[{idx}] start reference ({ref_id!r}, "
                        f"{dec['ref_r']}, {dec['ref_clash']}) contradicts bound start_record "
                        f"('start', {start_r}, {start_clash})."
                    )
            elif validated_ref_conv == "previous_move":
                prev_idx = m_idx - 1
                if prev_idx not in bound_by_index:
                    raise ValueError(
                        f"consecutive_delta_pairs[{idx}] at move_index={m_idx} under "
                        f"reference_convention='previous_move' requires bound record for "
                        f"prior move_index={prev_idx} in reference_records."
                    )
                ref_rec = bound_by_index[prev_idx]
                _, bound_ref_r = _to_exact_decimal(
                    ref_rec.metrics["r_work"].value,
                    field_name=f"reference_records[{ref_rec.move_id}].r_work",
                    allow_negative=False,
                )
                _, bound_ref_clash = _to_exact_decimal(
                    ref_rec.metrics["clashscore"].value,
                    field_name=f"reference_records[{ref_rec.move_id}].clashscore",
                    allow_negative=False,
                )
                if (
                    ref_id != ref_rec.move_id
                    or dec["ref_r"] != bound_ref_r
                    or dec["ref_clash"] != bound_ref_clash
                ):
                    raise ValueError(
                        f"consecutive_delta_pairs[{idx}] previous_move reference "
                        f"({ref_id!r}, {dec['ref_r']}, {dec['ref_clash']}) contradicts "
                        f"bound prior move record ({ref_rec.move_id!r}, {bound_ref_r}, {bound_ref_clash})."
                    )
            elif validated_ref_conv == "accepted_incumbent":
                if validated_start is None:
                    raise ValueError(
                        "start_record is required when verifying accepted_incumbent "
                        "reference evidence in stop_decision."
                    )
                validated_tie_pol = _validate_policy_choice(
                    tie_group_policy,
                    allowed=ALLOWED_TIE_GROUP_POLICIES,
                    field_name="tie_group_policy",
                )
                validated_res_pol = _validate_policy_choice(
                    residual_tie_policy,
                    allowed=ALLOWED_RESIDUAL_TIE_POLICIES,
                    field_name="residual_tie_policy",
                )
                missing_prior = [
                    prior_i
                    for prior_i in range(1, m_idx)
                    if prior_i not in bound_by_index
                ]
                if missing_prior:
                    raise ValueError(
                        f"consecutive_delta_pairs[{idx}] at move_index={m_idx} under "
                        f"reference_convention='accepted_incumbent' requires complete prior "
                        f"candidate prefix 1..{m_idx - 1} in reference_records; missing "
                        f"move_index={missing_prior}."
                    )
                exp_id, exp_r_val, exp_clash_val = (
                    _extract_reference_metrics_for_stop(
                        reference_convention=validated_ref_conv,
                        curr_idx=m_idx,
                        validated_moves_by_index=bound_by_index,
                        start_rec=validated_start,
                        tie_group_policy=validated_tie_pol,
                        residual_tie_policy=validated_res_pol,
                        readout_contract=validated_contract,
                    )
                )
                _, exp_r = _to_exact_decimal(
                    exp_r_val,
                    field_name="expected_incumbent.r_work",
                    allow_negative=False,
                )
                _, exp_clash = _to_exact_decimal(
                    exp_clash_val,
                    field_name="expected_incumbent.clashscore",
                    allow_negative=False,
                )
                if (
                    ref_id != exp_id
                    or dec["ref_r"] != exp_r
                    or dec["ref_clash"] != exp_clash
                ):
                    raise ValueError(
                        f"consecutive_delta_pairs[{idx}] accepted_incumbent reference "
                        f"({ref_id!r}, {dec['ref_r']}, {dec['ref_clash']}) contradicts "
                        f"replayed incumbent ({exp_id!r}, {exp_r}, {exp_clash})."
                    )
        reference_evidence_verified = True

    stagnation_triggered = False
    reasons: list[str] = []
    if len(normalized_pairs) >= STOP_CONSECUTIVE_MOVES_REQUIRED:
        last_two = normalized_pairs[-STOP_CONSECUTIVE_MOVES_REQUIRED:]
        if all(p["move_stagnant"] for p in last_two):
            stagnation_triggered = True
            reasons.append(
                f"stagnation_two_consecutive_moves:{last_two[0]['move_id']},{last_two[1]['move_id']}"
            )

    cap_exhausted = False
    budget_violation = False
    if resolved_budget is not None:
        cap_exhausted, cap_reasons = _evaluate_budget_cap_exhaustion(
            resolved_budget
        )
        reasons.extend(cap_reasons)
        if not resolved_budget.get("budget_ok", False):
            budget_violation = True
            reasons.append(
                f"budget_violation:{list(resolved_budget.get('violation_codes', ()))}"
            )

    should_stop = bool(
        stagnation_triggered or cap_exhausted or budget_violation
    )
    return {
        "should_stop": should_stop,
        "stagnation_triggered": stagnation_triggered,
        "budget_cap_exhausted": cap_exhausted,
        "budget_violation": budget_violation,
        "budget_evidence_verified": budget_evidence_verified,
        "reference_evidence_verified": reference_evidence_verified,
        "stop_reasons": tuple(reasons),
        "reference_convention": validated_ref_conv,
        "evaluated_pairs": tuple(normalized_pairs),
        "registration_status": REGISTRATION_STATUS,
        "stage2_status": STAGE2_SELECTOR_STATUS,
        "executed": False,
    }


def _extract_reference_metrics_for_stop(
    *,
    reference_convention: str,
    curr_idx: int,
    validated_moves_by_index: dict[int, CandidateSelectionRecord],
    start_rec: StartingGeometryRecord,
    tie_group_policy: str,
    residual_tie_policy: str,
    readout_contract: Mapping[str, Mapping[str, str]],
) -> tuple[str, int | float, int | float]:
    if reference_convention == "previous_move":
        if curr_idx == 1:
            if "r_work" not in start_rec.metrics:
                raise ValueError(
                    "start_record.metrics must include 'r_work' when evaluating Move 1 "
                    "stopping deltas against start/previous_move."
                )
            return (
                "start",
                start_rec.metrics["r_work"].value,
                start_rec.metrics["clashscore"].value,
            )
        prev_idx = curr_idx - 1
        if prev_idx not in validated_moves_by_index:
            raise ValueError(
                f"Cannot compute previous_move stopping delta at move_index={curr_idx}: "
                f"prior move_index={prev_idx} is not a COMPLETED_COMMENSURABLE move."
            )
        prev_rec = validated_moves_by_index[prev_idx]
        return (
            prev_rec.move_id,
            prev_rec.metrics["r_work"].value,
            prev_rec.metrics["clashscore"].value,
        )

    if reference_convention == "start_model":
        if "r_work" not in start_rec.metrics:
            raise ValueError(
                "start_record.metrics must include 'r_work' when reference_convention='start_model'."
            )
        return (
            "start",
            start_rec.metrics["r_work"].value,
            start_rec.metrics["clashscore"].value,
        )

    # accepted_incumbent over prior prefix 1..curr_idx-1
    prior_candidates = [
        validated_moves_by_index[i]
        for i in sorted(validated_moves_by_index.keys())
        if i < curr_idx
    ]
    if not prior_candidates:
        if "r_work" not in start_rec.metrics:
            raise ValueError(
                "start_record.metrics must include 'r_work' when evaluating Move 1 "
                "under reference_convention='accepted_incumbent'."
            )
        return (
            "start",
            start_rec.metrics["r_work"].value,
            start_rec.metrics["clashscore"].value,
        )
    inc_sel = select_candidate(
        prior_candidates,
        start_rec,
        tie_group_policy=tie_group_policy,
        residual_tie_policy=residual_tie_policy,
        readout_contract=readout_contract,
    )
    if inc_sel["selection_state"] == "unresolved_exact_tie":
        raise ValueError(
            f"Cannot resolve accepted_incumbent reference at move_index={curr_idx}: "
            f"prior prefix 1..{curr_idx - 1} has selection_state='unresolved_exact_tie' "
            f"over tied eligible moves {inc_sel['tied_move_ids']!r} under "
            f"residual_tie_policy={residual_tie_policy!r} (no transition policy is selected "
            "for continuing after an unresolved exact incumbent tie; falling back to 'start' "
            "is forbidden)."
        )
    inc_id = inc_sel["selected_move_id"]
    if inc_id is None:
        assert inc_sel["selection_state"] == "no_eligible_candidate"
        if "r_work" not in start_rec.metrics:
            raise ValueError(
                "No prior eligible incumbent and start_record.metrics lacks 'r_work'."
            )
        return (
            "start",
            start_rec.metrics["r_work"].value,
            start_rec.metrics["clashscore"].value,
        )
    inc_rec = next(c for c in prior_candidates if c.move_id == inc_id)
    return (
        inc_rec.move_id,
        inc_rec.metrics["r_work"].value,
        inc_rec.metrics["clashscore"].value,
    )


_PROVENANCE_SLOT_SPECS: tuple[
    tuple[str, tuple[str, ...], tuple[str, ...]], ...
] = (
    ("primary_command", ("primary_command_sha256",), ("primary_command",)),
    (
        "mechanical_backup",
        ("mechanical_backup_sha256",),
        ("mechanical_backup_command", "mechanical_backup"),
    ),
    ("actual_command", ("actual_command_sha256",), ("actual_command",)),
    (
        "effective_eff",
        ("effective_eff_sha256",),
        ("effective_eff_receipt", "effective_eff"),
    ),
)

_UNQUOTED_COMMAND_METACHARS: frozenset[str] = frozenset(";|&\x60$><*?[]~#()\\")


def _tokenize_bounded_command_text(
    raw_text: str, *, field_name: str
) -> tuple[str, ...]:
    """Deterministically tokenize raw command text into argv tokens without shell execution.

    Preserves quoted segments inside tokens (e.g. ``output.prefix="run_01"``) so downstream
    bounded PHIL parsing in ``phenix_stage2_flags.verify_flag_generation_guard`` sees the
    exact token structure, while rejecting newlines, NUL bytes, unterminated quotes, and
    shell control/interpolation metacharacters.
    """
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise ValueError(
            f"{field_name} must be a non-empty UTF-8 command string."
        )
    if "\x00" in raw_text or "\n" in raw_text or "\r" in raw_text:
        raise ValueError(
            f"{field_name} contains forbidden NUL byte or newline character."
        )

    tokens: list[str] = []
    buf: list[str] = []
    quote: str | None = None
    i = 0
    n = len(raw_text)
    while i < n:
        ch = raw_text[i]
        if quote is None:
            if ch in (" ", "\t"):
                if buf:
                    tokens.append("".join(buf))
                    buf = []
                i += 1
                continue
            if ch in ('"', "'"):
                quote = ch
                buf.append(ch)
                i += 1
                continue
            if ch in _UNQUOTED_COMMAND_METACHARS:
                raise ValueError(
                    f"{field_name} contains unsupported unquoted shell/interpolation "
                    f"character {ch!r}."
                )
            buf.append(ch)
            i += 1
        else:
            if ch == quote:
                buf.append(ch)
                quote = None
                i += 1
                continue
            if ch == "\\" and i + 1 < n:
                nxt = raw_text[i + 1]
                if nxt in ("\\", quote):
                    buf.append(ch)
                    buf.append(nxt)
                    i += 2
                    continue
                raise ValueError(
                    f"{field_name} contains unsupported escape sequence '\\{nxt}' "
                    "inside quoted token."
                )
            if ch in ("$", "\x60", "\\"):
                raise ValueError(
                    f"{field_name} contains unsupported shell/escape character {ch!r} "
                    "inside quoted token."
                )
            buf.append(ch)
            i += 1

    if quote is not None:
        raise ValueError(
            f"{field_name} contains an unterminated quote ({quote})."
        )
    if buf:
        tokens.append("".join(buf))
    if not tokens:
        raise ValueError(f"{field_name} produced no command argv tokens.")
    return tuple(tokens)


def _validate_argv_token_sequence(
    raw_argv: Any, *, field_name: str
) -> tuple[str, ...]:
    if (
        isinstance(raw_argv, (str, bytes, Mapping))
        or not isinstance(raw_argv, Sequence)
        or len(raw_argv) == 0
    ):
        raise ValueError(
            f"{field_name} must be a non-empty sequence of string tokens."
        )
    out: list[str] = []
    for idx, tok in enumerate(raw_argv):
        if not isinstance(tok, str) or not tok.strip() or tok != tok.strip():
            raise ValueError(
                f"{field_name}[{idx}] must be a non-empty stripped string token, got {tok!r}."
            )
        out.append(tok)
    return tuple(out)


def _resolve_optional_provenance_slot(
    src_map: Mapping[str, Any],
    *,
    src_prefix: str,
    slot_name: str,
    sha_keys: tuple[str, ...],
    text_keys: tuple[str, ...],
    is_command_layer: bool,
    allow_arm1b_nested: bool = True,
) -> dict[str, Any] | None:
    state_candidates: list[tuple[str, str]] = []
    sha_candidates: list[tuple[str, str]] = []
    text_candidates: list[tuple[str, str]] = []
    rep_candidates: list[tuple[str, str]] = []
    unavail_candidates: list[tuple[str, str]] = []
    not_app_candidates: list[tuple[str, str | None, str | None]] = []
    argv_candidates: list[tuple[str, tuple[str, ...]]] = []
    argv_sha_candidates: list[tuple[str, str]] = []
    source_id_candidates: list[tuple[str, str]] = []

    sources: list[tuple[str, Mapping[str, Any]]] = []
    if "arm1b_provenance" in src_map and src_map["arm1b_provenance"] is not None:
        if not allow_arm1b_nested:
            raise ValueError(
                f"{src_prefix}.arm1b_provenance is not permitted when arm != '1b'."
            )
        if not isinstance(src_map["arm1b_provenance"], Mapping):
            raise ValueError(f"{src_prefix}.arm1b_provenance must be a mapping.")
        sources.append(
            (f"{src_prefix}.arm1b_provenance", src_map["arm1b_provenance"])
        )
    sources.append((src_prefix, src_map))

    allowed_representations = {
        "unavailable",
        "not_applicable",
        "sha256",
        "utf8_text",
        "utf8_text_and_sha256",
    }

    def _parse_slot_mapping(
        raw_map: Mapping[str, Any], *, field_label: str
    ) -> None:
        allowed_map_keys = {
            "state",
            "representation",
            "sha256",
            "text",
            "reason",
            "controller_contract_justification",
            "verified_artifact_bytes_exist",
            "source_id",
        }
        if is_command_layer:
            allowed_map_keys |= {"argv", "argv_sha256"}
        unknown_keys = sorted(set(raw_map.keys()) - allowed_map_keys)
        if unknown_keys:
            raise ValueError(
                f"{field_label} contains unknown provenance binding keys: {unknown_keys}."
            )
        state_val = raw_map.get("state")
        if not isinstance(state_val, str) or state_val not in {
            "available",
            "unavailable",
            "not_applicable",
        }:
            raise ValueError(
                f"{field_label}.state must be one of ['available', 'not_applicable', 'unavailable'], "
                f"got {state_val!r}."
            )
        if (
            "verified_artifact_bytes_exist" in raw_map
            and raw_map["verified_artifact_bytes_exist"] is not False
        ):
            raise ValueError(
                f"{field_label}.verified_artifact_bytes_exist must be False in result-free "
                "receipt validation."
            )
        if "source_id" in raw_map and raw_map["source_id"] is not None:
            sid_val = _validate_safe_id(
                raw_map["source_id"], field_name=f"{field_label}.source_id"
            )
            source_id_candidates.append((f"{field_label}.source_id", sid_val))

        explicit_rep: str | None = None
        if "representation" in raw_map:
            rep_val = raw_map["representation"]
            if (
                not isinstance(rep_val, str)
                or rep_val not in allowed_representations
            ):
                raise ValueError(
                    f"{field_label}.representation must be one of {sorted(allowed_representations)}, "
                    f"got {rep_val!r}."
                )
            explicit_rep = rep_val

        if state_val == "unavailable":
            if (
                raw_map.get("sha256") is not None
                or raw_map.get("text") is not None
                or raw_map.get("argv") is not None
                or raw_map.get("argv_sha256") is not None
                or raw_map.get("controller_contract_justification") is not None
            ):
                raise ValueError(
                    f"{field_label} with state='unavailable' cannot carry sha256, text, argv, "
                    "or controller_contract_justification."
                )
            reason_raw = raw_map.get("reason")
            if not isinstance(reason_raw, str) or not reason_raw.strip():
                raise ValueError(
                    f"{field_label} with state='unavailable' must supply a non-empty 'reason'."
                )
            if explicit_rep is not None and explicit_rep != "unavailable":
                raise ValueError(
                    f"{field_label}.representation={explicit_rep!r} contradicts state='unavailable' "
                    "(expected 'unavailable')."
                )
            if explicit_rep is not None:
                rep_candidates.append(
                    (f"{field_label}.representation", explicit_rep)
                )
            state_candidates.append((f"{field_label}.state", "unavailable"))
            unavail_candidates.append(
                (f"{field_label}.reason", reason_raw.strip())
            )
            return

        if state_val == "not_applicable":
            if (
                raw_map.get("sha256") is not None
                or raw_map.get("text") is not None
                or raw_map.get("argv") is not None
                or raw_map.get("argv_sha256") is not None
            ):
                raise ValueError(
                    f"{field_label} with state='not_applicable' cannot carry sha256, text, or argv."
                )
            ccj_raw = raw_map.get("controller_contract_justification")
            reason_raw = raw_map.get("reason")
            ccj_val: str | None = None
            reason_val: str | None = None
            if ccj_raw is not None:
                if not isinstance(ccj_raw, str) or not ccj_raw.strip():
                    raise ValueError(
                        f"{field_label}.controller_contract_justification must be a non-empty string."
                    )
                ccj_val = ccj_raw.strip()
            if reason_raw is not None:
                if not isinstance(reason_raw, str) or not reason_raw.strip():
                    raise ValueError(
                        f"{field_label}.reason must be a non-empty string."
                    )
                reason_val = reason_raw.strip()
            if explicit_rep is not None and explicit_rep != "not_applicable":
                raise ValueError(
                    f"{field_label}.representation={explicit_rep!r} contradicts state='not_applicable' "
                    "(expected 'not_applicable')."
                )
            if explicit_rep is not None:
                rep_candidates.append(
                    (f"{field_label}.representation", explicit_rep)
                )
            state_candidates.append((f"{field_label}.state", "not_applicable"))
            not_app_candidates.append((field_label, ccj_val, reason_val))
            return

        # state_val == "available"
        if (
            raw_map.get("reason") is not None
            or raw_map.get("controller_contract_justification") is not None
        ):
            raise ValueError(
                f"{field_label} with state='available' cannot carry an unavailability 'reason' "
                "or 'controller_contract_justification'."
            )

        has_sha = "sha256" in raw_map and raw_map["sha256"] is not None
        has_text = "text" in raw_map and raw_map["text"] is not None
        if not has_sha and not has_text:
            raise ValueError(
                f"{field_label} with state='available' must supply 'sha256' and/or 'text'."
            )
        state_candidates.append((f"{field_label}.state", "available"))
        if "sha256" in raw_map and raw_map["sha256"] is not None:
            sha_candidates.append(
                (
                    f"{field_label}.sha256",
                    _validate_sha256(
                        raw_map["sha256"], field_name=f"{field_label}.sha256"
                    ),
                )
            )
        if "text" in raw_map and raw_map["text"] is not None:
            txt_val = raw_map["text"]
            if not isinstance(txt_val, str) or not txt_val.strip():
                raise ValueError(
                    f"{field_label}.text must be a non-empty string."
                )
            text_candidates.append((f"{field_label}.text", txt_val))
        if is_command_layer:
            if "argv" in raw_map and raw_map["argv"] is not None:
                argv_candidates.append(
                    (
                        f"{field_label}.argv",
                        _validate_argv_token_sequence(
                            raw_map["argv"], field_name=f"{field_label}.argv"
                        ),
                    )
                )
            if "argv_sha256" in raw_map and raw_map["argv_sha256"] is not None:
                argv_sha_candidates.append(
                    (
                        f"{field_label}.argv_sha256",
                        _validate_sha256(
                            raw_map["argv_sha256"],
                            field_name=f"{field_label}.argv_sha256",
                        ),
                    )
                )

        expected_map_rep = (
            "utf8_text_and_sha256"
            if (has_sha and has_text)
            else ("sha256" if has_sha else "utf8_text")
        )
        if explicit_rep is not None and explicit_rep != expected_map_rep:
            raise ValueError(
                f"{field_label}.representation={explicit_rep!r} contradicts supplied "
                f"available content (expected {expected_map_rep!r})."
            )
        if explicit_rep is not None:
            rep_candidates.append((f"{field_label}.representation", explicit_rep))

    for pfx, s_map in sources:
        for sk in sha_keys:
            if sk in s_map and s_map[sk] is not None:
                f_name = f"{pfx}.{sk}"
                val = s_map[sk]
                if isinstance(val, Mapping):
                    _parse_slot_mapping(val, field_label=f_name)
                elif isinstance(val, str) and val in UNAVAILABLE_EXECUTION_MARKERS:
                    state_candidates.append((f_name, "unavailable"))
                    unavail_candidates.append((f_name, val))
                else:
                    state_candidates.append((f_name, "available"))
                    sha_candidates.append(
                        (f_name, _validate_sha256(val, field_name=f_name))
                    )
        for tk in text_keys:
            if tk in s_map and s_map[tk] is not None:
                f_name = f"{pfx}.{tk}"
                val = s_map[tk]
                if isinstance(val, Mapping):
                    _parse_slot_mapping(val, field_label=f_name)
                elif isinstance(val, str) and val in UNAVAILABLE_EXECUTION_MARKERS:
                    state_candidates.append((f_name, "unavailable"))
                    unavail_candidates.append((f_name, val))
                else:
                    if not isinstance(val, str) or not val.strip():
                        raise ValueError(
                            f"{f_name} must be a non-empty UTF-8 command/receipt string."
                        )
                    state_candidates.append((f_name, "available"))
                    text_candidates.append((f_name, val))

        argv_key = f"{slot_name}_argv"
        argv_sha_key = f"{slot_name}_argv_sha256"
        phil_text_key = f"{slot_name}_phil_text"
        if not is_command_layer:
            for bad_k in (argv_key, argv_sha_key):
                if bad_k in s_map and s_map[bad_k] is not None:
                    raise ValueError(
                        f"{pfx}.{bad_k} is invalid: {slot_name!r} is a PHIL configuration layer, "
                        "not an argv command layer."
                    )
        else:
            if phil_text_key in s_map and s_map[phil_text_key] is not None:
                raise ValueError(
                    f"{pfx}.{phil_text_key} is invalid: {slot_name!r} is an argv command layer, "
                    "not a PHIL configuration layer."
                )
            if argv_key in s_map and s_map[argv_key] is not None:
                f_name = f"{pfx}.{argv_key}"
                argv_candidates.append(
                    (
                        f_name,
                        _validate_argv_token_sequence(
                            s_map[argv_key], field_name=f_name
                        ),
                    )
                )
            if argv_sha_key in s_map and s_map[argv_sha_key] is not None:
                f_name = f"{pfx}.{argv_sha_key}"
                argv_sha_candidates.append(
                    (
                        f_name,
                        _validate_sha256(s_map[argv_sha_key], field_name=f_name),
                    )
                )

    if not state_candidates:
        if argv_candidates or argv_sha_candidates:
            raise ValueError(
                f"{src_prefix} supplied {slot_name} argv/argv_sha256 without raw command text "
                "or provenance binding; space-joining argv to synthesize raw receipt text is forbidden."
            )
        return None

    base_state_src, slot_state = state_candidates[0]
    for other_state_src, other_state in state_candidates[1:]:
        if other_state != slot_state:
            raise ValueError(
                f"Conflicting {slot_name} state bindings in {src_prefix}: "
                f"{base_state_src}={slot_state!r} vs {other_state_src}={other_state!r}."
            )

    resolved_source_id: str | None = None
    if source_id_candidates:
        base_sid_src, resolved_source_id = source_id_candidates[0]
        for other_sid_src, other_sid in source_id_candidates[1:]:
            if other_sid != resolved_source_id:
                raise ValueError(
                    f"Conflicting {slot_name} source_id bindings: "
                    f"{base_sid_src}={resolved_source_id!r} vs {other_sid_src}={other_sid!r}."
                )

    if slot_state == "unavailable":
        if argv_candidates or argv_sha_candidates:
            raise ValueError(
                f"{src_prefix} {slot_name} with state='unavailable' cannot carry argv or argv_sha256."
            )
        base_u_src, base_reason = unavail_candidates[0]
        for other_u_src, other_reason in unavail_candidates[1:]:
            if other_reason != base_reason:
                raise ValueError(
                    f"Conflicting {slot_name} unavailability reasons in {src_prefix}: "
                    f"{base_u_src}={base_reason!r} vs {other_u_src}={other_reason!r}."
                )
        for rep_src, rep_val in rep_candidates:
            if rep_val != "unavailable":
                raise ValueError(
                    f"{rep_src}={rep_val!r} contradicts resolved representation 'unavailable'."
                )
        return {
            "state": "unavailable",
            "representation": "unavailable",
            "sha256": None,
            "text": None,
            "reason": base_reason,
            "controller_contract_justification": None,
            "argv": None,
            "argv_sha256": None,
            "source_id": resolved_source_id,
        }

    if slot_state == "not_applicable":
        if argv_candidates or argv_sha_candidates:
            raise ValueError(
                f"{src_prefix} {slot_name} with state='not_applicable' cannot carry argv or argv_sha256."
            )
        base_na_src, base_ccj, base_na_reason = not_app_candidates[0]
        for other_na_src, other_ccj, other_na_reason in not_app_candidates[1:]:
            if other_ccj != base_ccj or other_na_reason != base_na_reason:
                raise ValueError(
                    f"Conflicting {slot_name} not_applicable justifications in {src_prefix}: "
                    f"{base_na_src} vs {other_na_src}."
                )
        for rep_src, rep_val in rep_candidates:
            if rep_val != "not_applicable":
                raise ValueError(
                    f"{rep_src}={rep_val!r} contradicts resolved representation 'not_applicable'."
                )
        return {
            "state": "not_applicable",
            "representation": "not_applicable",
            "sha256": None,
            "text": None,
            "reason": base_na_reason,
            "controller_contract_justification": base_ccj,
            "argv": None,
            "argv_sha256": None,
            "source_id": resolved_source_id,
        }

    resolved_sha: str | None = None
    if sha_candidates:
        base_s_src, resolved_sha = sha_candidates[0]
        for other_s_src, other_s in sha_candidates[1:]:
            if other_s != resolved_sha:
                raise ValueError(
                    f"Conflicting SHA-256 bindings: {base_s_src}={resolved_sha!r} vs {other_s_src}={other_s!r}."
                )

    resolved_text: str | None = None
    if text_candidates:
        base_t_src, resolved_text = text_candidates[0]
        for other_t_src, other_t in text_candidates[1:]:
            if other_t != resolved_text:
                raise ValueError(
                    f"Conflicting text bindings: {base_t_src} vs {other_t_src}."
                )

    resolved_argv: tuple[str, ...] | None = None
    if argv_candidates:
        base_a_src, resolved_argv = argv_candidates[0]
        for other_a_src, other_a in argv_candidates[1:]:
            if other_a != resolved_argv:
                raise ValueError(
                    f"Conflicting argv bindings: {base_a_src} vs {other_a_src}."
                )

    resolved_argv_sha: str | None = None
    if argv_sha_candidates:
        base_as_src, resolved_argv_sha = argv_sha_candidates[0]
        for other_as_src, other_as in argv_sha_candidates[1:]:
            if other_as != resolved_argv_sha:
                raise ValueError(
                    f"Conflicting argv_sha256 bindings: {base_as_src}={resolved_argv_sha!r} "
                    f"vs {other_as_src}={other_as!r}."
                )

    if resolved_text is not None:
        computed_sha = hashlib.sha256(resolved_text.encode("utf-8")).hexdigest()
        if resolved_sha is not None and computed_sha != resolved_sha:
            raise ValueError(
                f"UTF-8 SHA-256 mismatch in {src_prefix}: text hashes to {computed_sha} != declared {resolved_sha}."
            )
        final_sha = computed_sha
        representation = (
            "utf8_text_and_sha256" if resolved_sha is not None else "utf8_text"
        )
    else:
        assert resolved_sha is not None
        final_sha = resolved_sha
        representation = "sha256"

    for rep_src, rep_val in rep_candidates:
        if rep_val != representation:
            raise ValueError(
                f"{rep_src}={rep_val!r} contradicts resolved representation {representation!r}."
            )

    return {
        "state": "available",
        "sha256": final_sha,
        "text": resolved_text,
        "representation": representation,
        "reason": None,
        "controller_contract_justification": None,
        "argv": resolved_argv,
        "argv_sha256": resolved_argv_sha,
        "source_id": resolved_source_id,
    }


def _resolve_parameter_files_for_move(
    *,
    raw_move: Mapping[str, Any],
    raw_ledger_entry: Mapping[str, Any],
    move_prefix: str,
    ledger_prefix: str,
) -> tuple[dict[str, str], dict[str, str]]:
    """Resolve and authenticate literal PHIL parameter_files and their UTF-8 SHA-256 digests."""
    allowed_pf_reps = {"utf8_text", "utf8_text_and_sha256"}

    def _extract_from_container(
        container: Mapping[str, Any], *, prefix: str
    ) -> tuple[dict[str, str], dict[str, str]]:
        texts: dict[str, str] = {}
        shas: dict[str, str] = {}

        if (
            "parameter_files" in container
            and container["parameter_files"] is not None
        ):
            raw_pf = container["parameter_files"]
            if not isinstance(raw_pf, Mapping):
                raise ValueError(f"{prefix}.parameter_files must be a mapping.")
            for pf_name, pf_val in raw_pf.items():
                if (
                    not isinstance(pf_name, str)
                    or not pf_name.strip()
                    or pf_name != pf_name.strip()
                ):
                    raise ValueError(
                        f"{prefix}.parameter_files key must be a non-empty stripped string, "
                        f"got {pf_name!r}."
                    )
                pf_label = f"{prefix}.parameter_files[{pf_name!r}]"
                if isinstance(pf_val, Mapping):
                    allowed_keys = {
                        "state",
                        "representation",
                        "text",
                        "sha256",
                        "verified_artifact_bytes_exist",
                    }
                    unknown = sorted(set(pf_val.keys()) - allowed_keys)
                    if unknown:
                        raise ValueError(
                            f"{pf_label} contains unknown keys: {unknown}."
                        )
                    if pf_val.get("state", "available") != "available":
                        raise ValueError(
                            f"{pf_label}.state must be 'available' with literal PHIL text, "
                            f"got {pf_val.get('state')!r}."
                        )
                    if (
                        "verified_artifact_bytes_exist" in pf_val
                        and pf_val["verified_artifact_bytes_exist"] is not False
                    ):
                        raise ValueError(
                            f"{pf_label}.verified_artifact_bytes_exist must be False."
                        )
                    has_t = "text" in pf_val and pf_val["text"] is not None
                    has_s = "sha256" in pf_val and pf_val["sha256"] is not None
                    if not has_t:
                        raise ValueError(
                            f"{pf_label} is missing literal PHIL 'text'; hash-only parameter "
                            "file entries cannot be inspected by the flag generation guard."
                        )
                    t_raw = pf_val["text"]
                    if not isinstance(t_raw, str) or not t_raw.strip():
                        raise ValueError(
                            f"{pf_label}.text must be a non-empty PHIL string."
                        )
                    comp_sha = hashlib.sha256(t_raw.encode("utf-8")).hexdigest()
                    if has_s:
                        decl_sha = _validate_sha256(
                            pf_val["sha256"], field_name=f"{pf_label}.sha256"
                        )
                        if decl_sha != comp_sha:
                            raise ValueError(
                                f"{pf_label} UTF-8 SHA-256 mismatch: text hashes to "
                                f"{comp_sha} != declared {decl_sha}."
                            )
                    exp_rep = (
                        "utf8_text_and_sha256" if has_s else "utf8_text"
                    )
                    if (
                        "representation" in pf_val
                        and pf_val["representation"] is not None
                    ):
                        rep_v = pf_val["representation"]
                        if (
                            not isinstance(rep_v, str)
                            or rep_v not in allowed_pf_reps
                            or rep_v != exp_rep
                        ):
                            raise ValueError(
                                f"{pf_label}.representation={rep_v!r} contradicts supplied "
                                f"parameter file content (expected {exp_rep!r})."
                            )
                    texts[pf_name] = t_raw
                    shas[pf_name] = comp_sha
                elif isinstance(pf_val, str):
                    if not pf_val.strip():
                        raise ValueError(
                            f"{pf_label} must be a non-empty literal PHIL string."
                        )
                    if pf_val in UNAVAILABLE_EXECUTION_MARKERS:
                        raise ValueError(
                            f"{pf_label}={pf_val!r} is an unavailability marker, not literal PHIL text."
                        )
                    comp_sha = hashlib.sha256(pf_val.encode("utf-8")).hexdigest()
                    texts[pf_name] = pf_val
                    shas[pf_name] = comp_sha
                else:
                    raise ValueError(
                        f"{pf_label} must be a literal PHIL string or typed content mapping."
                    )

        for sha_map_key in ("parameter_files_sha256", "parameter_file_digests"):
            if sha_map_key in container and container[sha_map_key] is not None:
                raw_smap = container[sha_map_key]
                if not isinstance(raw_smap, Mapping):
                    raise ValueError(
                        f"{prefix}.{sha_map_key} must be a mapping of filename -> sha256."
                    )
                for pf_name, raw_sha in raw_smap.items():
                    s_label = f"{prefix}.{sha_map_key}[{pf_name!r}]"
                    decl_sha = _validate_sha256(raw_sha, field_name=s_label)
                    if pf_name not in texts:
                        raise ValueError(
                            f"{s_label} declares SHA-256 for parameter file {pf_name!r} without "
                            "supplying its literal PHIL text in parameter_files; hash-only "
                            "parameter file evidence cannot be verified."
                        )
                    if shas[pf_name] != decl_sha:
                        raise ValueError(
                            f"{s_label} SHA-256 ({decl_sha}) does not match UTF-8 SHA-256 of "
                            f"parameter_files[{pf_name!r}] ({shas[pf_name]})."
                        )
        return texts, shas

    m_texts, m_shas = _extract_from_container(raw_move, prefix=move_prefix)
    l_texts, l_shas = _extract_from_container(
        raw_ledger_entry, prefix=ledger_prefix
    )

    combined_texts = dict(l_texts)
    combined_shas = dict(l_shas)
    for pf_name, m_txt in m_texts.items():
        if pf_name in combined_texts and combined_texts[pf_name] != m_txt:
            raise ValueError(
                f"{move_prefix}.parameter_files[{pf_name!r}] text does not match "
                f"{ledger_prefix}.parameter_files[{pf_name!r}]."
            )
        combined_texts[pf_name] = m_txt
        combined_shas[pf_name] = m_shas[pf_name]

    return combined_texts, combined_shas


_DISPATCHED_GUARD_LAYERS: frozenset[str] = frozenset(
    {"actual_command", "effective_eff"}
)
_DISPATCHED_MACRO_CYCLE_PATHS: frozenset[str] = frozenset(
    {
        "main.number_of_macro_cycles",
        "refinement.main.number_of_macro_cycles",
    }
)
_DISPATCHED_NPROC_PATHS: frozenset[str] = frozenset(
    {
        "main.nproc",
        "refinement.main.nproc",
    }
)
_STRICT_NONNEG_INT_LITERAL_RE = re.compile(r"^(?:0|[1-9][0-9]*)\Z")


def _verify_dispatched_budget_content_bindings(
    *,
    non_generation_assignments: Sequence[Mapping[str, Any]],
    ledger_move: Mapping[str, Any],
    move_prefix: str,
    ledger_prefix: str,
) -> None:
    """Verify explicit macro-cycle and nproc settings in dispatched sources against the budget ledger."""
    expected_planned_cycles = int(ledger_move["planned_macro_cycles"])
    expected_cpu_threads = int(ledger_move["configured_cpu_threads"])

    for assignment in non_generation_assignments:
        layer = str(assignment.get("layer", ""))
        if layer not in _DISPATCHED_GUARD_LAYERS:
            continue
        path = str(assignment.get("path", ""))
        if path in _DISPATCHED_MACRO_CYCLE_PATHS:
            ledger_field = "planned_macro_cycles"
            expected_value = expected_planned_cycles
        elif path in _DISPATCHED_NPROC_PATHS:
            ledger_field = "configured_cpu_threads"
            expected_value = expected_cpu_threads
        else:
            continue

        source_id = str(assignment.get("source_id", ""))
        raw_value = assignment.get("value")
        if (
            not isinstance(raw_value, str)
            or not _STRICT_NONNEG_INT_LITERAL_RE.fullmatch(raw_value)
        ):
            raise ValueError(
                f"{move_prefix} dispatched {layer} assignment (source_id={source_id!r}) "
                f"has invalid non-integer literal {path}={raw_value!r}; expected strict integer "
                f"literal matching {ledger_prefix}.{ledger_field}={expected_value}."
            )
        parsed_value = int(raw_value)
        if parsed_value != expected_value:
            raise ValueError(
                f"{move_prefix} dispatched {layer} assignment (source_id={source_id!r}) "
                f"sets {path}={raw_value!r} ({parsed_value}), which does not match "
                f"{ledger_prefix}.{ledger_field}={expected_value}."
            )


def _verify_move_flag_guard_and_provenance(
    *,
    arm: str,
    move_index: int,
    status: str,
    raw_move: Mapping[str, Any],
    raw_ledger_entry: Mapping[str, Any],
    ledger_move: Mapping[str, Any],
    move_prefix: str,
    ledger_prefix: str,
) -> dict[str, Any]:
    """Bind trajectory move and runtime ledger provenance to phenix_stage2_flags.verify_flag_generation_guard."""
    allow_arm1b_nested = arm == "1b"
    resolved_move_slots: dict[str, dict[str, Any] | None] = {}
    resolved_ledger_raw_slots: dict[str, dict[str, Any] | None] = {}
    for slot_name, sha_keys, text_keys in _PROVENANCE_SLOT_SPECS:
        is_cmd = slot_name in COMMAND_SOURCE_LAYERS
        resolved_move_slots[slot_name] = _resolve_optional_provenance_slot(
            raw_move,
            src_prefix=move_prefix,
            slot_name=slot_name,
            sha_keys=sha_keys,
            text_keys=text_keys,
            is_command_layer=is_cmd,
            allow_arm1b_nested=allow_arm1b_nested,
        )
        resolved_ledger_raw_slots[slot_name] = _resolve_optional_provenance_slot(
            raw_ledger_entry,
            src_prefix=ledger_prefix,
            slot_name=slot_name,
            sha_keys=sha_keys,
            text_keys=text_keys,
            is_command_layer=is_cmd,
            allow_arm1b_nested=allow_arm1b_nested,
        )

    if status == COMPLETED_COMMENSURABLE_STATUS:
        assert resolved_move_slots["actual_command"] is not None
        assert resolved_move_slots["effective_eff"] is not None

    arm1b_prov = ledger_move.get("arm1b_provenance")
    if arm == "1a" and arm1b_prov is not None:
        raise ValueError(
            f"{ledger_prefix}.arm1b_provenance must be None on Arm 1a."
        )
    observed_cycles = int(ledger_move["observed_macro_cycles"])
    ledger_move_status = str(ledger_move["move_status"])

    provenance_representations: dict[str, str] = {}
    guard_sources: dict[str, dict[str, Any]] = {}
    expected_raw_utf8_sha: dict[str, str] = {}
    expected_nul_argv_sha: dict[str, str] = {}
    expected_tokenized_argv: dict[str, tuple[str, ...]] = {}
    bound_custom_source_ids: dict[str, tuple[str, str]] = {}

    for slot_name, sha_keys, text_keys in _PROVENANCE_SLOT_SPECS:
        is_cmd = slot_name in COMMAND_SOURCE_LAYERS
        m_slot = resolved_move_slots[slot_name]
        l_raw_slot = resolved_ledger_raw_slots[slot_name]
        l_slot: dict[str, Any] | None = None
        if arm == "1b":
            if not isinstance(arm1b_prov, Mapping) or slot_name not in arm1b_prov:
                raise ValueError(
                    f"{ledger_prefix} is missing normalized Arm 1b provenance slot {slot_name!r}."
                )
            l_slot = dict(arm1b_prov[slot_name])
            if l_raw_slot is not None:
                l_slot["argv"] = l_raw_slot.get("argv")
                l_slot["argv_sha256"] = l_raw_slot.get("argv_sha256")
                l_slot["source_id"] = l_raw_slot.get("source_id")
        else:
            l_slot = l_raw_slot

        if m_slot is None and l_slot is None:
            raise ValueError(
                f"{move_prefix} is missing required {slot_name!r} provenance/guard source binding."
            )

        if l_slot is not None and l_slot.get("representation") is not None:
            provenance_representations[slot_name] = str(
                l_slot["representation"]
            )
        elif m_slot is not None and m_slot.get("representation") is not None:
            provenance_representations[slot_name] = str(
                m_slot["representation"]
            )

        if m_slot is not None and l_slot is not None:
            if (
                m_slot.get("source_id") is not None
                and l_slot.get("source_id") is not None
                and m_slot["source_id"] != l_slot["source_id"]
            ):
                raise ValueError(
                    f"{move_prefix} {slot_name} source_id ({m_slot['source_id']!r}) does not match "
                    f"{ledger_prefix} {slot_name} source_id ({l_slot['source_id']!r})."
                )
            if m_slot["state"] != l_slot["state"]:
                raise ValueError(
                    f"{move_prefix} {slot_name} state ({m_slot['state']!r}) does not match "
                    f"{ledger_prefix} {slot_name} state ({l_slot['state']!r})."
                )
            if m_slot["state"] == "available":
                if m_slot["sha256"] != l_slot["sha256"]:
                    raise ValueError(
                        f"{move_prefix} {slot_name} SHA-256 ({m_slot['sha256']}) does not match "
                        f"{ledger_prefix} normalized {slot_name} SHA-256 ({l_slot['sha256']})."
                    )
                if (
                    m_slot["text"] is not None
                    and l_slot.get("text") is not None
                    and m_slot["text"] != l_slot["text"]
                ):
                    raise ValueError(
                        f"{move_prefix} {slot_name} text does not match {ledger_prefix} {slot_name} text."
                    )
                if (
                    m_slot.get("argv") is not None
                    and l_slot.get("argv") is not None
                    and m_slot["argv"] != l_slot["argv"]
                ):
                    raise ValueError(
                        f"{move_prefix} {slot_name} argv does not match {ledger_prefix} {slot_name} argv."
                    )
                if (
                    m_slot.get("argv_sha256") is not None
                    and l_slot.get("argv_sha256") is not None
                    and m_slot["argv_sha256"] != l_slot["argv_sha256"]
                ):
                    raise ValueError(
                        f"{move_prefix} {slot_name} argv_sha256 ({m_slot['argv_sha256']}) does not match "
                        f"{ledger_prefix} {slot_name} argv_sha256 ({l_slot['argv_sha256']})."
                    )
            elif m_slot["state"] == "unavailable":
                if m_slot["reason"] != l_slot.get("reason"):
                    raise ValueError(
                        f"{move_prefix} {slot_name} unavailability reason ({m_slot['reason']!r}) "
                        f"does not match {ledger_prefix} ({l_slot.get('reason')!r})."
                    )
            elif m_slot["state"] == "not_applicable":
                if m_slot.get(
                    "controller_contract_justification"
                ) != l_slot.get(
                    "controller_contract_justification"
                ) or m_slot.get("reason") != l_slot.get("reason"):
                    raise ValueError(
                        f"{move_prefix} {slot_name} not_applicable justification does not match "
                        f"{ledger_prefix}."
                    )

        combined_state = str(
            m_slot["state"] if m_slot is not None else l_slot["state"]  # type: ignore[index]
        )
        if (
            status == COMPLETED_COMMENSURABLE_STATUS
            and combined_state == "unavailable"
        ):
            raise ValueError(
                f"{move_prefix} {slot_name} for a completed move must have state='available', "
                "got 'unavailable'."
            )
        if (
            slot_name in ("actual_command", "effective_eff")
            and ledger_move_status == "aborted_before_execution"
        ):
            for slot_origin, slot_claim in (
                (move_prefix, m_slot),
                (ledger_prefix, l_raw_slot),
                (ledger_prefix, l_slot),
            ):
                if slot_claim is not None and (
                    slot_claim.get("state") != "unavailable"
                    or slot_claim.get("reason")
                    not in UNAVAILABLE_NOT_EXECUTED_MARKERS
                ):
                    raise ValueError(
                        f"Arm {arm} {slot_origin} with status 'aborted_before_execution' must record "
                        f"explicit unavailable state (reason in {sorted(UNAVAILABLE_NOT_EXECUTED_MARKERS)}) "
                        f"for {slot_name} (got state={slot_claim.get('state')!r}, "
                        f"reason={slot_claim.get('reason')!r}) and cannot supply a fake hash or command."
                    )
            combined_abort_reason = (
                m_slot.get("reason")
                if m_slot is not None
                else (l_slot.get("reason") if l_slot is not None else None)
            )
            if (
                combined_state != "unavailable"
                or combined_abort_reason not in UNAVAILABLE_NOT_EXECUTED_MARKERS
            ):
                raise ValueError(
                    f"Arm {arm} {move_prefix} with status 'aborted_before_execution' must record "
                    f"explicit unavailable state (reason in {sorted(UNAVAILABLE_NOT_EXECUTED_MARKERS)}) "
                    f"for {slot_name} (got state={combined_state!r}, "
                    f"reason={combined_abort_reason!r}) and cannot supply a fake hash or command."
                )

        if m_slot is not None and m_slot.get("source_id") is not None:
            custom_sid: str | None = str(m_slot["source_id"])
            bound_custom_source_ids[slot_name] = (
                f"{move_prefix}.{slot_name}.source_id",
                custom_sid,
            )
        elif l_slot is not None and l_slot.get("source_id") is not None:
            custom_sid = str(l_slot["source_id"])
            bound_custom_source_ids[slot_name] = (
                f"{ledger_prefix}.{slot_name}.source_id",
                custom_sid,
            )
        else:
            custom_sid = None
        source_id = (
            custom_sid
            if custom_sid is not None
            else f"move_{move_index:02d}_{slot_name}"
        )

        if combined_state == "available":
            combined_sha = str(
                m_slot["sha256"] if m_slot is not None else l_slot["sha256"]  # type: ignore[index]
            )
            combined_text = (
                m_slot["text"]
                if (m_slot is not None and m_slot.get("text") is not None)
                else (l_slot.get("text") if l_slot is not None else None)
            )
            if combined_text is None:
                raise ValueError(
                    f"{move_prefix} {slot_name} supplies hash-only provenance "
                    "(representation='sha256') without raw UTF-8 text; hash-only evidence "
                    "cannot be inspected by verify_flag_generation_guard."
                )
            computed_raw_sha = hashlib.sha256(
                combined_text.encode("utf-8")
            ).hexdigest()
            if computed_raw_sha != combined_sha:
                raise ValueError(
                    f"{move_prefix} {slot_name} raw UTF-8 SHA-256 ({computed_raw_sha}) "
                    f"does not match declared SHA-256 ({combined_sha})."
                )
            expected_raw_utf8_sha[slot_name] = combined_sha

            if is_cmd:
                tokenized_argv = _tokenize_bounded_command_text(
                    combined_text, field_name=f"{move_prefix}.{slot_name}"
                )
                nul_argv_sha = hashlib.sha256(
                    "\x00".join(tokenized_argv).encode("utf-8")
                ).hexdigest()
                decl_argv = (
                    m_slot.get("argv") if m_slot is not None else None
                ) or (l_slot.get("argv") if l_slot is not None else None)
                if decl_argv is not None and tuple(decl_argv) != tokenized_argv:
                    raise ValueError(
                        f"{move_prefix} {slot_name} declared argv {tuple(decl_argv)!r} does not "
                        f"match bounded tokenization of raw command text {tokenized_argv!r}."
                    )
                decl_argv_sha = (
                    m_slot.get("argv_sha256") if m_slot is not None else None
                ) or (
                    l_slot.get("argv_sha256") if l_slot is not None else None
                )
                if decl_argv_sha is not None and decl_argv_sha != nul_argv_sha:
                    raise ValueError(
                        f"{move_prefix} {slot_name} declared NUL-joined argv_sha256 "
                        f"({decl_argv_sha}) does not match computed NUL-joined argv SHA-256 "
                        f"({nul_argv_sha})."
                    )
                expected_tokenized_argv[slot_name] = tokenized_argv
                expected_nul_argv_sha[slot_name] = nul_argv_sha
                guard_sources[slot_name] = {
                    "source_id": source_id,
                    "state": "supplied",
                    "argv": list(tokenized_argv),
                }
            else:
                guard_sources[slot_name] = {
                    "source_id": source_id,
                    "state": "supplied",
                    "phil_text": combined_text,
                }
        elif combined_state == "unavailable":
            combined_reason = str(
                m_slot["reason"] if m_slot is not None else l_slot["reason"]  # type: ignore[index]
            )
            if (
                slot_name in ("actual_command", "effective_eff")
                and observed_cycles > 0
            ):
                for slot_origin, slot_claim in (
                    (move_prefix, m_slot),
                    (ledger_prefix, l_raw_slot),
                    (ledger_prefix, l_slot),
                ):
                    if (
                        slot_claim is not None
                        and slot_claim.get("state") == "unavailable"
                        and slot_claim.get("reason")
                        in UNAVAILABLE_NOT_EXECUTED_MARKERS
                    ):
                        raise ValueError(
                            f"Arm {arm} {slot_origin} {slot_name} binding claims non-execution "
                            f"(reason={slot_claim['reason']!r}), which contradicts "
                            f"observed_macro_cycles={observed_cycles} (> 0) on "
                            f"move_status={ledger_move_status!r}."
                        )
                if combined_reason in UNAVAILABLE_NOT_EXECUTED_MARKERS:
                    raise ValueError(
                        f"Arm {arm} {move_prefix} {slot_name} binding claims non-execution "
                        f"(reason={combined_reason!r}), which contradicts "
                        f"observed_macro_cycles={observed_cycles} (> 0) on "
                        f"move_status={ledger_move_status!r}."
                    )
            guard_sources[slot_name] = {
                "source_id": source_id,
                "state": "unavailable",
                "reason": combined_reason,
            }
        elif combined_state == "not_applicable":
            combined_ccj = (
                m_slot.get("controller_contract_justification")
                if m_slot is not None
                else None
            ) or (
                l_slot.get("controller_contract_justification")
                if l_slot is not None
                else None
            )
            combined_reason = (
                m_slot.get("reason") if m_slot is not None else None
            ) or (l_slot.get("reason") if l_slot is not None else None)
            na_entry: dict[str, Any] = {
                "source_id": source_id,
                "state": "not_applicable",
            }
            if combined_ccj is not None:
                na_entry["controller_contract_justification"] = combined_ccj
            if combined_reason is not None:
                na_entry["reason"] = combined_reason
            guard_sources[slot_name] = na_entry

    # Validate and reconcile optional explicit flag_guard_sources if supplied on move or ledger
    allowed_fg_entry_keys = {
        "source_id",
        "state",
        "argv",
        "phil_text",
        "reason",
        "controller_contract_justification",
    }
    for container_pfx, container_map in (
        (move_prefix, raw_move),
        (ledger_prefix, raw_ledger_entry),
    ):
        if (
            "flag_guard_sources" in container_map
            and container_map["flag_guard_sources"] is not None
        ):
            fg_srcs = container_map["flag_guard_sources"]
            if not isinstance(fg_srcs, Mapping):
                raise ValueError(
                    f"{container_pfx}.flag_guard_sources must be a mapping."
                )
            unknown_layers = sorted(
                set(fg_srcs.keys()) - set(CANONICAL_SOURCE_LAYERS)
            )
            if unknown_layers:
                raise ValueError(
                    f"{container_pfx}.flag_guard_sources contains unknown layers: {unknown_layers}."
                )
            for layer_name, fg_entry in fg_srcs.items():
                fg_label = f"{container_pfx}.flag_guard_sources[{layer_name!r}]"
                if not isinstance(fg_entry, Mapping):
                    raise ValueError(f"{fg_label} must be a mapping.")
                unknown_fg_keys = sorted(
                    set(fg_entry.keys()) - allowed_fg_entry_keys
                )
                if unknown_fg_keys:
                    raise ValueError(
                        f"{fg_label} contains unknown keys: {unknown_fg_keys}."
                    )
                if layer_name in COMMAND_SOURCE_LAYERS and "phil_text" in fg_entry:
                    raise ValueError(
                        f"{fg_label}.phil_text is invalid: command layer {layer_name!r} "
                        "requires tokenized 'argv', not 'phil_text'."
                    )
                if layer_name == "effective_eff" and "argv" in fg_entry:
                    raise ValueError(
                        f"{fg_label}.argv is invalid: 'effective_eff' requires raw "
                        "'phil_text', not 'argv'."
                    )

                derived_entry = guard_sources[layer_name]
                if "source_id" in fg_entry:
                    if fg_entry["source_id"] is None:
                        raise ValueError(
                            f"{fg_label}.source_id must be a non-empty safe identifier string."
                        )
                    sid = _validate_safe_id(
                        fg_entry["source_id"],
                        field_name=f"{fg_label}.source_id",
                    )
                    if layer_name in bound_custom_source_ids:
                        prev_origin, prev_sid = bound_custom_source_ids[
                            layer_name
                        ]
                        if sid != prev_sid:
                            raise ValueError(
                                f"{fg_label}.source_id={sid!r} conflicts with "
                                f"{prev_origin}={prev_sid!r}."
                            )
                    bound_custom_source_ids[layer_name] = (
                        f"{fg_label}.source_id",
                        sid,
                    )
                    derived_entry["source_id"] = sid

                if "state" in fg_entry:
                    fg_state = fg_entry["state"]
                    if not isinstance(fg_state, str) or fg_state not in {
                        "supplied",
                        "unavailable",
                        "not_applicable",
                    }:
                        raise ValueError(
                            f"{fg_label}.state must be one of ['not_applicable', 'supplied', 'unavailable'], "
                            f"got {fg_state!r}."
                        )
                    if fg_state != derived_entry["state"]:
                        raise ValueError(
                            f"{fg_label}.state={fg_state!r} contradicts provenance-bound "
                            f"state {derived_entry['state']!r}."
                        )

                if derived_entry["state"] == "supplied":
                    if (
                        fg_entry.get("reason") is not None
                        or fg_entry.get("controller_contract_justification")
                        is not None
                    ):
                        raise ValueError(
                            f"{fg_label} with state='supplied' cannot carry 'reason' or "
                            "'controller_contract_justification'."
                        )
                    if layer_name in COMMAND_SOURCE_LAYERS:
                        if "argv" in fg_entry:
                            if fg_entry["argv"] is None:
                                raise ValueError(
                                    f"{fg_label}.argv cannot be None when state='supplied'."
                                )
                            fg_argv = _validate_argv_token_sequence(
                                fg_entry["argv"],
                                field_name=f"{fg_label}.argv",
                            )
                            if list(fg_argv) != derived_entry["argv"]:
                                raise ValueError(
                                    f"{fg_label}.argv={list(fg_argv)!r} does not match "
                                    f"provenance-tokenized argv {derived_entry['argv']!r}."
                                )
                    else:
                        if "phil_text" in fg_entry:
                            fg_phil = fg_entry["phil_text"]
                            if (
                                not isinstance(fg_phil, str)
                                or not fg_phil.strip()
                            ):
                                raise ValueError(
                                    f"{fg_label}.phil_text must be a non-empty string when state='supplied'."
                                )
                            if fg_phil != derived_entry["phil_text"]:
                                raise ValueError(
                                    f"{fg_label}.phil_text does not match provenance effective_eff text."
                                )
                elif derived_entry["state"] == "unavailable":
                    if (
                        fg_entry.get("argv") is not None
                        or fg_entry.get("phil_text") is not None
                        or fg_entry.get("controller_contract_justification")
                        is not None
                    ):
                        raise ValueError(
                            f"{fg_label} with state='unavailable' cannot carry 'argv', 'phil_text', "
                            "or 'controller_contract_justification'."
                        )
                    if "reason" in fg_entry:
                        fg_reason = fg_entry["reason"]
                        if (
                            not isinstance(fg_reason, str)
                            or not fg_reason.strip()
                        ):
                            raise ValueError(
                                f"{fg_label}.reason must be a non-empty string when state='unavailable'."
                            )
                        if fg_reason.strip() != derived_entry["reason"]:
                            raise ValueError(
                                f"{fg_label}.reason={fg_reason!r} does not match "
                                f"provenance unavailability reason {derived_entry['reason']!r}."
                            )
                elif derived_entry["state"] == "not_applicable":
                    if (
                        fg_entry.get("argv") is not None
                        or fg_entry.get("phil_text") is not None
                    ):
                        raise ValueError(
                            f"{fg_label} with state='not_applicable' cannot carry 'argv' or 'phil_text'."
                        )
                    if "controller_contract_justification" in fg_entry:
                        fg_ccj = fg_entry["controller_contract_justification"]
                        if not isinstance(fg_ccj, str) or not fg_ccj.strip():
                            raise ValueError(
                                f"{fg_label}.controller_contract_justification must be a non-empty string "
                                "when state='not_applicable'."
                            )
                        exp_ccj = derived_entry.get(
                            "controller_contract_justification"
                        )
                        if exp_ccj is not None and fg_ccj.strip() != exp_ccj:
                            raise ValueError(
                                f"{fg_label}.controller_contract_justification={fg_ccj!r} does not match "
                                f"provenance controller_contract_justification {exp_ccj!r}."
                            )
                        derived_entry["controller_contract_justification"] = (
                            fg_ccj.strip()
                        )
                    if "reason" in fg_entry:
                        fg_na_reason = fg_entry["reason"]
                        if (
                            not isinstance(fg_na_reason, str)
                            or not fg_na_reason.strip()
                        ):
                            raise ValueError(
                                f"{fg_label}.reason must be a non-empty string when state='not_applicable'."
                            )
                        exp_na_reason = derived_entry.get("reason")
                        if (
                            exp_na_reason is not None
                            and fg_na_reason.strip() != exp_na_reason
                        ):
                            raise ValueError(
                                f"{fg_label}.reason={fg_na_reason!r} does not match "
                                f"provenance not_applicable reason {exp_na_reason!r}."
                            )
                        derived_entry["reason"] = fg_na_reason.strip()

    param_files, param_file_shas = _resolve_parameter_files_for_move(
        raw_move=raw_move,
        raw_ledger_entry=raw_ledger_entry,
        move_prefix=move_prefix,
        ledger_prefix=ledger_prefix,
    )

    replayed_guard = verify_flag_generation_guard(
        arm=arm,
        sources=guard_sources,
        parameter_files=param_files if param_files else None,
    )
    _verify_dispatched_budget_content_bindings(
        non_generation_assignments=replayed_guard["non_generation_assignments"],
        ledger_move=ledger_move,
        move_prefix=move_prefix,
        ledger_prefix=ledger_prefix,
    )

    # Verify source_digests in replayed_guard match our distinct NUL-argv vs raw UTF-8 digests
    command_digest_bindings: dict[str, dict[str, Any]] = {}
    for layer_name in CANONICAL_SOURCE_LAYERS:
        g_entry = guard_sources[layer_name]
        if g_entry["state"] == "supplied":
            sid = g_entry["source_id"]
            guard_digest = replayed_guard["source_digests"].get(sid)
            if layer_name in COMMAND_SOURCE_LAYERS:
                exp_nul_sha = expected_nul_argv_sha[layer_name]
                exp_raw_sha = expected_raw_utf8_sha[layer_name]
                if guard_digest != exp_nul_sha:
                    raise ValueError(
                        f"{move_prefix} {layer_name} guard NUL-argv digest ({guard_digest}) "
                        f"does not match expected {exp_nul_sha}."
                    )
                command_digest_bindings[layer_name] = {
                    "source_id": sid,
                    "raw_utf8_sha256": exp_raw_sha,
                    "nul_argv_sha256": exp_nul_sha,
                    "argv": expected_tokenized_argv[layer_name],
                }
            else:
                exp_raw_sha = expected_raw_utf8_sha[layer_name]
                if guard_digest != exp_raw_sha:
                    raise ValueError(
                        f"{move_prefix} {layer_name} guard UTF-8 digest ({guard_digest}) "
                        f"does not match expected {exp_raw_sha}."
                    )

    for pf_name, exp_pf_sha in param_file_shas.items():
        guard_pf_sha = replayed_guard["source_digests"].get(pf_name)
        if guard_pf_sha != exp_pf_sha:
            raise ValueError(
                f"{move_prefix} parameter_files[{pf_name!r}] guard digest ({guard_pf_sha}) "
                f"does not match expected UTF-8 SHA-256 ({exp_pf_sha})."
            )

    def _normalize_strict_json_comparable(
        val: Any, *, field_name: str
    ) -> tuple[str, Any]:
        if val is None:
            return ("null", None)
        if isinstance(val, bool):
            return ("bool", val)
        if isinstance(val, int):
            return ("int", val)
        if isinstance(val, float):
            if not math.isfinite(val):
                raise ValueError(
                    f"{field_name} must not contain NaN or infinity."
                )
            return ("float", val)
        if isinstance(val, str):
            return ("str", val)
        if isinstance(val, Mapping):
            norm_map: dict[str, Any] = {}
            for k, v in val.items():
                if not isinstance(k, str):
                    raise ValueError(
                        f"{field_name} mapping key must be a string, got {type(k).__name__}."
                    )
                norm_map[k] = _normalize_strict_json_comparable(
                    v, field_name=f"{field_name}.{k}"
                )
            return ("map", norm_map)
        if isinstance(val, (list, tuple)) or (
            isinstance(val, Sequence)
            and not isinstance(val, (str, bytes, bytearray))
        ):
            return (
                "seq",
                tuple(
                    _normalize_strict_json_comparable(
                        item, field_name=f"{field_name}[{idx}]"
                    )
                    for idx, item in enumerate(val)
                ),
            )
        raise ValueError(
            f"{field_name} has unsupported non-JSON-compatible type {type(val).__name__}."
        )

    # Validate optional claimed flag_guard_receipt against replayed_guard
    for container_pfx, container_map in (
        (move_prefix, raw_move),
        (ledger_prefix, raw_ledger_entry),
    ):
        if (
            "flag_guard_receipt" in container_map
            and container_map["flag_guard_receipt"] is not None
        ):
            claimed_fg = container_map["flag_guard_receipt"]
            if not isinstance(claimed_fg, Mapping):
                raise ValueError(
                    f"{container_pfx}.flag_guard_receipt must be a mapping."
                )
            unknown_fg_rec_keys = sorted(
                set(claimed_fg.keys()) - set(replayed_guard.keys())
            )
            if unknown_fg_rec_keys:
                raise ValueError(
                    f"{container_pfx}.flag_guard_receipt contains unsupported keys: "
                    f"{unknown_fg_rec_keys}."
                )
            if not claimed_fg:
                raise ValueError(
                    f"{container_pfx}.flag_guard_receipt must be a non-empty mapping when supplied."
                )
            for fg_key, fg_val in claimed_fg.items():
                fg_field_label = f"{container_pfx}.flag_guard_receipt.{fg_key}"
                norm_claimed = _normalize_strict_json_comparable(
                    fg_val, field_name=fg_field_label
                )
                norm_replayed = _normalize_strict_json_comparable(
                    replayed_guard[fg_key],
                    field_name=f"replayed_guard.{fg_key}",
                )
                if norm_claimed != norm_replayed:
                    raise ValueError(
                        f"{fg_field_label} ({fg_val!r}) contradicts replayed flag guard "
                        f"({replayed_guard[fg_key]!r})."
                    )

    # Validate raw_move["flag_guard_verified"] against replayed_guard
    fg_claimed = raw_move["flag_guard_verified"]
    if not replayed_guard["incomplete"]:
        assert replayed_guard["guard_ok"] is True
        if fg_claimed is not True:
            raise ValueError(
                f"{move_prefix}.flag_guard_verified must be True (fail-closed U12 flag guard), "
                f"got {fg_claimed!r}."
            )
        flag_guard_verified_out: bool | str = True
    else:
        if status == COMPLETED_COMMENSURABLE_STATUS:
            raise ValueError(
                f"{move_prefix} (completed commensurable) cannot have incomplete flag-guard "
                f"verification (unavailable_sources={replayed_guard['unavailable_sources']!r})."
            )
        if isinstance(fg_claimed, bool):
            raise ValueError(
                f"{move_prefix}.flag_guard_verified={fg_claimed!r} fabricates a boolean "
                "verification result on an incomplete failed move with unavailable sources "
                f"({sorted(replayed_guard['unavailable_sources'].keys())}); "
                "use 'incomplete' or 'unavailable'."
            )
        if isinstance(fg_claimed, str):
            if fg_claimed not in (
                "incomplete",
                "unavailable",
                "INCOMPLETE_UNAVAILABLE_SOURCES",
            ):
                raise ValueError(
                    f"{move_prefix}.flag_guard_verified on an incomplete failed move must be "
                    f"'incomplete' or 'unavailable', got {fg_claimed!r}."
                )
        elif isinstance(fg_claimed, Mapping):
            allowed_fg_keys = {"state", "reason"}
            unknown_fg = sorted(set(fg_claimed.keys()) - allowed_fg_keys)
            if unknown_fg:
                raise ValueError(
                    f"{move_prefix}.flag_guard_verified contains unknown keys: {unknown_fg}."
                )
            st_fg = fg_claimed.get("state")
            if st_fg not in ("incomplete", "unavailable"):
                raise ValueError(
                    f"{move_prefix}.flag_guard_verified.state must be 'incomplete' or 'unavailable', "
                    f"got {st_fg!r}."
                )
            if "reason" in fg_claimed and (
                not isinstance(fg_claimed["reason"], str)
                or not fg_claimed["reason"].strip()
            ):
                raise ValueError(
                    f"{move_prefix}.flag_guard_verified.reason must be a non-empty string."
                )
        else:
            raise ValueError(
                f"{move_prefix}.flag_guard_verified on an incomplete failed move must be "
                f"'incomplete' or 'unavailable', got {fg_claimed!r}."
            )
        flag_guard_verified_out = "incomplete"

    return {
        "actual_command_sha256": expected_raw_utf8_sha.get("actual_command"),
        "effective_eff_sha256": expected_raw_utf8_sha.get("effective_eff"),
        "provenance_representations": provenance_representations,
        "command_digest_bindings": command_digest_bindings,
        "parameter_files": dict(param_files),
        "parameter_file_digests": dict(param_file_shas),
        "flag_guard_verified": flag_guard_verified_out,
        "flag_guard_status": replayed_guard["status"],
        "flag_guard_incomplete": replayed_guard["incomplete"],
        "replayed_flag_guard": replayed_guard,
    }


def verify_trajectory(
    trajectory: Mapping[str, Any],
    *,
    readout_contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate an offline outer-loop trajectory bundle, replaying redaction, U12 budgets, selection, and stopping.

    Epistemic note:
    - Requires an explicit caller-supplied out-of-band ``readout_contract``; never uses an
      envelope's embedded contract as authority. ``readout_contract`` binds declared metadata
      only and does not prove actual measurement sourcing or establish devfreeze policy.
    - This function validates supplied receipt structures, canonical JSON hashes, U12 budget
      ledgers, prefix cap-exhaustion rules, and deterministic selector/stop replay.
    - It does NOT prove OS/process isolation, whole-log text redaction outside the projected
      selection view, live admission-guard execution, or runtime correctness.
    - Move-ledger completion is never promoted to scientific arm completion
      (``scientific_arm_completion="not_assessed"``).
    """
    validated_contract = validate_readout_contract(readout_contract)
    if not isinstance(trajectory, Mapping):
        raise ValueError("trajectory must be a mapping.")
    if (
        "readout_contract" in trajectory
        and trajectory["readout_contract"] is not None
    ):
        embedded_contract = validate_readout_contract(
            trajectory["readout_contract"]
        )
        if embedded_contract != validated_contract:
            raise ValueError(
                "trajectory embedded readout_contract contradicts caller-bound out-of-band "
                "readout_contract (an envelope cannot authorize its own metadata)."
            )

    required_top = {
        "arm",
        "target_id",
        "subject_id",
        "start_model_sha256",
        "work_reflection_domain_sha256",
        "flag_partition_sha256",
        "sleep_partition_sha256",
        "snapshot_binding_sha256",
        "tie_group_policy",
        "residual_tie_policy",
        "reference_convention",
        "start_record",
        "claimed_start_redacted_view_sha256",
        "moves",
        "budget_ledger",
        "claimed_selection",
        "claimed_stop_decision",
    }
    missing_top = sorted(required_top - set(trajectory.keys()))
    if missing_top:
        raise ValueError(
            f"trajectory is missing required top-level keys: {missing_top}."
        )

    arm = trajectory["arm"]
    if not isinstance(arm, str) or arm not in CONTROLLER_ARM_IDS:
        raise ValueError(
            f"trajectory.arm must be one of {CONTROLLER_ARM_IDS}, got {arm!r}."
        )
    target_id = _validate_safe_id(
        trajectory["target_id"], field_name="trajectory.target_id"
    )
    subject_id = _validate_safe_id(
        trajectory["subject_id"], field_name="trajectory.subject_id"
    )
    start_model_sha = _validate_sha256(
        trajectory["start_model_sha256"],
        field_name="trajectory.start_model_sha256",
    )
    work_domain_sha = _validate_sha256(
        trajectory["work_reflection_domain_sha256"],
        field_name="trajectory.work_reflection_domain_sha256",
    )
    flag_partition_sha = _validate_sha256(
        trajectory["flag_partition_sha256"],
        field_name="trajectory.flag_partition_sha256",
    )
    sleep_partition_sha = _validate_sha256(
        trajectory["sleep_partition_sha256"],
        field_name="trajectory.sleep_partition_sha256",
    )
    snapshot_binding_sha = _validate_sha256(
        trajectory["snapshot_binding_sha256"],
        field_name="trajectory.snapshot_binding_sha256",
    )

    tie_group_policy = _validate_policy_choice(
        trajectory["tie_group_policy"],
        allowed=ALLOWED_TIE_GROUP_POLICIES,
        field_name="trajectory.tie_group_policy",
    )
    residual_tie_policy = _validate_policy_choice(
        trajectory["residual_tie_policy"],
        allowed=ALLOWED_RESIDUAL_TIE_POLICIES,
        field_name="trajectory.residual_tie_policy",
    )
    reference_convention = _validate_policy_choice(
        trajectory["reference_convention"],
        allowed=ALLOWED_STOP_REFERENCE_CONVENTIONS,
        field_name="trajectory.reference_convention",
    )

    start_redacted = redact_starting_geometry_for_selection(
        trajectory["start_record"],
        readout_contract=validated_contract,
    )
    start_rec: StartingGeometryRecord = start_redacted["record"]
    claimed_start_sha = _validate_sha256(
        trajectory["claimed_start_redacted_view_sha256"],
        field_name="trajectory.claimed_start_redacted_view_sha256",
    )
    if start_redacted["redacted_view_sha256"] != claimed_start_sha:
        raise ValueError(
            f"Start record redacted_view_sha256 mismatch: computed "
            f"{start_redacted['redacted_view_sha256']} != claimed {claimed_start_sha}."
        )
    if (
        start_rec.target_id != target_id
        or start_rec.subject_id != subject_id
        or start_rec.start_model_sha256 != start_model_sha
        or start_rec.work_reflection_domain_sha256 != work_domain_sha
    ):
        raise ValueError(
            "start_record lineage fields do not match trajectory top-level target/subject/model/domain bindings."
        )

    raw_moves = trajectory["moves"]
    raw_budget_ledger = trajectory["budget_ledger"]
    if (
        isinstance(raw_moves, (str, bytes, Mapping))
        or not isinstance(raw_moves, Sequence)
        or len(raw_moves) == 0
    ):
        raise ValueError("trajectory.moves must be a non-empty sequence.")
    if (
        isinstance(raw_budget_ledger, (str, bytes, Mapping))
        or not isinstance(raw_budget_ledger, Sequence)
        or len(raw_budget_ledger) != len(raw_moves)
    ):
        raise ValueError(
            "trajectory.budget_ledger must be a sequence with the exact same length as trajectory.moves."
        )

    budget_summary = verify_controller_budget(arm=arm, ledger=raw_budget_ledger)

    # Check prefix cap exhaustion and prior-move failure continuation before each subsequent move k >= 2
    for prefix_len in range(1, len(raw_budget_ledger)):
        prefix_summary = verify_controller_budget(
            arm=arm, ledger=raw_budget_ledger[:prefix_len]
        )
        if prefix_summary["contains_failed_or_aborted_move"]:
            raise ValueError(
                f"Trajectory prefix 1..{prefix_len} contains a failed or aborted move before "
                f"move {prefix_len + 1}; continuation after a failed/aborted move is unsupported "
                "pending an explicit transition policy."
            )
        if not prefix_summary["budget_ok"]:
            raise ValueError(
                f"Trajectory prefix 1..{prefix_len} already violated U12 budget before "
                f"move {prefix_len + 1}: {prefix_summary['violation_reasons']!r}."
            )
        prefix_exhausted, prefix_reasons = _evaluate_budget_cap_exhaustion(
            prefix_summary
        )
        if prefix_exhausted:
            raise ValueError(
                f"Trajectory prefix 1..{prefix_len} already exhausted U12 cap(s) "
                f"{prefix_reasons} before move {prefix_len + 1}; U10/U12 forbids executing "
                "another move after a cap is reached (even with zero incremental usage)."
            )

    seen_move_ids: set[str] = set()
    validated_commensurable_by_index: dict[int, CandidateSelectionRecord] = {}
    pool_inputs: list[Mapping[str, Any] | CandidateSelectionRecord] = []
    verified_move_summaries: list[dict[str, Any]] = []

    for idx, raw_move in enumerate(raw_moves):
        expected_idx = idx + 1
        prefix = f"trajectory.moves[{idx}]"
        if not isinstance(raw_move, Mapping):
            raise ValueError(f"{prefix} must be a mapping.")

        for req_m_key in (
            "move_id",
            "move_index",
            "status",
            "target_id",
            "subject_id",
            "work_reflection_domain_sha256",
            "flag_partition_sha256",
            "sleep_partition_sha256",
            "snapshot_binding_sha256",
            "flag_guard_verified",
        ):
            if req_m_key not in raw_move:
                raise ValueError(f"{prefix} is missing required key {req_m_key!r}.")

        move_id = _validate_safe_id(
            raw_move["move_id"], field_name=f"{prefix}.move_id"
        )
        if move_id in seen_move_ids:
            raise ValueError(f"Duplicate move_id {move_id!r} in trajectory.moves.")
        seen_move_ids.add(move_id)

        move_index = _validate_strict_int(
            raw_move["move_index"],
            field_name=f"{prefix}.move_index",
            min_value=1,
        )
        if move_index != expected_idx:
            raise ValueError(
                f"{prefix}.move_index must be {expected_idx}, got {move_index}."
            )

        if raw_move["target_id"] != target_id:
            raise ValueError(f"{prefix}.target_id mismatch.")
        if raw_move["subject_id"] != subject_id:
            raise ValueError(f"{prefix}.subject_id mismatch.")
        if raw_move["work_reflection_domain_sha256"] != work_domain_sha:
            raise ValueError(
                f"{prefix}.work_reflection_domain_sha256 mismatch."
            )
        if raw_move["flag_partition_sha256"] != flag_partition_sha:
            raise ValueError(f"{prefix}.flag_partition_sha256 mismatch.")
        if raw_move["sleep_partition_sha256"] != sleep_partition_sha:
            raise ValueError(f"{prefix}.sleep_partition_sha256 mismatch.")
        if raw_move["snapshot_binding_sha256"] != snapshot_binding_sha:
            raise ValueError(f"{prefix}.snapshot_binding_sha256 mismatch.")
        status = raw_move["status"]
        if not isinstance(status, str) or status not in U08_STATUS_CODES:
            raise ValueError(
                f"{prefix}.status must be one of {U08_STATUS_CODES}, got {status!r}."
            )
        if status == "INCOMMENSURABLE_ARM3A_AUTODETECT_MISMATCH":
            raise ValueError(
                f"{prefix}.status={status!r} is applicable only to arm '3a', "
                f"not arm {arm!r}."
            )

        ledger_move = budget_summary["moves"][idx]
        if status == COMPLETED_COMMENSURABLE_STATUS:
            if ledger_move["move_status"] != "completed":
                raise ValueError(
                    f"{prefix} has status={status!r} but budget_ledger[{idx}].move_status="
                    f"{ledger_move['move_status']!r}."
                )
            for req_exec_key in (
                "actual_command_sha256",
                "effective_eff_sha256",
                "claimed_redacted_view_sha256",
            ):
                if req_exec_key not in raw_move:
                    raise ValueError(
                        f"{prefix} (completed commensurable) requires {req_exec_key!r}."
                    )
            _validate_sha256(
                raw_move["actual_command_sha256"],
                field_name=f"{prefix}.actual_command_sha256",
            )
            _validate_sha256(
                raw_move["effective_eff_sha256"],
                field_name=f"{prefix}.effective_eff_sha256",
            )
            claimed_view_sha = _validate_sha256(
                raw_move["claimed_redacted_view_sha256"],
                field_name=f"{prefix}.claimed_redacted_view_sha256",
            )
            prov_agreement = _verify_move_flag_guard_and_provenance(
                arm=arm,
                move_index=move_index,
                status=status,
                raw_move=raw_move,
                raw_ledger_entry=raw_budget_ledger[idx],
                ledger_move=ledger_move,
                move_prefix=prefix,
                ledger_prefix=f"trajectory.budget_ledger[{idx}]",
            )

            redacted_move = redact_candidate_for_selection(
                raw_move, readout_contract=validated_contract
            )
            if redacted_move["redacted_view_sha256"] != claimed_view_sha:
                raise ValueError(
                    f"{prefix} redacted_view_sha256 mismatch: computed "
                    f"{redacted_move['redacted_view_sha256']} != claimed {claimed_view_sha}."
                )
            cand_rec: CandidateSelectionRecord = redacted_move["record"]
            validated_commensurable_by_index[move_index] = cand_rec
            pool_inputs.append(cand_rec)
            verified_move_summaries.append(
                {
                    "move_id": move_id,
                    "move_index": move_index,
                    "status": status,
                    "redacted_view_sha256": claimed_view_sha,
                    "actual_command_sha256": prov_agreement[
                        "actual_command_sha256"
                    ],
                    "effective_eff_sha256": prov_agreement[
                        "effective_eff_sha256"
                    ],
                    "provenance_representations": prov_agreement[
                        "provenance_representations"
                    ],
                    "command_digest_bindings": prov_agreement[
                        "command_digest_bindings"
                    ],
                    "parameter_files": prov_agreement["parameter_files"],
                    "parameter_file_digests": prov_agreement[
                        "parameter_file_digests"
                    ],
                    "flag_guard_verified": prov_agreement[
                        "flag_guard_verified"
                    ],
                    "flag_guard_status": prov_agreement["flag_guard_status"],
                    "flag_guard_incomplete": prov_agreement[
                        "flag_guard_incomplete"
                    ],
                    "replayed_flag_guard": prov_agreement[
                        "replayed_flag_guard"
                    ],
                }
            )
        else:
            # Failed or incommensurable move: retained in trajectory, never fabricated into a selectable candidate
            assert status in U08_FAILURE_STATUS_CODES
            prov_agreement = _verify_move_flag_guard_and_provenance(
                arm=arm,
                move_index=move_index,
                status=status,
                raw_move=raw_move,
                raw_ledger_entry=raw_budget_ledger[idx],
                ledger_move=ledger_move,
                move_prefix=prefix,
                ledger_prefix=f"trajectory.budget_ledger[{idx}]",
            )
            pool_inputs.append(
                {
                    "move_id": move_id,
                    "move_index": move_index,
                    "status": status,
                    "target_id": target_id,
                    "subject_id": subject_id,
                }
            )
            verified_move_summaries.append(
                {
                    "move_id": move_id,
                    "move_index": move_index,
                    "status": status,
                    "redacted_view_sha256": None,
                    "actual_command_sha256": prov_agreement[
                        "actual_command_sha256"
                    ],
                    "effective_eff_sha256": prov_agreement[
                        "effective_eff_sha256"
                    ],
                    "provenance_representations": prov_agreement[
                        "provenance_representations"
                    ],
                    "command_digest_bindings": prov_agreement[
                        "command_digest_bindings"
                    ],
                    "parameter_files": prov_agreement["parameter_files"],
                    "parameter_file_digests": prov_agreement[
                        "parameter_file_digests"
                    ],
                    "flag_guard_verified": prov_agreement[
                        "flag_guard_verified"
                    ],
                    "flag_guard_status": prov_agreement["flag_guard_status"],
                    "flag_guard_incomplete": prov_agreement[
                        "flag_guard_incomplete"
                    ],
                    "replayed_flag_guard": prov_agreement[
                        "replayed_flag_guard"
                    ],
                }
            )

        # Verify optional per-move selection checkpoint if recorded
        if (
            "selection_checkpoint" in raw_move
            and raw_move["selection_checkpoint"] is not None
        ):
            chk = raw_move["selection_checkpoint"]
            if not isinstance(chk, Mapping):
                raise ValueError(
                    f"{prefix}.selection_checkpoint must be a mapping."
                )
            prefix_sel = select_candidate(
                pool_inputs,
                start_rec,
                tie_group_policy=tie_group_policy,
                residual_tie_policy=residual_tie_policy,
                readout_contract=validated_contract,
            )
            if (
                chk.get("selected_move_id") != prefix_sel["selected_move_id"]
                or chk.get("selection_state") != prefix_sel["selection_state"]
            ):
                raise ValueError(
                    f"{prefix}.selection_checkpoint mismatch: claimed {chk!r} vs "
                    f"replayed {prefix_sel['selection_state']!r}/{prefix_sel['selected_move_id']!r}."
                )

    replayed_selection = select_candidate(
        pool_inputs,
        start_rec,
        tie_group_policy=tie_group_policy,
        residual_tie_policy=residual_tie_policy,
        readout_contract=validated_contract,
    )
    claimed_sel = trajectory["claimed_selection"]
    if not isinstance(claimed_sel, Mapping):
        raise ValueError("trajectory.claimed_selection must be a mapping.")
    if (
        claimed_sel.get("selection_state")
        != replayed_selection["selection_state"]
        or claimed_sel.get("selected_move_id")
        != replayed_selection["selected_move_id"]
    ):
        raise ValueError(
            "trajectory.claimed_selection does not match deterministic replay: "
            f"claimed ({claimed_sel.get('selection_state')!r}, {claimed_sel.get('selected_move_id')!r}) "
            f"vs replayed ({replayed_selection['selection_state']!r}, {replayed_selection['selected_move_id']!r})."
        )
    if "tied_move_ids" in claimed_sel:
        if tuple(claimed_sel["tied_move_ids"]) != replayed_selection["tied_move_ids"]:
            raise ValueError(
                f"trajectory.claimed_selection.tied_move_ids ({claimed_sel['tied_move_ids']!r}) "
                f"does not match replayed {replayed_selection['tied_move_ids']!r}."
            )

    # Replay U10/U12 stopping at EVERY trajectory prefix 1..len(raw_moves).
    # Any triggered stop at prefix_len < len(raw_moves) forbids executing move prefix_len + 1.
    replayed_stop: dict[str, Any] | None = None
    for prefix_len in range(1, len(raw_moves) + 1):
        prefix_commensurable_by_index = {
            m_i: rec
            for m_i, rec in validated_commensurable_by_index.items()
            if m_i <= prefix_len
        }
        prefix_trailing_indices: list[int] = []
        for m_idx in range(prefix_len, 0, -1):
            if m_idx in prefix_commensurable_by_index:
                prefix_trailing_indices.append(m_idx)
            else:
                break
        prefix_trailing_indices.reverse()

        prefix_delta_pairs: list[dict[str, Any]] = []
        for m_idx in prefix_trailing_indices[-2:]:
            c_rec = prefix_commensurable_by_index[m_idx]
            ref_id, ref_r, ref_clash = _extract_reference_metrics_for_stop(
                reference_convention=reference_convention,
                curr_idx=m_idx,
                validated_moves_by_index=prefix_commensurable_by_index,
                start_rec=start_rec,
                tie_group_policy=tie_group_policy,
                residual_tie_policy=residual_tie_policy,
                readout_contract=validated_contract,
            )
            c_r = c_rec.metrics["r_work"].value
            c_clash = c_rec.metrics["clashscore"].value
            prefix_delta_pairs.append(
                {
                    "move_id": c_rec.move_id,
                    "move_index": m_idx,
                    "move_status": COMPLETED_COMMENSURABLE_STATUS,
                    "reference_id": ref_id,
                    "reference_convention": reference_convention,
                    "candidate_r_work": c_r,
                    "reference_r_work": ref_r,
                    "candidate_clashscore": c_clash,
                    "reference_clashscore": ref_clash,
                }
            )

        prefix_budget_summary = (
            budget_summary
            if prefix_len == len(raw_moves)
            else verify_controller_budget(
                arm=arm, ledger=raw_budget_ledger[:prefix_len]
            )
        )
        prefix_stop = stop_decision(
            consecutive_delta_pairs=prefix_delta_pairs,
            reference_convention=reference_convention,
            budget_summary=prefix_budget_summary,
            arm=arm,
            budget_ledger=raw_budget_ledger[:prefix_len],
            require_budget_evidence=True,
            start_record=start_rec,
            reference_records=prefix_commensurable_by_index,
            readout_contract=validated_contract,
            require_reference_evidence=True,
            tie_group_policy=tie_group_policy,
            residual_tie_policy=residual_tie_policy,
        )
        if prefix_len < len(raw_moves) and prefix_stop["should_stop"]:
            raise ValueError(
                f"Trajectory prefix 1..{prefix_len} already triggered U10/U12 stop "
                f"(reasons={prefix_stop['stop_reasons']!r}, "
                f"stagnation_triggered={prefix_stop['stagnation_triggered']}, "
                f"budget_cap_exhausted={prefix_stop['budget_cap_exhausted']}, "
                f"budget_violation={prefix_stop['budget_violation']}) "
                f"before move {prefix_len + 1}; executing additional moves after a "
                "triggered stop decision is forbidden."
            )
        if prefix_len == len(raw_moves):
            replayed_stop = prefix_stop

    assert replayed_stop is not None
    claimed_stop = trajectory["claimed_stop_decision"]
    if not isinstance(claimed_stop, Mapping):
        raise ValueError("trajectory.claimed_stop_decision must be a mapping.")
    for stop_key in (
        "should_stop",
        "stagnation_triggered",
        "budget_cap_exhausted",
    ):
        if (
            stop_key not in claimed_stop
            or claimed_stop[stop_key] != replayed_stop[stop_key]
        ):
            raise ValueError(
                f"trajectory.claimed_stop_decision.{stop_key} ({claimed_stop.get(stop_key)!r}) "
                f"does not match replayed {replayed_stop[stop_key]!r}."
            )

    if not budget_summary["budget_ok"]:
        raise ValueError(
            "Trajectory verification failed: U12 budget_ok is False "
            f"({budget_summary['violation_reasons']!r}). Retained failed budget ledgers "
            "cannot pass compliant trajectory verification."
        )

    has_failed_move = len(validated_commensurable_by_index) != len(raw_moves)
    trajectory_state = (
        "retained_with_failed_move"
        if has_failed_move
        else "verified_compliant_trajectory"
    )
    compliant_completion_verified = bool(
        not has_failed_move
        and budget_summary["budget_ok"]
        and replayed_selection["selected_move_id"] is not None
    )

    if (
        "require_compliant_completion" in trajectory
        and trajectory["require_compliant_completion"] is True
        and not compliant_completion_verified
    ):
        raise ValueError(
            f"Trajectory did not achieve compliant completion: state={trajectory_state!r}, "
            f"selection_state={replayed_selection['selection_state']!r}."
        )

    return {
        "trajectory_ok": True,
        "trajectory_state": trajectory_state,
        "compliant_completion_verified": compliant_completion_verified,
        "scientific_arm_completion": "not_assessed",
        "arm": arm,
        "target_id": target_id,
        "subject_id": subject_id,
        "start_redacted_view_sha256": start_redacted["redacted_view_sha256"],
        "verified_moves": tuple(verified_move_summaries),
        "replayed_selection": replayed_selection,
        "replayed_stop_decision": replayed_stop,
        "budget_summary": budget_summary,
        "epistemic_note": (
            "Offline receipt, hash, budget, and replay verification only; does not prove "
            "OS/process isolation, whole-log text redaction outside the projected selection "
            "view, live admission-guard execution, or runtime correctness."
        ),
        "registration_status": REGISTRATION_STATUS,
        "stage2_status": STAGE2_SELECTOR_STATUS,
        "executed": False,
    }


__all__ = [
    "ALLOWED_METRIC_READOUT_KEYS",
    "ALLOWED_PUBLIC_CANDIDATE_KEYS",
    "ALLOWED_PUBLIC_START_KEYS",
    "ALLOWED_READOUT_CONTRACT_SPEC_KEYS",
    "ALLOWED_RESIDUAL_TIE_POLICIES",
    "ALLOWED_STOP_REFERENCE_CONVENTIONS",
    "ALLOWED_TIE_GROUP_POLICIES",
    "ANGLE_RMSZ_DELTA_ALLOWANCE",
    "ANGLE_RMSZ_FLOOR",
    "BOND_RMSZ_DELTA_ALLOWANCE",
    "BOND_RMSZ_FLOOR",
    "CANDIDATE_METRIC_NAMES",
    "CLASHSCORE_ADDEND",
    "CLASHSCORE_FLOOR",
    "CLASHSCORE_MULTIPLIER",
    "COMPLETED_COMMENSURABLE_STATUS",
    "EXECUTION_AUTHORIZED",
    "EXPECTED_METRIC_UNITS",
    "GEOMETRY_METRIC_NAMES",
    "MAX_LOSSLESS_JSON_INT",
    "MetricReadout",
    "OPTIONAL_START_METRIC_NAMES",
    "RAMA_OUT_PERCENT_DELTA_ALLOWANCE",
    "RAMA_OUT_PERCENT_FLOOR",
    "REGISTRATION_STATUS",
    "R_WORK_TIE_TOLERANCE",
    "STAGE2_SELECTOR_STATUS",
    "STOP_CONSECUTIVE_MOVES_REQUIRED",
    "STOP_DELTA_CLASHSCORE_LOWER",
    "STOP_DELTA_R_WORK_STRICT_LOWER",
    "StartingGeometryRecord",
    "CandidateSelectionRecord",
    "canonical_json_bytes",
    "canonical_json_sha256",
    "geometry_eligible",
    "redact_candidate_for_selection",
    "redact_starting_geometry_for_selection",
    "select_candidate",
    "selection_view",
    "stop_decision",
    "validate_public_candidate_record",
    "validate_readout_contract",
    "validate_starting_geometry_record",
    "verify_trajectory",
]
