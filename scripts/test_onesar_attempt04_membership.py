#!/usr/bin/env python3
"""Focused hermetic unit tests for scripts/check_onesar_attempt04_membership.py (#1192).

Exercises the accepted retained Attempt 04 semantic consistency checker once via
its real public fixed-pin entrypoint (`verify_retained_attempt04`), captures the
verified in-memory bundle through a transparent loader spy without bypassing
pins or mutating on-disk files, and runs targeted negative controls across the
private pure helper seams (`_project_retained_products`, `_check_mtz_word_join`,
`_check_shared_hkls`, `_derive_trace_record_metadata`, and
`_verify_loaded_attempt04_bundle`).
"""

from __future__ import annotations

from contextlib import ExitStack
import copy
import hashlib
import os
from pathlib import Path
import socket
import stat
import struct
import subprocess
import sys
from typing import Any
import unittest
from unittest import mock
import urllib.request

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import check_onesar_attempt04_membership as checker  # noqa: E402
import onesar_rerun  # noqa: E402


REPO_ROOT = checker.REPO_ROOT


def _sha256_regular_file(path: Path) -> str:
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise AssertionError(f"Expected regular non-symlink file: {path}")
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def _no_process_or_network_stack() -> ExitStack:
    """Block subprocess execution and network operations during checker calls."""
    stack = ExitStack()
    for target_obj, attr_name in (
        (subprocess, "Popen"),
        (subprocess, "run"),
        (subprocess, "call"),
        (subprocess, "check_call"),
        (subprocess, "check_output"),
        (os, "system"),
        (socket, "create_connection"),
        (urllib.request, "urlopen"),
    ):
        stack.enter_context(
            mock.patch.object(
                target_obj,
                attr_name,
                side_effect=AssertionError(
                    f"Forbidden process/network call during hermetic membership check: "
                    f"{target_obj.__name__}.{attr_name}"
                ),
            )
        )
    return stack


def _patch_mtz_word(
    mtz_bytes: bytes, *, ncols: int, row_idx: int, col_idx: int, word_u32: int
) -> bytes:
    """Return a copy of mtz_bytes with one 4-byte IEEE-754 word replaced."""
    buf = bytearray(mtz_bytes)
    offset = 80 + 4 * (ncols * row_idx + col_idx)
    struct.pack_into("<I", buf, offset, word_u32)
    return bytes(buf)


def _read_mtz_word(
    mtz_bytes: bytes, *, ncols: int, row_idx: int, col_idx: int
) -> int:
    offset = 80 + 4 * (ncols * row_idx + col_idx)
    return int(struct.unpack_from("<I", mtz_bytes, offset)[0])


class TestRetainedAttempt04Membership(unittest.TestCase):
    """Hermetic unit and mutation suite for check_onesar_attempt04_membership.py."""

    real_loader: Any
    loader_call_count: int
    base_bundle: dict[str, Any]
    positive_summary: dict[str, Any]
    pins_before: dict[str, str]
    event_first_index: dict[str, int]

    @classmethod
    def setUpClass(cls) -> None:
        cls.pins_before = {}
        for rel_path, expected_sha in checker.PINS.items():
            full_path = REPO_ROOT / rel_path
            if not full_path.exists():
                raise AssertionError(
                    f"Missing required retained Attempt 04 artifact (fail, never skip): {full_path}"
                )
            actual_sha = _sha256_regular_file(full_path)
            if actual_sha != expected_sha:
                raise AssertionError(
                    f"Retained artifact SHA-256 mismatch before test suite for {rel_path}: "
                    f"expected {expected_sha}, got {actual_sha}"
                )
            cls.pins_before[rel_path] = actual_sha

        cls.real_loader = checker._load_pinned_attempt04_bundle
        cls.loader_call_count = 0
        captured_bundles: list[dict[str, Any]] = []

        def _transparent_loader_wrapper(
            repo_root: Path = REPO_ROOT,
        ) -> dict[str, Any]:
            cls.loader_call_count += 1
            bundle = cls.real_loader(repo_root)
            captured_bundles.append(bundle)
            return bundle

        with _no_process_or_network_stack():
            with mock.patch.object(
                checker,
                "_load_pinned_attempt04_bundle",
                side_effect=_transparent_loader_wrapper,
            ):
                cls.positive_summary = checker.verify_retained_attempt04(
                    REPO_ROOT
                )

        if cls.loader_call_count != 1 or len(captured_bundles) != 1:
            raise AssertionError(
                f"Expected real fixed-pin loader to be called exactly once, got {cls.loader_call_count}"
            )
        if checker._load_pinned_attempt04_bundle is not cls.real_loader:
            raise AssertionError(
                "Failed to restore checker._load_pinned_attempt04_bundle after setUpClass"
            )
        cls.base_bundle = captured_bundles[0]

        cls.event_first_index = {}
        for idx, (_, rec) in enumerate(cls.base_bundle["trace_records"]):
            ev = rec.get("event", rec.get("record_type"))
            if isinstance(ev, str) and ev not in cls.event_first_index:
                cls.event_first_index[ev] = idx

    @classmethod
    def tearDownClass(cls) -> None:
        for rel_path, before_sha in cls.pins_before.items():
            after_sha = _sha256_regular_file(REPO_ROOT / rel_path)
            if after_sha != before_sha:
                raise AssertionError(
                    f"Retained file mutated during test suite: {rel_path}"
                )

    def _clone_trace_with_record_copy(
        self, trace_idx: int
    ) -> tuple[list[tuple[int, dict[str, Any]]], dict[str, Any]]:
        """Shallow-copy trace_records list and deep-copy only the targeted record."""
        records = list(self.base_bundle["trace_records"])
        line_no, orig_rec = records[trace_idx]
        rec_copy = copy.deepcopy(orig_rec)
        records[trace_idx] = (line_no, rec_copy)
        return records, rec_copy

    def _run_project_with_overrides(self, **overrides: Any) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "retained_ledger": self.base_bundle["input_hkl_ledger"],
            "retained_residual_members": self.base_bundle["residual_members"],
            "retained_completeness_members": self.base_bundle[
                "completeness_members"
            ],
            "retained_native_bin_bounds": self.base_bundle["native_bin_bounds"],
            "retained_native_slot_records": self.base_bundle[
                "native_slot_records"
            ],
            "retained_completeness_slot_records": self.base_bundle[
                "completeness_slot_records"
            ],
        }
        trace_records = overrides.pop(
            "trace_records", self.base_bundle["trace_records"]
        )
        kwargs.update(overrides)
        with _no_process_or_network_stack():
            return checker._project_retained_products(trace_records, **kwargs)

    def _run_mtz_word_join_with_overrides(
        self, **overrides: Any
    ) -> dict[str, Any]:
        orig_bytes = overrides.pop(
            "original_mtz_bytes", self.base_bundle["original_mtz_bytes"]
        )
        proj_bytes = overrides.pop(
            "projected_mtz_bytes", self.base_bundle["projected_mtz_bytes"]
        )
        out_bytes = overrides.pop(
            "hklout_mtz_bytes", self.base_bundle["hklout_mtz_bytes"]
        )
        kwargs: dict[str, Any] = {
            "retained_ledger": self.base_bundle["input_hkl_ledger"],
            "retained_raw_export": self.base_bundle["hklout_raw_export"],
            "residual_members": self.base_bundle["residual_members"],
        }
        kwargs.update(overrides)
        with _no_process_or_network_stack():
            return checker._check_mtz_word_join(
                orig_bytes, proj_bytes, out_bytes, **kwargs
            )

    def test_positive_retained_attempt04_summary_and_non_promotion_invariants(
        self,
    ) -> None:
        """Single positive public check verifies all 11 pins, product/population counts, and false admission flags."""
        self.assertEqual(self.loader_call_count, 1)
        self.assertIs(
            checker._load_pinned_attempt04_bundle, type(self).real_loader
        )

        summary = self.positive_summary
        self.assertEqual(summary["schema_id"], checker.DIAGNOSTIC_SCHEMA_ID)
        self.assertEqual(
            summary["schema_version"], checker.DIAGNOSTIC_SCHEMA_VERSION
        )
        self.assertEqual(
            summary["fixture_scope"], checker.DIAGNOSTIC_FIXTURE_SCOPE
        )
        self.assertIs(summary["diagnostic_consistency"], True)
        self.assertIs(summary["scientific_admission"], False)
        self.assertIs(summary["batch_eligible"], False)
        self.assertIs(summary["effective_hkls_proven"], False)
        self.assertIs(summary["native_bin_membership_proven"], False)

        verified_pins = summary["verified_pins"]
        self.assertEqual(set(verified_pins.keys()), set(checker.PINS.keys()))
        self.assertEqual(len(verified_pins), 11)
        for rel_path, expected_sha in checker.PINS.items():
            self.assertEqual(verified_pins[rel_path]["sha256"], expected_sha)
            self.assertGreater(verified_pins[rel_path]["size_bytes"], 0)
        self.assertEqual(
            verified_pins[checker.NATIVE_TRACE_REL]["size_bytes"],
            checker.TRACE_EXPECTED_SIZE_BYTES,
        )

        # #1288: envelope carries only actual inspect_native_trace_bytes fields;
        # physical line count and per-event counts live in trace_record_metadata.
        envelope = summary["envelope"]
        self.assertEqual(
            set(envelope.keys()),
            {
                "valid",
                "closed",
                "sha256_match",
                "size_bytes_match",
                "record_count",
                "event_count",
                "footer_record_count",
            },
        )
        self.assertNotIn("line_count", envelope)
        self.assertNotIn("event_counts", envelope)
        self.assertIs(envelope["valid"], True)
        self.assertIs(envelope["closed"], True)
        self.assertIs(envelope["sha256_match"], True)
        self.assertIs(envelope["size_bytes_match"], True)
        self.assertEqual(envelope["record_count"], 94281)
        self.assertEqual(envelope["event_count"], 94281)
        self.assertEqual(envelope["footer_record_count"], 94281)

        trace_meta = summary["trace_record_metadata"]
        self.assertEqual(
            trace_meta["source"], "parsed_verified_trace_bytes_snapshot"
        )
        self.assertEqual(trace_meta["physical_line_count"], 94283)
        self.assertEqual(trace_meta["header_record_count"], 1)
        self.assertEqual(trace_meta["numbered_event_count"], 94281)
        self.assertEqual(trace_meta["writer_close_record_count"], 1)
        self.assertEqual(trace_meta["header_line_number"], 1)
        self.assertEqual(trace_meta["first_numbered_event_line_number"], 2)
        self.assertEqual(trace_meta["last_numbered_event_line_number"], 94282)
        self.assertEqual(trace_meta["writer_close_line_number"], 94283)
        self.assertEqual(trace_meta["writer_close_record_count_field"], 94281)
        self.assertEqual(sum(trace_meta["event_counts"].values()), 94281)

        proj = summary["retained_projections"]
        self.assertEqual(
            proj,
            {
                "native_bin_bounds_matches": True,
                "native_bin_bounds_count": 21,
                "c0_l0_bounds_identical": True,
                "shared_internal_endpoints_count": 19,
                "residual_members_matches": True,
                "residual_members_count": 7248,
                "completeness_members_matches": True,
                "completeness_members_count": 7262,
                "native_slot_records_matches": True,
                "native_slot_records_count": 42,
                "completeness_slot_records_matches": True,
                "completeness_slot_records_count": 21,
            },
        )

        mtz_join = summary["mtz_word_join"]
        self.assertEqual(mtz_join["raw_total"], 7248)
        self.assertEqual(mtz_join["eligible_total"], 7228)
        self.assertEqual(mtz_join["eligible_work"], 6505)
        self.assertEqual(mtz_join["eligible_free"], 723)
        self.assertEqual(mtz_join["positive_eligible_total"], 7217)
        self.assertEqual(mtz_join["positive_eligible_work"], 6494)
        self.assertEqual(mtz_join["positive_eligible_free"], 723)
        self.assertEqual(mtz_join["eligible_zero_f_work_count"], 11)
        self.assertEqual(
            tuple(mtz_join["eligible_zero_f_input_row_indices"]),
            checker.EXPECTED_ZERO_F_INPUT_ROW_INDICES,
        )
        self.assertEqual(mtz_join["unassigned_padding_count"], 20)
        self.assertEqual(
            mtz_join["unassigned_padding_input_row_range"], [7228, 7247]
        )
        self.assertEqual(mtz_join["native_excluded_so_le_zero_total"], 31)
        self.assertEqual(mtz_join["hklout_nan_f_sigf_total"], 31)
        self.assertEqual(
            mtz_join["hklout_padding_nan_to_free_zero_total"], 20
        )
        self.assertIs(mtz_join["raw_export_verified"], True)
        ds_alloc = mtz_join["dataset_allocation"]
        self.assertIs(
            ds_alloc["hklout_split_base_and_observation_datasets"], True
        )
        self.assertEqual(ds_alloc["refmac_hklout_mtz"]["H"], 0)
        self.assertEqual(ds_alloc["refmac_hklout_mtz"]["R-free-flags"], 0)
        self.assertEqual(ds_alloc["refmac_hklout_mtz"]["F-obs"], 1)
        self.assertEqual(ds_alloc["refmac_hklout_mtz"]["SIGF-obs"], 1)

        cross = summary["cross_namespace"]
        self.assertEqual(
            cross,
            {
                "residual_hkl_count": 7248,
                "completeness_hkl_count": 7262,
                "shared_hkl_count": 7248,
                "shared_captured_j_identical": True,
                "shared_ifree_identical": True,
                "active_residual_equals_observed_completeness": True,
                "active_observed_hkl_count": 7217,
                "shared_excluded_hkl_count": 31,
                "extra_asu_hkl_count": 14,
                "missing_completeness_hkl_count": 45,
            },
        )

    def test_envelope_api_contract_and_retained_row0_word_decoding_regressions(
        self,
    ) -> None:
        """Regression checks for #1288 actual envelope API contract and #1289 row 0 positive word hex decoding."""
        # #1288: inspect_native_trace_bytes returns _build_result fields (valid, closed,
        # sha256_match, size_bytes_match, record_count, event_count, footer_record_count,
        # errors, first_failure), never line_count or event_counts.
        for bad_field, bad_val in (
            ("valid", False),
            ("closed", False),
            ("record_count", 94280),
        ):
            with self.subTest(envelope_failure_field=bad_field):
                fake_envelope = dict(self.base_bundle["envelope"])
                fake_envelope[bad_field] = bad_val
                fake_envelope["errors"] = [f"simulated {bad_field} failure"]
                with mock.patch.object(
                    checker,
                    "_read_pinned_regular_file",
                    side_effect=lambda root, rel, sha: (
                        b"{}",
                        {"sha256": sha, "size_bytes": 2},
                    ),
                ), mock.patch.object(
                    checker.refmac_diagnostic_trace,
                    "inspect_native_trace_bytes",
                    return_value=fake_envelope,
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        "Native trace envelope verification failed",
                    ):
                        checker._load_pinned_attempt04_bundle(REPO_ROOT)

        # #1288: _derive_trace_record_metadata rejects physical line count or writer_close mismatch.
        with self.subTest(trace_metadata="truncated_physical_lines"):
            with self.assertRaisesRegex(
                ValueError, "Expected 94283 physical trace records"
            ):
                checker._derive_trace_record_metadata(
                    self.base_bundle["trace_records"][:-1]
                )

        with self.subTest(trace_metadata="corrupt_writer_close_record_count"):
            records, close_rec = self._clone_trace_with_record_copy(
                len(self.base_bundle["trace_records"]) - 1
            )
            close_rec["record_count"] = 94280
            with self.assertRaisesRegex(
                ValueError, "must be an unnumbered writer_close footer"
            ):
                checker._derive_trace_record_metadata(records)

        # #1289: retained row 0 ([0, 0, 2]) has canonical uint32 bit-word hex strings
        # "41e9ddec" (F-obs) and "42af6681" (SIGF-obs) that decode to positive finite floats.
        row0 = self.base_bundle["hklout_raw_export"]["rows"][0]
        self.assertEqual(row0["hkl"], [0, 0, 2])
        self.assertEqual(row0["column_words_hex"]["F-obs"], "41e9ddec")
        self.assertEqual(row0["column_words_hex"]["SIGF-obs"], "42af6681")
        f_val = checker._decode_uint32_word_hex_float("41e9ddec")
        sigf_val = checker._decode_uint32_word_hex_float("42af6681")
        self.assertAlmostEqual(f_val, 29.233360290527344, places=6)
        self.assertAlmostEqual(sigf_val, 87.70020294189453, places=6)

        # Mutating row 0's active HKLOUT F-obs word in both MTZ bytes and raw export
        # to negative float word "c1e9ddec" (-29.23336) reaches the active-row positive float guard.
        out_cols = [
            c["label"]
            for c in self.base_bundle["hklout_raw_export"]["header_parse"][
                "columns"
            ]
        ]
        f_col_idx = out_cols.index("F-obs")
        bad_out_bytes = _patch_mtz_word(
            self.base_bundle["hklout_mtz_bytes"],
            ncols=17,
            row_idx=0,
            col_idx=f_col_idx,
            word_u32=0xC1E9DDEC,
        )
        bad_raw_export = copy.deepcopy(self.base_bundle["hklout_raw_export"])
        bad_raw_export["rows"][0]["column_words_hex"]["F-obs"] = "c1e9ddec"
        with self.assertRaisesRegex(
            ValueError,
            r"Non-positive or non-finite HKLOUT F-obs/SIGF-obs for active row \(0, 0, 2\)",
        ):
            self._run_mtz_word_join_with_overrides(
                hklout_mtz_bytes=bad_out_bytes,
                retained_raw_export=bad_raw_export,
            )

    def test_saved_member_projection_mutations(self) -> None:
        """Exact trace-to-analysis projection rejects mutations to saved residual/completeness member fields."""
        base_res = self.base_bundle["residual_members"]
        base_comp = self.base_bundle["completeness_members"]

        padding_idx = next(
            idx
            for idx, m in enumerate(base_res)
            if m["native_free_flag"]["bits_hex"] == "80000000"
        )
        excluded_idx = next(
            idx for idx, m in enumerate(base_res) if m["overall_added"] is False
        )

        residual_cases: tuple[tuple[str, int, str, Any], ...] = (
            ("source_input_F_word", 0, "source_input_F_word", "4419d9c3"),
            ("input_line_sequence_vs_physical", 0, "input_line", 29118),
            ("terminal_line", 0, "terminal_line", 29127),
            ("row_outcome", 0, "row_outcome", "excluded_sigma_guard_in_shell"),
            (
                "native_signed_zero_flag_to_plus_zero",
                padding_idx,
                "native_free_flag",
                {"bits_hex": "00000000", "decimal": "0.0"},
            ),
            ("active_operand_YOS_set_null", 0, "YOS", None),
            (
                "active_operand_YOS_mutated_value",
                0,
                "YOS",
                {"bits_hex": "3F800000", "decimal": "1.0"},
            ),
            (
                "excluded_operand_YOS_set_non_null",
                excluded_idx,
                "YOS",
                {"bits_hex": "00000000", "decimal": "0.0"},
            ),
        )

        for label, target_idx, field_name, bad_value in residual_cases:
            with self.subTest(residual_member_mutation=label):
                mutated_res = list(base_res)
                row_copy = copy.deepcopy(mutated_res[target_idx])
                row_copy[field_name] = bad_value
                mutated_res[target_idx] = row_copy
                with self.assertRaisesRegex(
                    ValueError,
                    rf"residual_members\.json mismatch at index {target_idx}",
                ):
                    self._run_project_with_overrides(
                        retained_residual_members=mutated_res
                    )

        completeness_cases: tuple[tuple[str, str, Any], ...] = (
            ("completeness_input_line", "input_line", 23),
            ("completeness_terminal_line", "terminal_line", 28),
            (
                "completeness_row_outcome",
                "row_outcome",
                "missing_shell_and_overall",
            ),
        )
        for label, field_name, bad_value in completeness_cases:
            with self.subTest(completeness_member_mutation=label):
                mutated_comp = list(base_comp)
                row_copy = copy.deepcopy(mutated_comp[0])
                row_copy[field_name] = bad_value
                mutated_comp[0] = row_copy
                with self.assertRaisesRegex(
                    ValueError,
                    r"completeness_members\.json mismatch at index 0",
                ):
                    self._run_project_with_overrides(
                        retained_completeness_members=mutated_comp
                    )

    def test_slot_and_bounds_record_mutations(self) -> None:
        """Whole-record and slot-set checks reject non-count field, duplicate/missing slot, and completeness line/HPERC mutations."""
        base_native_slots = self.base_bundle["native_slot_records"]
        base_comp_slots = self.base_bundle["completeness_slot_records"]
        base_bounds = self.base_bundle["native_bin_bounds"]

        with self.subTest(mutation="native_slot_non_count_AFOFO_raw"):
            mutated_slots = list(base_native_slots)
            slot0 = copy.deepcopy(mutated_slots[0])
            slot0["record"]["AFOFO_raw"] = {
                "bits_hex": "3F800000",
                "decimal": "1.0",
            }
            mutated_slots[0] = slot0
            with self.assertRaisesRegex(
                ValueError, r"native_slot_records\.json mismatch at index 0"
            ):
                self._run_project_with_overrides(
                    retained_native_slot_records=mutated_slots
                )

        with self.subTest(mutation="missing_retained_native_slot_record"):
            with self.assertRaisesRegex(
                ValueError, r"native_slot_records\.json length mismatch"
            ):
                self._run_project_with_overrides(
                    retained_native_slot_records=list(base_native_slots[:-1])
                )

        with self.subTest(mutation="duplicate_lsq_raw_accumulator_slot_in_trace"):
            l8_idx = self.event_first_index["lsq_raw_accumulator_slot"]
            records = list(self.base_bundle["trace_records"])
            dup_line, dup_rec = records[l8_idx]
            records.insert(l8_idx + 1, (dup_line, copy.deepcopy(dup_rec)))
            with self.assertRaisesRegex(
                ValueError, "Duplicate lsq_raw_accumulator_slot"
            ):
                self._run_project_with_overrides(trace_records=records)

        with self.subTest(mutation="completeness_slot_saved_line"):
            mutated_comp_slots = list(base_comp_slots)
            cslot0 = copy.deepcopy(mutated_comp_slots[0])
            cslot0["line"] = cslot0["record"]["sequence"]
            mutated_comp_slots[0] = cslot0
            with self.assertRaisesRegex(
                ValueError,
                r"completeness_slot_records\.json mismatch at index 0",
            ):
                self._run_project_with_overrides(
                    retained_completeness_slot_records=mutated_comp_slots
                )

        with self.subTest(mutation="completeness_slot_HPERC_SHELL_REFL"):
            mutated_comp_slots = list(base_comp_slots)
            cslot0 = copy.deepcopy(mutated_comp_slots[0])
            cslot0["record"]["HPERC_SHELL_REFL"] = {
                "bits_hex": "3F800000",
                "decimal": "1.0",
            }
            mutated_comp_slots[0] = cslot0
            with self.assertRaisesRegex(
                ValueError,
                r"completeness_slot_records\.json mismatch at index 0",
            ):
                self._run_project_with_overrides(
                    retained_completeness_slot_records=mutated_comp_slots
                )

        with self.subTest(mutation="native_bin_bounds_saved_line"):
            mutated_bounds = list(base_bounds)
            b0 = copy.deepcopy(mutated_bounds[0])
            b0["line"] = b0["record"]["sequence"]
            mutated_bounds[0] = b0
            with self.assertRaisesRegex(
                ValueError, r"native_bin_bounds\.json mismatch at index 0"
            ):
                self._run_project_with_overrides(
                    retained_native_bin_bounds=mutated_bounds
                )

    def test_completeness_and_lsq_carrier_and_bound_slot_guards(self) -> None:
        """Regression checks for #1290 C1/C2/C3/C4/L4 row-carrier bindings and #1291 missing C0/L0 bound slot ValueErrors."""
        c1_idx = self.event_first_index["completeness_row_input"]
        c2_idx = self.event_first_index["completeness_shell_increment"]
        c3_idx = self.event_first_index["completeness_overall_increment"]
        c4_idx = self.event_first_index["completeness_row_terminal"]
        l4_idx = self.event_first_index["lsq_shell_match_before"]
        c0_idx = self.event_first_index["completeness_bin_bounds"]
        l0_idx = self.event_first_index["lsq_coef_bin_bounds"]

        # #1290: C1 IFREE mutated (1 -> 2) while completeness_partition_code stays 1
        with self.subTest(guard="c1_ifree_contradicts_partition_code"):
            records, c1_rec = self._clone_trace_with_record_copy(c1_idx)
            c1_rec["IFREE"] = 2
            with self.assertRaisesRegex(
                ValueError,
                r"completeness_row_input field 'IFREE'/'completeness_partition_code' contradiction",
            ):
                self._run_project_with_overrides(trace_records=records)

        # #1290: C1 completeness_partition_code mutated (1 -> 0) while IFREE stays 1
        with self.subTest(guard="c1_partition_code_contradicts_ifree"):
            records, c1_rec = self._clone_trace_with_record_copy(c1_idx)
            c1_rec["completeness_partition_code"] = 0
            with self.assertRaisesRegex(
                ValueError,
                r"completeness_row_input field 'IFREE'/'completeness_partition_code' contradiction",
            ):
                self._run_project_with_overrides(trace_records=records)

        # #1290: C1 both IFREE=2 and completeness_partition_code=0 mutated -> C2 catches IFREE mismatch against open C1 row
        with self.subTest(guard="c2_ifree_contradicts_open_c1_row"):
            records, c1_rec = self._clone_trace_with_record_copy(c1_idx)
            c1_rec["IFREE"] = 2
            c1_rec["completeness_partition_code"] = 0
            with self.assertRaisesRegex(
                ValueError,
                r"completeness_shell_increment field 'IFREE' contradicts open C1 row",
            ):
                self._run_project_with_overrides(trace_records=records)

        # #1290: C2 completeness_observed_code contradicts open C1 row
        with self.subTest(guard="c2_observed_code_contradicts_open_c1_row"):
            records, c2_rec = self._clone_trace_with_record_copy(c2_idx)
            c2_rec["completeness_observed_code"] = 0
            with self.assertRaisesRegex(
                ValueError,
                r"completeness_shell_increment field 'completeness_observed_code' contradicts open C1 row",
            ):
                self._run_project_with_overrides(trace_records=records)

        # #1290: C3 completeness_observed_code contradicts open C1 row
        with self.subTest(guard="c3_observed_code_contradicts_open_c1_row"):
            records, c3_rec = self._clone_trace_with_record_copy(c3_idx)
            c3_rec["completeness_observed_code"] = 0
            with self.assertRaisesRegex(
                ValueError,
                r"completeness_overall_increment field 'completeness_observed_code' contradicts open C1 row",
            ):
                self._run_project_with_overrides(trace_records=records)

        # #1290: C4 terminal IFREE contradicts open C1 row
        with self.subTest(guard="c4_terminal_ifree_contradicts_open_c1_row"):
            records, c4_rec = self._clone_trace_with_record_copy(c4_idx)
            c4_rec["IFREE"] = 2
            with self.assertRaisesRegex(
                ValueError,
                r"completeness_row_terminal field 'IFREE' contradicts open C1 row",
            ):
                self._run_project_with_overrides(trace_records=records)

        # #1290: L4 IFREE contradicts open L2 row
        with self.subTest(guard="l4_ifree_contradicts_open_l2_row"):
            records, l4_rec = self._clone_trace_with_record_copy(l4_idx)
            l4_rec["IFREE"] = 2
            with self.assertRaisesRegex(
                ValueError,
                r"lsq_shell_match_before field 'IFREE' contradicts open L2 row",
            ):
                self._run_project_with_overrides(trace_records=records)

        # #1291: Missing C0 slot 1 raises contextual ValueError (not KeyError)
        with self.subTest(guard="missing_c0_slot_1_contextual_value_error"):
            records = list(self.base_bundle["trace_records"])
            del records[c0_idx]
            with self.assertRaisesRegex(
                ValueError,
                r"Missing required C0 bin boundary slot=1 in namespace='reporting_completeness'",
            ):
                self._run_project_with_overrides(trace_records=records)

        # #1291: Missing L0 slot 1 raises contextual ValueError (not KeyError)
        with self.subTest(guard="missing_l0_slot_1_contextual_value_error"):
            records = list(self.base_bundle["trace_records"])
            del records[l0_idx]
            with self.assertRaisesRegex(
                ValueError,
                r"Missing required L0 bin boundary slot=1 in namespace='residual_lsq'",
            ):
                self._run_project_with_overrides(trace_records=records)

    def test_ledger_eligibility_word_and_zero_f_row_mutations(self) -> None:
        """Rebuilt ledger and full-set checks reject ledger word/eligibility edits and zero-F row removal."""
        base_ledger = self.base_bundle["input_hkl_ledger"]
        zero_f_row_idx = checker.EXPECTED_ZERO_F_INPUT_ROW_INDICES[0]
        padding_row_idx = checker.EXPECTED_PADDING_INPUT_ROW_INDICES[0]

        with self.subTest(mutation="retained_ledger_f_obs_word_hex"):
            mut_ledger = copy.deepcopy(base_ledger)
            mut_ledger["raw_rows"][0]["f_obs_word_hex"] = "3f800000"
            with self.assertRaisesRegex(
                ValueError, r"projected_vs_retained_ledger\.raw_rows"
            ):
                self._run_mtz_word_join_with_overrides(
                    retained_ledger=mut_ledger
                )

        with self.subTest(mutation="retained_ledger_eligible_flag"):
            mut_ledger = copy.deepcopy(base_ledger)
            mut_ledger["raw_rows"][0]["eligible"] = False
            with self.assertRaisesRegex(
                ValueError, r"projected_vs_retained_ledger\.raw_rows"
            ):
                self._run_mtz_word_join_with_overrides(
                    retained_ledger=mut_ledger
                )

        with self.subTest(mutation="drop_zero_f_row_from_eligible_by_hkl"):
            mut_ledger = copy.deepcopy(base_ledger)
            zero_hkl = mut_ledger["raw_rows"][zero_f_row_idx]["hkl"]
            zero_key = f"{zero_hkl[0]},{zero_hkl[1]},{zero_hkl[2]}"
            del mut_ledger["eligible_by_hkl"][zero_key]
            with self.assertRaisesRegex(
                ValueError, r"projected_vs_retained_ledger\.eligible_by_hkl"
            ):
                self._run_mtz_word_join_with_overrides(
                    retained_ledger=mut_ledger
                )

        # Convert eligible zero-F row 283 into a positive-F row across synchronized
        # original_mtz_bytes, projected_mtz_bytes, and rebuilt retained_ledger so that
        # survivor counts (eligible_total=7228, eligible_work=6505) stay intact while
        # dropping the row from the zero-F population.
        with self.subTest(
            mutation="convert_zero_f_row_in_mtz_and_ledger_preserving_survivor_counts"
        ):
            labels = ("F-obs", "SIGF-obs", "R-free-flags")
            orig_layout = onesar_rerun._inspect_mtz_layout(
                self.base_bundle["original_mtz_bytes"], labels
            )
            proj_layout = onesar_rerun._inspect_mtz_layout(
                self.base_bundle["projected_mtz_bytes"], labels
            )
            mut_orig_bytes = _patch_mtz_word(
                self.base_bundle["original_mtz_bytes"],
                ncols=orig_layout["ncols"],
                row_idx=zero_f_row_idx,
                col_idx=orig_layout["col_indices"]["F-obs"],
                word_u32=0x3F800000,
            )
            mut_proj_bytes = _patch_mtz_word(
                self.base_bundle["projected_mtz_bytes"],
                ncols=proj_layout["ncols"],
                row_idx=zero_f_row_idx,
                col_idx=proj_layout["col_indices"]["F-obs"],
                word_u32=0x3F800000,
            )
            rebuilt_ledger = onesar_rerun.build_input_hkl_ledger(
                mut_proj_bytes
            )
            self.assertEqual(rebuilt_ledger["counts"]["eligible_total"], 7228)
            self.assertEqual(rebuilt_ledger["counts"]["eligible_work"], 6505)
            self.assertEqual(rebuilt_ledger["counts"]["eligible_zero_f"], 10)
            with self.assertRaisesRegex(
                ValueError,
                r"input_hkl_ledger\.counts mismatch at key 'eligible_zero_f'",
            ):
                self._run_mtz_word_join_with_overrides(
                    original_mtz_bytes=mut_orig_bytes,
                    projected_mtz_bytes=mut_proj_bytes,
                    retained_ledger=rebuilt_ledger,
                )

        # Swap the observation words of zero-F row 283 and padding row 7228 across
        # original_mtz_bytes, projected_mtz_bytes, and rebuilt retained_ledger so
        # all 13 ledger counts (including eligible_zero_f=11) match expected_counts,
        # reaching the per-row HKL join contract.
        with self.subTest(
            mutation="swap_zero_f_row_and_padding_row_preserving_all_ledger_counts"
        ):
            labels = ("F-obs", "SIGF-obs", "R-free-flags")
            orig_layout = onesar_rerun._inspect_mtz_layout(
                self.base_bundle["original_mtz_bytes"], labels
            )
            proj_layout = onesar_rerun._inspect_mtz_layout(
                self.base_bundle["projected_mtz_bytes"], labels
            )
            mut_orig_bytes = self.base_bundle["original_mtz_bytes"]
            mut_proj_bytes = self.base_bundle["projected_mtz_bytes"]
            for col_name in labels:
                o_col = orig_layout["col_indices"][col_name]
                p_col = proj_layout["col_indices"][col_name]
                w_zero = _read_mtz_word(
                    mut_proj_bytes,
                    ncols=proj_layout["ncols"],
                    row_idx=zero_f_row_idx,
                    col_idx=p_col,
                )
                w_pad = _read_mtz_word(
                    mut_proj_bytes,
                    ncols=proj_layout["ncols"],
                    row_idx=padding_row_idx,
                    col_idx=p_col,
                )
                mut_orig_bytes = _patch_mtz_word(
                    mut_orig_bytes,
                    ncols=orig_layout["ncols"],
                    row_idx=zero_f_row_idx,
                    col_idx=o_col,
                    word_u32=w_pad,
                )
                mut_orig_bytes = _patch_mtz_word(
                    mut_orig_bytes,
                    ncols=orig_layout["ncols"],
                    row_idx=padding_row_idx,
                    col_idx=o_col,
                    word_u32=w_zero,
                )
                mut_proj_bytes = _patch_mtz_word(
                    mut_proj_bytes,
                    ncols=proj_layout["ncols"],
                    row_idx=zero_f_row_idx,
                    col_idx=p_col,
                    word_u32=w_pad,
                )
                mut_proj_bytes = _patch_mtz_word(
                    mut_proj_bytes,
                    ncols=proj_layout["ncols"],
                    row_idx=padding_row_idx,
                    col_idx=p_col,
                    word_u32=w_zero,
                )
            rebuilt_ledger = onesar_rerun.build_input_hkl_ledger(
                mut_proj_bytes
            )
            self.assertEqual(
                rebuilt_ledger["counts"], base_ledger["counts"]
            )
            with self.assertRaisesRegex(
                ValueError,
                r"Unassigned padding row contract violated at HKL \(0, 20, 10\) \(row 283\)",
            ):
                self._run_mtz_word_join_with_overrides(
                    original_mtz_bytes=mut_orig_bytes,
                    projected_mtz_bytes=mut_proj_bytes,
                    retained_ledger=rebuilt_ledger,
                )

    def test_hklout_raw_export_and_mtz_word_join_mutations(self) -> None:
        """MTZ-byte/layout and #1292 H/K/L word-decoding checks reject raw-export and HKLOUT inconsistencies."""
        base_export = self.base_bundle["hklout_raw_export"]
        base_out_bytes = self.base_bundle["hklout_mtz_bytes"]
        out_cols = [
            c["label"] for c in base_export["header_parse"]["columns"]
        ]
        l_col_idx = out_cols.index("L")

        with self.subTest(mutation="raw_export_column_word_mismatch"):
            mut_export = copy.deepcopy(base_export)
            mut_export["rows"][0]["column_words_hex"]["FC"] = "00000000"
            with self.assertRaisesRegex(
                ValueError, r"HKLOUT word mismatch at row 0, column FC"
            ):
                self._run_mtz_word_join_with_overrides(
                    retained_raw_export=mut_export
                )

        with self.subTest(mutation="raw_export_top_level_header_byte_offset"):
            mut_export = copy.deepcopy(base_export)
            mut_export["header_byte_offset"] = 492948
            with self.assertRaisesRegex(
                ValueError,
                r"refmac_hklout_raw_export\.json byte/word layout metadata mismatch",
            ):
                self._run_mtz_word_join_with_overrides(
                    retained_raw_export=mut_export
                )

        with self.subTest(mutation="raw_export_row_index_mismatch"):
            mut_export = copy.deepcopy(base_export)
            mut_export["rows"][0]["row_index"] = 1
            with self.assertRaisesRegex(
                ValueError, r"Malformed raw export row metadata at row_index=0"
            ):
                self._run_mtz_word_join_with_overrides(
                    retained_raw_export=mut_export
                )

        # #1293: float row_index values (row0=0.0 and row1=1.0) must be rejected by
        # exact non-boolean int metadata checks even though 0.0 == 0 and 1.0 == 1.
        for target_row_idx, float_row_idx in ((0, 0.0), (1, 1.0)):
            with self.subTest(
                mutation=f"raw_export_float_row_index_row{target_row_idx}"
            ):
                mut_export = dict(base_export)
                mut_rows = list(base_export["rows"])
                row_copy = dict(mut_rows[target_row_idx])
                row_copy["row_index"] = float_row_idx
                mut_rows[target_row_idx] = row_copy
                mut_export["rows"] = mut_rows
                with self.assertRaisesRegex(
                    ValueError,
                    rf"Malformed raw export row metadata at row_index={target_row_idx}",
                ):
                    self._run_mtz_word_join_with_overrides(
                        retained_raw_export=mut_export
                    )

        with self.subTest(mutation="raw_export_column_index_mismatch"):
            mut_export = copy.deepcopy(base_export)
            mut_export["header_parse"]["columns"][0]["column_index"] = 1
            with self.assertRaisesRegex(
                ValueError, r"Column descriptor mismatch at index 0"
            ):
                self._run_mtz_word_join_with_overrides(
                    retained_raw_export=mut_export
                )

        with self.subTest(mutation="raw_export_header_dataset_id_mismatch"):
            mut_export = copy.deepcopy(base_export)
            mut_export["header_parse"]["columns"][3]["dataset_id"] = "1"
            with self.assertRaisesRegex(
                ValueError, r"Column descriptor mismatch at index 3"
            ):
                self._run_mtz_word_join_with_overrides(
                    retained_raw_export=mut_export
                )

        with self.subTest(mutation="raw_export_stripped_primary_header_card"):
            mut_export = copy.deepcopy(base_export)
            mut_export["primary_header_cards"][0] = mut_export[
                "primary_header_cards"
            ][0].strip()
            with self.assertRaisesRegex(
                ValueError,
                r"primary_header_cards\[0\] is not an 80-char string",
            ):
                self._run_mtz_word_join_with_overrides(
                    retained_raw_export=mut_export
                )

        # #1292 Case A (metadata-binding rejection): change actual MTZ L word at row 0
        # from 2.0 (0x40000000) to 4.0 (0x40800000) AND update exported column_words_hex["L"]
        # while leaving exported hkl=[0, 0, 2] unchanged.
        with self.subTest(
            guard="1292_case_a_mtz_hkl_word_disagrees_with_exported_hkl_metadata"
        ):
            mut_out_bytes = _patch_mtz_word(
                base_out_bytes,
                ncols=17,
                row_idx=0,
                col_idx=l_col_idx,
                word_u32=0x40800000,
            )
            mut_export = copy.deepcopy(base_export)
            mut_export["rows"][0]["column_words_hex"]["L"] = "40800000"
            self.assertEqual(mut_export["rows"][0]["hkl"], [0, 0, 2])
            with self.assertRaisesRegex(
                ValueError,
                r"refmac_hklout_raw_export\.rows\[0\]\.hkl mismatch at index 2",
            ):
                self._run_mtz_word_join_with_overrides(
                    hklout_mtz_bytes=mut_out_bytes,
                    retained_raw_export=mut_export,
                )

        # #1292 Case B (decoded-HKL duplicate rejection): change actual MTZ L word at row 0
        # to 4.0 (0x40800000), update exported column_words_hex["L"], AND update row 0's
        # recorded hkl to [0, 0, 4] so row 0 passes metadata binding and row 1 ([0, 0, 4])
        # reaches the decoded-HKL duplicate check.
        with self.subTest(
            guard="1292_case_b_duplicate_decoded_hkl_at_existing_row1"
        ):
            mut_out_bytes = _patch_mtz_word(
                base_out_bytes,
                ncols=17,
                row_idx=0,
                col_idx=l_col_idx,
                word_u32=0x40800000,
            )
            mut_export = copy.deepcopy(base_export)
            mut_export["rows"][0]["column_words_hex"]["L"] = "40800000"
            mut_export["rows"][0]["hkl"] = [0, 0, 4]
            self.assertEqual(mut_export["rows"][1]["hkl"], [0, 0, 4])
            with self.assertRaisesRegex(
                ValueError,
                r"Duplicate decoded HKL \(0, 0, 4\) in refmac_hklout\.mtz / refmac_hklout_raw_export\.json at row 1",
            ):
                self._run_mtz_word_join_with_overrides(
                    hklout_mtz_bytes=mut_out_bytes,
                    retained_raw_export=mut_export,
                )

        # #1292 Case C: non-integral HKL word in MTZ bytes and float HKL in JSON export
        with self.subTest(guard="1292_non_integral_mtz_hkl_word"):
            mut_out_bytes = _patch_mtz_word(
                base_out_bytes,
                ncols=17,
                row_idx=0,
                col_idx=l_col_idx,
                word_u32=0x40200000,  # 2.5
            )
            mut_export = copy.deepcopy(base_export)
            mut_export["rows"][0]["column_words_hex"]["L"] = "40200000"
            with self.assertRaisesRegex(
                ValueError,
                r"Non-finite or non-integral HKLOUT L word 0x40200000",
            ):
                self._run_mtz_word_join_with_overrides(
                    hklout_mtz_bytes=mut_out_bytes,
                    retained_raw_export=mut_export,
                )

        with self.subTest(guard="1292_non_int_exported_hkl_triplet"):
            mut_export = copy.deepcopy(base_export)
            mut_export["rows"][0]["hkl"] = [0, 0, 2.0]
            with self.assertRaisesRegex(
                ValueError,
                r"Expected 3-element non-boolean integer HKL triplet at refmac_hklout_raw_export\.rows\[0\]\.hkl",
            ):
                self._run_mtz_word_join_with_overrides(
                    retained_raw_export=mut_export
                )

    def test_cross_namespace_shared_j_and_missing_hkl_set_mutations(
        self,
    ) -> None:
        """Cross-namespace and projection checks reject excluded-row J drift and wrong missing/ASU HKL sets."""
        base_res = self.base_bundle["residual_members"]
        base_comp = self.base_bundle["completeness_members"]

        res_by_hkl = {tuple(r["hkl"]): r for r in base_res}
        excluded_shared_hkl = next(
            tuple(r["hkl"]) for r in base_res if r["overall_added"] is False
        )
        active_shared_hkl = next(
            tuple(r["hkl"]) for r in base_res if r["overall_added"] is True
        )
        extra_asu_idx = next(
            idx
            for idx, c in enumerate(base_comp)
            if tuple(c["hkl"]) not in res_by_hkl
        )
        excluded_comp_idx = next(
            idx
            for idx, c in enumerate(base_comp)
            if tuple(c["hkl"]) == excluded_shared_hkl
        )
        active_comp_idx = next(
            idx
            for idx, c in enumerate(base_comp)
            if tuple(c["hkl"]) == active_shared_hkl
        )

        # 1. Mutate captured J on an excluded shared HKL in completeness_members only
        with self.subTest(mutation="excluded_shared_hkl_j_disagreement"):
            mut_comp = list(base_comp)
            c_copy = copy.deepcopy(mut_comp[excluded_comp_idx])
            orig_j = c_copy["matched_bins"][0]
            c_copy["matched_bins"] = [(orig_j % 20) + 1]
            mut_comp[excluded_comp_idx] = c_copy
            with _no_process_or_network_stack():
                with self.assertRaisesRegex(
                    ValueError,
                    r"Cross-namespace captured J mismatch at shared HKL",
                ):
                    checker._check_shared_hkls(base_res, mut_comp)

        # 2. Swap observed/missing status between one excluded shared HKL and one active
        # shared HKL in completeness_members (preserving 7,217 observed and 45 missing counts).
        with self.subTest(
            mutation="wrong_missing_set_swapping_active_and_excluded_with_unchanged_counts"
        ):
            mut_comp = list(base_comp)
            c_excl = copy.deepcopy(mut_comp[excluded_comp_idx])
            c_act = copy.deepcopy(mut_comp[active_comp_idx])
            c_excl["observed_code"] = 1
            c_excl["row_outcome"] = "observed_shell_and_overall"
            c_act["observed_code"] = 0
            c_act["row_outcome"] = "missing_shell_and_overall"
            mut_comp[excluded_comp_idx] = c_excl
            mut_comp[active_comp_idx] = c_act
            with _no_process_or_network_stack():
                with self.assertRaisesRegex(
                    ValueError, r"Cross-namespace partition mismatch"
                ):
                    checker._check_shared_hkls(base_res, mut_comp)

        # 3. Replace a shared excluded HKL in completeness_members with an unused HKL
        # [99, 99, 99] while keeping 7,262 total and 45 missing completeness rows.
        with self.subTest(
            mutation="shared_excluded_hkl_replaced_with_extra_hkl_violating_subset"
        ):
            mut_comp = list(base_comp)
            c_excl = copy.deepcopy(mut_comp[excluded_comp_idx])
            c_excl["hkl"] = [99, 99, 99]
            mut_comp[excluded_comp_idx] = c_excl
            with _no_process_or_network_stack():
                with self.assertRaisesRegex(
                    ValueError,
                    r"residual_members HKLs are not a strict subset of completeness_members HKLs",
                ):
                    checker._check_shared_hkls(base_res, mut_comp)

        # 4. Mutate a saved extra-ASU missing HKL in completeness_members to [99, 99, 99]
        # against the unchanged captured C1 trace events (non-tautological identity anchor).
        with self.subTest(
            mutation="saved_extra_asu_hkl_mutated_against_captured_c1_trace_anchor"
        ):
            mut_comp = list(base_comp)
            c_extra = copy.deepcopy(mut_comp[extra_asu_idx])
            c_extra["hkl"] = [99, 99, 99]
            mut_comp[extra_asu_idx] = c_extra
            with self.assertRaisesRegex(
                ValueError,
                rf"completeness_members\.json mismatch at index {extra_asu_idx}",
            ):
                self._run_project_with_overrides(
                    retained_completeness_members=mut_comp
                )

    def test_public_pin_rejection_and_unsupported_retained_mode(self) -> None:
        """Public loader rejects corrupt SHA-256 bytes, private projection rejects unsupported modes, and flags stay False."""
        # Corrupt pin test on the real public loader using a scoped 1-byte flip on read_bytes
        target_path = (REPO_ROOT / checker.INPUT_LEDGER_REL).resolve()
        orig_read_bytes = Path.read_bytes

        def _corrupt_ledger_read_bytes(path_obj: Path) -> bytes:
            raw = orig_read_bytes(path_obj)
            if path_obj.resolve() == target_path:
                return raw[:-1] + (b"\x00" if raw[-1:] != b"\x00" else b"\x01")
            return raw

        with self.subTest(boundary="public_fixed_pin_sha256_rejection"):
            with _no_process_or_network_stack():
                with mock.patch.object(
                    Path,
                    "read_bytes",
                    autospec=True,
                    side_effect=_corrupt_ledger_read_bytes,
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        rf"SHA-256 mismatch for {checker.INPUT_LEDGER_REL}: expected {checker.PINS[checker.INPUT_LEDGER_REL]}",
                    ):
                        checker.verify_retained_attempt04(REPO_ROOT)

        # Unsupported retained mode in lsq_coef_begin and completeness_begin
        l1_idx = self.event_first_index["lsq_coef_begin"]
        c_begin_idx = self.event_first_index["completeness_begin"]

        for mode_field, bad_val in (
            ("REFS", "LSQF"),
            ("LFreeRexcludeVal", 0),
            ("NBIN", 10),
        ):
            with self.subTest(unsupported_lsq_mode=mode_field):
                records, l1_rec = self._clone_trace_with_record_copy(l1_idx)
                l1_rec[mode_field] = bad_val
                with self.assertRaisesRegex(
                    ValueError, "Unexpected lsq_coef_begin mode fields"
                ):
                    self._run_project_with_overrides(trace_records=records)

        with self.subTest(unsupported_completeness_mode="FREER_FLAG_false"):
            records, cb_rec = self._clone_trace_with_record_copy(c_begin_idx)
            cb_rec["FREER_FLAG"] = False
            with self.assertRaisesRegex(
                ValueError, "Unexpected completeness_begin header fields"
            ):
                self._run_project_with_overrides(trace_records=records)

        # Successful verification of the accepted bundle never promotes any scientific flag
        with _no_process_or_network_stack():
            res = checker._verify_loaded_attempt04_bundle(self.base_bundle)
        self.assertIs(res["diagnostic_consistency"], True)
        self.assertIs(res["scientific_admission"], False)
        self.assertIs(res["batch_eligible"], False)
        self.assertIs(res["effective_hkls_proven"], False)
        self.assertIs(res["native_bin_membership_proven"], False)


if __name__ == "__main__":
    unittest.main()
