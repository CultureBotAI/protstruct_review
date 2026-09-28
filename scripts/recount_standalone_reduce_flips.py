#!/usr/bin/env python3
"""Read-only, informational recount of one retained standalone Reduce bundle.

Source grammar: Reduce FlipMemo.cpp (orientation table / formatComment),
AtomPositions.cpp (15-column descriptors / describeChanges), CliqueList.cpp
(Single / Set prefixes), RotDonor.cpp and Rot3Fold.cpp (rotation comments).
Unknown grammar, SEGID descriptors and ambiguous coordinates fail closed.
No execution, network, legacy reduce2 comparison, historical correction or grade.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import sys

import bench_dictionary_loaded_reduce as driver

CONTRACT = "standalone-reduce-emitted-flip-recount/1"
KEY_FIELDS = ("model_ordinal", "chain_raw", "resnum", "icode", "resname", "altloc")
ORIENTATIONS = {
    "     no HD1": ("HIS", False), "     no HE2": ("HIS", False),
    "    +bothHN": ("HIS", False), "FLIP no HD1": ("HIS", True),
    "FLIP no HE2": ("HIS", True), "FLIP+bothHN": ("HIS", True),
    "    - no HN": ("HIS", False), "FLIP- no HN": ("HIS", True),
    "      amide": ("amide", False), "FLIP  amide": ("amide", True),
}
NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
FLIP_SCORE = re.compile(
    rf"sc= *(?P<score>{NUMBER})(?P<clash>[! ]) (?P<category>[CXFK])"
    rf"\(o=(?P<original>{NUMBER})(?P<original_clash>!?),"
    rf"f=(?P<flipped>{NUMBER})(?P<flipped_clash>!?)\)")
ROTATION_SCORE = re.compile(
    rf"sc= *(?P<score>{NUMBER})(?P<clash>[! ])?"
    rf"(?:  \(180deg=(?P<initial>{NUMBER})(?P<initial_clash>!?)\))?")
HEADERS = {
    "USER  MOD -----------------------------------------------------------------",
    'USER  MOD scores for adjustable sidechains, with "set" totals for H,N and Q',
    'USER  MOD "o" means original, "f" means flipped, "180deg" is methyl default',
    'USER  MOD flip categories: "K"=keep, "C"=clashes, "X"=uncertain, "F"=flip',
}
SUMMARY = re.compile(r"USER  MOD reduce\.[\d.]+ H: found=\d+, std=\d+, add=\d+, rem=\d+, adj=\d+")
CLASH_HEADER = re.compile(r'USER  MOD "!" flags a clash with an overlap of -?\d+\.\d{2}A or greater')


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def full_key(key: dict) -> tuple:
    return tuple(key[field] for field in KEY_FIELDS)


def key_dict(key: tuple) -> dict:
    return dict(zip(KEY_FIELDS, key, strict=True))


def descriptor(value: str) -> tuple[dict, str]:
    if len(value) != 15:
        raise ValueError("unsupported_descriptor_width_or_SEGID")
    if not re.fullmatch(r" *-?\d+", value[2:6]):
        raise ValueError("unsupported_residue_number")
    if not re.fullmatch(r"[ A-Z0-9]{3}", value[7:10]) or not value[7:10].strip():
        raise ValueError("unsupported_residue_name")
    return {"model_ordinal": 1, "chain_raw": value[:2], "resnum": int(value[2:6]),
            "icode": value[6], "resname": value[7:10], "altloc": value[14]}, value[10:14]


def finite_scores(match: re.Match, names: tuple[str, ...]) -> dict:
    result = {}
    for name in names:
        text = match[name]
        if text is not None:
            value = float(text)
            if not math.isfinite(value):
                raise ValueError("nonfinite_score")
            result[name + "_text"] = text
            result[name] = value
    return result


def parse_line(raw: str, line_number: int = 1) -> dict:
    """Classify every retained line; rejected records retain their exact text."""
    result = {"raw": raw, "line_number": line_number}
    try:
        if raw in HEADERS or SUMMARY.fullmatch(raw) or CLASH_HEADER.fullmatch(raw):
            return {**result, "status": "metadata"}
        if not raw.startswith("USER  MOD "):
            raise ValueError("unknown_USER_MOD_record")
        fields = raw[10:].split(":")
        if len(fields) != 4:
            raise ValueError("unsupported_record_shape")
        prefix, desc, orientation, tail = fields
        if prefix != "Single " and not re.fullmatch(r"Set *[1-9]\d*\.[1-9]\d*", prefix):
            raise ValueError("unsupported_prefix")
        key, atom = descriptor(desc)
        result.update(prefix=prefix, descriptor=desc, key=key, orientation=orientation)
        if atom != "    ":
            if not atom.strip() or not re.fullmatch(r"(?:   rot |methyl |NH3\+   ) *-?\d+", orientation):
                raise ValueError("unsupported_nonflip_orientation")
            match = ROTATION_SCORE.fullmatch(tail)
            if match is None:
                raise ValueError("malformed_rotation_tail")
            is_threefold = orientation.startswith(("methyl ", "NH3+   "))
            if is_threefold != (match["initial"] is not None):
                raise ValueError("rotation_tail_kind_mismatch")
            return {**result, "status": "non_flip_rotation", "atom_name_raw": atom,
                    **finite_scores(match, ("score", "initial")),
                    "clash_selected": match["clash"] == "!",
                    "clash_initial": match["initial_clash"] == "!"}
        if orientation not in ORIENTATIONS:
            raise ValueError("unsupported_flip_orientation")
        kind, flipped = ORIENTATIONS[orientation]
        if key["resname"] not in (("ASN", "GLN") if kind == "amide" else ("HIS",)):
            raise ValueError("orientation_residue_mismatch")
        match = FLIP_SCORE.fullmatch(tail)
        if match is None:
            raise ValueError("malformed_flip_tail")
        both_clash = match["original_clash"] == "!" and match["flipped_clash"] == "!"
        if (match["category"] == "C") != both_clash:
            raise ValueError("category_clash_contradiction")
        if (match["category"] == "F" and not flipped) or (match["category"] == "K" and flipped):
            raise ValueError("category_direction_contradiction")
        scores = finite_scores(match, ("score", "original", "flipped"))
        # Do not recompute confidence from scores rounded by Reduce's formatter.
        scores["original_score_text"] = scores.pop("original_text")
        scores["original_score"] = scores.pop("original")
        scores["flipped_score_text"] = scores.pop("flipped_text")
        scores["flipped_score"] = scores.pop("flipped")
        return {**result, "status": "parsed_flip", **scores, "flipped": flipped,
                "category": match["category"], "clash_selected": match["clash"] == "!",
                "clash_original": match["original_clash"] == "!",
                "clash_flipped": match["flipped_clash"] == "!"}
    except ValueError as error:
        return {**result, "status": "rejected", "reason": str(error)}


def coordinate_keys(h_bytes: bytes) -> tuple[set, set, set, str | None]:
    """Exact single-model residue/conformer keys; blank common atoms are shared.

    When named conformers exist, blank atoms do not create an additional blank
    conformer. A blank call against that residue is rejected as ambiguous.
    This is binding, not a test of side-chain completeness or chemical validity.
    """
    lines = h_bytes.decode("ascii").splitlines()
    models = [i for i, line in enumerate(lines) if line[:6] == "MODEL "]
    ends = [i for i, line in enumerate(lines) if line[:6] == "ENDMDL"]
    if len(models) > 1 or len(ends) != len(models) or (models and models[0] >= ends[0]):
        raise ValueError("Multiple/ambiguous MODEL boundaries")
    residues, atoms = {}, set()
    for i, line in enumerate(lines):
        if line[:6] not in ("ATOM  ", "HETATM"):
            continue
        if len(line) < 78 or (models and not models[0] < i < ends[0]):
            raise ValueError("Malformed or out-of-model coordinate")
        # Same decimal identity as FlipMemo's %4d; no hybrid-36 inference.
        key, _ = descriptor(line[20:22] + line[22:26] + line[26] + line[17:20] + "    " + line[16])
        item = full_key(key)
        atom = (*item, line[12:16])
        if atom in atoms or not line[12:16].strip():
            raise ValueError("Duplicate/ambiguous coordinate atom")
        atoms.add(atom)
        residues.setdefault(item[:-1], set()).add(item[-1])
    if not atoms:
        raise ValueError("No coordinates")
    keys = {(*residue, alt) for residue, alts in residues.items() for alt in (alts - {" "} or {" "})}
    candidates = {key for key in keys if key[4] in ("ASN", "GLN", "HIS")}
    return keys, candidates, atoms, lines[models[0]][10:14] if models else None


def recount(h_bytes: bytes, raw_bytes: bytes, *, input_bytes: bytes | None = None) -> dict:
    """Pure byte recount; output alone cannot establish newly generated calls.

    Supplied input bytes provide only an annotation-origin check here. Actual
    source/command/retained-byte admission belongs to recount_bundle.
    """
    if input_bytes is not None and any(
        # Reduce normalizes the four-character record name, but not the MOD body.
        re.match(rb"(?i:USER)\s+MOD\b", line) for line in input_bytes.splitlines()
    ):
        raise ValueError("Retained input contains USER MOD annotations; call origin is ambiguous")
    h_lines = h_bytes.splitlines(keepends=True)
    extracted = b"".join(line for line in h_lines if line.startswith(b"USER  MOD"))
    if raw_bytes != extracted:
        raise ValueError("Retained USER MOD bytes differ from H coordinates")
    keys, candidates, atoms, model_label = coordinate_keys(h_bytes)
    records = [parse_line(line, n) for n, line in enumerate(raw_bytes.decode("ascii").splitlines(), 1)]
    # The driver extracts the exact double-space spelling. Never lose an
    # identity-bearing alternate spelling, e.g. Reduce's ambiguous-A rename.
    other_user_mod = [{"h_line_number": n, "raw": line.decode("ascii").rstrip("\r\n")}
                      for n, line in enumerate(h_lines, 1)
                      if re.match(rb"USER\s+MOD\b", line) and not line.startswith(b"USER  MOD")]
    seen = set()
    for record in records:
        if record["status"] not in ("parsed_flip", "non_flip_rotation"):
            continue
        key = full_key(record["key"])
        identity = (key, record.get("atom_name_raw", "    "))
        reason = "missing_or_ambiguous_coordinate_binding" if key not in keys else None
        if record["status"] == "non_flip_rotation":
            # Common blank-alt atoms may belong to a named conformer, but an
            # unrelated atom in the same residue is not a rotation anchor.
            exact = (*key, record["atom_name_raw"])
            common = (*key[:-1], " ", record["atom_name_raw"])
            if exact not in atoms and common not in atoms:
                reason = "missing_rotation_atom_binding"
        if identity in seen:
            reason = "duplicate_mover_key"
        seen.add(identity)
        if reason:
            record.update(status="rejected", reason=reason)
    counts = Counter(record["status"] for record in records)
    calls = [record for record in records if record["status"] == "parsed_flip"]
    called = {full_key(call["key"]) for call in calls}
    rejected = counts["rejected"] > 0 or bool(other_user_mod)
    status = "rejected" if rejected else ("complete_emitted_calls" if calls else "needs_review_no_calls")
    if status == "complete_emitted_calls" and input_bytes is None:
        status = "output_only_unattributed"
    return {"contract": CONTRACT, "status": status, "h_sha256": digest(h_bytes),
            "input_sha256": digest(input_bytes) if input_bytes is not None else None,
            "input_annotation_check": "no_preexisting_USER_MOD" if input_bytes is not None else "not_supplied",
            "raw_sha256": digest(raw_bytes), "model_ordinal": 1, "model_label_raw": model_label,
            "records": records, "record_counts": {key: counts[key] for key in
                ("metadata", "non_flip_rotation", "parsed_flip", "rejected")},
            "raw_line_count": len(records), "unsupported_USER_MOD_spellings": other_user_mod,
            "parsed_mover_count": len(calls), "parsed_flipped_mover_count": sum(call["flipped"] for call in calls),
            "parsed_distinct_residue_count": len({key[:-1] for key in called}),
            "category_counts": dict(sorted(Counter(call["category"] for call in calls).items())),
            "coordinate_candidate_keys": [key_dict(key) for key in sorted(candidates)],
            "unadjudicated_coordinate_keys": [key_dict(key) for key in sorted(candidates - called)],
            "counts_admitted": status == "complete_emitted_calls",
            "coverage_scope": "Eligible output flip-call records only; not all chemically flippable residues. "
                              "New-call attribution requires admitted input without pre-existing USER MOD annotations. "
                              "Unadjudicated coordinates are not keep calls; rejected, zero-call and output-only counts are diagnostic only.",
            "comparison_scope": "Single standalone stream only; no reduce2 conflict rate, grade, or historical correction."}


def legacy_comparison_keys(_result: dict) -> None:
    """Deliberately no projection: both streams need a reviewed identity contract."""
    raise ValueError("Legacy (chain, residue, name) comparison is unsupported: expanded standalone "
                     "identities cannot be joined to the old reduce2 domain without a paired adapter")


def checked_inventory(directory: Path, inventory: dict) -> None:
    if not isinstance(inventory, dict) or not inventory:
        raise ValueError("Missing original retained inventory")
    for relative, sha256 in inventory.items():
        path = directory / relative
        if Path(relative).is_absolute() or ".." in Path(relative).parts or not path.resolve().is_relative_to(directory):
            raise ValueError("Evidence path escapes entry")
        if digest(path.read_bytes()) != sha256:
            raise ValueError(f"Original retained hash mismatch: {relative}")


def recount_bundle(directory: Path) -> dict:
    """Admit using the current driver's read-only checker; original paths required.

    Parent/worker inventories are checked against their retained original pins,
    not freshly generated hashes. This detects mutation, not maliciously forged
    manifests; no offline relocation or authenticated execution is asserted.
    """
    directory = directory.resolve(strict=True)
    parser_bytes = Path(__file__).read_bytes()
    parent_bytes = (directory / "result.json").read_bytes()
    parent = json.loads(parent_bytes)
    if parent.get("status") != "complete":
        raise ValueError("Parent evidence attempt is not complete")
    if parent.get("process", {}).get("returncode") != 0 or parent["process"].get("timed_out") is not False:
        raise ValueError("Parent process did not complete successfully")
    checked_inventory(directory, parent["retained_files"])
    for required in ("request.json", "worker-result.json", "raw-user-mod.txt"):
        if required not in parent["retained_files"]:
            raise ValueError(f"Parent inventory omits {required}")
    request = json.loads((directory / "request.json").read_bytes())
    worker = json.loads((directory / "worker-result.json").read_bytes())
    if (request.get("contract") != 1 or request.get("mode") != "execute"
            or request.get("entry") not in driver.COHORTS.get(request.get("cohort"), ())
            or Path(request["evidence_root"]) / request["entry"] != directory):
        raise ValueError("Unsupported request or mismatched one-entry directory")
    if worker.get("status") != "complete":
        raise ValueError("Worker evidence attempt is not complete")
    checked_inventory(directory, worker["evidence_files"])
    if any(parent["retained_files"].get(key) != value for key, value in worker["evidence_files"].items()):
        raise ValueError("Parent/worker evidence pins disagree")
    driver.admit_evidence(request, directory, worker)
    h_path = Path(worker["h_model"]["path"])
    if h_path.relative_to(directory).as_posix() not in worker["evidence_files"]:
        raise ValueError("H file absent from worker inventory")
    h_bytes = driver.checked_bytes(h_path, worker["h_model"]["sha256"])
    provenance = json.loads((directory / "input-provenance.json").read_bytes())
    retained_input = provenance["retained_file"]
    input_bytes = driver.checked_bytes(Path(retained_input["path"]), retained_input["sha256"])
    result = recount(h_bytes, (directory / "raw-user-mod.txt").read_bytes(), input_bytes=input_bytes)
    driver.admit_evidence(request, directory, worker)
    checked_inventory(directory, worker["evidence_files"])
    checked_inventory(directory, parent["retained_files"])
    if (directory / "result.json").read_bytes() != parent_bytes:
        raise ValueError("Parent result changed during recount")
    if Path(__file__).read_bytes() != parser_bytes:
        raise ValueError("Parser source changed during recount")
    result["evidence"] = {"entry_directory": str(directory), "entry": request["entry"],
                          "cohort": request["cohort"], "parent_sha256": digest(parent_bytes),
                          "retained_files": parent["retained_files"],
                          "parser_sha256": digest(parser_bytes),
                          "admission_checker_sha256": digest(Path(driver.__file__).read_bytes())}
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("entry_directory", type=Path)
    args = parser.parse_args(argv)
    try:
        result = recount_bundle(args.entry_directory)
        print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
        return 0 if result["counts_admitted"] else 1
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Recount refused: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
