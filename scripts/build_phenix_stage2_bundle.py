#!/usr/bin/env python3
"""Deterministic builder and verifier for the result-free Stage 2 illustrative bundle.

Generates and checks the synthetic Stage 2 profile, factorial schedule, and
development-exclusion artifact bundle under ``ref/research/data/phenix_stage2_2026-11-16``
(or a caller-supplied ``--output-dir``) using only the Python 3.12 standard library
and the sibling Stage 2 contract modules:

  - ``scripts/phenix_stage2_profiles.py`` (``fixed_profile``, ``render_known_eff_template``,
    ``factorial_cells``, ``resolution_tier``)
  - ``scripts/phenix_stage2_manifest.py`` (``build_dev_exclusions``, ``canonical_json_bytes``,
    ``canonical_json_sha256``)

Hard boundaries enforced by this builder:
  1. No files are written at import time.
  2. No PHENIX/CCP4/Gemmi binaries, vendor Python packages, or network/provider endpoints
     are imported or executed.
  3. Two-program ``Arm 3b-plus-readyset`` templates are emitted as separate
     ``phenix.ready_set`` and ``phenix.refine`` ``.eff.in`` files and are NEVER
     concatenated into a single ``.eff`` file.
  4. All 10 fixed-profile template bundles (15 ``.eff.in`` files) and all 5 factorial
     schedule JSONs (``16, 16, 16, 16, 8`` cells across ``d_min = 0.89, 0.90, 1.10, 1.50, 2.80`` A)
     remain explicitly incomplete (``is_complete = False``, ``adp_tls_levels_resolved = False``)
     and result-free (``registration_status = "selected_decisions_recorded"``,
     ``development_frozen = False``, ``execution_authorized = False``,
     ``frozen_result_free = False``).
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import phenix_stage2_manifest as p2m  # noqa: E402
import phenix_stage2_profiles as p2p  # noqa: E402

REPO_ROOT = SCRIPT_DIR.parent

BUNDLE_SCHEMA_ID = "protstruct_review.phenix_stage2_bundle_manifest.v1"
FACTORIAL_SCHEDULE_SCHEMA_ID = "protstruct_review.phenix_stage2_factorial_schedule.v1"

REGISTRATION_STATUS = "selected_decisions_recorded"
STAGE2_BUNDLE_STATUS = "prospective_spec_not_development_frozen"
DEVELOPMENT_FROZEN = False
EXECUTION_AUTHORIZED = False
FROZEN_RESULT_FREE = False
OUTCOMES_INCLUDED = False

DEFAULT_OUTPUT_RELPATH = "ref/research/data/phenix_stage2_2026-11-16"
BUNDLE_MANIFEST_FILENAME = "bundle_manifest.json"
DEV_EXCLUSIONS_FILENAME = "dev_exclusions.json"

SYNTHETIC_D_MIN_CASES: tuple[tuple[float, str, str, str], ...] = (
    (
        0.89,
        "0.89",
        "0p89A",
        "Sub-0.90 A Tier 1 boundary case (water ADP policy unresolved pending Stage 2 dev test).",
    ),
    (
        0.90,
        "0.90",
        "0p90A",
        "Lower [0.90, 1.10) A Tier 1 boundary case (waters isotropic in [0.90, 1.50) A).",
    ),
    (
        1.10,
        "1.10",
        "1p10A",
        "Tier 1 / Tier 2 cutoff case at d_min = 1.10 A ([1.10, 1.50) A).",
    ),
    (
        1.50,
        "1.50",
        "1p50A",
        "Tier 2 / Tier 3 cutoff case at d_min = 1.50 A ([1.50, 2.80) A; iso+tls).",
    ),
    (
        2.80,
        "2.80",
        "2p80A",
        "Tier 3 / Tier 4 cutoff case at d_min = 2.80 A (>= 2.80 A; sol_on pruned; iso/group+tls).",
    ),
)

FIXED_ARMS: tuple[tuple[str, str], ...] = (
    ("3b-refine-only", "3b_refine_only"),
    ("3b-plus-readyset", "3b_plus_readyset"),
)

EXPECTED_FACTORIAL_CELL_COUNTS: dict[str, int] = {
    "0.89": 16,
    "0.90": 16,
    "1.10": 16,
    "1.50": 16,
    "2.80": 8,
}

STAGE2_MODULE_SPECS: tuple[tuple[str, str, str], ...] = (
    (
        "phenix_stage2_profiles",
        "scripts/phenix_stage2_profiles.py",
        "U04 per-tier fixed profiles, pruned crossed factorial schedule, pure-H contract, and S1-S4 sensitivity specifications.",
    ),
    (
        "phenix_stage2_runtime",
        "scripts/phenix_stage2_runtime.py",
        "U08 8-code status classifier and U12 per-target controller budget/provenance ledger and move-admission guards.",
    ),
    (
        "phenix_stage2_flags",
        "scripts/phenix_stage2_flags.py",
        "U12 fail-closed r_free_flags.generate guard and U08/U09 HKL/R_free/R_sleep membership conservation verifier.",
    ),
    (
        "phenix_stage2_selector",
        "scripts/phenix_stage2_selector.py",
        "U10 holdout-redacted outer-loop candidate selector, T05 guardrails, tie-breaking, stopping rule, and trajectory verifier.",
    ),
    (
        "phenix_stage2_snapshot",
        "scripts/phenix_stage2_snapshot.py",
        "U12 shared dated LLM snapshot binder across Arm 1a and Arm 1b planner subroles (llm, cheap_llm, command_llm).",
    ),
    (
        "phenix_stage2_perturbation",
        "scripts/phenix_stage2_perturbation.py",
        "U05 Track (ii) deterministic seed derivation and 5-component perturbation specification compiler.",
    ),
    (
        "phenix_stage2_manifest",
        "scripts/phenix_stage2_manifest.py",
        "U02/U04 23-accession development exclusion manifest builder and U12 static provider metadata witness inspector.",
    ),
)

BUILDER_RELPATH = "scripts/build_phenix_stage2_bundle.py"

APPROVED_NOTE_RELPATH = "ref/research/phenix_step1_user_selections_2026-11-15.md"
APPROVED_NOTE_EXPECTED_SHA256 = (
    "14bbb0c9dc1883c2404f40193e135a4aaa974d8ab605fe95bb78d44c6a704a7b"
)

STATIC_WITNESS_SPECS: tuple[tuple[str, str, str | None, str], ...] = (
    (
        "phenix_langchain_static_witness",
        "ref/research/data/phenix_langchain_static_witness_2026-11-15.json",
        "692a0b4e082ac5f56622ca6c61b457120efa00542545c12e1672f66c01c9ec0f",
        "U12 static AST/byte witness of 44 Python source files under PHENIX_PREFIX/lib/python3.9/site-packages/libtbx/langchain/.",
    ),
    (
        "phenix_stage2_static_phil_witness",
        "ref/research/data/phenix_stage2_static_phil_witness_2026-11-16.json",
        None,
        "U04 static PHENIX 2.0-5936 PHIL parameter and preprocessing branch witness.",
    ),
    (
        "phenix_stage2_flag_static_witness",
        "ref/research/data/phenix_stage2_flag_static_witness_2026-11-16.json",
        "68a5f2aec79d85bbb68f8a21dd8a66894508b6645a7326dd9e08bfa5b6575d13",
        "U12 static witness of r_free_flags.generate paths across phenix.refine and libtbx.langchain.",
    ),
    (
        "phenix_stage2_provider_metadata_witness",
        "ref/research/data/phenix_stage2_provider_metadata_2026-11-16.json",
        None,
        "U12 read-only static distribution metadata witness under PHENIX_PREFIX/lib/python3.9/site-packages.",
    ),
)

DEV_EXCLUSION_SOURCE_SPECS: tuple[tuple[str, str, str, str], ...] = (
    (
        "negative_control_round2_enrolled",
        "ref/research/data/negative_control_round2_enrolled.json",
        "02fc974da9d1f8a2d8fb3c496c13196c200b31d182f1b7323cb25dcc59cbe7da",
        "Committed 22-entry sub-angstrom Round-2 negative-control development exclusion source.",
    ),
    (
        "refinement_assessment_1sar_and_controls",
        "ref/research/data/refinement_assessment_1sar_and_controls_2026-10-18.json",
        "db100e926bfcf6331c303087846c4d51117a4411c6afdf58877aada5dbf14245",
        "Committed 1SAR development case-study exclusion source with 6 retained subject artifacts.",
    ),
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_regular_file_bytes(path: Path, *, label: str) -> bytes:
    if path.is_symlink():
        raise ValueError(f"Required {label} must be a regular non-symlink file: {path}")
    if not path.exists():
        raise ValueError(f"Missing required {label}: {path}")
    if not path.is_file():
        raise ValueError(f"Required {label} must be a regular non-symlink file: {path}")
    return path.read_bytes()


def _validate_repo_root(repo_root: Path | str) -> Path:
    raw_root = Path(repo_root)
    if raw_root.is_symlink():
        raise ValueError(
            f"Repository root must be a regular non-symlink directory: {raw_root}"
        )
    if not raw_root.exists():
        raise ValueError(f"Repository root does not exist: {raw_root}")
    if not raw_root.is_dir():
        raise ValueError(
            f"Repository root must be a regular non-symlink directory: {raw_root}"
        )
    return raw_root


def _read_repo_regular_file_bytes(
    raw_repo_root: Path, relpath: str, *, label: str
) -> bytes:
    current = raw_repo_root
    parts = Path(relpath).parts
    if not parts:
        raise ValueError(f"Invalid empty relative path for {label}.")
    for part in parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise ValueError(
                f"Required {label} traverses symlinked directory component: {current}"
            )
        if not current.exists() or not current.is_dir():
            raise ValueError(
                f"Missing or non-directory parent for {label}: {current}"
            )
    leaf = current / parts[-1]
    return _read_regular_file_bytes(leaf, label=label)


EXECUTING_BUILDER_PATH = Path(__file__)
EXECUTING_IMPORTED_MODULES: dict[str, Path] = {
    "phenix_stage2_profiles": Path(p2p.__file__),
    "phenix_stage2_manifest": Path(p2m.__file__),
}


def _json_compatible_value(value: Any) -> Any:
    """Convert Stage 2 profile structures (including ResolutionTier and tuples) to plain JSON types."""
    if isinstance(value, p2p.ResolutionTier):
        return value.to_dict()
    if isinstance(value, p2p.RenderedEffBundle):
        return value.to_dict()
    if isinstance(value, Mapping):
        return {str(k): _json_compatible_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_compatible_value(v) for v in value]
    return value


def _collect_source_pins(repo_root: Path) -> dict[str, Any]:
    """Read and hash builder script, Stage 2 modules, approved Step 1 note, and static witnesses.

    Binds the generating implementation strictly to the actual executing builder script
    (``__file__``), the actual imported ``phenix_stage2_profiles`` and
    ``phenix_stage2_manifest`` modules, and the canonical Stage 2 implementation modules.
    Rejects any ``repo_root`` whose builder or Stage 2 module bytes differ from the
    executing implementation.
    """
    raw_repo_root = _validate_repo_root(repo_root)
    canonical_repo_root = _validate_repo_root(REPO_ROOT)

    executing_builder_bytes = _read_regular_file_bytes(
        EXECUTING_BUILDER_PATH, label="executing builder script"
    )
    builder_bytes = _read_repo_regular_file_bytes(
        raw_repo_root, BUILDER_RELPATH, label="builder script"
    )
    if builder_bytes != executing_builder_bytes:
        raise ValueError(
            f"Alternate repo_root builder script ({raw_repo_root / BUILDER_RELPATH}) bytes "
            f"(SHA-256 {_sha256_bytes(builder_bytes)}) differ from actual executing builder "
            f"script ({EXECUTING_BUILDER_PATH}, SHA-256 {_sha256_bytes(executing_builder_bytes)})."
        )
    builder_pin = {
        "relative_path": BUILDER_RELPATH,
        "sha256": _sha256_bytes(executing_builder_bytes),
        "size_bytes": len(executing_builder_bytes),
        "role": "Deterministic Stage 2 result-free illustrative bundle builder and verifier.",
    }

    module_pins: dict[str, dict[str, Any]] = {}
    for mod_id, relpath, role in STAGE2_MODULE_SPECS:
        raw = _read_repo_regular_file_bytes(
            raw_repo_root, relpath, label=f"Stage 2 module {mod_id}"
        )
        canonical_mod_bytes = _read_repo_regular_file_bytes(
            canonical_repo_root, relpath, label=f"canonical Stage 2 module {mod_id}"
        )
        if raw != canonical_mod_bytes:
            raise ValueError(
                f"Alternate repo_root Stage 2 module {mod_id} ({raw_repo_root / relpath}) bytes "
                f"(SHA-256 {_sha256_bytes(raw)}) differ from executing repository module "
                f"({canonical_repo_root / relpath}, SHA-256 {_sha256_bytes(canonical_mod_bytes)})."
            )
        imported_path = EXECUTING_IMPORTED_MODULES.get(mod_id)
        if imported_path is None and mod_id in sys.modules:
            loaded_file = getattr(sys.modules[mod_id], "__file__", None)
            if isinstance(loaded_file, str) and loaded_file:
                imported_path = Path(loaded_file)
        if imported_path is not None:
            imported_bytes = _read_regular_file_bytes(
                imported_path, label=f"imported Stage 2 module {mod_id}"
            )
            if raw != imported_bytes:
                raise ValueError(
                    f"Alternate repo_root Stage 2 module {mod_id} ({raw_repo_root / relpath}) bytes "
                    f"(SHA-256 {_sha256_bytes(raw)}) differ from actual imported module "
                    f"({imported_path}, SHA-256 {_sha256_bytes(imported_bytes)})."
                )
        module_pins[mod_id] = {
            "relative_path": relpath,
            "sha256": _sha256_bytes(raw),
            "size_bytes": len(raw),
            "role": role,
        }

    note_bytes = _read_repo_regular_file_bytes(
        raw_repo_root, APPROVED_NOTE_RELPATH, label="approved Step 1 policy note"
    )
    note_sha = _sha256_bytes(note_bytes)
    if note_sha != APPROVED_NOTE_EXPECTED_SHA256:
        raise ValueError(
            f"Approved policy note {APPROVED_NOTE_RELPATH} SHA-256 mismatch: "
            f"expected {APPROVED_NOTE_EXPECTED_SHA256}, got {note_sha}."
        )
    approved_note_pin = {
        "relative_path": APPROVED_NOTE_RELPATH,
        "sha256": note_sha,
        "size_bytes": len(note_bytes),
        "registration_status": REGISTRATION_STATUS,
        "role": "Approved Step 1 PHENIX scientific policy selections (U01-U14).",
    }

    witness_pins: dict[str, dict[str, Any]] = {}
    for wit_id, relpath, expected_sha, role in STATIC_WITNESS_SPECS:
        raw = _read_repo_regular_file_bytes(
            raw_repo_root, relpath, label=f"static witness {wit_id}"
        )
        canonical_wit_bytes = _read_repo_regular_file_bytes(
            canonical_repo_root, relpath, label=f"canonical static witness {wit_id}"
        )
        sha = _sha256_bytes(raw)
        if expected_sha is not None and sha != expected_sha:
            raise ValueError(
                f"Static witness {relpath} SHA-256 mismatch: expected {expected_sha}, got {sha}."
            )
        if raw != canonical_wit_bytes:
            raise ValueError(
                f"Static witness {relpath} in repo_root ({sha}) differs from executing "
                f"repository witness ({_sha256_bytes(canonical_wit_bytes)})."
            )
        parsed = json.loads(raw.decode("utf-8"))
        if not isinstance(parsed, Mapping):
            raise ValueError(f"Static witness {relpath} must decode to a JSON object.")
        entry: dict[str, Any] = {
            "relative_path": relpath,
            "sha256": sha,
            "size_bytes": len(raw),
            "role": role,
        }
        if "witness_sha256" in parsed:
            payload_without_self = {
                k: v for k, v in parsed.items() if k != "witness_sha256"
            }
            expected_inner = p2m.canonical_json_sha256(payload_without_self)
            if parsed["witness_sha256"] != expected_inner:
                raise ValueError(
                    f"Static witness {relpath} internal witness_sha256 mismatch: "
                    f"recorded {parsed['witness_sha256']!r} != computed {expected_inner!r}."
                )
            entry["witness_sha256"] = parsed["witness_sha256"]
        witness_pins[wit_id] = entry

    dev_source_pins: dict[str, dict[str, Any]] = {}
    for src_id, relpath, expected_sha, role in DEV_EXCLUSION_SOURCE_SPECS:
        raw = _read_repo_regular_file_bytes(
            raw_repo_root, relpath, label=f"development exclusion source {src_id}"
        )
        sha = _sha256_bytes(raw)
        if sha != expected_sha:
            raise ValueError(
                f"Development exclusion source {relpath} SHA-256 mismatch: "
                f"expected {expected_sha}, got {sha}."
            )
        dev_source_pins[src_id] = {
            "relative_path": relpath,
            "sha256": sha,
            "size_bytes": len(raw),
            "role": role,
        }

    return {
        "builder_script": builder_pin,
        "stage2_modules": module_pins,
        "approved_policy_note": approved_note_pin,
        "static_witnesses": witness_pins,
        "development_exclusion_sources": dev_source_pins,
    }


def _build_factorial_schedule_record(
    d_min: float, d_min_label: str, d_min_slug: str, boundary_note: str
) -> dict[str, Any]:
    tier = p2p.resolution_tier(d_min)
    raw_cells = p2p.factorial_cells(d_min)
    expected_count = EXPECTED_FACTORIAL_CELL_COUNTS[d_min_label]
    if len(raw_cells) != expected_count:
        raise ValueError(
            f"factorial_cells({d_min}) returned {len(raw_cells)} cells, expected {expected_count}."
        )
    serialized_cells = [_json_compatible_value(cell) for cell in raw_cells]
    unresolved_levels = [
        f"{tier.tier_id}_adp_tls_level_a_unresolved",
        f"{tier.tier_id}_adp_tls_level_b_unresolved",
    ]
    for cell in serialized_cells:
        if cell.get("adp_tls_level_resolved") is not False:
            raise ValueError(
                f"Factorial cell {cell.get('cell_id')!r} must keep adp_tls_level_resolved=False."
            )
        if cell.get("development_frozen") is not False:
            raise ValueError(
                f"Factorial cell {cell.get('cell_id')!r} must keep development_frozen=False."
            )

    payload: dict[str, Any] = {
        "schema_id": FACTORIAL_SCHEDULE_SCHEMA_ID,
        "registration_status": REGISTRATION_STATUS,
        "stage2_status": STAGE2_BUNDLE_STATUS,
        "development_frozen": DEVELOPMENT_FROZEN,
        "execution_authorized": EXECUTION_AUTHORIZED,
        "frozen_result_free": FROZEN_RESULT_FREE,
        "outcomes_included": OUTCOMES_INCLUDED,
        "synthetic_boundary_case": True,
        "d_min": float(d_min),
        "d_min_label": d_min_label,
        "d_min_slug": d_min_slug,
        "boundary_note": boundary_note,
        "tier_id": tier.tier_id,
        "tier": tier.to_dict(),
        "cell_count": len(serialized_cells),
        "adp_tls_levels_resolved": False,
        "unresolved_adp_tls_levels": unresolved_levels,
        "source_policy": "ref/research/phenix_step1_user_selections_2026-11-15.md#u04",
        "cells": serialized_cells,
    }
    payload["schedule_sha256"] = p2m.canonical_json_sha256(payload)
    return payload


def build_stage2_bundle_payloads(repo_root: Path = REPO_ROOT) -> dict[str, bytes]:
    """Build all 22 deterministic Stage 2 bundle files in memory without writing to disk."""
    raw_repo_root = _validate_repo_root(repo_root)
    source_pins = _collect_source_pins(raw_repo_root)

    files_by_name: dict[str, bytes] = {}
    artifact_entries: list[dict[str, Any]] = []
    fixed_bundle_records: list[dict[str, Any]] = []
    factorial_schedule_records: list[dict[str, Any]] = []

    for d_min, d_min_label, d_min_slug, boundary_note in SYNTHETIC_D_MIN_CASES:
        tier = p2p.resolution_tier(d_min)
        for arm_short, arm_file_slug in FIXED_ARMS:
            spec = p2p.fixed_profile(d_min, arm_short)
            rendered = p2p.render_known_eff_template(spec)
            if rendered.is_complete is not False:
                raise ValueError(
                    f"Known template for d_min={d_min_label}, arm={arm_short} must have is_complete=False."
                )
            if rendered.single_cell_binding_complete is not False:
                raise ValueError(
                    f"Known template for d_min={d_min_label}, arm={arm_short} must have "
                    "single_cell_binding_complete=False."
                )
            if rendered.comparison_one_factor_verified is not False:
                raise ValueError(
                    f"Known template for d_min={d_min_label}, arm={arm_short} must have "
                    "comparison_one_factor_verified=False."
                )

            refine_filename = (
                f"fixed_{tier.tier_id}_{d_min_slug}_{arm_file_slug}_refine.eff.in"
            )
            refine_bytes = rendered.refine_eff.encode("utf-8")
            refine_sha = _sha256_bytes(refine_bytes)
            files_by_name[refine_filename] = refine_bytes
            artifact_entries.append(
                {
                    "relative_path": refine_filename,
                    "bundle_relpath": f"{DEFAULT_OUTPUT_RELPATH}/{refine_filename}",
                    "artifact_kind": "fixed_profile_refine_eff_template",
                    "program_scope": "phenix.refine",
                    "d_min": float(d_min),
                    "d_min_label": d_min_label,
                    "tier_id": tier.tier_id,
                    "arm": arm_short,
                    "arm_id": spec["arm_id"],
                    "is_complete": False,
                    "single_cell_binding_complete": False,
                    "comparison_one_factor_verified": False,
                    "execution_ready_input_bundle": False,
                    "sha256": refine_sha,
                    "size_bytes": len(refine_bytes),
                    "purpose": (
                        f"Incomplete known-PHIL phenix.refine template for {spec['arm_id']} at "
                        f"synthetic d_min = {d_min_label} A ({tier.tier_id}); requires Stage 2 "
                        "per-target ADP/TLS/selection bindings."
                    ),
                    "source_policy": "ref/research/phenix_step1_user_selections_2026-11-15.md#u04",
                }
            )

            ready_set_filename: str | None = None
            ready_set_sha: str | None = None
            if arm_short == "3b-plus-readyset":
                if rendered.ready_set_eff is None:
                    raise ValueError(
                        f"3b-plus-readyset template at d_min={d_min_label} missing ready_set_eff."
                    )
                ready_set_filename = (
                    f"fixed_{tier.tier_id}_{d_min_slug}_{arm_file_slug}_ready_set.eff.in"
                )
                ready_set_bytes = rendered.ready_set_eff.encode("utf-8")
                ready_set_sha = _sha256_bytes(ready_set_bytes)
                files_by_name[ready_set_filename] = ready_set_bytes
                artifact_entries.append(
                    {
                        "relative_path": ready_set_filename,
                        "bundle_relpath": f"{DEFAULT_OUTPUT_RELPATH}/{ready_set_filename}",
                        "artifact_kind": "fixed_profile_ready_set_eff_template",
                        "program_scope": "phenix.ready_set",
                        "d_min": float(d_min),
                        "d_min_label": d_min_label,
                        "tier_id": tier.tier_id,
                        "arm": arm_short,
                        "arm_id": spec["arm_id"],
                        "is_complete": False,
                        "single_cell_binding_complete": False,
                        "comparison_one_factor_verified": False,
                        "execution_ready_input_bundle": False,
                        "sha256": ready_set_sha,
                        "size_bytes": len(ready_set_bytes),
                        "purpose": (
                            f"Separate known-PHIL phenix.ready_set preprocessing template for "
                            f"{spec['arm_id']} at synthetic d_min = {d_min_label} A ({tier.tier_id}); "
                            "kept strictly separate from phenix.refine PHIL."
                        ),
                        "source_policy": "ref/research/phenix_step1_user_selections_2026-11-15.md#u04",
                    }
                )
            else:
                if rendered.ready_set_eff is not None:
                    raise ValueError(
                        f"3b-refine-only template at d_min={d_min_label} must have ready_set_eff=None."
                    )

            fixed_bundle_records.append(
                {
                    "d_min": float(d_min),
                    "d_min_label": d_min_label,
                    "d_min_slug": d_min_slug,
                    "boundary_note": boundary_note,
                    "tier_id": tier.tier_id,
                    "arm": arm_short,
                    "arm_id": spec["arm_id"],
                    "arm_slug": spec["arm_slug"],
                    "is_complete": False,
                    "single_cell_binding_complete": False,
                    "comparison_one_factor_verified": False,
                    "water_adp_policy": spec["water_adp_policy"],
                    "adp_tls_architecture": spec["adp_tls_architecture"],
                    "weight_optimization_policy": spec["weight_optimization_policy"],
                    "refine_eff_path": refine_filename,
                    "refine_eff_sha256": refine_sha,
                    "ready_set_eff_path": ready_set_filename,
                    "ready_set_eff_sha256": ready_set_sha,
                    "required_bindings": dict(spec["required_bindings"]),
                    "unresolved_notes": list(spec["unresolved_notes"]),
                    "source_policy": "ref/research/phenix_step1_user_selections_2026-11-15.md#u04",
                }
            )

        sched_filename = f"factorial_schedule_{tier.tier_id}_{d_min_slug}.json"
        sched_record = _build_factorial_schedule_record(
            d_min, d_min_label, d_min_slug, boundary_note
        )
        sched_bytes = p2m.canonical_json_bytes(sched_record)
        sched_sha = _sha256_bytes(sched_bytes)
        files_by_name[sched_filename] = sched_bytes
        artifact_entries.append(
            {
                "relative_path": sched_filename,
                "bundle_relpath": f"{DEFAULT_OUTPUT_RELPATH}/{sched_filename}",
                "artifact_kind": "factorial_schedule_json",
                "program_scope": None,
                "d_min": float(d_min),
                "d_min_label": d_min_label,
                "tier_id": tier.tier_id,
                "arm": None,
                "arm_id": None,
                "is_complete": False,
                "single_cell_binding_complete": False,
                "comparison_one_factor_verified": False,
                "execution_ready_input_bundle": False,
                "sha256": sched_sha,
                "size_bytes": len(sched_bytes),
                "purpose": (
                    f"U04 resolution-feasible crossed factorial schedule ({sched_record['cell_count']} "
                    f"cells) at synthetic d_min = {d_min_label} A ({tier.tier_id}) with explicit "
                    "unresolved tier ADP/TLS level slots."
                ),
                "source_policy": "ref/research/phenix_step1_user_selections_2026-11-15.md#u04",
            }
        )
        factorial_schedule_records.append(
            {
                "d_min": float(d_min),
                "d_min_label": d_min_label,
                "d_min_slug": d_min_slug,
                "tier_id": tier.tier_id,
                "relative_path": sched_filename,
                "sha256": sched_sha,
                "schedule_sha256": sched_record["schedule_sha256"],
                "cell_count": sched_record["cell_count"],
                "adp_tls_levels_resolved": False,
                "unresolved_adp_tls_levels": list(
                    sched_record["unresolved_adp_tls_levels"]
                ),
                "pruned_solvent_levels": list(
                    sched_record["cells"][0]["pruned_solvent_levels"]
                ),
                "source_policy": "ref/research/phenix_step1_user_selections_2026-11-15.md#u04",
            }
        )

    dev_exclusions = p2m.build_dev_exclusions(raw_repo_root)
    dev_exclusions_bytes = p2m.canonical_json_bytes(dev_exclusions)
    dev_exclusions_sha = _sha256_bytes(dev_exclusions_bytes)
    files_by_name[DEV_EXCLUSIONS_FILENAME] = dev_exclusions_bytes
    artifact_entries.append(
        {
            "relative_path": DEV_EXCLUSIONS_FILENAME,
            "bundle_relpath": f"{DEFAULT_OUTPUT_RELPATH}/{DEV_EXCLUSIONS_FILENAME}",
            "artifact_kind": "dev_exclusions_manifest_json",
            "program_scope": None,
            "d_min": None,
            "d_min_label": None,
            "tier_id": None,
            "arm": None,
            "arm_id": None,
            "is_complete": False,
            "single_cell_binding_complete": False,
            "comparison_one_factor_verified": False,
            "execution_ready_input_bundle": False,
            "sha256": dev_exclusions_sha,
            "size_bytes": len(dev_exclusions_bytes),
            "purpose": (
                "U02/U04 23-accession development exclusion manifest (22 Round-2 sub-angstrom "
                "negative controls + 1 separate identifier-level 1SAR exclusion with 6 retained "
                "subjects); source-attested exclusion inventory, not 23 execution-ready input bundles."
            ),
            "source_policy": "ref/research/phenix_step1_user_selections_2026-11-15.md#u02",
        }
    )

    artifact_entries.sort(key=lambda item: str(item["relative_path"]))

    manifest_payload: dict[str, Any] = {
        "schema_id": BUNDLE_SCHEMA_ID,
        "registration_status": REGISTRATION_STATUS,
        "stage2_status": STAGE2_BUNDLE_STATUS,
        "development_frozen": DEVELOPMENT_FROZEN,
        "execution_authorized": EXECUTION_AUTHORIZED,
        "frozen_result_free": FROZEN_RESULT_FREE,
        "outcomes_included": OUTCOMES_INCLUDED,
        "pass_criterion_bindings_modified": False,
        "bundle_directory": DEFAULT_OUTPUT_RELPATH,
        "summary_counts": {
            "synthetic_d_min_cases": len(SYNTHETIC_D_MIN_CASES),
            "fixed_profile_template_bundles": len(fixed_bundle_records),
            "fixed_profile_eff_in_files": sum(
                1
                for item in artifact_entries
                if item["artifact_kind"]
                in {
                    "fixed_profile_refine_eff_template",
                    "fixed_profile_ready_set_eff_template",
                }
            ),
            "refine_eff_in_files": sum(
                1
                for item in artifact_entries
                if item["artifact_kind"] == "fixed_profile_refine_eff_template"
            ),
            "ready_set_eff_in_files": sum(
                1
                for item in artifact_entries
                if item["artifact_kind"] == "fixed_profile_ready_set_eff_template"
            ),
            "factorial_schedule_files": len(factorial_schedule_records),
            "factorial_cell_counts_by_d_min": {
                rec["d_min_label"]: rec["cell_count"]
                for rec in factorial_schedule_records
            },
            "dev_exclusion_accessions": dev_exclusions["counts"][
                "total_excluded_accessions"
            ],
            "round2_negative_control_accessions": dev_exclusions["counts"][
                "round2_negative_control_accessions"
            ],
            "separate_1sar_accessions": dev_exclusions["counts"][
                "separate_1sar_accessions"
            ],
            "onesar_retained_subject_count": dev_exclusions["counts"][
                "onesar_retained_subject_count"
            ],
            "governed_sibling_artifacts": len(artifact_entries),
            "total_bundle_files_including_manifest": len(artifact_entries) + 1,
        },
        "source_pins": source_pins,
        "fixed_profile_template_bundles": fixed_bundle_records,
        "factorial_schedules": factorial_schedule_records,
        "dev_exclusions_summary": {
            "relative_path": DEV_EXCLUSIONS_FILENAME,
            "sha256": dev_exclusions_sha,
            "manifest_sha256": dev_exclusions["manifest_sha256"],
            "counts": dict(dev_exclusions["counts"]),
            "execution_ready_input_bundle": False,
            "local_bytes_verified": False,
            "source_policy": "ref/research/phenix_step1_user_selections_2026-11-15.md#u02",
        },
        "artifacts": artifact_entries,
    }
    manifest_payload["manifest_sha256"] = p2m.canonical_json_sha256(manifest_payload)
    files_by_name[BUNDLE_MANIFEST_FILENAME] = p2m.canonical_json_bytes(manifest_payload)

    return files_by_name


def _preflight_output_directory(out_path: Path, expected_names: set[str]) -> None:
    """Bounded static preflight for ``out_path`` and all intended destination entries.

    Checks ``out_path``, its ancestor directories, any existing directory entries,
    and all intended destination filenames for symlinks (including dangling links,
    checked via ``is_symlink()`` independently of ``exists()``) and non-regular
    entries before any directory creation or file write occurs.
    """
    if out_path.is_symlink():
        raise ValueError(
            f"Refusing to write Stage 2 bundle to symlinked directory: {out_path}"
        )
    for anc in out_path.parents:
        if anc.is_symlink() and str(anc) not in {"/tmp", "/var", "/etc"}:
            raise ValueError(
                f"Refusing to write Stage 2 bundle under symlinked parent directory: {anc}"
            )
        if anc.is_symlink() and (not anc.exists() or not anc.is_dir()):
            raise ValueError(
                f"Output directory parent is a dangling or non-directory symlink: {anc}"
            )
        if not anc.is_symlink() and anc.exists() and not anc.is_dir():
            raise ValueError(
                f"Output directory parent exists and is not a directory: {anc}"
            )

    if out_path.exists():
        if not out_path.is_dir():
            raise ValueError(f"Output path exists and is not a directory: {out_path}")
        existing_entries = sorted(out_path.iterdir(), key=lambda p: p.name)
        existing_names = {entry.name for entry in existing_entries}
        unexpected = sorted(existing_names - expected_names)
        if unexpected:
            raise ValueError(
                f"Output directory {out_path} contains unexpected extra entries: {unexpected}"
            )
        for entry in existing_entries:
            if entry.is_symlink():
                raise ValueError(
                    f"Refusing to overwrite non-regular file or symlink in bundle directory: {entry}"
                )
            if not entry.is_file():
                raise ValueError(
                    f"Refusing to overwrite non-regular file or symlink in bundle directory: {entry}"
                )

    for filename in sorted(expected_names):
        if (
            not filename
            or "/" in filename
            or "\\" in filename
            or filename in {".", ".."}
            or Path(filename).name != filename
        ):
            raise ValueError(f"Invalid bundle destination filename: {filename!r}")
        target = out_path / filename
        if target.parent != out_path:
            raise ValueError(
                f"Bundle destination path escapes output directory {out_path}: {target}"
            )
        if target.is_symlink():
            raise ValueError(
                f"Refusing to overwrite non-regular file or symlink in bundle directory: {target}"
            )
        if target.exists() and not target.is_file():
            raise ValueError(
                f"Refusing to overwrite non-regular file or symlink in bundle directory: {target}"
            )


def write_stage2_bundle(
    output_dir: Path | str, *, repo_root: Path = REPO_ROOT
) -> dict[str, Any]:
    """Write the deterministic Stage 2 bundle to ``output_dir`` and verify its inventory."""
    raw_repo_root = _validate_repo_root(repo_root)
    out_path = Path(output_dir)
    if out_path.is_symlink():
        raise ValueError(f"Refusing to write Stage 2 bundle to symlinked directory: {out_path}")
    if out_path.exists() and not out_path.is_dir():
        raise ValueError(f"Output path exists and is not a directory: {out_path}")

    payloads = build_stage2_bundle_payloads(raw_repo_root)
    expected_names = set(payloads.keys())

    _preflight_output_directory(out_path, expected_names)

    if not out_path.exists():
        out_path.mkdir(parents=True, exist_ok=True)
        if out_path.is_symlink() or not out_path.is_dir():
            raise ValueError(
                f"Output path must be a regular non-symlink directory: {out_path}"
            )

    _preflight_output_directory(out_path, expected_names)

    for filename in sorted(payloads.keys()):
        target = out_path / filename
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise ValueError(
                f"Refusing to overwrite non-regular file or symlink in bundle directory: {target}"
            )
        target.write_bytes(payloads[filename])

    return verify_stage2_bundle(out_path, repo_root=raw_repo_root)


def verify_stage2_bundle(
    bundle_dir: Path | str, *, repo_root: Path = REPO_ROOT
) -> dict[str, Any]:
    """Verify an existing Stage 2 bundle directory against deterministic payloads and source pins.

    Fails closed (raising ``ValueError``) if:
      - ``bundle_dir`` is missing, not a directory, or a symlink;
      - any expected file is missing, is a symlink/non-regular file, or has stale bytes;
      - any unexpected extra file or subdirectory is present;
      - ``bundle_manifest.json`` internal ``manifest_sha256``, artifact hashes, or source pins
        disagree with current repository source files;
      - any governance flag attempts to promote ``registration_status`` or set
        ``development_frozen``, ``execution_authorized``, ``frozen_result_free``,
        or ``outcomes_included`` to ``True``.
    """
    raw_repo_root = _validate_repo_root(repo_root)
    bdir = Path(bundle_dir)
    if bdir.is_symlink():
        raise ValueError(f"Stage 2 bundle path must be a regular non-symlink directory: {bdir}")
    if not bdir.exists():
        raise ValueError(f"Stage 2 bundle directory does not exist: {bdir}")
    if not bdir.is_dir():
        raise ValueError(f"Stage 2 bundle path must be a regular non-symlink directory: {bdir}")

    expected_payloads = build_stage2_bundle_payloads(raw_repo_root)
    expected_names = set(expected_payloads.keys())

    actual_entries = list(bdir.iterdir())
    actual_names = {entry.name for entry in actual_entries}

    missing = sorted(expected_names - actual_names)
    if missing:
        raise ValueError(f"Stage 2 bundle directory {bdir} is missing required files: {missing}")

    extra = sorted(actual_names - expected_names)
    if extra:
        raise ValueError(f"Stage 2 bundle directory {bdir} contains unexpected extra files: {extra}")

    for entry in sorted(actual_entries, key=lambda p: p.name):
        if entry.is_symlink() or not entry.is_file():
            raise ValueError(
                f"Stage 2 bundle entry must be a regular non-symlink file: {entry}"
            )

    manifest_path = bdir / BUNDLE_MANIFEST_FILENAME
    manifest_raw = manifest_path.read_bytes()
    try:
        manifest_doc = json.loads(manifest_raw.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to parse {manifest_path}: {exc}") from exc
    if not isinstance(manifest_doc, Mapping):
        raise ValueError(f"{manifest_path} must contain a top-level JSON object.")

    if manifest_doc.get("registration_status") != REGISTRATION_STATUS:
        raise ValueError(
            f"Invalid registration_status in {manifest_path}: {manifest_doc.get('registration_status')!r}"
        )
    for flag_key in (
        "development_frozen",
        "execution_authorized",
        "frozen_result_free",
        "outcomes_included",
        "pass_criterion_bindings_modified",
    ):
        if manifest_doc.get(flag_key) is not False:
            raise ValueError(
                f"{manifest_path} must keep {flag_key}=False, got {manifest_doc.get(flag_key)!r}."
            )

    manifest_without_self = {
        k: v for k, v in manifest_doc.items() if k != "manifest_sha256"
    }
    computed_manifest_sha = p2m.canonical_json_sha256(manifest_without_self)
    if manifest_doc.get("manifest_sha256") != computed_manifest_sha:
        raise ValueError(
            f"{manifest_path} manifest_sha256 mismatch: recorded "
            f"{manifest_doc.get('manifest_sha256')!r} != computed {computed_manifest_sha!r}."
        )

    expected_manifest_doc = json.loads(
        expected_payloads[BUNDLE_MANIFEST_FILENAME].decode("utf-8")
    )
    if manifest_doc.get("source_pins") != expected_manifest_doc["source_pins"]:
        raise ValueError(
            f"{manifest_path} source_pins are stale or do not match current repository sources."
        )

    recorded_artifacts = manifest_doc.get("artifacts")
    if not isinstance(recorded_artifacts, list):
        raise ValueError(f"{manifest_path} artifacts field must be a list.")
    recorded_by_path: dict[str, Mapping[str, Any]] = {}
    for item in recorded_artifacts:
        if not isinstance(item, Mapping) or not isinstance(item.get("relative_path"), str):
            raise ValueError(f"Malformed artifact entry in {manifest_path}: {item!r}")
        rel = item["relative_path"]
        if rel in recorded_by_path:
            raise ValueError(f"Duplicate artifact relative_path in {manifest_path}: {rel!r}")
        recorded_by_path[rel] = item

    expected_sibling_names = expected_names - {BUNDLE_MANIFEST_FILENAME}
    if set(recorded_by_path.keys()) != expected_sibling_names:
        raise ValueError(
            f"{manifest_path} artifact inventory mismatch: expected {sorted(expected_sibling_names)}, "
            f"got {sorted(recorded_by_path.keys())}."
        )

    for filename, expected_bytes in sorted(expected_payloads.items()):
        actual_bytes = (bdir / filename).read_bytes()
        actual_sha = _sha256_bytes(actual_bytes)
        expected_sha = _sha256_bytes(expected_bytes)
        if filename != BUNDLE_MANIFEST_FILENAME:
            rec = recorded_by_path[filename]
            if rec.get("sha256") != actual_sha:
                raise ValueError(
                    f"Artifact {filename} on-disk SHA-256 ({actual_sha}) disagrees with "
                    f"bundle_manifest.json ({rec.get('sha256')!r})."
                )
        if actual_bytes != expected_bytes:
            raise ValueError(
                f"Stage 2 bundle file {filename} bytes are stale or modified "
                f"(expected SHA-256 {expected_sha}, got {actual_sha})."
            )

    return dict(manifest_doc)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate or verify the deterministic result-free Stage 2 PHENIX artifact bundle."
        )
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / DEFAULT_OUTPUT_RELPATH,
        help=(
            "Target directory for generating or checking the Stage 2 bundle "
            f"(default: {DEFAULT_OUTPUT_RELPATH})."
        ),
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root directory containing Stage 2 modules and static witnesses.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify that --output-dir matches the deterministic Stage 2 bundle without writing.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    if args.check:
        verify_stage2_bundle(args.output_dir, repo_root=args.repo_root)
    else:
        write_stage2_bundle(args.output_dir, repo_root=args.repo_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
