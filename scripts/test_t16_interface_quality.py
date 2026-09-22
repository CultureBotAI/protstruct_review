#!/usr/bin/env python3
"""Unit tests for t16_interface_quality pure logic (no DockQ binary needed).

The end-to-end DockQ run is exercised manually against real structures; these
tests cover the CAPRI band boundaries and DockQ-JSON extraction so they run
anywhere.
"""
from __future__ import annotations

import contextlib
import io
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import t16_interface_quality as t16  # noqa: E402


def _check(cond: bool, msg: str) -> None:
    if not cond:
        print(f"FAIL  {msg}")
        raise SystemExit(1)
    print(f"PASS  {msg}")


def test_capri_bands() -> None:
    # Boundaries from Basu & Wallner 2016: High>=0.80, Medium[0.49,0.80),
    # Acceptable[0.23,0.49), Incorrect<0.23.
    cases = {
        1.0: "High", 0.80: "High", 0.799: "Medium", 0.49: "Medium",
        0.489: "Acceptable", 0.23: "Acceptable", 0.229: "Incorrect", 0.0: "Incorrect",
    }
    for score, expected in cases.items():
        got = t16.capri_class(score)
        _check(got == expected, f"DockQ {score} -> {expected} (got {got})")


def test_extract() -> None:
    fake = {
        "GlobalDockQ": 0.5123,
        "best_mapping_str": "AB:AB",
        "best_result": {"AB": {"DockQ": 0.5123, "iRMSD": 2.1, "LRMSD": 4.4, "fnat": 0.6}},
    }
    s = t16.extract(fake)
    _check(s["dockq"] == 0.5123, f"extract global DockQ (got {s['dockq']})")
    _check(s["capri"] == "Medium", f"extract derives CAPRI class (got {s['capri']})")
    _check(s["mapping"] == "AB:AB" and "AB" in s["interfaces"],
           "extract carries mapping + per-interface breakdown")


def test_buried_surface_area() -> None:
    # BSA = ΣSASA(chains) − SASA(complex); burial reduces exposed area.
    _check(t16.buried_surface_area(10804.5, 11241.7) == 437.2,
           f"BSA = separated − complex (got {t16.buried_surface_area(10804.5, 11241.7)})")
    _check(t16.buried_surface_area(5000.0, 5000.0) == 0.0, "no burial -> BSA 0")


def test_render_keeps_comparison_provenance() -> None:
    summary = {
        "dockq": 0.9445,
        "capri": "High",
        "mapping": "AB:AB",
        "interfaces": {"AB": {"dockq": 0.9445}},
    }
    rows = yaml.safe_load(t16.render_yaml(
        summary,
        "EVAL_x",
        "EVAL_x_IFACE_AB_IDENTITY",
        "artifact:x#model.pdb",
        "pdb:1abc",
        "data/evidence/model_AB_AB.dockq.json",
    ))
    _check(len({row["id"] for row in rows}) == 2, "DockQ and CAPRI row ids are unique")
    for row in rows:
        _check(row["scope_selector"] == "EVAL_x_IFACE_AB_IDENTITY",
               "measurement selects the declared interface row")
        _check(row["subject_ref"] == "artifact:x#model.pdb",
               "candidate subject survives rendering")
        _check(row["reference_subject_ref"] == "pdb:1abc",
               "native/reference subject survives rendering")
        _check(row["evidence_refs"] == ["data/evidence/model_AB_AB.dockq.json"],
               "retained raw DockQ evidence survives rendering")
        _check("mapping AB:AB" in row["notes"], "mapping survives rendering")


def test_bsa_selects_declared_interface() -> None:
    rows = yaml.safe_load(t16.render_bsa_yaml(
        {"bsa": 437.8, "chains": ["A", "B"], "complex_sasa": 1.0},
        "EVAL_x",
        "EVAL_x_IFACE_AB_IDENTITY",
        "artifact:x#model.pdb",
    ))
    _check(rows[0]["scope_selector"] == "EVAL_x_IFACE_AB_IDENTITY",
           "BSA selects the declared interface row")
    _check(rows[0]["id"].endswith("EVAL_x_IFACE_AB_IDENTITY"),
           "BSA measurement id includes its interface selector")


def test_sequence_equivalent_mapping_controls() -> None:
    same = {"A": ("ALA", "GLY"), "B": ("ALA", "GLY")}
    expected = t16._sequence_equivalent_mappings(same, same, ("A", "B"), ("A", "B"))
    _check(expected == {"AB:AB", "AB:BA"},
           "same-sequence two-chain contact requires identity and swapped controls")
    hetero_model = {"A": ("ALA",), "B": ("GLY",)}
    hetero_native = {"A": ("ALA",), "B": ("GLY",)}
    expected = t16._sequence_equivalent_mappings(
        hetero_model, hetero_native, ("A", "B"), ("A", "B")
    )
    _check(expected == {"AB:AB"}, "heteromer has only its sequence-compatible mapping")


def test_mapping_controls_are_complete_and_match_bsa_chains() -> None:
    sequences = {"A": ("ALA",), "B": ("ALA",)}
    with mock.patch.object(t16, "_protein_chain_sequences", return_value=sequences):
        pair = t16._validate_mapping_controls(
            Path("model.pdb"), Path("native.pdb"), ["AB:AB", "AB:BA"], ("A", "B")
        )
        _check(pair == ("A", "B"), "complete controls return the bound BSA chain pair")
        try:
            t16._validate_mapping_controls(
                Path("model.pdb"), Path("native.pdb"), ["AB:AB"], ("A", "B")
            )
        except SystemExit as exc:
            incomplete = "missing=['AB:BA']" in str(exc)
        else:
            incomplete = False
        _check(incomplete, "omitting a sequence-equivalent mapping fails loudly")
        try:
            t16._validate_mapping_controls(
                Path("model.pdb"), Path("native.pdb"), ["AB:AB", "AB:BA"], ("C", "D")
            )
        except SystemExit as exc:
            mismatch = "does not match mapping candidate chains" in str(exc)
        else:
            mismatch = False
        _check(mismatch, "BSA chain selection must match DockQ candidate chains")


def test_missing_native_emits_no_partial_yaml() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        model = Path(tmpdir) / "model.pdb"
        model.write_text("END\n")
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            try:
                t16.main([
                    str(model), "--native", str(Path(tmpdir) / "missing.pdb"),
                    "--subject-ref", "artifact:model", "--reference-subject-ref", "pdb:native",
                    "--mapping", "AB:AB", "--interface-id", "IFACE_AB",
                    "--raw-json", str(Path(tmpdir) / "raw.json"),
                ])
            except SystemExit as exc:
                failed = "file not found" in str(exc)
            else:
                failed = False
        _check(failed and stdout.getvalue() == "",
               "native preflight fails before printing a valid-looking BSA prefix")


def test_dockq_failure_leaves_no_partial_evidence() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        target = root / "evidence.json"

        def failed_run(arguments):
            Path(arguments[2]).write_text("{partial")
            return SimpleNamespace(returncode=2, stdout="", stderr="failed")

        with (
            mock.patch.object(t16.shutil, "which", return_value="/fake/DockQ"),
            mock.patch.object(t16, "run_capture", side_effect=failed_run),
        ):
            try:
                t16.run_dockq(root / "model.pdb", root / "native.pdb", "AB:AB", target)
            except SystemExit:
                pass
        leftovers = list(root.glob(".*evidence.json.*.tmp"))
        _check(not target.exists() and not leftovers,
               "failed DockQ removes its temporary/partial JSON and leaves target reusable")


def test_repeated_mappings_publish_as_one_group() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        model = root / "model.pdb"
        native = root / "native.pdb"
        model.write_text("END\n")
        native.write_text("END\n")
        finals = [root / "identity.json", root / "swapped.json"]
        calls = 0

        def fail_second(_model, _native, mapping, destination):
            nonlocal calls
            calls += 1
            destination.write_text('{"complete": true}')
            if calls == 2:
                raise SystemExit("second mapping failed")
            return {
                "GlobalDockQ": 0.9,
                "best_mapping_str": mapping,
                "best_result": {},
            }

        stdout = io.StringIO()
        with (
            mock.patch.object(t16, "REPO", root),
            mock.patch.object(t16, "_validate_mapping_controls", return_value=("A", "B")),
            mock.patch.object(
                t16,
                "run_biotite_bsa",
                return_value={"bsa": 1.0, "chains": ["A", "B"]},
            ),
            mock.patch.object(t16, "run_dockq", side_effect=fail_second),
            contextlib.redirect_stdout(stdout),
        ):
            try:
                t16.main([
                    str(model), "--native", str(native),
                    "--subject-ref", "artifact:model",
                    "--reference-subject-ref", "artifact:native",
                    "--mapping", "AB:AB", "--interface-id", "IFACE_ID",
                    "--raw-json", str(finals[0]),
                    "--mapping", "AB:BA", "--interface-id", "IFACE_SWAP",
                    "--raw-json", str(finals[1]),
                ])
            except SystemExit:
                pass
        leftovers = list(root.glob(".*.group.*.json"))
        _check(
            not any(path.exists() for path in finals)
            and not leftovers
            and stdout.getvalue() == "",
            "a later mapping failure publishes neither evidence file nor YAML",
        )


def main() -> int:
    test_capri_bands()
    test_extract()
    test_buried_surface_area()
    test_render_keeps_comparison_provenance()
    test_bsa_selects_declared_interface()
    test_sequence_equivalent_mapping_controls()
    test_mapping_controls_are_complete_and_match_bsa_chains()
    test_missing_native_emits_no_partial_yaml()
    test_dockq_failure_leaves_no_partial_evidence()
    test_repeated_mappings_publish_as_one_group()
    print("\nall t16_interface_quality unit tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
