#!/usr/bin/env python3
"""Unit tests for Stage 2 PHENIX development exclusion and provider metadata witness generators."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))

import phenix_stage2_manifest as p2m  # noqa: E402


def _write_text(path: Path, content: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = content.encode("utf-8")
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


class TestPhenixStage2Manifest(unittest.TestCase):
    """Verify build_dev_exclusions and inspect_provider_metadata invariants."""

    def test_build_dev_exclusions_deterministic_and_complete(self) -> None:
        m1 = p2m.build_dev_exclusions(p2m.REPO_ROOT)
        m2 = p2m.build_dev_exclusions(p2m.REPO_ROOT)
        self.assertEqual(m1, m2)
        self.assertEqual(p2m.canonical_json_bytes(m1), p2m.canonical_json_bytes(m2))

        roundtripped = json.loads(p2m.canonical_json_bytes(m1).decode("utf-8"))
        self.assertEqual(roundtripped, m1)

        payload = {k: v for k, v in m1.items() if k != "manifest_sha256"}
        self.assertEqual(m1["manifest_sha256"], p2m.canonical_json_sha256(payload))

        self.assertEqual(m1["registration_status"], "selected_decisions_recorded")
        self.assertFalse(m1["execution_authorized"])
        self.assertFalse(m1["frozen_result_free"])
        self.assertFalse(m1["outcomes_included"])

        # Sources and SHA-256 bindings
        self.assertEqual(
            m1["sources"]["approved_policy_selections"]["sha256"],
            "14bbb0c9dc1883c2404f40193e135a4aaa974d8ab605fe95bb78d44c6a704a7b",
        )
        self.assertEqual(
            m1["sources"]["negative_control_round2_enrolled"]["sha256"],
            "02fc974da9d1f8a2d8fb3c496c13196c200b31d182f1b7323cb25dcc59cbe7da",
        )
        self.assertEqual(
            m1["sources"]["refinement_assessment_1sar"]["sha256"],
            "db100e926bfcf6331c303087846c4d51117a4411c6afdf58877aada5dbf14245",
        )

        # Counts: 22 Round-2 + 1 separate 1SAR = 23 unique accessions
        self.assertEqual(
            m1["counts"],
            {
                "round2_negative_control_accessions": 22,
                "separate_1sar_accessions": 1,
                "total_excluded_accessions": 23,
                "onesar_retained_subject_count": 6,
            },
        )
        self.assertEqual(len(m1["excluded_accessions"]), 23)
        self.assertEqual(len(set(m1["excluded_accessions"])), 23)
        self.assertEqual(m1["excluded_accessions"][-1], "1SAR")
        self.assertNotIn("1SAR", m1["excluded_accessions"][:22])

        # Verify 22 Round-2 rows whitelist and CIF role
        r2_rows = m1["round2_negative_controls"]
        self.assertEqual(len(r2_rows), 22)
        forbidden_r2_keys = {
            "in_run",
            "paths",
            "headroom_both_paths",
            "headroom_one_path_only",
            "cluster",
            "stratum",
            "d_min",
            "deposit_year",
            "test_value",
            "valid_flag_set",
        }
        for idx, row in enumerate(r2_rows):
            self.assertEqual(row["entry_index"], idx)
            self.assertEqual(row["source_pointer"], f"/entries/{idx}")
            self.assertEqual(row["verification_mode"], "source_attested")
            self.assertFalse(row["local_bytes_verified"])
            self.assertFalse(row["execution_ready_input_bundle"])
            self.assertEqual(
                row["cif_role"],
                "deposited_structural_mmcif_not_ligand_restraint_cif",
            )
            self.assertEqual(
                set(row["input_hashes"].keys()),
                {"model", "mtz", "cif", "validation_xml"},
            )
            self.assertEqual(
                row["column_selector_pointers"],
                {
                    "obs": f"/entries/{idx}/array_selection/obs",
                    "obs_f": f"/entries/{idx}/array_selection/obs/0",
                    "obs_sigf": f"/entries/{idx}/array_selection/obs/1",
                    "free_flag": f"/entries/{idx}/array_selection/free_flag",
                },
            )
            self.assertFalse(row["test_flag_values_recorded_in_source"])
            self.assertTrue(forbidden_r2_keys.isdisjoint(row.keys()))

        # Verify separate 1SAR exclusion and 6 nested retained subjects
        onesar = m1["onesar_exclusion"]
        self.assertEqual(onesar["pdb_id"], "1SAR")
        self.assertEqual(onesar["accession_level_exclusion_count"], 1)
        self.assertEqual(onesar["verification_mode"], "locally_byte_verified")
        self.assertTrue(onesar["local_bytes_verified"])
        self.assertFalse(onesar["execution_ready_input_bundle"])
        self.assertEqual(
            onesar["round7_status"],
            "absent_from_archive_never_measured",
        )
        self.assertEqual(
            onesar["artifact_archive"]["archive_sha256"],
            "9fc5352284b7ffa7763c633a3eb4d3d0db96b8c25a1be9bcea361722d2c53054",
        )
        self.assertFalse(onesar["artifact_archive"]["extracted_to_disk"])

        subjects = {s["subject_id"]: s for s in onesar["retained_subjects"]}
        self.assertEqual(
            set(subjects.keys()),
            {
                "starting_model",
                "packaged_round4_final_model",
                "retained_round5_model",
                "retained_round6_model",
                "original_input_mtz",
                "deposited_reference_model",
            },
        )
        self.assertEqual(
            subjects["starting_model"]["subject_ref"],
            "artifact:cdba2c07-daff-4f60-ae96-12452b3a5fbb#data/1sar.pdb",
        )
        self.assertEqual(
            subjects["starting_model"]["sha256"],
            "6b34c5d0dec6647df20eae9021ff7d511d6dedc03b4349c0b634d8e5b1f869e4",
        )
        self.assertEqual(
            subjects["packaged_round4_final_model"]["subject_ref"],
            "artifact:cdba2c07-daff-4f60-ae96-12452b3a5fbb#data/1sar_final.pdb",
        )
        self.assertEqual(
            subjects["packaged_round4_final_model"]["sha256"],
            "8cbc1650f8be5a3833f98833fa514ec7d490c2c3bb9aa930413abac05e2a510b",
        )
        # R5 and R6 have direct archive member byte ancestry and no false JSON pointer
        self.assertEqual(
            subjects["retained_round5_model"]["subject_ref"],
            "artifact:cdba2c07-daff-4f60-ae96-12452b3a5fbb#data/1sar_round5.pdb",
        )
        self.assertEqual(
            subjects["retained_round5_model"]["sha256"],
            "25c140b46e18a1d1ec211d985868894f227c827ea0c76f7187d41e1f75c03733",
        )
        self.assertIsNone(subjects["retained_round5_model"]["source_pointer"])
        self.assertEqual(
            subjects["retained_round5_model"]["hash_ancestry"],
            "direct_archive_member_bytes",
        )
        self.assertEqual(
            subjects["retained_round6_model"]["subject_ref"],
            "artifact:cdba2c07-daff-4f60-ae96-12452b3a5fbb#data/1sar_round6.pdb",
        )
        self.assertEqual(
            subjects["retained_round6_model"]["sha256"],
            "5d01ce3645d1295a42f620987785fd8368441418e82a0b6d6992d7f79500c110",
        )
        self.assertIsNone(subjects["retained_round6_model"]["source_pointer"])
        self.assertEqual(
            subjects["retained_round6_model"]["hash_ancestry"],
            "direct_archive_member_bytes",
        )
        self.assertEqual(
            subjects["original_input_mtz"]["subject_ref"],
            "artifact:cdba2c07-daff-4f60-ae96-12452b3a5fbb#data/1sar.mtz",
        )
        self.assertEqual(
            subjects["original_input_mtz"]["sha256"],
            "f36d5fe685a3e524e8809d17d19ce12073acdf339eba2cfd3b0347a818850ab2",
        )
        dep_subj = subjects["deposited_reference_model"]
        self.assertEqual(dep_subj["subject_ref"], "pdb:1SAR")
        self.assertEqual(dep_subj["role"], "deposited_reference_only")
        self.assertTrue(dep_subj["coordinate_file_available"])
        self.assertEqual(
            dep_subj["sha256"],
            "e60e5db6c7eb554a3ac4e184bdf7cbb7d69b682e287579bdcf5f8bf279d51f86",
        )
        for forbidden_1sar_key in (
            "inventory",
            "deposition_applicability",
            "deposited_r_work",
            "deposited_r_free",
            "header_lines",
        ):
            self.assertNotIn(forbidden_1sar_key, onesar)
            for s in onesar["retained_subjects"]:
                self.assertNotIn(forbidden_1sar_key, s)

    def test_dev_exclusions_source_sha_duplication_and_cardinality_guards(self) -> None:
        round2_raw = (p2m.REPO_ROOT / p2m.ROUND2_ENROLLED_PATH).read_text(
            encoding="utf-8"
        )
        round2_doc = json.loads(round2_raw)
        assessment_raw = (p2m.REPO_ROOT / p2m.ASSESSMENT_1SAR_PATH).read_text(
            encoding="utf-8"
        )
        assessment_doc = json.loads(assessment_raw)

        # 1. Source SHA mismatch when file bytes are tampered in a temporary repo
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_root = Path(tmpdir)
            for rel_path in (
                p2m.APPROVED_SELECTIONS_PATH,
                p2m.ROUND2_ENROLLED_PATH,
                p2m.ASSESSMENT_1SAR_PATH,
                p2m.ONESAR_ARCHIVE_PATH,
                p2m.ONESAR_DEPOSITED_PDB_PATH,
            ):
                dst = tmp_root / rel_path
                dst.parent.mkdir(parents=True, exist_ok=True)
                os.symlink(p2m.REPO_ROOT / rel_path, dst)

            # Baseline succeeds
            self.assertEqual(
                p2m.build_dev_exclusions(tmp_root)["manifest_sha256"],
                p2m.build_dev_exclusions(p2m.REPO_ROOT)["manifest_sha256"],
            )

            # Tamper Round-2 source file
            (tmp_root / p2m.ROUND2_ENROLLED_PATH).unlink()
            (tmp_root / p2m.ROUND2_ENROLLED_PATH).write_text(
                round2_raw + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                p2m.build_dev_exclusions(tmp_root)

        # 2. Row duplication, cardinality, 1SAR collision, and malformed selector guards
        bad_count = copy.deepcopy(round2_doc)
        bad_count["entries"] = bad_count["entries"][:21]
        with self.assertRaisesRegex(ValueError, "length 22"):
            p2m._parse_round2_exclusions(bad_count)

        bad_n_enrolled = copy.deepcopy(round2_doc)
        bad_n_enrolled["n_enrolled"] = 21
        with self.assertRaisesRegex(ValueError, "n_enrolled must be 22"):
            p2m._parse_round2_exclusions(bad_n_enrolled)

        dup_pdb = copy.deepcopy(round2_doc)
        dup_pdb["entries"][1]["pdb_id"] = dup_pdb["entries"][0]["pdb_id"]
        with self.assertRaisesRegex(ValueError, "Duplicate pdb_id"):
            p2m._parse_round2_exclusions(dup_pdb)

        onesar_in_r2 = copy.deepcopy(round2_doc)
        onesar_in_r2["entries"][0]["pdb_id"] = "1SAR"
        with self.assertRaisesRegex(ValueError, "1SAR"):
            p2m._parse_round2_exclusions(onesar_in_r2)

        bad_hashes = copy.deepcopy(round2_doc)
        del bad_hashes["entries"][0]["input_hashes"]["cif"]
        with self.assertRaisesRegex(ValueError, "input_hashes"):
            p2m._parse_round2_exclusions(bad_hashes)

        bad_sel = copy.deepcopy(round2_doc)
        bad_sel["entries"][0]["array_selection"]["test_value"] = 1
        with self.assertRaisesRegex(ValueError, "array_selection"):
            p2m._parse_round2_exclusions(bad_sel)

        # 3. 1SAR hash collision with Round-2 hash set is rejected
        with self.assertRaisesRegex(ValueError, "disjoint"):
            p2m._build_onesar_exclusion(
                p2m.REPO_ROOT,
                assessment_doc,
                {p2m.ONESAR_START_SHA256},
            )

        # 4. Unexpected Round 7 or duplicate archive member in 1SAR zip is rejected
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_root = Path(tmpdir)
            for rel_path in (
                p2m.APPROVED_SELECTIONS_PATH,
                p2m.ROUND2_ENROLLED_PATH,
                p2m.ASSESSMENT_1SAR_PATH,
                p2m.ONESAR_DEPOSITED_PDB_PATH,
            ):
                dst = tmp_root / rel_path
                dst.parent.mkdir(parents=True, exist_ok=True)
                os.symlink(p2m.REPO_ROOT / rel_path, dst)

            fake_zip = tmp_root / p2m.ONESAR_ARCHIVE_PATH
            fake_zip.parent.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(fake_zip, "w") as zf:
                zf.writestr("data/1sar.pdb", b"start")
                zf.writestr("data/1sar_final.pdb", b"r4")
                zf.writestr("data/1sar_round5.pdb", b"r5")
                zf.writestr("data/1sar_round6.pdb", b"r6")
                zf.writestr("data/1sar_round7.pdb", b"r7")
                zf.writestr("data/1sar.mtz", b"mtz")
            fake_zip_sha = hashlib.sha256(fake_zip.read_bytes()).hexdigest()
            patched_assessment = copy.deepcopy(assessment_doc)
            patched_assessment["case_study_1sar"]["provenance"][
                "archive_sha256"
            ] = fake_zip_sha
            with mock.patch.object(p2m, "ONESAR_ARCHIVE_SHA256", fake_zip_sha):
                with self.assertRaisesRegex(ValueError, "Round 7"):
                    p2m._build_onesar_exclusion(tmp_root, patched_assessment, set())

    def test_inspect_provider_metadata_fake_fixture_adapters_and_hidden(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prefix = Path(tmpdir) / "fake_phenix"
            sp = prefix / "lib" / "python3.9" / "site-packages"
            sp.mkdir(parents=True, exist_ok=True)

            # 1. Matching .dist-info/METADATA with Author-email and body that must not be serialized
            meta_openai_sha = _write_text(
                sp / "openai-1.30.0.dist-info" / "METADATA",
                (
                    "Metadata-Version: 2.1\n"
                    "Name: openai\n"
                    "Version: 1.30.0\n"
                    "Author: Secret Person\n"
                    "Author-email: secret_person@example.com\n"
                    "\n"
                    "Body text with token sk-secret.\n"
                ),
            )
            # 2. Matching .egg-info/PKG-INFO
            pkg_google_sha = _write_text(
                sp / "google_generativeai-0.5.0.egg-info" / "PKG-INFO",
                (
                    "Metadata-Version: 2.1\n"
                    "Name: google-generativeai\n"
                    "Version: 0.5.0\n"
                    "Maintainer-email: maint@example.com\n"
                ),
            )
            # 3. Hidden directory with matching METADATA
            meta_hidden_sha = _write_text(
                sp / ".hidden_ollama-0.2.1.dist-info" / "METADATA",
                (
                    "Metadata-Version: 2.1\n"
                    "Name: ollama-client\n"
                    "Version: 0.2.1\n"
                ),
            )
            # 4. Non-matching distribution metadata
            _write_text(
                sp / "numpy-1.26.4.dist-info" / "METADATA",
                (
                    "Metadata-Version: 2.1\n"
                    "Name: numpy\n"
                    "Version: 1.26.4\n"
                ),
            )

            # 5. Top-level native adapters covering module_file, regular_package, namespace_only_directory
            _write_text(sp / "langchain_openai.py", "# module file\n")
            _write_text(
                sp / "langchain_google_genai" / "__init__.py",
                "# regular package\n",
            )
            (sp / "langchain_ollama" / "sub").mkdir(parents=True, exist_ok=True)
            _write_text(sp / "langchain_ollama" / "sub" / "helper.py", "# helper\n")

            witness1 = p2m.inspect_provider_metadata(prefix)
            witness2 = p2m.inspect_provider_metadata(prefix)
            self.assertEqual(witness1, witness2)

            serialized = p2m.canonical_json_bytes(witness1).decode("utf-8")
            self.assertNotIn(str(prefix), serialized)
            self.assertNotIn(str(prefix.resolve()), serialized)
            self.assertNotIn("secret_person@example.com", serialized)
            self.assertNotIn("maint@example.com", serialized)
            self.assertNotIn("sk-secret", serialized)

            self.assertEqual(
                witness1["inspection_counts"],
                {
                    "directories_traversed": 8,
                    "files_traversed": 7,
                    "metadata_files_inspected": 4,
                    "dist_info_metadata_files_inspected": 3,
                    "pkg_info_metadata_files_inspected": 1,
                    "matched_distribution_count": 3,
                    "present_native_adapter_count": 3,
                },
            )
            self.assertEqual(
                witness1["matched_distributions"],
                [
                    {
                        "name": "ollama-client",
                        "path": (
                            "PHENIX_PREFIX/lib/python3.9/site-packages/"
                            ".hidden_ollama-0.2.1.dist-info/METADATA"
                        ),
                        "sha256": meta_hidden_sha,
                        "version": "0.2.1",
                    },
                    {
                        "name": "google-generativeai",
                        "path": (
                            "PHENIX_PREFIX/lib/python3.9/site-packages/"
                            "google_generativeai-0.5.0.egg-info/PKG-INFO"
                        ),
                        "sha256": pkg_google_sha,
                        "version": "0.5.0",
                    },
                    {
                        "name": "openai",
                        "path": (
                            "PHENIX_PREFIX/lib/python3.9/site-packages/"
                            "openai-1.30.0.dist-info/METADATA"
                        ),
                        "sha256": meta_openai_sha,
                        "version": "1.30.0",
                    },
                ],
            )

            adapters = witness1["native_adapter_modules"]
            self.assertEqual(
                adapters["langchain_openai"],
                {
                    "adapter_name": "langchain_openai",
                    "present": True,
                    "kind": "module_file",
                    "path": (
                        "PHENIX_PREFIX/lib/python3.9/site-packages/langchain_openai.py"
                    ),
                    "init_py_path": None,
                    "importability_proven": False,
                },
            )
            self.assertEqual(
                adapters["langchain_google_genai"],
                {
                    "adapter_name": "langchain_google_genai",
                    "present": True,
                    "kind": "regular_package",
                    "path": (
                        "PHENIX_PREFIX/lib/python3.9/site-packages/"
                        "langchain_google_genai"
                    ),
                    "init_py_path": (
                        "PHENIX_PREFIX/lib/python3.9/site-packages/"
                        "langchain_google_genai/__init__.py"
                    ),
                    "importability_proven": False,
                },
            )
            self.assertEqual(
                adapters["langchain_ollama"],
                {
                    "adapter_name": "langchain_ollama",
                    "present": True,
                    "kind": "namespace_only_directory",
                    "path": (
                        "PHENIX_PREFIX/lib/python3.9/site-packages/langchain_ollama"
                    ),
                    "init_py_path": None,
                    "importability_proven": False,
                },
            )
            self.assertEqual(
                witness1["shared_dated_snapshot"],
                {
                    "selected_identifier": None,
                    "availability": "not_assessed",
                    "runtime_binding": "not_assessed",
                },
            )
            self.assertEqual(
                witness1["static_source_witness"],
                {
                    "path": "ref/research/data/phenix_langchain_static_witness_2026-11-15.json",
                    "sha256": (
                        "692a0b4e082ac5f56622ca6c61b457120efa00542545c12e1672f66c01c9ec0f"
                    ),
                    "inspected_python_file_count": 44,
                },
            )

    def test_empty_tree_nested_adapters_and_missing_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prefix = Path(tmpdir) / "empty_phenix"
            sp = prefix / "lib" / "python3.9" / "site-packages"
            sp.mkdir(parents=True, exist_ok=True)
            # Nested module with adapter name does NOT count as top-level adapter
            _write_text(sp / "nested_pkg" / "langchain_openai.py", "# nested\n")

            witness = p2m.inspect_provider_metadata(prefix)
            self.assertEqual(witness["matched_distributions"], [])
            self.assertEqual(
                witness["inspection_counts"]["matched_distribution_count"], 0
            )
            self.assertEqual(
                witness["inspection_counts"]["present_native_adapter_count"], 0
            )
            for name in p2m.NATIVE_ADAPTER_NAMES:
                self.assertEqual(
                    witness["native_adapter_modules"][name]["kind"], "absent"
                )
                self.assertFalse(witness["native_adapter_modules"][name]["present"])

            # Missing prefix or missing site-packages fails closed
            with self.assertRaises(ValueError):
                p2m.inspect_provider_metadata(Path(tmpdir) / "nonexistent_prefix")
            incomplete_prefix = Path(tmpdir) / "incomplete_phenix"
            (incomplete_prefix / "lib" / "python3.9").mkdir(parents=True)
            with self.assertRaises(ValueError):
                p2m.inspect_provider_metadata(incomplete_prefix)

    def test_metadata_header_validation_and_missing_metadata_files(self) -> None:
        bad_metadata_contents: tuple[tuple[str, str], ...] = (
            ("missing_name", "Metadata-Version: 2.1\nVersion: 1.0.0\n"),
            ("missing_version", "Metadata-Version: 2.1\nName: openai\n"),
            ("empty_name", "Metadata-Version: 2.1\nName:   \nVersion: 1.0.0\n"),
            ("empty_version", "Metadata-Version: 2.1\nName: openai\nVersion: \n"),
            (
                "duplicate_name",
                "Metadata-Version: 2.1\nName: openai\nName: ollama\nVersion: 1.0.0\n",
            ),
            (
                "duplicate_version",
                "Metadata-Version: 2.1\nName: openai\nVersion: 1.0.0\nVersion: 2.0.0\n",
            ),
        )
        for label, content in bad_metadata_contents:
            with self.subTest(case=label):
                with tempfile.TemporaryDirectory() as tmpdir:
                    prefix = Path(tmpdir) / "phenix"
                    sp = prefix / "lib" / "python3.9" / "site-packages"
                    _write_text(sp / "pkg-1.0.dist-info" / "METADATA", content)
                    with self.assertRaises(ValueError):
                        p2m.inspect_provider_metadata(prefix)

        # .dist-info directory missing METADATA/PKG-INFO fails closed
        with tempfile.TemporaryDirectory() as tmpdir:
            prefix = Path(tmpdir) / "phenix_missing_meta"
            sp = prefix / "lib" / "python3.9" / "site-packages"
            (sp / "broken-1.0.dist-info").mkdir(parents=True, exist_ok=True)
            _write_text(sp / "broken-1.0.dist-info" / "RECORD", "")
            with self.assertRaisesRegex(ValueError, "missing METADATA/PKG-INFO"):
                p2m.inspect_provider_metadata(prefix)

        # #1381: structurally malformed headers (msg.defects) are rejected before
        # Name/Version extraction, using sanitized defect class names only (never
        # leaking raw discarded metadata header lines or defect repr).
        malformed_defect_cases: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
            (
                "leading_continuation",
                (
                    "  secret_continuation_header: sk-secret-123\n"
                    "Metadata-Version: 2.1\n"
                    "Name: openai\n"
                    "Version: 1.0.0\n"
                ),
                "FirstHeaderLineIsContinuationDefect",
                ("secret_continuation_header", "sk-secret-123"),
            ),
            (
                "malformed_line_before_conflicting_name_version",
                (
                    "Metadata-Version: 2.1\n"
                    "Name: openai\n"
                    "Version: 1.0.0\n"
                    "malformed_secret_line_without_colon\n"
                    "Name: ollama\n"
                    "Version: 9.9.9\n"
                ),
                "MissingHeaderBodySeparatorDefect",
                ("malformed_secret_line_without_colon", "ollama", "9.9.9"),
            ),
        )
        for label, bad_raw, expected_defect_cls, forbidden_substrings in (
            malformed_defect_cases
        ):
            with self.subTest(defect_case=label):
                with tempfile.TemporaryDirectory() as tmpdir:
                    prefix = Path(tmpdir) / "phenix_defects"
                    sp = prefix / "lib" / "python3.9" / "site-packages"
                    _write_text(
                        sp / "malformed-1.0.dist-info" / "METADATA", bad_raw
                    )
                    with self.assertRaises(ValueError) as ctx:
                        p2m.inspect_provider_metadata(prefix)
                    err_msg = str(ctx.exception)
                    self.assertIn("malformed header structure", err_msg)
                    self.assertIn(expected_defect_cls, err_msg)
                    for leak_tok in forbidden_substrings:
                        self.assertNotIn(leak_tok, err_msg)

        # #1381 positive control: ordinary header/body separation (blank line followed
        # by body lines including pseudo-header text) has no defects and remains accepted.
        with tempfile.TemporaryDirectory() as tmpdir:
            prefix = Path(tmpdir) / "phenix_header_body_ok"
            sp = prefix / "lib" / "python3.9" / "site-packages"
            expected_sha = _write_text(
                sp / "openai-1.2.0.dist-info" / "METADATA",
                (
                    "Metadata-Version: 2.1\n"
                    "Name: openai\n"
                    "Version: 1.2.0\n"
                    "\n"
                    "Free-form description body.\n"
                    "Name: body-line-not-a-header\n"
                ),
            )
            witness = p2m.inspect_provider_metadata(prefix)
            self.assertEqual(
                witness["matched_distributions"],
                [
                    {
                        "name": "openai",
                        "path": (
                            "PHENIX_PREFIX/lib/python3.9/site-packages/"
                            "openai-1.2.0.dist-info/METADATA"
                        ),
                        "sha256": expected_sha,
                        "version": "1.2.0",
                    }
                ],
            )

    def test_metadata_nonregular_entries_adapter_initializers_and_relative_prefix(
        self,
    ) -> None:
        # #1382: every entry named METADATA or PKG-INFO must resolve to a regular file
        # before directory recursion or counting (empty METADATA/PKG-INFO directory or
        # symlink to directory or non-regular entry is rejected, never zero-match absence).
        for rel_dir, meta_name in (
            ("openai-1.0.dist-info", "METADATA"),
            ("google-1.0.egg-info", "PKG-INFO"),
            ("nested_pkg", "METADATA"),
            ("nested_pkg", "PKG-INFO"),
        ):
            with self.subTest(dir_entry_case=f"{rel_dir}/{meta_name}"):
                with tempfile.TemporaryDirectory() as tmpdir:
                    prefix = Path(tmpdir) / "phenix_meta_dir"
                    sp = prefix / "lib" / "python3.9" / "site-packages"
                    (sp / rel_dir / meta_name).mkdir(parents=True, exist_ok=True)
                    with self.assertRaisesRegex(
                        ValueError,
                        f"Metadata entry 'PHENIX_PREFIX/lib/python3\\.9/site-packages/{rel_dir}/{meta_name}' "
                        "must resolve to a regular file",
                    ):
                        p2m.inspect_provider_metadata(prefix)

        # Owned symlink named METADATA pointing to an internal directory within prefix fails closed
        with tempfile.TemporaryDirectory() as tmpdir:
            prefix = Path(tmpdir) / "phenix_meta_dir_symlink"
            sp = prefix / "lib" / "python3.9" / "site-packages"
            target_dir = prefix / "internal_empty_dir"
            target_dir.mkdir(parents=True, exist_ok=True)
            dist_dir = sp / "openai-1.0.dist-info"
            dist_dir.mkdir(parents=True, exist_ok=True)
            os.symlink(target_dir, dist_dir / "METADATA")
            with self.assertRaisesRegex(
                ValueError, "must resolve to a regular file"
            ):
                p2m.inspect_provider_metadata(prefix)

        # Owned non-regular (FIFO) METADATA entry fails closed before counting
        if hasattr(os, "mkfifo"):
            with tempfile.TemporaryDirectory() as tmpdir:
                prefix = Path(tmpdir) / "phenix_meta_fifo"
                sp = prefix / "lib" / "python3.9" / "site-packages"
                dist_dir = sp / "openai-1.0.dist-info"
                dist_dir.mkdir(parents=True, exist_ok=True)
                os.mkfifo(dist_dir / "METADATA")
                with self.assertRaisesRegex(
                    ValueError, "must resolve to a regular file"
                ):
                    p2m.inspect_provider_metadata(prefix)

        # #1383: direct bytecode (__init__.pyc) or extension initializer artifacts
        # (__init__.so, __init__.cpython-39-darwin.so, __init__.pyd) inside a top-level
        # adapter directory must fail closed and never be labeled namespace_only_directory,
        # while true empty namespace directories remain valid.
        for bad_init_name in (
            "__init__.pyc",
            "__init__.pyo",
            "__init__.so",
            "__init__.cpython-39-darwin.so",
            "__init__.pyd",
        ):
            with self.subTest(bad_direct_init=bad_init_name):
                with tempfile.TemporaryDirectory() as tmpdir:
                    prefix = Path(tmpdir) / "phenix_bad_init"
                    sp = prefix / "lib" / "python3.9" / "site-packages"
                    _write_text(
                        sp / "langchain_ollama" / bad_init_name,
                        "compiled_or_extension_stub",
                    )
                    with self.assertRaisesRegex(
                        ValueError,
                        "Unsupported direct package initializer artifact",
                    ):
                        p2m.inspect_provider_metadata(prefix)

        # True empty namespace directory remains valid as namespace_only_directory
        with tempfile.TemporaryDirectory() as tmpdir:
            prefix = Path(tmpdir) / "phenix_empty_ns"
            sp = prefix / "lib" / "python3.9" / "site-packages"
            (sp / "langchain_ollama").mkdir(parents=True, exist_ok=True)
            witness_ns = p2m.inspect_provider_metadata(prefix)
            self.assertEqual(
                witness_ns["native_adapter_modules"]["langchain_ollama"]["kind"],
                "namespace_only_directory",
            )

        # #1384: relative prefix Path("p") and its canonical absolute equivalent must
        # produce the exact same portable witness without false leak-check rejection,
        # while never emitting private prefix paths.
        with tempfile.TemporaryDirectory() as tmpdir:
            abs_prefix = (Path(tmpdir) / "p").resolve()
            sp = abs_prefix / "lib" / "python3.9" / "site-packages"
            _write_text(
                sp / "openai-1.0.dist-info" / "METADATA",
                "Metadata-Version: 2.1\nName: openai\nVersion: 1.0.0\n",
            )
            _write_text(sp / "langchain_openai.py", "# module\n")

            prev_cwd = Path.cwd()
            try:
                os.chdir(tmpdir)
                rel_witness = p2m.inspect_provider_metadata(Path("p"))
                abs_witness = p2m.inspect_provider_metadata(abs_prefix)
            finally:
                os.chdir(prev_cwd)

            self.assertEqual(rel_witness, abs_witness)
            self.assertEqual(
                p2m.canonical_json_bytes(rel_witness),
                p2m.canonical_json_bytes(abs_witness),
            )
            serialized_rel = p2m.canonical_json_bytes(rel_witness).decode("utf-8")
            self.assertNotIn(str(abs_prefix), serialized_rel)

        # #1384 follow-up (1498): with relative symlink p -> real_prefix,
        # 1) normal metadata produces identical portable witnesses across relative
        #    symlink Path("p"), absolute symlink alias, and resolved real_prefix;
        # 2) synthetic metadata leaking the lexical absolute alias (or resolved prefix)
        #    in Version is rejected identically by both relative Path("p") and
        #    absolute-alias calls.
        with tempfile.TemporaryDirectory() as tmpdir:
            real_tmp = Path(tmpdir).resolve()
            real_prefix = real_tmp / "real_phenix"
            abs_alias = real_tmp / "p"
            sp = real_prefix / "lib" / "python3.9" / "site-packages"
            meta_file = sp / "openai-1.0.dist-info" / "METADATA"
            _write_text(
                meta_file,
                "Metadata-Version: 2.1\nName: openai\nVersion: 1.0.0\n",
            )
            os.symlink(real_prefix, abs_alias)

            prev_cwd = Path.cwd()
            try:
                os.chdir(real_tmp)
                w_rel_link = p2m.inspect_provider_metadata(Path("p"))
                w_abs_link = p2m.inspect_provider_metadata(abs_alias)
                w_real = p2m.inspect_provider_metadata(real_prefix)
                self.assertEqual(w_rel_link, w_abs_link)
                self.assertEqual(w_rel_link, w_real)

                for leaked_val in (str(Path("p").absolute()), str(abs_alias), str(real_prefix)):
                    _write_text(
                        meta_file,
                        f"Metadata-Version: 2.1\nName: openai\nVersion: {leaked_val}\n",
                    )
                    with self.assertRaisesRegex(
                        ValueError,
                        "Refusing to serialize absolute PHENIX prefix path",
                    ):
                        p2m.inspect_provider_metadata(Path("p"))
                    with self.assertRaisesRegex(
                        ValueError,
                        "Refusing to serialize absolute PHENIX prefix path",
                    ):
                        p2m.inspect_provider_metadata(abs_alias)
            finally:
                os.chdir(prev_cwd)

    def test_internal_and_escaping_symlinks(self) -> None:
        # 1. Valid internal symlink resolving within prefix succeeds
        with tempfile.TemporaryDirectory() as tmpdir:
            prefix = Path(tmpdir) / "phenix_internal"
            sp = prefix / "lib" / "python3.9" / "site-packages"
            sp.mkdir(parents=True, exist_ok=True)
            wheel_store = prefix / "conda_pkgs" / "langchain_core-0.1.50.dist-info"
            expected_sha = _write_text(
                wheel_store / "METADATA",
                "Metadata-Version: 2.1\nName: langchain-core\nVersion: 0.1.50\n",
            )
            os.symlink(
                wheel_store,
                sp / "langchain_core-0.1.50.dist-info",
            )
            witness = p2m.inspect_provider_metadata(prefix)
            self.assertEqual(
                witness["matched_distributions"],
                [
                    {
                        "name": "langchain-core",
                        "path": (
                            "PHENIX_PREFIX/lib/python3.9/site-packages/"
                            "langchain_core-0.1.50.dist-info/METADATA"
                        ),
                        "sha256": expected_sha,
                        "version": "0.1.50",
                    }
                ],
            )

        # 2. Ambiguous internal symlink (two paths in site-packages resolving to same real dir) fails
        with tempfile.TemporaryDirectory() as tmpdir:
            prefix = Path(tmpdir) / "phenix_dup_symlink"
            sp = prefix / "lib" / "python3.9" / "site-packages"
            _write_text(
                sp / "real-1.0.dist-info" / "METADATA",
                "Metadata-Version: 2.1\nName: openai\nVersion: 1.0\n",
            )
            os.symlink(sp / "real-1.0.dist-info", sp / "alias-1.0.dist-info")
            with self.assertRaisesRegex(ValueError, "Symlink ambiguity"):
                p2m.inspect_provider_metadata(prefix)

        # 3. Ambiguous top-level adapter (both .py file and package dir present) fails
        with tempfile.TemporaryDirectory() as tmpdir:
            prefix = Path(tmpdir) / "phenix_ambig_adapter"
            sp = prefix / "lib" / "python3.9" / "site-packages"
            _write_text(sp / "langchain_openai.py", "")
            _write_text(sp / "langchain_openai" / "__init__.py", "")
            with self.assertRaisesRegex(ValueError, "Ambiguous top-level adapter"):
                p2m.inspect_provider_metadata(prefix)

        # 4. Escaping symlink fails closed without reading outside-prefix bytes
        with tempfile.TemporaryDirectory() as tmpdir:
            outside_dir = Path(tmpdir) / "outside_secret"
            outside_meta = outside_dir / "METADATA"
            _write_text(
                outside_meta,
                "Metadata-Version: 2.1\nName: openai\nVersion: 9.9.9\n",
            )
            prefix = Path(tmpdir) / "phenix_escape"
            sp = prefix / "lib" / "python3.9" / "site-packages"
            sp.mkdir(parents=True, exist_ok=True)
            os.symlink(outside_dir, sp / "escape-9.9.9.dist-info")
            with self.assertRaisesRegex(ValueError, "escapes PHENIX_PREFIX"):
                p2m.inspect_provider_metadata(prefix)

        # 5. Broken symlink inside site-packages fails closed
        with tempfile.TemporaryDirectory() as tmpdir:
            prefix = Path(tmpdir) / "phenix_broken_link"
            sp = prefix / "lib" / "python3.9" / "site-packages"
            sp.mkdir(parents=True, exist_ok=True)
            os.symlink(prefix / "missing_target", sp / "dangling_link")
            with self.assertRaises(ValueError):
                p2m.inspect_provider_metadata(prefix)

    def test_unreadable_and_traversal_errors_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prefix = Path(tmpdir) / "phenix_io_err"
            sp = prefix / "lib" / "python3.9" / "site-packages"
            _write_text(
                sp / "openai-1.0.dist-info" / "METADATA",
                "Metadata-Version: 2.1\nName: openai\nVersion: 1.0\n",
            )

            with mock.patch("os.scandir", side_effect=PermissionError("denied")):
                with self.assertRaisesRegex(
                    ValueError, "Directory traversal failed"
                ):
                    p2m.inspect_provider_metadata(prefix)

            orig_read_bytes = Path.read_bytes

            def _fail_metadata_read(self_path: Path) -> bytes:
                if self_path.name == "METADATA":
                    raise PermissionError("unreadable metadata")
                return orig_read_bytes(self_path)

            with mock.patch.object(Path, "read_bytes", _fail_metadata_read):
                with self.assertRaisesRegex(
                    ValueError, "Cannot read metadata file"
                ):
                    p2m.inspect_provider_metadata(prefix)

    def test_module_is_pure_stdlib_without_vendor_or_importlib_metadata(self) -> None:
        module_path = Path(p2m.__file__).resolve()
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        imported_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module.split(".")[0])

        forbidden = {
            "subprocess",
            "importlib",
            "cctbx",
            "iotbx",
            "libtbx",
            "phenix",
            "langchain",
            "openai",
            "google",
            "ollama",
        }
        self.assertTrue(imported_modules.isdisjoint(forbidden))
        self.assertTrue(imported_modules.issubset(sys.stdlib_module_names))


if __name__ == "__main__":
    unittest.main()
