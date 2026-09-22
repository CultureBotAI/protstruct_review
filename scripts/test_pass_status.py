#!/usr/bin/env python3
"""Adversarial unit tests for the pass_status semantics gate."""
from __future__ import annotations

import copy
from datetime import date, datetime
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parent.parent
GUARD = REPO / "scripts" / "check_pass_status.py"
SCHEMA_REL = Path("schemas") / "protstruct_review.yaml"
BINDINGS_REL = Path("ref") / "structural_criteria.yaml"
THRESHOLD_REL = Path("ref") / "thresholds_and_standards.md"
CRITERION_ID = "CRIT_TEST_LT_5"
PASSED = 0

REAL_STATUSES = (
    "pass", "fail_criterion", "fail_by_oracle", "pass_with_caveat",
    "pass_criterion_fail_headline", "fail_by_oracle_within_cctbx",
    "informational", "criterion_inapplicable",
)


def check(label: str, got, want) -> None:
    global PASSED
    if got != want:
        print(f"FAIL  {label}: got {got!r}, want {want!r}")
        sys.exit(1)
    PASSED += 1
    print(f"PASS  {label}")


def run_guard(root: Path) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(GUARD), "--root", str(root)],
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout + proc.stderr


def write_schema(root: Path, statuses=REAL_STATUSES, payload=None) -> None:
    (root / "schemas").mkdir(parents=True, exist_ok=True)
    if payload is None:
        payload = {"enums": {
            "PassStatus": {"permissible_values": {
                status: {"description": status} for status in statuses
            }},
            "Stage": {"permissible_values": {
                value: {} for value in ("start", "intermediate", "final", "all")
            }},
            "MeasurementScope": {"permissible_values": {
                value: {} for value in (
                    "complex", "chain", "domain", "site", "residue", "atom",
                    "dataset", "ligand", "interface", "ensemble", "assembly",
                    "cohort",
                )
            }},
            "ToolFamily": {"permissible_values": {
                "cctbx": {}, "non_cctbx": {},
            }},
        }}
    (root / SCHEMA_REL).write_text(yaml.safe_dump(payload, sort_keys=False))


def default_binding() -> dict:
    return {
        "id": CRITERION_ID,
        "metric_definition_ref": "T_test_metric",
        "threshold_registry_section": 2,
        "threshold_registry_row": "Test metric",
        "threshold_registry_column": 2,
        "comparison_operand": "oracle_measure",
        "comparison_transform": "identity",
        "comparison_unit": "unitless",
        "effective_from": "2026-09-01",
        "applicability": {
            "catalog_task_refs": ["T05"],
            "stages": ["final"],
            "scopes": ["complex", "site"],
            "oracle_tool_refs": ["test oracle", "cctbx oracle"],
            "oracle_families": ["non_cctbx", "cctbx"],
            "required_precondition_ids": [],
            "requires_agent_claim": False,
        },
    }


def write_test_threshold(
    root: Path, criterion: str = "pass when **< 5**",
    provenance: str = "[benchmark]",
) -> None:
    (root / THRESHOLD_REL).write_text(
        "# Threshold registry\n\n"
        "## 2. Test thresholds\n\n"
        "| Metric | Criterion | Provenance |\n"
        "|---|---|---|\n"
        f"| Test metric | {criterion} | {provenance} |\n"
    )


def write_bindings(root: Path, bindings=None, payload=None) -> None:
    (root / "ref").mkdir(parents=True, exist_ok=True)
    (root / "ref" / "catalog.yaml").write_text(yaml.safe_dump({
        "catalog_tasks": [{
            "id": "T05",
            "metric_definition_refs": ["T_test_metric"],
            "oracle_tool_refs": ["test oracle"],
            "phenix_tool_refs": ["cctbx oracle"],
        }],
        "tools": [
            {
                "id": "test oracle", "family": "non_cctbx",
                "catalog_tasks_served": ["T05"],
            },
            {
                "id": "cctbx oracle", "family": "cctbx",
                "catalog_tasks_served": ["T05"],
            },
        ],
        "metric_definitions": [{
            "id": "T_test_metric", "name": "Test metric", "unit": "unitless",
            "applicable_task_refs": ["T05"],
        }],
    }, sort_keys=False))
    write_test_threshold(root)
    if payload is None:
        payload = {
            "criteria": [],
            "pass_criterion_bindings": (
                [default_binding()] if bindings is None else bindings
            ),
        }
    (root / BINDINGS_REL).write_text(yaml.safe_dump(payload, sort_keys=False))


def write_eval(root: Path, rows: list[dict], run_date="2026-09-30") -> None:
    (root / "data").mkdir(parents=True, exist_ok=True)
    if not (root / SCHEMA_REL).exists():
        write_schema(root)
    if not (root / BINDINGS_REL).exists():
        write_bindings(root)
    normalized = [
        {"id": f"EVAL_x_M_{index:03d}", **row}
        for index, row in enumerate(rows, 1)
    ]
    document = {"evaluation_runs": [{
        "id": "EVAL_x", "run_date": run_date, "measurements": normalized,
    }]}
    (root / "data" / f"EVAL_x_{run_date}.yaml").write_text(
        yaml.safe_dump(document, sort_keys=False)
    )


def verdict(
    row: dict,
    run_date="2026-09-30",
    *,
    bindings: list[dict] | None = None,
    threshold_cell: str | None = None,
) -> tuple[int, str]:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        write_schema(root)
        write_bindings(root, bindings=bindings)
        if threshold_cell is not None:
            write_test_threshold(root, threshold_cell)
        write_eval(root, [row], run_date)
        return run_guard(root)


def bound(status="pass", *, value=3.0, claim=None, family="non_cctbx") -> dict:
    row = {
        "catalog_task_ref": "T05",
        "stage": "final",
        "scope": "complex",
        "metric_definition_ref": "T_test_metric",
        "oracle_tool_ref": (
            "cctbx oracle" if family == "cctbx" else "test oracle"
        ),
        "oracle_family": family,
        "oracle_measure": {"value_numeric": value},
        "pass_criterion": "pass when < 5",
        "pass_criterion_ref": CRITERION_ID,
        "pass_status": status,
    }
    if claim is not None:
        row["agent_claim"] = claim
    return row


def main() -> int:
    claim = {"value_numeric": 4.9}

    # R1: verdicts need numeric source text and a contextual registry binding.
    for status in (
        "pass", "fail_criterion", "fail_by_oracle", "pass_with_caveat",
        "pass_criterion_fail_headline", "fail_by_oracle_within_cctbx",
    ):
        row = bound(
            status,
            value=(3.0 if status in {
                "pass", "pass_with_caveat", "pass_criterion_fail_headline"
            } else 7.0),
            claim=claim if status in {
                "fail_by_oracle", "fail_by_oracle_within_cctbx",
                "pass_with_caveat", "pass_criterion_fail_headline",
            } else None,
            family=(
                "cctbx"
                if status == "fail_by_oracle_within_cctbx"
                else "non_cctbx"
            ),
        )
        no_text = {
            key: value for key, value in row.items() if key != "pass_criterion"
        }
        rc, _ = verdict(no_text)
        check(f"R1: {status} without criterion text fails", rc, 1)
        no_ref = {
            key: value for key, value in row.items()
            if key != "pass_criterion_ref"
        }
        rc, _ = verdict(no_ref)
        check(f"R1: {status} without criterion ref fails", rc, 1)
        rc, _ = verdict(row)
        check(f"R1: {status} with applicable binding passes", rc, 0)

    rc, out = verdict(bound("pass", value=7.2))
    check("R1: passing verdict cannot contradict failing value", rc, 1)
    check("R1: passing contradiction diagnostic is explicit",
          "contradicts its numeric evidence" in out, True)
    rc, out = verdict(bound("fail_criterion", value=3.0))
    check("R1: failing verdict cannot contradict passing value", rc, 1)
    check("R1: failing contradiction diagnostic is explicit",
          "contradicts its numeric evidence" in out, True)

    failure_binding = default_binding()
    failure_row = bound("pass", value=7.0)
    failure_row["pass_criterion"] = "failure if > 5"
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        write_schema(root)
        write_bindings(root, bindings=[failure_binding])
        (root / THRESHOLD_REL).write_text(
            "# Threshold registry\n\n"
            "## 2. Test thresholds\n\n"
            "| Metric | Criterion | Provenance |\n"
            "|---|---|---|\n"
            "| Test metric | failure if **> 5** | [benchmark] |\n"
        )
        write_eval(root, [failure_row])
        rc, _ = run_guard(root)
    check("R1: true failure-condition cannot produce pass", rc, 1)
    failure_row["pass_status"] = "fail_criterion"
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        write_schema(root)
        write_bindings(root, bindings=[failure_binding])
        (root / THRESHOLD_REL).write_text(
            "# Threshold registry\n\n"
            "## 2. Test thresholds\n\n"
            "| Metric | Criterion | Provenance |\n"
            "|---|---|---|\n"
            "| Test metric | failure if **> 5** | [benchmark] |\n"
        )
        write_eval(root, [failure_row])
        rc, _ = run_guard(root)
    check("R1: true failure-condition supports fail verdict", rc, 0)
    row = bound()
    row.pop("oracle_measure")
    rc, out = verdict(row)
    check("R1: verdict without numeric operand fails", rc, 1)
    check("R1: missing operand diagnostic names carrier",
          "oracle_measure.value_numeric" in out, True)

    for label, carrier in (
        ("numeric plus not-applicable", {
            "value_numeric": 3.0, "is_not_applicable": True,
        }),
        ("numeric plus text", {
            "value_numeric": 3.0, "value_text": "N/A",
        }),
    ):
        row = bound()
        row["oracle_measure"] = carrier
        rc, _ = verdict(row)
        check(f"R1: operand rejects {label}", rc, 1)
    for spelling in ("3", "3.0", "1e0"):
        row = bound()
        row["oracle_measure"] = {"value_numeric": spelling}
        rc, _ = verdict(row)
        check(f"R1: quoted numeric {spelling!r} is not a typed number", rc, 1)

    exact_threshold = "pass when = 9007199254740993"
    exact_row = bound(value=9007199254740992)
    exact_row["pass_criterion"] = exact_threshold
    rc, _ = verdict(exact_row, threshold_cell=exact_threshold)
    check("R1: integer comparison remains exact above float precision", rc, 1)

    for malformed in (
        "pass when < 5e+", "pass when < 1*2",
        "pass when it is not true that < 5",
        "pass when resolution 2.0 and < 5",
        "pass when approximately < 5",
        "does not pass when < 5", "do not fail when > 5",
        "pass when != 5", "pass when ~= 5", "pass when within -5",
    ):
        row = bound()
        row["pass_criterion"] = malformed
        rc, out = verdict(row, threshold_cell=malformed)
        check(f"R1: malformed criterion {malformed!r} fails closed", rc, 1)
        check(f"R1: malformed criterion {malformed!r} has no traceback",
              "Traceback" in out, False)

    delta_binding = default_binding()
    delta_binding["comparison_operand"] = "delta"
    delta_binding["comparison_transform"] = "absolute"
    row = bound("pass_with_caveat")
    row["pass_criterion"] = "pass when |delta| < 5"
    row["agent_claim"] = {"value_numeric": 6.0}
    row["delta"] = {"value_numeric": -3.0}
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        write_schema(root)
        write_bindings(root, bindings=[delta_binding])
        (root / THRESHOLD_REL).write_text(
            "# Threshold registry\n\n"
            "## 2. Test thresholds\n\n"
            "| Metric | Criterion | Provenance |\n"
            "|---|---|---|\n"
            "| Test metric | pass when **\\|delta\\| < 5** | [benchmark] |\n"
        )
        write_eval(root, [row])
        rc, _ = run_guard(root)
    check("R1: explicit absolute-delta operand passes", rc, 0)
    inconsistent_delta = copy.deepcopy(row)
    inconsistent_delta["delta"] = {"value_numeric": -2.0}
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        write_schema(root)
        write_bindings(root, bindings=[delta_binding])
        (root / THRESHOLD_REL).write_text(
            "# Threshold registry\n\n"
            "## 2. Test thresholds\n\n"
            "| Metric | Criterion | Provenance |\n"
            "|---|---|---|\n"
            "| Test metric | pass when **\\|delta\\| < 5** | [benchmark] |\n"
        )
        write_eval(root, [inconsistent_delta])
        rc, out = run_guard(root)
    check("R1: arbitrary unverified delta operand fails", rc, 1)
    check("R1: delta derivation diagnostic is explicit",
          "oracle_measure - agent_claim" in out, True)
    row["agent_claim"] = {"value_numeric": 10.0}
    row["delta"] = {"value_numeric": -7.0}
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        write_schema(root)
        write_bindings(root, bindings=[delta_binding])
        (root / THRESHOLD_REL).write_text(
            "# Threshold registry\n\n"
            "## 2. Test thresholds\n\n"
            "| Metric | Criterion | Provenance |\n"
            "|---|---|---|\n"
            "| Test metric | pass when **\\|delta\\| < 5** | [benchmark] |\n"
        )
        write_eval(root, [row])
        rc, _ = run_guard(root)
    check("R1: explicit absolute-delta operand fails pass verdict", rc, 1)

    tolerance_binding = copy.deepcopy(delta_binding)
    tolerance_row = bound("pass_with_caveat")
    tolerance_row["pass_criterion"] = "pass when ± 5"
    tolerance_row["agent_claim"] = {"value_numeric": 6.0}
    tolerance_row["delta"] = {"value_numeric": -3.0}
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        write_schema(root)
        write_bindings(root, bindings=[tolerance_binding])
        (root / THRESHOLD_REL).write_text(
            "# Threshold registry\n\n"
            "## 2. Test thresholds\n\n"
            "| Metric | Criterion | Provenance |\n"
            "|---|---|---|\n"
            "| Test metric | pass when **± 5** | [benchmark] |\n"
        )
        write_eval(root, [tolerance_row])
        rc, _ = run_guard(root)
    check("R1: plus/minus tolerance is absolute and evaluable", rc, 0)

    percent_binding = default_binding()
    percent_binding["comparison_unit"] = "%"
    percent_row = bound()
    percent_row["pass_criterion"] = "pass when < 5 %"
    percent_row["oracle_measure"] = {
        "value_numeric": 0.06, "unit": "fraction",
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        write_schema(root)
        write_bindings(root, bindings=[percent_binding])
        (root / "ref" / "catalog.yaml").write_text(yaml.safe_dump({
            "catalog_tasks": [{
                "id": "T05", "metric_definition_refs": ["T_test_metric"],
                "oracle_tool_refs": ["test oracle"],
                "phenix_tool_refs": ["cctbx oracle"],
            }],
            "tools": [
                {"id": "test oracle", "family": "non_cctbx",
                 "catalog_tasks_served": ["T05"]},
                {"id": "cctbx oracle", "family": "cctbx",
                 "catalog_tasks_served": ["T05"]},
            ],
            "metric_definitions": [{
                "id": "T_test_metric", "name": "Test metric", "unit": "%",
                "applicable_task_refs": ["T05"],
            }],
        }, sort_keys=False))
        (root / THRESHOLD_REL).write_text(
            "# Threshold registry\n\n"
            "## 2. Test thresholds\n\n"
            "| Metric | Criterion | Provenance |\n"
            "|---|---|---|\n"
            "| Test metric | pass when **< 5 %** | [benchmark] |\n"
        )
        write_eval(root, [percent_row])
        rc, out = run_guard(root)
    check("R1: percent threshold rejects fraction carrier", rc, 1)
    check("R1: unit mismatch diagnostic names catalog unit",
          "catalog unit '%'" in out, True)

    percent_row["oracle_measure"] = {"value_numeric": 4.0, "unit": "%"}
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        write_schema(root)
        write_bindings(root, bindings=[percent_binding])
        (root / "ref" / "catalog.yaml").write_text(yaml.safe_dump({
            "catalog_tasks": [{
                "id": "T05", "metric_definition_refs": ["T_test_metric"],
                "oracle_tool_refs": ["test oracle"],
                "phenix_tool_refs": ["cctbx oracle"],
            }],
            "tools": [
                {"id": "test oracle", "family": "non_cctbx",
                 "catalog_tasks_served": ["T05"]},
                {"id": "cctbx oracle", "family": "cctbx",
                 "catalog_tasks_served": ["T05"]},
            ],
            "metric_definitions": [{
                "id": "T_test_metric", "name": "Test metric", "unit": "%",
                "applicable_task_refs": ["T05"],
            }],
        }, sort_keys=False))
        (root / THRESHOLD_REL).write_text(
            "# Threshold registry\n\n"
            "## 2. Test thresholds\n\n"
            "| Metric | Criterion | Provenance |\n"
            "|---|---|---|\n"
            "| Test metric | pass when **< 5 %** | [benchmark] |\n"
        )
        write_eval(root, [percent_row])
        rc, _ = run_guard(root)
    check("R1: percent threshold accepts percent carrier", rc, 0)

    length_binding = default_binding()
    length_binding["comparison_unit"] = "Å"
    length_row = bound()
    length_row["pass_criterion"] = "pass when < 5 Å"
    length_row["oracle_measure"] = {"value_numeric": 0.4, "unit": "nm"}
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        write_schema(root)
        write_bindings(root, bindings=[length_binding])
        (root / "ref" / "catalog.yaml").write_text(yaml.safe_dump({
            "catalog_tasks": [{
                "id": "T05", "metric_definition_refs": ["T_test_metric"],
                "oracle_tool_refs": ["test oracle"],
                "phenix_tool_refs": ["cctbx oracle"],
            }],
            "tools": [
                {"id": "test oracle", "family": "non_cctbx",
                 "catalog_tasks_served": ["T05"]},
                {"id": "cctbx oracle", "family": "cctbx",
                 "catalog_tasks_served": ["T05"]},
            ],
            "metric_definitions": [{
                "id": "T_test_metric", "name": "Test metric", "unit": "Å",
                "applicable_task_refs": ["T05"],
            }],
        }, sort_keys=False))
        (root / THRESHOLD_REL).write_text(
            "# Threshold registry\n\n"
            "## 2. Test thresholds\n\n"
            "| Metric | Criterion | Provenance |\n"
            "|---|---|---|\n"
            "| Test metric | pass when **< 5 Å** | [benchmark] |\n"
        )
        write_eval(root, [length_row])
        rc, _ = run_guard(root)
    check("R1: angstrom threshold rejects nanometer carrier", rc, 1)

    placeholders = (
        "n/a", "TBD", "see notes", "informational", "-", "pass",
        "fail_criterion",
    )
    for placeholder in placeholders:
        row = bound()
        row["pass_criterion"] = placeholder
        rc, _ = verdict(row)
        check(f"R1: placeholder {placeholder!r} is not a criterion", rc, 1)

    for prose in ("looks good", "criterion documented elsewhere"):
        row = bound()
        row["pass_criterion"] = prose
        rc, out = verdict(row)
        check(f"R1: nonnumeric prose {prose!r} fails", rc, 1)
        check("R1: nonnumeric diagnostic is explicit",
              "not a numeric comparison" in out, True)

    row = bound()
    row["pass_criterion"] = "pass when < 7"
    rc, out = verdict(row)
    check("R1: criterion absent from cited registry row fails", rc, 1)
    check("R1: source mismatch names registry row", "Test metric" in out, True)

    # A prefix is not an exact criterion match: <5 must not match a <50 row.
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        write_schema(root)
        write_bindings(root)
        (root / THRESHOLD_REL).write_text(
            "# Threshold registry\n\n"
            "## 2. Test thresholds\n\n"
            "| Metric | Criterion | Provenance |\n"
            "|---|---|---|\n"
            "| Test metric | pass when **< 50** | [benchmark] |\n"
        )
        write_eval(root, [bound()])
        rc, out = run_guard(root)
    check("R1: <5 does not prefix-match authoritative <50", rc, 1)
    check("R1: prefix mismatch names registry row", "Test metric" in out, True)

    row = bound()
    row["pass_criterion_ref"] = "CRIT_missing"
    rc, out = verdict(row)
    check("R1: unresolved criterion ref fails", rc, 1)
    check("R1: unresolved diagnostic names ref", "CRIT_missing" in out, True)

    row = bound()
    row["pass_criterion_ref"] = "   "
    rc, out = verdict(row)
    check("R1: blank criterion ref fails", rc, 1)
    check("R1: blank-ref diagnostic names field", "pass_criterion_ref" in out, True)

    # Every declared applicability dimension is enforced, not left as prose.
    for field, value in (
        ("catalog_task_ref", "T01"),
        ("stage", "input"),
        ("scope", "ligand"),
        ("oracle_tool_ref", "other oracle"),
        ("oracle_family", "web_service"),
        ("metric_definition_ref", "T_other_metric"),
    ):
        row = bound()
        row[field] = value
        rc, out = verdict(row)
        check(f"R1 applicability: wrong {field} fails", rc, 1)
        check(f"R1 applicability: wrong {field} is named", field in out, True)

    row = bound(family="cctbx")
    row["oracle_tool_ref"] = "test oracle"
    rc, out = verdict(row)
    check("R1 applicability: tool/family cross-pair fails", rc, 1)
    check("R1 applicability: canonical tool family is named",
          "canonical family" in out, True)

    requires_claim = default_binding()
    requires_claim["applicability"]["requires_agent_claim"] = True
    rc, out = verdict(bound(), bindings=[requires_claim])
    check("R1 applicability: required agent claim is enforced", rc, 1)
    check("R1 applicability: required-claim diagnostic is clear",
          "requires an asserted agent_claim" in out, True)
    rc, _ = verdict(
        bound("pass_with_caveat", claim=claim), bindings=[requires_claim]
    )
    check("R1 applicability: asserted required claim passes", rc, 0)

    requires_precondition = default_binding()
    requires_precondition["applicability"]["required_precondition_ids"] = [
        "matched_h_build"
    ]
    required_cell = "pass when < 5 [requires: matched_h_build]"
    required_row = bound()
    required_row["pass_criterion"] = required_cell
    rc, out = verdict(
        required_row, bindings=[requires_precondition], threshold_cell=required_cell
    )
    check("R1 applicability: missing required precondition fails", rc, 1)
    check("R1 applicability: missing precondition is named",
          "matched_h_build" in out, True)
    for status, evidence, expected in (
        ("void", ["raw.log"], 1),
        ("unknown", ["raw.log"], 1),
        ({"bad": "status"}, ["raw.log"], 1),
        (["void"], ["raw.log"], 1),
        ("satisfied", [], 1),
        ("satisfied", ["raw.log"], 0),
    ):
        row = bound()
        row["pass_criterion"] = required_cell
        row["criterion_preconditions"] = [{
            "id": "matched_h_build", "status": status,
            "evidence_refs": evidence,
        }]
        rc, _ = verdict(
            row, bindings=[requires_precondition], threshold_cell=required_cell
        )
        check(
            f"R1 applicability: precondition {status}/{bool(evidence)} result",
            rc,
            expected,
        )
    row = bound()
    row["pass_criterion"] = required_cell
    row["criterion_preconditions"] = [
        {"id": "matched_h_build", "status": "satisfied", "evidence_refs": ["a"]},
        {"id": "matched_h_build", "status": "satisfied", "evidence_refs": ["a"]},
    ]
    rc, out = verdict(
        row, bindings=[requires_precondition], threshold_cell=required_cell
    )
    check("R1 applicability: duplicate precondition fails", rc, 1)
    check("R1 applicability: duplicate precondition diagnostic is explicit",
          "appears 2 times" in out, True)
    row = bound()
    row["criterion_preconditions"] = False
    rc, out = verdict(row)
    check("R1 applicability: false precondition carrier fails", rc, 1)
    check("R1 applicability: false carrier diagnostic names list",
          "criterion_preconditions must be a list" in out, True)

    # A non-applicable criterion remains linked and evidence-backed, but is not
    # forced through numeric pass/fail evaluation.
    for precondition_status in ("void", "unknown"):
        row = bound("criterion_inapplicable")
        row["pass_criterion"] = required_cell
        row["criterion_preconditions"] = [{
            "id": "matched_h_build", "status": precondition_status,
            "evidence_refs": ["raw.log"],
        }]
        rc, _ = verdict(
            row, bindings=[requires_precondition], threshold_cell=required_cell
        )
        check(f"R2: criterion_inapplicable accepts {precondition_status}", rc, 0)
    row = bound("criterion_inapplicable")
    row["pass_criterion"] = required_cell
    row["criterion_preconditions"] = [{
        "id": "matched_h_build", "status": "satisfied",
        "evidence_refs": ["raw.log"],
    }]
    rc, _ = verdict(
        row, bindings=[requires_precondition], threshold_cell=required_cell
    )
    check("R2: criterion_inapplicable rejects all-satisfied preconditions", rc, 1)
    row["criterion_preconditions"][0]["status"] = {"bad": "status"}
    rc, out = verdict(
        row, bindings=[requires_precondition], threshold_cell=required_cell
    )
    check("R2: criterion_inapplicable rejects non-string status", rc, 1)
    check("R2: non-string precondition status has no traceback",
          "Traceback" in out, False)

    # R2: backdating never creates an exemption in a new root.
    rc, _ = verdict(
        {"pass_status": "informational", "pass_criterion": "< 5"},
        "1999-01-01",
    )
    check("R2: backdating cannot exempt informational + criterion", rc, 1)
    rc, out = verdict({
        "pass_status": "informational", "pass_criterion_ref": CRITERION_ID,
    })
    check("R2: informational + criterion ref fails", rc, 1)
    check("R2: criterion-ref diagnostic is contextual",
          "pass_criterion_ref" in out, True)
    rc, _ = verdict({"pass_status": "informational"})
    check("R2: bare informational passes", rc, 0)
    for explicit_empty in (None, "", "   "):
        rc, _ = verdict({
            "pass_status": "informational",
            "pass_criterion": explicit_empty,
        })
        check(
            f"R2: informational cannot carry explicit {explicit_empty!r} criterion",
            rc,
            1,
        )
    rc, _ = verdict({
        "pass_status": "informational", "pass_criterion_ref": None,
    })
    check("R2: informational cannot carry null criterion ref", rc, 1)
    for orphan in (
        {"pass_criterion": "pass when < 5"},
        {"pass_criterion_ref": CRITERION_ID},
        {"criterion_preconditions": []},
        {"pass_status": None, "pass_criterion_ref": CRITERION_ID},
    ):
        rc, _ = verdict(orphan)
        check("R2: statusless row rejects orphan criterion metadata", rc, 1)
    for carrier_name, malformed in (
        ("oracle_measure", {"value_numeric": 3, "value_text": "three"}),
        ("agent_claim", {"value_numeric": "3"}),
        ("delta", {"is_not_applicable": False}),
    ):
        rc, out = verdict({carrier_name: malformed})
        check(f"shape: statusless malformed {carrier_name} fails", rc, 1)
        check(f"shape: statusless malformed {carrier_name} is named",
              f"{carrier_name} must set exactly one" in out, True)
    rc, out = verdict({
        "oracle_measure": {
            "value_numeric": 3, "pass_status": "pass",
            "pass_criterion": "pass when < 5",
        }
    })
    check("R2: statusless row rejects nested oracle verdict metadata", rc, 1)
    check("R2: nested-verdict diagnostic names carrier",
          "oracle_measure" in out, True)
    row = bound()
    row["oracle_measure"]["pass_status"] = "pass"
    rc, _ = verdict(row)
    check("R1: validated parent cannot carry nested oracle verdict", rc, 1)
    for malformed_preconditions in (
        False, "text", {"status": "void"},
        [{"id": "x", "status": "void", "evidence_refs": ["raw.log"]}],
    ):
        rc, _ = verdict({
            "pass_status": "informational",
            "criterion_preconditions": malformed_preconditions,
        })
        check("R2: informational rejects criterion metadata", rc, 1)

    rc, out = verdict(bound(), run_date="2026-08-31")
    check("R1 temporal: verdict before binding effective_from fails", rc, 1)
    check("R1 temporal: interval diagnostic is explicit",
          "outside binding effective interval" in out, True)
    retired_binding = default_binding()
    retired_binding["effective_until"] = "2026-09-15"
    rc, _ = verdict(
        bound(), run_date="2026-09-16", bindings=[retired_binding]
    )
    check("R1 temporal: verdict after binding effective_until fails", rc, 1)
    rc, out = verdict(bound(), run_date="not-a-date")
    check("R1 temporal: malformed EvaluationRun date fails", rc, 1)
    check("R1 temporal: malformed date has no traceback", "Traceback" in out, False)
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        write_eval(root, [bound()], run_date="2026-09-30")
        source = root / "data" / "EVAL_x_2026-09-30.yaml"
        source.rename(root / "data" / "EVAL_x_2026-09-29.yaml")
        rc, out = run_guard(root)
    check("R1 temporal: filename date must match run_date", rc, 1)
    check("R1 temporal: filename mismatch is diagnosed",
          "does not match filename date" in out, True)

    # R3: disagreement requires an asserted value, not a truthy carrier.
    for label, bad_claim in (
        ("missing", None),
        ("empty mapping", {}),
        ("n/a", {"is_not_applicable": True}),
        ("blank text", {"value_text": "   "}),
        ("boolean numeric", {"value_numeric": True}),
        ("non-finite numeric", {"value_numeric": float("inf")}),
        ("two carriers", {"value_numeric": 1, "value_text": "one"}),
        ("not-applicable text", {"value_text": "Not applicable."}),
        ("not-measured text", {"value_text": "NOT-MEASURED"}),
        ("no-claim text", {"value_text": "No claim"}),
        ("opaque numeric text", {"value_text": "7.0"}),
        ("same-as-oracle text", {"value_text": "same as oracle"}),
    ):
        row = bound("fail_by_oracle", value=7.0, claim=bad_claim)
        if bad_claim is None:
            row.pop("agent_claim", None)
        rc, _ = verdict(row)
        check(f"R3: {label} is not an asserted claim", rc, 1)
    for label, good_claim in (("numeric zero", {"value_numeric": 0}),):
        rc, _ = verdict(bound("fail_by_oracle", value=7.0, claim=good_claim))
        check(f"R3: {label} is an asserted claim", rc, 0)
    rc, out = verdict(bound(
        "fail_by_oracle", value=7.0, claim={"value_numeric": 7.0}
    ))
    check("R3: equal agent and oracle values are not disagreement", rc, 1)
    check("R3: equal-value diagnostic is explicit",
          "do not demonstrate" in out, True)
    rc, _ = verdict(bound("fail_criterion", value=7.0))
    check("R3: fail_criterion does not invent an agent claim", rc, 0)
    for status, oracle in (("pass", 3.0), ("fail_criterion", 7.0)):
        rc, out = verdict(bound(
            status, value=oracle, claim={"value_numeric": 100.0}
        ))
        check(f"R3: {status} cannot hide a contradictory agent claim", rc, 1)
        check(f"R3: {status} downclassification diagnostic is explicit",
              "does not assert disagreement" in out, True)
        rc, _ = verdict(bound(
            status, value=oracle, claim={"value_numeric": oracle}
        ))
        check(f"R3: {status} may retain an equal numeric agent claim", rc, 0)
    rc, _ = verdict(bound(
        "pass", value=3.0, claim={"value_numeric": 3.0, "unit": "angstrom"}
    ))
    check("R3: plain pass rejects a unit-incompatible asserted claim", rc, 1)
    rc, _ = verdict(bound("pass", value=3.0, claim={"value_text": "three"}))
    check("R3: plain pass rejects an incomparable textual claim", rc, 1)
    for label, malformed_claim in (
        ("numeric plus text", {"value_numeric": 100.0, "value_text": "100"}),
        ("numeric plus n/a", {"value_numeric": 100.0, "is_not_applicable": True}),
        ("numeric plus false n/a flag",
         {"value_numeric": 100.0, "is_not_applicable": False}),
        ("numeric plus null text", {"value_numeric": 100.0, "value_text": None}),
        ("quoted numeric", {"value_numeric": "100"}),
    ):
        rc, out = verdict(bound("pass", value=3.0, claim=malformed_claim))
        check(f"R3: plain pass rejects malformed claim ({label})", rc, 1)
        check(f"R3: malformed claim ({label}) has explicit shape diagnostic",
              "must set exactly one" in out, True)
    for carrier_name, malformed_carrier in (
        ("oracle_measure", {"value_numeric": 3.0, "is_not_applicable": False}),
        ("oracle_measure", {"value_numeric": 3.0, "value_text": None}),
        ("delta", {"value_numeric": 0.0, "is_not_applicable": False}),
        ("delta", {"value_numeric": 0.0, "value_text": None}),
    ):
        row = bound("pass", value=3.0)
        row[carrier_name] = malformed_carrier
        rc, out = verdict(row)
        check(f"shape: malformed {carrier_name} carrier fails", rc, 1)
        check(f"shape: malformed {carrier_name} diagnostic names carrier",
              f"{carrier_name} must set exactly one" in out, True)

    # R4: within-cctbx means exactly that.
    rc, _ = verdict(bound(
        "fail_by_oracle_within_cctbx", value=7.0,
        claim=claim, family="non_cctbx"
    ))
    check("R4: within-cctbx on non-cctbx row fails", rc, 1)
    rc, _ = verdict(bound(
        "fail_by_oracle_within_cctbx", value=7.0,
        claim=claim, family="cctbx"
    ))
    check("R4: within-cctbx on cctbx row passes", rc, 0)
    rc, _ = verdict(bound(
        "fail_by_oracle", value=7.0, claim=claim, family="cctbx"
    ))
    check("R4: uncorroborated cctbx row cannot claim hard failure", rc, 1)
    rc, _ = verdict(bound("pass", value=3.0, family="cctbx"))
    check("R4: uncorroborated cctbx row cannot claim hard pass", rc, 1)
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        cctbx_context = bound(family="cctbx")
        cctbx_context.pop("pass_criterion")
        cctbx_context.pop("pass_criterion_ref")
        cctbx_context["pass_status"] = "informational"
        write_eval(root, [
            cctbx_context,
            bound("fail_by_oracle", value=7.0, claim=claim),
        ])
        rc, _ = run_guard(root)
    check("R4: independent row carries hard verdict; cctbx row stays informational",
          rc, 0)

    # Scalar diagnostics never stringify malformed structures or traceback.
    for field, values in (
        ("pass_criterion", (["a", "b"], {"a": "b"}, 5, True)),
        ("pass_status", (["pass"], {"status": "pass"}, 5, True, [], {})),
        ("pass_criterion_ref", (["CRIT"], {"id": "CRIT"}, 5, True)),
    ):
        for value in values:
            row = bound(family="cctbx") if field == "pass_status" else bound()
            row[field] = value
            rc, out = verdict(row)
            check(f"shape: {field}={value!r} fails", rc, 1)
            check(f"shape: {field}={value!r} has no traceback",
                  "Traceback" in out, False)
            check(f"shape: {field}={value!r} names field", field in out, True)

    row = bound()
    row["pass_status"] = "passed"
    rc, out = verdict(row)
    check("R0: unclassified status fails", rc, 1)
    check("R0: diagnostic says checked by no rule",
          "checked by no rule" in out, True)

    row = bound(value=10**400)
    rc, out = verdict(row)
    check("shape: huge numeric carrier fails", rc, 1)
    check("shape: huge numeric carrier does not traceback",
          "Traceback" in out, False)
    row = bound()
    row["oracle_tool_ref"] = {}
    rc, out = verdict(row)
    check("shape: mapping oracle_tool_ref fails", rc, 1)
    check("shape: mapping oracle_tool_ref has no traceback",
          "Traceback" in out, False)

    # R5: only materially different structured context may diverge. Ordering,
    # duplicates, notes, and YAML-native dates cannot create a bypass.
    def divergent(first: dict, second: dict) -> tuple[int, str]:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_eval(root, [first, second])
            return run_guard(root)

    def r5_base(*, value=3.0) -> dict:
        return bound(
            "pass_with_caveat", value=value,
            claim={"value_numeric": 4.0},
        )

    first = r5_base()
    second = copy.deepcopy(first)
    second["pass_status"] = "pass_criterion_fail_headline"
    rc, out = divergent(first, second)
    check("R5: identical evidence with divergent statuses fails", rc, 1)
    check("R5: diagnostic names both rows",
          "EVAL_x_M_001" in out and "EVAL_x_M_002" in out, True)

    first = r5_base()
    first["evidence_refs"] = ["a", "b"]
    second = copy.deepcopy(first)
    second["pass_status"] = "pass_criterion_fail_headline"
    second["evidence_refs"] = ["b", "a", "a"]
    rc, _ = divergent(first, second)
    check("R5: evidence-ref order/duplicates cannot bypass", rc, 1)

    first = r5_base()
    first["assumptions"] = [{
        "id": "a", "evidence_refs": ["one", "two"],
    }]
    second = copy.deepcopy(first)
    second["pass_status"] = "pass_criterion_fail_headline"
    second["assumptions"][0]["evidence_refs"] = ["two", "one", "one"]
    rc, _ = divergent(first, second)
    check("R5: nested evidence-ref order/duplicates cannot bypass", rc, 1)

    first = r5_base()
    second = copy.deepcopy(first)
    second["pass_status"] = "pass_criterion_fail_headline"
    second["evidence_refs"] = []
    rc, out = divergent(first, second)
    check("R5: absent and empty optional collection are equivalent", rc, 1)
    check("R5: empty-collection case reaches consistency rule",
          "identical scientific context" in out, True)

    first = r5_base(value=3)
    second = copy.deepcopy(first)
    second["pass_status"] = "pass_criterion_fail_headline"
    second["oracle_measure"]["value_numeric"] = 3.0
    rc, out = divergent(first, second)
    check("R5: integer and float spellings are equivalent", rc, 1)
    check("R5: numeric-spelling case reaches consistency rule",
          "identical scientific context" in out, True)

    first = r5_base()
    second = copy.deepcopy(first)
    second["pass_status"] = "pass_criterion_fail_headline"
    second["oracle_measure"]["unit"] = "unitless"
    second["agent_claim"]["unit"] = "dimensionless"
    rc, out = divergent(first, second)
    check("R5: absent and aliased unitless spellings are equivalent", rc, 1)
    check("R5: unitless-alias case reaches consistency rule",
          "identical scientific context" in out, True)

    angstrom_binding = default_binding()
    angstrom_binding["comparison_unit"] = "Å"
    first = r5_base()
    first["oracle_measure"]["unit"] = "angstrom"
    first["agent_claim"]["unit"] = "Å"
    second = copy.deepcopy(first)
    second["pass_status"] = "pass_criterion_fail_headline"
    second["oracle_measure"]["unit"] = "ångström"
    second["agent_claim"]["unit"] = "angstroms"
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        write_schema(root)
        write_bindings(root, bindings=[angstrom_binding])
        catalog_path = root / "ref" / "catalog.yaml"
        catalog = yaml.safe_load(catalog_path.read_text())
        catalog["metric_definitions"][0]["unit"] = "Å"
        catalog_path.write_text(yaml.safe_dump(catalog, sort_keys=False))
        write_test_threshold(root, "pass when < 5 Å")
        write_eval(root, [first, second])
        rc, out = run_guard(root)
    check("R5: angstrom unit aliases are equivalent", rc, 1)
    check("R5: angstrom-alias case reaches consistency rule",
          "identical scientific context" in out, True)

    first = r5_base()
    second = copy.deepcopy(first)
    second["pass_status"] = "pass_criterion_fail_headline"
    second["oracle_measure"]["is_not_applicable"] = False
    rc, out = divergent(first, second)
    check("R5: false oracle carrier flag cannot create a bypass", rc, 1)
    check("R5: false oracle carrier flag is rejected as malformed",
          "oracle_measure must set exactly one" in out, True)

    first = r5_base()
    second = copy.deepcopy(first)
    second["pass_status"] = "pass_criterion_fail_headline"
    second["pass_criterion"] = "  pass when < 5  "
    rc, out = divergent(first, second)
    check("R5: normalized criterion formatting cannot bypass", rc, 1)
    check("R5: criterion-format case reaches consistency rule",
          "identical scientific context" in out, True)

    first = r5_base()
    first["notes"] = "first prose rationale"
    second = copy.deepcopy(first)
    second["pass_status"] = "pass_criterion_fail_headline"
    second["notes"] = "different prose rationale"
    rc, _ = divergent(first, second)
    check("R5: notes alone cannot justify divergent status", rc, 1)

    first = r5_base()
    first["criterion_preconditions"] = [{
        "id": "context", "status": "satisfied", "evidence_refs": ["a"],
        "notes": "first prose rationale",
    }]
    second = copy.deepcopy(first)
    second["pass_status"] = "pass_criterion_fail_headline"
    second["criterion_preconditions"][0]["notes"] = "different prose rationale"
    rc, out = divergent(first, second)
    check("R5: nested notes alone cannot justify divergent status", rc, 1)
    check("R5: nested-notes case reaches consistency rule",
          "identical scientific context" in out, True)

    first = r5_base()
    first["assumptions"] = [{
        "id": "a", "as_of_date": yaml.safe_load("2026-09-22"),
    }]
    second = copy.deepcopy(first)
    second["pass_status"] = "pass_criterion_fail_headline"
    rc, out = divergent(first, second)
    check("R5: YAML-native date is compared without traceback", rc, 1)
    check("R5: YAML-native date emits no traceback", "Traceback" in out, False)

    first = r5_base()
    first["provenance_ref"] = {
        "id": "run", "run_at": datetime(2026, 9, 22, 12, 30),
    }
    second = copy.deepcopy(first)
    second["pass_status"] = "pass_criterion_fail_headline"
    second["provenance_ref"]["run_at"] = "2026-09-22T12:30:00"
    rc, out = divergent(first, second)
    check("R5: native/quoted provenance datetime cannot bypass", rc, 1)
    check("R5: equivalent provenance datetime reaches consistency rule",
          "identical scientific context" in out, True)

    first = r5_base()
    first["assumptions"] = [{
        "id": "a",
        "as_of_date": date(2026, 9, 22),
        "effective_at": datetime(2026, 9, 22, 12, 30),
    }]
    second = copy.deepcopy(first)
    second["pass_status"] = "pass_criterion_fail_headline"
    second["assumptions"][0]["as_of_date"] = "2026-09-22"
    second["assumptions"][0]["effective_at"] = "2026-09-22T12:30:00"
    rc, out = divergent(first, second)
    check("R5: native/quoted nested assumption times cannot bypass", rc, 1)
    check("R5: equivalent nested assumption times reach consistency rule",
          "identical scientific context" in out, True)

    passing = bound("pass", value=3.0)
    failing = bound("fail_criterion", value=7.2)
    failing.update({"scope": "site", "scope_selector": "active_site"})
    rc, _ = divergent(passing, failing)
    check("R5: different scope/value may legitimately diverge", rc, 0)

    first = r5_base()
    first["evidence_refs"] = ["evidence-a"]
    second = copy.deepcopy(first)
    second["pass_status"] = "pass_criterion_fail_headline"
    second["evidence_refs"] = ["evidence-b"]
    rc, _ = divergent(first, second)
    check("R5: different retained evidence is not inferred equivalent", rc, 0)

    row = bound()
    row["oracle_measure"][1] = "malformed key"
    rc, out = verdict(row)
    check("shape: nested non-string mapping key fails", rc, 1)
    check("shape: nested non-string mapping key does not traceback",
          "Traceback" in out, False)
    check("shape: nested non-string mapping key diagnostic is explicit",
          "non-string mapping key" in out, True)

    # Record-shape errors remain contextual rather than raw exceptions.
    for label, payload in (
        ("top-level list", "- not: a mapping\n"),
        ("top-level null", "null\n"),
        ("evaluation_runs empty", "evaluation_runs: []\n"),
        ("evaluation_runs mapping", "evaluation_runs: {}\n"),
        ("evaluation_runs false", "evaluation_runs: false\n"),
        ("evaluation_runs zero", "evaluation_runs: 0\n"),
        ("measurements mapping", "evaluation_runs:\n- id: E\n  measurements: {a: 1}\n"),
        ("measurements empty", "evaluation_runs:\n- id: E\n  measurements: []\n"),
        ("measurements false", "evaluation_runs:\n- id: E\n  measurements: false\n"),
        ("non-mapping row", "evaluation_runs:\n- id: E\n  measurements:\n  - text\n"),
        ("evaluation_runs scalar", "evaluation_runs: 5\n"),
        ("run scalar", "evaluation_runs:\n- text\n"),
        ("measurements scalar", "evaluation_runs:\n- id: E\n  measurements: 5\n"),
        ("cyclic YAML alias", (
            "evaluation_runs:\n- id: E\n  run_date: 2026-09-30\n"
            "  measurements:\n  - &row\n    id: E_M_1\n"
            "    pass_status: informational\n    notes: *row\n"
        )),
        ("unreadable YAML", "evaluation_runs: [\n"),
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_schema(root)
            write_bindings(root)
            (root / "data").mkdir(parents=True)
            (root / "data" / "EVAL_x.yaml").write_text(payload)
            rc, out = run_guard(root)
        check(f"record shape ({label}) fails", rc, 1)
        check(f"record shape ({label}) has no traceback",
              "Traceback" in out, False)

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        write_schema(root)
        write_bindings(root)
        (root / "data").mkdir(parents=True)
        (root / "data" / "EVAL_x_2026-09-30.yaml").write_text(
            "evaluation_runs:\n"
            "- id: EVAL_x\n"
            "  run_date: 2026-09-30\n"
            "  measurements:\n"
            "  - id: EVAL_x_M_001\n"
            "    pass_status: pass\n"
            "    pass_status: informational\n"
        )
        rc, out = run_guard(root)
    check("record shape (duplicate mapping key) fails", rc, 1)
    check("record shape (duplicate mapping key) has no traceback",
          "Traceback" in out, False)
    check("record shape (duplicate mapping key) is explicit",
          "duplicate YAML mapping key 'pass_status'" in out, True)

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        write_schema(root)
        write_bindings(root)
        write_eval(root, [{"pass_status": "informational"}])
        next((root / "data").glob("EVAL_*.yaml")).write_bytes(b"\xff\xfe")
        rc, out = run_guard(root)
    check("record encoding (non-UTF-8 EVAL) fails", rc, 1)
    check("record encoding (non-UTF-8 EVAL) has no traceback",
          "Traceback" in out, False)
    check("record encoding (non-UTF-8 EVAL) has record summary",
          "pass_status records:" in out, True)

    # Schema/config failures get their own summary, separate from row failures.
    schema_payloads = (
        ("top-level list", ["not", "mapping"]),
        ("enums list", {"enums": []}),
        ("PassStatus list", {"enums": {"PassStatus": []}}),
        ("permissible_values list", {
            "enums": {"PassStatus": {"permissible_values": []}}
        }),
    )
    for label, payload in schema_payloads:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_schema(root, payload=payload)
            write_bindings(root)
            write_eval(root, [{"pass_status": "informational"}])
            rc, out = run_guard(root)
        check(f"schema shape ({label}) fails", rc, 1)
        check(f"schema shape ({label}) has no traceback",
              "Traceback" in out, False)
        check(f"schema shape ({label}) has schema summary",
              "pass_status schema/registry:" in out, True)

    authority_paths = (
        ("schema", SCHEMA_REL),
        ("binding registry", BINDINGS_REL),
        ("threshold registry", THRESHOLD_REL),
        ("catalog", Path("ref") / "catalog.yaml"),
    )
    for label, relative_path in authority_paths:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_schema(root)
            write_bindings(root)
            write_eval(root, [{"pass_status": "informational"}])
            (root / relative_path).write_bytes(b"\xff\xfe")
            rc, out = run_guard(root)
        check(f"authority encoding ({label}) fails", rc, 1)
        check(f"authority encoding ({label}) has no traceback",
              "Traceback" in out, False)
        check(f"authority encoding ({label}) has schema summary",
              "pass_status schema/registry:" in out, True)

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        write_eval(root, [{"pass_status": "informational"}])
        write_schema(root, REAL_STATUSES + ("inconclusive",))
        rc, out = run_guard(root)
    check("schema drift: extra enum fails", rc, 1)
    check("schema drift: schema count is separate",
          "schema/registry: 1 violation" in out, True)
    check("schema drift: record summary is absent",
          "pass_status records:" in out, False)

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        write_eval(root, [{"pass_status": "informational"}])
        write_schema(root, tuple(
            status for status in REAL_STATUSES if status != "pass"
        ))
        rc, out = run_guard(root)
    check("schema drift: missing guarded enum fails", rc, 1)
    check("schema drift: missing enum is named", "omits guarded PassStatus 'pass'" in out, True)

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        write_eval(root, [{"pass_status": "pass"}])
        write_schema(root, REAL_STATUSES + ("inconclusive",))
        rc, out = run_guard(root)
    check("mixed schema and record failures fail", rc, 1)
    check("mixed failures report schema separately",
          "schema/registry: 1 violation" in out, True)
    check("mixed failures report records separately",
          "pass_status records:" in out, True)

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        write_schema(root)
        write_bindings(root)
        binding_path = root / BINDINGS_REL
        binding_text = binding_path.read_text()
        binding_path.write_text(binding_text.replace(
            "  effective_from: '2026-09-01'\n",
            "  effective_from: '2026-09-01'\n"
            "  effective_from: '2026-09-02'\n",
            1,
        ))
        write_eval(root, [{"pass_status": "informational"}])
        rc, out = run_guard(root)
    check("registry shape (duplicate mapping key) fails", rc, 1)
    check("registry shape (duplicate mapping key) has no traceback",
          "Traceback" in out, False)
    check("registry shape (duplicate mapping key) is explicit",
          "duplicate YAML mapping key 'effective_from'" in out, True)

    malformed_registries = [
        ("root list", ["not", "mapping"]),
        ("bindings missing", {"criteria": []}),
        ("bindings mapping", {"pass_criterion_bindings": {"id": "x"}}),
        ("entry scalar", {"pass_criterion_bindings": ["x"]}),
        ("blank id", {"pass_criterion_bindings": [
            {**default_binding(), "id": " "}
        ]}),
        ("bad section", {"pass_criterion_bindings": [
            {**default_binding(), "threshold_registry_section": "2"}
        ]}),
        ("missing registry row", {"pass_criterion_bindings": [
            {**default_binding(), "threshold_registry_row": "Absent row"}
        ]}),
        ("missing registry column", {"pass_criterion_bindings": [{
            key: value for key, value in default_binding().items()
            if key != "threshold_registry_column"
        }]}),
        ("nonnumeric registry column", {"pass_criterion_bindings": [
            {**default_binding(), "threshold_registry_column": "2"}
        ]}),
        ("label registry column", {"pass_criterion_bindings": [
            {**default_binding(), "threshold_registry_column": 1}
        ]}),
        ("out-of-range registry column", {"pass_criterion_bindings": [
            {**default_binding(), "threshold_registry_column": 4}
        ]}),
        ("missing comparison operand", {"pass_criterion_bindings": [{
            key: value for key, value in default_binding().items()
            if key != "comparison_operand"
        }]}),
        ("missing comparison transform", {"pass_criterion_bindings": [{
            key: value for key, value in default_binding().items()
            if key != "comparison_transform"
        }]}),
        ("missing comparison unit", {"pass_criterion_bindings": [{
            key: value for key, value in default_binding().items()
            if key != "comparison_unit"
        }]}),
        ("missing effective_from", {"pass_criterion_bindings": [{
            key: value for key, value in default_binding().items()
            if key != "effective_from"
        }]}),
        ("invalid effective_from", {"pass_criterion_bindings": [
            {**default_binding(), "effective_from": "September 1"}
        ]}),
        ("reversed effective interval", {"pass_criterion_bindings": [
            {**default_binding(), "effective_from": "2026-09-10",
             "effective_until": "2026-09-01"}
        ]}),
        ("self supersession", {"pass_criterion_bindings": [
            {**default_binding(), "supersedes_ref": CRITERION_ID}
        ]}),
        ("invalid comparison operand", {"pass_criterion_bindings": [
            {**default_binding(), "comparison_operand": "agent_claim"}
        ]}),
        ("invalid comparison transform", {"pass_criterion_bindings": [
            {**default_binding(), "comparison_transform": "signed"}
        ]}),
        ("unsupported absolute transform", {"pass_criterion_bindings": [
            {**default_binding(), "comparison_transform": "absolute"}
        ]}),
        ("mixed binding keys", {"pass_criterion_bindings": [
            {**default_binding(), 1: "bad"}
        ]}),
        ("missing applicability", {"pass_criterion_bindings": [{
            key: value for key, value in default_binding().items()
            if key != "applicability"
        }]}),
        ("duplicate id", {"pass_criterion_bindings": [
            default_binding(), default_binding()
        ]}),
    ]
    alias = default_binding()
    alias["id"] = "CRIT_ALIAS"
    malformed_registries.append(("duplicate semantics", {
        "pass_criterion_bindings": [default_binding(), alias]
    }))
    semantic_alias = default_binding()
    semantic_alias["id"] = "CRIT_ALIAS_REORDERED"
    semantic_alias["applicability"]["scopes"].reverse()
    semantic_alias["applicability"]["oracle_families"].reverse()
    malformed_registries.append(("duplicate reordered/extractor semantics", {
        "pass_criterion_bindings": [default_binding(), semantic_alias]
    }))
    for field in (
        "catalog_task_refs", "stages", "scopes", "oracle_tool_refs",
        "oracle_families",
    ):
        binding = default_binding()
        binding["applicability"][field] = []
        malformed_registries.append((f"empty {field}", {
            "pass_criterion_bindings": [binding]
        }))
        binding = default_binding()
        binding["applicability"][field].append(
            binding["applicability"][field][0]
        )
        malformed_registries.append((f"duplicate {field}", {
            "pass_criterion_bindings": [binding]
        }))
    for field, value in (
        ("stages", "finished"),
        ("scopes", "whole_model"),
        ("oracle_families", "web_service"),
    ):
        binding = default_binding()
        binding["applicability"][field] = [value]
        malformed_registries.append((f"invalid vocabulary {field}", {
            "pass_criterion_bindings": [binding]
        }))
    binding = default_binding()
    binding["applicability"]["oracle_tool_refs"] = ["missing oracle"]
    binding["applicability"]["oracle_families"] = ["non_cctbx"]
    malformed_registries.append(("missing catalog oracle tool", {
        "pass_criterion_bindings": [binding]
    }))
    binding = default_binding()
    binding["applicability"]["oracle_families"] = ["non_cctbx"]
    malformed_registries.append(("binding tool-family set mismatch", {
        "pass_criterion_bindings": [binding]
    }))
    binding = default_binding()
    binding["applicability"]["catalog_task_refs"] = ["T01"]
    malformed_registries.append(("metric/task mismatch", {
        "pass_criterion_bindings": [binding]
    }))
    binding = default_binding()
    binding["applicability"][1] = ["bad"]
    malformed_registries.append(("mixed applicability keys", {
        "pass_criterion_bindings": [binding]
    }))
    binding = default_binding()
    binding["applicability"]["required_precondition_ids"] = ["same", "same"]
    malformed_registries.append(("duplicate required precondition", {
        "pass_criterion_bindings": [binding]
    }))
    binding = default_binding()
    binding["applicability"]["requires_agent_claim"] = "no"
    malformed_registries.append(("nonboolean requires_agent_claim", {
        "pass_criterion_bindings": [binding]
    }))
    binding = default_binding()
    binding["applicability"]["prose_precondition"] = "matched H build"
    malformed_registries.append(("unsupported prose applicability", {
        "pass_criterion_bindings": [binding]
    }))

    for label, payload in malformed_registries:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_schema(root)
            write_bindings(root, payload=payload)
            write_eval(root, [{"pass_status": "informational"}])
            rc, out = run_guard(root)
        check(f"registry shape ({label}) fails", rc, 1)
        check(f"registry shape ({label}) has no traceback",
              "Traceback" in out, False)
        check(f"registry shape ({label}) has schema summary",
              "pass_status schema/registry:" in out, True)

    # Registry prose, provenance, operand wording, and catalog cross-links are
    # all authoritative rather than optional reviewer guidance.
    for label, criterion, binding_update, provenance in (
        ("missing provenance", "pass when < 5", {}, ""),
        ("unknown provenance", "pass when < 5", {}, "[opinion]"),
        ("unsupported condition prose",
         "pass when < 5 only when matched selections", {}, "[benchmark]"),
        ("omitted structured precondition",
         "pass when < 5 [requires: matched_selection]", {}, "[benchmark]"),
        ("explicit delta bound as oracle_measure",
         "pass when abs(delta) < 5",
         {"comparison_transform": "absolute"}, "[benchmark]"),
    ):
        binding = default_binding()
        binding.update(binding_update)
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_schema(root)
            write_bindings(root, bindings=[binding])
            write_test_threshold(root, criterion, provenance)
            write_eval(root, [{"pass_status": "informational"}])
            rc, out = run_guard(root)
        check(f"registry authority ({label}) fails", rc, 1)
        check(f"registry authority ({label}) has no traceback",
              "Traceback" in out, False)

    moved_tag_binding = default_binding()
    moved_tag_binding["threshold_registry_row"] = "Test metric [benchmark]"
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        write_schema(root)
        write_bindings(root, bindings=[moved_tag_binding])
        (root / THRESHOLD_REL).write_text(
            "# Threshold registry\n\n"
            "## 2. Test thresholds\n\n"
            "| Metric | Criterion | Provenance |\n"
            "|---|---|---|\n"
            "| Test metric [benchmark] | pass when < 5 | no retained source |\n"
        )
        write_eval(root, [{"pass_status": "informational"}])
        rc, out = run_guard(root)
    check("registry authority (tag moved out of provenance cell) fails", rc, 1)
    check("registry authority (tag moved out of provenance cell) is explicit",
          "Provenance/Source cell" in out, True)

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        write_schema(root)
        write_bindings(root)
        (root / THRESHOLD_REL).write_text(
            "# Threshold registry\n\n"
            "## 2. Intended section\n\n"
            "No threshold table is defined here.\n\n"
            "## Appendix\n\n"
            "| Metric | Criterion | Provenance |\n"
            "|---|---|---|\n"
            "| Test metric | pass when < 5 | [benchmark] |\n"
        )
        write_eval(root, [{"pass_status": "informational"}])
        rc, out = run_guard(root)
    check("registry authority (unnumbered H2 cannot bleed into section) fails", rc, 1)
    check("registry authority (wrong-section row is unresolved)",
          "must resolve exactly once, found 0" in out, True)

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        write_schema(root)
        write_bindings(root)
        (root / THRESHOLD_REL).write_text(
            "# Threshold registry\n\n"
            "## 2. Intended section\n\n"
            "No threshold table is defined here.\n\n"
            "## 2. Duplicate section\n\n"
            "| Metric | Criterion | Provenance |\n"
            "|---|---|---|\n"
            "| Test metric | pass when < 5 | [benchmark] |\n"
        )
        write_eval(root, [{"pass_status": "informational"}])
        rc, out = run_guard(root)
    check("registry authority (duplicate numbered H2 fails)", rc, 1)
    check("registry authority (duplicate numbered H2 is explicit)",
          "must have exactly one canonical numbered H2 heading, found 2" in out,
          True)

    for hidden_kind, before, after, indent in (
        ("fenced-code", "```markdown\n", "```\n", ""),
        ("HTML-comment", "<!--\n", "-->\n", ""),
        ("indented-code", "", "", "    "),
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_schema(root)
            write_bindings(root)
            hidden_table = "".join(
                indent + line + "\n" for line in (
                    "| Metric | Criterion | Provenance |",
                    "|---|---|---|",
                    "| Test metric | pass when < 5 | [benchmark] |",
                )
            )
            (root / THRESHOLD_REL).write_text(
                "# Threshold registry\n\n"
                "## 2. Intended section\n\n"
                + before + hidden_table + after
            )
            write_eval(root, [{"pass_status": "informational"}])
            rc, out = run_guard(root)
        check(f"registry authority ({hidden_kind} table fails)", rc, 1)
        check(f"registry authority ({hidden_kind} row is unresolved)",
              "must resolve exactly once, found 0" in out, True)

    for html_tag, opener, closer in (
        ("pre", "<pre>", "</pre>"),
        ("div", "<div>", "</div>"),
        ("unterminated-pre-opener", "<pre", "</pre>"),
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_schema(root)
            write_bindings(root)
            (root / THRESHOLD_REL).write_text(
                "# Threshold registry\n\n"
                "## 2. Intended section\n\n"
                f"{opener}\n"
                "| Metric | Criterion | Provenance |\n"
                "|---|---|---|\n"
                "| Test metric | pass when < 5 | [benchmark] |\n"
                f"{closer}\n"
            )
            write_eval(root, [{"pass_status": "informational"}])
            rc, out = run_guard(root)
        check(f"registry authority (raw HTML {html_tag} block fails)", rc, 1)
        check(f"registry authority (raw HTML {html_tag} diagnostic is explicit)",
              "cannot contain raw HTML block openers" in out, True)

    selected_provenance = default_binding()
    selected_provenance["threshold_registry_column"] = 3
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        write_schema(root)
        write_bindings(root, bindings=[selected_provenance])
        write_test_threshold(root, provenance="pass when < 5 [benchmark]")
        write_eval(root, [{"pass_status": "informational"}])
        rc, out = run_guard(root)
    check("registry authority (criterion cannot select provenance cell) fails", rc, 1)
    check("registry authority (selected provenance cell is explicit)",
          "cannot select the dedicated Provenance/Source cell" in out, True)

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        write_schema(root)
        write_bindings(root)
        (root / THRESHOLD_REL).write_text(
            "# Threshold registry\n\n"
            "## 2. Intended section\n\n"
            "| Metric | Criterion | **Provenance** | SOURCE |\n"
            "|---|---|---|---|\n"
            "| Test metric | pass when < 5 | [benchmark] | [literature] |\n"
        )
        write_eval(root, [{"pass_status": "informational"}])
        rc, out = run_guard(root)
    check("registry authority (duplicate normalized provenance headers) fails", rc, 1)
    check("registry authority (duplicate provenance headers are explicit)",
          "must have exactly one Provenance or Source column" in out, True)

    for label, mutate_catalog in (
        ("duplicate tool id",
         lambda catalog: catalog["tools"].append(
             copy.deepcopy(catalog["tools"][0])
         )),
        ("non-string tool family",
         lambda catalog: catalog["tools"][0].update({"family": []})),
        ("task omits bound metric",
         lambda catalog: catalog["catalog_tasks"][0].update({
             "metric_definition_refs": []
         })),
        ("task omits bound tool",
         lambda catalog: catalog["catalog_tasks"][0].update({
             "oracle_tool_refs": [], "phenix_tool_refs": []
         })),
        ("tool omits served task",
         lambda catalog: catalog["tools"][0].update({
             "catalog_tasks_served": []
         })),
    ):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_schema(root)
            write_bindings(root)
            catalog_path = root / "ref" / "catalog.yaml"
            catalog = yaml.safe_load(catalog_path.read_text())
            mutate_catalog(catalog)
            catalog_path.write_text(yaml.safe_dump(catalog, sort_keys=False))
            write_eval(root, [{"pass_status": "informational"}])
            rc, out = run_guard(root)
        check(f"catalog binding contract ({label}) fails", rc, 1)
        check(f"catalog binding contract ({label}) has no traceback",
              "Traceback" in out, False)

    def two_binding_fixture(
        second: dict, second_cell: str, *, first: dict | None = None,
    ) -> tuple[int, str]:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_schema(root)
            write_bindings(root, bindings=[first or default_binding(), second])
            (root / THRESHOLD_REL).write_text(
                "# Threshold registry\n\n## 2. Test thresholds\n\n"
                "| Metric | Criterion | Provenance |\n|---|---|---|\n"
                "| Test metric | pass when < 5 | [benchmark] |\n"
                f"| Easy metric | {second_cell} | [benchmark] |\n"
            )
            write_eval(root, [{"pass_status": "informational"}])
            return run_guard(root)

    easier = default_binding()
    easier.update({
        "id": "CRIT_EASY", "threshold_registry_row": "Easy metric",
    })
    rc, _ = two_binding_fixture(easier, "pass when < 50")
    check("temporal registry: overlapping threshold choices fail", rc, 1)

    alternate_operand = copy.deepcopy(easier)
    alternate_operand.update({
        "comparison_operand": "delta", "comparison_transform": "absolute",
    })
    rc, _ = two_binding_fixture(
        alternate_operand, "pass when |delta| < 1"
    )
    check("temporal registry: overlapping operand choices fail", rc, 1)

    retired = default_binding()
    retired["effective_until"] = "2026-09-15"
    successor = copy.deepcopy(easier)
    successor.update({
        "effective_from": "2026-09-16", "supersedes_ref": CRITERION_ID,
    })
    rc, _ = two_binding_fixture(successor, "pass when < 50", first=retired)
    check("temporal registry: nonoverlapping linked successor passes", rc, 0)

    unlinked_successor = copy.deepcopy(successor)
    unlinked_successor.pop("supersedes_ref")
    rc, _ = two_binding_fixture(
        unlinked_successor, "pass when < 50", first=retired
    )
    check("temporal registry: later same-context version must link", rc, 1)

    wrong_context_successor = copy.deepcopy(successor)
    wrong_context_successor["applicability"]["scopes"] = ["site"]
    rc, _ = two_binding_fixture(
        wrong_context_successor, "pass when < 50", first=retired
    )
    check("temporal registry: supersession cannot change context", rc, 1)

    partial_successor = copy.deepcopy(unlinked_successor)
    partial_successor["applicability"]["scopes"] = ["complex"]
    rc, out = two_binding_fixture(
        partial_successor, "pass when < 50", first=retired
    )
    check("temporal registry: unlinked partial context change fails", rc, 1)
    check("temporal registry: partial context diagnostic is explicit",
          "partly overlapping grading context" in out, True)

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        write_schema(root)
        write_bindings(root, bindings=[])
        write_eval(root, [{"pass_status": "informational"}])
        rc, _ = run_guard(root)
    check("an empty prospective binding registry is valid", rc, 0)

    with tempfile.TemporaryDirectory() as tmpdir:
        fixture = Path(tmpdir) / "structural_criteria.yaml"
        fixture.write_text(yaml.safe_dump({
            "criteria": [], "pass_criterion_bindings": [default_binding()],
        }, sort_keys=False))
        proc = subprocess.run(
            [
                sys.executable, "-c",
                "from linkml.validator.cli import cli; cli()",
                "--schema", str(REPO / "schemas" / "structural_criteria.yaml"),
                str(fixture),
            ],
            capture_output=True,
            text=True,
        )
    check("nonempty binding fixture validates against LinkML schema",
          proc.returncode, 0)

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        write_schema(root)
        write_bindings(root)
        (root / "data").mkdir()
        rc, out = run_guard(root)
    check("empty scan fails", rc, 1)
    check("empty scan says why", "empty scan" in out, True)

    # Pin every legacy exemption independently of implementation iteration.
    spec = importlib.util.spec_from_file_location("_guard", GUARD)
    guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(guard)
    expected_placeholders = {
        "n/a", "na", "-", "--", "tbd", "todo", "none", "see notes",
        "informational", "pass", "fail_criterion", "fail_by_oracle",
        "pass_with_caveat", "pass_criterion_fail_headline",
        "fail_by_oracle_within_cctbx", "criterion_inapplicable",
    }
    check("placeholder set is exactly documented",
          guard.PLACEHOLDER_CRITERIA, frozenset(expected_placeholders))

    legacy_1sar_path = (
        "data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-04-24.yaml"
    )
    legacy_1sar_run = "EVAL_1sar_cdba2c07_2026-04-24"
    legacy_synth_path = "data/examples/eval/EVAL_synth_active_site_2026-04-26.yaml"
    legacy_synth_run = "EVAL_synth_active_site_2026-04-26"
    expected_file_hashes = {
        legacy_1sar_path:
            "b3beb751fb99c94376002d88ccb7f8716b1dd4ae8177c40ff53b29ab12350532",
        legacy_synth_path:
            "624435778056f93eea841f9062ce76a6dc78513f4361fc0e2ab6b6264dd6919e",
    }
    check("legacy file exceptions are exact-path, not date keyed",
          guard.LEGACY_UNREGISTERED_CRITERION_FILES, expected_file_hashes)
    rows_by_location: dict[tuple[str, str, str], dict] = {}
    for relative_path, expected_hash in sorted(expected_file_hashes.items()):
        path = REPO / relative_path
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        check(f"legacy file hash matches committed bytes: {relative_path}",
              actual_hash, expected_hash)
        document = yaml.safe_load(path.read_text())
        for run in document["evaluation_runs"]:
            for row in run.get("measurements", []):
                rows_by_location[(relative_path, run["id"], row["id"])] = row

    expected_rows = {
        ("R2", legacy_1sar_path, legacy_1sar_run, f"{legacy_1sar_run}_M_003"): "009f755bd9ba09823ad13ae4a92d274137fdf23153192fec88ceff5f727a6227",
        ("R2", legacy_1sar_path, legacy_1sar_run, f"{legacy_1sar_run}_M_012"): "910631fb5558df5cf2a0b425668d8fb7edfd54ba86552a0a5a7adbaffdda9e71",
        ("R2", legacy_1sar_path, legacy_1sar_run, f"{legacy_1sar_run}_M_017"): "a340b481966cd3fd1683ee32a8c203bb64a0586045c772b2ac66b53d4bef43ed",
        ("R2", legacy_1sar_path, legacy_1sar_run, f"{legacy_1sar_run}_M_018"): "73194e8be2b8aa13cdf5e93018bfd0a14f41aca9b97a88fd51c20aea0d26eecb",
        ("R2", legacy_1sar_path, legacy_1sar_run, f"{legacy_1sar_run}_M_028"): "94b947bc8c219ca61dff0cf531b297cca425d8de42167d109b8b797c2a2b0d72",
        ("R2", legacy_1sar_path, legacy_1sar_run, f"{legacy_1sar_run}_M_032"): "d84d323b7330e83664a2e29c3676d96dd844632eaeced0752a558be2bbc424e1",
        ("R2", legacy_1sar_path, legacy_1sar_run, f"{legacy_1sar_run}_M_033"): "86d5e41767c4d1863e3f62e5e23fa8d11fff29b60ea0f97f471d64d877480a3b",
        ("R3", legacy_1sar_path, legacy_1sar_run, f"{legacy_1sar_run}_M_prosmart_asn_a39_score"): "15757236cfd5525302634734a8e49db9cd4fb2bd6f5467e25ff81e29f15d2024",
        ("R3", legacy_1sar_path, legacy_1sar_run, f"{legacy_1sar_run}_M_021"): "87db4746d39fdc810b4b943aa23e74d447f5d082acbd3c8b03f1b6af47a7c160",
        ("R3", legacy_1sar_path, legacy_1sar_run, f"{legacy_1sar_run}_M_ca_b_vs_mean_ratio"): "f21f4c015e1c446f028811d4c5234827e9a1238705095b655cf2bca7c7b02359",
        ("R3", legacy_1sar_path, legacy_1sar_run, f"{legacy_1sar_run}_M_ca_b_vs_protein"): "90d810d5c60d7cf0b63135eb467c78e0aed60c18b8398b1a7a11cd2238ed10d1",
        ("R3", legacy_1sar_path, legacy_1sar_run, f"{legacy_1sar_run}_M_water_rscc_distribution"): "1e6d72b5901dff6f28b699b258df0c2a36859cfa8ca2386e3945a181a3cddbfa",
        ("R3", legacy_1sar_path, legacy_1sar_run, f"{legacy_1sar_run}_M_ca_identity_z_ca"): "2edb31a055f89c2b322de980091eb1a0f72b8c44e8a5b5c37bff87deb8a82369",
        ("R3", legacy_1sar_path, legacy_1sar_run, f"{legacy_1sar_run}_M_ca_identity_summary"): "72232ed456585690cb37e93ebd1b62d1f735c523c887d8f9e1c976d048c87f5d",
        ("R3", legacy_1sar_path, legacy_1sar_run, f"{legacy_1sar_run}_M_na_identity_z_na"): "eff0e67eeef0f5b01f69f5389604f49ce993685dab38a3cc4a80a51d3d07e86f",
        ("R3", legacy_1sar_path, legacy_1sar_run, f"{legacy_1sar_run}_M_na_identity_summary"): "fa4370a601c7877f807901931d249aaa52888d894788a0d386fb47b331f45219",
        ("R2", legacy_1sar_path, legacy_1sar_run, f"{legacy_1sar_run}_M_ca_identity_z_mg"): "bca36de110182c252bd8e5678cb0c7a24621a32170e628df68c3199e0c9a40b0",
        ("R2", legacy_1sar_path, legacy_1sar_run, f"{legacy_1sar_run}_M_na_identity_z_mg"): "ccd363dff8f3b18148f41edf9a15733778f2260ff687c03413aca13daf69cda0",
        ("R2", legacy_1sar_path, legacy_1sar_run, f"{legacy_1sar_run}_M_t13_wilson_b"): "c459413d2cb056afc8f62744638b5c4ce032f513c7293e6f68dbfbc8a97a3fe1",
        ("R2", legacy_1sar_path, legacy_1sar_run, f"{legacy_1sar_run}_M_t13_aimless_attempt"): "1de274aadddc8e3aacc71b67cd0e4d3083134f1fc5c608b584d82cda28970ac2",
        ("R2", legacy_1sar_path, legacy_1sar_run, f"{legacy_1sar_run}_M_t13_ice_ring_flags"): "495891793a0f0e3c99d5b179316d8f93e8ee93554d5c28def2629bf5ed45cbd6",
        ("R3", legacy_synth_path, legacy_synth_run, f"{legacy_synth_run}_M_002"): "6f1f4f0e77d56da2bdb852585f7f18e716687b05e2bebcd36aaae605c17c0b43",
        ("R3", legacy_synth_path, legacy_synth_run, f"{legacy_synth_run}_M_003"): "99cc84d46ee1b69f8ff675772e242391e255204fb64091c54f53d725e44b89fa",
        ("R3", legacy_synth_path, legacy_synth_run, f"{legacy_synth_run}_M_004"): "ebb78ed816028c4ed31e3757f678e9bf8cc069dbd74f4cddc8d5ec4a685d0a1c",
    }
    check("exactly twenty-four row-level legacy exceptions remain",
          guard.LEGACY_ROW_EXCEPTIONS, expected_rows)
    for key, expected_digest in expected_rows.items():
        rule, relative_path, run_id, row_id = key
        check(f"legacy rule {row_id} is R2 or R3", rule in {"R2", "R3"}, True)
        row = rows_by_location[(relative_path, run_id, row_id)]
        payload = json.dumps(
            row, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            default=lambda value: (
                {"__yaml_scalar_type__": type(value).__name__,
                 "value": value.isoformat()}
                if isinstance(value, (date, datetime)) else
                {"__python_type__": type(value).__name__, "value": repr(value)}
            ),
        ).encode("utf-8")
        check(f"legacy row {row_id} digest matches",
              hashlib.sha256(payload).hexdigest(), expected_digest)

    rc, out = run_guard(REPO)
    check("committed records satisfy the guard", rc, 0)
    check("committed guard reports checked count",
          "measurements checked" in out, True)
    check("committed guard reports twenty-six explicit exceptions",
          "26 explicit legacy exception(s)" in out, True)

    print(f"\n{PASSED} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
