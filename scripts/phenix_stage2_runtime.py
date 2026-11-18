#!/usr/bin/env python3
"""Result-free Stage 2 PHENIX runtime contracts for U08 status classification and U12 controller budgets.

Scope and epistemic boundary:
- Registration status remains ``selected_decisions_recorded`` (NOT ``frozen_result_free``).
- This module implements pure Python 3.12 standard-library validators for:
  1. The finite 8-code completion and failure/incommensurability vocabulary (``U08``)
     across all six canonical study arms (``1a``, ``1b``, ``2``, ``3a``,
     ``3b-refine-only``, ``3b-plus-readyset``).
  2. The agentic controller (``Arm 1a``, ``Arm 1b``) per-target execution budget
     ledger verifier and prospective next-move admission guard (``U12``).
- It is strictly result-free: it never imports vendor/provider packages, never executes
  PHENIX or LLM calls, and never silently coerces unknown or failed observations into
  completed checkpoints.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import math
import re
from typing import Any

REGISTRATION_STATUS = "selected_decisions_recorded"
STAGE2_RUNTIME_STATUS = "prospective_runtime_contract_not_development_frozen"

STATIC_WITNESS_PATH = "ref/research/data/phenix_langchain_static_witness_2026-11-15.json"

CANONICAL_ARM_IDS: tuple[str, ...] = (
    "1a",
    "1b",
    "2",
    "3a",
    "3b-refine-only",
    "3b-plus-readyset",
)
CONTROLLER_ARM_IDS: tuple[str, ...] = ("1a", "1b")
LLM_SUBROLES: tuple[str, ...] = ("llm", "cheap_llm", "command_llm")

U08_STATUS_CODES: tuple[str, ...] = (
    "COMPLETED_COMMENSURABLE",
    "FAIL_PROCESS_CRASH_OR_NONZERO_EXIT",
    "FAIL_BUDGET_OR_WALLCLOCK_EXCEEDED",
    "FAIL_UNPARSABLE_OR_MISSING_ARTIFACT",
    "INCOMMENSURABLE_ARM3A_AUTODETECT_MISMATCH",
    "INCOMMENSURABLE_REFLECTION_DROP_OR_DOMAIN_CHANGE",
    "INCOMMENSURABLE_FREE_OR_SLEEP_FLAG_MUTATION",
    "INCOMMENSURABLE_ATOM_IDENTITY_OR_CELL_CORRUPTION",
)
U08_FAILURE_STATUS_CODES: tuple[str, ...] = U08_STATUS_CODES[1:]

OBSERVATION_TO_FAILURE_CODE: tuple[tuple[str, str], ...] = (
    ("process_ok", "FAIL_PROCESS_CRASH_OR_NONZERO_EXIT"),
    ("budget_ok", "FAIL_BUDGET_OR_WALLCLOCK_EXCEEDED"),
    ("artifacts_ok", "FAIL_UNPARSABLE_OR_MISSING_ARTIFACT"),
    ("autodetect_ok", "INCOMMENSURABLE_ARM3A_AUTODETECT_MISMATCH"),
    ("reflections_ok", "INCOMMENSURABLE_REFLECTION_DROP_OR_DOMAIN_CHANGE"),
    ("flags_ok", "INCOMMENSURABLE_FREE_OR_SLEEP_FLAG_MUTATION"),
    ("atom_cell_ok", "INCOMMENSURABLE_ATOM_IDENTITY_OR_CELL_CORRUPTION"),
)
REQUIRED_OBSERVATION_KEYS: frozenset[str] = frozenset(
    key for key, _ in OBSERVATION_TO_FAILURE_CODE
)

MAX_OUTER_MOVES = 8
MAX_MACRO_CYCLES = 25
MOVE_1_REQUIRED_MACRO_CYCLES = 5
MAX_TOTAL_TOKENS = 150_000
MAX_ELAPSED_SECONDS = 7200.0
REQUIRED_CONFIGURED_CPU_THREADS = 8

ALLOWED_MOVE_STATUSES: frozenset[str] = frozenset(
    {"completed", "aborted", "failed", "aborted_before_execution"}
)
ALLOWED_MOVE_KINDS: frozenset[str] = frozenset({"refinement", "non_refinement"})
UNAVAILABLE_NOT_EXECUTED_MARKERS: frozenset[str] = frozenset(
    {"unavailable_not_executed", "not_executed", "aborted_before_execution"}
)
UNAVAILABLE_EXECUTION_MARKERS: frozenset[str] = frozenset(
    {
        "unavailable_not_executed",
        "not_executed",
        "aborted_before_execution",
        "unavailable_aborted",
        "unavailable_execution_failed",
    }
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}\Z")

ARM1B_PROVENANCE_SLOT_SPECS: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("primary_command", "primary-command", ("primary_command_sha256",), ("primary_command",)),
    (
        "mechanical_backup",
        "mechanical-backup",
        ("mechanical_backup_sha256",),
        ("mechanical_backup_command", "mechanical_backup"),
    ),
    ("actual_command", "actual-command", ("actual_command_sha256",), ("actual_command",)),
    (
        "effective_eff",
        "effective-.eff",
        ("effective_eff_sha256",),
        ("effective_eff_receipt", "effective_eff"),
    ),
)
ALLOWED_ARM1B_PROVENANCE_KEYS: frozenset[str] = frozenset(
    key
    for _, _, sha_keys, text_keys in ARM1B_PROVENANCE_SLOT_SPECS
    for key in (*sha_keys, *text_keys)
)

_MISSING = object()


def _validate_strict_bool(value: Any, *, field_name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(
            f"{field_name} must be an explicit boolean (True or False), "
            f"got {value!r} ({type(value).__name__})."
        )
    return value


def _validate_strict_int(
    value: Any,
    *,
    field_name: str,
    min_value: int | None = None,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            f"{field_name} must be a strict int (not bool/float/str), "
            f"got {value!r} ({type(value).__name__})."
        )
    if min_value is not None and value < min_value:
        raise ValueError(f"{field_name} must be >= {min_value}, got {value}.")
    return value


def _validate_finite_nonnegative_float(value: Any, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(
            f"{field_name} must be a finite non-negative number (not bool), "
            f"got {value!r} ({type(value).__name__})."
        )
    fval = float(value)
    if not math.isfinite(fval) or fval < 0.0:
        raise ValueError(f"{field_name} must be finite and >= 0.0, got {value!r}.")
    return fval


def _validate_nonempty_str(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string, got {value!r}.")
    return value.strip()


def _parse_unavailable_observation(
    value: Mapping[str, Any], *, field_name: str
) -> dict[str, str]:
    allowed_keys = {"state", "reason"}
    unknown_keys = sorted(set(value.keys()) - allowed_keys)
    if unknown_keys:
        raise ValueError(
            f"{field_name} unavailable observation contains unknown keys: {unknown_keys}."
        )
    if "state" not in value or value["state"] != "unavailable":
        raise ValueError(
            f"{field_name} unavailable observation mapping requires explicit "
            f"state='unavailable', got {value.get('state')!r}."
        )
    if "reason" not in value:
        raise ValueError(
            f"{field_name} unavailable observation mapping requires a non-empty 'reason'."
        )
    reason_val = _validate_nonempty_str(value["reason"], field_name=f"{field_name}.reason")
    return {"state": "unavailable", "reason": reason_val}


def classify_u08_status(
    observations: Mapping[str, Any] | None = None,
    *,
    process_ok: Any = _MISSING,
    budget_ok: Any = _MISSING,
    artifacts_ok: Any = _MISSING,
    autodetect_ok: Any = _MISSING,
    reflections_ok: Any = _MISSING,
    flags_ok: Any = _MISSING,
    atom_cell_ok: Any = _MISSING,
    arm: str | None = None,
    failure_priority: Sequence[str] | None = None,
    provenance_id: str | None = None,
    reference_id: str | None = None,
) -> dict[str, Any]:
    """Classify a run into the exact 8-code U08 completion/failure/incommensurability vocabulary.

    Fail-closed rules:
    - All seven observation flags (``process_ok``, ``budget_ok``, ``artifacts_ok``,
      ``autodetect_ok``, ``reflections_ok``, ``flags_ok``, ``atom_cell_ok``) are mandatory.
    - Missing, ``None``, ``"unknown"``, or non-boolean scalar values (including ``0``/``1``)
      raise ``ValueError``.
    - ``autodetect_ok`` may be ``"not_applicable"`` ONLY when an explicit ``arm`` in
      ``CANONICAL_ARM_IDS`` other than ``"3a"`` is supplied.
    - Any observation may be supplied as an explicit structured unavailable mapping
      ``{"state": "unavailable", "reason": "<non-empty reason>"}`` ONLY when at least one
      independently known ``False`` observation guarantees non-completion (without
      assuming any execution or pipeline ordering among the seven U08 checks).
      Unknown/unavailable observations are preserved separately in ``unknown_observations``
      and ``unavailable_observations`` and are never coerced to ``True`` or mapped to a new
      failure code. Unknown-only would-be completion fails closed.
    - Returns all known detected failure codes in ``detected_failures`` and assigns a unique
      ``status`` automatically only when zero or one known failure is detected. When multiple
      known failures are detected, ``failure_priority`` must be an explicit duplicate-free
      sequence of exact ``U08_FAILURE_STATUS_CODES`` containing each detected failure
      code once; otherwise ``ValueError`` (``unresolved-primary-status``) is raised.
    - Never emits a ninth scientific status; ``provenance_id`` and ``reference_id`` are
      preserved as separate metadata fields.
    """
    if arm is not None:
        if not isinstance(arm, str) or arm not in CANONICAL_ARM_IDS:
            raise ValueError(
                f"arm must be one of {CANONICAL_ARM_IDS}, got {arm!r}."
            )

    if provenance_id is not None:
        provenance_id = _validate_nonempty_str(provenance_id, field_name="provenance_id")
    if reference_id is not None:
        reference_id = _validate_nonempty_str(reference_id, field_name="reference_id")

    kw_obs = {
        "process_ok": process_ok,
        "budget_ok": budget_ok,
        "artifacts_ok": artifacts_ok,
        "autodetect_ok": autodetect_ok,
        "reflections_ok": reflections_ok,
        "flags_ok": flags_ok,
        "atom_cell_ok": atom_cell_ok,
    }
    supplied_kw = {k: v for k, v in kw_obs.items() if v is not _MISSING}

    if observations is not None:
        if not isinstance(observations, Mapping):
            raise ValueError("observations must be a mapping of U08 observation flags.")
        extra_obs = set(observations.keys()) - REQUIRED_OBSERVATION_KEYS
        if extra_obs:
            raise ValueError(
                f"Unsupported observation keys {sorted(extra_obs)}; "
                f"expected {sorted(REQUIRED_OBSERVATION_KEYS)}."
            )
        missing_obs = REQUIRED_OBSERVATION_KEYS - set(observations.keys())
        if missing_obs:
            raise ValueError(
                f"Missing required U08 observation keys: {sorted(missing_obs)}."
            )
        for k, v in supplied_kw.items():
            if observations[k] != v or type(observations[k]) is not type(v):
                raise ValueError(
                    f"Conflicting observation value for {k!r} between observations mapping "
                    "and keyword argument."
                )
        raw_obs = dict(observations)
    else:
        missing_kw = [k for k, v in kw_obs.items() if v is _MISSING]
        if missing_kw:
            raise ValueError(
                f"Missing required U08 observation arguments: {sorted(missing_kw)}."
            )
        raw_obs = supplied_kw

    normalized_obs: dict[str, bool | str | dict[str, str]] = {}
    detected_failures: list[str] = []
    unavailable_keys: list[str] = []
    unavailable_observations: dict[str, dict[str, str]] = {}

    for obs_key, failure_code in OBSERVATION_TO_FAILURE_CODE:
        raw_val = raw_obs[obs_key]
        if obs_key == "autodetect_ok" and raw_val == "not_applicable":
            if arm is None or arm == "3a":
                raise ValueError(
                    "autodetect_ok='not_applicable' is permitted only when an explicit "
                    "non-'3a' canonical arm is supplied."
                )
            normalized_obs[obs_key] = "not_applicable"
            continue

        if isinstance(raw_val, Mapping):
            parsed_unavail = _parse_unavailable_observation(raw_val, field_name=obs_key)
            normalized_obs[obs_key] = parsed_unavail
            unavailable_keys.append(obs_key)
            unavailable_observations[obs_key] = parsed_unavail
            continue

        bval = _validate_strict_bool(raw_val, field_name=obs_key)
        if obs_key == "autodetect_ok" and bval is False and arm is not None and arm != "3a":
            raise ValueError(
                "autodetect_ok=False (INCOMMENSURABLE_ARM3A_AUTODETECT_MISMATCH) is "
                f"applicable only to arm '3a', not arm {arm!r}."
            )
        normalized_obs[obs_key] = bval
        if not bval:
            detected_failures.append(failure_code)

    if unavailable_keys and not detected_failures:
        raise ValueError(
            "Unavailable/unknown observations are permitted only when at least one "
            "independently known False check establishes a failure; unknown-only "
            "observations cannot establish COMPLETED_COMMENSURABLE."
        )

    failures_tuple = tuple(detected_failures)
    unknown_obs_tuple = tuple(unavailable_keys)

    normalized_priority: tuple[str, ...] | None = None
    if failure_priority is not None:
        if isinstance(failure_priority, (str, bytes, Mapping)) or not isinstance(
            failure_priority, Sequence
        ):
            raise ValueError(
                "unresolved-primary-status: failure_priority must be a sequence of "
                "U08_FAILURE_STATUS_CODES."
            )
        seen_prio: list[str] = []
        for idx, code in enumerate(failure_priority):
            if not isinstance(code, str) or code not in U08_FAILURE_STATUS_CODES:
                raise ValueError(
                    f"unresolved-primary-status: failure_priority[{idx}]={code!r} is not a "
                    f"valid U08 failure status code ({U08_FAILURE_STATUS_CODES})."
                )
            if code in seen_prio:
                raise ValueError(
                    f"unresolved-primary-status: duplicate failure code {code!r} in failure_priority."
                )
            seen_prio.append(code)
        normalized_priority = tuple(seen_prio)

    if len(failures_tuple) == 0:
        assert len(unknown_obs_tuple) == 0
        primary_status = "COMPLETED_COMMENSURABLE"
    elif len(failures_tuple) == 1:
        if normalized_priority is not None and failures_tuple[0] not in normalized_priority:
            raise ValueError(
                "unresolved-primary-status: supplied failure_priority does not contain "
                f"detected failure {failures_tuple[0]!r}."
            )
        primary_status = failures_tuple[0]
    else:
        if normalized_priority is None:
            raise ValueError(
                "unresolved-primary-status: multiple failures detected "
                f"{list(failures_tuple)}; an explicit caller failure_priority containing "
                "each detected failure once is required."
            )
        missing_from_prio = [f for f in failures_tuple if f not in normalized_priority]
        if missing_from_prio:
            raise ValueError(
                "unresolved-primary-status: failure_priority is missing detected failure(s) "
                f"{missing_from_prio}."
            )
        primary_status = next(code for code in normalized_priority if code in failures_tuple)

    is_commensurable = (len(failures_tuple) == 0 and len(unknown_obs_tuple) == 0)

    return {
        "status": primary_status,
        "primary_status": primary_status,
        "is_commensurable": is_commensurable,
        "detected_failures": failures_tuple,
        "failure_count": len(failures_tuple),
        "unknown_observations": unknown_obs_tuple,
        "unavailable_observations": unavailable_observations,
        "arm": arm,
        "observations": normalized_obs,
        "provenance_id": provenance_id,
        "reference_id": reference_id,
        "registration_status": REGISTRATION_STATUS,
        "stage2_status": STAGE2_RUNTIME_STATUS,
        "executed": False,
    }


def _validate_controller_arm(arm: Any) -> str:
    if not isinstance(arm, str) or arm not in CONTROLLER_ARM_IDS:
        raise ValueError(
            f"Unsupported arm {arm!r} for U12 controller budget verification; "
            f"explicit arm in {CONTROLLER_ARM_IDS} is required."
        )
    return arm


def _validate_role_tokens(role_tokens: Any, *, field_prefix: str) -> tuple[dict[str, int], int]:
    if not isinstance(role_tokens, Mapping):
        raise ValueError(
            f"{field_prefix}.role_tokens must be a mapping covering all 3 planner subroles "
            f"{LLM_SUBROLES}."
        )
    expected_roles = set(LLM_SUBROLES)
    actual_roles = set(role_tokens.keys())
    if actual_roles != expected_roles:
        raise ValueError(
            f"{field_prefix}.role_tokens must contain exact keys {sorted(expected_roles)}, "
            f"got {sorted(actual_roles)}."
        )
    normalized_roles: dict[str, int] = {}
    for role in LLM_SUBROLES:
        entry = role_tokens[role]
        role_field = f"{field_prefix}.role_tokens[{role!r}]"
        if isinstance(entry, Mapping):
            allowed = {
                "prompt_tokens",
                "completion_tokens",
                "total_tokens",
                "tokens",
                "zero_used",
                "status",
            }
            extra = set(entry.keys()) - allowed
            if extra:
                raise ValueError(f"Unsupported keys in {role_field}: {sorted(extra)}.")

            candidates: list[tuple[str, int]] = []
            if "prompt_tokens" in entry or "completion_tokens" in entry:
                if "prompt_tokens" not in entry or "completion_tokens" not in entry:
                    raise ValueError(
                        f"{role_field} token dict must include both 'prompt_tokens' and "
                        "'completion_tokens'."
                    )
                p_tok = _validate_strict_int(
                    entry["prompt_tokens"],
                    field_name=f"{role_field}.prompt_tokens",
                    min_value=0,
                )
                c_tok = _validate_strict_int(
                    entry["completion_tokens"],
                    field_name=f"{role_field}.completion_tokens",
                    min_value=0,
                )
                candidates.append(("prompt_tokens+completion_tokens", p_tok + c_tok))

            for alias_key in ("total_tokens", "tokens"):
                if alias_key in entry:
                    alias_val = _validate_strict_int(
                        entry[alias_key],
                        field_name=f"{role_field}.{alias_key}",
                        min_value=0,
                    )
                    candidates.append((alias_key, alias_val))

            if not candidates:
                raise ValueError(
                    f"{role_field} mapping must specify token counts or explicit zero-used record."
                )

            first_label, tot = candidates[0]
            for other_label, other_val in candidates[1:]:
                if other_val != tot:
                    raise ValueError(
                        f"Conflicting token counts in {role_field}: "
                        f"{first_label} ({tot}) != {other_label} ({other_val})."
                    )

            if "zero_used" in entry:
                zu = _validate_strict_bool(
                    entry["zero_used"], field_name=f"{role_field}.zero_used"
                )
                if zu and tot != 0:
                    raise ValueError(
                        f"{role_field} has zero_used=True but total_tokens={tot}."
                    )
            if "status" in entry:
                st = _validate_nonempty_str(
                    entry["status"], field_name=f"{role_field}.status"
                )
                if st == "zero_used" and tot != 0:
                    raise ValueError(
                        f"{role_field} has status='zero_used' but tokens={tot}."
                    )
            normalized_roles[role] = tot
        else:
            normalized_roles[role] = _validate_strict_int(
                entry,
                field_name=role_field,
                min_value=0,
            )

    total = sum(normalized_roles.values())
    return normalized_roles, total


def _validate_sha256_strict(value: Any, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or _SHA256_RE.fullmatch(value) is None
    ):
        raise ValueError(
            f"{field_name} must be an exact 64-character lowercase hex SHA-256 digest "
            f"(no whitespace or trailing newline), got {value!r}."
        )
    return value


def _validate_raw_provenance_text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"{field_name} must be a non-empty UTF-8 command/receipt text string, got {value!r}."
        )
    return value


def _validate_arm1b_move_provenance(
    move: Mapping[str, Any],
    *,
    move_status: str,
    observed_cycles: int,
    field_prefix: str,
) -> dict[str, Any]:
    nested_prov: Mapping[str, Any] | None = None
    if "arm1b_provenance" in move:
        if not isinstance(move["arm1b_provenance"], Mapping):
            raise ValueError(f"{field_prefix}.arm1b_provenance must be a mapping.")
        nested_prov = move["arm1b_provenance"]
        unknown_nested = sorted(set(nested_prov.keys()) - ALLOWED_ARM1B_PROVENANCE_KEYS)
        if unknown_nested:
            raise ValueError(
                f"{field_prefix}.arm1b_provenance contains unknown keys: {unknown_nested}."
            )

    def _resolve_slot(
        slot_name: str,
        label: str,
        sha_keys: tuple[str, ...],
        text_keys: tuple[str, ...],
    ) -> dict[str, Any]:
        sha_candidates: list[tuple[str, str]] = []
        text_candidates: list[tuple[str, str]] = []
        unavail_candidates: list[tuple[str, str]] = []
        rep_candidates: list[tuple[str, str]] = []

        sources: list[tuple[str, Mapping[str, Any]]] = []
        if nested_prov is not None:
            sources.append((f"{field_prefix}.arm1b_provenance", nested_prov))
        sources.append((field_prefix, move))

        allowed_representations = {
            "unavailable",
            "sha256",
            "utf8_text",
            "utf8_text_and_sha256",
        }

        def _parse_typed_mapping(
            raw_map: Mapping[str, Any], *, src_field: str
        ) -> None:
            allowed_map_keys = {
                "state",
                "representation",
                "sha256",
                "text",
                "reason",
                "verified_artifact_bytes_exist",
            }
            unknown_keys = sorted(set(raw_map.keys()) - allowed_map_keys)
            if unknown_keys:
                raise ValueError(
                    f"{src_field} contains unknown provenance binding keys: {unknown_keys}."
                )
            if "state" not in raw_map:
                raise ValueError(
                    f"{src_field} mapping must declare explicit 'state' ('available' or 'unavailable')."
                )
            state_val = _validate_nonempty_str(
                raw_map["state"], field_name=f"{src_field}.state"
            )
            explicit_rep: str | None = None
            if "representation" in raw_map:
                rep_raw = raw_map["representation"]
                if not isinstance(rep_raw, str) or rep_raw not in allowed_representations:
                    raise ValueError(
                        f"{src_field}.representation must be one of {sorted(allowed_representations)}, "
                        f"got {rep_raw!r}."
                    )
                explicit_rep = rep_raw
            if (
                "verified_artifact_bytes_exist" in raw_map
                and raw_map["verified_artifact_bytes_exist"] is not False
            ):
                raise ValueError(
                    f"{src_field}.verified_artifact_bytes_exist must be False in result-free "
                    "receipt validation (syntax/hash consistency does not prove artifact bytes exist)."
                )
            if state_val == "unavailable":
                if raw_map.get("sha256") is not None or raw_map.get("text") is not None:
                    raise ValueError(
                        f"{src_field} with state='unavailable' cannot also carry sha256 or text."
                    )
                if "reason" not in raw_map:
                    raise ValueError(
                        f"{src_field} with state='unavailable' must supply an explicit 'reason'."
                    )
                reason_val = _validate_nonempty_str(
                    raw_map["reason"], field_name=f"{src_field}.reason"
                )
                if explicit_rep is not None and explicit_rep != "unavailable":
                    raise ValueError(
                        f"{src_field}.representation must be 'unavailable' when state='unavailable', "
                        f"got {explicit_rep!r}."
                    )
                if explicit_rep is not None:
                    rep_candidates.append((f"{src_field}.representation", explicit_rep))
                unavail_candidates.append((src_field, reason_val))
            elif state_val == "available":
                if raw_map.get("reason") is not None:
                    raise ValueError(
                        f"{src_field} with state='available' cannot carry an unavailability 'reason'."
                    )
                has_sha = "sha256" in raw_map and raw_map["sha256"] is not None
                has_text = "text" in raw_map and raw_map["text"] is not None
                if not has_sha and not has_text:
                    raise ValueError(
                        f"{src_field} with state='available' must supply 'sha256' and/or 'text'."
                    )
                if "sha256" in raw_map:
                    sha_candidates.append(
                        (
                            f"{src_field}.sha256",
                            _validate_sha256_strict(
                                raw_map["sha256"], field_name=f"{src_field}.sha256"
                            ),
                        )
                    )
                if "text" in raw_map:
                    text_candidates.append(
                        (
                            f"{src_field}.text",
                            _validate_raw_provenance_text(
                                raw_map["text"], field_name=f"{src_field}.text"
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
                        f"{src_field}.representation={explicit_rep!r} contradicts supplied "
                        f"available content (expected {expected_map_rep!r})."
                    )
                if explicit_rep is not None:
                    rep_candidates.append((f"{src_field}.representation", explicit_rep))
            else:
                raise ValueError(
                    f"{src_field}.state must be 'available' or 'unavailable', got {state_val!r}."
                )

        for src_prefix, src_map in sources:
            for sk in sha_keys:
                if sk in src_map:
                    src_field = f"{src_prefix}.{sk}"
                    raw_val = src_map[sk]
                    if isinstance(raw_val, Mapping):
                        _parse_typed_mapping(raw_val, src_field=src_field)
                    elif (
                        isinstance(raw_val, str)
                        and raw_val in UNAVAILABLE_EXECUTION_MARKERS
                    ):
                        unavail_candidates.append((src_field, raw_val))
                    else:
                        sha_candidates.append(
                            (
                                src_field,
                                _validate_sha256_strict(raw_val, field_name=src_field),
                            )
                        )
            for tk in text_keys:
                if tk in src_map:
                    src_field = f"{src_prefix}.{tk}"
                    raw_val = src_map[tk]
                    if isinstance(raw_val, Mapping):
                        _parse_typed_mapping(raw_val, src_field=src_field)
                    elif (
                        isinstance(raw_val, str)
                        and raw_val in UNAVAILABLE_EXECUTION_MARKERS
                    ):
                        unavail_candidates.append((src_field, raw_val))
                    else:
                        text_candidates.append(
                            (
                                src_field,
                                _validate_raw_provenance_text(
                                    raw_val, field_name=src_field
                                ),
                            )
                        )

        if not sha_candidates and not text_candidates and not unavail_candidates:
            raise ValueError(
                f"Arm 1b {field_prefix} is missing required {label} receipt/command binding."
            )

        if unavail_candidates and (sha_candidates or text_candidates):
            raise ValueError(
                f"Arm 1b {field_prefix} {label} binding has conflicting unavailability "
                f"({unavail_candidates[0][0]}={unavail_candidates[0][1]!r}) and available "
                "digest/text representations."
            )

        if unavail_candidates:
            base_src, base_reason = unavail_candidates[0]
            for other_src, other_reason in unavail_candidates[1:]:
                if other_reason != base_reason:
                    raise ValueError(
                        f"Arm 1b {field_prefix} {label} unavailability aliases disagree: "
                        f"{base_src}={base_reason!r} vs {other_src}={other_reason!r}."
                    )
            return {
                "state": "unavailable",
                "representation": "unavailable",
                "sha256": None,
                "text": None,
                "reason": base_reason,
                "verified_artifact_bytes_exist": False,
            }

        resolved_sha: str | None = None
        if sha_candidates:
            base_sha_src, resolved_sha = sha_candidates[0]
            for other_sha_src, other_sha in sha_candidates[1:]:
                if other_sha != resolved_sha:
                    raise ValueError(
                        f"Arm 1b {field_prefix} {label} SHA-256 aliases disagree: "
                        f"{base_sha_src}={resolved_sha!r} vs {other_sha_src}={other_sha!r}."
                    )

        resolved_text: str | None = None
        if text_candidates:
            base_txt_src, resolved_text = text_candidates[0]
            for other_txt_src, other_txt in text_candidates[1:]:
                if other_txt != resolved_text:
                    raise ValueError(
                        f"Arm 1b {field_prefix} {label} command/receipt text aliases disagree: "
                        f"{base_txt_src}={resolved_text!r} vs {other_txt_src}={other_txt!r}."
                    )

        if resolved_text is not None:
            computed_sha = hashlib.sha256(resolved_text.encode("utf-8")).hexdigest()
            if resolved_sha is not None and computed_sha != resolved_sha:
                raise ValueError(
                    f"Arm 1b {field_prefix} {label} UTF-8 SHA-256 mismatch between raw text "
                    f"({computed_sha}) and declared sha256 ({resolved_sha})."
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
                    f"Arm 1b {field_prefix} {label} explicit representation {rep_src}={rep_val!r} "
                    f"contradicts resolved slot representation {representation!r}."
                )

        return {
            "state": "available",
            "representation": representation,
            "sha256": final_sha,
            "text": resolved_text,
            "reason": None,
            "verified_artifact_bytes_exist": False,
        }

    resolved_slots: dict[str, dict[str, Any]] = {}
    for slot_name, label, sha_keys, text_keys in ARM1B_PROVENANCE_SLOT_SPECS:
        resolved_slots[slot_name] = _resolve_slot(slot_name, label, sha_keys, text_keys)

    if move_status == "completed":
        for slot_name, slot_label, _, _ in ARM1B_PROVENANCE_SLOT_SPECS:
            if resolved_slots[slot_name]["state"] != "available":
                raise ValueError(
                    f"Arm 1b {field_prefix} with move_status='completed' requires available "
                    f"{slot_label} binding, got state='unavailable'."
                )
    elif move_status == "aborted_before_execution":
        for exec_slot, exec_label in (
            ("actual_command", "actual-command"),
            ("effective_eff", "effective-.eff"),
        ):
            slot_entry = resolved_slots[exec_slot]
            if (
                slot_entry["state"] != "unavailable"
                or slot_entry["reason"] not in UNAVAILABLE_NOT_EXECUTED_MARKERS
            ):
                raise ValueError(
                    f"Arm 1b {field_prefix} with status 'aborted_before_execution' must record "
                    f"explicit unavailable state (reason in {sorted(UNAVAILABLE_NOT_EXECUTED_MARKERS)}) "
                    f"for {exec_label} and cannot supply a fake hash or command."
                )

    if observed_cycles > 0:
        for exec_slot, exec_label in (
            ("actual_command", "actual-command"),
            ("effective_eff", "effective-.eff"),
        ):
            slot_entry = resolved_slots[exec_slot]
            if (
                slot_entry["state"] == "unavailable"
                and slot_entry["reason"] in UNAVAILABLE_NOT_EXECUTED_MARKERS
            ):
                raise ValueError(
                    f"Arm 1b {field_prefix} {exec_label} binding claims non-execution "
                    f"(reason={slot_entry['reason']!r}), which contradicts "
                    f"observed_macro_cycles={observed_cycles} (> 0) on "
                    f"move_status={move_status!r}."
                )

    return {
        "primary_command": resolved_slots["primary_command"],
        "mechanical_backup": resolved_slots["mechanical_backup"],
        "actual_command": resolved_slots["actual_command"],
        "effective_eff": resolved_slots["effective_eff"],
        "verified_artifact_bytes_exist": False,
        "epistemic_note": (
            "Receipt syntax and SHA-256 consistency only; does not prove actual artifact bytes exist."
        ),
    }


def verify_controller_budget(
    *,
    arm: str,
    ledger: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Verify an ordered U12 agentic controller (Arm 1a / Arm 1b) move ledger.

    Separates post-hoc observed ledger verification from prospective move admission:
    - Malformed or incomplete ledger data (non-mapping moves, missing required fields,
      non-contiguous ``move_index``, invalid/conflicting ``move_status``, bool/negative/non-int
      counts, non-finite/negative/decreasing ``elapsed_seconds``, ``aborted_before_execution``
      with non-zero ``observed_macro_cycles``, or missing/invalid ``Arm 1b`` provenance
      bindings) raises ``ValueError``.
    - Well-formed finite non-negative observed ledgers that exceed U12 caps
      (``> 8`` outer moves, ``> 25`` planned/observed macro-cycles, ``> 150,000`` total
      tokens, ``> 7200.0`` elapsed seconds) or violate move compliance rules
      (``observed_macro_cycles > planned_macro_cycles``, Move 1 ``planned_macro_cycles != 5``,
      completed Move 1 ``observed_macro_cycles != 5``, completed move with ``0`` observed
      macro-cycles, or ``configured_cpu_threads != 8``) are NOT discarded by exceptions:
      they return the full normalized ledger with uncoerced actual values,
      ``budget_ok=False``, exact ``violation_codes`` and ``violation_reasons``, and
      ``retained_in_denominator=True``.
    - Supports explicit ``move_kind`` in ``{'refinement', 'non_refinement'}`` (synthetic
      contract declaration, not native PHENIX program-identity proof; defaults to
      ``'refinement'`` when omitted, never inferred from zero macro-cycles). Move 1 must be
      ``move_kind='refinement'`` with ``planned_macro_cycles == 5`` (and ``observed_macro_cycles == 5``
      when completed). Later ``non_refinement`` moves (``move_index >= 2``) require
      ``planned_macro_cycles == 0`` and ``observed_macro_cycles == 0`` while retaining
      outer move count, token, wall-clock, thread, and ``Arm 1b`` receipt accounting.
      Later ``refinement`` moves require positive ``planned_macro_cycles >= 1``.
    - Reports move-ledger facts ``all_recorded_moves_completed`` and
      ``contains_failed_or_aborted_move`` alongside ``scientific_arm_completion="not_assessed"``.
      These are move-ledger facts only, not a U08 arm-outcome assignment; a single
      completed move (or ledger of completed moves) cannot establish whole-arm completion.
    """
    validated_arm = _validate_controller_arm(arm)
    if (
        isinstance(ledger, (str, bytes, Mapping))
        or not isinstance(ledger, Sequence)
        or len(ledger) == 0
    ):
        raise ValueError("ledger must be a non-empty sequence of move mappings.")

    normalized_moves: list[dict[str, Any]] = []
    violation_codes: list[str] = []
    violation_reasons: list[str] = []
    prev_elapsed = 0.0
    cum_planned_cycles = 0
    cum_observed_cycles = 0
    cum_tokens = 0
    role_token_totals = {role: 0 for role in LLM_SUBROLES}

    def _record_violation(
        code: str, reason: str, move_violations: list[str] | None = None
    ) -> None:
        if code not in violation_codes:
            violation_codes.append(code)
        violation_reasons.append(reason)
        if move_violations is not None:
            move_violations.append(reason)

    for idx, move in enumerate(ledger):
        expected_idx = idx + 1
        prefix = f"ledger[{idx}]"
        if not isinstance(move, Mapping):
            raise ValueError(f"{prefix} must be a mapping.")

        if "move_index" not in move:
            raise ValueError(f"{prefix} is missing required 'move_index'.")
        move_index = _validate_strict_int(
            move["move_index"], field_name=f"{prefix}.move_index", min_value=1
        )
        if move_index != expected_idx:
            raise ValueError(
                f"{prefix}.move_index must be {expected_idx} (contiguous 1..N without gaps or "
                f"duplicates), got {move_index}."
            )

        move_violations: list[str] = []
        if move_index > MAX_OUTER_MOVES:
            _record_violation(
                "move_count_exceeded",
                f"move_count_exceeded: {prefix}.move_index={move_index} exceeds U12 cap of {MAX_OUTER_MOVES} outer moves.",
                move_violations,
            )

        move_kind_explicit = "move_kind" in move
        if move_kind_explicit:
            raw_kind = move["move_kind"]
            if not isinstance(raw_kind, str) or raw_kind not in ALLOWED_MOVE_KINDS:
                raise ValueError(
                    f"{prefix}.move_kind must be one of {sorted(ALLOWED_MOVE_KINDS)}, "
                    f"got {raw_kind!r}."
                )
            move_kind = raw_kind
        else:
            move_kind = "refinement"

        if move_index == 1 and move_kind != "refinement":
            raise ValueError(
                f"{prefix} (Move 1) must have move_kind='refinement'; "
                "move_kind='non_refinement' is permitted only on later moves (move_index >= 2)."
            )

        supplied_statuses: list[tuple[str, str]] = []
        for status_key in ("move_status", "status"):
            if status_key in move:
                val_st = move[status_key]
                if not isinstance(val_st, str) or val_st not in ALLOWED_MOVE_STATUSES:
                    raise ValueError(
                        f"{prefix}.{status_key} must be one of {sorted(ALLOWED_MOVE_STATUSES)}, "
                        f"got {val_st!r}."
                    )
                supplied_statuses.append((status_key, val_st))
        if not supplied_statuses:
            raise ValueError(
                f"{prefix} is missing required explicit 'move_status' (or 'status')."
            )
        first_st_key, move_status = supplied_statuses[0]
        for other_st_key, other_st_val in supplied_statuses[1:]:
            if other_st_val != move_status:
                raise ValueError(
                    f"Conflicting status fields on {prefix}: "
                    f"{first_st_key}={move_status!r} vs {other_st_key}={other_st_val!r}."
                )

        if "planned_macro_cycles" not in move:
            raise ValueError(f"{prefix} is missing required 'planned_macro_cycles'.")
        if "observed_macro_cycles" not in move:
            raise ValueError(f"{prefix} is missing required 'observed_macro_cycles'.")

        if move_kind == "non_refinement":
            planned_cycles = _validate_strict_int(
                move["planned_macro_cycles"],
                field_name=f"{prefix}.planned_macro_cycles",
                min_value=0,
            )
            observed_cycles = _validate_strict_int(
                move["observed_macro_cycles"],
                field_name=f"{prefix}.observed_macro_cycles",
                min_value=0,
            )
            if planned_cycles != 0 or observed_cycles != 0:
                raise ValueError(
                    f"{prefix} with move_kind='non_refinement' requires "
                    "planned_macro_cycles == 0 and observed_macro_cycles == 0, "
                    f"got planned={planned_cycles}, observed={observed_cycles}."
                )
        else:
            planned_cycles = _validate_strict_int(
                move["planned_macro_cycles"],
                field_name=f"{prefix}.planned_macro_cycles",
                min_value=1,
            )
            if move_index == 1 and planned_cycles != MOVE_1_REQUIRED_MACRO_CYCLES:
                _record_violation(
                    "move_1_planned_macro_cycles_mismatch",
                    f"move_1_planned_macro_cycles_mismatch: {prefix}.planned_macro_cycles={planned_cycles} "
                    f"!= required {MOVE_1_REQUIRED_MACRO_CYCLES}.",
                    move_violations,
                )

            observed_cycles = _validate_strict_int(
                move["observed_macro_cycles"],
                field_name=f"{prefix}.observed_macro_cycles",
                min_value=0,
            )
            if observed_cycles > planned_cycles:
                _record_violation(
                    "observed_macro_cycles_exceed_planned",
                    f"observed_macro_cycles_exceed_planned: {prefix}.observed_macro_cycles ({observed_cycles}) "
                    f"exceeds planned_macro_cycles ({planned_cycles}).",
                    move_violations,
                )

            if move_status == "completed":
                if move_index == 1 and observed_cycles != MOVE_1_REQUIRED_MACRO_CYCLES:
                    _record_violation(
                        "move_1_completed_observed_macro_cycles_mismatch",
                        f"move_1_completed_observed_macro_cycles_mismatch: completed Move 1 "
                        f"observed_macro_cycles={observed_cycles} != required {MOVE_1_REQUIRED_MACRO_CYCLES}.",
                        move_violations,
                    )
                elif observed_cycles == 0:
                    _record_violation(
                        "completed_move_zero_observed_macro_cycles",
                        f"completed_move_zero_observed_macro_cycles: {prefix} marked 'completed' "
                        "with observed_macro_cycles == 0.",
                        move_violations,
                    )
            elif move_status == "aborted_before_execution":
                if observed_cycles != 0:
                    raise ValueError(
                        f"{prefix} marked 'aborted_before_execution' must have "
                        f"observed_macro_cycles == 0, got {observed_cycles}."
                    )

        if cum_observed_cycles + planned_cycles > MAX_MACRO_CYCLES:
            _record_violation(
                "planned_macro_cycles_exceeded",
                f"planned_macro_cycles_exceeded: {prefix} planned_macro_cycles ({planned_cycles}) "
                f"plus prior observed cycles ({cum_observed_cycles}) exceeds U12 cap of {MAX_MACRO_CYCLES}.",
                move_violations,
            )

        if "role_tokens" not in move:
            raise ValueError(f"{prefix} is missing required 'role_tokens'.")
        role_counts, move_tokens = _validate_role_tokens(
            move["role_tokens"], field_prefix=prefix
        )
        for move_tok_key in ("total_tokens", "tokens"):
            if move_tok_key in move:
                explicit_move_tot = _validate_strict_int(
                    move[move_tok_key],
                    field_name=f"{prefix}.{move_tok_key}",
                    min_value=0,
                )
                if explicit_move_tot != move_tokens:
                    raise ValueError(
                        f"{prefix}.{move_tok_key} ({explicit_move_tot}) does not match sum of "
                        f"role_tokens ({move_tokens})."
                    )

        if "elapsed_seconds" not in move:
            raise ValueError(f"{prefix} is missing required 'elapsed_seconds'.")
        elapsed = _validate_finite_nonnegative_float(
            move["elapsed_seconds"], field_name=f"{prefix}.elapsed_seconds"
        )
        if elapsed < prev_elapsed:
            raise ValueError(
                f"{prefix}.elapsed_seconds ({elapsed}) decreased from previous move "
                f"({prev_elapsed})."
            )
        prev_elapsed = elapsed

        if "configured_cpu_threads" not in move:
            raise ValueError(f"{prefix} is missing required 'configured_cpu_threads'.")
        threads = _validate_strict_int(
            move["configured_cpu_threads"],
            field_name=f"{prefix}.configured_cpu_threads",
            min_value=1,
        )
        if threads != REQUIRED_CONFIGURED_CPU_THREADS:
            _record_violation(
                "configured_cpu_threads_mismatch",
                f"configured_cpu_threads_mismatch: {prefix}.configured_cpu_threads={threads} "
                f"!= required {REQUIRED_CONFIGURED_CPU_THREADS}.",
                move_violations,
            )

        obs_cpu: float | None = None
        for cpu_obs_key in ("observed_cpu_utilization", "observed_cpu_threads"):
            if cpu_obs_key in move and move[cpu_obs_key] is not None:
                obs_cpu = _validate_finite_nonnegative_float(
                    move[cpu_obs_key], field_name=f"{prefix}.{cpu_obs_key}"
                )
                break

        arm1b_prov: dict[str, Any] | None = None
        if validated_arm == "1b":
            arm1b_prov = _validate_arm1b_move_provenance(
                move,
                move_status=move_status,
                observed_cycles=observed_cycles,
                field_prefix=prefix,
            )

        cum_planned_cycles += planned_cycles
        cum_observed_cycles += observed_cycles
        cum_tokens += move_tokens
        for r_key, r_val in role_counts.items():
            role_token_totals[r_key] += r_val

        if cum_observed_cycles > MAX_MACRO_CYCLES:
            _record_violation(
                "observed_macro_cycles_exceeded",
                f"observed_macro_cycles_exceeded: cumulative observed_macro_cycles ({cum_observed_cycles}) "
                f"at {prefix} exceeds U12 cap of {MAX_MACRO_CYCLES}.",
                move_violations,
            )
        if cum_tokens > MAX_TOTAL_TOKENS:
            _record_violation(
                "total_tokens_exceeded",
                f"total_tokens_exceeded: cumulative total_tokens ({cum_tokens}) at {prefix} "
                f"exceeds U12 cap of {MAX_TOTAL_TOKENS}.",
                move_violations,
            )
        if elapsed > MAX_ELAPSED_SECONDS:
            _record_violation(
                "elapsed_seconds_exceeded",
                f"elapsed_seconds_exceeded: cumulative elapsed_seconds ({elapsed}) at {prefix} "
                f"exceeds U12 cap of {MAX_ELAPSED_SECONDS}.",
                move_violations,
            )

        move_compliant_completed = (
            move_status == "completed" and len(move_violations) == 0
        )

        normalized_moves.append(
            {
                "move_index": move_index,
                "move_kind": move_kind,
                "move_kind_explicit": move_kind_explicit,
                "move_status": move_status,
                "planned_macro_cycles": planned_cycles,
                "observed_macro_cycles": observed_cycles,
                "role_tokens": role_counts,
                "move_total_tokens": move_tokens,
                "elapsed_seconds": elapsed,
                "configured_cpu_threads": threads,
                "observed_cpu_utilization": obs_cpu,
                "arm1b_provenance": arm1b_prov,
                "completed_checkpoint": move_compliant_completed,
                "violation_reasons": tuple(move_violations),
            }
        )

    move_1 = normalized_moves[0]
    move_1_checkpoint_completed = bool(
        move_1["completed_checkpoint"]
        and move_1["move_kind"] == "refinement"
        and move_1["planned_macro_cycles"] == MOVE_1_REQUIRED_MACRO_CYCLES
        and move_1["observed_macro_cycles"] == MOVE_1_REQUIRED_MACRO_CYCLES
        and move_1["configured_cpu_threads"] == REQUIRED_CONFIGURED_CPU_THREADS
    )
    all_recorded_moves_completed = all(
        m["move_status"] == "completed" for m in normalized_moves
    )
    budget_ok = len(violation_reasons) == 0
    unique_threads = {m["configured_cpu_threads"] for m in normalized_moves}
    summary_threads: int | tuple[int, ...] = (
        next(iter(unique_threads))
        if len(unique_threads) == 1
        else tuple(m["configured_cpu_threads"] for m in normalized_moves)
    )

    return {
        "budget_ok": budget_ok,
        "violation_codes": tuple(violation_codes),
        "violation_reasons": tuple(violation_reasons),
        "arm": validated_arm,
        "move_count": len(normalized_moves),
        "total_planned_macro_cycles": cum_planned_cycles,
        "total_observed_macro_cycles": cum_observed_cycles,
        "total_tokens": cum_tokens,
        "role_token_totals": role_token_totals,
        "elapsed_seconds": prev_elapsed,
        "configured_cpu_threads": summary_threads,
        "move_1_planned_macro_cycles": move_1["planned_macro_cycles"],
        "move_1_observed_macro_cycles": move_1["observed_macro_cycles"],
        "move_1_checkpoint_completed": move_1_checkpoint_completed,
        "all_recorded_moves_completed": all_recorded_moves_completed,
        "contains_failed_or_aborted_move": (not all_recorded_moves_completed),
        "scientific_arm_completion": "not_assessed",
        "retained_in_denominator": True,
        "moves": tuple(normalized_moves),
        "registration_status": REGISTRATION_STATUS,
        "stage2_status": STAGE2_RUNTIME_STATUS,
        "executed": False,
    }


def admit_controller_move(
    *,
    arm: str,
    ledger: Sequence[Mapping[str, Any]],
    requested_usage: Mapping[str, Any],
) -> dict[str, Any]:
    """Prospectively validate and admit the next controller move BEFORE execution.

    Accounts for requested increments (move count, ``move_kind``, ``planned_macro_cycles``,
    requested token budget, and projected ``elapsed_seconds``) against the U12 caps
    (``8`` moves, ``25`` macro-cycles, ``150,000`` tokens, ``7,200`` seconds,
    ``configured_cpu_threads == 8``, Move 1 ``move_kind='refinement'`` and
    ``planned_macro_cycles == 5``, later ``non_refinement`` moves requiring
    ``planned_macro_cycles == 0``, and later ``refinement`` moves requiring
    ``planned_macro_cycles >= 1``) before the move is executed.

    Prospective continuation after a failed or aborted move in ``ledger`` is
    unsupported because this implementation lacks a selected post-failure transition
    policy (not because the selected U08/U10/U12 policy forbids retries or defines
    a single failed move as whole-arm failure). Any prior ledger with
    ``budget_ok=False`` or with any U12 cumulative cap already exhausted
    (``8`` outer moves, ``25`` observed macro-cycles, ``150,000`` tokens, or
    ``7,200.0`` elapsed seconds) also stops prospective move admission (while
    an observed ledger at the cap remains compliant/retained and an incoming move
    from below a cap may reach the cap).
    """
    validated_arm = _validate_controller_arm(arm)
    if isinstance(ledger, (str, bytes, Mapping)) or not isinstance(ledger, Sequence):
        raise ValueError("ledger must be a sequence of prior move mappings.")
    if not isinstance(requested_usage, Mapping):
        raise ValueError("requested_usage must be a mapping.")

    if len(ledger) == 0:
        prior_moves = 0
        prior_observed_cycles = 0
        prior_tokens = 0
        prior_elapsed = 0.0
    else:
        prior_summary = verify_controller_budget(arm=validated_arm, ledger=ledger)
        if prior_summary["contains_failed_or_aborted_move"]:
            raise ValueError(
                "Prospective continuation after a failed or aborted move is unsupported: "
                "this implementation lacks a selected transition policy "
                "(the selected U08/U10/U12 policy does not forbid retries or define "
                "whole-arm failure from a single move)."
            )
        if not prior_summary["budget_ok"]:
            raise ValueError(
                "Cannot admit a new controller move after prior ledger budget/compliance "
                f"violation(s): {prior_summary['violation_reasons']!r}."
            )
        prior_moves = prior_summary["move_count"]
        prior_observed_cycles = prior_summary["total_observed_macro_cycles"]
        prior_tokens = prior_summary["total_tokens"]
        prior_elapsed = prior_summary["elapsed_seconds"]
        if prior_moves >= MAX_OUTER_MOVES:
            raise ValueError(
                f"Prospective move {prior_moves + 1} stopped: prior ledger has already "
                f"exhausted the U12 outer-move cap ({prior_moves}/{MAX_OUTER_MOVES})."
            )
        if prior_observed_cycles >= MAX_MACRO_CYCLES:
            raise ValueError(
                f"Prospective move {prior_moves + 1} stopped: prior ledger has already "
                f"exhausted the U12 cumulative macro-cycle cap "
                f"({prior_observed_cycles}/{MAX_MACRO_CYCLES})."
            )
        if prior_tokens >= MAX_TOTAL_TOKENS:
            raise ValueError(
                f"Prospective move {prior_moves + 1} stopped: prior ledger has already "
                f"exhausted the U12 cumulative token cap "
                f"({prior_tokens}/{MAX_TOTAL_TOKENS})."
            )
        if prior_elapsed >= MAX_ELAPSED_SECONDS:
            raise ValueError(
                f"Prospective move {prior_moves + 1} stopped: prior ledger has already "
                f"exhausted the U12 cumulative wall-clock cap "
                f"({prior_elapsed}/{MAX_ELAPSED_SECONDS}s)."
            )

    next_move_index = prior_moves + 1
    if next_move_index > MAX_OUTER_MOVES:
        raise ValueError(
            f"Prospective move {next_move_index} exceeds U12 cap of {MAX_OUTER_MOVES} outer moves."
        )

    if "move_index" in requested_usage and requested_usage["move_index"] is not None:
        req_idx = _validate_strict_int(
            requested_usage["move_index"],
            field_name="requested_usage.move_index",
            min_value=1,
        )
        if req_idx != next_move_index:
            raise ValueError(
                f"requested_usage.move_index must be {next_move_index}, got {req_idx}."
            )

    move_kind_explicit = "move_kind" in requested_usage
    if move_kind_explicit:
        raw_req_kind = requested_usage["move_kind"]
        if not isinstance(raw_req_kind, str) or raw_req_kind not in ALLOWED_MOVE_KINDS:
            raise ValueError(
                f"requested_usage.move_kind must be one of {sorted(ALLOWED_MOVE_KINDS)}, "
                f"got {raw_req_kind!r}."
            )
        move_kind = raw_req_kind
    else:
        move_kind = "refinement"

    if next_move_index == 1 and move_kind != "refinement":
        raise ValueError(
            "Prospective Move 1 requires move_kind='refinement'; "
            "move_kind='non_refinement' is permitted only on later moves (next_move_index >= 2)."
        )

    if "planned_macro_cycles" not in requested_usage:
        raise ValueError("requested_usage requires 'planned_macro_cycles'.")
    if move_kind == "non_refinement":
        planned_cycles = _validate_strict_int(
            requested_usage["planned_macro_cycles"],
            field_name="requested_usage.planned_macro_cycles",
            min_value=0,
        )
        if planned_cycles != 0:
            raise ValueError(
                f"Prospective move {next_move_index} with move_kind='non_refinement' "
                f"requires planned_macro_cycles == 0, got {planned_cycles}."
            )
        if (
            "observed_macro_cycles" in requested_usage
            and requested_usage["observed_macro_cycles"] is not None
        ):
            obs_req = _validate_strict_int(
                requested_usage["observed_macro_cycles"],
                field_name="requested_usage.observed_macro_cycles",
                min_value=0,
            )
            if obs_req != 0:
                raise ValueError(
                    f"Prospective move {next_move_index} with move_kind='non_refinement' "
                    f"requires observed_macro_cycles == 0 when supplied, got {obs_req}."
                )
    else:
        planned_cycles = _validate_strict_int(
            requested_usage["planned_macro_cycles"],
            field_name="requested_usage.planned_macro_cycles",
            min_value=1,
        )
        if next_move_index == 1 and planned_cycles != MOVE_1_REQUIRED_MACRO_CYCLES:
            raise ValueError(
                f"Prospective Move 1 requires planned_macro_cycles == {MOVE_1_REQUIRED_MACRO_CYCLES}, "
                f"got {planned_cycles}."
            )

    if "configured_cpu_threads" not in requested_usage:
        raise ValueError("requested_usage requires 'configured_cpu_threads'.")
    threads = _validate_strict_int(
        requested_usage["configured_cpu_threads"],
        field_name="requested_usage.configured_cpu_threads",
        min_value=1,
    )
    if threads != REQUIRED_CONFIGURED_CPU_THREADS:
        raise ValueError(
            f"requested_usage.configured_cpu_threads must be {REQUIRED_CONFIGURED_CPU_THREADS}, "
            f"got {threads}."
        )

    supplied_token_aliases: list[tuple[str, int]] = []
    if "role_tokens" in requested_usage:
        _, role_sum = _validate_role_tokens(
            requested_usage["role_tokens"], field_prefix="requested_usage"
        )
        supplied_token_aliases.append(("role_tokens", role_sum))
    for tok_key in ("requested_tokens", "estimated_tokens", "total_tokens", "tokens"):
        if tok_key in requested_usage:
            val_tok = _validate_strict_int(
                requested_usage[tok_key],
                field_name=f"requested_usage.{tok_key}",
                min_value=0,
            )
            supplied_token_aliases.append((tok_key, val_tok))
    if not supplied_token_aliases:
        raise ValueError(
            "requested_usage requires 'requested_tokens' (or 'role_tokens' / 'total_tokens')."
        )
    first_tok_key, req_tokens = supplied_token_aliases[0]
    for other_tok_key, other_tok_val in supplied_token_aliases[1:]:
        if other_tok_val != req_tokens:
            raise ValueError(
                f"Conflicting token aliases in requested_usage: "
                f"{first_tok_key} ({req_tokens}) != {other_tok_key} ({other_tok_val})."
            )

    supplied_elapsed_aliases: list[tuple[str, float]] = []
    for inc_key in ("requested_elapsed_seconds", "estimated_elapsed_seconds"):
        if inc_key in requested_usage:
            inc_sec = _validate_finite_nonnegative_float(
                requested_usage[inc_key],
                field_name=f"requested_usage.{inc_key}",
            )
            supplied_elapsed_aliases.append((inc_key, prior_elapsed + inc_sec))
    for cum_key in (
        "elapsed_seconds",
        "cumulative_elapsed_seconds",
        "projected_elapsed_seconds",
    ):
        if cum_key in requested_usage:
            cum_sec = _validate_finite_nonnegative_float(
                requested_usage[cum_key],
                field_name=f"requested_usage.{cum_key}",
            )
            if cum_sec < prior_elapsed:
                raise ValueError(
                    f"requested_usage.{cum_key} ({cum_sec}) is less than prior "
                    f"elapsed_seconds ({prior_elapsed})."
                )
            supplied_elapsed_aliases.append((cum_key, cum_sec))
    if not supplied_elapsed_aliases:
        raise ValueError(
            "requested_usage requires 'requested_elapsed_seconds' or cumulative 'elapsed_seconds'."
        )
    first_el_key, projected_elapsed = supplied_elapsed_aliases[0]
    for other_el_key, other_el_cum in supplied_elapsed_aliases[1:]:
        if other_el_cum != projected_elapsed:
            raise ValueError(
                f"Conflicting prospective elapsed_seconds aliases in requested_usage: "
                f"{first_el_key} implies cumulative {projected_elapsed!r}s vs "
                f"{other_el_key} implies cumulative {other_el_cum!r}s."
            )

    projected_cycles = prior_observed_cycles + planned_cycles
    projected_tokens = prior_tokens + req_tokens

    if projected_cycles > MAX_MACRO_CYCLES:
        raise ValueError(
            f"Prospective move {next_move_index} projected macro-cycles ({projected_cycles}) "
            f"exceeds U12 cap of {MAX_MACRO_CYCLES}."
        )
    if projected_tokens > MAX_TOTAL_TOKENS:
        raise ValueError(
            f"Prospective move {next_move_index} projected tokens ({projected_tokens}) "
            f"exceeds U12 cap of {MAX_TOTAL_TOKENS}."
        )
    if projected_elapsed > MAX_ELAPSED_SECONDS:
        raise ValueError(
            f"Prospective move {next_move_index} projected elapsed_seconds ({projected_elapsed}) "
            f"exceeds U12 cap of {MAX_ELAPSED_SECONDS}."
        )

    return {
        "admitted": True,
        "arm": validated_arm,
        "next_move_index": next_move_index,
        "move_kind": move_kind,
        "move_kind_explicit": move_kind_explicit,
        "planned_macro_cycles": planned_cycles,
        "projected_move_count": next_move_index,
        "projected_macro_cycles": projected_cycles,
        "projected_total_tokens": projected_tokens,
        "projected_elapsed_seconds": projected_elapsed,
        "configured_cpu_threads": REQUIRED_CONFIGURED_CPU_THREADS,
        "registration_status": REGISTRATION_STATUS,
        "stage2_status": STAGE2_RUNTIME_STATUS,
        "executed": False,
    }


__all__ = [
    "ALLOWED_MOVE_KINDS",
    "ALLOWED_MOVE_STATUSES",
    "CANONICAL_ARM_IDS",
    "CONTROLLER_ARM_IDS",
    "LLM_SUBROLES",
    "MAX_ELAPSED_SECONDS",
    "MAX_MACRO_CYCLES",
    "MAX_OUTER_MOVES",
    "MAX_TOTAL_TOKENS",
    "MOVE_1_REQUIRED_MACRO_CYCLES",
    "OBSERVATION_TO_FAILURE_CODE",
    "REGISTRATION_STATUS",
    "REQUIRED_CONFIGURED_CPU_THREADS",
    "STAGE2_RUNTIME_STATUS",
    "STATIC_WITNESS_PATH",
    "U08_FAILURE_STATUS_CODES",
    "U08_STATUS_CODES",
    "admit_controller_move",
    "classify_u08_status",
    "verify_controller_budget",
]
