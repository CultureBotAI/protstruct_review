#!/usr/bin/env python3
"""Enforce `pass_status` semantics on committed EvaluationRun records (#567).

`schemas/protstruct_review.yaml` defines each `PassStatus` value in terms of a
declared criterion and, for the disagreement statuses, an agent claim. Nothing
validated that, so a record could assert a verdict with no criterion recorded
anywhere — which is exactly what happened during the 2026-09-07 1SAR review:
one row was marked `pass` on the strength of a sentence in its `notes` while
`pass_criterion` sat empty, and two structurally identical rows were graded on
opposite conclusions from the same stated premise. Prose is not checkable; the
fields are.

Rules, each read straight off the enum's own description:

  R1  A status that references its criterion — pass, fail_by_oracle,
      pass_with_caveat, pass_criterion_fail_headline, fail_by_oracle_within_cctbx
      — requires a non-empty `pass_criterion`.
  R2  `informational` is "Reported without a declared criterion", so it must NOT
      carry a `pass_criterion`. (A criterion field holding the literal string
      "informational" is the status leaking into the criterion slot.)
  R3  `fail_by_oracle` / `fail_by_oracle_within_cctbx` are "...disagrees with
      agent claim...", so they require an `agent_claim` to disagree with.
  R4  `fail_by_oracle_within_cctbx` is "Two cctbx tools disagree...", so the row
      must declare `oracle_family: cctbx`.

R1 and R4 hold across every committed record and are enforced everywhere. R2 and
R3 are violated by records that predate the rule, so they are enforced only for
runs dated on or after CUTOVER; older violations are printed by name as
grandfathered, the same way `check_qds_trust_invariant.py` handles its own
cutover. History is history, but it is listed rather than hidden.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

CUTOVER = "2026-09-07"  # the date these semantics became enforceable

# Statuses whose enum description refers to the measurement's criterion.
CRITERION_BEARING = frozenset({
    "pass",
    "fail_by_oracle",
    "pass_with_caveat",
    "pass_criterion_fail_headline",
    "fail_by_oracle_within_cctbx",
})

# Statuses whose enum description refers to disagreeing with the agent's claim.
CLAIM_BEARING = frozenset({"fail_by_oracle", "fail_by_oracle_within_cctbx"})


def check_measurement(path: Path, run_date: str, row: dict,
                      failures: list[str], grandfathered: list[str]) -> None:
    """Apply R1-R4 to one measurement row."""
    status = row.get("pass_status")
    if not status:
        return
    rid = row.get("id", "<no id>")
    where = f"{path.name}: {rid}"
    criterion = row.get("pass_criterion")
    enforced = not run_date or run_date >= CUTOVER

    # R1 — a criterion-bearing status must name its criterion. Always enforced.
    if status in CRITERION_BEARING and not (criterion and str(criterion).strip()):
        failures.append(
            f"{where}: pass_status {status!r} asserts a verdict against a criterion, "
            f"but pass_criterion is empty (#567)")

    # R4 — the within-cctbx status must actually be a cctbx row. Always enforced.
    if status == "fail_by_oracle_within_cctbx" and row.get("oracle_family") != "cctbx":
        failures.append(
            f"{where}: pass_status 'fail_by_oracle_within_cctbx' requires "
            f"oracle_family 'cctbx', got {row.get('oracle_family')!r} (#567)")

    # R2 — informational means no declared criterion.
    if status == "informational" and criterion:
        message = (f"{where}: pass_status 'informational' means "
                   f"'reported without a declared criterion', but pass_criterion is "
                   f"{str(criterion)!r} (#567)")
        (failures if enforced else grandfathered).append(
            message if enforced else f"{message} — run dated {run_date}, predates the rule")

    # R3 — a disagreement status needs a claim to disagree with.
    if status in CLAIM_BEARING and not row.get("agent_claim"):
        message = (f"{where}: pass_status {status!r} disagrees with an agent claim, "
                   f"but the row carries no agent_claim (#567)")
        (failures if enforced else grandfathered).append(
            message if enforced else f"{message} — run dated {run_date}, predates the rule")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    args = ap.parse_args()
    root = Path(args.root)

    failures: list[str] = []
    grandfathered: list[str] = []
    checked = 0

    for path in sorted((root / "data").rglob("EVAL_*.yaml")):
        try:
            doc = yaml.safe_load(path.read_text()) or {}
        except (yaml.YAMLError, OSError) as exc:
            failures.append(f"{path.name}: unreadable ({type(exc).__name__})")
            continue
        for run in doc.get("evaluation_runs", []) or []:
            run_date = str(run.get("run_date", ""))[:10]
            for row in run.get("measurements", []) or []:
                checked += 1
                check_measurement(path, run_date, row, failures, grandfathered)

    for line in grandfathered:
        print(f"  grandfathered: {line}")
    for line in failures:
        print(f"FAIL  {line}", file=sys.stderr)

    if failures:
        print(f"pass_status semantics: {len(failures)} violation(s) across "
              f"{checked} measurement(s)", file=sys.stderr)
        return 1
    print(f"pass_status semantics hold ({checked} measurements checked, "
          f"{len(grandfathered)} grandfathered row(s) listed above)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
