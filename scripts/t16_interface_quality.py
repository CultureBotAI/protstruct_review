#!/usr/bin/env python3
"""Compute the T16 interface-quality metrics with DockQ.

Runs DockQ (Basu & Wallner 2016) on a model complex against a native/reference
complex and reports the DockQ score plus its CAPRI quality class. DockQ is
non-cctbx and non-PHENIX; the deposited biological assembly is the reference,
which is the trust model's tiebreaker for T16 (there is no PHENIX interface
scorer, so this is oracle-only).

Emits a pasteable EvaluationRun fragment containing measurements plus their
structured InterfaceQuality context. With `--native`, the fragment contains one
selected scalar headline bundle plus an InterfaceQuality row for every scored mapping:
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
      --structure-id 1abc \
      --subject-ref artifact:model --reference-subject-ref pdb:1abc \
      --native-chains A:B \
      --mapping AB:AB --interface-id IFACE_AB_ID \
      --raw-json evidence/model_AB_AB.dockq.json \
      --bsa-evidence evidence/model_AB.bsa.json \
      --headline-interface-id IFACE_AB_ID --eval-id EVAL_...
    python3 scripts/t16_interface_quality.py model.pdb --chains A:B \
      --structure-id 1abc --subject-ref artifact:model \
      --bsa-evidence evidence/model_AB.bsa.json  # BSA only
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import itertools
import json
import math
import os
import re
import sys
import tempfile
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
    # Pin the quadrature explicitly.  The benchmark and the committed 1SAR
    # values were produced with biotite 1.7.1's 1000-point default; relying on
    # an implicit default would let a dependency update silently redefine BSA.
    complex_sasa = float(
        np.nansum(struc.sasa(atoms, probe_radius=1.4, point_number=1000))
    )
    separated = sum(
        float(
            np.nansum(
                struc.sasa(
                    atoms[atoms.chain_id == c], probe_radius=1.4, point_number=1000
                )
            )
        )
        for c in chains
    )
    return {
        "bsa": buried_surface_area(complex_sasa, separated),
        "chains": chains,
        "complex_sasa": round(complex_sasa, 1),
        "complex_sasa_unrounded": complex_sasa,
        "separated_sasa_unrounded": separated,
        "bsa_unrounded": separated - complex_sasa,
    }


def run_dockq(
    model: Path, native: Path, mapping: str, raw_json_path: Path
) -> dict[str, Any]:
    """Run one explicit DockQ mapping and retain its exact JSON output."""
    # Run the module through this exact interpreter. A PATH console script may
    # belong to another Python environment, making importlib's recorded version
    # unrelated to the executable that produced the evidence.
    measured_dockq_version()
    raw_json_path = raw_json_path.resolve()
    if raw_json_path.exists():
        _fail(f"raw DockQ evidence already exists; refusing to overwrite: {raw_json_path}")
    raw_json_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=raw_json_path.parent,
        prefix=f".{raw_json_path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
    # DockQ owns creation of its JSON output.  Give it a nonexistent temporary
    # destination, validate that file, then publish with one atomic rename.
    temporary.unlink()
    try:
        cmd = [
            sys.executable,
            "-m",
            "DockQ",
            "--json",
            str(temporary),
            str(model),
            str(native),
            "--mapping",
            mapping,
        ]
        proc = run_capture(cmd)
        if proc.returncode != 0:
            _fail(
                f"DockQ failed ({proc.returncode}): "
                f"{proc.stderr.strip() or proc.stdout.strip()}"
            )
        if not temporary.is_file() or not temporary.stat().st_size:
            _fail(f"DockQ produced no output: {proc.stderr.strip() or proc.stdout.strip()}")
        try:
            result = json.loads(temporary.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            _fail(f"DockQ output is not valid JSON ({temporary}): {exc}")
        temporary.replace(raw_json_path)
        return result
    finally:
        temporary.unlink(missing_ok=True)


def _mapping_parts(mapping: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Parse DockQ's one-character PDB chain mapping syntax."""
    pieces = mapping.split(":")
    if len(pieces) != 2 or not all(pieces):
        _fail(f"invalid DockQ mapping {mapping!r}; expected MODELCHAINS:NATIVECHAINS.")
    model_chains = tuple(pieces[0])
    native_chains = tuple(pieces[1])
    if len(model_chains) != len(native_chains) or len(set(model_chains)) != len(model_chains):
        _fail(f"invalid DockQ mapping {mapping!r}; chains must form a one-to-one mapping.")
    if len(set(native_chains)) != len(native_chains):
        _fail(f"invalid DockQ mapping {mapping!r}; native chains are repeated.")
    return model_chains, native_chains


def _protein_chain_sequences(model: Path) -> dict[str, tuple[str, ...]]:
    """Return residue-name sequences for each protein chain in a PDB model."""
    try:
        import biotite.structure as struc
        import biotite.structure.io.pdb as pdb
    except ImportError:
        _fail("biotite not importable — install it (`pip install biotite`).")
    arr = pdb.get_structure(pdb.PDBFile.read(str(model)), model=1)
    protein = arr[struc.filter_amino_acids(arr)]
    sequences: dict[str, tuple[str, ...]] = {}
    for chain_id in sorted(set(protein.chain_id)):
        chain = protein[protein.chain_id == chain_id]
        starts = struc.get_residue_starts(chain)
        sequences[str(chain_id)] = tuple(str(chain.res_name[index]) for index in starts)
    return sequences


def _sequence_equivalent_mappings(
    native_sequences: dict[str, tuple[str, ...]],
    model_chains: tuple[str, ...],
    mapped_native_chains: tuple[str, ...],
) -> set[str]:
    """Expand one explicit mapping over equivalent selected native partners.

    Candidate and reference coordinates routinely differ by a missing residue or
    mutation.  Those ordinary imperfections must not make an explicit DockQ
    comparison impossible.  Ambiguity controls instead come from permutations
    among native partners with the same observed sequence: swapping equivalent
    reference chains remains mandatory regardless of candidate imperfections.
    """
    expected: set[str] = {
        f"{''.join(model_chains)}:{''.join(mapped_native_chains)}"
    }
    for permutation in itertools.permutations(mapped_native_chains):
        if all(
            native_sequences[native_chain] == native_sequences[permuted_chain]
            for native_chain, permuted_chain in zip(
                mapped_native_chains, permutation, strict=True
            )
        ):
            expected.add(f"{''.join(model_chains)}:{''.join(permutation)}")
    return expected


def _validate_mapping_controls(
    model: Path,
    native: Path,
    mappings: list[str],
    selected_chains: tuple[str, str] | None,
    selected_native_chains: tuple[str, str],
) -> tuple[str, str]:
    """Require every sequence-equivalent bijection for one declared interface pair."""
    parsed = [_mapping_parts(mapping) for mapping in mappings]
    model_chains, first_native = parsed[0]
    if len(model_chains) != 2:
        _fail("T16 currently scores one two-chain interface; mappings must name two chains.")
    if len(selected_native_chains) != 2 or len(set(selected_native_chains)) != 2:
        _fail("the selected native interface must contain exactly two distinct chains.")
    native_set = set(selected_native_chains)
    for mapping, (candidate, native_order) in zip(mappings, parsed, strict=True):
        if candidate != model_chains or set(native_order) != native_set:
            _fail(
                f"mapping {mapping!r} does not describe candidate chains "
                f"{''.join(model_chains)!r} and the explicitly selected native interface "
                f"{':'.join(selected_native_chains)!r}."
            )
    if selected_chains is not None and set(selected_chains) != set(model_chains):
        _fail(
            f"--chains {':'.join(selected_chains)} does not match mapping candidate chains "
            f"{''.join(model_chains)}."
        )
    model_sequences = _protein_chain_sequences(model)
    native_sequences = _protein_chain_sequences(native)
    missing_model = sorted(set(model_chains) - set(model_sequences))
    missing_native = sorted(native_set - set(native_sequences))
    if missing_model or missing_native:
        _fail(
            "mapping names chain(s) with no protein residues: "
            f"candidate missing={missing_model}, native missing={missing_native}."
        )
    expected = _sequence_equivalent_mappings(
        native_sequences,
        model_chains,
        first_native,
    )
    provided = set(mappings)
    if provided != expected:
        missing = sorted(expected - provided)
        extra = sorted(provided - expected)
        _fail(
            "DockQ requires every sequence-equivalent mapping control; "
            f"missing={missing}, unexpected={extra}."
        )
    return model_chains[0], model_chains[1]


def _finite_number(value: Any, label: str, *, unit_interval: bool = False) -> float:
    """Return a finite real JSON value, optionally constrained to [0, 1]."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"DockQ JSON {label} must be numeric (got {value!r}).")
    number = float(value)
    if not math.isfinite(number):
        _fail(f"DockQ JSON {label} must be finite (got {value!r}).")
    if unit_interval and not 0.0 <= number <= 1.0:
        _fail(f"DockQ JSON {label} must be in [0, 1] (got {number!r}).")
    return number


def _dockq_from_components(*, fnat: float, irmsd: float, lrmsd: float) -> float:
    """Recompute the standard DockQ score from its retained components."""
    return (
        fnat
        + 1.0 / (1.0 + (irmsd / 1.5) ** 2)
        + 1.0 / (1.0 + (lrmsd / 8.5) ** 2)
    ) / 3.0


def _mapping_dict(mapping: str) -> dict[str, str]:
    model_chains, native_chains = _mapping_parts(mapping)
    return dict(zip(model_chains, native_chains, strict=True))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def measured_dockq_version() -> str:
    """Return the installed DockQ distribution version used by the executable."""
    try:
        return importlib.metadata.version("DockQ")
    except importlib.metadata.PackageNotFoundError:
        _fail("DockQ distribution metadata unavailable — install DockQ")


def measured_biotite_version() -> str:
    """Return the installed Biotite distribution version used for BSA."""
    try:
        return importlib.metadata.version("biotite")
    except importlib.metadata.PackageNotFoundError:
        _fail("biotite distribution metadata unavailable — install biotite")


def bsa_evidence_record(
    bsa: dict[str, Any],
    *,
    evidence_id: str,
    model: Path,
    subject_ref: str,
    biotite_version: str,
) -> dict[str, Any]:
    """Build the content-bound retained evidence for one BSA calculation."""
    return {
        "id": evidence_id,
        "subject_ref": subject_ref,
        "input_path": str(model),
        "input_sha256": _sha256(model),
        "tool": "biotite SASA",
        "tool_version": biotite_version,
        "algorithm": "Shrake-Rupley",
        "parameters": {
            "chains": list(bsa["chains"]),
            "selection": "protein atoms only",
            "probe_radius_a": 1.4,
            "point_number": 1000,
        },
        "complex_sasa_a2": bsa["complex_sasa_unrounded"],
        "separated_sasa_a2": bsa["separated_sasa_unrounded"],
        "buried_surface_area_a2_unrounded": bsa["bsa_unrounded"],
        "buried_surface_area_a2_reported": bsa["bsa"],
        "formula": "separated_sasa_a2 - complex_sasa_a2",
    }


def bind_input_provenance(
    result: dict[str, Any],
    *,
    model: Path,
    native: Path,
    mapping: str,
    subject_ref: str,
    reference_subject_ref: str,
    dockq_version: str,
) -> dict[str, Any]:
    """Attach harness-owned input identities to otherwise path-only DockQ JSON."""
    bound = dict(result)
    bound["_protstruct_input_provenance"] = {
        "model": {
            "invocation_path": str(model),
            "subject_ref": subject_ref,
            "sha256": _sha256(model),
        },
        "native": {
            "invocation_path": str(native),
            "subject_ref": reference_subject_ref,
            "sha256": _sha256(native),
        },
        "mapping": mapping,
        "tool": {"id": "DockQ", "version": dockq_version},
    }
    return bound


def extract(
    result: dict[str, Any],
    expected_mapping: str,
    *,
    expected_subject_ref: str | None = None,
    expected_reference_subject_ref: str | None = None,
    expected_model_sha256: str | None = None,
    expected_native_sha256: str | None = None,
    expected_dockq_version: str | None = None,
) -> dict[str, Any]:
    """Validate and extract one requested two-chain comparison from DockQ JSON."""
    if not isinstance(result, dict):
        _fail("DockQ JSON root must be an object.")
    reported_mapping = result.get("best_mapping_str")
    if reported_mapping != expected_mapping:
        _fail(
            f"DockQ reported mapping {reported_mapping!r}, expected {expected_mapping!r}."
        )
    expected_chain_map = _mapping_dict(expected_mapping)
    if result.get("best_mapping") != expected_chain_map:
        _fail(
            "DockQ JSON best_mapping does not match best_mapping_str "
            f"{expected_mapping!r}."
        )
    expectations = {
        "model.subject_ref": expected_subject_ref,
        "native.subject_ref": expected_reference_subject_ref,
        "model.sha256": expected_model_sha256,
        "native.sha256": expected_native_sha256,
        "mapping": expected_mapping,
        "tool.id": "DockQ" if expected_dockq_version is not None else None,
        "tool.version": expected_dockq_version,
    }
    if any(value is not None for key, value in expectations.items() if key != "mapping"):
        provenance = result.get("_protstruct_input_provenance")
        if not isinstance(provenance, dict):
            _fail("DockQ JSON has no harness input provenance block.")
        model_provenance = provenance.get("model")
        native_provenance = provenance.get("native")
        if not isinstance(model_provenance, dict) or not isinstance(
            native_provenance, dict
        ):
            _fail("DockQ JSON harness input provenance must describe model and native.")
        observed = {
            "model.subject_ref": model_provenance.get("subject_ref"),
            "native.subject_ref": native_provenance.get("subject_ref"),
            "model.sha256": model_provenance.get("sha256"),
            "native.sha256": native_provenance.get("sha256"),
            "mapping": provenance.get("mapping"),
            "tool.id": (
                provenance.get("tool", {}).get("id")
                if isinstance(provenance.get("tool"), dict)
                else None
            ),
            "tool.version": (
                provenance.get("tool", {}).get("version")
                if isinstance(provenance.get("tool"), dict)
                else None
            ),
        }
        mismatches = [
            key
            for key, expected in expectations.items()
            if expected is not None and observed.get(key) != expected
        ]
        if mismatches:
            _fail(
                "DockQ JSON input provenance mismatch for " + ", ".join(mismatches) + "."
            )
        if result.get("model") != model_provenance.get("invocation_path"):
            _fail("DockQ JSON model path disagrees with harness input provenance.")
        if result.get("native") != native_provenance.get("invocation_path"):
            _fail("DockQ JSON native path disagrees with harness input provenance.")
    score_fields = {
        name: _finite_number(result[name], name, unit_interval=True)
        for name in ("GlobalDockQ", "best_dockq")
        if name in result
    }
    if not score_fields:
        _fail("DockQ JSON has no GlobalDockQ/best_dockq field — cannot score.")
    if len(score_fields) == 2 and not math.isclose(
        score_fields["GlobalDockQ"],
        score_fields["best_dockq"],
        rel_tol=1e-12,
        abs_tol=1e-12,
    ):
        _fail("DockQ JSON GlobalDockQ and best_dockq disagree.")
    raw_dockq = (
        score_fields["GlobalDockQ"]
        if "GlobalDockQ" in score_fields
        else score_fields["best_dockq"]
    )
    raw_interfaces = result.get("best_result")
    if not isinstance(raw_interfaces, dict) or not raw_interfaces:
        _fail("DockQ JSON best_result must contain a scored interface.")
    if len(raw_interfaces) != 1:
        _fail(
            "DockQ JSON best_result must contain exactly one interface for the "
            f"requested two-chain mapping (got {len(raw_interfaces)})."
        )
    interfaces: dict[str, dict[str, float]] = {}
    for name, iface in raw_interfaces.items():
        if not isinstance(name, str) or not name or not isinstance(iface, dict):
            _fail("DockQ JSON best_result entries must be named interface objects.")
        if iface.get("chain_map") != expected_chain_map:
            _fail(
                f"DockQ JSON best_result[{name!r}].chain_map does not match "
                f"{expected_mapping!r}."
            )
        interface_dockq = _finite_number(
            iface.get("DockQ"), f"best_result[{name!r}].DockQ", unit_interval=True
        )
        if not math.isclose(interface_dockq, raw_dockq, rel_tol=1e-9, abs_tol=1e-12):
            _fail(
                f"DockQ JSON global score {raw_dockq!r} does not match the sole "
                f"interface score {interface_dockq!r}."
            )
        irmsd = _finite_number(iface.get("iRMSD"), f"best_result[{name!r}].iRMSD")
        lrmsd = _finite_number(iface.get("LRMSD"), f"best_result[{name!r}].LRMSD")
        if irmsd < 0.0 or lrmsd < 0.0:
            _fail("DockQ JSON RMSD values must be non-negative.")
        fnat = _finite_number(
            iface.get("fnat"), f"best_result[{name!r}].fnat", unit_interval=True
        )
        recomputed_dockq = _dockq_from_components(
            fnat=fnat, irmsd=irmsd, lrmsd=lrmsd
        )
        if not math.isclose(
            interface_dockq, recomputed_dockq, rel_tol=1e-12, abs_tol=1e-12
        ):
            _fail(
                f"DockQ JSON best_result[{name!r}].DockQ {interface_dockq!r} "
                "does not match the standard DockQ formula applied to its "
                f"fnat/iRMSD/LRMSD components ({recomputed_dockq!r})."
            )
        interfaces[name] = {
            "dockq": round(interface_dockq, 4),
            "irmsd": round(irmsd, 3),
            "lrmsd": round(lrmsd, 3),
            "fnat": round(fnat, 4),
        }
    return {
        "dockq": raw_dockq,
        "capri": capri_class(raw_dockq),
        "mapping": reported_mapping,
        "interfaces": interfaces,
    }


def dockq_measurement_rows(
    summary: dict[str, Any],
    eval_id: str,
    interface_id: str,
    subject_ref: str,
    reference_subject_ref: str,
    evidence_ref: str,
) -> list[dict[str, Any]]:
    """Build the selected DockQ/CAPRI headline measurement pair."""
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
    return [score_row, class_row]


def render_yaml(
    summary: dict[str, Any],
    eval_id: str,
    interface_id: str,
    subject_ref: str,
    reference_subject_ref: str,
    evidence_ref: str,
) -> str:
    """Emit the two selected T16 measurement rows for paste-oriented callers."""
    return yaml.safe_dump(
        dockq_measurement_rows(
            summary,
            eval_id,
            interface_id,
            subject_ref,
            reference_subject_ref,
            evidence_ref,
        ),
        sort_keys=False,
        allow_unicode=True,
        width=100,
    )


def interface_quality_row(
    summary: dict[str, Any],
    *,
    structure_id: str,
    interface_id: str,
    subject_ref: str,
    reference_subject_ref: str,
    evidence_ref: str,
    bsa: dict[str, Any] | None = None,
    bsa_evidence_ref: str | None = None,
) -> dict[str, Any]:
    """Build one structured mapping-control row retained in the EvaluationRun."""
    model_chains, _native_chains = _mapping_parts(summary["mapping"])
    row: dict[str, Any] = {
        "id": interface_id,
        "structure_ref": structure_id,
        "subject_ref": subject_ref,
        "reference_subject_ref": reference_subject_ref,
        "interface_label": f"{''.join(model_chains)} interface, mapping {summary['mapping']}",
        "chain_id_1": model_chains[0],
        "chain_id_2": model_chains[1],
        "model_to_native_chain_mapping": summary["mapping"],
        "dockq_score": {"value_numeric": summary["dockq"]},
        "capri_quality_class": {"value_text": summary["capri"]},
        "evidence_refs": [evidence_ref],
        "notes": (
            f"DockQ vs reference over {len(summary['interfaces'])} interface(s); "
            "mapping retained explicitly."
        ),
    }
    if bsa is not None:
        if not bsa_evidence_ref:
            _fail("mixed DockQ/BSA InterfaceQuality requires retained BSA evidence.")
        row["buried_surface_area"] = {
            "value_numeric": bsa["bsa"],
            "unit": "Å²",
        }
        row["evidence_refs"].append(bsa_evidence_ref)
    else:
        row["tool_ref"] = "DockQ"
    return row


def bsa_measurement_row(
    bsa: dict[str, Any],
    eval_id: str,
    interface_id: str,
    subject_ref: str,
    evidence_ref: str,
) -> dict[str, Any]:
    """Build the buried-surface-area headline measurement row."""
    row = {
        "id": f"{eval_id}_M_T16_bsa_{re.sub(r'[^A-Za-z0-9]+', '_', interface_id).strip('_')}",
        "catalog_task_ref": "T16",
        "stage": "final",
        "scope": "interface",
        "scope_selector": interface_id,
        "metric_definition_ref": "T16_interface_buried_surface_area",
        "oracle_tool_ref": "biotite SASA",
        "oracle_family": "non_cctbx",
        "oracle_measure": {"value_numeric": bsa["bsa"], "unit": "Å²"},
        "pass_status": "informational",
        "subject_ref": subject_ref,
        "evidence_refs": [evidence_ref],
        "notes": (
            f"total area buried on complex formation across chains {'/'.join(bsa['chains'])} "
            f"(Shrake-Rupley SASA; ΣSASA(chains) − SASA(complex))."
        ),
    }
    return row


def bsa_interface_quality_row(
    bsa: dict[str, Any],
    *,
    structure_id: str,
    interface_id: str,
    subject_ref: str,
    evidence_ref: str,
) -> dict[str, Any]:
    """Build candidate-only structured context for a BSA measurement."""
    chains = bsa["chains"]
    return {
        "id": interface_id,
        "structure_ref": structure_id,
        "subject_ref": subject_ref,
        "interface_label": f"{''.join(chains)} interface, candidate-only BSA",
        "chain_id_1": chains[0],
        "chain_id_2": chains[1],
        "buried_surface_area": {
            "value_numeric": bsa["bsa"],
            "unit": "Å²",
        },
        "tool_ref": "biotite SASA",
        "evidence_refs": [evidence_ref],
        "notes": (
            "Candidate-only total two-sided BSA; no native/reference mapping or "
            "biological-assembly claim is implied."
        ),
    }


def render_bsa_yaml(
    bsa: dict[str, Any],
    eval_id: str,
    interface_id: str,
    subject_ref: str,
    structure_id: str,
    evidence_ref: str,
) -> str:
    """Emit QDS-admissible candidate-only BSA measurement and context rows."""
    return yaml.safe_dump(
        {
            "measurements": [
                bsa_measurement_row(
                    bsa, eval_id, interface_id, subject_ref, evidence_ref
                )
            ],
            "interface_qualities": [
                bsa_interface_quality_row(
                    bsa,
                    structure_id=structure_id,
                    interface_id=interface_id,
                    subject_ref=subject_ref,
                    evidence_ref=evidence_ref,
                )
            ],
        },
        sort_keys=False,
        allow_unicode=True,
        width=100,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("model", type=Path, help="model complex (PDB)")
    ap.add_argument("--native", type=Path, default=None,
                    help="native / deposited reference complex (enables DockQ + CAPRI)")
    ap.add_argument("--eval-id", default="EVAL_T16", help="eval id prefix for emitted rows")
    ap.add_argument(
        "--structure-id",
        default=None,
        help="Structure id required for emitted InterfaceQuality mapping rows",
    )
    ap.add_argument("--subject-ref", default=None,
                    help="stable identifier for the concrete model being measured")
    ap.add_argument("--reference-subject-ref", default=None,
                    help="stable identifier for the native/reference model")
    ap.add_argument("--chains", default=None,
                    help="model chain pair for BSA, formatted CHAIN1:CHAIN2")
    ap.add_argument(
        "--bsa-evidence",
        type=Path,
        required=True,
        help="new repository-local JSON destination for retained Biotite BSA evidence",
    )
    ap.add_argument(
        "--native-chains",
        default=None,
        help=(
            "explicit native/reference interface pair, formatted CHAIN1:CHAIN2; "
            "mapping completeness is evaluated within this selected interface"
        ),
    )
    ap.add_argument("--mapping", action="append", default=[],
                    help="DockQ chain map MODELCHAINS:NATIVECHAINS; repeat for controls")
    ap.add_argument("--interface-id", action="append", default=[],
                    help="declared InterfaceQuality id; one per --mapping")
    ap.add_argument(
        "--headline-interface-id",
        default=None,
        help=(
            "InterfaceQuality id selected for the headline T16 bundle; required "
            "with --native and must match exactly one --interface-id"
        ),
    )
    ap.add_argument("--raw-json", type=Path, action="append", default=[],
                    help="retained DockQ JSON path; one per --mapping")
    args = ap.parse_args(argv)

    if not args.model.exists():
        _fail(f"file not found: {args.model}")
    if args.model.suffix.lower() not in {".pdb", ".ent"}:
        _fail("only PDB input is currently supported; convert mmCIF explicitly before use.")
    if not args.subject_ref or not args.structure_id:
        _fail(
            "T16 output requires --structure-id and --subject-ref so every scalar "
            "resolves to structured InterfaceQuality context."
        )
    bsa_final_path = args.bsa_evidence.resolve()
    if not bsa_final_path.is_relative_to(REPO.resolve()):
        _fail(
            "BSA evidence must be stored inside the repository: "
            f"{bsa_final_path}"
        )
    if bsa_final_path.exists():
        _fail(
            "BSA evidence already exists; refusing to overwrite: "
            f"{bsa_final_path}"
        )

    selected_chains: tuple[str, str] | None = None
    if args.chains:
        parts = args.chains.split(":")
        if len(parts) != 2 or not all(parts) or parts[0] == parts[1]:
            _fail("--chains must name two distinct chain ids as CHAIN1:CHAIN2.")
        selected_chains = (parts[0], parts[1])

    dockq_options_present = bool(
        args.mapping
        or args.interface_id
        or args.raw_json
        or args.native_chains
        or args.headline_interface_id
    )
    if args.native is None and dockq_options_present:
        _fail(
            "--native-chains, --mapping, --interface-id, --raw-json, and "
            "--headline-interface-id require --native."
        )

    if args.native is not None:
        if not args.native.exists():
            _fail(f"file not found: {args.native}")
        if args.native.suffix.lower() not in {".pdb", ".ent"}:
            _fail("only PDB native/reference input is currently supported.")
        if not args.reference_subject_ref:
            _fail("DockQ requires --reference-subject-ref.")
        if not args.native_chains:
            _fail(
                "DockQ requires --native-chains CHAIN1:CHAIN2 to declare the selected "
                "native/reference interface."
            )
        if not args.headline_interface_id:
            _fail(
                "DockQ requires --headline-interface-id to select the explicit "
                "headline mapping/interface bundle."
            )
        native_parts = args.native_chains.split(":")
        if (
            len(native_parts) != 2
            or not all(native_parts)
            or native_parts[0] == native_parts[1]
            or any(len(chain) != 1 for chain in native_parts)
        ):
            _fail("--native-chains must name two distinct one-character PDB chain ids.")
        selected_native_chains = (native_parts[0], native_parts[1])
        counts = (len(args.mapping), len(args.interface_id), len(args.raw_json))
        if not args.mapping or len(set(counts)) != 1:
            _fail(
                "DockQ requires one --mapping, --interface-id, and --raw-json per "
                f"scored mapping (received {counts})."
            )
        if len(set(args.mapping)) != len(args.mapping):
            _fail("duplicate --mapping values are not allowed.")
        if len(set(args.interface_id)) != len(args.interface_id):
            _fail("duplicate --interface-id values are not allowed.")
        if args.headline_interface_id not in args.interface_id:
            _fail(
                f"--headline-interface-id {args.headline_interface_id!r} does not "
                "match any declared --interface-id."
            )
        resolved_raw = [path.resolve() for path in args.raw_json]
        if len(set(resolved_raw)) != len(resolved_raw):
            _fail("duplicate --raw-json destinations are not allowed.")
        if bsa_final_path in resolved_raw:
            _fail("--bsa-evidence and --raw-json destinations must be distinct.")
        for path in resolved_raw:
            if not path.is_relative_to(REPO.resolve()):
                _fail(f"raw DockQ evidence must be stored inside the repository: {path}")
            if path.exists():
                _fail(f"raw DockQ evidence already exists; refusing to overwrite: {path}")
        mapped_pair = _validate_mapping_controls(
            args.model,
            args.native,
            args.mapping,
            selected_chains,
            selected_native_chains,
        )
        if selected_chains is None:
            selected_chains = mapped_pair

    # Build all stdout and every evidence file in one staging group. A failed
    # BSA/native/mapping leg must leave neither a valid-looking YAML prefix nor
    # an orphaned subset of the evidence.
    bsa_interface_id = (
        args.headline_interface_id
        if args.native is not None
        else f"{args.eval_id}_IFACE"
    )
    bsa_evidence_ref = str(bsa_final_path.relative_to(REPO.resolve()))
    staged: list[tuple[Path, Path]] = []
    published: list[Path] = []
    try:
        bsa_result = run_biotite_bsa(args.model, selected_chains)
        biotite_version = measured_biotite_version()
        bsa_final_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=bsa_final_path.parent,
            prefix=f".{bsa_final_path.name}.group.",
            suffix=".json",
            delete=False,
        ) as handle:
            bsa_stage_path = Path(handle.name)
        staged.append((bsa_stage_path, bsa_final_path))
        evidence_suffix = re.sub(
            r"[^A-Za-z0-9]+", "_", bsa_interface_id
        ).strip("_")
        bsa_stage_path.write_text(
            json.dumps(
                bsa_evidence_record(
                    bsa_result,
                    evidence_id=f"{args.eval_id}_EVIDENCE_T16_bsa_{evidence_suffix}",
                    model=args.model,
                    subject_ref=args.subject_ref,
                    biotite_version=biotite_version,
                ),
                sort_keys=True,
                indent=2,
            )
            + "\n"
        )
        measurement_rows = [
            bsa_measurement_row(
                bsa_result,
                args.eval_id,
                bsa_interface_id,
                args.subject_ref,
                bsa_evidence_ref,
            )
        ]
        interface_rows: list[dict[str, Any]] = []
        if args.native is None:
            interface_rows.append(
                bsa_interface_quality_row(
                    bsa_result,
                    structure_id=args.structure_id,
                    interface_id=bsa_interface_id,
                    subject_ref=args.subject_ref,
                    evidence_ref=bsa_evidence_ref,
                )
            )

        # DockQ needs a reference; emit its rows only when --native is supplied.
        if args.native is not None:
            model_sha256 = _sha256(args.model)
            native_sha256 = _sha256(args.native)
            dockq_version = measured_dockq_version()
            for mapping, interface_id, raw_json in zip(
                args.mapping, args.interface_id, args.raw_json, strict=True
            ):
                final_path = raw_json.resolve()
                final_path.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(
                    dir=final_path.parent,
                    prefix=f".{final_path.name}.group.",
                    suffix=".json",
                    delete=False,
                ) as handle:
                    stage_path = Path(handle.name)
                stage_path.unlink()
                staged.append((stage_path, final_path))
                result = bind_input_provenance(
                    run_dockq(args.model, args.native, mapping, stage_path),
                    model=args.model,
                    native=args.native,
                    mapping=mapping,
                    subject_ref=args.subject_ref,
                    reference_subject_ref=args.reference_subject_ref,
                    dockq_version=dockq_version,
                )
                stage_path.write_text(
                    json.dumps(result, sort_keys=True, indent=2) + "\n"
                )
                summary = extract(
                    result,
                    mapping,
                    expected_subject_ref=args.subject_ref,
                    expected_reference_subject_ref=args.reference_subject_ref,
                    expected_model_sha256=model_sha256,
                    expected_native_sha256=native_sha256,
                    expected_dockq_version=dockq_version,
                )
                evidence_ref = str(final_path.relative_to(REPO.resolve()))
                is_headline = interface_id == args.headline_interface_id
                if is_headline:
                    measurement_rows.extend(
                        dockq_measurement_rows(
                            summary,
                            args.eval_id,
                            interface_id,
                            args.subject_ref,
                            args.reference_subject_ref,
                            evidence_ref,
                        )
                    )
                interface_rows.append(
                    interface_quality_row(
                        summary,
                        structure_id=args.structure_id,
                        interface_id=interface_id,
                        subject_ref=args.subject_ref,
                        reference_subject_ref=args.reference_subject_ref,
                        evidence_ref=evidence_ref,
                        bsa=bsa_result if is_headline else None,
                        bsa_evidence_ref=(bsa_evidence_ref if is_headline else None),
                    )
                )

        # Publish only after every calculation and rendered row has succeeded.
        # Hard-link creation is atomic and refuses an unexpected pre-existing
        # destination, unlike rename/replace which could overwrite evidence.
        for stage_path, final_path in staged:
            os.link(stage_path, final_path)
            published.append(final_path)
        for stage_path, _final_path in staged:
            stage_path.unlink(missing_ok=True)
    except BaseException:
        for stage_path, _final_path in staged:
            stage_path.unlink(missing_ok=True)
        for path in published:
            path.unlink(missing_ok=True)
        raise
    output: Any = {
        "measurements": measurement_rows,
        "interface_qualities": interface_rows,
    }
    sys.stdout.write(
        yaml.safe_dump(
            output,
            sort_keys=False,
            allow_unicode=True,
            width=100,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
