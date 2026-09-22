# Tolerance benchmark — interface buried surface area (biotite SASA vs PDBePISA)

De-provisionalizes `Interface buried surface area` in `ref/thresholds_and_standards.md` and the
`T16_interface_buried_surface_area` entry in `ref/structural_criteria.yaml` (GitHub #18). The
previous `|Δ| ≤ 10 %` was `[template]`-inferred: the mechanism (different surface algorithm,
different interface-area definition) was real but the **magnitude was never measured**. This is the
measurement.

Reproduce with:

```bash
python3 scripts/bench_t16_bsa_vs_pisa.py --cache <dir> --json <out.json>
```

## Configuration (matched probe radius, benchmarked asymmetric selections)

| | biotite | PDBePISA |
|---|---|---|
| Algorithm | Shrake–Rupley (numerical, 1000 points/atom) | Lee & Richards (analytical rolling-sphere) |
| Probe radius | 1.4 Å | 1.4 Å |
| Radii set | ProtOr (biotite default; H excluded) | PISA internal |
| Atom selection | `struc.filter_amino_acids` — protein only, no waters, no hetero | assembly molecules incl. ligand/hetero atoms |
| Quantity reported | ΣSASA(chains) − SASA(complex) = **both** sides | `interface_area` = **one** side (the mean of the two) |

The two quantities differ by a factor of two by definition, so the comparison is
biotite BSA vs **2 × PISA `interface_area`**. Failing to halve/double is the single largest error
mode here — it produces a 100 % "disagreement" that is pure bookkeeping.

PISA values come from the PDBe REST API for **biological assembly 1**
(`https://www.ebi.ac.uk/pdbe/api/pisa/interfaces/<id>/1`), not the interactive web server — the
same PISA 2.0 computation, machine-readable. Coordinates are the deposited asymmetric unit from
RCSB.

Two classes of listed "interface" are **excluded**, both because they would not compare what the
tolerance is about:

- **Symmetry mates** (two copies of the same author chain): the ASU cannot reproduce them without
  applying the operator.
- **Fragments of one molecule.** A cleaved protein deposited as several chains presents pairs that
  PISA lists as interfaces but which are *intramolecular*. `fragment_pairs()` detects them by
  building the inter-chain covalent (`SSBOND`) connectivity graph and skipping pairs that are in the
  same component **and** have disjoint residue numbering. Both halves of that test matter: a Fab
  light/heavy pair is disulfide-linked too, but its chains both number from 1, so overlapping ranges
  correctly keep it in as the genuine two-molecule interface it is. PISA's own
  `number_disulfide_bonds` field reads 0 for exactly these pairs and cannot serve as the filter.

1CHO is excluded outright rather than by the guard: its α-chymotrypsin is deposited as three
fragments (E 1–10, F 16–146, G 149–245), so beyond the three intramolecular pairs the guard catches,
its remaining pairs (F/I, G/I) are two halves of a *single* chymotrypsin–OMTKY3 interface. See
[#25](https://github.com/CultureBotAI/protstruct_review/issues/25) — an earlier revision of this
benchmark included all five and it loosened the tolerance.

## Test set and results

25 protein–protein interfaces across 17 entries, spanning 275 → 1839 Å² per side: protease–inhibitor
and other transient complexes, two antibody–antigen complexes, large obligate interfaces, and one
multi-interface oligomer (4HHB, haemoglobin — 5 distinct interfaces).

| Entry | Interface | biotite BSA (Å², total) | PISA area (Å², per side) | PISA × 2 (Å²) | Δ (Å²) | Δ (%) |
|---|---|---:|---:|---:|---:|---:|
| 4HHB | A/C | 562.7 | 274.7 | 549.5 | +13.2 | +2.37 |
| 1VFB | A/C | 697.6 | 336.2 | 672.4 | +25.2 | +3.67 |
| 3HFM | L/Y | 727.5 | 355.9 | 711.7 | +15.7 | +2.19 |
| 1VFB | B/C | 810.6 | 392.6 | 785.2 | +25.4 | +3.18 |
| 3HFM | H/Y | 994.7 | 487.1 | 974.2 | +20.5 | +2.08 |
| 1E96 | A/B | 1195.9 | 590.2 | 1180.3 | +15.5 | +1.31 |
| 1AY7 | A/B | 1247.5 | 616.9 | 1233.8 | +13.7 | +1.11 |
| 3SGB | E/I | 1281.1 | 633.2 | 1266.3 | +14.7 | +1.16 |
| 1GLA | F/G | 1310.4 | 650.9 | 1301.8 | +8.6 | +0.66 |
| 1PPF | E/I | 1340.0 | 660.8 | 1321.5 | +18.5 | +1.39 |
| 4HHB | A/D | 1365.2 | 674.8 | 1349.5 | +15.6 | +1.15 |
| 4HHB | C/B | 1364.5 | 679.3 | 1358.5 | +6.0 | +0.44 |
| 2PTC | E/I | 1439.7 | 714.3 | 1428.5 | +11.2 | +0.78 |
| 1CSE | E/I | 1500.7 | 743.8 | 1487.6 | +13.1 | +0.88 |
| 1BRS | A/D | 1569.1 | 778.5 | 1557.0 | +12.1 | +0.78 |
| 1AVX | A/B | 1599.2 | 792.1 | 1584.1 | +15.1 | +0.95 |
| 1VFB | A/B | 1610.8 | 795.5 | 1590.9 | +19.9 | +1.24 |
| 2SIC | E/I | 1621.7 | 806.9 | 1613.7 | +8.0 | +0.49 |
| 2SNI | E/I | 1640.5 | 815.1 | 1630.3 | +10.2 | +0.62 |
| 4HHB | A/B | 1654.0 | 820.9 | 1641.7 | +12.3 | +0.74 |
| 4HHB | C/D | 1701.4 | 846.6 | 1693.3 | +8.1 | +0.48 |
| 1TGS | Z/I | 1741.1 | 862.6 | 1725.3 | +15.8 | +0.91 |
| 1FSS | A/B | 1988.1 | 980.8 | 1961.5 | +26.6 | +1.35 |
| 1DFJ | E/I | 2622.6 | 1284.7 | 2569.5 | +53.2 | +2.05 |
| 3HFM | L/H | 3724.6 | 1838.6 | 3677.2 | +47.4 | +1.28 |

Distribution of |Δ|: **median 1.15 %, 90th percentile 2.37 %, max 3.67 %**; in absolute terms
median 15.1 Å², max 53.2 Å².

## Findings

**1. The disagreement is one-sided, not scatter.** biotite is larger than 2 × PISA in **25 of 25**
interfaces — there is not one negative Δ. This is a systematic offset, not noise: a signed median of
+1.15 % with zero sign changes. The likely contributors are the radii set (ProtOr vs PISA's internal
radii), Shrake–Rupley's 1000-point quadrature vs an analytical Lee–Richards surface, and PISA
counting ligand/hetero atoms in the molecule surface where the harness recipe counts protein atoms
only. Because the offset is one-directional, a symmetric ± tolerance is the wrong shape in
principle; it is kept only because the offset is small enough that a symmetric bound is not
misleading in practice.

**2. Relative error is dominated by interface size, not by complex type.** Split at 1200 Å² total:

| Subset | n | median \|Δ\| | max \|Δ\| |
|---|---:|---:|---:|
| < 1200 Å² total (< 600 Å² per side) | 6 | 2.28 % | 3.67 % |
| ≥ 1200 Å² total | 19 | 0.91 % | 2.05 % |

The absolute Δ does **not** scale with area (it ranges 6.0 → 53.2 Å² with no clean proportionality),
so relative error blows up on small interfaces — which is also the regime where the measurement
means least, since the harness treats < ~200 Å² per side as a crystal-packing contact rather than a
biological interface.

**3. The provisional ±10 % was ~4× too loose for real interfaces** and, taken as a relative bound
alone, still too tight to be safe on small ones. A single percentage cannot express both.

## Applied tolerance

> **|Δ| ≤ 3 % of the mean, or 30 Å², whichever is larger** — biotite SASA vs PISA, matched probe
> radius (1.4 Å), with the **selection actually benchmarked**: biotite protein-only versus PISA's
> assembly-molecule surface (which may include ligand/hetero atoms), and the PISA per-side area
> doubled. Expect biotite to read **high**; a negative Δ is off-distribution and worth investigating.

This envelope covers 25/25 measured interfaces. The tightest envelope that still covers all 25 is
max(2.5 %, 30 Å²); the relative term is rounded up to 3 % for margin, since with n = 25 and a
one-sided distribution an envelope fitted exactly to the sample would invite false alarms on unseen
data. The floor is what covers the two rows whose *relative* error exceeds 3 % (1VFB A/C at 3.67 %,
B/C at 3.18 % — both ≈ 25 Å² absolute).

On interfaces above ~1200 Å² the 3 % term binds and is ~3× tighter than the retired ±10 %; below
that the 30 Å² floor binds, which is what makes small-interface comparisons survivable.

> **Revision note.** The first version of this benchmark reported median 1.29 %, p90 3.59 %, max
> 9.06 % over 26 interfaces and set the floor at **60 Å²**. Five of those rows came from 1CHO, whose
> chymotrypsin is deposited as three fragments; three were intramolecular contacts and two were
> halves of one interface ([#25](https://github.com/CultureBotAI/protstruct_review/issues/25)).
> They supplied both the worst relative disagreement (9.06 %) and the row that set the 60 Å² floor,
> so removing them tightened the floor to 30 Å². The one-sided finding was unaffected.

## Scope limits

- Measures the **tool-definition noise floor on identical deposited coordinates**. It does not
  bound how much BSA moves when the *model* changes (refinement, agent edits) — that is a different
  quantity and is not benchmarked here.
- All 25 interfaces are protein–protein. Nucleic-acid and protein–ligand interfaces are unmeasured.
  The biotite leg is protein-only, while the PISA API leg uses its assembly-molecule surface; that
  controlled selection mismatch is baked into the empirical envelope and must not be rewritten as
  a matched protein-only PISA comparison.
- The fragment guard keys on `SSBOND` records. A cleaved molecule whose fragments are held together
  by something other than a disulfide, or an entry that omits `SSBOND` records, would not be caught.
  Entries where chain fragmentation is expected should be checked by hand, as 1CHO was.
- PISA assembly 1 only. Alternative assemblies were not tested.
- Single PISA version (2.0, as served by the PDBe API on 2026-07-24) and biotite 1.7.1.
