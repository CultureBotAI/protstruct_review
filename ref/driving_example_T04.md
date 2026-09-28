# Driving example — T04 Real-space refinement (map-based)

Standalone per-task driver for **T04 (real-space refinement against a map)**. Follows the structure of
`ref/driving_example.md`. Graded by **cross-tool agreement**: an independent map-model correlation and
FSC from Servalcat must corroborate the agent's PHENIX real-space refinement.

> **Thresholds are defined once** in `ref/thresholds_and_standards.md`; the `[provenance]` tags below
> point into it.

## Scenario

The agent is handed a starting model + a cryo-EM map + a resolution estimate and asked to refine in
real space and report map-model fit (CC_mask, d_FSC_model) and post-refinement geometry.

## Dataset — concrete IDs

- **Primary:** EMDB-`11668` / PDB `7a4m` (apoferritin, 1.22 Å — fast, high-res).
- **Second:** EMDB-`20646` / PDB `6u42`.

## What the agent must do

1. Run `phenix.real_space_refine model.pdb map.mrc resolution=<d>`.
2. Record CC_mask, CC_box, CC_peaks, CC_volume, d_FSC_model, ΔCC vs input, clashscore, Ramachandran.
3. Expected artefacts: refined PDB, `.log`, `.geo`.

## Independent cross-checks (harness, not agent)

- **Servalcat** (`fsc`, `localcc`) — independent model-map FSC and correlation (Murshudov-group code
  path, non-cctbx).
- **MolProbity standalone** — independent geometry after refinement.

## Scoring rubric

Each bullet is pass/fail; all must pass for green.

1. **Map-model fit did not degrade.** CC_mask_post ≥ CC_mask_pre − **0.04** (`d_min < 3.0 Å`) or
   **0.06** (`d_min ≥ 3.0 Å`); d_FSC_model_post ≤ d_FSC_model_pre **× 1.05** (relative, one-sided).
   `[registry §4 — map-model]`
2. **Cross-tool CC agreement.** PHENIX CC_mask and Servalcat CC on the same refined model agree within
   **± 0.02** (both correlate model against the same map; a larger gap means different masking).
   `[template]`
3. **Model-map FSC = 0.5 convention.** d_FSC_model is the resolution at which model-map FSC crosses
   **0.5**; both tools must use the same crossing, or the numbers are not comparable.
   `[literature — model-map FSC 0.5]`
4. **Geometry did not degrade.** clashscore / Ramachandran within the refinement Δ-tolerances (§4);
   MolProbity vs PHENIX clashscore agree within the registry §3 envelope — |Δ| ≤ 1.0, or 20 % of
   the mean, whichever is larger, with a matched H-build convention and hydrogens from the same
   `reduce` binary and version (a mismatch is void, not failed; record each tool's H convention and
   `reduce` version). `[registry §3 — clashscore]`

## Notes

- Real-space refinement can inflate map-model CC while degrading geometry (over-fitting into noise);
  rules 1 and 4 must both hold, so a CC gain bought with new clashes fails.
