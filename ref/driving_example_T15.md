# Driving example — T15 Structural/domain classification

Standalone per-task driver for **T15 (structural/domain classification)**. Follows the structure of
`ref/driving_example.md`. T15 is oracle-only (no PHENIX classifier). Its oracle-side check reports
DSSP helix/strand content alongside **cross-tool agreement** between two independent
secondary-structure assigners. A provisional content precondition indicates whether coil/coil
calls may dominate the agreement; it is not a model-quality verdict. The historical 0.65
expectation is not a current pass/fail floor. Comparing an agent-supplied assignment with DSSP is
a separate clause.

> **Thresholds are defined once** in `ref/thresholds_and_standards.md`; the `[provenance]` tags below
> point into it. This task is **runnable now** via `scripts/t15_ss_agreement.py` (DSSP + biotite
> P-SEA).

## Scenario

The agent is handed a model (PDB/mmCIF) and asked to assign secondary structure — a three-state
(H/E/C) label per residue — and, where a classification exists, domain boundaries and a fold id. The
harness independently re-assigns secondary structure with two non-cctbx tools and scores agreement.

## Dataset — concrete IDs

- **Primary:** PDB `1AKE` (adenylate kinase, multi-domain, CATH-classified) — exercises both SS and
  domain assignment.
- **Single-domain control:** PDB `2LYZ` (hen lysozyme).
- **Demonstrated calibration:** verified RCSB download `data/pdb_mtz/1sar_deposited.pdb` A/B →
  DSSP-vs-biotite three-state agreement **166/192 = 0.8646**, with DSSP H+E content
  **75/192 = 0.3906**
  (`scripts/t15_ss_agreement.py`).

## What the agent must do

1. Assign three-state secondary structure per residue (via DSSP, or its own method, stated).
2. Where available, report domain boundaries and a CATH/SCOPe/ECOD fold id (informational).
3. If reporting an agent-vs-oracle comparison, report the secondary-structure agreement against
   DSSP as a fraction and disclose the agent's assigner.

## Independent cross-checks (harness, not agent)

- **`scripts/t15_ss_agreement.py`** runs **DSSP** (`mkdssp`, H-bond energetics) and **biotite P-SEA**
  (Cα geometry) — two non-cctbx, algorithmically distinct assigners — and reports the DSSP H+E
  content, the three-state agreement fraction, and per-residue labels. It requires a new
  repository-local `--evidence-out` JSON destination; the no-overwrite bundle retains exact
  normalized-input/raw-DSSP bytes, both assignment streams, hashes, and measured versions, and
  both measurement rows cite it.
- **CATH / SCOPe / ECOD** lookups corroborate the domain/fold labels where a deposited classification
  exists (informational).

## Scoring rubric

Report both oracle-side values informationally and use content only to qualify how much weight the
exact-denominator agreement can bear. The historical calibration has only three noisy 1UBQ
controls at the bad end and did not retain separate DSSP/biotite counts, so neither the 0.20
content precondition nor the 0.65 agreement expectation is currently gradeable. The
agent-vs-DSSP clause is evaluated separately and is unevaluable when the agent supplies no
per-residue assignment.

1. **Oracle-side content diagnostic.** Report the fraction of scored residues that DSSP assigns H
   or E. **0.20 is a provisional interpretability precondition**: below it, a high agreement may
   merely mean that both methods call everything coil, so the agreement is weakly interpretable.
   Values on either side remain informational and do not pass or fail model quality. `[benchmark]`
2. **Oracle-side two-assigner report.** Report DSSP-vs-biotite agreement only when the residue-key
   sets are identical, together with the rule 1 diagnostic. **0.65 is a provisional expectation,
   not a pass/fail floor**, until the multi-structure benchmark is rerun with separate
   per-assigner counts.
   `[benchmark — historical denominator unproven]`
3. **Agent SS vs DSSP (separate).** When the agent supplies three-state per-residue labels, they
   agree with DSSP on **≥ 0.85** of the residues DSSP assigns. When the agent supplies no such
   assignment, this clause is **unevaluable**, not a failure of the oracle-side pair.
   `[template — secondary-structure agreement]`
4. **Agreement number reproduces.** If the agent reports an agent-vs-DSSP agreement fraction, it
   matches the harness recomputation within **± 0.02**. Otherwise this clause is unevaluable.
   `[template]`
5. **Labels are informational.** Domain/fold labels carry `pass_status: informational`; they are
   recorded and cross-checked against CATH/SCOPe/ECOD but are never the sole pass criterion (the
   oracle-pair agreement is likewise informational pending exact-denominator recalibration).
   `[schema/handbook]`
6. **Assigner disclosed.** When an agent assignment is evaluated, its method is recorded — DSSP,
   STRIDE, and P-SEA disagree at loop/turn boundaries, so an undisclosed assigner makes the
   agent-vs-DSSP number uninterpretable.

## Notes

- T15's current oracle-side result is **content and exact-denominator agreement, both reported
  informationally**. Content below the provisional 0.20 precondition weakens interpretation of the
  agreement; it does not fail the model. The historical 0.65 expectation is not gradeable. Two
  independent assigners rarely hit 1.0 because H-bond and Cα-geometry methods draw helix/strand
  ends differently; conversely, an all-coil assignment can hit 1.0.
- STRIDE is the catalog-preferred second assigner but is not currently installable via Homebrew;
  biotite P-SEA is the runnable stand-in (`ref/oracle_tools.md`).
