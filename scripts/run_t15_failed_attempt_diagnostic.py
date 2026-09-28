#!/usr/bin/env python3
"""Launch exactly one registered, retained-input 1BNI failure diagnostic; no fetches."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
from decimal import Decimal
from email.parser import BytesParser
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tomllib

sys.dont_write_bytecode = True  # Planning/importing local helpers must be read-only.

PLAN = "ref/research/t15_failed_attempt_diagnostic_preregistration_2026-09-27.md"
SELF = "scripts/run_t15_failed_attempt_diagnostic.py"
WRAPPER = "scripts/t15_ss_agreement.py"
INPUT = ("data/coscientists/openscientist/"
         "retained_evidence_2026-09-27_canaries02/t15_cache/1bni.pdb")
INPUT_SHA = "e7a0612d97d3b9f52f2ab6efcaa94b8baa410c37e30107992e4e2564b5385796"
INPUT_SIZE = 263574
EVAL_ID = "EVAL_T15_1BNI_DENOMINATOR_DIAGNOSTIC"
SUBJECT = f"retained:1BNI:sha256:{INPUT_SHA}"
TIMEOUT = 900
SOURCES = (PLAN, SELF, WRAPPER, "scripts/toolchain.py", "scripts/entry_sandbox.py",
           "uv.lock", "pyproject.toml", ".python-version")
PACKAGES = ("PyYAML", "pydantic", "numpy", "scipy", "gemmi", "biotite", "DockQ")
DSSP_HEADER = (
    "  #  RESIDUE AA STRUCTURE BP1 BP2  ACC     N-H-->O    O-->H-N    N-H-->O    O-->H-N"
    "    TCO  KAPPA ALPHA  PHI   PSI    X-CA   Y-CA   Z-CA"
)
AMINO_ACIDS = dict(zip(
    "ALA ARG ASN ASP CYS GLN GLU GLY HIS ILE LEU LYS MET PHE PRO SER THR TRP TYR VAL".split(),
    "ARNDCQEGHILKMFPSTWYV", strict=True,
))


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def read_regular(path: Path) -> bytes:
    """Read only a regular file, without following any path-component alias.

    Descriptor-relative traversal closes directory-alias races. O_NONBLOCK and
    fstat reject special files without waiting for FIFO/device producers.
    """
    path = path.absolute()
    if ".." in path.parts:
        raise OSError(f"unsupported traversal in evidence path: {path}")
    directory = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parts[1:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        if not stat.S_ISREG(os.stat(path.name, dir_fd=directory, follow_symlinks=False).st_mode):
            raise OSError(f"non-regular evidence file refused: {path}")
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise OSError(f"non-regular evidence file refused: {path}")
            return handle.read()
    finally:
        os.close(directory)


def identity(path: Path) -> dict:
    raw = read_regular(path)
    return {"sha256": sha(raw), "size_bytes": len(raw)}


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_new(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(raw)


def save_new(path: Path, payload: dict) -> None:
    write_new(path, serialized(payload))


def serialized(payload: dict) -> bytes:
    return (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode()


def contained(repo: Path, path: Path) -> Path:
    """Reject lexical escapes and every symlink component below the repository."""
    relative = path.relative_to(repo)
    if ".." in relative.parts:
        raise ValueError(f"path contains traversal: {path}")
    current = repo
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"path contains symlink: {current}")
    resolved = path.resolve()
    resolved.relative_to(repo)
    return resolved


def git_bytes(repo: Path, *arguments: str) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *arguments],
                          capture_output=True, check=True).stdout


def registration(repo: Path, commit: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("registration commit must be a complete lowercase Git object id")
    if commit == "4a150693dd64b79c38e9e57561667215994a35a1":
        raise ValueError("the old cohort registration does not register this diagnostic")
    if git_bytes(repo, "rev-parse", "HEAD").decode().strip() != commit:
        raise ValueError("HEAD differs from the reviewed diagnostic registration commit")
    snapshots = {}
    for name in SOURCES:
        path = contained(repo, repo / name)
        raw = read_regular(path)
        if raw != git_bytes(repo, "show", f"{commit}:{name}"):
            raise ValueError(f"source differs from registered bytes: {name}")
        snapshots[name] = raw
    if read_regular(Path(__file__)) != snapshots[SELF]:
        raise ValueError("executing helper differs from registered helper")
    original = read_regular(contained(repo, repo / INPUT))
    if len(original) != INPUT_SIZE or sha(original) != INPUT_SHA:
        raise ValueError("retained 1BNI bytes differ from preregistration")
    if original != git_bytes(repo, "show", f"{commit}:{INPUT}"):
        raise ValueError("1BNI input was not delivered in the registration commit")
    return {"sources": snapshots, "input": original}


def python_environment(repo: Path, *, metadata_pins: dict | None = None) -> dict:
    if sys.version_info[:2] != (3, 12):
        raise ValueError("the locked Python 3.12 benchmark environment is required")
    if Path(sys.prefix).resolve() != (repo / ".venv").resolve():
        raise ValueError("use this repository's locked .venv/bin/python")
    normalize = lambda text: re.sub(r"[-_.]+", "-", text).lower()
    locked = {}
    package_table = tomllib.loads(read_regular(repo / "uv.lock").decode("utf-8")).get("package")
    if not isinstance(package_table, list) or not package_table:
        raise ValueError("uv.lock requires a nonempty package array")
    for package in package_table:
        if (not isinstance(package, dict)
                or any(not isinstance(package.get(field), str) or not package[field]
                       for field in ("name", "version"))):
            raise ValueError("uv.lock package rows require string name/version fields")
        locked.setdefault(normalize(package["name"]), set()).add(package["version"])
    packages, metadata = {}, {}
    if metadata_pins is not None and set(metadata_pins) != set(PACKAGES):
        raise ValueError("post-run package metadata pins are incomplete")
    for name in PACKAGES:
        if metadata_pins is None:
            distribution = importlib.metadata.distribution(name)
            if not isinstance(distribution, importlib.metadata.PathDistribution):
                raise ValueError(f"unsupported package metadata provider: {name}")
            # Python 3.12's PathDistribution identifies one installed dist-info
            # directory. Do not call version()/read_text(), which follow aliases.
            path = Path(distribution._path) / "METADATA"
            path = path.absolute()
            if not path.is_relative_to(Path(sys.prefix).resolve()):
                raise ValueError(f"package metadata is outside the locked environment: {name}")
        else:
            path = Path(metadata_pins[name]["path"])
        raw = read_regular(path)
        pin = {"path": str(path), **identity_bytes(raw)}
        if metadata_pins is not None and pin != metadata_pins[name]:
            raise ValueError(f"changed package metadata: {name}")
        fields = BytesParser().parsebytes(raw, headersonly=True)
        names, versions = fields.get_all("Name", []), fields.get_all("Version", [])
        if len(names) != 1 or len(versions) != 1 or normalize(names[0]) != normalize(name):
            raise ValueError(f"ambiguous package Name/Version metadata: {name}")
        packages[name], metadata[name] = versions[0], pin
    for name, version in packages.items():
        if version not in locked.get(normalize(name), set()):
            raise ValueError(f"installed {name}={version} differs from uv.lock")
    if packages["biotite"] != "1.7.1" or packages["gemmi"] != "0.7.5":
        raise ValueError("this diagnostic pins Biotite 1.7.1 and Gemmi Python 0.7.5")
    return {"version": sys.version, "executable": sys.executable,
            "prefix": sys.prefix, "packages": packages,
            "package_metadata": metadata,
            "executable_identity": identity(Path(sys.executable).resolve())}


def load_module(repo: Path, name: str):
    spec = importlib.util.spec_from_file_location(
        f"_t15_diagnostic_{name}", repo / "scripts" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def executable_identities(repo: Path) -> dict:
    # Resolve only these two executables; do not probe unrelated licensed tools.
    toolchain = load_module(repo, "toolchain")
    return {
        name: {"path": str(path), **identity(path)}
        for name, path in (
            ("gemmi", toolchain.gemmi_executable()),
            ("dssp", toolchain.dssp_executable()),
        )
    }


def snapshot_pins(request: dict) -> dict:
    return {**{f"source_snapshot/{name}": pin
               for name, pin in request["source_identities"].items()},
            "input_snapshot/1bni.pdb": request["input_identity"]}


def snapshot_inventory_drift(files: dict, request: dict) -> list[str]:
    return [f"final inventory snapshot differs or is missing: {name}"
            for name, pin in snapshot_pins(request).items() if files.get(name) != pin]


def identity_drift(repo: Path, request: dict) -> list[str]:
    problems = []
    expected = {**request["source_identities"], INPUT: request["input_identity"]}
    for name, pin in expected.items():
        try:
            if identity(contained(repo, repo / name)) != pin:
                problems.append(f"changed bytes: {name}")
        except (OSError, ValueError) as error:
            problems.append(f"unavailable identity {name}: {error}")
    for name, pin in snapshot_pins(request).items():
        try:
            path = contained(repo, repo / request["root"] / name)
            if identity(path) != pin:
                problems.append(f"changed retained snapshot: {name}")
        except (OSError, ValueError) as error:
            problems.append(f"unavailable retained snapshot {name}: {error}")
    for name, pin in request["executables"].items():
        try:
            if identity(Path(pin["path"])) != {k: pin[k] for k in ("sha256", "size_bytes")}:
                problems.append(f"changed executable: {name}")
        except OSError as error:
            problems.append(f"unavailable executable {name}: {error}")
    try:
        if identity(Path(request["python"]["executable"]).resolve()) != request[
            "python"]["executable_identity"]:
            problems.append("changed Python executable")
    except OSError as error:
        problems.append(f"unavailable Python executable: {error}")
    return problems


def worker(request_path: Path, expected_sha: str) -> int:
    """Exec the wrapper in the owned group, redirecting streams without a shell."""
    raw = read_regular(request_path)
    if sha(raw) != expected_sha:
        raise ValueError("launch request changed before worker start")
    request = json.loads(raw)
    repo = Path(request["repo"])
    drift = identity_drift(repo, request)
    if drift:
        raise ValueError("; ".join(drift))
    entry = contained(repo, Path(request["entry_absolute"]))
    save_new(entry / "worker-context.json",
             {"recorded_at": utc(), "pid": os.getpid(), "pgid": os.getpgrp(),
              "wrapper_argv": request["wrapper_argv"], "request_sha256": expected_sha})
    with (entry / "wrapper.stdout").open("xb") as stdout, (
        entry / "wrapper.stderr"
    ).open("xb") as stderr:
        os.dup2(stdout.fileno(), 1)
        os.dup2(stderr.fileno(), 2)
    os.execvpe(request["wrapper_argv"][0], request["wrapper_argv"], dict(os.environ))
    raise AssertionError("exec returned")


def stream(rows: list) -> dict:
    result = {}
    for row in rows:
        if set(row) != {"chain", "resnum", "icode", "state"}:
            raise ValueError("assignment shape differs")
        key = tuple(row[name] for name in ("chain", "resnum", "icode"))
        if not all(isinstance(value, str) for value in key) or key in result:
            raise ValueError("invalid or duplicate assignment key")
        if row["state"] not in ("H", "E", "C"):
            raise ValueError("assignment is not a collapsed H/E/C state")
        result[key] = row["state"]
    return result


def retained(block: dict) -> bytes:
    raw = base64.b64decode(block["bytes_base64"], validate=True)
    if block["encoding"] != "base64" or identity_bytes(raw) != {
        key: block[key] for key in ("sha256", "size_bytes")
    }:
        raise ValueError("retained byte hash/size differs")
    return raw


def identity_bytes(raw: bytes) -> dict:
    return {"sha256": sha(raw), "size_bytes": len(raw)}


def observed_identity(path: Path) -> dict:
    try:
        return identity(path)
    except OSError as error:
        return {"error": f"{type(error).__name__}: {error}"}


def coordinate_inventory(raw: bytes) -> tuple[dict, set]:
    """Independent fixed-column inventory for this frozen single-model PDB.

    Atom identity and all coordinate/occupancy/B/element values must survive
    normalization. Serial numbers and documentary PDB records are not atom
    identity. ATOM protein residue keys define the registered coverage domain.
    This checks identity, not chemical completeness or missing-atom causality.
    """
    atoms, residues = {}, set()
    lines = raw.decode("ascii").splitlines()
    models = [n for n, line in enumerate(lines) if line[:6] == "MODEL "]
    ends = [n for n, line in enumerate(lines) if line[:6] == "ENDMDL"]
    if len(models) > 1 or len(models) != len(ends) or (models and models[0] >= ends[0]):
        raise ValueError("unsupported coordinate model boundaries")
    for n, line in enumerate(lines):
        record = line[:6]
        if record not in ("ATOM  ", "HETATM"):
            continue
        if len(line) < 78 or (models and not models[0] < n < ends[0]):
            raise ValueError(f"malformed/out-of-model coordinate at line {n + 1}")
        number = line[22:26].strip()
        if not re.fullmatch(r"-?\d+", number) or not line[21].strip():
            raise ValueError(f"unsupported coordinate residue identity at line {n + 1}")
        residue = (line[21], str(int(number)), line[26].strip())
        key = (record, *residue, line[17:20], line[16], line[12:16])
        values = tuple(float(line[a:b]) for a, b in
                       ((30, 38), (38, 46), (46, 54), (54, 60), (60, 66)))
        if (key in atoms or not line[12:16].strip() or not line[17:20].strip()
                or not line[76:78].strip() or not all(map(math.isfinite, values))):
            raise ValueError(f"ambiguous or nonfinite coordinate at line {n + 1}")
        atoms[key] = (*values, line[76:78].strip())
        if record == "ATOM  ":
            residues.add(residue)
    if not atoms or not residues:
        raise ValueError("coordinate evidence contains no protein atoms")
    return atoms, residues


def raw_dssp_assignments(raw: bytes) -> dict:
    """Independent admission of the pinned DSSP 4.6.1 fixed-column format.

    Grammar follows the tagged dssp-io.cpp formatter; no production parser is
    imported. Full records, header total and identities precede state collapse.
    Unsupported format changes fail closed; this is not a new state definition.
    """
    lines = raw.decode("utf-8").splitlines()
    headers = [i for i, line in enumerate(lines) if line == DSSP_HEADER]
    if len(headers) != 1:
        raise ValueError("raw DSSP needs exactly one residue table")
    totals = [line for line in lines[:headers[0]] if "TOTAL NUMBER OF RESIDUES," in line]
    if len(totals) != 1 or not re.fullmatch(
        r" *[0-9]+(?: +[0-9]+){4} TOTAL NUMBER OF RESIDUES, NUMBER OF CHAINS, "
        r"NUMBER OF SS-BRIDGES\(TOTAL,INTRACHAIN,INTERCHAIN\) +\.", totals[0]
    ):
        raise ValueError("raw DSSP needs the declared residue total")
    declared = int(totals[0][:5])
    result, serials = {}, set()
    for number, line in enumerate(lines[headers[0] + 1:], headers[0] + 2):
        def invalid(reason):
            raise ValueError(f"raw DSSP line {number}: {reason}")

        if len(line) != 136 or any(not 32 <= ord(c) <= 126 for c in line):
            invalid("incomplete/unsupported fixed-column record")
        if not re.fullmatch(r" *[1-9][0-9]*", line[:5]):
            invalid("invalid serial")
        serial = int(line[:5])
        if line[:5] != f"{serial:5d}" or serial in serials:
            invalid("noncanonical/duplicate serial")
        serials.add(serial)
        if line[13] == "!":
            # The formatter's break record has no residue identity/state and
            # only fixed zero/default-valued numeric fields.
            expected_tail = ("             0   0    0" + "      0, 0.0" + "     0, 0.0" * 3
                             + "   0.000" + " 360.0" * 4 + "    0.0" * 3)
            if line[5:13] != " " * 8 or line[14] not in " *" or line[15:] != expected_tail:
                invalid("malformed chain/gap break")
            continue
        if (line[12] != " " or line[14:16] != "  " or line[38] != " "
                or line[83:85] != "  " or any(line[i] != " " for i in (115, 122, 129))):
            invalid("invalid field separators")
        if not re.fullmatch(r" *-?[0-9]+", line[5:10]):
            invalid("invalid residue number")
        resnum = int(line[5:10])
        if line[5:10] != f"{resnum:5d}" or not line[11].strip():
            invalid("noncanonical residue number or unsupported blank chain")
        if not re.fullmatch(r"[A-Za-z]", line[13]) or line[16] not in "HBEGIPTS ":
            invalid("unsupported amino-acid/state code")
        for index, alphabet in ((17, " <>XP"), (18, " <>X3"), (19, " <>X4"),
                                (20, " <>X5"), (21, " S"), (22, " +-")):
            if line[index] not in alphabet:
                invalid("invalid structure flag")
        if not re.fullmatch(r"[ A-Za-z]{2}", line[23:25]) or not re.fullmatch(r"[ A-Z]", line[33]):
            invalid("invalid bridge/sheet label")
        for start in (25, 29, 34):
            field = line[start:start + 4]
            if not re.fullmatch(r" *[0-9]+", field) or field != f"{int(field):4d}":
                invalid("invalid bridge/accessibility integer")
        for start in (39, 50, 61, 72):
            if not re.fullmatch(r" *-?[0-9]+, *-?[0-9]+\.[0-9]", line[start:start + 11]):
                invalid("invalid hydrogen-bond field")
        for start in (85, 91, 97, 103, 109, 116, 123, 130):
            precision = 3 if start == 85 else 1
            if not re.fullmatch(r" *-?[0-9]+\.[0-9]{" + str(precision) + "}", line[start:start + 6]):
                invalid("invalid numeric record tail")
        key = (line[11], str(resnum), line[10].strip())
        if key in result:
            invalid("duplicate residue identity")
        result[key] = "H" if line[16] in "HGI" else "E" if line[16] in "EB" else "C"
    if len(result) != declared:
        raise ValueError("raw DSSP record count differs from its declared total")
    return result


def bind_raw_dssp_to_atoms(raw: bytes, atoms: dict) -> None:
    """Bind raw AA/CA fields to one source CA conformer at print precision.

    DSSP prints CA coordinates to one decimal place. An inclusive half-step
    interval handles either rounding direction at exact ties without importing
    a new quality tolerance. Lowercase DSSP disulfide labels identify cysteine.
    Unknown amino-acid mapping is unsupported, not inferred from a key alone.
    """
    raw_dssp_assignments(raw)  # Admit the full format before reading its columns.
    candidates = {}
    for key, values in atoms.items():
        record, chain, number, icode, name, _alt, atom = key
        if record != "ATOM  " or atom.strip() != "CA":
            continue
        aa = AMINO_ACIDS.get(name)
        if aa is None or values[-1] != "C":
            raise ValueError(f"unsupported source CA identity: {key}")
        candidates.setdefault((chain, number, icode), []).append((aa, values[:3]))
    lines = raw.decode("utf-8").splitlines()
    half_step = Decimal("0.1") / 2
    for line in lines[lines.index(DSSP_HEADER) + 1:]:
        if line[13] == "!":
            continue
        key = (line[11], str(int(line[5:10])), line[10].strip())
        aa = "C" if line[13].islower() else line[13]
        xyz = tuple(Decimal(line[start:start + 6].strip()) for start in (116, 123, 130))
        if not any(aa == source_aa and all(abs(value - Decimal(str(source))) <= half_step
                                         for value, source in zip(xyz, source_xyz, strict=True))
                   for source_aa, source_xyz in candidates.get(key, [])):
            raise ValueError(f"raw DSSP residue/CA coordinates disagree with normalized source: {key}")


def audit_failed_bundle(payload: dict, request: dict, source: bytes) -> dict:
    if (payload["evidence_format"] != "protstruct-review-t15-failed-attempt-v1"
            or payload["attempt_status"] != "failed_denominator_admission"
            or payload["measurements_emitted"] is not False
            or payload["catalog_task_ref"] != "T15"
            or payload["eval_id"] != EVAL_ID or payload["subject_ref"] != SUBJECT):
        raise ValueError("bundle is not the registered typed failed attempt")
    forbidden = {"aggregate", "fraction", "dssp_ss_content", "pass_status",
                 "pass_criterion", "pass_criterion_ref", "oracle_measure",
                 "agent_claim", "metric_definition_refs", "bundle_ref"}

    def reject_measurements(value):
        if isinstance(value, dict):
            if forbidden.intersection(value):
                raise ValueError("failed bundle contains scalar/grading metadata")
            for item in value.values():
                reject_measurements(item)
        elif isinstance(value, list):
            for item in value:
                reject_measurements(item)

    reject_measurements(payload)
    if retained(payload["source"]) != source:
        raise ValueError("failed bundle names different source bytes")
    normalized = retained(payload["normalization"])
    raw = retained(payload["dssp"]["raw_output"])
    if not normalized or not raw:
        raise ValueError("empty normalized/raw evidence")
    source_atoms, expected_keys = coordinate_inventory(source)
    normalized_atoms, normalized_keys = coordinate_inventory(normalized)
    if normalized_atoms != source_atoms or normalized_keys != expected_keys:
        raise ValueError("normalized coordinates differ from the frozen source model")
    a = stream(payload["dssp"]["assignments"])
    b = stream(payload["biotite_psea"]["assignments"])
    if not set(a).issubset(expected_keys) or not set(b).issubset(expected_keys):
        raise ValueError("assignment keys are unrelated to the source protein domain")
    parsed = raw_dssp_assignments(raw)
    if parsed != a:
        raise ValueError("raw DSSP stream differs from retained assignments")
    bind_raw_dssp_to_atoms(raw, normalized_atoms)
    shared, only_a, only_b = set(a) & set(b), set(a) - set(b), set(b) - set(a)
    if not only_a and not only_b and shared:
        raise ValueError("failed bundle actually has an admissible denominator")
    failure = payload["failure"]
    reason = "unequal_residue_keys" if shared else "no_shared_residue_keys"
    if failure["stage"] != "residue_key_admission" or failure["reason_code"] != reason:
        raise ValueError("failure type disagrees with streams")
    expected_counts = {"n_dssp": len(a), "n_biotite": len(b), "n_shared": len(shared),
                       "n_dssp_only": len(only_a), "n_biotite_only": len(only_b)}
    if (failure["counts"] != expected_counts
            or any(type(value) is not int for value in failure["counts"].values())):
        raise ValueError("failure counts disagree with complete streams")
    for label, keys in (("shared", shared), ("dssp_only", only_a), ("biotite_only", only_b)):
        expected = [{"chain": c, "resnum": r, "icode": i} for c, r, i in sorted(keys)]
        if failure[f"{label}_keys"] != expected:
            raise ValueError(f"{label} keys differ, including insertion codes")
    actual_versions = {name: payload[name]["tool_version"]
                       for name in ("normalization", "dssp", "biotite_psea")}
    if (not re.fullmatch(r"gemmi (?:version )?0\.7\.5", actual_versions["normalization"])
            or actual_versions["dssp"] != "mkdssp version 4.6.1"
            or actual_versions["biotite_psea"] != "1.7.1"):
        raise ValueError(f"version mismatch; not an instrument-only replay: {actual_versions}")
    normalization = payload["normalization"]["execution"]
    dssp = payload["dssp"]["execution"]
    for block in (normalization, dssp):
        if block["returncode"] != 0 or not all(
            isinstance(block[name], str) for name in ("stdout", "stderr")
        ):
            raise ValueError("completed subprocess provenance is inconsistent")
    ga, da = normalization["argv"], dssp["argv"]
    if (len(ga) != 4 or ga[:3] != [request["executables"]["gemmi"]["path"], "convert",
                                  str(Path(request["repo"]) / INPUT)]
            or len(da) != 5 or da[:3] != [
                request["executables"]["dssp"]["path"], "--output-format", "dssp"
            ] or da[3] != ga[3]):
        raise ValueError("captured scientific argv does not match the registered invocation")
    if payload["biotite_psea"]["execution"] != {
        "mode": "in_process", "status": "returned_assignments"
    }:
        raise ValueError("unexpected P-SEA execution provenance")
    predicted_missing = {("C", "3", "")}
    complete_prediction = (reason == "unequal_residue_keys" and bool(shared)
                           and set(b) == expected_keys
                           and set(a) == expected_keys - predicted_missing
                           and predicted_missing.issubset(expected_keys))
    return {"counts": expected_counts, "actual_versions": actual_versions,
            "prediction_matches": complete_prediction,
            "source_protein_residue_count": len(expected_keys),
            "source_coordinate_atom_count": len(source_atoms),
            "dssp_unassigned_source_keys": [list(k) for k in sorted(expected_keys - set(a))],
            "biotite_unassigned_source_keys": [list(k) for k in sorted(expected_keys - set(b))],
            "biotite_only_keys": failure["biotite_only_keys"],
            "scope": "raw DSSP and retained streams recounted; no new P-SEA execution",
            "not_a_quality_grade": True}


def inventory(root: Path) -> dict:
    """Collect available identities without following corrupt aliases.

    Errors are explicit entries, never substitute hashes or a complete manifest.
    A readable sibling still survives an unreadable/symlinked evidence object.
    """
    files = {}

    def walk(directory):
        try:
            children = sorted(directory.iterdir())
        except OSError as exc:
            files[directory.relative_to(root).as_posix()] = {"error": f"inventory directory: {exc}"}
            return
        for path in children:
            relative = path.relative_to(root).as_posix()
            try:
                mode = path.lstat().st_mode
                if stat.S_ISLNK(mode):
                    files[relative] = {"error": "unexpected evidence symlink; not followed"}
                elif stat.S_ISDIR(mode):
                    walk(path)
                elif stat.S_ISREG(mode):
                    files[relative] = identity(path)
                else:
                    files[relative] = {"error": "unexpected non-file evidence object"}
            except (OSError, ValueError) as exc:
                files[relative] = {"error": f"{type(exc).__name__}: {exc}"}

    walk(root)
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--registration-commit")
    parser.add_argument("--run-id")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--request-sha256", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker is not None:
        return worker(args.worker, args.request_sha256)
    if args.repo is None or args.registration_commit is None or args.run_id is None:
        parser.error("--repo, --registration-commit and --run-id are required")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", args.run_id):
        parser.error("--run-id must be a short lowercase safe suffix")
    repo = args.repo.resolve(strict=True)
    registered = registration(repo, args.registration_commit)
    root = contained(repo, repo / "data/coscientists/openscientist" /
                     f"retained_evidence_2026-09-27_t15-diagnostic-{args.run_id}")
    if root.exists():
        raise FileExistsError(f"diagnostic root already exists; no reuse/retry: {root}")
    python = python_environment(repo)
    executables = executable_identities(repo)
    entry = root / "entries" / "T15_1BNI"
    wrapper_argv = [sys.executable, "-B", str(repo / WRAPPER), str(repo / INPUT),
                    "--eval-id", EVAL_ID, "--subject-ref", SUBJECT,
                    "--evidence-out", str(entry / "failed-attempt.json")]
    request = {
        "format": "t15-1bni-diagnostic-launch-v1", "repo": str(repo),
        "registration_commit": args.registration_commit,
        "root": root.relative_to(repo).as_posix(), "entry_absolute": str(entry),
        "wrapper_argv": wrapper_argv, "timeout_seconds": TIMEOUT,
        "source_identities": {name: identity_bytes(raw)
                              for name, raw in registered["sources"].items()},
        "input_ref": INPUT, "input_identity": identity_bytes(registered["input"]),
        "python": python, "executables": executables,
        "policy": "one entry only; no fetch, retry, cohort continuation or quality grading",
    }
    print(json.dumps({**request, "mode": "execute" if args.execute else "plan_only"},
                     indent=2), flush=True)
    if not args.execute:
        return 0
    # Existing ancestors must also be non-symlinks. mkdir is the atomic reservation.
    contained(repo, root)
    root.mkdir(exist_ok=False)
    for name, raw in registered["sources"].items():
        write_new(root / "source_snapshot" / name, raw)
    write_new(root / "input_snapshot" / "1bni.pdb", registered["input"])
    sandbox_type = load_module(repo, "entry_sandbox").EntrySandbox
    sandbox = sandbox_type(root / "entries", "T15_1BNI")
    temporary = entry / "tmp"
    temporary.mkdir()
    environment = dict(os.environ)
    environment.update({"PYTHONDONTWRITEBYTECODE": "1", "TMPDIR": str(temporary),
                        "TMP": str(temporary), "TEMP": str(temporary),
                        "MPLCONFIGDIR": str(temporary / "matplotlib"),
                        "XDG_CACHE_HOME": str(temporary / "xdg"),
                        "PROTSTRUCT_GEMMI": executables["gemmi"]["path"],
                        "PROTSTRUCT_DSSP": executables["dssp"]["path"]})
    request["started_at"] = utc()
    request_path = entry / "launch-request.json"
    request_bytes = serialized(request)
    request_sha = sha(request_bytes)
    write_new(request_path, request_bytes)
    launch_argv = [sys.executable, "-B", str(repo / SELF), "--worker", str(request_path),
                   "--request-sha256", request_sha]
    owned_launch_bytes = serialized({"argv": launch_argv, "timeout_seconds": TIMEOUT})
    write_new(entry / "owned-launch.json", owned_launch_bytes)
    interrupted_pgids = []

    def interrupted(signum, _frame):
        interrupted_pgids.extend(sandbox_type.active_pgids())
        raise KeyboardInterrupt(f"signal {signum}; terminating only the owned process group")

    handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    result, error, exception_record = None, None, None
    for sig in handlers:
        signal.signal(sig, interrupted)
    try:
        drift = identity_drift(repo, request)
        if drift:
            raise ValueError("; ".join(drift))
        if read_regular(request_path) != request_bytes:
            raise ValueError("request changed before launch")
        result = sandbox.run_logged(launch_argv, "launcher.log", timeout=TIMEOUT, env=environment)
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}"
        exception_record = {
            "type": type(exc).__name__, "message": str(exc),
            "cleanup_record": getattr(exc, "cleanup_record", None),
            "notes": list(getattr(exc, "__notes__", [])),
        }
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
    drift = identity_drift(repo, request)
    after = {name: observed_identity(repo / name) for name in SOURCES}
    input_after = observed_identity(repo / INPUT)
    executable_after = {name: observed_identity(Path(pin["path"]))
                        for name, pin in executables.items()}
    try:
        python_after = python_environment(repo, metadata_pins=python["package_metadata"])
        if python_after != python:
            drift.append("changed Python environment/package versions")
    except (OSError, ValueError, importlib.metadata.PackageNotFoundError) as exc:
        python_after = {"error": f"{type(exc).__name__}: {exc}"}
        drift.append("Python environment no longer verifies against the lock")
    audit, audit_error = None, None
    admission_pins = {}

    def admission_bytes(path: Path) -> bytes:
        raw = read_regular(path)
        admission_pins[path.relative_to(root).as_posix()] = identity_bytes(raw)
        return raw

    try:
        if error or result is None or result.timed_out or result.returncode != 1:
            raise ValueError("expected untimed-out wrapper exit 1 was not observed")
        cleanup = getattr(result, "cleanup", None)
        if (not isinstance(cleanup, dict) or cleanup.get("group_absent_verified") is not True
                or cleanup.get("status") != "group_absent"
                or type(cleanup.get("pgid")) is not int or cleanup["pgid"] != result.pgid):
            raise ValueError("owned process group absence was not verified for this launch")
        if drift:
            raise ValueError("; ".join(drift))
        worker_record = json.loads(admission_bytes(entry / "worker-context.json"))
        if (admission_bytes(request_path) != request_bytes
                or admission_bytes(entry / "owned-launch.json") != owned_launch_bytes
                or result.arguments != launch_argv):
            raise ValueError("request/owned launch differs from the original parent pin")
        if (worker_record["pid"] != result.pid or worker_record["pgid"] != result.pgid
                or result.pid != result.pgid or not result.start_new_session
                or worker_record["wrapper_argv"] != wrapper_argv
                or worker_record["request_sha256"] != request_sha):
            raise ValueError("recorded wrapper identity differs from owned PID/PGID/request")
        if admission_bytes(entry / "wrapper.stdout") != b"":
            raise ValueError("rejected attempt emitted nonempty stdout")
        stderr = admission_bytes(entry / "wrapper.stderr").decode("utf-8")
        if "failed-attempt evidence retained:" not in stderr:
            raise ValueError("wrapper did not report retained failed-attempt evidence")
        audit = audit_failed_bundle(
            json.loads(admission_bytes(entry / "failed-attempt.json")),
            request, registered["input"]
        )
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
        audit_error = f"{type(exc).__name__}: {exc}"
    # The final inventory is also an admission input: hashing a corrupted copy
    # must not authenticate it as the registered instrument/input (#848).
    files = inventory(root)
    inventory_errors = {name: item["error"] for name, item in files.items() if "error" in item}
    inventory_drift = snapshot_inventory_drift(files, request)
    inventory_drift.extend(f"incomplete inventory {name}: {error}"
                           for name, error in inventory_errors.items())
    inventory_drift.extend(
        f"admission evidence changed or missing at final inventory: {name}"
        for name, pin in admission_pins.items() if files.get(name) != pin
    )
    if inventory_drift:
        drift.extend(inventory_drift)
        audit = None
        audit_error = "; ".join(inventory_drift)
    outcome = {
        "completed_at": utc(), "process": result.to_record() if result is not None else None,
        "launcher_error": error, "launcher_exception": exception_record,
        "interrupted_pgids": sorted(set(interrupted_pgids)),
        "identity_drift": drift, "audit": audit, "audit_error": audit_error,
        "source_identities_after": after, "input_identity_after": input_after,
        "executable_identities_after": executable_after, "python_after": python_after,
        "snapshot_identities_after": {name: files.get(name) for name in snapshot_pins(request)},
        "admission_file_identities": admission_pins,
        "launched_request_sha256": request_sha,
        "inventory_complete": not inventory_errors, "inventory_errors": inventory_errors,
        "diagnostic_retention_valid": audit is not None,
        "decision": "STOP; no automatic retry or cohort continuation",
    }
    result_path = entry / "launch-result.json"
    save_new(result_path, outcome)
    # Execution has stopped. The result is the sole file added after inventory;
    # hash its written bytes before publishing the otherwise unchanged inventory.
    files[result_path.relative_to(root).as_posix()] = identity(result_path)
    save_new(root / "final-file-manifest.json",
             {"format": "file-sha256-size-with-errors-v1", "files": files,
              "file_count": sum("sha256" in value for value in files.values()),
              "inventory_entry_count": len(files),
              "inventory_complete": not inventory_errors, "inventory_errors": inventory_errors,
              "inventory_excludes": ["final-file-manifest.json"],
              "reason": "a digest manifest cannot contain its own digest"})
    print(json.dumps({"result": outcome, "root": str(root)}, indent=2), flush=True)
    return 0 if audit is not None and audit["prediction_matches"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
