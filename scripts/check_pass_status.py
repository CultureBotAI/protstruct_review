#!/usr/bin/env python3
"""Enforce evidence-bound ``pass_status`` semantics on EvaluationRun records.

The schema's verdict statuses are meaningful only when their criterion and
claim are machine-auditable. This guard therefore enforces:

  R0  Every PassStatus enum value is classified by this guard.
  R1  Verdict statuses carry a non-placeholder string criterion and, unless
      frozen as exact legacy content, a ``pass_criterion_ref`` that resolves to
      an applicable PassCriterionBinding for the row's exact metric. Threshold
      values remain authoritative only in the threshold registry and drivers.
  R2  ``informational`` carries no criterion metadata. ``criterion_inapplicable``
      names a binding whose evidence-backed required precondition is void/unknown.
  R3  Disagreement statuses carry a finite, unit-compatible numeric agent claim
      that differs from the oracle. A plain ``pass`` or ``fail_criterion`` may
      not retain an asserted claim unless it equals the oracle exactly.
  R4  ``fail_by_oracle_within_cctbx`` declares ``oracle_family: cctbx``.
  R5  Rows with identical scientific evidence, context, criterion, assumptions,
      and evidence references cannot assign different statuses within one run.

Legacy exceptions are content-addressed by exact path plus file or row SHA-256.
A date never grants an exemption, and unused exceptions fail as stale policy.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, time, timezone
from decimal import Decimal
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

try:
    from strict_yaml import strict_yaml_load
except ModuleNotFoundError:  # imported as scripts.check_pass_status
    from scripts.strict_yaml import strict_yaml_load


CRITERION_BEARING = frozenset({
    "pass",
    "fail_criterion",
    "fail_by_oracle",
    "pass_with_caveat",
    "pass_criterion_fail_headline",
    "fail_by_oracle_within_cctbx",
})
CLAIM_BEARING = frozenset({
    "fail_by_oracle", "fail_by_oracle_within_cctbx", "pass_with_caveat",
    "pass_criterion_fail_headline",
})
# Known statuses that do not assert a numeric outcome. R2 still governs them.
NON_VERDICT_STATUSES = frozenset({"informational", "criterion_inapplicable"})
INAPPLICABLE_STATUS = "criterion_inapplicable"
PLACEHOLDER_CRITERIA = frozenset({
    "n/a", "na", "-", "--", "tbd", "todo", "none", "see notes", "informational",
    "pass", "fail_criterion", "fail_by_oracle", "pass_with_caveat",
    "pass_criterion_fail_headline", "fail_by_oracle_within_cctbx",
    "criterion_inapplicable",
})
PLACEHOLDER_CLAIMS = frozenset({
    "n/a", "na", "-", "--", "none", "unknown", "not reported",
    "no result", "unavailable", "informational", "not applicable",
    "not available", "no claim", "not measured", "not provided",
    "not recorded", "no value", "no data", "no measurement", "no estimate",
})
NORMALIZED_PLACEHOLDER_CLAIMS = frozenset(
    re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
    for value in PLACEHOLDER_CLAIMS
)
PASSING_VERDICTS = frozenset({
    "pass", "pass_with_caveat", "pass_criterion_fail_headline",
})
FAILING_VERDICTS = frozenset({
    "fail_criterion", "fail_by_oracle", "fail_by_oracle_within_cctbx",
})

LEGACY_1SAR_PATH = "data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-04-24.yaml"
LEGACY_1SAR_RUN = "EVAL_1sar_cdba2c07_2026-04-24"

# These dated sources predate criterion bindings. They also feed immutable QDS
# artifacts, so rewriting them in place would make the source/derivative pair
# disagree. Exact content pins preserve the records as unvalidated history; they
# do not endorse their criteria or scientific conclusions. Any correction must
# be a new dated EvaluationRun/QDS with explicit correction lineage.
LEGACY_SYNTH_PATH = "data/examples/eval/EVAL_synth_active_site_2026-04-26.yaml"
LEGACY_SYNTH_RUN = "EVAL_synth_active_site_2026-04-26"
LEGACY_UNREGISTERED_CRITERION_FILES = {
    LEGACY_1SAR_PATH: "b3beb751fb99c94376002d88ccb7f8716b1dd4ae8177c40ff53b29ab12350532",
    LEGACY_SYNTH_PATH: "624435778056f93eea841f9062ce76a6dc78513f4361fc0e2ab6b6264dd6919e",
}

# Historical rows violate the now-explicit R2/R3 semantics. Each exemption binds the
# rule, path, owning run, row id, and complete parsed row. These are preservation
# pins, not claims that the legacy status is scientifically correct.
LEGACY_ROW_EXCEPTIONS = {
    ("R2", LEGACY_1SAR_PATH, LEGACY_1SAR_RUN,
     f"{LEGACY_1SAR_RUN}_M_003"):
        "009f755bd9ba09823ad13ae4a92d274137fdf23153192fec88ceff5f727a6227",
    ("R2", LEGACY_1SAR_PATH, LEGACY_1SAR_RUN,
     f"{LEGACY_1SAR_RUN}_M_012"):
        "910631fb5558df5cf2a0b425668d8fb7edfd54ba86552a0a5a7adbaffdda9e71",
    ("R2", LEGACY_1SAR_PATH, LEGACY_1SAR_RUN,
     f"{LEGACY_1SAR_RUN}_M_017"):
        "a340b481966cd3fd1683ee32a8c203bb64a0586045c772b2ac66b53d4bef43ed",
    ("R2", LEGACY_1SAR_PATH, LEGACY_1SAR_RUN,
     f"{LEGACY_1SAR_RUN}_M_018"):
        "73194e8be2b8aa13cdf5e93018bfd0a14f41aca9b97a88fd51c20aea0d26eecb",
    ("R2", LEGACY_1SAR_PATH, LEGACY_1SAR_RUN,
     f"{LEGACY_1SAR_RUN}_M_028"):
        "94b947bc8c219ca61dff0cf531b297cca425d8de42167d109b8b797c2a2b0d72",
    ("R2", LEGACY_1SAR_PATH, LEGACY_1SAR_RUN,
     f"{LEGACY_1SAR_RUN}_M_032"):
        "d84d323b7330e83664a2e29c3676d96dd844632eaeced0752a558be2bbc424e1",
    ("R2", LEGACY_1SAR_PATH, LEGACY_1SAR_RUN,
     f"{LEGACY_1SAR_RUN}_M_033"):
        "86d5e41767c4d1863e3f62e5e23fa8d11fff29b60ea0f97f471d64d877480a3b",
    ("R3", LEGACY_1SAR_PATH, LEGACY_1SAR_RUN,
     f"{LEGACY_1SAR_RUN}_M_prosmart_asn_a39_score"):
        "15757236cfd5525302634734a8e49db9cd4fb2bd6f5467e25ff81e29f15d2024",
    ("R3", LEGACY_1SAR_PATH, LEGACY_1SAR_RUN,
     f"{LEGACY_1SAR_RUN}_M_021"):
        "87db4746d39fdc810b4b943aa23e74d447f5d082acbd3c8b03f1b6af47a7c160",
    ("R3", LEGACY_1SAR_PATH, LEGACY_1SAR_RUN,
     f"{LEGACY_1SAR_RUN}_M_ca_b_vs_mean_ratio"):
        "f21f4c015e1c446f028811d4c5234827e9a1238705095b655cf2bca7c7b02359",
    ("R3", LEGACY_1SAR_PATH, LEGACY_1SAR_RUN,
     f"{LEGACY_1SAR_RUN}_M_ca_b_vs_protein"):
        "90d810d5c60d7cf0b63135eb467c78e0aed60c18b8398b1a7a11cd2238ed10d1",
    ("R3", LEGACY_1SAR_PATH, LEGACY_1SAR_RUN,
     f"{LEGACY_1SAR_RUN}_M_water_rscc_distribution"):
        "1e6d72b5901dff6f28b699b258df0c2a36859cfa8ca2386e3945a181a3cddbfa",
    ("R3", LEGACY_1SAR_PATH, LEGACY_1SAR_RUN,
     f"{LEGACY_1SAR_RUN}_M_ca_identity_z_ca"):
        "2edb31a055f89c2b322de980091eb1a0f72b8c44e8a5b5c37bff87deb8a82369",
    ("R3", LEGACY_1SAR_PATH, LEGACY_1SAR_RUN,
     f"{LEGACY_1SAR_RUN}_M_ca_identity_summary"):
        "72232ed456585690cb37e93ebd1b62d1f735c523c887d8f9e1c976d048c87f5d",
    ("R3", LEGACY_1SAR_PATH, LEGACY_1SAR_RUN,
     f"{LEGACY_1SAR_RUN}_M_na_identity_z_na"):
        "eff0e67eeef0f5b01f69f5389604f49ce993685dab38a3cc4a80a51d3d07e86f",
    ("R3", LEGACY_1SAR_PATH, LEGACY_1SAR_RUN,
     f"{LEGACY_1SAR_RUN}_M_na_identity_summary"):
        "fa4370a601c7877f807901931d249aaa52888d894788a0d386fb47b331f45219",
    ("R2", LEGACY_1SAR_PATH, LEGACY_1SAR_RUN,
     f"{LEGACY_1SAR_RUN}_M_ca_identity_z_mg"):
        "bca36de110182c252bd8e5678cb0c7a24621a32170e628df68c3199e0c9a40b0",
    ("R2", LEGACY_1SAR_PATH, LEGACY_1SAR_RUN,
     f"{LEGACY_1SAR_RUN}_M_na_identity_z_mg"):
        "ccd363dff8f3b18148f41edf9a15733778f2260ff687c03413aca13daf69cda0",
    ("R2", LEGACY_1SAR_PATH, LEGACY_1SAR_RUN,
     f"{LEGACY_1SAR_RUN}_M_t13_wilson_b"):
        "c459413d2cb056afc8f62744638b5c4ce032f513c7293e6f68dbfbc8a97a3fe1",
    ("R2", LEGACY_1SAR_PATH, LEGACY_1SAR_RUN,
     f"{LEGACY_1SAR_RUN}_M_t13_aimless_attempt"):
        "1de274aadddc8e3aacc71b67cd0e4d3083134f1fc5c608b584d82cda28970ac2",
    ("R2", LEGACY_1SAR_PATH, LEGACY_1SAR_RUN,
     f"{LEGACY_1SAR_RUN}_M_t13_ice_ring_flags"):
        "495891793a0f0e3c99d5b179316d8f93e8ee93554d5c28def2629bf5ed45cbd6",
    ("R3", LEGACY_SYNTH_PATH, LEGACY_SYNTH_RUN,
     f"{LEGACY_SYNTH_RUN}_M_002"):
        "6f1f4f0e77d56da2bdb852585f7f18e716687b05e2bebcd36aaae605c17c0b43",
    ("R3", LEGACY_SYNTH_PATH, LEGACY_SYNTH_RUN,
     f"{LEGACY_SYNTH_RUN}_M_003"):
        "99cc84d46ee1b69f8ff675772e242391e255204fb64091c54f53d725e44b89fa",
    ("R3", LEGACY_SYNTH_PATH, LEGACY_SYNTH_RUN,
     f"{LEGACY_SYNTH_RUN}_M_004"):
        "ebb78ed816028c4ed31e3757f678e9bf8cc069dbd74f4cddc8d5ec4a685d0a1c",
}

# R5 uses a complete structured semantic signature. Different subjects,
# selectors, values, criteria, assumptions, or retained evidence may
# legitimately get different statuses; free-text notes alone may not.
VERDICT_SIGNATURE_FIELDS = (
    "catalog_task_ref", "metric_definition_ref", "stage", "scope",
    "scope_selector", "subject_ref", "reference_subject_ref", "oracle_tool_ref",
    "oracle_family", "agent_claim", "oracle_measure", "delta",
    "delta_from_measurement_ref", "derived_from_measurement_refs",
    "pass_criterion", "pass_criterion_ref", "criterion_preconditions",
    "provenance_ref", "bundle_ref",
    "evidence_refs", "assumptions",
)

# These lists are semantically sets. Their YAML order must not create an R5 bypass.
SET_LIKE_SIGNATURE_FIELDS = frozenset({
    "derived_from_measurement_refs", "evidence_refs", "assumptions",
    "criterion_preconditions",
})
NESTED_QDS_LINEAGE_FIELDS = frozenset({
    "source_measurement_ref", "source_evaluation_run_ref",
    "metric_definition_ref", "oracle_tool_ref", "oracle_family",
    "pass_status", "pass_criterion", "subject_ref", "reference_subject_ref",
    "stage", "scope", "scope_selector", "evidence_refs", "bundle_ref",
})


class ConfigurationShapeError(ValueError):
    """A guard input parsed as YAML but does not have its declared shape."""


def _strict_yaml_load(text: str) -> Any:
    return strict_yaml_load(text)


def _mapping(value: Any, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigurationShapeError(f"{location} must be a mapping")
    invalid_keys = [key for key in value if not isinstance(key, str)]
    if invalid_keys:
        rendered = ", ".join(
            f"{type(key).__name__} {key!r}" for key in invalid_keys
        )
        raise ConfigurationShapeError(
            f"{location} keys must be strings; found {rendered}"
        )
    return value


def schema_enum_values(root: Path, enum_name: str) -> set[str]:
    """Read one enum from the Eval schema with explicit shape checks."""
    path = root / "schemas" / "protstruct_review.yaml"
    doc = _mapping(_strict_yaml_load(path.read_text()) or {}, "schema root")
    enums = _mapping(doc.get("enums"), "schema enums")
    enum = _mapping(enums.get(enum_name), f"schema enums.{enum_name}")
    values = _mapping(
        enum.get("permissible_values"),
        f"schema enums.{enum_name}.permissible_values",
    )
    if not all(isinstance(key, str) for key in values):
        raise ConfigurationShapeError(
            f"schema enums.{enum_name}.permissible_values keys must be strings"
        )
    return set(values)


def schema_statuses(root: Path) -> set[str]:
    """Read PassStatus values from the schema with explicit shape checks."""
    return schema_enum_values(root, "PassStatus")


def _normalize_registry_text(value: str) -> str:
    """Normalize Markdown presentation without changing scientific operators."""
    text = value
    # Remove only balanced presentation delimiters. A global ``*`` deletion
    # would silently turn an unsupported expression such as ``1*2`` into 12.
    for pattern in (r"\*\*([^*\n]+)\*\*", r"__([^_\n]+)__", r"`([^`\n]+)`"):
        text = re.sub(pattern, r"\1", text)
    text = (
        text.replace("≤", "<=").replace("≥", ">=").replace("−", "-")
        .replace("+/-", "±")
    )
    text = re.sub(r"\s*(<=|>=|<|>)\s*", r"\1", text)
    return re.sub(r"\s+", " ", text).strip().casefold()


_NUMBER_PATTERN = (
    r"-?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?"
    r"(?![0-9a-z_.+*/-])"
)
_COMPARISON_PATTERN = re.compile(
    rf"(?:(?P<symbol><=|>=|<|>|(?<![<>=])=)\s*(?P<number>{_NUMBER_PATTERN}))"
    rf"|(?:(?P<phrase>at least|at most|no more than|within)\s+"
    rf"(?P<phrase_number>{_NUMBER_PATTERN}))"
    rf"|(?:(?P<tolerance>±)\s*(?P<tolerance_number>{_NUMBER_PATTERN}))"
)


def _parse_numeric_criterion(
    value: str,
) -> tuple[str, Decimal, bool, str | None] | None:
    """Return one directly evaluable comparison from normalized criterion text."""
    text = _normalize_registry_text(value)
    polarity = re.match(
        r"^(?:pass(?:es)?|fail(?:s|ure)?|outlier)\s+(?:if|when)\b", text
    )
    if (polarity is None
            or re.search(r"(?:!|~|≈)\s*=|\bnot\b|\bapprox(?:imately)?\b", text)
            or "*" in text):
        return None
    matches = list(_COMPARISON_PATTERN.finditer(text))
    if len(matches) != 1:
        return None
    match = matches[0]
    operand_text = text[polarity.end():match.start()].strip()
    if operand_text not in {
        "", "|delta|", "abs(delta)", "absolute delta", "absolute value",
        "|oracle_measure|", "abs(oracle_measure)",
    }:
        return None
    operand_hint = (
        "delta" if "delta" in operand_text else
        "oracle_measure" if "oracle_measure" in operand_text else None
    )
    absolute = False
    if match.group("symbol") is not None:
        operator = match.group("symbol")
        raw_number = match.group("number")
        absolute = bool(
            re.search(r"\|[^|]+\|\s*(?:<=|>=|<|>|=)", text)
            or re.search(r"\babs(?:olute)?\b", text)
        )
    elif match.group("phrase") is not None:
        operator = {
            "at least": ">=",
            "at most": "<=",
            "no more than": "<=",
            "within": "<=",
        }[match.group("phrase")]
        raw_number = match.group("phrase_number")
        absolute = match.group("phrase") == "within"
    else:
        operator = "<="
        raw_number = match.group("tolerance_number")
        absolute = True
    threshold = _coerce_finite_decimal(raw_number, allow_string=True)
    if threshold is None:
        return None
    if absolute and threshold < 0:
        return None
    return operator, threshold, absolute, operand_hint


def _threshold_registry_cells(
    root: Path, section: int, label: str
) -> tuple[list[str], list[str]]:
    """Return headers and cells for one canonical threshold table row."""
    path = root / "ref" / "thresholds_and_standards.md"
    current_section: int | None = None
    matching_section_headings = 0
    section_lines: list[str] = []
    wanted = _normalize_registry_text(label)
    fence: tuple[str, int] | None = None
    in_html_comment = False
    for raw_line in path.read_text().splitlines():
        if fence is not None:
            fence_char, fence_length = fence
            if re.fullmatch(
                rf" {{0,3}}{re.escape(fence_char)}{{{fence_length},}}[ \t]*",
                raw_line,
            ):
                fence = None
            if current_section == section:
                section_lines.append("")
            continue

        # A threshold is authoritative only when it is rendered Markdown, not
        # an example/comment that merely contains table-looking source text.
        visible_parts: list[str] = []
        remainder = raw_line
        while remainder:
            if in_html_comment:
                _hidden, marker, remainder = remainder.partition("-->")
                if not marker:
                    remainder = ""
                    break
                in_html_comment = False
                continue
            before, marker, after = remainder.partition("<!--")
            visible_parts.append(before)
            if not marker:
                break
            in_html_comment = True
            remainder = after
        line = "".join(visible_parts)

        opening_fence = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if opening_fence is not None:
            marker = opening_fence.group(1)
            fence = (marker[0], len(marker))
            if current_section == section:
                section_lines.append("")
            continue
        if re.match(
            r"^ {0,3}(?:</?[a-z][a-z0-9-]*(?=[\t />]|$)|<\?|<!\[cdata\[|<![a-z])",
            line,
            flags=re.IGNORECASE,
        ):
            raise ConfigurationShapeError(
                "threshold registry cannot contain raw HTML block openers; "
                "authoritative threshold tables must be rendered Markdown"
            )
        if line.startswith("\t") or line.startswith("    "):
            if current_section == section:
                section_lines.append("")
            continue
        if re.match(r"^##\s+", line):
            heading = re.match(r"^##\s+(\d+)\.", line)
            current_section = int(heading.group(1)) if heading else None
            if current_section == section:
                matching_section_headings += 1
            continue
        if current_section != section:
            continue
        section_lines.append(line)

    if matching_section_headings != 1:
        raise ConfigurationShapeError(
            f"threshold registry section {section} must have exactly one canonical "
            f"numbered H2 heading, found {matching_section_headings}"
        )

    parsed: list[list[str] | None] = []
    for line in section_lines:
        if not line.lstrip().startswith("|"):
            parsed.append(None)
            continue
        row_text = line.strip()
        if row_text.startswith("|"):
            row_text = row_text[1:]
        if row_text.endswith("|"):
            row_text = row_text[:-1]
        cells = [
            cell.replace(r"\|", "|").strip()
            for cell in re.split(r"(?<!\\)\|", row_text)
        ]
        parsed.append(cells)

    def separator(cells: list[str] | None) -> bool:
        return bool(cells) and all(
            re.fullmatch(r":?-{3,}:?", cell.strip()) is not None
            for cell in cells
        )

    matches: list[tuple[list[str], list[str]]] = []
    headers: list[str] | None = None
    for index, cells in enumerate(parsed):
        if cells is None:
            headers = None
            continue
        if separator(cells):
            continue
        next_cells = parsed[index + 1] if index + 1 < len(parsed) else None
        if separator(next_cells):
            headers = cells
            continue
        if cells and _normalize_registry_text(cells[0]) == wanted:
            matches.append((headers or [], cells))
    if len(matches) != 1:
        raise ConfigurationShapeError(
            f"threshold registry section {section} row {label!r} must resolve exactly "
            f"once, found {len(matches)}"
        )
    header_cells, row_cells = matches[0]
    if not header_cells or len(header_cells) != len(row_cells):
        raise ConfigurationShapeError(
            f"threshold registry section {section} row {label!r} must belong to "
            "a table with a same-width header"
        )
    return (
        [_normalize_registry_text(cell) for cell in header_cells],
        [_normalize_registry_text(cell) for cell in row_cells],
    )


def _normalize_unit(value: Any) -> str:
    if value is None or (isinstance(value, str) and not value.strip()):
        return "unitless"
    if not isinstance(value, str):
        raise ConfigurationShapeError(
            f"measurement unit must be a string or null, got {type(value).__name__}"
        )
    normalized = re.sub(r"\s+", " ", value).strip().casefold()
    aliases = {
        "percent": "%",
        "percentage": "%",
        "percentage point": "pp",
        "percentage points": "pp",
        "ångström": "å",
        "ångströms": "å",
        "angstrom": "å",
        "angstroms": "å",
        "nanometer": "nm",
        "nanometers": "nm",
        "dimensionless": "unitless",
        "residue": "count",
        "residues": "count",
        "atom": "count",
        "atoms": "count",
        "degree": "°",
        "degrees": "°",
        "sigma": "σ",
    }
    return aliases.get(normalized, normalized)


def _criterion_metadata(value: str) -> tuple[str, tuple[str, ...]]:
    """Read the complete supported suffix of a machine-gradeable criterion."""
    text = _normalize_registry_text(value)
    matches = list(_COMPARISON_PATTERN.finditer(text))
    if len(matches) != 1:
        raise ConfigurationShapeError(
            "criterion must contain exactly one supported numeric comparison"
        )
    tail = text[matches[0].end():].strip()
    markers = (
        (r"^å²(?=\s|$|[,;\[])", "å²"),
        (r"^å(?=\s|$|[,;\[])", "å"),
        (r"^nm(?=\s|$|[,;\[])", "nm"),
        (r"^%(?=\s|$|[,;\[])", "%"),
        (r"^pp(?=\s|$|[,;\[])", "pp"),
        (r"^°(?=\s|$|[,;\[])", "°"),
        (r"^σ(?=\s|$|[,;\[])", "σ"),
        (r"^(?:residues?|atoms?|count)(?=\s|$|[,;\[])", "count"),
        (r"^fraction(?=\s|$|[,;\[])", "fraction"),
        (r"^unitless(?=\s|$|[,;\[])", "unitless"),
    )
    unit = "unitless"
    for pattern, unit in markers:
        match = re.search(pattern, tail)
        if match:
            tail = tail[match.end():].strip()
            break
    tail = tail.lstrip(";, ").strip()
    if not tail:
        return unit, ()
    required = re.fullmatch(r"\[requires:\s*([^\]]+)\]", tail)
    if required is None:
        raise ConfigurationShapeError(
            "criterion suffix contains unsupported prose or unit; use only a "
            "canonical unit and optional '[requires: id, ...]' annotation"
        )
    ids = tuple(part.strip() for part in required.group(1).split(","))
    if (not ids or any(not re.fullmatch(r"[a-z][a-z0-9_]*", item) for item in ids)
            or len(ids) != len(set(ids))):
        raise ConfigurationShapeError(
            "criterion '[requires: ...]' annotation must contain unique snake_case ids"
        )
    return unit, ids


def _criterion_truth_means_pass(value: str) -> bool:
    """Derive comparison polarity only from explicit authoritative wording."""
    text = _normalize_registry_text(value)
    marker = re.match(
        r"^(pass(?:es)?|fail(?:s|ure)?|outlier)\s+(?:if|when)\b", text
    )
    all_markers = re.findall(
        r"\b(pass(?:es)?|fail(?:s|ure)?|outlier)\s+(?:if|when)\b", text
    )
    if marker is None or len(all_markers) != 1:
        raise ConfigurationShapeError(
            "criterion cell must start with exactly one positive 'pass if/when' "
            "or 'fail/failure/outlier if/when' clause"
        )
    return marker.group(1).startswith("pass")


def _catalog_metric_units(root: Path) -> dict[str, str | None]:
    """Load the authoritative unit for every catalog metric id."""
    path = root / "ref" / "catalog.yaml"
    doc = _mapping(_strict_yaml_load(path.read_text()) or {}, "catalog root")
    rows = doc.get("metric_definitions")
    if not isinstance(rows, list):
        raise ConfigurationShapeError("catalog .metric_definitions must be a list")
    result: dict[str, str | None] = {}
    for index, row in enumerate(rows):
        location = f"catalog .metric_definitions[{index}]"
        item = _mapping(row, location)
        metric_id = item.get("id")
        if not isinstance(metric_id, str) or not metric_id.strip():
            raise ConfigurationShapeError(f"{location}.id must be a nonblank string")
        if metric_id in result:
            raise ConfigurationShapeError(
                f"catalog contains duplicate metric id {metric_id!r}"
            )
        unit = item.get("unit")
        if not isinstance(unit, str) or not unit.strip():
            result[metric_id] = None
        else:
            result[metric_id] = _normalize_unit(unit)
    return result


def _catalog_metric_tasks(root: Path) -> dict[str, set[str]]:
    """Load each metric's canonical task domain."""
    path = root / "ref" / "catalog.yaml"
    doc = _mapping(_strict_yaml_load(path.read_text()) or {}, "catalog root")
    rows = doc.get("metric_definitions")
    if not isinstance(rows, list):
        raise ConfigurationShapeError("catalog .metric_definitions must be a list")
    result: dict[str, set[str]] = {}
    for index, row in enumerate(rows):
        location = f"catalog .metric_definitions[{index}]"
        item = _mapping(row, location)
        metric_id = item.get("id")
        tasks = item.get("applicable_task_refs")
        if not isinstance(metric_id, str) or not metric_id.strip():
            raise ConfigurationShapeError(f"{location}.id must be a nonblank string")
        if (not isinstance(tasks, list) or not tasks
                or not all(isinstance(task, str) and task.strip() for task in tasks)):
            raise ConfigurationShapeError(
                f"{location}.applicable_task_refs must be a nonempty list of strings"
            )
        result[metric_id] = set(tasks)
    return result


def _catalog_task_contracts(root: Path) -> dict[str, dict[str, set[str]]]:
    """Load each task's canonical metric and tool membership."""
    path = root / "ref" / "catalog.yaml"
    doc = _mapping(_strict_yaml_load(path.read_text()) or {}, "catalog root")
    rows = doc.get("catalog_tasks")
    if not isinstance(rows, list):
        raise ConfigurationShapeError("catalog .catalog_tasks must be a list")
    result: dict[str, dict[str, set[str]]] = {}
    for index, row in enumerate(rows):
        location = f"catalog .catalog_tasks[{index}]"
        item = _mapping(row, location)
        task_id = item.get("id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise ConfigurationShapeError(f"{location}.id must be a nonblank string")
        if task_id in result:
            raise ConfigurationShapeError(f"catalog contains duplicate task id {task_id!r}")
        metrics = item.get("metric_definition_refs")
        oracle_tools = item.get("oracle_tool_refs")
        phenix_tools = item.get("phenix_tool_refs")
        for field, values in (
            ("metric_definition_refs", metrics),
            ("oracle_tool_refs", oracle_tools),
            ("phenix_tool_refs", phenix_tools),
        ):
            if (not isinstance(values, list)
                    or not all(isinstance(value, str) and value.strip() for value in values)):
                raise ConfigurationShapeError(
                    f"{location}.{field} must be a list of nonblank strings"
                )
        result[task_id] = {
            "metrics": set(metrics),
            "tools": set(oracle_tools) | set(phenix_tools),
        }
    return result


def _catalog_tool_tasks(root: Path) -> dict[str, set[str]]:
    path = root / "ref" / "catalog.yaml"
    doc = _mapping(_strict_yaml_load(path.read_text()) or {}, "catalog root")
    rows = doc.get("tools")
    if not isinstance(rows, list):
        raise ConfigurationShapeError("catalog .tools must be a list")
    result: dict[str, set[str]] = {}
    for index, row in enumerate(rows):
        location = f"catalog .tools[{index}]"
        item = _mapping(row, location)
        tool_id = item.get("id")
        tasks = item.get("catalog_tasks_served")
        if not isinstance(tool_id, str) or not tool_id.strip():
            raise ConfigurationShapeError(f"{location}.id must be a nonblank string")
        if (not isinstance(tasks, list)
                or not all(isinstance(task, str) and task.strip() for task in tasks)):
            raise ConfigurationShapeError(
                f"{location}.catalog_tasks_served must be a list of strings"
            )
        if tool_id in result:
            raise ConfigurationShapeError(
                f"catalog contains duplicate tool id {tool_id!r}"
            )
        result[tool_id] = set(tasks)
    return result


def _catalog_tool_families(root: Path) -> dict[str, str]:
    """Load canonical tool-family assignments used by binding applicability."""
    path = root / "ref" / "catalog.yaml"
    doc = _mapping(_strict_yaml_load(path.read_text()) or {}, "catalog root")
    rows = doc.get("tools")
    if not isinstance(rows, list):
        raise ConfigurationShapeError("catalog .tools must be a list")
    result: dict[str, str] = {}
    for index, row in enumerate(rows):
        location = f"catalog .tools[{index}]"
        item = _mapping(row, location)
        tool_id = item.get("id")
        family = item.get("family")
        if not isinstance(tool_id, str) or not tool_id.strip():
            raise ConfigurationShapeError(f"{location}.id must be a nonblank string")
        if not isinstance(family, str) or family not in {"cctbx", "non_cctbx"}:
            raise ConfigurationShapeError(
                f"{location}.family must be 'cctbx' or 'non_cctbx'"
            )
        if tool_id in result:
            raise ConfigurationShapeError(
                f"catalog contains duplicate tool id {tool_id!r}"
            )
        result[tool_id] = family
    return result


def _looks_gradeable_criterion(value: str) -> bool:
    """Accept only one numeric comparison the guard can actually evaluate."""
    return _parse_numeric_criterion(value) is not None


def _iso_date(value: Any, location: str) -> date:
    """Parse a date-only YAML scalar without accepting datetimes or booleans."""
    if isinstance(value, datetime) or isinstance(value, bool):
        raise ConfigurationShapeError(f"{location} must be an ISO date, not a datetime")
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ConfigurationShapeError(f"{location} must be an ISO YYYY-MM-DD date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ConfigurationShapeError(
            f"{location} must be an ISO YYYY-MM-DD date"
        ) from exc
    if parsed.isoformat() != value:
        raise ConfigurationShapeError(f"{location} must use canonical YYYY-MM-DD form")
    return parsed


def pass_criterion_bindings(root: Path) -> dict[str, dict[str, Any]]:
    """Load contextual bindings without creating a second threshold source."""
    path = root / "ref" / "structural_criteria.yaml"
    doc = _mapping(_strict_yaml_load(path.read_text()) or {}, "criterion bindings root")
    rows = doc.get("pass_criterion_bindings")
    if not isinstance(rows, list):
        raise ConfigurationShapeError(
            "criterion bindings .pass_criterion_bindings must be a list"
        )
    result: dict[str, dict[str, Any]] = {}
    semantic_payloads: dict[str, str] = {}
    metric_units = _catalog_metric_units(root)
    metric_tasks = _catalog_metric_tasks(root)
    catalog_tasks = _catalog_task_contracts(root)
    tool_families = _catalog_tool_families(root)
    tool_tasks = _catalog_tool_tasks(root)
    allowed_vocabularies = {
        "stages": schema_enum_values(root, "Stage"),
        "scopes": schema_enum_values(root, "MeasurementScope"),
        "oracle_families": schema_enum_values(root, "ToolFamily"),
    }
    for index, row in enumerate(rows):
        location = f"criterion bindings .pass_criterion_bindings[{index}]"
        item = dict(_mapping(row, location))
        allowed_fields = {
            "id", "metric_definition_ref", "threshold_registry_section",
            "threshold_registry_row", "threshold_registry_column",
            "comparison_operand", "comparison_transform", "comparison_unit",
            "effective_from", "effective_until", "supersedes_ref", "applicability",
        }
        unexpected = sorted(set(item) - allowed_fields)
        if unexpected:
            raise ConfigurationShapeError(
                f"{location} has unsupported field(s): {', '.join(unexpected)}"
            )
        for field in (
            "id", "metric_definition_ref", "threshold_registry_row",
            "comparison_operand", "comparison_transform", "comparison_unit",
        ):
            value = item.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ConfigurationShapeError(f"{location}.{field} must be a nonblank string")
        effective_from = _iso_date(
            item.get("effective_from"), f"{location}.effective_from"
        )
        effective_until_raw = item.get("effective_until")
        effective_until = (
            _iso_date(effective_until_raw, f"{location}.effective_until")
            if effective_until_raw is not None else None
        )
        if effective_until is not None and effective_until < effective_from:
            raise ConfigurationShapeError(
                f"{location}.effective_until precedes effective_from"
            )
        supersedes_ref = item.get("supersedes_ref")
        if supersedes_ref is not None and (
            not isinstance(supersedes_ref, str) or not supersedes_ref.strip()
        ):
            raise ConfigurationShapeError(
                f"{location}.supersedes_ref must be a nonblank string when present"
            )
        if item["comparison_operand"] not in {"oracle_measure", "delta"}:
            raise ConfigurationShapeError(
                f"{location}.comparison_operand must be 'oracle_measure' or 'delta'"
            )
        if item["comparison_transform"] not in {"identity", "absolute"}:
            raise ConfigurationShapeError(
                f"{location}.comparison_transform must be 'identity' or 'absolute'"
            )
        metric_id = item["metric_definition_ref"]
        if metric_id not in metric_units:
            raise ConfigurationShapeError(
                f"{location}.metric_definition_ref {metric_id!r} is absent from "
                "ref/catalog.yaml metric_definitions"
            )
        if metric_units[metric_id] is None:
            raise ConfigurationShapeError(
                f"catalog metric {metric_id!r} must explicitly declare its unit; "
                "use 'unitless' for a dimensionless value before binding a verdict"
            )
        comparison_unit = _normalize_unit(item["comparison_unit"])
        if comparison_unit != metric_units[metric_id]:
            raise ConfigurationShapeError(
                f"{location}.comparison_unit {item['comparison_unit']!r} does not "
                f"match catalog metric {metric_id!r} unit {metric_units[metric_id]!r}"
            )
        section = item.get("threshold_registry_section")
        if not isinstance(section, int) or isinstance(section, bool) or section < 1:
            raise ConfigurationShapeError(
                f"{location}.threshold_registry_section must be a positive integer"
            )
        column = item.get("threshold_registry_column")
        if not isinstance(column, int) or isinstance(column, bool) or column < 2:
            raise ConfigurationShapeError(
                f"{location}.threshold_registry_column must be an integer >= 2"
            )
        applicability = _mapping(item.get("applicability"), f"{location}.applicability")
        allowed_applicability = {
            "catalog_task_refs", "stages", "scopes", "oracle_tool_refs",
            "oracle_families", "required_precondition_ids", "requires_agent_claim",
        }
        unexpected = sorted(set(applicability) - allowed_applicability)
        if unexpected:
            raise ConfigurationShapeError(
                f"{location}.applicability has unsupported field(s): "
                + ", ".join(unexpected)
            )
        for field in (
            "catalog_task_refs", "stages", "scopes", "oracle_tool_refs",
            "oracle_families",
        ):
            values = applicability.get(field)
            if (not isinstance(values, list) or not values
                    or not all(isinstance(value, str) and value.strip() for value in values)):
                raise ConfigurationShapeError(
                    f"{location}.applicability.{field} must be a nonempty list of "
                    "nonblank strings"
                )
            if len(values) != len(set(values)):
                raise ConfigurationShapeError(
                    f"{location}.applicability.{field} contains duplicates"
                )
            unsupported = sorted(set(values) - allowed_vocabularies.get(field, set()))
            if field in allowed_vocabularies and unsupported:
                raise ConfigurationShapeError(
                    f"{location}.applicability.{field} contains value(s) absent "
                    "from the Eval schema: " + ", ".join(unsupported)
                )
        required_preconditions = applicability.get("required_precondition_ids")
        if (not isinstance(required_preconditions, list)
                or not all(
                    isinstance(value, str) and value.strip()
                    for value in required_preconditions
                )):
            raise ConfigurationShapeError(
                f"{location}.applicability.required_precondition_ids must be a "
                "list of nonblank strings"
            )
        if len(required_preconditions) != len(set(required_preconditions)):
            raise ConfigurationShapeError(
                f"{location}.applicability.required_precondition_ids contains duplicates"
            )
        unsupported_tasks = sorted(
            set(applicability["catalog_task_refs"]) - metric_tasks[metric_id]
        )
        if unsupported_tasks:
            raise ConfigurationShapeError(
                f"{location}.applicability.catalog_task_refs contains task(s) not "
                f"declared for metric {metric_id!r}: " + ", ".join(unsupported_tasks)
            )
        unknown_tasks = sorted(
            set(applicability["catalog_task_refs"]) - set(catalog_tasks)
        )
        if unknown_tasks:
            raise ConfigurationShapeError(
                f"{location}.applicability.catalog_task_refs contains unknown "
                "catalog task(s): " + ", ".join(unknown_tasks)
            )
        for task_id in applicability["catalog_task_refs"]:
            task_contract = catalog_tasks[task_id]
            if metric_id not in task_contract["metrics"]:
                raise ConfigurationShapeError(
                    f"{location}: catalog task {task_id!r} does not list metric "
                    f"{metric_id!r} in metric_definition_refs"
                )
            absent_tools = sorted(
                set(applicability["oracle_tool_refs"]) - task_contract["tools"]
            )
            if absent_tools:
                raise ConfigurationShapeError(
                    f"{location}: catalog task {task_id!r} does not list bound "
                    "tool(s) in phenix_tool_refs/oracle_tool_refs: "
                    + ", ".join(absent_tools)
                )
        if not isinstance(applicability.get("requires_agent_claim"), bool):
            raise ConfigurationShapeError(
                f"{location}.applicability.requires_agent_claim must be a boolean"
            )
        missing_tools = sorted(
            set(applicability["oracle_tool_refs"]) - set(tool_families)
        )
        if missing_tools:
            raise ConfigurationShapeError(
                f"{location}.applicability.oracle_tool_refs contains tool(s) absent "
                "from ref/catalog.yaml: " + ", ".join(missing_tools)
            )
        for tool_id in applicability["oracle_tool_refs"]:
            unsupported_for_tool = sorted(
                set(applicability["catalog_task_refs"]) - tool_tasks[tool_id]
            )
            if unsupported_for_tool:
                raise ConfigurationShapeError(
                    f"{location}.applicability oracle tool {tool_id!r} does not "
                    "declare service for task(s): " + ", ".join(unsupported_for_tool)
                )
        bound_tool_families = {
            tool_families[tool_id]
            for tool_id in applicability["oracle_tool_refs"]
        }
        if set(applicability["oracle_families"]) != bound_tool_families:
            raise ConfigurationShapeError(
                f"{location}.applicability.oracle_families must equal the canonical "
                f"families of oracle_tool_refs: {sorted(bound_tool_families)!r}"
            )
        criterion_id = item["id"]
        if criterion_id in result:
            raise ConfigurationShapeError(
                f"criterion bindings contains duplicate id {criterion_id!r}"
            )
        registry_headers, registry_cells = _threshold_registry_cells(
            root, section, item["threshold_registry_row"]
        )
        allowed_provenance = {
            "schema", "molprobity", "literature", "catalog", "template",
            "calibration", "benchmark",
        }
        provenance_columns = [
            index for index, header in enumerate(registry_headers)
            if header.casefold() in {"provenance", "source"}
        ]
        if len(provenance_columns) != 1:
            raise ConfigurationShapeError(
                f"{location} threshold registry table must have exactly one "
                "Provenance or Source column"
            )
        provenance_cell = registry_cells[provenance_columns[0]]
        provenance_tags = {
            tag.strip().casefold()
            for tag in re.findall(r"\[([^\]]+)\]", provenance_cell)
        } & allowed_provenance
        if not provenance_tags:
            raise ConfigurationShapeError(
                f"{location} threshold registry Provenance/Source cell must carry "
                "an approved tag such as [benchmark] or [literature]"
            )
        if column > len(registry_cells):
            raise ConfigurationShapeError(
                f"{location}.threshold_registry_column {column} is outside the "
                f"{len(registry_cells)}-cell registry row"
            )
        if column - 1 == provenance_columns[0]:
            raise ConfigurationShapeError(
                f"{location}.threshold_registry_column cannot select the dedicated "
                "Provenance/Source cell"
            )
        extracted = registry_cells[column - 1]
        if not _looks_gradeable_criterion(extracted):
            raise ConfigurationShapeError(
                f"{location}.threshold_registry_column selects non-gradeable "
                f"text {extracted!r}"
            )
        operator, threshold, source_is_absolute, source_operand_hint = (
            _parse_numeric_criterion(extracted) or (None, None, False, None)
        )
        if (source_operand_hint is not None
                and source_operand_hint != item["comparison_operand"]):
            raise ConfigurationShapeError(
                f"{location}.comparison_operand {item['comparison_operand']!r} "
                f"conflicts with operand named in criterion {extracted!r}"
            )
        registry_unit, registry_preconditions = _criterion_metadata(extracted)
        if registry_unit != comparison_unit:
            raise ConfigurationShapeError(
                f"{location}.comparison_unit {item['comparison_unit']!r} does not "
                f"match registry criterion unit {registry_unit!r} in {extracted!r}"
            )
        if set(registry_preconditions) != set(required_preconditions):
            raise ConfigurationShapeError(
                f"{location}.applicability.required_precondition_ids must equal "
                f"the criterion cell's [requires: ...] ids "
                f"{list(registry_preconditions)!r}"
            )
        truth_means_pass = _criterion_truth_means_pass(extracted)
        if source_is_absolute and item["comparison_transform"] != "absolute":
            raise ConfigurationShapeError(
                f"{location}.comparison_transform must be 'absolute' for a "
                "criterion expressed as an absolute value, tolerance, or 'within'"
            )
        if not source_is_absolute and item["comparison_transform"] == "absolute":
            raise ConfigurationShapeError(
                f"{location}.comparison_transform cannot be 'absolute' because "
                "the extracted criterion does not express absolute-value semantics"
            )
        item["_threshold_criterion_text"] = extracted
        item["comparison_unit"] = comparison_unit
        item["_criterion_operator"] = operator
        item["_criterion_threshold"] = threshold
        item["_criterion_truth_means_pass"] = truth_means_pass
        item["_effective_from"] = effective_from
        item["_effective_until"] = effective_until
        item["_oracle_tool_families"] = {
            tool_id: tool_families[tool_id]
            for tool_id in applicability["oracle_tool_refs"]
        }

        # List order is not scientific semantics. Resolve the authoritative
        # cell first, then reject aliases over the canonical meaning.
        semantic_payload = _canonical_digest({
            "metric_definition_ref": item["metric_definition_ref"],
            "threshold_registry_section": section,
            "threshold_registry_row": _normalize_registry_text(
                item["threshold_registry_row"]
            ),
            "threshold_registry_column": column,
            "threshold_criterion_text": extracted,
            "comparison_operand": item["comparison_operand"],
            "comparison_transform": item["comparison_transform"],
            "comparison_unit": comparison_unit,
            "criterion_truth_means_pass": truth_means_pass,
            "applicability": {
                field: sorted(applicability[field])
                for field in (
                    "catalog_task_refs", "stages", "scopes", "oracle_tool_refs",
                    "oracle_families", "required_precondition_ids",
                )
            } | {
                "requires_agent_claim": applicability["requires_agent_claim"]
            },
        })
        if semantic_payload in semantic_payloads:
            raise ConfigurationShapeError(
                f"criterion bindings {semantic_payloads[semantic_payload]!r} and "
                f"{criterion_id!r} have duplicate semantics"
            )
        semantic_payloads[semantic_payload] = criterion_id
        result[criterion_id] = item
    for criterion_id, item in result.items():
        predecessor_id = item.get("supersedes_ref")
        if predecessor_id is None:
            continue
        if predecessor_id == criterion_id or predecessor_id not in result:
            raise ConfigurationShapeError(
                f"criterion binding {criterion_id!r}.supersedes_ref must name a "
                "different binding in the same registry"
            )
        predecessor = result[predecessor_id]
        if predecessor["metric_definition_ref"] != item["metric_definition_ref"]:
            raise ConfigurationShapeError(
                f"criterion binding {criterion_id!r} cannot supersede "
                f"{predecessor_id!r} for a different metric"
            )
        context_fields = (
            "metric_definition_ref", "comparison_operand",
            "comparison_transform", "comparison_unit",
        )
        same_context = all(
            predecessor[field] == item[field] for field in context_fields
        ) and all(
            set(predecessor["applicability"][field])
            == set(item["applicability"][field])
            for field in (
                "catalog_task_refs", "stages", "scopes", "oracle_tool_refs",
                "oracle_families", "required_precondition_ids",
            )
        ) and (
            predecessor["applicability"]["requires_agent_claim"]
            == item["applicability"]["requires_agent_claim"]
        )
        if not same_context:
            raise ConfigurationShapeError(
                f"criterion binding {criterion_id!r} may supersede only the same "
                f"operand and scientific applicability context as {predecessor_id!r}"
            )
        retired = predecessor["_effective_until"]
        if retired is None or item["_effective_from"] <= retired:
            raise ConfigurationShapeError(
                f"criterion binding {criterion_id!r} must start after the retired "
                f"effective_until of {predecessor_id!r}"
            )
    binding_items = list(result.items())
    dimensions = (
        "catalog_task_refs", "stages", "scopes", "oracle_tool_refs",
        "oracle_families",
    )
    for left_index, (left_id, left) in enumerate(binding_items):
        for right_id, right in binding_items[left_index + 1:]:
            same_metric = (
                left["metric_definition_ref"] == right["metric_definition_ref"]
            )
            contexts_intersect = same_metric and all(
                set(left["applicability"][field])
                & set(right["applicability"][field])
                for field in dimensions
            )
            exact_context = all(
                left[field] == right[field]
                for field in (
                    "metric_definition_ref", "comparison_operand",
                    "comparison_transform", "comparison_unit",
                )
            ) and all(
                set(left["applicability"][field])
                == set(right["applicability"][field])
                for field in (
                    "catalog_task_refs", "stages", "scopes", "oracle_tool_refs",
                    "oracle_families", "required_precondition_ids",
                )
            ) and (
                left["applicability"]["requires_agent_claim"]
                == right["applicability"]["requires_agent_claim"]
            )
            left_end = left["_effective_until"] or date.max
            right_end = right["_effective_until"] or date.max
            dates_intersect = (
                left["_effective_from"] <= right_end
                and right["_effective_from"] <= left_end
            )
            if contexts_intersect and dates_intersect:
                raise ConfigurationShapeError(
                    f"criterion bindings {left_id!r} and {right_id!r} have "
                    "overlapping effective dates and grading context; split the "
                    "applicability or retire/supersede the earlier binding"
                )
            if contexts_intersect and not dates_intersect and not exact_context:
                raise ConfigurationShapeError(
                    f"criterion bindings {left_id!r} and {right_id!r} change a "
                    "partly overlapping grading context across time. Bindings must "
                    "use atomic, identical applicability sets before they can form "
                    "an auditable supersession chain"
                )
    chains: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for criterion_id, item in binding_items:
        context_key = _canonical_digest({
            "metric_definition_ref": item["metric_definition_ref"],
            "comparison_operand": item["comparison_operand"],
            "comparison_transform": item["comparison_transform"],
            "comparison_unit": item["comparison_unit"],
            "applicability": {
                field: sorted(item["applicability"][field])
                for field in (
                    "catalog_task_refs", "stages", "scopes", "oracle_tool_refs",
                    "oracle_families", "required_precondition_ids",
                )
            } | {
                "requires_agent_claim":
                    item["applicability"]["requires_agent_claim"]
            },
        })
        chains.setdefault(context_key, []).append((criterion_id, item))
    for versions in chains.values():
        versions.sort(key=lambda pair: (pair[1]["_effective_from"], pair[0]))
        for (prior_id, _prior), (later_id, later) in zip(versions, versions[1:]):
            if later.get("supersedes_ref") != prior_id:
                raise ConfigurationShapeError(
                    f"criterion binding {later_id!r} must supersede immediately "
                    f"preceding same-context version {prior_id!r}; version lineage "
                    "must be a single append-only chain"
                )
    return result


def raw_criterion(row: dict[str, Any]) -> str:
    raw = row.get("pass_criterion")
    return raw.strip() if isinstance(raw, str) else ""


def criterion_of(row: dict[str, Any]) -> str:
    text = raw_criterion(row)
    return "" if text.lower() in PLACEHOLDER_CRITERIA else text


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        default=_json_default,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _json_default(value: Any) -> dict[str, str]:
    """Represent YAML-native scalars without letting diagnostics traceback."""
    if isinstance(value, (date, datetime)):
        return {"__yaml_scalar_type__": type(value).__name__, "value": value.isoformat()}
    return {"__python_type__": type(value).__name__, "value": repr(value)}


def _coerce_finite_decimal(
    value: Any, *, allow_string: bool = False
) -> Decimal | None:
    """Preserve numeric meaning without leaking overflow/type exceptions."""
    allowed_types = (int, float, str) if allow_string else (int, float)
    if not isinstance(value, allowed_types) or isinstance(value, bool):
        return None
    try:
        converted = Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError):
        return None
    if not converted.is_finite() or abs(converted) > Decimal(str(sys.float_info.max)):
        return None
    return converted


def _temporal_signature(field: str, value: Any) -> dict[str, str] | None:
    """Canonicalize only schema-declared R5 date/datetime slots."""
    if field == "as_of_date":
        parsed_date: date | None = None
        if isinstance(value, datetime):
            if value.timetz().replace(tzinfo=None) == time.min:
                parsed_date = value.date()
        elif isinstance(value, date):
            parsed_date = value
        elif isinstance(value, str):
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                try:
                    parsed_date = date.fromisoformat(value)
                except ValueError:
                    parsed_date = None
            elif re.match(r"^\d{4}-\d{2}-\d{2}[T ]", value):
                try:
                    parsed_datetime = datetime.fromisoformat(value)
                except ValueError:
                    parsed_datetime = None
                if (parsed_datetime is not None
                        and parsed_datetime.timetz().replace(tzinfo=None) == time.min):
                    parsed_date = parsed_datetime.date()
        if parsed_date is not None:
            return {"__date__": parsed_date.isoformat()}
        return None

    if field not in {"run_at", "effective_at"}:
        return None
    parsed_datetime: datetime | None = None
    if isinstance(value, datetime):
        parsed_datetime = value
    elif isinstance(value, date):
        parsed_datetime = datetime.combine(value, time.min)
    elif isinstance(value, str):
        if not re.match(r"^\d{4}-\d{2}-\d{2}(?:[T ]|$)", value):
            return None
        try:
            parsed_datetime = datetime.fromisoformat(value)
        except ValueError:
            return None
    if parsed_datetime is None:
        return None
    if parsed_datetime.tzinfo is not None:
        parsed_datetime = parsed_datetime.astimezone(timezone.utc)
    return {"__datetime__": parsed_datetime.isoformat()}


def _signature_value(
    field: str, value: Any, stack: set[int] | None = None
) -> Any:
    """Canonicalize schema-equivalent scientific context for R5 comparison."""
    if stack is None:
        stack = set()
    temporal = _temporal_signature(field, value)
    if temporal is not None:
        return temporal
    is_container = isinstance(value, (dict, list))
    object_id = id(value)
    if is_container and object_id in stack:
        return {"__cyclic_yaml_alias__": True}
    if is_container:
        stack.add(object_id)
    if field == "pass_criterion" and isinstance(value, str):
        return _normalize_registry_text(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if _coerce_finite_decimal(value) is not None:
            normalized = Decimal(str(value)).normalize()
            if normalized == 0:
                normalized = Decimal(0)
            return {"__numeric__": str(normalized)}
        return {"__nonfinite_numeric__": repr(value)}
    if isinstance(value, dict):
        normalized_mapping: dict[str, Any] = {}
        for key, child in sorted(value.items(), key=lambda item: repr(item[0])):
            if key == "notes" or child is None or child == []:
                continue
            if (field in {"agent_claim", "oracle_measure", "delta"}
                    and key == "unit"):
                continue
            safe_key = (
                key if isinstance(key, str)
                else f"__non_string_key__:{type(key).__name__}:{key!r}"
            )
            normalized_mapping[safe_key] = _signature_value(str(key), child, stack)
        if (field in {"agent_claim", "oracle_measure", "delta"}
                and value.get("value_numeric") is not None):
            try:
                normalized_mapping["unit"] = _normalize_unit(value.get("unit"))
            except ConfigurationShapeError:
                normalized_mapping["unit"] = {
                    "__invalid_unit__": repr(value.get("unit"))
                }
        stack.remove(object_id)
        return normalized_mapping
    if isinstance(value, list):
        normalized = [_signature_value("", child, stack) for child in value]
        stack.remove(object_id)
        if field not in SET_LIKE_SIGNATURE_FIELDS:
            return normalized
        keyed = {
            json.dumps(
                item, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                default=_json_default,
            ): item
            for item in normalized
        }
        return [keyed[key] for key in sorted(keyed)]
    return value


def _mapping_key_violations(
    value: Any, location: str, stack: set[int] | None = None
) -> list[str]:
    """Report non-string YAML mapping keys recursively without throwing."""
    if stack is None:
        stack = set()
    failures: list[str] = []
    if isinstance(value, (dict, list)):
        object_id = id(value)
        if object_id in stack:
            return [f"{location} contains a cyclic YAML alias"]
        stack.add(object_id)
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                failures.append(
                    f"{location} has non-string mapping key "
                    f"{type(key).__name__} {key!r}"
                )
            child_location = f"{location}.{key}" if isinstance(key, str) else location
            failures.extend(_mapping_key_violations(child, child_location, stack))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            failures.extend(
                _mapping_key_violations(child, f"{location}[{index}]", stack)
            )
    if isinstance(value, (dict, list)):
        stack.remove(id(value))
    return failures


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _typed_value_kind(carrier: Any) -> str | None:
    """Classify an exactly-one typed carrier, rejecting mixed/invalid shapes."""
    if not isinstance(carrier, dict):
        return None
    carrier_keys = [
        key for key in ("value_numeric", "value_text", "is_not_applicable")
        if key in carrier
    ]
    if len(carrier_keys) != 1:
        return None
    carrier_key = carrier_keys[0]
    if carrier_key == "value_numeric":
        return (
            "numeric"
            if _coerce_finite_decimal(carrier.get("value_numeric")) is not None
            else None
        )
    if carrier_key == "value_text":
        text = carrier.get("value_text")
        return "text" if isinstance(text, str) and text.strip() else None
    return "not_applicable" if carrier.get("is_not_applicable") is True else None


def _asserted_claim(row: dict[str, Any]) -> bool:
    claim = row.get("agent_claim")
    kind = _typed_value_kind(claim)
    if kind not in {"numeric", "text"}:
        return False
    if kind == "numeric":
        return True
    assert isinstance(claim, dict)
    text = claim.get("value_text")
    if not isinstance(text, str) or not text.strip():
        return False
    normalized_text = re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()
    return normalized_text not in NORMALIZED_PLACEHOLDER_CLAIMS


def _numeric_agent_oracle_relation(row: dict[str, Any]) -> bool | None:
    """Return numeric equality, or None when values are not comparable."""
    claim = row.get("agent_claim")
    oracle = row.get("oracle_measure")
    if not isinstance(claim, dict) or not isinstance(oracle, dict):
        return None
    if _typed_value_kind(claim) != "numeric" or _typed_value_kind(oracle) != "numeric":
        return None
    claim_numeric = claim.get("value_numeric")
    oracle_numeric = oracle.get("value_numeric")
    if claim_numeric is None or oracle_numeric is None:
        return None
    claim_value = _coerce_finite_decimal(claim_numeric)
    oracle_value = _coerce_finite_decimal(oracle_numeric)
    if claim_value is None or oracle_value is None:
        return None
    try:
        if _normalize_unit(claim.get("unit")) != _normalize_unit(oracle.get("unit")):
            return None
    except ConfigurationShapeError:
        return None
    return claim_value == oracle_value


def _agent_oracle_disagree(row: dict[str, Any]) -> bool:
    """Require a finite, typed, unit-compatible numeric inequality."""
    return _numeric_agent_oracle_relation(row) is False


def _criterion_holds(value: Decimal, binding: dict[str, Any]) -> bool:
    """Evaluate the registry-extracted comparison against one oracle value."""
    if binding["comparison_transform"] == "absolute":
        value = abs(value)
    operator = binding["_criterion_operator"]
    threshold = binding["_criterion_threshold"]
    if operator == "<":
        return value < threshold
    if operator == "<=":
        return value <= threshold
    if operator == ">":
        return value > threshold
    if operator == ">=":
        return value >= threshold
    if operator == "=":
        return value == threshold
    raise AssertionError(f"unsupported normalized criterion operator {operator!r}")


def _finite_typed_value(carrier: Any, expected_unit: str) -> Decimal | None:
    if not isinstance(carrier, dict) or _typed_value_kind(carrier) != "numeric":
        return None
    value = carrier.get("value_numeric")
    converted = _coerce_finite_decimal(value)
    if converted is None:
        return None
    try:
        carrier_unit = _normalize_unit(carrier.get("unit"))
    except ConfigurationShapeError:
        return None
    if carrier_unit != _normalize_unit(expected_unit):
        return None
    return converted


def _finite_criterion_operand(
    row: dict[str, Any], binding: dict[str, Any]
) -> Decimal | None:
    unit = binding["comparison_unit"]
    value = _finite_typed_value(row.get(binding["comparison_operand"]), unit)
    if value is None or binding["comparison_operand"] != "delta":
        return value
    if row.get("delta_from_measurement_ref") is not None:
        # Cross-row arithmetic belongs to referential integrity. A verdict must
        # instead grade a dedicated derived metric's oracle_measure so this
        # standalone guard never trusts an unresolved reference delta.
        return None
    agent = _finite_typed_value(row.get("agent_claim"), unit)
    oracle = _finite_typed_value(row.get("oracle_measure"), unit)
    if agent is None or oracle is None:
        return None
    expected_delta = oracle - agent
    if value != expected_delta:
        return None
    return value


def _binding_mismatches(
    row: dict[str, Any], binding: dict[str, Any], run_date: date | None,
    *, allow_inapplicable: bool = False,
) -> list[str]:
    """Return structured applicability fields that reject this measurement."""
    mismatches: list[str] = []
    metric = row.get("metric_definition_ref")
    if binding.get("metric_definition_ref") != metric:
        mismatches.append(
            f"metric_definition_ref={metric!r} (binding allows only "
            f"{binding.get('metric_definition_ref')!r})"
        )
    applicability = binding["applicability"]
    if run_date is None:
        mismatches.append("EvaluationRun.run_date is not a valid date")
    elif (run_date < binding["_effective_from"]
          or (binding["_effective_until"] is not None
              and run_date > binding["_effective_until"])):
        mismatches.append(
            f"run_date={run_date.isoformat()!r} is outside binding effective "
            f"interval {binding['_effective_from'].isoformat()}.."
            f"{binding['_effective_until'].isoformat() if binding['_effective_until'] else 'open'}"
        )
    fields = {
        "catalog_task_refs": "catalog_task_ref",
        "stages": "stage",
        "scopes": "scope",
        "oracle_tool_refs": "oracle_tool_ref",
        "oracle_families": "oracle_family",
    }
    for allowed_field, row_field in fields.items():
        observed = row.get(row_field)
        allowed = applicability[allowed_field]
        if not isinstance(observed, str) or observed not in allowed:
            mismatches.append(f"{row_field}={observed!r} (allowed: {allowed!r})")
    observed_tool = row.get("oracle_tool_ref")
    observed_family = row.get("oracle_family")
    canonical_family = (
        binding["_oracle_tool_families"].get(observed_tool)
        if isinstance(observed_tool, str) else None
    )
    if canonical_family is not None and observed_family != canonical_family:
        mismatches.append(
            f"oracle_tool_ref={observed_tool!r} has canonical family "
            f"{canonical_family!r}, not {observed_family!r}"
        )
    if (not allow_inapplicable and applicability["requires_agent_claim"]
            and not _asserted_claim(row)):
        mismatches.append("binding requires an asserted agent_claim")

    preconditions = row.get("criterion_preconditions", [])
    if not isinstance(preconditions, list):
        mismatches.append("criterion_preconditions must be a list")
        return mismatches
    by_id: dict[str, list[dict[str, Any]]] = {}
    for index, precondition in enumerate(preconditions):
        if not isinstance(precondition, dict):
            mismatches.append(
                f"criterion_preconditions[{index}] must be a mapping"
            )
            continue
        precondition_id = precondition.get("id")
        if not isinstance(precondition_id, str) or not precondition_id.strip():
            mismatches.append(
                f"criterion_preconditions[{index}].id must be a nonblank string"
            )
            continue
        by_id.setdefault(precondition_id, []).append(precondition)
        status = precondition.get("status")
        evidence = precondition.get("evidence_refs")
        allowed_statuses = (
            {"satisfied", "void", "unknown"}
            if allow_inapplicable else {"satisfied"}
        )
        if not isinstance(status, str) or status not in allowed_statuses:
            mismatches.append(
                f"criterion precondition {precondition_id!r} has status {status!r}, "
                f"not one of {sorted(allowed_statuses)!r}"
            )
        if (not isinstance(evidence, list) or not evidence
                or not all(isinstance(ref, str) and ref.strip() for ref in evidence)):
            mismatches.append(
                f"criterion precondition {precondition_id!r} requires retained evidence_refs"
            )
    for precondition_id, values in sorted(by_id.items()):
        if len(values) > 1:
            mismatches.append(
                f"criterion precondition {precondition_id!r} appears {len(values)} times"
            )
    for required_id in applicability["required_precondition_ids"]:
        if required_id not in by_id:
            mismatches.append(
                f"required criterion precondition {required_id!r} is missing"
            )
    unexpected_ids = sorted(
        set(by_id) - set(applicability["required_precondition_ids"])
    )
    if unexpected_ids:
        mismatches.append(
            "criterion_preconditions contains id(s) not required by binding: "
            + ", ".join(unexpected_ids)
        )
    if allow_inapplicable and not any(
        isinstance(values[0].get("status"), str)
        and values[0].get("status") in {"void", "unknown"}
        for precondition_id, values in by_id.items()
        if precondition_id in applicability["required_precondition_ids"] and values
    ):
        mismatches.append(
            "criterion_inapplicable requires at least one required precondition "
            "with status 'void' or 'unknown'"
        )
    return mismatches


def _legacy_row_exception(
    rule: str,
    relative_path: str,
    run_id: str,
    row: dict[str, Any],
    seen: set[tuple[str, str, str, str]],
) -> bool:
    row_id = row.get("id")
    if not isinstance(row_id, str):
        return False
    key = (rule, relative_path, run_id, row_id)
    expected = LEGACY_ROW_EXCEPTIONS.get(key)
    if expected is None or _canonical_digest(row) != expected or key in seen:
        return False
    seen.add(key)
    return True


def check_measurement(
    path: Path,
    relative_path: str,
    run_id: str,
    run_date: date | None,
    row: dict[str, Any],
    criteria: dict[str, dict[str, Any]] | None,
    legacy_file_ok: bool,
    failures: list[str],
    legacy_hits: list[str],
    seen_legacy_rows: set[tuple[str, str, str, str]],
    seen_legacy_files: set[str],
) -> None:
    """Apply R0-R4 to one measurement row."""
    status = row.get("pass_status")
    row_id = row.get("id", "<no id>")
    where = f"{path.name}: {row_id}"

    key_failures = _mapping_key_violations(row, where)
    if key_failures:
        failures.extend(key_failures)
        return
    for carrier_name in ("agent_claim", "oracle_measure", "delta"):
        carrier = row.get(carrier_name)
        if not isinstance(carrier, dict):
            continue
        nested = sorted(set(carrier) & NESTED_QDS_LINEAGE_FIELDS)
        if nested:
            failures.append(
                f"{where}: Eval {carrier_name} must not carry QDS lineage/verdict "
                f"field(s): {', '.join(nested)}; keep them on the parent "
                "MeasurementValue (#588)"
            )
    if not legacy_file_ok:
        for carrier_name in ("agent_claim", "oracle_measure", "delta"):
            if (carrier_name in row
                    and _typed_value_kind(row.get(carrier_name)) is None):
                failures.append(
                    f"{where}: {carrier_name} must set exactly one of a finite "
                    "numeric value, a nonblank text value, or "
                    "is_not_applicable: true (#588)"
                )
    if status is None:
        orphan_fields = sorted(
            field for field in (
                "pass_criterion", "pass_criterion_ref", "criterion_preconditions"
            ) if field in row
        )
        if orphan_fields:
            failures.append(
                f"{where}: criterion metadata requires an explicit pass_status; "
                f"orphan field(s): {', '.join(orphan_fields)} (#588)"
            )
        return

    if not isinstance(status, str):
        failures.append(
            f"{where}: pass_status must be a string, got {type(status).__name__}"
        )
        return
    raw = row.get("pass_criterion")
    if raw is not None and not isinstance(raw, str):
        failures.append(
            f"{where}: pass_criterion must be a string, got {type(raw).__name__}"
        )
        return
    criterion_ref = row.get("pass_criterion_ref")
    if criterion_ref is not None and not isinstance(criterion_ref, str):
        failures.append(
            f"{where}: pass_criterion_ref must be a string, got "
            f"{type(criterion_ref).__name__}"
        )
        return
    if isinstance(criterion_ref, str) and not criterion_ref.strip():
        failures.append(f"{where}: pass_criterion_ref must not be blank")
        return

    known = CRITERION_BEARING | CLAIM_BEARING | NON_VERDICT_STATUSES
    if status not in known:
        failures.append(
            f"{where}: pass_status {status!r} is not classified by this guard — "
            "it is checked by no rule (#567)"
        )
        return

    criterion = criterion_of(row)
    if status in CRITERION_BEARING:
        if not criterion:
            failures.append(
                f"{where}: pass_status {status!r} asserts a verdict against a criterion, "
                "but pass_criterion is empty (#567)"
            )
        elif not legacy_file_ok and not _looks_gradeable_criterion(criterion):
            failures.append(
                f"{where}: pass_criterion {criterion!r} is not a numeric comparison "
                "and cannot support a gradeable verdict (#588)"
            )
        if not criterion_ref:
            if legacy_file_ok:
                if relative_path not in seen_legacy_files:
                    legacy_hits.append(
                        f"{relative_path}: unregistered criteria accepted only for this "
                        "exact file SHA-256"
                    )
                seen_legacy_files.add(relative_path)
            else:
                failures.append(
                    f"{where}: pass_status {status!r} requires an authoritative "
                    "PassCriterionBinding pass_criterion_ref (#588)"
                )
        elif criteria is not None:
            registered = criteria.get(criterion_ref)
            if registered is None:
                failures.append(
                    f"{where}: pass_criterion_ref {criterion_ref!r} does not resolve in "
                    "ref/structural_criteria.yaml::pass_criterion_bindings (#588)"
                )
            else:
                normalized_criterion = _normalize_registry_text(criterion)
                criterion_matches = (
                    normalized_criterion
                    and normalized_criterion == registered["_threshold_criterion_text"]
                )
                if (normalized_criterion
                        and not criterion_matches):
                    failures.append(
                        f"{where}: pass_criterion {criterion!r} does not match the "
                        "criterion extracted from "
                        f"threshold registry section "
                        f"{registered['threshold_registry_section']} row "
                        f"{registered['threshold_registry_row']!r} (#588)"
                    )
                mismatches = _binding_mismatches(row, registered, run_date)
                if mismatches:
                    failures.append(
                        f"{where}: pass_criterion_ref {criterion_ref!r} is not "
                        "applicable to this row: " + "; ".join(mismatches) + " (#588)"
                    )
                if criterion_matches and not mismatches:
                    operand = _finite_criterion_operand(row, registered)
                    if operand is None:
                        delta_requirement = (
                            "; delta operands must equal unit-compatible "
                            "oracle_measure - agent_claim and cannot use "
                            "delta_from_measurement_ref"
                            if registered["comparison_operand"] == "delta"
                            else ""
                        )
                        failures.append(
                            f"{where}: pass_status {status!r} requires a finite numeric "
                            f"{registered['comparison_operand']}.value_numeric to "
                            f"evaluate its criterion, with exactly one value carrier "
                            f"and catalog unit {registered['comparison_unit']!r}"
                            f"{delta_requirement} (#588)"
                        )
                    else:
                        holds = _criterion_holds(operand, registered)
                        criterion_passes = (
                            holds if registered["_criterion_truth_means_pass"]
                            else not holds
                        )
                        expected = status in PASSING_VERDICTS
                        if criterion_passes != expected:
                            outcome = "passes" if criterion_passes else "fails"
                            failures.append(
                                f"{where}: pass_status {status!r} contradicts its "
                                f"numeric evidence: {registered['comparison_operand']} "
                                f"value {operand!r} {outcome} criterion {criterion!r} "
                                "(#588)"
                            )

    if status == INAPPLICABLE_STATUS:
        if not criterion:
            failures.append(
                f"{where}: criterion_inapplicable requires the authoritative "
                "pass_criterion display snapshot (#588)"
            )
        if not criterion_ref:
            failures.append(
                f"{where}: criterion_inapplicable requires pass_criterion_ref (#588)"
            )
        elif criteria is not None:
            registered = criteria.get(criterion_ref)
            if registered is None:
                failures.append(
                    f"{where}: pass_criterion_ref {criterion_ref!r} does not resolve in "
                    "ref/structural_criteria.yaml::pass_criterion_bindings (#588)"
                )
            else:
                normalized_criterion = _normalize_registry_text(criterion)
                if normalized_criterion != registered["_threshold_criterion_text"]:
                    failures.append(
                        f"{where}: criterion_inapplicable pass_criterion does not "
                        "match its authoritative registry cell (#588)"
                    )
                mismatches = _binding_mismatches(
                    row, registered, run_date, allow_inapplicable=True
                )
                if mismatches:
                    failures.append(
                        f"{where}: criterion_inapplicable binding is not applicable "
                        "to this row: " + "; ".join(mismatches) + " (#588)"
                    )

    if status == "informational":
        if "pass_criterion" in row:
            message = (
                f"{where}: pass_status 'informational' means 'reported without a declared "
                f"criterion', but pass_criterion is present as {row.get('pass_criterion')!r} "
                "(#567)"
            )
            if legacy_file_ok and _legacy_row_exception(
                "R2", relative_path, run_id, row, seen_legacy_rows
            ):
                legacy_hits.append(f"{message} — exact row SHA-256 exception")
            else:
                failures.append(message)
        if "pass_criterion_ref" in row:
            failures.append(
                f"{where}: pass_status 'informational' cannot carry "
                f"pass_criterion_ref {row.get('pass_criterion_ref')!r} (#588)"
            )
        if "criterion_preconditions" in row:
            failures.append(
                f"{where}: pass_status 'informational' cannot carry "
                "criterion_preconditions; use criterion_inapplicable for an "
                "evidence-backed void/unknown criterion (#588)"
            )

    if status in CLAIM_BEARING and (
        not _asserted_claim(row) or not _agent_oracle_disagree(row)
    ):
        if not _asserted_claim(row):
            detail = "agent_claim contains no asserted value"
        else:
            detail = (
                "agent_claim and oracle_measure do not demonstrate a finite, "
                "unit-compatible numeric disagreement"
            )
        message = (
            f"{where}: pass_status {status!r} asserts oracle disagreement, but "
            f"{detail} (#588)"
        )
        if legacy_file_ok and _legacy_row_exception(
            "R3", relative_path, run_id, row, seen_legacy_rows
        ):
            legacy_hits.append(f"{message} — exact row SHA-256 exception")
        else:
            failures.append(message)

    if (not legacy_file_ok and status in {"pass", "fail_criterion"}
            and _asserted_claim(row)):
        relation = _numeric_agent_oracle_relation(row)
        if relation is not True:
            detail = (
                "differ" if relation is False else
                "are not finite, numeric, and unit-compatible"
            )
            failures.append(
                f"{where}: pass_status {status!r} does not assert disagreement, "
                f"but retained agent_claim and oracle_measure {detail}; use a "
                "claim-bearing disagreement status or omit a non-load-bearing "
                "agent_claim (#588)"
            )

    if status == "fail_by_oracle_within_cctbx" and row.get("oracle_family") != "cctbx":
        failures.append(
            f"{where}: pass_status 'fail_by_oracle_within_cctbx' requires "
            f"oracle_family 'cctbx', got {row.get('oracle_family')!r} (#567)"
        )


def check_run_consistency(
    path: Path,
    run_id: str,
    rows: list[dict[str, Any]],
    failures: list[str],
) -> None:
    """R5: reject divergent statuses only for scientifically identical rows."""
    groups: dict[str, list[dict[str, Any]]] = {}
    known = CRITERION_BEARING | CLAIM_BEARING | NON_VERDICT_STATUSES
    for row in rows:
        status = row.get("pass_status")
        if not isinstance(status, str) or status not in known:
            continue
        signature = {
            field: _signature_value(field, row.get(field))
            for field in VERDICT_SIGNATURE_FIELDS
            if row.get(field) is not None and row.get(field) != []
        }
        key = json.dumps(
            signature, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
            default=_json_default,
        )
        groups.setdefault(key, []).append(row)
    for group in groups.values():
        statuses = {row["pass_status"] for row in group}
        if len(statuses) < 2:
            continue
        members = ", ".join(
            f"{row.get('id', '<no id>')}={row['pass_status']}" for row in group
        )
        failures.append(
            f"{path.name}: EvaluationRun {run_id!r} assigns different pass_status "
            f"values to rows with identical scientific context and evidence: {members} (#589)"
        )


def check_run_cross_family_trust(
    path: Path,
    run_id: str,
    rows: list[dict[str, Any]],
    legacy_file_ok: bool,
    failures: list[str],
) -> None:
    """Reserve hard verdicts for independent, non-cctbx oracle rows."""
    if legacy_file_ok:
        return
    valid_rows = [
        row for row in rows
        if not _mapping_key_violations(row, str(row.get("id", "<no id>")))
    ]
    for row in valid_rows:
        status = row.get("pass_status")
        if (row.get("oracle_family") != "cctbx"
                or not isinstance(status, str)
                or status not in CRITERION_BEARING
                or status == "fail_by_oracle_within_cctbx"):
            continue
        failures.append(
            f"{path.name}: EvaluationRun {run_id!r} measurement "
            f"{row.get('id', '<no id>')!r} assigns hard verdict {status!r} on a "
            "cctbx row. Record cctbx results as informational, or use "
            "fail_by_oracle_within_cctbx for unresolved same-family disagreement; "
            "the hard verdict belongs on the independently re-measured non_cctbx "
            "row (#588)"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    args = parser.parse_args()
    root = Path(args.root)

    schema_failures: list[str] = []
    record_failures: list[str] = []
    legacy_hits: list[str] = []
    seen_legacy_rows: set[tuple[str, str, str, str]] = set()
    seen_legacy_files: set[str] = set()
    checked = 0
    files = 0
    canonical_root = Path(__file__).resolve().parent.parent
    enforce_legacy_policy = root.resolve() == canonical_root.resolve()

    try:
        declared = schema_statuses(root)
    except (yaml.YAMLError, OSError, UnicodeError, ConfigurationShapeError) as exc:
        schema_failures.append(
            f"schemas/protstruct_review.yaml PassStatus is unreadable: "
            f"{type(exc).__name__}: {exc}"
        )
        declared = set()
    if not declared and not schema_failures:
        schema_failures.append("schemas/protstruct_review.yaml declares no PassStatus enum")
    known = CRITERION_BEARING | CLAIM_BEARING | NON_VERDICT_STATUSES
    for orphan in sorted(declared - known):
        schema_failures.append(
            f"schemas/protstruct_review.yaml declares PassStatus {orphan!r}, which this "
            "guard has no rule for — classify it before shipping (#567)"
        )
    for missing in sorted(known - declared):
        schema_failures.append(
            f"schemas/protstruct_review.yaml omits guarded PassStatus {missing!r}; "
            "the schema and semantic guard must declare the same vocabulary (#567)"
        )

    try:
        criteria: dict[str, dict[str, Any]] | None = pass_criterion_bindings(root)
    except (yaml.YAMLError, OSError, UnicodeError, ConfigurationShapeError) as exc:
        schema_failures.append(
            "ref/structural_criteria.yaml pass_criterion_bindings is unreadable: "
            f"{type(exc).__name__}: {exc}"
        )
        criteria = None

    for path in sorted((root / "data").rglob("EVAL_*.yaml")):
        files += 1
        dated_stem = re.search(r"_(\d{4}-\d{2}-\d{2})$", path.stem)
        filename_date: date | None = None
        if dated_stem is None:
            record_failures.append(
                f"{path.name}: canonical EVAL filename must end in YYYY-MM-DD "
                "matching EvaluationRun.run_date"
            )
        else:
            try:
                filename_date = date.fromisoformat(dated_stem.group(1))
            except ValueError:
                record_failures.append(
                    f"{path.name}: filename date is not a valid calendar date"
                )
        try:
            relative_path = path.relative_to(root).as_posix()
        except ValueError:
            relative_path = str(path)
        expected_file_hash = LEGACY_UNREGISTERED_CRITERION_FILES.get(relative_path)
        try:
            legacy_file_ok = (
                enforce_legacy_policy
                and expected_file_hash is not None
                and _file_digest(path) == expected_file_hash
            )
            doc = _strict_yaml_load(path.read_text())
        except (yaml.YAMLError, OSError, UnicodeError, ConfigurationShapeError) as exc:
            record_failures.append(
                f"{path.name}: unreadable ({type(exc).__name__}): {exc}"
            )
            continue
        if not isinstance(doc, dict):
            record_failures.append(f"{path.name}: top-level YAML is not a mapping")
            continue
        runs = doc.get("evaluation_runs")
        if not isinstance(runs, list) or not runs:
            record_failures.append(
                f"{path.name}: evaluation_runs must be a nonempty list"
            )
            continue
        for run in runs:
            if not isinstance(run, dict):
                record_failures.append(f"{path.name}: an evaluation_runs entry is not a mapping")
                continue
            run_id = run.get("id")
            if not isinstance(run_id, str) or not run_id.strip():
                record_failures.append(
                    f"{path.name}: EvaluationRun id must be a nonblank string"
                )
                run_id = "<no run id>"
            try:
                run_date = _iso_date(
                    run.get("run_date"),
                    f"{path.name}: EvaluationRun {run_id!r}.run_date",
                )
            except ConfigurationShapeError as exc:
                record_failures.append(str(exc))
                run_date = None
            if (run_date is not None and filename_date is not None
                    and run_date != filename_date):
                record_failures.append(
                    f"{path.name}: EvaluationRun {run_id!r}.run_date "
                    f"{run_date.isoformat()} does not match filename date "
                    f"{filename_date.isoformat()}"
                )
            rows = run.get("measurements")
            if not isinstance(rows, list) or not rows:
                record_failures.append(
                    f"{path.name}: measurements must be a nonempty list"
                )
                continue
            mapping_rows: list[dict[str, Any]] = []
            for row in rows:
                if not isinstance(row, dict):
                    record_failures.append(f"{path.name}: a measurements entry is not a mapping")
                    continue
                checked += 1
                mapping_rows.append(row)
                check_measurement(
                    path, relative_path, run_id, run_date, row, criteria, legacy_file_ok,
                    record_failures, legacy_hits, seen_legacy_rows, seen_legacy_files,
                )
            check_run_consistency(path, run_id, mapping_rows, record_failures)
            check_run_cross_family_trust(
                path, run_id, mapping_rows, legacy_file_ok, record_failures
            )

    if files == 0:
        record_failures.append(
            f"no EVAL_*.yaml records found under {root / 'data'} — refusing to report "
            "success on an empty scan (#567)"
        )
    elif checked == 0:
        record_failures.append(
            "no MeasurementValue rows were checked — refusing to report success on "
            "an empty or malformed EVAL scan (#567)"
        )

    if enforce_legacy_policy:
        for key in sorted(set(LEGACY_ROW_EXCEPTIONS) - seen_legacy_rows):
            record_failures.append(
                "stale or changed legacy row exception was not consumed: "
                f"rule={key[0]} path={key[1]} run={key[2]} row={key[3]} (#590)"
            )
        for relative_path in sorted(
            set(LEGACY_UNREGISTERED_CRITERION_FILES) - seen_legacy_files
        ):
            record_failures.append(
                "stale or changed legacy criterion-file exception was not consumed: "
                f"{relative_path} (#590)"
            )

    for line in legacy_hits:
        print(f"  explicit legacy exception: {line}")
    for line in schema_failures:
        print(f"FAIL  {line}", file=sys.stderr)
    for line in record_failures:
        print(f"FAIL  {line}", file=sys.stderr)

    if schema_failures:
        print(
            f"pass_status schema/registry: {len(schema_failures)} violation(s)",
            file=sys.stderr,
        )
    if record_failures:
        print(
            f"pass_status records: {len(record_failures)} violation(s); "
            f"{checked} measurement(s) checked in {files} file(s)",
            file=sys.stderr,
        )
    if schema_failures or record_failures:
        return 1
    print(
        f"pass_status semantics hold ({checked} measurements checked, "
        f"{len(legacy_hits)} explicit legacy exception(s))"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
