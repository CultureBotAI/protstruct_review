# Domain-expert review — cross-tool `[template]` agreement tolerances

A crystallographer / structural-biology methods review of the `[template]`-tagged agreement
tolerances in `ref/thresholds_and_standards.md`. These are **inter-program agreement tolerances** —
how close two independent tools must land on the same input for the harness to treat a measurement
as corroborated — not absolute quality bars. The tolerance should approximate the tool/method noise
floor for that quantity.

Produced by a fan-out deep-research pass (21 primary sources → 89 extracted claims → 25 verified by
3-vote adversarial verification → 22 confirmed, 3 refuted). This file is the audit trail; the
actionable edits it motivated are applied to `ref/thresholds_and_standards.md` and noted below.

## Headline verdict

The metric **definitions** the harness compares are sound (clashscore = serious overlaps ≥ 0.4 Å per
1000 atoms; the 98%-favored / 0.5%-outlier Ramachandran calibration; model-map FSC = 0.5 and
half-map FSC = 0.143; CC\* = √(2·CC½/(1+CC½))), so tolerances built on them measure the right
quantities. Two thresholds are wrong as set; the rest of the *assessed* set is defensible; and ten
tolerances were left unassessed for lack of direct evidence (a follow-up pass covers them).

## Applied fixes (see `ref/thresholds_and_standards.md`)

### 1. Bond-angle RMSD ±0.1° — DEFECT, made library-conditional (verified 3-0)

Restraint-library choice **alone** shifts bond-angle RMSD by **0.3–0.4°** — 3–4× the tolerance — and
resolution-independently. PHENIX has defaulted to the conformation-dependent library (CDL) since
~2016; gemmi draws bond/angle targets from the CCP4 monomer library (Engh & Huber lineage, shared
with Refmac). A PHENIX-vs-gemmi pairing therefore breaks ±0.1° for library reasons, not real
disagreement (one benchmark measured a ~0.64° PHENIX-vs-REFMAC angle gap on identical data).
**Fix applied:** require matched restraint libraries before comparing bond-angle RMSD; when libraries
differ, widen the tolerance to ~**±0.4°**.
*Sources: Moriarty NW, Tronrud DE, Adams PD & Karplus PA (2016), "A new default restraint library for the protein backbone in Phenix: a conformation-dependent geometry goes mainstream", Acta Cryst. D72(1):176–179, DOI 10.1107/S2059798315022408 — title, authors, volume/issue and page range verified against the Crossref API 2026-07-24 (IUCr blocks direct fetches); Tronrud & Karplus 2011;
Touw & Vriend 2010 (Acta Cryst. D66); gemmi documentation; Wojdyr et al. 2023 (Acta Cryst. D).*

### 2. CC½ high-resolution floor — citation corrected + loosened (verified 3-0)

Two problems. (i) **Misattribution**: the CC½ 0.1–0.2 cutoff material is in **Diederichs & Karplus
2013** ("Better models by discarding data?", Acta Cryst. D69:1215–1222), *not* the "Karplus &
Diederichs 2012" the registry cited. (ii) The **0.3 floor is more conservative than the source's own
0.1–0.2 recommendation**, and it ignores that statistical significance is sample-size-dependent
(CC > 0.3 significant only for n > 100; CC > 0.08 significant for n > 1000).
**Fix applied:** correct the citation to the 2013 companion paper and state the floor as **CC½ ≈
0.1–0.2** (with the note that significance is n-dependent), rather than a fixed 0.3.
*Sources: Karplus & Diederichs 2012 (Science 336:1030–1033) for CC½/CC\*; Diederichs & Karplus 2013
(Acta Cryst. D69:1215–1222) for the 0.1–0.2 cutoff and sample-size significance.*

## Confirmed sound (kept, with a noted precondition where relevant)

- **Bond-length RMSD ±0.003 Å** — defensible; bond lengths are nearly library-insensitive (unlike
  angles). Caveat: possibly slightly tight at atomic resolution, where CDL sigmas differ. (Moriarty
  2016; Moriarty et al. 2014, FEBS J.)
- **Clashscore ±1.0** — well grounded (Chen et al. 2010, Acta Cryst. D66:12–21; Williams et al. 2018,
  Protein Science 27:293–315). The absorbed ~0.5 hydrogen-build shift is mechanistically correct
  (Reduce places H at electron-cloud-center for X-ray vs nuclear positions; a ~0.1–0.16 Å per-H shift
  changes clash counts). **Recommended precondition** (added as a note): match the H-build convention
  between the two tools rather than absorbing it as a fudge.
- **Ramachandran / rotamer favored % (±1.0 pp) and outlier % (±0.5 pp)** — the safest fixed numbers;
  the 98%-favored / 0.5%-outlier calibration is correctly stated (Williams et al. 2018). Note: these
  measure inter-tool *agreement*, not convergence to an absolute MolProbity bar.
- **FSC 0.5 / 0.143** — correctly stated and applied (Rosenthal & Henderson 2003, J. Mol. Biol.
  333:721–745; Scheres & Chen 2012, Nat. Methods). Preserve the nuance: half-map FSC = 0.143 ↔
  model/reference-map FSC = 0.5; and `d_FSC_model` is "true resolution" only when the reference model
  is *independent* of the map (a model refined against the same map inherits an overfitting caveat).

## Refuted rationales (do not rely on these, even where the number stands)

Three claims were killed in verification:
- The "absolute MolProbity bar" framing of the pp tolerances (0-3) — they measure agreement, not
  convergence to a fixed MolProbity percentage.
- A >20–30% library-driven **bond-length** shift (1-2) — bond lengths are near-library-insensitive;
  the tight ±0.003 Å tolerance stands *because* of this, not despite it.
- One specific Rosenthal quote grounding the 0.143↔0.5 pairing (0-3) — the pairing still holds via
  Scheres & Chen 2012, but not via that quote.

## Coverage gap — ten tolerances left unassessed in the first pass

No direct primary-source evidence was found in the first pass for: CA RMSD between superposition
tools; aligned-residue count; Wilson B agreement; L-test ⟨|L|⟩; secondary-structure H/E/C agreement;
DockQ; interface BSA vs PISA; NMR ensemble RMSF; the gemmi-vs-PHENIX R offset; and RSCC/EDSTATS.

## Follow-up pass — the three highest-priority unassessed tolerances

The automated follow-up research workflow failed twice on a transient infrastructure error (a
StructuredOutput cap exceeded at the scope step, no progress cached), so the three highest-priority
items were researched directly instead. The remaining seven (CA RMSD, aligned-residue count, Wilson
B, L-test, DockQ, NMR RMSF, R offset) stay genuinely unassessed and provisional.

### RSCC (tolerance 16) — DEFECT confirmed with primary source

**Both the fixed RSCC ≥ 0.8 floor and the ±0.05 inter-program agreement tolerance are unsupportable.**
Tickle 2012 (Acta Cryst. D68:454–467) states verbatim that *"for RSR and RSCC no sensible criterion
for significance which is independent of B factor can be specified"*. RSCC mixes model accuracy and
precision and correlates strongly with B-factor, and the limiting-atom-radius convention alone gives
a 78 % difference in radius (MAPMAN fixed 1.50 Å vs SFALL 2.67 Å at B = 20 Å²), so RSR/RSCC *"vary
wildly according to the software used."* The paper's program-independent alternatives are **RSZD**
(real-space difference-density Z-score — a pure *accuracy* metric, significant at ±3σ) and **RSZO**
(observed-density Z-score — a pure *precision* metric, floor ~1σ).
**Fix applied:** demote RSCC to a corroboration-only signal that requires a **matched limiting-radius
convention**, and point the accuracy judgement at RSZD (±3σ) / RSZO (1σ) instead of a fixed RSCC
number. (Both are computed by EDSTATS and PDB-REDO `density-fitness`.)

### Secondary-structure H/E/C agreement (tolerance 10) — historical finding, superseded

This literature-only pass initially treated a ≥ 0.80 two-assigner floor as defensible from reported
DSSP/STRIDE agreement on ordered regions. The later repository benchmark disproved that use: the
floor failed on 12/16 well-ordered structures yet passed severely perturbed all-coil controls, and
the retained run did not prove today's exact per-assigner denominator. The bad-end sample is also
too sparse to promote DSSP H+E content ≥ 0.20 into a quality threshold. The active rule therefore
reports content as an informational precondition on interpreting two-assigner agreement; it grades
neither value. The separate agent-vs-DSSP ≥ 0.85 clause remains a different comparison. See
`tolerance_benchmark_ss_agreement.md` and the current threshold registry.

### Interface BSA vs PISA (tolerance 12) — historical provisional finding, now benchmarked

This literature pass found no published PISA-vs-Shrake-Rupley reproducibility figure, so the former
±10 % rule was initially provisional. The mechanism remains real: PISA uses a Lee & Richards (1971)
accessible-surface definition with a 1.4 Å probe, and probe radius / point density / inclusion of
waters and hetero atoms all shift SASA; PISA also reports *interface* area by its own definition,
which is not identical to the harness's ΣSASA(chains) − SASA(complex). A later committed empirical
benchmark superseded that provisional disposition: over 25 interfaces, the registered envelope is
max(3 % of the mean, 30 Å²), with matched 1.4 Å probe radius but the selections actually measured —
biotite protein-only versus PISA's API assembly-molecule surface, which may include ligand/hetero
atoms. See `tolerance_benchmark_interface_bsa.md`. *(Krissinel & Henrick 2007, J. Mol. Biol.
372:774–797; Lee & Richards 1971; Shrake & Rupley 1973.)*

## Second follow-up pass — the seven remaining tolerances

Researched directly (the automated workflow having repeatedly failed at its scope step). Three are
defects, two need a matched-configuration precondition, one is likely too tight, one is fine.

### DEFECTS

- **Aligned-residue count ± 2 residues (tolerance 2) — WRONG across aligner classes.** TM-align /
  US-align re-establish the residue equivalences from structure and **drop distant Cα pairs by
  design**; LSQ / sequence-based superposition keeps the full given alignment. Two aligners of
  *different classes* legitimately differ by tens of residues, not ±2. **Fix:** ±2 only *within* an
  aligner class (both structure-based, or both sequence-based); do not compare counts across classes.
  *(Zhang & Skolnick 2005, TM-align, NAR 33:2302; US-align docs.)*
- **NMR ensemble precision ± 0.05 Å (tolerance 13) — selection-dominated, unsupportable as-is.**
  Ensemble precision is the average RMSD to the mean coordinate *after superposition*, and "the
  well-defined positions used for superposition are often hand-picked, making the measure subjective
  and dependent on the choices." The number is dominated by the ordered-core selection, not tool
  noise. **Fix:** require a **matched ordered-core definition** (OLDERADO / PSVS FindCore) before any
  ±0.05 Å comparison; the whole-chain mean the current wrapper computes is especially
  selection-sensitive and should be reported alongside an ordered-core figure.
  *(Vuister et al. 2014, J. Biomol. NMR; OLDERADO — Kelley et al. 1997; PSVS — Bhattacharya et al.)*
- **gemmi-vs-PHENIX R offset "0.005–0.015 higher, gemmi is simpler" (tolerance 14) — rationale
  mischaracterised, magnitude unbenchmarked.** REFMAC and PHENIX both use a flat mask-based
  bulk-solvent model (Afonine 2013), and **gemmi implements the same flat-mask bulk solvent +
  anisotropic scaling** (in its `Scaling` class) — so gemmi is *not* categorically "simpler," and no
  benchmark supports the specific 0.005–0.015 magnitude or its sign. **Fix:** soften to "an
  independent R re-derivation may differ by a small amount from scaling / resolution-binning
  differences; magnitude unbenchmarked," and drop the "simpler bulk-solvent" claim.
  *(Afonine et al. 2013, Acta D69:625–634; gemmi scattering docs.)*

### Matched-configuration preconditions (keep the number, add the precondition)

- **CA RMSD ± 0.10 Å (tolerance 1) — same-selection precondition.** RMSD is computed only over aligned
  Cα pairs, and different aligners align different subsets, so ±0.10 Å is meaningful **only on the
  same residue selection** (both structure-based re-alignment, or both on a fixed selection). Keep the
  number; add the precondition. *(Zhang & Skolnick 2005.)*
- **DockQ ± 0.05 (tolerance 5) — fixed-chain-mapping precondition.** DockQ is deterministic given a
  chain mapping and reproduces the CAPRI classes; **chain-mapping ambiguity in multimers is the only
  real variance source** (DockQ v2 permutes exhaustively but needs the correct mapping). Keep ±0.05;
  require a fixed/verified chain mapping first (already a rule in `driving_example_T16.md`).
  *(Basu & Wallner 2016; DockQ v2, Mirabello & Wallner 2024.)*

### Likely too tight / method-conditional

- **Wilson B ± 2 Å² (tolerance 3).** `xtriage` uses a maximum-likelihood, anisotropy-aware Wilson-B
  estimate (Popov & Bourenkov 2004; Zwart et al. 2005) that is *less sensitive to resolution
  truncation* than the classic straight-line Wilson plot in `truncate`/`ctruncate` (bin-choice
  sensitive; the RSCALE bin control is "discouraged"). ML-vs-classic Wilson B can differ by more than
  2 Å², especially at low resolution or under anisotropy. **Loosen** to ~± 5 Å², or compare
  like-method to like-method. *(phenix.xtriage docs; CCP4 ctruncate/truncate docs.)*

### Fine as set

- **L-test ⟨|L|⟩ ± 0.02 (tolerance 4).** A robust statistic with theoretical values 0.5 (untwinned) /
  0.375 (perfect twin), insensitive to anisotropy/pseudo-centering when Miller indices are partitioned
  properly. The resolution range is auto-determined and differs slightly between programs, so **match
  the resolution range** and keep the same twin/no-twin call requirement. **Keep ± 0.02.**
  *(Padilla & Yeates 2003, Acta D59:1124–1130.)*

### Prioritized shortlist (this pass)

1. **Aligned-residue count (2)** — wrong across aligner classes; make class-conditional.
2. **NMR RMSF (13)** — selection-dominated; require a matched ordered-core (OLDERADO/FindCore).
3. **gemmi-vs-PHENIX R offset (14)** — rationale wrong, magnitude unbenchmarked; soften.
4. **Wilson B (3)** — likely too tight; loosen to ~±5 Å² or match method.
5–6. **CA RMSD (1), DockQ (5)** — add matched-configuration preconditions.
7. **L-test (4)** — fine; match resolution range.

## Independent workflow cross-check (second batch)

The automated deep-research workflow (which had failed on the first two attempts) completed on retry —
91 agents, 0 errors — and **independently confirmed every direct-research verdict above** for the
seven, with two quantitative refinements now folded into the registry:

- **DockQ (5) — tightened.** With chain mapping fixed, the same-implementation noise floor is **≈ 0.004**
  (DockQ v2 vs v1, R = 1.000 over 17,409 CASP15 models), so the kept ±0.05 was **~12× too loose**.
  Tightened to **±0.01**. Also, the hard "identical CAPRI class" rule can spuriously flip at the fixed
  0.23/0.49/0.80 boundaries, so the class match is **waived within ±0.03 of a boundary**. (Caveats the
  cross-check flags: "chain-mapping dominates variance" is a reasonable but *unproven* premise — that
  specific claim was refuted at verification; and v1→v2 is one author group's rewrite, a fair but
  imperfect stand-in for two independent programs.)
- **Wilson B (3) — downgraded to provisional.** No primary source on inter-program Wilson-B
  reproducibility survived verification, so the ±5 Å² is inference-only. At this stage it was marked
  provisional alongside interface BSA; the later committed BSA benchmark superseded only the BSA
  half of that historical disposition.
- **L-test (4) — kept, with a sharper caveat.** The full scale is only 0.125 (untwinned 0.500 →
  perfect twin 0.375), so ±0.02 is ~16 % of range; and xtriage/ctruncate share the Padilla–Yeates
  *method*, so agreement checks consistent computation, not method-independence.
- **CA RMSD (1), aligned count (2), NMR RMSF (6), R offset (7)** — all confirmed as originally revised
  (matched-configuration preconditions; unbenchmarked R-offset sign/magnitude).

At the time of this pass, interface BSA and Wilson B were both provisional. Interface BSA has since
been empirically benchmarked in this repository; this historical audit's provisional BSA wording is
not the current rule. Consult `ref/thresholds_and_standards.md` for current status.

## Time-sensitivity

PHENIX has defaulted to CDL since ~2016 and gemmi now feeds Refmac5 restraints (2023), so the
library-provenance split behind the bond-angle finding is current as of 2026 — but exact default
dictionaries change with tool versions. **The harness should record restraint-library and tool
versions alongside geometry measurements**, so a geometry disagreement can be attributed to a real
difference rather than a library mismatch.
