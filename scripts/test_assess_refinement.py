#!/usr/bin/env python3
"""Regression tests for scripts/assess_refinement.py and its generated outputs."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

import numpy as np
import yaml

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from assess_refinement import (  # noqa: E402
    DEFAULT_1SAR_COORD_AUDIT,
    DEFAULT_1SAR_EVAL,
    DEFAULT_1SAR_QDS,
    DEFAULT_ARCHIVE,
    DEFAULT_DEPOSITED_PDB,
    DEFAULT_ROUND10_RECOVER,
    DEFAULT_ROUND3_BENCH,
    DEFAULT_ROUND4_RECOVER,
    EXPECTED_1SAR_ARCHIVE_SHA256,
    EXPECTED_1SAR_COORD_AUDIT_SHA256,
    EXPECTED_1SAR_DEPOSITED_PDB_SHA256,
    EXPECTED_1SAR_EVAL_SHA256,
    EXPECTED_1SAR_FINAL_SUBJECT_REF,
    EXPECTED_1SAR_QDS_SHA256,
    EXPECTED_ROUND10_RECOVER_SHA256,
    EXPECTED_ROUND3_BENCH_SHA256,
    EXPECTED_ROUND4_RECOVER_SHA256,
    REPO_ROOT,
    _extract_control_row_metrics,
    _median_and_iqr,
    _parse_deposited_r_values,
    _require_eval_numeric,
    _require_eval_text,
    _require_qds_numeric,
    assess_1sar_case_study,
    audit_mtz_retention,
    build_full_assessment_report,
    compare_pdb_pair,
    deposition_applicability,
    evaluate_control_cohorts,
    kabsch_rmsd,
    resolve_verdict_status,
    serialize_assessment_report,
    sha256_file,
    summarize_control_cohort,
    summarize_pdb_inventory,
)

ASSESSMENT_JSON_PATH = (
    REPO_ROOT
    / "ref"
    / "research"
    / "data"
    / "refinement_assessment_1sar_and_controls_2026-10-18.json"
)
EXPECTED_FROZEN_ASSESSMENT_JSON_SHA256 = (
    "db100e926bfcf6331c303087846c4d51117a4411c6afdf58877aada5dbf14245"
)
EXPECTED_CLAUDE_LOG_SHA256 = (
    "9ba0fddf49e97f0725de084167a640563473b750d7a7fff78782af207c9fcd1c"
)
EXPECTED_FINAL_REPORT_MD_SHA256 = (
    "a296f07513a5e05c085b1639632a0a2f48e1c7ab0cce1b7596b230cae110b5a2"
)
ROUND2_ENROLLED_JSON_PATH = (
    REPO_ROOT / "ref" / "research" / "data" / "negative_control_round2_enrolled.json"
)
EXPECTED_ROUND2_ENROLLED_SHA256 = (
    "02fc974da9d1f8a2d8fb3c496c13196c200b31d182f1b7323cb25dcc59cbe7da"
)
ROUND2_SCREEN_JSON_PATH = (
    REPO_ROOT / "ref" / "research" / "data" / "negative_control_round2_screen.json"
)
EXPECTED_ROUND2_SCREEN_SHA256 = (
    "dfebc4b131a8df1ceac4190c00bc1d60eeaba00846167530e5a4d1a2152cb313"
)
ROUND9_ANIS_JSON_PATH = (
    REPO_ROOT / "ref" / "research" / "data" / "negative_control_round9_anis.json"
)
ROUND2_MD_PATH = REPO_ROOT / "ref" / "research" / "negative_control_round2.md"
CASE_STUDY_MD_PATH = (
    REPO_ROOT / "ref" / "research" / "refinement_assessment_case_study_2026-10-18.md"
)
SOURCE_CORRECTIONS_MD_PATH = (
    REPO_ROOT
    / "ref"
    / "research"
    / "refinement_assessment_source_corrections_2026-11-09.md"
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

    def _expected_current_report(self) -> dict:
        """Return a deep copy of the frozen JSON with only the two source-verified narrative corrections applied."""
        self.assertEqual(
            sha256_file(ASSESSMENT_JSON_PATH),
            EXPECTED_FROZEN_ASSESSMENT_JSON_SHA256,
        )
        round3_doc = json.loads(DEFAULT_ROUND3_BENCH.read_text(encoding="utf-8"))
        row_2vxn = round3_doc["rows"][2]
        self.assertEqual(row_2vxn["pdb_id"], "2VXN")
        self.assertEqual(row_2vxn["subject"], "null")
        d_phenix = f"{row_2vxn['numbers']['d_phenix']:+.4f}"
        d_gemmi = f"{row_2vxn['numbers']['d_gemmi']:+.4f}"
        d_refmac = f"{row_2vxn['numbers']['d_refmac']:+.4f}"

        expected = copy.deepcopy(self.saved_report)
        expected["case_study_1sar"][
            "missing_conflicting_and_inapplicable_evidence"
        ][0]["description"] = (
            "The trajectory log (claude_iterations.log:510, :752) claims an "
            "unarchived round-7 model with R-work = 0.1488, R-free = 0.1989, "
            "1,654 atoms reported in the log (192 residues, 159 waters, 1 Ca2+, "
            "1 Na+, and 1 SO4), and final_report.md:70, :150 describes removal "
            "of the disordered chain-B sulfate (ligand SO4 count 2 -> 1), not a "
            "restored B:97:SO4; because that round-7 coordinate file was never "
            "packaged into cdba2c07-daff-4f60-ae96-12452b3a5fbb_artifacts.zip, "
            "all round-7 counts remain unverified log/report claims rather than "
            "measured coordinate inventory. Instead, data/1sar_final.pdb is the "
            "round-4 PHENIX model (SHA-256 "
            "8cbc1650f8be5a3833f98833fa514ec7d490c2c3bb9aa930413abac05e2a510b, "
            "146 waters, 1,641 heavy atoms), while intermediate rounds 5 and 6 "
            "were saved separately as data/1sar_round5.pdb and data/1sar_round6.pdb."
        )
        expected["control_cohorts_evaluation"]["cross_cohort_findings"][
            "unchanged_control_invariance"
        ] = (
            "In unchanged_null (subject='null', n=22), phenix and gemmi delta R-free "
            "agree tightly (median |d_phenix - d_gemmi| = 0.0007), while REFMAC5 "
            "(evaluable on 19/22 targets; 3/22 two-path-only: 9YGW, 8R5K, 8QXQ) "
            "shows smaller deltas (median d_refmac = +0.0018 vs median d_phenix = +0.0035) "
            "and triggers solver-disagreement notes on 2/22 targets (2VXN on F-data, "
            f"where PHENIX/gemmi are positive ({d_phenix} / {d_gemmi}) while REFMAC sign is "
            f"negative ({d_refmac}); 9TXE on F-geom, where cctbx worsening stands down "
            "against improved REFMAC zBOND (-0.043)). Separating Question 1 "
            "(implementation agreement) from Question 3 (change relative to input) "
            "keeps solver-convention differences distinct from physical model changes."
        )
        return expected

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

    def test_control_cohort_baseline_matching_and_denominator_counts(self) -> None:
        """Verify ISOT-baseline + ANIS-delta is rejected while matching CIF-pinned provenance reconstructs endpoints with exact per-metric counts."""
        sample_block = {
            "state": "osol_h",
            "shift_all_residue": 0.0422,
            "two_path_only": False,
            "numbers": {
                "d_phenix": 0.0050,
                "d_gemmi": 0.0060,
                "d_refmac": 0.0092,
                "clash_pre": 1.0,
                "clash_post": 1.5,
                "d_favored_pp": -0.2,
                "d_rota_pp": 0.1,
                "d_zbond": -0.01,
                "shift_unmasked": 0.0400,
                "n_protected_fixed": 0,
            },
            "flags": {
                "F-data": False,
                "F-geom": False,
                "F-protected": False,
                "F-shift": False,
            },
            "conflicts": [],
            "verdict": "not-degraded",
        }
        matching_hashes = {
            "model": "m" * 64,
            "mtz": "t" * 64,
            "cif": "c" * 64,
        }
        sample_row = {
            "pdb_id": "4M7G",
            "d_min": 1.9,
            "refmac_convention": "ANIS",
            "input_hashes": matching_hashes,
            "recovered": sample_block,
        }
        isot_baseline_pre = {
            "rfree_phenix": 0.1500,
            "rfree_gemmi": 0.1520,
            "refmac": {"r_free": 0.1738},
        }

        # 1. Mixed convention (ISOT baseline + ANIS delta) or missing CIF hash must NOT produce post R-free
        mixed_norm = _extract_control_row_metrics(
            sample_row,
            state_key="recovered",
            baseline_pre=isot_baseline_pre,
            baseline_input_hashes=matching_hashes,
            baseline_convention_matches=False,
        )
        self.assertAlmostEqual(mixed_norm["d_refmac"], 0.0092, places=4)
        self.assertIsNone(mixed_norm["post_phenix_r_free"])
        self.assertIsNone(mixed_norm["post_gemmi_r_free"])
        self.assertIsNone(mixed_norm["post_refmac_r_free"])

        missing_cif_norm = _extract_control_row_metrics(
            sample_row,
            state_key="recovered",
            baseline_pre=isot_baseline_pre,
            baseline_input_hashes={"model": "m" * 64, "mtz": "t" * 64},
            baseline_convention_matches=True,
        )
        self.assertIsNone(missing_cif_norm["post_refmac_r_free"])

        # 2. Genuinely matching provenance (model, mtz, cif hashes + convention) reconstructs endpoints
        # and distinguishes delta count (n=2) from reconstructed post-REFMAC count (n=1).
        matched_norm_1 = _extract_control_row_metrics(
            sample_row,
            state_key="recovered",
            baseline_pre={
                "rfree_phenix": 0.1400,
                "rfree_gemmi": 0.1420,
                "refmac": {"r_free": 0.1193},
            },
            baseline_input_hashes=matching_hashes,
            baseline_convention_matches=True,
        )
        self.assertAlmostEqual(matched_norm_1["post_refmac_r_free"], 0.1285, places=4)

        sample_row_2 = dict(sample_row, pdb_id="8QXQ")
        matched_norm_2 = _extract_control_row_metrics(
            sample_row_2,
            state_key="recovered",
            baseline_pre={
                "rfree_phenix": 0.1600,
                "rfree_gemmi": 0.1620,
                "refmac": None,
            },
            baseline_input_hashes=matching_hashes,
            baseline_convention_matches=True,
        )
        self.assertAlmostEqual(matched_norm_2["d_refmac"], 0.0092, places=4)
        self.assertIsNone(matched_norm_2["post_refmac_r_free"])

        summary = summarize_control_cohort(
            cohort_id="synthetic_matched",
            description="Synthetic cohort with 2 REFMAC deltas and 1 usable REFMAC baseline.",
            source_path=ASSESSMENT_JSON_PATH,
            normalized_rows=[matched_norm_1, matched_norm_2],
        )
        self.assertEqual(summary["target_count"], 2)
        self.assertEqual(summary["refmac_evaluable_target_count"], 2)
        self.assertEqual(
            summary["change_relative_to_input"]["delta_r_free_refmac"]["count"], 2
        )
        self.assertEqual(
            summary["final_model_quality_support"]["post_refmac_r_free"]["count"], 1
        )
        self.assertEqual(
            summary["final_model_quality_support"]["post_refmac_r_free"][
                "unavailable_count"
            ],
            1,
        )
        self.assertAlmostEqual(
            summary["final_model_quality_support"]["post_refmac_r_free"]["median"],
            0.1285,
            places=4,
        )

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

    def test_1sar_fixed_source_digests_and_alternate_path_bundle(self) -> None:
        """Verify all five 1SAR fixed source digests and support exact source bundle at alternate paths."""
        self.assertEqual(sha256_file(DEFAULT_ARCHIVE), EXPECTED_1SAR_ARCHIVE_SHA256)
        self.assertEqual(
            sha256_file(DEFAULT_DEPOSITED_PDB), EXPECTED_1SAR_DEPOSITED_PDB_SHA256
        )
        self.assertEqual(sha256_file(DEFAULT_1SAR_QDS), EXPECTED_1SAR_QDS_SHA256)
        self.assertEqual(sha256_file(DEFAULT_1SAR_EVAL), EXPECTED_1SAR_EVAL_SHA256)
        self.assertEqual(
            sha256_file(DEFAULT_1SAR_COORD_AUDIT), EXPECTED_1SAR_COORD_AUDIT_SHA256
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_root = Path(tmpdir)
            alt_archive = tmp_root / "alt_artifacts.zip"
            alt_deposited = tmp_root / "alt_1sar_deposited.pdb"
            alt_qds = tmp_root / "alt_qds.yaml"
            alt_eval = tmp_root / "alt_eval.yaml"
            alt_audit = tmp_root / "alt_coord_audit.json"

            alt_archive.write_bytes(DEFAULT_ARCHIVE.read_bytes())
            alt_deposited.write_bytes(DEFAULT_DEPOSITED_PDB.read_bytes())
            alt_qds.write_bytes(DEFAULT_1SAR_QDS.read_bytes())
            alt_eval.write_bytes(DEFAULT_1SAR_EVAL.read_bytes())
            alt_audit.write_bytes(DEFAULT_1SAR_COORD_AUDIT.read_bytes())

            alt_case = assess_1sar_case_study(
                archive_path=alt_archive,
                deposited_pdb_path=alt_deposited,
                qds_path=alt_qds,
                eval_path=alt_eval,
                coord_audit_path=alt_audit,
            )
            default_case = self._expected_current_report()["case_study_1sar"]

            self.assertEqual(alt_case["provenance"]["archive_path"], str(alt_archive))
            self.assertEqual(
                alt_case["provenance"]["archive_sha256"], EXPECTED_1SAR_ARCHIVE_SHA256
            )
            self.assertEqual(
                alt_case["provenance"]["deposited_reference_model"]["path"],
                str(alt_deposited),
            )
            self.assertEqual(
                alt_case["provenance"]["deposited_reference_model"]["sha256"],
                EXPECTED_1SAR_DEPOSITED_PDB_SHA256,
            )
            self.assertEqual(
                alt_case["provenance"]["retained_records"]["qds_path"], str(alt_qds)
            )
            self.assertEqual(
                alt_case["provenance"]["retained_records"]["eval_path"], str(alt_eval)
            )
            self.assertEqual(
                alt_case["provenance"]["retained_records"][
                    "coordinate_and_t13_audit_path"
                ],
                str(alt_audit),
            )
            for section in (
                "implementation_agreement",
                "final_model_quality_support",
                "change_relative_to_input",
                "missing_conflicting_and_inapplicable_evidence",
            ):
                self.assertEqual(alt_case[section], default_case[section])

    def test_1sar_source_admission_rejects_altered_context_origins_deposition_and_nan(
        self,
    ) -> None:
        """Verify assess_1sar_case_study rejects altered metric/tool context, QDS origins, deposition bytes, and NaN."""
        eval_doc = yaml.safe_load(DEFAULT_1SAR_EVAL.read_text(encoding="utf-8"))
        qds_doc = yaml.safe_load(DEFAULT_1SAR_QDS.read_text(encoding="utf-8"))
        audit_doc = json.loads(DEFAULT_1SAR_COORD_AUDIT.read_text(encoding="utf-8"))

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_root = Path(tmpdir)

            # 1. Altered EVAL metric_definition_ref / oracle_tool_ref / subject_ref / NaN
            for label, field_name, bad_val in (
                ("wrong_metric", "metric_definition_ref", "T05_clashscore"),
                ("wrong_tool", "oracle_tool_ref", "ProSMART"),
                ("wrong_task", "catalog_task_ref", "T05"),
                ("wrong_stage", "stage", "initial"),
                ("wrong_subject", "subject_ref", "pdb:9XYZ"),
            ):
                bad_eval_doc = json.loads(json.dumps(eval_doc))
                refmac_row = next(
                    m
                    for m in bad_eval_doc["evaluation_runs"][0]["measurements"]
                    if m["id"] == "EVAL_1sar_cdba2c07_2026-09-23_M_refmac_rfree"
                )
                refmac_row[field_name] = bad_val
                bad_eval_path = tmp_root / f"eval_{label}.yaml"
                bad_eval_path.write_text(
                    yaml.safe_dump(bad_eval_doc), encoding="utf-8"
                )
                with self.assertRaisesRegex(
                    ValueError, "EvaluationRun SHA-256 mismatch"
                ):
                    assess_1sar_case_study(eval_path=bad_eval_path)

            nan_eval_doc = json.loads(json.dumps(eval_doc))
            refmac_row = next(
                m
                for m in nan_eval_doc["evaluation_runs"][0]["measurements"]
                if m["id"] == "EVAL_1sar_cdba2c07_2026-09-23_M_refmac_rfree"
            )
            refmac_row["oracle_measure"]["value_numeric"] = float("nan")
            nan_eval_path = tmp_root / "eval_nan.yaml"
            nan_eval_path.write_text(yaml.safe_dump(nan_eval_doc), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "EvaluationRun SHA-256 mismatch"):
                assess_1sar_case_study(eval_path=nan_eval_path)

            # 2. Altered QDS measurement_evidence_origins or NaN value
            stripped_qds_doc = json.loads(json.dumps(qds_doc))
            for origin in stripped_qds_doc["quality_data_sheets"][0][
                "measurement_evidence_origins"
            ]:
                for k in list(origin):
                    if k != "source_measurement_ref":
                        del origin[k]
            stripped_qds_path = tmp_root / "qds_stripped_origins.yaml"
            stripped_qds_path.write_text(
                yaml.safe_dump(stripped_qds_doc), encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "QDS SHA-256 mismatch"):
                assess_1sar_case_study(qds_path=stripped_qds_path)

            # 3. Unrelated or altered deposited PDB bytes
            other_pdb = tmp_root / "unrelated_9xyz.pdb"
            other_pdb.write_text(
                "HEADER    UNRELATED STRUCTURE                     01-JAN-00   9XYZ\n"
                "REMARK   3   FREE R VALUE                     : 0.001\n"
                "END\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "Deposited PDB SHA-256 mismatch"):
                assess_1sar_case_study(deposited_pdb_path=other_pdb)

            # 4. Altered coordinate audit model/dataset fields
            bad_audit_doc = json.loads(json.dumps(audit_doc))
            bad_audit_doc["dataset"]["subject_ref"] = "mtz:unrelated"
            bad_audit_path = tmp_root / "audit_bad_dataset.json"
            bad_audit_path.write_text(json.dumps(bad_audit_doc), encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError, "Coordinate/T13 audit SHA-256 mismatch"
            ):
                assess_1sar_case_study(coord_audit_path=bad_audit_path)

    def test_control_cohorts_fixed_source_digests_alternate_paths_and_admission_rejection(
        self,
    ) -> None:
        """Verify evaluate_control_cohorts pins the 3 control source digests, reuses admitted digests without re-reading, and rejects empty/altered inputs."""
        self.assertEqual(
            sha256_file(DEFAULT_ROUND3_BENCH), EXPECTED_ROUND3_BENCH_SHA256
        )
        self.assertEqual(
            sha256_file(DEFAULT_ROUND4_RECOVER), EXPECTED_ROUND4_RECOVER_SHA256
        )
        self.assertEqual(
            sha256_file(DEFAULT_ROUND10_RECOVER), EXPECTED_ROUND10_RECOVER_SHA256
        )

        default_controls = evaluate_control_cohorts()
        self.assertEqual(
            default_controls,
            self._expected_current_report()["control_cohorts_evaluation"],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_root = Path(tmpdir)
            alt_round3 = tmp_root / "alt_round3_bench.json"
            alt_round4 = tmp_root / "alt_round4_recover.json"
            alt_round10 = tmp_root / "alt_round10_recover.json"

            alt_round3.write_bytes(DEFAULT_ROUND3_BENCH.read_bytes())
            alt_round4.write_bytes(DEFAULT_ROUND4_RECOVER.read_bytes())
            alt_round10.write_bytes(DEFAULT_ROUND10_RECOVER.read_bytes())

            with mock.patch(
                "assess_refinement.sha256_file",
                side_effect=AssertionError(
                    "summarize_control_cohort must use admitted source_sha256 without re-reading source_path"
                ),
            ):
                alt_controls = evaluate_control_cohorts(
                    round3_path=alt_round3,
                    round4_path=alt_round4,
                    round10_path=alt_round10,
                )

            self.assertEqual(
                alt_controls["cross_cohort_findings"],
                default_controls["cross_cohort_findings"],
            )
            expected_sources = {
                "unchanged_null": (str(alt_round3), EXPECTED_ROUND3_BENCH_SHA256),
                "damaged_sa": (str(alt_round3), EXPECTED_ROUND3_BENCH_SHA256),
                "damaged_dynamics": (str(alt_round4), EXPECTED_ROUND4_RECOVER_SHA256),
                "recovered_unprotonated_solvent": (
                    str(alt_round4),
                    EXPECTED_ROUND4_RECOVER_SHA256,
                ),
                "recovered_protonated_ordered_solvent": (
                    str(alt_round10),
                    EXPECTED_ROUND10_RECOVER_SHA256,
                ),
            }
            for cohort_id, (expected_path, expected_sha) in expected_sources.items():
                alt_cohort = alt_controls["cohorts"][cohort_id]
                def_cohort = default_controls["cohorts"][cohort_id]
                self.assertEqual(alt_cohort["source_file"], expected_path)
                self.assertEqual(alt_cohort["source_sha256"], expected_sha)
                for key, val in def_cohort.items():
                    if key != "source_file":
                        self.assertEqual(alt_cohort[key], val)

            # Empty control payloads must be rejected before parsing or emitting 22-target prose
            empty_json = tmp_root / "empty_rows.json"
            empty_json.write_text('{"rows": []}\n', encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError, "Round 3 unchanged/SA control cohort SHA-256 mismatch"
            ):
                evaluate_control_cohorts(round3_path=empty_json)
            with self.assertRaisesRegex(
                ValueError, "Round 4 damaged/recovered control cohort SHA-256 mismatch"
            ):
                evaluate_control_cohorts(round4_path=empty_json)
            with self.assertRaisesRegex(
                ValueError, "Round 10 recovered control cohort SHA-256 mismatch"
            ):
                evaluate_control_cohorts(round10_path=empty_json)

            # Altered metric payloads for each of the 3 control sources must be rejected
            round3_doc = json.loads(DEFAULT_ROUND3_BENCH.read_text(encoding="utf-8"))
            round3_doc["rows"][0]["numbers"]["d_phenix"] = 0.9999
            bad_round3 = tmp_root / "bad_round3.json"
            bad_round3.write_text(json.dumps(round3_doc), encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError, "Round 3 unchanged/SA control cohort SHA-256 mismatch"
            ):
                evaluate_control_cohorts(round3_path=bad_round3)

            round4_doc = json.loads(DEFAULT_ROUND4_RECOVER.read_text(encoding="utf-8"))
            round4_doc["rows"][0]["perturbed"]["numbers"]["d_phenix"] = 0.9999
            bad_round4 = tmp_root / "bad_round4.json"
            bad_round4.write_text(json.dumps(round4_doc), encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError, "Round 4 damaged/recovered control cohort SHA-256 mismatch"
            ):
                evaluate_control_cohorts(round4_path=bad_round4)

            round10_doc = json.loads(
                DEFAULT_ROUND10_RECOVER.read_text(encoding="utf-8")
            )
            round10_doc["rows"][0]["recovered"]["numbers"]["d_phenix"] = 0.9999
            bad_round10 = tmp_root / "bad_round10.json"
            bad_round10.write_text(json.dumps(round10_doc), encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError, "Round 10 recovered control cohort SHA-256 mismatch"
            ):
                evaluate_control_cohorts(round10_path=bad_round10)

    def test_numeric_helpers_semantic_context_and_strict_json_guards(self) -> None:
        """Verify helper-level semantic context checks, non-finite rejection, and strict JSON emission."""
        base_row = {
            "id": "EVAL_1sar_cdba2c07_2026-09-23_M_refmac_rfree",
            "catalog_task_ref": "T03",
            "metric_definition_ref": "T03_r-free",
            "oracle_tool_ref": "REFMAC5",
            "stage": "final",
            "subject_ref": EXPECTED_1SAR_FINAL_SUBJECT_REF,
            "oracle_measure": {"value_numeric": 0.2128},
        }
        self.assertAlmostEqual(
            _require_eval_numeric(
                {base_row["id"]: base_row},
                base_row["id"],
                0.2128,
                expected_task_ref="T03",
                expected_metric_ref="T03_r-free",
                expected_oracle_ref="REFMAC5",
                expected_stage="final",
                expected_subject_ref=EXPECTED_1SAR_FINAL_SUBJECT_REF,
            ),
            0.2128,
            places=4,
        )

        # Reject altered metric, tool, task, stage, or subject_ref in _require_eval_numeric
        for field_name, wrong_val in (
            ("metric_definition_ref", "T05_clashscore"),
            ("oracle_tool_ref", "ProSMART"),
            ("catalog_task_ref", "T05"),
            ("stage", "initial"),
            ("subject_ref", "pdb:9XYZ"),
        ):
            mutated = dict(base_row, **{field_name: wrong_val})
            with self.assertRaises(ValueError):
                _require_eval_numeric(
                    {base_row["id"]: mutated},
                    base_row["id"],
                    0.2128,
                    expected_task_ref="T03",
                    expected_metric_ref="T03_r-free",
                    expected_oracle_ref="REFMAC5",
                    expected_stage="final",
                    expected_subject_ref=EXPECTED_1SAR_FINAL_SUBJECT_REF,
                )

        # Reject stripped context even without optional expected_* arguments
        stripped_row = {
            "id": base_row["id"],
            "oracle_measure": {"value_numeric": 0.2128},
        }
        with self.assertRaises(ValueError):
            _require_eval_numeric({base_row["id"]: stripped_row}, base_row["id"], 0.2128)

        text_row = {
            "id": "EVAL_1sar_cdba2c07_2026-09-23_M_t13_tncs_flag",
            "catalog_task_ref": "T13",
            "metric_definition_ref": "T13_tncs",
            "oracle_tool_ref": "ctruncate",
            "stage": "all",
            "subject_ref": "mtz:test",
            "oracle_measure": {"value_text": "false"},
        }
        self.assertEqual(
            _require_eval_text(
                {text_row["id"]: text_row},
                text_row["id"],
                "false",
                expected_task_ref="T13",
                expected_oracle_ref="ctruncate",
            ),
            "false",
        )
        with self.assertRaises(ValueError):
            _require_eval_text(
                {text_row["id"]: dict(text_row, oracle_tool_ref="wrong_tool")},
                text_row["id"],
                "false",
                expected_oracle_ref="ctruncate",
            )

        # Reject non-finite values in _require_eval_numeric, _require_qds_numeric, _median_and_iqr, kabsch_rmsd
        for bad_num in (float("nan"), float("inf"), float("-inf"), True, None):
            bad_eval_row = dict(base_row, oracle_measure={"value_numeric": bad_num})
            with self.assertRaises(ValueError):
                _require_eval_numeric(
                    {base_row["id"]: bad_eval_row}, base_row["id"], 0.2128
                )
            bad_qds_block = {
                "r_free": {
                    "source_measurement_ref": "EVAL_1sar_cdba2c07_2026-09-07_M_006",
                    "value_numeric": bad_num,
                }
            }
            with self.assertRaises(ValueError):
                _require_qds_numeric(
                    bad_qds_block,
                    "r_free",
                    "EVAL_1sar_cdba2c07_2026-09-07_M_006",
                    0.2136,
                )
            with self.assertRaises(ValueError):
                _median_and_iqr([1.0, bad_num])  # type: ignore[list-item]

        with self.assertRaises(ValueError):
            kabsch_rmsd(
                np.array([[0.0, 0.0, 0.0], [float("nan"), 1.0, 0.0]]),
                np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 0.0]]),
            )

        # Reject unrelated or non-finite deposited PDB header in _parse_deposited_r_values
        valid_dep = _parse_deposited_r_values(
            DEFAULT_DEPOSITED_PDB, require_1sar_header=True
        )
        self.assertIsNone(valid_dep["deposited_r_work"])
        self.assertIsNone(valid_dep["deposited_r_free"])
        with self.assertRaises(ValueError):
            _parse_deposited_r_values(
                DEFAULT_DEPOSITED_PDB,
                pdb_text=(
                    "HEADER    UNRELATED STRUCTURE                     01-JAN-00   9XYZ\n"
                    "REMARK   3   FREE R VALUE                     : 0.001\n"
                ),
                require_1sar_header=True,
            )
        with self.assertRaises(ValueError):
            _parse_deposited_r_values(
                DEFAULT_DEPOSITED_PDB,
                pdb_text=(
                    "HEADER    HYDROLASE (ENDORIBONUCLEASE)            13-DEC-90   1SAR\n"
                    "REMARK   3   FREE R VALUE                     : NaN\n"
                ),
                require_1sar_header=False,
            )

        # Verify strict JSON serializer rejects NaN and Inf
        serialized = serialize_assessment_report(self.saved_report)
        self.assertTrue(serialized.endswith("\n"))
        self.assertEqual(json.loads(serialized), self.saved_report)
        for non_finite in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(ValueError):
                serialize_assessment_report({"bad_metric": non_finite})

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
        """Verify frozen JSON matches build_full_assessment_report() outside the two dated narrative corrections and separates the 3 questions."""
        self.assertEqual(
            sha256_file(ASSESSMENT_JSON_PATH),
            EXPECTED_FROZEN_ASSESSMENT_JSON_SHA256,
        )
        self.assertIn(
            "159 waters (1,654 heavy atoms), and restored B:97:SO4",
            self.saved_report["case_study_1sar"][
                "missing_conflicting_and_inapplicable_evidence"
            ][0]["description"],
        )
        self.assertIn(
            "(+0.0053 / +0.0067)",
            self.saved_report["control_cohorts_evaluation"]["cross_cohort_findings"][
                "unchanged_control_invariance"
            ],
        )

        fresh_report = build_full_assessment_report()
        expected_report = self._expected_current_report()
        self.assertEqual(expected_report, fresh_report)

        # Prove that unrelated field drift in either case_study_1sar or control_cohorts_evaluation is never masked
        mutated_case_report = copy.deepcopy(fresh_report)
        mutated_case_report["case_study_1sar"]["final_model_quality_support"][
            "domains"
        ]["experimental_fit_and_data_completeness"]["r_free_phenix"] = 0.9999
        self.assertNotEqual(expected_report, mutated_case_report)

        mutated_evidence_report = copy.deepcopy(fresh_report)
        mutated_evidence_report["case_study_1sar"][
            "missing_conflicting_and_inapplicable_evidence"
        ][1]["description"] = "mutated_unrelated_evidence"
        self.assertNotEqual(expected_report, mutated_evidence_report)

        mutated_control_report = copy.deepcopy(fresh_report)
        mutated_control_report["control_cohorts_evaluation"]["cohorts"][
            "unchanged_null"
        ]["per_target_rows"][2]["d_phenix"] = 0.9999
        self.assertNotEqual(expected_report, mutated_control_report)

        case_1sar = fresh_report["case_study_1sar"]
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
        invariance_note = fresh_report["control_cohorts_evaluation"][
            "cross_cohort_findings"
        ]["unchanged_control_invariance"]
        self.assertIn("2VXN", invariance_note)
        self.assertIn("(+0.0214 / +0.0220)", invariance_note)
        self.assertIn("(-0.0122)", invariance_note)
        self.assertNotIn("+0.0053", invariance_note)
        self.assertNotIn("+0.0067", invariance_note)
        self.assertIn("9TXE", invariance_note)
        self.assertNotIn("8RFF", invariance_note)

        protonation_note = fresh_report["control_cohorts_evaluation"][
            "cross_cohort_findings"
        ]["recovered_control_protonation_contrast"]
        self.assertIn("multi-factor protocol change", protonation_note)
        self.assertIn("BREF ANIS", protonation_note)
        self.assertNotIn("isolates the effect", protonation_note)

    def test_null_control_2vxn_narrative_derived_from_source_row_and_case_study_sync(
        self,
    ) -> None:
        """Verify #964: 2VXN null-control deltas are derived from negative_control_round3_bench.json rows[2] and synced in case study."""
        self.assertEqual(
            sha256_file(DEFAULT_ROUND3_BENCH), EXPECTED_ROUND3_BENCH_SHA256
        )
        round3_doc = json.loads(DEFAULT_ROUND3_BENCH.read_text(encoding="utf-8"))
        row_2vxn = round3_doc["rows"][2]
        self.assertEqual(row_2vxn["pdb_id"], "2VXN")
        self.assertEqual(row_2vxn["subject"], "null")
        self.assertAlmostEqual(row_2vxn["numbers"]["d_phenix"], 0.0214, places=4)
        self.assertAlmostEqual(row_2vxn["numbers"]["d_gemmi"], 0.0220, places=4)
        self.assertAlmostEqual(row_2vxn["numbers"]["d_refmac"], -0.0122, places=4)
        self.assertAlmostEqual(row_2vxn["pre"]["rfree_phenix"], 0.1043, places=4)
        self.assertAlmostEqual(row_2vxn["post"]["rfree_phenix"], 0.1257, places=4)
        self.assertAlmostEqual(row_2vxn["pre"]["rfree_gemmi"], 0.1059, places=4)
        self.assertAlmostEqual(row_2vxn["post"]["rfree_gemmi"], 0.1279, places=4)
        self.assertAlmostEqual(
            row_2vxn["pre"]["refmac"]["r_free"], 0.1712, places=4
        )
        self.assertAlmostEqual(
            row_2vxn["post"]["refmac"]["r_free"], 0.1590, places=4
        )

        # Verify historical BREF ISOT (-0.0122) vs regenerated BREF ANIS (+0.0130) in round9_anis.json
        round9_doc = json.loads(ROUND9_ANIS_JSON_PATH.read_text(encoding="utf-8"))
        r9_2vxn = next(r for r in round9_doc["rows"] if r["pdb_id"] == "2VXN")
        self.assertAlmostEqual(r9_2vxn["paths"]["phenix"]["delta"], 0.0214, places=4)
        self.assertAlmostEqual(r9_2vxn["paths"]["gemmi"]["delta"], 0.0220, places=4)
        self.assertAlmostEqual(r9_2vxn["refmac"]["isot"]["delta"], -0.0122, places=4)
        self.assertAlmostEqual(r9_2vxn["refmac"]["anis"]["delta"], 0.0130, places=4)

        controls = evaluate_control_cohorts()
        invariance = controls["cross_cohort_findings"]["unchanged_control_invariance"]
        self.assertIn("(+0.0214 / +0.0220)", invariance)
        self.assertIn("(-0.0122)", invariance)
        self.assertNotIn("0.0053", invariance)
        self.assertNotIn("0.0067", invariance)

        # Prove generator dynamically formats the 2VXN null row rather than using a hardcoded narrative copy
        round4_doc = json.loads(DEFAULT_ROUND4_RECOVER.read_text(encoding="utf-8"))
        round10_doc = json.loads(DEFAULT_ROUND10_RECOVER.read_text(encoding="utf-8"))
        synthetic_round3 = copy.deepcopy(round3_doc)
        synthetic_round3["rows"][2]["numbers"]["d_phenix"] = 0.0315
        synthetic_round3["rows"][2]["numbers"]["d_gemmi"] = 0.0325
        synthetic_round3["rows"][2]["numbers"]["d_refmac"] = -0.0199
        with mock.patch(
            "assess_refinement._read_verified_control_json",
            side_effect=[
                (synthetic_round3, EXPECTED_ROUND3_BENCH_SHA256),
                (round4_doc, EXPECTED_ROUND4_RECOVER_SHA256),
                (round10_doc, EXPECTED_ROUND10_RECOVER_SHA256),
            ],
        ):
            synthetic_controls = evaluate_control_cohorts()
        synthetic_invariance = synthetic_controls["cross_cohort_findings"][
            "unchanged_control_invariance"
        ]
        self.assertIn("(+0.0315 / +0.0325)", synthetic_invariance)
        self.assertIn("(-0.0199)", synthetic_invariance)

        # Violating the sign-conflict invariant on 2VXN null row must raise ValueError
        bad_sign_round3 = copy.deepcopy(round3_doc)
        bad_sign_round3["rows"][2]["numbers"]["d_refmac"] = 0.0122
        with mock.patch(
            "assess_refinement._read_verified_control_json",
            side_effect=[
                (bad_sign_round3, EXPECTED_ROUND3_BENCH_SHA256),
                (round4_doc, EXPECTED_ROUND4_RECOVER_SHA256),
                (round10_doc, EXPECTED_ROUND10_RECOVER_SHA256),
            ],
        ):
            with self.assertRaisesRegex(
                ValueError, "Expected 2VXN null-control row"
            ):
                evaluate_control_cohorts()

        # Case-study markdown must cite the source-backed 2VXN values and ISOT vs ANIS context
        case_study_text = CASE_STUDY_MD_PATH.read_text(encoding="utf-8")
        self.assertIn("+0.0214 / +0.0220", case_study_text)
        self.assertIn("0.1043 -> 0.1257", case_study_text)
        self.assertIn("0.1059 -> 0.1279", case_study_text)
        self.assertIn("0.1712 -> 0.1590", case_study_text)
        self.assertIn("+0.0130", case_study_text)
        self.assertNotIn("0.0053", case_study_text)
        self.assertNotIn("0.0067", case_study_text)

    def test_round7_archive_attribution_and_dated_correction_audit_trail(self) -> None:
        """Verify #1003: archive log/report hashes and lines, corrected Round 7 narrative, and dated correction note."""
        self.assertEqual(
            sha256_file(ASSESSMENT_JSON_PATH),
            EXPECTED_FROZEN_ASSESSMENT_JSON_SHA256,
        )
        self.assertEqual(sha256_file(DEFAULT_ARCHIVE), EXPECTED_1SAR_ARCHIVE_SHA256)

        with zipfile.ZipFile(DEFAULT_ARCHIVE, "r") as zf:
            names = zf.namelist()
            self.assertEqual(
                [n for n in names if "round7" in n.lower()],
                [],
            )
            log_bytes = zf.read("claude_iterations.log")
            report_bytes = zf.read("final_report.md")

        self.assertEqual(
            hashlib.sha256(log_bytes).hexdigest(), EXPECTED_CLAUDE_LOG_SHA256
        )
        self.assertEqual(
            hashlib.sha256(report_bytes).hexdigest(),
            EXPECTED_FINAL_REPORT_MD_SHA256,
        )
        log_lines = log_bytes.decode("utf-8").splitlines()
        report_lines = report_bytes.decode("utf-8").splitlines()

        self.assertIn("159 waters, 1 Ca²⁺, 1 Na⁺, 1 SO4.", log_lines[509])
        self.assertIn(
            "(1654 atoms, 192 residues, 159 waters, 1 Ca²⁺, 1 Na⁺, 1 SO₄)",
            log_lines[751],
        )
        self.assertNotIn("heavy atoms", log_lines[751])
        self.assertIn(
            "removal of the disordered chain B sulfate",
            report_lines[69],
        )
        self.assertEqual(
            report_lines[149].strip(),
            "| **Ligands (SO₄)** | 2 | 1 | −1 (removed disordered) |",
        )

        case_1sar = assess_1sar_case_study()
        r7_traj = case_1sar["change_relative_to_input"][
            "model_composition_and_experimental_fit_trajectory"
        ]["r_factor_trajectory_across_retained_eval_and_logs"][
            "round7_log_reported_unarchived"
        ]
        self.assertIsNone(r7_traj["archive_member"])
        self.assertEqual(
            r7_traj["source"],
            "claude_iterations.log:510 (coordinate file absent from archive)",
        )

        r7_boundary = case_1sar[
            "missing_conflicting_and_inapplicable_evidence"
        ][0]
        self.assertEqual(
            r7_boundary["id"], "1sar_round7_coordinates_absent_from_archive"
        )
        desc = r7_boundary["description"]
        self.assertIn("1,654 atoms reported in the log", desc)
        self.assertIn("1 SO4", desc)
        self.assertIn(
            "final_report.md:70, :150 describes removal of the disordered chain-B sulfate (ligand SO4 count 2 -> 1), not a restored B:97:SO4",
            desc,
        )
        self.assertIn(
            "unverified log/report claims rather than measured coordinate inventory",
            desc,
        )
        self.assertNotIn("1,654 heavy atoms", desc)
        self.assertNotIn("and restored B:97:SO4", desc)

        self.assertTrue(SOURCE_CORRECTIONS_MD_PATH.is_file())
        corr_text = SOURCE_CORRECTIONS_MD_PATH.read_text(encoding="utf-8")
        provenance_boundary_line = next(
            line
            for line in corr_text.splitlines()
            if line.startswith("- **Provenance boundary:**")
        )
        self.assertIn(
            "the claimed `1SAR` Round 7 coordinate file is absent from the retained archive, so its reported inventory cannot be independently verified from retained coordinates",
            provenance_boundary_line,
        )
        self.assertNotIn(
            "no unarchived coordinate file exists",
            provenance_boundary_line,
        )
        for required_token in (
            "ref/research/data/refinement_assessment_1sar_and_controls_2026-10-18.json",
            EXPECTED_FROZEN_ASSESSMENT_JSON_SHA256,
            "/case_study_1sar/missing_conflicting_and_inapplicable_evidence/0/description",
            "1sar_round7_coordinates_absent_from_archive",
            "/control_cohorts_evaluation/cross_cohort_findings/unchanged_control_invariance",
            EXPECTED_1SAR_ARCHIVE_SHA256,
            EXPECTED_CLAUDE_LOG_SHA256,
            EXPECTED_FINAL_REPORT_MD_SHA256,
            EXPECTED_ROUND3_BENCH_SHA256,
            "1,654 atoms reported in the log",
            "#1000",
            "PR #998",
        ):
            self.assertIn(required_token, corr_text)

    def test_round2_enrolled_and_screened_stratum_vs_actual_resolution_counts(
        self,
    ) -> None:
        """Verify #987: negative_control_round2.md distinguishes inherited strata (21/2 screened, 20/2 enrolled) from actual d_min (15 <=0.90, 7 >0.90)."""
        self.assertEqual(
            sha256_file(ROUND2_ENROLLED_JSON_PATH),
            EXPECTED_ROUND2_ENROLLED_SHA256,
        )
        self.assertEqual(
            sha256_file(ROUND2_SCREEN_JSON_PATH),
            EXPECTED_ROUND2_SCREEN_SHA256,
        )
        screen_doc = json.loads(ROUND2_SCREEN_JSON_PATH.read_text(encoding="utf-8"))
        screened_rows = [
            r for r in screen_doc["rows"] if r.get("status") == "screened"
        ]
        self.assertEqual(len(screened_rows), 23)
        self.assertEqual(
            sum(1 for r in screened_rows if r["stratum"] is True), 21
        )
        self.assertEqual(
            sum(1 for r in screened_rows if r["stratum"] is False), 2
        )

        enrolled_doc = json.loads(
            ROUND2_ENROLLED_JSON_PATH.read_text(encoding="utf-8")
        )
        entries = enrolled_doc["entries"]
        self.assertEqual(len(entries), 22)
        self.assertEqual(sum(1 for e in entries if e["stratum"] is True), 20)
        self.assertEqual(sum(1 for e in entries if e["stratum"] is False), 2)
        self.assertEqual(sum(1 for e in entries if e["d_min"] <= 0.90), 15)
        self.assertEqual(sum(1 for e in entries if e["d_min"] > 0.90), 7)
        self.assertTrue(all(e["d_min"] <= 1.00 for e in entries))

        above_with_true = [
            (e["pdb_id"], e["d_min"])
            for e in entries
            if e["stratum"] is True and e["d_min"] > 0.90
        ]
        self.assertEqual(
            above_with_true,
            [
                ("7ATV", 0.96),
                ("6ZWY", 1.00),
                ("8QXQ", 0.94),
                ("6F1O", 0.96),
                ("5KXV", 0.98),
            ],
        )

        round2_md = ROUND2_MD_PATH.read_text(encoding="utf-8")
        for token in (
            "Inherited registered strata (`stratum = true` vs. `stratum = false`)",
            "**21** screened, **20**",
            "**2**\n  screened, **2** enrolled",
            EXPECTED_ROUND2_SCREEN_SHA256,
            EXPECTED_ROUND2_ENROLLED_SHA256,
            "scripts/screen_round1.py:402, 668–669",
            "**15** enrolled entries have `d_min <= 0.90 Å`",
            "**7** enrolled entries have\n  `d_min > 0.90 Å`",
            "`7ATV` (`0.96 Å`)",
            "`6ZWY`\n  (`1.00 Å`)",
            "`8QXQ` (`0.94 Å`)",
            "`6F1O` (`0.96 Å`)",
            "`5KXV` (`0.98 Å`)",
        ):
            self.assertIn(token, round2_md)

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
            "ref/research/refinement_assessment_source_corrections_2026-11-09.md",
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
