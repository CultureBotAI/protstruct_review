#!/usr/bin/env python3
"""Compute the T15 secondary-structure agreement metric from two independent assigners.

The T15 oracle-pair metric (`T15_secondary_structure_agreement`) is the fraction of
residues that two *independent* secondary-structure assigners place in the same
three-state class (H / E / C). It is reported informationally alongside DSSP H+E
content. The provisional 0.20 content precondition only indicates whether the
agreement has useful interpretive range; neither value grades model quality. The
historical 0.65 expectation is likewise non-gradeable until the benchmark is rerun
under the current exact-denominator rule.

Assigner A: **DSSP** (`mkdssp`) — Kabsch & Sander H-bond energetics.
Assigner B: **biotite** `annotate_sse` — Labesse P-SEA, a Cα-geometry method.

The two are genuinely different algorithm families (H-bond vs Cα geometry), so
agreement is informative rather than tautological, and both are non-cctbx —
satisfying the trust model without either being PHENIX.

Emits pasteable EvaluationMeasurement-shaped YAML rows for the scalar agreement
and the DSSP H+E interpretability diagnostic, plus optional per-residue three-state
labels. Every run requires an explicit repository-local ``--evidence-out`` path.
The no-overwrite JSON bundle retains the exact normalized input and raw DSSP bytes,
both per-residue assignments, input hashes, and measured tool versions; both rows
cite it through ``evidence_refs``.

If both assigners complete but their residue keys differ (or have no shared key),
the same no-overwrite destination instead retains a clearly typed failed-attempt
JSON before the nonzero exit. It contains no scalar measurements or grading;
earlier execution failures do not yet have this retention guarantee.

Degrades loudly: if `mkdssp` cannot be resolved through `PROTSTRUCT_DSSP` or
PATH, or biotite is not importable, exits non-zero with a clear message rather
than fabricating a number.

Usage:
    python3 scripts/t15_ss_agreement.py data/pdb_mtz/1sar_deposited.pdb \
      --eval-id EVAL_1sar_... --evidence-out data/evidence/EVIDENCE_1sar_t15.json
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.metadata
import io
import json
import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any

import yaml

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from toolchain import dssp_executable, gemmi_executable, run_capture  # noqa: E402

REPO = Path(__file__).resolve().parent.parent

# DSSP 4.6.1 has nine raw states. Preserve the existing HEC definition,
# including PPII -> C; unknown raw states are errors, never inferred coil.
_DSSP_TO_HEC = {"H": "H", "G": "H", "I": "H", "E": "E", "B": "E",
                "P": "C", "T": "C", "S": "C", " ": "C"}
_BIOTITE_TO_HEC = {"a": "H", "b": "E", "c": "C"}
_DSSP_HEADER = (
    "  #  RESIDUE AA STRUCTURE BP1 BP2  ACC     N-H-->O    O-->H-N    N-H-->O    O-->H-N"
    "    TCO  KAPPA ALPHA  PHI   PSI    X-CA   Y-CA   Z-CA"
)
_DSSP_TOTAL_SUFFIX = (
    " TOTAL NUMBER OF RESIDUES, NUMBER OF CHAINS, NUMBER OF SS-BRIDGES(TOTAL,INTRACHAIN,INTERCHAIN)"
    "                ."
)
_DSSP_BREAK_TAIL = (
    "             0   0    0      0, 0.0     0, 0.0     0, 0.0     0, 0.0"
    "   0.000 360.0 360.0 360.0 360.0    0.0    0.0    0.0"
)


def _fail(msg: str) -> None:
    """Exit non-zero with a clear oracle-status message (never a fabricated value)."""
    raise SystemExit(f"t15_ss_agreement: {msg}")


class DenominatorAdmissionError(SystemExit):
    """A completed assigner pair cannot supply the required common denominator."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"t15_ss_agreement: {message}")


# A residue is keyed on (chain, resnum, insertion-code) so that e.g. 10 and 10A
# are never conflated. Residue *name* is deliberately not part of the key: DSSP
# reports a one-letter code and biotite a three-letter name, so cross-checking
# names across the two formats is fragile; chain+num+icode uniquely locates the
# residue within one model, which is what the alignment needs.
ResKey = tuple[str, str, str]


_BUNDLE_RESULT_FIELDS = (
    "n_dssp",
    "n_biotite",
    "n_scored",
    "n_dropped",
    "n_agree",
    "fraction",
    "dssp_h",
    "dssp_e",
    "dssp_c",
    "dssp_ss_content",
)


def content_bound_bundle_ref(
    result: dict[str, Any],
    eval_id: str,
    input_sha256: str,
    normalized_sha256: str,
    gemmi_version: str,
    dssp_version: str,
    biotite_version: str,
    subject_ref: str | None = None,
) -> str:
    """Identify the coupled agreement/content result, not merely its EvalRun.

    An EvalRun id is routinely reused for more than one input (for example a
    candidate and deposited baseline).  Deriving the bundle id from that id
    alone lets rows from separate wrapper invocations look coupled.  Bind it to
    the input-file digest, every aggregate needed to reproduce both emitted
    measurements, and the concrete subject when supplied.  The digest is a
    required API input so non-CLI callers cannot silently fall back to an
    EvalRun-only identity.
    """
    payload = {
        "subject_ref": subject_ref,
        "input_sha256": input_sha256,
        "normalization_mode": "gemmi convert",
        "normalized_sha256": normalized_sha256,
        "gemmi_version": gemmi_version,
        "dssp_version": dssp_version,
        "biotite_version": biotite_version,
        **{field: result.get(field) for field in _BUNDLE_RESULT_FIELDS},
    }
    encoded = yaml.safe_dump(
        payload, sort_keys=True, allow_unicode=True
    ).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()[:16]
    return f"{eval_id}_T15_SS_{digest}"


def run_dssp_with_raw(
    model: Path, *, normalized_model: Path | None = None,
    execution_record: dict[str, Any] | None = None,
) -> tuple[dict[ResKey, str], bytes]:
    """Return collapsed assignments and the exact raw DSSP output bytes."""
    try:
        exe = dssp_executable()
    except FileNotFoundError as exc:
        _fail(str(exc))
    with tempfile.NamedTemporaryFile(suffix=".dssp", delete=False) as tmp:
        out_path = Path(tmp.name)
    normalised = normalized_model or _normalise_for_dssp(model)
    try:
        arguments = [exe, "--output-format", "dssp", str(normalised), str(out_path)]
        proc = run_capture(arguments)
        if execution_record is not None:
            execution_record.update({
                "argv": [str(value) for value in arguments],
                "returncode": proc.returncode,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
            })
        # `or`, not `and`. The two conditions are independent failures and neither
        # excuses the other: mkdssp can exit non-zero *after* writing a partial
        # residue table, and an `and` here accepted that truncated table as a
        # complete run -- `agreement()` then reported a "% concordant" over a short
        # denominator with nothing to say it was short (#117).
        if proc.returncode != 0 or not out_path.stat().st_size:
            _fail(f"mkdssp failed (exit {proc.returncode}, "
                  f"{out_path.stat().st_size} bytes written): "
                  f"{proc.stderr.strip() or proc.stdout.strip()}")
        raw_output = out_path.read_bytes()
        try:
            text = raw_output.decode("utf-8")
        except UnicodeDecodeError as exc:
            _fail(f"mkdssp output is not UTF-8 text: {exc}")
        return _parse_dssp(text), raw_output
    finally:
        out_path.unlink(missing_ok=True)
        if normalized_model is None and normalised != model:
            normalised.unlink(missing_ok=True)


def run_dssp(
    model: Path, *, normalized_model: Path | None = None
) -> dict[ResKey, str]:
    """Return {(chain, resnum, icode): HEC} from configured DSSP."""
    assignments, _raw_output = run_dssp_with_raw(
        model, normalized_model=normalized_model
    )
    return assignments


def measured_dssp_version() -> str:
    """Return version text measured from the configured DSSP executable."""
    try:
        exe = dssp_executable()
    except FileNotFoundError as exc:
        _fail(str(exc))
    proc = run_capture([exe, "--version"])
    lines = (proc.stdout + "\n" + proc.stderr).strip().splitlines()
    version = " | ".join(lines[:3])[:500]
    if proc.returncode != 0 or not version:
        _fail(
            f"mkdssp version probe failed (exit {proc.returncode}): "
            f"{version or 'no version output'}"
        )
    return version


def measured_gemmi_version() -> str:
    """Return version text measured from the configured normalization binary."""
    try:
        exe = gemmi_executable()
    except FileNotFoundError as exc:
        _fail(str(exc))
    assert exe is not None
    proc = run_capture([exe, "--version"])
    lines = (proc.stdout + "\n" + proc.stderr).strip().splitlines()
    version = " | ".join(lines[:3])[:500]
    if proc.returncode != 0 or not version:
        _fail(
            f"gemmi version probe failed (exit {proc.returncode}): "
            f"{version or 'no version output'}"
        )
    return version


def measured_biotite_version() -> str:
    """Return the installed biotite distribution version used by P-SEA."""
    try:
        return importlib.metadata.version("biotite")
    except importlib.metadata.PackageNotFoundError:
        _fail("biotite distribution metadata unavailable — install biotite")


def _normalise_for_dssp(
    model: Path, *, execution_record: dict[str, Any] | None = None
) -> Path:
    """Rewrite the model through `gemmi convert` so mkdssp will read it.

    mkdssp 4.x sniffs the input format and gets it wrong on PDB files downloaded
    from RCSB — it tries to parse them as mmCIF and dies with "This file does not
    seem to be an mmCIF file", followed by a cif-validator error naming a category
    from the entry's own header. It is not specific to one entry: 1UBQ, 12LO and
    every other RCSB `.pdb` tested fails, while the same coordinates rewritten by
    `gemmi convert` are accepted. This script previously only ever ran on a
    PHENIX-written file in `data/`, which is why the failure went unnoticed.

    Normalization is load-bearing for the reported denominator and assignment.
    Fail closed when gemmi is unavailable or conversion fails; silently switching
    to raw input would make otherwise identical wrapper invocations incomparable.
    """
    try:
        gemmi = gemmi_executable()
    except FileNotFoundError as exc:
        _fail(str(exc))
    assert gemmi is not None
    with tempfile.NamedTemporaryFile(suffix=".pdb", delete=False) as tmp:
        converted = Path(tmp.name)
    arguments = [gemmi, "convert", model, converted]
    proc = run_capture(arguments)
    if execution_record is not None:
        execution_record.update({
            "argv": [str(value) for value in arguments],
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        })
    if proc.returncode != 0 or not converted.stat().st_size:
        converted.unlink(missing_ok=True)
        _fail(
            f"gemmi convert failed (exit {proc.returncode}): "
            f"{proc.stderr.strip() or proc.stdout.strip() or 'no output'}"
        )
    return converted


def _parse_dssp(text: str) -> dict[ResKey, str]:
    """Admit complete DSSP 4.6.1 legacy records before collapsing their states.

    Grammar: PDB-REDO/dssp tag v4.6.1, libdssp/src/dssp-io.cpp:
    ResidueToDSSPLine and writeDSSP; nine-state enum in libdssp/include/dssp.hpp.
    Numeric overflow beyond the fixed fields and blank chains are explicitly
    unsupported, not omitted from the scientific denominator. This is syntax
    and declared-coverage admission, not authentication of tool execution.
    """
    lines = text.splitlines()
    headers = [i for i, line in enumerate(lines) if line == _DSSP_HEADER]
    if len(headers) != 1:
        _fail("require exactly one complete DSSP residue table header.")
    start = headers[0] + 1
    totals = [line for line in lines[:start - 1] if "TOTAL NUMBER OF RESIDUES" in line]
    if len(totals) != 1 or totals[0][17:] != _DSSP_TOTAL_SUFFIX:
        _fail("require exactly one valid DSSP declared residue total before the table.")

    def integer(field: str, line_number: int, *, signed: bool = False) -> int:
        if not re.fullmatch(r" *-?[0-9]+" if signed else r" *[0-9]+", field):
            _fail(f"DSSP line {line_number}: malformed decimal integer {field!r}.")
        value = int(field)
        if f"{value:{len(field)}d}" != field:
            _fail(f"DSSP line {line_number}: noncanonical/overflowed integer {field!r}.")
        return value

    total_line_number = lines.index(totals[0]) + 1
    declared = integer(totals[0][:5], total_line_number)
    for a, b in ((5, 8), (8, 11), (11, 14), (14, 17)):
        integer(totals[0][a:b], total_line_number)
    out: dict[ResKey, str] = {}
    serials: set[int] = set()
    for line_number, ln in enumerate(lines[start:], start + 1):
        if len(ln) != 136 or any(not 32 <= ord(char) <= 126 for char in ln):
            _fail(f"DSSP line {line_number}: incomplete, non-ASCII or unsupported-width record.")
        serial = integer(ln[:5], line_number)
        if serial < 1 or serial in serials:
            _fail(f"DSSP line {line_number}: invalid or duplicate record serial {serial}.")
        serials.add(serial)
        if ln[13] == "!":
            if ln[5:13] != " " * 8 or ln[14] not in " *" or ln[15:] != _DSSP_BREAK_TAIL:
                _fail(f"DSSP line {line_number}: malformed chain-break record.")
            continue
        resnum = str(integer(ln[5:10], line_number, signed=True))
        icode = ln[10].strip()  # insertion code column
        chain = ln[11].strip()
        if not chain:
            _fail(f"DSSP line {line_number}: blank-chain identity is unsupported; refusing to drop it.")
        ss = ln[16]
        if ss not in _DSSP_TO_HEC:
            _fail(f"DSSP line {line_number}: unknown secondary-structure state {ss!r}.")
        if (ln[12] != " " or ln[14:16] != "  " or not re.fullmatch(r"[A-Za-z]", ln[13])
                or ln[38] != " " or ln[83:85] != "  "
                or any(ln[index] != " " for index in (115, 122, 129))):
            _fail(f"DSSP line {line_number}: malformed residue fields or separators.")
        for index, allowed in ((17, " <>XP"), (18, " <>X3"), (19, " <>X4"),
                               (20, " <>X5"), (21, " S"), (22, " +-")):
            if ln[index] not in allowed:
                _fail(f"DSSP line {line_number}: malformed structure annotation at column {index + 1}.")
        if not re.fullmatch(r"[ A-Za-z]{2}", ln[23:25]) or not re.fullmatch(r"[ A-Z]", ln[33]):
            _fail(f"DSSP line {line_number}: malformed bridge/sheet label.")
        for a, b in ((25, 29), (29, 33), (34, 38)):
            integer(ln[a:b], line_number)
        for a in (39, 50, 61, 72):
            if not re.fullmatch(r" *-?[0-9]+, *-?[0-9]+\.[0-9]", ln[a:a + 11]):
                _fail(f"DSSP line {line_number}: malformed hydrogen-bond field.")
        for a, decimals in ((85, 3), (91, 1), (97, 1), (103, 1), (109, 1),
                            (116, 1), (123, 1), (130, 1)):
            if not re.fullmatch(rf" *-?[0-9]+\.[0-9]{{{decimals}}}", ln[a:a + 6]):
                _fail(f"DSSP line {line_number}: malformed angle/coordinate field.")
        key = (chain, resnum, icode)
        if key in out:
            _fail(f"DSSP line {line_number}: duplicate residue identity {key!r}.")
        out[key] = _DSSP_TO_HEC[ss]
    if len(out) != declared:
        _fail(f"DSSP declared {declared} residues but parsed {len(out)}; incomplete residue coverage.")
    return out


def run_biotite(model: Path) -> dict[ResKey, str]:
    """Return {(chain, resnum, icode): HEC} from biotite annotate_sse (per chain)."""
    try:
        import biotite.structure as struc
        import biotite.structure.io.pdb as pdb
    except ImportError:
        _fail("biotite not importable — install it (`pip install biotite`).")
    pdb_file = pdb.PDBFile.read(str(model))
    arr = pdb.get_structure(pdb_file, model=1)
    prot = arr[struc.filter_amino_acids(arr)]
    has_icode = "ins_code" in prot.get_annotation_categories()
    out: dict[ResKey, str] = {}
    for chain_id in sorted(set(prot.chain_id)):
        chain = prot[prot.chain_id == chain_id]
        sse = struc.annotate_sse(chain)  # one 'a'/'b'/'c' per residue, in order
        starts = struc.get_residue_starts(chain)  # first-atom index per residue, in order
        if len(sse) != len(starts):
            _fail(
                "biotite assignment/residue mismatch on chain "
                f"{chain_id!r}: {len(sse)} assignments for {len(starts)} residues; "
                "refusing to drop the chain from the agreement denominator."
            )
        for idx, code in zip(starts, sse):
            resnum = str(chain.res_id[idx])
            icode = str(chain.ins_code[idx]).strip() if has_icode else ""
            out[(chain_id, resnum, icode)] = _BIOTITE_TO_HEC.get(code, "C")
    return out


def agreement(a: dict[ResKey, str], b: dict[ResKey, str]) -> dict[str, Any]:
    """Three-state agreement over one exactly matched residue-key set.

    Scoring an intersection is unsafe here: dropping coil-rich or otherwise
    difficult residues can simultaneously inflate agreement and leave the DSSP
    content diagnostic on a different denominator.  The wrapper therefore treats any
    key-set mismatch as an unevaluable run rather than silently shortening it.
    """
    shared = sorted(set(a) & set(b))
    if not shared:
        raise DenominatorAdmissionError(
            "no_shared_residue_keys",
            "no residues in common between the two assigners — cannot compute agreement.",
        )
    dssp_only = sorted(set(a) - set(b))
    biotite_only = sorted(set(b) - set(a))
    if dssp_only or biotite_only:
        raise DenominatorAdmissionError(
            "unequal_residue_keys",
            "assigners scored different residue sets: "
            f"DSSP-only={len(dssp_only)}, biotite-only={len(biotite_only)}; "
            "T15 agreement and its DSSP H+E interpretability diagnostic require "
            "the same denominator."
        )
    matches = sum(1 for k in shared if a[k] == b[k])
    per_residue = [
        {"chain": c, "resnum": r, "icode": i, "dssp": a[k], "biotite": b[k], "agree": a[k] == b[k]}
        for k in shared
        for (c, r, i) in [k]
    ]
    dssp_counts = {state: sum(1 for value in a.values() if value == state) for state in "HEC"}
    return {
        "n_dssp": len(a),
        "n_biotite": len(b),
        "n_scored": len(shared),
        "n_dropped": 0,
        "n_agree": matches,
        "fraction": round(matches / len(shared), 4),
        "dssp_h": dssp_counts["H"],
        "dssp_e": dssp_counts["E"],
        "dssp_c": dssp_counts["C"],
        "dssp_ss_content": round((dssp_counts["H"] + dssp_counts["E"]) / len(a), 4),
        "per_residue": per_residue,
    }


def evidence_ref_for_path(destination: Path) -> tuple[Path, str]:
    """Resolve a new repository-local evidence path and its portable reference."""
    # Resolve would erase an existing dangling destination alias (#839).
    if destination.is_symlink():
        _fail(f"evidence already exists; refusing to overwrite: {destination}")
    resolved = destination.resolve()
    try:
        relative = resolved.relative_to(REPO.resolve())
    except ValueError:
        _fail(
            "--evidence-out must be inside the repository so emitted evidence_refs "
            f"remain portable: {resolved}"
        )
    if resolved.exists() or resolved.is_symlink():
        _fail(f"evidence already exists; refusing to overwrite: {resolved}")
    if resolved.suffix.casefold() != ".json":
        _fail(f"--evidence-out must name a .json file: {resolved}")
    return resolved, relative.as_posix()


def source_archive_provenance(
    archive: Path | None,
    member: str | None,
    source_bytes: bytes,
) -> tuple[str | None, str | None, str | None]:
    """Validate an optional repository-local ZIP member as the exact input source.

    A temporary extracted pathname is not durable provenance.  When an input came
    from a retained artifact archive, bind the evidence to both the portable
    archive path and the exact safe member name before any oracle work begins.
    """
    if (archive is None) != (member is None):
        _fail("--source-archive and --source-member must be supplied together")
    if archive is None or member is None:
        return None, None, None

    resolved = archive.resolve()
    try:
        archive_ref = resolved.relative_to(REPO.resolve()).as_posix()
    except ValueError:
        _fail(f"--source-archive must be inside the repository: {resolved}")
    member_path = PurePosixPath(member)
    if (
        not member
        or member_path.is_absolute()
        or "\\" in member
        or ".." in member_path.parts
        or member_path.as_posix() != member
    ):
        _fail(f"--source-member must be a safe canonical ZIP path: {member!r}")
    try:
        archive_bytes = resolved.read_bytes()
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as source_zip:
            matches = [info for info in source_zip.infolist() if info.filename == member]
            if len(matches) != 1:
                _fail(
                    f"source archive must contain exactly one member named {member!r}; "
                    f"found {len(matches)}"
                )
            info = matches[0]
            if info.is_dir():
                _fail(f"source archive member {member!r} is a directory")
            if info.file_size != len(source_bytes):
                _fail(
                    "source archive member size does not match the input model: "
                    f"{info.file_size} != {len(source_bytes)} bytes"
                )
            with source_zip.open(info) as member_stream:
                archived_bytes = member_stream.read(len(source_bytes) + 1)
    except (
        OSError,
        KeyError,
        RuntimeError,
        NotImplementedError,
        zipfile.BadZipFile,
    ) as exc:
        _fail(f"could not read source archive member {archive_ref}#{member}: {exc}")
    if archived_bytes != source_bytes:
        _fail(
            "input model bytes do not match the declared source archive member "
            f"{archive_ref}#{member}"
        )
    archive_sha256 = hashlib.sha256(archive_bytes).hexdigest()
    return archive_ref, member, archive_sha256


def subject_ref_for_source_archive(
    subject_ref: str | None,
    source_archive: str | None,
    source_member: str | None,
) -> str | None:
    """Derive or verify the artifact subject bound by archive provenance."""
    if source_archive is None or source_member is None:
        return subject_ref
    archive_name = PurePosixPath(source_archive).name
    artifact_id = (
        archive_name.removesuffix("_artifacts.zip")
        if archive_name.endswith("_artifacts.zip")
        else PurePosixPath(archive_name).stem
    )
    if not artifact_id:
        _fail(f"could not derive an artifact id from source archive {source_archive!r}")
    expected = f"artifact:{artifact_id}#{source_member}"
    if subject_ref is not None and subject_ref != expected:
        _fail(
            f"--subject-ref {subject_ref!r} does not identify the declared source "
            f"archive member; expected {expected!r}"
        )
    return expected


def build_evidence_bundle(
    *,
    bundle_ref: str,
    subject_ref: str | None,
    source_sha256: str,
    normalized_bytes: bytes,
    raw_dssp_bytes: bytes,
    dssp_assignments: dict[ResKey, str],
    biotite_assignments: dict[ResKey, str],
    result: dict[str, Any],
    gemmi_version: str,
    dssp_version: str,
    biotite_version: str,
    source_archive: str | None = None,
    source_member: str | None = None,
    source_archive_sha256: str | None = None,
) -> dict[str, Any]:
    """Build a self-contained, byte-replayable T15 evidence document."""
    normalized_sha256 = hashlib.sha256(normalized_bytes).hexdigest()
    raw_dssp_sha256 = hashlib.sha256(raw_dssp_bytes).hexdigest()
    keys = sorted(set(dssp_assignments) | set(biotite_assignments))
    assignments = [
        {
            "chain": chain,
            "resnum": resnum,
            "icode": icode,
            "dssp": dssp_assignments.get((chain, resnum, icode)),
            "biotite_psea": biotite_assignments.get((chain, resnum, icode)),
        }
        for chain, resnum, icode in keys
    ]
    aggregate = {
        field: result[field]
        for field in _BUNDLE_RESULT_FIELDS
    }
    evidence = {
        "evidence_format": "protstruct-review-t15-v1",
        "bundle_ref": bundle_ref,
        "subject_ref": subject_ref,
        "metric_definition_refs": [
            "T15_secondary_structure_agreement",
            "T15_secondary_structure_content",
        ],
        "source_sha256": source_sha256,
        "normalization": {
            "tool": "gemmi convert",
            "tool_version": gemmi_version,
            "sha256": normalized_sha256,
            "size_bytes": len(normalized_bytes),
            "encoding": "base64",
            "bytes_base64": base64.b64encode(normalized_bytes).decode("ascii"),
        },
        "dssp": {
            "tool": "DSSP",
            "tool_version": dssp_version,
            "raw_output_sha256": raw_dssp_sha256,
            "raw_output_size_bytes": len(raw_dssp_bytes),
            "raw_output_encoding": "base64",
            "raw_output_base64": base64.b64encode(raw_dssp_bytes).decode("ascii"),
        },
        "biotite_psea": {
            "tool": "biotite P-SEA",
            "tool_version": biotite_version,
        },
        "per_residue_assignments": assignments,
        "aggregate": aggregate,
    }
    if (
        source_archive is not None
        and source_member is not None
        and source_archive_sha256 is not None
    ):
        evidence["source_archive"] = source_archive
        evidence["source_member"] = source_member
        evidence["source_archive_sha256"] = source_archive_sha256
    return evidence


def build_failed_attempt_evidence(
    *,
    error: DenominatorAdmissionError,
    eval_id: str,
    subject_ref: str | None,
    source_bytes: bytes,
    normalized_bytes: bytes,
    raw_dssp_bytes: bytes,
    dssp_assignments: dict[ResKey, str],
    biotite_assignments: dict[ResKey, str],
    gemmi_version: str,
    dssp_version: str,
    biotite_version: str,
    normalization_execution: dict[str, Any],
    dssp_execution: dict[str, Any],
    source_archive: str | None,
    source_member: str | None,
    source_archive_sha256: str | None,
) -> dict[str, Any]:
    """Retain a rejected completed pair, never a shortened successful measurement."""
    def keys(values: set[ResKey]) -> list[dict[str, str]]:
        return [{"chain": c, "resnum": r, "icode": i} for c, r, i in sorted(values)]

    def stream(assignments: dict[ResKey, str]) -> list[dict[str, str]]:
        return [{"chain": c, "resnum": r, "icode": i, "state": assignments[c, r, i]}
                for c, r, i in sorted(assignments)]

    def retained(raw: bytes) -> dict[str, Any]:
        return {"sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw),
                "encoding": "base64", "bytes_base64": base64.b64encode(raw).decode("ascii")}

    a, b = set(dssp_assignments), set(biotite_assignments)
    evidence = {
        "evidence_format": "protstruct-review-t15-failed-attempt-v1",
        "attempt_status": "failed_denominator_admission",
        "catalog_task_ref": "T15",
        "eval_id": eval_id,
        "subject_ref": subject_ref,
        "measurements_emitted": False,
        "failure": {
            "stage": "residue_key_admission",
            "reason_code": error.reason_code,
            "message": str(error),
            "counts": {"n_dssp": len(a), "n_biotite": len(b), "n_shared": len(a & b),
                       "n_dssp_only": len(a - b), "n_biotite_only": len(b - a)},
            "shared_keys": keys(a & b),
            "dssp_only_keys": keys(a - b),
            "biotite_only_keys": keys(b - a),
        },
        "source": retained(source_bytes),
        "normalization": {"tool": "gemmi convert", "tool_version": gemmi_version,
                          **retained(normalized_bytes), "execution": normalization_execution},
        "dssp": {"tool": "DSSP", "tool_version": dssp_version,
                 "raw_output": retained(raw_dssp_bytes), "execution": dssp_execution,
                 "assignments": stream(dssp_assignments)},
        "biotite_psea": {"tool": "biotite P-SEA", "tool_version": biotite_version,
                         "execution": {"mode": "in_process", "status": "returned_assignments"},
                         "assignments": stream(biotite_assignments)},
        "provenance_limits": (
            "Normalization/DSSP argv, returncode and captured text are recorded at execution. "
            "No subprocess PID, timing or complete environment was recorded by these helpers. "
            "Biotite read the retained original source; DSSP read the retained normalized bytes. "
            "This failed attempt emits no agreement/content scalar or quality verdict. "
            "Earlier-phase failures are outside this completed-pair retention guarantee."
        ),
    }
    if source_archive is not None:
        evidence.update(source_archive=source_archive, source_member=source_member,
                        source_archive_sha256=source_archive_sha256)
    return evidence


def write_evidence_bundle_no_overwrite(
    destination: Path, payload: dict[str, Any]
) -> None:
    """Publish one JSON evidence bundle atomically without replacing any file."""
    if destination.exists() or destination.is_symlink():
        _fail(f"evidence already exists; refusing to overwrite: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode("utf-8")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        # A hard link is an atomic publish that fails if a concurrent writer won
        # the destination; Path.replace() would silently destroy retained evidence.
        os.link(temporary, destination)
    except FileExistsError:
        _fail(f"evidence already exists; refusing to overwrite: {destination}")
    except OSError as exc:
        _fail(f"could not publish evidence bundle {destination}: {exc}")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def render_yaml(
    result: dict[str, Any],
    eval_id: str,
    subject_ref: str | None = None,
    *,
    input_sha256: str,
    normalized_sha256: str,
    dssp_version: str,
    gemmi_version: str,
    biotite_version: str,
    evidence_ref: str,
) -> str:
    """Emit pasteable agreement and DSSP-content EvaluationMeasurement rows."""
    bundle_ref = content_bound_bundle_ref(
        result,
        eval_id,
        input_sha256,
        normalized_sha256,
        gemmi_version,
        dssp_version,
        biotite_version,
        subject_ref,
    )
    clears_content_precondition = result["dssp_ss_content"] >= 0.20
    if clears_content_precondition:
        interpretation_note = (
            "DSSP H+E content clears the provisional 0.20 interpretability "
            "precondition, so the paired agreement has useful interpretive range; "
            "this is not a model-quality verdict."
        )
    else:
        interpretation_note = (
            "DSSP H+E content falls below the provisional 0.20 interpretability "
            "precondition, so coil/coil agreement may dominate and the paired "
            "agreement is weakly interpretable; this is not a model-quality verdict."
        )
    agreement_measurement = {
        "id": f"{bundle_ref}_M_agreement",
        "catalog_task_ref": "T15",
        "stage": "final",
        "scope": "complex",
        "metric_definition_ref": "T15_secondary_structure_agreement",
        "oracle_tool_ref": "DSSP + biotite P-SEA",
        "oracle_family": "non_cctbx",
        "bundle_ref": bundle_ref,
        "evidence_refs": [evidence_ref],
        "oracle_measure": {"value_numeric": result["fraction"], "unit": "fraction"},
        "pass_status": "informational",
        "notes": (
            f"three-state (H/E/C) agreement between two independent non-cctbx assigners, "
            f"DSSP (H-bond) and biotite P-SEA (Cα geometry): "
            f"configured DSSP reported {dssp_version}; "
            f"biotite reported {biotite_version}; "
            f"DSSP input was normalized with gemmi convert ({gemmi_version}), "
            f"normalized SHA-256 {normalized_sha256}; biotite P-SEA read the "
            f"original source bytes, SHA-256 {input_sha256}; "
            f"{result['n_agree']}/{result['n_scored']} concordant over residues scored by both "
            f"(DSSP {result['n_dssp']}, biotite {result['n_biotite']}, "
            f"{result['n_dropped']} scored by only one and excluded). "
            f"{interpretation_note}"
        ),
    }
    content_measurement = {
        "id": f"{bundle_ref}_M_content",
        "catalog_task_ref": "T15",
        "stage": "final",
        "scope": "complex",
        "metric_definition_ref": "T15_secondary_structure_content",
        "oracle_tool_ref": "DSSP",
        "oracle_family": "non_cctbx",
        "bundle_ref": bundle_ref,
        "evidence_refs": [evidence_ref],
        "oracle_measure": {
            "value_numeric": result["dssp_ss_content"],
            "unit": "fraction",
        },
        "pass_status": "informational",
        "notes": (
            f"DSSP H+E content over all DSSP-scored residues: "
            f"({result['dssp_h']} H + {result['dssp_e']} E) / {result['n_dssp']} = "
            f"{result['dssp_ss_content']:.4f}; {result['dssp_c']} residues are coil. "
            f"Configured DSSP reported {dssp_version}. "
            f"Biotite reported {biotite_version}. "
            f"DSSP input was normalized with gemmi convert ({gemmi_version}), "
            f"normalized SHA-256 {normalized_sha256}; biotite P-SEA read the "
            f"original source bytes, SHA-256 {input_sha256}. "
            f"{interpretation_note}"
        ),
    }
    if subject_ref is not None:
        agreement_measurement["subject_ref"] = subject_ref
        content_measurement["subject_ref"] = subject_ref
    return yaml.safe_dump(
        [agreement_measurement, content_measurement],
        sort_keys=False,
        allow_unicode=True,
        width=100,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("model", type=Path, help="protein model (PDB)")
    ap.add_argument("--eval-id", default="EVAL_T15", help="eval id prefix for the emitted row")
    ap.add_argument(
        "--subject-ref",
        default=None,
        help=(
            "stable identifier for the concrete model; with --source-archive it "
            "must match (or is derived as) artifact:<archive-id>#<member>"
        ),
    )
    ap.add_argument(
        "--evidence-out",
        type=Path,
        required=True,
        help=(
            "new repository-local .json path for retained normalized input, raw DSSP "
            "output, assignments, hashes, and tool versions (never overwritten)"
        ),
    )
    ap.add_argument(
        "--source-archive",
        type=Path,
        help="repository-local ZIP containing the exact input model",
    )
    ap.add_argument(
        "--source-member",
        help="canonical member path whose bytes must exactly match the input model",
    )
    ap.add_argument("--per-residue", action="store_true", help="also print the per-residue table")
    args = ap.parse_args(argv)

    if not args.model.exists():
        _fail(f"model not found: {args.model}")
    evidence_path, evidence_ref = evidence_ref_for_path(args.evidence_out)
    source_bytes_before = args.model.read_bytes()
    input_sha256 = hashlib.sha256(source_bytes_before).hexdigest()
    source_archive, source_member, source_archive_sha256 = source_archive_provenance(
        args.source_archive,
        args.source_member,
        source_bytes_before,
    )
    subject_ref = subject_ref_for_source_archive(
        args.subject_ref, source_archive, source_member
    )

    dssp_version = measured_dssp_version()
    gemmi_version = measured_gemmi_version()
    biotite_version = measured_biotite_version()
    normalization_execution: dict[str, Any] = {}
    dssp_execution: dict[str, Any] = {}
    normalized_model = _normalise_for_dssp(args.model, execution_record=normalization_execution)
    try:
        normalized_bytes = normalized_model.read_bytes()
        normalized_sha256 = hashlib.sha256(normalized_bytes).hexdigest()
        dssp, raw_dssp_bytes = run_dssp_with_raw(
            args.model, normalized_model=normalized_model, execution_record=dssp_execution
        )
        try:
            normalized_after = normalized_model.read_bytes()
        except OSError as error:
            _fail(f"normalized model unavailable after DSSP; refusing to emit: {error}")
        if normalized_after != normalized_bytes:
            _fail("normalized model changed while DSSP was running; refusing to emit")
    finally:
        if normalized_model != args.model:
            normalized_model.unlink(missing_ok=True)
    bio = run_biotite(args.model)
    if args.model.read_bytes() != source_bytes_before:
        _fail(f"model changed while T15 was running; refusing to emit: {args.model}")
    try:
        result = agreement(dssp, bio)
    except DenominatorAdmissionError as error:
        failed_evidence = build_failed_attempt_evidence(
            error=error, eval_id=args.eval_id, subject_ref=subject_ref,
            source_bytes=source_bytes_before, normalized_bytes=normalized_bytes,
            raw_dssp_bytes=raw_dssp_bytes, dssp_assignments=dssp, biotite_assignments=bio,
            gemmi_version=gemmi_version, dssp_version=dssp_version, biotite_version=biotite_version,
            normalization_execution=normalization_execution, dssp_execution=dssp_execution,
            source_archive=source_archive, source_member=source_member,
            source_archive_sha256=source_archive_sha256,
        )
        write_evidence_bundle_no_overwrite(evidence_path, failed_evidence)
        print(f"t15_ss_agreement: failed-attempt evidence retained: {evidence_ref}", file=sys.stderr)
        raise

    bundle_ref = content_bound_bundle_ref(
        result,
        args.eval_id,
        input_sha256,
        normalized_sha256,
        gemmi_version,
        dssp_version,
        biotite_version,
        subject_ref,
    )
    rendered = render_yaml(
        result,
        args.eval_id,
        subject_ref,
        input_sha256=input_sha256,
        normalized_sha256=normalized_sha256,
        dssp_version=dssp_version,
        gemmi_version=gemmi_version,
        biotite_version=biotite_version,
        evidence_ref=evidence_ref,
    )
    evidence = build_evidence_bundle(
        bundle_ref=bundle_ref,
        subject_ref=subject_ref,
        source_sha256=input_sha256,
        normalized_bytes=normalized_bytes,
        raw_dssp_bytes=raw_dssp_bytes,
        dssp_assignments=dssp,
        biotite_assignments=bio,
        result=result,
        gemmi_version=gemmi_version,
        dssp_version=dssp_version,
        biotite_version=biotite_version,
        source_archive=source_archive,
        source_member=source_member,
        source_archive_sha256=source_archive_sha256,
    )
    write_evidence_bundle_no_overwrite(evidence_path, evidence)
    sys.stdout.write(rendered)
    if args.per_residue:
        print("# chain resnum icode dssp biotite agree")
        for r in result["per_residue"]:
            print(f"#  {r['chain']:>2} {r['resnum']:>5} {r['icode'] or '-':>1} "
                  f"{r['dssp']}   {r['biotite']}    {r['agree']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
