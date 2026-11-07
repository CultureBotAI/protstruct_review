"""Focused tests for the Task 357 retained-reference verification slice."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from typing import Any
from unittest import mock

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import onesar_refmac
import onesar_rerun
from onesar_records import (
    PhenixRetainedVerificationError,
    RetainedReferenceError,
    decode_strict_json_mapping,
    load_retained_reference,
    normalize_retained_reference,
    verify_retained_phenix_rfactor_evidence,
)
import refinement_cache
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


if __name__ == "__main__":
    unittest.main()

