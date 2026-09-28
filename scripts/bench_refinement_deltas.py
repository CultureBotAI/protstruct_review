#!/usr/bin/env python3
"""Benchmark the §4 refinement Δ-tolerances by actually refining.

`ref/thresholds_and_standards.md` §4 governs the compare→refine flow and asserts how
far a refinement may move a quantity before it counts as degradation:

  - ΔRMSD sanity            RMSD_post ≤ RMSD_pre + 0.12 Å (d_min < 2.5 A) / + 0.25 A (>= 2.5, round 42)
  - Geometry did not degrade  the resolution-conditional §4 Δ clause (favored − 0.5/− 6 pp;
                              clashscore ratio < 5x; rotamer + 4 pp) AND the separate absolute
                              floors (clashscore <= 4; favored >= 97 %; rotamer <= 2 %)

  (The flat + 0.05 A ΔRMSD and the max()/min() forms above were round 5's; this benchmark is what
  made them resolution-conditional across rounds 7-42. The live values are in §4.)

These are **not** cross-tool agreement tolerances, so none of the rounds 1-4 machinery
applies: the question is not "do two tools agree" but "how much does a refinement that
did *not* degrade the model actually move these numbers". That needs a refine →
re-measure loop, which is what this does.

Method — the null case. Each deposited model is re-refined against its own deposited
data with `phenix.refine`. The model is already at its refinement optimum, so a
correctly-behaving refinement should move these quantities very little; whatever
spread remains is the floor a Δ band has to clear.

Every tolerance above mixes a **Δ band** with an **absolute floor** (4, 97 %, 2 %).
They are different claims and only the Δ is measurable this way, so the floors are
reported separately: how often deposited structures violate them tells you whether
they are refinement checks at all or simply quality bars in disguise.

RMSD is computed **without re-superposition**, over matched (chain, resseq) Cα pairs.
Refinement preserves the coordinate frame, so the raw shift is the quantity of
interest, and superposing first would absorb part of what is being measured.

Usage:
    python3 scripts/bench_refinement_deltas.py --cache DIR --json out.json
    python3 scripts/bench_refinement_deltas.py 12LO 30IZ --cache DIR
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import sys
from pathlib import Path
from typing import Any

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from toolchain import run_logged, split_args
from refinement_cache import OperationFailed, cached_phenix_operation
from deterministic_cache import deterministic_product, generator_identity

_CLASHSCORE = re.compile(r"clashscore\s*=\s*([\d.]+)")
_RAMA_FAV = re.compile(r"SUMMARY:\s*([\d.]+)%\s*favored")
_ROTA_OUT = re.compile(r"SUMMARY:\s*([\d.]+)%\s*outliers")
_R_WORK = re.compile(r"r_work=([\d.]+)\s+r_free=([\d.]+)")

# The absolute floors embedded in the §4 tolerances, split out so they can be
# assessed as quality bars rather than as refinement deltas.
FLOOR_CLASHSCORE, FLOOR_FAVORED_PCT, FLOOR_ROTAMER_OUTLIER_PCT = 4.0, 97.0, 2.0

MACRO_CYCLES = 3


def ca_atoms(model: Path) -> dict[tuple[str, str], tuple[float, float, float]]:
    """Cα coordinates keyed by (chain, resseq+icode), altloc A or blank only."""
    out = {}
    for line in model.read_text(errors="ignore").splitlines():
        if not line.startswith("ATOM") or line[12:16].strip() != "CA":
            continue
        if line[16] not in (" ", "A"):
            continue
        key = (line[21], line[22:27].strip())
        if key not in out:
            out[key] = (float(line[30:38]), float(line[38:46]), float(line[46:54]))
    return out


def ca_shift_rmsd(before: Path, after: Path) -> tuple[float | None, int]:
    """RMSD over matched Cα pairs with NO superposition — the raw refinement shift."""
    a, b = ca_atoms(before), ca_atoms(after)
    shared = sorted(set(a) & set(b))
    if not shared:
        return None, 0
    total = sum((a[k][0] - b[k][0]) ** 2 + (a[k][1] - b[k][1]) ** 2 + (a[k][2] - b[k][2]) ** 2
                for k in shared)
    return round((total / len(shared)) ** 0.5, 4), len(shared)


def run_tool(exe: str, model: Path, work: Path, tag: str, pattern: re.Pattern) -> float | None:
    """Run a PHENIX validation tool on `model` and pull one number out of its log."""
    try:
        paths = cached_phenix_operation(
            work, exe, executable=exe, inputs={"model": model}, arguments=[model],
            required_outputs={}, timeout=3600, runner=run_logged,
        )
    except OperationFailed:
        return None
    match = pattern.search(paths["stdout"].read_text(errors="ignore"))
    return float(match.group(1)) if match else None


def measure(model: Path, work: Path, tag: str) -> dict[str, Any]:
    """Clashscore, Ramachandran favored % and rotamer outlier % for one model."""
    return {
        "clashscore": run_tool("phenix.clashscore", model, work, f"cs_{tag}", _CLASHSCORE),
        "rama_favored_pct": run_tool("phenix.ramalyze", model, work, f"rama_{tag}", _RAMA_FAV),
        "rotamer_outlier_pct": run_tool("phenix.rotalyze", model, work, f"rota_{tag}", _ROTA_OUT),
    }


# Restraints a crystallographer would actually apply at low resolution. Reference-model
# restraints are deliberately NOT included: they restrain to a higher-resolution
# homolog, which this benchmark does not have, and pointing them at the input model
# would restrain it to itself.
LOW_RES_RESTRAINTS = "ncs_search.enabled=True secondary_structure.enabled=True"


def refine_prefix(model_stem: str, restraints: bool) -> str:
    """Output prefix for a refinement run.

    These human-readable prefixes distinguish restrained and unrestrained runs.
    Cache identity additionally binds exact input/build/argument bytes (#777), so
    an output filename alone can no longer authenticate a previous invocation.

    `MACRO_CYCLES` is in the prefix for the same reason, and was not (#124): the
    argument above applies unchanged to any parameter that moves the refinement, and
    this repo does retune them between rounds -- `restraints` itself was added because
    round 7's null spreads came from default weights.
    """
    return f"{'rr' if restraints else 'r'}{MACRO_CYCLES}_{model_stem}"


# Causes worth naming rather than reporting as "phenix.refine failed". Round 37 lost 7
# of 18 entries and the batch said only that (#242); the log said exactly what was
# wrong. The first entry here is that case: older depositions frequently carry no
# R-free flags phenix.refine will accept.
#
# NOTE what the R-free case does NOT do: it does not set r_free_flags.generate=True.
# That would refine against NEWLY GENERATED flags, so R-free is no longer comparable
# with the deposited value and the run is not the same null re-refinement every other
# entry got. It is a methodological choice to register, not a default to reach for.
_REFINE_FAILURES: list[tuple[str, str]] = [
    # Both R-free causes carry the SAME caveat. Splitting them and warning on only one
    # meant the earliest-occurrence rule (#249) could report the more precise cause and
    # silently drop the warning -- which is what happened to round 37's real logs the
    # moment that rule landed.
    ("No array of R-free flags found", _RFREE_CAVEAT := (
        "no usable R-free flags in the deposited data (phenix suggests "
        "r_free_flags.generate=True, which would refine against NEW flags -- a "
        "different experiment, so it is not done here)")),
    ("r_free_flags.generate", _RFREE_CAVEAT),
    ("Unknown scattering type",
     "an atom's scattering type is absent from the table phenix uses"),
    ("Sorry: Crystal symmetry mismatch",
     "crystal symmetry differs between the model and the data"),
]


_MAX_QUOTED = 300


def refine_failure_reason(log: Path) -> str:
    """Why `phenix.refine` produced no output, from its own log.

    Falls back to the last non-empty lines rather than to a bare "failed": an
    unrecognised cause that is quoted can be diagnosed by a reader, and one that is
    discarded cannot. A 39 % failure rate reporting no reason is indistinguishable
    from a broken pipeline (#242).
    """
    # Any unreadable path is treated as a missing log (#250). This function's contract
    # is "never fail, always explain" -- it runs while the caller is recording a SKIP,
    # so raising here turns one skipped entry into a dead batch. `log.exists()` alone
    # is not enough: it is true for a directory, and read_text() then throws.
    if not log.exists():
        return "phenix.refine produced no output and no log"
    try:
        text = log.read_text(errors="ignore")
    except OSError:
        # Present but unreadable is a DIFFERENT fact from absent -- a directory where a
        # log should be says something went wrong with the run's plumbing, not with the
        # refinement. Collapsing the two would hide that.
        return "phenix.refine produced no output and no readable log"
    # EARLIEST occurrence in the log, not first in this list (#249). phenix prints the
    # r_free_flags.generate suggestion from several unrelated failure paths, so it is
    # the needle most likely to co-occur with a real cause and mask it -- and a
    # confidently wrong diagnosis is worse than the bare "failed" this replaces,
    # because that at least asserted nothing.
    hits = [(text.find(needle), reason) for needle, reason in _REFINE_FAILURES
            if needle in text]
    if hits:
        return min(hits)[1]
    tail = [l.strip() for l in text.splitlines() if l.strip()][-3:]
    if not tail:
        return "phenix.refine failed"
    # Bounded: this lands in a committed JSON record, and one malformed log should not
    # dominate the file (#249).
    # Control characters out: a truncated or partially-written log otherwise puts NULs
    # into a committed JSON record, where nothing downstream expects them (#250).
    quoted = "".join(c if c.isprintable() or c == " " else "?"
                     for c in " / ".join(tail))
    if len(quoted) > _MAX_QUOTED:
        quoted = quoted[:_MAX_QUOTED] + " …(truncated)"
    return "phenix.refine failed: " + quoted


def refine(model: Path, mtz: Path, work: Path,
           restraints: bool = False) -> tuple[Path | None, dict[str, Any]]:
    """Re-refine a deposited model against its own data; returns (refined model, R stats).

    With `restraints=True`, adds the NCS and secondary-structure restraints normally
    used at low resolution — the round-7 null spreads came from default weights with
    neither, which likely made them pessimistic.
    """
    # The operation directory supplies input identity; this simple output basename
    # avoids interpreting glob metacharacters from a scientific input filename.
    prefix = refine_prefix("model", restraints)
    arguments = [model, mtz, f"main.number_of_macro_cycles={MACRO_CYCLES}"]
    if restraints:
        arguments.extend(split_args(LOW_RES_RESTRAINTS))
    arguments.extend([f"output.prefix={prefix}", "--overwrite"])
    try:
        paths = cached_phenix_operation(
            work, "phenix.refine", executable="phenix.refine",
            inputs={"model": model, "reflections": mtz}, arguments=arguments,
            required_outputs={"model": f"{prefix}_001.pdb"}, timeout=7200, runner=run_logged,
        )
    except OperationFailed as error:
        log = error.log_path
        return None, {"failure_reason": refine_failure_reason(log)}
    r_values = _R_WORK.findall(paths["stdout"].read_text(errors="ignore"))
    stats: dict[str, Any] = {}
    if r_values:
        stats["r_work_pre"], stats["r_free_pre"] = float(r_values[0][0]), float(r_values[0][1])
        stats["r_work_post"], stats["r_free_post"] = float(r_values[-1][0]), float(r_values[-1][1])
    return paths["model"], stats


def collect(pairs: list[tuple[Path, Path]], work: Path,
            restraints: bool = False) -> tuple[list[dict], list[dict]]:
    """Refine each model and measure the geometry quantities before and after."""
    rows, skipped = [], []
    work.mkdir(parents=True, exist_ok=True)
    for model, mtz in pairs:
        name = model.stem.upper()
        print(f"[{name}]", file=sys.stderr)
        pre = measure(model, work, "pre")
        if pre["clashscore"] is None or pre["rama_favored_pct"] is None:
            skipped.append({"pdb_id": name, "reason": "pre-refinement validation failed"})
            continue
        refined, r_stats = refine(model, mtz, work, restraints=restraints)
        if refined is None:
            why = r_stats.get("failure_reason", "phenix.refine failed")
            print(f"  ! {why}", file=sys.stderr)
            skipped.append({"pdb_id": name, "reason": why})
            continue
        post = measure(refined, work, "postr" if restraints else "post")
        if post["clashscore"] is None or post["rama_favored_pct"] is None:
            skipped.append({"pdb_id": name, "reason": "post-refinement validation failed"})
            continue
        shift, n_ca = ca_shift_rmsd(model, refined)

        row: dict[str, Any] = {"pdb_id": name, "n_ca_matched": n_ca, "ca_shift_rmsd": shift,
                               **r_stats}
        for key in ("clashscore", "rama_favored_pct", "rotamer_outlier_pct"):
            row[f"{key}_pre"], row[f"{key}_post"] = pre[key], post[key]
            if pre[key] is not None and post[key] is not None:
                row[f"{key}_delta"] = round(post[key] - pre[key], 4)
        # Do the deposited models even satisfy the absolute floors?
        row["floor_clashscore_pre_ok"] = (pre["clashscore"] or 0) <= FLOOR_CLASHSCORE
        row["floor_favored_pre_ok"] = (pre["rama_favored_pct"] or 0) >= FLOOR_FAVORED_PCT
        row["floor_rotamer_pre_ok"] = (pre["rotamer_outlier_pct"] or 0) <= FLOOR_ROTAMER_OUTLIER_PCT
        rows.append(row)
        print(f"  Cα shift {shift} Å over {n_ca} | clash {pre['clashscore']}→{post['clashscore']}"
              f" | favored {pre['rama_favored_pct']}→{post['rama_favored_pct']}"
              f" | rota_out {pre['rotamer_outlier_pct']}→{post['rotamer_outlier_pct']}",
              file=sys.stderr)
    return rows, skipped


def summarize(rows: list[dict]) -> dict[str, Any]:
    """Δ distributions, plus how often deposited models meet the absolute floors."""
    if not rows:
        return {"n": 0}

    def stats(key: str) -> dict[str, Any]:
        """Signed AND absolute statistics.

        For a degradation check the signed direction is the point — an absolute
        median cannot distinguish "refinement systematically worsens this" from
        "refinement moves it both ways". Reporting only |Δ| once made an even
        4-up/4-down split read as a systematic +1.87 worsening.
        """
        values = [r[key] for r in rows if r.get(key) is not None]
        if not values:
            return {"n": 0}
        absolute = sorted(abs(v) for v in values)
        idx = min(len(absolute) - 1, max(0, round(0.9 * (len(absolute) - 1))))
        return {
            "n": len(values),
            "signed_median": round(statistics.median(values), 4),
            "n_worsened": sum(1 for v in values if v > 0),
            "n_improved": sum(1 for v in values if v < 0),
            "abs_median": round(statistics.median(absolute), 4),
            "abs_p90": round(absolute[idx], 4),
            "signed_min": round(min(values), 4),
            "signed_max": round(max(values), 4),
        }

    return {
        "n_entries": len(rows),
        "ca_shift_rmsd": stats("ca_shift_rmsd"),
        "clashscore_delta": stats("clashscore_delta"),
        "rama_favored_delta_pp": stats("rama_favored_pct_delta"),
        "rotamer_outlier_delta_pp": stats("rotamer_outlier_pct_delta"),
        "absolute_floors_met_by_deposited_models": {
            "clashscore <= 4": sum(1 for r in rows if r["floor_clashscore_pre_ok"]),
            "favored >= 97 %": sum(1 for r in rows if r["floor_favored_pre_ok"]),
            "rotamer outliers <= 2 %": sum(1 for r in rows if r["floor_rotamer_pre_ok"]),
            "of": len(rows),
        },
    }


# Perturbation levels (Å, Gaussian per-coordinate) for the detection test. Chosen to
# straddle the null-refinement spread (Cα shift up to 0.107 Å) so the smallest level
# is inside the noise and the largest is unambiguous damage.
PERTURB_SIGMAS = [0.05, 0.1, 0.2, 0.3, 0.5, 1.0]


def _perturb_coordinates(source: bytes, sigma: float, seed: int) -> bytes:
    """Keep the original seeded per-coordinate Gaussian/PDB rounding algorithm."""
    import random

    rng = random.Random(seed)
    lines = []
    for line in source.decode(errors="ignore").splitlines():
        if line.startswith(("ATOM", "HETATM")) and len(line) >= 54:
            x, y, z = float(line[30:38]), float(line[38:46]), float(line[46:54])
            x, y, z = (v + rng.gauss(0, sigma) for v in (x, y, z))
            line = f"{line[:30]}{x:8.3f}{y:8.3f}{z:8.3f}{line[54:]}"
        lines.append(line)
    return ("\n".join(lines) + "\n").encode()


def perturb(model: Path, sigma: float, work: Path, seed: int = 7) -> Path:
    """Generate or verify deterministic coordinates with source/seed provenance.

    Coordinate generation is cheap, so compute the expected bytes even on reuse.
    The producing script digest/runtime conservatively separate generator
    revisions; even unrelated edits to this script make a new bundle.
    Old filename-only products are neither adopted nor overwritten (#812).
    """
    source = model.read_bytes()
    sigma = float(sigma)
    expected = _perturb_coordinates(source, sigma, seed)
    provenance = {
        "source": {"path": str(model.resolve()),
                   "sha256": hashlib.sha256(source).hexdigest()},
        "sigma_hex": sigma.hex(),
        "seed": seed,
        "generator": generator_identity(
            __file__, "random.Random.gauss/PDB-coordinate-jitter-v1",
        ),
    }
    return deterministic_product(
        work, "pdb-perturb", filename="model.pdb", provenance=provenance, expected=expected,
    )


def detection_test(model: Path, work: Path) -> list[dict]:
    """Do the §4 bands catch a *known* degradation? The false-negative side.

    The null-case benchmark calibrates only how often a good refinement is wrongly
    flagged. This does the converse: damage a deposited model by a known amount and
    record which clause, if any, notices. A band that never fires is not a check.
    """
    pre = measure(model, work, "pre")
    rows = []
    for sigma in PERTURB_SIGMAS:
        damaged = perturb(model, sigma, work)
        post = measure(damaged, work, f"perturb{sigma}")
        shift, _ = ca_shift_rmsd(model, damaged)
        if post["clashscore"] is None or post["rama_favored_pct"] is None:
            rows.append({"sigma": sigma, "ca_shift_rmsd": shift, "measurement_failed": True})
            continue
        favored_drop = (pre["rama_favored_pct"] or 0) - (post["rama_favored_pct"] or 0)
        rotamer_rise = (post["rotamer_outlier_pct"] or 0) - (pre["rotamer_outlier_pct"] or 0)
        rows.append({
            "sigma": sigma,
            "ca_shift_rmsd": shift,
            "clashscore_pre": pre["clashscore"], "clashscore_post": post["clashscore"],
            "rama_favored_pct_post": post["rama_favored_pct"],
            "rotamer_outlier_pct_post": post["rotamer_outlier_pct"],
            # The bands as applied after the round-5 revision.
            "caught_by_rmsd": (shift or 0) > 0.15,
            "caught_by_favored": favored_drop > 1.5,
            "caught_by_rotamer": rotamer_rise > 4.0,
        })
        rows[-1]["caught"] = any(rows[-1][k] for k in
                                 ("caught_by_rmsd", "caught_by_favored", "caught_by_rotamer"))
    return rows


def find_pairs(cache: Path, ids: list[str] | None) -> list[tuple[Path, Path]]:
    """Match cached `<id>.pdb` with `<id>_g_obs.mtz` from the R-offset benchmark."""
    pairs = []
    for mtz in sorted(cache.glob("*_g_obs.mtz")):
        stem = mtz.name[: -len("_g_obs.mtz")]
        model = cache / f"{stem}.pdb"
        if not model.exists():
            continue
        if ids and stem.upper() not in {i.upper() for i in ids}:
            continue
        pairs.append((model, mtz))
    return pairs


# INCOMPLETE: 16 of the 37 entries, committed in round 18 as the most recoverable.
#
# **This WAS the most expensive partial record in the repo, resolved in round 42.** Both
# §4 X-ray band widths were once set just above a null maximum this set cannot reproduce:
#
#   ΔRMSD, d_min >= 2.5 A   band +0.35 A   set just above a null max of 0.285 A
#   favored, d_min >= 2.5 A band -6 pp     set just above a null max of 5.26 pp
#
# Both maxima came from the ~11 low-resolution entries round 7 added, named nowhere. Round
# 42 re-based both widths onto a 99/95 coverage bound over the 44 fresh NAMED entries
# (rounds 37/38/41, scripts/analyze_xray_band_coverage.py): the Ca band became +0.25 A and
# the favored band is kept at -6 pp but now backed as ~98% coverage. So the widths no
# longer depend on this lost set at all -- #225's research showed a lone observed maximum
# was a biased, low-confidence basis to begin with. This set still reproduces only the
# HIGH-resolution end of the OLD benchmark, which is why it stays marked INCOMPLETE.
#
# Recovered from three places, none of them a record of the set:
#   - the original 8, from the per-entry table in
#     `ref/research/tolerance_benchmark_refinement_deltas.md`
#   - 6 more at 1.45-1.98 A, from round 10's table
#   - 2 singly-named outliers: 31LC (round 8, 0.172 A) and 43SK (round 11, 0.1011 A,
#     the breach that widened the `< 2.5 A` band)
#
# `find_pairs()` globs whatever `<id>.pdb` + `<id>_g_obs.mtz` sit in `--cache`, which is
# why the set was never pinned in the first place: the script's input was a directory
# someone had populated by hand.
DEFAULT_SET = [
    # the original 8
    "12LO", "37AP", "30TW", "30IZ", "24MR", "28SX", "28SW", "11AF",
    # round 10, the high-resolution end (1.45-1.98 A)
    "9LLR", "9LLN", "9LLO", "9LLP", "37AS", "32CR",
    # named outliers
    "31LC", "43SK",
]
SET_IS_COMPLETE = False
SET_SHORTFALL = ("16 of 37 -- the ~11 low-resolution entries that produce BOTH quoted "
                 "null maxima (0.285 A, 5.26 pp) are named nowhere")


def main() -> int:
    from benchmark_environment import announce_benchmark_environment

    announce_benchmark_environment()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pdb_ids", nargs="*")
    ap.add_argument("--cache", required=True,
                    help="directory holding <id>.pdb and <id>_g_obs.mtz (bench_t06_r_offset.py)")
    ap.add_argument("--work", help="where to run refinements (default: <cache>/refine)")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--restraints", action="store_true",
                    help="refine with NCS + secondary-structure restraints (low-resolution practice)")
    ap.add_argument("--detection-test", action="store_true",
                    help="perturb models by known amounts and report which bands fire")
    args = ap.parse_args()

    cache = Path(args.cache)
    # Fall back to the committed set rather than to whatever the cache happens to
    # hold. Globbing a directory is how this benchmark's set was lost in the first
    # place, and an earlier version of this block only *warned* about that while
    # still globbing -- so the set was declared but never used, and validate.sh's
    # gate did not notice because it checked for a declaration (#78).
    ids = args.pdb_ids or list(DEFAULT_SET)
    pairs = find_pairs(cache, ids)
    if not pairs:
        raise SystemExit(f"no <id>.pdb + <id>_g_obs.mtz pairs found in {cache}")
    if not args.pdb_ids:
        print(f"using the committed benchmark set ({len(ids)} entries, {len(pairs)} "
              f"present in {cache}).\nWARNING: the set is INCOMPLETE -- "
              f"{SET_SHORTFALL}. This is a new measurement, not a reproduction of the "
              f"published figures.", file=sys.stderr)
    work = Path(args.work) if args.work else cache / "refine"

    if args.detection_test:
        work.mkdir(parents=True, exist_ok=True)
        results = []
        for model, _ in pairs:
            print(f"[{model.stem.upper()}]", file=sys.stderr)
            for row in detection_test(model, work):
                row["pdb_id"] = model.stem.upper()
                results.append(row)
                print(f"  σ={row['sigma']:<5} shift {row.get('ca_shift_rmsd')} Å"
                      f"  caught={row.get('caught')}"
                      f" (rmsd={row.get('caught_by_rmsd')}, fav={row.get('caught_by_favored')},"
                      f" rota={row.get('caught_by_rotamer')})", file=sys.stderr)
        by_sigma = {}
        for row in results:
            by_sigma.setdefault(row["sigma"], []).append(bool(row.get("caught")))
        summary = {"detection_by_sigma": {str(s): {"caught": sum(v), "of": len(v)}
                                          for s, v in sorted(by_sigma.items())}}
        if args.json_out:
            Path(args.json_out).write_text(
                json.dumps({"rows": results, "summary": summary}, indent=2) + "\n")
        print(json.dumps(summary, indent=2))
        return 0

    rows, skipped = collect(pairs, work, restraints=args.restraints)
    summary = summarize(rows)
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps({"rows": rows, "skipped": skipped, "summary": summary}, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
