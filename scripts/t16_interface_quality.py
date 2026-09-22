#!/usr/bin/env python3
"""Compute the T16 interface-quality metrics with DockQ.

Runs DockQ (Basu & Wallner 2016) on a model complex against a native/reference
complex and reports the DockQ score plus its CAPRI quality class. DockQ is
non-cctbx and non-PHENIX; the deposited biological assembly is the reference,
which is the trust model's tiebreaker for T16 (there is no PHENIX interface
scorer, so this is oracle-only).

Emits pasteable EvaluationMeasurement rows:
  - T16_interface_buried_surface_area (value_numeric, Å² — from the model alone)
  - T16_interface_dockq_score         (value_numeric = DockQ, the gradeable metric —
                                       only when a native reference is given)
  - T16_capri_interface_quality_class (value_text = High/Medium/Acceptable/Incorrect,
                                       informational — derived from the DockQ score)

Buried surface area is a property of the model complex and needs no reference, so
it is always emitted (via biotite's Shrake-Rupley SASA — an installable stand-in
for the PISA web service). DockQ needs a native/deposited reference, so it and the
CAPRI class are emitted only when `--native` is supplied.

Degrades loudly: if DockQ (with `--native`) or biotite is unavailable, exits
non-zero with a clear message rather than fabricating a value.

Usage:
    python3 scripts/t16_interface_quality.py model.pdb --native native.pdb \
      --reference-subject-ref pdb:1abc --mapping AB:AB --interface-id IFACE_AB_ID \
      --raw-json evidence/model_AB_AB.dockq.json --eval-id EVAL_...
    python3 scripts/t16_interface_quality.py model.pdb --chains A:B  # BSA only
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import yaml

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from toolchain import run_capture

REPO = Path(__file__).resolve().parent.parent

# CAPRI quality classes by DockQ score. Basu & Wallner, "DockQ: A Quality Measure
# for Protein-Protein Docking Models", PLOS ONE 2016; 11(8):e0161879.
# High >= 0.80; Medium [0.49, 0.80); Acceptable [0.23, 0.49); Incorrect < 0.23.
_CAPRI_BANDS = ((0.80, "High"), (0.49, "Medium"), (0.23, "Acceptable"))


def _fail(msg: str) -> None:
    """Exit non-zero with a clear oracle-status message (never a fabricated value)."""
    raise SystemExit(f"t16_interface_quality: {msg}")


def capri_class(dockq: float) -> str:
    """Map a DockQ score to its CAPRI quality class."""
    for threshold, label in _CAPRI_BANDS:
        if dockq >= threshold:
            return label
    return "Incorrect"


def buried_surface_area(complex_sasa: float, separated_sasa: float) -> float:
    """Total interface area buried on complex formation: ΣSASA(chains) − SASA(complex)."""
    return round(separated_sasa - complex_sasa, 1)


def run_biotite_bsa(
    model: Path, selected_chains: tuple[str, str] | None = None
) -> dict[str, Any]:
    """Compute total two-sided BSA for exactly one selected chain pair."""
    try:
        import numpy as np
        import biotite.structure as struc
        import biotite.structure.io.pdb as pdb
    except ImportError:
        _fail("biotite not importable — install it (`pip install biotite`).")
    prot = struc.filter_amino_acids
    arr = pdb.get_structure(pdb.PDBFile.read(str(model)), model=1)
    atoms = arr[prot(arr)]
    available = sorted(set(atoms.chain_id))
    if selected_chains is None:
        if len(available) != 2:
            _fail(
                "BSA requires exactly two protein chains or an explicit --chains A:B "
                f"selector; model contains {available}."
            )
        chains = available
    else:
        chains = list(selected_chains)
        missing = [chain for chain in chains if chain not in available]
        if missing:
            _fail(f"selected chain(s) {missing} absent from model; available: {available}.")
        atoms = atoms[(atoms.chain_id == chains[0]) | (atoms.chain_id == chains[1])]
    complex_sasa = float(np.nansum(struc.sasa(atoms)))
    separated = sum(float(np.nansum(struc.sasa(atoms[atoms.chain_id == c]))) for c in chains)
    return {
        "bsa": buried_surface_area(complex_sasa, separated),
        "chains": chains,
        "complex_sasa": round(complex_sasa, 1),
    }


def run_dockq(
    model: Path, native: Path, mapping: str, raw_json_path: Path
) -> dict[str, Any]:
    """Run one explicit DockQ mapping and retain its exact JSON output."""
    exe = shutil.which("DockQ")
    if exe is None:
        _fail("DockQ not found on PATH — install it (`pip install DockQ`).")
    if raw_json_path.exists():
        _fail(f"raw DockQ evidence already exists; refusing to overwrite: {raw_json_path}")
    raw_json_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [exe, "--json", str(raw_json_path), str(model), str(native), "--mapping", mapping]
    proc = run_capture(cmd)
    if proc.returncode != 0:
        _fail(f"DockQ failed ({proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}")
    if not raw_json_path.is_file() or not raw_json_path.stat().st_size:
        _fail(f"DockQ produced no output: {proc.stderr.strip() or proc.stdout.strip()}")
    try:
        return json.loads(raw_json_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        _fail(f"retained DockQ output is not valid JSON ({raw_json_path}): {exc}")


def extract(result: dict[str, Any]) -> dict[str, Any]:
    """Pull the global DockQ score and per-interface breakdown from DockQ JSON."""
    dockq = result.get("GlobalDockQ", result.get("best_dockq"))
    if dockq is None:
        _fail("DockQ JSON has no GlobalDockQ/best_dockq field — cannot score.")
    interfaces = {
        name: {
            "dockq": round(iface.get("DockQ", 0.0), 4),
            "irmsd": round(iface.get("iRMSD", 0.0), 3),
            "lrmsd": round(iface.get("LRMSD", 0.0), 3),
            "fnat": round(iface.get("fnat", 0.0), 4),
        }
        for name, iface in (result.get("best_result") or {}).items()
    }
    return {
        "dockq": round(float(dockq), 4),
        "capri": capri_class(float(dockq)),
        "mapping": result.get("best_mapping_str", ""),
        "interfaces": interfaces,
    }


def render_yaml(
    summary: dict[str, Any],
    eval_id: str,
    interface_id: str,
    subject_ref: str,
    reference_subject_ref: str,
    evidence_ref: str,
) -> str:
    """Emit the two T16 measurement rows (numeric score + informational class)."""
    n_iface = len(summary["interfaces"])
    row_suffix = re.sub(r"[^A-Za-z0-9]+", "_", interface_id).strip("_")
    score_row = {
        "id": f"{eval_id}_M_T16_dockq_{row_suffix}",
        "catalog_task_ref": "T16",
        "stage": "final",
        "scope": "interface",
        "scope_selector": interface_id,
        "subject_ref": subject_ref,
        "reference_subject_ref": reference_subject_ref,
        "metric_definition_ref": "T16_interface_dockq_score",
        "oracle_tool_ref": "DockQ",
        "oracle_family": "non_cctbx",
        "oracle_measure": {"value_numeric": summary["dockq"]},
        "pass_status": "informational",
        "evidence_refs": [evidence_ref],
        "notes": f"DockQ vs reference over {n_iface} interface(s), mapping {summary['mapping']}.",
    }
    class_row = {
        "id": f"{eval_id}_M_T16_capri_{row_suffix}",
        "catalog_task_ref": "T16",
        "stage": "final",
        "scope": "interface",
        "scope_selector": interface_id,
        "subject_ref": subject_ref,
        "reference_subject_ref": reference_subject_ref,
        "metric_definition_ref": "T16_capri_interface_quality_class",
        "oracle_tool_ref": "DockQ",
        "oracle_family": "non_cctbx",
        "oracle_measure": {"value_text": summary["capri"]},
        "pass_status": "informational",
        "evidence_refs": [evidence_ref],
        "notes": (
            "CAPRI class derived from DockQ score (Basu & Wallner 2016 bands), "
            f"mapping {summary['mapping']}."
        ),
    }
    return yaml.safe_dump([score_row, class_row], sort_keys=False, allow_unicode=True, width=100)


def render_bsa_yaml(
    bsa: dict[str, Any],
    eval_id: str,
    interface_id: str,
    subject_ref: str | None = None,
) -> str:
    """Emit the buried-surface-area measurement row."""
    row = {
        "id": f"{eval_id}_M_T16_bsa",
        "catalog_task_ref": "T16",
        "stage": "final",
        "scope": "interface",
        "scope_selector": interface_id,
        "metric_definition_ref": "T16_interface_buried_surface_area",
        "oracle_tool_ref": "biotite SASA",
        "oracle_family": "non_cctbx",
        "oracle_measure": {"value_numeric": bsa["bsa"], "unit": "Å²"},
        "pass_status": "informational",
        "notes": (
            f"total area buried on complex formation across chains {'/'.join(bsa['chains'])} "
            f"(Shrake-Rupley SASA; ΣSASA(chains) − SASA(complex))."
        ),
    }
    if subject_ref is not None:
        row["subject_ref"] = subject_ref
    return yaml.safe_dump([row], sort_keys=False, allow_unicode=True, width=100)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("model", type=Path, help="model complex (PDB)")
    ap.add_argument("--native", type=Path, default=None,
                    help="native / deposited reference complex (enables DockQ + CAPRI)")
    ap.add_argument("--eval-id", default="EVAL_T16", help="eval id prefix for emitted rows")
    ap.add_argument("--subject-ref", default=None,
                    help="stable identifier for the concrete model being measured")
    ap.add_argument("--reference-subject-ref", default=None,
                    help="stable identifier for the native/reference model")
    ap.add_argument("--chains", default=None,
                    help="model chain pair for BSA, formatted CHAIN1:CHAIN2")
    ap.add_argument("--mapping", action="append", default=[],
                    help="DockQ chain map MODELCHAINS:NATIVECHAINS; repeat for controls")
    ap.add_argument("--interface-id", action="append", default=[],
                    help="declared InterfaceQuality id; one per --mapping")
    ap.add_argument("--raw-json", type=Path, action="append", default=[],
                    help="retained DockQ JSON path; one per --mapping")
    args = ap.parse_args(argv)

    if not args.model.exists():
        _fail(f"file not found: {args.model}")
    if args.model.suffix.lower() not in {".pdb", ".ent"}:
        _fail("only PDB input is currently supported; convert mmCIF explicitly before use.")

    selected_chains: tuple[str, str] | None = None
    if args.chains:
        parts = args.chains.split(":")
        if len(parts) != 2 or not all(parts) or parts[0] == parts[1]:
            _fail("--chains must name two distinct chain ids as CHAIN1:CHAIN2.")
        selected_chains = (parts[0], parts[1])

    if args.native is not None:
        if not args.subject_ref or not args.reference_subject_ref:
            _fail("DockQ requires both --subject-ref and --reference-subject-ref.")
        counts = (len(args.mapping), len(args.interface_id), len(args.raw_json))
        if not args.mapping or len(set(counts)) != 1:
            _fail(
                "DockQ requires one --mapping, --interface-id, and --raw-json per "
                f"scored mapping (received {counts})."
            )

    # Buried surface area is a model-intrinsic property — always emitted.
    bsa_interface_id = args.interface_id[0] if args.interface_id else f"{args.eval_id}_IFACE"
    print(render_bsa_yaml(
        run_biotite_bsa(args.model, selected_chains),
        args.eval_id,
        bsa_interface_id,
        args.subject_ref,
    ), end="")

    # DockQ needs a reference; emit its rows only when --native is supplied.
    if args.native is not None:
        if not args.native.exists():
            _fail(f"file not found: {args.native}")
        for mapping, interface_id, raw_json in zip(
            args.mapping, args.interface_id, args.raw_json, strict=True
        ):
            summary = extract(run_dockq(args.model, args.native, mapping, raw_json))
            if summary["mapping"] and summary["mapping"] != mapping:
                _fail(
                    f"DockQ reported mapping {summary['mapping']!r}, expected {mapping!r}."
                )
            evidence_ref = str(raw_json.resolve().relative_to(REPO)) \
                if raw_json.resolve().is_relative_to(REPO) else str(raw_json.resolve())
            print(render_yaml(
                summary,
                args.eval_id,
                interface_id,
                args.subject_ref,
                args.reference_subject_ref,
                evidence_ref,
            ), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
