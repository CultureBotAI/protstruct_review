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

import importlib.util
import sys
from pathlib import Path

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


# --- Round 26: the status vocabulary is declared, not inferred from predicates -----
# Before #139 the vocabulary existed only as prefixes spread across four predicates in
# the READER, while the WRITER that produces the values lived in another file -- the
# shape of #136. 28 of the 97 rows matched none of those prefixes and were counted as
# `attempted` by DEFAULT (`not startswith("skipped")`), which happened to be right for
# them and would not be for the next status added.

import copy

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
_qds_doc = {"quality_data_sheets": [{
    "id": "QDS_new",
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

# Exercise the actual corpus through the same API, including ignored files because
# target_paths uses Path.rglob rather than a gitignore-aware search.
import yaml as _yaml
_live_records = [(_path, _yaml.safe_load(_path.read_text()))
                 for _path in integrity.target_paths()]
_live_index = integrity.build_corpus_indices(_live_records)
check("the live corpus has no ambiguous run/QDS/measurement/assumption ids",
      integrity.check_duplicate_ids(_live_index), [])
_live_ref_violations = []
for _path, _doc in _live_records:
    _live_ref_violations += integrity.check_corpus_refs(
        _doc, _path.relative_to(REPO), _live_index)
check("the live corpus satisfies all new cross-record references",
      _live_ref_violations, [])

# --- #608: every structured row selected by subject can carry that subject --------
_schema = _yaml.safe_load((REPO / "schemas" / "protstruct_review.yaml").read_text())
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
