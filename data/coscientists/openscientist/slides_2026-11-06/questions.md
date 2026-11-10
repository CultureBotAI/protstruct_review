# User-Input Questions and Decisions for `slides_2026-11-06`

Every `[USER INPUT: Q<N> ...]` placeholder in `slides.md` (and referenced in `outline.md`) marks an open project-framing or presentation-scope decision (`Q1`, `Q2`, `Q4`) that cannot be derived from committed repository records at `f3cfad326f28ddbf652dcdb0c5858443bee6e413`. Question `Q3` has been decided by the user and implemented on `Slide S06` and `Slide S24`. All experimental numbers, distributions, and provenance findings are supplied from committed repository sources.

---

## `Q1` — Intended Relationship to "Agentifying PHENIX"
- **Status**: `OPEN`
- **Referenced on**: `Slide S02` (`S02-role-in-agentifying-phenix`), `Slide S24` (`S24-project-choices-set-next-step`)
- **Placeholder tag**: `[USER INPUT: Q1]`
- **Context**: `AGENTS.md:3-15` defines `protstruct_review` as a quality-assessment harness for agent-refined or generated protein structures with two scientific goals (assessing protein refinement results on actual structures and understanding the landscape of macromolecular structure tools and measurements), and `ref/quality_reporting.md:19-36` defines how agreement, suitability, and improvement are separated. The committed repository does not implement or specify an upstream autonomous agent or controller architecture around `PHENIX`.
- **Question for user**:
  1. How should Slide `S02` frame the relationship between `protstruct_review` and "agentifying PHENIX"?
     - **Option A**: Present `protstruct_review` strictly as the downstream verification and measurement harness (`assess_refinement.py`, `qds_emit.py`, `ref/catalog.yaml`, `ref/structural_criteria.yaml`) that evaluates candidate structures produced by external agent workflows.
     - **Option B**: Describe a planned upstream co-scientist / tool-calling `PHENIX` loop that will call `protstruct_review` for before-and-after evidence, explicitly labeled as future/external architecture rather than implemented repository code.
     - **Option C**: Supply a project-specific program diagram or statement defining the broader "agentifying PHENIX" initiative.

---

## `Q2` — Target Audience, Talk Duration, and Technical Emphasis
- **Status**: `OPEN`
- **Referenced on**: `Slide S02` (`S02-role-in-agentifying-phenix`), `Slide S24` (`S24-project-choices-set-next-step`)
- **Placeholder tag**: `[USER INPUT: Q2]`
- **Context**: The 39-slide package covers motivation and verification principles (`Section 1`), harness development, measurement context, and the `S09a`/`S09f`/`S09b` threshold-discovery triplet (`Section 2`), the extreme-resolution control evaluation set (`Section 3`, including the `S13a`/`S13`/`S13b` triplet), empirical distributions and `1SAR`/`ProSMART` audits (`Section 4`, including triplets `S14a`–`S18b` and `S19`–`S21`), and synthesis/next steps (`Section 5`).
- **Question for user**:
  1. Who is the primary audience for this presentation (e.g., `PHENIX`/structural-biology developers, AI/co-scientist researchers, or program-review stakeholders)?
  2. What is the target live talk slot (e.g., 15–20 minute talk, 30–45 minute technical seminar, or read-ahead deck), and which sections or case-study slides (`S19`–`S21`) should receive primary live emphasis versus backup/appendix treatment?

---

## `Q3` — Definition of "Geometry Models" Scope (`A/B/C` Configurations + Broader Documented Taxonomy)
- **Status**: `DECIDED` (`2026-11-06`)
- **Implemented on**: `Slide S06` (`S06-three-geometry-configurations`), `Slide S24` (`S24-project-choices-set-next-step`)
- **Decision summary**:
  - `Slide S06` presents three larger top panels (`A: PHENIX CDL`, `B: PHENIX E&H`, and `C: Gemmi rmsz / CCP4 Monomer Library`), each carrying its own `Benchmarked · 17 models` badge from `ref/research/tolerance_benchmark_restraint_library.md:15-32,109-118`, above three smaller documented taxonomy category panels from `ref/catalog.yaml` (`phenix.amber` force-field restraints in `T03`; `phenix.eLBOW` and `CCP4 libcheck`/`AceDRG` ligand restraint generators in `T10`; `reduce`, `phenix.ready_set`, and `Schrödinger PrepWizard` protonation conventions in `T14`), each carrying its own `not yet benchmarked` badge scoped specifically to this 17-model `A/B/C` comparison.
  - Separate metadata-only installation-presence provenance is recorded in `ref/research/geometry_tool_presence_2026-11-06.json`.

---

## `Q4` — Priority Scientific or Engineering Next Step to Highlight on the Closing Slide
- **Status**: `OPEN`
- **Referenced on**: `Slide S24` (`S24-project-choices-set-next-step`)
- **Placeholder tag**: `[USER INPUT: Q4]`
- **Context**: Slide `S23` (`S23-retained-gaps-define-next-evidence`) summarizes source-established evidence gaps from committed repository files without pre-committing to new runs or a priority order:
  - **(a)** Admitting reviewed contextual `PassCriterionBinding` entries in `ref/structural_criteria.yaml:13-17` (`scripts/assess_refinement.py:24-28`) and machine-checkable shared-key classification metrics (`ref/research/t05_classification_floor_adoption_2026-09-27.md:19-23`).
  - **(b)** Recovering or regenerating missing `1SAR` Round-7 coordinates, a second-dictionary `RMSZ` check, and raw historical evaluator outputs/effective denominators (`ref/research/refinement_assessment_case_study_2026-10-18.md:51,59-72`), or recording single-factor recovery ablations with retained absolute `R-work`/`R-free` endpoints (`lines 158-166`).
  - **(c)** Diffing per-bond restraint lists across the `11/17` unequal-bond-count models (`ref/research/tolerance_benchmark_bond_rmsd.md:104-105`), or addressing the `T15` exact-denominator recalibration (`ref/threshold_evidence_status.yaml:360-377`, open issue `#765`) and `T14` flip-grading policy scope (`ref/threshold_evidence_status.yaml:567-575`).
- **Question for user**:
  1. Which of these source-established evidence tracks should Slide `S24` highlight as the top near-term priority for the project?
