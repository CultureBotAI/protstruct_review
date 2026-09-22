#!/usr/bin/env python3
"""Benchmark the secondary-structure agreement floor: DSSP vs biotite P-SEA.

Settles the `Secondary-structure agreement` `[template]` tolerance in
`ref/thresholds_and_standards.md`, whose second clause is "two independent assigners
floor ≥ 0.80 on a well-ordered model". `scripts/t15_ss_agreement.py` computes the
metric but had never been run over a set — only on the repo's own 1SAR.

This is one of the few tolerances where cross-tool agreement means what it says: DSSP
assigns from **hydrogen-bond energetics** (Kabsch & Sander) and biotite's P-SEA from
**Cα geometry** (Labesse). Neither can be derived from the other, and both are
non-cctbx.

Usage:
    python3 scripts/bench_t15_ss_agreement.py 1UBQ 1LYZ --cache DIR --json out.json
    python3 scripts/bench_t15_ss_agreement.py --ids-file ids.json --cache DIR
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yaml

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from toolchain import run_logged

RCSB_PDB = "https://files.rcsb.org/download/{pdb_id}.pdb"
REPO = Path(__file__).resolve().parent.parent
T15 = REPO / "scripts" / "t15_ss_agreement.py"

_COUNTS = re.compile(r"(\d+)/(\d+)\s+concordant")

# Minimum fraction of residues DSSP assigns to H or E for the agreement number to
# mean anything. Below this there is no secondary structure to agree *about*, and the
# metric saturates towards 1.0 — see `ss_content` and the write-up.
MIN_SS_CONTENT = 0.20

# Well-known, well-ordered structures spanning fold class: all-α, all-β, α/β, α+β.
DEFAULT_SET = [
    "1UBQ", "1LYZ", "1LZ1", "2PTN", "7RSA", "1CA2", "1MBN", "3EST",
    "1BNI", "2CI2", "9PAP", "1HEW", "4PTI", "1CRN", "2LYZ", "1TIM",
]


def fetch(pdb_id: str, cache: Path) -> Path | None:
    """Deposited PDB-format coordinates."""
    dest = cache / f"{pdb_id.lower()}.pdb"
    if dest.exists() and dest.stat().st_size:
        return dest
    cache.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(RCSB_PDB.format(pdb_id=pdb_id.upper()), timeout=180) as r:
            dest.write_bytes(r.read())
    except urllib.error.HTTPError:
        return None
    return dest


def _rows_by_metric(text: str) -> dict[str, dict[str, Any]]:
    """Parse the wrapper's YAML by metric id; row order is not semantic."""
    try:
        rows = yaml.safe_load(text) or []
    except yaml.YAMLError:
        return {}
    if not isinstance(rows, list):
        return {}
    return {
        row["metric_definition_ref"]: row
        for row in rows
        if isinstance(row, dict) and row.get("metric_definition_ref")
    }


def run_t15(model: Path, cache: Path) -> dict[str, Any] | None:
    """Run the harness and read agreement plus content from its typed YAML rows."""
    log = cache / f"t15_{model.stem}.log"
    rows = _rows_by_metric(log.read_text(errors="ignore")) if log.exists() else {}
    required = {"T15_secondary_structure_agreement", "T15_secondary_structure_content"}
    if not required.issubset(rows):
        run_logged(
            [sys.executable, T15, model, "--eval-id", "EVAL_BENCH"],
            log,
            timeout=3600,
        )
    if not log.exists():
        return None
    text = log.read_text(errors="ignore")
    rows = _rows_by_metric(text)
    if not required.issubset(rows):
        return None
    agreement = rows["T15_secondary_structure_agreement"].get("oracle_measure") or {}
    content = rows["T15_secondary_structure_content"].get("oracle_measure") or {}
    if agreement.get("value_numeric") is None or content.get("value_numeric") is None:
        return None
    counts = _COUNTS.search(text)
    return {
        "agreement": float(agreement["value_numeric"]),
        "ss_content": float(content["value_numeric"]),
        "n_concordant": int(counts.group(1)) if counts else None,
        "n_scored": int(counts.group(2)) if counts else None,
    }


def collect(pdb_ids: list[str], cache: Path) -> tuple[list[dict], list[dict]]:
    """Run the two assigners over every entry."""
    rows, skipped = [], []
    for pdb_id in pdb_ids:
        pdb_id = pdb_id.upper()
        print(f"[{pdb_id}]", file=sys.stderr)
        model = fetch(pdb_id, cache)
        if model is None:
            skipped.append({"pdb_id": pdb_id, "reason": "no PDB-format model"})
            continue
        result = run_t15(model, cache)
        if result is None:
            print("  ! t15_ss_agreement failed", file=sys.stderr)
            skipped.append({"pdb_id": pdb_id, "reason": "t15_ss_agreement failed"})
            continue
        content = result.pop("ss_content")
        rows.append({"pdb_id": pdb_id, **result,
                     "ss_content": content,
                     "interpretable": content is not None and content >= MIN_SS_CONTENT,
                     "meets_0_80_floor": result["agreement"] >= 0.80})
        flag = "" if (content or 0) >= MIN_SS_CONTENT else "  <- DEGENERATE (little/no SS)"
        print(f"  agreement {result['agreement']:.4f} over {result['n_scored']} residues,"
              f" SS content {content}{flag}", file=sys.stderr)
    return rows, skipped


def summarize(rows: list[dict]) -> dict[str, Any]:
    """Agreement distribution and how often the asserted floor holds."""
    if not rows:
        return {"n": 0}
    values = sorted(r["agreement"] for r in rows)
    idx = min(len(values) - 1, max(0, round(0.1 * (len(values) - 1))))
    return {
        "n_models": len(rows),
        "median": round(statistics.median(values), 4),
        "p10": round(values[idx], 4),
        "min": round(values[0], 4),
        "max": round(values[-1], 4),
        "n_meeting_0_80_floor": sum(1 for r in rows if r["meets_0_80_floor"]),
        "below_floor": [r["pdb_id"] for r in rows if not r["meets_0_80_floor"]],
        "n_degenerate_low_ss_content": sum(1 for r in rows if not r["interpretable"]),
        "degenerate": [r["pdb_id"] for r in rows if not r["interpretable"]],
    }


def main() -> int:
    from benchmark_environment import announce_benchmark_environment

    announce_benchmark_environment()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pdb_ids", nargs="*")
    ap.add_argument("--ids-file")
    ap.add_argument("--cache")
    ap.add_argument("--json", dest="json_out")
    args = ap.parse_args()

    ids = list(args.pdb_ids)
    if args.ids_file:
        payload = json.loads(Path(args.ids_file).read_text())
        ids += payload if isinstance(payload, list) else [i for v in payload.values() for i in v]
    if not ids:
        ids = DEFAULT_SET

    cache = Path(args.cache) if args.cache else Path(tempfile.gettempdir()) / "bench_cache_t15"
    rows, skipped = collect(ids, cache)
    summary = summarize(rows)
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps({"rows": rows, "skipped": skipped, "summary": summary}, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
