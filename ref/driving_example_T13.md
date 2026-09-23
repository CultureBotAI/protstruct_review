# Driving example — T13 X-ray data quality assessment

Standalone per-task driver for **T13 (X-ray data quality assessment)**. Follows the structure of
`ref/driving_example.md`. Graded by **cross-tool agreement** between PHENIX `xtriage` and the CCP4
data-processing oracles on the same reflection file, plus a hard check that the tool is honest about
what the input data can and cannot support.

Provenance tags: `[catalog]` = stated in `ref/catalog.yaml`; `[literature]` = an established
standard (cited inline); `[oracle_tools]` = a constraint documented in `ref/oracle_tools.md`;
`[calibration]` = a sanity check against the deposition.


> **Thresholds are defined once** in `ref/thresholds_and_standards.md`; the `[provenance]` tags below point into it.

## Scenario

The agent is handed a reflection file (MTZ/SCA/CIF), merged or unmerged, and asked to report data
quality: completeness (overall + outer shell), ⟨I/σ(I)⟩, R-merge/R-meas, CC½, twinning (L-test),
anisotropy, Wilson B, tNCS, and ice-ring flags. The harness re-derives the merged-data statistics
with CCP4 `ctruncate` (and `aimless` when unmerged intensities exist) and checks agreement.

## Dataset — concrete IDs

- **Primary:** the PHENIX `xtriage` tutorial MTZ (ships with PHENIX) — a known-good unmerged dataset
  where every metric is computable and `aimless` runs.
- **Merged-only case:** PDB `1SAR` structure factors (F-obs/SIGF-obs only). This exercises the
  documented failure mode where `aimless` aborts (`EMPTY` — no unmerged intensities) and only
  `ctruncate`-computable metrics remain. `[oracle_tools — T13 layering]`

## What the agent must do

1. Run `phenix.xtriage data.mtz` (optionally `phenix.reflection_statistics`).
2. Record: completeness overall + outer, ⟨I/σ(I)⟩, R-merge/R-meas, CC½, L-test statistic, ΔB
   anisotropy, Wilson B, tNCS flag, ice-ring flags.
3. Report `aimless` run status — did it run, or abort for lack of unmerged intensities?

## Independent cross-checks (harness, not agent)

- **CCP4 `ctruncate`** — Wilson B, L-test twinning, ΔB anisotropy, tNCS, ice rings on merged data.
- **CCP4 `aimless`** — the canonical source for CC½, ⟨I/σ⟩ outer, and R-merge/R-meas, but **only
  when unmerged intensities (M/ISYM column) are present**. `[oracle_tools]`
- Wrapper `scripts/t13_data_quality.py` runs both and emits parsed measurement rows.
  Its output is single-oracle **informational** diagnostics, not the paired
  `xtriage`/CCP4 agreement grades below. Rows identify the input MTZ by SHA-256,
  state the selected columns, and cite retained logs using portable repository
  paths. Use a fresh repository-local `--logdir`;
  missing or unrecognized flag evidence is unavailable, not a negative result.

## Scoring rubric

Each bullet is pass/fail; all must pass for green.

1. **Wilson B agreement.** `xtriage` (ML) and `ctruncate` (classic straight-line Wilson plot) Wilson B
   agree within **±5 Å² → max(25 %, 2.5 Å²)**, whichever is larger, and the comparison is **void under
   strong anisotropy** (the two estimators diverge by method, not error). `[registry §3 — Wilson B]`
2. **L-test twinning agreement.** Both tools' ⟨|L|⟩ agree within **±0.02**, and both make the same
   twin/no-twin call. (Untwinned ⟨|L|⟩ ≈ 0.5; perfect-twin ≈ 0.375 — Padilla & Yeates,
   *Acta Cryst.* D 2003.) `[literature]`
3. **Resolution-cutoff honesty via CC½.** If a high-resolution cutoff is claimed, CC½ at that shell
   must be significant. Data are usable down to **CC½ ≈ 0.1–0.2** (Diederichs & Karplus, *Acta Cryst.*
   D 2013), and significance is sample-size-dependent (per-shell test preferred over a fixed floor);
   a cutoff claimed where CC½ has fallen to noise is a fail. `[literature — CC½ resolution-cutoff floor]`
4. **Merged-data honesty.** On a **merged-only** input, CC½, ⟨I/σ⟩-outer, and R-merge/R-meas are
   **not obtainable** — they require unmerged intensities. The agent must report them as
   unavailable, not fabricate them, and `T13_aimless_status` must record the `aimless` abort.
   Reporting a CC½ from merged-only data is a hard fail. `[oracle_tools]` `[catalog T13_aimless_status]`
5. **Completeness agreement.** Overall completeness from `xtriage` vs the deposition's Table 1
   (when the entry is deposited) agrees within **±1 percentage point**. `[calibration — deposition]`

## Notes

- Check 4 is the load-bearing one: the most common T13 failure is a tool (or agent) emitting
  unmerged-only statistics from merged amplitudes. The harness treats a fabricated CC½ as worse than
  an honest "unavailable".
- `aimless` is the canonical oracle but is conditional on the data. When it cannot run, the trust
  model degrades gracefully to `ctruncate` for the metrics that *are* computable — and says so,
  rather than silently dropping to a weaker oracle.
