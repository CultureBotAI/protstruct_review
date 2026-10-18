#!/usr/bin/env python3
"""Regression tests for ref/tools_and_measurements_guide.md and its cross-links."""

from __future__ import annotations

from pathlib import Path
import re
import unittest
import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
GUIDE_PATH = REPO_ROOT / "ref" / "tools_and_measurements_guide.md"
CATALOG_PATH = REPO_ROOT / "ref" / "catalog.yaml"
RECOMMENDATIONS_PATH = REPO_ROOT / "ref" / "tool_recommendations.yaml"
ASSUMPTIONS_PATH = REPO_ROOT / "ref" / "tool_assumptions.yaml"
README_PATH = REPO_ROOT / "ref" / "README.md"
ORACLE_TOOLS_PATH = REPO_ROOT / "ref" / "oracle_tools.md"
QUALITY_REPORTING_PATH = REPO_ROOT / "ref" / "quality_reporting.md"

REQUIRED_CATEGORIES = [
    "Category 1: Experimental Fit & Data Quality",
    "Category 2: Geometry, Stereochemistry & Protonation",
    "Category 3: Structural Change & Local Rebuilding",
    "Category 4: Sites, Ligands & Biological Interfaces",
    "Category 5: Prediction Confidence & Predicted-Model Processing",
    "Category 6: Classification & Experimental-Restraint Specialization",
]

REQUIRED_EPISTEMIC_LAYERS = [
    "Documented capability",
    "Runnable local integration",
    "Retained independent evidence",
    "Calibrated interpretation vs informational reporting",
]

REQUIRED_REGISTRY_IDS = [
    "REC_T05_rama_z_score_top_performing_2026_10_18_capability_correction",
    "ASSUM_prosmart_reference_dependent_2026_10_18",
    "ASSUM_prosmart_no_top8000_default_2026_10_18",
    "REC_T05_bond-length_rmsd_top_considered_2026_09_27_capability_correction",
    "REC_T05_bond-angle_rmsd_top_considered_2026_09_27_capability_correction",
    "REC_T05_planarity_rmsd_top_considered_2026_09_27_capability_correction",
    "REC_T05_chirality_outliers_top_considered_2026_09_27_capability_correction",
    "REC_T06_overall_b_top_considered_2026_09_27_capability_correction",
    "REC_T02_omega_cis_trans_flips_top_considered_2026_09_27_capability_correction",
    "REC_T14_asn_gln_his_flip_set_conflicts_top_considered_2026_09_27_suspended",
    "REC_T14_h_added_top_considered_2026_09_27",
    "REC_T14_clashscore_delta_pre_vs_post_top_considered_2026_09_27_version_pin",
    "REC_T15_secondary_structure_agreement_top_considered_2026_09_22",
    "REC_T16_interface_buried_surface_area_top_considered_2026_09_22",
    "REC_T03_r_work_top_performing_2026_09_22",
    "REC_T03_r_free_top_performing_2026_09_22",
]


def validate_guide_content(
    guide_text: str,
    catalog_tasks: list[dict],
) -> list[str]:
    """Validate tools_and_measurements_guide.md text and return any errors."""
    errors: list[str] = []

    if "<!-- catalog-state: tasks=T01–T17; count=17; drivers=17 -->" not in guide_text:
        errors.append("Missing catalog-state header comment")

    for category in REQUIRED_CATEGORIES:
        if category not in guide_text:
            errors.append(f"Missing required question category heading: {category}")

    if "Synthesis: Using This Guide in Before/After Refinement Assessment" not in guide_text:
        errors.append("Missing synthesis section linking guide to before/after refinement assessment")

    # Split task sections: #### `TXX` — <task_name>
    section_pattern = re.compile(
        r"^#### `(T\d{2})` — ([^\n]+)\n(.*?)(?=^#### `T\d{2}` — |^## |\Z)",
        re.MULTILINE | re.DOTALL,
    )
    sections = {m.group(1): (m.group(2).strip(), m.group(3)) for m in section_pattern.finditer(guide_text)}

    for task in catalog_tasks:
        tid = task["id"]
        tname = task["task_name"]
        if tid not in sections:
            errors.append(f"Missing dedicated task subsection for {tid} ({tname})")
            continue
        sec_title, sec_body = sections[tid]
        if sec_title != tname:
            errors.append(f"Task {tid} title mismatch: expected {tname!r}, found {sec_title!r}")
        for layer in REQUIRED_EPISTEMIC_LAYERS:
            if f"**{layer}" not in sec_body:
                errors.append(f"Task {tid} subsection missing epistemic layer: {layer}")

    for reg_id in REQUIRED_REGISTRY_IDS:
        if reg_id not in guide_text:
            errors.append(f"Missing required active registry ID reference: {reg_id}")

    # Verify all markdown relative file links resolve on disk
    for match in re.finditer(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", guide_text):
        target = match.group(1)
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        resolved = (GUIDE_PATH.parent / target).resolve()
        if not resolved.exists():
            errors.append(f"Broken markdown link target in guide: {target}")

    # Verify all inline backtick repository file paths resolve on disk
    intentionally_missing_paths = {"data/1sar_final.pdb"}
    for match in re.finditer(r"`((?:ref|data|scripts|schemas)/[^`\s]+)`", guide_text):
        rel_path = match.group(1).rstrip(".,;:")
        if "*" in rel_path or "<" in rel_path or rel_path in intentionally_missing_paths:
            continue
        resolved = REPO_ROOT / rel_path
        if not resolved.exists():
            errors.append(f"Missing repository path cited in guide: {rel_path}")

    return errors


class TestToolsAndMeasurementsGuide(unittest.TestCase):
    """Verify completeness, registry alignment, cross-links, and mutation sensitivity."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.guide_text = GUIDE_PATH.read_text(encoding="utf-8")
        cls.catalog = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))
        cls.catalog_tasks = cls.catalog["catalog_tasks"]
        cls.recommendations = yaml.safe_load(RECOMMENDATIONS_PATH.read_text(encoding="utf-8"))[
            "tool_recommendations"
        ]
        cls.assumptions = yaml.safe_load(ASSUMPTIONS_PATH.read_text(encoding="utf-8"))[
            "assumptions"
        ]

    def test_guide_passes_all_structural_and_epistemic_checks(self) -> None:
        self.assertEqual(len(self.catalog_tasks), 17)
        errors = validate_guide_content(self.guide_text, self.catalog_tasks)
        self.assertEqual(errors, [])

    def test_all_cited_registry_ids_exist_in_yaml_registries(self) -> None:
        rec_ids = {r["id"] for r in self.recommendations}
        assum_ids = {a["id"] for a in self.assumptions}

        cited_recs = set(re.findall(r"`(REC_[^`\s]+)`", self.guide_text))
        cited_assums = set(re.findall(r"`(ASSUM_[^`\s]+)`", self.guide_text))

        self.assertGreaterEqual(len(cited_recs), 25)
        self.assertGreaterEqual(len(cited_assums), 15)

        missing_recs = cited_recs - rec_ids
        missing_assums = cited_assums - assum_ids
        self.assertEqual(missing_recs, set(), f"Guide cites unknown REC_ IDs: {missing_recs}")
        self.assertEqual(missing_assums, set(), f"Guide cites unknown ASSUM_ IDs: {missing_assums}")

    def test_cross_links_present_in_reference_docs(self) -> None:
        for path in (README_PATH, ORACLE_TOOLS_PATH, QUALITY_REPORTING_PATH):
            text = path.read_text(encoding="utf-8")
            self.assertIn(
                "tools_and_measurements_guide.md",
                text,
                f"Expected cross-link to tools_and_measurements_guide.md in {path.name}",
            )

    def test_negative_mutations_fail_validation(self) -> None:
        # 1. Removing a task heading must fail
        mutated_no_t11 = self.guide_text.replace(
            "#### `T11` — Loop / missing-region fitting",
            "#### Loop fitting section",
        )
        errors_no_t11 = validate_guide_content(mutated_no_t11, self.catalog_tasks)
        self.assertTrue(any("T11" in err for err in errors_no_t11))

        # 2. Removing a question category heading must fail
        mutated_no_cat4 = self.guide_text.replace(
            "Category 4: Sites, Ligands & Biological Interfaces",
            "Sites and Interfaces",
        )
        errors_no_cat4 = validate_guide_content(mutated_no_cat4, self.catalog_tasks)
        self.assertTrue(any("Category 4" in err for err in errors_no_cat4))

        # 3. Removing an epistemic layer from a task section must fail
        mutated_no_layer = self.guide_text.replace(
            "- **Retained independent evidence**: `T08_docked_map_cc`",
            "- **Evidence summary**: `T08_docked_map_cc`",
        )
        errors_no_layer = validate_guide_content(mutated_no_layer, self.catalog_tasks)
        self.assertTrue(any("T08" in err and "Retained independent evidence" in err for err in errors_no_layer))

        # 4. Removing the #911 ProSMART capability correction reference must fail
        mutated_no_911 = self.guide_text.replace(
            "REC_T05_rama_z_score_top_performing_2026_10_18_capability_correction",
            "REC_T05_rama_z_score_legacy",
        )
        errors_no_911 = validate_guide_content(mutated_no_911, self.catalog_tasks)
        self.assertTrue(
            any("REC_T05_rama_z_score_top_performing_2026_10_18_capability_correction" in err for err in errors_no_911)
        )
        rec_ids = {r["id"] for r in self.recommendations}
        cited_in_mutated = set(re.findall(r"`(REC_[^`\s]+)`", mutated_no_911))
        self.assertIn("REC_T05_rama_z_score_legacy", cited_in_mutated - rec_ids)

        # 5. Citing a nonexistent repository path must fail
        mutated_bad_path = self.guide_text.replace(
            "`ref/research/data/refinement_assessment_1sar_and_controls_2026-10-18.json`",
            "`ref/research/data/nonexistent_artifact_2026-10-18.json`",
        )
        errors_bad_path = validate_guide_content(mutated_bad_path, self.catalog_tasks)
        self.assertTrue(
            any("nonexistent_artifact_2026-10-18.json" in err for err in errors_bad_path)
        )


if __name__ == "__main__":
    unittest.main()
