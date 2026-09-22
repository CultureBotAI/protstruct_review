# Driving example — T16 Interface and assembly quality

Standalone per-task driver for **T16 (interface and assembly quality)**. Follows the structure of
`ref/driving_example.md`. T16 is oracle-only (no PHENIX interface scorer); the deposited biological
assembly is the reference, which is the trust model's tiebreaker.

> **Thresholds are defined once** in `ref/thresholds_and_standards.md`; the `[provenance]` tags below
> point into it. This task is **runnable now** via `scripts/t16_interface_quality.py` (DockQ + biotite
> SASA).

## Scenario

The agent is handed a complex/assembly model — for a predicted or refined interface, plus the
deposited reference assembly — and asked to report interface quality: buried surface area, the DockQ
score against the reference, and its CAPRI class.

## Dataset — concrete IDs

- **Primary:** PDB `1BRS` (barnase–barstar, a canonical tight complex).
- **Second complex:** PDB `2SIC` (subtilisin–SSI).
- **Demonstrated calibration:** identity DockQ on the verified RCSB download
  `data/pdb_mtz/1sar_deposited.pdb` A/B → **1.000, class High**; its interface buries
  **442.1 Å² total two-sided** (**221.05 Å² per side**) by the harness convention
  (`scripts/t16_interface_quality.py`).

## What the agent must do

1. Compute the interface buried surface area (Å²) for the model complex using the harness's
   **total two-sided** convention: `ΣSASA(separated chains) − SASA(complex)`.
2. Score the model interface against the deposited reference with DockQ; report the DockQ score and
   the CAPRI quality class.
3. Expected artefacts: the DockQ JSON and a parsed metrics table.

## Independent cross-checks (harness, not agent)

- **`scripts/t16_interface_quality.py`** runs **DockQ** (model vs native → DockQ score, CAPRI class
  derived from the Basu & Wallner 2016 bands) and **biotite SASA** (Shrake-Rupley buried surface
  area from the model alone — an installable stand-in for PISA). The biotite result is total
  two-sided BSA. Both are non-cctbx.
- **PISA/PDBePISA** corroborates buried surface area and biological-assembly inference where the web
  service is reachable (the deposition-grade reference). PISA `interface_area` is per side and is
  doubled before comparison with the harness total.

## Scoring rubric

Each bullet is pass/fail; all must pass for green.

1. **DockQ reproduces.** With the **same chain mapping**, the agent's DockQ agrees with the harness
   DockQ within **± 0.01** (same-implementation noise floor ≈ 0.004); the **CAPRI class matches**,
   except it is not flagged when either score is within **± 0.03** of a class boundary
   (0.23 / 0.49 / 0.80). `[template — DockQ score]`
2. **Buried surface area agrees.** The agent's protein-only BSA agrees with biotite SASA within
   **max(3 % of the two values' mean, 30 Å²)** after matching a 1.4 Å probe and atom selection.
   A PISA comparison instead uses the exact API convention benchmarked here: its assembly surface
   may include ligand/hetero atoms, and its per-side `interface_area` is doubled. Do not describe
   that PISA leg as a matched protein-only comparison.
   `[benchmark — interface buried surface area]`
3. **CAPRI class matches the score.** The reported class is consistent with the DockQ score under the
   standard bands (High ≥ 0.80; Medium ≥ 0.49; Acceptable ≥ 0.23; Incorrect < 0.23).
   `[literature — CAPRI class from DockQ]`
4. **Identity calibration.** Scoring the deposited reference against itself gives DockQ **1.000** and
   class **High**; anything else exposes a chain-mapping or parsing bug, not a model defect.
   `[calibration]`
5. **Chain mapping disclosed.** The model→native chain mapping used by DockQ is recorded — a wrong
   mapping silently deflates the score. For selected chain sets with sequence-equivalent partners,
   score and retain every plausible bijection; selecting only the highest DockQ mapping does not
   satisfy this gate.

## Notes

- BSA is a property of the model alone (no reference needed) and is always computable; DockQ needs
  the deposited reference. `scripts/t16_interface_quality.py` reflects this — BSA always, DockQ
  only with `--native`. The wrapper accepts one repeated `--mapping`, `--interface-id`, and
  `--raw-json` triple per mapping, and requires typed `--subject-ref` and
  `--reference-subject-ref`; the raw JSON is retained rather than deleted. Select an exact BSA
  pair with `--chains A:B`. The current wrapper reads PDB, not mmCIF. Unless explicitly labelled
  otherwise, every BSA in harness output is the total two-sided value; a per-side value is half
  that total.
- PISA remains the `top_considered` BSA oracle (deposition-grade); biotite SASA is the runnable
  `top_performing` stand-in when the web service is unreachable.
