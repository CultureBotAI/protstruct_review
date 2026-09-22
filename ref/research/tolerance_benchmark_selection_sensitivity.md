# Tolerance benchmark — what two "matched selection" preconditions are worth

Two tolerances in `ref/thresholds_and_standards.md` carry a precondition rather than a measured
number, because no second implementation of either tool is installed:

- **DockQ score** `|Δ| ≤ 0.01` *after fixing/verifying the chain mapping*, with chain-mapping
  ambiguity treated as a measurable variance source.
- **NMR ensemble precision** `|Δ| ≤ 0.05 Å` *only on a matched ordered-core selection*, because
  "precision is dominated by the superposition selection".

A cross-tool benchmark is unavailable for both. The *presumption each rests on* is measurable, and
that is what these two benchmarks do: vary only the selection and watch the metric move.

```bash
python3 scripts/bench_t16_dockq_mapping.py --cache <dir> --json <out.json>
python3 scripts/bench_t17_ordered_core.py <ensembles.pdb> --json <out.json>
```

## DockQ — chain-mapping ambiguity

Each structure is scored **against itself**, so a perfect mapping is 1.0 by construction and
everything below is mapping cost alone, with no modelling error mixed in. Only mappings that pair
chains of the *same sequence* are scored: mapping onto a different sequence is an error, not
ambiguity.

| Complex | chains | mapping | DockQ |
|---|---:|---|---:|
| 4HHB | 4 | ABCD:ABCD | **1.0000** |
| 4HHB | | ABCD:CDAB | 0.9819 |
| 4HHB | | ABCD:ADCB | **0.2145** |
| 4HHB | | ABCD:CBAD | **0.2116** |
| 1BRS | 6 | ABCDEF:ABCDEF | **1.0000** |
| 1BRS | | ABCDEF:CBADEF | **0.2175** |

Spread: **0.785 median, 0.788 max** — against a ±0.01 tolerance, i.e. **~79×**. 1VFB, 3HFM and 2SIC
have no equivalent chains and so no ambiguity to measure.

That **0.788 maximum belongs to this five-entry self-comparison benchmark**; it is not a universal
upper bound. A later 1SAR control compares the packaged model with the deposited reference and
retains both same-sequence mappings in
`data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-09-21.yaml`: `AB:AB` scores 0.9445 and
`AB:BA` scores 0.0063, a spread of **0.9382** (~94× the tolerance). The underlying DockQ outputs
are retained as `EVIDENCE_1sar_cdba2c07_2026-09-21_dockq_AB_AB.json` and
`EVIDENCE_1sar_cdba2c07_2026-09-21_dockq_AB_BA.json` in the same directory. The A/B pair is a
**crystallographic contact**, not a certified biological assembly, so this follow-up extends the
observed mapping-sensitivity category without becoming another biological-assembly benchmark row.

**Findings.** The presumption is now proven, with a magnitude: a plausible mis-mapping moves DockQ
from 1.00 to 0.21 — the difference between CAPRI class *High* and *Incorrect*. Note 4HHB's
`CDAB` mapping still scores 0.98: swapping the two αβ half-tetramers maps each chain onto its
pseudo-symmetric equivalent, so the ambiguity is harmless there. Swapping only one pair (`ADCB`,
`CBAD`) collapses the score. So "chain-mapping ambiguity" is not one risk but two: symmetric swaps
that cost nothing, and partial swaps that cost everything — and only the second is detectable from
the score alone. The original hetero-complexes each had a unique sequence per chain and therefore
one plausible mapping, but the 1SAR follow-up shows that the underlying condition is broader than
biological homo-oligomer status: ambiguity exists whenever the selected reference interface offers
sequence-equivalent chains, including a nonbiological crystallographic contact.

## NMR ensemble precision — ordered-core selection

`scripts/t17_nmr_ensemble.py` defines the ordered core as residues with per-residue Cα RMSF ≤ 2.0 Å.
The cutoff is swept while everything else is held fixed; the script's own functions are reused, so
this measures the harness's metric rather than a re-implementation.

Mean Cα RMSF (Å) by ordered-core cutoff:

| Ensemble | residues | whole chain | 1.0 Å | 1.5 Å | 2.0 Å | 2.5 Å | 3.0 Å | 4.0 Å | sweep spread |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1D3Z | 76 | 0.428 | 0.300 | 0.316 | 0.316 | 0.316 | 0.316 | 0.355 | 0.054 |
| 1G6J | 76 | 0.575 | 0.444 | 0.455 | 0.455 | 0.477 | 0.477 | 0.513 | 0.069 |
| 1XPW | 143 | 0.778 | 0.583 | 0.666 | 0.703 | 0.724 | 0.724 | 0.724 | 0.141 |
| 2K39 | 76 | 1.390 | 0.853 | 1.027 | 1.068 | 1.095 | 1.095 | 1.123 | 0.271 |
| 2N54 | 132 | 3.798 | — | 1.365 | 1.643 | 1.889 | 2.074 | 2.207 | **0.842** |

| | median | max |
|---|---:|---:|
| Spread across cutoffs | **0.141 Å** | **0.842 Å** |
| Whole chain − 2.0 Å core | 0.120 Å | **2.154 Å** |

**Findings.** Changing only the ordered-core cutoff — no different tool, no different ensemble, no
different superposition algorithm — moves the reported precision by a median of 0.141 Å and up to
0.842 Å, i.e. **3× to 17× the ±0.05 Å tolerance**. Reporting the whole-chain mean instead of the
ordered-core mean moves it by up to 2.154 Å, **43×**. The precondition is not a refinement of this
tolerance; it is the difference between the tolerance meaning something and meaning nothing. A sixth
ensemble (2JZ4) failed loudly — "no residues below the ordered-core cutoff — ensemble is disordered"
— which is the T17 script degrading as designed rather than returning a number.

## Applied

> **DockQ |Δ| ≤ 0.01 stands, and its chain-mapping precondition is now a hard gate, not a caveat.**
> The original controlled benchmark observed a maximum spread of **0.788** (~79× the tolerance),
> and the later 1SAR crystallographic-contact control extends the observed spread to **0.9382**
> (~94×).
> Record the mapping with any DockQ score. Symmetric whole-subunit swaps may cost almost nothing
> (4HHB `CDAB` → 0.98) while partial swaps collapse the score, so a high score does not prove the
> mapping is right. The gate applies whenever sequence-equivalent reference chains admit more than
> one mapping, whether or not the pair is a biological homo-oligomer.
>
> **NMR precision |Δ| ≤ 0.05 Å stands, and requires the ordered-core *cutoff* to match, not merely
> the intent to use one.** The cutoff alone is worth up to 0.84 Å; whole-chain vs ordered-core is
> worth up to 2.15 Å. Report the cutoff with the value.

## Scope limits

- Both original benchmarks are **self-comparisons**, not cross-tool measurements: they bound what
  the precondition is worth, not the tool-vs-tool noise floor, which remains unmeasured for lack of
  a second implementation of either. The later 1SAR mapping control is explicitly a separate
  model-to-reference observation.
- DockQ's controlled self-comparison benchmark: 2 complexes with genuine ambiguity out of 5
  attempted, and mapping enumeration is capped at 8 per complex. The later 1SAR result is a
  separately retained model-to-reference crystallographic-contact control, not a sixth row in that
  benchmark. Sequence identity is judged by exact one-letter match from CA records, so
  near-identical chains (point mutants, differing disorder) are treated as distinct and their
  ambiguity is missed.
- NMR: 5 ensembles, 76–143 residues. The cutoff grid is 6 fixed values, not the actual OLDERADO or
  PSVS FindCore definitions, which select cores by a different procedure entirely.
