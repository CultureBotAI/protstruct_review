#!/usr/bin/env python3
"""Focused hermetic unit tests for scripts/phenix_stage2_runtime.py (U08, U12)."""

from __future__ import annotations

import ast
import copy
import hashlib
import math
from pathlib import Path
import sys
import unittest

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import phenix_stage2_runtime as r2  # noqa: E402


def _all_true_observations() -> dict[str, bool]:
    return {
        "process_ok": True,
        "budget_ok": True,
        "artifacts_ok": True,
        "autodetect_ok": True,
        "reflections_ok": True,
        "flags_ok": True,
        "atom_cell_ok": True,
    }


def _make_move(
    move_index: int = 1,
    *,
    planned_macro_cycles: int = 5,
    observed_macro_cycles: int = 5,
    move_status: str = "completed",
    llm_tokens: int = 1000,
    cheap_tokens: int = 500,
    command_tokens: int = 500,
    elapsed_seconds: float = 300.0,
    configured_cpu_threads: int = 8,
    arm1b: bool = False,
) -> dict[str, object]:
    move: dict[str, object] = {
        "move_index": move_index,
        "move_status": move_status,
        "planned_macro_cycles": planned_macro_cycles,
        "observed_macro_cycles": observed_macro_cycles,
        "role_tokens": {
            "llm": llm_tokens,
            "cheap_llm": cheap_tokens,
            "command_llm": command_tokens,
        },
        "elapsed_seconds": elapsed_seconds,
        "configured_cpu_threads": configured_cpu_threads,
    }
    if arm1b:
        if move_status == "aborted_before_execution":
            move["arm1b_provenance"] = {
                "primary_command_sha256": "a" * 64,
                "mechanical_backup_sha256": "b" * 64,
                "actual_command_sha256": "unavailable_not_executed",
                "effective_eff_sha256": "unavailable_not_executed",
            }
        else:
            move["arm1b_provenance"] = {
                "primary_command_sha256": "a" * 64,
                "mechanical_backup_sha256": "b" * 64,
                "actual_command_sha256": "c" * 64,
                "effective_eff_sha256": "d" * 64,
            }
    return move


class TestU08StatusClassifier(unittest.TestCase):
    """Verify the 8-code U08 completion and failure/incommensurability classifier."""

    def test_all_eight_exact_u08_statuses_and_provenance_separation(self) -> None:
        self.assertEqual(
            r2.U08_STATUS_CODES,
            (
                "COMPLETED_COMMENSURABLE",
                "FAIL_PROCESS_CRASH_OR_NONZERO_EXIT",
                "FAIL_BUDGET_OR_WALLCLOCK_EXCEEDED",
                "FAIL_UNPARSABLE_OR_MISSING_ARTIFACT",
                "INCOMMENSURABLE_ARM3A_AUTODETECT_MISMATCH",
                "INCOMMENSURABLE_REFLECTION_DROP_OR_DOMAIN_CHANGE",
                "INCOMMENSURABLE_FREE_OR_SLEEP_FLAG_MUTATION",
                "INCOMMENSURABLE_ATOM_IDENTITY_OR_CELL_CORRUPTION",
            ),
        )
        self.assertEqual(len(r2.U08_STATUS_CODES), 8)

        # 1. COMPLETED_COMMENSURABLE (both mapping and keyword invocation)
        res_ok = r2.classify_u08_status(
            _all_true_observations(),
            arm="3a",
            provenance_id="prov-001",
            reference_id="ref-3a-001",
        )
        self.assertEqual(res_ok["status"], "COMPLETED_COMMENSURABLE")
        self.assertTrue(res_ok["is_commensurable"])
        self.assertEqual(res_ok["detected_failures"], ())
        self.assertEqual(res_ok["provenance_id"], "prov-001")
        self.assertEqual(res_ok["reference_id"], "ref-3a-001")
        self.assertFalse(res_ok["executed"])

        # Explicit Arm 3a success via keyword arguments without imposing 5-cycle controller rule
        res_3a_kw = r2.classify_u08_status(
            process_ok=True,
            budget_ok=True,
            artifacts_ok=True,
            autodetect_ok=True,
            reflections_ok=True,
            flags_ok=True,
            atom_cell_ok=True,
            arm="3a",
        )
        self.assertEqual(res_3a_kw["status"], "COMPLETED_COMMENSURABLE")
        self.assertTrue(res_3a_kw["is_commensurable"])

        # Non-3a arms allow autodetect_ok="not_applicable"
        for non_3a_arm in ("1a", "1b", "2", "3b-refine-only", "3b-plus-readyset"):
            with self.subTest(non_3a_arm=non_3a_arm):
                obs = _all_true_observations()
                obs["autodetect_ok"] = "not_applicable"  # type: ignore[assignment]
                res_non3a = r2.classify_u08_status(obs, arm=non_3a_arm)
                self.assertEqual(res_non3a["status"], "COMPLETED_COMMENSURABLE")
                self.assertEqual(
                    res_non3a["observations"]["autodetect_ok"], "not_applicable"
                )

        # 2..8: Each single failure maps to its exact U08 status code
        for obs_key, expected_code in r2.OBSERVATION_TO_FAILURE_CODE:
            with self.subTest(single_failure=obs_key):
                obs = _all_true_observations()
                obs[obs_key] = False
                arm = "3a" if obs_key == "autodetect_ok" else "1a"
                res_fail = r2.classify_u08_status(obs, arm=arm)
                self.assertEqual(res_fail["status"], expected_code)
                self.assertEqual(res_fail["primary_status"], expected_code)
                self.assertFalse(res_fail["is_commensurable"])
                self.assertEqual(res_fail["detected_failures"], (expected_code,))
                self.assertIn(res_fail["status"], r2.U08_STATUS_CODES)

    def test_rejects_missing_unknown_or_nonboolean_observations(self) -> None:
        # Missing observation key
        for key in r2.REQUIRED_OBSERVATION_KEYS:
            with self.subTest(missing_key=key):
                obs = _all_true_observations()
                obs.pop(key)
                with self.assertRaises(ValueError):
                    r2.classify_u08_status(obs, arm="1a")

        # Unknown / non-boolean values (None, 1, 0, "true", "unknown")
        for key in r2.REQUIRED_OBSERVATION_KEYS:
            for bad_val in (None, 1, 0, "true", "false", "unknown", []):
                with self.subTest(key=key, bad_val=bad_val):
                    obs = _all_true_observations()
                    obs[key] = bad_val  # type: ignore[assignment]
                    with self.assertRaises(ValueError):
                        r2.classify_u08_status(obs, arm="3a")

        # autodetect_ok="not_applicable" rejected on arm="3a" or arm=None
        obs_na = _all_true_observations()
        obs_na["autodetect_ok"] = "not_applicable"  # type: ignore[assignment]
        with self.assertRaises(ValueError):
            r2.classify_u08_status(obs_na, arm="3a")
        with self.assertRaises(ValueError):
            r2.classify_u08_status(obs_na, arm=None)

        # autodetect_ok=False rejected on explicit non-3a arm
        obs_auto_false = _all_true_observations()
        obs_auto_false["autodetect_ok"] = False
        with self.assertRaises(ValueError):
            r2.classify_u08_status(obs_auto_false, arm="1a")

        # Unknown arm rejected
        with self.assertRaises(ValueError):
            r2.classify_u08_status(_all_true_observations(), arm="arm_unknown")

    def test_multiple_failures_require_explicit_priority_ordering(self) -> None:
        obs_multi = _all_true_observations()
        obs_multi["process_ok"] = False
        obs_multi["artifacts_ok"] = False
        f_proc = "FAIL_PROCESS_CRASH_OR_NONZERO_EXIT"
        f_art = "FAIL_UNPARSABLE_OR_MISSING_ARTIFACT"

        # Without failure_priority, raises unresolved-primary-status
        with self.assertRaisesRegex(ValueError, "unresolved-primary-status"):
            r2.classify_u08_status(obs_multi, arm="1a")

        # Explicit priority ordering [f_art, f_proc] selects f_art while preserving all detected_failures
        res_art_first = r2.classify_u08_status(
            obs_multi,
            arm="1a",
            failure_priority=[f_art, f_proc],
        )
        self.assertEqual(res_art_first["status"], f_art)
        self.assertEqual(res_art_first["detected_failures"], (f_proc, f_art))

        # Reversed priority [f_proc, f_art] selects f_proc
        res_proc_first = r2.classify_u08_status(
            obs_multi,
            arm="1a",
            failure_priority=[f_proc, f_art],
        )
        self.assertEqual(res_proc_first["status"], f_proc)
        self.assertEqual(res_proc_first["detected_failures"], (f_proc, f_art))

        # Missing one of the detected failures in failure_priority fails closed
        with self.assertRaisesRegex(ValueError, "unresolved-primary-status"):
            r2.classify_u08_status(
                obs_multi,
                arm="1a",
                failure_priority=[f_proc],
            )

        # Duplicate failure code in failure_priority fails closed
        with self.assertRaisesRegex(ValueError, "unresolved-primary-status"):
            r2.classify_u08_status(
                obs_multi,
                arm="1a",
                failure_priority=[f_proc, f_proc, f_art],
            )

        # Invalid or COMPLETED_COMMENSURABLE code in failure_priority fails closed
        for bad_prio in (
            ["COMPLETED_COMMENSURABLE", f_proc, f_art],
            ["INVENTED_NINTH_STATUS", f_proc, f_art],
            f_proc,
        ):
            with self.subTest(bad_prio=bad_prio):
                with self.assertRaisesRegex(ValueError, "unresolved-primary-status"):
                    r2.classify_u08_status(
                        obs_multi,
                        arm="1a",
                        failure_priority=bad_prio,  # type: ignore[arg-type]
                    )

    def test_known_failures_with_downstream_unavailable_audits(self) -> None:
        # 1. Known process crash with downstream unavailable audits (no fabricated True or extra failure codes)
        obs_crash: dict[str, object] = {
            "process_ok": False,
            "budget_ok": True,
            "artifacts_ok": {
                "state": "unavailable",
                "reason": "process_crashed_before_artifact_emission",
            },
            "autodetect_ok": "not_applicable",
            "reflections_ok": {
                "state": "unavailable",
                "reason": "no_output_mtz_after_crash",
            },
            "flags_ok": {
                "state": "unavailable",
                "reason": "no_output_mtz_after_crash",
            },
            "atom_cell_ok": {
                "state": "unavailable",
                "reason": "no_output_model_after_crash",
            },
        }
        res_crash = r2.classify_u08_status(obs_crash, arm="1a")
        self.assertEqual(res_crash["status"], "FAIL_PROCESS_CRASH_OR_NONZERO_EXIT")
        self.assertEqual(res_crash["primary_status"], "FAIL_PROCESS_CRASH_OR_NONZERO_EXIT")
        self.assertFalse(res_crash["is_commensurable"])
        self.assertEqual(
            res_crash["detected_failures"], ("FAIL_PROCESS_CRASH_OR_NONZERO_EXIT",)
        )
        self.assertEqual(res_crash["failure_count"], 1)
        self.assertEqual(
            res_crash["unknown_observations"],
            ("artifacts_ok", "reflections_ok", "flags_ok", "atom_cell_ok"),
        )
        self.assertEqual(
            res_crash["observations"]["artifacts_ok"],
            {
                "state": "unavailable",
                "reason": "process_crashed_before_artifact_emission",
            },
        )
        self.assertIsNot(res_crash["observations"]["artifacts_ok"], True)

        # 2. Known missing/unparsable artifact on Arm 3a with downstream unavailable audits
        obs_missing_art: dict[str, object] = {
            "process_ok": True,
            "budget_ok": True,
            "artifacts_ok": False,
            "autodetect_ok": {
                "state": "unavailable",
                "reason": "log_and_eff_unparsable",
            },
            "reflections_ok": {
                "state": "unavailable",
                "reason": "missing_output_mtz",
            },
            "flags_ok": {
                "state": "unavailable",
                "reason": "missing_output_mtz",
            },
            "atom_cell_ok": {
                "state": "unavailable",
                "reason": "missing_output_pdb",
            },
        }
        res_missing_art = r2.classify_u08_status(obs_missing_art, arm="3a")
        self.assertEqual(res_missing_art["status"], "FAIL_UNPARSABLE_OR_MISSING_ARTIFACT")
        self.assertFalse(res_missing_art["is_commensurable"])
        self.assertEqual(
            res_missing_art["detected_failures"],
            ("FAIL_UNPARSABLE_OR_MISSING_ARTIFACT",),
        )
        self.assertEqual(
            res_missing_art["unknown_observations"],
            ("autodetect_ok", "reflections_ok", "flags_ok", "atom_cell_ok"),
        )

        # 3. Multiple known failures (process_ok=False AND artifacts_ok=False) with downstream
        # unavailable audits still require explicit caller failure_priority
        obs_two_known = copy.deepcopy(obs_missing_art)
        obs_two_known["process_ok"] = False
        with self.assertRaisesRegex(ValueError, "unresolved-primary-status"):
            r2.classify_u08_status(obs_two_known, arm="3a")

        res_two_known = r2.classify_u08_status(
            obs_two_known,
            arm="3a",
            failure_priority=[
                "FAIL_PROCESS_CRASH_OR_NONZERO_EXIT",
                "FAIL_UNPARSABLE_OR_MISSING_ARTIFACT",
            ],
        )
        self.assertEqual(res_two_known["status"], "FAIL_PROCESS_CRASH_OR_NONZERO_EXIT")
        self.assertEqual(
            res_two_known["detected_failures"],
            (
                "FAIL_PROCESS_CRASH_OR_NONZERO_EXIT",
                "FAIL_UNPARSABLE_OR_MISSING_ARTIFACT",
            ),
        )
        self.assertEqual(
            res_two_known["unknown_observations"],
            ("autodetect_ok", "reflections_ok", "flags_ok", "atom_cell_ok"),
        )

        # 4. Unknown-only would-be completion (no independently known False check) fails closed
        obs_unknown_only: dict[str, object] = dict(_all_true_observations())
        obs_unknown_only["atom_cell_ok"] = {
            "state": "unavailable",
            "reason": "audit_skipped",
        }
        with self.assertRaisesRegex(ValueError, "unknown-only"):
            r2.classify_u08_status(obs_unknown_only, arm="3a")

        # 5. Order-independent unavailable checks: ANY observation (including budget_ok or
        # process_ok) may be state='unavailable' with a non-empty reason when at least one
        # independently known False check guarantees non-completion
        obs_art_fail_unavail_budget: dict[str, object] = dict(_all_true_observations())
        obs_art_fail_unavail_budget["budget_ok"] = {
            "state": "unavailable",
            "reason": "budget_ledger_unavailable_after_artifact_failure",
        }
        obs_art_fail_unavail_budget["artifacts_ok"] = False
        res_art_unavail_budget = r2.classify_u08_status(
            obs_art_fail_unavail_budget, arm="1a"
        )
        self.assertEqual(
            res_art_unavail_budget["status"], "FAIL_UNPARSABLE_OR_MISSING_ARTIFACT"
        )
        self.assertFalse(res_art_unavail_budget["is_commensurable"])
        self.assertEqual(
            res_art_unavail_budget["detected_failures"],
            ("FAIL_UNPARSABLE_OR_MISSING_ARTIFACT",),
        )
        self.assertEqual(
            res_art_unavail_budget["unknown_observations"], ("budget_ok",)
        )
        self.assertEqual(
            res_art_unavail_budget["unavailable_observations"]["budget_ok"],
            {
                "state": "unavailable",
                "reason": "budget_ledger_unavailable_after_artifact_failure",
            },
        )

        obs_flag_fail_unavail_process: dict[str, object] = dict(_all_true_observations())
        obs_flag_fail_unavail_process["process_ok"] = {
            "state": "unavailable",
            "reason": "process_exit_status_not_recorded",
        }
        obs_flag_fail_unavail_process["flags_ok"] = False
        res_flag_unavail_proc = r2.classify_u08_status(
            obs_flag_fail_unavail_process, arm="1a"
        )
        self.assertEqual(
            res_flag_unavail_proc["status"],
            "INCOMMENSURABLE_FREE_OR_SLEEP_FLAG_MUTATION",
        )
        self.assertFalse(res_flag_unavail_proc["is_commensurable"])
        self.assertEqual(
            res_flag_unavail_proc["detected_failures"],
            ("INCOMMENSURABLE_FREE_OR_SLEEP_FLAG_MUTATION",),
        )
        self.assertEqual(
            res_flag_unavail_proc["unknown_observations"], ("process_ok",)
        )
        self.assertEqual(
            res_flag_unavail_proc["unavailable_observations"]["process_ok"],
            {
                "state": "unavailable",
                "reason": "process_exit_status_not_recorded",
            },
        )

        # 6. Malformed unavailable mappings (missing/empty reason, bad state, extra key) reject
        for bad_unavail in (
            {},
            {"state": "unavailable"},
            {"state": "unavailable", "reason": ""},
            {"state": "unavailable", "reason": "   "},
            {"state": "available", "reason": "some_reason"},
            {"state": "not_evaluated", "reason": "wrong_state_label"},
            {"status": "unavailable", "reason": "wrong_key_name"},
            {"state": "unavailable", "status": "unavailable", "reason": "extra_key"},
            {"state": "unavailable", "reason": "ok", "extra": 1},
        ):
            with self.subTest(bad_unavail=bad_unavail):
                obs_malformed: dict[str, object] = dict(_all_true_observations())
                obs_malformed["process_ok"] = False
                obs_malformed["artifacts_ok"] = bad_unavail
                with self.assertRaises(ValueError):
                    r2.classify_u08_status(obs_malformed, arm="1a")


class TestControllerBudgetAndAdmission(unittest.TestCase):
    """Verify U12 controller-only budget ledger verifier and prospective move admission."""

    def test_controller_scope_requires_explicit_arm_1a_or_1b(self) -> None:
        ledger = [_make_move(1)]
        for bad_arm in ("2", "3a", "3b-refine-only", "3b-plus-readyset", "", None, 1):
            with self.subTest(bad_arm=bad_arm):
                with self.assertRaises(ValueError):
                    r2.verify_controller_budget(
                        arm=bad_arm,  # type: ignore[arg-type]
                        ledger=ledger,
                    )
                with self.assertRaises(ValueError):
                    r2.admit_controller_move(
                        arm=bad_arm,  # type: ignore[arg-type]
                        ledger=[],
                        requested_usage={
                            "planned_macro_cycles": 5,
                            "configured_cpu_threads": 8,
                            "requested_tokens": 1000,
                            "requested_elapsed_seconds": 60.0,
                        },
                    )

        # Calling without keyword 'arm' raises TypeError
        with self.assertRaises(TypeError):
            r2.verify_controller_budget(ledger=ledger)  # type: ignore[call-arg]
        with self.assertRaises(TypeError):
            r2.admit_controller_move(ledger=[], requested_usage={})  # type: ignore[call-arg]

    def test_cap_boundaries_and_first_move_rules(self) -> None:
        # Exact boundary: 8 moves, 25 total macro-cycles (5 + 7*2 + 6 = 25),
        # 150,000 total tokens, 7200.0 elapsed_seconds, 8 configured CPU threads
        cycles_per_move = [5, 3, 3, 3, 3, 3, 3, 2]
        self.assertEqual(sum(cycles_per_move), 25)
        moves = []
        for idx, cyc in enumerate(cycles_per_move, start=1):
            tok = 18750  # 8 * 18750 = 150,000
            moves.append(
                {
                    "move_index": idx,
                    "move_status": "completed",
                    "planned_macro_cycles": cyc,
                    "observed_macro_cycles": cyc,
                    "role_tokens": {
                        "llm": 10000,
                        "cheap_llm": 5000,
                        "command_llm": tok - 15000,
                    },
                    "elapsed_seconds": float(idx * 900),
                    "configured_cpu_threads": 8,
                    "observed_cpu_utilization": 6.4,
                }
            )

        summary = r2.verify_controller_budget(arm="1a", ledger=moves)
        self.assertTrue(summary["budget_ok"])
        self.assertEqual(summary["move_count"], 8)
        self.assertEqual(summary["total_planned_macro_cycles"], 25)
        self.assertEqual(summary["total_observed_macro_cycles"], 25)
        self.assertEqual(summary["total_tokens"], 150_000)
        self.assertEqual(summary["elapsed_seconds"], 7200.0)
        self.assertTrue(summary["move_1_checkpoint_completed"])
        self.assertTrue(summary["all_recorded_moves_completed"])
        self.assertFalse(summary["contains_failed_or_aborted_move"])
        self.assertEqual(summary["scientific_arm_completion"], "not_assessed")
        self.assertNotIn("run_completed", summary)
        self.assertNotIn("failed_or_aborted", summary)
        self.assertTrue(summary["retained_in_denominator"])
        self.assertEqual(summary["moves"][0]["observed_cpu_utilization"], 6.4)

        # Exceeding each cap by 1 unit in observed ledger retains full normalized ledger,
        # marks budget_ok=False with exact violation_codes/violation_reasons, keeps
        # retained_in_denominator=True, and blocks any subsequent admit_controller_move
        over_moves = copy.deepcopy(moves)
        over_moves[-1]["planned_macro_cycles"] = 1
        over_moves[-1]["observed_macro_cycles"] = 1
        over_moves.append(
            _make_move(
                9,
                planned_macro_cycles=1,
                observed_macro_cycles=1,
                llm_tokens=0,
                cheap_tokens=0,
                command_tokens=0,
                elapsed_seconds=7200.0,
            )
        )
        res_over_moves = r2.verify_controller_budget(arm="1a", ledger=over_moves)
        self.assertFalse(res_over_moves["budget_ok"])
        self.assertEqual(res_over_moves["move_count"], 9)
        self.assertEqual(len(res_over_moves["moves"]), 9)
        self.assertIn("move_count_exceeded", res_over_moves["violation_codes"])
        self.assertTrue(res_over_moves["retained_in_denominator"])
        self.assertFalse(res_over_moves["moves"][-1]["completed_checkpoint"])
        with self.assertRaises(ValueError):
            r2.admit_controller_move(
                arm="1a",
                ledger=moves,
                requested_usage={
                    "planned_macro_cycles": 1,
                    "configured_cpu_threads": 8,
                    "requested_tokens": 0,
                    "requested_elapsed_seconds": 0.0,
                },
            )

        over_cycles = copy.deepcopy(moves)
        over_cycles[-1]["planned_macro_cycles"] = 3
        over_cycles[-1]["observed_macro_cycles"] = 3
        res_over_cycles = r2.verify_controller_budget(arm="1a", ledger=over_cycles)
        self.assertFalse(res_over_cycles["budget_ok"])
        self.assertEqual(res_over_cycles["total_planned_macro_cycles"], 26)
        self.assertEqual(res_over_cycles["total_observed_macro_cycles"], 26)
        self.assertIn("planned_macro_cycles_exceeded", res_over_cycles["violation_codes"])
        self.assertIn("observed_macro_cycles_exceeded", res_over_cycles["violation_codes"])
        self.assertTrue(res_over_cycles["retained_in_denominator"])
        self.assertFalse(res_over_cycles["moves"][-1]["completed_checkpoint"])

        over_tokens = copy.deepcopy(moves)
        over_tokens[-1]["role_tokens"]["command_llm"] = 3751  # type: ignore[index]
        res_over_tokens = r2.verify_controller_budget(arm="1a", ledger=over_tokens)
        self.assertFalse(res_over_tokens["budget_ok"])
        self.assertEqual(res_over_tokens["total_tokens"], 150_001)
        self.assertIn("total_tokens_exceeded", res_over_tokens["violation_codes"])
        self.assertTrue(res_over_tokens["retained_in_denominator"])
        self.assertFalse(res_over_tokens["moves"][-1]["completed_checkpoint"])

        over_time = copy.deepcopy(moves)
        over_time[-1]["elapsed_seconds"] = 7200.1
        res_over_time = r2.verify_controller_budget(arm="1a", ledger=over_time)
        self.assertFalse(res_over_time["budget_ok"])
        self.assertEqual(res_over_time["elapsed_seconds"], 7200.1)
        self.assertIn("elapsed_seconds_exceeded", res_over_time["violation_codes"])
        self.assertTrue(res_over_time["retained_in_denominator"])
        self.assertFalse(res_over_time["moves"][-1]["completed_checkpoint"])

        # Move 1 planned == 0 (non-positive) raises ValueError, while positive planned != 5
        # is retained as a Move 1 compliance violation (budget_ok=False, not fabricated success)
        m1_zero_planned = _make_move(1, planned_macro_cycles=0, observed_macro_cycles=0)
        with self.assertRaises(ValueError):
            r2.verify_controller_budget(arm="1a", ledger=[m1_zero_planned])

        for bad_m1_planned in (3, 4, 6):
            with self.subTest(bad_m1_planned=bad_m1_planned):
                m1_bad = _make_move(
                    1,
                    planned_macro_cycles=bad_m1_planned,
                    observed_macro_cycles=bad_m1_planned,
                )
                res_m1_bad = r2.verify_controller_budget(arm="1a", ledger=[m1_bad])
                self.assertFalse(res_m1_bad["budget_ok"])
                self.assertEqual(res_m1_bad["move_1_planned_macro_cycles"], bad_m1_planned)
                self.assertFalse(res_m1_bad["move_1_checkpoint_completed"])
                self.assertFalse(res_m1_bad["moves"][0]["completed_checkpoint"])
                self.assertIn("move_1_planned_macro_cycles_mismatch", res_m1_bad["violation_codes"])
                self.assertTrue(res_m1_bad["retained_in_denominator"])
                with self.assertRaises(ValueError):
                    r2.admit_controller_move(
                        arm="1a",
                        ledger=[m1_bad],
                        requested_usage={
                            "planned_macro_cycles": 3,
                            "configured_cpu_threads": 8,
                            "requested_tokens": 1000,
                            "requested_elapsed_seconds": 60.0,
                        },
                    )

        # Completed Move 1 with observed_macro_cycles < 5 is retained as a compliance violation
        # (budget_ok=False, move_1_checkpoint_completed=False, completed_checkpoint=False)
        for bad_m1_obs in (0, 1, 3, 4):
            with self.subTest(completed_m1_obs=bad_m1_obs):
                m1_incomplete_success = _make_move(
                    1,
                    planned_macro_cycles=5,
                    observed_macro_cycles=bad_m1_obs,
                    move_status="completed",
                )
                res_m1_inc = r2.verify_controller_budget(
                    arm="1a", ledger=[m1_incomplete_success]
                )
                self.assertFalse(res_m1_inc["budget_ok"])
                self.assertEqual(res_m1_inc["move_1_observed_macro_cycles"], bad_m1_obs)
                self.assertFalse(res_m1_inc["move_1_checkpoint_completed"])
                self.assertFalse(res_m1_inc["moves"][0]["completed_checkpoint"])
                self.assertIn(
                    "move_1_completed_observed_macro_cycles_mismatch",
                    res_m1_inc["violation_codes"],
                )
                self.assertTrue(res_m1_inc["retained_in_denominator"])
                with self.assertRaises(ValueError):
                    r2.admit_controller_move(
                        arm="1a",
                        ledger=[m1_incomplete_success],
                        requested_usage={
                            "planned_macro_cycles": 3,
                            "configured_cpu_threads": 8,
                            "requested_tokens": 1000,
                            "requested_elapsed_seconds": 60.0,
                        },
                    )

        # Aborted or failed Move 1 with 0 or partial (<5) observed cycles is preserved
        # without coercion, never marked completed checkpoint, and retained in denominator
        for status, obs_cyc in (
            ("aborted_before_execution", 0),
            ("aborted", 0),
            ("aborted", 2),
            ("failed", 4),
        ):
            with self.subTest(failed_m1_status=status, obs_cyc=obs_cyc):
                m1_failed = _make_move(
                    1,
                    planned_macro_cycles=5,
                    observed_macro_cycles=obs_cyc,
                    move_status=status,
                    arm1b=True,
                )
                res_failed = r2.verify_controller_budget(arm="1b", ledger=[m1_failed])
                self.assertEqual(res_failed["move_1_planned_macro_cycles"], 5)
                self.assertEqual(res_failed["move_1_observed_macro_cycles"], obs_cyc)
                self.assertEqual(res_failed["total_observed_macro_cycles"], obs_cyc)
                self.assertFalse(res_failed["move_1_checkpoint_completed"])
                self.assertFalse(res_failed["all_recorded_moves_completed"])
                self.assertTrue(res_failed["contains_failed_or_aborted_move"])
                self.assertEqual(res_failed["scientific_arm_completion"], "not_assessed")
                self.assertNotIn("run_completed", res_failed)
                self.assertNotIn("failed_or_aborted", res_failed)
                self.assertTrue(res_failed["retained_in_denominator"])
                self.assertFalse(res_failed["moves"][0]["completed_checkpoint"])

    def test_rejects_gaps_duplicates_negative_bool_nonfinite_and_decreasing_clock(self) -> None:
        m1 = _make_move(1, elapsed_seconds=100.0)
        m2 = _make_move(2, planned_macro_cycles=3, observed_macro_cycles=3, elapsed_seconds=200.0)

        # Gap in move_index (1, 3)
        m3_gap = _make_move(3, planned_macro_cycles=3, observed_macro_cycles=3, elapsed_seconds=200.0)
        with self.assertRaises(ValueError):
            r2.verify_controller_budget(arm="1a", ledger=[m1, m3_gap])

        # Duplicate move_index (1, 1)
        with self.assertRaises(ValueError):
            r2.verify_controller_budget(arm="1a", ledger=[m1, copy.deepcopy(m1)])

        # Decreasing clock (100.0 -> 99.9)
        m2_dec = copy.deepcopy(m2)
        m2_dec["elapsed_seconds"] = 99.9
        with self.assertRaises(ValueError):
            r2.verify_controller_budget(arm="1a", ledger=[m1, m2_dec])

        # Non-finite or negative or bool elapsed_seconds
        for bad_clock in (-0.1, math.nan, math.inf, -math.inf, True, False, "100.0", None):
            with self.subTest(bad_clock=bad_clock):
                m_clock = _make_move(1)
                m_clock["elapsed_seconds"] = bad_clock
                with self.assertRaises(ValueError):
                    r2.verify_controller_budget(arm="1a", ledger=[m_clock])

        # Bool or negative/non-positive counts in cycles, tokens, or configured_cpu_threads raise ValueError
        for field_key, bad_val in (
            ("planned_macro_cycles", True),
            ("planned_macro_cycles", 0),
            ("planned_macro_cycles", -5),
            ("observed_macro_cycles", True),
            ("observed_macro_cycles", False),
            ("observed_macro_cycles", -1),
            ("configured_cpu_threads", True),
            ("configured_cpu_threads", 0),
            ("configured_cpu_threads", -1),
        ):
            with self.subTest(field_key=field_key, bad_val=bad_val):
                m_bad = _make_move(1)
                m_bad[field_key] = bad_val
                with self.assertRaises(ValueError):
                    r2.verify_controller_budget(arm="1a", ledger=[m_bad])

        # Actual observed_macro_cycles exceeding planned_macro_cycles (e.g. 6 > 5) remains actual (6, not coerced to 5),
        # marks budget_ok=False with plan-mismatch violation, and blocks subsequent admit_controller_move
        m_obs_gt_plan = _make_move(1, planned_macro_cycles=5, observed_macro_cycles=6)
        res_obs_gt_plan = r2.verify_controller_budget(arm="1a", ledger=[m_obs_gt_plan])
        self.assertFalse(res_obs_gt_plan["budget_ok"])
        self.assertEqual(res_obs_gt_plan["move_1_planned_macro_cycles"], 5)
        self.assertEqual(res_obs_gt_plan["move_1_observed_macro_cycles"], 6)
        self.assertEqual(res_obs_gt_plan["total_observed_macro_cycles"], 6)
        self.assertEqual(res_obs_gt_plan["moves"][0]["observed_macro_cycles"], 6)
        self.assertFalse(res_obs_gt_plan["move_1_checkpoint_completed"])
        self.assertFalse(res_obs_gt_plan["moves"][0]["completed_checkpoint"])
        self.assertIn("observed_macro_cycles_exceed_planned", res_obs_gt_plan["violation_codes"])
        self.assertTrue(res_obs_gt_plan["retained_in_denominator"])
        with self.assertRaises(ValueError):
            r2.admit_controller_move(
                arm="1a",
                ledger=[m_obs_gt_plan],
                requested_usage={
                    "planned_macro_cycles": 3,
                    "configured_cpu_threads": 8,
                    "requested_tokens": 1000,
                    "requested_elapsed_seconds": 60.0,
                },
            )

        # Wrong positive configured_cpu_threads (e.g. 4 or 16 != 8) is retained as a recorded
        # compliance violation (budget_ok=False, not fabricated success) and rejected prospectively
        for bad_threads in (4, 16):
            with self.subTest(bad_threads=bad_threads):
                m_threads = _make_move(1, configured_cpu_threads=bad_threads)
                res_threads = r2.verify_controller_budget(arm="1a", ledger=[m_threads])
                self.assertFalse(res_threads["budget_ok"])
                self.assertEqual(res_threads["configured_cpu_threads"], bad_threads)
                self.assertEqual(res_threads["moves"][0]["configured_cpu_threads"], bad_threads)
                self.assertFalse(res_threads["move_1_checkpoint_completed"])
                self.assertFalse(res_threads["moves"][0]["completed_checkpoint"])
                self.assertIn("configured_cpu_threads_mismatch", res_threads["violation_codes"])
                self.assertTrue(res_threads["retained_in_denominator"])
                with self.assertRaises(ValueError):
                    r2.admit_controller_move(
                        arm="1a",
                        ledger=[],
                        requested_usage={
                            "planned_macro_cycles": 5,
                            "configured_cpu_threads": bad_threads,
                            "requested_tokens": 1000,
                            "requested_elapsed_seconds": 60.0,
                        },
                    )
                with self.assertRaises(ValueError):
                    r2.admit_controller_move(
                        arm="1a",
                        ledger=[m_threads],
                        requested_usage={
                            "planned_macro_cycles": 3,
                            "configured_cpu_threads": 8,
                            "requested_tokens": 1000,
                            "requested_elapsed_seconds": 60.0,
                        },
                    )

        for bad_tok in (True, False, -1, 1.5, "100", None):
            with self.subTest(bad_role_tok=bad_tok):
                m_tok = _make_move(1)
                m_tok["role_tokens"] = {
                    "llm": bad_tok,
                    "cheap_llm": 0,
                    "command_llm": 0,
                }
                with self.assertRaises(ValueError):
                    r2.verify_controller_budget(arm="1a", ledger=[m_tok])

    def test_arm1b_provenance_and_all_three_role_token_accounting(self) -> None:
        # Explicit zero-used role record and prompt+completion breakdown supported
        m1_1b = {
            "move_index": 1,
            "move_status": "completed",
            "planned_macro_cycles": 5,
            "observed_macro_cycles": 5,
            "role_tokens": {
                "llm": {"prompt_tokens": 800, "completion_tokens": 200, "total_tokens": 1000},
                "cheap_llm": {"total_tokens": 0, "zero_used": True, "status": "zero_used"},
                "command_llm": 400,
            },
            "total_tokens": 1400,
            "elapsed_seconds": 150.0,
            "configured_cpu_threads": 8,
            "arm1b_provenance": {
                "primary_command_sha256": "a" * 64,
                "mechanical_backup_sha256": "b" * 64,
                "actual_command_sha256": "c" * 64,
                "effective_eff_sha256": "d" * 64,
            },
        }
        res_1b = r2.verify_controller_budget(arm="1b", ledger=[m1_1b])
        self.assertTrue(res_1b["budget_ok"])
        self.assertEqual(
            res_1b["role_token_totals"],
            {"llm": 1000, "cheap_llm": 0, "command_llm": 400},
        )
        self.assertEqual(res_1b["total_tokens"], 1400)

        # Missing any of the 3 LLM subroles fails closed
        for missing_role in ("llm", "cheap_llm", "command_llm"):
            with self.subTest(missing_role=missing_role):
                m_missing_role = copy.deepcopy(m1_1b)
                m_missing_role["role_tokens"].pop(missing_role)  # type: ignore[attr-defined]
                m_missing_role.pop("total_tokens")
                with self.assertRaises(ValueError):
                    r2.verify_controller_budget(arm="1b", ledger=[m_missing_role])

        # Missing any of the 4 Arm 1b provenance bindings fails closed
        for missing_prov in (
            "primary_command_sha256",
            "mechanical_backup_sha256",
            "actual_command_sha256",
            "effective_eff_sha256",
        ):
            with self.subTest(missing_prov=missing_prov):
                m_missing_prov = copy.deepcopy(m1_1b)
                m_missing_prov["arm1b_provenance"].pop(missing_prov)  # type: ignore[attr-defined]
                with self.assertRaises(ValueError):
                    r2.verify_controller_budget(arm="1b", ledger=[m_missing_prov])

        # Completed move cannot use 'unavailable_not_executed', while aborted_before_execution requires it
        m_bad_completed_prov = copy.deepcopy(m1_1b)
        m_bad_completed_prov["arm1b_provenance"]["actual_command_sha256"] = (  # type: ignore[index]
            "unavailable_not_executed"
        )
        with self.assertRaises(ValueError):
            r2.verify_controller_budget(arm="1b", ledger=[m_bad_completed_prov])

        m_bad_aborted_prov = _make_move(
            1,
            planned_macro_cycles=5,
            observed_macro_cycles=0,
            move_status="aborted_before_execution",
            arm1b=True,
        )
        m_bad_aborted_prov["arm1b_provenance"]["actual_command_sha256"] = "c" * 64  # type: ignore[index]
        with self.assertRaises(ValueError):
            r2.verify_controller_budget(arm="1b", ledger=[m_bad_aborted_prov])

    def test_prospective_move_admission_before_execution(self) -> None:
        # Admitting Move 1 requires planned_macro_cycles == 5
        adm1 = r2.admit_controller_move(
            arm="1a",
            ledger=[],
            requested_usage={
                "planned_macro_cycles": 5,
                "configured_cpu_threads": 8,
                "requested_tokens": 20_000,
                "requested_elapsed_seconds": 600.0,
            },
        )
        self.assertTrue(adm1["admitted"])
        self.assertEqual(adm1["next_move_index"], 1)
        self.assertEqual(adm1["projected_macro_cycles"], 5)
        self.assertEqual(adm1["projected_total_tokens"], 20_000)
        self.assertEqual(adm1["projected_elapsed_seconds"], 600.0)

        # Move 1 planned != 5 rejected prospectively
        with self.assertRaises(ValueError):
            r2.admit_controller_move(
                arm="1a",
                ledger=[],
                requested_usage={
                    "planned_macro_cycles": 3,
                    "configured_cpu_threads": 8,
                    "requested_tokens": 1000,
                    "requested_elapsed_seconds": 60.0,
                },
            )

        # Prior ledger with 22 cycles, 140k tokens, 7000s elapsed
        prior_ledger = [
            _make_move(
                1,
                planned_macro_cycles=5,
                observed_macro_cycles=5,
                llm_tokens=50_000,
                cheap_tokens=10_000,
                command_tokens=10_000,
                elapsed_seconds=3500.0,
            ),
            _make_move(
                2,
                planned_macro_cycles=17,
                observed_macro_cycles=17,
                llm_tokens=50_000,
                cheap_tokens=10_000,
                command_tokens=10_000,
                elapsed_seconds=7000.0,
            ),
        ]

        # Within cap (3 cycles -> 25, 10k tokens -> 150k, +200s -> 7200s) admitted
        adm_ok = r2.admit_controller_move(
            arm="1a",
            ledger=prior_ledger,
            requested_usage={
                "planned_macro_cycles": 3,
                "configured_cpu_threads": 8,
                "requested_tokens": 10_000,
                "requested_elapsed_seconds": 200.0,
            },
        )
        self.assertTrue(adm_ok["admitted"])
        self.assertEqual(adm_ok["projected_macro_cycles"], 25)
        self.assertEqual(adm_ok["projected_total_tokens"], 150_000)
        self.assertEqual(adm_ok["projected_elapsed_seconds"], 7200.0)

        # Over cycle cap (22 + 4 = 26 > 25) rejected BEFORE execution
        with self.assertRaises(ValueError):
            r2.admit_controller_move(
                arm="1a",
                ledger=prior_ledger,
                requested_usage={
                    "planned_macro_cycles": 4,
                    "configured_cpu_threads": 8,
                    "requested_tokens": 1000,
                    "requested_elapsed_seconds": 100.0,
                },
            )

        # Over token cap (140k + 10,001 > 150k) rejected BEFORE execution
        with self.assertRaises(ValueError):
            r2.admit_controller_move(
                arm="1a",
                ledger=prior_ledger,
                requested_usage={
                    "planned_macro_cycles": 2,
                    "configured_cpu_threads": 8,
                    "requested_tokens": 10_001,
                    "requested_elapsed_seconds": 100.0,
                },
            )

        # Over wall-clock cap (7000 + 200.1 > 7200) rejected BEFORE execution
        with self.assertRaises(ValueError):
            r2.admit_controller_move(
                arm="1a",
                ledger=prior_ledger,
                requested_usage={
                    "planned_macro_cycles": 2,
                    "configured_cpu_threads": 8,
                    "requested_tokens": 1000,
                    "requested_elapsed_seconds": 200.1,
                },
            )

    def test_usage_alias_consistency_for_tokens_and_elapsed_time(self) -> None:
        # #1338 reproduction: 150001-vs-0 token alias bypass in role_tokens
        for bad_role_entry in (
            {"total_tokens": 0, "tokens": 150_001},
            {"total_tokens": 150_001, "tokens": 0},
            {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "tokens": 150_001},
            {"prompt_tokens": 100, "completion_tokens": 50, "tokens": 150_001},
            {"total_tokens": 100, "tokens": True},
            {"total_tokens": 100, "tokens": False},
            {"total_tokens": 100, "tokens": math.nan},
            {"total_tokens": 100, "tokens": -1},
            {"total_tokens": 100, "tokens": "100"},
            {"total_tokens": 100, "tokens": None},
            {"prompt_tokens": 60, "completion_tokens": 40, "total_tokens": 100, "tokens": True},
        ):
            with self.subTest(bad_role_entry=bad_role_entry):
                m_bad = _make_move(1)
                m_bad["role_tokens"] = {
                    "llm": bad_role_entry,
                    "cheap_llm": 0,
                    "command_llm": 0,
                }
                with self.assertRaises(ValueError):
                    r2.verify_controller_budget(arm="1a", ledger=[m_bad])
                with self.assertRaises(ValueError):
                    r2.admit_controller_move(
                        arm="1a",
                        ledger=[],
                        requested_usage={
                            "planned_macro_cycles": 5,
                            "configured_cpu_threads": 8,
                            "role_tokens": m_bad["role_tokens"],
                            "requested_elapsed_seconds": 60.0,
                        },
                    )

        # Equal duplicate aliases in role_tokens and move-level tokens are accepted
        m_dup_ok = _make_move(1)
        m_dup_ok["role_tokens"] = {
            "llm": {
                "prompt_tokens": 600,
                "completion_tokens": 400,
                "total_tokens": 1000,
                "tokens": 1000,
            },
            "cheap_llm": {"total_tokens": 500, "tokens": 500},
            "command_llm": {"total_tokens": 0, "tokens": 0, "zero_used": True, "status": "zero_used"},
        }
        m_dup_ok["total_tokens"] = 1500
        m_dup_ok["tokens"] = 1500
        res_dup_ok = r2.verify_controller_budget(arm="1a", ledger=[m_dup_ok])
        self.assertTrue(res_dup_ok["budget_ok"])
        self.assertEqual(res_dup_ok["total_tokens"], 1500)

        # Conflicting or malformed secondary move-level token alias rejected
        for bad_move_tok in (150_001, 0, True, False, None, -1, "1500"):
            with self.subTest(bad_move_tok=bad_move_tok):
                m_conflict = copy.deepcopy(m_dup_ok)
                m_conflict["tokens"] = bad_move_tok
                with self.assertRaises(ValueError):
                    r2.verify_controller_budget(arm="1a", ledger=[m_conflict])

        # #1338 / #1340 in admit_controller_move: 150001-vs-0 token alias bypass and
        # malformed secondary token aliases rejected
        for bad_req_tokens in (
            {"requested_tokens": 0, "estimated_tokens": 150_001},
            {"requested_tokens": 0, "total_tokens": 150_001},
            {"requested_tokens": 0, "tokens": 150_001},
            {"requested_tokens": 100, "tokens": True},
            {"requested_tokens": 100, "estimated_tokens": None},
            {"requested_tokens": 100, "total_tokens": -1},
            {"requested_tokens": 100, "tokens": "100"},
        ):
            with self.subTest(bad_req_tokens=bad_req_tokens):
                with self.assertRaises(ValueError):
                    r2.admit_controller_move(
                        arm="1a",
                        ledger=[],
                        requested_usage={
                            "planned_macro_cycles": 5,
                            "configured_cpu_threads": 8,
                            "requested_elapsed_seconds": 60.0,
                            **bad_req_tokens,
                        },
                    )

        # #1340 reproduction: 7201-vs-1 elapsed time alias bypass, sub-1e-9 alias disagreement
        # just above 7200.0, and malformed secondary elapsed aliases rejected
        just_over_7200 = 7200.0 + 5e-10
        self.assertGreater(just_over_7200, 7200.0)
        self.assertLess(just_over_7200 - 7200.0, 1e-9)

        for bad_req_elapsed in (
            {"requested_elapsed_seconds": 1.0, "estimated_elapsed_seconds": 7201.0},
            {"requested_elapsed_seconds": 7201.0, "estimated_elapsed_seconds": 1.0},
            {"requested_elapsed_seconds": 1.0, "elapsed_seconds": 7201.0},
            {"requested_elapsed_seconds": 1.0, "cumulative_elapsed_seconds": 7201.0},
            {"requested_elapsed_seconds": 1.0, "projected_elapsed_seconds": 7201.0},
            # Sub-1e-9 disagreement just above 7200 cap must reject disagreement, not pick 7200.0
            {"requested_elapsed_seconds": 7200.0, "estimated_elapsed_seconds": just_over_7200},
            {"requested_elapsed_seconds": just_over_7200, "elapsed_seconds": 7200.0},
            {"requested_elapsed_seconds": 7200.0, "elapsed_seconds": just_over_7200},
            {"requested_elapsed_seconds": 7200.0, "cumulative_elapsed_seconds": just_over_7200},
            # Malformed secondary elapsed aliases
            {"requested_elapsed_seconds": 60.0, "estimated_elapsed_seconds": True},
            {"requested_elapsed_seconds": 60.0, "estimated_elapsed_seconds": math.nan},
            {"requested_elapsed_seconds": 60.0, "estimated_elapsed_seconds": math.inf},
            {"requested_elapsed_seconds": 60.0, "estimated_elapsed_seconds": -1.0},
            {"requested_elapsed_seconds": 60.0, "estimated_elapsed_seconds": None},
            {"requested_elapsed_seconds": 60.0, "elapsed_seconds": "60.0"},
            {"requested_elapsed_seconds": 60.0, "cumulative_elapsed_seconds": False},
        ):
            with self.subTest(bad_req_elapsed=bad_req_elapsed):
                with self.assertRaises(ValueError):
                    r2.admit_controller_move(
                        arm="1a",
                        ledger=[],
                        requested_usage={
                            "planned_macro_cycles": 5,
                            "configured_cpu_threads": 8,
                            "requested_tokens": 1000,
                            **bad_req_elapsed,
                        },
                    )

        # Equal duplicate prospective token & elapsed aliases at exact 7200.0 cap are accepted
        prior_m1 = _make_move(1, elapsed_seconds=7000.0)
        adm_dup_ok = r2.admit_controller_move(
            arm="1a",
            ledger=[prior_m1],
            requested_usage={
                "planned_macro_cycles": 3,
                "configured_cpu_threads": 8,
                "requested_tokens": 5000,
                "estimated_tokens": 5000,
                "total_tokens": 5000,
                "tokens": 5000,
                "requested_elapsed_seconds": 200.0,
                "estimated_elapsed_seconds": 200.0,
                "elapsed_seconds": 7200.0,
                "cumulative_elapsed_seconds": 7200.0,
                "projected_elapsed_seconds": 7200.0,
            },
        )
        self.assertTrue(adm_dup_ok["admitted"])
        self.assertEqual(adm_dup_ok["projected_elapsed_seconds"], 7200.0)

    def test_explicit_observed_move_status_required_and_reconciled(self) -> None:
        # #1339: Missing move_status / status must fail closed (no default 'completed'
        # checkpoint and no subsequent move admission)
        m_no_status = _make_move(1)
        m_no_status.pop("move_status")
        with self.assertRaisesRegex(ValueError, "missing required explicit 'move_status'"):
            r2.verify_controller_budget(arm="1a", ledger=[m_no_status])
        with self.assertRaisesRegex(ValueError, "missing required explicit 'move_status'"):
            r2.admit_controller_move(
                arm="1a",
                ledger=[m_no_status],
                requested_usage={
                    "planned_macro_cycles": 3,
                    "configured_cpu_threads": 8,
                    "requested_tokens": 1000,
                    "requested_elapsed_seconds": 60.0,
                },
            )

        # Contradictory move_status vs status (e.g. completed vs failed) or malformed
        # secondary status must fail closed in both verify_controller_budget and admit_controller_move
        for move_st, alias_st in (
            ("completed", "failed"),
            ("failed", "completed"),
            ("completed", "aborted"),
            ("completed", "aborted_before_execution"),
            ("completed", None),
            ("completed", True),
            ("completed", "unknown_status"),
            ("invalid_status", "completed"),
        ):
            with self.subTest(move_st=move_st, alias_st=alias_st):
                m_conflict = _make_move(1)
                m_conflict["move_status"] = move_st
                m_conflict["status"] = alias_st
                with self.assertRaises(ValueError):
                    r2.verify_controller_budget(arm="1a", ledger=[m_conflict])
                with self.assertRaises(ValueError):
                    r2.admit_controller_move(
                        arm="1a",
                        ledger=[m_conflict],
                        requested_usage={
                            "planned_macro_cycles": 3,
                            "configured_cpu_threads": 8,
                            "requested_tokens": 1000,
                            "requested_elapsed_seconds": 60.0,
                        },
                    )

        # Equal valid duplicate (move_status == status) and standalone 'status' pass,
        # and next move admission succeeds only when explicit status is 'completed'
        m_dup_completed = _make_move(1)
        m_dup_completed["status"] = "completed"
        res_dup = r2.verify_controller_budget(arm="1a", ledger=[m_dup_completed])
        self.assertTrue(res_dup["move_1_checkpoint_completed"])
        self.assertTrue(res_dup["all_recorded_moves_completed"])
        self.assertFalse(res_dup["contains_failed_or_aborted_move"])
        self.assertEqual(res_dup["scientific_arm_completion"], "not_assessed")
        self.assertNotIn("run_completed", res_dup)
        self.assertNotIn("failed_or_aborted", res_dup)

        adm_after_explicit = r2.admit_controller_move(
            arm="1a",
            ledger=[m_dup_completed],
            requested_usage={
                "planned_macro_cycles": 3,
                "configured_cpu_threads": 8,
                "requested_tokens": 1000,
                "requested_elapsed_seconds": 60.0,
            },
        )
        self.assertTrue(adm_after_explicit["admitted"])

        # Aborted/failed move with equal duplicate status preserves partial observed cycles
        # and blocks subsequent move admission pending a selected transition policy
        m_dup_failed = _make_move(
            1,
            planned_macro_cycles=5,
            observed_macro_cycles=2,
            move_status="failed",
        )
        m_dup_failed["status"] = "failed"
        res_dup_failed = r2.verify_controller_budget(arm="1a", ledger=[m_dup_failed])
        self.assertFalse(res_dup_failed["move_1_checkpoint_completed"])
        self.assertFalse(res_dup_failed["all_recorded_moves_completed"])
        self.assertTrue(res_dup_failed["contains_failed_or_aborted_move"])
        self.assertEqual(res_dup_failed["scientific_arm_completion"], "not_assessed")
        self.assertEqual(res_dup_failed["move_1_observed_macro_cycles"], 2)
        with self.assertRaisesRegex(
            ValueError, "lacks a selected transition policy"
        ):
            r2.admit_controller_move(
                arm="1a",
                ledger=[m_dup_failed],
                requested_usage={
                    "planned_macro_cycles": 3,
                    "configured_cpu_threads": 8,
                    "requested_tokens": 1000,
                    "requested_elapsed_seconds": 60.0,
                },
            )

    def test_arm1b_typed_provenance_bindings_and_sha256_strictness(self) -> None:
        # 1. Valid 64-hex lowercase SHA-256 and dual UTF-8 text + SHA-256 bindings
        raw_primary = "phenix.refine model.pdb data.mtz main.number_of_macro_cycles=5"
        raw_backup = "phenix.refine model.pdb data.mtz strategy=individual_sites+individual_adp"
        raw_actual = raw_primary
        raw_eff = "refinement {\n  main {\n    number_of_macro_cycles = 5\n  }\n}\n"

        sha_primary = hashlib.sha256(raw_primary.encode("utf-8")).hexdigest()
        sha_backup = hashlib.sha256(raw_backup.encode("utf-8")).hexdigest()
        sha_actual = hashlib.sha256(raw_actual.encode("utf-8")).hexdigest()
        sha_eff = hashlib.sha256(raw_eff.encode("utf-8")).hexdigest()

        m_valid = _make_move(1, arm1b=True)
        m_valid["arm1b_provenance"] = {
            "primary_command": raw_primary,
            "primary_command_sha256": sha_primary,
            "mechanical_backup_command": raw_backup,
            "mechanical_backup": raw_backup,
            "mechanical_backup_sha256": sha_backup,
            "actual_command_sha256": sha_actual,
            "effective_eff_receipt": raw_eff,
        }
        # Equal top-level duplicate sha256 alias is reconciled
        m_valid["primary_command_sha256"] = sha_primary

        res_valid = r2.verify_controller_budget(arm="1b", ledger=[m_valid])
        prov = res_valid["moves"][0]["arm1b_provenance"]
        self.assertFalse(prov["verified_artifact_bytes_exist"])
        self.assertIn("does not prove actual artifact bytes exist", prov["epistemic_note"])
        self.assertEqual(
            prov["primary_command"],
            {
                "state": "available",
                "representation": "utf8_text_and_sha256",
                "sha256": sha_primary,
                "text": raw_primary,
                "reason": None,
                "verified_artifact_bytes_exist": False,
            },
        )
        self.assertEqual(
            prov["actual_command"],
            {
                "state": "available",
                "representation": "sha256",
                "sha256": sha_actual,
                "text": None,
                "reason": None,
                "verified_artifact_bytes_exist": False,
            },
        )
        self.assertEqual(
            prov["effective_eff"],
            {
                "state": "available",
                "representation": "utf8_text",
                "sha256": sha_eff,
                "text": raw_eff,
                "reason": None,
                "verified_artifact_bytes_exist": False,
            },
        )

        # 2. Malformed SHA-256 and trailing LF / whitespace strictly rejected (\Z)
        for bad_sha in (
            "a" * 64 + "\n",
            "a" * 64 + " ",
            " " + "a" * 64,
            "A" * 64,
            "a" * 63,
            "a" * 65,
            "g" * 64,
            "not-a-sha256-digest",
            "",
            None,
            True,
            12345,
        ):
            with self.subTest(bad_sha=bad_sha):
                m_bad_sha = _make_move(1, arm1b=True)
                m_bad_sha["arm1b_provenance"]["primary_command_sha256"] = bad_sha  # type: ignore[index]
                with self.assertRaises(ValueError):
                    r2.verify_controller_budget(arm="1b", ledger=[m_bad_sha])

        # 3. Alias conflicts: nested vs top-level sha256, same-kind text aliases, and UTF-8 text vs sha256 mismatch
        m_nested_vs_top = _make_move(1, arm1b=True)
        m_nested_vs_top["primary_command_sha256"] = "e" * 64
        with self.assertRaisesRegex(ValueError, "SHA-256 aliases disagree"):
            r2.verify_controller_budget(arm="1b", ledger=[m_nested_vs_top])

        m_same_kind_text_conflict = _make_move(1, arm1b=True)
        m_same_kind_text_conflict["arm1b_provenance"]["mechanical_backup_command"] = raw_backup  # type: ignore[index]
        m_same_kind_text_conflict["arm1b_provenance"]["mechanical_backup"] = raw_backup + " --other"  # type: ignore[index]
        m_same_kind_text_conflict["arm1b_provenance"]["mechanical_backup_sha256"] = sha_backup  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "text aliases disagree"):
            r2.verify_controller_budget(arm="1b", ledger=[m_same_kind_text_conflict])

        m_utf8_mismatch = _make_move(1, arm1b=True)
        m_utf8_mismatch["arm1b_provenance"]["primary_command"] = raw_primary  # type: ignore[index]
        m_utf8_mismatch["arm1b_provenance"]["primary_command_sha256"] = "f" * 64  # type: ignore[index]
        with self.assertRaisesRegex(ValueError, "UTF-8 SHA-256 mismatch"):
            r2.verify_controller_budget(arm="1b", ledger=[m_utf8_mismatch])

        # 4. Aborted-before-execution: actual/effective must be unavailable (no fake hash or command),
        # while primary/backup must remain available
        m_aborted_pre = _make_move(
            1,
            planned_macro_cycles=5,
            observed_macro_cycles=0,
            move_status="aborted_before_execution",
            arm1b=True,
        )
        res_aborted_pre = r2.verify_controller_budget(arm="1b", ledger=[m_aborted_pre])
        prov_pre = res_aborted_pre["moves"][0]["arm1b_provenance"]
        self.assertEqual(prov_pre["actual_command"]["state"], "unavailable")
        self.assertEqual(prov_pre["actual_command"]["reason"], "unavailable_not_executed")
        self.assertIsNone(prov_pre["actual_command"]["sha256"])
        self.assertEqual(prov_pre["effective_eff"]["state"], "unavailable")

        # Fake raw command on aborted_before_execution rejected
        m_aborted_fake_cmd = copy.deepcopy(m_aborted_pre)
        m_aborted_fake_cmd["arm1b_provenance"].pop("actual_command_sha256")  # type: ignore[attr-defined]
        m_aborted_fake_cmd["arm1b_provenance"]["actual_command"] = raw_actual  # type: ignore[index]
        with self.assertRaises(ValueError):
            r2.verify_controller_budget(arm="1b", ledger=[m_aborted_fake_cmd])

        # Completed moves reject unavailable primary_command or mechanical_backup
        for pre_slot in ("primary_command_sha256", "mechanical_backup_sha256"):
            with self.subTest(completed_unavail_pre_slot=pre_slot):
                m_bad_completed_pre = _make_move(1, move_status="completed", arm1b=True)
                m_bad_completed_pre["arm1b_provenance"][pre_slot] = {  # type: ignore[index]
                    "state": "unavailable",
                    "reason": "planner_failed_before_command_synthesis",
                }
                with self.assertRaises(ValueError):
                    r2.verify_controller_budget(arm="1b", ledger=[m_bad_completed_pre])

        # Early planner failure (failed / aborted / aborted_before_execution) with four explicit
        # reason-bearing unavailable bindings and zero observed macro-cycles retains a
        # failed/non-completed denominator record without inventing artifacts
        for early_status in ("failed", "aborted", "aborted_before_execution"):
            with self.subTest(early_planner_failure_status=early_status):
                m_early_fail = _make_move(
                    1,
                    planned_macro_cycles=5,
                    observed_macro_cycles=0,
                    move_status=early_status,
                    arm1b=True,
                )
                m_early_fail["arm1b_provenance"] = {
                    "primary_command": {
                        "state": "unavailable",
                        "representation": "unavailable",
                        "reason": "planner_llm_timeout_before_primary_command",
                    },
                    "mechanical_backup": {
                        "state": "unavailable",
                        "reason": "planner_llm_timeout_before_backup_command",
                    },
                    "actual_command_sha256": "unavailable_not_executed",
                    "effective_eff_sha256": {
                        "state": "unavailable",
                        "representation": "unavailable",
                        "reason": "not_executed",
                    },
                }
                res_early = r2.verify_controller_budget(arm="1b", ledger=[m_early_fail])
                self.assertEqual(res_early["move_1_planned_macro_cycles"], 5)
                self.assertEqual(res_early["move_1_observed_macro_cycles"], 0)
                self.assertFalse(res_early["move_1_checkpoint_completed"])
                self.assertFalse(res_early["all_recorded_moves_completed"])
                self.assertTrue(res_early["contains_failed_or_aborted_move"])
                self.assertEqual(res_early["scientific_arm_completion"], "not_assessed")
                self.assertNotIn("run_completed", res_early)
                self.assertNotIn("failed_or_aborted", res_early)
                self.assertTrue(res_early["retained_in_denominator"])
                early_prov = res_early["moves"][0]["arm1b_provenance"]
                self.assertEqual(early_prov["primary_command"]["state"], "unavailable")
                self.assertEqual(
                    early_prov["primary_command"]["reason"],
                    "planner_llm_timeout_before_primary_command",
                )
                self.assertEqual(early_prov["mechanical_backup"]["state"], "unavailable")
                self.assertEqual(early_prov["actual_command"]["state"], "unavailable")
                self.assertEqual(early_prov["effective_eff"]["state"], "unavailable")

                # Missing any of the four slots on an early failure still rejects
                for missing_slot_key in (
                    "primary_command",
                    "mechanical_backup",
                    "actual_command_sha256",
                    "effective_eff_sha256",
                ):
                    m_early_missing = copy.deepcopy(m_early_fail)
                    m_early_missing["arm1b_provenance"].pop(missing_slot_key)  # type: ignore[attr-defined]
                    with self.assertRaises(ValueError):
                        r2.verify_controller_budget(arm="1b", ledger=[m_early_missing])

        # 5. Failed/aborted moves allow explicit field-specific unavailability on actual/effective,
        # while completed moves reject it
        m_failed_unavail = _make_move(
            1,
            planned_macro_cycles=5,
            observed_macro_cycles=2,
            move_status="failed",
            arm1b=True,
        )
        m_failed_unavail["arm1b_provenance"]["effective_eff_sha256"] = {  # type: ignore[index]
            "state": "unavailable",
            "reason": "process_crashed_before_eff_flush",
        }
        res_failed_unavail = r2.verify_controller_budget(arm="1b", ledger=[m_failed_unavail])
        self.assertEqual(
            res_failed_unavail["moves"][0]["arm1b_provenance"]["effective_eff"],
            {
                "state": "unavailable",
                "representation": "unavailable",
                "sha256": None,
                "text": None,
                "reason": "process_crashed_before_eff_flush",
                "verified_artifact_bytes_exist": False,
            },
        )

        m_completed_unavail = _make_move(1, move_status="completed", arm1b=True)
        m_completed_unavail["arm1b_provenance"]["effective_eff_sha256"] = {  # type: ignore[index]
            "state": "unavailable",
            "reason": "process_crashed_before_eff_flush",
        }
        with self.assertRaises(ValueError):
            r2.verify_controller_budget(arm="1b", ledger=[m_completed_unavail])

        # 6. Typed mapping representation validation: correct supplied labels & omitted-label
        # derivation pass; contradictory/unknown/non-string labels reject
        m_rep_ok = _make_move(1, move_status="completed", arm1b=True)
        m_rep_ok["arm1b_provenance"] = {
            "primary_command": {
                "state": "available",
                "representation": "utf8_text_and_sha256",
                "text": raw_primary,
                "sha256": sha_primary,
            },
            "mechanical_backup": {
                "state": "available",
                "representation": "utf8_text",
                "text": raw_backup,
            },
            "actual_command_sha256": {
                "state": "available",
                "representation": "sha256",
                "sha256": sha_actual,
            },
            "effective_eff": {
                "state": "available",
                "text": raw_eff,
                "sha256": sha_eff,
            },
        }
        res_rep_ok = r2.verify_controller_budget(arm="1b", ledger=[m_rep_ok])
        prov_rep_ok = res_rep_ok["moves"][0]["arm1b_provenance"]
        self.assertEqual(
            prov_rep_ok["primary_command"]["representation"], "utf8_text_and_sha256"
        )
        self.assertEqual(prov_rep_ok["mechanical_backup"]["representation"], "utf8_text")
        self.assertEqual(prov_rep_ok["actual_command"]["representation"], "sha256")
        self.assertEqual(
            prov_rep_ok["effective_eff"]["representation"], "utf8_text_and_sha256"
        )

        for bad_rep_map in (
            {
                "state": "available",
                "representation": "unavailable",
                "sha256": sha_primary,
            },
            {
                "state": "available",
                "representation": "utf8_text",
                "sha256": sha_primary,
            },
            {
                "state": "available",
                "representation": "utf8_text_and_sha256",
                "sha256": sha_primary,
            },
            {
                "state": "available",
                "representation": "sha256",
                "text": raw_primary,
            },
            {
                "state": "available",
                "representation": "sha256",
                "text": raw_primary,
                "sha256": sha_primary,
            },
            {
                "state": "available",
                "representation": "utf8_text",
                "text": raw_primary,
                "sha256": sha_primary,
            },
            {
                "state": "available",
                "representation": "unknown_label",
                "sha256": sha_primary,
            },
            {
                "state": "available",
                "representation": None,
                "sha256": sha_primary,
            },
            {
                "state": "available",
                "representation": True,
                "sha256": sha_primary,
            },
        ):
            with self.subTest(bad_rep_map=bad_rep_map):
                m_bad_rep = _make_move(1, move_status="completed", arm1b=True)
                m_bad_rep["arm1b_provenance"]["primary_command_sha256"] = bad_rep_map  # type: ignore[index]
                with self.assertRaises(ValueError):
                    r2.verify_controller_budget(arm="1b", ledger=[m_bad_rep])

        # Unavailable state with non-'unavailable' representation rejects
        m_bad_unavail_rep = _make_move(
            1,
            planned_macro_cycles=5,
            observed_macro_cycles=0,
            move_status="failed",
            arm1b=True,
        )
        m_bad_unavail_rep["arm1b_provenance"]["actual_command_sha256"] = {  # type: ignore[index]
            "state": "unavailable",
            "representation": "sha256",
            "reason": "not_executed",
        }
        with self.assertRaises(ValueError):
            r2.verify_controller_budget(arm="1b", ledger=[m_bad_unavail_rep])

        # Explicit representation='sha256' in mapping combined with top-level raw text on same slot rejects
        m_cross_rep_conflict = _make_move(1, move_status="completed", arm1b=True)
        m_cross_rep_conflict["arm1b_provenance"]["primary_command_sha256"] = {  # type: ignore[index]
            "state": "available",
            "representation": "sha256",
            "sha256": sha_primary,
        }
        m_cross_rep_conflict["primary_command"] = raw_primary
        with self.assertRaisesRegex(ValueError, "contradicts resolved slot representation"):
            r2.verify_controller_budget(arm="1b", ledger=[m_cross_rep_conflict])

    def test_ledger_facts_versus_scientific_arm_completion_and_transition_policy(self) -> None:
        # 1. Bounded fixture: one completed move records move-ledger facts only
        # and keeps scientific_arm_completion == 'not_assessed' (no old ambiguous aliases)
        m1_done = _make_move(1, planned_macro_cycles=5, observed_macro_cycles=5, move_status="completed")
        res_one_done = r2.verify_controller_budget(arm="1a", ledger=[m1_done])
        self.assertTrue(res_one_done["all_recorded_moves_completed"])
        self.assertFalse(res_one_done["contains_failed_or_aborted_move"])
        self.assertEqual(res_one_done["scientific_arm_completion"], "not_assessed")
        self.assertNotIn("run_completed", res_one_done)
        self.assertNotIn("failed_or_aborted", res_one_done)

        # 2. Bounded fixture: failed move records move-ledger facts only, retains denominator
        # membership, and keeps scientific_arm_completion == 'not_assessed'
        m1_fail = _make_move(1, planned_macro_cycles=5, observed_macro_cycles=2, move_status="failed")
        res_one_fail = r2.verify_controller_budget(arm="1a", ledger=[m1_fail])
        self.assertFalse(res_one_fail["all_recorded_moves_completed"])
        self.assertTrue(res_one_fail["contains_failed_or_aborted_move"])
        self.assertEqual(res_one_fail["scientific_arm_completion"], "not_assessed")
        self.assertTrue(res_one_fail["retained_in_denominator"])
        self.assertNotIn("run_completed", res_one_fail)
        self.assertNotIn("failed_or_aborted", res_one_fail)

        # 3. Bounded fixture: unsupported continuation after failed/aborted move reports
        # that this implementation lacks a selected transition policy (not that U08/U10/U12
        # forbids retries or defines whole-arm failure from a single move)
        for bad_prior_status, obs_cyc in (
            ("failed", 2),
            ("aborted", 1),
            ("aborted_before_execution", 0),
        ):
            with self.subTest(bad_prior_status=bad_prior_status):
                m_prior = _make_move(
                    1,
                    planned_macro_cycles=5,
                    observed_macro_cycles=obs_cyc,
                    move_status=bad_prior_status,
                )
                with self.assertRaises(ValueError) as ctx:
                    r2.admit_controller_move(
                        arm="1a",
                        ledger=[m_prior],
                        requested_usage={
                            "planned_macro_cycles": 3,
                            "configured_cpu_threads": 8,
                            "requested_tokens": 1000,
                            "requested_elapsed_seconds": 60.0,
                        },
                    )
                err_msg = str(ctx.exception)
                self.assertIn("this implementation lacks a selected transition policy", err_msg)
                self.assertIn("does not forbid retries", err_msg)

    def test_explicit_later_non_refinement_moves_and_refinement_constraints(self) -> None:
        # 1. Multi-program synthetic ledger (Arm 1b):
        # Move 1: explicit refinement (planned=5, observed=5)
        # Move 2: explicit non_refinement (planned=0, observed=0, retains tokens/wall/move count/receipts)
        # Move 3: explicit refinement (planned=3, observed=3)
        m1_ref = _make_move(
            1,
            planned_macro_cycles=5,
            observed_macro_cycles=5,
            move_status="completed",
            llm_tokens=1000,
            cheap_tokens=500,
            command_tokens=500,
            elapsed_seconds=300.0,
            arm1b=True,
        )
        m1_ref["move_kind"] = "refinement"

        m2_nonref = _make_move(
            2,
            planned_macro_cycles=0,
            observed_macro_cycles=0,
            move_status="completed",
            llm_tokens=600,
            cheap_tokens=200,
            command_tokens=200,
            elapsed_seconds=420.0,
            arm1b=True,
        )
        m2_nonref["move_kind"] = "non_refinement"

        m3_ref = _make_move(
            3,
            planned_macro_cycles=3,
            observed_macro_cycles=3,
            move_status="completed",
            llm_tokens=800,
            cheap_tokens=300,
            command_tokens=400,
            elapsed_seconds=700.0,
            arm1b=True,
        )
        m3_ref["move_kind"] = "refinement"

        res_multi = r2.verify_controller_budget(
            arm="1b", ledger=[m1_ref, m2_nonref, m3_ref]
        )
        self.assertTrue(res_multi["budget_ok"])
        self.assertEqual(res_multi["move_count"], 3)
        self.assertEqual(res_multi["total_planned_macro_cycles"], 8)
        self.assertEqual(res_multi["total_observed_macro_cycles"], 8)
        self.assertEqual(res_multi["total_tokens"], 4500)
        self.assertEqual(res_multi["elapsed_seconds"], 700.0)
        self.assertTrue(res_multi["move_1_checkpoint_completed"])
        self.assertTrue(res_multi["all_recorded_moves_completed"])
        self.assertEqual(res_multi["moves"][1]["move_kind"], "non_refinement")
        self.assertTrue(res_multi["moves"][1]["move_kind_explicit"])
        self.assertTrue(res_multi["moves"][1]["completed_checkpoint"])
        self.assertEqual(
            res_multi["moves"][1]["arm1b_provenance"]["primary_command"]["state"],
            "available",
        )

        # Prospective admission of later non_refinement move (Move 2) with planned_macro_cycles=0
        adm_nonref = r2.admit_controller_move(
            arm="1b",
            ledger=[m1_ref],
            requested_usage={
                "move_kind": "non_refinement",
                "planned_macro_cycles": 0,
                "configured_cpu_threads": 8,
                "requested_tokens": 1000,
                "requested_elapsed_seconds": 120.0,
            },
        )
        self.assertTrue(adm_nonref["admitted"])
        self.assertEqual(adm_nonref["next_move_index"], 2)
        self.assertEqual(adm_nonref["move_kind"], "non_refinement")
        self.assertTrue(adm_nonref["move_kind_explicit"])
        self.assertEqual(adm_nonref["planned_macro_cycles"], 0)
        self.assertEqual(adm_nonref["projected_macro_cycles"], 5)
        self.assertEqual(adm_nonref["projected_total_tokens"], 3000)
        self.assertEqual(adm_nonref["projected_elapsed_seconds"], 420.0)

        # 2. Missing move_kind (or explicit refinement) with planned_macro_cycles=0 is rejected
        # (never infers non_refinement from zero macro-cycles)
        for kind_opt in (None, "refinement"):
            with self.subTest(missing_or_ref_kind_zero=kind_opt):
                m2_zero_no_kind = _make_move(
                    2,
                    planned_macro_cycles=0,
                    observed_macro_cycles=0,
                    move_status="completed",
                    elapsed_seconds=420.0,
                )
                if kind_opt is not None:
                    m2_zero_no_kind["move_kind"] = kind_opt
                with self.assertRaises(ValueError):
                    r2.verify_controller_budget(
                        arm="1a", ledger=[m1_ref, m2_zero_no_kind]
                    )
                req_zero: dict[str, object] = {
                    "planned_macro_cycles": 0,
                    "configured_cpu_threads": 8,
                    "requested_tokens": 1000,
                    "requested_elapsed_seconds": 120.0,
                }
                if kind_opt is not None:
                    req_zero["move_kind"] = kind_opt
                with self.assertRaises(ValueError):
                    r2.admit_controller_move(
                        arm="1a", ledger=[m1_ref], requested_usage=req_zero
                    )

        # 3. Move 1 with move_kind='non_refinement' is rejected in both verify and admit
        for m1_planned in (0, 5):
            with self.subTest(m1_nonref_planned=m1_planned):
                m1_bad_nonref = _make_move(
                    1,
                    planned_macro_cycles=m1_planned,
                    observed_macro_cycles=m1_planned,
                    move_status="completed",
                )
                m1_bad_nonref["move_kind"] = "non_refinement"
                with self.assertRaises(ValueError):
                    r2.verify_controller_budget(arm="1a", ledger=[m1_bad_nonref])
                with self.assertRaises(ValueError):
                    r2.admit_controller_move(
                        arm="1a",
                        ledger=[],
                        requested_usage={
                            "move_kind": "non_refinement",
                            "planned_macro_cycles": m1_planned,
                            "configured_cpu_threads": 8,
                            "requested_tokens": 1000,
                            "requested_elapsed_seconds": 60.0,
                        },
                    )

        # 4. Later non_refinement move with non-zero planned or observed macro-cycles is rejected
        for bad_plan, bad_obs in ((1, 0), (0, 1), (2, 2)):
            with self.subTest(nonref_bad_plan=bad_plan, nonref_bad_obs=bad_obs):
                m2_bad_nonref = copy.deepcopy(m2_nonref)
                m2_bad_nonref["planned_macro_cycles"] = bad_plan
                m2_bad_nonref["observed_macro_cycles"] = bad_obs
                with self.assertRaises(ValueError):
                    r2.verify_controller_budget(
                        arm="1b", ledger=[m1_ref, m2_bad_nonref]
                    )
        with self.assertRaises(ValueError):
            r2.admit_controller_move(
                arm="1b",
                ledger=[m1_ref],
                requested_usage={
                    "move_kind": "non_refinement",
                    "planned_macro_cycles": 1,
                    "configured_cpu_threads": 8,
                    "requested_tokens": 1000,
                    "requested_elapsed_seconds": 60.0,
                },
            )

        # 5. Failed later refinement move with 0 observed macro-cycles is preserved without
        # violation, while completed later refinement move with 0 observed macro-cycles
        # records completed_move_zero_observed_macro_cycles violation
        m2_failed_ref_zero = _make_move(
            2,
            planned_macro_cycles=3,
            observed_macro_cycles=0,
            move_status="failed",
            elapsed_seconds=420.0,
        )
        m2_failed_ref_zero["move_kind"] = "refinement"
        res_failed_ref_zero = r2.verify_controller_budget(
            arm="1a", ledger=[m1_ref, m2_failed_ref_zero]
        )
        self.assertTrue(res_failed_ref_zero["budget_ok"])
        self.assertTrue(res_failed_ref_zero["contains_failed_or_aborted_move"])
        self.assertEqual(res_failed_ref_zero["total_planned_macro_cycles"], 8)
        self.assertEqual(res_failed_ref_zero["total_observed_macro_cycles"], 5)

        m2_completed_ref_zero = _make_move(
            2,
            planned_macro_cycles=3,
            observed_macro_cycles=0,
            move_status="completed",
            elapsed_seconds=420.0,
        )
        m2_completed_ref_zero["move_kind"] = "refinement"
        res_completed_ref_zero = r2.verify_controller_budget(
            arm="1a", ledger=[m1_ref, m2_completed_ref_zero]
        )
        self.assertFalse(res_completed_ref_zero["budget_ok"])
        self.assertIn(
            "completed_move_zero_observed_macro_cycles",
            res_completed_ref_zero["violation_codes"],
        )

    def test_stops_admission_when_any_cumulative_cap_is_already_exhausted(self) -> None:
        # 1. Cycle cap exhausted at 5 + 20 = 25 observed macro-cycles:
        # observed ledger at cap is compliant/retained, but Move 3 (even non_refinement with 0 cycles) is stopped
        ledger_25_cycles = [
            _make_move(1, planned_macro_cycles=5, observed_macro_cycles=5, elapsed_seconds=300.0),
            _make_move(2, planned_macro_cycles=20, observed_macro_cycles=20, elapsed_seconds=900.0),
        ]
        res_25 = r2.verify_controller_budget(arm="1a", ledger=ledger_25_cycles)
        self.assertTrue(res_25["budget_ok"])
        self.assertTrue(res_25["retained_in_denominator"])
        self.assertEqual(res_25["total_observed_macro_cycles"], 25)
        with self.assertRaisesRegex(
            ValueError,
            r"prior ledger has already exhausted the U12 cumulative macro-cycle cap \(25/25\)",
        ):
            r2.admit_controller_move(
                arm="1a",
                ledger=ledger_25_cycles,
                requested_usage={
                    "move_kind": "non_refinement",
                    "planned_macro_cycles": 0,
                    "configured_cpu_threads": 8,
                    "requested_tokens": 500,
                    "requested_elapsed_seconds": 30.0,
                },
            )

        # 2. Token cap exhausted at 150,000 tokens:
        # observed ledger at cap is compliant/retained, but next move with 0 requested tokens is stopped
        ledger_150k_tokens = [
            _make_move(
                1,
                planned_macro_cycles=5,
                observed_macro_cycles=5,
                llm_tokens=100_000,
                cheap_tokens=25_000,
                command_tokens=25_000,
                elapsed_seconds=300.0,
            )
        ]
        res_150k = r2.verify_controller_budget(arm="1a", ledger=ledger_150k_tokens)
        self.assertTrue(res_150k["budget_ok"])
        self.assertTrue(res_150k["retained_in_denominator"])
        self.assertEqual(res_150k["total_tokens"], 150_000)
        with self.assertRaisesRegex(
            ValueError,
            r"prior ledger has already exhausted the U12 cumulative token cap \(150000/150000\)",
        ):
            r2.admit_controller_move(
                arm="1a",
                ledger=ledger_150k_tokens,
                requested_usage={
                    "planned_macro_cycles": 3,
                    "configured_cpu_threads": 8,
                    "requested_tokens": 0,
                    "requested_elapsed_seconds": 30.0,
                },
            )

        # 3. Wall-clock cap exhausted at 7200.0 seconds:
        # observed ledger at cap is compliant/retained, but next move with 0.0s increment is stopped
        ledger_7200s = [
            _make_move(1, planned_macro_cycles=5, observed_macro_cycles=5, elapsed_seconds=7200.0)
        ]
        res_7200s = r2.verify_controller_budget(arm="1a", ledger=ledger_7200s)
        self.assertTrue(res_7200s["budget_ok"])
        self.assertTrue(res_7200s["retained_in_denominator"])
        self.assertEqual(res_7200s["elapsed_seconds"], 7200.0)
        with self.assertRaisesRegex(
            ValueError,
            r"prior ledger has already exhausted the U12 cumulative wall-clock cap \(7200\.0/7200\.0s\)",
        ):
            r2.admit_controller_move(
                arm="1a",
                ledger=ledger_7200s,
                requested_usage={
                    "planned_macro_cycles": 3,
                    "configured_cpu_threads": 8,
                    "requested_tokens": 100,
                    "requested_elapsed_seconds": 0.0,
                },
            )

        # 4. Reaching caps from below (Move 8 reaching 25 cycles, 150k tokens, 7200.0s) is admitted
        ledger_7_moves = [
            _make_move(
                idx,
                planned_macro_cycles=(5 if idx == 1 else 3),
                observed_macro_cycles=(5 if idx == 1 else 3),
                llm_tokens=10_000,
                cheap_tokens=5_000,
                command_tokens=5_000,
                elapsed_seconds=float(idx * 900),
            )
            for idx in range(1, 8)
        ]
        adm_reach_cap = r2.admit_controller_move(
            arm="1a",
            ledger=ledger_7_moves,
            requested_usage={
                "planned_macro_cycles": 2,
                "configured_cpu_threads": 8,
                "requested_tokens": 10_000,
                "requested_elapsed_seconds": 900.0,
            },
        )
        self.assertTrue(adm_reach_cap["admitted"])
        self.assertEqual(adm_reach_cap["projected_move_count"], 8)
        self.assertEqual(adm_reach_cap["projected_macro_cycles"], 25)
        self.assertEqual(adm_reach_cap["projected_total_tokens"], 150_000)
        self.assertEqual(adm_reach_cap["projected_elapsed_seconds"], 7200.0)

    def test_reconciles_non_execution_receipts_with_positive_observed_cycles(self) -> None:
        # 1. Failed or aborted Arm 1b move with observed_macro_cycles > 0 rejects non-execution markers
        # on actual_command or effective_eff (both shorthand and typed mapping)
        for status in ("failed", "aborted"):
            for marker in (
                "not_executed",
                "unavailable_not_executed",
                "aborted_before_execution",
            ):
                for slot_key in ("actual_command_sha256", "effective_eff_sha256"):
                    with self.subTest(
                        status=status, marker=marker, slot_key=slot_key, form="shorthand"
                    ):
                        m_bad = _make_move(
                            1,
                            planned_macro_cycles=5,
                            observed_macro_cycles=2,
                            move_status=status,
                            arm1b=True,
                        )
                        m_bad["arm1b_provenance"][slot_key] = marker  # type: ignore[index]
                        with self.assertRaisesRegex(
                            ValueError,
                            r"binding claims non-execution.*contradicts observed_macro_cycles=2",
                        ):
                            r2.verify_controller_budget(arm="1b", ledger=[m_bad])

                    with self.subTest(
                        status=status, marker=marker, slot_key=slot_key, form="typed"
                    ):
                        m_bad_typed = _make_move(
                            1,
                            planned_macro_cycles=5,
                            observed_macro_cycles=2,
                            move_status=status,
                            arm1b=True,
                        )
                        m_bad_typed["arm1b_provenance"][slot_key] = {  # type: ignore[index]
                            "state": "unavailable",
                            "reason": marker,
                        }
                        with self.assertRaisesRegex(
                            ValueError,
                            r"binding claims non-execution.*contradicts observed_macro_cycles=2",
                        ):
                            r2.verify_controller_budget(arm="1b", ledger=[m_bad_typed])

        # 2. Positive observed cycles with ordinary missing-artifact / execution-failed reasons on
        # actual/effective AND independent unavailability on primary/backup remains valid evidence retention
        for status in ("failed", "aborted"):
            m_valid_fail = _make_move(
                1,
                planned_macro_cycles=5,
                observed_macro_cycles=2,
                move_status=status,
                arm1b=True,
            )
            m_valid_fail["arm1b_provenance"] = {
                "primary_command_sha256": {
                    "state": "unavailable",
                    "reason": "llm primary command rejected by pre-dispatch validator; mechanical backup executed",
                },
                "mechanical_backup_sha256": "b" * 64,
                "actual_command_sha256": "c" * 64,
                "effective_eff_sha256": {
                    "state": "unavailable",
                    "reason": "unavailable_execution_failed",
                },
            }
            res_valid_fail = r2.verify_controller_budget(arm="1b", ledger=[m_valid_fail])
            self.assertTrue(res_valid_fail["budget_ok"])
            self.assertEqual(res_valid_fail["total_observed_macro_cycles"], 2)
            self.assertEqual(
                res_valid_fail["moves"][0]["arm1b_provenance"]["effective_eff"]["reason"],
                "unavailable_execution_failed",
            )

        # 3. Zero observed cycles (observed_macro_cycles == 0) legitimately retains non-execution markers
        for status in ("failed", "aborted", "aborted_before_execution"):
            m_zero = _make_move(
                1,
                planned_macro_cycles=5,
                observed_macro_cycles=0,
                move_status=status,
                arm1b=True,
            )
            m_zero["arm1b_provenance"] = {
                "primary_command_sha256": "not_executed",
                "mechanical_backup_sha256": "not_executed",
                "actual_command_sha256": "not_executed",
                "effective_eff_sha256": "aborted_before_execution",
            }
            res_zero = r2.verify_controller_budget(arm="1b", ledger=[m_zero])
            self.assertTrue(res_zero["budget_ok"])
            self.assertEqual(res_zero["total_observed_macro_cycles"], 0)


class TestPureStdlibAndNoExecution(unittest.TestCase):
    """Verify scripts/phenix_stage2_runtime.py imports only pure Python stdlib modules."""

    def test_no_forbidden_imports(self) -> None:
        src_path = SCRIPT_DIR / "phenix_stage2_runtime.py"
        tree = ast.parse(src_path.read_text(encoding="utf-8"), filename=str(src_path))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])

        forbidden = {
            "subprocess",
            "os",
            "socket",
            "urllib",
            "http",
            "requests",
            "langchain",
            "openai",
            "google",
            "ollama",
            "libtbx",
            "phenix",
            "iotbx",
            "mmtbx",
            "cctbx",
            "toolchain",
        }
        self.assertEqual(imported & forbidden, set())


if __name__ == "__main__":
    unittest.main()
