#!/usr/bin/env python3
"""Unit tests for the pass_status semantics gate (#567).

Fixture-driven. The load-bearing case is the one that actually shipped during
the 2026-09-07 1SAR review: a row marked `pass` whose criterion lived only in
its `notes`, with `pass_criterion` empty. That must fail regardless of date.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
GUARD = REPO / "scripts" / "check_pass_status.py"
PASSED = 0

POST = "2026-09-30"   # after CUTOVER
PRE = "2026-04-24"    # before CUTOVER


def check(label: str, got, want) -> None:
    global PASSED
    if got != want:
        print(f"FAIL  {label}: got {got!r}, want {want!r}")
        sys.exit(1)
    PASSED += 1
    print(f"PASS  {label}")


def run_guard(root: Path) -> tuple[int, str]:
    proc = subprocess.run([sys.executable, str(GUARD), "--root", str(root)],
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


SCHEMA_REL = Path("schemas") / "protstruct_review.yaml"


def write_schema(root: Path, statuses) -> None:
    """Write a minimal schema declaring the given PassStatus values."""
    (root / "schemas").mkdir(parents=True, exist_ok=True)
    doc = {"enums": {"PassStatus": {
        "permissible_values": {s: {"description": s} for s in statuses}}}}
    (root / SCHEMA_REL).write_text(yaml.safe_dump(doc, sort_keys=False))


REAL_STATUSES = ("pass", "fail_by_oracle", "pass_with_caveat",
                 "pass_criterion_fail_headline", "fail_by_oracle_within_cctbx",
                 "informational")


def write_eval(root: Path, run_date: str, row: dict) -> None:
    (root / "data").mkdir(parents=True, exist_ok=True)
    if not (root / SCHEMA_REL).exists():
        write_schema(root, REAL_STATUSES)
    row = {"id": "EVAL_x_M_001", **row}
    doc = {"evaluation_runs": [{"id": "EVAL_x", "run_date": run_date,
                                "measurements": [row]}]}
    (root / "data" / "EVAL_x.yaml").write_text(yaml.safe_dump(doc, sort_keys=False))


def verdict(run_date: str, row: dict) -> tuple[int, str]:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        write_eval(root, run_date, row)
        return run_guard(root)


def main() -> int:
    claim = {"value_numeric": 0.149}

    # R1 — every criterion-bearing status, both sides of the cutover. Table-driven
    # so that dropping any one status from CRITERION_BEARING fails a test.
    for status in ("pass", "fail_by_oracle", "pass_with_caveat",
                   "pass_criterion_fail_headline", "fail_by_oracle_within_cctbx"):
        row = {"pass_status": status, "oracle_family": "cctbx", "agent_claim": claim}
        for date, label in ((POST, "post"), (PRE, "pre")):
            rc, out = verdict(date, row)
            check(f"R1 {label}-cutover: {status} with no criterion fails", rc, 1)
            check(f"R1 {label}-cutover: {status} names the row", "EVAL_x_M_001" in out, True)
        rc, _ = verdict(POST, {**row, "pass_criterion": "offset in 0.005-0.015"})
        check(f"R1: {status} with a criterion passes", rc, 0)

    rc, _ = verdict(POST, {"pass_status": "pass", "pass_criterion": "   "})
    check("R1: a whitespace-only criterion is not a criterion", rc, 1)
    for placeholder in ("n/a", "TBD", "see notes", "informational", "-"):
        rc, _ = verdict(POST, {"pass_status": "pass", "pass_criterion": placeholder})
        check(f"R1: {placeholder!r} does not count as a criterion", rc, 1)

    # R0 — a status no rule set classifies must not sail through.
    rc, out = verdict(POST, {"pass_status": "passed", "pass_criterion": "< 0.05"})
    check("R0: an unclassified status fails", rc, 1)
    check("R0: says it is checked by no rule", "checked by no rule" in out, True)

    # R2 — informational must not carry a criterion; grandfathered before cutover.
    rc, _ = verdict(POST, {"pass_status": "informational", "pass_criterion": "< 0.05"})
    check("R2 post-cutover: informational + criterion fails", rc, 1)
    rc, out = verdict(PRE, {"pass_status": "informational", "pass_criterion": "< 0.05"})
    check("R2 pre-cutover: grandfathered, not failed", rc, 0)
    check("R2 pre-cutover: listed by name", "grandfathered" in out, True)
    rc, _ = verdict(POST, {"pass_status": "informational"})
    check("R2: bare informational passes", rc, 0)

    # R3 — a disagreement status needs a claim; grandfathered before cutover.
    rc, _ = verdict(POST, {"pass_status": "fail_by_oracle", "pass_criterion": "match within 0.005"})
    check("R3 post-cutover: fail_by_oracle without agent_claim fails", rc, 1)
    rc, _ = verdict(PRE, {"pass_status": "fail_by_oracle", "pass_criterion": "match within 0.005"})
    check("R3 pre-cutover: grandfathered", rc, 0)
    rc, _ = verdict(POST, {"pass_status": "fail_by_oracle",
                           "pass_criterion": "match within 0.005", "agent_claim": claim})
    check("R3: with a claim, passes", rc, 0)

    # R4 — the within-cctbx status must be a cctbx row. Always enforced.
    rc, _ = verdict(PRE, {"pass_status": "fail_by_oracle_within_cctbx",
                          "pass_criterion": "match within 0.005",
                          "agent_claim": claim, "oracle_family": "non_cctbx"})
    check("R4: within_cctbx on a non-cctbx row fails even pre-cutover", rc, 1)
    rc, _ = verdict(POST, {"pass_status": "fail_by_oracle_within_cctbx",
                           "pass_criterion": "match within 0.005",
                           "agent_claim": claim, "oracle_family": "cctbx"})
    check("R4: within_cctbx on a cctbx row passes", rc, 0)

    # R3 — the within-cctbx variant needs a claim too (guards CLAIM_BEARING).
    rc, _ = verdict(POST, {"pass_status": "fail_by_oracle_within_cctbx",
                           "pass_criterion": "match within 0.005",
                           "oracle_family": "cctbx"})
    check("R3: within_cctbx without agent_claim fails", rc, 1)

    # A row with no status at all is not this guard's business.
    rc, _ = verdict(POST, {"metric_definition_ref": "T03_r-work"})
    check("a row without pass_status is ignored", rc, 0)

    # A missing run_date must enforce, not exempt — the fail-closed direction.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "data").mkdir(parents=True)
        write_schema(root, REAL_STATUSES)
        (root / "data" / "EVAL_x.yaml").write_text(yaml.safe_dump(
            {"evaluation_runs": [{"id": "EVAL_x", "measurements": [
                {"id": "EVAL_x_M_001", "pass_status": "informational",
                 "pass_criterion": "< 0.05"}]}]}, sort_keys=False))
        rc, _ = run_guard(root)
    check("a missing run_date enforces rather than exempts", rc, 1)

    # An empty scan is an error, not a pass — zero files must never read as all-valid.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "data").mkdir(parents=True)
        write_schema(root, REAL_STATUSES)
        rc, out = run_guard(root)
    check("an empty scan fails", rc, 1)
    check("an empty scan says why", "empty scan" in out, True)

    # Malformed shapes fail with a message, not a traceback.
    for label, payload in (
        ("top-level list", "- not: a mapping\n"),
        ("measurements as a mapping", "evaluation_runs:\n- id: E\n  measurements: {a: 1}\n"),
        ("non-mapping row", "evaluation_runs:\n- id: E\n  measurements:\n  - just-a-string\n"),
        ("evaluation_runs as a scalar", "evaluation_runs: 5\n"),
        ("evaluation_runs entry as a scalar", "evaluation_runs:\n- just-a-string\n"),
        ("measurements as a scalar", "evaluation_runs:\n- id: E\n  measurements: 5\n"),
        ("unreadable YAML", "evaluation_runs: [\n"),
    ):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "data").mkdir(parents=True)
            write_schema(root, REAL_STATUSES)
            (root / "data" / "EVAL_x.yaml").write_text(payload)
            rc, out = run_guard(root)
        check(f"malformed ({label}) fails", rc, 1)
        check(f"malformed ({label}) reports, not crashes", "Traceback" not in out, True)

    # The schema-drift defence: a PassStatus the guard has no rule for must fail,
    # and an unreadable or enum-less schema must not silently disable the check.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        write_eval(root, POST, {"pass_status": "informational"})
        write_schema(root, REAL_STATUSES + ("inconclusive",))
        rc, out = run_guard(root)
    check("schema drift: a 7th PassStatus fails", rc, 1)
    check("schema drift: names the orphan", "inconclusive" in out, True)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        write_eval(root, POST, {"pass_status": "informational"})
        write_schema(root, REAL_STATUSES)
        rc, _ = run_guard(root)
    check("schema drift: a matching schema passes", rc, 0)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        write_eval(root, POST, {"pass_status": "informational"})
        (root / "schemas").mkdir(parents=True, exist_ok=True)
        (root / SCHEMA_REL).write_text("enums: [\n")
        rc, out = run_guard(root)
    check("schema drift: an unreadable schema fails loudly", rc, 1)
    check("schema drift: says the schema was unreadable", "schema unreadable" in out, True)

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        write_eval(root, POST, {"pass_status": "informational"})
        write_schema(root, ())
        rc, out = run_guard(root)
    check("schema drift: a schema with no PassStatus fails", rc, 1)

    # Every placeholder is exercised, so removing one from the set fails a test.
    from importlib import util as _util
    spec = _util.spec_from_file_location("_guard", REPO / "scripts" / "check_pass_status.py")
    guard_mod = _util.module_from_spec(spec)
    spec.loader.exec_module(guard_mod)
    # Pinned, not read from the module: iterating the set under test would let a
    # deleted entry pass by simply not being exercised.
    expected_placeholders = {"n/a", "na", "-", "--", "tbd", "todo", "none",
                             "see notes", "informational"}
    check("the placeholder set is exactly as documented",
          guard_mod.PLACEHOLDER_CRITERIA, frozenset(expected_placeholders))
    for placeholder in sorted(expected_placeholders):
        rc, _ = verdict(POST, {"pass_status": "pass", "pass_criterion": placeholder})
        check(f"R1: placeholder {placeholder!r} is not a criterion", rc, 1)
        rc, _ = verdict(POST, {"pass_status": "informational", "pass_criterion": placeholder})
        check(f"R2: placeholder {placeholder!r} on informational is still reported", rc, 1)

    # The committed corpus must satisfy the guard as shipped.
    rc, out = run_guard(REPO)
    check("committed records satisfy the guard", rc, 0)
    check("committed records report a checked count", "measurements checked" in out, True)

    print(f"\n{PASSED} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
