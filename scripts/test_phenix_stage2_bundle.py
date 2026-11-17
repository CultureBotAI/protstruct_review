#!/usr/bin/env python3
"""Integration tests for the result-free Stage 2 PHENIX bundle and cross-module contracts.

Runs hermetically under the repository Python environment with zero PHENIX/CCP4/Gemmi
execution, zero vendor library or directory access, and zero network calls.
"""

from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from typing import Any
import unittest

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import build_phenix_stage2_bundle as b2b  # noqa: E402
import phenix_stage2_manifest as p2m  # noqa: E402
import phenix_stage2_profiles as p2p  # noqa: E402
import phenix_stage2_selector as p2s  # noqa: E402

try:
    from strict_yaml import strict_yaml_load
except ModuleNotFoundError:  # pragma: no cover
    from scripts.strict_yaml import strict_yaml_load


EXPECTED_APPROVED_NOTE_SHA256 = (
    "14bbb0c9dc1883c2404f40193e135a4aaa974d8ab605fe95bb78d44c6a704a7b"
)
EXPECTED_LANGCHAIN_WITNESS_SHA256 = (
    "692a0b4e082ac5f56622ca6c61b457120efa00542545c12e1672f66c01c9ec0f"
)
EXPECTED_FLAG_WITNESS_SHA256 = (
    "68a5f2aec79d85bbb68f8a21dd8a66894508b6645a7326dd9e08bfa5b6575d13"
)
EXPECTED_HISTORICAL_OPERATION_MANIFEST_RELPATH = (
    "data/coscientists/openscientist/"
    "retained_1sar_pr1007_R4_rfactors_attempt04/refmac/refmac_operation_manifest.json"
)
EXPECTED_HISTORICAL_OPERATION_MANIFEST_SHA256 = (
    "f0a6736e37aa6d0594ec45864e2daf2ed7cc2aaadd6fe8bbc2b55268caf9c6bd"
)

SYNTHETIC_READOUT_CONTRACT: dict[str, dict[str, str]] = {
    "r_work": {
        "producer_id": "synthetic_gemmi_rfactor_work_fit_v1",
        "readout_id": "T03_r_work_bin_scaled_synthetic",
        "unit": "fraction",
        "source_receipt_id": "synthetic_receipt_work_v1",
    },
    "llg_work": {
        "producer_id": "synthetic_phenix_refine_work_llg_v1",
        "readout_id": "work_llg_readout_synthetic",
        "unit": "llg_units",
        "source_receipt_id": "synthetic_receipt_work_v1",
    },
    "molprobity_score": {
        "producer_id": "synthetic_molprobity_reduce_probe_v1",
        "readout_id": "T05_molprobity_composite_synthetic",
        "unit": "score",
        "source_receipt_id": "synthetic_receipt_work_v1",
    },
    "bond_rmsz": {
        "producer_id": "synthetic_gemmi_rmsz_clibd_mon_v1",
        "readout_id": "T05_bond_rmsz_synthetic",
        "unit": "rmsz",
        "source_receipt_id": "synthetic_receipt_work_v1",
    },
    "angle_rmsz": {
        "producer_id": "synthetic_gemmi_rmsz_clibd_mon_v1",
        "readout_id": "T05_angle_rmsz_synthetic",
        "unit": "rmsz",
        "source_receipt_id": "synthetic_receipt_work_v1",
    },
    "clashscore": {
        "producer_id": "synthetic_molprobity_reduce_probe_v1",
        "readout_id": "T05_clashscore_synthetic",
        "unit": "clashes_per_1000_atoms",
        "source_receipt_id": "synthetic_receipt_work_v1",
    },
    "rama_out_percent": {
        "producer_id": "synthetic_molprobity_ramalyze_v1",
        "readout_id": "T05_ramachandran_outliers_pct_synthetic",
        "unit": "percent",
        "source_receipt_id": "synthetic_receipt_work_v1",
    },
}


def _sha256_tag(tag: str) -> str:
    return hashlib.sha256(tag.encode("utf-8")).hexdigest()


def _make_synthetic_metric(
    metric_name: str,
    value: float,
    *,
    subject_sha256: str,
    contract: dict[str, dict[str, str]] = SYNTHETIC_READOUT_CONTRACT,
) -> dict[str, Any]:
    spec = contract[metric_name]
    return {
        "value": value,
        "unit": spec["unit"],
        "producer_id": spec["producer_id"],
        "readout_id": spec["readout_id"],
        "input_subject_sha256": subject_sha256,
        "source_receipt_id": spec["source_receipt_id"],
    }


def _make_synthetic_start_record(
    *, contract: dict[str, dict[str, str]] = SYNTHETIC_READOUT_CONTRACT
) -> dict[str, Any]:
    start_sha = _sha256_tag("synthetic_start_model")
    domain_sha = _sha256_tag("synthetic_work_domain")
    return {
        "record_type": "starting_geometry_v1",
        "subject_id": "synth_target_01_start",
        "target_id": "synth_target_01",
        "work_reflection_domain_sha256": domain_sha,
        "start_model_sha256": start_sha,
        "metrics": {
            "bond_rmsz": _make_synthetic_metric(
                "bond_rmsz", 0.60, subject_sha256=start_sha, contract=contract
            ),
            "angle_rmsz": _make_synthetic_metric(
                "angle_rmsz", 0.80, subject_sha256=start_sha, contract=contract
            ),
            "clashscore": _make_synthetic_metric(
                "clashscore", 6.0, subject_sha256=start_sha, contract=contract
            ),
            "rama_out_percent": _make_synthetic_metric(
                "rama_out_percent", 0.20, subject_sha256=start_sha, contract=contract
            ),
            "r_work": _make_synthetic_metric(
                "r_work", 0.2100, subject_sha256=start_sha, contract=contract
            ),
            "llg_work": _make_synthetic_metric(
                "llg_work", 1000.0, subject_sha256=start_sha, contract=contract
            ),
            "molprobity_score": _make_synthetic_metric(
                "molprobity_score", 1.60, subject_sha256=start_sha, contract=contract
            ),
        },
    }


def _make_synthetic_candidate_record(
    move_id: str,
    move_index: int,
    *,
    r_work: float,
    llg_work: float,
    molprobity_score: float,
    clashscore: float,
    contract: dict[str, dict[str, str]] = SYNTHETIC_READOUT_CONTRACT,
) -> dict[str, Any]:
    cand_sha = _sha256_tag(f"synthetic_candidate:{move_id}:{move_index}")
    domain_sha = _sha256_tag("synthetic_work_domain")
    return {
        "record_type": "candidate_selection_v1",
        "move_id": move_id,
        "move_index": move_index,
        "status": p2s.COMPLETED_COMMENSURABLE_STATUS,
        "subject_id": "synth_target_01_start",
        "target_id": "synth_target_01",
        "work_reflection_domain_sha256": domain_sha,
        "candidate_model_sha256": cand_sha,
        "metrics": {
            "r_work": _make_synthetic_metric(
                "r_work", r_work, subject_sha256=cand_sha, contract=contract
            ),
            "llg_work": _make_synthetic_metric(
                "llg_work", llg_work, subject_sha256=cand_sha, contract=contract
            ),
            "molprobity_score": _make_synthetic_metric(
                "molprobity_score",
                molprobity_score,
                subject_sha256=cand_sha,
                contract=contract,
            ),
            "bond_rmsz": _make_synthetic_metric(
                "bond_rmsz", 0.70, subject_sha256=cand_sha, contract=contract
            ),
            "angle_rmsz": _make_synthetic_metric(
                "angle_rmsz", 0.95, subject_sha256=cand_sha, contract=contract
            ),
            "clashscore": _make_synthetic_metric(
                "clashscore", clashscore, subject_sha256=cand_sha, contract=contract
            ),
            "rama_out_percent": _make_synthetic_metric(
                "rama_out_percent", 0.40, subject_sha256=cand_sha, contract=contract
            ),
        },
    }


def _make_synthetic_trajectory(
    *, contract: dict[str, dict[str, str]] = SYNTHETIC_READOUT_CONTRACT
) -> dict[str, Any]:
    start_rec = _make_synthetic_start_record(contract=contract)
    start_red = p2s.redact_starting_geometry_for_selection(
        start_rec, readout_contract=contract
    )
    cand_rec = _make_synthetic_candidate_record(
        "move_01",
        1,
        r_work=0.1980,
        llg_work=1250.0,
        molprobity_score=1.35,
        clashscore=5.2,
        contract=contract,
    )
    cand_red = p2s.redact_candidate_for_selection(
        cand_rec, readout_contract=contract
    )

    prim_txt = (
        "phenix.refine model.pdb data.mtz "
        "xray_data.r_free_flags.generate=False "
        "main.number_of_macro_cycles=5 "
        'output.prefix="move_01_prim"'
    )
    back_txt = (
        "phenix.refine model.pdb data.mtz "
        "xray_data.r_free_flags.generate=False "
        "main.number_of_macro_cycles=5 "
        'output.prefix="move_01_back"'
    )
    act_txt = (
        "phenix.refine model.pdb data.mtz "
        "xray_data.r_free_flags.generate=False "
        "main.number_of_macro_cycles=5 "
        'output.prefix="move_01_act"'
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
        "    number_of_macro_cycles = 5\n"
        "  }\n"
        '  output.prefix = "move_01_act"\n'
        "}\n"
    )
    prov = {
        "primary_command": prim_txt,
        "primary_command_sha256": _sha256_tag(prim_txt),
        "mechanical_backup": back_txt,
        "mechanical_backup_sha256": _sha256_tag(back_txt),
        "actual_command": act_txt,
        "actual_command_sha256": _sha256_tag(act_txt),
        "effective_eff": eff_txt,
        "effective_eff_sha256": _sha256_tag(eff_txt),
    }

    flag_sha = _sha256_tag("synth_flag_partition")
    sleep_sha = _sha256_tag("synth_sleep_partition")
    snap_sha = _sha256_tag("synth_snapshot_binding")

    move_entry = copy.deepcopy(cand_rec)
    move_entry.update(
        {
            "flag_partition_sha256": flag_sha,
            "sleep_partition_sha256": sleep_sha,
            "snapshot_binding_sha256": snap_sha,
            "flag_guard_verified": True,
            "actual_command_sha256": prov["actual_command_sha256"],
            "effective_eff_sha256": prov["effective_eff_sha256"],
            "claimed_redacted_view_sha256": cand_red["redacted_view_sha256"],
        }
    )

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
            **prov,
        }
    ]

    return {
        "arm": "1b",
        "target_id": "synth_target_01",
        "subject_id": "synth_target_01_start",
        "start_model_sha256": start_rec["start_model_sha256"],
        "work_reflection_domain_sha256": start_rec["work_reflection_domain_sha256"],
        "flag_partition_sha256": flag_sha,
        "sleep_partition_sha256": sleep_sha,
        "snapshot_binding_sha256": snap_sha,
        "tie_group_policy": "anchored_at_min_r_work",
        "residual_tie_policy": "unresolved_tie",
        "reference_convention": "previous_move",
        "start_record": start_rec,
        "claimed_start_redacted_view_sha256": start_red["redacted_view_sha256"],
        "moves": [move_entry],
        "budget_ledger": budget_ledger,
        "claimed_selection": {
            "selection_state": "selected_unique",
            "selected_move_id": "move_01",
            "tied_move_ids": ("move_01",),
        },
        "claimed_stop_decision": {
            "should_stop": False,
            "stagnation_triggered": False,
            "budget_cap_exhausted": False,
        },
        "require_compliant_completion": True,
    }


class TestPhenixStage2BundleIntegration(unittest.TestCase):
    """Integration tests for build_phenix_stage2_bundle and Stage 2 package invariants."""

    def test_regenerate_into_disposable_dir_matches_committed_bundle_exactly(
        self,
    ) -> None:
        committed_dir = REPO_ROOT / b2b.DEFAULT_OUTPUT_RELPATH
        self.assertTrue(
            committed_dir.is_dir(),
            f"Committed Stage 2 bundle directory missing: {committed_dir}",
        )

        # Verify committed bundle directly via CLI --check and API
        self.assertEqual(
            b2b.main(["--check", "--output-dir", str(committed_dir)]), 0
        )
        committed_manifest = b2b.verify_stage2_bundle(
            committed_dir, repo_root=REPO_ROOT
        )

        with tempfile.TemporaryDirectory() as tmp:
            regen_dir = Path(tmp) / "stage2_regen"
            rc_gen = b2b.main(["--output-dir", str(regen_dir)])
            self.assertEqual(rc_gen, 0)
            rc_chk = b2b.main(["--check", "--output-dir", str(regen_dir)])
            self.assertEqual(rc_chk, 0)

            committed_files = sorted(p.name for p in committed_dir.iterdir())
            regen_files = sorted(p.name for p in regen_dir.iterdir())
            self.assertEqual(len(regen_files), 22)
            self.assertEqual(committed_files, regen_files)

            for fname in regen_files:
                with self.subTest(file=fname):
                    c_bytes = (committed_dir / fname).read_bytes()
                    r_bytes = (regen_dir / fname).read_bytes()
                    self.assertEqual(c_bytes, r_bytes)

        self.assertEqual(
            committed_manifest["registration_status"], "selected_decisions_recorded"
        )
        self.assertFalse(committed_manifest["development_frozen"])
        self.assertFalse(committed_manifest["execution_authorized"])
        self.assertFalse(committed_manifest["frozen_result_free"])
        self.assertFalse(committed_manifest["outcomes_included"])
        self.assertFalse(committed_manifest["pass_criterion_bindings_modified"])

    def test_verify_stage2_bundle_fails_on_missing_extra_stale_or_source_pin_mutations(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bdir = Path(tmp) / "bundle"
            b2b.write_stage2_bundle(bdir, repo_root=REPO_ROOT)

            # 1. Missing file fails closed
            target_eff = bdir / "fixed_T1_0p89A_3b_refine_only_refine.eff.in"
            saved_bytes = target_eff.read_bytes()
            target_eff.unlink()
            with self.assertRaisesRegex(ValueError, "missing required files"):
                b2b.verify_stage2_bundle(bdir, repo_root=REPO_ROOT)
            target_eff.write_bytes(saved_bytes)

            # 2. Extra file fails closed in both verify_stage2_bundle and write_stage2_bundle
            extra_file = bdir / "unexpected_extra.eff.in"
            extra_file.write_text("# rogue\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unexpected extra files"):
                b2b.verify_stage2_bundle(bdir, repo_root=REPO_ROOT)
            with self.assertRaisesRegex(ValueError, "unexpected extra entries"):
                b2b.write_stage2_bundle(bdir, repo_root=REPO_ROOT)
            extra_file.unlink()

            # 3. Stale artifact bytes fail closed
            target_eff.write_bytes(saved_bytes + b"# stale comment\n")
            with self.assertRaisesRegex(ValueError, "disagrees with bundle_manifest"):
                b2b.verify_stage2_bundle(bdir, repo_root=REPO_ROOT)
            target_eff.write_bytes(saved_bytes)

            # 4. Mutated source_pins (even with recomputed manifest_sha256) fail closed
            manifest_path = bdir / b2b.BUNDLE_MANIFEST_FILENAME
            orig_manifest_bytes = manifest_path.read_bytes()
            orig_manifest = json.loads(orig_manifest_bytes.decode("utf-8"))

            pin_mutations = [
                ("builder_script", ["source_pins", "builder_script", "sha256"]),
                (
                    "stage2_module_profiles",
                    [
                        "source_pins",
                        "stage2_modules",
                        "phenix_stage2_profiles",
                        "sha256",
                    ],
                ),
                (
                    "stage2_module_selector",
                    [
                        "source_pins",
                        "stage2_modules",
                        "phenix_stage2_selector",
                        "sha256",
                    ],
                ),
                (
                    "approved_policy_note",
                    ["source_pins", "approved_policy_note", "sha256"],
                ),
                (
                    "static_langchain_witness",
                    [
                        "source_pins",
                        "static_witnesses",
                        "phenix_langchain_static_witness",
                        "sha256",
                    ],
                ),
            ]
            for label, key_path in pin_mutations:
                with self.subTest(pin_mutation=label):
                    mut_doc = copy.deepcopy(orig_manifest)
                    cursor: Any = mut_doc
                    for key in key_path[:-1]:
                        cursor = cursor[key]
                    cursor[key_path[-1]] = "f" * 64
                    mut_without_self = {
                        k: v for k, v in mut_doc.items() if k != "manifest_sha256"
                    }
                    mut_doc["manifest_sha256"] = p2m.canonical_json_sha256(
                        mut_without_self
                    )
                    manifest_path.write_bytes(p2m.canonical_json_bytes(mut_doc))
                    with self.assertRaisesRegex(
                        ValueError, "source_pins are stale or do not match"
                    ):
                        b2b.verify_stage2_bundle(bdir, repo_root=REPO_ROOT)

            # 5. Promoted governance flags fail closed
            for flag_key in (
                "development_frozen",
                "execution_authorized",
                "frozen_result_free",
                "outcomes_included",
                "pass_criterion_bindings_modified",
            ):
                with self.subTest(promoted_flag=flag_key):
                    mut_doc = copy.deepcopy(orig_manifest)
                    mut_doc[flag_key] = True
                    mut_without_self = {
                        k: v for k, v in mut_doc.items() if k != "manifest_sha256"
                    }
                    mut_doc["manifest_sha256"] = p2m.canonical_json_sha256(
                        mut_without_self
                    )
                    manifest_path.write_bytes(p2m.canonical_json_bytes(mut_doc))
                    with self.assertRaisesRegex(
                        ValueError, f"must keep {flag_key}=False"
                    ):
                        b2b.verify_stage2_bundle(bdir, repo_root=REPO_ROOT)

            manifest_path.write_bytes(orig_manifest_bytes)
            b2b.verify_stage2_bundle(bdir, repo_root=REPO_ROOT)

    def test_fixed_profile_templates_separate_programs_incomplete_and_factorial_counts(
        self,
    ) -> None:
        payloads = b2b.build_stage2_bundle_payloads(REPO_ROOT)
        manifest = json.loads(
            payloads[b2b.BUNDLE_MANIFEST_FILENAME].decode("utf-8")
        )

        self.assertEqual(
            manifest["summary_counts"],
            {
                "synthetic_d_min_cases": 5,
                "fixed_profile_template_bundles": 10,
                "fixed_profile_eff_in_files": 15,
                "refine_eff_in_files": 10,
                "ready_set_eff_in_files": 5,
                "factorial_schedule_files": 5,
                "factorial_cell_counts_by_d_min": {
                    "0.89": 16,
                    "0.90": 16,
                    "1.10": 16,
                    "1.50": 16,
                    "2.80": 8,
                },
                "dev_exclusion_accessions": 23,
                "round2_negative_control_accessions": 22,
                "separate_1sar_accessions": 1,
                "onesar_retained_subject_count": 6,
                "governed_sibling_artifacts": 21,
                "total_bundle_files_including_manifest": 22,
            },
        )

        # Verify all 10 fixed-profile template bundles and 15 .eff.in files
        bundles = manifest["fixed_profile_template_bundles"]
        self.assertEqual(len(bundles), 10)
        for b_rec in bundles:
            self.assertFalse(b_rec["is_complete"])
            self.assertFalse(b_rec["single_cell_binding_complete"])
            self.assertFalse(b_rec["comparison_one_factor_verified"])

            spec = p2p.fixed_profile(b_rec["d_min"], b_rec["arm"])
            rendered = p2p.render_known_eff_template(spec)
            self.assertFalse(rendered.is_complete)

            ref_name = b_rec["refine_eff_path"]
            ref_text = payloads[ref_name].decode("utf-8")
            self.assertEqual(ref_text, rendered.refine_eff)
            self.assertIn("# [SCOPE: phenix.refine]", ref_text)
            self.assertNotIn("# [SCOPE: phenix.ready_set]", ref_text)
            self.assertNotIn("ready_set.actions.", ref_text)
            self.assertIn(
                "# STATUS: RESULT-FREE STAGE 2 PROSPECTIVE SPECIFICATION TEMPLATE (INCOMPLETE / UNVERIFIED)",
                ref_text,
            )
            self.assertIn(
                "# WARNING: DO NOT EXECUTE. Required Stage 2 bindings below remain unresolved.",
                ref_text,
            )
            self.assertIn("# UNRESOLVED_REQUIRED_BINDING:", ref_text)

            if b_rec["arm"] == "3b-plus-readyset":
                rs_name = b_rec["ready_set_eff_path"]
                self.assertIsNotNone(rs_name)
                rs_text = payloads[rs_name].decode("utf-8")
                self.assertEqual(rs_text, rendered.ready_set_eff)
                self.assertIn(
                    "# STATUS: RESULT-FREE STAGE 2 PROSPECTIVE SPECIFICATION TEMPLATE (INCOMPLETE / UNVERIFIED)",
                    rs_text,
                )
                self.assertIn(
                    "# WARNING: DO NOT EXECUTE. Required Stage 2 bindings below remain unresolved.",
                    rs_text,
                )
                self.assertIn("# [SCOPE: phenix.ready_set]", rs_text)
                self.assertNotIn("# [SCOPE: phenix.refine]", rs_text)
                self.assertNotIn("refinement.main.", rs_text)
                self.assertIn("ready_set.actions.hydrogens = True", rs_text)
                self.assertIn("ready_set.actions.ligands = True", rs_text)
            else:
                self.assertIsNone(b_rec["ready_set_eff_path"])
                self.assertIsNone(b_rec["ready_set_eff_sha256"])

        # Verify all 5 factorial schedule JSONs (16, 16, 16, 16, 8) and unresolved ADP bindings
        schedules = manifest["factorial_schedules"]
        self.assertEqual(len(schedules), 5)
        self.assertEqual(
            [(s["d_min_label"], s["cell_count"]) for s in schedules],
            [
                ("0.89", 16),
                ("0.90", 16),
                ("1.10", 16),
                ("1.50", 16),
                ("2.80", 8),
            ],
        )
        for s_rec in schedules:
            self.assertFalse(s_rec["adp_tls_levels_resolved"])
            sched_doc = json.loads(payloads[s_rec["relative_path"]].decode("utf-8"))
            self.assertEqual(sched_doc["cell_count"], s_rec["cell_count"])
            self.assertEqual(len(sched_doc["cells"]), s_rec["cell_count"])
            self.assertFalse(sched_doc["adp_tls_levels_resolved"])
            self.assertFalse(sched_doc["development_frozen"])
            self.assertFalse(sched_doc["execution_authorized"])
            self.assertFalse(sched_doc["frozen_result_free"])
            for cell in sched_doc["cells"]:
                self.assertFalse(cell["adp_tls_level_resolved"])
                self.assertIn(
                    cell["factors"]["adp_tls_mode"],
                    sched_doc["unresolved_adp_tls_levels"],
                )
                self.assertIn("adp_tls_level_binding", cell["required_bindings"])
                self.assertIn("shared_ligand_cifs", cell["required_bindings"])
                if cell["factors"]["ready_set_h"] == "H_riding":
                    self.assertEqual(
                        cell["preprocessing"]["phil_assignments"][
                            "ready_set.actions.hydrogens"
                        ],
                        True,
                    )
                    self.assertEqual(
                        cell["preprocessing"]["phil_assignments"][
                            "ready_set.actions.ligands"
                        ],
                        False,
                    )

    def test_dev_exclusions_23_accessions_vs_6_onesar_subjects_and_not_ready_bundles(
        self,
    ) -> None:
        payloads = b2b.build_stage2_bundle_payloads(REPO_ROOT)
        dev_doc = json.loads(payloads[b2b.DEV_EXCLUSIONS_FILENAME].decode("utf-8"))

        self.assertEqual(
            dev_doc["counts"],
            {
                "round2_negative_control_accessions": 22,
                "separate_1sar_accessions": 1,
                "total_excluded_accessions": 23,
                "onesar_retained_subject_count": 6,
            },
        )
        self.assertEqual(len(dev_doc["excluded_accessions"]), 23)
        self.assertEqual(len(set(dev_doc["excluded_accessions"])), 23)
        self.assertEqual(dev_doc["excluded_accessions"][-1], "1SAR")
        self.assertNotIn("1SAR", dev_doc["excluded_accessions"][:22])

        self.assertEqual(len(dev_doc["round2_negative_controls"]), 22)
        for row in dev_doc["round2_negative_controls"]:
            self.assertFalse(row["execution_ready_input_bundle"])
            self.assertFalse(row["local_bytes_verified"])
            self.assertEqual(row["verification_mode"], "source_attested")
            self.assertEqual(
                row["cif_role"],
                "deposited_structural_mmcif_not_ligand_restraint_cif",
            )

        self.assertNotIn("separate_1sar_exclusion", dev_doc)
        onesar = dev_doc["onesar_exclusion"]
        self.assertEqual(onesar["pdb_id"], "1SAR")
        self.assertEqual(onesar["accession_level_exclusion_count"], 1)
        self.assertFalse(onesar["execution_ready_input_bundle"])
        self.assertTrue(onesar["local_bytes_verified"])
        self.assertEqual(onesar["verification_mode"], "locally_byte_verified")
        self.assertEqual(len(onesar["retained_subjects"]), 6)
        for subj in onesar["retained_subjects"]:
            self.assertNotIn("execution_ready_input_bundle", subj)
            self.assertTrue(subj["local_bytes_verified"])
            self.assertEqual(subj["verification_mode"], "locally_byte_verified")

    def test_portable_static_provider_metadata_witness_without_vendor_access(
        self,
    ) -> None:
        witness_path = (
            REPO_ROOT
            / "ref/research/data/phenix_stage2_provider_metadata_2026-11-16.json"
        )
        raw_bytes = witness_path.read_bytes()
        raw_text = raw_bytes.decode("utf-8")

        for forbidden_token in ("/Users/", "/home/", "/opt/", "/var/", "/tmp/", "\\"):
            self.assertNotIn(forbidden_token, raw_text)

        doc = json.loads(raw_text)
        self.assertEqual(
            doc["schema"],
            "phenix_stage2_provider_metadata_witness_v1",
        )
        self.assertEqual(doc["registration_status"], "selected_decisions_recorded")
        self.assertEqual(doc["portable_prefix"], "PHENIX_PREFIX")
        self.assertEqual(
            doc["inspected_root"], "PHENIX_PREFIX/lib/python3.9/site-packages"
        )

        query_scope = doc["query_scope"]
        self.assertEqual(
            query_scope["inspected_subtree"],
            "PHENIX_PREFIX/lib/python3.9/site-packages",
        )
        self.assertFalse(query_scope["vendor_imports_executed"])
        self.assertFalse(query_scope["importlib_metadata_used"])
        self.assertFalse(query_scope["pth_files_executed"])
        self.assertFalse(query_scope["commands_executed"])
        self.assertFalse(query_scope["network_or_provider_calls"])

        self.assertEqual(
            doc["shared_dated_snapshot"],
            {
                "selected_identifier": None,
                "availability": "not_assessed",
                "runtime_binding": "not_assessed",
            },
        )
        self.assertEqual(
            doc["approved_policy_source"],
            {
                "path": "ref/research/phenix_step1_user_selections_2026-11-15.md",
                "sha256": EXPECTED_APPROVED_NOTE_SHA256,
                "section": "U12",
            },
        )
        self.assertEqual(
            doc["static_source_witness"],
            {
                "path": "ref/research/data/phenix_langchain_static_witness_2026-11-15.json",
                "sha256": EXPECTED_LANGCHAIN_WITNESS_SHA256,
                "inspected_python_file_count": 44,
            },
        )

        counts = doc["inspection_counts"]
        self.assertGreater(counts["directories_traversed"], 0)
        self.assertGreater(counts["files_traversed"], 0)
        self.assertEqual(
            counts["metadata_files_inspected"],
            counts["dist_info_metadata_files_inspected"]
            + counts["pkg_info_metadata_files_inspected"],
        )
        self.assertEqual(
            counts["matched_distribution_count"], len(doc["matched_distributions"])
        )
        self.assertEqual(counts["present_native_adapter_count"], 0)

        payload_without_self = {k: v for k, v in doc.items() if k != "witness_sha256"}
        self.assertEqual(
            doc["witness_sha256"], p2m.canonical_json_sha256(payload_without_self)
        )

    def test_approved_note_witness_hashes_historical_operation_manifest_and_empty_pass_criteria(
        self,
    ) -> None:
        note_bytes = (REPO_ROOT / b2b.APPROVED_NOTE_RELPATH).read_bytes()
        self.assertEqual(
            hashlib.sha256(note_bytes).hexdigest(), EXPECTED_APPROVED_NOTE_SHA256
        )

        lc_bytes = (
            REPO_ROOT / "ref/research/data/phenix_langchain_static_witness_2026-11-15.json"
        ).read_bytes()
        self.assertEqual(
            hashlib.sha256(lc_bytes).hexdigest(), EXPECTED_LANGCHAIN_WITNESS_SHA256
        )

        flag_bytes = (
            REPO_ROOT / "ref/research/data/phenix_stage2_flag_static_witness_2026-11-16.json"
        ).read_bytes()
        self.assertEqual(
            hashlib.sha256(flag_bytes).hexdigest(), EXPECTED_FLAG_WITNESS_SHA256
        )

        op_manifest_path = REPO_ROOT / EXPECTED_HISTORICAL_OPERATION_MANIFEST_RELPATH
        self.assertTrue(
            op_manifest_path.is_file(), f"Missing {op_manifest_path}"
        )
        self.assertEqual(
            hashlib.sha256(op_manifest_path.read_bytes()).hexdigest(),
            EXPECTED_HISTORICAL_OPERATION_MANIFEST_SHA256,
        )

        criteria_path = REPO_ROOT / "ref/structural_criteria.yaml"
        criteria_doc = strict_yaml_load(criteria_path.read_text(encoding="utf-8"))
        self.assertEqual(criteria_doc.get("pass_criterion_bindings"), [])

    def test_selector_out_of_band_readout_contract_synthetic_bindings_and_rejections(
        self,
    ) -> None:
        # 1. Valid 7-entry synthetic readout_contract passes validate_readout_contract
        validated_contract = p2s.validate_readout_contract(SYNTHETIC_READOUT_CONTRACT)
        self.assertEqual(
            set(validated_contract.keys()), set(p2s.CANDIDATE_METRIC_NAMES)
        )
        self.assertEqual(len(validated_contract), 7)

        start_rec = _make_synthetic_start_record()
        cand_rec = _make_synthetic_candidate_record(
            "move_01",
            1,
            r_work=0.1980,
            llg_work=1250.0,
            molprobity_score=1.35,
            clashscore=5.2,
        )
        traj = _make_synthetic_trajectory()

        # 2. Omitted (None) readout_contract fails closed across all selector entry points
        with self.assertRaisesRegex(ValueError, "readout_contract"):
            p2s.validate_readout_contract(None)
        with self.assertRaisesRegex(ValueError, "readout_contract"):
            p2s.geometry_eligible(cand_rec, start_rec, readout_contract=None)
        with self.assertRaisesRegex(ValueError, "readout_contract"):
            p2s.select_candidate(
                [cand_rec],
                start_rec,
                tie_group_policy="anchored_at_min_r_work",
                residual_tie_policy="unresolved_tie",
                readout_contract=None,
            )
        with self.assertRaisesRegex(ValueError, "readout_contract"):
            p2s.verify_trajectory(traj, readout_contract=None)

        # 3. Embedded trajectory["readout_contract"] cannot self-authorize when out-of-band
        #    readout_contract is omitted (None) or when it contradicts caller's readout_contract
        traj_self_auth = copy.deepcopy(traj)
        traj_self_auth["readout_contract"] = copy.deepcopy(SYNTHETIC_READOUT_CONTRACT)
        with self.assertRaisesRegex(ValueError, "readout_contract"):
            p2s.verify_trajectory(traj_self_auth, readout_contract=None)

        alt_contract = copy.deepcopy(SYNTHETIC_READOUT_CONTRACT)
        for entry in alt_contract.values():
            entry["source_receipt_id"] = "synthetic_receipt_work_v2"
        traj_alt = _make_synthetic_trajectory(contract=alt_contract)
        traj_alt["readout_contract"] = alt_contract
        with self.assertRaisesRegex(
            ValueError, "contradicts caller-bound out-of-band readout_contract"
        ):
            p2s.verify_trajectory(
                traj_alt, readout_contract=SYNTHETIC_READOUT_CONTRACT
            )

        # 4. Mismatched producer_id, readout_id, unit, or source_receipt_id fails closed
        for field_name, bad_val, expected_err in (
            ("producer_id", "wrong_producer_v9", "Readout contract mismatch"),
            ("readout_id", "wrong_readout_v9", "Readout contract mismatch"),
            ("source_receipt_id", "wrong_receipt_v9", "Readout contract mismatch"),
            ("unit", "percent", "unit must be 'fraction'"),
        ):
            with self.subTest(mismatch_field=field_name):
                bad_cand = copy.deepcopy(cand_rec)
                bad_cand["metrics"]["r_work"][field_name] = bad_val
                with self.assertRaisesRegex(ValueError, expected_err):
                    p2s.select_candidate(
                        [bad_cand],
                        start_rec,
                        tie_group_policy="anchored_at_min_r_work",
                        residual_tie_policy="unresolved_tie",
                        readout_contract=SYNTHETIC_READOUT_CONTRACT,
                    )

        # 5. Positive control with explicit caller-bound out-of-band readout_contract succeeds
        elig = p2s.geometry_eligible(
            cand_rec, start_rec, readout_contract=SYNTHETIC_READOUT_CONTRACT
        )
        self.assertTrue(elig["eligible"])
        sel = p2s.select_candidate(
            [cand_rec],
            start_rec,
            tie_group_policy="anchored_at_min_r_work",
            residual_tie_policy="unresolved_tie",
            readout_contract=SYNTHETIC_READOUT_CONTRACT,
        )
        self.assertEqual(sel["selected_move_id"], "move_01")
        verified = p2s.verify_trajectory(
            traj, readout_contract=SYNTHETIC_READOUT_CONTRACT
        )
        self.assertTrue(verified["trajectory_ok"])

    def test_builder_uses_only_stdlib_and_stage2_modules(self) -> None:
        builder_path = REPO_ROOT / "scripts/build_phenix_stage2_bundle.py"
        tree = ast.parse(builder_path.read_text(encoding="utf-8"))
        allowed_imports = {
            "__future__",
            "argparse",
            "collections",
            "collections.abc",
            "hashlib",
            "json",
            "pathlib",
            "sys",
            "typing",
            "phenix_stage2_manifest",
            "phenix_stage2_profiles",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertIn(alias.name, allowed_imports)
            elif isinstance(node, ast.ImportFrom):
                self.assertIn(node.module, allowed_imports)

    def test_regressions_1385_executing_source_identity_and_1386_destination_preflight(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # 1. #1385: Owned alternate repo_root must match actual executing/imported implementation bytes
            alt_root = tmp_path / "alt_repo"
            required_relpaths = [
                b2b.BUILDER_RELPATH,
                b2b.APPROVED_NOTE_RELPATH,
                p2m.ONESAR_ARCHIVE_PATH,
                p2m.ONESAR_DEPOSITED_PDB_PATH,
                *(rel for _, rel, _ in b2b.STAGE2_MODULE_SPECS),
                *(rel for _, rel, _, _ in b2b.STATIC_WITNESS_SPECS),
                *(rel for _, rel, _, _ in b2b.DEV_EXCLUSION_SOURCE_SPECS),
            ]
            for rel in required_relpaths:
                src_file = REPO_ROOT / rel
                dst_file = alt_root / rel
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                dst_file.write_bytes(src_file.read_bytes())

            # Identical source copy remains supported and produces identical payloads
            identical_payloads = b2b.build_stage2_bundle_payloads(repo_root=alt_root)
            canonical_payloads = b2b.build_stage2_bundle_payloads(repo_root=REPO_ROOT)
            self.assertEqual(identical_payloads, canonical_payloads)

            # Mutated profile, manifest, or builder source in alt_root must fail closed
            for mutated_rel in (
                "scripts/phenix_stage2_profiles.py",
                "scripts/phenix_stage2_manifest.py",
                "scripts/build_phenix_stage2_bundle.py",
            ):
                with self.subTest(mutated_alt_source=mutated_rel):
                    target_src = alt_root / mutated_rel
                    orig_bytes = target_src.read_bytes()
                    target_src.write_bytes(orig_bytes + b"\n# mutated source bytes\n")
                    out_try = tmp_path / f"out_{Path(mutated_rel).stem}"
                    with self.assertRaisesRegex(ValueError, "differ from"):
                        b2b.build_stage2_bundle_payloads(repo_root=alt_root)
                    with self.assertRaisesRegex(ValueError, "differ from"):
                        b2b.write_stage2_bundle(out_try, repo_root=alt_root)
                    with self.assertRaisesRegex(ValueError, "differ from"):
                        b2b.main(
                            [
                                "--repo-root",
                                str(alt_root),
                                "--output-dir",
                                str(out_try),
                            ]
                        )
                    self.assertFalse(out_try.exists())
                    target_src.write_bytes(orig_bytes)

            # 2. #1386: Dangling expected-name leaf symlink rejected before any write; outside target absent
            dangling_leaf_dir = tmp_path / "dangling_leaf_bundle"
            dangling_leaf_dir.mkdir()
            outside_target = tmp_path / "outside_owned_target.eff"
            late_leaf_name = "fixed_T4_2p80A_3b_refine_only_refine.eff.in"
            (dangling_leaf_dir / late_leaf_name).symlink_to(outside_target)
            self.assertFalse(outside_target.exists())

            with self.assertRaisesRegex(ValueError, "symlink"):
                b2b.write_stage2_bundle(dangling_leaf_dir, repo_root=REPO_ROOT)
            self.assertFalse(outside_target.exists())
            self.assertEqual(
                [p.name for p in dangling_leaf_dir.iterdir()],
                [late_leaf_name],
            )

            # 3. #1386: Dangling output-directory symlink rejected by write and verify
            outside_dir_target = tmp_path / "outside_owned_dir_target"
            dangling_out_dir = tmp_path / "dangling_out_dir"
            dangling_out_dir.symlink_to(outside_dir_target)
            with self.assertRaisesRegex(ValueError, "symlink"):
                b2b.write_stage2_bundle(dangling_out_dir, repo_root=REPO_ROOT)
            with self.assertRaisesRegex(ValueError, "non-symlink directory"):
                b2b.verify_stage2_bundle(dangling_out_dir, repo_root=REPO_ROOT)
            self.assertFalse(outside_dir_target.exists())

            # 4. #1386: Late-sorted non-regular destination rejected before any earlier file is written
            late_invalid_dir = tmp_path / "late_invalid_bundle"
            late_invalid_dir.mkdir()
            (late_invalid_dir / late_leaf_name).mkdir()
            with self.assertRaisesRegex(ValueError, "non-regular file"):
                b2b.write_stage2_bundle(late_invalid_dir, repo_root=REPO_ROOT)
            self.assertEqual(
                [p.name for p in late_invalid_dir.iterdir()],
                [late_leaf_name],
            )


if __name__ == "__main__":
    unittest.main()
