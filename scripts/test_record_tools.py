#!/usr/bin/env python3
"""Pure-logic unit tests for the record-level harness tools.

Covers the parsing and conversion steps that turn a tool's output into a graded row.
Both defects pinned here are of the same shape: a value that looked right for the
wrong reason, and would have gone on looking right until the input changed.

  #121  the twin-operator flag keyed on `Twin fraction estimates by twinning operator`,
        a section header ctruncate prints UNCONDITIONALLY -- above either an operator
        table or the words "No operators found". It gave the right answer only because
        a different literal happened to match first.
  #126  the unit regex had no `Å²`, so a BSA or Wilson-B cell became `value_text`.
        `qds_emit._strongest()` ranks numeric above text, so a real measurement lost to
        a weaker text-only one from another tool.

  #721  missing or contradictory twin-operator sections must remain unavailable;
        absence of a parsed report is not a negative scientific result.

No network, no CCP4; safe to run anywhere.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PASSED = 0


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def check(label: str, got, want) -> None:
    global PASSED
    if got != want:
        print(f"FAIL  {label}: got {got!r}, want {want!r}")
        sys.exit(1)
    PASSED += 1
    print(f"PASS  {label} (got {got!r})")


t13 = load("t13_data_quality")
tsv = load("tsv_to_records")


# --- #121: the twin-operator flag ------------------------------------------------

CTRUNCATE_LOG = REPO / "data/coscientists/openscientist/t13_oracle_logs/ctruncate.log"
REAL = CTRUNCATE_LOG.read_text()

operators = lambda text: t13.parse_ctruncate(text, str(CTRUNCATE_LOG))["twin_operators_found"]

check("the committed log reports no twinning operators", operators(REAL), 0)
check("the log really does print the header above 'No operators found'",
      "Twin fraction estimates by twinning operator" in REAL and "No operators found" in REAL,
      True)

# The mutation that exposed the defect: reword ONLY the first-principles line, leaving
# "No operators found" exactly as it is. Before the fix this returned 1.
_reworded = REAL.replace(
    "First principles calculation has found no potential twinning operators",
    "First-principles search located no candidate twin laws")
check("a reworded first-principles line does not flip the flag", operators(_reworded), 0)

# And the flag must still be able to say 1, or the test above passes vacuously.
_with_table = REAL.replace("No operators found", "  h,-k,-l      0.021      0.019")
check("an actual operator table does set the flag", operators(_with_table), 1)

check("a log with no twinning section at all reports unavailable (#721)",
      operators("Resolution range of data: 50.0 - 1.5 A\n"), None)

# #137: the section is checked at EVERY occurrence. A first section saying "No
# operators found" must not mask a later one carrying a real table. Such a
# contradiction is unavailable, not a cherry-picked positive result (#721).
_twice = REAL.replace(
    "Twin fraction estimates by twinning operator\n\nNo operators found",
    "Twin fraction estimates by twinning operator\n\nNo operators found\n\n"
    "Twin fraction estimates by twinning operator\n\n  h,-k,-l      0.021      0.019",
    1)
check("contradictory operator sections are unavailable rather than cherry-picked (#721)",
      operators(_twice), None)
check("and two empty sections still report none",
      operators(REAL.replace(
          "Twin fraction estimates by twinning operator\n\nNo operators found",
          "Twin fraction estimates by twinning operator\n\nNo operators found\n\n"
          "Twin fraction estimates by twinning operator\n\nNo operators found", 1)), 0)


# --- #126: squared units are numeric ----------------------------------------------

check("BSA in Å² parses as a number",
      tsv.parse_cell_to_measurement("1180.4 Å²"),
      {"value_numeric": 1180.4, "unit": "Å²"})
check("and the ASCII spelling too",
      tsv.parse_cell_to_measurement("25.3 Å^2"),
      {"value_numeric": 25.3, "unit": "Å^2"})
# The alternation is ordered: a bare `Å` listed first would match the `Å` of `Å²` and
# leave `²` to fail the anchored tail, which is the defect itself.
check("a bare Å still parses, and is not swallowed by the squared branch",
      tsv.parse_cell_to_measurement("0.15 Å"), {"value_numeric": 0.15, "unit": "Å"})
for _cell, _want in [("92.5 %", "%"), ("-1.2 σ", "σ"), ("12 deg", "deg"), ("104.5 °", "°")]:
    check(f"  {_cell} keeps its unit",
          tsv.parse_cell_to_measurement(_cell).get("unit"), _want)
check("genuinely non-numeric text is still text",
      tsv.parse_cell_to_measurement("passes visual inspection"),
      {"value_text": "passes visual inspection"})
check("and an empty cell is still not-applicable",
      tsv.parse_cell_to_measurement("n/a"), {"is_not_applicable": True})


print(f"\nall record-tool unit tests passed ({PASSED} checks)")
