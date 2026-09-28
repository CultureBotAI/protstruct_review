# Driving example — T11 Loop / missing-region fitting

Standalone per-task driver for **T11 (loop / missing-region fitting)**. Follows the structure of
`ref/driving_example.md`. Graded by **cross-tool agreement** on the rebuilt loop's fit and geometry,
with a held-out reference loop (where available) as tiebreaker.

> **Thresholds are defined once** in `ref/thresholds_and_standards.md`; the `[provenance]` tags below
> point into it.

## Scenario

The agent is handed a model with a missing/poor loop + map/data and asked to rebuild the loop and
report its fit, geometry, and (where a reference exists) RMSD to the true loop.

## Dataset — concrete IDs

- **Primary:** a deposited structure with a well-ordered loop deliberately deleted, so the deposited
  loop is the held-out reference; + its MTZ/map.

## What the agent must do

1. Run `phenix.fit_loops` / `phenix.rebuild_model`.
2. Record loop RSCC, Ramachandran-favored within the loop, RMSD of the rebuilt loop to the reference,
   and any new outliers introduced elsewhere.
3. Expected artefacts: the rebuilt model + report.

## Independent cross-checks (harness, not agent)

- **EDSTATS** — independent loop RSCC / RSR against the density.
- **MolProbity standalone** — independent Ramachandran/rotamer for the loop and whole-model outliers.
- **`gemmi align`** — RMSD of the rebuilt loop to the held-out reference loop.

## Scoring rubric

Each bullet is pass/fail; all must pass for green.

1. **Loop fits the density (accuracy).** EDSTATS real-space difference-density Z-score **RSZD** within
   **±3σ** per loop residue and observed-density **RSZO** above **~1σ** — the B-factor-independent
   metrics. RSCC/RSR carry no resolution-independent significance criterion, so if reported they are
   corroboration-only and require a matched limiting-radius convention (Tickle 2012). `[literature — real-space density fit]`
2. **Loop geometry is clean.** Ramachandran-favored within the loop meets the geometry Δ-tolerance
   (registry §4); MolProbity vs PHENIX clashscore agree within the registry §3 envelope — |Δ| ≤ 1.0, or 20 % of
   the mean, whichever is larger, with a matched H-build convention and hydrogens from the same
   `reduce` binary and version (a mismatch is void, not failed; record each tool's H convention and
   `reduce` version). `[registry §3 — clashscore]`
3. **Correct rebuild vs reference.** Where a reference loop exists, RMSD of the rebuilt loop is within
   **± 0.10 Å** of an independent `gemmi align` superposition. `[template — CA RMSD]`
4. **No collateral damage.** The rebuild introduces **no new outliers** elsewhere in the model — a
   loop that fits but adds outliers outside the loop is a fail.

## Notes

- A loop can be built into noise with good local RSCC; rule 3 (RMSD to the held-out reference) is the
  ground-truth check, and rule 4 guards against a rebuild that improves the loop at the model's expense.
