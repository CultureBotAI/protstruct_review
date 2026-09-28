#!/usr/bin/env python3
"""Benchmark the map-model half of the §4 refinement Δ-tolerances (cryo-EM).

`ref/thresholds_and_standards.md` §4 asserts:

  - Map-model fit did not degrade   CC_mask_post ≥ CC_mask_pre − 0.04 (d_min < 3.0 A) / − 0.06
                                    (d_min >= 3.0 A);  d_FSC_model_post ≤ d_FSC_model_pre × 1.05
                                    (the − 0.01 / + 0.05 A shown here originally were the round-5
                                    values this benchmark then made resolution-conditional/relative)

Neither quantity exists for X-ray data — `phenix.refine` reports no CC_mask, and
`d_FSC_model` is a map-model FSC measure — so this row cannot be covered by
`scripts/bench_refinement_deltas.py` and needs cryo-EM entries with released maps.

Method, per entry: real-space refine the deposited model against its own deposited
map, and measure CC_mask and d_FSC_model before and after. As in the X-ray case this
is the **null case** — the deposited model is already at its optimum, so whatever
spread remains is the floor a Δ band has to clear.

  - `phenix.map_correlations model map resolution=R` → CC_mask, CC_volume, CC_peaks.
    (`phenix.map_model_cc` is deprecated and refuses to run without `--force`.)
  - `phenix.mtriage model map` → d_FSC_model at FSC = 0 / 0.143 / 0.5, masked and
    unmasked.
  - `phenix.real_space_refine model map resolution=R` → the refined model.

Usage:
    python3 scripts/bench_refinement_deltas_em.py --cache DIR --json out.json
    # cache holds <pdb_id>.cif and its map as <pdb_id>.map, plus resolutions.json
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path
from typing import Any

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from refinement_cache import OperationFailed, cached_phenix_operation

_CC_MASK = re.compile(r"CC_mask\s*:\s*([\d.]+)")
# mtriage prints masked and unmasked columns; FSC=0.143 is the conventional model-map
# figure, so take that row's masked value. NOTE this summary value is unreliable —
# see `d_fsc_from_curve`, which is what this benchmark actually uses.
_D_FSC_MODEL = re.compile(r"FSC\(map,\s*model map\)=0\.143\s*:\s*([\d.]+)\s+([\d.]+)")

FSC_CURVE = "fsc_model.masked.mtriage.log"
FSC_THRESHOLD = 0.143


def read_fsc_curve(path: Path) -> list[tuple[float, float]]:
    """(d, FSC) pairs from mtriage's model-map FSC curve, ordered low → high resolution."""
    rows = []
    for line in path.read_text(errors="ignore").splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            inv_d, fsc = float(parts[0]), float(parts[1])
        except ValueError:
            continue
        if inv_d > 0:
            rows.append((1.0 / inv_d, fsc))
    return rows


# Consecutive shells that must stay below the threshold before a crossing counts.
# 20 is ~0.1 % of a typical 18 000-shell curve — long enough to reject a one-shell
# artefact, short enough not to run past a genuine crossing. See `d_fsc_from_curve`.
FSC_SUSTAIN_SHELLS = 20


def d_fsc_from_curve(rows: list[tuple[float, float]], threshold: float = FSC_THRESHOLD,
                     sustain: int = FSC_SUSTAIN_SHELLS) -> float | None:
    """Resolution beyond which FSC stays below `threshold` for `sustain` shells.

    Two naive rules both fail, in opposite directions:

    - **First crossing** (what mtriage reports) is defeated by a single anomalous
      LOW-resolution shell. 9VJD's masked model-map FSC dips to 0.073 at 23.11 Å and
      recovers above 0.5, so mtriage returns 23.11 Å for a 2.86 Å map.
    - **Last crossing** is defeated by oscillation in the HIGH-resolution tail. 27WR
      crosses 0.143 repeatedly between 2.15 and 2.70 Å (362 of 569 shells there are
      above the threshold), so the last crossing gives 2.24 Å — finer than the map's
      own 2.70 Å resolution, which is not credible.

    Requiring the crossing to be *sustained* rejects both. Measured against the five
    EM entries with curves, `sustain=20` gives 9VJD 2.77, 27WR 2.59, 21BQ 2.62,
    10GX 2.69, 10QT 2.99 — every one at or just inside its map resolution.
    """
    run = 0
    for i, (_, fsc) in enumerate(rows):
        if fsc < threshold:
            run += 1
            if run == sustain:
                return rows[i - sustain + 1][0]
        else:
            run = 0
    return None


def cache_key(tag: str, resolution: float) -> str:
    """Legacy display label, NOT cache identity (#777).

    Content-addressed operations below use input bytes, measured build and exact
    arguments. Consumers must use returned artifact paths, not rebuild old names.
    """
    return f"{tag}_{resolution:g}A"


def measure(model: Path, map_file: Path, resolution: float, work: Path,
            tag: str) -> dict[str, Any]:
    """CC_mask and masked d_FSC_model(0.143) for one model against one map."""
    # tag labels the caller's row, not the scientific invocation. Identical inputs
    # intentionally share evidence across screening and benchmark consumers.
    arguments = [model, map_file, f"resolution={resolution}"]
    inputs = {"model": model, "map": map_file}
    cc_manifest = mt_manifest = None
    try:
        result = cached_phenix_operation(
            work, "em-map-correlations", executable="phenix.map_correlations",
            inputs=inputs, arguments=arguments, required_outputs={}, timeout=7200,
        )
        cc_log, cc_manifest = result["stdout"], result["manifest"]
        cc_text = cc_log.read_text(errors="ignore")
    except OperationFailed as error:
        cc_log, cc_text = error.log_path, None
    # Fixed-name mtriage products live inside one authenticated invocation bundle.
    try:
        result = cached_phenix_operation(
            work, "em-mtriage", executable="phenix.mtriage",
            inputs=inputs, arguments=arguments,
            required_outputs={"curve": FSC_CURVE}, timeout=7200,
        )
        curve_path, mt_log = result["curve"], result["stdout"]
        mt_manifest = result["manifest"]
    except OperationFailed as error:
        curve_path, mt_log = None, error.log_path
    d_value = d_fsc_from_curve(read_fsc_curve(curve_path)) if curve_path else None
    cc = _CC_MASK.search(cc_text) if cc_text else None
    # mtriage's model-map FSC crossings are degenerate without half-maps: 27WR reports
    # FSC=0.5 at 29.79 Å for a 2.7 Å map, and 9VJD reports FSC=0.143 at 29.65 Å for a
    # 2.86 Å map (passing resolution= explicitly does not fix it, and the log shows
    # "d99 (half map 1): None"). A crossing far outside the map's own resolution is a
    # failed curve, not a measurement, so it is reported as unreliable rather than
    # differenced into a tolerance.
    plausible = d_value is not None and d_value <= 2.5 * resolution
    return {
        "cc_mask": float(cc.group(1)) if cc else None,
        "d_fsc_model_masked": d_value,
        "d_fsc_model_plausible": plausible,
        # The caller needs this to explain a failure, and used to rebuild it from the
        # tag by hand. When #119 put the resolution into the key, the two copies of the
        # naming rule fell out of step and every CC_mask failure started reporting
        # "map_correlations produced no log" instead of its real cause (#136).
        # Returning the path removes the duplication rather than re-syncing it.
        "cc_log": cc_log,
        "curve_path": curve_path,
        "fsc_log": mt_log,
        "cc_evidence": cc_manifest,
        "fsc_evidence": mt_manifest,
    }


# `Sorry:` is how cctbx reports a fatal, user-actionable problem; a bare traceback is
# a crash. Both end the run, but they mean different things to whoever reads the skip
# list, so the reason is carried through rather than flattened to "failed".
_SORRY = re.compile(r"^Sorry: (.+)$", re.MULTILINE)
_UNKNOWN_ENERGY = re.compile(
    r"Number of atoms with unknown nonbonded energy type symbols: (\d+)")


_SCATTERING = re.compile(
    r"model contains atoms which are not in the scattering table", re.IGNORECASE)
_UNKNOWN_TYPES = re.compile(r"Unknown atom types:\s*\n\s*(.+)")


def failure_reason(log: Path, step: str) -> str:
    """Why a PHENIX step stopped, in one line, from its log.

    A skip recorded as "<step> failed" is indistinguishable from a bug in this script.
    The common causes are neither: an entry carrying a ligand with no monomer-library
    restraints, or an atom type absent from the electron scattering table, cannot be
    processed by this pipeline at all. Those are properties of the entry and belong in
    the scope limits.

    Applied to every step, not just refinement. 10EN failed in `map_correlations` and
    vanished from the log entirely -- the caller appended a bare "map_correlations
    failed" to the skip list and printed nothing, so the entry simply disappeared
    between two bracketed ids.
    """
    if not log.exists():
        return f"{step} produced no log"
    text = log.read_text(errors="ignore")
    unknown = _UNKNOWN_ENERGY.search(text)
    if unknown:
        return (f"unparameterised ligand: {unknown.group(1)} atoms with unknown "
                f"nonbonded energy types (no monomer-library restraints)")
    if _SCATTERING.search(text):
        types = _UNKNOWN_TYPES.search(text)
        named = f": {types.group(1).strip()}" if types else ""
        return f"atom type absent from the electron scattering table{named}"
    sorry = _SORRY.search(text)
    if sorry:
        return f"{step}: {sorry.group(1).strip()}"
    if "Traceback" in text:
        return f"{step} crashed (traceback in log)"
    return f"{step} produced no usable result"


def refine_failure_reason(log: Path) -> str:
    """Back-compatible wrapper: the refinement step's failure reason."""
    return failure_reason(log, "real_space_refine")


def refine(model: Path, map_file: Path, resolution: float, work: Path,
           tag: str) -> tuple[Path | None, str | None]:
    """Real-space refine the model against its map.

    Returns (refined coordinates, failure reason). Exactly one is None.
    """
    try:
        result = cached_phenix_operation(
            work, "em-real-space-refine", executable="phenix.real_space_refine",
            inputs={"model": model, "map": map_file},
            arguments=[model, map_file, f"resolution={resolution}",
                       "output.prefix=refined", "--overwrite"],
            required_outputs={"model": "refined_real_space_refined_*.cif"},
            timeout=14400,
        )
    except OperationFailed as error:
        return None, refine_failure_reason(error.log_path)
    return result["model"], None


def collect(entries: list[dict], cache: Path,
            record=None) -> tuple[list[dict], list[dict]]:
    """Refine and re-measure each EM entry.

    `record(rows, skipped)` is called after **every** entry, with only that
    entry's result. Without it the caller only learns anything once the whole
    batch finishes -- and round 19's batch ran for about nine hours, so a crash
    at entry 9 of 10 would have left the committed TSV empty and the record for
    eight completed refinements recoverable only by whoever still had the cache.
    That is the failure mode rounds 16-18 spent three rounds closing, and it was
    the last all-or-nothing step in the pipeline.
    """
    rows, skipped = [], []

    def emit(row: dict | None = None, skip: dict | None = None) -> None:
        if record:
            record([row] if row else [], [skip] if skip else [])

    for entry in entries:
        pdb_id, resolution = entry["pdb_id"].lower(), float(entry["resolution"])
        model, map_file = cache / f"{pdb_id}.cif", cache / f"{pdb_id}.map"
        print(f"[{pdb_id.upper()}]", file=sys.stderr)
        if not model.exists() or not map_file.exists():
            skip = {"pdb_id": pdb_id.upper(), "reason": "model or map missing"}
            skipped.append(skip)
            emit(skip=skip)
            continue
        pre = measure(model, map_file, resolution, cache, f"{pdb_id}_pre")
        if pre["cc_mask"] is None:
            reason = failure_reason(pre["cc_log"], "map_correlations")
            print(f"  ! {reason}", file=sys.stderr)
            skip = {"pdb_id": pdb_id.upper(), "reason": reason}
            skipped.append(skip)
            emit(skip=skip)
            continue
        refined, reason = refine(model, map_file, resolution, cache, pdb_id)
        if refined is None:
            print(f"  ! {reason}", file=sys.stderr)
            skip = {"pdb_id": pdb_id.upper(), "reason": reason}
            skipped.append(skip)
            emit(skip=skip)
            continue
        post = measure(refined, map_file, resolution, cache, f"{pdb_id}_post")
        if post["cc_mask"] is None:
            reason = failure_reason(post["cc_log"], "map_correlations (post)")
            print(f"  ! {reason}", file=sys.stderr)
            skip = {"pdb_id": pdb_id.upper(), "reason": reason}
            skipped.append(skip)
            emit(skip=skip)
            continue
        row = {"pdb_id": pdb_id.upper(), "resolution": resolution,
               "cc_mask_pre": pre["cc_mask"], "cc_mask_post": post["cc_mask"],
               "cc_mask_delta": round(post["cc_mask"] - pre["cc_mask"], 4),
               "d_fsc_model_pre": pre["d_fsc_model_masked"],
               "d_fsc_model_post": post["d_fsc_model_masked"],
               "d_fsc_model_reliable": pre["d_fsc_model_plausible"]
                                       and post["d_fsc_model_plausible"]}
        if (pre["d_fsc_model_plausible"] and post["d_fsc_model_plausible"]):
            row["d_fsc_model_delta"] = round(
                post["d_fsc_model_masked"] - pre["d_fsc_model_masked"], 4)
            if pre["d_fsc_model_masked"]:
                row["d_fsc_model_delta_pct"] = round(
                    100.0 * row["d_fsc_model_delta"] / pre["d_fsc_model_masked"], 3)
                # Positive only: how much WORSE the fit got. Improvements report 0.
                row["d_fsc_model_degradation_pct"] = max(0.0, row["d_fsc_model_delta_pct"])
        rows.append(row)
        emit(row=row)
        print(f"  CC_mask {pre['cc_mask']}→{post['cc_mask']} (Δ {row['cc_mask_delta']:+.4f})"
              f" | d_FSC_model {pre['d_fsc_model_masked']}→{post['d_fsc_model_masked']}",
              file=sys.stderr)
    return rows, skipped


def summarize(rows: list[dict]) -> dict[str, Any]:
    """Δ distributions against the asserted bands."""
    if not rows:
        return {"n": 0}

    def stats(key: str) -> dict[str, Any]:
        values = [r[key] for r in rows if r.get(key) is not None]
        if not values:
            return {"n": 0}
        return {"n": len(values), "median": round(statistics.median(values), 4),
                "min": round(min(values), 4), "max": round(max(values), 4)}

    return {
        "n_entries": len(rows),
        "cc_mask_delta": stats("cc_mask_delta"),
        "d_fsc_model_delta": stats("d_fsc_model_delta"),
        "n_d_fsc_model_reliable": sum(1 for r in rows if r.get("d_fsc_model_reliable")),
        # d_FSC_model spans 2.2-6.1 Å across the benchmark set, so the band is
        # relative: an absolute one is simultaneously too tight at the top of that
        # range and too loose at the bottom (round 12).
        "d_fsc_model_relative_pct": stats("d_fsc_model_delta_pct"),
        # d_FSC_model is a resolution: LARGER is worse. The §4 clause is "did not
        # degrade", so the band is one-sided and improvements are unbounded. Measuring
        # it as a two-sided |delta| counts a better fit as a failure (round 13).
        "d_fsc_model_degradation_pct": stats("d_fsc_model_degradation_pct"),
        "asserted_bands": {
            "cc_mask": "post >= pre - 0.04 (d_min < 3.0 A); - 0.06 (d_min >= 3.0 A)",
            "d_fsc_model": "post <= pre * 1.05 (one-sided; improvements unbounded)",
        },
    }


RESULTS_TSV = "ref/research/data/em_refinement_deltas.tsv"

# This benchmark's entry set is the TSV itself, not a hardcoded list. That is the
# stronger form: the file is cumulative, it records the skips alongside the
# measurements, and it carries the round each entry belongs to -- so "which entries did
# this benchmark run on" is answerable per round rather than in aggregate. Declared here
# because `scripts/validate.sh` requires every bench script to commit its set, and a
# list duplicated from the TSV would be one more thing to drift.
SET_RECORD = "ref/research/data/em_refinement_deltas.tsv"
SET_IS_COMPLETE = False   # rounds <=13 are partly unrecoverable; see the LOST rows

# The `status` vocabulary of that file, declared ONCE, here, next to the writer that
# produces it. `check_registry_figures.py` imports this rather than carrying its own
# copy -- one rule, one copy, which is what #136 was about.
#
# Before this existed the vocabulary was implicit in a handful of predicates
# (`startswith("skipped")`, `startswith("screened only")`, `== "measured"`), and 28 of
# the 97 rows matched NONE of them: 23 `delta-only`, 1 `d_FSC only`, 4 `LOST`. No
# published denominator was wrong, because `attempted` is defined by SUBTRACTION --
# `not startswith("skipped")` -- so an unrecognised status silently joins it and
# happens to be right for these rows, which genuinely were attempted.
#
# That is the hazard rather than the bug: the next status added lands in `attempted` by
# default, silently, whether or not it belongs there. Declaring the vocabulary turns
# "unknown status is quietly counted" into "unknown status fails the gate".
# Each entry is (how to match, what it means). The match rule matters: a bare
# `startswith` absorbed anything sharing a prefix with a declared value --
# `measured-partially`, `LOSTISH`, `screened only later` all passed as "known" and then
# joined `attempted` silently, which is the hazard this vocabulary exists to close
# (#148). The statuses are not one shape: `measured` stands alone, and the rest carry a
# payload behind a delimiter, so the delimiter is part of the match.
STATUS_PREFIXES = {
    "measured": ("exact", "refined and re-measured; full pre/post values"),
    "skipped: ": ("prefix", "entered the benchmark, could not be refined; reason follows"),
    "screened only (": ("prefix", "measured pre-refinement for a hypothesis, never "
                                  "refined (round 23); NOT part of the benchmark "
                                  "denominator"),
    "delta-only (": ("prefix", "a Δ is recorded but the per-entry pre/post values were "
                               "never published; counts as attempted"),
    "d_FSC only (": ("prefix", "round 13 published the d_FSC direction but not the "
                               "CC_mask Δ; counts as attempted"),
    "LOST: ": ("prefix", "round 13 measured it and the identity is unrecoverable; "
                         "excluded from the named set by its UNKNOWN pdb_id, not by "
                         "this status"),
}


def status_is_known(status: str) -> bool:
    """Whether a `status` cell matches the declared vocabulary.

    Exact where the status stands alone, prefix-INCLUDING-its-delimiter where it carries
    a payload. `measured-partially` is not `measured`, and treating it as such is how an
    undeclared status reaches a published denominator (#148).
    """
    for token, (rule, _) in STATUS_PREFIXES.items():
        if status == token if rule == "exact" else status.startswith(token):
            return True
    return False


def append_results(rows: list[dict], skipped: list[dict], path: Path,
                   round_label: str = "") -> None:
    """Append this run's per-entry values to a committed, cumulative TSV.

    Round 16 found that round 13's entry IDs do not exist anywhere in the repo. Its
    write-up names 9O9K and 9H7U and reports the branch minimum; the other four
    entries it measured are unrecoverable, because results were only ever written to a
    JSON in a temporary cache. That makes the CC_mask degradation count permanently a
    range (14-19) rather than a number -- and the count is the evidence measure for a
    one-sided band, so an unrecoverable identity is an unrecoverable piece of
    evidence.

    Prose in an audit trail is not a record: it names the entries an author found
    interesting, which is exactly the subset that cannot be used to recount anything.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    header = ("pdb_id\tround\tresolution\tcc_mask_pre\tcc_mask_post\tcc_mask_delta\t"
              "d_fsc_model_pre\td_fsc_model_post\td_fsc_model_delta_pct\tstatus\n")
    existing = path.read_text() if path.exists() else ""
    seen = {line.split("\t")[0]: line.split("\t")
            for line in existing.splitlines()[1:] if line.strip()}
    lines = [] if existing else [header]
    superseded: list[tuple[str, list[str], list[str]]] = []

    def offer(cells: list[str]) -> None:
        """Write a row, or record that an existing row would have been overwritten.

        Dedup is by `pdb_id` and the drop used to be silent, which is right for the
        idempotent re-offer this file's incremental writer depends on and wrong for
        everything else: a corrected measurement, or one of the 10 `skipped:` entries
        succeeding on a later attempt, was discarded without a word and the stale row
        stood as the benchmark's record (#120).

        So identical re-offers stay silent and a row whose VALUES differ is announced.
        Writing it is still not automatic -- this is a cumulative, hand-auditable
        record and silently rewriting history is the worse failure -- but the operator
        now learns that a decision is needed instead of learning nothing.
        """
        prior = seen.get(cells[0])
        if prior is None:
            lines.append("\t".join(cells) + "\n")
            return
        # Compare everything but the round label: a re-measurement in a later round is
        # a change of round, not of value, and only the values matter here.
        if prior[:1] + prior[2:] != cells[:1] + cells[2:]:
            superseded.append((cells[0], prior, cells))

    for r in rows:
        offer([str(x) for x in [
            r["pdb_id"], round_label, r["resolution"], r["cc_mask_pre"],
            r["cc_mask_post"], r["cc_mask_delta"], r.get("d_fsc_model_pre"),
            r.get("d_fsc_model_post"), r.get("d_fsc_model_delta_pct"),
            "measured"]])
    for s in skipped:
        offer([s["pdb_id"], round_label, "", "", "", "", "", "", "",
               f"skipped: {s['reason']}"])
    if lines:
        with path.open("a") as fh:
            fh.writelines(lines)
    _report_superseded(superseded, path)


def _report_superseded(superseded: list[tuple[str, list[str], list[str]]],
                       path: Path) -> None:
    """Say loudly which new rows were dropped because the id was already on file."""
    if not superseded:
        return
    print(f"\n!! {len(superseded)} row(s) NOT written to {path}: the id is already on "
          f"file with DIFFERENT values. Nothing was overwritten — decide per entry and "
          f"edit the file by hand if the new measurement should stand.", file=sys.stderr)
    for pdb_id, prior, new in superseded:
        print(f"   {pdb_id}\n     on file: {'  '.join(prior[2:])}"
              f"\n     new:     {'  '.join(new[2:])}", file=sys.stderr)


def main() -> int:
    from benchmark_environment import announce_benchmark_environment

    announce_benchmark_environment()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--entries", help="JSON: [{pdb_id, resolution}, ...]; default <cache>/entries.json")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--results-tsv", default=RESULTS_TSV,
                    help="cumulative per-entry record, appended to and committed; "
                         "empty string disables")
    ap.add_argument("--round", default="",
                    help="round label written to the TSV's `round` column. Without it "
                         "a later cross-round analysis has to reconstruct which round "
                         "measured what by matching prose against row order")
    args = ap.parse_args()

    cache = Path(args.cache)
    entries_path = Path(args.entries) if args.entries else cache / "entries.json"
    entries = json.loads(entries_path.read_text())

    tsv = Path(args.results_tsv) if args.results_tsv else None
    # Append as each entry finishes rather than after the batch. The final call
    # below is retained as a no-op safety net -- append_results dedups by id, so
    # re-offering rows already written changes nothing.
    record = ((lambda r, s: append_results(r, s, tsv, args.round)) if tsv else None)
    rows, skipped = collect(entries, cache, record=record)
    if tsv:
        append_results(rows, skipped, tsv, args.round)
    summary = summarize(rows)
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps({"rows": rows, "skipped": skipped, "summary": summary}, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
