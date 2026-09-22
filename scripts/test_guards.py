#!/usr/bin/env python3
"""Unit tests for the two scripts that exist to catch other scripts' mistakes.

`check_registry_figures.py` and `check_referential_integrity.py` are guards. This
repo's own triage ranks "a guard that does not guard" second only to a wrong published
claim, because a guard with a hole hides the whole class beneath it -- and both of
these had one:

  #116  `nesting_check()` compared four counts it derived ITSELF from the TSV and never
        read the registry. Those inclusions hold by construction of `append_results`,
        so no run of the pipeline could fail them; meanwhile the registry's 59, 35 and
        63 were pinned to no literal at all.
  #118  the docstring promised a `structure_ref` check that was never implemented --
        `local_structure_ids` sat computed and unused -- so a dangling structure_ref
        passed silently through the gate that exists to catch dangling refs.

Every test below must FAIL if its fix is reverted; a test that passes either way is
the same defect one level up. No network, no PHENIX; safe to run anywhere.
"""
from __future__ import annotations

import copy
from contextlib import redirect_stderr
from dataclasses import replace
import importlib.util
import io
import sys
import tempfile
from pathlib import Path

import qds_emit as current_qds_emitter

REPO = Path(__file__).resolve().parent.parent
PASSED = 0


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def check(label: str, got, want) -> None:
    global PASSED
    if got != want:
        print(f"FAIL  {label}: got {got!r}, want {want!r}")
        sys.exit(1)
    PASSED += 1
    print(f"PASS  {label} (got {got!r})")


figures = load("check_registry_figures")
integrity = load("check_referential_integrity")

REGISTRY_TEXT = (REPO / figures.REGISTRY).read_text()
ROWS = figures.load(REPO / figures.TSV)


def statuses(registry: str, rows=None) -> dict[str, str]:
    return {r["check"]: r["status"] for r in figures.run(registry, rows or ROWS)}


# --- check_registry_figures: the live registry is the baseline --------------------

_live = statuses(REGISTRY_TEXT)
check("every registry figure matches the data as committed",
      sorted({v for v in _live.values()}), ["OK"])
check("the nested denominators are among the figures checked",
      all(k in _live for k in ["refinement-attempt count", "full pre/post count",
                               "refinement attempts incl. LOST", "stated counts nest"]),
      True)


# --- #116: a figure that drifts while the ordering survives must be caught --------
# This is the precise case the old check passed: 69 >= 61 >= 58 >= 35 still nests, so
# nothing fired, while the registry's stated 59 had become wrong.

_drift = REGISTRY_TEXT.replace("of which **59** reached a refinement attempt",
                               "of which **61** reached a refinement attempt")
check("a drifted attempt count is caught even though the ordering still nests",
      statuses(_drift)["refinement-attempt count"] != "OK", True)
check("and the ordering check alone would NOT have caught it",
      statuses(_drift)["stated counts nest"], "OK")

_measured = REGISTRY_TEXT.replace("**35** have full pre/post values",
                                  "**34** have full pre/post values")
check("a drifted pre/post count is caught", statuses(_measured)["full pre/post count"] != "OK", True)

_lost = REGISTRY_TEXT.replace("(**63** entries reached a refinement attempt in total",
                              "(**64** entries reached a refinement attempt in total")
check("so is the LOST-inclusive attempt count",
      statuses(_lost)["refinement attempts incl. LOST"] != "OK", True)


# --- #115, restated: the relationship must be checked in the PROSE ----------------

_broken = REGISTRY_TEXT.replace("of which **59** reached a refinement attempt",
                                "of which **70** reached a refinement attempt")
check("a stated relationship that does not nest is BROKEN",
      statuses(_broken)["stated counts nest"], "BROKEN")

_reworded = REGISTRY_TEXT.replace("of which **59** reached a refinement attempt, ",
                                  "of these, **59** were attempted; ")
check("rewording the sentence goes MISSING rather than silently passing",
      statuses(_reworded)["stated counts nest"], "MISSING")


# --- the data side, for completeness ----------------------------------------------

check("the five denominators derive from the file as the registry states them",
      [len(figures._named(ROWS)), len(figures._attempted(ROWS)),
       len(figures._with_delta(ROWS)), len(figures._measured(ROWS)),
       len(figures._attempted_incl_lost(ROWS))],
      [69, 59, 58, 35, 63])
check("`screened only` rows are outside every one of them",
      any(r["status"].startswith("screened only") for r in figures._named(ROWS)), False)


# --- #118: structure_ref resolves, or it is reported ------------------------------

_eval = {"evaluation_runs": [{
    "id": "EVAL_x", "structure_ref": "1sar",
    "ligands": [{"id": "1sar:A:CA98", "structure_ref": "1sar"}],
}]}
check("a record whose nested structure_refs agree is clean",
      integrity.check_structure_refs(_eval, Path("EVAL_x.yaml"), set()), [])

_typo = {"evaluation_runs": [{
    "id": "EVAL_x", "structure_ref": "1sar",
    "ligands": [{"id": "1sar:A:CA98", "structure_ref": "1srn"}],
}]}
_v = integrity.check_structure_refs(_typo, Path("EVAL_x.yaml"), set())
check("a nested structure_ref naming a different structure is a violation", len(_v), 1)
check("and the message locates it", "ligands[0].structure_ref" in _v[0], True)

check("with a declared structure index, refs resolve against it instead",
      len(integrity.check_structure_refs(_typo, Path("EVAL_x.yaml"), {"1sar", "1srn"})), 0)
check("and an unknown id fails against that index",
      len(integrity.check_structure_refs(_typo, Path("EVAL_x.yaml"), {"1sar"})), 1)

# The committed records must pass the check that was just switched on -- a new guard
# that fails on the existing corpus is a guard nobody will keep.
_real = sorted((REPO / "data").rglob("EVAL_*.yaml")) + sorted((REPO / "data").rglob("QDS_*.yaml"))
check("the committed records satisfy it", _real != [], True)
for _p in _real:
    import yaml
    _doc = yaml.safe_load(_p.read_text())
    check(f"  {_p.relative_to(REPO)}",
          integrity.check_structure_refs(_doc, _p.relative_to(REPO), set()), [])

_source_measurement = {
    "id": "M_snapshot",
    "metric_definition_ref": "T06_r-free",
    "oracle_tool_ref": "gemmi validate",
    "oracle_family": "non_cctbx",
    "oracle_measure": {"value_numeric": 0.2},
}
_wrapped = integrity._expected_wrapped_measurement(
    _source_measurement,
    "EVAL_snapshot",
    (("gemmi validate", "non_cctbx"),),
)
check(
    "wrapped lineage uses the source-pinned Tool family",
    _wrapped["oracle_family"],
    "non_cctbx",
)


# --- Measurement catalog semantics are relationships, not isolated ids -----------
def _measurement_catalog_semantic_violations(row, tools=None, metrics=None):
    doc = {
        "tools": tools or [],
        "metric_definitions": metrics or [],
        "evaluation_runs": [{"id": "EVAL_catalog_semantics", "measurements": [row]}],
    }
    index = integrity.build_corpus_indices([(Path("catalog-semantics.yaml"), doc)])
    return integrity.check_measurement_catalog_semantics(index)


_catalog_semantic_row = {
    "id": "CATALOG_SEMANTICS_M_001",
    "catalog_task_ref": "T06",
    "metric_definition_ref": "T06_r-free",
    "oracle_tool_ref": "gemmi validate",
    "oracle_family": "non_cctbx",
    "oracle_measure": {"value_numeric": 0.2, "unit": "fraction"},
}
check("a MeasurementValue matching both catalog relationships is clean",
      _measurement_catalog_semantic_violations(_catalog_semantic_row), [])
check("an unrelated source Tool snapshot preserves per-tool catalog fallback",
      _measurement_catalog_semantic_violations(
          _catalog_semantic_row,
          tools=[{
              "id": "unrelated historical oracle",
              "family": "cctbx",
              "catalog_tasks_served": ["T03"],
          }]), [])

_wrong_metric_task = copy.deepcopy(_catalog_semantic_row)
_wrong_metric_task["catalog_task_ref"] = "T05"
_violations = _measurement_catalog_semantic_violations(_wrong_metric_task)
check("a resolved metric cannot be used under an undeclared task",
      any("applicable only to catalog tasks" in violation
          for violation in _violations), True)
check("the metric/task diagnostic names both ids",
      any("T06_r-free" in violation and "T05" in violation
          for violation in _violations), True)

_wrong_oracle_family = copy.deepcopy(_catalog_semantic_row)
_wrong_oracle_family["oracle_family"] = "cctbx"
_violations = _measurement_catalog_semantic_violations(_wrong_oracle_family)
check("a resolved oracle tool cannot claim the wrong family",
      any("does not match authoritative family" in violation
          for violation in _violations), True)
check("an omitted oracle family is also incoherent with a known tool",
      any("oracle_family None" in violation for violation in
          _measurement_catalog_semantic_violations({
              key: value for key, value in _catalog_semantic_row.items()
              if key != "oracle_family"
          })), True)

_source_pinned_tool = [{
    "id": "local historical oracle",
    "family": "cctbx",
    "catalog_tasks_served": ["T06"],
}]
_source_pinned_row = {
    **_catalog_semantic_row,
    "id": "CATALOG_SEMANTICS_M_002",
    "oracle_tool_ref": "local historical oracle",
    "oracle_family": "cctbx",
}
check("a source-owned Tool declaration supplies the authoritative family",
      _measurement_catalog_semantic_violations(
          _source_pinned_row, _source_pinned_tool), [])
_wrong_source_pinned_family = copy.deepcopy(_source_pinned_row)
_wrong_source_pinned_family["oracle_family"] = "non_cctbx"
check("source-owned Tool family mismatches are rejected",
      any("authoritative family 'cctbx'" in violation for violation in
          _measurement_catalog_semantic_violations(
              _wrong_source_pinned_family, _source_pinned_tool)), True)

_wrong_catalog_tool_task = {
    **_catalog_semantic_row,
    "id": "CATALOG_SEMANTICS_M_TOOL_TASK",
    "catalog_task_ref": "T03",
    "metric_definition_ref": "T03_r-free",
}
_violations = _measurement_catalog_semantic_violations(_wrong_catalog_tool_task)
check("catalog fallback rejects a tool outside its declared task set",
      any("serves only catalog tasks ['T06']" in violation
          for violation in _violations), True)
check("the tool/task diagnostic names the tool and row task",
      any("gemmi validate" in violation and "T03" in violation
          for violation in _violations), True)

_repinned_catalog_tool = [{
    "id": "gemmi validate",
    "family": "non_cctbx",
    "catalog_tasks_served": ["T03"],
}]
check("a source Tool snapshot overrides live catalog task applicability",
      _measurement_catalog_semantic_violations(
          _wrong_catalog_tool_task, tools=_repinned_catalog_tool), [])
check("a source Tool snapshot cannot fall through to a broader live task set",
      any("serves only catalog tasks ['T03']" in violation for violation in
          _measurement_catalog_semantic_violations(
              _catalog_semantic_row, tools=_repinned_catalog_tool)), True)

_empty_task_snapshot = [{
    "id": "gemmi validate",
    "family": "non_cctbx",
    "catalog_tasks_served": [],
}]
check("an explicit empty source Tool task set remains authoritative",
      any("serves only catalog tasks []" in violation for violation in
          _measurement_catalog_semantic_violations(
              _catalog_semantic_row, tools=_empty_task_snapshot)), True)

_source_pinned_metric = [{
    "id": "local_historical_metric",
    "applicable_task_refs": ["T03"],
}]
_source_pinned_metric_row = {
    **_catalog_semantic_row,
    "id": "CATALOG_SEMANTICS_M_003",
    "catalog_task_ref": "T03",
    "metric_definition_ref": "local_historical_metric",
    "oracle_tool_ref": "REFMAC5 (CCP4)",
}
check("a source-owned MetricDefinition supplies task applicability",
      _measurement_catalog_semantic_violations(
          _source_pinned_metric_row, metrics=_source_pinned_metric), [])
_wrong_source_metric_task = copy.deepcopy(_source_pinned_metric_row)
_wrong_source_metric_task["catalog_task_ref"] = "T05"
check("source-owned MetricDefinition task mismatches are rejected",
      any("applicable only to catalog tasks ['T03']" in violation
          for violation in _measurement_catalog_semantic_violations(
              _wrong_source_metric_task, metrics=_source_pinned_metric)), True)


# --- Round 26: the status vocabulary is declared, not inferred from predicates -----
# Before #139 the vocabulary existed only as prefixes spread across four predicates in
# the READER, while the WRITER that produces the values lived in another file -- the
# shape of #136. 28 of the 97 rows matched none of those prefixes and were counted as
# `attempted` by DEFAULT (`not startswith("skipped")`), which happened to be right for
# them and would not be for the next status added.

check("every committed status matches the declared vocabulary",
      figures.vocabulary_check(ROWS)["status"], "OK")

_drifted = copy.deepcopy(ROWS)
_drifted.append({**_drifted[0], "pdb_id": "9XXX", "cc_mask_delta": "",
                 "status": "failed: real_space_refine timeout"})
check("an undeclared status is reported, not absorbed",
      figures.vocabulary_check(_drifted)["status"], "UNDECLARED")
check("and it would otherwise have joined `attempted` silently",
      len(figures._attempted(_drifted)) - len(figures._attempted(ROWS)), 1)

# The case the guard really exists for: a typo in an EXISTING status. This moves a
# published denominator by 10 entries.
_typo = copy.deepcopy(ROWS)
for _r in _typo:
    _r["status"] = _r["status"].replace("skipped:", "skip:", 1)
check("a typo in a known status is caught", figures.vocabulary_check(_typo)["status"],
      "UNDECLARED")
check("and it moves `attempted` by 10", len(figures._attempted(_typo)), 69)

# Scope, stated rather than implied: the registry literals ALSO go STALE on that typo.
# They are not redundant with each other -- the registry check blames the REGISTRY
# ("registry says 59, data gives 69"), which invites correcting a figure that is right,
# i.e. #113's failure mode. The vocabulary check names the cause. It also covers counts
# the registry does not pin, where nothing else would fire at all.
_reg_statuses = {r["check"]: r["status"] for r in figures.run(REGISTRY_TEXT, _typo)}
check("the registry check fires too, but blames the registry",
      _reg_statuses["refinement-attempt count"], "STALE")

# The vocabulary is imported from the writer, never re-declared here.
_prefixes, _is_known = figures._status_vocabulary()
check("the vocabulary comes from the script that writes the file", sorted(_prefixes),
      ["LOST: ", "d_FSC only (", "delta-only (", "measured", "screened only (", "skipped: "])

# #148: a bare `startswith` absorbed anything sharing a prefix with a declared status,
# so `measured-partially` passed as known and then joined `attempted` by default --
# the very hazard this vocabulary exists to close. Matching now requires the delimiter
# a payload-carrying status actually uses, and `measured` matches exactly.
for _s in ["measured", "skipped: reason", "LOST: id never recorded",
           "screened only (round 23): x", "delta-only (y)", "d_FSC only (z)"]:
    check(f"  declared status accepted: {_s[:24]!r}", _is_known(_s), True)
for _s in ["measured-partially", "measured_v2", "LOSTISH", "screened only later", ""]:
    check(f"  undeclared look-alike rejected: {_s[:24]!r}", _is_known(_s), False)
check("and a look-alike is reported by the vocabulary check, not absorbed",
      figures.vocabulary_check(
          [{**ROWS[0], "status": "measured-partially"}])["status"], "UNDECLARED")


# --- Round 26: a round document's claims about its own findings ------------------
# #130 ("three high" when four were) and #135 ("a 20-file audit round" that was 19)
# were both caught by review, not by a check, and both flattered the round. The rule
# -- every quoted figure comes from a committed, re-runnable script -- had never been
# applied to a round document's claims about ITSELF.

def _raises_keyerror(figures):
    try:
        figures._status_is({"status": "x"}, "nonsense")
    except KeyError:
        return True
    return False


roundfig = load("check_round_figures")
FINDINGS = roundfig.load(roundfig.RECORD)
ROUND25_DOC = Path(roundfig.ROUND25).read_text()

def _round_statuses(doc):
    return {r["check"]: r["status"] for r in roundfig.run(doc, FINDINGS)}

check("round 25's document matches its findings record",
      sorted({v for v in _round_statuses(ROUND25_DOC).values()}), ["OK"])

# Each mutation must fire, or the check above passes for the wrong reason.
check("the exact #130 miscount is caught",
      _round_statuses(ROUND25_DOC.replace("Four high (#116, #117, #118, #127).",
                                          "Three high (#116, #117, #118)."))
      ["pass-1 high count"], "MISSING")
check("a wrong per-issue severity is caught",
      _round_statuses(ROUND25_DOC.replace("**#136 (high)", "**#136 (medium)"))
      ["severity of #136"], "STALE")
check("a citation of an issue that does not exist is caught",
      _round_statuses(ROUND25_DOC.replace("**#130 (medium)", "**#999 (medium)"))
      ["severity of #999"], "MISSING")
check("and rewording a covered claim does not silently pass",
      _round_statuses(ROUND25_DOC.replace("Twelve defects, filed as #116–#127.",
                                          "A dozen defects were filed."))
      ["pass-1 finding count"], "MISSING")

# The severity parse is anchored to the start of a line. Unanchored it took the first
# match anywhere, and #130's body OPENS by quoting the label it reports on -- so the
# record read `high` for an issue declaring `medium`. That is #121's shape.
check("a severity quoted mid-sentence is not mistaken for the declaration",
      roundfig.severity_of(
          "Four of the twelve are labelled `**Severity: high**`:\n\n"
          "**Severity: medium** (a wrong published count)."), "medium")
check("an issue with no severity line is recorded as unstated, not defaulted",
      roundfig.severity_of("no severity here"), "unstated")

# #149, three defects in this gate, each verified by running it.
# 1. A FENCED block sits at column 0 too, so the line anchor alone did not stop an
#    issue that quotes another issue's severity from reporting the quoted value.
check("a severity inside a fenced block is not mistaken for the declaration",
      roundfig.severity_of("quoting:\n\n```\n**Severity: high**\n```\n\n**Severity: low**\n"),
      "low")
# 2. A citation the regex did not anticipate produced NO result item -- unchecked and
#    unmentioned. Anything claim-shaped is now reported.
check("a mis-capitalised citation is checked, not dropped",
      [r["status"] for r in roundfig.severity_claims("**#130 (High)** x", FINDINGS)],
      ["STALE"])
check("an unrecognised severity word is reported rather than ignored",
      [r["status"] for r in roundfig.severity_claims("**#130 (bogus)** x", FINDINGS)],
      ["UNRECOGNISED"])
check("and UNRECOGNISED is a failure, unlike UNCHECKABLE",
      roundfig.severity_claims("**#130 (bogus)** x", FINDINGS)[0]["status"]
      not in ("OK", "UNCHECKABLE"), True)
# 3. An empty pass-1 subset reported a traceback instead of a diagnostic.
check("an empty record reports instead of raising",
      "re-run --refresh" in roundfig.round25_checks([])[0][2], True)
# A quoted counter-example is not a claim, whatever formatting it carries. #144 fixed
# the un-bolded case by requiring bold; this round then quoted a BOLDED example inside
# backticks and the gate reported it. Code formatting is the discriminator, not bold.
check("a claim quoted inside backticks is not checked as a claim",
      roundfig.severity_claims("the regex missed (`**#130 (High)**`) entirely", FINDINGS), [])
check("nor one inside a fenced block",
      roundfig.severity_claims("example:\n\n```\n**#130 (high)**\n```\n", FINDINGS), [])
check("while a claim in running prose still is",
      [r["status"] for r in roundfig.severity_claims("**#130 (medium)** — a real claim", FINDINGS)],
      ["OK"])

# The record must not contain pull requests. `gh issue view <n>` resolves a PR number
# happily, so a numeric range pulled #128 and #129 in as `unstated`.
check("no pull requests in the findings record",
      [r["issue"] for r in FINDINGS if r["issue"] in {"128", "129"}], [])
# The `**Severity:` convention starts at #116. The record now spans back to #87 so it
# covers every issue the round documents cite, and those older ones legitimately have no
# machine-readable severity -- reported as UNCHECKABLE rather than failed (#144's lesson:
# a guard that fires on correct input gets ignored).
check("every issue from #116 on carries a stated severity",
      [r["issue"] for r in FINDINGS
       if int(r["issue"]) >= 116 and r["severity"] == "unstated"], [])
check("and the unstated ones are all older than the convention",
      max(int(r["issue"]) for r in FINDINGS if r["severity"] == "unstated") < 116, True)
check("a claim against a pre-convention issue is UNCHECKABLE, not a failure",
      [r["status"] for r in roundfig.severity_claims("**#87 (medium)** something", FINDINGS)],
      ["UNCHECKABLE"])
# Not `assert True`: actually run the entrypoint and confirm it exits 0 while genuine
# UNCHECKABLE rows are present, which is the behaviour the status exists for.
import contextlib as _ctx, io as _io
_buf, _err = _io.StringIO(), _io.StringIO()
with _ctx.redirect_stdout(_buf), _ctx.redirect_stderr(_err):
    _rc = roundfig.main()
check("the gate exits 0 despite UNCHECKABLE rows", _rc, 0)
check("and says how many it could not check",
      "predate the severity convention" in _buf.getvalue(), True)
check("with at least one genuinely present",
      sum(1 for r in roundfig.run_all(roundfig.REPO, FINDINGS)
          if r["status"] == "UNCHECKABLE") > 0, True)


# --- Round 26: a vocabulary believed schema-enforced, and enforced on one class ---
# #142: two documents asserted `oracle_family` was a required schema enum -- issue #125
# ("a required enum in the schema") and round 26's own pass-4 audit, which listed the
# vocabulary as already closed and therefore never checked it. It was declared on
# `Finding` only. `MeasurementValue` and `HeadlineFinding` carried it bare, and
# `qds_emit` reads `measurements`, whose range is MeasurementValue -- so every value
# feeding build_cross_tool_coverage() and _strongest() was unconstrained.
#
# Parsed from the schema text rather than run through linkml-validate, so this test
# needs no linkml install and runs anywhere.

import yaml as _yaml
_schema = _yaml.safe_load((REPO / "schemas/protstruct_review.yaml").read_text())
_families = {
    f"{cls}.{slot}": attrs.get("range")
    for cls, body in _schema.get("classes", {}).items()
    for slot, attrs in (body.get("attributes") or {}).items()
    if slot == "oracle_family"
}
check("every class declaring oracle_family constrains it to ToolFamily",
      sorted(k for k, v in _families.items() if v != "ToolFamily"), [])
check("all oracle_family-bearing classes are covered",
      sorted(_families),
      ["Finding.oracle_family", "HeadlineFinding.oracle_family",
       "MeasurementValue.oracle_family", "TypedMeasurementValue.oracle_family"])
check("the enum itself still admits exactly the two families",
      sorted(_schema["enums"]["ToolFamily"]["permissible_values"]), ["cctbx", "non_cctbx"])


# --- Round 26, pass 6: the partitions an input-space enumeration found -------------
# #151/#152. Every prior fix here was tested against the construct that motivated it
# and failed the next one -- inline backticks, then fenced blocks, then bold-inside-
# backticks, then ~~~. So this block is a partition MAP, not a regression test for one
# case, and the two false NEGATIVES matter most: a gate that declines to look is worse
# than one that complains.

_D = ROUND25_DOC  # a real document, for the cases that need one

# False negatives -- the gate must still SEE these.
check("a stray backtick does not delete a later real claim",
      [r["status"] for r in roundfig.severity_claims(
          "stray ` here. The claim **#136 (medium)** is WRONG, then `end`.", FINDINGS)],
      ["STALE"])
check("a quoted literal does not satisfy a check the prose contradicts",
      [r["status"] for r in roundfig.run(
          "Eleven defects, filed as #116-126.\n\n```\nTwelve defects, filed as #116–#127.\n```\n",
          FINDINGS)][:1],
      ["MISSING"])

# Quotation, by every fence and span style these documents actually use.
check("a ~~~ fenced severity is a quotation, not a declaration",
      roundfig.severity_of("q:\n\n~~~\n**Severity: high**\n~~~\n\n**Severity: low**\n"), "low")
check("an unclosed fence does not leak its contents",
      roundfig.severity_of("q:\n\n```\n**Severity: high**\n"), "unstated")
for _label, _doc in [
        ("backtick-wrapped", "the regex missed (`**#130 (High)**`) entirely"),
        ("fenced", "example:\n\n```\n**#130 (high)**\n```\n"),
        ("indented", "shown as:\n\n    **#136 (medium)**\n\nnot a claim."),
        ("blockquoted", "> **#136 (medium)** quoted from elsewhere")]:
    check(f"  quotation ignored: {_label}", roundfig.severity_claims(_doc, FINDINGS), [])
check("while a claim in running prose is still checked",
      [r["status"] for r in roundfig.severity_claims("**#130 (medium)** — a real claim", FINDINGS)],
      ["OK"])

# #152: the denominators classify via the declared vocabulary, not their own prefixes.
import copy as _copy
_bad = _copy.deepcopy(ROWS)
_bad.append({**_bad[0], "pdb_id": "9XXX", "status": "skipped-early: still counts",
             "cc_mask_delta": ""})
check("an undeclared look-alike is not absorbed as a real skip",
      len(figures._attempted(_bad)) - len(figures._attempted(ROWS)), 1)
check("and the published denominators are unchanged by the rewrite",
      [len(f(ROWS)) for f in (figures._named, figures._attempted, figures._with_delta,
                              figures._measured, figures._attempted_incl_lost)],
      [69, 59, 58, 35, 63])
check("the denominator predicates reject an undeclared token outright",
      _raises_keyerror(figures), True)

# #153: an AMBIGUOUS token used to resolve by dict order. No two declared statuses share
# a prefix today, so this constructs the case a future round would create.
_saved_vocab = figures._VOCAB
try:
    figures._VOCAB = dict(_saved_vocab)
    figures._VOCAB["skipped-early: "] = ("prefix", "a future status")
    _ambiguous = False
    try:
        figures._status_is({"status": "skipped-early: x"}, "skipped")
    except KeyError as _e:
        _ambiguous = "matches 2 declared statuses" in str(_e)
    check("an ambiguous status token fails rather than picking one", _ambiguous, True)
finally:
    figures._VOCAB = _saved_vocab
check("and the real vocabulary has no ambiguous token today",
      [tok for tok in ("measured", "skipped", "screened only")
       if len([d for d in figures._VOCAB if d.startswith(tok)]) != 1], [])


# --- #189: round_figures must not count a pull request as an issue ------------------
# scripts/round_figures.py is a helper, not a gate, so it is not run by validate.sh --
# but the RULE it depends on is shared with check_round_figures.issue_numbers, and that
# sharing is what this pins. Writing the fallback without reusing that rule made the
# tool report 3 issues for a range holding 2, counting its own PR: the exact defect
# (#155) the --issues flag exists to prevent, laundered as derived output.

rf = load("round_figures")
check("round_figures reuses the sibling's issue rule rather than copying it",
      "_real_issue_numbers" in (REPO / "scripts" / "round_figures.py").read_text(), True)
check("and that rule is check_round_figures.issue_numbers",
      "check_round_figures.py" in (REPO / "scripts" / "round_figures.py").read_text(), True)

# The rule itself, exercised offline: the findings record -- which issue_numbers is the
# live counterpart of -- contains no pull-request number. #128/#129/#141 are PRs whose
# numbers sit inside the record's range, so their absence is the property that matters.
_record_ids = {r["issue"] for r in FINDINGS}
_prs_in_range = {"128", "129", "141", "154", "159", "168", "175", "178", "181"}
check("no pull-request number appears in the findings record",
      sorted(_record_ids & _prs_in_range), [])
check("while issues bracketing them do", 
      {"127", "130"} <= _record_ids, True)


# --- #605: cross-document provenance refs resolve to one concrete object ----------
# LinkML checks that these slots are strings, but not that the named run/measurement/
# assumption exists. The guard must build one corpus index: resolving each file in
# isolation is exactly how a dangling QDS source reference used to pass.

_old_doc = {"evaluation_runs": [{
    "id": "EVAL_old", "run_date": "2026-01-01", "structure_ref": "1sar",
    "measurements": [{
        "id": "EVAL_old_M_001",
        "assumptions": [{"id": "ASSUM_old"}],
    }],
}]}
_new_doc = {"evaluation_runs": [{
    "id": "EVAL_new", "run_date": "2026-02-01", "structure_ref": "1sar",
    "superseded_assumption_refs": ["ASSUM_old"],
    "measurements": [{
        "id": "EVAL_new_M_001",
        "catalog_task_ref": "T16",
        "stage": "final",
        "scope": "interface",
        "scope_selector": "interface_A_B",
        "subject_ref": "artifact:new#model.pdb",
        "reference_subject_ref": "repo:reference.pdb",
        "metric_definition_ref": "T16_interface_dockq_score",
        "oracle_tool_ref": "DockQ",
        "oracle_family": "non_cctbx",
        "oracle_measure": {"value_numeric": 0.9, "unit": "fraction"},
        "pass_status": "pass",
        "pass_criterion": ">= 0.8",
        "evidence_refs": ["ref/catalog.yaml"],
        "notes": "retained source note",
    }],
}]}
_future_doc = {"evaluation_runs": [{
    "id": "EVAL_future", "run_date": "2026-03-01", "structure_ref": "1sar",
    "measurements": [],
}]}
_qds_doc = {"quality_data_sheets": [{
    "id": "QDS_new",
    "emitter_contract_version": "1",
    "structure_ref": "1sar",
    "derived_from_evaluation_run_refs": ["EVAL_old", "EVAL_new"],
    "value": {
        "value_numeric": 0.9,
        "unit": "fraction",
        "source_measurement_ref": "EVAL_new_M_001",
        "source_evaluation_run_ref": "EVAL_new",
        "metric_definition_ref": "T16_interface_dockq_score",
        "oracle_tool_ref": "DockQ",
        "oracle_family": "non_cctbx",
        "pass_status": "pass",
        "pass_criterion": ">= 0.8",
        "subject_ref": "artifact:new#model.pdb",
        "reference_subject_ref": "repo:reference.pdb",
        "evidence_refs": ["ref/catalog.yaml"],
        "stage": "final",
        "scope": "interface",
        "scope_selector": "interface_A_B",
        "notes": "retained source note",
    },
    "evidence_refs": ["EVAL_old", "PaperCitation", "ref/catalog.yaml"],
}]}
_cross_records = [
    (Path("old.yaml"), _old_doc),
    (Path("new.yaml"), _new_doc),
    (Path("future.yaml"), _future_doc),
    (Path("qds.yaml"), _qds_doc),
]
_cross_index = integrity.build_corpus_indices(_cross_records)
check("unique cross-record ids produce no duplicate diagnostics",
      integrity.check_duplicate_ids(_cross_index), [])
for _path, _doc in _cross_records:
    check(f"  cross-record fixture resolves: {_path}",
          integrity.check_corpus_refs(_doc, _path, _cross_index), [])

_dangling_run = _copy.deepcopy(_qds_doc)
_dangling_run["quality_data_sheets"][0]["derived_from_evaluation_run_refs"][0] = "EVAL_gone"
_violations = integrity.check_corpus_refs(
    _dangling_run, Path("dangling-run.yaml"), _cross_index)
check("a dangling QDS input run is rejected",
      any("EVAL_gone" in v and "EvaluationRun" in v for v in _violations), True)

_dangling_source_run = _copy.deepcopy(_qds_doc)
_dangling_source_run["quality_data_sheets"][0]["value"][
    "source_evaluation_run_ref"] = "EVAL_gone"
_violations = integrity.check_corpus_refs(
    _dangling_source_run, Path("dangling-source-run.yaml"), _cross_index)
check("a dangling source_evaluation_run_ref is rejected",
      any("source_evaluation_run_ref" in v and "EVAL_gone" in v for v in _violations), True)

_dangling_measurement = _copy.deepcopy(_qds_doc)
_dangling_measurement["quality_data_sheets"][0]["value"][
    "source_measurement_ref"] = "EVAL_new_M_missing"
_violations = integrity.check_corpus_refs(
    _dangling_measurement, Path("dangling-measurement.yaml"), _cross_index)
check("a dangling source_measurement_ref is rejected",
      any("source_measurement_ref" in v and "EVAL_new_M_missing" in v
          for v in _violations), True)

_wrong_owner = _copy.deepcopy(_qds_doc)
_wrong_owner["quality_data_sheets"][0]["value"][
    "source_evaluation_run_ref"] = "EVAL_old"
_violations = integrity.check_corpus_refs(
    _wrong_owner, Path("wrong-owner.yaml"), _cross_index)
check("paired source refs must name the measurement's actual owning run",
      any("belongs to 'EVAL_new', not paired" in v for v in _violations), True)

_unpaired_measurement = _copy.deepcopy(_qds_doc)
del _unpaired_measurement["quality_data_sheets"][0]["value"][
    "source_evaluation_run_ref"]
_violations = integrity.check_corpus_refs(
    _unpaired_measurement, Path("unpaired-measurement.yaml"), _cross_index)
check("source_measurement_ref is rejected without its source run pair",
      any("must pair" in v and "source_evaluation_run_ref" in v
          for v in _violations), True)

_unpaired_run = _copy.deepcopy(_qds_doc)
del _unpaired_run["quality_data_sheets"][0]["value"]["source_measurement_ref"]
_violations = integrity.check_corpus_refs(
    _unpaired_run, Path("unpaired-run.yaml"), _cross_index)
check("source_evaluation_run_ref is rejected without its source measurement pair",
      any("must pair" in v and "source_measurement_ref" in v
          for v in _violations), True)

_not_an_input = _copy.deepcopy(_qds_doc)
_not_an_input["quality_data_sheets"][0]["derived_from_evaluation_run_refs"] = [
    "EVAL_old"]
_violations = integrity.check_corpus_refs(
    _not_an_input, Path("not-an-input.yaml"), _cross_index)
check("a scalar source run must be an input to its enclosing QDS",
      any("is not an input in the enclosing QDS" in v for v in _violations), True)

_source_fields = (
    "value_numeric", "unit", "metric_definition_ref", "oracle_tool_ref",
    "oracle_family", "pass_status", "pass_criterion", "subject_ref",
    "reference_subject_ref", "evidence_refs", "stage", "scope",
    "scope_selector", "notes",
)
for _field in _source_fields:
    _mutated_wrapper = _copy.deepcopy(_qds_doc)
    _mutated_wrapper["quality_data_sheets"][0]["value"][_field] = "tampered"
    _violations = integrity.check_corpus_refs(
        _mutated_wrapper, Path(f"tampered-{_field}.yaml"), _cross_index)
    check(f"a wrapped {_field} must exactly match its source measurement",
          any("does not exactly match source measurement" in v and _field in v
              for v in _violations), True)

_missing_source_field = _copy.deepcopy(_qds_doc)
del _missing_source_field["quality_data_sheets"][0]["value"]["notes"]
_violations = integrity.check_corpus_refs(
    _missing_source_field, Path("missing-source-field.yaml"), _cross_index)
check("a wrapped scalar cannot silently omit source metadata",
      any("does not exactly match source measurement" in v and "notes" in v
          for v in _violations), True)

_missing_source_pair = _copy.deepcopy(_qds_doc)
del _missing_source_pair["quality_data_sheets"][0]["value"][
    "source_evaluation_run_ref"]
del _missing_source_pair["quality_data_sheets"][0]["value"][
    "source_measurement_ref"]
_violations = integrity.check_corpus_refs(
    _missing_source_pair, Path("missing-source-pair.yaml"), _cross_index)
check("a nonlegacy routed scalar cannot omit both lineage fields",
      any("routed scalar in a nonlegacy QDS" in v for v in _violations), True)

_missing_all_self_description = _copy.deepcopy(_qds_doc)
_adversarial_qds = _missing_all_self_description["quality_data_sheets"][0]
_untrusted_scalar = _adversarial_qds.pop("value")
_adversarial_qds["interface_quality_summary"] = {
    "id": "QDS_new_interface_quality",
    "interface_dockq_score": _untrusted_scalar,
}
del _untrusted_scalar["source_evaluation_run_ref"]
del _untrusted_scalar["source_measurement_ref"]
del _untrusted_scalar["metric_definition_ref"]
_untrusted_scalar["value_numeric"] = 0.123
_violations = integrity.check_corpus_refs(
    _missing_all_self_description, Path("missing-all-self-description.yaml"),
    _cross_index)
check("a routed slot cannot evade lineage by deleting its metric identity too",
      any("routed scalar in a nonlegacy QDS" in v for v in _violations), True)

_source_without_family = _copy.deepcopy(_new_doc)
del _source_without_family["evaluation_runs"][0]["measurements"][0]["oracle_family"]
_canonical_records = [
    (Path("old.yaml"), _old_doc),
    (Path("new-without-family.yaml"), _source_without_family),
    (Path("qds.yaml"), _qds_doc),
]
_canonical_index = integrity.build_corpus_indices(_canonical_records)
check("source payload comparison accounts for emitter family canonicalization",
      integrity.check_corpus_refs(
          _qds_doc, Path("qds.yaml"), _canonical_index), [])

_source_interface = {
    "id": "IFACE_source",
    "structure_ref": "1sar",
    "subject_ref": "artifact:new#model.pdb",
    "reference_subject_ref": "repo:reference.pdb",
    "model_to_native_chain_mapping": "AB:AB",
    "dockq_score": {"value_numeric": 0.9},
    "buried_surface_area": {"value_numeric": 437.8, "unit": "Å²"},
}
_row_eval_doc = {"evaluation_runs": [{
    "id": "EVAL_rows", "run_date": "2026-02-02", "structure_ref": "1sar",
    "interface_qualities": [_copy.deepcopy(_source_interface)],
}]}
_emitted_interface = _copy.deepcopy(_source_interface)
_emitted_interface.update({
    "source_evaluation_run_ref": "EVAL_rows",
    "source_row_ref": "IFACE_source",
})
_row_qds_doc = {"quality_data_sheets": [{
    "id": "QDS_rows",
    "emitter_contract_version": "1",
    "structure_ref": "1sar",
    "derived_from_evaluation_run_refs": ["EVAL_rows"],
    "coverage_scope": "partial",
    "interface_quality_summary": {
        "id": "QDS_rows_interface_quality",
        "interface_qualities": [_emitted_interface],
    },
}]}
_row_records = [
    (Path("row-eval.yaml"), _row_eval_doc),
    (Path("row-qds.yaml"), _row_qds_doc),
]
_row_index = integrity.build_corpus_indices(_row_records)
check("a copied structured row with exact lineage and payload resolves",
      integrity.check_corpus_refs(
          _row_qds_doc, Path("row-qds.yaml"), _row_index), [])

_future_route_id = "T99_future_nested_interface_bsa"
current_qds_emitter.METRIC_TO_QDS_SLOT[_future_route_id] = (
    "interface_quality_summary", "buried_surface_area"
)
_drift_module_name = "check_referential_integrity_route_drift"
try:
    _drift_spec = importlib.util.spec_from_file_location(
        _drift_module_name, REPO / "scripts/check_referential_integrity.py"
    )
    _drift_integrity = importlib.util.module_from_spec(_drift_spec)
    sys.modules[_drift_module_name] = _drift_integrity
    _drift_spec.loader.exec_module(_drift_integrity)
    _drift_index = _drift_integrity.build_corpus_indices(_row_records)
    _route_drift_violations = _drift_integrity.check_corpus_refs(
        _row_qds_doc, Path("row-qds.yaml"), _drift_index
    )
finally:
    current_qds_emitter.METRIC_TO_QDS_SLOT.pop(_future_route_id)
    sys.modules.pop(_drift_module_name, None)
check(
    "future current-emitter routes cannot reinterpret a contract-1 structured row",
    _route_drift_violations,
    [],
)
check(
    "referential routing registers both retained QDS contracts",
    set(integrity.QDS_ROUTED_SCALAR_SLOTS_BY_CONTRACT),
    {"1", "2"},
)
check(
    "contract 2 explicitly owns new T14 metrics as coverage-only",
    integrity.qds_emit_contract_v2.COVERAGE_ONLY_METRIC_IDS,
    frozenset(
        {
            "T14_asn_gln_his_flip_candidates_scored",
            "T14_asn_gln_his_flip_set_conflicts",
        }
    ),
)
check(
    "contract-2 coverage-only T14 metrics are not silently scalar-routed",
    integrity.qds_emit_contract_v2.COVERAGE_ONLY_METRIC_IDS.intersection(
        integrity.qds_emit_contract_v2.METRIC_TO_QDS_SLOT
    ),
    frozenset(),
)

_drifted_row = _copy.deepcopy(_row_qds_doc)
_drifted_row["quality_data_sheets"][0]["interface_quality_summary"][
    "interface_qualities"][0]["dockq_score"]["value_numeric"] = 1.0
_violations = integrity.check_corpus_refs(
    _drifted_row, Path("row-drift.yaml"), _row_index)
check("a copied structured payload cannot diverge from its source",
      any("does not exactly match source structured row" in v
          for v in _violations), True)

_unlinked_row = _copy.deepcopy(_row_qds_doc)
_row = _unlinked_row["quality_data_sheets"][0]["interface_quality_summary"][
    "interface_qualities"][0]
del _row["source_evaluation_run_ref"]
del _row["source_row_ref"]
_violations = integrity.check_corpus_refs(
    _unlinked_row, Path("row-unlinked.yaml"), _row_index)
check("a copied structured row cannot omit both lineage fields",
      any("copied interface_qualities row in a nonlegacy QDS" in v
          for v in _violations), True)

check("record-shaped .yml files are explicitly rejected",
      any("must use the .yaml suffix" in v for v in integrity._check_data_record_filename(
          _row_qds_doc, Path("data/x/QDS_rows.yml"))), True)

check("EvaluationRun .yml files are explicitly rejected too",
      any("evaluation_runs must use the .yaml suffix" in v
          for v in integrity._check_data_record_filename(
              _row_eval_doc, Path("data/x/EVAL_rows.yml"))), True)

_canonical_eval_carrier = {"evaluation_runs": [
    {"id": "run-a", "eval_filename_stem": "EVAL_rows"},
    {"id": "run-b", "eval_filename_stem": "EVAL_rows"},
]}
check("a canonical multi-run EvaluationRun carrier is accepted",
      integrity._check_data_record_filename(
          _canonical_eval_carrier, Path("data/x/EVAL_rows.yaml")), [])

_noncanonical_eval_path = Path("data/x/not_an_eval.yaml")
_noncanonical_eval_index = integrity.build_corpus_indices(
    [(_noncanonical_eval_path, _canonical_eval_carrier)])
_noncanonical_eval_violations = integrity.check_corpus_refs(
    _canonical_eval_carrier, _noncanonical_eval_path,
    _noncanonical_eval_index)
check("a noncanonical .yaml carrier cannot smuggle EvaluationRuns",
      any("must use an EVAL_*.yaml filename" in v
          for v in _noncanonical_eval_violations), True)

with tempfile.TemporaryDirectory() as _tmp:
    _tmp_root = Path(_tmp)
    _ignored_carrier = _tmp_root / "data" / ".ignored" / "not_an_eval.yaml"
    _ignored_carrier.parent.mkdir(parents=True)
    _ignored_carrier.write_text(_yaml.safe_dump(_canonical_eval_carrier))
    _saved_repo, _saved_catalog = integrity.REPO, integrity.CATALOG
    try:
        integrity.REPO = _tmp_root
        integrity.CATALOG = _tmp_root / "ref" / "catalog.yaml"
        _discovered = integrity.target_paths()
        _discovered_records = [
            (_path, _yaml.safe_load(_path.read_text()))
            for _path in _discovered
        ]
        _discovered_index = integrity.build_corpus_indices(_discovered_records)
        _ignored_doc = next(
            _doc for _path, _doc in _discovered_records
            if _path == _ignored_carrier)
        _ignored_violations = integrity.check_corpus_refs(
            _ignored_doc, _ignored_carrier.relative_to(_tmp_root),
            _discovered_index)
    finally:
        integrity.REPO, integrity.CATALOG = _saved_repo, _saved_catalog
    check("ignore-independent corpus discovery sees a hidden YAML carrier",
          _ignored_carrier in _discovered, True)
    check("the discovered hidden carrier is rejected by filename admission",
          any("must use an EVAL_*.yaml filename" in v
              for v in _ignored_violations), True)

_missing_eval_stem = {"evaluation_runs": [{"id": "run-a"}]}
check("a canonical EvaluationRun carrier requires eval_filename_stem",
      any("eval_filename_stem must be a nonblank string" in v
          for v in integrity._check_data_record_filename(
              _missing_eval_stem, Path("data/x/EVAL_rows.yaml"))), True)

_mismatched_eval_stem = _copy.deepcopy(_canonical_eval_carrier)
_mismatched_eval_stem["evaluation_runs"][1]["eval_filename_stem"] = "EVAL_other"
check("every run in a multi-run carrier must name the owning stem",
      any("does not match filename stem 'EVAL_rows'" in v
          for v in integrity._check_data_record_filename(
              _mismatched_eval_stem, Path("data/x/EVAL_rows.yaml"))), True)

_mixed_carrier = _copy.deepcopy(_row_qds_doc)
_mixed_carrier["evaluation_runs"] = [{
    "id": "run-a", "eval_filename_stem": "QDS_rows",
}]
check("a QDS_ carrier cannot also smuggle EvaluationRuns",
      any("must use an EVAL_*.yaml filename" in v
          for v in integrity._check_data_record_filename(
              _mixed_carrier, Path("data/x/QDS_rows.yaml"))), True)

_outside_qds = _copy.deepcopy(_qds_doc["quality_data_sheets"][0]["value"])
_violations = integrity.check_corpus_refs(
    {"detached_value": _outside_qds}, Path("detached.yaml"), _cross_index)
check("source refs outside a QualityDataSheet are rejected",
      any("outside a QualityDataSheet" in v for v in _violations), True)

_evidence = {"evidence_refs": ["PaperCitation", "ref/catalog.yaml", "EVAL_old"]}
check("citation keys, repository paths, and a resolving EVAL evidence ref are allowed",
      integrity.check_corpus_refs(_evidence, Path("evidence.yaml"), _cross_index), [])
_evidence["evidence_refs"].append("EVAL_missing")
_violations = integrity.check_corpus_refs(_evidence, Path("evidence.yaml"), _cross_index)
check("an EVAL_* evidence token is reserved and must resolve",
      any("evidence_refs[3]" in v and "EVAL_missing" in v for v in _violations), True)

_self_evidence = _copy.deepcopy(_new_doc)
_self_evidence["evaluation_runs"][0]["measurements"][0][
    "criterion_preconditions"
] = [{
    "id": "matched_h_build",
    "status": "satisfied",
    "evidence_refs": ["EVAL_new"],
}]
_violations = integrity.check_corpus_refs(
    _self_evidence, Path("self-evidence.yaml"), _cross_index)
check("a criterion precondition cannot cite its owning run as evidence",
      any("is circular" in v and "EVAL_new" in v for v in _violations), True)
_self_evidence["evaluation_runs"][0]["measurements"][0][
    "criterion_preconditions"
][0]["evidence_refs"] = ["EVAL_old"]
check("a criterion precondition may cite an earlier retained run",
      integrity.check_corpus_refs(
          _self_evidence, Path("earlier-evidence.yaml"), _cross_index), [])
_self_evidence["evaluation_runs"][0]["measurements"][0][
    "criterion_preconditions"
][0]["evidence_refs"] = ["EVAL_future"]
_violations = integrity.check_corpus_refs(
    _self_evidence, Path("future-evidence.yaml"), _cross_index)
check("a criterion precondition cannot cite a future EvaluationRun",
      any("not earlier than owning" in v and "EVAL_future" in v
          for v in _violations), True)

# EvaluationRun.id is intentionally unconstrained; the EVAL_ prefix belongs to
# carrier naming, not object identity. Exact indexed ids must get the same temporal
# treatment without turning unrelated unresolved citation keys into run refs.
_arbitrary_current = _copy.deepcopy(_new_doc)
_arbitrary_current["evaluation_runs"][0]["id"] = "RUN_current"
_arbitrary_future = _copy.deepcopy(_future_doc)
_arbitrary_future["evaluation_runs"][0]["id"] = "RUN_future"
_arbitrary_index = integrity.build_corpus_indices([
    (Path("arbitrary-current.yaml"), _arbitrary_current),
    (Path("arbitrary-future.yaml"), _arbitrary_future),
])
_arbitrary_precondition = _arbitrary_current["evaluation_runs"][0][
    "measurements"
][0].setdefault("criterion_preconditions", [{
    "id": "matched_h_build", "status": "satisfied", "evidence_refs": [],
}])
_arbitrary_precondition[0]["evidence_refs"] = [
    "RUN_future", "ref/catalog.yaml",
]
_violations = integrity.check_corpus_refs(
    _arbitrary_current, Path("arbitrary-current.yaml"), _arbitrary_index)
check("an indexed arbitrary-id future EvaluationRun is date-checked",
      any("not earlier than owning" in v and "RUN_future" in v
          for v in _violations), True)
_arbitrary_precondition[0]["evidence_refs"] = [
    "RUN_current", "ref/catalog.yaml",
]
_violations = integrity.check_corpus_refs(
    _arbitrary_current, Path("arbitrary-current.yaml"), _arbitrary_index)
check("an indexed arbitrary-id owning EvaluationRun is circular",
      any("is circular" in v and "RUN_current" in v
          for v in _violations), True)
for _label, _weak_ref in (
    ("invented citation token", "made_up_token"),
    ("URL only", "https://example.org/assertion"),
):
    _self_evidence["evaluation_runs"][0]["measurements"][0][
        "criterion_preconditions"
    ][0]["evidence_refs"] = [_weak_ref]
    _violations = integrity.check_corpus_refs(
        _self_evidence, Path("weak-evidence.yaml"), _cross_index)
    check(f"criterion precondition rejects {_label} without retained evidence",
          any("must include at least one distinct repository file" in v
              for v in _violations), True)

with tempfile.TemporaryDirectory() as _tmp:
    _tmp_root = Path(_tmp)
    _current_file = _tmp_root / "new.yaml"
    _current_file.write_text("evaluation_runs: []\n")
    (_tmp_root / "future.yaml").write_text("evaluation_runs: []\n")
    _saved_repo = integrity.REPO
    try:
        integrity.REPO = _tmp_root
        for _self_ref in ("new.yaml", "repo:new.yaml"):
            _self_evidence["evaluation_runs"][0]["measurements"][0][
                "criterion_preconditions"
            ][0]["evidence_refs"] = [_self_ref]
            _violations = integrity.check_corpus_refs(
                _self_evidence, Path("new.yaml"), _cross_index)
            check(f"criterion precondition rejects self-file evidence {_self_ref!r}",
                  any("own carrier file" in v for v in _violations), True)
        _self_evidence["evaluation_runs"][0]["measurements"][0][
            "criterion_preconditions"
        ][0]["evidence_refs"] = ["future.yaml"]
        _violations = integrity.check_corpus_refs(
            _self_evidence, Path("new.yaml"), _cross_index)
        check("a future EvaluationRun carrier path cannot bypass date checking",
              any("EvaluationRun carrier by path" in v
                  for v in _violations), True)
        check("an EVAL carrier path does not count as retained precondition evidence",
              any("must include at least one distinct repository file" in v
                  for v in _violations), True)
        check("an EVAL carrier path remains ordinary evidence outside a precondition",
              integrity.check_corpus_refs(
                  {"evidence_refs": ["future.yaml"]},
                  Path("detached-evidence.yaml"), _cross_index), [])
    finally:
        integrity.REPO = _saved_repo

_missing_evidence = {"evidence_refs": ["data/does/not/exist.json"]}
_violations = integrity.check_corpus_refs(
    _missing_evidence, Path("missing-evidence.yaml"), _cross_index)
check("a missing repository evidence path is rejected",
      any("does not resolve to a repository file" in v for v in _violations), True)

_missing_bare_evidence = {"evidence_refs": ["missing-output.json"]}
_violations = integrity.check_corpus_refs(
    _missing_bare_evidence, Path("missing-bare-evidence.yaml"), _cross_index)
check("a missing bare evidence filename is also rejected",
      any("does not resolve to a repository file" in v for v in _violations), True)

_absolute_evidence = {"evidence_refs": ["/private/tmp/nonportable.json"]}
_violations = integrity.check_corpus_refs(
    _absolute_evidence, Path("absolute-evidence.yaml"), _cross_index)
check("an absolute evidence path is rejected",
      any("absolute, non-portable" in v for v in _violations), True)

_escaping_evidence = {"evidence_refs": ["../outside-repository.json"]}
_violations = integrity.check_corpus_refs(
    _escaping_evidence, Path("escaping-evidence.yaml"), _cross_index)
check("an escaping evidence path is rejected",
      any("escapes the repository" in v for v in _violations), True)

_portable_evidence = {"evidence_refs": [
    "https://example.org/evidence/output.json", "10.1234/example/article",
    "Smith.et.al.2024", "repo:ref/catalog.yaml#catalog",
]}
check("URLs, citation keys, and resolving repo: evidence refs are allowed",
      integrity.check_corpus_refs(
          _portable_evidence, Path("portable-evidence.yaml"), _cross_index), [])

_missing_repo_uri = {"evidence_refs": ["repo:data/missing-output.json"]}
_violations = integrity.check_corpus_refs(
    _missing_repo_uri, Path("missing-repo-uri.yaml"), _cross_index)
check("a missing repo: evidence URI is rejected",
      any("does not resolve to a repository file" in v for v in _violations), True)

_missing_assumption = _copy.deepcopy(_new_doc)
_missing_assumption["evaluation_runs"][0]["superseded_assumption_refs"] = ["ASSUM_gone"]
_violations = integrity.check_corpus_refs(
    _missing_assumption, Path("missing-assumption.yaml"), _cross_index)
check("a dangling superseded assumption is rejected",
      any("ASSUM_gone" in v and "Assumption" in v for v in _violations), True)

_self_doc = {"evaluation_runs": [{
    "id": "EVAL_self", "run_date": "2026-03-01",
    "assumptions": [{"id": "ASSUM_self"}],
    "superseded_assumption_refs": ["ASSUM_self"],
}]}
_self_index = integrity.build_corpus_indices([(Path("self.yaml"), _self_doc)])
_violations = integrity.check_corpus_refs(_self_doc, Path("self.yaml"), _self_index)
check("a run cannot supersede its own assumption",
      any("same EvaluationRun" in v for v in _violations), True)

_future_old = {"evaluation_runs": [{
    "id": "EVAL_before", "run_date": "2026-01-01",
    "superseded_assumption_refs": ["ASSUM_future"],
}]}
_future_new = {"evaluation_runs": [{
    "id": "EVAL_after", "run_date": "2026-02-01",
    "assumptions": [{"id": "ASSUM_future"}],
}]}
_future_index = integrity.build_corpus_indices([
    (Path("before.yaml"), _future_old), (Path("after.yaml"), _future_new)])
_violations = integrity.check_corpus_refs(
    _future_old, Path("before.yaml"), _future_index)
check("a run cannot supersede an assumption from a future run",
      any("not a run earlier" in v for v in _violations), True)

_reversed_qds = _copy.deepcopy(_qds_doc)
_reversed_qds["quality_data_sheets"][0]["derived_from_evaluation_run_refs"] = [
    "EVAL_new", "EVAL_old"]
_violations = integrity.check_corpus_refs(
    _reversed_qds, Path("reversed-qds.yaml"), _cross_index)
check("the superseded assumption's owner must be an earlier QDS input",
      any("not an earlier input to this QDS" in v for v in _violations), True)

_duplicate_doc = {"evaluation_runs": [{
    "id": "EVAL_old", "run_date": "2026-01-02",
    "measurements": [{
        "id": "EVAL_old_M_001", "assumptions": [{"id": "ASSUM_old"}],
    }],
}]}
_duplicate_index = integrity.build_corpus_indices(
    _cross_records + [(Path("duplicate.yaml"), _duplicate_doc)])
_duplicate_messages = integrity.check_duplicate_ids(_duplicate_index)
check("duplicate run, measurement, and assumption ids are all diagnosed",
      sorted(label for label in ("EvaluationRun", "MeasurementValue", "Assumption")
             if any(label in v for v in _duplicate_messages)),
      ["Assumption", "EvaluationRun", "MeasurementValue"])
_violations = integrity.check_corpus_refs(_qds_doc, Path("qds.yaml"), _duplicate_index)
check("a ref to a duplicate id is explicitly ambiguous",
      any("is ambiguous" in v for v in _violations), True)

_duplicate_qds_index = integrity.build_corpus_indices([
    (Path("first.yaml"), _qds_doc), (Path("second.yaml"), _qds_doc),
])
check("duplicate QualityDataSheet ids are diagnosed corpus-wide",
      any("duplicate QualityDataSheet id 'QDS_new'" in v
          for v in integrity.check_duplicate_ids(_duplicate_qds_index)), True)

_misnamed_qds = {"quality_data_sheets": [{
    "id": "QDS_named", "structure_ref": "1sar",
    "derived_from_evaluation_run_refs": [],
}]}
_violations = integrity.check_corpus_refs(
    _misnamed_qds, Path("data/provider/not_a_qds.yaml"), _cross_index)
check("data YAML containing a QDS cannot escape QDS filename discovery",
      any("must use a QDS_*.yaml filename" in v for v in _violations), True)
check("a QDS id must exactly match its data filename stem",
      any("does not match filename stem" in v for v in _violations), True)
check("a correctly named QDS data file satisfies the naming convention",
      integrity.check_corpus_refs(
          _misnamed_qds, Path("data/provider/QDS_named.yaml"), _cross_index), [])

_wrong_structure = _copy.deepcopy(_qds_doc)
_wrong_structure["quality_data_sheets"][0]["structure_ref"] = "9zzz"
_violations = integrity.check_corpus_refs(
    _wrong_structure, Path("wrong-structure.yaml"), _cross_index)
check("every QDS structure_ref must match each input run",
      any("does not match input EvaluationRun" in v and "9zzz" in v
          for v in _violations), True)

_duplicate_input = _copy.deepcopy(_qds_doc)
_duplicate_input["quality_data_sheets"][0][
    "derived_from_evaluation_run_refs"].append("EVAL_new")
_violations = integrity.check_corpus_refs(
    _duplicate_input, Path("duplicate-input.yaml"), _cross_index)
check("a QDS cannot list one derivation input twice",
      any("derived_from_evaluation_run_refs" in v and "duplicates 'EVAL_new'" in v
          for v in _violations), True)

_pin_doc = _copy.deepcopy(_new_doc)
_pin_doc["qds_replay_pins"] = [{
    "id": "PIN_QDS_new",
    "qds_ref": "QDS_new",
    "source_evaluation_run_refs": ["EVAL_old", "EVAL_new"],
    "emitter_contract_version": "1",
}]
_pin_records = [
    (Path("old.yaml"), _old_doc),
    (Path("pin.yaml"), _pin_doc),
    (Path("qds.yaml"), _qds_doc),
]
_pin_index = integrity.build_corpus_indices(_pin_records)
check("a replay pin resolves its target QDS and exact source runs",
      integrity.check_corpus_refs(_pin_doc, Path("pin.yaml"), _pin_index), [])

_dangling_pin_qds = _copy.deepcopy(_pin_doc)
_dangling_pin_qds["qds_replay_pins"][0]["qds_ref"] = "QDS_missing"
_violations = integrity.check_corpus_refs(
    _dangling_pin_qds, Path("dangling-pin-qds.yaml"), _pin_index)
check("a replay pin cannot name a missing QDS",
      any("qds_ref" in v and "QDS_missing" in v and "does not resolve" in v
          for v in _violations), True)

_dangling_pin_run = _copy.deepcopy(_pin_doc)
_dangling_pin_run["qds_replay_pins"][0]["source_evaluation_run_refs"][0] = (
    "EVAL_missing"
)
_violations = integrity.check_corpus_refs(
    _dangling_pin_run, Path("dangling-pin-run.yaml"), _pin_index)
check("a replay pin cannot name a missing source run",
      any("source_evaluation_run_refs[0]" in v and "EVAL_missing" in v
          and "does not resolve" in v for v in _violations), True)
check("a replay pin must exactly match its QDS derivation refs",
      any("differs from target QDS" in v for v in _violations), True)

_orphan_pin = {"qds_replay_pins": _copy.deepcopy(_pin_doc["qds_replay_pins"])}
_violations = integrity.check_corpus_refs(
    _orphan_pin, Path("orphan-pin.yaml"), _pin_index)
check("a replay pin must be owned by a source run in its document",
      any("not owned by any source EvaluationRun" in v for v in _violations), True)

_duplicate_pin_a = {"qds_replay_pins": _copy.deepcopy(_pin_doc["qds_replay_pins"])}
_duplicate_pin_b = {"qds_replay_pins": _copy.deepcopy(_pin_doc["qds_replay_pins"])}
_duplicate_pin_b["qds_replay_pins"][0]["id"] = "PIN_QDS_new_second"
_duplicate_pin_index = integrity.build_corpus_indices(
    _cross_records
    + [(Path("pin-a.yaml"), _duplicate_pin_a),
       (Path("pin-b.yaml"), _duplicate_pin_b)]
)
_duplicate_pin_messages = integrity.check_duplicate_ids(_duplicate_pin_index)
check("multiple replay pins for one QDS are diagnosed corpus-wide",
      any("multiple QdsReplayPins target qds_ref 'QDS_new'" in v
          for v in _duplicate_pin_messages), True)
_duplicate_pin_b["qds_replay_pins"][0]["id"] = "PIN_QDS_new"
_duplicate_pin_index = integrity.build_corpus_indices(
    _cross_records
    + [(Path("pin-a.yaml"), _duplicate_pin_a),
       (Path("pin-b.yaml"), _duplicate_pin_b)]
)
check("duplicate replay-pin ids are diagnosed corpus-wide",
      any("duplicate QdsReplayPin id 'PIN_QDS_new'" in v
          for v in integrity.check_duplicate_ids(_duplicate_pin_index)), True)


# --- #548/#577/#666: typed measurement lineage is semantic, not just a string -----
def _measurement_relation_violations(*docs):
    records = [
        (Path(f"measurement-lineage-{index}.yaml"), doc)
        for index, doc in enumerate(docs)
    ]
    return integrity.check_measurement_relations(
        integrity.build_corpus_indices(records)
    )


_relation_context = {
    "catalog_task_ref": "T03",
    "stage": "final",
    "scope": "complex",
    "scope_selector": "packaged model",
    "subject_ref": "artifact:example#model.pdb",
    "metric_definition_ref": "T03_r-work",
}
_pair_baseline = {
    "id": "PAIR_M_001",
    **_relation_context,
    "oracle_tool_ref": "phenix.model_vs_data",
    "oracle_family": "cctbx",
    "oracle_measure": {"value_numeric": 0.1564, "unit": "fraction"},
}
_pair_delta = {
    "id": "PAIR_M_002",
    **_relation_context,
    "oracle_tool_ref": "gemmi sfcalc",
    "oracle_family": "non_cctbx",
    "oracle_measure": {"value_numeric": 0.1622, "unit": "fraction"},
    "delta": {"value_numeric": 0.0058, "unit": "fraction"},
    "delta_from_measurement_ref": "PAIR_M_001",
}
_pair_doc = {"evaluation_runs": [{
    "id": "EVAL_pair",
    "measurements": [_pair_baseline, _pair_delta],
}]}
check("a same-run, same-context pair delta with exact arithmetic is valid",
      _measurement_relation_violations(_pair_doc), [])

_bad_arithmetic = _copy.deepcopy(_pair_doc)
_bad_arithmetic["evaluation_runs"][0]["measurements"][1]["delta"][
    "value_numeric"
] = 0.0057
_violations = _measurement_relation_violations(_bad_arithmetic)
check("0.1622 - 0.1564 cannot be reported as 0.0057",
      any("does not equal" in violation and "0.0058" in violation
          for violation in _violations), True)

_trailing_zero_precision = _copy.deepcopy(_pair_doc)
_trailing_zero_precision["evaluation_runs"][0]["measurements"][0][
    "oracle_measure"
]["value_numeric"] = 0.1598
_trailing_zero_precision["evaluation_runs"][0]["measurements"][1]["delta"][
    "value_numeric"
] = 0.002  # yaml.safe_load("0.0020") has exactly this value (#667).
check("a parsed 0.002 delta cannot hide an exact 0.0024 source difference",
      any("does not equal" in violation and "0.0024" in violation
          for violation in
          _measurement_relation_violations(_trailing_zero_precision)), True)

_dangling_pair = _copy.deepcopy(_pair_doc)
_dangling_pair["evaluation_runs"][0]["measurements"][1][
    "delta_from_measurement_ref"
] = "PAIR_M_missing"
check("a pair-delta source ref must resolve",
      any("does not resolve" in violation for violation in
          _measurement_relation_violations(_dangling_pair)), True)

_ambiguous_pair_source = {"evaluation_runs": [{
    "id": "EVAL_duplicate_pair_source",
    "measurements": [_copy.deepcopy(_pair_baseline)],
}]}
check("a pair-delta source ref must resolve uniquely",
      any("is ambiguous" in violation for violation in
          _measurement_relation_violations(
              _pair_doc, _ambiguous_pair_source)), True)

_cross_run_pair = _copy.deepcopy(_pair_doc)
_moved_baseline = _cross_run_pair["evaluation_runs"][0]["measurements"].pop(0)
_cross_run_pair["evaluation_runs"].append({
    "id": "EVAL_other_pair", "measurements": [_moved_baseline],
})
check("a pair-delta source must belong to the same EvaluationRun",
      any("not owning EvaluationRun" in violation for violation in
          _measurement_relation_violations(_cross_run_pair)), True)

_self_pair = _copy.deepcopy(_pair_doc)
_self_pair["evaluation_runs"][0]["measurements"][1][
    "delta_from_measurement_ref"
] = "PAIR_M_002"
check("a pair delta cannot reference itself",
      any("cannot reference its own" in violation for violation in
          _measurement_relation_violations(_self_pair)), True)

_cyclic_pair = _copy.deepcopy(_pair_doc)
_cyclic_pair["evaluation_runs"][0]["measurements"][0].update({
    "delta_from_measurement_ref": "PAIR_M_002",
    "delta": {"value_numeric": -0.0058, "unit": "fraction"},
})
check("pair-delta lineage cannot form a cycle",
      any("lineage forms a cycle" in violation for violation in
          _measurement_relation_violations(_cyclic_pair)), True)

for _field in integrity.DELTA_CONTEXT_FIELDS:
    _mismatch = _copy.deepcopy(_pair_doc)
    _mismatch["evaluation_runs"][0]["measurements"][0][_field] = (
        f"different-{_field}"
    )
    check(f"  pair-delta source must match {_field}",
          any(f"mismatched {_field}" in violation for violation in
              _measurement_relation_violations(_mismatch)), True)

for _row_index, _side in ((0, "source"), (1, "derived")):
    _missing_subject = _copy.deepcopy(_pair_doc)
    del _missing_subject["evaluation_runs"][0]["measurements"][_row_index][
        "subject_ref"
    ]
    check(f"a pair delta rejects a missing {_side} subject_ref",
          any("requires a non-empty subject_ref" in violation for violation in
              _measurement_relation_violations(_missing_subject)), True)

for _row_index, _carrier in ((0, "oracle_measure"),
                             (1, "oracle_measure"),
                             (1, "delta")):
    _text_carrier = _copy.deepcopy(_pair_doc)
    _text_carrier["evaluation_runs"][0]["measurements"][_row_index][
        _carrier
    ] = {"value_text": "not numeric", "unit": "fraction"}
    check(f"  pair delta requires numeric row {_row_index} {_carrier}",
          any("must carry one finite value_numeric" in violation for violation in
              _measurement_relation_violations(_text_carrier)), True)

_unit_mismatch = _copy.deepcopy(_pair_doc)
_unit_mismatch["evaluation_runs"][0]["measurements"][1]["delta"]["unit"] = "count"
check("pair-delta values must have compatible units",
      any("incompatible numeric units" in violation for violation in
          _measurement_relation_violations(_unit_mismatch)), True)

_derived_context = {
    "catalog_task_ref": "T14",
    "stage": "final",
    "scope": "complex",
    "scope_selector": "packaged model",
    "subject_ref": "artifact:example#model.pdb",
}
_derived_source_a = {
    "id": "DERIVED_M_001",
    **_derived_context,
    "metric_definition_ref": "T14_asn_gln_his_flip_candidates_scored",
    "oracle_tool_ref": "reduce (standalone, Richardson)",
    "oracle_family": "non_cctbx",
    "oracle_measure": {"value_numeric": 14, "unit": "count"},
    "pass_status": "informational",
}
_derived_source_b = {
    "id": "DERIVED_M_002",
    **_derived_context,
    "metric_definition_ref": "T14_asn_gln_his_flip_candidates_scored",
    "oracle_tool_ref": "mmtbx.reduce2",
    "oracle_family": "cctbx",
    "oracle_measure": {"value_numeric": 18, "unit": "count"},
    "pass_status": "informational",
}
_derived_composite = {
    "id": "DERIVED_M_003",
    **_derived_context,
    "metric_definition_ref": "generic_comparison_metric",
    "oracle_tool_ref": "mmtbx.reduce2",
    "oracle_family": "cctbx",
    "oracle_measure": {"value_numeric": 0, "unit": "count"},
    "derived_from_measurement_refs": ["DERIVED_M_001", "DERIVED_M_002"],
}
_derived_doc = {"evaluation_runs": [{
    "id": "EVAL_derived",
    "measurements": [
        _derived_source_a, _derived_source_b, _derived_composite,
    ],
}]}
check("generic derived lineage permits a distinct composite metric",
      _measurement_relation_violations(_derived_doc), [])

_duplicate_derived_ref = _copy.deepcopy(_derived_doc)
_duplicate_derived_ref["evaluation_runs"][0]["measurements"][2][
    "derived_from_measurement_refs"
] = ["DERIVED_M_001", "DERIVED_M_001"]
check("generic derived lineage rejects duplicate source refs",
      any("contains duplicate refs" in violation for violation in
          _measurement_relation_violations(_duplicate_derived_ref)), True)

_dangling_derived_ref = _copy.deepcopy(_derived_doc)
_dangling_derived_ref["evaluation_runs"][0]["measurements"][2][
    "derived_from_measurement_refs"
][1] = "DERIVED_M_missing"
check("each generic derived source ref must resolve",
      any("does not resolve" in violation for violation in
          _measurement_relation_violations(_dangling_derived_ref)), True)

_ambiguous_derived_source = {"evaluation_runs": [{
    "id": "EVAL_duplicate_derived_source",
    "measurements": [_copy.deepcopy(_derived_source_a)],
}]}
check("each generic derived source ref must resolve uniquely",
      any("is ambiguous" in violation for violation in
          _measurement_relation_violations(
              _derived_doc, _ambiguous_derived_source)), True)

_self_derived_ref = _copy.deepcopy(_derived_doc)
_self_derived_ref["evaluation_runs"][0]["measurements"][2][
    "derived_from_measurement_refs"
][1] = "DERIVED_M_003"
check("generic derived lineage rejects a self reference",
      any("cannot reference its own" in violation for violation in
          _measurement_relation_violations(_self_derived_ref)), True)

_cyclic_derived = _copy.deepcopy(_derived_doc)
_cyclic_derived["evaluation_runs"][0]["measurements"][0][
    "derived_from_measurement_refs"
] = ["DERIVED_M_003"]
check("generic derived lineage cannot form a cycle",
      any("lineage forms a cycle" in violation for violation in
          _measurement_relation_violations(_cyclic_derived)), True)

_mixed_relation_cycle = _copy.deepcopy(_derived_doc)
_mixed_source = _mixed_relation_cycle["evaluation_runs"][0]["measurements"][0]
_mixed_source.update({
    "metric_definition_ref": "generic_comparison_metric",
    "delta_from_measurement_ref": "DERIVED_M_003",
    "delta": {"value_numeric": 14, "unit": "count"},
})
check("mixed pair-delta and derived lineage cannot form a cycle",
      any("lineage forms a cycle" in violation for violation in
          _measurement_relation_violations(_mixed_relation_cycle)), True)

_cross_run_derived = _copy.deepcopy(_derived_doc)
_moved_derived_source = _cross_run_derived["evaluation_runs"][0][
    "measurements"
].pop(0)
_cross_run_derived["evaluation_runs"].append({
    "id": "EVAL_other_derived", "measurements": [_moved_derived_source],
})
check("generic derived sources must belong to the same EvaluationRun",
      any("not owning EvaluationRun" in violation for violation in
          _measurement_relation_violations(_cross_run_derived)), True)

for _field in integrity.DERIVED_CONTEXT_FIELDS:
    _derived_mismatch = _copy.deepcopy(_derived_doc)
    _derived_mismatch["evaluation_runs"][0]["measurements"][0][_field] = (
        f"different-{_field}"
    )
    check(f"  generic derived source must match {_field}",
          any(f"mismatched {_field}" in violation for violation in
              _measurement_relation_violations(_derived_mismatch)), True)

_missing_derived_subject = _copy.deepcopy(_derived_doc)
del _missing_derived_subject["evaluation_runs"][0]["measurements"][2][
    "subject_ref"
]
check("generic derived lineage rejects a missing derived subject_ref",
      any("requires a non-empty subject_ref" in violation for violation in
          _measurement_relation_violations(_missing_derived_subject)), True)

_missing_derived_source_subject = _copy.deepcopy(_derived_doc)
del _missing_derived_source_subject["evaluation_runs"][0]["measurements"][0][
    "subject_ref"
]
check("generic derived lineage rejects a missing source subject_ref",
      any("requires a non-empty subject_ref" in violation for violation in
          _measurement_relation_violations(_missing_derived_source_subject)), True)

_t14_doc = _copy.deepcopy(_derived_doc)
_t14_row = _t14_doc["evaluation_runs"][0]["measurements"][2]
_t14_row["metric_definition_ref"] = "T14_asn_gln_his_flip_set_conflicts"
_t14_row["oracle_measure"]["count"] = 14
_t14_row["pass_status"] = "informational"
check("T14 flip conflicts retain a denominator and both canonical families",
      _measurement_relation_violations(_t14_doc), [])

_integral_float_t14 = _copy.deepcopy(_t14_doc)
_integral_float_rows = _integral_float_t14["evaluation_runs"][0]["measurements"]
_integral_float_rows[0]["oracle_measure"]["value_numeric"] = 14.0
_integral_float_rows[1]["oracle_measure"]["value_numeric"] = 18.0
_integral_float_rows[2]["oracle_measure"].update({
    "value_numeric": 0.0,
    "count": 14.0,
})
check("T14 count carriers accept finite mathematically integral floats",
      _measurement_relation_violations(_integral_float_t14), [])

for _invalid_count in (
    None, 0, 1.5, True, float("nan"), float("inf"), float("-inf"),
):
    _bad_t14_count = _copy.deepcopy(_t14_doc)
    _bad_t14_count["evaluation_runs"][0]["measurements"][2][
        "oracle_measure"
    ]["count"] = _invalid_count
    check(f"  T14 conflict denominator rejects {_invalid_count!r}",
          any("positive integer oracle_measure.count" in violation
              for violation in _measurement_relation_violations(_bad_t14_count)),
          True)

_one_family_t14 = _copy.deepcopy(_t14_doc)
_one_family_t14["evaluation_runs"][0]["measurements"][1][
    "oracle_tool_ref"
] = "reduce (standalone, Richardson)"
check("T14 conflict lineage must collectively span both canonical families",
      any("both cctbx and non_cctbx are required" in violation
          for violation in _measurement_relation_violations(_one_family_t14)),
      True)

_misclaimed_t14 = _copy.deepcopy(_t14_doc)
_misclaimed_t14["evaluation_runs"][0]["measurements"][2][
    "oracle_family"
] = "non_cctbx"
check("a cctbx-dependent T14 comparison cannot claim non_cctbx provenance",
      any("must not claim oracle_family non_cctbx" in violation
          for violation in _measurement_relation_violations(_misclaimed_t14)),
      True)

for _source_index, _wrong_family in ((0, "cctbx"), (1, "non_cctbx")):
    _misclaimed_t14_source = _copy.deepcopy(_t14_doc)
    _misclaimed_t14_source["evaluation_runs"][0]["measurements"][_source_index][
        "oracle_family"
    ] = _wrong_family
    check(f"  T14 source {_source_index} must assert its catalog tool family",
          any("asserts oracle_family" in violation and "canonical family" in violation
              for violation in
              _measurement_relation_violations(_misclaimed_t14_source)), True)

_standalone_t14_candidate = {"evaluation_runs": [{
    "id": "EVAL_standalone_t14_candidate",
    "measurements": [_copy.deepcopy(_derived_source_a)],
}]}
check("a standalone informational T14 candidate count is valid",
      _measurement_relation_violations(_standalone_t14_candidate), [])

_graded_standalone_t14_candidate = _copy.deepcopy(_standalone_t14_candidate)
_graded_standalone_t14_candidate["evaluation_runs"][0]["measurements"][0].update({
    "pass_status": "pass",
    "pass_criterion": "candidate count <= 10%",
})
_graded_candidate_violations = _measurement_relation_violations(
    _graded_standalone_t14_candidate
)
check("a standalone T14 candidate count must remain informational",
      any("candidate-count measurement" in violation
          and "requires pass_status 'informational'" in violation
          for violation in _graded_candidate_violations), True)
check("a standalone T14 candidate count cannot carry a criterion",
      any("candidate-count measurement" in violation
          and "must not carry pass_criterion" in violation
          for violation in _graded_candidate_violations), True)

_nested_graded_t14_candidate = _copy.deepcopy(_standalone_t14_candidate)
_nested_graded_t14_candidate["evaluation_runs"][0]["measurements"][0][
    "oracle_measure"
].update({
    "pass_status": "pass",
    "pass_criterion": "candidate count <= 10%",
})
_nested_candidate_violations = _measurement_relation_violations(
    _nested_graded_t14_candidate
)
check("a T14 candidate count rejects a nested oracle verdict",
      any("oracle_measure.pass_status" in violation
          and "must remain informational" in violation
          for violation in _nested_candidate_violations), True)
check("a T14 candidate count rejects a nested oracle criterion",
      any("oracle_measure" in violation
          and "must not carry pass_criterion" in violation
          for violation in _nested_candidate_violations), True)

for _source_index in (0, 1):
    _graded_t14_source = _copy.deepcopy(_t14_doc)
    _graded_t14_source["evaluation_runs"][0]["measurements"][_source_index].update({
        "pass_status": "pass",
        "pass_criterion": "candidate count <= 10%",
    })
    _graded_source_violations = _measurement_relation_violations(
        _graded_t14_source
    )
    check(f"  T14 source {_source_index} cannot assert a cohort pass",
          any("candidate-count measurement" in violation
              and "requires pass_status 'informational'" in violation
              for violation in _graded_source_violations), True)
    check(f"  T14 source {_source_index} cannot carry a threshold criterion",
          any("candidate-count measurement" in violation
              and "must not carry pass_criterion" in violation
              for violation in _graded_source_violations), True)

_graded_single_structure_t14 = _copy.deepcopy(_t14_doc)
_graded_single_structure_t14["evaluation_runs"][0]["measurements"][2].update({
    "pass_status": "pass",
    "pass_criterion": "conflict rate <= 10%",
})
_graded_t14_violations = _measurement_relation_violations(
    _graded_single_structure_t14
)
check("a single-structure T14 conflict row cannot assert a cohort pass",
      any("requires pass_status 'informational'" in violation
          for violation in _graded_t14_violations), True)
check("a single-structure T14 conflict row cannot carry a threshold criterion",
      any("must not carry pass_criterion" in violation
          for violation in _graded_t14_violations), True)

_nested_graded_single_structure_t14 = _copy.deepcopy(_t14_doc)
_nested_graded_single_structure_t14["evaluation_runs"][0]["measurements"][2][
    "oracle_measure"
].update({
    "pass_status": "pass",
    "pass_criterion": "conflict rate <= 10%",
})
_nested_graded_t14_violations = _measurement_relation_violations(
    _nested_graded_single_structure_t14
)
check("a single-structure T14 conflict row rejects a nested oracle verdict",
      any("oracle_measure.pass_status" in violation
          and "must remain informational" in violation
          for violation in _nested_graded_t14_violations), True)
check("a single-structure T14 conflict row rejects a nested oracle criterion",
      any("oracle_measure" in violation
          and "must not carry pass_criterion" in violation
          for violation in _nested_graded_t14_violations), True)

_graded_cohort_t14 = _copy.deepcopy(_t14_doc)
for _cohort_row in _graded_cohort_t14["evaluation_runs"][0]["measurements"]:
    _cohort_row.update({
        "scope": "cohort",
        "scope_selector": "round48 preregistered 41-entry cohort",
        "subject_ref": "cohort:round48:41-protein-entries",
    })
_cohort_conflict = _graded_cohort_t14["evaluation_runs"][0]["measurements"][2]
_cohort_conflict.update({
    "pass_status": "pass",
    "pass_criterion": "conflict rate <= 10%",
})
_cohort_conflict["oracle_measure"].update({
    "pass_status": "pass",
    "pass_criterion": "conflict rate <= 10%",
})
check("a cohort-scoped T14 conflict aggregate may apply the registered criterion",
      _measurement_relation_violations(_graded_cohort_t14), [])


def _cohort_verdict_doc(numerator, denominator, status, criterion):
    doc = _copy.deepcopy(_graded_cohort_t14)
    conflict = doc["evaluation_runs"][0]["measurements"][2]
    conflict["oracle_measure"].update({
        "value_numeric": numerator,
        "count": denominator,
        "pass_status": status,
        "pass_criterion": criterion,
    })
    conflict.update({
        "pass_status": status,
        "pass_criterion": criterion,
    })
    return doc


check("a T14 cohort rate exactly at 10% passes inclusively",
      _measurement_relation_violations(
          _cohort_verdict_doc(1, 10, "pass", "conflict rate <= 10%")), [])
check("a T14 cohort rate below 10% may pass with a caveat",
      _measurement_relation_violations(
          _cohort_verdict_doc(
              0, 10, "pass_with_caveat", "conflict rate ≤ 10 %")), [])
check("a T14 cohort rate above 10% fails the criterion",
      _measurement_relation_violations(
          _cohort_verdict_doc(
              2, 10, "fail_criterion", "conflict rate <= 10%")), [])

for _numerator, _spoofed_status in ((1, "fail_criterion"), (2, "pass")):
    _spoofed_cohort_verdict = _cohort_verdict_doc(
        _numerator, 10, _spoofed_status, "conflict rate <= 10%"
    )
    check(f"a {_numerator}/10 T14 cohort cannot claim {_spoofed_status}",
          any("inclusive 10% boundary" in violation
              and "pass_status" in violation
              for violation in _measurement_relation_violations(
                  _spoofed_cohort_verdict)), True)

_ambiguous_cohort_criterion = _cohort_verdict_doc(
    1, 10, "pass", "conflict rate <= 10% or <= 20%"
)
check("a T14 cohort grade must name only the registered <=10% criterion",
      any("unambiguous pass_criterion" in violation
          for violation in _measurement_relation_violations(
              _ambiguous_cohort_criterion)), True)

_negated_cohort_criterion = _cohort_verdict_doc(
    1, 10, "pass", "not conflict rate <= 10%"
)
check("a negated T14 cohort threshold is not the registered criterion",
      any("unambiguous pass_criterion" in violation
          for violation in _measurement_relation_violations(
              _negated_cohort_criterion)), True)

_nested_spoofed_cohort = _cohort_verdict_doc(
    1, 10, "pass", "conflict rate <= 10%"
)
_nested_spoofed_cohort["evaluation_runs"][0]["measurements"][2][
    "oracle_measure"
]["pass_status"] = "fail_criterion"
check("a nested T14 cohort verdict cannot invert the registered arithmetic",
      any("oracle_measure" in violation and "inclusive 10% boundary" in violation
          for violation in _measurement_relation_violations(
              _nested_spoofed_cohort)), True)

_informational_cohort = _cohort_verdict_doc(
    2, 10, "informational", ""
)
check("an informational T14 cohort observation remains non-gradeable",
      _measurement_relation_violations(_informational_cohort), [])

_unnamed_cohort_t14 = _copy.deepcopy(_graded_cohort_t14)
for _cohort_row in _unnamed_cohort_t14["evaluation_runs"][0]["measurements"]:
    _cohort_row["scope_selector"] = ""
check("a cohort-scoped T14 conflict aggregate must name its cohort",
      any("requires scope_selector naming the preregistered cohort" in violation
          for violation in _measurement_relation_violations(_unnamed_cohort_t14)),
      True)

_too_few_t14_refs = _copy.deepcopy(_t14_doc)
_too_few_t14_refs["evaluation_runs"][0]["measurements"][2][
    "derived_from_measurement_refs"
] = ["DERIVED_M_001"]
check("T14 conflict lineage requires two distinct source measurements",
      any("exactly two distinct derived_from_measurement_refs" in violation
          for violation in _measurement_relation_violations(_too_few_t14_refs)),
      True)

_wrong_t14_metric = _copy.deepcopy(_t14_doc)
_wrong_t14_metric["evaluation_runs"][0]["measurements"][0][
    "metric_definition_ref"
] = "T03_r-work"
check("T14 conflict sources must measure the candidate-count metric",
      any("must measure 'T14_asn_gln_his_flip_candidates_scored'" in violation
          for violation in _measurement_relation_violations(_wrong_t14_metric)),
      True)

_wrong_t14_task = _copy.deepcopy(_t14_doc)
_wrong_t14_task["evaluation_runs"][0]["measurements"][2][
    "catalog_task_ref"
] = "T03"
check("T14 conflict composite must remain a T14 measurement",
      any("must have catalog_task_ref 'T14'" in violation
          for violation in _measurement_relation_violations(_wrong_t14_task)),
      True)

_wrong_t14_tool = _copy.deepcopy(_t14_doc)
_wrong_t14_tool["evaluation_runs"][0]["measurements"][0][
    "oracle_tool_ref"
] = "gemmi sfcalc"
check("T14 conflict sources must use the canonical tool pair",
      any("source tools are" in violation and "expected" in violation
          for violation in _measurement_relation_violations(_wrong_t14_tool)),
      True)

for _invalid_numerator in (
    -1, 1.5, True, float("nan"), float("inf"), float("-inf"),
):
    _bad_t14_numerator = _copy.deepcopy(_t14_doc)
    _bad_t14_numerator["evaluation_runs"][0]["measurements"][2][
        "oracle_measure"
    ]["value_numeric"] = _invalid_numerator
    check(f"  T14 conflict numerator rejects {_invalid_numerator!r}",
          any("non-negative integer oracle_measure.value_numeric" in violation
              for violation in
              _measurement_relation_violations(_bad_t14_numerator)), True)

for _extra_carrier in ({"value_text": "zero"},
                       {"is_not_applicable": True}):
    _contradictory_t14 = _copy.deepcopy(_t14_doc)
    _contradictory_t14["evaluation_runs"][0]["measurements"][2][
        "oracle_measure"
    ].update(_extra_carrier)
    check(f"  T14 conflict composite rejects {_extra_carrier!r}",
          any("single non-negative integer" in violation
              for violation in
              _measurement_relation_violations(_contradictory_t14)), True)

for _extra_carrier in ({"value_text": "fourteen"},
                       {"is_not_applicable": True}):
    _contradictory_t14_source = _copy.deepcopy(_t14_doc)
    _contradictory_t14_source["evaluation_runs"][0]["measurements"][0][
        "oracle_measure"
    ].update(_extra_carrier)
    check(f"  T14 candidate source rejects {_extra_carrier!r}",
          any("integral oracle_measure.value_numeric candidate count" in violation
              for violation in _measurement_relation_violations(
                  _contradictory_t14_source)), True)

_too_many_t14_conflicts = _copy.deepcopy(_t14_doc)
_too_many_t14_conflicts["evaluation_runs"][0]["measurements"][2][
    "oracle_measure"
]["value_numeric"] = 15
check("T14 conflict count cannot exceed its eligible denominator",
      any("exceeds eligible denominator" in violation for violation in
          _measurement_relation_violations(_too_many_t14_conflicts)), True)

_wrong_t14_unit = _copy.deepcopy(_t14_doc)
_wrong_t14_unit["evaluation_runs"][0]["measurements"][2][
    "oracle_measure"
]["unit"] = "percent"
check("T14 conflict count requires count units",
      any("requires oracle_measure.unit 'count'" in violation
          for violation in _measurement_relation_violations(_wrong_t14_unit)),
      True)

_wrong_t14_source_unit = _copy.deepcopy(_t14_doc)
_wrong_t14_source_unit["evaluation_runs"][0]["measurements"][0][
    "oracle_measure"
]["unit"] = "percent"
check("T14 candidate source requires count units",
      any("must use oracle_measure.unit 'count'" in violation
          for violation in
          _measurement_relation_violations(_wrong_t14_source_unit)), True)

for _invalid_source_count in (
    0, -1, 1.5, True, float("nan"), float("inf"), float("-inf"),
):
    _bad_t14_source_count = _copy.deepcopy(_t14_doc)
    _bad_t14_source_count["evaluation_runs"][0]["measurements"][0][
        "oracle_measure"
    ]["value_numeric"] = _invalid_source_count
    check(f"  T14 candidate source rejects {_invalid_source_count!r}",
          any("integral oracle_measure.value_numeric candidate count" in violation
              for violation in
              _measurement_relation_violations(_bad_t14_source_count)), True)

_inflated_t14_denominator = _copy.deepcopy(_t14_doc)
_inflated_t14_denominator["evaluation_runs"][0]["measurements"][2][
    "oracle_measure"
]["count"] = 15
check("T14 conflict denominator cannot exceed a source candidate count",
      any("exceeds a source candidate count" in violation
          for violation in
          _measurement_relation_violations(_inflated_t14_denominator)), True)

_wrong_t14_carrier = _copy.deepcopy(_t14_doc)
_wrong_t14_carrier["evaluation_runs"][0]["measurements"][2][
    "oracle_tool_ref"
] = "phenix.model_vs_data"
check("T14 conflict carrier must expose its cctbx dependency",
      any("must conservatively identify its cctbx dependency" in violation
          for violation in _measurement_relation_violations(_wrong_t14_carrier)),
      True)

# Exercise the actual corpus through the same API, including ignored files because
# target_paths uses Path.rglob rather than a gitignore-aware search.
import yaml as _yaml
_live_records = [(_path, _yaml.safe_load(_path.read_text()))
                 for _path in integrity.target_paths()]
_live_index = integrity.build_corpus_indices(_live_records)
check("the live corpus has no ambiguous run/QDS/measurement/assumption ids",
      integrity.check_duplicate_ids(_live_index), [])
check("the live corpus satisfies typed measurement lineage",
      integrity.check_measurement_relations(_live_index), [])
check("the live corpus satisfies MeasurementValue catalog semantics",
      integrity.check_measurement_catalog_semantics(
          _live_index, enforce_legacy_policy=True), [])

_legacy_semantic_row_id = (
    "EVAL_1sar_cdba2c07_2026-04-24_M_water_rscc_distribution"
)
_legacy_semantic_targets = _live_index["measurement"].get(
    _legacy_semantic_row_id, [])
check("the content-addressed metric/task exception identifies one immutable row",
      len(_legacy_semantic_targets), 1)
_legacy_semantic_target = _legacy_semantic_targets[0]
_seen_semantic_exceptions = set()
check("the exact legacy metric/task defect consumes its registered exception",
      integrity._legacy_measurement_semantic_exception(
          "metric_task", _legacy_semantic_target,
          _seen_semantic_exceptions), True)
check("the metric/task exception consumption records its exact key",
      len(_seen_semantic_exceptions), 1)

def _live_measurements_replacing(row_id, target):
    measurements = {
        measurement_id: list(targets)
        for measurement_id, targets in _live_index["measurement"].items()
    }
    measurements[row_id] = [target]
    return {"measurement": measurements}

_changed_legacy_row = copy.deepcopy(_legacy_semantic_target.node)
_changed_legacy_row["notes"] += " Mutated after publication."
_changed_legacy_target = replace(
    _legacy_semantic_target, node=_changed_legacy_row)
_violations = integrity.check_measurement_catalog_semantics(
    _live_measurements_replacing(
        _legacy_semantic_row_id, _changed_legacy_target),
    enforce_legacy_policy=True,
)
check("changing any legacy row content invalidates the metric/task exception",
      any("applicable only to catalog tasks" in violation
          for violation in _violations), True)
check("a changed legacy row also makes its exception stale",
      any("exception was not consumed" in violation
          for violation in _violations), True)

_legacy_tool_task_row_id = "EVAL_synth_active_site_2026-04-26_M_005"
_legacy_tool_task_targets = _live_index["measurement"].get(
    _legacy_tool_task_row_id, [])
check("a content-addressed tool/task exception identifies one immutable row",
      len(_legacy_tool_task_targets), 1)
_legacy_tool_task_target = _legacy_tool_task_targets[0]
_seen_semantic_exceptions = set()
check("the exact legacy tool/task defect consumes its registered exception",
      integrity._legacy_measurement_semantic_exception(
          "tool_task", _legacy_tool_task_target,
          _seen_semantic_exceptions), True)
_changed_tool_task_row = copy.deepcopy(_legacy_tool_task_target.node)
_changed_tool_task_row["notes"] = "Mutated after publication."
_changed_tool_task_target = replace(
    _legacy_tool_task_target, node=_changed_tool_task_row)
_violations = integrity.check_measurement_catalog_semantics(
    _live_measurements_replacing(
        _legacy_tool_task_row_id, _changed_tool_task_target),
    enforce_legacy_policy=True,
)
check("changing any legacy row content invalidates the tool/task exception",
      any("serves only catalog tasks" in violation
          for violation in _violations), True)
check("a changed tool/task row also makes its exception stale",
      any("rule=tool_task" in violation and "exception was not consumed" in violation
          for violation in _violations), True)
_live_ref_violations = []
for _path, _doc in _live_records:
    _live_ref_violations += integrity.check_corpus_refs(
        _doc, _path.relative_to(REPO), _live_index)
check("the live corpus satisfies all new cross-record references",
      _live_ref_violations, [])

# Strict YAML loading must fail contextually even before an authority index exists.
_saved_catalog = integrity.CATALOG
_saved_structural_criteria = integrity.STRUCTURAL_CRITERIA
for _label, _corrupt_authority in (
    ("catalog", "catalog.yaml"),
    ("criterion registry", "structural_criteria.yaml"),
):
    with tempfile.TemporaryDirectory() as _tmp:
        _tmp_root = Path(_tmp)
        _catalog = _tmp_root / "catalog.yaml"
        _criteria = _tmp_root / "structural_criteria.yaml"
        _catalog.write_bytes(_saved_catalog.read_bytes())
        _criteria.write_bytes(_saved_structural_criteria.read_bytes())
        (_tmp_root / _corrupt_authority).write_bytes(b"\xff\xfe")
        integrity.CATALOG = _catalog
        integrity.STRUCTURAL_CRITERIA = _criteria
        _stderr = io.StringIO()
        with redirect_stderr(_stderr):
            _rc = integrity.main()
        _diagnostic = _stderr.getvalue()
    check(f"non-UTF-8 {_label} fails referential integrity", _rc, 1)
    check(f"non-UTF-8 {_label} has contextual authority diagnostic",
          "authoritative catalog/criterion registry is unreadable" in _diagnostic
          and "UnicodeDecodeError" in _diagnostic, True)
    check(f"non-UTF-8 {_label} has no traceback",
          "Traceback" in _diagnostic, False)
integrity.CATALOG = _saved_catalog
integrity.STRUCTURAL_CRITERIA = _saved_structural_criteria

with tempfile.TemporaryDirectory() as _tmp:
    _tmp_root = Path(_tmp)
    _bad_record = _tmp_root / "bad.yaml"
    _bad_record.write_bytes(b"\xff\xfe")
    _saved_integrity_repo = integrity.REPO
    _saved_target_paths = integrity.target_paths
    try:
        integrity.REPO = _tmp_root
        integrity.target_paths = lambda: [_bad_record]
        _stderr = io.StringIO()
        with redirect_stderr(_stderr):
            _rc = integrity.main()
        _diagnostic = _stderr.getvalue()
    finally:
        integrity.REPO = _saved_integrity_repo
        integrity.target_paths = _saved_target_paths
check("non-UTF-8 target record fails referential integrity", _rc, 1)
check("non-UTF-8 target record has contextual file diagnostic",
      "bad.yaml: unreadable (UnicodeDecodeError)" in _diagnostic, True)
check("non-UTF-8 target record has no traceback",
      "Traceback" in _diagnostic, False)

# --- #608: every structured row selected by subject can carry that subject --------
_schema = _yaml.safe_load((REPO / "schemas" / "protstruct_review.yaml").read_text())
check("MeasurementScope explicitly represents preregistered cohorts",
      "cohort" in _schema["enums"]["MeasurementScope"]["permissible_values"],
      True)
_subject_scoped_classes = (
    "SecondaryStructureAssignment", "DomainAssignment",
    "PredictionEnsembleQuality", "NmrEnsembleQuality", "PairwiseComparison",
    "ResidueOutlier", "DensityPeak", "FlaggedRegion", "PerResidueValue",
    "Ligand", "Site",
)
for _class_name in _subject_scoped_classes:
    check(f"{_class_name} can identify its concrete subject",
          "subject_ref" in _schema["classes"][_class_name]["attributes"], True)
check("PairwiseComparison can identify its concrete reference subject",
      "reference_subject_ref" in
      _schema["classes"]["PairwiseComparison"]["attributes"], True)


print(f"\nall guard unit tests passed ({PASSED} checks)")
