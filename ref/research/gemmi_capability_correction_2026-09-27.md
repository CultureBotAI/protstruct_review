# Capability-specific Gemmi recommendations — 2026-09-27 (#785)

The seven recommendations that attributed geometry or overall-B measurements to `gemmi validate`
were not a runnable measurement contract. Replacing every occurrence with `gemmi rmsz` would also
be wrong: a real command does not establish equivalence to every advertised metric.

## Evidence and decisions

The source inspected is the pinned Gemmi 0.7.5
[rmsz command](https://raw.githubusercontent.com/project-gemmi/gemmi/v0.7.5/prog/rmsz.cpp)
and [topology implementation](https://raw.githubusercontent.com/project-gemmi/gemmi/v0.7.5/include/gemmi/topo.hpp).
The configured installed Gemmi 0.7.5 command's `rmsz --help` also exits successfully. That capability
probe is not a model measurement or a cross-tool benchmark.

| Metric context | Current recommendation |
|---|---|
| T03 bond/angle RMSD | Use separate bond rmsD in Å and angle rmsD in degrees, not one mixed-unit scalar or rmsZ. |
| T05 bond-length RMSD | Use bond rmsD with the registry's bond-count and library conditions. |
| T05 bond-angle RMSD | Use angle rmsD with restraint-population and library provenance. |
| T05 chirality | Qualified alternative for wrong-handed centres, preserving the checked-centre denominator; not general chiral-volume outliers. |
| T05 planarity RMSD | Deprecate the unsupported recommendation: Gemmi's statistic aggregates maximum atom deviation per plane, with no established equivalence to this catalog metric. |
| T02 paired omega flips | Deprecate: single-model torsion-restraint deviations are not matched-residue cis/trans changes between models. |
| T06 overall B | Deprecate: the intended statistic and validated producer remain undefined; neither mean atomic B nor Wilson B can be silently substituted. |

The `gemmi rmsz` Tool serves T03/T05 only. The old Tool identity and all seven original dated
recommendations remain unchanged for historical snapshots. Seven timestamped successors record
three supported replacements, one qualified alternative and three deprecations. The current T06
oracle list no longer advertises the unsupported command. The catalog's prose and generated TSV
are changed together.

This is a capability correction, not new wrappers, threshold calibration, scientific measurements
or a claim that every metric now has an implemented independent oracle. The deliberately deprecated
recommendations expose those remaining capability gaps rather than asserting nonexistent support.

## Validation and review

Focused tests check schema/link integrity, exact predecessor preservation, timestamp-boundary
selection in live and retained implementations, deprecation in recommendation snapshots, required
capability qualifiers and generated-view equality. They include mutations that remove each required
qualifier or alter the declared tool/role. The review must also examine the actual scientific
capabilities; passing text-contract tests alone cannot prove them.

The first complete gate found #825: the new test imported the generated package without placing
the repository root on its import path. A focused run with `PYTHONPATH=.` had masked that failure.
The correction derives the root from `__file__`, matching existing schema tests; the gate is not
relaxed and no environment override is required. Direct and foreign-working-directory invocations
with `PYTHONPATH` unset must both pass before rerunning the full gate.

Independent capability review found no defect in the seven successor mappings, but identified
pre-existing contradictory units in the current T05 driver and oracle guide (#827): both labelled
the whole rmsD line Å. Those two lines now distinguish distance and angular fields, and a regression
requires the correct units. No historical result or comparison tolerance changes.

The full locked benchmark-extra hermetic gate and independent read-only review are required before
commit/merge. Raw measurements, issued Eval/QDS files and retained emitter implementations are
outside this change.
