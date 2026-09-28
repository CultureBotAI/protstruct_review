#!/usr/bin/env python3
"""#798: version applicability is explicit in both rows and every live consumer.

Hermetic text/YAML tests only. No scientific executables or historical reruns.
The sidecar is guard data; the threshold itself remains in the Markdown registry.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
from pathlib import Path
import re
import unittest

import yaml

import check_driver_thresholds as guard

REPO = Path(__file__).resolve().parent.parent
METRICS = (
    "Clashscore benchmarked versions (§3)",
    "Clashscore benchmarked versions, H-placement row (§3)",
)
CAVEAT = "Matching versions alone does not validate changed H-build settings (#799/#790)."
SUCCESSOR = "REC_T14_clashscore_delta_pre_vs_post_top_considered_2026_09_27_version_pin"
PREDECESSOR = "REC_T14_clashscore_delta_pre_vs_post_top_considered_2026_09_27"


def normalize(text: str) -> str:
    return " ".join(text.split())


def rubric(text: str, heading: str) -> str:
    """Select one actual rubric block, not unrelated versions in the same file."""
    start = text.index(heading)
    tail = text[start:]
    end = re.search(r"\n(?:\d+\. |## )", tail)
    return tail[:end.start()] if end else tail


def policy_errors(text: str, policy: str) -> list[str]:
    normalized = normalize(text)
    errors = []
    if policy not in normalized:
        errors.append("missing exact version pin or informational fallback")
    if CAVEAT not in normalized:
        errors.append("missing necessary-not-sufficient H-build caveat")
    return errors


def contexts(root: Path) -> dict[str, str]:
    """Read only the clauses that actually carry clashscore applicability."""
    read = lambda path: (root / path).read_text()
    registry = read("ref/thresholds_and_standards.md")
    rows = registry.splitlines()
    clash = next(row for row in rows if row.startswith("| Clashscore |"))
    h_placement = next(row for row in rows if row.startswith("| H-placement agreement |"))
    method = registry.split("> - **Clashscore**", 1)[1].split("\n\n", 1)[0]
    out = {
        "registry Clashscore": clash,
        "registry H-placement clashscore": h_placement.split("**Clashscore check:**", 1)[1],
        "registry method-dependence": method.replace("\n>", "\n"),
    }
    headings = {
        "ref/driving_example.md": "7. **MolProbity ≈ PHENIX.**",
        "ref/driving_example_T03.md": "4. **Geometry did not degrade.**",
        "ref/driving_example_T04.md": "4. **Geometry did not degrade.**",
        "ref/driving_example_T05.md": "2. **Clashscore agreement.**",
        "ref/driving_example_T11.md": "2. **Loop geometry is clean.**",
        "ref/driving_example_T14.md": "3. **Clashscore agreement.**",
    }
    for path, heading in headings.items():
        out[path] = rubric(read(path), heading)
    catalog = yaml.safe_load(read("ref/catalog.yaml"))
    task = next(row for row in catalog["catalog_tasks"] if row["id"] == "T14")
    out["catalog T14 gold_standard"] = task["gold_standard"].split(
        "clashscore comparison", 1
    )[1]
    criteria = yaml.safe_load(read("ref/structural_criteria.yaml"))
    clash_criterion = next(row for row in criteria["criteria"] if row["id"] == "T05_clashscore")
    out["structural criterion precondition"] = clash_criterion["cross_tool_agreement"]["precondition"]
    task_md = read("ref/tasks_and_evaluations.md").split(
        "### T14 —", 1
    )[1].split("\n### ", 1)[0]
    out["task Markdown clashscore"] = task_md.split(
        "Apply the registered clashscore envelope", 1
    )[1].split("A neutron structure", 1)[0]
    task_tsv = next(
        row for row in csv.DictReader(io.StringIO(read("ref/tasks_and_evaluations.tsv")), delimiter="\t")
        if row["id"] == "T14"
    )
    out["task TSV clashscore"] = task_tsv["gold_standard"].split(
        "clashscore comparison", 1
    )[1]
    recommendations = yaml.safe_load(read("ref/tool_recommendations.yaml"))["tool_recommendations"]
    successor = next(row for row in recommendations if row["id"] == SUCCESSOR)
    out["active T14 recommendation"] = successor["justification"]
    out["dated benchmark clarification"] = read(
        "ref/research/tolerance_benchmark_clashscore_h.md"
    ).split("## Version applicability clarification (2026-09-27, #798)", 1)[1]
    return out


class ClashscoreVersionPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = guard.CHECKS_BY_METRIC[METRICS[0]]["current"]
        self.registry = (REPO / "ref/thresholds_and_standards.md").read_text()

    def test_each_registry_cell_has_the_same_complete_policy(self) -> None:
        for metric in METRICS:
            with self.subTest(metric=metric):
                entry = guard.CHECKS_BY_METRIC[metric]
                self.assertEqual(entry["current"], self.policy)
                self.assertEqual(guard.registry_value(entry["registry"], self.registry), self.policy)

    def test_each_pin_and_fallback_is_load_bearing_in_each_cell(self) -> None:
        replacements = (
            ("PHENIX 2.0-5936", "PHENIX 9.9-9999"),
            ("Richardson reduce 4.16.250520", "Richardson reduce 9.99.999999"),
            ("standalone probe 2.26.021123", "standalone probe 9.99.999999"),
            ("(both builds)", "(standalone build only)"),
            ("Other or unverified versions are informational", "Other or unverified versions pass"),
            ("Other or unverified versions are informational", "Other or unverified versions fail"),
            ("Other or unverified versions are informational", "Other or unverified versions are void"),
            (self.policy, "Matching reduce versions qualify."),
        )
        for metric in METRICS:
            entry = guard.CHECKS_BY_METRIC[metric]
            row_label = "| Clashscore |" if metric == METRICS[0] else "| H-placement agreement |"
            row = next(line for line in self.registry.splitlines() if line.startswith(row_label))
            for old, new in replacements:
                with self.subTest(metric=metric, mutation=old, replacement=new):
                    changed_policy = self.policy.replace(old, new)
                    self.assertNotEqual(changed_policy, self.policy)
                    changed_row = row.replace(self.policy, changed_policy)
                    self.assertNotEqual(changed_row, row)
                    mutated = self.registry.replace(row, changed_row)
                    # The other correct row must not satisfy this cell's missing pin.
                    self.assertNotEqual(guard.registry_value(entry["registry"], mutated), self.policy)

    def test_live_consumers_have_scoped_positive_requirements(self) -> None:
        observed = contexts(REPO)
        self.assertEqual(len(observed), 15)
        for name, text in observed.items():
            with self.subTest(context=name):
                self.assertEqual(policy_errors(text, self.policy), [])

    def test_consumer_mutations_fail_without_borrowing_other_sections(self) -> None:
        for name, text in contexts(REPO).items():
            normalized = normalize(text)
            for old in (
                "PHENIX 2.0-5936",
                "Richardson reduce 4.16.250520",
                "standalone probe 2.26.021123",
                "(both builds)",
                "Other or unverified versions are informational",
                CAVEAT,
            ):
                with self.subTest(context=name, removed=old):
                    self.assertIn(old, normalized)
                    changed = normalized.replace(old, "", 1)
                    self.assertTrue(policy_errors(changed, self.policy))
        # Versions in another rubric are not part of the selected clashscore rule.
        bad_rule = "2. **Clashscore agreement.** Matching versions qualify.\n"
        unrelated = "3. **Unrelated check.** " + self.policy + " " + CAVEAT
        self.assertTrue(policy_errors(rubric(bad_rule + unrelated, "2. **Clashscore agreement.**"), self.policy))

    def test_catalog_view_is_regenerated_without_changing_its_meaning(self) -> None:
        catalog = yaml.safe_load((REPO / "ref/catalog.yaml").read_text())
        task = next(row for row in catalog["catalog_tasks"] if row["id"] == "T14")
        rows = csv.DictReader(
            io.StringIO((REPO / "ref/tasks_and_evaluations.tsv").read_text()), delimiter="\t"
        )
        tsv = next(row for row in rows if row["id"] == "T14")
        self.assertEqual(tsv["gold_standard"], task["gold_standard"])

    def test_recommendation_is_a_dated_successor(self) -> None:
        rows = yaml.safe_load((REPO / "ref/tool_recommendations.yaml").read_text())["tool_recommendations"]
        by_id = {row["id"]: row for row in rows}
        successor, predecessor = by_id[SUCCESSOR], by_id[PREDECESSOR]
        self.assertEqual(str(successor["as_of_date"]), "2026-09-27")
        self.assertEqual(successor["supersedes_recommendation_ref"], PREDECESSOR)
        self.assertGreater(
            dt.datetime.fromisoformat(str(successor["effective_at"])),
            dt.datetime.fromisoformat(str(predecessor["effective_at"])),
        )
        self.assertNotIn("Clashscore version pin:", predecessor["justification"])
        self.assertEqual(
            [row["id"] for row in rows if row.get("supersedes_recommendation_ref") == PREDECESSOR],
            [SUCCESSOR],
        )

    def test_clarification_does_not_claim_new_or_authenticated_science(self) -> None:
        text = contexts(REPO)["dated benchmark clarification"]
        self.assertIn("not a new scientific run", text)
        self.assertIn("not been independently authenticated", normalize(text))
        self.assertIn("does not certify the dictionary-loaded rerun", text)
        self.assertIn("causal-decomposition", text)


if __name__ == "__main__":
    unittest.main()
