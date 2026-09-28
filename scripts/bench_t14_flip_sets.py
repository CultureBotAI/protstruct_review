#!/usr/bin/env python3
"""Historical Asn/Gln/His flip-set benchmark implementation.

Legacy parser warning (#846): HIS and small-Set records are omitted; signed,
insertion-code and alternate identities are incomplete, and short-key duplicates
overwrite. Its totals are legacy-parser summaries, not complete inventories.
For new standalone evidence use recount_standalone_reduce_flips.py. A paired
reduce2 comparison still needs a separately reviewed identity/coverage contract.
The historical method below is not current grading authority (#809).

`ref/thresholds_and_standards.md` requires the two H builders to agree on the
"same Asn/Gln/His flip set". PR #28 measured H count and clashscore but not flips,
because `phenix.clashscore` does not emit flip records. **`reduce` does**: both
builders write `USER  MOD` lines into the output PDB recording, per residue, whether
the amide/imidazole was flipped and how confident the call was.

Record format (Richardson `reduce`):

    USER  MOD Single : A  32 GLN     :FLIP  amide:sc=   0.435  F(o=-0.2,f=0.44)
    USER  MOD Single : A   2 GLN     :      amide:sc=   1.61   X(o=1.6,f=1.2)

The single-letter code before `(o=...` is the flip category: `F` = flipped,
`K` = keep, `C` = clashes either way, `X` = uncertain. Both the decision and the
category are compared, because an `X`-vs-`K` disagreement is a weaker signal than
`F`-vs-`K`: the first is two builders hedging differently on an ambiguous residue,
the second is a genuine conflict about the model.

It also compares the **H-atom count** between the two builders, which is the other
half of the H-placement tolerance and the comparison that tolerance actually names.
(PR #28 measured H count between two *conventions* of one builder instead, which is
a different quantity — see `ref/research/tolerance_benchmark_flip_sets.md`.)

Usage:
    python3 scripts/bench_t14_flip_sets.py 1ABC 2DEF --cache DIR --json out.json
    python3 scripts/bench_t14_flip_sets.py --ids-file ids.json --cache DIR
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

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from toolchain import phenix as phenix_executable, run_logged, run_to_file
from standalone_reduce import build_hydrogens

RCSB_PDB = "https://files.rcsb.org/download/{pdb_id}.pdb"
# reduce2 reports each flippable group's final pose in its .txt report, e.g.
#   AmideFlip at chain A GLN 2 NE2 Initial score: 13.30 ... pose Unflipped
#   HisFlip   at chain A HIS 55 ... pose Flipped
# NOTE add_flip_movers defaults to False: without it reduce2 never builds flip movers
# and reports nothing, which is what made this comparison look impossible.
_REDUCE2_FLIP = re.compile(
    r"(?:Amide|His)Flip at chain (?P<chain>\S+)\s+(?P<resname>\S+)\s+(?P<resseq>\d+)\s+"
    r"\S+.*?pose (?P<pose>Flipped|Unflipped)")

# USER  MOD Single : A  32 GLN     :FLIP  amide:sc=   0.435  F(o=-0.2,f=0.44)
_FLIP = re.compile(
    r"^USER  MOD \S+\s*:\s*(?P<chain>.)\s*(?P<resseq>\d+)\s+(?P<resname>\S+)\s*:"
    r"(?P<decision>FLIP|\s*)\s*(?P<kind>amide|his)\s*:sc=\s*(?P<score>\S+)\s+"
    r"(?P<category>[A-Z])\(")

FLIPPABLE = {"ASN", "GLN", "HIS"}


def hydrogen_count(model_h: Path) -> int:
    """Hydrogens in a built model (element column, not name heuristics)."""
    return sum(1 for line in model_h.read_text(errors="ignore").splitlines()
               if line.startswith(("ATOM", "HETATM")) and line[76:78].strip() == "H")


def het_components(model: Path) -> set[str]:
    """Non-water hetero components present — the ones a het dictionary must cover."""
    return {line[17:20].strip() for line in model.read_text(errors="ignore").splitlines()
            if line.startswith("HETATM") and line[17:20].strip() != "HOH"}


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


def build(model: Path, cache: Path, phenix: bool) -> Path | None:
    """Add hydrogens with one of the two builders; returns the output PDB."""
    if not phenix:
        return build_hydrogens(model, cache)
    out = cache / f"{model.stem}_h_phx.pdb"
    executable = phenix_executable("phenix.reduce")
    if not out.exists() or not out.stat().st_size:
        run_to_file([executable, "-quiet", "-build", model], out, timeout=3600)
        if not out.exists() or not out.stat().st_size:
            return None
    return out


def reduce2_flip_calls(model: Path, cache: Path) -> dict[tuple[str, int, str], tuple[bool, str]] | None:
    """Flip decisions from the distinct, cctbx-family `mmtbx.reduce2` builder.

    `phenix.reduce` and standalone `reduce` are the same binary, so comparing them
    measures redistribution, not method. This benchmark compares PHENIX-distributed
    Reduce with reduce2: both are catalogued cctbx-family, so it does not establish
    independent corroboration (#809/#824). Flip records require
    `add_flip_movers=True`; the default is
    False, in which case it builds no flip movers and reports nothing at all.
    """
    report = cache / f"{model.stem}FH.txt"
    if not report.exists() or not _REDUCE2_FLIP.search(report.read_text(errors="ignore")):
        run_logged(
            [phenix_executable("mmtbx.reduce2"), model.name, "approach=add", "add_flip_movers=True"],
            cache / f"r2_{model.stem}.log",
            cwd=cache,
            timeout=7200,
        )
    if not report.exists():
        return None
    calls = {}
    for m in _REDUCE2_FLIP.finditer(report.read_text(errors="ignore")):
        resname = m.group("resname").upper()
        if resname not in FLIPPABLE:
            continue
        calls[(m.group("chain"), int(m.group("resseq")), resname)] = (
            m.group("pose") == "Flipped", "F" if m.group("pose") == "Flipped" else "K")
    return calls or None


def confident_conflicts(reduce_calls: dict, reduce2_calls: dict) -> list:
    """Residues where `reduce` is confident (category F/K) and `reduce2` disagrees (#287).

    An informational flip-set measure; grading is suspended (#809). A disagreement where `reduce` wrote category
    `X` (uncertain) or `C` (clashes either way) is one builder declining to commit, not a
    genuine conflict about the model, so it is excluded here and kept only as a diagnostic.
    Keyed like the callers: `(chain, resnum, resname)`, value `(flipped_bool, category)`.
    """
    shared = set(reduce_calls) & set(reduce2_calls)
    return sorted(k for k in shared
                  if reduce_calls[k][0] != reduce2_calls[k][0]
                  and reduce_calls[k][1] in ("F", "K"))


def flip_calls(model_h: Path) -> dict[tuple[str, int, str], tuple[bool, str]]:
    """Reproduce legacy parsed short keys, not the complete mover population.

    Known omissions/collisions are documented in #846 and the module warning.
    Preserve this historical algorithm; do not join a new one-sided parser to
    the old reduce2 domain or describe these keys as a complete residue inventory.
    """
    calls = {}
    for line in model_h.read_text(errors="ignore").splitlines():
        if not line.startswith("USER  MOD"):
            continue
        match = _FLIP.match(line)
        if not match:
            continue
        resname = match.group("resname").upper()
        if resname not in FLIPPABLE:
            continue
        key = (match.group("chain"), int(match.group("resseq")), resname)
        calls[key] = (match.group("decision").strip() == "FLIP", match.group("category"))
    return calls


def collect(pdb_ids: list[str], cache: Path) -> tuple[list[dict], list[dict]]:
    """Compare the two builders' flip calls on every entry."""
    rows, skipped = [], []
    for pdb_id in pdb_ids:
        pdb_id = pdb_id.upper()
        print(f"[{pdb_id}]", file=sys.stderr)
        model = fetch(pdb_id, cache)
        if model is None:
            skipped.append({"pdb_id": pdb_id, "reason": "no PDB-format model"})
            continue
        phx, std = build(model, cache, phenix=True), build(model, cache, phenix=False)
        if phx is None or std is None:
            skipped.append({"pdb_id": pdb_id, "reason": "an H builder failed"})
            continue
        n_h_phx, n_h_std = hydrogen_count(phx), hydrogen_count(std)
        het = het_components(model)
        a, b = flip_calls(phx), flip_calls(std)
        r2 = reduce2_flip_calls(model, cache)
        if not a and not b:
            print("  ! no flippable residues with USER MOD records — skipped", file=sys.stderr)
            skipped.append({"pdb_id": pdb_id, "reason": "no flip records"})
            continue

        shared = sorted(set(a) & set(b))
        decision_diffs = [k for k in shared if a[k][0] != b[k][0]]
        category_diffs = [k for k in shared if a[k][1] != b[k][1] and a[k][0] == b[k][0]]
        # Historical producer: PHENIX-distributed reduce (a), not standalone (b).
        # Both are cctbx-family here; this is informational, not an independent gate (#809).
        r2_shared = sorted(set(a) & set(r2)) if r2 else []
        r2_diffs = [k for k in r2_shared if a[k][0] != r2[k][0]]
        r2_confident_diffs = confident_conflicts(a, r2) if r2 else []
        rows.append({
            "pdb_id": pdb_id,
            "standalone_reduce_evidence": str(std.parent / "manifest.json"),
            "n_flippable_phenix": len(a),
            "n_flippable_standalone": len(b),
            "n_shared": len(shared),
            "n_only_phenix": len(set(a) - set(b)),
            "n_only_standalone": len(set(b) - set(a)),
            "n_flipped_phenix": sum(1 for v in a.values() if v[0]),
            "n_flipped_standalone": sum(1 for v in b.values() if v[0]),
            "n_h_phenix": n_h_phx,
            "n_h_standalone": n_h_std,
            "h_count_delta_pct": round(100.0 * (n_h_phx - n_h_std) / n_h_std, 3) if n_h_std else None,
            "het_components": sorted(het),
            "has_het": bool(het),
            "n_reduce2_shared": len(r2_shared),
            "n_reduce2_decision_disagreements": len(r2_diffs),
            "reduce2_disagreements": [f"{c}{r} {n}" for c, r, n in r2_diffs],
            "n_reduce2_confident_conflicts": len(r2_confident_diffs),
            "reduce2_confident_conflicts": [f"{c}{r} {n}" for c, r, n in r2_confident_diffs],
            "n_flipped_reduce2": sum(1 for v in r2.values() if v[0]) if r2 else None,
            "n_decision_disagreements": len(decision_diffs),
            "n_category_only_disagreements": len(category_diffs),
            "decision_disagreements": [f"{c}{r} {n}" for c, r, n in decision_diffs],
            "identical": not decision_diffs and not category_diffs
                         and set(a) == set(b),
        })
        print(f"  {len(shared)} shared residues, {rows[-1]['n_flipped_phenix']}/"
              f"{rows[-1]['n_flipped_standalone']} flipped, "
              f"{len(decision_diffs)} decision diffs, {len(category_diffs)} category-only diffs"
              f" | reduce2 {rows[-1]['n_reduce2_decision_disagreements']}/"
              f"{rows[-1]['n_reduce2_shared']} disagree"
              f" | H {n_h_phx}/{n_h_std} ({rows[-1]['h_count_delta_pct']:+.3f} %)"
              f"{' het:' + ','.join(sorted(het)) if het else ''}", file=sys.stderr)
    return rows, skipped


def summarize(rows: list[dict]) -> dict[str, Any]:
    """How often the two builders make identical flip calls."""
    if not rows:
        return {"n": 0}
    shared = sum(r["n_shared"] for r in rows)

    def h_stats(subset: list[dict]) -> dict[str, Any]:
        values = sorted(abs(r["h_count_delta_pct"]) for r in subset
                        if r["h_count_delta_pct"] is not None)
        if not values:
            return {"n": 0}
        idx = min(len(values) - 1, max(0, round(0.9 * (len(values) - 1))))
        return {"n": len(values), "abs_median": round(statistics.median(values), 3),
                "abs_p90": round(values[idx], 3), "abs_max": round(values[-1], 3),
                "n_exceeding_0.1_pct": sum(1 for v in values if v > 0.1)}

    return {
        "n_models": len(rows),
        "h_count_all": h_stats(rows),
        "h_count_protein_only": h_stats([r for r in rows if not r["has_het"]]),
        "h_count_with_het": h_stats([r for r in rows if r["has_het"]]),
        "n_flippable_residues_compared": shared,
        "n_models_identical": sum(1 for r in rows if r["identical"]),
        "total_decision_disagreements": sum(r["n_decision_disagreements"] for r in rows),
        "reduce_vs_reduce2": {
            "n_residues_compared": sum(r["n_reduce2_shared"] for r in rows),
            # Raw disagreements and confident-conflict counts are informational (#809).
            "n_decision_disagreements": sum(r["n_reduce2_decision_disagreements"] for r in rows),
            "n_confident_conflicts": sum(r["n_reduce2_confident_conflicts"] for r in rows),
            "n_models": sum(1 for r in rows if r["n_reduce2_shared"]),
        },
        "total_category_only_disagreements": sum(r["n_category_only_disagreements"] for r in rows),
        "total_residues_only_one_builder": sum(
            r["n_only_phenix"] + r["n_only_standalone"] for r in rows),
        "total_flipped_phenix": sum(r["n_flipped_phenix"] for r in rows),
        "total_flipped_standalone": sum(r["n_flipped_standalone"] for r in rows),
    }


# INCOMPLETE: 12 of the 17 models, committed in round 18 as the most that can be
# recovered. `ref/research/tolerance_benchmark_round6.md` tables the per-model
# disagreement rate for the 12 models with a NONZERO rate; the 5 that agreed perfectly
# are named nowhere, because a table of interesting cases is not a record of a set.
#
# That is exactly the defect the round-17 audit was looking for, and it bites here: the
# quoted "worst model 16.4 %" (30IZ, 12/73) is recoverable, but the 7.5 % aggregate rate
# it sits in is NOT -- it is 48 disagreements over 639 residues across all 17 models,
# and 5 of those models cannot be re-run because nothing says what they were.
#
# Note also this set includes 9LK0, which is absent from the 17-model sets used by
# `bench_t05_bond_rmsd.py` and `bench_t05_restraint_library.py`. The sibling benchmarks
# are NOT interchangeable sources for it.
DEFAULT_SET = [
    "30IZ", "9PN7", "24MR", "9LK0", "9HX9", "9HW2", "11AF", "30TW", "37AP", "37AS",
    "37BG", "28SV",
]
SET_IS_COMPLETE = False
SET_SHORTFALL = "12 of 17 -- the 5 models with ZERO flip disagreements were never named"


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
        print(f"WARNING: the committed set is INCOMPLETE -- {SET_SHORTFALL}.\n"
              f"Running {len(ids)} entries; published figures used more.",
              file=sys.stderr)

    cache = Path(args.cache) if args.cache else Path(tempfile.gettempdir()) / "bench_cache_t14"
    rows, skipped = collect(ids, cache)
    summary = summarize(rows)
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps({"rows": rows, "skipped": skipped, "summary": summary}, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
