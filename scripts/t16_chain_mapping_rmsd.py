#!/usr/bin/env python3
"""Measure chainwise C-alpha Kabsch RMSD for disclosed DockQ mappings.

The command reads either a candidate PDB file or one PDB member directly from
an artifact ZIP, so mapping-selection evidence can name and hash the exact
archived input without extracting a second untracked copy.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import sys
import zipfile
from pathlib import Path
from typing import Any

import numpy as np


ResidueKey = tuple[str, str, str]


def _pdb_ca(text: str, chain_id: str) -> dict[ResidueKey, np.ndarray]:
    """Return one C-alpha coordinate per standard residue for a PDB chain."""
    rows: dict[ResidueKey, tuple[str, np.ndarray]] = {}
    for line in text.splitlines():
        if not line.startswith("ATOM  ") or line[12:16].strip() != "CA":
            continue
        if line[21:22] != chain_id:
            continue
        altloc = line[16:17]
        if altloc not in {" ", "A"}:
            continue
        key = (line[22:26].strip(), line[26:27].strip(), line[17:20].strip())
        coord = np.array(
            [float(line[30:38]), float(line[38:46]), float(line[46:54])],
            dtype=float,
        )
        existing = rows.get(key)
        if existing is None or (existing[0] != " " and altloc == " "):
            rows[key] = (altloc, coord)
    return {key: value[1] for key, value in rows.items()}


def kabsch_rmsd(moving: np.ndarray, fixed: np.ndarray) -> float:
    """Unweighted, reflection-free Kabsch RMSD after independent centering."""
    if moving.shape != fixed.shape or moving.ndim != 2 or moving.shape[1] != 3:
        raise ValueError("Kabsch inputs must be equal N x 3 arrays")
    if moving.shape[0] < 3:
        raise ValueError("at least three matched C-alpha atoms are required")
    moving_centered = moving - moving.mean(axis=0)
    fixed_centered = fixed - fixed.mean(axis=0)
    u, _singular_values, vh = np.linalg.svd(moving_centered.T @ fixed_centered)
    rotation = u @ vh
    if np.linalg.det(rotation) < 0:
        vh[-1, :] *= -1
        rotation = u @ vh
    fitted = moving_centered @ rotation
    return float(np.sqrt(np.mean(np.sum((fitted - fixed_centered) ** 2, axis=1))))


def compare_pair(
    candidate_text: str,
    reference_text: str,
    model_chain: str,
    native_chain: str,
) -> dict[str, Any]:
    model = _pdb_ca(candidate_text, model_chain)
    native = _pdb_ca(reference_text, native_chain)
    shared = sorted(model.keys() & native.keys())
    rmsd = kabsch_rmsd(
        np.array([model[key] for key in shared]),
        np.array([native[key] for key in shared]),
    )
    return {
        "model_chain": model_chain,
        "native_chain": native_chain,
        "matched_ca_count": len(shared),
        "rmsd_a": round(rmsd, 6),
    }


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _display_path(path: Path) -> str:
    """Prefer a repository-relative executable/script path when reproducible."""
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.as_posix()


def _invocation_args(argv: list[str]) -> list[str]:
    """Retain the Python interpreter as well as the script and its arguments."""
    interpreter = _display_path(Path(sys.executable))
    interpreter_path = Path(interpreter)
    if (
        interpreter_path.parent.as_posix() == ".venv/bin"
        and interpreter_path.name.startswith("python3")
    ):
        # `uv run` and validate.sh may enter the same environment through its
        # python3 alias.  Canonicalize that alias so retained evidence does not
        # drift solely because the shell selected python rather than python3.
        interpreter = ".venv/bin/python"
    return [
        interpreter,
        _display_path(Path(__file__)),
        *argv,
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--candidate", type=Path)
    source.add_argument("--candidate-zip", type=Path)
    parser.add_argument("--candidate-member")
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument(
        "--pair",
        action="append",
        required=True,
        help="MODEL:NATIVE one-character chain pair; repeat for every comparison",
    )
    args = parser.parse_args(argv)

    if args.candidate_zip:
        if not args.candidate_member:
            parser.error("--candidate-zip requires --candidate-member")
        with zipfile.ZipFile(args.candidate_zip) as archive:
            candidate_bytes = archive.read(args.candidate_member)
        candidate_source: dict[str, str] = {
            "archive": args.candidate_zip.as_posix(),
            "member": args.candidate_member,
        }
    else:
        if args.candidate_member:
            parser.error("--candidate-member is valid only with --candidate-zip")
        candidate_bytes = args.candidate.read_bytes()
        candidate_source = {"path": args.candidate.as_posix()}

    reference_bytes = args.reference.read_bytes()
    candidate_text = candidate_bytes.decode("utf-8")
    reference_text = reference_bytes.decode("utf-8")
    comparisons = []
    for pair in args.pair:
        model_chain, separator, native_chain = pair.partition(":")
        if separator != ":" or len(model_chain) != 1 or len(native_chain) != 1:
            parser.error(f"invalid --pair {pair!r}; expected one-character MODEL:NATIVE")
        comparisons.append(
            compare_pair(candidate_text, reference_text, model_chain, native_chain)
        )

    invoked = _invocation_args(argv if argv is not None else sys.argv[1:])
    result = {
        "format_version": 1,
        "method": "unweighted reflection-free Kabsch fit of residue-matched C-alpha atoms",
        "matching_key": ["PDB residue sequence number", "insertion code", "residue name"],
        "atom_selection": "ATOM records named CA; blank altloc preferred, otherwise A",
        "software": {
            "script": "scripts/t16_chain_mapping_rmsd.py",
            "numpy_version": np.__version__,
            # The calculation depends on the Python language/runtime line, not
            # the maintenance-patch build. Record the governed major.minor
            # compatibility boundary so replay is exact across locked CI hosts.
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
        },
        "command": shlex.join(invoked),
        "candidate": {**candidate_source, "sha256": _sha256(candidate_bytes)},
        "reference": {
            "path": args.reference.as_posix(),
            "sha256": _sha256(reference_bytes),
        },
        "comparisons": comparisons,
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
