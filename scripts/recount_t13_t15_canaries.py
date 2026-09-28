#!/usr/bin/env python3
"""Read-only replay of the two retained PR831 attempt roots, never a tool rerun.

Historical source bytes come from a digest-checked retained snapshot, falling
back to git show at the preregistered commit. Today's HEAD is not the instrument.
Successful entries are informational; stopped/missing cohort members stay visible.
Exit 0 validates the retained record (including its failures), not the science;
exit 2 means the retained record cannot be replayed consistently.
"""
from __future__ import annotations

import argparse
import ast
import base64
from collections import Counter
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import struct
import subprocess
import sys
from unittest import mock

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
COMMIT = "4a150693dd64b79c38e9e57561667215994a35a1"
BASE = "data/coscientists/openscientist"
SNAPSHOT = BASE + "/retained_canary_sources_2026-09-27"
INPUT = BASE + "/retained_evidence_2026-09-23/data/1sar.mtz"
INPUT_SHA = "f36d5fe685a3e524e8809d17d19ce12073acdf339eba2cfd3b0347a818850ab2"
COHORT = ("1UBQ", "1LYZ", "1LZ1", "2PTN", "7RSA", "1CA2", "1MBN", "3EST",
          "1BNI", "2CI2", "9PAP", "1HEW", "4PTI", "1CRN", "2LYZ", "1TIM")
PREFIXES = {"canaries01": 6, "canaries02": 9}
SOURCE_PINS = {
    "ref/research/t13_t15_canaries_preregistration_2026-09-27.md": "97d46d0fcfe9f17527dc3a60b4667929cec3c2646c27427824f16a5c44c38714",
    "uv.lock": "c80b8cd4c874a7cf46cd6d5712df4d0a5fd2e1ac755d5ab1efb07d94448fa8b9",
    "scripts/entry_sandbox.py": "d90356b60b62c4ebb1dcfc1aae904f42e5af09ad947e5eefdf5dac8f150771f8",
    "scripts/toolchain.py": "e32dd23ba61d684edea4cf86208c6d7fec62af060898c63cba96f40bd0bc338f",
    "scripts/benchmark_environment.py": "3b8e2ed8808139f3e6b3e07f1ec194eea87984564e4401b598f26ae7a92d1377",
    "scripts/t13_data_quality.py": "9cf55c75fe51a9711f7df97138ba2404e2144dcc7c7b1c4c6c9419b78191355a",
    "scripts/t15_ss_agreement.py": "42a84d759284752bcc2c8340148a1306c39cb5ca3a1da6eb85180496124a9f4f",
    "scripts/bench_t15_ss_agreement.py": "cb0ad3aac45f0dbc7498f603e014a57eb303bd4b79ad0b274eb953b32784637a",
}
VERSIONS = {"normalization": "gemmi 0.7.5", "dssp": "mkdssp version 4.6.1",
            "biotite_psea": "1.7.1"}
METRICS = ("T15_secondary_structure_agreement", "T15_secondary_structure_content")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate mapping key: {key}")
        result[key] = value
    return result


class UniqueYaml(yaml.SafeLoader):
    pass


def yaml_mapping(loader, node):
    return unique_pairs((loader.construct_object(k), loader.construct_object(v))
                        for k, v in node.value)


UniqueYaml.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, yaml_mapping)


def load_json(path):
    def invalid(value):
        raise ValueError(f"nonfinite JSON token: {value}")
    return json.loads(path.read_text(), object_pairs_hook=unique_pairs, parse_constant=invalid)


def safe_path(root, reference):
    require(isinstance(reference, str) and reference, "empty/non-string path")
    rel = PurePosixPath(reference)
    require(not rel.is_absolute() and ".." not in rel.parts
            and rel.as_posix() == reference and "\\" not in reference, f"unsafe path: {reference}")
    candidate = root
    for part in rel.parts:
        candidate = candidate / part
        require(not candidate.is_symlink(), f"symlink evidence path: {candidate}")
    candidate.resolve().relative_to(root.resolve())
    return candidate


def inventory(root):
    paths = list(root.rglob("*"))  # Includes gitignored files; never follows symlinks.
    require(not any(p.is_symlink() for p in paths), f"symlink in retained tree: {root}")
    return {p.relative_to(root).as_posix(): {"sha256": sha(p.read_bytes()), "size": p.stat().st_size}
            for p in paths if p.is_file()}


def historical_sources(repo):
    snapshot = safe_path(repo, SNAPSHOT)
    source = {}
    for name, digest in SOURCE_PINS.items():
        if snapshot.exists():
            raw = safe_path(snapshot, name).read_bytes()
        else:
            result = subprocess.run(["git", "-C", str(repo), "show", f"{COMMIT}:{name}"],
                                    check=True, capture_output=True)
            raw = result.stdout
        require(sha(raw) == digest, f"historical source digest mismatch: {name}")
        source[name] = raw
    return source, "retained_snapshot" if snapshot.exists() else "preregistered_git_commit"


def informational(row):
    require(row.get("pass_status") == "informational", "non-informational measurement")
    require(not any(k in row for k in ("pass_criterion", "pass_criterion_ref",
                                      "criterion_preconditions")), "criterion metadata present")


def decode_bytes(part, data, digest, size):
    raw = base64.b64decode(part[data], validate=True)
    require(raw and type(part[size]) is int and len(raw) == part[size]
            and sha(raw) == part[digest], "retained payload size/hash mismatch")
    return raw


def raw_dssp_assignments(raw):
    lines = raw.decode("utf-8").splitlines()
    require(lines and "version 4.6.1" in lines[0], "raw DSSP version mismatch")
    headers = [i for i, line in enumerate(lines) if line.startswith("  #  RESIDUE")]
    require(len(headers) == 1, "missing/ambiguous raw DSSP table")
    result = {}
    for line in lines[headers[0] + 1:]:
        if not line.strip():
            continue
        require(len(line) >= 17, "truncated raw DSSP row")
        if line[13] == "!":
            continue
        key = (line[11].strip(), str(int(line[5:10])), line[10].strip())
        require(key[0] and key not in result, "empty/duplicate raw DSSP key")
        state = line[16]
        require(state in " HGIEBTSPC", "unknown raw DSSP state")
        result[key] = "H" if state in "HGI" else "E" if state in "EB" else "C"
    require(result, "empty raw DSSP assignments")
    return result


def recount_t15(repo, root, entry, pdb):
    path = root / "t15_evidence" / f"{pdb.lower()}.t15-evidence.json"
    evidence = load_json(path)
    require(evidence["evidence_format"] == "protstruct-review-t15-v1", "wrong T15 format")
    require(evidence["subject_ref"] is None, "benchmark invocation had no subject override")
    require(evidence["metric_definition_refs"] == list(METRICS), "wrong bundle metrics")
    require(sha((root / "t15_cache" / f"{pdb.lower()}.pdb").read_bytes())
            == evidence["source_sha256"], "T15 source digest mismatch")
    for section, version in VERSIONS.items():
        require(evidence[section]["tool_version"] == version, f"version mismatch: {section}")
    decode_bytes(evidence["normalization"], "bytes_base64", "sha256", "size_bytes")
    raw = decode_bytes(evidence["dssp"], "raw_output_base64", "raw_output_sha256",
                       "raw_output_size_bytes")
    assignments = evidence["per_residue_assignments"]
    require(isinstance(assignments, list) and assignments, "empty/malformed assignment stream")
    observed, biotite = {}, {}
    for row in assignments:
        key = (row["chain"], row["resnum"], row["icode"])
        require(all(isinstance(x, str) for x in key) and key[0] and key[1]
                and len(key[2]) <= 1 and key not in observed, "invalid/duplicate assignment key")
        require(row["dssp"] in ("H", "E", "C") and row["biotite_psea"] in ("H", "E", "C"),
                "missing/invalid assigner value")
        observed[key], biotite[key] = row["dssp"], row["biotite_psea"]
    require(raw_dssp_assignments(raw) == observed, "raw DSSP/assignment mismatch")
    n, same = len(observed), sum(observed[k] == biotite[k] for k in observed)
    counts = Counter(observed.values())
    calculated = {"n_dssp": n, "n_biotite": n, "n_scored": n, "n_dropped": 0, "n_agree": same,
                  "fraction": round(same / n, 4), "dssp_h": counts["H"], "dssp_e": counts["E"],
                  "dssp_c": counts["C"], "dssp_ss_content": round((counts["H"] + counts["E"]) / n, 4)}
    require(all(type(evidence["aggregate"].get(k)) is int for k in calculated
                if k not in {"fraction", "dssp_ss_content"}), "invalid aggregate count type")
    require(evidence["aggregate"] == calculated, "T15 aggregate mismatch")
    payload = {"subject_ref": None, "input_sha256": evidence["source_sha256"],
               "normalization_mode": "gemmi convert",
               "normalized_sha256": evidence["normalization"]["sha256"],
               "gemmi_version": VERSIONS["normalization"], "dssp_version": VERSIONS["dssp"],
               "biotite_version": VERSIONS["biotite_psea"], **calculated}
    bundle = "EVAL_BENCH_T15_SS_" + sha(
        yaml.safe_dump(payload, sort_keys=True, allow_unicode=True).encode())[:16]
    require(evidence["bundle_ref"] == bundle, "T15 result identity mismatch")
    benchmark = load_json(entry / "benchmark.json")
    require(benchmark["skipped"] == [] and len(benchmark["rows"]) == 1, "skipped/extra T15 row")
    expected_row = {"pdb_id": pdb, "agreement": calculated["fraction"],
                    "ss_content": calculated["dssp_ss_content"], "n_concordant": same,
                    "n_scored": n, "n_dssp": n, "n_biotite": n, "n_dropped": 0,
                    "clears_provisional_content_precondition": calculated["dssp_ss_content"] >= .20,
                    "meets_provisional_0_65_expectation":
                        calculated["dssp_ss_content"] >= .20 and calculated["fraction"] >= .65}
    require(all(type(benchmark["rows"][0].get(k)) is int for k in
                ("n_concordant", "n_scored", "n_dssp", "n_biotite", "n_dropped")),
            "invalid runner count type")
    require(benchmark["rows"] == [expected_row], "runner row mismatch")
    rows = yaml.load((root / "t15_cache" / f"t15_{pdb.lower()}.log").read_text(), Loader=UniqueYaml)
    require(isinstance(rows, list) and len(rows) == 2, "wrong wrapper row count")
    require({r["metric_definition_ref"] for r in rows} == set(METRICS), "wrong wrapper metrics")
    for row in rows:
        informational(row)
        metric = row["metric_definition_ref"]
        first = metric == METRICS[0]
        require(row["id"] == bundle + ("_M_agreement" if first else "_M_content")
                and row["bundle_ref"] == bundle and row.get("subject_ref") is None,
                "wrapper identity/subject mismatch")
        require(row["catalog_task_ref"] == "T15" and row["stage"] == "final"
                and row["scope"] == "complex" and row["oracle_family"] == "non_cctbx"
                and row["oracle_tool_ref"] == ("DSSP + biotite P-SEA" if first else "DSSP"),
                "wrong wrapper measurement context")
        require(row["oracle_measure"] == {"value_numeric": calculated[
            "fraction" if first else "dssp_ss_content"], "unit": "fraction"}, "wrapper scalar mismatch")
        require(row["evidence_refs"] == [path.relative_to(repo).as_posix()], "wrapper evidence mismatch")
        notes = row.get("notes", "")
        require(all(value in notes for value in (*VERSIONS.values(), evidence["source_sha256"],
                                                 evidence["normalization"]["sha256"])),
                "wrapper notes lost version/input provenance")
        required_note = (f"{same}/{n} concordant over residues scored by both "
                         f"(DSSP {n}, biotite {n}, 0 scored by only one and excluded)"
                         if first else f"({counts['H']} H + {counts['E']} E) / {n} = "
                         f"{calculated['dssp_ss_content']:.4f}")
        require(required_note in notes, "wrapper note counts mismatch")
    return {"pdb_id": pdb, "status": "admitted_informational", **calculated,
            "raw_integer_content_prediction": 100 * (counts["H"] + counts["E"]) >= 20 * n,
            "raw_integer_agreement_prediction": 100 * same >= 65 * n}


def mtz_row_count(raw):
    require(raw[:4] == b"MTZ " and raw[8:10] == bytes.fromhex("4441"), "unsupported MTZ header")
    offset = (struct.unpack("<i", raw[4:8])[0] - 1) * 4
    require(80 <= offset < len(raw), "invalid MTZ offset")
    records = []
    for start in range(offset, len(raw), 80):
        record = raw[start:start + 80]
        require(len(record) == 80, "truncated MTZ header")
        line = record.decode("ascii").strip()
        if line == "END":
            break
        records.append(line.split())
    else:
        raise ValueError("missing MTZ END")
    rows = [r for r in records if r and r[0] == "NCOL"]
    require(len(rows) == 1 and len(rows[0]) == 4, "ambiguous MTZ dimensions")
    cols, n, batches = map(int, rows[0][1:])
    require(cols > 0 and n > 0 and batches == 0 and offset == 80 + 4 * cols * n,
            "invalid MTZ dimensions")
    return n


def check_overwrite_refusal(repo, logs, source):
    """Exercise only pinned historical main with scientific functions and writes denied."""
    tree = ast.parse(source)
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef)
                 and n.name in {"main", "_repository_location"}]
    require(len(functions) == 2 and logs.is_dir(), "historical overwrite check unavailable")
    deny = mock.Mock(side_effect=ValueError("scientific execution forbidden in replay"))
    namespace = {"argparse": argparse, "Path": Path, "hashlib": hashlib, "sys": sys,
                 "REPO_ROOT": repo, "try_aimless": deny, "run_ctruncate": deny}
    exec(compile(ast.Module(body=functions, type_ignores=[]), "<pinned historical T13>", "exec"),
         namespace)
    def refused_mkdir(path, *args, **kwargs):
        require(path == logs and kwargs == {"parents": True, "exist_ok": False},
                "unexpected mkdir request in historical refusal check")
        raise FileExistsError(logs)
    argv = ["t13_data_quality.py", str(repo / INPUT), "--eval-id", "EVAL_T13_OPERATIONAL_CANARY",
            "--columns", "F-obs,SIGF-obs", "--logdir", str(logs)]
    with mock.patch.object(sys, "argv", argv), mock.patch.object(Path, "mkdir", refused_mkdir):
        try:
            namespace["main"]()
        except SystemExit as error:
            require("refusing to overwrite" in str(error), "wrong historical overwrite refusal")
        else:
            raise ValueError("historical main did not refuse overwrite")
    require(not deny.called, "historical overwrite path reached a scientific function")
    return True


def recount_t13(repo, entry, historical):
    logs = entry / "tool_logs"
    aimless, ctruncate = (logs / "aimless.log").read_text(), (logs / "ctruncate.log").read_text()
    require("version 0.8.3" in aimless and "CCP4 9.0.015" in aimless
            and "hkl_unmerge_list::prepare - EMPTY" in aimless, "unexpected AIMLESS outcome/version")
    require("version 1.17.29" in ctruncate and "CCP4 9.0.015" in ctruncate,
            "unexpected ctruncate version")
    n = mtz_row_count((logs / "ctruncate_out.mtz").read_bytes())
    require(n == mtz_row_count((repo / INPUT).read_bytes()), "T13 operational row-count mismatch")
    def number(pattern):
        found = re.findall(pattern, ctruncate)
        require(len(found) == 1, f"ambiguous/missing T13 log field: {pattern}")
        value = float(found[0])
        require(math.isfinite(value), "nonfinite T13 log value")
        return value
    wilson = number(r"Estimate of Wilson B factor:\s*([0-9.]+)")
    twin = number(r"Twin fraction estimate from L-test:\s*([0-9.]+)")
    matrix = re.search(r"Anisotropic B scaling \(orthogonal coords\):\s*\n([\s\S]+?)\n\n", ctruncate)
    require(matrix is not None, "missing anisotropy matrix")
    matrix_rows = [line.strip().strip("|").split() for line in matrix[1].splitlines()]
    require(len(matrix_rows) == 3 and all(len(r) == 3 for r in matrix_rows), "malformed anisotropy matrix")
    diagonal = [round(float(row[i]), 4) for i, row in enumerate(matrix_rows)]
    require(all(math.isfinite(v) for v in diagonal) and "Some anisotropy detetect." in ctruncate,
            "missing/invalid anisotropy diagnostic")
    require("No translational NCS detected (with resolution limited to  4.00 A)" in ctruncate
            and "First principles calculation has found no potential twinning operators" in ctruncate,
            "missing explicit negative T13 flag evidence")
    ice = re.findall(r"^\s*(3\.90|3\.67|3\.44|2\.67)\s+(yes|no)\s+", ctruncate, re.M)
    require(ice == [("3.90", "no"), ("3.67", "no"), ("3.44", "yes"), ("2.67", "no")],
            "changed/incomplete retained ice-ring table")
    expected = {"T13_wilson_b": {"value_numeric": wilson, "unit": "Å²"},
                "T13_l-test_twinning": {"value_numeric": twin, "unit": "fraction"},
                "T13_anisotropy_δb_aniso": {"value_numeric": max(diagonal) - min(diagonal), "unit": "Å²"},
                "T13_tncs_flag": {"value_text": "false"},
                "T13_ice-ring_flags": {"value_text": "3.44Å"},
                "T13_aimless_status": {"value_text": "failed"}}
    rows = yaml.load((entry / "launcher.log").read_text(), Loader=UniqueYaml)
    require(isinstance(rows, list) and len(rows) == len(expected)
            and {r["metric_definition_ref"] for r in rows} == set(expected), "wrong T13 metric rows")
    for row in rows:
        informational(row)
        metric = row["metric_definition_ref"]
        attempt = metric == "T13_aimless_status"
        require(row["oracle_measure"] == expected[metric], f"T13 log/row mismatch: {metric}")
        require(row["subject_ref"] == "mtz:sha256:" + INPUT_SHA
                and row["catalog_task_ref"] == "T13" and row["stage"] == "all"
                and row["scope"] == "dataset" and row["oracle_family"] == "non_cctbx"
                and row["scope_selector"] == ("all input reflections" if attempt else "/*/*/[F-obs,SIGF-obs]"),
                "T13 subject/context mismatch")
        require(row["oracle_tool_ref"] == ("CCP4 aimless" if attempt else "ctruncate")
                and row["agent_claim"] == {"is_not_applicable": True}, "T13 oracle/claim mismatch")
        ref = (logs / ("aimless.log" if attempt else "ctruncate.log")).relative_to(repo).as_posix()
        require(row["evidence_refs"] == [ref], "T13 evidence reference mismatch")
    return {"status": "operational_only", "measurement_rows": len(rows), "output_reflections": n,
            "historical_overwrite_refusal_with_tools_and_writes_denied":
                check_overwrite_refusal(repo, logs, historical["scripts/t13_data_quality.py"])}


def expected_argv(request, entry_id):
    old = request["repo"]
    require(isinstance(old, str) and old.startswith("/") and old.rstrip("/") == old,
            "malformed historical repository path")
    entry, root = old + "/" + request["entry"], old + "/" + request["root"]
    head = [old + "/.venv/bin/python", "-B"]
    if entry_id == "T13_1SAR":
        return head + [old + "/scripts/t13_data_quality.py", old + "/" + INPUT,
                       "--columns", "F-obs,SIGF-obs", "--eval-id", "EVAL_T13_OPERATIONAL_CANARY",
                       "--logdir", entry + "/tool_logs"]
    return head + [old + "/scripts/bench_t15_ss_agreement.py", entry_id[4:],
                   "--cache", root + "/t15_cache", "--evidence-dir", root + "/t15_evidence",
                   "--json", entry + "/benchmark.json"]


def input_atom_inventory(path):
    """Inspect saved PDB ATOM fields only; these are not either assigner's keys."""
    residues, names, atom_records = {}, {}, 0
    for line in path.read_text().splitlines():
        require(not line.startswith(("MODEL ", "ENDMDL")), "input-only recount requires one unnumbered model")
        if not line.startswith("ATOM  "):
            continue
        require(len(line) >= 27 and line[12:16].strip() and line[22:26].strip(),
                "malformed PDB ATOM identity")
        key = (line[21].strip(), line[22:26].strip(), line[26].strip())
        name = line[17:20].strip()
        require(key not in names or names[key] == name, "ambiguous PDB residue identity")
        names[key] = name
        residues.setdefault(key, set()).add(line[12:16].strip())
        atom_records += 1
    require(residues, "saved failed input has no ATOM residues")
    incomplete = [{"chain": key[0], "resnum": key[1], "icode": key[2], "resname": names[key],
                   "missing_backbone_atoms": sorted({"N", "CA", "C", "O"} - atoms)}
                  for key, atoms in sorted(residues.items()) if {"N", "CA", "C", "O"} - atoms]
    return {"scope": "saved input ATOM fields only; not unmatched assigner keys or a cause",
            "atom_records": atom_records, "atom_residues": len(residues),
            "residues_per_chain": dict(sorted(Counter(key[0] for key in residues).items())),
            "incomplete_backbone_residues": incomplete}


def recount_root(repo, label, historical):
    relative = BASE + "/retained_evidence_2026-09-27_" + label
    root = safe_path(repo, relative)
    files = inventory(root)
    owner = load_json(root / "launch-root.json")
    require(owner == {"format": "preregistered-canaries-launch-root-v1",
                      "preregistration_commit": COMMIT, "source_hashes": SOURCE_PINS},
            "launch-root identity/source mismatch")
    ids = ["T15_" + pdb for pdb in COHORT[:PREFIXES[label]]]
    if label == "canaries01":
        ids.insert(0, "T13_1SAR")
    require({p.name for p in (root / "entries").iterdir()} == set(ids),
            "missing/extra attempted entry; refusing a success-only or expanded cohort")
    covered, attempts, prior_end = set(), [], None
    for entry_id in ids:
        entry = root / "entries" / entry_id
        request, result = load_json(entry / "launch-request.json"), load_json(entry / "launch-result.json")
        require(request["mode"] == "execute" and request["preregistration_commit"] == COMMIT
                and request["root"] == relative and request["entry"] == relative + "/entries/" + entry_id
                and request["source_hashes"] == SOURCE_PINS and request["timeout_seconds"] == 900
                and request["t13_input_sha256_before"] == INPUT_SHA, "launch request provenance mismatch")
        require(request["python_packages"]["gemmi"] == "0.7.5"
                and request["python_packages"]["biotite"] == "1.7.1"
                and isinstance(request["python"], str)
                and request["python"].startswith("3.12."), "recorded environment mismatch")
        process = result["process"]
        require(request["argv"] == expected_argv(request, entry_id)
                and process["arguments"] == request["argv"], "recorded execution argv mismatch")
        require(result["source_hashes_after"] == SOURCE_PINS and result["sources_unchanged"] is True
                and result["t13_input_sha256_after"] == INPUT_SHA and result["t13_input_unchanged"] is True,
                "post-execution source/input mismatch")
        require(result["launcher_error"] is None and result["interrupted_pgids"] == []
                and process["timed_out"] is False and process["termination_signal"] is None
                and process["start_new_session"] is True and type(process["pid"]) is int
                and process["pid"] > 0 and type(process["pgid"]) is int
                and process["pgid"] == process["pid"], "unexpected process outcome")
        started, ended = datetime.fromisoformat(request["started_at"]), datetime.fromisoformat(result["completed_at"])
        require(started.tzinfo is not None and ended.tzinfo is not None and started <= ended
                and (prior_end is None or prior_end <= started), "overlapping/out-of-order invocation")
        prior_end = ended
        manifest = result["files_before_result_manifest"]
        require(isinstance(manifest, dict) and manifest, "empty file inventory")
        last = entry_id == ids[-1]
        required = {"launch-root.json", f"entries/{entry_id}/launch-request.json",
                    f"entries/{entry_id}/launcher.log"}
        require(required <= manifest.keys(), "manifest omits required launch evidence")
        expected_files = covered | required
        if entry_id == "T13_1SAR":
            expected_files |= {f"entries/{entry_id}/tool_logs/{name}" for name in
                               ("aimless.log", "ctruncate.log", "ctruncate_out.mtz")}
        elif not last or label == "canaries02":
            pdb = entry_id[4:].lower()
            expected_files |= {f"entries/{entry_id}/benchmark.json",
                               f"t15_cache/{pdb}.pdb", f"t15_cache/t15_{pdb}.log"}
            if not last:
                expected_files.add(f"t15_evidence/{pdb}.t15-evidence.json")
        require(manifest.keys() == expected_files, "manifest snapshot omits or misattributes attempt files")
        for ref, recorded in manifest.items():
            safe_path(root, ref)
            require(ref in files and isinstance(recorded, dict)
                    and type(recorded.get("size")) is int and recorded == files[ref],
                    f"manifest file/hash mismatch: {ref}")
        covered.update(manifest)
        covered.add(f"entries/{entry_id}/launch-result.json")  # A manifest cannot hash itself.
        require(type(process["returncode"]) is int and process["returncode"] == (1 if last else 0),
                "unexpected success/failure sequence")
        if not last:
            detail = (recount_t13(repo, entry, historical) if entry_id == "T13_1SAR"
                      else recount_t15(repo, root, entry, entry_id[4:]))
        else:
            pdb = entry_id[4:]
            require(not (root / "t15_evidence" / f"{pdb.lower()}.t15-evidence.json").exists(),
                    "failed attempt unexpectedly has a success bundle")
            if label == "canaries01":
                require("socket.gaierror" in (entry / "launcher.log").read_text()
                        and "nodename nor servname provided, or not known" in (entry / "launcher.log").read_text()
                        and not (entry / "benchmark.json").exists()
                        and not (root / "t15_cache" / f"{pdb.lower()}.pdb").exists()
                        and not (root / "t15_cache" / f"t15_{pdb.lower()}.log").exists(),
                        "unexpected first-root fetch failure evidence")
                detail = {"pdb_id": pdb, "status": "failed_fetch", "raw_assignments": "unavailable"}
            else:
                log = (root / "t15_cache" / f"t15_{pdb.lower()}.log").read_text()
                require("DSSP-only=0, biotite-only=1" in log, "missing denominator refusal")
                require((root / "t15_cache" / f"{pdb.lower()}.pdb").stat().st_size > 0,
                        "missing failed input")
                require(load_json(entry / "benchmark.json") == {"rows": [], "skipped": [
                    {"pdb_id": pdb, "reason": "t15_ss_agreement failed"}], "summary": {"n": 0}},
                    "failed entry's skipped outcome missing")
                detail = {"pdb_id": pdb, "status": "failed_denominator_admission",
                          "reported_dssp_only": 0, "reported_biotite_only": 1,
                          "raw_assignments": "unavailable; failure keys cannot be independently recounted",
                          "input_coordinate_inspection": input_atom_inventory(
                              root / "t15_cache" / f"{pdb.lower()}.pdb")}
        attempts.append({"entry_id": entry_id, "returncode": process["returncode"],
                         "started_at": request["started_at"], "completed_at": result["completed_at"],
                         "pid": process["pid"], "pgid": process["pgid"], **detail})
    require(covered == files.keys(), "unmanifested retained file(s); do not hide or add attempts")
    return {"root": relative, "attempts": attempts, "unstarted_t15": list(COHORT[PREFIXES[label]:]),
            "t15_admitted": sum(r["status"] == "admitted_informational" for r in attempts),
            "t15_failed": 1, "complete_cohort": False, "retained_files": len(files)}


def recount(repo=REPO_ROOT):
    repo = repo.resolve()
    require(sha(safe_path(repo, INPUT).read_bytes()) == INPUT_SHA, "retained T13 input digest mismatch")
    historical, source_mode = historical_sources(repo)
    roots = [recount_root(repo, label, historical) for label in PREFIXES]
    return {"preregistration_commit": COMMIT, "source_pin_verification": source_mode, "roots": roots,
            "scientific_acceptance": "informational only; full T15 cohort unestablished",
            "limits": ["No scientific tools or assigners were reexecuted.",
                       "1BNI asymmetric key identities/raw failed streams were not retained.",
                       "Final manifests do not hash themselves; the repository revision anchors them.",
                       "Successful attempts in separate roots are not additional cohort members."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        result = recount()
    except (ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError,
            struct.error, yaml.YAMLError) as error:
        parser.exit(2, f"retained canary replay failed: {error}\n")
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
