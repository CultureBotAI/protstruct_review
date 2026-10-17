# Quality-reporting guide correction — 2026-10-17

Base: `main` at `d06475eb378f32e948c2eca177a92aad3ca99121` (PR #905).
Task branch: `correct-quality-reporting-2026-10-17`.

The first direction in `NEXT_TASKS.md` was to correct the scientific guide before
building a reusable refinement assessment. Two read-only audits checked its
scientific sources and its agreement with the repository's catalog, criteria,
schema, emitter and retained 1SAR records. The author verified the material
findings and filed #907–#910 before implementation. The sibling-document review
subsequently found the separate registry issue #911, which remains open.

| Issue | Verified defect | Correction boundary |
|---|---|---|
| [#907](https://github.com/CultureBotAI/protstruct_review/issues/907) | Incorrect pLDDT-to-B formula and confidence treated as observed accuracy/disorder | Use PHENIX's documented empirical conversion, identify scale and units, and retain prediction provenance after coordinate changes |
| [#908](https://github.com/CultureBotAI/protstruct_review/issues/908) | Universal quality bands, equivalence/noise claims and zero-motion failure contradict scoped criteria | Explain measurements and matched-input comparisons; link registry applicability instead of introducing cutoffs |
| [#909](https://github.com/CultureBotAI/protstruct_review/issues/909) | Reduce/Probe credited with unrelated metrics, separate tool names treated as independence, unsupported literature consensus and obsolete 1SAR gap closure | Name metric-producing components, distinguish repository policy from literature, and retain claim-specific evidence gaps |
| [#910](https://github.com/CultureBotAI/protstruct_review/issues/910) | Recommended content presented as mandatory/automatic QDS behavior; site/ligand identifiers described as arbitrary text | Separate scientific recommendations, schema fields and emitter support; correct directly repeated descriptions without changing field requirements |
| [#911](https://github.com/CultureBotAI/protstruct_review/issues/911) | ProSMART Rama-Z capability in active recommendations/assumptions is not established by the cited structural-comparison scores | Separate open follow-up: verify producer/output identity and make dated, append-only registry corrections before relying on that recommendation |

The correction covers `ref/quality_reporting.md` and its directly repeated
descriptions in the evaluation skill, oracle guidance, reference index and schema. The Python
models are regenerated from the canonical schema. It does not change runtime
grading rules, threshold values, schema field requiredness, retained measurements,
or frozen EVAL/QDS records. No structural measurement or scientific tool is run.
The ProSMART registry follow-up stays open because it requires a capability audit
and versioned recommendation/assumption updates. The current change removes the
blanket capability claim from the guide and oracle prose without reinterpreting
historical scores or editing their snapshots.

## Evidence used

- [PHENIX process_predicted_model documentation](https://www.phenix-online.org/documentation/reference/process_predicted_model.html)
  defines confidence-derived error estimates and pseudo-B values.
- [Evans and Murshudov (2013)](https://journals.iucr.org/d/issues/2013/07/00/ba5190/index.html)
  discusses useful weak diffraction data beyond conventional cutoffs.
- [Williams et al. (2018)](https://pmc.ncbi.nlm.nih.gov/articles/PMC5734394/)
  identifies MolProbity components and shared cctbx infrastructure.
- [Lawson et al. (2021)](https://doi.org/10.1038/s41592-020-01051-w)
  distinguishes monitoring optimization against one map from archive-wide
  comparisons; it does not establish the old guide's universal consensus rule.
- [The threshold registry](../thresholds_and_standards.md),
  [criterion bindings](../structural_criteria.yaml), and
  [evidence ledger](../threshold_evidence_status.yaml) govern applicability and
  evidence qualifications. Agreement criteria do not grade model quality.
- [The 2026-09-23 1SAR sheet](../../data/coscientists/openscientist/QDS_1sar_cdba2c07_2026-09-23.yaml)
  retains explicit waivers for claims lacking independent support. Packaged
  round-4 coordinates cannot adjudicate the report's unretained round-7 model.
- `schemas/protstruct_review.yaml::MeasurementValue`, `PairwiseComparison`,
  and `SiteQuality`, together with `scripts/qds_emit.py`, establish exact
  selectors, optional fields, supported routing and source-supplied summaries.

## Backlog reconciliation

On 2026-10-17, the complete open queues contained twelve issues and no PRs before
publication of this branch; both counts matched separate GraphQL totals. All
bodies and comments were read. The original seven issues retained their September
dispositions; #907–#910 record this task's guide defects and #911 the separate
capability follow-up. Exact PR #905 and issue #906 checks confirmed the preceding workflow/fixture delivery
on the base commit. Local guide work remains distinct from delivered main.

The existing `reconcile-next-tasks` skill already implements the user's requested
update workflow, so a duplicate skill is unnecessary. `NEXT_TASKS.md` records that
delivery, the guide work and the next proposed before/after assessment. Its
generated threshold block and historical evidence qualifications are preserved.
No stopped campaign is restarted and no installation availability is inferred.

## Validation and independent review

A separate read-only reviewer checked the completed diff against primary sources,
current routing, schema descriptions, retained 1SAR evidence and saved GitHub queues.
That pass found a residual instance of #910 in the evaluation skill: declaring a
Site/Ligand was still said to guarantee a ligand-quality block. The actual builder
requires eligible supported measurements supplying values. The wording was corrected,
along with a stale geometry section pointer. The guide also makes clear that the
mean/count requirement is a schema reporting instruction. These fixes receive a
separate read-only follow-up before publication.

Models were regenerated with the locked `gen-pydantic` command:

```bash
uv run --locked --extra benchmark gen-pydantic schemas/protstruct_review.yaml > protstruct_review/models.py
```

The required locked Python 3.12 benchmark-extra gate, focused backlog guards,
generated-model check and whitespace check are run before commit. Their final
results and the separate read-only review are recorded with the PR. CI must pass
on both Linux and macOS for the reviewed head before any approved merge. These
checks validate repository consistency; scientific interpretation also requires
the source review described above.
