#!/usr/bin/env python3
"""Result-free Stage 2 PHENIX shared 6-role dated LLM snapshot configuration binder (U12).

Scope and epistemic boundary:
- Registration status remains ``selected_decisions_recorded`` (NOT ``frozen_result_free``).
- This module implements a pure Python 3.12 standard-library configuration validator and
  deterministic SHA-256 binder (:func:`bind_shared_snapshot_config`) across the 2 agentic
  controller arms (``1a``, ``1b``) and 3 planner LLM subroles (``llm``, ``cheap_llm``,
  ``command_llm``) — 6 canonical ``(arm, role)`` slots in total.
- It enforces:
  1. Exact 6-slot completeness across ``("1a", "1b") x ("llm", "cheap_llm", "command_llm")``
     with no missing, duplicate, or extra ``(arm, role)`` records.
  2. Equality across all 6 roles of the shared model tuple:
     ``(provider, endpoint, snapshot_id, temperature=0.0)``, where ``provider`` must be one of
     the static-witnessed ``libtbx.langchain`` factory branches (``"ollama"``, ``"google"``,
     ``"openai"`` per ``U12-W1``), ``snapshot_id`` must carry a pinned valid calendar date
     (rejecting floating aliases such as ``"latest"``, ``"default"``, ``"auto"``), and
     ``temperature`` must be a strict numeric ``0.0`` (not ``bool``).
  3. Explicit per-role 64-hex lowercase SHA-256 bindings for ``prompt_sha256``,
     ``config_sha256``, ``adapter_sha256``, and ``dependency_sha256`` (which may legitimately
     differ across roles/arms).
  4. Binding of a caller-supplied ``snapshot_witness`` JSON record (whose ``provider`` and
     ``snapshot_id`` must match the shared 6-role tuple) verified against an explicit
     ``snapshot_source_sha256`` under canonical JSON serialization.
- Epistemic limits:
  - A date-shaped synthetic identifier or matching ``snapshot_source_sha256`` proves ONLY
    internal configuration consistency; it does NOT prove independent sourcing, vendor
    model existence, native runtime compatibility, or credential/network availability.
  - All status fields (``registration_status="selected_decisions_recorded"``,
    ``runtime_binding="not_assessed"``, ``availability="not_assessed"``,
    ``execution_authorized=False``, ``executed=False``) are fixed constants and can never
    be overridden by caller inputs.
  - No concrete model snapshot is selected by this module; the committed static witness
    ``ref/research/data/phenix_langchain_static_witness_2026-11-15.json`` retains
    ``selected_identifier: null``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import datetime
import hashlib
import json
import math
import re
from typing import Any

REGISTRATION_STATUS = "selected_decisions_recorded"
STAGE2_SNAPSHOT_STATUS = "prospective_snapshot_config_binder_not_development_frozen"
RUNTIME_BINDING_STATUS = "not_assessed"
AVAILABILITY_STATUS = "not_assessed"
EXECUTION_AUTHORIZED = False

STATIC_WITNESS_PATH = (
    "ref/research/data/phenix_langchain_static_witness_2026-11-15.json"
)

CONTROLLER_ARM_IDS: tuple[str, ...] = ("1a", "1b")
LLM_SUBROLES: tuple[str, ...] = ("llm", "cheap_llm", "command_llm")
CANONICAL_ARM_ROLE_SLOTS: tuple[tuple[str, str], ...] = tuple(
    (arm, role) for arm in CONTROLLER_ARM_IDS for role in LLM_SUBROLES
)

OBSERVED_NATIVE_PROVIDER_BRANCHES: tuple[str, ...] = ("ollama", "google", "openai")
REQUIRED_TEMPERATURE: float = 0.0

ARTIFACT_HASH_KEYS: tuple[str, ...] = (
    "prompt_sha256",
    "config_sha256",
    "adapter_sha256",
    "dependency_sha256",
)

ALLOWED_ROLE_RECORD_KEYS: frozenset[str] = frozenset(
    {
        "arm",
        "role",
        "provider",
        "endpoint",
        "snapshot_id",
        "temperature",
        *ARTIFACT_HASH_KEYS,
    }
)

FORBIDDEN_FLOATING_ALIASES: frozenset[str] = frozenset(
    {
        "latest",
        "default",
        "auto",
        "expensive",
        "cheap",
        "none",
        "null",
        "unpinned",
        "current",
        "stable",
        "preview",
        "head",
        "main",
    }
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}\Z")
_SNAPSHOT_ID_CHARS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]*\Z")
_ISO_DATE_TOKEN_RE = re.compile(r"(?:^|[-_.:@/])((?:20[2-9][0-9])-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12][0-9]|3[01]))(?:$|[-_.:@/])")
_COMPACT_DATE_TOKEN_RE = re.compile(r"(?:^|[-_.:@/])((?:20[2-9][0-9])(?:0[1-9]|1[0-2])(?:0[1-9]|[12][0-9]|3[01]))(?:$|[-_.:@/])")
_WHITESPACE_OR_CTRL_RE = re.compile(r"[\s\x00-\x1f\x7f]")


def _validate_strict_stripped_str(value: Any, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or _WHITESPACE_OR_CTRL_RE.search(value) is not None
    ):
        raise ValueError(
            f"{field_name} must be a non-empty string without whitespace or control "
            f"characters, got {value!r}."
        )
    return value


def _validate_sha256_strict(value: Any, *, field_name: str) -> str:
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


def _validate_provider(value: Any, *, field_name: str) -> str:
    provider = _validate_strict_stripped_str(value, field_name=field_name)
    if provider not in OBSERVED_NATIVE_PROVIDER_BRANCHES:
        raise ValueError(
            f"{field_name} must be one of the static-witnessed libtbx.langchain provider "
            f"branches {OBSERVED_NATIVE_PROVIDER_BRANCHES}, got {provider!r}."
        )
    return provider


def _validate_endpoint(value: Any, *, field_name: str) -> str:
    return _validate_strict_stripped_str(value, field_name=field_name)


def _validate_temperature_zero(value: Any, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(
            f"{field_name} must be a strict numeric 0.0 (not bool/str/None), "
            f"got {value!r} ({type(value).__name__})."
        )
    fval = float(value)
    if not math.isfinite(fval) or fval != REQUIRED_TEMPERATURE:
        raise ValueError(
            f"{field_name} must be exact {REQUIRED_TEMPERATURE} per U12 policy, got {value!r}."
        )
    return 0.0


def _validate_dated_snapshot_id(value: Any, *, field_name: str) -> str:
    snap_id = _validate_strict_stripped_str(value, field_name=field_name)
    if _SNAPSHOT_ID_CHARS_RE.fullmatch(snap_id) is None:
        raise ValueError(
            f"{field_name}={snap_id!r} contains invalid characters for a snapshot identifier."
        )

    lower_id = snap_id.lower()
    if lower_id in FORBIDDEN_FLOATING_ALIASES:
        raise ValueError(
            f"{field_name}={snap_id!r} is a forbidden unpinned/floating alias."
        )

    segments = [seg for seg in re.split(r"[-_.:@/]+", lower_id) if seg]
    for seg in segments:
        if seg in FORBIDDEN_FLOATING_ALIASES:
            raise ValueError(
                f"{field_name}={snap_id!r} contains forbidden floating alias token {seg!r}."
            )

    parsed_dates: list[datetime.date] = []
    for match in _ISO_DATE_TOKEN_RE.finditer(snap_id):
        raw_dt = match.group(1)
        try:
            year_s, month_s, day_s = raw_dt.split("-")
            parsed_dates.append(
                datetime.date(int(year_s), int(month_s), int(day_s))
            )
        except ValueError as exc:
            raise ValueError(
                f"{field_name}={snap_id!r} contains invalid calendar date {raw_dt!r}."
            ) from exc

    for match in _COMPACT_DATE_TOKEN_RE.finditer(snap_id):
        raw_dt = match.group(1)
        try:
            parsed_dates.append(
                datetime.date(
                    int(raw_dt[0:4]), int(raw_dt[4:6]), int(raw_dt[6:8])
                )
            )
        except ValueError as exc:
            raise ValueError(
                f"{field_name}={snap_id!r} contains invalid compact calendar date {raw_dt!r}."
            ) from exc

    if not parsed_dates:
        # Also check if a date-shaped token had an invalid calendar day/month such as 2026-02-30 or 2026-13-01
        if re.search(r"20\d{2}-\d{2}-\d{2}|20\d{6}", snap_id):
            raise ValueError(
                f"{field_name}={snap_id!r} contains an invalid calendar date token."
            )
        raise ValueError(
            f"{field_name}={snap_id!r} is unpinned: requires an explicit valid calendar "
            "date token (YYYY-MM-DD or YYYYMMDD) in the snapshot identifier."
        )

    # Reject a bare date with no model stem
    non_date_segments = [
        seg
        for seg in segments
        if not re.fullmatch(r"\d{4}|\d{2}|\d{8}", seg)
    ]
    if not non_date_segments:
        raise ValueError(
            f"{field_name}={snap_id!r} must include a model identifier stem in addition "
            "to the calendar date token."
        )

    return snap_id


def _normalize_strict_json_value(value: Any, *, field_name: str) -> Any:
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(
                f"{field_name} contains non-finite float {value!r}; strict JSON requires "
                "finite numbers."
            )
        return value
    if isinstance(value, Mapping):
        out_map: dict[str, Any] = {}
        for k, v in value.items():
            if not isinstance(k, str) or not k.strip():
                raise ValueError(
                    f"{field_name} mapping keys must be non-empty strings, got {k!r}."
                )
            out_map[k] = _normalize_strict_json_value(
                v, field_name=f"{field_name}.{k}"
            )
        return out_map
    if isinstance(value, (list, tuple)):
        return [
            _normalize_strict_json_value(item, field_name=f"{field_name}[{idx}]")
            for idx, item in enumerate(value)
        ]
    raise ValueError(
        f"{field_name} contains unsupported non-JSON value {value!r} "
        f"({type(value).__name__})."
    )


def canonical_json_bytes(record: Mapping[str, Any]) -> bytes:
    """Serialize a strict JSON mapping deterministically to UTF-8 bytes.

    Uses sorted keys, compact separators ``(",", ":")``, ``ensure_ascii=False``,
    and ``allow_nan=False`` after validating that all nested keys and values are
    strict finite JSON data types.
    """
    if not isinstance(record, Mapping):
        raise ValueError(
            f"canonical_json_bytes requires a mapping, got {type(record).__name__}."
        )
    normalized = _normalize_strict_json_value(record, field_name="record")
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_json_sha256(record: Mapping[str, Any]) -> str:
    """Return the lowercase 64-hex SHA-256 digest of :func:`canonical_json_bytes`."""
    return hashlib.sha256(canonical_json_bytes(record)).hexdigest()


def _extract_six_role_records(
    role_configs: Any,
) -> dict[tuple[str, str], Mapping[str, Any]]:
    if role_configs is None:
        raise ValueError("role_configs is required and cannot be None.")

    extracted: dict[tuple[str, str], Mapping[str, Any]] = {}

    if isinstance(role_configs, Mapping):
        if len(role_configs) == 0:
            raise ValueError("role_configs mapping cannot be empty.")
        first_key = next(iter(role_configs.keys()))
        if isinstance(first_key, tuple):
            # Flat mapping keyed by (arm, role) tuples
            for raw_pair, rec in role_configs.items():
                if (
                    not isinstance(raw_pair, tuple)
                    or len(raw_pair) != 2
                    or raw_pair not in CANONICAL_ARM_ROLE_SLOTS
                ):
                    raise ValueError(
                        f"Invalid (arm, role) key {raw_pair!r} in role_configs; "
                        f"expected exact {CANONICAL_ARM_ROLE_SLOTS}."
                    )
                if not isinstance(rec, Mapping):
                    raise ValueError(
                        f"role_configs[{raw_pair!r}] must be a mapping."
                    )
                extracted[raw_pair] = rec
        else:
            # Nested mapping arm -> role -> record
            expected_arms = set(CONTROLLER_ARM_IDS)
            actual_arms = set(role_configs.keys())
            if actual_arms != expected_arms:
                missing_arms = sorted(expected_arms - actual_arms)
                extra_arms = sorted(actual_arms - expected_arms)
                raise ValueError(
                    f"role_configs must contain exact controller arms {list(CONTROLLER_ARM_IDS)}; "
                    f"missing={missing_arms}, extra={extra_arms}."
                )
            for arm in CONTROLLER_ARM_IDS:
                arm_map = role_configs[arm]
                if not isinstance(arm_map, Mapping):
                    raise ValueError(
                        f"role_configs[{arm!r}] must be a mapping of subrole -> config."
                    )
                expected_roles = set(LLM_SUBROLES)
                actual_roles = set(arm_map.keys())
                if actual_roles != expected_roles:
                    missing_roles = sorted(expected_roles - actual_roles)
                    extra_roles = sorted(actual_roles - expected_roles)
                    raise ValueError(
                        f"role_configs[{arm!r}] must contain exact subroles {list(LLM_SUBROLES)}; "
                        f"missing={missing_roles}, extra={extra_roles}."
                    )
                for role in LLM_SUBROLES:
                    rec = arm_map[role]
                    if not isinstance(rec, Mapping):
                        raise ValueError(
                            f"role_configs[{arm!r}][{role!r}] must be a mapping."
                        )
                    extracted[(arm, role)] = rec
    elif isinstance(role_configs, Sequence) and not isinstance(
        role_configs, (str, bytes)
    ):
        for idx, rec in enumerate(role_configs):
            if not isinstance(rec, Mapping):
                raise ValueError(f"role_configs[{idx}] must be a mapping.")
            if "arm" not in rec or "role" not in rec:
                raise ValueError(
                    f"role_configs[{idx}] in sequence input must include explicit 'arm' and 'role'."
                )
            arm_val = rec["arm"]
            role_val = rec["role"]
            pair = (arm_val, role_val)
            if pair not in CANONICAL_ARM_ROLE_SLOTS:
                raise ValueError(
                    f"role_configs[{idx}] has invalid (arm, role)={pair!r}; "
                    f"expected one of {CANONICAL_ARM_ROLE_SLOTS}."
                )
            if pair in extracted:
                raise ValueError(
                    f"Duplicate (arm, role)={pair!r} in role_configs at index {idx}."
                )
            extracted[pair] = rec
    else:
        raise ValueError(
            "role_configs must be a nested mapping (arm -> role -> record), "
            "(arm, role)-keyed mapping, or sequence of 6 role config mappings."
        )

    expected_slots = set(CANONICAL_ARM_ROLE_SLOTS)
    actual_slots = set(extracted.keys())
    if actual_slots != expected_slots:
        missing_slots = sorted(expected_slots - actual_slots)
        extra_slots = sorted(actual_slots - expected_slots)
        raise ValueError(
            "role_configs must contain all 6 canonical (arm, role) slots "
            f"{list(CANONICAL_ARM_ROLE_SLOTS)}; missing={missing_slots}, extra={extra_slots}."
        )

    return extracted


def _validate_snapshot_witness(
    snapshot_witness: Any,
    *,
    snapshot_source_sha256: Any,
    expected_provider: str,
    expected_endpoint: str,
    expected_snapshot_id: str,
) -> tuple[dict[str, Any], str]:
    verified_source_sha = _validate_sha256_strict(
        snapshot_source_sha256, field_name="snapshot_source_sha256"
    )
    if not isinstance(snapshot_witness, Mapping) or len(snapshot_witness) == 0:
        raise ValueError(
            "snapshot_witness must be a non-empty strict-JSON mapping (a bare "
            "snapshot_source_sha256 digest without the witness record is rejected)."
        )

    normalized_witness = _normalize_strict_json_value(
        snapshot_witness, field_name="snapshot_witness"
    )
    assert isinstance(normalized_witness, dict)

    # Reject unselected static witness (selected_identifier: null)
    if "selected_identifier" in normalized_witness:
        sel_id = normalized_witness["selected_identifier"]
        if sel_id is None:
            raise ValueError(
                "snapshot_witness has selected_identifier=None; the unselected Stage 1 "
                "witness cannot satisfy a concrete Stage 2 snapshot binding."
            )
        if "snapshot_id" not in normalized_witness:
            raise ValueError(
                "snapshot_witness must declare explicit 'snapshot_id' (and 'provider')."
            )
        if sel_id != normalized_witness["snapshot_id"]:
            raise ValueError(
                f"snapshot_witness.selected_identifier ({sel_id!r}) conflicts with "
                f"snapshot_witness.snapshot_id ({normalized_witness['snapshot_id']!r})."
            )

    if "provider" not in normalized_witness:
        raise ValueError("snapshot_witness is missing required 'provider'.")
    if "snapshot_id" not in normalized_witness:
        raise ValueError("snapshot_witness is missing required 'snapshot_id'.")

    witness_provider = _validate_provider(
        normalized_witness["provider"], field_name="snapshot_witness.provider"
    )
    witness_snapshot_id = _validate_dated_snapshot_id(
        normalized_witness["snapshot_id"], field_name="snapshot_witness.snapshot_id"
    )
    if witness_provider != expected_provider:
        raise ValueError(
            f"snapshot_witness.provider ({witness_provider!r}) does not match shared "
            f"6-role provider ({expected_provider!r})."
        )
    if witness_snapshot_id != expected_snapshot_id:
        raise ValueError(
            f"snapshot_witness.snapshot_id ({witness_snapshot_id!r}) does not match "
            f"shared 6-role snapshot_id ({expected_snapshot_id!r})."
        )

    if "endpoint" in normalized_witness and normalized_witness["endpoint"] is not None:
        witness_endpoint = _validate_endpoint(
            normalized_witness["endpoint"], field_name="snapshot_witness.endpoint"
        )
        if witness_endpoint != expected_endpoint:
            raise ValueError(
                f"snapshot_witness.endpoint ({witness_endpoint!r}) does not match "
                f"shared 6-role endpoint ({expected_endpoint!r})."
            )

    # Forbid caller witness from asserting runtime availability, execution authorization, execution, or freeze
    if (
        "runtime_binding" in normalized_witness
        and (
            not isinstance(normalized_witness["runtime_binding"], str)
            or normalized_witness["runtime_binding"] != RUNTIME_BINDING_STATUS
        )
    ):
        raise ValueError(
            f"snapshot_witness.runtime_binding cannot assert {normalized_witness['runtime_binding']!r}; "
            f"must remain {RUNTIME_BINDING_STATUS!r}."
        )
    if (
        "availability" in normalized_witness
        and (
            not isinstance(normalized_witness["availability"], str)
            or normalized_witness["availability"] != AVAILABILITY_STATUS
        )
    ):
        raise ValueError(
            f"snapshot_witness.availability cannot assert {normalized_witness['availability']!r}; "
            f"must remain {AVAILABILITY_STATUS!r}."
        )
    if (
        "execution_authorized" in normalized_witness
        and normalized_witness["execution_authorized"] is not False
    ):
        raise ValueError(
            "snapshot_witness.execution_authorized cannot be True in result-free "
            "Stage 2 snapshot configuration binding."
        )
    if (
        "executed" in normalized_witness
        and normalized_witness["executed"] is not False
    ):
        raise ValueError(
            f"snapshot_witness.executed must be exact False when supplied, "
            f"got {normalized_witness['executed']!r}."
        )
    if (
        "registration_status" in normalized_witness
        and (
            not isinstance(normalized_witness["registration_status"], str)
            or normalized_witness["registration_status"] != REGISTRATION_STATUS
        )
    ):
        raise ValueError(
            f"snapshot_witness.registration_status cannot assert "
            f"{normalized_witness['registration_status']!r}; must remain {REGISTRATION_STATUS!r}."
        )
    if (
        "stage2_status" in normalized_witness
        and (
            not isinstance(normalized_witness["stage2_status"], str)
            or normalized_witness["stage2_status"] != STAGE2_SNAPSHOT_STATUS
        )
    ):
        raise ValueError(
            f"snapshot_witness.stage2_status cannot assert "
            f"{normalized_witness['stage2_status']!r}; must remain {STAGE2_SNAPSHOT_STATUS!r}."
        )

    computed_sha = canonical_json_sha256(normalized_witness)
    if computed_sha != verified_source_sha:
        raise ValueError(
            f"snapshot_source_sha256 ({verified_source_sha}) does not match canonical "
            f"JSON SHA-256 of snapshot_witness ({computed_sha})."
        )

    return normalized_witness, verified_source_sha


def bind_shared_snapshot_config(
    *,
    role_configs: Any,
    snapshot_witness: Mapping[str, Any],
    snapshot_source_sha256: str,
) -> dict[str, Any]:
    """Validate and deterministically bind the shared 6-role Stage 2 LLM snapshot configuration.

    Enforces:
    - Exact 6-slot completeness across ``("1a", "1b") x ("llm", "cheap_llm", "command_llm")``.
    - Identical ``(provider, endpoint, snapshot_id, temperature=0.0)`` across all 6 slots.
    - Explicit per-role 64-hex lowercase SHA-256 digests for ``prompt_sha256``,
      ``config_sha256``, ``adapter_sha256``, and ``dependency_sha256``.
    - Canonical JSON SHA-256 verification of ``snapshot_witness`` against
      ``snapshot_source_sha256`` and agreement of ``snapshot_witness`` ``(provider, snapshot_id)``
      with the 6-role shared model tuple.
    - Deterministic aggregate ``effective_binding_sha256`` covering all 6 canonical
      ``(arm, role)`` slots, the shared model tuple, all 4 per-role artifact hashes, and
      the ``snapshot_witness`` / ``snapshot_source_sha256`` binding.
    - Fixed non-promotional statuses: ``runtime_binding="not_assessed"``,
      ``availability="not_assessed"``, ``registration_status="selected_decisions_recorded"``,
      ``execution_authorized=False``, and ``executed=False``.
    """
    raw_slots = _extract_six_role_records(role_configs)

    normalized_slot_records: list[dict[str, Any]] = []
    shared_tuple: tuple[str, str, str, float] | None = None
    shared_origin: tuple[str, str] | None = None

    for arm, role in CANONICAL_ARM_ROLE_SLOTS:
        rec = raw_slots[(arm, role)]
        prefix = f"role_configs[{arm!r}][{role!r}]"

        unknown_keys = sorted(set(rec.keys()) - ALLOWED_ROLE_RECORD_KEYS)
        if unknown_keys:
            raise ValueError(
                f"{prefix} contains unknown or forbidden keys: {unknown_keys}."
            )

        if "arm" in rec and rec["arm"] != arm:
            raise ValueError(
                f"{prefix}.arm={rec['arm']!r} conflicts with slot arm {arm!r}."
            )
        if "role" in rec and rec["role"] != role:
            raise ValueError(
                f"{prefix}.role={rec['role']!r} conflicts with slot role {role!r}."
            )

        for req_key in (
            "provider",
            "endpoint",
            "snapshot_id",
            "temperature",
            *ARTIFACT_HASH_KEYS,
        ):
            if req_key not in rec:
                raise ValueError(
                    f"{prefix} is missing required field {req_key!r}."
                )

        provider = _validate_provider(
            rec["provider"], field_name=f"{prefix}.provider"
        )
        endpoint = _validate_endpoint(
            rec["endpoint"], field_name=f"{prefix}.endpoint"
        )
        snapshot_id = _validate_dated_snapshot_id(
            rec["snapshot_id"], field_name=f"{prefix}.snapshot_id"
        )
        temperature = _validate_temperature_zero(
            rec["temperature"], field_name=f"{prefix}.temperature"
        )

        current_tuple = (provider, endpoint, snapshot_id, temperature)
        if shared_tuple is None:
            shared_tuple = current_tuple
            shared_origin = (arm, role)
        elif current_tuple != shared_tuple:
            raise ValueError(
                f"Shared snapshot tuple mismatch between {shared_origin} {shared_tuple!r} "
                f"and {(arm, role)} {current_tuple!r}: U12 requires identical "
                "(provider, endpoint, snapshot_id, temperature=0.0) across all 6 roles."
            )

        artifact_hashes: dict[str, str] = {}
        for h_key in ARTIFACT_HASH_KEYS:
            artifact_hashes[h_key] = _validate_sha256_strict(
                rec[h_key], field_name=f"{prefix}.{h_key}"
            )

        normalized_slot_records.append(
            {
                "arm": arm,
                "role": role,
                "provider": provider,
                "endpoint": endpoint,
                "snapshot_id": snapshot_id,
                "temperature": temperature,
                "prompt_sha256": artifact_hashes["prompt_sha256"],
                "config_sha256": artifact_hashes["config_sha256"],
                "adapter_sha256": artifact_hashes["adapter_sha256"],
                "dependency_sha256": artifact_hashes["dependency_sha256"],
            }
        )

    assert shared_tuple is not None
    shared_provider, shared_endpoint, shared_snapshot_id, shared_temp = shared_tuple

    normalized_witness, verified_source_sha = _validate_snapshot_witness(
        snapshot_witness,
        snapshot_source_sha256=snapshot_source_sha256,
        expected_provider=shared_provider,
        expected_endpoint=shared_endpoint,
        expected_snapshot_id=shared_snapshot_id,
    )

    shared_model_dict = {
        "provider": shared_provider,
        "endpoint": shared_endpoint,
        "snapshot_id": shared_snapshot_id,
        "temperature": shared_temp,
    }

    canonical_binding_payload = {
        "schema": "phenix_stage2_shared_snapshot_binding_v1",
        "shared_model_tuple": shared_model_dict,
        "snapshot_source_sha256": verified_source_sha,
        "snapshot_witness": normalized_witness,
        "arm_role_bindings": normalized_slot_records,
    }
    effective_binding_sha256 = canonical_json_sha256(canonical_binding_payload)

    by_arm_role: dict[str, dict[str, dict[str, Any]]] = {
        arm: {} for arm in CONTROLLER_ARM_IDS
    }
    for slot_rec in normalized_slot_records:
        by_arm_role[slot_rec["arm"]][slot_rec["role"]] = dict(slot_rec)

    return {
        "binding_ok": True,
        "effective_binding_sha256": effective_binding_sha256,
        "shared_model_tuple": shared_model_dict,
        "provider": shared_provider,
        "endpoint": shared_endpoint,
        "snapshot_id": shared_snapshot_id,
        "temperature": shared_temp,
        "snapshot_source_sha256": verified_source_sha,
        "snapshot_witness": normalized_witness,
        "arm_role_bindings": tuple(normalized_slot_records),
        "role_configs": by_arm_role,
        "runtime_binding": RUNTIME_BINDING_STATUS,
        "availability": AVAILABILITY_STATUS,
        "registration_status": REGISTRATION_STATUS,
        "stage2_status": STAGE2_SNAPSHOT_STATUS,
        "execution_authorized": EXECUTION_AUTHORIZED,
        "executed": False,
        "epistemic_note": (
            "Binds supplied 6-role configuration and snapshot_witness hashes only; "
            "does not prove independent sourcing, vendor snapshot existence, native "
            "adapter compatibility, or runtime availability."
        ),
    }


__all__ = [
    "ALLOWED_ROLE_RECORD_KEYS",
    "ARTIFACT_HASH_KEYS",
    "AVAILABILITY_STATUS",
    "CANONICAL_ARM_ROLE_SLOTS",
    "CONTROLLER_ARM_IDS",
    "EXECUTION_AUTHORIZED",
    "FORBIDDEN_FLOATING_ALIASES",
    "LLM_SUBROLES",
    "OBSERVED_NATIVE_PROVIDER_BRANCHES",
    "REGISTRATION_STATUS",
    "REQUIRED_TEMPERATURE",
    "RUNTIME_BINDING_STATUS",
    "STAGE2_SNAPSHOT_STATUS",
    "STATIC_WITNESS_PATH",
    "bind_shared_snapshot_config",
    "canonical_json_bytes",
    "canonical_json_sha256",
]
