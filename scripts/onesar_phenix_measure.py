#!/usr/bin/env python3
"""Vendor Python 3.9 helper for PHENIX 2.0-5936 first-block R-factor and map export.

This script runs under ``phenix.python`` via :mod:`scripts.onesar_rerun`.
All ``cctbx`` / ``iotbx`` / ``mmtbx`` imports are deferred inside
:func:`measure_first_block_rfactors` so the module can be imported and its pure
math/snapshot helpers unit-tested under the repository Python 3.12 environment
without vendor libraries installed.

Scientific contract (Task 082 / 079 preregistration / 078 native design):
- Uses the public first-block ``mmtbx.model_vs_data`` sequence:
  - ``iotbx.pdb.input`` on the untouched model PDB.
  - ``iotbx.reflection_file_reader.any_reflection_file`` on the projected
    6-column observation MTZ.
  - ``cctbx.crystal.select_crystal_symmetry`` with ``enforce_similarity=True``.
  - ``mmtbx.model_vs_data.reflection_file_server``.
  - ``iotbx.extract_xtal_data.data_and_flags_master_params().extract()`` with
    ``labels=["F-obs", "SIGF-obs"]``, ``r_free_flags.label="R-free-flags"``,
    ``r_free_flags.test_flag_value=1``, ``r_free_flags.required=True``,
    ``r_free_flags.generate=False``, ``r_free_flags.ignore_r_free_flags=False``,
    and ``keep_going=False``.
  - ``mmtbx.model.manager`` + ``setup_scattering_dictionaries(scattering_table="n_gaussian", d_min=f_obs.d_min())``.
  - ``mmtbx.f_model.manager(xray_structure=..., r_free_flags=..., f_obs=..., twin_law=None)``
    followed by ``fmodel.update_all_scales(update_f_part1=True)``.
- Does NOT run the second ``mmtbx.model_vs_data`` block (lines 176-225) that
  re-applies PDB ``REMARK 3`` resolution cutoffs or rebuilds ``fmodel``.
- Exports full-precision extracted pre-``fmodel``, final effective, actual work,
  and actual free arrays, work/free-specific scaled model structure factors
  (``f_model_scaled_with_k1_w`` and ``f_model_scaled_with_k1_t``), scatterer
  invariance snapshots, and fresh ``2mFo-DFc`` / ``mFo-DFc`` complex map
  coefficients alongside float32 MTZ supplements.
"""

from __future__ import annotations

import argparse
import copy
import errno
import hashlib
import json
import math
import os
import stat
import struct
import sys
from io import StringIO
from pathlib import Path
from typing import Any, Mapping, Sequence


EXPECTED_PARAMETERS = {
    "algorithm": "mmtbx.model_vs_data.first_block_public_api",
    "labels": ["F-obs", "SIGF-obs"],
    "r_free_flags_label": "R-free-flags",
    "test_flag_value": 1,
    "r_free_flags_generate": False,
    "ignore_r_free_flags": False,
    "keep_going": False,
    "scattering_table": "n_gaussian",
    "twin_law": None,
    "update_f_part1": True,
    "apply_pdb_header_resolution_cut": False,
}

EXPECTED_MAP_PARAMETERS = {
    "acentrics_scale": 2.0,
    "centrics_pre_scale": 1.0,
    "exclude_free_r_reflections": False,
    "fill_missing": False,
    "isotropize": True,
    "sharp": False,
    "phases_prefix": "PH",
}


def _sha256_file_py39(path: Path) -> str:
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise ValueError(f"Regular non-symlink file required: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_parameters_contract(params: Mapping[str, Any]) -> None:
    """Verify that the operation parameter JSON matches the preregistered contract."""
    if not isinstance(params, Mapping):
        raise ValueError("Operation parameters must be a JSON object")
    for key, expected in EXPECTED_PARAMETERS.items():
        actual = params.get(key)
        if actual != expected or type(actual) is not type(expected):
            raise ValueError(
                f"Parameter {key!r} mismatch: expected {expected!r}, got {actual!r}"
            )
    expected_prefix = params.get("expected_resolved_prefix")
    if (
        not isinstance(expected_prefix, str)
        or not expected_prefix
        or not Path(expected_prefix).is_absolute()
    ):
        raise ValueError(
            "Operation parameters must include an absolute "
            f"expected_resolved_prefix; got {expected_prefix!r}"
        )
    expected_version = params.get("expected_phenix_version")
    if not isinstance(expected_version, str) or not expected_version:
        raise ValueError(
            "Operation parameters must include a non-empty "
            f"expected_phenix_version; got {expected_version!r}"
        )
    map_params = params.get("map_coefficients")
    if not isinstance(map_params, Mapping):
        raise ValueError("Operation parameters missing map_coefficients object")
    for key, expected in EXPECTED_MAP_PARAMETERS.items():
        actual = map_params.get(key)
        if actual != expected or type(actual) is not type(expected):
            raise ValueError(
                f"map_coefficients.{key} mismatch: expected {expected!r}, got {actual!r}"
            )


def compute_rfactor_from_arrays(
    f_obs: Sequence[float],
    f_model_scaled_amplitudes: Sequence[float],
) -> dict[str, float]:
    """Compute exact double-precision crystallographic R-factor numerator, denominator, and ratio."""
    if len(f_obs) != len(f_model_scaled_amplitudes):
        raise ValueError(
            f"Length mismatch in R-factor arrays: {len(f_obs)} vs "
            f"{len(f_model_scaled_amplitudes)}"
        )
    if not f_obs:
        raise ValueError("Cannot compute R-factor on empty reflection array")
    numerator = 0.0
    denominator = 0.0
    for idx, (fo, fm) in enumerate(zip(f_obs, f_model_scaled_amplitudes)):
        fo_val = float(fo)
        fm_val = float(fm)
        if not math.isfinite(fo_val) or not math.isfinite(fm_val):
            raise ValueError(f"Non-finite amplitude at index {idx}: fo={fo}, fm={fm}")
        if fo_val <= 0.0 or fm_val < 0.0:
            raise ValueError(
                f"Invalid amplitude sign at index {idx}: fo={fo_val}, fm={fm_val}"
            )
        numerator += abs(fo_val - fm_val)
        denominator += fo_val
    if denominator <= 0.0:
        raise ValueError(f"Non-positive R-factor denominator: {denominator}")
    return {
        "numerator": numerator,
        "denominator": denominator,
        "r_factor": numerator / denominator,
    }


def build_raw_scatterer_snapshot(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Capture raw scatterer count and records without finite/non-empty digest validation."""
    raw_records: list[dict[str, Any]] = []
    for idx, rec in enumerate(records):
        raw_records.append(
            {
                "index": idx,
                "label": str(rec["label"]),
                "scattering_type": str(rec["scattering_type"]),
                "site_frac": [float(x) for x in rec["site_frac"]],
                "site_cart": [float(x) for x in rec["site_cart"]],
                "occupancy": float(rec["occupancy"]),
                "u_iso": float(rec["u_iso"]),
                "u_star": [float(x) for x in rec["u_star"]],
                "use_u_iso": bool(rec["use_u_iso"]),
                "use_u_aniso": bool(rec["use_u_aniso"]),
            }
        )
    return {
        "n_scatterers": len(raw_records),
        "sha256": None,
        "records": raw_records,
    }


def snapshot_scatterer_records(
    records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compute a canonical digest and normalized representation of scatterer state."""
    if not records:
        raise ValueError("Scatterer snapshot cannot be empty")
    normalized: list[dict[str, Any]] = []
    for idx, rec in enumerate(records):
        site_frac = [float(x) for x in rec["site_frac"]]
        site_cart = [float(x) for x in rec["site_cart"]]
        u_star = [float(x) for x in rec["u_star"]]
        occ = float(rec["occupancy"])
        u_iso = float(rec["u_iso"])
        if (
            len(site_frac) != 3
            or len(site_cart) != 3
            or len(u_star) != 6
            or not all(math.isfinite(v) for v in site_frac + site_cart + u_star)
            or not math.isfinite(occ)
            or not math.isfinite(u_iso)
        ):
            raise ValueError(f"Invalid scatterer record at index {idx}: {rec!r}")
        normalized.append(
            {
                "index": idx,
                "label": str(rec["label"]),
                "scattering_type": str(rec["scattering_type"]),
                "site_frac": site_frac,
                "site_cart": site_cart,
                "occupancy": occ,
                "u_iso": u_iso,
                "u_star": u_star,
                "use_u_iso": bool(rec["use_u_iso"]),
                "use_u_aniso": bool(rec["use_u_aniso"]),
            }
        )
    canonical_bytes = json.dumps(
        normalized, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return {
        "n_scatterers": len(normalized),
        "sha256": hashlib.sha256(canonical_bytes).hexdigest(),
        "records": normalized,
    }


def compare_scatterer_snapshots(
    before: Mapping[str, Any],
    after_model: Mapping[str, Any],
    after_fmodel: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare scatterer snapshots before and after scaling and fail on any mutation."""
    before_recs = before.get("records")
    after_model_recs = after_model.get("records")
    after_fmodel_recs = after_fmodel.get("records")
    if (
        not isinstance(before_recs, list)
        or not isinstance(after_model_recs, list)
        or not isinstance(after_fmodel_recs, list)
        or not before_recs
        or len(before_recs) != len(after_model_recs)
        or len(before_recs) != len(after_fmodel_recs)
    ):
        raise ValueError("Scatterer count changed across f_model scaling")

    recomputed_before = snapshot_scatterer_records(before_recs)
    recomputed_after_model = snapshot_scatterer_records(after_model_recs)
    recomputed_after_fmodel = snapshot_scatterer_records(after_fmodel_recs)
    for stage_name, raw_snap, recomputed_snap in (
        ("before", before, recomputed_before),
        ("after_model", after_model, recomputed_after_model),
        ("after_fmodel", after_fmodel, recomputed_after_fmodel),
    ):
        if raw_snap.get("n_scatterers") != recomputed_snap["n_scatterers"]:
            raise ValueError(
                f"{stage_name} snapshot n_scatterers mismatch with its records"
            )
        if raw_snap.get("sha256") != recomputed_snap["sha256"]:
            raise ValueError(
                f"{stage_name} snapshot sha256 mismatch with its records"
            )

    max_site_cart_diff = 0.0
    max_occ_diff = 0.0
    max_u_iso_diff = 0.0
    max_u_star_diff = 0.0

    for idx, base in enumerate(recomputed_before["records"]):
        for other_label, other in (
            ("after_model", recomputed_after_model["records"][idx]),
            ("after_fmodel", recomputed_after_fmodel["records"][idx]),
        ):
            if (
                base["label"] != other["label"]
                or base["scattering_type"] != other["scattering_type"]
                or base["use_u_iso"] != other["use_u_iso"]
                or base["use_u_aniso"] != other["use_u_aniso"]
            ):
                raise ValueError(
                    f"Scatterer metadata mutated at index {idx} ({other_label}): "
                    f"{base!r} vs {other!r}"
                )
            for a, b in zip(base["site_cart"], other["site_cart"]):
                max_site_cart_diff = max(max_site_cart_diff, abs(float(a) - float(b)))
            max_occ_diff = max(
                max_occ_diff, abs(float(base["occupancy"]) - float(other["occupancy"]))
            )
            max_u_iso_diff = max(
                max_u_iso_diff, abs(float(base["u_iso"]) - float(other["u_iso"]))
            )
            for a, b in zip(base["u_star"], other["u_star"]):
                max_u_star_diff = max(max_u_star_diff, abs(float(a) - float(b)))

    summary = {
        "n_scatterers": len(before_recs),
        "before_sha256": recomputed_before["sha256"],
        "after_model_sha256": recomputed_after_model["sha256"],
        "after_fmodel_sha256": recomputed_after_fmodel["sha256"],
        "identical_before_vs_after_model": (
            recomputed_before["sha256"] == recomputed_after_model["sha256"]
        ),
        "identical_before_vs_after_fmodel": (
            recomputed_before["sha256"] == recomputed_after_fmodel["sha256"]
        ),
        "max_abs_site_cart_diff": max_site_cart_diff,
        "max_abs_occupancy_diff": max_occ_diff,
        "max_abs_u_iso_diff": max_u_iso_diff,
        "max_abs_u_star_diff": max_u_star_diff,
        "snapshots": {
            "before": recomputed_before,
            "after_model": recomputed_after_model,
            "after_fmodel": recomputed_after_fmodel,
        },
    }
    if (
        summary["before_sha256"] != summary["after_model_sha256"]
        or summary["before_sha256"] != summary["after_fmodel_sha256"]
        or max_site_cart_diff != 0.0
        or max_occ_diff != 0.0
        or max_u_iso_diff != 0.0
        or max_u_star_diff != 0.0
    ):
        raise ValueError(f"Scatterer snapshot mutated during scaling: {summary}")
    return summary


def _capture_xrs_snapshot(
    xrs: Any,
    *,
    on_raw_capture: Any = None,
) -> dict[str, Any]:
    sites_cart = list(xrs.sites_cart())
    scatterers = list(xrs.scatterers())
    if len(sites_cart) != len(scatterers):
        raise ValueError("xray_structure sites_cart and scatterers size mismatch")
    records: list[dict[str, Any]] = []
    for idx, sc in enumerate(scatterers):
        records.append(
            {
                "label": str(sc.label),
                "scattering_type": str(sc.scattering_type),
                "site_frac": [float(v) for v in sc.site],
                "site_cart": [float(v) for v in sites_cart[idx]],
                "occupancy": float(sc.occupancy),
                "u_iso": float(sc.u_iso),
                "u_star": [float(v) for v in sc.u_star],
                "use_u_iso": bool(sc.flags.use_u_iso()),
                "use_u_aniso": bool(sc.flags.use_u_aniso()),
            }
        )
    if on_raw_capture is not None:
        on_raw_capture(build_raw_scatterer_snapshot(records))
    return snapshot_scatterer_records(records)


def _extract_runtime_crystal_symmetry_record(
    crystal_symmetry: Any,
    *,
    label: str = "crystal_symmetry",
) -> dict[str, Any]:
    """Extract unit cell, space-group number, and XYZ symmetry operations from cctbx.crystal.symmetry."""
    if (
        crystal_symmetry is None
        or crystal_symmetry.unit_cell() is None
        or crystal_symmetry.space_group_info() is None
    ):
        raise RuntimeError(f"{label} is missing complete crystal_symmetry")
    unit_cell_obj = crystal_symmetry.unit_cell()
    sgi = crystal_symmetry.space_group_info()
    sg_fn = getattr(crystal_symmetry, "space_group", None)
    sg = sg_fn() if callable(sg_fn) else None
    sgi_group_fn = getattr(sgi, "group", None)
    sgi_group = sgi_group_fn() if callable(sgi_group_fn) else None
    if sg is None:
        sg = sgi_group
    if sg is None:
        raise RuntimeError(f"{label} is missing space_group()")

    sg_type_fn = getattr(sg, "type", None)
    sg_type = sg_type_fn() if callable(sg_type_fn) else None
    sg_num_fn = getattr(sg_type, "number", None) if sg_type is not None else None
    if not callable(sg_num_fn):
        raise RuntimeError(
            f"{label}.space_group().type().number() is unavailable"
        )
    raw_sg_number = sg_num_fn()
    if (
        type(raw_sg_number) is bool
        or not isinstance(raw_sg_number, int)
        or not (1 <= int(raw_sg_number) <= 230)
    ):
        raise RuntimeError(
            f"{label} space_group().type().number() must be an integer in 1..230, "
            f"got {raw_sg_number!r}"
        )
    space_group_number = int(raw_sg_number)

    sgi_type_fn = getattr(sgi, "type", None)
    sgi_type = sgi_type_fn() if callable(sgi_type_fn) else None
    if sgi_type is not None:
        sgi_num_fn = getattr(sgi_type, "number", None)
        if not callable(sgi_num_fn):
            raise RuntimeError(
                f"{label}.space_group_info().type().number() is unavailable"
            )
        sgi_num = sgi_num_fn()
        if (
            type(sgi_num) is bool
            or not isinstance(sgi_num, int)
            or int(sgi_num) != space_group_number
        ):
            raise RuntimeError(
                f"{label} space_group_info().type().number() {sgi_num!r} "
                f"disagrees with space_group().type().number() {space_group_number!r}"
            )

    all_ops_fn = getattr(sg, "all_ops", None)
    if not callable(all_ops_fn):
        raise RuntimeError(f"{label}.space_group().all_ops() is unavailable")
    raw_ops = list(all_ops_fn())
    if not raw_ops:
        raise RuntimeError(
            f"{label}.space_group().all_ops() returned no symmetry operations"
        )
    operators_xyz: list[str] = []
    for op_idx, op in enumerate(raw_ops):
        as_xyz_fn = getattr(op, "as_xyz", None)
        if not callable(as_xyz_fn):
            raise RuntimeError(
                f"{label}.space_group().all_ops()[{op_idx}] is missing as_xyz()"
            )
        op_xyz = as_xyz_fn()
        if not isinstance(op_xyz, str) or not op_xyz.strip():
            raise RuntimeError(
                f"{label}.space_group().all_ops()[{op_idx}].as_xyz() returned "
                f"invalid operator string {op_xyz!r}"
            )
        operators_xyz.append(str(op_xyz))

    if sgi_group is not None and sgi_group is not sg:
        sgi_all_ops_fn = getattr(sgi_group, "all_ops", None)
        if not callable(sgi_all_ops_fn):
            raise RuntimeError(
                f"{label}.space_group_info().group().all_ops() is unavailable"
            )
        sgi_ops_xyz = [str(op.as_xyz()) for op in list(sgi_all_ops_fn())]
        if sgi_ops_xyz != operators_xyz:
            raise RuntimeError(
                f"{label} space_group_info().group().all_ops() {sgi_ops_xyz!r} "
                f"disagrees with space_group().all_ops() {operators_xyz!r}"
            )

    space_group_symbol = str(sgi.symbol_and_number())
    if not space_group_symbol.strip():
        raise RuntimeError(
            f"{label}.space_group_info().symbol_and_number() returned empty string"
        )
    return {
        "unit_cell": [float(x) for x in unit_cell_obj.parameters()],
        "space_group_symbol": space_group_symbol,
        "space_group_number": space_group_number,
        "space_group_operators_xyz": operators_xyz,
        "unit_cell_precision_note": (
            "Effective runtime unit cell selected by cctbx.crystal.select_crystal_symmetry "
            "from reflection Miller arrays (CCP4/iotbx float32 CELL/DCELL promoted to float64)."
        ),
    }


def _inspect_vendor_modules(
    module_map: Mapping[str, Any],
    *,
    expected_resolved_prefix: str | Path | None = None,
) -> dict[str, Any]:
    resolved_prefix = Path(sys.prefix).resolve(strict=True)
    resolved_exec = Path(sys.executable).resolve(strict=True)
    if not resolved_exec.is_relative_to(resolved_prefix):
        raise ValueError(
            f"sys.executable {resolved_exec} escapes sys.prefix {resolved_prefix}"
        )
    expected_prefix_path: Path | None = None
    if expected_resolved_prefix is not None:
        expected_prefix_path = Path(expected_resolved_prefix).resolve(strict=True)
        if not resolved_prefix.is_relative_to(expected_prefix_path):
            raise ValueError(
                f"Runtime resolved_sys_prefix {resolved_prefix} does not belong "
                f"to expected_resolved_prefix {expected_prefix_path}"
            )
        if not resolved_exec.is_relative_to(expected_prefix_path):
            raise ValueError(
                f"Runtime resolved_sys_executable {resolved_exec} escapes "
                f"expected_resolved_prefix {expected_prefix_path}"
            )
    vendor_modules: dict[str, dict[str, str]] = {}
    for key, mod in module_map.items():
        mod_file = getattr(mod, "__file__", None)
        if not isinstance(mod_file, str) or not mod_file:
            raise ValueError(f"Loaded module {key} has no __file__ attribute")
        mod_path = Path(mod_file).resolve(strict=True)
        if not mod_path.is_relative_to(resolved_prefix):
            raise ValueError(
                f"Loaded module {key} at {mod_path} escapes sys.prefix {resolved_prefix}"
            )
        if expected_prefix_path is not None and not mod_path.is_relative_to(
            expected_prefix_path
        ):
            raise ValueError(
                f"Loaded module {key} at {mod_path} escapes "
                f"expected_resolved_prefix {expected_prefix_path}"
            )
        vendor_modules[key] = {
            "module_name": str(getattr(mod, "__name__", key)),
            "configured_path": mod_file,
            "resolved_path": str(mod_path),
            "sha256": _sha256_file_py39(mod_path),
        }
    return {
        "python_version": sys.version,
        "sys_executable": sys.executable,
        "resolved_sys_executable": str(resolved_exec),
        "sys_prefix": sys.prefix,
        "resolved_sys_prefix": str(resolved_prefix),
        "vendor_modules": vendor_modules,
    }


def _export_map_records(miller_array: Any) -> dict[str, Any]:
    indices = list(miller_array.indices())
    data = list(miller_array.data())
    centric_flags = list(miller_array.centric_flags().data())
    if len(indices) != len(data) or len(indices) != len(centric_flags):
        raise ValueError("Map coefficient array index/data/centric_flags length mismatch")
    records: list[dict[str, Any]] = []
    centric_count = 0
    acentric_count = 0
    for hkl, coeff, is_centric in zip(indices, data, centric_flags):
        re_val = float(coeff.real)
        im_val = float(coeff.imag)
        amp_val = float(abs(coeff))
        phase_deg = float(math.degrees(math.atan2(im_val, re_val)) % 360.0)
        centric_bool = bool(is_centric)
        if centric_bool:
            centric_count += 1
        else:
            acentric_count += 1
        records.append(
            {
                "hkl": [int(hkl[0]), int(hkl[1]), int(hkl[2])],
                "real": re_val,
                "imag": im_val,
                "amplitude": amp_val,
                "phase_deg": phase_deg,
                "is_centric": centric_bool,
            }
        )
    return {
        "n_reflections": len(records),
        "centric_count": centric_count,
        "acentric_count": acentric_count,
        "records": records,
    }


def _emit_stage_log(stage_label: str, text: str) -> None:
    sys.stdout.write(f"=== [onesar_phenix_measure] {stage_label} ===\n")
    if text:
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")
    sys.stdout.flush()


def encode_raw_evidence_nonfinite(
    value: Any,
    *,
    field_path: str = "",
    nonfinite_locations: list[dict[str, Any]] | None = None,
) -> Any:
    """Recursively replace non-finite float values with strict-JSON IEEE-754 tags.

    Ordinary finite floats, ints, booleans, strings, lists, and mappings are
    returned unchanged so valid finite measurements have identical JSON
    representation. Non-finite floats (NaN, +Inf, -Inf) are replaced in-place
    at their exact field location with a tagged object recording the IEEE-754
    binary64 bit pattern (``0x...``), sign bit, kind (``nan``, ``+inf``,
    ``-inf``), string representation, and ``field_path``.
    """
    if type(value) is float and not math.isfinite(value):
        bits = struct.unpack(">Q", struct.pack(">d", value))[0]
        kind = (
            "nan"
            if math.isnan(value)
            else ("+inf" if value > 0.0 else "-inf")
        )
        tag = {
            "__nonfinite_ieee754_float64__": True,
            "kind": kind,
            "repr": str(value),
            "ieee754_binary64_hex": f"0x{bits:016x}",
            "sign_bit": int((bits >> 63) & 1),
            "field_path": field_path,
        }
        if nonfinite_locations is not None:
            nonfinite_locations.append(dict(tag))
        return tag
    if isinstance(value, Mapping):
        if value.get("__nonfinite_ieee754_float64__") is True:
            tag_copy = dict(value)
            if nonfinite_locations is not None:
                nonfinite_locations.append(tag_copy)
            return tag_copy
        out_dict: dict[str, Any] = {}
        for k, v in value.items():
            k_str = str(k)
            child_path = f"{field_path}.{k_str}" if field_path else k_str
            out_dict[k_str] = encode_raw_evidence_nonfinite(
                v,
                field_path=child_path,
                nonfinite_locations=nonfinite_locations,
            )
        return out_dict
    if isinstance(value, (list, tuple)):
        return [
            encode_raw_evidence_nonfinite(
                item,
                field_path=f"{field_path}[{idx}]",
                nonfinite_locations=nonfinite_locations,
            )
            for idx, item in enumerate(value)
        ]
    return value


def _prepare_partial_evidence_for_checkpoint(
    partial_evidence: dict[str, Any],
) -> dict[str, Any]:
    """Sanitize non-finite float values in partial_evidence in-place and update nonfinite_raw_values."""
    locations: list[dict[str, Any]] = []
    for key in list(partial_evidence.keys()):
        if key == "nonfinite_raw_values":
            continue
        partial_evidence[key] = encode_raw_evidence_nonfinite(
            partial_evidence[key],
            field_path=key,
            nonfinite_locations=locations,
        )
    partial_evidence["nonfinite_raw_values"] = locations
    return partial_evidence


def _open_checkpoint_temp_file(tmp_path: Path) -> Any:
    """Open the temporary checkpoint sibling file for writing."""
    return tmp_path.open("w", encoding="utf-8")


def _atomic_write_json_checkpoint(
    payload: Mapping[str, Any],
    target_path: Path | None,
    *,
    allow_nonfinite_tags: bool = False,
) -> None:
    """Atomically write a complete JSON checkpoint via a temporary sibling file."""
    if target_path is None:
        return
    to_serialize = (
        encode_raw_evidence_nonfinite(payload)
        if allow_nonfinite_tags
        else payload
    )
    serialized = (
        json.dumps(to_serialize, indent=2, sort_keys=True, allow_nan=False)
        + "\n"
    )
    tmp_path = target_path.parent / f".{target_path.name}.tmp.{os.getpid()}"
    try:
        with _open_checkpoint_temp_file(tmp_path) as fh:
            fh.write(serialized)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError as exc:
                if exc.errno not in (errno.EINVAL, errno.ENOTSUP):
                    raise
        os.replace(tmp_path, target_path)
    except BaseException:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _checkpoint_diagnostics(
    diagnostics: Mapping[str, Any],
    out_diagnostics_json_path: Path | None,
) -> None:
    """Persist the current diagnostics dictionary to disk via atomic replacement."""
    _atomic_write_json_checkpoint(
        diagnostics, out_diagnostics_json_path, allow_nonfinite_tags=True
    )


class _PersistentTeeLogStream:
    """Writable log stream that flushes vendor log output live to stdout and diagnostics."""

    def __init__(
        self,
        stage_label: str,
        diagnostics: dict[str, Any],
        diagnostics_field: str,
        diagnostics_json_path: Path | None = None,
        log_file_path: Path | None = None,
    ) -> None:
        self._stage_label = stage_label
        self._diagnostics = diagnostics
        self._diagnostics_field = diagnostics_field
        self._diagnostics_json_path = diagnostics_json_path
        self._log_file_path = log_file_path
        self._buffer = StringIO()
        self._banner_emitted = False
        self._ends_with_newline = True
        if self._log_file_path is not None:
            with self._log_file_path.open("w", encoding="utf-8") as fh:
                fh.write("")
                fh.flush()

    def _emit_banner_if_needed(self) -> None:
        if not self._banner_emitted:
            sys.stdout.write(
                f"=== [onesar_phenix_measure] {self._stage_label} ===\n"
            )
            sys.stdout.flush()
            self._banner_emitted = True
            self._ends_with_newline = True

    def _sync_persistent(self, chunk: str) -> None:
        if self._log_file_path is not None and chunk:
            with self._log_file_path.open("a", encoding="utf-8") as fh:
                fh.write(chunk)
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except OSError:
                    pass
        self._diagnostics[self._diagnostics_field] = self._buffer.getvalue()
        _checkpoint_diagnostics(self._diagnostics, self._diagnostics_json_path)

    def write(self, text: Any) -> int:
        chunk = str(text)
        if not chunk:
            return 0
        self._buffer.write(chunk)
        self._emit_banner_if_needed()
        sys.stdout.write(chunk)
        sys.stdout.flush()
        self._ends_with_newline = chunk.endswith("\n")
        self._sync_persistent(chunk)
        return len(chunk)

    def writelines(self, lines: Any) -> None:
        for line in lines:
            self.write(line)

    def flush(self) -> None:
        sys.stdout.flush()
        self._sync_persistent("")

    def finalize(self) -> str:
        self._emit_banner_if_needed()
        if not self._ends_with_newline:
            sys.stdout.write("\n")
            sys.stdout.flush()
            self._ends_with_newline = True
        text = self._buffer.getvalue()
        self._diagnostics[self._diagnostics_field] = text
        _checkpoint_diagnostics(self._diagnostics, self._diagnostics_json_path)
        return text

    def getvalue(self) -> str:
        return self._buffer.getvalue()


def measure_first_block_rfactors(
    *,
    pdb_path: Path,
    mtz_path: Path,
    params_path: Path,
    out_json_path: Path,
    out_maps_mtz_path: Path,
    out_obs_pair_mtz_path: Path,
    out_diagnostics_json_path: Path | None = None,
    out_partial_json_path: Path | None = None,
) -> dict[str, Any]:
    """Execute the first-block ``mmtbx.model_vs_data`` measurement inside ``phenix.python``."""
    effective_partial_json_path = (
        out_partial_json_path
        if out_partial_json_path is not None
        else out_json_path.with_name(
            f"{out_json_path.stem}_partial_evidence.json"
        )
    )
    if out_json_path.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing output JSON: {out_json_path}"
        )
    if effective_partial_json_path.exists():
        raise FileExistsError(
            "Refusing to overwrite existing partial evidence JSON: "
            f"{effective_partial_json_path}"
        )
    if (
        out_diagnostics_json_path is not None
        and out_diagnostics_json_path.exists()
    ):
        raise FileExistsError(
            "Refusing to overwrite existing diagnostics JSON: "
            f"{out_diagnostics_json_path}"
        )

    diagnostics: dict[str, Any] = {
        "schema_version": 1,
        "status": "running",
        "current_phase": "parameter_validation",
        "phase_history": ["parameter_validation"],
        "adapter_identity": (
            "mmtbx.model_vs_data.first_block_public_api "
            "(public Python API adapter; not the phenix.model_vs_data CLI banner)"
        ),
        "extract_xtal_data_log": None,
        "extract_xtal_data_constructor_log_note": (
            "iotbx.extract_xtal_data.run owns an internal self.log StringIO buffer "
            "that becomes accessible only after __init__ returns; if __init__ raises "
            "before returning, only the exception is accessible."
        ),
        "model_manager_log": "",
        "f_model_manager_log_note": (
            "mmtbx.f_model.manager.__init__ accepts no log parameter in "
            "PHENIX 2.0-5936."
        ),
        "fmodel_update_all_scales_log": "",
        "partial_evidence_json_path": str(effective_partial_json_path),
        "partial_evidence_status": "running_partial_unverified",
        "completed_raw_stages": [],
        "failure": None,
    }
    partial_evidence: dict[str, Any] = {
        "schema_version": 1,
        "artifact_role": "partial_unverified_phenix_evidence",
        "reusable_cache_output": False,
        "canonical_eval_qds_eligible": False,
        "algorithm": "mmtbx.model_vs_data.first_block_public_api",
        "status": "running_partial_unverified",
        "current_phase": "parameter_validation",
        "phase_history": ["parameter_validation"],
        "completed_stages": [],
        "rfactor_replay_verified": False,
        "map_export_verified": False,
        "expected_resolved_prefix": None,
        "expected_phenix_version": None,
        "runtime_environment": None,
        "crystal_symmetry": None,
        "extraction": None,
        "extracted_pre_fmodel": None,
        "xray_structure_snapshots_raw": {
            "before": None,
            "after_model": None,
            "after_fmodel": None,
            "invariance_verified": False,
        },
        "xray_structure_invariance": None,
        "final_effective": None,
        "actual_work": None,
        "actual_free": None,
        "resolution_ranges": None,
        "scales_and_rfactors": None,
        "rfactor_replay_comparison": None,
        "map_coefficients": None,
        "nonfinite_raw_values": [],
        "failure": None,
    }
    current_phase = "parameter_validation"

    def _enter_phase(phase: str) -> None:
        nonlocal current_phase
        current_phase = phase
        diagnostics["current_phase"] = phase
        partial_evidence["current_phase"] = phase
        if (
            not diagnostics["phase_history"]
            or diagnostics["phase_history"][-1] != phase
        ):
            diagnostics["phase_history"].append(phase)
        partial_evidence["phase_history"] = list(diagnostics["phase_history"])
        _checkpoint_diagnostics(diagnostics, out_diagnostics_json_path)

    def _checkpoint_partial_stage(stage_name: str | None = None) -> None:
        if stage_name is not None and (
            not partial_evidence["completed_stages"]
            or partial_evidence["completed_stages"][-1] != stage_name
        ):
            partial_evidence["completed_stages"].append(stage_name)
        partial_evidence["current_phase"] = current_phase
        partial_evidence["phase_history"] = list(diagnostics["phase_history"])
        diagnostics["partial_evidence_status"] = partial_evidence["status"]
        diagnostics["completed_raw_stages"] = list(
            partial_evidence["completed_stages"]
        )
        _prepare_partial_evidence_for_checkpoint(partial_evidence)
        _atomic_write_json_checkpoint(
            partial_evidence,
            effective_partial_json_path,
            allow_nonfinite_tags=True,
        )
        _checkpoint_diagnostics(diagnostics, out_diagnostics_json_path)

    _checkpoint_diagnostics(diagnostics, out_diagnostics_json_path)
    try:
        params = json.loads(params_path.read_text(encoding="utf-8"))
        validate_parameters_contract(params)
        expected_resolved_prefix = str(
            Path(params["expected_resolved_prefix"]).resolve(strict=True)
        )
        expected_phenix_version = str(params["expected_phenix_version"])

        _enter_phase("vendor_imports")
        # Deferred vendor imports (executed only inside phenix.python).
        from cctbx import crystal
        from iotbx import extract_xtal_data
        import iotbx.mtz
        import iotbx.pdb
        from iotbx import reflection_file_reader
        from iotbx import reflection_file_utils
        import mmtbx.f_model.f_model as mmtbx_f_model_mod
        import mmtbx.map_tools
        import mmtbx.model
        import mmtbx.model_vs_data

        _enter_phase("runtime_environment_inspection")
        runtime_env = _inspect_vendor_modules(
            {
                "vendor_mmtbx_model_vs_data": mmtbx.model_vs_data,
                "vendor_iotbx_extract_xtal_data": extract_xtal_data,
                "vendor_iotbx_reflection_file_utils": reflection_file_utils,
                "vendor_mmtbx_f_model": mmtbx_f_model_mod,
                "vendor_mmtbx_map_tools": mmtbx.map_tools,
                "vendor_iotbx_mtz": iotbx.mtz,
            },
            expected_resolved_prefix=expected_resolved_prefix,
        )

        _enter_phase("pdb_input")
        pdb_inp = iotbx.pdb.input(file_name=str(pdb_path))
        pdb_symmetry = pdb_inp.crystal_symmetry()
        if (
            pdb_symmetry is None
            or pdb_symmetry.unit_cell() is None
            or pdb_symmetry.space_group_info() is None
        ):
            raise RuntimeError("Model PDB is missing complete crystal_symmetry")
        _extract_runtime_crystal_symmetry_record(
            pdb_symmetry, label="Model PDB crystal_symmetry"
        )

        _enter_phase("reflection_file_input")
        reflection_file = reflection_file_reader.any_reflection_file(
            file_name=str(mtz_path)
        )
        reflection_arrays = reflection_file.as_miller_arrays()
        if not reflection_arrays:
            raise RuntimeError(
                "No reflection Miller arrays available in MTZ for symmetry selection"
            )
        reflection_symmetries = []
        ref_cell_and_sg = None
        for arr in reflection_arrays:
            arr_sym = arr.crystal_symmetry()
            if (
                arr_sym is None
                or arr_sym.unit_cell() is None
                or arr_sym.space_group_info() is None
            ):
                raise RuntimeError(
                    "Reflection Miller array is missing complete crystal_symmetry"
                )
            arr_sym_record = _extract_runtime_crystal_symmetry_record(
                arr_sym, label="Reflection Miller array crystal_symmetry"
            )
            key = (
                tuple(round(float(x), 6) for x in arr_sym_record["unit_cell"]),
                arr_sym_record["space_group_symbol"],
                arr_sym_record["space_group_number"],
                tuple(arr_sym_record["space_group_operators_xyz"]),
            )
            if ref_cell_and_sg is None:
                ref_cell_and_sg = key
            elif key != ref_cell_and_sg:
                raise RuntimeError(
                    f"Ambiguous reflection crystal_symmetry across Miller arrays: "
                    f"{ref_cell_and_sg} vs {key}"
                )
            reflection_symmetries.append(arr_sym)

        _enter_phase("crystal_symmetry_consensus")
        crystal_symmetry = crystal.select_crystal_symmetry(
            from_command_line=None,
            from_parameter_file=None,
            from_coordinate_files=[pdb_symmetry],
            from_reflection_files=[reflection_symmetries[0]],
            enforce_similarity=True,
            absolute_angle_tolerance=1.0e-2,
            absolute_length_tolerance=1.0e-2,
        )
        if (
            crystal_symmetry is None
            or crystal_symmetry.unit_cell() is None
            or crystal_symmetry.space_group_info() is None
        ):
            raise RuntimeError("Failed to determine consensus crystal_symmetry")
        crystal_symmetry_record = _extract_runtime_crystal_symmetry_record(
            crystal_symmetry, label="Consensus crystal_symmetry"
        )

        _enter_phase("extract_xtal_data")
        rfs = mmtbx.model_vs_data.reflection_file_server(
            crystal_symmetry=crystal_symmetry,
            reflection_files=[reflection_file],
        )
        extract_params = extract_xtal_data.data_and_flags_master_params().extract()
        extract_params.labels = ["F-obs", "SIGF-obs"]
        extract_params.r_free_flags.label = "R-free-flags"
        extract_params.r_free_flags.test_flag_value = 1
        extract_params.r_free_flags.generate = False
        extract_params.r_free_flags.ignore_r_free_flags = False

        df = extract_xtal_data.run(
            reflection_file_server=rfs,
            parameters=extract_params,
            keep_going=False,
        )
        # Retain df.log immediately after construction before checking errors or later work.
        extract_log_text = (
            df.log.getvalue() if getattr(df, "log", None) is not None else ""
        )
        diagnostics["extract_xtal_data_log"] = extract_log_text
        _emit_stage_log("extract_xtal_data.run (df.log)", extract_log_text)
        _checkpoint_diagnostics(diagnostics, out_diagnostics_json_path)

        err_list = [str(e) for e in getattr(df, "err", [])]
        if err_list:
            raise RuntimeError(f"extract_xtal_data reported errors: {err_list}")
        if df.f_obs is None or df.r_free_flags is None:
            raise RuntimeError("extract_xtal_data did not return f_obs and r_free_flags")
        if df.f_obs.sigmas() is None:
            raise RuntimeError("Extracted f_obs is missing sigmas")
        if int(df.test_flag_value) != 1:
            raise RuntimeError(
                f"Unexpected extracted test_flag_value: {df.test_flag_value!r}"
            )
        if not df.f_obs.indices().all_eq(df.r_free_flags.indices()):
            raise RuntimeError("Extracted f_obs and r_free_flags indices are not aligned")

        extracted_indices = list(df.f_obs.indices())
        extracted_f = list(df.f_obs.data())
        extracted_sigf = list(df.f_obs.sigmas())
        extracted_flags = [bool(flag) for flag in list(df.r_free_flags.data())]
        if not any(extracted_flags) or all(extracted_flags):
            raise RuntimeError(
                "Extracted r_free_flags must contain non-empty work and free sets"
            )
        extracted_rows: list[dict[str, Any]] = []
        for hkl, fo, sigfo, is_free in zip(
            extracted_indices, extracted_f, extracted_sigf, extracted_flags
        ):
            extracted_rows.append(
                {
                    "hkl": [int(hkl[0]), int(hkl[1]), int(hkl[2])],
                    "f_obs": float(fo),
                    "sigf_obs": float(sigfo),
                    "is_free": bool(is_free),
                }
            )

        extraction_record = {
            "labels": ["F-obs", "SIGF-obs"],
            "r_free_flags_label": "R-free-flags",
            "test_flag_value": int(df.test_flag_value),
            "r_free_flags_generate": False,
            "ignore_r_free_flags": False,
            "keep_going": False,
            "err": err_list,
            "log_text": extract_log_text,
            "applied_pdb_header_resolution_cut": False,
            "raw_data_info": (
                str(df.raw_data.info()) if df.raw_data is not None else None
            ),
            "raw_flags_info": (
                str(df.raw_flags.info()) if df.raw_flags is not None else None
            ),
        }
        partial_evidence["expected_resolved_prefix"] = expected_resolved_prefix
        partial_evidence["expected_phenix_version"] = expected_phenix_version
        partial_evidence["runtime_environment"] = copy.deepcopy(runtime_env)
        partial_evidence["crystal_symmetry"] = copy.deepcopy(
            crystal_symmetry_record
        )
        partial_evidence["extraction"] = copy.deepcopy(extraction_record)
        partial_evidence["extracted_pre_fmodel"] = copy.deepcopy(extracted_rows)
        if hasattr(df.f_obs, "d_max_min"):
            ext_dmax_pre, ext_dmin_pre = df.f_obs.d_max_min()
            partial_evidence["resolution_ranges"] = {
                "extracted_pre_fmodel": {
                    "d_max": float(ext_dmax_pre),
                    "d_min": float(ext_dmin_pre),
                }
            }
        _checkpoint_partial_stage("extract_xtal_data")

        def _record_raw_xrs_snapshot(
            stage_key: str, raw_snapshot: Mapping[str, Any]
        ) -> None:
            partial_evidence["xray_structure_snapshots_raw"][stage_key] = (
                copy.deepcopy(dict(raw_snapshot))
            )
            _checkpoint_partial_stage()

        _enter_phase("model_manager")
        model_log = _PersistentTeeLogStream(
            "mmtbx.model.manager",
            diagnostics,
            "model_manager_log",
            diagnostics_json_path=out_diagnostics_json_path,
        )
        try:
            model = mmtbx.model.manager(
                model_input=pdb_inp,
                crystal_symmetry=crystal_symmetry,
                log=model_log,
            )
            model.setup_scattering_dictionaries(
                scattering_table="n_gaussian",
                d_min=df.f_obs.d_min(),
            )
        finally:
            model_log.finalize()

        before_xrs_snapshot = _capture_xrs_snapshot(
            model.get_xray_structure(),
            on_raw_capture=lambda raw_snap: _record_raw_xrs_snapshot(
                "before", raw_snap
            ),
        )
        partial_evidence["xray_structure_snapshots_raw"]["before"] = (
            copy.deepcopy(before_xrs_snapshot)
        )
        _checkpoint_partial_stage("xray_structure_snapshot_before")

        _enter_phase("fmodel_manager_init")
        fmodel = mmtbx.f_model.manager(
            xray_structure=model.get_xray_structure(),
            r_free_flags=df.r_free_flags,
            f_obs=df.f_obs,
            twin_law=None,
        )

        _enter_phase("update_all_scales")
        fmodel_log = _PersistentTeeLogStream(
            "fmodel.update_all_scales",
            diagnostics,
            "fmodel_update_all_scales_log",
            diagnostics_json_path=out_diagnostics_json_path,
        )
        try:
            fmodel.update_all_scales(update_f_part1=True, log=fmodel_log)
        finally:
            fmodel_log.finalize()

        after_model_xrs_snapshot = _capture_xrs_snapshot(
            model.get_xray_structure(),
            on_raw_capture=lambda raw_snap: _record_raw_xrs_snapshot(
                "after_model", raw_snap
            ),
        )
        partial_evidence["xray_structure_snapshots_raw"]["after_model"] = (
            copy.deepcopy(after_model_xrs_snapshot)
        )
        _checkpoint_partial_stage("xray_structure_snapshot_after_model")

        after_fmodel_xrs_snapshot = _capture_xrs_snapshot(
            fmodel.xray_structure,
            on_raw_capture=lambda raw_snap: _record_raw_xrs_snapshot(
                "after_fmodel", raw_snap
            ),
        )
        partial_evidence["xray_structure_snapshots_raw"]["after_fmodel"] = (
            copy.deepcopy(after_fmodel_xrs_snapshot)
        )
        _checkpoint_partial_stage("xray_structure_snapshot_after_fmodel")

        xrs_invariance = compare_scatterer_snapshots(
            before_xrs_snapshot,
            after_model_xrs_snapshot,
            after_fmodel_xrs_snapshot,
        )
        partial_evidence["xray_structure_snapshots_raw"][
            "invariance_verified"
        ] = True
        partial_evidence["xray_structure_invariance"] = copy.deepcopy(
            xrs_invariance
        )
        _checkpoint_partial_stage("xray_structure_invariance")

        _enter_phase("rfactor_replay")
        final_f_obs_arr = fmodel.f_obs()
        final_flags_arr = fmodel.r_free_flags()
        if final_f_obs_arr.sigmas() is None:
            raise RuntimeError("fmodel.f_obs() sigmas are None")
        if not final_f_obs_arr.indices().all_eq(final_flags_arr.indices()):
            raise RuntimeError(
                "fmodel.f_obs() and fmodel.r_free_flags() indices disagree"
            )

        final_rows: list[dict[str, Any]] = []
        sigmas_by_hkl: dict[tuple[int, int, int], float] = {}
        for hkl, fo, sigfo, is_free in zip(
            list(final_f_obs_arr.indices()),
            list(final_f_obs_arr.data()),
            list(final_f_obs_arr.sigmas()),
            list(final_flags_arr.data()),
        ):
            hkl_tuple = (int(hkl[0]), int(hkl[1]), int(hkl[2]))
            sigmas_by_hkl[hkl_tuple] = float(sigfo)
            final_rows.append(
                {
                    "hkl": [hkl_tuple[0], hkl_tuple[1], hkl_tuple[2]],
                    "f_obs": float(fo),
                    "sigf_obs": float(sigfo),
                    "is_free": bool(is_free),
                }
            )
        partial_evidence["final_effective"] = copy.deepcopy(final_rows)
        if hasattr(final_f_obs_arr, "d_max_min"):
            fin_dmax_pre, fin_dmin_pre = final_f_obs_arr.d_max_min()
            if not isinstance(partial_evidence.get("resolution_ranges"), dict):
                partial_evidence["resolution_ranges"] = {}
            partial_evidence["resolution_ranges"]["final_effective"] = {
                "d_max": float(fin_dmax_pre),
                "d_min": float(fin_dmin_pre),
            }
        _checkpoint_partial_stage("final_effective_raw")

        f_obs_work_arr = fmodel.f_obs_work()
        f_model_work_arr = fmodel.f_model_work()
        f_model_scaled_w_arr = fmodel.f_model_scaled_with_k1_w()
        if not (
            f_obs_work_arr.indices().all_eq(f_model_work_arr.indices())
            and f_obs_work_arr.indices().all_eq(f_model_scaled_w_arr.indices())
        ):
            raise RuntimeError("Work reflection array indices are not aligned")

        work_sigmas = (
            list(f_obs_work_arr.sigmas())
            if f_obs_work_arr.sigmas() is not None
            else [
                sigmas_by_hkl[(int(h[0]), int(h[1]), int(h[2]))]
                for h in list(f_obs_work_arr.indices())
            ]
        )
        actual_work_rows: list[dict[str, Any]] = []
        for hkl, fo, sigfo, fm_raw, fm_scaled in zip(
            list(f_obs_work_arr.indices()),
            list(f_obs_work_arr.data()),
            work_sigmas,
            list(f_model_work_arr.data()),
            list(f_model_scaled_w_arr.data()),
        ):
            actual_work_rows.append(
                {
                    "hkl": [int(hkl[0]), int(hkl[1]), int(hkl[2])],
                    "f_obs": float(fo),
                    "sigf_obs": float(sigfo),
                    "f_model_real": float(fm_raw.real),
                    "f_model_imag": float(fm_raw.imag),
                    "f_model_amplitude": float(abs(fm_raw)),
                    "f_model_scaled_with_k1_w_real": float(fm_scaled.real),
                    "f_model_scaled_with_k1_w_imag": float(fm_scaled.imag),
                    "f_model_scaled_with_k1_w_amplitude": float(abs(fm_scaled)),
                }
            )
        partial_evidence["actual_work"] = copy.deepcopy(actual_work_rows)
        if hasattr(f_obs_work_arr, "d_max_min"):
            work_dmax_pre, work_dmin_pre = f_obs_work_arr.d_max_min()
            if not isinstance(partial_evidence.get("resolution_ranges"), dict):
                partial_evidence["resolution_ranges"] = {}
            partial_evidence["resolution_ranges"]["actual_work"] = {
                "d_max": float(work_dmax_pre),
                "d_min": float(work_dmin_pre),
            }
        _checkpoint_partial_stage("actual_work_raw")

        f_obs_free_arr = fmodel.f_obs_free()
        f_model_free_arr = fmodel.f_model_free()
        f_model_scaled_t_arr = fmodel.f_model_scaled_with_k1_t()
        if not (
            f_obs_free_arr.indices().all_eq(f_model_free_arr.indices())
            and f_obs_free_arr.indices().all_eq(f_model_scaled_t_arr.indices())
        ):
            raise RuntimeError("Free reflection array indices are not aligned")

        free_sigmas = (
            list(f_obs_free_arr.sigmas())
            if f_obs_free_arr.sigmas() is not None
            else [
                sigmas_by_hkl[(int(h[0]), int(h[1]), int(h[2]))]
                for h in list(f_obs_free_arr.indices())
            ]
        )
        actual_free_rows: list[dict[str, Any]] = []
        for hkl, fo, sigfo, fm_raw, fm_scaled in zip(
            list(f_obs_free_arr.indices()),
            list(f_obs_free_arr.data()),
            free_sigmas,
            list(f_model_free_arr.data()),
            list(f_model_scaled_t_arr.data()),
        ):
            actual_free_rows.append(
                {
                    "hkl": [int(hkl[0]), int(hkl[1]), int(hkl[2])],
                    "f_obs": float(fo),
                    "sigf_obs": float(sigfo),
                    "f_model_real": float(fm_raw.real),
                    "f_model_imag": float(fm_raw.imag),
                    "f_model_amplitude": float(abs(fm_raw)),
                    "f_model_scaled_with_k1_t_real": float(fm_scaled.real),
                    "f_model_scaled_with_k1_t_imag": float(fm_scaled.imag),
                    "f_model_scaled_with_k1_t_amplitude": float(abs(fm_scaled)),
                }
            )
        partial_evidence["actual_free"] = copy.deepcopy(actual_free_rows)
        if hasattr(f_obs_free_arr, "d_max_min"):
            free_dmax_pre, free_dmin_pre = f_obs_free_arr.d_max_min()
            if not isinstance(partial_evidence.get("resolution_ranges"), dict):
                partial_evidence["resolution_ranges"] = {}
            partial_evidence["resolution_ranges"]["actual_free"] = {
                "d_max": float(free_dmax_pre),
                "d_min": float(free_dmin_pre),
            }
        _checkpoint_partial_stage("actual_free_raw")

        scale_k1_w_val = float(fmodel.scale_k1_w())
        scale_k1_t_val = float(fmodel.scale_k1_t())
        scale_k1_val = float(fmodel.scale_k1())

        work_replay = compute_rfactor_from_arrays(
            [r["f_obs"] for r in actual_work_rows],
            [r["f_model_scaled_with_k1_w_amplitude"] for r in actual_work_rows],
        )
        free_replay = compute_rfactor_from_arrays(
            [r["f_obs"] for r in actual_free_rows],
            [r["f_model_scaled_with_k1_t_amplitude"] for r in actual_free_rows],
        )
        all_rows = actual_work_rows + actual_free_rows
        all_replay = compute_rfactor_from_arrays(
            [r["f_obs"] for r in all_rows],
            [scale_k1_val * r["f_model_amplitude"] for r in all_rows],
        )
        native_r_work = float(fmodel.r_work())
        native_r_free = float(fmodel.r_free())
        native_r_all = float(fmodel.r_all())

        ext_dmax, ext_dmin = df.f_obs.d_max_min()
        fin_dmax, fin_dmin = final_f_obs_arr.d_max_min()
        work_dmax, work_dmin = f_obs_work_arr.d_max_min()
        free_dmax, free_dmin = f_obs_free_arr.d_max_min()
        resolution_ranges_record = {
            "extracted_pre_fmodel": {
                "d_max": float(ext_dmax),
                "d_min": float(ext_dmin),
            },
            "final_effective": {
                "d_max": float(fin_dmax),
                "d_min": float(fin_dmin),
            },
            "actual_work": {
                "d_max": float(work_dmax),
                "d_min": float(work_dmin),
            },
            "actual_free": {
                "d_max": float(free_dmax),
                "d_min": float(free_dmin),
            },
        }
        scales_and_rfactors_record = {
            "r_work": native_r_work,
            "r_free": native_r_free,
            "r_all": native_r_all,
            "r_free_r_work_gap": native_r_free - native_r_work,
            "scale_k1_w": scale_k1_w_val,
            "scale_k1_t": scale_k1_t_val,
            "scale_k1": scale_k1_val,
            "work_numerator": work_replay["numerator"],
            "work_denominator": work_replay["denominator"],
            "free_numerator": free_replay["numerator"],
            "free_denominator": free_replay["denominator"],
            "all_numerator": all_replay["numerator"],
            "all_denominator": all_replay["denominator"],
            "work_count": len(actual_work_rows),
            "free_count": len(actual_free_rows),
            "final_effective_count": len(final_rows),
            "extracted_pre_fmodel_count": len(extracted_rows),
        }

        # Checkpoint completed raw R-factor arrays and both native/replayed scalars
        # BEFORE scaled-complex and native-vs-replayed R-factor assertions (#1014).
        partial_evidence["final_effective"] = copy.deepcopy(final_rows)
        partial_evidence["actual_work"] = copy.deepcopy(actual_work_rows)
        partial_evidence["actual_free"] = copy.deepcopy(actual_free_rows)
        partial_evidence["resolution_ranges"] = copy.deepcopy(
            resolution_ranges_record
        )
        partial_evidence["scales_and_rfactors"] = {
            **scales_and_rfactors_record,
            "replayed_r_work": work_replay["r_factor"],
            "replayed_r_free": free_replay["r_factor"],
            "replayed_r_all": all_replay["r_factor"],
            "replayed_r_free_r_work_gap": (
                free_replay["r_factor"] - work_replay["r_factor"]
            ),
        }
        partial_evidence["rfactor_replay_comparison"] = {
            "native_r_work": native_r_work,
            "replayed_r_work": work_replay["r_factor"],
            "r_work_abs_diff": abs(native_r_work - work_replay["r_factor"]),
            "native_r_free": native_r_free,
            "replayed_r_free": free_replay["r_factor"],
            "r_free_abs_diff": abs(native_r_free - free_replay["r_factor"]),
            "native_r_all": native_r_all,
            "replayed_r_all": all_replay["r_factor"],
            "r_all_abs_diff": abs(native_r_all - all_replay["r_factor"]),
            "work_numerator": work_replay["numerator"],
            "work_denominator": work_replay["denominator"],
            "free_numerator": free_replay["numerator"],
            "free_denominator": free_replay["denominator"],
            "all_numerator": all_replay["numerator"],
            "all_denominator": all_replay["denominator"],
            "scale_k1_w": scale_k1_w_val,
            "scale_k1_t": scale_k1_t_val,
            "scale_k1": scale_k1_val,
        }
        _checkpoint_partial_stage("rfactor_raw_arrays_and_scalars")

        for row in actual_work_rows:
            if not math.isclose(
                row["f_model_scaled_with_k1_w_real"],
                scale_k1_w_val * row["f_model_real"],
                rel_tol=1e-12,
                abs_tol=1e-12,
            ) or not math.isclose(
                row["f_model_scaled_with_k1_w_imag"],
                scale_k1_w_val * row["f_model_imag"],
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                raise RuntimeError(
                    f"Work reflection {row['hkl']} scaled complex coefficient "
                    f"({row['f_model_scaled_with_k1_w_real']}, "
                    f"{row['f_model_scaled_with_k1_w_imag']}) disagrees with "
                    f"scale_k1_w * f_model_work"
                )
        for row in actual_free_rows:
            if not math.isclose(
                row["f_model_scaled_with_k1_t_real"],
                scale_k1_t_val * row["f_model_real"],
                rel_tol=1e-12,
                abs_tol=1e-12,
            ) or not math.isclose(
                row["f_model_scaled_with_k1_t_imag"],
                scale_k1_t_val * row["f_model_imag"],
                rel_tol=1e-12,
                abs_tol=1e-12,
            ):
                raise RuntimeError(
                    f"Free reflection {row['hkl']} scaled complex coefficient "
                    f"({row['f_model_scaled_with_k1_t_real']}, "
                    f"{row['f_model_scaled_with_k1_t_imag']}) disagrees with "
                    f"scale_k1_t * f_model_free"
                )

        if not math.isclose(
            work_replay["r_factor"], native_r_work, rel_tol=1e-12, abs_tol=1e-12
        ):
            raise RuntimeError(
                f"Native fmodel.r_work() {native_r_work} disagrees with array replay "
                f"{work_replay['r_factor']}"
            )
        if not math.isclose(
            free_replay["r_factor"], native_r_free, rel_tol=1e-12, abs_tol=1e-12
        ):
            raise RuntimeError(
                f"Native fmodel.r_free() {native_r_free} disagrees with array replay "
                f"{free_replay['r_factor']}"
            )
        if not math.isclose(
            all_replay["r_factor"], native_r_all, rel_tol=1e-12, abs_tol=1e-12
        ):
            raise RuntimeError(
                f"Native fmodel.r_all() {native_r_all} disagrees with array replay "
                f"{all_replay['r_factor']}"
            )

        partial_evidence["rfactor_replay_verified"] = True
        _checkpoint_partial_stage("rfactor_replay_verified")

        _enter_phase("map_export")
        map_params_record = {
            "acentrics_scale": 2.0,
            "centrics_pre_scale": 1.0,
            "exclude_free_r_reflections": False,
            "fill_missing": False,
            "isotropize": True,
            "sharp": False,
        }
        coeff_semantics = (
            "cctbx_map_tools_combine_already_incorporates_centric_and_acentric_scales_"
            "do_not_double_acentrics_again"
        )
        # Fresh complex map coefficients from the same first-block fmodel.
        mc_2mfo_dfc = fmodel.map_coefficients(
            map_type="2mFo-DFc",
            acentrics_scale=2.0,
            centrics_pre_scale=1.0,
            exclude_free_r_reflections=False,
            fill_missing=False,
            isotropize=True,
            sharp=False,
        )
        if mc_2mfo_dfc is None:
            raise RuntimeError("fmodel.map_coefficients returned None")
        map_2mfo_payload = _export_map_records(mc_2mfo_dfc)
        partial_evidence["map_coefficients"] = {
            "2mFo-DFc": {
                "map_type": "2mFo-DFc",
                "amplitude_label": "2FOFCWT",
                "phase_label": "PH2FOFCWT",
                "parameters": dict(map_params_record),
                "coefficient_semantics": coeff_semantics,
                **copy.deepcopy(map_2mfo_payload),
            },
            "mFo-DFc": None,
            "mtz_supplements": None,
        }
        _checkpoint_partial_stage("map_coefficients_2mfo_dfc_raw")

        mc_mfo_dfc = fmodel.map_coefficients(
            map_type="mFo-DFc",
            acentrics_scale=2.0,
            centrics_pre_scale=1.0,
            exclude_free_r_reflections=False,
            fill_missing=False,
            isotropize=True,
            sharp=False,
        )
        if mc_mfo_dfc is None:
            raise RuntimeError("fmodel.map_coefficients returned None")
        map_mfo_payload = _export_map_records(mc_mfo_dfc)
        partial_evidence["map_coefficients"]["mFo-DFc"] = {
            "map_type": "mFo-DFc",
            "amplitude_label": "FOFCWT",
            "phase_label": "PHFOFCWT",
            "parameters": dict(map_params_record),
            "coefficient_semantics": coeff_semantics,
            **copy.deepcopy(map_mfo_payload),
        }
        _checkpoint_partial_stage("map_coefficients_raw")

        decorator = iotbx.mtz.label_decorator(phases_prefix="PH")
        maps_dataset = mc_2mfo_dfc.as_mtz_dataset(
            column_root_label="2FOFCWT",
            label_decorator=decorator,
        )
        maps_dataset.add_miller_array(
            miller_array=mc_mfo_dfc,
            column_root_label="FOFCWT",
            label_decorator=decorator,
        )
        maps_mtz_obj = maps_dataset.mtz_object()
        maps_columns = [str(lbl) for lbl in maps_mtz_obj.column_labels()]
        if maps_columns != [
            "H",
            "K",
            "L",
            "2FOFCWT",
            "PH2FOFCWT",
            "FOFCWT",
            "PHFOFCWT",
        ]:
            raise RuntimeError(f"Unexpected phx_maps.mtz column labels: {maps_columns}")
        maps_mtz_obj.write(file_name=str(out_maps_mtz_path))

        obs_pair_dataset = mc_2mfo_dfc.as_mtz_dataset(
            column_root_label="2FOFCWT",
            label_decorator=decorator,
        )
        obs_pair_mtz_obj = obs_pair_dataset.mtz_object()
        obs_pair_columns = [str(lbl) for lbl in obs_pair_mtz_obj.column_labels()]
        if obs_pair_columns != ["H", "K", "L", "2FOFCWT", "PH2FOFCWT"]:
            raise RuntimeError(
                f"Unexpected PHX_OBS_PAIR_ONLY.mtz column labels: {obs_pair_columns}"
            )
        obs_pair_mtz_obj.write(file_name=str(out_obs_pair_mtz_path))

        maps_readback = iotbx.mtz.object(file_name=str(out_maps_mtz_path))
        maps_column_types = [str(col.type()) for col in maps_readback.columns()]
        if [str(col.label()) for col in maps_readback.columns()] != maps_columns:
            raise RuntimeError("Read-back phx_maps.mtz column labels mismatch")
        if maps_column_types != ["H", "H", "H", "F", "P", "F", "P"]:
            raise RuntimeError(
                f"Read-back phx_maps.mtz column types mismatch: {maps_column_types}"
            )
        if int(maps_readback.n_reflections()) != len(final_rows):
            raise RuntimeError(
                f"Read-back phx_maps.mtz reflection count {maps_readback.n_reflections()} "
                f"!= final_effective {len(final_rows)}"
            )

        obs_pair_readback = iotbx.mtz.object(file_name=str(out_obs_pair_mtz_path))
        obs_pair_column_types = [
            str(col.type()) for col in obs_pair_readback.columns()
        ]
        if [str(col.label()) for col in obs_pair_readback.columns()] != obs_pair_columns:
            raise RuntimeError("Read-back PHX_OBS_PAIR_ONLY.mtz column labels mismatch")
        if obs_pair_column_types != ["H", "H", "H", "F", "P"]:
            raise RuntimeError(
                "Read-back PHX_OBS_PAIR_ONLY.mtz column types mismatch: "
                f"{obs_pair_column_types}"
            )
        if int(obs_pair_readback.n_reflections()) != len(final_rows):
            raise RuntimeError(
                "Read-back PHX_OBS_PAIR_ONLY.mtz reflection count "
                f"{obs_pair_readback.n_reflections()} != final_effective {len(final_rows)}"
            )

        mtz_supplements_record = {
            "precision_note": (
                "MTZ files store float32 amplitudes and phases as a supplement "
                "for downstream CCP4/Gemmi FFT consumers; full-precision float64 "
                "complex coefficients are retained in this JSON payload."
            ),
            "phx_maps_filename": out_maps_mtz_path.name,
            "phx_maps_sha256": _sha256_file_py39(out_maps_mtz_path),
            "phx_maps_columns": maps_columns,
            "phx_maps_column_types": maps_column_types,
            "obs_pair_only_filename": out_obs_pair_mtz_path.name,
            "obs_pair_only_sha256": _sha256_file_py39(out_obs_pair_mtz_path),
            "obs_pair_only_columns": obs_pair_columns,
            "obs_pair_only_column_types": obs_pair_column_types,
        }
        partial_evidence["map_coefficients"]["mtz_supplements"] = copy.deepcopy(
            mtz_supplements_record
        )
        partial_evidence["map_export_verified"] = True
        partial_evidence["status"] = "completed_superseded_by_verified_payload"
        current_phase = "completed"
        diagnostics["status"] = "succeeded"
        diagnostics["current_phase"] = "completed"
        diagnostics["phase_history"].append("completed")
        _checkpoint_partial_stage("map_export_verified")

        payload: dict[str, Any] = {
            "schema_version": 1,
            "algorithm": "mmtbx.model_vs_data.first_block_public_api",
            "expected_resolved_prefix": expected_resolved_prefix,
            "expected_phenix_version": expected_phenix_version,
            "runtime_environment": runtime_env,
            "diagnostics": copy.deepcopy(diagnostics),
            "crystal_symmetry": crystal_symmetry_record,
            "extraction": extraction_record,
            "resolution_ranges": resolution_ranges_record,
            "xray_structure_invariance": xrs_invariance,
            "scales_and_rfactors": scales_and_rfactors_record,
            "extracted_pre_fmodel": extracted_rows,
            "final_effective": final_rows,
            "actual_work": actual_work_rows,
            "actual_free": actual_free_rows,
            "map_coefficients": {
                "2mFo-DFc": {
                    "map_type": "2mFo-DFc",
                    "amplitude_label": "2FOFCWT",
                    "phase_label": "PH2FOFCWT",
                    "parameters": dict(map_params_record),
                    "coefficient_semantics": coeff_semantics,
                    **map_2mfo_payload,
                },
                "mFo-DFc": {
                    "map_type": "mFo-DFc",
                    "amplitude_label": "FOFCWT",
                    "phase_label": "PHFOFCWT",
                    "parameters": dict(map_params_record),
                    "coefficient_semantics": coeff_semantics,
                    **map_mfo_payload,
                },
                "mtz_supplements": mtz_supplements_record,
            },
        }

        _atomic_write_json_checkpoint(payload, out_json_path)
        return payload
    except Exception as exc:
        limitation = None
        if (
            current_phase == "extract_xtal_data"
            and diagnostics["extract_xtal_data_log"] is None
        ):
            limitation = (
                "extract_xtal_data.run raised before returning; internal "
                "self.log StringIO on the unreturned instance is not accessible."
            )
        elif current_phase == "fmodel_manager_init":
            limitation = (
                "mmtbx.f_model.manager.__init__ accepts no log parameter "
                "in PHENIX 2.0-5936; no internal constructor log stream exists."
            )
        failure_record = {
            "failed_phase": current_phase,
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "constructor_log_limitation": limitation,
        }
        partial_evidence["status"] = "failed_partial_unverified"
        partial_evidence["current_phase"] = current_phase
        partial_evidence["phase_history"] = list(diagnostics["phase_history"])
        partial_evidence["failure"] = copy.deepcopy(failure_record)
        diagnostics["status"] = "failed"
        diagnostics["current_phase"] = current_phase
        diagnostics["partial_evidence_status"] = partial_evidence["status"]
        diagnostics["completed_raw_stages"] = list(
            partial_evidence["completed_stages"]
        )
        diagnostics["failure"] = failure_record
        try:
            _prepare_partial_evidence_for_checkpoint(partial_evidence)
            _atomic_write_json_checkpoint(
                partial_evidence,
                effective_partial_json_path,
                allow_nonfinite_tags=True,
            )
            _checkpoint_diagnostics(diagnostics, out_diagnostics_json_path)
            sys.stderr.write(
                "=== [onesar_phenix_measure] FAILURE DIAGNOSTIC ===\n"
                + json.dumps(
                    encode_raw_evidence_nonfinite(diagnostics["failure"]),
                    indent=2,
                    sort_keys=True,
                    allow_nan=False,
                )
                + "\n"
            )
            sys.stderr.flush()
        except Exception as checkpoint_exc:
            sys.stderr.write(
                "=== [onesar_phenix_measure] CHECKPOINT SERIALIZATION WARNING ===\n"
                f"{type(checkpoint_exc).__name__}: {checkpoint_exc}\n"
            )
            sys.stderr.flush()
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run first-block PHENIX model_vs_data R-factor and map export."
    )
    parser.add_argument("--pdb", required=True, type=Path)
    parser.add_argument("--mtz", required=True, type=Path)
    parser.add_argument("--params-json", required=True, type=Path)
    parser.add_argument("--out-json", required=True, type=Path)
    parser.add_argument("--out-diagnostics-json", default=None, type=Path)
    parser.add_argument("--out-partial-json", default=None, type=Path)
    parser.add_argument("--out-maps-mtz", required=True, type=Path)
    parser.add_argument("--out-obs-pair-mtz", required=True, type=Path)
    args = parser.parse_args(argv)

    measure_first_block_rfactors(
        pdb_path=args.pdb.resolve(strict=True),
        mtz_path=args.mtz.resolve(strict=True),
        params_path=args.params_json.resolve(strict=True),
        out_json_path=args.out_json,
        out_maps_mtz_path=args.out_maps_mtz,
        out_obs_pair_mtz_path=args.out_obs_pair_mtz,
        out_diagnostics_json_path=args.out_diagnostics_json,
        out_partial_json_path=args.out_partial_json,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
