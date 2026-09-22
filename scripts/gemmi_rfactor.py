#!/usr/bin/env python3
"""Independent R-work / R-free from two MTZs using gemmi + numpy — no cctbx (#296).

The T06 oracle of record is `phenix.model_vs_data`; this is the non-cctbx code path
`ref/quality_reporting.md` names for the cross-check ("scripts/gemmi_rfactor.py or
its successor" — this is the successor). The negative-control benchmark's headroom
screen (phase 2 of #295) requires it: enrollment demands that two independent code
paths agree there is no headroom, and both being cctbx would be the trust-model
violation the harness exists to prevent.

What it does: reads Fobs (+ sigma + free flags) from one MTZ and Fcalc from another
(produced by `gemmi sfcalc`, which applies its own bulk-solvent + scaling), joins on
hkl, applies a bin-wise isotropic rescale, and reports R-work / R-free.

Assumptions (`ref/tool_assumptions.yaml`): upstream `gemmi sfcalc --scale-to`
uses flat-mask bulk solvent with global anisotropic/solvent scaling; this script
then adds work-fitted bin-wise isotropic rescaling in linear reflection-count
bins. For matched model, MTZ, work set and cctbx mask radii, only the signed
gemmi-minus-PHENIX values are descriptive: the §3 envelope benchmarked direct
summation of globally scaled `gemmi sfcalc` FC values, not this script's extra
bin-wise rescaling. This script's R-work and R-free offsets are informational
pending estimator-matched benchmarks, and values from the tools must not be averaged.

Scale fitting is WORK-ONLY (#316, superseding #304's accept-and-document): the
per-bin scales are fit on work reflections and applied unchanged to the free
set, so no information from the test set reaches the reported R-free. The
eval-artifact original (and this script before #316) fit on all reflections —
mild leakage the 2026-08-12 Codex review correctly flagged as undermining the
held-out independence this path exists to provide. #304's condition was honored
in the same change: the cross-fit offset was re-measured on the four cached
round-1/2 pairs (5SY4 and 9YGW, pre and post models) — work-only minus all-fit
R-free was +0.00001, +0.00001, -0.00000, +0.00000, i.e. <= 1e-5. With a ~5 %
free set and 20 bins the leakage was principled, not practically large; the
recorded 1SAR R-work and R-free measurements are unaffected at their stated
precision, and no prior round's delta moves at 4-decimal reporting. Only the
directly summed R-work offset is gradeable under registry §3; this script's
bin-rescaled R-work and R-free offsets remain informational pending an
estimator-matched R-work benchmark and a test-set-specific R-free benchmark.

WHAT THE PROMOTION FIXED (vs data/coscientists/openscientist/gemmi_rfactor.py)
------------------------------------------------------------------------------
The eval-artifact original hardcoded `free = (flag != 0)`. That is correct for a
PHENIX-style 0/1 column where 1 marks the test set, and silently SWAPS work and
free for a CCP4-style `FreeR_flag` column, where flags run 0-19 and the free set is
`flag == 0` (~5 %): there, `flag != 0` calls 95 % of reflections free. The two
conventions cannot be told apart by column values alone in every case, so the flag
convention is inferred conservatively and every inference is printed; `--free-value`
overrides. A free fraction outside 0.1-30 % is refused, loudly, whether inferred or
given (#302).

Usage:
    python3 scripts/gemmi_rfactor.py obs.mtz calc.mtz
    python3 scripts/gemmi_rfactor.py obs.mtz calc.mtz --obs-columns FP,SIGFP --free-value 0
    python3 scripts/gemmi_rfactor.py obs.mtz calc.mtz --json out.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

# Column-label fallbacks, tried in order. First hit wins and is reported.
OBS_CANDIDATES = (("F-obs", "SIGF-obs"), ("FP", "SIGFP"), ("FOBS", "SIGFOBS"),
                  ("F", "SIGF"))
CALC_CANDIDATES = ("FC", "F-calc", "FCALC")
FREE_CANDIDATES = ("R-free-flags", "FreeR_flag", "FREE", "FreeRflag")

# A free set outside this fraction band means the flag convention was misread, and
# an R-free computed on it would be confidently wrong. Refuse instead. The floor is
# 0.1 %, not 1 %: large high-resolution datasets commonly cap the test set at
# ~1000-2000 reflections, well under 1 % of the total, while a swapped convention
# lands at ~70-99 % and is caught by the ceiling (#302).
FREE_FRACTION_BAND = (0.001, 0.30)


def hkl_key(hkl: np.ndarray) -> np.ndarray:
    """Pack h,k,l into one int64 key for joining. 16 bits for k and l matches the
    original; |index| >= 32768 would collide, far beyond any real dataset."""
    h = hkl[:, 0].astype(np.int64)
    k = hkl[:, 1].astype(np.int64) & 0xFFFF
    l = hkl[:, 2].astype(np.int64) & 0xFFFF
    return (h << 32) | (k << 16) | l


def join_on_hkl(hkl_obs: np.ndarray, hkl_calc: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Indices (into obs, into calc) of reflections present in both files."""
    key_o, key_c = hkl_key(hkl_obs), hkl_key(hkl_calc)
    order = np.argsort(key_c)
    pos = np.searchsorted(key_c[order], key_o)
    pos_clipped = np.minimum(pos, len(order) - 1)
    matched = key_c[order][pos_clipped] == key_o
    return np.nonzero(matched)[0], order[pos_clipped[matched]]


def infer_free_value(flags: np.ndarray) -> int:
    """Which flag value marks the free (test) set.

    Two live conventions: PHENIX-style 0/1 with 1 = free (the minority), and
    CCP4-style 0..N with 0 = free. Decided conservatively:

      - exactly two distinct values -> the minority value is free (covers 0/1
        either way round)
      - three or more distinct values -> CCP4 convention, free = 0

    Anything else (one value, or a "minority" that is not a minority) is refused —
    the caller must pass --free-value. Silence is the failure mode being avoided:
    a swapped convention yields a plausible-looking, wrong R-free.
    """
    values, counts = np.unique(flags, return_counts=True)
    if len(values) == 2:
        return int(values[np.argmin(counts)])
    if len(values) > 2:
        if 0 not in values:
            raise SystemExit("gemmi_rfactor: multi-valued free-flag column with no 0; "
                             "pass --free-value explicitly")
        return 0
    raise SystemExit(f"gemmi_rfactor: free-flag column has a single value "
                     f"({values[0]}); pass --free-value explicitly")


def binwise_scale(fobs: np.ndarray, fcalc: np.ndarray, s2: np.ndarray,
                  nbins: int = 20, fit_mask: np.ndarray | None = None) -> np.ndarray:
    """Least-squares scale per equal-count resolution bin, applied to Fcalc.

    Removes residual resolution-dependent drift the upstream sfcalc scaling left
    behind. Equal-count (not equal-width) bins, matching the original and differing
    from PHENIX's adaptive shells by design — see the module docstring.

    `fit_mask` selects the reflections the scales are FIT on (the work set, per
    #316); the fit is applied to every reflection in the bin. A bin whose
    fit-selection is empty falls back to the global fit-selection scale rather
    than to a leaky all-reflection fit. None fits on everything (the pre-#316
    behavior, kept for measuring the offset, never for reporting).
    """
    if fit_mask is None:
        fit_mask = np.ones_like(fobs, dtype=bool)
    if not fit_mask.any():
        # Unreachable via compute() (the free-fraction band guarantees a work
        # majority) but importable: an empty fit selection would silently
        # scale everything to zero.
        raise SystemExit("gemmi_rfactor: empty fit selection for the scale fit")
    global_s = (fobs[fit_mask] * fcalc[fit_mask]).sum() / \
        max((fcalc[fit_mask] ** 2).sum(), 1e-12)
    scale = np.ones_like(fcalc)
    order = np.argsort(s2)
    for ix in np.array_split(order, nbins):
        if len(ix) == 0:
            continue
        fit_ix = ix[fit_mask[ix]]
        if len(fit_ix) == 0:
            scale[ix] = global_s
            continue
        s = (fobs[fit_ix] * fcalc[fit_ix]).sum() / \
            max((fcalc[fit_ix] ** 2).sum(), 1e-12)
        scale[ix] = s
    return fcalc * scale


def r_factor(fobs: np.ndarray, fcalc: np.ndarray, mask: np.ndarray) -> float:
    o, c = fobs[mask], fcalc[mask]
    denom = np.abs(o).sum()
    if denom == 0:
        raise SystemExit("gemmi_rfactor: empty or zero-amplitude selection")
    return float(np.abs(o - c).sum() / denom)


def pick_columns(labels: list[str], candidates, what: str):
    for cand in candidates:
        want = (cand,) if isinstance(cand, str) else cand
        if all(w in labels for w in want):
            return want if len(want) > 1 else want[0]
    raise SystemExit(f"gemmi_rfactor: no {what} column among {labels}; "
                     f"tried {candidates}")


def compute(obs_path: str, calc_path: str, obs_columns: str | None,
            calc_column: str | None, free_column: str | None,
            free_value: int | None, nbins: int) -> dict:
    import gemmi  # deferred so the unit tests need no gemmi import to test the math

    mtz_o = gemmi.read_mtz_file(obs_path)
    mtz_c = gemmi.read_mtz_file(calc_path)
    arr_o = np.array(mtz_o, copy=False)
    arr_c = np.array(mtz_c, copy=False)
    cols_o = {c.label: arr_o[:, i] for i, c in enumerate(mtz_o.columns)}
    cols_c = {c.label: arr_c[:, i] for i, c in enumerate(mtz_c.columns)}

    if obs_columns:
        f_label, sig_label = [c.strip() for c in obs_columns.split(",")]
    else:
        f_label, sig_label = pick_columns(list(cols_o), OBS_CANDIDATES, "Fobs")
    fc_label = calc_column or pick_columns(list(cols_c), CALC_CANDIDATES, "Fcalc")
    fr_label = free_column or pick_columns(list(cols_o), FREE_CANDIDATES, "free-flag")
    for label in (f_label, sig_label, fr_label):
        if label not in cols_o:
            raise SystemExit(f"gemmi_rfactor: column {label!r} not in {obs_path}")
    if fc_label not in cols_c:
        raise SystemExit(f"gemmi_rfactor: column {fc_label!r} not in {calc_path}")

    hkl_o = np.column_stack([cols_o["H"], cols_o["K"], cols_o["L"]]).astype(int)
    hkl_c = np.column_stack([cols_c["H"], cols_c["K"], cols_c["L"]]).astype(int)
    io, ic = join_on_hkl(hkl_o, hkl_c)

    fobs, sig = cols_o[f_label][io], cols_o[sig_label][io]
    flags = cols_o[fr_label][io]
    fcalc = cols_c[fc_label][ic]
    hkl = hkl_o[io]

    ok = np.isfinite(fobs) & np.isfinite(fcalc) & np.isfinite(sig) & (sig > 0) \
        & np.isfinite(flags)
    fobs, fcalc, flags, hkl = fobs[ok], fcalc[ok], flags[ok].astype(int), hkl[ok]
    if len(fobs) == 0:
        raise SystemExit("gemmi_rfactor: zero usable reflections after the join")

    inferred = free_value if free_value is not None else infer_free_value(flags)
    free_mask = flags == inferred
    work_mask = ~free_mask
    fraction = free_mask.mean()
    if not (FREE_FRACTION_BAND[0] <= fraction <= FREE_FRACTION_BAND[1]):
        # Refused under an explicit --free-value too — an asserted-but-wrong value
        # must not produce a plausible-looking wrong R-free — but the message must
        # not send the caller in a circle (#302).
        hint = ("the flag convention was misread; pass --free-value"
                if free_value is None else
                "that cannot be a test set; check the flag column and value")
        origin = "inferred" if free_value is None else "given"
        raise SystemExit(
            f"gemmi_rfactor: free set is {fraction:.1%} of reflections ({origin} "
            f"free value {inferred}) — outside {FREE_FRACTION_BAND}; {hint}")

    cell = mtz_o.cell
    s2 = np.array([cell.calculate_1_d2((int(h), int(k), int(l))) for h, k, l in hkl])
    # Scales fit on WORK only, applied to all (#316): the free set is held out
    # of every fitted parameter this script owns.
    fcalc_s = binwise_scale(fobs, fcalc, s2, nbins, fit_mask=work_mask)

    r_work = r_factor(fobs, fcalc_s, work_mask)
    r_free = r_factor(fobs, fcalc_s, free_mask)
    return {"n_matched": int(len(fobs)), "n_work": int(work_mask.sum()),
            "n_free": int(free_mask.sum()), "free_value": int(inferred),
            "free_value_inferred": free_value is None,
            "obs_columns": [f_label, sig_label], "calc_column": fc_label,
            "free_column": fr_label, "nbins": nbins,
            "r_work": round(r_work, 4), "r_free": round(r_free, 4),
            "r_free_gap": round(r_free - r_work, 4)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("obs_mtz")
    ap.add_argument("calc_mtz", help="from `gemmi sfcalc` (carries FC)")
    ap.add_argument("--obs-columns", help="F,SIGF labels (default: autodetect)")
    ap.add_argument("--calc-column", help="Fcalc label (default: autodetect)")
    ap.add_argument("--free-column", help="free-flag label (default: autodetect)")
    ap.add_argument("--free-value", type=int,
                    help="flag value marking the FREE set (default: infer, printed)")
    ap.add_argument("--nbins", type=int, default=20)
    ap.add_argument("--json", dest="json_out")
    args = ap.parse_args()

    result = compute(args.obs_mtz, args.calc_mtz, args.obs_columns,
                     args.calc_column, args.free_column, args.free_value,
                     args.nbins)
    origin = "inferred" if result["free_value_inferred"] else "given"
    print(f"matched reflections: {result['n_matched']}")
    print(f"  work: {result['n_work']}, free: {result['n_free']} "
          f"(free value {result['free_value']}, {origin})")
    print(f"R-work (gemmi)  = {result['r_work']:.4f}")
    print(f"R-free (gemmi)  = {result['r_free']:.4f}")
    print(f"R-free gap      = {result['r_free_gap']:.4f}")
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(result, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
