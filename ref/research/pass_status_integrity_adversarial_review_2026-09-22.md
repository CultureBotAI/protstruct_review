# Pass-status integrity adversarial review — 2026-09-22

## Scope and method

This record documents the independent review and remediation performed after
`qds-integrity-1sar-2026-09-21` merged as PR #613. The working branch is
`pass-status-integrity-2026-09-22`, based on main after PRs #689 and #690. The
review covered the complete pass-status, QDS-selection, YAML-loading, catalog,
and referential-integrity path; it also re-read the immutable Eval/QDS sources
whose defects the new policy must preserve without endorsing.

Repository-absence checks used `rg -uu --hidden`, so ignored files were included
(with `.git` and `.venv` excluded where their contents were irrelevant). No
PHENIX, CCP4, gemmi, or other scientific measurement program was run.

## Findings and disposition

| Issue | Finding | Disposition in this branch |
|---|---|---|
| #588 | A nonblank criterion could be unrelated, unevaluable, or numerically inconsistent with the row. | Fixed with registry-grounded bindings, exact applicability, typed operands, and recomputed outcomes. |
| #589 | Individually valid rows could assign opposite statuses to identical scientific evidence. | Fixed with a complete structured R5 signature; prose notes are not verdict context. |
| #590 | Date-based grandfathering was backdatable. | Fixed with canonical-root, exact-path, full-file, and parsed-row SHA-256 pins; unused pins fail. |
| #593, #594, #598, #599, #600 | Malformed scalar/schema handling, reporting, and documentation defects in the original guard. | Fixed and regression-tested. |
| #691 | The frozen synthetic Eval/QDS assigns lDDT, RSCC, and H-bond quantities to incompatible tools/metrics and has inconsistent residue scope. | Not rewritten. A new dated correction remains required. |
| #692 | The April ProSMART row stores Procrustes displacement as RSRZ, applies an unregistered cutoff, and overclaims Ramachandran confirmation without retained output. | Not rewritten. A new dated correction remains required. |
| #693 | April ion rows label a local heuristic as canonical CheckMyMetal and overstate Ca identity using wrong-protein biology. | Not rewritten. A new dated correction remains required. |
| #694 | Active T10 guidance and historical sheets use fixed RSCC/RSR bars forbidden by the threshold registry. | Active guidance and new-dated correction remain follow-up work. |
| #695 | Pairwise lDDT similarity is encoded as directional improvement. | A new-dated correction remains required. |
| #696 | The first R5 signature was order-sensitive and let reordered or duplicated nested evidence evade comparison. | Fixed by recursive set normalization/deduplication; notes are ignored. |
| #697 | QDS equal-priority selection omitted authoritative binding and precondition context. | Fixed in live selection and the retained-contract preflight without changing frozen output shapes. |
| #698 | Binding edits could retroactively re-grade history or overlap another rule. | Fixed with inclusive effective intervals and linear immediate-predecessor supersession. |
| #699 | Nested typed-value carriers could smuggle QDS verdict/lineage authority. | Fixed by rejecting source nesting and copying only scalar/statistical fields. |
| #700 | Standard YAML loading silently accepted duplicate mapping keys. | Fixed with one duplicate-rejecting safe loader across Eval/QDS, registry, trust, RI, and emission inputs. |
| #701 | Duplicate catalog ids and one-way task links made binding applicability ambiguous. | Fixed; three duplicate Tool rows were removed and bidirectional binding links are checked. |
| #702 | Corpus RI resolved ids but did not prove metric/task or tool applicability. | Fixed with source-snapshot-first/catalog-fallback semantic checks and exact content pins for immutable defects. |
| #703 | A criterion precondition could cite itself, its carrier, a future run, an invented token, or a URL. | Fixed by requiring distinct retained repository evidence or a uniquely resolving strictly earlier EvaluationRun. Both run-id and carrier-path representations are checked. |
| #704 | Load-bearing preconditions were unenforced and there was no honest inapplicable status. | Fixed with exact `[requires: ...]` bindings, typed checks, and `criterion_inapplicable`. |

The last independent fuzz pass found three additional bypass classes inside the
first remediation and they were fixed before merge:

1. Repeating the same numbered threshold H2 let a later impostor section supply
   the bound row. A referenced section must now have exactly one canonical
   numbered heading.
2. Table-like lines inside fenced code, HTML comments, or indented code were
   treated as rendered threshold tables. Non-rendered Markdown contexts are now
   excluded.
3. Future/circular precondition evidence was initially date-checked only for an
   `EVAL_*` id. A carrier pathname, or a valid EvaluationRun id with another
   prefix, bypassed chronology. RI now resolves both representations before
   applying the same strictly-earlier rule.

## Implemented authority model

1. Threshold values remain defined only in
   `ref/thresholds_and_standards.md`. A `PassCriterionBinding` stores no copied
   cutoff. It selects one complete rendered registry cell by numbered section,
   exact first-cell row label, and one-based column.
2. The selected cell must contain exactly one supported positive-polarity
   numeric comparison and an approved tag in a dedicated Provenance/Source
   cell. The binding declares operand, transform, canonical unit, task, stage,
   scope, tool, family, and effective interval. The display snapshot must equal
   the selected cell after presentation-only normalization.
3. The guard recomputes pass/fail with exact decimal arithmetic. A delta operand
   must equal the unit-compatible `oracle_measure - agent_claim`; unresolved
   cross-row deltas cannot grade a standalone verdict.
4. Every load-bearing condition is named in the selected cell as
   `[requires: id,...]`, exactly mirrored by the binding and the row's structured
   preconditions. Verdicts require all checks satisfied. An inapplicable verdict
   requires at least one required check to be `void` or `unknown`, with retained
   evidence. Informational rows carry no criterion metadata.
5. All four disagreement statuses require a finite numeric, unit-compatible
   inequality. Plain `pass` and `fail_criterion` cannot retain a contradictory or
   incomparable asserted claim. Hard criterion-bearing verdicts cannot be placed
   on a cctbx row; the same-family tentative status remains distinct.
6. Binding versions use inclusive intervals, identical atomic context, and one
   append-only immediate-predecessor chain. The canonical Eval filename date
   must equal `run_date`.
7. QDS ambiguity detection includes binding, preconditions, agent/delta lineage,
   evidence, and assumptions. The retained-contract preflight enforces the same
   source distinction while preserving frozen v1/v2 output layouts.

## Historical-record decision

The review rejected an early attempt to rewrite legacy statuses. Some proposed
replacement grades were themselves scientifically unsound, and changing a dated
Eval without regenerating its immutable derivative would leave source and QDS in
conflict. The two affected source Evals therefore remain byte-identical to main:

- April 1SAR Eval: `b3beb751fb99c94376002d88ccb7f8716b1dd4ae8177c40ff53b29ab12350532`
- Synthetic active-site Eval: `624435778056f93eea841f9062ce76a6dc78513f4361fc0e2ab6b6264dd6919e`

The guard reports 26 explicit pass-status exceptions: two full-file pins for
pre-binding criteria and 24 exact row pins for known R2/R3 defects. RI has
one exact metric/task pin and 38 exact tool/task pins where frozen rows conflict
with current catalog applicability. These exceptions preserve unvalidated
history; they do not certify the claims. Issues #580, #585, #591, #610, #665,
and #691–#695 remain open for scientific reruns, standalone/correction
semantics, or new dated records.

## Verification

- `scripts/test_pass_status.py`: 589 checks passed.
- `scripts/test_qds_emit.py`: all emitter regressions passed.
- `scripts/test_check_qds_trust.py`: 87 checks passed.
- `scripts/test_guards.py`: 329 checks passed.
- `scripts/check_referential_integrity.py`: all references resolved.
- The committed 2026-09-21 QDS was independently replayed through frozen
  emitter contract 1 with its pinned source snapshot and issue timestamp; both
  the parsed object and serialized bytes exactly matched the committed artifact.
- `git diff --check` and Python compilation passed.
- `PYTHON=.venv/bin/python bash scripts/validate.sh`: full repository gate
  passed (`All checks passed!`; Ruff correctness checks passed).
- `.venv/bin/python scripts/test_bench_tolerances.py`: 241 checks passed.
