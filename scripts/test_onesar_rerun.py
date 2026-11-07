#!/usr/bin/env python3
"""Hermetic unit tests for 1SAR input admission, MTZ projection, and PHENIX R-factor reconciliation.

Runs under the repository Python environment with zero PHENIX/CCP4/Gemmi
execution, zero vendor library imports, and zero network access.
"""

from __future__ import annotations

import ast
import contextlib
import copy
import hashlib
import io
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import types
import unittest
import warnings
import zipfile
from pathlib import Path
from typing import Any, Callable, Mapping
from unittest import mock

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import onesar_phenix_measure  # noqa: E402
import onesar_rerun  # noqa: E402
import refinement_cache  # noqa: E402
import toolchain  # noqa: E402


REPO_ROOT = _SCRIPTS_DIR.parent
COMMITTED_ARCHIVE = REPO_ROOT / onesar_rerun.ARCHIVE_REL_PATH


def _card(text: str) -> bytes:
    return text.ljust(80).encode("ascii")


def _build_synthetic_mtz(
    rows: list[tuple[float, ...]],
    *,
    columns: list[tuple[str, str, str]] | None = None,
    datasets: list[tuple[int, str]] | None = None,
    cell: tuple[float, float, float, float, float, float] = (
        64.897,
        78.323,
        38.792,
        90.0,
        90.0,
        90.0,
    ),
    syminf: str = "SYMINF   4 4 P 19 'P 21 21 21' PG222",
    symm_cards: tuple[str, ...] = (
        "SYMM X,Y,Z",
        "SYMM -X+1/2,-Y,Z+1/2",
        "SYMM -X,Y+1/2,-Z+1/2",
        "SYMM X+1/2,-Y+1/2,-Z",
    ),
    valm: str = "VALM NAN",
) -> bytes:
    """Construct a synthetic little-endian MTZ byte stream for pure unit testing."""
    if columns is None:
        columns = [
            ("H", "H", "1"),
            ("K", "H", "1"),
            ("L", "H", "1"),
            ("F-obs", "F", "1"),
            ("SIGF-obs", "Q", "1"),
            ("R-free-flags", "I", "1"),
        ]
    if datasets is None:
        datasets = [(1, "Original-experimental-data-mapped-to-asu")]
    ncols = len(columns)
    nrows = len(rows)
    flat_values: list[float] = []
    for row in rows:
        if len(row) != ncols:
            raise ValueError(f"Row width {len(row)} != ncols {ncols}")
        flat_values.extend(float(v) for v in row)
    data_bytes = struct.pack(f"<{len(flat_values)}f", *flat_values)
    header_offset = (80 + len(data_bytes)) // 4 + 1

    cards: list[bytes] = [
        _card("VERS MTZ:V1.1"),
        _card("TITLE synthetic test mtz"),
        _card(f"NCOL {ncols:8d} {nrows:12d} {0:8d}"),
        _card(
            f"CELL {cell[0]:9.4f} {cell[1]:9.4f} {cell[2]:9.4f} "
            f"{cell[3]:8.4f} {cell[4]:8.4f} {cell[5]:8.4f}"
        ),
        _card("SORT    1   2   3   0   0"),
        _card(syminf),
    ]
    for symm in symm_cards:
        cards.append(_card(symm))
    cards.append(_card("RESO 0.00200000 0.25000000"))
    cards.append(_card(valm))
    cards.append(_card(f"NDIF {len(datasets):8d}"))
    for d_id, d_name in datasets:
        cards.append(_card(f"PROJECT {d_id:7d} project"))
        cards.append(_card(f"CRYSTAL {d_id:7d} crystal"))
        cards.append(_card(f"DATASET {d_id:7d} {d_name}"))
        cards.append(
            _card(
                f"DCELL {d_id:9d} {cell[0]:9.4f} {cell[1]:9.4f} {cell[2]:9.4f} "
                f"{cell[3]:8.4f} {cell[4]:8.4f} {cell[5]:8.4f}"
            )
        )
        cards.append(_card(f"DWAVEL {d_id:8d}    1.00000"))
    for name, ctype, d_id in columns:
        cards.append(_card(f"COLUMN {name:<30s} {ctype} 0.0 100.0 {d_id}"))
    cards.append(_card("END"))

    preamble = (
        b"MTZ "
        + struct.pack("<I", header_offset)
        + bytes([0x44, 0x41, 0x00, 0x00])
        + b"\x00" * 68
    )
    return preamble + data_bytes + b"".join(cards)


def _build_synthetic_map_mtz_pair(
    records_2fofc: list[dict[str, Any]],
    records_fofc: list[dict[str, Any]],
    *,
    cell: tuple[float, float, float, float, float, float] = (
        64.897,
        78.323,
        38.792,
        90.0,
        90.0,
        90.0,
    ),
) -> tuple[bytes, bytes]:
    """Build synthetic phx_maps.mtz and PHX_OBS_PAIR_ONLY.mtz byte streams."""
    fofc_by_hkl = {
        tuple(rec["hkl"]): rec for rec in records_fofc
    }
    maps_rows: list[tuple[float, ...]] = []
    pair_rows: list[tuple[float, ...]] = []
    for rec2 in records_2fofc:
        h, k, l = rec2["hkl"]
        rec1 = fofc_by_hkl[(h, k, l)]
        # Emulate iotbx.mtz phase storage in [0, 360) degrees float32
        ph2 = float(rec2["phase_deg"]) % 360.0
        ph1 = float(rec1["phase_deg"]) % 360.0
        maps_rows.append(
            (
                float(h),
                float(k),
                float(l),
                float(rec2["amplitude"]),
                ph2,
                float(rec1["amplitude"]),
                ph1,
            )
        )
        pair_rows.append(
            (
                float(h),
                float(k),
                float(l),
                float(rec2["amplitude"]),
                ph2,
            )
        )
    maps_bytes = _build_synthetic_mtz(
        maps_rows,
        columns=[
            ("H", "H", "1"),
            ("K", "H", "1"),
            ("L", "H", "1"),
            ("2FOFCWT", "F", "1"),
            ("PH2FOFCWT", "P", "1"),
            ("FOFCWT", "F", "1"),
            ("PHFOFCWT", "P", "1"),
        ],
        cell=cell,
    )
    pair_bytes = _build_synthetic_mtz(
        pair_rows,
        columns=[
            ("H", "H", "1"),
            ("K", "H", "1"),
            ("L", "H", "1"),
            ("2FOFCWT", "F", "1"),
            ("PH2FOFCWT", "P", "1"),
        ],
        cell=cell,
    )
    return maps_bytes, pair_bytes


def _make_reconciliation_fixture() -> tuple[
    dict[str, Any], dict[str, Any], dict[str, str], bytes, bytes
]:
    """Create a pure-math synthetic input ledger, helper payload, and map MTZs."""
    nan = float("nan")
    mtz_bytes = _build_synthetic_mtz(
        [
            # Eligible work rows (flag=0), including one zero-F and one negative-F row
            (1, 0, 0, 100.0, 2.0, 0.0),
            (0, 1, 0, 200.0, 3.0, 0.0),
            (0, 0, 1, 0.0, 1.5, 0.0),
            (1, 1, 0, -5.0, 1.2, 0.0),
            (1, 1, 1, 150.0, 2.5, 0.0),
            # Eligible free rows (flag=1)
            (2, 0, 0, 80.0, 1.8, 1.0),
            (0, 2, 0, 120.0, 2.2, 1.0),
            # Ineligible all-NaN padding row (F, SIGF, flag all NaN)
            (0, 0, 2, nan, nan, nan),
        ]
    )
    input_ledger = onesar_rerun.build_input_hkl_ledger(mtz_bytes)

    # Suppose extract_xtal_data regularizes out the zero-F (0,0,1) and negative-F (1,1,0)
    # rows, leaving 5 extracted reflections; and f_model outlier removal drops (1,1,1),
    # leaving 2 work reflections [(1,0,0), (0,1,0)] and 2 free reflections [(2,0,0), (0,2,0)].
    scale_k1_w = 0.5
    scale_k1_t = 0.6
    scale_k1 = 0.54

    # Work: (1,0,0) fo=100, |fm_raw|=180 -> |fm_scaled_w|=90; diff=10
    #       (0,1,0) fo=200, |fm_raw|=420 -> |fm_scaled_w|=210; diff=10
    # work_num = 20, work_den = 300, r_work = 20 / 300
    # Free: (2,0,0) fo=80,  |fm_raw|=100 -> |fm_scaled_t|=60; diff=20
    #       (0,2,0) fo=120, |fm_raw|=250 -> |fm_scaled_t|=150; diff=30
    # free_num = 50, free_den = 200, r_free = 50 / 200 = 0.25
    # All (using scale_k1 = 0.54):
    #   (1,0,0): |100 - 0.54*180| = |100 - 97.2| = 2.8
    #   (0,1,0): |200 - 0.54*420| = |200 - 226.8| = 26.8
    #   (2,0,0): |80  - 0.54*100| = |80  - 54.0| = 26.0
    #   (0,2,0): |120 - 0.54*250| = |120 - 135.0| = 15.0
    # all_num = 70.6, all_den = 500.0, r_all = 70.6 / 500.0 = 0.1412
    r_work = 20.0 / 300.0
    r_free = 50.0 / 200.0
    all_num = 70.6
    all_den = 500.0
    r_all = all_num / all_den

    vendor_shas = {
        key: hashlib.sha256(key.encode("utf-8")).hexdigest()
        for key in onesar_rerun.PHENIX_VENDOR_SOURCE_RELPATHS
    }
    vendor_modules = {
        key: {
            "module_name": key,
            "configured_path": f"/opt/phenix/lib/python3.9/site-packages/{rel}",
            "resolved_path": f"/opt/phenix/lib/python3.9/site-packages/{rel}",
            "sha256": vendor_shas[key],
        }
        for key, rel in onesar_rerun.PHENIX_VENDOR_SOURCE_RELPATHS.items()
    }

    scatterer_records = [
        {
            "label": "PDB=\" N   VAL A   1 \"",
            "scattering_type": "N",
            "site_frac": [0.1, 0.2, 0.3],
            "site_cart": [6.4897, 15.6646, 11.6376],
            "occupancy": 1.0,
            "u_iso": 0.25,
            "u_star": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "use_u_iso": True,
            "use_u_aniso": False,
        },
        {
            "label": "PDB=\" CA  VAL A   1 \"",
            "scattering_type": "C",
            "site_frac": [0.12, 0.22, 0.32],
            "site_cart": [7.78764, 17.23106, 12.41344],
            "occupancy": 1.0,
            "u_iso": 0.28,
            "u_star": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "use_u_iso": True,
            "use_u_aniso": False,
        },
    ]
    snap = onesar_phenix_measure.snapshot_scatterer_records(scatterer_records)
    xrs_invariance = onesar_phenix_measure.compare_scatterer_snapshots(
        snap, copy.deepcopy(snap), copy.deepcopy(snap)
    )

    final_hkls = [
        ([1, 0, 0], 100.0, 2.0, False),
        ([0, 1, 0], 200.0, 3.0, False),
        ([2, 0, 0], 80.0, 1.8, True),
        ([0, 2, 0], 120.0, 2.2, True),
    ]
    map_records_2fofc = [
        {
            "hkl": [1, 0, 0],
            "real": 10.0,
            "imag": 0.0,
            "amplitude": 10.0,
            "phase_deg": 0.0,
            "is_centric": True,
        },
        {
            "hkl": [0, 1, 0],
            "real": -12.0,
            "imag": 0.0,
            "amplitude": 12.0,
            "phase_deg": 180.0,
            "is_centric": True,
        },
        {
            "hkl": [2, 0, 0],
            "real": 0.0,
            "imag": 8.0,
            "amplitude": 8.0,
            "phase_deg": 90.0,
            "is_centric": False,
        },
        {
            "hkl": [0, 2, 0],
            "real": 0.0,
            "imag": -6.0,
            "amplitude": 6.0,
            "phase_deg": -90.0,
            "is_centric": False,
        },
    ]
    map_records_fofc = [
        {
            "hkl": [1, 0, 0],
            "real": 2.0,
            "imag": 0.0,
            "amplitude": 2.0,
            "phase_deg": 0.0,
            "is_centric": True,
        },
        {
            "hkl": [0, 1, 0],
            "real": -1.5,
            "imag": 0.0,
            "amplitude": 1.5,
            "phase_deg": 180.0,
            "is_centric": True,
        },
        {
            "hkl": [2, 0, 0],
            "real": 0.0,
            "imag": 1.25,
            "amplitude": 1.25,
            "phase_deg": 90.0,
            "is_centric": False,
        },
        {
            "hkl": [0, 2, 0],
            "real": 0.0,
            "imag": -0.75,
            "amplitude": 0.75,
            "phase_deg": -90.0,
            "is_centric": False,
        },
    ]
    maps_mtz_bytes, obs_pair_mtz_bytes = _build_synthetic_map_mtz_pair(
        map_records_2fofc, map_records_fofc
    )
    map_params = {
        "acentrics_scale": 2.0,
        "centrics_pre_scale": 1.0,
        "exclude_free_r_reflections": False,
        "fill_missing": False,
        "isotropize": True,
        "sharp": False,
    }

    runtime_cell = onesar_rerun.ccp4_mtz_float32_unit_cell(
        input_ledger["crystallographic_context"]["cell_a_b_c_alpha_beta_gamma"]
    )
    ca_rt, cb_rt, cc_rt = runtime_cell[0], runtime_cell[1], runtime_cell[2]

    payload = {
        "schema_version": 1,
        "algorithm": "mmtbx.model_vs_data.first_block_public_api",
        "expected_resolved_prefix": "/opt/phenix",
        "expected_phenix_version": toolchain.PHENIX_VERSION,
        "runtime_environment": {
            "python_version": "3.9.18",
            "sys_executable": "/opt/phenix/bin/python3.9",
            "resolved_sys_executable": "/opt/phenix/bin/python3.9",
            "sys_prefix": "/opt/phenix",
            "resolved_sys_prefix": "/opt/phenix",
            "vendor_modules": vendor_modules,
        },
        "crystal_symmetry": {
            "unit_cell": list(runtime_cell),
            "space_group_symbol": "P 21 21 21 (No. 19)",
            "space_group_number": 19,
            "space_group_operators_xyz": [
                "x,y,z",
                "-x+1/2,-y,z+1/2",
                "-x,y+1/2,-z+1/2",
                "x+1/2,-y+1/2,-z",
            ],
        },
        "extraction": {
            "labels": ["F-obs", "SIGF-obs"],
            "r_free_flags_label": "R-free-flags",
            "test_flag_value": 1,
            "r_free_flags_generate": False,
            "ignore_r_free_flags": False,
            "keep_going": False,
            "err": [],
            "log_text": "extract_xtal_data synthetic log\n",
            "applied_pdb_header_resolution_cut": False,
        },
        "diagnostics": {
            "extract_xtal_data_log": "extract_xtal_data synthetic log\n",
            "model_manager_log": "model.manager synthetic log\n",
            "fmodel_update_all_scales_log": "update_all_scales synthetic log\n",
            "failure": None,
        },
        "resolution_ranges": {
            "extracted_pre_fmodel": {
                "d_max": cb_rt,
                "d_min": 1.0
                / math.sqrt(
                    (1.0 / ca_rt) ** 2
                    + (1.0 / cb_rt) ** 2
                    + (1.0 / cc_rt) ** 2
                ),
            },
            "final_effective": {"d_max": cb_rt, "d_min": ca_rt / 2.0},
            "actual_work": {"d_max": cb_rt, "d_min": ca_rt},
            "actual_free": {"d_max": cb_rt / 2.0, "d_min": ca_rt / 2.0},
        },
        "xray_structure_invariance": xrs_invariance,
        "scales_and_rfactors": {
            "r_work": r_work,
            "r_free": r_free,
            "r_all": r_all,
            "r_free_r_work_gap": r_free - r_work,
            "scale_k1_w": scale_k1_w,
            "scale_k1_t": scale_k1_t,
            "scale_k1": scale_k1,
            "work_numerator": 20.0,
            "work_denominator": 300.0,
            "free_numerator": 50.0,
            "free_denominator": 200.0,
            "all_numerator": all_num,
            "all_denominator": all_den,
            "work_count": 2,
            "free_count": 2,
            "final_effective_count": 4,
            "extracted_pre_fmodel_count": 5,
        },
        "extracted_pre_fmodel": [
            {"hkl": [1, 0, 0], "f_obs": 100.0, "sigf_obs": 2.0, "is_free": False},
            {"hkl": [0, 1, 0], "f_obs": 200.0, "sigf_obs": 3.0, "is_free": False},
            {"hkl": [1, 1, 1], "f_obs": 150.0, "sigf_obs": 2.5, "is_free": False},
            {"hkl": [2, 0, 0], "f_obs": 80.0, "sigf_obs": 1.8, "is_free": True},
            {"hkl": [0, 2, 0], "f_obs": 120.0, "sigf_obs": 2.2, "is_free": True},
        ],
        "final_effective": [
            {"hkl": hkl, "f_obs": fo, "sigf_obs": sigfo, "is_free": is_free}
            for hkl, fo, sigfo, is_free in final_hkls
        ],
        "actual_work": [
            {
                "hkl": [1, 0, 0],
                "f_obs": 100.0,
                "sigf_obs": 2.0,
                "f_model_real": 108.0,
                "f_model_imag": 144.0,
                "f_model_amplitude": 180.0,
                "f_model_scaled_with_k1_w_real": 54.0,
                "f_model_scaled_with_k1_w_imag": 72.0,
                "f_model_scaled_with_k1_w_amplitude": 90.0,
            },
            {
                "hkl": [0, 1, 0],
                "f_obs": 200.0,
                "sigf_obs": 3.0,
                "f_model_real": 252.0,
                "f_model_imag": 336.0,
                "f_model_amplitude": 420.0,
                "f_model_scaled_with_k1_w_real": 126.0,
                "f_model_scaled_with_k1_w_imag": 168.0,
                "f_model_scaled_with_k1_w_amplitude": 210.0,
            },
        ],
        "actual_free": [
            {
                "hkl": [2, 0, 0],
                "f_obs": 80.0,
                "sigf_obs": 1.8,
                "f_model_real": 60.0,
                "f_model_imag": 80.0,
                "f_model_amplitude": 100.0,
                "f_model_scaled_with_k1_t_real": 36.0,
                "f_model_scaled_with_k1_t_imag": 48.0,
                "f_model_scaled_with_k1_t_amplitude": 60.0,
            },
            {
                "hkl": [0, 2, 0],
                "f_obs": 120.0,
                "sigf_obs": 2.2,
                "f_model_real": 150.0,
                "f_model_imag": 200.0,
                "f_model_amplitude": 250.0,
                "f_model_scaled_with_k1_t_real": 90.0,
                "f_model_scaled_with_k1_t_imag": 120.0,
                "f_model_scaled_with_k1_t_amplitude": 150.0,
            },
        ],
        "map_coefficients": {
            "2mFo-DFc": {
                "map_type": "2mFo-DFc",
                "amplitude_label": "2FOFCWT",
                "phase_label": "PH2FOFCWT",
                "parameters": dict(map_params),
                "coefficient_semantics": "combine_includes_scales",
                "n_reflections": 4,
                "centric_count": 2,
                "acentric_count": 2,
                "records": copy.deepcopy(map_records_2fofc),
            },
            "mFo-DFc": {
                "map_type": "mFo-DFc",
                "amplitude_label": "FOFCWT",
                "phase_label": "PHFOFCWT",
                "parameters": dict(map_params),
                "coefficient_semantics": "combine_includes_scales",
                "n_reflections": 4,
                "centric_count": 2,
                "acentric_count": 2,
                "records": copy.deepcopy(map_records_fofc),
            },
            "mtz_supplements": {
                "phx_maps_sha256": hashlib.sha256(maps_mtz_bytes).hexdigest(),
                "phx_maps_columns": [
                    "H",
                    "K",
                    "L",
                    "2FOFCWT",
                    "PH2FOFCWT",
                    "FOFCWT",
                    "PHFOFCWT",
                ],
                "obs_pair_only_sha256": hashlib.sha256(obs_pair_mtz_bytes).hexdigest(),
                "obs_pair_only_columns": [
                    "H",
                    "K",
                    "L",
                    "2FOFCWT",
                    "PH2FOFCWT",
                ],
            },
        },
    }
    return input_ledger, payload, vendor_shas, maps_mtz_bytes, obs_pair_mtz_bytes


class TestOnesarSubjectAndArchiveAdmission(unittest.TestCase):
    def test_allowed_subjects_and_forbidden_r7(self) -> None:
        expected_members = {
            "start": ("data/1sar.pdb", "start"),
            "R4": ("data/1sar_final.pdb", "final"),
            "R5": ("data/1sar_round5.pdb", "intermediate"),
            "R6": ("data/1sar_round6.pdb", "intermediate"),
        }
        for subj, (member, stage) in expected_members.items():
            spec = onesar_rerun.resolve_subject_spec(subj)
            self.assertEqual(spec["subject_id"], subj)
            self.assertEqual(spec["member"], member)
            self.assertEqual(spec["stage"], stage)
            self.assertEqual(len(spec["sha256"]), 64)

        for forbidden in (
            "R7",
            "round7",
            "1sar_round7",
            "data/1sar_round7.pdb",
            "deposited",
            "1sar_deposited",
            "R1",
            "",
        ):
            with self.assertRaises(ValueError):
                onesar_rerun.resolve_subject_spec(forbidden)

    def test_committed_archive_members_match_preregistered_hashes(self) -> None:
        self.assertTrue(COMMITTED_ARCHIVE.is_file())
        for subj in ("start", "R4", "R5", "R6"):
            spec = onesar_rerun.resolve_subject_spec(subj)
            data = onesar_rerun.read_verified_archive_member(
                COMMITTED_ARCHIVE,
                spec["member"],
                expected_archive_sha256=onesar_rerun.ARCHIVE_SHA256,
                expected_member_sha256=spec["sha256"],
            )
            self.assertEqual(hashlib.sha256(data).hexdigest(), spec["sha256"])

        mtz_bytes = onesar_rerun.read_verified_archive_member(
            COMMITTED_ARCHIVE,
            onesar_rerun.MTZ_MEMBER,
            expected_archive_sha256=onesar_rerun.ARCHIVE_SHA256,
            expected_member_sha256=onesar_rerun.MTZ_SHA256,
        )
        self.assertEqual(
            hashlib.sha256(mtz_bytes).hexdigest(), onesar_rerun.MTZ_SHA256
        )

    def test_archive_member_admission_rejects_bad_hashes_duplicates_symlinks_and_paths(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)
            zip_path = tmp_dir / "test.zip"
            payload = b"HEADER    TEST\nEND\n"
            payload_sha = hashlib.sha256(payload).hexdigest()

            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("data/model.pdb", payload)
            zip_sha = hashlib.sha256(zip_path.read_bytes()).hexdigest()

            # Valid read succeeds.
            self.assertEqual(
                onesar_rerun.read_verified_archive_member(
                    zip_path,
                    "data/model.pdb",
                    expected_archive_sha256=zip_sha,
                    expected_member_sha256=payload_sha,
                ),
                payload,
            )

            # Wrong archive hash fails.
            with self.assertRaisesRegex(ValueError, "Archive SHA-256 mismatch"):
                onesar_rerun.read_verified_archive_member(
                    zip_path,
                    "data/model.pdb",
                    expected_archive_sha256="0" * 64,
                    expected_member_sha256=payload_sha,
                )

            # Wrong member hash fails.
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                onesar_rerun.read_verified_archive_member(
                    zip_path,
                    "data/model.pdb",
                    expected_archive_sha256=zip_sha,
                    expected_member_sha256="f" * 64,
                )

            # Unsafe member names fail before touching the archive.
            for bad_name in ("/etc/passwd", "../secret.pdb", "data\\model.pdb", "data//model.pdb"):
                with self.assertRaisesRegex(ValueError, "Unsafe archive member"):
                    onesar_rerun.read_verified_archive_member(
                        zip_path,
                        bad_name,
                        expected_archive_sha256=zip_sha,
                        expected_member_sha256=payload_sha,
                    )

            # Symlink to archive fails.
            link_zip = tmp_dir / "link.zip"
            link_zip.symlink_to(zip_path)
            with self.assertRaisesRegex(ValueError, "Regular non-symlink file"):
                onesar_rerun.read_verified_archive_member(
                    link_zip,
                    "data/model.pdb",
                    expected_archive_sha256=zip_sha,
                    expected_member_sha256=payload_sha,
                )

            # Duplicate member entries fail (suppress zipfile's own UserWarning on write).
            dup_zip = tmp_dir / "dup.zip"
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(dup_zip, "w") as zf:
                    zf.writestr("data/model.pdb", payload)
                    zf.writestr("data/model.pdb", payload)
            dup_sha = hashlib.sha256(dup_zip.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, "duplicate entries"):
                onesar_rerun.read_verified_archive_member(
                    dup_zip,
                    "data/model.pdb",
                    expected_archive_sha256=dup_sha,
                    expected_member_sha256=payload_sha,
                )

            # Symlink ZIP member entry fails.
            sym_zip = tmp_dir / "sym_member.zip"
            info = zipfile.ZipInfo("data/model.pdb")
            info.external_attr = (0o120777) << 16
            with zipfile.ZipFile(sym_zip, "w") as zf:
                zf.writestr(info, payload)
            sym_sha = hashlib.sha256(sym_zip.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, "is a symlink"):
                onesar_rerun.read_verified_archive_member(
                    sym_zip,
                    "data/model.pdb",
                    expected_archive_sha256=sym_sha,
                    expected_member_sha256=payload_sha,
                )


class TestFreshEvidenceRootBoundary(unittest.TestCase):
    def test_fresh_evidence_root_rejects_existing_symlinks_and_outside_repo(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_repo = Path(tmp).resolve(strict=True) / "repo"
            fake_repo.mkdir()

            fresh = onesar_rerun.prepare_fresh_evidence_root(
                fake_repo / "runs" / "canary_01", repo_root=fake_repo
            )
            self.assertTrue(fresh.is_dir())

            # Reusing an existing directory must fail with FileExistsError without mutating contents.
            marker = fresh / "marker.txt"
            marker.write_text("do not touch\n", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                onesar_rerun.prepare_fresh_evidence_root(fresh, repo_root=fake_repo)
            self.assertEqual(
                marker.read_text(encoding="utf-8"), "do not touch\n"
            )

            # Repo root itself is rejected.
            with self.assertRaisesRegex(ValueError, "strict subdirectory"):
                onesar_rerun.prepare_fresh_evidence_root(fake_repo, repo_root=fake_repo)

            # Path outside repo root is rejected.
            outside = Path(tmp).resolve(strict=True) / "outside_dir"
            with self.assertRaisesRegex(ValueError, "strict subdirectory"):
                onesar_rerun.prepare_fresh_evidence_root(outside, repo_root=fake_repo)

            # Raw '..' traversal segments in evidence_root or repo_root are rejected.
            for bad_target in (
                Path("runs/../escape"),
                Path(f"{fake_repo}/runs/../still_inside"),
            ):
                with self.assertRaisesRegex(
                    ValueError, "parent-directory traversal"
                ):
                    onesar_rerun.prepare_fresh_evidence_root(
                        bad_target, repo_root=fake_repo
                    )
            with self.assertRaisesRegex(
                ValueError, "parent-directory traversal"
            ):
                onesar_rerun.prepare_fresh_evidence_root(
                    fake_repo / "runs" / "canary_02",
                    repo_root=Path(f"{fake_repo}/../repo"),
                )

            # Symlink ancestor inside repo is rejected.
            real_sub = fake_repo / "real_sub"
            real_sub.mkdir()
            sym_sub = fake_repo / "sym_sub"
            sym_sub.symlink_to(real_sub)
            with self.assertRaisesRegex(ValueError, "must not be a symlink"):
                onesar_rerun.prepare_fresh_evidence_root(
                    sym_sub / "child", repo_root=fake_repo
                )

            # Dangling symlink at leaf is rejected.
            dangling_leaf = fake_repo / "runs" / "dangling_leaf"
            dangling_leaf.symlink_to(fake_repo / "runs" / "missing_target")
            with self.assertRaisesRegex(ValueError, "must not be a symlink"):
                onesar_rerun.prepare_fresh_evidence_root(
                    dangling_leaf, repo_root=fake_repo
                )

            # Symlinked repo_root or symlinked ancestor of repo_root is rejected.
            sym_repo = Path(tmp).resolve(strict=True) / "sym_repo"
            sym_repo.symlink_to(fake_repo)
            with self.assertRaisesRegex(
                ValueError, "Repository root must not be a symlink"
            ):
                onesar_rerun.prepare_fresh_evidence_root(
                    sym_repo / "runs" / "c3", repo_root=sym_repo
                )
            real_parent = Path(tmp).resolve(strict=True) / "real_parent"
            nested_repo = real_parent / "nested_repo"
            nested_repo.mkdir(parents=True)
            sym_parent = Path(tmp).resolve(strict=True) / "sym_parent"
            sym_parent.symlink_to(real_parent)
            with self.assertRaisesRegex(
                ValueError, "Repository root must not be a symlink"
            ):
                onesar_rerun.prepare_fresh_evidence_root(
                    sym_parent / "nested_repo" / "runs" / "c4",
                    repo_root=sym_parent / "nested_repo",
                )


class TestMtzProjectionAndHklLedger(unittest.TestCase):
    def test_committed_1sar_mtz_projection_and_ledger_counts(self) -> None:
        mtz_bytes = onesar_rerun.read_verified_archive_member(
            COMMITTED_ARCHIVE,
            onesar_rerun.MTZ_MEMBER,
            expected_archive_sha256=onesar_rerun.ARCHIVE_SHA256,
            expected_member_sha256=onesar_rerun.MTZ_SHA256,
        )
        projected_bytes, proj_summary = onesar_rerun.project_observation_mtz(mtz_bytes)
        self.assertEqual(proj_summary["input_ncols"], 16)
        self.assertEqual(proj_summary["projected_ncols"], 6)
        self.assertEqual(proj_summary["nrows"], 7248)
        self.assertEqual(
            proj_summary["projected_columns"],
            ["H", "K", "L", "F-obs", "SIGF-obs", "R-free-flags"],
        )
        self.assertEqual(proj_summary["retained_dataset_ids"], ["1"])
        self.assertEqual(
            set(proj_summary["crystallographic_context"]),
            {
                "cell_a_b_c_alpha_beta_gamma",
                "resolution_limits_inverse_a2",
                "symmetry",
            },
        )
        self.assertEqual(
            proj_summary["retention_audit"]["audit_status"], "preserved"
        )

        ledger = onesar_rerun.build_input_hkl_ledger(projected_bytes)
        self.assertEqual(
            ledger["crystallographic_context"],
            proj_summary["crystallographic_context"],
        )
        counts = ledger["counts"]
        self.assertEqual(counts["raw_total"], 7248)
        self.assertEqual(counts["raw_work"], 6505)
        self.assertEqual(counts["raw_free"], 723)
        self.assertEqual(counts["raw_unassigned"], 20)
        self.assertEqual(counts["eligible_total"], 7228)
        self.assertEqual(counts["eligible_work"], 6505)
        self.assertEqual(counts["eligible_free"], 723)
        self.assertEqual(counts["eligible_zero_f"], 11)
        self.assertEqual(counts["eligible_negative_f"], 0)
        self.assertEqual(counts["ineligible_total"], 20)
        self.assertEqual(counts["ineligible_nonfinite_f"], 20)
        self.assertEqual(counts["ineligible_nonpositive_or_nonfinite_sigf"], 0)
        self.assertEqual(counts["ineligible_unassigned_flag"], 20)
        self.assertEqual(len(ledger["ineligible_rows"]), 20)
        for row in ledger["ineligible_rows"]:
            self.assertIsNone(row["f_obs"])
            self.assertIsNone(row["sigf_obs"])
            self.assertIsNone(row["r_free_flag"])
            self.assertIsNone(row["is_free"])
            self.assertEqual(row["partition"], "unassigned")
            self.assertEqual(len(row["f_obs_word_hex"]), 8)
            self.assertEqual(len(row["sigf_obs_word_hex"]), 8)
            self.assertEqual(len(row["r_free_flag_word_hex"]), 8)

    def test_synthetic_mtz_eligibility_zero_negative_nan_and_failure_modes(
        self,
    ) -> None:
        nan = float("nan")
        # Include archived columns in synthetic MTZ to verify projection strips them.
        cols = [
            ("H", "H", "1"),
            ("K", "H", "1"),
            ("L", "H", "1"),
            ("F-obs", "F", "1"),
            ("SIGF-obs", "Q", "1"),
            ("R-free-flags", "I", "1"),
            ("F-model", "F", "2"),
            ("2FOFCWT", "F", "3"),
        ]
        datasets = [
            (1, "Original-experimental-data-mapped-to-asu"),
            (2, "Model-structure-factors"),
            (3, "Electron-density"),
        ]
        mtz_bytes = _build_synthetic_mtz(
            [
                (1, 0, 0, 50.0, 2.0, 0.0, 48.0, 51.0),
                (0, 1, 0, 0.0, 1.0, 0.0, 1.0, 0.5),
                (0, 0, 1, -3.5, 0.8, 1.0, 2.0, 0.2),
                (1, 1, 0, nan, nan, 0.0, 10.0, 10.0),
                (1, 0, 1, 25.0, 0.0, 1.0, 20.0, 22.0),
                (0, 1, 1, 30.0, -1.0, 0.0, 28.0, 29.0),
                (1, 1, 1, nan, nan, nan, nan, nan),
            ],
            columns=cols,
            datasets=datasets,
        )
        proj_bytes, proj_summary = onesar_rerun.project_observation_mtz(mtz_bytes)
        self.assertEqual(proj_summary["input_ncols"], 8)
        self.assertEqual(proj_summary["projected_ncols"], 6)
        self.assertEqual(proj_summary["retained_dataset_ids"], ["1"])

        ledger = onesar_rerun.build_input_hkl_ledger(proj_bytes)
        counts = ledger["counts"]
        self.assertEqual(counts["raw_total"], 7)
        self.assertEqual(counts["raw_work"], 4)
        self.assertEqual(counts["raw_free"], 2)
        self.assertEqual(counts["raw_unassigned"], 1)
        self.assertEqual(counts["eligible_total"], 3)
        self.assertEqual(counts["eligible_work"], 2)
        self.assertEqual(counts["eligible_free"], 1)
        self.assertEqual(counts["eligible_zero_f"], 1)
        self.assertEqual(counts["eligible_negative_f"], 1)
        self.assertEqual(counts["ineligible_total"], 4)
        self.assertEqual(counts["ineligible_nonfinite_f"], 2)
        self.assertEqual(counts["ineligible_nonpositive_or_nonfinite_sigf"], 2)
        self.assertEqual(counts["ineligible_unassigned_flag"], 1)
        self.assertTrue(ledger["eligible_by_hkl"]["0,1,0"]["is_zero_f"])
        self.assertTrue(ledger["eligible_by_hkl"]["0,0,1"]["is_negative_f"])
        unassigned_rows = [
            r for r in ledger["ineligible_rows"] if r["hkl"] == [1, 1, 1]
        ]
        self.assertEqual(len(unassigned_rows), 1)
        self.assertIsNone(unassigned_rows[0]["r_free_flag"])
        self.assertIsNone(unassigned_rows[0]["is_free"])
        self.assertEqual(unassigned_rows[0]["partition"], "unassigned")

        # Duplicate HKL fails.
        dup_mtz = _build_synthetic_mtz(
            [
                (1, 0, 0, 50.0, 2.0, 0.0),
                (1, 0, 0, 60.0, 2.5, 1.0),
            ]
        )
        with self.assertRaisesRegex(ValueError, "Duplicate Miller index"):
            onesar_rerun.build_input_hkl_ledger(dup_mtz)

        # NaN R-free flag on an eligible reflection fails.
        nan_flag_mtz = _build_synthetic_mtz(
            [
                (1, 0, 0, 50.0, 2.0, nan),
                (0, 1, 0, 60.0, 2.5, 1.0),
            ]
        )
        with self.assertRaisesRegex(ValueError, "Invalid R-free flag value"):
            onesar_rerun.build_input_hkl_ledger(nan_flag_mtz)

        # Undeclared integer flag (e.g. 2) on an eligible or ineligible reflection fails.
        bad_flag_mtz = _build_synthetic_mtz(
            [
                (1, 0, 0, 50.0, 2.0, 0.0),
                (0, 1, 0, 60.0, 2.5, 2.0),
            ]
        )
        with self.assertRaisesRegex(ValueError, "Invalid R-free flag value"):
            onesar_rerun.build_input_hkl_ledger(bad_flag_mtz)

        bad_ineligible_flag_mtz = _build_synthetic_mtz(
            [
                (1, 0, 0, 50.0, 2.0, 0.0),
                (0, 1, 0, 60.0, 2.5, 1.0),
                (0, 0, 1, nan, nan, 2.0),
            ]
        )
        with self.assertRaisesRegex(ValueError, "Invalid R-free flag value"):
            onesar_rerun.build_input_hkl_ledger(bad_ineligible_flag_mtz)

        # Non-integral Miller index fails.
        frac_hkl_mtz = _build_synthetic_mtz(
            [
                (1.5, 0, 0, 50.0, 2.0, 0.0),
                (0, 1, 0, 60.0, 2.5, 1.0),
            ]
        )
        with self.assertRaisesRegex(ValueError, "Non-integral Miller index"):
            onesar_rerun.build_input_hkl_ledger(frac_hkl_mtz)


class TestPhenixReconciliationAndPureHelpers(unittest.TestCase):
    def _reconcile(
        self,
        payload: dict[str, Any],
        ledger: dict[str, Any],
        vendor_shas: dict[str, str],
        maps_bytes: bytes,
        pair_bytes: bytes,
        **kwargs: Any,
    ) -> dict[str, Any]:
        return onesar_rerun.reconcile_phenix_rfactor_output(
            payload,
            ledger,
            expected_vendor_source_sha256=vendor_shas,
            phx_maps_mtz_bytes=maps_bytes,
            phx_obs_pair_only_mtz_bytes=pair_bytes,
            **kwargs,
        )

    def test_reconcile_valid_payload_and_stage_exclusions(self) -> None:
        ledger, payload, vendor_shas, maps_bytes, pair_bytes = (
            _make_reconciliation_fixture()
        )
        result = self._reconcile(
            payload, ledger, vendor_shas, maps_bytes, pair_bytes
        )
        self.assertEqual(result["reconciliation_status"], "verified")
        self.assertEqual(result["counts"]["raw_mtz_total"], 8)
        self.assertEqual(result["counts"]["input_eligible_total"], 7)
        self.assertEqual(result["counts"]["extracted_pre_fmodel_total"], 5)
        self.assertEqual(result["counts"]["final_effective_total"], 4)
        self.assertEqual(result["counts"]["actual_work_total"], 2)
        self.assertEqual(result["counts"]["actual_free_total"], 2)
        self.assertEqual(
            result["set_differences"]["raw_to_input_eligible_excluded_hkls"],
            [[0, 0, 2]],
        )
        self.assertEqual(
            result["set_differences"]["input_eligible_to_extracted_excluded_hkls"],
            [[0, 0, 1], [1, 1, 0]],
        )
        self.assertEqual(
            result["set_differences"]["extracted_to_final_effective_excluded_hkls"],
            [[1, 1, 1]],
        )
        self.assertAlmostEqual(
            result["rfactors"]["replayed_r_work"], 20.0 / 300.0, places=15
        )
        self.assertAlmostEqual(
            result["rfactors"]["replayed_r_free"], 0.25, places=15
        )
        self.assertAlmostEqual(
            result["rfactors"]["replayed_r_all"], 70.6 / 500.0, places=15
        )
        self.assertEqual(
            set(result["resolution_ranges"]),
            {
                "extracted_pre_fmodel",
                "final_effective",
                "actual_work",
                "actual_free",
            },
        )
        ca_f32, cb_f32 = (
            struct.unpack("<f", struct.pack("<f", 64.897))[0],
            struct.unpack("<f", struct.pack("<f", 78.323))[0],
        )
        self.assertAlmostEqual(
            result["resolution_ranges"]["actual_work"]["recomputed_d_max"],
            cb_f32,
            places=15,
        )
        self.assertAlmostEqual(
            result["resolution_ranges"]["actual_work"]["recomputed_d_min"],
            ca_f32,
            places=15,
        )
        self.assertAlmostEqual(
            result["resolution_ranges"]["actual_free"]["recomputed_d_max"],
            cb_f32 / 2.0,
            places=15,
        )
        self.assertAlmostEqual(
            result["resolution_ranges"]["actual_free"]["recomputed_d_min"],
            ca_f32 / 2.0,
            places=15,
        )

    def test_reconcile_rejects_work_free_scale_conflation(self) -> None:
        ledger, payload, vendor_shas, maps_bytes, pair_bytes = (
            _make_reconciliation_fixture()
        )
        # Substitute work scale_k1_w (0.5) in place of free scale_k1_t (0.6) on free set.
        bad = copy.deepcopy(payload)
        bad["actual_free"][0]["f_model_scaled_with_k1_t_real"] = 30.0
        bad["actual_free"][0]["f_model_scaled_with_k1_t_imag"] = 40.0
        bad["actual_free"][0]["f_model_scaled_with_k1_t_amplitude"] = 50.0
        with self.assertRaisesRegex(
            ValueError, "disagrees with scale_k1_t \\* \\|f_model_free\\|"
        ):
            self._reconcile(bad, ledger, vendor_shas, maps_bytes, pair_bytes)

        # Complex sign reversal or imaginary sign flip that preserves amplitude and
        # scalar R_work / R_free must be rejected for both actual_work and actual_free (#1021).
        work_sign_flip = copy.deepcopy(payload)
        work_sign_flip["actual_work"][0]["f_model_scaled_with_k1_w_real"] = (
            -54.0
        )
        work_sign_flip["actual_work"][0]["f_model_scaled_with_k1_w_imag"] = (
            -72.0
        )
        with self.assertRaisesRegex(
            ValueError,
            "actual_work\\[1,0,0\\] f_model_scaled_with_k1_w complex components .* disagree with scale_k1_w \\* f_model_work",
        ):
            self._reconcile(
                work_sign_flip, ledger, vendor_shas, maps_bytes, pair_bytes
            )

        work_imag_flip = copy.deepcopy(payload)
        work_imag_flip["actual_work"][1]["f_model_scaled_with_k1_w_imag"] = (
            -168.0
        )
        with self.assertRaisesRegex(
            ValueError,
            "actual_work\\[0,1,0\\] f_model_scaled_with_k1_w complex components .* disagree with scale_k1_w \\* f_model_work",
        ):
            self._reconcile(
                work_imag_flip, ledger, vendor_shas, maps_bytes, pair_bytes
            )

        free_sign_flip = copy.deepcopy(payload)
        free_sign_flip["actual_free"][0]["f_model_scaled_with_k1_t_real"] = (
            -36.0
        )
        free_sign_flip["actual_free"][0]["f_model_scaled_with_k1_t_imag"] = (
            -48.0
        )
        with self.assertRaisesRegex(
            ValueError,
            "actual_free\\[2,0,0\\] f_model_scaled_with_k1_t complex components .* disagree with scale_k1_t \\* f_model_free",
        ):
            self._reconcile(
                free_sign_flip, ledger, vendor_shas, maps_bytes, pair_bytes
            )

        free_imag_flip = copy.deepcopy(payload)
        free_imag_flip["actual_free"][1]["f_model_scaled_with_k1_t_imag"] = (
            -120.0
        )
        with self.assertRaisesRegex(
            ValueError,
            "actual_free\\[0,2,0\\] f_model_scaled_with_k1_t complex components .* disagree with scale_k1_t \\* f_model_free",
        ):
            self._reconcile(
                free_imag_flip, ledger, vendor_shas, maps_bytes, pair_bytes
            )

    def test_reconcile_rejects_partition_flag_and_set_violations(self) -> None:
        ledger, payload, vendor_shas, maps_bytes, pair_bytes = (
            _make_reconciliation_fixture()
        )

        # Overlapping work and free HKL fails.
        overlap = copy.deepcopy(payload)
        overlap["actual_free"].append(
            {
                "hkl": [1, 0, 0],
                "f_obs": 100.0,
                "sigf_obs": 2.0,
                "f_model_real": 100.0,
                "f_model_imag": 0.0,
                "f_model_amplitude": 100.0,
                "f_model_scaled_with_k1_t_real": 60.0,
                "f_model_scaled_with_k1_t_imag": 0.0,
                "f_model_scaled_with_k1_t_amplitude": 60.0,
            }
        )
        with self.assertRaisesRegex(ValueError, "non-disjoint"):
            self._reconcile(overlap, ledger, vendor_shas, maps_bytes, pair_bytes)

        # Swapped 0/1 flag assignment fails.
        swapped = copy.deepcopy(payload)
        swapped["extracted_pre_fmodel"][0]["is_free"] = True
        with self.assertRaisesRegex(ValueError, "Flag mismatch at extracted HKL"):
            self._reconcile(swapped, ledger, vendor_shas, maps_bytes, pair_bytes)

        # Unknown HKL not in raw MTZ fails.
        unknown = copy.deepcopy(payload)
        unknown["extracted_pre_fmodel"].append(
            {"hkl": [9, 9, 9], "f_obs": 50.0, "sigf_obs": 1.0, "is_free": False}
        )
        with self.assertRaisesRegex(ValueError, "absent from input MTZ raw ledger"):
            self._reconcile(unknown, ledger, vendor_shas, maps_bytes, pair_bytes)

        # Second-block PDB header cutoff flag fails.
        second_block = copy.deepcopy(payload)
        second_block["extraction"]["applied_pdb_header_resolution_cut"] = True
        with self.assertRaisesRegex(
            ValueError, "Second-block PDB header resolution cutoff"
        ):
            self._reconcile(
                second_block, ledger, vendor_shas, maps_bytes, pair_bytes
            )

    def test_reconcile_rejects_scatterer_mutation_map_contract_and_prefix_mix(
        self,
    ) -> None:
        ledger, payload, vendor_shas, maps_bytes, pair_bytes = (
            _make_reconciliation_fixture()
        )

        # Scatterer coordinate or occupancy drift fails even when top-level diff is spoofed.
        mut_xrs = copy.deepcopy(payload)
        mut_xrs["xray_structure_invariance"]["max_abs_occupancy_diff"] = 1e-4
        with self.assertRaisesRegex(
            ValueError, "Non-zero max_abs_occupancy_diff"
        ):
            self._reconcile(mut_xrs, ledger, vendor_shas, maps_bytes, pair_bytes)

        # Mutate a scatterer record in after_fmodel without updating its sha256 -> fails digest check.
        mut_snap = copy.deepcopy(payload)
        mut_snap["xray_structure_invariance"]["snapshots"]["after_fmodel"][
            "records"
        ][0]["site_cart"][0] += 0.01
        with self.assertRaisesRegex(
            ValueError, "after_fmodel snapshot sha256 mismatch"
        ):
            self._reconcile(mut_snap, ledger, vendor_shas, maps_bytes, pair_bytes)

        # Mutate a scatterer record AND recompute after_fmodel["sha256"] while spoofing
        # top-level after_fmodel_sha256 and max_abs_site_cart_diff=0 -> still caught!
        spoofed_snap = copy.deepcopy(payload)
        bad_records = copy.deepcopy(
            spoofed_snap["xray_structure_invariance"]["snapshots"]["after_fmodel"][
                "records"
            ]
        )
        bad_records[0]["occupancy"] = 0.75
        recomputed_bad = onesar_phenix_measure.snapshot_scatterer_records(
            bad_records
        )
        spoofed_snap["xray_structure_invariance"]["snapshots"]["after_fmodel"] = (
            recomputed_bad
        )
        with self.assertRaisesRegex(ValueError, "Scatterer snapshot mutated"):
            self._reconcile(
                spoofed_snap, ledger, vendor_shas, maps_bytes, pair_bytes
            )

        # Missing snapshots fails.
        no_snaps = copy.deepcopy(payload)
        del no_snaps["xray_structure_invariance"]["snapshots"]
        with self.assertRaisesRegex(
            ValueError,
            "xray_structure_invariance must contain snapshots",
        ):
            self._reconcile(no_snaps, ledger, vendor_shas, maps_bytes, pair_bytes)

        # Map coefficient fill_missing=True fails.
        bad_map = copy.deepcopy(payload)
        bad_map["map_coefficients"]["2mFo-DFc"]["parameters"]["fill_missing"] = True
        with self.assertRaisesRegex(
            ValueError, "parameters violate preregistered contract"
        ):
            self._reconcile(bad_map, ledger, vendor_shas, maps_bytes, pair_bytes)

        # Mixed vendor sys.prefix fails.
        bad_prefix = copy.deepcopy(payload)
        bad_prefix["runtime_environment"]["vendor_modules"][
            "vendor_mmtbx_model_vs_data"
        ]["resolved_path"] = "/other/install/mmtbx/model_vs_data.py"
        with self.assertRaisesRegex(ValueError, "escapes resolved_sys_prefix"):
            self._reconcile(
                bad_prefix, ledger, vendor_shas, maps_bytes, pair_bytes
            )

        # Same source hashes under a different installation prefix fails (#1013).
        other_prefix = copy.deepcopy(payload)
        other_prefix["expected_resolved_prefix"] = "/other/phenix"
        other_prefix["runtime_environment"]["sys_prefix"] = "/other/phenix"
        other_prefix["runtime_environment"]["resolved_sys_prefix"] = "/other/phenix"
        other_prefix["runtime_environment"]["sys_executable"] = (
            "/other/phenix/bin/python3.9"
        )
        other_prefix["runtime_environment"]["resolved_sys_executable"] = (
            "/other/phenix/bin/python3.9"
        )
        for mod_key, rel in onesar_rerun.PHENIX_VENDOR_SOURCE_RELPATHS.items():
            other_prefix["runtime_environment"]["vendor_modules"][mod_key][
                "resolved_path"
            ] = f"/other/phenix/lib/python3.9/site-packages/{rel}"
        with self.assertRaisesRegex(
            ValueError, "resolved_sys_prefix .* != expected_resolved_prefix"
        ):
            self._reconcile(
                other_prefix,
                ledger,
                vendor_shas,
                maps_bytes,
                pair_bytes,
                expected_resolved_prefix="/opt/phenix",
            )

        # Wrong PHENIX version in payload fails (#1013).
        bad_ver = copy.deepcopy(payload)
        bad_ver["expected_phenix_version"] = "2.0-5935"
        with self.assertRaisesRegex(
            ValueError, "expected_phenix_version '2.0-5935' !="
        ):
            self._reconcile(bad_ver, ledger, vendor_shas, maps_bytes, pair_bytes)

    def test_full_precision_counts_sums_and_r_all_reconciliation_1015(self) -> None:
        ledger, payload, vendor_shas, maps_bytes, pair_bytes = (
            _make_reconciliation_fixture()
        )

        # Per-HKL f_obs mismatch between final_effective and actual_work fails.
        bad_final_fo = copy.deepcopy(payload)
        bad_final_fo["final_effective"][0]["f_obs"] = 100.5
        with self.assertRaisesRegex(
            ValueError, "actual_work\\[1,0,0\\] F/SIGF .* disagrees with final_effective"
        ):
            self._reconcile(
                bad_final_fo, ledger, vendor_shas, maps_bytes, pair_bytes
            )

        # Per-HKL sigf_obs mismatch between final_effective and actual_free fails.
        bad_final_sigf = copy.deepcopy(payload)
        bad_final_sigf["final_effective"][2]["sigf_obs"] = 9.9
        with self.assertRaisesRegex(
            ValueError, "actual_free\\[2,0,0\\] F/SIGF .* disagrees with final_effective"
        ):
            self._reconcile(
                bad_final_sigf, ledger, vendor_shas, maps_bytes, pair_bytes
            )

        # Mutated work_count / free_count / final_effective_count / extracted_pre_fmodel_count fails.
        for count_key in (
            "work_count",
            "free_count",
            "final_effective_count",
            "extracted_pre_fmodel_count",
        ):
            bad_cnt = copy.deepcopy(payload)
            bad_cnt["scales_and_rfactors"][count_key] += 1
            with self.assertRaisesRegex(
                ValueError, "Reported scales_and_rfactors counts disagree"
            ):
                self._reconcile(
                    bad_cnt, ledger, vendor_shas, maps_bytes, pair_bytes
                )
            bool_cnt = copy.deepcopy(payload)
            bool_cnt["scales_and_rfactors"][count_key] = True
            with self.assertRaisesRegex(ValueError, "must be a positive int"):
                self._reconcile(
                    bool_cnt, ledger, vendor_shas, maps_bytes, pair_bytes
                )

        # Mutated numerator/denominator sums fail.
        for sum_key, err_pat in (
            ("work_numerator", "Reported work_numerator"),
            ("work_denominator", "Reported work_denominator"),
            ("free_numerator", "Reported free_numerator"),
            ("free_denominator", "Reported free_denominator"),
            ("all_numerator", "Reported all_numerator"),
            ("all_denominator", "Reported all_denominator"),
        ):
            bad_sum = copy.deepcopy(payload)
            bad_sum["scales_and_rfactors"][sum_key] += 1.0
            with self.assertRaisesRegex(ValueError, err_pat):
                self._reconcile(
                    bad_sum, ledger, vendor_shas, maps_bytes, pair_bytes
                )

        # Mutated r_all (e.g. 0.14 instead of 70.6 / 500.0 = 0.1412) fails.
        bad_r_all = copy.deepcopy(payload)
        bad_r_all["scales_and_rfactors"]["r_all"] = 0.14
        with self.assertRaisesRegex(
            ValueError, "Replayed r_all .* disagrees with native fmodel.r_all"
        ):
            self._reconcile(
                bad_r_all, ledger, vendor_shas, maps_bytes, pair_bytes
            )

    def test_resolution_ranges_reconciliation_and_cell_metric_1020(
        self,
    ) -> None:
        ledger, payload, vendor_shas, maps_bytes, pair_bytes = (
            _make_reconciliation_fixture()
        )

        # 0. Actual parser-produced ledger regression (#1008 / #1020):
        # mtz_crystallographic_context emits exact decimal string tokens (e.g. '64.897', '9E+1').
        parser_tokens = ledger["crystallographic_context"][
            "cell_a_b_c_alpha_beta_gamma"
        ]
        self.assertEqual(
            parser_tokens,
            ["64.897", "78.323", "38.792", "9E+1", "9E+1", "9E+1"],
        )
        self.assertTrue(all(type(tok) is str for tok in parser_tokens))
        self.assertEqual(
            onesar_rerun.validate_unit_cell_parameters(parser_tokens),
            (64.897, 78.323, 38.792, 90.0, 90.0, 90.0),
        )
        expected_f32_cell = struct.unpack(
            "<6f", struct.pack("<6f", 64.897, 78.323, 38.792, 90.0, 90.0, 90.0)
        )
        self.assertEqual(
            onesar_rerun.ccp4_mtz_float32_unit_cell(parser_tokens),
            expected_f32_cell,
        )
        baseline_res = self._reconcile(
            payload, ledger, vendor_shas, maps_bytes, pair_bytes
        )
        self.assertEqual(baseline_res["reconciliation_status"], "verified")
        self.assertEqual(
            baseline_res["crystal_symmetry"]["input_header_cell_tokens"],
            ["64.897", "78.323", "38.792", "9E+1", "9E+1", "9E+1"],
        )
        self.assertEqual(
            baseline_res["crystal_symmetry"]["input_header_cell_float64"],
            [64.897, 78.323, 38.792, 90.0, 90.0, 90.0],
        )
        self.assertEqual(
            baseline_res["crystal_symmetry"]["effective_runtime_unit_cell"],
            list(expected_f32_cell),
        )
        self.assertEqual(
            baseline_res["crystal_symmetry"]["max_abs_runtime_vs_float32_diff"],
            0.0,
        )
        self.assertEqual(
            baseline_res["crystal_symmetry"]["space_group_symbol"],
            "P 21 21 21 (No. 19)",
        )
        self.assertEqual(
            baseline_res["crystal_symmetry"]["space_group_number"], 19
        )
        self.assertEqual(
            baseline_res["crystal_symmetry"]["raw_space_group_operators_xyz"],
            [
                "x,y,z",
                "-x+1/2,-y,z+1/2",
                "-x,y+1/2,-z+1/2",
                "x+1/2,-y+1/2,-z",
            ],
        )
        self.assertEqual(
            baseline_res["crystal_symmetry"][
                "normalized_space_group_operators_xyz"
            ],
            [
                "-X+1/2,-Y,Z+1/2",
                "-X,Y+1/2,-Z+1/2",
                "X+1/2,-Y+1/2,-Z",
                "X,Y,Z",
            ],
        )
        self.assertEqual(
            baseline_res["crystal_symmetry"]["normalized_lookup_symbol"],
            "P212121",
        )
        self.assertEqual(
            baseline_res["crystal_symmetry"]["symmetry_normalization_policy"],
            onesar_rerun.SYMMETRY_OPERATOR_NORMALIZATION_POLICY,
        )
        # Reconciliation must preserve the original string tokens in the ledger untouched.
        self.assertEqual(
            ledger["crystallographic_context"]["cell_a_b_c_alpha_beta_gamma"],
            ["64.897", "78.323", "38.792", "9E+1", "9E+1", "9E+1"],
        )
        self.assertTrue(
            all(
                type(tok) is str
                for tok in ledger["crystallographic_context"][
                    "cell_a_b_c_alpha_beta_gamma"
                ]
            )
        )

        # Unrounded decimal-header resolution ranges or unrounded runtime unit_cell are rejected:
        unrounded_ranges_payload = copy.deepcopy(payload)
        unrounded_ranges_payload["resolution_ranges"]["extracted_pre_fmodel"][
            "d_max"
        ] = 78.323
        with self.assertRaisesRegex(
            ValueError,
            "resolution_ranges\\['extracted_pre_fmodel'\\]\\.d_max 78\\.322999999999993 disagrees with recomputed 78\\.322998046875000",
        ):
            self._reconcile(
                unrounded_ranges_payload,
                ledger,
                vendor_shas,
                maps_bytes,
                pair_bytes,
            )

        unrounded_runtime_cell_payload = copy.deepcopy(payload)
        unrounded_runtime_cell_payload["crystal_symmetry"]["unit_cell"] = [
            64.897,
            78.323,
            38.792,
            90.0,
            90.0,
            90.0,
        ]
        with self.assertRaisesRegex(
            ValueError,
            "phenix_payload\\.crystal_symmetry\\.unit_cell\\[0\\] \\(a\\) .* disagrees with installed CCP4/iotbx float32 conversion",
        ):
            self._reconcile(
                unrounded_runtime_cell_payload,
                ledger,
                vendor_shas,
                maps_bytes,
                pair_bytes,
            )

        for idx_symm, (bad_symm_fn, symm_err) in enumerate((
            (
                lambda p: p.pop("crystal_symmetry"),
                "phenix_payload missing crystal_symmetry section",
            ),
            (
                lambda p: p["crystal_symmetry"].update(
                    {"space_group_symbol": ""}
                ),
                "space_group_symbol must be a non-empty string",
            ),
            (
                lambda p: p["crystal_symmetry"].update(
                    {"unit_cell": [64.897, 78.323, 38.792]}
                ),
                "unit_cell must be a 6-element numeric sequence",
            ),
            (
                lambda p: p["crystal_symmetry"].update(
                    {
                        "unit_cell": [
                            "64.89700317382812",
                            78.322998046875,
                            38.79199981689453,
                            90.0,
                            90.0,
                            90.0,
                        ]
                    }
                ),
                "must be a finite number",
            ),
            (
                lambda p: p["crystal_symmetry"].update(
                    {
                        "unit_cell": [
                            65.0,
                            78.322998046875,
                            38.79199981689453,
                            90.0,
                            90.0,
                            90.0,
                        ]
                    }
                ),
                "disagrees with installed CCP4/iotbx float32 conversion",
            ),
            # Missing / invalid / inconsistent runtime space_group_number (#1025):
            (
                lambda p: p["crystal_symmetry"].pop("space_group_number"),
                "space_group_number must be an int in 1..230",
            ),
            (
                lambda p: p["crystal_symmetry"].update(
                    {"space_group_number": None}
                ),
                "space_group_number must be an int in 1..230",
            ),
            (
                lambda p: p["crystal_symmetry"].update(
                    {"space_group_number": True}
                ),
                "space_group_number must be an int in 1..230",
            ),
            (
                lambda p: p["crystal_symmetry"].update(
                    {"space_group_number": "19"}
                ),
                "space_group_number must be an int in 1..230",
            ),
            (
                lambda p: p["crystal_symmetry"].update(
                    {"space_group_number": 0}
                ),
                "space_group_number must be an int in 1..230",
            ),
            (
                lambda p: p["crystal_symmetry"].update(
                    {"space_group_number": 231}
                ),
                "space_group_number must be an int in 1..230",
            ),
            (
                lambda p: p["crystal_symmetry"].update(
                    {"space_group_number": 1}
                ),
                "space_group_number 1 disagrees with input_ledger space_group_number 19",
            ),
            # Missing / invalid / unsupported-spelling / inconsistent runtime space_group_operators_xyz (#1025):
            (
                lambda p: p["crystal_symmetry"].pop(
                    "space_group_operators_xyz"
                ),
                "space_group_operators_xyz must be a non-empty sequence",
            ),
            (
                lambda p: p["crystal_symmetry"].update(
                    {"space_group_operators_xyz": None}
                ),
                "space_group_operators_xyz must be a non-empty sequence",
            ),
            (
                lambda p: p["crystal_symmetry"].update(
                    {"space_group_operators_xyz": []}
                ),
                "space_group_operators_xyz must be a non-empty sequence",
            ),
            (
                lambda p: p["crystal_symmetry"].update(
                    {"space_group_operators_xyz": ["x,y,z"]}
                ),
                "space_group_operators_xyz .* disagrees with input_ledger symmetry\\.operators_xyz",
            ),
            (
                lambda p: p["crystal_symmetry"].update(
                    {
                        "space_group_operators_xyz": [
                            "x,y,z",
                            "X,Y,Z",
                            "-x,y+1/2,-z+1/2",
                            "x+1/2,-y+1/2,-z",
                        ]
                    }
                ),
                "contains duplicate normalized symmetry operators",
            ),
            (
                lambda p: p["crystal_symmetry"].update(
                    {
                        "space_group_operators_xyz": [
                            "x,y,z",
                            "-x+1/4,-y,z+1/2",
                            "-x,y+1/2,-z+1/2",
                            "x+1/2,-y+1/2,-z",
                        ]
                    }
                ),
                "space_group_operators_xyz .* disagrees with input_ledger symmetry\\.operators_xyz",
            ),
            (
                lambda p: p["crystal_symmetry"].update(
                    {
                        "space_group_operators_xyz": [
                            "x,y,z",
                            "-x+0.5,-y,z+0.5",
                            "-x,y+1/2,-z+1/2",
                            "x+1/2,-y+1/2,-z",
                        ]
                    }
                ),
                "uses unsupported or malformed symmetry operator spelling",
            ),
            (
                lambda p: p["crystal_symmetry"].update(
                    {
                        "space_group_operators_xyz": [
                            "x,y,z",
                            "1/2-x,-y,1/2+z",
                            "-x,y+1/2,-z+1/2",
                            "x+1/2,-y+1/2,-z",
                        ]
                    }
                ),
                "uses unsupported or malformed symmetry operator spelling",
            ),
            (
                lambda p: p["crystal_symmetry"].update(
                    {
                        "space_group_operators_xyz": [
                            "x,y,z",
                            "-x+2/4,-y,z+1/2",
                            "-x,y+1/2,-z+1/2",
                            "x+1/2,-y+1/2,-z",
                        ]
                    }
                ),
                "has non-canonical or unreduced translation",
            ),
            (
                lambda p: p["crystal_symmetry"].update(
                    {
                        "space_group_operators_xyz": [
                            "+x,y,z",
                            "-x+1/2,-y,z+1/2",
                            "-x,y+1/2,-z+1/2",
                            "x+1/2,-y+1/2,-z",
                        ]
                    }
                ),
                "uses unsupported or malformed symmetry operator spelling",
            ),
            (
                lambda p: p["crystal_symmetry"].update(
                    {
                        "space_group_operators_xyz": [
                            "a,b,c",
                            "-x+1/2,-y,z+1/2",
                            "-x,y+1/2,-z+1/2",
                            "x+1/2,-y+1/2,-z",
                        ]
                    }
                ),
                "uses unsupported or malformed symmetry operator spelling",
            ),
            # Non-empty wrong-group or inconsistent display string declarations (#1025):
            (
                lambda p: p["crystal_symmetry"].update(
                    {"space_group_symbol": "P 1 (No. 1)"}
                ),
                "declares space-group number 1, which disagrees with space_group_number 19",
            ),
            (
                lambda p: p["crystal_symmetry"].update(
                    {"space_group_symbol": "P 21 21 21 (No. 1)"}
                ),
                "declares space-group number 1, which disagrees with space_group_number 19",
            ),
            (
                lambda p: p["crystal_symmetry"].update(
                    {"space_group_symbol": "P 1 (No. 19)"}
                ),
                "normalized symbol 'P1'\\) disagrees with input_ledger space_group_symbol 'P212121'",
            ),
            (
                lambda p: p["crystal_symmetry"].update(
                    {"space_group_symbol": "C 21 21 21 (No. 19)"}
                ),
                "normalized symbol 'C212121'\\) disagrees with input_ledger space_group_symbol 'P212121'",
            ),
            (
                lambda p: p["crystal_symmetry"].update(
                    {"space_group_symbol": "P 21 21 21"}
                ),
                "must match installed cctbx\\.sgtbx\\.space_group_info\\.symbol_and_number\\(\\) format",
            ),
            (
                lambda p: p["crystal_symmetry"].update(
                    {"space_group_symbol": "arbitrary_nonempty_string"}
                ),
                "must match installed cctbx\\.sgtbx\\.space_group_info\\.symbol_and_number\\(\\) format",
            ),
        )):
            with self.subTest(idx=idx_symm, symm_err=symm_err):
                bad_symm_payload = copy.deepcopy(payload)
                bad_symm_fn(bad_symm_payload)
                with self.assertRaisesRegex(ValueError, symm_err):
                    self._reconcile(
                        bad_symm_payload,
                        ledger,
                        vendor_shas,
                        maps_bytes,
                        pair_bytes,
                    )

        # Also verify the real committed 1SAR MTZ parser-produced ledger cell tokens normalize cleanly:
        real_mtz_bytes = onesar_rerun.read_verified_archive_member(
            COMMITTED_ARCHIVE,
            onesar_rerun.MTZ_MEMBER,
            expected_archive_sha256=onesar_rerun.ARCHIVE_SHA256,
            expected_member_sha256=onesar_rerun.MTZ_SHA256,
        )
        real_proj_bytes, _ = onesar_rerun.project_observation_mtz(real_mtz_bytes)
        real_ledger = onesar_rerun.build_input_hkl_ledger(real_proj_bytes)
        real_cell_tokens = real_ledger["crystallographic_context"][
            "cell_a_b_c_alpha_beta_gamma"
        ]
        self.assertTrue(all(type(tok) is str for tok in real_cell_tokens))
        self.assertEqual(
            onesar_rerun.validate_unit_cell_parameters(real_cell_tokens),
            (64.897, 78.323, 38.792, 90.0, 90.0, 90.0),
        )

        # 1. Orthogonal cell closed-form check: (10, 20, 30, 90, 90, 90).
        orth_cell = (10.0, 20.0, 30.0, 90.0, 90.0, 90.0)
        self.assertAlmostEqual(
            onesar_rerun.compute_hkl_d_spacing([1, 0, 0], orth_cell),
            10.0,
            places=14,
        )
        self.assertAlmostEqual(
            onesar_rerun.compute_hkl_d_spacing([0, 1, 0], orth_cell),
            20.0,
            places=14,
        )
        self.assertAlmostEqual(
            onesar_rerun.compute_hkl_d_spacing([0, 0, 1], orth_cell),
            30.0,
            places=14,
        )
        self.assertAlmostEqual(
            onesar_rerun.compute_hkl_d_spacing([1, 2, 3], orth_cell),
            10.0 / math.sqrt(3.0),
            places=14,
        )

        # 2. Non-orthogonal hexagonal cell closed-form check: (10, 10, 20, 90, 90, 120).
        # Exact formula: 1/d^2 = (4/3)*(h^2 + h*k + k^2)/a^2 + l^2/c^2.
        hex_cell = (10.0, 10.0, 20.0, 90.0, 90.0, 120.0)
        self.assertAlmostEqual(
            onesar_rerun.compute_hkl_d_spacing([1, 0, 0], hex_cell),
            5.0 * math.sqrt(3.0),
            places=13,
        )
        self.assertAlmostEqual(
            onesar_rerun.compute_hkl_d_spacing([1, 1, 0], hex_cell),
            5.0,
            places=13,
        )
        self.assertAlmostEqual(
            onesar_rerun.compute_hkl_d_spacing([1, -1, 0], hex_cell),
            5.0 * math.sqrt(3.0),
            places=13,
        )
        self.assertAlmostEqual(
            onesar_rerun.compute_hkl_d_spacing([1, 1, 2], hex_cell),
            2.0 * math.sqrt(5.0),
            places=13,
        )
        self.assertAlmostEqual(
            onesar_rerun.compute_hkl_d_spacing([2, 0, 0], hex_cell),
            2.5 * math.sqrt(3.0),
            places=13,
        )

        # Full reconcile_phenix_rfactor_output on a non-orthogonal hexagonal cell:
        # fixture stage HKLs:
        #   extracted_pre_fmodel: (1,0,0)->5*sqrt(3), (0,1,0)->5*sqrt(3),
        #     (1,1,1)->1/sqrt(12/300 + 1/400)=20/sqrt(17),
        #     (2,0,0)->2.5*sqrt(3), (0,2,0)->2.5*sqrt(3)
        #   final_effective: (1,0,0), (0,1,0), (2,0,0), (0,2,0)
        #   actual_work: (1,0,0), (0,1,0) -> d = 5*sqrt(3)
        #   actual_free: (2,0,0), (0,2,0) -> d = 2.5*sqrt(3)
        hex_mtz_bytes = _build_synthetic_mtz(
            [
                (1, 0, 0, 100.0, 2.0, 0.0),
                (0, 1, 0, 200.0, 3.0, 0.0),
                (0, 0, 1, 0.0, 1.5, 0.0),
                (1, 1, 0, -5.0, 1.2, 0.0),
                (1, 1, 1, 150.0, 2.5, 0.0),
                (2, 0, 0, 80.0, 1.8, 1.0),
                (0, 2, 0, 120.0, 2.2, 1.0),
                (0, 0, 2, float("nan"), float("nan"), float("nan")),
            ],
            cell=hex_cell,
        )
        hex_ledger = onesar_rerun.build_input_hkl_ledger(hex_mtz_bytes)
        hex_maps_bytes, hex_pair_bytes = _build_synthetic_map_mtz_pair(
            payload["map_coefficients"]["2mFo-DFc"]["records"],
            payload["map_coefficients"]["mFo-DFc"]["records"],
            cell=hex_cell,
        )
        hex_payload = copy.deepcopy(payload)
        hex_payload["crystal_symmetry"]["unit_cell"] = list(
            onesar_rerun.ccp4_mtz_float32_unit_cell(hex_cell)
        )
        hex_payload["map_coefficients"]["mtz_supplements"][
            "phx_maps_sha256"
        ] = hashlib.sha256(hex_maps_bytes).hexdigest()
        hex_payload["map_coefficients"]["mtz_supplements"][
            "obs_pair_only_sha256"
        ] = hashlib.sha256(hex_pair_bytes).hexdigest()
        hex_d_100 = 5.0 * math.sqrt(3.0)
        hex_d_200 = 2.5 * math.sqrt(3.0)
        hex_d_111 = 20.0 / math.sqrt(17.0)
        hex_payload["resolution_ranges"] = {
            "extracted_pre_fmodel": {"d_max": hex_d_100, "d_min": hex_d_200},
            "final_effective": {"d_max": hex_d_100, "d_min": hex_d_200},
            "actual_work": {"d_max": hex_d_100, "d_min": hex_d_100},
            "actual_free": {"d_max": hex_d_200, "d_min": hex_d_200},
        }
        self.assertAlmostEqual(
            onesar_rerun.compute_hkl_d_spacing([1, 1, 1], hex_cell),
            hex_d_111,
            places=13,
        )
        hex_res = self._reconcile(
            hex_payload,
            hex_ledger,
            vendor_shas,
            hex_maps_bytes,
            hex_pair_bytes,
        )
        self.assertEqual(hex_res["reconciliation_status"], "verified")
        self.assertAlmostEqual(
            hex_res["resolution_ranges"]["actual_work"]["recomputed_d_max"],
            hex_d_100,
            places=12,
        )

        # Orthogonal approximation on the hexagonal cell (10.0 instead of 5*sqrt(3)) must fail!
        hex_orth_approx = copy.deepcopy(hex_payload)
        hex_orth_approx["resolution_ranges"]["actual_work"] = {
            "d_max": 10.0,
            "d_min": 10.0,
        }
        with self.assertRaisesRegex(
            ValueError,
            "resolution_ranges\\['actual_work'\\]\\.d_max .* disagrees with recomputed",
        ):
            self._reconcile(
                hex_orth_approx,
                hex_ledger,
                vendor_shas,
                hex_maps_bytes,
                hex_pair_bytes,
            )

        # 3. General triclinic cell verified against independent 3D Cartesian cross-product basis:
        tri_cell = (10.0, 12.0, 15.0, 80.0, 85.0, 70.0)
        ta, tb, tc, talpha, tbeta, tgamma = tri_cell
        ca_r = math.cos(math.radians(talpha))
        cb_r = math.cos(math.radians(tbeta))
        cg_r = math.cos(math.radians(tgamma))
        sg_r = math.sin(math.radians(tgamma))
        vec_a = (ta, 0.0, 0.0)
        vec_b = (tb * cg_r, tb * sg_r, 0.0)
        cx = tc * cb_r
        cy = tc * (ca_r - cb_r * cg_r) / sg_r
        cz = math.sqrt(tc * tc - cx * cx - cy * cy)
        vec_c = (cx, cy, cz)

        def _cross(
            u: tuple[float, float, float], v: tuple[float, float, float]
        ) -> tuple[float, float, float]:
            return (
                u[1] * v[2] - u[2] * v[1],
                u[2] * v[0] - u[0] * v[2],
                u[0] * v[1] - u[1] * v[0],
            )

        def _dot(
            u: tuple[float, float, float], v: tuple[float, float, float]
        ) -> float:
            return u[0] * v[0] + u[1] * v[1] + u[2] * v[2]

        vol = _dot(vec_a, _cross(vec_b, vec_c))
        b_cross_c = _cross(vec_b, vec_c)
        c_cross_a = _cross(vec_c, vec_a)
        a_cross_b = _cross(vec_a, vec_b)
        astar = (b_cross_c[0] / vol, b_cross_c[1] / vol, b_cross_c[2] / vol)
        bstar = (c_cross_a[0] / vol, c_cross_a[1] / vol, c_cross_a[2] / vol)
        cstar = (a_cross_b[0] / vol, a_cross_b[1] / vol, a_cross_b[2] / vol)

        tri_hkls = [
            [1, 0, 0],
            [0, 1, 0],
            [0, 0, 1],
            [1, 2, -1],
            [-2, 1, 3],
            [3, -2, -4],
        ]
        indep_ds: list[float] = []
        for h, k, l in tri_hkls:
            sx = h * astar[0] + k * bstar[0] + l * cstar[0]
            sy = h * astar[1] + k * bstar[1] + l * cstar[1]
            sz = h * astar[2] + k * bstar[2] + l * cstar[2]
            d_indep = 1.0 / math.sqrt(sx * sx + sy * sy + sz * sz)
            indep_ds.append(d_indep)
            self.assertAlmostEqual(
                onesar_rerun.compute_hkl_d_spacing([h, k, l], tri_cell),
                d_indep,
                places=13,
            )
        tri_stage_range = onesar_rerun.compute_stage_resolution_range(
            tri_hkls, tri_cell
        )
        self.assertAlmostEqual(
            tri_stage_range["d_max"], max(indep_ds), places=13
        )
        self.assertAlmostEqual(
            tri_stage_range["d_min"], min(indep_ds), places=13
        )

        # 4. Missing, malformed, swapped, nonfinite, boolean, cross-stage copied, or fabricated ranges fail:
        missing_rr = copy.deepcopy(payload)
        del missing_rr["resolution_ranges"]
        with self.assertRaisesRegex(
            ValueError, "phenix_payload\\.resolution_ranges must be a mapping"
        ):
            self._reconcile(
                missing_rr, ledger, vendor_shas, maps_bytes, pair_bytes
            )

        missing_stage = copy.deepcopy(payload)
        del missing_stage["resolution_ranges"]["actual_free"]
        with self.assertRaisesRegex(
            ValueError, "phenix_payload\\.resolution_ranges must be a mapping"
        ):
            self._reconcile(
                missing_stage, ledger, vendor_shas, maps_bytes, pair_bytes
            )

        extra_stage = copy.deepcopy(payload)
        extra_stage["resolution_ranges"]["raw_mtz"] = {
            "d_max": 78.323,
            "d_min": 64.897,
        }
        with self.assertRaisesRegex(
            ValueError, "phenix_payload\\.resolution_ranges must be a mapping"
        ):
            self._reconcile(
                extra_stage, ledger, vendor_shas, maps_bytes, pair_bytes
            )

        missing_dmin = copy.deepcopy(payload)
        del missing_dmin["resolution_ranges"]["actual_work"]["d_min"]
        with self.assertRaisesRegex(
            ValueError,
            "resolution_ranges\\['actual_work'\\] must be a mapping with exact keys",
        ):
            self._reconcile(
                missing_dmin, ledger, vendor_shas, maps_bytes, pair_bytes
            )

        swapped_bounds = copy.deepcopy(payload)
        swapped_bounds["resolution_ranges"]["actual_work"] = {
            "d_max": 64.897,
            "d_min": 78.323,
        }
        with self.assertRaisesRegex(
            ValueError, "has inverted bounds: d_max=64.897 < d_min=78.323"
        ):
            self._reconcile(
                swapped_bounds, ledger, vendor_shas, maps_bytes, pair_bytes
            )

        for bad_val, err_pat in (
            (float("nan"), "must be a finite number"),
            (float("inf"), "must be a finite number"),
            (0.0, "must be positive"),
            (-5.0, "must be positive"),
            (True, "must be a finite number"),
        ):
            bad_d = copy.deepcopy(payload)
            bad_d["resolution_ranges"]["actual_work"]["d_min"] = bad_val
            with self.assertRaisesRegex(ValueError, err_pat):
                self._reconcile(
                    bad_d, ledger, vendor_shas, maps_bytes, pair_bytes
                )

        # Copying final_effective onto extracted_pre_fmodel, actual_work, or actual_free fails:
        for stage_target, field_pat in (
            ("extracted_pre_fmodel", "d_min"),
            ("actual_work", "d_min"),
            ("actual_free", "d_max"),
        ):
            copied_stage = copy.deepcopy(payload)
            copied_stage["resolution_ranges"][stage_target] = copy.deepcopy(
                payload["resolution_ranges"]["final_effective"]
            )
            with self.assertRaisesRegex(
                ValueError,
                f"resolution_ranges\\['{stage_target}'\\]\\.{field_pat} .* disagrees with recomputed",
            ):
                self._reconcile(
                    copied_stage, ledger, vendor_shas, maps_bytes, pair_bytes
                )

        # Fabricated 1.8 A range on the low-resolution fixture stage HKL set fails:
        fabricated_18 = copy.deepcopy(payload)
        fabricated_18["resolution_ranges"]["final_effective"]["d_min"] = 1.8
        with self.assertRaisesRegex(
            ValueError,
            "resolution_ranges\\['final_effective'\\]\\.d_min 1\\.800000000000000 disagrees with recomputed",
        ):
            self._reconcile(
                fabricated_18, ledger, vendor_shas, maps_bytes, pair_bytes
            )

        # Numeric scalar/measurement checks remain strict (do not accept decimal strings):
        str_d = copy.deepcopy(payload)
        str_d["resolution_ranges"]["actual_work"]["d_min"] = "64.897"
        with self.assertRaisesRegex(ValueError, "must be a finite number"):
            self._reconcile(
                str_d, ledger, vendor_shas, maps_bytes, pair_bytes
            )
        str_rw = copy.deepcopy(payload)
        str_rw["scales_and_rfactors"]["r_work"] = "0.06666666666666667"
        with self.assertRaisesRegex(ValueError, "must be a finite number"):
            self._reconcile(
                str_rw, ledger, vendor_shas, maps_bytes, pair_bytes
            )

        # 5. Origin (0, 0, 0) HKL and invalid/singular/malformed-token unit cells raise ValueError:
        with self.assertRaisesRegex(
            ValueError, "Miller index \\(0, 0, 0\\) has undefined d-spacing"
        ):
            onesar_rerun.compute_hkl_d_spacing([0, 0, 0], orth_cell)
        with self.assertRaisesRegex(
            ValueError, "Miller index \\(0, 0, 0\\) has undefined d-spacing"
        ):
            onesar_rerun.compute_stage_resolution_range([[0, 0, 0]], orth_cell)

        for bad_cell, cell_err in (
            ([10.0, 20.0, 30.0], "must be a 6-element sequence"),
            ((0.0, 20.0, 30.0, 90.0, 90.0, 90.0), "must be positive"),
            ((-10.0, 20.0, 30.0, 90.0, 90.0, 90.0), "must be positive"),
            ((True, 20.0, 30.0, 90.0, 90.0, 90.0), "must be a finite number"),
            ((10.0, 20.0, 30.0, 0.0, 90.0, 90.0), "must be positive"),
            (
                (10.0, 20.0, 30.0, 180.0, 90.0, 90.0),
                "must be in \\(0, 180\\) degrees",
            ),
            (
                (10.0, 20.0, 30.0, 90.0, 120.0, 150.0),
                "violate crystallographic cone inequalities",
            ),
            (
                (10.0, 20.0, 30.0, 40.0, 50.0, 100.0),
                "violate crystallographic cone inequalities",
            ),
            (
                ("", "78.323", "38.792", "9E+1", "9E+1", "9E+1"),
                "must be a valid decimal unit-cell token",
            ),
            (
                (" 64.897", "78.323", "38.792", "9E+1", "9E+1", "9E+1"),
                "must be a valid decimal unit-cell token",
            ),
            (
                ("64.897 ", "78.323", "38.792", "9E+1", "9E+1", "9E+1"),
                "must be a valid decimal unit-cell token",
            ),
            (
                ("64_897", "78.323", "38.792", "9E+1", "9E+1", "9E+1"),
                "must be a valid decimal unit-cell token",
            ),
            (
                ("64.897a", "78.323", "38.792", "9E+1", "9E+1", "9E+1"),
                "must be a valid decimal unit-cell token",
            ),
            (
                ("NaN", "78.323", "38.792", "9E+1", "9E+1", "9E+1"),
                "must be a finite number",
            ),
            (
                ("inf", "78.323", "38.792", "9E+1", "9E+1", "9E+1"),
                "must be a finite number",
            ),
            (
                ("-Infinity", "78.323", "38.792", "9E+1", "9E+1", "9E+1"),
                "must be a finite number",
            ),
            (
                ("1e1000", "78.323", "38.792", "9E+1", "9E+1", "9E+1"),
                "must be a finite number",
            ),
            (
                ("0", "78.323", "38.792", "9E+1", "9E+1", "9E+1"),
                "must be positive",
            ),
            (
                ("-64.897", "78.323", "38.792", "9E+1", "9E+1", "9E+1"),
                "must be positive",
            ),
            (
                ("64.897", "78.323", "38.792", "1.8E+2", "9E+1", "9E+1"),
                "must be in \\(0, 180\\) degrees",
            ),
        ):
            with self.assertRaisesRegex(ValueError, cell_err):
                onesar_rerun.validate_unit_cell_parameters(bad_cell)
            bad_ledger = copy.deepcopy(ledger)
            bad_ledger["crystallographic_context"][
                "cell_a_b_c_alpha_beta_gamma"
            ] = list(bad_cell)
            with self.assertRaisesRegex(ValueError, cell_err):
                self._reconcile(
                    payload, bad_ledger, vendor_shas, maps_bytes, pair_bytes
                )

    def test_map_coefficients_and_mtz_supplements_reconciliation_1016(self) -> None:
        ledger, payload, vendor_shas, maps_bytes, pair_bytes = (
            _make_reconciliation_fixture()
        )

        # Mutated JSON map amplitude or phase fails.
        bad_json_amp = copy.deepcopy(payload)
        bad_json_amp["map_coefficients"]["2mFo-DFc"]["records"][0][
            "amplitude"
        ] = 11.0
        with self.assertRaisesRegex(
            ValueError, "amplitude 11.0 != hypot\\(real, imag\\)"
        ):
            self._reconcile(
                bad_json_amp, ledger, vendor_shas, maps_bytes, pair_bytes
            )

        bad_json_phase = copy.deepcopy(payload)
        bad_json_phase["map_coefficients"]["2mFo-DFc"]["records"][2][
            "phase_deg"
        ] = 45.0
        with self.assertRaisesRegex(
            ValueError, "phase_deg 45.0 disagrees with atan2"
        ):
            self._reconcile(
                bad_json_phase, ledger, vendor_shas, maps_bytes, pair_bytes
            )

        # Mutated centric_count fails.
        bad_centric = copy.deepcopy(payload)
        bad_centric["map_coefficients"]["2mFo-DFc"]["centric_count"] = 3
        bad_centric["map_coefficients"]["2mFo-DFc"]["acentric_count"] = 1
        with self.assertRaisesRegex(
            ValueError, "centric/acentric counts .* !="
        ):
            self._reconcile(
                bad_centric, ledger, vendor_shas, maps_bytes, pair_bytes
            )

        # Wrong MTZ SHA-256 fails.
        bad_sha = copy.deepcopy(payload)
        bad_sha["map_coefficients"]["mtz_supplements"]["phx_maps_sha256"] = (
            "0" * 64
        )
        with self.assertRaisesRegex(
            ValueError, "phx_maps.mtz SHA-256 .* disagrees"
        ):
            self._reconcile(
                bad_sha, ledger, vendor_shas, maps_bytes, pair_bytes
            )

        # Wrong column type in phx_maps.mtz (e.g. Q instead of P) fails.
        bad_type_maps = _build_synthetic_mtz(
            [(1, 0, 0, 10.0, 0.0, 2.0, 0.0)],
            columns=[
                ("H", "H", "1"),
                ("K", "H", "1"),
                ("L", "H", "1"),
                ("2FOFCWT", "F", "1"),
                ("PH2FOFCWT", "Q", "1"),
                ("FOFCWT", "F", "1"),
                ("PHFOFCWT", "P", "1"),
            ],
        )
        bad_type_payload = copy.deepcopy(payload)
        bad_type_payload["map_coefficients"]["mtz_supplements"][
            "phx_maps_sha256"
        ] = hashlib.sha256(bad_type_maps).hexdigest()
        with self.assertRaisesRegex(
            ValueError, "Map MTZ column types .* do not match expected"
        ):
            self._reconcile(
                bad_type_payload,
                ledger,
                vendor_shas,
                bad_type_maps,
                pair_bytes,
            )

        # Mutated float32 amplitude in phx_maps.mtz fails.
        mut_recs_2fofc = copy.deepcopy(
            payload["map_coefficients"]["2mFo-DFc"]["records"]
        )
        mut_recs_2fofc[0]["amplitude"] = 99.0
        bad_amp_maps, _ = _build_synthetic_map_mtz_pair(
            mut_recs_2fofc, payload["map_coefficients"]["mFo-DFc"]["records"]
        )
        bad_amp_payload = copy.deepcopy(payload)
        bad_amp_payload["map_coefficients"]["mtz_supplements"][
            "phx_maps_sha256"
        ] = hashlib.sha256(bad_amp_maps).hexdigest()
        # Keep PHX_OBS_PAIR_ONLY matching bad_amp_maps so it reaches the JSON amplitude comparison:
        _, bad_amp_pair = _build_synthetic_map_mtz_pair(
            mut_recs_2fofc, payload["map_coefficients"]["mFo-DFc"]["records"]
        )
        bad_amp_payload["map_coefficients"]["mtz_supplements"][
            "obs_pair_only_sha256"
        ] = hashlib.sha256(bad_amp_pair).hexdigest()
        with self.assertRaisesRegex(
            ValueError, "phx_maps.mtz 2FOFCWT 99.0 disagrees with JSON amplitude 10.0"
        ):
            self._reconcile(
                bad_amp_payload,
                ledger,
                vendor_shas,
                bad_amp_maps,
                bad_amp_pair,
            )

        # Mismatched 2FOFCWT word in PHX_OBS_PAIR_ONLY.mtz vs phx_maps.mtz fails.
        mismatch_pair_payload = copy.deepcopy(payload)
        mismatch_pair_payload["map_coefficients"]["mtz_supplements"][
            "obs_pair_only_sha256"
        ] = hashlib.sha256(bad_amp_pair).hexdigest()
        with self.assertRaisesRegex(
            ValueError,
            "PHX_OBS_PAIR_ONLY.mtz 2FOFCWT/PH2FOFCWT words differ from phx_maps.mtz",
        ):
            self._reconcile(
                mismatch_pair_payload,
                ledger,
                vendor_shas,
                maps_bytes,
                bad_amp_pair,
            )

    def test_helper_pure_functions_and_python39_static_contract(self) -> None:
        # Pure scatterer snapshot comparison catches mutations.
        base_rec = [
            {
                "label": "N",
                "scattering_type": "N",
                "site_frac": [0.1, 0.2, 0.3],
                "site_cart": [6.4, 15.6, 11.6],
                "occupancy": 1.0,
                "u_iso": 0.25,
                "u_star": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                "use_u_iso": True,
                "use_u_aniso": False,
            }
        ]
        snap_before = onesar_phenix_measure.snapshot_scatterer_records(base_rec)
        snap_same = onesar_phenix_measure.snapshot_scatterer_records(base_rec)
        inv = onesar_phenix_measure.compare_scatterer_snapshots(
            snap_before, snap_same, snap_same
        )
        self.assertEqual(inv["max_abs_site_cart_diff"], 0.0)

        mut_rec = copy.deepcopy(base_rec)
        mut_rec[0]["site_cart"][0] += 0.001
        snap_mut = onesar_phenix_measure.snapshot_scatterer_records(mut_rec)
        with self.assertRaisesRegex(ValueError, "Scatterer snapshot mutated"):
            onesar_phenix_measure.compare_scatterer_snapshots(
                snap_before, snap_mut, snap_same
            )

        # build_raw_scatterer_snapshot retains empty and non-finite records without
        # validating finiteness or computing a canonical digest (#1014, Task 128):
        raw_empty_snap = onesar_phenix_measure.build_raw_scatterer_snapshot([])
        self.assertEqual(
            raw_empty_snap,
            {"n_scatterers": 0, "sha256": None, "records": []},
        )
        with self.subTest(
            case="strict_snapshot_rejects_empty_scatterer_records"
        ):
            with self.assertRaisesRegex(
                ValueError, "Scatterer snapshot cannot be empty"
            ):
                onesar_phenix_measure.snapshot_scatterer_records([])

        nf_occ_bits = struct.unpack(
            ">d", struct.pack(">Q", 0x7FF8000000000123)
        )[0]
        nf_rec = copy.deepcopy(base_rec)
        nf_rec[0]["occupancy"] = nf_occ_bits
        raw_nf_snap = onesar_phenix_measure.build_raw_scatterer_snapshot(nf_rec)
        self.assertEqual(raw_nf_snap["n_scatterers"], 1)
        self.assertIsNone(raw_nf_snap["sha256"])
        encoded_raw_nf_snap = (
            onesar_phenix_measure.encode_raw_evidence_nonfinite(
                raw_nf_snap,
                field_path="xray_structure_snapshots_raw.after_model",
            )
        )
        self.assertEqual(
            encoded_raw_nf_snap["records"][0]["occupancy"][
                "ieee754_binary64_hex"
            ],
            "0x7ff8000000000123",
        )
        with self.subTest(
            case="strict_snapshot_rejects_nonfinite_scatterer_record"
        ):
            with self.assertRaisesRegex(
                ValueError, "Invalid scatterer record at index 0"
            ):
                onesar_phenix_measure.snapshot_scatterer_records(nf_rec)

        # Symmetry operator normalization policy (#1025, Task 128):
        self.assertEqual(
            onesar_rerun.normalize_symmetry_operator_xyz(
                " -x + 1/2,  -y,  z + 1/2 "
            ),
            "-X+1/2,-Y,Z+1/2",
        )
        for bad_op_case, bad_op_str, bad_op_pat in (
            (
                "symm_prefixed",
                "SYMM   -x + 1/2,  -y,  z + 1/2 ",
                "unsupported or malformed",
            ),
            (
                "translation_first",
                "1/2-X, -Y, 1/2+Z",
                "unsupported or malformed",
            ),
            (
                "leading_plus_translation_first",
                "+1/2+X, +1/2-Y, -Z",
                "unsupported or malformed",
            ),
            (
                "wrong_component_count",
                "X,Y",
                "must have 3 comma-separated XYZ components",
            ),
            (
                "decimal_translation",
                "X+0.5,Y,Z",
                "unsupported or malformed",
            ),
        ):
            with self.subTest(case=f"normalize_symmetry_rejects_{bad_op_case}"):
                with self.assertRaisesRegex(ValueError, bad_op_pat):
                    onesar_rerun.normalize_symmetry_operator_xyz(bad_op_str)

        # Strict-JSON IEEE-754 nonfinite tagger preserves finite values and tags NaN/+Inf/-Inf:
        nf_locs: list[dict[str, Any]] = []
        encoded_nf = onesar_phenix_measure.encode_raw_evidence_nonfinite(
            {
                "finite": 12.5,
                "flag": True,
                "count": 3,
                "items": [float("nan"), float("inf"), float("-inf")],
            },
            nonfinite_locations=nf_locs,
        )
        self.assertEqual(encoded_nf["finite"], 12.5)
        self.assertIs(encoded_nf["flag"], True)
        self.assertEqual(encoded_nf["count"], 3)
        self.assertEqual(len(nf_locs), 3)
        self.assertEqual(
            [item["kind"] for item in nf_locs], ["nan", "+inf", "-inf"]
        )
        self.assertEqual(
            [item["field_path"] for item in nf_locs],
            ["items[0]", "items[1]", "items[2]"],
        )
        self.assertEqual(
            nf_locs[1]["ieee754_binary64_hex"], "0x7ff0000000000000"
        )
        self.assertEqual(
            nf_locs[2]["ieee754_binary64_hex"], "0xfff0000000000000"
        )
        # Re-encoding an already tagged structure is idempotent:
        nf_locs_second: list[dict[str, Any]] = []
        encoded_nf_second = (
            onesar_phenix_measure.encode_raw_evidence_nonfinite(
                encoded_nf, nonfinite_locations=nf_locs_second
            )
        )
        self.assertEqual(encoded_nf_second, encoded_nf)
        self.assertEqual(nf_locs_second, nf_locs)

        # Static AST verification of scripts/onesar_phenix_measure.py:
        # - No top-level vendor imports
        # - No Python 3.10+/3.11+ zip(strict=...) or hashlib.file_digest
        # - No call to second-block get_r_rfree_sigma
        helper_path = _SCRIPTS_DIR / "onesar_phenix_measure.py"
        tree = ast.parse(helper_path.read_text(encoding="utf-8"))
        forbidden_top_imports = {"cctbx", "iotbx", "mmtbx", "scitbx", "libtbx"}
        for node in tree.body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_mod = alias.name.split(".")[0]
                    self.assertNotIn(root_mod, forbidden_top_imports)
            elif isinstance(node, ast.ImportFrom) and node.module:
                root_mod = node.module.split(".")[0]
                self.assertNotIn(root_mod, forbidden_top_imports)

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Attribute):
                    self.assertNotEqual(node.func.attr, "file_digest")
                    self.assertNotEqual(node.func.attr, "get_r_rfree_sigma")
                    if (
                        isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "reflection_file"
                    ):
                        self.assertNotEqual(node.func.attr, "crystal_symmetry")
                    if (
                        isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "extract_xtal_data"
                        and node.func.attr == "run"
                    ):
                        kw_names = {kw.arg for kw in node.keywords}
                        self.assertNotIn("log", kw_names)
                    if (
                        isinstance(node.func.value, ast.Attribute)
                        and node.func.value.attr == "f_model"
                        and node.func.attr == "manager"
                    ):
                        kw_names = {kw.arg for kw in node.keywords}
                        self.assertNotIn("log", kw_names)
                    if node.func.attr == "map_coefficients":
                        kw_names = {kw.arg for kw in node.keywords}
                        self.assertIn("sharp", kw_names)
                        self.assertNotIn("resharp_after_isotropize", kw_names)
                elif isinstance(node.func, ast.Name) and node.func.id == "zip":
                    kw_names = {kw.arg for kw in node.keywords}
                    self.assertNotIn("strict", kw_names)

    def test_operation_rejects_protstruct_env_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_repo = Path(tmp).resolve(strict=True)
            saved_protstruct = {
                k: v
                for k, v in os.environ.items()
                if k.startswith("PROTSTRUCT_")
            }
            try:
                for k in saved_protstruct:
                    os.environ.pop(k, None)
                for env_override, expected_var in (
                    (
                        {"PROTSTRUCT_PHENIX_BIN": "/custom/phenix_bin"},
                        "PROTSTRUCT_PHENIX_BIN",
                    ),
                    (
                        {"PROTSTRUCT_UNRELATED_CUSTOM": "1"},
                        "PROTSTRUCT_UNRELATED_CUSTOM",
                    ),
                    (
                        {"PROTSTRUCT_PHENIX_BIN": ""},
                        "PROTSTRUCT_PHENIX_BIN",
                    ),
                ):
                    with mock.patch.dict(os.environ, env_override, clear=False):
                        with self.assertRaisesRegex(
                            ValueError,
                            rf"no PROTSTRUCT_\* environment overrides.*{expected_var}",
                        ):
                            onesar_rerun.run_phenix_rfactor_operation(
                                fake_repo / "out",
                                subject_id="R4",
                                repo_root=fake_repo,
                            )
                        self.assertFalse((fake_repo / "out").exists())
            finally:
                for k in list(os.environ.keys()):
                    if k.startswith("PROTSTRUCT_"):
                        os.environ.pop(k, None)
                os.environ.update(saved_protstruct)

    def test_stage_subject_inputs_and_unmeasured_build_rejection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_repo = Path(tmp).resolve(strict=True)
            staged = onesar_rerun.stage_subject_inputs(
                fake_repo / "runs" / "r4_stage",
                subject_id="R4",
                repo_root=fake_repo,
                archive_path=COMMITTED_ARCHIVE,
            )
            self.assertTrue(staged["original_pdb_path"].is_file())
            self.assertTrue(staged["original_mtz_path"].is_file())
            self.assertTrue(staged["projected_mtz_path"].is_file())
            self.assertTrue(staged["input_ledger_path"].is_file())
            self.assertTrue(staged["admission_json_path"].is_file())
            self.assertEqual(
                staged["admission_record"]["subject"]["sha256"],
                onesar_rerun.ALLOWED_SUBJECTS["R4"]["sha256"],
            )
            self.assertEqual(
                staged["input_ledger"]["counts"]["eligible_total"], 7228
            )
            persisted_ledger = json.loads(
                staged["input_ledger_path"].read_text(encoding="utf-8")
            )
            self.assertEqual(
                persisted_ledger["counts"], staged["input_ledger"]["counts"]
            )
            self.assertEqual(
                len(persisted_ledger["eligible_by_hkl"]), 7228
            )
            self.assertEqual(len(persisted_ledger["ineligible_rows"]), 20)
            self.assertEqual(len(persisted_ledger["raw_rows"]), 7248)

            # Rejects unmeasured PHENIX build dictionary before invoking subprocess (#1014).
            unmeasured_build = {
                "reported_version_source": "command_output",
                "reported_version": "2.0-5936",
                "parsed_build": "2.0-5936",
                "version_probe": {"probe_mode": "command_output"},
            }
            unmeasured_runner_calls: list[list[str]] = []

            def _unexpected_runner(
                argv: list[str], log: Path, *, cwd: Path, timeout: float
            ) -> subprocess.CompletedProcess[str]:
                unmeasured_runner_calls.append(list(argv))
                raise AssertionError("Scientific worker must not be launched")

            unmeasured_run_dir = fake_repo / "runs" / "r4_unmeasured"
            with mock.patch.object(
                toolchain, "phenix_build_evidence", return_value=unmeasured_build
            ):
                with self.assertRaisesRegex(
                    ValueError, "failed #957 admission gate"
                ):
                    onesar_rerun.run_phenix_rfactor_operation(
                        unmeasured_run_dir,
                        subject_id="R4",
                        repo_root=fake_repo,
                        archive_path=COMMITTED_ARCHIVE,
                        require_no_protstruct_overrides=False,
                        runner=_unexpected_runner,
                    )
            self.assertEqual(unmeasured_runner_calls, [])
            self.assertFalse((unmeasured_run_dir / "phenix" / "cache").exists())
            preflight_unmeasured_path = (
                unmeasured_run_dir
                / "phenix"
                / "phenix_preflight_build_evidence.json"
            )
            failure_unmeasured_path = (
                unmeasured_run_dir
                / "phenix"
                / "phenix_build_admission_failure.json"
            )
            self.assertTrue(preflight_unmeasured_path.is_file())
            self.assertTrue(failure_unmeasured_path.is_file())
            self.assertEqual(
                json.loads(preflight_unmeasured_path.read_text(encoding="utf-8")),
                unmeasured_build,
            )
            failure_unmeasured_doc = json.loads(
                failure_unmeasured_path.read_text(encoding="utf-8")
            )
            self.assertEqual(failure_unmeasured_doc["status"], "rejected")
            self.assertFalse(failure_unmeasured_doc["worker_launched"])
            self.assertEqual(
                failure_unmeasured_doc["measured_build"], unmeasured_build
            )
            self.assertEqual(
                failure_unmeasured_doc["failure"]["failed_stage"],
                "validate_measured_phenix_build",
            )
            self.assertEqual(
                failure_unmeasured_doc["preflight_build_evidence_sha256"],
                hashlib.sha256(preflight_unmeasured_path.read_bytes()).hexdigest(),
            )

            # Rejects failed version_probe and retains full raw probe evidence on disk (#1014).
            failed_probe_build = {
                "reported_version_source": "unknown",
                "reported_version": "unknown",
                "parsed_build": None,
                "version_probe": {
                    "error": "phenix_env.sh exited with returncode 1",
                    "probe_mode": "vendor_setup_environment",
                    "setup_returncode": 1,
                    "setup_stdout": "",
                    "setup_stderr": "phenix_env.sh: missing dispatcher",
                },
            }
            failed_probe_run_dir = fake_repo / "runs" / "r4_failed_probe"
            with mock.patch.object(
                toolchain,
                "phenix_build_evidence",
                return_value=failed_probe_build,
            ):
                with self.assertRaisesRegex(
                    ValueError, "failed #957 admission gate"
                ):
                    onesar_rerun.run_phenix_rfactor_operation(
                        failed_probe_run_dir,
                        subject_id="R4",
                        repo_root=fake_repo,
                        archive_path=COMMITTED_ARCHIVE,
                        require_no_protstruct_overrides=False,
                        runner=_unexpected_runner,
                    )
            self.assertEqual(unmeasured_runner_calls, [])
            self.assertFalse(
                (failed_probe_run_dir / "phenix" / "cache").exists()
            )
            preflight_failed_path = (
                failed_probe_run_dir
                / "phenix"
                / "phenix_preflight_build_evidence.json"
            )
            admission_failed_path = (
                failed_probe_run_dir
                / "phenix"
                / "phenix_build_admission_failure.json"
            )
            self.assertTrue(preflight_failed_path.is_file())
            self.assertTrue(admission_failed_path.is_file())
            self.assertEqual(
                json.loads(preflight_failed_path.read_text(encoding="utf-8")),
                failed_probe_build,
            )
            admission_failed_doc = json.loads(
                admission_failed_path.read_text(encoding="utf-8")
            )
            self.assertEqual(admission_failed_doc["status"], "rejected")
            self.assertFalse(admission_failed_doc["worker_launched"])
            self.assertEqual(
                admission_failed_doc["measured_build"], failed_probe_build
            )
            self.assertEqual(
                admission_failed_doc["failure"]["failed_stage"],
                "validate_measured_phenix_build",
            )

    def test_orchestration_with_real_cache_success_and_failure_retention(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp).resolve(strict=True)
            fake_repo = tmp_root / "repo"
            fake_repo.mkdir()

            # Build a synthetic PHENIX installation tree for file_identity and vendor source hashing.
            fake_prefix = tmp_root / "phenix-2.0-5936"
            fake_bin = fake_prefix / "phenix_bin"
            fake_site = fake_prefix / "lib" / "python3.9" / "site-packages"
            fake_bin.mkdir(parents=True)
            (fake_prefix / "phenix_env.sh").write_text(
                "#!/bin/sh\nexport PHENIX_VERSION=2.0\nexport PHENIX_RELEASE_TAG=5936\n",
                encoding="utf-8",
            )
            (fake_bin / "phenix.version").write_text(
                "#!/bin/sh\n", encoding="utf-8"
            )
            (fake_bin / "phenix.python").write_text(
                "#!/bin/sh\n", encoding="utf-8"
            )

            vendor_modules_payload = {}
            for key, rel in onesar_rerun.PHENIX_VENDOR_SOURCE_RELPATHS.items():
                mod_file = fake_site / rel
                mod_file.parent.mkdir(parents=True, exist_ok=True)
                content = f"# synthetic {key}\n".encode("utf-8")
                mod_file.write_bytes(content)
                resolved_mod = mod_file.resolve(strict=True)
                vendor_modules_payload[key] = {
                    "module_name": key,
                    "configured_path": str(resolved_mod),
                    "resolved_path": str(resolved_mod),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }

            banner = "PHENIX: 2.0-5936\n  Version: 2.0\n  Release tag: 5936"
            setup_resolved = (fake_prefix / "phenix_env.sh").resolve(strict=True)
            disp_resolved = (fake_bin / "phenix.version").resolve(strict=True)
            resolved_prefix_str = str(fake_prefix.resolve(strict=True))
            fake_measured_build = {
                "reported_version_source": "vendor_setup_environment",
                "reported_version": banner,
                "parsed_build": "2.0-5936",
                "version_probe": {
                    "error": None,
                    "probe_mode": "vendor_setup_environment",
                    "configured_prefix": str(fake_prefix),
                    "resolved_prefix": resolved_prefix_str,
                    "setup_configured_path": str(fake_prefix / "phenix_env.sh"),
                    "setup_resolved_path": str(setup_resolved),
                    "setup_sha256": hashlib.sha256(
                        setup_resolved.read_bytes()
                    ).hexdigest(),
                    "setup_argv": toolchain.phenix_setup_argv(setup_resolved),
                    "setup_returncode": 0,
                    "setup_stdout": "",
                    "setup_stderr": "",
                    "setup_version_fields": {
                        "PHENIX_VERSION": "2.0",
                        "PHENIX_RELEASE_TAG": "5936",
                    },
                    "setup_parsed_build": "2.0-5936",
                    "configured_path": str(fake_bin / "phenix.version"),
                    "resolved_path": str(disp_resolved),
                    "sha256": hashlib.sha256(
                        disp_resolved.read_bytes()
                    ).hexdigest(),
                    "argv": [str(disp_resolved)],
                    "returncode": 0,
                    "stdout": banner + "\n",
                    "stderr": "",
                    "parsed_build": "2.0-5936",
                    "ignored_inherited_version_variables": [],
                    "ignored_inherited_shell_hooks": [],
                },
            }
            self.assertTrue(
                refinement_cache._build_is_measured(fake_measured_build)
            )

            # Internally consistent wrong version (2.0-5935) must be rejected (#1013, #1014)
            # and retain preflight build evidence + admission failure without launching worker.
            wrong_ver_banner = "PHENIX: 2.0-5935\n  Version: 2.0\n  Release tag: 5935"
            wrong_ver_build = copy.deepcopy(fake_measured_build)
            wrong_ver_build["reported_version"] = wrong_ver_banner
            wrong_ver_build["parsed_build"] = "2.0-5935"
            wrong_ver_build["version_probe"]["setup_version_fields"] = {
                "PHENIX_VERSION": "2.0",
                "PHENIX_RELEASE_TAG": "5935",
            }
            wrong_ver_build["version_probe"]["setup_parsed_build"] = "2.0-5935"
            wrong_ver_build["version_probe"]["stdout"] = wrong_ver_banner + "\n"
            wrong_ver_build["version_probe"]["parsed_build"] = "2.0-5935"
            self.assertTrue(refinement_cache._build_is_measured(wrong_ver_build))
            wrong_ver_runner_calls: list[list[str]] = []

            def _wrong_ver_spy_runner(
                argv: list[str], log: Path, *, cwd: Path, timeout: float
            ) -> subprocess.CompletedProcess[str]:
                wrong_ver_runner_calls.append(list(argv))
                raise AssertionError("Scientific worker must not be launched")

            wrong_ver_run_dir = fake_repo / "runs" / "r4_wrong_ver"
            with mock.patch.object(
                toolchain, "phenix_build_evidence", return_value=wrong_ver_build
            ):
                with self.assertRaisesRegex(
                    ValueError, "PHENIX build version mismatch: expected '2.0-5936'"
                ):
                    onesar_rerun.run_phenix_rfactor_operation(
                        wrong_ver_run_dir,
                        subject_id="R4",
                        repo_root=fake_repo,
                        archive_path=COMMITTED_ARCHIVE,
                        require_no_protstruct_overrides=False,
                        runner=_wrong_ver_spy_runner,
                    )
            self.assertEqual(wrong_ver_runner_calls, [])
            self.assertFalse((wrong_ver_run_dir / "phenix" / "cache").exists())
            wrong_ver_preflight_path = (
                wrong_ver_run_dir
                / "phenix"
                / "phenix_preflight_build_evidence.json"
            )
            wrong_ver_failure_path = (
                wrong_ver_run_dir
                / "phenix"
                / "phenix_build_admission_failure.json"
            )
            self.assertTrue(wrong_ver_preflight_path.is_file())
            self.assertTrue(wrong_ver_failure_path.is_file())
            self.assertEqual(
                json.loads(wrong_ver_preflight_path.read_text(encoding="utf-8")),
                wrong_ver_build,
            )
            wrong_ver_failure_doc = json.loads(
                wrong_ver_failure_path.read_text(encoding="utf-8")
            )
            self.assertEqual(wrong_ver_failure_doc["status"], "rejected")
            self.assertFalse(wrong_ver_failure_doc["worker_launched"])
            self.assertEqual(
                wrong_ver_failure_doc["measured_build"], wrong_ver_build
            )
            self.assertEqual(
                wrong_ver_failure_doc["failure"]["failed_stage"],
                "validate_measured_phenix_build",
            )

            def fake_success_runner(
                argv: list[str], log: Path, *, cwd: Path, timeout: float
            ) -> subprocess.CompletedProcess[str]:
                self.assertEqual(
                    Path(argv[0]),
                    (fake_bin / "phenix.python").resolve(strict=True),
                )
                mtz_arg = Path(argv[argv.index("--mtz") + 1])
                out_json = Path(argv[argv.index("--out-json") + 1])
                out_maps = Path(argv[argv.index("--out-maps-mtz") + 1])
                out_obs_pair = Path(argv[argv.index("--out-obs-pair-mtz") + 1])
                out_diag = Path(
                    argv[argv.index("--out-diagnostics-json") + 1]
                )
                # Outputs must be placed inside the cache attempt directory (cwd).
                self.assertEqual(out_json.parent, cwd)
                self.assertEqual(out_maps.parent, cwd)
                self.assertEqual(out_obs_pair.parent, cwd)
                self.assertEqual(out_diag.parent, cwd)

                ledger = onesar_rerun.build_input_hkl_ledger(
                    mtz_arg.read_bytes()
                )
                work_candidates = [
                    v
                    for v in ledger["eligible_by_hkl"].values()
                    if not v["is_free"] and v["f_obs"] > 0.0
                ][:2]
                free_candidates = [
                    v
                    for v in ledger["eligible_by_hkl"].values()
                    if v["is_free"] and v["f_obs"] > 0.0
                ][:2]
                w0, w1 = work_candidates
                f0, f1 = free_candidates

                scale_k1_w = 0.5
                scale_k1_t = 0.5
                scale_k1 = 0.5
                _, base_payload, _, _, _ = _make_reconciliation_fixture()
                synth = copy.deepcopy(base_payload)
                synth["expected_resolved_prefix"] = resolved_prefix_str
                synth["expected_phenix_version"] = toolchain.PHENIX_VERSION
                synth["runtime_environment"]["sys_prefix"] = str(fake_prefix)
                synth["runtime_environment"]["resolved_sys_prefix"] = (
                    resolved_prefix_str
                )
                synth["runtime_environment"]["sys_executable"] = str(
                    (fake_bin / "phenix.python").resolve(strict=True)
                )
                synth["runtime_environment"]["resolved_sys_executable"] = str(
                    (fake_bin / "phenix.python").resolve(strict=True)
                )
                synth["runtime_environment"]["vendor_modules"] = (
                    vendor_modules_payload
                )
                selected = [w0, w1, f0, f1]
                synth["extracted_pre_fmodel"] = [
                    {
                        "hkl": list(item["hkl"]),
                        "f_obs": float(item["f_obs"]),
                        "sigf_obs": float(item["sigf_obs"]),
                        "is_free": bool(item["is_free"]),
                    }
                    for item in selected
                ]
                synth["final_effective"] = copy.deepcopy(
                    synth["extracted_pre_fmodel"]
                )
                synth["actual_work"] = [
                    {
                        "hkl": list(item["hkl"]),
                        "f_obs": float(item["f_obs"]),
                        "sigf_obs": float(item["sigf_obs"]),
                        "f_model_real": float(item["f_obs"]) / scale_k1_w,
                        "f_model_imag": 0.0,
                        "f_model_amplitude": float(item["f_obs"]) / scale_k1_w,
                        "f_model_scaled_with_k1_w_real": float(item["f_obs"]),
                        "f_model_scaled_with_k1_w_imag": 0.0,
                        "f_model_scaled_with_k1_w_amplitude": float(
                            item["f_obs"]
                        ),
                    }
                    for item in (w0, w1)
                ]
                synth["actual_free"] = [
                    {
                        "hkl": list(item["hkl"]),
                        "f_obs": float(item["f_obs"]),
                        "sigf_obs": float(item["sigf_obs"]),
                        "f_model_real": float(item["f_obs"]) / scale_k1_t,
                        "f_model_imag": 0.0,
                        "f_model_amplitude": float(item["f_obs"]) / scale_k1_t,
                        "f_model_scaled_with_k1_t_real": float(item["f_obs"]),
                        "f_model_scaled_with_k1_t_imag": 0.0,
                        "f_model_scaled_with_k1_t_amplitude": float(
                            item["f_obs"]
                        ),
                    }
                    for item in (f0, f1)
                ]
                w_den = float(w0["f_obs"] + w1["f_obs"])
                f_den = float(f0["f_obs"] + f1["f_obs"])
                synth["scales_and_rfactors"].update(
                    {
                        "r_work": 0.0,
                        "r_free": 0.0,
                        "r_all": 0.0,
                        "r_free_r_work_gap": 0.0,
                        "scale_k1_w": scale_k1_w,
                        "scale_k1_t": scale_k1_t,
                        "scale_k1": scale_k1,
                        "work_numerator": 0.0,
                        "work_denominator": w_den,
                        "free_numerator": 0.0,
                        "free_denominator": f_den,
                        "all_numerator": 0.0,
                        "all_denominator": w_den + f_den,
                        "work_count": 2,
                        "free_count": 2,
                        "final_effective_count": 4,
                        "extracted_pre_fmodel_count": 4,
                    }
                )
                map_recs = [
                    {
                        "hkl": list(item["hkl"]),
                        "real": 1.0,
                        "imag": 0.0,
                        "amplitude": 1.0,
                        "phase_deg": 0.0,
                        "is_centric": True,
                    }
                    for item in selected
                ]
                synth["map_coefficients"]["2mFo-DFc"]["records"] = copy.deepcopy(
                    map_recs
                )
                synth["map_coefficients"]["2mFo-DFc"]["centric_count"] = 4
                synth["map_coefficients"]["2mFo-DFc"]["acentric_count"] = 0
                synth["map_coefficients"]["mFo-DFc"]["records"] = copy.deepcopy(
                    map_recs
                )
                synth["map_coefficients"]["mFo-DFc"]["centric_count"] = 4
                synth["map_coefficients"]["mFo-DFc"]["acentric_count"] = 0

                cell_floats = tuple(
                    float(x)
                    for x in ledger["crystallographic_context"][
                        "cell_a_b_c_alpha_beta_gamma"
                    ]
                )
                runtime_cell_floats = onesar_rerun.ccp4_mtz_float32_unit_cell(
                    ledger["crystallographic_context"][
                        "cell_a_b_c_alpha_beta_gamma"
                    ]
                )
                synth["crystal_symmetry"] = {
                    "unit_cell": list(runtime_cell_floats),
                    "space_group_symbol": "P 21 21 21 (No. 19)",
                    "space_group_number": 19,
                    "space_group_operators_xyz": [
                        "x,y,z",
                        "-x+1/2,-y,z+1/2",
                        "-x,y+1/2,-z+1/2",
                        "x+1/2,-y+1/2,-z",
                    ],
                }
                ca, cb, cc = (
                    runtime_cell_floats[0],
                    runtime_cell_floats[1],
                    runtime_cell_floats[2],
                )

                def _orth_range(
                    items: list[dict[str, Any]],
                ) -> dict[str, float]:
                    ds = [
                        1.0
                        / math.sqrt(
                            (it["hkl"][0] / ca) ** 2
                            + (it["hkl"][1] / cb) ** 2
                            + (it["hkl"][2] / cc) ** 2
                        )
                        for it in items
                    ]
                    return {"d_max": max(ds), "d_min": min(ds)}

                synth["resolution_ranges"] = {
                    "extracted_pre_fmodel": _orth_range(selected),
                    "final_effective": _orth_range(selected),
                    "actual_work": _orth_range([w0, w1]),
                    "actual_free": _orth_range([f0, f1]),
                }
                m_bytes, p_bytes = _build_synthetic_map_mtz_pair(
                    map_recs, map_recs, cell=cell_floats  # type: ignore[arg-type]
                )
                synth["map_coefficients"]["mtz_supplements"][
                    "phx_maps_sha256"
                ] = hashlib.sha256(m_bytes).hexdigest()
                synth["map_coefficients"]["mtz_supplements"][
                    "obs_pair_only_sha256"
                ] = hashlib.sha256(p_bytes).hexdigest()

                diag_doc = {
                    "schema_version": 1,
                    "status": "succeeded",
                    "extract_xtal_data_log": synth["diagnostics"][
                        "extract_xtal_data_log"
                    ],
                    "model_manager_log": synth["diagnostics"][
                        "model_manager_log"
                    ],
                    "fmodel_update_all_scales_log": synth["diagnostics"][
                        "fmodel_update_all_scales_log"
                    ],
                    "failure": None,
                }
                log.write_text("synthetic phenix.python stdout\n", encoding="utf-8")
                out_maps.write_bytes(m_bytes)
                out_obs_pair.write_bytes(p_bytes)
                out_diag.write_text(
                    json.dumps(diag_doc, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                out_json.write_text(
                    json.dumps(synth, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(argv, 0)

            with (
                mock.patch.object(
                    toolchain,
                    "phenix",
                    side_effect=lambda exe: fake_bin / exe,
                ),
                mock.patch.object(
                    toolchain,
                    "phenix_build_evidence",
                    return_value=fake_measured_build,
                ),
            ):
                reconciled = onesar_rerun.run_phenix_rfactor_operation(
                    fake_repo / "runs" / "r4_success",
                    subject_id="R4",
                    repo_root=fake_repo,
                    archive_path=COMMITTED_ARCHIVE,
                    require_no_protstruct_overrides=False,
                    runner=fake_success_runner,
                )

                self.assertEqual(
                    reconciled["operation_manifest"]["returncode"], 0
                )
                self.assertTrue(reconciled["operation_manifest"]["reusable"])
                manifest_path = Path(reconciled["manifest_path"])
                self.assertTrue(manifest_path.is_file())
                self.assertEqual(manifest_path.name, "success.json")
                self.assertEqual(manifest_path.parent.name, "bundle")
                self.assertTrue(
                    Path(reconciled["phenix_rfactors_json_path"]).is_file()
                )
                self.assertTrue(
                    Path(reconciled["phenix_diagnostics_json_path"]).is_file()
                )
                self.assertTrue(
                    Path(reconciled["input_hkl_ledger_json_path"]).is_file()
                )
                self.assertTrue(Path(reconciled["phx_maps_mtz_path"]).is_file())
                self.assertTrue(
                    Path(reconciled["phx_obs_pair_only_mtz_path"]).is_file()
                )
                self.assertTrue(
                    Path(
                        reconciled["preflight_build_evidence_json_path"]
                    ).is_file()
                )
                self.assertEqual(
                    json.loads(
                        Path(
                            reconciled["preflight_build_evidence_json_path"]
                        ).read_text(encoding="utf-8")
                    ),
                    fake_measured_build,
                )
                self.assertFalse(
                    (
                        fake_repo
                        / "runs"
                        / "r4_success"
                        / "phenix"
                        / "phenix_build_admission_failure.json"
                    ).exists()
                )
                self.assertEqual(
                    reconciled["reconciliation"]["reconciliation_status"],
                    "verified",
                )

                # Failure retention test: non-zero exit raises OperationFailed and retains log
                # as well as parent failure manifest with paths/hashes of partial/diagnostic artifacts (#1014).
                def fake_failing_runner(
                    argv: list[str], log: Path, *, cwd: Path, timeout: float
                ) -> subprocess.CompletedProcess[str]:
                    out_diag = Path(
                        argv[argv.index("--out-diagnostics-json") + 1]
                    )
                    out_partial = Path(
                        argv[argv.index("--out-partial-json") + 1]
                    )
                    self.assertEqual(out_diag.parent, cwd)
                    self.assertEqual(out_partial.parent, cwd)
                    log.write_text(
                        "simulated extraction failure\n", encoding="utf-8"
                    )
                    onesar_phenix_measure._atomic_write_json_checkpoint(
                        {
                            "schema_version": 1,
                            "status": "failed",
                            "current_phase": "rfactor_replay",
                            "completed_raw_stages": [
                                "extract_xtal_data",
                                "xray_structure_invariance",
                                "rfactor_raw_arrays_and_scalars",
                            ],
                            "partial_evidence_status": "failed_partial_unverified",
                            "failure": {
                                "failed_phase": "rfactor_replay",
                                "exception_type": "RuntimeError",
                                "exception_message": "simulated rfactor mismatch",
                            },
                        },
                        out_diag,
                    )
                    onesar_phenix_measure._atomic_write_json_checkpoint(
                        {
                            "schema_version": 1,
                            "artifact_role": "partial_unverified_phenix_evidence",
                            "reusable_cache_output": False,
                            "canonical_eval_qds_eligible": False,
                            "status": "failed_partial_unverified",
                            "current_phase": "rfactor_replay",
                            "completed_stages": [
                                "extract_xtal_data",
                                "xray_structure_invariance",
                                "rfactor_raw_arrays_and_scalars",
                            ],
                            "rfactor_replay_verified": False,
                            "map_export_verified": False,
                            "failure": {
                                "failed_phase": "rfactor_replay",
                                "exception_type": "RuntimeError",
                                "exception_message": "simulated rfactor mismatch",
                            },
                        },
                        out_partial,
                    )
                    return subprocess.CompletedProcess(argv, 2)

                r4_failure_dir = fake_repo / "runs" / "r4_failure"
                with self.assertRaises(refinement_cache.OperationFailed) as ctx:
                    onesar_rerun.run_phenix_rfactor_operation(
                        r4_failure_dir,
                        subject_id="R4",
                        repo_root=fake_repo,
                        archive_path=COMMITTED_ARCHIVE,
                        require_no_protstruct_overrides=False,
                        runner=fake_failing_runner,
                    )
                self.assertTrue(ctx.exception.log_path.is_file())
                self.assertIn(
                    "simulated extraction failure",
                    ctx.exception.log_path.read_text(encoding="utf-8"),
                )
                parent_failure_path = (
                    r4_failure_dir / "phenix" / "phenix_operation_failure.json"
                )
                self.assertTrue(parent_failure_path.is_file())
                parent_failure_doc = json.loads(
                    parent_failure_path.read_text(encoding="utf-8")
                )
                self.assertEqual(parent_failure_doc["status"], "failed")
                self.assertFalse(parent_failure_doc["reusable_cache_output"])
                self.assertFalse(
                    parent_failure_doc["canonical_eval_qds_eligible"]
                )
                self.assertIn(
                    "phenix_partial_evidence_json",
                    parent_failure_doc["retained_attempt_artifacts"],
                )
                self.assertIn(
                    "phenix_diagnostics_json",
                    parent_failure_doc["retained_attempt_artifacts"],
                )
                retained_partial_entry = parent_failure_doc[
                    "retained_attempt_artifacts"
                ]["phenix_partial_evidence_json"]
                self.assertEqual(
                    retained_partial_entry["sha256"],
                    hashlib.sha256(
                        Path(retained_partial_entry["path"]).read_bytes()
                    ).hexdigest(),
                )
                self.assertEqual(
                    parent_failure_doc["partial_evidence_summary"][
                        "completed_stages"
                    ],
                    [
                        "extract_xtal_data",
                        "xray_structure_invariance",
                        "rfactor_raw_arrays_and_scalars",
                    ],
                )
                self.assertFalse(
                    (
                        r4_failure_dir
                        / "phenix"
                        / "phenix_reconciled_manifest.json"
                    ).exists()
                )

            # Drift between preflight phenix_build_evidence() and cached_phenix_operation's
            # internal phenix_build_evidence() call is rejected (#1013).
            drifted_build = copy.deepcopy(fake_measured_build)
            drifted_build["version_probe"]["setup_sha256"] = "b" * 64
            with (
                mock.patch.object(
                    toolchain,
                    "phenix",
                    side_effect=lambda exe: fake_bin / exe,
                ),
                mock.patch.object(
                    toolchain,
                    "phenix_build_evidence",
                    side_effect=[fake_measured_build, drifted_build],
                ),
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "Cache manifest measured_build drifted from preflight",
                ):
                    onesar_rerun.run_phenix_rfactor_operation(
                        fake_repo / "runs" / "r4_drift",
                        subject_id="R4",
                        repo_root=fake_repo,
                        archive_path=COMMITTED_ARCHIVE,
                        require_no_protstruct_overrides=False,
                        runner=fake_success_runner,
                    )

            # Hermetic local-Python subprocess timeout test (#1014):
            # Invoke the actual onesar_phenix_measure.py worker in a child subprocess via
            # cached_phenix_operation + toolchain.run_logged (runner=None) with a bounded
            # timeout while fmodel.update_all_scales writes through _PersistentTeeLogStream
            # and then blocks past the timeout (so finally: and except: never run).
            timeout_prefix = tmp_root / "phenix-timeout-2.0-5936"
            timeout_bin = timeout_prefix / "phenix_bin"
            timeout_site = (
                timeout_prefix / "lib" / "python3.9" / "site-packages"
            )
            timeout_bin.mkdir(parents=True)
            (timeout_prefix / "phenix_env.sh").write_text(
                "#!/bin/sh\nexport PHENIX_VERSION=2.0\nexport PHENIX_RELEASE_TAG=5936\n",
                encoding="utf-8",
            )
            (timeout_bin / "phenix.version").write_text(
                "#!/bin/sh\n", encoding="utf-8"
            )
            for pkg_rel in (
                "cctbx/__init__.py",
                "iotbx/__init__.py",
                "iotbx/mtz/__init__.py",
                "mmtbx/__init__.py",
                "mmtbx/f_model/__init__.py",
            ):
                pkg_init = timeout_site / pkg_rel
                pkg_init.parent.mkdir(parents=True, exist_ok=True)
                pkg_init.write_text(
                    "from .f_model import manager\n"
                    if pkg_rel == "mmtbx/f_model/__init__.py"
                    else "# synthetic package\n",
                    encoding="utf-8",
                )

            (timeout_site / "cctbx" / "crystal.py").write_text(
                "import struct, types\n"
                "_F32_CELL = struct.unpack('<6f', struct.pack('<6f', 64.897, 78.323, 38.792, 90.0, 90.0, 90.0))\n"
                "_OPS = [types.SimpleNamespace(as_xyz=lambda s=op: s) for op in ('x,y,z', '-x+1/2,-y,z+1/2', '-x,y+1/2,-z+1/2', 'x+1/2,-y+1/2,-z')]\n"
                "_SG = types.SimpleNamespace(type=lambda: types.SimpleNamespace(number=lambda: 19), all_ops=lambda: list(_OPS))\n"
                "_SGI = types.SimpleNamespace(symbol_and_number=lambda: 'P 21 21 21 (No. 19)', type=lambda: types.SimpleNamespace(number=lambda: 19), group=lambda: _SG)\n"
                "_SYM = types.SimpleNamespace(\n"
                "    unit_cell=lambda: types.SimpleNamespace(parameters=lambda: _F32_CELL),\n"
                "    space_group=lambda: _SG,\n"
                "    space_group_info=lambda: _SGI,\n"
                ")\n"
                "def select_crystal_symmetry(**kwargs):\n"
                "    return _SYM\n",
                encoding="utf-8",
            )
            (timeout_site / "iotbx" / "pdb.py").write_text(
                "from cctbx.crystal import _SYM\n"
                "class _Inp:\n"
                "    def crystal_symmetry(self):\n"
                "        return _SYM\n"
                "def input(file_name):\n"
                "    return _Inp()\n",
                encoding="utf-8",
            )
            (timeout_site / "iotbx" / "mtz" / "__init__.py").write_text(
                "import types\n"
                "def label_decorator(phases_prefix='PH'):\n"
                "    return types.SimpleNamespace(phases_prefix=phases_prefix)\n",
                encoding="utf-8",
            )
            (timeout_site / "iotbx" / "reflection_file_reader.py").write_text(
                "import types\n"
                "from cctbx.crystal import _SYM\n"
                "def any_reflection_file(file_name):\n"
                "    return types.SimpleNamespace(\n"
                "        file_type=lambda: 'ccp4_mtz',\n"
                "        as_miller_arrays=lambda: [types.SimpleNamespace(crystal_symmetry=lambda: _SYM)],\n"
                "    )\n",
                encoding="utf-8",
            )
            (timeout_site / "iotbx" / "reflection_file_utils.py").write_text(
                "def reflection_file_server(**kwargs):\n    return 'RFS'\n",
                encoding="utf-8",
            )
            (timeout_site / "iotbx" / "extract_xtal_data.py").write_text(
                "import io, struct, types\n"
                "_CA_F32 = struct.unpack('<f', struct.pack('<f', 64.897))[0]\n"
                "class _Arr(list):\n"
                "    def all_eq(self, other):\n"
                "        return list(self) == list(other)\n"
                "class _Miller:\n"
                "    def __init__(self, idx, data, sigmas=None):\n"
                "        self._idx = _Arr(idx)\n"
                "        self._data = _Arr(data)\n"
                "        self._sigmas = _Arr(sigmas) if sigmas is not None else None\n"
                "    def indices(self):\n"
                "        return self._idx\n"
                "    def data(self):\n"
                "        return self._data\n"
                "    def sigmas(self):\n"
                "        return self._sigmas\n"
                "    def d_min(self):\n"
                "        return 1.8\n"
                "    def d_max_min(self):\n"
                "        return (_CA_F32, 1.8)\n"
                "def data_and_flags_master_params():\n"
                "    return types.SimpleNamespace(\n"
                "        extract=lambda: types.SimpleNamespace(\n"
                "            labels=None,\n"
                "            r_free_flags=types.SimpleNamespace(\n"
                "                label=None, test_flag_value=None, generate=True, ignore_r_free_flags=True\n"
                "            ),\n"
                "        )\n"
                "    )\n"
                "def run(reflection_file_server, parameters=None, keep_going=False):\n"
                "    log_buf = io.StringIO()\n"
                "    log_buf.write('LIVE_EXTRACT_XTAL_DATA_MARKER\\n')\n"
                "    hkls = [(1, 0, 0), (0, 1, 0)]\n"
                "    return types.SimpleNamespace(\n"
                "        log=log_buf,\n"
                "        err=[],\n"
                "        f_obs=_Miller(hkls, [100.0, 80.0], [2.0, 1.8]),\n"
                "        r_free_flags=_Miller(hkls, [False, True]),\n"
                "        raw_data=None,\n"
                "        raw_flags=None,\n"
                "        test_flag_value=1,\n"
                "    )\n",
                encoding="utf-8",
            )
            (timeout_site / "mmtbx" / "model_vs_data.py").write_text(
                "def reflection_file_server(**kwargs):\n    return 'RFS'\n",
                encoding="utf-8",
            )
            (timeout_site / "mmtbx" / "map_tools.py").write_text(
                "# synthetic map_tools\n",
                encoding="utf-8",
            )
            (timeout_site / "mmtbx" / "model.py").write_text(
                "import types\n"
                "class _Scat:\n"
                "    label = 'N'\n"
                "    scattering_type = 'N'\n"
                "    site = (0.1, 0.2, 0.3)\n"
                "    occupancy = 1.0\n"
                "    u_iso = 0.25\n"
                "    u_star = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)\n"
                "    flags = types.SimpleNamespace(use_u_iso=lambda: True, use_u_aniso=lambda: False)\n"
                "class _Xrs:\n"
                "    def scatterers(self):\n"
                "        return [_Scat()]\n"
                "    def sites_cart(self):\n"
                "        return [(6.4, 15.6, 11.6)]\n"
                "    def scattering_type_registry(self):\n"
                "        return types.SimpleNamespace(Unassigned=False, has_unknown_type_symbols=lambda: False)\n"
                "def manager(model_input, crystal_symmetry, log=None):\n"
                "    if log is not None:\n"
                "        log.write('LIVE_MODEL_MANAGER_MARKER_BEFORE_SCALES\\n')\n"
                "    xrs = _Xrs()\n"
                "    return types.SimpleNamespace(\n"
                "        get_xray_structure=lambda: xrs,\n"
                "        setup_scattering_dictionaries=lambda **kw: None,\n"
                "    )\n",
                encoding="utf-8",
            )
            (timeout_site / "mmtbx" / "f_model" / "f_model.py").write_text(
                "import time, types\n"
                "from mmtbx.model import _Xrs\n"
                "def manager(xray_structure, r_free_flags, f_obs, twin_law=None):\n"
                "    def _update_all_scales(update_f_part1=True, log=None):\n"
                "        if log is not None:\n"
                "            log.write('LIVE_SCALING_MARKER_BEFORE_TIMEOUT\\n')\n"
                "        time.sleep(5.0)\n"
                "    return types.SimpleNamespace(\n"
                "        xray_structure=_Xrs(),\n"
                "        update_all_scales=_update_all_scales,\n"
                "    )\n",
                encoding="utf-8",
            )

            for rel_vendor in onesar_rerun.PHENIX_VENDOR_SOURCE_RELPATHS.values():
                self.assertTrue((timeout_site / rel_vendor).is_file())
            self.assertEqual(
                set(
                    onesar_rerun.resolve_phenix_vendor_source_files(
                        timeout_prefix
                    )
                ),
                set(onesar_rerun.PHENIX_VENDOR_SOURCE_RELPATHS),
            )

            resolved_timeout_prefix = str(timeout_prefix.resolve(strict=True))
            resolved_timeout_site = str(timeout_site.resolve(strict=True))
            timeout_py_wrapper = timeout_bin / "phenix.python"
            bootstrap_py = timeout_prefix / "bootstrap_phenix_python.py"
            bootstrap_py.write_text(
                "import runpy, sys\n"
                f"sys.prefix = {resolved_timeout_prefix!r}\n"
                f"sys.executable = {str(timeout_py_wrapper)!r}\n"
                f"sys.path.insert(0, {resolved_timeout_site!r})\n"
                "sys.argv = sys.argv[1:]\n"
                "runpy.run_path(sys.argv[0], run_name='__main__')\n",
                encoding="utf-8",
            )
            timeout_py_wrapper.write_text(
                "#!/bin/sh\n"
                f'exec "{sys.executable}" "{bootstrap_py.resolve(strict=True)}" "$@"\n',
                encoding="utf-8",
            )
            timeout_py_wrapper.chmod(0o755)

            timeout_setup_resolved = (
                timeout_prefix / "phenix_env.sh"
            ).resolve(strict=True)
            timeout_disp_resolved = (
                timeout_bin / "phenix.version"
            ).resolve(strict=True)
            timeout_measured_build = copy.deepcopy(fake_measured_build)
            timeout_measured_build["version_probe"].update(
                {
                    "configured_prefix": str(timeout_prefix),
                    "resolved_prefix": resolved_timeout_prefix,
                    "setup_configured_path": str(
                        timeout_prefix / "phenix_env.sh"
                    ),
                    "setup_resolved_path": str(timeout_setup_resolved),
                    "setup_sha256": hashlib.sha256(
                        timeout_setup_resolved.read_bytes()
                    ).hexdigest(),
                    "setup_argv": toolchain.phenix_setup_argv(
                        timeout_setup_resolved
                    ),
                    "configured_path": str(timeout_bin / "phenix.version"),
                    "resolved_path": str(timeout_disp_resolved),
                    "sha256": hashlib.sha256(
                        timeout_disp_resolved.read_bytes()
                    ).hexdigest(),
                    "argv": [str(timeout_disp_resolved)],
                }
            )

            def _readiness_aware_timeout_subprocess_run(
                cmd: Any, *args: Any, **kwargs: Any
            ) -> subprocess.CompletedProcess[str]:
                cwd_path = Path(kwargs["cwd"])
                diag_file = cwd_path / "phenix_diagnostics.json"
                proc = subprocess.Popen(
                    cmd,
                    cwd=kwargs.get("cwd"),
                    stdout=kwargs.get("stdout"),
                    stderr=kwargs.get("stderr"),
                    text=kwargs.get("text", True),
                    env=kwargs.get("env"),
                )
                try:
                    deadline = time.monotonic() + 15.0
                    while time.monotonic() < deadline:
                        if diag_file.is_file():
                            try:
                                doc = json.loads(
                                    diag_file.read_text(encoding="utf-8")
                                )
                                if (
                                    doc.get("current_phase")
                                    == "update_all_scales"
                                    and "LIVE_SCALING_MARKER_BEFORE_TIMEOUT"
                                    in (
                                        doc.get("fmodel_update_all_scales_log")
                                        or ""
                                    )
                                ):
                                    break
                            except (OSError, ValueError):
                                pass
                        if proc.poll() is not None:
                            break
                        time.sleep(0.01)
                    proc.communicate(timeout=0.05)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                    raise
                return subprocess.CompletedProcess(cmd, proc.returncode or 0)

            timeout_run_dir = fake_repo / "runs" / "r4_live_timeout"
            with (
                mock.patch.object(
                    toolchain,
                    "phenix",
                    side_effect=lambda exe: timeout_bin / exe,
                ),
                mock.patch.object(
                    toolchain,
                    "phenix_build_evidence",
                    return_value=timeout_measured_build,
                ),
                mock.patch.object(
                    toolchain.subprocess,
                    "run",
                    side_effect=_readiness_aware_timeout_subprocess_run,
                ),
            ):
                with self.assertRaises(refinement_cache.OperationFailed) as t_ctx:
                    onesar_rerun.run_phenix_rfactor_operation(
                        timeout_run_dir,
                        subject_id="R4",
                        repo_root=fake_repo,
                        archive_path=COMMITTED_ARCHIVE,
                        require_no_protstruct_overrides=False,
                        runner=None,
                        timeout=2.5,
                    )

            self.assertTrue(t_ctx.exception.log_path.is_file())
            self.assertIn(
                "PHENIX operation timed out; retained log:",
                str(t_ctx.exception),
            )
            self.assertIsInstance(
                t_ctx.exception.__cause__, subprocess.TimeoutExpired
            )
            stdout_log_text = t_ctx.exception.log_path.read_text(
                encoding="utf-8"
            )
            self.assertIn(
                "=== [onesar_phenix_measure] mmtbx.model.manager ===",
                stdout_log_text,
            )
            self.assertIn(
                "LIVE_MODEL_MANAGER_MARKER_BEFORE_SCALES",
                stdout_log_text,
            )
            self.assertIn(
                "=== [onesar_phenix_measure] fmodel.update_all_scales ===",
                stdout_log_text,
            )
            self.assertIn(
                "LIVE_SCALING_MARKER_BEFORE_TIMEOUT",
                stdout_log_text,
            )

            timeout_diag_path = (
                t_ctx.exception.log_path.parent / "phenix_diagnostics.json"
            )
            self.assertTrue(timeout_diag_path.is_file())
            timeout_diag_doc = json.loads(
                timeout_diag_path.read_text(encoding="utf-8")
            )
            self.assertEqual(timeout_diag_doc["status"], "running")
            self.assertEqual(
                timeout_diag_doc["current_phase"], "update_all_scales"
            )
            self.assertEqual(
                timeout_diag_doc["phase_history"],
                [
                    "parameter_validation",
                    "vendor_imports",
                    "runtime_environment_inspection",
                    "pdb_input",
                    "reflection_file_input",
                    "crystal_symmetry_consensus",
                    "extract_xtal_data",
                    "model_manager",
                    "fmodel_manager_init",
                    "update_all_scales",
                ],
            )
            self.assertEqual(
                timeout_diag_doc["extract_xtal_data_log"],
                "LIVE_EXTRACT_XTAL_DATA_MARKER\n",
            )
            self.assertEqual(
                timeout_diag_doc["model_manager_log"],
                "LIVE_MODEL_MANAGER_MARKER_BEFORE_SCALES\n",
            )
            self.assertEqual(
                timeout_diag_doc["fmodel_update_all_scales_log"],
                "LIVE_SCALING_MARKER_BEFORE_TIMEOUT\n",
            )
            self.assertIsNone(timeout_diag_doc["failure"])

            timeout_partial_path = (
                t_ctx.exception.log_path.parent
                / "phenix_rfactors_partial_evidence.json"
            )
            self.assertTrue(timeout_partial_path.is_file())
            timeout_partial_doc = json.loads(
                timeout_partial_path.read_text(encoding="utf-8")
            )
            self.assertEqual(
                timeout_partial_doc["status"], "running_partial_unverified"
            )
            self.assertEqual(
                timeout_partial_doc["completed_stages"],
                ["extract_xtal_data", "xray_structure_snapshot_before"],
            )
            self.assertEqual(
                len(timeout_partial_doc["extracted_pre_fmodel"]), 2
            )
            self.assertEqual(
                timeout_partial_doc["xray_structure_snapshots_raw"]["before"][
                    "n_scatterers"
                ],
                1,
            )
            self.assertIsNone(
                timeout_partial_doc["xray_structure_snapshots_raw"][
                    "after_model"
                ]
            )
            self.assertIsNone(
                timeout_partial_doc["xray_structure_snapshots_raw"][
                    "after_fmodel"
                ]
            )
            self.assertFalse(
                timeout_partial_doc["xray_structure_snapshots_raw"][
                    "invariance_verified"
                ]
            )
            self.assertIsNone(timeout_partial_doc["xray_structure_invariance"])
            timeout_parent_fail = (
                timeout_run_dir / "phenix" / "phenix_operation_failure.json"
            )
            self.assertTrue(timeout_parent_fail.is_file())
            timeout_parent_doc = json.loads(
                timeout_parent_fail.read_text(encoding="utf-8")
            )
            self.assertIn(
                "phenix_partial_evidence_json",
                timeout_parent_doc["retained_attempt_artifacts"],
            )
            self.assertIn(
                "phenix_diagnostics_json",
                timeout_parent_doc["retained_attempt_artifacts"],
            )

    def test_in_process_measure_first_block_rfactors_with_source_backed_doubles_1017(
        self,
    ) -> None:
        """Directly execute measure_first_block_rfactors in-process with narrow source-backed doubles."""

        class _FakeArray(list):
            def size(self) -> int:
                return len(self)

            def all_eq(self, other: Any) -> bool:
                return list(self) == list(other)

        class _FakeMillerArray:
            def __init__(
                self,
                indices: list[tuple[int, int, int]],
                data: list[Any],
                sigmas: list[float] | None = None,
                centric_flags: list[bool] | None = None,
            ) -> None:
                self._indices = _FakeArray(indices)
                self._data = _FakeArray(data)
                self._sigmas = (
                    _FakeArray(sigmas) if sigmas is not None else None
                )
                self._centric = (
                    _FakeArray(centric_flags)
                    if centric_flags is not None
                    else _FakeArray([idx[1] == 0 for idx in indices])
                )

            def indices(self) -> _FakeArray:
                return self._indices

            def data(self) -> _FakeArray:
                return self._data

            def sigmas(self) -> _FakeArray | None:
                return self._sigmas

            def size(self) -> int:
                return len(self._indices)

            def _d_values(self) -> list[float]:
                f32_cell = onesar_rerun.ccp4_mtz_float32_unit_cell(
                    (64.897, 78.323, 38.792, 90.0, 90.0, 90.0)
                )
                return [
                    onesar_rerun.compute_hkl_d_spacing((h, k, l), f32_cell)
                    for h, k, l in self._indices
                ]

            def d_min(self) -> float:
                return min(self._d_values())

            def d_max_min(self) -> tuple[float, float]:
                d_vals = self._d_values()
                return (max(d_vals), min(d_vals))

            def info(self) -> str:
                return "synthetic_miller_array"

            def centric_flags(self) -> Any:
                parent = self

                class _Flags:
                    def data(self_inner) -> _FakeArray:
                        return parent._centric

                return _Flags()

            def as_mtz_dataset(
                self, column_root_label: str, label_decorator: Any = None
            ) -> Any:
                return _FakeMtzDataset(self, column_root_label)

        class _FakeMtzDataset:
            fail_in_map_write: bool = False

            def __init__(self, first_array: _FakeMillerArray, root_label: str) -> None:
                self.arrays: list[tuple[_FakeMillerArray, str]] = [
                    (first_array, root_label)
                ]

            def add_miller_array(
                self,
                miller_array: _FakeMillerArray,
                column_root_label: str,
                label_decorator: Any = None,
            ) -> None:
                self.arrays.append((miller_array, column_root_label))

            def mtz_object(self) -> Any:
                parent = self

                class _Writer:
                    def column_labels(self_inner) -> list[str]:
                        cols = ["H", "K", "L"]
                        for _, lbl in parent.arrays:
                            cols.extend([lbl, f"PH{lbl}"])
                        return cols

                    def write(self_inner, file_name: str) -> None:
                        if _FakeMtzDataset.fail_in_map_write:
                            raise RuntimeError(
                                "Injected synthetic map write failure"
                            )
                        recs_by_label: dict[str, list[dict[str, Any]]] = {}
                        for arr, lbl in parent.arrays:
                            recs: list[dict[str, Any]] = []
                            for idx, cval, is_c in zip(
                                arr.indices(),
                                arr.data(),
                                arr.centric_flags().data(),
                            ):
                                re_v = float(cval.real)
                                im_v = float(cval.imag)
                                amp_v = math.hypot(re_v, im_v)
                                ph_v = (
                                    0.0
                                    if amp_v == 0.0
                                    else math.degrees(math.atan2(im_v, re_v))
                                )
                                recs.append(
                                    {
                                        "hkl": list(idx),
                                        "real": re_v,
                                        "imag": im_v,
                                        "amplitude": amp_v,
                                        "phase_deg": ph_v,
                                        "is_centric": bool(is_c),
                                    }
                                )
                            recs_by_label[lbl] = recs
                        if "FOFCWT" in recs_by_label:
                            m_bytes, _ = _build_synthetic_map_mtz_pair(
                                recs_by_label["2FOFCWT"],
                                recs_by_label["FOFCWT"],
                            )
                            Path(file_name).write_bytes(m_bytes)
                        else:
                            _, p_bytes = _build_synthetic_map_mtz_pair(
                                recs_by_label["2FOFCWT"],
                                recs_by_label["2FOFCWT"],
                            )
                            Path(file_name).write_bytes(p_bytes)

                return _Writer()

        class _FakeMtzObjectReadback:
            def __init__(self, file_name: str) -> None:
                mtz_bytes = Path(file_name).read_bytes()
                _, headers = onesar_rerun._mtz_headers(mtz_bytes)
                ncol_row = [
                    line.split() for line in headers if line.startswith("NCOL ")
                ][0]
                self._nrows = int(ncol_row[2])
                col_rows = [
                    line.split()
                    for line in headers
                    if line.startswith("COLUMN ")
                ]
                self._labels = [parts[1] for parts in col_rows]
                self._types = [parts[2] for parts in col_rows]

            def columns(self) -> list[Any]:
                return [
                    types.SimpleNamespace(
                        label=lambda l=lbl: l,
                        type=lambda t=tp: t,
                    )
                    for lbl, tp in zip(self._labels, self._types)
                ]

            def column_labels(self) -> list[str]:
                return list(self._labels)

            def column_types(self) -> list[str]:
                return list(self._types)

            def n_reflections(self) -> int:
                return self._nrows

        class _FakeScatterer:
            def __init__(self) -> None:
                self.label = "PDB=\" N   VAL A   1 \""
                self.scattering_type = "N"
                self.site = (0.1, 0.2, 0.3)
                self.occupancy = 1.0
                self.u_iso = 0.25
                self.u_star = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
                self.flags = types.SimpleNamespace(
                    use_u_iso=lambda: True,
                    use_u_aniso=lambda: False,
                )

        class _FakeXrayStructure:
            def scatterers(self) -> list[_FakeScatterer]:
                return [_FakeScatterer()]

            def sites_cart(self) -> list[tuple[float, float, float]]:
                return [(6.4897, 15.6646, 11.6376)]

            def scattering_type_registry(self) -> Any:
                return types.SimpleNamespace(
                    Unassigned=False,
                    has_unknown_type_symbols=lambda: False,
                )

        hkls_5 = [(1, 0, 0), (0, 1, 0), (1, 1, 1), (2, 0, 0), (0, 2, 0)]
        f_obs_5 = [100.0, 200.0, 150.0, 80.0, 120.0]
        sigf_5 = [2.0, 3.0, 2.5, 1.8, 2.2]
        flags_5 = [False, False, False, True, True]

        hkls_4 = [(1, 0, 0), (0, 1, 0), (2, 0, 0), (0, 2, 0)]
        f_obs_4 = [100.0, 200.0, 80.0, 120.0]
        sigf_4 = [2.0, 3.0, 1.8, 2.2]
        flags_4 = [False, False, True, True]

        hkls_w = [(1, 0, 0), (0, 1, 0)]
        f_obs_w = [100.0, 200.0]
        sigf_w = [2.0, 3.0]
        fm_w = [complex(108.0, 144.0), complex(252.0, 336.0)]
        fm_scaled_w = [complex(54.0, 72.0), complex(126.0, 168.0)]

        hkls_t = [(2, 0, 0), (0, 2, 0)]
        f_obs_t = [80.0, 120.0]
        sigf_t = [1.8, 2.2]
        fm_t = [complex(60.0, 80.0), complex(150.0, 200.0)]
        fm_scaled_t = [complex(36.0, 48.0), complex(90.0, 120.0)]

        _fake_f32_cell = onesar_rerun.ccp4_mtz_float32_unit_cell(
            (64.897, 78.323, 38.792, 90.0, 90.0, 90.0)
        )
        _fake_rt_mx_ops = [
            types.SimpleNamespace(as_xyz=lambda s=op: s)
            for op in (
                "x,y,z",
                "-x+1/2,-y,z+1/2",
                "-x,y+1/2,-z+1/2",
                "x+1/2,-y+1/2,-z",
            )
        ]
        _fake_space_group = types.SimpleNamespace(
            type=lambda: types.SimpleNamespace(number=lambda: 19),
            all_ops=lambda: list(_fake_rt_mx_ops),
        )
        _fake_space_group_info = types.SimpleNamespace(
            symbol_and_number=lambda: "P 21 21 21 (No. 19)",
            type=lambda: types.SimpleNamespace(number=lambda: 19),
            group=lambda: _fake_space_group,
        )
        _fake_symmetry = types.SimpleNamespace(
            unit_cell=lambda: types.SimpleNamespace(
                parameters=lambda: _fake_f32_cell
            ),
            space_group=lambda: _fake_space_group,
            space_group_info=lambda: _fake_space_group_info,
        )

        def _make_vendor_modules(
            *,
            df_err: list[str] | None = None,
            raise_in_extract: bool = False,
            fail_in_fmodel: bool = False,
            fail_in_map_write: bool = False,
            fail_in_map_coefficients: bool = False,
            fail_in_second_map_coefficients: bool = False,
            mutate_scatterer_count_in_scales: bool = False,
            mutate_scatterer_occupancy_in_scales: bool = False,
            nonfinite_scatterer_occupancy_in_scales: float | None = None,
            nonfinite_scatterer_u_iso_in_scales: float | None = None,
            empty_scatterers_in_scales: bool = False,
            symmetry_override: Any = None,
            nonfinite_work_model_coeff: bool = False,
            nonpositive_final_obs: bool = False,
            fail_in_free_array: bool = False,
            native_r_work_override: float | None = None,
        ) -> dict[str, Any]:
            _FakeMtzDataset.fail_in_map_write = fail_in_map_write
            scales_completed = [False]
            active_symmetry = (
                symmetry_override
                if symmetry_override is not None
                else _fake_symmetry
            )

            class _ScopedXrayStructure(_FakeXrayStructure):
                def scatterers(self) -> list[_FakeScatterer]:
                    if scales_completed[0] and empty_scatterers_in_scales:
                        return []
                    if (
                        scales_completed[0]
                        and mutate_scatterer_count_in_scales
                    ):
                        return [_FakeScatterer(), _FakeScatterer()]
                    if (
                        scales_completed[0]
                        and mutate_scatterer_occupancy_in_scales
                    ):
                        sc = _FakeScatterer()
                        sc.occupancy = 0.5
                        return [sc]
                    if (
                        scales_completed[0]
                        and nonfinite_scatterer_occupancy_in_scales is not None
                    ):
                        sc = _FakeScatterer()
                        sc.occupancy = nonfinite_scatterer_occupancy_in_scales
                        return [sc]
                    if (
                        scales_completed[0]
                        and nonfinite_scatterer_u_iso_in_scales is not None
                    ):
                        sc = _FakeScatterer()
                        sc.u_iso = nonfinite_scatterer_u_iso_in_scales
                        return [sc]
                    return super().scatterers()

                def sites_cart(self) -> list[tuple[float, float, float]]:
                    if scales_completed[0] and empty_scatterers_in_scales:
                        return []
                    if (
                        scales_completed[0]
                        and mutate_scatterer_count_in_scales
                    ):
                        return [
                            (6.4897, 15.6646, 11.6376),
                            (6.4897, 15.6646, 11.6376),
                        ]
                    return super().sites_cart()

            iotbx_mod = types.ModuleType("iotbx")
            iotbx_pdb = types.ModuleType("iotbx.pdb")
            iotbx_mtz = types.ModuleType("iotbx.mtz")
            iotbx_rfr = types.ModuleType("iotbx.reflection_file_reader")
            iotbx_rfu = types.ModuleType("iotbx.reflection_file_utils")
            iotbx_exd = types.ModuleType("iotbx.extract_xtal_data")
            mmtbx_mod = types.ModuleType("mmtbx")
            mmtbx_fmodel = types.ModuleType("mmtbx.f_model")
            mmtbx_fmodel_mod = types.ModuleType("mmtbx.f_model.f_model")
            mmtbx_map_tools = types.ModuleType("mmtbx.map_tools")
            mmtbx_model = types.ModuleType("mmtbx.model")
            mmtbx_mvd = types.ModuleType("mmtbx.model_vs_data")
            cctbx_mod = types.ModuleType("cctbx")
            cctbx_crystal = types.ModuleType("cctbx.crystal")

            class _PdbInp:
                def crystal_symmetry(self) -> Any:
                    return active_symmetry

                def get_r_rfree_sigma(self, *args: Any, **kwargs: Any) -> Any:
                    raise AssertionError(
                        "Second-block get_r_rfree_sigma must never be called"
                    )

            iotbx_pdb.input = lambda file_name: _PdbInp()
            iotbx_mtz.object = _FakeMtzObjectReadback
            iotbx_mtz.label_decorator = (
                lambda phases_prefix="PH": types.SimpleNamespace(
                    phases_prefix=phases_prefix
                )
            )
            iotbx_rfr.any_reflection_file = lambda file_name: types.SimpleNamespace(
                file_type=lambda: "ccp4_mtz",
                as_miller_arrays=lambda: [
                    types.SimpleNamespace(
                        crystal_symmetry=lambda: active_symmetry
                    )
                ],
            )
            iotbx_rfu.reflection_file_server = lambda **kwargs: "RFS"
            mmtbx_mvd.reflection_file_server = lambda **kwargs: "RFS"
            cctbx_crystal.select_crystal_symmetry = (
                lambda **kwargs: active_symmetry
            )

            def _data_and_flags_master_params() -> Any:
                return types.SimpleNamespace(
                    extract=lambda: types.SimpleNamespace(
                        file_name=None,
                        labels=None,
                        r_free_flags=types.SimpleNamespace(
                            file_name=None,
                            label=None,
                            test_flag_value=None,
                            generate=True,
                            ignore_r_free_flags=True,
                        ),
                    )
                )

            def _extract_run(
                reflection_file_server: Any,
                parameters: Any = None,
                keep_going: bool = False,
            ) -> Any:
                if raise_in_extract:
                    raise RuntimeError(
                        "extract_xtal_data constructor raised before returning"
                    )
                log_buf = io.StringIO()
                log_buf.write("Detailed extract_xtal_data log output\n")
                return types.SimpleNamespace(
                    log=log_buf,
                    err=list(df_err) if df_err is not None else [],
                    f_obs=_FakeMillerArray(hkls_5, f_obs_5, sigf_5),
                    r_free_flags=_FakeMillerArray(hkls_5, flags_5),
                    raw_data=_FakeMillerArray(hkls_5, f_obs_5, sigf_5),
                    raw_flags=_FakeMillerArray(hkls_5, [0, 0, 0, 1, 1]),
                    test_flag_value=1,
                )

            iotbx_exd.data_and_flags_master_params = (
                _data_and_flags_master_params
            )
            iotbx_exd.run = _extract_run

            def _model_manager(
                model_input: Any,
                crystal_symmetry: Any,
                log: Any,
            ) -> Any:
                log.write("model.manager initialization log\n")
                xrs = _ScopedXrayStructure()
                return types.SimpleNamespace(
                    get_xray_structure=lambda: xrs,
                    setup_scattering_dictionaries=lambda **kw: None,
                )

            mmtbx_model.manager = _model_manager

            def _map_coefficients(
                map_type: str,
                acentrics_scale: float = 2.0,
                centrics_pre_scale: float = 1.0,
                exclude_free_r_reflections: bool = False,
                fill_missing: bool = False,
                isotropize: bool = True,
                sharp: bool = False,
            ) -> _FakeMillerArray:
                if fail_in_map_coefficients:
                    raise RuntimeError(
                        "Injected synthetic map_coefficients failure"
                    )
                if fail_in_second_map_coefficients and map_type == "mFo-DFc":
                    raise RuntimeError(
                        "Injected synthetic second-map coefficient failure"
                    )
                if map_type == "2mFo-DFc":
                    return _FakeMillerArray(
                        hkls_4,
                        [
                            complex(10.0, 0.0),
                            complex(-12.0, 0.0),
                            complex(0.0, 8.0),
                            complex(0.0, -6.0),
                        ],
                        centric_flags=[True, True, False, False],
                    )
                return _FakeMillerArray(
                    hkls_4,
                    [
                        complex(2.0, 0.0),
                        complex(-1.5, 0.0),
                        complex(0.0, 1.25),
                        complex(0.0, -0.75),
                    ],
                    centric_flags=[True, True, False, False],
                )

            def _fmodel_manager(
                xray_structure: Any,
                r_free_flags: Any,
                f_obs: Any,
                twin_law: Any = None,
            ) -> Any:
                if fail_in_fmodel:
                    raise RuntimeError("Simulated f_model outlier failure")

                def _update_all_scales(
                    update_f_part1: bool = True,
                    log: Any = None,
                ) -> None:
                    if log is not None:
                        log.write("fmodel.update_all_scales log\n")
                    scales_completed[0] = True

                def _f_obs_free() -> _FakeMillerArray:
                    if fail_in_free_array:
                        raise RuntimeError(
                            "Injected synthetic f_obs_free failure"
                        )
                    return _FakeMillerArray(hkls_t, f_obs_t, sigf_t)

                effective_r_work = (
                    native_r_work_override
                    if native_r_work_override is not None
                    else (20.0 / 300.0)
                )
                return types.SimpleNamespace(
                    xray_structure=_ScopedXrayStructure(),
                    update_all_scales=_update_all_scales,
                    map_coefficients=_map_coefficients,
                    f_obs=lambda: _FakeMillerArray(
                        hkls_4,
                        [0.0, *f_obs_4[1:]]
                        if nonpositive_final_obs
                        else f_obs_4,
                        sigf_4,
                    ),
                    r_free_flags=lambda: _FakeMillerArray(hkls_4, flags_4),
                    f_obs_work=lambda: _FakeMillerArray(
                        hkls_w,
                        [0.0, *f_obs_w[1:]]
                        if nonpositive_final_obs
                        else f_obs_w,
                        sigf_w,
                    ),
                    f_obs_free=_f_obs_free,
                    f_model_work=lambda: _FakeMillerArray(
                        hkls_w,
                        [complex(float("nan"), 144.0), *fm_w[1:]]
                        if nonfinite_work_model_coeff
                        else fm_w,
                    ),
                    f_model_free=lambda: _FakeMillerArray(hkls_t, fm_t),
                    f_model_scaled_with_k1_w=lambda: _FakeMillerArray(
                        hkls_w,
                        [complex(float("nan"), 72.0), *fm_scaled_w[1:]]
                        if nonfinite_work_model_coeff
                        else fm_scaled_w,
                    ),
                    f_model_scaled_with_k1_t=lambda: _FakeMillerArray(
                        hkls_t, fm_scaled_t
                    ),
                    r_work=lambda: effective_r_work,
                    r_free=lambda: 50.0 / 200.0,
                    r_all=lambda: 70.6 / 500.0,
                    scale_k1_w=lambda: 0.5,
                    scale_k1_t=lambda: 0.6,
                    scale_k1=lambda: 0.54,
                )

            mmtbx_fmodel.manager = _fmodel_manager
            mmtbx_fmodel.f_model = mmtbx_fmodel_mod
            mmtbx_fmodel_mod.manager = _fmodel_manager

            iotbx_mod.pdb = iotbx_pdb
            iotbx_mod.mtz = iotbx_mtz
            iotbx_mod.reflection_file_reader = iotbx_rfr
            iotbx_mod.reflection_file_utils = iotbx_rfu
            iotbx_mod.extract_xtal_data = iotbx_exd
            mmtbx_mod.f_model = mmtbx_fmodel
            mmtbx_mod.map_tools = mmtbx_map_tools
            mmtbx_mod.model = mmtbx_model
            mmtbx_mod.model_vs_data = mmtbx_mvd
            cctbx_mod.crystal = cctbx_crystal

            return {
                "iotbx": iotbx_mod,
                "iotbx.pdb": iotbx_pdb,
                "iotbx.mtz": iotbx_mtz,
                "iotbx.reflection_file_reader": iotbx_rfr,
                "iotbx.reflection_file_utils": iotbx_rfu,
                "iotbx.extract_xtal_data": iotbx_exd,
                "mmtbx": mmtbx_mod,
                "mmtbx.f_model": mmtbx_fmodel,
                "mmtbx.f_model.f_model": mmtbx_fmodel_mod,
                "mmtbx.map_tools": mmtbx_map_tools,
                "mmtbx.model": mmtbx_model,
                "mmtbx.model_vs_data": mmtbx_mvd,
                "cctbx": cctbx_mod,
                "cctbx.crystal": cctbx_crystal,
            }

        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp).resolve(strict=True)
            fake_prefix = tmp_dir / "opt_phenix"
            fake_prefix.mkdir(parents=True, exist_ok=True)
            resolved_fake_prefix = str(fake_prefix.resolve(strict=True))
            pdb_path = tmp_dir / "model.pdb"
            mtz_path = tmp_dir / "obs.mtz"
            params_path = tmp_dir / "params.json"
            out_json = tmp_dir / "rfactors.json"
            out_maps = tmp_dir / "phx_maps.mtz"
            out_pair = tmp_dir / "PHX_OBS_PAIR_ONLY.mtz"
            out_diag = tmp_dir / "diagnostics.json"

            pdb_path.write_text("HEADER TEST\nEND\n", encoding="utf-8")
            ledger, fixture_payload, vendor_shas, _, _ = (
                _make_reconciliation_fixture()
            )
            mtz_path.write_bytes(b"MTZ_DUMMY")
            params = dict(onesar_phenix_measure.EXPECTED_PARAMETERS)
            params["subject_id"] = "R4"
            params["expected_resolved_prefix"] = resolved_fake_prefix
            params["expected_phenix_version"] = toolchain.PHENIX_VERSION
            params["map_coefficients"] = dict(
                onesar_phenix_measure.EXPECTED_MAP_PARAMETERS
            )
            params_path.write_text(
                json.dumps(params, indent=2) + "\n", encoding="utf-8"
            )

            fake_runtime_env = copy.deepcopy(
                fixture_payload["runtime_environment"]
            )
            fake_runtime_env["sys_prefix"] = resolved_fake_prefix
            fake_runtime_env["resolved_sys_prefix"] = resolved_fake_prefix
            fake_runtime_env["sys_executable"] = (
                f"{resolved_fake_prefix}/bin/python3.9"
            )
            fake_runtime_env["resolved_sys_executable"] = (
                f"{resolved_fake_prefix}/bin/python3.9"
            )
            for mod_key, rel in onesar_rerun.PHENIX_VENDOR_SOURCE_RELPATHS.items():
                mod_p = f"{resolved_fake_prefix}/lib/python3.9/site-packages/{rel}"
                fake_runtime_env["vendor_modules"][mod_key]["configured_path"] = (
                    mod_p
                )
                fake_runtime_env["vendor_modules"][mod_key]["resolved_path"] = (
                    mod_p
                )

            # 1. Success path in-process:
            with (
                mock.patch.dict(sys.modules, _make_vendor_modules()),
                mock.patch.object(
                    onesar_phenix_measure,
                    "_inspect_vendor_modules",
                    return_value=fake_runtime_env,
                ),
            ):
                result_payload = (
                    onesar_phenix_measure.measure_first_block_rfactors(
                        pdb_path=pdb_path,
                        mtz_path=mtz_path,
                        params_path=params_path,
                        out_json_path=out_json,
                        out_maps_mtz_path=out_maps,
                        out_obs_pair_mtz_path=out_pair,
                        out_diagnostics_json_path=out_diag,
                    )
                )

            self.assertTrue(out_json.is_file())
            self.assertTrue(out_maps.is_file())
            self.assertTrue(out_pair.is_file())
            self.assertTrue(out_diag.is_file())
            self.assertEqual(
                result_payload["diagnostics"]["current_phase"], "completed"
            )
            self.assertIn(
                "update_all_scales",
                result_payload["diagnostics"]["phase_history"],
            )
            reconciled = onesar_rerun.reconcile_phenix_rfactor_output(
                result_payload,
                ledger,
                expected_vendor_source_sha256=vendor_shas,
                expected_resolved_prefix=resolved_fake_prefix,
                phx_maps_mtz_path=out_maps,
                phx_obs_pair_only_mtz_path=out_pair,
                phenix_diagnostics_path=out_diag,
            )
            self.assertEqual(reconciled["reconciliation_status"], "verified")

            # 1b. Direct _PersistentTeeLogStream live-flush verification before finalize():
            live_diag_path = tmp_dir / "live_tee_diag.json"
            live_log_path = tmp_dir / "live_tee.log"
            live_diag: dict[str, Any] = {
                "status": "running",
                "current_phase": "update_all_scales",
                "fmodel_update_all_scales_log": "",
            }
            tee_stream = onesar_phenix_measure._PersistentTeeLogStream(
                "fmodel.update_all_scales",
                live_diag,
                "fmodel_update_all_scales_log",
                diagnostics_json_path=live_diag_path,
                log_file_path=live_log_path,
            )
            tee_stream.write("chunk_one\n")
            # Persisted on disk immediately on write() without calling finalize():
            self.assertEqual(
                live_log_path.read_text(encoding="utf-8"), "chunk_one\n"
            )
            self.assertEqual(
                json.loads(live_diag_path.read_text(encoding="utf-8"))[
                    "fmodel_update_all_scales_log"
                ],
                "chunk_one\n",
            )
            tee_stream.write("chunk_two")
            self.assertEqual(
                live_log_path.read_text(encoding="utf-8"),
                "chunk_one\nchunk_two",
            )
            self.assertEqual(
                json.loads(live_diag_path.read_text(encoding="utf-8"))[
                    "fmodel_update_all_scales_log"
                ],
                "chunk_one\nchunk_two",
            )

            # 1c. Deterministic interrupted-checkpoint test (#1014 Follow-up 2, #1017):
            # A failed/interrupted checkpoint write or promotion must preserve the prior
            # complete JSON checkpoint on disk and unlink the temporary sibling.
            with self.subTest(case="1c_interrupted_checkpoint"):
                self._verify_atomic_checkpoint_interrupted_write_and_promotion(
                    tmp_dir
                )

            # 2. Failure in extract_xtal_data retains df.log in diagnostics file (#1014, #1017):
            with self.subTest(case="2_extract_xtal_data_err"):
                out_diag_err = tmp_dir / "diagnostics_exd_err.json"
                with (
                    mock.patch.dict(
                        sys.modules,
                        _make_vendor_modules(
                            df_err=["Bad R-free flags column"]
                        ),
                    ),
                    mock.patch.object(
                        onesar_phenix_measure,
                        "_inspect_vendor_modules",
                        return_value=fake_runtime_env,
                    ),
                ):
                    with self.assertRaisesRegex(
                        RuntimeError, "extract_xtal_data reported errors"
                    ):
                        onesar_phenix_measure.measure_first_block_rfactors(
                            pdb_path=pdb_path,
                            mtz_path=mtz_path,
                            params_path=params_path,
                            out_json_path=tmp_dir / "unused1.json",
                            out_maps_mtz_path=tmp_dir / "unused1.mtz",
                            out_obs_pair_mtz_path=tmp_dir / "unused1_pair.mtz",
                            out_diagnostics_json_path=out_diag_err,
                        )
                self.assertTrue(out_diag_err.is_file())
                diag_err_doc = json.loads(
                    out_diag_err.read_text(encoding="utf-8")
                )
                self.assertEqual(diag_err_doc["status"], "failed")
                self.assertEqual(
                    diag_err_doc["current_phase"], "extract_xtal_data"
                )
                self.assertEqual(
                    diag_err_doc["failure"]["failed_phase"],
                    "extract_xtal_data",
                )
                self.assertIn(
                    "Detailed extract_xtal_data log output",
                    diag_err_doc["extract_xtal_data_log"],
                )

            # 2b. Exception inside extract_xtal_data.run before returning records
            # constructor_log_limitation for the unreturned internal StringIO (#1014):
            with self.subTest(case="2b_extract_xtal_data_raise"):
                out_diag_exd_raise = tmp_dir / "diagnostics_exd_raise.json"
                with (
                    mock.patch.dict(
                        sys.modules,
                        _make_vendor_modules(raise_in_extract=True),
                    ),
                    mock.patch.object(
                        onesar_phenix_measure,
                        "_inspect_vendor_modules",
                        return_value=fake_runtime_env,
                    ),
                ):
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "extract_xtal_data constructor raised before returning",
                    ):
                        onesar_phenix_measure.measure_first_block_rfactors(
                            pdb_path=pdb_path,
                            mtz_path=mtz_path,
                            params_path=params_path,
                            out_json_path=tmp_dir / "unused1b.json",
                            out_maps_mtz_path=tmp_dir / "unused1b.mtz",
                            out_obs_pair_mtz_path=tmp_dir / "unused1b_pair.mtz",
                            out_diagnostics_json_path=out_diag_exd_raise,
                        )
                self.assertTrue(out_diag_exd_raise.is_file())
                diag_exd_raise_doc = json.loads(
                    out_diag_exd_raise.read_text(encoding="utf-8")
                )
                self.assertEqual(diag_exd_raise_doc["status"], "failed")
                self.assertEqual(
                    diag_exd_raise_doc["current_phase"], "extract_xtal_data"
                )
                self.assertIsNone(diag_exd_raise_doc["extract_xtal_data_log"])
                self.assertIn(
                    "internal self.log StringIO on the unreturned instance is not accessible",
                    diag_exd_raise_doc["failure"]["constructor_log_limitation"],
                )

            # 3. Failure in mmtbx.f_model.manager records constructor_log_limitation (#1014):
            with self.subTest(case="3_fmodel_manager_init_fail"):
                out_diag_fm = tmp_dir / "diagnostics_fmodel_err.json"
                with (
                    mock.patch.dict(
                        sys.modules,
                        _make_vendor_modules(fail_in_fmodel=True),
                    ),
                    mock.patch.object(
                        onesar_phenix_measure,
                        "_inspect_vendor_modules",
                        return_value=fake_runtime_env,
                    ),
                ):
                    with self.assertRaisesRegex(
                        RuntimeError, "Simulated f_model outlier failure"
                    ):
                        onesar_phenix_measure.measure_first_block_rfactors(
                            pdb_path=pdb_path,
                            mtz_path=mtz_path,
                            params_path=params_path,
                            out_json_path=tmp_dir / "unused2.json",
                            out_maps_mtz_path=tmp_dir / "unused2.mtz",
                            out_obs_pair_mtz_path=tmp_dir / "unused2_pair.mtz",
                            out_diagnostics_json_path=out_diag_fm,
                        )
                self.assertTrue(out_diag_fm.is_file())
                diag_fm_doc = json.loads(
                    out_diag_fm.read_text(encoding="utf-8")
                )
                self.assertEqual(diag_fm_doc["status"], "failed")
                self.assertEqual(
                    diag_fm_doc["failure"]["failed_phase"],
                    "fmodel_manager_init",
                )
                self.assertIn(
                    "accepts no log parameter",
                    diag_fm_doc["failure"]["constructor_log_limitation"],
                )
                self.assertIn(
                    "model.manager initialization log",
                    diag_fm_doc["model_manager_log"],
                )
                partial_fm_doc = json.loads(
                    (tmp_dir / "unused2_partial_evidence.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(
                    partial_fm_doc["xray_structure_snapshots_raw"]["before"],
                    result_payload["xray_structure_invariance"]["snapshots"][
                        "before"
                    ],
                )
                self.assertIsNone(
                    partial_fm_doc["xray_structure_snapshots_raw"][
                        "after_model"
                    ]
                )
                self.assertIsNone(
                    partial_fm_doc["xray_structure_snapshots_raw"][
                        "after_fmodel"
                    ]
                )
                self.assertFalse(
                    partial_fm_doc["xray_structure_snapshots_raw"][
                        "invariance_verified"
                    ]
                )
                self.assertIsNone(partial_fm_doc["xray_structure_invariance"])

            # 3a1. Scatterer count change during scaling retains all three raw scatterer
            # snapshots (counts 1, 2, 2) while leaving verified invariance None (#1014, Task 120):
            with self.subTest(case="3a1_scatterer_count_change"):
                out_json_scc = tmp_dir / "rfactors_scc.json"
                out_partial_scc = (
                    tmp_dir / "rfactors_scc_partial_evidence.json"
                )
                out_diag_scc = tmp_dir / "diagnostics_scc.json"
                with (
                    mock.patch.dict(
                        sys.modules,
                        _make_vendor_modules(
                            mutate_scatterer_count_in_scales=True
                        ),
                    ),
                    mock.patch.object(
                        onesar_phenix_measure,
                        "_inspect_vendor_modules",
                        return_value=fake_runtime_env,
                    ),
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        "Scatterer count changed across f_model scaling",
                    ):
                        onesar_phenix_measure.measure_first_block_rfactors(
                            pdb_path=pdb_path,
                            mtz_path=mtz_path,
                            params_path=params_path,
                            out_json_path=out_json_scc,
                            out_maps_mtz_path=tmp_dir / "scc_maps.mtz",
                            out_obs_pair_mtz_path=tmp_dir / "scc_pair.mtz",
                            out_diagnostics_json_path=out_diag_scc,
                        )
                self.assertFalse(out_json_scc.is_file())
                self.assertTrue(out_partial_scc.is_file())
                partial_scc_doc = json.loads(
                    out_partial_scc.read_text(encoding="utf-8")
                )
                self.assertEqual(
                    partial_scc_doc["status"], "failed_partial_unverified"
                )
                self.assertFalse(partial_scc_doc["reusable_cache_output"])
                self.assertFalse(partial_scc_doc["canonical_eval_qds_eligible"])
                self.assertFalse(partial_scc_doc["rfactor_replay_verified"])
                self.assertFalse(partial_scc_doc["map_export_verified"])
                self.assertIsNone(partial_scc_doc["xray_structure_invariance"])
                raw_snaps_scc = partial_scc_doc["xray_structure_snapshots_raw"]
                self.assertFalse(raw_snaps_scc["invariance_verified"])
                self.assertEqual(
                    raw_snaps_scc["before"],
                    result_payload["xray_structure_invariance"]["snapshots"][
                        "before"
                    ],
                )
                self.assertEqual(raw_snaps_scc["before"]["n_scatterers"], 1)
                self.assertEqual(
                    raw_snaps_scc["after_model"]["n_scatterers"], 2
                )
                self.assertEqual(
                    len(raw_snaps_scc["after_model"]["records"]), 2
                )
                self.assertEqual(
                    raw_snaps_scc["after_fmodel"]["n_scatterers"], 2
                )
                self.assertEqual(
                    len(raw_snaps_scc["after_fmodel"]["records"]), 2
                )
                self.assertEqual(
                    partial_scc_doc["completed_stages"],
                    [
                        "extract_xtal_data",
                        "xray_structure_snapshot_before",
                        "xray_structure_snapshot_after_model",
                        "xray_structure_snapshot_after_fmodel",
                    ],
                )
                with self.assertRaisesRegex(
                    ValueError,
                    "Partial/unverified PHENIX evidence artifact cannot be reconciled",
                ):
                    onesar_rerun.reconcile_phenix_rfactor_output(
                        partial_scc_doc,
                        ledger,
                        expected_vendor_source_sha256=vendor_shas,
                        expected_resolved_prefix=resolved_fake_prefix,
                    )

            # 3a2. Scatterer occupancy change during scaling retains structured raw snapshots
            # in xray_structure_snapshots_raw while leaving verified invariance None (#1014, Task 120):
            with self.subTest(case="3a2_scatterer_occupancy_change"):
                out_json_soc = tmp_dir / "rfactors_soc.json"
                out_partial_soc = (
                    tmp_dir / "rfactors_soc_partial_evidence.json"
                )
                out_diag_soc = tmp_dir / "diagnostics_soc.json"
                with (
                    mock.patch.dict(
                        sys.modules,
                        _make_vendor_modules(
                            mutate_scatterer_occupancy_in_scales=True
                        ),
                    ),
                    mock.patch.object(
                        onesar_phenix_measure,
                        "_inspect_vendor_modules",
                        return_value=fake_runtime_env,
                    ),
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        "Scatterer snapshot mutated during scaling",
                    ):
                        onesar_phenix_measure.measure_first_block_rfactors(
                            pdb_path=pdb_path,
                            mtz_path=mtz_path,
                            params_path=params_path,
                            out_json_path=out_json_soc,
                            out_maps_mtz_path=tmp_dir / "soc_maps.mtz",
                            out_obs_pair_mtz_path=tmp_dir / "soc_pair.mtz",
                            out_diagnostics_json_path=out_diag_soc,
                        )
                self.assertFalse(out_json_soc.is_file())
                self.assertTrue(out_partial_soc.is_file())
                partial_soc_doc = json.loads(
                    out_partial_soc.read_text(encoding="utf-8")
                )
                self.assertIsNone(partial_soc_doc["xray_structure_invariance"])
                raw_snaps_soc = partial_soc_doc["xray_structure_snapshots_raw"]
                self.assertFalse(raw_snaps_soc["invariance_verified"])
                self.assertEqual(
                    raw_snaps_soc["before"]["records"][0]["occupancy"], 1.0
                )
                self.assertEqual(
                    raw_snaps_soc["after_model"]["records"][0]["occupancy"],
                    0.5,
                )
                self.assertEqual(
                    raw_snaps_soc["after_fmodel"]["records"][0]["occupancy"],
                    0.5,
                )
                with self.assertRaisesRegex(
                    ValueError,
                    "Partial/unverified PHENIX evidence artifact cannot be reconciled",
                ):
                    onesar_rerun.reconcile_phenix_rfactor_output(
                        partial_soc_doc,
                        ledger,
                        expected_vendor_source_sha256=vendor_shas,
                        expected_resolved_prefix=resolved_fake_prefix,
                    )

            # 3a2b. Non-finite post-scaling occupancy retains all captured scatterer records
            # and exact IEEE-754 bits in xray_structure_snapshots_raw["after_model"] before
            # snapshot_scatterer_records raises ValueError (#1014, Task 128):
            with self.subTest(
                case="3a2b_scatterer_nonfinite_occupancy_after_scales"
            ):
                out_json_snfo = tmp_dir / "rfactors_snfo.json"
                out_partial_snfo = (
                    tmp_dir / "rfactors_snfo_partial_evidence.json"
                )
                out_diag_snfo = tmp_dir / "diagnostics_snfo.json"
                snfo_nan_val = struct.unpack(
                    ">d", struct.pack(">Q", 0x7FF8000000000123)
                )[0]
                with (
                    mock.patch.dict(
                        sys.modules,
                        _make_vendor_modules(
                            nonfinite_scatterer_occupancy_in_scales=snfo_nan_val
                        ),
                    ),
                    mock.patch.object(
                        onesar_phenix_measure,
                        "_inspect_vendor_modules",
                        return_value=fake_runtime_env,
                    ),
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        "Invalid scatterer record at index 0",
                    ):
                        onesar_phenix_measure.measure_first_block_rfactors(
                            pdb_path=pdb_path,
                            mtz_path=mtz_path,
                            params_path=params_path,
                            out_json_path=out_json_snfo,
                            out_maps_mtz_path=tmp_dir / "snfo_maps.mtz",
                            out_obs_pair_mtz_path=tmp_dir / "snfo_pair.mtz",
                            out_diagnostics_json_path=out_diag_snfo,
                        )
                self.assertFalse(out_json_snfo.is_file())
                self.assertTrue(out_partial_snfo.is_file())
                partial_snfo_doc = json.loads(
                    out_partial_snfo.read_text(encoding="utf-8"),
                    parse_constant=lambda tok: (_ for _ in ()).throw(
                        ValueError(f"Forbidden non-strict JSON constant: {tok}")
                    ),
                )
                self.assertEqual(
                    partial_snfo_doc["status"], "failed_partial_unverified"
                )
                self.assertIsNone(partial_snfo_doc["xray_structure_invariance"])
                raw_snaps_snfo = partial_snfo_doc[
                    "xray_structure_snapshots_raw"
                ]
                self.assertFalse(raw_snaps_snfo["invariance_verified"])
                self.assertEqual(
                    raw_snaps_snfo["before"]["n_scatterers"], 1
                )
                self.assertIsNotNone(raw_snaps_snfo["before"]["sha256"])
                after_model_snfo = raw_snaps_snfo["after_model"]
                self.assertIsNotNone(after_model_snfo)
                self.assertEqual(after_model_snfo["n_scatterers"], 1)
                self.assertIsNone(after_model_snfo["sha256"])
                self.assertEqual(len(after_model_snfo["records"]), 1)
                snfo_rec0 = after_model_snfo["records"][0]
                self.assertEqual(snfo_rec0["label"], 'PDB=" N   VAL A   1 "')
                self.assertEqual(snfo_rec0["scattering_type"], "N")
                self.assertEqual(snfo_rec0["site_frac"], [0.1, 0.2, 0.3])
                self.assertEqual(
                    snfo_rec0["site_cart"], [6.4897, 15.6646, 11.6376]
                )
                self.assertEqual(snfo_rec0["u_iso"], 0.25)
                occ_tag = snfo_rec0["occupancy"]
                self.assertIsInstance(occ_tag, dict)
                self.assertTrue(occ_tag["__nonfinite_ieee754_float64__"])
                self.assertEqual(occ_tag["kind"], "nan")
                self.assertEqual(
                    occ_tag["ieee754_binary64_hex"], "0x7ff8000000000123"
                )
                self.assertEqual(occ_tag["sign_bit"], 0)
                self.assertEqual(
                    occ_tag["field_path"],
                    "xray_structure_snapshots_raw.after_model.records[0].occupancy",
                )
                self.assertIsNone(raw_snaps_snfo["after_fmodel"])
                self.assertEqual(
                    partial_snfo_doc["completed_stages"],
                    ["extract_xtal_data", "xray_structure_snapshot_before"],
                )
                self.assertEqual(
                    [
                        item["field_path"]
                        for item in partial_snfo_doc["nonfinite_raw_values"]
                    ],
                    [
                        "xray_structure_snapshots_raw.after_model.records[0].occupancy"
                    ],
                )
                with self.assertRaisesRegex(
                    ValueError,
                    "Partial/unverified PHENIX evidence artifact cannot be reconciled",
                ):
                    onesar_rerun.reconcile_phenix_rfactor_output(
                        partial_snfo_doc,
                        ledger,
                        expected_vendor_source_sha256=vendor_shas,
                        expected_resolved_prefix=resolved_fake_prefix,
                    )

            # 3a2c. Non-finite post-scaling isotropic ADP (u_iso) retains all captured scatterer
            # records and exact IEEE-754 bits in xray_structure_snapshots_raw["after_model"] (#1014, Task 128):
            with self.subTest(case="3a2c_scatterer_nonfinite_adp_after_scales"):
                out_json_snfu = tmp_dir / "rfactors_snfu.json"
                out_partial_snfu = (
                    tmp_dir / "rfactors_snfu_partial_evidence.json"
                )
                out_diag_snfu = tmp_dir / "diagnostics_snfu.json"
                snfu_nan_val = struct.unpack(
                    ">d", struct.pack(">Q", 0xFFF8000000000456)
                )[0]
                with (
                    mock.patch.dict(
                        sys.modules,
                        _make_vendor_modules(
                            nonfinite_scatterer_u_iso_in_scales=snfu_nan_val
                        ),
                    ),
                    mock.patch.object(
                        onesar_phenix_measure,
                        "_inspect_vendor_modules",
                        return_value=fake_runtime_env,
                    ),
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        "Invalid scatterer record at index 0",
                    ):
                        onesar_phenix_measure.measure_first_block_rfactors(
                            pdb_path=pdb_path,
                            mtz_path=mtz_path,
                            params_path=params_path,
                            out_json_path=out_json_snfu,
                            out_maps_mtz_path=tmp_dir / "snfu_maps.mtz",
                            out_obs_pair_mtz_path=tmp_dir / "snfu_pair.mtz",
                            out_diagnostics_json_path=out_diag_snfu,
                        )
                self.assertFalse(out_json_snfu.is_file())
                self.assertTrue(out_partial_snfu.is_file())
                partial_snfu_doc = json.loads(
                    out_partial_snfu.read_text(encoding="utf-8"),
                    parse_constant=lambda tok: (_ for _ in ()).throw(
                        ValueError(f"Forbidden non-strict JSON constant: {tok}")
                    ),
                )
                self.assertIsNone(partial_snfu_doc["xray_structure_invariance"])
                raw_snaps_snfu = partial_snfu_doc[
                    "xray_structure_snapshots_raw"
                ]
                self.assertFalse(raw_snaps_snfu["invariance_verified"])
                after_model_snfu = raw_snaps_snfu["after_model"]
                self.assertIsNotNone(after_model_snfu)
                self.assertEqual(after_model_snfu["n_scatterers"], 1)
                self.assertIsNone(after_model_snfu["sha256"])
                self.assertEqual(
                    after_model_snfu["records"][0]["occupancy"], 1.0
                )
                uiso_tag = after_model_snfu["records"][0]["u_iso"]
                self.assertIsInstance(uiso_tag, dict)
                self.assertTrue(uiso_tag["__nonfinite_ieee754_float64__"])
                self.assertEqual(uiso_tag["kind"], "nan")
                self.assertEqual(
                    uiso_tag["ieee754_binary64_hex"], "0xfff8000000000456"
                )
                self.assertEqual(uiso_tag["sign_bit"], 1)
                self.assertEqual(
                    uiso_tag["field_path"],
                    "xray_structure_snapshots_raw.after_model.records[0].u_iso",
                )
                self.assertIsNone(raw_snaps_snfu["after_fmodel"])
                self.assertEqual(
                    partial_snfu_doc["completed_stages"],
                    ["extract_xtal_data", "xray_structure_snapshot_before"],
                )
                self.assertEqual(
                    [
                        item["field_path"]
                        for item in partial_snfu_doc["nonfinite_raw_values"]
                    ],
                    [
                        "xray_structure_snapshots_raw.after_model.records[0].u_iso"
                    ],
                )
                with self.assertRaisesRegex(
                    ValueError,
                    "Partial/unverified PHENIX evidence artifact cannot be reconciled",
                ):
                    onesar_rerun.reconcile_phenix_rfactor_output(
                        partial_snfu_doc,
                        ledger,
                        expected_vendor_source_sha256=vendor_shas,
                        expected_resolved_prefix=resolved_fake_prefix,
                    )

            # 3a2d. Post-scaling zero scatterer population retains n_scatterers=0 and records=[]
            # in xray_structure_snapshots_raw["after_model"] before failing closed (#1014, Task 128):
            with self.subTest(
                case="3a2d_scatterer_empty_population_after_scales"
            ):
                out_json_semp = tmp_dir / "rfactors_semp.json"
                out_partial_semp = (
                    tmp_dir / "rfactors_semp_partial_evidence.json"
                )
                out_diag_semp = tmp_dir / "diagnostics_semp.json"
                with (
                    mock.patch.dict(
                        sys.modules,
                        _make_vendor_modules(empty_scatterers_in_scales=True),
                    ),
                    mock.patch.object(
                        onesar_phenix_measure,
                        "_inspect_vendor_modules",
                        return_value=fake_runtime_env,
                    ),
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        "Scatterer snapshot cannot be empty",
                    ):
                        onesar_phenix_measure.measure_first_block_rfactors(
                            pdb_path=pdb_path,
                            mtz_path=mtz_path,
                            params_path=params_path,
                            out_json_path=out_json_semp,
                            out_maps_mtz_path=tmp_dir / "semp_maps.mtz",
                            out_obs_pair_mtz_path=tmp_dir / "semp_pair.mtz",
                            out_diagnostics_json_path=out_diag_semp,
                        )
                self.assertFalse(out_json_semp.is_file())
                self.assertTrue(out_partial_semp.is_file())
                partial_semp_doc = json.loads(
                    out_partial_semp.read_text(encoding="utf-8")
                )
                self.assertIsNone(partial_semp_doc["xray_structure_invariance"])
                raw_snaps_semp = partial_semp_doc[
                    "xray_structure_snapshots_raw"
                ]
                self.assertFalse(raw_snaps_semp["invariance_verified"])
                self.assertEqual(
                    raw_snaps_semp["before"]["n_scatterers"], 1
                )
                self.assertEqual(
                    raw_snaps_semp["after_model"],
                    {"n_scatterers": 0, "sha256": None, "records": []},
                )
                self.assertIsNone(raw_snaps_semp["after_fmodel"])
                self.assertEqual(
                    partial_semp_doc["completed_stages"],
                    ["extract_xtal_data", "xray_structure_snapshot_before"],
                )
                self.assertEqual(partial_semp_doc["nonfinite_raw_values"], [])
                with self.assertRaisesRegex(
                    ValueError,
                    "Partial/unverified PHENIX evidence artifact cannot be reconciled",
                ):
                    onesar_rerun.reconcile_phenix_rfactor_output(
                        partial_semp_doc,
                        ledger,
                        expected_vendor_source_sha256=vendor_shas,
                        expected_resolved_prefix=resolved_fake_prefix,
                    )

            # 3a2e. Worker fails closed when runtime crystal_symmetry is missing or has
            # inconsistent space_group_number / symmetry operators (#1025, Task 128):
            missing_sg_symm = types.SimpleNamespace(
                unit_cell=lambda: types.SimpleNamespace(
                    parameters=lambda: _fake_f32_cell
                ),
                space_group_info=lambda: types.SimpleNamespace(
                    symbol_and_number=lambda: "P 21 21 21 (No. 19)",
                ),
                is_similar_symmetry=lambda other: True,
            )
            mismatch_num_symm = types.SimpleNamespace(
                unit_cell=lambda: types.SimpleNamespace(
                    parameters=lambda: _fake_f32_cell
                ),
                space_group=lambda: types.SimpleNamespace(
                    type=lambda: types.SimpleNamespace(number=lambda: 19),
                    all_ops=lambda: list(_fake_rt_mx_ops),
                ),
                space_group_info=lambda: types.SimpleNamespace(
                    symbol_and_number=lambda: "P 21 21 21 (No. 19)",
                    type=lambda: types.SimpleNamespace(number=lambda: 18),
                ),
                is_similar_symmetry=lambda other: True,
            )
            empty_ops_symm = types.SimpleNamespace(
                unit_cell=lambda: types.SimpleNamespace(
                    parameters=lambda: _fake_f32_cell
                ),
                space_group=lambda: types.SimpleNamespace(
                    type=lambda: types.SimpleNamespace(number=lambda: 19),
                    all_ops=lambda: [],
                ),
                space_group_info=lambda: types.SimpleNamespace(
                    symbol_and_number=lambda: "P 21 21 21 (No. 19)",
                    type=lambda: types.SimpleNamespace(number=lambda: 19),
                ),
                is_similar_symmetry=lambda other: True,
            )
            for idx_sym, (sym_case_name, bad_sym_obj, bad_sym_pat) in enumerate(
                (
                    (
                        "missing_space_group",
                        missing_sg_symm,
                        r"is missing space_group\(\)",
                    ),
                    (
                        "mismatched_group_and_info_number",
                        mismatch_num_symm,
                        r"space_group_info\(\)\.type\(\)\.number\(\) 18 disagrees with space_group\(\)\.type\(\)\.number\(\) 19",
                    ),
                    (
                        "empty_all_ops",
                        empty_ops_symm,
                        r"space_group\(\)\.all_ops\(\) returned no symmetry operations",
                    ),
                )
            ):
                with self.subTest(
                    case=f"3a2e_worker_symmetry_{sym_case_name}"
                ):
                    out_json_sym = (
                        tmp_dir / f"rfactors_symm_bad_{idx_sym}.json"
                    )
                    out_partial_sym = (
                        tmp_dir
                        / f"rfactors_symm_bad_{idx_sym}_partial_evidence.json"
                    )
                    out_maps_sym = (
                        tmp_dir / f"symm_bad_{idx_sym}_maps.mtz"
                    )
                    out_pair_sym = (
                        tmp_dir / f"symm_bad_{idx_sym}_pair.mtz"
                    )
                    out_diag_sym = (
                        tmp_dir / f"diag_symm_bad_{idx_sym}.json"
                    )
                    with (
                        mock.patch.dict(
                            sys.modules,
                            _make_vendor_modules(symmetry_override=bad_sym_obj),
                        ),
                        mock.patch.object(
                            onesar_phenix_measure,
                            "_inspect_vendor_modules",
                            return_value=fake_runtime_env,
                        ),
                    ):
                        with self.assertRaisesRegex(RuntimeError, bad_sym_pat):
                            onesar_phenix_measure.measure_first_block_rfactors(
                                pdb_path=pdb_path,
                                mtz_path=mtz_path,
                                params_path=params_path,
                                out_json_path=out_json_sym,
                                out_maps_mtz_path=out_maps_sym,
                                out_obs_pair_mtz_path=out_pair_sym,
                                out_diagnostics_json_path=out_diag_sym,
                            )
                    self.assertFalse(out_json_sym.is_file())
                    self.assertFalse(out_maps_sym.is_file())
                    self.assertFalse(out_pair_sym.is_file())
                    self.assertTrue(out_partial_sym.is_file())
                    self.assertTrue(out_diag_sym.is_file())
                    partial_sym_doc = json.loads(
                        out_partial_sym.read_text(encoding="utf-8")
                    )
                    diag_sym_doc = json.loads(
                        out_diag_sym.read_text(encoding="utf-8")
                    )
                    self.assertEqual(
                        partial_sym_doc["status"], "failed_partial_unverified"
                    )
                    self.assertEqual(
                        partial_sym_doc["failure"]["failed_phase"], "pdb_input"
                    )
                    self.assertEqual(
                        partial_sym_doc["failure"]["exception_type"],
                        "RuntimeError",
                    )
                    self.assertRegex(
                        partial_sym_doc["failure"]["exception_message"],
                        bad_sym_pat,
                    )
                    self.assertEqual(diag_sym_doc["status"], "failed")
                    self.assertEqual(
                        diag_sym_doc["current_phase"], "pdb_input"
                    )
                    self.assertEqual(
                        diag_sym_doc["partial_evidence_status"],
                        "failed_partial_unverified",
                    )
                    self.assertEqual(
                        diag_sym_doc["failure"]["exception_type"],
                        "RuntimeError",
                    )
                    self.assertRegex(
                        diag_sym_doc["failure"]["exception_message"],
                        bad_sym_pat,
                    )
                    with self.assertRaisesRegex(
                        ValueError,
                        "Partial/unverified PHENIX evidence artifact cannot be reconciled",
                    ):
                        onesar_rerun.reconcile_phenix_rfactor_output(
                            partial_sym_doc,
                            ledger,
                            expected_vendor_source_sha256=vendor_shas,
                            expected_resolved_prefix=resolved_fake_prefix,
                        )

            # 3a3. Non-finite model coefficient fails in compute_rfactor_from_arrays after
            # checkpointing final_effective, actual_work, and actual_free with strict-JSON
            # IEEE-754 nonfinite tags (#1014, Task 120):
            with self.subTest(case="3a3_nonfinite_work_model_coefficient"):
                out_json_nf = tmp_dir / "rfactors_nonfinite.json"
                out_partial_nf = (
                    tmp_dir / "rfactors_nonfinite_partial_evidence.json"
                )
                out_diag_nf = tmp_dir / "diagnostics_nonfinite.json"
                with (
                    mock.patch.dict(
                        sys.modules,
                        _make_vendor_modules(nonfinite_work_model_coeff=True),
                    ),
                    mock.patch.object(
                        onesar_phenix_measure,
                        "_inspect_vendor_modules",
                        return_value=fake_runtime_env,
                    ),
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        r"Non-finite amplitude at index 0: fo=100\.0, fm=nan",
                    ):
                        onesar_phenix_measure.measure_first_block_rfactors(
                            pdb_path=pdb_path,
                            mtz_path=mtz_path,
                            params_path=params_path,
                            out_json_path=out_json_nf,
                            out_maps_mtz_path=tmp_dir / "nf_maps.mtz",
                            out_obs_pair_mtz_path=tmp_dir / "nf_pair.mtz",
                            out_diagnostics_json_path=out_diag_nf,
                        )
                self.assertFalse(out_json_nf.is_file())
                self.assertTrue(out_partial_nf.is_file())
                # Verify strict RFC 8259 JSON compliance (no bare NaN/Infinity tokens):
                partial_nf_doc = json.loads(
                    out_partial_nf.read_text(encoding="utf-8"),
                    parse_constant=lambda tok: (_ for _ in ()).throw(
                        ValueError(f"Forbidden non-strict JSON constant: {tok}")
                    ),
                )
                self.assertEqual(
                    partial_nf_doc["status"], "failed_partial_unverified"
                )
                self.assertFalse(partial_nf_doc["rfactor_replay_verified"])
                self.assertIsNone(partial_nf_doc["scales_and_rfactors"])
                self.assertIsNone(partial_nf_doc["rfactor_replay_comparison"])
                self.assertEqual(
                    partial_nf_doc["extracted_pre_fmodel"],
                    result_payload["extracted_pre_fmodel"],
                )
                self.assertEqual(
                    partial_nf_doc["final_effective"],
                    result_payload["final_effective"],
                )
                self.assertEqual(
                    partial_nf_doc["actual_free"],
                    result_payload["actual_free"],
                )
                self.assertEqual(len(partial_nf_doc["actual_work"]), 2)
                self.assertEqual(
                    partial_nf_doc["actual_work"][1],
                    result_payload["actual_work"][1],
                )
                nf_row0 = partial_nf_doc["actual_work"][0]
                self.assertEqual(nf_row0["hkl"], [1, 0, 0])
                self.assertEqual(nf_row0["f_obs"], 100.0)
                self.assertEqual(nf_row0["sigf_obs"], 2.0)
                self.assertEqual(nf_row0["f_model_imag"], 144.0)
                self.assertEqual(
                    nf_row0["f_model_scaled_with_k1_w_imag"], 72.0
                )
                expected_nf_fields = [
                    "f_model_real",
                    "f_model_amplitude",
                    "f_model_scaled_with_k1_w_real",
                    "f_model_scaled_with_k1_w_amplitude",
                ]
                for nf_field in expected_nf_fields:
                    tag_obj = nf_row0[nf_field]
                    self.assertIsInstance(tag_obj, dict)
                    self.assertTrue(tag_obj["__nonfinite_ieee754_float64__"])
                    self.assertEqual(tag_obj["kind"], "nan")
                    self.assertEqual(tag_obj["repr"], "nan")
                    self.assertEqual(
                        tag_obj["field_path"], f"actual_work[0].{nf_field}"
                    )
                    self.assertTrue(
                        tag_obj["ieee754_binary64_hex"].startswith("0x")
                    )
                self.assertEqual(
                    [
                        item["field_path"]
                        for item in partial_nf_doc["nonfinite_raw_values"]
                    ],
                    [f"actual_work[0].{f}" for f in expected_nf_fields],
                )
                self.assertIn(
                    "final_effective_raw", partial_nf_doc["completed_stages"]
                )
                self.assertIn(
                    "actual_work_raw", partial_nf_doc["completed_stages"]
                )
                self.assertIn(
                    "actual_free_raw", partial_nf_doc["completed_stages"]
                )
                self.assertNotIn(
                    "rfactor_raw_arrays_and_scalars",
                    partial_nf_doc["completed_stages"],
                )
                with self.assertRaisesRegex(
                    ValueError,
                    "Partial/unverified PHENIX evidence artifact cannot be reconciled",
                ):
                    onesar_rerun.reconcile_phenix_rfactor_output(
                        partial_nf_doc,
                        ledger,
                        expected_vendor_source_sha256=vendor_shas,
                        expected_resolved_prefix=resolved_fake_prefix,
                    )

            # 3a4. Non-positive observation (fo=0.0) fails in compute_rfactor_from_arrays
            # while retaining completed final_effective, actual_work, and actual_free (#1014, Task 120):
            with self.subTest(case="3a4_nonpositive_final_observation"):
                out_json_np = tmp_dir / "rfactors_nonpos.json"
                out_partial_np = (
                    tmp_dir / "rfactors_nonpos_partial_evidence.json"
                )
                out_diag_np = tmp_dir / "diagnostics_nonpos.json"
                with (
                    mock.patch.dict(
                        sys.modules,
                        _make_vendor_modules(nonpositive_final_obs=True),
                    ),
                    mock.patch.object(
                        onesar_phenix_measure,
                        "_inspect_vendor_modules",
                        return_value=fake_runtime_env,
                    ),
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        r"Invalid amplitude sign at index 0: fo=0\.0, fm=90\.0",
                    ):
                        onesar_phenix_measure.measure_first_block_rfactors(
                            pdb_path=pdb_path,
                            mtz_path=mtz_path,
                            params_path=params_path,
                            out_json_path=out_json_np,
                            out_maps_mtz_path=tmp_dir / "np_maps.mtz",
                            out_obs_pair_mtz_path=tmp_dir / "np_pair.mtz",
                            out_diagnostics_json_path=out_diag_np,
                        )
                self.assertFalse(out_json_np.is_file())
                self.assertTrue(out_partial_np.is_file())
                partial_np_doc = json.loads(
                    out_partial_np.read_text(encoding="utf-8")
                )
                self.assertFalse(partial_np_doc["rfactor_replay_verified"])
                self.assertIsNone(partial_np_doc["scales_and_rfactors"])
                self.assertIsNone(partial_np_doc["rfactor_replay_comparison"])
                self.assertEqual(partial_np_doc["nonfinite_raw_values"], [])
                self.assertEqual(len(partial_np_doc["final_effective"]), 4)
                self.assertEqual(
                    partial_np_doc["final_effective"][0]["f_obs"], 0.0
                )
                self.assertEqual(
                    partial_np_doc["final_effective"][1:],
                    result_payload["final_effective"][1:],
                )
                self.assertEqual(len(partial_np_doc["actual_work"]), 2)
                self.assertEqual(
                    partial_np_doc["actual_work"][0]["f_obs"], 0.0
                )
                self.assertEqual(
                    partial_np_doc["actual_work"][1],
                    result_payload["actual_work"][1],
                )
                self.assertEqual(
                    partial_np_doc["actual_free"],
                    result_payload["actual_free"],
                )
                with self.assertRaisesRegex(
                    ValueError,
                    "Partial/unverified PHENIX evidence artifact cannot be reconciled",
                ):
                    onesar_rerun.reconcile_phenix_rfactor_output(
                        partial_np_doc,
                        ledger,
                        expected_vendor_source_sha256=vendor_shas,
                        expected_resolved_prefix=resolved_fake_prefix,
                    )

            # 3a5. Failure while constructing actual_free preserves already completed
            # final_effective and actual_work arrays (#1014, Task 120):
            with self.subTest(
                case="3a5_later_free_array_failure_preserves_final_and_work"
            ):
                out_json_ffail = tmp_dir / "rfactors_freefail.json"
                out_partial_ffail = (
                    tmp_dir / "rfactors_freefail_partial_evidence.json"
                )
                out_diag_ffail = tmp_dir / "diagnostics_freefail.json"
                with (
                    mock.patch.dict(
                        sys.modules,
                        _make_vendor_modules(fail_in_free_array=True),
                    ),
                    mock.patch.object(
                        onesar_phenix_measure,
                        "_inspect_vendor_modules",
                        return_value=fake_runtime_env,
                    ),
                ):
                    with self.assertRaisesRegex(
                        RuntimeError, "Injected synthetic f_obs_free failure"
                    ):
                        onesar_phenix_measure.measure_first_block_rfactors(
                            pdb_path=pdb_path,
                            mtz_path=mtz_path,
                            params_path=params_path,
                            out_json_path=out_json_ffail,
                            out_maps_mtz_path=tmp_dir / "ffail_maps.mtz",
                            out_obs_pair_mtz_path=tmp_dir / "ffail_pair.mtz",
                            out_diagnostics_json_path=out_diag_ffail,
                        )
                self.assertFalse(out_json_ffail.is_file())
                self.assertTrue(out_partial_ffail.is_file())
                partial_ffail_doc = json.loads(
                    out_partial_ffail.read_text(encoding="utf-8")
                )
                self.assertEqual(
                    partial_ffail_doc["final_effective"],
                    result_payload["final_effective"],
                )
                self.assertEqual(
                    partial_ffail_doc["actual_work"],
                    result_payload["actual_work"],
                )
                self.assertIsNone(partial_ffail_doc["actual_free"])

            # 3b. Deliberate native r_work mismatch fails before success output is written,
            # while partial_evidence JSON on disk retains extracted/final/work/free HKLs,
            # observations, complex model coefficients, scatterers, and both native and
            # replayed scalar R values (#1014 Finding 4, #1017):
            with self.subTest(case="3b_native_r_work_mismatch"):
                out_json_rmis = tmp_dir / "rfactors_rmismatch.json"
                out_partial_rmis = (
                    tmp_dir / "rfactors_rmismatch_partial_evidence.json"
                )
                out_diag_rmis = tmp_dir / "diagnostics_rmismatch.json"
                with (
                    mock.patch.dict(
                        sys.modules,
                        _make_vendor_modules(
                            native_r_work_override=(20.0 / 300.0 + 0.01)
                        ),
                    ),
                    mock.patch.object(
                        onesar_phenix_measure,
                        "_inspect_vendor_modules",
                        return_value=fake_runtime_env,
                    ),
                ):
                    with self.assertRaisesRegex(
                        RuntimeError,
                        r"Native fmodel\.r_work\(\) .* disagrees with array replay",
                    ):
                        onesar_phenix_measure.measure_first_block_rfactors(
                            pdb_path=pdb_path,
                            mtz_path=mtz_path,
                            params_path=params_path,
                            out_json_path=out_json_rmis,
                            out_maps_mtz_path=tmp_dir / "rmismatch_maps.mtz",
                            out_obs_pair_mtz_path=tmp_dir
                            / "rmismatch_pair.mtz",
                            out_diagnostics_json_path=out_diag_rmis,
                        )
                self.assertFalse(out_json_rmis.is_file())
                self.assertTrue(out_partial_rmis.is_file())
                partial_rmis_doc = json.loads(
                    out_partial_rmis.read_text(encoding="utf-8")
                )
                self.assertEqual(
                    partial_rmis_doc["artifact_role"],
                    "partial_unverified_phenix_evidence",
                )
                self.assertFalse(partial_rmis_doc["reusable_cache_output"])
                self.assertFalse(
                    partial_rmis_doc["canonical_eval_qds_eligible"]
                )
                self.assertEqual(
                    partial_rmis_doc["status"], "failed_partial_unverified"
                )
                self.assertFalse(partial_rmis_doc["rfactor_replay_verified"])
                self.assertEqual(
                    partial_rmis_doc["extracted_pre_fmodel"],
                    result_payload["extracted_pre_fmodel"],
                )
                self.assertEqual(
                    partial_rmis_doc["final_effective"],
                    result_payload["final_effective"],
                )
                self.assertEqual(
                    partial_rmis_doc["actual_work"],
                    result_payload["actual_work"],
                )
                self.assertEqual(
                    partial_rmis_doc["actual_free"],
                    result_payload["actual_free"],
                )
                self.assertEqual(
                    partial_rmis_doc["xray_structure_invariance"],
                    result_payload["xray_structure_invariance"],
                )
                self.assertAlmostEqual(
                    partial_rmis_doc["scales_and_rfactors"]["r_work"],
                    20.0 / 300.0 + 0.01,
                    places=12,
                )
                self.assertAlmostEqual(
                    partial_rmis_doc["scales_and_rfactors"]["replayed_r_work"],
                    20.0 / 300.0,
                    places=12,
                )
                self.assertAlmostEqual(
                    partial_rmis_doc["rfactor_replay_comparison"][
                        "r_work_abs_diff"
                    ],
                    0.01,
                    places=12,
                )
                self.assertIsNone(partial_rmis_doc["map_coefficients"])
                with self.assertRaisesRegex(
                    ValueError,
                    "Partial/unverified PHENIX evidence artifact cannot be reconciled",
                ):
                    onesar_rerun.reconcile_phenix_rfactor_output(
                        partial_rmis_doc,
                        ledger,
                        expected_vendor_source_sha256=vendor_shas,
                        expected_resolved_prefix=resolved_fake_prefix,
                    )

            # 3c. Failure during map MTZ serialization/writing retains completed R-factor
            # arrays AND already-obtained complex map_coefficients without writing out_json (#1014 Finding 4, #1017):
            with self.subTest(case="3c_map_mtz_write_failure"):
                out_json_mfail = tmp_dir / "rfactors_mapwrite_fail.json"
                out_partial_mfail = (
                    tmp_dir / "rfactors_mapwrite_fail_partial_evidence.json"
                )
                out_diag_mfail = tmp_dir / "diagnostics_mapwrite_fail.json"
                with (
                    mock.patch.dict(
                        sys.modules,
                        _make_vendor_modules(fail_in_map_write=True),
                    ),
                    mock.patch.object(
                        onesar_phenix_measure,
                        "_inspect_vendor_modules",
                        return_value=fake_runtime_env,
                    ),
                ):
                    with self.assertRaisesRegex(
                        RuntimeError, "Injected synthetic map write failure"
                    ):
                        onesar_phenix_measure.measure_first_block_rfactors(
                            pdb_path=pdb_path,
                            mtz_path=mtz_path,
                            params_path=params_path,
                            out_json_path=out_json_mfail,
                            out_maps_mtz_path=tmp_dir / "mapwrite_fail_maps.mtz",
                            out_obs_pair_mtz_path=tmp_dir
                            / "mapwrite_fail_pair.mtz",
                            out_diagnostics_json_path=out_diag_mfail,
                        )
                self.assertFalse(out_json_mfail.is_file())
                self.assertTrue(out_partial_mfail.is_file())
                partial_mfail_doc = json.loads(
                    out_partial_mfail.read_text(encoding="utf-8")
                )
                self.assertEqual(
                    partial_mfail_doc["status"], "failed_partial_unverified"
                )
                self.assertTrue(partial_mfail_doc["rfactor_replay_verified"])
                self.assertFalse(partial_mfail_doc["map_export_verified"])
                self.assertEqual(
                    partial_mfail_doc["actual_work"],
                    result_payload["actual_work"],
                )
                self.assertEqual(
                    partial_mfail_doc["actual_free"],
                    result_payload["actual_free"],
                )
                self.assertEqual(
                    partial_mfail_doc["map_coefficients"]["2mFo-DFc"],
                    result_payload["map_coefficients"]["2mFo-DFc"],
                )
                self.assertEqual(
                    partial_mfail_doc["map_coefficients"]["mFo-DFc"],
                    result_payload["map_coefficients"]["mFo-DFc"],
                )
                self.assertIsNone(
                    partial_mfail_doc["map_coefficients"]["mtz_supplements"]
                )
                self.assertNotIn("mtz_supplements", partial_mfail_doc)

            # 3d. Failure inside fmodel.map_coefficients retains completed R-factor arrays
            # without fabricating map_coefficients (#1014 Finding 4, #1017):
            with self.subTest(case="3d_map_coefficients_failure"):
                out_json_mcfail = tmp_dir / "rfactors_mapcoeff_fail.json"
                out_partial_mcfail = (
                    tmp_dir / "rfactors_mapcoeff_fail_partial_evidence.json"
                )
                out_diag_mcfail = tmp_dir / "diagnostics_mapcoeff_fail.json"
                with (
                    mock.patch.dict(
                        sys.modules,
                        _make_vendor_modules(fail_in_map_coefficients=True),
                    ),
                    mock.patch.object(
                        onesar_phenix_measure,
                        "_inspect_vendor_modules",
                        return_value=fake_runtime_env,
                    ),
                ):
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "Injected synthetic map_coefficients failure",
                    ):
                        onesar_phenix_measure.measure_first_block_rfactors(
                            pdb_path=pdb_path,
                            mtz_path=mtz_path,
                            params_path=params_path,
                            out_json_path=out_json_mcfail,
                            out_maps_mtz_path=tmp_dir
                            / "mapcoeff_fail_maps.mtz",
                            out_obs_pair_mtz_path=tmp_dir
                            / "mapcoeff_fail_pair.mtz",
                            out_diagnostics_json_path=out_diag_mcfail,
                        )
                self.assertFalse(out_json_mcfail.is_file())
                self.assertTrue(out_partial_mcfail.is_file())
                partial_mcfail_doc = json.loads(
                    out_partial_mcfail.read_text(encoding="utf-8")
                )
                self.assertTrue(partial_mcfail_doc["rfactor_replay_verified"])
                self.assertIsNone(partial_mcfail_doc["map_coefficients"])
                self.assertNotIn("mtz_supplements", partial_mcfail_doc)

            # 3d2. Failure on the second fmodel.map_coefficients("mFo-DFc") call retains
            # the already obtained/exported first map ("2mFo-DFc") and completed R-factor
            # arrays while leaving "mFo-DFc" and "mtz_supplements" None (#1014, Task 120):
            with self.subTest(case="3d2_second_map_coefficients_failure"):
                out_json_mc2fail = tmp_dir / "rfactors_mapcoeff2_fail.json"
                out_partial_mc2fail = (
                    tmp_dir / "rfactors_mapcoeff2_fail_partial_evidence.json"
                )
                out_diag_mc2fail = tmp_dir / "diagnostics_mapcoeff2_fail.json"
                out_maps_mc2fail = tmp_dir / "mapcoeff2_fail_maps.mtz"
                out_pair_mc2fail = tmp_dir / "mapcoeff2_fail_pair.mtz"
                with (
                    mock.patch.dict(
                        sys.modules,
                        _make_vendor_modules(
                            fail_in_second_map_coefficients=True
                        ),
                    ),
                    mock.patch.object(
                        onesar_phenix_measure,
                        "_inspect_vendor_modules",
                        return_value=fake_runtime_env,
                    ),
                ):
                    with self.assertRaisesRegex(
                        RuntimeError,
                        "Injected synthetic second-map coefficient failure",
                    ):
                        onesar_phenix_measure.measure_first_block_rfactors(
                            pdb_path=pdb_path,
                            mtz_path=mtz_path,
                            params_path=params_path,
                            out_json_path=out_json_mc2fail,
                            out_maps_mtz_path=out_maps_mc2fail,
                            out_obs_pair_mtz_path=out_pair_mc2fail,
                            out_diagnostics_json_path=out_diag_mc2fail,
                        )
                self.assertFalse(out_json_mc2fail.is_file())
                self.assertFalse(out_maps_mc2fail.is_file())
                self.assertFalse(out_pair_mc2fail.is_file())
                self.assertTrue(out_partial_mc2fail.is_file())
                partial_mc2fail_doc = json.loads(
                    out_partial_mc2fail.read_text(encoding="utf-8")
                )
                self.assertEqual(
                    partial_mc2fail_doc["status"], "failed_partial_unverified"
                )
                self.assertTrue(partial_mc2fail_doc["rfactor_replay_verified"])
                self.assertFalse(partial_mc2fail_doc["map_export_verified"])
                self.assertEqual(
                    partial_mc2fail_doc["extracted_pre_fmodel"],
                    result_payload["extracted_pre_fmodel"],
                )
                self.assertEqual(
                    partial_mc2fail_doc["final_effective"],
                    result_payload["final_effective"],
                )
                self.assertEqual(
                    partial_mc2fail_doc["actual_work"],
                    result_payload["actual_work"],
                )
                self.assertEqual(
                    partial_mc2fail_doc["actual_free"],
                    result_payload["actual_free"],
                )
                self.assertEqual(
                    partial_mc2fail_doc["map_coefficients"]["2mFo-DFc"],
                    result_payload["map_coefficients"]["2mFo-DFc"],
                )
                self.assertIsNone(
                    partial_mc2fail_doc["map_coefficients"]["mFo-DFc"]
                )
                self.assertIsNone(
                    partial_mc2fail_doc["map_coefficients"]["mtz_supplements"]
                )
                self.assertNotIn("mtz_supplements", partial_mc2fail_doc)
                self.assertIn(
                    "map_coefficients_2mfo_dfc_raw",
                    partial_mc2fail_doc["completed_stages"],
                )
                self.assertNotIn(
                    "map_coefficients_raw",
                    partial_mc2fail_doc["completed_stages"],
                )
                with self.assertRaisesRegex(
                    ValueError,
                    "Partial/unverified PHENIX evidence artifact cannot be reconciled",
                ):
                    onesar_rerun.reconcile_phenix_rfactor_output(
                        partial_mc2fail_doc,
                        ledger,
                        expected_vendor_source_sha256=vendor_shas,
                        expected_resolved_prefix=resolved_fake_prefix,
                    )

            # 4. Direct _inspect_vendor_modules check for inside/outside prefix (#1013):
            with self.subTest(case="4_inspect_vendor_modules_prefix"):
                fake_bin = fake_prefix / "bin"
                fake_bin.mkdir(parents=True, exist_ok=True)
                fake_py = fake_bin / "python3.9"
                fake_py.write_text("#!/bin/sh\n", encoding="utf-8")
                inside_mod_file = fake_prefix / "lib" / "mod_inside.py"
                inside_mod_file.parent.mkdir(parents=True, exist_ok=True)
                inside_mod_file.write_text("# inside\n", encoding="utf-8")
                outside_mod_file = tmp_dir / "mod_outside.py"
                outside_mod_file.write_text("# outside\n", encoding="utf-8")
                with (
                    mock.patch.object(sys, "prefix", resolved_fake_prefix),
                    mock.patch.object(sys, "executable", str(fake_py)),
                ):
                    inspected = onesar_phenix_measure._inspect_vendor_modules(
                        {
                            "vendor_test": types.SimpleNamespace(
                                __name__="vendor_test",
                                __file__=str(inside_mod_file),
                            )
                        },
                        expected_resolved_prefix=resolved_fake_prefix,
                    )
                    self.assertEqual(
                        inspected["resolved_sys_prefix"], resolved_fake_prefix
                    )
                    with self.assertRaisesRegex(
                        ValueError, "escapes sys.prefix"
                    ):
                        onesar_phenix_measure._inspect_vendor_modules(
                            {
                                "vendor_test": types.SimpleNamespace(
                                    __name__="vendor_test",
                                    __file__=str(outside_mod_file),
                                )
                            },
                            expected_resolved_prefix=resolved_fake_prefix,
                        )

    def _verify_atomic_checkpoint_interrupted_write_and_promotion(
        self, tmp_dir: Path
    ) -> None:
        """Verify mid-write partial bytes and failed promotion preserve prior JSON and unlink temp siblings."""
        atomic_target = tmp_dir / "atomic_checkpoint.json"
        prior_payload = {
            "status": "running",
            "current_phase": "extract_xtal_data",
            "phase_history": ["startup", "extract_xtal_data"],
            "extract_xtal_data_log": "complete prior log\n",
        }
        onesar_phenix_measure._checkpoint_diagnostics(
            prior_payload, atomic_target
        )
        prior_bytes = atomic_target.read_bytes()
        self.assertEqual(
            json.loads(atomic_target.read_text(encoding="utf-8")),
            prior_payload,
        )

        real_open_temp = onesar_phenix_measure._open_checkpoint_temp_file
        partial_temp_records: list[tuple[Path, bytes]] = []

        class _InterruptedTempFileWrapper:
            def __init__(self, tmp_path: Path) -> None:
                self._tmp_path = tmp_path
                self._fh = real_open_temp(tmp_path)

            def __enter__(self) -> "_InterruptedTempFileWrapper":
                self._fh.__enter__()
                return self

            def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Any:
                return self._fh.__exit__(exc_type, exc_val, exc_tb)

            def write(self, data: str) -> int:
                partial_chunk = data[:16]
                self._fh.write(partial_chunk)
                self._fh.flush()
                os.fsync(self._fh.fileno())
                partial_temp_records.append(
                    (self._tmp_path, self._tmp_path.read_bytes())
                )
                raise OSError(
                    "Simulated mid-write interruption after partial bytes"
                )

        with mock.patch.object(
            onesar_phenix_measure,
            "_open_checkpoint_temp_file",
            side_effect=_InterruptedTempFileWrapper,
        ):
            with self.assertRaisesRegex(
                OSError,
                "Simulated mid-write interruption after partial bytes",
            ):
                onesar_phenix_measure._checkpoint_diagnostics(
                    {
                        "status": "running",
                        "current_phase": "update_all_scales",
                    },
                    atomic_target,
                )

        self.assertEqual(len(partial_temp_records), 1)
        recorded_tmp_path, recorded_partial_bytes = partial_temp_records[0]
        self.assertEqual(len(recorded_partial_bytes), 16)
        self.assertFalse(recorded_tmp_path.exists())
        self.assertEqual(atomic_target.read_bytes(), prior_bytes)
        self.assertEqual(
            json.loads(atomic_target.read_text(encoding="utf-8")),
            prior_payload,
        )
        self.assertEqual(
            list(tmp_dir.glob(".atomic_checkpoint.json.tmp.*")), []
        )

        real_os_replace = onesar_phenix_measure.os.replace
        replace_temp_records: list[tuple[Path, bytes]] = []

        def _interrupted_os_replace(src: Any, dst: Any) -> None:
            src_path = Path(src)
            replace_temp_records.append((src_path, src_path.read_bytes()))
            raise OSError("Simulated os.replace interruption")

        with mock.patch.object(
            onesar_phenix_measure.os,
            "replace",
            side_effect=_interrupted_os_replace,
        ):
            with self.assertRaisesRegex(
                OSError, "Simulated os.replace interruption"
            ):
                onesar_phenix_measure._checkpoint_diagnostics(
                    {
                        "status": "running",
                        "current_phase": "update_all_scales",
                    },
                    atomic_target,
                )
        self.assertEqual(len(replace_temp_records), 1)
        replace_tmp_path, replace_tmp_bytes = replace_temp_records[0]
        self.assertEqual(
            json.loads(replace_tmp_bytes.decode("utf-8"))["current_phase"],
            "update_all_scales",
        )
        self.assertFalse(replace_tmp_path.exists())
        self.assertEqual(atomic_target.read_bytes(), prior_bytes)
        self.assertEqual(
            json.loads(atomic_target.read_text(encoding="utf-8")),
            prior_payload,
        )
        self.assertEqual(
            list(tmp_dir.glob(".atomic_checkpoint.json.tmp.*")), []
        )
        self.assertIs(
            onesar_phenix_measure._open_checkpoint_temp_file, real_open_temp
        )
        self.assertIs(onesar_phenix_measure.os.replace, real_os_replace)

    def test_atomic_checkpoint_interrupted_write_and_promotion_preserve_prior_1014(
        self,
    ) -> None:
        """Standalone test for mid-write partial bytes and failed promotion on atomic checkpoints."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp).resolve(strict=True)
            self._verify_atomic_checkpoint_interrupted_write_and_promotion(
                tmp_dir
            )


class TestTask179CanaryCliAndAttemptOrchestration(unittest.TestCase):
    """Hermetic tests for the Task 179 thin single-subject CLI and attempt orchestration."""

    @staticmethod
    def _write_json_file(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = (
            json.dumps(dict(payload), indent=2, sort_keys=True, allow_nan=False)
            + "\n"
        ).encode("utf-8")
        path.write_bytes(raw)
        return {
            "path": str(path),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw),
            "persisted": True,
        }

    @staticmethod
    @contextlib.contextmanager
    def _without_protstruct_env_overrides() -> Any:
        saved = {
            k: v
            for k, v in os.environ.items()
            if k.startswith("PROTSTRUCT_")
        }
        try:
            for k in saved:
                os.environ.pop(k, None)
            yield
        finally:
            for k in list(os.environ.keys()):
                if k.startswith("PROTSTRUCT_"):
                    os.environ.pop(k, None)
            os.environ.update(saved)

    @classmethod
    def _make_fake_phenix_runner_and_build(
        cls, base_dir: Path
    ) -> tuple[Path, dict[str, Any], Callable[..., subprocess.CompletedProcess[str]]]:
        fake_prefix = base_dir / "phenix-2.0-5936-synthetic"
        fake_bin = fake_prefix / "phenix_bin"
        fake_site = fake_prefix / "lib" / "python3.9" / "site-packages"
        fake_bin.mkdir(parents=True, exist_ok=True)
        (fake_prefix / "phenix_env.sh").write_text(
            "#!/bin/sh\nexport PHENIX_VERSION=2.0\nexport PHENIX_RELEASE_TAG=5936\n",
            encoding="utf-8",
        )
        (fake_bin / "phenix.version").write_text("#!/bin/sh\n", encoding="utf-8")
        (fake_bin / "phenix.python").write_text("#!/bin/sh\n", encoding="utf-8")

        vendor_modules_payload: dict[str, dict[str, str]] = {}
        for key, rel in onesar_rerun.PHENIX_VENDOR_SOURCE_RELPATHS.items():
            mod_file = fake_site / rel
            mod_file.parent.mkdir(parents=True, exist_ok=True)
            content = f"# synthetic test module {key}\n".encode("utf-8")
            mod_file.write_bytes(content)
            resolved_mod = mod_file.resolve(strict=True)
            vendor_modules_payload[key] = {
                "module_name": key,
                "configured_path": str(resolved_mod),
                "resolved_path": str(resolved_mod),
                "sha256": hashlib.sha256(content).hexdigest(),
            }

        banner = "PHENIX: 2.0-5936\n  Version: 2.0\n  Release tag: 5936"
        setup_resolved = (fake_prefix / "phenix_env.sh").resolve(strict=True)
        disp_resolved = (fake_bin / "phenix.version").resolve(strict=True)
        resolved_prefix_str = str(fake_prefix.resolve(strict=True))
        fake_measured_build: dict[str, Any] = {
            "reported_version_source": "vendor_setup_environment",
            "reported_version": banner,
            "parsed_build": "2.0-5936",
            "version_probe": {
                "error": None,
                "probe_mode": "vendor_setup_environment",
                "configured_prefix": str(fake_prefix),
                "resolved_prefix": resolved_prefix_str,
                "setup_configured_path": str(fake_prefix / "phenix_env.sh"),
                "setup_resolved_path": str(setup_resolved),
                "setup_sha256": hashlib.sha256(
                    setup_resolved.read_bytes()
                ).hexdigest(),
                "setup_argv": toolchain.phenix_setup_argv(setup_resolved),
                "setup_returncode": 0,
                "setup_stdout": "",
                "setup_stderr": "",
                "setup_version_fields": {
                    "PHENIX_VERSION": "2.0",
                    "PHENIX_RELEASE_TAG": "5936",
                },
                "setup_parsed_build": "2.0-5936",
                "configured_path": str(fake_bin / "phenix.version"),
                "resolved_path": str(disp_resolved),
                "sha256": hashlib.sha256(disp_resolved.read_bytes()).hexdigest(),
                "argv": [str(disp_resolved)],
                "returncode": 0,
                "stdout": banner + "\n",
                "stderr": "",
                "parsed_build": "2.0-5936",
                "ignored_inherited_version_variables": [],
                "ignored_inherited_shell_hooks": [],
            },
        }

        def fake_phenix_runner(
            argv: list[str], log: Path, *, cwd: Path, timeout: float
        ) -> subprocess.CompletedProcess[str]:
            mtz_arg = Path(argv[argv.index("--mtz") + 1])
            out_json = Path(argv[argv.index("--out-json") + 1])
            out_maps = Path(argv[argv.index("--out-maps-mtz") + 1])
            out_obs_pair = Path(argv[argv.index("--out-obs-pair-mtz") + 1])
            out_diag = Path(argv[argv.index("--out-diagnostics-json") + 1])

            ledger = onesar_rerun.build_input_hkl_ledger(mtz_arg.read_bytes())
            work_candidates = [
                v
                for v in ledger["eligible_by_hkl"].values()
                if not v["is_free"] and v["f_obs"] > 0.0
            ][:3]
            free_candidates = [
                v
                for v in ledger["eligible_by_hkl"].values()
                if v["is_free"] and v["f_obs"] > 0.0
            ][:2]
            w0, w1, w_outlier = (
                work_candidates[0],
                work_candidates[1],
                work_candidates[2],
            )
            f0, f1 = free_candidates[0], free_candidates[1]

            scale_k1_w = 0.5
            scale_k1_t = 0.5
            scale_k1 = 0.5
            work_ratio = 0.875
            free_ratio = 0.75

            _, base_payload, _, _, _ = _make_reconciliation_fixture()
            synth = copy.deepcopy(base_payload)
            synth["expected_resolved_prefix"] = resolved_prefix_str
            synth["expected_phenix_version"] = toolchain.PHENIX_VERSION
            synth["runtime_environment"]["sys_prefix"] = str(fake_prefix)
            synth["runtime_environment"]["resolved_sys_prefix"] = (
                resolved_prefix_str
            )
            synth["runtime_environment"]["sys_executable"] = str(
                (fake_bin / "phenix.python").resolve(strict=True)
            )
            synth["runtime_environment"]["resolved_sys_executable"] = str(
                (fake_bin / "phenix.python").resolve(strict=True)
            )
            synth["runtime_environment"]["vendor_modules"] = (
                vendor_modules_payload
            )

            extracted_items = [w0, w1, w_outlier, f0, f1]
            final_items = [w0, w1, f0, f1]
            synth["extracted_pre_fmodel"] = [
                {
                    "hkl": list(item["hkl"]),
                    "f_obs": float(item["f_obs"]),
                    "sigf_obs": float(item["sigf_obs"]),
                    "is_free": bool(item["is_free"]),
                }
                for item in extracted_items
            ]
            synth["final_effective"] = [
                {
                    "hkl": list(item["hkl"]),
                    "f_obs": float(item["f_obs"]),
                    "sigf_obs": float(item["sigf_obs"]),
                    "is_free": bool(item["is_free"]),
                }
                for item in final_items
            ]
            synth["actual_work"] = [
                {
                    "hkl": list(item["hkl"]),
                    "f_obs": float(item["f_obs"]),
                    "sigf_obs": float(item["sigf_obs"]),
                    "f_model_real": (work_ratio * float(item["f_obs"]))
                    / scale_k1_w,
                    "f_model_imag": 0.0,
                    "f_model_amplitude": (work_ratio * float(item["f_obs"]))
                    / scale_k1_w,
                    "f_model_scaled_with_k1_w_real": work_ratio
                    * float(item["f_obs"]),
                    "f_model_scaled_with_k1_w_imag": 0.0,
                    "f_model_scaled_with_k1_w_amplitude": work_ratio
                    * float(item["f_obs"]),
                }
                for item in (w0, w1)
            ]
            synth["actual_free"] = [
                {
                    "hkl": list(item["hkl"]),
                    "f_obs": float(item["f_obs"]),
                    "sigf_obs": float(item["sigf_obs"]),
                    "f_model_real": (free_ratio * float(item["f_obs"]))
                    / scale_k1_t,
                    "f_model_imag": 0.0,
                    "f_model_amplitude": (free_ratio * float(item["f_obs"]))
                    / scale_k1_t,
                    "f_model_scaled_with_k1_t_real": free_ratio
                    * float(item["f_obs"]),
                    "f_model_scaled_with_k1_t_imag": 0.0,
                    "f_model_scaled_with_k1_t_amplitude": free_ratio
                    * float(item["f_obs"]),
                }
                for item in (f0, f1)
            ]

            w_den = float(w0["f_obs"]) + float(w1["f_obs"])
            w_num = abs(
                float(w0["f_obs"]) - work_ratio * float(w0["f_obs"])
            ) + abs(float(w1["f_obs"]) - work_ratio * float(w1["f_obs"]))
            f_den = float(f0["f_obs"]) + float(f1["f_obs"])
            f_num = abs(
                float(f0["f_obs"]) - free_ratio * float(f0["f_obs"])
            ) + abs(float(f1["f_obs"]) - free_ratio * float(f1["f_obs"]))
            all_num = w_num + f_num
            all_den = w_den + f_den
            r_work = w_num / w_den
            r_free = f_num / f_den
            r_all = all_num / all_den
            r_gap = r_free - r_work

            synth["scales_and_rfactors"].update(
                {
                    "r_work": r_work,
                    "r_free": r_free,
                    "r_all": r_all,
                    "r_free_r_work_gap": r_gap,
                    "scale_k1_w": scale_k1_w,
                    "scale_k1_t": scale_k1_t,
                    "scale_k1": scale_k1,
                    "work_numerator": w_num,
                    "work_denominator": w_den,
                    "free_numerator": f_num,
                    "free_denominator": f_den,
                    "all_numerator": all_num,
                    "all_denominator": all_den,
                    "work_count": 2,
                    "free_count": 2,
                    "final_effective_count": 4,
                    "extracted_pre_fmodel_count": 5,
                }
            )

            map_recs = [
                {
                    "hkl": list(item["hkl"]),
                    "real": 1.0,
                    "imag": 0.0,
                    "amplitude": 1.0,
                    "phase_deg": 0.0,
                    "is_centric": True,
                }
                for item in final_items
            ]
            synth["map_coefficients"]["2mFo-DFc"]["records"] = copy.deepcopy(
                map_recs
            )
            synth["map_coefficients"]["2mFo-DFc"]["centric_count"] = 4
            synth["map_coefficients"]["2mFo-DFc"]["acentric_count"] = 0
            synth["map_coefficients"]["mFo-DFc"]["records"] = copy.deepcopy(
                map_recs
            )
            synth["map_coefficients"]["mFo-DFc"]["centric_count"] = 4
            synth["map_coefficients"]["mFo-DFc"]["acentric_count"] = 0

            cell_floats = tuple(
                float(x)
                for x in ledger["crystallographic_context"][
                    "cell_a_b_c_alpha_beta_gamma"
                ]
            )
            runtime_cell_floats = onesar_rerun.ccp4_mtz_float32_unit_cell(
                ledger["crystallographic_context"][
                    "cell_a_b_c_alpha_beta_gamma"
                ]
            )
            synth["crystal_symmetry"] = {
                "unit_cell": list(runtime_cell_floats),
                "space_group_symbol": "P 21 21 21 (No. 19)",
                "space_group_number": 19,
                "space_group_operators_xyz": [
                    "x,y,z",
                    "-x+1/2,-y,z+1/2",
                    "-x,y+1/2,-z+1/2",
                    "x+1/2,-y+1/2,-z",
                ],
            }
            ca, cb, cc = (
                runtime_cell_floats[0],
                runtime_cell_floats[1],
                runtime_cell_floats[2],
            )

            def _orth_range(items: list[dict[str, Any]]) -> dict[str, float]:
                ds = [
                    1.0
                    / math.sqrt(
                        (it["hkl"][0] / ca) ** 2
                        + (it["hkl"][1] / cb) ** 2
                        + (it["hkl"][2] / cc) ** 2
                    )
                    for it in items
                ]
                return {"d_max": max(ds), "d_min": min(ds)}

            synth["resolution_ranges"] = {
                "extracted_pre_fmodel": _orth_range(extracted_items),
                "final_effective": _orth_range(final_items),
                "actual_work": _orth_range([w0, w1]),
                "actual_free": _orth_range([f0, f1]),
            }

            m_bytes, p_bytes = _build_synthetic_map_mtz_pair(
                map_recs, map_recs, cell=cell_floats  # type: ignore[arg-type]
            )
            synth["map_coefficients"]["mtz_supplements"]["phx_maps_sha256"] = (
                hashlib.sha256(m_bytes).hexdigest()
            )
            synth["map_coefficients"]["mtz_supplements"][
                "obs_pair_only_sha256"
            ] = hashlib.sha256(p_bytes).hexdigest()

            diag_doc = {
                "schema_version": 1,
                "status": "succeeded",
                "extract_xtal_data_log": synth["diagnostics"][
                    "extract_xtal_data_log"
                ],
                "model_manager_log": synth["diagnostics"]["model_manager_log"],
                "fmodel_update_all_scales_log": synth["diagnostics"][
                    "fmodel_update_all_scales_log"
                ],
                "failure": None,
            }
            log.write_text("synthetic phenix.python stdout\n", encoding="utf-8")
            out_maps.write_bytes(m_bytes)
            out_obs_pair.write_bytes(p_bytes)
            out_diag.write_text(
                json.dumps(diag_doc, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            if "--out-partial-json" in argv:
                out_partial = Path(argv[argv.index("--out-partial-json") + 1])
                out_partial.write_text(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "artifact_role": "partial_unverified_phenix_evidence",
                            "status": "completed_superseded_by_verified_payload",
                            "current_phase": "completed",
                            "completed_stages": [
                                "extract_xtal_data",
                                "fmodel_manager_init",
                                "update_all_scales",
                                "rfactor_replay",
                                "map_export",
                            ],
                            "rfactor_replay_verified": True,
                            "map_export_verified": True,
                            "nonfinite_raw_values": [],
                            "failure": None,
                        },
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )
            out_json.write_text(
                json.dumps(synth, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(argv, 0)

        return fake_bin, fake_measured_build, fake_phenix_runner

    def test_cli_parser_required_flags_aliases_and_rejections(self) -> None:
        """Verify CLI required flags, lowercase aliases, rejections, and help vs refusal exit codes."""
        # Valid subjects and lowercase aliases normalize cleanly.
        for raw_subj, expected_norm in (
            ("start", "start"),
            ("R4", "R4"),
            ("r4", "R4"),
            ("R5", "R5"),
            ("r5", "R5"),
            ("R6", "R6"),
            ("r6", "R6"),
        ):
            ns = onesar_rerun.parse_cli_args(
                [
                    "--subject",
                    raw_subj,
                    "--family",
                    "rfactors",
                    "--evidence-out",
                    ".temp/canary_test",
                ]
            )
            self.assertEqual(ns.subject, expected_norm)
            self.assertEqual(ns.family, "rfactors")
            self.assertEqual(ns.timeout, 900.0)
            self.assertEqual(ns.evidence_out, Path(".temp/canary_test"))

        # Custom positive timeout is accepted.
        ns_timeout = onesar_rerun.parse_cli_args(
            [
                "--subject",
                "R4",
                "--family",
                "rfactors",
                "--evidence-out",
                ".temp/canary_timeout",
                "--timeout",
                "120.5",
            ]
        )
        self.assertEqual(ns_timeout.timeout, 120.5)

        # Rejected subjects: R7, r7, all, unknown.
        for bad_subject in ("R7", "r7", "all", "START", "R0", ""):
            with self.assertRaisesRegex(ValueError, "Unsupported subject"):
                onesar_rerun.parse_cli_args(
                    [
                        "--subject",
                        bad_subject,
                        "--family",
                        "rfactors",
                        "--evidence-out",
                        ".temp/bad_subj",
                    ]
                )

        # Rejected families: all, t01, t05, empty.
        for bad_family in ("all", "t01", "t05", "RFACTORS", ""):
            with self.assertRaisesRegex(
                ValueError, "Unsupported measurement family"
            ):
                onesar_rerun.parse_cli_args(
                    [
                        "--subject",
                        "R4",
                        "--family",
                        bad_family,
                        "--evidence-out",
                        ".temp/bad_fam",
                    ]
                )

        # Rejected timeouts: <= 0, NaN, inf, -inf (using --timeout=<val> so -inf reaches the validator).
        for bad_timeout in ("0", "-5", "nan", "inf", "-inf"):
            with self.assertRaisesRegex(ValueError, "Operation timeout"):
                onesar_rerun.parse_cli_args(
                    [
                        "--subject",
                        "R4",
                        "--family",
                        "rfactors",
                        "--evidence-out",
                        ".temp/bad_to",
                        f"--timeout={bad_timeout}",
                    ]
                )

        # Missing required flags or --all rejected by argparse (SystemExit != 0; main returns 2).
        for bad_argv in (
            [],
            ["--subject", "R4", "--family", "rfactors"],
            ["--subject", "R4", "--evidence-out", ".temp/x"],
            ["--family", "rfactors", "--evidence-out", ".temp/x"],
            [
                "--subject",
                "R4",
                "--family",
                "rfactors",
                "--evidence-out",
                ".temp/x",
                "--all",
            ],
        ):
            with self.assertRaises(SystemExit) as cm:
                onesar_rerun.parse_cli_args(bad_argv)
            self.assertNotEqual(cm.exception.code, 0)
            self.assertEqual(onesar_rerun.main(bad_argv), 2)

        # --help exits 0 via main(["--help"]).
        self.assertEqual(onesar_rerun.main(["--help"]), 0)

    def test_pre_admission_rejections_occur_before_parent_creation_or_producer_calls(
        self,
    ) -> None:
        """Verify pre-admission rejections never create <parent A>, mutate existing targets, or call producers."""
        import onesar_records
        import onesar_refmac

        with tempfile.TemporaryDirectory() as tmp:
            fake_repo = Path(tmp).resolve(strict=True) / "repo"
            fake_repo.mkdir()

            existing_dir = fake_repo / "runs" / "existing_attempt"
            existing_dir.mkdir(parents=True)
            marker_file = existing_dir / "keep.txt"
            marker_file.write_text("immutable marker\n", encoding="utf-8")

            real_sub = fake_repo / "real_sub"
            real_sub.mkdir()
            sym_sub = fake_repo / "sym_sub"
            sym_sub.symlink_to(real_sub)

            outside_target = Path(tmp).resolve(strict=True) / "outside_attempt"

            with (
                self._without_protstruct_env_overrides(),
                mock.patch.object(
                    onesar_rerun,
                    "run_phenix_rfactor_operation",
                    side_effect=AssertionError("PHENIX producer must not run"),
                ) as phx_mock,
                mock.patch.object(
                    onesar_refmac,
                    "run_refmac_rfactor_operation",
                    side_effect=AssertionError("REFMAC producer must not run"),
                ) as rm_mock,
                mock.patch.object(
                    onesar_records,
                    "publish_retained_rfactor_records",
                    side_effect=AssertionError("Record publisher must not run"),
                ) as pub_mock,
            ):
                # 1. Invalid subject R7 / r7.
                fresh_r7 = fake_repo / "runs" / "r7_attempt"
                self.assertEqual(
                    onesar_rerun.main(
                        [
                            "--subject",
                            "R7",
                            "--family",
                            "rfactors",
                            "--evidence-out",
                            str(fresh_r7),
                            "--repo-root",
                            str(fake_repo),
                        ]
                    ),
                    2,
                )
                self.assertFalse(fresh_r7.exists())

                # 2. Invalid family.
                fresh_fam = fake_repo / "runs" / "fam_attempt"
                self.assertEqual(
                    onesar_rerun.main(
                        [
                            "--subject",
                            "R4",
                            "--family",
                            "t05",
                            "--evidence-out",
                            str(fresh_fam),
                            "--repo-root",
                            str(fake_repo),
                        ]
                    ),
                    2,
                )
                self.assertFalse(fresh_fam.exists())

                # 3. PROTSTRUCT_* environment override (unrelated var and empty var).
                for env_override in (
                    {"PROTSTRUCT_CUSTOM_FOO": "bar"},
                    {"PROTSTRUCT_PHENIX_BIN": ""},
                ):
                    fresh_env = fake_repo / "runs" / "env_attempt"
                    with mock.patch.dict(os.environ, env_override):
                        self.assertEqual(
                            onesar_rerun.main(
                                [
                                    "--subject",
                                    "R4",
                                    "--family",
                                    "rfactors",
                                    "--evidence-out",
                                    str(fresh_env),
                                    "--repo-root",
                                    str(fake_repo),
                                ]
                            ),
                            2,
                        )
                    self.assertFalse(fresh_env.exists())

                # 4. Existing target directory preserved untouched.
                self.assertEqual(
                    onesar_rerun.main(
                        [
                            "--subject",
                            "R4",
                            "--family",
                            "rfactors",
                            "--evidence-out",
                            str(existing_dir),
                            "--repo-root",
                            str(fake_repo),
                        ]
                    ),
                    2,
                )
                self.assertEqual(
                    marker_file.read_text(encoding="utf-8"),
                    "immutable marker\n",
                )
                self.assertEqual(
                    list(existing_dir.iterdir()), [marker_file]
                )

                # 5. Symlink ancestor, outside-repo target, and raw '..' target rejected.
                for bad_out in (
                    sym_sub / "attempt_01",
                    outside_target,
                    Path(f"{fake_repo}/runs/../runs/attempt_dotdot"),
                ):
                    self.assertEqual(
                        onesar_rerun.main(
                            [
                                "--subject",
                                "R4",
                                "--family",
                                "rfactors",
                                "--evidence-out",
                                str(bad_out),
                                "--repo-root",
                                str(fake_repo),
                            ]
                        ),
                        2,
                    )
                self.assertFalse(outside_target.exists())

                self.assertEqual(phx_mock.call_count, 0)
                self.assertEqual(rm_mock.call_count, 0)
                self.assertEqual(pub_mock.call_count, 0)

    def test_sequential_orchestration_distinct_children_midnight_date_and_all_four_subjects(
        self,
    ) -> None:
        """Verify sequential 2-producer orchestration, distinct children, 14-key checkpoint, and midnight UTC start date."""
        import onesar_records
        import onesar_refmac

        with tempfile.TemporaryDirectory() as tmp:
            fake_repo = Path(tmp).resolve(strict=True) / "repo"
            fake_repo.mkdir()

            for raw_subject, expected_subject in (
                ("r4", "R4"),
                ("start", "start"),
                ("r5", "R5"),
                ("r6", "R6"),
            ):
                with self.subTest(subject=raw_subject):
                    call_order: list[tuple[str, Path, str]] = []
                    parent_out = (
                        fake_repo / "runs" / f"attempt_{expected_subject.lower()}"
                    )

                    def fake_phenix_op(
                        evidence_root: Path,
                        subject_id: str = "R4",
                        *,
                        repo_root: Path = REPO_ROOT,
                        archive_path: Path | None = None,
                        timeout: float = 900.0,
                        require_no_protstruct_overrides: bool = True,
                        runner: Any = None,
                    ) -> dict[str, Any]:
                        # parent_attempt_started.json must already exist before Producer 1 starts.
                        started_path = (
                            parent_out
                            / onesar_rerun.PARENT_ATTEMPT_STARTED_FILENAME
                        )
                        self.assertTrue(started_path.is_file())
                        self.assertFalse(evidence_root.exists())
                        call_order.append(("phenix", evidence_root, subject_id))
                        self.assertEqual(subject_id, expected_subject)
                        self.assertEqual(repo_root, fake_repo)
                        self.assertEqual(timeout, 450.0)
                        self.assertFalse(require_no_protstruct_overrides)

                        cache_manifest_path = (
                            evidence_root
                            / "phenix"
                            / "cache"
                            / "op"
                            / "bundle"
                            / "success.json"
                        )
                        cache_ref = self._write_json_file(
                            cache_manifest_path,
                            {
                                "returncode": 0,
                                "reusable": True,
                                "invocation": {"executable": "phenix.python"},
                                "artifacts": {},
                            },
                        )
                        reconciled_path = (
                            evidence_root
                            / "phenix"
                            / "phenix_reconciled_manifest.json"
                        )
                        reconciled_payload = {
                            "schema_version": 1,
                            "subject": onesar_rerun.resolve_subject_spec(
                                subject_id
                            ),
                            "mtz": {
                                "member": onesar_rerun.MTZ_MEMBER,
                                "sha256": onesar_rerun.MTZ_SHA256,
                                "subject_ref": onesar_rerun.MTZ_SUBJECT_REF,
                            },
                            "staged_files": {},
                            "manifest_path": str(cache_manifest_path),
                            "manifest_sha256": cache_ref["sha256"],
                            "operation_manifest": {"returncode": 0},
                            "reconciliation": {
                                "reconciliation_status": "verified"
                            },
                        }
                        self._write_json_file(
                            reconciled_path, reconciled_payload
                        )
                        return reconciled_payload

                    def fake_refmac_op(
                        evidence_root: Path | str,
                        subject_id: str = "R4",
                        *,
                        repo_root: Path | str = REPO_ROOT,
                        archive_path: Path | str | None = None,
                        timeout: float = 900.0,
                        require_no_protstruct_overrides: bool = True,
                        runner: Any = None,
                    ) -> dict[str, Any]:
                        ev_path = Path(evidence_root)
                        self.assertFalse(ev_path.exists())
                        call_order.append(("refmac", ev_path, subject_id))
                        self.assertEqual(subject_id, expected_subject)
                        self.assertEqual(Path(repo_root), fake_repo)
                        self.assertEqual(timeout, 450.0)
                        self.assertFalse(require_no_protstruct_overrides)

                        rm_manifest_path = (
                            ev_path / "refmac" / "refmac_operation_manifest.json"
                        )
                        rm_payload = {
                            "schema_version": 1,
                            "status": "diagnostic_captured_gates_unproven",
                            "subject_id": subject_id,
                        }
                        rm_ref = self._write_json_file(
                            rm_manifest_path, rm_payload
                        )
                        # Match onesar_refmac.run_refmac_rfactor_operation return shape (no "persisted" key).
                        rm_ref.pop("persisted", None)
                        # Include fallback ancestry metadata to verify intact forwarding.
                        rm_ref["is_fallback"] = True
                        rm_ref["fallback_for_preexisting_path"] = str(
                            ev_path / "refmac" / "intended.json"
                        )
                        out = dict(rm_payload)
                        out["manifest_json"] = rm_ref
                        return out

                    def fake_publish(
                        admitted_root: Path | str,
                        *,
                        subject_id: str,
                        checkpoint_reference: Mapping[str, Any] | None = None,
                        phenix_reconciled_manifest_reference: (
                            Mapping[str, Any] | None
                        ) = None,
                        refmac_operation_manifest_reference: (
                            Mapping[str, Any] | None
                        ) = None,
                        expected_family: str = "rfactors",
                        expected_run_date: str | None = None,
                        repo_root: Path | str | None = None,
                        output_repo_root: Path | str | None = None,
                        **kwargs: Any,
                    ) -> dict[str, Any]:
                        call_order.append(
                            ("publish", Path(admitted_root), subject_id)
                        )
                        self.assertEqual(subject_id, expected_subject)
                        self.assertEqual(expected_family, "rfactors")
                        # Midnight-spanning interval must forward UTC start date 2026-11-06.
                        self.assertEqual(expected_run_date, "2026-11-06")
                        assert isinstance(checkpoint_reference, Mapping)
                        assert isinstance(
                            phenix_reconciled_manifest_reference, Mapping
                        )
                        assert isinstance(
                            refmac_operation_manifest_reference, Mapping
                        )
                        self.assertTrue(
                            Path(
                                str(phenix_reconciled_manifest_reference["path"])
                            ).name
                            == "phenix_reconciled_manifest.json"
                        )
                        self.assertIs(
                            refmac_operation_manifest_reference.get(
                                "persisted"
                            ),
                            True,
                        )
                        self.assertIs(
                            refmac_operation_manifest_reference.get(
                                "is_fallback"
                            ),
                            True,
                        )
                        err = onesar_records.RefmacScientificAdmissionRefusedError(
                            "synthetic refusal after checkpoint",
                            refusal_record={
                                "producer": "refmac",
                                "subject_id": subject_id,
                                "integrity_verified": True,
                                "scientific_proof_established": False,
                                "unknown_native_premises": {},
                                "refusal_reasons": ["unproven"],
                                "unsupported_proof_claims": [],
                                "verified_references": {},
                            },
                        )
                        err.authoring_outcome = {  # type: ignore[attr-defined]
                            "status": "refused",
                            "published": False,
                            "failed_stage": "refmac_retained_verification",
                            "authoring_policy_issued_at": None,
                            "outcome_path": str(
                                Path(admitted_root)
                                / "authoring_outcomes"
                                / "authoring_outcome_0001.json"
                            ),
                        }
                        err.authoring_outcome_path = err.authoring_outcome[  # type: ignore[attr-defined]
                            "outcome_path"
                        ]
                        raise err

                    with (
                        mock.patch.object(
                            onesar_rerun,
                            "run_phenix_rfactor_operation",
                            side_effect=fake_phenix_op,
                        ),
                        mock.patch.object(
                            onesar_refmac,
                            "run_refmac_rfactor_operation",
                            side_effect=fake_refmac_op,
                        ),
                        mock.patch.object(
                            onesar_records,
                            "publish_retained_rfactor_records",
                            side_effect=fake_publish,
                        ),
                    ):
                        outcome = onesar_rerun.run_single_subject_rfactor_attempt(
                            parent_out,
                            raw_subject,
                            family="rfactors",
                            repo_root=fake_repo,
                            timeout=450.0,
                            require_no_protstruct_overrides=False,
                            started_at_utc_override="2026-11-06T23:58:10+00:00",
                            checkpoint_finished_at_utc_override="2026-11-07T00:03:25+00:00",
                        )

                    self.assertEqual(
                        call_order,
                        [
                            ("phenix", parent_out / "phenix", expected_subject),
                            ("refmac", parent_out / "refmac", expected_subject),
                            ("publish", parent_out, expected_subject),
                        ],
                    )
                    self.assertEqual(outcome["status"], "refused")
                    self.assertIs(outcome["published"], False)
                    self.assertEqual(outcome["run_date"], "2026-11-06")
                    self.assertIsNone(outcome["authoring_policy_issued_at"])

                    # Verify parent_completed_execution_checkpoint.json has exact 14 keys and no outcome/CLI fields.
                    cp_path = (
                        parent_out
                        / onesar_rerun.PARENT_COMPLETED_CHECKPOINT_FILENAME
                    )
                    cp_doc = json.loads(cp_path.read_text(encoding="utf-8"))
                    self.assertEqual(
                        set(cp_doc.keys()),
                        onesar_records.REQUIRED_PARENT_EXECUTION_CHECKPOINT_KEYS,
                    )
                    self.assertEqual(len(cp_doc), 14)
                    self.assertEqual(cp_doc["run_date"], "2026-11-06")
                    self.assertEqual(
                        cp_doc["started_at_utc"], "2026-11-06T23:58:10+00:00"
                    )
                    self.assertEqual(
                        cp_doc["finished_at_utc"], "2026-11-07T00:03:25+00:00"
                    )
                    self.assertTrue(
                        cp_doc["refmac_operation_manifest"]["is_fallback"]
                    )
                    for forbidden_key in (
                        "argv",
                        "final_outcome",
                        "authoring_outcome",
                        "published",
                        "status",
                    ):
                        self.assertNotIn(forbidden_key, cp_doc)

    def test_post_start_record_identity_resolution_failure_persists_failed_outcome(
        self,
    ) -> None:
        """Verify a post-start _resolve_rfactor_record_identities exception persists a failed outcome before any producer."""
        import onesar_records
        import onesar_refmac

        with tempfile.TemporaryDirectory() as tmp:
            fake_repo = Path(tmp).resolve(strict=True) / "repo"
            fake_repo.mkdir()
            fail_out = fake_repo / "runs" / "identity_res_fail"

            with (
                self._without_protstruct_env_overrides(),
                mock.patch.object(
                    onesar_records,
                    "_resolve_rfactor_record_identities",
                    side_effect=onesar_records.RfactorRecordAssemblyError(
                        "injected post-start identity resolution failure"
                    ),
                ) as res_mock,
                mock.patch.object(
                    onesar_rerun,
                    "run_phenix_rfactor_operation",
                    side_effect=AssertionError(
                        "PHENIX must not run after identity resolution failure"
                    ),
                ) as phx_mock,
                mock.patch.object(
                    onesar_refmac,
                    "run_refmac_rfactor_operation",
                    side_effect=AssertionError(
                        "REFMAC must not run after identity resolution failure"
                    ),
                ) as rm_mock,
                mock.patch.object(
                    onesar_records,
                    "publish_retained_rfactor_records",
                    side_effect=AssertionError(
                        "Publisher must not run after identity resolution failure"
                    ),
                ) as pub_mock,
            ):
                rc = onesar_rerun.main(
                    [
                        "--subject",
                        "R4",
                        "--family",
                        "rfactors",
                        "--evidence-out",
                        str(fail_out),
                        "--repo-root",
                        str(fake_repo),
                    ]
                )
                self.assertEqual(rc, 1)
                self.assertEqual(res_mock.call_count, 1)
                self.assertEqual(phx_mock.call_count, 0)
                self.assertEqual(rm_mock.call_count, 0)
                self.assertEqual(pub_mock.call_count, 0)

            self.assertTrue(
                (fail_out / onesar_rerun.PARENT_ATTEMPT_STARTED_FILENAME).is_file()
            )
            outcome_path = fail_out / onesar_rerun.PARENT_ATTEMPT_OUTCOME_FILENAME
            self.assertTrue(outcome_path.is_file())
            self.assertFalse((fail_out / "phenix").exists())
            self.assertFalse((fail_out / "refmac").exists())

            outcome_doc = json.loads(outcome_path.read_text(encoding="utf-8"))
            self.assertEqual(outcome_doc["status"], "failed")
            self.assertIs(outcome_doc["published"], False)
            self.assertEqual(outcome_doc["commit_state"], "not_committed")
            self.assertIs(outcome_doc["committed"], False)
            self.assertEqual(
                outcome_doc["failed_stage"], "record_identity_resolution"
            )
            self.assertEqual(
                outcome_doc["completed_steps"], ["parent_attempt_started"]
            )
            self.assertEqual(
                outcome_doc["intended_paths"],
                {"eval_path": None, "qds_path": None},
            )
            self.assertEqual(
                outcome_doc["error"]["exception_type"],
                "RfactorRecordAssemblyError",
            )
            self.assertIn(
                "injected post-start identity resolution failure",
                outcome_doc["error"]["exception_message"],
            )

    def test_phenix_cache_manifest_vs_reconciled_manifest_binding_and_producer_failures(
        self,
    ) -> None:
        """Verify Producer 1/2 failure handling and rejection of cache success.json as reconciled manifest."""
        import onesar_records
        import onesar_refmac

        with tempfile.TemporaryDirectory() as tmp:
            fake_repo = Path(tmp).resolve(strict=True) / "repo"
            fake_repo.mkdir()

            # 1. Producer 1 failure before staging stops before Producer 2 and writes parent_attempt_outcome.json.
            p1_fail_out = fake_repo / "runs" / "p1_fail"
            with (
                mock.patch.object(
                    onesar_rerun,
                    "run_phenix_rfactor_operation",
                    side_effect=RuntimeError("synthetic phenix pre-stage failure"),
                ),
                mock.patch.object(
                    onesar_refmac,
                    "run_refmac_rfactor_operation",
                    side_effect=AssertionError("REFMAC must not run after PHENIX failure"),
                ) as rm_mock,
                mock.patch.object(
                    onesar_records,
                    "publish_retained_rfactor_records",
                    side_effect=AssertionError("Publisher must not run after PHENIX failure"),
                ) as pub_mock,
            ):
                outcome_p1 = onesar_rerun.run_single_subject_rfactor_attempt(
                    p1_fail_out,
                    "R4",
                    repo_root=fake_repo,
                    require_no_protstruct_overrides=False,
                )
                self.assertEqual(rm_mock.call_count, 0)
                self.assertEqual(pub_mock.call_count, 0)
            self.assertEqual(outcome_p1["status"], "failed")
            self.assertIs(outcome_p1["published"], False)
            self.assertEqual(
                outcome_p1["failed_stage"], "phenix_rfactor_operation"
            )
            self.assertIsNone(outcome_p1["completed_checkpoint_reference"])
            self.assertIs(
                outcome_p1["phenix_inventory"][
                    "retained_attempt_artifacts_available"
                ],
                False,
            )
            self.assertEqual(
                outcome_p1["phenix_inventory"][
                    "retained_attempt_artifacts_status"
                ],
                "unavailable",
            )
            self.assertFalse(
                (
                    p1_fail_out
                    / onesar_rerun.PARENT_COMPLETED_CHECKPOINT_FILENAME
                ).exists()
            )
            self.assertTrue(
                (
                    p1_fail_out / onesar_rerun.PARENT_ATTEMPT_OUTCOME_FILENAME
                ).is_file()
            )

            # 2. Producer 1 failure with phenix_operation_failure.json inventories retained_attempt_artifacts
            # and inputs/original_data.mtz while rejecting symlink/outside-root entries.
            p1_ret_fail_out = fake_repo / "runs" / "p1_retained_fail"
            outside_secret = Path(tmp).resolve(strict=True) / "outside_secret.json"
            outside_secret.write_text('{"secret": true}\n', encoding="utf-8")

            def _retained_fail_phenix(
                evidence_root: Path, *args: Any, **kwargs: Any
            ) -> dict[str, Any]:
                inputs_dir = evidence_root / "inputs"
                inputs_dir.mkdir(parents=True, exist_ok=True)
                (inputs_dir / "original_model.pdb").write_text(
                    "ATOM      1  N   VAL A   1       1.000   2.000   3.000  1.00 10.00           N\nEND\n",
                    encoding="utf-8",
                )
                (inputs_dir / "original_data.mtz").write_bytes(b"MTZ_ORIG_BYTES")
                (inputs_dir / "projected_observations.mtz").write_bytes(
                    b"MTZ_PROJ_BYTES"
                )
                self._write_json_file(
                    inputs_dir / "input_hkl_ledger.json", {"schema_version": 1}
                )
                self._write_json_file(
                    inputs_dir / "input_admission.json", {"schema_version": 1}
                )

                phx_dir = evidence_root / "phenix"
                phx_dir.mkdir(parents=True, exist_ok=True)
                preflight_path = phx_dir / "phenix_preflight_build_evidence.json"
                preflight_ref = self._write_json_file(
                    preflight_path, {"parsed_build": "2.0-5936"}
                )

                attempt_dir = (
                    phx_dir
                    / "cache"
                    / "refinement_cache_v1"
                    / "onesar_phenix_first_block_rfactors_R4"
                    / ".attempt-0123456789abcdef-x"
                )
                attempt_dir.mkdir(parents=True, exist_ok=True)
                stdout_p = attempt_dir / "stdout.log"
                stdout_p.write_text("failed worker stdout\n", encoding="utf-8")
                inv_p = attempt_dir / "invocation.json"
                self._write_json_file(inv_p, {"contract": 1})
                diag_p = attempt_dir / "phenix_diagnostics.json"
                self._write_json_file(diag_p, {"status": "failed"})
                partial_p = attempt_dir / "phenix_rfactors_partial_evidence.json"
                self._write_json_file(partial_p, {"status": "failed"})
                maps_p = attempt_dir / "phx_maps.mtz"
                maps_p.write_bytes(b"MAPS_BYTES")
                obs_p = attempt_dir / "PHX_OBS_PAIR_ONLY.mtz"
                obs_p.write_bytes(b"OBS_BYTES")
                rf_p = attempt_dir / "phenix_rfactors.json"
                self._write_json_file(rf_p, {"schema_version": 1})
                man_p = attempt_dir / "success.json"
                self._write_json_file(man_p, {"returncode": 0, "reusable": True})

                symlink_p = attempt_dir / "symlink_escape.json"
                symlink_p.symlink_to(outside_secret)

                retained_map = {}
                for k, p in (
                    ("stdout_log", stdout_p),
                    ("invocation_json", inv_p),
                    ("phenix_diagnostics_json", diag_p),
                    ("phenix_partial_evidence_json", partial_p),
                    ("phx_maps_mtz", maps_p),
                    ("phx_obs_pair_only_mtz", obs_p),
                    ("phenix_rfactors_json", rf_p),
                    ("manifest_json", man_p),
                ):
                    retained_map[k] = {
                        "path": str(p),
                        "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                    }
                retained_map["escaped_outside"] = {
                    "path": str(outside_secret),
                    "sha256": hashlib.sha256(
                        outside_secret.read_bytes()
                    ).hexdigest(),
                }
                retained_map["escaped_symlink"] = {
                    "path": str(symlink_p),
                    "sha256": hashlib.sha256(
                        outside_secret.read_bytes()
                    ).hexdigest(),
                }

                self._write_json_file(
                    phx_dir / "phenix_operation_failure.json",
                    {
                        "schema_version": 1,
                        "status": "failed",
                        "failed_stage": "reconcile_phenix_rfactor_output",
                        "preflight_build_evidence_json_path": str(preflight_path),
                        "preflight_build_evidence_sha256": preflight_ref["sha256"],
                        "retained_attempt_artifacts": retained_map,
                    },
                )
                raise RuntimeError("reconciliation failed after worker execution")

            with (
                mock.patch.object(
                    onesar_rerun,
                    "run_phenix_rfactor_operation",
                    side_effect=_retained_fail_phenix,
                ),
                mock.patch.object(
                    onesar_refmac,
                    "run_refmac_rfactor_operation",
                    side_effect=AssertionError("REFMAC must not run"),
                ),
            ):
                outcome_p1_ret = onesar_rerun.run_single_subject_rfactor_attempt(
                    p1_ret_fail_out,
                    "R4",
                    repo_root=fake_repo,
                    require_no_protstruct_overrides=False,
                )
            self.assertEqual(outcome_p1_ret["status"], "failed")
            self.assertIs(outcome_p1_ret["published"], False)
            phx_inv_ret = outcome_p1_ret["phenix_inventory"]
            self.assertIs(
                phx_inv_ret["retained_attempt_artifacts_available"], True
            )
            self.assertEqual(
                phx_inv_ret["retained_attempt_artifacts_status"], "available"
            )
            for expected_key in (
                "original_data_mtz",
                "original_model_pdb",
                "projected_observations_mtz",
                "input_hkl_ledger_json",
                "input_admission_json",
                "preflight_build_evidence_json",
                "phenix_operation_failure_json",
                "stdout_log",
                "invocation_json",
                "phenix_diagnostics_json",
                "phenix_partial_evidence_json",
                "phx_maps_mtz",
                "phx_obs_pair_only_mtz",
                "phenix_rfactors_json",
                "manifest_json",
                "cache_manifest_json",
            ):
                self.assertIn(expected_key, phx_inv_ret["retained_files"])
            self.assertNotIn("escaped_outside", phx_inv_ret["retained_files"])
            self.assertNotIn("escaped_symlink", phx_inv_ret["retained_files"])

            # 3. Producer 1 returns only cache success.json (missing phenix_reconciled_manifest.json) -> fails closed.
            p1_cache_only_out = fake_repo / "runs" / "p1_cache_only"

            def _cache_only_phenix(
                evidence_root: Path, *args: Any, **kwargs: Any
            ) -> dict[str, Any]:
                cache_path = (
                    evidence_root
                    / "phenix"
                    / "cache"
                    / "op"
                    / "bundle"
                    / "success.json"
                )
                ref = self._write_json_file(
                    cache_path,
                    {"returncode": 0, "reusable": True, "artifacts": {}},
                )
                return {
                    "manifest_path": str(cache_path),
                    "manifest_sha256": ref["sha256"],
                }

            with (
                mock.patch.object(
                    onesar_rerun,
                    "run_phenix_rfactor_operation",
                    side_effect=_cache_only_phenix,
                ),
                mock.patch.object(
                    onesar_refmac,
                    "run_refmac_rfactor_operation",
                    side_effect=AssertionError("REFMAC must not run when reconciled manifest is missing"),
                ) as rm_mock2,
            ):
                outcome_cache_only = (
                    onesar_rerun.run_single_subject_rfactor_attempt(
                        p1_cache_only_out,
                        "R4",
                        repo_root=fake_repo,
                        require_no_protstruct_overrides=False,
                    )
                )
                self.assertEqual(rm_mock2.call_count, 0)
            self.assertEqual(outcome_cache_only["status"], "failed")
            self.assertEqual(
                outcome_cache_only["failed_stage"],
                "phenix_reconciled_manifest_binding",
            )
            self.assertFalse(
                (
                    p1_cache_only_out
                    / onesar_rerun.PARENT_COMPLETED_CHECKPOINT_FILENAME
                ).exists()
            )

            # 4. Producer 2 failure (RefmacCollectorError) preserves PHENIX and REFMAC artifacts and skips checkpoint/publish.
            p2_fail_out = fake_repo / "runs" / "p2_fail"

            def _ok_phenix(
                evidence_root: Path, *args: Any, **kwargs: Any
            ) -> dict[str, Any]:
                cache_path = (
                    evidence_root
                    / "phenix"
                    / "cache"
                    / "op"
                    / "bundle"
                    / "success.json"
                )
                c_ref = self._write_json_file(
                    cache_path, {"returncode": 0, "reusable": True}
                )
                rec_path = (
                    evidence_root
                    / "phenix"
                    / "phenix_reconciled_manifest.json"
                )
                rec_payload = {
                    "schema_version": 1,
                    "subject": onesar_rerun.resolve_subject_spec("R4"),
                    "mtz": {
                        "member": onesar_rerun.MTZ_MEMBER,
                        "sha256": onesar_rerun.MTZ_SHA256,
                        "subject_ref": onesar_rerun.MTZ_SUBJECT_REF,
                    },
                    "staged_files": {},
                    "manifest_path": str(cache_path),
                    "manifest_sha256": c_ref["sha256"],
                    "operation_manifest": {"returncode": 0},
                    "reconciliation": {"reconciliation_status": "verified"},
                }
                self._write_json_file(rec_path, rec_payload)
                return rec_payload

            def _failing_refmac(
                evidence_root: Path | str, *args: Any, **kwargs: Any
            ) -> dict[str, Any]:
                ev_path = Path(evidence_root)
                rm_man_path = (
                    ev_path / "refmac" / "refmac_operation_manifest.json"
                )
                rm_diag_path = ev_path / "refmac" / "refmac_diagnostics.json"
                man_ref = self._write_json_file(
                    rm_man_path,
                    {"schema_version": 1, "failed_stage": "refmac_returncode"},
                )
                diag_ref = self._write_json_file(
                    rm_diag_path,
                    {"schema_version": 1, "failed_stage": "refmac_returncode"},
                )
                raise onesar_refmac.RefmacCollectorError(
                    "REFMAC exited with code 7",
                    failed_stage="refmac_returncode",
                    manifest_path=rm_man_path,
                    diagnostics_path=rm_diag_path,
                    returncode=7,
                    manifest_payload={
                        "manifest_json": man_ref,
                        "diagnostics_json": diag_ref,
                    },
                )

            with (
                mock.patch.object(
                    onesar_rerun,
                    "run_phenix_rfactor_operation",
                    side_effect=_ok_phenix,
                ),
                mock.patch.object(
                    onesar_refmac,
                    "run_refmac_rfactor_operation",
                    side_effect=_failing_refmac,
                ),
                mock.patch.object(
                    onesar_records,
                    "publish_retained_rfactor_records",
                    side_effect=AssertionError("Publisher must not run after REFMAC failure"),
                ) as pub_mock3,
            ):
                outcome_p2 = onesar_rerun.run_single_subject_rfactor_attempt(
                    p2_fail_out,
                    "R4",
                    repo_root=fake_repo,
                    require_no_protstruct_overrides=False,
                )
                self.assertEqual(pub_mock3.call_count, 0)
            self.assertEqual(outcome_p2["status"], "failed")
            self.assertEqual(
                outcome_p2["failed_stage"],
                "refmac_rfactor_operation:refmac_returncode",
            )
            self.assertFalse(
                (
                    p2_fail_out
                    / onesar_rerun.PARENT_COMPLETED_CHECKPOINT_FILENAME
                ).exists()
            )
            self.assertIn(
                "phenix_reconciled_manifest_json",
                outcome_p2["phenix_inventory"]["retained_files"],
            )
            self.assertIn(
                "operation_manifest_json",
                outcome_p2["refmac_inventory"]["retained_files"],
            )
            self.assertIn(
                "diagnostics_json",
                outcome_p2["refmac_inventory"]["retained_files"],
            )

    def test_record_layer_exceptions_commit_states_system_exit_and_keyboard_interrupt(
        self,
    ) -> None:
        """Verify SystemExit(0), QdsCompletenessError, KeyboardInterrupt, and committed/unknown commit_state preservation."""
        import onesar_records
        import onesar_refmac
        from qds_emit_contract_v4 import QdsCompletenessError

        with tempfile.TemporaryDirectory() as tmp:
            fake_repo = Path(tmp).resolve(strict=True) / "repo"
            fake_repo.mkdir()

            def _stub_phenix(
                evidence_root: Path, *args: Any, **kwargs: Any
            ) -> dict[str, Any]:
                cache_path = (
                    evidence_root
                    / "phenix"
                    / "cache"
                    / "op"
                    / "bundle"
                    / "success.json"
                )
                c_ref = self._write_json_file(
                    cache_path, {"returncode": 0, "reusable": True}
                )
                rec_path = (
                    evidence_root
                    / "phenix"
                    / "phenix_reconciled_manifest.json"
                )
                rec_payload = {
                    "schema_version": 1,
                    "subject": onesar_rerun.resolve_subject_spec("R4"),
                    "mtz": {
                        "member": onesar_rerun.MTZ_MEMBER,
                        "sha256": onesar_rerun.MTZ_SHA256,
                        "subject_ref": onesar_rerun.MTZ_SUBJECT_REF,
                    },
                    "staged_files": {},
                    "manifest_path": str(cache_path),
                    "manifest_sha256": c_ref["sha256"],
                    "operation_manifest": {"returncode": 0},
                    "reconciliation": {"reconciliation_status": "verified"},
                }
                self._write_json_file(rec_path, rec_payload)
                return rec_payload

            def _stub_refmac(
                evidence_root: Path | str, *args: Any, **kwargs: Any
            ) -> dict[str, Any]:
                ev_path = Path(evidence_root)
                rm_man_path = (
                    ev_path / "refmac" / "refmac_operation_manifest.json"
                )
                rm_payload = {
                    "schema_version": 1,
                    "status": "diagnostic_captured_gates_unproven",
                }
                rm_ref = self._write_json_file(rm_man_path, rm_payload)
                rm_ref.pop("persisted", None)
                out = dict(rm_payload)
                out["manifest_json"] = rm_ref
                return out

            with (
                self._without_protstruct_env_overrides(),
                mock.patch.object(
                    onesar_rerun,
                    "run_phenix_rfactor_operation",
                    side_effect=_stub_phenix,
                ),
                mock.patch.object(
                    onesar_refmac,
                    "run_refmac_rfactor_operation",
                    side_effect=_stub_refmac,
                ),
            ):
                # 1. SystemExit(0) inside record layer is treated as status="refused" and main returns 1 (nonzero).
                sysexit_out = fake_repo / "runs" / "sysexit_zero"
                with mock.patch.object(
                    onesar_records,
                    "publish_retained_rfactor_records",
                    side_effect=SystemExit(0),
                ):
                    rc_sysexit = onesar_rerun.main(
                        [
                            "--subject",
                            "R4",
                            "--family",
                            "rfactors",
                            "--evidence-out",
                            str(sysexit_out),
                            "--repo-root",
                            str(fake_repo),
                        ]
                    )
                self.assertEqual(rc_sysexit, 1)
                sysexit_doc = json.loads(
                    (
                        sysexit_out
                        / onesar_rerun.PARENT_ATTEMPT_OUTCOME_FILENAME
                    ).read_text(encoding="utf-8")
                )
                self.assertEqual(sysexit_doc["status"], "refused")
                self.assertIs(sysexit_doc["published"], False)
                self.assertEqual(
                    sysexit_doc["error"]["system_exit_code"], 0
                )

                # 2. QdsCompletenessError is treated as status="refused" and main returns 1.
                qds_err_out = fake_repo / "runs" / "qds_completeness_err"
                with mock.patch.object(
                    onesar_records,
                    "publish_retained_rfactor_records",
                    side_effect=QdsCompletenessError("missing active tool_ref"),
                ):
                    rc_qds = onesar_rerun.main(
                        [
                            "--subject",
                            "R4",
                            "--family",
                            "rfactors",
                            "--evidence-out",
                            str(qds_err_out),
                            "--repo-root",
                            str(fake_repo),
                        ]
                    )
                self.assertEqual(rc_qds, 1)
                qds_doc = json.loads(
                    (
                        qds_err_out
                        / onesar_rerun.PARENT_ATTEMPT_OUTCOME_FILENAME
                    ).read_text(encoding="utf-8")
                )
                self.assertEqual(qds_doc["status"], "refused")
                self.assertIs(qds_doc["published"], False)

                # 3. Post-commit exception (commit_state="committed") preserves published=True, committed=True
                # without contradictory published=False, while main returns 1 due to unhandled post-commit error.
                committed_err_out = fake_repo / "runs" / "post_commit_err"
                post_commit_exc = RuntimeError(
                    "staging cleanup failed after commit"
                )
                post_commit_exc.commit_state = "committed"  # type: ignore[attr-defined]
                post_commit_exc.committed = True  # type: ignore[attr-defined]
                post_commit_exc.authoring_policy_issued_at = (  # type: ignore[attr-defined]
                    "2026-11-06T23:59:59+00:00"
                )
                post_commit_exc.authoring_outcome = {  # type: ignore[attr-defined]
                    "status": "published",
                    "published": True,
                    "authoring_policy_issued_at": "2026-11-06T23:59:59+00:00",
                }
                with mock.patch.object(
                    onesar_records,
                    "publish_retained_rfactor_records",
                    side_effect=post_commit_exc,
                ):
                    rc_post_commit = onesar_rerun.main(
                        [
                            "--subject",
                            "R4",
                            "--family",
                            "rfactors",
                            "--evidence-out",
                            str(committed_err_out),
                            "--repo-root",
                            str(fake_repo),
                        ]
                    )
                self.assertEqual(rc_post_commit, 1)
                committed_doc = json.loads(
                    (
                        committed_err_out
                        / onesar_rerun.PARENT_ATTEMPT_OUTCOME_FILENAME
                    ).read_text(encoding="utf-8")
                )
                self.assertEqual(committed_doc["commit_state"], "committed")
                self.assertIs(committed_doc["committed"], True)
                self.assertIs(committed_doc["published"], True)
                self.assertEqual(
                    committed_doc["authoring_policy_issued_at"],
                    "2026-11-06T23:59:59+00:00",
                )
                self.assertIsNotNone(committed_doc["error"])

                # 4. Indeterminate commit state (commit_state="unknown") preserves published=None, committed=None.
                unknown_err_out = fake_repo / "runs" / "unknown_commit_err"
                unknown_exc = OSError("os.link EIO with lost provisional inode")
                unknown_exc.commit_state = "unknown"  # type: ignore[attr-defined]
                unknown_exc.committed = None  # type: ignore[attr-defined]
                unknown_exc.provisional_outcome_path = str(  # type: ignore[attr-defined]
                    unknown_err_out
                    / "authoring_outcomes"
                    / "authoring_outcome_0001.json.provisional.txt"
                )
                with mock.patch.object(
                    onesar_records,
                    "publish_retained_rfactor_records",
                    side_effect=unknown_exc,
                ):
                    rc_unknown = onesar_rerun.main(
                        [
                            "--subject",
                            "R4",
                            "--family",
                            "rfactors",
                            "--evidence-out",
                            str(unknown_err_out),
                            "--repo-root",
                            str(fake_repo),
                        ]
                    )
                self.assertEqual(rc_unknown, 1)
                unknown_doc = json.loads(
                    (
                        unknown_err_out
                        / onesar_rerun.PARENT_ATTEMPT_OUTCOME_FILENAME
                    ).read_text(encoding="utf-8")
                )
                self.assertEqual(unknown_doc["commit_state"], "unknown")
                self.assertIsNone(unknown_doc["committed"])
                self.assertIsNone(unknown_doc["published"])
                self.assertEqual(unknown_doc["status"], "unknown")
                self.assertIsNotNone(unknown_doc["provisional_outcome_path"])

                # 5. KeyboardInterrupt writes status="interrupted" to parent_attempt_outcome.json and re-raises.
                kbd_out = fake_repo / "runs" / "kbd_interrupt"
                with mock.patch.object(
                    onesar_records,
                    "publish_retained_rfactor_records",
                    side_effect=KeyboardInterrupt("simulated Ctrl-C"),
                ):
                    with self.assertRaises(KeyboardInterrupt):
                        onesar_rerun.run_single_subject_rfactor_attempt(
                            kbd_out,
                            "R4",
                            repo_root=fake_repo,
                            require_no_protstruct_overrides=False,
                        )
                kbd_doc = json.loads(
                    (
                        kbd_out / onesar_rerun.PARENT_ATTEMPT_OUTCOME_FILENAME
                    ).read_text(encoding="utf-8")
                )
                self.assertEqual(kbd_doc["status"], "interrupted")
                self.assertIs(kbd_doc["published"], False)

    def test_finalization_outcome_persistence_and_inventory_eio_resilience(
        self,
    ) -> None:
        """Verify #1093 outcome-write failure preservation, #1094 inventory EIO resilience, and #1095 REFMAC manifest binding."""
        import errno
        import io
        import onesar_records
        import onesar_refmac
        from qds_emit_contract_v4 import QdsCompletenessError

        with tempfile.TemporaryDirectory() as tmp:
            fake_repo = Path(tmp).resolve(strict=True) / "repo"
            fake_repo.mkdir()

            def _stub_phenix(
                evidence_root: Path, *args: Any, **kwargs: Any
            ) -> dict[str, Any]:
                cache_path = (
                    evidence_root
                    / "phenix"
                    / "cache"
                    / "op"
                    / "bundle"
                    / "success.json"
                )
                c_ref = self._write_json_file(
                    cache_path, {"returncode": 0, "reusable": True}
                )
                rec_path = (
                    evidence_root
                    / "phenix"
                    / "phenix_reconciled_manifest.json"
                )
                rec_payload = {
                    "schema_version": 1,
                    "subject": onesar_rerun.resolve_subject_spec("R4"),
                    "mtz": {
                        "member": onesar_rerun.MTZ_MEMBER,
                        "sha256": onesar_rerun.MTZ_SHA256,
                        "subject_ref": onesar_rerun.MTZ_SUBJECT_REF,
                    },
                    "staged_files": {},
                    "manifest_path": str(cache_path),
                    "manifest_sha256": c_ref["sha256"],
                    "operation_manifest": {"returncode": 0},
                    "reconciliation": {"reconciliation_status": "verified"},
                }
                self._write_json_file(rec_path, rec_payload)
                return rec_payload

            def _stub_refmac(
                evidence_root: Path | str, *args: Any, **kwargs: Any
            ) -> dict[str, Any]:
                ev_path = Path(evidence_root)
                rm_man_path = (
                    ev_path / "refmac" / "refmac_operation_manifest.json"
                )
                rm_payload = {
                    "schema_version": 1,
                    "status": "diagnostic_captured_gates_unproven",
                }
                rm_ref = self._write_json_file(rm_man_path, rm_payload)
                rm_ref.pop("persisted", None)
                rm_ref["is_fallback"] = True
                rm_ref["fallback_anchor_dir"] = str(ev_path / "refmac")
                out = dict(rm_payload)
                out["manifest_json"] = rm_ref
                return out

            # Direct #1095 check: _bind_refmac_operation_manifest_reference accepts onesar_refmac
            # manifest_json without "persisted", derives persisted=True, and rejects persisted=False.
            rm_bind_root = fake_repo / "runs" / "rm_bind_unit" / "refmac"
            rm_bind_result = _stub_refmac(rm_bind_root)
            self.assertNotIn("persisted", rm_bind_result["manifest_json"])
            bound_rm_ref = onesar_rerun._bind_refmac_operation_manifest_reference(
                rm_bind_root, rm_bind_result
            )
            self.assertIs(bound_rm_ref["persisted"], True)
            self.assertIs(bound_rm_ref["is_fallback"], True)
            bad_rm_result = copy.deepcopy(rm_bind_result)
            bad_rm_result["manifest_json"]["persisted"] = False
            with self.assertRaisesRegex(
                ValueError, "REFMAC manifest_json reference is not persisted"
            ):
                onesar_rerun._bind_refmac_operation_manifest_reference(
                    rm_bind_root, bad_rm_result
                )

            # Mutate the no-"persisted" rm_bind_result to verify real disk revalidation:
            # (i) same-length valid JSON byte edit without refreshing digest (restored afterward),
            # (ii) separate size-only mismatch, and (iii) unsafe outside-root and symlink paths.
            rm_manifest_disk_path = Path(
                str(rm_bind_result["manifest_json"]["path"])
            )
            orig_rm_manifest_bytes = rm_manifest_disk_path.read_bytes()
            same_len_tampered_bytes = orig_rm_manifest_bytes.replace(
                b'"schema_version": 1', b'"schema_version": 2', 1
            )
            self.assertEqual(
                len(same_len_tampered_bytes), len(orig_rm_manifest_bytes)
            )
            self.assertNotEqual(
                same_len_tampered_bytes, orig_rm_manifest_bytes
            )
            try:
                rm_manifest_disk_path.write_bytes(same_len_tampered_bytes)
                self.assertNotIn("persisted", rm_bind_result["manifest_json"])
                with self.assertRaisesRegex(
                    ValueError,
                    "REFMAC operation manifest on-disk digest/size mismatch",
                ):
                    onesar_rerun._bind_refmac_operation_manifest_reference(
                        rm_bind_root, rm_bind_result
                    )
            finally:
                rm_manifest_disk_path.write_bytes(orig_rm_manifest_bytes)
            self.assertEqual(
                rm_manifest_disk_path.read_bytes(), orig_rm_manifest_bytes
            )
            self.assertEqual(
                onesar_rerun._bind_refmac_operation_manifest_reference(
                    rm_bind_root, rm_bind_result
                ),
                bound_rm_ref,
            )

            size_mismatch_rm_result = copy.deepcopy(rm_bind_result)
            self.assertNotIn(
                "persisted", size_mismatch_rm_result["manifest_json"]
            )
            size_mismatch_rm_result["manifest_json"]["size_bytes"] = (
                int(rm_bind_result["manifest_json"]["size_bytes"]) + 1
            )
            with self.assertRaisesRegex(
                ValueError,
                "REFMAC operation manifest on-disk digest/size mismatch",
            ):
                onesar_rerun._bind_refmac_operation_manifest_reference(
                    rm_bind_root, size_mismatch_rm_result
                )

            outside_rm_manifest_path = (
                fake_repo / "runs" / "outside_refmac_manifest.json"
            )
            outside_rm_manifest_path.write_bytes(orig_rm_manifest_bytes)
            outside_rm_result = copy.deepcopy(rm_bind_result)
            self.assertNotIn("persisted", outside_rm_result["manifest_json"])
            outside_rm_result["manifest_json"]["path"] = str(
                outside_rm_manifest_path
            )
            with self.assertRaisesRegex(
                FileNotFoundError,
                "REFMAC operation manifest is missing or outside child root",
            ):
                onesar_rerun._bind_refmac_operation_manifest_reference(
                    rm_bind_root, outside_rm_result
                )

            symlink_rm_manifest_path = (
                rm_bind_root / "refmac" / "symlink_operation_manifest.json"
            )
            symlink_rm_manifest_path.symlink_to(rm_manifest_disk_path)
            symlink_rm_result = copy.deepcopy(rm_bind_result)
            self.assertNotIn("persisted", symlink_rm_result["manifest_json"])
            symlink_rm_result["manifest_json"]["path"] = str(
                symlink_rm_manifest_path
            )
            with self.assertRaisesRegex(
                FileNotFoundError,
                "REFMAC operation manifest is missing or outside child root",
            ):
                onesar_rerun._bind_refmac_operation_manifest_reference(
                    rm_bind_root, symlink_rm_result
                )
            self.assertEqual(
                rm_manifest_disk_path.read_bytes(), orig_rm_manifest_bytes
            )
            self.assertEqual(
                onesar_rerun._bind_refmac_operation_manifest_reference(
                    rm_bind_root, rm_bind_result
                ),
                bound_rm_ref,
            )

            real_write_exclusive = onesar_rerun._write_exclusive_parent_json_record

            def _fail_only_outcome_write(
                payload: Mapping[str, Any],
                target_path: Path,
                *,
                parent_root: Path,
            ) -> dict[str, Any]:
                if (
                    target_path.name
                    == onesar_rerun.PARENT_ATTEMPT_OUTCOME_FILENAME
                ):
                    raise PermissionError(
                        errno.EACCES,
                        "simulated parent_attempt_outcome.json write failure",
                        str(target_path),
                    )
                return real_write_exclusive(
                    payload, target_path, parent_root=parent_root
                )

            # 1a. #1093: Ordinary producer failure + outcome write failure preserves original exception and attaches state.
            p1_write_fail_out = fake_repo / "runs" / "p1_outcome_write_fail"
            orig_p1_exc = RuntimeError("simulated phenix producer failure")
            with (
                self._without_protstruct_env_overrides(),
                mock.patch.object(
                    onesar_rerun,
                    "run_phenix_rfactor_operation",
                    side_effect=orig_p1_exc,
                ),
                mock.patch.object(
                    onesar_rerun,
                    "_write_exclusive_parent_json_record",
                    side_effect=_fail_only_outcome_write,
                ),
            ):
                with self.assertRaises(RuntimeError) as cm_p1:
                    onesar_rerun.run_single_subject_rfactor_attempt(
                        p1_write_fail_out,
                        "R4",
                        repo_root=fake_repo,
                        require_no_protstruct_overrides=False,
                    )
            self.assertIs(cm_p1.exception, orig_p1_exc)
            self.assertEqual(
                getattr(cm_p1.exception, "failed_stage", None),
                "phenix_rfactor_operation",
            )
            self.assertEqual(
                getattr(cm_p1.exception, "commit_state", None), "not_committed"
            )
            self.assertIs(getattr(cm_p1.exception, "committed", None), False)
            self.assertIs(getattr(cm_p1.exception, "published", None), False)
            p1_attached = getattr(cm_p1.exception, "attempt_outcome", None)
            self.assertIsInstance(p1_attached, Mapping)
            self.assertEqual(p1_attached["status"], "failed")
            self.assertIsNone(p1_attached["outcome_record_reference"])
            self.assertEqual(
                p1_attached["outcome_persistence_error"]["exception_type"],
                "PermissionError",
            )
            self.assertEqual(
                p1_attached["outcome_persistence_error"]["errno"],
                errno.EACCES,
            )
            self.assertTrue(
                any(
                    "parent_attempt_outcome_persistence" in n
                    for n in getattr(cm_p1.exception, "__notes__", ())
                )
            )

            # 1b. #1093: Post-admission ValueError + outcome write failure via main() exits 1 (not 2 rejected_pre_admission).
            val_write_fail_out = fake_repo / "runs" / "val_outcome_write_fail"
            stderr_val = io.StringIO()
            with (
                self._without_protstruct_env_overrides(),
                mock.patch.object(
                    onesar_rerun,
                    "run_phenix_rfactor_operation",
                    side_effect=ValueError("post-admission producer ValueError"),
                ),
                mock.patch.object(
                    onesar_rerun,
                    "_write_exclusive_parent_json_record",
                    side_effect=_fail_only_outcome_write,
                ),
                mock.patch.object(sys, "stderr", stderr_val),
            ):
                rc_val = onesar_rerun.main(
                    [
                        "--subject",
                        "R4",
                        "--family",
                        "rfactors",
                        "--evidence-out",
                        str(val_write_fail_out),
                        "--repo-root",
                        str(fake_repo),
                    ]
                )
            self.assertEqual(rc_val, 1)
            val_summary = json.loads(stderr_val.getvalue())
            self.assertEqual(val_summary["status"], "failed")
            self.assertEqual(
                val_summary["failed_stage"], "phenix_rfactor_operation"
            )
            self.assertIsNone(val_summary["outcome_record_path"])
            self.assertEqual(
                val_summary["outcome_persistence_error"]["exception_type"],
                "PermissionError",
            )

            # 1b-ii. #1093: Stored SystemExit(0) and QdsCompletenessError + outcome write failure
            # across both run_single_subject_rfactor_attempt and main() (never process success).
            sysexit_write_fail_out = (
                fake_repo / "runs" / "sysexit_outcome_write_fail"
            )
            orig_sysexit_exc = SystemExit(0)
            with (
                self._without_protstruct_env_overrides(),
                mock.patch.object(
                    onesar_rerun,
                    "run_phenix_rfactor_operation",
                    side_effect=_stub_phenix,
                ),
                mock.patch.object(
                    onesar_refmac,
                    "run_refmac_rfactor_operation",
                    side_effect=_stub_refmac,
                ),
                mock.patch.object(
                    onesar_records,
                    "publish_retained_rfactor_records",
                    side_effect=orig_sysexit_exc,
                ),
                mock.patch.object(
                    onesar_rerun,
                    "_write_exclusive_parent_json_record",
                    side_effect=_fail_only_outcome_write,
                ),
            ):
                with self.assertRaises(SystemExit) as cm_sysexit:
                    onesar_rerun.run_single_subject_rfactor_attempt(
                        sysexit_write_fail_out,
                        "R4",
                        repo_root=fake_repo,
                        require_no_protstruct_overrides=False,
                    )
            self.assertIs(cm_sysexit.exception, orig_sysexit_exc)
            self.assertIs(type(cm_sysexit.exception), SystemExit)
            self.assertEqual(cm_sysexit.exception.code, 0)
            self.assertEqual(
                getattr(cm_sysexit.exception, "status", None), "refused"
            )
            self.assertEqual(
                getattr(cm_sysexit.exception, "failed_stage", None),
                "publish_retained_rfactor_records",
            )
            self.assertEqual(
                getattr(cm_sysexit.exception, "commit_state", None),
                "not_committed",
            )
            self.assertIs(
                getattr(cm_sysexit.exception, "committed", None), False
            )
            self.assertIs(
                getattr(cm_sysexit.exception, "published", None), False
            )
            sysexit_attached = getattr(
                cm_sysexit.exception, "attempt_outcome", None
            )
            self.assertIsInstance(sysexit_attached, Mapping)
            self.assertEqual(sysexit_attached["status"], "refused")
            self.assertEqual(
                sysexit_attached["failed_stage"],
                "publish_retained_rfactor_records",
            )
            self.assertEqual(sysexit_attached["commit_state"], "not_committed")
            self.assertIs(sysexit_attached["committed"], False)
            self.assertIs(sysexit_attached["published"], False)
            self.assertEqual(sysexit_attached["error"]["system_exit_code"], 0)
            self.assertIsNone(sysexit_attached["outcome_record_reference"])
            self.assertEqual(
                sysexit_attached["outcome_persistence_error"]["exception_type"],
                "PermissionError",
            )
            self.assertEqual(
                sysexit_attached["outcome_persistence_error"]["errno"],
                errno.EACCES,
            )

            sysexit_cli_write_fail_out = (
                fake_repo / "runs" / "sysexit_cli_outcome_write_fail"
            )
            orig_sysexit_cli_exc = SystemExit(0)
            stderr_sysexit_cli = io.StringIO()
            with (
                self._without_protstruct_env_overrides(),
                mock.patch.object(
                    onesar_rerun,
                    "run_phenix_rfactor_operation",
                    side_effect=_stub_phenix,
                ),
                mock.patch.object(
                    onesar_refmac,
                    "run_refmac_rfactor_operation",
                    side_effect=_stub_refmac,
                ),
                mock.patch.object(
                    onesar_records,
                    "publish_retained_rfactor_records",
                    side_effect=orig_sysexit_cli_exc,
                ),
                mock.patch.object(
                    onesar_rerun,
                    "_write_exclusive_parent_json_record",
                    side_effect=_fail_only_outcome_write,
                ),
                mock.patch.object(sys, "stderr", stderr_sysexit_cli),
            ):
                rc_sysexit_cli = onesar_rerun.main(
                    [
                        "--subject",
                        "R4",
                        "--family",
                        "rfactors",
                        "--evidence-out",
                        str(sysexit_cli_write_fail_out),
                        "--repo-root",
                        str(fake_repo),
                    ]
                )
            self.assertEqual(rc_sysexit_cli, 1)
            sysexit_cli_summary = json.loads(stderr_sysexit_cli.getvalue())
            self.assertEqual(sysexit_cli_summary["status"], "refused")
            self.assertIs(sysexit_cli_summary["published"], False)
            self.assertEqual(
                sysexit_cli_summary["commit_state"], "not_committed"
            )
            self.assertIs(sysexit_cli_summary["committed"], False)
            self.assertEqual(
                sysexit_cli_summary["failed_stage"],
                "publish_retained_rfactor_records",
            )
            self.assertIsNone(sysexit_cli_summary["outcome_record_path"])
            self.assertEqual(
                sysexit_cli_summary["outcome_persistence_error"][
                    "exception_type"
                ],
                "PermissionError",
            )
            self.assertEqual(
                sysexit_cli_summary["outcome_persistence_error"]["errno"],
                errno.EACCES,
            )

            qds_write_fail_out = (
                fake_repo / "runs" / "qds_outcome_write_fail"
            )
            orig_qds_exc = QdsCompletenessError(
                "missing active tool_ref before write fail"
            )
            with (
                self._without_protstruct_env_overrides(),
                mock.patch.object(
                    onesar_rerun,
                    "run_phenix_rfactor_operation",
                    side_effect=_stub_phenix,
                ),
                mock.patch.object(
                    onesar_refmac,
                    "run_refmac_rfactor_operation",
                    side_effect=_stub_refmac,
                ),
                mock.patch.object(
                    onesar_records,
                    "publish_retained_rfactor_records",
                    side_effect=orig_qds_exc,
                ),
                mock.patch.object(
                    onesar_rerun,
                    "_write_exclusive_parent_json_record",
                    side_effect=_fail_only_outcome_write,
                ),
            ):
                with self.assertRaises(QdsCompletenessError) as cm_qds:
                    onesar_rerun.run_single_subject_rfactor_attempt(
                        qds_write_fail_out,
                        "R4",
                        repo_root=fake_repo,
                        require_no_protstruct_overrides=False,
                    )
            self.assertIs(cm_qds.exception, orig_qds_exc)
            self.assertIs(type(cm_qds.exception), QdsCompletenessError)
            self.assertEqual(
                getattr(cm_qds.exception, "status", None), "refused"
            )
            self.assertEqual(
                getattr(cm_qds.exception, "failed_stage", None),
                "publish_retained_rfactor_records",
            )
            self.assertEqual(
                getattr(cm_qds.exception, "commit_state", None), "not_committed"
            )
            self.assertIs(getattr(cm_qds.exception, "committed", None), False)
            self.assertIs(getattr(cm_qds.exception, "published", None), False)
            qds_attached = getattr(cm_qds.exception, "attempt_outcome", None)
            self.assertIsInstance(qds_attached, Mapping)
            self.assertEqual(qds_attached["status"], "refused")
            self.assertEqual(
                qds_attached["failed_stage"],
                "publish_retained_rfactor_records",
            )
            self.assertEqual(qds_attached["commit_state"], "not_committed")
            self.assertIs(qds_attached["committed"], False)
            self.assertIs(qds_attached["published"], False)
            self.assertIsNone(qds_attached["outcome_record_reference"])
            self.assertEqual(
                qds_attached["outcome_persistence_error"]["exception_type"],
                "PermissionError",
            )
            self.assertEqual(
                qds_attached["outcome_persistence_error"]["errno"],
                errno.EACCES,
            )

            qds_cli_write_fail_out = (
                fake_repo / "runs" / "qds_cli_outcome_write_fail"
            )
            orig_qds_cli_exc = QdsCompletenessError(
                "missing active tool_ref cli before write fail"
            )
            stderr_qds_cli = io.StringIO()
            with (
                self._without_protstruct_env_overrides(),
                mock.patch.object(
                    onesar_rerun,
                    "run_phenix_rfactor_operation",
                    side_effect=_stub_phenix,
                ),
                mock.patch.object(
                    onesar_refmac,
                    "run_refmac_rfactor_operation",
                    side_effect=_stub_refmac,
                ),
                mock.patch.object(
                    onesar_records,
                    "publish_retained_rfactor_records",
                    side_effect=orig_qds_cli_exc,
                ),
                mock.patch.object(
                    onesar_rerun,
                    "_write_exclusive_parent_json_record",
                    side_effect=_fail_only_outcome_write,
                ),
                mock.patch.object(sys, "stderr", stderr_qds_cli),
            ):
                rc_qds_cli = onesar_rerun.main(
                    [
                        "--subject",
                        "R4",
                        "--family",
                        "rfactors",
                        "--evidence-out",
                        str(qds_cli_write_fail_out),
                        "--repo-root",
                        str(fake_repo),
                    ]
                )
            self.assertEqual(rc_qds_cli, 1)
            qds_cli_summary = json.loads(stderr_qds_cli.getvalue())
            self.assertEqual(qds_cli_summary["status"], "refused")
            self.assertIs(qds_cli_summary["published"], False)
            self.assertEqual(qds_cli_summary["commit_state"], "not_committed")
            self.assertIs(qds_cli_summary["committed"], False)
            self.assertEqual(
                qds_cli_summary["failed_stage"],
                "publish_retained_rfactor_records",
            )
            self.assertIsNone(qds_cli_summary["outcome_record_path"])
            self.assertEqual(
                qds_cli_summary["outcome_persistence_error"]["exception_type"],
                "PermissionError",
            )
            self.assertEqual(
                qds_cli_summary["outcome_persistence_error"]["errno"],
                errno.EACCES,
            )

            # 1c. #1093: Public scientific refusal + outcome write failure preserves RefmacScientificAdmissionRefusedError.
            refusal_write_fail_out = (
                fake_repo / "runs" / "refusal_outcome_write_fail"
            )
            refusal_exc = onesar_records.RefmacScientificAdmissionRefusedError(
                "simulated public scientific refusal",
                refusal_record={
                    "producer": "refmac",
                    "subject_id": "R4",
                    "integrity_verified": True,
                    "scientific_proof_established": False,
                    "unknown_native_premises": {},
                    "refusal_reasons": ["unproven"],
                    "unsupported_proof_claims": [],
                    "verified_references": {},
                },
            )
            refusal_exc.authoring_outcome = {  # type: ignore[attr-defined]
                "status": "refused",
                "published": False,
                "failed_stage": "refmac_retained_verification",
                "outcome_path": str(
                    refusal_write_fail_out
                    / "authoring_outcomes"
                    / "authoring_outcome_0001.json"
                ),
            }
            refusal_exc.authoring_outcome_path = refusal_exc.authoring_outcome[  # type: ignore[attr-defined]
                "outcome_path"
            ]
            with (
                self._without_protstruct_env_overrides(),
                mock.patch.object(
                    onesar_rerun,
                    "run_phenix_rfactor_operation",
                    side_effect=_stub_phenix,
                ),
                mock.patch.object(
                    onesar_refmac,
                    "run_refmac_rfactor_operation",
                    side_effect=_stub_refmac,
                ),
                mock.patch.object(
                    onesar_records,
                    "publish_retained_rfactor_records",
                    side_effect=refusal_exc,
                ),
                mock.patch.object(
                    onesar_rerun,
                    "_write_exclusive_parent_json_record",
                    side_effect=_fail_only_outcome_write,
                ),
            ):
                with self.assertRaises(
                    onesar_records.RefmacScientificAdmissionRefusedError
                ) as cm_ref:
                    onesar_rerun.run_single_subject_rfactor_attempt(
                        refusal_write_fail_out,
                        "R4",
                        repo_root=fake_repo,
                        require_no_protstruct_overrides=False,
                    )
            self.assertIs(cm_ref.exception, refusal_exc)
            self.assertEqual(
                getattr(cm_ref.exception, "failed_stage", None),
                "refmac_retained_verification",
            )
            self.assertEqual(
                getattr(cm_ref.exception, "commit_state", None), "not_committed"
            )
            self.assertIs(getattr(cm_ref.exception, "committed", None), False)
            ref_attached = getattr(cm_ref.exception, "attempt_outcome", None)
            self.assertIsInstance(ref_attached, Mapping)
            self.assertEqual(ref_attached["status"], "refused")
            self.assertIsNone(ref_attached["outcome_record_reference"])
            self.assertEqual(
                ref_attached["scientific_refusal"]["integrity_verified"], True
            )

            # 1d. #1093: Post-commit publisher exception (commit_state="committed") + outcome write failure.
            committed_write_fail_out = (
                fake_repo / "runs" / "committed_outcome_write_fail"
            )
            committed_pub_exc = RuntimeError(
                "post-commit cleanup error before parent outcome write"
            )
            committed_pub_exc.commit_state = "committed"  # type: ignore[attr-defined]
            committed_pub_exc.committed = True  # type: ignore[attr-defined]
            committed_pub_exc.authoring_policy_issued_at = (  # type: ignore[attr-defined]
                "2026-11-06T23:59:59+00:00"
            )
            committed_pub_exc.authoring_outcome = {  # type: ignore[attr-defined]
                "status": "published",
                "published": True,
                "commit_state": "committed",
                "authoring_policy_issued_at": "2026-11-06T23:59:59+00:00",
                "outcome_path": str(
                    committed_write_fail_out
                    / "authoring_outcomes"
                    / "authoring_outcome_0001.json"
                ),
            }
            committed_pub_exc.authoring_outcome_path = (  # type: ignore[attr-defined]
                committed_pub_exc.authoring_outcome["outcome_path"]
            )
            with (
                self._without_protstruct_env_overrides(),
                mock.patch.object(
                    onesar_rerun,
                    "run_phenix_rfactor_operation",
                    side_effect=_stub_phenix,
                ),
                mock.patch.object(
                    onesar_refmac,
                    "run_refmac_rfactor_operation",
                    side_effect=_stub_refmac,
                ),
                mock.patch.object(
                    onesar_records,
                    "publish_retained_rfactor_records",
                    side_effect=committed_pub_exc,
                ),
                mock.patch.object(
                    onesar_rerun,
                    "_write_exclusive_parent_json_record",
                    side_effect=_fail_only_outcome_write,
                ),
            ):
                with self.assertRaises(RuntimeError) as cm_comm:
                    onesar_rerun.run_single_subject_rfactor_attempt(
                        committed_write_fail_out,
                        "R4",
                        repo_root=fake_repo,
                        require_no_protstruct_overrides=False,
                    )
            self.assertIs(cm_comm.exception, committed_pub_exc)
            self.assertEqual(
                getattr(cm_comm.exception, "commit_state", None), "committed"
            )
            self.assertIs(getattr(cm_comm.exception, "committed", None), True)
            self.assertIs(getattr(cm_comm.exception, "published", None), True)
            comm_attached = getattr(cm_comm.exception, "attempt_outcome", None)
            self.assertIsInstance(comm_attached, Mapping)
            self.assertEqual(comm_attached["commit_state"], "committed")
            self.assertIs(comm_attached["committed"], True)
            self.assertIs(comm_attached["published"], True)
            self.assertIsNone(comm_attached["outcome_record_reference"])
            self.assertEqual(
                comm_attached["outcome_persistence_error"]["exception_type"],
                "PermissionError",
            )

            # 1e. #1093: Indeterminate commit state (commit_state="unknown") + outcome write failure.
            unknown_write_fail_out = (
                fake_repo / "runs" / "unknown_outcome_write_fail"
            )
            unknown_pub_exc = OSError("os.link EIO with indeterminate commit")
            unknown_pub_exc.commit_state = "unknown"  # type: ignore[attr-defined]
            unknown_pub_exc.committed = None  # type: ignore[attr-defined]
            unknown_pub_exc.provisional_outcome_path = str(  # type: ignore[attr-defined]
                unknown_write_fail_out
                / "authoring_outcomes"
                / "authoring_outcome_0001.json.provisional.txt"
            )
            with (
                self._without_protstruct_env_overrides(),
                mock.patch.object(
                    onesar_rerun,
                    "run_phenix_rfactor_operation",
                    side_effect=_stub_phenix,
                ),
                mock.patch.object(
                    onesar_refmac,
                    "run_refmac_rfactor_operation",
                    side_effect=_stub_refmac,
                ),
                mock.patch.object(
                    onesar_records,
                    "publish_retained_rfactor_records",
                    side_effect=unknown_pub_exc,
                ),
                mock.patch.object(
                    onesar_rerun,
                    "_write_exclusive_parent_json_record",
                    side_effect=_fail_only_outcome_write,
                ),
            ):
                with self.assertRaises(OSError) as cm_unk:
                    onesar_rerun.run_single_subject_rfactor_attempt(
                        unknown_write_fail_out,
                        "R4",
                        repo_root=fake_repo,
                        require_no_protstruct_overrides=False,
                    )
            self.assertIs(cm_unk.exception, unknown_pub_exc)
            self.assertEqual(
                getattr(cm_unk.exception, "commit_state", None), "unknown"
            )
            self.assertIsNone(getattr(cm_unk.exception, "committed", None))
            self.assertIsNone(getattr(cm_unk.exception, "published", None))
            unk_attached = getattr(cm_unk.exception, "attempt_outcome", None)
            self.assertIsInstance(unk_attached, Mapping)
            self.assertEqual(unk_attached["status"], "unknown")
            self.assertIsNone(unk_attached["outcome_record_reference"])

            # 1f. #1093: No-exception committed return where a foreign file pre-exists at parent_attempt_outcome.json.
            foreign_outcome_out = (
                fake_repo / "runs" / "foreign_outcome_collision"
            )
            foreign_bytes = b'{"foreign": "do_not_clobber"}\n'

            def _committed_pub_creating_foreign_outcome(
                admitted_root: Path | str, *args: Any, **kwargs: Any
            ) -> dict[str, Any]:
                foreign_target = (
                    Path(admitted_root)
                    / onesar_rerun.PARENT_ATTEMPT_OUTCOME_FILENAME
                )
                foreign_target.write_bytes(foreign_bytes)
                return {
                    "status": "published",
                    "published": True,
                    "commit_state": "committed",
                    "committed": True,
                    "issued_at": "2026-11-06T23:59:59+00:00",
                    "authoring_outcome_path": str(
                        Path(admitted_root)
                        / "authoring_outcomes"
                        / "authoring_outcome_0001.json"
                    ),
                    "authoring_outcome": {
                        "status": "published",
                        "published": True,
                        "commit_state": "committed",
                        "authoring_policy_issued_at": "2026-11-06T23:59:59+00:00",
                        "outcome_path": str(
                            Path(admitted_root)
                            / "authoring_outcomes"
                            / "authoring_outcome_0001.json"
                        ),
                    },
                }

            stderr_foreign = io.StringIO()
            with (
                self._without_protstruct_env_overrides(),
                mock.patch.object(
                    onesar_rerun,
                    "run_phenix_rfactor_operation",
                    side_effect=_stub_phenix,
                ),
                mock.patch.object(
                    onesar_refmac,
                    "run_refmac_rfactor_operation",
                    side_effect=_stub_refmac,
                ),
                mock.patch.object(
                    onesar_records,
                    "publish_retained_rfactor_records",
                    side_effect=_committed_pub_creating_foreign_outcome,
                ),
                mock.patch.object(sys, "stderr", stderr_foreign),
            ):
                rc_foreign = onesar_rerun.main(
                    [
                        "--subject",
                        "R4",
                        "--family",
                        "rfactors",
                        "--evidence-out",
                        str(foreign_outcome_out),
                        "--repo-root",
                        str(fake_repo),
                    ]
                )
            self.assertEqual(rc_foreign, 1)
            self.assertEqual(
                (
                    foreign_outcome_out
                    / onesar_rerun.PARENT_ATTEMPT_OUTCOME_FILENAME
                ).read_bytes(),
                foreign_bytes,
            )
            foreign_summary = json.loads(stderr_foreign.getvalue())
            self.assertEqual(foreign_summary["status"], "published")
            self.assertIs(foreign_summary["published"], True)
            self.assertEqual(foreign_summary["commit_state"], "committed")
            self.assertIs(foreign_summary["committed"], True)
            self.assertEqual(
                foreign_summary["failed_stage"],
                "parent_attempt_outcome_persistence",
            )
            self.assertIsNone(foreign_summary["outcome_record_path"])
            self.assertEqual(
                foreign_summary["outcome_persistence_error"]["exception_type"],
                "FileExistsError",
            )

            # 1g. #1093: KeyboardInterrupt + outcome write failure preserves KeyboardInterrupt identity and attaches outcome.
            kbd_write_fail_out = fake_repo / "runs" / "kbd_outcome_write_fail"
            orig_kbd_exc = KeyboardInterrupt("simulated Ctrl-C before write fail")
            with (
                self._without_protstruct_env_overrides(),
                mock.patch.object(
                    onesar_rerun,
                    "run_phenix_rfactor_operation",
                    side_effect=_stub_phenix,
                ),
                mock.patch.object(
                    onesar_refmac,
                    "run_refmac_rfactor_operation",
                    side_effect=_stub_refmac,
                ),
                mock.patch.object(
                    onesar_records,
                    "publish_retained_rfactor_records",
                    side_effect=orig_kbd_exc,
                ),
                mock.patch.object(
                    onesar_rerun,
                    "_write_exclusive_parent_json_record",
                    side_effect=_fail_only_outcome_write,
                ),
            ):
                with self.assertRaises(KeyboardInterrupt) as cm_kbd:
                    onesar_rerun.run_single_subject_rfactor_attempt(
                        kbd_write_fail_out,
                        "R4",
                        repo_root=fake_repo,
                        require_no_protstruct_overrides=False,
                    )
            self.assertIs(cm_kbd.exception, orig_kbd_exc)
            kbd_attached = getattr(cm_kbd.exception, "attempt_outcome", None)
            self.assertIsInstance(kbd_attached, Mapping)
            self.assertEqual(kbd_attached["status"], "interrupted")
            self.assertIsNone(kbd_attached["outcome_record_reference"])
            self.assertEqual(
                kbd_attached["outcome_persistence_error"]["exception_type"],
                "PermissionError",
            )

            # 2a. #1094: Child-root OSError(errno.EIO) after ordinary producer failure writes parent_attempt_outcome.json
            # with evidence_root_exists=None and inventory_status="unavailable" (never confirmed absence False).
            eio_fail_out = fake_repo / "runs" / "child_inventory_eio_fail"
            orig_eio_producer_exc = RuntimeError(
                "simulated phenix failure before child EIO"
            )
            real_is_symlink = Path.is_symlink

            def _eio_on_child_roots(path_obj: Path) -> bool:
                if path_obj in (
                    eio_fail_out / "phenix",
                    eio_fail_out / "refmac",
                    eio_kbd_out / "phenix",
                    eio_kbd_out / "refmac",
                ):
                    raise OSError(
                        errno.EIO, "simulated child stat I/O failure"
                    )
                return real_is_symlink(path_obj)

            eio_kbd_out = fake_repo / "runs" / "child_inventory_eio_kbd"
            with (
                self._without_protstruct_env_overrides(),
                mock.patch.object(
                    onesar_rerun,
                    "run_phenix_rfactor_operation",
                    side_effect=orig_eio_producer_exc,
                ),
                mock.patch.object(
                    Path,
                    "is_symlink",
                    autospec=True,
                    side_effect=_eio_on_child_roots,
                ),
            ):
                outcome_eio = onesar_rerun.run_single_subject_rfactor_attempt(
                    eio_fail_out,
                    "R4",
                    repo_root=fake_repo,
                    require_no_protstruct_overrides=False,
                )
            self.assertEqual(outcome_eio["status"], "failed")
            self.assertEqual(
                outcome_eio["failed_stage"], "phenix_rfactor_operation"
            )
            self.assertEqual(
                outcome_eio["error"]["exception_type"], "RuntimeError"
            )
            for inv_key in ("phenix_inventory", "refmac_inventory"):
                inv_block = outcome_eio[inv_key]
                self.assertIsNone(inv_block["evidence_root_exists"])
                self.assertEqual(inv_block["inventory_status"], "unavailable")
                self.assertEqual(
                    inv_block["inspection_error"]["errno"], errno.EIO
                )
            eio_outcome_path = (
                eio_fail_out / onesar_rerun.PARENT_ATTEMPT_OUTCOME_FILENAME
            )
            self.assertTrue(eio_outcome_path.is_file())
            self.assertEqual(
                hashlib.sha256(eio_outcome_path.read_bytes()).hexdigest(),
                outcome_eio["outcome_record_reference"]["sha256"],
            )

            # 2b. #1094: Child-root OSError(errno.EIO) after KeyboardInterrupt persists parent_attempt_outcome.json and re-raises.
            orig_eio_kbd_exc = KeyboardInterrupt(
                "simulated Ctrl-C before child EIO"
            )
            with (
                self._without_protstruct_env_overrides(),
                mock.patch.object(
                    onesar_rerun,
                    "run_phenix_rfactor_operation",
                    side_effect=orig_eio_kbd_exc,
                ),
                mock.patch.object(
                    Path,
                    "is_symlink",
                    autospec=True,
                    side_effect=_eio_on_child_roots,
                ),
            ):
                with self.assertRaises(KeyboardInterrupt) as cm_eio_kbd:
                    onesar_rerun.run_single_subject_rfactor_attempt(
                        eio_kbd_out,
                        "R4",
                        repo_root=fake_repo,
                        require_no_protstruct_overrides=False,
                    )
            self.assertIs(cm_eio_kbd.exception, orig_eio_kbd_exc)
            eio_kbd_outcome_path = (
                eio_kbd_out / onesar_rerun.PARENT_ATTEMPT_OUTCOME_FILENAME
            )
            self.assertTrue(eio_kbd_outcome_path.is_file())
            eio_kbd_doc = json.loads(
                eio_kbd_outcome_path.read_text(encoding="utf-8")
            )
            self.assertEqual(eio_kbd_doc["status"], "interrupted")
            self.assertIsNone(
                eio_kbd_doc["phenix_inventory"]["evidence_root_exists"]
            )
            self.assertEqual(
                eio_kbd_doc["phenix_inventory"]["inventory_status"],
                "unavailable",
            )
            self.assertEqual(
                eio_kbd_doc["phenix_inventory"]["inspection_error"]["errno"],
                errno.EIO,
            )

    def test_real_retained_public_verification_and_scientific_refusal_r4_and_start(
        self,
    ) -> None:
        """Exercise real PHENIX, REFMAC, parent-checkpoint, and record-layer verifiers on R4 and start."""
        import onesar_records
        import test_onesar_refmac

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve(strict=True)
            fake_repo = base / "repo"
            fake_repo.mkdir()
            fake_output_repo = base / "output_repo"
            fake_output_repo.mkdir()

            fake_phx_bin, fake_phx_build, fake_phx_runner = (
                self._make_fake_phenix_runner_and_build(base)
            )
            fake_ccp4 = test_onesar_refmac._FakeCcp4Fixture(base)

            def fake_refmac_runner(
                xyzin: Path,
                hklin: Path,
                xyzout: Path,
                hklout: Path,
                log_path: Path,
                keywords: str,
                *,
                cwd: Path,
                timeout: float,
                xml_output: Path,
                executable: Path,
                env: Mapping[str, str],
                ccp4: bool,
            ) -> subprocess.CompletedProcess[str]:
                test_onesar_refmac.TestRefmacCollectorFirstSlice._write_capture_success_outputs(
                    xyzin, hklin, xyzout, hklout, log_path
                )
                argv = [
                    str(executable),
                    "XYZIN",
                    str(xyzin),
                    "HKLIN",
                    str(hklin),
                    "XYZOUT",
                    str(xyzout),
                    "HKLOUT",
                    str(hklout),
                    "XMLOUT",
                    str(xml_output),
                ]
                return subprocess.CompletedProcess(
                    args=argv,
                    returncode=0,
                    stdout=test_onesar_refmac.SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG,
                    stderr="",
                )

            for subject_id, expect_qds_path in (
                ("R4", True),
                ("start", False),
            ):
                with self.subTest(subject_id=subject_id):
                    attempt_out = (
                        REPO_ROOT
                        / ".temp"
                        / f"test_task179_real_refusal_{subject_id.lower()}_{os.getpid()}"
                    )
                    self.assertFalse(attempt_out.exists())
                    try:
                        with (
                            self._without_protstruct_env_overrides(),
                            mock.patch.object(
                                toolchain,
                                "phenix",
                                side_effect=lambda exe: fake_phx_bin / exe,
                            ),
                            mock.patch.object(
                                toolchain,
                                "phenix_build_evidence",
                                return_value=fake_phx_build,
                            ),
                            mock.patch.object(
                                toolchain,
                                "CCP4_SETUP",
                                fake_ccp4.setup_script,
                            ),
                            mock.patch.object(
                                toolchain,
                                "ccp4_environment",
                                return_value=dict(fake_ccp4.sourced_env),
                            ),
                            mock.patch.object(
                                onesar_records,
                                "_prepare_rfactor_eval_and_live_qds_records",
                                side_effect=AssertionError(
                                    "Private record assembly must never be called on scientific refusal"
                                ),
                            ) as prep_mock,
                            mock.patch.object(
                                onesar_records,
                                "_publish_prepared_rfactor_records",
                                side_effect=AssertionError(
                                    "Private record publication must never be called on scientific refusal"
                                ),
                            ) as priv_pub_mock,
                        ):
                            outcome = onesar_rerun.run_single_subject_rfactor_attempt(
                                attempt_out,
                                subject_id,
                                family="rfactors",
                                repo_root=REPO_ROOT,
                                output_repo_root=fake_output_repo,
                                archive_path=COMMITTED_ARCHIVE,
                                timeout=120.0,
                                require_no_protstruct_overrides=False,
                                phenix_runner=fake_phx_runner,
                                refmac_runner=fake_refmac_runner,
                                started_at_utc_override="2026-11-06T23:58:10+00:00",
                                checkpoint_finished_at_utc_override="2026-11-07T00:03:25+00:00",
                            )
                            self.assertEqual(prep_mock.call_count, 0)
                            self.assertEqual(priv_pub_mock.call_count, 0)

                        self.assertEqual(outcome["status"], "refused")
                        self.assertIs(outcome["published"], False)
                        self.assertIs(outcome["committed"], False)
                        self.assertEqual(
                            outcome["failed_stage"],
                            "refmac_retained_verification",
                        )
                        self.assertEqual(outcome["run_date"], "2026-11-06")
                        self.assertIsNone(outcome["authoring_policy_issued_at"])

                        # Verify real-layout PHENIX and REFMAC inventories include original_data.mtz
                        # and all returned cache/raw/audit/manifest files.
                        phx_files = outcome["phenix_inventory"]["retained_files"]
                        for expected_phx_key in (
                            "input_admission_json",
                            "original_model_pdb",
                            "original_data_mtz",
                            "projected_observations_mtz",
                            "input_hkl_ledger_json",
                            "preflight_build_evidence_json",
                            "phenix_operation_parameters_json",
                            "phenix_reconciled_manifest_json",
                            "cache_manifest_json",
                            "stdout_log",
                            "phenix_rfactors_json",
                            "phenix_diagnostics_json",
                            "phenix_partial_evidence_json",
                            "phx_maps_mtz",
                            "phx_obs_pair_only_mtz",
                        ):
                            self.assertIn(expected_phx_key, phx_files)
                        self.assertTrue(
                            phx_files["original_data_mtz"]["path"].endswith(
                                "inputs/original_data.mtz"
                            )
                        )
                        self.assertIn(
                            "refinement_cache_v1",
                            phx_files["phenix_rfactors_json"]["path"],
                        )
                        self.assertIn(
                            "refinement_cache_v1",
                            phx_files["phx_maps_mtz"]["path"],
                        )

                        rm_files = outcome["refmac_inventory"]["retained_files"]
                        for expected_rm_key in (
                            "input_admission_json",
                            "original_model_pdb",
                            "original_data_mtz",
                            "projected_observations_mtz",
                            "input_hkl_ledger_json",
                            "refmac_keywords_txt",
                            "pre_execution_checkpoint_json",
                            "post_execution_checkpoint_json",
                            "refmac_log",
                            "refmac_xyzout_pdb",
                            "refmac_hklout_mtz",
                            "parsed_log_json",
                            "hklout_raw_export_json",
                            "hklout_audit_json",
                            "xyzout_audit_json",
                            "diagnostics_json",
                            "operation_manifest_json",
                        ):
                            self.assertIn(expected_rm_key, rm_files)
                        self.assertTrue(
                            rm_files["original_data_mtz"]["path"].endswith(
                                "inputs/original_data.mtz"
                            )
                        )

                        # Verify intended_paths for R4 (EVAL + QDS) vs start (EVAL-only).
                        if expect_qds_path:
                            self.assertTrue(
                                str(outcome["intended_paths"]["eval_path"]).endswith(
                                    "data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-11-06.yaml"
                                )
                            )
                            self.assertTrue(
                                str(outcome["intended_paths"]["qds_path"]).endswith(
                                    "data/coscientists/openscientist/QDS_1sar_cdba2c07_2026-11-06.yaml"
                                )
                            )
                        else:
                            self.assertTrue(
                                str(outcome["intended_paths"]["eval_path"]).endswith(
                                    "data/coscientists/openscientist/EVAL_1sar_cdba2c07-start_2026-11-06.yaml"
                                )
                            )
                            self.assertIsNone(
                                outcome["intended_paths"]["qds_path"]
                            )

                        # Zero canonical files created in fake_output_repo.
                        self.assertEqual(list(fake_output_repo.rglob("*.yaml")), [])

                        # Verify parent_completed_execution_checkpoint.json is byte-identical to its reference
                        # and passes verify_retained_parent_execution_checkpoint directly.
                        cp_ref = outcome["completed_checkpoint_reference"]
                        assert isinstance(cp_ref, Mapping)
                        cp_path = Path(str(cp_ref["path"]))
                        self.assertEqual(
                            hashlib.sha256(cp_path.read_bytes()).hexdigest(),
                            cp_ref["sha256"],
                        )
                        verified_cp = (
                            onesar_records.verify_retained_parent_execution_checkpoint(
                                attempt_out,
                                subject_id=subject_id,
                                checkpoint_reference=cp_ref,
                                expected_family="rfactors",
                                expected_run_date="2026-11-06",
                                repo_root=REPO_ROOT,
                            )
                        )
                        self.assertEqual(
                            verified_cp["verification_status"], "verified"
                        )

                        # Verify scientific_refusal and persisted authoring_outcome_0001.json.
                        sci_refusal = outcome["scientific_refusal"]
                        assert isinstance(sci_refusal, Mapping)
                        self.assertIs(sci_refusal["integrity_verified"], True)
                        self.assertIs(
                            sci_refusal["scientific_proof_established"], False
                        )
                        self.assertEqual(
                            set(sci_refusal["unknown_native_premises"].keys()),
                            set(onesar_records.REFMAC_UNKNOWN_NATIVE_PREMISE_KEYS),
                        )
                        auth_outcome_path = Path(
                            str(outcome["authoring_outcome_path"])
                        )
                        self.assertTrue(auth_outcome_path.is_file())
                        auth_outcome_doc = json.loads(
                            auth_outcome_path.read_text(encoding="utf-8")
                        )
                        self.assertEqual(auth_outcome_doc["status"], "refused")
                        self.assertIs(auth_outcome_doc["published"], False)
                        self.assertEqual(
                            auth_outcome_doc["failed_stage"],
                            "refmac_retained_verification",
                        )

                        # Cross-child staged input hash disagreement is rejected at parent_checkpoint_verification.
                        if subject_id == "R4":
                            rm_pdb = (
                                attempt_out
                                / "refmac"
                                / "inputs"
                                / "original_model.pdb"
                            )
                            orig_pdb_bytes = rm_pdb.read_bytes()
                            try:
                                rm_pdb.write_bytes(
                                    orig_pdb_bytes + b"\nREMARK TAMPERED\n"
                                )
                                with self.assertRaises(
                                    onesar_records.ParentExecutionBindingError
                                ):
                                    onesar_records.verify_retained_parent_execution_checkpoint(
                                        attempt_out,
                                        subject_id="R4",
                                        checkpoint_reference=cp_ref,
                                        expected_family="rfactors",
                                        expected_run_date="2026-11-06",
                                        repo_root=REPO_ROOT,
                                    )
                            finally:
                                rm_pdb.write_bytes(orig_pdb_bytes)
                    finally:
                        if attempt_out.exists():
                            shutil.rmtree(attempt_out)

            # Also exercise the top-level CLI main() entrypoint on R4 with fake native runners.
            cli_attempt_out = (
                REPO_ROOT
                / ".temp"
                / f"test_task179_cli_main_r4_{os.getpid()}"
            )
            self.assertFalse(cli_attempt_out.exists())
            try:
                with (
                    self._without_protstruct_env_overrides(),
                    mock.patch.object(
                        toolchain,
                        "phenix",
                        side_effect=lambda exe: fake_phx_bin / exe,
                    ),
                    mock.patch.object(
                        toolchain,
                        "phenix_build_evidence",
                        return_value=fake_phx_build,
                    ),
                    mock.patch.object(
                        toolchain,
                        "run_logged",
                        side_effect=fake_phx_runner,
                    ),
                    mock.patch.object(
                        toolchain,
                        "CCP4_SETUP",
                        fake_ccp4.setup_script,
                    ),
                    mock.patch.object(
                        toolchain,
                        "ccp4_environment",
                        return_value=dict(fake_ccp4.sourced_env),
                    ),
                    mock.patch.object(
                        toolchain,
                        "run_refmac",
                        side_effect=fake_refmac_runner,
                    ),
                    mock.patch.object(
                        onesar_records,
                        "_prepare_rfactor_eval_and_live_qds_records",
                        side_effect=AssertionError(
                            "Private record assembly must never be called on scientific refusal"
                        ),
                    ),
                    mock.patch.object(
                        onesar_records,
                        "_publish_prepared_rfactor_records",
                        side_effect=AssertionError(
                            "Private record publication must never be called on scientific refusal"
                        ),
                    ),
                ):
                    rc_main = onesar_rerun.main(
                        [
                            "--subject",
                            "R4",
                            "--family",
                            "rfactors",
                            "--evidence-out",
                            str(cli_attempt_out),
                            "--repo-root",
                            str(REPO_ROOT),
                            "--archive",
                            str(COMMITTED_ARCHIVE),
                            "--timeout",
                            "120.0",
                        ]
                    )
                self.assertEqual(rc_main, 1)
                cli_outcome_doc = json.loads(
                    (
                        cli_attempt_out
                        / onesar_rerun.PARENT_ATTEMPT_OUTCOME_FILENAME
                    ).read_text(encoding="utf-8")
                )
                self.assertEqual(cli_outcome_doc["status"], "refused")
                self.assertIs(cli_outcome_doc["published"], False)
                self.assertEqual(
                    cli_outcome_doc["failed_stage"],
                    "refmac_retained_verification",
                )
            finally:
                if cli_attempt_out.exists():
                    shutil.rmtree(cli_attempt_out)


if __name__ == "__main__":
    unittest.main()
