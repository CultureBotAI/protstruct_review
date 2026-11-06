# Tolerance benchmark — restraint library vs implementation in geometry RMSD

Closes the matched-library gap PR #28 opened, and **corrects a claim PR #28 made**.

PR #28 measured bond-length RMSD across libraries (PHENIX/CDL vs gemmi/CCP4 monomer library), set
±0.008 Å, and attributed the gap to the restraint library — by analogy with the domain-expert
review's bond-*angle* finding. That attribution was never tested. It is wrong for bond lengths.

Reproduce with:

```bash
python3 scripts/bench_t05_restraint_library.py --ids-file <ids.json> --cache <dir> --json <out.json>
```

## Configuration

Three configurations over the same 17 deposited models, which lets the disagreement be decomposed
instead of merely measured:

| | Tool | Library |
|---|---|---|
| **A** | `phenix.model_statistics restraints_library.cdl=True` | CDL (PHENIX default) |
| **B** | `phenix.model_statistics restraints_library.cdl=False` | Engh & Huber |
| **C** | `gemmi rmsz` | CCP4 monomer library (E&H-derived) |

- **A vs B** — pure **library** effect: one implementation, one code path, only the targets change.
- **B vs C** — near-matched library, different implementations: combines **implementation** with residual non-identical dictionary and bond-population differences.
- **A vs C** — the cross-library figure PR #28 published.

"Near-matched" is load-bearing in B vs C: the CCP4 monomer library is E&H-derived but not identical
to PHENIX's non-CDL targets, and the two tools may restrain different populations. The B-vs-C
contrast therefore includes non-identical dictionaries and potentially different populations; it does not isolate or bound an unmeasured matched-library contrast.

## Results

Bond RMSD (Å), sorted by the implementation term:

| Entry | A: CDL | B: E&H | C: gemmi | library (B−A) | implementation (C−B) |
|---|---:|---:|---:|---:|---:|
| 30TW | 0.01434 | 0.01427 | 0.08100 | −0.00007 | +0.06673 |
| 9PLB | 0.00949 | 0.00949 | 0.02400 | +0.00000 | +0.01451 |
| 28SX | 0.00354 | 0.00474 | 0.01700 | +0.00120 | +0.01226 |
| 28SW | 0.01220 | 0.01238 | 0.02100 | +0.00018 | +0.00862 |
| 28SV | 0.01266 | 0.01309 | 0.02100 | +0.00043 | +0.00791 |
| 9LLR | 0.00400 | 0.00522 | 0.01100 | +0.00122 | +0.00578 |
| 11AF | 0.01040 | 0.01005 | 0.01500 | −0.00035 | +0.00495 |
| 9HW2 | 0.01610 | 0.01620 | 0.02100 | +0.00010 | +0.00480 |
| 9PN7 | 0.00180 | 0.00354 | 0.00700 | +0.00174 | +0.00346 |
| 28SZ | 0.00322 | 0.00457 | 0.00800 | +0.00135 | +0.00343 |
| 12LO | 0.00510 | 0.00568 | 0.00900 | +0.00058 | +0.00332 |
| 9HX9 | 0.01753 | 0.01783 | 0.02100 | +0.00030 | +0.00317 |
| 30IZ | 0.00379 | 0.00491 | 0.00800 | +0.00112 | +0.00309 |
| 24MR | 0.00865 | 0.00827 | 0.01100 | −0.00038 | +0.00273 |
| 37BG | 0.00745 | 0.00795 | 0.01000 | +0.00050 | +0.00205 |
| 37AS | 0.00966 | 0.01002 | 0.01100 | +0.00036 | +0.00098 |
| 37AP | 0.00872 | 0.00914 | 0.01000 | +0.00042 | +0.00086 |

| Term | bond, median | bond, max | angle, median | angle, max |
|---|---:|---:|---:|---:|
| Library (A vs B) | **0.00042 Å** | 0.00174 Å | **0.265°** | 0.471° |
| Implementation (B vs C) | **0.00346 Å** | 0.06673 Å | **0.298°** | 0.707° |
| Cross-library (A vs C) | 0.00478 Å | 0.06666 Å | 0.519° | 1.122° |

Restricted to the 6 models where PHENIX and gemmi restrain the **same number of bonds**:
within-PHENIX CDL→E&H switch (A vs B) median 0.00085 Å (max 0.00174), near-matched B-vs-C contrast median 0.00320 Å (max **0.00578**). *(Note: the historical table labels "library" and "implementation" above denote the A−B and B−C contrasts respectively and do not establish a pure causal decomposition.)*

## Findings

**1. PR #28's attribution was wrong for bond lengths.** On the 6 models where PHENIX and gemmi
restrain the **same number of bonds** — the only population where the bond-RMSD tolerance considers
the comparison valid at all — the within-PHENIX CDL→E&H switch (A vs B) accounts for **21 %** of the gap (median
0.00085 of 0.00405 Å). Across all 17 models it is 9 %, but that figure is deflated by the
count-mismatched models, whose B-vs-C contrast is contaminated by differing bond populations (30TW alone contributes
+0.067 Å). Quote **21 %**; the conclusion is the same either way — the within-PHENIX CDL→E&H switch is the minority
term — but 9 % overstates the point by more than double.

Switching PHENIX from CDL to Engh & Huber isolates the within-PHENIX library switch inside one
implementation, and it barely moves the number. The remaining ~79 % in B vs C reflects cross-engine
implementation (how gemmi and PHENIX enumerate and sum bond restraints) together with residual
differences between non-identical Engh & Huber-derived dictionaries and restrained bond populations.
The ±0.008 Å tolerance itself stands; only its stated *cause* was wrong, and that matters because
switching PHENIX from CDL to Engh & Huber alone does not bring the two tools into agreement.

**2. For bond angles the library-conditional framing is right.** The within-PHENIX CDL→E&H switch accounts for **51 %** of
the cross-library angle gap (56 % on matched-count models — stable, unlike the bond-length share), with a median effect of **0.265°** and a max of 0.471° — an in-repo,
independent confirmation of the review's "0.3–0.4° for library reasons alone", which until now was
a literature claim the harness had never reproduced. Bond angles and bond lengths simply do not
behave the same way, and the review's angle finding does not transfer.

**3. The near-matched-library contrast is barely tighter than the cross-library tolerance.** On matched bond
counts the observed B-vs-C contrast (with non-identical E&H-derived dictionaries and possible population differences) is median 0.0032 Å, max **0.0058 Å**, against the cross-library
±0.008 Å. The within-PHENIX CDL→E&H switch alone did not eliminate the observed cross-tool gap, which follows directly from
finding 1.

## Applied

> **Bond-length RMSD keeps |Δ| ≤ 0.008 Å** across implementations, gated on equal bond count. The
> adopted conditional **matched-library** policy band remains **|Δ| ≤ 0.006 Å**; this study does not
> directly measure or bound the truly matched cross-engine contrast, so its empirical tightness is not established by the ~21 % within-PHENIX CDL→E&H (A–B) observation on valid (matched-count) comparisons. The within-PHENIX CDL→E&H switch alone did not eliminate the observed cross-tool gap on bond lengths.
>
> **Bond-angle RMSD** keeps its library-conditional treatment, now with an in-repo magnitude: the
> within-PHENIX CDL→E&H switch shifts angle RMSD by a median **0.265°** (max 0.471°).

## Scope limits

- The within-PHENIX CDL→E&H switch's share of the gap is subset-dependent for bond lengths (21 % on matched-count models,
  9 % across all 17) because the count-mismatched models inflate the B-vs-C contrast. It is
  stable for angles (51 %/56 %). Both readings support the same conclusion.
- B vs C is a near-matched contrast, not a direct measurement of a matched-library floor: E&H and the CCP4 monomer library are
  related but not identical, and the two tools may restrain different populations, so residual library and population differences remain inside the historical "implementation" (B vs C) column.
- The bond-count mismatch that dominates the tail (30TW, +0.067 Å) is unexplained beyond the
  inspection in `tolerance_benchmark_bond_rmsd.md` — the scripts record counts but do not diff the
  restraint lists.
- 17 X-ray models; ligand-heavy models, where monomer-library coverage differs most, are not
  represented.
- One version pair: PHENIX 2.0-5936, gemmi **0.7.4** (CCP4's bundled binary, for the rmsz legs — see the disclosure below), CCP4 9.0.015 monomer library.

> **Disclosure (2026-08-29, #502).** The `gemmi rmsz` legs above ran under the sourced CCP4 environment, which prepends `ccp4-9/bin` to `PATH` — and that directory carries CCP4's bundled **gemmi 0.7.4**. So the rmsz figures in this document were produced by 0.7.4, not the Homebrew 0.7.5 named here and in the run manifests; the PHENIX and monomer-library identities are unaffected. A one-model spot check (1d3z, full rmsz output) is byte-identical between the two versions; the tables were not re-run and are not re-judged. From PR #501 on, every gemmi invocation resolves through `toolchain.gemmi_executable()` (`PROTSTRUCT_GEMMI` or PATH, absolute path in argv), and the run manifest written by `tool_versions()` records that resolved path and version alongside the measurement.
