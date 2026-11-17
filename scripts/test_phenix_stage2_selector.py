#!/usr/bin/env python3
"""Unit tests for Stage 2 PHENIX outer-loop selector, redactor, and trajectory verifier (scripts/phenix_stage2_selector.py)."""

from __future__ import annotations

import ast
import copy
from decimal import Context, Decimal, localcontext
import hashlib
import json
from pathlib import Path
import sys
from typing import Any
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from phenix_stage2_runtime import (  # noqa: E402
    U08_FAILURE_STATUS_CODES,
    U08_STATUS_CODES,
    UNAVAILABLE_NOT_EXECUTED_MARKERS,
)
from phenix_stage2_selector import (  # noqa: E402
    CANDIDATE_METRIC_NAMES,
    COMPLETED_COMMENSURABLE_STATUS,
    EXPECTED_METRIC_UNITS,
    MAX_LOSSLESS_JSON_INT,
    REGISTRATION_STATUS,
    CandidateSelectionRecord,
    canonical_json_bytes,
    geometry_eligible,
    redact_candidate_for_selection,
    redact_starting_geometry_for_selection,
    select_candidate,
    selection_view,
    stop_decision,
    validate_public_candidate_record,
    validate_readout_contract,
    validate_starting_geometry_record,
    verify_trajectory,
)

SYNTHETIC_TEST_READOUT_CONTRACT: dict[str, dict[str, str]] = {
    "r_work": {
        "producer_id": "gemmi_rfactor_work_fit_v1",
        "readout_id": "T03_r_work_bin_scaled",
        "unit": "fraction",
        "source_receipt_id": "receipt_work_v1",
    },
    "llg_work": {
        "producer_id": "phenix_refine_work_llg_v1",
        "readout_id": "work_llg_readout",
        "unit": "llg_units",
        "source_receipt_id": "receipt_work_v1",
    },
    "molprobity_score": {
        "producer_id": "molprobity_reduce_probe_v1",
        "readout_id": "T05_molprobity_composite",
        "unit": "score",
        "source_receipt_id": "receipt_work_v1",
    },
    "bond_rmsz": {
        "producer_id": "gemmi_rmsz_clibd_mon_v1",
        "readout_id": "T05_bond_rmsz",
        "unit": "rmsz",
        "source_receipt_id": "receipt_work_v1",
    },
    "angle_rmsz": {
        "producer_id": "gemmi_rmsz_clibd_mon_v1",
        "readout_id": "T05_angle_rmsz",
        "unit": "rmsz",
        "source_receipt_id": "receipt_work_v1",
    },
    "clashscore": {
        "producer_id": "molprobity_reduce_probe_v1",
        "readout_id": "T05_clashscore",
        "unit": "clashes_per_1000_atoms",
        "source_receipt_id": "receipt_work_v1",
    },
    "rama_out_percent": {
        "producer_id": "molprobity_ramalyze_v1",
        "readout_id": "T05_ramachandran_outliers_pct",
        "unit": "percent",
        "source_receipt_id": "receipt_work_v1",
    },
}


def _sha256_tag(tag: str) -> str:
    return hashlib.sha256(tag.encode("utf-8")).hexdigest()


def _make_metric(
    metric_name: str,
    value: float | int | Decimal,
    *,
    subject_sha256: str,
    producer_id: str | None = None,
    readout_id: str | None = None,
    source_receipt_id: str = "receipt_work_v1",
) -> dict[str, Any]:
    default_producers = {
        "r_work": ("gemmi_rfactor_work_fit_v1", "T03_r_work_bin_scaled"),
        "llg_work": ("phenix_refine_work_llg_v1", "work_llg_readout"),
        "molprobity_score": (
            "molprobity_reduce_probe_v1",
            "T05_molprobity_composite",
        ),
        "bond_rmsz": ("gemmi_rmsz_clibd_mon_v1", "T05_bond_rmsz"),
        "angle_rmsz": ("gemmi_rmsz_clibd_mon_v1", "T05_angle_rmsz"),
        "clashscore": ("molprobity_reduce_probe_v1", "T05_clashscore"),
        "rama_out_percent": (
            "molprobity_ramalyze_v1",
            "T05_ramachandran_outliers_pct",
        ),
    }
    prod, rd = default_producers[metric_name]
    return {
        "value": value,
        "unit": EXPECTED_METRIC_UNITS[metric_name],
        "producer_id": producer_id or prod,
        "readout_id": readout_id or rd,
        "input_subject_sha256": subject_sha256,
        "source_receipt_id": source_receipt_id,
    }


def _make_start_record(
    *,
    bond_rmsz: float = 0.60,
    angle_rmsz: float = 0.80,
    clashscore: float = 6.0,
    rama_out_percent: float = 0.20,
    r_work: float = 0.2200,
    llg_work: float = 1000.0,
    molprobity_score: float = 1.60,
    include_private_holdout: bool = False,
) -> dict[str, Any]:
    start_sha = _sha256_tag("model:start")
    domain_sha = _sha256_tag("domain:work_hkl")
    rec: dict[str, Any] = {
        "record_type": "starting_geometry_v1",
        "subject_id": "target_anon_01_start",
        "target_id": "target_anon_01",
        "work_reflection_domain_sha256": domain_sha,
        "start_model_sha256": start_sha,
        "metrics": {
            "bond_rmsz": _make_metric(
                "bond_rmsz", bond_rmsz, subject_sha256=start_sha
            ),
            "angle_rmsz": _make_metric(
                "angle_rmsz", angle_rmsz, subject_sha256=start_sha
            ),
            "clashscore": _make_metric(
                "clashscore", clashscore, subject_sha256=start_sha
            ),
            "rama_out_percent": _make_metric(
                "rama_out_percent", rama_out_percent, subject_sha256=start_sha
            ),
            "r_work": _make_metric(
                "r_work", r_work, subject_sha256=start_sha
            ),
            "llg_work": _make_metric(
                "llg_work", llg_work, subject_sha256=start_sha
            ),
            "molprobity_score": _make_metric(
                "molprobity_score", molprobity_score, subject_sha256=start_sha
            ),
        },
    }
    if include_private_holdout:
        rec["r_free"] = 0.2512
        rec["r_sleep"] = 0.2489
        rec["raw_log_text"] = "FINAL R_work = 0.2200 R_free = 0.2512"
        rec["metrics"]["r_free"] = {"value": 0.2512}
        rec["metrics"]["bond_rmsz"]["hidden_r_free_note"] = "0.2512"
    return rec


def _make_candidate_record(
    move_id: str = "move_01",
    move_index: int = 1,
    *,
    status: str = COMPLETED_COMMENSURABLE_STATUS,
    r_work: float = 0.2000,
    llg_work: float = 1250.0,
    molprobity_score: float = 1.40,
    bond_rmsz: float = 0.70,
    angle_rmsz: float = 0.95,
    clashscore: float = 5.5,
    rama_out_percent: float = 0.40,
    include_private_holdout: bool = False,
    holdout_r_free: float = 0.2400,
    holdout_r_sleep: float = 0.2380,
) -> dict[str, Any]:
    cand_sha = _sha256_tag(f"model:{move_id}:{move_index}")
    domain_sha = _sha256_tag("domain:work_hkl")
    rec: dict[str, Any] = {
        "record_type": "candidate_selection_v1",
        "move_id": move_id,
        "move_index": move_index,
        "status": status,
        "subject_id": "target_anon_01_start",
        "target_id": "target_anon_01",
        "work_reflection_domain_sha256": domain_sha,
        "candidate_model_sha256": cand_sha,
        "metrics": {
            "r_work": _make_metric(
                "r_work", r_work, subject_sha256=cand_sha
            ),
            "llg_work": _make_metric(
                "llg_work", llg_work, subject_sha256=cand_sha
            ),
            "molprobity_score": _make_metric(
                "molprobity_score", molprobity_score, subject_sha256=cand_sha
            ),
            "bond_rmsz": _make_metric(
                "bond_rmsz", bond_rmsz, subject_sha256=cand_sha
            ),
            "angle_rmsz": _make_metric(
                "angle_rmsz", angle_rmsz, subject_sha256=cand_sha
            ),
            "clashscore": _make_metric(
                "clashscore", clashscore, subject_sha256=cand_sha
            ),
            "rama_out_percent": _make_metric(
                "rama_out_percent", rama_out_percent, subject_sha256=cand_sha
            ),
        },
    }
    if include_private_holdout:
        rec["r_free"] = holdout_r_free
        rec["r_sleep"] = holdout_r_sleep
        rec["free_r_gap"] = holdout_r_free - r_work
        rec["raw_phenix_log"] = (
            f"macro_cycle 5: r_work={r_work:.4f} r_free={holdout_r_free:.4f} "
            f"r_sleep={holdout_r_sleep:.4f}"
        )
        rec["raw_log_sha256"] = _sha256_tag(rec["raw_phenix_log"])
        rec["parameter_block_eff"] = "refinement.main.number_of_macro_cycles=5"
        rec["metrics"]["r_free"] = {"value": holdout_r_free}
        rec["metrics"]["r_sleep"] = {"value": holdout_r_sleep}
        rec["metrics"]["r_work"]["private_audit_log_excerpt"] = (
            f"r_free={holdout_r_free}"
        )
    return rec


class TestPhenixStage2Selector(unittest.TestCase):
    """Test suite for scripts/phenix_stage2_selector.py."""

    def test_redaction_strips_holdout_and_holdout_mutations_never_change_view_or_choice(
        self,
    ) -> None:
        priv_start = _make_start_record(include_private_holdout=True)
        red_start = selection_view(
            priv_start,
            kind="start",
            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
        )
        self.assertNotIn("r_free", red_start["public_view"])
        self.assertNotIn("r_sleep", red_start["public_view"])
        self.assertNotIn("raw_log_text", red_start["public_view"])
        self.assertNotIn("r_free", red_start["public_view"]["metrics"])

        priv_c1_a = _make_candidate_record(
            "move_01",
            1,
            r_work=0.1980,
            include_private_holdout=True,
            holdout_r_free=0.2100,
            holdout_r_sleep=0.2150,
        )
        priv_c1_b = _make_candidate_record(
            "move_01",
            1,
            r_work=0.1980,
            include_private_holdout=True,
            holdout_r_free=0.3999,
            holdout_r_sleep=0.4100,
        )
        view_a = redact_candidate_for_selection(
            priv_c1_a, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
        )
        view_b = redact_candidate_for_selection(
            priv_c1_b, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
        )
        self.assertEqual(view_a["public_view"], view_b["public_view"])
        self.assertEqual(
            view_a["redacted_view_sha256"], view_b["redacted_view_sha256"]
        )
        self.assertNotIn("r_free", str(view_a["public_view"]).lower())
        self.assertNotIn("r_sleep", str(view_a["public_view"]).lower())

        # Direct public validator rejects unredacted extra fields on top-level or metric dict
        with self.assertRaisesRegex(ValueError, "unknown or unredacted keys"):
            validate_public_candidate_record(
                priv_c1_a, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
            )
        with self.assertRaisesRegex(ValueError, "unknown or unredacted keys"):
            validate_starting_geometry_record(
                priv_start, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
            )

        # Reject holdout token smuggled inside an allowlisted identifier field
        smuggled = _make_candidate_record("move_01", 1)
        smuggled["metrics"]["r_work"]["source_receipt_id"] = "receipt_r_free_01"
        with self.assertRaisesRegex(ValueError, "forbidden holdout token"):
            redact_candidate_for_selection(
                smuggled, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
            )

    def test_geometry_eligible_four_exact_u10_guard_boundaries(self) -> None:
        # Case 1: Floor-dominated start (start=0.60 -> bond cap 1.00; start=0.80 -> angle cap 1.50;
        # start=6.0 -> clash cap max(7.6, 15)=15; start=0.20 -> rama cap max(0.70, 1.0)=1.0)
        start_floor = _make_start_record(
            bond_rmsz=0.60,
            angle_rmsz=0.80,
            clashscore=6.0,
            rama_out_percent=0.20,
        )
        cand_exact_floor = _make_candidate_record(
            bond_rmsz=1.0,
            angle_rmsz=1.5,
            clashscore=15.0,
            rama_out_percent=1.0,
        )
        res_floor = geometry_eligible(
            cand_exact_floor,
            start_floor,
            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
        )
        self.assertTrue(res_floor["eligible"])
        self.assertEqual(res_floor["failed_guards"], ())

        for field, over_val in (
            ("bond_rmsz", 1.0001),
            ("angle_rmsz", 1.5001),
            ("clashscore", 15.0001),
            ("rama_out_percent", 1.0001),
        ):
            with self.subTest(regime="floor", field=field):
                bad_cand = copy.deepcopy(cand_exact_floor)
                bad_cand["metrics"][field]["value"] = over_val
                bad_res = geometry_eligible(
                    bad_cand,
                    start_floor,
                    readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                )
                self.assertFalse(bad_res["eligible"])
                self.assertEqual(bad_res["failed_guards"], (field,))

        # Case 2: Start-dominated regime
        # bond start=1.10 -> cap 1.25 (note: in IEEE-754 float 1.10 + 0.15 == 1.2500000000000002,
        # Decimal gives exact 1.25)
        # angle start=1.40 -> cap 1.60
        # clash start=20.0 -> cap 1.1*20.0 + 1 = 23.0
        # rama start=1.20 -> cap 1.70
        start_high = _make_start_record(
            bond_rmsz=1.10,
            angle_rmsz=1.40,
            clashscore=20.0,
            rama_out_percent=1.20,
        )
        cand_exact_high = _make_candidate_record(
            bond_rmsz=1.25,
            angle_rmsz=1.60,
            clashscore=23.0,
            rama_out_percent=1.70,
        )
        res_high = geometry_eligible(
            cand_exact_high,
            start_high,
            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
        )
        self.assertTrue(res_high["eligible"])

        for field, over_val in (
            ("bond_rmsz", 1.25001),
            ("angle_rmsz", 1.60001),
            ("clashscore", 23.0001),
            ("rama_out_percent", 1.70001),
        ):
            with self.subTest(regime="start_dominated", field=field):
                bad_cand = copy.deepcopy(cand_exact_high)
                bad_cand["metrics"][field]["value"] = over_val
                bad_res = geometry_eligible(
                    bad_cand,
                    start_high,
                    readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                )
                self.assertFalse(bad_res["eligible"])
                self.assertEqual(bad_res["failed_guards"], (field,))

    def test_numeric_domain_rejects_bool_nonfinite_negative_and_bad_units_while_allowing_negative_llg_and_rwork_above_one(
        self,
    ) -> None:
        start = _make_start_record()

        # Negative LLG_work and R_work > 1.0 are valid finite measurements
        cand_neg_llg = _make_candidate_record(
            "move_01", 1, r_work=1.15, llg_work=-420.5
        )
        self.assertTrue(
            geometry_eligible(
                cand_neg_llg,
                start,
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
            )["eligible"]
        )

        # Negative RMSZ, clashscore, MolProbity, R_work, or rama_out_percent > 100 must fail closed
        invalid_metric_values = [
            ("bond_rmsz", -0.01),
            ("angle_rmsz", -0.1),
            ("clashscore", -1.0),
            ("molprobity_score", -0.5),
            ("r_work", -0.001),
            ("rama_out_percent", -0.1),
            ("rama_out_percent", 100.01),
            ("bond_rmsz", False),
            ("clashscore", True),
            ("r_work", float("nan")),
            ("llg_work", float("inf")),
            ("llg_work", float("-inf")),
            ("r_work", "0.2000"),
        ]
        for m_name, bad_val in invalid_metric_values:
            with self.subTest(metric=m_name, bad_val=bad_val):
                bad_cand = _make_candidate_record("move_01", 1)
                bad_cand["metrics"][m_name]["value"] = bad_val
                with self.assertRaises(ValueError):
                    validate_public_candidate_record(
                        bad_cand,
                        readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                    )

        # Wrong unit on rama_out_percent (e.g. fraction instead of percent)
        bad_unit_cand = _make_candidate_record("move_01", 1)
        bad_unit_cand["metrics"]["rama_out_percent"]["unit"] = "fraction"
        with self.assertRaisesRegex(ValueError, "unit must be 'percent'"):
            validate_public_candidate_record(
                bad_unit_cand,
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
            )

        # Producer mismatch between candidate and start / contract
        bad_prod_cand = _make_candidate_record("move_01", 1)
        bad_prod_cand["metrics"]["bond_rmsz"]["producer_id"] = (
            "phenix_model_statistics_cdl_v1"
        )
        with self.assertRaisesRegex(ValueError, "Readout contract mismatch"):
            geometry_eligible(
                bad_prod_cand,
                start,
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
            )

    def test_select_candidate_anchored_tie_group_nontransitive_3_candidate_and_permutation_invariance(
        self,
    ) -> None:
        start = _make_start_record()
        # Non-transitive 3-candidate fixture:
        # c1: R_work = 0.2000 (minimum anchor), LLG = 1000, MP = 1.50
        # c2: R_work = 0.2005 (0.2005 - 0.2000 == 0.0005 <= 0.0005 -> in anchored tie group;
        #     note float 0.2005 - 0.2000 == 0.0005000000000000004 > 0.0005 in IEEE-754 float!),
        #     LLG = 1100, MP = 1.45
        # c3: R_work = 0.2009 (within 0.0004 of c2, but 0.2009 - 0.2000 == 0.0009 > 0.0005 from anchor c1 -> NOT in tie group),
        #     LLG = 5000, MP = 0.80
        c1 = _make_candidate_record(
            "move_01", 1, r_work=0.2000, llg_work=1000.0, molprobity_score=1.50
        )
        c2 = _make_candidate_record(
            "move_02", 2, r_work=0.2005, llg_work=1100.0, molprobity_score=1.45
        )
        c3 = _make_candidate_record(
            "move_03", 3, r_work=0.2009, llg_work=5000.0, molprobity_score=0.80
        )

        # Verify that IEEE-754 float subtraction would have failed 0.2005 - 0.2000 <= 0.0005
        self.assertGreater(0.2005 - 0.2000, 0.0005)

        permutations = [
            [c1, c2, c3],
            [c3, c2, c1],
            [c2, c3, c1],
            [c2, c1, c3],
        ]
        for perm in permutations:
            res = select_candidate(
                perm,
                start,
                tie_group_policy="anchored_at_min_r_work",
                residual_tie_policy="unresolved_tie",
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
            )
            self.assertEqual(res["selection_state"], "selected_unique")
            self.assertEqual(res["selected_move_id"], "move_02")
            self.assertEqual(
                res["tie_group_move_ids"], ("move_01", "move_02")
            )
            self.assertEqual(
                res["eligible_move_ids"], ("move_01", "move_02", "move_03")
            )

    def test_select_candidate_molprobity_tiebreak_and_residual_exact_tie_policies(
        self,
    ) -> None:
        start = _make_start_record()
        # Equal R_work within 0.0005 and equal LLG_work -> lower MolProbity wins
        m1 = _make_candidate_record(
            "move_01", 1, r_work=0.1950, llg_work=1400.0, molprobity_score=1.35
        )
        m2 = _make_candidate_record(
            "move_02", 2, r_work=0.1953, llg_work=1400.0, molprobity_score=1.20
        )
        res_mp = select_candidate(
            [m1, m2],
            start,
            tie_group_policy="anchored_at_min_r_work",
            residual_tie_policy="unresolved_tie",
            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
        )
        self.assertEqual(res_mp["selection_state"], "selected_unique")
        self.assertEqual(res_mp["selected_move_id"], "move_02")

        # Residual exact tie on (R_work tie group, LLG_work, MolProbity)
        m2_exact = _make_candidate_record(
            "move_02", 2, r_work=0.1953, llg_work=1400.0, molprobity_score=1.35
        )
        res_unres = select_candidate(
            [m2_exact, m1],
            start,
            tie_group_policy="anchored_at_min_r_work",
            residual_tie_policy="unresolved_tie",
            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
        )
        self.assertEqual(res_unres["selection_state"], "unresolved_exact_tie")
        self.assertIsNone(res_unres["selected_move_id"])
        self.assertEqual(res_unres["tied_move_ids"], ("move_01", "move_02"))

        res_canon = select_candidate(
            [m2_exact, m1],
            start,
            tie_group_policy="anchored_at_min_r_work",
            residual_tie_policy="canonical_move_id_asc",
            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
        )
        self.assertEqual(
            res_canon["selection_state"], "selected_by_canonical_id_tiebreak"
        )
        self.assertEqual(res_canon["selected_move_id"], "move_01")
        self.assertEqual(res_canon["tied_move_ids"], ("move_01", "move_02"))

        # Missing policy bindings fail closed
        with self.assertRaisesRegex(ValueError, "tie_group_policy"):
            select_candidate(
                [m1],
                start,
                residual_tie_policy="unresolved_tie",
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
            )
        with self.assertRaisesRegex(ValueError, "residual_tie_policy"):
            select_candidate(
                [m1],
                start,
                tie_group_policy="anchored_at_min_r_work",
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
            )

    def test_select_candidate_excludes_failed_moves_and_returns_no_eligible_when_all_fail(
        self,
    ) -> None:
        start = _make_start_record()
        failed_moves = [
            {
                "move_id": f"move_fail_{idx}",
                "move_index": idx,
                "status": code,
                "target_id": "target_anon_01",
                "subject_id": "target_anon_01_start",
            }
            for idx, code in enumerate(U08_FAILURE_STATUS_CODES, start=1)
        ]
        geom_fail = _make_candidate_record(
            "move_08", 8, r_work=0.1700, clashscore=40.0
        )
        res = select_candidate(
            [*failed_moves, geom_fail],
            start,
            tie_group_policy="anchored_at_min_r_work",
            residual_tie_policy="unresolved_tie",
            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
        )
        self.assertEqual(res["selection_state"], "no_eligible_candidate")
        self.assertIsNone(res["selected_move_id"])
        self.assertEqual(
            len(res["ineligible_by_status"]), len(U08_FAILURE_STATUS_CODES)
        )
        self.assertEqual(len(res["ineligible_by_geometry"]), 1)

    def test_stop_decision_strict_decimal_boundaries_contiguity_and_budget_caps(
        self,
    ) -> None:
        traj_fixture = self._make_valid_trajectory()
        base_ledger = traj_fixture["budget_ledger"]
        base_budget = {
            "budget_ok": True,
            "move_count": 3,
            "total_observed_macro_cycles": 11,
            "total_tokens": 9000,
            "elapsed_seconds": 800.0,
        }

        # Exact boundary test:
        # delta_r_work must be strictly > -0.0005, and delta_clashscore >= -0.5.
        # In binary IEEE-754 float, 0.5 - 0.5005 == -0.0004999999999999449 (> -0.0005),
        # which would falsely satisfy the strict > -0.0005 stagnation inequality if float
        # subtraction were used. In exact Decimal(str(value)), Decimal("0.5") - Decimal("0.5005")
        # == Decimal("-0.0005"), which is NOT > Decimal("-0.0005")!
        self.assertGreater(0.5 - 0.5005, -0.0005)
        pair_exact_minus_5e4 = {
            "move_id": "move_02",
            "move_index": 2,
            "move_status": COMPLETED_COMMENSURABLE_STATUS,
            "reference_id": "move_01",
            "candidate_r_work": 0.5,
            "reference_r_work": 0.5005,
            "candidate_clashscore": 5.5,
            "reference_clashscore": 6.0,  # delta == -0.5 (inclusive >= -0.5)
        }
        pair_after_exact = {
            "move_id": "move_03",
            "move_index": 3,
            "move_status": COMPLETED_COMMENSURABLE_STATUS,
            "reference_id": "move_02",
            "candidate_r_work": 0.4996,
            "reference_r_work": 0.5,  # delta == -0.0004 > -0.0005
            "candidate_clashscore": 5.0,
            "reference_clashscore": 5.5,  # delta == -0.5 >= -0.5
        }
        res_not_stagnant = stop_decision(
            consecutive_delta_pairs=[pair_exact_minus_5e4, pair_after_exact],
            reference_convention="previous_move",
            arm="1b",
            budget_ledger=base_ledger,
            budget_summary=base_budget,
        )
        self.assertFalse(res_not_stagnant["stagnation_triggered"])
        self.assertFalse(res_not_stagnant["should_stop"])
        self.assertTrue(res_not_stagnant["budget_evidence_verified"])

        # Coherent chain where both pairs are strictly > -0.0005 and >= -0.5:
        # Move 1 (0.5005, 6.0) -> Move 2 (0.5001, 5.5) -> Move 3 (0.4997, 5.0)
        # has exact deltas -0.0004 and -0.0004 -> triggers stagnation.
        pair_stagnant_1 = {
            "move_id": "move_02",
            "move_index": 2,
            "move_status": COMPLETED_COMMENSURABLE_STATUS,
            "reference_id": "move_01",
            "candidate_r_work": 0.5001,
            "reference_r_work": 0.5005,  # delta == -0.0004 > -0.0005
            "candidate_clashscore": 5.5,
            "reference_clashscore": 6.0,  # delta == -0.5 >= -0.5
        }
        pair_stagnant_2 = {
            "move_id": "move_03",
            "move_index": 3,
            "move_status": COMPLETED_COMMENSURABLE_STATUS,
            "reference_id": "move_02",
            "candidate_r_work": 0.4997,
            "reference_r_work": 0.5001,  # delta == -0.0004 > -0.0005
            "candidate_clashscore": 5.0,
            "reference_clashscore": 5.5,  # delta == -0.5 >= -0.5
        }
        res_stagnant = stop_decision(
            consecutive_delta_pairs=[pair_stagnant_1, pair_stagnant_2],
            reference_convention="previous_move",
            arm="1b",
            budget_ledger=base_ledger,
            budget_summary=base_budget,
        )
        self.assertTrue(res_stagnant["stagnation_triggered"])
        self.assertTrue(res_stagnant["should_stop"])
        self.assertTrue(res_stagnant["budget_evidence_verified"])

        # Clashscore improvement of -0.5001 (< -0.5) on Move 3 prevents stagnation
        pair_clash_improved = copy.deepcopy(pair_stagnant_2)
        pair_clash_improved["candidate_clashscore"] = 4.9999
        res_clash_ok = stop_decision(
            consecutive_delta_pairs=[pair_stagnant_1, pair_clash_improved],
            reference_convention="previous_move",
            arm="1b",
            budget_ledger=base_ledger,
            budget_summary=base_budget,
        )
        self.assertFalse(res_clash_ok["stagnation_triggered"])

        # Non-contiguous move_index (bridging a gap/failed move) raises ValueError
        pair_gap = copy.deepcopy(pair_stagnant_2)
        pair_gap["move_index"] = 4
        with self.assertRaisesRegex(ValueError, "Non-contiguous move_index"):
            stop_decision(
                consecutive_delta_pairs=[pair_stagnant_1, pair_gap],
                reference_convention="previous_move",
                arm="1b",
                budget_ledger=base_ledger,
            )

        # Missing budget evidence when require_budget_evidence=True raises ValueError
        with self.assertRaisesRegex(
            ValueError, "requires \\(arm, budget_ledger\\) evidence"
        ):
            stop_decision(
                consecutive_delta_pairs=[pair_stagnant_1, pair_stagnant_2],
                reference_convention="previous_move",
            )

        # Verified budget cap exhaustion (25 macro cycles across 5 moves in Arm 1b)
        # surfaces should_stop=True, budget_cap_exhausted=True, budget_violation=False,
        # and budget_evidence_verified=True.
        cap_exhausted_ledger = [
            {
                "move_index": 1,
                "move_kind": "refinement",
                "move_status": "completed",
                "planned_macro_cycles": 5,
                "observed_macro_cycles": 5,
                "role_tokens": {"llm": 1000, "cheap_llm": 200, "command_llm": 200},
                "elapsed_seconds": 200.0,
                "configured_cpu_threads": 8,
                "primary_command_sha256": _sha256_tag("p1"),
                "mechanical_backup_sha256": _sha256_tag("b1"),
                "actual_command_sha256": _sha256_tag("a1"),
                "effective_eff_sha256": _sha256_tag("e1"),
            },
            {
                "move_index": 2,
                "move_kind": "refinement",
                "move_status": "completed",
                "planned_macro_cycles": 5,
                "observed_macro_cycles": 5,
                "role_tokens": {"llm": 1000, "cheap_llm": 200, "command_llm": 200},
                "elapsed_seconds": 400.0,
                "configured_cpu_threads": 8,
                "primary_command_sha256": _sha256_tag("p2"),
                "mechanical_backup_sha256": _sha256_tag("b2"),
                "actual_command_sha256": _sha256_tag("a2"),
                "effective_eff_sha256": _sha256_tag("e2"),
            },
            {
                "move_index": 3,
                "move_kind": "refinement",
                "move_status": "completed",
                "planned_macro_cycles": 5,
                "observed_macro_cycles": 5,
                "role_tokens": {"llm": 1000, "cheap_llm": 200, "command_llm": 200},
                "elapsed_seconds": 600.0,
                "configured_cpu_threads": 8,
                "primary_command_sha256": _sha256_tag("p3"),
                "mechanical_backup_sha256": _sha256_tag("b3"),
                "actual_command_sha256": _sha256_tag("a3"),
                "effective_eff_sha256": _sha256_tag("e3"),
            },
            {
                "move_index": 4,
                "move_kind": "refinement",
                "move_status": "completed",
                "planned_macro_cycles": 5,
                "observed_macro_cycles": 5,
                "role_tokens": {"llm": 1000, "cheap_llm": 200, "command_llm": 200},
                "elapsed_seconds": 800.0,
                "configured_cpu_threads": 8,
                "primary_command_sha256": _sha256_tag("p4"),
                "mechanical_backup_sha256": _sha256_tag("b4"),
                "actual_command_sha256": _sha256_tag("a4"),
                "effective_eff_sha256": _sha256_tag("e4"),
            },
            {
                "move_index": 5,
                "move_kind": "refinement",
                "move_status": "completed",
                "planned_macro_cycles": 5,
                "observed_macro_cycles": 5,
                "role_tokens": {"llm": 1000, "cheap_llm": 200, "command_llm": 200},
                "elapsed_seconds": 1000.0,
                "configured_cpu_threads": 8,
                "primary_command_sha256": _sha256_tag("p5"),
                "mechanical_backup_sha256": _sha256_tag("b5"),
                "actual_command_sha256": _sha256_tag("a5"),
                "effective_eff_sha256": _sha256_tag("e5"),
            },
        ]
        res_cap = stop_decision(
            consecutive_delta_pairs=[pair_exact_minus_5e4],
            reference_convention="previous_move",
            arm="1b",
            budget_ledger=cap_exhausted_ledger,
        )
        self.assertFalse(res_cap["stagnation_triggered"])
        self.assertTrue(res_cap["budget_cap_exhausted"])
        self.assertFalse(res_cap["budget_violation"])
        self.assertTrue(res_cap["budget_evidence_verified"])
        self.assertTrue(res_cap["should_stop"])

        # Issue #1365 regression: canonical runtime ledger with only configured_cpu_threads=4
        # (and all counters below caps) sets budget_violation=True and should_stop=True,
        # while keeping budget_cap_exhausted=False.
        thread_mismatch_ledger = [
            {
                "move_index": 1,
                "move_kind": "refinement",
                "move_status": "completed",
                "planned_macro_cycles": 5,
                "observed_macro_cycles": 5,
                "role_tokens": {"llm": 1000, "cheap_llm": 200, "command_llm": 200},
                "elapsed_seconds": 180.0,
                "configured_cpu_threads": 4,
            }
        ]
        res_thread_viol = stop_decision(
            consecutive_delta_pairs=[],
            reference_convention="previous_move",
            arm="1a",
            budget_ledger=thread_mismatch_ledger,
        )
        self.assertFalse(res_thread_viol["stagnation_triggered"])
        self.assertFalse(res_thread_viol["budget_cap_exhausted"])
        self.assertTrue(res_thread_viol["budget_violation"])
        self.assertTrue(res_thread_viol["budget_evidence_verified"])
        self.assertTrue(res_thread_viol["should_stop"])
        self.assertEqual(
            res_thread_viol["stop_reasons"],
            ("budget_violation:['configured_cpu_threads_mismatch']",),
        )

        # Genuine over-cap runtime ledger sets both budget_cap_exhausted=True and budget_violation=True
        over_cap_ledger = [
            {
                "move_index": 1,
                "move_kind": "refinement",
                "move_status": "completed",
                "planned_macro_cycles": 5,
                "observed_macro_cycles": 5,
                "role_tokens": {"llm": 150000, "cheap_llm": 1, "command_llm": 0},
                "elapsed_seconds": 180.0,
                "configured_cpu_threads": 8,
            }
        ]
        res_over_cap = stop_decision(
            consecutive_delta_pairs=[],
            reference_convention="previous_move",
            arm="1a",
            budget_ledger=over_cap_ledger,
        )
        self.assertFalse(res_over_cap["stagnation_triggered"])
        self.assertTrue(res_over_cap["budget_cap_exhausted"])
        self.assertTrue(res_over_cap["budget_violation"])
        self.assertTrue(res_over_cap["budget_evidence_verified"])
        self.assertTrue(res_over_cap["should_stop"])

    @staticmethod
    def _make_move_provenance_bundle(
        move_idx: int, macro_cycles: int
    ) -> dict[str, str]:
        prim_txt = (
            f"phenix.refine model.pdb data.mtz "
            f"xray_data.r_free_flags.generate=False "
            f"main.number_of_macro_cycles={macro_cycles} "
            f"output.prefix=\"move_0{move_idx}_prim\""
        )
        back_txt = (
            f"phenix.refine model.pdb data.mtz "
            f"xray_data.r_free_flags.generate=False "
            f"main.number_of_macro_cycles={macro_cycles} "
            f"output.prefix=\"move_0{move_idx}_back\""
        )
        act_txt = (
            f"phenix.refine model.pdb data.mtz "
            f"xray_data.r_free_flags.generate=False "
            f"main.number_of_macro_cycles={macro_cycles} "
            f"output.prefix=\"move_0{move_idx}_act\""
        )
        eff_txt = (
            "data_manager {\n"
            "  fmodel {\n"
            "    xray_data {\n"
            "      r_free_flags {\n"
            "        generate = False\n"
            "      }\n"
            "    }\n"
            "  }\n"
            "}\n"
            "refinement {\n"
            "  main {\n"
            f"    number_of_macro_cycles = {macro_cycles}\n"
            "  }\n"
            f"  output.prefix = \"move_0{move_idx}_act\"\n"
            "}\n"
        )
        return {
            "primary_command": prim_txt,
            "primary_command_sha256": _sha256_tag(prim_txt),
            "mechanical_backup": back_txt,
            "mechanical_backup_sha256": _sha256_tag(back_txt),
            "actual_command": act_txt,
            "actual_command_sha256": _sha256_tag(act_txt),
            "effective_eff": eff_txt,
            "effective_eff_sha256": _sha256_tag(eff_txt),
        }

    def _make_valid_trajectory(self) -> dict[str, Any]:
        start_priv = _make_start_record(
            r_work=0.2100, clashscore=6.0, include_private_holdout=True
        )
        start_red = redact_starting_geometry_for_selection(
            start_priv, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
        )

        m1_priv = _make_candidate_record(
            "move_01",
            1,
            r_work=0.2000,
            llg_work=1200.0,
            molprobity_score=1.45,
            clashscore=5.6,
            include_private_holdout=True,
        )
        m2_priv = _make_candidate_record(
            "move_02",
            2,
            r_work=0.1998,
            llg_work=1260.0,
            molprobity_score=1.40,
            clashscore=5.4,
            include_private_holdout=True,
        )
        m3_priv = _make_candidate_record(
            "move_03",
            3,
            r_work=0.1997,
            llg_work=1270.0,
            molprobity_score=1.38,
            clashscore=5.2,
            include_private_holdout=True,
        )

        flag_sha = _sha256_tag("partition:r_free")
        sleep_sha = _sha256_tag("partition:r_sleep")
        snap_sha = _sha256_tag("binding:shared_snapshot")

        prov_by_idx = {
            1: self._make_move_provenance_bundle(1, 5),
            2: self._make_move_provenance_bundle(2, 3),
            3: self._make_move_provenance_bundle(3, 3),
        }

        moves: list[dict[str, Any]] = []
        for idx, m_priv in enumerate([m1_priv, m2_priv, m3_priv], start=1):
            red = redact_candidate_for_selection(
                m_priv, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
            )
            prov = prov_by_idx[idx]
            m_entry = copy.deepcopy(m_priv)
            m_entry.update(
                {
                    "flag_partition_sha256": flag_sha,
                    "sleep_partition_sha256": sleep_sha,
                    "snapshot_binding_sha256": snap_sha,
                    "flag_guard_verified": True,
                    "actual_command_sha256": prov["actual_command_sha256"],
                    "effective_eff_sha256": prov["effective_eff_sha256"],
                    "claimed_redacted_view_sha256": red["redacted_view_sha256"],
                }
            )
            moves.append(m_entry)

        budget_ledger = [
            {
                "move_index": 1,
                "move_kind": "refinement",
                "move_status": "completed",
                "planned_macro_cycles": 5,
                "observed_macro_cycles": 5,
                "role_tokens": {"llm": 2000, "cheap_llm": 500, "command_llm": 500},
                "elapsed_seconds": 300.0,
                "configured_cpu_threads": 8,
                **prov_by_idx[1],
            },
            {
                "move_index": 2,
                "move_kind": "refinement",
                "move_status": "completed",
                "planned_macro_cycles": 3,
                "observed_macro_cycles": 3,
                "role_tokens": {"llm": 2000, "cheap_llm": 500, "command_llm": 500},
                "elapsed_seconds": 550.0,
                "configured_cpu_threads": 8,
                **prov_by_idx[2],
            },
            {
                "move_index": 3,
                "move_kind": "refinement",
                "move_status": "completed",
                "planned_macro_cycles": 3,
                "observed_macro_cycles": 3,
                "role_tokens": {"llm": 2000, "cheap_llm": 500, "command_llm": 500},
                "elapsed_seconds": 800.0,
                "configured_cpu_threads": 8,
                **prov_by_idx[3],
            },
        ]

        return {
            "arm": "1b",
            "target_id": "target_anon_01",
            "subject_id": "target_anon_01_start",
            "start_model_sha256": start_priv["start_model_sha256"],
            "work_reflection_domain_sha256": start_priv[
                "work_reflection_domain_sha256"
            ],
            "flag_partition_sha256": flag_sha,
            "sleep_partition_sha256": sleep_sha,
            "snapshot_binding_sha256": snap_sha,
            "tie_group_policy": "anchored_at_min_r_work",
            "residual_tie_policy": "unresolved_tie",
            "reference_convention": "previous_move",
            "start_record": start_priv,
            "claimed_start_redacted_view_sha256": start_red[
                "redacted_view_sha256"
            ],
            "moves": moves,
            "budget_ledger": budget_ledger,
            "claimed_selection": {
                "selection_state": "selected_unique",
                "selected_move_id": "move_03",
                "tied_move_ids": ("move_03",),
            },
            "claimed_stop_decision": {
                "should_stop": True,
                "stagnation_triggered": True,
                "budget_cap_exhausted": False,
            },
            "require_compliant_completion": True,
        }

    def test_verify_trajectory_succeeds_and_rejects_tampering_budget_or_prefix_cap_exhaustion(
        self,
    ) -> None:
        traj = self._make_valid_trajectory()
        res = verify_trajectory(
            traj, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
        )
        self.assertTrue(res["trajectory_ok"])
        self.assertTrue(res["compliant_completion_verified"])
        self.assertEqual(res["scientific_arm_completion"], "not_assessed")
        self.assertEqual(res["registration_status"], REGISTRATION_STATUS)

        # Mutating ONLY private held-out values in moves[1] does not break redacted hash or selection
        traj_holdout_mut = copy.deepcopy(traj)
        traj_holdout_mut["moves"][1]["r_free"] = 0.4567
        traj_holdout_mut["moves"][1]["raw_phenix_log"] = "CHANGED_R_FREE=0.4567"
        res_holdout_mut = verify_trajectory(
            traj_holdout_mut, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
        )
        self.assertEqual(
            res["replayed_selection"]["selected_move_id"],
            res_holdout_mut["replayed_selection"]["selected_move_id"],
        )

        # Tampering with claimed_redacted_view_sha256 fails closed
        traj_bad_sha = copy.deepcopy(traj)
        traj_bad_sha["moves"][0]["claimed_redacted_view_sha256"] = _sha256_tag(
            "tampered"
        )
        with self.assertRaisesRegex(
            ValueError, "redacted_view_sha256 mismatch"
        ):
            verify_trajectory(
                traj_bad_sha, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
            )

        # Tampering with claimed_selection fails closed
        traj_bad_sel = copy.deepcopy(traj)
        traj_bad_sel["claimed_selection"]["selected_move_id"] = "move_01"
        with self.assertRaisesRegex(
            ValueError, "claimed_selection does not match"
        ):
            verify_trajectory(
                traj_bad_sel, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
            )

        # Tampering with flag_guard_verified fails closed
        traj_bad_flag = copy.deepcopy(traj)
        traj_bad_flag["moves"][2]["flag_guard_verified"] = False
        with self.assertRaisesRegex(ValueError, "flag_guard_verified"):
            verify_trajectory(
                traj_bad_flag, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
            )

        # Earlier-prefix budget violation (Move 1 observed_macro_cycles != 5 before Move 2)
        # is rejected by the prefix budget guard before Move 2
        traj_bad_prefix_budget = copy.deepcopy(traj)
        traj_bad_prefix_budget["budget_ledger"][0]["observed_macro_cycles"] = 4
        with self.assertRaisesRegex(
            ValueError, "already violated U12 budget before move 2"
        ):
            verify_trajectory(
                traj_bad_prefix_budget,
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
            )

        # Terminal-move budget violation (where all prior prefixes 1..1 and 1..2 are compliant)
        # reaches and fails the final budget_ok is False check
        traj_bad_budget = copy.deepcopy(traj)
        traj_bad_budget["budget_ledger"][2]["configured_cpu_threads"] = 4
        with self.assertRaisesRegex(ValueError, "U12 budget_ok is False"):
            verify_trajectory(
                traj_bad_budget,
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
            )

        # Prefix cap exhaustion: Move 2 reaches 150,000 tokens exactly, Move 3 uses 0 tokens
        # (budget_ok on full 3-move ledger would be True, but prefix 1..2 already exhausted token cap!)
        traj_prefix_cap = copy.deepcopy(traj)
        traj_prefix_cap["budget_ledger"][1]["role_tokens"] = {
            "llm": 146000,
            "cheap_llm": 500,
            "command_llm": 500,
        }
        traj_prefix_cap["budget_ledger"][2]["role_tokens"] = {
            "llm": 0,
            "cheap_llm": 0,
            "command_llm": 0,
        }
        with self.assertRaisesRegex(
            ValueError, "already exhausted U12 cap"
        ):
            verify_trajectory(
                traj_prefix_cap,
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
            )

    def test_verify_trajectory_retains_terminal_failed_move_without_selecting_it(
        self,
    ) -> None:
        traj = self._make_valid_trajectory()
        prov3 = self._make_move_provenance_bundle(3, 3)
        # Replace Move 3 with a terminal failed move (aborted_before_execution)
        traj["moves"][2] = {
            "move_id": "move_03",
            "move_index": 3,
            "status": "FAIL_PROCESS_CRASH_OR_NONZERO_EXIT",
            "target_id": "target_anon_01",
            "subject_id": "target_anon_01_start",
            "work_reflection_domain_sha256": traj[
                "work_reflection_domain_sha256"
            ],
            "flag_partition_sha256": traj["flag_partition_sha256"],
            "sleep_partition_sha256": traj["sleep_partition_sha256"],
            "snapshot_binding_sha256": traj["snapshot_binding_sha256"],
            "flag_guard_verified": "incomplete",
        }
        traj["budget_ledger"][2] = {
            "move_index": 3,
            "move_kind": "refinement",
            "move_status": "aborted_before_execution",
            "planned_macro_cycles": 3,
            "observed_macro_cycles": 0,
            "role_tokens": {"llm": 500, "cheap_llm": 0, "command_llm": 0},
            "elapsed_seconds": 600.0,
            "configured_cpu_threads": 8,
            "primary_command": prov3["primary_command"],
            "primary_command_sha256": prov3["primary_command_sha256"],
            "mechanical_backup": prov3["mechanical_backup"],
            "mechanical_backup_sha256": prov3["mechanical_backup_sha256"],
            "actual_command": "not_executed",
            "effective_eff": "not_executed",
        }
        traj["claimed_selection"] = {
            "selection_state": "selected_unique",
            "selected_move_id": "move_02",
            "tied_move_ids": ("move_02",),
        }
        traj["claimed_stop_decision"] = {
            "should_stop": False,
            "stagnation_triggered": False,
            "budget_cap_exhausted": False,
        }
        traj["require_compliant_completion"] = False

        res = verify_trajectory(
            traj, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
        )
        self.assertTrue(res["trajectory_ok"])
        self.assertEqual(res["trajectory_state"], "retained_with_failed_move")
        self.assertFalse(res["compliant_completion_verified"])
        self.assertEqual(
            res["replayed_selection"]["selected_move_id"], "move_02"
        )
        self.assertEqual(
            res["verified_moves"][2]["flag_guard_verified"], "incomplete"
        )
        self.assertTrue(res["verified_moves"][2]["flag_guard_incomplete"])

        # If require_compliant_completion=True, a trajectory with a failed move raises ValueError
        traj["require_compliant_completion"] = True
        with self.assertRaisesRegex(
            ValueError, "Trajectory did not achieve compliant completion"
        ):
            verify_trajectory(
                traj, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
            )

        # Issue #1370 regression: terminal INCOMMENSURABLE_REFLECTION_DROP_OR_DOMAIN_CHANGE
        # with a completed, budget-compliant ledger (move_status='completed') and valid
        # source-bound False proof is retained as retained_with_failed_move, excluded from
        # selection, compliant_completion_verified=False, scientific_arm_completion='not_assessed'.
        traj_incomm = self._make_valid_trajectory()
        traj_incomm["moves"][2] = {
            "move_id": "move_03",
            "move_index": 3,
            "status": "INCOMMENSURABLE_REFLECTION_DROP_OR_DOMAIN_CHANGE",
            "target_id": "target_anon_01",
            "subject_id": "target_anon_01_start",
            "work_reflection_domain_sha256": traj_incomm[
                "work_reflection_domain_sha256"
            ],
            "flag_partition_sha256": traj_incomm["flag_partition_sha256"],
            "sleep_partition_sha256": traj_incomm["sleep_partition_sha256"],
            "snapshot_binding_sha256": traj_incomm["snapshot_binding_sha256"],
            "flag_guard_verified": True,
        }
        traj_incomm["claimed_selection"] = {
            "selection_state": "selected_unique",
            "selected_move_id": "move_02",
            "tied_move_ids": ("move_02",),
        }
        traj_incomm["claimed_stop_decision"] = {
            "should_stop": False,
            "stagnation_triggered": False,
            "budget_cap_exhausted": False,
        }
        traj_incomm["require_compliant_completion"] = False

        res_incomm = verify_trajectory(
            traj_incomm, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
        )
        self.assertTrue(res_incomm["trajectory_ok"])
        self.assertEqual(
            res_incomm["trajectory_state"], "retained_with_failed_move"
        )
        self.assertFalse(res_incomm["compliant_completion_verified"])
        self.assertEqual(
            res_incomm["scientific_arm_completion"], "not_assessed"
        )
        self.assertEqual(
            res_incomm["replayed_selection"]["selected_move_id"], "move_02"
        )
        self.assertEqual(
            [
                (r["move_id"], r["status"])
                for r in res_incomm["replayed_selection"][
                    "ineligible_by_status"
                ]
            ],
            [
                (
                    "move_03",
                    "INCOMMENSURABLE_REFLECTION_DROP_OR_DOMAIN_CHANGE",
                )
            ],
        )
        self.assertIs(res_incomm["verified_moves"][2]["flag_guard_verified"], True)
        self.assertFalse(
            res_incomm["verified_moves"][2]["flag_guard_incomplete"]
        )

        # Forward check preserved: COMPLETED_COMMENSURABLE with non-completed ledger move_status rejects
        traj_comm_failed_ledger = self._make_valid_trajectory()
        traj_comm_failed_ledger["budget_ledger"][2]["move_status"] = "failed"
        with self.assertRaisesRegex(
            ValueError,
            "has status='COMPLETED_COMMENSURABLE' but budget_ledger\\[2\\]\\.move_status='failed'",
        ):
            verify_trajectory(
                traj_comm_failed_ledger,
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
            )

    def test_lossless_numeric_domain_and_revalidation_roundtrip_invariance(
        self,
    ) -> None:
        # Issue #1354 regression: high-precision Decimal that cannot round-trip losslessly
        # through JSON float (e.g. Decimal("1.0000000000000000001") where float() is 1.0)
        # must be rejected on first validation so a failed geometry guard can never become
        # selected_unique after to_public_dict() revalidation.
        start_zero = _make_start_record(bond_rmsz=0.0)
        cand_lossy_dec = _make_candidate_record(
            "move_01", 1, bond_rmsz=Decimal("1.0000000000000000001")
        )
        with self.assertRaisesRegex(
            ValueError, "cannot round-trip losslessly"
        ):
            geometry_eligible(
                cand_lossy_dec,
                start_zero,
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
            )
        with self.assertRaisesRegex(
            ValueError, "cannot round-trip losslessly"
        ):
            select_candidate(
                [cand_lossy_dec],
                start_zero,
                tie_group_policy="anchored_at_min_r_work",
                residual_tie_policy="unresolved_tie",
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
            )
        with self.assertRaisesRegex(
            ValueError, "cannot round-trip losslessly"
        ):
            redact_candidate_for_selection(
                cand_lossy_dec, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
            )

        # Large integers outside [-MAX_LOSSLESS_JSON_INT, MAX_LOSSLESS_JSON_INT] are rejected
        for huge_int in (
            MAX_LOSSLESS_JSON_INT + 1,
            -(MAX_LOSSLESS_JSON_INT + 1),
            10**20 + 1,
        ):
            with self.subTest(huge_int=huge_int):
                cand_huge = _make_candidate_record(
                    "move_01", 1, llg_work=huge_int
                )
                with self.assertRaisesRegex(
                    ValueError, "MAX_LOSSLESS_JSON_INT"
                ):
                    validate_public_candidate_record(
                        cand_huge,
                        readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                    )

        # Supported ordinary ints, floats, and lossless Decimals round-trip identically
        # across raw dict, typed CandidateSelectionRecord, public_view, JSON bytes, and selection.
        start_int_float = _make_start_record(
            bond_rmsz=0,
            angle_rmsz=1.0,
            clashscore=6,
            rama_out_percent=Decimal("0.25"),
        )
        cand_int_float = _make_candidate_record(
            "move_01",
            1,
            r_work=Decimal("0.2005"),
            llg_work=1250,
            molprobity_score=1.40,
            bond_rmsz=1,
            angle_rmsz=Decimal("1.5"),
            clashscore=15,
            rama_out_percent=1,
        )
        red_s = redact_starting_geometry_for_selection(
            start_int_float, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
        )
        red_c = redact_candidate_for_selection(
            cand_int_float, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
        )

        # Ordinary int values stay int in public_view; floats stay float
        self.assertIs(
            type(red_c["public_view"]["metrics"]["clashscore"]["value"]), int
        )
        self.assertEqual(
            red_c["public_view"]["metrics"]["clashscore"]["value"], 15
        )
        self.assertIs(
            type(red_c["public_view"]["metrics"]["molprobity_score"]["value"]),
            float,
        )

        # Revalidating from typed record, public_view dict, and parsed JSON bytes gives identical results
        re_from_typed = validate_public_candidate_record(
            red_c["record"], readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
        )
        re_from_pub = validate_public_candidate_record(
            red_c["public_view"],
            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
        )
        re_from_json = validate_public_candidate_record(
            json.loads(
                canonical_json_bytes(red_c["public_view"]).decode("utf-8")
            ),
            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
        )
        self.assertEqual(
            re_from_typed.to_public_dict(), red_c["public_view"]
        )
        self.assertEqual(re_from_pub.to_public_dict(), red_c["public_view"])
        self.assertEqual(re_from_json.to_public_dict(), red_c["public_view"])

        elig_raw = geometry_eligible(
            cand_int_float,
            start_int_float,
            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
        )
        elig_typed = geometry_eligible(
            red_c["record"],
            red_s["record"],
            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
        )
        elig_pub = geometry_eligible(
            red_c["public_view"],
            red_s["public_view"],
            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
        )
        self.assertEqual(elig_raw, elig_typed)
        self.assertEqual(elig_raw, elig_pub)

        sel_raw = select_candidate(
            [cand_int_float],
            start_int_float,
            tie_group_policy="anchored_at_min_r_work",
            residual_tie_policy="unresolved_tie",
            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
        )
        sel_typed = select_candidate(
            [red_c["record"]],
            red_s["record"],
            tie_group_policy="anchored_at_min_r_work",
            residual_tie_policy="unresolved_tie",
            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
        )
        sel_pub = select_candidate(
            [red_c["public_view"]],
            red_s["public_view"],
            tie_group_policy="anchored_at_min_r_work",
            residual_tie_policy="unresolved_tie",
            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
        )
        self.assertEqual(sel_raw, sel_typed)
        self.assertEqual(sel_raw, sel_pub)

    def test_isolated_decimal_context_invariance_across_ambient_precisions(
        self,
    ) -> None:
        # Issue #1355 regression: ambient decimal.localcontext(Context(prec=2)) or default
        # prec=28 must never round guard caps, tie-group differences, or stopping deltas.
        start = _make_start_record(
            bond_rmsz=1.10,  # 1.10 + 0.15 = 1.25 (under prec=2 would round to 1.2!)
            angle_rmsz=1.35,  # 1.35 + 0.20 = 1.55
            clashscore=14.5,  # 1.1 * 14.5 + 1 = 16.95
            rama_out_percent=0.75,  # 0.75 + 0.5 = 1.25
        )
        c1 = _make_candidate_record(
            "move_01",
            1,
            r_work=1e-35,
            llg_work=1000.0,
            molprobity_score=1.50,
            bond_rmsz=1.24,
            angle_rmsz=1.54,
            clashscore=16.94,
            rama_out_percent=1.24,
        )
        c2 = _make_candidate_record(
            "move_02",
            2,
            r_work=0.0005,
            llg_work=2000.0,
            molprobity_score=1.20,
            bond_rmsz=1.24,
            angle_rmsz=1.54,
            clashscore=16.94,
            rama_out_percent=1.24,
        )
        c_above = _make_candidate_record(
            "move_03",
            3,
            r_work=0.0005000000000000001,
            llg_work=9000.0,
            molprobity_score=0.90,
            bond_rmsz=1.24,
            angle_rmsz=1.54,
            clashscore=16.94,
            rama_out_percent=1.24,
        )

        stop_pairs = [
            {
                "move_id": "move_02",
                "move_index": 2,
                "move_status": COMPLETED_COMMENSURABLE_STATUS,
                "reference_id": "move_01",
                "candidate_r_work": 1e-35,
                "reference_r_work": 0.0005,  # exact delta = -0.0004999...9 > -0.0005 (stagnant!)
                "candidate_clashscore": 5.5,
                "reference_clashscore": 6.0,
            },
            {
                "move_id": "move_03",
                "move_index": 3,
                "move_status": COMPLETED_COMMENSURABLE_STATUS,
                "reference_id": "move_02",
                "candidate_r_work": 1e-35,
                "reference_r_work": 1e-35,  # coherent previous_move reference == move_02 candidate
                "candidate_clashscore": 5.0,
                "reference_clashscore": 5.5,
            },
        ]
        traj_ledger = self._make_valid_trajectory()["budget_ledger"]
        budget = {
            "budget_ok": True,
            "move_count": 3,
            "total_observed_macro_cycles": 11,
            "total_tokens": 9000,
            "elapsed_seconds": 800.0,
        }

        baseline_elig = geometry_eligible(
            c1, start, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
        )
        baseline_sel = select_candidate(
            [c1, c2, c_above],
            start,
            tie_group_policy="anchored_at_min_r_work",
            residual_tie_policy="unresolved_tie",
            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
        )
        baseline_stop = stop_decision(
            consecutive_delta_pairs=stop_pairs,
            reference_convention="previous_move",
            arm="1b",
            budget_ledger=traj_ledger,
            budget_summary=budget,
        )

        self.assertTrue(baseline_elig["eligible"])
        self.assertEqual(
            baseline_sel["tie_group_move_ids"], ("move_01", "move_02")
        )
        self.assertEqual(baseline_sel["selected_move_id"], "move_02")
        self.assertTrue(baseline_stop["stagnation_triggered"])

        for prec in (1, 2, 5, 28, 50, 100):
            with self.subTest(ambient_prec=prec):
                with localcontext(Context(prec=prec)):
                    self.assertEqual(
                        geometry_eligible(
                            c1,
                            start,
                            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                        ),
                        baseline_elig,
                    )
                    self.assertEqual(
                        select_candidate(
                            [c1, c2, c_above],
                            start,
                            tie_group_policy="anchored_at_min_r_work",
                            residual_tie_policy="unresolved_tie",
                            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                        ),
                        baseline_sel,
                    )
                    self.assertEqual(
                        stop_decision(
                            consecutive_delta_pairs=stop_pairs,
                            reference_convention="previous_move",
                            arm="1b",
                            budget_ledger=traj_ledger,
                            budget_summary=budget,
                        ),
                        baseline_stop,
                    )

    def test_failed_candidate_header_and_lineage_parity_between_mapping_and_typed_record(
        self,
    ) -> None:
        # Issue #1356 regression: select_candidate must apply identical header and
        # supplied-lineage validation to CandidateSelectionRecord and Mapping inputs
        # BEFORE branching on failure, while retaining honest failed records that omit metrics.
        start = _make_start_record()
        valid_cand = _make_candidate_record("move_02", 2, r_work=0.1980)

        honest_failed_map = {
            "move_id": "move_01",
            "move_index": 1,
            "status": "FAIL_PROCESS_CRASH_OR_NONZERO_EXIT",
            "target_id": "target_anon_01",
            "subject_id": "target_anon_01_start",
        }
        honest_failed_typed = CandidateSelectionRecord(
            move_id="move_01",
            move_index=1,
            status="FAIL_PROCESS_CRASH_OR_NONZERO_EXIT",
            subject_id="target_anon_01_start",
            target_id="target_anon_01",
            work_reflection_domain_sha256=start[
                "work_reflection_domain_sha256"
            ],
            candidate_model_sha256=None,  # type: ignore[arg-type]
            metrics={},
        )
        res_map = select_candidate(
            [honest_failed_map, valid_cand],
            start,
            tie_group_policy="anchored_at_min_r_work",
            residual_tie_policy="unresolved_tie",
            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
        )
        res_typed = select_candidate(
            [honest_failed_typed, valid_cand],
            start,
            tie_group_policy="anchored_at_min_r_work",
            residual_tie_policy="unresolved_tie",
            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
        )
        self.assertEqual(res_map["selected_move_id"], "move_02")
        self.assertEqual(res_typed["selected_move_id"], "move_02")
        self.assertEqual(
            res_map["ineligible_by_status"], res_typed["ineligible_by_status"]
        )

        # Invalid headers/lineage must fail closed identically on both Mapping and CandidateSelectionRecord
        invalid_overrides: list[tuple[str, dict[str, Any]]] = [
            ("holdout_move_id", {"move_id": "r_free_0.25"}),
            ("whitespace_move_id", {"move_id": "move 01"}),
            ("negative_index", {"move_index": -1}),
            ("zero_index", {"move_index": 0}),
            ("bool_index", {"move_index": True}),
            ("invalid_status", {"status": "INVALID_STATUS"}),
            ("wrong_target_id", {"target_id": "other_target_99"}),
            ("wrong_subject_id", {"subject_id": "other_subject_99"}),
            ("holdout_target_id", {"target_id": "target_r_sleep_01"}),
            (
                "wrong_work_domain_sha",
                {"work_reflection_domain_sha256": _sha256_tag("other_domain")},
            ),
            (
                "malformed_work_domain_sha",
                {"work_reflection_domain_sha256": "not_a_sha256"},
            ),
            (
                "malformed_candidate_model_sha",
                {"candidate_model_sha256": "not_a_sha256"},
            ),
        ]
        for label, overrides in invalid_overrides:
            with self.subTest(case=label):
                bad_map = dict(honest_failed_map)
                bad_map.update(overrides)
                with self.assertRaises(ValueError):
                    select_candidate(
                        [bad_map, valid_cand],
                        start,
                        tie_group_policy="anchored_at_min_r_work",
                        residual_tie_policy="unresolved_tie",
                        readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                    )

                typed_kwargs: dict[str, Any] = {
                    "move_id": "move_01",
                    "move_index": 1,
                    "status": "FAIL_PROCESS_CRASH_OR_NONZERO_EXIT",
                    "subject_id": "target_anon_01_start",
                    "target_id": "target_anon_01",
                    "work_reflection_domain_sha256": start[
                        "work_reflection_domain_sha256"
                    ],
                    "candidate_model_sha256": None,
                    "metrics": {},
                }
                typed_kwargs.update(overrides)
                bad_typed = CandidateSelectionRecord(**typed_kwargs)
                with self.assertRaises(ValueError):
                    select_candidate(
                        [bad_typed, valid_cand],
                        start,
                        tie_group_policy="anchored_at_min_r_work",
                        residual_tie_policy="unresolved_tie",
                        readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                    )

    def test_readout_contract_binds_public_metadata_and_rejects_raw_audit_receipt_ids(
        self,
    ) -> None:
        # Issues #1363 and #1366 regression:
        # - Every public entry point requires an explicit caller-supplied out-of-band
        #   readout_contract; missing/None rejects.
        # - Private envelopes that carry changing raw audit receipt IDs and differing holdout
        #   values (while omitting public provenance keys on CANDIDATE_METRIC_NAMES so they
        #   are projected from the explicit caller readout_contract) produce identical
        #   public_view, redacted_view_sha256, and select_candidate output.
        # - Envelope-level self-authorization (changing embedded readout_contract or metric
        #   IDs and claiming freshly recomputed public hashes while caller readout_contract is
        #   held fixed) is rejected.
        start = _make_start_record()
        cand = _make_candidate_record("move_01", 1)
        traj = self._make_valid_trajectory()

        # 0. Missing/None readout_contract rejects at every public entry point
        with self.assertRaisesRegex(ValueError, "readout_contract"):
            validate_readout_contract(None)
        with self.assertRaisesRegex(ValueError, "readout_contract"):
            validate_starting_geometry_record(start)
        with self.assertRaisesRegex(ValueError, "readout_contract"):
            validate_public_candidate_record(cand)
        with self.assertRaisesRegex(ValueError, "readout_contract"):
            redact_starting_geometry_for_selection(start)
        with self.assertRaisesRegex(ValueError, "readout_contract"):
            redact_candidate_for_selection(cand)
        with self.assertRaisesRegex(ValueError, "readout_contract"):
            selection_view(cand, kind="candidate")
        with self.assertRaisesRegex(ValueError, "readout_contract"):
            selection_view(start, kind="start")
        with self.assertRaisesRegex(ValueError, "readout_contract"):
            geometry_eligible(cand, start)
        with self.assertRaisesRegex(ValueError, "readout_contract"):
            select_candidate(
                [cand],
                start,
                tie_group_policy="anchored_at_min_r_work",
                residual_tie_policy="unresolved_tie",
            )
        with self.assertRaisesRegex(ValueError, "readout_contract"):
            verify_trajectory(traj)

        audit_id_20 = f"audit-{_sha256_tag('privateRfree=0.20')}"
        audit_id_25 = f"audit-{_sha256_tag('privateRfree=0.25')}"

        # 1. Private envelopes that carry changing raw audit receipt IDs and differing private
        # holdout slots (with public provenance omitted on CANDIDATE_METRIC_NAMES so it is
        # projected from explicit caller readout_contract) produce identical public_view,
        # redacted_view_sha256, and select_candidate output (#1363 + #1366).
        priv_a = _make_candidate_record(
            "move_01",
            1,
            r_work=0.1980,
            include_private_holdout=True,
            holdout_r_free=0.2000,
            holdout_r_sleep=0.1990,
        )
        priv_b = _make_candidate_record(
            "move_01",
            1,
            r_work=0.1980,
            include_private_holdout=True,
            holdout_r_free=0.2500,
            holdout_r_sleep=0.2490,
        )
        for m_name in CANDIDATE_METRIC_NAMES:
            m_slot_a = priv_a["metrics"][m_name]
            m_slot_a["audit_receipt_id"] = audit_id_20
            m_slot_a["raw_receipt_sha256"] = _sha256_tag("privateRfree=0.20")
            del m_slot_a["source_receipt_id"]
            del m_slot_a["producer_id"]
            del m_slot_a["readout_id"]

            m_slot_b = priv_b["metrics"][m_name]
            m_slot_b["audit_receipt_id"] = audit_id_25
            m_slot_b["raw_receipt_sha256"] = _sha256_tag("privateRfree=0.25")
            del m_slot_b["source_receipt_id"]
            del m_slot_b["producer_id"]
            del m_slot_b["readout_id"]

        # Metadata-free projection without explicit readout_contract must fail closed
        with self.assertRaisesRegex(ValueError, "readout_contract"):
            redact_candidate_for_selection(priv_a)

        red_a = redact_candidate_for_selection(
            priv_a, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
        )
        red_b = redact_candidate_for_selection(
            priv_b, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
        )
        self.assertEqual(red_a["public_view"], red_b["public_view"])
        self.assertEqual(
            red_a["redacted_view_sha256"], red_b["redacted_view_sha256"]
        )
        self.assertEqual(
            red_a["public_view"]["metrics"]["r_work"]["source_receipt_id"],
            "receipt_work_v1",
        )

        sel_a = select_candidate(
            [red_a["public_view"]],
            start,
            tie_group_policy="anchored_at_min_r_work",
            residual_tie_policy="unresolved_tie",
            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
        )
        sel_b = select_candidate(
            [red_b["public_view"]],
            start,
            tie_group_policy="anchored_at_min_r_work",
            residual_tie_policy="unresolved_tie",
            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
        )
        self.assertEqual(sel_a, sel_b)

        # 2. Putting audit-<sha256(privateRfree=...)> or any unbound/contradicting metadata ID
        # into source_receipt_id, producer_id, or readout_id fails closed across redaction,
        # public validation, geometry_eligible, select_candidate, and verify_trajectory.
        for bad_audit_id in (
            audit_id_20,
            audit_id_25,
            "unbound_receipt_v99",
        ):
            with self.subTest(bad_source_receipt_id=bad_audit_id):
                cand_bad_receipt = _make_candidate_record("move_01", 1)
                cand_bad_receipt["metrics"]["r_work"]["source_receipt_id"] = (
                    bad_audit_id
                )
                with self.assertRaisesRegex(
                    ValueError, "Readout contract mismatch"
                ):
                    redact_candidate_for_selection(
                        cand_bad_receipt,
                        readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                    )
                with self.assertRaisesRegex(
                    ValueError, "Readout contract mismatch"
                ):
                    validate_public_candidate_record(
                        cand_bad_receipt,
                        readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                    )
                with self.assertRaisesRegex(
                    ValueError, "Readout contract mismatch"
                ):
                    geometry_eligible(
                        cand_bad_receipt,
                        start,
                        readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                    )
                with self.assertRaisesRegex(
                    ValueError, "Readout contract mismatch"
                ):
                    select_candidate(
                        [cand_bad_receipt],
                        start,
                        tie_group_policy="anchored_at_min_r_work",
                        residual_tie_policy="unresolved_tie",
                        readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                    )

        start_bad_receipt = _make_start_record()
        start_bad_receipt["metrics"]["bond_rmsz"]["source_receipt_id"] = (
            audit_id_20
        )
        with self.assertRaisesRegex(ValueError, "Readout contract mismatch"):
            redact_starting_geometry_for_selection(
                start_bad_receipt,
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
            )
        with self.assertRaisesRegex(ValueError, "Readout contract mismatch"):
            validate_starting_geometry_record(
                start_bad_receipt,
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
            )

        # 3. Attempting to register raw audit prefixes or embedded hex digests in
        # readout_contract itself fails closed in validate_readout_contract.
        for bad_contract_id in (
            audit_id_20,
            "audit_receipt_01",
            "raw-log-receipt",
            "log:phenix_01",
            "private_receipt_01",
            f"receipt_{_sha256_tag('digest')[:16]}",
        ):
            with self.subTest(bad_contract_id=bad_contract_id):
                bad_contract = copy.deepcopy(SYNTHETIC_TEST_READOUT_CONTRACT)
                bad_contract["r_work"]["source_receipt_id"] = bad_contract_id
                with self.assertRaisesRegex(
                    ValueError,
                    "raw/audit receipt or embedded digest",
                ):
                    validate_readout_contract(bad_contract)

        # 4. Explicit caller-bound custom logical readout_contract supplied out-of-band works
        # end-to-end across redaction, geometry_eligible, select_candidate, and verify_trajectory,
        # whereas envelope self-authorization (mutating embedded contract/metric IDs and claiming
        # recomputed hashes while caller readout_contract is held fixed) is rejected.
        custom_contract = copy.deepcopy(SYNTHETIC_TEST_READOUT_CONTRACT)
        for m_spec in custom_contract.values():
            m_spec["source_receipt_id"] = "contract_work_readout_v2"

        traj_custom = self._make_valid_trajectory()
        traj_custom["readout_contract"] = custom_contract
        for m_name in CANDIDATE_METRIC_NAMES:
            traj_custom["start_record"]["metrics"][m_name][
                "source_receipt_id"
            ] = "contract_work_readout_v2"
        traj_custom["claimed_start_redacted_view_sha256"] = (
            redact_starting_geometry_for_selection(
                traj_custom["start_record"], readout_contract=custom_contract
            )["redacted_view_sha256"]
        )
        for move_entry in traj_custom["moves"]:
            for m_name in CANDIDATE_METRIC_NAMES:
                move_entry["metrics"][m_name]["source_receipt_id"] = (
                    "contract_work_readout_v2"
                )
            move_entry["claimed_redacted_view_sha256"] = (
                redact_candidate_for_selection(
                    move_entry, readout_contract=custom_contract
                )["redacted_view_sha256"]
            )

        # With caller contract held fixed at SYNTHETIC_TEST_READOUT_CONTRACT, the rogue
        # self-authorized envelope (even with freshly recomputed hashes) MUST be rejected,
        # both with and without the embedded trajectory["readout_contract"] field.
        with self.assertRaisesRegex(
            ValueError, "contradicts caller-bound out-of-band readout_contract"
        ):
            verify_trajectory(
                traj_custom, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
            )
        traj_custom_no_embedded = copy.deepcopy(traj_custom)
        del traj_custom_no_embedded["readout_contract"]
        with self.assertRaisesRegex(ValueError, "Readout contract mismatch"):
            verify_trajectory(
                traj_custom_no_embedded,
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
            )

        # When the caller explicitly binds custom_contract out-of-band, verification succeeds.
        verified_custom = verify_trajectory(
            traj_custom, readout_contract=custom_contract
        )
        self.assertTrue(verified_custom["trajectory_ok"])

    def test_stop_decision_budget_summary_validation_and_ledger_authority(
        self,
    ) -> None:
        # Issue #1361 regression:
        # 1. Malformed budget_summary mappings (NaN/inf/negative/bool counters, non-bool
        #    budget_ok, or budget_ok=True while exceeding U12 caps) must fail closed even
        #    when require_budget_evidence=False.
        # 2. Complete stop-policy verification (require_budget_evidence=True) requires
        #    canonical (arm, budget_ledger) verified via verify_controller_budget; summary-only
        #    calls cannot claim budget_evidence_verified=True.
        # 3. When both budget_summary and (arm, budget_ledger) are supplied, any mismatch
        #    raises ValueError.
        traj = self._make_valid_trajectory()
        valid_ledger = traj["budget_ledger"]
        valid_summary = {
            "budget_ok": True,
            "move_count": 3,
            "total_observed_macro_cycles": 11,
            "total_tokens": 9000,
            "elapsed_seconds": 800.0,
        }
        coherent_pairs = [
            {
                "move_id": "move_01",
                "move_index": 1,
                "move_status": COMPLETED_COMMENSURABLE_STATUS,
                "reference_id": "start",
                "candidate_r_work": 0.2000,
                "reference_r_work": 0.2100,
                "candidate_clashscore": 5.6,
                "reference_clashscore": 6.0,
            }
        ]

        invalid_summaries: list[tuple[str, dict[str, Any]]] = [
            ("nan_elapsed", {**valid_summary, "elapsed_seconds": float("nan")}),
            ("inf_elapsed", {**valid_summary, "elapsed_seconds": float("inf")}),
            ("neg_elapsed", {**valid_summary, "elapsed_seconds": -1.0}),
            ("bool_elapsed", {**valid_summary, "elapsed_seconds": True}),
            ("neg_move_count", {**valid_summary, "move_count": -5}),
            ("bool_move_count", {**valid_summary, "move_count": True}),
            (
                "neg_macro_cycles",
                {**valid_summary, "total_observed_macro_cycles": -1},
            ),
            (
                "bool_macro_cycles",
                {**valid_summary, "total_observed_macro_cycles": False},
            ),
            ("neg_tokens", {**valid_summary, "total_tokens": -100}),
            ("bool_tokens", {**valid_summary, "total_tokens": True}),
            ("int_budget_ok", {**valid_summary, "budget_ok": 1}),
            (
                "ok_with_violations",
                {
                    **valid_summary,
                    "budget_ok": True,
                    "violation_codes": ["some_violation"],
                },
            ),
            (
                "ok_over_macro_cap",
                {**valid_summary, "total_observed_macro_cycles": 26},
            ),
            ("ok_over_move_cap", {**valid_summary, "move_count": 9}),
            ("ok_over_token_cap", {**valid_summary, "total_tokens": 150001}),
            (
                "ok_over_elapsed_cap",
                {**valid_summary, "elapsed_seconds": 7200.1},
            ),
        ]
        for label, bad_sum in invalid_summaries:
            for req_flag in (True, False):
                with self.subTest(case=label, require_budget_evidence=req_flag):
                    with self.assertRaises(ValueError):
                        stop_decision(
                            consecutive_delta_pairs=coherent_pairs,
                            reference_convention="previous_move",
                            budget_summary=bad_sum,
                            require_budget_evidence=req_flag,
                        )

        # Positive controls (#1367): exact U12 caps (25 cycles, 8 moves, 150000 tokens,
        # 7200.0 elapsed seconds) are compliant with budget_ok=True and trigger
        # budget_cap_exhausted=True, budget_violation=False, should_stop=True in
        # formula-only mode (with budget_evidence_verified=False).
        for cap_label, cap_override in (
            ("exact_macro_cap_25", {"total_observed_macro_cycles": 25}),
            ("exact_move_cap_8", {"move_count": 8}),
            ("exact_token_cap_150000", {"total_tokens": 150000}),
            ("exact_elapsed_cap_7200", {"elapsed_seconds": 7200.0}),
        ):
            with self.subTest(exact_cap=cap_label):
                exact_cap_summary = {**valid_summary, **cap_override}
                res_exact_cap = stop_decision(
                    consecutive_delta_pairs=coherent_pairs,
                    reference_convention="previous_move",
                    budget_summary=exact_cap_summary,
                    require_budget_evidence=False,
                )
                self.assertTrue(res_exact_cap["budget_cap_exhausted"])
                self.assertFalse(res_exact_cap["budget_violation"])
                self.assertFalse(res_exact_cap["budget_evidence_verified"])
                self.assertTrue(res_exact_cap["should_stop"])

        # Summary-only call with require_budget_evidence=True (default) must reject
        with self.assertRaisesRegex(
            ValueError,
            "requires canonical \\(arm, budget_ledger\\) evidence",
        ):
            stop_decision(
                consecutive_delta_pairs=coherent_pairs,
                reference_convention="previous_move",
                budget_summary=valid_summary,
            )

        # Summary-only call with require_budget_evidence=False evaluates formula caps/violations
        # but MUST set budget_evidence_verified=False
        res_unverified = stop_decision(
            consecutive_delta_pairs=coherent_pairs,
            reference_convention="previous_move",
            budget_summary=valid_summary,
            require_budget_evidence=False,
        )
        self.assertFalse(res_unverified["budget_evidence_verified"])
        self.assertFalse(res_unverified["should_stop"])

        # Contradictions between budget_summary and (arm, budget_ledger) must reject
        for field_name, wrong_val in (
            ("budget_ok", False),
            ("move_count", 2),
            ("total_observed_macro_cycles", 10),
            ("total_tokens", 8999),
            ("elapsed_seconds", 799.5),
            ("arm", "1a"),
        ):
            with self.subTest(contradicted_field=field_name):
                contradicting_summary = dict(valid_summary)
                contradicting_summary[field_name] = wrong_val
                with self.assertRaisesRegex(ValueError, "contradicts"):
                    stop_decision(
                        consecutive_delta_pairs=coherent_pairs,
                        reference_convention="previous_move",
                        arm="1b",
                        budget_ledger=valid_ledger,
                        budget_summary=contradicting_summary,
                    )

    def test_stop_decision_reference_continuity_and_bound_reference_evidence(
        self,
    ) -> None:
        # Issue #1362 + Review 1438 regressions:
        # 1. Under reference_convention='previous_move', adjacent pairs must satisfy
        #    pair[i].reference_id == pair[i-1].move_id,
        #    pair[i].reference_r_work == pair[i-1].candidate_r_work, and
        #    pair[i].reference_clashscore == pair[i-1].candidate_clashscore;
        #    Move 1 must have reference_id='start' and Move k > 1 cannot have reference_id='start'.
        # 2. Under reference_convention='start_model', all pairs must have reference_id='start'
        #    and identical (reference_r_work, reference_clashscore).
        # 3. When claiming reference_evidence_verified=True, stop_decision requires bound
        #    candidate records for EVERY evaluated pair and bound records for EVERY referenced
        #    previous move, order-independent lineage agreement across start and candidate
        #    records, and mandatory accepted_incumbent selector replay (including when
        #    reference_id='start' at later moves, with no missing-policy or partial-prefix fallback).
        traj = self._make_valid_trajectory()
        ledger = traj["budget_ledger"]

        pair_m1 = {
            "move_id": "move_01",
            "move_index": 1,
            "move_status": COMPLETED_COMMENSURABLE_STATUS,
            "reference_id": "start",
            "candidate_r_work": 0.2000,
            "reference_r_work": 0.2100,
            "candidate_clashscore": 5.6,
            "reference_clashscore": 6.0,
        }
        pair_m2 = {
            "move_id": "move_02",
            "move_index": 2,
            "move_status": COMPLETED_COMMENSURABLE_STATUS,
            "reference_id": "move_01",
            "candidate_r_work": 0.1998,
            "reference_r_work": 0.2000,
            "candidate_clashscore": 5.4,
            "reference_clashscore": 5.6,
        }
        pair_m3 = {
            "move_id": "move_03",
            "move_index": 3,
            "move_status": COMPLETED_COMMENSURABLE_STATUS,
            "reference_id": "move_02",
            "candidate_r_work": 0.1997,
            "reference_r_work": 0.1998,
            "candidate_clashscore": 5.2,
            "reference_clashscore": 5.4,
        }

        # Formula-only mode (no bound reference records, require_reference_evidence=False)
        # returns reference_evidence_verified=False
        res_formula_only = stop_decision(
            consecutive_delta_pairs=[pair_m2, pair_m3],
            reference_convention="previous_move",
            arm="1b",
            budget_ledger=ledger,
        )
        self.assertFalse(res_formula_only["reference_evidence_verified"])

        # 1. previous_move continuity violations
        bad_ref_id = {**pair_m3, "reference_id": "move_99"}
        with self.assertRaisesRegex(
            ValueError, "previous_move reference_id continuity mismatch"
        ):
            stop_decision(
                consecutive_delta_pairs=[pair_m2, bad_ref_id],
                reference_convention="previous_move",
                arm="1b",
                budget_ledger=ledger,
            )

        bad_start_on_m2 = {**pair_m2, "reference_id": "start"}
        with self.assertRaisesRegex(
            ValueError, "must reference prior move_index=1, not 'start'"
        ):
            stop_decision(
                consecutive_delta_pairs=[bad_start_on_m2, pair_m3],
                reference_convention="previous_move",
                arm="1b",
                budget_ledger=ledger,
            )

        bad_nonstart_on_m1 = {
            **pair_m1,
            "reference_id": "move_00",
        }
        with self.assertRaisesRegex(
            ValueError, "at move_index=1 .* must have reference_id='start'"
        ):
            stop_decision(
                consecutive_delta_pairs=[bad_nonstart_on_m1],
                reference_convention="previous_move",
                arm="1b",
                budget_ledger=ledger,
            )

        bad_self_ref = {**pair_m2, "reference_id": "move_02"}
        with self.assertRaisesRegex(
            ValueError, "cannot equal move_id"
        ):
            stop_decision(
                consecutive_delta_pairs=[bad_self_ref],
                reference_convention="previous_move",
                arm="1b",
                budget_ledger=ledger,
            )

        bad_ref_r = {**pair_m3, "reference_r_work": 0.2050}
        with self.assertRaisesRegex(
            ValueError, "previous_move reference_r_work continuity mismatch"
        ):
            stop_decision(
                consecutive_delta_pairs=[pair_m2, bad_ref_r],
                reference_convention="previous_move",
                arm="1b",
                budget_ledger=ledger,
            )

        bad_ref_clash = {**pair_m3, "reference_clashscore": 9.9}
        with self.assertRaisesRegex(
            ValueError, "previous_move reference_clashscore continuity mismatch"
        ):
            stop_decision(
                consecutive_delta_pairs=[pair_m2, bad_ref_clash],
                reference_convention="previous_move",
                arm="1b",
                budget_ledger=ledger,
            )

        # 2. start_model reference consistency violations
        start_pair_m2 = {
            **pair_m2,
            "reference_id": "start",
            "reference_r_work": 0.2100,
            "reference_clashscore": 6.0,
        }
        start_pair_m3 = {
            **pair_m3,
            "reference_id": "start",
            "reference_r_work": 0.2100,
            "reference_clashscore": 6.0,
        }
        with self.assertRaisesRegex(
            ValueError, "under reference_convention='start_model' must have reference_id='start'"
        ):
            stop_decision(
                consecutive_delta_pairs=[
                    {**start_pair_m2, "reference_id": "move_01"},
                    start_pair_m3,
                ],
                reference_convention="start_model",
                arm="1b",
                budget_ledger=ledger,
            )
        with self.assertRaisesRegex(
            ValueError, "start_model reference metrics mismatch"
        ):
            stop_decision(
                consecutive_delta_pairs=[
                    start_pair_m2,
                    {**start_pair_m3, "reference_r_work": 0.2200},
                ],
                reference_convention="start_model",
                arm="1b",
                budget_ledger=ledger,
            )

        # 3. Bound reference evidence verification (start_record + reference_records)
        start_rec = redact_starting_geometry_for_selection(
            traj["start_record"],
            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
        )["record"]
        move_records = [
            redact_candidate_for_selection(
                m, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
            )["record"]
            for m in traj["moves"]
        ]

        res_bound_prev = stop_decision(
            consecutive_delta_pairs=[pair_m2, pair_m3],
            reference_convention="previous_move",
            arm="1b",
            budget_ledger=ledger,
            start_record=start_rec,
            reference_records=move_records,
            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
            require_reference_evidence=True,
        )
        self.assertTrue(res_bound_prev["reference_evidence_verified"])
        self.assertTrue(res_bound_prev["stagnation_triggered"])

        # Finding 1 regression: incomplete bound candidate/previous records (e.g. only move_01
        # bound while move_02/move_03 are missing, or move_02 missing, or reference_records
        # omitted entirely) must fail closed and never claim reference_evidence_verified=True.
        for incomplete_label, incomplete_refs in (
            ("only_m1_bound", [move_records[0]]),
            ("missing_m2", [move_records[0], move_records[2]]),
            ("missing_m3", [move_records[0], move_records[1]]),
            ("empty_refs", []),
        ):
            with self.subTest(incomplete_refs=incomplete_label):
                with self.assertRaisesRegex(
                    ValueError,
                    "requires a bound candidate record for every evaluated pair",
                ):
                    stop_decision(
                        consecutive_delta_pairs=[pair_m2, pair_m3],
                        reference_convention="previous_move",
                        arm="1b",
                        budget_ledger=ledger,
                        start_record=start_rec,
                        reference_records=incomplete_refs,
                        readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                        require_reference_evidence=True,
                    )

        # Missing prior move_01 in reference_records when first pair starts at move_index=2 rejects
        with self.assertRaisesRegex(
            ValueError, "requires bound record for prior move_index=1"
        ):
            stop_decision(
                consecutive_delta_pairs=[pair_m2, pair_m3],
                reference_convention="previous_move",
                arm="1b",
                budget_ledger=ledger,
                start_record=start_rec,
                reference_records=move_records[1:],  # move_01 omitted!
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                require_reference_evidence=True,
            )

        # Forged move_01 reference_r_work in pair_m2 contradicts bound move_01 record
        with self.assertRaisesRegex(
            ValueError, "contradicts bound prior move record"
        ):
            stop_decision(
                consecutive_delta_pairs=[
                    {**pair_m2, "reference_r_work": 0.1999},
                    pair_m3,
                ],
                reference_convention="previous_move",
                arm="1b",
                budget_ledger=ledger,
                start_record=start_rec,
                reference_records=move_records,
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                require_reference_evidence=True,
            )

        # Forged start_model reference_r_work contradicts bound start_record
        with self.assertRaisesRegex(
            ValueError, "contradicts bound start_record"
        ):
            stop_decision(
                consecutive_delta_pairs=[
                    {**start_pair_m2, "reference_r_work": 0.2500},
                    {**start_pair_m3, "reference_r_work": 0.2500},
                ],
                reference_convention="start_model",
                arm="1b",
                budget_ledger=ledger,
                start_record=start_rec,
                reference_records=move_records,
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                require_reference_evidence=True,
            )

        # Finding 2 regression (accepted_incumbent):
        # - Move 1's explicit 'start' reference is valid with bound start_record and move_01.
        res_inc_m1 = stop_decision(
            consecutive_delta_pairs=[pair_m1],
            reference_convention="accepted_incumbent",
            arm="1b",
            budget_ledger=ledger,
            start_record=start_rec,
            reference_records=[move_records[0]],
            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
            require_reference_evidence=True,
        )
        self.assertTrue(res_inc_m1["reference_evidence_verified"])

        # - At Move 2/Move 3, claiming reference_id='start' when move_01 IS geometry-eligible
        #   must NOT bypass accepted_incumbent replay via the generic start branch!
        forged_start_incumbent_m2 = {
            **pair_m2,
            "reference_id": "start",
            "reference_r_work": 0.2100,
            "reference_clashscore": 6.0,
        }
        with self.assertRaisesRegex(
            ValueError, "contradicts replayed incumbent"
        ):
            stop_decision(
                consecutive_delta_pairs=[forged_start_incumbent_m2],
                reference_convention="accepted_incumbent",
                arm="1b",
                budget_ledger=ledger,
                start_record=start_rec,
                reference_records=move_records[:2],
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                require_reference_evidence=True,
                tie_group_policy="anchored_at_min_r_work",
                residual_tie_policy="unresolved_tie",
            )

        # - Positive control: when move_01 is geometry-ineligible (clashscore=99.0),
        #   replaying accepted_incumbent at Move 2 legitimately selects 'start' and succeeds.
        m1_inelig = redact_candidate_for_selection(
            _make_candidate_record("move_01", 1, r_work=0.1900, clashscore=99.0),
            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
        )["record"]
        res_inc_legit_start = stop_decision(
            consecutive_delta_pairs=[forged_start_incumbent_m2],
            reference_convention="accepted_incumbent",
            arm="1b",
            budget_ledger=ledger,
            start_record=start_rec,
            reference_records=[m1_inelig, move_records[1]],
            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
            require_reference_evidence=True,
            tie_group_policy="anchored_at_min_r_work",
            residual_tie_policy="unresolved_tie",
        )
        self.assertTrue(res_inc_legit_start["reference_evidence_verified"])

        # - Missing tie_group_policy, missing residual_tie_policy, missing start_record,
        #   or partial prior prefix (move_01 omitted when evaluating move_02/move_03)
        #   under accepted_incumbent must fail closed (no missing-policy fallback!).
        with self.assertRaisesRegex(ValueError, "tie_group_policy"):
            stop_decision(
                consecutive_delta_pairs=[pair_m2, pair_m3],
                reference_convention="accepted_incumbent",
                arm="1b",
                budget_ledger=ledger,
                start_record=start_rec,
                reference_records=move_records,
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                require_reference_evidence=True,
                residual_tie_policy="unresolved_tie",
            )
        with self.assertRaisesRegex(ValueError, "residual_tie_policy"):
            stop_decision(
                consecutive_delta_pairs=[pair_m2, pair_m3],
                reference_convention="accepted_incumbent",
                arm="1b",
                budget_ledger=ledger,
                start_record=start_rec,
                reference_records=move_records,
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                require_reference_evidence=True,
                tie_group_policy="anchored_at_min_r_work",
            )
        with self.assertRaisesRegex(ValueError, "start_record is required"):
            stop_decision(
                consecutive_delta_pairs=[pair_m2, pair_m3],
                reference_convention="accepted_incumbent",
                arm="1b",
                budget_ledger=ledger,
                reference_records=move_records,
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                require_reference_evidence=True,
                tie_group_policy="anchored_at_min_r_work",
                residual_tie_policy="unresolved_tie",
            )
        with self.assertRaisesRegex(
            ValueError, "requires complete prior candidate prefix"
        ):
            stop_decision(
                consecutive_delta_pairs=[pair_m2, pair_m3],
                reference_convention="accepted_incumbent",
                arm="1b",
                budget_ledger=ledger,
                start_record=start_rec,
                reference_records=move_records[1:],  # move_01 missing from prefix!
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                require_reference_evidence=True,
                tie_group_policy="anchored_at_min_r_work",
                residual_tie_policy="unresolved_tie",
            )

        # Forged accepted_incumbent reference_id on Move 3 (claiming move_01 instead of incumbent move_02) rejects
        inc_pair_m2 = dict(pair_m2)
        inc_pair_m3_forged = {
            **pair_m3,
            "reference_id": "move_01",
            "reference_r_work": 0.2000,
            "reference_clashscore": 5.6,
        }
        with self.assertRaisesRegex(
            ValueError, "contradicts replayed incumbent"
        ):
            stop_decision(
                consecutive_delta_pairs=[inc_pair_m2, inc_pair_m3_forged],
                reference_convention="accepted_incumbent",
                arm="1b",
                budget_ledger=ledger,
                start_record=start_rec,
                reference_records=move_records,
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                require_reference_evidence=True,
                tie_group_policy="anchored_at_min_r_work",
                residual_tie_policy="unresolved_tie",
            )

        # Finding 3 regression: order-independent lineage validation across reference_records
        # and reference_records['start'].
        start_other_target = _make_start_record(
            r_work=0.2100, clashscore=6.0
        )
        start_other_target["target_id"] = "other_target_99"
        start_other_rec = redact_starting_geometry_for_selection(
            start_other_target,
            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
        )["record"]

        # Order A: candidate A first, then 'start' B
        refs_order_a = {
            "move_01": move_records[0],
            "start": start_other_rec,
        }
        # Order B: 'start' B first, then candidate A
        refs_order_b = {
            "start": start_other_rec,
            "move_01": move_records[0],
        }
        for order_label, mixed_refs in (
            ("candidate_then_start", refs_order_a),
            ("start_then_candidate", refs_order_b),
        ):
            with self.subTest(lineage_order=order_label):
                with self.assertRaisesRegex(ValueError, "lineage .* mismatches"):
                    stop_decision(
                        consecutive_delta_pairs=[pair_m1],
                        reference_convention="previous_move",
                        arm="1b",
                        budget_ledger=ledger,
                        reference_records=mixed_refs,
                        readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                        require_reference_evidence=True,
                    )

        # Coherent positive control: distinct candidate_model_sha256 vs start_model_sha256
        # with matching (target_id, subject_id, work_reflection_domain_sha256) succeeds in both orders.
        for order_label, coherent_refs in (
            (
                "candidate_then_start",
                {"move_01": move_records[0], "start": start_rec},
            ),
            (
                "start_then_candidate",
                {"start": start_rec, "move_01": move_records[0]},
            ),
        ):
            with self.subTest(coherent_order=order_label):
                self.assertNotEqual(
                    move_records[0].candidate_model_sha256,
                    start_rec.start_model_sha256,
                )
                res_coherent = stop_decision(
                    consecutive_delta_pairs=[pair_m1],
                    reference_convention="previous_move",
                    arm="1b",
                    budget_ledger=ledger,
                    reference_records=coherent_refs,
                    readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                    require_reference_evidence=True,
                )
                self.assertTrue(res_coherent["reference_evidence_verified"])

        # Finding 4 regression (#1362 comment 6933997225): bind standalone stop_decision
        # evaluated move_index values to canonical budget_ledger moves and require
        # completed ledger status when budget_ledger is supplied.
        # - Evaluated indices 2/3 against a 1-move ledger reject
        with self.assertRaisesRegex(
            ValueError,
            "move_index=2 is absent from canonical budget_ledger \\(move_count=1\\)",
        ):
            stop_decision(
                consecutive_delta_pairs=[pair_m2, pair_m3],
                reference_convention="previous_move",
                arm="1b",
                budget_ledger=ledger[:1],
                start_record=start_rec,
                reference_records=move_records,
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                require_reference_evidence=True,
            )

        # - Completed pairs against failed or aborted ledger status reject
        ledger_m3_failed = copy.deepcopy(ledger)
        ledger_m3_failed[2]["move_status"] = "failed"
        with self.assertRaisesRegex(
            ValueError,
            "at move_index=3 has move_status='COMPLETED_COMMENSURABLE' but canonical budget_ledger move_status='failed'",
        ):
            stop_decision(
                consecutive_delta_pairs=[pair_m2, pair_m3],
                reference_convention="previous_move",
                arm="1b",
                budget_ledger=ledger_m3_failed,
                start_record=start_rec,
                reference_records=move_records,
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                require_reference_evidence=True,
            )

        ledger_m3_aborted = copy.deepcopy(ledger)
        ledger_m3_aborted[2].update(
            {
                "move_status": "aborted_before_execution",
                "observed_macro_cycles": 0,
                "actual_command": "not_executed",
                "effective_eff": "not_executed",
            }
        )
        del ledger_m3_aborted[2]["actual_command_sha256"]
        del ledger_m3_aborted[2]["effective_eff_sha256"]
        with self.assertRaisesRegex(
            ValueError,
            "at move_index=3 has move_status='COMPLETED_COMMENSURABLE' but canonical budget_ledger move_status='aborted_before_execution'",
        ):
            stop_decision(
                consecutive_delta_pairs=[pair_m2, pair_m3],
                reference_convention="previous_move",
                arm="1b",
                budget_ledger=ledger_m3_aborted,
                start_record=start_rec,
                reference_records=move_records,
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                require_reference_evidence=True,
            )

        # - Valid historical-prefix pairs (move_index=1, 2) with a longer 3-move completed ledger pass
        res_hist_prefix = stop_decision(
            consecutive_delta_pairs=[pair_m1, pair_m2],
            reference_convention="previous_move",
            arm="1b",
            budget_ledger=ledger,
            start_record=start_rec,
            reference_records=move_records,
            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
            require_reference_evidence=True,
        )
        self.assertTrue(res_hist_prefix["budget_evidence_verified"])
        self.assertTrue(res_hist_prefix["reference_evidence_verified"])
        self.assertFalse(res_hist_prefix["stagnation_triggered"])

        # - Explicit no-ledger formula-only call remains supported and unverified
        res_no_ledger_formula = stop_decision(
            consecutive_delta_pairs=[pair_m2, pair_m3],
            reference_convention="previous_move",
            budget_summary={
                "budget_ok": True,
                "move_count": 3,
                "total_observed_macro_cycles": 11,
                "total_tokens": 9000,
                "elapsed_seconds": 800.0,
            },
            require_budget_evidence=False,
        )
        self.assertFalse(res_no_ledger_formula["budget_evidence_verified"])
        self.assertTrue(res_no_ledger_formula["stagnation_triggered"])

    def test_verify_trajectory_prefix_stop_replay_across_all_three_reference_conventions(
        self,
    ) -> None:
        # Issue #1357 regression:
        # - verify_trajectory must replay U10/U12 stopping at EVERY trajectory prefix
        #   1..len(moves) and reject any move executed after an earlier prefix triggered stop.
        # - Baseline 3-move trajectory (start: R=0.2100, clash=6.0; m1: 0.2000/5.6;
        #   m2: 0.1998/5.4; m3: 0.1997/5.2) triggers stagnation at prefix 3 under both
        #   previous_move and accepted_incumbent, so terminal 3-move trajectory succeeds
        #   while appending an improving Move 4 (0.1800/4.0) is rejected.
        # - Under start_model, those 3 moves have start-relative deltas <= -0.0100 and do
        #   not stagnate at prefix 3 (so Move 4 succeeds); a separate start-relative
        #   stagnant 3-move trajectory (m2: 0.2098/5.8, m3: 0.2097/5.7 vs start 0.2100/6.0)
        #   triggers stagnation at prefix 3 under start_model and rejects an appended Move 4.
        base_traj = self._make_valid_trajectory()

        def _append_improving_move_4(traj_in: dict[str, Any]) -> dict[str, Any]:
            t4 = copy.deepcopy(traj_in)
            prov4 = self._make_move_provenance_bundle(4, 3)
            m4_priv = _make_candidate_record(
                "move_04",
                4,
                r_work=0.1800,
                llg_work=1400.0,
                molprobity_score=1.20,
                clashscore=4.0,
                include_private_holdout=True,
            )
            red4 = redact_candidate_for_selection(
                m4_priv, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
            )
            m4_entry = copy.deepcopy(m4_priv)
            m4_entry.update(
                {
                    "flag_partition_sha256": t4["flag_partition_sha256"],
                    "sleep_partition_sha256": t4["sleep_partition_sha256"],
                    "snapshot_binding_sha256": t4["snapshot_binding_sha256"],
                    "flag_guard_verified": True,
                    "actual_command_sha256": prov4["actual_command_sha256"],
                    "effective_eff_sha256": prov4["effective_eff_sha256"],
                    "claimed_redacted_view_sha256": red4[
                        "redacted_view_sha256"
                    ],
                }
            )
            t4["moves"].append(m4_entry)
            t4["budget_ledger"].append(
                {
                    "move_index": 4,
                    "move_kind": "refinement",
                    "move_status": "completed",
                    "planned_macro_cycles": 3,
                    "observed_macro_cycles": 3,
                    "role_tokens": {
                        "llm": 2000,
                        "cheap_llm": 500,
                        "command_llm": 500,
                    },
                    "elapsed_seconds": 1000.0,
                    "configured_cpu_threads": 8,
                    **prov4,
                }
            )
            t4["claimed_selection"] = {
                "selection_state": "selected_unique",
                "selected_move_id": "move_04",
                "tied_move_ids": ("move_04",),
            }
            t4["claimed_stop_decision"] = {
                "should_stop": False,
                "stagnation_triggered": False,
                "budget_cap_exhausted": False,
            }
            return t4

        for conv in ("previous_move", "accepted_incumbent"):
            with self.subTest(reference_convention=conv):
                traj_3 = copy.deepcopy(base_traj)
                traj_3["reference_convention"] = conv
                res_3 = verify_trajectory(
                    traj_3, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
                )
                self.assertTrue(res_3["trajectory_ok"])
                self.assertTrue(
                    res_3["replayed_stop_decision"]["stagnation_triggered"]
                )
                self.assertTrue(res_3["replayed_stop_decision"]["should_stop"])

                traj_4 = _append_improving_move_4(traj_3)
                with self.assertRaisesRegex(
                    ValueError,
                    "Trajectory prefix 1\\.\\.3 already triggered U10/U12 stop .* before move 4",
                ):
                    verify_trajectory(
                        traj_4, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
                    )

        # Under start_model, base_traj's 3 moves do NOT stagnate at prefix 3, so Move 4 is allowed
        traj_start_nonstag = copy.deepcopy(base_traj)
        traj_start_nonstag["reference_convention"] = "start_model"
        traj_start_nonstag["claimed_stop_decision"] = {
            "should_stop": False,
            "stagnation_triggered": False,
            "budget_cap_exhausted": False,
        }
        res_start_3 = verify_trajectory(
            traj_start_nonstag,
            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
        )
        self.assertFalse(res_start_3["replayed_stop_decision"]["should_stop"])
        traj_start_4_ok = _append_improving_move_4(traj_start_nonstag)
        res_start_4 = verify_trajectory(
            traj_start_4_ok, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
        )
        self.assertTrue(res_start_4["trajectory_ok"])
        self.assertEqual(
            res_start_4["replayed_selection"]["selected_move_id"], "move_04"
        )

        # Separate coherent start-relative stagnant 3-move trajectory for start_model:
        # start=(0.2100, 6.0), m1=(0.2000, 5.6), m2=(0.2098, 5.8), m3=(0.2097, 5.7)
        # m2 vs start: delta_r = -0.0002 > -0.0005, delta_clash = -0.2 >= -0.5 (stagnant)
        # m3 vs start: delta_r = -0.0003 > -0.0005, delta_clash = -0.3 >= -0.5 (stagnant)
        traj_start_stag = copy.deepcopy(base_traj)
        traj_start_stag["reference_convention"] = "start_model"
        for idx, (r_val, clash_val, llg_val, mp_val) in enumerate(
            [(0.2098, 5.8, 1180.0, 1.48), (0.2097, 5.7, 1185.0, 1.47)],
            start=1,
        ):
            m_priv = _make_candidate_record(
                f"move_0{idx + 1}",
                idx + 1,
                r_work=r_val,
                llg_work=llg_val,
                molprobity_score=mp_val,
                clashscore=clash_val,
                include_private_holdout=True,
            )
            red_m = redact_candidate_for_selection(
                m_priv, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
            )
            m_entry = copy.deepcopy(m_priv)
            m_entry.update(
                {
                    "flag_partition_sha256": traj_start_stag[
                        "flag_partition_sha256"
                    ],
                    "sleep_partition_sha256": traj_start_stag[
                        "sleep_partition_sha256"
                    ],
                    "snapshot_binding_sha256": traj_start_stag[
                        "snapshot_binding_sha256"
                    ],
                    "flag_guard_verified": True,
                    "actual_command_sha256": traj_start_stag["budget_ledger"][
                        idx
                    ]["actual_command_sha256"],
                    "effective_eff_sha256": traj_start_stag["budget_ledger"][
                        idx
                    ]["effective_eff_sha256"],
                    "claimed_redacted_view_sha256": red_m[
                        "redacted_view_sha256"
                    ],
                }
            )
            traj_start_stag["moves"][idx] = m_entry
        traj_start_stag["claimed_selection"] = {
            "selection_state": "selected_unique",
            "selected_move_id": "move_01",
            "tied_move_ids": ("move_01",),
        }
        traj_start_stag["claimed_stop_decision"] = {
            "should_stop": True,
            "stagnation_triggered": True,
            "budget_cap_exhausted": False,
        }
        res_start_stag_3 = verify_trajectory(
            traj_start_stag, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
        )
        self.assertTrue(
            res_start_stag_3["replayed_stop_decision"]["stagnation_triggered"]
        )
        traj_start_stag_4 = _append_improving_move_4(traj_start_stag)
        with self.assertRaisesRegex(
            ValueError,
            "Trajectory prefix 1\\.\\.3 already triggered U10/U12 stop .* before move 4",
        ):
            verify_trajectory(
                traj_start_stag_4,
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
            )

    def test_verify_trajectory_command_and_eff_provenance_agreement(
        self,
    ) -> None:
        # Issue #1359 regression:
        # Completed move actual_command_sha256 and effective_eff_sha256 (plus any optional
        # text/primary/backup provenance bindings) must agree with the normalized Arm 1b
        # budget_ledger[idx] provenance slots, while preserving honest receipt representations.
        traj = self._make_valid_trajectory()

        # 1. Mutating trajectory.moves[idx].actual_command_sha256 or effective_eff_sha256
        #    without updating budget_ledger[idx] (or vice versa) fails closed.
        for field_name, text_key, slot_label in (
            ("actual_command_sha256", "actual_command", "actual_command SHA-256"),
            ("effective_eff_sha256", "effective_eff", "effective_eff SHA-256"),
        ):
            with self.subTest(mutated_move_field=field_name):
                t_mut_move = copy.deepcopy(traj)
                t_mut_move["moves"][1][field_name] = _sha256_tag("rogue_digest")
                with self.assertRaisesRegex(ValueError, slot_label):
                    verify_trajectory(
                        t_mut_move,
                        readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                    )

            with self.subTest(mutated_ledger_field=field_name):
                t_mut_ledger = copy.deepcopy(traj)
                del t_mut_ledger["budget_ledger"][1][text_key]
                t_mut_ledger["budget_ledger"][1][field_name] = _sha256_tag(
                    "rogue_ledger_digest"
                )
                with self.assertRaisesRegex(ValueError, slot_label):
                    verify_trajectory(
                        t_mut_ledger,
                        readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                    )

        # 2. Optional primary_command_sha256 or mechanical_backup_sha256 on moves[idx]
        #    that contradicts budget_ledger[idx] fails closed.
        for opt_field, opt_label in (
            ("primary_command_sha256", "primary_command SHA-256"),
            ("mechanical_backup_sha256", "mechanical_backup SHA-256"),
        ):
            with self.subTest(optional_move_field=opt_label):
                t_opt = copy.deepcopy(traj)
                t_opt["moves"][0][opt_field] = _sha256_tag("wrong_opt")
                with self.assertRaisesRegex(ValueError, opt_label):
                    verify_trajectory(
                        t_opt, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
                    )

        # 3. Honest Arm 1b ledger representations (raw UTF-8 text, text+sha256, nested
        #    arm1b_provenance, and typed slot mappings) whose normalized SHA-256 matches
        #    moves[idx] succeed and record explicit provenance_representations.
        t_honest_forms = copy.deepcopy(traj)
        cmd1_txt = (
            "phenix.refine model.pdb data.mtz "
            "xray_data.r_free_flags.generate=False "
            "main.number_of_macro_cycles=5"
        )
        eff1_txt = (
            "data_manager.fmodel.xray_data.r_free_flags.generate = False\n"
            "refinement.main.number_of_macro_cycles = 5\n"
        )
        cmd1_sha = _sha256_tag(cmd1_txt)
        eff1_sha = _sha256_tag(eff1_txt)
        t_honest_forms["moves"][0]["actual_command_sha256"] = cmd1_sha
        t_honest_forms["moves"][0]["effective_eff_sha256"] = eff1_sha
        # Move 1 ledger uses raw text only for actual_command and text+sha256 for effective_eff
        del t_honest_forms["budget_ledger"][0]["actual_command_sha256"]
        del t_honest_forms["budget_ledger"][0]["effective_eff"]
        t_honest_forms["budget_ledger"][0]["actual_command"] = cmd1_txt
        t_honest_forms["budget_ledger"][0]["effective_eff_receipt"] = eff1_txt
        t_honest_forms["budget_ledger"][0]["effective_eff_sha256"] = eff1_sha
        # Move 2 ledger uses typed mapping for actual_command_sha256 while moves[1] supplies text
        t_honest_forms["moves"][1]["actual_command"] = t_honest_forms[
            "budget_ledger"
        ][1]["actual_command"]
        del t_honest_forms["budget_ledger"][1]["actual_command"]
        t_honest_forms["budget_ledger"][1]["actual_command_sha256"] = {
            "state": "available",
            "representation": "sha256",
            "sha256": t_honest_forms["moves"][1]["actual_command_sha256"],
        }

        res_honest = verify_trajectory(
            t_honest_forms, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
        )
        self.assertTrue(res_honest["trajectory_ok"])
        self.assertEqual(
            res_honest["verified_moves"][0]["provenance_representations"][
                "actual_command"
            ],
            "utf8_text",
        )
        self.assertEqual(
            res_honest["verified_moves"][0]["provenance_representations"][
                "effective_eff"
            ],
            "utf8_text_and_sha256",
        )
        self.assertEqual(
            res_honest["verified_moves"][1]["provenance_representations"][
                "actual_command"
            ],
            "sha256",
        )

        # Mutating the raw command text in budget_ledger[0] while keeping moves[0] hash fixed rejects
        t_bad_text = copy.deepcopy(t_honest_forms)
        t_bad_text["budget_ledger"][0]["actual_command"] = (
            "phenix.refine model.pdb data.mtz xray_data.r_free_flags.generate=False main.number_of_macro_cycles=4"
        )
        with self.assertRaisesRegex(
            ValueError, "actual_command SHA-256 .* does not match"
        ):
            verify_trajectory(
                t_bad_text, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
            )

        # 4. Issue #1368 regression: per-mapping typed representation label must be validated
        #    against THAT mapping's own (has_sha, has_text) BEFORE combining with outer aliases,
        #    while preserving aggregate representation agreement.
        #    - Exact #1368 case: outer actual_command_sha256=cmd1_sha plus
        #      actual_command={state:'available', text:cmd1_txt, representation:'utf8_text_and_sha256'}
        #      (missing its own sha256) must reject with per-mapping contradiction!
        per_mapping_mismatch_cases: list[tuple[str, dict[str, Any], str]] = [
            (
                "text_only_claiming_utf8_text_and_sha256",
                {
                    "state": "available",
                    "text": cmd1_txt,
                    "representation": "utf8_text_and_sha256",
                },
                "contradicts supplied available content \\(expected 'utf8_text'\\)",
            ),
            (
                "text_only_claiming_sha256",
                {
                    "state": "available",
                    "text": cmd1_txt,
                    "representation": "sha256",
                },
                "contradicts supplied available content \\(expected 'utf8_text'\\)",
            ),
            (
                "hash_only_claiming_utf8_text",
                {
                    "state": "available",
                    "sha256": cmd1_sha,
                    "representation": "utf8_text",
                },
                "contradicts supplied available content \\(expected 'sha256'\\)",
            ),
            (
                "hash_only_claiming_utf8_text_and_sha256",
                {
                    "state": "available",
                    "sha256": cmd1_sha,
                    "representation": "utf8_text_and_sha256",
                },
                "contradicts supplied available content \\(expected 'sha256'\\)",
            ),
            (
                "neither_sha_nor_text",
                {
                    "state": "available",
                    "representation": "sha256",
                },
                "must supply 'sha256' and/or 'text'",
            ),
            (
                "both_claiming_utf8_text",
                {
                    "state": "available",
                    "text": cmd1_txt,
                    "sha256": cmd1_sha,
                    "representation": "utf8_text",
                },
                "contradicts supplied available content \\(expected 'utf8_text_and_sha256'\\)",
            ),
            (
                "both_claiming_sha256",
                {
                    "state": "available",
                    "text": cmd1_txt,
                    "sha256": cmd1_sha,
                    "representation": "sha256",
                },
                "contradicts supplied available content \\(expected 'utf8_text_and_sha256'\\)",
            ),
            (
                "reverse_aggregate_text_only_utf8_text_plus_outer_hash",
                {
                    "state": "available",
                    "text": cmd1_txt,
                    "representation": "utf8_text",
                },
                "contradicts resolved representation 'utf8_text_and_sha256'",
            ),
        ]
        for case_label, bad_map, expected_err in per_mapping_mismatch_cases:
            with self.subTest(typed_rep_case=case_label):
                t_bad_rep = copy.deepcopy(t_honest_forms)
                t_bad_rep["moves"][0]["actual_command"] = bad_map
                with self.assertRaisesRegex(ValueError, expected_err):
                    verify_trajectory(
                        t_bad_rep,
                        readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                    )

        # Honest typed mapping on moves[0] with both text and sha256 and representation='utf8_text_and_sha256'
        # alongside outer actual_command_sha256=cmd1_sha succeeds.
        t_honest_typed_move = copy.deepcopy(t_honest_forms)
        t_honest_typed_move["moves"][0]["actual_command"] = {
            "state": "available",
            "text": cmd1_txt,
            "sha256": cmd1_sha,
            "representation": "utf8_text_and_sha256",
        }
        res_honest_typed = verify_trajectory(
            t_honest_typed_move,
            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
        )
        self.assertTrue(res_honest_typed["trajectory_ok"])

    def test_verify_trajectory_bound_flag_generation_guard_proof_and_representations(
        self,
    ) -> None:
        # Issue #1358 regression:
        # 1. verify_trajectory must not trust a bare boolean flag_guard_verified=True; it must
        #    invoke phenix_stage2_flags.verify_flag_generation_guard against the exact command
        #    and effective .eff receipts bound to trajectory.moves and budget_ledger.
        # 2. Primary review witness: actual_command="phenix.refine ... r_free_flags.generate=True"
        #    with matching raw UTF-8 SHA-256 and flag_guard_verified=True MUST fail closed.
        # 3. Any r_free_flags.generate=True in primary_command, mechanical_backup (even unused),
        #    actual_command, effective_eff, or parameter_files MUST fail closed.
        # 4. Omission of explicit r_free_flags.generate=False in effective_eff fails closed.
        # 5. NUL-joined argv SHA-256 and raw UTF-8 command SHA-256 are distinct and validated
        #    against their respective representations; swapping them or supplying argv without
        #    raw text fails closed.
        # 6. Hash-only provenance without raw text cannot prove the guard and fails closed.
        # 7. Arm 1a verifies selector-bound sources without inventing arm1b_provenance and
        #    enforces explicit controller_contract_justification when mechanical_backup is not_applicable.
        # 8. Honest terminal failed moves with unavailable execution artifacts record
        #    flag_guard_verified='incomplete' without fabricating True or False.
        base_traj = self._make_valid_trajectory()
        res_ok = verify_trajectory(
            base_traj, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
        )
        self.assertTrue(res_ok["trajectory_ok"])

        # Verify NUL-joined argv digest vs raw UTF-8 digest distinction on all 3 command layers
        m0_bindings = res_ok["verified_moves"][0]["command_digest_bindings"]
        for cmd_layer in (
            "primary_command",
            "mechanical_backup",
            "actual_command",
        ):
            self.assertIn(cmd_layer, m0_bindings)
            raw_sha = m0_bindings[cmd_layer]["raw_utf8_sha256"]
            nul_sha = m0_bindings[cmd_layer]["nul_argv_sha256"]
            argv_toks = m0_bindings[cmd_layer]["argv"]
            self.assertNotEqual(raw_sha, nul_sha)
            self.assertEqual(
                nul_sha,
                hashlib.sha256(
                    "\x00".join(argv_toks).encode("utf-8")
                ).hexdigest(),
            )
            sid = m0_bindings[cmd_layer]["source_id"]
            self.assertEqual(
                res_ok["verified_moves"][0]["replayed_flag_guard"][
                    "source_digests"
                ][sid],
                nul_sha,
            )

        # 1. Exact #1358 primary review case and generate=True in each canonical layer
        bad_true_cmd = (
            "phenix.refine model.pdb data.mtz "
            "xray_data.r_free_flags.generate=True "
            "main.number_of_macro_cycles=5"
        )
        bad_true_cmd_sha = _sha256_tag(bad_true_cmd)
        for cmd_slot, sha_slot in (
            ("primary_command", "primary_command_sha256"),
            ("mechanical_backup", "mechanical_backup_sha256"),
            ("actual_command", "actual_command_sha256"),
        ):
            with self.subTest(true_in_command_layer=cmd_slot):
                t_true_cmd = copy.deepcopy(base_traj)
                t_true_cmd["budget_ledger"][0][cmd_slot] = bad_true_cmd
                t_true_cmd["budget_ledger"][0][sha_slot] = bad_true_cmd_sha
                if cmd_slot == "actual_command":
                    t_true_cmd["moves"][0][sha_slot] = bad_true_cmd_sha
                with self.assertRaisesRegex(
                    ValueError, "Forbidden R-free flag generation request"
                ):
                    verify_trajectory(
                        t_true_cmd,
                        readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                    )

        # generate=True in effective_eff fails closed even with matching UTF-8 hashes
        bad_true_eff = (
            "data_manager.fmodel.xray_data.r_free_flags.generate = True\n"
            "refinement.main.number_of_macro_cycles = 5\n"
        )
        bad_true_eff_sha = _sha256_tag(bad_true_eff)
        t_true_eff = copy.deepcopy(base_traj)
        t_true_eff["budget_ledger"][0]["effective_eff"] = bad_true_eff
        t_true_eff["budget_ledger"][0]["effective_eff_sha256"] = (
            bad_true_eff_sha
        )
        t_true_eff["moves"][0]["effective_eff_sha256"] = bad_true_eff_sha
        with self.assertRaisesRegex(
            ValueError, "Forbidden R-free flag generation request"
        ):
            verify_trajectory(
                t_true_eff, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
            )

        # 2. Omission of explicit r_free_flags.generate=False in effective_eff fails closed
        omitted_eff = "refinement.main.number_of_macro_cycles = 5\n"
        omitted_eff_sha = _sha256_tag(omitted_eff)
        t_omit_eff = copy.deepcopy(base_traj)
        t_omit_eff["budget_ledger"][0]["effective_eff"] = omitted_eff
        t_omit_eff["budget_ledger"][0]["effective_eff_sha256"] = omitted_eff_sha
        t_omit_eff["moves"][0]["effective_eff_sha256"] = omitted_eff_sha
        with self.assertRaisesRegex(
            ValueError, "missing an explicit r_free_flags\\.generate = False"
        ):
            verify_trajectory(
                t_omit_eff, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
            )

        # 3. Parameter file reference in command:
        # - Missing parameter_files fails closed (filename in hashed command does not authenticate bytes)
        # - Hash-only parameter_files entry fails closed
        # - generate=True inside parameter_files fails closed
        # - Valid generate=False parameter_files succeeds and retains literal content + digest
        cmd_with_pf = (
            "phenix.refine model.pdb data.mtz extra_params.eff "
            "xray_data.r_free_flags.generate=False "
            "main.number_of_macro_cycles=5"
        )
        cmd_with_pf_sha = _sha256_tag(cmd_with_pf)
        t_pf_missing = copy.deepcopy(base_traj)
        t_pf_missing["budget_ledger"][0]["actual_command"] = cmd_with_pf
        t_pf_missing["budget_ledger"][0]["actual_command_sha256"] = (
            cmd_with_pf_sha
        )
        t_pf_missing["moves"][0]["actual_command_sha256"] = cmd_with_pf_sha
        with self.assertRaisesRegex(
            ValueError, "literal contents were not supplied in parameter_files"
        ):
            verify_trajectory(
                t_pf_missing, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
            )

        pf_false_txt = (
            "data_manager.fmodel.xray_data.r_free_flags.generate = False\n"
        )
        pf_false_sha = _sha256_tag(pf_false_txt)
        t_pf_hash_only = copy.deepcopy(t_pf_missing)
        t_pf_hash_only["moves"][0]["parameter_files_sha256"] = {
            "extra_params.eff": pf_false_sha
        }
        with self.assertRaisesRegex(
            ValueError, "hash-only parameter file evidence"
        ):
            verify_trajectory(
                t_pf_hash_only,
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
            )

        t_pf_true = copy.deepcopy(t_pf_missing)
        t_pf_true["moves"][0]["parameter_files"] = {
            "extra_params.eff": "data_manager.fmodel.xray_data.r_free_flags.generate = True\n"
        }
        with self.assertRaisesRegex(
            ValueError, "Forbidden R-free flag generation request"
        ):
            verify_trajectory(
                t_pf_true, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
            )

        t_pf_valid = copy.deepcopy(t_pf_missing)
        t_pf_valid["moves"][0]["parameter_files"] = {
            "extra_params.eff": pf_false_txt
        }
        t_pf_valid["moves"][0]["parameter_files_sha256"] = {
            "extra_params.eff": pf_false_sha
        }
        res_pf = verify_trajectory(
            t_pf_valid, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
        )
        self.assertTrue(res_pf["trajectory_ok"])
        self.assertEqual(
            res_pf["verified_moves"][0]["parameter_files"],
            {"extra_params.eff": pf_false_txt},
        )
        self.assertEqual(
            res_pf["verified_moves"][0]["parameter_file_digests"],
            {"extra_params.eff": pf_false_sha},
        )

        # 4. Representation/digest mismatches between NUL-joined argv and raw UTF-8 command text:
        # - Swapping NUL-joined argv SHA-256 into actual_command_sha256 fails closed
        t_swap_sha = copy.deepcopy(base_traj)
        nul_act_sha = m0_bindings["actual_command"]["nul_argv_sha256"]
        t_swap_sha["moves"][0]["actual_command_sha256"] = nul_act_sha
        with self.assertRaisesRegex(
            ValueError, "actual_command SHA-256 .* does not match"
        ):
            verify_trajectory(
                t_swap_sha, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
            )

        # - Supplying raw UTF-8 SHA-256 in actual_command_argv_sha256 fails closed
        t_bad_argv_sha = copy.deepcopy(base_traj)
        t_bad_argv_sha["moves"][0]["actual_command_argv_sha256"] = m0_bindings[
            "actual_command"
        ]["raw_utf8_sha256"]
        with self.assertRaisesRegex(
            ValueError,
            "declared NUL-joined argv_sha256 .* does not match computed",
        ):
            verify_trajectory(
                t_bad_argv_sha,
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
            )

        # - Supplying actual_command_argv that disagrees with bounded tokenization fails closed
        t_bad_argv = copy.deepcopy(base_traj)
        t_bad_argv["moves"][0]["actual_command_argv"] = [
            "phenix.refine",
            "model.pdb",
            "data.mtz",
            "xray_data.r_free_flags.generate=False",
        ]
        with self.assertRaisesRegex(
            ValueError,
            "declared argv .* does not match bounded tokenization",
        ):
            verify_trajectory(
                t_bad_argv, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
            )

        # - Forged flag_guard_receipt with mismatched source_digests or guard_ok fails closed
        t_forged_receipt = copy.deepcopy(base_traj)
        t_forged_receipt["moves"][0]["flag_guard_receipt"] = {
            "guard_ok": True,
            "source_digests": {"move_01_actual_command": _sha256_tag("forged")},
        }
        with self.assertRaisesRegex(
            ValueError, "flag_guard_receipt\\.source_digests .* contradicts"
        ):
            verify_trajectory(
                t_forged_receipt,
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
            )

        # - Issue #1371 regressions on flag_guard_receipt:
        #   * Canonical complete receipt after JSON round-trip (lists matching replay tuples) is accepted
        canonical_m0_fg_json = json.loads(
            json.dumps(res_ok["verified_moves"][0]["replayed_flag_guard"])
        )
        self.assertIsInstance(
            canonical_m0_fg_json["generation_occurrences"], list
        )
        t_fg_full_json = copy.deepcopy(base_traj)
        t_fg_full_json["moves"][0]["flag_guard_receipt"] = canonical_m0_fg_json
        res_fg_full_json = verify_trajectory(
            t_fg_full_json,
            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
        )
        self.assertTrue(res_fg_full_json["trajectory_ok"])

        #   * Valid partial claim is accepted
        t_fg_partial_ok = copy.deepcopy(base_traj)
        t_fg_partial_ok["moves"][0]["flag_guard_receipt"] = {
            "guard_ok": True,
            "executed": False,
            "registration_status": REGISTRATION_STATUS,
        }
        res_fg_partial_ok = verify_trajectory(
            t_fg_partial_ok,
            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
        )
        self.assertTrue(res_fg_partial_ok["trajectory_ok"])

        #   * Claiming executed=True in flag_guard_receipt fails closed
        t_fg_exec_true = copy.deepcopy(base_traj)
        t_fg_exec_true["moves"][0]["flag_guard_receipt"] = {
            "guard_ok": True,
            "executed": True,
        }
        with self.assertRaisesRegex(
            ValueError, "flag_guard_receipt\\.executed .* contradicts"
        ):
            verify_trajectory(
                t_fg_exec_true,
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
            )

        #   * Frozen registration_status or native_effective_file_compatibility contradiction fails closed
        for bad_fg_field, bad_fg_val in (
            ("registration_status", "frozen_registered"),
            ("native_effective_file_compatibility", "verified_native_compatible"),
            ("stage2_status", "stage2_frozen_complete"),
        ):
            with self.subTest(bad_receipt_claim=bad_fg_field):
                t_fg_bad_claim = copy.deepcopy(base_traj)
                t_fg_bad_claim["moves"][0]["flag_guard_receipt"] = {
                    bad_fg_field: bad_fg_val,
                }
                with self.assertRaisesRegex(
                    ValueError,
                    f"flag_guard_receipt\\.{bad_fg_field} .* contradicts",
                ):
                    verify_trajectory(
                        t_fg_bad_claim,
                        readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                    )

        #   * Unsupported/unknown key in flag_guard_receipt fails closed
        t_fg_rec_unknown = copy.deepcopy(base_traj)
        t_fg_rec_unknown["moves"][0]["flag_guard_receipt"] = {
            "guard_ok": True,
            "unsupported_extra_claim": "rogue",
        }
        with self.assertRaisesRegex(
            ValueError, "flag_guard_receipt contains unsupported keys"
        ):
            verify_trajectory(
                t_fg_rec_unknown,
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
            )

        #   * Wrong-typed boolean (0 instead of False or 1 instead of True) fails closed
        for bool_field, int_impostor in (
            ("executed", 0),
            ("incomplete", 0),
            ("guard_ok", 1),
        ):
            with self.subTest(wrong_typed_bool=bool_field):
                t_fg_int_bool = copy.deepcopy(base_traj)
                t_fg_int_bool["moves"][0]["flag_guard_receipt"] = {
                    bool_field: int_impostor,
                }
                with self.assertRaisesRegex(
                    ValueError,
                    f"flag_guard_receipt\\.{bool_field} .* contradicts",
                ):
                    verify_trajectory(
                        t_fg_int_bool,
                        readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                    )

        # 5. Hash-only provenance (missing raw UTF-8 text) fails closed across every layer
        for cmd_slot in (
            "primary_command",
            "mechanical_backup",
            "actual_command",
            "effective_eff",
        ):
            with self.subTest(hash_only_layer=cmd_slot):
                t_hash_only = copy.deepcopy(base_traj)
                del t_hash_only["budget_ledger"][0][cmd_slot]
                with self.assertRaisesRegex(
                    ValueError,
                    f"{cmd_slot} supplies hash-only provenance",
                ):
                    verify_trajectory(
                        t_hash_only,
                        readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                    )

        # 6. Arm 1a trajectory: runtime returns arm1b_provenance=None; selector verifies
        #    selector-bound sources and requires explicit controller_contract_justification
        #    when mechanical_backup is marked not_applicable.
        t_arm1a = copy.deepcopy(base_traj)
        t_arm1a["arm"] = "1a"
        for idx in range(3):
            prov = self._make_move_provenance_bundle(
                idx + 1, 5 if idx == 0 else 3
            )
            for k in tuple(prov.keys()):
                t_arm1a["budget_ledger"][idx].pop(k, None)
            t_arm1a["moves"][idx].update(
                {
                    "primary_command": prov["primary_command"],
                    "primary_command_sha256": prov["primary_command_sha256"],
                    "mechanical_backup": {
                        "state": "not_applicable",
                        "representation": "not_applicable",
                        "controller_contract_justification": (
                            "Arm 1a single-command dispatch without mechanical backup."
                        ),
                    },
                    "actual_command": prov["actual_command"],
                    "actual_command_sha256": prov["actual_command_sha256"],
                    "effective_eff": prov["effective_eff"],
                    "effective_eff_sha256": prov["effective_eff_sha256"],
                }
            )
        res_arm1a = verify_trajectory(
            t_arm1a, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
        )
        self.assertTrue(res_arm1a["trajectory_ok"])
        for l_m in res_arm1a["budget_summary"]["moves"]:
            self.assertIsNone(l_m["arm1b_provenance"])

        # Arm 1a missing controller_contract_justification on not_applicable mechanical_backup rejects
        t_arm1a_no_just = copy.deepcopy(t_arm1a)
        t_arm1a_no_just["moves"][0]["mechanical_backup"] = {
            "state": "not_applicable",
            "representation": "not_applicable",
        }
        with self.assertRaisesRegex(
            ValueError, "controller_contract_justification"
        ):
            verify_trajectory(
                t_arm1a_no_just,
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
            )

        # Arm 1a with only argv and no raw command text fails closed (never space-joins argv)
        t_arm1a_argv_only = copy.deepcopy(t_arm1a)
        del t_arm1a_argv_only["moves"][0]["primary_command"]
        del t_arm1a_argv_only["moves"][0]["primary_command_sha256"]
        t_arm1a_argv_only["moves"][0]["primary_command_argv"] = [
            "phenix.refine",
            "model.pdb",
            "data.mtz",
            "xray_data.r_free_flags.generate=False",
        ]
        with self.assertRaisesRegex(
            ValueError,
            "space-joining argv to synthesize raw receipt text is forbidden",
        ):
            verify_trajectory(
                t_arm1a_argv_only,
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
            )

        # 6b. Explicit flag_guard_sources validation before reconciliation/sanitization:
        # - Command layer carrying phil_text rejects (cannot smuggle r_free_flags.generate=True)
        t_fg_cmd_phil = copy.deepcopy(base_traj)
        t_fg_cmd_phil["moves"][0]["flag_guard_sources"] = {
            "primary_command": {
                "phil_text": "data_manager.fmodel.xray_data.r_free_flags.generate = True\n",
            }
        }
        with self.assertRaisesRegex(
            ValueError,
            "flag_guard_sources\\['primary_command'\\]\\.phil_text is invalid",
        ):
            verify_trajectory(
                t_fg_cmd_phil,
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
            )

        # - effective_eff carrying argv rejects (cannot smuggle r_free_flags.generate=True)
        t_fg_eff_argv = copy.deepcopy(base_traj)
        t_fg_eff_argv["moves"][0]["flag_guard_sources"] = {
            "effective_eff": {
                "argv": ["r_free_flags.generate=True"],
            }
        }
        with self.assertRaisesRegex(
            ValueError,
            "flag_guard_sources\\['effective_eff'\\]\\.argv is invalid",
        ):
            verify_trajectory(
                t_fg_eff_argv,
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
            )

        # - Arm 1a not_applicable mechanical_backup carrying argv in flag_guard_sources rejects
        t_fg_na_argv = copy.deepcopy(t_arm1a)
        t_fg_na_argv["moves"][0]["flag_guard_sources"] = {
            "mechanical_backup": {
                "argv": ["r_free_flags.generate=True"],
            }
        }
        with self.assertRaisesRegex(
            ValueError,
            "flag_guard_sources\\['mechanical_backup'\\] with state='not_applicable' cannot carry 'argv'",
        ):
            verify_trajectory(
                t_fg_na_argv,
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
            )

        # - Unknown keys in flag_guard_sources entry reject
        t_fg_unknown_key = copy.deepcopy(base_traj)
        t_fg_unknown_key["moves"][0]["flag_guard_sources"] = {
            "primary_command": {
                "state": "supplied",
                "unexpected_extra_key": True,
            }
        }
        with self.assertRaisesRegex(
            ValueError,
            "flag_guard_sources\\['primary_command'\\] contains unknown keys",
        ):
            verify_trajectory(
                t_fg_unknown_key,
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
            )

        # - Conflicting source_id across move and ledger flag_guard_sources rejects (no last-alias-wins)
        t_fg_conflict_sid = copy.deepcopy(base_traj)
        t_fg_conflict_sid["moves"][0]["flag_guard_sources"] = {
            "primary_command": {"source_id": "custom_move_01_primary"}
        }
        t_fg_conflict_sid["budget_ledger"][0]["flag_guard_sources"] = {
            "primary_command": {"source_id": "different_ledger_01_primary"}
        }
        with self.assertRaisesRegex(
            ValueError,
            "source_id='different_ledger_01_primary' conflicts with",
        ):
            verify_trajectory(
                t_fg_conflict_sid,
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
            )

        # - Valid partial matching flag_guard_sources claim succeeds
        t_fg_valid_partial = copy.deepcopy(base_traj)
        t_fg_valid_partial["moves"][0]["flag_guard_sources"] = {
            "primary_command": {
                "source_id": "custom_move_01_primary",
                "state": "supplied",
            }
        }
        res_fg_partial = verify_trajectory(
            t_fg_valid_partial,
            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
        )
        self.assertTrue(res_fg_partial["trajectory_ok"])
        self.assertEqual(
            res_fg_partial["verified_moves"][0]["command_digest_bindings"][
                "primary_command"
            ]["source_id"],
            "custom_move_01_primary",
        )

        # 7. Honest terminal failed move with unavailable execution artifacts:
        #    must not fabricate boolean True or False for flag_guard_verified, and
        #    still rejects if supplied primary/backup has generate=True.
        t_failed_term = copy.deepcopy(base_traj)
        prov3 = self._make_move_provenance_bundle(3, 3)
        t_failed_term["moves"][2] = {
            "move_id": "move_03",
            "move_index": 3,
            "status": "FAIL_PROCESS_CRASH_OR_NONZERO_EXIT",
            "target_id": "target_anon_01",
            "subject_id": "target_anon_01_start",
            "work_reflection_domain_sha256": t_failed_term[
                "work_reflection_domain_sha256"
            ],
            "flag_partition_sha256": t_failed_term["flag_partition_sha256"],
            "sleep_partition_sha256": t_failed_term["sleep_partition_sha256"],
            "snapshot_binding_sha256": t_failed_term["snapshot_binding_sha256"],
            "flag_guard_verified": "incomplete",
        }
        t_failed_term["budget_ledger"][2] = {
            "move_index": 3,
            "move_kind": "refinement",
            "move_status": "aborted_before_execution",
            "planned_macro_cycles": 3,
            "observed_macro_cycles": 0,
            "role_tokens": {"llm": 500, "cheap_llm": 0, "command_llm": 0},
            "elapsed_seconds": 600.0,
            "configured_cpu_threads": 8,
            "primary_command": prov3["primary_command"],
            "primary_command_sha256": prov3["primary_command_sha256"],
            "mechanical_backup": prov3["mechanical_backup"],
            "mechanical_backup_sha256": prov3["mechanical_backup_sha256"],
            "actual_command": "not_executed",
            "effective_eff": "not_executed",
        }
        t_failed_term["claimed_selection"] = {
            "selection_state": "selected_unique",
            "selected_move_id": "move_02",
            "tied_move_ids": ("move_02",),
        }
        t_failed_term["claimed_stop_decision"] = {
            "should_stop": False,
            "stagnation_triggered": False,
            "budget_cap_exhausted": False,
        }
        t_failed_term["require_compliant_completion"] = False

        for fabricated_bool in (True, False):
            with self.subTest(fabricated_incomplete_bool=fabricated_bool):
                t_fab = copy.deepcopy(t_failed_term)
                t_fab["moves"][2]["flag_guard_verified"] = fabricated_bool
                with self.assertRaisesRegex(
                    ValueError,
                    "fabricates a boolean verification result on an incomplete failed move",
                ):
                    verify_trajectory(
                        t_fab,
                        readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                    )

        # Supplied generate=True in mechanical_backup on an aborted move still fails closed
        t_aborted_true_backup = copy.deepcopy(t_failed_term)
        t_aborted_true_backup["budget_ledger"][2]["mechanical_backup"] = (
            bad_true_cmd
        )
        t_aborted_true_backup["budget_ledger"][2][
            "mechanical_backup_sha256"
        ] = bad_true_cmd_sha
        with self.assertRaisesRegex(
            ValueError, "Forbidden R-free flag generation request"
        ):
            verify_trajectory(
                t_aborted_true_backup,
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
            )

        # Unavailable layer carrying argv in flag_guard_sources rejects
        t_unavail_fg_argv = copy.deepcopy(t_failed_term)
        t_unavail_fg_argv["moves"][2]["flag_guard_sources"] = {
            "actual_command": {
                "argv": ["r_free_flags.generate=True"],
            }
        }
        with self.assertRaisesRegex(
            ValueError,
            "flag_guard_sources\\['actual_command'\\] with state='unavailable' cannot carry 'argv'",
        ):
            verify_trajectory(
                t_unavail_fg_argv,
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
            )

    def test_accepted_incumbent_distinguishes_unresolved_exact_tie_from_no_eligible_candidate(
        self,
    ) -> None:
        # Issue #1360 regression:
        # - When prior prefix 1..curr_idx-1 has two eligible moves with an exact tie on
        #   (r_work, llg_work, molprobity_score) under residual_tie_policy='unresolved_tie',
        #   select_candidate returns selection_state='unresolved_exact_tie' (selected_move_id=None).
        # - accepted_incumbent MUST NOT treat that as no_eligible_candidate or silently fall
        #   back to 'start'; both stop_decision and verify_trajectory must raise ValueError.
        # - Under residual_tie_policy='canonical_move_id_asc', the tie resolves to 'move_01'.
        # - When all prior moves are geometry-ineligible (selection_state='no_eligible_candidate'),
        #   falling back to 'start' remains valid.
        traj = self._make_valid_trajectory()
        ledger = traj["budget_ledger"]
        start_rec = redact_starting_geometry_for_selection(
            traj["start_record"],
            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
        )["record"]

        # Make move_01 and move_02 tie identically on (r_work, llg_work, molprobity_score)
        m1_tie_priv = _make_candidate_record(
            "move_01",
            1,
            r_work=0.2000,
            llg_work=1250.0,
            molprobity_score=1.40,
            clashscore=5.6,
            include_private_holdout=True,
        )
        m2_tie_priv = _make_candidate_record(
            "move_02",
            2,
            r_work=0.2000,
            llg_work=1250.0,
            molprobity_score=1.40,
            clashscore=5.6,
            include_private_holdout=True,
        )
        m3_priv = _make_candidate_record(
            "move_03",
            3,
            r_work=0.1999,
            llg_work=1260.0,
            molprobity_score=1.39,
            clashscore=5.4,
            include_private_holdout=True,
        )
        m1_tie_rec = redact_candidate_for_selection(
            m1_tie_priv, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
        )["record"]
        m2_tie_rec = redact_candidate_for_selection(
            m2_tie_priv, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
        )["record"]
        m3_rec = redact_candidate_for_selection(
            m3_priv, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
        )["record"]

        pair_m2 = {
            "move_id": "move_02",
            "move_index": 2,
            "move_status": COMPLETED_COMMENSURABLE_STATUS,
            "reference_id": "move_01",
            "candidate_r_work": 0.2000,
            "reference_r_work": 0.2000,
            "candidate_clashscore": 5.6,
            "reference_clashscore": 5.6,
        }
        # Regardless of whether Move 3 claims 'start', 'move_01', or 'move_02',
        # unresolved_tie at prefix 1..2 must raise ValueError in stop_decision.
        for claimed_ref_id, claimed_ref_r, claimed_ref_clash in (
            ("start", 0.2100, 6.0),
            ("move_01", 0.2000, 5.6),
            ("move_02", 0.2000, 5.6),
        ):
            with self.subTest(claimed_ref_id=claimed_ref_id):
                pair_m3_claim = {
                    "move_id": "move_03",
                    "move_index": 3,
                    "move_status": COMPLETED_COMMENSURABLE_STATUS,
                    "reference_id": claimed_ref_id,
                    "candidate_r_work": 0.1999,
                    "reference_r_work": claimed_ref_r,
                    "candidate_clashscore": 5.4,
                    "reference_clashscore": claimed_ref_clash,
                }
                with self.assertRaisesRegex(
                    ValueError, "unresolved_exact_tie"
                ):
                    stop_decision(
                        consecutive_delta_pairs=[pair_m2, pair_m3_claim],
                        reference_convention="accepted_incumbent",
                        arm="1b",
                        budget_ledger=ledger,
                        start_record=start_rec,
                        reference_records=[m1_tie_rec, m2_tie_rec, m3_rec],
                        readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                        require_reference_evidence=True,
                        tie_group_policy="anchored_at_min_r_work",
                        residual_tie_policy="unresolved_tie",
                    )

        # In verify_trajectory, accepted_incumbent + unresolved_tie with tied prefix 1..2 also rejects
        traj_unresolved_inc = copy.deepcopy(traj)
        traj_unresolved_inc["reference_convention"] = "accepted_incumbent"
        traj_unresolved_inc["residual_tie_policy"] = "unresolved_tie"
        for idx, m_priv in enumerate([m1_tie_priv, m2_tie_priv, m3_priv]):
            red = redact_candidate_for_selection(
                m_priv, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
            )
            m_entry = copy.deepcopy(m_priv)
            m_entry.update(
                {
                    "flag_partition_sha256": traj["flag_partition_sha256"],
                    "sleep_partition_sha256": traj["sleep_partition_sha256"],
                    "snapshot_binding_sha256": traj["snapshot_binding_sha256"],
                    "flag_guard_verified": True,
                    "actual_command_sha256": traj["budget_ledger"][idx][
                        "actual_command_sha256"
                    ],
                    "effective_eff_sha256": traj["budget_ledger"][idx][
                        "effective_eff_sha256"
                    ],
                    "claimed_redacted_view_sha256": red[
                        "redacted_view_sha256"
                    ],
                }
            )
            traj_unresolved_inc["moves"][idx] = m_entry
        with self.assertRaisesRegex(ValueError, "unresolved_exact_tie"):
            verify_trajectory(
                traj_unresolved_inc,
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
            )

        # With explicit residual_tie_policy='canonical_move_id_asc', prefix 1..2 resolves to move_01
        traj_canon_inc = copy.deepcopy(traj_unresolved_inc)
        traj_canon_inc["residual_tie_policy"] = "canonical_move_id_asc"
        res_canon = verify_trajectory(
            traj_canon_inc, readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT
        )
        self.assertTrue(res_canon["trajectory_ok"])

        # Contrast with no_eligible_candidate: when move_01 and move_02 are both geometry-ineligible,
        # Move 3 under accepted_incumbent legitimately falls back to 'start' and succeeds.
        m1_inelig_rec = redact_candidate_for_selection(
            _make_candidate_record("move_01", 1, r_work=0.2000, clashscore=99.0),
            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
        )["record"]
        m2_inelig_rec = redact_candidate_for_selection(
            _make_candidate_record("move_02", 2, r_work=0.2000, clashscore=99.0),
            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
        )["record"]
        pair_m2_no_elig = {
            "move_id": "move_02",
            "move_index": 2,
            "move_status": COMPLETED_COMMENSURABLE_STATUS,
            "reference_id": "start",
            "candidate_r_work": 0.2000,
            "reference_r_work": 0.2100,
            "candidate_clashscore": 99.0,
            "reference_clashscore": 6.0,
        }
        pair_m3_no_elig = {
            "move_id": "move_03",
            "move_index": 3,
            "move_status": COMPLETED_COMMENSURABLE_STATUS,
            "reference_id": "start",
            "candidate_r_work": 0.1999,
            "reference_r_work": 0.2100,
            "candidate_clashscore": 5.4,
            "reference_clashscore": 6.0,
        }
        res_no_elig = stop_decision(
            consecutive_delta_pairs=[pair_m2_no_elig, pair_m3_no_elig],
            reference_convention="accepted_incumbent",
            arm="1b",
            budget_ledger=ledger,
            start_record=start_rec,
            reference_records=[m1_inelig_rec, m2_inelig_rec, m3_rec],
            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
            require_reference_evidence=True,
            tie_group_policy="anchored_at_min_r_work",
            residual_tie_policy="unresolved_tie",
        )
        self.assertTrue(res_no_elig["reference_evidence_verified"])

    def test_verify_trajectory_positive_cycles_vs_nonexecution_markers_and_arm3a_status_consistency(
        self,
    ) -> None:
        # Issues #1379 and #1380 regressions:
        # 1. (#1379) Both controller arms ('1a' and '1b') reject explicit non-execution
        #    markers (UNAVAILABLE_NOT_EXECUTED_MARKERS) on actual_command or effective_eff
        #    when canonical runtime ledger observed_macro_cycles > 0, across move-only,
        #    ledger-only, and matching both-alias carriers, and when only one execution
        #    slot or both execution slots carry the non-execution marker.
        # 2. (#1379) Single-alias non-execution vs crash/loss reason conflicts between
        #    moves[idx] and budget_ledger[idx] continue to be rejected by move-vs-ledger
        #    reason agreement.
        # 3. (#1379) Honest failed positive-cycle moves with crash/loss unavailability
        #    reasons ('not_retained_after_crash', 'unavailable_after_crash',
        #    'unavailable_execution_failed') and zero-cycle failed moves with explicit
        #    non-execution markers remain retained as retained_with_failed_move
        #    (flag_guard_verified='incomplete').
        # 4. (#1380) Both controller arms ('1a' and '1b') reject
        #    INCOMMENSURABLE_ARM3A_AUTODETECT_MISMATCH (applicable only to Arm 3a), while
        #    generic scientific incommensurability statuses remain retained.
        base_1b = self._make_valid_trajectory()
        prov3 = self._make_move_provenance_bundle(3, 3)

        def _make_arm1a_base() -> dict[str, Any]:
            t1a = copy.deepcopy(base_1b)
            t1a["arm"] = "1a"
            for idx in range(3):
                p = self._make_move_provenance_bundle(
                    idx + 1, 5 if idx == 0 else 3
                )
                for k in tuple(p.keys()):
                    t1a["budget_ledger"][idx].pop(k, None)
                t1a["moves"][idx].update(
                    {
                        "primary_command": p["primary_command"],
                        "primary_command_sha256": p["primary_command_sha256"],
                        "mechanical_backup": {
                            "state": "not_applicable",
                            "representation": "not_applicable",
                            "controller_contract_justification": (
                                "Arm 1a single-command dispatch without mechanical backup."
                            ),
                        },
                        "actual_command": p["actual_command"],
                        "actual_command_sha256": p["actual_command_sha256"],
                        "effective_eff": p["effective_eff"],
                        "effective_eff_sha256": p["effective_eff_sha256"],
                    }
                )
            return t1a

        base_1a = _make_arm1a_base()

        def _configure_terminal_failed_move(
            traj_in: dict[str, Any],
            *,
            observed_cycles: int,
            move_status: str = "failed",
            act_slot: Any,
            eff_slot: Any,
            carrier: str = "both",
        ) -> dict[str, Any]:
            t = copy.deepcopy(traj_in)
            arm_id = t["arm"]
            m2: dict[str, Any] = {
                "move_id": "move_03",
                "move_index": 3,
                "status": "FAIL_PROCESS_CRASH_OR_NONZERO_EXIT",
                "target_id": "target_anon_01",
                "subject_id": "target_anon_01_start",
                "work_reflection_domain_sha256": t[
                    "work_reflection_domain_sha256"
                ],
                "flag_partition_sha256": t["flag_partition_sha256"],
                "sleep_partition_sha256": t["sleep_partition_sha256"],
                "snapshot_binding_sha256": t["snapshot_binding_sha256"],
                "flag_guard_verified": "incomplete",
            }
            l2: dict[str, Any] = {
                "move_index": 3,
                "move_kind": "refinement",
                "move_status": move_status,
                "planned_macro_cycles": 3,
                "observed_macro_cycles": observed_cycles,
                "role_tokens": {"llm": 500, "cheap_llm": 0, "command_llm": 0},
                "elapsed_seconds": 800.0,
                "configured_cpu_threads": 8,
            }
            na_backup = {
                "state": "not_applicable",
                "representation": "not_applicable",
                "controller_contract_justification": (
                    "Arm 1a single-command dispatch without mechanical backup."
                ),
            }
            if arm_id == "1b":
                l2.update(
                    {
                        "primary_command": prov3["primary_command"],
                        "primary_command_sha256": prov3[
                            "primary_command_sha256"
                        ],
                        "mechanical_backup": prov3["mechanical_backup"],
                        "mechanical_backup_sha256": prov3[
                            "mechanical_backup_sha256"
                        ],
                        "actual_command": copy.deepcopy(act_slot),
                        "effective_eff": copy.deepcopy(eff_slot),
                    }
                )
                if carrier == "both":
                    m2["actual_command"] = copy.deepcopy(act_slot)
                    m2["effective_eff"] = copy.deepcopy(eff_slot)
            else:
                if carrier in ("move_only", "both"):
                    m2.update(
                        {
                            "primary_command": prov3["primary_command"],
                            "primary_command_sha256": prov3[
                                "primary_command_sha256"
                            ],
                            "mechanical_backup": copy.deepcopy(na_backup),
                            "actual_command": copy.deepcopy(act_slot),
                            "effective_eff": copy.deepcopy(eff_slot),
                        }
                    )
                if carrier in ("ledger_only", "both"):
                    l2.update(
                        {
                            "primary_command": prov3["primary_command"],
                            "primary_command_sha256": prov3[
                                "primary_command_sha256"
                            ],
                            "mechanical_backup": copy.deepcopy(na_backup),
                            "actual_command": copy.deepcopy(act_slot),
                            "effective_eff": copy.deepcopy(eff_slot),
                        }
                    )
            t["moves"][2] = m2
            t["budget_ledger"][2] = l2
            t["claimed_selection"] = {
                "selection_state": "selected_unique",
                "selected_move_id": "move_02",
                "tied_move_ids": ("move_02",),
            }
            t["claimed_stop_decision"] = {
                "should_stop": False,
                "stagnation_triggered": False,
                "budget_cap_exhausted": False,
            }
            t["require_compliant_completion"] = False
            return t

        crash_loss_map = {
            "state": "unavailable",
            "representation": "unavailable",
            "reason": "not_retained_after_crash",
        }

        # 1. Positive observed_macro_cycles=3 with explicit non-execution marker in
        #    actual_command only, effective_eff only, or both slots must fail closed
        #    on both Arm 1a (move_only, ledger_only, both) and Arm 1b.
        for marker in sorted(UNAVAILABLE_NOT_EXECUTED_MARKERS):
            nonexec_map = {
                "state": "unavailable",
                "representation": "unavailable",
                "reason": marker,
            }
            for slot_case, act_claim, eff_claim in (
                ("both_slots_str", marker, marker),
                ("both_slots_map", nonexec_map, nonexec_map),
                ("actual_command_only", nonexec_map, crash_loss_map),
                ("effective_eff_only", crash_loss_map, nonexec_map),
            ):
                for carrier_mode in ("move_only", "ledger_only", "both"):
                    with self.subTest(
                        arm="1a",
                        marker=marker,
                        slot_case=slot_case,
                        carrier=carrier_mode,
                    ):
                        t_bad_1a = _configure_terminal_failed_move(
                            base_1a,
                            observed_cycles=3,
                            act_slot=act_claim,
                            eff_slot=eff_claim,
                            carrier=carrier_mode,
                        )
                        with self.assertRaisesRegex(
                            ValueError,
                            "claims non-execution .* contradicts observed_macro_cycles=3",
                        ):
                            verify_trajectory(
                                t_bad_1a,
                                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                            )

                for carrier_mode_1b in ("ledger_only", "both"):
                    with self.subTest(
                        arm="1b",
                        marker=marker,
                        slot_case=slot_case,
                        carrier=carrier_mode_1b,
                    ):
                        t_bad_1b = _configure_terminal_failed_move(
                            base_1b,
                            observed_cycles=3,
                            act_slot=act_claim,
                            eff_slot=eff_claim,
                            carrier=carrier_mode_1b,
                        )
                        with self.assertRaisesRegex(
                            ValueError,
                            "claims non-execution .* contradicts observed_macro_cycles=3",
                        ):
                            verify_trajectory(
                                t_bad_1b,
                                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                            )

        # 2. Preservation check (1483): unilateral non-execution vs crash-loss reason conflict
        #    between moves[2] and budget_ledger[2] is rejected by move-vs-ledger reason agreement.
        t_conflict_1a = _configure_terminal_failed_move(
            base_1a,
            observed_cycles=3,
            act_slot=crash_loss_map,
            eff_slot=crash_loss_map,
            carrier="both",
        )
        t_conflict_1a["moves"][2]["actual_command"] = {
            "state": "unavailable",
            "representation": "unavailable",
            "reason": "unavailable_not_executed",
        }
        with self.assertRaisesRegex(
            ValueError,
            "actual_command unavailability reason \\('unavailable_not_executed'\\) does not match",
        ):
            verify_trajectory(
                t_conflict_1a,
                readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
            )

        # 3. Honest positive-cycle (observed_macro_cycles=3) failed move with crash/loss
        #    unavailability reasons remains retained_with_failed_move on both Arm 1a and Arm 1b.
        for arm_base in (base_1a, base_1b):
            for honest_reason in (
                "not_retained_after_crash",
                "unavailable_after_crash",
                "unavailable_execution_failed",
            ):
                honest_slot = {
                    "state": "unavailable",
                    "representation": "unavailable",
                    "reason": honest_reason,
                }
                with self.subTest(
                    arm=arm_base["arm"], honest_crash_reason=honest_reason
                ):
                    t_honest_crash = _configure_terminal_failed_move(
                        arm_base,
                        observed_cycles=3,
                        move_status="failed",
                        act_slot=honest_slot,
                        eff_slot=honest_slot,
                        carrier="both",
                    )
                    res_crash = verify_trajectory(
                        t_honest_crash,
                        readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                    )
                    self.assertTrue(res_crash["trajectory_ok"])
                    self.assertEqual(
                        res_crash["trajectory_state"],
                        "retained_with_failed_move",
                    )
                    self.assertFalse(res_crash["compliant_completion_verified"])
                    self.assertEqual(
                        res_crash["verified_moves"][2]["flag_guard_verified"],
                        "incomplete",
                    )

        # 4. Zero-cycle (observed_macro_cycles=0) failed/aborted moves with explicit
        #    non-execution markers remain retained_with_failed_move on both Arm 1a and Arm 1b.
        for arm_base in (base_1a, base_1b):
            for zero_status in ("failed", "aborted_before_execution"):
                for marker in ("unavailable_not_executed", "not_executed"):
                    with self.subTest(
                        arm=arm_base["arm"],
                        zero_status=zero_status,
                        marker=marker,
                    ):
                        t_zero_ok = _configure_terminal_failed_move(
                            arm_base,
                            observed_cycles=0,
                            move_status=zero_status,
                            act_slot=marker,
                            eff_slot=marker,
                            carrier="both",
                        )
                        res_zero = verify_trajectory(
                            t_zero_ok,
                            readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                        )
                        self.assertTrue(res_zero["trajectory_ok"])
                        self.assertEqual(
                            res_zero["trajectory_state"],
                            "retained_with_failed_move",
                        )
                        self.assertEqual(
                            res_zero["verified_moves"][2][
                                "flag_guard_verified"
                            ],
                            "incomplete",
                        )

        # 5. (#1380) INCOMMENSURABLE_ARM3A_AUTODETECT_MISMATCH is rejected on both
        #    controller arms ('1a' and '1b'), while the three generic scientific
        #    incommensurability statuses remain retained.
        generic_incomm_statuses = (
            "INCOMMENSURABLE_REFLECTION_DROP_OR_DOMAIN_CHANGE",
            "INCOMMENSURABLE_FREE_OR_SLEEP_FLAG_MUTATION",
            "INCOMMENSURABLE_ATOM_IDENTITY_OR_CELL_CORRUPTION",
        )
        for arm_base in (base_1a, base_1b):
            arm_id = arm_base["arm"]
            with self.subTest(arm=arm_id, status="INCOMMENSURABLE_ARM3A_AUTODETECT_MISMATCH"):
                t_arm3a_status = copy.deepcopy(arm_base)
                t_arm3a_status["moves"][2]["status"] = (
                    "INCOMMENSURABLE_ARM3A_AUTODETECT_MISMATCH"
                )
                t_arm3a_status["claimed_selection"] = {
                    "selection_state": "selected_unique",
                    "selected_move_id": "move_02",
                    "tied_move_ids": ("move_02",),
                }
                t_arm3a_status["claimed_stop_decision"] = {
                    "should_stop": False,
                    "stagnation_triggered": False,
                    "budget_cap_exhausted": False,
                }
                t_arm3a_status["require_compliant_completion"] = False
                with self.assertRaisesRegex(
                    ValueError,
                    f"INCOMMENSURABLE_ARM3A_AUTODETECT_MISMATCH.*applicable only to arm '3a', not arm {arm_id!r}",
                ):
                    verify_trajectory(
                        t_arm3a_status,
                        readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                    )

            for gen_status in generic_incomm_statuses:
                with self.subTest(arm=arm_id, status=gen_status):
                    t_gen = copy.deepcopy(arm_base)
                    t_gen["moves"][2]["status"] = gen_status
                    t_gen["claimed_selection"] = {
                        "selection_state": "selected_unique",
                        "selected_move_id": "move_02",
                        "tied_move_ids": ("move_02",),
                    }
                    t_gen["claimed_stop_decision"] = {
                        "should_stop": False,
                        "stagnation_triggered": False,
                        "budget_cap_exhausted": False,
                    }
                    t_gen["require_compliant_completion"] = False
                    res_gen = verify_trajectory(
                        t_gen,
                        readout_contract=SYNTHETIC_TEST_READOUT_CONTRACT,
                    )
                    self.assertTrue(res_gen["trajectory_ok"])
                    self.assertEqual(
                        res_gen["trajectory_state"],
                        "retained_with_failed_move",
                    )
                    self.assertFalse(res_gen["compliant_completion_verified"])
                    self.assertEqual(
                        res_gen["scientific_arm_completion"], "not_assessed"
                    )

    def test_module_imports_only_stdlib_and_phenix_stage2_runtime(self) -> None:
        mod_path = REPO_ROOT / "scripts" / "phenix_stage2_selector.py"
        tree = ast.parse(mod_path.read_text(encoding="utf-8"))
        allowed_modules = {
            "__future__",
            "collections",
            "collections.abc",
            "dataclasses",
            "decimal",
            "hashlib",
            "json",
            "math",
            "re",
            "typing",
            "phenix_stage2_flags",
            "phenix_stage2_runtime",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertIn(alias.name, allowed_modules)
            elif isinstance(node, ast.ImportFrom):
                self.assertIn(node.module, allowed_modules)
        self.assertEqual(len(U08_STATUS_CODES), 8)


if __name__ == "__main__":
    unittest.main()
