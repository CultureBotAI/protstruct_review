# Tolerance benchmark — clashscore and H-placement (cctbx vs Richardson standalone)

Settles two `[template]` tolerances in `ref/thresholds_and_standards.md` that shared a tool pair and
rested on a **single** in-repo observation (1SAR: 3.13 cctbx vs 3.63 standalone):

- Clashscore ± 1.0
- H-placement: H-atom count within ± 2 %, same Asn/Gln/His flip set, clashscore delta within ± 1.0

Reproduce with:

```bash
python3 scripts/bench_t05_clashscore_h.py --ids-file <ids.json> --cache <dir> --json <out.json>
```

## Configuration

Both paths are the same pipeline — build hydrogens, count serious overlaps — in different
implementations:

- **cctbx**: `phenix.clashscore model.pdb` (hydrogens built internally).
- **standalone**: Richardson `reduce -build`, then `probe -u -q -mc -het -once`, with the score
  summed here by the MolProbity definition: serious clashes (overlap ≥ 0.4 Å) per 1000 atoms,
  counting each atom pair once. Validated against `phenix.clashscore` on 1SAR (32.25 vs 32.59).

Standalone `reduce` is run **twice**, `-build` (electron-cloud-center H) and `-build -nuclear`
(nuclear H), because the H-build convention is the suspected dominant term and the only way to
measure it is to vary it. cctbx defaults to electron-cloud placement for X-ray models, so
`-build` is the matched configuration and `-nuclear` is the mismatched one.

Test set: 10 deposited X-ray models with no deposited hydrogens, clashscore 1.18–13.61. Models that
already carry H are skipped — they would test neither H-builder.

## Results

| Entry | cctbx | standalone (electron-cloud) | standalone (nuclear) | Δ matched | Δ mismatched | H count (ec/nuc) |
|---|---:|---:|---:|---:|---:|---|
| 24MR | 13.61 | 11.34 | 28.54 | −2.27 | +14.93 | 8327 / 8328 |
| 37AS | 3.68 | 3.30 | 14.48 | −0.38 | +10.80 | 3486 / 3486 |
| 37AP | 2.49 | 2.26 | 11.59 | −0.23 | +9.10 | 1770 / 1770 |
| 11AF | 6.65 | 6.46 | 15.45 | −0.19 | +8.80 | 2529 / 2529 |
| 28SZ | 9.64 | 9.50 | 32.61 | −0.14 | +22.97 | 2367 / 2367 |
| 37BG | 3.40 | 3.31 | 11.96 | −0.09 | +8.56 | 7999 / 8000 |
| 12LO | 1.18 | 1.18 | 7.09 | +0.00 | +5.91 | 412 / 412 |
| 30IZ | 1.83 | 1.83 | 15.13 | +0.00 | +13.30 | 9727 / 9728 |
| 9LLR | 1.94 | 1.94 | 8.13 | −0.00 | +6.19 | 1226 / 1226 |
| 9PN7 | 6.65 | 6.65 | 27.95 | +0.00 | +21.30 | 9784 / 9784 |

| | median \|Δ\| | p90 | max |
|---|---:|---:|---:|
| Clashscore, **matched** H convention | 0.115 | 0.38 | 2.27 |
| Clashscore, **mismatched** H convention | 9.95 | 21.3 | 22.97 |
| H-atom count difference (%) | 0.000 | 0.012 | 0.013 |

## Findings

**1. The H-build convention is not a caveat, it is the entire signal.** Matched, the two
implementations agree to a median of 0.115 clashscore units. Mismatched, they disagree by a median
of **9.95** and up to **22.97** — 10 to 23 times the ±1.0 tolerance. The earlier in-repo 1SAR
observation (Δ ≈ 0.5) understated this by more than an order of magnitude, because it happened to
compare two electron-cloud builds. Nuclear H sit further from their parent atoms, so every H-bearing
contact tightens and the clash count roughly triples.

**2. ±1.0 is right for the matched case but needs a relative term.** Nine of ten pairs agree within
0.4. The exception, 24MR (Δ 2.27), is the highest-clashscore model in the set at 13.61 — the
disagreement is 17 % of the value. A clashscore of 30 compared to a tolerance of ±1.0 is a 3 %
demand; that is tighter than these implementations support.

**3. The H-count tolerance is ~150× too loose, and it checks the wrong thing.** Observed H-count
differences are **0.013 % at worst** against an allowed 2 %. **Correction:** this compares one
builder in two conventions, not the two builders the tolerance names — see
`tolerance_benchmark_flip_sets.md`, where the correct pair diverges by up to 3.96 % on
ligand-bearing models because the two distributions ship different het dictionaries. The
observation below still holds for the convention question; it is the wrong basis for the tolerance. The count is essentially always
identical because both builders place the same *number* of hydrogens on the same residues — what
differs is *where* they put them. A ±2 % H-count check therefore passes even when the two models
have systematically different H positions, giving false assurance. The clashscore delta is the check
that actually sees the difference.

## Applied tolerances

> **Clashscore: |Δ| ≤ 1.0, or 20 % of the mean, whichever is larger** — cctbx vs Richardson
> standalone, **with a matched H-build convention**. Under a mismatched convention (nuclear vs
> electron-cloud) expect 6–23 units of disagreement; that comparison is void, not failed.
>
> **H-placement: superseded** by `tolerance_benchmark_flip_sets.md` — the ± 0.1 % below was measured
> on one builder in two conventions. The two builders the tolerance names agree **exactly** on
> protein-only models and diverge up to 3.96 % when hetero components are present. **H-count agreement does not imply
> H-position agreement** — it is nearly insensitive to the convention that dominates the score, so
> it must not be reported as evidence that two H builds match.

The relative term covers 10/10 (24MR needs 17 %); the 1.0 floor keeps low-clashscore models from
being held to an unreasonably tight absolute band.

## Scope limits

- 10 models, clashscore 1.18–13.61. Severely clashing models (≳ 40, the registry's "anomalous"
  band) are not represented; the 20 % relative term is an extrapolation there.
- The Asn/Gln/His **flip set** part of the H-placement tolerance is not measured here — only H count
  and the resulting clashscore. It was measured separately in `tolerance_benchmark_flip_sets.md`,
  using `reduce`'s own `USER  MOD` records: 0 disagreements over 634 residues, because
  `phenix.reduce` **is** the standalone Richardson binary (identical version strings).
- That identity also **re-attributes the matched-convention residual measured above**. Since both
  paths build hydrogens with the same binary, the median 0.115 clashscore difference cannot come from
  H placement; it comes from the clash-counting step (`phenix.clashscore`'s internal analysis vs the
  `probe` summation here). The mismatched-convention result (median 9.95) is unaffected — that
  comparison deliberately changes the H geometry.

> **Correction (2026-09-26, #763/#776/#793/#794; the attribution was withdrawn in #728).** The
> re-attribution in the bullet above is withdrawn. Sharing the `reduce` release does not make the two
> paths score the same hydrogens, or even the same side-chain orientations. In PHENIX 2.0-5936,
> `phenix.clashscore` defaults to `do_flips=False`: it trims, then runs `molprobity.reduce` — PHENIX's
> build with PHENIX's het dictionary (`-DB … -ALLALT`) — with `-oh -his -flip -keep -allalt -limit120
> -pen9999`, and the 9999 penalty in effect disables Asn/Gln/His flips (`mmtbx/programs/clashscore.py`,
> `mmtbx/validation/clashscore.py`). This benchmark ran the standalone build as `reduce -build`
> (`-build` is the same as `-FLIP`), with its own dictionary, before `probe`. The two distributions'
> het dictionaries are known to differ (`tolerance_benchmark_flip_sets.md` findings 1 and 4), and five
> of the ten models here — 24MR, 37AP, 37AS, 37BG, 28SZ — are ligand-bearing models whose H counts
> diverge between them; 24MR, which sets the 2.27 maximum, also carries 49 of the 56 flips in that
> record. The H coordinates themselves were not compared. So the matched-convention residual (median
> 0.115) cannot be assigned to the clash-counting step: it mixes flip policy, dictionary-driven H
> construction and counting in unknown proportions (`ASSUM_molprobity_h_atom_placement_2026_09_23`
> in `ref/tool_assumptions.yaml`). The tolerance itself is unaffected: it bounds the benchmarked
> pipeline, differences included, and the registry states its precondition as the same `reduce`
> release under a matched convention.

- Standalone clashscore is summed by this script from probe output rather than by MolProbity's own
  `clashscore` wrapper (not installed); it was validated against `phenix.clashscore` on 1SAR to
  within 0.34 units.
- One version pair: PHENIX 2.0-5936, reduce 4.16.250520, probe 2.26.021123.
