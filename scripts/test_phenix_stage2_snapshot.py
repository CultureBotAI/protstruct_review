#!/usr/bin/env python3
"""Unit tests for Stage 2 PHENIX shared 6-role dated snapshot binder (scripts/phenix_stage2_snapshot.py)."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path
import sys
from typing import Any
import unittest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from phenix_stage2_snapshot import (  # noqa: E402
    ARTIFACT_HASH_KEYS,
    AVAILABILITY_STATUS,
    CANONICAL_ARM_ROLE_SLOTS,
    CONTROLLER_ARM_IDS,
    EXECUTION_AUTHORIZED,
    FORBIDDEN_FLOATING_ALIASES,
    LLM_SUBROLES,
    OBSERVED_NATIVE_PROVIDER_BRANCHES,
    REGISTRATION_STATUS,
    RUNTIME_BINDING_STATUS,
    STAGE2_SNAPSHOT_STATUS,
    STATIC_WITNESS_PATH,
    bind_shared_snapshot_config,
    canonical_json_bytes,
    canonical_json_sha256,
)


def _sha256_tag(tag: str) -> str:
    return hashlib.sha256(tag.encode("utf-8")).hexdigest()


def _make_valid_role_configs(
    *,
    provider: str = "openai",
    endpoint: str = "https://api.example.invalid/v1/chat/completions",
    snapshot_id: str = "gpt-test-model-2026-10-15",
    temperature: float = 0.0,
) -> dict[str, dict[str, dict[str, Any]]]:
    configs: dict[str, dict[str, dict[str, Any]]] = {}
    for arm in CONTROLLER_ARM_IDS:
        configs[arm] = {}
        for role in LLM_SUBROLES:
            configs[arm][role] = {
                "arm": arm,
                "role": role,
                "provider": provider,
                "endpoint": endpoint,
                "snapshot_id": snapshot_id,
                "temperature": temperature,
                # Per-role artifact hashes may legitimately differ across roles/arms
                "prompt_sha256": _sha256_tag(f"prompt:{arm}:{role}"),
                "config_sha256": _sha256_tag(f"config:{arm}:{role}"),
                "adapter_sha256": _sha256_tag(f"adapter:{arm}:{role}"),
                "dependency_sha256": _sha256_tag(f"dependency:{arm}:{role}"),
            }
    return configs


def _make_valid_witness(
    *,
    provider: str = "openai",
    endpoint: str = "https://api.example.invalid/v1/chat/completions",
    snapshot_id: str = "gpt-test-model-2026-10-15",
    extra_note: str = "prospective_test_witness_only",
) -> tuple[dict[str, Any], str]:
    witness = {
        "schema": "phenix_stage2_snapshot_witness_test_v1",
        "provider": provider,
        "endpoint": endpoint,
        "snapshot_id": snapshot_id,
        "selected_identifier": snapshot_id,
        "witness_note": extra_note,
    }
    return witness, canonical_json_sha256(witness)


class TestPhenixStage2SnapshotBinder(unittest.TestCase):
    """Test suite for scripts/phenix_stage2_snapshot.py."""

    def test_valid_six_role_binding_across_input_shapes_and_distinct_role_hashes(
        self,
    ) -> None:
        nested = _make_valid_role_configs()
        witness, source_sha = _make_valid_witness()

        res_nested = bind_shared_snapshot_config(
            role_configs=nested,
            snapshot_witness=witness,
            snapshot_source_sha256=source_sha,
        )
        self.assertTrue(res_nested["binding_ok"])
        self.assertEqual(res_nested["provider"], "openai")
        self.assertEqual(
            res_nested["endpoint"],
            "https://api.example.invalid/v1/chat/completions",
        )
        self.assertEqual(res_nested["snapshot_id"], "gpt-test-model-2026-10-15")
        self.assertEqual(res_nested["temperature"], 0.0)
        self.assertIs(type(res_nested["temperature"]), float)
        self.assertEqual(res_nested["snapshot_source_sha256"], source_sha)

        # Fixed non-promotional statuses
        self.assertEqual(res_nested["runtime_binding"], RUNTIME_BINDING_STATUS)
        self.assertEqual(res_nested["runtime_binding"], "not_assessed")
        self.assertEqual(res_nested["availability"], AVAILABILITY_STATUS)
        self.assertEqual(res_nested["availability"], "not_assessed")
        self.assertEqual(res_nested["registration_status"], REGISTRATION_STATUS)
        self.assertEqual(
            res_nested["registration_status"], "selected_decisions_recorded"
        )
        self.assertNotEqual(
            res_nested["registration_status"], "frozen_result_free"
        )
        self.assertIs(res_nested["execution_authorized"], EXECUTION_AUTHORIZED)
        self.assertFalse(res_nested["execution_authorized"])
        self.assertFalse(res_nested["executed"])

        # Tuple-keyed mapping and reversed sequence of 6 role records must produce the exact same hash
        tuple_keyed = {
            (arm, role): copy.deepcopy(nested[arm][role])
            for arm, role in reversed(CANONICAL_ARM_ROLE_SLOTS)
        }
        seq_records = [
            copy.deepcopy(nested[arm][role])
            for arm, role in reversed(CANONICAL_ARM_ROLE_SLOTS)
        ]
        res_tuple = bind_shared_snapshot_config(
            role_configs=tuple_keyed,
            snapshot_witness=dict(reversed(list(witness.items()))),
            snapshot_source_sha256=source_sha,
        )
        res_seq = bind_shared_snapshot_config(
            role_configs=seq_records,
            snapshot_witness=witness,
            snapshot_source_sha256=source_sha,
        )
        self.assertEqual(
            res_nested["effective_binding_sha256"],
            res_tuple["effective_binding_sha256"],
        )
        self.assertEqual(
            res_nested["effective_binding_sha256"],
            res_seq["effective_binding_sha256"],
        )

    def test_valid_date_formats_and_supported_providers(self) -> None:
        self.assertEqual(
            OBSERVED_NATIVE_PROVIDER_BRANCHES, ("ollama", "google", "openai")
        )
        cases = [
            ("openai", "gpt-model-2026-11-01"),
            ("google", "models/gemini-pro-20261101"),
            ("ollama", "llama3.1:70b-instruct-2026-09-30-q4_K_M"),
        ]
        self.assertEqual(
            {provider for provider, _ in cases},
            set(OBSERVED_NATIVE_PROVIDER_BRANCHES),
        )
        for provider, snap_id in cases:
            with self.subTest(provider=provider, snap_id=snap_id):
                cfgs = _make_valid_role_configs(
                    provider=provider, snapshot_id=snap_id
                )
                witness, source_sha = _make_valid_witness(
                    provider=provider, snapshot_id=snap_id
                )
                res = bind_shared_snapshot_config(
                    role_configs=cfgs,
                    snapshot_witness=witness,
                    snapshot_source_sha256=source_sha,
                )
                self.assertEqual(res["provider"], provider)
                self.assertEqual(res["snapshot_id"], snap_id)

    def test_committed_stage1_static_witness_retains_null_and_is_rejected_if_bound(
        self,
    ) -> None:
        witness_path = REPO_ROOT / STATIC_WITNESS_PATH
        self.assertTrue(witness_path.is_file())
        raw_bytes = witness_path.read_bytes()
        self.assertEqual(
            hashlib.sha256(raw_bytes).hexdigest(),
            "692a0b4e082ac5f56622ca6c61b457120efa00542545c12e1672f66c01c9ec0f",
        )
        static_witness = json.loads(raw_bytes.decode("utf-8"))
        self.assertEqual(static_witness["schema"], "static_source_witness_v1")
        shared_snap = static_witness["shared_dated_snapshot"]
        self.assertIsNone(shared_snap["selected_identifier"])
        self.assertEqual(shared_snap["runtime_binding"], "not_assessed")
        self.assertEqual(shared_snap["availability"], "not_assessed")

        cfgs = _make_valid_role_configs()
        unselected_sha = canonical_json_sha256(shared_snap)
        with self.assertRaisesRegex(
            ValueError, "selected_identifier=None"
        ):
            bind_shared_snapshot_config(
                role_configs=cfgs,
                snapshot_witness=shared_snap,
                snapshot_source_sha256=unselected_sha,
            )

    def test_rejects_missing_extra_duplicate_or_conflicting_arm_role_slots(
        self,
    ) -> None:
        witness, source_sha = _make_valid_witness()

        # Missing subrole in arm 1b
        missing_role = _make_valid_role_configs()
        del missing_role["1b"]["command_llm"]
        with self.assertRaisesRegex(ValueError, "command_llm"):
            bind_shared_snapshot_config(
                role_configs=missing_role,
                snapshot_witness=witness,
                snapshot_source_sha256=source_sha,
            )

        # Missing arm 1b
        missing_arm = _make_valid_role_configs()
        del missing_arm["1b"]
        with self.assertRaisesRegex(ValueError, "missing=\\['1b'\\]"):
            bind_shared_snapshot_config(
                role_configs=missing_arm,
                snapshot_witness=witness,
                snapshot_source_sha256=source_sha,
            )

        # Extra arm 1c
        extra_arm = _make_valid_role_configs()
        extra_arm["1c"] = copy.deepcopy(extra_arm["1a"])
        with self.assertRaisesRegex(ValueError, "extra=\\['1c'\\]"):
            bind_shared_snapshot_config(
                role_configs=extra_arm,
                snapshot_witness=witness,
                snapshot_source_sha256=source_sha,
            )

        # Extra subrole
        extra_role = _make_valid_role_configs()
        extra_role["1a"]["router_llm"] = copy.deepcopy(extra_role["1a"]["llm"])
        with self.assertRaisesRegex(ValueError, "router_llm"):
            bind_shared_snapshot_config(
                role_configs=extra_role,
                snapshot_witness=witness,
                snapshot_source_sha256=source_sha,
            )

        # Duplicate slot in sequence
        base = _make_valid_role_configs()
        seq = [
            copy.deepcopy(base[arm][role])
            for arm, role in CANONICAL_ARM_ROLE_SLOTS
        ]
        seq[-1] = copy.deepcopy(base["1a"]["llm"])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            bind_shared_snapshot_config(
                role_configs=seq,
                snapshot_witness=witness,
                snapshot_source_sha256=source_sha,
            )

        # Inner arm/role field mismatch with outer key
        conflict = _make_valid_role_configs()
        conflict["1b"]["cheap_llm"]["role"] = "llm"
        with self.assertRaisesRegex(ValueError, "conflicts with slot role"):
            bind_shared_snapshot_config(
                role_configs=conflict,
                snapshot_witness=witness,
                snapshot_source_sha256=source_sha,
            )

    def test_rejects_mismatch_across_six_roles_on_any_shared_tuple_component(
        self,
    ) -> None:
        witness, source_sha = _make_valid_witness()

        for arm, role in CANONICAL_ARM_ROLE_SLOTS[1:]:
            # Provider mismatch on one slot
            cfgs_prov = _make_valid_role_configs()
            cfgs_prov[arm][role]["provider"] = "google"
            with self.assertRaisesRegex(
                ValueError, "Shared snapshot tuple mismatch"
            ):
                bind_shared_snapshot_config(
                    role_configs=cfgs_prov,
                    snapshot_witness=witness,
                    snapshot_source_sha256=source_sha,
                )

            # Endpoint mismatch on one slot
            cfgs_ep = _make_valid_role_configs()
            cfgs_ep[arm][role]["endpoint"] = (
                "https://other.example.invalid/v1/chat"
            )
            with self.assertRaisesRegex(
                ValueError, "Shared snapshot tuple mismatch"
            ):
                bind_shared_snapshot_config(
                    role_configs=cfgs_ep,
                    snapshot_witness=witness,
                    snapshot_source_sha256=source_sha,
                )

            # Snapshot ID mismatch on one slot (using a valid dated identifier that differs from the shared tuple)
            cfgs_snap = _make_valid_role_configs()
            cfgs_snap[arm][role]["snapshot_id"] = "gpt-other-model-2026-10-16"
            with self.assertRaisesRegex(
                ValueError, "Shared snapshot tuple mismatch"
            ):
                bind_shared_snapshot_config(
                    role_configs=cfgs_snap,
                    snapshot_witness=witness,
                    snapshot_source_sha256=source_sha,
                )

    def test_rejects_floating_aliases_unpinned_ids_and_invalid_calendar_dates(
        self,
    ) -> None:
        bad_ids = [
            *FORBIDDEN_FLOATING_ALIASES,
            "gpt-4o-latest",
            "gemini-pro:latest",
            "llama3-default-2026-10-15",
            "gpt-4o-auto-2026-10-15",
            "gpt-4o-preview-2026-10-15",
            "gpt-4o",
            "gemini-1.5-pro-002",
            "llama3.1:70b",
            "gpt-model-2026-02-30",
            "gpt-model-2026-13-01",
            "gpt-model-20260230",
            "2026-10-15",
            "20261015",
            "gpt model 2026-10-15",
            " router-model-2026-10-15",
        ]
        for bad_id in bad_ids:
            with self.subTest(bad_id=bad_id):
                cfgs = _make_valid_role_configs(snapshot_id=bad_id)
                witness = {
                    "provider": "openai",
                    "snapshot_id": bad_id,
                }
                source_sha = canonical_json_sha256(witness)
                with self.assertRaises(ValueError):
                    bind_shared_snapshot_config(
                        role_configs=cfgs,
                        snapshot_witness=witness,
                        snapshot_source_sha256=source_sha,
                    )

    def test_rejects_invalid_provider_temperature_and_artifact_hashes(
        self,
    ) -> None:
        witness, source_sha = _make_valid_witness()

        # Unsupported provider
        cfgs_bad_prov = _make_valid_role_configs(provider="anthropic")
        with self.assertRaisesRegex(
            ValueError, "static-witnessed libtbx.langchain provider"
        ):
            bind_shared_snapshot_config(
                role_configs=cfgs_bad_prov,
                snapshot_witness=witness,
                snapshot_source_sha256=source_sha,
            )

        # Invalid temperatures (including bool False/True, non-zero, str, None, NaN, inf)
        for bad_temp in (
            False,
            True,
            0.1,
            -0.01,
            1,
            "0.0",
            None,
            float("nan"),
            float("inf"),
        ):
            with self.subTest(bad_temp=bad_temp):
                cfgs_temp = _make_valid_role_configs()
                cfgs_temp["1a"]["command_llm"]["temperature"] = bad_temp
                with self.assertRaises(ValueError):
                    bind_shared_snapshot_config(
                        role_configs=cfgs_temp,
                        snapshot_witness=witness,
                        snapshot_source_sha256=source_sha,
                    )

        # Missing or malformed per-role artifact hashes
        for h_key in ARTIFACT_HASH_KEYS:
            for bad_hash in (
                "",
                "abc",
                "G" * 64,
                "A" * 64,  # uppercase hex rejected
                None,
                123,
            ):
                with self.subTest(h_key=h_key, bad_hash=bad_hash):
                    cfgs_hash = _make_valid_role_configs()
                    cfgs_hash["1b"]["llm"][h_key] = bad_hash
                    with self.assertRaises(ValueError):
                        bind_shared_snapshot_config(
                            role_configs=cfgs_hash,
                            snapshot_witness=witness,
                            snapshot_source_sha256=source_sha,
                        )

            cfgs_missing_hash = _make_valid_role_configs()
            del cfgs_missing_hash["1b"]["llm"][h_key]
            with self.assertRaisesRegex(ValueError, h_key):
                bind_shared_snapshot_config(
                    role_configs=cfgs_missing_hash,
                    snapshot_witness=witness,
                    snapshot_source_sha256=source_sha,
                )

    def test_rejects_invalid_snapshot_witness_or_mismatched_source_sha256(
        self,
    ) -> None:
        cfgs = _make_valid_role_configs()
        witness, source_sha = _make_valid_witness()

        # Bare SHA-256 without witness mapping
        for bad_witness in (None, {}, [], "not_a_mapping"):
            with self.subTest(bad_witness=bad_witness):
                with self.assertRaises(ValueError):
                    bind_shared_snapshot_config(
                        role_configs=cfgs,
                        snapshot_witness=bad_witness,  # type: ignore[arg-type]
                        snapshot_source_sha256=source_sha,
                    )

        # Mismatched snapshot_source_sha256
        with self.assertRaisesRegex(
            ValueError,
            "snapshot_source_sha256 .* does not match canonical JSON SHA-256",
        ):
            bind_shared_snapshot_config(
                role_configs=cfgs,
                snapshot_witness=witness,
                snapshot_source_sha256=_sha256_tag("wrong_digest"),
            )

        # Witness provider mismatch with 6-role tuple
        w_prov = copy.deepcopy(witness)
        w_prov["provider"] = "google"
        with self.assertRaisesRegex(
            ValueError, "snapshot_witness.provider .* does not match"
        ):
            bind_shared_snapshot_config(
                role_configs=cfgs,
                snapshot_witness=w_prov,
                snapshot_source_sha256=canonical_json_sha256(w_prov),
            )

        # Witness snapshot_id mismatch with 6-role tuple
        w_snap = copy.deepcopy(witness)
        w_snap["snapshot_id"] = "gpt-test-model-2026-10-16"
        w_snap["selected_identifier"] = "gpt-test-model-2026-10-16"
        with self.assertRaisesRegex(
            ValueError, "snapshot_witness.snapshot_id .* does not match"
        ):
            bind_shared_snapshot_config(
                role_configs=cfgs,
                snapshot_witness=w_snap,
                snapshot_source_sha256=canonical_json_sha256(w_snap),
            )

        # Witness endpoint mismatch
        w_ep = copy.deepcopy(witness)
        w_ep["endpoint"] = "https://wrong.example.invalid/v1"
        with self.assertRaisesRegex(
            ValueError, "snapshot_witness.endpoint .* does not match"
        ):
            bind_shared_snapshot_config(
                role_configs=cfgs,
                snapshot_witness=w_ep,
                snapshot_source_sha256=canonical_json_sha256(w_ep),
            )

        # Issue #1369: omitted reserved status fields stay omitted; canonical reserved
        # statuses are accepted and consistent with top-level statuses; True/frozen/unknown/
        # wrong-type claims are rejected even when snapshot_source_sha256 is recomputed.
        res_omitted = bind_shared_snapshot_config(
            role_configs=cfgs,
            snapshot_witness=witness,
            snapshot_source_sha256=source_sha,
        )
        for omitted_key in (
            "executed",
            "registration_status",
            "runtime_binding",
            "availability",
            "execution_authorized",
            "stage2_status",
        ):
            self.assertNotIn(omitted_key, res_omitted["snapshot_witness"])

        w_canonical_statuses = copy.deepcopy(witness)
        w_canonical_statuses.update(
            {
                "executed": False,
                "registration_status": REGISTRATION_STATUS,
                "runtime_binding": RUNTIME_BINDING_STATUS,
                "availability": AVAILABILITY_STATUS,
                "execution_authorized": False,
                "stage2_status": STAGE2_SNAPSHOT_STATUS,
            }
        )
        res_canonical = bind_shared_snapshot_config(
            role_configs=cfgs,
            snapshot_witness=w_canonical_statuses,
            snapshot_source_sha256=canonical_json_sha256(w_canonical_statuses),
        )
        self.assertIs(res_canonical["snapshot_witness"]["executed"], False)
        self.assertEqual(
            res_canonical["snapshot_witness"]["registration_status"],
            res_canonical["registration_status"],
        )
        self.assertEqual(
            res_canonical["snapshot_witness"]["runtime_binding"],
            res_canonical["runtime_binding"],
        )
        self.assertEqual(
            res_canonical["snapshot_witness"]["availability"],
            res_canonical["availability"],
        )
        self.assertIs(
            res_canonical["snapshot_witness"]["execution_authorized"],
            res_canonical["execution_authorized"],
        )
        self.assertEqual(
            res_canonical["snapshot_witness"]["stage2_status"],
            res_canonical["stage2_status"],
        )

        # Witness attempting to promote or mistype runtime_binding, availability,
        # execution_authorized, executed, registration_status, or stage2_status
        for forbidden_override, expected_regex in (
            ({"runtime_binding": "verified"}, "snapshot_witness\\.runtime_binding"),
            ({"runtime_binding": None}, "snapshot_witness\\.runtime_binding"),
            ({"availability": "available"}, "snapshot_witness\\.availability"),
            ({"availability": None}, "snapshot_witness\\.availability"),
            (
                {"execution_authorized": True},
                "snapshot_witness\\.execution_authorized",
            ),
            (
                {"execution_authorized": 0},
                "snapshot_witness\\.execution_authorized",
            ),
            (
                {"execution_authorized": None},
                "snapshot_witness\\.execution_authorized",
            ),
            ({"executed": True}, "snapshot_witness\\.executed"),
            ({"executed": 0}, "snapshot_witness\\.executed"),
            ({"executed": None}, "snapshot_witness\\.executed"),
            ({"executed": "False"}, "snapshot_witness\\.executed"),
            (
                {"registration_status": "frozen_result_free"},
                "snapshot_witness\\.registration_status",
            ),
            (
                {"registration_status": "unknown_status"},
                "snapshot_witness\\.registration_status",
            ),
            (
                {"registration_status": None},
                "snapshot_witness\\.registration_status",
            ),
            (
                {"registration_status": False},
                "snapshot_witness\\.registration_status",
            ),
            (
                {"stage2_status": "frozen_stage2"},
                "snapshot_witness\\.stage2_status",
            ),
        ):
            with self.subTest(forbidden_override=forbidden_override):
                w_bad = copy.deepcopy(witness)
                w_bad.update(forbidden_override)
                with self.assertRaisesRegex(ValueError, expected_regex):
                    bind_shared_snapshot_config(
                        role_configs=cfgs,
                        snapshot_witness=w_bad,
                        snapshot_source_sha256=canonical_json_sha256(w_bad),
                    )

        # Non-finite float or non-JSON value inside witness
        w_nan = copy.deepcopy(witness)
        w_nan["bad_float"] = float("nan")
        with self.assertRaisesRegex(ValueError, "non-finite float"):
            canonical_json_bytes(w_nan)

    def test_effective_binding_sha256_changes_on_any_slot_artifact_tuple_or_witness_mutation(
        self,
    ) -> None:
        base_cfgs = _make_valid_role_configs()
        base_witness, base_sha = _make_valid_witness()
        baseline = bind_shared_snapshot_config(
            role_configs=base_cfgs,
            snapshot_witness=base_witness,
            snapshot_source_sha256=base_sha,
        )["effective_binding_sha256"]

        seen_hashes = {baseline}

        # Mutate each of the 6 (arm, role) slots across each of the 4 artifact hash categories
        for arm, role in CANONICAL_ARM_ROLE_SLOTS:
            for h_key in ARTIFACT_HASH_KEYS:
                mut_cfgs = _make_valid_role_configs()
                mut_cfgs[arm][role][h_key] = _sha256_tag(
                    f"mutated:{arm}:{role}:{h_key}"
                )
                mut_res = bind_shared_snapshot_config(
                    role_configs=mut_cfgs,
                    snapshot_witness=base_witness,
                    snapshot_source_sha256=base_sha,
                )
                mut_hash = mut_res["effective_binding_sha256"]
                self.assertNotEqual(
                    mut_hash,
                    baseline,
                    f"Mutating {arm}.{role}.{h_key} must change effective_binding_sha256",
                )
                self.assertNotIn(mut_hash, seen_hashes)
                seen_hashes.add(mut_hash)

        # Mutate shared model tuple (provider, endpoint, snapshot_id)
        tuple_mutations = [
            {
                "provider": "google",
                "endpoint": "https://api.example.invalid/v1/chat/completions",
                "snapshot_id": "gpt-test-model-2026-10-15",
            },
            {
                "provider": "openai",
                "endpoint": "https://alt.example.invalid/v1/chat/completions",
                "snapshot_id": "gpt-test-model-2026-10-15",
            },
            {
                "provider": "openai",
                "endpoint": "https://api.example.invalid/v1/chat/completions",
                "snapshot_id": "gpt-test-model-2026-10-16",
            },
        ]
        for mut_params in tuple_mutations:
            mut_cfgs = _make_valid_role_configs(**mut_params)
            mut_w, mut_w_sha = _make_valid_witness(**mut_params)
            mut_res = bind_shared_snapshot_config(
                role_configs=mut_cfgs,
                snapshot_witness=mut_w,
                snapshot_source_sha256=mut_w_sha,
            )
            mut_hash = mut_res["effective_binding_sha256"]
            self.assertNotEqual(mut_hash, baseline)
            self.assertNotIn(mut_hash, seen_hashes)
            seen_hashes.add(mut_hash)

        # Mutate snapshot_witness content while keeping 6-role config unchanged
        alt_w, alt_w_sha = _make_valid_witness(
            extra_note="different_witness_provenance_record"
        )
        alt_res = bind_shared_snapshot_config(
            role_configs=base_cfgs,
            snapshot_witness=alt_w,
            snapshot_source_sha256=alt_w_sha,
        )
        self.assertNotEqual(alt_res["effective_binding_sha256"], baseline)
        self.assertNotIn(alt_res["effective_binding_sha256"], seen_hashes)

    def test_module_uses_only_stdlib_imports(self) -> None:
        mod_path = REPO_ROOT / "scripts" / "phenix_stage2_snapshot.py"
        tree = ast.parse(mod_path.read_text(encoding="utf-8"))
        allowed_stdlib = {
            "__future__",
            "collections",
            "collections.abc",
            "datetime",
            "hashlib",
            "json",
            "math",
            "re",
            "typing",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertIn(alias.name, allowed_stdlib)
            elif isinstance(node, ast.ImportFrom):
                self.assertIn(node.module, allowed_stdlib)


if __name__ == "__main__":
    unittest.main()
