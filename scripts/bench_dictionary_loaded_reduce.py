#!/usr/bin/env python3
"""One-entry, standalone-only #799 evidence collection; plan-only by default.

No PHENIX, nuclear arm, cohort aggregation, historical reproduction claim, or
grading. Each execution owns an entirely new repository-local evidence root.
The parent orchestrator must inspect 24MR before expanding the fixed cohorts.
The flip arm retains raw USER MOD records/counts, not parsed flip conclusions.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.request

import bench_t05_clashscore_h as clash
from benchmark_environment import announce_benchmark_environment
from entry_sandbox import EntrySandbox
import standalone_reduce
import toolchain

REPO_ROOT = Path(__file__).resolve().parent.parent
TIMEOUT = 900
MAX_INPUT_BYTES = 64 * 1024 * 1024
DEFAULT_SET = tuple("24MR 37AS 37AP 11AF 28SZ 37BG 12LO 30IZ 9LLR 9PN7".split())
FLIP_SET = tuple("12OC 14ZZ 15C8 1A0C 1B9B 1BDJ 1OWJ 1RH7 1TIJ 1VYJ 1W1I 1ZY2 "
                 "2I4M 2IEF 2IY0 2QIZ 2QTU 2YOL 3A01 3G7M 3MIU 3ZM5 4DYT 4FN9 "
                 "4MH1 4NJD 4Q9R 4W7P 5DZK 5MAC 5T9A 5URQ 5X6C 6ABT 6LE5 6QGY "
                 "6TPW 7D6N 7LMC 7P4U 7PLN".split())
COHORTS = {"clashscore": DEFAULT_SET, "flip": FLIP_SET}
SOURCE_FILES = ("bench_dictionary_loaded_reduce.py", "standalone_reduce.py",
                "bench_t05_clashscore_h.py", "toolchain.py", "entry_sandbox.py",
                "benchmark_environment.py")
LIMITATION = ("New retained-input observation, not authenticated historical reproduction; "
              "informational only. No PHENIX comparator or independent grading is supplied.")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_new(path: Path, data: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(data)


def save_new(path: Path, value: dict) -> None:
    write_new(path, (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode())


def identity(path: Path) -> dict:
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or not resolved.stat().st_size:
        raise ValueError(f"Nonempty file required: {path}")
    return {"path": str(resolved), "sha256": digest(resolved.read_bytes()), "bytes": resolved.stat().st_size}


def verify_identity(record: dict) -> None:
    if identity(Path(record["path"])) != record:
        raise ValueError(f"Source/input/executable changed: {record['path']}")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(f"Inconsistent retained evidence: {message}")


def checked_bytes(path: Path, sha256: str) -> bytes:
    data = path.read_bytes()
    require(digest(data) == sha256, f"bytes changed: {path}")
    return data


def pdb_inventory(data: bytes, entry: str, *, allow_h: bool = False) -> dict:
    """Narrow PDB admission; no inferred element, model selection or renumbering."""
    lines = data.decode("ascii").splitlines()
    headers = [line for line in lines if line[:6] == "HEADER"]
    if len(headers) != 1 or headers[0][62:66].strip().upper() != entry:
        raise ValueError("Require exactly one HEADER with the selected entry ID")
    models = [i for i, line in enumerate(lines) if line[:6] == "MODEL "]
    ends = [i for i, line in enumerate(lines) if line[:6] == "ENDMDL"]
    if len(models) > 1 or len(ends) != len(models) or (models and models[0] >= ends[0]):
        raise ValueError("Multiple/ambiguous MODEL boundaries are unsupported")
    atoms, h_all, h_nonwater = 0, 0, 0
    keys, altlocs, icodes, hetero = set(), set(), set(), set()
    for number, line in enumerate(lines):
        if line[:6] not in ("ATOM  ", "HETATM"):
            continue
        if models and not models[0] < number < ends[0]:
            raise ValueError("Coordinate outside the sole MODEL")
        if len(line) < 78 or not re.fullmatch(r"[A-Z]{1,2}", line[76:78].strip()):
            raise ValueError("Missing/ambiguous explicit element")
        element = line[76:78].strip()
        if not allow_h and element in ("H", "D"):
            raise ValueError("Pre-existing H/D requires a preregistered preparation amendment")
        try:
            residue = int(line[22:26])
            values = [float(line[a:b]) for a, b in ((30, 38), (38, 46), (46, 54), (54, 60), (60, 66))]
        except ValueError as error:
            raise ValueError("Unsupported residue number or malformed coordinate/occupancy/B") from error
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Nonfinite coordinate/occupancy/B")
        if not line[12:16].strip() or not line[17:20].strip():
            raise ValueError("Missing atom or residue name")
        key = (line[21], residue, line[26], line[17:20], line[12:16], line[16])
        if key in keys:
            raise ValueError("Duplicate/ambiguous atom identity")
        keys.add(key)
        altlocs.add(line[16]); icodes.add(line[26])
        if line[:6] == "HETATM" and line[17:20] != "HOH":
            hetero.add(line[17:20])
        atoms += 1
        h_all += element == "H"
        h_nonwater += element == "H" and line[17:20] != "HOH"
    if not atoms:
        raise ValueError("No coordinate records")
    return {"atom_records": atoms, "h_all_records": h_all, "h_nonwater_records": h_nonwater,
            "model_count": 1, "altloc_codes": sorted(altlocs), "insertion_codes": sorted(icodes),
            "nonwater_hetero_components": sorted(hetero)}


def make_plan(args: argparse.Namespace) -> dict:
    entry = args.entry.upper()
    if entry not in COHORTS[args.cohort]:
        raise ValueError(f"{entry} is outside the fixed {args.cohort} cohort")
    root = args.evidence_root.resolve()
    if root == REPO_ROOT or not root.is_relative_to(REPO_ROOT) or ".git" in root.relative_to(REPO_ROOT).parts:
        raise ValueError("Evidence root must be a new contained repository-local directory")
    if root.exists() or args.evidence_root.is_symlink():
        raise FileExistsError("Evidence root already exists; use a new root per entry/attempt")
    if args.input is None and any((args.source_url, args.retrieved_at, args.unknown_origin_reason)):
        raise ValueError("Retained-input provenance options require --input")
    if args.input is not None and (not args.source_url or not args.retrieved_at) and not args.unknown_origin_reason:
        raise ValueError("Unknown original URL/retrieval time requires --unknown-origin-reason")
    if args.retrieved_at:
        moment = dt.datetime.fromisoformat(args.retrieved_at.replace("Z", "+00:00"))
        if moment.tzinfo is None:
            raise ValueError("Asserted retrieval time must include timezone")
    if args.source_url and not re.match(r"https?://[^/]+", args.source_url):
        raise ValueError("Asserted source URL must be HTTP(S)")
    return {"contract": 1, "mode": "execute" if args.execute else "plan_only", "entry": entry,
            "cohort": args.cohort, "cohort_ids": list(COHORTS[args.cohort]),
            "evidence_root": str(root), "timeout_seconds": TIMEOUT,
            "input": str(args.input.resolve()) if args.input else None,
            "source_url_asserted": args.source_url, "retrieved_at_asserted": args.retrieved_at,
            "unknown_origin_reason": args.unknown_origin_reason,
            "fetch_url": f"https://files.rcsb.org/download/{entry}.pdb" if args.input is None else None,
            "preregistration": str(args.preregistration.resolve()) if args.preregistration else None,
            "configured_tools": {"reduce": str(toolchain.REDUCE.resolve()), "probe": str(toolchain.PROBE.resolve()),
                                 "dictionary": str(toolchain.REDUCE_HET_DICT.resolve())},
            "expected_versions": {"reduce": toolchain.REDUCE_VERSION, "probe": toolchain.PROBE_VERSION},
            "nuclear": False, "flip_policy": "standalone -build (flips enabled)",
            "parsed_flip_conclusions": "unavailable; raw USER MOD/counts only",
            "limitation": LIMITATION}


def acquire_input(request: dict, entry_dir: Path) -> tuple[Path, dict]:
    started = utc_now()
    if request["input"]:
        original = identity(Path(request["input"]))
        if original["bytes"] > MAX_INPUT_BYTES:
            raise ValueError("Input exceeds bounded PDB size")
        data = Path(original["path"]).read_bytes()
        verify_identity(original)
        if digest(data) != original["sha256"]:
            raise ValueError("Retained input changed while copying")
        provenance = {"origin": "retained_local", "original_file": original,
                      "original_url": request["source_url_asserted"],
                      "original_retrieved_at": request["retrieved_at_asserted"],
                      "supplied_metadata_is_asserted": True,
                      "unknown_origin_reason": request["unknown_origin_reason"]}
    else:
        with urllib.request.urlopen(request["fetch_url"], timeout=180) as response:
            if response.status != 200:
                raise ValueError(f"Input fetch HTTP status {response.status}")
            data = response.read(MAX_INPUT_BYTES + 1)
            provenance = {"origin": "fresh_fetch", "requested_url": request["fetch_url"],
                          "response_url": response.geturl(), "http_status": response.status,
                          "response_headers": {key: response.headers.get(key) for key in
                                               ("Date", "ETag", "Last-Modified", "Content-Type")},
                          "retrieved_at": utc_now()}
    if not data or len(data) > MAX_INPUT_BYTES:
        raise ValueError("Empty or oversized PDB response")
    path = entry_dir / "input.pdb"
    write_new(path, data)
    provenance.update(acquisition_started_at=started, retained_at=utc_now(), retained_file=identity(path))
    save_new(entry_dir / "input-provenance.json", provenance)
    inventory = pdb_inventory(data, request["entry"])
    save_new(entry_dir / "input-inventory.json", inventory)
    return path, provenance


def version_evidence(name: str, executable: Path, expected: str, directory: Path) -> dict:
    args = [str(executable), "-version"]
    save_new(directory / f"{name}-version-request.json", {"argv": args, "started_at": utc_now()})
    try:
        result = toolchain.run_capture(args, cwd=directory, timeout=10)
    except (OSError, subprocess.SubprocessError) as error:
        record = {"argv": args, "error": f"{type(error).__name__}: {error}",
                  "completed_at": utc_now(), "expected_version": expected}
        for key in ("stdout", "stderr"):
            partial = getattr(error, key, None)
            if partial is not None:
                data = partial.encode() if isinstance(partial, str) else partial
                write_new(directory / f"{name}-version-{key}.bin", data)
                record[key + "_sha256"] = digest(data)
        save_new(directory / f"{name}-version.json", record)
        raise
    record = {"argv": args, "returncode": result.returncode, "stdout": result.stdout,
              "stderr": result.stderr, "completed_at": utc_now(), "expected_version": expected}
    save_new(directory / f"{name}-version.json", record)
    # Reduce's documented source branch for -Version exits 2; this exception is
    # not accepted for its H-building invocation or for Probe.
    expected_status = 2 if name == "reduce" else 0
    if result.returncode != expected_status or (result.stdout + result.stderr).strip() != f"{name}.{expected}":
        raise ValueError(f"Unverified {name} version; retained command evidence")
    return record


@contextmanager
def retain_helper_commands(entry_dir: Path, allowed: set[str]):
    """Add provenance at the existing helpers' I/O boundary, not scoring logic."""
    original, original_probe = toolchain.run_to_file, clash.run_to_file
    command_root = entry_dir / "commands"
    command_root.mkdir()
    sequence = 0
    receipts = []

    def recorded(arguments, output_path, **kwargs):
        nonlocal sequence
        argv = [str(argument) for argument in arguments]
        if str(Path(argv[0]).resolve()) not in allowed:
            raise ValueError("Unexpected executable in standalone-only worker")
        sequence += 1
        directory = command_root / f"{sequence:02d}"
        directory.mkdir()
        request_record = {"argv": argv, "started_at": utc_now(),
                 "cwd": str(Path.cwd()), "stdout_initial_path": str(output_path),
                 "timeout_seconds": kwargs.get("timeout")}
        save_new(directory / "request.json", request_record)
        outcome = {}
        try:
            result = original(arguments, output_path, **kwargs)
            outcome["returncode"] = result.returncode
            return result
        except BaseException as error:
            outcome["error"] = f"{type(error).__name__}: {error}"
            raise
        finally:
            stderr = kwargs.get("stderr")
            if hasattr(stderr, "flush"):
                stderr.flush()
            for source, name in ((Path(output_path), "stdout.bin"),
                                 (Path(stderr.name) if hasattr(stderr, "name") else None, "stderr.bin")):
                if source is not None and source.is_file():
                    data = source.read_bytes()
                    write_new(directory / name, data)
                    outcome[name + "_sha256"] = digest(data)
            outcome["completed_at"] = utc_now()
            save_new(directory / "result.json", outcome)
            receipts.append({"request": request_record, "result": outcome})

    toolchain.run_to_file = recorded
    clash.run_to_file = recorded
    try:
        yield receipts
    finally:
        toolchain.run_to_file, clash.run_to_file = original, original_probe


def recount_legacy_ec(raw: bytes, h_bytes: bytes) -> dict:
    """Read-only replay of the unchanged helper's EC rules, not a new definition."""
    pairs = set()
    for line in raw.decode(errors="ignore").splitlines():
        if not line.strip():
            continue
        fields = line.split(":")
        require(len(fields) == 19 and fields[2] in {"wc", "cc", "wh", "so", "bo", "wo", "hb"}
                and all(fields[index].strip() for index in (1, 3, 4, 12, 13)), "Probe contact grammar")
        numeric = [float(fields[index]) for index in (*range(5, 12), *range(14, 19))]
        require(all(math.isfinite(value) for value in numeric), "nonfinite Probe contact")
        if fields[2] in {"bo", "wo"} and numeric[0] <= clash.CLASH_OVERLAP:
            pairs.add(frozenset((fields[3], fields[4])))
    atoms = sum(line.startswith(("ATOM", "HETATM")) and line[17:20] != "HOH"
                for line in h_bytes.decode(errors="ignore").splitlines())
    require(atoms > 0, "zero legacy Probe denominator")
    return {"atom_count": atoms, "clash_pair_count": len(pairs),
            "clashscore": 1000.0 * len(pairs) / atoms,
            "clash_pairs": sorted(sorted(pair) for pair in pairs)}


def scoped_version_record(name: str, item: dict, version: dict, expected: str) -> dict:
    """Describe an already verified version command without invoking tools."""
    return {"expected_version": expected, "available": True,
            "reported_version": (version["stdout"] + version["stderr"]).strip(),
            "reported_version_source": "command_output", "executable_identity": item,
            "version_command": version}


def admit_evidence(request: dict, directory: Path, result: dict) -> None:
    """Require one coherent input/helper/raw/result chain at both boundaries."""
    def read_json(path):
        return json.loads(path.read_text())

    require(read_json(directory / "request.json") == request, "launch request changed")
    for source in request["source_files"]:
        verify_identity(source)
        checked_bytes(directory / "sources" / Path(source["path"]).name, source["sha256"])
    prereg = request["preregistration_identity"]
    verify_identity(prereg)
    checked_bytes(directory / "sources/preregistration.md", prereg["sha256"])
    provenance = read_json(directory / "input-provenance.json")
    model = provenance["retained_file"]
    require(Path(model["path"]) == directory / "input.pdb", "retained input location")
    verify_identity(model)
    model_bytes = checked_bytes(Path(model["path"]), model["sha256"])
    require(read_json(directory / "input-inventory.json") == pdb_inventory(model_bytes, request["entry"]),
            "input inventory")
    require(provenance["origin"] == ("retained_local" if request["input"] else "fresh_fetch"), "input origin")
    if provenance["origin"] == "retained_local":
        verify_identity(provenance["original_file"])
        require(provenance["original_file"]["path"] == request["input"]
                and provenance["original_file"]["sha256"] == model["sha256"]
                and provenance["original_url"] == request["source_url_asserted"]
                and provenance["original_retrieved_at"] == request["retrieved_at_asserted"]
                and provenance["unknown_origin_reason"] == request["unknown_origin_reason"]
                and provenance["supplied_metadata_is_asserted"] is True, "retained source/input binding")
    else:
        require(provenance["requested_url"] == request["fetch_url"], "fetch request binding")
    tools = read_json(directory / "tool-identities.json")
    scoped = {}
    for name, item in tools.items():
        verify_identity(item)
        require(item["path"] == request["configured_tools"][name], "configured tool binding")
        if name == "dictionary":
            continue
        version = read_json(directory / f"{name}-version.json")
        argv = [item["path"], "-version"]
        require(version["argv"] == argv and read_json(directory / f"{name}-version-request.json")["argv"] == argv
                and version["returncode"] == (2 if name == "reduce" else 0)
                and (version["stdout"] + version["stderr"]).strip() == f"{name}.{request['expected_versions'][name]}",
                "version evidence")
        scoped[name] = scoped_version_record(name, item, version, request["expected_versions"][name])
    environment = read_json(directory / "benchmark-environment.json")
    require(environment == result["benchmark_environment"]
            and environment["external_tools"] == scoped, "scoped environment evidence")

    receipts = result["command_receipts"]
    require(len(receipts) == (2 if request["cohort"] == "clashscore" else 1), "helper command count")
    for index, receipt in enumerate(receipts, start=1):
        command = directory / "commands" / f"{index:02d}"
        require(read_json(command / "request.json") == receipt["request"]
                and read_json(command / "result.json") == receipt["result"]
                and receipt["result"].get("returncode") == 0, "command receipt")
        for stream in ("stdout", "stderr"):
            checked_bytes(command / f"{stream}.bin", receipt["result"][f"{stream}.bin_sha256"])

    h_model = result["h_model"]
    h_path = Path(h_model["path"])
    require(h_path.is_relative_to(directory / "work"), "H output location")
    verify_identity(h_model)
    h_bytes = checked_bytes(h_path, h_model["sha256"])
    require(result["h_inventory"] == pdb_inventory(h_bytes, request["entry"], allow_h=True), "H inventory")
    raw_user_mod = b"".join(line for line in h_bytes.splitlines(keepends=True) if line.startswith(b"USER  MOD"))
    require((directory / "raw-user-mod.txt").read_bytes() == raw_user_mod
            and result["raw_user_mod_record_count"] == len(raw_user_mod.splitlines()), "raw USER MOD/count binding")
    reduce = read_json(h_path.parent / "manifest.json")
    inputs = {name: {key: item[key] for key in ("path", "sha256")}
              for name, item in (("model", model), ("executable", tools["reduce"]), ("dictionary", tools["dictionary"]))}
    reduce_argv = [tools["reduce"]["path"], "-quiet", "-build", "-DB", tools["dictionary"]["path"], model["path"]]
    require(reduce["invocation"] == {"contract": 1, "inputs": inputs, "argv": reduce_argv}
            and receipts[0]["request"]["argv"] == reduce_argv and reduce["returncode"] == 0,
            "Reduce invocation")
    require(reduce["output_sha256"] == h_model["sha256"] == receipts[0]["result"]["stdout.bin_sha256"]
            and reduce["stderr_sha256"] == receipts[0]["result"]["stderr.bin_sha256"], "Reduce output bindings")
    checked_bytes(h_path.parent / "stderr.log", reduce["stderr_sha256"])
    if request["cohort"] == "clashscore":
        manifest_path = Path(result["probe_manifest"])
        require(manifest_path.is_relative_to(directory / "work"), "Probe evidence location")
        probe = read_json(manifest_path)
        probe_argv = [tools["probe"]["path"], "-u", "-q", "-mc", "-het", "-once", "ogt33 not water", "ogt33", h_model["path"]]
        require(probe["argv"] == probe_argv == receipts[1]["request"]["argv"]
                and probe["returncode"] == 0 and probe["score_status"] == "measured"
                and probe["model_sha256"] == h_model["sha256"]
                and probe["executable_sha256"] == tools["probe"]["sha256"], "Probe invocation")
        for stream in ("stdout", "stderr"):
            require(probe[f"{stream}_sha256"] == receipts[1]["result"][f"{stream}.bin_sha256"], "Probe output binding")
        contacts = checked_bytes(manifest_path.parent / "stdout.txt", probe["stdout_sha256"])
        checked_bytes(manifest_path.parent / "stderr.log", probe["stderr_sha256"])
        recounted = recount_legacy_ec(contacts, h_bytes)
        require(all(probe[key] == value for key, value in recounted.items())
                and result["clashscore"] == recounted["clashscore"], "Probe counts/pairs/score")
    verify_identity(h_model)


def worker(request_file: Path, *, announce=announce_benchmark_environment) -> int:
    request = json.loads(request_file.read_text())
    directory = request_file.parent
    if (Path.cwd().resolve() != directory.resolve() or request["mode"] != "execute"
            or os.getpid() != os.getpgrp()
            or directory.resolve() != Path(request["evidence_root"]) / request["entry"]
            or request["cohort"] not in COHORTS
            or request["entry"] not in COHORTS[request["cohort"]]
            or request["cohort_ids"] != list(COHORTS[request["cohort"]])):
        raise ValueError("Worker requires its own explicit-execution request and entry cwd")
    save_new(directory / "worker-start.json", {"pid": os.getpid(), "pgid": os.getpgrp(), "started_at": utc_now()})
    result = {"status": "failed", "limitation": LIMITATION}
    try:
        for source in request["source_files"]:
            verify_identity(source)
        verify_identity(request["preregistration_identity"])
        model, provenance = acquire_input(request, directory)
        tools = {"reduce": identity(toolchain.REDUCE), "dictionary": identity(toolchain.REDUCE_HET_DICT)}
        if request["cohort"] == "clashscore":
            tools["probe"] = identity(toolchain.PROBE)
            if clash.PROBE.resolve() != toolchain.PROBE.resolve():
                raise ValueError("Probe helper configuration differs from the recorded toolchain")
        if any(record["path"] != request["configured_tools"][name] for name, record in tools.items()):
            raise ValueError("Worker configuration differs from its launch request")
        save_new(directory / "tool-identities.json", tools)
        scoped = {}
        for name in ("reduce", "probe"):
            if name in tools:
                version = version_evidence(name, Path(tools[name]["path"]), request["expected_versions"][name], directory)
                verify_identity(tools[name])
                scoped[name] = scoped_version_record(name, tools[name], version, request["expected_versions"][name])
        result["benchmark_environment"] = announce(stream=sys.stderr, external_tools=scoped)
        save_new(directory / "benchmark-environment.json", result["benchmark_environment"])
        with retain_helper_commands(directory, {v["path"] for k, v in tools.items() if k != "dictionary"}) as receipts:
            result["command_receipts"] = receipts
            h_model = standalone_reduce.build_hydrogens(model, directory / "work", nuclear=False)
            h_identity = identity(h_model)
            h_bytes = checked_bytes(h_model, h_identity["sha256"])
            verify_identity(h_identity)
            inventory = pdb_inventory(h_bytes, request["entry"], allow_h=True)
            if inventory["h_all_records"] == 0:
                raise ValueError("Reduce returned no H atoms")
            raw = "".join(line for line in h_bytes.decode("ascii").splitlines(keepends=True)
                          if line.startswith("USER  MOD"))
            write_new(directory / "raw-user-mod.txt", raw.encode("ascii"))
            result.update(h_model=h_identity, h_inventory=inventory,
                          raw_user_mod_record_count=len(raw.splitlines()),
                          component_dictionary_coverage="unavailable; loaded dictionary is not complete ligand H coverage",
                          parsed_flip_conclusions="unavailable; raw USER MOD/counts only")
            verify_identity(h_identity)
            if request["cohort"] == "clashscore":
                evidence = {}
                score = clash.run_probe_clashscore(h_model, directory / "work", evidence)
                if score is None or not math.isfinite(score):
                    raise ValueError("Standalone Probe score is unavailable")
                result.update(clashscore=score, probe_manifest=evidence["manifest"],
                              scoring_definition="unchanged legacy EC Probe helper; informational")
            verify_identity(result["h_model"])
        for record in [*tools.values(), provenance["retained_file"], *request["source_files"],
                       request["preregistration_identity"]]:
            verify_identity(record)
        if provenance["origin"] == "retained_local":
            verify_identity(provenance["original_file"])
        configured = {"reduce": toolchain.REDUCE, "dictionary": toolchain.REDUCE_HET_DICT,
                      "probe": toolchain.PROBE}
        if any(identity(configured[name]) != record for name, record in tools.items()):
            raise ValueError("Configured executable/dictionary identity changed during execution")
        admit_evidence(request, directory, result)
        # Pin the admitted bundle before publication. The still-open worker log
        # is deliberately outside this boundary and is inventoried by the parent.
        result["evidence_files"] = {str(path.relative_to(directory)): digest(path.read_bytes())
                                    for path in sorted(directory.rglob("*"))
                                    if path.is_file() and path.name != "worker.log"}
        result["status"] = "complete"
    except BaseException as error:
        result["error"] = f"{type(error).__name__}: {error}"
    result["completed_at"] = utc_now()
    save_new(directory / "worker-result.json", result)
    return 0 if result["status"] == "complete" else 1


def execute(request: dict) -> int:
    root = Path(request["evidence_root"])
    root.mkdir(parents=False, exist_ok=False)
    sandbox = EntrySandbox(root, request["entry"])
    outcome = {"status": "failed", "started_at": utc_now(), "limitation": LIMITATION}
    save_new(sandbox.path / "launch-plan.json", request)
    try:
        if not request["preregistration"]:
            raise ValueError("--execute requires a retained --preregistration file")
        prereg = Path(request["preregistration"]).resolve(strict=True)
        if not prereg.is_relative_to(REPO_ROOT):
            raise ValueError("Preregistration must be repository-local")
        request["preregistration_identity"] = identity(prereg)
        sources = sandbox.path / "sources"
        sources.mkdir()
        request["source_files"] = [identity(REPO_ROOT / "scripts" / name) for name in SOURCE_FILES]
        for record in request["source_files"]:
            retained = Path(record["path"]).read_bytes()
            if digest(retained) != record["sha256"]:
                raise ValueError("Source changed during snapshot")
            write_new(sources / Path(record["path"]).name, retained)
            verify_identity(record)
        retained = prereg.read_bytes()
        if digest(retained) != request["preregistration_identity"]["sha256"]:
            raise ValueError("Preregistration changed during snapshot")
        write_new(sources / "preregistration.md", retained)
        request["python"] = {"executable": str(Path(sys.executable).resolve()), "version": sys.version}
        request_file = sandbox.path / "request.json"
        save_new(request_file, request)
        argv = [sys.executable, "-B", str(Path(__file__).resolve()), "--worker", str(request_file)]
        save_new(sandbox.path / "launch-request.json", {"argv": argv, "timeout_seconds": TIMEOUT})
        environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        for name, variable in (("reduce", "PROTSTRUCT_REDUCE"), ("probe", "PROTSTRUCT_PROBE"),
                               ("dictionary", "PROTSTRUCT_REDUCE_HET_DICT")):
            environment[variable] = request["configured_tools"][name]
        process = sandbox.run_logged(argv, "worker.log", timeout=TIMEOUT, env=environment)
        outcome["process"] = process.to_record()
        result_file = sandbox.path / "worker-result.json"
        result_bytes = result_file.read_bytes() if result_file.exists() else b"{}"
        result = json.loads(result_bytes)
        if process.returncode == 0 and not process.timed_out and result.get("status") == "complete":
            provenance = json.loads((sandbox.path / "input-provenance.json").read_text())
            tools = json.loads((sandbox.path / "tool-identities.json").read_text())
            final_identities = [*request["source_files"], request["preregistration_identity"],
                                *tools.values(), provenance["retained_file"], result["h_model"]]
            if provenance["origin"] == "retained_local":
                final_identities.append(provenance["original_file"])
            for record in final_identities:
                verify_identity(record)
            for relative, sha256 in result["evidence_files"].items():
                checked_bytes(sandbox.child(relative), sha256)
            admit_evidence(request, sandbox.path, result)
            outcome["status"] = "complete"
            outcome["completion_scope"] = "This one-entry evidence attempt only; not cohort/study completion or grading"
        else:
            outcome["error"] = "Worker failed, timed out, or did not retain a complete result"
    except BaseException as error:
        outcome["error"] = f"{type(error).__name__}: {error}"
    outcome["completed_at"] = utc_now()
    outcome["retained_files"] = {relative: digest(sandbox.child(relative).read_bytes())
                                 for relative in sandbox.inventory()}
    if outcome["status"] == "complete":
        try:
            require(outcome["retained_files"]["worker-result.json"] == digest(result_bytes), "worker result changed during admission")
            require(all(outcome["retained_files"].get(relative) == sha256
                        for relative, sha256 in result["evidence_files"].items()), "admitted files changed during inventory")
        except ValueError as error:
            outcome.update(status="failed", error=str(error))
    save_new(sandbox.path / "result.json", outcome)
    print(json.dumps(outcome, indent=2))
    return 0 if outcome["status"] == "complete" else 1


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) == 2 and arguments[0] == "--worker":
        # Announce inside the owned worker, after its version checks and before
        # H building; do not probe unrelated tools or run anything in plan mode.
        return worker(Path(arguments[1]), announce=lambda **kwargs: announce_benchmark_environment(**kwargs))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", choices=COHORTS, required=True)
    parser.add_argument("--entry", required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--source-url")
    parser.add_argument("--retrieved-at")
    parser.add_argument("--unknown-origin-reason")
    parser.add_argument("--preregistration", type=Path)
    parser.add_argument("--execute", action="store_true")
    try:
        request = make_plan(parser.parse_args(arguments))
        if request["mode"] == "plan_only":
            print(json.dumps(request, indent=2))
            return 0
        return execute(request)
    except (OSError, ValueError) as error:
        print(f"Request refused: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
