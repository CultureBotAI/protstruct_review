#!/usr/bin/env python3
"""Unit tests for t15_ss_agreement pure logic (no mkdssp/biotite needed).

The end-to-end run is exercised manually against real oracles; these tests cover
the parsing, three-state collapse, and agreement math so they run anywhere.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import json
import sys
import tempfile
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


# A tiny slice of real legacy-DSSP output (header + three residue lines).
_DSSP_SAMPLE = """\
  #  RESIDUE AA STRUCTURE BP1 BP2  ACC     N-H-->O
    1    1 A D              0   0  148      0, 0.0
    2    2 A V  E     -a   89   0A  71      1,-0.1
    8    8 A L  H  > S+     0   0   14     88,-1.0
"""


def test_parse_dssp() -> None:
    parsed = t15._parse_dssp(_DSSP_SAMPLE)
    _check(parsed == {("A", "1", ""): "C", ("A", "2", ""): "E", ("A", "8", ""): "H"},
           f"_parse_dssp collapses to HEC keyed on (chain,resnum,icode) (got {parsed})")


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
    _check(t15._DSSP_TO_HEC.get("T", "C") == "C", "DSSP turn -> C via default")
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

        def fake_normalize(_model: Path) -> Path:
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
                "--subject-ref", "artifact:model",
                "--evidence-out", str(evidence_path),
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


def test_oracle_failure_publishes_neither_evidence_nor_yaml() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        model = root / "model.pdb"
        model.write_text("MODEL\nEND\n")
        normalized = root / ".normalized.pdb"
        target = root / "data/evidence/failure.json"

        def fake_normalize(_model: Path) -> Path:
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


def main() -> int:
    test_parse_dssp()
    test_dssp_uses_toolchain_override_and_runner()
    test_collapse_maps()
    test_agreement()
    test_mismatched_residue_sets_fail()
    test_content_detects_degenerate_agreement()
    test_render_emits_agreement_and_content()
    test_main_retains_complete_evidence_and_links_rows()
    test_evidence_is_no_overwrite_and_fail_atomic()
    test_oracle_failure_publishes_neither_evidence_nor_yaml()
    test_insertion_code_not_conflated()
    print("\nall t15_ss_agreement unit tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
