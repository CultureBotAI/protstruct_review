#!/usr/bin/env python3
"""Read-only observed atom/H/D inventory of one retained standalone bundle.

No tools, network, chemical coverage inference, flip parsing or grading. The
original retained paths and their byte identities must remain available.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import stat
import sys

import bench_dictionary_loaded_reduce as driver
import recount_standalone_reduce_flips as retained

CONTRACT = "standalone-reduce-observed-component-inventory/1"
KEY_FIELDS = ("model_ordinal", "model_label_raw", "chain_raw", "resnum", "icode", "resname_raw")
LIMITATION = (
    "Observed coordinate-record counts only, not dictionary coverage, chemical "
    "completeness, protonation correctness, or proof of missing/added chemistry. "
    "Input-only/output-only means absence of the exact record identity in one "
    "retained file, not chemical absence. No historical reproduction or grade."
)


def regular_bytes(path: Path) -> bytes:
    """Read a regular file without following any inner path symlink (#870).

    Directory descriptors bind traversal; O_NONBLOCK also prevents a raced FIFO
    replacement from blocking before fstat rejects it. The entry alias is
    canonicalized once by inventory_bundle, not by this artifact reader.
    """
    path = Path(path).absolute()
    if ".." in path.parts:
        raise ValueError(f"Unsupported parent traversal: {path}")
    directory = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise ValueError(f"Regular evidence file required: {path}")
            chunks = []
            remaining = before.st_size + 1
            while remaining:
                chunk = os.read(descriptor, min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            data = b"".join(chunks)
            after = os.fstat(descriptor)
            driver.require(len(data) == before.st_size == after.st_size
                           and before.st_mtime_ns == after.st_mtime_ns
                           and before.st_ctime_ns == after.st_ctime_ns,
                           f"file changed while reading: {path}")
            return data
        finally:
            os.close(descriptor)
    finally:
        os.close(directory)


def checked_bytes(path: Path, sha256: str) -> bytes:
    return driver.checked_bytes(path, sha256, read_bytes=regular_bytes)


def checked_inventory(directory: Path, files: dict) -> None:
    retained.checked_inventory(directory, files, read_bytes=regular_bytes)


def admit_evidence(request: dict, directory: Path, worker: dict) -> None:
    driver.admit_evidence(request, directory, worker, read_bytes=regular_bytes)


def check_worker_cleanup(directory: Path, parent: dict, worker: dict, request: dict) -> None:
    """Bind a cleanup receipt to this exact isolated worker and launch (#869)."""
    process = parent["process"]
    cleanup = process.get("cleanup") or {}
    launch = json.loads(original_bytes(directory, "launch-request.json", parent, worker))
    started = json.loads(original_bytes(directory, "worker-start.json", parent, worker))
    sources = [item["path"] for item in request["source_files"]
               if Path(item["path"]).name == "bench_dictionary_loaded_reduce.py"]
    driver.require(len(sources) == 1, "one retained worker driver required")
    argv = launch.get("argv")
    driver.require(isinstance(argv, list) and len(argv) == 5 and all(isinstance(arg, str) for arg in argv)
                   and argv[1:] == ["-B", sources[0], "--worker", str(directory / "request.json")]
                   and Path(argv[0]).is_absolute()
                   and str(Path(argv[0]).resolve(strict=True)) == request["python"]["executable"]
                   and process.get("arguments") == argv
                   and type(launch.get("timeout_seconds")) is int and launch["timeout_seconds"] == driver.TIMEOUT,
                   "worker launch binding")
    identities = [process.get("pid"), process.get("pgid"), started.get("pid"), started.get("pgid"), cleanup.get("pgid")]
    driver.require(all(type(value) is int and value > 0 for value in identities)
                   and len(set(identities)) == 1 and process.get("start_new_session") is True
                   and cleanup.get("status") == "group_absent" and cleanup.get("group_absent_verified") is True,
                   "verified owned-group cleanup must bind the isolated worker")


def counts(records: list[tuple[str, str, str]]) -> dict:
    elements = Counter(element for _, _, element in records)
    return {"atom_records": len(records), "h_records": elements["H"],
            "d_records": elements["D"], "other_element_records": len(records) - elements["H"] - elements["D"]}


def partition(records: list[tuple[str, str, str]]) -> dict:
    return {"counts": counts(records), "record_types": {
        kind: counts([row for row in records if row[0] == kind]) for kind in ("ATOM", "HETATM")}}


def coordinate_inventory(data: bytes, entry: str) -> dict:
    """Count each admitted coordinate record once, without expanding altlocs."""
    observed = driver.pdb_inventory(data, entry, allow_h=True)
    groups = {}
    atoms = set()
    model_label = None
    for line in data.decode("ascii").splitlines():
        if line[:6] == "MODEL ":
            model_label = line[10:14]
        if line[:6] not in ("ATOM  ", "HETATM"):
            continue
        # No hybrid-36 or other reinterpretation of the fixed decimal field.
        if not re.fullmatch(r" *-?\d+", line[22:26]):
            raise ValueError("Unsupported decimal residue identity")
        key = (1, model_label, line[20:22], int(line[22:26]), line[26], line[17:20])
        identity = (*key, line[12:16], line[16])
        if identity in atoms:
            raise ValueError("Duplicate coordinate identity")
        atoms.add(identity)
        groups.setdefault(key, []).append((line[:6].strip(), line[16], line[76:78].strip()))
    records = [record for group in groups.values() for record in group]
    water = [record for key, group in groups.items() if key[-1] == "HOH" for record in group]
    nonwater = [record for key, group in groups.items() if key[-1] != "HOH" for record in group]
    totals = {"all": partition(records), "exact_HOH": partition(water), "non_HOH": partition(nonwater)}
    driver.require(totals["all"]["counts"]["atom_records"] == observed["atom_records"]
                   and totals["all"]["counts"]["h_records"] == observed["h_all_records"]
                   and totals["non_HOH"]["counts"]["h_records"] == observed["h_nonwater_records"],
                   "component/global inventory agreement")
    return {"totals": totals, "groups": groups, "model_label_raw": model_label}


def describe_group(records: list[tuple[str, str, str]]) -> dict:
    return {**partition(records), "altlocs": [
        {"altloc": altloc, **partition([row for row in records if row[1] == altloc])}
        for altloc in sorted({row[1] for row in records})]}


def inventory_bytes(input_bytes: bytes, h_bytes: bytes, entry: str) -> dict:
    """Pure observed-record description; this function does not admit a bundle."""
    before = coordinate_inventory(input_bytes, entry)
    after = coordinate_inventory(h_bytes, entry)
    keys = set(before["groups"]) | set(after["groups"])
    components = []
    for key in sorted(keys, key=lambda item: (item[0], item[1] is not None, item[1] or "", *item[2:])):
        left, right = before["groups"].get(key, []), after["groups"].get(key, [])
        if key[-1] == "HOH" or not any(row[0] == "HETATM" for row in left + right):
            continue
        components.append({"identity": dict(zip(KEY_FIELDS, key, strict=True)),
                           "observed_presence": "both" if left and right else ("input_only" if left else "output_only"),
                           "input": describe_group(left), "output": describe_group(right),
                           "chemical_coverage": "unassessed"})
    return {"contract": CONTRACT, "status": "observed_counts_only", "bundle_admitted": False,
            "entry": entry, "input_sha256": driver.digest(input_bytes), "h_sha256": driver.digest(h_bytes),
            "input_model_label_raw": before["model_label_raw"], "output_model_label_raw": after["model_label_raw"],
            "input_totals": before["totals"], "output_totals": after["totals"],
            "nonwater_hetero_instances": components,
            "selection": "Exact non-HOH residue identity with any HETATM record in either file; "
                         "count both ATOM/HETATM partitions at that identity. No chemical-class inference.",
            "altloc_policy": "Literal records, no occupancy weighting or conformer expansion; "
                             "blank/common atoms occur once in their own blank partition.",
            "chemical_coverage": "unassessed", "limitation": LIMITATION}


def original_bytes(directory: Path, relative: str, parent: dict, worker: dict) -> bytes:
    expected = parent["retained_files"].get(relative)
    driver.require(expected is not None and worker["evidence_files"].get(relative) == expected,
                   f"original parent/worker pin missing: {relative}")
    return checked_bytes(directory / relative, expected)


def diagnostic_records(directory: Path, parent: dict, worker: dict, tools: dict) -> list[dict]:
    """Keep complete stderr and the combined launch log without guessing causes."""
    required = {f"commands/{number:02d}/stderr.bin" for number in range(1, len(worker["command_receipts"]) + 1)}
    paths = {name for name in parent["retained_files"] if Path(name).name in ("stderr.bin", "stderr.log")}
    driver.require(required <= paths, "command stderr pins missing")
    records = []
    for relative in sorted(paths):
        raw = original_bytes(directory, relative, parent, worker)
        records.append({"path": relative, "sha256": driver.digest(raw), "bytes": len(raw),
                        "stream": "stderr", "text": raw.decode("utf-8", errors="replace"),
                        "assignment": "unassigned"})
    for name in sorted(set(tools) - {"dictionary"}):
        relative = f"{name}-version.json"
        raw = original_bytes(directory, relative, parent, worker)
        records.append({"path": relative, "sha256": driver.digest(raw), "bytes": len(raw),
                        "stream": "captured version stderr", "json_field": "stderr",
                        "text": json.loads(raw)["stderr"], "assignment": "unassigned"})
    relative = "worker.log"
    driver.require(relative in parent["retained_files"], "combined launch log pin missing")
    raw = checked_bytes(directory / relative, parent["retained_files"][relative])
    records.append({"path": relative, "sha256": driver.digest(raw), "bytes": len(raw),
                    "stream": "combined launch stdout/stderr and cleanup diagnostics",
                    "text": raw.decode("utf-8", errors="replace"), "assignment": "unassigned"})
    return records


def inventory_bundle(directory: Path) -> dict:
    directory = directory.resolve(strict=True)
    sources = {Path(path).absolute(): regular_bytes(Path(path))
               for path in (__file__, driver.__file__, retained.__file__)}
    parent_bytes = regular_bytes(directory / "result.json")
    parent = json.loads(parent_bytes)
    process = parent.get("process", {})
    driver.require(parent.get("status") == "complete" and type(process.get("returncode")) is int
                   and process["returncode"] == 0 and process.get("timed_out") is False,
                   "parent process did not complete successfully")
    checked_inventory(directory, parent["retained_files"])
    driver.require({"request.json", "worker-result.json"} <= parent["retained_files"].keys(),
                   "parent request/worker pins missing")
    request = json.loads(checked_bytes(directory / "request.json", parent["retained_files"]["request.json"]))
    worker = json.loads(checked_bytes(directory / "worker-result.json", parent["retained_files"]["worker-result.json"]))
    driver.require(request.get("contract") == 1 and request.get("mode") == "execute"
                   and request.get("entry") in driver.COHORTS.get(request.get("cohort"), ())
                   and request.get("cohort_ids") == list(driver.COHORTS[request["cohort"]])
                   and Path(request["evidence_root"]) / request["entry"] == directory,
                   "unsupported request or mismatched entry")
    driver.require(worker.get("status") == "complete", "worker attempt is not complete")
    checked_inventory(directory, worker["evidence_files"])
    driver.require(all(parent["retained_files"].get(key) == value for key, value in worker["evidence_files"].items()),
                   "parent/worker evidence pins disagree")
    check_worker_cleanup(directory, parent, worker, request)
    admit_evidence(request, directory, worker)
    provenance = json.loads(original_bytes(directory, "input-provenance.json", parent, worker))
    tools = json.loads(original_bytes(directory, "tool-identities.json", parent, worker))
    input_bytes = original_bytes(directory, "input.pdb", parent, worker)
    h_relative = Path(worker["h_model"]["path"]).relative_to(directory).as_posix()
    h_bytes = original_bytes(directory, h_relative, parent, worker)
    driver.require(driver.digest(input_bytes) == provenance["retained_file"]["sha256"]
                   and driver.digest(h_bytes) == worker["h_model"]["sha256"], "read coordinate byte pins")
    result = inventory_bytes(input_bytes, h_bytes, request["entry"])
    result["unassigned_diagnostics"] = diagnostic_records(directory, parent, worker, tools)
    # Re-admit after interpretation: never repin modified evidence as a success.
    admit_evidence(request, directory, worker)
    checked_inventory(directory, worker["evidence_files"])
    checked_inventory(directory, parent["retained_files"])
    driver.require(regular_bytes(directory / "result.json") == parent_bytes, "parent changed during inventory")
    driver.require(all(regular_bytes(path) == value for path, value in sources.items()), "inventory source changed")
    result.update(status="complete_observed_inventory", bundle_admitted=True,
                  diagnostic_policy="Complete retained streams, unassigned; no warning classifier or residue attribution. "
                                    "UTF-8 replacement text is a view; path/hash identifies exact retained bytes.",
                  evidence={"entry_directory": str(directory), "cohort": request["cohort"],
                            "parent_sha256": driver.digest(parent_bytes), "retained_files": parent["retained_files"],
                            "postprocessor_sources": [{"path": str(path), "sha256": driver.digest(value)}
                                                      for path, value in sources.items()],
                            "boundary": "Original paths and original pins required. Mutation detection, not "
                                        "malicious-manifest authentication, execution attestation or relocatable replay."})
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("entry_directory", type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(inventory_bundle(args.entry_directory), indent=2, sort_keys=True, allow_nan=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        print(f"Inventory refused: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
