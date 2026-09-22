#!/usr/bin/env python3
"""Benchmark the T16 interface-BSA agreement tolerance: biotite SASA vs PDBePISA.

De-provisionalizes the `Interface buried surface area | |Δ| ≤ 10 %` tolerance in
`ref/thresholds_and_standards.md` / `ref/structural_criteria.yaml` (GitHub #18) by
measuring the actual inter-program spread on a set of deposited complexes instead
of asserting a magnitude.

Method (matched probe radius, with the asymmetric atom selections actually benchmarked):
  - biotite  : Shrake-Rupley SASA, 1.4 Å probe, ProtOr radii, protein atoms only
               (`struc.filter_amino_acids` — no waters, no hetero), exactly the
               recipe `scripts/t16_interface_quality.py` uses. Total buried area
               ΣSASA(chains) − SASA(complex), i.e. *both* sides of the interface.
  - PDBePISA : `interface_area` from the PDBe PISA REST API for biological
               assembly 1. PISA reports the area buried on *one* side (the mean of
               the two), so the comparable quantity is 2 × interface_area. PISA uses a
               Lee & Richards surface and includes ligand/hetero atoms in the
               molecule surface; those deliberate definitional differences are part
               of the empirical tolerance, not a matched-protein-only comparison.

Comparison is per interface, restricted to protein-protein interfaces between two
distinct author chains present in the asymmetric unit (symmetry-mate interfaces are
skipped: the ASU coordinates cannot reproduce them without applying the operator).

Usage:
    python3 scripts/bench_t16_bsa_vs_pisa.py                 # default test set
    python3 scripts/bench_t16_bsa_vs_pisa.py 1brs 2ptc ...   # explicit entries
    python3 scripts/bench_t16_bsa_vs_pisa.py --cache DIR --json out.json
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

PISA_API = "https://www.ebi.ac.uk/pdbe/api/pisa/interfaces/{pdb_id}/1"
RCSB_PDB = "https://files.rcsb.org/download/{pdb_id}.pdb"

# Test set spanning interface size and complex type: protease-inhibitor and other
# transient complexes (~600-900 Å² per side), antibody-antigen, obligate/large
# interfaces (> 1500 Å²), and a multi-interface oligomer (4HHB, haemoglobin).
#
# 1CHO is deliberately absent: its α-chymotrypsin is deposited as three fragments
# (E 1-10, F 16-146, G 149-245), so every pair it contributes is either
# intramolecular or half of a split interface. The `fragment_pairs` guard catches
# the intramolecular ones automatically; the entry is dropped outright because the
# remaining pairs are partial interfaces.
DEFAULT_SET = [
    "1brs",  # barnase-barstar (transient, the canonical case)
    "2ptc",  # trypsin-BPTI
    "1ppf",  # leukocyte elastase-OMTKY3
    "1cse",  # subtilisin Carlsberg-eglin c
    "2sni",  # subtilisin novo-chymotrypsin inhibitor 2
    "1tgs",  # trypsinogen-pancreatic secretory trypsin inhibitor
    "3sgb",  # S. griseus protease B-OMTKY3
    "2sic",  # subtilisin-SSI
    "1avx",  # trypsin-soybean trypsin inhibitor
    "1ay7",  # barnase-SD-barstar
    "1vfb",  # Fv D1.3-lysozyme (antibody-antigen)
    "3hfm",  # HyHEL-10 Fab-lysozyme (antibody-antigen, 3 chains)
    "1fss",  # acetylcholinesterase-fasciculin (large)
    "1dfj",  # RNase A-RNase inhibitor (very large)
    "1e96",  # Rac-p67phox
    "1gla",  # glycerol kinase-IIA(Glc)
    "4hhb",  # haemoglobin (multi-interface oligomer, alpha2beta2)
]


def fetch(url: str, dest: Path, binary: bool = False) -> Path:
    """Download `url` to `dest` unless already cached. Returns `dest`."""
    if dest.exists() and dest.stat().st_size:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=60) as resp:
        data = resp.read()
    dest.write_bytes(data)
    return dest


def pisa_interfaces(pdb_id: str, cache: Path) -> tuple[list[dict[str, Any]], str | None]:
    """PISA assembly-1 interface records for `pdb_id`, and why the list is empty.

    Returns `(interfaces, reason)`; exactly one is meaningful. An empty list used to
    mean both "the API failed" and "PISA lists no interfaces here", which are opposite
    facts — the first loses a committed entry from the denominator, the second is a
    real measurement of zero. This is the only benchmark in the set that depends on a
    live third-party endpoint at run time (every sibling reads static RCSB files), so
    it is the one where a transient 5xx or a rate limit can silently shrink the set
    (#127).
    """
    dest = cache / f"pisa_{pdb_id}.json"
    try:
        fetch(PISA_API.format(pdb_id=pdb_id), dest)
    except urllib.error.HTTPError as exc:
        print(f"  ! PISA API {exc.code} for {pdb_id} — skipped", file=sys.stderr)
        return [], f"PISA API HTTP {exc.code}"
    payload = json.loads(dest.read_text()).get(pdb_id, {})
    interfaces = payload.get("assembly", {}).get("interfaces", []) or []
    return interfaces, None if interfaces else "PISA lists no interfaces"


def fragment_pairs(model: Path) -> set[frozenset[str]]:
    """Chain pairs that are fragments of ONE molecule, not an interface.

    A cleaved protein deposited as several chains (1CHO's α-chymotrypsin is chains
    E 1-10, F 16-146, G 149-245, held together by disulfides) presents chain pairs
    that PISA lists as interfaces but which are intramolecular contacts. Buried area
    across them is not interface area, and PISA's own `number_disulfide_bonds` field
    reads 0 for exactly these pairs, so it cannot serve as the filter.

    Test: the two chains are in the same covalent (SSBOND) component **and** their
    residue-number ranges are disjoint. Both halves matter — a Fab light/heavy pair
    is disulfide-linked too, but its chains both number from 1, so overlapping
    ranges keep it in as the genuine two-molecule interface it is.
    """
    bonds: list[tuple[str, str]] = []
    spans: dict[str, list[int]] = {}
    for line in model.read_text(errors="ignore").splitlines():
        if line.startswith("SSBOND") and len(line) > 35:
            a, b = line[15], line[29]
            if a != b:
                bonds.append((a, b))
        elif line.startswith("ATOM"):
            spans.setdefault(line[21], []).append(int(line[22:26]))

    # Connected components of the inter-chain covalent graph (chain counts are tiny,
    # so a plain BFS is clearer than union-find and just as fast).
    adjacent: dict[str, set[str]] = {}
    for a, b in bonds:
        adjacent.setdefault(a, set()).add(b)
        adjacent.setdefault(b, set()).add(a)
    component: dict[str, str] = {}
    for start in adjacent:
        if start in component:
            continue
        queue = [start]
        while queue:
            chain = queue.pop()
            if chain in component:
                continue
            component[chain] = start
            queue.extend(adjacent.get(chain, ()))

    pairs = set()
    for a in spans:
        for b in spans:
            if a >= b or a not in component or component[a] != component.get(b):
                continue
            lo_a, hi_a = min(spans[a]), max(spans[a])
            lo_b, hi_b = min(spans[b]), max(spans[b])
            if hi_a < lo_b or hi_b < lo_a:  # disjoint numbering
                pairs.add(frozenset((a, b)))
    return pairs


def biotite_bsa(model: Path, chain_a: str, chain_b: str) -> float | None:
    """Total buried area for the `chain_a`/`chain_b` pair, by the t16 script's recipe.

    Returns None when either chain has no protein atoms in the deposited ASU.
    """
    import numpy as np
    import biotite.structure as struc
    import biotite.structure.io.pdb as pdb

    arr = pdb.get_structure(pdb.PDBFile.read(str(model)), model=1)
    arr = arr[struc.filter_amino_acids(arr)]
    pair = arr[np.isin(arr.chain_id, [chain_a, chain_b])]
    a = pair[pair.chain_id == chain_a]
    b = pair[pair.chain_id == chain_b]
    if not a.array_length() or not b.array_length():
        return None
    # Pin the biotite 1.7.1 default used for the published benchmark.  The
    # 1000-point quadrature is load-bearing (and differs measurably from 100).
    complex_sasa = float(np.nansum(struc.sasa(pair, point_number=1000)))
    separated = float(np.nansum(struc.sasa(a, point_number=1000))) + float(
        np.nansum(struc.sasa(b, point_number=1000))
    )
    return separated - complex_sasa


def collect(pdb_ids: list[str], cache: Path,
            pause: float = 0.5) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Run both oracles over every eligible protein-protein interface in `pdb_ids`.

    Returns `(rows, skipped)` like every sibling benchmark. It previously returned rows
    alone and dropped failures at four `continue`s with nothing but a stderr line, so a
    re-run's completeness was unverifiable from its own output — and the published band
    is anchored to the observed **max**, which is exactly what a drop biased toward the
    slow multi-interface entries would remove (#127).
    """
    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for pdb_id in pdb_ids:
        pdb_id = pdb_id.lower()
        print(f"[{pdb_id}]", file=sys.stderr)
        interfaces, reason = pisa_interfaces(pdb_id, cache)
        if not interfaces:
            skipped.append({"pdb_id": pdb_id.upper(), "interface": "", "reason": reason})
            # The pause is a rate limit, so it matters MOST after a failure: leaving it
            # to the end of the loop body meant a throttled call removed the delay
            # before the next one, making cascades likelier.
            time.sleep(pause)
            continue
        try:
            model = fetch(RCSB_PDB.format(pdb_id=pdb_id.upper()), cache / f"{pdb_id}.pdb")
        except urllib.error.HTTPError as exc:
            print(f"  ! RCSB {exc.code} for {pdb_id} — skipped", file=sys.stderr)
            skipped.append({"pdb_id": pdb_id.upper(), "interface": "",
                            "reason": f"RCSB HTTP {exc.code}"})
            time.sleep(pause)
            continue
        intramolecular = fragment_pairs(model)
        for iface in interfaces:
            mols = iface.get("molecules", [])
            if len(mols) != 2 or any(m.get("molecule_class") != "Protein" for m in mols):
                continue
            ca, cb = mols[0].get("chain_id"), mols[1].get("chain_id")
            if not ca or not cb or ca == cb:
                continue  # symmetry mate — not reproducible from the ASU alone
            if frozenset((ca, cb)) in intramolecular:
                print(f"  ! {pdb_id} {ca}/{cb}: fragments of one molecule — skipped",
                      file=sys.stderr)
                skipped.append({"pdb_id": pdb_id.upper(), "interface": f"{ca}/{cb}",
                                "reason": "fragments of one molecule"})
                continue
            bsa = biotite_bsa(model, ca, cb)
            if bsa is None:
                print(f"  ! {pdb_id} {ca}/{cb}: chain missing from ASU — skipped", file=sys.stderr)
                skipped.append({"pdb_id": pdb_id.upper(), "interface": f"{ca}/{cb}",
                                "reason": "chain missing from ASU"})
                continue
            pisa_total = 2.0 * float(iface["interface_area"])
            mean = (bsa + pisa_total) / 2.0
            rows.append(
                {
                    "pdb_id": pdb_id,
                    "interface": f"{ca}/{cb}",
                    "biotite_bsa_total": round(bsa, 1),
                    "pisa_interface_area": round(float(iface["interface_area"]), 1),
                    "pisa_bsa_total": round(pisa_total, 1),
                    "delta": round(bsa - pisa_total, 1),
                    "rel_delta_pct": round(100.0 * (bsa - pisa_total) / mean, 2),
                    "abs_rel_delta_pct": round(abs(100.0 * (bsa - pisa_total) / mean), 2),
                    "pisa_n_interface_residues": iface.get("number_interface_residues"),
                }
            )
            print(f"  {ca}/{cb}: biotite {bsa:8.1f}  PISA×2 {pisa_total:8.1f}"
                  f"  Δ {bsa - pisa_total:+7.1f} ({rows[-1]['rel_delta_pct']:+.1f} %)",
                  file=sys.stderr)
        time.sleep(pause)
    # NOTE the scope: `skipped` records the four paths that can LOSE an entry (PISA or
    # RCSB failing, fragments of one molecule, a chain absent from the ASU). The two
    # filters above it — non-protein pairs and symmetry mates — are eligibility rules,
    # deterministic given the input, and are not failures to record.
    return rows, skipped


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Signed-bias and |Δ| distribution over all measured interfaces."""
    signed = [r["rel_delta_pct"] for r in rows]
    absolute = sorted(r["abs_rel_delta_pct"] for r in rows)
    if not rows:
        return {"n": 0}

    def pct(p: float) -> float:
        idx = min(len(absolute) - 1, max(0, round(p / 100.0 * (len(absolute) - 1))))
        return absolute[idx]

    return {
        "n_interfaces": len(rows),
        "n_entries": len({r["pdb_id"] for r in rows}),
        "signed_median_pct": round(statistics.median(signed), 2),
        "signed_mean_pct": round(statistics.fmean(signed), 2),
        "abs_median_pct": round(statistics.median(absolute), 2),
        "abs_p90_pct": round(pct(90), 2),
        "abs_max_pct": round(absolute[-1], 2),
        "abs_min_pct": round(absolute[0], 2),
    }


def main() -> int:
    from benchmark_environment import announce_benchmark_environment

    announce_benchmark_environment()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pdb_ids", nargs="*", default=None, help="PDB IDs (default: built-in set)")
    ap.add_argument("--cache", default=None, help="download cache directory")
    ap.add_argument("--json", dest="json_out", default=None, help="write full results here")
    args = ap.parse_args()

    # Default outside the working tree: the no-argument invocation downloads a few
    # hundred MB of coordinates, and dropping that wherever the user happens to be
    # standing is one `git add -A` away from committing it.
    cache = Path(args.cache) if args.cache else Path(tempfile.gettempdir()) / "bench_cache_t16"
    requested = args.pdb_ids or DEFAULT_SET
    rows, skipped = collect(requested, cache)
    summary = summarize(rows)
    # `requested` and `skipped` ship with the results so a later reader can tell a
    # complete run from one that lost entries to a flaky PISA endpoint.
    out = {"requested_ids": list(requested), "rows": rows, "skipped": skipped,
           "summary": summary}
    if skipped:
        print(f"!! {len(skipped)} interface(s)/entr(ies) skipped — see `skipped` in the "
              f"JSON; this run does NOT cover the full committed set.", file=sys.stderr)
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
