#!/usr/bin/env python3
"""Hermetic #766 ledger recount, visibility, drift and consumer regressions.

These tests inspect retained records; they neither execute scientific tools nor
turn evidence-status metadata into permission to grade a measurement. Set TMPDIR
to a scratch directory when running a staged copy of this test.
"""
from __future__ import annotations

import ast
from collections import Counter
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import yaml

import check_threshold_evidence_status as guard


REPO = Path(__file__).resolve().parent.parent
LEDGER = "ref/threshold_evidence_status.yaml"
REGISTRY = "ref/thresholds_and_standards.md"
CONSUMERS = (REGISTRY, "NEXT_TASKS.md")
BEGIN = "<!-- threshold-status-summary:start -->"
END = "<!-- threshold-status-summary:end -->"
EVIDENCE_PATH = "ref/research/synthetic_retained_evidence.md"
EVIDENCE = "# Retained synthetic record\n\n## Results\n\nReported numbers are informational.\n"


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write(root: Path, path: str, text: str) -> None:
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def dump_ledger(root: Path, ledger: dict) -> None:
    write(root, LEDGER, yaml.safe_dump(ledger, sort_keys=False, allow_unicode=True))


def component(identity: str, policy: str, evidence: str) -> dict:
    return {
        "id": identity,
        "scope": f"Synthetic scoped claim: {identity}",
        "policy_state": policy,
        "evidence_state": evidence,
        "limitations": "Retained text is not execution authentication or independent calibration.",
        "issue_refs": [],
    }


def fixture(root: Path, template: dict) -> dict:
    """Only four rows and one evidence file; never copy the repository."""
    ledger = deepcopy(template)
    specifications = (
        (
            "secondary_structure", 3, "Secondary-structure agreement",
            "[benchmark — historical denominator unproven]", "reported_backed",
            [component("agent_vs_dssp", "active_conditional", "unmeasured"),
             component("two_assigner_expectation", "provisional_informational", "denominator_unproven"),
             component("content_precondition", "provisional_informational", "limited_controls")],
        ),
        (
            "h_placement", 3, "H-placement agreement", "[benchmark]", "reported_backed",
            [component("flip_conflict", "suspended", "producer_mismatch"),
             component("h_count", "active_conditional", "retained_record"),
             component("historical_clashscore", "active_conditional", "retained_record"),
             component("changed_h_build", "informational", "unmeasured")],
        ),
        (
            "l_test", 3, r"L-test ⟨\|L\|⟩", "[benchmark]", "reported_partial",
            [component("twin_call", "active_conditional", "partial_record"),
             component("numeric_delta", "informational", "partial_record")],
        ),
        (
            "absolute_floors", 4, "Absolute geometry floors", "[literature]", "excluded_literature",
            [component("quality_bars", "active_conditional", "external_standard_cited")],
        ),
    )
    ledger["rows"] = []
    lines_by_section: dict[int, list[str]] = {3: [], 4: []}
    for identity, section, label, tag, history, components in specifications:
        source_row = f"| {label} | Compare |Δ| and |Z| under stated conditions. | oracle | `{tag}` |"
        self_reference = identity == "absolute_floors"
        ledger["rows"].append({
            "id": identity,
            "section": section,
            "row_label": label.replace(r"\|", "|"),
            "observed_line": 999,  # Deliberately non-authoritative diagnostic.
            "row_sha256": sha256(source_row),
            "provenance_tags": [tag],
            "historical_inventory_class": history,
            "evidence_refs": [{
                "path": REGISTRY if self_reference else EVIDENCE_PATH,
                "anchor": f"| {label} |" if self_reference else "## Results",
                "sha256": sha256(source_row) if self_reference else sha256(EVIDENCE),
                "hash_scope": "registry_row" if self_reference else "full_file",
            }],
            "components": components,
        })
        lines_by_section[section].append(source_row)
    registry = "# Synthetic registry\n\n"
    for section, title in ((3, "Cross-tool agreement tolerances"), (4, "Before/after tolerances")):
        registry += (
            f"## {section}. {title}\n\n"
            "| Metric | Tolerance | Tools | Provenance |\n"
            "|---|---|---|---|\n" + "\n".join(lines_by_section[section]) + "\n\n"
        )
    registry += "## 5. Outside the inventory\n\n"
    registry += "| Metric | Tolerance | Tools | Provenance |\n|---|---|---|---|\n"
    registry += "| Not inventoried | Outside sections 3/4 | oracle | `[benchmark]` |\n"
    block = BEGIN + "\n" + guard.summary(ledger) + "\n" + END + "\n"
    registry += "\n" + "\n".join(guard.HISTORICAL_QUALIFIERS[REGISTRY]) + "\n"
    write(root, REGISTRY, registry + "\n" + block)
    write(root, "NEXT_TASKS.md", "# Next tasks\n\n" + block + "\n"
          + "\n".join(guard.HISTORICAL_QUALIFIERS["NEXT_TASKS.md"]) + "\n")
    write(root, "ref/research/partial_record_triage.md", "# Synthetic historical triage\n\n"
          + "\n".join(guard.HISTORICAL_QUALIFIERS["ref/research/partial_record_triage.md"]) + "\n")
    write(root, EVIDENCE_PATH, EVIDENCE)
    dump_ledger(root, ledger)
    return ledger


class ThresholdEvidenceStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.published = guard.load_ledger(REPO / LEDGER)

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="threshold-evidence-status-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.ledger = fixture(self.root, self.published)
        self.assertEqual(guard.audit(self.root), [], "Synthetic baseline must be audit-clean")

    def reset_fixture(self) -> None:
        self.ledger = fixture(self.root, self.published)

    def read_registry(self) -> str:
        return (self.root / REGISTRY).read_text(encoding="utf-8")

    def assert_audit_fails(self) -> list[str]:
        errors = guard.audit(self.root)
        self.assertTrue(errors, "Mutation must be rejected rather than silently ignored")
        return errors

    def audit_published(self) -> list[str]:
        """A staged test may read unchanged evidence from an explicit base root."""
        base_name = os.environ.get("PROTSTRUCT_TEST_BASE_ROOT")
        if not base_name:
            return guard.audit(REPO)
        base = Path(base_name).resolve()
        resolve = guard.resolve_evidence

        def overlay(root: Path, relative: str) -> Path:
            # Containment remains enforced by the production resolver for both
            # roots. Only published-state evidence uses this read-only fallback.
            chosen = root if (root / relative).exists() else base
            return resolve(chosen, relative)

        with mock.patch.object(guard, "resolve_evidence", side_effect=overlay):
            return guard.audit(REPO)

    def test_01_published_inventory_and_both_axes_are_recomputed(self) -> None:
        self.assertEqual(Path(guard.__file__).resolve().parent, Path(__file__).resolve().parent)
        self.assertEqual(self.audit_published(), [])
        counts = guard.recount(self.published)
        self.assertEqual(counts["row_count"], 21)
        self.assertEqual(counts["component_count"], 41)
        self.assertEqual(counts["section_counts"], {"3": 17, "4": 4})
        self.assertEqual(counts["historical_inventory"], {
            "reported_backed": 18, "reported_partial": 2, "excluded_literature": 1,
        })
        self.assertEqual(counts["benchmark_family_count"], 20)
        components = [item for row in self.published["rows"] for item in row["components"]]
        for axis, key in (("policy_state", "policy_counts"), ("evidence_state", "evidence_counts")):
            expected = Counter(item[axis] for item in components)
            self.assertEqual({k: v for k, v in counts[key].items() if v}, dict(expected))
            self.assertEqual(sum(counts[key].values()), len(components))
        expected_cross = Counter(f"{item['policy_state']}/{item['evidence_state']}" for item in components)
        self.assertEqual({k: v for k, v in counts["cross_counts"].items() if v}, dict(expected_cross))
        self.assertEqual(guard.recount(self.published), counts)

    def test_02_t15_current_change_does_not_reclassify_history(self) -> None:
        before = guard.recount(self.ledger)
        summary_before = guard.summary(self.ledger)
        changed = deepcopy(self.ledger)
        changed["rows"][0]["components"][1]["evidence_state"] = "retained_record"
        after = guard.recount(changed)
        self.assertNotEqual(guard.summary(changed), summary_before)
        self.assertEqual(after["historical_inventory"], before["historical_inventory"])
        self.assertEqual(after["policy_counts"], before["policy_counts"])
        self.assertNotEqual(after["evidence_counts"], before["evidence_counts"])
        dump_ledger(self.root, changed)
        self.assert_audit_fails()  # Existing consumer summaries are now stale.

    def test_03_t14_flip_change_preserves_sibling_scopes(self) -> None:
        changed = deepcopy(self.ledger)
        siblings = deepcopy(changed["rows"][1]["components"][1:])
        changed["rows"][1]["components"][0]["policy_state"] = "informational"
        changed["rows"][1]["components"][0]["evidence_state"] = "unmeasured"
        self.assertEqual(changed["rows"][1]["components"][1:], siblings)
        before, after = guard.recount(self.ledger), guard.recount(changed)
        self.assertEqual(before["policy_counts"]["active_conditional"], after["policy_counts"]["active_conditional"])
        self.assertNotEqual(guard.summary(self.ledger), guard.summary(changed))
        self.assertIn("h_placement", after["row_flags"]["active_conditional"])
        self.assertNotIn("h_placement", after["row_flags"]["suspended"])

    def test_04_qualified_benchmark_tag_is_not_dropped(self) -> None:
        counts = guard.recount(self.ledger)
        literal_only = sum("[benchmark]" in row["provenance_tags"] for row in self.ledger["rows"])
        self.assertEqual(literal_only, 2)
        self.assertEqual(counts["benchmark_family_count"], 3)
        changed = deepcopy(self.ledger)
        changed["rows"][0]["provenance_tags"] = ["[benchmark]"]
        dump_ledger(self.root, changed)
        self.assert_audit_fails()

    def test_05_real_row_coverage_and_rendered_visibility(self) -> None:
        original = self.read_registry()
        row = next(line for line in original.splitlines() if line.startswith("| H-placement agreement |"))
        for label, mutated in (
            ("removed", original.replace(row + "\n", "")),
            ("added", original.replace(row, row + "\n| New live row | value | oracle | `[benchmark]` |")),
            ("duplicate", original.replace(row, row + "\n" + row)),
            ("duplicate-section", original + "\n## 3. Duplicate live section\n"),
            ("wrong-section", original.replace("## 4.", "## 6.")),
        ):
            with self.subTest(mutation=label):
                write(self.root, REGISTRY, mutated)
                self.assert_audit_fails()
        hidden = (
            "```markdown\n## 3. Fenced example\n| Hidden | x | x | `[benchmark]` |\n```\n\n"
            "~~~\n## 4. Tilde-fenced example\n| Hidden | x | x | `[benchmark]` |\n~~~\n\n"
            "<!--\n## 3. Comment example\n| Hidden | x | x | `[benchmark]` |\n-->\n\n"
            "    ## 4. Indented code example\n    | Hidden | x | x | `[benchmark]` |\n\n"
        )
        write(self.root, REGISTRY, hidden + original)
        self.assertEqual(guard.registry_rows(hidden + original), guard.registry_rows(original))
        self.assertEqual(guard.audit(self.root), [])
        # Without a real rendered header/separator, pipe-looking prose is not a table.
        malformed = original.replace("|---|---|---|---|", "not a table separator", 1)
        self.assertFalse(any(section == 3 for section, _ in guard.registry_rows(malformed)))
        write(self.root, REGISTRY, malformed)
        self.assert_audit_fails()

    def test_06_escaped_first_cell_and_unescaped_body_pipes(self) -> None:
        rows = guard.registry_rows(self.read_registry())
        self.assertEqual(len(rows), 4)
        key = (3, "L-test ⟨|L|⟩")
        self.assertIn(key, rows)
        self.assertIn("Compare |Δ| and |Z|", rows[key])
        self.assertEqual(sha256(rows[key]), self.ledger["rows"][2]["row_sha256"])

    def test_07_row_tag_evidence_and_anchor_drift_fail_without_repair(self) -> None:
        mutations = (
            "row-byte", "tag", "evidence-byte", "missing-anchor", "wrong-anchor",
            "self-anchor", "self-hash", "self-scope", "external-row-scope",
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                self.reset_fixture()
                if mutation == "row-byte":
                    write(self.root, REGISTRY, self.read_registry().replace("Compare |Δ|", "Compare  |Δ|", 1))
                elif mutation == "tag":
                    write(self.root, REGISTRY, self.read_registry().replace("[benchmark — historical denominator unproven]", "[literature]", 1))
                elif mutation == "evidence-byte":
                    write(self.root, EVIDENCE_PATH, EVIDENCE + "\nA changed retained observation.\n")
                else:
                    changed = deepcopy(self.ledger)
                    reference = changed["rows"][-1 if mutation.startswith("self-") else 0]["evidence_refs"][0]
                    if mutation == "missing-anchor":
                        del reference["anchor"]
                    elif mutation in ("self-hash", "self-scope"):
                        reference["sha256"] = sha256(self.read_registry())
                        if mutation == "self-scope":
                            reference["hash_scope"] = "full_file"
                    elif mutation == "external-row-scope":
                        reference["hash_scope"] = "registry_row"
                    else:
                        reference["anchor"] = "## Results" if mutation == "self-anchor" else "## Absent results"
                    dump_ledger(self.root, changed)
                before = {p: (self.root / p).read_bytes() for p in (LEDGER, REGISTRY, EVIDENCE_PATH)}
                self.assert_audit_fails()
                self.assertEqual(before, {p: (self.root / p).read_bytes() for p in before})

    def test_08_row_order_and_outside_whitespace_are_not_identity(self) -> None:
        original = self.read_registry()
        first, second = [line for line in original.splitlines() if line.startswith(("| Secondary-structure", "| H-placement"))]
        changed = original.replace(first + "\n" + second, second + "\n" + first)
        changed = "\n\n" + changed.replace("## 4.", "\n\n## 4.")
        self.assertEqual(guard.registry_rows(changed), guard.registry_rows(original))
        write(self.root, REGISTRY, changed)
        self.assertEqual(guard.audit(self.root), [])
        reordered = deepcopy(self.ledger)
        reordered["rows"].reverse()
        for row in reordered["rows"]:
            row["components"].reverse()
        self.assertEqual(guard.recount(reordered), guard.recount(self.ledger))
        self.assertEqual(guard.summary(reordered), guard.summary(self.ledger))
        relabelled = changed.replace("| H-placement agreement |", "| H-placement renamed |")
        write(self.root, REGISTRY, relabelled)
        self.assert_audit_fails()

    def test_09_strict_shapes_keys_enums_paths_and_ids(self) -> None:
        def changes():
            for location in ((), ("rows", 0), ("rows", 0, "components", 0), ("rows", 0, "evidence_refs", 0)):
                yield f"unknown field at {location}", location, "unknown_field", True
            yield "policy enum", ("rows", 0, "components", 0), "policy_state", "fully_backed"
            yield "evidence enum", ("rows", 0, "components", 0), "evidence_state", "proved"
            yield "history enum", ("rows", 0), "historical_inventory_class", "currently_backed"
            yield "status enum", (), "status", "scientifically_certified"
            yield "empty scope", ("rows", 0, "components", 0), "scope", "  "
            yield "missing evidence", ("rows", 0), "evidence_refs", []
            yield "hash", ("rows", 0), "row_sha256", "not-sha256"
            yield "evidence hash", ("rows", 0, "evidence_refs", 0), "sha256", "z" * 64
            yield "hash scope", ("rows", 0, "evidence_refs", 0), "hash_scope", "unhashed"
            yield "date", (), "as_of_date", "2026-02-30"
            yield "rows shape", (), "rows", {}
            yield "components shape", ("rows", 0), "components", "not-a-list"
            yield "components empty", ("rows", 0), "components", []
            yield "duplicate row id", ("rows", 1), "id", self.ledger["rows"][0]["id"]
            yield "duplicate component id", ("rows", 1, "components", 1), "id", "flip_conflict"
            yield "wrong source", (), "source", "ref/not_the_registry.md"
            yield "wrong scope sections", (), "inventory_sections", [3, 4, 5]
        for name, location, key, value in changes():
            with self.subTest(mutation=name):
                changed = deepcopy(self.ledger)
                target = changed
                for part in location:
                    target = target[part]
                target[key] = value
                dump_ledger(self.root, changed)
                with self.assertRaises(ValueError):
                    guard.load_ledger(self.root / LEDGER)
                self.assert_audit_fails()
        duplicate_yaml = yaml.safe_dump(self.ledger, sort_keys=False, allow_unicode=True) + "format_version: 1\n"
        write(self.root, LEDGER, duplicate_yaml)
        with self.assertRaises(ValueError):
            guard.load_ledger(self.root / LEDGER)
        for path in ("../outside.md", "/outside.md", "ref/../../outside.md"):
            with self.subTest(outside_path=path):
                changed = deepcopy(self.ledger)
                changed["rows"][0]["evidence_refs"][0]["path"] = path
                dump_ledger(self.root, changed)
                self.assert_audit_fails()
        with tempfile.TemporaryDirectory(prefix="threshold-evidence-outside-", dir=self.root.parent) as outside_name:
            outside = Path(outside_name)
            write(outside, "evidence.md", EVIDENCE)
            (self.root / "ref/research/outside-link.md").symlink_to(outside / "evidence.md")
            changed = deepcopy(self.ledger)
            changed["rows"][0]["evidence_refs"][0]["path"] = "ref/research/outside-link.md"
            dump_ledger(self.root, changed)
            self.assert_audit_fails()

    def test_10_each_consumer_requires_one_exact_summary(self) -> None:
        for path in CONSUMERS:
            for mutation in ("missing", "duplicate", "stale", "fenced", "raw-html", "reversed"):
                with self.subTest(consumer=path, mutation=mutation):
                    self.reset_fixture()
                    text = (self.root / path).read_text(encoding="utf-8")
                    block = BEGIN + "\n" + guard.summary(self.ledger) + "\n" + END
                    self.assertIn(block, text)
                    replacement = {
                        "missing": "", "duplicate": block + "\n" + block,
                        "stale": BEGIN + "\nstale current summary\n" + END,
                        "fenced": "```markdown\n" + block + "\n```",
                        "raw-html": '<div style="display:none">\n' + block + "\n</div>",
                        "reversed": END + "\n" + guard.summary(self.ledger) + "\n" + BEGIN,
                    }[mutation]
                    write(self.root, path, text.replace(block, replacement))
                    self.assert_audit_fails()

    def test_11_components_partition_but_row_flags_overlap(self) -> None:
        counts = guard.recount(self.ledger)
        self.assertEqual(counts["component_count"], 10)
        self.assertEqual(sum(counts["policy_counts"].values()), 10)
        self.assertEqual(sum(counts["evidence_counts"].values()), 10)
        self.assertEqual(counts["row_count"], 4)
        for flag in ("suspended", "active_conditional", "informational"):
            self.assertIn("h_placement", counts["row_flags"][flag])
        self.assertGreater(sum(len(rows) for rows in counts["row_flags"].values()), counts["row_count"])
        for flags in (counts["row_flags"], counts["evidence_row_flags"]):
            for identities in flags.values():
                self.assertEqual(identities, sorted(set(identities)))
        self.assertIn("components", guard.summary(self.ledger).lower())
        self.assertIn("historical", guard.summary(self.ledger).lower())

    def test_12_old_current_certification_cannot_replace_requalified_summary(self) -> None:
        for path in CONSUMERS:
            with self.subTest(consumer=path):
                self.reset_fixture()
                original = (self.root / path).read_text(encoding="utf-8")
                old_claim = "18 fully backed; 2 partial. Every resolvable partial record is resolved."
                write(self.root, path, original.replace(guard.summary(self.ledger), old_claim))
                self.assert_audit_fails()

    def test_13_active_unmeasured_and_suspended_remain_distinct(self) -> None:
        original = deepcopy(self.ledger)
        counts = guard.recount(self.ledger)
        self.assertEqual(counts["cross_counts"]["active_conditional/unmeasured"], 1)
        self.assertEqual(counts["cross_counts"]["suspended/producer_mismatch"], 1)
        self.assertIn("secondary_structure", counts["row_flags"]["active_conditional"])
        self.assertIn("secondary_structure", counts["evidence_row_flags"]["unmeasured"])
        self.assertEqual(self.ledger, original)
        self.assertEqual(guard.audit(self.root), [])
        # Metadata reports an existing policy; no grading engine is consulted.
        tree = ast.parse(Path(guard.__file__).read_text(encoding="utf-8"))
        modules = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        modules += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
        for name in filter(None, modules):
            self.assertFalse(name.startswith(("qds_emit", "check_pass_status", "gemmi", "cctbx", "mmtbx")), name)

    def test_14_check_mode_is_read_only_and_uses_no_external_execution(self) -> None:
        tracked = (LEDGER, REGISTRY, "NEXT_TASKS.md", EVIDENCE_PATH,
                   "ref/research/partial_record_triage.md")
        before = {path: (self.root / path).read_bytes() for path in tracked}
        with mock.patch("subprocess.run", side_effect=AssertionError("No external execution")), \
             mock.patch("subprocess.Popen", side_effect=AssertionError("No external execution")), \
             mock.patch.object(Path, "write_text", side_effect=AssertionError("Read-only audit")), \
             mock.patch.object(Path, "write_bytes", side_effect=AssertionError("Read-only audit")):
            self.assertEqual(guard.audit(self.root), [])
        self.assertEqual(before, {path: (self.root / path).read_bytes() for path in tracked})
        # Source/evidence bytes are observed, never automatically repaired.
        write(self.root, EVIDENCE_PATH, EVIDENCE + "Changed evidence.\n")
        before_failure = {path: (self.root / path).read_bytes() for path in tracked}
        self.assert_audit_fails()
        self.assertEqual(before_failure, {path: (self.root / path).read_bytes() for path in tracked})


    def test_15_historical_qualifiers_cannot_be_removed_or_hidden(self) -> None:
        for path, qualifiers in guard.HISTORICAL_QUALIFIERS.items():
            for qualifier in qualifiers:
                for mutation in ("removed", "current", "fenced", "commented", "indented", "duplicate"):
                    with self.subTest(consumer=path, qualifier=qualifier, mutation=mutation):
                        self.reset_fixture()
                        text = (self.root / path).read_text()
                        replacement = {
                            "removed": "",
                            "current": "**Where the registry currently stands.**",
                            "fenced": "```markdown\n" + qualifier + "\n```",
                            "commented": "<!--\n" + qualifier + "\n-->",
                            "indented": "    " + qualifier,
                            "duplicate": qualifier + "\n" + qualifier,
                        }[mutation]
                        mutated = text.replace(qualifier, replacement, 1)
                        write(self.root, path, mutated)
                        # The generated count block itself has not changed (#836).
                        if path in CONSUMERS:
                            self.assertIsNone(guard._consumer_error(mutated, guard.summary(self.ledger), path))
                        errors = self.assert_audit_fails()
                        self.assertTrue(any("historical qualifier" in error for error in errors), errors)

    def test_16_adoption_changes_policy_not_evidence_or_other_calibrations(self) -> None:
        rows = {row["id"]: row for row in self.published["rows"]}
        scoped = {row["id"]: {c["id"]: c for c in row["components"]} for row in rows.values()}
        for identity in ("favored_percent", "outlier_percent"):
            self.assertEqual(scoped[identity]["shared_classification"]["policy_state"], "active_conditional")
            self.assertEqual(scoped[identity]["shared_classification"]["evidence_state"], "retained_record")
            self.assertIn("criterion binding", scoped[identity]["shared_classification"]["limitations"])
            self.assertTrue(any(ref["path"].endswith("t05_classification_floor_adoption_2026-09-27.md")
                                for ref in rows[identity]["evidence_refs"]))
        self.assertEqual(scoped["favored_percent"]["rotamer_favored"]["policy_state"], "policy_unresolved")
        for identity in ("dockq", "nmr_precision"):
            self.assertEqual(scoped[identity]["numeric_tolerance"]["evidence_state"], "unmeasured")
        self.assertEqual(scoped["secondary_structure"]["two_assigner_expectation"]["evidence_state"],
                         "denominator_unproven")
        self.assertEqual(scoped["h_placement"]["flip_conflict"]["policy_state"], "suspended")
        counts = guard.recount(self.published)
        self.assertEqual(counts["policy_counts"]["active_conditional"], 29)
        self.assertEqual(counts["policy_counts"]["policy_unresolved"], 1)
        self.assertEqual(counts["row_flags"]["policy_unresolved"], ["favored_percent"])


if __name__ == "__main__":
    unittest.main()
