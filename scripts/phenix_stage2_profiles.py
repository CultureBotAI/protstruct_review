#!/usr/bin/env python3
"""Result-free Stage 2 PHENIX profile, factorial, pure-H, and sensitivity specs (U04).

This module encodes the user-approved Step 1 scientific policy selections for U04
(ref/research/phenix_step1_user_selections_2026-11-15.md) and the static PHENIX
2.0-5936 source witness facts (ref/research/phenix_resolution_profile_decisions_2026-11-09.md)
as pure, deterministic Python 3.12 data structures and PHIL renderers.

Epistemic boundary:
- Registration status remains ``selected_decisions_recorded`` (NOT ``frozen_result_free``).
- Profiles and cell schedules returned here are prospective Stage 2 specifications;
  they have NOT been tuned or frozen on the 23-structure development set and do NOT
  authorize any refinement trial, canary run, or native binary execution.
- Unresolved Stage 2 freeze bindings (exact atom/TLS selection strings, water ADP
  mode below 0.90 A, Tier 4 isotropic-vs-group ADP and weight-optimization policy,
  and tier-specific ADP/TLS factorial levels) are preserved as explicit required
  bindings rather than silently inferred. Tier 4 low-resolution restraint PHIL
  switches are locked from ref/research/data/phenix_stage2_static_phil_witness_2026-11-16.json
  (effective native NCS/restraint construction remains unassessed prior to runtime).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import copy
import json
import math
from pathlib import Path
import re
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

REGISTRATION_STATUS = "selected_decisions_recorded"
STAGE2_SPEC_STATUS = "prospective_spec_not_development_frozen"
DORMANT_TLS_ADP_GUARD_ANCHOR = (
    "PHENIX_PREFIX/lib/python3.9/site-packages/phenix/refinement/fsr/preprocess.py:483-508"
)

TIER_CUTOFF_T1_T2 = 1.10
TIER_CUTOFF_T2_T3 = 1.50
TIER_CUTOFF_T3_T4 = 2.80
WATER_SUB_0P90_CUTOFF = 0.90
S1_MIN_D_MIN = 1.50
S1_MAX_D_MIN = 1.70

CDL_PHIL_PATH = "refinement.pdb_interpretation.restraints_library.cdl"
MACRO_CYCLES_PHIL_PATH = "refinement.main.number_of_macro_cycles"
ORDERED_SOLVENT_PHIL_PATH = "refinement.main.ordered_solvent"
SWITCH_ISO_LIMIT_PHIL_PATH = "refinement.main.switch_to_isotropic_high_res_limit"
HYDROGENS_REFINE_PHIL_PATH = "refinement.hydrogens.refine"
OPT_XYZ_WEIGHT_PHIL_PATH = "refinement.target_weights.optimize_xyz_weight"
OPT_ADP_WEIGHT_PHIL_PATH = "refinement.target_weights.optimize_adp_weight"
FORCE_OPT_WEIGHTS_PHIL_PATH = "refinement.target_weights.force_optimize_weights"
C_BETA_RESTRAINTS_PHIL_PATH = "refinement.pdb_interpretation.c_beta_restraints"
NONBONDED_WEIGHT_PHIL_PATH = "refinement.pdb_interpretation.nonbonded_weight"
TORSION_NCS_SEARCH_ENABLED_PHIL_PATH = "refinement.pdb_interpretation.ncs_search.enabled"
NCS_TYPE_PHIL_PATH = "refinement.ncs.type"
SECONDARY_STRUCTURE_ENABLED_PHIL_PATH = (
    "refinement.pdb_interpretation.secondary_structure.enabled"
)
ROTAMER_RESTRAINTS_PHIL_PATH = "refinement.main.rotamer_restraints"
ADP_ANISO_SELECTION_PHIL_PATH = "refinement.refine.adp.individual.anisotropic"
ADP_ISO_SELECTION_PHIL_PATH = "refinement.refine.adp.individual.isotropic"
ADP_GROUP_SELECTION_PHIL_PATH = "refinement.refine.adp.group"
ADP_GROUP_MODE_PHIL_PATH = "refinement.refine.adp.group_adp_refinement_mode"
TLS_SELECTION_PHIL_PATH = "refinement.refine.adp.tls"
REFINE_STRATEGY_PHIL_PATH = "refinement.refine.strategy"

READY_SET_HYDROGENS_PHIL_PATH = "ready_set.actions.hydrogens"
READY_SET_LIGANDS_PHIL_PATH = "ready_set.actions.ligands"
READY_SET_CIF_FILE_NAME_PHIL_PATH = "ready_set.input.cif_file_name"
REFINE_MONOMER_CIF_PHIL_PATH = "refinement.input.monomers.file_name"

SOURCE_ANCHORS: dict[str, str] = {
    "master_init_params": (
        "PHENIX_PREFIX/lib/python3.9/site-packages/phenix/refinement/__init__.params:"
        "1-3,111-119,316-337,350-358,470-480,668-674"
    ),
    "preprocess": (
        "PHENIX_PREFIX/lib/python3.9/site-packages/phenix/refinement/fsr/preprocess.py:"
        "162-177,348-417,483-513,663-680,730-736,837-840"
    ),
    "task_table_run_sol": (
        "PHENIX_PREFIX/lib/python3.9/site-packages/phenix/refinement/task_table.py:63-83,115-124"
    ),
    "xyz_weight_skip_predicate": (
        "PHENIX_PREFIX/lib/python3.9/site-packages/phenix/refinement/xyz_reciprocal_space.py:"
        "274-288,385-400,452-487"
    ),
    "adp_weight_branch_3p0": (
        "PHENIX_PREFIX/lib/python3.9/site-packages/mmtbx/refinement/adp_refinement.py:"
        "276-301,325-330"
    ),
    "weights_special_case": (
        "PHENIX_PREFIX/lib/python3.9/site-packages/mmtbx/refinement/weights.py:"
        "10-22,320-334,353-375,421-426"
    ),
    "weights_params_bins": (
        "PHENIX_PREFIX/lib/python3.9/site-packages/mmtbx/refinement/weights_params.py:1-104"
    ),
    "ordered_solvent_defaults": (
        "PHENIX_PREFIX/lib/python3.9/site-packages/mmtbx/solvent/ordered_solvent.py:101-106"
    ),
    "cdl_master_params": (
        "PHENIX_PREFIX/lib/python3.9/site-packages/mmtbx/monomer_library/pdb_interpretation.py:"
        "151-160,227,578"
    ),
    "ready_set_defaults": (
        "PHENIX_PREFIX/lib/python3.9/site-packages/elbow/programs/ready_set_params.py:"
        "31-38,79-101"
    ),
    "faq_refine": (
        "PHENIX_PREFIX/lib/python3.9/site-packages/phenix_html/rst_files/faqs/refine.txt:"
        "185-188,356-361,425-448,460-478"
    ),
    "static_phil_witness_2026_11_16": (
        "ref/research/data/phenix_stage2_static_phil_witness_2026-11-16.json"
    ),
}

ALLOWED_STRATEGIES: frozenset[str] = frozenset(
    {
        "individual_sites",
        "individual_sites_real_space",
        "rigid_body",
        "individual_adp",
        "group_adp",
        "tls",
        "occupancies",
        "group_anomalous",
    }
)
ADP_TLS_STRATEGY_TOKENS: frozenset[str] = frozenset(
    {"individual_adp", "group_adp", "tls"}
)
ALLOWED_COMMON_NON_ADP_STRATEGIES: frozenset[str] = (
    ALLOWED_STRATEGIES - ADP_TLS_STRATEGY_TOKENS
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_UNSAFE_TEXT_CHARS = frozenset({"\n", "\r", "\x00", ";", "{", "}", "#", "`", "$"})
_UNSAFE_PATH_CHARS = frozenset({"\n", "\r", "\x00", ";", "|", "&", "$", "`", "{", "}", "#", " "})
_FORBIDDEN_SYMBOLIC_SELECTORS = frozenset(
    {
        "unresolved",
        "tbd",
        "todo",
        "placeholder",
        "<unresolved>",
        "auto",
        "auto_from_tier",
        "default",
        "none",
        "null",
        "macromol_heavy_aniso",
        "water_iso",
        "iso+tls",
        "iso/group+tls",
        "t1_adp_tls_level_a_unresolved",
        "t1_adp_tls_level_b_unresolved",
        "t2_adp_tls_level_a_unresolved",
        "t2_adp_tls_level_b_unresolved",
        "t3_adp_tls_level_a_unresolved",
        "t3_adp_tls_level_b_unresolved",
        "t4_adp_tls_level_a_unresolved",
        "t4_adp_tls_level_b_unresolved",
    }
)

_ARM_ALIASES: dict[str, tuple[str, str]] = {
    "arm 3b-refine-only": ("Arm 3b-refine-only", "arm3b-refine-only"),
    "arm3b-refine-only": ("Arm 3b-refine-only", "arm3b-refine-only"),
    "3b-refine-only": ("Arm 3b-refine-only", "arm3b-refine-only"),
    "arm_3b_refine_only": ("Arm 3b-refine-only", "arm3b-refine-only"),
    "arm3b_refine_only": ("Arm 3b-refine-only", "arm3b-refine-only"),
    "arm 3b-plus-readyset": ("Arm 3b-plus-readyset", "arm3b-plus-readyset"),
    "arm3b-plus-readyset": ("Arm 3b-plus-readyset", "arm3b-plus-readyset"),
    "3b-plus-readyset": ("Arm 3b-plus-readyset", "arm3b-plus-readyset"),
    "arm_3b_plus_readyset": ("Arm 3b-plus-readyset", "arm3b-plus-readyset"),
    "arm3b_plus_readyset": ("Arm 3b-plus-readyset", "arm3b-plus-readyset"),
}


class ResolutionTier(str):
    """String-compatible resolution tier identifier ('T1'..'T4') with structured metadata."""

    tier_id: str
    tier_number: int
    tier_name: str
    label: str
    d_min: float
    interval: str
    lower_bound_angstrom: float
    upper_bound_angstrom: float | None
    lower_inclusive: bool
    upper_exclusive: bool
    c_beta_forced_false_by_native_preprocess: bool
    unrequested_aniso_demoted_by_native_preprocess: bool
    ordered_solvent_native_eligible: bool
    sub_0p90_water_adp_unresolved: bool

    def __new__(
        cls,
        tier_id: str,
        *,
        tier_number: int,
        tier_name: str,
        label: str,
        d_min: float,
        interval: str,
        lower_bound_angstrom: float,
        upper_bound_angstrom: float | None,
        lower_inclusive: bool,
        upper_exclusive: bool,
        c_beta_forced_false_by_native_preprocess: bool,
        unrequested_aniso_demoted_by_native_preprocess: bool,
        ordered_solvent_native_eligible: bool,
        sub_0p90_water_adp_unresolved: bool,
    ) -> ResolutionTier:
        obj = super().__new__(cls, tier_id)
        obj.tier_id = tier_id
        obj.tier_number = tier_number
        obj.tier_name = tier_name
        obj.label = label
        obj.d_min = d_min
        obj.interval = interval
        obj.lower_bound_angstrom = lower_bound_angstrom
        obj.upper_bound_angstrom = upper_bound_angstrom
        obj.lower_inclusive = lower_inclusive
        obj.upper_exclusive = upper_exclusive
        obj.c_beta_forced_false_by_native_preprocess = (
            c_beta_forced_false_by_native_preprocess
        )
        obj.unrequested_aniso_demoted_by_native_preprocess = (
            unrequested_aniso_demoted_by_native_preprocess
        )
        obj.ordered_solvent_native_eligible = ordered_solvent_native_eligible
        obj.sub_0p90_water_adp_unresolved = sub_0p90_water_adp_unresolved
        return obj

    def _constructor_kwargs(self) -> dict[str, Any]:
        return {
            "tier_number": self.tier_number,
            "tier_name": self.tier_name,
            "label": self.label,
            "d_min": self.d_min,
            "interval": self.interval,
            "lower_bound_angstrom": self.lower_bound_angstrom,
            "upper_bound_angstrom": self.upper_bound_angstrom,
            "lower_inclusive": self.lower_inclusive,
            "upper_exclusive": self.upper_exclusive,
            "c_beta_forced_false_by_native_preprocess": (
                self.c_beta_forced_false_by_native_preprocess
            ),
            "unrequested_aniso_demoted_by_native_preprocess": (
                self.unrequested_aniso_demoted_by_native_preprocess
            ),
            "ordered_solvent_native_eligible": self.ordered_solvent_native_eligible,
            "sub_0p90_water_adp_unresolved": self.sub_0p90_water_adp_unresolved,
        }

    def __getnewargs_ex__(self) -> tuple[tuple[str], dict[str, Any]]:
        return ((str(self),), self._constructor_kwargs())

    def __copy__(self) -> ResolutionTier:
        return type(self)(str(self), **self._constructor_kwargs())

    def __deepcopy__(self, memo: dict[int, Any]) -> ResolutionTier:
        copied_kwargs = {
            k: copy.deepcopy(v, memo) for k, v in self._constructor_kwargs().items()
        }
        dup = type(self)(copy.deepcopy(str(self), memo), **copied_kwargs)
        memo[id(self)] = dup
        return dup

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier_id": self.tier_id,
            **self._constructor_kwargs(),
        }

    def __getitem__(self, key: int | slice | str) -> Any:
        if isinstance(key, str):
            data = self.to_dict()
            if key in data:
                return data[key]
            raise KeyError(key)
        return super().__getitem__(key)


class RenderedEffBundle(str):
    """Deterministic rendered PHIL text with separated ``ready_set`` and ``refine`` scopes."""

    refine_eff: str
    ready_set_eff: str | None
    is_complete: bool
    single_cell_binding_complete: bool
    comparison_one_factor_verified: bool
    registration_status: str
    stage2_status: str
    scopes: dict[str, str | None]

    def __new__(
        cls,
        combined_text: str,
        *,
        refine_eff: str,
        ready_set_eff: str | None,
        is_complete: bool,
        comparison_one_factor_verified: bool = False,
    ) -> RenderedEffBundle:
        obj = super().__new__(cls, combined_text)
        obj.refine_eff = refine_eff
        obj.ready_set_eff = ready_set_eff
        obj.is_complete = is_complete
        obj.single_cell_binding_complete = is_complete
        obj.comparison_one_factor_verified = bool(comparison_one_factor_verified)
        obj.registration_status = REGISTRATION_STATUS
        obj.stage2_status = STAGE2_SPEC_STATUS
        obj.scopes = {
            "ready_set": ready_set_eff,
            "refine": refine_eff,
        }
        return obj

    def _constructor_kwargs(self) -> dict[str, Any]:
        return {
            "refine_eff": self.refine_eff,
            "ready_set_eff": self.ready_set_eff,
            "is_complete": self.is_complete,
            "comparison_one_factor_verified": self.comparison_one_factor_verified,
        }

    def __getnewargs_ex__(self) -> tuple[tuple[str], dict[str, Any]]:
        return ((str(self),), self._constructor_kwargs())

    def __copy__(self) -> RenderedEffBundle:
        return type(self)(str(self), **self._constructor_kwargs())

    def __deepcopy__(self, memo: dict[int, Any]) -> RenderedEffBundle:
        copied_kwargs = {
            k: copy.deepcopy(v, memo) for k, v in self._constructor_kwargs().items()
        }
        dup = type(self)(copy.deepcopy(str(self), memo), **copied_kwargs)
        memo[id(self)] = dup
        return dup

    def to_dict(self) -> dict[str, Any]:
        return {
            "combined_eff": str(self),
            "refine_eff": self.refine_eff,
            "ready_set_eff": self.ready_set_eff,
            "scopes": dict(self.scopes),
            "is_complete": self.is_complete,
            "single_cell_binding_complete": self.single_cell_binding_complete,
            "comparison_one_factor_verified": self.comparison_one_factor_verified,
            "registration_status": self.registration_status,
            "stage2_status": self.stage2_status,
        }

    def __getitem__(self, key: int | slice | str) -> Any:
        if isinstance(key, str):
            data = self.to_dict()
            if key in data:
                return data[key]
            raise KeyError(key)
        return super().__getitem__(key)


def _validate_d_min(d_min: Any) -> float:
    if isinstance(d_min, bool) or not isinstance(d_min, (int, float)):
        raise ValueError(
            f"d_min must be a finite positive real number (int or float), not {type(d_min).__name__}."
        )
    value = float(d_min)
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"d_min must be finite and strictly positive, got {d_min!r}.")
    return value


def _normalize_arm(arm: Any) -> tuple[str, str]:
    if not isinstance(arm, str):
        raise ValueError(f"arm must be a string, got {type(arm).__name__}.")
    cleaned = " ".join(arm.strip().lower().split())
    if cleaned not in _ARM_ALIASES:
        raise ValueError(
            f"Unsupported arm {arm!r}; expected 'Arm 3b-refine-only' or 'Arm 3b-plus-readyset'."
        )
    return _ARM_ALIASES[cleaned]


def _validate_portable_relpath(path_value: Any, *, suffix: str | None = None) -> str:
    if not isinstance(path_value, str):
        raise ValueError(f"Path must be a string, got {type(path_value).__name__}.")
    if not path_value or path_value != path_value.strip():
        raise ValueError("Path must be a non-empty, stripped relative path string.")
    if any(ch in _UNSAFE_PATH_CHARS for ch in path_value):
        raise ValueError(f"Path {path_value!r} contains unsafe or whitespace characters.")
    if "\\" in path_value or _WINDOWS_DRIVE_RE.match(path_value):
        raise ValueError(f"Path {path_value!r} must use portable POSIX relative syntax.")
    if path_value.startswith("/") or path_value.startswith("~"):
        raise ValueError(f"Absolute or home-relative path {path_value!r} is forbidden.")
    parts = path_value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"Path {path_value!r} must not contain empty, '.', or '..' segments.")
    if parts[0].lower() in {"users", "home", "private", "var", "tmp", "etc"}:
        raise ValueError(f"Host-like path prefix in {path_value!r} is forbidden.")
    if suffix is not None and not path_value.endswith(suffix):
        raise ValueError(f"Path {path_value!r} must end with {suffix!r}.")
    return path_value


def _validate_sha256(digest: Any, *, field_name: str = "sha256") -> str:
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or _SHA256_RE.fullmatch(digest) is None
    ):
        raise ValueError(
            f"{field_name} must be a 64-character lowercase hexadecimal SHA-256 string, got {digest!r}."
        )
    return digest


def _validate_selection_string(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string, got {type(value).__name__}.")
    stripped = value.strip()
    if not stripped or value != stripped:
        raise ValueError(
            f"{field_name} must be a non-empty string without leading/trailing whitespace."
        )
    if any(ch in _UNSAFE_TEXT_CHARS for ch in value) or '"' in value or "\\" in value:
        raise ValueError(
            f"{field_name} contains forbidden line-break, quote, or PHIL-injection characters: {value!r}."
        )
    if stripped.startswith("/") or _WINDOWS_DRIVE_RE.match(stripped):
        raise ValueError(f"{field_name} must not be a filesystem path: {value!r}.")
    normalized = stripped.lower()
    if (
        normalized in _FORBIDDEN_SYMBOLIC_SELECTORS
        or "unresolved" in normalized
        or "placeholder" in normalized
        or "todo" in normalized
        or "tbd" in normalized
    ):
        raise ValueError(
            f"{field_name} cannot use symbolic or unresolved placeholder text {value!r}."
        )
    return value


def _validate_tls_groups(value: Any, *, field_name: str = "tls_group_selections") -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) == 0:
        raise ValueError(f"{field_name} must be a non-empty sequence of selection strings.")
    cleaned: list[str] = []
    for idx, item in enumerate(value):
        sel = _validate_selection_string(item, field_name=f"{field_name}[{idx}]")
        cleaned.append(sel)
    if len(set(cleaned)) != len(cleaned):
        raise ValueError(f"{field_name} contains duplicate TLS group selection strings.")
    return tuple(cleaned)


def _validate_strategy_list(
    value: Any,
    *,
    required_tokens: frozenset[str] = frozenset(),
    forbidden_tokens: frozenset[str] = frozenset(),
) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or len(value) == 0:
        raise ValueError("refine_strategy must be a non-empty sequence of strategy names.")
    tokens: list[str] = []
    for idx, item in enumerate(value):
        if not isinstance(item, str):
            raise ValueError(f"refine_strategy[{idx}] must be a string.")
        tok = item.strip()
        if tok not in ALLOWED_STRATEGIES:
            raise ValueError(
                f"Unsupported strategy token {item!r} in refine_strategy; allowed: {sorted(ALLOWED_STRATEGIES)}."
            )
        if tok not in tokens:
            tokens.append(tok)
    missing = required_tokens - set(tokens)
    if missing:
        raise ValueError(f"refine_strategy is missing required strategy tokens: {sorted(missing)}.")
    disallowed = forbidden_tokens & set(tokens)
    if disallowed:
        raise ValueError(f"refine_strategy includes forbidden strategy tokens: {sorted(disallowed)}.")
    return tuple(tokens)


def resolution_tier(d_min: float | int) -> ResolutionTier:
    """Classify ``d_min`` (Å) into the four U04/#1047 resolution tiers.

    Half-open cutoffs (P1c / U01 / U04):
    - ``T1`` (Tier 1 — Ultra-High): ``0 < d_min < 1.10``
    - ``T2`` (Tier 2 — High):       ``1.10 <= d_min < 1.50``
    - ``T3`` (Tier 3 — Medium):     ``1.50 <= d_min < 2.80``
    - ``T4`` (Tier 4 — Low):        ``d_min >= 2.80``
    """
    val = _validate_d_min(d_min)
    c_beta_forced_false = val <= TIER_CUTOFF_T2_T3
    unrequested_aniso_demoted = val > TIER_CUTOFF_T2_T3
    ordered_solvent_eligible = val < TIER_CUTOFF_T3_T4

    if val < TIER_CUTOFF_T1_T2:
        return ResolutionTier(
            "T1",
            tier_number=1,
            tier_name="Ultra-High",
            label="Tier 1 — Ultra-High (d_min < 1.10 A)",
            d_min=val,
            interval="(0.0, 1.10)",
            lower_bound_angstrom=0.0,
            upper_bound_angstrom=TIER_CUTOFF_T1_T2,
            lower_inclusive=False,
            upper_exclusive=True,
            c_beta_forced_false_by_native_preprocess=c_beta_forced_false,
            unrequested_aniso_demoted_by_native_preprocess=unrequested_aniso_demoted,
            ordered_solvent_native_eligible=ordered_solvent_eligible,
            sub_0p90_water_adp_unresolved=(val < WATER_SUB_0P90_CUTOFF),
        )
    if val < TIER_CUTOFF_T2_T3:
        return ResolutionTier(
            "T2",
            tier_number=2,
            tier_name="High",
            label="Tier 2 — High (1.10 <= d_min < 1.50 A)",
            d_min=val,
            interval="[1.10, 1.50)",
            lower_bound_angstrom=TIER_CUTOFF_T1_T2,
            upper_bound_angstrom=TIER_CUTOFF_T2_T3,
            lower_inclusive=True,
            upper_exclusive=True,
            c_beta_forced_false_by_native_preprocess=c_beta_forced_false,
            unrequested_aniso_demoted_by_native_preprocess=unrequested_aniso_demoted,
            ordered_solvent_native_eligible=ordered_solvent_eligible,
            sub_0p90_water_adp_unresolved=False,
        )
    if val < TIER_CUTOFF_T3_T4:
        return ResolutionTier(
            "T3",
            tier_number=3,
            tier_name="Medium",
            label="Tier 3 — Medium (1.50 <= d_min < 2.80 A)",
            d_min=val,
            interval="[1.50, 2.80)",
            lower_bound_angstrom=TIER_CUTOFF_T2_T3,
            upper_bound_angstrom=TIER_CUTOFF_T3_T4,
            lower_inclusive=True,
            upper_exclusive=True,
            c_beta_forced_false_by_native_preprocess=c_beta_forced_false,
            unrequested_aniso_demoted_by_native_preprocess=unrequested_aniso_demoted,
            ordered_solvent_native_eligible=ordered_solvent_eligible,
            sub_0p90_water_adp_unresolved=False,
        )
    return ResolutionTier(
        "T4",
        tier_number=4,
        tier_name="Low",
        label="Tier 4 — Low (d_min >= 2.80 A)",
        d_min=val,
        interval="[2.80, inf)",
        lower_bound_angstrom=TIER_CUTOFF_T3_T4,
        upper_bound_angstrom=None,
        lower_inclusive=True,
        upper_exclusive=False,
        c_beta_forced_false_by_native_preprocess=c_beta_forced_false,
        unrequested_aniso_demoted_by_native_preprocess=unrequested_aniso_demoted,
        ordered_solvent_native_eligible=ordered_solvent_eligible,
        sub_0p90_water_adp_unresolved=False,
    )


def fixed_profile(d_min: float | int, arm: str) -> dict[str, Any]:
    """Return the U04 Stage 2 prospective fixed-profile contract for ``Arm 3b``.

    Distinguishes ``Arm 3b-refine-only`` (no ``phenix.ready_set`` preprocessing) from
    ``Arm 3b-plus-readyset`` (combined ``hydrogens=True, ligands=True`` preprocessing),
    locks the known U04 PHIL assignments, and lists all unresolved Stage 2 bindings
    that must be supplied before a complete ``.eff`` file can be rendered.
    """
    tier = resolution_tier(d_min)
    arm_id, arm_slug = _normalize_arm(arm)

    if arm_slug == "arm3b-plus-readyset":
        preprocessing = {
            "enabled": True,
            "program": "phenix.ready_set",
            "phil_assignments": {
                READY_SET_HYDROGENS_PHIL_PATH: True,
                READY_SET_LIGANDS_PHIL_PATH: True,
            },
            "source_anchor": SOURCE_ANCHORS["ready_set_defaults"],
            "note": (
                "Arm 3b-plus-readyset runs phenix.ready_set with default combined "
                "hydrogens=True and ligands=True (#1240)."
            ),
        }
    else:
        preprocessing = {
            "enabled": False,
            "program": None,
            "phil_assignments": {},
            "source_anchor": SOURCE_ANCHORS["ready_set_defaults"],
            "note": "Arm 3b-refine-only runs phenix.refine directly without phenix.ready_set.",
        }

    known_refine_phil: dict[str, bool | int | float | str] = {
        MACRO_CYCLES_PHIL_PATH: 5,
        HYDROGENS_REFINE_PHIL_PATH: "riding",
        CDL_PHIL_PATH: True,
    }
    required_bindings: dict[str, str] = {}
    unresolved_notes: list[str] = []

    if tier.tier_id in {"T1", "T2"}:
        known_refine_phil[ORDERED_SOLVENT_PHIL_PATH] = True
        known_refine_phil[OPT_XYZ_WEIGHT_PHIL_PATH] = True
        known_refine_phil[OPT_ADP_WEIGHT_PHIL_PATH] = True
        required_bindings["adp_anisotropic_selection"] = (
            "Exact atom-selection string for refinement.refine.adp.individual.anisotropic "
            "(macromolecular heavy atoms; never inferred from tier name alone)."
        )
        required_bindings["adp_isotropic_selection"] = (
            "Exact atom-selection string for refinement.refine.adp.individual.isotropic "
            "(waters isotropic in [0.90, 1.50) A; below 0.90 A governed by Stage 2 dev test)."
        )
        if tier.sub_0p90_water_adp_unresolved:
            water_adp_policy = "unresolved_dev_test_below_0.90A"
            required_bindings["sub_0p90_water_adp_mode"] = (
                "Stage 2 development-set choice ('isotropic' or 'anisotropic') for water ADPs "
                "at d_min < 0.90 A (U04)."
            )
            required_bindings["sub_0p90_water_selection_audit"] = (
                "Source-bound water-selection audit declaration dict binding "
                "'refinement_input_model_sha256', 'audit_receipt_sha256', "
                "'adp_isotropic_selection', 'adp_anisotropic_selection', and strict "
                "nonnegative integer water-atom routing counts ('total', 'isotropic', "
                "'anisotropic', 'neither', 'both') consistent with sub_0p90_water_adp_mode "
                "(supplied-declaration consistency only; not verified coordinate contents or "
                "native behavior)."
            )
            unresolved_notes.append(
                "At d_min < 0.90 A, water ADP policy (isotropic vs. anisotropic) is explicitly "
                "unresolved until frozen on the 23-structure Stage 2 development set (U04), and "
                "requires an explicit source-bound water-selection audit declaration (#1337)."
            )
        else:
            water_adp_policy = "isotropic_in_0.90_to_1.50A"
        adp_tls_architecture = "macromol_heavy_aniso_waters_iso_0p90_1p50_dev_tested_lt_0p90"
        weight_optimization_policy = "optimize_xyz_and_adp_weights_true"
        low_res_restraints_policy = {
            "torsion_ncs": False,
            "secondary_structure": False,
            "rotamer": False,
        }
    elif tier.tier_id == "T3":
        known_refine_phil[ORDERED_SOLVENT_PHIL_PATH] = True
        known_refine_phil[OPT_XYZ_WEIGHT_PHIL_PATH] = True
        known_refine_phil[OPT_ADP_WEIGHT_PHIL_PATH] = True
        water_adp_policy = "isotropic"
        adp_tls_architecture = "iso+tls"
        weight_optimization_policy = "optimize_xyz_and_adp_weights_true"
        required_bindings["adp_isotropic_selection"] = (
            "Exact atom-selection string for refinement.refine.adp.individual.isotropic."
        )
        required_bindings["tls_group_selections"] = (
            "Non-empty sequence of explicit TLS group atom-selection strings for "
            "refinement.refine.adp.tls."
        )
        required_bindings["refine_strategy"] = (
            "Explicit refinement.refine.strategy token sequence including 'individual_adp' and 'tls'."
        )
        low_res_restraints_policy = {
            "torsion_ncs": False,
            "secondary_structure": False,
            "rotamer": False,
        }
    else:
        known_refine_phil[ORDERED_SOLVENT_PHIL_PATH] = False
        known_refine_phil[TORSION_NCS_SEARCH_ENABLED_PHIL_PATH] = True
        known_refine_phil[NCS_TYPE_PHIL_PATH] = "torsion"
        known_refine_phil[SECONDARY_STRUCTURE_ENABLED_PHIL_PATH] = True
        known_refine_phil[ROTAMER_RESTRAINTS_PHIL_PATH] = True
        water_adp_policy = "ordered_solvent_disabled"
        adp_tls_architecture = "iso/group+tls"
        weight_optimization_policy = "unresolved_in_u04_for_t4_fixed_profile"
        required_bindings["t4_adp_mode"] = (
            "Stage 2 choice between 'isotropic_plus_tls' and 'group_adp_plus_tls' for Tier 4 "
            "('iso/group+tls' in U04)."
        )
        required_bindings["adp_selection"] = (
            "Exact atom-selection string for Tier 4 isotropic or group ADP refinement."
        )
        required_bindings["tls_group_selections"] = (
            "Non-empty sequence of explicit TLS group atom-selection strings for "
            "refinement.refine.adp.tls."
        )
        required_bindings["refine_strategy"] = (
            "Explicit refinement.refine.strategy token sequence matching t4_adp_mode and 'tls'."
        )
        required_bindings["t4_weight_optimization_policy"] = (
            "Explicit Tier 4 weight-optimization dict {'optimize_xyz_weight': bool, "
            "'optimize_adp_weight': bool, 'force_optimize_weights': bool}; U04 does not "
            "specify optimize_xyz/adp_weight for the Tier 4 fixed profile."
        )
        unresolved_notes.append(
            "Tier 4 fixed profile requires explicit Stage 2 bindings for iso-vs-group ADP mode, "
            "TLS group selections, and weight-optimization policy; low-resolution restraint "
            "PHIL switches are locked from ref/research/data/phenix_stage2_static_phil_witness_2026-11-16.json "
            "(effective native NCS/restraint construction remains unassessed)."
        )
        low_res_restraints_policy = {
            "torsion_ncs": True,
            "secondary_structure": True,
            "rotamer": True,
        }

    return {
        "kind": "fixed_profile",
        "registration_status": REGISTRATION_STATUS,
        "stage2_status": STAGE2_SPEC_STATUS,
        "development_frozen": False,
        "arm_id": arm_id,
        "arm_slug": arm_slug,
        "d_min": tier.d_min,
        "tier": tier,
        "tier_id": tier.tier_id,
        "macro_cycles": 5,
        "hydrogens_refine": "riding",
        "cdl_phil_path": CDL_PHIL_PATH,
        "cdl_enabled": True,
        "ordered_solvent": known_refine_phil[ORDERED_SOLVENT_PHIL_PATH],
        "adp_tls_architecture": adp_tls_architecture,
        "water_adp_policy": water_adp_policy,
        "weight_optimization_policy": weight_optimization_policy,
        "low_res_restraints_policy": low_res_restraints_policy,
        "preprocessing": preprocessing,
        "known_refine_phil": known_refine_phil,
        "required_bindings": required_bindings,
        "unresolved_notes": unresolved_notes,
        "dormant_source_block_untouched": DORMANT_TLS_ADP_GUARD_ANCHOR,
        "source_anchors": dict(SOURCE_ANCHORS),
    }


def _validate_hd_common_start_and_receipt(
    start_model_sha256: Any,
    hd_audit_receipt: Any,
) -> dict[str, Any]:
    """Validate declared common starting-model SHA-256 and H/D audit receipt contract.

    Validates the supplied receipt contract only (receipt SHA-256, subject model SHA-256
    matching ``hd_free_start_model_sha256``, and strict integer ``hd_atom_count == 0``),
    without inspecting coordinate files or claiming runtime verification.
    """
    start_sha = _validate_sha256(
        start_model_sha256,
        field_name="hd_free_start_model_sha256",
    )
    if not isinstance(hd_audit_receipt, Mapping):
        raise ValueError(
            "hd_audit_receipt must be a mapping with keys "
            "{'receipt_sha256', 'subject_model_sha256', 'hd_atom_count'}."
        )
    required_receipt_keys = {"receipt_sha256", "subject_model_sha256", "hd_atom_count"}
    actual_keys = set(hd_audit_receipt.keys())
    if actual_keys != required_receipt_keys:
        raise ValueError(
            f"hd_audit_receipt must have exact keys {sorted(required_receipt_keys)}, "
            f"got {sorted(actual_keys)}."
        )
    receipt_sha = _validate_sha256(
        hd_audit_receipt["receipt_sha256"],
        field_name="hd_audit_receipt.receipt_sha256",
    )
    subject_sha = _validate_sha256(
        hd_audit_receipt["subject_model_sha256"],
        field_name="hd_audit_receipt.subject_model_sha256",
    )
    if subject_sha != start_sha:
        raise ValueError(
            "hd_audit_receipt['subject_model_sha256'] must equal hd_free_start_model_sha256: "
            f"{subject_sha!r} != {start_sha!r}."
        )
    hd_count = hd_audit_receipt["hd_atom_count"]
    if isinstance(hd_count, bool) or not isinstance(hd_count, int) or hd_count != 0:
        raise ValueError(
            "hd_audit_receipt['hd_atom_count'] must be strict integer 0 "
            f"(not bool/nonzero/unknown), got {hd_count!r}."
        )
    return {
        "hd_free_start_model_sha256": start_sha,
        "receipt_sha256": receipt_sha,
        "subject_model_sha256": subject_sha,
        "hd_atom_count": 0,
    }


def pure_h_contract(
    shared_ligand_cifs: Sequence[Mapping[str, Any] | tuple[str, str]],
    *,
    hd_free_start_model_sha256: Any = None,
    hd_audit_receipt: Any = None,
) -> dict[str, Any]:
    """Validate and return the U04/#1240/#1334 pure-hydrogen factorial isolation contract.

    Enforces:
    - Unique, portable relative ``.cif`` paths + 64-hex lowercase SHA-256 digests.
    - Exact same frozen ligand CIF tuple pinned on both ``H_off`` and ``H_riding``.
    - ``H_riding`` runs ``phenix.ready_set`` with ``ready_set.actions.hydrogens=True``
      and ``ready_set.actions.ligands=False`` (#1240).
    - Both ``H_off`` and ``H_riding`` require the identical declared ``H``/``D``-free
      common starting coordinate model digest and declared H/D audit receipt binding
      (because ``phenix.refine`` does not strip input H/D atoms per
      ``preprocess.py:348-372``, and a bare hash alone does not prove H/D absence).
    """
    declared_common_start: dict[str, Any] | None = None
    if hd_free_start_model_sha256 is not None or hd_audit_receipt is not None:
        declared_common_start = _validate_hd_common_start_and_receipt(
            hd_free_start_model_sha256,
            hd_audit_receipt,
        )
    if isinstance(shared_ligand_cifs, (str, bytes, Mapping)) or not isinstance(
        shared_ligand_cifs, Sequence
    ):
        raise ValueError(
            "shared_ligand_cifs must be a sequence of {'path', 'sha256'} mappings or (path, sha256) tuples."
        )

    normalized_cifs: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    seen_hashes: set[str] = set()

    for idx, item in enumerate(shared_ligand_cifs):
        if isinstance(item, Mapping):
            allowed_keys = {"path", "sha256"}
            alt_keys = {"cif_path", "sha256"}
            keys = set(item.keys())
            if keys == allowed_keys:
                raw_path = item["path"]
            elif keys == alt_keys:
                raw_path = item["cif_path"]
            else:
                raise ValueError(
                    f"shared_ligand_cifs[{idx}] mapping must have exact keys {{'path', 'sha256'}}, got {sorted(keys)}."
                )
            raw_sha = item["sha256"]
        elif isinstance(item, (tuple, list)) and len(item) == 2:
            raw_path, raw_sha = item
        else:
            raise ValueError(
                f"shared_ligand_cifs[{idx}] must be a {'path', 'sha256'} mapping or 2-tuple."
            )

        path_str = _validate_portable_relpath(raw_path, suffix=".cif")
        sha_str = _validate_sha256(raw_sha, field_name=f"shared_ligand_cifs[{idx}].sha256")

        if path_str in seen_paths:
            raise ValueError(f"Duplicate ligand CIF path {path_str!r} in shared_ligand_cifs.")
        if sha_str in seen_hashes:
            raise ValueError(f"Duplicate ligand CIF SHA-256 {sha_str!r} in shared_ligand_cifs.")

        seen_paths.add(path_str)
        seen_hashes.add(sha_str)
        normalized_cifs.append({"path": path_str, "sha256": sha_str})

    frozen_cifs = tuple(normalized_cifs)

    return {
        "kind": "pure_h_isolation_contract",
        "registration_status": REGISTRATION_STATUS,
        "stage2_status": STAGE2_SPEC_STATUS,
        "executed": False,
        "shared_ligand_cifs": frozen_cifs,
        "declared_common_start": copy.deepcopy(declared_common_start),
        "levels": {
            "H_off": {
                "level_id": "H_off",
                "executed": False,
                "ready_set_planned": False,
                "ready_set_phil": {},
                "refine_phil": {},
                "requires_proven_hd_free_common_start": True,
                "requires_declared_common_start_sha256": True,
                "requires_declared_hd_audit_receipt": True,
                "bare_hash_alone_sufficient": False,
                "omitted_ready_set_alone_sufficient": False,
                "hd_free_start_requirement_reason": (
                    "phenix.refine does not strip existing H/D scatterers from the input model "
                    "(preprocess.py:348-372); H_off therefore requires a declared H/D-free common "
                    "starting coordinate model and H/D audit receipt binding in addition to "
                    "omitting phenix.ready_set."
                ),
                "shared_ligand_cifs": frozen_cifs,
                "declared_common_start": copy.deepcopy(declared_common_start),
            },
            "H_riding": {
                "level_id": "H_riding",
                "executed": False,
                "ready_set_planned": True,
                "ready_set_phil": {
                    READY_SET_HYDROGENS_PHIL_PATH: True,
                    READY_SET_LIGANDS_PHIL_PATH: False,
                },
                "refine_phil": {
                    HYDROGENS_REFINE_PHIL_PATH: "riding",
                },
                "requires_proven_hd_free_common_start": True,
                "requires_declared_common_start_sha256": True,
                "requires_declared_hd_audit_receipt": True,
                "bare_hash_alone_sufficient": False,
                "shared_ligand_cifs": frozen_cifs,
                "declared_common_start": copy.deepcopy(declared_common_start),
            },
        },
        "arm3b_plus_readyset_combined_reservation": {
            "arm_id": "Arm 3b-plus-readyset",
            "ready_set_phil": {
                READY_SET_HYDROGENS_PHIL_PATH: True,
                READY_SET_LIGANDS_PHIL_PATH: True,
            },
            "used_in_pure_h_factorial": False,
            "source_anchor": SOURCE_ANCHORS["ready_set_defaults"],
        },
        "source_anchors": {
            "ready_set_defaults": SOURCE_ANCHORS["ready_set_defaults"],
            "preprocess_hd_handling": SOURCE_ANCHORS["preprocess"],
        },
    }


def factorial_cells(d_min: float | int) -> list[dict[str, Any]]:
    """Return the U04 resolution-feasible crossed factorial schedule for ``d_min``.

    Crosses:
      ``ready_set_h`` (``H_off``, ``H_riding``)
      x ``ordered_solvent`` (``sol_off``, ``sol_on`` in T1-T3; ``sol_on`` pruned in T4)
      x ``adp_tls_mode`` (two explicitly unresolved tier-specific levels; never auto-chosen)
      x ``optimize_weights`` (``wt_fixed`` vs ``wt_opt`` with ``force_optimize_weights=True``)

    Produces 16 unique cells in T1-T3 and 8 unique cells in T4.
    """
    tier = resolution_tier(d_min)
    h_levels = ("H_off", "H_riding")
    if tier.tier_id == "T4":
        solvent_levels: tuple[str, ...] = ("sol_off",)
        pruned_solvent_levels: tuple[str, ...] = ("sol_on",)
        solvent_pruning_reason: str | None = (
            "sol_on is pruned at d_min >= 2.80 A (T4) because phenix/refinement/task_table.py:"
            "118-124 requires strict ordered_solvent.low_resolution > d_min (default 2.8 > d_min)."
        )
    else:
        solvent_levels = ("sol_off", "sol_on")
        pruned_solvent_levels = ()
        solvent_pruning_reason = None

    adp_tls_levels = (
        f"{tier.tier_id}_adp_tls_level_a_unresolved",
        f"{tier.tier_id}_adp_tls_level_b_unresolved",
    )
    weight_levels = ("wt_fixed", "wt_opt")

    unrequested_aniso_forbidden = tier.d_min > TIER_CUTOFF_T2_T3
    aniso_demotion_contract = {
        "unrequested_aniso_macromol_forbidden": unrequested_aniso_forbidden,
        "demotion_cutoff_angstrom": TIER_CUTOFF_T2_T3,
        "explicit_anisotropic_selection_exception": True,
        "silent_native_anisotropic_promotion": False,
        "source_anchor": SOURCE_ANCHORS["preprocess"],
        "explanation": (
            "assert_no_anisotropic_atoms_at_low_resolution (preprocess.py:394-417) converts "
            "unrequested input anisotropic scatterers to isotropic when d_min > "
            "main.switch_to_isotropic_high_res_limit (default 1.5 A), except explicit "
            "params.refine.adp.individual.anisotropic selections (:400-407, 730-736) and TLS "
            "groups when tls is in refine.strategy (:408-411). When no explicit isotropic or "
            "anisotropic selections are given, preprocess.py:837-840 preserves input flags and "
            "never silently promotes isotropic scatterers to anisotropic."
        ),
    }

    cells: list[dict[str, Any]] = []
    for h_level in h_levels:
        for sol_level in solvent_levels:
            for adp_level in adp_tls_levels:
                for wt_level in weight_levels:
                    cell_id = (
                        f"{tier.tier_id}__{h_level}__{sol_level}__{adp_level}__{wt_level}"
                    )
                    if h_level == "H_riding":
                        preprocessing = {
                            "enabled": True,
                            "program": "phenix.ready_set",
                            "phil_assignments": {
                                READY_SET_HYDROGENS_PHIL_PATH: True,
                                READY_SET_LIGANDS_PHIL_PATH: False,
                            },
                            "requires_proven_hd_free_common_start": True,
                            "source_anchor": SOURCE_ANCHORS["ready_set_defaults"],
                        }
                    else:
                        preprocessing = {
                            "enabled": False,
                            "program": None,
                            "phil_assignments": {},
                            "requires_proven_hd_free_common_start": True,
                            "source_anchor": SOURCE_ANCHORS["preprocess"],
                        }

                    known_refine_phil: dict[str, bool | int | float | str] = {
                        MACRO_CYCLES_PHIL_PATH: 5,
                        CDL_PHIL_PATH: True,
                        ORDERED_SOLVENT_PHIL_PATH: (sol_level == "sol_on"),
                    }
                    if h_level == "H_riding":
                        known_refine_phil[HYDROGENS_REFINE_PHIL_PATH] = "riding"

                    if wt_level == "wt_opt":
                        known_refine_phil[OPT_XYZ_WEIGHT_PHIL_PATH] = True
                        known_refine_phil[OPT_ADP_WEIGHT_PHIL_PATH] = True
                        known_refine_phil[FORCE_OPT_WEIGHTS_PHIL_PATH] = True
                    else:
                        known_refine_phil[OPT_XYZ_WEIGHT_PHIL_PATH] = False
                        known_refine_phil[OPT_ADP_WEIGHT_PHIL_PATH] = False
                        known_refine_phil[FORCE_OPT_WEIGHTS_PHIL_PATH] = False

                    required_bindings: dict[str, str] = {
                        "adp_tls_level_binding": (
                            f"Concrete Stage 2 ADP/TLS selection & strategy binding for unresolved "
                            f"factorial slot {adp_level!r} in tier {tier.tier_id}."
                        ),
                        "shared_ligand_cifs": (
                            "Shared frozen ligand CIF bindings (validated via pure_h_contract) "
                            "held identical across H_off and H_riding."
                        ),
                        "hd_free_start_model_sha256": (
                            "Declared SHA-256 digest of the common H/D-free starting coordinate model "
                            "shared across H_off and H_riding."
                        ),
                        "hd_audit_receipt": (
                            "Declared H/D audit receipt binding "
                            "{'receipt_sha256': <64-hex>, 'subject_model_sha256': <64-hex matching "
                            "hd_free_start_model_sha256>, 'hd_atom_count': 0} (validates declared "
                            "receipt contract only; not runtime-measured)."
                        ),
                    }

                    cells.append(
                        {
                            "kind": "factorial_cell",
                            "registration_status": REGISTRATION_STATUS,
                            "stage2_status": STAGE2_SPEC_STATUS,
                            "development_frozen": False,
                            "study_track": "parameter_sensitivity",
                            "design_role": "crossed_factorial_core",
                            "one_factor": False,
                            "interaction_claims_permitted": True,
                            "r_free_selection_permitted": False,
                            "r_sleep_selection_permitted": False,
                            "cell_id": cell_id,
                            "d_min": tier.d_min,
                            "tier": tier,
                            "tier_id": tier.tier_id,
                            "factors": {
                                "ready_set_h": h_level,
                                "ordered_solvent": sol_level,
                                "adp_tls_mode": adp_level,
                                "optimize_weights": wt_level,
                            },
                            "adp_tls_level_resolved": False,
                            "pruned_solvent_levels": pruned_solvent_levels,
                            "solvent_pruning_reason": solvent_pruning_reason,
                            "aniso_demotion_contract": copy.deepcopy(aniso_demotion_contract),
                            "preprocessing": preprocessing,
                            "known_refine_phil": known_refine_phil,
                            "required_bindings": required_bindings,
                            "dormant_source_block_untouched": DORMANT_TLS_ADP_GUARD_ANCHOR,
                            "source_anchors": {
                                "run_sol": SOURCE_ANCHORS["task_table_run_sol"],
                                "preprocess": SOURCE_ANCHORS["preprocess"],
                                "xyz_weight_skip": SOURCE_ANCHORS["xyz_weight_skip_predicate"],
                                "ready_set_defaults": SOURCE_ANCHORS["ready_set_defaults"],
                                "cdl": SOURCE_ANCHORS["cdl_master_params"],
                            },
                        }
                    )
    return cells


COORDINATE_STRATEGY_TOKENS_FOR_CBETA: frozenset[str] = frozenset(
    {"individual_sites", "individual_sites_real_space"}
)


def predict_static_c_beta_restraints(
    d_min: float | int,
    requested_c_beta_restraints: bool,
    refine_strategy: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Evaluate the static PHENIX preprocess.py:170-174 C-beta restraint predicate.

    In ``phenix/refinement/fsr/preprocess.py:170-174``, ``c_beta_restraints`` is forced
    ``False`` whenever ``d_min <= 1.5`` OR neither ``individual_sites_real_space`` nor
    ``individual_sites`` is present in ``refine.strategy``.

    This helper is strictly a STATIC source-predicate calculation (``runtime_measured=False``)
    and never executes PHENIX or infers an unbound coordinate strategy.
    """
    val = _validate_d_min(d_min)
    if not isinstance(requested_c_beta_restraints, bool):
        raise ValueError(
            "requested_c_beta_restraints must be a bool (not int/str), "
            f"got {type(requested_c_beta_restraints).__name__}."
        )
    strategies: tuple[str, ...] | None = None
    if refine_strategy is not None:
        strategies = _validate_strategy_list(refine_strategy)

    d_min_le_1p50 = val <= TIER_CUTOFF_T2_T3
    coord_active: bool | None = (
        bool(set(strategies) & COORDINATE_STRATEGY_TOKENS_FOR_CBETA)
        if strategies is not None
        else None
    )

    if not requested_c_beta_restraints:
        static_effective: bool | None = False
        status = "static_source_derived_disabled_by_request"
    elif d_min_le_1p50:
        static_effective = False
        status = "static_source_derived_forced_false_le_1p50"
    elif strategies is None:
        static_effective = None
        status = "conditional_unassessed_until_strategy_bound"
    elif coord_active:
        static_effective = True
        status = "static_source_derived_enabled_with_coordinate_strategy"
    else:
        static_effective = False
        status = "static_source_derived_forced_false_no_coordinate_strategy"

    return {
        "requested_c_beta_restraints": requested_c_beta_restraints,
        "static_effective_c_beta_restraints": static_effective,
        "prediction_status": status,
        "prediction_basis": "static_source_predicate_not_runtime_measured",
        "runtime_measured": False,
        "d_min": val,
        "d_min_le_1p50": d_min_le_1p50,
        "coordinate_strategy_bound": (strategies is not None),
        "coordinate_strategy_active": coord_active,
        "required_coordinate_strategies": ("individual_sites", "individual_sites_real_space"),
        "source_anchor": SOURCE_ANCHORS["preprocess"],
    }


def sensitivity_cells(d_min: float | int) -> list[dict[str, Any]]:
    """Return the U04 one-factor sensitivity cells (S1-S4) applicable at ``d_min``.

    Every cell is explicitly one-factor (``one_factor=True``,
    ``interaction_claims_permitted=False``):
    - ``S1``: inclusive ``1.50 <= d_min <= 1.70`` (``1.5`` code vs ``1.7`` FAQ switch limit).
    - ``S2``: ``refinement.pdb_interpretation.restraints_library.cdl`` ``True`` vs ``False`` (#1238).
    - ``S3``: separate ``c_beta_restraints`` (``True`` vs ``False``) and ``nonbonded_weight``
      (``100`` vs ``16``) one-factor comparisons (never crossed into a 2x2 interaction grid),
      recording the native limitation that ``c_beta_restraints`` is forced ``False`` at
      ``d_min <= 1.50`` (``preprocess.py:170-174``).
    - ``S4``: Tier 4 (``d_min >= 2.80``) only; ``torsion_ncs``, ``secondary_structure``,
      and ``rotamer`` restraints turned off one-by-one against ``all_on`` using the
      source-verified PHIL switches in
      ``ref/research/data/phenix_stage2_static_phil_witness_2026-11-16.json``
      (effective native NCS/restraint construction remains unassessed).
    """
    tier = resolution_tier(d_min)
    val = tier.d_min
    cells: list[dict[str, Any]] = []

    base_ordered_solvent = tier.tier_id != "T4"
    c_beta_forced_false = val <= TIER_CUTOFF_T2_T3

    def _common_refine_phil() -> dict[str, bool | int | float | str]:
        phil: dict[str, bool | int | float | str] = {
            MACRO_CYCLES_PHIL_PATH: 5,
            HYDROGENS_REFINE_PHIL_PATH: "riding",
            CDL_PHIL_PATH: True,
            ORDERED_SOLVENT_PHIL_PATH: base_ordered_solvent,
        }
        if tier.tier_id in {"T1", "T2", "T3"}:
            phil[OPT_XYZ_WEIGHT_PHIL_PATH] = True
            phil[OPT_ADP_WEIGHT_PHIL_PATH] = True
        return phil

    def _common_required_bindings() -> dict[str, str]:
        req: dict[str, str] = {
            "adp_tls_level_binding": (
                f"Concrete Stage 2 baseline ADP/TLS selection & strategy binding for tier {tier.tier_id}."
            ),
        }
        if tier.tier_id == "T4":
            req["t4_weight_optimization_policy"] = (
                "Explicit Tier 4 weight-optimization dict {'optimize_xyz_weight': bool, "
                "'optimize_adp_weight': bool, 'force_optimize_weights': bool}."
            )
        return req

    # S1: inclusive [1.50, 1.70] A
    if S1_MIN_D_MIN <= val <= S1_MAX_D_MIN:
        s1_static_contrast = val > TIER_CUTOFF_T2_T3
        s1_predicate_note = (
            "At exact d_min == 1.50 A, preprocess.py:395-396 strict inequality "
            "(d_min > switch_to_isotropic_high_res_limit) evaluates False for both 1.5 and 1.7 "
            "(no static switch contrast expected; both cells remain scheduled per inclusive "
            "[1.50, 1.70] A U04 policy without claiming a measured zero difference)."
            if not s1_static_contrast
            else (
                "For 1.50 < d_min <= 1.70 A, preprocess.py:395-396 strict inequality "
                "(d_min > switch_to_isotropic_high_res_limit) evaluates True for 1.5 and False "
                "for 1.7 on unrequested ANISOU atoms when input ADP flags are preserved."
            )
        )
        for label_suffix, limit_val, origin in (
            ("1p5_code", 1.5, "code_default_preprocess_py_395_396"),
            ("1p7_faq", 1.7, "faq_refine_txt_444_448"),
        ):
            phil = _common_refine_phil()
            phil[SWITCH_ISO_LIMIT_PHIL_PATH] = limit_val
            s1_req = _common_required_bindings()
            s1_req["adp_tls_level_binding"] = (
                "S1 preserve_input_adp binding: mode='preserve_input_adp', 'individual_adp' "
                "active in refine_strategy, NO explicit isotropic/anisotropic/group/TLS "
                "selections, and declared input_model_sha256, applicability_receipt_sha256, "
                "and positive unrequested_anisou_count (> 0)."
            )
            cells.append(
                {
                    "kind": "sensitivity_cell",
                    "registration_status": REGISTRATION_STATUS,
                    "stage2_status": STAGE2_SPEC_STATUS,
                    "development_frozen": False,
                    "study_track": "parameter_sensitivity",
                    "design_role": "one_factor_sensitivity",
                    "arm_family": "S1",
                    "comparison_group": "S1_switch_to_isotropic_high_res_limit",
                    "cell_id": f"S1__{tier.tier_id}__switch_to_isotropic_limit_{label_suffix}",
                    "one_factor": True,
                    "interaction_claims_permitted": False,
                    "r_free_selection_permitted": False,
                    "r_sleep_selection_permitted": False,
                    "d_min": val,
                    "tier": tier,
                    "tier_id": tier.tier_id,
                    "factor_name": SWITCH_ISO_LIMIT_PHIL_PATH,
                    "factor_level": limit_val,
                    "level_origin": origin,
                    "s1_binding_mode": "preserve_input_adp",
                    "native_demotion_strict_gt_1p5": s1_static_contrast,
                    "native_demotion_strict_gt_switch_limit": (val > limit_val),
                    "expected_static_switch_contrast": s1_static_contrast,
                    "static_switch_predicate_note": s1_predicate_note,
                    "preprocessing": {
                        "enabled": False,
                        "program": None,
                        "phil_assignments": {},
                    },
                    "known_refine_phil": phil,
                    "required_bindings": s1_req,
                    "dormant_source_block_untouched": DORMANT_TLS_ADP_GUARD_ANCHOR,
                    "source_anchors": {
                        "init_params": SOURCE_ANCHORS["master_init_params"],
                        "preprocess": SOURCE_ANCHORS["preprocess"],
                        "faq_refine": SOURCE_ANCHORS["faq_refine"],
                    },
                }
            )

    # S2: CDL True vs False (#1238)
    for cdl_val in (True, False):
        phil = _common_refine_phil()
        phil[CDL_PHIL_PATH] = cdl_val
        cells.append(
            {
                "kind": "sensitivity_cell",
                "registration_status": REGISTRATION_STATUS,
                "stage2_status": STAGE2_SPEC_STATUS,
                "development_frozen": False,
                "study_track": "parameter_sensitivity",
                "design_role": "one_factor_sensitivity",
                "arm_family": "S2",
                "comparison_group": "S2_restraints_library_cdl",
                "cell_id": f"S2__{tier.tier_id}__cdl_{str(cdl_val).lower()}",
                "one_factor": True,
                "interaction_claims_permitted": False,
                "r_free_selection_permitted": False,
                "r_sleep_selection_permitted": False,
                "d_min": val,
                "tier": tier,
                "tier_id": tier.tier_id,
                "factor_name": CDL_PHIL_PATH,
                "factor_level": cdl_val,
                "preprocessing": {
                    "enabled": False,
                    "program": None,
                    "phil_assignments": {},
                },
                "known_refine_phil": phil,
                "required_bindings": _common_required_bindings(),
                "dormant_source_block_untouched": DORMANT_TLS_ADP_GUARD_ANCHOR,
                "source_anchors": {
                    "cdl_master_params": SOURCE_ANCHORS["cdl_master_params"],
                    "init_params": SOURCE_ANCHORS["master_init_params"],
                },
            }
        )

    # S3a: c_beta_restraints True vs False (separate one-factor comparison)
    for cbeta_val in (True, False):
        phil = _common_refine_phil()
        phil[C_BETA_RESTRAINTS_PHIL_PATH] = cbeta_val
        cbeta_pred = predict_static_c_beta_restraints(
            val,
            cbeta_val,
            refine_strategy=None,
        )
        cells.append(
            {
                "kind": "sensitivity_cell",
                "registration_status": REGISTRATION_STATUS,
                "stage2_status": STAGE2_SPEC_STATUS,
                "development_frozen": False,
                "study_track": "parameter_sensitivity",
                "design_role": "one_factor_sensitivity",
                "arm_family": "S3",
                "comparison_group": "S3_c_beta_restraints",
                "cell_id": f"S3__{tier.tier_id}__c_beta_restraints_{str(cbeta_val).lower()}",
                "one_factor": True,
                "interaction_claims_permitted": False,
                "crossed_with_nonbonded_weight": False,
                "r_free_selection_permitted": False,
                "r_sleep_selection_permitted": False,
                "d_min": val,
                "tier": tier,
                "tier_id": tier.tier_id,
                "factor_name": C_BETA_RESTRAINTS_PHIL_PATH,
                "factor_level": cbeta_val,
                "requested_c_beta_restraints": cbeta_val,
                "c_beta_forced_false_by_d_min_le_1p5": c_beta_forced_false,
                "c_beta_forced_false_by_native_preprocess": (
                    True if c_beta_forced_false else (False if not cbeta_val else None)
                ),
                "effective_native_c_beta_restraints": cbeta_pred["static_effective_c_beta_restraints"],
                "static_effective_c_beta_restraints": cbeta_pred["static_effective_c_beta_restraints"],
                "c_beta_prediction_status": cbeta_pred["prediction_status"],
                "c_beta_prediction_basis": cbeta_pred["prediction_basis"],
                "native_limitation_note": (
                    "STATIC source predicate (phenix/refinement/fsr/preprocess.py:170-174, "
                    "not runtime measured): params.pdb_interpretation.c_beta_restraints is "
                    "forced False whenever d_min <= 1.50 A OR neither "
                    "individual_sites_real_space nor individual_sites is in refine.strategy. "
                    "For unbound S3 specs at d_min > 1.50 A with factor_level=True, effective "
                    "C-beta restraint activation remains conditional/unassessed until "
                    "refine_strategy is bound."
                ),
                "preprocessing": {
                    "enabled": False,
                    "program": None,
                    "phil_assignments": {},
                },
                "known_refine_phil": phil,
                "required_bindings": _common_required_bindings(),
                "dormant_source_block_untouched": DORMANT_TLS_ADP_GUARD_ANCHOR,
                "source_anchors": {
                    "preprocess": SOURCE_ANCHORS["preprocess"],
                },
            }
        )

    # S3b: nonbonded_weight 100 vs 16 (separate one-factor comparison)
    for nb_val in (100, 16):
        phil = _common_refine_phil()
        phil[NONBONDED_WEIGHT_PHIL_PATH] = nb_val
        cells.append(
            {
                "kind": "sensitivity_cell",
                "registration_status": REGISTRATION_STATUS,
                "stage2_status": STAGE2_SPEC_STATUS,
                "development_frozen": False,
                "study_track": "parameter_sensitivity",
                "design_role": "one_factor_sensitivity",
                "arm_family": "S3",
                "comparison_group": "S3_nonbonded_weight",
                "cell_id": f"S3__{tier.tier_id}__nonbonded_weight_{nb_val}",
                "one_factor": True,
                "interaction_claims_permitted": False,
                "crossed_with_c_beta_restraints": False,
                "r_free_selection_permitted": False,
                "r_sleep_selection_permitted": False,
                "d_min": val,
                "tier": tier,
                "tier_id": tier.tier_id,
                "factor_name": NONBONDED_WEIGHT_PHIL_PATH,
                "factor_level": nb_val,
                "c_beta_forced_false_by_native_preprocess": c_beta_forced_false,
                "preprocessing": {
                    "enabled": False,
                    "program": None,
                    "phil_assignments": {},
                },
                "known_refine_phil": phil,
                "required_bindings": _common_required_bindings(),
                "dormant_source_block_untouched": DORMANT_TLS_ADP_GUARD_ANCHOR,
                "source_anchors": {
                    "preprocess": SOURCE_ANCHORS["preprocess"],
                },
            }
        )

    # S4: Tier 4 only — torsion_ncs, secondary_structure, rotamer turned off one-by-one vs all-on
    if tier.tier_id == "T4":
        s4_levels: tuple[tuple[str, str | None, dict[str, bool]], ...] = (
            (
                "all_on",
                None,
                {"torsion_ncs": True, "secondary_structure": True, "rotamer": True},
            ),
            (
                "torsion_ncs_off",
                "torsion_ncs",
                {"torsion_ncs": False, "secondary_structure": True, "rotamer": True},
            ),
            (
                "secondary_structure_off",
                "secondary_structure",
                {"torsion_ncs": True, "secondary_structure": False, "rotamer": True},
            ),
            (
                "rotamer_off",
                "rotamer",
                {"torsion_ncs": True, "secondary_structure": True, "rotamer": False},
            ),
        )
        for level_tag, ablated_name, restraint_states in s4_levels:
            phil = _common_refine_phil()
            phil[TORSION_NCS_SEARCH_ENABLED_PHIL_PATH] = bool(restraint_states["torsion_ncs"])
            phil[NCS_TYPE_PHIL_PATH] = "torsion"
            phil[SECONDARY_STRUCTURE_ENABLED_PHIL_PATH] = bool(
                restraint_states["secondary_structure"]
            )
            phil[ROTAMER_RESTRAINTS_PHIL_PATH] = bool(restraint_states["rotamer"])
            cells.append(
                {
                    "kind": "sensitivity_cell",
                    "registration_status": REGISTRATION_STATUS,
                    "stage2_status": STAGE2_SPEC_STATUS,
                    "development_frozen": False,
                    "study_track": "parameter_sensitivity",
                    "design_role": "one_factor_sensitivity",
                    "arm_family": "S4",
                    "comparison_group": "S4_t4_low_resolution_restraints_one_by_one",
                    "cell_id": f"S4__T4__{level_tag}",
                    "one_factor": True,
                    "interaction_claims_permitted": False,
                    "r_free_selection_permitted": False,
                    "r_sleep_selection_permitted": False,
                    "d_min": val,
                    "tier": tier,
                    "tier_id": tier.tier_id,
                    "factor_name": "t4_low_resolution_restraints_one_by_one",
                    "factor_level": level_tag,
                    "ablated_restraint": ablated_name,
                    "restraint_states": dict(restraint_states),
                    "effective_behavior_note": (
                        "Unassessed; enabling search/restraints is not proof of applicable "
                        "NCS or restraint construction."
                    ),
                    "preprocessing": {
                        "enabled": False,
                        "program": None,
                        "phil_assignments": {},
                    },
                    "known_refine_phil": phil,
                    "required_bindings": _common_required_bindings(),
                    "dormant_source_block_untouched": DORMANT_TLS_ADP_GUARD_ANCHOR,
                    "source_anchors": {
                        "preprocess": SOURCE_ANCHORS["preprocess"],
                        "faq_refine": SOURCE_ANCHORS["faq_refine"],
                        "static_phil_witness": SOURCE_ANCHORS[
                            "static_phil_witness_2026_11_16"
                        ],
                    },
                }
            )

    return cells


def _format_phil_scalar(value: bool | int | float | str) -> str:
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"Non-finite float {value!r} cannot be rendered to PHIL.")
        return repr(value)
    if isinstance(value, str):
        if any(ch in _UNSAFE_TEXT_CHARS for ch in value) or '"' in value or "\\" in value:
            raise ValueError(f"Unsafe string value {value!r} cannot be rendered to PHIL.")
        if " " in value or "\t" in value or "+" in value:
            return f'"{value}"' if "+" not in value or " " in value else value
        return value
    raise ValueError(f"Unsupported PHIL scalar type {type(value).__name__}.")


def _format_phil_quoted_string(value: str) -> str:
    if any(ch in _UNSAFE_TEXT_CHARS for ch in value) or '"' in value or "\\" in value:
        raise ValueError(f"Unsafe quoted string {value!r} cannot be rendered to PHIL.")
    return f'"{value}"'


_BOOL_PHIL_PATHS: frozenset[str] = frozenset(
    {
        CDL_PHIL_PATH,
        ORDERED_SOLVENT_PHIL_PATH,
        OPT_XYZ_WEIGHT_PHIL_PATH,
        OPT_ADP_WEIGHT_PHIL_PATH,
        FORCE_OPT_WEIGHTS_PHIL_PATH,
        C_BETA_RESTRAINTS_PHIL_PATH,
        TORSION_NCS_SEARCH_ENABLED_PHIL_PATH,
        SECONDARY_STRUCTURE_ENABLED_PHIL_PATH,
        ROTAMER_RESTRAINTS_PHIL_PATH,
        READY_SET_HYDROGENS_PHIL_PATH,
        READY_SET_LIGANDS_PHIL_PATH,
    }
)
_INT_PHIL_PATHS: frozenset[str] = frozenset(
    {
        MACRO_CYCLES_PHIL_PATH,
        NONBONDED_WEIGHT_PHIL_PATH,
    }
)
_FLOAT_PHIL_PATHS: frozenset[str] = frozenset(
    {
        SWITCH_ISO_LIMIT_PHIL_PATH,
    }
)
_STR_PHIL_PATHS: frozenset[str] = frozenset(
    {
        HYDROGENS_REFINE_PHIL_PATH,
        NCS_TYPE_PHIL_PATH,
        ADP_GROUP_MODE_PHIL_PATH,
    }
)


def _validate_phil_assignment_types(assignments: Mapping[str, Any], *, scope_label: str) -> None:
    for key, val in assignments.items():
        if not isinstance(key, str) or not key:
            raise ValueError(f"{scope_label} PHIL key must be a non-empty string, got {key!r}.")
        if key in _BOOL_PHIL_PATHS:
            if not isinstance(val, bool):
                raise ValueError(
                    f"{scope_label}[{key!r}] requires bool, got {type(val).__name__} ({val!r})."
                )
        elif key in _INT_PHIL_PATHS:
            if isinstance(val, bool) or not isinstance(val, int):
                raise ValueError(
                    f"{scope_label}[{key!r}] requires int (not bool), got {type(val).__name__} ({val!r})."
                )
        elif key in _FLOAT_PHIL_PATHS:
            if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(float(val)):
                raise ValueError(
                    f"{scope_label}[{key!r}] requires finite float/int (not bool), got {val!r}."
                )
        elif key in _STR_PHIL_PATHS:
            if not isinstance(val, str):
                raise ValueError(
                    f"{scope_label}[{key!r}] requires str, got {type(val).__name__} ({val!r})."
                )
            _format_phil_scalar(val)
        else:
            _format_phil_scalar(val)


def _assert_canonical_spec_match(actual: Any, expected: Any, *, path: str) -> None:
    if isinstance(expected, ResolutionTier):
        if isinstance(actual, ResolutionTier):
            if str(actual) != str(expected) or actual.to_dict() != expected.to_dict():
                raise ValueError(f"{path} ResolutionTier metadata does not match canonical policy.")
            return
        if type(actual) is str and actual == str(expected):
            return
        raise ValueError(f"{path} must match canonical tier {str(expected)!r}, got {actual!r}.")
    if isinstance(expected, bool):
        if not isinstance(actual, bool) or actual is not expected:
            raise ValueError(f"{path} must be canonical bool {expected!r}, got {actual!r}.")
        return
    if isinstance(expected, int):
        if isinstance(actual, bool) or not isinstance(actual, int) or actual != expected:
            raise ValueError(f"{path} must be canonical int {expected!r}, got {actual!r}.")
        return
    if isinstance(expected, float):
        if (
            isinstance(actual, bool)
            or not isinstance(actual, (int, float))
            or not math.isfinite(float(actual))
            or float(actual) != expected
        ):
            raise ValueError(f"{path} must be canonical float {expected!r}, got {actual!r}.")
        return
    if isinstance(expected, str):
        if not isinstance(actual, str) or actual != expected:
            raise ValueError(f"{path} must match canonical string {expected!r}, got {actual!r}.")
        return
    if expected is None:
        if actual is not None:
            raise ValueError(f"{path} must be None, got {actual!r}.")
        return
    if isinstance(expected, Mapping):
        if not isinstance(actual, Mapping):
            raise ValueError(f"{path} must be a mapping, got {type(actual).__name__}.")
        for k in actual.keys():
            if not isinstance(k, str):
                raise ValueError(f"{path} contains non-string key {k!r}.")
        actual_keys = set(actual.keys())
        expected_keys = set(expected.keys())
        if actual_keys != expected_keys:
            missing = sorted(expected_keys - actual_keys)
            extra = sorted(actual_keys - expected_keys)
            raise ValueError(
                f"{path} keys deviate from canonical policy (missing={missing}, extra={extra})."
            )
        for k in sorted(expected_keys):
            _assert_canonical_spec_match(actual[k], expected[k], path=f"{path}.{k}")
        return
    if isinstance(expected, (tuple, list)):
        if isinstance(actual, (str, bytes)) or not isinstance(actual, (tuple, list)):
            raise ValueError(f"{path} must be a list or tuple, got {type(actual).__name__}.")
        if len(actual) != len(expected):
            raise ValueError(
                f"{path} length {len(actual)} does not match canonical length {len(expected)}."
            )
        for idx, (act_item, exp_item) in enumerate(zip(actual, expected, strict=True)):
            _assert_canonical_spec_match(act_item, exp_item, path=f"{path}[{idx}]")
        return
    raise ValueError(f"Unsupported canonical spec element at {path}: {expected!r}.")


def _reconstruct_canonical_spec(spec: Mapping[str, Any]) -> dict[str, Any]:
    kind = spec.get("kind")
    if kind not in {"fixed_profile", "factorial_cell", "sensitivity_cell"}:
        raise ValueError(f"Unsupported spec kind {kind!r}.")
    d_min = _validate_d_min(spec.get("d_min"))
    if kind == "fixed_profile":
        arm_raw = spec.get("arm_id") if "arm_id" in spec else spec.get("arm_slug")
        if not isinstance(arm_raw, str):
            raise ValueError("fixed_profile spec must include string 'arm_id' or 'arm_slug'.")
        return fixed_profile(d_min, arm_raw)
    cell_id = spec.get("cell_id")
    if not isinstance(cell_id, str) or not cell_id:
        raise ValueError(f"{kind} spec must include non-empty string 'cell_id'.")
    candidates = (
        factorial_cells(d_min) if kind == "factorial_cell" else sensitivity_cells(d_min)
    )
    for cell in candidates:
        if cell["cell_id"] == cell_id:
            return cell
    raise ValueError(f"Unknown or mismatched {kind} cell_id {cell_id!r} for d_min={d_min}.")


def _validate_spec_structure(spec: Any) -> dict[str, Any]:
    if not isinstance(spec, Mapping):
        raise ValueError(f"spec must be a mapping, got {type(spec).__name__}.")
    for required_key in (
        "kind",
        "tier_id",
        "d_min",
        "preprocessing",
        "known_refine_phil",
        "required_bindings",
    ):
        if required_key not in spec:
            raise ValueError(f"spec is missing required structural key {required_key!r}.")
    if spec["kind"] not in {"fixed_profile", "factorial_cell", "sensitivity_cell"}:
        raise ValueError(f"Unsupported spec kind {spec['kind']!r}.")
    if not isinstance(spec["known_refine_phil"], Mapping) or not isinstance(
        spec["required_bindings"], Mapping
    ):
        raise ValueError("spec['known_refine_phil'] and spec['required_bindings'] must be mappings.")
    prep = spec["preprocessing"]
    if not isinstance(prep, Mapping) or not isinstance(prep.get("enabled"), bool):
        raise ValueError("spec['preprocessing'] must be a mapping with boolean 'enabled'.")
    prep_phil = prep.get("phil_assignments", {})
    if not isinstance(prep_phil, Mapping):
        raise ValueError("spec['preprocessing']['phil_assignments'] must be a mapping.")
    _validate_phil_assignment_types(prep_phil, scope_label="preprocessing.phil_assignments")
    _validate_phil_assignment_types(spec["known_refine_phil"], scope_label="known_refine_phil")

    canonical = _reconstruct_canonical_spec(spec)
    _assert_canonical_spec_match(spec, canonical, path="spec")
    try:
        actual_json = json.dumps(spec, sort_keys=True, allow_nan=False)
        canonical_json = json.dumps(canonical, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"spec is not canonical JSON-serializable: {exc}") from exc
    if actual_json != canonical_json:
        raise ValueError("spec deviates from canonical Stage 2 policy.")
    return canonical


def _validate_t4_weight_policy_binding(policy: Any) -> dict[str, bool]:
    if not isinstance(policy, Mapping):
        raise ValueError("t4_weight_optimization_policy must be a mapping.")
    expected_keys = {"optimize_xyz_weight", "optimize_adp_weight", "force_optimize_weights"}
    if set(policy.keys()) != expected_keys:
        raise ValueError(
            f"t4_weight_optimization_policy must have exact keys {sorted(expected_keys)}, "
            f"got {sorted(policy.keys())}."
        )
    out: dict[str, bool] = {}
    for key in expected_keys:
        val = policy[key]
        if not isinstance(val, bool):
            raise ValueError(
                f"t4_weight_optimization_policy[{key!r}] must be a bool, got {type(val).__name__}."
            )
        out[key] = val
    if (out["optimize_xyz_weight"] or out["optimize_adp_weight"]) and not out[
        "force_optimize_weights"
    ]:
        raise ValueError(
            "When Tier 4 weight optimization is enabled, force_optimize_weights must be True "
            "(xyz_reciprocal_space.py:452-464)."
        )
    if not out["optimize_xyz_weight"] and not out["optimize_adp_weight"] and out[
        "force_optimize_weights"
    ]:
        raise ValueError(
            "force_optimize_weights cannot be True when both optimize_xyz_weight and "
            "optimize_adp_weight are False."
        )
    return out


def _validate_common_non_adp_strategy(
    value: Any, *, field_name: str = "common_non_adp_strategy"
) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(
            f"{field_name} must be a sequence of non-ADP strategy names (not a single string)."
        )
    tokens: list[str] = []
    for idx, item in enumerate(value):
        if not isinstance(item, str):
            raise ValueError(f"{field_name}[{idx}] must be a string.")
        tok = item.strip()
        if tok in ADP_TLS_STRATEGY_TOKENS:
            raise ValueError(
                f"{field_name} cannot include ADP/TLS strategy token {tok!r}."
            )
        if tok not in ALLOWED_COMMON_NON_ADP_STRATEGIES:
            raise ValueError(
                f"Unsupported or confounding strategy token {item!r} in {field_name}; "
                f"allowed non-ADP strategies: {sorted(ALLOWED_COMMON_NON_ADP_STRATEGIES)}."
            )
        if tok in tokens:
            raise ValueError(f"Duplicate strategy token {tok!r} in {field_name}.")
        tokens.append(tok)
    return tuple(tokens)


def _validate_s1_preserve_input_adp_binding(
    binding: Any,
    outer_bindings: Mapping[str, Any] | None = None,
    *,
    common_non_adp_strategy: Any = None,
) -> tuple[list[tuple[str, str]], dict[str, Any]]:
    """Validate S1-specific preserve_input_adp binding and declared applicability evidence."""
    if not isinstance(binding, Mapping):
        raise ValueError("adp_tls_level_binding must be a mapping.")
    allowed_keys = {
        "mode",
        "preserve_input_adp",
        "refine_strategy",
        "common_non_adp_strategy",
        "input_model_sha256",
        "applicability_receipt_sha256",
        "unrequested_anisou_count",
        "adp_isotropic_selection",
        "adp_anisotropic_selection",
        "adp_group_selection",
        "tls_group_selections",
    }
    extra = set(binding.keys()) - allowed_keys
    if extra:
        raise ValueError(
            f"Unsupported keys in S1 adp_tls_level_binding: {sorted(extra)}."
        )

    outer = outer_bindings if isinstance(outer_bindings, Mapping) else {}
    inner_mode = binding.get("mode")
    outer_mode = outer.get("s1_binding_mode")
    preserve_flag = binding.get("preserve_input_adp")

    if preserve_flag is not None and (not isinstance(preserve_flag, bool) or preserve_flag is False):
        raise ValueError(
            "S1 preserve_input_adp flag must be True when supplied."
        )
    if inner_mode is not None and outer_mode is not None and inner_mode != outer_mode:
        raise ValueError(
            f"Conflicting S1 binding modes: {inner_mode!r} vs {outer_mode!r}."
        )
    effective_mode = inner_mode if inner_mode is not None else outer_mode
    if effective_mode is None and preserve_flag is True:
        effective_mode = "preserve_input_adp"
    if effective_mode != "preserve_input_adp":
        raise ValueError(
            "S1 sensitivity cells require mode='preserve_input_adp' to retain input ADP flags "
            "for switch_to_isotropic_high_res_limit comparison."
        )

    for sel_key in (
        "adp_isotropic_selection",
        "adp_anisotropic_selection",
        "adp_group_selection",
        "tls_group_selections",
    ):
        if sel_key in binding and binding[sel_key] is not None:
            raise ValueError(
                f"S1 preserve_input_adp mode forbids explicit {sel_key!r} because explicit "
                "ADP/TLS selections neutralize or exempt native switch_to_isotropic_high_res_limit demotion."
            )

    if "refine_strategy" not in binding:
        raise ValueError("adp_tls_level_binding requires 'refine_strategy'.")
    strategies = _validate_strategy_list(
        binding["refine_strategy"],
        required_tokens=frozenset({"individual_adp"}),
        forbidden_tokens=frozenset({"group_adp", "tls"}),
    )
    non_adp_tokens = tuple(tok for tok in strategies if tok not in ADP_TLS_STRATEGY_TOKENS)

    bound_common = binding.get("common_non_adp_strategy")
    if bound_common is not None and common_non_adp_strategy is not None:
        val_inner = _validate_common_non_adp_strategy(
            bound_common, field_name="adp_tls_level_binding.common_non_adp_strategy"
        )
        val_outer = _validate_common_non_adp_strategy(
            common_non_adp_strategy, field_name="common_non_adp_strategy"
        )
        if frozenset(val_inner) != frozenset(val_outer):
            raise ValueError(
                f"Conflicting common_non_adp_strategy bindings: {val_inner} vs {val_outer}."
            )
        expected_non_adp: tuple[str, ...] | None = val_outer
    elif bound_common is not None:
        expected_non_adp = _validate_common_non_adp_strategy(
            bound_common, field_name="adp_tls_level_binding.common_non_adp_strategy"
        )
    elif common_non_adp_strategy is not None:
        expected_non_adp = _validate_common_non_adp_strategy(
            common_non_adp_strategy, field_name="common_non_adp_strategy"
        )
    else:
        expected_non_adp = None

    if non_adp_tokens and expected_non_adp is None:
        raise ValueError(
            f"Non-ADP strategy tokens {list(non_adp_tokens)} in refine_strategy require an "
            "explicit 'common_non_adp_strategy' binding."
        )
    if expected_non_adp is not None and frozenset(non_adp_tokens) != frozenset(expected_non_adp):
        raise ValueError(
            f"Non-ADP strategy tokens {list(non_adp_tokens)} in refine_strategy do not match "
            f"common_non_adp_strategy {list(expected_non_adp)}."
        )

    def _resolve_field(key: str) -> Any:
        in_inner = key in binding and binding[key] is not None
        in_outer = key in outer and outer[key] is not None
        if in_inner and in_outer and binding[key] != outer[key]:
            raise ValueError(
                f"Conflicting S1 {key!r} values between adp_tls_level_binding and outer bindings."
            )
        if in_inner:
            return binding[key]
        if in_outer:
            return outer[key]
        raise ValueError(
            f"S1 preserve_input_adp binding is missing required applicability declaration {key!r}."
        )

    input_sha = _validate_sha256(
        _resolve_field("input_model_sha256"),
        field_name="input_model_sha256",
    )
    receipt_sha = _validate_sha256(
        _resolve_field("applicability_receipt_sha256"),
        field_name="applicability_receipt_sha256",
    )
    raw_count = _resolve_field("unrequested_anisou_count")
    if isinstance(raw_count, bool) or not isinstance(raw_count, int) or raw_count <= 0:
        raise ValueError(
            "S1 unrequested_anisou_count must be a strictly positive integer (> 0, not bool), "
            f"got {raw_count!r}."
        )

    lines: list[tuple[str, str]] = [
        (REFINE_STRATEGY_PHIL_PATH, "+".join(strategies)),
    ]
    normalized_meta: dict[str, Any] = {
        "mode": "preserve_input_adp",
        "refine_strategy": strategies,
        "common_non_adp_strategy": non_adp_tokens,
        "input_model_sha256": input_sha,
        "applicability_receipt_sha256": receipt_sha,
        "unrequested_anisou_count": raw_count,
    }
    return lines, normalized_meta


def _validate_adp_tls_level_binding(
    binding: Any,
    *,
    tier_id: str,
    d_min: float,
    expected_level_id: str | None = None,
    common_non_adp_strategy: Any = None,
) -> list[tuple[str, str]]:
    if not isinstance(binding, Mapping):
        raise ValueError("adp_tls_level_binding must be a mapping.")
    if binding.get("mode") == "preserve_input_adp" or binding.get("preserve_input_adp") is True:
        raise ValueError(
            "preserve_input_adp mode is only valid for S1 sensitivity cells."
        )
    allowed_keys = {
        "level_id",
        "refine_strategy",
        "common_non_adp_strategy",
        "adp_isotropic_selection",
        "adp_anisotropic_selection",
        "adp_group_selection",
        "tls_group_selections",
        "unrequested_aniso_macromol",
    }
    extra = set(binding.keys()) - allowed_keys
    if extra:
        raise ValueError(
            f"Unsupported keys in adp_tls_level_binding: {sorted(extra)}."
        )
    if expected_level_id is not None:
        if binding.get("level_id") != expected_level_id:
            raise ValueError(
                f"adp_tls_level_binding['level_id'] must match cell adp_tls_mode "
                f"{expected_level_id!r}, got {binding.get('level_id')!r}."
            )
    if "unrequested_aniso_macromol" in binding:
        unreq = binding["unrequested_aniso_macromol"]
        if not isinstance(unreq, bool):
            raise ValueError(
                "adp_tls_level_binding['unrequested_aniso_macromol'] must be a bool, "
                f"got {type(unreq).__name__}."
            )
        if unreq is True and d_min > TIER_CUTOFF_T2_T3:
            raise ValueError(
                "Unrequested macromolecular anisotropic ADP is forbidden at d_min > 1.50 A "
                "(preprocess.py:394-417)."
            )
    if "refine_strategy" not in binding:
        raise ValueError("adp_tls_level_binding requires 'refine_strategy'.")
    strategies = _validate_strategy_list(binding["refine_strategy"])
    non_adp_tokens = tuple(tok for tok in strategies if tok not in ADP_TLS_STRATEGY_TOKENS)
    adp_tokens = frozenset(tok for tok in strategies if tok in ADP_TLS_STRATEGY_TOKENS)

    bound_common = binding.get("common_non_adp_strategy")
    if bound_common is not None and common_non_adp_strategy is not None:
        val_inner = _validate_common_non_adp_strategy(
            bound_common, field_name="adp_tls_level_binding.common_non_adp_strategy"
        )
        val_outer = _validate_common_non_adp_strategy(
            common_non_adp_strategy, field_name="common_non_adp_strategy"
        )
        if frozenset(val_inner) != frozenset(val_outer):
            raise ValueError(
                f"Conflicting common_non_adp_strategy bindings: {val_inner} vs {val_outer}."
            )
        expected_non_adp: tuple[str, ...] | None = val_outer
    elif bound_common is not None:
        expected_non_adp = _validate_common_non_adp_strategy(
            bound_common, field_name="adp_tls_level_binding.common_non_adp_strategy"
        )
    elif common_non_adp_strategy is not None:
        expected_non_adp = _validate_common_non_adp_strategy(
            common_non_adp_strategy, field_name="common_non_adp_strategy"
        )
    else:
        expected_non_adp = None

    if non_adp_tokens and expected_non_adp is None:
        raise ValueError(
            f"Non-ADP strategy tokens {list(non_adp_tokens)} in refine_strategy require an "
            "explicit 'common_non_adp_strategy' binding."
        )
    if expected_non_adp is not None and frozenset(non_adp_tokens) != frozenset(expected_non_adp):
        raise ValueError(
            f"Non-ADP strategy tokens {list(non_adp_tokens)} in refine_strategy do not match "
            f"common_non_adp_strategy {list(expected_non_adp)}."
        )

    lines: list[tuple[str, str]] = [
        (REFINE_STRATEGY_PHIL_PATH, "+".join(strategies)),
    ]

    has_aniso = (
        "adp_anisotropic_selection" in binding
        and binding["adp_anisotropic_selection"] is not None
    )
    has_iso = (
        "adp_isotropic_selection" in binding
        and binding["adp_isotropic_selection"] is not None
    )
    has_indiv = has_aniso or has_iso
    has_group = (
        "adp_group_selection" in binding and binding["adp_group_selection"] is not None
    )
    has_tls = (
        "tls_group_selections" in binding and binding["tls_group_selections"] is not None
    )

    if has_indiv and "individual_adp" not in adp_tokens:
        raise ValueError(
            "adp_tls_level_binding specifies individual isotropic/anisotropic selection "
            "but 'individual_adp' is not in refine_strategy."
        )
    if "individual_adp" in adp_tokens and not has_indiv:
        raise ValueError(
            "adp_tls_level_binding includes 'individual_adp' in refine_strategy but omits "
            "both adp_isotropic_selection and adp_anisotropic_selection."
        )

    if has_group and "group_adp" not in adp_tokens:
        raise ValueError(
            "adp_tls_level_binding specifies adp_group_selection but 'group_adp' is not in "
            "refine_strategy."
        )
    if "group_adp" in adp_tokens and not has_group:
        raise ValueError(
            "adp_tls_level_binding includes 'group_adp' in refine_strategy but omits "
            "adp_group_selection."
        )

    if has_tls and "tls" not in adp_tokens:
        raise ValueError(
            "adp_tls_level_binding supplies tls_group_selections but 'tls' is not in refine_strategy."
        )
    if "tls" in adp_tokens and not has_tls:
        raise ValueError(
            "adp_tls_level_binding includes 'tls' in refine_strategy but omits tls_group_selections."
        )

    if not (has_indiv or has_group or has_tls):
        raise ValueError(
            "adp_tls_level_binding must specify at least one explicit ADP or TLS selection."
        )

    if has_aniso:
        aniso_sel = _validate_selection_string(
            binding["adp_anisotropic_selection"],
            field_name="adp_tls_level_binding.adp_anisotropic_selection",
        )
        lines.append((ADP_ANISO_SELECTION_PHIL_PATH, _format_phil_quoted_string(aniso_sel)))

    if has_iso:
        iso_sel = _validate_selection_string(
            binding["adp_isotropic_selection"],
            field_name="adp_tls_level_binding.adp_isotropic_selection",
        )
        lines.append((ADP_ISO_SELECTION_PHIL_PATH, _format_phil_quoted_string(iso_sel)))

    if has_group:
        grp_sel = _validate_selection_string(
            binding["adp_group_selection"],
            field_name="adp_tls_level_binding.adp_group_selection",
        )
        lines.append((ADP_GROUP_MODE_PHIL_PATH, "group_selection"))
        lines.append((ADP_GROUP_SELECTION_PHIL_PATH, _format_phil_quoted_string(grp_sel)))

    if has_tls:
        tls_groups = _validate_tls_groups(
            binding["tls_group_selections"],
            field_name="adp_tls_level_binding.tls_group_selections",
        )
        for group_sel in tls_groups:
            lines.append((TLS_SELECTION_PHIL_PATH, _format_phil_quoted_string(group_sel)))

    return lines


def normalize_adp_tls_binding_signature(
    binding: Any,
    *,
    tier_id: str,
    d_min: float,
    expected_level_id: str | None = None,
    common_non_adp_strategy: Any = None,
) -> dict[str, Any]:
    """Return a normalized declared ADP/TLS binding signature for factorial level comparison.

    Normalization contract (#1336):
    - ``refine_strategy`` and ``common_non_adp_strategy`` are normalized as sorted token
      sets (``refine_strategy_set``, ``adp_strategy_set``, ``common_non_adp_strategy_set``)
      because PHIL ``choice(multi=True)`` strategy membership is a set; supplying the same
      strategy tokens in different order cannot define a distinct ADP/TLS factorial level.
    - Atom-selection strings (``adp_anisotropic_selection``, ``adp_isotropic_selection``,
      ``adp_group_selection``, and each element of ``tls_group_selections``) are kept as
      exact validated selector strings without claiming general semantic equivalence of
      arbitrary atom-selection expressions.
    - ``tls_group_selections`` is normalized as a sorted tuple of exact validated selection
      strings (``tls_group_selections_set``) so that permuting an identical declared TLS
      group collection cannot by itself create a distinct ADP/TLS factorial level. This is
      a specification-level factor-distinctness guard only and does not claim numerical
      runtime identity or parse/verify disjointness of overlapping selection strings.
    """
    _validate_adp_tls_level_binding(
        binding,
        tier_id=tier_id,
        d_min=d_min,
        expected_level_id=expected_level_id,
        common_non_adp_strategy=common_non_adp_strategy,
    )
    strategies = _validate_strategy_list(binding["refine_strategy"])
    non_adp_tokens = tuple(
        sorted(tok for tok in strategies if tok not in ADP_TLS_STRATEGY_TOKENS)
    )
    adp_tokens = tuple(
        sorted(tok for tok in strategies if tok in ADP_TLS_STRATEGY_TOKENS)
    )
    has_aniso = (
        "adp_anisotropic_selection" in binding
        and binding["adp_anisotropic_selection"] is not None
    )
    has_iso = (
        "adp_isotropic_selection" in binding
        and binding["adp_isotropic_selection"] is not None
    )
    has_group = (
        "adp_group_selection" in binding and binding["adp_group_selection"] is not None
    )
    has_tls = (
        "tls_group_selections" in binding and binding["tls_group_selections"] is not None
    )
    aniso_sel = (
        _validate_selection_string(
            binding["adp_anisotropic_selection"],
            field_name="adp_tls_level_binding.adp_anisotropic_selection",
        )
        if has_aniso
        else None
    )
    iso_sel = (
        _validate_selection_string(
            binding["adp_isotropic_selection"],
            field_name="adp_tls_level_binding.adp_isotropic_selection",
        )
        if has_iso
        else None
    )
    grp_sel = (
        _validate_selection_string(
            binding["adp_group_selection"],
            field_name="adp_tls_level_binding.adp_group_selection",
        )
        if has_group
        else None
    )
    tls_groups_set = (
        tuple(
            sorted(
                _validate_tls_groups(
                    binding["tls_group_selections"],
                    field_name="adp_tls_level_binding.tls_group_selections",
                )
            )
        )
        if has_tls
        else ()
    )
    return {
        "refine_strategy_set": tuple(sorted(strategies)),
        "adp_strategy_set": adp_tokens,
        "common_non_adp_strategy_set": non_adp_tokens,
        "adp_anisotropic_selection": aniso_sel,
        "adp_isotropic_selection": iso_sel,
        "adp_group_selection": grp_sel,
        "group_adp_refinement_mode": "group_selection" if has_group else None,
        "tls_group_selections_set": tls_groups_set,
        "unrequested_aniso_macromol": bool(
            binding.get("unrequested_aniso_macromol", False)
        ),
    }


def render_known_eff_template(spec: Mapping[str, Any]) -> RenderedEffBundle:
    """Render a clearly marked INCOMPLETE template with known PHIL lines and unresolved comments.

    Symbolic/unresolved bindings are emitted strictly as ``# UNRESOLVED_REQUIRED_BINDING``
    comments and are never presented as executable PHIL syntax.
    """
    validated_spec = _validate_spec_structure(spec)
    prep = validated_spec["preprocessing"]
    ready_set_eff: str | None = None

    header_lines = [
        "# STATUS: RESULT-FREE STAGE 2 PROSPECTIVE SPECIFICATION TEMPLATE (INCOMPLETE / UNVERIFIED)",
        f"# registration_status = {REGISTRATION_STATUS} (NOT frozen_result_free)",
        f"# stage2_status = {STAGE2_SPEC_STATUS}",
        f"# spec_kind = {validated_spec['kind']} | tier_id = {validated_spec['tier_id']} | d_min = {validated_spec['d_min']}",
        "# WARNING: DO NOT EXECUTE. Required Stage 2 bindings below remain unresolved.",
    ]

    if prep.get("enabled"):
        rs_lines = [
            *header_lines,
            "# [SCOPE: phenix.ready_set]",
        ]
        for key in sorted(prep["phil_assignments"]):
            val = prep["phil_assignments"][key]
            rs_lines.append(f"{key} = {_format_phil_scalar(val)}")
        if "shared_ligand_cifs" in validated_spec["required_bindings"]:
            rs_lines.append(
                "# UNRESOLVED_REQUIRED_BINDING: shared_ligand_cifs — "
                f"{validated_spec['required_bindings']['shared_ligand_cifs']}"
            )
        ready_set_eff = "\n".join(rs_lines) + "\n"

    ref_lines = [
        *header_lines,
        "# [SCOPE: phenix.refine]",
    ]
    known_phil = validated_spec["known_refine_phil"]
    for key in sorted(known_phil):
        val = known_phil[key]
        ref_lines.append(f"{key} = {_format_phil_scalar(val)}")
    for req_key in sorted(validated_spec["required_bindings"]):
        desc = validated_spec["required_bindings"][req_key]
        ref_lines.append(f"# UNRESOLVED_REQUIRED_BINDING: {req_key} — {desc}")

    refine_eff = "\n".join(ref_lines) + "\n"
    combined = (ready_set_eff + "\n" + refine_eff) if ready_set_eff is not None else refine_eff
    return RenderedEffBundle(
        combined,
        refine_eff=refine_eff,
        ready_set_eff=ready_set_eff,
        is_complete=False,
    )


def _validate_sub_0p90_water_selection_audit(
    audit: Any,
    *,
    water_mode: str,
    iso_sel: str,
    aniso_sel: str,
) -> dict[str, Any]:
    """Validate the sub-0.90 A water-selection audit declaration (#1337).

    Enforces supplied-declaration consistency only (no coordinate-file or native execution
    inspection):
    - Valid 64-hex lowercase SHA-256 digests for ``refinement_input_model_sha256`` and
      ``audit_receipt_sha256``.
    - Receipt ``adp_isotropic_selection`` and ``adp_anisotropic_selection`` equal the exact
      emitted selector strings (and are not identical to each other).
    - Strict nonnegative integer water-atom routing counts (``total``, ``isotropic``,
      ``anisotropic``, ``neither``, ``both``) with ``neither == 0``, ``both == 0``, and
      ``isotropic + anisotropic == total``.
    - Mode-to-routing consistency: ``water_mode == 'isotropic'`` requires
      ``isotropic == total`` and ``anisotropic == 0``; ``water_mode == 'anisotropic'``
      requires ``anisotropic == total`` and ``isotropic == 0``.
    - Zero-water declarations (``total == 0``) are recorded as explicit no-water
      applicability (``explicit_no_water_applicability_not_observed_contrast``), never an
      observed contrast.
    """
    if not isinstance(audit, Mapping):
        raise ValueError("sub_0p90_water_selection_audit must be a mapping.")

    base_required = {
        "refinement_input_model_sha256",
        "audit_receipt_sha256",
        "adp_isotropic_selection",
        "adp_anisotropic_selection",
    }
    short_count_keys = {"total", "isotropic", "anisotropic", "neither", "both"}
    prefixed_count_keys = {
        "water_atom_count_total",
        "water_atom_count_isotropic",
        "water_atom_count_anisotropic",
        "water_atom_count_neither",
        "water_atom_count_both",
    }
    allowed_top_keys = (
        base_required | short_count_keys | prefixed_count_keys | {"water_routing_counts"}
    )
    extra_top = set(audit.keys()) - allowed_top_keys
    if extra_top:
        raise ValueError(
            f"Unsupported keys in sub_0p90_water_selection_audit: {sorted(extra_top)}."
        )
    missing_base = sorted(base_required - set(audit.keys()))
    if missing_base:
        raise ValueError(
            f"sub_0p90_water_selection_audit is missing required keys {missing_base}."
        )

    model_sha = _validate_sha256(
        audit["refinement_input_model_sha256"],
        field_name="sub_0p90_water_selection_audit.refinement_input_model_sha256",
    )
    receipt_sha = _validate_sha256(
        audit["audit_receipt_sha256"],
        field_name="sub_0p90_water_selection_audit.audit_receipt_sha256",
    )
    audit_iso = _validate_selection_string(
        audit["adp_isotropic_selection"],
        field_name="sub_0p90_water_selection_audit.adp_isotropic_selection",
    )
    audit_aniso = _validate_selection_string(
        audit["adp_anisotropic_selection"],
        field_name="sub_0p90_water_selection_audit.adp_anisotropic_selection",
    )
    if audit_iso != iso_sel:
        raise ValueError(
            "sub_0p90_water_selection_audit['adp_isotropic_selection'] must match emitted "
            f"adp_isotropic_selection: {audit_iso!r} != {iso_sel!r}."
        )
    if audit_aniso != aniso_sel:
        raise ValueError(
            "sub_0p90_water_selection_audit['adp_anisotropic_selection'] must match emitted "
            f"adp_anisotropic_selection: {audit_aniso!r} != {aniso_sel!r}."
        )
    if iso_sel == aniso_sel:
        raise ValueError(
            "adp_isotropic_selection and adp_anisotropic_selection cannot be identical."
        )

    nested_counts = audit.get("water_routing_counts")
    if nested_counts is not None:
        if not isinstance(nested_counts, Mapping):
            raise ValueError(
                "sub_0p90_water_selection_audit['water_routing_counts'] must be a mapping."
            )
        if set(nested_counts.keys()) != short_count_keys:
            raise ValueError(
                "sub_0p90_water_selection_audit['water_routing_counts'] must have exact keys "
                f"{sorted(short_count_keys)}, got {sorted(nested_counts.keys())}."
            )

    resolved_counts: dict[str, int] = {}
    for name in ("total", "isotropic", "anisotropic", "neither", "both"):
        pref_key = f"water_atom_count_{name}"
        candidates: list[Any] = []
        if name in audit:
            candidates.append(audit[name])
        if pref_key in audit:
            candidates.append(audit[pref_key])
        if isinstance(nested_counts, Mapping) and name in nested_counts:
            candidates.append(nested_counts[name])
        if not candidates:
            raise ValueError(
                f"sub_0p90_water_selection_audit is missing required water-routing count {name!r} "
                f"(or {pref_key!r})."
            )
        raw_val = candidates[0]
        for other_val in candidates[1:]:
            if (
                type(other_val) is not type(raw_val)
                or other_val != raw_val
            ):
                raise ValueError(
                    f"Conflicting values for water-routing count {name!r} in "
                    "sub_0p90_water_selection_audit."
                )
        if isinstance(raw_val, bool) or not isinstance(raw_val, int) or raw_val < 0:
            raise ValueError(
                f"sub_0p90_water_selection_audit water count {name!r} must be a strict "
                f"nonnegative int (not bool), got {raw_val!r}."
            )
        resolved_counts[name] = raw_val

    c_total = resolved_counts["total"]
    c_iso = resolved_counts["isotropic"]
    c_aniso = resolved_counts["anisotropic"]
    c_neither = resolved_counts["neither"]
    c_both = resolved_counts["both"]

    if c_neither != 0:
        raise ValueError(
            "sub_0p90_water_selection_audit requires 'neither' == 0 "
            f"(all water atoms must be routed), got {c_neither}."
        )
    if c_both != 0:
        raise ValueError(
            "sub_0p90_water_selection_audit requires 'both' == 0 "
            f"(water selections must be mutually exclusive), got {c_both}."
        )
    if c_iso + c_aniso + c_neither + c_both != c_total:
        raise ValueError(
            "sub_0p90_water_selection_audit mutually exclusive counts must sum to total: "
            f"isotropic({c_iso}) + anisotropic({c_aniso}) + neither({c_neither}) + both({c_both}) "
            f"!= total({c_total})."
        )

    if water_mode == "isotropic":
        if c_iso != c_total or c_aniso != 0:
            raise ValueError(
                "sub_0p90_water_adp_mode='isotropic' requires all declared water atoms to be "
                f"routed isotropic (isotropic={c_total}, anisotropic=0), got "
                f"isotropic={c_iso}, anisotropic={c_aniso}, total={c_total}."
            )
    elif water_mode == "anisotropic":
        if c_aniso != c_total or c_iso != 0:
            raise ValueError(
                "sub_0p90_water_adp_mode='anisotropic' requires all declared water atoms to be "
                f"routed anisotropic (anisotropic={c_total}, isotropic=0), got "
                f"isotropic={c_iso}, anisotropic={c_aniso}, total={c_total}."
            )
    else:
        raise ValueError(f"Unsupported sub_0p90_water_adp_mode {water_mode!r}.")

    applicability_status = (
        "explicit_no_water_applicability_not_observed_contrast"
        if c_total == 0
        else "declared_water_routing_consistent_unverified"
    )
    return {
        "refinement_input_model_sha256": model_sha,
        "audit_receipt_sha256": receipt_sha,
        "adp_isotropic_selection": audit_iso,
        "adp_anisotropic_selection": audit_aniso,
        "water_atom_count_total": c_total,
        "water_atom_count_isotropic": c_iso,
        "water_atom_count_anisotropic": c_aniso,
        "water_atom_count_neither": c_neither,
        "water_atom_count_both": c_both,
        "applicability_status": applicability_status,
    }


def render_eff(
    spec: Mapping[str, Any],
    bindings: Mapping[str, Any] | None = None,
) -> RenderedEffBundle:
    """Render deterministic flat PHIL text from ``spec`` and validated ``bindings``.

    Completeness semantics:
    - ``is_complete=True`` (and ``single_cell_binding_complete=True``) on ``render_eff``
      means supplied single-cell binding completeness ONLY, NOT comparison-level
      one-factor verification (``comparison_one_factor_verified=False``).
    - Actual model/native realization of the declared bindings remains unverified by
      this result-free specification compiler.
    - For one-factor sensitivity comparison groups (``S1``, ``S2``, ``S3_c_beta_restraints``,
      ``S3_nonbonded_weight``, ``S4_t4_low_resolution_restraints_one_by_one``), use
      ``validate_sensitivity_comparison_bindings`` / ``render_sensitivity_comparison``
      (or ``validate_s1_pair_bindings`` / ``render_s1_pair`` for ``S1``) to enforce
      shared non-factor bindings and exact single-factor PHIL diffs across the group.

    Fails closed (``ValueError``) if:
    - any required binding in ``spec['required_bindings']`` is missing or None,
    - any extra/unsupported key or locked-parameter override is passed in ``bindings``,
    - any binding value uses symbolic placeholder text, non-finite numbers, bool-as-number,
      invalid paths/hashes, or newline/comment/brace/shell injection characters.
    """
    validated_spec = _validate_spec_structure(spec)
    if bindings is None or not isinstance(bindings, Mapping):
        raise ValueError("bindings must be a mapping supplying all required_bindings.")

    required_keys = set(validated_spec["required_bindings"].keys())
    supplied_keys = set(bindings.keys())
    kind = str(validated_spec["kind"])
    if kind == "factorial_cell":
        optional_keys = {"common_non_adp_strategy"}
    elif kind == "sensitivity_cell":
        if validated_spec.get("arm_family") == "S1":
            optional_keys = {
                "common_non_adp_strategy",
                "s1_binding_mode",
                "input_model_sha256",
                "applicability_receipt_sha256",
                "unrequested_anisou_count",
            }
        else:
            optional_keys = {"common_non_adp_strategy"}
    else:
        optional_keys = set()

    missing_keys = sorted(required_keys - supplied_keys)
    if missing_keys:
        raise ValueError(
            f"Cannot render complete .eff: missing required Stage 2 bindings {missing_keys}."
        )
    extra_keys = sorted(supplied_keys - required_keys - optional_keys)
    if extra_keys:
        raise ValueError(
            f"Unsupported or extra override keys in bindings {extra_keys}; "
            f"only {sorted(required_keys | optional_keys)} are permitted."
        )

    tier_id = str(validated_spec["tier_id"])
    d_min = _validate_d_min(validated_spec["d_min"])

    known_phil = dict(validated_spec["known_refine_phil"])
    for k, v in known_phil.items():
        if isinstance(v, float) and not math.isfinite(v):
            raise ValueError(f"Locked PHIL parameter {k!r} has non-finite float {v!r}.")

    extra_refine_lines: list[tuple[str, str]] = []
    extra_ready_set_lines: list[tuple[str, str]] = []
    metadata_comments: list[str] = []

    if kind == "fixed_profile":
        if tier_id in {"T1", "T2"}:
            aniso_sel = _validate_selection_string(
                bindings["adp_anisotropic_selection"],
                field_name="adp_anisotropic_selection",
            )
            iso_sel = _validate_selection_string(
                bindings["adp_isotropic_selection"],
                field_name="adp_isotropic_selection",
            )
            if "sub_0p90_water_adp_mode" in required_keys:
                water_mode = bindings["sub_0p90_water_adp_mode"]
                if water_mode not in {"isotropic", "anisotropic"}:
                    raise ValueError(
                        "sub_0p90_water_adp_mode must be 'isotropic' or 'anisotropic', "
                        f"got {water_mode!r}."
                    )
                water_audit = _validate_sub_0p90_water_selection_audit(
                    bindings["sub_0p90_water_selection_audit"],
                    water_mode=water_mode,
                    iso_sel=iso_sel,
                    aniso_sel=aniso_sel,
                )
                metadata_comments.extend(
                    [
                        f"# sub_0p90_water_adp_mode = {water_mode} "
                        "(unresolved Stage 2 dev-set choice; supplied-declaration consistency only, "
                        "not verified coordinate contents or native behavior)",
                        f"# sub_0p90_water_selection_audit: "
                        f"refinement_input_model_sha256={water_audit['refinement_input_model_sha256']} | "
                        f"audit_receipt_sha256={water_audit['audit_receipt_sha256']} | "
                        f"total={water_audit['water_atom_count_total']} | "
                        f"isotropic={water_audit['water_atom_count_isotropic']} | "
                        f"anisotropic={water_audit['water_atom_count_anisotropic']} | "
                        f"neither={water_audit['water_atom_count_neither']} | "
                        f"both={water_audit['water_atom_count_both']} | "
                        f"applicability={water_audit['applicability_status']} "
                        "(supplied-declaration consistency only; not verified coordinate contents or native behavior)",
                    ]
                )
            extra_refine_lines.append(
                (ADP_ANISO_SELECTION_PHIL_PATH, _format_phil_quoted_string(aniso_sel))
            )
            extra_refine_lines.append(
                (ADP_ISO_SELECTION_PHIL_PATH, _format_phil_quoted_string(iso_sel))
            )
        elif tier_id == "T3":
            iso_sel = _validate_selection_string(
                bindings["adp_isotropic_selection"],
                field_name="adp_isotropic_selection",
            )
            tls_groups = _validate_tls_groups(bindings["tls_group_selections"])
            strategies = _validate_strategy_list(
                bindings["refine_strategy"],
                required_tokens=frozenset({"individual_adp", "tls"}),
                forbidden_tokens=frozenset({"group_adp"}),
            )
            extra_refine_lines.append((REFINE_STRATEGY_PHIL_PATH, "+".join(strategies)))
            extra_refine_lines.append(
                (ADP_ISO_SELECTION_PHIL_PATH, _format_phil_quoted_string(iso_sel))
            )
            for grp in tls_groups:
                extra_refine_lines.append(
                    (TLS_SELECTION_PHIL_PATH, _format_phil_quoted_string(grp))
                )
        elif tier_id == "T4":
            t4_mode = bindings["t4_adp_mode"]
            if t4_mode not in {"isotropic_plus_tls", "group_adp_plus_tls"}:
                raise ValueError(
                    "t4_adp_mode must be 'isotropic_plus_tls' or 'group_adp_plus_tls', "
                    f"got {t4_mode!r}."
                )
            adp_sel = _validate_selection_string(
                bindings["adp_selection"], field_name="adp_selection"
            )
            tls_groups = _validate_tls_groups(bindings["tls_group_selections"])
            req_strat = (
                frozenset({"individual_adp", "tls"})
                if t4_mode == "isotropic_plus_tls"
                else frozenset({"group_adp", "tls"})
            )
            forbid_strat = (
                frozenset({"group_adp"})
                if t4_mode == "isotropic_plus_tls"
                else frozenset({"individual_adp"})
            )
            strategies = _validate_strategy_list(
                bindings["refine_strategy"],
                required_tokens=req_strat,
                forbidden_tokens=forbid_strat,
            )
            extra_refine_lines.append((REFINE_STRATEGY_PHIL_PATH, "+".join(strategies)))
            if t4_mode == "isotropic_plus_tls":
                extra_refine_lines.append(
                    (ADP_ISO_SELECTION_PHIL_PATH, _format_phil_quoted_string(adp_sel))
                )
            else:
                extra_refine_lines.append((ADP_GROUP_MODE_PHIL_PATH, "group_selection"))
                extra_refine_lines.append(
                    (ADP_GROUP_SELECTION_PHIL_PATH, _format_phil_quoted_string(adp_sel))
                )
            for grp in tls_groups:
                extra_refine_lines.append(
                    (TLS_SELECTION_PHIL_PATH, _format_phil_quoted_string(grp))
                )

            wt_policy = _validate_t4_weight_policy_binding(
                bindings["t4_weight_optimization_policy"]
            )
            known_phil[OPT_XYZ_WEIGHT_PHIL_PATH] = wt_policy["optimize_xyz_weight"]
            known_phil[OPT_ADP_WEIGHT_PHIL_PATH] = wt_policy["optimize_adp_weight"]
            known_phil[FORCE_OPT_WEIGHTS_PHIL_PATH] = wt_policy["force_optimize_weights"]

    elif kind == "factorial_cell":
        expected_adp_level = str(validated_spec["factors"]["adp_tls_mode"])
        extra_refine_lines.extend(
            _validate_adp_tls_level_binding(
                bindings["adp_tls_level_binding"],
                tier_id=tier_id,
                d_min=d_min,
                expected_level_id=expected_adp_level,
                common_non_adp_strategy=bindings.get("common_non_adp_strategy"),
            )
        )
        h_contract = pure_h_contract(
            bindings["shared_ligand_cifs"],
            hd_free_start_model_sha256=bindings["hd_free_start_model_sha256"],
            hd_audit_receipt=bindings["hd_audit_receipt"],
        )
        prep_enabled = bool(validated_spec["preprocessing"].get("enabled"))
        for cif_entry in h_contract["shared_ligand_cifs"]:
            cif_path_quoted = _format_phil_quoted_string(cif_entry["path"])
            if prep_enabled:
                extra_ready_set_lines.append(
                    (READY_SET_CIF_FILE_NAME_PHIL_PATH, cif_path_quoted)
                )
            extra_refine_lines.append((REFINE_MONOMER_CIF_PHIL_PATH, cif_path_quoted))
            metadata_comments.append(
                f"# shared_ligand_cif: {cif_entry['path']} sha256={cif_entry['sha256']}"
            )
        hd_meta = h_contract["declared_common_start"]
        metadata_comments.extend(
            [
                f"# hd_free_start_model_sha256 = {hd_meta['hd_free_start_model_sha256']} "
                "(declared common starting-model binding; not runtime-verified from hash alone)",
                f"# hd_audit_receipt_sha256 = {hd_meta['receipt_sha256']} | "
                f"subject_model_sha256 = {hd_meta['subject_model_sha256']} | "
                f"declared_hd_atom_count = {hd_meta['hd_atom_count']} "
                "(declared evidence-bound receipt contract; coordinate bytes not inspected by spec compiler)",
            ]
        )

    elif kind == "sensitivity_cell":
        metadata_comments.append(_SINGLE_CELL_SENSITIVITY_STATUS_COMMENT)
        if validated_spec.get("arm_family") == "S1":
            s1_lines, s1_meta = _validate_s1_preserve_input_adp_binding(
                bindings["adp_tls_level_binding"],
                bindings,
                common_non_adp_strategy=bindings.get("common_non_adp_strategy"),
            )
            extra_refine_lines.extend(s1_lines)
            metadata_comments.extend(
                [
                    "# s1_binding_mode = preserve_input_adp "
                    "(declared input-ADP preservation; not runtime-verified)",
                    f"# s1_input_model_sha256 = {s1_meta['input_model_sha256']} "
                    "(declared starting-model digest; hash alone does not prove ANISOU eligibility)",
                    f"# s1_applicability_receipt_sha256 = {s1_meta['applicability_receipt_sha256']} | "
                    f"declared_unrequested_anisou_count = {s1_meta['unrequested_anisou_count']} "
                    "(evidence-bound applicability declaration; not verified native execution)",
                    "# s1_expected_static_switch_contrast = "
                    f"{_format_phil_scalar(bool(validated_spec['expected_static_switch_contrast']))}",
                ]
            )
        else:
            extra_refine_lines.extend(
                _validate_adp_tls_level_binding(
                    bindings["adp_tls_level_binding"],
                    tier_id=tier_id,
                    d_min=d_min,
                    expected_level_id=None,
                    common_non_adp_strategy=bindings.get("common_non_adp_strategy"),
                )
            )
            if validated_spec.get("comparison_group") == "S3_c_beta_restraints":
                cbeta_pred = predict_static_c_beta_restraints(
                    d_min,
                    bool(validated_spec["factor_level"]),
                    refine_strategy=bindings["adp_tls_level_binding"]["refine_strategy"],
                )
                metadata_comments.append(
                    "# s3_c_beta_static_prediction: "
                    f"requested={_format_phil_scalar(cbeta_pred['requested_c_beta_restraints'])} | "
                    f"static_effective={_format_phil_scalar(bool(cbeta_pred['static_effective_c_beta_restraints']))} | "
                    f"status={cbeta_pred['prediction_status']} "
                    "(static preprocess.py:170-174 predicate; not runtime-measured)"
                )
        if "t4_weight_optimization_policy" in required_keys:
            wt_policy = _validate_t4_weight_policy_binding(
                bindings["t4_weight_optimization_policy"]
            )
            known_phil[OPT_XYZ_WEIGHT_PHIL_PATH] = wt_policy["optimize_xyz_weight"]
            known_phil[OPT_ADP_WEIGHT_PHIL_PATH] = wt_policy["optimize_adp_weight"]
            known_phil[FORCE_OPT_WEIGHTS_PHIL_PATH] = wt_policy["force_optimize_weights"]

    header_lines = [
        "# STATUS: RESULT-FREE STAGE 2 PROSPECTIVE SPECIFICATION — NOT DEVELOPMENT-FROZEN OR RUNTIME-VERIFIED",
        f"# registration_status = {REGISTRATION_STATUS} (NOT frozen_result_free)",
        f"# stage2_status = {STAGE2_SPEC_STATUS}",
        f"# spec_kind = {kind} | tier_id = {tier_id} | d_min = {d_min}",
        *metadata_comments,
    ]

    prep = validated_spec["preprocessing"]
    ready_set_eff: str | None = None
    if prep.get("enabled"):
        rs_lines = [
            *header_lines,
            "# [SCOPE: phenix.ready_set]",
        ]
        for key in sorted(prep["phil_assignments"]):
            val = prep["phil_assignments"][key]
            rs_lines.append(f"{key} = {_format_phil_scalar(val)}")
        for key, formatted_val in extra_ready_set_lines:
            rs_lines.append(f"{key} = {formatted_val}")
        ready_set_eff = "\n".join(rs_lines) + "\n"

    ref_lines = [
        *header_lines,
        "# [SCOPE: phenix.refine]",
    ]
    for key in sorted(known_phil):
        val = known_phil[key]
        ref_lines.append(f"{key} = {_format_phil_scalar(val)}")
    for key, formatted_val in extra_refine_lines:
        ref_lines.append(f"{key} = {formatted_val}")

    refine_eff = "\n".join(ref_lines) + "\n"
    combined = (ready_set_eff + "\n" + refine_eff) if ready_set_eff is not None else refine_eff
    return RenderedEffBundle(
        combined,
        refine_eff=refine_eff,
        ready_set_eff=ready_set_eff,
        is_complete=True,
        comparison_one_factor_verified=False,
    )


_SINGLE_CELL_SENSITIVITY_STATUS_COMMENT = (
    "# single_cell_binding_completeness_only = True | comparison_one_factor_verified = False "
    "(single-cell render_eff checks supplied cell bindings only, not comparison-group "
    "one-factor identity; actual model/native realization remains unverified)"
)
_COMPARISON_VERIFIED_SENSITIVITY_STATUS_COMMENT = (
    "# single_cell_binding_completeness_only = False | comparison_one_factor_verified = True "
    "(verified supplied comparison-group bindings and operative one-factor PHIL diffs only; "
    "actual model/native realization and development-set freeze remain unverified)"
)


def _with_comparison_one_factor_verified(bundle: RenderedEffBundle) -> RenderedEffBundle:
    updated_refine = bundle.refine_eff.replace(
        _SINGLE_CELL_SENSITIVITY_STATUS_COMMENT,
        _COMPARISON_VERIFIED_SENSITIVITY_STATUS_COMMENT,
    )
    updated_ready_set = (
        bundle.ready_set_eff.replace(
            _SINGLE_CELL_SENSITIVITY_STATUS_COMMENT,
            _COMPARISON_VERIFIED_SENSITIVITY_STATUS_COMMENT,
        )
        if bundle.ready_set_eff is not None
        else None
    )
    updated_combined = (
        (updated_ready_set + "\n" + updated_refine)
        if updated_ready_set is not None
        else updated_refine
    )
    return RenderedEffBundle(
        updated_combined,
        refine_eff=updated_refine,
        ready_set_eff=updated_ready_set,
        is_complete=bundle.is_complete,
        comparison_one_factor_verified=True,
    )


def _non_comment_phil_lines(eff_text: str) -> list[str]:
    return [
        line.strip()
        for line in eff_text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _diff_non_comment_phil(eff_a: str, eff_b: str, *, context_label: str) -> list[tuple[str, str]]:
    lines_a = _non_comment_phil_lines(eff_a)
    lines_b = _non_comment_phil_lines(eff_b)
    if len(lines_a) != len(lines_b):
        raise ValueError(
            f"{context_label} rendered non-comment PHIL line counts differ "
            f"({len(lines_a)} vs {len(lines_b)}); non-factor bindings are not identical."
        )
    return [
        (la, lb)
        for la, lb in zip(lines_a, lines_b, strict=True)
        if la != lb
    ]


def validate_factorial_bindings_batch(
    cells: Sequence[Mapping[str, Any]],
    bindings_by_cell: Mapping[str, Mapping[str, Any]] | Sequence[Mapping[str, Any]],
) -> dict[str, RenderedEffBundle]:
    """Validate and render a batch of factorial cells sharing a common non-ADP strategy and CIF contract."""
    if isinstance(cells, (str, bytes, Mapping)) or not isinstance(cells, Sequence) or len(cells) == 0:
        raise ValueError("cells must be a non-empty sequence of factorial_cell specs.")

    validated_cells: list[dict[str, Any]] = []
    seen_cell_ids: set[str] = set()
    for cell in cells:
        canonical = _validate_spec_structure(cell)
        if canonical["kind"] != "factorial_cell":
            raise ValueError(
                f"validate_factorial_bindings_batch requires factorial_cell specs, got {canonical['kind']!r}."
            )
        cid = str(canonical["cell_id"])
        if cid in seen_cell_ids:
            raise ValueError(f"Duplicate factorial cell_id {cid!r} in batch.")
        seen_cell_ids.add(cid)
        validated_cells.append(canonical)

    expected_d_min = validated_cells[0]["d_min"]
    expected_tier = validated_cells[0]["tier_id"]
    for c in validated_cells[1:]:
        if c["d_min"] != expected_d_min or c["tier_id"] != expected_tier:
            raise ValueError("All factorial cells in a batch must share the same d_min and tier_id.")

    if isinstance(bindings_by_cell, Mapping):
        if set(bindings_by_cell.keys()) != seen_cell_ids:
            raise ValueError(
                "bindings_by_cell mapping keys must match the exact cell_id set of cells."
            )
        ordered_bindings = [bindings_by_cell[c["cell_id"]] for c in validated_cells]
    elif not isinstance(bindings_by_cell, (str, bytes)) and isinstance(bindings_by_cell, Sequence):
        if len(bindings_by_cell) != len(validated_cells):
            raise ValueError("bindings_by_cell sequence length must match cells length.")
        ordered_bindings = list(bindings_by_cell)
    else:
        raise ValueError("bindings_by_cell must be a cell_id mapping or a sequence of binding dicts.")

    shared_non_adp: tuple[str, ...] | None = None
    shared_cifs: tuple[dict[str, str], ...] | None = None
    shared_hd_start_meta: dict[str, Any] | None = None
    adp_level_signatures: dict[str, dict[str, Any]] = {}
    rendered_by_id: dict[str, RenderedEffBundle] = {}

    for cell, b in zip(validated_cells, ordered_bindings, strict=True):
        if not isinstance(b, Mapping):
            raise ValueError("Each cell binding entry must be a mapping.")
        adp_b = b.get("adp_tls_level_binding")
        if not isinstance(adp_b, Mapping):
            raise ValueError("Each cell binding must include mapping 'adp_tls_level_binding'.")

        raw_common = (
            b.get("common_non_adp_strategy")
            if "common_non_adp_strategy" in b
            else adp_b.get("common_non_adp_strategy")
        )
        if raw_common is None:
            raise ValueError(
                f"Cell {cell['cell_id']!r} is missing required explicit 'common_non_adp_strategy'."
            )
        cell_common_non_adp = tuple(
            sorted(_validate_common_non_adp_strategy(raw_common))
        )

        if shared_non_adp is None:
            shared_non_adp = cell_common_non_adp
        elif cell_common_non_adp != shared_non_adp:
            raise ValueError(
                f"common_non_adp_strategy varies across factorial cells: "
                f"{shared_non_adp} vs {cell_common_non_adp}."
            )

        rendered = render_eff(cell, b)
        rendered_by_id[cell["cell_id"]] = rendered

        level_id = str(cell["factors"]["adp_tls_mode"])
        sig = normalize_adp_tls_binding_signature(
            adp_b,
            tier_id=str(cell["tier_id"]),
            d_min=float(cell["d_min"]),
            expected_level_id=level_id,
            common_non_adp_strategy=shared_non_adp,
        )
        if level_id not in adp_level_signatures:
            adp_level_signatures[level_id] = sig
        elif adp_level_signatures[level_id] != sig:
            raise ValueError(
                f"Inconsistent ADP/TLS binding for factorial level {level_id!r} across cells."
            )

        cell_h_contract = pure_h_contract(
            b["shared_ligand_cifs"],
            hd_free_start_model_sha256=b["hd_free_start_model_sha256"],
            hd_audit_receipt=b["hd_audit_receipt"],
        )
        cell_cifs = cell_h_contract["shared_ligand_cifs"]
        if shared_cifs is None:
            shared_cifs = cell_cifs
        elif cell_cifs != shared_cifs:
            raise ValueError("shared_ligand_cifs varies across factorial cells in the same batch.")

        cell_hd_meta = cell_h_contract["declared_common_start"]
        if shared_hd_start_meta is None:
            shared_hd_start_meta = cell_hd_meta
        elif cell_hd_meta != shared_hd_start_meta:
            raise ValueError(
                "Common starting model or H/D audit receipt binding varies across factorial cells "
                f"in the same batch: {shared_hd_start_meta!r} vs {cell_hd_meta!r}."
            )

    if len(adp_level_signatures) == 2:
        sigs = [
            {k: v for k, v in s.items() if k != "unrequested_aniso_macromol"}
            for s in adp_level_signatures.values()
        ]
        if sigs[0] == sigs[1]:
            raise ValueError(
                "The two unresolved ADP/TLS factorial levels cannot be bound to equivalent "
                "operative strategy sets and selections (order-only or non-operative metadata "
                "aliases are not distinct ADP/TLS modes)."
            )

    return rendered_by_id


def validate_s1_pair_bindings(
    cells: Sequence[Mapping[str, Any]],
    bindings_by_cell: Mapping[str, Any] | Sequence[Mapping[str, Any]],
) -> dict[str, RenderedEffBundle]:
    """Validate and render the two S1 sensitivity cells (1.5 vs 1.7) at a common d_min.

    Enforces identical starting-model digest, applicability receipt digest, positive
    unrequested ANISOU count, and strategy across both cells, and verifies that the
    rendered .eff files differ ONLY on ``refinement.main.switch_to_isotropic_high_res_limit``.
    """
    if (
        isinstance(cells, (str, bytes, Mapping))
        or not isinstance(cells, Sequence)
        or len(cells) != 2
    ):
        raise ValueError("validate_s1_pair_bindings requires a 2-cell sequence of S1 specs.")

    validated_cells: list[dict[str, Any]] = []
    seen_cell_ids: set[str] = set()
    for cell in cells:
        canonical = _validate_spec_structure(cell)
        if canonical["kind"] != "sensitivity_cell" or canonical.get("arm_family") != "S1":
            raise ValueError(
                "validate_s1_pair_bindings requires sensitivity_cell specs with arm_family == 'S1'."
            )
        cid = str(canonical["cell_id"])
        if cid in seen_cell_ids:
            raise ValueError(f"Duplicate S1 cell_id {cid!r} in pair.")
        seen_cell_ids.add(cid)
        validated_cells.append(canonical)

    if validated_cells[0]["d_min"] != validated_cells[1]["d_min"]:
        raise ValueError("Both S1 cells in a pair must share the exact same d_min.")
    if {float(c["factor_level"]) for c in validated_cells} != {1.5, 1.7}:
        raise ValueError("S1 pair must contain factor_level 1.5 and 1.7.")

    if isinstance(bindings_by_cell, Mapping):
        if set(bindings_by_cell.keys()) == seen_cell_ids and all(
            isinstance(bindings_by_cell[cid], Mapping) for cid in seen_cell_ids
        ):
            ordered_bindings = [bindings_by_cell[c["cell_id"]] for c in validated_cells]
        else:
            ordered_bindings = [bindings_by_cell, bindings_by_cell]
    elif not isinstance(bindings_by_cell, (str, bytes)) and isinstance(bindings_by_cell, Sequence):
        if len(bindings_by_cell) != 2:
            raise ValueError("bindings_by_cell sequence length must be 2 for an S1 pair.")
        ordered_bindings = list(bindings_by_cell)
    else:
        raise ValueError(
            "bindings_by_cell must be a shared binding mapping, a cell_id mapping, or a 2-element sequence."
        )

    metas: list[dict[str, Any]] = []
    rendered_by_id: dict[str, RenderedEffBundle] = {}
    for cell, b in zip(validated_cells, ordered_bindings, strict=True):
        if not isinstance(b, Mapping):
            raise ValueError("Each S1 cell binding entry must be a mapping.")
        _, meta = _validate_s1_preserve_input_adp_binding(
            b.get("adp_tls_level_binding"),
            b,
            common_non_adp_strategy=b.get("common_non_adp_strategy"),
        )
        metas.append(meta)
        rendered_by_id[cell["cell_id"]] = _with_comparison_one_factor_verified(
            render_eff(cell, b)
        )

    if metas[0] != metas[1]:
        raise ValueError(
            f"S1 pair bindings must be identical across both cells; got {metas[0]!r} vs {metas[1]!r}."
        )

    by_level = {float(c["factor_level"]): rendered_by_id[c["cell_id"]] for c in validated_cells}
    lines_1p5 = str(by_level[1.5]).splitlines()
    lines_1p7 = str(by_level[1.7]).splitlines()
    if len(lines_1p5) != len(lines_1p7):
        raise ValueError("Rendered S1 pair .eff outputs have mismatched line counts.")
    diffs = [
        (l1, l2)
        for l1, l2 in zip(lines_1p5, lines_1p7, strict=True)
        if l1 != l2
    ]
    expected_diff = [
        (
            f"{SWITCH_ISO_LIMIT_PHIL_PATH} = 1.5",
            f"{SWITCH_ISO_LIMIT_PHIL_PATH} = 1.7",
        )
    ]
    if diffs != expected_diff:
        raise ValueError(
            f"S1 pair rendered .eff outputs must differ only on {SWITCH_ISO_LIMIT_PHIL_PATH}; "
            f"got diffs {diffs!r}."
        )

    return rendered_by_id


def render_s1_pair(
    d_min: float,
    bindings: Mapping[str, Any] | Sequence[Mapping[str, Any]],
) -> dict[str, RenderedEffBundle]:
    """Schedule and render the S1 (1.5 vs 1.7) sensitivity cell pair at ``d_min``."""
    s1_cells = [c for c in sensitivity_cells(d_min) if c["arm_family"] == "S1"]
    if len(s1_cells) != 2:
        raise ValueError(
            f"d_min={d_min!r} is outside the inclusive S1 [1.50, 1.70] A window."
        )
    return validate_s1_pair_bindings(s1_cells, bindings)


_SENSITIVITY_COMPARISON_GROUP_ALIASES: dict[str, str] = {
    "S1": "S1_switch_to_isotropic_high_res_limit",
    "S1_switch_to_isotropic_high_res_limit": "S1_switch_to_isotropic_high_res_limit",
    "S2": "S2_restraints_library_cdl",
    "S2_restraints_library_cdl": "S2_restraints_library_cdl",
    "S3_c_beta_restraints": "S3_c_beta_restraints",
    "S3_nonbonded_weight": "S3_nonbonded_weight",
    "S4": "S4_t4_low_resolution_restraints_one_by_one",
    "S4_t4_low_resolution_restraints_one_by_one": "S4_t4_low_resolution_restraints_one_by_one",
}


def _normalize_s2_s4_non_factor_binding(
    binding: Mapping[str, Any],
    *,
    tier_id: str,
    d_min: float,
) -> dict[str, Any]:
    adp_b = binding.get("adp_tls_level_binding")
    if not isinstance(adp_b, Mapping):
        raise ValueError("Sensitivity cell binding requires mapping 'adp_tls_level_binding'.")
    adp_phil_lines = tuple(
        _validate_adp_tls_level_binding(
            adp_b,
            tier_id=tier_id,
            d_min=d_min,
            expected_level_id=None,
            common_non_adp_strategy=binding.get("common_non_adp_strategy"),
        )
    )
    strategies = _validate_strategy_list(adp_b["refine_strategy"])
    non_adp_tokens = tuple(tok for tok in strategies if tok not in ADP_TLS_STRATEGY_TOKENS)
    wt_policy = (
        _validate_t4_weight_policy_binding(binding["t4_weight_optimization_policy"])
        if tier_id == "T4"
        else None
    )
    return {
        "level_id": adp_b.get("level_id"),
        "common_non_adp_strategy": non_adp_tokens,
        "refine_strategy": strategies,
        "unrequested_aniso_macromol": bool(adp_b.get("unrequested_aniso_macromol", False)),
        "adp_phil_lines": adp_phil_lines,
        "t4_weight_optimization_policy": wt_policy,
    }


def validate_sensitivity_comparison_bindings(
    cells: Sequence[Mapping[str, Any]],
    bindings_by_cell: Mapping[str, Any] | Sequence[Mapping[str, Any]],
) -> dict[str, RenderedEffBundle]:
    """Validate and render a complete one-factor sensitivity comparison group at a single ``d_min``.

    Supported canonical ``comparison_group`` values:
    - ``S1_switch_to_isotropic_high_res_limit`` (delegates to ``validate_s1_pair_bindings``)
    - ``S2_restraints_library_cdl`` (2 cells: ``cdl_true`` vs ``cdl_false``)
    - ``S3_c_beta_restraints`` (2 cells: ``c_beta_restraints_true`` vs ``c_beta_restraints_false``)
    - ``S3_nonbonded_weight`` (2 cells: ``nonbonded_weight_100`` vs ``nonbonded_weight_16``)
    - ``S4_t4_low_resolution_restraints_one_by_one`` (4 Tier 4 cells: ``all_on`` vs each of
      ``torsion_ncs_off``, ``secondary_structure_off``, ``rotamer_off``)

    Enforces:
    - Exact canonical complete group cell IDs at a single ``d_min`` (rejecting missing,
      duplicate, extra, or mixed-group cells, including combining the two ``S3`` factors).
    - Identical declared non-factor bindings across all cells in the group: ``adp_tls_level_binding``
      (including exact ``refine_strategy``, ``common_non_adp_strategy``, and ADP/TLS selectors)
      and ``t4_weight_optimization_policy`` (in Tier 4).
    - Exact single-factor diffs across non-comment PHIL assignments (for ``S4``, each single
      ablation changes ONLY its named boolean vs ``S4__T4__all_on`` while preserving
      ``refinement.ncs.type = torsion``).
    """
    if (
        isinstance(cells, (str, bytes, Mapping))
        or not isinstance(cells, Sequence)
        or len(cells) == 0
    ):
        raise ValueError(
            "validate_sensitivity_comparison_bindings requires a non-empty sequence of sensitivity_cell specs."
        )

    validated_cells: list[dict[str, Any]] = []
    seen_cell_ids: set[str] = set()
    for cell in cells:
        canonical = _validate_spec_structure(cell)
        if canonical["kind"] != "sensitivity_cell":
            raise ValueError(
                "validate_sensitivity_comparison_bindings requires sensitivity_cell specs, "
                f"got {canonical['kind']!r}."
            )
        cid = str(canonical["cell_id"])
        if cid in seen_cell_ids:
            raise ValueError(f"Duplicate sensitivity cell_id {cid!r} in comparison group.")
        seen_cell_ids.add(cid)
        validated_cells.append(canonical)

    expected_d_min = float(validated_cells[0]["d_min"])
    expected_tier = str(validated_cells[0]["tier_id"])
    comparison_group = str(validated_cells[0]["comparison_group"])
    for c in validated_cells[1:]:
        if float(c["d_min"]) != expected_d_min or str(c["tier_id"]) != expected_tier:
            raise ValueError(
                "All sensitivity cells in a comparison group must share the exact same d_min and tier_id."
            )
        if str(c["comparison_group"]) != comparison_group:
            raise ValueError(
                "Cannot combine sensitivity cells from different comparison_group values "
                f"({comparison_group!r} vs {c['comparison_group']!r}); S2, S3_c_beta_restraints, "
                "S3_nonbonded_weight, and S4 must be validated as separate one-factor comparisons."
            )

    if comparison_group == "S1_switch_to_isotropic_high_res_limit":
        return validate_s1_pair_bindings(validated_cells, bindings_by_cell)

    canonical_group_cells = [
        c
        for c in sensitivity_cells(expected_d_min)
        if c["comparison_group"] == comparison_group
    ]
    expected_group_ids = [str(c["cell_id"]) for c in canonical_group_cells]
    expected_group_id_set = set(expected_group_ids)
    if seen_cell_ids != expected_group_id_set or len(validated_cells) != len(expected_group_ids):
        missing_ids = sorted(expected_group_id_set - seen_cell_ids)
        extra_ids = sorted(seen_cell_ids - expected_group_id_set)
        raise ValueError(
            f"Incomplete or invalid cell set for comparison_group {comparison_group!r} at "
            f"d_min={expected_d_min}: expected canonical complete group {expected_group_ids}, "
            f"missing={missing_ids}, extra={extra_ids}."
        )

    allowed_single_binding_keys = {
        "adp_tls_level_binding",
        "t4_weight_optimization_policy",
        "common_non_adp_strategy",
    }
    if isinstance(bindings_by_cell, Mapping):
        mapping_keys = set(bindings_by_cell.keys())
        if mapping_keys == seen_cell_ids and all(
            isinstance(bindings_by_cell[cid], Mapping) for cid in seen_cell_ids
        ):
            bindings_map: dict[str, Mapping[str, Any]] = {
                cid: bindings_by_cell[cid] for cid in expected_group_ids
            }
        elif mapping_keys and mapping_keys.issubset(allowed_single_binding_keys):
            bindings_map = {cid: bindings_by_cell for cid in expected_group_ids}
        else:
            raise ValueError(
                f"bindings_by_cell mapping keys must either match the canonical group cell_ids "
                f"{expected_group_ids} or be a single shared binding dict; got keys {sorted(mapping_keys)}."
            )
    elif not isinstance(bindings_by_cell, (str, bytes)) and isinstance(bindings_by_cell, Sequence):
        if len(bindings_by_cell) != len(validated_cells):
            raise ValueError(
                f"bindings_by_cell sequence length ({len(bindings_by_cell)}) must match "
                f"canonical group cell count ({len(validated_cells)})."
            )
        seq_map: dict[str, Mapping[str, Any]] = {}
        for c, b_item in zip(validated_cells, bindings_by_cell, strict=True):
            if not isinstance(b_item, Mapping):
                raise ValueError("Each cell binding entry in bindings_by_cell must be a mapping.")
            seq_map[str(c["cell_id"])] = b_item
        bindings_map = {cid: seq_map[cid] for cid in expected_group_ids}
    else:
        raise ValueError(
            "bindings_by_cell must be a shared binding mapping, a cell_id mapping, or a sequence of binding dicts."
        )

    cell_by_id = {str(c["cell_id"]): c for c in canonical_group_cells}
    shared_signature: dict[str, Any] | None = None
    rendered_by_id: dict[str, RenderedEffBundle] = {}

    for cid in expected_group_ids:
        cell = cell_by_id[cid]
        b = bindings_map[cid]
        if not isinstance(b, Mapping):
            raise ValueError(f"Binding for cell {cid!r} must be a mapping.")
        rendered = render_eff(cell, b)
        if rendered.ready_set_eff is not None:
            raise ValueError(f"Sensitivity cell {cid!r} must not emit a ready_set scope.")
        sig = _normalize_s2_s4_non_factor_binding(
            b,
            tier_id=expected_tier,
            d_min=expected_d_min,
        )
        if shared_signature is None:
            shared_signature = sig
        elif sig != shared_signature:
            raise ValueError(
                f"Non-factor bindings vary across cells in sensitivity comparison_group "
                f"{comparison_group!r} (cell {cid!r} differs from group baseline): "
                f"{shared_signature!r} vs {sig!r}."
            )
        rendered_by_id[cid] = _with_comparison_one_factor_verified(rendered)

    if comparison_group == "S2_restraints_library_cdl":
        cid_true = f"S2__{expected_tier}__cdl_true"
        cid_false = f"S2__{expected_tier}__cdl_false"
        diffs = _diff_non_comment_phil(
            rendered_by_id[cid_true].refine_eff,
            rendered_by_id[cid_false].refine_eff,
            context_label=comparison_group,
        )
        expected_diff = [
            (f"{CDL_PHIL_PATH} = True", f"{CDL_PHIL_PATH} = False"),
        ]
        if diffs != expected_diff:
            raise ValueError(
                f"{comparison_group} non-comment PHIL assignments must differ only on "
                f"{CDL_PHIL_PATH}; got {diffs!r}."
            )

    elif comparison_group == "S3_c_beta_restraints":
        cid_true = f"S3__{expected_tier}__c_beta_restraints_true"
        cid_false = f"S3__{expected_tier}__c_beta_restraints_false"
        diffs = _diff_non_comment_phil(
            rendered_by_id[cid_true].refine_eff,
            rendered_by_id[cid_false].refine_eff,
            context_label=comparison_group,
        )
        expected_diff = [
            (
                f"{C_BETA_RESTRAINTS_PHIL_PATH} = True",
                f"{C_BETA_RESTRAINTS_PHIL_PATH} = False",
            ),
        ]
        if diffs != expected_diff:
            raise ValueError(
                f"{comparison_group} non-comment PHIL assignments must differ only on "
                f"{C_BETA_RESTRAINTS_PHIL_PATH}; got {diffs!r}."
            )

    elif comparison_group == "S3_nonbonded_weight":
        cid_100 = f"S3__{expected_tier}__nonbonded_weight_100"
        cid_16 = f"S3__{expected_tier}__nonbonded_weight_16"
        diffs = _diff_non_comment_phil(
            rendered_by_id[cid_100].refine_eff,
            rendered_by_id[cid_16].refine_eff,
            context_label=comparison_group,
        )
        expected_diff = [
            (
                f"{NONBONDED_WEIGHT_PHIL_PATH} = 100",
                f"{NONBONDED_WEIGHT_PHIL_PATH} = 16",
            ),
        ]
        if diffs != expected_diff:
            raise ValueError(
                f"{comparison_group} non-comment PHIL assignments must differ only on "
                f"{NONBONDED_WEIGHT_PHIL_PATH}; got {diffs!r}."
            )

    elif comparison_group == "S4_t4_low_resolution_restraints_one_by_one":
        cid_all_on = "S4__T4__all_on"
        all_on_eff = rendered_by_id[cid_all_on].refine_eff
        all_on_lines = _non_comment_phil_lines(all_on_eff)
        if f"{NCS_TYPE_PHIL_PATH} = torsion" not in all_on_lines:
            raise ValueError(
                f"{cid_all_on} is missing required '{NCS_TYPE_PHIL_PATH} = torsion'."
            )
        s4_ablation_expectations: tuple[tuple[str, str], ...] = (
            ("S4__T4__torsion_ncs_off", TORSION_NCS_SEARCH_ENABLED_PHIL_PATH),
            ("S4__T4__secondary_structure_off", SECONDARY_STRUCTURE_ENABLED_PHIL_PATH),
            ("S4__T4__rotamer_off", ROTAMER_RESTRAINTS_PHIL_PATH),
        )
        for ablation_cid, phil_path in s4_ablation_expectations:
            ablation_eff = rendered_by_id[ablation_cid].refine_eff
            ablation_lines = _non_comment_phil_lines(ablation_eff)
            if f"{NCS_TYPE_PHIL_PATH} = torsion" not in ablation_lines:
                raise ValueError(
                    f"{ablation_cid} must preserve '{NCS_TYPE_PHIL_PATH} = torsion'."
                )
            diffs = _diff_non_comment_phil(
                all_on_eff,
                ablation_eff,
                context_label=f"{cid_all_on}_vs_{ablation_cid}",
            )
            expected_diff = [(f"{phil_path} = True", f"{phil_path} = False")]
            if diffs != expected_diff:
                raise ValueError(
                    f"S4 ablation {ablation_cid!r} vs {cid_all_on!r} must differ only on "
                    f"{phil_path}; got {diffs!r}."
                )
    else:
        raise ValueError(f"Unsupported sensitivity comparison_group {comparison_group!r}.")

    return rendered_by_id


def render_sensitivity_comparison(
    d_min: float,
    comparison_group: str,
    bindings_by_cell: Mapping[str, Any] | Sequence[Mapping[str, Any]],
) -> dict[str, RenderedEffBundle]:
    """Schedule, validate, and render a canonical one-factor sensitivity comparison group at ``d_min``."""
    if not isinstance(comparison_group, str) or not comparison_group.strip():
        raise ValueError("comparison_group must be a non-empty string.")
    key = comparison_group.strip()
    if key == "S3":
        raise ValueError(
            "Ambiguous comparison_group 'S3'; specify 'S3_c_beta_restraints' or "
            "'S3_nonbonded_weight' separately (S3 factors are never combined)."
        )
    if key not in _SENSITIVITY_COMPARISON_GROUP_ALIASES:
        raise ValueError(
            f"Unsupported sensitivity comparison_group {comparison_group!r}; "
            f"allowed: {sorted(_SENSITIVITY_COMPARISON_GROUP_ALIASES)}."
        )
    canonical_group = _SENSITIVITY_COMPARISON_GROUP_ALIASES[key]
    group_cells = [
        c
        for c in sensitivity_cells(d_min)
        if c["comparison_group"] == canonical_group
    ]
    if not group_cells:
        raise ValueError(
            f"Comparison group {canonical_group!r} is not scheduled at d_min={d_min!r}."
        )
    return validate_sensitivity_comparison_bindings(group_cells, bindings_by_cell)
