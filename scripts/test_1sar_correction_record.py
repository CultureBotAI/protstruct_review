#!/usr/bin/env python3
"""Acceptance checks for the issued 1SAR correction, not new oracle executions.

Load repository records, never the scratch authoring helpers. Exact historical
rows remain audit inputs; independent fixed-column/log arithmetic is limited to
the retained evidence helper. No scientific executables or network are invoked.
"""
from __future__ import annotations

from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
import zipfile

import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import audit_1sar_retained_evidence as retained_audit  # noqa: E402
import check_qds_trust_invariant as trust  # noqa: E402
import qds_emit  # noqa: E402
import qds_emit_contract_v4 as contract  # noqa: E402
from protstruct_review.models import Container  # noqa: E402
from strict_yaml import strict_yaml_load  # noqa: E402


BASE = Path("data/coscientists/openscientist")
OLD = "EVAL_1sar_cdba2c07_2026-04-24"
SEPTEMBER = "EVAL_1sar_cdba2c07_2026-09-07"
NEW = "EVAL_1sar_cdba2c07_2026-09-23"
DATASET_OWNER = "EVAL_1sar_cdba2c07_dataset_2026-09-23"
QDS = NEW.replace("EVAL_", "QDS_", 1)
SUBJECT = "artifact:cdba2c07-daff-4f60-ae96-12452b3a5fbb#data/1sar_final.pdb"
STARTING = SUBJECT.replace("data/1sar_final.pdb", "data/1sar.pdb")
AUDIT_PATH = BASE / "retained_evidence_2026-09-23/coordinate_and_t13_audit.json"
AUDIT_TOOL = "protstruct retained-coordinate audit"
METAL_TOOL = "protstruct local metal geometry screen"
SOURCE_HASHES = {
    "2026-04-24": "b3beb751fb99c94376002d88ccb7f8716b1dd4ae8177c40ff53b29ab12350532",
    "2026-09-07": "34973db5ae89ca5276cee44f3b5e72c3ef6256810683a20af6a24b1d2c4c3c37",
    "2026-09-21": "13b0af152c3d243e3f15b6d209b83f66509f4c4e89675f22edce91d8cc06cccd",
    "2026-09-22": "fad09acc293d69df7f488ba43e6797c82aece024fe7b4744313263f68ae96c3d",
}
# Scientific retirements are explicit acceptance expectations, not imported from
# the authoring plan or inferred from whatever operations the new file contains.
WITHDRAWN_SCALARS = frozenset({
    "M_006", "M_007", "M_008", "M_009", "M_010", "M_011",
    "M_water_count", "M_total_atoms", "M_mean_b", "M_per_residue_displacement_summary",
    "M_round7_rwork", "M_round7_rfree", "M_ca_b_vs_mean_ratio",
    "M_peak_inventory_oracle_vs_agent", "M_prosmart_global_rmsd",
    "M_prosmart_asn_a39_score", "M_ca_b_vs_protein", "M_na_b_vs_protein",
    "M_so4_b_vs_protein", "M_water_b_distribution", "M_water_rscc_distribution",
    "M_ca_identity_summary", "M_na_identity_summary",
})


def yaml_digest(value: object) -> str:
    return hashlib.sha256(yaml.safe_dump(value, sort_keys=True, allow_unicode=True).encode()).hexdigest()


def walk_dicts(value: object):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_dicts(child)


class RealCorrectionRecordTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source_paths = [REPO / BASE / f"EVAL_1sar_cdba2c07_{date}.yaml"
                            for date in SOURCE_HASHES]
        cls.source_paths.append(REPO / BASE / f"{NEW}.yaml")
        cls.documents = [strict_yaml_load(path.read_text()) for path in cls.source_paths]
        cls.carrier = cls.documents[-1]
        cls.raw_runs = {row["id"]: row for doc in cls.documents for row in doc["evaluation_runs"]}
        cls.new_runs = cls.carrier["evaluation_runs"]
        cls.new_rows = [row for run in cls.new_runs for row in run.get("measurements", [])]
        cls.operations = [row for run in cls.new_runs for row in run.get("corrections", [])]
        cls.context = cls.carrier["qds_emission_contexts"][0]
        cls.qds_path = REPO / BASE / f"{QDS}.yaml"
        cls.qds_document = strict_yaml_load(cls.qds_path.read_text())
        cls.qds = cls.qds_document["quality_data_sheets"][0]
        cls.audit = json.loads((REPO / AUDIT_PATH).read_text())
        cls.projection = contract.prepare_projection(cls.documents, QDS, "1sar", REPO)
        cls.active_rows = [row for run in cls.projection["runs"] for row in run["measurements"]]

    def test_frozen_source_bytes_are_unchanged(self) -> None:
        for date, expected in SOURCE_HASHES.items():
            with self.subTest(date=date):
                path = REPO / BASE / f"EVAL_1sar_cdba2c07_{date}.yaml"
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), expected)

    def test_real_carriers_schema_and_complete_audit_boundary(self) -> None:
        Container.model_validate(self.carrier)
        Container.model_validate(self.qds_document)
        self.assertEqual([run["id"] for run in self.new_runs], [NEW, DATASET_OWNER])
        expected_sources = [f"EVAL_1sar_cdba2c07_{date}" for date in SOURCE_HASHES] + [NEW, DATASET_OWNER]
        self.assertEqual(self.context["source_evaluation_run_refs"], expected_sources)
        self.assertEqual(self.qds["derived_from_evaluation_run_refs"], expected_sources)
        self.assertEqual(self.qds["active_evaluation_run_refs"], expected_sources[1:5])
        self.assertEqual(self.qds["emitter_contract_version"], "4")
        self.assertEqual(self.qds["coverage_scope"], "cumulative")
        self.assertEqual(self.qds["subject_ref"], SUBJECT)
        self.assertEqual(len(self.operations), 148)
        self.assertEqual(len(self.new_rows), 63)
        self.assertEqual(len(self.qds["measurement_evidence_origins"]), 63)
        self.assertEqual(len(self.qds["cross_tool_waivers"]), 11)
        self.assertEqual(len(self.qds["corrected_qds_refs"]), 9)

    def test_identity_resolution_and_space_group_match_packaged_pdb_header(self) -> None:
        with zipfile.ZipFile(REPO / self.audit["archive"]["path"]) as archive:
            lines = archive.read("data/1sar_final.pdb").decode("ascii").splitlines()
        resolution = [line for line in lines if line.startswith("REMARK   3")
                      and "RESOLUTION RANGE HIGH (ANGSTROMS)" in line]
        crystallographic = [line for line in lines if line.startswith("CRYST1")]
        self.assertEqual(len(resolution), 1)
        self.assertEqual(len(crystallographic), 1)
        expected_resolution = float(resolution[0].split(":", 1)[1])
        expected_group = crystallographic[0][55:66].strip()
        self.assertEqual((expected_resolution, expected_group), (2.5, "P 21 21 21"))
        structure = next(row for row in self.carrier["structures"] if row["id"] == "1sar")
        for record in (structure, self.qds["identity_block"]):
            self.assertIn("resolution_a", record)
            self.assertIn("space_group", record)
            self.assertEqual(record["resolution_a"], expected_resolution)
            self.assertEqual(record["space_group"], expected_group)

    def test_all_83_april_scalars_have_exact_hashed_individual_corrections(self) -> None:
        originals = {row["id"]: row for row in self.raw_runs[OLD]["measurements"]}
        operations = [row for row in self.operations if row["target_collection"] == "measurements"]
        self.assertEqual(len(originals), 83)
        self.assertEqual(len(operations), 83)
        self.assertEqual({row["target_ref"] for row in operations}, set(originals))
        self.assertEqual(Counter(row["action"] for row in operations), {"replace": 60, "withdraw": 23})
        current = {row["id"]: row for row in self.new_rows}
        for operation in operations:
            with self.subTest(target=operation["target_ref"]):
                target = operation["target_ref"]
                self.assertEqual(operation["target_evaluation_run_ref"], OLD)
                self.assertEqual(operation["target_sha256"], yaml_digest(originals[target]))
                self.assertTrue(operation["reason"])
                self.assertTrue(operation["evidence_refs"])
                expected = "withdraw" if target.removeprefix(OLD + "_") in WITHDRAWN_SCALARS else "replace"
                self.assertEqual(operation["action"], expected)
                if expected == "replace":
                    self.assertIn(operation["replacement_ref"], current)
                    self.assertNotIn(operation["replacement_ref"], originals)
                else:
                    self.assertNotIn("replacement_ref", operation)

    def test_new_scalars_and_active_values_do_not_reinstate_unsupported_grades(self) -> None:
        for row in self.new_rows:
            with self.subTest(measurement=row["id"]):
                self.assertEqual(row["pass_status"], "informational")
                for field in ("pass_criterion", "pass_criterion_ref", "criterion_preconditions",
                              "agent_claim", "delta", "delta_from_measurement_ref"):
                    self.assertNotIn(field, row)
        for row in self.active_rows:
            self.assertEqual(row["pass_status"], "informational", row["id"])
            self.assertNotIn("pass_criterion", row, row["id"])
        for value in walk_dicts(self.qds):
            if "pass_status" in value:
                self.assertEqual(value["pass_status"], "informational")
                self.assertNotIn("pass_criterion", value)

    def test_live_authoring_and_snapshot_replay_match_the_issued_sheet(self) -> None:
        before = copy.deepcopy(self.documents)
        live = qds_emit.emit_qds(self.source_paths, qds_id=QDS, structure_id="1sar")
        replayed = contract.emit_projection(self.projection)
        self.assertEqual(trust._canonical_qds_text(live), trust._canonical_qds_text(self.qds))
        self.assertEqual(trust._canonical_qds_text(replayed), trust._canonical_qds_text(self.qds))
        self.assertEqual(self.documents, before)

    def test_real_source_owned_pin_replays_and_rejects_forged_observation_date(self) -> None:
        failures: list[str] = []
        index = trust._load_eval_runs(REPO, failures)
        self.assertEqual(failures, [])
        grandfathered: list[str] = []
        trust.check_sheet(self.qds_path, REPO, self.qds, index, failures, grandfathered)
        self.assertEqual(failures, [])
        self.assertEqual(grandfathered, [])
        forged = copy.deepcopy(self.qds)
        origin = next(row for row in forged["measurement_evidence_origins"]
                      if row["origin_evaluation_run_ref"] == OLD)
        origin["origin_run_date"] = "2026-09-23"
        trust.check_sheet(self.qds_path, REPO, forged, index, failures, grandfathered)
        self.assertTrue(failures, "An old observation cannot be refreshed by changing its emitted origin date")

    def test_retained_audit_json_is_exact_reproducible_output(self) -> None:
        recomputed = json.loads(json.dumps(retained_audit.audit(), allow_nan=False))
        self.assertEqual(self.audit, recomputed)
        self.assertEqual(self.audit["evidence_ref"], AUDIT_PATH.as_posix())
        self.assertIn("no external oracle invocation", self.audit["audit_kind"])
        self.assertEqual(self.audit["coordinate_selections"]["all_heavy_atoms_b_a2"]["count"], 1641)
        self.assertEqual(self.audit["coordinate_selections"]["standard_amino_acid_atoms_b_a2"]["count"], 1488)
        self.assertEqual(self.audit["coordinate_selections"]["water_residue_count"], 146)

    def test_dataset_association_binds_retained_original_input_not_output_or_model(self) -> None:
        self.assertEqual(len(self.qds["dataset_associations"]), 1)
        association = self.qds["dataset_associations"][0]
        self.assertEqual(association, self.context["dataset_associations"][0])
        payload = (REPO / association["dataset_path"]).read_bytes()
        with zipfile.ZipFile(REPO / self.audit["archive"]["path"]) as archive:
            self.assertEqual(payload, archive.read("data/1sar.mtz"))
        self.assertEqual(hashlib.sha256(payload).hexdigest(), association["dataset_sha256"])
        self.assertEqual(association["dataset_subject_ref"], "mtz:sha256:" + association["dataset_sha256"])
        self.assertEqual(association["model_subject_ref"], SUBJECT)
        self.assertEqual((association["owner_evaluation_run_ref"], association["catalog_task_ref"],
                          association["stage"], association["scope"]), (NEW, "T13", "all", "dataset"))
        self.assertTrue(self.audit["t13"]["crystallographic_context_equivalence"]["normalized_context_equal"])
        self.assertEqual(self.audit["t13"]["selected_observation_equivalence"]["matching_reflection_keys"], 7248)
        excluded = self.raw_runs[DATASET_OWNER]["measurements"]
        self.assertEqual(len(excluded), 3)
        self.assertTrue(all(row["catalog_task_ref"] == "T06" and row["scope"] == "dataset" for row in excluded))
        self.assertTrue({row["id"] for row in excluded}.isdisjoint(row["id"] for row in self.active_rows))

    def test_t13_diagnostics_preserve_saved_may_execution_and_failed_aimless(self) -> None:
        rows = self.qds["data_quality_summary"]["diagnostics"]
        by_metric = {row["metric_definition_ref"]: row for row in rows}
        self.assertEqual(len(rows), 7)
        self.assertEqual(len(by_metric), 7)
        expected = {
            "T13_completeness_overall_outer": 99.38, "T13_wilson_b": 14.542,
            "T13_l-test_twinning": 0.03, "T13_anisotropy_δb_aniso": 7.3188,
            "T13_tncs_flag": "false", "T13_ice-ring_flags": "3.44Å", "T13_aimless_status": "failed",
        }
        self.assertEqual(set(by_metric), set(expected))
        for metric, value in expected.items():
            row = by_metric[metric]
            self.assertEqual(row["subject_ref"], self.audit["dataset"]["subject_ref"])
            self.assertEqual((row["stage"], row["scope"], row["pass_status"]), ("all", "dataset", "informational"))
            if isinstance(value, str):
                self.assertEqual(row["value_text"], value)
            else:
                self.assertAlmostEqual(row["value_numeric"], value, places=10)
            self.assertIn(AUDIT_PATH.as_posix(), row["evidence_refs"])
        stats = self.audit["t13"]["ctruncate_parsed"]
        self.assertEqual(stats["moment_2_acentric"], 1.968)
        self.assertEqual(self.audit["t13"]["execution_date_in_retained_logs"], "2026-05-04")
        aimless = by_metric["T13_aimless_status"]
        self.assertIn("hkl_unmerge_list::prepare - EMPTY", aimless["notes"])
        self.assertIn("remain unavailable", aimless["notes"])
        self.assertNotIn("1.997", by_metric["T13_l-test_twinning"]["notes"])

    def test_replacement_origin_dates_do_not_promote_historical_r_observations(self) -> None:
        summary = self.qds["refinement_summary"]
        for slot, suffix, number in (("r_work", "M_005", 0.1622), ("r_free", "M_006", 0.2136),
                                     ("r_free_gap", "M_007", 0.0515)):
            row = summary[slot]
            self.assertEqual(row["source_evaluation_run_ref"], SEPTEMBER)
            self.assertEqual(row["source_measurement_ref"], SEPTEMBER + "_" + suffix)
            self.assertEqual(row["value_numeric"], number)
            self.assertEqual(row["oracle_family"], "non_cctbx")
        origins = self.qds["measurement_evidence_origins"]
        operations = {row["replacement_ref"]: row for row in self.operations
                      if row["target_collection"] == "measurements" and row["action"] == "replace"}
        for origin in origins:
            source = origin["source_measurement_ref"]
            if source in operations:
                self.assertEqual(origin["origin_evaluation_run_ref"], OLD)
                self.assertEqual(origin["origin_measurement_ref"], operations[source]["target_ref"])
                self.assertEqual(origin["origin_run_date"], "2026-04-24")
        self.assertIn("not a complete new scientific rerun", self.qds["scope_notes"])

    def test_three_coordinate_recounts_have_actual_method_and_standalone_origins(self) -> None:
        rows = [row for row in self.new_rows if row["oracle_tool_ref"] == AUDIT_TOOL]
        self.assertEqual(len(rows), 3)
        self.assertEqual({row["metric_definition_ref"] for row in rows},
                         {"T05_waters_count", "T05_total_atoms", "T05_overall_b_mean"})
        replacements = {row.get("replacement_ref") for row in self.operations}
        origins = {row["source_measurement_ref"]: row for row in self.qds["measurement_evidence_origins"]}
        expected = {"T05_waters_count": 146, "T05_total_atoms": 1641, "T05_overall_b_mean": 15.981413772090189}
        for row in rows:
            self.assertNotIn(row["id"], replacements)
            self.assertEqual(row["subject_ref"], SUBJECT)
            self.assertAlmostEqual(row["oracle_measure"]["value_numeric"], expected[row["metric_definition_ref"]])
            self.assertIn(AUDIT_PATH.as_posix(), row["evidence_refs"])
            self.assertIn(self.audit["audit_source_sha256"], row["notes"])
            self.assertEqual(origins[row["id"]]["origin_evaluation_run_ref"], NEW)
            self.assertEqual(origins[row["id"]]["origin_measurement_ref"], row["id"])
            self.assertEqual(origins[row["id"]]["origin_run_date"], "2026-09-23")

    def test_unavailable_historical_phenix_evidence_is_typed_and_surfaced(self) -> None:
        expected = {SEPTEMBER + "_" + suffix for suffix in ("M_001", "M_002", "M_003")}
        source = [row for row in self.raw_runs[NEW]["assumptions"]
                  if row["id"].startswith(NEW + "_ASSUM_raw_output_unavailable_")]
        self.assertEqual({row["measurement_ref"] for row in source}, expected)
        emitted = {row["id"]: row for row in self.qds["assumptions_report"]}
        for row in source:
            self.assertEqual((row["kind"], row["scope"], row["status"]),
                             ("explicit", "measurement", "known_violation"))
            self.assertEqual(emitted[row["id"]], row)
            self.assertIn("not retained", row["description"])
            self.assertIn("no new scientific execution", row["description"])
            self.assertTrue(row["evidence_refs"])

    def test_density_peaks_cannot_contribute_to_steric_clash_coverage(self) -> None:
        for row in self.active_rows:
            if row["metric_definition_ref"] in {"T05_clashes_unique_pairs", "T05_clashscore"}:
                self.assertNotEqual(row["oracle_tool_ref"], "phenix.find_peaks_holes")
                self.assertNotIn("M_peak_inventory", row["id"])
        for row in self.qds["cross_tool_coverage"]["task_coverage"]:
            if row.get("metric_definition_ref") in {"T05_clashes_unique_pairs", "T05_clashscore"}:
                self.assertNotIn("phenix.find_peaks_holes", row["cctbx_oracles"])
        peaks = self.qds["per_residue_quality"]["density_peaks"]
        self.assertEqual(len(peaks), len(self.raw_runs[OLD]["density_peaks"]))
        self.assertTrue(all("Historical" in row["interpretation"] for row in peaks))

    def test_prosmart_and_displacements_are_not_false_validation_or_sfcalc_outputs(self) -> None:
        self.assertFalse(any(row["metric_definition_ref"] == "T05_per_residue_rsrz"
                             and row["oracle_tool_ref"] == "ProSMART" for row in self.active_rows))
        self.assertFalse(any(row["metric_definition_ref"] == "T01_per_residue_displacement"
                             and row["oracle_tool_ref"] == "gemmi sfcalc" for row in self.active_rows))
        displacements = self.qds["per_residue_quality"]["displacement_per_residue_a"]
        self.assertEqual(len(displacements), 10)
        for row in displacements:
            self.assertNotIn("tool_ref", row)
            self.assertIn("does not identify a verified", row["value"]["notes"])
        outliers = self.qds["per_residue_quality"]["outliers"]
        rama = next(row for row in outliers if row["residue_ref"] == "1sar:A:39")
        self.assertEqual(rama["tool_ref"], "mmtbx.validation_summary")
        self.assertIn("No independent", rama["details"])

    def test_local_metal_diagnostics_do_not_claim_canonical_service_or_element_verdicts(self) -> None:
        rows = [row for row in self.new_rows if row["metric_definition_ref"] == "T10_ligand_element_identity_z"]
        self.assertEqual(len(rows), 4)
        self.assertEqual(sorted(row["oracle_measure"]["value_numeric"] for row in rows), [1.87, 3.25, 14.06, 16.35])
        for row in rows:
            self.assertEqual(row["oracle_tool_ref"], METAL_TOOL)
            self.assertEqual(row["oracle_measure"]["unit"], "dimensionless")
            self.assertEqual(row["scope"], "atom")
            self.assertIn("No canonical CheckMyMetal execution", row["notes"])
            self.assertIn("not an independently validated significance statistic", row["notes"])
        for row in self.active_rows:
            self.assertNotEqual(row["oracle_tool_ref"], "CheckMyMetal")

    def test_rscc_water_observations_survive_without_density_outlier_grades(self) -> None:
        quality = self.qds["per_residue_quality"]
        waters = {"1sar:S:680": 0.658, "1sar:S:707": 0.668, "1sar:S:729": 0.691}
        self.assertTrue(set(waters).isdisjoint(row["residue_ref"] for row in quality["outliers"]))
        rscc = {row["residue_ref"]: row for row in quality["rscc_per_residue"]}
        self.assertEqual(set(rscc), set(waters))
        for residue, value in waters.items():
            self.assertEqual(rscc[residue]["value"]["value_numeric"], value)
            self.assertIn("Informational only", rscc[residue]["value"]["notes"])
        for site in self.qds["site_qualities"]:
            self.assertEqual(site["ligand_quality"]["rscc"]["pass_status"], "informational")

    def test_global_b_ratios_are_not_reintroduced_as_local_surroundings(self) -> None:
        self.assertFalse(any(row["metric_definition_ref"] == "T10_ligand_b_vs_surroundings"
                             for row in self.active_rows))
        for site in self.qds["site_qualities"]:
            self.assertNotIn("ligand_b_factor_vs_surroundings", site["ligand_quality"])
        selected = self.audit["coordinate_selections"]
        self.assertIn("Global protein denominator, not a local surrounding shell", selected["ratio_interpretation"])
        protein_mean = selected["standard_amino_acid_atoms_b_a2"]["mean"]
        self.assertAlmostEqual(protein_mean, 15.484670698924731, places=12)
        for row in selected["ligands"]:
            self.assertAlmostEqual(row["mean_b_over_global_protein_mean"],
                                   row["mean_b_factor_a2"] / protein_mean, places=12)

    def test_pairwise_similarity_preserves_methods_without_directional_improvement(self) -> None:
        self.assertEqual(len(self.qds["pairwise_comparisons"]), 1)
        pair = self.qds["pairwise_comparisons"][0]
        self.assertEqual(pair["subject_ref"], SUBJECT)
        self.assertEqual(pair["reference_subject_ref"], STARTING)
        self.assertEqual(pair["ca_rmsd_a"]["value_numeric"], 0.423)
        self.assertEqual(pair["tm_score"]["value_numeric"], 0.987)
        self.assertEqual(pair["lddt"]["value_numeric"], 0.9725)
        self.assertIn("not evidence of directional quality improvement", pair["verdict"])
        self.assertIn("no shared alignment", pair["alignment_method"])
        self.assertNotIn("residues_aligned", pair)

    def test_cctbx_only_coverage_retains_metric_specific_gaps_not_a_task_pass(self) -> None:
        rows = self.qds["cross_tool_coverage"]["task_coverage"]
        gated = [row for row in rows if row["cctbx_oracles"] and not row["non_cctbx_oracles"]]
        self.assertEqual(len(gated), 11)
        for row in gated:
            self.assertIn("open — cctbx only — WAIVED", row["gap_status"])
            self.assertIn("never a pass", row["gap_status"])
        self.assertFalse(any(row["gap_status"] == "closed" for row in rows))
        aimless = next(row for row in rows if row["metric_definition_ref"] == "T13_aimless_status")
        self.assertEqual(aimless["non_cctbx_oracles"], [])
        self.assertIn("not counted as coverage", aimless["gap_status"])

    def test_real_raw_target_mutation_and_wrong_dataset_binding_fail_closed(self) -> None:
        documents = copy.deepcopy(self.documents)
        documents[0]["evaluation_runs"][0]["measurements"][0]["notes"] = "Forged raw evidence."
        with self.assertRaisesRegex(contract.QdsCompletenessError, "target_sha256"):
            contract.prepare_projection(documents, QDS, "1sar", REPO)
        documents = copy.deepcopy(self.documents)
        association = documents[-1]["qds_emission_contexts"][0]["dataset_associations"][0]
        association["dataset_sha256"] = "0" * 64
        with self.assertRaises(contract.QdsCompletenessError):
            contract.prepare_projection(documents, QDS, "1sar", REPO)


if __name__ == "__main__":
    unittest.main()
