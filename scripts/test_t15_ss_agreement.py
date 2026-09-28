#!/usr/bin/env python3
"""Unit and retained-evidence tests for ``t15_ss_agreement``.

The ordinary unit fixtures mock external oracles.  The committed 1SAR guard
always replays retained bytes and arithmetic, and conditionally reruns the exact
evidence-producing Python P-SEA version; it never invokes mkdssp or gemmi.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import importlib.metadata
import io
import json
import sys
import tempfile
import warnings
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import t15_ss_agreement as t15  # noqa: E402
import toolchain  # noqa: E402


GEMMI_VERSION = "gemmi version 0.7.5"
BIOTITE_VERSION = "1.7.1"
NORMALIZED_SHA = "c" * 64


def _check(cond: bool, msg: str) -> None:
    if not cond:
        print(f"FAIL  {msg}")
        raise SystemExit(1)
    print(f"PASS  {msg}")


# Full synthetic records following the v4.6.1 upstream formatter, independent
# of the production parser constants. Frozen 1SAR bytes are separately replayed.
_RAW_HEADER = (
    "  #  RESIDUE AA STRUCTURE BP1 BP2  ACC     N-H-->O    O-->H-N    N-H-->O    O-->H-N"
    "    TCO  KAPPA ALPHA  PHI   PSI    X-CA   Y-CA   Z-CA"
)
_RAW_TOTAL_SUFFIX = (
    " TOTAL NUMBER OF RESIDUES, NUMBER OF CHAINS, NUMBER OF SS-BRIDGES(TOTAL,INTRACHAIN,INTERCHAIN)"
    "                ."
)


def _dssp_row(serial=1, chain="A", resnum=1, icode="", state="H", aa="A"):
    row = list(" " * 136)
    row[:5], row[5:10] = f"{serial:5d}", f"{int(resnum):5d}"
    row[10], row[11], row[13], row[16] = icode or " ", chain, aa, state
    for a, b in ((25, 29), (29, 33), (34, 38)):
        row[a:b] = f"{0:4d}"
    for a in (39, 50, 61, 72):
        row[a:a + 11] = f"{'0, 0.0':>11s}"
    row[85:91] = f"{0:6.3f}"
    for a in (91, 97, 103, 109, 116, 123, 130):
        row[a:a + 6] = f"{0:6.1f}"
    return "".join(row)


def _dssp_break(serial=2, marker="*"):
    return (f"{serial:5d}        !{marker}             0   0    0"
            "      0, 0.0     0, 0.0     0, 0.0     0, 0.0"
            "   0.000 360.0 360.0 360.0 360.0    0.0    0.0    0.0")


def _dssp_text(rows, declared=None):
    if declared is None:
        declared = sum(row[13] != "!" for row in rows)
    total = f"{declared:5d}{1:3d}{0:3d}{0:3d}{0:3d}" + _RAW_TOTAL_SUFFIX
    return "\n".join([total, _RAW_HEADER, *rows]) + "\n"


_DSSP_SAMPLE = _dssp_text([
    _dssp_row(1, resnum=1, state=" ", aa="D"),
    _dssp_row(2, resnum=2, state="E", aa="V"),
    _dssp_row(3, resnum=8, state="H", aa="L"),
])


def test_parse_dssp() -> None:
    parsed = t15._parse_dssp(_DSSP_SAMPLE)
    _check(parsed == {("A", "1", ""): "C", ("A", "2", ""): "E", ("A", "8", ""): "H"},
           f"_parse_dssp collapses to HEC keyed on (chain,resnum,icode) (got {parsed})")


def _expect_dssp_failure(raw, message):
    try:
        t15._parse_dssp(raw)
    except SystemExit as error:
        assert error.code != 0 and message in str(error), str(error)
        assert not isinstance(error, t15.DenominatorAdmissionError)
        return
    raise AssertionError(f"malformed DSSP accepted: expected {message!r}")


def test_dssp_nine_states_signed_identity_and_breaks() -> None:
    states = {"H": "H", "G": "H", "I": "H", "E": "E", "B": "E",
              "P": "C", "T": "C", "S": "C", " ": "C"}
    rows = [_dssp_row(n, resnum=n, state=state, aa="a")
            for n, state in enumerate(states, 1)]
    assert t15._parse_dssp(_dssp_text(rows)) == {
        ("A", str(n), ""): value for n, value in enumerate(states.values(), 1)
    }
    rows = [_dssp_row(1, resnum=-2), _dssp_break(2, " "),
            _dssp_row(3, resnum=-2, icode="A", state="P"), _dssp_break(4, "*"),
            _dssp_row(5, chain="B", resnum=0, state=" ")]
    assert t15._parse_dssp(_dssp_text(rows).replace("\n", "\r\n")) == {
        ("A", "-2", ""): "H", ("A", "-2", "A"): "C", ("B", "0", ""): "C",
    }
    assert t15._parse_dssp(_dssp_text([], declared=0)) == {}
    _check(True, "nine raw DSSP states, signed/insertion identities and both complete break forms")


def test_dssp_rejects_unknown_states_and_incomplete_rows() -> None:
    for state in ("Z", "C", "-", "*", "h", "?"):
        _expect_dssp_failure(_dssp_text([_dssp_row(state=state)]), "unknown secondary-structure")
    row = _dssp_row()
    for bad in (row[:16], row[:17], row[:135], row + " ", "trailer", "", " " * 136,
                row[:20] + "\t" + row[21:], row[:20] + "é" + row[21:]):
        _expect_dssp_failure(_dssp_text([row]) + bad + "\n", "DSSP line")
    _check(True, "unknown raw codes and every malformed/truncated residue row fail explicitly")


def test_dssp_rejects_bad_identity_and_duplicate_records() -> None:
    row = _dssp_row()
    for number in (" ABCD", "  1.0", "   +1", " 0001", "   -0", "1    "):
        _expect_dssp_failure(_dssp_text([row[:5] + number + row[10:]]), "integer")
    _expect_dssp_failure(_dssp_text([_dssp_row(chain=" ")]), "blank-chain identity is unsupported")
    _expect_dssp_failure(_dssp_text([row, _dssp_row(2, state="E")]), "duplicate residue identity")
    _expect_dssp_failure(_dssp_text([row, _dssp_row(2, state="E")], declared=1),
                         "duplicate residue identity")
    _expect_dssp_failure(_dssp_text([row, _dssp_row(1, resnum=2)]), "duplicate record serial")
    _expect_dssp_failure(_dssp_text([_dssp_row(0)]), "record serial")
    _check(True, "decimal identity, nonblank chain, unique serial and unique full residue key required")


def test_dssp_validates_full_fields_and_exact_break_grammar() -> None:
    row = _dssp_row()
    mutations = {
        12: "X", 13: "?", 14: "X", 17: "Z", 18: "P", 19: "3", 20: "4", 21: "X",
        22: "X", 23: "?", 25: "X", 29: "X", 33: "a", 34: "X", 38: "X", 39: "X",
        50: "X", 61: "X", 72: "X", 83: "X", 85: "X", 91: "X", 97: "X",
        103: "X", 109: "X", 115: "X", 116: "X", 122: "X", 123: "X", 129: "X", 130: "X",
    }
    for position, char in mutations.items():
        _expect_dssp_failure(_dssp_text([row[:position] + char + row[position + 1:]]), "DSSP line")
    breaker = _dssp_break()
    for position, char in ((5, "1"), (11, "A"), (14, "X"), (16, "H"), (100, "1")):
        bad = breaker[:position] + char + breaker[position + 1:]
        _expect_dssp_failure(_dssp_text([row, bad]), "malformed chain-break")
    _check(True, "complete numeric/annotation fields and exact break records are required")


def test_dssp_header_and_declared_total_coverage() -> None:
    valid = _dssp_text([_dssp_row()])
    for malformed in (valid.replace(_RAW_HEADER, "  #  RESIDUE AA STRUCTURE"),
                      valid + _RAW_HEADER + "\n", valid.replace(_RAW_HEADER, "")):
        _expect_dssp_failure(malformed, "table header")
    total = valid.splitlines()[0]
    for malformed in (valid[len(total) + 1:], total + "\n" + valid,
                      valid.replace(_RAW_TOTAL_SUFFIX, _RAW_TOTAL_SUFFIX[:-1]),
                      valid.replace(total, " ABCD" + total[5:]),
                      valid.replace(total, total[:5] + "  X" + total[8:])):
        _expect_dssp_failure(malformed, "DSSP")
    for declared in (0, 2):
        _expect_dssp_failure(_dssp_text([_dssp_row()], declared), "incomplete residue coverage")
    _expect_dssp_failure(_dssp_text([], declared=1), "incomplete residue coverage")
    _check(True, "one full header/declared total and exact residue-count coverage are mandatory")


def test_dssp_uses_toolchain_override_and_runner() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        configured = root / "configured-mkdssp"
        configured.write_text("#!/bin/sh\nexit 0\n")
        configured.chmod(0o755)
        model = root / "model.pdb"
        model.write_text("MODEL\nEND\n")
        seen: list[list[object]] = []

        def fake_run_capture(arguments: list[object]) -> SimpleNamespace:
            seen.append(arguments)
            Path(arguments[-1]).write_text(_DSSP_SAMPLE)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        with (
            mock.patch.object(toolchain, "DSSP", configured),
            mock.patch.object(t15, "run_capture", side_effect=fake_run_capture),
            mock.patch.object(t15, "_normalise_for_dssp", return_value=model),
        ):
            resolved = t15.dssp_executable()
            parsed = t15.run_dssp(model)

        _check(resolved == configured.resolve(),
               "PROTSTRUCT_DSSP-configured executable is resolved through toolchain")
        _check(bool(seen) and Path(seen[0][0]) == configured.resolve(),
               "run_dssp executes the toolchain-resolved DSSP path through run_capture")
        _check(parsed[("A", "2", "")] == "E",
               "run_dssp parses output produced by the shared runner")

        with (
            mock.patch.object(toolchain, "DSSP", configured),
            mock.patch.object(
                t15,
                "run_capture",
                return_value=SimpleNamespace(
                    returncode=0,
                    stdout="mkdssp version 4.6.1\n",
                    stderr="",
                ),
            ) as version_run,
        ):
            version = t15.measured_dssp_version()
        _check(version == "mkdssp version 4.6.1",
               "configured DSSP version is measured from command output")
        _check(version_run.call_args.args[0] == [configured.resolve(), "--version"],
               "DSSP version probe uses the toolchain-resolved executable")

        with (
            mock.patch.object(toolchain, "GEMMI", configured),
            mock.patch.object(
                t15,
                "run_capture",
                return_value=SimpleNamespace(
                    returncode=0,
                    stdout=GEMMI_VERSION + "\n",
                    stderr="",
                ),
            ) as gemmi_version_run,
        ):
            gemmi_version = t15.measured_gemmi_version()
        _check(gemmi_version == GEMMI_VERSION,
               "configured gemmi version is measured from command output")
        _check(gemmi_version_run.call_args.args[0] == [configured.resolve(), "--version"],
               "gemmi version probe uses the toolchain-resolved executable")


def test_collapse_maps() -> None:
    _check(t15._DSSP_TO_HEC.get("G") == "H" and t15._DSSP_TO_HEC.get("B") == "E",
           "DSSP 3-10 helix -> H and bridge -> E")
    _check(t15._DSSP_TO_HEC["T"] == "C" and t15._DSSP_TO_HEC["P"] == "C",
           "DSSP turn and PPII preserve their explicit existing C collapse")
    _check(t15._BIOTITE_TO_HEC == {"a": "H", "b": "E", "c": "C"}, "biotite a/b/c -> HEC")


def test_agreement() -> None:
    a = {("A", "1", ""): "C", ("A", "2", ""): "E", ("A", "3", ""): "H", ("A", "4", ""): "H"}
    b = {("A", "1", ""): "C", ("A", "2", ""): "E", ("A", "3", ""): "C", ("A", "4", ""): "H"}
    r = t15.agreement(a, b)
    _check(r["n_scored"] == 4, f"agreement scores the complete matched set (got {r['n_scored']})")
    _check(r["n_agree"] == 3 and r["fraction"] == 0.75,
           f"agreement fraction = 3/4 (got {r['fraction']})")
    _check(r["n_dssp"] == 4 and r["n_biotite"] == 4 and r["n_dropped"] == 0,
           f"per-assigner counts prove no dropped residues (got dssp={r['n_dssp']} "
           f"biotite={r['n_biotite']} dropped={r['n_dropped']})")
    _check(r["dssp_ss_content"] == 0.75,
           f"DSSP content uses all DSSP rows, not the shared denominator (got {r['dssp_ss_content']})")


def test_mismatched_residue_sets_fail() -> None:
    dssp = {("A", str(i), ""): ("H" if i <= 30 else "C") for i in range(1, 101)}
    biotite = {("A", str(i), ""): "C" for i in range(91, 101)}
    try:
        t15.agreement(dssp, biotite)
    except SystemExit as exc:
        message = str(exc)
    else:
        message = ""
    _check(
        "different residue sets" in message and "DSSP-only=90" in message,
        "a tiny biased intersection is unevaluable instead of agreement=1.0/content=0.30",
    )


def test_content_detects_degenerate_agreement() -> None:
    coil = {("A", str(i), ""): "C" for i in range(1, 5)}
    r = t15.agreement(coil, coil)
    _check(r["fraction"] == 1.0 and r["dssp_ss_content"] == 0.0,
           "perfect all-coil agreement retains zero H+E content")


def test_render_emits_agreement_and_content() -> None:
    a = {("A", "1", ""): "H", ("A", "2", ""): "E", ("A", "3", ""): "C"}
    rows = yaml.safe_load(
        t15.render_yaml(
            t15.agreement(a, a), "EVAL_test", input_sha256="a" * 64,
            dssp_version="mkdssp version 4.6.1",
            normalized_sha256=NORMALIZED_SHA, gemmi_version=GEMMI_VERSION,
            biotite_version=BIOTITE_VERSION,
            evidence_ref="data/evidence/t15-test.json",
        )
    )
    by_metric = {row["metric_definition_ref"]: row for row in rows}
    _check(set(by_metric) == {
        "T15_secondary_structure_agreement", "T15_secondary_structure_content"
    }, "YAML carries both T15 scalar metrics")
    _check(by_metric["T15_secondary_structure_agreement"]["oracle_tool_ref"] ==
           "DSSP + biotite P-SEA", "agreement row preserves paired-tool provenance")
    _check(by_metric["T15_secondary_structure_content"]["oracle_tool_ref"] == "DSSP",
           "content row identifies DSSP as its sole source")
    _check(by_metric["T15_secondary_structure_agreement"]["pass_status"] == "informational",
           "oracle-pair agreement is explicitly non-gradeable")
    _check(by_metric["T15_secondary_structure_content"]["pass_status"] == "informational" and
           "pass_criterion" not in by_metric["T15_secondary_structure_content"],
           "content row is an informational interpretability diagnostic, not a grade")
    _check(all("pass_criterion" not in row for row in rows),
           "neither non-gradeable T15 row carries a pass criterion")
    _check(all(row["oracle_measure"].get("unit") == "fraction" for row in rows),
            "both T15 fractions declare their unit")
    _check(len({row.get("bundle_ref") for row in rows}) == 1 and
           rows[0].get("bundle_ref", "").startswith("EVAL_test_T15_SS_"),
           "agreement and content rows carry one content-bound invocation bundle")
    _check(all(row.get("evidence_refs") == ["data/evidence/t15-test.json"]
               for row in rows),
           "both T15 rows cite the same retained evidence bundle")
    _check(all("scope_selector" not in row for row in rows),
           "complex-scoped rows do not overload scope_selector with provenance")

    other = {("A", str(i), ""): ("H" if i == 1 else "C") for i in range(1, 4)}
    other_rows = yaml.safe_load(
        t15.render_yaml(
            t15.agreement(other, other), "EVAL_test", input_sha256="a" * 64,
            dssp_version="mkdssp version 4.6.1",
            normalized_sha256=NORMALIZED_SHA, gemmi_version=GEMMI_VERSION,
            biotite_version=BIOTITE_VERSION,
            evidence_ref="data/evidence/t15-test.json",
        )
    )
    _check(
        rows[0]["bundle_ref"] != other_rows[0]["bundle_ref"],
        "separate results using the same EvalRun id cannot share a bundle identity",
    )
    _check(
        {row["id"] for row in rows}.isdisjoint(row["id"] for row in other_rows),
        "separate results using the same EvalRun id cannot share measurement ids",
    )
    digest_a_rows = yaml.safe_load(
        t15.render_yaml(
            t15.agreement(a, a), "EVAL_test", input_sha256="a" * 64,
            dssp_version="mkdssp version 4.6.1",
            normalized_sha256=NORMALIZED_SHA, gemmi_version=GEMMI_VERSION,
            biotite_version=BIOTITE_VERSION,
            evidence_ref="data/evidence/t15-test.json",
        )
    )
    digest_b_rows = yaml.safe_load(
        t15.render_yaml(
            t15.agreement(a, a), "EVAL_test", input_sha256="b" * 64,
            dssp_version="mkdssp version 4.6.1",
            normalized_sha256=NORMALIZED_SHA, gemmi_version=GEMMI_VERSION,
            biotite_version=BIOTITE_VERSION,
            evidence_ref="data/evidence/t15-test.json",
        )
    )
    _check(
        digest_a_rows[0]["bundle_ref"] != digest_b_rows[0]["bundle_ref"],
        "identical aggregate results from different input bytes cannot share a bundle",
    )
    _check(
        {row["id"] for row in digest_a_rows}.isdisjoint(
            row["id"] for row in digest_b_rows
        ),
        "different input bytes cannot reuse T15 measurement ids",
    )
    _check(
        all("mkdssp version 4.6.1" in row["notes"] for row in rows),
        "both T15 rows retain the measured DSSP version",
    )
    _check(
        all(
            GEMMI_VERSION in row["notes"]
            and BIOTITE_VERSION in row["notes"]
            and NORMALIZED_SHA in row["notes"]
            for row in rows
        ),
        "both T15 rows retain tool versions and normalized-byte digest",
    )

    coil = {("A", str(i), ""): "C" for i in range(1, 5)}
    coil_rows = yaml.safe_load(
        t15.render_yaml(
            t15.agreement(coil, coil), "EVAL_coil", input_sha256="d" * 64,
            normalized_sha256="e" * 64,
            dssp_version="mkdssp version 4.6.1", gemmi_version=GEMMI_VERSION,
            biotite_version=BIOTITE_VERSION,
            evidence_ref="data/evidence/t15-coil.json",
        )
    )
    coil_content = next(
        row for row in coil_rows
        if row["metric_definition_ref"] == "T15_secondary_structure_content"
    )
    coil_agreement = next(
        row for row in coil_rows
        if row["metric_definition_ref"] == "T15_secondary_structure_agreement"
    )
    _check(coil_content["pass_status"] == "informational" and
           "pass_criterion" not in coil_content,
           "all-coil content remains informational rather than failing model quality")
    _check(all("falls below the provisional 0.20" in row["notes"]
               and "not a model-quality verdict" in row["notes"]
               for row in (coil_content, coil_agreement)),
           "low content flags weak agreement interpretation without a quality verdict")


def test_main_retains_complete_evidence_and_links_rows() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        model = root / "model.pdb"
        model_bytes = b"MODEL\nATOM source\nEND\n"
        normalized_bytes = b"MODEL\nATOM normalized\nEND\n"
        raw_dssp_bytes = _DSSP_SAMPLE.encode("utf-8")
        model.write_bytes(model_bytes)
        source_archive = root / "data/artifact.zip"
        source_archive.parent.mkdir(parents=True)
        with zipfile.ZipFile(source_archive, "w") as source_zip:
            source_zip.writestr("data/model.pdb", model_bytes)
        normalized = root / ".normalized.pdb"
        evidence_path = root / "data/evidence/t15.json"
        dssp = {
            ("A", "1", ""): "C",
            ("A", "2", ""): "E",
            ("A", "8", ""): "H",
        }
        biotite = {
            ("A", "1", ""): "C",
            ("A", "2", ""): "E",
            ("A", "8", ""): "C",
        }

        def fake_normalize(_model: Path, **_kwargs) -> Path:
            normalized.write_bytes(normalized_bytes)
            return normalized

        stdout = io.StringIO()
        with (
            mock.patch.object(t15, "REPO", root),
            mock.patch.object(t15, "measured_dssp_version", return_value="mkdssp 4.6.1"),
            mock.patch.object(t15, "measured_gemmi_version", return_value=GEMMI_VERSION),
            mock.patch.object(t15, "measured_biotite_version", return_value=BIOTITE_VERSION),
            mock.patch.object(t15, "_normalise_for_dssp", side_effect=fake_normalize),
            mock.patch.object(
                t15, "run_dssp_with_raw", return_value=(dssp, raw_dssp_bytes)
            ),
            mock.patch.object(t15, "run_biotite", return_value=biotite),
            contextlib.redirect_stdout(stdout),
        ):
            rc = t15.main([
                str(model),
                "--eval-id", "EVAL_evidence",
                "--evidence-out", str(evidence_path),
                "--source-archive", str(source_archive),
                "--source-member", "data/model.pdb",
            ])

        _check(rc == 0 and evidence_path.is_file(),
               "main publishes one retained T15 evidence bundle")
        _check(not normalized.exists(),
               "transient normalized path is removed after its exact bytes are retained")
        evidence = json.loads(evidence_path.read_text())
        rows = yaml.safe_load(stdout.getvalue())
        evidence_ref = "data/evidence/t15.json"
        _check(
            all(row["evidence_refs"] == [evidence_ref] for row in rows)
            and {row["bundle_ref"] for row in rows} == {evidence["bundle_ref"]},
            "both rows link the exact retained bundle and share its bundle identity",
        )
        _check(
            evidence["source_sha256"] == hashlib.sha256(model_bytes).hexdigest()
            and evidence["normalization"]["sha256"]
            == hashlib.sha256(normalized_bytes).hexdigest()
            and base64.b64decode(evidence["normalization"]["bytes_base64"])
            == normalized_bytes,
            "evidence binds the source hash and retains exact normalized input bytes",
        )
        _check(
            evidence["source_archive"] == "data/artifact.zip"
            and evidence["source_member"] == "data/model.pdb",
            "evidence binds the portable source archive and exact member",
        )
        _check(
            evidence["subject_ref"] == "artifact:artifact#data/model.pdb"
            and all(
                row["subject_ref"] == evidence["subject_ref"] for row in rows
            ),
            "archive provenance derives one subject for evidence and measurements",
        )
        _check(
            evidence["source_archive_sha256"]
            == hashlib.sha256(source_archive.read_bytes()).hexdigest(),
            "evidence binds the complete source archive bytes",
        )
        _check(
            evidence["dssp"]["raw_output_sha256"]
            == hashlib.sha256(raw_dssp_bytes).hexdigest()
            and base64.b64decode(evidence["dssp"]["raw_output_base64"])
            == raw_dssp_bytes,
            "evidence retains exact raw DSSP bytes and their digest",
        )
        _check(
            evidence["normalization"]["tool_version"] == GEMMI_VERSION
            and evidence["dssp"]["tool_version"] == "mkdssp 4.6.1"
            and evidence["biotite_psea"]["tool_version"] == BIOTITE_VERSION,
            "evidence retains every measured tool version",
        )
        assignments = evidence["per_residue_assignments"]
        _check(
            len(assignments) == 3
            and assignments[0]["dssp"] == "C"
            and assignments[0]["biotite_psea"] == "C"
            and assignments[-1]["dssp"] == "H"
            and assignments[-1]["biotite_psea"] == "C",
            "evidence retains both per-residue assignment streams",
        )


def test_evidence_is_no_overwrite_and_fail_atomic() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        model = root / "model.pdb"
        model.write_text("MODEL\nEND\n")
        target = root / "evidence.json"
        target.write_text("sentinel\n")
        with (
            mock.patch.object(t15, "REPO", root),
            mock.patch.object(t15, "measured_dssp_version") as dssp_version,
        ):
            try:
                t15.main([str(model), "--evidence-out", str(target)])
            except SystemExit as exc:
                message = str(exc)
            else:
                message = ""
        _check("refusing to overwrite" in message and target.read_text() == "sentinel\n",
               "a pre-existing evidence target is preserved byte-for-byte")
        _check(not dssp_version.called,
               "overwrite refusal happens before any external oracle work")

        failed_target = root / "nested/failure.json"
        with mock.patch.object(t15.os, "link", side_effect=OSError("simulated publish failure")):
            try:
                t15.write_evidence_bundle_no_overwrite(failed_target, {"complete": True})
            except SystemExit as exc:
                publish_message = str(exc)
            else:
                publish_message = ""
        leftovers = list(failed_target.parent.glob(f".{failed_target.name}.*.tmp"))
        _check(
            "could not publish evidence bundle" in publish_message
            and not failed_target.exists()
            and leftovers == [],
            "a publication failure leaves neither a partial target nor staging debris",
        )


def test_source_archive_binding_fails_before_oracle_work() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        model = root / "model.pdb"
        model.write_bytes(b"MODEL\ninput\nEND\n")
        archive = root / "artifact.zip"
        with zipfile.ZipFile(archive, "w") as source_zip:
            source_zip.writestr("data/model.pdb", b"MODEL\nxxxxx\nEND\n")
        bad_archive = root / "not-a-zip.zip"
        bad_archive.write_bytes(b"not a zip archive")

        cases = [
            (
                ["--source-archive", str(archive)],
                "must be supplied together",
            ),
            (
                ["--source-member", "data/model.pdb"],
                "must be supplied together",
            ),
            (
                [
                    "--source-archive", str(archive),
                    "--source-member", "../model.pdb",
                ],
                "safe canonical ZIP path",
            ),
            (
                [
                    "--source-archive", str(archive),
                    "--source-member", "data/model.pdb",
                ],
                "do not match",
            ),
            (
                [
                    "--source-archive", str(archive),
                    "--source-member", "missing.pdb",
                ],
                "found 0",
            ),
            (
                [
                    "--source-archive", str(root / "missing.zip"),
                    "--source-member", "data/model.pdb",
                ],
                "could not read source archive member",
            ),
            (
                [
                    "--source-archive", str(bad_archive),
                    "--source-member", "data/model.pdb",
                ],
                "could not read source archive member",
            ),
            (
                [
                    "--source-archive", str(archive),
                    "--source-member", "data\\model.pdb",
                ],
                "safe canonical ZIP path",
            ),
        ]
        for extra_args, expected in cases:
            target = root / f"evidence-{len(extra_args)}-{expected[:3]}.json"
            with (
                mock.patch.object(t15, "REPO", root),
                mock.patch.object(t15, "measured_dssp_version") as dssp_version,
            ):
                try:
                    t15.main([
                        str(model),
                        "--evidence-out", str(target),
                        *extra_args,
                    ])
                except SystemExit as exc:
                    message = str(exc)
                else:
                    message = ""
            _check(expected in message, f"invalid archive binding fails: {expected}")
            _check(not dssp_version.called and not target.exists(),
                   "invalid archive binding runs no oracle and writes no evidence")

        duplicate_archive = root / "duplicate.zip"
        with zipfile.ZipFile(duplicate_archive, "w") as source_zip:
            source_zip.writestr("data/model.pdb", model.read_bytes())
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                source_zip.writestr("data/model.pdb", model.read_bytes())
        with mock.patch.object(t15, "REPO", root):
            try:
                t15.source_archive_provenance(
                    duplicate_archive, "data/model.pdb", model.read_bytes()
                )
            except SystemExit as exc:
                message = str(exc)
            else:
                message = ""
        _check("found 2" in message, "duplicate ZIP member is rejected")

        oversized_archive = root / "oversized.zip"
        with zipfile.ZipFile(oversized_archive, "w") as source_zip:
            source_zip.writestr("data/model.pdb", model.read_bytes() + b"extra")
        with mock.patch.object(t15, "REPO", root):
            try:
                t15.source_archive_provenance(
                    oversized_archive, "data/model.pdb", model.read_bytes()
                )
            except SystemExit as exc:
                message = str(exc)
            else:
                message = ""
        _check("size does not match" in message, "oversized ZIP member is rejected")

        repository_root = root / "repository"
        repository_root.mkdir()
        with mock.patch.object(t15, "REPO", repository_root):
            try:
                t15.source_archive_provenance(
                    archive, "data/model.pdb", model.read_bytes()
                )
            except SystemExit as exc:
                message = str(exc)
            else:
                message = ""
        _check(
            "must be inside the repository" in message,
            "an archive outside the repository is rejected",
        )

        matching_archive = root / "bound_artifacts.zip"
        with zipfile.ZipFile(matching_archive, "w") as source_zip:
            source_zip.writestr("data/model.pdb", model.read_bytes())
        mismatch_target = root / "subject-mismatch.json"
        with (
            mock.patch.object(t15, "REPO", root),
            mock.patch.object(t15, "measured_dssp_version") as dssp_version,
        ):
            try:
                t15.main([
                    str(model),
                    "--subject-ref", "artifact:wrong#other.pdb",
                    "--evidence-out", str(mismatch_target),
                    "--source-archive", str(matching_archive),
                    "--source-member", "data/model.pdb",
                ])
            except SystemExit as exc:
                message = str(exc)
            else:
                message = ""
        _check(
            "does not identify the declared source archive member" in message,
            "an archive-bound run rejects a mismatched subject reference",
        )
        _check(
            not dssp_version.called and not mismatch_target.exists(),
            "archive/subject mismatch fails before oracle work",
        )


def test_oracle_failure_publishes_neither_evidence_nor_yaml() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        model = root / "model.pdb"
        model.write_text("MODEL\nEND\n")
        normalized = root / ".normalized.pdb"
        target = root / "data/evidence/failure.json"

        def fake_normalize(_model: Path, **_kwargs) -> Path:
            normalized.write_text("NORMALIZED\n")
            return normalized

        stdout = io.StringIO()
        with (
            mock.patch.object(t15, "REPO", root),
            mock.patch.object(t15, "measured_dssp_version", return_value="mkdssp 4.6.1"),
            mock.patch.object(t15, "measured_gemmi_version", return_value=GEMMI_VERSION),
            mock.patch.object(t15, "measured_biotite_version", return_value=BIOTITE_VERSION),
            mock.patch.object(t15, "_normalise_for_dssp", side_effect=fake_normalize),
            mock.patch.object(
                t15,
                "run_dssp_with_raw",
                return_value=({("A", "1", ""): "C"}, _DSSP_SAMPLE.encode()),
            ),
            mock.patch.object(t15, "run_biotite", side_effect=SystemExit("biotite failed")),
            contextlib.redirect_stdout(stdout),
        ):
            try:
                t15.main([str(model), "--evidence-out", str(target)])
            except SystemExit as exc:
                message = str(exc)
            else:
                message = ""
        _check("biotite failed" in message and not target.exists() and stdout.getvalue() == "",
               "an oracle failure publishes neither evidence nor measurement YAML")
        _check(not normalized.exists(),
               "an oracle failure still removes the transient normalized file")


def test_insertion_code_not_conflated() -> None:
    # 10 and 10A must be distinct residues, not merged.
    a = {("A", "10", ""): "H", ("A", "10", "A"): "E"}
    b = {("A", "10", ""): "H", ("A", "10", "A"): "E"}
    r = t15.agreement(a, b)
    _check(r["n_scored"] == 2 and r["n_agree"] == 2,
           f"insertion code keeps 10 and 10A distinct (got n_scored={r['n_scored']})")


def _optional_exact_biotite_replay(
    source_bytes: bytes, expected_version: str
) -> dict[t15.ResKey, str] | None:
    """Replay P-SEA only with the exact evidence-producing optional version."""
    try:
        installed_version = importlib.metadata.version("biotite")
    except importlib.metadata.PackageNotFoundError:
        installed_version = None
    if installed_version != expected_version:
        print(
            "SKIP  exact T15 P-SEA replay requires optional biotite "
            f"{expected_version} (installed: {installed_version or 'absent'})"
        )
        return None
    with tempfile.TemporaryDirectory() as tmpdir:
        source_model = Path(tmpdir) / "source.pdb"
        source_model.write_bytes(source_bytes)
        return t15.run_biotite(source_model)


def test_optional_biotite_replay_is_version_exact() -> None:
    expected = {("A", "1", ""): "C"}
    for installed in (None, "1.6.0"):
        version_result = (
            importlib.metadata.PackageNotFoundError("biotite")
            if installed is None
            else installed
        )
        stdout = io.StringIO()
        with (
            mock.patch.object(
                importlib.metadata,
                "version",
                side_effect=version_result if installed is None else None,
                return_value=version_result if installed is not None else None,
            ),
            mock.patch.object(t15, "run_biotite") as run_biotite,
            contextlib.redirect_stdout(stdout),
        ):
            replayed = _optional_exact_biotite_replay(b"MODEL\nEND\n", BIOTITE_VERSION)
        _check(
            replayed is None and not run_biotite.called,
            "absent or mismatched optional biotite cannot replay retained evidence",
        )
        _check(
            f"installed: {installed or 'absent'}" in stdout.getvalue(),
            "a skipped P-SEA replay names the installed version state",
        )
    with (
        mock.patch.object(
            importlib.metadata, "version", return_value=BIOTITE_VERSION
        ),
        mock.patch.object(t15, "run_biotite", return_value=expected) as run_biotite,
    ):
        replayed = _optional_exact_biotite_replay(b"MODEL\nEND\n", BIOTITE_VERSION)
    _check(
        replayed == expected and run_biotite.call_count == 1,
        "the exact evidence-producing biotite version replays P-SEA once",
    )


def test_committed_1sar_evidence_replays_without_external_oracles() -> None:
    """Recompute every published T15 scalar from the retained evidence chain."""
    repo = Path(__file__).resolve().parent.parent
    evidence_path = (
        repo / "data/coscientists/openscientist/"
        "EVIDENCE_1sar_cdba2c07_2026-09-22_t15.json"
    )
    eval_path = (
        repo / "data/coscientists/openscientist/"
        "EVAL_1sar_cdba2c07_2026-09-22.yaml"
    )
    qds_path = (
        repo / "data/coscientists/openscientist/"
        "QDS_1sar_cdba2c07_2026-09-22.yaml"
    )
    evidence = json.loads(evidence_path.read_text())
    archive_path = repo / evidence["source_archive"]
    archive_bytes = archive_path.read_bytes()
    _check(
        hashlib.sha256(archive_bytes).hexdigest()
        == evidence["source_archive_sha256"],
        "committed T15 evidence pins the complete artifact archive",
    )
    with zipfile.ZipFile(archive_path) as source_zip:
        matching_members = [
            info
            for info in source_zip.infolist()
            if info.filename == evidence["source_member"]
        ]
        _check(
            len(matching_members) == 1,
            "committed T15 archive has one unambiguous source member",
        )
        source_bytes = source_zip.read(matching_members[0])
    _check(
        hashlib.sha256(source_bytes).hexdigest() == evidence["source_sha256"],
        "committed T15 source member matches its evidence hash",
    )
    artifact_id = archive_path.name.removesuffix("_artifacts.zip")
    expected_subject = f"artifact:{artifact_id}#{evidence['source_member']}"
    _check(
        evidence["subject_ref"] == expected_subject,
        "committed T15 subject names the exact archive id and member",
    )

    normalization = evidence["normalization"]
    normalized_bytes = base64.b64decode(
        normalization["bytes_base64"], validate=True
    )
    _check(
        len(normalized_bytes) == normalization["size_bytes"]
        and hashlib.sha256(normalized_bytes).hexdigest()
        == normalization["sha256"],
        "retained normalized input bytes match their size and SHA-256",
    )
    dssp_evidence = evidence["dssp"]
    raw_dssp = base64.b64decode(
        dssp_evidence["raw_output_base64"], validate=True
    )
    _check(
        len(raw_dssp) == dssp_evidence["raw_output_size_bytes"]
        and hashlib.sha256(raw_dssp).hexdigest()
        == dssp_evidence["raw_output_sha256"],
        "retained raw DSSP bytes match their size and SHA-256",
    )
    parsed_dssp = t15._parse_dssp(raw_dssp.decode("utf-8"))

    rows = evidence["per_residue_assignments"]
    keys = [(row["chain"], row["resnum"], row["icode"]) for row in rows]
    _check(
        keys == sorted(set(keys)),
        "retained T15 assignment keys are unique and canonically sorted",
    )
    _check(
        all(
            row.get("dssp") in {"H", "E", "C"}
            and row.get("biotite_psea") in {"H", "E", "C"}
            for row in rows
        ),
        "retained T15 assignment rows contain only complete H/E/C pairs",
    )
    stored_dssp = {
        key: row["dssp"] for key, row in zip(keys, rows, strict=True)
    }
    stored_biotite = {
        key: row["biotite_psea"] for key, row in zip(keys, rows, strict=True)
    }
    _check(
        parsed_dssp == stored_dssp,
        "raw DSSP output reproduces every retained collapsed assignment",
    )
    replayed_biotite = _optional_exact_biotite_replay(
        source_bytes, evidence["biotite_psea"]["tool_version"]
    )
    if replayed_biotite is not None:
        _check(
            replayed_biotite == stored_biotite,
            "the exact evidence-producing biotite P-SEA reproduces every assignment",
        )

    result = t15.agreement(parsed_dssp, stored_biotite)
    recomputed_aggregate = {
        field: result[field] for field in t15._BUNDLE_RESULT_FIELDS
    }
    _check(
        recomputed_aggregate == evidence["aggregate"],
        "retained assignments reproduce every T15 aggregate",
    )
    expected_bundle_ref = t15.content_bound_bundle_ref(
        result,
        "EVAL_1sar_cdba2c07_2026-09-22",
        evidence["source_sha256"],
        normalization["sha256"],
        normalization["tool_version"],
        dssp_evidence["tool_version"],
        evidence["biotite_psea"]["tool_version"],
        evidence["subject_ref"],
    )
    _check(
        expected_bundle_ref == evidence["bundle_ref"],
        "committed T15 bundle id is content-bound to the replayed result",
    )

    eval_doc = yaml.safe_load(eval_path.read_text())
    run = eval_doc["evaluation_runs"][0]
    _check(
        run["catalog_tasks_applied"] == ["T15"],
        "the candidate run applies T15 only",
    )
    measurements = {
        row["metric_definition_ref"]: row for row in run["measurements"]
    }
    expected_values = {
        "T15_secondary_structure_agreement": (0.8802, "DSSP + biotite P-SEA"),
        "T15_secondary_structure_content": (0.375, "DSSP"),
    }
    _check(
        set(measurements) == set(expected_values),
        "the candidate run publishes exactly the two replayed T15 metrics",
    )
    for metric, (value, tool) in expected_values.items():
        row = measurements[metric]
        _check(
            row["oracle_measure"] == {"value_numeric": value, "unit": "fraction"}
            and row["oracle_tool_ref"] == tool
            and row["oracle_family"] == "non_cctbx"
            and row["pass_status"] == "informational"
            and "pass_criterion" not in row
            and row["subject_ref"] == expected_subject
            and row["bundle_ref"] == evidence["bundle_ref"]
            and row["evidence_refs"] == [
                evidence_path.relative_to(repo).as_posix()
            ],
            f"{metric} preserves the exact replayed value and provenance",
        )

    qds = yaml.safe_load(qds_path.read_text())["quality_data_sheets"][0]
    _check(
        qds["derived_from_evaluation_run_refs"] == [
            "EVAL_1sar_cdba2c07_2026-09-21",
            "EVAL_1sar_cdba2c07_2026-09-22",
        ]
        and qds["coverage_scope"] == "partial",
        "the new QDS is an exact two-run partial T15+T16 sheet",
    )
    classification = qds["classification_summary"]
    _check(
        classification["secondary_structure_agreement"]["value_numeric"]
        == evidence["aggregate"]["fraction"]
        and classification["secondary_structure_content"]["value_numeric"]
        == evidence["aggregate"]["dssp_ss_content"],
        "the QDS classification block preserves both replayed T15 values",
    )
    interface_rows = qds["interface_quality_summary"]["interface_qualities"]
    mapping_scores = {
        row["model_to_native_chain_mapping"]: row["dockq_score"]["value_numeric"]
        for row in interface_rows
    }
    _check(
        mapping_scores == {
            "AB:AB": 0.9445273046764164,
            "AB:BA": 0.006320910841818854,
        },
        "the combined QDS retains both T16 mappings without rerunning T16",
    )
    _check(
        "retracted" not in qds["headline_verdict"].casefold()
        and "not rerun" in qds["headline_verdict"]
        and "not a model-quality" in qds["headline_verdict"],
        "the QDS headline excludes stale retraction prose and states its limits",
    )


def test_committed_dssp_raw_mutations_fail_closed() -> None:
    path = (Path(__file__).resolve().parent.parent / "data/coscientists/openscientist/"
            "EVIDENCE_1sar_cdba2c07_2026-09-22_t15.json")
    original = path.read_bytes()
    evidence = json.loads(original)
    raw = base64.b64decode(evidence["dssp"]["raw_output_base64"], validate=True).decode("utf-8")
    lines = raw.splitlines()
    start = lines.index(_RAW_HEADER) + 1
    assert "\u00a0" in raw[:raw.index(_RAW_HEADER)]  # UTF-8 prose is not residue grammar.
    assert any(line[16] == "P" for line in lines[start:])
    expected = {(row["chain"], row["resnum"], row["icode"]): row["dssp"]
                for row in evidence["per_residue_assignments"]}
    assert t15._parse_dssp(raw) == expected
    unknown = list(lines)
    unknown[start] = unknown[start][:16] + "Z" + unknown[start][17:]
    _expect_dssp_failure("\n".join(unknown) + "\n", "unknown secondary-structure")
    _expect_dssp_failure("\n".join(lines[:-1]) + "\n", "incomplete residue coverage")
    truncated = list(lines)
    truncated[start] = truncated[start][:17]
    _expect_dssp_failure("\n".join(truncated) + "\n", "unsupported-width")
    assert path.read_bytes() == original
    _check(True, "saved DSSP UTF-8 header/P states replay unchanged; in-memory corruptions fail")


@contextlib.contextmanager
def _mocked_completed_pair(root, dssp, biotite, *, behavior=None, raw_override=None):
    """Exercise public main and real I/O helpers, never a scientific executable."""
    model = root / "model.pdb"
    model_bytes = b"HEADER original source\r\nEND\r\n"
    normalized_bytes = b"HEADER normalized source\nEND\n"
    model.write_bytes(model_bytes)
    rows = [_dssp_row(n, chain, resnum, icode, " " if state == "C" else state)
            for n, ((chain, resnum, icode), state) in enumerate(sorted(dssp.items()), 1)]
    raw_dssp = (_dssp_text(rows).replace("\n", "\r\n").encode("ascii")
                if raw_override is None else raw_override)
    calls = []

    def fake_capture(arguments):
        argv = [str(value) for value in arguments]
        calls.append(argv)
        conversion = argv[1] == "convert"
        Path(argv[-1]).write_bytes(normalized_bytes if conversion else raw_dssp)
        if not conversion and behavior == "normalized_changed":
            Path(argv[-2]).write_bytes(b"changed before DSSP consumption\n")
        if not conversion and behavior == "normalized_missing":
            Path(argv[-2]).unlink()
        phase = "normalize" if conversion else "dssp"
        return SimpleNamespace(
            returncode=7 if behavior == f"{phase}_fail" else 0,
            stdout=f"{phase} stdout\n", stderr=f"{phase} stderr\n",
        )

    def fake_biotite(_model):
        if behavior == "biotite_fail":
            raise SystemExit("mock P-SEA failed before completing assignments")
        if behavior == "source_changed":
            model.write_bytes(b"changed while assigners ran\n")
        return biotite

    stdout, stderr = io.StringIO(), io.StringIO()
    evidence = root / "data/evidence/t15.json"
    fixture = SimpleNamespace(
        model=model, model_bytes=model_bytes, normalized_bytes=normalized_bytes,
        raw_dssp=raw_dssp, calls=calls, stdout=stdout, stderr=stderr,
        evidence=evidence,
        argv=[str(model), "--eval-id", "EVAL_failed_pair", "--subject-ref",
              "model:fixture", "--evidence-out", str(evidence), "--per-residue"],
    )
    with (
        mock.patch.object(t15, "REPO", root),
        mock.patch.object(t15, "measured_dssp_version", return_value="DSSP measured 4.6.1"),
        mock.patch.object(t15, "measured_gemmi_version", return_value="gemmi measured 0.7.5"),
        mock.patch.object(t15, "measured_biotite_version", return_value="1.7.1"),
        mock.patch.object(t15, "dssp_executable", return_value=Path("/mock/mkdssp")),
        mock.patch.object(t15, "gemmi_executable", return_value=Path("/mock/gemmi")),
        mock.patch.object(t15, "run_capture", side_effect=fake_capture),
        mock.patch.object(t15, "run_biotite", side_effect=fake_biotite),
        contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr),
    ):
        yield fixture


def _expect_main_failure(fixture):
    try:
        t15.main(fixture.argv)
    except SystemExit as error:
        assert error.code != 0
        return error
    raise AssertionError("public main unexpectedly accepted a rejected attempt")


def test_failed_pair_retains_exact_evidence() -> None:
    dssp = {("A", "10", ""): "H", ("A", "10", "A"): "E"}
    biotite = {("A", "10", ""): "C", ("B", "10", ""): "C"}
    with tempfile.TemporaryDirectory() as tmpdir:
        with _mocked_completed_pair(Path(tmpdir), dssp, biotite) as f:
            with (
                mock.patch.object(t15, "build_evidence_bundle") as success_builder,
                mock.patch.object(t15, "render_yaml") as renderer,
            ):
                error = _expect_main_failure(f)
                success_builder.assert_not_called()
                renderer.assert_not_called()
            retained = f.evidence.read_bytes()
            payload = json.loads(retained)
            assert isinstance(error, t15.DenominatorAdmissionError)
            assert payload["failure"] == {
                "stage": "residue_key_admission",
                "reason_code": "unequal_residue_keys",
                "message": str(error),
                "counts": {"n_dssp": 2, "n_biotite": 2, "n_shared": 1,
                           "n_dssp_only": 1, "n_biotite_only": 1},
                "shared_keys": [{"chain": "A", "resnum": "10", "icode": ""}],
                "dssp_only_keys": [{"chain": "A", "resnum": "10", "icode": "A"}],
                "biotite_only_keys": [{"chain": "B", "resnum": "10", "icode": ""}],
            }
            assert payload["evidence_format"] == "protstruct-review-t15-failed-attempt-v1"
            assert payload["attempt_status"] == "failed_denominator_admission"
            assert payload["catalog_task_ref"] == "T15"
            assert payload["eval_id"] == "EVAL_failed_pair"
            assert payload["subject_ref"] == "model:fixture"
            assert payload["measurements_emitted"] is False
            for block, exact in (
                (payload["source"], f.model_bytes),
                (payload["normalization"], f.normalized_bytes),
                (payload["dssp"]["raw_output"], f.raw_dssp),
            ):
                assert base64.b64decode(block["bytes_base64"], validate=True) == exact
                assert block["sha256"] == hashlib.sha256(exact).hexdigest()
                assert block["size_bytes"] == len(exact) and block["encoding"] == "base64"
            for name, expected in (("dssp", dssp), ("biotite_psea", biotite)):
                assert payload[name]["assignments"] == [
                    {"chain": c, "resnum": r, "icode": i, "state": state}
                    for (c, r, i), state in sorted(expected.items())
                ]
            assert payload["normalization"]["tool_version"] == "gemmi measured 0.7.5"
            assert payload["dssp"]["tool_version"] == "DSSP measured 4.6.1"
            assert payload["biotite_psea"]["tool_version"] == "1.7.1"
            assert len(f.calls) == 2
            for index, name, phase in ((0, "normalization", "normalize"), (1, "dssp", "dssp")):
                assert payload[name]["execution"] == {
                    "argv": f.calls[index], "returncode": 0,
                    "stdout": f"{phase} stdout\n", "stderr": f"{phase} stderr\n",
                }
                assert not Path(f.calls[index][-1]).exists()
            assert payload["biotite_psea"]["execution"] == {
                "mode": "in_process", "status": "returned_assignments",
            }
            assert not ({"aggregate", "bundle_ref", "metric_definition_refs",
                         "fraction", "pass_status", "pass_criterion"} & payload.keys())
            assert f.stdout.getvalue() == ""
            assert f.stderr.getvalue() == (
                "t15_ss_agreement: failed-attempt evidence retained: data/evidence/t15.json\n"
            )
            with mock.patch.object(t15, "measured_dssp_version") as version_probe:
                repeated = _expect_main_failure(f)
                version_probe.assert_not_called()
            assert "refusing to overwrite" in str(repeated)
            assert f.evidence.read_bytes() == retained and len(f.calls) == 2
    _check(True, "failed public main retains exact streams, bytes, provenance and insertion keys")


def test_failed_pair_zero_shared_and_archive_binding() -> None:
    for dssp, biotite in (
        ({("A", "10", "A"): "H"}, {("A", "10", ""): "E"}),
        ({}, {}),
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            with _mocked_completed_pair(root, dssp, biotite) as f:
                archive = root / "source_artifacts.zip"
                with zipfile.ZipFile(archive, "w") as source_zip:
                    source_zip.writestr("inputs/model.pdb", f.model_bytes)
                subject_index = f.argv.index("--subject-ref")
                del f.argv[subject_index:subject_index + 2]
                f.argv.extend(["--source-archive", str(archive),
                               "--source-member", "inputs/model.pdb"])
                error = _expect_main_failure(f)
                payload = json.loads(f.evidence.read_bytes())
                assert isinstance(error, t15.DenominatorAdmissionError)
                assert payload["failure"]["reason_code"] == "no_shared_residue_keys"
                assert payload["failure"]["counts"] == {
                    "n_dssp": len(dssp), "n_biotite": len(biotite), "n_shared": 0,
                    "n_dssp_only": len(dssp), "n_biotite_only": len(biotite),
                }
                assert payload["failure"]["shared_keys"] == []
                for label, assignments in (("dssp", dssp), ("biotite", biotite)):
                    assert payload["failure"][f"{label}_only_keys"] == [
                        {"chain": c, "resnum": r, "icode": i}
                        for c, r, i in sorted(assignments)
                    ]
                assert payload["source_archive"] == "source_artifacts.zip"
                assert payload["source_member"] == "inputs/model.pdb"
                assert payload["source_archive_sha256"] == hashlib.sha256(
                    archive.read_bytes()
                ).hexdigest()
                assert payload["subject_ref"] == "artifact:source#inputs/model.pdb"
                assert f.stdout.getvalue() == "" and len(f.calls) == 2
    _check(True, "zero-shared and empty completed pairs retain exact archive-bound failures")


def test_failed_pair_no_output_on_preflight_or_publication_failure() -> None:
    a, b = {("A", "1", ""): "H"}, {("A", "2", ""): "E"}
    for case in ("exists", "outside", "existing_symlink", "dangling_symlink",
                 "publish_race", "publish_error"):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "repository"
            root.mkdir()
            with _mocked_completed_pair(root, a, b) as f:
                target = f.evidence
                if case in {"exists", "existing_symlink", "dangling_symlink"}:
                    target.parent.mkdir(parents=True)
                    if case.endswith("symlink"):
                        referent = root / "existing.json"
                        if case == "existing_symlink":
                            referent.write_bytes(b"sentinel\n")
                        target.symlink_to(referent)
                    else:
                        target.write_bytes(b"sentinel\n")
                elif case == "outside":
                    target = Path(tmpdir) / "outside.json"
                    f.argv[f.argv.index("--evidence-out") + 1] = str(target)

                def publication_failure(_source, destination):
                    if case == "publish_race":
                        Path(destination).write_bytes(b"sentinel\n")
                        raise FileExistsError("concurrent publication won")
                    raise OSError("mock publication failure")

                with contextlib.ExitStack() as stack:
                    if case.startswith("publish_"):
                        stack.enter_context(mock.patch.object(
                            t15.os, "link", side_effect=publication_failure
                        ))
                    error = _expect_main_failure(f)
                assert f.stdout.getvalue() == ""
                assert "failed-attempt evidence retained" not in f.stderr.getvalue()
                assert not list(root.rglob("*.tmp"))
                if case in {"exists", "existing_symlink", "publish_race"}:
                    assert target.read_bytes() == b"sentinel\n"
                elif case == "dangling_symlink":
                    assert target.is_symlink() and not target.exists()
                    assert target.readlink() == referent and not referent.exists()
                else:
                    assert not target.exists()
                if not case.startswith("publish_"):
                    assert f.calls == []
                assert not isinstance(error, t15.DenominatorAdmissionError)
    _check(True, "failed-attempt publication preserves repository-local/no-overwrite safeguards")


def test_failed_pair_earlier_failures_do_not_claim_retention() -> None:
    a, b = {("A", "1", ""): "H"}, {("A", "2", ""): "E"}
    for behavior in ("normalize_fail", "dssp_fail", "biotite_fail", "source_changed"):
        with tempfile.TemporaryDirectory() as tmpdir:
            with _mocked_completed_pair(Path(tmpdir), a, b, behavior=behavior) as f:
                error = _expect_main_failure(f)
                assert not isinstance(error, t15.DenominatorAdmissionError)
                assert not f.evidence.exists()
                assert f.stdout.getvalue() == "" and f.stderr.getvalue() == ""
                assert all(not Path(call[-1]).exists() for call in f.calls)
    _check(True, "earlier failure or changed source emits neither measurements nor failure evidence")


def test_success_contract_excludes_failed_attempt_metadata() -> None:
    a = {("A", "10", ""): "H", ("A", "10", "A"): "E"}
    b = {("A", "10", ""): "C", ("A", "10", "A"): "E"}
    with tempfile.TemporaryDirectory() as tmpdir:
        with _mocked_completed_pair(Path(tmpdir), a, b) as f:
            assert t15.main(f.argv) == 0
            payload = json.loads(f.evidence.read_bytes())
            assert set(payload) == {
                "evidence_format", "bundle_ref", "subject_ref", "metric_definition_refs",
                "source_sha256", "normalization", "dssp", "biotite_psea",
                "per_residue_assignments", "aggregate",
            }
            assert payload["evidence_format"] == "protstruct-review-t15-v1"
            assert payload["aggregate"]["n_scored"] == 2
            assert payload["aggregate"]["fraction"] == 0.5
            assert all("execution" not in payload[key]
                       for key in ("normalization", "dssp", "biotite_psea"))
            rows = yaml.safe_load(f.stdout.getvalue())
            assert len(rows) == 2
            assert all(row["pass_status"] == "informational" for row in rows)
            assert all(row["evidence_refs"] == ["data/evidence/t15.json"] for row in rows)
            assert f.stderr.getvalue() == ""
    _check(True, "successful CLI retains the existing evidence shape and two informational rows")


def test_normalized_input_stability_before_any_publication() -> None:
    a = {("A", "1", ""): "H"}
    for b in (a, {("A", "2", ""): "E"}):
        for behavior in ("normalized_changed", "normalized_missing"):
            with tempfile.TemporaryDirectory() as tmpdir:
                with _mocked_completed_pair(Path(tmpdir), a, b, behavior=behavior) as f:
                    with mock.patch.object(t15, "run_biotite") as biotite:
                        error = _expect_main_failure(f)
                        biotite.assert_not_called()
                    assert "normalized model" in str(error)
                    assert "refusing to emit" in str(error)
                    assert not isinstance(error, t15.DenominatorAdmissionError)
                    assert not f.evidence.exists()
                    assert f.stdout.getvalue() == "" and f.stderr.getvalue() == ""
                    assert all(not Path(call[-1]).exists() for call in f.calls)
    _check(True, "normalized mutation/removal refuses success and failed-denominator publication")


def test_malformed_dssp_public_main_never_publishes() -> None:
    a = {("A", "1", ""): "H"}
    raw_cases = (
        _dssp_text([_dssp_row(state="Z")]),
        _dssp_text([_dssp_row()[:17]], declared=1),
        _dssp_text([_dssp_row(), _dssp_row(2)]),
        _dssp_text([_dssp_row()], declared=2),
        _dssp_text([_dssp_row(chain=" ")]),
    )
    for raw in raw_cases:
        with tempfile.TemporaryDirectory() as tmpdir:
            with _mocked_completed_pair(Path(tmpdir), a, a, raw_override=raw.encode()) as f:
                with mock.patch.object(t15, "run_biotite") as biotite:
                    error = _expect_main_failure(f)
                    biotite.assert_not_called()
                assert not isinstance(error, t15.DenominatorAdmissionError)
                assert not f.evidence.exists()
                assert f.stdout.getvalue() == "" and f.stderr.getvalue() == ""
                assert all(not Path(call[-1]).exists() for call in f.calls)
    _check(True, "malformed DSSP cannot publish measurements or a completed-pair failure bundle")


def main() -> int:
    test_parse_dssp()
    test_dssp_nine_states_signed_identity_and_breaks()
    test_dssp_rejects_unknown_states_and_incomplete_rows()
    test_dssp_rejects_bad_identity_and_duplicate_records()
    test_dssp_validates_full_fields_and_exact_break_grammar()
    test_dssp_header_and_declared_total_coverage()
    test_dssp_uses_toolchain_override_and_runner()
    test_collapse_maps()
    test_agreement()
    test_mismatched_residue_sets_fail()
    test_content_detects_degenerate_agreement()
    test_render_emits_agreement_and_content()
    test_main_retains_complete_evidence_and_links_rows()
    test_evidence_is_no_overwrite_and_fail_atomic()
    test_source_archive_binding_fails_before_oracle_work()
    test_oracle_failure_publishes_neither_evidence_nor_yaml()
    test_insertion_code_not_conflated()
    test_optional_biotite_replay_is_version_exact()
    test_failed_pair_retains_exact_evidence()
    test_failed_pair_zero_shared_and_archive_binding()
    test_failed_pair_no_output_on_preflight_or_publication_failure()
    test_failed_pair_earlier_failures_do_not_claim_retention()
    test_success_contract_excludes_failed_attempt_metadata()
    test_normalized_input_stability_before_any_publication()
    test_malformed_dssp_public_main_never_publishes()
    test_committed_1sar_evidence_replays_without_external_oracles()
    test_committed_dssp_raw_mutations_fail_closed()
    print("\nall t15_ss_agreement unit tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
