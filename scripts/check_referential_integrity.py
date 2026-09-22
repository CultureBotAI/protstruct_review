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
  - EvaluationRun, QualityDataSheet, MeasurementValue, and run-owned Assumption ids
    are unique across the corpus, so a string reference never resolves by file ordering
  - QDS input/source refs, superseded assumptions, and `EVAL_*` evidence refs resolve;
    paired source run/measurement refs name an input run that actually owns the
    measurement, and every wrapped scalar exactly matches that source measurement
  - repository-path evidence refs stay inside the repository and resolve to a file

Exits non-zero with a per-violation report on the first miss. Wired into
`scripts/validate.sh` so `linkml-validate` and the integrity check both
run before any commit.

Closes Codex finding #3 (medium): "Metric references are not enforced,
and the committed example already drifts from the canonical catalog."
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Iterable, Sequence
from urllib.parse import urlsplit

import yaml

import qds_emit_contract_v1


REPO = Path(__file__).resolve().parent.parent
CATALOG = REPO / "ref" / "catalog.yaml"

KNOWN_TASK_IDS = {f"T{n:02d}" for n in range(1, 18)}
EVIDENCE_FILE_SUFFIXES = {
    ".cif",
    ".csv",
    ".json",
    ".log",
    ".map",
    ".md",
    ".mtz",
    ".out",
    ".pdb",
    ".tsv",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}


@dataclass(frozen=True)
class RefTarget:
    """One corpus object that can be named by a string reference."""

    file: Path
    pointer: str
    owner_run_id: str | None = None
    run_date: Any = None
    superseded_assumption_refs: tuple[str, ...] = ()
    source_collection: str | None = None
    node: dict[str, Any] | None = None
    source_tool_families: tuple[tuple[str, str], ...] = ()


CorpusIndices = dict[str, dict[str, list[RefTarget]]]


# Structured rows copied verbatim by qds_emit. A current QDS carries an
# explicit source-run/source-row pair on each one; the guard reconstructs the
# emitted row from that source instead of trusting the committed copy.
SOURCE_STRUCTURED_ROW_KEYS = (
    "residue_outliers",
    "density_peaks",
    "flagged_regions",
    "per_residue_values",
    "secondary_structure_assignments",
    "domain_assignments",
    "interface_qualities",
    "prediction_ensemble_qualities",
    "nmr_ensemble_qualities",
    "pairwise_comparisons",
)

QDS_COPIED_ROW_SOURCE_KEYS = {
    "outliers": "residue_outliers",
    "density_peaks": "density_peaks",
    "flagged_regions": "flagged_regions",
    "lddt_per_residue": "per_residue_values",
    "displacement_per_residue_a": "per_residue_values",
    "ramachandran_z_per_residue": "per_residue_values",
    "rsrz_per_residue": "per_residue_values",
    "rscc_per_residue": "per_residue_values",
    "b_factor_z_per_residue": "per_residue_values",
    "secondary_structure_per_residue": "per_residue_values",
    "fsc_q_per_residue": "per_residue_values",
    "secondary_structure_assignments": "secondary_structure_assignments",
    "domain_assignments": "domain_assignments",
    "interface_qualities": "interface_qualities",
    "prediction_ensemble_qualities": "prediction_ensemble_qualities",
    "nmr_ensemble_qualities": "nmr_ensemble_qualities",
    "pairwise_comparisons": "pairwise_comparisons",
}


def _routed_scalar_slots(
    routing_table: dict[str, Any],
) -> frozenset[tuple[str, str]]:
    """Return emitter-owned QDS summary slots for one frozen contract.

    A committed scalar cannot decide whether it is governed merely by retaining
    ``metric_definition_ref``: deleting that field together with both source refs
    would otherwise make a forged value look like an unwrapped scalar.  The QDS
    block/slot path is fixed by the emitter routing table and remains authoritative
    even when every self-describing field on the value has been removed.
    """
    slots: set[tuple[str, str]] = set()
    for destination in routing_table.values():
        destinations = destination if isinstance(destination, list) else [destination]
        slots.update(destinations)
    return frozenset(slots)


QDS_ROUTED_SCALAR_SLOTS_BY_CONTRACT = {
    "1": _routed_scalar_slots(qds_emit_contract_v1.METRIC_TO_QDS_SLOT),
}


def _qds_contract_routing(
    qds: dict[str, Any] | None,
) -> tuple[frozenset[tuple[str, str]], frozenset[str]]:
    """Return routing owned by the QDS's retained emitter contract.

    Current-emitter routing is intentionally not a fallback: a future route must
    not retroactively reinterpret a contract-1 structured payload as a scalar.
    Missing/unsupported contracts are diagnosed by the QDS trust guard.
    """
    version = str((qds or {}).get("emitter_contract_version") or "")
    slots = QDS_ROUTED_SCALAR_SLOTS_BY_CONTRACT.get(version, frozenset())
    return slots, frozenset(block for block, _slot in slots)


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
    targets += sorted((REPO / "data").rglob("*.yml"))
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
        "quality_data_sheet": {},
        "measurement": {},
        "structured_row": {},
        "assumption": {},
        "qds_replay_pin": {},
        "qds_replay_pin_target": {},
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
                                node=assumption,
                            ),
                        )
                add_assumptions(value, child, run, file)
        elif isinstance(node, list):
            for i, value in enumerate(node):
                add_assumptions(value, f"{path}[{i}]", run, file)

    for file, doc in records:
        if not isinstance(doc, dict):
            continue
        source_tool_families = tuple(
            sorted(
                (str(tool["id"]), str(tool["family"]))
                for tool in doc.get("tools", []) or []
                if isinstance(tool, dict) and tool.get("id") and tool.get("family")
            )
        )
        for i, pin in enumerate(doc.get("qds_replay_pins") or []):
            if not isinstance(pin, dict):
                continue
            target = RefTarget(
                file=file,
                pointer=f"$.qds_replay_pins[{i}]",
                node=pin,
            )
            _add_target(indices["qds_replay_pin"], pin.get("id"), target)
            _add_target(indices["qds_replay_pin_target"], pin.get("qds_ref"), target)
        for i, qds in enumerate(doc.get("quality_data_sheets") or []):
            if not isinstance(qds, dict):
                continue
            _add_target(
                indices["quality_data_sheet"],
                qds.get("id"),
                RefTarget(
                    file=file,
                    pointer=f"$.quality_data_sheets[{i}]",
                    node=qds,
                ),
            )
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
                    node=run,
                    source_tool_families=source_tool_families,
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
                        node=measurement,
                        source_tool_families=source_tool_families,
                    ),
                )
            for collection in SOURCE_STRUCTURED_ROW_KEYS:
                for j, row in enumerate(run.get(collection) or []):
                    if not isinstance(row, dict):
                        continue
                    _add_target(
                        indices["structured_row"],
                        row.get("id"),
                        RefTarget(
                            file=file,
                            pointer=f"{run_path}.{collection}[{j}]",
                            owner_run_id=run.get("id"),
                            run_date=run.get("run_date"),
                            source_collection=collection,
                            node=row,
                        ),
                    )
            add_assumptions(run, run_path, run, file)
    return indices


def check_duplicate_ids(indices: CorpusIndices) -> list[str]:
    """Report ids whose references would have more than one possible target."""
    labels = {
        "evaluation_run": "EvaluationRun",
        "quality_data_sheet": "QualityDataSheet",
        "measurement": "MeasurementValue",
        "structured_row": "structured source row",
        "assumption": "Assumption",
        "qds_replay_pin": "QdsReplayPin",
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
    for qds_ref, targets in sorted(indices["qds_replay_pin_target"].items()):
        if len(targets) < 2:
            continue
        locations = ", ".join(
            f"{_shown(target.file)}:{target.pointer}" for target in targets
        )
        violations.append(
            f"multiple QdsReplayPins target qds_ref {qds_ref!r} at {locations}; "
            "the replay boundary is ambiguous"
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
        "quality_data_sheet": "QualityDataSheet",
        "measurement": "MeasurementValue",
        "structured_row": "structured source row",
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


WRAPPED_MEASUREMENT_FIELDS = {
    "source_measurement_ref": "id",
    "source_evaluation_run_ref": "_source_evaluation_run_ref",
    "metric_definition_ref": "metric_definition_ref",
    "oracle_tool_ref": "oracle_tool_ref",
    "oracle_family": "oracle_family",
    "pass_status": "pass_status",
    "pass_criterion": "pass_criterion",
    "subject_ref": "subject_ref",
    "reference_subject_ref": "reference_subject_ref",
    "evidence_refs": "evidence_refs",
    "bundle_ref": "bundle_ref",
    "stage": "stage",
    "scope": "scope",
    "scope_selector": "scope_selector",
    "notes": "notes",
}


def _canonical_tool_families() -> dict[str, str]:
    """Return the catalog-authoritative family for each named tool."""
    catalog = yaml.safe_load(CATALOG.read_text()) or {}
    return {
        str(tool["id"]): str(tool["family"])
        for tool in catalog.get("tools", []) or []
        if isinstance(tool, dict) and tool.get("id") and tool.get("family")
    }


def _expected_wrapped_measurement(
    measurement: dict[str, Any],
    owner_run_id: str,
    source_tool_families: tuple[tuple[str, str], ...] = (),
) -> dict[str, Any]:
    """Reconstruct the TypedMeasurementValue that qds_emit must have copied."""
    expected = dict(measurement.get("oracle_measure") or {})
    source = dict(measurement)
    authoritative_families = (
        dict(source_tool_families)
        if source_tool_families
        else _canonical_tool_families()
    )
    canonical_family = authoritative_families.get(
        str(source.get("oracle_tool_ref") or "")
    )
    if canonical_family:
        # qds_emit canonicalizes/fills this field before wrapping it. Compare
        # against the emitted form, not optional raw source metadata.
        source["oracle_family"] = canonical_family
    source["_source_evaluation_run_ref"] = owner_run_id
    for output_key, source_key in WRAPPED_MEASUREMENT_FIELDS.items():
        value = source.get(source_key)
        if value not in (None, ""):
            expected[output_key] = value
    return expected


def _expected_structured_row(row: dict[str, Any], owner_run_id: str) -> dict[str, Any]:
    expected = dict(row)
    expected["source_evaluation_run_ref"] = owner_run_id
    expected["source_row_ref"] = row.get("id")
    return expected


def _looks_like_routed_scalar(node: dict[str, Any]) -> bool:
    """Recognize wrapped measurements even outside a canonical summary slot."""
    return bool(node.get("metric_definition_ref")) and any(
        key in node for key in ("value_numeric", "value_text", "is_not_applicable")
    )


def _is_frozen_legacy_qds(rel: Path, qds: dict[str, Any]) -> bool:
    """Use the same content-pinned legacy decision as the trust guard."""
    try:
        import check_qds_trust_invariant as trust_guard

        path = rel if rel.is_absolute() else REPO / rel
        return trust_guard._is_frozen_legacy(path, REPO, qds)
    except (ImportError, OSError):
        return False


def _repository_relative(path: Path) -> Path | None:
    """Normalize an absolute or caller-relative path to a repository path."""
    if not path.is_absolute():
        return path
    try:
        return path.resolve().relative_to(REPO.resolve())
    except ValueError:
        return None


def _check_qds_filename(doc: dict[str, Any], rel: Path) -> list[str]:
    """Keep record-shaped data YAML discoverable by every QDS gate."""
    repo_rel = _repository_relative(rel)
    if repo_rel is None or not repo_rel.parts or repo_rel.parts[0] != "data":
        return []

    violations: list[str] = []
    if "evaluation_runs" in doc and repo_rel.suffix != ".yaml":
        violations.append(
            f"{rel}: a data YAML carrying evaluation_runs must use the .yaml suffix"
        )

    qds_rows = doc.get("quality_data_sheets") or []
    if "quality_data_sheets" in doc and repo_rel.suffix != ".yaml":
        violations.append(
            f"{rel}: a data YAML carrying quality_data_sheets must use the .yaml suffix"
        )
    if not qds_rows:
        return violations
    if not repo_rel.stem.startswith("QDS_"):
        violations.append(
            f"{rel}: a data YAML carrying quality_data_sheets must use a QDS_*.yaml filename"
        )
    for i, qds in enumerate(qds_rows):
        if not isinstance(qds, dict):
            continue
        qds_id = qds.get("id")
        if isinstance(qds_id, str) and repo_rel.stem != qds_id:
            violations.append(
                f"{rel}: $.quality_data_sheets[{i}].id = {qds_id!r} does not match "
                f"filename stem {repo_rel.stem!r}"
            )
    return violations


def _is_url_or_citation_with_slash(ref: str) -> bool:
    """Return true for URL/DOI syntax that must not be treated as a repo path."""
    parsed = urlsplit(ref)
    if parsed.scheme and parsed.scheme.lower() != "file":
        return True
    # Bare DOI syntax is common in citation fields and contains a slash.
    prefix, separator, _suffix = ref.partition("/")
    return bool(separator and prefix.startswith("10.") and prefix[3:].isdigit())


def _check_evidence_path(ref: str, rel: Path, path: str) -> list[str]:
    """Resolve path-like evidence refs without constraining citation keys or URLs."""
    repository_uri = ref.startswith("repo:")
    path_text = ref.removeprefix("repo:") if repository_uri else ref
    posix_path = Path(path_text)
    windows_path = PureWindowsPath(path_text)
    if posix_path.is_absolute() or windows_path.is_absolute() or ref.startswith("file:"):
        return [f"{rel}: {path} = {ref!r} is an absolute, non-portable evidence path"]
    if not repository_uri and _is_url_or_citation_with_slash(ref):
        return []
    raw_path = path_text.split("#", 1)[0]
    if (
        not repository_uri
        and "/" not in path_text
        and "\\" not in path_text
        and not path_text.startswith(".")
        and Path(raw_path).suffix.lower() not in EVIDENCE_FILE_SUFFIXES
    ):
        return []

    # Repository refs use POSIX separators in YAML. Treat a backslash as path syntax
    # (so it cannot masquerade as a citation) but reject it as non-portable.
    if "\\" in path_text:
        return [f"{rel}: {path} = {ref!r} is not a portable repository evidence path"]
    resolved = (REPO / raw_path).resolve()
    try:
        resolved.relative_to(REPO.resolve())
    except ValueError:
        return [f"{rel}: {path} = {ref!r} escapes the repository"]
    if not resolved.is_file():
        return [f"{rel}: {path} = {ref!r} does not resolve to a repository file"]
    return []


def check_corpus_refs(doc: Any, rel: Path, indices: CorpusIndices) -> list[str]:
    """Resolve references whose targets can live in another YAML document."""
    violations: list[str] = []
    if not isinstance(doc, dict):
        return violations
    violations += _check_qds_filename(doc, rel)

    local_run_ids = {
        str(run.get("id"))
        for run in doc.get("evaluation_runs", []) or []
        if isinstance(run, dict) and run.get("id")
    }
    for pin_i, pin in enumerate(doc.get("qds_replay_pins", []) or []):
        if not isinstance(pin, dict):
            continue
        pin_path = f"$.qds_replay_pins[{pin_i}]"
        qds_ref = pin.get("qds_ref")
        qds_target = None
        if isinstance(qds_ref, str):
            qds_target = _resolve(
                qds_ref,
                "quality_data_sheet",
                indices,
                rel,
                f"{pin_path}.qds_ref",
                violations,
            )
        else:
            violations.append(f"{rel}: {pin_path}.qds_ref must name a QualityDataSheet")
        source_refs = pin.get("source_evaluation_run_refs")
        if not isinstance(source_refs, list) or not all(
            isinstance(ref, str) for ref in source_refs
        ):
            violations.append(
                f"{rel}: {pin_path}.source_evaluation_run_refs must be a list of "
                "EvaluationRun ids"
            )
            source_refs = []
        for ref_i, run_ref in enumerate(source_refs):
            _resolve(
                run_ref,
                "evaluation_run",
                indices,
                rel,
                f"{pin_path}.source_evaluation_run_refs[{ref_i}]",
                violations,
            )
        if source_refs and local_run_ids.isdisjoint(source_refs):
            violations.append(
                f"{rel}: {pin_path} is not owned by any source EvaluationRun in "
                "the same document"
            )
        if qds_target is not None and isinstance(qds_target.node, dict):
            qds_refs = qds_target.node.get("derived_from_evaluation_run_refs") or []
            if source_refs != qds_refs:
                violations.append(
                    f"{rel}: {pin_path}.source_evaluation_run_refs differs from "
                    f"target QDS {qds_ref!r} derivation refs"
                )
            qds_contract = str(qds_target.node.get("emitter_contract_version") or "")
            pin_contract = str(pin.get("emitter_contract_version") or "")
            if pin_contract != qds_contract:
                violations.append(
                    f"{rel}: {pin_path}.emitter_contract_version {pin_contract!r} "
                    f"differs from target QDS {qds_ref!r} contract {qds_contract!r}"
                )

    def check(
        node: Any,
        path: str,
        current_run: dict[str, Any] | None = None,
        current_qds: dict[str, Any] | None = None,
        copied_source_key: str | None = None,
        qds_block: str | None = None,
        routed_scalar_slot: bool = False,
    ) -> None:
        if isinstance(node, dict):
            qds_routed_slots, qds_routed_blocks = _qds_contract_routing(current_qds)
            source_run_ref = node.get("source_evaluation_run_ref")
            source_measurement_ref = node.get("source_measurement_ref")
            source_row_ref = node.get("source_row_ref")
            source_run = None
            source_measurement = None
            source_row = None
            has_source_run = isinstance(source_run_ref, str)
            has_source_measurement = isinstance(source_measurement_ref, str)
            has_source_row = isinstance(source_row_ref, str)
            modern_qds = (
                current_qds is not None
                and not _is_frozen_legacy_qds(rel, current_qds)
            )
            if has_source_measurement and has_source_row:
                violations.append(
                    f"{rel}: {path} cannot carry both source_measurement_ref and "
                    "source_row_ref"
                )
            if has_source_measurement != has_source_run and not has_source_row:
                missing = (
                    "source_measurement_ref" if has_source_run else "source_evaluation_run_ref"
                )
                violations.append(
                    f"{rel}: {path} must pair source_evaluation_run_ref and "
                    f"source_measurement_ref; {missing} is missing"
                )
            if has_source_row != has_source_run and not has_source_measurement:
                missing = "source_row_ref" if has_source_run else "source_evaluation_run_ref"
                violations.append(
                    f"{rel}: {path} must pair source_evaluation_run_ref and "
                    f"source_row_ref; {missing} is missing"
                )
            if (
                modern_qds
                and (routed_scalar_slot or _looks_like_routed_scalar(node))
                and not has_source_measurement
            ):
                violations.append(
                    f"{rel}: {path} is a routed scalar in a nonlegacy QDS and must "
                    "carry source_evaluation_run_ref plus source_measurement_ref"
                )
            if modern_qds and copied_source_key is not None and not has_source_row:
                violations.append(
                    f"{rel}: {path} is a copied {copied_source_key} row in a "
                    "nonlegacy QDS and must carry source_evaluation_run_ref plus "
                    "source_row_ref"
                )
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
            if isinstance(source_row_ref, str):
                source_row = _resolve(
                    source_row_ref,
                    "structured_row",
                    indices,
                    rel,
                    f"{path}.source_row_ref",
                    violations,
                )
            if source_run is not None and source_measurement is not None:
                if source_measurement.owner_run_id != source_run_ref:
                    violations.append(
                        f"{rel}: {path}.source_measurement_ref = {source_measurement_ref!r} "
                        f"belongs to {source_measurement.owner_run_id!r}, not paired "
                        f"source_evaluation_run_ref {source_run_ref!r}"
                    )
                if current_qds is None:
                    violations.append(
                        f"{rel}: {path} carries source refs outside a QualityDataSheet"
                    )
                else:
                    derived_refs = current_qds.get("derived_from_evaluation_run_refs") or []
                    if source_run_ref not in derived_refs:
                        violations.append(
                            f"{rel}: {path}.source_evaluation_run_ref = {source_run_ref!r} "
                            "is not an input in the enclosing QDS "
                            "derived_from_evaluation_run_refs"
                        )
                source_node = source_measurement.node
                if (
                    source_measurement.owner_run_id == source_run_ref
                    and isinstance(source_node, dict)
                ):
                    expected = _expected_wrapped_measurement(
                        source_node,
                        source_run_ref,
                        source_measurement.source_tool_families,
                    )
                    if node != expected:
                        differing = sorted(
                            key
                            for key in set(node) | set(expected)
                            if node.get(key) != expected.get(key)
                            or (key in node) != (key in expected)
                        )
                        violations.append(
                            f"{rel}: {path} does not exactly match source measurement "
                            f"{source_measurement_ref!r}; differing fields: "
                            f"{', '.join(differing)}"
                        )
            if source_run is not None and source_row is not None:
                if source_row.owner_run_id != source_run_ref:
                    violations.append(
                        f"{rel}: {path}.source_row_ref = {source_row_ref!r} belongs to "
                        f"{source_row.owner_run_id!r}, not paired "
                        f"source_evaluation_run_ref {source_run_ref!r}"
                    )
                if copied_source_key and source_row.source_collection != copied_source_key:
                    violations.append(
                        f"{rel}: {path}.source_row_ref = {source_row_ref!r} resolves "
                        f"to {source_row.source_collection!r}, expected "
                        f"{copied_source_key!r}"
                    )
                if current_qds is None:
                    violations.append(
                        f"{rel}: {path} carries source refs outside a QualityDataSheet"
                    )
                else:
                    derived_refs = current_qds.get("derived_from_evaluation_run_refs") or []
                    if source_run_ref not in derived_refs:
                        violations.append(
                            f"{rel}: {path}.source_evaluation_run_ref = "
                            f"{source_run_ref!r} is not an input in the enclosing QDS "
                            "derived_from_evaluation_run_refs"
                        )
                if isinstance(source_row.node, dict):
                    expected = _expected_structured_row(
                        source_row.node, str(source_run_ref)
                    )
                    if node != expected:
                        differing = sorted(
                            key
                            for key in set(node) | set(expected)
                            if node.get(key) != expected.get(key)
                            or (key in node) != (key in expected)
                        )
                        violations.append(
                            f"{rel}: {path} does not exactly match source structured "
                            f"row {source_row_ref!r}; differing fields: "
                            f"{', '.join(differing)}"
                        )

            for key, value in node.items():
                child = f"{path}.{key}"
                if key == "evaluation_runs" and isinstance(value, list):
                    for i, run in enumerate(value):
                        check(
                            run,
                            f"{child}[{i}]",
                            run if isinstance(run, dict) else None,
                            current_qds,
                        )
                    continue
                if key == "quality_data_sheets" and isinstance(value, list):
                    for i, qds in enumerate(value):
                        check(
                            qds,
                            f"{child}[{i}]",
                            current_run,
                            qds if isinstance(qds, dict) else None,
                        )
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
                        if not isinstance(ref, str):
                            continue
                        evidence_path = f"{child}[{i}]"
                        # EVAL_* is the reserved namespace for EvaluationRun ids.
                        if ref.startswith("EVAL_"):
                            _resolve(
                                ref,
                                "evaluation_run",
                                indices,
                                rel,
                                evidence_path,
                                violations,
                            )
                        else:
                            violations.extend(_check_evidence_path(ref, rel, evidence_path))

                # Source refs were resolved together above so ownership can be checked.
                if key not in {
                    "source_evaluation_run_ref",
                    "source_measurement_ref",
                    "source_row_ref",
                }:
                    child_qds_block = qds_block
                    if node is current_qds and key in qds_routed_blocks:
                        child_qds_block = key
                    child_is_routed_scalar = (
                        child_qds_block is not None
                        and (child_qds_block, key) in qds_routed_slots
                    )
                    child_source_key = (
                        QDS_COPIED_ROW_SOURCE_KEYS.get(key)
                        if current_qds is not None and isinstance(value, list)
                        else None
                    )
                    check(
                        value,
                        child,
                        current_run,
                        current_qds,
                        child_source_key,
                        child_qds_block,
                        child_is_routed_scalar,
                    )
        elif isinstance(node, list):
            for i, value in enumerate(node):
                check(
                    value,
                    f"{path}[{i}]",
                    current_run,
                    current_qds,
                    copied_source_key,
                    qds_block,
                    routed_scalar_slot,
                )

    check(doc, "$")

    # Supersession is an operation on an ordered emitter input, not just a date claim.
    # Whenever a QDS includes a superseding run, the run owning the withdrawn
    # assumption must also be present earlier in that same input list.
    for qds_i, qds in enumerate(doc.get("quality_data_sheets") or []):
        if not isinstance(qds, dict):
            continue
        refs = qds.get("derived_from_evaluation_run_refs") or []
        seen_refs: set[str] = set()
        qds_structure = qds.get("structure_ref")
        for run_i, run_ref in enumerate(refs):
            if not isinstance(run_ref, str):
                continue
            if run_ref in seen_refs:
                violations.append(
                    f"{rel}: $.quality_data_sheets[{qds_i}]."
                    f"derived_from_evaluation_run_refs[{run_i}] duplicates {run_ref!r}"
                )
            seen_refs.add(run_ref)
            run_targets = indices["evaluation_run"].get(run_ref, [])
            if len(run_targets) != 1 or not isinstance(run_targets[0].node, dict):
                continue
            run_structure = run_targets[0].node.get("structure_ref")
            if (
                isinstance(qds_structure, str)
                and isinstance(run_structure, str)
                and qds_structure != run_structure
            ):
                violations.append(
                    f"{rel}: $.quality_data_sheets[{qds_i}].structure_ref = "
                    f"{qds_structure!r} does not match input EvaluationRun {run_ref!r} "
                    f"structure_ref {run_structure!r}"
                )
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
