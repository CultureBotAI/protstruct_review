#!/usr/bin/env python3
"""Focused tests for scripts/prepare_refmac_diagnostic.py and trace_hooks.f90."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import prepare_refmac_diagnostic as prd  # noqa: E402


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _build_synthetic_file_lines(
    rel_path: str, specs: tuple[prd.HookInsertionSpec, ...]
) -> list[str]:
    """Construct a small synthetic file that places every spec's context and anchor at exact original lines."""
    file_specs = sorted(
        (s for s in specs if s.rel_path == rel_path),
        key=lambda s: s.original_line,
    )
    if not file_specs:
        return ["! synthetic untouched file"]

    max_line = max(
        s.original_line + len(s.context_after) + 5 for s in file_specs
    )
    if rel_path == "CMakeLists.txt":
        max_line = max(max_line, 246)

    is_fixed = rel_path.endswith(".f")
    default_line = (
        "C     synthetic line" if is_fixed else "! synthetic line"
    )
    lines = [f"{default_line} {i}" for i in range(1, max_line + 1)]

    for spec in file_specs:
        idx0 = spec.original_line - 1
        before_len = len(spec.context_before)
        for offset, ctx_line in enumerate(spec.context_before):
            lines[idx0 - before_len + offset] = ctx_line
        lines[idx0] = spec.anchor_text
        for offset, ctx_line in enumerate(spec.context_after):
            lines[idx0 + 1 + offset] = ctx_line

    if rel_path == "CMakeLists.txt":
        lines[178] = ")"
        lines[191] = "add_executable(libcheck"
        lines[192] = "const.f90"
        lines[237] = ")"
        lines[242] = "add_executable(header2matr header2matr.f90)"

    return lines


def create_synthetic_vendor_source(root: Path) -> dict[str, str]:
    """Create a small synthetic vendor tree with exact line anchors and return its pin map."""
    root.mkdir(parents=True, exist_ok=True)
    synthetic_pins: dict[str, str] = {}

    for rel_path in sorted(prd.PINNED_ORIGINAL_FILE_SHA256):
        lines = _build_synthetic_file_lines(rel_path, prd.HOOK_INSERTION_SPECS)
        text = "\n".join(lines) + "\n"
        (root / rel_path).write_text(text, encoding="utf-8")
        synthetic_pins[rel_path] = _sha256_text(text)

    untouched_text = "module untouched_helper\n  implicit none\nend module untouched_helper\n"
    (root / "untouched_helper.f90").write_text(untouched_text, encoding="utf-8")
    return synthetic_pins


class TestPrepareRefmacDiagnostic(unittest.TestCase):
    def test_hook_specs_fixed_form_column_limit_and_unique_ids(self) -> None:
        seen_ids: set[str] = set()
        for spec in prd.HOOK_INSERTION_SPECS:
            self.assertNotIn(spec.source_hook_id, seen_ids)
            seen_ids.add(spec.source_hook_id)
            self.assertIn(spec.phase, ("before", "after"))
            if spec.rel_path.endswith(".f"):
                for line in spec.inserted_lines:
                    self.assertLessEqual(
                        len(line),
                        72,
                        f"Fixed-form line in {spec.source_hook_id} exceeds 72 chars: {line!r}",
                    )

        expected_lsq_ids = {
            "L_import",
            "L0",
            "L1",
            "L2",
            "L3",
            "L4",
            "L5",
            "L6a",
            "L6b",
            "L7",
            "L8",
            "L9_work",
            "L9_free",
            "final_carrier_work",
            "final_carrier_free",
            "L_end",
        }
        actual_lsq_ids = {
            s.source_hook_id
            for s in prd.HOOK_INSERTION_SPECS
            if s.rel_path == "subcf_scale1.f"
        }
        self.assertEqual(actual_lsq_ids, expected_lsq_ids)

    def test_synthetic_preparation_preserves_subsequence_and_manifest_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            src_dir = tmp_path / "vendor_src"
            allowed_prep = tmp_path / "allowed_prep"
            allowed_prep.mkdir()
            out_dir = allowed_prep / "prepared_out"
            pins = create_synthetic_vendor_source(src_dir)

            manifest = prd.prepare_refmac_diagnostic_source(
                src_dir,
                out_dir,
                verify_git=False,
                pinned_hashes=pins,
                _allowed_output_roots=(allowed_prep,),
            )

            self.assertTrue(manifest["preparation_only"])
            self.assertFalse(manifest["native_execution_performed"])
            self.assertEqual(manifest["schema_id"], prd.MANIFEST_SCHEMA_ID)
            self.assertEqual(
                manifest["source_verification_status"],
                "unverified_synthetic_source",
            )
            self.assertEqual(
                manifest["upstream_source"]["git_verification"]["verification_status"],
                "unverified_synthetic_source",
            )
            self.assertFalse(
                manifest["upstream_source"]["git_verification"]["all_tracked_blobs_verified"]
            )

            manifest_file = out_dir / prd.MANIFEST_FILENAME
            patch_file = out_dir / prd.PATCH_FILENAME
            self.assertTrue(manifest_file.is_file())
            self.assertTrue(patch_file.is_file())

            disk_manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            self.assertEqual(manifest, disk_manifest)

            patch_bytes = patch_file.read_bytes()
            self.assertEqual(
                hashlib.sha256(patch_bytes).hexdigest(),
                manifest["unified_patch"]["sha256"],
            )

            for mod_name, mod_src in (
                ("trace_writer.f90", prd.TRACE_WRITER_SOURCE),
                ("trace_hooks.f90", prd.TRACE_HOOKS_SOURCE),
            ):
                copied_bytes = (out_dir / mod_name).read_bytes()
                self.assertEqual(copied_bytes, mod_src.read_bytes())
                self.assertEqual(
                    hashlib.sha256(copied_bytes).hexdigest(),
                    manifest["diagnostic_modules"][mod_name]["sha256"],
                )

            self.assertEqual(len(manifest["source_inventory"]), 6)
            self.assertEqual(len(manifest["output_source_inventory"]), 6)
            for inv_item in manifest["source_inventory"]:
                raw_src = (src_dir / inv_item["path"]).read_bytes()
                self.assertEqual(
                    inv_item["git_blob_id"],
                    prd.compute_git_blob_sha1(raw_src),
                )
                self.assertFalse(inv_item["commit_blob_verified"])

            for mod_entry in manifest["modified_vendor_files"]:
                rel = mod_entry["path"]
                orig_bytes = (src_dir / rel).read_bytes()
                patched_bytes = (out_dir / rel).read_bytes()
                self.assertEqual(
                    hashlib.sha256(orig_bytes).hexdigest(),
                    mod_entry["before_sha256"],
                )
                self.assertEqual(
                    hashlib.sha256(patched_bytes).hexdigest(),
                    mod_entry["after_sha256"],
                )
                orig_lines = orig_bytes.decode("utf-8").splitlines()
                patched_lines = patched_bytes.decode("utf-8").splitlines()
                prd.verify_original_is_ordered_subsequence(
                    orig_lines,
                    patched_lines,
                    mod_entry["inserted_line_count"],
                )

            untouched_orig = (src_dir / "untouched_helper.f90").read_bytes()
            untouched_out = (out_dir / "untouched_helper.f90").read_bytes()
            self.assertEqual(untouched_orig, untouched_out)

    def test_changed_source_pin_rejected_before_output_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            src_dir = tmp_path / "vendor_src"
            allowed_prep = tmp_path / "allowed_prep"
            allowed_prep.mkdir()
            out_dir = allowed_prep / "prepared_out"
            pins = create_synthetic_vendor_source(src_dir)

            bad_pins = dict(pins)
            bad_pins["subcf_scale1.f"] = "0" * 64

            with self.assertRaisesRegex(
                ValueError, "Pinned source SHA-256 mismatch for subcf_scale1.f"
            ):
                prd.prepare_refmac_diagnostic_source(
                    src_dir,
                    out_dir,
                    verify_git=False,
                    pinned_hashes=bad_pins,
                    _allowed_output_roots=(allowed_prep,),
                )
            self.assertFalse(out_dir.exists())

    def test_existing_and_overlapping_and_symlink_destinations_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            src_dir = tmp_path / "vendor_src"
            allowed_prep = tmp_path / "allowed_prep"
            allowed_prep.mkdir()
            pins = create_synthetic_vendor_source(src_dir)

            existing_out = allowed_prep / "existing_out"
            existing_out.mkdir()
            with self.assertRaises(FileExistsError):
                prd.prepare_refmac_diagnostic_source(
                    src_dir,
                    existing_out,
                    verify_git=False,
                    pinned_hashes=pins,
                    _allowed_output_roots=(allowed_prep,),
                )

            # Existing ancestor output path raises FileExistsError before overlap check
            with self.assertRaises(FileExistsError):
                prd.prepare_refmac_diagnostic_source(
                    src_dir,
                    tmp_path,
                    verify_git=False,
                    pinned_hashes=pins,
                    _allowed_output_roots=(allowed_prep,),
                )

            # Fresh nested output inside source reaches overlap rejection
            nested_out = src_dir / "nested_out"
            with self.assertRaisesRegex(ValueError, "must not overlap"):
                prd.prepare_refmac_diagnostic_source(
                    src_dir,
                    nested_out,
                    verify_git=False,
                    pinned_hashes=pins,
                    _allowed_output_roots=(allowed_prep,),
                )
            self.assertFalse(nested_out.exists())

            # Symlink source path is rejected
            symlink_src = tmp_path / "symlink_src"
            symlink_src.symlink_to(src_dir)
            fresh_out = allowed_prep / "fresh_out"
            with self.assertRaisesRegex(ValueError, "Symlink component rejected"):
                prd.prepare_refmac_diagnostic_source(
                    symlink_src,
                    fresh_out,
                    verify_git=False,
                    pinned_hashes=pins,
                    _allowed_output_roots=(allowed_prep,),
                )
            self.assertFalse(fresh_out.exists())

            # Symlink destination parent component is rejected
            real_dest_parent = tmp_path / "real_dest_parent"
            real_dest_parent.mkdir()
            symlink_dest_parent = allowed_prep / "symlink_dest_parent"
            symlink_dest_parent.symlink_to(real_dest_parent)
            symlink_out = symlink_dest_parent / "fresh_out"
            with self.assertRaisesRegex(ValueError, "Symlink component rejected"):
                prd.prepare_refmac_diagnostic_source(
                    src_dir,
                    symlink_out,
                    verify_git=False,
                    pinned_hashes=pins,
                    _allowed_output_roots=(allowed_prep,),
                )
            self.assertFalse((real_dest_parent / "fresh_out").exists())

    def test_missing_and_duplicate_anchors_rejected_before_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            src_dir = tmp_path / "vendor_src"
            allowed_prep = tmp_path / "allowed_prep"
            allowed_prep.mkdir()
            out_dir = allowed_prep / "prepared_out"
            create_synthetic_vendor_source(src_dir)

            # Mutate anchor line in subcf_scale1.f and update pin so hash check passes
            subcf_path = src_dir / "subcf_scale1.f"
            lines = subcf_path.read_text(encoding="utf-8").splitlines()
            lines[93] = "      CALL SOMETHING_ELSE(N_REFINED_ATOMS)"
            mutated_text = "\n".join(lines) + "\n"
            subcf_path.write_text(mutated_text, encoding="utf-8")

            pins = {
                rel: hashlib.sha256((src_dir / rel).read_bytes()).hexdigest()
                for rel in prd.PINNED_ORIGINAL_FILE_SHA256
            }
            with self.assertRaisesRegex(ValueError, "Missing anchor for hook 'L0'"):
                prd.prepare_refmac_diagnostic_source(
                    src_dir,
                    out_dir,
                    verify_git=False,
                    pinned_hashes=pins,
                    _allowed_output_roots=(allowed_prep,),
                )
            self.assertFalse(out_dir.exists())

            # Restore line 94, extend fixture past index 501, and duplicate context + anchor
            lines = _build_synthetic_file_lines("subcf_scale1.f", prd.HOOK_INSERTION_SPECS)
            while len(lines) <= 505:
                lines.append(f"C     synthetic line {len(lines) + 1}")
            lines[499] = "      IF(LREFIN.AND.REFS.EQ.'LSQF') IMODE = 2"
            lines[500] = "      CALL FIND_NREFINED_ATOMS(N_REFINED_ATOMS)"
            lines[501] = "      DO     I=1,NREF"
            dup_text = "\n".join(lines) + "\n"
            subcf_path.write_text(dup_text, encoding="utf-8")
            pins["subcf_scale1.f"] = _sha256_text(dup_text)

            with self.assertRaisesRegex(ValueError, "Duplicate anchor matches"):
                prd.prepare_refmac_diagnostic_source(
                    src_dir,
                    out_dir,
                    verify_git=False,
                    pinned_hashes=pins,
                    _allowed_output_roots=(allowed_prep,),
                )
            self.assertFalse(out_dir.exists())

    def test_vendor_git_verification_rejects_wrong_commit_or_dirty_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src_dir = Path(tmp).resolve()

            def fake_run_wrong_commit(argv, **kwargs):
                return subprocess.CompletedProcess(
                    argv, 0, stdout="deadbeef" * 5 + "\n", stderr=""
                )

            with mock.patch.object(prd.subprocess, "run", side_effect=fake_run_wrong_commit):
                with self.assertRaisesRegex(ValueError, "Upstream git commit mismatch"):
                    prd.verify_vendor_git_checkout(src_dir)

            responses = [
                subprocess.CompletedProcess([], 0, stdout=prd.UPSTREAM_GIT_COMMIT + "\n", stderr=""),
                subprocess.CompletedProcess([], 0, stdout=prd.UPSTREAM_GIT_COMMIT + "\n", stderr=""),
                subprocess.CompletedProcess([], 0, stdout=" M subcf_scale1.f\n", stderr=""),
            ]
            with mock.patch.object(prd.subprocess, "run", side_effect=responses):
                with self.assertRaisesRegex(ValueError, "Vendor git working tree is not clean"):
                    prd.verify_vendor_git_checkout(src_dir)

            # Reject symlink (120000) or gitlink/submodule (160000 commit) in commit tree
            bad_tree_responses = [
                subprocess.CompletedProcess([], 0, stdout=prd.UPSTREAM_GIT_COMMIT + "\n", stderr=""),
                subprocess.CompletedProcess([], 0, stdout=prd.UPSTREAM_GIT_COMMIT + "\n", stderr=""),
                subprocess.CompletedProcess([], 0, stdout="", stderr=""),
                subprocess.CompletedProcess(
                    [],
                    0,
                    stdout=b"120000 blob " + (b"a" * 40) + b"\tsymlink_file.f90\x00",
                    stderr=b"",
                ),
            ]
            with mock.patch.object(prd.subprocess, "run", side_effect=bad_tree_responses):
                with self.assertRaisesRegex(ValueError, "Unsupported git tree entry"):
                    prd.verify_vendor_git_checkout(src_dir)

    def test_modified_non_pinned_file_rejected_even_when_git_status_is_clean(self) -> None:
        """Verify #1129: full commit-tree blob SHA-1 check catches modified non-pinned files."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            src_dir = tmp_path / "vendor_src"
            allowed_prep = tmp_path / "allowed_prep"
            allowed_prep.mkdir()
            pins = create_synthetic_vendor_source(src_dir)

            tracked_files = sorted(
                [*prd.PINNED_ORIGINAL_FILE_SHA256.keys(), "untouched_helper.f90"]
            )
            ls_tree_chunks: list[bytes] = []
            for rel in tracked_files:
                blob_sha1 = prd.compute_git_blob_sha1((src_dir / rel).read_bytes())
                ls_tree_chunks.append(
                    f"100644 blob {blob_sha1}\t{rel}\x00".encode("utf-8")
                )
            ls_tree_payload = b"".join(ls_tree_chunks)

            def make_git_responses() -> list[subprocess.CompletedProcess[Any]]:
                return [
                    subprocess.CompletedProcess(
                        [], 0, stdout=prd.UPSTREAM_GIT_COMMIT + "\n", stderr=""
                    ),
                    subprocess.CompletedProcess(
                        [], 0, stdout=prd.UPSTREAM_GIT_COMMIT + "\n", stderr=""
                    ),
                    # git status --porcelain returns clean (e.g. assume-unchanged / skip-worktree)
                    subprocess.CompletedProcess([], 0, stdout="", stderr=""),
                    subprocess.CompletedProcess(
                        [], 0, stdout=ls_tree_payload, stderr=b""
                    ),
                ]

            # 1. Unmodified tree passes full commit-blob verification
            verified_out = allowed_prep / "verified_out"
            with mock.patch.object(
                prd.subprocess, "run", side_effect=make_git_responses()
            ):
                manifest = prd.prepare_refmac_diagnostic_source(
                    src_dir,
                    verified_out,
                    verify_git=True,
                    pinned_hashes=pins,
                    _allowed_output_roots=(allowed_prep,),
                )
            self.assertEqual(
                manifest["source_verification_status"],
                "verified_upstream_commit_tree",
            )
            self.assertTrue(
                manifest["upstream_source"]["git_verification"]["all_tracked_blobs_verified"]
            )
            for item in manifest["source_inventory"]:
                self.assertTrue(item["commit_blob_verified"])

            # 2. Mutate non-pinned untouched_helper.f90 while keeping all 5 SHA-256 pins intact
            # and keeping git status --porcelain clean
            helper_path = src_dir / "untouched_helper.f90"
            original_helper_bytes = helper_path.read_bytes()
            helper_path.write_text(
                "module untouched_helper\n  ! covertly modified line\nend module untouched_helper\n",
                encoding="utf-8",
            )
            mutated_out = allowed_prep / "mutated_out"
            with mock.patch.object(
                prd.subprocess, "run", side_effect=make_git_responses()
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "Pinned commit blob mismatch for untouched_helper.f90",
                ):
                    prd.prepare_refmac_diagnostic_source(
                        src_dir,
                        mutated_out,
                        verify_git=True,
                        pinned_hashes=pins,
                        _allowed_output_roots=(allowed_prep,),
                    )
            self.assertFalse(mutated_out.exists())

            # Restore helper and verify extra untracked/ignored file on disk is also rejected
            helper_path.write_bytes(original_helper_bytes)
            extra_file = src_dir / "ignored_extra.f90"
            extra_file.write_text("! extra ignored file\n", encoding="utf-8")
            extra_out = allowed_prep / "extra_out"
            with mock.patch.object(
                prd.subprocess, "run", side_effect=make_git_responses()
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "Unexpected untracked or ignored files in source tree",
                ):
                    prd.prepare_refmac_diagnostic_source(
                        src_dir,
                        extra_out,
                        verify_git=True,
                        pinned_hashes=pins,
                        _allowed_output_roots=(allowed_prep,),
                    )
            self.assertFalse(extra_out.exists())
            extra_file.unlink()

            # 3. End-to-end check with a real temporary git repo and assume-unchanged
            git_bin = shutil.which("git")
            if git_bin is not None:
                git_env = prd._git_clean_environment()
                git_env["GIT_AUTHOR_NAME"] = "Test"
                git_env["GIT_AUTHOR_EMAIL"] = "test@example.com"
                git_env["GIT_COMMITTER_NAME"] = "Test"
                git_env["GIT_COMMITTER_EMAIL"] = "test@example.com"
                subprocess.run(
                    [git_bin, "-C", str(src_dir), "init", "-q"],
                    env=git_env,
                    check=True,
                )
                subprocess.run(
                    [git_bin, "-C", str(src_dir), "add", "--", *tracked_files],
                    env=git_env,
                    check=True,
                )
                subprocess.run(
                    [git_bin, "-C", str(src_dir), "commit", "-q", "-m", "init"],
                    env=git_env,
                    check=True,
                )
                head_commit = subprocess.run(
                    [git_bin, "-C", str(src_dir), "rev-parse", "HEAD"],
                    capture_output=True,
                    text=True,
                    env=git_env,
                    check=True,
                ).stdout.strip()
                subprocess.run(
                    [git_bin, "-C", str(src_dir), "tag", prd.UPSTREAM_GIT_TAG],
                    env=git_env,
                    check=True,
                )
                # Hide modification of non-pinned file from git status using --assume-unchanged
                subprocess.run(
                    [
                        git_bin,
                        "-C",
                        str(src_dir),
                        "update-index",
                        "--assume-unchanged",
                        "untouched_helper.f90",
                    ],
                    env=git_env,
                    check=True,
                )
                helper_path.write_text(
                    "module untouched_helper\n  ! hidden by assume-unchanged\nend module untouched_helper\n",
                    encoding="utf-8",
                )
                status_check = subprocess.run(
                    [
                        git_bin,
                        "-C",
                        str(src_dir),
                        "status",
                        "--porcelain",
                        "--untracked-files=all",
                    ],
                    capture_output=True,
                    text=True,
                    env=git_env,
                    check=True,
                )
                self.assertEqual(status_check.stdout, "")

                _, tree_entries = prd.verify_vendor_git_checkout(
                    src_dir,
                    expected_commit=head_commit,
                    expected_tag=prd.UPSTREAM_GIT_TAG,
                )
                with self.assertRaisesRegex(
                    ValueError,
                    "Pinned commit blob mismatch for untouched_helper.f90",
                ):
                    prd.collect_and_verify_source_inventory(
                        src_dir,
                        list(tree_entries),
                        pinned_hashes=pins,
                        commit_tree_entries=tree_entries,
                        require_commit_blobs=True,
                    )

    def test_output_boundary_enforces_authorized_preparation_areas_and_rejects_escapes(
        self,
    ) -> None:
        """Verify #1130: output must be strictly inside authorized preparation areas."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            src_dir = tmp_path / "vendor_src"
            allowed_prep = tmp_path / ".orchestration" / "evidence" / "601-instrumented-build"
            allowed_prep.mkdir(parents=True)
            pins = create_synthetic_vendor_source(src_dir)

            # 1. Default boundary check rejects arbitrary temp or installation-like paths
            outside_default = tmp_path / "outside_default_out"
            with self.assertRaisesRegex(
                ValueError, "outside authorized diagnostic preparation areas"
            ):
                prd.prepare_refmac_diagnostic_source(
                    src_dir,
                    outside_default,
                    verify_git=False,
                    pinned_hashes=pins,
                )
            self.assertFalse(outside_default.exists())

            install_dir_parent = tmp_path / "opt" / "ccp4-9.0.015"
            install_dir_parent.mkdir(parents=True)
            install_like_out = install_dir_parent / "refmac5_instrumented"
            with self.assertRaisesRegex(
                ValueError, "outside authorized diagnostic preparation areas"
            ):
                prd.prepare_refmac_diagnostic_source(
                    src_dir,
                    install_like_out,
                    verify_git=False,
                    pinned_hashes=pins,
                    _allowed_output_roots=(allowed_prep,),
                )
            self.assertFalse(install_like_out.exists())

            # 2. Output inside allowed area succeeds
            valid_out = allowed_prep / "prepared_tree"
            manifest = prd.prepare_refmac_diagnostic_source(
                src_dir,
                valid_out,
                verify_git=False,
                pinned_hashes=pins,
                _allowed_output_roots=(allowed_prep,),
            )
            self.assertTrue((valid_out / prd.MANIFEST_FILENAME).is_file())
            self.assertEqual(manifest["schema_id"], prd.MANIFEST_SCHEMA_ID)

            # 3. Symlink inside allowed area pointing outside is rejected without side effects
            outside_target = tmp_path / "outside_target"
            outside_target.mkdir()
            escape_symlink = allowed_prep / "escape_link"
            escape_symlink.symlink_to(outside_target)
            escaped_out = escape_symlink / "escaped_tree"
            with self.assertRaisesRegex(ValueError, "Symlink component rejected"):
                prd.prepare_refmac_diagnostic_source(
                    src_dir,
                    escaped_out,
                    verify_git=False,
                    pinned_hashes=pins,
                    _allowed_output_roots=(allowed_prep,),
                )
            self.assertFalse((outside_target / "escaped_tree").exists())

            # 4. Symlinked allowed root itself is rejected
            symlink_allowed_root = tmp_path / "symlink_allowed_root"
            symlink_allowed_root.symlink_to(outside_target)
            with self.assertRaisesRegex(
                ValueError, "Symlink component rejected in allowed output root"
            ):
                prd.prepare_refmac_diagnostic_source(
                    src_dir,
                    outside_target / "via_symlink_root",
                    verify_git=False,
                    pinned_hashes=pins,
                    _allowed_output_roots=(symlink_allowed_root,),
                )
            self.assertFalse((outside_target / "via_symlink_root").exists())

            # 5. discover_authorized_preparation_roots derives PRIMARY + worktree areas
            fake_wt = tmp_path / "protstruct_review-wt-999"
            fake_primary = tmp_path / "protstruct_review"
            fake_primary_git = fake_primary / ".git"
            fake_wt.mkdir()
            fake_primary_git.mkdir(parents=True)
            git_rev_responses = [
                subprocess.CompletedProcess([], 0, stdout=str(fake_wt) + "\n", stderr=""),
                subprocess.CompletedProcess(
                    [], 0, stdout=str(fake_primary_git) + "\n", stderr=""
                ),
            ]
            with mock.patch.object(prd.subprocess, "run", side_effect=git_rev_responses):
                roots = prd.discover_authorized_preparation_roots(fake_wt)
            self.assertIn(
                fake_wt / ".orchestration" / "evidence" / "601-instrumented-build",
                roots,
            )
            self.assertIn(fake_wt / ".temp", roots)
            self.assertIn(
                fake_primary / ".orchestration" / "evidence" / "601-instrumented-build",
                roots,
            )
            self.assertIn(fake_primary / ".temp", roots)

    def test_source_walk_permission_error_refused_before_output_creation(self) -> None:
        """Verify #1136: os.walk traversal errors raise contextual ValueError before output creation."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            src_dir = tmp_path / "vendor_src"
            allowed_prep = tmp_path / "allowed_prep"
            allowed_prep.mkdir()
            pins = create_synthetic_vendor_source(src_dir)
            unreadable_sub = src_dir / "unreadable_subdir"
            unreadable_sub.mkdir()

            real_scandir = os.scandir

            def fake_scandir(path: Any = ".") -> Any:
                if Path(path).resolve() == unreadable_sub:
                    raise PermissionError(
                        errno.EACCES, "Permission denied", str(unreadable_sub)
                    )
                return real_scandir(path)

            # 1. Unverified synthetic source inventory (verify_git=False)
            unverified_out = allowed_prep / "unverified_walk_err_out"
            with mock.patch.object(prd.os, "scandir", side_effect=fake_scandir):
                with self.assertRaisesRegex(
                    ValueError,
                    "Source directory traversal failed during unverified synthetic source inventory",
                ) as ctx_unverified:
                    prd.prepare_refmac_diagnostic_source(
                        src_dir,
                        unverified_out,
                        verify_git=False,
                        pinned_hashes=pins,
                        _allowed_output_roots=(allowed_prep,),
                    )
            self.assertIsInstance(ctx_unverified.exception.__cause__, PermissionError)
            self.assertFalse(unverified_out.exists())

            # 2. Verified extra-file inventory (verify_git=True)
            tracked_files = sorted(
                [*prd.PINNED_ORIGINAL_FILE_SHA256.keys(), "untouched_helper.f90"]
            )
            ls_tree_payload = b"".join(
                f"100644 blob {prd.compute_git_blob_sha1((src_dir / rel).read_bytes())}\t{rel}\x00".encode(
                    "utf-8"
                )
                for rel in tracked_files
            )
            git_responses = [
                subprocess.CompletedProcess(
                    [], 0, stdout=prd.UPSTREAM_GIT_COMMIT + "\n", stderr=""
                ),
                subprocess.CompletedProcess(
                    [], 0, stdout=prd.UPSTREAM_GIT_COMMIT + "\n", stderr=""
                ),
                subprocess.CompletedProcess([], 0, stdout="", stderr=""),
                subprocess.CompletedProcess([], 0, stdout=ls_tree_payload, stderr=b""),
            ]
            verified_out = allowed_prep / "verified_walk_err_out"
            with (
                mock.patch.object(prd.subprocess, "run", side_effect=git_responses),
                mock.patch.object(prd.os, "scandir", side_effect=fake_scandir),
            ):
                with self.assertRaisesRegex(
                    ValueError,
                    "Source directory traversal failed during verified extra-file inventory",
                ) as ctx_verified:
                    prd.prepare_refmac_diagnostic_source(
                        src_dir,
                        verified_out,
                        verify_git=True,
                        pinned_hashes=pins,
                        _allowed_output_roots=(allowed_prep,),
                    )
            self.assertIsInstance(ctx_verified.exception.__cause__, PermissionError)
            self.assertFalse(verified_out.exists())

    def test_static_invalid_row_latch_and_carrier_guard_clauses(self) -> None:
        """Verify #1119/#1133 static hook source and insertion-spec guard clauses."""
        hooks_src = prd.TRACE_HOOKS_SOURCE.read_text(encoding="utf-8")
        self.assertIn("lsq_numeric_invalid_latched", hooks_src)
        self.assertIn("subroutine latch_lsq_numeric_invalid", hooks_src)

        spec_by_id = {s.source_hook_id: s for s in prd.HOOK_INSERTION_SPECS}
        for guarded_id in ("L4", "L8", "L9_work", "L9_free", "final_carrier_free"):
            joined = "\n".join(spec_by_id[guarded_id].inserted_lines)
            self.assertIn("IF(trace_lsq_accumulators_valid()) THEN", joined)

        work_carrier_joined = "\n".join(spec_by_id["final_carrier_work"].inserted_lines)
        self.assertIn("IF(nrefa_this(1,NB1).GT.0.AND.", work_carrier_joined)
        self.assertIn("trace_lsq_accumulators_valid()) THEN", work_carrier_joined)

        for addition_id in ("L5", "L6a", "L6b"):
            joined = "\n".join(spec_by_id[addition_id].inserted_lines)
            self.assertIn("IF(trace_lsq_can_capture_addition()) THEN", joined)

    def test_static_bounded_hook_record_event_clauses(self) -> None:
        """Verify #1127/#1133 static per-slot event names and skipTest behavior without gfortran."""
        hooks_src = prd.TRACE_HOOKS_SOURCE.read_text(encoding="utf-8")
        self.assertIn('call trace_begin("lsq_coef_bin_bounds")', hooks_src)
        self.assertIn('call trace_begin("lsq_coef_part_scale")', hooks_src)
        self.assertIn('call trace_begin("completeness_bin_bounds")', hooks_src)
        self.assertIn('call trace_begin("completeness_summary_slot")', hooks_src)

        with mock.patch.object(shutil, "which", return_value=None):
            with self.assertRaises(unittest.SkipTest):
                self.test_invalid_row_then_valid_row_and_cross_call_carrier_contract()
            with self.assertRaises(unittest.SkipTest):
                self.test_bounded_hook_records_for_bins_20_26_27_and_500()

    def test_invalid_row_then_valid_row_and_cross_call_carrier_contract(self) -> None:
        """Verify #1119/#1128 dynamic compiled fixture for call-wide persistent invalidity latch and carrier guard."""
        gfortran = shutil.which("gfortran")
        if gfortran is None:
            self.skipTest(
                "gfortran compiler unavailable on PATH; dynamic Fortran hook fixture skipped"
            )

        driver_f90 = """\
program test_persistent_invalidity
  use protstruct_diagnostic_hooks, only: &
    trace_hook_lsq_l0_begin, trace_hook_lsq_l0_end, &
    trace_hook_lsq_l1, trace_hook_lsq_l2_no_freer, trace_hook_lsq_l2_with_freer, &
    trace_hook_lsq_l3, &
    trace_hook_lsq_l4_valid, trace_hook_lsq_l4_invalid, &
    trace_hook_lsq_l5_valid, trace_hook_lsq_l5_invalid, &
    trace_hook_lsq_l6a_valid, trace_hook_lsq_l6a_invalid, &
    trace_hook_lsq_l6b_valid, trace_hook_lsq_l6b_invalid, &
    trace_hook_lsq_l7, trace_hook_lsq_l8_valid, trace_hook_lsq_l8_invalid, &
    trace_hook_lsq_l9_work_valid, trace_hook_lsq_l9_work_invalid, &
    trace_hook_lsq_l9_free_valid, &
    trace_hook_lsq_final_carrier_work_valid, trace_hook_lsq_final_carrier_work_invalid, &
    trace_hook_lsq_final_carrier_free_valid, &
    trace_hook_lsq_l_end, trace_lsq_accumulators_valid, trace_lsq_can_capture_addition, &
    trace_hook_normal_termination
  implicit none

  integer, parameter :: nbm = 2
  integer :: ihh(3)
  real :: sminb(2), smaxb(2)
  integer :: nrefa_this(2, nbm), nrefa(2, nbm), nrefm(2, nbm)
  real :: dummy_acc(2, nbm)
  real :: hrfac_shell_work(2), rfactor_work
  real :: hrfac_shell_free(2), rfactor_free

  sminb = (/ 0.0, 0.0 /)
  smaxb = (/ 0.5, 0.5 /)
  nrefa_this = 0
  nrefa = 2
  nrefm = 0
  dummy_acc = 0.0
  hrfac_shell_work = -777.0
  rfactor_work = -777.0
  hrfac_shell_free = -888.0
  rfactor_free = -888.0

  ! Call 1: Row 1 reaches addition without L3 (invalid), Row 2 has valid L3
  call trace_hook_lsq_l0_begin( &
    2, 2, 0, 1, 1, 2, 0, 100, 10, 1, 1, .false., 'LSQF', .false., .true., &
    'XR', .false., .false., sminb, smaxb, 1.0, 0.0, .false., .false., &
    .false., .false., .false., .false., .false.)
  call trace_hook_lsq_l0_end()

  ! Row 1: L3 does NOT run (e.g. NaN SO bypasses SO > 0 and SO <= 0)
  ihh = (/ 1, 0, 0 /)
  call trace_hook_lsq_l1(1)
  call trace_hook_lsq_l2_no_freer(1, ihh, 10.0, -999.0, 0, 1, 0.04, 0.2, 0.0)
  if (trace_lsq_accumulators_valid()) then
    call trace_hook_lsq_l4_valid(1, 1, 1, sminb(1), smaxb(1), nrefa_this(1,1), &
      0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
  else
    call trace_hook_lsq_l4_invalid(1, 1, 1, sminb(1), smaxb(1), nrefa_this(1,1))
  end if
  nrefa_this(1,1) = nrefa_this(1,1) + 1
  if (trace_lsq_can_capture_addition()) then
    error stop "Row 1 must not allow valid L5 capture without L3"
  else
    call trace_hook_lsq_l5_invalid(1, 1, 1, nrefa_this(1,1))
  end if
  if (trace_lsq_can_capture_addition()) then
    error stop "Row 1 must not allow valid L6a capture"
  else
    call trace_hook_lsq_l6a_invalid(1, 2, 1, nrefa_this(1,2))
  end if
  nrefa_this(1,2) = nrefa_this(1,2) + 1
  if (trace_lsq_can_capture_addition()) then
    error stop "Row 1 must not allow valid L6b capture"
  else
    call trace_hook_lsq_l6b_invalid(1, 2, 1, nrefa_this(1,2))
  end if
  call trace_hook_lsq_l7(1)

  ! Row 2: valid row where L3 runs, but call-wide invalidity must stay latched!
  ihh = (/ 0, 1, 0 /)
  call trace_hook_lsq_l1(2)
  call trace_hook_lsq_l2_no_freer(2, ihh, 20.0, 2.0, 0, 1, 0.04, 0.2, 0.0)
  call trace_hook_lsq_l3(2, 20.0, 18.0, 0.0, 2.0, 2.0, 2.0, 0.5, 2.0, 1.0, 1.0)
  if (trace_lsq_accumulators_valid()) then
    error stop "Row 2 L4 must remain latched invalid"
  else
    call trace_hook_lsq_l4_invalid(2, 1, 1, sminb(1), smaxb(1), nrefa_this(1,1))
  end if
  nrefa_this(1,1) = nrefa_this(1,1) + 1
  if (trace_lsq_can_capture_addition()) then
    error stop "Row 2 L5 must remain latched invalid"
  else
    call trace_hook_lsq_l5_invalid(2, 1, 1, nrefa_this(1,1))
  end if
  if (trace_lsq_can_capture_addition()) then
    error stop "Row 2 L6a must remain latched invalid"
  else
    call trace_hook_lsq_l6a_invalid(2, 2, 1, nrefa_this(1,2))
  end if
  nrefa_this(1,2) = nrefa_this(1,2) + 1
  if (trace_lsq_can_capture_addition()) then
    error stop "Row 2 L6b must remain latched invalid"
  else
    call trace_hook_lsq_l6b_invalid(2, 2, 1, nrefa_this(1,2))
  end if
  call trace_hook_lsq_l7(2)

  if (trace_lsq_accumulators_valid()) then
    error stop "L8 must remain latched invalid"
  else
    call trace_hook_lsq_l8_invalid(1, 2, nbm, nrefa_this, nrefa, nrefm)
  end if
  if (trace_lsq_accumulators_valid()) then
    error stop "L9_work must remain latched invalid"
  else
    call trace_hook_lsq_l9_work_invalid(1, 2, nrefa_this(1,1))
    call trace_hook_lsq_l9_work_invalid(2, 2, nrefa_this(1,2))
  end if
  if (nrefa_this(1,2) > 0 .and. trace_lsq_accumulators_valid()) then
    error stop "final_carrier_work must remain latched invalid"
  else
    call trace_hook_lsq_final_carrier_work_invalid(2, nrefa_this(1,2), nrefa(1,2))
  end if
  call trace_hook_lsq_l_end()

  ! Call 2: Follow-up invocation after invalid Call 1, where work partition is EMPTY
  ! (nrefa_this(1,NB1) == 0) and only a valid free reflection is processed.
  ! Native subcf_scale1.f leaves HRFAC_SHELL_WORK(NB1) untouched on empty-work calls,
  ! whereas free-empty explicitly assigns hrfac_shell_free(i) = 0.0.
  nrefa_this = 0
  nrefa(1, :) = 0
  nrefa(2, :) = 1
  call trace_hook_lsq_l0_begin( &
    1, 1, 0, 1, 1, 2, 0, 100, 10, 1, 1, .false., 'LSQF', .true., .true., &
    'XR', .false., .false., sminb, smaxb, 1.0, 0.0, .false., .false., &
    .false., .false., .false., .false., .false.)
  call trace_hook_lsq_l0_end()

  ihh = (/ 0, 0, 1 /)
  call trace_hook_lsq_l1(1)
  call trace_hook_lsq_l2_with_freer(1, ihh, 15.0, 1.5, 0, 2, 0.0, 0.04, 0.2, 0.0)
  call trace_hook_lsq_l3(1, 15.0, 12.0, 0.0, 1.5, 1.5, 1.5, 0.6666667, 3.0, 2.0, 1.0)
  call trace_hook_lsq_l4_valid(1, 1, 2, sminb(1), smaxb(1), nrefa_this(2,1), &
    0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
  nrefa_this(2,1) = 1
  call trace_hook_lsq_l5_valid(1, 1, 2, nrefa_this(2,1), &
    3.0, 225.0, 180.0, 144.0, 12.0, 15.0, 1.5, 2.0, 4.0, 10.0, 100.0)
  call trace_hook_lsq_l6a_valid(1, 2, 2, nrefa_this(2,2), &
    0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
  nrefa_this(2,2) = 1
  call trace_hook_lsq_l6b_valid(1, 2, 2, nrefa_this(2,2), &
    3.0, 225.0, 180.0, 144.0, 12.0, 15.0, 1.5, 2.0, 4.0, 10.0, 100.0)
  call trace_hook_lsq_l7(1)
  call trace_hook_lsq_l8_valid(1, 2, nbm, nrefa_this, nrefa, nrefm, &
    dummy_acc, dummy_acc, dummy_acc, dummy_acc, dummy_acc, dummy_acc, &
    dummy_acc, dummy_acc, dummy_acc, dummy_acc, dummy_acc, 0.0, 4.0)
  call trace_hook_lsq_l9_free_valid(1, 2, nrefa_this(2,1), 3.0, 15.0, 0.2)
  call trace_hook_lsq_l9_free_valid(2, 2, nrefa_this(2,2), 3.0, 15.0, 0.2)
  hrfac_shell_free = 0.2
  rfactor_work = hrfac_shell_work(2)
  if (nrefa_this(1,2) > 0 .and. trace_lsq_accumulators_valid()) then
    call trace_hook_lsq_final_carrier_work_valid(2, nrefa_this(1,2), nrefa(1,2), &
      hrfac_shell_work(2), rfactor_work)
  else
    call trace_hook_lsq_final_carrier_work_invalid(2, nrefa_this(1,2), nrefa(1,2))
  end if
  rfactor_free = hrfac_shell_free(2)
  call trace_hook_lsq_final_carrier_free_valid(2, nrefa_this(2,2), nrefa(2,2), 1, &
    hrfac_shell_free(2), rfactor_free)
  call trace_hook_lsq_l_end()

  ! Call 3: Valid work reflection, empty free in current call (nrefa_this(2,NB1) == 0),
  ! but NREFA(2,NB1) > 0 from completeness; native explicitly assigns hrfac_shell_free(i) = 0.0.
  nrefa_this = 0
  nrefa(1, :) = 1
  nrefa(2, :) = 1
  call trace_hook_lsq_l0_begin( &
    1, 1, 0, 1, 1, 2, 0, 100, 10, 1, 1, .false., 'LSQF', .true., .true., &
    'XR', .false., .false., sminb, smaxb, 1.0, 0.0, .false., .false., &
    .false., .false., .false., .false., .false.)
  call trace_hook_lsq_l0_end()
  call trace_hook_lsq_l1(1)
  call trace_hook_lsq_l2_with_freer(1, ihh, 20.0, 2.0, 0, 1, 1.0, 0.04, 0.2, 0.0)
  call trace_hook_lsq_l3(1, 20.0, 16.0, 0.0, 2.0, 2.0, 2.0, 0.5, 4.0, 2.0, 1.0)
  call trace_hook_lsq_l4_valid(1, 1, 1, sminb(1), smaxb(1), nrefa_this(1,1), &
    0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
  nrefa_this(1,1) = 1
  call trace_hook_lsq_l5_valid(1, 1, 1, nrefa_this(1,1), &
    4.0, 400.0, 320.0, 256.0, 16.0, 20.0, 2.0, 2.0, 4.0, 10.0, 100.0)
  call trace_hook_lsq_l6a_valid(1, 2, 1, nrefa_this(1,2), &
    0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
  nrefa_this(1,2) = 1
  call trace_hook_lsq_l6b_valid(1, 2, 1, nrefa_this(1,2), &
    4.0, 400.0, 320.0, 256.0, 16.0, 20.0, 2.0, 2.0, 4.0, 10.0, 100.0)
  call trace_hook_lsq_l7(1)
  call trace_hook_lsq_l8_valid(1, 2, nbm, nrefa_this, nrefa, nrefm, &
    dummy_acc, dummy_acc, dummy_acc, dummy_acc, dummy_acc, dummy_acc, &
    dummy_acc, dummy_acc, dummy_acc, dummy_acc, dummy_acc, 4.0, 0.0)
  call trace_hook_lsq_l9_work_valid(1, 2, nrefa_this(1,1), 4.0, 20.0, 0.2)
  call trace_hook_lsq_l9_work_valid(2, 2, nrefa_this(1,2), 4.0, 20.0, 0.2)
  hrfac_shell_work = 0.2
  ! Native else branch for nrefa_this(2,i) == 0 explicitly zeroes hrfac_shell_free
  hrfac_shell_free = 0.0
  rfactor_work = hrfac_shell_work(2)
  if (nrefa_this(1,2) > 0 .and. trace_lsq_accumulators_valid()) then
    call trace_hook_lsq_final_carrier_work_valid(2, nrefa_this(1,2), nrefa(1,2), &
      hrfac_shell_work(2), rfactor_work)
  else
    call trace_hook_lsq_final_carrier_work_invalid(2, nrefa_this(1,2), nrefa(1,2))
  end if
  rfactor_free = hrfac_shell_free(2)
  call trace_hook_lsq_final_carrier_free_valid(2, nrefa_this(2,2), nrefa(2,2), 1, &
    hrfac_shell_free(2), rfactor_free)
  call trace_hook_lsq_l_end()

  call trace_hook_normal_termination()
end program test_persistent_invalidity
"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            driver_path = tmp_path / "driver.f90"
            exe_path = tmp_path / "driver"
            trace_path = tmp_path / "trace.jsonl"
            driver_path.write_text(driver_f90, encoding="utf-8")

            compile_proc = subprocess.run(
                [
                    gfortran,
                    "-O3",
                    "-J",
                    str(tmp_path),
                    str(prd.TRACE_WRITER_SOURCE),
                    str(prd.TRACE_HOOKS_SOURCE),
                    str(driver_path),
                    "-o",
                    str(exe_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                compile_proc.returncode,
                0,
                f"gfortran compile failed: {compile_proc.stderr}",
            )

            env = dict(os.environ)
            env["REFMAC_DIAGNOSTIC_TRACE"] = str(trace_path)
            run_proc = subprocess.run(
                [str(exe_path)],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            self.assertEqual(
                run_proc.returncode,
                0,
                f"driver execution failed: {run_proc.stderr}",
            )

            records = [
                json.loads(line)
                for line in trace_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(records[0]["record_type"], "header")
            self.assertEqual(records[-1]["record_type"], "writer_close")

            by_call_hook_row = {
                (r.get("call_id"), r.get("source_hook_id"), r.get("row_index")): r
                for r in records
                if "source_hook_id" in r and "row_index" in r
            }
            self.assertTrue(by_call_hook_row[(1, "L4", 1)]["numeric_capture_valid"])
            self.assertFalse(by_call_hook_row[(1, "L5", 1)]["numeric_capture_valid"])
            self.assertFalse(by_call_hook_row[(1, "L5", 1)]["l3_operands_ran"])
            self.assertNotIn("AFOMFC_after", by_call_hook_row[(1, "L5", 1)])
            self.assertEqual(
                by_call_hook_row[(1, "L7", 1)]["row_outcome"],
                "invalid_addition_without_operands",
            )
            self.assertTrue(by_call_hook_row[(1, "L7", 1)]["row_invalid_addition"])
            self.assertFalse(by_call_hook_row[(1, "L7", 1)]["numeric_capture_valid_for_call"])

            # Call 1 Row 2 had valid L3, but accumulators remain omitted while counts/terminal continue
            self.assertFalse(by_call_hook_row[(1, "L1", 2)]["numeric_capture_valid_for_call"])
            self.assertIn("YOS", by_call_hook_row[(1, "L3", 2)])
            self.assertFalse(by_call_hook_row[(1, "L4", 2)]["numeric_capture_valid"])
            self.assertNotIn("AFOMFC_before", by_call_hook_row[(1, "L4", 2)])
            self.assertFalse(by_call_hook_row[(1, "L5", 2)]["numeric_capture_valid"])
            self.assertTrue(by_call_hook_row[(1, "L5", 2)]["l3_operands_ran"])
            self.assertNotIn("AFOMFC_after", by_call_hook_row[(1, "L5", 2)])
            self.assertEqual(by_call_hook_row[(1, "L5", 2)]["nrefa_this_after"], 2)
            self.assertEqual(
                by_call_hook_row[(1, "L7", 2)]["row_outcome"],
                "included_shell_and_overall",
            )
            self.assertFalse(by_call_hook_row[(1, "L7", 2)]["row_invalid_addition"])
            self.assertFalse(by_call_hook_row[(1, "L7", 2)]["numeric_capture_valid_for_call"])

            l_end_call1 = next(
                r for r in records if r.get("source_hook_id") == "L_end" and r.get("call_id") == 1
            )
            self.assertFalse(l_end_call1["numeric_capture_valid"])
            self.assertTrue(l_end_call1["numeric_invalid_latched"])
            self.assertEqual(l_end_call1["numeric_invalid_first_row"], 1)
            self.assertEqual(l_end_call1["numeric_invalid_hook"], "L5")
            self.assertEqual(l_end_call1["expected_rows"], 2)
            self.assertEqual(l_end_call1["emitted_rows"], 2)

            # Call 2: empty work after invalid Call 1 must omit numeric work carrier
            work_carrier_call2 = next(
                r
                for r in records
                if r.get("source_hook_id") == "final_carrier_work" and r.get("call_id") == 2
            )
            self.assertFalse(work_carrier_call2["numeric_capture_valid"])
            self.assertFalse(work_carrier_call2["fresh_division_in_current_call"])
            self.assertEqual(work_carrier_call2["nrefa_this_work_NB1"], 0)
            self.assertNotIn("HRFAC_SHELL_WORK_NB1", work_carrier_call2)
            self.assertNotIn("RFACTOR_WORK", work_carrier_call2)

            expected_real32_0p2 = {
                "bits_hex": "3E4CCCCD",
                "decimal": "20000000298023223876953125E-26",
            }
            expected_real32_0p0 = {
                "bits_hex": "00000000",
                "decimal": "0.0",
            }

            free_carrier_call2 = next(
                r
                for r in records
                if r.get("source_hook_id") == "final_carrier_free" and r.get("call_id") == 2
            )
            self.assertTrue(free_carrier_call2["numeric_capture_valid"])
            self.assertTrue(free_carrier_call2["fresh_division_in_current_call"])
            self.assertEqual(
                free_carrier_call2["HRFAC_SHELL_FREE_NB1"], expected_real32_0p2
            )
            self.assertEqual(
                free_carrier_call2["RFACTOR_FREE"], expected_real32_0p2
            )

            # Call 3: empty free in current call explicitly assigns 0.0 in native subcf_scale1.f
            work_carrier_call3 = next(
                r
                for r in records
                if r.get("source_hook_id") == "final_carrier_work" and r.get("call_id") == 3
            )
            self.assertTrue(work_carrier_call3["numeric_capture_valid"])
            self.assertTrue(work_carrier_call3["fresh_division_in_current_call"])
            self.assertEqual(
                work_carrier_call3["HRFAC_SHELL_WORK_NB1"], expected_real32_0p2
            )
            self.assertEqual(
                work_carrier_call3["RFACTOR_WORK"], expected_real32_0p2
            )

            free_carrier_call3 = next(
                r
                for r in records
                if r.get("source_hook_id") == "final_carrier_free" and r.get("call_id") == 3
            )
            self.assertTrue(free_carrier_call3["numeric_capture_valid"])
            self.assertFalse(free_carrier_call3["fresh_division_in_current_call"])
            self.assertEqual(free_carrier_call3["nrefa_this_free_NB1"], 0)
            self.assertEqual(
                free_carrier_call3["HRFAC_SHELL_FREE_NB1"], expected_real32_0p0
            )
            self.assertEqual(
                free_carrier_call3["RFACTOR_FREE"], expected_real32_0p0
            )

    def test_bounded_hook_records_for_bins_20_26_27_and_500(self) -> None:
        """Verify #1127 dynamic compiled fixture for per-slot bounded records across BINS 20, 26, 27, and 500."""
        gfortran = shutil.which("gfortran")
        if gfortran is None:
            self.skipTest(
                "gfortran compiler unavailable on PATH; dynamic Fortran hook fixture skipped"
            )

        driver_f90 = """\
program test_bounded_bins
  use protstruct_diagnostic_hooks, only: &
    trace_hook_lsq_l0_begin, trace_hook_lsq_l0_freer, trace_hook_lsq_l0_aniso, &
    trace_hook_lsq_l0_bulk, trace_hook_lsq_l0_parts, trace_hook_lsq_l0_end, &
    trace_hook_lsq_l_end, &
    trace_hook_comp_c0, trace_hook_comp_c5_with_free, trace_hook_comp_c5_no_free, &
    trace_hook_comp_c_end, trace_hook_normal_termination
  implicit none

  ! Native agreem.f90 defines NMAXPART = 3; stress_parts = 70 is an artificial
  ! serialization stress fixture for trace_hook_lsq_l0_parts.
  integer, parameter :: nbm = 501, hmaxshell = 501, native_npart = 3, stress_parts = 70
  integer :: bins_list(4)
  integer :: idx, nbin, nb1, ibin, ip
  real :: sminb(nbm), smaxb(nbm), cell(6), cell_l(6), aniso(6), rcell(6)
  real :: scale_part(stress_parts), b_part(stress_parts)
  logical :: scale_part_flag(stress_parts), b_part_flag(stress_parts)
  integer :: nrefa(2, nbm), nrefm(2, nbm)
  integer :: hnref_work(hmaxshell), hnref_free(hmaxshell)
  integer :: hnref_obs(hmaxshell), hnref_all(hmaxshell)
  real :: hperc_refl(hmaxshell)

  bins_list = (/ 20, 26, 27, 500 /)
  cell = (/ 50.0, 60.0, 70.0, 90.0, 90.0, 90.0 /)
  cell_l = cell
  aniso = (/ 0.1, 0.2, 0.3, 0.0, 0.0, 0.0 /)
  rcell = (/ 0.02, 0.016, 0.014, 90.0, 90.0, 90.0 /)

  do ip = 1, stress_parts
    scale_part(ip) = 1.0 + real(ip) * 0.01
    b_part(ip) = real(ip) * 0.5
    scale_part_flag(ip) = .true.
    b_part_flag(ip) = .false.
  end do

  do idx = 1, 4
    nbin = bins_list(idx)
    nb1 = nbin + 1
    do ibin = 1, nb1
      sminb(ibin) = real(ibin - 1) * 0.001
      smaxb(ibin) = real(ibin) * 0.001
      nrefa(1, ibin) = 100 + ibin
      nrefa(2, ibin) = 10 + ibin
      nrefm(1, ibin) = 5 + ibin
      nrefm(2, ibin) = 1 + ibin
      hnref_work(ibin) = nrefa(1, ibin)
      hnref_free(ibin) = nrefa(2, ibin)
      hnref_obs(ibin) = nrefa(1, ibin) + nrefa(2, ibin)
      hnref_all(ibin) = hnref_obs(ibin) + nrefm(1, ibin) + nrefm(2, ibin)
      hperc_refl(ibin) = 95.0
    end do

    call trace_hook_lsq_l0_begin( &
      0, 1, native_npart, 1, nbin, nb1, 0, 500, 200, 1, 1, .true., 'LSQF', .true., .true., &
      'XR', .false., .false., sminb, smaxb, 1.0, 0.0, .true., .true., &
      .true., .true., .true., .true., .true.)
    call trace_hook_lsq_l0_freer(0)
    call trace_hook_lsq_l0_aniso(aniso, rcell)
    call trace_hook_lsq_l0_bulk(0.35, 45.0)
    call trace_hook_lsq_l0_parts(native_npart, scale_part, b_part, scale_part_flag, b_part_flag)
    call trace_hook_lsq_l0_end()
    call trace_hook_lsq_l_end()

    ! Completeness with free
    call trace_hook_comp_c0( &
      4, 0, 0, nbin, nb1, 1.5, .true., cell, cell_l, &
      0.02, 0.016, 0.014, 0.0, 0.0, 0.0, sminb, smaxb)
    call trace_hook_comp_c5_with_free( &
      nbin, nb1, nbm, hmaxshell, .true., nrefa, nrefm, &
      hnref_work, hnref_free, hnref_obs, hnref_all, hperc_refl, &
      nrefa(1, nb1), nrefa(2, nb1), 5.0)
    call trace_hook_comp_c_end()

    ! Completeness without free
    call trace_hook_comp_c0( &
      4, 0, 0, nbin, nb1, 1.5, .false., cell, cell_l, &
      0.02, 0.016, 0.014, 0.0, 0.0, 0.0, sminb, smaxb)
    call trace_hook_comp_c5_no_free( &
      nbin, nb1, nbm, hmaxshell, .false., nrefa, nrefm, &
      hnref_work, hnref_free, hnref_obs, hnref_all, hperc_refl, &
      nrefa(1, nb1), 0.0)
    call trace_hook_comp_c_end()
  end do

  ! Call 5: artificial serialization stress fixture with stress_parts = 70
  nbin = 20
  nb1 = 21
  call trace_hook_lsq_l0_begin( &
    0, 1, stress_parts, 1, nbin, nb1, 0, 500, 200, 1, 1, .true., 'LSQF', .true., .true., &
    'XR', .false., .false., sminb, smaxb, 1.0, 0.0, .true., .true., &
    .true., .true., .true., .true., .true.)
  call trace_hook_lsq_l0_parts(stress_parts, scale_part, b_part, scale_part_flag, b_part_flag)
  call trace_hook_lsq_l0_end()
  call trace_hook_lsq_l_end()

  call trace_hook_normal_termination()
end program test_bounded_bins
"""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp).resolve()
            driver_path = tmp_path / "driver_bins.f90"
            exe_path = tmp_path / "driver_bins"
            trace_path = tmp_path / "trace_bins.jsonl"
            driver_path.write_text(driver_f90, encoding="utf-8")

            compile_proc = subprocess.run(
                [
                    gfortran,
                    "-O3",
                    "-J",
                    str(tmp_path),
                    str(prd.TRACE_WRITER_SOURCE),
                    str(prd.TRACE_HOOKS_SOURCE),
                    str(driver_path),
                    "-o",
                    str(exe_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(
                compile_proc.returncode,
                0,
                f"gfortran compile failed: {compile_proc.stderr}",
            )

            env = dict(os.environ)
            env["REFMAC_DIAGNOSTIC_TRACE"] = str(trace_path)
            run_proc = subprocess.run(
                [str(exe_path)],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
            self.assertEqual(
                run_proc.returncode,
                0,
                f"driver execution failed: {run_proc.stderr}",
            )

            records = [
                json.loads(line)
                for line in trace_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(records[0]["record_type"], "header")
            self.assertEqual(records[-1]["record_type"], "writer_close")

            for rec in records:
                self.assertLessEqual(len(rec), 45)

            for call_id, expected_nbin in enumerate((20, 26, 27, 500), start=1):
                expected_nb1 = expected_nbin + 1
                l0_bounds = [
                    r
                    for r in records
                    if r.get("event") == "lsq_coef_bin_bounds"
                    and r.get("call_id") == call_id
                ]
                self.assertEqual(len(l0_bounds), expected_nb1)
                self.assertTrue(l0_bounds[-1]["is_overall_slot"])

                # Native agreem.f90 NMAXPART = 3
                l0_parts = [
                    r
                    for r in records
                    if r.get("event") == "lsq_coef_part_scale"
                    and r.get("call_id") == call_id
                ]
                self.assertEqual(len(l0_parts), 3)

                comp_call_with_free = 2 * call_id - 1
                comp_call_no_free = 2 * call_id

                c0_bounds_free = [
                    r
                    for r in records
                    if r.get("event") == "completeness_bin_bounds"
                    and r.get("call_id") == comp_call_with_free
                ]
                self.assertEqual(len(c0_bounds_free), expected_nb1)
                self.assertTrue(c0_bounds_free[-1]["is_overall_slot"])

                c5_sum_free = next(
                    r
                    for r in records
                    if r.get("event") == "completeness_summary"
                    and r.get("call_id") == comp_call_with_free
                )
                self.assertIn("NHREFL_FREE", c5_sum_free)

                c5_sum_nofree = next(
                    r
                    for r in records
                    if r.get("event") == "completeness_summary"
                    and r.get("call_id") == comp_call_no_free
                )
                self.assertNotIn("NHREFL_FREE", c5_sum_nofree)

                c5_slots_free = [
                    r
                    for r in records
                    if r.get("event") == "completeness_summary_slot"
                    and r.get("call_id") == comp_call_with_free
                ]
                self.assertEqual(len(c5_slots_free), expected_nb1)
                self.assertEqual(c5_slots_free[-1]["slot_index"], expected_nb1)
                self.assertTrue(c5_slots_free[-1]["is_overall_slot"])

            # Artificial serialization stress fixture (call_id == 5, stress_parts = 70)
            l0_parts_stress = [
                r
                for r in records
                if r.get("event") == "lsq_coef_part_scale"
                and r.get("call_id") == 5
            ]
            self.assertEqual(len(l0_parts_stress), 70)


if __name__ == "__main__":
    unittest.main()
