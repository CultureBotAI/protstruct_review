# Corrected synthetic active-site fixture — 2026-09-23

## Scope and issue priority

Branch `synthetic-active-site-correction-2026-09-23` starts from main
`44e43444faebf6a42f1eca3b36908c9aae4cbede` (PR #726). The preceding full-queue
review and live-path repair are recorded in
`density_t13_adversarial_review_2026-09-23.md`.

After #726, the 11 remaining open issues were #580, #585, #591, #610,
#691–#695, #725 and #727. The next priority was #691: active regression tests
still taught incorrect scientific provenance and residue scope. The necessary
registry preparation exposed #727; independent review then filed #728 and #729
before their fixes. Final standards review filed #730 for the omitted hand-written
catalog view. This branch addresses those five issues, plus the synthetic-fixture
portion of #591. It does not resolve April 1SAR's historical ion/ice rows, so
#591 remains open. The larger dated real-record correction still depends on
#610/#725 and covers #580/#585/#692–#695.

## Corrected fixture and derivation

New sources and output:

- `data/examples/eval/EVAL_synth_active_site_2026-09-23.yaml`
- `data/examples/qds/QDS_synth_active_site_2026-09-23.yaml`

These contain invented rendering-test values, not a new scientific run. The
source and standalone QDS headline say so. The context explicitly limits the
sheet to selected T01/T05/T10 fields; it does not claim complete task coverage.

The intended scoring roles are now OpenStructure for lDDT, edstats for RSCC,
and standalone MolProbity/probe for ligand hydrogen bonds. TM-align remains
the alignment/TM-score/RMSD tool, not an lDDT scorer. Reciprocal catalog links
were added for these existing tools and metrics; the TSV was regenerated.
The fictional molecular ligand is ATP at A201, avoiding a hydrogen-bond count
attributed to the old monatomic calcium fixture.

The site, array and scalar selector all name exactly A33/A34/A35/A36/A38:

```text
invented residue values: .91, .88, .93, .79, .95
arithmetic mean:         .892
population SD:          .056
minimum / maximum:      .79 / .95
count:                  5
```

The population-SD convention is explicit; the old .062 was neither the exact
population SD nor the sample SD (.06260990337). The illustrative whole-pair
lDDT is separately labelled and is not this five-residue arithmetic mean.
The current emitter retains the full residue array; it does not populate an
additional site-level mean-lDDT scalar. The correctly typed M_006 summary
remains in the source and is arithmetically checked by the test.

All six scalar rows are informational, with no invented agent claims or
unregistered cutoff. Pairwise similarity is described as preservation, not
directional quality improvement. The partial contract-3 emission context and
source-owned tool/recommendation/assumption snapshots are pinned, including
predecessors needed to validate supersession chains. Live emission and frozen
contract-3 replay produce the same canonical QDS bytes.

## Registry correction and independent review

Preparation found that `ASSUM_molprobity_h_atom_placement` and
`REC_T05_clashscore_top_performing` still attributed the historical 1SAR
3.13/3.63 gap to different H builds. #727 adds dated successors, preserving
both predecessors and their old replay behavior.

Independent review round 1 found a defect in that proposed fix (#728): it
replaced the old attribution with an equally unsupported counting-only
mechanism. `scripts/bench_t05_clashscore_h.py:149–156` supplies the original
no-H input to phenix.clashscore but builds another H model for standalone
probe. No identical-H-coordinate/dictionary check isolates counting. The
retained flip-set benchmark also documents different hetero dictionaries and
ligand-H construction. The new registry rows and active skill now report the
observed matched-convention pipeline residual while leaving its causal
decomposition unresolved. No old scientific artifact was rewritten and no
new oracle measurement is claimed.

The reviewer also verified that no pre-existing registry row was changed or
deleted, that the dated successors activate at 06:55:50 UTC (not one second
earlier), and that the new catalog links are reciprocal. The new fixture's
snapshots were refreshed after #728; all snapshot rows match their live
registry source exactly.

Independent review round 2 found #729: the invented rotamer annotation and
current registry/skill equated not-favored with OUTLIER, omitting the Allowed
category documented in `scripts/bench_vs_deposited.py:78–80` and the retained
round-7 benchmark. A dated assumption successor preserves that distinction and
the residue-specific joint torsion score; the fictional annotation now explicitly
invents the classification without an angular-offset rationale. The predecessor
remains frozen. The source snapshot, emitted QDS, replay pin and regression
assertions were updated together.

Independent review round 3 found no new code/data blocker. The reviewer
recomputed all six replay digests and the residue statistics, checked canonical
live/replay equality and exact registry snapshots, tested inclusive activation
times for all three superseders, and verified byte-identical April artifacts.
The reviewer ran focused checks only, not the full gate or scientific tools.

The final standards check found #730: the generated TSV was current, but the
hand-written task view omitted the new metric-specific oracle roles. Its T01/T10
sections were updated in this same catalog-change branch, as rule 6 requires.
Independent round-4 delta review found no new code/scientific blocker and
confirmed unchanged QDS/replay bytes and frozen April artifacts.

A fresh full-queue read on September 23, before #730 was filed, confirmed 13 open issues, matching the
GitHub total, and no open PRs before this branch's submission. GitHub main was
still `44e43444faebf6a42f1eca3b36908c9aae4cbede`. Dispositions are:

| Priority | Issues | Disposition and dependency |
| --- | --- | --- |
| P1 | #691, #727–#729 | Fixed on this unmerged branch; closure requires merge and passing review/gate. |
| P2 | #730 | Filed after that queue snapshot (bringing the total to 14); task-view synchronization fixed on this branch. |
| P1 | #610, #725 | Next implementation: typed all-evidence correction and dataset/model admission. |
| P1 | #585, #692–#695 | Remaining historical scientific/standalone defects; dated correction depends on #610. #694's live paths are fixed by #726. |
| P1 | #591 | Enum/live generator fixed; synthetic portion on this branch, frozen ion/ice rows await correction. |
| P2 | #580 | Grading harm mitigated; saved raw output unavailable in prior ignore-inclusive audit. Needs durable typed unavailable-evidence treatment or a licensed rerun, not invented evidence. |

The next actions are to merge this tested fixture, implement #610/#725, then
publish the dated 1SAR correction. These are code reproduction and synthetic
fixture checks, not new scientific tool execution. No issue is considered fixed
on main merely because its patch exists here.

## Historical boundary and checks

The April synthetic Eval/QDS pair remains byte-identical to main. Active local
block/emission tests now select the September fixture. An ignore-inclusive
search outside `data/` found remaining old-fixture references only in named
historical/exemption guards and their tests.

One obsolete task-only RI exception was removed for the *synthetic* April
M_004: MolProbity now legitimately serves T10 hydrogen-bond counting. This
does not validate that old row's false MolProbity/RSCC attribution. Other
historical integrity/status exceptions remain exact and unchanged.

Focused verification passed: the full emitter regression suite, independent
canonical replay, QDS trust, referential integrity, source Container schema,
pass-status, Ruff, and `git diff --check`. The post-#729 full hermetic gate passed
with exit 0. After the #730 view synchronization, the full gate was rerun and
again exited 0 with `All checks passed!` before commit. No scientific oracle
execution was performed by this branch.
