# Driving example — T14 Hydrogen placement / protonation

Standalone per-task driver for **T14 (hydrogen placement / protonation)**. Follows the structure of
`ref/driving_example.md`. Flip-conflict grading is suspended: all scopes are informational and
criterion-free pending a matched independent benchmark (#809). The retained round47/48 comparison
used PHENIX-distributed `reduce` and `mmtbx.reduce2`, not the claimed standalone pair; both producers
are catalogued cctbx-family. `phenix.reduce` and standalone `reduce` dispatch the same Richardson
implementation in the measured installation, so their agreement is a packaging/defaults check,
not independent scientific corroboration. The other registered checks retain their own exact
implementation and applicability conditions.

> **Thresholds are defined once** in `ref/thresholds_and_standards.md`; the `[provenance]` tags below
> point into it.

## Scenario

The agent is handed a model without hydrogens (or partial H) and asked to add hydrogens, propose
Asn/Gln/His flips, and report the clashscore change and H-bond-network consistency.

## Dataset — concrete IDs

- **Primary:** PDB `1HQ1` (high-res, no deposited hydrogens).
- **Neutron comparator (where available):** PDB `5E5V` — neutron data locate H directly.

## What the agent must do

1. Add hydrogens with `phenix.reduce`, recording the executable/version, build variant
   (`reduce -build` versus plain add-H), and electron-cloud versus nuclear H convention.
2. Record H-atom count, the per-residue Asn/Gln/His decisions, clashscore before and after the
   build, and H-bond-network observations.
3. Expected artefacts: the H-added model and complete reduce log, including its `USER  MOD` records
   (H tallies and the residue-level flip decisions needed to audit a conflict count), plus the het
   dictionary path actually loaded (resolved from `-DB`, then a same-named file in the working
   directory, then `REDUCE_HET_DICT`, then the compiled default) and `reduce`'s stderr. `USER  MOD` does
   not record the dictionary; a build that cannot open one reports `could not open` on stderr and adds
   no hetero hydrogens, which went unnoticed in the benchmarks because stderr was discarded (#799).

## Independent cross-checks (harness, not agent)

- **Standalone `reduce 4.16.250520`** (Richardson lab) — compare with the PHENIX redistribution
  only when `phenix.reduce` also reports `reduce.4.16.250520`, and only as a
  dispatcher/distribution check; it is not an independent H-placement oracle.
- **`mmtbx.reduce2` from PHENIX 2.0-5936** — a distinct H-builder, but still cctbx-family.
  The historical benchmark compared it with PHENIX-distributed `reduce`, using
  `approach=add add_flip_movers=True`; it is not independent corroboration under the trust model.
- **`propka3`** — independent pKa / protonation-state prediction for His/Asp/Glu.
- Neutron structure — direct experimental H positions, the tiebreaker when available.

## Scoring rubric

Every applicable gradeable check must pass for green. A void comparison must be reported as void,
not converted to either a pass or a fail. The suspended flip check cannot supply a pass or establish
independent H-placement validation.

1. **Conditional H-count agreement.** For a protein-only model, `phenix.reduce` and standalone
   `reduce` must add the identical number of H atoms (**Δ = 0**) only for the measured tool/version
   pair: the PHENIX redistribution and standalone build both reporting `reduce.4.16.250520`. A tool
   or version mismatch is informational pending a matched benchmark. When non-water hetero
   components are present, the registered comparison is **void**: the measured counts diverged on
   ligand-bearing models, most likely because the standalone build loaded no het dictionary as
   invoked (#799). Even an exact count is only a same-binary
   packaging/defaults check and says nothing about H-position agreement.
   `[benchmark — H-placement agreement]`
2. **Confident flip-set conflicts — informational only.** Count a conflict where the identified
   `reduce` producer made a confident F/K call and `reduce2` made the opposite flip decision.
   X/C calls remain in the eligible shared-residue denominator but not the conflict numerator.
   Retain both the numerator and denominator, the source rows and residue-level evidence.
   A cohort still uses `scope: cohort` with its exact preregistered set in `scope_selector`.
   No scope may use the historical cohort band: parent and nested interpretation metadata must
   remain informational and criterion-free. The retained PHENIX-distributed Reduce versus
   reduce2 numbers do not calibrate the proposed independent standalone comparison.
   `[benchmark — historical informational evidence; registry §3, #809]`
3. **Clashscore agreement.** Report each builder's pre→post clashscore change informationally. Apply
   the registered Clashscore envelope — **|Δ| ≤ 1.0, or 20 % of the mean, whichever is larger** —
   only when both counters score hydrogens built by the **same `reduce` binary and version** under the
   same electron-cloud or nuclear convention. The benchmark compared `phenix.clashscore` with standalone
   `probe`, each on hydrogens built separately by that release (PHENIX's internal build disables
   Asn/Gln/His flips by default; the standalone build, as invoked, most likely loaded no het
   dictionary, #799); it did not establish identical H
   coordinates, did not separate H construction from clash counting, and did not benchmark changes
   between `reduce` and `mmtbx.reduce2` models. A builder or H-convention mismatch makes the
   governed comparison **void**, not failed. Clashscore version pin: PHENIX 2.0-5936, Richardson reduce 4.16.250520 (both builds), and standalone probe 2.26.021123. Other or unverified versions are informational pending a matched benchmark, not a threshold pass or fail.
   Matching versions alone does not validate changed H-build settings (#799/#790).
   `[benchmark — Clashscore]`
4. **Build configuration disclosed.** State the add-H/flip-mover settings, H convention, executable
   version, and hetero dictionary provenance. `reduce -build`, plain add-H, and
   `mmtbx.reduce2 approach=add add_flip_movers=True` are not interchangeable.

## Notes

- `phenix.reduce` versus standalone `reduce` can localise a dispatcher, packaging, or defaults bug,
  but cannot close the trust-model requirement because both names reach the same underlying binary.
- H-count agreement is deliberately separate from H-position/clashscore agreement: atom counts are
  nearly insensitive to the electron-cloud/nuclear convention that dominates clashscore.
- No registered tolerance currently grades a difference between the pre→post clashscore changes of
  two distinct H builders. Keep that comparison informational until its exact pipeline is benchmarked.
- Treat an implementation/version/configuration change as a new pipeline: retain it, report it, and
  do not inherit a verdict from the pinned benchmark without a matched preregistered remeasurement.
