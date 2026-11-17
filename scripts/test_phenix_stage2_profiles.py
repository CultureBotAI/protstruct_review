#!/usr/bin/env python3
"""Focused hermetic unit tests for scripts/phenix_stage2_profiles.py (U04)."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import pickle
import sys
import unittest

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import phenix_stage2_profiles as p2  # noqa: E402

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_HD_FREE = "c" * 64
SHA_HD_RECEIPT = "d" * 64
VALID_HD_RECEIPT = {
    "receipt_sha256": SHA_HD_RECEIPT,
    "subject_model_sha256": SHA_HD_FREE,
    "hd_atom_count": 0,
}


class TestResolutionTier(unittest.TestCase):
    """Verify exact half-open resolution tier boundaries and invalid input rejection."""

    def test_exact_half_open_boundaries(self) -> None:
        cases = [
            (0.75, "T1", True, False, True, True),
            (0.8999, "T1", True, False, True, True),
            (0.90, "T1", True, False, True, False),
            (1.0999, "T1", True, False, True, False),
            (1.10, "T2", True, False, True, False),
            (1.4999, "T2", True, False, True, False),
            (1.50, "T3", True, False, True, False),
            (1.5001, "T3", False, True, True, False),
            (2.7999, "T3", False, True, True, False),
            (2.80, "T4", False, True, False, False),
            (3.50, "T4", False, True, False, False),
        ]
        for (
            d_min,
            expected_id,
            expected_cbeta_forced,
            expected_aniso_demoted,
            expected_sol_eligible,
            expected_sub_0p90,
        ) in cases:
            with self.subTest(d_min=d_min):
                tier = p2.resolution_tier(d_min)
                self.assertEqual(tier, expected_id)
                self.assertEqual(tier.tier_id, expected_id)
                self.assertEqual(tier["tier_id"], expected_id)
                self.assertAlmostEqual(tier.d_min, float(d_min))
                self.assertEqual(
                    tier.c_beta_forced_false_by_native_preprocess,
                    expected_cbeta_forced,
                )
                self.assertEqual(
                    tier.unrequested_aniso_demoted_by_native_preprocess,
                    expected_aniso_demoted,
                )
                self.assertEqual(
                    tier.ordered_solvent_native_eligible,
                    expected_sol_eligible,
                )
                self.assertEqual(
                    tier.sub_0p90_water_adp_unresolved,
                    expected_sub_0p90,
                )

    def test_rejects_invalid_d_min_values(self) -> None:
        invalid_values = [
            True,
            False,
            None,
            "1.5",
            0,
            0.0,
            -0.001,
            -2.0,
            math.nan,
            math.inf,
            -math.inf,
            [1.5],
            {"d_min": 1.5},
        ]
        for bad in invalid_values:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    p2.resolution_tier(bad)  # type: ignore[arg-type]

    def test_copy_deepcopy_and_json_roundtrip(self) -> None:
        tier = p2.resolution_tier(1.25)
        shallow = copy.copy(tier)
        deep = copy.deepcopy(tier)
        unpickled = pickle.loads(pickle.dumps(tier))

        self.assertIsNot(tier, shallow)
        self.assertIsNot(tier, deep)
        self.assertEqual(tier.to_dict(), shallow.to_dict())
        self.assertEqual(tier.to_dict(), deep.to_dict())
        self.assertEqual(tier.to_dict(), unpickled.to_dict())

        # Mutating an attribute on the deep copy must not affect the original
        deep.label = "modified-label"
        self.assertNotEqual(tier.label, deep.label)

        prof = p2.fixed_profile(1.25, "Arm 3b-refine-only")
        prof_copy = copy.deepcopy(prof)
        self.assertIsNot(prof["tier"], prof_copy["tier"])
        self.assertEqual(prof["tier"].to_dict(), prof_copy["tier"].to_dict())

        # JSON roundtrip preserves profile meaning and renders identically
        roundtripped = json.loads(json.dumps(prof))
        self.assertEqual(roundtripped["tier"], "T2")
        self.assertEqual(roundtripped["tier_id"], "T2")
        bindings = {
            "adp_anisotropic_selection": "not water and not element H",
            "adp_isotropic_selection": "water",
        }
        self.assertEqual(
            str(p2.render_eff(prof, bindings)),
            str(p2.render_eff(roundtripped, bindings)),
        )


class TestFixedProfile(unittest.TestCase):
    """Verify Arm 3b-refine-only vs Arm 3b-plus-readyset and tier-specific contracts."""

    def test_arm_distinction_and_locked_defaults(self) -> None:
        p_refine_only = p2.fixed_profile(1.20, "Arm 3b-refine-only")
        p_plus_rs = p2.fixed_profile(1.20, "Arm 3b-plus-readyset")

        self.assertEqual(p_refine_only["registration_status"], "selected_decisions_recorded")
        self.assertFalse(p_refine_only["development_frozen"])
        self.assertFalse(p_refine_only["preprocessing"]["enabled"])
        self.assertIsNone(p_refine_only["preprocessing"]["program"])
        self.assertEqual(p_refine_only["preprocessing"]["phil_assignments"], {})

        self.assertTrue(p_plus_rs["preprocessing"]["enabled"])
        self.assertEqual(p_plus_rs["preprocessing"]["program"], "phenix.ready_set")
        self.assertEqual(
            p_plus_rs["preprocessing"]["phil_assignments"],
            {
                "ready_set.actions.hydrogens": True,
                "ready_set.actions.ligands": True,
            },
        )

        for prof in (p_refine_only, p_plus_rs):
            self.assertEqual(prof["macro_cycles"], 5)
            self.assertEqual(prof["hydrogens_refine"], "riding")
            self.assertEqual(
                prof["cdl_phil_path"],
                "refinement.pdb_interpretation.restraints_library.cdl",
            )
            self.assertTrue(prof["cdl_enabled"])
            self.assertEqual(
                prof["known_refine_phil"]["refinement.main.number_of_macro_cycles"], 5
            )
            self.assertEqual(
                prof["known_refine_phil"]["refinement.hydrogens.refine"], "riding"
            )
            self.assertTrue(
                prof["known_refine_phil"][
                    "refinement.pdb_interpretation.restraints_library.cdl"
                ]
            )
            self.assertIn("preprocess.py:483-508", prof["dormant_source_block_untouched"])

    def test_t1_sub_0p90_vs_0p90_to_1p50_water_policy(self) -> None:
        p_ultra = p2.fixed_profile(0.82, "Arm 3b-refine-only")
        self.assertEqual(p_ultra["tier_id"], "T1")
        self.assertEqual(p_ultra["water_adp_policy"], "unresolved_dev_test_below_0.90A")
        self.assertIn("sub_0p90_water_adp_mode", p_ultra["required_bindings"])
        self.assertIn("sub_0p90_water_selection_audit", p_ultra["required_bindings"])
        self.assertIn("adp_anisotropic_selection", p_ultra["required_bindings"])
        self.assertIn("adp_isotropic_selection", p_ultra["required_bindings"])
        self.assertTrue(p_ultra["ordered_solvent"])
        self.assertTrue(
            p_ultra["known_refine_phil"]["refinement.target_weights.optimize_xyz_weight"]
        )
        self.assertTrue(
            p_ultra["known_refine_phil"]["refinement.target_weights.optimize_adp_weight"]
        )

        p_t1_hi = p2.fixed_profile(0.95, "Arm 3b-refine-only")
        self.assertEqual(p_t1_hi["tier_id"], "T1")
        self.assertEqual(p_t1_hi["water_adp_policy"], "isotropic_in_0.90_to_1.50A")
        self.assertNotIn("sub_0p90_water_adp_mode", p_t1_hi["required_bindings"])
        self.assertNotIn("sub_0p90_water_selection_audit", p_t1_hi["required_bindings"])

        p_t2 = p2.fixed_profile(1.35, "Arm 3b-refine-only")
        self.assertEqual(p_t2["tier_id"], "T2")
        self.assertEqual(p_t2["water_adp_policy"], "isotropic_in_0.90_to_1.50A")
        self.assertNotIn("sub_0p90_water_adp_mode", p_t2["required_bindings"])
        self.assertNotIn("sub_0p90_water_selection_audit", p_t2["required_bindings"])

    def test_t3_and_t4_fixed_profiles(self) -> None:
        p_t3 = p2.fixed_profile(2.00, "Arm 3b-refine-only")
        self.assertEqual(p_t3["tier_id"], "T3")
        self.assertEqual(p_t3["adp_tls_architecture"], "iso+tls")
        self.assertTrue(p_t3["ordered_solvent"])
        self.assertTrue(
            p_t3["known_refine_phil"]["refinement.target_weights.optimize_xyz_weight"]
        )
        self.assertTrue(
            p_t3["known_refine_phil"]["refinement.target_weights.optimize_adp_weight"]
        )
        self.assertEqual(
            set(p_t3["required_bindings"].keys()),
            {"adp_isotropic_selection", "tls_group_selections", "refine_strategy"},
        )

        p_t4 = p2.fixed_profile(3.10, "Arm 3b-plus-readyset")
        self.assertEqual(p_t4["tier_id"], "T4")
        self.assertEqual(p_t4["adp_tls_architecture"], "iso/group+tls")
        self.assertFalse(p_t4["ordered_solvent"])
        self.assertFalse(p_t4["known_refine_phil"]["refinement.main.ordered_solvent"])
        self.assertEqual(
            p_t4["low_res_restraints_policy"],
            {"torsion_ncs": True, "secondary_structure": True, "rotamer": True},
        )
        self.assertEqual(
            p_t4["weight_optimization_policy"],
            "unresolved_in_u04_for_t4_fixed_profile",
        )
        self.assertNotIn(
            "refinement.target_weights.optimize_xyz_weight", p_t4["known_refine_phil"]
        )
        self.assertNotIn(
            "refinement.target_weights.optimize_adp_weight", p_t4["known_refine_phil"]
        )
        self.assertIn("t4_weight_optimization_policy", p_t4["required_bindings"])
        self.assertNotIn("s4_torsion_ncs_phil_path", p_t4["required_bindings"])
        self.assertNotIn("s4_secondary_structure_phil_path", p_t4["required_bindings"])
        self.assertNotIn("s4_rotamer_phil_path", p_t4["required_bindings"])
        self.assertTrue(
            p_t4["known_refine_phil"]["refinement.pdb_interpretation.ncs_search.enabled"]
        )
        self.assertEqual(p_t4["known_refine_phil"]["refinement.ncs.type"], "torsion")
        self.assertTrue(
            p_t4["known_refine_phil"][
                "refinement.pdb_interpretation.secondary_structure.enabled"
            ]
        )
        self.assertTrue(p_t4["known_refine_phil"]["refinement.main.rotamer_restraints"])

    def test_rejects_unknown_arm(self) -> None:
        with self.assertRaises(ValueError):
            p2.fixed_profile(1.50, "Arm 3a")
        with self.assertRaises(ValueError):
            p2.fixed_profile(1.50, 123)  # type: ignore[arg-type]


class TestFactorialCells(unittest.TestCase):
    """Verify crossed factorial cell counts, pruning rules, and weight-optimization flags."""

    def test_cell_counts_and_uniqueness_across_tiers(self) -> None:
        for d_min, expected_tier, expected_count in (
            (0.95, "T1", 16),
            (1.25, "T2", 16),
            (1.50, "T3", 16),
            (2.20, "T3", 16),
            (2.80, "T4", 8),
            (3.40, "T4", 8),
        ):
            with self.subTest(d_min=d_min):
                cells = p2.factorial_cells(d_min)
                self.assertEqual(len(cells), expected_count)
                cell_ids = [c["cell_id"] for c in cells]
                self.assertEqual(len(set(cell_ids)), expected_count)
                factor_tuples = [
                    (
                        c["factors"]["ready_set_h"],
                        c["factors"]["ordered_solvent"],
                        c["factors"]["adp_tls_mode"],
                        c["factors"]["optimize_weights"],
                    )
                    for c in cells
                ]
                self.assertEqual(len(set(factor_tuples)), expected_count)
                for cell in cells:
                    self.assertEqual(cell["tier_id"], expected_tier)
                    self.assertFalse(cell["r_free_selection_permitted"])
                    self.assertFalse(cell["r_sleep_selection_permitted"])
                    self.assertFalse(cell["adp_tls_level_resolved"])
                    self.assertIn("adp_tls_level_binding", cell["required_bindings"])
                    self.assertIn("shared_ligand_cifs", cell["required_bindings"])

    def test_t4_ordered_solvent_pruning_and_aniso_demotion_contract(self) -> None:
        t4_cells = p2.factorial_cells(2.80)
        self.assertEqual(len(t4_cells), 8)
        for cell in t4_cells:
            self.assertEqual(cell["factors"]["ordered_solvent"], "sol_off")
            self.assertEqual(cell["pruned_solvent_levels"], ("sol_on",))
            self.assertFalse(cell["known_refine_phil"]["refinement.main.ordered_solvent"])
            contract = cell["aniso_demotion_contract"]
            self.assertTrue(contract["unrequested_aniso_macromol_forbidden"])
            self.assertTrue(contract["explicit_anisotropic_selection_exception"])
            self.assertFalse(contract["silent_native_anisotropic_promotion"])

        t3_at_1p50 = p2.factorial_cells(1.50)
        self.assertFalse(
            t3_at_1p50[0]["aniso_demotion_contract"]["unrequested_aniso_macromol_forbidden"]
        )
        t3_at_1p55 = p2.factorial_cells(1.55)
        self.assertTrue(
            t3_at_1p55[0]["aniso_demotion_contract"]["unrequested_aniso_macromol_forbidden"]
        )

    def test_weight_optimization_and_pure_h_factor_flags(self) -> None:
        cells = p2.factorial_cells(1.80)
        for cell in cells:
            phil = cell["known_refine_phil"]
            if cell["factors"]["optimize_weights"] == "wt_opt":
                self.assertTrue(phil["refinement.target_weights.optimize_xyz_weight"])
                self.assertTrue(phil["refinement.target_weights.optimize_adp_weight"])
                self.assertTrue(phil["refinement.target_weights.force_optimize_weights"])
            else:
                self.assertFalse(phil["refinement.target_weights.optimize_xyz_weight"])
                self.assertFalse(phil["refinement.target_weights.optimize_adp_weight"])
                self.assertFalse(phil["refinement.target_weights.force_optimize_weights"])

            if cell["factors"]["ready_set_h"] == "H_riding":
                self.assertTrue(cell["preprocessing"]["enabled"])
                self.assertEqual(
                    cell["preprocessing"]["phil_assignments"],
                    {
                        "ready_set.actions.hydrogens": True,
                        "ready_set.actions.ligands": False,
                    },
                )
                self.assertEqual(phil["refinement.hydrogens.refine"], "riding")
                self.assertIn("hd_free_start_model_sha256", cell["required_bindings"])
                self.assertIn("hd_audit_receipt", cell["required_bindings"])
            else:
                self.assertFalse(cell["preprocessing"]["enabled"])
                self.assertEqual(cell["preprocessing"]["phil_assignments"], {})
                self.assertIn("hd_free_start_model_sha256", cell["required_bindings"])
                self.assertIn("hd_audit_receipt", cell["required_bindings"])


class TestPureHContract(unittest.TestCase):
    """Verify pure-H isolation contract (#1240, #1334) and ligand CIF validation."""

    def test_valid_pure_h_contract(self) -> None:
        cifs = [
            {"path": "restraints/ligA.cif", "sha256": SHA_A},
            ("restraints/sub/ligB.cif", SHA_B),
        ]
        contract = p2.pure_h_contract(
            cifs,
            hd_free_start_model_sha256=SHA_HD_FREE,
            hd_audit_receipt=VALID_HD_RECEIPT,
        )
        self.assertFalse(contract["executed"])
        self.assertEqual(len(contract["shared_ligand_cifs"]), 2)
        self.assertEqual(
            contract["levels"]["H_off"]["shared_ligand_cifs"],
            contract["levels"]["H_riding"]["shared_ligand_cifs"],
        )
        self.assertEqual(
            contract["levels"]["H_off"]["declared_common_start"],
            contract["levels"]["H_riding"]["declared_common_start"],
        )

        h_off = contract["levels"]["H_off"]
        self.assertFalse(h_off["executed"])
        self.assertFalse(h_off["ready_set_planned"])
        self.assertNotIn("ready_set_executed", h_off)
        self.assertTrue(h_off["requires_proven_hd_free_common_start"])
        self.assertTrue(h_off["requires_declared_common_start_sha256"])
        self.assertTrue(h_off["requires_declared_hd_audit_receipt"])
        self.assertFalse(h_off["bare_hash_alone_sufficient"])
        self.assertFalse(h_off["omitted_ready_set_alone_sufficient"])

        h_riding = contract["levels"]["H_riding"]
        self.assertFalse(h_riding["executed"])
        self.assertTrue(h_riding["ready_set_planned"])
        self.assertNotIn("ready_set_executed", h_riding)
        self.assertTrue(h_riding["requires_proven_hd_free_common_start"])
        self.assertTrue(h_riding["requires_declared_common_start_sha256"])
        self.assertTrue(h_riding["requires_declared_hd_audit_receipt"])
        self.assertFalse(h_riding["bare_hash_alone_sufficient"])
        self.assertEqual(
            h_riding["ready_set_phil"],
            {
                "ready_set.actions.hydrogens": True,
                "ready_set.actions.ligands": False,
            },
        )
        self.assertEqual(
            h_riding["refine_phil"],
            {"refinement.hydrogens.refine": "riding"},
        )
        self.assertFalse(
            contract["arm3b_plus_readyset_combined_reservation"]["used_in_pure_h_factorial"]
        )

        # Walk nested contract and ensure no '*executed*' field is True anywhere
        def _assert_no_executed_true(node: object) -> None:
            if isinstance(node, dict):
                for k, v in node.items():
                    if "executed" in str(k):
                        self.assertIs(v, False)
                    _assert_no_executed_true(v)
            elif isinstance(node, (list, tuple)):
                for item in node:
                    _assert_no_executed_true(item)

        _assert_no_executed_true(contract)

    def test_rejects_invalid_shared_ligand_cifs(self) -> None:
        bad_inputs = [
            "restraints/ligA.cif",
            [{"path": "/abs/path/ligA.cif", "sha256": SHA_A}],
            [{"path": "../escape/ligA.cif", "sha256": SHA_A}],
            [{"path": "Users/someone/ligA.cif", "sha256": SHA_A}],
            [{"path": "restraints/ligA.pdb", "sha256": SHA_A}],
            [{"path": "restraints/lig A.cif", "sha256": SHA_A}],
            [{"path": "restraints/ligA.cif", "sha256": "not-a-sha256"}],
            [{"path": "restraints/ligA.cif", "sha256": "a" * 63}],
            [{"path": "restraints/ligA.cif", "sha256": "a" * 65}],
            [{"path": "restraints/ligA.cif", "sha256": "g" * 64}],
            [{"path": "restraints/ligA.cif", "sha256": "A" * 64}],
            [{"path": "restraints/ligA.cif", "sha256": SHA_A + "\n"}],
            [{"path": "restraints/ligA.cif", "sha256": SHA_A + "\r\n"}],
            [{"path": "restraints/ligA.cif", "sha256": SHA_A + " "}],
            [{"path": "restraints/ligA.cif", "sha256": " " + SHA_A}],
            [{"path": "restraints/ligA.cif", "sha256": True}],
            [{"path": "restraints/ligA.cif", "sha256": 123}],
            [{"path": "restraints/ligA.cif", "sha256": None}],
            [
                {"path": "restraints/ligA.cif", "sha256": SHA_A},
                {"path": "restraints/ligA.cif", "sha256": SHA_B},
            ],
            [
                {"path": "restraints/ligA.cif", "sha256": SHA_A},
                {"path": "restraints/ligB.cif", "sha256": SHA_A},
            ],
        ]
        for bad in bad_inputs:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    p2.pure_h_contract(bad)  # type: ignore[arg-type]

        # Also verify hd_free_start_model_sha256 rejects trailing LF/CRLF/non-string
        t3_cell = p2.factorial_cells(1.80)[0]
        for bad_sha in (SHA_HD_FREE + "\n", SHA_HD_FREE + "\r\n", SHA_HD_FREE + " ", True):
            with self.subTest(bad_hd_free_sha=bad_sha):
                with self.assertRaises(ValueError):
                    p2.render_eff(
                        t3_cell,
                        {
                            "adp_tls_level_binding": {
                                "level_id": t3_cell["factors"]["adp_tls_mode"],
                                "common_non_adp_strategy": ["individual_sites"],
                                "refine_strategy": ["individual_sites", "individual_adp", "tls"],
                                "adp_isotropic_selection": "all",
                                "tls_group_selections": ["chain A"],
                            },
                            "shared_ligand_cifs": [],
                            "hd_free_start_model_sha256": bad_sha,
                            "hd_audit_receipt": VALID_HD_RECEIPT,
                        },
                    )


class TestSensitivityCells(unittest.TestCase):
    """Verify one-factor S1-S4 sensitivity schedules and boundary conditions."""

    def test_s1_inclusive_1p50_to_1p70_boundary(self) -> None:
        for d_min, exp_contrast, exp_gt_limits in (
            (1.50, False, [False, False]),
            (1.60, True, [True, False]),
            (1.70, True, [True, False]),
        ):
            with self.subTest(included_d_min=d_min):
                cells = p2.sensitivity_cells(d_min)
                s1 = [c for c in cells if c["arm_family"] == "S1"]
                self.assertEqual(len(s1), 2)
                self.assertEqual([c["factor_level"] for c in s1], [1.5, 1.7])
                self.assertEqual(
                    [c["native_demotion_strict_gt_switch_limit"] for c in s1],
                    exp_gt_limits,
                )
                for c in s1:
                    self.assertEqual(
                        c["factor_name"],
                        "refinement.main.switch_to_isotropic_high_res_limit",
                    )
                    self.assertEqual(c["s1_binding_mode"], "preserve_input_adp")
                    self.assertIs(c["expected_static_switch_contrast"], exp_contrast)
                    self.assertIs(c["native_demotion_strict_gt_1p5"], exp_contrast)
                    self.assertTrue(c["one_factor"])
                    self.assertFalse(c["interaction_claims_permitted"])

        for d_min in (1.05, 1.4999, 1.7001, 2.20, 2.80):
            with self.subTest(excluded_d_min=d_min):
                cells = p2.sensitivity_cells(d_min)
                s1 = [c for c in cells if c["arm_family"] == "S1"]
                self.assertEqual(s1, [])

    def test_s2_and_s3_separate_one_factor_comparisons(self) -> None:
        cells_le_1p5 = p2.sensitivity_cells(1.50)
        s2 = [c for c in cells_le_1p5 if c["arm_family"] == "S2"]
        self.assertEqual(len(s2), 2)
        self.assertEqual([c["factor_level"] for c in s2], [True, False])

        s3 = [c for c in cells_le_1p5 if c["arm_family"] == "S3"]
        self.assertEqual(len(s3), 4)
        s3_cbeta = [c for c in s3 if c["comparison_group"] == "S3_c_beta_restraints"]
        s3_nb = [c for c in s3 if c["comparison_group"] == "S3_nonbonded_weight"]
        self.assertEqual(len(s3_cbeta), 2)
        self.assertEqual(len(s3_nb), 2)
        for c in s3_cbeta:
            self.assertFalse(c["crossed_with_nonbonded_weight"])
            self.assertTrue(c["c_beta_forced_false_by_native_preprocess"])
            self.assertFalse(c["effective_native_c_beta_restraints"])
        for c in s3_nb:
            self.assertFalse(c["crossed_with_c_beta_restraints"])
            self.assertIn(c["factor_level"], (100, 16))

        cells_gt_1p5 = p2.sensitivity_cells(1.85)
        s3_cbeta_gt = [
            c
            for c in cells_gt_1p5
            if c["arm_family"] == "S3" and c["comparison_group"] == "S3_c_beta_restraints"
        ]
        self.assertTrue(s3_cbeta_gt[0]["factor_level"])
        self.assertFalse(s3_cbeta_gt[0]["c_beta_forced_false_by_d_min_le_1p5"])
        self.assertIsNone(s3_cbeta_gt[0]["c_beta_forced_false_by_native_preprocess"])
        self.assertIsNone(s3_cbeta_gt[0]["effective_native_c_beta_restraints"])
        self.assertIsNone(s3_cbeta_gt[0]["static_effective_c_beta_restraints"])
        self.assertEqual(
            s3_cbeta_gt[0]["c_beta_prediction_status"],
            "conditional_unassessed_until_strategy_bound",
        )
        self.assertEqual(
            s3_cbeta_gt[0]["c_beta_prediction_basis"],
            "static_source_predicate_not_runtime_measured",
        )
        self.assertFalse(s3_cbeta_gt[1]["factor_level"])
        self.assertIs(s3_cbeta_gt[1]["c_beta_forced_false_by_native_preprocess"], False)
        self.assertIs(s3_cbeta_gt[1]["effective_native_c_beta_restraints"], False)
        self.assertEqual(
            s3_cbeta_gt[1]["c_beta_prediction_status"],
            "static_source_derived_disabled_by_request",
        )

        # #1333: Static C-beta prediction covers individual_sites, individual_sites_real_space,
        # ADP-only, rigid_body-only, exact 1.50, disabled request, and missing strategy
        pred_sites = p2.predict_static_c_beta_restraints(
            2.0, True, ["individual_sites", "individual_adp"]
        )
        self.assertIs(pred_sites["static_effective_c_beta_restraints"], True)
        self.assertEqual(
            pred_sites["prediction_status"],
            "static_source_derived_enabled_with_coordinate_strategy",
        )
        self.assertFalse(pred_sites["runtime_measured"])

        pred_real_space = p2.predict_static_c_beta_restraints(
            2.0, True, ["individual_sites_real_space", "individual_adp"]
        )
        self.assertIs(pred_real_space["static_effective_c_beta_restraints"], True)
        self.assertEqual(
            pred_real_space["prediction_status"],
            "static_source_derived_enabled_with_coordinate_strategy",
        )

        pred_adp_only = p2.predict_static_c_beta_restraints(
            2.0, True, ["individual_adp"]
        )
        self.assertIs(pred_adp_only["static_effective_c_beta_restraints"], False)
        self.assertEqual(
            pred_adp_only["prediction_status"],
            "static_source_derived_forced_false_no_coordinate_strategy",
        )

        pred_rigid_only = p2.predict_static_c_beta_restraints(
            2.0, True, ["rigid_body", "individual_adp"]
        )
        self.assertIs(pred_rigid_only["static_effective_c_beta_restraints"], False)
        self.assertEqual(
            pred_rigid_only["prediction_status"],
            "static_source_derived_forced_false_no_coordinate_strategy",
        )

        pred_exact_1p50 = p2.predict_static_c_beta_restraints(
            1.50, True, ["individual_sites", "individual_adp"]
        )
        self.assertIs(pred_exact_1p50["static_effective_c_beta_restraints"], False)
        self.assertEqual(
            pred_exact_1p50["prediction_status"],
            "static_source_derived_forced_false_le_1p50",
        )

        pred_disabled = p2.predict_static_c_beta_restraints(
            2.0, False, ["individual_sites", "individual_adp"]
        )
        self.assertIs(pred_disabled["static_effective_c_beta_restraints"], False)
        self.assertEqual(
            pred_disabled["prediction_status"],
            "static_source_derived_disabled_by_request",
        )

        pred_missing_strat = p2.predict_static_c_beta_restraints(2.0, True, None)
        self.assertIsNone(pred_missing_strat["static_effective_c_beta_restraints"])
        self.assertEqual(
            pred_missing_strat["prediction_status"],
            "conditional_unassessed_until_strategy_bound",
        )

        # Rendering S3 c_beta_restraints=True at d_min=2.0 with ADP-only vs individual_sites
        s3_2p0_true = [
            c
            for c in p2.sensitivity_cells(2.0)
            if c["comparison_group"] == "S3_c_beta_restraints" and c["factor_level"] is True
        ][0]
        eff_adp_only = p2.render_eff(
            s3_2p0_true,
            {
                "adp_tls_level_binding": {
                    "refine_strategy": ["individual_adp"],
                    "adp_isotropic_selection": "all",
                }
            },
        )
        self.assertIn(
            "# s3_c_beta_static_prediction: requested=True | static_effective=False | "
            "status=static_source_derived_forced_false_no_coordinate_strategy",
            eff_adp_only.refine_eff,
        )

        eff_with_sites = p2.render_eff(
            s3_2p0_true,
            {
                "adp_tls_level_binding": {
                    "common_non_adp_strategy": ["individual_sites"],
                    "refine_strategy": ["individual_sites", "individual_adp"],
                    "adp_isotropic_selection": "all",
                }
            },
        )
        self.assertIn(
            "# s3_c_beta_static_prediction: requested=True | static_effective=True | "
            "status=static_source_derived_enabled_with_coordinate_strategy",
            eff_with_sites.refine_eff,
        )

    def test_s4_only_in_t4_and_locks_source_verified_restraint_paths(self) -> None:
        for d_min in (0.95, 1.30, 2.00):
            s4_non_t4 = [c for c in p2.sensitivity_cells(d_min) if c["arm_family"] == "S4"]
            self.assertEqual(s4_non_t4, [])

        t4_cells = p2.sensitivity_cells(2.95)
        s4 = [c for c in t4_cells if c["arm_family"] == "S4"]
        self.assertEqual(len(s4), 4)
        self.assertEqual(
            [c["factor_level"] for c in s4],
            ["all_on", "torsion_ncs_off", "secondary_structure_off", "rotamer_off"],
        )
        expected_switches = {
            "all_on": (True, True, True),
            "torsion_ncs_off": (False, True, True),
            "secondary_structure_off": (True, False, True),
            "rotamer_off": (True, True, False),
        }
        for c in s4:
            self.assertTrue(c["one_factor"])
            self.assertFalse(c["interaction_claims_permitted"])
            self.assertNotIn("s4_torsion_ncs_phil_path", c["required_bindings"])
            self.assertNotIn("s4_secondary_structure_phil_path", c["required_bindings"])
            self.assertNotIn("s4_rotamer_phil_path", c["required_bindings"])
            phil = c["known_refine_phil"]
            exp_ncs, exp_ss, exp_rot = expected_switches[c["factor_level"]]
            self.assertIs(
                phil["refinement.pdb_interpretation.ncs_search.enabled"], exp_ncs
            )
            self.assertEqual(phil["refinement.ncs.type"], "torsion")
            self.assertIs(
                phil["refinement.pdb_interpretation.secondary_structure.enabled"], exp_ss
            )
            self.assertIs(phil["refinement.main.rotamer_restraints"], exp_rot)
            self.assertIn("Unassessed", c["effective_behavior_note"])


class TestRenderEffAndTemplates(unittest.TestCase):
    """Verify fail-closed .eff rendering, template comments, and scope separation."""

    def test_render_known_eff_template_marks_incomplete(self) -> None:
        prof = p2.fixed_profile(0.85, "Arm 3b-plus-readyset")
        bundle = p2.render_known_eff_template(prof)
        self.assertFalse(bundle.is_complete)
        self.assertIsNotNone(bundle.ready_set_eff)
        self.assertIn("# [SCOPE: phenix.ready_set]", bundle.ready_set_eff or "")
        self.assertIn("ready_set.actions.hydrogens = True", bundle.ready_set_eff or "")
        self.assertIn("ready_set.actions.ligands = True", bundle.ready_set_eff or "")
        self.assertIn("# [SCOPE: phenix.refine]", bundle.refine_eff)
        self.assertIn(
            "# UNRESOLVED_REQUIRED_BINDING: sub_0p90_water_adp_mode", bundle.refine_eff
        )
        self.assertIn(
            "# UNRESOLVED_REQUIRED_BINDING: sub_0p90_water_selection_audit",
            bundle.refine_eff,
        )
        self.assertIn(
            "refinement.pdb_interpretation.restraints_library.cdl = True",
            bundle.refine_eff,
        )

    def test_render_eff_fails_closed_on_missing_or_extra_or_invalid_bindings(self) -> None:
        prof_t2 = p2.fixed_profile(1.25, "Arm 3b-refine-only")

        # Missing bindings
        with self.assertRaises(ValueError):
            p2.render_eff(prof_t2, None)
        with self.assertRaises(ValueError):
            p2.render_eff(prof_t2, {"adp_anisotropic_selection": "not water and not element H"})

        # Extra override key
        with self.assertRaises(ValueError):
            p2.render_eff(
                prof_t2,
                {
                    "adp_anisotropic_selection": "not water and not element H",
                    "adp_isotropic_selection": "water",
                    "refinement.main.number_of_macro_cycles": 10,
                },
            )

        # Symbolic placeholder string rejected
        for placeholder in (
            "unresolved",
            "TBD",
            "auto",
            "T2_adp_tls_level_a_unresolved",
            "water\nrefinement.main.ordered_solvent = False",
            'water "quoted"',
            "water; extra_stmt",
            "water # comment",
            "water { group }",
        ):
            with self.subTest(placeholder=placeholder):
                with self.assertRaises(ValueError):
                    p2.render_eff(
                        prof_t2,
                        {
                            "adp_anisotropic_selection": "not water and not element H",
                            "adp_isotropic_selection": placeholder,
                        },
                    )

        # Bool passed where int/float expected or int passed where bool expected in spec
        corrupted_bool_as_int = copy.deepcopy(prof_t2)
        corrupted_bool_as_int["known_refine_phil"][
            "refinement.main.number_of_macro_cycles"
        ] = True
        with self.assertRaises(ValueError):
            p2.render_eff(
                corrupted_bool_as_int,
                {
                    "adp_anisotropic_selection": "not water and not element H",
                    "adp_isotropic_selection": "water",
                },
            )

        corrupted_int_as_bool = copy.deepcopy(prof_t2)
        corrupted_int_as_bool["known_refine_phil"]["refinement.main.ordered_solvent"] = 1
        with self.assertRaises(ValueError):
            p2.render_eff(
                corrupted_int_as_bool,
                {
                    "adp_anisotropic_selection": "not water and not element H",
                    "adp_isotropic_selection": "water",
                },
            )

    def test_canonical_policy_guard_rejects_mutated_specs(self) -> None:
        base_prof = p2.fixed_profile(1.20, "3b-refine-only")
        valid_bindings = {
            "adp_anisotropic_selection": "protein and not element H",
            "adp_isotropic_selection": "water",
        }

        mutations: list[tuple[str, dict[str, object]]] = []

        m_cycles = copy.deepcopy(base_prof)
        m_cycles["known_refine_phil"]["refinement.main.number_of_macro_cycles"] = 99
        mutations.append(("macro_cycles_99", m_cycles))

        m_added_phil = copy.deepcopy(base_prof)
        m_added_phil["known_refine_phil"]["refinement.main.simulated_annealing"] = True
        mutations.append(("added_simulated_annealing", m_added_phil))

        m_dropped_req = copy.deepcopy(base_prof)
        m_dropped_req["required_bindings"].pop("adp_isotropic_selection")
        mutations.append(("dropped_required_binding", m_dropped_req))

        m_mut_solvent = copy.deepcopy(base_prof)
        m_mut_solvent["ordered_solvent"] = False
        m_mut_solvent["known_refine_phil"]["refinement.main.ordered_solvent"] = False
        mutations.append(("mutated_ordered_solvent", m_mut_solvent))

        m_mut_cdl = copy.deepcopy(base_prof)
        m_mut_cdl["known_refine_phil"][
            "refinement.pdb_interpretation.restraints_library.cdl"
        ] = False
        mutations.append(("mutated_cdl", m_mut_cdl))

        m_mut_prep = copy.deepcopy(base_prof)
        m_mut_prep["preprocessing"]["enabled"] = True
        mutations.append(("mutated_prep_enabled", m_mut_prep))

        m_extra_key = copy.deepcopy(base_prof)
        m_extra_key["extra_policy_override"] = "injected"
        mutations.append(("extra_top_level_key", m_extra_key))

        m_malicious_key = copy.deepcopy(base_prof)
        m_malicious_key["known_refine_phil"][
            "refinement.main.ordered_solvent\nrefinement.main.simulated_annealing"
        ] = True
        mutations.append(("malicious_phil_key", m_malicious_key))

        m_tier_id = copy.deepcopy(base_prof)
        m_tier_id["tier_id"] = "T1\ninjected"
        mutations.append(("mutated_tier_id", m_tier_id))

        m_tier_meta = copy.deepcopy(base_prof)
        m_tier_meta["tier"].label = "tampered"
        mutations.append(("mutated_tier_metadata", m_tier_meta))

        m_nonfinite = copy.deepcopy(base_prof)
        m_nonfinite["known_refine_phil"]["refinement.main.number_of_macro_cycles"] = math.nan
        mutations.append(("nonfinite_phil_value", m_nonfinite))

        fact_cell = copy.deepcopy(p2.factorial_cells(1.20)[0])
        fact_cell["cell_id"] = "T2__H_off__sol_off__bad_level__wt_fixed"
        mutations.append(("bad_factorial_cell_id", fact_cell))

        sens_cell = copy.deepcopy(p2.sensitivity_cells(1.60)[0])
        sens_cell["cell_id"] = "S1__T3__unknown_cell"
        mutations.append(("bad_sensitivity_cell_id", sens_cell))

        for label, mutated_spec in mutations:
            with self.subTest(mutation=label):
                with self.assertRaises(ValueError):
                    p2.render_known_eff_template(mutated_spec)
                with self.assertRaises(ValueError):
                    p2.render_eff(mutated_spec, valid_bindings)

        # JSON roundtrip succeeds on fixed_profile, factorial_cell, and sensitivity_cell
        for raw_spec in (
            base_prof,
            p2.factorial_cells(1.20)[0],
            p2.sensitivity_cells(1.60)[0],
        ):
            rt_spec = json.loads(json.dumps(raw_spec, allow_nan=False))
            self.assertEqual(
                str(p2.render_known_eff_template(raw_spec)),
                str(p2.render_known_eff_template(rt_spec)),
            )

    def test_render_eff_complete_for_fixed_factorial_and_s4_specs(self) -> None:
        # T1 (< 0.90 A) fixed profile with Arm 3b-plus-readyset
        prof_t1 = p2.fixed_profile(0.85, "Arm 3b-plus-readyset")
        rendered_t1 = p2.render_eff(
            prof_t1,
            {
                "sub_0p90_water_adp_mode": "anisotropic",
                "adp_anisotropic_selection": "not element H",
                "adp_isotropic_selection": "element H",
                "sub_0p90_water_selection_audit": {
                    "refinement_input_model_sha256": SHA_A,
                    "audit_receipt_sha256": SHA_B,
                    "adp_isotropic_selection": "element H",
                    "adp_anisotropic_selection": "not element H",
                    "total": 140,
                    "isotropic": 0,
                    "anisotropic": 140,
                    "neither": 0,
                    "both": 0,
                },
            },
        )
        self.assertTrue(rendered_t1.is_complete)
        self.assertIsNotNone(rendered_t1.ready_set_eff)
        self.assertIn(
            'refinement.refine.adp.individual.anisotropic = "not element H"',
            rendered_t1.refine_eff,
        )

        # T3 factorial cell (H_off)
        t3_cell = p2.factorial_cells(1.80)[0]
        rendered_cell = p2.render_eff(
            t3_cell,
            {
                "adp_tls_level_binding": {
                    "level_id": t3_cell["factors"]["adp_tls_mode"],
                    "common_non_adp_strategy": ["individual_sites"],
                    "refine_strategy": ["individual_sites", "individual_adp", "tls"],
                    "adp_isotropic_selection": "all",
                    "tls_group_selections": ["chain A", "chain B"],
                },
                "shared_ligand_cifs": [{"path": "restraints/ligA.cif", "sha256": SHA_A}],
                "hd_free_start_model_sha256": SHA_HD_FREE,
                "hd_audit_receipt": VALID_HD_RECEIPT,
            },
        )
        self.assertTrue(rendered_cell.is_complete)
        self.assertIsNone(rendered_cell.ready_set_eff)
        self.assertIn(
            "refinement.refine.strategy = individual_sites+individual_adp+tls",
            rendered_cell.refine_eff,
        )
        self.assertIn(
            'refinement.input.monomers.file_name = "restraints/ligA.cif"',
            rendered_cell.refine_eff,
        )
        self.assertNotIn("verified H/D-free input", rendered_cell.refine_eff)
        self.assertIn(
            "(declared common starting-model binding; not runtime-verified from hash alone)",
            rendered_cell.refine_eff,
        )
        self.assertIn(
            "(declared evidence-bound receipt contract; coordinate bytes not inspected by spec compiler)",
            rendered_cell.refine_eff,
        )

        # #1327: Rejects unrequested_aniso_macromol=True at d_min > 1.50 A,
        # while allowing explicit adp_anisotropic_selection with individual_adp
        with self.assertRaises(ValueError):
            p2.render_eff(
                t3_cell,
                {
                    "adp_tls_level_binding": {
                        "level_id": t3_cell["factors"]["adp_tls_mode"],
                        "common_non_adp_strategy": ["individual_sites"],
                        "refine_strategy": ["individual_sites", "individual_adp"],
                        "adp_isotropic_selection": "all",
                        "unrequested_aniso_macromol": True,
                    },
                    "shared_ligand_cifs": [],
                    "hd_free_start_model_sha256": SHA_HD_FREE,
                    "hd_audit_receipt": VALID_HD_RECEIPT,
                },
            )

        # T4 S4 sensitivity cell (torsion_ncs_off)
        s4_cells = [c for c in p2.sensitivity_cells(3.00) if c["arm_family"] == "S4"]
        s4_tncs_off = s4_cells[1]
        rendered_s4 = p2.render_eff(
            s4_tncs_off,
            {
                "adp_tls_level_binding": {
                    "common_non_adp_strategy": ["individual_sites"],
                    "refine_strategy": ["individual_sites", "group_adp", "tls"],
                    "adp_group_selection": "all",
                    "tls_group_selections": ["chain A"],
                },
                "t4_weight_optimization_policy": {
                    "optimize_xyz_weight": False,
                    "optimize_adp_weight": False,
                    "force_optimize_weights": False,
                },
            },
        )
        self.assertTrue(rendered_s4.is_complete)
        self.assertIn(
            "refinement.pdb_interpretation.ncs_search.enabled = False",
            rendered_s4.refine_eff,
        )
        self.assertIn("refinement.ncs.type = torsion", rendered_s4.refine_eff)
        self.assertIn(
            "refinement.pdb_interpretation.secondary_structure.enabled = True",
            rendered_s4.refine_eff,
        )
        self.assertIn(
            "refinement.main.rotamer_restraints = True",
            rendered_s4.refine_eff,
        )

        # Rejects caller-supplied s4_*_phil_path bindings (including fake/unrelated paths)
        for extra_s4_bindings in (
            {
                "s4_torsion_ncs_phil_path": "refinement.main.simulated_annealing",
                "s4_secondary_structure_phil_path": "refinement.main.use_experimental_phases",
                "s4_rotamer_phil_path": "refinement.main.fake_unknown_parameter",
            },
            {
                "s4_torsion_ncs_phil_path": "refinement.pdb_interpretation.ncs_search.enabled",
            },
        ):
            with self.subTest(extra_s4_bindings=extra_s4_bindings):
                with self.assertRaises(ValueError):
                    p2.render_eff(
                        s4_tncs_off,
                        {
                            "adp_tls_level_binding": {
                                "common_non_adp_strategy": ["individual_sites"],
                                "refine_strategy": ["individual_sites", "group_adp", "tls"],
                                "adp_group_selection": "all",
                                "tls_group_selections": ["chain A"],
                            },
                            "t4_weight_optimization_policy": {
                                "optimize_xyz_weight": False,
                                "optimize_adp_weight": False,
                                "force_optimize_weights": False,
                            },
                            **extra_s4_bindings,
                        },
                    )

        # Rejects int where bool is required in t4_weight_optimization_policy
        with self.assertRaises(ValueError):
            p2.render_eff(
                s4_tncs_off,
                {
                    "adp_tls_level_binding": {
                        "common_non_adp_strategy": ["individual_sites"],
                        "refine_strategy": ["individual_sites", "group_adp", "tls"],
                        "adp_group_selection": "all",
                        "tls_group_selections": ["chain A"],
                    },
                    "t4_weight_optimization_policy": {
                        "optimize_xyz_weight": 0,
                        "optimize_adp_weight": False,
                        "force_optimize_weights": False,
                    },
                },
            )

    def test_pure_h_cif_forwarding_and_custom_group_adp_mode(self) -> None:
        # #1328: H_riding cell forwards every frozen CIF to ready_set.input.cif_file_name
        # AND refinement.input.monomers.file_name as actual non-comment PHIL assignments
        h_riding_cell = [
            c
            for c in p2.factorial_cells(1.20)
            if c["factors"]["ready_set_h"] == "H_riding"
        ][0]
        shared_cifs = [
            {"path": "ligands/customA.cif", "sha256": SHA_A},
            {"path": "ligands/customB.cif", "sha256": SHA_B},
        ]
        rendered_hr = p2.render_eff(
            h_riding_cell,
            {
                "adp_tls_level_binding": {
                    "level_id": h_riding_cell["factors"]["adp_tls_mode"],
                    "common_non_adp_strategy": ["individual_sites"],
                    "refine_strategy": ["individual_sites", "individual_adp"],
                    "adp_isotropic_selection": "all",
                },
                "shared_ligand_cifs": shared_cifs,
                "hd_free_start_model_sha256": SHA_HD_FREE,
                "hd_audit_receipt": VALID_HD_RECEIPT,
            },
        )
        self.assertIsNotNone(rendered_hr.ready_set_eff)
        rs_assignments = [
            line.strip()
            for line in (rendered_hr.ready_set_eff or "").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        ref_assignments = [
            line.strip()
            for line in rendered_hr.refine_eff.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertIn("ready_set.actions.hydrogens = True", rs_assignments)
        self.assertIn("ready_set.actions.ligands = False", rs_assignments)
        self.assertIn(
            'ready_set.input.cif_file_name = "ligands/customA.cif"', rs_assignments
        )
        self.assertIn(
            'ready_set.input.cif_file_name = "ligands/customB.cif"', rs_assignments
        )
        self.assertIn(
            'refinement.input.monomers.file_name = "ligands/customA.cif"',
            ref_assignments,
        )
        self.assertIn(
            'refinement.input.monomers.file_name = "ligands/customB.cif"',
            ref_assignments,
        )

        # #1329: Custom group selection emits group_adp_refinement_mode = group_selection
        # across fixed T4, factorial, and sensitivity cells
        prof_t4 = p2.fixed_profile(3.10, "Arm 3b-refine-only")
        rendered_t4_fixed = p2.render_eff(
            prof_t4,
            {
                "t4_adp_mode": "group_adp_plus_tls",
                "adp_selection": "chain A",
                "tls_group_selections": ["chain A"],
                "refine_strategy": ["individual_sites", "group_adp", "tls"],
                "t4_weight_optimization_policy": {
                    "optimize_xyz_weight": False,
                    "optimize_adp_weight": False,
                    "force_optimize_weights": False,
                },
            },
        )
        t4_fixed_assignments = [
            line.strip()
            for line in rendered_t4_fixed.refine_eff.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertIn(
            "refinement.refine.adp.group_adp_refinement_mode = group_selection",
            t4_fixed_assignments,
        )
        self.assertIn('refinement.refine.adp.group = "chain A"', t4_fixed_assignments)

        t4_fact_cell = p2.factorial_cells(3.10)[0]
        rendered_t4_fact = p2.render_eff(
            t4_fact_cell,
            {
                "adp_tls_level_binding": {
                    "level_id": t4_fact_cell["factors"]["adp_tls_mode"],
                    "common_non_adp_strategy": ["individual_sites"],
                    "refine_strategy": ["individual_sites", "group_adp"],
                    "adp_group_selection": "chain A",
                },
                "shared_ligand_cifs": [],
                "hd_free_start_model_sha256": SHA_HD_FREE,
                "hd_audit_receipt": VALID_HD_RECEIPT,
            },
        )
        t4_fact_assignments = [
            line.strip()
            for line in rendered_t4_fact.refine_eff.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertIn(
            "refinement.refine.adp.group_adp_refinement_mode = group_selection",
            t4_fact_assignments,
        )
        self.assertIn('refinement.refine.adp.group = "chain A"', t4_fact_assignments)

        s2_cell = [c for c in p2.sensitivity_cells(3.10) if c["arm_family"] == "S2"][0]
        rendered_s2_grp = p2.render_eff(
            s2_cell,
            {
                "adp_tls_level_binding": {
                    "common_non_adp_strategy": ["individual_sites"],
                    "refine_strategy": ["individual_sites", "group_adp", "tls"],
                    "adp_group_selection": "chain A",
                    "tls_group_selections": ["chain A"],
                },
                "t4_weight_optimization_policy": {
                    "optimize_xyz_weight": False,
                    "optimize_adp_weight": False,
                    "force_optimize_weights": False,
                },
            },
        )
        s2_grp_assignments = [
            line.strip()
            for line in rendered_s2_grp.refine_eff.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertIn(
            "refinement.refine.adp.group_adp_refinement_mode = group_selection",
            s2_grp_assignments,
        )

        # Attempting to override group_adp_refinement_mode is rejected
        with self.assertRaises(ValueError):
            p2.render_eff(
                t4_fact_cell,
                {
                    "adp_tls_level_binding": {
                        "level_id": t4_fact_cell["factors"]["adp_tls_mode"],
                        "common_non_adp_strategy": ["individual_sites"],
                        "refine_strategy": ["individual_sites", "group_adp"],
                        "adp_group_selection": "chain A",
                        "group_adp_refinement_mode": "one_adp_group_per_residue",
                    },
                    "shared_ligand_cifs": [],
                    "hd_free_start_model_sha256": SHA_HD_FREE,
                    "hd_audit_receipt": VALID_HD_RECEIPT,
                },
            )

    def test_adp_strategy_coupling_and_explicit_aniso_exceptions(self) -> None:
        t2_cell = p2.factorial_cells(1.20)[0]
        lvl_t2 = t2_cell["factors"]["adp_tls_mode"]

        # #1325: Rejects individual/group/TLS selections missing matching strategy token,
        # strategy token missing matching selection, rigid_body/confounding strategies,
        # and non-ADP strategy tokens missing or mismatching common_non_adp_strategy
        invalid_adp_bindings = [
            # rigid_body with individual isotropic selection
            {
                "level_id": lvl_t2,
                "refine_strategy": ["rigid_body"],
                "adp_isotropic_selection": "all",
            },
            # group selector with tls only (missing group_adp)
            {
                "level_id": lvl_t2,
                "refine_strategy": ["tls"],
                "adp_group_selection": "chain A",
                "tls_group_selections": ["chain A"],
            },
            # individual selector with tls only (missing individual_adp)
            {
                "level_id": lvl_t2,
                "refine_strategy": ["tls"],
                "adp_isotropic_selection": "all",
                "tls_group_selections": ["chain A"],
            },
            # individual_adp in strategy but no individual selection
            {
                "level_id": lvl_t2,
                "refine_strategy": ["individual_adp", "tls"],
                "tls_group_selections": ["chain A"],
            },
            # group_adp in strategy but no group selection
            {
                "level_id": lvl_t2,
                "refine_strategy": ["group_adp", "tls"],
                "tls_group_selections": ["chain A"],
            },
            # non-ADP strategy token without common_non_adp_strategy
            {
                "level_id": lvl_t2,
                "refine_strategy": ["individual_sites", "individual_adp"],
                "adp_isotropic_selection": "all",
            },
            # non-ADP strategy token mismatching common_non_adp_strategy
            {
                "level_id": lvl_t2,
                "common_non_adp_strategy": ["individual_sites"],
                "refine_strategy": ["rigid_body", "individual_adp"],
                "adp_isotropic_selection": "all",
            },
            # ADP token included inside common_non_adp_strategy
            {
                "level_id": lvl_t2,
                "common_non_adp_strategy": ["individual_adp"],
                "refine_strategy": ["individual_adp"],
                "adp_isotropic_selection": "all",
            },
        ]
        for idx, bad_adp in enumerate(invalid_adp_bindings):
            with self.subTest(bad_adp_idx=idx):
                with self.assertRaises(ValueError):
                    p2.render_eff(
                        t2_cell,
                        {
                            "adp_tls_level_binding": bad_adp,
                            "shared_ligand_cifs": [],
                            "hd_free_start_model_sha256": SHA_HD_FREE,
                            "hd_audit_receipt": VALID_HD_RECEIPT,
                        },
                    )

        # Matching shared supported non-ADP strategies (e.g. rigid_body, occupancies)
        # with valid ADP strategy & selection render cleanly without blanket exclusion
        for non_adp_tok in ("rigid_body", "occupancies", "group_anomalous"):
            with self.subTest(shared_non_adp=non_adp_tok):
                rendered_shared = p2.render_eff(
                    t2_cell,
                    {
                        "adp_tls_level_binding": {
                            "level_id": lvl_t2,
                            "common_non_adp_strategy": [non_adp_tok],
                            "refine_strategy": [non_adp_tok, "individual_adp"],
                            "adp_isotropic_selection": "all",
                        },
                        "shared_ligand_cifs": [],
                        "hd_free_start_model_sha256": SHA_HD_FREE,
                        "hd_audit_receipt": VALID_HD_RECEIPT,
                    },
                )
                self.assertTrue(rendered_shared.is_complete)
                self.assertIn(
                    f"refinement.refine.strategy = {non_adp_tok}+individual_adp",
                    rendered_shared.refine_eff,
                )

        # #1327: At d_min = 1.60 A (T3), explicit adp_anisotropic_selection with individual_adp
        # is permitted (native demotion exception), whereas unrequested_aniso_macromol=True is rejected
        t3_1p60_cell = p2.factorial_cells(1.60)[0]
        lvl_1p60 = t3_1p60_cell["factors"]["adp_tls_mode"]
        explicit_aniso_1p60 = p2.render_eff(
            t3_1p60_cell,
            {
                "adp_tls_level_binding": {
                    "level_id": lvl_1p60,
                    "refine_strategy": ["individual_adp"],
                    "adp_anisotropic_selection": "protein and not element H",
                    "unrequested_aniso_macromol": False,
                },
                "shared_ligand_cifs": [],
                "hd_free_start_model_sha256": SHA_HD_FREE,
                "hd_audit_receipt": VALID_HD_RECEIPT,
            },
        )
        self.assertTrue(explicit_aniso_1p60.is_complete)
        self.assertIn(
            'refinement.refine.adp.individual.anisotropic = "protein and not element H"',
            explicit_aniso_1p60.refine_eff,
        )

        # Unrequested aniso rejected at 1.60 A, allowed at exact boundary d_min = 1.50 A
        with self.assertRaises(ValueError):
            p2.render_eff(
                t3_1p60_cell,
                {
                    "adp_tls_level_binding": {
                        "level_id": lvl_1p60,
                        "refine_strategy": ["individual_adp"],
                        "adp_isotropic_selection": "all",
                        "unrequested_aniso_macromol": True,
                    },
                    "shared_ligand_cifs": [],
                    "hd_free_start_model_sha256": SHA_HD_FREE,
                    "hd_audit_receipt": VALID_HD_RECEIPT,
                },
            )

        t3_1p50_cell = p2.factorial_cells(1.50)[0]
        boundary_1p50 = p2.render_eff(
            t3_1p50_cell,
            {
                "adp_tls_level_binding": {
                    "level_id": t3_1p50_cell["factors"]["adp_tls_mode"],
                    "refine_strategy": ["individual_adp"],
                    "adp_anisotropic_selection": "not water and not element H",
                    "unrequested_aniso_macromol": True,
                },
                "shared_ligand_cifs": [],
                "hd_free_start_model_sha256": SHA_HD_FREE,
                "hd_audit_receipt": VALID_HD_RECEIPT,
            },
        )
        self.assertTrue(boundary_1p50.is_complete)

        # Non-bool unrequested_aniso_macromol values (1, 0, "true") are rejected
        for bad_flag in (1, 0, "true", None):
            with self.subTest(bad_unreq_flag=bad_flag):
                with self.assertRaises(ValueError):
                    p2.render_eff(
                        t3_1p50_cell,
                        {
                            "adp_tls_level_binding": {
                                "level_id": t3_1p50_cell["factors"]["adp_tls_mode"],
                                "refine_strategy": ["individual_adp"],
                                "adp_isotropic_selection": "all",
                                "unrequested_aniso_macromol": bad_flag,
                            },
                            "shared_ligand_cifs": [],
                            "hd_free_start_model_sha256": SHA_HD_FREE,
                            "hd_audit_receipt": VALID_HD_RECEIPT,
                        },
                    )

        # Batch validator enforces identical common_non_adp_strategy, shared_ligand_cifs,
        # hd_free_start_model_sha256, and hd_audit_receipt across H_off and H_riding
        t3_cells = p2.factorial_cells(1.80)
        batch_bindings: dict[str, dict[str, object]] = {}
        for c in t3_cells:
            lvl = c["factors"]["adp_tls_mode"]
            if lvl.endswith("_level_a_unresolved"):
                adp_b = {
                    "level_id": lvl,
                    "common_non_adp_strategy": ["individual_sites"],
                    "refine_strategy": ["individual_sites", "individual_adp"],
                    "adp_isotropic_selection": "all",
                }
            else:
                adp_b = {
                    "level_id": lvl,
                    "common_non_adp_strategy": ["individual_sites"],
                    "refine_strategy": ["individual_sites", "individual_adp", "tls"],
                    "adp_isotropic_selection": "all",
                    "tls_group_selections": ["chain A"],
                }
            entry: dict[str, object] = {
                "adp_tls_level_binding": adp_b,
                "shared_ligand_cifs": [{"path": "restraints/ligA.cif", "sha256": SHA_A}],
                "hd_free_start_model_sha256": SHA_HD_FREE,
                "hd_audit_receipt": copy.deepcopy(VALID_HD_RECEIPT),
            }
            batch_bindings[c["cell_id"]] = entry

        batch_rendered = p2.validate_factorial_bindings_batch(t3_cells, batch_bindings)
        self.assertEqual(len(batch_rendered), 16)

        # Varying common_non_adp_strategy in one cell of the batch fails closed
        mismatched_batch = copy.deepcopy(batch_bindings)
        first_id = t3_cells[0]["cell_id"]
        mismatched_batch[first_id]["adp_tls_level_binding"] = {
            "level_id": t3_cells[0]["factors"]["adp_tls_mode"],
            "common_non_adp_strategy": ["individual_sites_real_space"],
            "refine_strategy": ["individual_sites_real_space", "individual_adp"],
            "adp_isotropic_selection": "all",
        }
        with self.assertRaises(ValueError):
            p2.validate_factorial_bindings_batch(t3_cells, mismatched_batch)

    def test_pure_h_common_start_and_audit_receipt_contract(self) -> None:
        cells = p2.factorial_cells(1.80)
        h_off_cell = [c for c in cells if c["factors"]["ready_set_h"] == "H_off"][0]
        h_riding_cell = [c for c in cells if c["factors"]["ready_set_h"] == "H_riding"][0]

        def _base_binding(cell: dict[str, object]) -> dict[str, object]:
            return {
                "adp_tls_level_binding": {
                    "level_id": cell["factors"]["adp_tls_mode"],  # type: ignore[index]
                    "common_non_adp_strategy": ["individual_sites"],
                    "refine_strategy": ["individual_sites", "individual_adp"],
                    "adp_isotropic_selection": "all",
                },
                "shared_ligand_cifs": [{"path": "restraints/ligA.cif", "sha256": SHA_A}],
                "hd_free_start_model_sha256": SHA_HD_FREE,
                "hd_audit_receipt": copy.deepcopy(VALID_HD_RECEIPT),
            }

        # Valid declared common binding renders both H_off and H_riding
        r_off = p2.render_eff(h_off_cell, _base_binding(h_off_cell))
        r_rid = p2.render_eff(h_riding_cell, _base_binding(h_riding_cell))
        for bundle in (r_off, r_rid):
            self.assertTrue(bundle.is_complete)
            self.assertNotIn("verified H/D-free input", str(bundle))
            self.assertIn(
                f"# hd_free_start_model_sha256 = {SHA_HD_FREE} "
                "(declared common starting-model binding; not runtime-verified from hash alone)",
                bundle.refine_eff,
            )
            self.assertIn(
                f"# hd_audit_receipt_sha256 = {SHA_HD_RECEIPT} | "
                f"subject_model_sha256 = {SHA_HD_FREE} | declared_hd_atom_count = 0 "
                "(declared evidence-bound receipt contract; coordinate bytes not inspected by spec compiler)",
                bundle.refine_eff,
            )

        # Missing hd_free_start_model_sha256 or hd_audit_receipt on H_riding fails closed
        for missing_key in ("hd_free_start_model_sha256", "hd_audit_receipt"):
            with self.subTest(missing_h_riding=missing_key):
                bad_rid = _base_binding(h_riding_cell)
                bad_rid.pop(missing_key)
                with self.assertRaises(ValueError):
                    p2.render_eff(h_riding_cell, bad_rid)

        # Bare hash alone (without hd_audit_receipt or with bare string receipt) is insufficient
        for cell in (h_off_cell, h_riding_cell):
            bad_bare = _base_binding(cell)
            bad_bare.pop("hd_audit_receipt")
            with self.assertRaises(ValueError):
                p2.render_eff(cell, bad_bare)
            bad_str_receipt = _base_binding(cell)
            bad_str_receipt["hd_audit_receipt"] = SHA_HD_RECEIPT
            with self.assertRaises(ValueError):
                p2.render_eff(cell, bad_str_receipt)

        # Receipt subject_model_sha256 mismatching hd_free_start_model_sha256 fails closed
        bad_mismatch = _base_binding(h_off_cell)
        bad_mismatch["hd_audit_receipt"] = {
            "receipt_sha256": SHA_HD_RECEIPT,
            "subject_model_sha256": SHA_A,
            "hd_atom_count": 0,
        }
        with self.assertRaises(ValueError):
            p2.render_eff(h_off_cell, bad_mismatch)

        # Nonzero, unknown, string, float, or bool hd_atom_count fails closed
        for bad_hd_count in (1, -1, 14, False, True, None, "0", "unknown", 0.0):
            with self.subTest(bad_hd_count=bad_hd_count):
                bad_cnt = _base_binding(h_off_cell)
                bad_cnt["hd_audit_receipt"] = {
                    "receipt_sha256": SHA_HD_RECEIPT,
                    "subject_model_sha256": SHA_HD_FREE,
                    "hd_atom_count": bad_hd_count,
                }
                with self.assertRaises(ValueError):
                    p2.render_eff(h_off_cell, bad_cnt)

        # Batch validator rejects differing starting-model SHA or differing receipt SHA
        # between H_off and H_riding
        pair_cells = [h_off_cell, h_riding_cell]
        b_off = _base_binding(h_off_cell)
        b_rid_diff_model = _base_binding(h_riding_cell)
        b_rid_diff_model["hd_free_start_model_sha256"] = SHA_B
        b_rid_diff_model["hd_audit_receipt"] = {
            "receipt_sha256": SHA_HD_RECEIPT,
            "subject_model_sha256": SHA_B,
            "hd_atom_count": 0,
        }
        with self.assertRaises(ValueError):
            p2.validate_factorial_bindings_batch(pair_cells, [b_off, b_rid_diff_model])

        b_rid_diff_receipt = _base_binding(h_riding_cell)
        b_rid_diff_receipt["hd_audit_receipt"] = {
            "receipt_sha256": SHA_B,
            "subject_model_sha256": SHA_HD_FREE,
            "hd_atom_count": 0,
        }
        with self.assertRaises(ValueError):
            p2.validate_factorial_bindings_batch(pair_cells, [b_off, b_rid_diff_receipt])

    def test_s1_preserve_input_adp_and_pair_rendering(self) -> None:
        valid_s1_bindings = {
            "adp_tls_level_binding": {
                "mode": "preserve_input_adp",
                "common_non_adp_strategy": ["individual_sites"],
                "refine_strategy": ["individual_sites", "individual_adp"],
                "input_model_sha256": SHA_A,
                "applicability_receipt_sha256": SHA_B,
                "unrequested_anisou_count": 42,
            }
        }

        for d_min in (1.50, 1.60, 1.70):
            with self.subTest(s1_pair_d_min=d_min):
                pair_rendered = p2.render_s1_pair(d_min, valid_s1_bindings)
                self.assertEqual(len(pair_rendered), 2)
                s1_cells = [c for c in p2.sensitivity_cells(d_min) if c["arm_family"] == "S1"]
                r_1p5 = pair_rendered[s1_cells[0]["cell_id"]]
                r_1p7 = pair_rendered[s1_cells[1]["cell_id"]]

                for bundle in (r_1p5, r_1p7):
                    self.assertTrue(bundle.is_complete)
                    self.assertIn(
                        "refinement.refine.strategy = individual_sites+individual_adp",
                        bundle.refine_eff,
                    )
                    self.assertNotIn("refinement.refine.adp.individual", bundle.refine_eff)
                    self.assertNotIn("refinement.refine.adp.group", bundle.refine_eff)
                    self.assertNotIn("refinement.refine.adp.tls", bundle.refine_eff)
                    self.assertIn(
                        "# s1_binding_mode = preserve_input_adp "
                        "(declared input-ADP preservation; not runtime-verified)",
                        bundle.refine_eff,
                    )
                    self.assertIn(
                        "evidence-bound applicability declaration; not verified native execution",
                        bundle.refine_eff,
                    )

                diffs = [
                    (l1, l2)
                    for l1, l2 in zip(
                        r_1p5.refine_eff.splitlines(),
                        r_1p7.refine_eff.splitlines(),
                        strict=True,
                    )
                    if l1 != l2
                ]
                self.assertEqual(
                    diffs,
                    [
                        (
                            "refinement.main.switch_to_isotropic_high_res_limit = 1.5",
                            "refinement.main.switch_to_isotropic_high_res_limit = 1.7",
                        )
                    ],
                )

        s1_1p60 = [c for c in p2.sensitivity_cells(1.60) if c["arm_family"] == "S1"]
        cell_1p5 = s1_1p60[0]

        # Reject explicit isotropic, anisotropic, group, or TLS selections on S1
        for bad_sel_key, bad_sel_val in (
            ("adp_isotropic_selection", "all"),
            ("adp_anisotropic_selection", "protein and not element H"),
            ("adp_group_selection", "chain A"),
            ("tls_group_selections", ["chain A"]),
        ):
            with self.subTest(bad_s1_selection=bad_sel_key):
                bad_b = copy.deepcopy(valid_s1_bindings)
                bad_b["adp_tls_level_binding"][bad_sel_key] = bad_sel_val  # type: ignore[index]
                with self.assertRaises(ValueError):
                    p2.render_eff(cell_1p5, bad_b)

        # Reject missing applicability fields or invalid unrequested_anisou_count
        for missing_key in (
            "mode",
            "input_model_sha256",
            "applicability_receipt_sha256",
            "unrequested_anisou_count",
        ):
            with self.subTest(missing_s1_key=missing_key):
                bad_b = copy.deepcopy(valid_s1_bindings)
                bad_b["adp_tls_level_binding"].pop(missing_key)  # type: ignore[attr-defined]
                with self.assertRaises(ValueError):
                    p2.render_eff(cell_1p5, bad_b)

        for bad_count in (0, -5, True, False, "42", 42.0):
            with self.subTest(bad_anisou_count=bad_count):
                bad_b = copy.deepcopy(valid_s1_bindings)
                bad_b["adp_tls_level_binding"]["unrequested_anisou_count"] = bad_count  # type: ignore[index]
                with self.assertRaises(ValueError):
                    p2.render_eff(cell_1p5, bad_b)

        # Reject preserve_input_adp mode on non-S1 sensitivity cells
        s2_cell = [c for c in p2.sensitivity_cells(1.60) if c["arm_family"] == "S2"][0]
        with self.assertRaises(ValueError):
            p2.render_eff(s2_cell, valid_s1_bindings)

        # Reject mismatched bindings across the S1 pair
        b_alt = copy.deepcopy(valid_s1_bindings)
        b_alt["adp_tls_level_binding"]["unrequested_anisou_count"] = 99  # type: ignore[index]
        with self.assertRaises(ValueError):
            p2.validate_s1_pair_bindings(s1_1p60, [valid_s1_bindings, b_alt])

    def test_s2_s3_s4_comparison_validators_and_one_factor_diffs(self) -> None:
        # #1335: Single-cell render_eff marks single_cell_binding_complete=True
        # and comparison_one_factor_verified=False, with explicit comment
        s2_t2 = [
            c
            for c in p2.sensitivity_cells(1.20)
            if c["comparison_group"] == "S2_restraints_library_cdl"
        ]
        b_indiv = {
            "adp_tls_level_binding": {
                "common_non_adp_strategy": ["individual_sites"],
                "refine_strategy": ["individual_sites", "individual_adp"],
                "adp_isotropic_selection": "all",
            }
        }
        b_group = {
            "adp_tls_level_binding": {
                "common_non_adp_strategy": ["individual_sites"],
                "refine_strategy": ["individual_sites", "group_adp"],
                "adp_group_selection": "all",
            }
        }
        single_a = p2.render_eff(s2_t2[0], b_indiv)
        single_b = p2.render_eff(s2_t2[1], b_group)
        self.assertTrue(single_a.is_complete)
        self.assertTrue(single_a.single_cell_binding_complete)
        self.assertFalse(single_a.comparison_one_factor_verified)
        self.assertIn(
            "# single_cell_binding_completeness_only = True | comparison_one_factor_verified = False",
            single_a.refine_eff,
        )
        self.assertTrue(single_b.is_complete)
        self.assertFalse(single_b.comparison_one_factor_verified)

        # Case 1 reproduction (#1335): changed ADP mode/selectors across S2 pair is rejected
        # at comparison level (both as sequence and as per-cell dict)
        with self.assertRaises(ValueError):
            p2.validate_sensitivity_comparison_bindings(s2_t2, [b_indiv, b_group])
        with self.assertRaises(ValueError):
            p2.render_sensitivity_comparison(
                1.20,
                "S2_restraints_library_cdl",
                {
                    s2_t2[0]["cell_id"]: b_indiv,
                    s2_t2[1]["cell_id"]: b_group,
                },
            )

        # Changed ADP selector within individual_adp across S3_c_beta_restraints or S3_nonbonded_weight is rejected
        s3_cbeta = [
            c
            for c in p2.sensitivity_cells(1.80)
            if c["comparison_group"] == "S3_c_beta_restraints"
        ]
        s3_nb = [
            c
            for c in p2.sensitivity_cells(1.80)
            if c["comparison_group"] == "S3_nonbonded_weight"
        ]
        b_indiv_chain_a = {
            "adp_tls_level_binding": {
                "common_non_adp_strategy": ["individual_sites"],
                "refine_strategy": ["individual_sites", "individual_adp"],
                "adp_isotropic_selection": "chain A",
            }
        }
        for grp_cells in (s3_cbeta, s3_nb):
            with self.subTest(grp=grp_cells[0]["comparison_group"]):
                with self.assertRaises(ValueError):
                    p2.validate_sensitivity_comparison_bindings(
                        grp_cells, [b_indiv, b_indiv_chain_a]
                    )

        # Positive S2, S3_c_beta_restraints, and S3_nonbonded_weight comparisons
        rendered_s2 = p2.render_sensitivity_comparison(1.20, "S2", b_indiv)
        self.assertEqual(
            list(rendered_s2.keys()),
            ["S2__T2__cdl_true", "S2__T2__cdl_false"],
        )
        for bundle in rendered_s2.values():
            self.assertTrue(bundle.is_complete)
            self.assertTrue(bundle.single_cell_binding_complete)
            self.assertTrue(bundle.comparison_one_factor_verified)
            self.assertTrue(bundle.to_dict()["comparison_one_factor_verified"])
            self.assertIn(
                "# single_cell_binding_completeness_only = False | comparison_one_factor_verified = True "
                "(verified supplied comparison-group bindings and operative one-factor PHIL diffs only; "
                "actual model/native realization and development-set freeze remain unverified)",
                bundle.refine_eff,
            )
            self.assertIn(
                "# single_cell_binding_completeness_only = False | comparison_one_factor_verified = True",
                str(bundle),
            )
            self.assertIn(
                "# single_cell_binding_completeness_only = False | comparison_one_factor_verified = True",
                bundle.to_dict()["combined_eff"],
            )
            self.assertNotIn("comparison_one_factor_verified = False", bundle.refine_eff)
            self.assertNotIn("comparison_one_factor_verified = False", str(bundle))
        self.assertEqual(
            p2._diff_non_comment_phil(
                rendered_s2["S2__T2__cdl_true"].refine_eff,
                rendered_s2["S2__T2__cdl_false"].refine_eff,
                context_label="test_s2",
            ),
            [
                (
                    "refinement.pdb_interpretation.restraints_library.cdl = True",
                    "refinement.pdb_interpretation.restraints_library.cdl = False",
                )
            ],
        )

        rendered_s3_cb = p2.render_sensitivity_comparison(
            1.80,
            "S3_c_beta_restraints",
            [copy.deepcopy(b_indiv), copy.deepcopy(b_indiv)],
        )
        self.assertEqual(
            list(rendered_s3_cb.keys()),
            ["S3__T3__c_beta_restraints_true", "S3__T3__c_beta_restraints_false"],
        )
        self.assertEqual(
            p2._diff_non_comment_phil(
                rendered_s3_cb["S3__T3__c_beta_restraints_true"].refine_eff,
                rendered_s3_cb["S3__T3__c_beta_restraints_false"].refine_eff,
                context_label="test_s3_cb",
            ),
            [
                (
                    "refinement.pdb_interpretation.c_beta_restraints = True",
                    "refinement.pdb_interpretation.c_beta_restraints = False",
                )
            ],
        )

        rendered_s3_nb = p2.render_sensitivity_comparison(
            1.80,
            "S3_nonbonded_weight",
            {
                "S3__T3__nonbonded_weight_100": copy.deepcopy(b_indiv),
                "S3__T3__nonbonded_weight_16": copy.deepcopy(b_indiv),
            },
        )
        self.assertEqual(
            list(rendered_s3_nb.keys()),
            ["S3__T3__nonbonded_weight_100", "S3__T3__nonbonded_weight_16"],
        )
        self.assertEqual(
            p2._diff_non_comment_phil(
                rendered_s3_nb["S3__T3__nonbonded_weight_100"].refine_eff,
                rendered_s3_nb["S3__T3__nonbonded_weight_16"].refine_eff,
                context_label="test_s3_nb",
            ),
            [
                (
                    "refinement.pdb_interpretation.nonbonded_weight = 100",
                    "refinement.pdb_interpretation.nonbonded_weight = 16",
                )
            ],
        )

        # Positive S4 Tier 4 group comparison: all_on vs each single ablation
        s4_cells = [
            c
            for c in p2.sensitivity_cells(3.10)
            if c["comparison_group"] == "S4_t4_low_resolution_restraints_one_by_one"
        ]
        b_t4_shared = {
            "adp_tls_level_binding": {
                "common_non_adp_strategy": ["individual_sites"],
                "refine_strategy": ["individual_sites", "group_adp", "tls"],
                "adp_group_selection": "all",
                "tls_group_selections": ["chain A"],
            },
            "t4_weight_optimization_policy": {
                "optimize_xyz_weight": False,
                "optimize_adp_weight": False,
                "force_optimize_weights": False,
            },
        }
        rendered_s4 = p2.render_sensitivity_comparison(3.10, "S4", b_t4_shared)
        self.assertEqual(
            list(rendered_s4.keys()),
            [
                "S4__T4__all_on",
                "S4__T4__torsion_ncs_off",
                "S4__T4__secondary_structure_off",
                "S4__T4__rotamer_off",
            ],
        )
        for cid, bundle in rendered_s4.items():
            self.assertTrue(bundle.comparison_one_factor_verified)
            self.assertIn(
                "refinement.ncs.type = torsion",
                p2._non_comment_phil_lines(bundle.refine_eff),
            )
        self.assertEqual(
            p2._diff_non_comment_phil(
                rendered_s4["S4__T4__all_on"].refine_eff,
                rendered_s4["S4__T4__torsion_ncs_off"].refine_eff,
                context_label="s4_tncs",
            ),
            [
                (
                    "refinement.pdb_interpretation.ncs_search.enabled = True",
                    "refinement.pdb_interpretation.ncs_search.enabled = False",
                )
            ],
        )
        self.assertEqual(
            p2._diff_non_comment_phil(
                rendered_s4["S4__T4__all_on"].refine_eff,
                rendered_s4["S4__T4__secondary_structure_off"].refine_eff,
                context_label="s4_ss",
            ),
            [
                (
                    "refinement.pdb_interpretation.secondary_structure.enabled = True",
                    "refinement.pdb_interpretation.secondary_structure.enabled = False",
                )
            ],
        )
        self.assertEqual(
            p2._diff_non_comment_phil(
                rendered_s4["S4__T4__all_on"].refine_eff,
                rendered_s4["S4__T4__rotamer_off"].refine_eff,
                context_label="s4_rot",
            ),
            [
                (
                    "refinement.main.rotamer_restraints = True",
                    "refinement.main.rotamer_restraints = False",
                )
            ],
        )

        # Reject changed T4 weight optimization policy across S4 cells (or T4 S2 cells)
        b_t4_opt_weights = copy.deepcopy(b_t4_shared)
        b_t4_opt_weights["t4_weight_optimization_policy"] = {
            "optimize_xyz_weight": True,
            "optimize_adp_weight": False,
            "force_optimize_weights": True,
        }
        with self.assertRaises(ValueError):
            p2.validate_sensitivity_comparison_bindings(
                s4_cells,
                [
                    b_t4_shared,
                    b_t4_shared,
                    b_t4_shared,
                    b_t4_opt_weights,
                ],
            )
        s2_t4 = [
            c
            for c in p2.sensitivity_cells(3.10)
            if c["comparison_group"] == "S2_restraints_library_cdl"
        ]
        with self.assertRaises(ValueError):
            p2.validate_sensitivity_comparison_bindings(
                s2_t4,
                [b_t4_shared, b_t4_opt_weights],
            )

        # Reject changed ADP mode across S4 cells
        b_t4_indiv_adp = copy.deepcopy(b_t4_shared)
        b_t4_indiv_adp["adp_tls_level_binding"] = {
            "common_non_adp_strategy": ["individual_sites"],
            "refine_strategy": ["individual_sites", "individual_adp", "tls"],
            "adp_isotropic_selection": "all",
            "tls_group_selections": ["chain A"],
        }
        with self.assertRaises(ValueError):
            p2.validate_sensitivity_comparison_bindings(
                s4_cells,
                [b_t4_shared, b_t4_indiv_adp, b_t4_shared, b_t4_shared],
            )

        # Reject missing, duplicate, wrong, or mixed-group cells
        # 1. Missing cell in S2 or S4
        with self.assertRaises(ValueError):
            p2.validate_sensitivity_comparison_bindings([s2_t2[0]], [b_indiv])
        with self.assertRaises(ValueError):
            p2.validate_sensitivity_comparison_bindings(s4_cells[:3], b_t4_shared)
        with self.assertRaises(ValueError):
            p2.validate_sensitivity_comparison_bindings(s4_cells[1:], b_t4_shared)

        # 2. Duplicate cell
        with self.assertRaises(ValueError):
            p2.validate_sensitivity_comparison_bindings(
                [s2_t2[0], s2_t2[0]], [b_indiv, b_indiv]
            )

        # 3. Combining the two S3 factors or mixing S2 and S3
        with self.assertRaises(ValueError):
            p2.validate_sensitivity_comparison_bindings(
                [s3_cbeta[0], s3_nb[0]], [b_indiv, b_indiv]
            )
        with self.assertRaises(ValueError):
            p2.validate_sensitivity_comparison_bindings(
                [*s3_cbeta, *s3_nb], b_indiv
            )
        with self.assertRaises(ValueError):
            p2.render_sensitivity_comparison(1.80, "S3", b_indiv)

        # 4. Mismatched d_min across cells
        s2_t3 = [
            c
            for c in p2.sensitivity_cells(1.80)
            if c["comparison_group"] == "S2_restraints_library_cdl"
        ]
        with self.assertRaises(ValueError):
            p2.validate_sensitivity_comparison_bindings(
                [s2_t2[0], s2_t3[1]], [b_indiv, b_indiv]
            )

        # 5. Unscheduled S4 at d_min < 2.80 A
        with self.assertRaises(ValueError):
            p2.render_sensitivity_comparison(1.80, "S4", b_indiv)

    def test_factorial_normalized_binding_signature_and_order_aliases(self) -> None:
        t3_cells = p2.factorial_cells(1.80)
        self.assertEqual(len(t3_cells), 16)

        def _build_batch(
            level_a_adp_fn: object,
            level_b_adp_fn: object,
        ) -> dict[str, dict[str, object]]:
            batch: dict[str, dict[str, object]] = {}
            for idx, cell in enumerate(t3_cells):
                lvl = str(cell["factors"]["adp_tls_mode"])
                if lvl.endswith("_level_a_unresolved"):
                    adp_b = dict(level_a_adp_fn(idx, lvl))  # type: ignore[operator]
                else:
                    adp_b = dict(level_b_adp_fn(idx, lvl))  # type: ignore[operator]
                batch[cell["cell_id"]] = {
                    "adp_tls_level_binding": adp_b,
                    "shared_ligand_cifs": [
                        {"path": "restraints/ligA.cif", "sha256": SHA_A}
                    ],
                    "hd_free_start_model_sha256": SHA_HD_FREE,
                    "hd_audit_receipt": copy.deepcopy(VALID_HD_RECEIPT),
                }
            return batch

        # 1. Exact Case 2 reproduction (#1336): full 16-cell batch with strategy-only
        # reordering ([individual_adp, tls] vs [tls, individual_adp]) is rejected
        batch_case2 = _build_batch(
            lambda _idx, lvl: {
                "level_id": lvl,
                "common_non_adp_strategy": [],
                "refine_strategy": ["individual_adp", "tls"],
                "adp_isotropic_selection": "all",
                "tls_group_selections": ["chain A", "chain B"],
            },
            lambda _idx, lvl: {
                "level_id": lvl,
                "common_non_adp_strategy": [],
                "refine_strategy": ["tls", "individual_adp"],
                "adp_isotropic_selection": "all",
                "tls_group_selections": ["chain A", "chain B"],
            },
        )
        with self.assertRaises(ValueError):
            p2.validate_factorial_bindings_batch(t3_cells, batch_case2)

        # #1325 regression: full 16-cell genuinely different ADP batch whose strategies
        # contain only ADP tokens but omit explicit common_non_adp_strategy must reject,
        # while the same batch with explicit common_non_adp_strategy=[] must pass.
        batch_missing_common = _build_batch(
            lambda _idx, lvl: {
                "level_id": lvl,
                "refine_strategy": ["individual_adp"],
                "adp_isotropic_selection": "all",
            },
            lambda _idx, lvl: {
                "level_id": lvl,
                "refine_strategy": ["individual_adp", "tls"],
                "adp_isotropic_selection": "all",
                "tls_group_selections": ["chain A"],
            },
        )
        with self.assertRaisesRegex(
            ValueError, "missing required explicit 'common_non_adp_strategy'"
        ):
            p2.validate_factorial_bindings_batch(t3_cells, batch_missing_common)

        batch_explicit_empty_common = _build_batch(
            lambda _idx, lvl: {
                "level_id": lvl,
                "common_non_adp_strategy": [],
                "refine_strategy": ["individual_adp"],
                "adp_isotropic_selection": "all",
            },
            lambda _idx, lvl: {
                "level_id": lvl,
                "common_non_adp_strategy": [],
                "refine_strategy": ["individual_adp", "tls"],
                "adp_isotropic_selection": "all",
                "tls_group_selections": ["chain A"],
            },
        )
        rendered_empty_common = p2.validate_factorial_bindings_batch(
            t3_cells, batch_explicit_empty_common
        )
        self.assertEqual(len(rendered_empty_common), 16)

        # Also rejected with non-ADP strategy included ([individual_sites, individual_adp, tls]
        # vs [individual_sites, tls, individual_adp])
        batch_strategy_reorder = _build_batch(
            lambda _idx, lvl: {
                "level_id": lvl,
                "common_non_adp_strategy": ["individual_sites"],
                "refine_strategy": ["individual_sites", "individual_adp", "tls"],
                "adp_isotropic_selection": "all",
                "tls_group_selections": ["chain A", "chain B"],
            },
            lambda _idx, lvl: {
                "level_id": lvl,
                "common_non_adp_strategy": ["individual_sites"],
                "refine_strategy": ["individual_sites", "tls", "individual_adp"],
                "adp_isotropic_selection": "all",
                "tls_group_selections": ["chain A", "chain B"],
            },
        )
        with self.assertRaises(ValueError):
            p2.validate_factorial_bindings_batch(t3_cells, batch_strategy_reorder)

        # 2. Full 16-cell batch with same TLS-group collection reordered
        # (["chain A", "chain B"] vs ["chain B", "chain A"]) is rejected
        batch_tls_reorder = _build_batch(
            lambda _idx, lvl: {
                "level_id": lvl,
                "common_non_adp_strategy": ["individual_sites"],
                "refine_strategy": ["individual_sites", "individual_adp", "tls"],
                "adp_isotropic_selection": "all",
                "tls_group_selections": ["chain A", "chain B"],
            },
            lambda _idx, lvl: {
                "level_id": lvl,
                "common_non_adp_strategy": ["individual_sites"],
                "refine_strategy": ["individual_sites", "individual_adp", "tls"],
                "adp_isotropic_selection": "all",
                "tls_group_selections": ["chain B", "chain A"],
            },
        )
        with self.assertRaises(ValueError):
            p2.validate_factorial_bindings_batch(t3_cells, batch_tls_reorder)

        # 3. Repeated same-level order aliases (strategy-order + TLS-group order aliases
        # within Level A) normalize consistently when Level B is genuinely distinct
        batch_same_level_aliases = _build_batch(
            lambda idx, lvl: {
                "level_id": lvl,
                "common_non_adp_strategy": ["individual_sites"],
                "refine_strategy": (
                    ["individual_sites", "individual_adp", "tls"]
                    if idx % 2 == 0
                    else ["tls", "individual_sites", "individual_adp"]
                ),
                "adp_isotropic_selection": "all",
                "tls_group_selections": (
                    ["chain A", "chain B"]
                    if idx % 2 == 0
                    else ["chain B", "chain A"]
                ),
            },
            lambda _idx, lvl: {
                "level_id": lvl,
                "common_non_adp_strategy": ["individual_sites"],
                "refine_strategy": ["individual_sites", "group_adp", "tls"],
                "adp_group_selection": "all",
                "tls_group_selections": ["chain A", "chain B"],
            },
        )
        rendered_aliases = p2.validate_factorial_bindings_batch(
            t3_cells, batch_same_level_aliases
        )
        self.assertEqual(len(rendered_aliases), 16)

        # 4. Genuinely inconsistent bindings within the same level still fail closed
        batch_inconsistent_same_level = copy.deepcopy(batch_same_level_aliases)
        first_cid = t3_cells[0]["cell_id"]
        batch_inconsistent_same_level[first_cid]["adp_tls_level_binding"][  # type: ignore[index]
            "adp_isotropic_selection"
        ] = "not water"
        with self.assertRaises(ValueError):
            p2.validate_factorial_bindings_batch(
                t3_cells, batch_inconsistent_same_level
            )

        # 5. Actual different selection strings or TLS group collections pass
        batch_distinct_selectors = _build_batch(
            lambda _idx, lvl: {
                "level_id": lvl,
                "common_non_adp_strategy": ["individual_sites"],
                "refine_strategy": ["individual_sites", "individual_adp", "tls"],
                "adp_isotropic_selection": "all",
                "tls_group_selections": ["chain A"],
            },
            lambda _idx, lvl: {
                "level_id": lvl,
                "common_non_adp_strategy": ["individual_sites"],
                "refine_strategy": ["individual_sites", "individual_adp", "tls"],
                "adp_isotropic_selection": "all",
                "tls_group_selections": ["chain A", "chain B"],
            },
        )
        rendered_distinct = p2.validate_factorial_bindings_batch(
            t3_cells, batch_distinct_selectors
        )
        self.assertEqual(len(rendered_distinct), 16)

        # 6. #1336 follow-up: at d_min = 1.20 A (<= 1.50 A), a full 16-cell batch
        # whose two ADP/TLS levels differ ONLY on non-operative metadata
        # unrequested_aniso_macromol (False vs True) is rejected
        t2_cells = p2.factorial_cells(1.20)
        self.assertEqual(len(t2_cells), 16)
        batch_t2_metadata_only: dict[str, dict[str, object]] = {}
        for cell in t2_cells:
            lvl = str(cell["factors"]["adp_tls_mode"])
            is_lvl_a = lvl.endswith("_level_a_unresolved")
            batch_t2_metadata_only[cell["cell_id"]] = {
                "adp_tls_level_binding": {
                    "level_id": lvl,
                    "common_non_adp_strategy": ["individual_sites"],
                    "refine_strategy": ["individual_sites", "individual_adp"],
                    "adp_anisotropic_selection": "not water and not element H",
                    "adp_isotropic_selection": "water",
                    "unrequested_aniso_macromol": (False if is_lvl_a else True),
                },
                "shared_ligand_cifs": [
                    {"path": "restraints/ligA.cif", "sha256": SHA_A}
                ],
                "hd_free_start_model_sha256": SHA_HD_FREE,
                "hd_audit_receipt": copy.deepcopy(VALID_HD_RECEIPT),
            }
        with self.assertRaises(ValueError):
            p2.validate_factorial_bindings_batch(t2_cells, batch_t2_metadata_only)

        # Genuinely distinct operative selectors at d_min = 1.20 A pass, while
        # inconsistent unrequested_aniso_macromol within the same level still rejects
        batch_t2_distinct = copy.deepcopy(batch_t2_metadata_only)
        for cell in t2_cells:
            lvl = str(cell["factors"]["adp_tls_mode"])
            if lvl.endswith("_level_b_unresolved"):
                batch_t2_distinct[cell["cell_id"]]["adp_tls_level_binding"] = {
                    "level_id": lvl,
                    "common_non_adp_strategy": ["individual_sites"],
                    "refine_strategy": ["individual_sites", "individual_adp", "tls"],
                    "adp_isotropic_selection": "all",
                    "tls_group_selections": ["chain A"],
                    "unrequested_aniso_macromol": True,
                }
        rendered_t2_distinct = p2.validate_factorial_bindings_batch(
            t2_cells, batch_t2_distinct
        )
        self.assertEqual(len(rendered_t2_distinct), 16)

        batch_t2_inconsistent_meta = copy.deepcopy(batch_t2_distinct)
        first_t2_cid = t2_cells[0]["cell_id"]
        batch_t2_inconsistent_meta[first_t2_cid]["adp_tls_level_binding"][  # type: ignore[index]
            "unrequested_aniso_macromol"
        ] = True
        with self.assertRaises(ValueError):
            p2.validate_factorial_bindings_batch(
                t2_cells, batch_t2_inconsistent_meta
            )

    def test_sub_0p90_water_selection_audit_declaration_and_counterexamples(self) -> None:
        prof_085 = p2.fixed_profile(0.85, "Arm 3b-refine-only")
        aniso_macromol = "protein and not element H and not element D"
        iso_water = "water"
        aniso_with_water = "(protein or water) and not element H and not element D"
        iso_hd_only = "element H or element D"

        # 1. Original #1337 counterexample: bare sub_0p90_water_adp_mode + two selectors
        # without sub_0p90_water_selection_audit is rejected for both modes
        for bare_mode in ("isotropic", "anisotropic"):
            with self.subTest(bare_mode=bare_mode):
                with self.assertRaisesRegex(
                    ValueError, "sub_0p90_water_selection_audit"
                ):
                    p2.render_eff(
                        prof_085,
                        {
                            "sub_0p90_water_adp_mode": bare_mode,
                            "adp_anisotropic_selection": aniso_macromol,
                            "adp_isotropic_selection": iso_water,
                        },
                    )

        # 2. Contradictory declared mode vs routing counts (#1337 Case 3 reproduction):
        # declaring anisotropic water mode while routing all 120 water atoms isotropic
        # (or declaring isotropic mode while routing all 120 water atoms anisotropic) rejects
        with self.assertRaisesRegex(ValueError, "sub_0p90_water_adp_mode='anisotropic'"):
            p2.render_eff(
                prof_085,
                {
                    "sub_0p90_water_adp_mode": "anisotropic",
                    "adp_anisotropic_selection": aniso_macromol,
                    "adp_isotropic_selection": iso_water,
                    "sub_0p90_water_selection_audit": {
                        "refinement_input_model_sha256": SHA_A,
                        "audit_receipt_sha256": SHA_B,
                        "adp_isotropic_selection": iso_water,
                        "adp_anisotropic_selection": aniso_macromol,
                        "total": 120,
                        "isotropic": 120,
                        "anisotropic": 0,
                        "neither": 0,
                        "both": 0,
                    },
                },
            )
        with self.assertRaisesRegex(ValueError, "sub_0p90_water_adp_mode='isotropic'"):
            p2.render_eff(
                prof_085,
                {
                    "sub_0p90_water_adp_mode": "isotropic",
                    "adp_anisotropic_selection": aniso_with_water,
                    "adp_isotropic_selection": iso_hd_only,
                    "sub_0p90_water_selection_audit": {
                        "refinement_input_model_sha256": SHA_A,
                        "audit_receipt_sha256": SHA_B,
                        "adp_isotropic_selection": iso_hd_only,
                        "adp_anisotropic_selection": aniso_with_water,
                        "total": 120,
                        "isotropic": 0,
                        "anisotropic": 120,
                        "neither": 0,
                        "both": 0,
                    },
                },
            )

        # 3. Consistent synthetic declarations for isotropic and anisotropic modes render
        # with explicit unverified labels and produce distinct executable selectors
        rendered_iso = p2.render_eff(
            prof_085,
            {
                "sub_0p90_water_adp_mode": "isotropic",
                "adp_anisotropic_selection": aniso_macromol,
                "adp_isotropic_selection": iso_water,
                "sub_0p90_water_selection_audit": {
                    "refinement_input_model_sha256": SHA_A,
                    "audit_receipt_sha256": SHA_B,
                    "adp_isotropic_selection": iso_water,
                    "adp_anisotropic_selection": aniso_macromol,
                    "water_atom_count_total": 120,
                    "water_atom_count_isotropic": 120,
                    "water_atom_count_anisotropic": 0,
                    "water_atom_count_neither": 0,
                    "water_atom_count_both": 0,
                },
            },
        )
        rendered_aniso = p2.render_eff(
            prof_085,
            {
                "sub_0p90_water_adp_mode": "anisotropic",
                "adp_anisotropic_selection": aniso_with_water,
                "adp_isotropic_selection": iso_hd_only,
                "sub_0p90_water_selection_audit": {
                    "refinement_input_model_sha256": SHA_A,
                    "audit_receipt_sha256": SHA_B,
                    "adp_isotropic_selection": iso_hd_only,
                    "adp_anisotropic_selection": aniso_with_water,
                    "total": 120,
                    "isotropic": 0,
                    "anisotropic": 120,
                    "neither": 0,
                    "both": 0,
                },
            },
        )
        for bundle in (rendered_iso, rendered_aniso):
            self.assertTrue(bundle.is_complete)
            self.assertIn(
                "(unresolved Stage 2 dev-set choice; supplied-declaration consistency only, "
                "not verified coordinate contents or native behavior)",
                bundle.refine_eff,
            )
            self.assertIn(
                "applicability=declared_water_routing_consistent_unverified "
                "(supplied-declaration consistency only; not verified coordinate contents or native behavior)",
                bundle.refine_eff,
            )
        self.assertNotEqual(
            p2._non_comment_phil_lines(rendered_iso.refine_eff),
            p2._non_comment_phil_lines(rendered_aniso.refine_eff),
        )

        # 4. Zero-water declaration records explicit no-water applicability (never observed contrast)
        rendered_zero_water = p2.render_eff(
            prof_085,
            {
                "sub_0p90_water_adp_mode": "isotropic",
                "adp_anisotropic_selection": aniso_macromol,
                "adp_isotropic_selection": iso_water,
                "sub_0p90_water_selection_audit": {
                    "refinement_input_model_sha256": SHA_A,
                    "audit_receipt_sha256": SHA_B,
                    "adp_isotropic_selection": iso_water,
                    "adp_anisotropic_selection": aniso_macromol,
                    "total": 0,
                    "isotropic": 0,
                    "anisotropic": 0,
                    "neither": 0,
                    "both": 0,
                },
            },
        )
        self.assertIn(
            "applicability=explicit_no_water_applicability_not_observed_contrast",
            rendered_zero_water.refine_eff,
        )

        # 5. Reject mismatched receipt selectors, nonzero neither/both, non-summing counts,
        # bool/negative/float/string counts, and malformed digests
        base_valid_audit = {
            "refinement_input_model_sha256": SHA_A,
            "audit_receipt_sha256": SHA_B,
            "adp_isotropic_selection": iso_water,
            "adp_anisotropic_selection": aniso_macromol,
            "total": 120,
            "isotropic": 120,
            "anisotropic": 0,
            "neither": 0,
            "both": 0,
        }
        bad_audits = [
            {**base_valid_audit, "adp_isotropic_selection": "chain W"},
            {**base_valid_audit, "adp_anisotropic_selection": "not water"},
            {**base_valid_audit, "neither": 1, "total": 121},
            {**base_valid_audit, "both": 1, "total": 121},
            {**base_valid_audit, "total": 125},
            {**base_valid_audit, "isotropic": 60, "anisotropic": 60},
            {**base_valid_audit, "total": True, "isotropic": True},
            {**base_valid_audit, "neither": False},
            {**base_valid_audit, "total": -1, "isotropic": -1},
            {**base_valid_audit, "total": "120", "isotropic": 120},
            {**base_valid_audit, "total": 120.0, "isotropic": 120},
            {**base_valid_audit, "refinement_input_model_sha256": "bad_sha"},
            {**base_valid_audit, "audit_receipt_sha256": "A" * 64},
        ]
        for idx, bad_audit in enumerate(bad_audits):
            with self.subTest(bad_audit_idx=idx):
                with self.assertRaises(ValueError):
                    p2.render_eff(
                        prof_085,
                        {
                            "sub_0p90_water_adp_mode": "isotropic",
                            "adp_anisotropic_selection": aniso_macromol,
                            "adp_isotropic_selection": iso_water,
                            "sub_0p90_water_selection_audit": bad_audit,
                        },
                    )

        # 6. Fixed profiles at d_min >= 0.90 A remain unchanged
        for d_ge_090 in (0.90, 0.95, 1.25):
            with self.subTest(d_ge_090=d_ge_090):
                prof_ge = p2.fixed_profile(d_ge_090, "Arm 3b-refine-only")
                self.assertNotIn(
                    "sub_0p90_water_selection_audit", prof_ge["required_bindings"]
                )
                r_ge = p2.render_eff(
                    prof_ge,
                    {
                        "adp_anisotropic_selection": aniso_macromol,
                        "adp_isotropic_selection": iso_water,
                    },
                )
                self.assertTrue(r_ge.is_complete)

    def test_rejects_identical_and_whitespace_aliased_iso_aniso_adp_selections_1410(
        self,
    ) -> None:
        # 1. Exact #1410 fixed-profile reproducer and T1/T2 coverage across arms
        for d_min in (0.90, 0.95, 1.10, 1.20, 1.49):
            for arm in ("3b-refine-only", "3b-plus-readyset"):
                prof = p2.fixed_profile(d_min, arm)
                for iso_sel, aniso_sel in (
                    ("all", "all"),
                    ("protein and not element H", "protein and not element H"),
                    ("name ' C  '", "name ' C  '"),
                ):
                    with self.subTest(
                        route="fixed_profile_exact_equal",
                        d_min=d_min,
                        arm=arm,
                        iso_sel=iso_sel,
                        aniso_sel=aniso_sel,
                    ):
                        with self.assertRaisesRegex(
                            ValueError, "cannot be identical"
                        ):
                            p2.render_eff(
                                prof,
                                {
                                    "adp_isotropic_selection": iso_sel,
                                    "adp_anisotropic_selection": aniso_sel,
                                },
                            )
                for iso_ws, aniso_ws in (
                    ("all", " all "),
                    (" all", "all"),
                    ("all ", "all"),
                ):
                    with self.subTest(
                        route="fixed_profile_leading_trailing_ws",
                        d_min=d_min,
                        arm=arm,
                        iso_ws=iso_ws,
                        aniso_ws=aniso_ws,
                    ):
                        with self.assertRaises(ValueError):
                            p2.render_eff(
                                prof,
                                {
                                    "adp_isotropic_selection": iso_ws,
                                    "adp_anisotropic_selection": aniso_ws,
                                },
                            )

        # Sub-0.90 A fixed profile also rejects identical selectors
        prof_085 = p2.fixed_profile(0.85, "3b-refine-only")
        for sub_iso, sub_aniso in (
            ("all", "all"),
            ("name ' C  '", "name ' C  '"),
        ):
            with self.subTest(route="fixed_profile_sub_0p90", sub_iso=sub_iso):
                with self.assertRaisesRegex(ValueError, "cannot be identical"):
                    p2.render_eff(
                        prof_085,
                        {
                            "sub_0p90_water_adp_mode": "isotropic",
                            "adp_isotropic_selection": sub_iso,
                            "adp_anisotropic_selection": sub_aniso,
                            "sub_0p90_water_selection_audit": {
                                "refinement_input_model_sha256": SHA_A,
                                "audit_receipt_sha256": SHA_B,
                                "adp_isotropic_selection": sub_iso,
                                "adp_anisotropic_selection": sub_aniso,
                                "total": 10,
                                "isotropic": 10,
                                "anisotropic": 0,
                                "neither": 0,
                                "both": 0,
                            },
                        },
                    )

        # 2. Factorial cell, normalize_adp_tls_binding_signature, and batch validator
        f_cells_120 = p2.factorial_cells(1.20)
        f_cell_0 = f_cells_120[0]
        f_lvl_0 = str(f_cell_0["factors"]["adp_tls_mode"])
        for bad_iso, bad_aniso in (
            ("all", "all"),
            ("name ' C  '", "name ' C  '"),
            ("all", " all "),
            (" all", "all"),
        ):
            with self.subTest(
                route="factorial_single_and_signature",
                bad_iso=bad_iso,
                bad_aniso=bad_aniso,
            ):
                bad_adp_binding = {
                    "level_id": f_lvl_0,
                    "common_non_adp_strategy": ["individual_sites"],
                    "refine_strategy": ["individual_sites", "individual_adp"],
                    "adp_isotropic_selection": bad_iso,
                    "adp_anisotropic_selection": bad_aniso,
                }
                with self.assertRaises(ValueError):
                    p2.render_eff(
                        f_cell_0,
                        {
                            "adp_tls_level_binding": bad_adp_binding,
                            "shared_ligand_cifs": [],
                            "hd_free_start_model_sha256": SHA_HD_FREE,
                            "hd_audit_receipt": copy.deepcopy(VALID_HD_RECEIPT),
                        },
                    )
                with self.assertRaises(ValueError):
                    p2.normalize_adp_tls_binding_signature(
                        bad_adp_binding,
                        tier_id="T2",
                        d_min=1.20,
                        expected_level_id=f_lvl_0,
                    )

        bad_batch_120: dict[str, dict[str, object]] = {}
        for cell in f_cells_120:
            lvl = str(cell["factors"]["adp_tls_mode"])
            is_lvl_a = lvl.endswith("_level_a_unresolved")
            bad_batch_120[cell["cell_id"]] = {
                "adp_tls_level_binding": (
                    {
                        "level_id": lvl,
                        "common_non_adp_strategy": ["individual_sites"],
                        "refine_strategy": ["individual_sites", "individual_adp"],
                        "adp_isotropic_selection": "all",
                        "adp_anisotropic_selection": "all",
                    }
                    if is_lvl_a
                    else {
                        "level_id": lvl,
                        "common_non_adp_strategy": ["individual_sites"],
                        "refine_strategy": ["individual_sites", "individual_adp", "tls"],
                        "adp_isotropic_selection": "all",
                        "tls_group_selections": ["chain A"],
                    }
                ),
                "shared_ligand_cifs": [],
                "hd_free_start_model_sha256": SHA_HD_FREE,
                "hd_audit_receipt": copy.deepcopy(VALID_HD_RECEIPT),
            }
        with self.assertRaisesRegex(ValueError, "cannot be identical"):
            p2.validate_factorial_bindings_batch(f_cells_120, bad_batch_120)

        # 3. Sensitivity cells (S2, S3_c_beta_restraints, S3_nonbonded_weight, S4)
        sens_120 = p2.sensitivity_cells(1.20)
        for grp in (
            "S2_restraints_library_cdl",
            "S3_c_beta_restraints",
            "S3_nonbonded_weight",
        ):
            grp_cell = [c for c in sens_120 if c["comparison_group"] == grp][0]
            for bad_iso, bad_aniso in (
                ("all", "all"),
                ("name ' C  '", "name ' C  '"),
                ("all", " all "),
            ):
                with self.subTest(
                    route="sensitivity_120",
                    grp=grp,
                    bad_iso=bad_iso,
                    bad_aniso=bad_aniso,
                ):
                    bad_sens_binding = {
                        "adp_tls_level_binding": {
                            "common_non_adp_strategy": ["individual_sites"],
                            "refine_strategy": ["individual_sites", "individual_adp"],
                            "adp_isotropic_selection": bad_iso,
                            "adp_anisotropic_selection": bad_aniso,
                        }
                    }
                    with self.assertRaises(ValueError):
                        p2.render_eff(grp_cell, bad_sens_binding)
                    with self.assertRaises(ValueError):
                        p2.render_sensitivity_comparison(1.20, grp, bad_sens_binding)

        s4_cell = [
            c for c in p2.sensitivity_cells(3.10) if c["arm_family"] == "S4"
        ][0]
        bad_s4_binding = {
            "adp_tls_level_binding": {
                "common_non_adp_strategy": ["individual_sites"],
                "refine_strategy": ["individual_sites", "individual_adp", "tls"],
                "adp_isotropic_selection": "all",
                "adp_anisotropic_selection": "all",
                "tls_group_selections": ["chain A"],
                "unrequested_aniso_macromol": False,
            },
            "t4_weight_optimization_policy": {
                "optimize_xyz_weight": False,
                "optimize_adp_weight": False,
                "force_optimize_weights": False,
            },
        }
        with self.assertRaisesRegex(ValueError, "cannot be identical"):
            p2.render_eff(s4_cell, bad_s4_binding)
        with self.assertRaisesRegex(ValueError, "cannot be identical"):
            p2.render_sensitivity_comparison(3.10, "S4", bad_s4_binding)

        # 4. Valid distinct selectors (including distinct single-quoted atom-name whitespace
        # preserved by iotbx/pdb/atom_selection.py:54-74) continue to pass across all routes
        for valid_iso, valid_aniso in (
            ("water", "not water and not element H"),
            ("name ' C  '", "name ' C '"),
        ):
            with self.subTest(
                route="valid_distinct_selectors",
                valid_iso=valid_iso,
                valid_aniso=valid_aniso,
            ):
                valid_fixed = p2.render_eff(
                    p2.fixed_profile(1.20, "3b-refine-only"),
                    {
                        "adp_anisotropic_selection": valid_aniso,
                        "adp_isotropic_selection": valid_iso,
                    },
                )
                self.assertTrue(valid_fixed.is_complete)
                self.assertIn(
                    f'refinement.refine.adp.individual.anisotropic = "{valid_aniso}"',
                    valid_fixed.refine_eff,
                )
                self.assertIn(
                    f'refinement.refine.adp.individual.isotropic = "{valid_iso}"',
                    valid_fixed.refine_eff,
                )

                valid_sub_085 = p2.render_eff(
                    prof_085,
                    {
                        "sub_0p90_water_adp_mode": "isotropic",
                        "adp_anisotropic_selection": valid_aniso,
                        "adp_isotropic_selection": valid_iso,
                        "sub_0p90_water_selection_audit": {
                            "refinement_input_model_sha256": SHA_A,
                            "audit_receipt_sha256": SHA_B,
                            "adp_isotropic_selection": valid_iso,
                            "adp_anisotropic_selection": valid_aniso,
                            "total": 10,
                            "isotropic": 10,
                            "anisotropic": 0,
                            "neither": 0,
                            "both": 0,
                        },
                    },
                )
                self.assertTrue(valid_sub_085.is_complete)
                self.assertIn(
                    f'refinement.refine.adp.individual.anisotropic = "{valid_aniso}"',
                    valid_sub_085.refine_eff,
                )
                self.assertIn(
                    f'refinement.refine.adp.individual.isotropic = "{valid_iso}"',
                    valid_sub_085.refine_eff,
                )

                valid_fact = p2.render_eff(
                    f_cell_0,
                    {
                        "adp_tls_level_binding": {
                            "level_id": f_lvl_0,
                            "common_non_adp_strategy": ["individual_sites"],
                            "refine_strategy": ["individual_sites", "individual_adp"],
                            "adp_anisotropic_selection": valid_aniso,
                            "adp_isotropic_selection": valid_iso,
                        },
                        "shared_ligand_cifs": [],
                        "hd_free_start_model_sha256": SHA_HD_FREE,
                        "hd_audit_receipt": copy.deepcopy(VALID_HD_RECEIPT),
                    },
                )
                self.assertTrue(valid_fact.is_complete)
                self.assertIn(
                    f'refinement.refine.adp.individual.anisotropic = "{valid_aniso}"',
                    valid_fact.refine_eff,
                )
                self.assertIn(
                    f'refinement.refine.adp.individual.isotropic = "{valid_iso}"',
                    valid_fact.refine_eff,
                )

                valid_s2_comp = p2.render_sensitivity_comparison(
                    1.20,
                    "S2",
                    {
                        "adp_tls_level_binding": {
                            "common_non_adp_strategy": ["individual_sites"],
                            "refine_strategy": ["individual_sites", "individual_adp"],
                            "adp_anisotropic_selection": valid_aniso,
                            "adp_isotropic_selection": valid_iso,
                        }
                    },
                )
                self.assertEqual(len(valid_s2_comp), 2)
                for bundle in valid_s2_comp.values():
                    self.assertTrue(bundle.is_complete)
                    self.assertTrue(bundle.comparison_one_factor_verified)
                    self.assertIn(
                        f'refinement.refine.adp.individual.anisotropic = "{valid_aniso}"',
                        bundle.refine_eff,
                    )
                    self.assertIn(
                        f'refinement.refine.adp.individual.isotropic = "{valid_iso}"',
                        bundle.refine_eff,
                    )


if __name__ == "__main__":
    unittest.main()
