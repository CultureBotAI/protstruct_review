#!/usr/bin/env python3
"""Benchmark clashscore and H-placement agreement: cctbx vs Richardson standalone.

Settles two `[template]` tolerances in `ref/thresholds_and_standards.md` that were
backed by a single in-repo observation (1SAR: 3.13 cctbx vs 3.63 standalone):

  - Clashscore  ± 1.0
  - H-placement  H-atom count within ± 2 %, clashscore delta within ± 1.0

Both come from one run per model, because both paths are the same pipeline —
build hydrogens, then count serious overlaps — differing in implementation:

  - cctbx path:      `phenix.clashscore model.pdb` (adds H internally via reduce)
  - standalone path: Richardson `reduce -build`, then `probe`, with the clashscore
    summed here by the MolProbity definition — serious clashes (overlap ≥ 0.4 Å)
    per 1000 atoms, counting each atom pair once.

The dominant expected term is the **H-build convention**: cctbx defaults to
electron-cloud-center hydrogen positions for X-ray models, standalone `reduce`
defaults to nuclear positions. Running standalone `reduce` both ways (`-build` and
`-nuclear`) separates that convention effect from the implementation noise floor —
which is the thing the tolerance is supposed to bound.

Usage:
    python3 scripts/bench_t05_clashscore_h.py 1ABC 2DEF --cache DIR --json out.json
    python3 scripts/bench_t05_clashscore_h.py --ids-file ids.json --cache DIR
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from toolchain import PROBE, REDUCE, phenix, run_logged, run_to_file
from standalone_reduce import build_hydrogens

RCSB_PDB = "https://files.rcsb.org/download/{pdb_id}.pdb"
_CLASHSCORE = re.compile(r"clashscore\s*=\s*([\d.]+)")

# MolProbity's clash criterion: a "serious" clash is an overlap of at least 0.4 Å.
CLASH_OVERLAP = -0.4


def fetch(pdb_id: str, cache: Path) -> Path | None:
    """Download the deposited PDB-format coordinates; None if unavailable."""
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


def count_atoms(model: Path, hydrogens_only: bool = False) -> int:
    """Atoms in the clashscore denominator: non-water ATOM/HETATM records."""
    total = 0
    for line in model.read_text(errors="ignore").splitlines():
        if not line.startswith(("ATOM", "HETATM")) or line[17:20] == "HOH":
            continue
        if hydrogens_only and line[76:78].strip() != "H":
            continue
        total += 1
    return total


def run_phenix_clashscore(model: Path, work: Path) -> float | None:
    """cctbx clashscore (hydrogens built internally)."""
    log = work / f"pcs_{model.stem}.log"
    if not log.exists() or not _CLASHSCORE.search(log.read_text(errors="ignore")):
        run_logged([phenix("phenix.clashscore"), model], log, cwd=work, timeout=3600)
    if not log.exists():
        return None
    match = _CLASHSCORE.search(log.read_text(errors="ignore"))
    return float(match.group(1)) if match else None


def run_reduce(model: Path, work: Path, nuclear: bool) -> Path | None:
    """Dictionary-explicit standalone Reduce; invalid evidence fails hard."""
    return build_hydrogens(model, work, nuclear=nuclear)


def run_probe_clashscore(model_h: Path, work: Path,
                        evidence: dict[str, str] | None = None) -> float | None:
    """Serious clashes per 1000 atoms, only after a successful retained run.

    Probe is inexpensive compared with H construction. Always run it in a new
    evidence directory; file existence alone never authenticates old scores.
    """
    model_h = model_h.resolve(strict=True)
    executable = PROBE.resolve(strict=True)
    model_hash = hashlib.sha256(model_h.read_bytes()).hexdigest()
    executable_hash = hashlib.sha256(executable.read_bytes()).hexdigest()
    work.mkdir(parents=True, exist_ok=True)
    attempt = Path(tempfile.mkdtemp(prefix="probe_evidence_", dir=work.resolve()))
    out, error_log = attempt / "stdout.txt", attempt / "stderr.log"
    arguments = [executable, "-u", "-q", "-mc", "-het", "-once",
                 "ogt33 not water", "ogt33", model_h]
    with error_log.open("w") as errors:
        process = run_to_file(arguments, out, stderr=errors, timeout=3600)
    manifest = {
        "argv": [str(arg) for arg in arguments],
        "model_sha256": model_hash, "executable_sha256": executable_hash,
        "returncode": process.returncode,
        "score_status": "unparsed",
        "stdout_sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
        "stderr_sha256": hashlib.sha256(error_log.read_bytes()).hexdigest(),
    }
    manifest_path = attempt / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    if process.returncode or re.search(r"\berror\b|could not open", error_log.read_text(), re.I):
        raise RuntimeError(f"Probe failed (exit {process.returncode}); retained stderr: {error_log}")
    if (hashlib.sha256(model_h.read_bytes()).hexdigest() != model_hash
            or hashlib.sha256(executable.read_bytes()).hexdigest() != executable_hash):
        raise RuntimeError(f"Probe input changed during execution; retained evidence: {attempt}")
    pairs = set()
    for line in out.read_text(errors="ignore").splitlines():
        if not line.strip():
            continue
        fields = line.split(":")
        # Probe -u -q emits exactly 19 fields without the optional condensed
        # dot-count column. Its writeRaw() names seven contact types; bo/wo
        # denote bad/worse overlaps. Unknown nonempty output is not zero.
        if (len(fields) != 19 or fields[2] not in {"wc", "cc", "wh", "so", "bo", "wo", "hb"}
                or not all(fields[index].strip() for index in (1, 3, 4, 12, 13))):
            raise RuntimeError(f"Malformed Probe contact; retained evidence: {attempt}")
        try:
            numeric = [float(fields[index]) for index in (*range(5, 12), *range(14, 19))]
        except ValueError:
            raise RuntimeError(f"Malformed Probe overlap; retained evidence: {attempt}") from None
        if not all(math.isfinite(value) for value in numeric):
            raise RuntimeError(f"Nonfinite Probe overlap; retained evidence: {attempt}")
        if fields[2] in {"bo", "wo"} and numeric[0] <= CLASH_OVERLAP:
            pairs.add(frozenset((fields[3], fields[4])))
    atoms = count_atoms(model_h)
    if not atoms:
        return None
    score = 1000.0 * len(pairs) / atoms
    manifest.update(score_status="measured", atom_count=atoms,
                    clash_pair_count=len(pairs), clashscore=score,
                    clash_pairs=sorted(sorted(pair) for pair in pairs))
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    if evidence is not None:
        evidence["manifest"] = str(manifest_path)
    return score


def collect(pdb_ids: list[str], cache: Path) -> tuple[list[dict], list[dict]]:
    """Run both pipelines, plus both standalone H conventions, on every entry."""
    rows, skipped = [], []
    for pdb_id in pdb_ids:
        pdb_id = pdb_id.upper()
        print(f"[{pdb_id}]", file=sys.stderr)
        model = fetch(pdb_id, cache)
        if model is None:
            skipped.append({"pdb_id": pdb_id, "reason": "no PDB-format model"})
            continue
        if count_atoms(model, hydrogens_only=True):
            print("  ! model already has hydrogens — skipped", file=sys.stderr)
            skipped.append({"pdb_id": pdb_id, "reason": "deposited model already has H"})
            continue

        phenix_cs = run_phenix_clashscore(model, cache)
        h_ec = run_reduce(model, cache, nuclear=False)
        h_nuc = run_reduce(model, cache, nuclear=True)
        if phenix_cs is None or h_ec is None or h_nuc is None:
            skipped.append({"pdb_id": pdb_id, "reason": "clashscore or reduce failed"})
            continue
        probe_ec, probe_nuc = {}, {}
        cs_ec = run_probe_clashscore(h_ec, cache, probe_ec)
        cs_nuc = run_probe_clashscore(h_nuc, cache, probe_nuc)
        if cs_ec is None or cs_nuc is None:
            skipped.append({"pdb_id": pdb_id, "reason": "probe failed"})
            continue

        n_h_ec = count_atoms(h_ec, hydrogens_only=True)
        n_h_nuc = count_atoms(h_nuc, hydrogens_only=True)
        rows.append({
            "pdb_id": pdb_id,
            "standalone_reduce_evidence": {
                "electron_cloud": str(h_ec.parent / "manifest.json"),
                "nuclear": str(h_nuc.parent / "manifest.json"),
            },
            "standalone_probe_evidence": {"electron_cloud": probe_ec["manifest"],
                                          "nuclear": probe_nuc["manifest"]},
            "n_atoms": count_atoms(model),
            "phenix_clashscore": round(phenix_cs, 2),
            "standalone_clashscore_electron_cloud": round(cs_ec, 2),
            "standalone_clashscore_nuclear": round(cs_nuc, 2),
            # Matched convention: cctbx uses electron-cloud H for X-ray models.
            "delta_matched": round(cs_ec - phenix_cs, 2),
            "abs_delta_matched": round(abs(cs_ec - phenix_cs), 2),
            # Mismatched convention: the error a naive pairing would make.
            "delta_mismatched": round(cs_nuc - phenix_cs, 2),
            "abs_delta_mismatched": round(abs(cs_nuc - phenix_cs), 2),
            "n_h_electron_cloud": n_h_ec,
            "n_h_nuclear": n_h_nuc,
            "h_count_delta_pct": round(100.0 * (n_h_nuc - n_h_ec) / n_h_ec, 3) if n_h_ec else None,
        })
        print(f"  cctbx {phenix_cs:7.2f} | standalone ec {cs_ec:7.2f} nuc {cs_nuc:7.2f}"
              f" | Δmatched {cs_ec - phenix_cs:+6.2f} Δmismatched {cs_nuc - phenix_cs:+6.2f}"
              f" | H {n_h_ec}/{n_h_nuc}", file=sys.stderr)
    return rows, skipped


def summarize(rows: list[dict]) -> dict[str, Any]:
    """Agreement under matched vs mismatched H convention, and H-count agreement."""
    if not rows:
        return {"n": 0}

    def stats(values: list[float]) -> dict[str, Any]:
        ordered = sorted(abs(v) for v in values)
        idx = min(len(ordered) - 1, max(0, round(0.9 * (len(ordered) - 1))))
        return {
            "signed_median": round(statistics.median(values), 3),
            "abs_median": round(statistics.median(ordered), 3),
            "abs_p90": round(ordered[idx], 3),
            "abs_max": round(ordered[-1], 3),
        }

    return {
        "n": len(rows),
        "clashscore_matched_convention": stats([r["delta_matched"] for r in rows]),
        "clashscore_mismatched_convention": stats([r["delta_mismatched"] for r in rows]),
        "h_count_delta_pct": stats([r["h_count_delta_pct"] for r in rows
                                    if r["h_count_delta_pct"] is not None]),
        "clashscore_range": [min(r["phenix_clashscore"] for r in rows),
                             max(r["phenix_clashscore"] for r in rows)],
    }


# The 10 models the clashscore agreement tolerance was measured on, committed in round
# 18. Recovered from the per-entry table in
# `ref/research/tolerance_benchmark_clashscore_h.md`, which tabulates cctbx, standalone
# electron-cloud and standalone nuclear values for every one of them.
DEFAULT_SET = [
    "24MR", "37AS", "37AP", "11AF", "28SZ", "37BG", "12LO", "30IZ", "9LLR", "9PN7",
]
SET_IS_COMPLETE = True


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
        ids = list(DEFAULT_SET)
        print(f"using the committed benchmark set ({len(ids)} entries)",
              file=sys.stderr)

    for tool in (REDUCE, PROBE):
        if not tool.exists():
            raise SystemExit(f"required tool not found: {tool}")

    cache = Path(args.cache) if args.cache else Path(tempfile.gettempdir()) / "bench_cache_t05"
    rows, skipped = collect(ids, cache)
    summary = summarize(rows)
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps({"rows": rows, "skipped": skipped, "summary": summary}, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
