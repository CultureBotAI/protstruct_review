# Tolerance benchmark — bond-length RMSD (phenix.model_statistics vs gemmi rmsz)

Settles the `Bond-length RMSD | ± 0.003 Å` `[template]` tolerance in
`ref/thresholds_and_standards.md`. The domain-expert review made bond **angle** RMSD
library-conditional — PHENIX's conformation-dependent library (CDL) vs the CCP4 monomer library
shifts angles by 0.3–0.4° for library reasons alone — but left bond **length** untested against the
same library difference. This is that test.

Reproduce with:

```bash
python3 scripts/bench_t05_bond_rmsd.py --ids-file <ids.json> --cache <dir> --json <out.json>
```

## Configuration

| | phenix.model_statistics | gemmi rmsz |
|---|---|---|
| Restraint library | PHENIX default (CDL since ~2016) | CCP4 monomer library (`$CLIBD_MON`, Engh & Huber lineage — the library REFMAC uses) |
| Reported line | `covalent geometry : bond <rmsd> (<n>)` | `Model rmsD: bond: <rmsd>` |

**Recipe correction:** `ref/oracle_tools.md` cited `gemmi validate` for this comparison. There is no
such gemmi subcommand — the geometry validator is **`gemmi rmsz`**, and it prints rmsZ (unitless
Z-scores) *and* rmsD (Å) on separate lines. Only the **rmsD** line is comparable to PHENIX's RMSD;
comparing PHENIX's Å figure against gemmi's Z-score line would be a units error, not a disagreement.

PHENIX's `covalent geometry : bond` figure is used rather than its headline `Bond:` line, because
the headline includes SS-bond and link restraints while the covalent-geometry figure matches the
bond population gemmi counts.

Test set: 17 deposited X-ray models, bond RMSD 0.0018–0.0175 Å, 440–9634 restrained bonds.

## Results

| Entry | PHENIX rmsD (Å) | n bonds | gemmi rmsD (Å) | n bonds | Δ (Å) | same count |
|---|---:|---:|---:|---:|---:|---|
| 30TW | 0.0143 | 4677 | 0.0810 | 9544 | +0.0667 | no |
| 9PLB | 0.0095 | 624 | 0.0240 | 977 | +0.0145 | no |
| 28SX | 0.0035 | 2330 | 0.0170 | 4769 | +0.0135 | no |
| 28SW | 0.0122 | 2275 | 0.0210 | 4652 | +0.0088 | no |
| 28SV | 0.0127 | 4931 | 0.0210 | 10331 | +0.0083 | no |
| 9LLR | 0.0040 | 1412 | 0.0110 | 1412 | +0.0070 | **yes** |
| 9PN7 | 0.0018 | 9634 | 0.0070 | 9634 | +0.0052 | **yes** |
| 9HW2 | 0.0161 | 4426 | 0.0210 | 8843 | +0.0049 | no |
| 28SZ | 0.0032 | 2311 | 0.0080 | 2322 | +0.0048 | no |
| 11AF | 0.0104 | 2630 | 0.0150 | 2670 | +0.0046 | no |
| 30IZ | 0.0038 | 9513 | 0.0080 | 9513 | +0.0042 | **yes** |
| 12LO | 0.0051 | 440 | 0.0090 | 440 | +0.0039 | **yes** |
| 9HX9 | 0.0175 | 8454 | 0.0210 | 16758 | +0.0035 | no |
| 37BG | 0.0075 | 8518 | 0.0100 | 8534 | +0.0026 | no |
| 24MR | 0.0086 | 9248 | 0.0110 | 9270 | +0.0023 | no |
| 37AP | 0.0087 | 1803 | 0.0100 | 1803 | +0.0013 | **yes** |
| 37AS | 0.0097 | 3556 | 0.0110 | 3556 | +0.0013 | **yes** |

| Subset | n | median \|Δ\| | max \|Δ\| |
|---|---:|---:|---:|
| Same bond count | 6 | 0.0040 | **0.0070** |
| Different bond count | 11 | 0.0049 | **0.0667** |
| All | 17 | 0.0048 | 0.0667 |

Signed: gemmi reads higher in **17 of 17**.

## Findings

**1. ±0.003 Å fails, systematically.** Even on the six models where both tools restrain exactly the
same number of bonds, the median disagreement is **0.0040 Å** and the max **0.0070 Å** — the
tolerance is exceeded by the *typical* case, not the tail. The direction is fixed: gemmi higher in
17/17, with no sign changes.

**2. ~~The cause is the restraint library~~ — CORRECTED, see
`tolerance_benchmark_restraint_library.md`.** This section originally attributed the gap to the
restraint library, by analogy with the review's bond-angle finding. A follow-up benchmark isolated
the library switch inside a single implementation (PHENIX with CDL vs Engh & Huber, A vs B) and found
it accounts for **21 %** of the gap on matched-bond-count models (median 0.00085 of 0.00405 Å; 9 %
across all 17, deflated by the count-mismatched models). The remaining B-vs-C contrast reflects
cross-engine implementation (how the two tools enumerate and sum bond restraints) together with
residual differences between non-identical Engh & Huber-derived dictionaries and restrained bond
populations. The tolerance below is unaffected; its *explanation* was wrong, which matters because
switching PHENIX from CDL to Engh & Huber alone does not bring the two tools into agreement. For bond
**angles** the library-conditional framing does hold (51 % of the angle gap, median 0.265°).

**3. The two tools frequently do not restrain the same bonds — and the mismatch is often a factor of
two.** Only 6/17 agree on the bond count. Several disagree ~2× (30TW 4677 vs 9544; 28SX 2330 vs
4769; 9HX9 8454 vs 16758), consistent with different handling of alternate conformations. Where the
counts diverge, the disagreement blows out to 0.0667 Å — 22× the old tolerance. A bond-count
mismatch means the two RMSDs are sums over different restraint populations and are not comparable.

## Applied tolerance

> **|Δ| ≤ 0.008 Å, and only when both tools restrain the same number of bonds.** With **matched
> restraint libraries** the tolerance is **|Δ| ≤ 0.006 Å** — barely tighter, because the within-PHENIX
> library switch accounts for ~21 % of the disagreement (`tolerance_benchmark_restraint_library.md`). Expect gemmi/CCP4-library figures to read
> **high** against PHENIX/CDL; a negative Δ is off-distribution. When the bond counts differ (11/17
> here), the comparison is **void**: report both figures with their counts rather than a Δ.

0.008 Å covers 6/6 of the matched-count subset (max 0.0070) with margin. This loosens the tolerance
by ~2.7×, which is the honest direction: the old ±0.003 Å was tighter than the observed cross-tool
differences, so it would have flagged correct models as disagreeing.

## Scope limits

- Cross-library only. The near-matched-library contrast was measured separately in
  `tolerance_benchmark_restraint_library.md` and informs the adopted conditional **0.006 Å** band, with
  residual confounding from non-identical Engh & Huber-derived dictionaries and possible bond-population
  differences — not "much tighter", because the within-PHENIX library switch turned out to be a minor
  term for bond lengths.
- The ~2× bond-count mismatches are attributed to alternate-conformation handling by inspection, not
  verified — the scripts record the counts but do not diff the restraint lists.
- 17 X-ray models, bond RMSD 0.0018–0.0175 Å. Models with unusual ligands or heavy covalent
  modification are not represented, and are where monomer-library coverage differences would be
  largest.
- One version pair: PHENIX 2.0-5936 and gemmi against CCP4 9.0.015's monomer library — gemmi **0.7.4** (CCP4's bundled binary) for the rmsz legs, see the disclosure below.

> **Disclosure (2026-08-29, #502).** The `gemmi rmsz` legs above ran under the sourced CCP4 environment, which prepends `ccp4-9/bin` to `PATH` — and that directory carries CCP4's bundled **gemmi 0.7.4**. So the rmsz figures in this document were produced by 0.7.4, not the Homebrew 0.7.5 named here and in the run manifests; the PHENIX and monomer-library identities are unaffected. A one-model spot check (1d3z, full rmsz output) is byte-identical between the two versions; the tables were not re-run and are not re-judged. From PR #501 on, every gemmi invocation resolves through `toolchain.gemmi_executable()` (`PROTSTRUCT_GEMMI` or PATH, absolute path in argv), and the run manifest written by `tool_versions()` records that resolved path and version alongside the measurement.
