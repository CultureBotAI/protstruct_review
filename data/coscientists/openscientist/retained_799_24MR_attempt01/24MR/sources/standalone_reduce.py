"""Dictionary-explicit, evidence-retaining standalone Reduce execution (#799).

Old bare PDB caches do not prove that Reduce loaded a dictionary. Never reuse
them. A successful cache entry binds the exact input, executable, dictionary,
options, stdout and stderr. Invalid evidence is an error, not permission to
overwrite history; use a fresh work directory to repeat a damaged invocation.
"""
from __future__ import annotations

import hashlib
import json
import re
import tempfile
from pathlib import Path

import toolchain


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _file_identity(path: Path) -> dict[str, str]:
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or not resolved.stat().st_size:
        raise ValueError(f"Reduce requires a nonempty file: {path}")
    return {"path": str(resolved), "sha256": _sha256(resolved)}


def build_hydrogens(model: Path, work: Path, *, nuclear: bool = False) -> Path:
    """Build with an explicit dictionary; retain separate stdout/stderr evidence.

    This deliberately invokes only standalone Reduce, not a PHENIX version
    probe or wrapper. Dictionary and binary defaults belong to toolchain.py.
    A dictionary error is fatal even when Reduce returns zero with a PDB.
    """
    inputs = {
        "model": _file_identity(model),
        "executable": _file_identity(toolchain.REDUCE),
        "dictionary": _file_identity(toolchain.REDUCE_HET_DICT),
    }
    arguments = [inputs["executable"]["path"], "-quiet", "-build",
                 "-DB", inputs["dictionary"]["path"]]
    if nuclear:
        arguments.append("-nuclear")
    arguments.append(inputs["model"]["path"])
    invocation = {"contract": 1, "inputs": inputs, "argv": arguments}
    key = hashlib.sha256(json.dumps(invocation, sort_keys=True).encode()).hexdigest()
    destination = work.resolve() / "reduce_dictionary_v1" / key
    suffix = "nuc" if nuclear else "ec"
    output_name = f"{Path(inputs['model']['path']).stem}_h_{suffix}_{key[:16]}.pdb"

    if destination.exists():
        try:
            manifest = json.loads((destination / "manifest.json").read_text())
            valid = (isinstance(manifest, dict)
                     and manifest.get("invocation") == invocation
                     and type(manifest.get("returncode")) is int
                     and manifest["returncode"] == 0
                     and manifest.get("output_sha256") == _sha256(destination / output_name)
                     and manifest.get("stderr_sha256") == _sha256(destination / "stderr.log"))
        except (OSError, ValueError):
            valid = False
        if not valid:
            raise RuntimeError(f"Invalid Reduce cache evidence: {destination}; use a fresh work directory")
        return destination / output_name

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{key[:16]}-", dir=destination.parent))
    output = staging / output_name
    error_log = staging / "stderr.log"
    # Keep failed attempts, including stderr, as diagnostic evidence. Only a
    # completely successful bundle receives the reusable content-addressed name.
    with error_log.open("w") as errors:
        process = toolchain.run_to_file(arguments, output, stderr=errors, timeout=3600)
    diagnostics = error_log.read_text(errors="replace")
    if process.returncode or re.search(r"ERROR\s+CTab|could not open", diagnostics, re.IGNORECASE):
        raise RuntimeError(f"Reduce failed (exit {process.returncode}); retained stderr: {error_log}")
    if not any(line.startswith(("ATOM  ", "HETATM"))
               for line in output.read_text(errors="replace").splitlines()):
        raise RuntimeError(f"Reduce produced no coordinate records; retained stderr: {error_log}")
    # Refuse publication if a source was changed while the external process ran.
    for item in inputs.values():
        if _sha256(Path(item["path"])) != item["sha256"]:
            raise RuntimeError(f"Reduce input changed during execution; retained attempt: {staging}")
    manifest = {"invocation": invocation, "returncode": process.returncode,
                "output_sha256": _sha256(output), "stderr_sha256": _sha256(error_log)}
    (staging / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    staging.rename(destination)
    return destination / output_name
