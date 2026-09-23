#!/usr/bin/env python3
"""Unit tests for check_driver_thresholds.py — the registry→consumer drift gate.

Each test must FAIL if the guard's logic is broken (round 27). No network, no PHENIX.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PASSED = 0


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def check(label, got, want) -> None:
    global PASSED
    if got != want:
        print(f"FAIL  {label}: got {got!r}, want {want!r}", file=sys.stderr)
        raise SystemExit(1)
    print(f"PASS  {label} (got {got!r})")
    PASSED += 1


def main() -> int:
    m = load("check_driver_thresholds")
    check("sidecar loaded without error (#531)", m._LOAD_ERROR, None)

    # A retired value stated on a live (non-history) line is a defect.
    check("retired value on a live line is flagged",
          m.stale_hits("agreement |Δ| ≤ 0.10 Å.", ["≤ 0.10 Å"]),
          ["≤ 0.10 Å"])

    # The same value shown as history is exempt (each marker).
    for mark in ("pre-benchmark", "originally", "round-5", "catalog's", "was a "):
        check(f"history marker {mark!r} exempts the line",
              m.stale_hits(f"({mark} template) ≤ 0.10 Å", ["≤ 0.10 Å"]),
              [])

    # A clean consumer has no hits.
    check("clean consumer has no hits",
          m.stale_hits("|Δ| ≤ 0.03 Å per §3", ["≤ 0.10 Å"]),
          [])

    # #694: preserve the exact bad authoring examples as regression inputs.
    # These are policy contradictions, not a newly defined numeric cutoff.
    density = m.CHECKS_BY_METRIC["Real-space density-fit interpretation (§2)"]
    for old_text in (
        "Real-space correlation coefficient. > 0.85 = good fit.",
        "Real-space R. < 0.20 = good fit at typical resolutions.",
        "ligand_quality: RSCC (>0.85), RSR (<0.20),",
        "Density support — RSCC. Threshold: > 0.85 for ligands.",
        "Flag waters with RSCC < 0.7 as density_misfit ResidueOutliers.",
        "Add `ResidueOutlier` rows for the worst N waters (not all N=146).",
        "matched radii between tools before any ±0.05 comparison is meaningful",
        "Fraction of residues below the configured RSCC quality threshold.",
        "Fraction of residues with poor real-space correlation.",
        "RSCC outlier fraction | Fraction of weakly supported residues",
    ):
        check(f"#694 rejects original active guidance {old_text!r}",
              bool(m.stale_hits(old_text, density["retired"])), True)
    for rel in density["consumers"]:
        check(f"#694 active consumer has no retired fixed bars: {rel}",
              m.stale_hits((REPO / rel).read_text(), density["retired"]), [])

    pose = m.CHECKS_BY_METRIC["CA RMSD domain boundary (§3)"]
    for old_text in pose["retired"]:
        check(f"#723 rejects unsupported ligand-pose instruction {old_text!r}",
              bool(m.stale_hits(old_text, pose["retired"])), True)
    for rel in pose["consumers"]:
        check(f"#723 active consumer has no unsupported pose bars: {rel}",
              m.stale_hits((REPO / rel).read_text(), pose["retired"]), [])

    # registry_value extracts the current figure, and detects a changed one.
    check("registry_value extracts the current CA RMSD",
          m.registry_value(m.CHECKS_BY_METRIC["CA RMSD agreement (§3)"]["registry"], "| CA RMSD | \\|Δ\\| ≤ **0.03 Å**"),
          "0.03")
    check("registry_value sees a changed value",
          m.registry_value(m.CHECKS_BY_METRIC["CA RMSD agreement (§3)"]["registry"], "| CA RMSD | \\|Δ\\| ≤ **0.05 Å**"),
          "0.05")
    check("registry_value returns None on a reworded row",
          m.registry_value(m.CHECKS_BY_METRIC["CA RMSD agreement (§3)"]["registry"], "| CA RMSD | agreement is tight"),
          None)

    # Every CHECKS metric must still be derivable from the LIVE registry, and match.
    registry = (REPO / "ref/thresholds_and_standards.md").read_text()
    for c in m.CHECKS:
        check(f"live registry still yields {c['metric']}",
              m.registry_value(c["registry"], registry), c["current"])

    # Step (b): the table is data. Every consumer exists, every section is a
    # real registry heading, and the loader refuses malformed tables by name.
    for c in m.CHECKS:
        check(f"consumer paths exist for {c['metric']}",
              all((REPO / rel).exists() for rel in c["consumers"]), True)
        check(f"section {c['section']} is a registry heading ({c['metric']})",
              c["section"] in m.section_headings(registry), True)
    check("sidecar has at least the five historical entries", len(m.CHECKS) >= 5, True)
    check("keyed lookup covers every entry", set(m.CHECKS_BY_METRIC) == {c["metric"] for c in m.CHECKS}, True)
    import tempfile
    good = (REPO / "ref/thresholds_and_standards.yaml").read_text()
    bad_tables = {
        "missing key": (good.replace("    section: 3\n", "", 1), "missing ['section']"),
        "duplicate metric": (good.replace('metric: "ΔRMSD band, d_min >= 2.5 (§4)"', 'metric: "CA RMSD agreement (§3)"'), "duplicate metric"),
        "unquoted float current": (good.replace('current: "0.03"', 'current: 0.03'), "current must be a non-empty string"),
        "pattern without a capture group": (good.replace("([\\d.]+) Å\\*\\*'", "[\\d.]+ Å\\*\\*'", 1), "exactly one capture group, has 0"),
        "empty consumers": (good.replace("    consumers:\n      - ref/driving_example.md\n      - ref/driving_example_T01.md\n      - scripts/bench_t01_superposition.py\n", "    consumers: []\n"), "consumers must be a non-empty list"),
        "unknown key": (good.replace("    section: 3\n", "    section: 3\n    note: x\n", 1), "unknown key(s) ['note']"),
        "empty table": ("governed: []\n", "non-empty 'governed' list"),
        "YAML syntax error (#525)": (good + "\n  - : : :\n", "unreadable sidecar"),
        "float retired literal": (good.replace('retired: ["0.01220", "0.01090", "0.00540"]', "retired: [0.01220, 0.01090, 0.00540]"), "retired must be a non-empty list of strings"),
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        for i, (label, (text, reason)) in enumerate(bad_tables.items()):
            assert text != good, label
            path = Path(tmpdir) / f"{i}.yaml"
            path.write_text(text)
            try:
                m.load_checks(path)
                got = "(accepted)"
            except ValueError as exc:
                got = str(exc)
            check(f"loader rejects a table with {label} for the right reason",
                  reason in got, True)
        try:
            m.load_checks(Path(tmpdir) / "absent.yaml")
            got = "(accepted)"
        except ValueError as exc:
            got = str(exc)
        check("loader names a missing sidecar (#525)", "unreadable sidecar" in got, True)
    # #527: a value read from the wrong section is a failure
    spans = m.section_spans(registry)
    check("section spans cover the numbered headings", set(spans) >= {3, 4, 6}, True)
    for c in m.CHECKS:
        hit = m.re.search(c["registry"], registry)
        check(f"{c['metric']} is read from inside section {c['section']}",
              hit is not None
              and spans[c["section"]][0] <= hit.start() < spans[c["section"]][1], True)

    print(f"\nall driver-threshold guard tests passed ({PASSED} checks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
