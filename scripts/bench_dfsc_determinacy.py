#!/usr/bin/env python3
"""Measure how well-DETERMINED each model-map FSC crossing is (round 40, #224 redesign).

The #224 ratio screen failed three ways (`analyze_crossing_fence_viability.py`, #258): the
ratio→excursion signal is 2-point leverage, the fence is confounded with fit (#234), and the
fresh-candidate pool is empty. All three trace to the ratio being a SELECTION criterion for a
rare event. Round 40 stops selecting and measures the mechanism the §4 caveat is really about:
a crossing that sits on a FLAT stretch of the FSC curve is poorly determined, so a small model
change moves the reported crossing a long way — and the pre→post "excursion" is then mostly
shell-quantisation jitter, not model movement.

Two determinacy measures per entry, from the DEPOSITED model only (no `real_space_refine`):

  D_perturb — the primary measure. Perturb the deposited coordinates by a fixed known sigma
              (Gaussian, per-atom), re-run mtriage, and record how far the sustained crossing
              moves. Averaged over sigma in {0.1, 0.2, 0.3} Å, two seeds each, as registered.
              This is the crossing's sensitivity to a controlled model change — a within-entry
              measurement that isolates determinacy from the absolute fit level.

  D_width   — corroborating. The resolution span (Å) over which the deposited model-map FSC
              stays within +/-0.05 of the 0.143 threshold around the crossing. Wider = flatter
              = less determined. A pure re-read of the deposited curve; no extra tool runs.

Reuses `bench_refinement_deltas_em.measure` (mtriage), `read_fsc_curve` and `d_fsc_from_curve`
so the crossing is the identical quantity the benchmark and the screen compute. Perturbation is
gemmi-based because the EM models are mmCIF, which the PDB-column perturber cannot edit.

The excursion each determinacy value is tested against is NOT re-measured here: it is the
committed `d_fsc_model_delta_pct` in `ref/research/data/em_refinement_deltas.tsv`. So this is a
re-analysis of existing outcomes with a new predictor, not a fresh refinement benchmark.

Usage:
    python3 scripts/bench_dfsc_determinacy.py --cache DIR --json out.json
    python3 scripts/bench_dfsc_determinacy.py 10BU --cache DIR      # one entry (canary)
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import random
import sys
from pathlib import Path
from typing import Any

import gemmi

REPO = Path(__file__).resolve().parent.parent


def _load_em():
    spec = importlib.util.spec_from_file_location(
        "bench_em", REPO / "scripts" / "bench_refinement_deltas_em.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["bench_em"] = m
    spec.loader.exec_module(m)
    return m


EM = _load_em()

SIGMAS = (0.1, 0.2, 0.3)
SEEDS = (7, 11)
WIDTH_DELTA = 0.05  # FSC band half-width around 0.143 for D_width

# The set this benchmark ran on is recorded in its committed results file, which lists
# every entry with its determinacy measures and the excursion label it was tested
# against -- the same convention the EM benchmark uses (validate.sh's entry-set gate).
# The ids are chosen at runtime as (cached maps) ∩ (entries with a committed excursion),
# so the record IS the set: there is no fixed DEFAULT_SET to run blind from.
SET_RECORD = "ref/research/data/round40_dfsc_determinacy.json"


def perturb_cif(model: Path, sigma: float, seed: int, out: Path) -> Path:
    """Copy `model` (mmCIF) with Gaussian noise added to every atom coordinate.

    gemmi rather than the PDB-column perturber in bench_refinement_deltas: EM models are
    mmCIF and routinely exceed the PDB atom-serial limit, so a fixed-column edit is unsafe.
    Deterministic in (sigma, seed): a later run reproduces the same perturbed model.
    """
    if out.exists() and out.stat().st_size:
        return out
    st = gemmi.read_structure(str(model))
    rng = random.Random(f"{model.stem}:{sigma}:{seed}")
    for m in st:
        for chain in m:
            for res in chain:
                for atom in res:
                    p = atom.pos
                    atom.pos = gemmi.Position(p.x + rng.gauss(0, sigma),
                                              p.y + rng.gauss(0, sigma),
                                              p.z + rng.gauss(0, sigma))
    st.setup_entities()
    st.make_mmcif_document().write_file(str(out))
    return out


def d_width(curve: list[tuple[float, float]], crossing: float | None,
            delta: float = WIDTH_DELTA) -> float | None:
    """Resolution span (Å) of the shells whose FSC is within `delta` of 0.143.

    Restricted to the contiguous run of near-threshold shells that contains the crossing, so
    an unrelated flat stretch elsewhere on the curve does not inflate it. Returns the span in Å
    (max d − min d over that run); a well-determined crossing passes through the band in a few
    shells and scores near 0, a flat one lingers and scores large.
    """
    if crossing is None or not curve:
        return None
    lo, hi = EM.FSC_THRESHOLD - delta, EM.FSC_THRESHOLD + delta
    near = [i for i, (_, fsc) in enumerate(curve) if lo <= fsc <= hi]
    if not near:
        return None
    # the shell closest in resolution to the crossing
    anchor = min(range(len(curve)), key=lambda i: abs(curve[i][0] - crossing))
    # grow a contiguous run of near-threshold shells around the anchor
    near_set = set(near)
    if anchor not in near_set:
        anchor = min(near, key=lambda i: abs(i - anchor))
    lo_i = hi_i = anchor
    while lo_i - 1 in near_set:
        lo_i -= 1
    while hi_i + 1 in near_set:
        hi_i += 1
    ds = [curve[i][0] for i in range(lo_i, hi_i + 1)]
    return round(abs(max(ds) - min(ds)), 4)


def measure_entry(pdb_id: str, resolution: float, cache: Path,
                  work: Path) -> dict[str, Any]:
    """Deposited crossing, D_width, and D_perturb for one entry."""
    model, map_file = cache / f"{pdb_id}.cif", cache / f"{pdb_id}.map"
    if not model.exists() or not map_file.exists():
        return {"pdb_id": pdb_id, "error": "model or map not in cache"}
    dep = EM.measure(model, map_file, resolution, work, f"det_dep_{pdb_id}")
    d0 = dep["d_fsc_model_masked"]
    curve_path = dep["curve_path"]
    curve = EM.read_fsc_curve(curve_path) if curve_path else []
    row: dict[str, Any] = {
        "pdb_id": pdb_id, "resolution": resolution,
        "d_fsc_model_dep": d0, "d_fsc_dep_plausible": dep["d_fsc_model_plausible"],
        "cc_mask_dep": dep["cc_mask"],
        "d_width": d_width(curve, d0),
    }
    if d0 is None or not dep["d_fsc_model_plausible"]:
        row["error"] = "deposited crossing missing or implausible"
        return row
    shifts, per_sigma = [], {}
    for sigma in SIGMAS:
        s_shifts = []
        for seed in SEEDS:
            pert = perturb_cif(model, sigma, seed, work / f"{pdb_id}_p{sigma}_{seed}.cif")
            m = EM.measure(pert, map_file, resolution, work, f"det_p{sigma}_{seed}_{pdb_id}")
            dp = m["d_fsc_model_masked"]
            if dp is not None and m["d_fsc_model_plausible"]:
                s_shifts.append(abs(dp - d0))
        if s_shifts:
            per_sigma[str(sigma)] = round(sum(s_shifts) / len(s_shifts), 4)
            shifts.extend(s_shifts)
    row["d_perturb_by_sigma"] = per_sigma
    row["d_perturb"] = round(sum(shifts) / len(shifts), 4) if shifts else None
    row["d_perturb_at_0.2"] = per_sigma.get("0.2")
    row["n_perturb_valid"] = len(shifts)
    return row


def load_labels() -> dict[str, dict[str, float]]:
    """ratio, cc_mask_pre and |excursion| from the committed EM record, keyed by id."""
    import csv
    out = {}
    tsv = REPO / "ref/research/data/em_refinement_deltas.tsv"
    for r in csv.DictReader(tsv.open(), delimiter="\t"):
        def f(k):
            try:
                return float(r[k])
            except (TypeError, ValueError):
                return None
        res, pre, dl = f("resolution"), f("d_fsc_model_pre"), f("d_fsc_model_delta_pct")
        rec = {"resolution": res, "cc_mask_pre": f("cc_mask_pre"),
               "excursion_pct": dl, "ratio": (pre / res) if (res and pre) else None}
        out[r["pdb_id"].upper()] = rec
    return out


def main() -> int:
    from benchmark_environment import announce_benchmark_environment

    announce_benchmark_environment()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pdb_ids", nargs="*")
    ap.add_argument("--cache", required=True)
    ap.add_argument("--work", help="default <cache>/determinacy")
    ap.add_argument("--json", dest="json_out")
    args = ap.parse_args()

    cache = Path(args.cache)
    work = Path(args.work) if args.work else cache / "determinacy"
    work.mkdir(parents=True, exist_ok=True)
    labels = load_labels()

    ids = [i.upper() for i in args.pdb_ids]
    if not ids:
        # every cached entry that also has a committed excursion label
        ids = sorted({p.stem.upper() for p in cache.glob("*.cif")}
                     & {k for k, v in labels.items() if v["excursion_pct"] is not None})
    rows = []
    for pdb_id in ids:
        lab = labels.get(pdb_id, {})
        res = lab.get("resolution")
        if res is None:
            rows.append({"pdb_id": pdb_id, "error": "no resolution in em record"})
            print(f"[{pdb_id}] no resolution on record", file=sys.stderr)
            continue
        print(f"[{pdb_id}] res {res}", file=sys.stderr)
        row = measure_entry(pdb_id, res, cache, work)
        row["ratio"] = lab.get("ratio")
        row["cc_mask_pre"] = lab.get("cc_mask_pre")
        row["excursion_pct"] = lab.get("excursion_pct")
        rows.append(row)
        print(f"  d_dep {row.get('d_fsc_model_dep')}  D_width {row.get('d_width')}  "
              f"D_perturb {row.get('d_perturb')} (n={row.get('n_perturb_valid')})  "
              f"|excursion| {abs(row['excursion_pct']) if row.get('excursion_pct') is not None else None}",
              file=sys.stderr)
    out = {"rows": rows, "sigmas": SIGMAS, "seeds": SEEDS}
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps({"n": len(rows),
                      "n_with_perturb": sum(1 for r in rows if r.get("d_perturb") is not None)},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
