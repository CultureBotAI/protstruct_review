#!/usr/bin/env bash
# Validate every schema-governed record in the repo against schemas/protstruct_review.yaml.
# Exits non-zero on the first failure.
#
# Usage:
#   bash scripts/validate.sh
#   bash scripts/validate.sh --quiet   # suppress per-file "OK" lines
#
# This gate is hermetic: it does not use the network or invoke PHENIX/CCP4.
# Select its interpreter with PYTHON=/path/to/python3. All Python dependencies,
# including LinkML validation, are imported from that same interpreter.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCHEMA="${REPO_ROOT}/schemas/protstruct_review.yaml"
PYTHON="${PYTHON:-python3}"

QUIET=0
if [[ "${1:-}" == "--quiet" ]]; then
  QUIET=1
fi

fail() {
  echo "FAIL: $1" >&2
  exit 1
}

if ! command -v "${PYTHON}" >/dev/null 2>&1; then
  fail "Python interpreter '${PYTHON}' was not found. Bootstrap the development environment as documented in README.md, or set PYTHON=/path/to/python3."
fi

if ! dependency_error="$("${PYTHON}" -c '
import importlib
required = ("gemmi", "linkml", "numpy", "pydantic", "ruff", "scipy", "yaml")
missing = []
for name in required:
    try:
        importlib.import_module(name)
    except Exception as exc:
        missing.append(f"{name}: {exc}")
if missing:
    raise SystemExit("; ".join(missing))
' 2>&1)"; then
  fail "Python dependency preflight failed for ${PYTHON}: ${dependency_error}. Bootstrap the development environment as documented in README.md."
fi

# Calling the LinkML CLI through the selected interpreter prevents the common
# split-environment failure where `linkml-validate` and `python3` come from
# different installations (#398).
LINKML_VALIDATE=("${PYTHON}" -c "from linkml.validator.cli import cli; cli()")

validate_one() {
  local path="$1"
  if ! out="$("${LINKML_VALIDATE[@]}" --schema "${SCHEMA}" "${path}" 2>&1)"; then
    echo "${out}"
    fail "${path}"
  fi
  if echo "${out}" | grep -qE '^\[(ERROR|WARN)\]'; then
    echo "${out}"
    fail "${path}"
  fi
  if [[ "${QUIET}" == "0" ]]; then
    echo "OK   ${path#${REPO_ROOT}/}"
  fi
}

# 1. Canonical catalog + tool recommendations + tool assumptions
validate_one "${REPO_ROOT}/ref/catalog.yaml"
validate_one "${REPO_ROOT}/ref/tool_recommendations.yaml"
validate_one "${REPO_ROOT}/ref/tool_assumptions.yaml"

# 1b. Structural-criteria registry against its own schema (separate schema).
if ! out="$("${LINKML_VALIDATE[@]}" --schema "${REPO_ROOT}/schemas/structural_criteria.yaml" \
                            "${REPO_ROOT}/ref/structural_criteria.yaml" 2>&1)"; then
  echo "${out}"; fail "ref/structural_criteria.yaml"
fi
if echo "${out}" | grep -qE '^\[(ERROR|WARN)\]'; then echo "${out}"; fail "ref/structural_criteria.yaml"; fi
if [[ "${QUIET}" == "0" ]]; then echo "OK   ref/structural_criteria.yaml (structural_criteria schema)"; fi

# 2. Every record under data/ — both synthetic test fixtures
#    (data/examples/) and real per-artefact evals + QDS in
#    data/<provider>/<system>/.
#
#    The provider is discovered, not hardcoded. This loop used to name `coscientists`
#    while the comment above promised `data/<provider>/<system>/`, so records under any
#    other provider would never have been schema-checked. The count is asserted below
#    for the same reason: zero files validated used to be indistinguishable from all
#    files valid (#123).
# Capture discovery before consuming it so a `find`/`sort` failure is visible to
# `set -e`. This is Bash 3.2-compatible; `globstar` made the documented command
# fail on the default macOS shell before the first record was checked (#398).
if ! RECORD_FILES="$(find "${REPO_ROOT}/data" -type f \
    \( -name 'EVAL_*.yaml' -o -name 'QDS_*.yaml' \
       -o \( -path '*/data/examples/catalog/*' -name '*.yaml' \) \) \
    -print | LC_ALL=C sort)"; then
  fail "could not enumerate schema-governed records under data/"
fi

n_records=0
while IFS= read -r f; do
  [[ -z "${f}" ]] && continue
  validate_one "${f}"
  n_records=$((n_records + 1))
done <<< "${RECORD_FILES}"

if [[ "${n_records}" -eq 0 ]]; then
  fail "no records matched under data/ — record discovery found nothing, which is a
        gate failure, not a pass. Check data/ has not been moved or renamed."
fi

if [[ "${QUIET}" == "0" ]]; then
  echo "all ${n_records} records valid"
fi

# 3. Referential integrity (metric_definition_ref / oracle_tool_ref /
#    catalog_task_ref must resolve in ref/catalog.yaml)
if ! "${PYTHON}" "${REPO_ROOT}/scripts/check_referential_integrity.py"; then
  fail "referential integrity"
fi

# 3a. Catalog-derived task range, driver inventory, and runnable-wrapper claims
#     must agree across the authoritative documentation (#395).
if ! "${PYTHON}" "${REPO_ROOT}/scripts/check_documentation_state.py"; then
  fail "catalog-derived documentation state"
fi

# 3aa. Every distributed scientific fixture has an exact archive URL and
#      checksum, and no PHENIX documentation mirror is tracked (#400, #401).
if ! "${PYTHON}" "${REPO_ROOT}/scripts/check_fixture_provenance.py"; then
  fail "fixture provenance and publication boundary"
fi

# 3b. Negative-control series records reconcile (#312): screen/enrolled/reps
#     internal consistency, full-run manifests only in committed records
#     (#319), and round-doc headline figures matching the record (#311 class).
if ! "${PYTHON}" "${REPO_ROOT}/scripts/check_negative_control_records.py"; then
  fail "negative-control record reconciliation"
fi

# 3c. Trust invariant on committed QDS files (#315): no gradeable task rests
#     on cctbx-only or unclassifiable evidence without a named waiver;
#     pre-cutover history is grandfathered BY NAME, never silently.
if ! "${PYTHON}" "${REPO_ROOT}/scripts/check_qds_trust_invariant.py"; then
  fail "QDS trust invariant"
fi

# 3c-bis. pass_status semantics on committed evaluation records (#567): a status
#     that asserts a verdict must name the criterion it was judged against, and a
#     disagreement status must carry the claim it disagrees with. Without this a
#     verdict could live entirely in free-text `notes` — which is how one row
#     shipped marked `pass` with an empty criterion during the 1SAR review, and
#     how two identical rows were graded on opposite conclusions.
if ! "${PYTHON}" "${REPO_ROOT}/scripts/check_pass_status.py"; then
  fail "pass_status semantics"
fi

# 3d. NEXT_TASKS NC-table dates match the git merge trail — the
#     date/attribution class recurred in consecutive reconciliations
#     (#372, #386), and the repo's rule is to build the guard on the
#     second recurrence, not keep catching it by hand.
if ! "${PYTHON}" "${REPO_ROOT}/scripts/check_next_tasks_dates.py"; then
  fail "NEXT_TASKS dates out of step with the merge trail"
fi

# 4. QDS emitter regression tests (geometry-slot completeness, site/ligand/
#    per-residue/pairwise/tool-recs builder coverage, fail-hard negative test)
if ! "${PYTHON}" "${REPO_ROOT}/scripts/test_qds_emit.py"; then
  fail "qds_emit regression"
fi

# 4b. T15 SS-agreement pure-logic unit tests (parsing/collapse/agreement; no
#     mkdssp/biotite needed, so safe to run anywhere).
if ! "${PYTHON}" "${REPO_ROOT}/scripts/test_t15_ss_agreement.py"; then
  fail "t15_ss_agreement unit tests"
fi

# 4c. T16 interface-quality pure-logic unit tests (CAPRI bands / DockQ-JSON
#     extraction; no DockQ binary needed, so safe to run anywhere).
if ! "${PYTHON}" "${REPO_ROOT}/scripts/test_t16_interface_quality.py"; then
  fail "t16_interface_quality unit tests"
fi

# 4d. T17 NMR ensemble-precision pure-logic unit tests (mean-RMSF arithmetic;
#     no biotite/ensemble needed, so safe to run anywhere).
if ! "${PYTHON}" "${REPO_ROOT}/scripts/test_t17_nmr_ensemble.py"; then
  fail "t17_nmr_ensemble unit tests"
fi

# 4e. T17 restraint-summary pure-logic unit tests (wwPDB-report parsing;
#     no network / real report needed, so safe to run anywhere).
if ! "${PYTHON}" "${REPO_ROOT}/scripts/test_t17_restraint_summary.py"; then
  fail "t17_restraint_summary unit tests"
fi

# 4f. Tolerance-benchmark pure-logic unit tests (summary statistics + xtriage /
#     ctruncate log parsing; no network, PISA, PHENIX or CCP4 needed).
if ! "${PYTHON}" "${REPO_ROOT}/scripts/test_bench_tolerances.py"; then
  fail "bench tolerance unit tests"
fi

# 4g. The guards' own tests. check_registry_figures.py and
#     check_referential_integrity.py exist to catch other scripts' mistakes, and both
#     shipped with a hole (#116, #118) — one comparing four counts it derived itself
#     and never reading the registry, the other promising a structure_ref check in its
#     docstring that was never written. A guard needs a guard.
if ! "${PYTHON}" "${REPO_ROOT}/scripts/test_guards.py"; then
  fail "guard unit tests"
fi

# 4h. Record-tool parsing tests (ctruncate twin operators, TSV unit conversion).
if ! "${PYTHON}" "${REPO_ROOT}/scripts/test_record_tools.py"; then
  fail "record tool unit tests"
fi

# 4i. Every remaining scripts/test_*.py, discovered rather than enumerated (#228).
#     test_round_figures.py shipped in #188 with 18 checks and was never run here,
#     because this file names each suite by hand and one was forgotten -- silently,
#     as it always would be. A suite nothing executes is the repo's #2 class: a
#     guard that does not guard. Discovery cannot go stale the same way; the suites
#     above keep their named invocations so their failure messages stay specific.
for _suite in "${REPO_ROOT}"/scripts/test_*.py; do
  case "$(basename "${_suite}")" in
    test_qds_emit.py|test_t15_ss_agreement.py|test_t16_interface_quality.py| \
    test_t17_nmr_ensemble.py|test_t17_restraint_summary.py|test_bench_tolerances.py| \
    test_guards.py|test_record_tools.py|test_summary_coverage.py) continue ;;
  esac
  if ! "${PYTHON}" "${_suite}"; then
    fail "$(basename "${_suite}" .py)"
  fi
done

# 5. Published-view drift. ref/tasks_and_evaluations.{tsv,md} are views of
#    ref/catalog.yaml. Nothing else here compares them, so a task added to the
#    catalog alone used to ship silently (T15-T17 did exactly that).
#    The TSV is generated, so it must match byte-for-byte. The .md is
#    hand-written prose, so only check that every catalog task has a section.
TSV="${REPO_ROOT}/ref/tasks_and_evaluations.tsv"
MD="${REPO_ROOT}/ref/tasks_and_evaluations.md"
TSV_REGEN="$(mktemp)"
MODEL_REGEN="$(mktemp)"
trap 'rm -f "${TSV_REGEN}" "${MODEL_REGEN}"' EXIT

if ! "${PYTHON}" "${REPO_ROOT}/scripts/records_to_tsv.py" \
       "${REPO_ROOT}/ref/catalog.yaml" --kind catalog -o "${TSV_REGEN}" >/dev/null; then
  fail "tasks_and_evaluations.tsv could not be regenerated"
fi
if ! diff -q "${TSV}" "${TSV_REGEN}" >/dev/null; then
  diff "${TSV}" "${TSV_REGEN}" >&2 || true
  fail "ref/tasks_and_evaluations.tsv is stale — regenerate with: ${PYTHON} scripts/records_to_tsv.py ref/catalog.yaml --kind catalog -o ref/tasks_and_evaluations.tsv"
fi

# The schema is canonical and models.py is generated. Regenerate through the
# selected interpreter so drift cannot be hidden by a mismatched global CLI.
if ! (
  cd "${REPO_ROOT}"
  "${PYTHON}" -c '
from linkml.generators.pydanticgen import PydanticGenerator
from pathlib import Path
import sys
Path(sys.argv[2]).write_text(PydanticGenerator(sys.argv[1]).serialize())
' "schemas/protstruct_review.yaml" "${MODEL_REGEN}"
); then
  fail "protstruct_review/models.py could not be regenerated"
fi
if ! diff -q "${REPO_ROOT}/protstruct_review/models.py" "${MODEL_REGEN}" >/dev/null; then
  diff "${REPO_ROOT}/protstruct_review/models.py" "${MODEL_REGEN}" >&2 || true
  fail "protstruct_review/models.py is stale — regenerate with the pinned LinkML environment"
fi

# Enumerate task ids into a variable BEFORE the loop. A crash inside a
# `< <(...)` process substitution is NOT caught by `set -e` (it's a subshell),
# so reading the ids inline would let a malformed catalog yield zero ids and
# pass silently — the very drift this section guards against. Capturing first,
# with an explicit status check, makes an enumeration failure loud.
if ! TASK_IDS="$("${PYTHON}" -c '
import sys, yaml
doc = yaml.safe_load(open(sys.argv[1]))
tasks = doc.get("catalog_tasks", [])
if not tasks:
    sys.exit("no catalog_tasks found in " + sys.argv[1])
for task in tasks:
    print(task["id"])
' "${REPO_ROOT}/ref/catalog.yaml")"; then
  fail "could not enumerate catalog task ids from ref/catalog.yaml"
fi

missing=""
while IFS= read -r task_id; do
  [[ -z "${task_id}" ]] && continue
  grep -q "^### ${task_id} " "${MD}" || missing="${missing} ${task_id}"
done <<< "${TASK_IDS}"
if [[ -n "${missing}" ]]; then
  fail "ref/tasks_and_evaluations.md has no section for:${missing}"
fi

if [[ "${QUIET}" == "0" ]]; then
  echo "published views in sync with ref/catalog.yaml"
fi

# The two summary files -- NEXT_TASKS.md and ref/research/lessons.md -- must cover every
# round, and the counts they quote must match the record. Both checks used to live here
# as embedded python and were un-testable, which is how #157 shipped: each matched any
# `| ... |` line anywhere in the file, so an unrelated table or a fenced example row
# silently satisfied coverage for a round that was genuinely missing. They now live in a
# script with unit tests.
if ! "${PYTHON}" "${REPO_ROOT}/scripts/test_summary_coverage.py" > /dev/null; then
  "${PYTHON}" "${REPO_ROOT}/scripts/test_summary_coverage.py" >&2 || true
  fail "summary coverage unit tests"
fi
if ! "${PYTHON}" "${REPO_ROOT}/scripts/check_summary_coverage.py" > /dev/null 2>&1; then
  "${PYTHON}" "${REPO_ROOT}/scripts/check_summary_coverage.py" >&2 || true
  fail "summary files do not cover every round, or quote a count the record contradicts"
fi
if [[ "${QUIET}" == "0" ]]; then
  echo "summary files cover every round and their counts match the record"
fi

# Every bench_*.py must commit the entry set it ran on. The round-17 audit found that
# 7 of the registry's 20 `[benchmark]` rows quote a figure from a set that cannot be
# reconstructed, and the cause was systemic rather than per-row: only four scripts
# hardcoded their entries, the rest took an uncommitted `--ids-file` or globbed a cache,
# and no `ids.json` was committed anywhere in the repo. A `[benchmark]` provenance
# claims the number can be regenerated by re-running -- which is false unless the set
# ships with the script.
#
# This checks a set is DECLARED, not that it is complete: several are knowingly partial
# and say so via SET_IS_COMPLETE = False. A declared-but-incomplete set is the honest
# state and passes; an undeclared one does not.
if ! setless="$("${PYTHON}" -c '
import ast, pathlib, re, sys

repo = pathlib.Path(sys.argv[1])
missing = []
# SET_RECORD is written with double quotes. The pattern is assembled from chr() calls
# because this whole program sits inside a single-quoted shell string, so it cannot
# contain an apostrophe -- and a character class covering both quote styles would.
SET_RECORD_RE = ("^SET_RECORD" + chr(92) + "s*=" + chr(92) + "s*"
                 + chr(34) + "([^" + chr(34) + "]+)" + chr(34))
for script in sorted((repo / "scripts").glob("bench_*.py")):
    text = script.read_text()
    # DEFAULT_PAIRS covers the superposition benchmark, whose unit is a pair of ids;
    # KNOWN_IDS covers benchmarks whose set is recorded but not runnable as a default.
    declared = re.search(r"^(DEFAULT_SET|DEFAULT_PAIRS|KNOWN_IDS)\s*=", text, re.M)
    if declared:
        # A DECLARED set is not a USED one. bench_refinement_deltas.py declared its
        # set, mentioned it only inside a warning string, and went on globbing the
        # cache -- so the guarantee this gate exists to enforce was false for the one
        # script behind the most expensive partial record in the registry (#78).
        # Require at least one reference outside the assignment and outside a print().
        name = declared.group(1)
        tree = ast.parse(text)
        prints = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "print":
                prints.update(id(n) for n in ast.walk(node))
        used = any(isinstance(n, ast.Name) and n.id == name
                   and isinstance(n.ctx, ast.Load) and id(n) not in prints
                   for n in ast.walk(tree))
        if used:
            continue
        # Two benchmarks record a set they cannot run from: the L-test has no id
        # argument at all (it reads a prior run logs), and the ordered-core script
        # takes file paths. They opt out via SET_NOT_RUNNABLE, which carries the
        # reason in the file rather than as a special case hidden in this gate.
        if re.search(r"^SET_NOT_RUNNABLE\s*=\s*" + chr(34), text, re.M):
            continue
        missing.append(script.name + " (" + name + " declared but never used)")
        continue
    # SET_RECORD names a committed data file holding the set instead -- the EM
    # benchmark keeps its entries in a cumulative TSV, which is stronger than a
    # hardcoded list because it also records what was skipped. The file must exist,
    # or the declaration is a promise rather than a record.
    record = re.search(SET_RECORD_RE, text, re.M)
    if record and (repo / record.group(1)).exists():
        continue
    missing.append(script.name + ("" if not record else " (SET_RECORD file missing)"))
print(" ".join(missing))
' "${REPO_ROOT}")"; then
  fail "could not check benchmark entry sets"
fi
if [[ -n "${setless// /}" ]]; then
  fail "bench script(s) do not commit the entry set they run on: ${setless}"
fi
if [[ "${QUIET}" == "0" ]]; then
  echo "every bench_*.py commits its entry set"
fi

# `test_toolchain.py`, discovered by the generic unit-suite loop above, enforces
# that tool paths exist only in scripts/toolchain.py and that no runner grows a
# new shell-interpolated subprocess boundary (#394).

# The registry quotes figures computed from ref/research/data/em_refinement_deltas.tsv,
# and that file grows every round -- so those figures age silently. Three instances were
# caught (#72, #107, #113), all three by accident during reviews of unrelated work.
# Catching a class three times by luck is not a process.
#
# This recomputes each one and fails if the registry's text no longer matches. It also
# fails if the quoted literal has been REWORDED, because a gate that only compares
# numbers is defeated by a rewrite -- which is exactly how a figure escapes notice.
if ! "${PYTHON}" "${REPO_ROOT}/scripts/check_registry_figures.py" > /dev/null 2>&1; then
  "${PYTHON}" "${REPO_ROOT}/scripts/check_registry_figures.py" >&2 || true
  fail "registry figures no longer match ref/research/data/em_refinement_deltas.tsv"
fi
if [[ "${QUIET}" == "0" ]]; then
  echo "registry figures match the per-entry data"
fi

# A round document's claims about its OWN findings age and mis-state the same way the
# registry's did. #130 ("three high" when four were labelled high) and #135 ("a 20-file
# audit round" that was 19) were both caught by review rather than by a check, and both
# were wrong in the direction that flatters the round.
#
# The findings themselves live in a committed TSV rather than being fetched at gate
# time: `gh` is not available or authenticated everywhere, and a check that silently
# skips is a guard that does not guard. Refresh it deliberately with
# `${PYTHON} scripts/check_round_figures.py --refresh`.
if ! "${PYTHON}" "${REPO_ROOT}/scripts/check_round_figures.py" > /dev/null 2>&1; then
  "${PYTHON}" "${REPO_ROOT}/scripts/check_round_figures.py" >&2 || true
  fail "a round document's figures no longer match ref/research/data/round_findings.tsv"
fi
if [[ "${QUIET}" == "0" ]]; then
  echo "round-document figures match the findings record"
fi

# Every id a round refined must appear in its committed selection record. #255 was a
# refined, usable entry (1A0C) present in round37_xray_deltas.json but dropped from
# round37_xray_selection.json, so the write-up's "21 selected" could not be checked
# against its own artefact -- and nothing reconciled the two files, so the gate passed
# for the whole life of round 37 (#261). The check is one-directional: selection may
# hold MORE ids than the deltas (fetch rejects), never fewer.
if ! "${PYTHON}" "${REPO_ROOT}/scripts/test_selection_deltas.py" > /dev/null; then
  "${PYTHON}" "${REPO_ROOT}/scripts/test_selection_deltas.py" >&2 || true
  fail "selection/deltas guard unit tests"
fi
if ! "${PYTHON}" "${REPO_ROOT}/scripts/check_selection_deltas.py" > /dev/null 2>&1; then
  "${PYTHON}" "${REPO_ROOT}/scripts/check_selection_deltas.py" >&2 || true
  fail "a round refined an entry its selection record does not list"
fi
if [[ "${QUIET}" == "0" ]]; then
  echo "selection records account for every refined entry"
fi

# The driving examples and benchmark docstrings must not restate a retired registry value
# as a live threshold. A Codex review found CA RMSD graded at 0.10 A (§3 says 0.03), and
# ΔRMSD/CC_mask/d_FSC_model at their round-5 values, in driving_example*.md and several
# bench_*.py docstrings, with nothing reconciling the registry against its consumers. The
# check re-derives each value from the registry (so a future §-change fails here too) and
# flags retired literals stated as current.
if ! "${PYTHON}" "${REPO_ROOT}/scripts/test_driver_thresholds.py" > /dev/null; then
  "${PYTHON}" "${REPO_ROOT}/scripts/test_driver_thresholds.py" >&2 || true
  fail "driver-threshold guard unit tests"
fi
if ! "${PYTHON}" "${REPO_ROOT}/scripts/check_driver_thresholds.py" > /dev/null 2>&1; then
  "${PYTHON}" "${REPO_ROOT}/scripts/check_driver_thresholds.py" >&2 || true
  fail "driver thresholds: a consumer restates a retired value, or ref/thresholds_and_standards.yaml is malformed"
fi
if [[ "${QUIET}" == "0" ]]; then
  echo "driver/docstring thresholds match the registry"
fi

# Keep the initial lint boundary intentionally narrow: syntax/runtime-name
# failures and Pyflakes correctness checks. Generated models and committed
# research artifacts are excluded in pyproject.toml (#397).
if ! "${PYTHON}" -m ruff check "${REPO_ROOT}"; then
  fail "Ruff correctness checks"
fi
if [[ "${QUIET}" == "0" ]]; then
  echo "Ruff correctness checks passed"
fi
