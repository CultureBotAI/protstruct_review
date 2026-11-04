#!/usr/bin/env python3
"""Regression tests for scripts/assess_refinement.py and its generated outputs."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

import numpy as np
import yaml

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from assess_refinement import (  # noqa: E402
    DEFAULT_1SAR_COORD_AUDIT,
    DEFAULT_1SAR_QDS,
    DEFAULT_ARCHIVE,
    EXPECTED_1SAR_ARCHIVE_SHA256,
    REPO_ROOT,
    _median_and_iqr,
    assess_1sar_case_study,
    audit_mtz_retention,
    build_full_assessment_report,
    compare_pdb_pair,
    deposition_applicability,
    kabsch_rmsd,
    resolve_verdict_status,
    sha256_file,
    summarize_pdb_inventory,
)

ASSESSMENT_JSON_PATH = (
    REPO_ROOT
    / "ref"
    / "research"
    / "data"
    / "refinement_assessment_1sar_and_controls_2026-10-18.json"
)
CASE_STUDY_MD_PATH = (
    REPO_ROOT / "ref" / "research" / "refinement_assessment_case_study_2026-10-18.md"
)


class AssessRefinementTests(unittest.TestCase):
    """Test suite for before/after refinement assessment logic and artifacts."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.saved_report = json.loads(ASSESSMENT_JSON_PATH.read_text(encoding="utf-8"))
        with zipfile.ZipFile(DEFAULT_ARCHIVE, "r") as zf:
            cls.start_pdb_text = zf.read("data/1sar.pdb").decode("utf-8")
            cls.final_pdb_text = zf.read("data/1sar_final.pdb").decode("utf-8")
            cls.start_mtz_bytes = zf.read("data/1sar.mtz")
            cls.final_mtz_bytes = zf.read("data/1sar_final.mtz")

    def test_resolve_verdict_status_uncalibrated_and_bound(self) -> None:
        """Verify pass_criterion_bindings policy rejects unevaluated bindings and unknown statuses."""
        # Empty bindings unconditionally return 'informational' for valid or None requested_status
        self.assertEqual(resolve_verdict_status([], "pass"), "informational")
        self.assertEqual(resolve_verdict_status([], "fail"), "informational")
        self.assertEqual(resolve_verdict_status([], "NeedsReview"), "informational")
        self.assertEqual(resolve_verdict_status([], "informational"), "informational")
        self.assertEqual(resolve_verdict_status([], None), "informational")
        self.assertEqual(resolve_verdict_status(None, "pass"), "informational")

        # Unknown requested_status raises ValueError
        with self.assertRaises(ValueError):
            resolve_verdict_status([], "unknown")

        # Non-empty bindings raise ValueError until criterion evaluation is implemented
        bound = [{"metric": "r_free", "operator": "<=", "threshold": 0.25}]
        for status in ("pass", "fail", "NeedsReview", "informational", None, "unknown"):
            with self.assertRaises(ValueError):
                resolve_verdict_status(bound, status)

    def test_median_and_iqr_empty_and_unavailable_counts(self) -> None:
        """Verify _median_and_iqr handles empty lists safely and reports counts."""
        empty_summary = _median_and_iqr([], total_count=22)
        self.assertEqual(empty_summary["status"], "unavailable")
        self.assertEqual(empty_summary["count"], 0)
        self.assertEqual(empty_summary["unavailable_count"], 22)
        self.assertIsNone(empty_summary["median"])
        self.assertIsNone(empty_summary["p25"])
        self.assertIsNone(empty_summary["p75"])

        avail_summary = _median_and_iqr([1.0, 2.0, 3.0], total_count=5)
        self.assertEqual(avail_summary["status"], "available")
        self.assertEqual(avail_summary["count"], 3)
        self.assertEqual(avail_summary["unavailable_count"], 2)
        self.assertAlmostEqual(avail_summary["median"], 2.0, places=4)

    def test_archive_sha256_verification_and_corruption_rejection(self) -> None:
        """Verify assess_1sar_case_study computes and checks archive SHA-256."""
        self.assertEqual(sha256_file(DEFAULT_ARCHIVE), EXPECTED_1SAR_ARCHIVE_SHA256)
        self.assertEqual(
            self.saved_report["case_study_1sar"]["provenance"]["archive_sha256"],
            EXPECTED_1SAR_ARCHIVE_SHA256,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            bad_archive = Path(tmpdir) / "corrupted_artifacts.zip"
            bad_archive.write_bytes(DEFAULT_ARCHIVE.read_bytes() + b"\x00")
            with self.assertRaises(ValueError):
                assess_1sar_case_study(archive_path=bad_archive)

            bad_coord_audit = Path(tmpdir) / "bad_coord_audit.json"
            audit_data = json.loads(
                DEFAULT_1SAR_COORD_AUDIT.read_text(encoding="utf-8")
            )
            audit_data["archive"]["sha256"] = "0" * 64
            bad_coord_audit.write_text(json.dumps(audit_data), encoding="utf-8")
            with self.assertRaises(ValueError):
                assess_1sar_case_study(coord_audit_path=bad_coord_audit)

    def test_qds_and_eval_validation_and_t15_canonical_ids(self) -> None:
        """Verify assess_1sar_case_study validates QDS and EVAL inputs and uses canonical T15 IDs."""
        case_1sar = self.saved_report["case_study_1sar"]
        q1_obs = {
            row["observable_id"]: row
            for row in case_1sar["implementation_agreement"]["observables"]
        }
        t15_impls = q1_obs["T15_secondary_structure_3state"]["implementations"]
        self.assertEqual(
            t15_impls[0]["source_measurement_refs"],
            ["EVAL_1sar_cdba2c07_2026-09-22_T15_SS_97824701cc681ebe_M_content"],
        )
        self.assertEqual(
            t15_impls[1]["source_measurement_refs"],
            ["EVAL_1sar_cdba2c07_2026-09-22_T15_SS_97824701cc681ebe_M_agreement"],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            empty_qds = Path(tmpdir) / "empty_qds.yaml"
            empty_qds.write_text("quality_data_sheets:\n  - {}\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                assess_1sar_case_study(qds_path=empty_qds)

            empty_eval = Path(tmpdir) / "empty_eval.yaml"
            empty_eval.write_text("evaluation_runs:\n  - {}\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                assess_1sar_case_study(eval_path=empty_eval)

            corrupted_qds = Path(tmpdir) / "corrupted_qds.yaml"
            qds_doc = yaml.safe_load(DEFAULT_1SAR_QDS.read_text(encoding="utf-8"))
            qds_doc["quality_data_sheets"][0]["geometry_summary"]["clashscore"][
                "value_numeric"
            ] = 99.99
            corrupted_qds.write_text(yaml.safe_dump(qds_doc), encoding="utf-8")
            with self.assertRaises(ValueError):
                assess_1sar_case_study(qds_path=corrupted_qds)

    def test_deposition_applicability_null_and_numeric(self) -> None:
        """Verify deposited R-free applicability handling for None, negative, and valid values."""
        none_res = deposition_applicability(None)
        self.assertEqual(none_res["deposition_clause"], "unevaluable")
        self.assertEqual(none_res["deposited_reference"], "unavailable")

        neg_res = deposition_applicability(-0.15)
        self.assertEqual(neg_res["deposition_clause"], "unevaluable")
        self.assertEqual(neg_res["deposited_reference"], "unavailable")

        # Even if refmac_rfree is available, missing deposited_rfree stays unevaluable
        refmac_only_res = deposition_applicability(None, refmac_rfree=0.2128)
        self.assertEqual(refmac_only_res["deposition_clause"], "unevaluable")
        self.assertEqual(refmac_only_res["refmac_reference"], "available")

        valid_res = deposition_applicability(0.195)
        self.assertEqual(valid_res["deposition_clause"], "evaluable")
        self.assertEqual(valid_res["deposited_reference"], "available")

    def test_kabsch_rmsd_validation_and_identity(self) -> None:
        """Verify kabsch_rmsd rejects invalid shapes and returns 0.0 on identical coordinates."""
        coords = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
        self.assertAlmostEqual(kabsch_rmsd(coords, coords), 0.0, places=8)
        with self.assertRaises(ValueError):
            kabsch_rmsd(np.zeros((0, 3)), np.zeros((0, 3)))
        with self.assertRaises(ValueError):
            kabsch_rmsd(np.zeros((2, 2)), np.zeros((2, 2)))

    def test_mtz_reflection_retention_1sar_and_identity(self) -> None:
        """Verify MTZ reflection retention detects the 11 invalidated zero-F reflections on 1SAR."""
        mtz_labels = ("F-obs", "SIGF-obs", "R-free-flags")
        audit = audit_mtz_retention(
            self.start_mtz_bytes,
            self.final_mtz_bytes,
            input_labels=mtz_labels,
            output_labels=mtz_labels,
            flag_values={0, 1},
            free_value=1,
        )
        self.assertEqual(audit["audit_status"], "not_preserved")
        self.assertEqual(audit["input"]["raw_rows"], 7248)
        self.assertEqual(audit["output"]["raw_rows"], 7262)
        self.assertEqual(audit["input"]["eligible_rows"], 7228)
        self.assertEqual(audit["output"]["eligible_rows"], 7217)
        self.assertEqual(audit["input"]["work_rows"], 6505)
        self.assertEqual(audit["output"]["work_rows"], 6494)
        self.assertEqual(audit["input"]["free_rows"], 723)
        self.assertEqual(audit["output"]["free_rows"], 723)
        self.assertEqual(audit["input"]["zero_f"], 11)
        self.assertEqual(len(audit["invalidated_input_hkls"]), 11)
        self.assertEqual(audit["added_all_nan_rows"], 14)

        # Self-audit must report preserved
        self_audit = audit_mtz_retention(
            self.start_mtz_bytes,
            self.start_mtz_bytes,
            input_labels=mtz_labels,
            output_labels=mtz_labels,
            flag_values={0, 1},
            free_value=1,
        )
        self.assertEqual(self_audit["audit_status"], "preserved")
        self.assertEqual(len(self_audit["invalidated_input_hkls"]), 0)
        self.assertEqual(self_audit["added_all_nan_rows"], 0)

    def test_coordinate_and_inventory_shifts_1sar_and_identity(self) -> None:
        """Verify coordinate/B-factor shifts and atom inventory changes on 1SAR and self-comparison."""
        start_inv = summarize_pdb_inventory(self.start_pdb_text)
        final_inv = summarize_pdb_inventory(self.final_pdb_text)
        self.assertEqual(start_inv["total_non_hydrogen_atoms"], 1498)
        self.assertEqual(start_inv["water_atom_count"], 0)
        self.assertEqual(final_inv["total_non_hydrogen_atoms"], 1641)
        self.assertEqual(final_inv["water_atom_count"], 146)

        shifts = compare_pdb_pair(self.start_pdb_text, self.final_pdb_text)
        self.assertEqual(shifts["shared_all_heavy_atoms"]["atom_count"], 1493)
        self.assertAlmostEqual(
            shifts["shared_all_heavy_atoms"]["unsuperposed_rmsd_angstrom"],
            0.8460,
            places=3,
        )
        self.assertEqual(shifts["shared_ca_atoms"]["atom_count"], 192)
        self.assertAlmostEqual(
            shifts["shared_ca_atoms"]["unsuperposed_rmsd_angstrom"], 0.4229, places=3
        )
        self.assertAlmostEqual(
            shifts["shared_ca_atoms"]["kabsch_superposed_ca_rmsd_angstrom"],
            0.4191,
            places=3,
        )
        self.assertEqual(shifts["inventory_deltas"]["added_water_atoms"], 146)
        self.assertEqual(shifts["inventory_deltas"]["removed_water_atoms"], 0)
        self.assertEqual(len(shifts["inventory_deltas"]["removed_non_water_atoms"]), 5)
        self.assertEqual(len(shifts["inventory_deltas"]["added_non_water_atoms"]), 2)

        # Identity comparison must produce zero shifts
        zero_shifts = compare_pdb_pair(self.start_pdb_text, self.start_pdb_text)
        self.assertEqual(
            zero_shifts["shared_all_heavy_atoms"]["unsuperposed_rmsd_angstrom"], 0.0
        )
        self.assertEqual(
            zero_shifts["shared_ca_atoms"]["kabsch_superposed_ca_rmsd_angstrom"], 0.0
        )
        self.assertEqual(zero_shifts["inventory_deltas"]["added_water_atoms"], 0)
        self.assertEqual(zero_shifts["inventory_deltas"]["removed_non_water_atoms"], [])
        self.assertEqual(zero_shifts["inventory_deltas"]["added_non_water_atoms"], [])

    def test_saved_json_matches_fresh_build_and_separates_three_questions(self) -> None:
        """Verify saved JSON report matches build_full_assessment_report() and separates the 3 questions."""
        fresh_report = build_full_assessment_report()
        self.assertEqual(self.saved_report, fresh_report)

        case_1sar = self.saved_report["case_study_1sar"]
        self.assertEqual(case_1sar["pass_criterion_bindings"], [])
        self.assertEqual(case_1sar["assessment_verdict_status"], "informational")
        for key in (
            "implementation_agreement",
            "final_model_quality_support",
            "change_relative_to_input",
            "missing_conflicting_and_inapplicable_evidence",
        ):
            self.assertIn(key, case_1sar)

        # Check 1SAR Question 1, Question 2, Question 3 key values
        q1_obs = {
            row["observable_id"]: row
            for row in case_1sar["implementation_agreement"]["observables"]
        }
        self.assertIn("T03_r_work_r_free", q1_obs)
        self.assertAlmostEqual(
            q1_obs["T03_r_work_r_free"]["spread_summary"]["gemmi_minus_phenix_r_free"],
            0.0020,
            places=4,
        )
        self.assertIn("T15_secondary_structure_3state", q1_obs)
        self.assertAlmostEqual(
            q1_obs["T15_secondary_structure_3state"]["spread_summary"][
                "q3_agreement_fraction"
            ],
            0.8802,
            places=4,
        )

        q2_domains = case_1sar["final_model_quality_support"]["domains"]
        self.assertAlmostEqual(
            q2_domains["experimental_fit_and_data_completeness"]["r_free_phenix"],
            0.2116,
            places=4,
        )
        self.assertAlmostEqual(
            q2_domains["dimer_interface_and_fold_conservation_vs_deposited_1sar"][
                "dockq_identity_mapping_AB_AB"
            ],
            0.9445,
            places=4,
        )
        self.assertEqual(
            case_1sar["provenance"]["deposited_reference_model"][
                "deposition_applicability"
            ]["deposition_clause"],
            "unevaluable",
        )

        q3 = case_1sar["change_relative_to_input"]
        self.assertEqual(
            q3["reflection_data_retention"]["audit_status"], "not_preserved"
        )
        self.assertAlmostEqual(
            q3["retained_start_to_packaged_quality_deltas"]["phenix_r_free"]["delta"],
            -0.1840,
            places=4,
        )

        # Check all 5 control cohorts have n=22 and all 3 question sections
        cohorts = self.saved_report["control_cohorts_evaluation"]["cohorts"]
        expected_cohorts = {
            "unchanged_null": (22, 19, 3, 3, "available"),
            "damaged_sa": (22, 19, 3, 18, "available"),
            "damaged_dynamics": (22, 19, 3, 22, "unavailable"),
            "recovered_unprotonated_solvent": (22, 19, 3, 22, "unavailable"),
            "recovered_protonated_ordered_solvent": (22, 21, 1, 9, "unavailable"),
        }
        for cohort_id, (
            n_total,
            n_refmac,
            n_two_path,
            n_f_data,
            post_rfree_status,
        ) in expected_cohorts.items():
            self.assertIn(cohort_id, cohorts)
            c = cohorts[cohort_id]
            self.assertEqual(c["target_count"], n_total)
            self.assertEqual(c["refmac_evaluable_target_count"], n_refmac)
            self.assertEqual(c["two_path_only_target_count"], n_two_path)
            self.assertEqual(c["assessment_verdict_status"], "informational")
            self.assertIn("implementation_agreement", c)
            self.assertIn("final_model_quality_support", c)
            self.assertIn("change_relative_to_input", c)
            self.assertEqual(
                c["change_relative_to_input"]["diagnostic_flag_counts"]["F-data"],
                n_f_data,
            )
            post_phenix = c["final_model_quality_support"]["post_phenix_r_free"]
            self.assertEqual(post_phenix["status"], post_rfree_status)
            if post_rfree_status == "unavailable":
                self.assertEqual(post_phenix["count"], 0)
                self.assertEqual(post_phenix["unavailable_count"], 22)
                self.assertIsNone(post_phenix["median"])
                for row in c["per_target_rows"]:
                    self.assertIsNone(row["post_phenix_r_free"])
                    self.assertIsNone(row["post_gemmi_r_free"])
                    self.assertIsNone(row["post_refmac_r_free"])
            else:
                self.assertEqual(post_phenix["count"], 22)
                self.assertEqual(post_phenix["unavailable_count"], 0)
                self.assertIsNotNone(post_phenix["median"])

        unchanged_conflicts = [
            r["pdb_id"]
            for r in cohorts["unchanged_null"]["per_target_rows"]
            if r["conflict_count"] > 0
        ]
        self.assertEqual(unchanged_conflicts, ["2VXN", "9TXE"])
        invariance_note = self.saved_report["control_cohorts_evaluation"][
            "cross_cohort_findings"
        ]["unchanged_control_invariance"]
        self.assertIn("2VXN", invariance_note)
        self.assertIn("9TXE", invariance_note)
        self.assertNotIn("8RFF", invariance_note)

        protonation_note = self.saved_report["control_cohorts_evaluation"][
            "cross_cohort_findings"
        ]["recovered_control_protonation_contrast"]
        self.assertIn("multi-factor protocol change", protonation_note)
        self.assertIn("BREF ANIS", protonation_note)
        self.assertNotIn("isolates the effect", protonation_note)

    def test_case_study_markdown_exists_and_documents_required_findings(self) -> None:
        """Verify case study markdown report exists, cites existing repo paths, and documents 1SAR and the 5 control cohorts."""
        self.assertTrue(CASE_STUDY_MD_PATH.is_file())
        text = CASE_STUDY_MD_PATH.read_text(encoding="utf-8")
        for token in (
            "implementation_agreement",
            "final_model_quality_support",
            "change_relative_to_input",
            "8cbc1650f8be5a3833f98833fa514ec7d490c2c3bb9aa930413abac05e2a510b",
            "6b34c5d0dec6647df20eae9021ff7d511d6dedc03b4349c0b634d8e5b1f869e4",
            "data/1sar_round5.pdb",
            "data/1sar_round6.pdb",
            "0.1488 / 0.1989",
            "49.972–2.500 Å",
            "Asn39 (`Asn A 39`)",
            "not_preserved",
            "unchanged_null",
            "damaged_sa",
            "damaged_dynamics",
            "recovered_unprotonated_solvent",
            "recovered_protonated_ordered_solvent",
            "2VXN",
            "9TXE",
            "NeedsReview",
            "5.8.0431",
            "0.4.131",
            "4.5.2 (historical)",
            "4.6.1",
            "1.7.1",
        ):
            self.assertIn(token, text)
        self.assertNotIn("Thr39", text)
        self.assertNotIn("1.8007", text)
        self.assertNotIn("8RFF", text)

        for rel_path in (
            "scripts/assess_refinement.py",
            "scripts/test_assess_refinement.py",
            "ref/research/data/refinement_assessment_1sar_and_controls_2026-10-18.json",
            "data/coscientists/openscientist/cdba2c07-daff-4f60-ae96-12452b3a5fbb_artifacts.zip",
            "data/pdb_mtz/1sar_deposited.pdb",
            "data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-09-23.yaml",
            "data/coscientists/openscientist/QDS_1sar_cdba2c07_2026-09-23.yaml",
            "data/coscientists/openscientist/retained_evidence_2026-09-23/coordinate_and_t13_audit.json",
            "ref/research/data/negative_control_round3_bench.json",
            "ref/research/data/negative_control_round4_recover.json",
            "ref/research/data/negative_control_round10_recover.json",
        ):
            self.assertIn(rel_path, text)
            self.assertTrue((REPO_ROOT / rel_path).is_file(), f"Missing {rel_path}")


if __name__ == "__main__":
    unittest.main()
