"""Focused tests for the Task 357 retained-reference verification slice."""

from __future__ import annotations

from collections.abc import Mapping
import builtins
import copy
import errno
import hashlib
import io
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any
import unittest
from unittest import mock

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import onesar_records
import onesar_refmac
import onesar_rerun
from onesar_records import (
    EXPECTED_FAMILY_ID,
    ParentExecutionBindingError,
    PhenixRetainedVerificationError,
    REFMAC_FALSE_ADMISSION_ELIGIBILITY_KEYS,
    REFMAC_PROOF_TO_REASON_KEYS,
    REFMAC_UNKNOWN_NATIVE_PREMISE_KEYS,
    RefmacRetainedVerificationError,
    RefmacScientificAdmissionRefusedError,
    RetainedReferenceError,
    build_parent_completed_execution_checkpoint_payload,
    decode_strict_json_mapping,
    load_retained_reference,
    normalize_retained_reference,
    validate_parent_execution_timing,
    verify_retained_parent_execution_checkpoint,
    verify_retained_phenix_rfactor_evidence,
    verify_retained_refmac_rfactor_evidence,
)
import refinement_cache
import test_onesar_refmac
from test_onesar_rerun import (
    COMMITTED_ARCHIVE,
    REPO_ROOT,
    _build_synthetic_map_mtz_pair,
    _make_reconciliation_fixture,
)
import toolchain


def _write_file_with_digest(path: Path, data: bytes) -> tuple[str, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest(), len(data)


def _write_json_with_digest(path: Path, payload: dict) -> tuple[str, int, bytes]:
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    sha256, size_bytes = _write_file_with_digest(path, raw)
    return sha256, size_bytes, raw


class TestRetainedReferenceFirstSlice(unittest.TestCase):
    """Focused tests for Task 357 retained-reference loading and refusal."""

    def test_ordinary_phenix_and_refmac_references_succeed_and_preserve_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            attempt_root = Path(tmp).resolve() / "attempt_001"
            phenix_dir = attempt_root / "phenix_child" / "phenix"
            bundle_dir = phenix_dir / "cache" / "op" / "bundle"
            refmac_dir = attempt_root / "refmac_child" / "refmac"

            rfactors_path = bundle_dir / "phenix_rfactors.json"
            rf_sha, rf_size, _ = _write_json_with_digest(
                rfactors_path,
                {
                    "schema_version": 1,
                    "synthetic_fixture": True,
                    "r_work": 0.195,
                    "r_free": 0.231,
                },
            )

            cache_manifest_path = bundle_dir / "success.json"
            cache_sha, cache_size, _ = _write_json_with_digest(
                cache_manifest_path,
                {
                    "returncode": 0,
                    "reusable": True,
                    "invocation": {"executable": "phenix.python"},
                    "artifacts": {
                        "phenix_rfactors_json": {
                            "path": str(rfactors_path),
                            "sha256": rf_sha,
                        }
                    },
                },
            )

            reconciled_path = phenix_dir / "phenix_reconciled_manifest.json"
            rec_sha, rec_size, rec_bytes = _write_json_with_digest(
                reconciled_path,
                {
                    "schema_version": 1,
                    "synthetic_fixture": True,
                    "manifest_path": str(cache_manifest_path),
                    "manifest_sha256": cache_sha,
                    "operation_manifest": {"returncode": 0, "reusable": True},
                    "reconciliation": {"reconciliation_status": "verified"},
                },
            )

            # 1. Load PHENIX reconciled manifest via explicit CLI/caller path+sha256 binding.
            rec_loaded = load_retained_reference(
                attempt_root,
                path=reconciled_path,
                sha256=rec_sha,
                parse_json=True,
                reject_cache_manifest_as_phenix_reconciled=True,
                label="phenix_reconciled_manifest",
            )
            self.assertEqual(rec_loaded["bytes"], rec_bytes)
            self.assertEqual(
                rec_loaded["verified_reference"]["path"], str(reconciled_path)
            )
            self.assertEqual(
                rec_loaded["verified_reference"]["sha256"], rec_sha
            )
            self.assertEqual(
                rec_loaded["verified_reference"]["size_bytes"], rec_size
            )
            self.assertIsNone(
                rec_loaded["verified_reference"]["declared_size_bytes"]
            )
            self.assertTrue(
                rec_loaded["verified_reference"]["integrity_verified"]
            )
            self.assertFalse(
                rec_loaded["verified_reference"]["scientific_proof_established"]
            )
            self.assertFalse(rec_loaded["verified_reference"]["is_fallback"])

            # 2. Load the cache success.json via the explicit carrier keys on the reconciled manifest.
            cache_loaded = load_retained_reference(
                attempt_root,
                rec_loaded["json"],
                path_key="manifest_path",
                sha256_key="manifest_sha256",
                size_bytes_key=None,
                parse_json=True,
                label="phenix_cache_manifest",
            )
            self.assertEqual(
                cache_loaded["verified_reference"]["path"],
                str(cache_manifest_path),
            )
            self.assertEqual(
                cache_loaded["verified_reference"]["size_bytes"], cache_size
            )

            # 3. Load cache artifact via its {"path", "sha256"} reference dict.
            rf_ref = cache_loaded["json"]["artifacts"]["phenix_rfactors_json"]
            rf_loaded = load_retained_reference(
                attempt_root,
                rf_ref,
                size_bytes_key=None,
                parse_json=True,
                label="phenix_rfactors_json",
            )
            self.assertEqual(
                rf_loaded["verified_reference"]["size_bytes"], rf_size
            )
            self.assertEqual(rf_loaded["json"]["r_work"], 0.195)

            # 4. Load REFMAC primary manifest_json reference dict (with size_bytes) and raw binary bytes.
            refmac_hklout = refmac_dir / "refmac_out.mtz"
            hkl_bytes = b"MTZ synthetic binary payload"
            hkl_sha, hkl_size = _write_file_with_digest(refmac_hklout, hkl_bytes)

            refmac_manifest_path = refmac_dir / "refmac_manifest.json"
            rm_sha, rm_size, rm_bytes = _write_json_with_digest(
                refmac_manifest_path,
                {
                    "schema_version": 1,
                    "status": "diagnostic_captured_gates_unproven",
                    "canonical_eval_qds_eligible": False,
                    "raw_outputs": {
                        "hklout": {
                            "path": str(refmac_hklout),
                            "sha256": hkl_sha,
                            "size_bytes": hkl_size,
                            "exists": True,
                            "is_symlink": False,
                            "is_regular_file": True,
                        }
                    },
                },
            )
            refmac_manifest_ref = {
                "path": str(refmac_manifest_path),
                "persisted": True,
                "sha256": rm_sha,
                "size_bytes": rm_size,
            }
            rm_loaded = load_retained_reference(
                attempt_root,
                refmac_manifest_ref,
                parse_json=True,
                label="refmac_manifest_json",
            )
            self.assertEqual(rm_loaded["bytes"], rm_bytes)
            self.assertEqual(
                rm_loaded["verified_reference"]["declared_size_bytes"], rm_size
            )
            self.assertFalse(
                rm_loaded["verified_reference"]["scientific_proof_established"]
            )

            hkl_loaded = load_retained_reference(
                attempt_root,
                rm_loaded["json"]["raw_outputs"]["hklout"],
                parse_json=False,
                label="refmac_hklout",
            )
            self.assertEqual(hkl_loaded["bytes"], hkl_bytes)
            self.assertIsNone(hkl_loaded["json"])

            # Confirm original files on disk remain byte-identical.
            self.assertEqual(reconciled_path.read_bytes(), rec_bytes)
            self.assertEqual(refmac_manifest_path.read_bytes(), rm_bytes)
            self.assertEqual(refmac_hklout.read_bytes(), hkl_bytes)

    def test_refmac_selected_fallback_reference_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            attempt_root = Path(tmp).resolve() / "attempt_fallback"
            fallback_dir = attempt_root / "refmac_child" / "refmac_retention"
            fallback_manifest_path = (
                fallback_dir / "refmac_manifest__child_fallback.json"
            )
            fb_sha, fb_size, _ = _write_json_with_digest(
                fallback_manifest_path,
                {
                    "schema_version": 1,
                    "status": "diagnostic_captured_gates_unproven",
                    "paths": {
                        "manifest_json_path": str(fallback_manifest_path),
                    },
                },
            )
            selected_manifest_json_ref = {
                "path": str(fallback_manifest_path),
                "persisted": True,
                "sha256": fb_sha,
                "size_bytes": fb_size,
                "fallback_for_unwritable_or_damaged_child_dir": True,
                "collision_avoided_in_parent_retention_dir": True,
                "intended_child_dir_path": str(
                    attempt_root / "refmac_child" / "refmac" / "refmac_manifest.json"
                ),
                "parent_retention_dir": str(fallback_dir),
                "actual_retention_anchor_dir": str(fallback_dir),
                "actual_retention_anchor_kind": "parent_retention_dir",
            }
            loaded = load_retained_reference(
                attempt_root,
                selected_manifest_json_ref,
                parse_json=True,
                label="refmac_manifest_fallback",
            )
            vref = loaded["verified_reference"]
            self.assertEqual(vref["path"], str(fallback_manifest_path))
            self.assertTrue(vref["is_fallback"])
            self.assertEqual(vref["fallback_anchor_dir"], str(fallback_dir))
            self.assertTrue(vref["integrity_verified"])
            self.assertFalse(vref["scientific_proof_established"])

            # Usable-child sibling collision fallback shape (#1057):
            # onesar_refmac._write_json_with_sibling_collision_fallback returns
            # {"path", "sha256", "size_bytes", "fallback_for_preexisting_path"}.
            usable_child_dir = attempt_root / "refmac_child" / "refmac"
            intended_target = usable_child_dir / "refmac_manifest.json"
            _, _, preexisting_bytes = _write_json_with_digest(
                intended_target,
                {"squatter": True},
            )
            sibling_payload = {
                "schema_version": 1,
                "status": "diagnostic_captured_gates_unproven",
                "canonical_eval_qds_eligible": False,
            }
            sibling_ref = onesar_refmac._write_json_with_sibling_collision_fallback(
                sibling_payload,
                intended_target,
                root=usable_child_dir,
            )
            self.assertEqual(
                set(sibling_ref.keys()),
                {"path", "sha256", "size_bytes", "fallback_for_preexisting_path"},
            )
            self.assertEqual(
                sibling_ref["fallback_for_preexisting_path"],
                str(intended_target),
            )
            sibling_path = Path(sibling_ref["path"])
            sibling_bytes = sibling_path.read_bytes()

            sibling_loaded = load_retained_reference(
                attempt_root,
                sibling_ref,
                parse_json=True,
                label="refmac_sibling_collision_fallback",
            )
            sibling_vref = sibling_loaded["verified_reference"]
            self.assertEqual(sibling_vref["path"], str(sibling_path))
            self.assertTrue(sibling_vref["is_fallback"])
            self.assertIsNone(sibling_vref["fallback_anchor_dir"])
            self.assertTrue(sibling_vref["integrity_verified"])
            self.assertFalse(sibling_vref["scientific_proof_established"])
            self.assertEqual(intended_target.read_bytes(), preexisting_bytes)
            self.assertEqual(sibling_path.read_bytes(), sibling_bytes)

    def test_rejects_phenix_cache_manifest_when_reconciled_manifest_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            attempt_root = Path(tmp).resolve() / "attempt_phx_wrong_manifest"
            cache_manifest_path = (
                attempt_root / "phenix_child" / "phenix" / "cache" / "bundle" / "success.json"
            )
            cache_sha, _, _ = _write_json_with_digest(
                cache_manifest_path,
                {
                    "returncode": 0,
                    "reusable": True,
                    "invocation": {},
                    "artifacts": {},
                },
            )
            with self.assertRaisesRegex(
                RetainedReferenceError,
                "cache success.json must not be substituted for phenix_reconciled_manifest.json",
            ):
                load_retained_reference(
                    attempt_root,
                    path=cache_manifest_path,
                    sha256=cache_sha,
                    parse_json=True,
                    reject_cache_manifest_as_phenix_reconciled=True,
                    label="phenix_reconciled_manifest",
                )

    def test_rejects_missing_payload_only_and_malformed_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            attempt_root = Path(tmp).resolve() / "attempt_bad_refs"
            attempt_root.mkdir(parents=True, exist_ok=True)
            valid_sha = "a" * 64

            # Payload-only / unpersisted REFMAC record (no_verified_anchor_available).
            unpersisted_ref = {
                "path": None,
                "persisted": False,
                "no_verified_anchor_available": True,
                "sha256": valid_sha,
                "size_bytes": 128,
                "unpersisted_reason": "No verified writable retention anchor available",
            }
            with self.assertRaisesRegex(
                RetainedReferenceError,
                "refusing payload-only or unpersisted artifact reference",
            ):
                load_retained_reference(
                    attempt_root,
                    unpersisted_ref,
                    label="unpersisted_manifest",
                )

            # no_verified_anchor_available=True even if persisted not set to False.
            with self.assertRaisesRegex(
                RetainedReferenceError,
                "no_verified_anchor_available=True",
            ):
                normalize_retained_reference(
                    {
                        "path": str(attempt_root / "x.json"),
                        "sha256": valid_sha,
                        "no_verified_anchor_available": True,
                    }
                )

            # payload_materialized=False.
            with self.assertRaisesRegex(
                RetainedReferenceError,
                "payload_materialized=False",
            ):
                normalize_retained_reference(
                    {
                        "path": str(attempt_root / "x.json"),
                        "sha256": valid_sha,
                        "payload_materialized": False,
                    }
                )

            # Missing reference and path/sha256.
            with self.assertRaisesRegex(
                RetainedReferenceError,
                "explicit reference mapping or \\(path, sha256\\) pair is required",
            ):
                normalize_retained_reference(None)

            # Non-mapping reference.
            with self.assertRaisesRegex(
                RetainedReferenceError,
                "reference must be a mapping",
            ):
                normalize_retained_reference(["not", "a", "mapping"])  # type: ignore[arg-type]

            # Missing path or sha256 keys.
            with self.assertRaisesRegex(
                RetainedReferenceError,
                "missing required path key",
            ):
                normalize_retained_reference({"sha256": valid_sha})
            with self.assertRaisesRegex(
                RetainedReferenceError,
                "missing required sha256 key",
            ):
                normalize_retained_reference(
                    {"path": str(attempt_root / "missing.json")}
                )

            # Malformed sha256 (short or uppercase).
            with self.assertRaisesRegex(
                RetainedReferenceError,
                "expected 64-character lowercase hex sha256",
            ):
                normalize_retained_reference(
                    {"path": str(attempt_root / "a.json"), "sha256": "abc123"}
                )
            with self.assertRaisesRegex(
                RetainedReferenceError,
                "expected 64-character lowercase hex sha256",
            ):
                normalize_retained_reference(
                    {"path": str(attempt_root / "a.json"), "sha256": "A" * 64}
                )

            # Invalid size_bytes (bool or negative).
            with self.assertRaisesRegex(
                RetainedReferenceError,
                "expected non-negative int size_bytes",
            ):
                normalize_retained_reference(
                    {
                        "path": str(attempt_root / "a.json"),
                        "sha256": valid_sha,
                        "size_bytes": True,
                    }
                )
            with self.assertRaisesRegex(
                RetainedReferenceError,
                "expected non-negative int size_bytes",
            ):
                normalize_retained_reference(
                    {
                        "path": str(attempt_root / "a.json"),
                        "sha256": valid_sha,
                        "size_bytes": -1,
                    }
                )

            # Disagreeing explicit vs mapping fields.
            with self.assertRaisesRegex(
                RetainedReferenceError,
                "explicit path .* disagrees with reference",
            ):
                normalize_retained_reference(
                    {"path": str(attempt_root / "a.json"), "sha256": valid_sha},
                    path=attempt_root / "b.json",
                )
            with self.assertRaisesRegex(
                RetainedReferenceError,
                "explicit sha256 .* disagrees with reference",
            ):
                normalize_retained_reference(
                    {"path": str(attempt_root / "a.json"), "sha256": valid_sha},
                    sha256="b" * 64,
                )

            # Missing disk file.
            with self.assertRaisesRegex(
                RetainedReferenceError,
                "retained file does not exist on disk",
            ):
                load_retained_reference(
                    attempt_root,
                    {
                        "path": str(attempt_root / "does_not_exist.json"),
                        "sha256": valid_sha,
                        "size_bytes": 10,
                    },
                )

    def test_rejects_tampered_bytes_wrong_sha256_and_wrong_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            attempt_root = Path(tmp).resolve() / "attempt_tamper"
            target = attempt_root / "sub" / "artifact.json"
            sha, size, _ = _write_json_with_digest(target, {"ok": True})

            # Wrong sha256 with matching size.
            with self.assertRaisesRegex(
                RetainedReferenceError,
                "sha256 mismatch",
            ):
                load_retained_reference(
                    attempt_root,
                    {
                        "path": str(target),
                        "sha256": "0" * 64,
                        "size_bytes": size,
                    },
                )

            # Wrong declared size_bytes with matching sha256.
            with self.assertRaisesRegex(
                RetainedReferenceError,
                "size_bytes mismatch",
            ):
                load_retained_reference(
                    attempt_root,
                    {
                        "path": str(target),
                        "sha256": sha,
                        "size_bytes": size + 1,
                    },
                )

            # Post-write file tamper on disk.
            target.write_bytes(b'{"ok": false}\n')
            with self.assertRaisesRegex(
                RetainedReferenceError,
                "(size_bytes mismatch|sha256 mismatch)",
            ):
                load_retained_reference(
                    attempt_root,
                    {
                        "path": str(target),
                        "sha256": sha,
                        "size_bytes": size,
                    },
                )

    def test_rejects_outside_traversal_symlink_and_nonregular_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            attempt_root = base / "attempt_root"
            outside_dir = base / "outside"
            attempt_root.mkdir(parents=True, exist_ok=True)
            outside_dir.mkdir(parents=True, exist_ok=True)

            outside_file = outside_dir / "secret.json"
            out_sha, out_size, _ = _write_json_with_digest(
                outside_file, {"outside": True}
            )

            # 1. Outside absolute path.
            with self.assertRaisesRegex(
                RetainedReferenceError,
                "is outside admitted root",
            ):
                load_retained_reference(
                    attempt_root,
                    {
                        "path": str(outside_file),
                        "sha256": out_sha,
                        "size_bytes": out_size,
                    },
                )

            # 2. Parent traversal '..' in path.
            with self.assertRaisesRegex(
                RetainedReferenceError,
                "parent-directory traversal",
            ):
                load_retained_reference(
                    attempt_root,
                    {
                        "path": "../outside/secret.json",
                        "sha256": out_sha,
                        "size_bytes": out_size,
                    },
                )

            # 3. Symlink leaf inside admitted_root pointing to outside_file or inside file.
            inside_file = attempt_root / "real.json"
            in_sha, in_size, _ = _write_json_with_digest(
                inside_file, {"inside": True}
            )
            symlink_leaf = attempt_root / "link.json"
            os.symlink(inside_file, symlink_leaf)
            with self.assertRaisesRegex(
                RetainedReferenceError,
                "retained file path is a symlink",
            ):
                load_retained_reference(
                    attempt_root,
                    {
                        "path": str(symlink_leaf),
                        "sha256": in_sha,
                        "size_bytes": in_size,
                    },
                )

            # 4. Symlink ancestor directory inside admitted_root.
            real_subdir = attempt_root / "real_subdir"
            sub_file = real_subdir / "nested.json"
            sub_sha, sub_size, _ = _write_json_with_digest(
                sub_file, {"nested": True}
            )
            symlink_subdir = attempt_root / "link_subdir"
            os.symlink(real_subdir, symlink_subdir)
            with self.assertRaisesRegex(
                RetainedReferenceError,
                "ancestor component is a symlink",
            ):
                load_retained_reference(
                    attempt_root,
                    {
                        "path": str(symlink_subdir / "nested.json"),
                        "sha256": sub_sha,
                        "size_bytes": sub_size,
                    },
                )

            # 5. Symlinked admitted_root itself.
            symlink_root = base / "symlink_attempt_root"
            os.symlink(attempt_root, symlink_root)
            with self.assertRaisesRegex(
                RetainedReferenceError,
                "symlink component is not permitted",
            ):
                load_retained_reference(
                    symlink_root,
                    {
                        "path": str(symlink_root / "real.json"),
                        "sha256": in_sha,
                        "size_bytes": in_size,
                    },
                )

            # 6. Admitted root containing symlink + '..' (#1055):
            # attempt_root/link/.. (where link -> outside_dir/child) resolves on the
            # filesystem to outside_dir, while naive os.path.abspath would erase
            # 'link/..' to attempt_root. Both forms must be rejected before abspath.
            outside_child = outside_dir / "child"
            outside_child.mkdir(parents=True, exist_ok=True)
            link_inside_attempt = attempt_root / "link"
            os.symlink(outside_child, link_inside_attempt)
            erased_symlink_root = f"{attempt_root}/link/.."
            with self.assertRaisesRegex(
                RetainedReferenceError,
                "parent-directory traversal",
            ):
                load_retained_reference(
                    erased_symlink_root,
                    {
                        "path": "real.json",
                        "sha256": in_sha,
                        "size_bytes": in_size,
                    },
                )
            base_link_to_outside = base / "base_link"
            os.symlink(outside_child, base_link_to_outside)
            erased_base_symlink_root = f"{base}/base_link/../attempt_root"
            with self.assertRaisesRegex(
                RetainedReferenceError,
                "parent-directory traversal",
            ):
                load_retained_reference(
                    erased_base_symlink_root,
                    {
                        "path": "real.json",
                        "sha256": in_sha,
                        "size_bytes": in_size,
                    },
                )

            # Normal admitted_root continues to succeed.
            normal_loaded = load_retained_reference(
                attempt_root,
                {
                    "path": "real.json",
                    "sha256": in_sha,
                    "size_bytes": in_size,
                },
                parse_json=True,
                label="normal_root_control",
            )
            self.assertEqual(normal_loaded["json"], {"inside": True})
            self.assertFalse(
                normal_loaded["verified_reference"]["scientific_proof_established"]
            )

            # 7. Non-regular file (directory passed as artifact path).
            with self.assertRaisesRegex(
                RetainedReferenceError,
                "retained path is not a regular file",
            ):
                load_retained_reference(
                    attempt_root,
                    {
                        "path": str(real_subdir),
                        "sha256": in_sha,
                    },
                )

    def test_strict_json_decoding_rejects_malformed_duplicate_keys_and_nonfinite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            attempt_root = Path(tmp).resolve() / "attempt_json"

            cases = [
                (
                    "bad_utf8.json",
                    b"\xff\xfe\xfd",
                    "not valid UTF-8",
                ),
                (
                    "malformed_syntax.json",
                    b'{"a": 1,\n',
                    "malformed JSON content",
                ),
                (
                    "top_level_list.json",
                    b"[1, 2, 3]\n",
                    "expected top-level JSON object mapping",
                ),
                (
                    "duplicate_top_key.json",
                    b'{"a": 1, "a": 2}\n',
                    "duplicate JSON object key 'a'",
                ),
                (
                    "duplicate_nested_key.json",
                    b'{"outer": {"dup": 1, "dup": 2}}\n',
                    "duplicate JSON object key 'dup'",
                ),
                (
                    "nan_constant.json",
                    b'{"r_work": NaN}\n',
                    "non-finite JSON constant 'NaN'",
                ),
                (
                    "inf_constant.json",
                    b'{"r_free": Infinity}\n',
                    "non-finite JSON constant 'Infinity'",
                ),
                (
                    "neginf_constant.json",
                    b'{"gap": -Infinity}\n',
                    "non-finite JSON constant '-Infinity'",
                ),
                (
                    "pos_exp_overflow.json",
                    b'{"value": 1e400}\n',
                    "non-finite JSON float token '1e400'",
                ),
                (
                    "neg_exp_overflow.json",
                    b'{"value": -1e400}\n',
                    "non-finite JSON float token '-1e400'",
                ),
                (
                    "nested_list_object_exp_overflow.json",
                    b'{"outer": {"items": [1.0, 1e400, -1e400]}}\n',
                    "non-finite JSON float token '1e400'",
                ),
            ]

            for filename, raw_bytes, expected_pattern in cases:
                with self.subTest(filename=filename):
                    file_path = attempt_root / filename
                    sha, size = _write_file_with_digest(file_path, raw_bytes)
                    with self.assertRaisesRegex(
                        RetainedReferenceError, expected_pattern
                    ):
                        load_retained_reference(
                            attempt_root,
                            {
                                "path": str(file_path),
                                "sha256": sha,
                                "size_bytes": size,
                            },
                            parse_json=True,
                            label=filename,
                        )
                    with self.assertRaisesRegex(
                        RetainedReferenceError, expected_pattern
                    ):
                        decode_strict_json_mapping(raw_bytes, label=filename)
                    self.assertEqual(file_path.read_bytes(), raw_bytes)

            # Ordinary finite exponent control (#1054) succeeds and preserves bytes.
            finite_exp_bytes = (
                b'{"sci_small": 1.25e-3, "nested": {"arr": [2.5e2, -4.0e1]}}\n'
            )
            finite_exp_path = attempt_root / "finite_exp_control.json"
            fe_sha, fe_size = _write_file_with_digest(
                finite_exp_path, finite_exp_bytes
            )
            direct_decoded = decode_strict_json_mapping(
                finite_exp_bytes, label="finite_exp_control"
            )
            self.assertEqual(
                direct_decoded,
                {"sci_small": 0.00125, "nested": {"arr": [250.0, -40.0]}},
            )
            fe_loaded = load_retained_reference(
                attempt_root,
                {
                    "path": str(finite_exp_path),
                    "sha256": fe_sha,
                    "size_bytes": fe_size,
                },
                parse_json=True,
                label="finite_exp_control",
            )
            self.assertEqual(fe_loaded["json"], direct_decoded)
            self.assertEqual(fe_loaded["bytes"], finite_exp_bytes)
            self.assertEqual(finite_exp_path.read_bytes(), finite_exp_bytes)
            self.assertFalse(
                fe_loaded["verified_reference"]["scientific_proof_established"]
            )


def _snapshot_tree_bytes(root: Path) -> dict[Path, bytes]:
    """Snapshot all regular non-symlink files under ``root`` for immutability checks."""
    snap: dict[Path, bytes] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_symlink() and path.is_file():
            snap[path] = path.read_bytes()
    return snap


def _restore_tree_bytes(root: Path, snapshot: dict[Path, bytes]) -> None:
    """Restore ``root`` to the exact file set and byte contents in ``snapshot``."""
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_symlink() or (path.is_file() and path not in snapshot):
            path.unlink()
    for path, raw_bytes in snapshot.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            path.unlink()
        if not path.exists() or path.read_bytes() != raw_bytes:
            path.write_bytes(raw_bytes)


def _create_synthetic_retained_phenix_envelope(
    tmp_root: Path,
    *,
    subject_id: str = "R4",
    run_name: str = "r4_synthetic_envelope",
    write_completed_partial_checkpoint: bool = False,
) -> dict[str, Any]:
    """Create a clearly labelled synthetic retained PHENIX envelope via real staging/cache.

    Adapts the bounded pattern from
    ``TestPhenixReconciliationAndPureHelpers.test_orchestration_with_real_cache_success_and_failure_retention``
    without invoking any installed PHENIX/CCP4 executable or vendor Python module.
    """
    fake_repo = tmp_root / "synthetic_workspace"
    fake_repo.mkdir(parents=True, exist_ok=True)

    fake_prefix = tmp_root / "phenix-2.0-5936-synthetic"
    fake_bin = fake_prefix / "phenix_bin"
    fake_site = fake_prefix / "lib" / "python3.9" / "site-packages"
    fake_bin.mkdir(parents=True, exist_ok=True)
    (fake_prefix / "phenix_env.sh").write_text(
        "#!/bin/sh\nexport PHENIX_VERSION=2.0\nexport PHENIX_RELEASE_TAG=5936\n",
        encoding="utf-8",
    )
    (fake_bin / "phenix.version").write_text("#!/bin/sh\n", encoding="utf-8")
    (fake_bin / "phenix.python").write_text("#!/bin/sh\n", encoding="utf-8")

    vendor_modules_payload: dict[str, dict[str, str]] = {}
    for key, rel in onesar_rerun.PHENIX_VENDOR_SOURCE_RELPATHS.items():
        mod_file = fake_site / rel
        mod_file.parent.mkdir(parents=True, exist_ok=True)
        content = f"# synthetic test module {key}\n".encode("utf-8")
        mod_file.write_bytes(content)
        resolved_mod = mod_file.resolve(strict=True)
        vendor_modules_payload[key] = {
            "module_name": key,
            "configured_path": str(resolved_mod),
            "resolved_path": str(resolved_mod),
            "sha256": hashlib.sha256(content).hexdigest(),
        }

    banner = "PHENIX: 2.0-5936\n  Version: 2.0\n  Release tag: 5936"
    setup_resolved = (fake_prefix / "phenix_env.sh").resolve(strict=True)
    disp_resolved = (fake_bin / "phenix.version").resolve(strict=True)
    resolved_prefix_str = str(fake_prefix.resolve(strict=True))
    fake_measured_build: dict[str, Any] = {
        "reported_version_source": "vendor_setup_environment",
        "reported_version": banner,
        "parsed_build": "2.0-5936",
        "version_probe": {
            "error": None,
            "probe_mode": "vendor_setup_environment",
            "configured_prefix": str(fake_prefix),
            "resolved_prefix": resolved_prefix_str,
            "setup_configured_path": str(fake_prefix / "phenix_env.sh"),
            "setup_resolved_path": str(setup_resolved),
            "setup_sha256": hashlib.sha256(setup_resolved.read_bytes()).hexdigest(),
            "setup_argv": toolchain.phenix_setup_argv(setup_resolved),
            "setup_returncode": 0,
            "setup_stdout": "",
            "setup_stderr": "",
            "setup_version_fields": {
                "PHENIX_VERSION": "2.0",
                "PHENIX_RELEASE_TAG": "5936",
            },
            "setup_parsed_build": "2.0-5936",
            "configured_path": str(fake_bin / "phenix.version"),
            "resolved_path": str(disp_resolved),
            "sha256": hashlib.sha256(disp_resolved.read_bytes()).hexdigest(),
            "argv": [str(disp_resolved)],
            "returncode": 0,
            "stdout": banner + "\n",
            "stderr": "",
            "parsed_build": "2.0-5936",
            "ignored_inherited_version_variables": [],
            "ignored_inherited_shell_hooks": [],
        },
    }

    selected_summary: dict[str, Any] = {}

    def fake_success_runner(
        argv: list[str], log: Path, *, cwd: Path, timeout: float
    ) -> subprocess.CompletedProcess[str]:
        mtz_arg = Path(argv[argv.index("--mtz") + 1])
        out_json = Path(argv[argv.index("--out-json") + 1])
        out_maps = Path(argv[argv.index("--out-maps-mtz") + 1])
        out_obs_pair = Path(argv[argv.index("--out-obs-pair-mtz") + 1])
        out_diag = Path(argv[argv.index("--out-diagnostics-json") + 1])
        out_partial = Path(argv[argv.index("--out-partial-json") + 1])

        ledger = onesar_rerun.build_input_hkl_ledger(mtz_arg.read_bytes())
        work_candidates = [
            v
            for v in ledger["eligible_by_hkl"].values()
            if not v["is_free"] and v["f_obs"] > 0.0
        ][:3]
        free_candidates = [
            v
            for v in ledger["eligible_by_hkl"].values()
            if v["is_free"] and v["f_obs"] > 0.0
        ][:2]
        w0, w1, w_outlier = work_candidates[0], work_candidates[1], work_candidates[2]
        f0, f1 = free_candidates[0], free_candidates[1]

        scale_k1_w = 0.5
        scale_k1_t = 0.5
        scale_k1 = 0.5
        # Use exact dyadic fractions (7/8 = 0.875 for work, 3/4 = 0.75 for free) so
        # synthetic R_work = 0.125, R_free = 0.25, gap = 0.125 with zero float64 rounding.
        work_ratio = 0.875
        free_ratio = 0.75

        _, base_payload, _, _, _ = _make_reconciliation_fixture()
        synth = copy.deepcopy(base_payload)
        synth["expected_resolved_prefix"] = resolved_prefix_str
        synth["expected_phenix_version"] = toolchain.PHENIX_VERSION
        synth["runtime_environment"]["sys_prefix"] = str(fake_prefix)
        synth["runtime_environment"]["resolved_sys_prefix"] = resolved_prefix_str
        synth["runtime_environment"]["sys_executable"] = str(
            (fake_bin / "phenix.python").resolve(strict=True)
        )
        synth["runtime_environment"]["resolved_sys_executable"] = str(
            (fake_bin / "phenix.python").resolve(strict=True)
        )
        synth["runtime_environment"]["vendor_modules"] = vendor_modules_payload

        extracted_items = [w0, w1, w_outlier, f0, f1]
        final_items = [w0, w1, f0, f1]
        synth["extracted_pre_fmodel"] = [
            {
                "hkl": list(item["hkl"]),
                "f_obs": float(item["f_obs"]),
                "sigf_obs": float(item["sigf_obs"]),
                "is_free": bool(item["is_free"]),
            }
            for item in extracted_items
        ]
        synth["final_effective"] = [
            {
                "hkl": list(item["hkl"]),
                "f_obs": float(item["f_obs"]),
                "sigf_obs": float(item["sigf_obs"]),
                "is_free": bool(item["is_free"]),
            }
            for item in final_items
        ]
        synth["actual_work"] = [
            {
                "hkl": list(item["hkl"]),
                "f_obs": float(item["f_obs"]),
                "sigf_obs": float(item["sigf_obs"]),
                "f_model_real": (work_ratio * float(item["f_obs"])) / scale_k1_w,
                "f_model_imag": 0.0,
                "f_model_amplitude": (work_ratio * float(item["f_obs"])) / scale_k1_w,
                "f_model_scaled_with_k1_w_real": work_ratio * float(item["f_obs"]),
                "f_model_scaled_with_k1_w_imag": 0.0,
                "f_model_scaled_with_k1_w_amplitude": work_ratio * float(item["f_obs"]),
            }
            for item in (w0, w1)
        ]
        synth["actual_free"] = [
            {
                "hkl": list(item["hkl"]),
                "f_obs": float(item["f_obs"]),
                "sigf_obs": float(item["sigf_obs"]),
                "f_model_real": (free_ratio * float(item["f_obs"])) / scale_k1_t,
                "f_model_imag": 0.0,
                "f_model_amplitude": (free_ratio * float(item["f_obs"])) / scale_k1_t,
                "f_model_scaled_with_k1_t_real": free_ratio * float(item["f_obs"]),
                "f_model_scaled_with_k1_t_imag": 0.0,
                "f_model_scaled_with_k1_t_amplitude": free_ratio * float(item["f_obs"]),
            }
            for item in (f0, f1)
        ]

        w_den = float(w0["f_obs"]) + float(w1["f_obs"])
        w_num = abs(float(w0["f_obs"]) - work_ratio * float(w0["f_obs"])) + abs(
            float(w1["f_obs"]) - work_ratio * float(w1["f_obs"])
        )
        f_den = float(f0["f_obs"]) + float(f1["f_obs"])
        f_num = abs(float(f0["f_obs"]) - free_ratio * float(f0["f_obs"])) + abs(
            float(f1["f_obs"]) - free_ratio * float(f1["f_obs"])
        )
        all_num = w_num + f_num
        all_den = w_den + f_den
        r_work = w_num / w_den
        r_free = f_num / f_den
        r_all = all_num / all_den
        r_gap = r_free - r_work

        synth["scales_and_rfactors"].update(
            {
                "r_work": r_work,
                "r_free": r_free,
                "r_all": r_all,
                "r_free_r_work_gap": r_gap,
                "scale_k1_w": scale_k1_w,
                "scale_k1_t": scale_k1_t,
                "scale_k1": scale_k1,
                "work_numerator": w_num,
                "work_denominator": w_den,
                "free_numerator": f_num,
                "free_denominator": f_den,
                "all_numerator": all_num,
                "all_denominator": all_den,
                "work_count": 2,
                "free_count": 2,
                "final_effective_count": 4,
                "extracted_pre_fmodel_count": 5,
            }
        )

        map_recs = [
            {
                "hkl": list(item["hkl"]),
                "real": 1.0,
                "imag": 0.0,
                "amplitude": 1.0,
                "phase_deg": 0.0,
                "is_centric": True,
            }
            for item in final_items
        ]
        synth["map_coefficients"]["2mFo-DFc"]["records"] = copy.deepcopy(map_recs)
        synth["map_coefficients"]["2mFo-DFc"]["centric_count"] = 4
        synth["map_coefficients"]["2mFo-DFc"]["acentric_count"] = 0
        synth["map_coefficients"]["mFo-DFc"]["records"] = copy.deepcopy(map_recs)
        synth["map_coefficients"]["mFo-DFc"]["centric_count"] = 4
        synth["map_coefficients"]["mFo-DFc"]["acentric_count"] = 0

        cell_floats = tuple(
            float(x)
            for x in ledger["crystallographic_context"]["cell_a_b_c_alpha_beta_gamma"]
        )
        runtime_cell_floats = onesar_rerun.ccp4_mtz_float32_unit_cell(
            ledger["crystallographic_context"]["cell_a_b_c_alpha_beta_gamma"]
        )
        synth["crystal_symmetry"] = {
            "unit_cell": list(runtime_cell_floats),
            "space_group_symbol": "P 21 21 21 (No. 19)",
            "space_group_number": 19,
            "space_group_operators_xyz": [
                "x,y,z",
                "-x+1/2,-y,z+1/2",
                "-x,y+1/2,-z+1/2",
                "x+1/2,-y+1/2,-z",
            ],
        }
        ca, cb, cc = (
            runtime_cell_floats[0],
            runtime_cell_floats[1],
            runtime_cell_floats[2],
        )

        def _orth_range(items: list[dict[str, Any]]) -> dict[str, float]:
            ds = [
                1.0
                / math.sqrt(
                    (it["hkl"][0] / ca) ** 2
                    + (it["hkl"][1] / cb) ** 2
                    + (it["hkl"][2] / cc) ** 2
                )
                for it in items
            ]
            return {"d_max": max(ds), "d_min": min(ds)}

        synth["resolution_ranges"] = {
            "extracted_pre_fmodel": _orth_range(extracted_items),
            "final_effective": _orth_range(final_items),
            "actual_work": _orth_range([w0, w1]),
            "actual_free": _orth_range([f0, f1]),
        }

        m_bytes, p_bytes = _build_synthetic_map_mtz_pair(
            map_recs, map_recs, cell=cell_floats  # type: ignore[arg-type]
        )
        synth["map_coefficients"]["mtz_supplements"]["phx_maps_sha256"] = (
            hashlib.sha256(m_bytes).hexdigest()
        )
        synth["map_coefficients"]["mtz_supplements"]["obs_pair_only_sha256"] = (
            hashlib.sha256(p_bytes).hexdigest()
        )

        diag_doc = {
            "schema_version": 1,
            "status": "succeeded",
            "extract_xtal_data_log": synth["diagnostics"]["extract_xtal_data_log"],
            "model_manager_log": synth["diagnostics"]["model_manager_log"],
            "fmodel_update_all_scales_log": synth["diagnostics"][
                "fmodel_update_all_scales_log"
            ],
            "failure": None,
        }
        log.write_text("synthetic phenix.python stdout\n", encoding="utf-8")
        out_maps.write_bytes(m_bytes)
        out_obs_pair.write_bytes(p_bytes)
        out_diag.write_text(
            json.dumps(diag_doc, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if write_completed_partial_checkpoint:
            partial_doc = {
                "schema_version": 1,
                "status": "completed_superseded_by_verified_payload",
                "current_phase": "completed",
                "failure": None,
                "nonfinite_raw_values": [],
            }
            out_partial.write_text(
                json.dumps(partial_doc, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        out_json.write_text(
            json.dumps(synth, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        selected_summary.update(
            {
                "expected_work_hkls": sorted(
                    [list(w0["hkl"]), list(w1["hkl"])],
                    key=lambda h: (h[0], h[1], h[2]),
                ),
                "expected_free_hkls": sorted(
                    [list(f0["hkl"]), list(f1["hkl"])],
                    key=lambda h: (h[0], h[1], h[2]),
                ),
                "expected_outlier_hkl": list(w_outlier["hkl"]),
                "expected_r_work": r_work,
                "expected_r_free": r_free,
                "expected_r_all": r_all,
                "expected_r_gap": r_gap,
                "expected_work_numerator": w_num,
                "expected_work_denominator": w_den,
                "expected_free_numerator": f_num,
                "expected_free_denominator": f_den,
            }
        )
        return subprocess.CompletedProcess(argv, 0)

    admitted_root = fake_repo / "runs"
    evidence_root = admitted_root / run_name
    with (
        mock.patch.object(
            toolchain,
            "phenix",
            side_effect=lambda exe: fake_bin / exe,
        ),
        mock.patch.object(
            toolchain,
            "phenix_build_evidence",
            return_value=fake_measured_build,
        ),
    ):
        reconciled_record = onesar_rerun.run_phenix_rfactor_operation(
            evidence_root,
            subject_id=subject_id,
            repo_root=fake_repo,
            archive_path=COMMITTED_ARCHIVE,
            require_no_protstruct_overrides=False,
            runner=fake_success_runner,
        )

    reconciled_manifest_path = (
        evidence_root / "phenix" / "phenix_reconciled_manifest.json"
    )
    reconciled_manifest_bytes = reconciled_manifest_path.read_bytes()
    reconciled_manifest_sha256 = hashlib.sha256(reconciled_manifest_bytes).hexdigest()
    return {
        "admitted_root": admitted_root,
        "evidence_root": evidence_root,
        "fake_prefix": fake_prefix,
        "fake_measured_build": fake_measured_build,
        "reconciled_record": reconciled_record,
        "reconciled_manifest_path": reconciled_manifest_path,
        "reconciled_manifest_sha256": reconciled_manifest_sha256,
        "reconciled_manifest_size_bytes": len(reconciled_manifest_bytes),
        **selected_summary,
    }


def _rehash_cache_and_reconciled_manifest(
    evidence_root: Path,
    *,
    reconciled_doc: dict[str, Any] | None = None,
    cache_manifest_doc: dict[str, Any] | None = None,
) -> tuple[Path, str, int]:
    """Rewrite cache ``success.json`` and ``phenix_reconciled_manifest.json`` after a test mutation."""
    reconciled_path = evidence_root / "phenix" / "phenix_reconciled_manifest.json"
    if reconciled_doc is None:
        reconciled_doc = json.loads(reconciled_path.read_text(encoding="utf-8"))
    cache_manifest_path = Path(reconciled_doc["manifest_path"])
    if cache_manifest_doc is None:
        cache_manifest_doc = json.loads(
            cache_manifest_path.read_text(encoding="utf-8")
        )
    bundle_dir = cache_manifest_path.parent
    for entry in cache_manifest_doc.get("artifacts", {}).values():
        if isinstance(entry, dict) and isinstance(entry.get("path"), str):
            art_file = bundle_dir / entry["path"]
            if art_file.is_file() and not art_file.is_symlink():
                entry["sha256"] = hashlib.sha256(art_file.read_bytes()).hexdigest()
    cache_sha, _, _ = _write_json_with_digest(cache_manifest_path, cache_manifest_doc)
    reconciled_doc["manifest_sha256"] = cache_sha
    reconciled_doc["operation_manifest"] = cache_manifest_doc
    rec_sha, rec_size, _ = _write_json_with_digest(reconciled_path, reconciled_doc)
    return reconciled_path, rec_sha, rec_size


class TestPhenixRetainedVerifier(unittest.TestCase):
    """Hermetic tests for Task 363/366 verify_retained_phenix_rfactor_evidence."""

    def test_synthetic_retained_envelope_reaches_verifier_without_execution_or_mutation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp).resolve(strict=True)
            env = _create_synthetic_retained_phenix_envelope(
                tmp_root,
                subject_id="R4",
                run_name="r4_baseline",
                write_completed_partial_checkpoint=False,
            )
            admitted_root: Path = env["admitted_root"]
            evidence_root: Path = env["evidence_root"]
            fake_prefix: Path = env["fake_prefix"]
            rec_path: Path = env["reconciled_manifest_path"]
            rec_sha: str = env["reconciled_manifest_sha256"]
            rec_size: int = env["reconciled_manifest_size_bytes"]

            admitted_snapshot = _snapshot_tree_bytes(admitted_root)
            prefix_snapshot = _snapshot_tree_bytes(fake_prefix)

            # Forbid any producer, cache execution, build probe, or subprocess launch
            # during pure verification.
            with (
                mock.patch.object(
                    onesar_rerun,
                    "run_phenix_rfactor_operation",
                    side_effect=AssertionError(
                        "run_phenix_rfactor_operation must not be called"
                    ),
                ),
                mock.patch.object(
                    refinement_cache,
                    "cached_phenix_operation",
                    side_effect=AssertionError(
                        "cached_phenix_operation must not be called"
                    ),
                ),
                mock.patch.object(
                    refinement_cache,
                    "cached_operation",
                    side_effect=AssertionError("cached_operation must not be called"),
                ),
                mock.patch.object(
                    toolchain,
                    "phenix_build_evidence",
                    side_effect=AssertionError(
                        "phenix_build_evidence must not be called"
                    ),
                ),
                mock.patch.object(
                    toolchain,
                    "phenix",
                    side_effect=AssertionError("toolchain.phenix must not be called"),
                ),
                mock.patch.object(
                    toolchain,
                    "run_logged",
                    side_effect=AssertionError(
                        "toolchain.run_logged must not be called"
                    ),
                ),
                mock.patch.object(
                    subprocess,
                    "run",
                    side_effect=AssertionError("subprocess.run must not be called"),
                ),
            ):
                verified = verify_retained_phenix_rfactor_evidence(
                    admitted_root,
                    subject_id="R4",
                    reconciled_manifest_path=rec_path,
                    reconciled_manifest_sha256=rec_sha,
                    reconciled_manifest_size_bytes=rec_size,
                    repo_root=REPO_ROOT,
                )
                verified_via_ref = verify_retained_phenix_rfactor_evidence(
                    admitted_root,
                    subject_id="R4",
                    reconciled_manifest_reference={
                        "path": str(rec_path),
                        "sha256": rec_sha,
                        "size_bytes": rec_size,
                    },
                    repo_root=REPO_ROOT,
                )

            self.assertEqual(verified, verified_via_ref)
            self.assertEqual(_snapshot_tree_bytes(admitted_root), admitted_snapshot)
            self.assertEqual(_snapshot_tree_bytes(fake_prefix), prefix_snapshot)

            self.assertEqual(verified["producer"], "phenix")
            self.assertEqual(verified["verification_status"], "verified")
            self.assertEqual(verified["admitted_root"], str(admitted_root))
            self.assertEqual(verified["evidence_root"], str(evidence_root))
            self.assertEqual(verified["repo_root"], str(REPO_ROOT))
            self.assertEqual(verified["subject_id"], "R4")
            self.assertEqual(
                verified["subject"], onesar_rerun.resolve_subject_spec("R4")
            )
            self.assertEqual(
                verified["mtz"],
                {
                    "member": onesar_rerun.MTZ_MEMBER,
                    "sha256": onesar_rerun.MTZ_SHA256,
                    "subject_ref": onesar_rerun.MTZ_SUBJECT_REF,
                },
            )
            self.assertEqual(verified["reconciled_manifest_path"], str(rec_path))
            self.assertEqual(verified["reconciled_manifest_sha256"], rec_sha)
            self.assertNotEqual(
                verified["manifest_path"], verified["reconciled_manifest_path"]
            )
            self.assertEqual(Path(verified["manifest_path"]).name, "success.json")
            self.assertEqual(
                Path(verified["manifest_path"]).parent.name, "bundle"
            )

            # Counts and HKL sets (#1058).
            self.assertEqual(verified["work_count"], 2)
            self.assertEqual(verified["free_count"], 2)
            self.assertEqual(verified["counts"]["raw_mtz_total"], 7248)
            self.assertEqual(verified["counts"]["input_eligible_total"], 7228)
            self.assertEqual(verified["counts"]["extracted_pre_fmodel_total"], 5)
            self.assertEqual(verified["counts"]["final_effective_total"], 4)
            self.assertEqual(verified["counts"]["actual_work_total"], 2)
            self.assertEqual(verified["counts"]["actual_free_total"], 2)
            self.assertEqual(verified["counts"]["excluded_raw_to_input_eligible"], 20)
            self.assertEqual(
                verified["counts"]["excluded_extracted_to_final_effective"], 1
            )
            self.assertEqual(
                verified["actual_work_hkls"], env["expected_work_hkls"]
            )
            self.assertEqual(
                verified["actual_free_hkls"], env["expected_free_hkls"]
            )

            # R-factors and replay agreement (#1059, #1060).
            rf = verified["rfactors"]
            self.assertAlmostEqual(rf["r_work"], 0.125, places=15)
            self.assertAlmostEqual(rf["r_free"], 0.25, places=15)
            self.assertAlmostEqual(rf["r_free_r_work_gap"], 0.125, places=15)
            self.assertAlmostEqual(rf["replayed_r_work"], 0.125, places=15)
            self.assertAlmostEqual(rf["replayed_r_free"], 0.25, places=15)
            self.assertAlmostEqual(rf["replayed_r_free_r_work_gap"], 0.125, places=15)
            self.assertAlmostEqual(
                rf["r_all"], env["expected_r_all"], places=15
            )
            self.assertAlmostEqual(
                rf["replayed_r_all"], env["expected_r_all"], places=15
            )
            self.assertAlmostEqual(
                rf["work_numerator"], env["expected_work_numerator"], places=12
            )
            self.assertAlmostEqual(
                rf["work_denominator"], env["expected_work_denominator"], places=12
            )
            self.assertAlmostEqual(
                rf["free_numerator"], env["expected_free_numerator"], places=12
            )
            self.assertAlmostEqual(
                rf["free_denominator"], env["expected_free_denominator"], places=12
            )
            self.assertEqual(rf["scale_k1_w"], 0.5)
            self.assertEqual(rf["scale_k1_t"], 0.5)
            self.assertEqual(rf["scale_k1"], 0.5)

            # Intra-PHENIX set differences vs cross-tool symmetric differences.
            intra_diffs = verified["intra_phenix_set_differences"]
            self.assertEqual(
                set(intra_diffs.keys()),
                {
                    "raw_to_input_eligible_excluded_hkls",
                    "input_eligible_to_extracted_excluded_hkls",
                    "extracted_to_final_effective_excluded_hkls",
                },
            )
            self.assertEqual(
                len(intra_diffs["raw_to_input_eligible_excluded_hkls"]), 20
            )
            self.assertEqual(
                len(intra_diffs["input_eligible_to_extracted_excluded_hkls"]),
                7223,
            )
            self.assertEqual(
                intra_diffs["extracted_to_final_effective_excluded_hkls"],
                [env["expected_outlier_hkl"]],
            )
            self.assertIsNone(verified["cross_tool_symmetric_differences"])

            # Input ledger preserves zero-F eligibility on 1SAR.mtz (11 zero-F rows).
            self.assertEqual(
                verified["input_hkl_ledger_summary"]["counts"]["eligible_zero_f"],
                11,
            )
            self.assertIsNone(
                verified["verified_references"]["partial_evidence_json"]
            )

            # One-producer meaning and explicit non-established boundaries.
            self.assertEqual(
                verified["verification_boundaries"],
                {
                    "phenix_retained_evidence_verified": True,
                    "independent_oracle_cross_check_established": False,
                    "refmac_native_proof_established": False,
                    "canary_scientific_admission_established": False,
                    "eval_or_qds_published": False,
                },
            )
            self.assertFalse(
                verified["verified_references"]["reconciled_manifest"][
                    "scientific_proof_established"
                ]
            )

            # Also verify completed partial-evidence checkpoint envelope when present.
            env_partial = _create_synthetic_retained_phenix_envelope(
                tmp_root / "with_partial",
                subject_id="start",
                run_name="start_with_partial",
                write_completed_partial_checkpoint=True,
            )
            verified_partial = verify_retained_phenix_rfactor_evidence(
                env_partial["admitted_root"],
                subject_id="start",
                reconciled_manifest_path=env_partial["reconciled_manifest_path"],
                reconciled_manifest_sha256=env_partial["reconciled_manifest_sha256"],
                repo_root=REPO_ROOT,
            )
            self.assertEqual(verified_partial["subject_id"], "start")
            self.assertEqual(verified_partial["subject"]["stage"], "start")
            self.assertIsNotNone(
                verified_partial["verified_references"]["partial_evidence_json"]
            )
            self.assertTrue(
                verified_partial["verified_references"]["partial_evidence_json"][
                    "integrity_verified"
                ]
            )

    def test_rejects_manifest_substitution_tampered_inputs_and_provenance_mismatches(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp).resolve(strict=True)
            env = _create_synthetic_retained_phenix_envelope(
                tmp_root,
                subject_id="R4",
                run_name="r4_tamper_suite",
                write_completed_partial_checkpoint=True,
            )
            admitted_root: Path = env["admitted_root"]
            evidence_root: Path = env["evidence_root"]
            fake_prefix: Path = env["fake_prefix"]
            rec_path: Path = env["reconciled_manifest_path"]
            rec_sha: str = env["reconciled_manifest_sha256"]

            admitted_snapshot = _snapshot_tree_bytes(admitted_root)
            prefix_snapshot = _snapshot_tree_bytes(fake_prefix)

            def _reset() -> None:
                _restore_tree_bytes(admitted_root, admitted_snapshot)
                _restore_tree_bytes(fake_prefix, prefix_snapshot)

            # 1. Substituting cache bundle/success.json for phenix_reconciled_manifest.json fails.
            with self.subTest(case="substitute_cache_manifest"):
                cache_manifest_path = Path(env["reconciled_record"]["manifest_path"])
                cache_manifest_sha = env["reconciled_record"]["manifest_sha256"]
                with self.assertRaisesRegex(
                    PhenixRetainedVerificationError,
                    "cache success.json must not be substituted for phenix_reconciled_manifest.json",
                ):
                    verify_retained_phenix_rfactor_evidence(
                        admitted_root,
                        subject_id="R4",
                        reconciled_manifest_path=cache_manifest_path,
                        reconciled_manifest_sha256=cache_manifest_sha,
                        repo_root=REPO_ROOT,
                    )

            # 2. Wrong subject_id ("start" for an "R4" envelope) or forbidden "R7" fails.
            with self.subTest(case="wrong_or_forbidden_subject"):
                with self.assertRaisesRegex(
                    PhenixRetainedVerificationError,
                    "phenix_reconciled_manifest\\.subject: disagrees with preregistered subject",
                ):
                    verify_retained_phenix_rfactor_evidence(
                        admitted_root,
                        subject_id="start",
                        reconciled_manifest_path=rec_path,
                        reconciled_manifest_sha256=rec_sha,
                        repo_root=REPO_ROOT,
                    )
                with self.assertRaisesRegex(
                    PhenixRetainedVerificationError,
                    "subject_id: .*R7",
                ):
                    verify_retained_phenix_rfactor_evidence(
                        admitted_root,
                        subject_id="R7",
                        reconciled_manifest_path=rec_path,
                        reconciled_manifest_sha256=rec_sha,
                        repo_root=REPO_ROOT,
                    )

            # 3. Presence of failure marker in phenix/ fails.
            with self.subTest(case="failure_marker_present"):
                try:
                    failure_marker = (
                        evidence_root / "phenix" / "phenix_operation_failure.json"
                    )
                    failure_marker.write_text(
                        '{"status": "failed"}\n', encoding="utf-8"
                    )
                    with self.assertRaisesRegex(
                        PhenixRetainedVerificationError,
                        "refusing retained PHENIX directory with failure record present",
                    ):
                        verify_retained_phenix_rfactor_evidence(
                            admitted_root,
                            subject_id="R4",
                            reconciled_manifest_path=rec_path,
                            reconciled_manifest_sha256=rec_sha,
                            repo_root=REPO_ROOT,
                        )
                finally:
                    _reset()

            # 4. Tampered projected_observations.mtz (even with re-signed staged_files digest) fails
            # pure project_observation_mtz reproduction.
            with self.subTest(case="tampered_projected_mtz_rehashed"):
                try:
                    proj_path = (
                        evidence_root / "inputs" / "projected_observations.mtz"
                    )
                    orig_mtz_path = (
                        evidence_root / "inputs" / "original_data.mtz"
                    )
                    proj_path.write_bytes(orig_mtz_path.read_bytes())
                    new_proj_sha = hashlib.sha256(
                        proj_path.read_bytes()
                    ).hexdigest()
                    rec_doc = json.loads(rec_path.read_text(encoding="utf-8"))
                    rec_doc["staged_files"][
                        "projected_observations_mtz_sha256"
                    ] = new_proj_sha
                    new_rec_sha, _, _ = _write_json_with_digest(
                        rec_path, rec_doc
                    )
                    with self.assertRaisesRegex(
                        PhenixRetainedVerificationError,
                        "staged_files\\.projected_observations_mtz: retained bytes or digest disagree with pure observation-only MTZ projection",
                    ):
                        verify_retained_phenix_rfactor_evidence(
                            admitted_root,
                            subject_id="R4",
                            reconciled_manifest_path=rec_path,
                            reconciled_manifest_sha256=new_rec_sha,
                            repo_root=REPO_ROOT,
                        )
                finally:
                    _reset()

            # 5. Tampered input_hkl_ledger.json (e.g. zeroing eligible_zero_f and re-signing
            # both staged_files and top-level sha256) fails pure build_input_hkl_ledger rebuild.
            with self.subTest(case="tampered_input_ledger_zero_f_rehashed"):
                try:
                    ledger_path = (
                        evidence_root / "inputs" / "input_hkl_ledger.json"
                    )
                    ledger_doc = json.loads(
                        ledger_path.read_text(encoding="utf-8")
                    )
                    ledger_doc["counts"]["eligible_zero_f"] = 0
                    new_ledger_sha, _, _ = _write_json_with_digest(
                        ledger_path, ledger_doc
                    )
                    rec_doc = json.loads(rec_path.read_text(encoding="utf-8"))
                    rec_doc["staged_files"]["input_hkl_ledger_json_sha256"] = (
                        new_ledger_sha
                    )
                    rec_doc["input_hkl_ledger_json_sha256"] = new_ledger_sha
                    new_rec_sha, _, _ = _write_json_with_digest(
                        rec_path, rec_doc
                    )
                    with self.assertRaisesRegex(
                        PhenixRetainedVerificationError,
                        "staged_files\\.input_hkl_ledger_json: retained ledger disagrees with pure rebuild",
                    ):
                        verify_retained_phenix_rfactor_evidence(
                            admitted_root,
                            subject_id="R4",
                            reconciled_manifest_path=rec_path,
                            reconciled_manifest_sha256=new_rec_sha,
                            repo_root=REPO_ROOT,
                        )
                finally:
                    _reset()

            # 6. Top-level duplicate path/digest disagreement with staged_files or cache_artifacts fails.
            with self.subTest(case="duplicate_reference_disagreement"):
                try:
                    rec_doc = json.loads(rec_path.read_text(encoding="utf-8"))
                    rec_doc["input_hkl_ledger_json_sha256"] = "0" * 64
                    new_rec_sha, _, _ = _write_json_with_digest(
                        rec_path, rec_doc
                    )
                    with self.assertRaisesRegex(
                        PhenixRetainedVerificationError,
                        "top-level input_hkl_ledger_json_path/sha256 disagrees with staged_files",
                    ):
                        verify_retained_phenix_rfactor_evidence(
                            admitted_root,
                            subject_id="R4",
                            reconciled_manifest_path=rec_path,
                            reconciled_manifest_sha256=new_rec_sha,
                            repo_root=REPO_ROOT,
                        )
                finally:
                    _reset()

                try:
                    rec_doc = json.loads(rec_path.read_text(encoding="utf-8"))
                    rec_doc["phenix_rfactors_json_path"] = str(
                        evidence_root / "phenix" / "phenix_rfactors.json"
                    )
                    new_rec_sha, _, _ = _write_json_with_digest(
                        rec_path, rec_doc
                    )
                    with self.assertRaisesRegex(
                        PhenixRetainedVerificationError,
                        "phenix_reconciled_manifest\\.phenix_rfactors_json_path: disagrees with verified cache bundle artifact",
                    ):
                        verify_retained_phenix_rfactor_evidence(
                            admitted_root,
                            subject_id="R4",
                            reconciled_manifest_path=rec_path,
                            reconciled_manifest_sha256=new_rec_sha,
                            repo_root=REPO_ROOT,
                        )
                finally:
                    _reset()

            # 7. Unmeasured, wrong-version, or drifted PHENIX build evidence fails.
            with self.subTest(case="unmeasured_or_drifted_build_evidence"):
                preflight_path = (
                    evidence_root
                    / "phenix"
                    / "phenix_preflight_build_evidence.json"
                )
                try:
                    preflight_doc = json.loads(
                        preflight_path.read_text(encoding="utf-8")
                    )
                    preflight_doc["reported_version_source"] = "command_output"
                    new_pf_sha, _, _ = _write_json_with_digest(
                        preflight_path, preflight_doc
                    )
                    rec_doc = json.loads(rec_path.read_text(encoding="utf-8"))
                    rec_doc["preflight_build_evidence_sha256"] = new_pf_sha
                    new_rec_sha, _, _ = _write_json_with_digest(
                        rec_path, rec_doc
                    )
                    with self.assertRaisesRegex(
                        PhenixRetainedVerificationError,
                        "failed #957 admission gate",
                    ):
                        verify_retained_phenix_rfactor_evidence(
                            admitted_root,
                            subject_id="R4",
                            reconciled_manifest_path=rec_path,
                            reconciled_manifest_sha256=new_rec_sha,
                            repo_root=REPO_ROOT,
                        )
                finally:
                    _reset()

                # Consistently measured wrong PHENIX release (2.0-5935) passes _build_is_measured
                # and fails the pinned-version check in validate_measured_phenix_build.
                try:
                    preflight_doc = json.loads(
                        preflight_path.read_text(encoding="utf-8")
                    )
                    wrong_banner = (
                        "PHENIX: 2.0-5935\n  Version: 2.0\n  Release tag: 5935"
                    )
                    preflight_doc["reported_version"] = wrong_banner
                    preflight_doc["parsed_build"] = "2.0-5935"
                    preflight_doc["version_probe"]["setup_version_fields"] = {
                        "PHENIX_VERSION": "2.0",
                        "PHENIX_RELEASE_TAG": "5935",
                    }
                    preflight_doc["version_probe"]["setup_parsed_build"] = (
                        "2.0-5935"
                    )
                    preflight_doc["version_probe"]["stdout"] = (
                        wrong_banner + "\n"
                    )
                    preflight_doc["version_probe"]["parsed_build"] = "2.0-5935"
                    new_pf_sha, _, _ = _write_json_with_digest(
                        preflight_path, preflight_doc
                    )
                    rec_doc = json.loads(rec_path.read_text(encoding="utf-8"))
                    rec_doc["preflight_build_evidence_sha256"] = new_pf_sha
                    new_rec_sha, _, _ = _write_json_with_digest(
                        rec_path, rec_doc
                    )
                    with self.assertRaisesRegex(
                        PhenixRetainedVerificationError,
                        "PHENIX build version mismatch: expected '2\\.0-5936'",
                    ):
                        verify_retained_phenix_rfactor_evidence(
                            admitted_root,
                            subject_id="R4",
                            reconciled_manifest_path=rec_path,
                            reconciled_manifest_sha256=new_rec_sha,
                            repo_root=REPO_ROOT,
                        )
                finally:
                    _reset()

                # Cache invocation measured_build passes validate_measured_phenix_build at 2.0-5936
                # under a different installation prefix, failing preflight vs cache identity check.
                try:
                    other_prefix = tmp_root / "phenix-2.0-5936-other-prefix"
                    other_setup = other_prefix / "phenix_env.sh"
                    other_disp = other_prefix / "phenix_bin" / "phenix.version"
                    rec_doc = json.loads(rec_path.read_text(encoding="utf-8"))
                    cache_doc = copy.deepcopy(rec_doc["operation_manifest"])
                    other_prefix_build = copy.deepcopy(
                        cache_doc["invocation"]["measured_build"]
                    )
                    probe = other_prefix_build["version_probe"]
                    probe["configured_prefix"] = str(other_prefix)
                    probe["resolved_prefix"] = str(other_prefix)
                    probe["setup_configured_path"] = str(other_setup)
                    probe["setup_resolved_path"] = str(other_setup)
                    probe["setup_argv"] = toolchain.phenix_setup_argv(
                        other_setup
                    )
                    probe["configured_path"] = str(other_disp)
                    probe["resolved_path"] = str(other_disp)
                    probe["argv"] = [str(other_disp)]
                    cache_doc["invocation"]["measured_build"] = (
                        other_prefix_build
                    )
                    _, new_rec_sha, _ = _rehash_cache_and_reconciled_manifest(
                        evidence_root,
                        reconciled_doc=rec_doc,
                        cache_manifest_doc=cache_doc,
                    )
                    with self.assertRaisesRegex(
                        PhenixRetainedVerificationError,
                        "cache_operation_manifest\\.invocation\\.measured_build: drifted from preflight PHENIX build evidence",
                    ):
                        verify_retained_phenix_rfactor_evidence(
                            admitted_root,
                            subject_id="R4",
                            reconciled_manifest_path=rec_path,
                            reconciled_manifest_sha256=new_rec_sha,
                            repo_root=REPO_ROOT,
                        )
                finally:
                    _reset()

            # 8. Operation parameters contract or metadata mismatch fails.
            with self.subTest(case="parameters_contract_or_metadata_mismatch"):
                try:
                    params_path = (
                        evidence_root
                        / "phenix"
                        / "phenix_operation_parameters.json"
                    )
                    params_doc = json.loads(
                        params_path.read_text(encoding="utf-8")
                    )
                    params_doc["apply_pdb_header_resolution_cut"] = True
                    new_params_sha, _, _ = _write_json_with_digest(
                        params_path, params_doc
                    )
                    rec_doc = json.loads(rec_path.read_text(encoding="utf-8"))
                    cache_doc = copy.deepcopy(rec_doc["operation_manifest"])
                    cache_doc["invocation"]["inputs"]["parameters_json"][
                        "sha256"
                    ] = new_params_sha
                    _, new_rec_sha, _ = _rehash_cache_and_reconciled_manifest(
                        evidence_root,
                        reconciled_doc=rec_doc,
                        cache_manifest_doc=cache_doc,
                    )
                    with self.assertRaisesRegex(
                        PhenixRetainedVerificationError,
                        "validate_parameters_contract",
                    ):
                        verify_retained_phenix_rfactor_evidence(
                            admitted_root,
                            subject_id="R4",
                            reconciled_manifest_path=rec_path,
                            reconciled_manifest_sha256=new_rec_sha,
                            repo_root=REPO_ROOT,
                        )
                finally:
                    _reset()

            # 9. External provenance mismatch (wrong repo_root or tampered vendor module) fails.
            with self.subTest(case="external_helper_or_vendor_module_mismatch"):
                other_repo = tmp_root / "other_repo"
                (other_repo / "scripts").mkdir(parents=True, exist_ok=True)
                (other_repo / "scripts" / "onesar_phenix_measure.py").write_text(
                    "# wrong helper\n", encoding="utf-8"
                )
                with self.assertRaisesRegex(
                    PhenixRetainedVerificationError,
                    "invocation\\.inputs\\.helper_script: path .* is outside admitted root",
                ):
                    verify_retained_phenix_rfactor_evidence(
                        admitted_root,
                        subject_id="R4",
                        reconciled_manifest_path=rec_path,
                        reconciled_manifest_sha256=rec_sha,
                        repo_root=other_repo,
                    )

                try:
                    vendor_mod_path = (
                        fake_prefix
                        / "lib"
                        / "python3.9"
                        / "site-packages"
                        / onesar_rerun.PHENIX_VENDOR_SOURCE_RELPATHS[
                            "vendor_mmtbx_model_vs_data"
                        ]
                    )
                    vendor_mod_path.write_bytes(b"# tampered vendor source\n")
                    with self.assertRaisesRegex(
                        PhenixRetainedVerificationError,
                        "invocation\\.inputs\\.vendor_mmtbx_model_vs_data: sha256 mismatch",
                    ):
                        verify_retained_phenix_rfactor_evidence(
                            admitted_root,
                            subject_id="R4",
                            reconciled_manifest_path=rec_path,
                            reconciled_manifest_sha256=rec_sha,
                            repo_root=REPO_ROOT,
                        )
                finally:
                    _reset()

            # 10. Cache bundle contract: non-bundle-relative artifact path or failed partial
            # checkpoint status fails.
            with self.subTest(case="cache_bundle_and_partial_checkpoint_contracts"):
                try:
                    rec_doc = json.loads(rec_path.read_text(encoding="utf-8"))
                    cache_doc = copy.deepcopy(rec_doc["operation_manifest"])
                    cache_doc["artifacts"]["phenix_rfactors_json"]["path"] = (
                        "../phenix_rfactors.json"
                    )
                    cache_sha, _, _ = _write_json_with_digest(
                        Path(rec_doc["manifest_path"]), cache_doc
                    )
                    rec_doc["manifest_sha256"] = cache_sha
                    rec_doc["operation_manifest"] = cache_doc
                    new_rec_sha, _, _ = _write_json_with_digest(
                        rec_path, rec_doc
                    )
                    with self.assertRaisesRegex(
                        PhenixRetainedVerificationError,
                        "(refinement_cache\\._read_success|expected bundle-relative path 'phenix_rfactors\\.json')",
                    ):
                        verify_retained_phenix_rfactor_evidence(
                            admitted_root,
                            subject_id="R4",
                            reconciled_manifest_path=rec_path,
                            reconciled_manifest_sha256=new_rec_sha,
                            repo_root=REPO_ROOT,
                        )
                finally:
                    _reset()

                try:
                    partial_path = Path(
                        env["reconciled_record"][
                            "phenix_partial_evidence_json_path"
                        ]
                    )
                    bad_partial = json.loads(
                        partial_path.read_text(encoding="utf-8")
                    )
                    bad_partial["status"] = "failed_partial_unverified"
                    new_part_sha, _, _ = _write_json_with_digest(
                        partial_path, bad_partial
                    )
                    rec_doc = json.loads(rec_path.read_text(encoding="utf-8"))
                    rec_doc["phenix_partial_evidence_sha256"] = new_part_sha
                    new_rec_sha, _, _ = _write_json_with_digest(
                        rec_path, rec_doc
                    )
                    with self.assertRaisesRegex(
                        PhenixRetainedVerificationError,
                        "phenix_partial_evidence_json: partial checkpoint is not a clean completed_superseded_by_verified_payload",
                    ):
                        verify_retained_phenix_rfactor_evidence(
                            admitted_root,
                            subject_id="R4",
                            reconciled_manifest_path=rec_path,
                            reconciled_manifest_sha256=new_rec_sha,
                            repo_root=REPO_ROOT,
                        )
                finally:
                    _reset()

            # Confirm baseline envelope still verifies cleanly after all tamper subtests reset.
            final_check = verify_retained_phenix_rfactor_evidence(
                admitted_root,
                subject_id="R4",
                reconciled_manifest_path=rec_path,
                reconciled_manifest_sha256=rec_sha,
                repo_root=REPO_ROOT,
            )
            self.assertEqual(final_check["verification_status"], "verified")

    def test_verifier_invokes_real_pure_reconciliation_and_rejects_status_spoofing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp).resolve(strict=True)
            env = _create_synthetic_retained_phenix_envelope(
                tmp_root,
                subject_id="R4",
                run_name="r4_reconciliation_suite",
                write_completed_partial_checkpoint=False,
            )
            admitted_root: Path = env["admitted_root"]
            evidence_root: Path = env["evidence_root"]
            rec_path: Path = env["reconciled_manifest_path"]
            admitted_snapshot = _snapshot_tree_bytes(admitted_root)

            # 1. Nontrivial numerical/selection inconsistency in phenix_rfactors.json:
            # Perturb reported r_free (and gap) in phenix_rfactors.json while keeping the
            # actual_free reflection table unchanged, rehash phenix_rfactors.json in
            # bundle/success.json and phenix_reconciled_manifest.json, and keep
            # reconciled_manifest["reconciliation"]["reconciliation_status"] = "verified".
            rfactors_path = Path(
                env["reconciled_record"]["phenix_rfactors_json_path"]
            )
            with self.subTest(case="r_free_perturbation"):
                try:
                    rf_payload = json.loads(
                        rfactors_path.read_text(encoding="utf-8")
                    )
                    rf_payload["scales_and_rfactors"]["r_free"] = 0.21
                    rf_payload["scales_and_rfactors"]["r_free_r_work_gap"] = (
                        0.21 - rf_payload["scales_and_rfactors"]["r_work"]
                    )
                    _write_json_with_digest(rfactors_path, rf_payload)
                    _, new_rec_sha, _ = _rehash_cache_and_reconciled_manifest(
                        evidence_root
                    )
                    with self.assertRaisesRegex(
                        PhenixRetainedVerificationError,
                        "reconcile_phenix_rfactor_output: Replayed r_free .* disagrees with native fmodel\\.r_free\\(\\)",
                    ):
                        verify_retained_phenix_rfactor_evidence(
                            admitted_root,
                            subject_id="R4",
                            reconciled_manifest_path=rec_path,
                            reconciled_manifest_sha256=new_rec_sha,
                            repo_root=REPO_ROOT,
                        )
                finally:
                    _restore_tree_bytes(admitted_root, admitted_snapshot)

            # 2. Selection/HKL mismatch in phenix_rfactors.json:
            # Drop one HKL from final_effective while keeping actual_work + actual_free
            # unchanged and re-signing all artifact/manifest digests.
            with self.subTest(case="final_effective_hkl_drop"):
                try:
                    rf_payload = json.loads(
                        rfactors_path.read_text(encoding="utf-8")
                    )
                    rf_payload["final_effective"] = rf_payload[
                        "final_effective"
                    ][:3]
                    rf_payload["scales_and_rfactors"][
                        "final_effective_count"
                    ] = 3
                    _write_json_with_digest(rfactors_path, rf_payload)
                    _, new_rec_sha, _ = _rehash_cache_and_reconciled_manifest(
                        evidence_root
                    )
                    with self.assertRaisesRegex(
                        PhenixRetainedVerificationError,
                        "reconcile_phenix_rfactor_output: .*final_effective",
                    ):
                        verify_retained_phenix_rfactor_evidence(
                            admitted_root,
                            subject_id="R4",
                            reconciled_manifest_path=rec_path,
                            reconciled_manifest_sha256=new_rec_sha,
                            repo_root=REPO_ROOT,
                        )
                finally:
                    _restore_tree_bytes(admitted_root, admitted_snapshot)

            # 3. Runtime vendor-module provenance mismatch inside phenix_rfactors.json:
            # Change a vendor module sha256 inside runtime_environment.vendor_modules
            # while re-signing phenix_rfactors.json and manifests.
            with self.subTest(case="runtime_vendor_module_sha256_mismatch"):
                try:
                    rf_payload = json.loads(
                        rfactors_path.read_text(encoding="utf-8")
                    )
                    rf_payload["runtime_environment"]["vendor_modules"][
                        "vendor_mmtbx_f_model"
                    ]["sha256"] = "f" * 64
                    _write_json_with_digest(rfactors_path, rf_payload)
                    _, new_rec_sha, _ = _rehash_cache_and_reconciled_manifest(
                        evidence_root
                    )
                    with self.assertRaisesRegex(
                        PhenixRetainedVerificationError,
                        "reconcile_phenix_rfactor_output: .*vendor_mmtbx_f_model",
                    ):
                        verify_retained_phenix_rfactor_evidence(
                            admitted_root,
                            subject_id="R4",
                            reconciled_manifest_path=rec_path,
                            reconciled_manifest_sha256=new_rec_sha,
                            repo_root=REPO_ROOT,
                        )
                finally:
                    _restore_tree_bytes(admitted_root, admitted_snapshot)

            # 4. Stored reconciliation summary tampered in phenix_reconciled_manifest.json
            # while keeping reconciliation_status == "verified" and raw payload valid.
            with self.subTest(case="stored_reconciliation_summary_spoofing"):
                try:
                    rec_doc = json.loads(rec_path.read_text(encoding="utf-8"))
                    rec_doc["reconciliation"]["rfactors"]["r_free"] = 0.199
                    new_rec_sha, _, _ = _write_json_with_digest(
                        rec_path, rec_doc
                    )
                    with self.assertRaisesRegex(
                        PhenixRetainedVerificationError,
                        "phenix_reconciled_manifest\\.reconciliation: retained reconciliation summary disagrees with fresh full-precision reconciliation",
                    ):
                        verify_retained_phenix_rfactor_evidence(
                            admitted_root,
                            subject_id="R4",
                            reconciled_manifest_path=rec_path,
                            reconciled_manifest_sha256=new_rec_sha,
                            repo_root=REPO_ROOT,
                        )
                finally:
                    _restore_tree_bytes(admitted_root, admitted_snapshot)


def _create_synthetic_retained_refmac_capture(
    tmp_root: Path,
    *,
    subject_id: str = "R4",
    run_name: str = "refmac_capture_r4",
) -> dict[str, Any]:
    """Build a complete synthetic retained REFMAC capture using the accepted _FakeCcp4Fixture."""
    fake_repo = tmp_root / f"{run_name}_repo"
    fake_repo.mkdir(parents=True, exist_ok=True)
    fake_repo = fake_repo.resolve(strict=True)
    ccp4_fixture = test_onesar_refmac._FakeCcp4Fixture(
        tmp_root / f"{run_name}_ccp4_prefix"
    )
    evidence_root = fake_repo / "runs" / run_name / "evidence"

    def _runner(
        xyzin: Path,
        hklin: Path,
        xyzout: Path,
        hklout: Path,
        log_path: Path,
        keywords: str,
        *,
        cwd: Path,
        timeout: float,
        xml_output: Path,
        executable: Path,
        env: Mapping[str, str],
        ccp4: bool,
    ) -> subprocess.CompletedProcess[str]:
        _ = (keywords, cwd, timeout, env, ccp4)
        test_onesar_refmac.TestRefmacCollectorFirstSlice._write_capture_success_outputs(
            xyzin, hklin, xyzout, hklout, log_path
        )
        argv = [
            str(executable),
            "XYZIN",
            str(xyzin),
            "HKLIN",
            str(hklin),
            "XYZOUT",
            str(xyzout),
            "HKLOUT",
            str(hklout),
            "XMLOUT",
            str(xml_output),
        ]
        return subprocess.CompletedProcess(
            args=argv,
            returncode=0,
            stdout=test_onesar_refmac.SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG,
            stderr="",
        )

    with (
        mock.patch.dict(
            os.environ,
            {"PROTSTRUCT_CCP4_SETUP": str(ccp4_fixture.setup_script)},
            clear=False,
        ),
        mock.patch.object(toolchain, "CCP4_SETUP", ccp4_fixture.setup_script),
        mock.patch.object(
            toolchain,
            "ccp4_environment",
            return_value=dict(ccp4_fixture.sourced_env),
        ),
    ):
        capture_result = onesar_refmac.run_refmac_rfactor_operation(
            evidence_root=evidence_root,
            subject_id=subject_id,
            repo_root=fake_repo,
            archive_path=COMMITTED_ARCHIVE,
            require_no_protstruct_overrides=False,
            runner=_runner,
        )

    resolved_evidence_root = evidence_root.resolve(strict=True)
    return {
        "admitted_root": (fake_repo / "runs" / run_name).resolve(strict=True),
        "evidence_root": resolved_evidence_root,
        "fake_repo": fake_repo,
        "capture_result": capture_result,
        "manifest_ref": copy.deepcopy(capture_result["manifest_json"]),
        "manifest_path": Path(capture_result["manifest_json"]["path"]),
        "diagnostics_path": Path(capture_result["diagnostics_json"]["path"]),
        "hklout_audit_path": Path(capture_result["hklout_audit_json"]["path"]),
    }


def _create_synthetic_f1_fallback_refmac_capture(
    tmp_root: Path,
    *,
    subject_id: str = "R4",
    run_name: str = "refmac_f1_fallback_r4",
    evidence_root: Path | None = None,
    fake_repo: Path | None = None,
) -> dict[str, Any]:
    """Build a genuine producer-persisted F1 fallback REFMAC capture via onesar_refmac.run_refmac_rfactor_operation."""
    if fake_repo is None:
        fake_repo = tmp_root / f"{run_name}_repo"
        fake_repo.mkdir(parents=True, exist_ok=True)
    fake_repo = fake_repo.resolve(strict=True)
    ccp4_fixture = test_onesar_refmac._FakeCcp4Fixture(
        tmp_root / f"{run_name}_ccp4_prefix"
    )
    if evidence_root is None:
        evidence_root = fake_repo / "runs" / run_name / "evidence"
    refmac_dir = evidence_root / "refmac"
    d0_child_target = refmac_dir / "refmac_diagnostics.json"

    def _runner(
        xyzin: Path,
        hklin: Path,
        xyzout: Path,
        hklout: Path,
        log_path: Path,
        keywords: str,
        *,
        cwd: Path,
        timeout: float,
        xml_output: Path,
        executable: Path,
        env: Mapping[str, str],
        ccp4: bool,
    ) -> subprocess.CompletedProcess[str]:
        _ = (keywords, cwd, timeout, env, ccp4)
        test_onesar_refmac.TestRefmacCollectorFirstSlice._write_capture_success_outputs(
            xyzin, hklin, xyzout, hklout, log_path
        )
        argv = [
            str(executable),
            "XYZIN",
            str(xyzin),
            "HKLIN",
            str(hklin),
            "XYZOUT",
            str(xyzout),
            "HKLOUT",
            str(hklout),
            "XMLOUT",
            str(xml_output),
        ]
        return subprocess.CompletedProcess(
            args=argv,
            returncode=0,
            stdout=test_onesar_refmac.SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG,
            stderr="",
        )

    orig_atomic = onesar_refmac._atomic_write_new_json_file
    written_by_path: dict[str, dict[str, Any]] = {}

    def _wrapped_atomic_f1(
        payload: Any,
        target_path: Path,
        *,
        root: Path,
    ) -> dict[str, Any]:
        if target_path == d0_child_target and root == refmac_dir:
            raise PermissionError(
                errno.EACCES,
                "F1 injected late D0 child write failure",
                str(d0_child_target),
            )
        res = orig_atomic(payload, target_path, root=root)
        written_by_path[str(target_path)] = res
        if isinstance(res.get("path"), str):
            written_by_path[res["path"]] = res
        return res

    caught_err: onesar_refmac.RefmacCollectorError | None = None
    with (
        mock.patch.dict(
            os.environ,
            {"PROTSTRUCT_CCP4_SETUP": str(ccp4_fixture.setup_script)},
            clear=False,
        ),
        mock.patch.object(toolchain, "CCP4_SETUP", ccp4_fixture.setup_script),
        mock.patch.object(
            toolchain,
            "ccp4_environment",
            return_value=dict(ccp4_fixture.sourced_env),
        ),
        mock.patch.object(
            onesar_refmac,
            "_atomic_write_new_json_file",
            side_effect=_wrapped_atomic_f1,
        ),
    ):
        try:
            onesar_refmac.run_refmac_rfactor_operation(
                evidence_root=evidence_root,
                subject_id=subject_id,
                repo_root=fake_repo,
                archive_path=COMMITTED_ARCHIVE,
                require_no_protstruct_overrides=False,
                runner=_runner,
            )
        except onesar_refmac.RefmacCollectorError as exc:
            caught_err = exc

    if (
        caught_err is None
        or caught_err.manifest_path is None
        or caught_err.diagnostics_path is None
        or caught_err.manifest_payload is None
    ):
        raise AssertionError(
            f"Expected F1 RefmacCollectorError with persisted fallback pair, got {caught_err!r}"
        )

    resolved_evidence_root = evidence_root.resolve(strict=True)
    manifest_path = Path(caught_err.manifest_path).resolve(strict=True)
    diagnostics_path = Path(caught_err.diagnostics_path).resolve(strict=True)
    manifest_ref_f1 = copy.deepcopy(written_by_path[str(manifest_path)])
    return {
        "admitted_root": resolved_evidence_root.parent,
        "evidence_root": resolved_evidence_root,
        "fake_repo": fake_repo,
        "collector_error": caught_err,
        "manifest_ref": manifest_ref_f1,
        "manifest_path": manifest_path,
        "diagnostics_path": diagnostics_path,
        "manifest_payload": copy.deepcopy(caught_err.manifest_payload),
        "diagnostics_payload": copy.deepcopy(caught_err.diagnostics_payload),
    }


def _create_synthetic_verified_root_fallback_refmac_capture(
    tmp_root: Path,
    *,
    subject_id: str = "R4",
    run_name: str = "refmac_verified_root_fallback_r4",
    evidence_root: Path | None = None,
    fake_repo: Path | None = None,
) -> dict[str, Any]:
    """Build a genuine producer-persisted verified-root fallback REFMAC capture via onesar_refmac.run_refmac_rfactor_operation."""
    if fake_repo is None:
        fake_repo = tmp_root / f"{run_name}_repo"
        fake_repo.mkdir(parents=True, exist_ok=True)
    fake_repo = fake_repo.resolve(strict=True)
    ccp4_fixture = test_onesar_refmac._FakeCcp4Fixture(
        tmp_root / f"{run_name}_ccp4_prefix"
    )
    if evidence_root is None:
        evidence_root = fake_repo / "runs" / run_name / "evidence"
    refmac_dir = evidence_root / "refmac"
    parent_retention_dir = evidence_root / "refmac_parent_retention"

    def _runner(
        xyzin: Path,
        hklin: Path,
        xyzout: Path,
        hklout: Path,
        log_path: Path,
        keywords: str,
        *,
        cwd: Path,
        timeout: float,
        xml_output: Path,
        executable: Path,
        env: Mapping[str, str],
        ccp4: bool,
    ) -> subprocess.CompletedProcess[str]:
        _ = (keywords, cwd, timeout, env, ccp4)
        test_onesar_refmac.TestRefmacCollectorFirstSlice._write_capture_success_outputs(
            xyzin, hklin, xyzout, hklout, log_path
        )
        argv = [
            str(executable),
            "XYZIN",
            str(xyzin),
            "HKLIN",
            str(hklin),
            "XYZOUT",
            str(xyzout),
            "HKLOUT",
            str(hklout),
            "XMLOUT",
            str(xml_output),
        ]
        return subprocess.CompletedProcess(
            args=argv,
            returncode=0,
            stdout=test_onesar_refmac.SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG,
            stderr="",
        )

    orig_atomic = onesar_refmac._atomic_write_new_json_file
    written_by_path: dict[str, dict[str, Any]] = {}
    denied_writes: list[str] = []

    def _wrapped_atomic_root_fallback(
        payload: Any,
        target_path: Path,
        *,
        root: Path,
    ) -> dict[str, Any]:
        if target_path.name == "refmac_diagnostics.json" and root in (
            refmac_dir,
            parent_retention_dir,
            refmac_dir.resolve(strict=False),
            parent_retention_dir.resolve(strict=False),
        ):
            denied_writes.append(str(target_path))
            raise PermissionError(
                errno.EACCES,
                "Owned synthetic late diagnostics write denial",
                str(target_path),
            )
        res = orig_atomic(payload, target_path, root=root)
        written_by_path[str(target_path)] = res
        if isinstance(res.get("path"), str):
            written_by_path[res["path"]] = res
        return res

    caught_err: onesar_refmac.RefmacCollectorError | None = None
    with (
        mock.patch.dict(
            os.environ,
            {"PROTSTRUCT_CCP4_SETUP": str(ccp4_fixture.setup_script)},
            clear=False,
        ),
        mock.patch.object(toolchain, "CCP4_SETUP", ccp4_fixture.setup_script),
        mock.patch.object(
            toolchain,
            "ccp4_environment",
            return_value=dict(ccp4_fixture.sourced_env),
        ),
        mock.patch.object(
            onesar_refmac,
            "_atomic_write_new_json_file",
            side_effect=_wrapped_atomic_root_fallback,
        ),
    ):
        try:
            onesar_refmac.run_refmac_rfactor_operation(
                evidence_root=evidence_root,
                subject_id=subject_id,
                repo_root=fake_repo,
                archive_path=COMMITTED_ARCHIVE,
                require_no_protstruct_overrides=False,
                runner=_runner,
            )
        except onesar_refmac.RefmacCollectorError as exc:
            caught_err = exc

    if (
        caught_err is None
        or caught_err.manifest_path is None
        or caught_err.diagnostics_path is None
        or caught_err.manifest_payload is None
        or caught_err.diagnostics_payload is None
    ):
        raise AssertionError(
            f"Expected verified-root fallback RefmacCollectorError with persisted fallback pair, got {caught_err!r}"
        )

    resolved_evidence_root = evidence_root.resolve(strict=True)
    manifest_path = Path(caught_err.manifest_path).resolve(strict=True)
    diagnostics_path = Path(caught_err.diagnostics_path).resolve(strict=True)
    manifest_ref_rf = copy.deepcopy(written_by_path[str(manifest_path)])
    return {
        "admitted_root": resolved_evidence_root.parent,
        "evidence_root": resolved_evidence_root,
        "fake_repo": fake_repo,
        "collector_error": caught_err,
        "denied_writes": list(denied_writes),
        "manifest_ref": manifest_ref_rf,
        "manifest_path": manifest_path,
        "diagnostics_path": diagnostics_path,
        "actual_anchor_dir": manifest_path.parent,
        "manifest_payload": copy.deepcopy(caught_err.manifest_payload),
        "diagnostics_payload": copy.deepcopy(caught_err.diagnostics_payload),
    }


def _rehash_refmac_manifest_and_diagnostics(
    manifest_path: Path,
    diagnostics_path: Path,
    *,
    manifest_doc: dict[str, Any],
    diagnostics_doc: dict[str, Any],
    hklout_audit_path: Path | None = None,
    hklout_audit_doc: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Re-write and re-hash REFMAC audit, diagnostics, and manifest JSON files in dependency order."""
    if hklout_audit_path is not None and hklout_audit_doc is not None:
        hkl_sha, hkl_size, _ = _write_json_with_digest(
            hklout_audit_path, hklout_audit_doc
        )
        for doc in (diagnostics_doc, manifest_doc):
            if isinstance(doc.get("hklout_audit_json"), dict):
                doc["hklout_audit_json"]["path"] = str(hklout_audit_path)
                doc["hklout_audit_json"]["sha256"] = hkl_sha
                doc["hklout_audit_json"]["size_bytes"] = hkl_size
            if isinstance(doc.get("audits"), dict):
                doc["audits"]["hklout_mtz_audit"] = copy.deepcopy(hklout_audit_doc)

    diag_sha, diag_size, _ = _write_json_with_digest(
        diagnostics_path, diagnostics_doc
    )
    if isinstance(manifest_doc.get("diagnostics_json"), dict):
        manifest_doc["diagnostics_json"]["path"] = str(diagnostics_path)
        manifest_doc["diagnostics_json"]["sha256"] = diag_sha
        manifest_doc["diagnostics_json"]["size_bytes"] = diag_size
    if isinstance(manifest_doc.get("paths"), dict):
        manifest_doc["paths"]["diagnostics_json_path"] = str(diagnostics_path)
        manifest_doc["paths"]["manifest_json_path"] = str(manifest_path)

    man_sha, man_size, _ = _write_json_with_digest(manifest_path, manifest_doc)
    return {
        "path": str(manifest_path),
        "persisted": True,
        "sha256": man_sha,
        "size_bytes": man_size,
    }


class TestRefmacRetainedRefusalBoundary(unittest.TestCase):
    """Focused tests for Task 369 Part 1 retained REFMAC admission/refusal boundary."""

    def test_complete_synthetic_capture_refuses_three_unproven_native_premises_and_preserves_bytes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp).resolve(strict=True)
            env = _create_synthetic_retained_refmac_capture(
                tmp_root,
                subject_id="R4",
                run_name="r4_complete_capture",
            )
            admitted_root: Path = env["admitted_root"]
            manifest_ref: dict[str, Any] = env["manifest_ref"]
            admitted_snapshot = _snapshot_tree_bytes(admitted_root)

            with (
                mock.patch.object(
                    onesar_refmac,
                    "run_refmac_rfactor_operation",
                    side_effect=AssertionError(
                        "verify_retained_refmac_rfactor_evidence must not invoke run_refmac_rfactor_operation"
                    ),
                ),
                mock.patch.object(
                    toolchain,
                    "run_refmac",
                    side_effect=AssertionError(
                        "verify_retained_refmac_rfactor_evidence must not invoke toolchain.run_refmac"
                    ),
                ),
                mock.patch.object(
                    toolchain,
                    "ccp4_environment",
                    side_effect=AssertionError(
                        "verify_retained_refmac_rfactor_evidence must not invoke toolchain.ccp4_environment"
                    ),
                ),
                mock.patch.object(
                    subprocess,
                    "run",
                    side_effect=AssertionError(
                        "verify_retained_refmac_rfactor_evidence must not spawn subprocesses"
                    ),
                ),
            ):
                with self.assertRaises(RefmacScientificAdmissionRefusedError) as ctx:
                    verify_retained_refmac_rfactor_evidence(
                        admitted_root,
                        subject_id="R4",
                        manifest_reference=manifest_ref,
                        repo_root=REPO_ROOT,
                    )

            err = ctx.exception
            self.assertIsInstance(err, RefmacRetainedVerificationError)
            self.assertIsInstance(err, RetainedReferenceError)
            self.assertTrue(err.integrity_verified)
            self.assertFalse(err.scientific_proof_established)
            self.assertEqual(err.unsupported_proof_claims, ())
            self.assertEqual(
                set(err.unknown_native_premises.keys()),
                set(REFMAC_UNKNOWN_NATIVE_PREMISE_KEYS),
            )
            for premise_key in REFMAC_UNKNOWN_NATIVE_PREMISE_KEYS:
                prem_info = err.unknown_native_premises[premise_key]
                self.assertIs(prem_info["proven"], False)
                self.assertIsInstance(prem_info["unproven_reason"], str)
                self.assertTrue(prem_info["unproven_reason"].strip())
                self.assertIs(prem_info["manifest_claimed_value"], False)
                self.assertIs(prem_info["diagnostics_claimed_value"], False)
                self.assertIs(prem_info["hklout_audit_claimed_value"], False)

            refusal_rec = err.refusal_record
            self.assertEqual(refusal_rec["producer"], "refmac")
            self.assertEqual(
                refusal_rec["verification_status"],
                "diagnostic_captured_scientific_admission_refused",
            )
            self.assertEqual(refusal_rec["subject_id"], "R4")
            self.assertEqual(refusal_rec["manifest_path"], manifest_ref["path"])
            self.assertEqual(refusal_rec["manifest_sha256"], manifest_ref["sha256"])
            self.assertIs(
                refusal_rec["verification_boundaries"][
                    "refmac_retained_evidence_integrity_verified"
                ],
                True,
            )
            self.assertIs(
                refusal_rec["verification_boundaries"]["scientific_admission_proven"],
                False,
            )
            self.assertIs(
                refusal_rec["verification_boundaries"][
                    "canary_scientific_admission_established"
                ],
                False,
            )
            self.assertIs(
                refusal_rec["verification_boundaries"]["eval_or_qds_published"],
                False,
            )

            # Passing the full collector return mapping extracts manifest_json and reaches the same refusal.
            with self.assertRaises(RefmacScientificAdmissionRefusedError) as ctx_full:
                verify_retained_refmac_rfactor_evidence(
                    admitted_root,
                    subject_id="R4",
                    manifest_reference=env["capture_result"],
                    repo_root=REPO_ROOT,
                )
            self.assertTrue(ctx_full.exception.integrity_verified)
            self.assertFalse(ctx_full.exception.scientific_proof_established)

            # Verify no file under admitted_root was added, deleted, or modified.
            self.assertEqual(_snapshot_tree_bytes(admitted_root), admitted_snapshot)

    def test_flipping_summary_booleans_status_or_adding_proof_carrier_cannot_bypass_refusal(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp).resolve(strict=True)
            env = _create_synthetic_retained_refmac_capture(
                tmp_root,
                subject_id="R4",
                run_name="r4_forged_claims",
            )
            admitted_root: Path = env["admitted_root"]
            manifest_path: Path = env["manifest_path"]
            diagnostics_path: Path = env["diagnostics_path"]
            hklout_audit_path: Path = env["hklout_audit_path"]
            admitted_snapshot = _snapshot_tree_bytes(admitted_root)

            # 1. Flip all 3 native proof booleans, all 6 admission eligibility booleans,
            # gates 3/4/5, and status across hklout_audit, diagnostics, and manifest,
            # and re-sign all JSON files on disk.
            with self.subTest(case="all_booleans_and_status_flipped_to_proven"):
                try:
                    man_doc = json.loads(manifest_path.read_text(encoding="utf-8"))
                    diag_doc = json.loads(
                        diagnostics_path.read_text(encoding="utf-8")
                    )
                    hkl_doc = json.loads(
                        hklout_audit_path.read_text(encoding="utf-8")
                    )
                    for proof_key, reason_key in REFMAC_PROOF_TO_REASON_KEYS:
                        hkl_doc[proof_key] = True
                        hkl_doc[reason_key] = None
                        for doc in (man_doc, diag_doc):
                            doc[proof_key] = True
                            doc[reason_key] = None
                    for doc in (man_doc, diag_doc):
                        doc["status"] = "diagnostic_captured_all_gates_proven"
                        for elig_key in REFMAC_FALSE_ADMISSION_ELIGIBILITY_KEYS:
                            doc[elig_key] = True
                        for gate_key in (
                            "gate_3_effective_hkls_proven",
                            "gate_4_native_bin_membership_proven",
                            "gate_5_native_residual_reconstruction_proven",
                        ):
                            doc["preregistered_gates"][gate_key] = {
                                "proven": True,
                                "status": "proven",
                                "reason": None,
                            }

                    forged_ref = _rehash_refmac_manifest_and_diagnostics(
                        manifest_path,
                        diagnostics_path,
                        manifest_doc=man_doc,
                        diagnostics_doc=diag_doc,
                        hklout_audit_path=hklout_audit_path,
                        hklout_audit_doc=hkl_doc,
                    )
                    with self.assertRaises(
                        RefmacScientificAdmissionRefusedError
                    ) as ctx:
                        verify_retained_refmac_rfactor_evidence(
                            admitted_root,
                            subject_id="R4",
                            manifest_reference=forged_ref,
                            repo_root=REPO_ROOT,
                        )
                    err = ctx.exception
                    self.assertFalse(err.integrity_verified)
                    self.assertFalse(err.scientific_proof_established)
                    self.assertGreater(len(err.unsupported_proof_claims), 0)
                    self.assertEqual(
                        err.refusal_record["verification_status"],
                        "refused_unsupported_proof_claim",
                    )
                    self.assertEqual(
                        set(err.unknown_native_premises.keys()),
                        set(REFMAC_UNKNOWN_NATIVE_PREMISE_KEYS),
                    )
                    for premise_key in REFMAC_UNKNOWN_NATIVE_PREMISE_KEYS:
                        self.assertIs(
                            err.unknown_native_premises[premise_key]["proven"],
                            False,
                        )
                finally:
                    _restore_tree_bytes(admitted_root, admitted_snapshot)

            # 2. Inject an unsupported proof carrier key (e.g. "reconciliation" /
            # "native_proof_contract") into manifest_json and diagnostics_json.
            with self.subTest(case="unsupported_proof_carrier_key"):
                try:
                    man_doc = json.loads(manifest_path.read_text(encoding="utf-8"))
                    diag_doc = json.loads(
                        diagnostics_path.read_text(encoding="utf-8")
                    )
                    man_doc["reconciliation"] = {
                        "reconciliation_status": "verified",
                        "scientific_admission_proven": True,
                    }
                    diag_doc["native_proof_contract"] = {
                        "contract_version": 1,
                        "all_gates_proven": True,
                    }
                    forged_ref = _rehash_refmac_manifest_and_diagnostics(
                        manifest_path,
                        diagnostics_path,
                        manifest_doc=man_doc,
                        diagnostics_doc=diag_doc,
                    )
                    with self.assertRaises(
                        RefmacScientificAdmissionRefusedError
                    ) as ctx:
                        verify_retained_refmac_rfactor_evidence(
                            admitted_root,
                            subject_id="R4",
                            manifest_reference=forged_ref,
                            repo_root=REPO_ROOT,
                        )
                    err = ctx.exception
                    self.assertFalse(err.integrity_verified)
                    self.assertFalse(err.scientific_proof_established)
                    self.assertTrue(
                        any(
                            "reconciliation" in claim
                            for claim in err.unsupported_proof_claims
                        )
                    )
                    self.assertTrue(
                        any(
                            "native_proof_contract" in claim
                            for claim in err.unsupported_proof_claims
                        )
                    )
                finally:
                    _restore_tree_bytes(admitted_root, admitted_snapshot)

            self.assertEqual(_snapshot_tree_bytes(admitted_root), admitted_snapshot)

    def test_missing_or_tampered_required_evidence_and_identity_mismatches_refuse(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp).resolve(strict=True)
            env = _create_synthetic_retained_refmac_capture(
                tmp_root,
                subject_id="R4",
                run_name="r4_tamper_suite",
            )
            admitted_root: Path = env["admitted_root"]
            evidence_root: Path = env["evidence_root"]
            manifest_ref: dict[str, Any] = env["manifest_ref"]
            manifest_path: Path = env["manifest_path"]
            diagnostics_path: Path = env["diagnostics_path"]
            hklout_audit_path: Path = env["hklout_audit_path"]
            admitted_snapshot = _snapshot_tree_bytes(admitted_root)

            # 1. Wrong/mismatched subject_id ("start"), forbidden subject_id ("R7"), and unknown subject_id ("R99").
            with self.subTest(case="subject_mismatch_and_r7"):
                with self.assertRaisesRegex(
                    RefmacRetainedVerificationError,
                    "refmac_operation_manifest\\.subject_id: expected 'start', got 'R4'",
                ) as ctx_start:
                    verify_retained_refmac_rfactor_evidence(
                        admitted_root,
                        subject_id="start",
                        manifest_reference=manifest_ref,
                        repo_root=REPO_ROOT,
                    )
                self.assertNotIsInstance(
                    ctx_start.exception, RefmacScientificAdmissionRefusedError
                )
                with self.assertRaisesRegex(
                    RefmacRetainedVerificationError,
                    "subject_id: Subject 'R7' is excluded from the 1SAR trajectory rerun contract",
                ) as ctx_r7:
                    verify_retained_refmac_rfactor_evidence(
                        admitted_root,
                        subject_id="R7",
                        manifest_reference=manifest_ref,
                        repo_root=REPO_ROOT,
                    )
                self.assertNotIsInstance(
                    ctx_r7.exception, RefmacScientificAdmissionRefusedError
                )
                with self.assertRaisesRegex(
                    RefmacRetainedVerificationError,
                    "subject_id: Unknown 1SAR subject 'R99'",
                ) as ctx_r99:
                    verify_retained_refmac_rfactor_evidence(
                        admitted_root,
                        subject_id="R99",
                        manifest_reference=manifest_ref,
                        repo_root=REPO_ROOT,
                    )
                self.assertNotIsInstance(
                    ctx_r99.exception, RefmacScientificAdmissionRefusedError
                )

            # 2. Tampered linked required JSON artifact (hklout_audit_json modified on disk).
            with self.subTest(case="tampered_hklout_audit_json"):
                try:
                    hklout_audit_path.write_bytes(
                        hklout_audit_path.read_bytes() + b"\n"
                    )
                    with self.assertRaisesRegex(
                        RefmacRetainedVerificationError,
                        "refmac_operation_manifest\\.hklout_audit_json: (size_bytes|sha256) mismatch",
                    ) as ctx_hkl:
                        verify_retained_refmac_rfactor_evidence(
                            admitted_root,
                            subject_id="R4",
                            manifest_reference=manifest_ref,
                            repo_root=REPO_ROOT,
                        )
                    self.assertNotIsInstance(
                        ctx_hkl.exception, RefmacScientificAdmissionRefusedError
                    )
                finally:
                    _restore_tree_bytes(admitted_root, admitted_snapshot)

            # 3. Missing required raw output file (refmac_hklout.mtz removed from disk).
            with self.subTest(case="missing_raw_hklout_mtz"):
                try:
                    (evidence_root / "refmac" / "refmac_hklout.mtz").unlink()
                    with self.assertRaisesRegex(
                        RefmacRetainedVerificationError,
                        "raw_outputs\\.hklout: retained file does not exist on disk",
                    ) as ctx_rm:
                        verify_retained_refmac_rfactor_evidence(
                            admitted_root,
                            subject_id="R4",
                            manifest_reference=manifest_ref,
                            repo_root=REPO_ROOT,
                        )
                    self.assertNotIsInstance(
                        ctx_rm.exception, RefmacScientificAdmissionRefusedError
                    )
                finally:
                    _restore_tree_bytes(admitted_root, admitted_snapshot)

            # 4. Output-for-input substitution: invocation.xyzin_path pointed at refmac_xyzout.pdb.
            with self.subTest(case="output_substituted_for_input"):
                try:
                    man_doc = json.loads(manifest_path.read_text(encoding="utf-8"))
                    diag_doc = json.loads(
                        diagnostics_path.read_text(encoding="utf-8")
                    )
                    xyzout_str = str(
                        evidence_root / "refmac" / "refmac_xyzout.pdb"
                    )
                    man_doc["invocation"]["xyzin_path"] = xyzout_str
                    diag_doc["invocation"]["xyzin_path"] = xyzout_str
                    bad_ref = _rehash_refmac_manifest_and_diagnostics(
                        manifest_path,
                        diagnostics_path,
                        manifest_doc=man_doc,
                        diagnostics_doc=diag_doc,
                    )
                    with self.assertRaisesRegex(
                        RefmacRetainedVerificationError,
                        "outputs must never replace inputs",
                    ) as ctx_sub:
                        verify_retained_refmac_rfactor_evidence(
                            admitted_root,
                            subject_id="R4",
                            manifest_reference=bad_ref,
                            repo_root=REPO_ROOT,
                        )
                    self.assertNotIsInstance(
                        ctx_sub.exception, RefmacScientificAdmissionRefusedError
                    )
                finally:
                    _restore_tree_bytes(admitted_root, admitted_snapshot)

            self.assertEqual(_snapshot_tree_bytes(admitted_root), admitted_snapshot)

    def test_legitimate_fallback_reference_is_followed_without_canonical_path_guessing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp).resolve(strict=True)

            # 1. Genuine producer-persisted F1 fallback capture where D0 child write fails
            # and both diagnostics_json and manifest_json are persisted in refmac_parent_retention/.
            f1_env = _create_synthetic_f1_fallback_refmac_capture(
                tmp_root,
                subject_id="R4",
                run_name="r4_f1_real_fallback",
            )
            f1_admitted_root: Path = f1_env["admitted_root"]
            f1_evidence_root: Path = f1_env["evidence_root"]
            f1_manifest_ref: dict[str, Any] = f1_env["manifest_ref"]
            f1_manifest_path: Path = f1_env["manifest_path"]
            f1_diag_path: Path = f1_env["diagnostics_path"]
            f1_snapshot = _snapshot_tree_bytes(f1_admitted_root)

            with self.subTest(case="genuine_f1_producer_fallback_capture"):
                with self.assertRaises(
                    RefmacScientificAdmissionRefusedError
                ) as ctx:
                    verify_retained_refmac_rfactor_evidence(
                        f1_admitted_root,
                        subject_id="R4",
                        manifest_reference=f1_manifest_ref,
                        repo_root=REPO_ROOT,
                    )
                err = ctx.exception
                self.assertTrue(err.integrity_verified)
                self.assertFalse(err.scientific_proof_established)
                self.assertEqual(err.unsupported_proof_claims, ())
                self.assertEqual(
                    set(err.unknown_native_premises.keys()),
                    set(REFMAC_UNKNOWN_NATIVE_PREMISE_KEYS),
                )
                self.assertEqual(
                    err.refusal_record["manifest_status"],
                    "failed",
                )
                self.assertEqual(
                    err.refusal_record["manifest_failed_stage"],
                    "persist_collector_artifacts_in_refmac_dir",
                )
                self.assertIs(
                    err.refusal_record["fallback_persistence_used"],
                    True,
                )
                self.assertIs(
                    err.refusal_record["verification_boundaries"][
                        "model_preservation_proven"
                    ],
                    False,
                )
                self.assertIs(
                    err.refusal_record["verification_boundaries"][
                        "xyzout_audit_model_preservation_proven"
                    ],
                    True,
                )
                self.assertEqual(
                    err.verified_references["refmac_operation_manifest"]["path"],
                    str(f1_manifest_path),
                )
                self.assertEqual(
                    err.verified_references["diagnostics_json"]["path"],
                    str(f1_diag_path),
                )
                self.assertTrue(
                    err.verified_references["diagnostics_json"]["is_fallback"]
                )
                for staged_key in (
                    "original_model_pdb",
                    "original_data_mtz",
                    "projected_observations_mtz",
                    "input_hkl_ledger_json",
                ):
                    self.assertIn(
                        staged_key,
                        err.verified_references["staged_files"],
                    )
                for raw_key in ("log", "xyzout", "hklout"):
                    self.assertIsNotNone(
                        err.verified_references["raw_outputs"][raw_key]
                    )
                self.assertIsNone(
                    err.verified_references["raw_outputs"]["xmlout"]
                )
                self.assertIsNotNone(
                    err.verified_references["xmlout_audit_json"]
                )
                self.assertIs(
                    f1_env["manifest_payload"]["raw_outputs"]["xmlout"][
                        "exists"
                    ],
                    False,
                )
                self.assertIsNone(
                    f1_env["manifest_payload"]["raw_outputs"]["xmlout"][
                        "sha256"
                    ]
                )
                self.assertIsNone(
                    f1_env["manifest_payload"]["raw_outputs"]["xmlout"][
                        "size_bytes"
                    ]
                )
                self.assertIs(
                    f1_env["manifest_payload"]["audits"]["xmlout_audit"][
                        "valid"
                    ],
                    True,
                )
                self.assertIs(
                    f1_env["manifest_payload"]["audits"]["xmlout_audit"][
                        "present"
                    ],
                    False,
                )
                self.assertEqual(
                    f1_env["manifest_payload"]["audits"]["xmlout_audit"][
                        "status"
                    ],
                    "absent",
                )
                self.assertEqual(
                    _snapshot_tree_bytes(f1_admitted_root), f1_snapshot
                )

            # 2. Tampering with a raw output on the genuine F1 fallback capture raises
            # RefmacRetainedVerificationError (not RefmacScientificAdmissionRefusedError).
            with self.subTest(case="tampered_raw_output_on_f1_fallback_capture"):
                try:
                    raw_hklout = (
                        f1_evidence_root / "refmac" / "refmac_hklout.mtz"
                    )
                    raw_hklout.write_bytes(raw_hklout.read_bytes() + b"\x00")
                    with self.assertRaisesRegex(
                        RefmacRetainedVerificationError,
                        "raw_outputs\\.hklout: (size_bytes|sha256) mismatch",
                    ) as ctx_tamp:
                        verify_retained_refmac_rfactor_evidence(
                            f1_admitted_root,
                            subject_id="R4",
                            manifest_reference=f1_manifest_ref,
                            repo_root=REPO_ROOT,
                        )
                    self.assertNotIsInstance(
                        ctx_tamp.exception, RefmacScientificAdmissionRefusedError
                    )
                finally:
                    _restore_tree_bytes(f1_admitted_root, f1_snapshot)

            # 3. Relocating a clean status="diagnostic_captured_gates_unproven" (failures=[])
            # manifest into refmac_parent_retention/ with fallback metadata is rejected as an
            # incoherent fallback payload (RefmacRetainedVerificationError).
            env = _create_synthetic_retained_refmac_capture(
                tmp_root,
                subject_id="R4",
                run_name="r4_relocated_clean_fallback",
            )
            admitted_root: Path = env["admitted_root"]
            evidence_root: Path = env["evidence_root"]
            canonical_manifest_path: Path = env["manifest_path"]
            canonical_diag_path: Path = env["diagnostics_path"]
            admitted_snapshot = _snapshot_tree_bytes(admitted_root)

            with self.subTest(case="relocated_clean_manifest_at_fallback_path_rejected"):
                try:
                    man_doc = json.loads(
                        canonical_manifest_path.read_text(encoding="utf-8")
                    )
                    diag_doc = json.loads(
                        canonical_diag_path.read_text(encoding="utf-8")
                    )
                    parent_retention_dir = (
                        evidence_root / "refmac_parent_retention"
                    )
                    fallback_diag_path = (
                        parent_retention_dir
                        / "refmac_diagnostics__child_fallback.json"
                    )
                    fallback_manifest_path = (
                        parent_retention_dir
                        / "refmac_operation_manifest__child_fallback.json"
                    )

                    _write_file_with_digest(
                        canonical_manifest_path, b"{corrupt canonical manifest\n"
                    )
                    _write_file_with_digest(
                        canonical_diag_path, b"{corrupt canonical diagnostics\n"
                    )

                    diag_sha, diag_size, _ = _write_json_with_digest(
                        fallback_diag_path, diag_doc
                    )
                    man_doc["diagnostics_json"] = {
                        "path": str(fallback_diag_path),
                        "persisted": True,
                        "sha256": diag_sha,
                        "size_bytes": diag_size,
                        "fallback_for_unwritable_or_damaged_child_dir": True,
                        "intended_child_dir_path": str(canonical_diag_path),
                        "parent_retention_dir": str(parent_retention_dir),
                        "actual_retention_anchor_dir": str(parent_retention_dir),
                        "actual_retention_anchor_kind": "parent_retention_dir",
                    }
                    man_doc["paths"]["diagnostics_json_path"] = str(
                        fallback_diag_path
                    )
                    man_doc["paths"]["manifest_json_path"] = str(
                        fallback_manifest_path
                    )
                    man_sha, man_size, _ = _write_json_with_digest(
                        fallback_manifest_path, man_doc
                    )
                    relocated_clean_ref = {
                        "path": str(fallback_manifest_path),
                        "persisted": True,
                        "sha256": man_sha,
                        "size_bytes": man_size,
                        "fallback_for_unwritable_or_damaged_child_dir": True,
                        "intended_child_dir_path": str(canonical_manifest_path),
                        "parent_retention_dir": str(parent_retention_dir),
                        "actual_retention_anchor_dir": str(parent_retention_dir),
                        "actual_retention_anchor_kind": "parent_retention_dir",
                    }

                    with self.assertRaisesRegex(
                        RefmacRetainedVerificationError,
                        "relocated clean payload at fallback path or with fallback metadata is not permitted without producer fallback failure state",
                    ) as ctx_reloc:
                        verify_retained_refmac_rfactor_evidence(
                            admitted_root,
                            subject_id="R4",
                            manifest_reference=relocated_clean_ref,
                            repo_root=REPO_ROOT,
                        )
                    self.assertNotIsInstance(
                        ctx_reloc.exception,
                        RefmacScientificAdmissionRefusedError,
                    )
                finally:
                    _restore_tree_bytes(admitted_root, admitted_snapshot)

            # 4. Genuine verified-root fallback capture (#1063): late D0 write fails in both
            # refmac_dir and refmac_parent_retention, and the real producer persists the complete
            # final pair in refmac_parent_retention.verified_root_fallback.<pid>/.
            rf_env = _create_synthetic_verified_root_fallback_refmac_capture(
                tmp_root,
                subject_id="R4",
                run_name="r4_verified_root_fallback",
            )
            rf_admitted_root: Path = rf_env["admitted_root"]
            rf_evidence_root: Path = rf_env["evidence_root"]
            rf_manifest_ref: dict[str, Any] = rf_env["manifest_ref"]
            rf_manifest_path: Path = rf_env["manifest_path"]
            rf_diag_path: Path = rf_env["diagnostics_path"]
            rf_anchor_dir: Path = rf_env["actual_anchor_dir"]
            rf_snapshot = _snapshot_tree_bytes(rf_admitted_root)

            self.assertEqual(
                rf_env["denied_writes"],
                [
                    str(rf_evidence_root / "refmac" / "refmac_diagnostics.json"),
                    str(
                        rf_evidence_root
                        / "refmac_parent_retention"
                        / "refmac_diagnostics.json"
                    ),
                ],
            )
            self.assertIs(
                rf_env["collector_error"].publication_pair_complete, True
            )
            self.assertIsNone(
                rf_env["collector_error"].publication_terminal_failure
            )
            self.assertTrue(
                rf_anchor_dir.name.startswith(
                    "refmac_parent_retention.verified_root_fallback."
                )
            )

            real_resolve_anchor = (
                onesar_records._resolve_and_validate_refmac_actual_anchor
            )
            real_classify_fb = onesar_records._classify_refmac_fallback_failures
            anchor_invocations: list[str | None] = []
            anchor_calls: list[Path | None] = []
            classify_calls: list[tuple[bool, bool, bool]] = []

            def _spy_resolve_anchor(*args: Any, **kwargs: Any) -> Path | None:
                doc_arg = args[0] if args else kwargs.get("manifest_doc", {})
                anchor_invocations.append(
                    doc_arg.get("actual_parent_retention_anchor_kind")
                    if isinstance(doc_arg, Mapping)
                    else None
                )
                res = real_resolve_anchor(*args, **kwargs)
                anchor_calls.append(res)
                return res

            def _spy_classify_fb(
                *args: Any, **kwargs: Any
            ) -> tuple[bool, bool, bool]:
                res = real_classify_fb(*args, **kwargs)
                classify_calls.append(res)
                return res

            with self.subTest(case="genuine_verified_root_fallback_producer_capture"):
                anchor_calls.clear()
                classify_calls.clear()
                with (
                    mock.patch.object(
                        onesar_records,
                        "_resolve_and_validate_refmac_actual_anchor",
                        side_effect=_spy_resolve_anchor,
                    ),
                    mock.patch.object(
                        onesar_records,
                        "_classify_refmac_fallback_failures",
                        side_effect=_spy_classify_fb,
                    ),
                    self.assertRaises(
                        RefmacScientificAdmissionRefusedError
                    ) as ctx_rf,
                ):
                    verify_retained_refmac_rfactor_evidence(
                        rf_admitted_root,
                        subject_id="R4",
                        manifest_reference=rf_manifest_ref,
                        repo_root=REPO_ROOT,
                    )
                self.assertEqual(anchor_calls, [rf_anchor_dir])
                self.assertEqual(classify_calls, [(True, True, False)])
                rf_err = ctx_rf.exception
                self.assertTrue(rf_err.integrity_verified)
                self.assertFalse(rf_err.scientific_proof_established)
                self.assertEqual(rf_err.unsupported_proof_claims, ())
                self.assertEqual(
                    set(rf_err.unknown_native_premises.keys()),
                    set(REFMAC_UNKNOWN_NATIVE_PREMISE_KEYS),
                )
                for premise_key in REFMAC_UNKNOWN_NATIVE_PREMISE_KEYS:
                    prem_info = rf_err.unknown_native_premises[premise_key]
                    self.assertIs(prem_info["proven"], False)
                    self.assertTrue(prem_info["unproven_reason"].strip())
                self.assertEqual(
                    rf_err.refusal_record["manifest_status"],
                    "failed",
                )
                self.assertEqual(
                    rf_err.refusal_record["manifest_failed_stage"],
                    "verify_parent_retention_directory",
                )
                self.assertEqual(
                    [
                        item["failed_stage"]
                        for item in rf_err.refusal_record["manifest_failures"]
                    ],
                    [
                        "verify_parent_retention_directory",
                        "persist_collector_artifacts_in_refmac_dir",
                    ],
                )
                self.assertIs(
                    rf_err.refusal_record["fallback_persistence_used"],
                    True,
                )
                self.assertEqual(
                    rf_err.refusal_record[
                        "actual_parent_retention_anchor_kind"
                    ],
                    "verified_evidence_root_exclusive_dir",
                )
                self.assertEqual(
                    rf_err.refusal_record["actual_parent_retention_anchor_dir"],
                    str(rf_anchor_dir),
                )
                self.assertIs(
                    rf_err.refusal_record["verification_boundaries"][
                        "model_preservation_proven"
                    ],
                    False,
                )
                self.assertIs(
                    rf_err.refusal_record["verification_boundaries"][
                        "xyzout_audit_model_preservation_proven"
                    ],
                    True,
                )
                self.assertEqual(
                    rf_err.verified_references["refmac_operation_manifest"][
                        "path"
                    ],
                    str(rf_manifest_path),
                )
                self.assertTrue(
                    rf_err.verified_references["refmac_operation_manifest"][
                        "is_fallback"
                    ]
                )
                self.assertEqual(
                    rf_err.verified_references["diagnostics_json"]["path"],
                    str(rf_diag_path),
                )
                self.assertTrue(
                    rf_err.verified_references["diagnostics_json"][
                        "is_fallback"
                    ]
                )
                for raw_key in ("log", "xyzout", "hklout"):
                    self.assertIsNotNone(
                        rf_err.verified_references["raw_outputs"][raw_key]
                    )
                self.assertIsNone(
                    rf_err.verified_references["raw_outputs"]["xmlout"]
                )
                self.assertEqual(
                    _snapshot_tree_bytes(rf_admitted_root), rf_snapshot
                )

            # 5. Contradictory or missing actual anchor on verified-root fallback capture is refused.
            with self.subTest(
                case="verified_root_fallback_contradictory_or_missing_anchor_rejected"
            ):
                try:
                    man_doc = json.loads(
                        rf_manifest_path.read_text(encoding="utf-8")
                    )
                    diag_doc = json.loads(
                        rf_diag_path.read_text(encoding="utf-8")
                    )
                    man_doc["actual_parent_retention_anchor_kind"] = (
                        "parent_retention_dir"
                    )
                    diag_doc["actual_parent_retention_anchor_kind"] = (
                        "parent_retention_dir"
                    )
                    bad_anchor_ref = _rehash_refmac_manifest_and_diagnostics(
                        rf_manifest_path,
                        rf_diag_path,
                        manifest_doc=man_doc,
                        diagnostics_doc=diag_doc,
                    )
                    anchor_invocations.clear()
                    anchor_calls.clear()
                    with (
                        mock.patch.object(
                            onesar_records,
                            "_resolve_and_validate_refmac_actual_anchor",
                            side_effect=_spy_resolve_anchor,
                        ),
                        self.assertRaisesRegex(
                            RefmacRetainedVerificationError,
                            "actual_parent_retention_anchor_dir: expected .*refmac_parent_retention",
                        ) as ctx_bad_kind,
                    ):
                        verify_retained_refmac_rfactor_evidence(
                            rf_admitted_root,
                            subject_id="R4",
                            manifest_reference=bad_anchor_ref,
                            repo_root=REPO_ROOT,
                        )
                    self.assertNotIsInstance(
                        ctx_bad_kind.exception,
                        RefmacScientificAdmissionRefusedError,
                    )
                    self.assertEqual(
                        anchor_invocations, ["parent_retention_dir"]
                    )
                    self.assertEqual(anchor_calls, [])
                finally:
                    _restore_tree_bytes(rf_admitted_root, rf_snapshot)

                try:
                    man_doc = json.loads(
                        rf_manifest_path.read_text(encoding="utf-8")
                    )
                    diag_doc = json.loads(
                        rf_diag_path.read_text(encoding="utf-8")
                    )
                    man_doc["parent_retention_fallback_anchor"][
                        "evidence_root_verified"
                    ] = False
                    diag_doc["parent_retention_fallback_anchor"][
                        "evidence_root_verified"
                    ] = False
                    unverified_anchor_ref = (
                        _rehash_refmac_manifest_and_diagnostics(
                            rf_manifest_path,
                            rf_diag_path,
                            manifest_doc=man_doc,
                            diagnostics_doc=diag_doc,
                        )
                    )
                    classify_calls.clear()
                    with (
                        mock.patch.object(
                            onesar_records,
                            "_classify_refmac_fallback_failures",
                            side_effect=_spy_classify_fb,
                        ),
                        self.assertRaisesRegex(
                            RefmacRetainedVerificationError,
                            "collector reported failure\\(s\\) at failed_stage='verify_parent_retention_directory'",
                        ) as ctx_unver,
                    ):
                        verify_retained_refmac_rfactor_evidence(
                            rf_admitted_root,
                            subject_id="R4",
                            manifest_reference=unverified_anchor_ref,
                            repo_root=REPO_ROOT,
                        )
                    self.assertNotIsInstance(
                        ctx_unver.exception,
                        RefmacScientificAdmissionRefusedError,
                    )
                    self.assertEqual(classify_calls, [(False, False, False)])
                finally:
                    _restore_tree_bytes(rf_admitted_root, rf_snapshot)

                try:
                    man_doc = json.loads(
                        rf_manifest_path.read_text(encoding="utf-8")
                    )
                    diag_doc = json.loads(
                        rf_diag_path.read_text(encoding="utf-8")
                    )
                    self.assertEqual(
                        man_doc["actual_parent_retention_anchor_kind"],
                        "verified_evidence_root_exclusive_dir",
                    )
                    self.assertEqual(
                        diag_doc["actual_parent_retention_anchor_kind"],
                        "verified_evidence_root_exclusive_dir",
                    )
                    man_doc["actual_parent_retention_anchor_dir"] = None
                    diag_doc["actual_parent_retention_anchor_dir"] = None
                    missing_anchor_ref = (
                        _rehash_refmac_manifest_and_diagnostics(
                            rf_manifest_path,
                            rf_diag_path,
                            manifest_doc=man_doc,
                            diagnostics_doc=diag_doc,
                        )
                    )
                    anchor_invocations.clear()
                    anchor_calls.clear()
                    with (
                        mock.patch.object(
                            onesar_records,
                            "_resolve_and_validate_refmac_actual_anchor",
                            side_effect=_spy_resolve_anchor,
                        ),
                        self.assertRaisesRegex(
                            RefmacRetainedVerificationError,
                            "refmac_operation_manifest\\.actual_parent_retention_anchor_kind: expected None when actual_parent_retention_anchor_dir is None, got 'verified_evidence_root_exclusive_dir'",
                        ) as ctx_missing_anchor,
                    ):
                        verify_retained_refmac_rfactor_evidence(
                            rf_admitted_root,
                            subject_id="R4",
                            manifest_reference=missing_anchor_ref,
                            repo_root=REPO_ROOT,
                        )
                    self.assertNotIsInstance(
                        ctx_missing_anchor.exception,
                        RefmacScientificAdmissionRefusedError,
                    )
                    self.assertEqual(
                        anchor_invocations,
                        ["verified_evidence_root_exclusive_dir"],
                    )
                    self.assertEqual(anchor_calls, [])
                finally:
                    _restore_tree_bytes(rf_admitted_root, rf_snapshot)

                with self.assertRaises(RefmacScientificAdmissionRefusedError):
                    verify_retained_refmac_rfactor_evidence(
                        rf_admitted_root,
                        subject_id="R4",
                        manifest_reference=rf_manifest_ref,
                        repo_root=REPO_ROOT,
                    )
                self.assertEqual(
                    _snapshot_tree_bytes(rf_admitted_root), rf_snapshot
                )

            # 6. Incomplete or unpersisted publication pair on verified-root fallback capture is refused.
            with self.subTest(
                case="verified_root_fallback_incomplete_publication_pair_rejected"
            ):
                with self.assertRaisesRegex(
                    RefmacRetainedVerificationError,
                    "publication_pair_complete",
                ) as ctx_inc_env:
                    verify_retained_refmac_rfactor_evidence(
                        rf_admitted_root,
                        subject_id="R4",
                        manifest_reference={
                            "schema_version": 1,
                            "collector_stage": onesar_refmac.COLLECTOR_STAGE,
                            "publication_pair_complete": False,
                            "publication_terminal_failure": {
                                "stage": "persist_manifest_m0",
                                "reason": "M0 failed after D0 was saved in verified-root fallback",
                            },
                            "manifest_json": copy.deepcopy(rf_manifest_ref),
                        },
                        repo_root=REPO_ROOT,
                    )
                self.assertNotIsInstance(
                    ctx_inc_env.exception,
                    RefmacScientificAdmissionRefusedError,
                )

                try:
                    man_doc = json.loads(
                        rf_manifest_path.read_text(encoding="utf-8")
                    )
                    man_doc["diagnostics_json"]["persisted"] = False
                    man_sha, man_size, _ = _write_json_with_digest(
                        rf_manifest_path, man_doc
                    )
                    unpersisted_diag_ref = dict(rf_manifest_ref)
                    unpersisted_diag_ref["sha256"] = man_sha
                    unpersisted_diag_ref["size_bytes"] = man_size
                    with self.assertRaisesRegex(
                        RefmacRetainedVerificationError,
                        "refmac_operation_manifest\\.diagnostics_json: refusing payload-only or unpersisted artifact reference",
                    ) as ctx_inc_diag:
                        verify_retained_refmac_rfactor_evidence(
                            rf_admitted_root,
                            subject_id="R4",
                            manifest_reference=unpersisted_diag_ref,
                            repo_root=REPO_ROOT,
                        )
                    self.assertNotIsInstance(
                        ctx_inc_diag.exception,
                        RefmacScientificAdmissionRefusedError,
                    )
                finally:
                    _restore_tree_bytes(rf_admitted_root, rf_snapshot)

                for (
                    pub_case_label,
                    target_member,
                    field_name,
                    field_value,
                    expected_err_re,
                ) in (
                    (
                        "manifest_pair_incomplete",
                        "manifest",
                        "publication_pair_complete",
                        False,
                        "refmac_operation_manifest: refusing incomplete publication pair \\(publication_pair_complete=False\\)",
                    ),
                    (
                        "manifest_terminal_failure",
                        "manifest",
                        "publication_terminal_failure",
                        {
                            "stage": "persist_manifest_m0",
                            "reason": "M0 failed after D0 was saved in verified-root fallback",
                        },
                        "refmac_operation_manifest: refusing manifest with publication_terminal_failure=",
                    ),
                    (
                        "diagnostics_pair_incomplete",
                        "diagnostics",
                        "publication_pair_complete",
                        False,
                        "refmac_diagnostics: refusing incomplete publication pair \\(publication_pair_complete=False\\)",
                    ),
                    (
                        "diagnostics_terminal_failure",
                        "diagnostics",
                        "publication_terminal_failure",
                        {
                            "stage": "persist_diagnostics_d0",
                            "reason": "D0 failed before M0 in verified-root fallback",
                        },
                        "refmac_diagnostics: refusing diagnostics with publication_terminal_failure=",
                    ),
                    (
                        "manifest_terminal_failure_omitted",
                        "manifest",
                        "publication_terminal_failure",
                        "__delete_field__",
                        "refmac_operation_manifest: missing required top-level key\\(s\\): \\['publication_terminal_failure'\\]",
                    ),
                    (
                        "diagnostics_terminal_failure_omitted",
                        "diagnostics",
                        "publication_terminal_failure",
                        "__delete_field__",
                        "refmac_diagnostics: missing required top-level key\\(s\\): \\['publication_terminal_failure'\\]",
                    ),
                ):
                    with self.subTest(
                        publication_member_case=pub_case_label
                    ):
                        try:
                            man_doc = json.loads(
                                rf_manifest_path.read_text(encoding="utf-8")
                            )
                            diag_doc = json.loads(
                                rf_diag_path.read_text(encoding="utf-8")
                            )
                            target_doc = (
                                man_doc
                                if target_member == "manifest"
                                else diag_doc
                            )
                            if field_value == "__delete_field__":
                                del target_doc[field_name]
                            else:
                                target_doc[field_name] = field_value
                            mut_ref = _rehash_refmac_manifest_and_diagnostics(
                                rf_manifest_path,
                                rf_diag_path,
                                manifest_doc=man_doc,
                                diagnostics_doc=diag_doc,
                            )
                            with self.assertRaisesRegex(
                                RefmacRetainedVerificationError,
                                expected_err_re,
                            ) as ctx_pub_member:
                                verify_retained_refmac_rfactor_evidence(
                                    rf_admitted_root,
                                    subject_id="R4",
                                    manifest_reference=mut_ref,
                                    repo_root=REPO_ROOT,
                                )
                            self.assertNotIsInstance(
                                ctx_pub_member.exception,
                                RefmacScientificAdmissionRefusedError,
                            )
                        finally:
                            _restore_tree_bytes(rf_admitted_root, rf_snapshot)

                with self.assertRaises(RefmacScientificAdmissionRefusedError):
                    verify_retained_refmac_rfactor_evidence(
                        rf_admitted_root,
                        subject_id="R4",
                        manifest_reference=rf_manifest_ref,
                        repo_root=REPO_ROOT,
                    )
                self.assertEqual(
                    _snapshot_tree_bytes(rf_admitted_root), rf_snapshot
                )

    def test_payload_only_and_unpersisted_records_refuse_as_diagnostic_only(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            admitted_root = Path(tmp).resolve(strict=True) / "attempt_unpersisted"
            admitted_root.mkdir(parents=True, exist_ok=True)
            admitted_snapshot = _snapshot_tree_bytes(admitted_root)

            # 1. Explicit persisted=False reference dict.
            with self.subTest(case="persisted_false_reference"):
                with self.assertRaisesRegex(
                    RefmacRetainedVerificationError,
                    "refusing payload-only or unpersisted REFMAC artifact reference",
                ) as ctx1:
                    verify_retained_refmac_rfactor_evidence(
                        admitted_root,
                        subject_id="R4",
                        manifest_reference={
                            "path": None,
                            "persisted": False,
                            "sha256": None,
                            "size_bytes": None,
                            "unpersisted_reason": "No verified retention anchor available",
                        },
                        repo_root=REPO_ROOT,
                    )
                self.assertNotIsInstance(
                    ctx1.exception, RefmacScientificAdmissionRefusedError
                )

            # 2. Collector payload with manifest_json=None or nested persisted=False.
            with self.subTest(case="collector_payload_manifest_json_unpersisted"):
                with self.assertRaisesRegex(
                    RefmacRetainedVerificationError,
                    "refusing payload-only or unpersisted REFMAC",
                ) as ctx2:
                    verify_retained_refmac_rfactor_evidence(
                        admitted_root,
                        subject_id="R4",
                        manifest_reference={
                            "schema_version": 1,
                            "collector_stage": onesar_refmac.COLLECTOR_STAGE,
                            "publication_pair_complete": True,
                            "publication_terminal_failure": None,
                            "manifest_json": {
                                "path": None,
                                "persisted": False,
                                "sha256": None,
                                "unpersisted_reason": "child and parent dirs unavailable",
                            },
                        },
                        repo_root=REPO_ROOT,
                    )
                self.assertNotIsInstance(
                    ctx2.exception, RefmacScientificAdmissionRefusedError
                )

            # 3. In-memory manifest_payload dict without manifest_json or persisted path/sha256.
            with self.subTest(case="raw_in_memory_manifest_payload"):
                with self.assertRaisesRegex(
                    RefmacRetainedVerificationError,
                    "refusing payload-only in-memory REFMAC manifest dictionary without persisted file reference",
                ) as ctx3:
                    verify_retained_refmac_rfactor_evidence(
                        admitted_root,
                        subject_id="R4",
                        manifest_reference={
                            "schema_version": 1,
                            "collector_stage": onesar_refmac.COLLECTOR_STAGE,
                            "status": "diagnostic_captured_gates_unproven",
                            "raw_outputs": {},
                            "operation_checks": {"collector_succeeded": True},
                        },
                        repo_root=REPO_ROOT,
                    )
                self.assertNotIsInstance(
                    ctx3.exception, RefmacScientificAdmissionRefusedError
                )

            # 4. RefmacCollectorError exception object passed directly.
            with self.subTest(case="collector_exception_object"):
                collector_err = onesar_refmac.RefmacCollectorError(
                    "synthetic collector failure",
                    failed_stage="refmac_returncode",
                    diagnostics_payload={"status": "failed"},
                    manifest_payload={"status": "failed", "manifest_json": None},
                )
                with self.assertRaisesRegex(
                    RefmacRetainedVerificationError,
                    "refusing collector exception RefmacCollectorError at retained reference boundary",
                ) as ctx4:
                    verify_retained_refmac_rfactor_evidence(
                        admitted_root,
                        subject_id="R4",
                        manifest_reference=collector_err,
                        repo_root=REPO_ROOT,
                    )
                self.assertNotIsInstance(
                    ctx4.exception, RefmacScientificAdmissionRefusedError
                )

            self.assertEqual(_snapshot_tree_bytes(admitted_root), admitted_snapshot)


def _create_synthetic_common_parent_fixture(
    tmp_root: Path,
    *,
    subject_id: str = "R4",
    started_at_utc: str = "2026-11-06T23:58:10+00:00",
    finished_at_utc: str = "2026-11-07T00:03:25+00:00",
    run_date: str = "2026-11-06",
) -> dict[str, Any]:
    """Build a small, clearly synthetic common-parent fixture for Task 369 Part 2 tests."""
    fake_repo = tmp_root / f"parent_{subject_id}_repo"
    fake_repo.mkdir(parents=True, exist_ok=True)
    fake_repo = fake_repo.resolve(strict=True)
    parent_root = fake_repo / "runs" / f"parent_{subject_id}"
    phenix_root = parent_root / "phenix_child"
    refmac_root = parent_root / "refmac_child"

    phx_staged = onesar_rerun.stage_subject_inputs(
        phenix_root,
        subject_id=subject_id,
        repo_root=fake_repo,
        archive_path=COMMITTED_ARCHIVE,
    )
    rm_staged = onesar_rerun.stage_subject_inputs(
        refmac_root,
        subject_id=subject_id,
        repo_root=fake_repo,
        archive_path=COMMITTED_ARCHIVE,
    )
    parent_root = parent_root.resolve(strict=True)
    phenix_root = phenix_root.resolve(strict=True)
    refmac_root = refmac_root.resolve(strict=True)

    phx_dir = phenix_root / "phenix"
    phx_bundle_dir = phx_dir / "cache" / "bundle"
    phx_cache_manifest_path = phx_bundle_dir / "success.json"
    phx_cache_sha, _, _ = _write_json_with_digest(
        phx_cache_manifest_path,
        {
            "synthetic_fixture": True,
            "returncode": 0,
            "reusable": True,
            "invocation": {"executable": "phenix.python"},
            "artifacts": {},
        },
    )
    phx_reconciled_path = phx_dir / "phenix_reconciled_manifest.json"
    phx_rec_payload = {
        "schema_version": 1,
        "synthetic_fixture": True,
        "subject": copy.deepcopy(phx_staged["admission_record"]["subject"]),
        "mtz": copy.deepcopy(phx_staged["admission_record"]["mtz"]),
        "staged_files": copy.deepcopy(
            phx_staged["admission_record"]["staged_files"]
        ),
        "input_hkl_ledger_json_path": str(phx_staged["input_ledger_path"]),
        "input_hkl_ledger_json_sha256": phx_staged["admission_record"][
            "staged_files"
        ]["input_hkl_ledger_json_sha256"],
        "manifest_path": str(phx_cache_manifest_path),
        "manifest_sha256": phx_cache_sha,
        "operation_manifest": {"returncode": 0, "reusable": True},
        "reconciliation": {"reconciliation_status": "verified"},
    }
    phx_rec_sha, phx_rec_size, _ = _write_json_with_digest(
        phx_reconciled_path, phx_rec_payload
    )

    rm_dir = refmac_root / "refmac"
    rm_log_path = rm_dir / "refmac.log"
    rm_xyzout_path = rm_dir / "refmac_xyzout.pdb"
    rm_hklout_path = rm_dir / "refmac_hklout.mtz"
    rm_log_sha, rm_log_size = _write_file_with_digest(
        rm_log_path, b"SYNTHETIC REFMAC LOG\n"
    )
    rm_xyz_sha, rm_xyz_size = _write_file_with_digest(
        rm_xyzout_path, b"REMARK SYNTHETIC XYZOUT\nEND\n"
    )
    rm_hkl_sha, rm_hkl_size = _write_file_with_digest(
        rm_hklout_path, b"MTZ SYNTHETIC HKLOUT\n"
    )
    rm_adm_sha = hashlib.sha256(
        rm_staged["admission_json_path"].read_bytes()
    ).hexdigest()

    rm_manifest_path = rm_dir / "refmac_operation_manifest.json"
    rm_manifest_payload = {
        "schema_version": 1,
        "synthetic_fixture": True,
        "collector_stage": onesar_refmac.COLLECTOR_STAGE,
        "status": "diagnostic_captured_gates_unproven",
        "publication_pair_complete": True,
        "publication_terminal_failure": None,
        "subject_id": subject_id,
        "subject": copy.deepcopy(rm_staged["admission_record"]["subject"]),
        "mtz": copy.deepcopy(rm_staged["admission_record"]["mtz"]),
        "staged_files": copy.deepcopy(
            rm_staged["admission_record"]["staged_files"]
        ),
        "input_admission_json_path": str(rm_staged["admission_json_path"]),
        "input_admission_json_sha256": rm_adm_sha,
        "input_hkl_ledger_json_path": str(rm_staged["input_ledger_path"]),
        "input_hkl_ledger_json_sha256": rm_staged["admission_record"][
            "staged_files"
        ]["input_hkl_ledger_json_sha256"],
        "invocation": {
            "xyzin_path": str(rm_staged["original_pdb_path"]),
            "hklin_path": str(rm_staged["projected_mtz_path"]),
            "xyzout_path": str(rm_xyzout_path),
            "hklout_path": str(rm_hklout_path),
        },
        "paths": {
            "original_pdb_path": str(rm_staged["original_pdb_path"]),
            "original_mtz_path": str(rm_staged["original_mtz_path"]),
            "projected_mtz_path": str(rm_staged["projected_mtz_path"]),
            "input_ledger_path": str(rm_staged["input_ledger_path"]),
            "admission_json_path": str(rm_staged["admission_json_path"]),
            "log_path": str(rm_log_path),
            "xyzout_path": str(rm_xyzout_path),
            "hklout_path": str(rm_hklout_path),
            "manifest_json_path": str(rm_manifest_path),
        },
        "raw_outputs": {
            "log": {
                "path": str(rm_log_path),
                "sha256": rm_log_sha,
                "size_bytes": rm_log_size,
                "exists": True,
                "is_symlink": False,
                "is_regular_file": True,
            },
            "xyzout": {
                "path": str(rm_xyzout_path),
                "sha256": rm_xyz_sha,
                "size_bytes": rm_xyz_size,
                "exists": True,
                "is_symlink": False,
                "is_regular_file": True,
            },
            "hklout": {
                "path": str(rm_hklout_path),
                "sha256": rm_hkl_sha,
                "size_bytes": rm_hkl_size,
                "exists": True,
                "is_symlink": False,
                "is_regular_file": True,
            },
        },
        "effective_hkls_proven": False,
        "effective_hkls_unproven_reason": "synthetic unproven active HKL mask",
        "native_bin_membership_proven": False,
        "native_bin_membership_unproven_reason": "synthetic unproven native bins",
        "native_residual_reconstruction_proven": False,
        "native_residual_reconstruction_unproven_reason": (
            "synthetic unproven native residual reconstruction"
        ),
        "all_preregistered_gates_passed": False,
        "canonical_eval_qds_eligible": False,
        "eval_admission_eligible": False,
        "qds_admission_eligible": False,
        "canary_admission_eligible": False,
        "scientific_admission_proven": False,
    }
    rm_man_sha, rm_man_size, _ = _write_json_with_digest(
        rm_manifest_path, rm_manifest_payload
    )

    phx_ref = {
        "path": str(phx_reconciled_path),
        "sha256": phx_rec_sha,
        "size_bytes": phx_rec_size,
        "persisted": True,
    }
    rm_ref = {
        "path": str(rm_manifest_path),
        "sha256": rm_man_sha,
        "size_bytes": rm_man_size,
        "persisted": True,
    }
    checkpoint_payload = build_parent_completed_execution_checkpoint_payload(
        subject_id=subject_id,
        family=EXPECTED_FAMILY_ID,
        parent_evidence_root=parent_root,
        phenix_evidence_root=phenix_root,
        refmac_evidence_root=refmac_root,
        phenix_reconciled_manifest=phx_ref,
        refmac_operation_manifest=rm_ref,
        started_at_utc=started_at_utc,
        finished_at_utc=finished_at_utc,
        run_date=run_date,
    )
    checkpoint_path = parent_root / "parent_completed_execution_checkpoint.json"
    cp_sha, cp_size, _ = _write_json_with_digest(
        checkpoint_path, checkpoint_payload
    )
    checkpoint_ref = {
        "path": str(checkpoint_path),
        "sha256": cp_sha,
        "size_bytes": cp_size,
        "persisted": True,
    }
    return {
        "fake_repo": fake_repo,
        "parent_root": parent_root,
        "phenix_root": phenix_root,
        "refmac_root": refmac_root,
        "phenix_staged": phx_staged,
        "refmac_staged": rm_staged,
        "phenix_reconciled_path": phx_reconciled_path,
        "refmac_manifest_path": rm_manifest_path,
        "checkpoint_path": checkpoint_path,
        "checkpoint_payload": checkpoint_payload,
        "checkpoint_ref": checkpoint_ref,
    }


class TestParentExecutionCheckpointBinding(unittest.TestCase):
    """Focused tests for Task 369 Part 2 common-parent identity and time validation."""

    def test_midnight_spanning_utc_interval_and_common_parent_binding_succeed_and_preserve_bytes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp).resolve(strict=True)
            fix = _create_synthetic_common_parent_fixture(
                tmp_root,
                subject_id="R4",
                started_at_utc="2026-11-06T23:58:10+00:00",
                finished_at_utc="2026-11-07T00:03:25+00:00",
                run_date="2026-11-06",
            )
            parent_root: Path = fix["parent_root"]
            parent_snapshot = _snapshot_tree_bytes(parent_root)

            verified = verify_retained_parent_execution_checkpoint(
                parent_root,
                subject_id="R4",
                checkpoint_reference=fix["checkpoint_ref"],
                expected_family="rfactors",
                expected_run_date="2026-11-06",
                repo_root=REPO_ROOT,
            )
            self.assertEqual(verified["verification_status"], "verified")
            self.assertEqual(verified["family"], "rfactors")
            self.assertEqual(verified["subject_id"], "R4")
            self.assertEqual(verified["subject"]["stage"], "final")
            self.assertEqual(verified["timing"]["run_date"], "2026-11-06")
            self.assertEqual(
                verified["timing"]["started_utc_date"], "2026-11-06"
            )
            self.assertEqual(
                verified["timing"]["finished_utc_date"], "2026-11-07"
            )
            self.assertTrue(verified["timing"]["spans_utc_midnight"])
            self.assertEqual(verified["timing"]["elapsed_seconds"], 315.0)
            self.assertIs(
                verified["verification_boundaries"][
                    "parent_execution_checkpoint_verified"
                ],
                True,
            )
            self.assertIs(
                verified["verification_boundaries"][
                    "common_subject_and_projected_inputs_bound"
                ],
                True,
            )
            self.assertIs(
                verified["verification_boundaries"][
                    "authoring_outcome_separated_from_execution_checkpoint"
                ],
                True,
            )
            self.assertIs(
                verified["verification_boundaries"][
                    "scientific_proof_established"
                ],
                False,
            )

            # Also verify non-UTC offset timestamp whose UTC conversion spans midnight:
            # 2026-11-06T16:58:10-07:00 == 2026-11-06T23:58:10+00:00 -> UTC date 2026-11-06.
            non_utc_timing = validate_parent_execution_timing(
                "2026-11-06T16:58:10-07:00",
                "2026-11-06T17:03:25-07:00",
                "2026-11-06",
                expected_run_date="2026-11-06",
            )
            self.assertEqual(non_utc_timing["started_utc_date"], "2026-11-06")
            self.assertEqual(non_utc_timing["finished_utc_date"], "2026-11-07")
            self.assertTrue(non_utc_timing["spans_utc_midnight"])

            self.assertEqual(_snapshot_tree_bytes(parent_root), parent_snapshot)

    def test_malformed_naive_reversed_timestamps_and_run_date_mismatches_rejected(
        self,
    ) -> None:
        # 1. Naive timestamps (missing timezone offset).
        with self.subTest(case="naive_started_at_utc"):
            with self.assertRaisesRegex(
                ParentExecutionBindingError,
                "started_at_utc: expected full timezone-qualified ISO-8601 timestamp",
            ):
                validate_parent_execution_timing(
                    "2026-11-06T23:58:10",
                    "2026-11-07T00:03:25+00:00",
                    "2026-11-06",
                )

        # 2. Malformed timestamp or date-only string.
        with self.subTest(case="malformed_finished_at_utc"):
            with self.assertRaisesRegex(
                ParentExecutionBindingError,
                "finished_at_utc: expected full timezone-qualified ISO-8601 timestamp",
            ):
                validate_parent_execution_timing(
                    "2026-11-06T23:58:10+00:00",
                    "2026-11-07",
                    "2026-11-06",
                )

        # 3. Reversed interval (finished_at_utc < started_at_utc).
        with self.subTest(case="reversed_interval"):
            with self.assertRaisesRegex(
                ParentExecutionBindingError,
                "reversed execution interval",
            ):
                validate_parent_execution_timing(
                    "2026-11-07T00:03:25+00:00",
                    "2026-11-06T23:58:10+00:00",
                    "2026-11-07",
                )

        # 4. Midnight-spanning run where run_date was set to finish date ("2026-11-07")
        # instead of UTC start date ("2026-11-06").
        with self.subTest(case="finish_date_instead_of_utc_start_date"):
            with self.assertRaisesRegex(
                ParentExecutionBindingError,
                "run_date '2026-11-07' disagrees with started_at_utc converted to UTC date '2026-11-06'",
            ):
                validate_parent_execution_timing(
                    "2026-11-06T23:58:10+00:00",
                    "2026-11-07T00:03:25+00:00",
                    "2026-11-07",
                )

        # 5. Non-UTC offset timestamp where local date ("2026-11-06") differs from
        # UTC start date ("2026-11-07" for 2026-11-06T18:30:00-07:00).
        with self.subTest(case="local_date_disagrees_with_utc_converted_start_date"):
            with self.assertRaisesRegex(
                ParentExecutionBindingError,
                "run_date '2026-11-06' disagrees with started_at_utc converted to UTC date '2026-11-07'",
            ):
                validate_parent_execution_timing(
                    "2026-11-06T18:30:00-07:00",
                    "2026-11-06T18:45:00-07:00",
                    "2026-11-06",
                )

    def test_registered_identity_cross_producer_and_authoring_outcome_separation_enforced(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp).resolve(strict=True)
            fix = _create_synthetic_common_parent_fixture(
                tmp_root,
                subject_id="R4",
            )
            parent_root: Path = fix["parent_root"]
            checkpoint_path: Path = fix["checkpoint_path"]
            rm_manifest_path: Path = fix["refmac_manifest_path"]
            parent_snapshot = _snapshot_tree_bytes(parent_root)

            # 0. Family mismatch ("1sar" vs canonical "rfactors") rejected in builder and verifier.
            with self.subTest(case="family_mismatch_rejected"):
                with self.assertRaisesRegex(
                    ParentExecutionBindingError,
                    "parent_execution_checkpoint\\.family: expected 'rfactors', got '1sar'",
                ):
                    build_parent_completed_execution_checkpoint_payload(
                        subject_id="R4",
                        family="1sar",
                        parent_evidence_root=parent_root,
                        phenix_evidence_root=fix["phenix_root"],
                        refmac_evidence_root=fix["refmac_root"],
                        phenix_reconciled_manifest=fix["checkpoint_payload"][
                            "phenix_reconciled_manifest"
                        ],
                        refmac_operation_manifest=fix["checkpoint_payload"][
                            "refmac_operation_manifest"
                        ],
                        started_at_utc="2026-11-06T23:58:10+00:00",
                        finished_at_utc="2026-11-07T00:03:25+00:00",
                        run_date="2026-11-06",
                    )
                try:
                    cp_doc = json.loads(
                        checkpoint_path.read_text(encoding="utf-8")
                    )
                    cp_doc["family"] = "1sar"
                    cp_sha, cp_size, _ = _write_json_with_digest(
                        checkpoint_path, cp_doc
                    )
                    with self.assertRaisesRegex(
                        ParentExecutionBindingError,
                        "parent_execution_checkpoint\\.family: expected 'rfactors', got '1sar'",
                    ):
                        verify_retained_parent_execution_checkpoint(
                            parent_root,
                            subject_id="R4",
                            checkpoint_path=checkpoint_path,
                            checkpoint_sha256=cp_sha,
                            checkpoint_size_bytes=cp_size,
                            repo_root=REPO_ROOT,
                        )
                finally:
                    _restore_tree_bytes(parent_root, parent_snapshot)

            # 1. Authoring-outcome field mixed into the completed execution checkpoint.
            with self.subTest(case="authoring_outcome_mixed_into_checkpoint"):
                try:
                    cp_doc = json.loads(
                        checkpoint_path.read_text(encoding="utf-8")
                    )
                    cp_doc["authoring_outcome"] = {"status": "refused"}
                    cp_sha, cp_size, _ = _write_json_with_digest(
                        checkpoint_path, cp_doc
                    )
                    with self.assertRaisesRegex(
                        ParentExecutionBindingError,
                        "final authoring-outcome field\\(s\\) must remain separate from the hashed execution checkpoint",
                    ):
                        verify_retained_parent_execution_checkpoint(
                            parent_root,
                            subject_id="R4",
                            checkpoint_path=checkpoint_path,
                            checkpoint_sha256=cp_sha,
                            checkpoint_size_bytes=cp_size,
                            repo_root=REPO_ROOT,
                        )
                finally:
                    _restore_tree_bytes(parent_root, parent_snapshot)

            # 2. Cross-producer subject/model mismatch (REFMAC child staged with "start" while PHENIX child is "R4").
            with self.subTest(case="cross_producer_subject_mismatch"):
                try:
                    start_spec = onesar_rerun.resolve_subject_spec("start")
                    rm_doc = json.loads(
                        rm_manifest_path.read_text(encoding="utf-8")
                    )
                    rm_doc["subject_id"] = "start"
                    rm_doc["subject"] = start_spec
                    rm_sha, rm_size, _ = _write_json_with_digest(
                        rm_manifest_path, rm_doc
                    )
                    cp_doc = json.loads(
                        checkpoint_path.read_text(encoding="utf-8")
                    )
                    cp_doc["refmac_operation_manifest"]["sha256"] = rm_sha
                    cp_doc["refmac_operation_manifest"]["size_bytes"] = rm_size
                    cp_sha, cp_size, _ = _write_json_with_digest(
                        checkpoint_path, cp_doc
                    )
                    with self.assertRaisesRegex(
                        ParentExecutionBindingError,
                        "refmac_operation_manifest\\.subject: disagrees with parent/preregistered subject specification for 'R4'",
                    ):
                        verify_retained_parent_execution_checkpoint(
                            parent_root,
                            subject_id="R4",
                            checkpoint_path=checkpoint_path,
                            checkpoint_sha256=cp_sha,
                            checkpoint_size_bytes=cp_size,
                            repo_root=REPO_ROOT,
                        )
                finally:
                    _restore_tree_bytes(parent_root, parent_snapshot)

            # 3. REFMAC output substituted for input in invocation/paths.
            with self.subTest(case="refmac_output_substituted_for_input"):
                try:
                    rm_doc = json.loads(
                        rm_manifest_path.read_text(encoding="utf-8")
                    )
                    rm_doc["invocation"]["hklin_path"] = rm_doc["paths"][
                        "hklout_path"
                    ]
                    rm_sha, rm_size, _ = _write_json_with_digest(
                        rm_manifest_path, rm_doc
                    )
                    cp_doc = json.loads(
                        checkpoint_path.read_text(encoding="utf-8")
                    )
                    cp_doc["refmac_operation_manifest"]["sha256"] = rm_sha
                    cp_doc["refmac_operation_manifest"]["size_bytes"] = rm_size
                    cp_sha, cp_size, _ = _write_json_with_digest(
                        checkpoint_path, cp_doc
                    )
                    with self.assertRaisesRegex(
                        ParentExecutionBindingError,
                        "REFMAC outputs must reside in refmac_dir and never replace staged inputs",
                    ):
                        verify_retained_parent_execution_checkpoint(
                            parent_root,
                            subject_id="R4",
                            checkpoint_path=checkpoint_path,
                            checkpoint_sha256=cp_sha,
                            checkpoint_size_bytes=cp_size,
                            repo_root=REPO_ROOT,
                        )
                finally:
                    _restore_tree_bytes(parent_root, parent_snapshot)

            # 4. Overlapping/identical producer child roots rejected.
            with self.subTest(case="identical_child_roots_rejected"):
                with self.assertRaisesRegex(
                    ParentExecutionBindingError,
                    "phenix_evidence_root and refmac_evidence_root must be distinct non-overlapping child directories",
                ):
                    build_parent_completed_execution_checkpoint_payload(
                        subject_id="R4",
                        parent_evidence_root=parent_root,
                        phenix_evidence_root=fix["phenix_root"],
                        refmac_evidence_root=fix["phenix_root"],
                        phenix_reconciled_manifest=fix["checkpoint_payload"][
                            "phenix_reconciled_manifest"
                        ],
                        refmac_operation_manifest=fix["checkpoint_payload"][
                            "refmac_operation_manifest"
                        ],
                        started_at_utc="2026-11-06T23:58:10+00:00",
                        finished_at_utc="2026-11-07T00:03:25+00:00",
                        run_date="2026-11-06",
                    )

            # 5. Relocated clean REFMAC manifest at fallback path in parent checkpoint rejected.
            with self.subTest(case="relocated_clean_refmac_fallback_rejected_in_parent"):
                try:
                    rm_doc = json.loads(
                        rm_manifest_path.read_text(encoding="utf-8")
                    )
                    parent_ret_dir = (
                        fix["refmac_root"] / "refmac_parent_retention"
                    )
                    reloc_rm_path = (
                        parent_ret_dir / "refmac_operation_manifest.json"
                    )
                    rm_doc["paths"]["manifest_json_path"] = str(reloc_rm_path)
                    reloc_sha, reloc_size, _ = _write_json_with_digest(
                        reloc_rm_path, rm_doc
                    )
                    cp_doc = json.loads(
                        checkpoint_path.read_text(encoding="utf-8")
                    )
                    cp_doc["refmac_operation_manifest"] = {
                        "path": str(reloc_rm_path),
                        "sha256": reloc_sha,
                        "size_bytes": reloc_size,
                        "persisted": True,
                    }
                    cp_sha, cp_size, _ = _write_json_with_digest(
                        checkpoint_path, cp_doc
                    )
                    with self.assertRaisesRegex(
                        ParentExecutionBindingError,
                        "fallback manifest location or metadata requires supported fallback failure stage in failures",
                    ):
                        verify_retained_parent_execution_checkpoint(
                            parent_root,
                            subject_id="R4",
                            checkpoint_path=checkpoint_path,
                            checkpoint_sha256=cp_sha,
                            checkpoint_size_bytes=cp_size,
                            repo_root=REPO_ROOT,
                        )
                finally:
                    _restore_tree_bytes(parent_root, parent_snapshot)

            self.assertEqual(_snapshot_tree_bytes(parent_root), parent_snapshot)

            # 6. Genuine F1 producer-persisted fallback REFMAC manifest bound alongside PHENIX child
            # in parent completed execution checkpoint succeeds with scientific_proof_established=False.
            with self.subTest(case="genuine_f1_fallback_refmac_bound_in_parent_checkpoint"):
                f1_parent_root = (
                    fix["fake_repo"] / "runs" / "parent_with_f1_refmac"
                )
                f1_phenix_root = f1_parent_root / "phenix_child"
                f1_refmac_root = f1_parent_root / "refmac_child"
                f1_phx_staged = onesar_rerun.stage_subject_inputs(
                    f1_phenix_root,
                    subject_id="R4",
                    repo_root=fix["fake_repo"],
                    archive_path=COMMITTED_ARCHIVE,
                )
                f1_rm_env = _create_synthetic_f1_fallback_refmac_capture(
                    tmp_root,
                    subject_id="R4",
                    run_name="parent_f1_rm_child",
                    evidence_root=f1_refmac_root,
                    fake_repo=fix["fake_repo"],
                )
                f1_parent_root = f1_parent_root.resolve(strict=True)
                f1_phenix_root = f1_phenix_root.resolve(strict=True)
                f1_refmac_root = f1_refmac_root.resolve(strict=True)

                f1_phx_dir = f1_phenix_root / "phenix"
                f1_phx_cache_path = (
                    f1_phx_dir / "cache" / "bundle" / "success.json"
                )
                f1_phx_cache_sha, _, _ = _write_json_with_digest(
                    f1_phx_cache_path,
                    {
                        "synthetic_fixture": True,
                        "returncode": 0,
                        "reusable": True,
                        "invocation": {"executable": "phenix.python"},
                        "artifacts": {},
                    },
                )
                f1_phx_rec_path = (
                    f1_phx_dir / "phenix_reconciled_manifest.json"
                )
                f1_phx_rec_sha, f1_phx_rec_size, _ = _write_json_with_digest(
                    f1_phx_rec_path,
                    {
                        "schema_version": 1,
                        "synthetic_fixture": True,
                        "subject": copy.deepcopy(
                            f1_phx_staged["admission_record"]["subject"]
                        ),
                        "mtz": copy.deepcopy(
                            f1_phx_staged["admission_record"]["mtz"]
                        ),
                        "staged_files": copy.deepcopy(
                            f1_phx_staged["admission_record"]["staged_files"]
                        ),
                        "input_hkl_ledger_json_path": str(
                            f1_phx_staged["input_ledger_path"]
                        ),
                        "input_hkl_ledger_json_sha256": f1_phx_staged[
                            "admission_record"
                        ]["staged_files"]["input_hkl_ledger_json_sha256"],
                        "manifest_path": str(f1_phx_cache_path),
                        "manifest_sha256": f1_phx_cache_sha,
                        "operation_manifest": {
                            "returncode": 0,
                            "reusable": True,
                        },
                        "reconciliation": {
                            "reconciliation_status": "verified"
                        },
                    },
                )
                f1_cp_payload = (
                    build_parent_completed_execution_checkpoint_payload(
                        subject_id="R4",
                        family=EXPECTED_FAMILY_ID,
                        parent_evidence_root=f1_parent_root,
                        phenix_evidence_root=f1_phenix_root,
                        refmac_evidence_root=f1_refmac_root,
                        phenix_reconciled_manifest={
                            "path": str(f1_phx_rec_path),
                            "sha256": f1_phx_rec_sha,
                            "size_bytes": f1_phx_rec_size,
                            "persisted": True,
                        },
                        refmac_operation_manifest=f1_rm_env["manifest_ref"],
                        started_at_utc="2026-11-06T23:58:10+00:00",
                        finished_at_utc="2026-11-07T00:03:25+00:00",
                        run_date="2026-11-06",
                    )
                )
                f1_cp_path = (
                    f1_parent_root
                    / "parent_completed_execution_checkpoint.json"
                )
                f1_cp_sha, f1_cp_size, _ = _write_json_with_digest(
                    f1_cp_path, f1_cp_payload
                )
                f1_parent_snapshot = _snapshot_tree_bytes(f1_parent_root)
                f1_verified = verify_retained_parent_execution_checkpoint(
                    f1_parent_root,
                    subject_id="R4",
                    checkpoint_reference={
                        "path": str(f1_cp_path),
                        "sha256": f1_cp_sha,
                        "size_bytes": f1_cp_size,
                        "persisted": True,
                    },
                    repo_root=REPO_ROOT,
                )
                self.assertEqual(
                    f1_verified["verification_status"], "verified"
                )
                self.assertEqual(f1_verified["family"], "rfactors")
                self.assertEqual(
                    f1_verified["verified_references"][
                        "refmac_operation_manifest"
                    ]["path"],
                    str(f1_rm_env["manifest_path"]),
                )
                self.assertIs(
                    f1_verified["verification_boundaries"][
                        "scientific_proof_established"
                    ],
                    False,
                )
                self.assertEqual(
                    _snapshot_tree_bytes(f1_parent_root), f1_parent_snapshot
                )

            # 7. Genuine verified-root fallback REFMAC manifest (#1063) bound alongside PHENIX child
            # in parent completed execution checkpoint succeeds with scientific_proof_established=False,
            # while contradictory/missing anchor metadata or an incomplete publication pair is rejected.
            with self.subTest(
                case="genuine_verified_root_fallback_refmac_bound_in_parent_checkpoint"
            ):
                rf_parent_root = (
                    fix["fake_repo"]
                    / "runs"
                    / "parent_with_verified_root_fallback_refmac"
                )
                rf_phenix_root = rf_parent_root / "phenix_child"
                rf_refmac_root = rf_parent_root / "refmac_child"
                rf_phx_staged = onesar_rerun.stage_subject_inputs(
                    rf_phenix_root,
                    subject_id="R4",
                    repo_root=fix["fake_repo"],
                    archive_path=COMMITTED_ARCHIVE,
                )
                rf_rm_env = (
                    _create_synthetic_verified_root_fallback_refmac_capture(
                        tmp_root,
                        subject_id="R4",
                        run_name="parent_verified_root_fb_rm_child",
                        evidence_root=rf_refmac_root,
                        fake_repo=fix["fake_repo"],
                    )
                )
                rf_parent_root = rf_parent_root.resolve(strict=True)
                rf_phenix_root = rf_phenix_root.resolve(strict=True)
                rf_refmac_root = rf_refmac_root.resolve(strict=True)

                rf_phx_dir = rf_phenix_root / "phenix"
                rf_phx_cache_path = (
                    rf_phx_dir / "cache" / "bundle" / "success.json"
                )
                rf_phx_cache_sha, _, _ = _write_json_with_digest(
                    rf_phx_cache_path,
                    {
                        "synthetic_fixture": True,
                        "returncode": 0,
                        "reusable": True,
                        "invocation": {"executable": "phenix.python"},
                        "artifacts": {},
                    },
                )
                rf_phx_rec_path = (
                    rf_phx_dir / "phenix_reconciled_manifest.json"
                )
                rf_phx_rec_sha, rf_phx_rec_size, _ = _write_json_with_digest(
                    rf_phx_rec_path,
                    {
                        "schema_version": 1,
                        "synthetic_fixture": True,
                        "subject": copy.deepcopy(
                            rf_phx_staged["admission_record"]["subject"]
                        ),
                        "mtz": copy.deepcopy(
                            rf_phx_staged["admission_record"]["mtz"]
                        ),
                        "staged_files": copy.deepcopy(
                            rf_phx_staged["admission_record"]["staged_files"]
                        ),
                        "input_hkl_ledger_json_path": str(
                            rf_phx_staged["input_ledger_path"]
                        ),
                        "input_hkl_ledger_json_sha256": rf_phx_staged[
                            "admission_record"
                        ]["staged_files"]["input_hkl_ledger_json_sha256"],
                        "manifest_path": str(rf_phx_cache_path),
                        "manifest_sha256": rf_phx_cache_sha,
                        "operation_manifest": {
                            "returncode": 0,
                            "reusable": True,
                        },
                        "reconciliation": {
                            "reconciliation_status": "verified"
                        },
                    },
                )
                rf_cp_payload = (
                    build_parent_completed_execution_checkpoint_payload(
                        subject_id="R4",
                        family=EXPECTED_FAMILY_ID,
                        parent_evidence_root=rf_parent_root,
                        phenix_evidence_root=rf_phenix_root,
                        refmac_evidence_root=rf_refmac_root,
                        phenix_reconciled_manifest={
                            "path": str(rf_phx_rec_path),
                            "sha256": rf_phx_rec_sha,
                            "size_bytes": rf_phx_rec_size,
                            "persisted": True,
                        },
                        refmac_operation_manifest=rf_rm_env["manifest_ref"],
                        started_at_utc="2026-11-06T23:58:10+00:00",
                        finished_at_utc="2026-11-07T00:03:25+00:00",
                        run_date="2026-11-06",
                    )
                )
                rf_cp_path = (
                    rf_parent_root
                    / "parent_completed_execution_checkpoint.json"
                )
                rf_cp_sha, rf_cp_size, _ = _write_json_with_digest(
                    rf_cp_path, rf_cp_payload
                )
                rf_parent_snapshot = _snapshot_tree_bytes(rf_parent_root)

                real_resolve_anchor = (
                    onesar_records._resolve_and_validate_refmac_actual_anchor
                )
                real_classify_fb = (
                    onesar_records._classify_refmac_fallback_failures
                )
                parent_anchor_invocations: list[str | None] = []
                parent_anchor_calls: list[Path | None] = []
                parent_classify_calls: list[tuple[bool, bool, bool]] = []

                def _spy_parent_resolve_anchor(
                    *args: Any, **kwargs: Any
                ) -> Path | None:
                    doc_arg = (
                        args[0] if args else kwargs.get("manifest_doc", {})
                    )
                    parent_anchor_invocations.append(
                        doc_arg.get("actual_parent_retention_anchor_kind")
                        if isinstance(doc_arg, Mapping)
                        else None
                    )
                    res = real_resolve_anchor(*args, **kwargs)
                    parent_anchor_calls.append(res)
                    return res

                def _spy_parent_classify_fb(
                    *args: Any, **kwargs: Any
                ) -> tuple[bool, bool, bool]:
                    res = real_classify_fb(*args, **kwargs)
                    parent_classify_calls.append(res)
                    return res

                with (
                    mock.patch.object(
                        onesar_records,
                        "_resolve_and_validate_refmac_actual_anchor",
                        side_effect=_spy_parent_resolve_anchor,
                    ),
                    mock.patch.object(
                        onesar_records,
                        "_classify_refmac_fallback_failures",
                        side_effect=_spy_parent_classify_fb,
                    ),
                ):
                    rf_verified = verify_retained_parent_execution_checkpoint(
                        rf_parent_root,
                        subject_id="R4",
                        checkpoint_reference={
                            "path": str(rf_cp_path),
                            "sha256": rf_cp_sha,
                            "size_bytes": rf_cp_size,
                            "persisted": True,
                        },
                        repo_root=REPO_ROOT,
                    )
                self.assertEqual(
                    parent_anchor_calls, [rf_rm_env["actual_anchor_dir"]]
                )
                self.assertEqual(
                    parent_classify_calls, [(True, True, False)]
                )
                self.assertEqual(
                    rf_verified["verification_status"], "verified"
                )
                self.assertEqual(rf_verified["family"], "rfactors")
                self.assertEqual(
                    rf_verified["verified_references"][
                        "refmac_operation_manifest"
                    ]["path"],
                    str(rf_rm_env["manifest_path"]),
                )
                self.assertEqual(
                    Path(
                        rf_verified["verified_references"][
                            "refmac_operation_manifest"
                        ]["path"]
                    ).parent,
                    rf_rm_env["actual_anchor_dir"],
                )
                self.assertTrue(
                    rf_verified["verified_references"][
                        "refmac_operation_manifest"
                    ]["is_fallback"]
                )
                self.assertEqual(
                    rf_rm_env["manifest_payload"][
                        "actual_parent_retention_anchor_kind"
                    ],
                    "verified_evidence_root_exclusive_dir",
                )
                self.assertEqual(
                    rf_rm_env["manifest_payload"][
                        "actual_parent_retention_anchor_dir"
                    ],
                    str(rf_rm_env["actual_anchor_dir"]),
                )
                self.assertEqual(
                    rf_rm_env["manifest_payload"]["status"],
                    "failed",
                )
                self.assertIs(
                    rf_verified["verification_boundaries"][
                        "scientific_proof_established"
                    ],
                    False,
                )
                self.assertEqual(
                    _snapshot_tree_bytes(rf_parent_root), rf_parent_snapshot
                )

                # Contradictory anchor metadata or incomplete publication pair in parent checkpoint is rejected.
                try:
                    rm_man_doc = json.loads(
                        rf_rm_env["manifest_path"].read_text(encoding="utf-8")
                    )
                    rm_diag_doc = json.loads(
                        rf_rm_env["diagnostics_path"].read_text(
                            encoding="utf-8"
                        )
                    )
                    rm_man_doc["parent_retention_fallback_anchor"][
                        "evidence_root_verified"
                    ] = False
                    rm_diag_doc["parent_retention_fallback_anchor"][
                        "evidence_root_verified"
                    ] = False
                    bad_rm_ref = _rehash_refmac_manifest_and_diagnostics(
                        rf_rm_env["manifest_path"],
                        rf_rm_env["diagnostics_path"],
                        manifest_doc=rm_man_doc,
                        diagnostics_doc=rm_diag_doc,
                    )
                    cp_doc = json.loads(rf_cp_path.read_text(encoding="utf-8"))
                    cp_doc["refmac_operation_manifest"]["sha256"] = bad_rm_ref[
                        "sha256"
                    ]
                    cp_doc["refmac_operation_manifest"]["size_bytes"] = (
                        bad_rm_ref["size_bytes"]
                    )
                    bad_cp_sha, bad_cp_size, _ = _write_json_with_digest(
                        rf_cp_path, cp_doc
                    )
                    parent_classify_calls.clear()
                    with (
                        mock.patch.object(
                            onesar_records,
                            "_classify_refmac_fallback_failures",
                            side_effect=_spy_parent_classify_fb,
                        ),
                        self.assertRaisesRegex(
                            ParentExecutionBindingError,
                            "fallback manifest location or metadata requires supported fallback failure stage in failures",
                        ),
                    ):
                        verify_retained_parent_execution_checkpoint(
                            rf_parent_root,
                            subject_id="R4",
                            checkpoint_reference={
                                "path": str(rf_cp_path),
                                "sha256": bad_cp_sha,
                                "size_bytes": bad_cp_size,
                                "persisted": True,
                            },
                            repo_root=REPO_ROOT,
                        )
                    self.assertEqual(
                        parent_classify_calls, [(False, False, False)]
                    )
                finally:
                    _restore_tree_bytes(rf_parent_root, rf_parent_snapshot)

                try:
                    rm_man_doc = json.loads(
                        rf_rm_env["manifest_path"].read_text(encoding="utf-8")
                    )
                    rm_diag_doc = json.loads(
                        rf_rm_env["diagnostics_path"].read_text(
                            encoding="utf-8"
                        )
                    )
                    self.assertEqual(
                        rm_man_doc["actual_parent_retention_anchor_kind"],
                        "verified_evidence_root_exclusive_dir",
                    )
                    self.assertEqual(
                        rm_diag_doc["actual_parent_retention_anchor_kind"],
                        "verified_evidence_root_exclusive_dir",
                    )
                    rm_man_doc["actual_parent_retention_anchor_dir"] = None
                    rm_diag_doc["actual_parent_retention_anchor_dir"] = None
                    missing_rm_ref = _rehash_refmac_manifest_and_diagnostics(
                        rf_rm_env["manifest_path"],
                        rf_rm_env["diagnostics_path"],
                        manifest_doc=rm_man_doc,
                        diagnostics_doc=rm_diag_doc,
                    )
                    cp_doc = json.loads(rf_cp_path.read_text(encoding="utf-8"))
                    cp_doc["refmac_operation_manifest"]["sha256"] = (
                        missing_rm_ref["sha256"]
                    )
                    cp_doc["refmac_operation_manifest"]["size_bytes"] = (
                        missing_rm_ref["size_bytes"]
                    )
                    missing_cp_sha, missing_cp_size, _ = (
                        _write_json_with_digest(rf_cp_path, cp_doc)
                    )
                    parent_anchor_invocations.clear()
                    parent_anchor_calls.clear()
                    with (
                        mock.patch.object(
                            onesar_records,
                            "_resolve_and_validate_refmac_actual_anchor",
                            side_effect=_spy_parent_resolve_anchor,
                        ),
                        self.assertRaisesRegex(
                            ParentExecutionBindingError,
                            "refmac_operation_manifest\\.actual_parent_retention_anchor_kind: expected None when actual_parent_retention_anchor_dir is None, got 'verified_evidence_root_exclusive_dir'",
                        ),
                    ):
                        verify_retained_parent_execution_checkpoint(
                            rf_parent_root,
                            subject_id="R4",
                            checkpoint_reference={
                                "path": str(rf_cp_path),
                                "sha256": missing_cp_sha,
                                "size_bytes": missing_cp_size,
                                "persisted": True,
                            },
                            repo_root=REPO_ROOT,
                        )
                    self.assertEqual(
                        parent_anchor_invocations,
                        ["verified_evidence_root_exclusive_dir"],
                    )
                    self.assertEqual(parent_anchor_calls, [])
                finally:
                    _restore_tree_bytes(rf_parent_root, rf_parent_snapshot)

                try:
                    rm_man_doc = json.loads(
                        rf_rm_env["manifest_path"].read_text(encoding="utf-8")
                    )
                    rm_man_doc["diagnostics_json"] = None
                    inc_rm_sha, inc_rm_size, _ = _write_json_with_digest(
                        rf_rm_env["manifest_path"], rm_man_doc
                    )
                    cp_doc = json.loads(rf_cp_path.read_text(encoding="utf-8"))
                    cp_doc["refmac_operation_manifest"]["sha256"] = inc_rm_sha
                    cp_doc["refmac_operation_manifest"]["size_bytes"] = (
                        inc_rm_size
                    )
                    inc_cp_sha, inc_cp_size, _ = _write_json_with_digest(
                        rf_cp_path, cp_doc
                    )
                    parent_classify_calls.clear()
                    with (
                        mock.patch.object(
                            onesar_records,
                            "_classify_refmac_fallback_failures",
                            side_effect=_spy_parent_classify_fb,
                        ),
                        self.assertRaisesRegex(
                            ParentExecutionBindingError,
                            "fallback manifest location or metadata requires supported fallback failure stage in failures",
                        ),
                    ):
                        verify_retained_parent_execution_checkpoint(
                            rf_parent_root,
                            subject_id="R4",
                            checkpoint_reference={
                                "path": str(rf_cp_path),
                                "sha256": inc_cp_sha,
                                "size_bytes": inc_cp_size,
                                "persisted": True,
                            },
                            repo_root=REPO_ROOT,
                        )
                    self.assertEqual(
                        parent_classify_calls, [(False, False, False)]
                    )
                finally:
                    _restore_tree_bytes(rf_parent_root, rf_parent_snapshot)

                for (
                    pub_case_label,
                    target_member,
                    field_name,
                    field_value,
                    expected_err_re,
                ) in (
                    (
                        "manifest_pair_incomplete",
                        "manifest",
                        "publication_pair_complete",
                        False,
                        "refmac_operation_manifest: refusing incomplete publication pair \\(publication_pair_complete=False\\)",
                    ),
                    (
                        "manifest_terminal_failure",
                        "manifest",
                        "publication_terminal_failure",
                        {
                            "stage": "persist_manifest_m0",
                            "reason": "M0 failed after D0 was saved in verified-root fallback",
                        },
                        "refmac_operation_manifest: refusing manifest with publication_terminal_failure=",
                    ),
                    (
                        "diagnostics_pair_incomplete",
                        "diagnostics",
                        "publication_pair_complete",
                        False,
                        "refmac_diagnostics: refusing incomplete publication pair \\(publication_pair_complete=False\\)",
                    ),
                    (
                        "diagnostics_terminal_failure",
                        "diagnostics",
                        "publication_terminal_failure",
                        {
                            "stage": "persist_diagnostics_d0",
                            "reason": "D0 failed before M0 in verified-root fallback",
                        },
                        "refmac_diagnostics: refusing diagnostics with publication_terminal_failure=",
                    ),
                    (
                        "manifest_terminal_failure_omitted",
                        "manifest",
                        "publication_terminal_failure",
                        "__delete_field__",
                        "refmac_operation_manifest: missing required publication_terminal_failure key",
                    ),
                    (
                        "diagnostics_terminal_failure_omitted",
                        "diagnostics",
                        "publication_terminal_failure",
                        "__delete_field__",
                        "refmac_diagnostics: missing required publication_terminal_failure key",
                    ),
                ):
                    with self.subTest(
                        parent_publication_member_case=pub_case_label
                    ):
                        try:
                            rm_man_doc = json.loads(
                                rf_rm_env["manifest_path"].read_text(
                                    encoding="utf-8"
                                )
                            )
                            rm_diag_doc = json.loads(
                                rf_rm_env["diagnostics_path"].read_text(
                                    encoding="utf-8"
                                )
                            )
                            target_rm_doc = (
                                rm_man_doc
                                if target_member == "manifest"
                                else rm_diag_doc
                            )
                            if field_value == "__delete_field__":
                                del target_rm_doc[field_name]
                            else:
                                target_rm_doc[field_name] = field_value
                            mut_rm_ref = (
                                _rehash_refmac_manifest_and_diagnostics(
                                    rf_rm_env["manifest_path"],
                                    rf_rm_env["diagnostics_path"],
                                    manifest_doc=rm_man_doc,
                                    diagnostics_doc=rm_diag_doc,
                                )
                            )
                            cp_doc = json.loads(
                                rf_cp_path.read_text(encoding="utf-8")
                            )
                            cp_doc["refmac_operation_manifest"]["sha256"] = (
                                mut_rm_ref["sha256"]
                            )
                            cp_doc["refmac_operation_manifest"][
                                "size_bytes"
                            ] = mut_rm_ref["size_bytes"]
                            mut_cp_sha, mut_cp_size, _ = (
                                _write_json_with_digest(rf_cp_path, cp_doc)
                            )
                            with self.assertRaisesRegex(
                                ParentExecutionBindingError,
                                expected_err_re,
                            ):
                                verify_retained_parent_execution_checkpoint(
                                    rf_parent_root,
                                    subject_id="R4",
                                    checkpoint_reference={
                                        "path": str(rf_cp_path),
                                        "sha256": mut_cp_sha,
                                        "size_bytes": mut_cp_size,
                                        "persisted": True,
                                    },
                                    repo_root=REPO_ROOT,
                                )
                        finally:
                            _restore_tree_bytes(
                                rf_parent_root, rf_parent_snapshot
                            )

                rf_verified_post = verify_retained_parent_execution_checkpoint(
                    rf_parent_root,
                    subject_id="R4",
                    checkpoint_reference={
                        "path": str(rf_cp_path),
                        "sha256": rf_cp_sha,
                        "size_bytes": rf_cp_size,
                        "persisted": True,
                    },
                    repo_root=REPO_ROOT,
                )
                self.assertEqual(
                    rf_verified_post["verification_status"], "verified"
                )
                self.assertEqual(
                    _snapshot_tree_bytes(rf_parent_root), rf_parent_snapshot
                )

    def test_phenix_child_input_admission_symlink_refused_before_any_target_open_or_read(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp).resolve(strict=True)
            fix = _create_synthetic_common_parent_fixture(
                tmp_root,
                subject_id="R4",
            )
            parent_root: Path = fix["parent_root"]
            phenix_root: Path = fix["phenix_root"]
            parent_snapshot = _snapshot_tree_bytes(parent_root)

            outside_dir = (tmp_root / "outside_sentinel_dir").resolve()
            outside_dir.mkdir(parents=True, exist_ok=True)
            outside_sentinel = outside_dir / "input_admission.json"
            outside_sentinel.write_bytes(
                b'{"outside_sentinel": true, "must_never_be_opened": true}\n'
            )

            real_os_open = os.open
            real_builtins_open = builtins.open
            real_io_open = io.open
            real_path_open = Path.open
            real_path_read_bytes = Path.read_bytes
            real_path_read_text = Path.read_text
            real_admit_and_hash = (
                onesar_records._admit_and_hash_regular_file_under_root
            )
            opened_outside_targets: list[str] = []

            def _record_if_outside_target(path_obj: Any) -> None:
                if isinstance(path_obj, int):
                    return
                try:
                    raw_path = os.fspath(path_obj)
                except TypeError:
                    return
                if isinstance(raw_path, bytes):
                    raw_path = os.fsdecode(raw_path)
                try:
                    resolved = Path(raw_path).resolve(strict=False)
                    if resolved == outside_sentinel or resolved.is_relative_to(
                        outside_dir
                    ):
                        opened_outside_targets.append(str(raw_path))
                except OSError:
                    pass

            def _spy_os_open(
                path: str | os.PathLike[str],
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                _record_if_outside_target(path)
                if dir_fd is not None:
                    return real_os_open(path, flags, mode, dir_fd=dir_fd)
                return real_os_open(path, flags, mode)

            def _spy_builtins_open(
                file: Any, *args: Any, **kwargs: Any
            ) -> Any:
                _record_if_outside_target(file)
                return real_builtins_open(file, *args, **kwargs)

            def _spy_io_open(file: Any, *args: Any, **kwargs: Any) -> Any:
                _record_if_outside_target(file)
                return real_io_open(file, *args, **kwargs)

            def _spy_path_open(
                self_path: Path, *args: Any, **kwargs: Any
            ) -> Any:
                _record_if_outside_target(self_path)
                return real_path_open(self_path, *args, **kwargs)

            def _spy_path_read_bytes(
                self_path: Path, *args: Any, **kwargs: Any
            ) -> bytes:
                _record_if_outside_target(self_path)
                return real_path_read_bytes(self_path, *args, **kwargs)

            def _spy_path_read_text(
                self_path: Path, *args: Any, **kwargs: Any
            ) -> str:
                _record_if_outside_target(self_path)
                return real_path_read_text(self_path, *args, **kwargs)

            def _deliberate_preread_admit_and_hash(
                admitted_root: Path,
                candidate_path: Path,
                *,
                label: str,
            ) -> tuple[Path, str, int]:
                _ = Path(candidate_path).read_bytes()
                return real_admit_and_hash(
                    admitted_root,
                    candidate_path,
                    label=label,
                )

            # 1. Leaf symlink: phenix_root / "inputs" / "input_admission.json" -> outside_sentinel.
            with self.subTest(case="leaf_symlink_input_admission_json"):
                opened_outside_targets.clear()
                phx_admission_path = (
                    phenix_root / "inputs" / "input_admission.json"
                )
                try:
                    phx_admission_path.unlink()
                    os.symlink(outside_sentinel, phx_admission_path)
                    with (
                        mock.patch.object(
                            os, "open", side_effect=_spy_os_open
                        ),
                        mock.patch.object(
                            builtins, "open", side_effect=_spy_builtins_open
                        ),
                        mock.patch.object(io, "open", side_effect=_spy_io_open),
                        mock.patch.object(Path, "open", _spy_path_open),
                        mock.patch.object(
                            Path, "read_bytes", _spy_path_read_bytes
                        ),
                        mock.patch.object(
                            Path, "read_text", _spy_path_read_text
                        ),
                        self.assertRaisesRegex(
                            ParentExecutionBindingError,
                            "phenix_child\\.input_admission_json: retained file path is a symlink",
                        ),
                    ):
                        verify_retained_parent_execution_checkpoint(
                            parent_root,
                            subject_id="R4",
                            checkpoint_reference=fix["checkpoint_ref"],
                            repo_root=REPO_ROOT,
                        )
                    self.assertEqual(opened_outside_targets, [])

                    # Controlled negative-control check: a deliberate Path.read_bytes pre-read before
                    # the real path admission guard IS detected by the spy on the leaf symlink.
                    opened_outside_targets.clear()
                    with (
                        mock.patch.object(
                            os, "open", side_effect=_spy_os_open
                        ),
                        mock.patch.object(
                            builtins, "open", side_effect=_spy_builtins_open
                        ),
                        mock.patch.object(io, "open", side_effect=_spy_io_open),
                        mock.patch.object(Path, "open", _spy_path_open),
                        mock.patch.object(
                            Path, "read_bytes", _spy_path_read_bytes
                        ),
                        mock.patch.object(
                            Path, "read_text", _spy_path_read_text
                        ),
                        mock.patch.object(
                            onesar_records,
                            "_admit_and_hash_regular_file_under_root",
                            side_effect=_deliberate_preread_admit_and_hash,
                        ),
                        self.assertRaisesRegex(
                            ParentExecutionBindingError,
                            "phenix_child\\.input_admission_json: retained file path is a symlink",
                        ),
                    ):
                        verify_retained_parent_execution_checkpoint(
                            parent_root,
                            subject_id="R4",
                            checkpoint_reference=fix["checkpoint_ref"],
                            repo_root=REPO_ROOT,
                        )
                    self.assertGreaterEqual(len(opened_outside_targets), 1)
                finally:
                    if os.path.lexists(phx_admission_path):
                        phx_admission_path.unlink()
                    _restore_tree_bytes(parent_root, parent_snapshot)

            # 2. Ancestor directory symlink: phenix_root / "inputs" -> outside_dir.
            with self.subTest(case="ancestor_symlink_inputs_dir"):
                opened_outside_targets.clear()
                phx_inputs_dir = phenix_root / "inputs"
                backup_inputs_dir = tmp_root / "backup_phenix_inputs"
                try:
                    phx_inputs_dir.rename(backup_inputs_dir)
                    os.symlink(outside_dir, phx_inputs_dir)
                    with (
                        mock.patch.object(
                            os, "open", side_effect=_spy_os_open
                        ),
                        mock.patch.object(
                            builtins, "open", side_effect=_spy_builtins_open
                        ),
                        mock.patch.object(io, "open", side_effect=_spy_io_open),
                        mock.patch.object(Path, "open", _spy_path_open),
                        mock.patch.object(
                            Path, "read_bytes", _spy_path_read_bytes
                        ),
                        mock.patch.object(
                            Path, "read_text", _spy_path_read_text
                        ),
                        self.assertRaisesRegex(
                            ParentExecutionBindingError,
                            "phenix_child\\.input_admission_json: ancestor component is a symlink",
                        ),
                    ):
                        verify_retained_parent_execution_checkpoint(
                            parent_root,
                            subject_id="R4",
                            checkpoint_reference=fix["checkpoint_ref"],
                            repo_root=REPO_ROOT,
                        )
                    self.assertEqual(opened_outside_targets, [])

                    # Controlled negative-control check: a deliberate Path.read_bytes pre-read before
                    # the real path admission guard IS detected by the spy on the ancestor symlink.
                    opened_outside_targets.clear()
                    with (
                        mock.patch.object(
                            os, "open", side_effect=_spy_os_open
                        ),
                        mock.patch.object(
                            builtins, "open", side_effect=_spy_builtins_open
                        ),
                        mock.patch.object(io, "open", side_effect=_spy_io_open),
                        mock.patch.object(Path, "open", _spy_path_open),
                        mock.patch.object(
                            Path, "read_bytes", _spy_path_read_bytes
                        ),
                        mock.patch.object(
                            Path, "read_text", _spy_path_read_text
                        ),
                        mock.patch.object(
                            onesar_records,
                            "_admit_and_hash_regular_file_under_root",
                            side_effect=_deliberate_preread_admit_and_hash,
                        ),
                        self.assertRaisesRegex(
                            ParentExecutionBindingError,
                            "phenix_child\\.input_admission_json: ancestor component is a symlink",
                        ),
                    ):
                        verify_retained_parent_execution_checkpoint(
                            parent_root,
                            subject_id="R4",
                            checkpoint_reference=fix["checkpoint_ref"],
                            repo_root=REPO_ROOT,
                        )
                    self.assertGreaterEqual(len(opened_outside_targets), 1)
                finally:
                    if os.path.islink(phx_inputs_dir):
                        phx_inputs_dir.unlink()
                    if backup_inputs_dir.exists():
                        backup_inputs_dir.rename(phx_inputs_dir)
                    _restore_tree_bytes(parent_root, parent_snapshot)

            self.assertEqual(_snapshot_tree_bytes(parent_root), parent_snapshot)


if __name__ == "__main__":
    unittest.main()

