#!/usr/bin/env python3
"""Reusable before/after refinement assessment workflow and control evaluator.

This module and CLI separate three distinct questions that were previously
conflated in single-table refinement summaries:

1. Implementation agreement (`implementation_agreement`):
   Do independent software implementations agree on the same observable when
   applied to the same model and reflection set?
2. Final-model quality support (`final_model_quality_support`):
   What absolute measurements support the final model's suitability for its
   intended downstream use?
3. Change relative to input (`change_relative_to_input`):
   What improved, remained invariant, or regressed relative to the actual
   starting model and input reflection data?

In addition, every assessment record carries:
- Explicit provenance (`subject_ref`, SHA-256 digests, atom/residue/water/ligand
  inventories, reflection-retention audit, and tool versions).
- Explicit `missing_conflicting_and_inapplicable_evidence` entries so absent
  artifacts (such as the unarchived 1SAR round-7 model), inapplicable clauses
  (such as null deposited R-free or merged-MTZ `aimless`), and cross-solver
  scaling offsets are never silently smoothed over.
- Explicit `pass_criterion_bindings`: whenever `pass_criterion_bindings` is
  empty (`[]`), `assessment_verdict_status` is forced to `"informational"`
  rather than emitting an uncalibrated pass/fail verdict; non-empty bindings
  and unknown `requested_status` values raise `ValueError` until criterion
  evaluation is implemented.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import sys
from typing import Any
import zipfile

import numpy as np
import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from audit_1sar_retained_evidence import ARCHIVE, pdb_atoms  # noqa: E402
from t03_reflection_retention import (  # noqa: E402
    audit_mtz_retention,
    deposition_applicability,
)

DEFAULT_ARCHIVE = REPO_ROOT / ARCHIVE
DEFAULT_DEPOSITED_PDB = REPO_ROOT / "data/pdb_mtz/1sar_deposited.pdb"
DEFAULT_1SAR_QDS = (
    REPO_ROOT / "data/coscientists/openscientist/QDS_1sar_cdba2c07_2026-09-23.yaml"
)
DEFAULT_1SAR_EVAL = (
    REPO_ROOT / "data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-09-23.yaml"
)
DEFAULT_1SAR_COORD_AUDIT = (
    REPO_ROOT
    / "data/coscientists/openscientist/retained_evidence_2026-09-23/coordinate_and_t13_audit.json"
)
DEFAULT_ROUND3_BENCH = REPO_ROOT / "ref/research/data/negative_control_round3_bench.json"
DEFAULT_ROUND4_RECOVER = (
    REPO_ROOT / "ref/research/data/negative_control_round4_recover.json"
)
DEFAULT_ROUND10_RECOVER = (
    REPO_ROOT / "ref/research/data/negative_control_round10_recover.json"
)

STANDARD_AMINO_ACIDS = frozenset(
    {
        "ALA",
        "ARG",
        "ASN",
        "ASP",
        "CYS",
        "GLN",
        "GLU",
        "GLY",
        "HIS",
        "ILE",
        "LEU",
        "LYS",
        "MET",
        "PHE",
        "PRO",
        "SER",
        "THR",
        "TRP",
        "TYR",
        "VAL",
    }
)


EXPECTED_1SAR_ARCHIVE_SHA256 = (
    "9fc5352284b7ffa7763c633a3eb4d3d0db96b8c25a1be9bcea361722d2c53054"
)
EXPECTED_1SAR_DEPOSITED_PDB_SHA256 = (
    "e60e5db6c7eb554a3ac4e184bdf7cbb7d69b682e287579bdcf5f8bf279d51f86"
)
EXPECTED_1SAR_QDS_SHA256 = (
    "4548cb4c36355938687ffef840ecb0b3a9b91c9eacad2157bc1124d962d82db2"
)
EXPECTED_1SAR_EVAL_SHA256 = (
    "1d971c69997d19456d288fa5882547bcdde608c689407d275186f2319a1ae310"
)
EXPECTED_1SAR_COORD_AUDIT_SHA256 = (
    "5a03ab678c26970a4a1bdeaf5742ed46a6bd7ffd982ac22d656c1a0b5189cbdf"
)
EXPECTED_ROUND3_BENCH_SHA256 = (
    "3635bd878d160c770594c2c5ed92a1139dbbd8d63daa28a48aa249656d7f6dee"
)
EXPECTED_ROUND4_RECOVER_SHA256 = (
    "dee4b3994c81ec2e5aecfe86569c36b720f8fd0a9c04581dc96585edb275afdf"
)
EXPECTED_ROUND10_RECOVER_SHA256 = (
    "1c6e710e87bb08c23d77b1fa3a7aea2fe18a136b00cec6d35d40e2d171b78bb7"
)
EXPECTED_1SAR_START_SUBJECT_REF = (
    "artifact:cdba2c07-daff-4f60-ae96-12452b3a5fbb#data/1sar.pdb"
)
EXPECTED_1SAR_FINAL_SUBJECT_REF = (
    "artifact:cdba2c07-daff-4f60-ae96-12452b3a5fbb#data/1sar_final.pdb"
)
EXPECTED_1SAR_MTZ_SUBJECT_REF = (
    "mtz:sha256:f36d5fe685a3e524e8809d17d19ce12073acdf339eba2cfd3b0347a818850ab2"
)
VALID_VERDICT_STATUSES = frozenset({"pass", "fail", "NeedsReview", "informational"})


def _require_finite_float(raw_val: Any, context: str) -> float:
    """Convert raw_val to float and reject None, booleans, NaN, and Inf."""
    if raw_val is None or isinstance(raw_val, (bool, np.bool_)):
        raise ValueError(f"Missing or non-numeric value for {context}: {raw_val!r}")
    try:
        val = float(raw_val)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid numeric value for {context}: {raw_val!r}") from exc
    if not math.isfinite(val):
        raise ValueError(f"Non-finite numeric value for {context}: {raw_val!r}")
    return val


def _require_finite_int(raw_val: Any, context: str) -> int:
    """Convert raw_val to an exact integer and reject None, booleans, NaN, and Inf."""
    val = _require_finite_float(raw_val, context)
    if not val.is_integer():
        raise ValueError(f"Non-integer numeric value for {context}: {raw_val!r}")
    return int(val)


def _display_path(path: Path) -> str:
    """Return a repository-relative path string when inside REPO_ROOT, else str(path)."""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def sha256_bytes(data: bytes) -> str:
    """Return the hex SHA-256 digest of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 digest of a file on disk."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def kabsch_rmsd(coords_a: np.ndarray, coords_b: np.ndarray) -> float:
    """Return the optimal right-handed Kabsch-superposed RMSD in Angstroms."""
    arr_a = np.asarray(coords_a, dtype=float)
    arr_b = np.asarray(coords_b, dtype=float)
    if arr_a.shape != arr_b.shape or arr_a.ndim != 2 or arr_a.shape[1] != 3:
        raise ValueError("kabsch_rmsd requires matching (N, 3) coordinate arrays")
    if arr_a.shape[0] == 0:
        raise ValueError("kabsch_rmsd requires at least one atom")
    if not (np.all(np.isfinite(arr_a)) and np.all(np.isfinite(arr_b))):
        raise ValueError("kabsch_rmsd requires finite coordinate arrays")
    centered_a = arr_a - np.mean(arr_a, axis=0)
    centered_b = arr_b - np.mean(arr_b, axis=0)
    cov = centered_a.T @ centered_b
    u_mat, _, vt_mat = np.linalg.svd(cov)
    det_sign = 1.0 if np.linalg.det(u_mat @ vt_mat) >= 0.0 else -1.0
    correction = np.diag([1.0, 1.0, det_sign])
    rotation = u_mat @ correction @ vt_mat
    aligned_a = centered_a @ rotation
    diffs = aligned_a - centered_b
    rmsd = float(np.sqrt(np.mean(np.sum(diffs * diffs, axis=1))))
    if not math.isfinite(rmsd):
        raise ValueError("kabsch_rmsd produced a non-finite RMSD")
    return rmsd


def resolve_verdict_status(
    pass_criterion_bindings: list[dict[str, Any]] | None,
    requested_status: str | None = None,
) -> str:
    """Enforce informational status whenever pass_criterion_bindings is empty.

    Until pass_criterion_bindings evaluation is implemented, non-empty
    pass_criterion_bindings are rejected with ValueError so caller-supplied
    requested_status values cannot bypass criterion evaluation. Unknown
    non-None requested_status strings are also rejected with ValueError.
    """
    if requested_status is not None and requested_status not in VALID_VERDICT_STATUSES:
        raise ValueError(
            f"Unknown requested_status {requested_status!r}; expected one of "
            f"{sorted(VALID_VERDICT_STATUSES)} or None"
        )
    if pass_criterion_bindings:
        raise ValueError(
            "Non-empty pass_criterion_bindings are not yet supported: "
            "resolve_verdict_status does not evaluate pass criteria and refuses "
            "to echo caller-supplied requested_status values."
        )
    return "informational"


def summarize_pdb_inventory(pdb_text: str) -> dict[str, Any]:
    """Summarize atom, residue, water, and non-water heteroatom inventory."""
    atoms = pdb_atoms(pdb_text)
    protein_atoms = [a for a in atoms if a["key"][3] in STANDARD_AMINO_ACIDS]
    water_atoms = [a for a in atoms if a["key"][3] in {"HOH", "WAT"}]
    hetero_atoms = [
        a
        for a in atoms
        if a["key"][3] not in STANDARD_AMINO_ACIDS
        and a["key"][3] not in {"HOH", "WAT"}
    ]

    protein_residues = sorted(
        {
            (a["key"][0], int(a["key"][1]), a["key"][2], a["key"][3])
            for a in protein_atoms
        }
    )
    chains: dict[str, int] = {}
    for chain_id, _, _, _ in protein_residues:
        chains[chain_id] = chains.get(chain_id, 0) + 1

    hetero_groups: dict[str, list[dict[str, Any]]] = {}
    for atom in hetero_atoms:
        chain_id, resseq_str, icode, resname, _ = atom["key"]
        key = f"{chain_id}:{resseq_str}{icode}:{resname}"
        hetero_groups.setdefault(key, []).append(atom)

    hetero_summary = []
    for key in sorted(hetero_groups):
        group = hetero_groups[key]
        b_vals = [float(a["b_factor"]) for a in group]
        hetero_summary.append(
            {
                "group_id": key,
                "atom_count": len(group),
                "mean_b_iso": round(float(np.mean(b_vals)), 3),
                "min_b_iso": round(float(np.min(b_vals)), 3),
                "max_b_iso": round(float(np.max(b_vals)), 3),
            }
        )

    def _b_stats(rows: list[dict[str, Any]]) -> dict[str, float | None]:
        if not rows:
            return {"mean": None, "median": None, "min": None, "max": None}
        vals = [float(r["b_factor"]) for r in rows]
        return {
            "mean": round(float(np.mean(vals)), 3),
            "median": round(float(np.median(vals)), 3),
            "min": round(float(np.min(vals)), 3),
            "max": round(float(np.max(vals)), 3),
        }

    return {
        "total_non_hydrogen_atoms": len(atoms),
        "protein_atom_count": len(protein_atoms),
        "protein_residue_count": len(protein_residues),
        "protein_residues_by_chain": chains,
        "water_atom_count": len(water_atoms),
        "non_water_hetero_atom_count": len(hetero_atoms),
        "non_water_hetero_groups": hetero_summary,
        "b_factor_summary": {
            "all_atoms": _b_stats(atoms),
            "protein_atoms": _b_stats(protein_atoms),
            "water_atoms": _b_stats(water_atoms),
            "non_water_hetero_atoms": _b_stats(hetero_atoms),
        },
    }


def compare_pdb_pair(start_pdb_text: str, final_pdb_text: str) -> dict[str, Any]:
    """Compare starting and final PDB models across coordinates, B-factors, and inventory."""
    start_atoms = pdb_atoms(start_pdb_text)
    final_atoms = pdb_atoms(final_pdb_text)

    def _atom_key(atom: dict[str, Any]) -> tuple[str, int, str, str, str]:
        chain_id, resseq_str, icode, resname, atom_name = atom["key"]
        return (chain_id, int(resseq_str), icode, resname, atom_name)

    start_map = {_atom_key(a): a for a in start_atoms}
    final_map = {_atom_key(a): a for a in final_atoms}

    shared_keys = sorted(set(start_map).intersection(final_map))
    added_keys = sorted(set(final_map) - set(start_map))
    removed_keys = sorted(set(start_map) - set(final_map))

    shared_protein_keys = [k for k in shared_keys if k[3] in STANDARD_AMINO_ACIDS]
    shared_ca_keys = [k for k in shared_protein_keys if k[4] == "CA"]

    def _unsuperposed_metrics(
        keys: list[tuple[str, int, str, str, str]],
    ) -> dict[str, Any]:
        if not keys:
            return {
                "atom_count": 0,
                "unsuperposed_rmsd_angstrom": None,
                "mean_shift_angstrom": None,
                "median_shift_angstrom": None,
                "p95_shift_angstrom": None,
                "max_shift_angstrom": None,
                "max_shift_atom": None,
                "mean_delta_b_iso": None,
                "median_delta_b_iso": None,
            }
        start_xyz = np.array([start_map[k]["xyz"] for k in keys], dtype=float)
        final_xyz = np.array([final_map[k]["xyz"] for k in keys], dtype=float)
        diffs = final_xyz - start_xyz
        dists = np.linalg.norm(diffs, axis=1)
        max_idx = int(np.argmax(dists))
        max_key = keys[max_idx]
        b_deltas = np.array(
            [
                float(final_map[k]["b_factor"]) - float(start_map[k]["b_factor"])
                for k in keys
            ],
            dtype=float,
        )
        return {
            "atom_count": len(keys),
            "unsuperposed_rmsd_angstrom": round(
                float(np.sqrt(np.mean(np.sum(diffs * diffs, axis=1)))), 4
            ),
            "mean_shift_angstrom": round(float(np.mean(dists)), 4),
            "median_shift_angstrom": round(float(np.median(dists)), 4),
            "p95_shift_angstrom": round(float(np.percentile(dists, 95)), 4),
            "max_shift_angstrom": round(float(dists[max_idx]), 4),
            "max_shift_atom": (
                f"{max_key[0]}:{max_key[1]}{max_key[2]}:{max_key[3]}:{max_key[4]}"
            ),
            "mean_delta_b_iso": round(float(np.mean(b_deltas)), 4),
            "median_delta_b_iso": round(float(np.median(b_deltas)), 4),
        }

    ca_superposed_all: float | None = None
    if shared_ca_keys:
        start_ca_xyz = np.array(
            [start_map[k]["xyz"] for k in shared_ca_keys], dtype=float
        )
        final_ca_xyz = np.array(
            [final_map[k]["xyz"] for k in shared_ca_keys], dtype=float
        )
        ca_superposed_all = round(kabsch_rmsd(start_ca_xyz, final_ca_xyz), 4)

    chain_ca_summary: dict[str, dict[str, Any]] = {}
    chains = sorted({k[0] for k in shared_ca_keys})
    for chain_id in chains:
        ckeys = [k for k in shared_ca_keys if k[0] == chain_id]
        s_xyz = np.array([start_map[k]["xyz"] for k in ckeys], dtype=float)
        f_xyz = np.array([final_map[k]["xyz"] for k in ckeys], dtype=float)
        unsuperposed = _unsuperposed_metrics(ckeys)
        chain_ca_summary[chain_id] = {
            "ca_count": len(ckeys),
            "kabsch_superposed_ca_rmsd_angstrom": round(kabsch_rmsd(s_xyz, f_xyz), 4),
            "unsuperposed_ca_rmsd_angstrom": unsuperposed["unsuperposed_rmsd_angstrom"],
            "mean_ca_shift_angstrom": unsuperposed["mean_shift_angstrom"],
            "max_ca_shift_angstrom": unsuperposed["max_shift_angstrom"],
            "max_ca_shift_atom": unsuperposed["max_shift_atom"],
        }

    added_waters = [k for k in added_keys if k[3] in {"HOH", "WAT"}]
    removed_waters = [k for k in removed_keys if k[3] in {"HOH", "WAT"}]
    added_non_water = [
        f"{k[0]}:{k[1]}{k[2]}:{k[3]}:{k[4]}"
        for k in added_keys
        if k[3] not in {"HOH", "WAT"}
    ]
    removed_non_water = [
        f"{k[0]}:{k[1]}{k[2]}:{k[3]}:{k[4]}"
        for k in removed_keys
        if k[3] not in {"HOH", "WAT"}
    ]

    return {
        "shared_all_heavy_atoms": _unsuperposed_metrics(shared_keys),
        "shared_protein_heavy_atoms": _unsuperposed_metrics(shared_protein_keys),
        "shared_ca_atoms": {
            **_unsuperposed_metrics(shared_ca_keys),
            "kabsch_superposed_ca_rmsd_angstrom": ca_superposed_all,
            "by_chain": chain_ca_summary,
        },
        "inventory_deltas": {
            "added_total_atoms": len(added_keys),
            "removed_total_atoms": len(removed_keys),
            "added_water_atoms": len(added_waters),
            "removed_water_atoms": len(removed_waters),
            "added_non_water_atoms": added_non_water,
            "removed_non_water_atoms": removed_non_water,
        },
    }


def _parse_deposited_r_values(
    pdb_path: Path,
    *,
    pdb_text: str | None = None,
    require_1sar_header: bool = False,
) -> dict[str, Any]:
    """Parse REMARK 3 R VALUE and FREE R VALUE lines from a deposited PDB header."""
    text = (
        pdb_text
        if pdb_text is not None
        else pdb_path.read_text(encoding="utf-8", errors="replace")
    )
    r_work: float | None = None
    r_free: float | None = None
    raw_lines: list[str] = []
    has_1sar_header = False
    for line in text.splitlines():
        if line.startswith("HEADER") and "1SAR" in line:
            has_1sar_header = True
        if line.startswith("REMARK   3   R VALUE") or line.startswith(
            "REMARK   3   FREE R VALUE"
        ):
            raw_lines.append(line.strip())
            if ":" in line:
                head, tail = line.split(":", 1)
                token = tail.strip().split()[0] if tail.strip() else "NULL"
                if (
                    "FREE R VALUE" in head
                    and "TEST SET" not in head
                    and "ERROR" not in head
                ):
                    if token.upper() in {"NULL", "NONE", "N/A", "."}:
                        r_free = None
                    else:
                        r_free = _require_finite_float(
                            token, f"{pdb_path} REMARK 3 FREE R VALUE"
                        )
                elif "R VALUE" in head and "FREE" not in head and "ERROR" not in head:
                    if token.upper() in {"NULL", "NONE", "N/A", "."}:
                        r_work = None
                    else:
                        r_work = _require_finite_float(
                            token, f"{pdb_path} REMARK 3 R VALUE"
                        )
    if require_1sar_header:
        if not has_1sar_header:
            raise ValueError(
                f"Deposited PDB {pdb_path} is missing expected HEADER for 1SAR"
            )
        if r_work is not None or r_free is not None:
            raise ValueError(
                f"Deposited PDB {pdb_path} R-work={r_work!r} or R-free={r_free!r} "
                "does not match expected NULL working/free R values for 1SAR"
            )
        required_1sar_lines = (
            "REMARK   3   R VALUE     (WORKING + TEST SET) : 0.172",
            "REMARK   3   R VALUE            (WORKING SET) : NULL",
            "REMARK   3   FREE R VALUE                     : NULL",
        )
        for req_line in required_1sar_lines:
            if req_line not in raw_lines:
                raise ValueError(
                    f"Deposited PDB {pdb_path} is missing expected REMARK 3 line {req_line!r}"
                )
    return {
        "deposited_r_work": r_work,
        "deposited_r_free": r_free,
        "deposition_applicability": deposition_applicability(r_free),
        "header_lines": raw_lines,
    }


def _validate_eval_measurement_context(
    row: dict[str, Any],
    measurement_id: str,
    *,
    expected_task_ref: str | None = None,
    expected_metric_ref: str | None = None,
    expected_oracle_ref: str | None = None,
    expected_stage: str | None = None,
    expected_subject_ref: str | None = None,
) -> None:
    """Validate semantic context fields on an EvaluationRun measurement row."""
    for required_field in (
        "catalog_task_ref",
        "metric_definition_ref",
        "oracle_tool_ref",
        "stage",
        "subject_ref",
    ):
        val = row.get(required_field)
        if not isinstance(val, str) or not val.strip():
            raise ValueError(
                f"Measurement {measurement_id!r} missing non-empty {required_field!r}"
            )
    checks = (
        ("catalog_task_ref", expected_task_ref),
        ("metric_definition_ref", expected_metric_ref),
        ("oracle_tool_ref", expected_oracle_ref),
        ("stage", expected_stage),
        ("subject_ref", expected_subject_ref),
    )
    for field_name, expected_val in checks:
        if expected_val is not None and row.get(field_name) != expected_val:
            raise ValueError(
                f"Measurement {measurement_id!r} {field_name}={row.get(field_name)!r} "
                f"does not match expected {expected_val!r}"
            )


def _require_eval_numeric(
    measurements_by_id: dict[str, dict[str, Any]],
    measurement_id: str,
    expected: float,
    *,
    tol: float = 1e-4,
    expected_task_ref: str | None = None,
    expected_metric_ref: str | None = None,
    expected_oracle_ref: str | None = None,
    expected_stage: str | None = None,
    expected_subject_ref: str | None = None,
) -> float:
    """Return a validated finite numeric measurement from an EvaluationRun."""
    expected_val = _require_finite_float(expected, f"{measurement_id}.expected")
    tol_val = _require_finite_float(tol, f"{measurement_id}.tol")
    row = measurements_by_id.get(measurement_id)
    if not isinstance(row, dict):
        raise ValueError(
            f"Missing required numeric measurement {measurement_id!r} in evaluation_run"
        )
    _validate_eval_measurement_context(
        row,
        measurement_id,
        expected_task_ref=expected_task_ref,
        expected_metric_ref=expected_metric_ref,
        expected_oracle_ref=expected_oracle_ref,
        expected_stage=expected_stage,
        expected_subject_ref=expected_subject_ref,
    )
    oracle_measure = row.get("oracle_measure")
    raw_val = (
        oracle_measure.get("value_numeric")
        if isinstance(oracle_measure, dict) and "value_numeric" in oracle_measure
        else row.get("value_numeric")
    )
    if raw_val is None:
        raise ValueError(
            f"Missing required numeric measurement {measurement_id!r} in evaluation_run"
        )
    val = _require_finite_float(raw_val, f"measurement {measurement_id!r}")
    if abs(val - expected_val) > tol_val:
        raise ValueError(
            f"Measurement {measurement_id!r} value_numeric={val} does not match "
            f"expected {expected_val} (tol={tol_val})"
        )
    return val


def _require_eval_text(
    measurements_by_id: dict[str, dict[str, Any]],
    measurement_id: str,
    expected: str,
    *,
    expected_task_ref: str | None = None,
    expected_metric_ref: str | None = None,
    expected_oracle_ref: str | None = None,
    expected_stage: str | None = None,
    expected_subject_ref: str | None = None,
) -> str:
    """Return a validated text measurement from an EvaluationRun."""
    row = measurements_by_id.get(measurement_id)
    if not isinstance(row, dict):
        raise ValueError(
            f"Missing required text measurement {measurement_id!r} in evaluation_run"
        )
    _validate_eval_measurement_context(
        row,
        measurement_id,
        expected_task_ref=expected_task_ref,
        expected_metric_ref=expected_metric_ref,
        expected_oracle_ref=expected_oracle_ref,
        expected_stage=expected_stage,
        expected_subject_ref=expected_subject_ref,
    )
    oracle_measure = row.get("oracle_measure")
    raw_val = (
        oracle_measure.get("value_text")
        if isinstance(oracle_measure, dict) and "value_text" in oracle_measure
        else row.get("value_text")
    )
    if not isinstance(raw_val, str):
        raise ValueError(
            f"Missing required text measurement {measurement_id!r} in evaluation_run"
        )
    if raw_val != expected:
        raise ValueError(
            f"Measurement {measurement_id!r} value_text={raw_val!r} does not match "
            f"expected {expected!r}"
        )
    return raw_val


def _require_qds_numeric(
    summary_block: dict[str, Any],
    field_name: str,
    expected_ref: str,
    expected: float,
    *,
    tol: float = 1e-4,
) -> float:
    """Return a validated finite numeric field from a QualityDataSheet summary block."""
    expected_val = _require_finite_float(expected, f"QDS {field_name}.expected")
    tol_val = _require_finite_float(tol, f"QDS {field_name}.tol")
    if not isinstance(summary_block, dict):
        raise ValueError(f"Missing QDS summary block for {field_name!r}")
    entry = summary_block.get(field_name)
    if (
        not isinstance(entry, dict)
        or entry.get("source_measurement_ref") != expected_ref
        or entry.get("value_numeric") is None
    ):
        raise ValueError(
            f"QDS field {field_name!r} missing or does not bind {expected_ref!r}"
        )
    val = _require_finite_float(
        entry.get("value_numeric"), f"QDS field {field_name!r}"
    )
    if abs(val - expected_val) > tol_val:
        raise ValueError(
            f"QDS field {field_name!r} value_numeric={val} does not match "
            f"expected {expected_val} (tol={tol_val})"
        )
    return val


def _require_qds_text(
    summary_block: dict[str, Any],
    field_name: str,
    expected_ref: str,
    expected: str,
) -> str:
    """Return a validated text field from a QualityDataSheet summary block."""
    if not isinstance(summary_block, dict):
        raise ValueError(f"Missing QDS summary block for {field_name!r}")
    entry = summary_block.get(field_name)
    if (
        not isinstance(entry, dict)
        or entry.get("source_measurement_ref") != expected_ref
        or not isinstance(entry.get("value_text"), str)
    ):
        raise ValueError(
            f"QDS field {field_name!r} missing or does not bind {expected_ref!r}"
        )
    val = entry["value_text"]
    if val != expected:
        raise ValueError(
            f"QDS field {field_name!r} value_text={val!r} does not match "
            f"expected {expected!r}"
        )
    return val


def _read_verified_1sar_bytes(
    path: Path,
    expected_sha256: str,
    source_label: str,
) -> tuple[bytes, str]:
    """Read a fixed 1SAR source once as bytes and verify its SHA-256 digest."""
    raw_bytes = path.read_bytes()
    actual_sha256 = sha256_bytes(raw_bytes)
    if actual_sha256 != expected_sha256:
        raise ValueError(
            f"{source_label} SHA-256 mismatch for {path}: "
            f"actual={actual_sha256!r}, expected={expected_sha256!r}"
        )
    return raw_bytes, actual_sha256


def _read_verified_1sar_text(
    path: Path,
    expected_sha256: str,
    source_label: str,
) -> tuple[str, str]:
    """Read a fixed 1SAR text source once as bytes, verify its SHA-256, and decode UTF-8."""
    raw_bytes, actual_sha256 = _read_verified_1sar_bytes(
        path, expected_sha256, source_label
    )
    try:
        return raw_bytes.decode("utf-8"), actual_sha256
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"Non-UTF-8 content in {source_label} source {path}"
        ) from exc


def assess_1sar_case_study(
    archive_path: Path = DEFAULT_ARCHIVE,
    deposited_pdb_path: Path = DEFAULT_DEPOSITED_PDB,
    qds_path: Path = DEFAULT_1SAR_QDS,
    eval_path: Path = DEFAULT_1SAR_EVAL,
    coord_audit_path: Path = DEFAULT_1SAR_COORD_AUDIT,
    pass_criterion_bindings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the structured before/after refinement assessment for 1SAR.

    Fixed retained-bundle boundary: this specialized 1SAR reader admits the
    five retained case-study inputs (`archive_path`, `deposited_pdb_path`,
    `qds_path`, `eval_path`, `coord_audit_path`) at default or alternate file
    paths only when their exact byte SHA-256 digests match the retained 1SAR
    bundle BEFORE parsing or deriving any case-study output.
    """
    bindings = list(pass_criterion_bindings or [])
    resolve_verdict_status(bindings, None)

    archive_bytes, actual_archive_sha256 = _read_verified_1sar_bytes(
        archive_path, EXPECTED_1SAR_ARCHIVE_SHA256, "Archive"
    )
    deposited_pdb_text, actual_deposited_sha256 = _read_verified_1sar_text(
        deposited_pdb_path, EXPECTED_1SAR_DEPOSITED_PDB_SHA256, "Deposited PDB"
    )
    qds_text, _ = _read_verified_1sar_text(
        qds_path, EXPECTED_1SAR_QDS_SHA256, "QDS"
    )
    eval_text, _ = _read_verified_1sar_text(
        eval_path, EXPECTED_1SAR_EVAL_SHA256, "EvaluationRun"
    )
    coord_audit_text, _ = _read_verified_1sar_text(
        coord_audit_path, EXPECTED_1SAR_COORD_AUDIT_SHA256, "Coordinate/T13 audit"
    )

    try:
        qds_doc = yaml.safe_load(qds_text)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid QDS YAML in {qds_path}") from exc
    if (
        not isinstance(qds_doc, dict)
        or not isinstance(qds_doc.get("quality_data_sheets"), list)
        or len(qds_doc["quality_data_sheets"]) != 1
    ):
        raise ValueError(f"Invalid QDS document in {qds_path}")
    qds = qds_doc["quality_data_sheets"][0]
    expected_subject_ref = EXPECTED_1SAR_FINAL_SUBJECT_REF
    if (
        not isinstance(qds, dict)
        or qds.get("id") != "QDS_1sar_cdba2c07_2026-09-23"
        or qds.get("structure_ref") != "1sar"
        or qds.get("subject_ref") != expected_subject_ref
    ):
        raise ValueError(
            "QDS record does not match expected 1SAR id, structure_ref, or subject_ref"
        )

    try:
        eval_doc = yaml.safe_load(eval_text)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid EvaluationRun YAML in {eval_path}") from exc
    if (
        not isinstance(eval_doc, dict)
        or not isinstance(eval_doc.get("evaluation_runs"), list)
        or not eval_doc["evaluation_runs"]
    ):
        raise ValueError(f"Invalid EvaluationRun document in {eval_path}")
    eval_run = eval_doc["evaluation_runs"][0]
    if (
        not isinstance(eval_run, dict)
        or eval_run.get("id") != "EVAL_1sar_cdba2c07_2026-09-23"
        or eval_run.get("structure_ref") != "1sar"
    ):
        raise ValueError(
            "EvaluationRun record does not match expected 1SAR id or structure_ref"
        )

    verdict_status = resolve_verdict_status(
        bindings, eval_run.get("overall_verdict_status")
    )

    try:
        coord_audit = json.loads(coord_audit_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid coordinate audit JSON in {coord_audit_path}") from exc
    if not isinstance(coord_audit, dict):
        raise ValueError(f"Invalid coordinate audit JSON in {coord_audit_path}")
    recorded_archive_sha256 = (
        coord_audit.get("archive", {}).get("sha256")
        if isinstance(coord_audit.get("archive"), dict)
        else None
    )
    if (
        recorded_archive_sha256 != EXPECTED_1SAR_ARCHIVE_SHA256
        or actual_archive_sha256 != recorded_archive_sha256
    ):
        raise ValueError(
            f"Archive SHA-256 mismatch for {archive_path}: actual={actual_archive_sha256!r}, "
            f"coord_audit={recorded_archive_sha256!r}, expected={EXPECTED_1SAR_ARCHIVE_SHA256!r}"
        )

    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as zf:
        start_pdb_bytes = zf.read("data/1sar.pdb")
        final_pdb_bytes = zf.read("data/1sar_final.pdb")
        start_mtz_bytes = zf.read("data/1sar.mtz")
        final_mtz_bytes = zf.read("data/1sar_final.mtz")

    final_pdb_sha256 = sha256_bytes(final_pdb_bytes)
    start_mtz_sha256 = sha256_bytes(start_mtz_bytes)
    model_block = coord_audit.get("model")
    if (
        not isinstance(model_block, dict)
        or model_block.get("sha256") != final_pdb_sha256
        or model_block.get("subject_ref") != qds["subject_ref"]
        or model_block.get("member") != "data/1sar_final.pdb"
    ):
        raise ValueError(
            "Coordinate audit model SHA-256 or subject_ref does not match archived data/1sar_final.pdb"
        )
    dataset_block = coord_audit.get("dataset")
    if (
        not isinstance(dataset_block, dict)
        or dataset_block.get("sha256") != start_mtz_sha256
        or dataset_block.get("subject_ref") != EXPECTED_1SAR_MTZ_SUBJECT_REF
        or dataset_block.get("member") != "data/1sar.mtz"
    ):
        raise ValueError(
            "Coordinate audit dataset SHA-256 or subject_ref does not match archived data/1sar.mtz"
        )

    eval_measurements = {
        m["id"]: m
        for m in eval_run.get("measurements", [])
        if isinstance(m, dict) and isinstance(m.get("id"), str)
    }
    eval_refinements = {
        r["id"]: r
        for r in eval_run.get("refinements", [])
        if isinstance(r, dict) and isinstance(r.get("id"), str)
    }
    qds_origins = {
        o["source_measurement_ref"]: o
        for o in qds.get("measurement_evidence_origins", [])
        if isinstance(o, dict) and isinstance(o.get("source_measurement_ref"), str)
    }
    for required_origin_ref in (
        "EVAL_1sar_cdba2c07_2026-09-07_M_001",
        "EVAL_1sar_cdba2c07_2026-09-07_M_002",
        "EVAL_1sar_cdba2c07_2026-09-07_M_003",
        "EVAL_1sar_cdba2c07_2026-09-07_M_005",
        "EVAL_1sar_cdba2c07_2026-09-07_M_006",
        "EVAL_1sar_cdba2c07_2026-09-07_M_007",
        "EVAL_1sar_cdba2c07_2026-09-22_T15_SS_97824701cc681ebe_M_content",
        "EVAL_1sar_cdba2c07_2026-09-22_T15_SS_97824701cc681ebe_M_agreement",
        "EVAL_1sar_cdba2c07_2026-09-21_M_006",
        "EVAL_1sar_cdba2c07_2026-09-21_M_007",
        "EVAL_1sar_cdba2c07_2026-09-23_M_016",
    ):
        origin_entry = qds_origins.get(required_origin_ref)
        if not isinstance(origin_entry, dict):
            raise ValueError(
                f"QDS measurement_evidence_origins missing {required_origin_ref!r}"
            )
        for origin_field in (
            "source_evaluation_run_ref",
            "origin_evaluation_run_ref",
            "origin_measurement_ref",
            "origin_run_date",
        ):
            field_val = origin_entry.get(origin_field)
            if not isinstance(field_val, str) or not field_val.strip():
                raise ValueError(
                    f"QDS measurement_evidence_origins[{required_origin_ref!r}] "
                    f"missing non-empty {origin_field!r}"
                )

    gemmi_rwork = _require_qds_numeric(
        qds.get("refinement_summary", {}),
        "r_work",
        "EVAL_1sar_cdba2c07_2026-09-07_M_005",
        0.1622,
    )
    gemmi_rfree = _require_qds_numeric(
        qds.get("refinement_summary", {}),
        "r_free",
        "EVAL_1sar_cdba2c07_2026-09-07_M_006",
        0.2136,
    )
    gemmi_rgap = _require_qds_numeric(
        qds.get("refinement_summary", {}),
        "r_free_gap",
        "EVAL_1sar_cdba2c07_2026-09-07_M_007",
        0.0515,
    )

    round4_hist = eval_refinements.get(
        "EVAL_1sar_cdba2c07_2026-09-23_R_packaged_round4_historical"
    )
    if not isinstance(round4_hist, dict):
        raise ValueError(
            "Missing EVAL_1sar_cdba2c07_2026-09-23_R_packaged_round4_historical in evaluation_run"
        )
    for metric_key in ("r_work", "r_free", "r_free_gap"):
        metric_block = round4_hist.get(metric_key)
        if (
            not isinstance(metric_block, dict)
            or metric_block.get("subject_ref") != EXPECTED_1SAR_FINAL_SUBJECT_REF
        ):
            raise ValueError(
                f"Refinement EVAL_1sar_cdba2c07_2026-09-23_R_packaged_round4_historical.{metric_key} "
                f"missing or does not match expected subject_ref {EXPECTED_1SAR_FINAL_SUBJECT_REF!r}"
            )
    phenix_final_rwork = _require_finite_float(
        round4_hist["r_work"].get("value_numeric"),
        "round4_hist.r_work.value_numeric",
    )
    phenix_final_rfree = _require_finite_float(
        round4_hist["r_free"].get("value_numeric"),
        "round4_hist.r_free.value_numeric",
    )
    phenix_final_rgap = _require_finite_float(
        round4_hist["r_free_gap"].get("value_numeric"),
        "round4_hist.r_free_gap.value_numeric",
    )
    if (
        abs(phenix_final_rwork - 0.1564) > 1e-4
        or abs(phenix_final_rfree - 0.2116) > 1e-4
        or abs(phenix_final_rgap - 0.0552) > 1e-4
    ):
        raise ValueError(
            "Unexpected packaged round-4 historical PHENIX R-values in evaluation_run"
        )

    refmac_rwork = _require_eval_numeric(
        eval_measurements,
        "EVAL_1sar_cdba2c07_2026-09-23_M_refmac_rwork",
        0.1693,
        expected_task_ref="T03",
        expected_metric_ref="T03_r-work",
        expected_oracle_ref="REFMAC5",
        expected_stage="final",
        expected_subject_ref=EXPECTED_1SAR_FINAL_SUBJECT_REF,
    )
    refmac_rfree = _require_eval_numeric(
        eval_measurements,
        "EVAL_1sar_cdba2c07_2026-09-23_M_refmac_rfree",
        0.2128,
        expected_task_ref="T03",
        expected_metric_ref="T03_r-free",
        expected_oracle_ref="REFMAC5",
        expected_stage="final",
        expected_subject_ref=EXPECTED_1SAR_FINAL_SUBJECT_REF,
    )
    servalcat_rwork = _require_eval_numeric(
        eval_measurements,
        "EVAL_1sar_cdba2c07_2026-09-23_M_servalcat_sigmaa_rwork",
        0.1705,
    )
    servalcat_rfree = _require_eval_numeric(
        eval_measurements,
        "EVAL_1sar_cdba2c07_2026-09-23_M_servalcat_sigmaa_rfree",
        0.2209,
    )
    servalcat_rgap = _require_eval_numeric(
        eval_measurements,
        "EVAL_1sar_cdba2c07_2026-09-23_M_servalcat_sigmaa_gap",
        0.0504,
    )
    clash_molprobity = _require_eval_numeric(
        eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_016", 3.63
    )
    _require_qds_numeric(
        qds.get("geometry_summary", {}),
        "clashscore",
        "EVAL_1sar_cdba2c07_2026-09-23_M_016",
        clash_molprobity,
    )
    clash_mmtbx_final = _require_eval_numeric(
        eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_015", 3.13
    )
    clash_mmtbx_start = _require_eval_numeric(
        eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_014", 31.66
    )
    refmac_bond_rmsd = _require_eval_numeric(
        eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_refmac_bond_rmsd", 0.0105
    )
    refmac_angle_rmsd = _require_eval_numeric(
        eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_refmac_angle_rmsd", 1.4957
    )
    refmac_bond_rmsz = _require_eval_numeric(
        eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_refmac_bond_rmsz", 0.884
    )
    refmac_angle_rmsz = _require_eval_numeric(
        eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_refmac_angle_rmsz", 0.864
    )
    mmtbx_bond_rmsd = _require_eval_numeric(
        eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_026", 0.007
    )
    mmtbx_angle_rmsd = _require_eval_numeric(
        eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_027", 0.85
    )
    dssp_he_fraction = _require_qds_numeric(
        qds.get("classification_summary", {}),
        "secondary_structure_content",
        "EVAL_1sar_cdba2c07_2026-09-22_T15_SS_97824701cc681ebe_M_content",
        0.375,
    )
    psea_q3_agreement = _require_qds_numeric(
        qds.get("classification_summary", {}),
        "secondary_structure_agreement",
        "EVAL_1sar_cdba2c07_2026-09-22_T15_SS_97824701cc681ebe_M_agreement",
        0.8802,
    )
    completeness_pct = _require_eval_numeric(
        eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_030", 99.38
    )
    wilson_b = _require_eval_numeric(
        eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_t13_wilson_b", 14.542
    )
    twin_fraction_l = _require_eval_numeric(
        eval_measurements,
        "EVAL_1sar_cdba2c07_2026-09-23_M_t13_twin_fraction_l",
        0.03,
    )
    delta_b_aniso_raw = _require_eval_numeric(
        eval_measurements,
        "EVAL_1sar_cdba2c07_2026-09-23_M_t13_delta_b_aniso",
        7.3188,
        tol=1e-3,
    )
    tncs_text = _require_eval_text(
        eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_t13_tncs_flag", "false"
    )
    _require_eval_text(
        eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_t13_ice_ring_flags", "3.44Å"
    )
    _require_eval_text(
        eval_measurements,
        "EVAL_1sar_cdba2c07_2026-09-23_M_t13_aimless_attempt",
        "failed",
    )
    rama_favored_pct = _require_eval_numeric(
        eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_022", 98.4
    )
    rama_outliers_start = _require_eval_numeric(
        eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_019", 9.04
    )
    rama_outliers_final = _require_eval_numeric(
        eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_020", 0.53
    )
    rotamer_outliers_final = _require_eval_numeric(
        eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_023", 4.88
    )
    c_beta_deviations = _require_finite_int(
        _require_eval_numeric(
            eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_024", 0.0
        ),
        "EVAL_1sar_cdba2c07_2026-09-23_M_024",
    )
    molprobity_score = _require_eval_numeric(
        eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_025", 1.63
    )
    holton_start = _require_eval_numeric(
        eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_028", 3.32
    )
    holton_final = _require_eval_numeric(
        eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_029", 1.33
    )
    dockq_ab = round(
        _require_qds_numeric(
            qds.get("interface_quality_summary", {}),
            "interface_dockq_score",
            "EVAL_1sar_cdba2c07_2026-09-21_M_006",
            0.9445,
        ),
        4,
    )
    dockq_capri = _require_qds_text(
        qds.get("interface_quality_summary", {}),
        "capri_interface_quality_class",
        "EVAL_1sar_cdba2c07_2026-09-21_M_007",
        "High",
    )
    phenix_start_rwork = _require_eval_numeric(
        eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_004", 0.3334
    )
    phenix_start_rfree = _require_eval_numeric(
        eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_005", 0.3956
    )
    phenix_delta_rfree = _require_eval_numeric(
        eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_013", -0.1840
    )
    lddt_global = _require_eval_numeric(
        eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_lddt_global", 0.9725
    )
    phenix_superpose_rmsd = _require_eval_numeric(
        eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_001", 0.43
    )
    tmalign_rmsd = _require_eval_numeric(
        eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_002", 0.41
    )
    tmalign_tmscore = _require_eval_numeric(
        eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_003", 0.987
    )
    round0_rwork = _require_eval_numeric(
        eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_round0_rwork", 0.3334
    )
    round0_rfree = _require_eval_numeric(
        eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_round0_rfree", 0.3956
    )
    round2_rwork = _require_eval_numeric(
        eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_round2_rwork", 0.1686
    )
    round2_rfree = _require_eval_numeric(
        eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_round2_rfree", 0.2301
    )
    round3_rwork = _require_eval_numeric(
        eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_round3_rwork", 0.1589
    )
    round3_rfree = _require_eval_numeric(
        eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_round3_rfree", 0.2164
    )
    round5_rwork = _require_eval_numeric(
        eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_round5_rwork", 0.1555
    )
    round5_rfree = _require_eval_numeric(
        eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_round5_rfree", 0.2104
    )
    round6_rwork = _require_eval_numeric(
        eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_round6_rwork", 0.1539
    )
    round6_rfree = _require_eval_numeric(
        eval_measurements, "EVAL_1sar_cdba2c07_2026-09-23_M_round6_rfree", 0.2068
    )

    deposition_info = _parse_deposited_r_values(
        deposited_pdb_path,
        pdb_text=deposited_pdb_text,
        require_1sar_header=True,
    )

    start_pdb_text = start_pdb_bytes.decode("utf-8", errors="replace")
    final_pdb_text = final_pdb_bytes.decode("utf-8", errors="replace")

    start_inventory = summarize_pdb_inventory(start_pdb_text)
    final_inventory = summarize_pdb_inventory(final_pdb_text)
    pair_comparison = compare_pdb_pair(start_pdb_text, final_pdb_text)
    mtz_labels = ("F-obs", "SIGF-obs", "R-free-flags")
    mtz_retention = audit_mtz_retention(
        start_mtz_bytes,
        final_mtz_bytes,
        input_labels=mtz_labels,
        output_labels=mtz_labels,
        flag_values={0, 1},
        free_value=1,
    )

    # Question 1: Implementation agreement on the same observable (packaged final model)
    implementation_agreement = {
        "question": (
            "Do independent software implementations agree on the same observable "
            "when applied to the packaged 1SAR round-4 model (data/1sar_final.pdb) "
            "and reflection set (data/1sar.mtz)?"
        ),
        "observables": [
            {
                "observable_id": "T03_r_work_r_free",
                "task_id": "T03",
                "subject_ref": qds["subject_ref"],
                "atom_selection": "all_1641_model_heavy_atoms_against_data/1sar.mtz",
                "implementations": [
                    {
                        "tool": "gemmi sfcalc (gemmi_rfactor.py, bin-rescaled)",
                        "version": "0.7.5",
                        "r_work": gemmi_rwork,
                        "r_free": gemmi_rfree,
                        "r_free_minus_r_work": gemmi_rgap,
                        "source_measurement_refs": [
                            "EVAL_1sar_cdba2c07_2026-09-07_M_005",
                            "EVAL_1sar_cdba2c07_2026-09-07_M_006",
                            "EVAL_1sar_cdba2c07_2026-09-07_M_007",
                        ],
                        "evidence_tier": "retained_qds_primary",
                    },
                    {
                        "tool": "phenix.model_vs_data",
                        "version": "1.21.2-5419 (historical)",
                        "r_work": phenix_final_rwork,
                        "r_free": phenix_final_rfree,
                        "r_free_minus_r_work": phenix_final_rgap,
                        "source_measurement_refs": [
                            "EVAL_1sar_cdba2c07_2026-09-07_M_001",
                            "EVAL_1sar_cdba2c07_2026-09-07_M_002",
                            "EVAL_1sar_cdba2c07_2026-09-07_M_003",
                        ],
                        "evidence_tier": "historical_eval_row",
                    },
                    {
                        "tool": "REFMAC5 (NCYC=0 evaluation)",
                        "version": "5.8.0431 (historical)",
                        "r_work": refmac_rwork,
                        "r_free": refmac_rfree,
                        "r_free_minus_r_work": round(refmac_rfree - refmac_rwork, 4),
                        "source_measurement_refs": [
                            "EVAL_1sar_cdba2c07_2026-09-23_M_refmac_rwork",
                            "EVAL_1sar_cdba2c07_2026-09-23_M_refmac_rfree",
                        ],
                        "evidence_tier": "historical_eval_row",
                    },
                    {
                        "tool": "Servalcat sigmaa",
                        "version": "0.4.131 (historical, recorded n_free=362)",
                        "r_work": servalcat_rwork,
                        "r_free": servalcat_rfree,
                        "r_free_minus_r_work": servalcat_rgap,
                        "source_measurement_refs": [
                            "EVAL_1sar_cdba2c07_2026-09-23_M_servalcat_sigmaa_rwork",
                            "EVAL_1sar_cdba2c07_2026-09-23_M_servalcat_sigmaa_rfree",
                            "EVAL_1sar_cdba2c07_2026-09-23_M_servalcat_sigmaa_gap",
                        ],
                        "evidence_tier": "historical_eval_row",
                    },
                ],
                "spread_summary": {
                    "r_work_range": [phenix_final_rwork, servalcat_rwork],
                    "r_work_max_abs_delta": round(
                        servalcat_rwork - phenix_final_rwork, 4
                    ),
                    "r_free_range": [phenix_final_rfree, servalcat_rfree],
                    "r_free_max_abs_delta": round(
                        servalcat_rfree - phenix_final_rfree, 4
                    ),
                    "gemmi_minus_phenix_r_work": round(
                        gemmi_rwork - phenix_final_rwork, 4
                    ),
                    "gemmi_minus_phenix_r_free": round(
                        gemmi_rfree - phenix_final_rfree, 4
                    ),
                },
                "agreement_assessment": (
                    "Retained gemmi sfcalc (bin-rescaled), phenix.model_vs_data, "
                    "and REFMAC5 R-free values span 0.2116 to 0.2136 (range "
                    "0.0020); Servalcat sigmaa reports 0.2209 with recorded "
                    "n_free=362. The archive audit preserves 723 stored "
                    "free-reflection entries, but this does not establish "
                    "matched effective reflection selections/free flags across "
                    "the historical tool invocations. Historical REFMAC5 raw "
                    "oracle output is not retained. The +0.0058 R-work / "
                    "+0.0020 R-free offset between gemmi_rfactor.py "
                    "(bin-rescaled) and phenix.model_vs_data remains "
                    "descriptive and informational."
                ),
            },
            {
                "observable_id": "T05_all_atom_clashscore",
                "task_id": "T05",
                "subject_ref": qds["subject_ref"],
                "atom_selection": "all_atoms_with_explicit_riding_hydrogens",
                "implementations": [
                    {
                        "tool": "MolProbity clashscore (standalone reduce/probe)",
                        "version": "4.5.2 (historical)",
                        "clashscore": clash_molprobity,
                        "source_measurement_refs": [
                            "EVAL_1sar_cdba2c07_2026-09-23_M_016",
                        ],
                        "evidence_tier": "historical_eval_row",
                    },
                    {
                        "tool": "mmtbx.validation_summary",
                        "version": "1.21.2-5419 (historical)",
                        "clashscore": clash_mmtbx_final,
                        "source_measurement_refs": [
                            "EVAL_1sar_cdba2c07_2026-09-23_M_015",
                        ],
                        "evidence_tier": "historical_eval_row",
                    },
                ],
                "spread_summary": {
                    "clashscore_range": [clash_mmtbx_final, clash_molprobity],
                    "abs_delta": round(clash_molprobity - clash_mmtbx_final, 2),
                },
                "agreement_assessment": (
                    "Standalone MolProbity (3.63, 11 bad-overlap pairs over 3,027 "
                    "H-built atoms) and mmtbx.validation_summary (3.13) differ by "
                    "0.50 clashes/1000 atoms on data/1sar_final.pdb; raw H-built "
                    "coordinates were not retained, so the 0.50 difference is "
                    "recorded without causal attribution."
                ),
            },
            {
                "observable_id": "T05_bond_and_angle_rmsd",
                "task_id": "T05",
                "subject_ref": qds["subject_ref"],
                "atom_selection": "covalent_protein_and_heteroatom_restraints",
                "implementations": [
                    {
                        "tool": "REFMAC5",
                        "version": "5.8.0431 (historical)",
                        "bond_rmsd_angstrom": refmac_bond_rmsd,
                        "angle_rmsd_deg": refmac_angle_rmsd,
                        "bond_rmsz": refmac_bond_rmsz,
                        "angle_rmsz": refmac_angle_rmsz,
                        "source_measurement_refs": [
                            "EVAL_1sar_cdba2c07_2026-09-23_M_refmac_bond_rmsd",
                            "EVAL_1sar_cdba2c07_2026-09-23_M_refmac_angle_rmsd",
                            "EVAL_1sar_cdba2c07_2026-09-23_M_refmac_bond_rmsz",
                            "EVAL_1sar_cdba2c07_2026-09-23_M_refmac_angle_rmsz",
                        ],
                        "evidence_tier": "historical_eval_row",
                    },
                    {
                        "tool": "mmtbx.validation_summary",
                        "version": "1.21.2-5419 (historical)",
                        "bond_rmsd_angstrom": mmtbx_bond_rmsd,
                        "angle_rmsd_deg": mmtbx_angle_rmsd,
                        "bond_rmsz": None,
                        "angle_rmsz": None,
                        "source_measurement_refs": [
                            "EVAL_1sar_cdba2c07_2026-09-23_M_026",
                            "EVAL_1sar_cdba2c07_2026-09-23_M_027",
                        ],
                        "evidence_tier": "historical_eval_row",
                    },
                ],
                "spread_summary": {
                    "bond_rmsd_abs_delta_angstrom": round(
                        refmac_bond_rmsd - mmtbx_bond_rmsd, 4
                    ),
                    "angle_rmsd_abs_delta_deg": round(
                        refmac_angle_rmsd - mmtbx_angle_rmsd, 4
                    ),
                },
                "agreement_assessment": (
                    "REFMAC5 (0.0105 A / 1.4957 deg) and mmtbx.validation_summary "
                    "(0.007 A / 0.85 deg) differ by 0.0035 A and 0.6457 deg on "
                    "data/1sar_final.pdb; matched bond counts and raw restraint-library "
                    "outputs were not retained, and the agent-reported 0.004 A / 0.99 deg "
                    "values belong to the absent round-7 model."
                ),
            },
            {
                "observable_id": "T15_secondary_structure_3state",
                "task_id": "T15",
                "subject_ref": qds["subject_ref"],
                "atom_selection": "192_protein_residues_chains_A_and_B",
                "implementations": [
                    {
                        "tool": "mkdssp (DSSP H-bond/electrostatic)",
                        "version": "4.6.1",
                        "he_fraction": dssp_he_fraction,
                        "he_residue_count": int(round(dssp_he_fraction * 192)),
                        "total_residues": 192,
                        "source_measurement_refs": [
                            "EVAL_1sar_cdba2c07_2026-09-22_T15_SS_97824701cc681ebe_M_content",
                        ],
                        "evidence_tier": "recomputed_in_retained_eval",
                    },
                    {
                        "tool": "biotite.structure.annotate_sse (P-SEA CA geometry)",
                        "version": "1.7.1",
                        "q3_agreement_vs_dssp": psea_q3_agreement,
                        "matching_residues_vs_dssp": int(
                            round(psea_q3_agreement * 192)
                        ),
                        "total_residues": 192,
                        "source_measurement_refs": [
                            "EVAL_1sar_cdba2c07_2026-09-22_T15_SS_97824701cc681ebe_M_agreement",
                        ],
                        "evidence_tier": "recomputed_in_retained_eval",
                    },
                ],
                "spread_summary": {
                    "q3_agreement_fraction": psea_q3_agreement,
                    "discrepant_residue_count": 192
                    - int(round(psea_q3_agreement * 192)),
                },
                "agreement_assessment": (
                    "DSSP and P-SEA agree on 169/192 residues (88.02% Q3); 23 "
                    "residues have different H/E/C assignments. DSSP uses "
                    "backbone H-bond energies, whereas P-SEA uses CA-only "
                    "distance/dihedral criteria."
                ),
            },
        ],
    }

    # Question 2: What supports the final model's quality for its intended use?
    final_model_quality_support = {
        "question": (
            "What measurements support the packaged final model's (data/1sar_final.pdb, "
            "round 4) quality for downstream structural analysis at 2.50 A packaged/MTZ "
            "dataset resolution (49.972-2.500 A in data/1sar.mtz; 1.80 A deposited 1SAR reference)?"
        ),
        "subject_ref": qds["subject_ref"],
        "packaged_model_resolution_angstrom": 2.50,
        "mtz_resolution_range_angstrom": [49.972, 2.500],
        "deposited_reference_resolution_angstrom": 1.80,
        "domains": {
            "experimental_fit_and_data_completeness": {
                "completeness_percent": completeness_pct,
                "wilson_b_angstrom2": wilson_b,
                "twin_fraction_l_test": twin_fraction_l,
                "tncs_detected": tncs_text.lower() == "true",
                "anisotropy_delta_b_angstrom2": round(delta_b_aniso_raw, 3),
                "ice_ring_anomaly": "3.44 A shell (I/sigma Z = 5.21)",
                "r_work_phenix": phenix_final_rwork,
                "r_free_phenix": phenix_final_rfree,
                "r_free_minus_r_work_phenix": phenix_final_rgap,
                "r_work_gemmi": gemmi_rwork,
                "r_free_gemmi": gemmi_rfree,
                "r_free_minus_r_work_gemmi": gemmi_rgap,
                "r_work_pdb_header": 0.1563,
                "r_free_pdb_header": 0.2114,
            },
            "stereochemistry_and_geometry": {
                "clashscore_molprobity": clash_molprobity,
                "clashscore_mmtbx": clash_mmtbx_final,
                "ramachandran_favored_percent": rama_favored_pct,
                "ramachandran_outliers_percent": rama_outliers_final,
                "ramachandran_outlier_residues": ["1sar:A:39 (Asn A 39)"],
                "rotamer_outliers_percent": rotamer_outliers_final,
                "c_beta_deviations": c_beta_deviations,
                "molprobity_composite_score": molprobity_score,
                "mmtbx_bond_rmsd_angstrom": mmtbx_bond_rmsd,
                "mmtbx_angle_rmsd_deg": mmtbx_angle_rmsd,
                "refmac_bond_rmsz": refmac_bond_rmsz,
                "refmac_angle_rmsz": refmac_angle_rmsz,
                "holton_geom_energy_ratio_sigma": holton_final,
            },
            "dimer_interface_and_fold_conservation_vs_deposited_1sar": {
                "reference_subject_ref": "pdb:1SAR (data/pdb_mtz/1sar_deposited.pdb)",
                "interface_context": (
                    "Deposited 1SAR A/B crystallographic contact; DockQ/CAPRI here "
                    "do not certify a biological assembly."
                ),
                "dockq_identity_mapping_AB_AB": dockq_ab,
                "dockq_identity_capri_class": dockq_capri,
                "dockq_swapped_mapping_AB_BA": 0.0063,
                "chain_A_kabsch_ca_rmsd_vs_deposited_angstrom": 0.191,
                "chain_B_kabsch_ca_rmsd_vs_deposited_angstrom": 0.180,
                "active_site_and_ligand_note": (
                    "Chainwise backbone fold and the A/B crystallographic "
                    "contact match deposited 1SAR closely (DockQ = 0.9445, "
                    "chain CA RMSD 0.191 / 0.180 A). The identity mapping is "
                    "supported by independent chainwise fits; these interface "
                    "scores do not certify a biological assembly. A:97:SO4 is "
                    "retained (mean B = 17.588 A^2), whereas B:97:SO4 was "
                    "removed in packaged round 4 and A:98:CA (B = 42.73 A^2) "
                    "and B:98:NA (B = 22.85 A^2) were added."
                ),
            },
        },
    }

    # Question 3: What improved or regressed relative to the actual input?
    change_relative_to_input = {
        "question": (
            "What improved, stayed invariant, or regressed between the actual "
            "starting model/data (data/1sar.pdb, data/1sar.mtz) and the packaged "
            "final model/data (data/1sar_final.pdb, data/1sar_final.mtz)?"
        ),
        "starting_subject_ref": "artifact:cdba2c07-daff-4f60-ae96-12452b3a5fbb#data/1sar.pdb",
        "final_subject_ref": qds["subject_ref"],
        "reflection_data_retention": {
            "input_mtz": "data/1sar.mtz",
            "output_mtz": "data/1sar_final.mtz",
            "audit_status": mtz_retention["audit_status"],
            "input_total_rows": mtz_retention["input"]["raw_rows"],
            "output_total_rows": mtz_retention["output"]["raw_rows"],
            "input_eligible_count": mtz_retention["input"]["eligible_rows"],
            "output_eligible_count": mtz_retention["output"]["eligible_rows"],
            "input_work_count": mtz_retention["input"]["work_rows"],
            "output_work_count": mtz_retention["output"]["work_rows"],
            "input_free_count": mtz_retention["input"]["free_rows"],
            "output_free_count": mtz_retention["output"]["free_rows"],
            "input_zero_f_count": mtz_retention["input"]["zero_f"],
            "changed_free_flag_count": len(mtz_retention["changed_flags"]),
            "changed_observation_count": len(mtz_retention["changed_observations"]),
            "invalidated_input_hkl_count": len(
                mtz_retention["invalidated_input_hkls"]
            ),
            "invalidated_input_hkls": [
                list(hkl) for hkl in mtz_retention["invalidated_input_hkls"]
            ],
            "added_raw_rows": mtz_retention["added_raw_rows"],
            "added_all_nan_rows": mtz_retention["added_all_nan_rows"],
            "interpretation": (
                "All 723 free-R reflections and 6,494 positive-F work reflections "
                "preserve identical (F-obs, SIGF-obs, R-free-flags) values in "
                "data/1sar_final.mtz. However, audit_mtz_retention flags "
                "'not_preserved' because 11 input work reflections with F=0.0 in "
                "data/1sar.mtz were written as NaN in data/1sar_final.mtz and 14 "
                "all-NaN reflection rows were appended."
            ),
        },
        "coordinate_and_b_factor_changes": pair_comparison,
        "retained_pairwise_similarity_metrics": {
            "openstructure_ca_lddt_global": lddt_global,
            "openstructure_ca_lddt_per_residue_mean_chain_A": 0.9714,
            "gemmi_superposed_ca_rmsd_historical_angstrom": 0.423,
            "phenix_superpose_models_rmsd_historical_angstrom": phenix_superpose_rmsd,
            "tmalign_ca_rmsd_96res_historical_angstrom": tmalign_rmsd,
            "tmalign_tm_score_historical": tmalign_tmscore,
        },
        "retained_start_to_packaged_quality_deltas": {
            "phenix_r_work": {
                "start": phenix_start_rwork,
                "final_packaged": phenix_final_rwork,
                "delta": round(phenix_final_rwork - phenix_start_rwork, 4),
                "source_refs": [
                    "EVAL_1sar_cdba2c07_2026-09-23_M_004",
                    "EVAL_1sar_cdba2c07_2026-09-07_M_001",
                ],
            },
            "phenix_r_free": {
                "start": phenix_start_rfree,
                "final_packaged": phenix_final_rfree,
                "delta": phenix_delta_rfree,
                "source_refs": [
                    "EVAL_1sar_cdba2c07_2026-09-23_M_005",
                    "EVAL_1sar_cdba2c07_2026-09-07_M_002",
                    "EVAL_1sar_cdba2c07_2026-09-23_M_013",
                ],
            },
            "mmtbx_clashscore": {
                "start": clash_mmtbx_start,
                "final_packaged": clash_mmtbx_final,
                "delta": round(clash_mmtbx_final - clash_mmtbx_start, 2),
                "source_refs": [
                    "EVAL_1sar_cdba2c07_2026-09-23_M_014",
                    "EVAL_1sar_cdba2c07_2026-09-23_M_015",
                ],
            },
            "mmtbx_ramachandran_outliers_percent": {
                "start": rama_outliers_start,
                "final_packaged": rama_outliers_final,
                "delta": round(rama_outliers_final - rama_outliers_start, 2),
                "source_refs": [
                    "EVAL_1sar_cdba2c07_2026-09-23_M_019",
                    "EVAL_1sar_cdba2c07_2026-09-23_M_020",
                ],
            },
            "holton_geometry_energy_ratio_sigma": {
                "start": holton_start,
                "final_packaged": holton_final,
                "delta": round(holton_final - holton_start, 2),
                "source_refs": [
                    "EVAL_1sar_cdba2c07_2026-09-23_M_028",
                    "EVAL_1sar_cdba2c07_2026-09-23_M_029",
                ],
            },
        },
        "model_composition_and_experimental_fit_trajectory": {
            "starting_model_composition": start_inventory,
            "packaged_final_model_composition": final_inventory,
            "water_count_change": (
                final_inventory["water_atom_count"]
                - start_inventory["water_atom_count"]
            ),
            "non_water_hetero_changes": {
                "preserved_groups": ["A:97:SO4 (5 atoms)"],
                "removed_groups_in_packaged_round4": ["B:97:SO4 (5 atoms)"],
                "added_groups_in_packaged_round4": [
                    "A:98:CA (1 atom, B=42.73 A^2)",
                    "B:98:NA (1 atom, B=22.85 A^2)",
                ],
            },
            "r_factor_trajectory_across_retained_eval_and_logs": {
                "round0_starting_model_phenix": {
                    "archive_member": "data/1sar.pdb",
                    "r_work": round0_rwork,
                    "r_free": round0_rfree,
                    "source": "EVAL_1sar_cdba2c07_2026-09-23_M_round0_rwork / M_round0_rfree",
                },
                "round2_intermediate_phenix": {
                    "archive_member": "data/1sar_round2.pdb",
                    "r_work": round2_rwork,
                    "r_free": round2_rfree,
                    "source": "EVAL_1sar_cdba2c07_2026-09-23_M_round2_rwork / M_round2_rfree",
                },
                "round3_intermediate_phenix": {
                    "archive_member": "data/1sar_round3.pdb",
                    "r_work": round3_rwork,
                    "r_free": round3_rfree,
                    "source": "EVAL_1sar_cdba2c07_2026-09-23_M_round3_rwork / M_round3_rfree",
                },
                "round4_packaged_final_phenix": {
                    "archive_member": "data/1sar_final.pdb",
                    "r_work": phenix_final_rwork,
                    "r_free": phenix_final_rfree,
                    "pdb_header_r_work": 0.1563,
                    "pdb_header_r_free": 0.2114,
                    "delta_r_work_vs_round0": round(
                        phenix_final_rwork - round0_rwork, 4
                    ),
                    "delta_r_free_vs_round0": round(
                        phenix_final_rfree - round0_rfree, 4
                    ),
                    "source": "EVAL_1sar_cdba2c07_2026-09-07_M_001 / M_002 (data/1sar_final.pdb)",
                },
                "round5_intermediate_phenix": {
                    "archive_member": "data/1sar_round5.pdb",
                    "r_work": round5_rwork,
                    "r_free": round5_rfree,
                    "source": "EVAL_1sar_cdba2c07_2026-09-23_M_round5_rwork / M_round5_rfree",
                },
                "round6_intermediate_phenix": {
                    "archive_member": "data/1sar_round6.pdb",
                    "r_work": round6_rwork,
                    "r_free": round6_rfree,
                    "source": "EVAL_1sar_cdba2c07_2026-09-23_M_round6_rwork / M_round6_rfree",
                },
                "round7_log_reported_unarchived": {
                    "archive_member": None,
                    "r_work": 0.1488,
                    "r_free": 0.1989,
                    "delta_r_work_vs_round4": round(0.1488 - phenix_final_rwork, 4),
                    "delta_r_free_vs_round4": round(0.1989 - phenix_final_rfree, 4),
                    "source": "claude_iterations.log:510 (coordinate file absent from archive)",
                },
            },
        },
    }

    missing_conflicting_and_inapplicable_evidence = [
        {
            "category": "missing_final_artifact",
            "id": "1sar_round7_coordinates_absent_from_archive",
            "severity": "critical_provenance_boundary",
            "description": (
                "The trajectory log (claude_iterations.log:510, :752) reports a "
                "round-7 model with R-work = 0.1488, R-free = 0.1989, 159 waters "
                "(1,654 heavy atoms), and restored B:97:SO4, but that coordinate "
                "file was never packaged into cdba2c07-daff-4f60-ae96-12452b3a5fbb_artifacts.zip. "
                "Instead, data/1sar_final.pdb is the round-4 PHENIX model "
                "(SHA-256 8cbc1650f8be5a3833f98833fa514ec7d490c2c3bb9aa930413abac05e2a510b, "
                "146 waters, 1,641 heavy atoms), while intermediate rounds 5 and 6 "
                "were saved separately as data/1sar_round5.pdb and data/1sar_round6.pdb."
            ),
            "handling_rule": (
                "Assess data/1sar_final.pdb strictly as the round-4 packaged model "
                "and record round 7 as an unverified log-only claim."
            ),
        },
        {
            "category": "inapplicable_or_unevaluable_clause",
            "id": "1sar_deposited_r_free_null",
            "severity": "clause_inapplicable",
            "description": (
                "Deposited PDB entry 1SAR (data/pdb_mtz/1sar_deposited.pdb, 1991 "
                "deposition) records 'REMARK 3 FREE R VALUE : NULL'. Any pass "
                "criterion requiring comparison against deposited R-free is "
                "mathematically unevaluable."
            ),
            "handling_rule": (
                "deposition_applicability(None) returns deposition_clause='unevaluable'."
            ),
        },
        {
            "category": "inapplicable_or_unevaluable_clause",
            "id": "1sar_aimless_merged_mtz_input",
            "severity": "tool_precondition_mismatch",
            "description": (
                "Running aimless on data/1sar.mtz fails with 'hkl_unmerge_list::prepare "
                "- EMPTY' because data/1sar.mtz contains merged structure-factor "
                "amplitudes (F-obs, SIGF-obs) rather than unmerged diffraction intensities."
            ),
            "handling_rule": (
                "Record T13 merging statistics (R_merge, R_meas, R_pim, CC1/2) as "
                "not_applicable_merged_input and use ctruncate / phenix.model_vs_data "
                "for merged reflection diagnostics."
            ),
        },
        {
            "category": "reflection_retention_boundary",
            "id": "1sar_mtz_zero_f_work_reflections_invalidated",
            "severity": "audit_warning",
            "description": (
                "11 input work reflections with F=0.0 in data/1sar.mtz became NaN "
                "in data/1sar_final.mtz (reducing eligible reflections from 7,228 "
                "to 7,217) and 14 all-NaN HKL rows were added. All 723 free-R "
                "reflections and 6,494 positive-F work reflections are preserved."
            ),
            "handling_rule": (
                "Compute independent R-factor checks against the original input "
                "data/1sar.mtz and report the 11 invalidated zero-F work reflections "
                "explicitly."
            ),
        },
        {
            "category": "missing_raw_oracle_outputs_on_historical_rows",
            "id": "1sar_historical_april_may_raw_logs_unretained",
            "severity": "partial_baseline_coverage",
            "description": (
                "Historical April/May oracle measurements in EVAL_1sar_cdba2c07_2026-09-23.yaml "
                "(such as starting-model phenix.model_vs_data R-work 0.3334 / R-free "
                "0.3956 and mmtbx.validation_summary clashscore 31.66) are preserved "
                "from frozen evaluation rows without retained raw stdout logs, whereas "
                "start-vs-final coordinate, B-factor, atom/water/ligand inventory, "
                "and MTZ reflection-retention metrics are freshly derived directly "
                "from the archived PDB and MTZ bytes."
            ),
            "handling_rule": (
                "Distinguish directly recomputed byte-level audit metrics from "
                "transcribed historical evaluation rows."
            ),
        },
    ]

    return {
        "case_id": "1sar_cdba2c07_2026-09-23",
        "pass_criterion_bindings": bindings,
        "assessment_verdict_status": verdict_status,
        "provenance": {
            "archive_path": _display_path(archive_path),
            "archive_sha256": actual_archive_sha256,
            "starting_model": {
                "subject_ref": "artifact:cdba2c07-daff-4f60-ae96-12452b3a5fbb#data/1sar.pdb",
                "archive_member": "data/1sar.pdb",
                "sha256": sha256_bytes(start_pdb_bytes),
                "inventory": start_inventory,
            },
            "packaged_final_model": {
                "subject_ref": qds["subject_ref"],
                "archive_member": "data/1sar_final.pdb",
                "sha256": final_pdb_sha256,
                "packaged_stage_description": (
                    "Round-4 PHENIX refinement output packaged as data/1sar_final.pdb; "
                    "subsequent rounds 5 and 6 exist in the archive as data/1sar_round5.pdb "
                    "and data/1sar_round6.pdb, while reported round 7 is absent."
                ),
                "inventory": final_inventory,
            },
            "deposited_reference_model": {
                "subject_ref": "pdb:1SAR",
                "path": _display_path(deposited_pdb_path),
                "sha256": actual_deposited_sha256,
                **deposition_info,
            },
            "reflection_data": {
                "input_mtz_member": "data/1sar.mtz",
                "input_mtz_sha256": start_mtz_sha256,
                "output_mtz_member": "data/1sar_final.mtz",
                "output_mtz_sha256": sha256_bytes(final_mtz_bytes),
            },
            "retained_records": {
                "qds_path": _display_path(qds_path),
                "eval_path": _display_path(eval_path),
                "coordinate_and_t13_audit_path": _display_path(coord_audit_path),
            },
        },
        "implementation_agreement": implementation_agreement,
        "final_model_quality_support": final_model_quality_support,
        "change_relative_to_input": change_relative_to_input,
        "missing_conflicting_and_inapplicable_evidence": (
            missing_conflicting_and_inapplicable_evidence
        ),
    }


def _has_verified_matching_baseline(
    row: dict[str, Any],
    block: dict[str, Any],
    baseline_input_hashes: dict[str, Any] | None,
    baseline_convention_matches: bool,
) -> bool:
    """Return True only when cross-file baseline provenance is explicitly verified."""
    if not baseline_convention_matches or not isinstance(baseline_input_hashes, dict):
        return False
    target_hashes = block.get("input_hashes") or row.get("input_hashes")
    if not isinstance(target_hashes, dict):
        return False
    for key in ("model", "mtz", "cif"):
        base_val = baseline_input_hashes.get(key)
        targ_val = target_hashes.get(key)
        if not isinstance(base_val, str) or not base_val or base_val != targ_val:
            return False
    return True


def _extract_control_row_metrics(
    row: dict[str, Any],
    state_key: str | None = None,
    baseline_pre: dict[str, Any] | None = None,
    *,
    baseline_input_hashes: dict[str, Any] | None = None,
    baseline_convention_matches: bool = False,
) -> dict[str, Any]:
    """Normalize a single row from round3_bench, round4_recover, or round10_recover."""
    if not isinstance(row, dict) or not isinstance(row.get("pdb_id"), str):
        raise ValueError("Control row must be a dict with string 'pdb_id'")
    pdb_id = row["pdb_id"]
    d_min = _require_finite_float(row.get("d_min"), f"{pdb_id}.d_min")
    block = row[state_key] if state_key is not None else row
    if not isinstance(block, dict):
        raise ValueError(f"Control row {pdb_id!r} block must be a dict")
    numbers = block.get("numbers")
    if not isinstance(numbers, dict):
        raise ValueError(f"Control row {pdb_id!r} numbers must be a dict")
    direct_pre = block.get("pre")
    can_use_cross_file_baseline = (
        direct_pre is None
        and baseline_pre is not None
        and _has_verified_matching_baseline(
            row,
            block,
            baseline_input_hashes=baseline_input_hashes,
            baseline_convention_matches=baseline_convention_matches,
        )
    )
    pre = (
        direct_pre
        if isinstance(direct_pre, dict)
        else (baseline_pre if can_use_cross_file_baseline else {})
    ) or {}
    post = block.get("post")
    flags = block.get("flags")
    if not isinstance(flags, dict):
        raise ValueError(f"Control row {pdb_id!r} flags must be a dict")

    d_phenix = _require_finite_float(
        numbers.get("d_phenix"), f"{pdb_id}.numbers.d_phenix"
    )
    d_gemmi = _require_finite_float(
        numbers.get("d_gemmi"), f"{pdb_id}.numbers.d_gemmi"
    )
    d_refmac = (
        _require_finite_float(
            numbers.get("d_refmac"), f"{pdb_id}.numbers.d_refmac"
        )
        if numbers.get("d_refmac") is not None
        else None
    )
    clash_pre = _require_finite_float(
        numbers.get("clash_pre"), f"{pdb_id}.numbers.clash_pre"
    )
    clash_post = _require_finite_float(
        numbers.get("clash_post"), f"{pdb_id}.numbers.clash_post"
    )
    d_favored_pp = _require_finite_float(
        numbers.get("d_favored_pp"), f"{pdb_id}.numbers.d_favored_pp"
    )
    d_rota_pp = _require_finite_float(
        numbers.get("d_rota_pp"), f"{pdb_id}.numbers.d_rota_pp"
    )
    d_zbond = (
        _require_finite_float(
            numbers.get("d_zbond"), f"{pdb_id}.numbers.d_zbond"
        )
        if numbers.get("d_zbond") is not None
        else None
    )
    shift_unmasked = _require_finite_float(
        numbers.get("shift_unmasked"), f"{pdb_id}.numbers.shift_unmasked"
    )
    shift_all_residue = _require_finite_float(
        block.get("shift_all_residue"), f"{pdb_id}.shift_all_residue"
    )
    n_protected_fixed = _require_finite_int(
        numbers.get("n_protected_fixed"), f"{pdb_id}.numbers.n_protected_fixed"
    )

    pre_phenix_r_free = (
        _require_finite_float(
            pre.get("rfree_phenix"), f"{pdb_id}.pre.rfree_phenix"
        )
        if pre.get("rfree_phenix") is not None
        else None
    )
    pre_gemmi_r_free = (
        _require_finite_float(
            pre.get("rfree_gemmi"), f"{pdb_id}.pre.rfree_gemmi"
        )
        if pre.get("rfree_gemmi") is not None
        else None
    )
    pre_refmac_block = pre.get("refmac")
    pre_refmac_r_free = (
        _require_finite_float(
            pre_refmac_block.get("r_free"), f"{pdb_id}.pre.refmac.r_free"
        )
        if isinstance(pre_refmac_block, dict)
        and pre_refmac_block.get("r_free") is not None
        else None
    )

    if isinstance(post, dict):
        post_phenix_r_free = _require_finite_float(
            post.get("rfree_phenix"), f"{pdb_id}.post.rfree_phenix"
        )
        post_gemmi_r_free = _require_finite_float(
            post.get("rfree_gemmi"), f"{pdb_id}.post.rfree_gemmi"
        )
        post_refmac_block = post.get("refmac")
        post_refmac_r_free = (
            _require_finite_float(
                post_refmac_block.get("r_free"), f"{pdb_id}.post.refmac.r_free"
            )
            if isinstance(post_refmac_block, dict)
            and post_refmac_block.get("r_free") is not None
            else None
        )
    elif isinstance(direct_pre, dict) or can_use_cross_file_baseline:
        post_phenix_r_free = (
            round(pre_phenix_r_free + d_phenix, 4)
            if pre_phenix_r_free is not None
            else None
        )
        post_gemmi_r_free = (
            round(pre_gemmi_r_free + d_gemmi, 4)
            if pre_gemmi_r_free is not None
            else None
        )
        post_refmac_r_free = (
            round(pre_refmac_r_free + d_refmac, 4)
            if (pre_refmac_r_free is not None and d_refmac is not None)
            else None
        )
    else:
        post_phenix_r_free = None
        post_gemmi_r_free = None
        post_refmac_r_free = None

    return {
        "pdb_id": pdb_id,
        "d_min": d_min,
        "state": block.get("state", row.get("subject", state_key or "unknown")),
        "d_phenix": d_phenix,
        "d_gemmi": d_gemmi,
        "d_refmac": d_refmac,
        "abs_diff_phenix_gemmi_delta": round(abs(d_phenix - d_gemmi), 6),
        "abs_diff_phenix_refmac_delta": (
            round(abs(d_phenix - d_refmac), 6) if d_refmac is not None else None
        ),
        "clash_pre": clash_pre,
        "clash_post": clash_post,
        "clash_delta": round(clash_post - clash_pre, 4),
        "d_favored_pp": d_favored_pp,
        "d_rota_pp": d_rota_pp,
        "d_zbond": d_zbond,
        "shift_unmasked": shift_unmasked,
        "shift_all_residue": shift_all_residue,
        "n_protected_fixed": n_protected_fixed,
        "post_phenix_r_free": post_phenix_r_free,
        "post_gemmi_r_free": post_gemmi_r_free,
        "post_refmac_r_free": post_refmac_r_free,
        "pre_phenix_r_free": pre_phenix_r_free,
        "pre_gemmi_r_free": pre_gemmi_r_free,
        "pre_refmac_r_free": pre_refmac_r_free,
        "two_path_only": bool(block.get("two_path_only", d_refmac is None)),
        "flags": {
            "F-data": bool(flags["F-data"]),
            "F-geom": bool(flags["F-geom"]),
            "F-protected": bool(flags["F-protected"]),
            "F-shift": bool(flags["F-shift"]),
        },
        "conflict_count": len(block.get("conflicts", [])),
        "conflicts": list(block.get("conflicts", [])),
        "historical_script_verdict": block.get("verdict"),
    }


def _median_and_iqr(
    values: list[float],
    total_count: int | None = None,
) -> dict[str, Any]:
    """Compute availability status, counts, median, mean, min, p25, p75, and max."""
    checked_values = [
        _require_finite_float(v, f"_median_and_iqr.values[{idx}]")
        for idx, v in enumerate(values)
    ]
    effective_total = (
        len(checked_values)
        if total_count is None
        else _require_finite_int(total_count, "_median_and_iqr.total_count")
    )
    if effective_total < len(checked_values):
        raise ValueError(
            f"_median_and_iqr total_count={effective_total} is smaller than "
            f"len(values)={len(checked_values)}"
        )
    if not checked_values:
        return {
            "status": "unavailable",
            "count": 0,
            "unavailable_count": effective_total,
            "median": None,
            "mean": None,
            "min": None,
            "p25": None,
            "p75": None,
            "max": None,
        }
    arr = np.array(checked_values, dtype=float)
    return {
        "status": "available",
        "count": len(checked_values),
        "unavailable_count": effective_total - len(checked_values),
        "median": round(float(np.median(arr)), 4),
        "mean": round(float(np.mean(arr)), 4),
        "min": round(float(np.min(arr)), 4),
        "p25": round(float(np.percentile(arr, 25)), 4),
        "p75": round(float(np.percentile(arr, 75)), 4),
        "max": round(float(np.max(arr)), 4),
    }


def summarize_control_cohort(
    cohort_id: str,
    description: str,
    source_path: Path,
    normalized_rows: list[dict[str, Any]],
    pass_criterion_bindings: list[dict[str, Any]] | None = None,
    source_sha256: str | None = None,
) -> dict[str, Any]:
    """Summarize a 22-structure control cohort across the three core questions."""
    bindings = list(pass_criterion_bindings or [])
    n_total = len(normalized_rows)

    d_phenix_vals = [r["d_phenix"] for r in normalized_rows]
    d_gemmi_vals = [r["d_gemmi"] for r in normalized_rows]
    d_refmac_vals = [
        r["d_refmac"] for r in normalized_rows if r["d_refmac"] is not None
    ]
    pg_diffs = [r["abs_diff_phenix_gemmi_delta"] for r in normalized_rows]
    pr_diffs = [
        r["abs_diff_phenix_refmac_delta"]
        for r in normalized_rows
        if r["abs_diff_phenix_refmac_delta"] is not None
    ]
    clash_deltas = [r["clash_delta"] for r in normalized_rows]
    clash_posts = [r["clash_post"] for r in normalized_rows]
    post_rfree_phenix = [
        r["post_phenix_r_free"]
        for r in normalized_rows
        if r["post_phenix_r_free"] is not None
    ]
    post_rfree_gemmi = [
        r["post_gemmi_r_free"]
        for r in normalized_rows
        if r["post_gemmi_r_free"] is not None
    ]
    post_rfree_refmac = [
        r["post_refmac_r_free"]
        for r in normalized_rows
        if r["post_refmac_r_free"] is not None
    ]
    d_favored_vals = [r["d_favored_pp"] for r in normalized_rows]
    d_rota_vals = [r["d_rota_pp"] for r in normalized_rows]
    d_zbond_vals = [r["d_zbond"] for r in normalized_rows if r["d_zbond"] is not None]
    shifts = [r["shift_all_residue"] for r in normalized_rows]

    n_conflicts = sum(1 for r in normalized_rows if r["conflict_count"] > 0)
    n_f_data = sum(1 for r in normalized_rows if r["flags"]["F-data"])
    n_f_geom = sum(1 for r in normalized_rows if r["flags"]["F-geom"])
    n_f_prot = sum(1 for r in normalized_rows if r["flags"]["F-protected"])
    n_f_shift = sum(1 for r in normalized_rows if r["flags"]["F-shift"])

    n_rfree_improved_phenix = sum(1 for r in normalized_rows if r["d_phenix"] < 0.0)
    n_rfree_unchanged_phenix = sum(
        1 for r in normalized_rows if abs(r["d_phenix"]) < 1e-9
    )
    n_rfree_regressed_phenix = sum(1 for r in normalized_rows if r["d_phenix"] > 0.0)
    n_clash_non_worse = sum(1 for r in normalized_rows if r["clash_delta"] <= 0.0)

    return {
        "cohort_id": cohort_id,
        "description": description,
        "source_file": _display_path(source_path),
        "source_sha256": (
            source_sha256 if source_sha256 is not None else sha256_file(source_path)
        ),
        "target_count": n_total,
        "refmac_evaluable_target_count": len(d_refmac_vals),
        "two_path_only_target_count": n_total - len(d_refmac_vals),
        "pass_criterion_bindings": bindings,
        "assessment_verdict_status": resolve_verdict_status(bindings, None),
        "implementation_agreement": {
            "phenix_vs_gemmi_delta_r_free_abs_diff": _median_and_iqr(
                pg_diffs, total_count=n_total
            ),
            "phenix_vs_refmac_delta_r_free_abs_diff": _median_and_iqr(
                pr_diffs, total_count=n_total
            ),
            "targets_with_solver_or_metric_conflicts": n_conflicts,
            "d_phenix_summary": _median_and_iqr(d_phenix_vals, total_count=n_total),
            "d_gemmi_summary": _median_and_iqr(d_gemmi_vals, total_count=n_total),
            "d_refmac_summary": _median_and_iqr(d_refmac_vals, total_count=n_total),
        },
        "final_model_quality_support": {
            "post_phenix_r_free": _median_and_iqr(
                post_rfree_phenix, total_count=n_total
            ),
            "post_gemmi_r_free": _median_and_iqr(post_rfree_gemmi, total_count=n_total),
            "post_refmac_r_free": _median_and_iqr(
                post_rfree_refmac, total_count=n_total
            ),
            "post_clashscore": _median_and_iqr(clash_posts, total_count=n_total),
        },
        "change_relative_to_input": {
            "delta_r_free_phenix": _median_and_iqr(d_phenix_vals, total_count=n_total),
            "delta_r_free_gemmi": _median_and_iqr(d_gemmi_vals, total_count=n_total),
            "delta_r_free_refmac": _median_and_iqr(d_refmac_vals, total_count=n_total),
            "delta_clashscore": _median_and_iqr(clash_deltas, total_count=n_total),
            "delta_ramachandran_favored_pp": _median_and_iqr(
                d_favored_vals, total_count=n_total
            ),
            "delta_rotamer_outliers_pp": _median_and_iqr(
                d_rota_vals, total_count=n_total
            ),
            "delta_refmac_zbond": _median_and_iqr(d_zbond_vals, total_count=n_total),
            "all_residue_shift_angstrom": _median_and_iqr(shifts, total_count=n_total),
            "direction_counts": {
                "phenix_r_free_improved": n_rfree_improved_phenix,
                "phenix_r_free_unchanged": n_rfree_unchanged_phenix,
                "phenix_r_free_regressed": n_rfree_regressed_phenix,
                "clashscore_improved_or_unchanged": n_clash_non_worse,
                "clashscore_regressed": n_total - n_clash_non_worse,
            },
            "diagnostic_flag_counts": {
                "F-data": n_f_data,
                "F-geom": n_f_geom,
                "F-protected": n_f_prot,
                "F-shift": n_f_shift,
            },
        },
        "per_target_rows": normalized_rows,
    }


def _read_verified_control_json(
    path: Path,
    expected_sha256: str,
    source_label: str,
) -> tuple[dict[str, Any], str]:
    """Read a fixed retained control-cohort JSON source once as bytes, verify its SHA-256 digest before parsing, and return the parsed dictionary and verified digest."""
    raw_text, actual_sha256 = _read_verified_1sar_text(
        path, expected_sha256, source_label
    )
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid control-cohort JSON in {path}") from exc
    if not isinstance(parsed, dict) or not isinstance(parsed.get("rows"), list):
        raise ValueError(f"Invalid control-cohort JSON structure in {path}")
    return parsed, actual_sha256


def evaluate_control_cohorts(
    round3_path: Path = DEFAULT_ROUND3_BENCH,
    round4_path: Path = DEFAULT_ROUND4_RECOVER,
    round10_path: Path = DEFAULT_ROUND10_RECOVER,
) -> dict[str, Any]:
    """Evaluate the fixed retained unchanged, damaged, and recovered control cohorts.

    Fixed retained-bundle boundary: this specialized control-cohort reader admits
    the three retained 22-structure control inputs (`round3_path`, `round4_path`,
    `round10_path`) at default or alternate file paths only when their exact byte
    SHA-256 digests match the retained control bundle BEFORE parsing or deriving
    any cohort summary or scientific conclusion.
    """
    round3_data, round3_sha256 = _read_verified_control_json(
        round3_path,
        EXPECTED_ROUND3_BENCH_SHA256,
        "Round 3 unchanged/SA control cohort",
    )
    round4_data, round4_sha256 = _read_verified_control_json(
        round4_path,
        EXPECTED_ROUND4_RECOVER_SHA256,
        "Round 4 damaged/recovered control cohort",
    )
    round10_data, round10_sha256 = _read_verified_control_json(
        round10_path,
        EXPECTED_ROUND10_RECOVER_SHA256,
        "Round 10 recovered control cohort",
    )

    baseline_rows_by_pdb = {
        r["pdb_id"]: r
        for r in round3_data["rows"]
        if r.get("subject") == "null" and "pre" in r
    }

    null_rows = [
        _extract_control_row_metrics(r)
        for r in round3_data["rows"]
        if r.get("subject") == "null"
    ]
    sa_rows = [
        _extract_control_row_metrics(r)
        for r in round3_data["rows"]
        if r.get("subject") == "sa"
    ]
    perturbed_rows = [
        _extract_control_row_metrics(
            r,
            state_key="perturbed",
            baseline_pre=baseline_rows_by_pdb.get(r["pdb_id"], {}).get("pre"),
            baseline_input_hashes=baseline_rows_by_pdb.get(r["pdb_id"], {}).get(
                "input_hashes"
            ),
            baseline_convention_matches=False,
        )
        for r in round4_data["rows"]
    ]
    round4_recovered_rows = [
        _extract_control_row_metrics(
            r,
            state_key="recovered",
            baseline_pre=baseline_rows_by_pdb.get(r["pdb_id"], {}).get("pre"),
            baseline_input_hashes=baseline_rows_by_pdb.get(r["pdb_id"], {}).get(
                "input_hashes"
            ),
            baseline_convention_matches=False,
        )
        for r in round4_data["rows"]
    ]
    round10_recovered_rows = [
        _extract_control_row_metrics(
            r,
            state_key="recovered",
            baseline_pre=baseline_rows_by_pdb.get(r["pdb_id"], {}).get("pre"),
            baseline_input_hashes=baseline_rows_by_pdb.get(r["pdb_id"], {}).get(
                "input_hashes"
            ),
            baseline_convention_matches=False,
        )
        for r in round10_data["rows"]
    ]

    cohorts = {
        "unchanged_null": summarize_control_cohort(
            cohort_id="unchanged_null",
            description=(
                "Null re-refinement control (subject='null', n=22; 19 REFMAC-evaluable, "
                "3 two-path-only): deposited structures re-refined without intentional "
                "perturbation to calibrate baseline noise and expose cross-solver "
                "disagreement flags."
            ),
            source_path=round3_path,
            normalized_rows=null_rows,
            source_sha256=round3_sha256,
        ),
        "damaged_sa": summarize_control_cohort(
            cohort_id="damaged_sa",
            description=(
                "Simulated-annealing damaged control (subject='sa', n=22; 19 REFMAC-evaluable, "
                "3 two-path-only): models perturbed via simulated annealing to verify that "
                "coordinate and fit regressions are separated from solver disagreements."
            ),
            source_path=round3_path,
            normalized_rows=sa_rows,
            source_sha256=round3_sha256,
        ),
        "damaged_dynamics": summarize_control_cohort(
            cohort_id="damaged_dynamics",
            description=(
                "Cartesian-dynamics damaged control (stop_at_diff=0.5 A, state='perturbed', "
                "n=22; 19 REFMAC-evaluable, 3 two-path-only): controlled coordinate "
                "perturbation prior to recovery refinement (within-round deltas retained; "
                "absolute post R-free not recorded in round4_recover.json)."
            ),
            source_path=round4_path,
            normalized_rows=perturbed_rows,
            source_sha256=round4_sha256,
        ),
        "recovered_unprotonated_solvent": summarize_control_cohort(
            cohort_id="recovered_unprotonated_solvent",
            description=(
                "Round-4 recovery refinement after Cartesian-dynamics perturbation "
                "(state='recovered', n=22; 19 REFMAC-evaluable under BREF ISOT, 3 two-path-only): "
                "baseline recovery refinement without ordered_solvent=True and without "
                "phenix.ready_set explicit riding hydrogens (within-round deltas retained; "
                "absolute post R-free not recorded in round4_recover.json)."
            ),
            source_path=round4_path,
            normalized_rows=round4_recovered_rows,
            source_sha256=round4_sha256,
        ),
        "recovered_protonated_ordered_solvent": summarize_control_cohort(
            cohort_id="recovered_protonated_ordered_solvent",
            description=(
                "Round-10 multi-factor recovery refinement (state='osol_h', n=22; "
                "21 REFMAC-evaluable under ANISOU-aware BREF ANIS, 1 two-path-only): "
                "combines regenerated Cartesian-dynamics perturbations with phenix.ready_set "
                "explicit riding hydrogens followed by ordered_solvent=True (within-round "
                "deltas retained; absolute post R-free not recorded in round10_recover.json)."
            ),
            source_path=round10_path,
            normalized_rows=round10_recovered_rows,
            source_sha256=round10_sha256,
        ),
    }

    return {
        "cohorts": cohorts,
        "cross_cohort_findings": {
            "unchanged_control_invariance": (
                "In unchanged_null (subject='null', n=22), phenix and gemmi delta R-free "
                "agree tightly (median |d_phenix - d_gemmi| = 0.0007), while REFMAC5 "
                "(evaluable on 19/22 targets; 3/22 two-path-only: 9YGW, 8R5K, 8QXQ) "
                "shows smaller deltas (median d_refmac = +0.0018 vs median d_phenix = +0.0035) "
                "and triggers solver-disagreement notes on 2/22 targets (2VXN on F-data, "
                "where PHENIX/gemmi are positive (+0.0053 / +0.0067) while REFMAC sign is "
                "negative (-0.0122); 9TXE on F-geom, where cctbx worsening stands down "
                "against improved REFMAC zBOND (-0.043)). Separating Question 1 "
                "(implementation agreement) from Question 3 (change relative to input) "
                "keeps solver-convention differences distinct from physical model changes."
            ),
            "damaged_control_sensitivity": (
                "Both damaged_sa (median d_phenix = +0.0209, 18/22 F-data flags, 2/22 "
                "F-shift flags) and damaged_dynamics (median d_phenix = +0.2629, median "
                "shift = 0.2465 A, 22/22 F-data and 22/22 F-shift flags, 13/22 F-geom flags) "
                "show strong R-free regressions across phenix, gemmi, and REFMAC5, "
                "confirming cross-solver sensitivity to physical model degradation."
            ),
            "recovered_control_protonation_contrast": (
                "Historical protocol comparison between recovered_unprotonated_solvent "
                "(round 4, n=22; 19/22 REFMAC-evaluable under BREF ISOT) and "
                "recovered_protonated_ordered_solvent (round 10, n=22; 21/22 REFMAC-evaluable "
                "under ANISOU-aware BREF ANIS) reflects a multi-factor protocol change "
                "rather than a single-variable ablation: between round 4 and round 10, "
                "Cartesian-dynamics perturbations were regenerated in intermediate rounds, "
                "refinement added phenix.ready_set explicit riding hydrogens plus a second "
                "ordered_solvent=True pass (round 6 tested ordered_solvent=True without "
                "hydrogens and still flagged 18/22 targets on F-data, median d_phenix = +0.0155), "
                "and REFMAC5 switched from BREF ISOT to ANISOU-aware BREF ANIS (rounds 9-10). "
                "Across these combined changes, median d_phenix shifts from +0.0188 "
                "(22/22 F-data flags) in round 4 to +0.0063 (9/22 F-data flags; 8/22 improved "
                "below pre-perturbation R-free) in round 10, while median all-residue shift "
                "remains small (0.0435 A in round 4 vs 0.0422 A in round 10)."
            ),
        },
    }


def build_full_assessment_report(
    pass_criterion_bindings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the complete JSON assessment report for 1SAR and the 5 control cohorts."""
    bindings = list(pass_criterion_bindings or [])
    resolve_verdict_status(bindings, None)
    return {
        "schema_version": "1.0.0",
        "generated_at": "2026-10-18",
        "assessment_design": {
            "three_separated_questions": [
                {
                    "id": "implementation_agreement",
                    "question": "Do implementations agree on the same observable?",
                    "purpose": (
                        "Isolate cross-tool parameterization differences (bulk-solvent "
                        "masking, scaling, restraint dictionaries, hydrogen placement, "
                        "secondary-structure definitions) on the exact same coordinate "
                        "and reflection inputs."
                    ),
                },
                {
                    "id": "final_model_quality_support",
                    "question": "What supports the final model's quality for its intended use?",
                    "purpose": (
                        "Report absolute fit, stereochemistry, data quality, and fold/"
                        "interface metrics on the final model with explicit resolution "
                        "and applicability context."
                    ),
                },
                {
                    "id": "change_relative_to_input",
                    "question": "What improved or regressed relative to the actual input?",
                    "purpose": (
                        "Quantify direct before-vs-after coordinate shifts, B-factor "
                        "shifts, atom/water/ligand inventory changes, reflection-set "
                        "retention, and R-factor/geometry deltas relative to the "
                        "actual starting model."
                    ),
                },
            ],
            "uncalibrated_verdict_policy": (
                "When pass_criterion_bindings is empty ([]), assessment_verdict_status "
                "is unconditionally 'informational'; non-empty pass_criterion_bindings "
                "and unknown requested_status values raise ValueError until criterion "
                "evaluation is implemented."
            ),
        },
        "case_study_1sar": assess_1sar_case_study(
            pass_criterion_bindings=bindings,
        ),
        "control_cohorts_evaluation": evaluate_control_cohorts(),
    }


def serialize_assessment_report(report: dict[str, Any]) -> str:
    """Serialize an assessment report to strict JSON, rejecting NaN and Inf."""
    return json.dumps(report, indent=2, sort_keys=False, allow_nan=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for generating the before/after refinement assessment JSON."""
    parser = argparse.ArgumentParser(
        description=(
            "Run the before/after refinement assessment on the retained 1SAR "
            "X-ray archive and the 22-structure unchanged/damaged/recovered "
            "control cohorts."
        )
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Optional path to write the JSON assessment report.",
    )
    args = parser.parse_args(argv)

    report = build_full_assessment_report()
    serialized = serialize_assessment_report(report)
    if args.output_json is not None:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(serialized, encoding="utf-8")
    else:
        sys.stdout.write(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
