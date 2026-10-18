#!/usr/bin/env python3
"""Regression tests for ProSMART capability and assumption records (#911)."""
from __future__ import annotations

import pathlib
import sys
import unittest

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_referential_integrity  # noqa: E402
from protstruct_review.models import Container  # noqa: E402
import qds_emit  # noqa: E402
import qds_emit_contract_v1  # noqa: E402

HISTORICAL_RAMA_Z_PREDECESSOR = {
    "id": "REC_T05_rama_z_score_top_performing",
    "metric_definition_ref": "T05_rama_z_score",
    "tool_ref": "ProSMART",
    "role": "top_performing",
    "rank": 1,
    "justification": (
        "ProSMART (CCP4 stack, Murshudov-group code path) computes a non-cctbx "
        "per-residue Ramachandran-Z score — exactly this metric — giving an "
        "independent second reading on Ramachandran-Z alongside the wwPDB "
        "pipeline. Relocated here from the Ramachandran/rotamer outlier-percentage "
        "metrics, which ProSMART does not classify."
    ),
    "evidence_refs": ["Nicholls2014"],
    "as_of_date": "2026-07-22",
    "effective_at": "2026-07-22T00:00:00+00:00",
}

HISTORICAL_ASSUM_REFERENCE_DEPENDENT = {
    "id": "ASSUM_prosmart_reference_dependent",
    "as_of_date": "2026-04-30",
    "effective_at": "2026-04-30T00:00:00+00:00",
    "kind": "explicit",
    "scope": "tool",
    "title": "ProSMART analysis is reference-dependent",
    "description": (
        "ProSMART computes per-residue scores AGAINST a reference "
        "structure (typically the deposited model or a high-resolution "
        "comparator). Choosing a different reference changes every "
        "score. There is no \"absolute\" ProSMART number for a structure."
    ),
    "consequences": (
        "A ProSMART Rama-Z of 1.2 vs reference X is not the same number "
        "as 1.2 vs reference Y. Reports must always quote the reference."
    ),
    "mitigation": (
        "Pin the reference per evaluation. For agentic refinement vs "
        "starting model, use the agent's input model as the reference. "
        "For absolute geometry analysis, use Top8000 (when available "
        "via ProSMART's data files) or compare to a high-resolution "
        "family member."
    ),
    "status": "mitigated",
    "tool_ref": "ProSMART",
}

HISTORICAL_ASSUM_NO_TOP8000 = {
    "id": "ASSUM_prosmart_no_top8000_default",
    "as_of_date": "2026-04-30",
    "effective_at": "2026-04-30T00:00:00+00:00",
    "kind": "implicit",
    "scope": "tool",
    "title": "ProSMART needs an explicit reference; no Top8000 default",
    "description": (
        "Unlike MolProbity (which has Top8000 baked in), ProSMART's "
        "Rama-Z analysis requires the user to supply a reference. The "
        "tool ships with template-based options but no single default."
    ),
    "consequences": (
        "Running ProSMART without specifying a reference gives a "
        "meaningless score; misconfigured runs can pass silently."
    ),
    "mitigation": "Always specify the reference structure on the command line.",
    "status": "unchecked",
    "tool_ref": "ProSMART",
}

QDS_EMIT_MODULES = (
    qds_emit,
    qds_emit_contract_v1,
)


def _eval_with_rama_z_and_prosmart() -> list[dict[str, object]]:
    return [
        {
            "id": "EVAL_test_prosmart_911",
            "measurements": [
                {
                    "id": "EVAL_test_prosmart_911_M_rama_z",
                    "metric_definition_ref": "T05_rama_z_score",
                    "oracle_tool_ref": "wwPDB validation pipeline",
                },
                {
                    "id": "EVAL_test_prosmart_911_M_prosmart_t02",
                    "metric_definition_ref": "T02_per-residue_cα_distance",
                    "oracle_tool_ref": "ProSMART",
                },
            ],
        }
    ]


class ProsmartCapabilityRecommendationsTests(unittest.TestCase):
    def test_predecessor_registry_rows_preserved_byte_for_byte(self) -> None:
        rec_doc = yaml.safe_load(
            (REPO_ROOT / "ref" / "tool_recommendations.yaml").read_text(
                encoding="utf-8"
            )
        )
        Container.model_validate(rec_doc)
        rec_by_id = {row["id"]: row for row in rec_doc["tool_recommendations"]}
        self.assertEqual(
            rec_by_id["REC_T05_rama_z_score_top_performing"],
            HISTORICAL_RAMA_Z_PREDECESSOR,
        )
        self.assertEqual(
            rec_by_id["REC_T05_rama_z_score_top_considered"]["tool_ref"],
            "wwPDB validation pipeline",
        )
        self.assertEqual(
            rec_by_id["REC_T05_rama_z_score_top_considered"]["role"],
            "top_considered",
        )

        assum_doc = yaml.safe_load(
            (REPO_ROOT / "ref" / "tool_assumptions.yaml").read_text(encoding="utf-8")
        )
        Container.model_validate(assum_doc)
        assum_by_id = {row["id"]: row for row in assum_doc["assumptions"]}
        self.assertEqual(
            assum_by_id["ASSUM_prosmart_reference_dependent"],
            HISTORICAL_ASSUM_REFERENCE_DEPENDENT,
        )
        self.assertEqual(
            assum_by_id["ASSUM_prosmart_no_top8000_default"],
            HISTORICAL_ASSUM_NO_TOP8000,
        )

    def test_current_rama_z_recommendation_deprecates_prosmart(self) -> None:
        eval_runs = _eval_with_rama_z_and_prosmart()
        for module in QDS_EMIT_MODULES:
            with self.subTest(module=module.__name__):
                applied = module.build_tool_recommendations_applied(
                    eval_runs,
                    issued_at="2026-10-18T12:00:00+00:00",
                )
                rama_z_rows = [
                    row
                    for row in applied
                    if row["metric_definition_ref"] == "T05_rama_z_score"
                ]
                by_id = {row["id"]: row for row in rama_z_rows}
                self.assertIn("REC_T05_rama_z_score_top_considered", by_id)
                self.assertIn(
                    "REC_T05_rama_z_score_top_performing_2026_10_18_capability_correction",
                    by_id,
                )
                self.assertNotIn("REC_T05_rama_z_score_top_performing", by_id)

                corr = by_id[
                    "REC_T05_rama_z_score_top_performing_2026_10_18_capability_correction"
                ]
                self.assertEqual(corr["tool_ref"], "ProSMART")
                self.assertEqual(corr["role"], "deprecated")
                self.assertIsNone(corr.get("rank"))
                self.assertEqual(corr["as_of_date"], "2026-10-18")
                self.assertEqual(corr["effective_at"], "2026-10-18T00:00:00+00:00")
                self.assertEqual(
                    corr["supersedes_recommendation_ref"],
                    "REC_T05_rama_z_score_top_performing",
                )
                for ref in (
                    "Nicholls2014",
                    "EVAL_1sar_cdba2c07_2026-09-23",
                    "ref/research/prosmart_rama_z_correction_2026-10-18.md",
                ):
                    self.assertIn(ref, corr["evidence_refs"])

                active_prosmart_rama_z = [
                    row
                    for row in rama_z_rows
                    if row["tool_ref"] == "ProSMART"
                    and row["role"] in {"top_considered", "top_performing", "alternative"}
                ]
                self.assertEqual(active_prosmart_rama_z, [])

    def test_historical_rama_z_cutoffs_remain_reproducible(self) -> None:
        eval_runs = _eval_with_rama_z_and_prosmart()
        for cutoff in (
            "2026-07-22T00:00:00+00:00",
            "2026-09-23T09:00:00+00:00",
            "2026-10-17T23:59:59+00:00",
        ):
            for module in QDS_EMIT_MODULES:
                with self.subTest(cutoff=cutoff, module=module.__name__):
                    applied = {
                        row["id"]: row
                        for row in module.build_tool_recommendations_applied(
                            eval_runs,
                            issued_at=cutoff,
                        )
                    }
                    self.assertIn("REC_T05_rama_z_score_top_performing", applied)
                    self.assertNotIn(
                        "REC_T05_rama_z_score_top_performing_2026_10_18_capability_correction",
                        applied,
                    )
                    self.assertEqual(
                        applied["REC_T05_rama_z_score_top_performing"],
                        HISTORICAL_RAMA_Z_PREDECESSOR,
                    )

    def test_current_prosmart_assumptions_supersede_rama_z_claims(self) -> None:
        eval_runs = _eval_with_rama_z_and_prosmart()
        for module in QDS_EMIT_MODULES:
            with self.subTest(module=module.__name__):
                assumptions = {
                    row["id"]: row
                    for row in module.build_assumptions_report(
                        eval_runs,
                        issued_at="2026-10-18T12:00:00+00:00",
                    )
                }
                self.assertIn("ASSUM_prosmart_reference_dependent_2026_10_18", assumptions)
                self.assertIn("ASSUM_prosmart_no_top8000_default_2026_10_18", assumptions)
                self.assertNotIn("ASSUM_prosmart_reference_dependent", assumptions)
                self.assertNotIn("ASSUM_prosmart_no_top8000_default", assumptions)

                ref_dep = assumptions["ASSUM_prosmart_reference_dependent_2026_10_18"]
                self.assertEqual(ref_dep["tool_ref"], "ProSMART")
                self.assertEqual(ref_dep["as_of_date"], "2026-10-18")
                self.assertEqual(ref_dep["effective_at"], "2026-10-18T00:00:00+00:00")
                self.assertEqual(
                    ref_dep["supersedes_assumption_ref"],
                    "ASSUM_prosmart_reference_dependent",
                )
                self.assertIn("Procrustes", ref_dep["description"])
                self.assertIn("no reference-free", ref_dep["description"])

                no_top8000 = assumptions["ASSUM_prosmart_no_top8000_default_2026_10_18"]
                self.assertEqual(no_top8000["tool_ref"], "ProSMART")
                self.assertEqual(no_top8000["as_of_date"], "2026-10-18")
                self.assertEqual(no_top8000["effective_at"], "2026-10-18T00:00:00+00:00")
                self.assertEqual(
                    no_top8000["supersedes_assumption_ref"],
                    "ASSUM_prosmart_no_top8000_default",
                )
                self.assertIn(
                    "does not evaluate single-model Ramachandran contours",
                    no_top8000["description"],
                )

    def test_historical_prosmart_assumptions_remain_reproducible(self) -> None:
        eval_runs = _eval_with_rama_z_and_prosmart()
        for cutoff in (
            "2026-04-30T00:00:00+00:00",
            "2026-05-01T01:44:22-07:00",
            "2026-05-04T09:00:00+00:00",
            "2026-05-05T09:00:00+00:00",
            "2026-09-23T09:00:00+00:00",
            "2026-10-17T23:59:59+00:00",
        ):
            for module in QDS_EMIT_MODULES:
                with self.subTest(cutoff=cutoff, module=module.__name__):
                    assumptions = {
                        row["id"]: row
                        for row in module.build_assumptions_report(
                            eval_runs,
                            issued_at=cutoff,
                        )
                    }
                    self.assertIn("ASSUM_prosmart_reference_dependent", assumptions)
                    self.assertIn("ASSUM_prosmart_no_top8000_default", assumptions)
                    self.assertNotIn(
                        "ASSUM_prosmart_reference_dependent_2026_10_18",
                        assumptions,
                    )
                    self.assertNotIn(
                        "ASSUM_prosmart_no_top8000_default_2026_10_18",
                        assumptions,
                    )

    def test_catalog_and_docs_keep_prosmart_out_of_active_t05_oracles(self) -> None:
        catalog = yaml.safe_load(
            (REPO_ROOT / "ref" / "catalog.yaml").read_text(encoding="utf-8")
        )
        Container.model_validate(catalog)
        tasks = {row["id"]: row for row in catalog["catalog_tasks"]}
        tools = {row["id"]: row for row in catalog["tools"]}

        self.assertIn("ProSMART", tasks["T02"]["oracle_tool_refs"])
        self.assertNotIn("ProSMART", tasks["T01"]["oracle_tool_refs"])
        self.assertNotIn("ProSMART", tasks["T05"]["oracle_tool_refs"])
        self.assertIn("ProSMART", tools)
        # Historical 2026-04-24 1SAR row M_prosmart_asn_a39_score references T05;
        # tools entry preserves historical tool_ref/task resolution while active
        # task oracle_tool_refs keep ProSMART on T02 only.
        self.assertIn("T02", tools["ProSMART"]["catalog_tasks_served"])

        oracle_tools = (REPO_ROOT / "ref" / "oracle_tools.md").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "not a Ramachandran outlier classifier or `T05_rama_z_score` producer",
            oracle_tools,
        )
        self.assertIn(
            "ProSMART is comparative `T02`, not a Ramachandran classifier or `T05_rama_z_score` producer",
            oracle_tools,
        )

        correction_note = (
            REPO_ROOT
            / "ref"
            / "research"
            / "prosmart_rama_z_correction_2026-10-18.md"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "REC_T05_rama_z_score_top_performing_2026_10_18_capability_correction",
            correction_note,
        )
        self.assertIn("ASSUM_prosmart_reference_dependent_2026_10_18", correction_note)
        self.assertIn("ASSUM_prosmart_no_top8000_default_2026_10_18", correction_note)
        self.assertIn("EVAL_1sar_cdba2c07_2026-09-23_CORR_SCALAR_062", correction_note)
        self.assertEqual(check_referential_integrity.main(), 0)

    def test_microsecond_activation_boundary(self) -> None:
        eval_runs = _eval_with_rama_z_and_prosmart()
        before = "2026-10-17T23:59:59.999999+00:00"
        exact = "2026-10-18T00:00:00+00:00"
        for module in QDS_EMIT_MODULES:
            with self.subTest(module=module.__name__):
                recs_before = {
                    r["id"]
                    for r in module.build_tool_recommendations_applied(
                        eval_runs, issued_at=before
                    )
                }
                recs_exact = {
                    r["id"]
                    for r in module.build_tool_recommendations_applied(
                        eval_runs, issued_at=exact
                    )
                }
                self.assertIn("REC_T05_rama_z_score_top_performing", recs_before)
                self.assertNotIn(
                    "REC_T05_rama_z_score_top_performing_2026_10_18_capability_correction",
                    recs_before,
                )
                self.assertNotIn("REC_T05_rama_z_score_top_performing", recs_exact)
                self.assertIn(
                    "REC_T05_rama_z_score_top_performing_2026_10_18_capability_correction",
                    recs_exact,
                )

                assum_before = {
                    a["id"]
                    for a in module.build_assumptions_report(
                        eval_runs, issued_at=before
                    )
                }
                assum_exact = {
                    a["id"]
                    for a in module.build_assumptions_report(
                        eval_runs, issued_at=exact
                    )
                }
                self.assertIn("ASSUM_prosmart_reference_dependent", assum_before)
                self.assertIn("ASSUM_prosmart_no_top8000_default", assum_before)
                self.assertNotIn(
                    "ASSUM_prosmart_reference_dependent_2026_10_18", assum_before
                )
                self.assertNotIn(
                    "ASSUM_prosmart_no_top8000_default_2026_10_18", assum_before
                )
                self.assertNotIn("ASSUM_prosmart_reference_dependent", assum_exact)
                self.assertNotIn("ASSUM_prosmart_no_top8000_default", assum_exact)
                self.assertIn(
                    "ASSUM_prosmart_reference_dependent_2026_10_18", assum_exact
                )
                self.assertIn(
                    "ASSUM_prosmart_no_top8000_default_2026_10_18", assum_exact
                )


if __name__ == "__main__":
    unittest.main()
