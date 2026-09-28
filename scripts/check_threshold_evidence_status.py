#!/usr/bin/env python3
"""Recount the descriptive section-3/4 evidence ledger without changing grading.

This checks coverage, provenance drift and generated summaries. It cannot establish
scientific validity, independently calibrated thresholds or permission to grade.
"""
from __future__ import annotations

import argparse
from collections import Counter
import datetime as dt
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys

import yaml

from strict_yaml import strict_yaml_load

REPO = Path(__file__).resolve().parent.parent
LEDGER = "ref/threshold_evidence_status.yaml"
REGISTRY = "ref/thresholds_and_standards.md"
CONSUMERS = (REGISTRY, "NEXT_TASKS.md")
# #836: these retained narratives are not current certification. Protect their
# explicit visible qualifiers, not arbitrary prose or every historical number.
HISTORICAL_QUALIFIERS = {
    REGISTRY: ("> **Historical through-round48 inventory (not current authority).**",),
    "NEXT_TASKS.md": (
        "**Historical registry narrative (through round48; not current policy).**",
        "**Historical count convention (round 18) — two different counting units.**",
    ),
    "ref/research/partial_record_triage.md": (
        "> **Historical triage, retained 2026-09-27; not a current completeness claim.**",
    ),
}
START = "<!-- threshold-status-summary:start -->"
END = "<!-- threshold-status-summary:end -->"
POLICY_STATES = frozenset({
    "active_conditional", "informational", "provisional_informational",
    "provisional_conditional", "suspended", "not_evaluable", "policy_unresolved",
})
EVIDENCE_STATES = frozenset({
    "retained_record", "partial_record", "denominator_unproven", "producer_mismatch",
    "unmeasured", "unverified_ancillary", "limited_controls", "external_standard_cited",
})
HISTORICAL_STATES = frozenset({"reported_backed", "reported_partial", "excluded_literature"})
TOP_FIELDS = frozenset({
    "format_version", "status", "as_of_date", "scope", "source", "inventory_sections",
    "review_depth", "policy_state_definition", "evidence_state_definition",
    "historical_inventory_definition", "rows",
})
ROW_FIELDS = frozenset({
    "id", "section", "row_label", "observed_line", "row_sha256", "provenance_tags",
    "historical_inventory_class", "evidence_refs", "components",
})
COMPONENT_FIELDS = frozenset({
    "id", "scope", "policy_state", "evidence_state", "limitations", "issue_refs",
})
EVIDENCE_FIELDS = frozenset({"path", "anchor", "sha256", "hash_scope"})
TAG = re.compile(r"\[(?:benchmark(?: — [^\]]+)?|template|literature|catalog|schema|MolProbity|calibration)\]")
HASH = re.compile(r"[0-9a-f]{64}")


def _shape(value, fields: frozenset[str], where: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{where}: expected mapping")
    if set(value) != fields:
        raise ValueError(f"{where}: missing/unknown fields {set(value) ^ fields}")


def _text(value, where: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{where}: expected nonempty string")


def _identifier(value, where: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", value):
        raise ValueError(f"{where}: invalid identifier")


def _hash(value, where: str) -> None:
    if not isinstance(value, str) or not HASH.fullmatch(value):
        raise ValueError(f"{where}: invalid SHA-256")


def _items(value, where: str, *, nonempty: bool = True) -> None:
    if not isinstance(value, list) or (nonempty and not value):
        raise ValueError(f"{where}: expected {'nonempty ' if nonempty else ''}list")


def _path(value, where: str) -> None:
    _text(value, where)
    path = PurePosixPath(value)
    if (path.is_absolute() or ".." in path.parts or "\\" in value
            or path.as_posix() != value or value in (".", "")):
        raise ValueError(f"{where}: path must be canonical repository-relative")


def load_ledger(path: Path) -> dict:
    try:
        doc = strict_yaml_load(path.read_text())
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"{path}: unreadable ledger: {error}") from error
    _shape(doc, TOP_FIELDS, "ledger")
    if type(doc["format_version"]) is not int or doc["format_version"] != 1:
        raise ValueError("ledger: unsupported format_version")
    if doc["status"] != "descriptive_inventory":
        raise ValueError("ledger: status must be descriptive_inventory")
    if doc["source"] != REGISTRY or doc["inventory_sections"] != [3, 4]:
        raise ValueError("ledger: source/scope must be the canonical sections 3 and 4")
    if any(type(section) is not int for section in doc["inventory_sections"]):
        raise ValueError("ledger: section numbers must be integers")
    date = doc["as_of_date"]
    if not isinstance(date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        raise ValueError("ledger: as_of_date must be a quoted ISO date")
    try:
        dt.date.fromisoformat(date)
    except ValueError as error:
        raise ValueError("ledger: invalid as_of_date") from error
    for name in ("scope", "review_depth", "policy_state_definition",
                 "evidence_state_definition", "historical_inventory_definition"):
        _text(doc[name], f"ledger.{name}")
    _items(doc["rows"], "ledger.rows")
    ids, keys = set(), set()
    for row in doc["rows"]:
        _shape(row, ROW_FIELDS, "row")
        _identifier(row["id"], "row.id")
        where = row["id"]
        if row["id"] in ids:
            raise ValueError(f"{where}: duplicate row id")
        ids.add(row["id"])
        if type(row["section"]) is not int or row["section"] not in (3, 4):
            raise ValueError(f"{where}: invalid section")
        _text(row["row_label"], f"{where}.row_label")
        if "\n" in row["row_label"] or "\r" in row["row_label"]:
            raise ValueError(f"{where}: row label cannot span lines")
        key = (row["section"], row["row_label"])
        if key in keys:
            raise ValueError(f"{where}: duplicate row locator")
        keys.add(key)
        if type(row["observed_line"]) is not int or row["observed_line"] < 1:
            raise ValueError(f"{where}: observed_line must be positive")
        _hash(row["row_sha256"], f"{where}.row_sha256")
        if (not isinstance(row["historical_inventory_class"], str)
                or row["historical_inventory_class"] not in HISTORICAL_STATES):
            raise ValueError(f"{where}: unknown historical classification")
        _items(row["provenance_tags"], f"{where}.provenance_tags")
        if any(not isinstance(tag, str) or not TAG.fullmatch(tag)
               for tag in row["provenance_tags"]):
            raise ValueError(f"{where}: malformed provenance tags")
        if len(set(row["provenance_tags"])) != len(row["provenance_tags"]):
            raise ValueError(f"{where}: duplicate provenance tags")
        _items(row["evidence_refs"], f"{where}.evidence_refs")
        refs = set()
        for evidence in row["evidence_refs"]:
            _shape(evidence, EVIDENCE_FIELDS, f"{where}.evidence")
            _path(evidence["path"], f"{where}.evidence.path")
            _text(evidence["anchor"], f"{where}.evidence.anchor")
            _hash(evidence["sha256"], f"{where}.evidence.sha256")
            if evidence["hash_scope"] not in ("full_file", "registry_row"):
                raise ValueError(f"{where}: invalid evidence hash_scope")
            if evidence["path"] == REGISTRY:
                if (evidence["hash_scope"] != "registry_row"
                        or evidence["sha256"] != row["row_sha256"]):
                    raise ValueError(f"{where}: self-evidence must pin the owning registry row")
            elif evidence["hash_scope"] != "full_file":
                raise ValueError(f"{where}: registry_row scope requires the canonical registry")
            reference = (evidence["path"], evidence["anchor"])
            if reference in refs:
                raise ValueError(f"{where}: duplicate evidence reference")
            refs.add(reference)
        _items(row["components"], f"{where}.components")
        component_ids = set()
        for component in row["components"]:
            _shape(component, COMPONENT_FIELDS, f"{where}.component")
            _identifier(component["id"], f"{where}.component.id")
            if component["id"] in component_ids:
                raise ValueError(f"{where}: duplicate component id")
            component_ids.add(component["id"])
            for field in ("scope", "limitations"):
                _text(component[field], f"{where}.{component['id']}.{field}")
            if (not isinstance(component["policy_state"], str)
                    or component["policy_state"] not in POLICY_STATES):
                raise ValueError(f"{where}: unknown policy_state")
            if (not isinstance(component["evidence_state"], str)
                    or component["evidence_state"] not in EVIDENCE_STATES):
                raise ValueError(f"{where}: unknown evidence_state")
            _items(component["issue_refs"], f"{where}.issue_refs", nonempty=False)
            if any(type(issue) is not int or issue < 1 for issue in component["issue_refs"]):
                raise ValueError(f"{where}: issue references must be positive integers")
            if len(set(component["issue_refs"])) != len(component["issue_refs"]):
                raise ValueError(f"{where}: duplicate issue reference")
    return doc


def _visible_lines(text: str):
    """Ignore non-rendered examples/comments without reinterpreting criterion cells."""
    fence = None
    comment = False
    for number, raw in enumerate(text.splitlines(), 1):
        if fence:
            if re.fullmatch(rf" {{0,3}}{re.escape(fence[0])}{{{fence[1]},}}[ \t]*", raw):
                fence = None
            yield number, raw, ""
            continue
        parts, remaining = [], raw
        while remaining:
            if comment:
                _, marker, remaining = remaining.partition("-->")
                if not marker:
                    remaining = ""
                    break
                comment = False
            else:
                before, marker, remaining = remaining.partition("<!--")
                parts.append(before)
                if not marker:
                    break
                comment = True
        line = "".join(parts)
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if marker:
            fence = (marker[1][0], len(marker[1]))
            line = ""
        elif line.startswith("\t") or line.startswith("    "):
            line = ""
        elif re.match(r"^ {0,3}(?:</?[a-z][a-z0-9-]*(?=[\t />]|$)|<\?|<!\[cdata\[|<![a-z])",
                      line, re.IGNORECASE):
            raise ValueError(f"registry line {number}: raw HTML block is unsupported")
        yield number, raw, line
    if fence or comment:
        raise ValueError("registry: unterminated fence or HTML comment")


def _cells(line: str) -> list[str] | None:
    if not line.lstrip().startswith("|"):
        return None
    value = line.strip()[1:]
    if value.endswith("|"):
        value = value[:-1]
    return [cell.replace(r"\|", "|").strip() for cell in re.split(r"(?<!\\)\|", value)]


def _separator(line: str) -> bool:
    cells = _cells(line)
    return bool(cells) and len(cells) > 1 and all(
        re.fullmatch(r":?-{3,}:?", cell) for cell in cells
    )


def registry_rows(text: str) -> dict[tuple[int, str], str]:
    lines = list(_visible_lines(text))
    result = {}
    headings = Counter()
    section, in_table = None, False
    for index, (number, raw, line) in enumerate(lines):
        heading = re.match(r"^ {0,3}##\s+(\d+)\.", line)
        if re.match(r"^ {0,3}##\s+", line):
            section = int(heading[1]) if heading else None
            in_table = False
            if section in (3, 4):
                headings[section] += 1
            continue
        if section not in (3, 4):
            continue
        if _separator(line):
            continue
        cells = _cells(line)
        if cells is None:
            in_table = False
            continue
        if index + 1 < len(lines) and _separator(lines[index + 1][2]):
            in_table = True
            continue
        if not in_table:
            continue
        label = cells[0]
        if not label:
            raise ValueError(f"registry line {number}: empty first-cell label")
        key = (section, label)
        if key in result:
            raise ValueError(f"registry line {number}: duplicate row {key}")
        result[key] = raw
    if headings != Counter({3: 1, 4: 1}):
        raise ValueError("registry: require exactly one numbered H2 for sections 3 and 4")
    return result


def recount(ledger: dict) -> dict:
    rows = ledger["rows"]
    components = [component for row in rows for component in row["components"]]
    count = lambda values: dict(sorted(Counter(values).items()))
    return {
        "row_count": len(rows),
        "component_count": len(components),
        "section_counts": count(str(row["section"]) for row in rows),
        "historical_inventory": count(row["historical_inventory_class"] for row in rows),
        "benchmark_family_count": sum(
            any(tag.startswith("[benchmark") for tag in row["provenance_tags"]) for row in rows
        ),
        "policy_counts": count(component["policy_state"] for component in components),
        "evidence_counts": count(component["evidence_state"] for component in components),
        "cross_counts": count(component["policy_state"] + "/" + component["evidence_state"]
                              for component in components),
        "row_flags": {
            state: sorted(row["id"] for row in rows if any(
                component["policy_state"] == state for component in row["components"]
            )) for state in sorted(POLICY_STATES)
        },
        "evidence_row_flags": {
            state: sorted(row["id"] for row in rows if any(
                component["evidence_state"] == state for component in row["components"]
            )) for state in sorted(EVIDENCE_STATES)
        },
    }


def summary(ledger: dict) -> str:
    totals = recount(ledger)
    history = totals["historical_inventory"]
    def counts(values):
        return "; ".join(f"{key}={value}" for key, value in values.items())
    flags = "; ".join(
        f"{state}: {', '.join(totals['row_flags'][state]) or 'none'}"
        for state in ("suspended", "not_evaluable", "policy_unresolved",
                      "provisional_informational", "provisional_conditional")
    )
    return (
        "**Current descriptive inventory (§3/§4; not grading authorization).**\n\n"
        f"{totals['row_count']} rows; {totals['benchmark_family_count']} benchmark-family rows "
        f"(including qualified tags); {totals['component_count']} scoped components.\n"
        "Historical through-round48 labels: "
        f"{history.get('reported_backed', 0)} reported-backed / "
        f"{history.get('reported_partial', 0)} reported-partial / "
        f"{history.get('excluded_literature', 0)} excluded-literature rows. "
        "These are historical claims, not current scientific certification.\n\n"
        "Component policy counts: " + counts(totals["policy_counts"]) + ".\n\n"
        "Component evidence counts: " + counts(totals["evidence_counts"]) + ".\n\n"
        "Scoped row flags (overlapping, not additive): " + flags + ".\n\n"
        "The ledger separates active rules from retained evidence, provisional interpretation, "
        "suspension and unavailable calibration. Retained records do not by themselves establish "
        "independent calibration or complete execution provenance. Counts of components are not "
        "counts of rows or distinct benchmarks. See `ref/threshold_evidence_status.yaml`; "
        "scientific grading still requires the applicable registry criterion and evidence."
    )


def resolve_evidence(root: Path, relative: str) -> Path:
    _path(relative, "evidence path")
    path = root / relative
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
        raise ValueError(f"evidence path escapes repository or is not a file: {relative}")
    return resolved


def _consumer_error(text: str, expected: str, label: str) -> str | None:
    if text.count(START) != 1 or text.count(END) != 1:
        return f"{label}: require exactly one generated summary block"
    if text.index(END) < text.index(START):
        return f"{label}: reversed generated summary markers"
    before, after = text.split(START, 1)
    content, _ = after.split(END, 1)
    if END in before or content != "\n" + expected + "\n":
        return f"{label}: stale or malformed generated summary"
    # A byte-identical block inside a fence/comment is not a published summary.
    first = text[:text.index(START)].count("\n") + 2
    last = first + len(expected.splitlines()) - 1
    try:
        visible = {number: line for number, _, line in _visible_lines(text)}
    except ValueError as error:
        return f"{label}: unsupported summary visibility: {error}"
    if any(visible.get(number) != line
           for number, line in zip(range(first, last + 1), expected.splitlines())):
        return f"{label}: generated summary is not visibly rendered"
    return None


def _historical_qualification_errors(text: str, label: str) -> list[str]:
    try:
        lines = [visible for _, _, visible in _visible_lines(text)]
    except ValueError as error:
        return [f"{label}: unsupported historical-qualification visibility: {error}"]
    return [
        f"{label}: require exactly one visible historical qualifier: {qualifier}"
        for qualifier in HISTORICAL_QUALIFIERS[label]
        if sum(line.startswith(qualifier) for line in lines) != 1
    ]


def audit(root: Path) -> list[str]:
    try:
        ledger = load_ledger(root / LEDGER)
        actual = registry_rows((root / REGISTRY).read_text())
    except (OSError, ValueError, TypeError) as error:
        return [str(error)]
    errors = []
    indexed = {(row["section"], row["row_label"]): row for row in ledger["rows"]}
    if set(indexed) != set(actual):
        errors.append(f"registry/ledger coverage mismatch: missing={sorted(set(actual) - set(indexed))}; "
                      f"extra={sorted(set(indexed) - set(actual))}")
    for key in sorted(set(indexed) & set(actual)):
        row, literal = indexed[key], actual[key]
        if hashlib.sha256(literal.encode()).hexdigest() != row["row_sha256"]:
            errors.append(f"{row['id']}: stale registry row fingerprint")
        if TAG.findall(literal) != row["provenance_tags"]:
            errors.append(f"{row['id']}: stale provenance tags")
        for evidence in row["evidence_refs"]:
            try:
                if evidence["hash_scope"] == "registry_row":
                    content = literal.encode()
                else:
                    content = resolve_evidence(root, evidence["path"]).read_bytes()
                if hashlib.sha256(content).hexdigest() != evidence["sha256"]:
                    errors.append(f"{row['id']}: changed evidence fingerprint: {evidence['path']}")
                if evidence["anchor"] not in content.decode():
                    errors.append(f"{row['id']}: missing evidence anchor: {evidence['path']}")
            except (OSError, ValueError, UnicodeError) as error:
                errors.append(f"{row['id']}: unreadable evidence {evidence['path']}: {error}")
    expected = summary(ledger)
    for consumer in CONSUMERS:
        try:
            error = _consumer_error((root / consumer).read_text(), expected, consumer)
            if error:
                errors.append(error)
        except OSError as error:
            errors.append(f"{consumer}: unreadable summary consumer: {error}")
    for consumer in HISTORICAL_QUALIFIERS:
        try:
            errors.extend(_historical_qualification_errors((root / consumer).read_text(), consumer))
        except OSError as error:
            errors.append(f"{consumer}: unreadable historical narrative: {error}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO)
    parser.add_argument("--json", action="store_true", help="print deterministic recount JSON")
    args = parser.parse_args()
    errors = audit(args.root)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    ledger = load_ledger(args.root / LEDGER)
    print(json.dumps(recount(ledger), sort_keys=True, indent=2) if args.json else summary(ledger))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
