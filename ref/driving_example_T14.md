# Driving example — T14 Hydrogen placement / protonation

Standalone per-task driver for **T14 (hydrogen placement / protonation)**. Follows the structure of
`ref/driving_example.md`. The load-bearing cross-tool comparison uses genuinely distinct builders:
standalone Richardson-lab `reduce` and `mmtbx.reduce2`. `phenix.reduce` and standalone `reduce`
dispatch the same Richardson binary in the measured installation, so agreement between those two is
a packaging/defaults check, not independent scientific corroboration. The registered bands are tied
to the exact measured implementations and settings named below; merely disclosing a different
version does not make the old band transferable.

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
3. Expected artefacts: the H-added model and complete reduce log, including `USER  MOD` dictionary
   provenance and the residue-level flip decisions needed to audit a conflict count.

## Independent cross-checks (harness, not agent)

- **Standalone `reduce 4.16.250520`** (Richardson lab) — compare with the PHENIX redistribution
  only when `phenix.reduce` also reports `reduce.4.16.250520`, and only as a
  dispatcher/distribution check; it is not an independent H-placement oracle.
- **`mmtbx.reduce2` from PHENIX 2.0-5936** — the distinct H-builder used in the registered
  flip-conflict benchmark. Run with `approach=add add_flip_movers=True`; flip movers are off by
  default. Another version or mover configuration is a new, currently unbenchmarked pipeline.
- **`propka3`** — independent pKa / protonation-state prediction for His/Asp/Glu.
- Neutron structure — direct experimental H positions, the tiebreaker when available.

## Scoring rubric

Every applicable check must pass for green. A void comparison must be reported as void, not converted
to either a pass or a fail.

1. **Conditional H-count agreement.** For a protein-only model, `phenix.reduce` and standalone
   `reduce` must add the identical number of H atoms (**Δ = 0**) only for the measured tool/version
   pair: the PHENIX redistribution and standalone build both reporting `reduce.4.16.250520`. A tool
   or version mismatch is informational pending a matched benchmark. When non-water hetero
   components are present, the registered comparison is **void** because the two distributions
   carry different hetero dictionaries. Even an exact count is only a same-binary
   packaging/defaults check and says nothing about H-position agreement.
   `[benchmark — H-placement agreement]`
2. **Confident flip-set conflicts.** Compare standalone `reduce` with `mmtbx.reduce2`, not with the
   same-binary `phenix.reduce` dispatcher. Count a conflict only where `reduce` made a confident F/K
   call and `reduce2` made the opposite flip decision; `reduce` X/C calls mean that builder declined
   to commit and belong in the raw-disagreement diagnostic, not the conflict numerator. Report both
   the conflict count and eligible shared-residue denominator. The governed **≤ 10 %** band applies
   only to a preregistered cohort aggregate produced by the measured pair — standalone
   `reduce 4.16.250520` and `mmtbx.reduce2` from PHENIX 2.0-5936 with
   `approach=add add_flip_movers=True`. Encode such an aggregate as `scope: cohort` with a
   `scope_selector` naming the exact preregistered set. An individual structure uses its structural
   scope and is informational and criterion-free; a version/configuration mismatch is likewise
   informational rather than a threshold pass or fail.
   `[benchmark — H-placement agreement, round 48]`
3. **Clashscore agreement.** Report each builder's pre→post clashscore change informationally. Apply
   the registered Clashscore envelope — **|Δ| ≤ 1.0, or 20 % of the mean, whichever is larger** —
   only when two counters score the **same H-built coordinates** under the same electron-cloud or
   nuclear convention. The benchmark compared cctbx clash counting with standalone probe after the
   same Richardson H build; it did not benchmark changes between `reduce` and `mmtbx.reduce2`
   models. It measured PHENIX 2.0-5936, `reduce 4.16.250520`, and `probe 2.26.021123`; a counter-version,
   convention, or coordinate mismatch makes the governed comparison **void**, not failed.
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
