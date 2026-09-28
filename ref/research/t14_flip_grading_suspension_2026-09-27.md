# T14 flip grading suspended — 2026-09-27 (#809)

The user approved suspension of the unsupported flip-conflict grading rule while retaining
correctly attributed historical numbers. This is an evidence/policy correction, not a new
scientific run or a recalibration of the old band.

## Producer attribution

The round48 implementation at git commit `cc36747`, `scripts/bench_t14_flip_sets.py::collect`,
assigns `a, b = flip_calls(phx), flip_calls(std)`. Its reduce2 shared set, raw disagreements and
`confident_conflicts(a, r2)` all use `a`: PHENIX-distributed Reduce, not standalone Reduce.
Today's implementation retains that producer choice; its misleading “either build” comment is
corrected without changing the experiment or relabelling the retained JSON.

The catalog places `phenix.reduce` and `mmtbx.reduce2` in the cctbx family. Their distinct
implementations do not satisfy this repository's independent-oracle requirement. In particular,
calling the historical first producer “standalone” cannot establish the missing comparison.

## Retained-data recount

Run `uv run --locked --extra benchmark -- python scripts/recount_t14_flip_history.py`.
It ignores the stored summary, sums the per-model records and verifies the retained disagreement
list lengths. Across 41 protein entries (12CI is the named excluded member of the 42-entry set):

- Confident conflicts: 56 / 3105 = 1.8035426731%.
- Raw disagreements: 340 / 3105 = 10.9500805153%.
- PHENIX/standalone shared residues: 3101, with 4 PHENIX-only and 1 standalone-only residues;
  the retained rows report 2 flip-decision disagreements. The builders cannot be interchanged
  without changing the evidence.
- The named cohort's largest absolute H-count gap is 3MIU, 6.7796610169%, computed from integer
  H counts. The registry's older 3.96% figure belongs to the retired 17-model report, not this
  cohort. Neither is a bound for the corrected dictionary-loaded pipeline (#799).

This recount authenticates arithmetic in the committed record, not the original execution inputs,
logs or tool builds. Missing full historical residue-decision vectors prevent reconstructing a
replacement standalone-versus-reduce2 benchmark from these aggregates alone.

## Current policy and preserved history

Every current flip-conflict measurement is informational and criterion-free, including cohort
aggregates and nested interpretation metadata. Keep exact source identity, numerator, eligible
shared-residue denominator and cohort/structure scope. The former cohort band supplies no pass
or fail pending a matched independent benchmark. The H-count and clashscore clauses retain their
separate applicability conditions; #798's clashscore version pins do not reopen flip grading.

The dated recommendation supersedes, rather than edits, its predecessor. Historical research
records receive clearly dated corrections. Raw benchmark JSON, issued Eval/QDS carriers and
frozen emitter contracts are unchanged. Current authoring must inspect the correction-projected
active evidence, so withdrawing an old graded row does not block its corrective sheet. Direct
retained-contract replay remains historical replay, not a new-authoring route.

The old 18/2 registry inventory is explicitly historical. Its complete ledger/count reconciliation
remains #766; the T15 denominator rerun remains #765. Dictionary-loaded measurements and causal
clashscore decomposition remain #799/#790. No such rerun is claimed completed here.

## Regression evidence

The producer regression uses deliberately different PHENIX and standalone residue maps. Changing
the three reduce2 comparison operands from the PHENIX map to the standalone map in memory makes
the test fail at its shared-residue count assertion (one assertion failure, zero setup errors).
The committed function is not rewritten for this negative control. The recount regression ignores
the stored summary and rejects a mutated count/list pair; neither test executes a scientific tool.

Independent review found stale live-script independence/grading language and an unqualified Applied
block in the older cited report (#824). The live docstrings/comments now describe informational,
same-family historical comparisons; the older report has a visible dated suspension banner without
rewriting its numerical history.

The review also filed #826 for the difference between public correction projection and raw corpus
admission. Further verification refuted its claimed historical-publication blocker: an
ignored-inclusive repository YAML inventory found only three actual candidate/conflict measurements,
September 7 M009, M010 and M016, all informational and criterion-free. The synthetic withdrawn grade
was never an admissible source: it invents a binding and a cctbx hard pass. Public active-projection
tests do not override raw source checks. No broad withdrawal exception or pass-status relaxation is
introduced; frozen replay and valid informational history remain unchanged.
