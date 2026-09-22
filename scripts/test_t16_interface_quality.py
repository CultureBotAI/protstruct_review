#!/usr/bin/env python3
"""Unit tests for t16_interface_quality pure logic (no DockQ binary needed).

The end-to-end DockQ run is exercised manually against real structures; these
tests cover the CAPRI band boundaries and DockQ-JSON extraction so they run
anywhere.
"""
from __future__ import annotations

import sys
from pathlib import Path

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


def main() -> int:
    test_capri_bands()
    test_extract()
    test_buried_surface_area()
    test_render_keeps_comparison_provenance()
    test_bsa_selects_declared_interface()
    print("\nall t16_interface_quality unit tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
