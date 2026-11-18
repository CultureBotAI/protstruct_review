#!/usr/bin/env python3
"""Unit tests for the result-free Stage 2 U05 perturbation specification compiler."""

from __future__ import annotations

import ast
import copy
from decimal import Decimal
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import phenix_stage2_perturbation as p2p  # noqa: E402


PARENT_SHA_A = "a" * 64
PARENT_SHA_B = "b" * 64

# Static synthetic HMAC-SHA256 fixtures (key = b"protstruct-track2-v1", message UTF-8)
# matching .orchestration/evidence/1356-merge1321-stage2/u05-independent-hmac-vectors.json
EXPECTED_HMAC_VECTORS: tuple[tuple[str, str, str], ...] = (
    (
        "ANON_0001",
        "414e4f4e5f30303031",
        "0cd84d2c21d965797d579f77a7963f487673709b61b6a4b6d1b86d751a7595c0",
    ),
    (
        "ANON_0048",
        "414e4f4e5f30303438",
        "bcd7d3192b7844156ef20dd1b2c162ae8f1f1f2c0f69a0570ca5b3485160982d",
    ),
    (
        "fixture-target-A",
        "666978747572652d7461726765742d41",
        "369fa4b291a312ffa66fa819a16bb626c9cd3b0a66429d23ddf20c54d4b7aeb0",
    ),
)


class TestPhenixStage2Perturbation(unittest.TestCase):
    """Verify U05 perturbation specification compilation, hashes, and fail-closed guards."""

    def test_independent_hmac_vectors_and_seed_determinism(self) -> None:
        self.assertEqual(p2p.TRACK2_HMAC_KEY_UTF8, "protstruct-track2-v1")
        self.assertEqual(p2p.TRACK2_HMAC_KEY_BYTES, b"protstruct-track2-v1")
        self.assertEqual(p2p.TRACK2_HMAC_ALGORITHM, "HMAC-SHA256")
        self.assertEqual(p2p.TRACK2_MESSAGE_ENCODING, "utf-8")

        for anon_id, expected_msg_hex, expected_digest in EXPECTED_HMAC_VECTORS:
            with self.subTest(anon_target_id=anon_id):
                digest1 = p2p.track2_seed_digest(anon_id)
                digest2 = p2p.track2_seed_digest(anon_id)
                self.assertEqual(digest1, expected_digest)
                self.assertEqual(digest2, expected_digest)
                self.assertEqual(len(digest1), 64)

                spec = p2p.build_perturbation_spec(anon_id, PARENT_SHA_A, 1.80)
                self.assertEqual(spec["seed_digest"], expected_digest)
                self.assertEqual(
                    spec["seed_derivation"],
                    {
                        "algorithm": "HMAC-SHA256",
                        "domain_key_utf8": "protstruct-track2-v1",
                        "key_secrecy_claim": (
                            "public_deterministic_domain_separator_not_secret"
                        ),
                        "message_field": "anon_target_id",
                        "message_encoding": "utf-8",
                        "message_utf8_hex": expected_msg_hex,
                        "seed_digest_hex": expected_digest,
                        "prng_seed_conversion_status": (
                            "unresolved_pending_stage2_executable_freeze"
                        ),
                    },
                )
                self.assertEqual(
                    spec["anonymization_verification_status"],
                    "syntax_validated_only_not_runtime_anonymization_proof",
                )

    def test_anon_target_id_validation_and_bare_pdb_rejection(self) -> None:
        invalid_ids: tuple[object, ...] = (
            None,
            123,
            "",
            "   ",
            " ANON_0001",
            "ANON_0001 ",
            "ANON 0001",
            "ANON/0001",
            "ANON:0001",
            "-leading_dash",
            ".leading_dot",
            "_leading_underscore",
            "ANON_0001\n",
            "ANON_0001_Å",
            "αβγ",
            "A" * 129,
            # Bare 4-character PDB accession codes must be rejected
            "1SAR",
            "1sar",
            "1AKE",
            "4HHB",
            "9ZZZ",
        )
        for bad_id in invalid_ids:
            with self.subTest(bad_id=bad_id):
                with self.assertRaises(ValueError):
                    p2p.track2_seed_digest(bad_id)  # type: ignore[arg-type]
                with self.assertRaises(ValueError):
                    p2p.build_perturbation_spec(
                        bad_id,  # type: ignore[arg-type]
                        PARENT_SHA_A,
                        1.75,
                    )

    def test_five_ordered_operations_and_units(self) -> None:
        spec = p2p.build_perturbation_spec("ANON_0001", PARENT_SHA_A, 1.35)
        ops = spec["operations"]
        self.assertEqual(len(ops), 5)
        self.assertEqual([op["step_index"] for op in ops], [1, 2, 3, 4, 5])
        self.assertEqual(
            [op["operation_id"] for op in ops],
            [
                "strip_crystallographic_waters",
                "strip_anisou_convert_isotropic",
                "lognormal_isotropic_b_factor_jitter",
                "coordinate_sites_shake",
                "surface_and_pocket_chi1_chi2_torsion_noise",
            ],
        )

        # Step 1: strip HOH / DOD
        self.assertEqual(ops[0]["action"], "strip_residues")
        self.assertEqual(ops[0]["residue_names"], ["HOH", "DOD"])

        # Step 2: strip ANISOU / convert to isotropic B
        self.assertEqual(ops[1]["records_stripped"], ["ANISOU"])
        self.assertEqual(ops[1]["target_adp_mode"], "isotropic")

        # Step 3: +/-20% log-normal B jitter clamped to [5, 150] A^2
        self.assertEqual(ops[2]["distribution"], "lognormal")
        self.assertEqual(ops[2]["nominal_fractional_jitter_percent"], 20.0)
        self.assertEqual(ops[2]["nominal_fractional_jitter"], 0.20)
        self.assertEqual(ops[2]["clamp_min_b_iso"], 5.0)
        self.assertEqual(ops[2]["clamp_max_b_iso"], 150.0)
        self.assertEqual(ops[2]["unit"], "angstrom_squared")

        # Step 4: sites.shake = 0.25 A for d_min < 1.50 A
        self.assertEqual(ops[3]["action"], "sites.shake")
        self.assertEqual(ops[3]["parameter_path"], "sites.shake")
        self.assertEqual(ops[3]["parameter_value"], 0.25)
        self.assertNotIn("target_rmsd", ops[3])
        self.assertEqual(ops[3]["unit"], "angstrom")
        self.assertEqual(ops[3]["d_min_threshold_angstrom"], 1.5)
        self.assertEqual(ops[3]["regime"], "d_min_lt_1.50")

        # Step 5: 15 deg RMS chi1/chi2 torsion noise on 10% of surface and binding-pocket sidechains
        self.assertEqual(ops[4]["action"], "chi1_chi2_torsion_noise")
        self.assertEqual(ops[4]["torsion_angles"], ["chi1", "chi2"])
        self.assertEqual(ops[4]["rms_perturbation"], 15.0)
        self.assertEqual(ops[4]["unit"], "degrees")
        self.assertEqual(ops[4]["subset_fraction"], 0.10)
        self.assertEqual(ops[4]["subset_percent"], 10.0)
        self.assertEqual(
            ops[4]["eligible_classes"],
            ["surface_sidechains", "binding_pocket_sidechains"],
        )

    def test_d_min_1_50_boundary_and_resolution_tiers(self) -> None:
        cases: tuple[tuple[float | int | Decimal, float, str, str], ...] = (
            (0.95, 0.25, "d_min_lt_1.50", "T1"),
            (1.10, 0.25, "d_min_lt_1.50", "T2"),
            (1.4999, 0.25, "d_min_lt_1.50", "T2"),
            (Decimal("1.4999"), 0.25, "d_min_lt_1.50", "T2"),
            (1.5, 0.35, "d_min_ge_1.50", "T3"),
            (1.50, 0.35, "d_min_ge_1.50", "T3"),
            (Decimal("1.50"), 0.35, "d_min_ge_1.50", "T3"),
            (2.79, 0.35, "d_min_ge_1.50", "T3"),
            (2.80, 0.35, "d_min_ge_1.50", "T4"),
            (3.50, 0.35, "d_min_ge_1.50", "T4"),
            (2, 0.35, "d_min_ge_1.50", "T3"),
        )
        for d_val, expected_shake, expected_regime, expected_tier in cases:
            with self.subTest(d_min=d_val):
                spec = p2p.build_perturbation_spec("ANON_0001", PARENT_SHA_A, d_val)
                shake_op = spec["operations"][3]
                self.assertEqual(shake_op["parameter_value"], expected_shake)
                self.assertNotIn("target_rmsd", shake_op)
                self.assertEqual(shake_op["regime"], expected_regime)
                self.assertEqual(spec["resolution_tier"], expected_tier)

    def test_determinism_json_roundtrip_and_spec_hash_binding(self) -> None:
        spec1 = p2p.build_perturbation_spec("ANON_0001", PARENT_SHA_A, 1.49)
        spec2 = p2p.build_perturbation_spec("ANON_0001", PARENT_SHA_A, 1.49)
        self.assertEqual(spec1, spec2)
        self.assertEqual(
            p2p.canonical_json_bytes(spec1),
            p2p.canonical_json_bytes(spec2),
        )

        # Pure JSON round-trip preserves exact structure
        roundtripped = json.loads(p2p.canonical_json_bytes(spec1).decode("utf-8"))
        self.assertEqual(roundtripped, spec1)

        # Verify spec_sha256 equals canonical_json_sha256 of canonical payload
        payload1 = {
            k: v
            for k, v in spec1.items()
            if k not in ("spec_sha256", "epistemic_note")
        }
        self.assertEqual(spec1["spec_sha256"], p2p.canonical_json_sha256(payload1))

        # Different target ID, parent SHA, or d_min produces distinct spec_sha256
        spec_other_id = p2p.build_perturbation_spec("ANON_0048", PARENT_SHA_A, 1.49)
        spec_other_parent = p2p.build_perturbation_spec("ANON_0001", PARENT_SHA_B, 1.49)
        spec_other_dmin = p2p.build_perturbation_spec("ANON_0001", PARENT_SHA_A, 1.50)
        self.assertNotEqual(spec1["spec_sha256"], spec_other_id["spec_sha256"])
        self.assertNotEqual(spec1["spec_sha256"], spec_other_parent["spec_sha256"])
        self.assertNotEqual(spec1["spec_sha256"], spec_other_dmin["spec_sha256"])

        # Mutating source policy hash, operation order, or HMAC encoding changes canonical digest
        tampered_source = copy.deepcopy(payload1)
        tampered_source["approved_source"]["sha256"] = "c" * 64
        self.assertNotEqual(
            p2p.canonical_json_sha256(tampered_source), spec1["spec_sha256"]
        )

        tampered_ops = copy.deepcopy(payload1)
        tampered_ops["operations"] = list(reversed(tampered_ops["operations"]))
        self.assertNotEqual(
            p2p.canonical_json_sha256(tampered_ops), spec1["spec_sha256"]
        )

        tampered_encoding = copy.deepcopy(payload1)
        tampered_encoding["seed_derivation"]["message_encoding"] = "ascii"
        self.assertNotEqual(
            p2p.canonical_json_sha256(tampered_encoding), spec1["spec_sha256"]
        )

    def test_approved_source_pin_and_tamper_rejection(self) -> None:
        spec = p2p.build_perturbation_spec("ANON_0001", PARENT_SHA_A, 1.80)
        self.assertEqual(
            spec["approved_source"],
            {
                "path": "ref/research/phenix_step1_user_selections_2026-11-15.md",
                "section": "U05",
                "sha256": (
                    "14bbb0c9dc1883c2404f40193e135a4aaa974d8ab605fe95bb78d44c6a704a7b"
                ),
                "source_bytes_verified": True,
            },
        )

        # Callers cannot substitute an arbitrary source digest or path and label it approved
        with self.assertRaisesRegex(ValueError, "source_sha256"):
            p2p.build_perturbation_spec(
                "ANON_0001",
                PARENT_SHA_A,
                1.80,
                source_sha256="f" * 64,
            )
        with self.assertRaisesRegex(ValueError, "source_path"):
            p2p.build_perturbation_spec(
                "ANON_0001",
                PARENT_SHA_A,
                1.80,
                source_path="ref/research/other_note.md",
            )
        with self.assertRaises(TypeError):
            p2p.build_perturbation_spec(
                "ANON_0001",
                PARENT_SHA_A,
                1.80,
                verify_source_file_bytes=False,  # type: ignore[call-arg]
            )

        # Owned fake-root missing-file and changed-file checks (#1376)
        real_source_bytes = (p2p.REPO_ROOT / p2p.APPROVED_SOURCE_PATH).read_bytes()
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_root = Path(tmpdir)
            with mock.patch.object(p2p, "REPO_ROOT", fake_root):
                with self.assertRaisesRegex(
                    ValueError, "Approved U05 policy source file is missing"
                ):
                    p2p.build_perturbation_spec("ANON_0001", PARENT_SHA_A, 1.80)

                fake_source_file = fake_root / p2p.APPROVED_SOURCE_PATH
                fake_source_file.parent.mkdir(parents=True, exist_ok=True)
                fake_source_file.write_bytes(real_source_bytes + b"\n")
                with self.assertRaisesRegex(
                    ValueError, "does not match pinned"
                ):
                    p2p.build_perturbation_spec("ANON_0001", PARENT_SHA_A, 1.80)

                fake_source_file.write_bytes(real_source_bytes)
                verified_spec = p2p.build_perturbation_spec(
                    "ANON_0001", PARENT_SHA_A, 1.80
                )
                self.assertTrue(
                    verified_spec["approved_source"]["source_bytes_verified"]
                )

    def test_invalid_d_min_parent_sha_and_track_isolation(self) -> None:
        bad_d_mins: tuple[object, ...] = (
            True,
            False,
            0,
            0.0,
            -1.2,
            Decimal("0"),
            Decimal("-0.5"),
            float("nan"),
            float("inf"),
            float("-inf"),
            Decimal("NaN"),
            Decimal("Infinity"),
            Decimal("1.12345678901234567890123456789"),
            "1.50",
            None,
        )
        for bad_d in bad_d_mins:
            with self.subTest(bad_d_min=bad_d):
                with self.assertRaises(ValueError):
                    p2p.build_perturbation_spec(
                        "ANON_0001",
                        PARENT_SHA_A,
                        bad_d,  # type: ignore[arg-type]
                    )

        bad_shas: tuple[object, ...] = (
            "",
            "a" * 63,
            "a" * 65,
            "A" * 64,
            "g" * 64,
            12345,
            None,
        )
        for bad_sha in bad_shas:
            with self.subTest(bad_parent_sha=bad_sha):
                with self.assertRaises(ValueError):
                    p2p.build_perturbation_spec(
                        "ANON_0001",
                        bad_sha,  # type: ignore[arg-type]
                        1.80,
                    )

        # Track (ii) isolation: never mix clean_null_stability or parameter_sensitivity
        for bad_track in (
            "clean_null_stability",
            "parameter_sensitivity",
            "pooled",
            "track_i",
            "track_iii",
            "",
            None,
        ):
            with self.subTest(bad_track=bad_track):
                with self.assertRaisesRegex(ValueError, "perturbation_recovery"):
                    p2p.build_perturbation_spec(
                        "ANON_0001",
                        PARENT_SHA_A,
                        1.80,
                        track=bad_track,  # type: ignore[arg-type]
                    )

    def test_unresolved_execution_requirements_and_fail_closed_guard(self) -> None:
        spec = p2p.build_perturbation_spec("ANON_0001", PARENT_SHA_A, 1.65)
        self.assertEqual(spec["registration_status"], "selected_decisions_recorded")
        self.assertEqual(
            spec["stage2_status"],
            "result_free_u05_perturbation_spec_not_executable",
        )
        self.assertFalse(spec["executable"])
        self.assertFalse(spec["execution_authorized"])
        self.assertFalse(spec["frozen_result_free"])
        self.assertFalse(spec["executed"])
        self.assertTrue(spec["pooling_forbidden"])
        self.assertEqual(
            spec["unpooled_from_tracks"],
            ["clean_null_stability", "parameter_sensitivity"],
        )

        req_by_id = {
            item["requirement_id"]: item
            for item in spec["unresolved_execution_requirements"]
        }
        req_ids = [
            item["requirement_id"]
            for item in spec["unresolved_execution_requirements"]
        ]
        self.assertEqual(
            req_ids,
            [
                "anisou_to_b_iso_conversion_convention",
                "lognormal_b_jitter_parameterization_and_atom_scope",
                "prng_algorithm_seed_conversion_and_stream_version",
                "canonical_atom_and_residue_ordering",
                "sites_shake_sampling_semantics_and_atom_population",
                "surface_and_binding_pocket_eligibility_and_overlap",
                "ten_percent_subset_rounding_and_sampling_rule",
                "torsion_atom_and_altloc_population_and_subset_unit",
                "missing_chi2_and_chi1_chi2_torsion_correlation",
            ],
        )
        shake_req_desc = req_by_id[
            "sites_shake_sampling_semantics_and_atom_population"
        ]["description"]
        self.assertNotIn("restraint-aware", shake_req_desc)
        self.assertIn("rms_difference", shake_req_desc)

        torsion_pop_req = req_by_id[
            "torsion_atom_and_altloc_population_and_subset_unit"
        ]
        self.assertEqual(
            torsion_pop_req["step_operation_id"],
            "surface_and_pocket_chi1_chi2_torsion_noise",
        )
        self.assertIn("held fixed", torsion_pop_req["description"])
        self.assertIn("residues or individual alternate conformers", torsion_pop_req["description"])

        # Executable-recipe guard always rejects result-free contract
        with self.assertRaisesRegex(
            ValueError,
            "mandatory execution requirements remain unresolved",
        ):
            p2p.require_executable_perturbation_spec(spec)

        # Even if a caller mutates flags and clears unresolved_execution_requirements, guard still rejects
        forged = copy.deepcopy(spec)
        forged["executable"] = True
        forged["execution_authorized"] = True
        forged["frozen_result_free"] = True
        forged["registration_status"] = "frozen_result_free"
        forged["unresolved_execution_requirements"] = []
        with self.assertRaisesRegex(
            ValueError,
            "anisou_to_b_iso_conversion_convention",
        ):
            p2p.require_executable_perturbation_spec(forged)

        with self.assertRaises(ValueError):
            p2p.require_executable_perturbation_spec("not_a_mapping")  # type: ignore[arg-type]

    def test_module_is_pure_stdlib_and_free_of_subprocesses(self) -> None:
        module_path = Path(p2p.__file__).resolve()
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        imported_modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_modules.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.add(node.module.split(".")[0])

        forbidden = {"subprocess", "os", "random", "numpy", "scipy", "cctbx", "iotbx"}
        self.assertTrue(imported_modules.isdisjoint(forbidden))
        self.assertTrue(imported_modules.issubset(sys.stdlib_module_names))


if __name__ == "__main__":
    unittest.main()
