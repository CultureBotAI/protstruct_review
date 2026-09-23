#!/usr/bin/env python3
"""Recount retained 1SAR coordinates and T13 logs without external tool runs.

This is deliberately an audit of one retained artifact, not an MTZ/PDB library
or a new refinement/validation oracle. Coordinate arithmetic is freshly derived;
T13 values are parsed from saved May 4 logs. No PHENIX, CCP4 or gemmi is invoked.
The command writes JSON to stdout only. It never rewrites an evidence file.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import re
import shlex
import statistics
import struct
from typing import Any
import zipfile

from t13_data_quality import parse_ctruncate


REPO = Path(__file__).resolve().parent.parent
BASE = Path("data/coscientists/openscientist")
EVIDENCE_REF = (BASE / "retained_evidence_2026-09-23/coordinate_and_t13_audit.json").as_posix()
ARCHIVE = BASE / "cdba2c07-daff-4f60-ae96-12452b3a5fbb_artifacts.zip"
ARCHIVE_SHA256 = "9fc5352284b7ffa7763c633a3eb4d3d0db96b8c25a1be9bcea361722d2c53054"
MODEL_MEMBER = "data/1sar_final.pdb"
DATA_MEMBER = "data/1sar.mtz"
AMINO_ACIDS = frozenset("ALA ARG ASN ASP CYS GLN GLU GLY HIS ILE LEU LYS MET PHE PRO SER THR TRP TYR VAL".split())


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def pdb_atoms(text: str) -> list[dict[str, Any]]:
    """Read the concrete single-model, no-altloc PDB used by this audit."""
    atoms: list[dict[str, Any]] = []
    keys: set[tuple[str, ...]] = set()
    if any(line.startswith("MODEL ") for line in text.splitlines()):
        raise ValueError("audit requires an implicit single PDB model")
    for line in text.splitlines():
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        if len(line) < 78 or line[16:17] != " ":
            raise ValueError("audit requires complete fixed-column atoms without altlocs")
        element = line[76:78].strip()
        if not element:
            raise ValueError("atom lacks its explicit element")
        if element in {"H", "D"}:
            continue
        key = (line[21:22], line[22:26].strip(), line[26:27].strip(),
               line[17:20].strip(), line[12:16].strip())
        if key in keys:
            raise ValueError(f"duplicate atom key {key!r}")
        keys.add(key)
        coords = [float(line[start:end]) for start, end in ((30, 38), (38, 46), (46, 54))]
        occupancy, b_factor = float(line[54:60]), float(line[60:66])
        if not all(math.isfinite(v) for v in [*coords, occupancy, b_factor]):
            raise ValueError("nonfinite coordinate, occupancy or B factor")
        atoms.append({"key": key, "element": element, "xyz": coords,
                      "occupancy": occupancy, "b_factor": b_factor})
    if not atoms:
        raise ValueError("empty coordinate selection")
    return atoms


def distribution(values: list[float]) -> dict[str, Any]:
    if not values:
        raise ValueError("empty distribution")
    return {"count": len(values), "mean": statistics.fmean(values),
            "population_std_dev": statistics.pstdev(values),
            "min": min(values), "max": max(values)}


def _mtz_headers(blob: bytes) -> tuple[int, list[str]]:
    """Read complete records from the retained little-endian MTZ header."""
    if blob[:4] != b"MTZ " or blob[8:10] != bytes.fromhex("4441"):
        raise ValueError("audit supports only little-endian IEEE MTZ input")
    offset = (struct.unpack("<i", blob[4:8])[0] - 1) * 4
    if not 80 <= offset < len(blob):
        raise ValueError("invalid MTZ header offset")
    headers: list[str] = []
    for start in range(offset, len(blob), 80):
        record = blob[start:start + 80]
        if len(record) != 80:
            raise ValueError("audit requires complete 80-byte MTZ header records")
        line = record.decode("ascii").strip()
        if line == "END":
            break
        headers.append(line)
    else:
        raise ValueError("MTZ header has no END record")
    return offset, headers


def mtz_observations(blob: bytes, labels: tuple[str, str]) -> dict[tuple[int, ...], tuple[bytes, bytes]]:
    """Read exact IEEE bytes from the two known retained little-endian MTZs.

    No crystallographic calculation or symmetry expansion is performed. This
    compares the stored H/K/L-indexed selected observations, including NaNs.
    Crystallographic context is checked separately before asserting equivalence.
    """
    if len(labels) != 2 or len(set(labels)) != 2:
        raise ValueError("audit requires exactly two distinct observation columns")
    offset, headers = _mtz_headers(blob)
    count_rows = [line.split() for line in headers if line.startswith("NCOL ")]
    if len(count_rows) != 1:
        raise ValueError("MTZ requires exactly one NCOL header")
    ncols, nrows = map(int, count_rows[0][1:3])
    columns = [line.split()[1] for line in headers if line.startswith("COLUMN ")]
    if (ncols != len(columns) or len(set(columns)) != ncols
            or columns[:3] != ["H", "K", "L"] or nrows <= 0
            or offset != 80 + 4 * ncols * nrows):
        raise ValueError("MTZ table dimensions or column identities are inconsistent")
    indices = [columns.index(label) for label in labels]
    out = {}
    for number in range(nrows):
        start = 80 + number * ncols * 4
        row = blob[start:start + ncols * 4]
        hkl_values = struct.unpack("<fff", row[:12])
        if any(not math.isfinite(v) or v != int(v) for v in hkl_values):
            raise ValueError("non-integral reflection index")
        hkl = tuple(int(v) for v in hkl_values)
        if hkl in out:
            raise ValueError("duplicate reflection key")
        out[hkl] = tuple(row[4 * index:4 * index + 4] for index in indices)
    return out


def mtz_crystallographic_context(blob: bytes) -> dict[str, Any]:
    """Normalize the retained context, without an MTZ library or reindexing.

    Numeric header values compare as exact decimals, not rounded binary floats.
    Operator order, whitespace/case, space-group-name spacing and the optional
    PG prefix are formatting only. No algebraic operator equivalence is assumed.
    Dataset numbers/names may differ, but every declared dataset must have the
    global cell and every column must resolve to a declared dataset.
    """
    _, headers = _mtz_headers(blob)
    records: dict[str, list[list[str]]] = {}
    for line in headers:
        tokens = shlex.split(line)
        if tokens:
            records.setdefault(tokens[0], []).append(tokens[1:])

    def one(key: str) -> list[str]:
        rows = records.get(key, [])
        if len(rows) != 1:
            raise ValueError(f"MTZ context requires exactly one {key} record")
        return rows[0]

    def numbers(tokens: list[str], count: int, label: str) -> list[Decimal]:
        if len(tokens) != count:
            raise ValueError(f"MTZ context {label} requires {count} numeric fields")
        try:
            values = [Decimal(token) for token in tokens]
        except InvalidOperation as exc:
            raise ValueError(f"MTZ context {label} has invalid numeric fields") from exc
        if any(not value.is_finite() for value in values):
            raise ValueError(f"MTZ context {label} has nonfinite numeric fields")
        return values

    cell = numbers(one("CELL"), 6, "CELL")
    if any(value <= 0 for value in cell[:3]) or any(not 0 < value < 180 for value in cell[3:]):
        raise ValueError("MTZ context CELL has invalid lengths or angles")
    resolution = numbers(one("RESO"), 2, "RESO")
    if not 0 < resolution[0] <= resolution[1]:
        raise ValueError("MTZ context RESO requires positive ordered inverse-square limits")
    info = one("SYMINF")
    if len(info) not in (6, 7):
        raise ValueError("MTZ context SYMINF has an unsupported shape")
    operator_count, primitive_count, group_number = int(info[0]), int(info[1]), int(info[3])
    lattice = info[2].upper()
    if (operator_count <= 0 or not 0 < primitive_count <= operator_count
            or operator_count % primitive_count or not 1 <= group_number <= 230
            or lattice not in {"P", "A", "B", "C", "I", "F", "R", "H"}):
        raise ValueError("MTZ context SYMINF has invalid counts, lattice or group number")
    symbol = "".join(info[4].upper().split())
    point_group = info[5].upper().removeprefix("PG")
    if not symbol or not point_group:
        raise ValueError("MTZ context SYMINF lacks a group symbol")
    if len(info) == 7 and info[6] != "X":
        raise ValueError("MTZ context SYMINF has an unsupported trailing field")
    operators = []
    for row in records.get("SYMM", []):
        operator = "".join(row).upper()
        components = operator.split(",")
        if (len(components) != 3
                or any(not re.fullmatch(r"[+-]?[XYZ](?:[+-](?:\d+/[1-9]\d*|\d+))?", part)
                       for part in components)
                or sorted(re.findall(r"[XYZ]", operator)) != ["X", "Y", "Z"]):
            raise ValueError("MTZ context SYMM has an unsupported operator shape")
        operators.append(operator)
    if len(operators) != operator_count or len(set(operators)) != operator_count:
        raise ValueError("MTZ context SYMM count or uniqueness disagrees with SYMINF")

    ndif = one("NDIF")
    if len(ndif) != 1 or int(ndif[0]) <= 0:
        raise ValueError("MTZ context NDIF requires one positive dataset count")
    datasets: set[int] = set()
    for row in records.get("DATASET", []):
        if len(row) < 2:
            raise ValueError("MTZ context DATASET lacks its id or name")
        dataset_id = int(row[0])
        if dataset_id < 0 or dataset_id in datasets:
            raise ValueError("MTZ context DATASET has invalid or duplicate ids")
        datasets.add(dataset_id)
    cells: set[int] = set()
    for row in records.get("DCELL", []):
        if len(row) != 7:
            raise ValueError("MTZ context DCELL requires an id and six cell fields")
        dataset_id = int(row[0])
        if dataset_id not in datasets or dataset_id in cells:
            raise ValueError("MTZ context DCELL has undeclared or duplicate dataset ids")
        if numbers(row[1:], 6, "DCELL") != cell:
            raise ValueError("MTZ context DCELL differs from global CELL")
        cells.add(dataset_id)
    if len(datasets) != int(ndif[0]) or cells != datasets:
        raise ValueError("MTZ context DATASET/DCELL coverage disagrees with NDIF")
    columns = records.get("COLUMN", [])
    if not columns or any(len(row) != 5 or int(row[4]) not in datasets for row in columns):
        raise ValueError("MTZ context COLUMN lacks a declared dataset association")

    def exact_decimal(value: Decimal) -> str:
        # Decimal.normalize() uses ambient precision and could silently erase
        # a small header difference. Strip zeros on the exact tuple instead.
        sign, digits, exponent = value.as_tuple()
        digits = list(digits)
        while len(digits) > 1 and digits[-1] == 0:
            digits.pop()
            exponent += 1
        return str(Decimal((sign, tuple(digits), exponent)))

    return {
        "cell_a_b_c_alpha_beta_gamma": [exact_decimal(value) for value in cell],
        "resolution_limits_inverse_a2": [exact_decimal(value) for value in resolution],
        "symmetry": {"operator_count": operator_count, "primitive_operator_count": primitive_count,
                     "lattice": lattice, "space_group_number": group_number,
                     "space_group_symbol": symbol, "point_group": point_group,
                     "operators_xyz": sorted(operators)},
    }


def observation_digest(rows: dict[tuple[int, ...], tuple[bytes, bytes]]) -> str:
    return sha256(b"".join(struct.pack("<iii", *key) + b"".join(rows[key]) for key in sorted(rows)))


def audit(repo: Path = REPO) -> dict[str, Any]:
    archive_bytes = (repo / ARCHIVE).read_bytes()
    if sha256(archive_bytes) != ARCHIVE_SHA256:
        raise ValueError("retained archive differs from the reviewed exact artifact")
    with zipfile.ZipFile(repo / ARCHIVE) as archive:
        members = archive.infolist()
        for name in (MODEL_MEMBER, DATA_MEMBER):
            if sum(row.filename == name for row in members) != 1:
                raise ValueError(f"archive member is missing or duplicated: {name}")
        model_bytes, data_bytes = archive.read(MODEL_MEMBER), archive.read(DATA_MEMBER)
    atoms = pdb_atoms(model_bytes.decode("ascii"))
    protein = [a for a in atoms if a["key"][3] in AMINO_ACIDS]
    water = [a for a in atoms if a["key"][3] == "HOH"]
    water_residues = {a["key"][:4] for a in water}
    if len(water_residues) != len(water):
        raise ValueError("water selection is not one heavy atom per residue")
    protein_b = statistics.fmean(a["b_factor"] for a in protein)
    ligands = []
    for chain, residue, name in (("A", "98", "CA"), ("B", "98", "NA"), ("A", "97", "SO4")):
        selected = [a for a in atoms if a["key"][:4] == (chain, residue, "", name)]
        mean_b = statistics.fmean(a["b_factor"] for a in selected)
        ligands.append({"chain": chain, "residue_number": int(residue), "modelled_component": name,
                        "atom_count": len(selected), "mean_b_factor_a2": mean_b,
                        "mean_b_over_global_protein_mean": mean_b / protein_b,
                        "atoms": selected})
    ctruncate_path = BASE / "t13_oracle_logs/ctruncate.log"
    aimless_path = BASE / "t13_oracle_logs/aimless.log"
    output_path = BASE / "t13_oracle_logs/ctruncate_out.mtz"
    log_bytes, aimless_bytes, output_bytes = [(repo / path).read_bytes()
                                            for path in (ctruncate_path, aimless_path, output_path)]
    original = mtz_observations(data_bytes, ("F-obs", "SIGF-obs"))
    retained = mtz_observations(output_bytes, ("F", "SIGF"))
    if original != retained:
        raise ValueError("saved ctruncate selected observations differ from archived data")
    original_context = mtz_crystallographic_context(data_bytes)
    retained_context = mtz_crystallographic_context(output_bytes)
    if original_context != retained_context:
        raise ValueError("saved ctruncate crystallographic context differs from archived data")
    context_headers = {
        label: [line for line in _mtz_headers(blob)[1]
                if line.split() and line.split()[0] in {"CELL", "SYMINF", "SYMM", "RESO", "NDIF", "DATASET", "DCELL", "COLUMN"}]
        for label, blob in (("archived_input", data_bytes), ("ctruncate_output", output_bytes))
    }
    if b"hkl_unmerge_list::prepare - EMPTY" not in aimless_bytes:
        raise ValueError("retained aimless log does not show the recorded failure")
    return {
        "audit_kind": "retained-coordinate recount and saved-log parsing; no external oracle invocation",
        "evidence_ref": EVIDENCE_REF,
        "replay_command": ".venv/bin/python scripts/audit_1sar_retained_evidence.py",
        "audit_source_sha256": sha256(Path(__file__).read_bytes()),
        "t13_parser_source_sha256": sha256((repo / "scripts/t13_data_quality.py").read_bytes()),
        "archive": {"path": ARCHIVE.as_posix(), "sha256": ARCHIVE_SHA256, "member_count": len(members)},
        "model": {"member": MODEL_MEMBER, "sha256": sha256(model_bytes),
                  "subject_ref": "artifact:cdba2c07-daff-4f60-ae96-12452b3a5fbb#" + MODEL_MEMBER},
        "dataset": {"member": DATA_MEMBER, "sha256": sha256(data_bytes),
                    "subject_ref": "mtz:sha256:" + sha256(data_bytes)},
        "coordinate_selections": {
            "policy": "All non-H/D fixed-column atoms; protein means standard amino-acid residues only, not all ATOM records. No altlocs, no occupancy weighting.",
            "all_heavy_atoms_b_a2": distribution([a["b_factor"] for a in atoms]),
            "standard_amino_acid_atoms_b_a2": distribution([a["b_factor"] for a in protein]),
            "waters_b_a2": distribution([a["b_factor"] for a in water]),
            "water_residue_count": len(water_residues),
            "ligands": ligands,
            "ratio_interpretation": "Global protein denominator, not a local surrounding shell; no element-identity, occupancy or quality inference.",
        },
        "t13": {
            "execution_date_in_retained_logs": "2026-05-04",
            "logs": [{"path": path.as_posix(), "sha256": sha256(blob)}
                     for path, blob in ((ctruncate_path, log_bytes), (aimless_path, aimless_bytes))],
            "ctruncate_output": {"path": output_path.as_posix(), "sha256": sha256(output_bytes)},
            "selected_observation_equivalence": {
                "matching_reflection_keys": len(original), "exact_selected_float_bytes_equal": True,
                "canonical_hkl_f_sigf_sha256": observation_digest(original),
                "limitation": "Proves equality of retained selected observations, not the full bytes of the unretained historical input file or a new execution.",
            },
            "crystallographic_context_equivalence": {
                "normalized_context_equal": True, "normalized_context": original_context,
                "retained_header_records": context_headers,
                "comparison_policy": "Exact decimal CELL/RESO, normalized SYMINF and sorted whitespace/case-normalized SYMM operators; all declared DCELLs equal CELL and all column dataset ids resolve. Dataset ids/names are not cross-file identities. No reindexing or algebraic operator equivalence is assumed.",
                "limitation": "Together with selected-observation equality, establishes retained data/context equivalence only; does not recover the historical input file bytes or assert a new scientific execution.",
            },
            "ctruncate_parsed": parse_ctruncate(log_bytes.decode(), ctruncate_path.as_posix()),
            "aimless_status": "failed: hkl_unmerge_list::prepare - EMPTY",
        },
    }


if __name__ == "__main__":
    print(json.dumps(audit(), indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False))
