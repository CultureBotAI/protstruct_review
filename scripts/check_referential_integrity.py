#!/usr/bin/env python3
"""Check that every reference in committed YAML records resolves.

`linkml-validate` enforces type and enum constraints but does not enforce
that string-typed references point at declared instances. This script
walks every YAML record under `ref/` and `data/examples/` and verifies:

  - every `metric_definition_ref` resolves in `ref/catalog.yaml::metric_definitions`
  - every MeasurementValue uses its metric only with a task declared by that
    MetricDefinition's `applicable_task_refs`
  - every `pass_criterion_ref` resolves in
    `ref/structural_criteria.yaml::pass_criterion_bindings`
  - every `oracle_tool_ref` / `tool_ref` resolves in `ref/catalog.yaml::tools`
  - every MeasurementValue's `oracle_family` matches its source-pinned Tool
    declaration when present, otherwise the canonical catalog declaration
  - every MeasurementValue uses its oracle tool only with a task declared by
    that source-pinned Tool, falling back to the canonical catalog declaration
  - every `catalog_task_ref` / `catalog_tasks_applied[]` is a known T0NN id
  - every `structure_ref` resolves in `ref/catalog.yaml::structures` or the same
    record's structures[] WHEN either exists; neither does today, so it falls back
    to requiring every nested `structure_ref` to match its own record's. See
    `check_structure_refs` — this bullet described a check that was never
    implemented until #118.
  - EvaluationRun, QualityDataSheet, MeasurementValue, and run-owned Assumption ids
    are unique across the corpus, so a string reference never resolves by file ordering
  - measurement-to-measurement delta/derivation refs resolve within their owning run;
    pair deltas also preserve context, numeric units, and exact nominal arithmetic
  - QDS input/source refs, superseded assumptions, and `EVAL_*` evidence refs resolve;
    an EvaluationRun cannot cite itself as its own evidence;
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

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import subprocess
import sys
from typing import Any, Iterable, Sequence
from urllib.parse import urlsplit

import yaml

import qds_emit_contract_v1
import qds_emit_contract_v2
import qds_emit_contract_v3

try:
    from strict_yaml import strict_yaml_load
except ModuleNotFoundError:  # imported as scripts.check_referential_integrity
    from scripts.strict_yaml import strict_yaml_load


REPO = Path(__file__).resolve().parent.parent
CATALOG = REPO / "ref" / "catalog.yaml"
STRUCTURAL_CRITERIA = REPO / "ref" / "structural_criteria.yaml"

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
    source_tool_tasks: tuple[tuple[str, tuple[str, ...]], ...] = ()
    source_metric_tasks: tuple[tuple[str, tuple[str, ...]], ...] = ()
    source_document: dict[str, Any] | None = None


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


# Immutable records that predate these relationship guards are preserved without
# widening today's catalog to fit their stale metric/tool assignments. Each
# exception binds the rule, repository path, owning run, row id, and complete
# parsed row. Grouping row digests below only removes repeated path/run literals;
# the materialized keys retain all four coordinates. Any content change must be
# published as a new dated record rather than silently inheriting an exemption.
# #753: 24 tool_task exemptions for phenix.model_vs_data T03/T13 and standalone
# reduce T05 were retired after registering their actual producer/task links.
# This does not validate those frozen rows' metrics, grades or interpretations;
# unrelated semantic exceptions and stale-exception enforcement remain intact.
_LEGACY_TOOL_TASK_ROW_DIGESTS = (
    (
        "data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-04-24.yaml",
        "EVAL_1sar_cdba2c07_2026-04-24",
        {
            "EVAL_1sar_cdba2c07_2026-04-24_M_007": "5722a0f869d8be38546244f8526115e46798e00155cbd91d35f7079833431584",
            "EVAL_1sar_cdba2c07_2026-04-24_M_009": "93ae20f14dd833363435adab1cc7b62d4e379f38ce77e49627eafc4c7b6f88fc",
            "EVAL_1sar_cdba2c07_2026-04-24_M_011": "af89f85407d946ada7bebb29b3159a275fccbd532ce0ff579d8a9f151ccffbfd",
            "EVAL_1sar_cdba2c07_2026-04-24_M_ca_b_vs_mean_ratio": "f21f4c015e1c446f028811d4c5234827e9a1238705095b655cf2bca7c7b02359",
            "EVAL_1sar_cdba2c07_2026-04-24_M_mean_b": "01e53f6517114a024431bfc3ec3a7ae05aae3f6c66fb115e03f2551a36707816",
            "EVAL_1sar_cdba2c07_2026-04-24_M_per_residue_displacement_summary": "1a20b0d87b7cfb505af8d226486abf3e69e9699f64097ee4effbd7ebf3f6a3bb",
            "EVAL_1sar_cdba2c07_2026-04-24_M_prosmart_global_rmsd": "7dc9b9c3f742b8d3c271dfeba66d18a6a626af85ddc5aec4135e66f2717c657d",
            "EVAL_1sar_cdba2c07_2026-04-24_M_total_atoms": "bda6294c0cf6bafd95560e2669259d9a6d917438c1108540ac7a9e78f5142e42",
            "EVAL_1sar_cdba2c07_2026-04-24_M_water_count": "c40200650b7c82d2e7bf6c827d23894e9875f23035c14a79be39f653f8032860",
        },
    ),
    (
        "data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-09-07.yaml",
        "EVAL_1sar_cdba2c07_2026-09-07",
        {
            "EVAL_1sar_cdba2c07_2026-09-07_M_005": "56e23ae684fa604796cae91985bad5d95c4834db5d1b3b4441fb743cde05c0aa",
            "EVAL_1sar_cdba2c07_2026-09-07_M_006": "da6fd9d72d05a6452631e2510d225e241cb505c7c9cec9bf2f4d9eb28749a7d0",
            "EVAL_1sar_cdba2c07_2026-09-07_M_007": "58deeb81400fc40da513e30696834c121392a81b7a873dcb2a0a579e63647747",
        },
    ),
    (
        "data/examples/eval/EVAL_synth_active_site_2026-04-26.yaml",
        "EVAL_synth_active_site_2026-04-26",
        {
            # MolProbity now legitimately serves T10 H-bond counting (#691),
            # so this task-only exception for old M_004 is obsolete. That does
            # not validate its false MolProbity/RSCC attribution; the frozen
            # source remains historical and the new dated fixture uses edstats.
            "EVAL_synth_active_site_2026-04-26_M_005": "b97f1bf63f0d492eca72b463b115a562abf36fd006ada98b3c51377cd92191e2",
        },
    ),
)

LEGACY_MEASUREMENT_SEMANTIC_EXCEPTIONS = {
    (
        "metric_task",
        "data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-04-24.yaml",
        "EVAL_1sar_cdba2c07_2026-04-24",
        "EVAL_1sar_cdba2c07_2026-04-24_M_water_rscc_distribution",
    ): "1e6d72b5901dff6f28b699b258df0c2a36859cfa8ca2386e3945a181a3cddbfa",
    **{
        ("tool_task", path, run_id, row_id): digest
        for path, run_id, row_digests in _LEGACY_TOOL_TASK_ROW_DIGESTS
        for row_id, digest in row_digests.items()
    },
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
    "2": _routed_scalar_slots(qds_emit_contract_v2.METRIC_TO_QDS_SLOT),
    "3": _routed_scalar_slots(qds_emit_contract_v3.METRIC_TO_QDS_SLOT),
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
    if version == "4":
        # Import lazily: retained contracts never depend on the new projection
        # implementation, and there is still only one emitter-owned route table.
        import qds_emit_contract_v4

        slots = _routed_scalar_slots(qds_emit_contract_v4.METRIC_TO_QDS_SLOT)
        return slots, frozenset(block for block, _slot in slots)
    slots = QDS_ROUTED_SCALAR_SLOTS_BY_CONTRACT.get(version, frozenset())
    return slots, frozenset(block for block, _slot in slots)


def load_catalog_indices() -> dict[str, set[str]]:
    """Return ids from the catalog and the non-threshold verdict bindings."""
    doc = strict_yaml_load(CATALOG.read_text())
    criterion_doc = strict_yaml_load(STRUCTURAL_CRITERIA.read_text())
    return {
        "metric": {m["id"] for m in doc.get("metric_definitions", [])},
        "criterion": {
            c["id"]
            for c in criterion_doc.get("pass_criterion_bindings", []) or []
        },
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
        STRUCTURAL_CRITERIA,
        REPO / "ref" / "tool_recommendations.yaml",
        REPO / "ref" / "tool_assumptions.yaml",
    ]
    # Every provider, not just `coscientists`. Path.rglob intentionally includes
    # ignored files too; a dangling ref must not become invisible due to gitignore.
    targets += sorted((REPO / "data").rglob("*.yaml"))
    targets += sorted((REPO / "data").rglob("*.yml"))
    return sorted({path for path in targets if path.exists()})


def repository_yaml_paths(root: Path = REPO) -> list[Path]:
    """Find tracked and local YAML so a record cannot hide off the normal routes."""
    root = root.absolute()
    tracked: set[Path] = set()
    try:
        proc = subprocess.run(
            [
                "git",
                "-C",
                str(root),
                "ls-files",
                "--cached",
                "-z",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        tracked = {
            path.absolute()
            for item in proc.stdout.split("\0")
            if item
            for path in (root / item,)
            if (path.is_file() or path.is_symlink())
            and path.suffix.lower() in {".yaml", ".yml"}
        }
    except (OSError, subprocess.CalledProcessError):
        # A source archive without .git still gets a filesystem-complete scan.
        tracked = set()

    ignored_dependency_roots = {
        ".git",
        ".venv",
        ".mypy_cache",
        ".ruff_cache",
        "__pycache__",
        "node_modules",
    }
    local: set[Path] = set()
    for directory, child_dirs, filenames in os.walk(root):
        child_dirs[:] = [
            name for name in child_dirs if name not in ignored_dependency_roots
        ]
        for filename in filenames:
            path = Path(directory) / filename
            if path.suffix.lower() in {".yaml", ".yml"}:
                local.add(path.absolute())
    return sorted(tracked | local)


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
        "qds_emission_context": {},
        "qds_emission_context_target": {},
        "correction": {},
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
        source_tool_tasks = tuple(
            sorted(
                (
                    str(tool["id"]),
                    tuple(
                        str(task)
                        for task in tool.get("catalog_tasks_served", []) or []
                    ),
                )
                for tool in doc.get("tools", []) or []
                if isinstance(tool, dict) and tool.get("id")
            )
        )
        source_metric_tasks = tuple(
            sorted(
                (
                    str(metric["id"]),
                    tuple(
                        str(task)
                        for task in metric.get("applicable_task_refs", []) or []
                    ),
                )
                for metric in doc.get("metric_definitions", []) or []
                if isinstance(metric, dict) and metric.get("id")
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
        for i, context in enumerate(doc.get("qds_emission_contexts") or []):
            if not isinstance(context, dict):
                continue
            target = RefTarget(
                file=file,
                pointer=f"$.qds_emission_contexts[{i}]",
                node=context,
                source_document=doc,
            )
            _add_target(
                indices["qds_emission_context"], context.get("id"), target
            )
            _add_target(
                indices["qds_emission_context_target"],
                context.get("qds_ref"),
                target,
            )
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
                    source_tool_tasks=source_tool_tasks,
                    source_metric_tasks=source_metric_tasks,
                    source_document=doc,
                ),
            )
            for j, correction in enumerate(run.get("corrections") or []):
                if isinstance(correction, dict):
                    _add_target(
                        indices["correction"],
                        correction.get("id"),
                        RefTarget(
                            file=file,
                            pointer=f"{run_path}.corrections[{j}]",
                            owner_run_id=run.get("id"),
                            run_date=run.get("run_date"),
                            node=correction,
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
                        source_tool_tasks=source_tool_tasks,
                        source_metric_tasks=source_metric_tasks,
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
        "qds_emission_context": "QdsEmissionContext",
        "correction": "EvidenceCorrection",
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
    for qds_ref, targets in sorted(
        indices["qds_emission_context_target"].items()
    ):
        if len(targets) < 2:
            continue
        locations = ", ".join(
            f"{_shown(target.file)}:{target.pointer}" for target in targets
        )
        violations.append(
            f"multiple QdsEmissionContexts target qds_ref {qds_ref!r} at "
            f"{locations}; the source-owned sheet recipe is ambiguous"
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
        "qds_emission_context": "QdsEmissionContext",
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


DELTA_CONTEXT_FIELDS = (
    "catalog_task_ref",
    "metric_definition_ref",
    "stage",
    "subject_ref",
    "reference_subject_ref",
    "scope",
    "scope_selector",
)
DERIVED_CONTEXT_FIELDS = (
    "catalog_task_ref",
    "subject_ref",
    "reference_subject_ref",
    "stage",
    "scope",
    "scope_selector",
)
T14_FLIP_CONFLICT_METRIC = "T14_asn_gln_his_flip_set_conflicts"
T14_FLIP_SOURCE_METRIC = "T14_asn_gln_his_flip_candidates_scored"
T14_COHORT_SCOPE = "cohort"
T14_FLIP_SOURCE_TOOLS = {
    "reduce (standalone, Richardson)",
    "mmtbx.reduce2",
}
NON_CRITERION_TEXT = {
    "n/a",
    "na",
    "-",
    "--",
    "tbd",
    "todo",
    "none",
    "see notes",
    "informational",
}


def _measurement_location(target: RefTarget) -> str:
    return f"{_shown(target.file)}:{target.pointer}"


def _normalized_measurement_unit(payload: dict[str, Any]) -> str:
    """Normalize only spelling aliases; never silently convert numeric values."""
    unit = str(payload.get("unit") or "").strip().casefold()
    aliases = {
        "": "dimensionless",
        "1": "dimensionless",
        "fraction": "dimensionless",
        "unitless": "dimensionless",
        "dimensionless": "dimensionless",
        "%": "percent",
        "percent": "percent",
        "percentage": "percent",
    }
    return aliases.get(unit, unit)


def _finite_integral_number(value: Any, *, minimum: int) -> int | None:
    """Return a finite mathematical integer without requiring a YAML int token."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not decimal.is_finite() or decimal != decimal.to_integral_value():
        return None
    integer = int(decimal)
    return integer if integer >= minimum else None


def _meaningful_pass_criterion(row: dict[str, Any]) -> str:
    """Return a real threshold expression, excluding absence placeholders."""
    criterion = str(row.get("pass_criterion") or "").strip()
    return "" if criterion.casefold() in NON_CRITERION_TEXT else criterion


def _is_t14_conflict_rate_criterion(value: Any) -> bool:
    """Recognize only the canonical registered inclusive 10% criterion."""
    text = str(value or "").strip().casefold().replace("≤", "<=")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s*<=\s*", " <= ", text)
    text = re.sub(r"\s*%\s*", "%", text).strip()
    return text == "conflict rate <= 10%"


def _check_t14_cohort_verdict(
    row: dict[str, Any],
    *,
    numerator: int,
    denominator: int,
    location: str,
    violations: list[str],
) -> None:
    """Bind cohort grades to the preregistered inclusive 10% boundary."""
    status = row.get("pass_status")
    if status == "informational":
        _check_t14_informational_only(
            row,
            location=location,
            label="cohort conflict result declared informational",
            violations=violations,
        )
        return

    passes = numerator * 10 <= denominator
    expected_statuses = {"pass", "pass_with_caveat"} if passes else {
        "fail_criterion"
    }
    if status not in expected_statuses:
        relation = "at or below" if passes else "above"
        violations.append(
            f"{location}: cohort conflict rate {numerator}/{denominator} is "
            f"{relation} the inclusive 10% boundary and requires pass_status in "
            f"{sorted(expected_statuses)!r}, not {status!r}"
        )
    if not _is_t14_conflict_rate_criterion(row.get("pass_criterion")):
        violations.append(
            f"{location}: gradeable cohort conflict result requires an unambiguous "
            "pass_criterion naming conflict rate <= 10%"
        )

    nested = row.get("oracle_measure")
    if not isinstance(nested, dict):
        return
    nested_status = nested.get("pass_status")
    nested_criterion = _meaningful_pass_criterion(nested)
    if nested_status in (None, "") and not nested_criterion:
        return
    if nested_status not in expected_statuses:
        violations.append(
            f"{location}.oracle_measure: cohort conflict verdict must match "
            f"{numerator}/{denominator} at the inclusive 10% boundary; expected "
            f"{sorted(expected_statuses)!r}, not {nested_status!r}"
        )
    if not _is_t14_conflict_rate_criterion(nested.get("pass_criterion")):
        violations.append(
            f"{location}.oracle_measure: gradeable cohort conflict result requires "
            "an unambiguous pass_criterion naming conflict rate <= 10%"
        )


def _check_t14_informational_only(
    row: dict[str, Any],
    *,
    location: str,
    label: str,
    violations: list[str],
) -> None:
    """Reject a grade on both a measurement row and its typed value carrier."""
    if row.get("pass_status") != "informational":
        violations.append(
            f"{location}: {label} requires pass_status 'informational'"
        )
    pass_criterion = _meaningful_pass_criterion(row)
    if pass_criterion:
        violations.append(
            f"{location}: {label} must not carry pass_criterion "
            f"{pass_criterion!r}"
        )

    oracle_measure = row.get("oracle_measure")
    if not isinstance(oracle_measure, dict):
        return
    nested_status = oracle_measure.get("pass_status")
    if nested_status not in (None, "", "informational"):
        violations.append(
            f"{location}.oracle_measure.pass_status = {nested_status!r}; "
            f"{label} must remain informational when nested status is present"
        )
    nested_criterion = _meaningful_pass_criterion(oracle_measure)
    if nested_criterion:
        violations.append(
            f"{location}.oracle_measure: {label} must not carry pass_criterion "
            f"{nested_criterion!r}"
        )


def _check_t14_flip_candidate_interpretation(
    source: RefTarget,
    violations: list[str],
) -> None:
    """Candidate counts are opportunities, never thresholded outcomes."""
    row = source.node or {}
    if row.get("metric_definition_ref") != T14_FLIP_SOURCE_METRIC:
        return
    _check_t14_informational_only(
        row,
        location=_measurement_location(source),
        label=f"{T14_FLIP_SOURCE_METRIC} candidate-count measurement",
        violations=violations,
    )


def _finite_decimal_carrier(
    row: dict[str, Any],
    field: str,
    *,
    location: str,
    violations: list[str],
) -> tuple[Decimal, Any, dict[str, Any]] | None:
    """Return one unambiguous finite numeric carrier, reporting why it is unusable."""
    payload = row.get(field)
    if not isinstance(payload, dict):
        violations.append(
            f"{location}.{field} must be a typed numeric value for a pair delta"
        )
        return None
    value = payload.get("value_numeric")
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or payload.get("value_text") not in (None, "")
        or payload.get("is_not_applicable") is True
    ):
        violations.append(
            f"{location}.{field} must carry one finite value_numeric for a pair delta"
        )
        return None
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError):
        violations.append(
            f"{location}.{field}.value_numeric = {value!r} is not a finite decimal"
        )
        return None
    if not decimal.is_finite():
        violations.append(
            f"{location}.{field}.value_numeric = {value!r} is not a finite decimal"
        )
        return None
    return decimal, value, payload


def _validate_relation_context(
    source: RefTarget,
    target: RefTarget,
    fields: Sequence[str],
    *,
    relation: str,
    violations: list[str],
) -> None:
    source_node = source.node or {}
    target_node = target.node or {}
    source_location = _measurement_location(source)
    target_id = target_node.get("id")
    if "subject_ref" in fields:
        if not str(source_node.get("subject_ref") or "").strip():
            violations.append(
                f"{source_location}.{relation} requires a non-empty subject_ref on "
                "the derived measurement"
            )
        if not str(target_node.get("subject_ref") or "").strip():
            violations.append(
                f"{source_location}.{relation} target {target_id!r} requires a "
                "non-empty subject_ref"
            )
    for field in fields:
        if source_node.get(field) != target_node.get(field):
            violations.append(
                f"{source_location}.{relation} target {target_id!r} has mismatched "
                f"{field} (derived={source_node.get(field)!r}, "
                f"source={target_node.get(field)!r})"
            )


def _resolve_owned_measurement_ref(
    source: RefTarget,
    ref: Any,
    *,
    relation_path: str,
    indices: CorpusIndices,
    violations: list[str],
) -> RefTarget | None:
    source_node = source.node or {}
    source_location = _measurement_location(source)
    if not isinstance(ref, str) or not ref.strip():
        violations.append(f"{source_location}.{relation_path} must name a MeasurementValue")
        return None
    if ref == source_node.get("id"):
        violations.append(
            f"{source_location}.{relation_path} cannot reference its own measurement {ref!r}"
        )
        return None
    target = _resolve(
        ref,
        "measurement",
        indices,
        _shown(source.file),
        f"{source.pointer}.{relation_path}",
        violations,
    )
    if target is None:
        return None
    if target.owner_run_id != source.owner_run_id:
        violations.append(
            f"{source_location}.{relation_path} = {ref!r} belongs to EvaluationRun "
            f"{target.owner_run_id!r}, not owning EvaluationRun {source.owner_run_id!r}"
        )
        return None
    return target


def _check_pair_delta(
    source: RefTarget,
    indices: CorpusIndices,
    violations: list[str],
) -> None:
    row = source.node or {}
    if "delta_from_measurement_ref" not in row:
        return
    target = _resolve_owned_measurement_ref(
        source,
        row.get("delta_from_measurement_ref"),
        relation_path="delta_from_measurement_ref",
        indices=indices,
        violations=violations,
    )
    if target is None or not isinstance(target.node, dict):
        return
    _validate_relation_context(
        source,
        target,
        DELTA_CONTEXT_FIELDS,
        relation="delta_from_measurement_ref",
        violations=violations,
    )

    source_location = _measurement_location(source)
    current = _finite_decimal_carrier(
        row, "oracle_measure", location=source_location, violations=violations
    )
    referenced = _finite_decimal_carrier(
        target.node,
        "oracle_measure",
        location=_measurement_location(target),
        violations=violations,
    )
    delta = _finite_decimal_carrier(
        row, "delta", location=source_location, violations=violations
    )
    if current is None or referenced is None or delta is None:
        return

    units = {
        "oracle_measure": _normalized_measurement_unit(current[2]),
        "referenced oracle_measure": _normalized_measurement_unit(referenced[2]),
        "delta": _normalized_measurement_unit(delta[2]),
    }
    if len(set(units.values())) != 1:
        violations.append(
            f"{source_location}.delta_from_measurement_ref has incompatible numeric "
            f"units {units}"
        )
        return

    expected = current[0] - referenced[0]
    observed = delta[0]
    # Validate the nominal committed values exactly. An ordinary YAML loader erases
    # trailing zeroes (0.0020 becomes float 0.002), so inferring a tolerance from the
    # parsed delta would silently widen its written precision (#667).
    if observed != expected:
        violations.append(
            f"{source_location}.delta.value_numeric = {observed} does not equal this "
            f"row's oracle_measure {current[0]} minus referenced oracle_measure "
            f"{referenced[0]} ({expected})"
        )


def _check_derived_measurement_refs(
    source: RefTarget,
    indices: CorpusIndices,
    violations: list[str],
) -> list[RefTarget]:
    row = source.node or {}
    if "derived_from_measurement_refs" not in row:
        return []
    refs = row.get("derived_from_measurement_refs")
    source_location = _measurement_location(source)
    if not isinstance(refs, list) or not refs:
        violations.append(
            f"{source_location}.derived_from_measurement_refs must be a non-empty list"
        )
        return []

    string_refs = [ref for ref in refs if isinstance(ref, str)]
    if len(string_refs) != len(set(string_refs)):
        violations.append(
            f"{source_location}.derived_from_measurement_refs contains duplicate refs"
        )

    resolved: list[RefTarget] = []
    for index, ref in enumerate(refs):
        target = _resolve_owned_measurement_ref(
            source,
            ref,
            relation_path=f"derived_from_measurement_refs[{index}]",
            indices=indices,
            violations=violations,
        )
        if target is None or not isinstance(target.node, dict):
            continue
        resolved.append(target)
        _validate_relation_context(
            source,
            target,
            DERIVED_CONTEXT_FIELDS,
            relation=f"derived_from_measurement_refs[{index}]",
            violations=violations,
        )
    return resolved


def _check_t14_flip_conflict_derivation(
    source: RefTarget,
    derived_targets: list[RefTarget],
    violations: list[str],
) -> None:
    row = source.node or {}
    if row.get("metric_definition_ref") != T14_FLIP_CONFLICT_METRIC:
        return
    source_location = _measurement_location(source)
    if row.get("catalog_task_ref") != "T14":
        violations.append(
            f"{source_location}: {T14_FLIP_CONFLICT_METRIC} must have "
            "catalog_task_ref 'T14'"
        )
    if row.get("scope") == T14_COHORT_SCOPE:
        if not str(row.get("scope_selector") or "").strip():
            violations.append(
                f"{source_location}: cohort-scoped {T14_FLIP_CONFLICT_METRIC} "
                "requires scope_selector naming the preregistered cohort"
            )
    else:
        _check_t14_informational_only(
            row,
            location=source_location,
            label=(
                f"structure-level {T14_FLIP_CONFLICT_METRIC}; the <= 10% "
                "criterion applies only to scope 'cohort'"
            ),
            violations=violations,
        )
    oracle_measure = row.get("oracle_measure") or {}
    denominator = oracle_measure.get("count") if isinstance(oracle_measure, dict) else None
    numerator = (
        oracle_measure.get("value_numeric")
        if isinstance(oracle_measure, dict)
        else None
    )
    denominator_count = _finite_integral_number(denominator, minimum=1)
    numerator_count = _finite_integral_number(numerator, minimum=0)
    if denominator_count is None:
        violations.append(
            f"{source_location}: {T14_FLIP_CONFLICT_METRIC} requires a positive "
            "integer oracle_measure.count denominator"
        )
    if (
        numerator_count is None
        or not isinstance(oracle_measure, dict)
        or oracle_measure.get("value_text") not in (None, "")
        or oracle_measure.get("is_not_applicable") is True
    ):
        violations.append(
            f"{source_location}: {T14_FLIP_CONFLICT_METRIC} requires a "
            "single non-negative integer oracle_measure.value_numeric conflict count"
        )
    if not isinstance(oracle_measure, dict) or _normalized_measurement_unit(
        oracle_measure
    ) != "count":
        violations.append(
            f"{source_location}: {T14_FLIP_CONFLICT_METRIC} requires "
            "oracle_measure.unit 'count'"
        )
    if (
        numerator_count is not None
        and denominator_count is not None
        and numerator_count > denominator_count
    ):
        violations.append(
            f"{source_location}: conflict count {numerator_count} exceeds eligible "
            f"denominator {denominator_count}"
        )
    if (
        row.get("scope") == T14_COHORT_SCOPE
        and numerator_count is not None
        and denominator_count is not None
    ):
        _check_t14_cohort_verdict(
            row,
            numerator=numerator_count,
            denominator=denominator_count,
            location=source_location,
            violations=violations,
        )

    refs = row.get("derived_from_measurement_refs")
    distinct_refs = set(refs) if isinstance(refs, list) and all(
        isinstance(ref, str) for ref in refs
    ) else set()
    if len(distinct_refs) != 2:
        violations.append(
            f"{source_location}: {T14_FLIP_CONFLICT_METRIC} requires exactly two "
            "distinct derived_from_measurement_refs"
        )

    tool_families = _canonical_tool_families()
    source_tools = {
        str((target.node or {}).get("oracle_tool_ref") or "")
        for target in derived_targets
    }
    if source_tools != T14_FLIP_SOURCE_TOOLS:
        violations.append(
            f"{source_location}: {T14_FLIP_CONFLICT_METRIC} source tools are "
            f"{sorted(source_tools)!r}; expected {sorted(T14_FLIP_SOURCE_TOOLS)!r}"
        )
    source_counts: list[int] = []
    for target in derived_targets:
        target_node = target.node or {}
        target_id = target_node.get("id")
        if target_node.get("catalog_task_ref") != "T14":
            violations.append(
                f"{source_location}: source {target_id!r} must have catalog_task_ref 'T14'"
            )
        if target_node.get("metric_definition_ref") != T14_FLIP_SOURCE_METRIC:
            violations.append(
                f"{source_location}: source {target_id!r} must measure "
                f"{T14_FLIP_SOURCE_METRIC!r}"
            )
        target_tool = str(target_node.get("oracle_tool_ref") or "")
        canonical_family = tool_families.get(target_tool)
        claimed_family = target_node.get("oracle_family")
        if canonical_family is not None and claimed_family != canonical_family:
            violations.append(
                f"{source_location}: source {target_id!r} asserts oracle_family "
                f"{claimed_family!r}, but catalog tool {target_tool!r} has canonical "
                f"family {canonical_family!r}"
            )
        target_measure = target_node.get("oracle_measure") or {}
        target_count = (
            target_measure.get("value_numeric")
            if isinstance(target_measure, dict)
            else None
        )
        normalized_target_count = _finite_integral_number(target_count, minimum=1)
        if (
            normalized_target_count is None
            or not isinstance(target_measure, dict)
            or target_measure.get("value_text") not in (None, "")
            or target_measure.get("is_not_applicable") is True
        ):
            violations.append(
                f"{source_location}: source {target_id!r} must carry a positive "
                "integral oracle_measure.value_numeric candidate count"
            )
        else:
            source_counts.append(normalized_target_count)
        if not isinstance(target_measure, dict) or _normalized_measurement_unit(
            target_measure
        ) != "count":
            violations.append(
                f"{source_location}: source {target_id!r} must use "
                "oracle_measure.unit 'count'"
            )
    if (
        denominator_count is not None
        and source_counts
        and denominator_count > min(source_counts)
    ):
        violations.append(
            f"{source_location}: eligible denominator {denominator_count} exceeds a "
            f"source candidate count (minimum {min(source_counts)})"
        )

    source_families = {
        tool_families.get(str((target.node or {}).get("oracle_tool_ref") or ""))
        for target in derived_targets
    }
    source_families.discard(None)
    required_families = {"cctbx", "non_cctbx"}
    if not required_families.issubset(source_families):
        violations.append(
            f"{source_location}: {T14_FLIP_CONFLICT_METRIC} source families are "
            f"{sorted(source_families)!r}; both cctbx and non_cctbx are required"
        )
    if "cctbx" in source_families and row.get("oracle_family") == "non_cctbx":
        violations.append(
            f"{source_location}: {T14_FLIP_CONFLICT_METRIC} depends on a cctbx "
            "source and must not claim oracle_family non_cctbx"
        )
    if row.get("oracle_tool_ref") != "mmtbx.reduce2" or row.get("oracle_family") != "cctbx":
        violations.append(
            f"{source_location}: {T14_FLIP_CONFLICT_METRIC} must conservatively "
            "identify its cctbx dependency as mmtbx.reduce2 / cctbx"
        )


def check_measurement_catalog_semantics(
    indices: CorpusIndices,
    *,
    enforce_legacy_policy: bool = False,
) -> list[str]:
    """Validate catalog-owned metric/task, tool/family, and tool/task semantics."""
    metric_tasks = _canonical_metric_tasks()
    catalog_tool_families = _canonical_tool_families()
    catalog_tool_tasks = _canonical_tool_tasks()
    seen_legacy_exceptions: set[tuple[str, str, str, str]] = set()
    violations: list[str] = []

    for targets in indices["measurement"].values():
        for source in targets:
            row = source.node
            if not isinstance(row, dict):
                continue
            location = _measurement_location(source)

            metric_ref = row.get("metric_definition_ref")
            task_ref = row.get("catalog_task_ref")
            authoritative_metric_tasks = dict(metric_tasks)
            authoritative_metric_tasks.update(
                (metric, frozenset(tasks))
                for metric, tasks in source.source_metric_tasks
            )
            applicable_tasks = (
                authoritative_metric_tasks.get(metric_ref)
                if isinstance(metric_ref, str)
                else None
            )
            if (
                applicable_tasks is not None
                and isinstance(task_ref, str)
                and task_ref not in applicable_tasks
                and not _legacy_measurement_semantic_exception(
                    "metric_task", source, seen_legacy_exceptions
                )
            ):
                violations.append(
                    f"{location}: metric_definition_ref {metric_ref!r} is applicable "
                    f"only to catalog tasks {sorted(applicable_tasks)!r}, not "
                    f"catalog_task_ref {task_ref!r}"
                )

            tool_ref = row.get("oracle_tool_ref")
            if isinstance(tool_ref, str):
                # A source-owned Tool declaration records the family as of that
                # immutable EvaluationRun. Its complete task declaration has the
                # same precedence. Unpinned tools fall back to the live catalog.
                authoritative_families = dict(catalog_tool_families)
                authoritative_families.update(dict(source.source_tool_families))
                expected_family = authoritative_families.get(tool_ref)
                if (
                    expected_family is not None
                    and row.get("oracle_family") != expected_family
                ):
                    violations.append(
                        f"{location}: oracle_family {row.get('oracle_family')!r} does "
                        f"not match authoritative family {expected_family!r} for "
                        f"oracle_tool_ref {tool_ref!r}"
                    )

                authoritative_tool_tasks = dict(catalog_tool_tasks)
                authoritative_tool_tasks.update(
                    (tool, frozenset(tasks))
                    for tool, tasks in source.source_tool_tasks
                )
                served_tasks = authoritative_tool_tasks.get(tool_ref)
                if (
                    served_tasks is not None
                    and isinstance(task_ref, str)
                    and task_ref not in served_tasks
                    and not _legacy_measurement_semantic_exception(
                        "tool_task", source, seen_legacy_exceptions
                    )
                ):
                    violations.append(
                        f"{location}: oracle_tool_ref {tool_ref!r} serves only "
                        f"catalog tasks {sorted(served_tasks)!r}, not "
                        f"catalog_task_ref {task_ref!r}"
                    )

    if enforce_legacy_policy:
        for key in sorted(
            set(LEGACY_MEASUREMENT_SEMANTIC_EXCEPTIONS)
            - seen_legacy_exceptions
        ):
            violations.append(
                "stale or changed legacy measurement semantic exception was not "
                f"consumed: rule={key[0]} path={key[1]} run={key[2]} row={key[3]}"
            )
    return violations


def check_measurement_relations(indices: CorpusIndices) -> list[str]:
    """Validate typed MeasurementValue-to-MeasurementValue relationships."""
    violations: list[str] = []
    for targets in indices["measurement"].values():
        for source in targets:
            if not isinstance(source.node, dict):
                continue
            _check_pair_delta(source, indices, violations)
            derived_targets = _check_derived_measurement_refs(source, indices, violations)
            _check_t14_flip_candidate_interpretation(source, violations)
            _check_t14_flip_conflict_derivation(source, derived_targets, violations)
    _check_measurement_relation_cycles(indices, violations)
    return violations


def _check_measurement_relation_cycles(
    indices: CorpusIndices, violations: list[str]
) -> None:
    """Reject cycles across all directional measurement-lineage relations."""
    unique_targets = {
        measurement_id: targets[0]
        for measurement_id, targets in indices["measurement"].items()
        if len(targets) == 1 and isinstance(targets[0].node, dict)
    }
    edges: dict[str, set[str]] = {}
    for measurement_id, source in unique_targets.items():
        source_node = source.node or {}
        refs: list[Any] = [source_node.get("delta_from_measurement_ref")]
        derived_refs = source_node.get("derived_from_measurement_refs")
        if isinstance(derived_refs, list):
            refs.extend(derived_refs)
        for ref in refs:
            target = unique_targets.get(ref) if isinstance(ref, str) else None
            if (
                target is not None
                and target.owner_run_id == source.owner_run_id
                and ref != measurement_id
            ):
                edges.setdefault(measurement_id, set()).add(ref)

    state: dict[str, int] = {}
    stack: list[str] = []
    positions: dict[str, int] = {}

    def visit(measurement_id: str) -> None:
        state[measurement_id] = 1
        positions[measurement_id] = len(stack)
        stack.append(measurement_id)
        for target_id in sorted(edges.get(measurement_id, set())):
            if state.get(target_id, 0) == 0:
                visit(target_id)
            elif state.get(target_id) == 1:
                cycle = stack[positions[target_id]:] + [target_id]
                source = unique_targets[measurement_id]
                violations.append(
                    f"{_measurement_location(source)} measurement lineage forms a "
                    f"cycle: {' -> '.join(cycle)}"
                )
        stack.pop()
        positions.pop(measurement_id, None)
        state[measurement_id] = 2

    for measurement_id in sorted(edges):
        if state.get(measurement_id, 0) == 0:
            visit(measurement_id)


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
    catalog = strict_yaml_load(CATALOG.read_text()) or {}
    return {
        str(tool["id"]): str(tool["family"])
        for tool in catalog.get("tools", []) or []
        if isinstance(tool, dict) and tool.get("id") and tool.get("family")
    }


def _canonical_tool_tasks() -> dict[str, frozenset[str]]:
    """Return the catalog-authoritative task applicability for each tool."""
    catalog = strict_yaml_load(CATALOG.read_text()) or {}
    return {
        str(tool["id"]): frozenset(
            str(task) for task in tool.get("catalog_tasks_served", []) or []
        )
        for tool in catalog.get("tools", []) or []
        if isinstance(tool, dict) and tool.get("id")
    }


def _canonical_metric_tasks() -> dict[str, frozenset[str]]:
    """Return the catalog-authoritative task applicability for each metric."""
    catalog = strict_yaml_load(CATALOG.read_text()) or {}
    return {
        str(metric["id"]): frozenset(
            str(task) for task in metric.get("applicable_task_refs", []) or []
        )
        for metric in catalog.get("metric_definitions", []) or []
        if isinstance(metric, dict) and metric.get("id")
    }


def _json_default(value: Any) -> dict[str, str]:
    """Represent YAML-native scalars deterministically in exception digests."""
    if isinstance(value, (date, datetime)):
        return {
            "__yaml_scalar_type__": type(value).__name__,
            "value": value.isoformat(),
        }
    return {
        "__python_type__": type(value).__name__,
        "value": repr(value),
    }


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=_json_default,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _canonical_datetime_text(value: Any) -> str | None:
    """Normalize a YAML string/native datetime to one UTC instant."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    try:
        return parsed.astimezone(timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _legacy_measurement_semantic_exception(
    rule: str,
    target: RefTarget,
    seen: set[tuple[str, str, str, str]],
) -> bool:
    """Consume one exact, content-addressed historical semantic exception."""
    row = target.node
    if not isinstance(row, dict):
        return False
    run_id = target.owner_run_id
    row_id = row.get("id")
    if not isinstance(run_id, str) or not isinstance(row_id, str):
        return False
    key = (rule, _shown(target.file).as_posix(), run_id, row_id)
    expected = LEGACY_MEASUREMENT_SEMANTIC_EXCEPTIONS.get(key)
    if expected is None or key in seen or _canonical_digest(row) != expected:
        return False
    seen.add(key)
    return True


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


def check_qds_contract_floor(
    doc: dict[str, Any], yaml_path: Path, root: Path = REPO
) -> list[str]:
    """Reject replay-only emitter contracts on new committed QDS carriers."""
    if not isinstance(doc, dict):
        return []
    try:
        rel = yaml_path.absolute().relative_to(root.absolute())
    except ValueError:
        return []
    try:
        import check_qds_trust_invariant as trust_guard
    except ImportError:
        from scripts import check_qds_trust_invariant as trust_guard

    violations: list[str] = []
    for qds_i, qds in enumerate(doc.get("quality_data_sheets") or []):
        if not isinstance(qds, dict):
            continue
        error = trust_guard.qds_contract_policy_error(yaml_path, root, qds)
        if error is not None:
            violations.append(
                f"{rel}: $.quality_data_sheets[{qds_i}]: {error}"
            )
    return violations


def check_record_carrier_route(
    doc: dict[str, Any], yaml_path: Path, root: Path = REPO
) -> list[str]:
    """Keep Eval/QDS objects out of schema-valid but unguarded containers."""
    if not isinstance(doc, dict):
        return []
    try:
        rel = yaml_path.absolute().relative_to(root.absolute())
    except ValueError:
        return []
    under_data = bool(rel.parts and rel.parts[0] == "data")
    canonical_eval = (
        under_data and rel.suffix == ".yaml" and rel.stem.startswith("EVAL_")
    )
    canonical_qds = (
        under_data and rel.suffix == ".yaml" and rel.stem.startswith("QDS_")
    )

    violations: list[str] = []
    if yaml_path.is_symlink() and (
        "evaluation_runs" in doc or "quality_data_sheets" in doc
    ):
        violations.append(
            f"{rel}: EvaluationRun/QualityDataSheet carriers must be regular "
            "files; YAML symlinks are not permitted"
        )
    if "evaluation_runs" in doc and not canonical_eval:
        violations.append(
            f"{rel}: evaluation_runs may only be carried by canonical "
            "data/**/EVAL_*.yaml records"
        )
    if "quality_data_sheets" in doc and not canonical_qds:
        violations.append(
            f"{rel}: quality_data_sheets may only be carried by canonical "
            "data/**/QDS_*.yaml records"
        )
    return violations


def check_repository_record_carriers(
    root: Path = REPO, exclude_paths: Iterable[Path] = ()
) -> list[str]:
    """Inspect YAML outside normal record discovery for hidden Eval/QDS rows."""
    excluded = {path.absolute() for path in exclude_paths}
    violations: list[str] = []
    for path in repository_yaml_paths(root):
        if path.absolute() in excluded:
            continue
        try:
            doc = strict_yaml_load(path.read_text())
        except (yaml.YAMLError, OSError, UnicodeError) as exc:
            try:
                shown = path.absolute().relative_to(root.absolute())
            except ValueError:
                shown = path
            violations.append(
                f"{shown}: cannot inspect YAML for noncanonical Eval/QDS "
                f"carriers ({type(exc).__name__}): {exc}"
            )
            continue
        if not isinstance(doc, dict):
            continue
        violations.extend(check_record_carrier_route(doc, path, root))
        violations.extend(check_qds_contract_floor(doc, path, root))
    return violations


def _check_data_record_filename(doc: dict[str, Any], rel: Path) -> list[str]:
    """Keep record-shaped data YAML discoverable by every authoritative gate."""
    repo_rel = _repository_relative(rel)
    if repo_rel is None or not repo_rel.parts or repo_rel.parts[0] != "data":
        return []

    violations: list[str] = []
    eval_rows = doc.get("evaluation_runs") or []
    if "evaluation_runs" in doc:
        if repo_rel.suffix != ".yaml":
            violations.append(
                f"{rel}: a data YAML carrying evaluation_runs must use the .yaml suffix"
            )
        if not repo_rel.stem.startswith("EVAL_"):
            violations.append(
                f"{rel}: a data YAML carrying evaluation_runs must use an "
                "EVAL_*.yaml filename"
            )
        if isinstance(eval_rows, list):
            for i, run in enumerate(eval_rows):
                if not isinstance(run, dict):
                    continue
                declared_stem = run.get("eval_filename_stem")
                if not isinstance(declared_stem, str) or not declared_stem.strip():
                    violations.append(
                        f"{rel}: $.evaluation_runs[{i}].eval_filename_stem must be "
                        f"a nonblank string matching filename stem {repo_rel.stem!r}"
                    )
                elif declared_stem != repo_rel.stem:
                    violations.append(
                        f"{rel}: $.evaluation_runs[{i}].eval_filename_stem = "
                        f"{declared_stem!r} does not match filename stem "
                        f"{repo_rel.stem!r}"
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


def _check_evidence_path(
    ref: str, rel: Path, path: str, *, reject_self: bool = False
) -> tuple[list[str], bool]:
    """Resolve path-like evidence and report whether it is a retained repo file."""
    repository_uri = ref.startswith("repo:")
    path_text = ref.removeprefix("repo:") if repository_uri else ref
    posix_path = Path(path_text)
    windows_path = PureWindowsPath(path_text)
    if posix_path.is_absolute() or windows_path.is_absolute() or ref.startswith("file:"):
        return [f"{rel}: {path} = {ref!r} is an absolute, non-portable evidence path"], False
    if not repository_uri and _is_url_or_citation_with_slash(ref):
        return [], False
    raw_path = path_text.split("#", 1)[0]
    if (
        not repository_uri
        and "/" not in path_text
        and "\\" not in path_text
        and not path_text.startswith(".")
        and Path(raw_path).suffix.lower() not in EVIDENCE_FILE_SUFFIXES
    ):
        return [], False

    # Repository refs use POSIX separators in YAML. Treat a backslash as path syntax
    # (so it cannot masquerade as a citation) but reject it as non-portable.
    if "\\" in path_text:
        return [f"{rel}: {path} = {ref!r} is not a portable repository evidence path"], False
    resolved = (REPO / raw_path).resolve()
    try:
        resolved.relative_to(REPO.resolve())
    except ValueError:
        return [f"{rel}: {path} = {ref!r} escapes the repository"], False
    if not resolved.is_file():
        return [f"{rel}: {path} = {ref!r} does not resolve to a repository file"], False
    current_file = rel.resolve() if rel.is_absolute() else (REPO / rel).resolve()
    if reject_self and resolved == current_file:
        return [
            f"{rel}: {path} = {ref!r} is circular: a record cannot cite its own "
            "carrier file as evidence"
        ], False
    return [], True


def _contract4_projection(
    context: dict[str, Any],
    indices: CorpusIndices,
    rel: Path,
    path: str,
    violations: list[str],
) -> dict[str, Any] | None:
    """Validate the exact source graph with the retained contract-4 projector.

    Original carrier snapshots, including withdrawn rows, are passed intact.
    Resolving only surviving output rows would let a bad correction hide its
    target or let old sources acquire today's registry metadata.
    """
    refs = context.get("source_evaluation_run_refs")
    if not isinstance(refs, list) or not refs:
        return None  # The context relationship checks report this malformed list.
    documents: list[dict[str, Any]] = []
    seen_files: set[Path] = set()
    for ref in refs:
        if not isinstance(ref, str):
            return None
        targets = indices["evaluation_run"].get(ref, [])
        if len(targets) != 1:
            return None  # The caller resolves the same refs with precise paths.
        target = targets[0]
        if not isinstance(target.source_document, dict):
            violations.append(
                f"{rel}: {path} source run {ref!r} has no original source carrier"
            )
            return None
        file = target.file.absolute()
        if file not in seen_files:
            seen_files.add(file)
            documents.append(target.source_document)
    try:
        from qds_emit_contract_v4 import prepare_projection

        return prepare_projection(
            documents,
            qds_id=str(context.get("qds_ref") or ""),
            structure_id=str(context.get("structure_ref") or ""),
            repo_root=REPO,
        )
    except (ImportError, OSError, ValueError, TypeError, KeyError, SystemExit) as exc:
        violations.append(f"{rel}: {path} invalid contract-4 source projection: {exc}")
        return None


def _contract4_tool_families(
    qds: dict[str, Any], indices: CorpusIndices
) -> tuple[tuple[str, str], ...]:
    """Find the source-owned authority, never a live fallback, for v4 payloads."""
    contexts = indices["qds_emission_context"].get(qds.get("emission_context_ref"), [])
    if len(contexts) != 1 or not isinstance(contexts[0].node, dict):
        return ()
    owner = contexts[0].node.get("snapshot_owner_evaluation_run_ref")
    targets = indices["evaluation_run"].get(owner, [])
    if len(targets) != 1:
        return ()
    return targets[0].source_tool_families


def _check_corrected_qds_refs(
    context: dict[str, Any], indices: CorpusIndices, rel: Path, path: str,
    violations: list[str],
) -> None:
    refs = context.get("corrected_qds_refs", [])
    if not isinstance(refs, list):
        violations.append(f"{rel}: {path}.corrected_qds_refs must be a list")
        return
    seen: set[str] = set()
    issued = _canonical_datetime_text(context.get("issued_at"))
    for index, ref in enumerate(refs):
        ref_path = f"{path}.corrected_qds_refs[{index}]"
        if not isinstance(ref, str) or not ref.strip():
            violations.append(f"{rel}: {ref_path} must name an earlier QualityDataSheet")
            continue
        if ref in seen:
            violations.append(f"{rel}: {ref_path} duplicates {ref!r}")
        seen.add(ref)
        target = _resolve(ref, "quality_data_sheet", indices, rel, ref_path, violations)
        if target is None or not isinstance(target.node, dict):
            continue
        previous = target.node
        previous_time = _canonical_datetime_text(previous.get("issued_at"))
        if (ref == context.get("qds_ref") or issued is None or previous_time is None
                or datetime.fromisoformat(previous_time) >= datetime.fromisoformat(issued)):
            violations.append(f"{rel}: {ref_path} must name a strictly earlier QualityDataSheet")
        if previous.get("structure_ref") != context.get("structure_ref"):
            violations.append(f"{rel}: {ref_path} names a QualityDataSheet for another structure")


def check_corpus_refs(doc: Any, rel: Path, indices: CorpusIndices) -> list[str]:
    """Resolve references whose targets can live in another YAML document."""
    violations: list[str] = []
    if not isinstance(doc, dict):
        return violations
    violations += _check_data_record_filename(doc, rel)

    # A path to an EVAL carrier must not turn an EvaluationRun into generic file
    # evidence.  Criterion preconditions cite EvaluationRun ids so their dates can
    # be checked; accepting the carrier path would bypass that temporal check.
    evaluation_carrier_files = {
        (
            target.file.resolve()
            if target.file.is_absolute()
            else (REPO / target.file).resolve()
        )
        for targets in indices["evaluation_run"].values()
        for target in targets
    }

    local_run_ids = {
        str(run.get("id"))
        for run in doc.get("evaluation_runs", []) or []
        if isinstance(run, dict) and run.get("id")
    }
    for run_i, run in enumerate(doc.get("evaluation_runs", []) or []):
        if not isinstance(run, dict) or not run.get("corrections"):
            continue
        run_id = run.get("id")
        owned_contexts = [
            target.node
            for targets in indices["qds_emission_context"].values()
            for target in targets
            if isinstance(target.node, dict)
            and run_id in (target.node.get("source_evaluation_run_refs") or [])
            and any(
                isinstance(qds_target.node, dict)
                and str(qds_target.node.get("emitter_contract_version")) == "4"
                for qds_target in indices["quality_data_sheet"].get(
                    target.node.get("qds_ref"), []
                )
            )
        ]
        if not owned_contexts:
            violations.append(
                f"{rel}: $.evaluation_runs[{run_i}].corrections is orphaned: "
                "its owning run must be an input to a source-owned contract-4 context"
            )
        # Validate here too when the owner and the context have different carriers.
        for context in owned_contexts:
            _contract4_projection(context, indices, rel,
                                  f"$.evaluation_runs[{run_i}].corrections", violations)
    for context_i, context in enumerate(doc.get("qds_emission_contexts", []) or []):
        if not isinstance(context, dict):
            continue
        context_path = f"$.qds_emission_contexts[{context_i}]"
        context_id = context.get("id")
        if not (
            rel.parts
            and rel.parts[0] == "data"
            and rel.name.startswith("EVAL_")
            and rel.suffix == ".yaml"
        ):
            violations.append(
                f"{rel}: {context_path} must live in a canonical data/**/EVAL_*.yaml "
                "source carrier"
            )
        qds_ref = context.get("qds_ref")
        qds_target = None
        if isinstance(qds_ref, str):
            qds_target = _resolve(
                qds_ref,
                "quality_data_sheet",
                indices,
                rel,
                f"{context_path}.qds_ref",
                violations,
            )
        else:
            violations.append(
                f"{rel}: {context_path}.qds_ref must name a QualityDataSheet"
            )
        source_refs = context.get("source_evaluation_run_refs")
        if not isinstance(source_refs, list) or not source_refs or not all(
            isinstance(ref, str) for ref in source_refs
        ):
            violations.append(
                f"{rel}: {context_path}.source_evaluation_run_refs must be a "
                "non-empty list of EvaluationRun ids"
            )
            source_refs = []
        elif len(source_refs) != len(set(source_refs)):
            violations.append(
                f"{rel}: {context_path}.source_evaluation_run_refs repeats an id"
            )
        for ref_i, run_ref in enumerate(source_refs):
            _resolve(
                run_ref,
                "evaluation_run",
                indices,
                rel,
                f"{context_path}.source_evaluation_run_refs[{ref_i}]",
                violations,
            )
        owner_ref = context.get("owner_evaluation_run_ref")
        if not isinstance(owner_ref, str) or owner_ref not in source_refs:
            violations.append(
                f"{rel}: {context_path}.owner_evaluation_run_ref must name one of "
                "its source EvaluationRuns"
            )
        elif owner_ref not in local_run_ids:
            violations.append(
                f"{rel}: {context_path}.owner_evaluation_run_ref must resolve in "
                "the same document"
            )
        target_contract = (
            str(qds_target.node.get("emitter_contract_version") or "")
            if qds_target is not None and isinstance(qds_target.node, dict) else ""
        )
        if target_contract != "4" and context.get("coverage_scope") != "partial":
            violations.append(
                f"{rel}: {context_path}.coverage_scope must be 'partial'"
            )
        if target_contract == "4":
            if context.get("snapshot_owner_evaluation_run_ref") != owner_ref:
                violations.append(
                    f"{rel}: {context_path}.snapshot_owner_evaluation_run_ref must "
                    "name the context's owning source EvaluationRun"
                )
            _check_corrected_qds_refs(context, indices, rel, context_path, violations)
            _contract4_projection(context, indices, rel, context_path, violations)
        elif any(key in context for key in (
            "snapshot_owner_evaluation_run_ref", "corrected_qds_refs", "dataset_associations"
        )):
            violations.append(f"{rel}: {context_path} carries contract-4-only context fields")
        if qds_target is not None and isinstance(qds_target.node, dict):
            qds = qds_target.node
            if target_contract not in {"3", "4"}:
                violations.append(
                    f"{rel}: {context_path}.qds_ref must target emitter contract 3 or 4"
                )
            expected_pairs = (
                ("emission_context_ref", context_id),
                ("structure_ref", context.get("structure_ref")),
                ("subject_ref", context.get("subject_ref")),
                ("issued_at", context.get("issued_at")),
                ("coverage_scope", context.get("coverage_scope")),
                ("scope_notes", context.get("scope_notes")),
                ("headline_verdict", context.get("headline_verdict")),
            )
            for field, expected in expected_pairs:
                actual = qds.get(field)
                if field == "issued_at":
                    actual_time = _canonical_datetime_text(actual)
                    values_match = (
                        actual_time is not None
                        and actual_time == _canonical_datetime_text(expected)
                    )
                else:
                    values_match = str(actual or "") == str(expected or "")
                if not values_match:
                    violations.append(
                        f"{rel}: {context_path}.{field} differs from target QDS "
                        f"{qds_ref!r}"
                    )
            qds_refs = qds.get("derived_from_evaluation_run_refs") or []
            if source_refs != qds_refs:
                violations.append(
                    f"{rel}: {context_path}.source_evaluation_run_refs differs "
                    f"from target QDS {qds_ref!r} derivation refs"
                )
            identity = qds.get("identity_block")
            qds_description = (
                identity.get("description") if isinstance(identity, dict) else None
            )
            if str(qds_description or "") != str(
                context.get("identity_description") or ""
            ):
                violations.append(
                    f"{rel}: {context_path}.identity_description differs from "
                    f"target QDS {qds_ref!r} identity_block.description"
                )

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
            pin_context_ref = pin.get("qds_emission_context_ref")
            qds_context_ref = qds_target.node.get("emission_context_ref")
            context_required = (
                pin_contract == "4" or (
                    pin_contract == "3"
                    and qds_target.node.get("coverage_scope") == "partial"
                )
            )
            if context_required:
                if not isinstance(pin_context_ref, str):
                    violations.append(
                        f"{rel}: {pin_path}.qds_emission_context_ref is required "
                        "for partial contract-3 and every contract-4 QDS"
                    )
                else:
                    context_target = _resolve(
                        pin_context_ref,
                        "qds_emission_context",
                        indices,
                        rel,
                        f"{pin_path}.qds_emission_context_ref",
                        violations,
                    )
                    if pin_context_ref != qds_context_ref:
                        violations.append(
                            f"{rel}: {pin_path}.qds_emission_context_ref differs "
                            f"from target QDS {qds_ref!r}"
                        )
                    if (
                        context_target is not None
                        and isinstance(context_target.node, dict)
                        and context_target.node.get("qds_ref") != qds_ref
                    ):
                        violations.append(
                            f"{rel}: {pin_path}.qds_emission_context_ref targets a "
                            "context owned by another QDS"
                        )
                digest = pin.get("source_qds_emission_context_sha256")
                if not isinstance(digest, str) or not re.fullmatch(
                    r"[0-9a-f]{64}", digest
                ):
                    violations.append(
                        f"{rel}: {pin_path}.source_qds_emission_context_sha256 "
                        "must be a lowercase SHA-256 digest for partial "
                        "contract-3 and every contract-4 QDS"
                    )
            elif pin_context_ref is not None or pin.get(
                "source_qds_emission_context_sha256"
            ) is not None:
                violations.append(
                    f"{rel}: {pin_path} carries partial-sheet emission-context "
                    f"fields under contract/scope {pin_contract!r}/"
                    f"{qds_target.node.get('coverage_scope')!r}"
                )
            for field in ("source_evaluation_runs_sha256", "source_structures_sha256"):
                digest = pin.get(field)
                if pin_contract == "4":
                    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                        violations.append(
                            f"{rel}: {pin_path}.{field} must be a lowercase SHA-256 "
                            "digest for contract 4"
                        )
                elif field in pin:
                    violations.append(f"{rel}: {pin_path}.{field} is only permitted for contract 4")

    def check(
        node: Any,
        path: str,
        current_run: dict[str, Any] | None = None,
        current_qds: dict[str, Any] | None = None,
        copied_source_key: str | None = None,
        qds_block: str | None = None,
        routed_scalar_slot: bool = False,
        in_criterion_precondition: bool = False,
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
                    source_families = source_measurement.source_tool_families
                    if (current_qds is not None
                            and str(current_qds.get("emitter_contract_version")) == "4"):
                        source_families = _contract4_tool_families(current_qds, indices)
                        if not source_families:
                            violations.append(
                                f"{rel}: {path} has no contract-4 snapshot-owner "
                                "Tool authority for source comparison"
                            )
                    expected = _expected_wrapped_measurement(
                        source_node,
                        source_run_ref,
                        source_families,
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
                if (
                    node is current_qds
                    and str(current_qds.get("emitter_contract_version")) == "4"
                    and re.fullmatch(r"\$\.quality_data_sheets\[\d+\]", path)
                    and key == "measurement_evidence_origins"
                ):
                    # This exact schema-owned field is derived audit metadata,
                    # not a collection of copied scalar values. Compare its
                    # complete ordered payload against the source projection
                    # below; similarly named/nested fields receive no exemption.
                    continue
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
                    has_retained_precondition_evidence = False
                    for i, ref in enumerate(value):
                        if not isinstance(ref, str):
                            continue
                        evidence_path = f"{child}[{i}]"
                        # EVAL_* is reserved for EvaluationRun ids, but the schema
                        # deliberately leaves EvaluationRun.id unconstrained.  An
                        # exact indexed id is therefore run evidence regardless of
                        # prefix; unresolved arbitrary tokens remain citations.
                        if (ref.startswith("EVAL_")
                                or ref in indices["evaluation_run"]):
                            target = _resolve(
                                ref,
                                "evaluation_run",
                                indices,
                                rel,
                                evidence_path,
                                violations,
                            )
                            if target is not None and (
                                current_run is None or not in_criterion_precondition
                            ):
                                has_retained_precondition_evidence = True
                            elif target is not None and current_run is not None:
                                current_id = current_run.get("id")
                                evidence_date = _iso_date(target.run_date)
                                current_date = _iso_date(current_run.get("run_date"))
                                if ref == current_id:
                                    violations.append(
                                        f"{rel}: {evidence_path} = {ref!r} is circular: "
                                        "an EvaluationRun cannot cite itself as evidence"
                                    )
                                elif (evidence_date is None or current_date is None
                                      or evidence_date >= current_date):
                                    violations.append(
                                        f"{rel}: {evidence_path} = {ref!r} is dated "
                                        f"{evidence_date!r}, not earlier than owning "
                                        f"EvaluationRun {current_id!r} dated {current_date!r}"
                                    )
                                else:
                                    has_retained_precondition_evidence = True
                        else:
                            path_violations, retained = _check_evidence_path(
                                ref, rel, evidence_path,
                                reject_self=in_criterion_precondition,
                            )
                            violations.extend(path_violations)
                            if retained and in_criterion_precondition:
                                path_text = ref.removeprefix("repo:")
                                resolved_evidence = (
                                    REPO / path_text.split("#", 1)[0]
                                ).resolve()
                                if resolved_evidence in evaluation_carrier_files:
                                    violations.append(
                                        f"{rel}: {evidence_path} = {ref!r} names an "
                                        "EvaluationRun carrier by path; cite the "
                                        "strictly earlier EvaluationRun id so its "
                                        "date is checked"
                                    )
                                    retained = False
                            has_retained_precondition_evidence |= retained
                    if (in_criterion_precondition
                            and not has_retained_precondition_evidence):
                        violations.append(
                            f"{rel}: {child} must include at least one distinct "
                            "repository file or strictly earlier EvaluationRun; "
                            "citations and URLs may only supplement retained evidence"
                        )
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
                    if (current_qds is not None
                            and str(current_qds.get("emitter_contract_version")) == "4"
                            and child_qds_block == "data_quality_summary"
                            and key == "diagnostics"):
                        # Unlike singleton mapped slots this is a list of wrappers.
                        # The obligation propagates to each item even if an attacker
                        # deletes all of its self-describing provenance fields.
                        child_is_routed_scalar = True
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
                        in_criterion_precondition or key == "criterion_preconditions",
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
                    in_criterion_precondition,
                )

    check(doc, "$")

    # Supersession is an operation on an ordered emitter input, not just a date claim.
    # Whenever a QDS includes a superseding run, the run owning the withdrawn
    # assumption must also be present earlier in that same input list.
    for qds_i, qds in enumerate(doc.get("quality_data_sheets") or []):
        if not isinstance(qds, dict):
            continue
        qds_path = f"$.quality_data_sheets[{qds_i}]"
        qds_contract = str(qds.get("emitter_contract_version") or "")
        qds_scope = qds.get("coverage_scope")
        context_ref = qds.get("emission_context_ref")
        context_target = None
        if qds_contract == "4" or (qds_contract == "3" and qds_scope == "partial"):
            if not isinstance(context_ref, str) or not context_ref.strip():
                violations.append(
                    f"{rel}: {qds_path}.emission_context_ref is required for a "
                    "partial contract-3 or any contract-4 QDS"
                )
            else:
                context_target = _resolve(
                    context_ref,
                    "qds_emission_context",
                    indices,
                    rel,
                    f"{qds_path}.emission_context_ref",
                    violations,
                )
                if (
                    context_target is not None
                    and isinstance(context_target.node, dict)
                    and context_target.node.get("qds_ref") != qds.get("id")
                ):
                    violations.append(
                        f"{rel}: {qds_path}.emission_context_ref targets a context "
                        "owned by another QDS"
                    )
        elif context_ref is not None:
            violations.append(
                f"{rel}: {qds_path}.emission_context_ref is only permitted on a "
                "partial contract-3 or any contract-4 QDS"
            )
        v4_fields = (
            "active_evaluation_run_refs", "applied_corrections",
            "dataset_associations", "corrected_qds_refs", "measurement_evidence_origins",
        )
        if qds_contract == "4":
            if context_target is not None and isinstance(context_target.node, dict):
                context = context_target.node
                _check_corrected_qds_refs(context, indices, rel, qds_path, violations)
                projection = _contract4_projection(context, indices, rel, qds_path, violations)
                for key in ("dataset_associations", "corrected_qds_refs"):
                    expected = context.get(key, [])
                    if key == "dataset_associations" and projection is not None:
                        expected = projection["dataset_associations"]
                    if qds.get(key, []) != expected:
                        violations.append(
                            f"{rel}: {qds_path}.{key} differs from its source-owned context"
                        )
                if projection is not None:
                    expected_active = [run["id"] for run in projection["runs"]]
                    if qds.get("active_evaluation_run_refs") != expected_active:
                        violations.append(
                            f"{rel}: {qds_path}.active_evaluation_run_refs differs "
                            "from the corrected, subject-eligible source projection"
                        )
                    if qds.get("applied_corrections", []) != projection["corrections"]:
                        violations.append(
                            f"{rel}: {qds_path}.applied_corrections differs from "
                            "the exact source-owned correction operations"
                        )
                    if qds.get("measurement_evidence_origins", []) != projection["measurement_evidence_origins"]:
                        violations.append(
                            f"{rel}: {qds_path}.measurement_evidence_origins differs from "
                            "the exact ordered source-derived measurement lineage"
                        )
        elif any(field in qds for field in v4_fields):
            violations.append(f"{rel}: {qds_path} carries contract-4-only evidence fields")
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


def check_record(
    yaml_path: Path, indices: dict[str, set[str]], doc: Any = None
) -> list[str]:
    """Return a list of human-readable violation messages for one record."""
    if doc is None:
        doc = strict_yaml_load(yaml_path.read_text())
    if doc is None:
        return []
    violations: list[str] = []
    rel = yaml_path.relative_to(REPO)
    violations += check_record_carrier_route(doc, yaml_path)
    violations += check_qds_contract_floor(doc, yaml_path)

    for collection in ("catalog_tasks", "tools", "metric_definitions"):
        seen_ids: set[str] = set()
        for index, row in enumerate(doc.get(collection, []) or []):
            if not isinstance(row, dict) or not isinstance(row.get("id"), str):
                continue
            row_id = row["id"]
            if row_id in seen_ids:
                violations.append(
                    f"{rel}: $.{collection}[{index}].id duplicates {row_id!r} "
                    "within the same document"
                )
            seen_ids.add(row_id)

    # Local indices for refs that may resolve within the same document.
    local_metric_ids = {m["id"] for m in doc.get("metric_definitions", []) or []}
    local_tool_ids = {t["id"] for t in doc.get("tools", []) or []}
    local_structure_ids = {s["id"] for s in doc.get("structures", []) or []}

    metric_ok = indices["metric"] | local_metric_ids
    criterion_ok = indices["criterion"]
    tool_ok = indices["tool"] | local_tool_ids
    task_ok = indices["task"]

    # The schema declares `agent_claim`, `oracle_measure`, `delta` as
    # TypedMeasurementValue (not refs), so checking by-key is naive but
    # safe — the keys we look for are unambiguous in this schema.
    REF_KEYS = {
        "metric_definition_ref": ("metric", metric_ok),
        "pass_criterion_ref": ("criterion", criterion_ok),
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
    try:
        indices = load_catalog_indices()
    except (
        yaml.YAMLError,
        OSError,
        UnicodeError,
        AttributeError,
        TypeError,
        KeyError,
    ) as exc:
        print(
            "FAIL: authoritative catalog/criterion registry is unreadable: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1
    failed = False
    records: list[tuple[Path, Any]] = []
    for path in target_paths():
        try:
            records.append((path, strict_yaml_load(path.read_text())))
        except (yaml.YAMLError, OSError, UnicodeError) as e:
            print(
                f"FAIL: {path.relative_to(REPO)}: unreadable "
                f"({type(e).__name__}): {e}",
                file=sys.stderr,
            )
            failed = True

    for violation in check_repository_record_carriers(
        REPO, (path for path, _doc in records)
    ):
        print(f"FAIL: {violation}", file=sys.stderr)
        failed = True

    corpus_indices = build_corpus_indices(records)
    for violation in check_duplicate_ids(corpus_indices):
        print(f"FAIL: {violation}", file=sys.stderr)
        failed = True

    for violation in check_measurement_relations(corpus_indices):
        print(f"FAIL: {violation}", file=sys.stderr)
        failed = True

    for violation in check_measurement_catalog_semantics(
        corpus_indices, enforce_legacy_policy=True
    ):
        print(f"FAIL: {violation}", file=sys.stderr)
        failed = True

    for path, doc in records:
        violations = check_record(path, indices, doc)
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
