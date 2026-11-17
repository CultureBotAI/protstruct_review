#!/usr/bin/env python3
"""Unit tests for result-free Stage 2 PHENIX flag-generation and HKL/sleep membership guards."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import sys
import unittest

from phenix_stage2_flags import (
    ALLOWED_SOURCE_STATES,
    CANONICAL_ARM_IDS,
    CANONICAL_GENERATION_KEY,
    CANONICAL_SOURCE_LAYERS,
    NATIVE_EFFECTIVE_FILE_COMPATIBILITY,
    REGISTRATION_STATUS,
    STAGE2_FLAGS_STATUS,
    STATIC_WITNESS_PATH,
    WITNESSED_GENERATION_PATHS,
    verify_flag_generation_guard,
    verify_hkl_and_sleep_membership,
)


def _valid_arm1b_sources(
    *,
    primary_gen: str = "r_free_flags.generate=False",
    backup_gen: str = "xray_data.r_free_flags.generate=False",
    actual_gen: str = "data_manager.fmodel.xray_data.r_free_flags.generate=False",
    effective_phil: str = (
        "data_manager {\n"
        "  fmodel {\n"
        "    xray_data {\n"
        "      r_free_flags {\n"
        "        generate = False\n"
        "      }\n"
        "    }\n"
        "  }\n"
        "}\n"
    ),
) -> dict[str, dict[str, object]]:
    return {
        "primary_command": {
            "source_id": "src_primary_cmd",
            "state": "supplied",
            "argv": [
                "phenix.refine",
                "model_in.pdb",
                "data_in.mtz",
                primary_gen,
                "main.number_of_macro_cycles=3",
            ],
        },
        "mechanical_backup": {
            "source_id": "src_backup_cmd",
            "state": "supplied",
            "argv": [
                "phenix.refine",
                "model_in.pdb",
                "data_in.mtz",
                backup_gen,
                "main.number_of_macro_cycles=1",
            ],
        },
        "actual_command": {
            "source_id": "src_actual_cmd",
            "state": "supplied",
            "argv": [
                "phenix.refine",
                "model_in.pdb",
                "data_in.mtz",
                actual_gen,
                "main.number_of_macro_cycles=3",
            ],
        },
        "effective_eff": {
            "source_id": "src_effective_eff",
            "state": "supplied",
            "phil_text": effective_phil,
        },
    }


class TestStage2FlagStaticWitnessAndConstants(unittest.TestCase):
    """Test committed static witness artifact and module epistemic boundaries."""

    def test_constants_and_epistemic_boundaries(self) -> None:
        self.assertEqual(REGISTRATION_STATUS, "selected_decisions_recorded")
        self.assertEqual(
            STAGE2_FLAGS_STATUS, "prospective_flag_guard_not_development_frozen"
        )
        self.assertEqual(NATIVE_EFFECTIVE_FILE_COMPATIBILITY, "unassessed")
        self.assertEqual(
            CANONICAL_GENERATION_KEY,
            "data_manager.fmodel.xray_data.r_free_flags.generate",
        )
        self.assertEqual(
            WITNESSED_GENERATION_PATHS,
            frozenset(
                {
                    "r_free_flags.generate",
                    "xray_data.r_free_flags.generate",
                    "data_manager.fmodel.xray_data.r_free_flags.generate",
                }
            ),
        )
        self.assertEqual(
            CANONICAL_SOURCE_LAYERS,
            ("primary_command", "mechanical_backup", "actual_command", "effective_eff"),
        )
        self.assertEqual(
            ALLOWED_SOURCE_STATES,
            frozenset({"supplied", "not_applicable", "unavailable"}),
        )
        self.assertEqual(
            CANONICAL_ARM_IDS,
            ("1a", "1b", "2", "3a", "3b-refine-only", "3b-plus-readyset"),
        )

    def test_static_witness_json_matches_witnessed_paths(self) -> None:
        repo_root = Path(__file__).resolve().parent.parent
        witness_file = repo_root / STATIC_WITNESS_PATH
        self.assertTrue(witness_file.is_file(), f"Missing {witness_file}")
        raw_bytes = witness_file.read_bytes()
        self.assertEqual(
            hashlib.sha256(raw_bytes).hexdigest(),
            "68a5f2aec79d85bbb68f8a21dd8a66894508b6645a7326dd9e08bfa5b6575d13",
        )
        payload = json.loads(raw_bytes.decode("utf-8"))
        self.assertEqual(set(payload.keys()), {"scope", "files", "observations"})
        self.assertEqual(
            payload["scope"],
            "Static source-byte inspection only; no imports, commands, native execution or provider calls. Names and source defaults are not effective-run proof.",
        )
        self.assertEqual(
            payload["files"],
            [
                {
                    "path": "PHENIX_PREFIX/lib/python3.9/site-packages/phenix/refinement/driver.py",
                    "sha256": "10782c18028f56bff8e1faee0085599ec7c5c7497953a2ca3e971453b72f4510",
                    "line_count": 929,
                    "source_lines": [579, 580, 590, 620, 634, 635],
                },
                {
                    "path": "PHENIX_PREFIX/lib/python3.9/site-packages/iotbx/data_manager/miller_array.py",
                    "sha256": "7c240926ec5f504bcdf5de0dc4c0c9317ba67d954769359f1a73ef9b38dbde39",
                    "line_count": 930,
                    "source_lines": [513, 514, 516, 517, 518],
                },
                {
                    "path": "PHENIX_PREFIX/lib/python3.9/site-packages/iotbx/extract_xtal_data.py",
                    "sha256": "ae19ae6c380fcf4a080897a6820aac9e2b8a49eeabac973c5126b7d793980d5c",
                    "line_count": 832,
                    "source_lines": [161, 179, 222, 223],
                },
            ],
        )
        obs_by_id = {obs["id"]: obs for obs in payload["observations"]}
        self.assertEqual(
            set(obs_by_id.keys()),
            {
                "effective_generation_path",
                "effective_dump_lineage",
                "default_is_not_observation",
            },
        )
        self.assertEqual(
            obs_by_id["effective_generation_path"]["value"],
            CANONICAL_GENERATION_KEY,
        )
        self.assertEqual(
            obs_by_id["effective_dump_lineage"]["value"],
            "driver.write_params_file emits dm_working_phil before refinement master parameters",
        )
        self.assertEqual(
            obs_by_id["effective_dump_lineage"]["source"],
            "phenix/refinement/driver.py:579-585",
        )
        self.assertEqual(
            obs_by_id["default_is_not_observation"]["value"],
            "generate=False is a static default at iotbx/extract_xtal_data.py:179; missing effective generation evidence remains unresolved, never inferred False.",
        )

        # Two shorthand paths come from U12 / retained langchain static witness
        langchain_witness_file = (
            repo_root
            / "ref/research/data/phenix_langchain_static_witness_2026-11-15.json"
        )
        self.assertTrue(langchain_witness_file.is_file())
        lc_payload = json.loads(langchain_witness_file.read_text(encoding="utf-8"))
        lc_obs_by_id = {obs["id"]: obs for obs in lc_payload["observations"]}
        self.assertIn("U12-W4", lc_obs_by_id)
        self.assertIn(
            "r_free_flags.generate=True", lc_obs_by_id["U12-W4"]["claim"]
        )
        u12_doc = (
            repo_root / "ref/research/phenix_step1_user_selections_2026-11-15.md"
        ).read_text(encoding="utf-8")
        self.assertIn("r_free_flags.generate=True", u12_doc)
        self.assertIn("xray_data.r_free_flags.generate=True", u12_doc)
        self.assertEqual(
            WITNESSED_GENERATION_PATHS,
            frozenset(
                {
                    "r_free_flags.generate",
                    "xray_data.r_free_flags.generate",
                    obs_by_id["effective_generation_path"]["value"],
                }
            ),
        )

    def test_module_uses_only_stdlib_imports(self) -> None:
        mod_path = Path(__file__).resolve().parent / "phenix_stage2_flags.py"
        tree = ast.parse(mod_path.read_text(encoding="utf-8"))
        stdlib_names = sys.stdlib_module_names
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    self.assertIn(root, stdlib_names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                root = node.module.split(".")[0]
                self.assertIn(root, stdlib_names)


class TestFlagGenerationGuard(unittest.TestCase):
    """Test verify_flag_generation_guard across grammar, source layers, and fail-closed rules."""

    def test_valid_arm1b_all_three_witnessed_spellings_and_brace_forms(self) -> None:
        for effective_phil in (
            "r_free_flags.generate = False\n",
            "xray_data.r_free_flags.generate = false\n",
            "data_manager.fmodel.xray_data.r_free_flags.generate = False\n",
            "r_free_flags { generate = False }\n",
            "xray_data { r_free_flags { generate = False } }\n",
            "data_manager { fmodel { xray_data { r_free_flags { generate = False } } } }\n",
            "data_manager.fmodel { xray_data.r_free_flags { generate = False } }\n",
        ):
            with self.subTest(effective_phil=effective_phil.strip()):
                sources = _valid_arm1b_sources(effective_phil=effective_phil)
                res = verify_flag_generation_guard(arm="1b", sources=sources)
                self.assertTrue(res["guard_ok"])
                self.assertTrue(res["passed"])
                self.assertFalse(res["incomplete"])
                self.assertEqual(res["status"], "VERIFIED_SUPPLIED_SOURCES_FALSE")
                self.assertTrue(res["effective_generation_explicit_false"])
                self.assertEqual(
                    res["native_effective_file_compatibility"], "unassessed"
                )
                self.assertEqual(res["registration_status"], REGISTRATION_STATUS)
                self.assertFalse(res["executed"])
                for occ in res["generation_occurrences"]:
                    self.assertEqual(occ["canonical_key"], CANONICAL_GENERATION_KEY)
                    self.assertIs(occ["value"], False)

    def test_rejects_unwitnessed_refinement_input_alias_and_abbreviations(self) -> None:
        bad_paths = (
            "refinement.input.xray_data.r_free_flags.generate = False",
            "refinement { input { xray_data { r_free_flags { generate = False } } } }",
            "r_free_flags.gen = False",
            "generate = False",
            "xray_data.generate = False",
            "unknown.scope.param = False",
        )
        for bad_phil in bad_paths:
            with self.subTest(bad_phil=bad_phil):
                sources = _valid_arm1b_sources(
                    effective_phil=f"{bad_phil}\nr_free_flags.generate = False\n"
                )
                with self.assertRaisesRegex(
                    ValueError,
                    r"unsupported, unknown, or abbreviated PHIL parameter path",
                ):
                    verify_flag_generation_guard(arm="1b", sources=sources)

    def test_rejects_any_true_request_across_any_layer_even_if_overridden(self) -> None:
        # 1. True in primary_command
        s1 = _valid_arm1b_sources(primary_gen="r_free_flags.generate=True")
        with self.assertRaisesRegex(
            ValueError, r"Forbidden R-free flag generation request.*primary_command"
        ):
            verify_flag_generation_guard(arm="1b", sources=s1)

        # 2. True in unused mechanical_backup on Arm 1b
        s2 = _valid_arm1b_sources(backup_gen="xray_data.r_free_flags.generate=True")
        with self.assertRaisesRegex(
            ValueError, r"Forbidden R-free flag generation request.*mechanical_backup"
        ):
            verify_flag_generation_guard(arm="1b", sources=s2)

        # 3. True in actual_command followed by False in actual_command
        s3 = _valid_arm1b_sources()
        s3["actual_command"]["argv"] = [
            "phenix.refine",
            "model_in.pdb",
            "data_in.mtz",
            "r_free_flags.generate=True",
            "r_free_flags.generate=False",
        ]
        with self.assertRaisesRegex(
            ValueError, r"Forbidden R-free flag generation request.*actual_command"
        ):
            verify_flag_generation_guard(arm="1b", sources=s3)

        # 4. True followed by False inside effective_eff
        s4 = _valid_arm1b_sources(
            effective_phil=(
                "r_free_flags.generate = True\n"
                "data_manager.fmodel.xray_data.r_free_flags.generate = False\n"
            )
        )
        with self.assertRaisesRegex(
            ValueError, r"Forbidden R-free flag generation request.*effective_eff"
        ):
            verify_flag_generation_guard(arm="1b", sources=s4)

        # 5. True in referenced parameter file even when effective_eff has False
        s5 = _valid_arm1b_sources()
        s5["primary_command"]["argv"] = [
            "phenix.refine",
            "model_in.pdb",
            "data_in.mtz",
            "extra_params.eff",
        ]
        with self.assertRaisesRegex(
            ValueError, r"Forbidden R-free flag generation request.*extra_params\.eff"
        ):
            verify_flag_generation_guard(
                arm="1b",
                sources=s5,
                parameter_files={
                    "extra_params.eff": (
                        "xray_data.r_free_flags.generate = True\n"
                        "xray_data.r_free_flags.generate = False\n"
                    )
                },
            )

    def test_requires_explicit_false_in_effective_eff_never_infers_default(self) -> None:
        sources = _valid_arm1b_sources(
            effective_phil="main.number_of_macro_cycles = 3\n"
        )
        with self.assertRaisesRegex(
            ValueError,
            r"sources\['effective_eff'\] is missing an explicit r_free_flags\.generate = False",
        ):
            verify_flag_generation_guard(arm="1b", sources=sources)

    def test_comments_and_quoted_strings_do_not_spoof_or_trigger_comments(self) -> None:
        # A '#' comment containing True is ignored, and '# ... = False' does not satisfy effective False
        sources_comment_only = _valid_arm1b_sources(
            effective_phil=(
                "# r_free_flags.generate = False\n"
                "main.number_of_macro_cycles = 3\n"
            )
        )
        with self.assertRaisesRegex(
            ValueError,
            r"sources\['effective_eff'\] is missing an explicit r_free_flags\.generate = False",
        ):
            verify_flag_generation_guard(arm="1b", sources=sources_comment_only)

        # Quoted value containing '#' and 'r_free_flags.generate = False' is parsed as a string value for output.prefix
        sources_quoted_spoof = _valid_arm1b_sources(
            effective_phil='output.prefix = "run1 # r_free_flags.generate = False"\n'
        )
        with self.assertRaisesRegex(
            ValueError,
            r"sources\['effective_eff'\] is missing an explicit r_free_flags\.generate = False",
        ):
            verify_flag_generation_guard(arm="1b", sources=sources_quoted_spoof)

        # Quoted value with '#' plus actual explicit False passes
        sources_valid_quote = _valid_arm1b_sources(
            effective_phil=(
                "# comment mentioning r_free_flags.generate = True\n"
                'output.prefix = "prefix_with_#_hash"\n'
                "r_free_flags.generate = False\n"
            )
        )
        res = verify_flag_generation_guard(arm="1b", sources=sources_valid_quote)
        self.assertTrue(res["guard_ok"])

    def test_rejects_malformed_phil_syntax_and_unknown_truth_values(self) -> None:
        bad_phils = (
            "r_free_flags { generate = False\n",  # unclosed brace
            "r_free_flags.generate = False }\n",  # extra closing brace
            "r_free_flags.generate = Auto\n",  # unknown truth value Auto
            "r_free_flags.generate = None\n",  # unknown truth value None
            "r_free_flags.generate = 0\n",  # integer 0 rejected for bool
            'r_free_flags.generate = "False"\n',  # quoted boolean rejected
            'output.prefix = "unterminated\nr_free_flags.generate = False\n',
            'output.prefix = "$HOME/out"\nr_free_flags.generate = False\n',
            "r_free_flags.generate = $(echo False)\n",
        )
        for bad_phil in bad_phils:
            with self.subTest(bad_phil=bad_phil):
                sources = _valid_arm1b_sources(effective_phil=bad_phil)
                with self.assertRaises(ValueError):
                    verify_flag_generation_guard(arm="1b", sources=sources)

    def test_rejects_opaque_command_strings_shell_meta_and_unclassified_argv(self) -> None:
        # Opaque command string instead of argv token list
        s_str = _valid_arm1b_sources()
        s_str["primary_command"]["argv"] = (
            "phenix.refine model.pdb data.mtz r_free_flags.generate=False"
        )
        with self.assertRaisesRegex(
            ValueError, r"argv must be a non-empty sequence of string tokens"
        ):
            verify_flag_generation_guard(arm="1b", sources=s_str)

        # Shell metacharacters / interpolation in argv
        for bad_tok in (
            "r_free_flags.generate=$GEN",
            "model*.pdb",
            "data.mtz;rm",
            "--overwrite",
            "mystery_positional_arg",
        ):
            with self.subTest(bad_tok=bad_tok):
                s_bad = _valid_arm1b_sources()
                s_bad["primary_command"]["argv"] = [
                    "phenix.refine",
                    "model_in.pdb",
                    "data_in.mtz",
                    bad_tok,
                ]
                with self.assertRaises(ValueError):
                    verify_flag_generation_guard(arm="1b", sources=s_bad)

    def test_parameter_file_resolution_and_cycle_detection(self) -> None:
        # Unresolved parameter file in argv fails closed
        s_unres = _valid_arm1b_sources()
        s_unres["primary_command"]["argv"] = [
            "phenix.refine",
            "model_in.pdb",
            "data_in.mtz",
            "missing_params.eff",
        ]
        with self.assertRaisesRegex(
            ValueError, r"Unresolved parameter file reference 'missing_params\.eff'"
        ):
            verify_flag_generation_guard(arm="1b", sources=s_unres)

        # Unresolved 'include file' in PHIL fails closed
        s_inc_unres = _valid_arm1b_sources(
            effective_phil="include file missing_inc.phil\nr_free_flags.generate = False\n"
        )
        with self.assertRaisesRegex(
            ValueError, r"Unresolved parameter file reference 'missing_inc\.phil'"
        ):
            verify_flag_generation_guard(arm="1b", sources=s_inc_unres)

        # Cyclic parameter file reference (a.eff -> b.eff -> a.eff) fails closed
        s_cycle = _valid_arm1b_sources()
        s_cycle["primary_command"]["argv"] = [
            "phenix.refine",
            "model_in.pdb",
            "data_in.mtz",
            "a.eff",
        ]
        with self.assertRaisesRegex(
            ValueError,
            r"Cyclic parameter file reference detected.*a\.eff -> b\.eff -> a\.eff",
        ):
            verify_flag_generation_guard(
                arm="1b",
                sources=s_cycle,
                parameter_files={
                    "a.eff": "include file b.eff\n",
                    "b.eff": "include file a.eff\n",
                },
            )

        # Valid acyclic and nested parameter file inclusion records digests and reference edges
        s_valid_pf = _valid_arm1b_sources(
            effective_phil="include file eff_child.phil\n"
        )
        s_valid_pf["primary_command"]["argv"] = [
            "phenix.refine",
            "model_in.pdb",
            "data_in.mtz",
            "cmd_params.eff",
        ]
        res = verify_flag_generation_guard(
            arm="1b",
            sources=s_valid_pf,
            parameter_files={
                "cmd_params.eff": (
                    "include file nested_child.def\n"
                    "r_free_flags.generate = False\n"
                ),
                "nested_child.def": "main.number_of_macro_cycles = 3\n",
                "eff_child.phil": "data_manager.fmodel.xray_data.r_free_flags.generate = False\n",
            },
        )
        self.assertTrue(res["guard_ok"])
        self.assertIn("cmd_params.eff", res["source_digests"])
        self.assertIn("nested_child.def", res["source_digests"])
        self.assertIn("eff_child.phil", res["source_digests"])
        self.assertEqual(len(res["reference_edges"]), 3)

    def test_rejects_unconsumed_parameter_files_and_classification_conflicts(
        self,
    ) -> None:
        # 1. orphanTrue: unreferenced parameter file containing generate=True fails closed
        with self.assertRaisesRegex(
            ValueError,
            r"Forbidden R-free flag generation request.*orphan\.eff",
        ):
            verify_flag_generation_guard(
                arm="1b",
                sources=_valid_arm1b_sources(),
                parameter_files={"orphan.eff": "r_free_flags.generate = True\n"},
            )

        # 2. filename-classificationTrue: model_in.pdb supplied in parameter_files with generate=True fails closed
        with self.assertRaisesRegex(
            ValueError,
            r"Classification conflict for parameter_files\['model_in\.pdb'\]",
        ):
            verify_flag_generation_guard(
                arm="1b",
                sources=_valid_arm1b_sources(),
                parameter_files={"model_in.pdb": "r_free_flags.generate = True\n"},
            )

        # 3. orphanmalformed: unreferenced parameter file with malformed PHIL fails closed
        with self.assertRaisesRegex(
            ValueError,
            r"orphan_bad\.eff: unclosed brace scope",
        ):
            verify_flag_generation_guard(
                arm="1b",
                sources=_valid_arm1b_sources(),
                parameter_files={
                    "orphan_bad.eff": "r_free_flags { generate = False\n"
                },
            )

        # 4. unusedFalse: unreferenced parameter file with valid generate=False still fails closed as unconsumed
        with self.assertRaisesRegex(
            ValueError,
            r"Unconsumed parameter_files entries were supplied but never referenced.*'unused_ok\.eff'",
        ):
            verify_flag_generation_guard(
                arm="1b",
                sources=_valid_arm1b_sources(),
                parameter_files={
                    "unused_ok.eff": "r_free_flags.generate = False\n"
                },
            )

    def test_layer_states_unique_source_id_arm1a_arm1b_and_unavailable_handling(self) -> None:
        # Duplicate source_id rejected
        s_dup = _valid_arm1b_sources()
        s_dup["mechanical_backup"]["source_id"] = "src_primary_cmd"
        with self.assertRaisesRegex(ValueError, r"Duplicate source_id"):
            verify_flag_generation_guard(arm="1b", sources=s_dup)

        # Missing layer rejected
        s_missing = _valid_arm1b_sources()
        del s_missing["mechanical_backup"]
        with self.assertRaisesRegex(ValueError, r"sources must contain exact layer keys"):
            verify_flag_generation_guard(arm="1b", sources=s_missing)

        # Arm 1b rejects mechanical_backup = not_applicable
        s_1b_na = _valid_arm1b_sources()
        s_1b_na["mechanical_backup"] = {
            "source_id": "src_backup_cmd",
            "state": "not_applicable",
            "controller_contract_justification": "Attempted skip on 1b",
        }
        with self.assertRaisesRegex(
            ValueError, r"Arm 1b requires all four source layers"
        ):
            verify_flag_generation_guard(arm="1b", sources=s_1b_na)

        # Arm 1a rejects mechanical_backup = not_applicable without controller_contract_justification
        s_1a_no_just = _valid_arm1b_sources()
        s_1a_no_just["mechanical_backup"] = {
            "source_id": "src_backup_cmd",
            "state": "not_applicable",
        }
        with self.assertRaisesRegex(
            ValueError, r"requires an explicit non-empty 'controller_contract_justification'"
        ):
            verify_flag_generation_guard(arm="1a", sources=s_1a_no_just)

        # Arm 1a accepts mechanical_backup = not_applicable when justified
        s_1a_ok = _valid_arm1b_sources()
        s_1a_ok["mechanical_backup"] = {
            "source_id": "src_backup_cmd",
            "state": "not_applicable",
            "controller_contract_justification": (
                "Arm 1a single-shot baseline contract does not configure a mechanical backup move."
            ),
        }
        res_1a = verify_flag_generation_guard(arm="1a", sources=s_1a_ok)
        self.assertTrue(res_1a["guard_ok"])
        self.assertIn("mechanical_backup", res_1a["not_applicable_sources"])

        # Unavailable actual_command or effective_eff returns guard_ok=False, incomplete=True
        s_unavail = _valid_arm1b_sources()
        s_unavail["effective_eff"] = {
            "source_id": "src_effective_eff",
            "state": "unavailable",
            "reason": "Subprocess aborted before writing effective .eff output",
        }
        res_unavail = verify_flag_generation_guard(arm="1b", sources=s_unavail)
        self.assertFalse(res_unavail["guard_ok"])
        self.assertFalse(res_unavail["passed"])
        self.assertTrue(res_unavail["incomplete"])
        self.assertEqual(res_unavail["status"], "INCOMPLETE_UNAVAILABLE_SOURCES")
        self.assertIn("effective_eff", res_unavail["unavailable_sources"])

        # Even when effective_eff is unavailable, a True in primary_command still raises ValueError
        s_unavail_true = _valid_arm1b_sources(primary_gen="r_free_flags.generate=True")
        s_unavail_true["effective_eff"] = {
            "source_id": "src_effective_eff",
            "state": "unavailable",
            "reason": "Aborted early",
        }
        with self.assertRaisesRegex(
            ValueError, r"Forbidden R-free flag generation request"
        ):
            verify_flag_generation_guard(arm="1b", sources=s_unavail_true)

    def test_effective_eff_preserves_exact_utf8_bytes_and_line_numbers(self) -> None:
        raw_a = "r_free_flags.generate = False"
        raw_b = "\n\n  r_free_flags.generate = False  \n\n"
        res_a = verify_flag_generation_guard(
            arm="1b", sources=_valid_arm1b_sources(effective_phil=raw_a)
        )
        res_b = verify_flag_generation_guard(
            arm="1b", sources=_valid_arm1b_sources(effective_phil=raw_b)
        )
        sha_a = res_a["source_digests"]["src_effective_eff"]
        sha_b = res_b["source_digests"]["src_effective_eff"]
        self.assertEqual(sha_a, hashlib.sha256(raw_a.encode("utf-8")).hexdigest())
        self.assertEqual(sha_b, hashlib.sha256(raw_b.encode("utf-8")).hexdigest())
        self.assertNotEqual(sha_a, sha_b)

        eff_occ_a = [
            occ
            for occ in res_a["generation_occurrences"]
            if occ["layer"] == "effective_eff"
        ]
        eff_occ_b = [
            occ
            for occ in res_b["generation_occurrences"]
            if occ["layer"] == "effective_eff"
        ]
        self.assertEqual(len(eff_occ_a), 1)
        self.assertEqual(len(eff_occ_b), 1)
        self.assertEqual(eff_occ_a[0]["line"], 1)
        self.assertEqual(eff_occ_b[0]["line"], 3)

        # Empty or whitespace-only effective_eff still rejects
        for blank in ("", "   \n\t  "):
            with self.subTest(blank=blank):
                with self.assertRaisesRegex(
                    ValueError,
                    r"sources\['effective_eff'\]\.phil_text must be a non-empty string",
                ):
                    verify_flag_generation_guard(
                        arm="1b",
                        sources=_valid_arm1b_sources(effective_phil=blank),
                    )

    def test_unambiguous_source_id_digest_bindings_and_strict_whitespace_rejection(
        self,
    ) -> None:
        # 1. Regression (#1351): primary_command has source_id='p' with assignment at argv[1],
        # while effective_eff has source_id='p:argv[1]', plus nested parameter-file ancestry.
        # Every occurrence and reference edge maps unambiguously to its exact digest-backed source_id.
        primary_argv = [
            "phenix.refine",
            "r_free_flags.generate=False",
            "model_in.pdb",
            "data_in.mtz",
            "cmd_top.eff",
        ]
        backup_argv = [
            "phenix.refine",
            "model_in.pdb",
            "data_in.mtz",
            "xray_data.r_free_flags.generate=False",
        ]
        actual_argv = [
            "phenix.refine",
            "model_in.pdb",
            "data_in.mtz",
            "data_manager.fmodel.xray_data.r_free_flags.generate=False",
            "main.number_of_macro_cycles=3",
        ]
        effective_phil = (
            "include file eff_nested.phil\n"
            "data_manager.fmodel.xray_data.r_free_flags.generate = False\n"
        )
        cmd_top_text = "include file cmd_leaf.def\nr_free_flags.generate = False\n"
        cmd_leaf_text = "main.number_of_macro_cycles = 3\n"
        eff_nested_text = "output.prefix = \"run_out\"\n"

        sources = {
            "primary_command": {
                "source_id": "p",
                "state": "supplied",
                "argv": primary_argv,
            },
            "mechanical_backup": {
                "source_id": "b",
                "state": "supplied",
                "argv": backup_argv,
            },
            "actual_command": {
                "source_id": "a",
                "state": "supplied",
                "argv": actual_argv,
            },
            "effective_eff": {
                "source_id": "p:argv[1]",
                "state": "supplied",
                "phil_text": effective_phil,
            },
        }
        res = verify_flag_generation_guard(
            arm="1b",
            sources=sources,
            parameter_files={
                "cmd_top.eff": cmd_top_text,
                "cmd_leaf.def": cmd_leaf_text,
                "eff_nested.phil": eff_nested_text,
            },
        )
        self.assertTrue(res["guard_ok"])

        expected_p_sha = hashlib.sha256(
            "\x00".join(primary_argv).encode("utf-8")
        ).hexdigest()
        expected_eff_sha = hashlib.sha256(effective_phil.encode("utf-8")).hexdigest()
        self.assertEqual(res["source_digests"]["p"], expected_p_sha)
        self.assertEqual(res["source_digests"]["p:argv[1]"], expected_eff_sha)
        self.assertNotEqual(expected_p_sha, expected_eff_sha)

        # Primary argv[1] occurrence has source_id='p' and token_index=1 (not 'p:argv[1]')
        primary_argv_occs = [
            occ
            for occ in res["generation_occurrences"]
            if occ["layer"] == "primary_command" and occ["source_id"] == "p"
        ]
        self.assertEqual(len(primary_argv_occs), 1)
        self.assertEqual(primary_argv_occs[0]["token_index"], 1)
        self.assertEqual(
            res["source_digests"][primary_argv_occs[0]["source_id"]],
            expected_p_sha,
        )

        # Parameter-file occurrence retains actual parameter-file source_id ('cmd_top.eff') and token_index=None
        pf_occs = [
            occ
            for occ in res["generation_occurrences"]
            if occ["source_id"] == "cmd_top.eff"
        ]
        self.assertEqual(len(pf_occs), 1)
        self.assertEqual(pf_occs[0]["layer"], "primary_command")
        self.assertIsNone(pf_occs[0]["token_index"])
        self.assertEqual(
            res["source_digests"][pf_occs[0]["source_id"]],
            hashlib.sha256(cmd_top_text.encode("utf-8")).hexdigest(),
        )

        # Effective_eff occurrence has source_id='p:argv[1]', layer='effective_eff', token_index=None
        eff_occs = [
            occ
            for occ in res["generation_occurrences"]
            if occ["layer"] == "effective_eff"
        ]
        self.assertEqual(len(eff_occs), 1)
        self.assertEqual(eff_occs[0]["source_id"], "p:argv[1]")
        self.assertIsNone(eff_occs[0]["token_index"])
        self.assertEqual(
            res["source_digests"][eff_occs[0]["source_id"]],
            expected_eff_sha,
        )

        # Every occurrence and reference edge resolves to an exact key in source_digests
        for occ in res["generation_occurrences"]:
            self.assertIn(occ["source_id"], res["source_digests"])
        for assign in res["non_generation_assignments"]:
            self.assertIn(assign["source_id"], res["source_digests"])
        for edge in res["reference_edges"]:
            self.assertIn(edge["from_source_id"], res["source_digests"])
            self.assertIn(edge["to_source_id"], res["source_digests"])

        # 2. Regression (#1352): reject leading or trailing whitespace in source_id on any layer
        for layer_name in CANONICAL_SOURCE_LAYERS:
            for bad_id in (" p", "p ", "  src_id  ", "\tsrc_id", "src_id\n"):
                with self.subTest(layer_name=layer_name, bad_id=bad_id):
                    s_ws = _valid_arm1b_sources()
                    s_ws[layer_name]["source_id"] = bad_id
                    with self.assertRaisesRegex(
                        ValueError,
                        r"must be a non-empty string without leading or trailing whitespace",
                    ):
                        verify_flag_generation_guard(arm="1b", sources=s_ws)


class TestHklAndSleepMembershipGuard(unittest.TestCase):
    """Test verify_hkl_and_sleep_membership exact per-HKL and sleep-set preservation."""

    def test_valid_unchanged_parent_subset_and_disjoint_comparative_domains_pass(
        self,
    ) -> None:
        before_flags = {
            (1, 0, 0): 0,
            (0, 1, 0): 1,
            (0, 0, 1): 0,
            (1, 1, 1): 1,
        }
        after_flags = {
            (1, 1, 1): 1,
            (0, 0, 1): 0,
            (0, 1, 0): 1,
            (1, 0, 0): 0,
        }

        # 1. Unchanged parent / pre-sleep control domain (sleep HKLs present as subset of flag map)
        parent_sleep_set = {(0, 0, 1)}
        res_subset = verify_hkl_and_sleep_membership(
            before_hkl_flags=before_flags,
            after_hkl_flags=after_flags,
            before_sleep_hkls=parent_sleep_set,
            after_sleep_hkls=list(parent_sleep_set),
        )
        self.assertTrue(res_subset["membership_ok"])
        self.assertEqual(res_subset["hkl_count"], 4)
        self.assertEqual(res_subset["sleep_hkl_count"], 1)
        self.assertEqual(
            res_subset["before_hkl_flags_sha256"],
            res_subset["after_hkl_flags_sha256"],
        )
        self.assertEqual(
            res_subset["before_sleep_sha256"], res_subset["after_sleep_sha256"]
        )
        self.assertEqual(res_subset["registration_status"], REGISTRATION_STATUS)
        self.assertFalse(res_subset["executed"])

        # 2. Unchanged comparative common_analysis_derivative domain (U09:185-189: sealed sleep physically removed, disjoint from active flag map)
        disjoint_sleep_set = {(9, 9, 9), (8, 8, 8)}
        res_disjoint = verify_hkl_and_sleep_membership(
            before_hkl_flags=before_flags,
            after_hkl_flags=after_flags,
            before_sleep_hkls=disjoint_sleep_set,
            after_sleep_hkls=[(8, 8, 8), (9, 9, 9)],
        )
        self.assertTrue(res_disjoint["membership_ok"])
        self.assertEqual(res_disjoint["hkl_count"], 4)
        self.assertEqual(res_disjoint["sleep_hkl_count"], 2)
        self.assertEqual(
            res_disjoint["before_hkl_flags_sha256"],
            res_disjoint["after_hkl_flags_sha256"],
        )
        self.assertEqual(
            res_disjoint["before_sleep_sha256"],
            res_disjoint["after_sleep_sha256"],
        )

    def test_rejects_missing_extra_same_count_replacement_and_flag_swap(self) -> None:
        base_flags = {
            (1, 0, 0): 0,
            (0, 1, 0): 1,
            (0, 0, 1): 0,
            (1, 1, 1): 1,
        }
        empty_sleep: set[tuple[int, int, int]] = set()

        # 1. Missing HKL
        with self.assertRaisesRegex(ValueError, r"missing_hkls=\[\(1, 1, 1\)\]"):
            verify_hkl_and_sleep_membership(
                before_hkl_flags=base_flags,
                after_hkl_flags={(1, 0, 0): 0, (0, 1, 0): 1, (0, 0, 1): 0},
                before_sleep_hkls=empty_sleep,
                after_sleep_hkls=empty_sleep,
            )

        # 2. Extra HKL
        with self.assertRaisesRegex(ValueError, r"extra_hkls=\[\(2, 2, 2\)\]"):
            verify_hkl_and_sleep_membership(
                before_hkl_flags=base_flags,
                after_hkl_flags={**base_flags, (2, 2, 2): 0},
                before_sleep_hkls=empty_sleep,
                after_sleep_hkls=empty_sleep,
            )

        # 3. Same-count HKL replacement: replace (1, 1, 1) with (2, 2, 2) keeping count=4 and flag counts equal
        replaced_flags = {
            (1, 0, 0): 0,
            (0, 1, 0): 1,
            (0, 0, 1): 0,
            (2, 2, 2): 1,
        }
        with self.assertRaisesRegex(
            ValueError, r"missing_hkls=\[\(1, 1, 1\)\], extra_hkls=\[\(2, 2, 2\)\]"
        ):
            verify_hkl_and_sleep_membership(
                before_hkl_flags=base_flags,
                after_hkl_flags=replaced_flags,
                before_sleep_hkls=empty_sleep,
                after_sleep_hkls=empty_sleep,
            )

        # 4. Same-count flag swap: swap flags between (1, 0, 0) and (0, 1, 0) keeping total free/work counts identical
        swapped_flags = {
            (1, 0, 0): 1,
            (0, 1, 0): 0,
            (0, 0, 1): 0,
            (1, 1, 1): 1,
        }
        with self.assertRaisesRegex(
            ValueError, r"mutated_flag_hkls=\[\(0, 1, 0\), \(1, 0, 0\)\]"
        ):
            verify_hkl_and_sleep_membership(
                before_hkl_flags=base_flags,
                after_hkl_flags=swapped_flags,
                before_sleep_hkls=empty_sleep,
                after_sleep_hkls=empty_sleep,
            )

    def test_rejects_sleep_set_membership_mutations_and_duplicates(self) -> None:
        base_flags = {
            (1, 0, 0): 0,
            (0, 1, 0): 1,
            (0, 0, 1): 0,
        }
        # Same-count sleep HKL swap (subset domain)
        with self.assertRaisesRegex(
            ValueError,
            r"missing_sleep_hkls=\[\(1, 0, 0\)\], extra_sleep_hkls=\[\(0, 0, 1\)\]",
        ):
            verify_hkl_and_sleep_membership(
                before_hkl_flags=base_flags,
                after_hkl_flags=dict(base_flags),
                before_sleep_hkls={(1, 0, 0)},
                after_sleep_hkls={(0, 0, 1)},
            )

        # Same-count sleep HKL swap (disjoint comparative domain)
        with self.assertRaisesRegex(
            ValueError,
            r"missing_sleep_hkls=\[\(9, 9, 9\)\], extra_sleep_hkls=\[\(8, 8, 8\)\]",
        ):
            verify_hkl_and_sleep_membership(
                before_hkl_flags=base_flags,
                after_hkl_flags=dict(base_flags),
                before_sleep_hkls={(9, 9, 9)},
                after_sleep_hkls={(8, 8, 8)},
            )

        # Duplicate HKL in sleep collection rejected
        with self.assertRaisesRegex(
            ValueError, r"contains duplicate HKL \(9, 9, 9\)"
        ):
            verify_hkl_and_sleep_membership(
                before_hkl_flags=base_flags,
                after_hkl_flags=dict(base_flags),
                before_sleep_hkls=[(9, 9, 9), (9, 9, 9)],
                after_sleep_hkls=[(9, 9, 9)],
            )

    def test_rejects_absent_empty_maps_omitted_sleep_sets_and_bool_types(self) -> None:
        valid_flags = {(1, 0, 0): 0, (0, 1, 0): 1}
        # Empty flag map rejected
        with self.assertRaisesRegex(ValueError, r"non-empty mapping"):
            verify_hkl_and_sleep_membership(
                before_hkl_flags={},
                after_hkl_flags=valid_flags,
                before_sleep_hkls=set(),
                after_sleep_hkls=set(),
            )

        # Omitted sleep set rejected
        with self.assertRaisesRegex(
            ValueError, r"before_sleep_hkls must be an explicit collection"
        ):
            verify_hkl_and_sleep_membership(
                before_hkl_flags=valid_flags,
                after_hkl_flags=valid_flags,
                after_sleep_hkls=set(),
            )

        # Bool flag value rejected (bool is a subclass of int in Python)
        with self.assertRaisesRegex(ValueError, r"must be a strict int"):
            verify_hkl_and_sleep_membership(
                before_hkl_flags={(1, 0, 0): False, (0, 1, 0): True},  # type: ignore[dict-item]
                after_hkl_flags={(1, 0, 0): False, (0, 1, 0): True},  # type: ignore[dict-item]
                before_sleep_hkls=set(),
                after_sleep_hkls=set(),
            )

        # Bool inside HKL tuple rejected
        with self.assertRaisesRegex(ValueError, r"must be a strict int"):
            verify_hkl_and_sleep_membership(
                before_hkl_flags={(True, 0, 0): 0},  # type: ignore[dict-item]
                after_hkl_flags={(True, 0, 0): 0},  # type: ignore[dict-item]
                before_sleep_hkls=set(),
                after_sleep_hkls=set(),
            )

        # (0, 0, 0) Miller index rejected
        with self.assertRaisesRegex(ValueError, r"cannot contain Miller index \(0, 0, 0\)"):
            verify_hkl_and_sleep_membership(
                before_hkl_flags={(0, 0, 0): 0},
                after_hkl_flags={(0, 0, 0): 0},
                before_sleep_hkls=set(),
                after_sleep_hkls=set(),
            )


if __name__ == "__main__":
    unittest.main()
