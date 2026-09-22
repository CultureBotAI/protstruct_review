# Tolerance benchmark — independent-code-path R-work offset (gemmi sfcalc vs phenix.model_vs_data)

Settles the R-work tolerance in `ref/thresholds_and_standards.md` whose row admitted its own
magnitude was **unbenchmarked**: "an independent R re-derivation may differ *by a small amount* from
scaling / resolution-binning differences (magnitude **unbenchmarked**)". Every value in this
benchmark is summed over the **work set**; it does not establish an R-free offset band.

Reproduce with:

```bash
python3 scripts/bench_t06_r_offset.py --ids-file <ids.json> --cache <dir> --json <out.json>
```

## Configuration

Both paths start from the same deposited model and the same MTZ:

| | phenix.model_vs_data | gemmi sfcalc |
|---|---|---|
| Fcalc | cctbx FFT, flat-mask bulk solvent | gemmi FFT, flat-mask bulk solvent |
| Scaling | **per-resolution-bin** k_iso / k_aniso / k_mask | **global** k_overall + one anisotropic B, global k_sol / B_sol |
| Mask radii | cctbx set | `--radii-set=cctbx` (matched); gemmi's own default is `vdw` |
| R reported by | the program | summed here: R = Σ‖F_obs‖−‖F_calc‖ / Σ‖F_obs‖ over the work set |

The R summation is done outside both programs on purpose: it is three lines of arithmetic, and
keeping it out means the comparison is between two **Fcalc computations**, not two reporting
conventions. gemmi is *not* a simplified code path — it applies the same flat-mask bulk-solvent and
anisotropic scaling model — so a large offset would indicate a configuration problem, not a
"sophisticated vs simple" difference.

Test set: 15 X-ray entries, 1.20–2.92 Å, R_work 0.127–0.255, work sets of 4.8 k–155 k reflections,
drawn resolution-stratified from RCSB and filtered to entries that deposited **amplitudes** with a
free-flag column.

### Three traps, each worth more than the effect being measured

- **Free-flag convention.** Getting it backwards computes R-free and calls it R-work — worth about
  **+0.06** in R, four times the offset being measured. Two conventions occur and both appear in
  this test set: two-valued flags (the minority value marks the test set) and CCP4/REFMAC
  multi-bin flags (10–20 near-equal bins, where bin **0** is the test set). `free_test_value()`
  handles both and returns None rather than guess. Verified against PHENIX's own free count on 11MQ
  (518 reflections with flag 0; PHENIX reported Nfree = 517) and on 12LO (n_work 11025, matching
  PHENIX exactly).
- **Converter choice.** CCP4's `cif2mtz` re-settings the space group for some entries — 11AF's
  deposited `CRYST1` says P 2 21 21, CCP4 writes P 21 21 2 — and `phenix.model_vs_data` then aborts
  on a symmetry mismatch. `gemmi cif2mtz` preserves the deposited setting. The MTZ is also stripped
  to H K L + amplitudes + free flags, because depositions carrying FC/PHIC make model_vs_data abort
  with "Multiple equally suitable arrays of observed xray data found".
- **Which PHENIX number.** `model_vs_data` emits two result blocks — the first over the data as
  given, the second re-run inside the resolution limits in the model header. On 28JJ these differ by
  0.019 in R (0.2424 over 64.79–2.10 Å vs 0.2231 over 64.79–2.30 Å), which is the entire width of
  the tolerance, and the second block reports the 26047 excluded reflections as "F-obs outliers".
  The **first** block is used, matched by the `d_min` the gemmi side is run at.

## Results

| Entry | d_min (Å) | N_work | PHENIX R_work | gemmi R_work | Δ | mask-convention effect |
|---|---:|---:|---:|---:|---:|---:|
| 29QD | 1.20 | 154664 | 0.1266 | 0.1318 | +0.0052 | +0.0022 |
| 12LO | 1.37 | 11025 | 0.1740 | 0.1786 | +0.0046 | +0.0020 |
| 29OL | 1.44 | 19111 | 0.1886 | 0.1955 | +0.0069 | +0.0040 |
| 29OH | 1.54 | 14315 | 0.2154 | 0.2183 | +0.0029 | +0.0028 |
| 30TW | 1.70 | 60983 | 0.1753 | 0.1815 | +0.0062 | +0.0030 |
| 9LK0 | 1.78 | 43719 | 0.2075 | 0.2164 | +0.0089 | +0.0027 |
| 37AP | 1.82 | 22008 | 0.1622 | 0.1695 | +0.0073 | +0.0065 |
| 36TD | 2.00 | 50074 | 0.2000 | 0.2073 | +0.0073 | +0.0040 |
| 30IZ | 2.02 | 49379 | 0.1897 | 0.1971 | +0.0074 | +0.0055 |
| 28JJ | 2.10 | 104918 | 0.2424 | 0.2462 | +0.0038 | +0.0105 |
| 11MQ | 2.38 | 4804 | 0.2331 | 0.2482 | +0.0151 | +0.0140 |
| 24MR | 2.47 | 45315 | 0.2230 | 0.2278 | +0.0048 | +0.0049 |
| 28SX | 2.59 | 10166 | 0.2549 | 0.2636 | +0.0087 | +0.0057 |
| 11AF | 2.60 | 11264 | 0.2386 | 0.2452 | +0.0066 | +0.0043 |
| 28SW | 2.92 | 6496 | 0.2440 | 0.2556 | +0.0116 | +0.0043 |

|Δ|: **median 0.0069, p90 0.0116, max 0.0151**. Signed: gemmi reads higher in **15 of 15**.

## Findings

**1. "A small amount" is now a number: ~0.007 typical, up to 0.015.** In R-factor terms that is
0.7 percentage points typically and 1.5 at worst — on models whose R_work spans 0.13–0.25, i.e. an
offset of 3–6 % of the value being checked. Large enough that an agent's R re-derivation landing
0.01 from PHENIX is *expected*, not evidence of a modelling error.

**2. The observed offset is one-sided; the criterion is not.** gemmi is higher in 15/15, with no
sign changes. PHENIX refits k_iso, k_aniso and k_mask per resolution bin, while `gemmi sfcalc`
applies one global scale and one anisotropic tensor, but the paths also differ in Fcalc
implementation, objective details and outlier rejection. The sample therefore establishes a useful
sign diagnostic, not a mathematical guarantee. A non-positive offset merits configuration review;
it does not fail an otherwise close absolute agreement by itself. Neither R is "the true R".

**3. Mask convention is worth as much as the code difference.** Running gemmi with its own default
`vdw` radii instead of `--radii-set=cctbx` adds a **median +0.0043 and up to +0.014** — comparable
to the entire offset. Any comparison that does not match the mask radii is measuring configuration,
not implementation.

**4. No clean resolution trend.** Median |Δ| runs 0.0057 (< 1.8 Å), 0.0073 (1.8–2.5 Å), 0.0087
(≥ 2.5 Å) — mildly increasing, but the worst case (11MQ, 0.0151) is mid-resolution and coincides
with the largest mask effect, so the driver looks like solvent content rather than resolution.

## Applied tolerance

> Define ΔR_work = R_work(gemmi) − R_work(PHENIX). Require **|ΔR_work| ≤ 0.02** for directly summed
> `gemmi sfcalc --radii-set=cctbx` FC values vs `phenix.model_vs_data`, on the same model, the same
> MTZ and the same work set. gemmi at or below PHENIX is off the observed 15-entry distribution and
> triggers investigation, not automatic failure. Matching the mask radii set is a **precondition**,
> not a refinement.

The tightest envelope covering all 15 is 0.016; rounded to 0.02 for margin at n = 15. This replaces
an unquantified "small amount", and it is deliberately not tighter: the two programs differ in
scaling freedom by design.

## Scope limits

- Deposited models scored against their own data. This bounds **tool-vs-tool** disagreement, not how
  much R moves when a model changes.
- Amplitude depositions only; entries depositing intensities are skipped rather than converted,
  since the conversion would add a code path under test.
- `gemmi sfcalc` offers no per-bin scaling, so the offset cannot be reduced by configuring gemmi
  differently — it is structural to the comparison.
- **Outlier rejection is asymmetric.** PHENIX excludes its own F-obs outliers from `r_work` (3–31
  reflections per entry in the first block); the gemmi-side sum here rejects nothing. At worst that
  is 31/10166 ≈ 0.3 % of reflections, and the affected entries are not the ones with the largest
  offsets, but it is part of the measured offset. Reproducing PHENIX's rejection criterion on the
  gemmi side was rejected as a fix: it would import the code path under test.
- One version pair: PHENIX 2.0-5936 and gemmi 0.7.5.
- **R-work only.** No R-free values entered the tolerance calculation. Applying this envelope to
  R-free would be an unbenchmarked extrapolation; an R-free offset remains informational until a
  test-set-specific benchmark is run.
- **Estimator-specific.** The benchmark directly summed the globally scaled FC values emitted by
  `gemmi sfcalc`. It does not govern `scripts/gemmi_rfactor.py`, which adds work-fitted bin-wise
  isotropic rescaling; that estimator needs its own benchmark before receiving a verdict.
