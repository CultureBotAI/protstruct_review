# Coding standards — protstruct_review

<!-- catalog-state: tasks=T01–T17; count=17; drivers=17 -->

Repo-specific rules a reviewer can cite as **hard violations**, not judgement calls. These are
the invariants of *this* harness — they sit on top of, and override, the generic code-smell
baseline any review already carries. Generic style (naming, dead code, error handling) is not
repeated here; only what is particular to this project is.

The authority for domain conventions is `/protstruct-eval` (`.claude/skills/protstruct-eval/SKILL.md`).
Where this file and the handbook overlap, they must agree; if they drift, that is itself a defect.

## Trust model (load-bearing — never violate)

1. **No PHENIX-grades-PHENIX.** Every gradeable task must be cross-checked by at least one
   independent, non-cctbx oracle (MolProbity, ChimeraX, REFMAC/Servalcat, gemmi, DSSP, DockQ, …).
   A task whose only oracle is another PHENIX/cctbx tool is a violation — add an external oracle
   or state explicitly in the row that none exists.
2. **The deposition is the tiebreaker**, not either tool: a deposited PDB/EMDB entry or a
   publication Table 1 breaks a cross-tool disagreement.
3. **Every quantitative claim is re-measured, never transcribed** from the agent under evaluation.
   If a number in a QDS narrative cannot be traced to a re-run oracle measurement, it does not
   belong there.

## Catalog and its views

4. **`ref/catalog.yaml` is canonical.** `ref/tasks_and_evaluations.tsv` and `.md` are *views*.
5. **The TSV is generated — never hand-edit it.** Regenerate:
   `python3 scripts/records_to_tsv.py ref/catalog.yaml --kind catalog -o ref/tasks_and_evaluations.tsv`.
   It must match a fresh regeneration byte-for-byte (`scripts/validate.sh` enforces this).
6. **The `.md` is hand-written prose**, but every catalog task must have a `### T<NN> ` section in
   it (also enforced by `validate.sh`). Update it in the *same commit* as the catalog change.
7. **Example datasets are concrete deposition IDs** (`1AKE`, `EMDB-11668`), never "any
   high-resolution structure" or "deposited entries with curated mappings". A run must be
   reproducible without a scavenger hunt.

## Metrics

8. **Every task needs at least one gradeable metric, and gradeable means numeric** — a number two
   tools can disagree about. No "good fit", no bare pass/fail prose as the sole metric.
9. **Label-valued metrics** (a secondary-structure state, a CATH id, a CAPRI class) are allowed
   only as *descriptive content*: they carry `pass_status: informational` and ride alongside a
   numeric metric, never instead of one. The idiom for grading categorical data is to score the
   *agreement between two independent labellers* as a number
   (e.g. `T15_secondary_structure_agreement` = three-state DSSP-vs-STRIDE concordance).
10. **Pass thresholds live only in `ref/thresholds_and_standards.md`** — the catalog defines metric
    shape, and the per-task `driving_example_T<NN>.md` files for T01–T17 cite and contextualize the
    registry rather than defining or restating numeric values. Every threshold carries an approved
    `[provenance]` tag, and a new threshold without admissible provenance is not admissible.
    **Negative-control clause:** the §6 verdict thresholds are re-derived from committed
    round records by `scripts/bench_recover_leg.py`, so there the registry *restates* the
    record-derived constants and validate 3b (`check_negative_control_records.py`) asserts the
    restatement is exact — the record is the source, the registry the human-readable copy.
    The guard's own table of governed values (`ref/thresholds_and_standards.yaml`: read-pattern,
    consumers, retired literals) is guard data, not a definition; a threshold's value still lives
    only in the `.md` row the pattern reads.

## QDS emitter (`scripts/qds_emit.py`)

11. **One routing table.** A single `METRIC_TO_QDS_SLOT` maps every metric id to its destination.
    Never add a second table. A metric that must land in more than one block uses a **list** of
    `(block, slot)` pairs as its value — not a parallel mapping.
12. **Route by canonical metric id, never by substring.** The table is validated against
    `ref/catalog.yaml` at import; a typo must be a hard error, not a silent miss.
13. **Fail-hard on implied content.** If an eval carries content that implies a QDS block, the
    emitter must emit that block or raise `QdsCompletenessError` (which subclasses `SystemExit` by
    design — preserve that). Adding a metric at a new `scope` means adding its implied-block rule.
13b. **Fail-hard on cctbx-only coverage (#315).** Each gradeable metric/context claim whose
    cross-tool coverage is cctbx-only or unclassifiable refuses to emit unless the eval declares a
    matching `CrossToolWaiver` (task + metric/context qualifiers, reason, date); a legacy task-only
    waiver is accepted only when exactly one claim for that task is gated. The waiver annotates
    only the coverage row it excuses.
    Non-cctbx-only coverage is deliberately NOT gated — the rule forbids self-grading, not
    independent-only evidence. Committed QDS files are checked by
    `scripts/check_qds_trust_invariant.py` (validate step 3c), which rebuilds coverage from the
    named source EvaluationRuns. Modern source documents pin the relevant `Structure`, `Tool`,
    `tool_recommendations`, and `assumptions` snapshots plus a source-owned `qds_replay_pins`
    boundary; the QDS pins an append-only emitter contract version. The guard replays the whole
    sheet through that retained implementation, independently canonicalizes it, and verifies the
    source/output SHA-256 pins without consulting today's live registries. Historical exceptions
    are frozen by exact repository path, QDS id, issue timestamp, and full-file SHA-256; a date
    alone never grants an exemption. Live selection and the retained-contract preflight reject
    equal-priority rows whose criterion binding/preconditions, agent-claim/delta lineage, or
    assumptions differ, and reject QDS lineage/verdict fields smuggled inside source value carriers.
    This source-owned preflight protects retained v1/v2 artifacts without changing their frozen
    output shape.
13c. **A verdict must name an applicable, registry-grounded criterion (#567, #588).** A
    `pass_status` that asserts an outcome — `pass`, `fail_criterion`, `fail_by_oracle`,
    `pass_with_caveat`, `pass_criterion_fail_headline`, `fail_by_oracle_within_cctbx` — requires
    both a numeric-comparison `pass_criterion` and a `pass_criterion_ref`. The reference resolves in
    `ref/structural_criteria.yaml::pass_criterion_bindings`, whose exact metric and structured
    task/stage/scope/tool/family applicability, effective date, canonical catalog unit, and
    metric↔task/tool↔task links must match the row. A binding selects one complete normalized table
    cell by section, first-cell row label, and one-based column; that cell must contain exactly one
    strict positive-polarity comparison (`pass(es)`, `fail(s/ure)`, or `outlier`, followed by
    `if`/`when`). The binding declares the operand and transform, and the guard recomputes the result
    with exact decimal arithmetic; a delta must equal unit-compatible `oracle_measure - agent_claim`.
    The row's status must agree with that result. The registry's dedicated Provenance/Source cell
    must contain an approved tag. Bindings never copy threshold values into the catalog or create a
    second threshold source.

    Every load-bearing applicability condition must be encoded in the selected cell's literal
    `[requires: id,...]` annotation. The binding lists exactly those ids, and the measurement carries
    each once in evidence-backed `criterion_preconditions[]`. A verdict requires every check to be
    `satisfied`; `criterion_inapplicable` retains the authoritative criterion/ref and requires at
    least one required check to be `void` or `unknown`. `informational` means "reported without a
    declared criterion" and carries none of `pass_criterion`, `pass_criterion_ref`, or
    `criterion_preconditions`. The four disagreement statuses (`fail_by_oracle`,
    `fail_by_oracle_within_cctbx`, `pass_with_caveat`, and `pass_criterion_fail_headline`) require a
    finite numeric, unit-compatible agent claim that differs from the oracle. A plain `pass` or
    `fail_criterion` cannot retain a contradictory asserted claim. Gradeable source carriers set
    exactly one of numeric, text, or true-not-applicable, and cannot contain nested QDS lineage or
    verdict fields. Text-only disagreement cannot support a numeric verdict.

    `fail_by_oracle_within_cctbx` is the sole criterion-bearing status allowed on a cctbx-only row;
    a hard pass/failure belongs on an independently remeasured non-cctbx row. A criterion recorded
    only in `notes`, nonnumeric prose, a placeholder (`n/a`, `TBD`, or a status name), or text absent
    from its cited registry cell is not a criterion. Rows in one run with identical structured
    scientific context, values, criterion binding/preconditions, assumptions, and retained evidence
    must not assign different statuses; list ordering and duplicates do not make evidence different,
    and free-text `notes` alone cannot justify a different verdict. Looser metric/tool groupings remain
    unsafe because different subjects and values can legitimately pass and fail the same rule.
    Committed records are checked by `scripts/check_pass_status.py` (validate step 3c-bis).
    Pre-registry history is preserved, not validated, only by explicit path plus exact file/row
    SHA-256; a date never grants an exemption, mutation makes an exemption stale, and scientific
    corrections require a new dated record rather than rewriting an immutable source/QDS pair.
    Binding versions use inclusive effective intervals and an immediate-predecessor, same-context,
    append-only supersession chain; overlapping or partly changed temporal contexts fail. A canonical
    EVAL filename date must equal `EvaluationRun.run_date`. Duplicate YAML keys, statusless criterion
    metadata, and malformed status, criterion, schema, binding, carrier, or record shapes fail with
    contextual diagnostics.
13d. **A QDS scalar keeps its measurement context.** Newly emitted summary values carry the source
    EvaluationRun and MeasurementValue ids, canonical metric, subject, stage/scope/selector,
    oracle tool and family, `pass_status`, criterion, and notes. Frozen contracts do not inline newer
    binding/precondition fields; consumers resolve `source_measurement_ref` for that complete source
    context, and retained-contract preflight prevents ambiguous source collapse. `subject_ref` identifies the
    concrete model or dataset; do not overload `scope_selector` with provenance prose. When a QDS
    names a subject, explicit non-matching measurements are ineligible and legacy unlabelled rows
    are fallback-only. A multi-subject input without an explicit QDS subject fails hard.
13e. **Coupled summary values come from one code path.** In particular, R-work, R-free, and their
    gap must be selected as a coherent bundle from one evaluation run, subject, tool, and oracle
    family. Never choose those slots independently or synthesize a triple across Gemmi, REFMAC,
    Servalcat, or cctbx results. If no coherent bundle covers the available slots, emission fails.
14. **Behaviour-preserving refactors must be proven so.** After touching the emitter, regenerate a
    committed QDS and diff it: only `issued_at` may differ.

## Schema

15. **`schemas/protstruct_review.yaml` is the source; `protstruct_review/models.py` is generated**
    (`gen-pydantic`). Regenerate and commit the models in the same commit as any schema change —
    never hand-edit the models.
16. The single-file schema is past its ~600-line split guideline **by design** while there is one
    consumer and no subset reader; see `schemas/README.md`. Do not split it speculatively — the
    trigger is a *second consumer*, not the line count.

## Serialisation and scripts

17. **Emit YAML with `yaml.safe_dump` on a data structure**, never by appending f-string lines. Use
    `sort_keys=False` (field order is meaningful — these files are read by humans) and
    `allow_unicode=True` (units like `Å`, `Å²` must not become escape sequences). Hand-rendered
    YAML bypasses the LinkML validator and invites quoting bugs.
18. **Shell gates must fail loudly.** Under `set -euo pipefail`, a crash inside a `< <(...)`
    process substitution is *not* caught. Capture a subprocess's output into a variable with an
    explicit status check *before* consuming it, so an enumeration failure aborts rather than
    yielding an empty list that passes silently.
19. **Scripts derive `REPO_ROOT` from their own location** (`__file__` / `BASH_SOURCE`), never a
    hardcoded absolute path. No `/Users/...` in any `.py`, `.sh`, schema, or doc.
19b. **Benchmark tool execution is shell-free.** Pass paths and arguments as a list through
    `scripts/toolchain.py`; use `cwd` and log file handles for redirection. Only the audited CCP4
    adapter may source a vendor setup script. PHENIX, CCP4, TM-align, DSSP, probe, and reduce paths
    and pinned versions are defined once in that module and overridden only with `PROTSTRUCT_*`
    environment variables.

## The gate

20. **`bash scripts/validate.sh` must be green before commit.** It runs LinkML validation of every
    record, referential integrity, the emitter regression tests, and the published-view drift
    check. A change that needs the gate relaxed needs the gate *fixed*, not bypassed.
