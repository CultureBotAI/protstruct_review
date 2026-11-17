#!/usr/bin/env python3
"""Result-free Stage 2 PHENIX Track (ii) perturbation specification compiler (U05).

Scope and epistemic boundary:
- Registration status remains ``selected_decisions_recorded`` (NOT ``frozen_result_free``).
- This module compiles a deterministic, pure-JSON specification record for the U05
  perturbation-recovery track (``Track (ii)``, ``track="perturbation_recovery"``) from an
  anonymous target identifier, parent model SHA-256 digest, and diffraction resolution
  limit ``d_min``.
- It does NOT generate perturbed coordinates, sample any PRNG stream, write files, or
  invoke native crystallographic tools.
- ``track2_seed_digest(anon_target_id)`` computes
  `` HMAC-SHA256(key=b"protstruct-track2-v1", msg=anon_target_id.encode("utf-8")) ``
  and returns the 64-character lowercase hexadecimal digest without choosing an unapproved
  PRNG seed-conversion or stream-partitioning convention.
- Anonymous-ID syntax validation enforces a safe non-empty ASCII identifier and rejects
  bare 4-character PDB accession codes, but syntax validation alone is NOT a proof of
  runtime target anonymization, and the public HMAC key provides determinism rather than
  cryptographic secrecy.
- Source policy selection is pinned to ``ref/research/phenix_step1_user_selections_2026-11-15.md``
  (full-file SHA-256 ``14bbb0c9dc1883c2404f40193e135a4aaa974d8ab605fe95bb78d44c6a704a7b``,
  section ``U05``). Callers cannot substitute an arbitrary source digest and mark it approved.
- Because U05 policy selection leaves concrete execution conventions unresolved (including
  ``ANISOU``-to-isotropic B conversion vs. retained ``B_iso``, ``+/-20%`` log-normal
  parameterization, PRNG algorithm/seed conversion, canonical atom/altloc ordering,
  ``sites.shake`` displacement statistic/sampling realization and atom population,
  surface/pocket eligibility and overlap, exact ``10%`` rounding, torsion atom/altloc
  population and residue-vs-conformer subset counting, and missing-``chi2`` / torsion
  correlation), compiled specifications always set ``executable=False``,
  ``execution_authorized=False``, ``frozen_result_free=False``, and ``executed=False``, and
  :func:`require_executable_perturbation_spec` always fails closed.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import json
import math
from pathlib import Path
import re
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

REGISTRATION_STATUS = "selected_decisions_recorded"
STAGE2_PERTURBATION_STATUS = (
    "result_free_u05_perturbation_spec_not_executable"
)
EXECUTION_AUTHORIZED = False
EXECUTABLE_SPEC = False
FROZEN_RESULT_FREE = False

TRACK2_ID = "perturbation_recovery"
TRACK2_NUMBER = "ii"
UNPOOLED_OTHER_TRACKS: tuple[str, str] = (
    "clean_null_stability",
    "parameter_sensitivity",
)

TRACK2_HMAC_KEY_UTF8 = "protstruct-track2-v1"
TRACK2_HMAC_KEY_BYTES = b"protstruct-track2-v1"
TRACK2_HMAC_ALGORITHM = "HMAC-SHA256"
TRACK2_MESSAGE_ENCODING = "utf-8"

APPROVED_SOURCE_PATH = (
    "ref/research/phenix_step1_user_selections_2026-11-15.md"
)
APPROVED_SOURCE_SHA256 = (
    "14bbb0c9dc1883c2404f40193e135a4aaa974d8ab605fe95bb78d44c6a704a7b"
)
APPROVED_SOURCE_SECTION = "U05"

SITES_SHAKE_D_MIN_THRESHOLD = Decimal("1.50")
SITES_SHAKE_HIGH_RES_ANGSTROM = 0.25
SITES_SHAKE_LOW_RES_ANGSTROM = 0.35

B_FACTOR_JITTER_PERCENT = 20.0
B_FACTOR_JITTER_FRACTION = 0.20
B_FACTOR_CLAMP_MIN_A2 = 5.0
B_FACTOR_CLAMP_MAX_A2 = 150.0

TORSION_NOISE_RMS_DEGREES = 15.0
TORSION_NOISE_SUBSET_FRACTION = 0.10
TORSION_NOISE_SUBSET_PERCENT = 10.0

_SHA256_RE = re.compile(r"^[0-9a-f]{64}\Z")
_ANON_TARGET_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_BARE_PDB_CODE_RE = re.compile(r"^[1-9][A-Za-z0-9]{3}\Z")

UNRESOLVED_EXECUTION_REQUIREMENTS: tuple[dict[str, str], ...] = (
    {
        "requirement_id": "anisou_to_b_iso_conversion_convention",
        "step_operation_id": "strip_anisou_convert_isotropic",
        "description": (
            "Unresolved whether stripping ANISOU retains the existing ATOM/HETATM B_iso "
            "column verbatim or recomputes B_eq = (8*pi^2/3)*tr(U_cart) when they differ."
        ),
    },
    {
        "requirement_id": "lognormal_b_jitter_parameterization_and_atom_scope",
        "step_operation_id": "lognormal_isotropic_b_factor_jitter",
        "description": (
            "Unresolved exact parameterization of +/-20% log-normal B-factor jitter "
            "(sigma_ln vs ln(1.20), zero-mean vs -0.5*sigma^2 drift correction) and "
            "atom/altloc population scope."
        ),
    },
    {
        "requirement_id": "prng_algorithm_seed_conversion_and_stream_version",
        "step_operation_id": "all_stochastic_steps",
        "description": (
            "Unresolved PRNG algorithm, implementation version, integer/state seed "
            "conversion from the 256-bit HMAC-SHA256 digest, and substream partitioning "
            "across B-factor jitter, coordinate shake, and sidechain torsion noise."
        ),
    },
    {
        "requirement_id": "canonical_atom_and_residue_ordering",
        "step_operation_id": "all_stochastic_steps",
        "description": (
            "Unresolved canonical chain, residue, atom, and alternate-conformer (altloc) "
            "ordering that consumes PRNG draws."
        ),
    },
    {
        "requirement_id": "sites_shake_sampling_semantics_and_atom_population",
        "step_operation_id": "coordinate_sites_shake",
        "description": (
            "Unresolved concrete displacement statistic/sampling realization (e.g. "
            "native cctbx/phenix.pdbtools shake passing rms_difference vs. standalone "
            "displacement sampling) and which atom/altloc populations are perturbed "
            "vs. held fixed."
        ),
    },
    {
        "requirement_id": "surface_and_binding_pocket_eligibility_and_overlap",
        "step_operation_id": "surface_and_pocket_chi1_chi2_torsion_noise",
        "description": (
            "Unresolved quantitative SASA cutoff for surface sidechains, binding-pocket "
            "definition on apo vs holo targets, and union vs stratified handling of "
            "residues belonging to both surface and binding pocket."
        ),
    },
    {
        "requirement_id": "ten_percent_subset_rounding_and_sampling_rule",
        "step_operation_id": "surface_and_pocket_chi1_chi2_torsion_noise",
        "description": (
            "Unresolved exact integer rounding rule (floor, round, ceil, minimum count) "
            "for selecting 10% of eligible sidechains and sampling-without-replacement order."
        ),
    },
    {
        "requirement_id": "torsion_atom_and_altloc_population_and_subset_unit",
        "step_operation_id": "surface_and_pocket_chi1_chi2_torsion_noise",
        "description": (
            "Unresolved sidechain torsion atom and alternate-conformer (altloc) "
            "population scope, including which atoms and conformers are perturbed "
            "vs. held fixed and whether the 10% subset counts eligible residues or "
            "individual alternate conformers."
        ),
    },
    {
        "requirement_id": "missing_chi2_and_chi1_chi2_torsion_correlation",
        "step_operation_id": "surface_and_pocket_chi1_chi2_torsion_noise",
        "description": (
            "Unresolved handling of residues lacking chi2 (e.g. SER, THR, CYS, VAL) or "
            "constrained rings (PRO, disulfides), correlation between chi1 and chi2 "
            "noise draws, and downstream sidechain atom rotation convention."
        ),
    },
)


def _validate_anon_target_id(anon_target_id: Any) -> str:
    if not isinstance(anon_target_id, str):
        raise ValueError(
            f"anon_target_id must be a str, got {type(anon_target_id).__name__}."
        )
    if (
        not anon_target_id
        or anon_target_id != anon_target_id.strip()
        or not anon_target_id.isascii()
        or _ANON_TARGET_ID_RE.fullmatch(anon_target_id) is None
    ):
        raise ValueError(
            "anon_target_id must be a non-empty stripped ASCII identifier matching "
            f"{_ANON_TARGET_ID_RE.pattern!r}, got {anon_target_id!r}."
        )
    if _BARE_PDB_CODE_RE.fullmatch(anon_target_id) is not None:
        raise ValueError(
            f"anon_target_id={anon_target_id!r} resembles a bare 4-character PDB "
            "accession code; supply a synthetic/anonymized target identifier."
        )
    return anon_target_id


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


def _validate_d_min(d_min: Any) -> tuple[float, Decimal, str]:
    if isinstance(d_min, bool) or not isinstance(d_min, (int, float, Decimal)):
        raise ValueError(
            f"d_min must be a positive finite number (not bool), got {d_min!r} "
            f"({type(d_min).__name__})."
        )
    if isinstance(d_min, Decimal):
        if not d_min.is_finite():
            raise ValueError(f"d_min must be finite, got {d_min!r}.")
        f_val = float(d_min)
        if not math.isfinite(f_val) or Decimal(str(f_val)) != d_min:
            raise ValueError(
                f"d_min Decimal {d_min!r} cannot round-trip losslessly through JSON float."
            )
        dec_val = d_min
    else:
        f_val = float(d_min)
        if not math.isfinite(f_val):
            raise ValueError(f"d_min must be finite, got {d_min!r}.")
        try:
            dec_val = Decimal(str(f_val))
        except InvalidOperation as exc:
            raise ValueError(f"Invalid numeric d_min {d_min!r}.") from exc

    if dec_val <= Decimal("0"):
        raise ValueError(f"d_min must be strictly positive (> 0), got {d_min!r}.")

    if dec_val < Decimal("1.10"):
        tier_id = "T1"
    elif dec_val < SITES_SHAKE_D_MIN_THRESHOLD:
        tier_id = "T2"
    elif dec_val < Decimal("2.80"):
        tier_id = "T3"
    else:
        tier_id = "T4"
    return f_val, dec_val, tier_id


def _normalize_strict_json_value(value: Any, *, field_name: str) -> Any:
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(
                f"{field_name} contains non-finite float {value!r}."
            )
        return value
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if not isinstance(k, str) or not k.strip():
                raise ValueError(
                    f"{field_name} mapping keys must be non-empty strings, got {k!r}."
                )
            out[k] = _normalize_strict_json_value(
                v, field_name=f"{field_name}.{k}"
            )
        return out
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
    """Serialize a strict JSON mapping deterministically to UTF-8 bytes."""
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


def track2_seed_digest(anon_target_id: str) -> str:
    """Compute the U05 deterministic Track (ii) HMAC-SHA256 seed digest.

    Computes ``hmac.new(b"protstruct-track2-v1", anon_target_id.encode("utf-8"), hashlib.sha256).hexdigest()``.
    Returns the full 64-character lowercase hex digest without converting it into an
    unapproved PRNG integer or state. Syntax validation of ``anon_target_id`` does not
    prove runtime target anonymization, and the public HMAC key provides determinism
    rather than secrecy.
    """
    validated_id = _validate_anon_target_id(anon_target_id)
    return hmac.new(
        TRACK2_HMAC_KEY_BYTES,
        validated_id.encode(TRACK2_MESSAGE_ENCODING),
        hashlib.sha256,
    ).hexdigest()


def _verify_approved_source_pin(
    *,
    source_path: str | None,
    source_sha256: str | None,
) -> dict[str, Any]:
    resolved_rel_path = (
        APPROVED_SOURCE_PATH if source_path is None else source_path
    )
    if (
        not isinstance(resolved_rel_path, str)
        or resolved_rel_path != APPROVED_SOURCE_PATH
    ):
        raise ValueError(
            f"source_path must be the exact approved U05 policy document "
            f"{APPROVED_SOURCE_PATH!r}, got {source_path!r}."
        )

    resolved_sha = (
        APPROVED_SOURCE_SHA256
        if source_sha256 is None
        else _validate_sha256_strict(
            source_sha256, field_name="source_sha256"
        )
    )
    if resolved_sha != APPROVED_SOURCE_SHA256:
        raise ValueError(
            f"source_sha256 ({resolved_sha}) does not match the approved U05 policy "
            f"document SHA-256 ({APPROVED_SOURCE_SHA256}); callers cannot substitute "
            "an unapproved source digest."
        )

    full_path = REPO_ROOT / APPROVED_SOURCE_PATH
    if not full_path.is_file():
        raise ValueError(
            f"Approved U05 policy source file is missing at {APPROVED_SOURCE_PATH!r}."
        )
    actual_sha = hashlib.sha256(full_path.read_bytes()).hexdigest()
    if actual_sha != APPROVED_SOURCE_SHA256:
        raise ValueError(
            f"Approved U05 policy source file {APPROVED_SOURCE_PATH!r} SHA-256 "
            f"({actual_sha}) does not match pinned {APPROVED_SOURCE_SHA256}."
        )

    return {
        "path": APPROVED_SOURCE_PATH,
        "section": APPROVED_SOURCE_SECTION,
        "sha256": APPROVED_SOURCE_SHA256,
        "source_bytes_verified": True,
    }


def build_perturbation_spec(
    anon_target_id: str,
    parent_model_sha256: str,
    d_min: float | int | Decimal,
    *,
    track: str = TRACK2_ID,
    source_path: str | None = None,
    source_sha256: str | None = None,
) -> dict[str, Any]:
    """Compile a deterministic, result-free U05 Track (ii) perturbation specification record.

    Enforces:
    - Track (ii) (``track="perturbation_recovery"``) isolation; rejects Track (i)
      (``clean_null_stability``), Track (iii) (``parameter_sensitivity``), or any unknown track.
    - Deterministic seed digest via :func:`track2_seed_digest` with explicit UTF-8 and
      HMAC-SHA256 provenance fields.
    - Mandatory full-file byte verification of the approved U05 policy document.
    - Exact 5-step U05 operator sequence with resolution-dependent ``sites.shake``
      (``0.25 Å`` for ``d_min < 1.50 Å``; ``0.35 Å`` for ``d_min >= 1.50 Å``).
    - Explicit unresolved execution requirements and fixed non-executable status flags
      (``executable=False``, ``execution_authorized=False``, ``frozen_result_free=False``,
      ``executed=False``).
    """
    if not isinstance(track, str) or track != TRACK2_ID:
        raise ValueError(
            f"track must be {TRACK2_ID!r} (Track (ii) perturbation-recovery only; "
            f"never pooled with {UNPOOLED_OTHER_TRACKS}), got {track!r}."
        )

    validated_id = _validate_anon_target_id(anon_target_id)
    validated_parent_sha = _validate_sha256_strict(
        parent_model_sha256, field_name="parent_model_sha256"
    )
    d_min_float, d_min_dec, tier_id = _validate_d_min(d_min)
    approved_source = _verify_approved_source_pin(
        source_path=source_path,
        source_sha256=source_sha256,
    )

    seed_hex = track2_seed_digest(validated_id)
    msg_utf8_bytes = validated_id.encode(TRACK2_MESSAGE_ENCODING)

    is_high_res_shake = d_min_dec < SITES_SHAKE_D_MIN_THRESHOLD
    shake_amplitude = (
        SITES_SHAKE_HIGH_RES_ANGSTROM
        if is_high_res_shake
        else SITES_SHAKE_LOW_RES_ANGSTROM
    )
    shake_regime = "d_min_lt_1.50" if is_high_res_shake else "d_min_ge_1.50"

    operations: list[dict[str, Any]] = [
        {
            "step_index": 1,
            "operation_id": "strip_crystallographic_waters",
            "action": "strip_residues",
            "residue_names": ["HOH", "DOD"],
            "description": "Strip all crystallographic waters (HOH / DOD).",
        },
        {
            "step_index": 2,
            "operation_id": "strip_anisou_convert_isotropic",
            "action": "strip_anisou_and_ensure_isotropic_adp",
            "records_stripped": ["ANISOU"],
            "target_adp_mode": "isotropic",
            "description": (
                "Strip all ANISOU records (converting atoms to isotropic B-factors)."
            ),
        },
        {
            "step_index": 3,
            "operation_id": "lognormal_isotropic_b_factor_jitter",
            "action": "lognormal_b_factor_jitter",
            "distribution": "lognormal",
            "nominal_fractional_jitter_percent": B_FACTOR_JITTER_PERCENT,
            "nominal_fractional_jitter": B_FACTOR_JITTER_FRACTION,
            "clamp_min_b_iso": B_FACTOR_CLAMP_MIN_A2,
            "clamp_max_b_iso": B_FACTOR_CLAMP_MAX_A2,
            "unit": "angstrom_squared",
            "description": (
                "Apply +/-20% log-normal isotropic B-factor jitter clamped to [5, 150] A^2."
            ),
        },
        {
            "step_index": 4,
            "operation_id": "coordinate_sites_shake",
            "action": "sites.shake",
            "parameter_path": "sites.shake",
            "parameter_value": shake_amplitude,
            "unit": "angstrom",
            "d_min_threshold_angstrom": 1.5,
            "regime": shake_regime,
            "description": (
                f"Apply coordinate perturbation sites.shake = {shake_amplitude:.2f} A "
                f"({'d_min < 1.50 A' if is_high_res_shake else 'd_min >= 1.50 A'})."
            ),
        },
        {
            "step_index": 5,
            "operation_id": "surface_and_pocket_chi1_chi2_torsion_noise",
            "action": "chi1_chi2_torsion_noise",
            "torsion_angles": ["chi1", "chi2"],
            "rms_perturbation": TORSION_NOISE_RMS_DEGREES,
            "unit": "degrees",
            "subset_fraction": TORSION_NOISE_SUBSET_FRACTION,
            "subset_percent": TORSION_NOISE_SUBSET_PERCENT,
            "eligible_classes": [
                "surface_sidechains",
                "binding_pocket_sidechains",
            ],
            "description": (
                "Apply 15 deg RMS chi1/chi2 torsion noise on 10% of surface and "
                "binding-pocket sidechains."
            ),
        },
    ]

    seed_derivation = {
        "algorithm": TRACK2_HMAC_ALGORITHM,
        "domain_key_utf8": TRACK2_HMAC_KEY_UTF8,
        "key_secrecy_claim": "public_deterministic_domain_separator_not_secret",
        "message_field": "anon_target_id",
        "message_encoding": TRACK2_MESSAGE_ENCODING,
        "message_utf8_hex": msg_utf8_bytes.hex(),
        "seed_digest_hex": seed_hex,
        "prng_seed_conversion_status": "unresolved_pending_stage2_executable_freeze",
    }

    unresolved_list = [dict(item) for item in UNRESOLVED_EXECUTION_REQUIREMENTS]

    canonical_payload: dict[str, Any] = {
        "schema": "phenix_stage2_u05_perturbation_spec_v1",
        "track": TRACK2_ID,
        "track_number": TRACK2_NUMBER,
        "unpooled_from_tracks": list(UNPOOLED_OTHER_TRACKS),
        "pooling_forbidden": True,
        "anon_target_id": validated_id,
        "anonymization_verification_status": (
            "syntax_validated_only_not_runtime_anonymization_proof"
        ),
        "parent_model_sha256": validated_parent_sha,
        "d_min": d_min_float,
        "d_min_decimal": str(d_min_dec),
        "resolution_tier": tier_id,
        "seed_digest": seed_hex,
        "seed_derivation": seed_derivation,
        "approved_source": approved_source,
        "operations": operations,
        "unresolved_execution_requirements": unresolved_list,
        "registration_status": REGISTRATION_STATUS,
        "stage2_status": STAGE2_PERTURBATION_STATUS,
        "executable": False,
        "execution_authorized": False,
        "frozen_result_free": False,
        "executed": False,
    }
    spec_sha256 = canonical_json_sha256(canonical_payload)

    return {
        **canonical_payload,
        "spec_sha256": spec_sha256,
        "epistemic_note": (
            "Result-free U05 specification only; binds approved policy source, parent "
            "model SHA-256, HMAC-SHA256 seed digest, and 5-step operator order, while "
            "retaining explicit unresolved execution requirements. Does not generate "
            "coordinates or authorize execution."
        ),
    }


def require_executable_perturbation_spec(spec: Mapping[str, Any]) -> None:
    """Fail-closed guard for callers requiring a concrete executable perturbation recipe.

    Always rejects result-free U05 perturbation specifications (including tampered copies
    that attempt to set ``executable=True``, ``execution_authorized=True``,
    ``frozen_result_free=True``, or clear ``unresolved_execution_requirements``) because
    concrete coordinate-generation conventions are unresolved in Stage 1 policy selection.
    """
    if not isinstance(spec, Mapping):
        raise ValueError(
            f"perturbation spec must be a mapping, got {type(spec).__name__}."
        )
    canonical_unresolved_ids = [
        item["requirement_id"] for item in UNRESOLVED_EXECUTION_REQUIREMENTS
    ]
    raise ValueError(
        "U05 perturbation specification is a result-free Stage 2 policy contract "
        f"(registration_status={REGISTRATION_STATUS!r}, executable=False, "
        "execution_authorized=False) and cannot be executed to generate coordinates; "
        f"mandatory execution requirements remain unresolved: {canonical_unresolved_ids}."
    )


__all__ = [
    "APPROVED_SOURCE_PATH",
    "APPROVED_SOURCE_SECTION",
    "APPROVED_SOURCE_SHA256",
    "B_FACTOR_CLAMP_MAX_A2",
    "B_FACTOR_CLAMP_MIN_A2",
    "B_FACTOR_JITTER_FRACTION",
    "B_FACTOR_JITTER_PERCENT",
    "EXECUTABLE_SPEC",
    "EXECUTION_AUTHORIZED",
    "FROZEN_RESULT_FREE",
    "REGISTRATION_STATUS",
    "SITES_SHAKE_D_MIN_THRESHOLD",
    "SITES_SHAKE_HIGH_RES_ANGSTROM",
    "SITES_SHAKE_LOW_RES_ANGSTROM",
    "STAGE2_PERTURBATION_STATUS",
    "TORSION_NOISE_RMS_DEGREES",
    "TORSION_NOISE_SUBSET_FRACTION",
    "TORSION_NOISE_SUBSET_PERCENT",
    "TRACK2_HMAC_ALGORITHM",
    "TRACK2_HMAC_KEY_BYTES",
    "TRACK2_HMAC_KEY_UTF8",
    "TRACK2_ID",
    "TRACK2_MESSAGE_ENCODING",
    "TRACK2_NUMBER",
    "UNPOOLED_OTHER_TRACKS",
    "UNRESOLVED_EXECUTION_REQUIREMENTS",
    "build_perturbation_spec",
    "canonical_json_bytes",
    "canonical_json_sha256",
    "require_executable_perturbation_spec",
    "track2_seed_digest",
]
