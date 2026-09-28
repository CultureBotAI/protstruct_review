#!/usr/bin/env python3
"""Hermetic T03 policy regressions and retained IEEE-word recount; no tool runs."""
from __future__ import annotations

import copy
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import struct
import unittest
from unittest import mock
import zipfile

from audit_1sar_retained_evidence import ARCHIVE
import check_driver_thresholds as driver_guard
from t03_reflection_retention import audit_mtz_retention, deposition_applicability
import t03_reflection_retention as retention

REPO = Path(__file__).resolve().parent.parent
LABELS = ("F", "SIGF", "FREE")
NAN = float("nan")


def mtz(rows: list[list[float]], *, cell: str = "10 20 30 90 90 90") -> bytes:
    table = b"".join(struct.pack("<6f", *row) for row in rows)
    preamble = bytearray(80)
    preamble[:4] = b"MTZ "
    preamble[4:8] = struct.pack("<i", (80 + len(table)) // 4 + 1)
    preamble[8:12] = bytes.fromhex("44410000")
    columns = ("H", "K", "L", *LABELS)
    records = [f"NCOL 6 {len(rows)} 0", "VALM NAN"]
    records += [f"COLUMN {label} {kind} 0 0 0"
                for label, kind in zip(columns, ("H", "H", "H", "F", "Q", "I"))]
    records += [f"CELL {cell}", "SYMINF 1 1 P 1 'P1' 1", "SYMM X,Y,Z",
                "RESO 0.001 0.16", "NDIF 1", "DATASET 0 synthetic",
                f"DCELL 0 {cell}", "END"]
    return bytes(preamble) + table + b"".join(record.encode().ljust(80, b" ") for record in records)


def replace_header(blob: bytes, keyword: str, replacements: list[str]) -> bytes:
    """Modify synthetic fixed-width records without changing reflection bytes."""
    offset = (struct.unpack("<i", blob[4:8])[0] - 1) * 4
    records = [blob[start:start + 80].decode().strip()
               for start in range(offset, len(blob), 80)]
    retained = [record for record in records if record.split()[0] not in {keyword, "END"}]
    return blob[:offset] + b"".join(
        record.encode().ljust(80, b" ") for record in [*retained, *replacements, "END"]
    )


class ReflectionRetentionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.rows = [[1, 0, 0, 10, 1, 0], [2, 0, 0, 0, 1, 1],
                     [3, 0, 0, -2, 1, 0], [4, 0, 0, NAN, NAN, NAN]]

    def compare(self, output: list[list[float]], *, before: list[list[float]] | None = None) -> dict:
        return audit_mtz_retention(
            mtz(self.rows if before is None else before), mtz(output),
            input_labels=LABELS, output_labels=LABELS, flag_values={0, 1}, free_value=1,
        )

    def test_missing_deposition_is_unevaluable_even_with_refmac(self) -> None:
        for missing in (None, "NULL", NAN, float("inf"), True, -0.1):
            with self.subTest(reference=missing):
                result = deposition_applicability(missing, 0.21)
                self.assertEqual(result["deposition_clause"], "unevaluable")
                self.assertEqual(result["refmac_reference"], "available")
        self.assertEqual(deposition_applicability(0.2, 0.21)["deposition_clause"], "evaluable")

    def test_zero_and_negative_f_are_retained_and_reordering_is_harmless(self) -> None:
        result = self.compare(list(reversed(self.rows)))
        self.assertEqual(result["audit_status"], "preserved")
        self.assertEqual(result["input"]["eligible_rows"], 3)
        self.assertEqual(result["input"]["zero_f"], 1)
        self.assertEqual(result["input"]["negative_f"], 1)

    def test_padding_is_counted_without_changing_the_input_domain(self) -> None:
        result = self.compare(self.rows + [[5, 0, 0, NAN, NAN, NAN]])
        self.assertEqual(result["audit_status"], "preserved")
        self.assertEqual(result["added_raw_rows"], 1)
        self.assertEqual(result["added_all_nan_rows"], 1)
        self.assertEqual(result["output"]["excluded_nonfinite_f"], 2)

    def test_missing_input_observation_fails_despite_matching_intersection_flags(self) -> None:
        result = self.compare(self.rows[1:])
        self.assertEqual(result["audit_status"], "not_preserved")
        self.assertEqual(result["missing_input_hkls"], [(1, 0, 0)])
        self.assertEqual(result["changed_flags"], [])

    def test_zero_f_changed_to_nan_is_not_excluded_from_input_denominator(self) -> None:
        output = copy.deepcopy(self.rows)
        output[1][3] = NAN
        result = self.compare(output)
        self.assertEqual(result["audit_status"], "not_preserved")
        self.assertEqual(result["invalidated_input_hkls"], [(2, 0, 0)])
        self.assertEqual(result["input"]["eligible_rows"], 3)
        self.assertEqual(result["output"]["eligible_rows"], 2)

    def test_same_count_replacement_reports_both_loss_and_new_usable_key(self) -> None:
        output = copy.deepcopy(self.rows)
        output[0][0] = 5
        result = self.compare(output)
        self.assertEqual(result["input"]["eligible_rows"], result["output"]["eligible_rows"])
        self.assertEqual(result["audit_status"], "not_preserved")
        self.assertEqual(result["missing_input_hkls"], [(1, 0, 0)])
        self.assertEqual(result["new_usable_output_hkls"], [(5, 0, 0)])

    def test_changed_flags_and_observations_are_not_an_unchanged_input(self) -> None:
        for column in (3, 4, 5):
            with self.subTest(column=column):
                output = copy.deepcopy(self.rows)
                output[0][column] += 1
                result = self.compare(output)
                self.assertEqual(result["audit_status"], "not_preserved")
                key = "changed_flags" if column == 5 else "changed_observations"
                self.assertEqual(result[key], [(1, 0, 0)])

    def test_missing_or_malformed_input_flags_cannot_shrink_a_passing_domain(self) -> None:
        for flag in (NAN, float("inf"), 0.5, 9):
            with self.subTest(flag=flag):
                rows = copy.deepcopy(self.rows)
                rows[0][5] = flag
                with self.assertRaisesRegex(ValueError, "input observations have invalid flags"):
                    self.compare(rows, before=rows)

    def test_invalid_output_flags_are_reported_not_dropped_silently(self) -> None:
        output = copy.deepcopy(self.rows)
        output[0][5] = NAN
        result = self.compare(output)
        self.assertEqual(result["audit_status"], "not_preserved")
        self.assertEqual(result["invalid_output_flags"], [(1, 0, 0)])
        self.assertEqual(result["invalidated_input_hkls"], [(1, 0, 0)])

    def test_nonpositive_or_nonfinite_sigmas_are_excluded_and_counted(self) -> None:
        rows = self.rows + [[5, 0, 0, 2, 0, 0], [6, 0, 0, 2, -1, 0], [7, 0, 0, 2, NAN, 0]]
        result = self.compare(rows, before=rows)
        self.assertEqual(result["audit_status"], "preserved")
        self.assertEqual(result["input"]["excluded_nonpositive_or_nonfinite_sigf"], 3)

    def test_duplicate_and_nonintegral_hkls_are_unevaluable(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate reflection key"):
            self.compare(self.rows + [self.rows[0]])
        for key in (0.5, NAN):
            output = copy.deepcopy(self.rows)
            output[0][0] = key
            with self.assertRaisesRegex(ValueError, "non-integral reflection index"):
                self.compare(output)

    def test_context_mismatch_and_nonexplicit_flag_encoding_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "context differs"):
            audit_mtz_retention(
                mtz(self.rows), mtz(self.rows, cell="11 20 30 90 90 90"),
                input_labels=LABELS, output_labels=LABELS, flag_values={0, 1}, free_value=1,
            )
        for flags, free in (({0, 1}, None), ({0}, 0), ({0, 1.0}, 1)):
            with self.subTest(flags=flags, free=free):
                with self.assertRaisesRegex(ValueError, "encoding"):
                    audit_mtz_retention(
                        mtz(self.rows), mtz(self.rows), input_labels=LABELS,
                        output_labels=LABELS, flag_values=flags, free_value=free,
                    )

    def test_empty_observation_domain_is_not_a_vacuous_pass(self) -> None:
        rows = [[4, 0, 0, NAN, NAN, NAN]]
        with self.assertRaisesRegex(ValueError, "nonempty observed work and free"):
            self.compare(rows, before=rows)

    def assert_rejected_on_either_side(self, modified: bytes, message: str) -> None:
        valid = mtz(self.rows)
        for side, pair in (("input", (modified, valid)), ("output", (valid, modified))):
            with self.subTest(side=side), self.assertRaisesRegex(ValueError, message):
                audit_mtz_retention(
                    *pair, input_labels=LABELS, output_labels=LABELS,
                    flag_values={0, 1}, free_value=1,
                )

    def test_valm_must_be_explicit_unambiguous_nan_on_both_sides(self) -> None:
        for replacement in ([], ["VALM -999"], ["VALM 0"], ["VALM"], ["VALM nonsense"],
                            ["VALM NAN extra"], ["VALM NAN", "VALM NAN"],
                            ["VALM NAN", "VALM -999"]):
            with self.subTest(header=replacement):
                self.assert_rejected_on_either_side(
                    replace_header(mtz(self.rows), "VALM", replacement), "VALM NAN",
                )

    def test_finite_sentinel_cannot_masquerade_as_preserved_negative_f(self) -> None:
        rows = [[1, 0, 0, 10, 1, 0], [2, 0, 0, 20, 1, 1], [3, 0, 0, -999, 1, 0]]
        before = mtz(rows)
        after = replace_header(before, "VALM", ["VALM -999"])
        with self.assertRaisesRegex(ValueError, "VALM NAN"):
            audit_mtz_retention(
                before, after, input_labels=LABELS, output_labels=LABELS,
                flag_values={0, 1}, free_value=1,
            )

    def test_ncol_requires_complete_unique_zero_batch_metadata_on_both_sides(self) -> None:
        for replacement in ([], ["NCOL"], ["NCOL 6 4"], ["NCOL 6 4 1"],
                            ["NCOL 6 4 -1"], ["NCOL 6 4 nonsense"], ["NCOL 6 4 0.0"],
                            ["NCOL 6 4 0 extra"], ["NCOL 6 4 0", "NCOL 6 4 0"]):
            with self.subTest(header=replacement):
                self.assert_rejected_on_either_side(
                    replace_header(mtz(self.rows), "NCOL", replacement), "NCOL",
                )

    def test_unmerged_markers_fail_even_with_zero_declared_batches(self) -> None:
        valid = mtz(self.rows)
        self.assert_rejected_on_either_side(
            replace_header(valid, "BATCH", ["BATCH 1"]), "unmerged",
        )
        for column in ("COLUMN H Y 0 0 0", "COLUMN H B 0 0 0",
                       "COLUMN M/ISYM H 0 0 0", "COLUMN BATCH H 0 0 0"):
            with self.subTest(column=column):
                self.assert_rejected_on_either_side(
                    valid.replace(b"COLUMN H H 0 0 0".ljust(80), column.encode().ljust(80)),
                    "unmerged",
                )

    def test_metadata_admission_cli_exits_unevaluable_without_json(self) -> None:
        argv = ["audit", "input.mtz", "output.mtz", "--input-columns", "F,SIGF,FREE",
                "--output-columns", "F,SIGF,FREE", "--flag-values", "0,1", "--free-value", "1"]
        valid = mtz(self.rows)
        for keyword, replacement in (("VALM", ["VALM -999"]), ("NCOL", ["NCOL 6 4 1"]),
                                     ("BATCH", ["BATCH 1"])):
            invalid = replace_header(valid, keyword, replacement)
            for pair in ((invalid, valid), (valid, invalid)):
                with self.subTest(keyword=keyword, invalid_input=pair[0] == invalid), mock.patch(
                    "sys.argv", argv,
                ), mock.patch.object(Path, "read_bytes", side_effect=pair), redirect_stderr(
                    io.StringIO(),
                ) as stderr, redirect_stdout(io.StringIO()) as stdout:
                    with self.assertRaises(SystemExit) as raised:
                        retention.main()
                    self.assertEqual(raised.exception.code, 2)
                    self.assertIn("unevaluable:", stderr.getvalue())
                    self.assertEqual(stdout.getvalue(), "")

    def test_cli_is_read_only_and_distinguishes_preserved_lost_and_unevaluable(self) -> None:
        argv = ["audit", "input.mtz", "output.mtz", "--input-columns", "F,SIGF,FREE",
                "--output-columns", "F,SIGF,FREE", "--flag-values", "0,1", "--free-value", "1"]
        for output, expected in ((self.rows, 0), (self.rows[1:], 1)):
            with self.subTest(expected=expected), mock.patch("sys.argv", argv), mock.patch.object(
                Path, "read_bytes", side_effect=[mtz(self.rows), mtz(output)],
            ), redirect_stdout(io.StringIO()) as stdout:
                self.assertEqual(retention.main(), expected)
                self.assertEqual(json.loads(stdout.getvalue())["audit_status"],
                                 "preserved" if expected == 0 else "not_preserved")
        broken = copy.deepcopy(self.rows)
        broken[0][5] = NAN
        with mock.patch("sys.argv", argv), mock.patch.object(
            Path, "read_bytes", side_effect=[mtz(broken), mtz(self.rows)],
        ), redirect_stderr(io.StringIO()) as stderr:
            with self.assertRaises(SystemExit) as raised:
                retention.main()
            self.assertEqual(raised.exception.code, 2)
            self.assertIn("input observations have invalid flags", stderr.getvalue())

    def test_retained_1sar_all_six_outputs_invalidate_eleven_input_zero_f_rows(self) -> None:
        labels = ("F-obs", "SIGF-obs", "R-free-flags")
        with zipfile.ZipFile(REPO / ARCHIVE) as archive:
            before = archive.read("data/1sar.mtz")
            outputs = sorted(name for name in archive.namelist()
                             if name.endswith(".mtz") and name != "data/1sar.mtz")
            self.assertEqual(len(outputs), 6)
            for name in outputs:
                with self.subTest(member=name):
                    result = audit_mtz_retention(
                        before, archive.read(name), input_labels=labels,
                        output_labels=labels, flag_values={0, 1}, free_value=1,
                    )
                    self.assertEqual(result["audit_status"], "not_preserved")
                    self.assertEqual(
                        result["input_sha256"],
                        "f36d5fe685a3e524e8809d17d19ce12073acdf339eba2cfd3b0347a818850ab2",
                    )
                    self.assertEqual(result["input"]["raw_rows"], 7248)
                    self.assertEqual(result["input"]["eligible_rows"], 7228)
                    self.assertEqual(result["input"]["zero_f"], 11)
                    self.assertEqual(result["input"]["excluded_nonfinite_f"], 20)
                    self.assertEqual(result["output"]["raw_rows"], 7262)
                    self.assertEqual(result["output"]["eligible_rows"], 7217)
                    self.assertEqual(len(result["invalidated_input_hkls"]), 11)
                    self.assertEqual(result["missing_input_hkls"], [])
                    self.assertEqual(result["changed_flags"], [])
                    self.assertEqual(result["changed_observations"], [])
                    self.assertEqual(result["new_usable_output_hkls"], [])
                    self.assertEqual(result["added_all_nan_rows"], 14)

    def test_registry_and_driver_keep_both_required_policy_definitions(self) -> None:
        checks = {row["metric"]: row for row in driver_guard.load_checks(
            REPO / "ref/thresholds_and_standards.yaml")}
        registry = (REPO / "ref/thresholds_and_standards.md").read_text()
        driver = (REPO / "ref/driving_example_T03.md").read_text()
        for name in ("T03 missing deposited R-free (§3)", "T03 input-led reflection retention (§3)"):
            row = checks[name]
            self.assertEqual(driver_guard.registry_value(row["registry"], registry), row["current"])
            self.assertEqual(driver_guard.stale_hits(driver, row["retired"]), [])
            for retired in row["retired"]:
                self.assertTrue(driver_guard.stale_hits(retired, row["retired"]))
            mutated = registry.replace(row["current"], "UNSUPPORTED POLICY")
            self.assertNotEqual(driver_guard.registry_value(row["registry"], mutated), row["current"])
        self.assertIn("including zero and negative values", registry)
        self.assertIn("Missing or malformed flags on otherwise", registry)
        self.assertIn("Do not rewrite or automatically regrade issued EVAL/QDS", registry)


if __name__ == "__main__":
    unittest.main()
