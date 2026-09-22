#!/usr/bin/env python3
"""Network-free checks for t16_chain_mapping_rmsd.py."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
from pathlib import Path

import numpy as np


SCRIPT = Path(__file__).with_name("t16_chain_mapping_rmsd.py")
REPO = SCRIPT.resolve().parent.parent
spec = importlib.util.spec_from_file_location("t16_chain_mapping_rmsd", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


def check(label: str, condition: bool) -> None:
    if not condition:
        raise SystemExit(f"FAIL  {label}")
    print(f"PASS  {label}")


def atom(serial: int, chain: str, residue: int, xyz: tuple[float, float, float]) -> str:
    x, y, z = xyz
    return (
        f"ATOM  {serial:5d}  CA  ALA {chain}{residue:4d}    "
        f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00 10.00           C"
    )


fixed = [(0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 3.0, 0.0), (0.0, 0.0, 4.0)]
moving = [(10.0 - y, 20.0 + x, 30.0 + z) for x, y, z in fixed]
candidate = "\n".join(atom(i, "A", i, xyz) for i, xyz in enumerate(moving, 1))
reference = "\n".join(atom(i, "B", i, xyz) for i, xyz in enumerate(fixed, 1))
result = module.compare_pair(candidate, reference, "A", "B")
check("all residue-matched C-alpha atoms are counted", result["matched_ca_count"] == 4)
check("rigid rotation and translation fit to zero RMSD", result["rmsd_a"] == 0.0)

reflected = np.array(fixed, dtype=float)
reflected[:, 0] *= -1
check(
    "reflection is not accepted as a rigid rotation",
    module.kabsch_rmsd(np.array(fixed), reflected) > 0.1,
)
invocation = module._invocation_args(["--pair", "A:A"])
check(
    "retained invocation includes an explicit Python interpreter",
    Path(invocation[0]).name.startswith("python")
    and invocation[1].endswith("scripts/t16_chain_mapping_rmsd.py"),
)

replay_args = [
    "--candidate-zip",
    "data/coscientists/openscientist/"
    "cdba2c07-daff-4f60-ae96-12452b3a5fbb_artifacts.zip",
    "--candidate-member",
    "data/1sar_final.pdb",
    "--reference",
    "data/pdb_mtz/1sar_deposited.pdb",
    "--pair",
    "A:A",
    "--pair",
    "B:B",
    "--pair",
    "A:B",
    "--pair",
    "B:A",
]
original_cwd = Path.cwd()
stdout = io.StringIO()
try:
    os.chdir(REPO)
    with contextlib.redirect_stdout(stdout):
        exit_status = module.main(replay_args)
finally:
    os.chdir(original_cwd)
expected_evidence = (
    REPO
    / "data/coscientists/openscientist/"
    "EVIDENCE_1sar_cdba2c07_2026-09-21_chain_mapping_rmsd.json"
).read_text()
check("committed 1SAR RMSD replay exits successfully", exit_status == 0)
actual_document = json.loads(stdout.getvalue())
expected_document = json.loads(expected_evidence)
version_pattern = re.compile(r"\d+(?:\.\d+)+(?:[A-Za-z0-9.+-]*)?")
for label, document in (("replay", actual_document), ("committed", expected_document)):
    software = document.get("software") or {}
    check(
        f"{label} RMSD evidence records well-formed runtime version provenance",
        all(
            isinstance(software.get(key), str)
            and version_pattern.fullmatch(software[key]) is not None
            for key in ("python_version", "numpy_version")
        ),
    )
check(
    "committed 1SAR RMSD evidence command is the exact canonical replay command",
    actual_document["command"] == expected_document["command"],
)
check(
    "committed 1SAR RMSD scientific and runtime provenance match the replay exactly",
    actual_document == expected_document,
)
print("all T16 chain-mapping RMSD tests passed")
