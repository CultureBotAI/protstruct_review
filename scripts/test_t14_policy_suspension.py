"""Historical producer/recount and current policy prose checks for #809."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml

import bench_t14_flip_sets as bench
import recount_t14_flip_history as history

REPO = Path(__file__).resolve().parent.parent
METRIC = "T14_asn_gln_his_flip_set_conflicts"


class T14PolicySuspensionTests(unittest.TestCase):
    def test_collect_distinguishes_the_actual_historical_producer(self):
        phx = {("A", 1, "ASN"): (True, "F"), ("A", 2, "GLN"): (False, "K")}
        std = {("A", 1, "ASN"): (False, "K")}
        reduce2 = {("A", 1, "ASN"): (False, "K"), ("A", 2, "GLN"): (False, "K")}
        with patch.object(bench, "fetch", return_value=Path("input.pdb")), \
                patch.object(bench, "build", side_effect=lambda model, cache, phenix: Path("phenix.pdb" if phenix else "standalone.pdb")), \
                patch.object(bench, "hydrogen_count", return_value=10), \
                patch.object(bench, "het_components", return_value=set()), \
                patch.object(bench, "flip_calls", side_effect=lambda path: phx if path.stem == "phenix" else std), \
                patch.object(bench, "reduce2_flip_calls", return_value=reduce2), \
                contextlib.redirect_stderr(io.StringIO()):
            rows, skipped = bench.collect(["TEST"], Path("unused-cache"))
        self.assertEqual(skipped, [])
        self.assertEqual(rows[0]["n_reduce2_shared"], 2)
        self.assertEqual(rows[0]["n_reduce2_decision_disagreements"], 1)
        self.assertEqual(rows[0]["n_reduce2_confident_conflicts"], 1)
        self.assertEqual(rows[0]["n_shared"], 1)
        self.assertEqual(bench.confident_conflicts(std, reduce2), [])

    def test_recount_ignores_the_stored_summary(self):
        result = history.recount()
        self.assertEqual((result["models"], result["confident_conflicts"], result["raw_disagreements"], result["eligible_shared_residues"]),
                         (41, 56, 340, 3105))
        self.assertEqual(result["record_sha256"], "862eb423eb5b01389d92f76fdfd3cf8e46a6f8f6b80f862e777fbf8a0b6a8344")
        self.assertEqual(result["maximum_absolute_h_count_gap_percent"][0], "3MIU")
        self.assertAlmostEqual(result["maximum_absolute_h_count_gap_percent"][1], 6.779661016949152)
        document = json.loads(history.RECORD.read_text())
        document["summary"] = {"invented": "not consulted"}
        with tempfile.TemporaryDirectory(prefix="t14-recount-") as temporary:
            path = Path(temporary) / "record.json"
            path.write_text(json.dumps(document))
            changed = history.recount(path)
            result.pop("record_sha256")
            changed.pop("record_sha256")
            self.assertEqual(result, changed)
            document["rows"][0]["n_reduce2_confident_conflicts"] += 1
            path.write_text(json.dumps(document))
            with self.assertRaisesRegex(ValueError, "count/list mismatch"):
                history.recount(path)

    def test_current_registry_driver_and_catalog_suspend_all_scopes(self):
        registry = (REPO / "ref/thresholds_and_standards.md").read_text()
        row = next(line for line in registry.splitlines() if line.startswith("| H-placement agreement |"))
        flip = row.split("**H-count check:**", 1)[0]
        self.assertIn("**Flip-conflict grading suspended (#809):**", flip)
        self.assertIn("all scopes are informational and criterion-free", flip)
        self.assertIn("PHENIX-distributed", flip)
        self.assertIn("both producers are catalogued cctbx-family", flip)
        catalog = yaml.safe_load((REPO / "ref/catalog.yaml").read_text())
        task = next(item for item in catalog["catalog_tasks"] if item["id"] == "T14")
        metric = next(item for item in catalog["metric_definitions"] if item["id"] == METRIC)
        for text in (task["gold_standard"], metric["description"]):
            self.assertIn("all scopes are informational and criterion-free", text)
        driver = (REPO / "ref/driving_example_T14.md").read_text().split("2. **Confident flip-set", 1)[1].split("3. **Clashscore", 1)[0]
        self.assertIn("No scope may use the historical cohort band", driver)
        self.assertIn("informational and criterion-free", driver)

    def test_flip_recommendation_is_append_only_and_separate_from_clashscore(self):
        rows = yaml.safe_load((REPO / "ref/tool_recommendations.yaml").read_text())["tool_recommendations"]
        predecessor = "REC_T14_asn_gln_his_flip_set_conflicts_top_considered_2026_09_22"
        successors = [row for row in rows if row.get("supersedes_recommendation_ref") == predecessor]
        self.assertEqual(len(successors), 1)
        self.assertEqual(successors[0]["metric_definition_ref"], METRIC)
        self.assertIn("all scopes are informational and criterion-free", successors[0]["justification"])
        old = next(row for row in rows if row["id"] == predecessor)
        self.assertEqual(str(old["as_of_date"]), "2026-09-22")
        self.assertNotIn("suspended", old["justification"])

    def test_historical_prose_has_visible_dated_corrections(self):
        for round_number in (47, 48):
            for suffix in ("", "_preregistration"):
                path = REPO / f"ref/research/tolerance_benchmark_round{round_number}{suffix}.md"
                text = path.read_text()
                self.assertIn("Current status (2026-09-27, #809)", text[:400])
                self.assertIn("## Producer attribution and grading correction (2026-09-27, #809)", text)
                self.assertIn("not the\n> claimed standalone pair", text)

    def test_live_producer_documentation_and_earliest_report_do_not_grade(self):
        self.assertIn("both are catalogued cctbx-family", bench.reduce2_flip_calls.__doc__)
        self.assertIn("does not establish\n    independent corroboration", bench.reduce2_flip_calls.__doc__)
        self.assertIn("grading is suspended", bench.confident_conflicts.__doc__)
        text = (REPO / "ref/research/tolerance_benchmark_flip_sets.md").read_text()
        self.assertIn("Current status (2026-09-27, #809/#824)", text[:500])
        self.assertIn("historical Applied block below is not a", text[:800])
        self.assertIn("Original numbers remain historical", text[:800])


if __name__ == "__main__":
    unittest.main()
