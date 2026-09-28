# T05 classification-floor adoption — 2026-09-27 (#786)

## Decision and scope

The user approved adoption of round46's preregistered classification floor in both registry §3
Ramachandran/rotamer rows. The numeric floor is defined in
[`thresholds_and_standards.md`](../thresholds_and_standards.md), not repeated as a new definition here.
The favored row applies it to three-state Ramachandran verdict agreement; the outlier row applies
it separately to three-state Ramachandran and binary rotamer OUTLIER/non-OUTLIER agreement.

Applicability is the declared PHENIX 2.0-5936 `phenix.ramalyze`/`phenix.rotalyze` comparison with
the wwPDB validation report on the same coordinate subject, using shared
`(chain, resnum, icode, resname)` keys. Each measure has its own nonzero shared-key denominator;
counts and every differing key/verdict must be retained. Do not pool models or the two measures.
A missing applicable comparison is unevaluable, not a pass. Other PHENIX versions and standalone
MolProbity are outside this adoption. This checks reproduction of a deposited reference, not
method independence: both pipelines are MolProbity-derived.

This is a documentary adoption, not a new executable grading path. No catalog agreement metric,
PassCriterionBinding, emitter change or graded QDS is added. The current binding registry remains
empty. QDS classification-agreement rows therefore remain informational without criterion metadata until an
appropriate separately reviewed machine-readable metric and contextual binding exist. The unmeasured
rotamer-favored-percent clause is unchanged; this adoption does not calibrate or resolve it.

## Read-only recount of retained evidence

Sources: [preregistration](tolerance_benchmark_round46_preregistration.md),
[result record](tolerance_benchmark_round46.md), and
[retained JSON](data/round46_vs_deposited.json). No tool was rerun and no historical source was edited.

The JSON contains 42 rows: 41 protein entries with positive shared counts for both comparisons,
and 12CI with both counts zero and no agreement value. Zero is not an agreement denominator.
Independent integer recount:

| Retained quantity | Recount | Interpretation |
|---|---|---|
| Ramachandran matching/shared keys | 46,677 / 46,677 | Each of the 41 entries agrees completely |
| Exact rotamer-name matching/shared keys | 38,741 / 38,744 | A distinct, finer-grained diagnostic |
| 15C8 exact rotamer-name matching/shared keys | 368 / 371 | Fraction 0.9919137466, displayed as 0.9919 |
| 15C8 Ramachandran matching/shared keys | 426 / 426 | Not the rotamer denominator |
| Rotamer name differences whose OUTLIER verdict differs | 0 / 38,744 shared keys | Reconstructed under the retained producer's OUTLIER-name convention |

All three name differences occur on 15C8: H/52A PRO (`t0` vs `Cg_exo`), H/82A SER
(`mt` vs `p`), and H/82B SER (`mt` vs `m`). The JSON records local PHENIX `Favored`
for each, while the report supplies a non-OUTLIER rotamer name. It does **not** retain a report-side
Favored/Allowed verdict, so “both Favored” is stronger than this JSON establishes. These differences
do not lower binary OUTLIER/non-OUTLIER agreement. The result record's 0.9919 minimum describes exact
name agreement, not the adopted binary rotamer classification measure.

The complete retained disagreement list length equals shared minus same-name count for every entry.
The binary recount uses that list and the producer's convention that an outlier name is literally
`OUTLIER` (`scripts/bench_vs_deposited.py::rotamer_agreement`). It is a reconstruction from
summarized producer output, not a fresh audit of all underlying XML/log verdicts. Likewise, the
version is declared by preregistration/result prose; the JSON does not authenticate executable
versions. Altlocs are not another key field in this retained comparison. Report the actual key
handling and shared counts; do not equate them with all separately scored altlocs or all model residues.

Historical records and figures are preserved, including the result record's correction of the
earlier insertion-code collision. New applicability uses the corrected four-part key, not the
obsolete three-part description still present in historical prose. Use integer numerator/denominator
ratios for comparisons, not a rounded display fraction.

## Guard and remaining work

Review correction #830 was filed before amending the initial scratch proposal: appending a current
classification floor behind the old percentage-leading text left the reader's first apparent rule
unchanged. Each Tolerance cell now opens with the complete current floor and applicability. Old
percentage paragraphs are explicitly historical diagnostics, while the retained, unresolved
rotamer-favored exception is separately labeled. The obsolete present-tense claim that the band
question “is #284” is removed. Guard regressions require the floor at the **start** of each cell;
merely containing it later fails. No historical research record, numerical observation or scientific
execution result is rewritten by this presentation correction.

Two governed-sidecar entries read the floor from each canonical registry row and require its exact
version, subject, key, denominator, scope and documentary-adoption limitations. The T05 driver cites
the registry floor without copying its numeric value. Hermetic regressions exercise both floor and
applicability mutations, actual retained JSON counts, the insertion-code parser, exact-name versus
OUTLIER classification, zero denominators, and the unchanged machine-binding boundary.

The pending #766 descriptive ledger needs a separate integration update after this patch:
`favored_percent/shared_classification` and `outlier_percent/shared_classification` move from
`policy_unresolved` to `active_conditional`, while their retained-record evidence states remain.
Their limitations must carry the adopted version/pair scope and lack of QDS authorization; their
registry fingerprints and evidence references must be refreshed. The rotamer-favored component
stays unresolved. Do not silently apply the old #766 row fingerprints or count this adoption as
new independent calibration.
