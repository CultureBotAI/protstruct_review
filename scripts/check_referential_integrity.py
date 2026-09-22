#!/usr/bin/env python3
"""Check that every reference in committed YAML records resolves.

`linkml-validate` enforces type and enum constraints but does not enforce
that string-typed references point at declared instances. This script
walks every YAML record under `ref/` and `data/examples/` and verifies:

  - every `metric_definition_ref` resolves in `ref/catalog.yaml::metric_definitions`
  - every `oracle_tool_ref` / `tool_ref` resolves in `ref/catalog.yaml::tools`
  - every `catalog_task_ref` / `catalog_tasks_applied[]` is a known T0NN id
  - every `structure_ref` resolves in `ref/catalog.yaml::structures` or the same
    record's structures[] WHEN either exists; neither does today, so it falls back
    to requiring every nested `structure_ref` to match its own record's. See
    `check_structure_refs` — this bullet described a check that was never
    implemented until #118.
  - EvaluationRun, MeasurementValue, and run-owned Assumption ids are unique across
    the corpus, so a string reference never resolves by file ordering
  - QDS input/source refs, superseded assumptions, and `EVAL_*` evidence refs resolve;
    paired source run/measurement refs name the run that actually owns the measurement

Exits non-zero with a per-violation report on the first miss. Wired into
`scripts/validate.sh` so `linkml-validate` and the integrity check both
run before any commit.

Closes Codex finding #3 (medium): "Metric references are not enforced,
and the committed example already drifts from the canonical catalog."
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import yaml


REPO = Path(__file__).resolve().parent.parent
CATALOG = REPO / "ref" / "catalog.yaml"

KNOWN_TASK_IDS = {f"T{n:02d}" for n in range(1, 18)}


@dataclass(frozen=True)
class RefTarget:
    """One corpus object that can be named by a string reference."""

    file: Path
    pointer: str
    owner_run_id: str | None = None
    run_date: Any = None
    superseded_assumption_refs: tuple[str, ...] = ()


CorpusIndices = dict[str, dict[str, list[RefTarget]]]


def load_catalog_indices() -> dict[str, set[str]]:
    """Return {kind: set_of_known_ids} indices from the canonical catalog."""
    doc = yaml.safe_load(CATALOG.read_text())
    return {
        "metric": {m["id"] for m in doc.get("metric_definitions", [])},
        "tool": {t["id"] for t in doc.get("tools", [])},
        "task": KNOWN_TASK_IDS,
        # Empty today -- ref/catalog.yaml declares no `structures:` collection. The
        # index is built anyway so `check_structure_refs` starts resolving against it
        # the moment one is added, rather than needing to be remembered then.
        "structure": {s["id"] for s in doc.get("structures", []) or []},
    }


def target_paths() -> list[Path]:
    """Return every YAML document covered by this repository guard."""
    targets = [
        CATALOG,
        REPO / "ref" / "tool_recommendations.yaml",
        REPO / "ref" / "tool_assumptions.yaml",
    ]
    # Every provider, not just `coscientists`. Path.rglob intentionally includes
    # ignored files too; a dangling ref must not become invisible due to gitignore.
    targets += sorted((REPO / "data").rglob("*.yaml"))
    return sorted({path for path in targets if path.exists()})


def _shown(path: Path) -> Path:
    """Use a repository-relative path in diagnostics when possible."""
    try:
        return path.resolve().relative_to(REPO.resolve())
    except ValueError:
        return path


def _add_target(
    index: dict[str, list[RefTarget]], object_id: Any, target: RefTarget
) -> None:
    if isinstance(object_id, str):
        index.setdefault(object_id, []).append(target)


def build_corpus_indices(records: Sequence[tuple[Path, Any]]) -> CorpusIndices:
    """Index cross-document reference targets and retain their owning runs."""
    indices: CorpusIndices = {
        "evaluation_run": {},
        "measurement": {},
        "assumption": {},
    }

    def add_assumptions(node: Any, path: str, run: dict[str, Any], file: Path) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                child = f"{path}.{key}"
                if key == "assumptions" and isinstance(value, list):
                    for i, assumption in enumerate(value):
                        if not isinstance(assumption, dict):
                            continue
                        _add_target(
                            indices["assumption"],
                            assumption.get("id"),
                            RefTarget(
                                file=file,
                                pointer=f"{child}[{i}]",
                                owner_run_id=run.get("id"),
                                run_date=run.get("run_date"),
                            ),
                        )
                add_assumptions(value, child, run, file)
        elif isinstance(node, list):
            for i, value in enumerate(node):
                add_assumptions(value, f"{path}[{i}]", run, file)

    for file, doc in records:
        if not isinstance(doc, dict):
            continue
        for i, run in enumerate(doc.get("evaluation_runs") or []):
            if not isinstance(run, dict):
                continue
            run_path = f"$.evaluation_runs[{i}]"
            superseded = tuple(
                ref
                for ref in run.get("superseded_assumption_refs") or []
                if isinstance(ref, str)
            )
            _add_target(
                indices["evaluation_run"],
                run.get("id"),
                RefTarget(
                    file=file,
                    pointer=run_path,
                    owner_run_id=run.get("id"),
                    run_date=run.get("run_date"),
                    superseded_assumption_refs=superseded,
                ),
            )
            for j, measurement in enumerate(run.get("measurements") or []):
                if not isinstance(measurement, dict):
                    continue
                _add_target(
                    indices["measurement"],
                    measurement.get("id"),
                    RefTarget(
                        file=file,
                        pointer=f"{run_path}.measurements[{j}]",
                        owner_run_id=run.get("id"),
                        run_date=run.get("run_date"),
                    ),
                )
            add_assumptions(run, run_path, run, file)
    return indices


def check_duplicate_ids(indices: CorpusIndices) -> list[str]:
    """Report ids whose references would have more than one possible target."""
    labels = {
        "evaluation_run": "EvaluationRun",
        "measurement": "MeasurementValue",
        "assumption": "Assumption",
    }
    violations: list[str] = []
    for kind, label in labels.items():
        for object_id, targets in sorted(indices[kind].items()):
            if len(targets) < 2:
                continue
            locations = ", ".join(
                f"{_shown(target.file)}:{target.pointer}" for target in targets
            )
            violations.append(
                f"duplicate {label} id {object_id!r} at {locations}; references are ambiguous"
            )
    return violations


def _resolve(
    object_id: str,
    kind: str,
    indices: CorpusIndices,
    rel: Path,
    path: str,
    violations: list[str],
) -> RefTarget | None:
    labels = {
        "evaluation_run": "EvaluationRun",
        "measurement": "MeasurementValue",
        "assumption": "Assumption",
    }
    targets = indices[kind].get(object_id, [])
    if not targets:
        violations.append(f"{rel}: {path} = {object_id!r} does not resolve to a {labels[kind]}")
        return None
    if len(targets) > 1:
        violations.append(
            f"{rel}: {path} = {object_id!r} is ambiguous ({len(targets)} {labels[kind]} ids)"
        )
        return None
    return targets[0]


def _iso_date(value: Any) -> str | None:
    """Normalize YAML date objects/strings for strict ISO-date comparison."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return str(value.isoformat())[:10]
    text = str(value)
    return text[:10] if len(text) >= 10 else None


def check_corpus_refs(doc: Any, rel: Path, indices: CorpusIndices) -> list[str]:
    """Resolve references whose targets can live in another YAML document."""
    violations: list[str] = []
    if not isinstance(doc, dict):
        return violations

    def check(node: Any, path: str, current_run: dict[str, Any] | None = None) -> None:
        if isinstance(node, dict):
            source_run_ref = node.get("source_evaluation_run_ref")
            source_measurement_ref = node.get("source_measurement_ref")
            source_run = None
            source_measurement = None
            if isinstance(source_run_ref, str):
                source_run = _resolve(
                    source_run_ref,
                    "evaluation_run",
                    indices,
                    rel,
                    f"{path}.source_evaluation_run_ref",
                    violations,
                )
            if isinstance(source_measurement_ref, str):
                source_measurement = _resolve(
                    source_measurement_ref,
                    "measurement",
                    indices,
                    rel,
                    f"{path}.source_measurement_ref",
                    violations,
                )
            if source_run is not None and source_measurement is not None:
                if source_measurement.owner_run_id != source_run_ref:
                    violations.append(
                        f"{rel}: {path}.source_measurement_ref = {source_measurement_ref!r} "
                        f"belongs to {source_measurement.owner_run_id!r}, not paired "
                        f"source_evaluation_run_ref {source_run_ref!r}"
                    )

            for key, value in node.items():
                child = f"{path}.{key}"
                if key == "evaluation_runs" and isinstance(value, list):
                    for i, run in enumerate(value):
                        check(run, f"{child}[{i}]", run if isinstance(run, dict) else None)
                    continue
                if key == "derived_from_evaluation_run_refs" and isinstance(value, list):
                    for i, ref in enumerate(value):
                        if isinstance(ref, str):
                            _resolve(
                                ref,
                                "evaluation_run",
                                indices,
                                rel,
                                f"{child}[{i}]",
                                violations,
                            )
                elif key == "superseded_assumption_refs" and isinstance(value, list):
                    for i, ref in enumerate(value):
                        if not isinstance(ref, str):
                            continue
                        target = _resolve(
                            ref,
                            "assumption",
                            indices,
                            rel,
                            f"{child}[{i}]",
                            violations,
                        )
                        if target is None or current_run is None:
                            continue
                        current_id = current_run.get("id")
                        old_date = _iso_date(target.run_date)
                        current_date = _iso_date(current_run.get("run_date"))
                        if target.owner_run_id == current_id:
                            violations.append(
                                f"{rel}: {child}[{i}] = {ref!r} is owned by the same "
                                f"EvaluationRun {current_id!r}, not an earlier run"
                            )
                        elif old_date is None or current_date is None or old_date >= current_date:
                            violations.append(
                                f"{rel}: {child}[{i}] = {ref!r} is owned by "
                                f"{target.owner_run_id!r} dated {old_date!r}, not a run "
                                f"earlier than {current_id!r} dated {current_date!r}"
                            )
                elif key == "evidence_refs" and isinstance(value, list):
                    for i, ref in enumerate(value):
                        # Citation keys and repository paths intentionally remain open
                        # strings. EVAL_* is the reserved namespace for EvaluationRun ids.
                        if isinstance(ref, str) and ref.startswith("EVAL_"):
                            _resolve(
                                ref,
                                "evaluation_run",
                                indices,
                                rel,
                                f"{child}[{i}]",
                                violations,
                            )

                # Source refs were resolved together above so ownership can be checked.
                if key not in {"source_evaluation_run_ref", "source_measurement_ref"}:
                    check(value, child, current_run)
        elif isinstance(node, list):
            for i, value in enumerate(node):
                check(value, f"{path}[{i}]", current_run)

    check(doc, "$")

    # Supersession is an operation on an ordered emitter input, not just a date claim.
    # Whenever a QDS includes a superseding run, the run owning the withdrawn
    # assumption must also be present earlier in that same input list.
    for qds_i, qds in enumerate(doc.get("quality_data_sheets") or []):
        if not isinstance(qds, dict):
            continue
        refs = qds.get("derived_from_evaluation_run_refs") or []
        positions = {ref: i for i, ref in enumerate(refs) if isinstance(ref, str)}
        for run_i, run_ref in enumerate(refs):
            if not isinstance(run_ref, str):
                continue
            run_targets = indices["evaluation_run"].get(run_ref, [])
            if len(run_targets) != 1:
                continue
            for assumption_ref in run_targets[0].superseded_assumption_refs:
                assumption_targets = indices["assumption"].get(assumption_ref, [])
                if len(assumption_targets) != 1:
                    continue
                owner = assumption_targets[0].owner_run_id
                if owner not in positions or positions[owner] >= run_i:
                    violations.append(
                        f"{rel}: $.quality_data_sheets[{qds_i}]."
                        f"derived_from_evaluation_run_refs[{run_i}] = {run_ref!r} "
                        f"supersedes {assumption_ref!r}, but its owner {owner!r} is not "
                        "an earlier input to this QDS"
                    )
    return violations


def walk(node: Any, path: str = "$") -> Iterable[tuple[str, str, Any]]:
    """Yield (json-pointer-style path, key, value) tuples for every leaf."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from walk(v, f"{path}.{k}")
            if not isinstance(v, (dict, list)):
                yield path, k, v
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, f"{path}[{i}]")


def check_record(yaml_path: Path, indices: dict[str, set[str]]) -> list[str]:
    """Return a list of human-readable violation messages for one record."""
    doc = yaml.safe_load(yaml_path.read_text())
    if doc is None:
        return []
    violations: list[str] = []
    rel = yaml_path.relative_to(REPO)

    # Local indices for refs that may resolve within the same document.
    local_metric_ids = {m["id"] for m in doc.get("metric_definitions", []) or []}
    local_tool_ids = {t["id"] for t in doc.get("tools", []) or []}
    local_structure_ids = {s["id"] for s in doc.get("structures", []) or []}

    metric_ok = indices["metric"] | local_metric_ids
    tool_ok = indices["tool"] | local_tool_ids
    task_ok = indices["task"]

    # The schema declares `agent_claim`, `oracle_measure`, `delta` as
    # TypedMeasurementValue (not refs), so checking by-key is naive but
    # safe — the keys we look for are unambiguous in this schema.
    REF_KEYS = {
        "metric_definition_ref": ("metric", metric_ok),
        "oracle_tool_ref": ("tool", tool_ok),
        "tool_ref": ("tool", tool_ok),
        "catalog_task_ref": ("task", task_ok),
    }
    LIST_REF_KEYS = {
        "catalog_tasks_applied": ("task", task_ok),
        "catalog_task_refs": ("task", task_ok),
        "phenix_tool_refs": ("tool", tool_ok),
        "oracle_tool_refs": ("tool", tool_ok),
        "metric_definition_refs": ("metric", metric_ok),
    }

    def check(node: Any, path: str = "$") -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k in REF_KEYS and isinstance(v, str):
                    kind, allowed = REF_KEYS[k]
                    if v not in allowed:
                        violations.append(f"{rel}: {path}.{k} = {v!r} not in known {kind} ids")
                if k in LIST_REF_KEYS and isinstance(v, list):
                    kind, allowed = LIST_REF_KEYS[k]
                    for i, item in enumerate(v):
                        if isinstance(item, str) and item not in allowed:
                            violations.append(
                                f"{rel}: {path}.{k}[{i}] = {item!r} not in known {kind} ids"
                            )
                check(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                check(v, f"{path}[{i}]")

    check(doc)
    violations += check_structure_refs(doc, rel, indices["structure"] | local_structure_ids)
    return violations


# Top-level collections whose members each carry their own `structure_ref`, under which
# every nested `structure_ref` must agree.
RECORD_COLLECTIONS = ("evaluation_runs", "quality_data_sheets", "agent_artifacts")


def check_structure_refs(doc: Any, rel: Path, declared: set[str]) -> list[str]:
    """Check `structure_ref` — the one ref this script's docstring promised and skipped.

    The promise was "resolves either in `ref/catalog.yaml::structures` or in the same
    record's structures[]". Neither collection exists anywhere in the repo: the schema
    declares `structure_ref: {range: Structure}` but nothing instantiates a `Structure`,
    so the check as written had no index to resolve against and was silently never
    implemented (#118) -- while `local_structure_ids` sat computed and unused above.

    So it resolves against those collections WHEN they exist, and otherwise falls back
    to the invariant that does hold today and catches the same typo: within one record
    (one evaluation_run, one QDS), every nested `structure_ref` must equal that record's
    own. An EVAL is about one structure; `ligands[].structure_ref` naming a different
    one is a defect whether or not a `structures:` collection is ever added.
    """
    violations: list[str] = []
    if not isinstance(doc, dict):
        return violations

    def nested_refs(node: Any, path: str) -> Iterable[tuple[str, str]]:
        if isinstance(node, dict):
            for k, v in node.items():
                if k == "structure_ref" and isinstance(v, str):
                    yield f"{path}.{k}", v
                else:
                    yield from nested_refs(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                yield from nested_refs(v, f"{path}[{i}]")

    for collection in RECORD_COLLECTIONS:
        for i, record in enumerate(doc.get(collection) or []):
            if not isinstance(record, dict):
                continue
            base = f"$.{collection}[{i}]"
            own = record.get("structure_ref")
            for path, value in nested_refs(record, base):
                if declared and value not in declared:
                    violations.append(
                        f"{rel}: {path} = {value!r} not in known structure ids")
                elif not declared and own and value != own:
                    violations.append(
                        f"{rel}: {path} = {value!r} does not match the record's own "
                        f"structure_ref {own!r}")
    return violations


def main() -> int:
    indices = load_catalog_indices()
    failed = False
    records: list[tuple[Path, Any]] = []
    for path in target_paths():
        try:
            records.append((path, yaml.safe_load(path.read_text())))
        except yaml.YAMLError as e:
            print(f"FAIL: {path.relative_to(REPO)}: YAML parse error: {e}", file=sys.stderr)
            failed = True

    corpus_indices = build_corpus_indices(records)
    for violation in check_duplicate_ids(corpus_indices):
        print(f"FAIL: {violation}", file=sys.stderr)
        failed = True

    for path, doc in records:
        violations = check_record(path, indices)
        violations += check_corpus_refs(doc, path.relative_to(REPO), corpus_indices)
        if violations:
            failed = True
            for v in violations:
                print(f"FAIL: {v}", file=sys.stderr)
        else:
            print(f"OK   {path.relative_to(REPO)}")

    if failed:
        print("\nrefs unresolved — fix the violations above or extend ref/catalog.yaml", file=sys.stderr)
        return 1
    print("all references resolve")
    return 0


if __name__ == "__main__":
    sys.exit(main())
