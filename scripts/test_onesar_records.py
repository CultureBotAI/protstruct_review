"""Focused tests for the Task 357 retained-reference verification slice."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import onesar_refmac
from onesar_records import (
    RetainedReferenceError,
    decode_strict_json_mapping,
    load_retained_reference,
    normalize_retained_reference,
)


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


if __name__ == "__main__":
    unittest.main()
