#!/usr/bin/env python3
"""Hermetic CI integration tests for retained Attempt 04 offline contract replays (#1284).

Executes the unchanged committed CLI companions in isolated child processes:
- ref/research/1sar_attempt04_contract_assessment/replay_bins.py
- ref/research/1sar_attempt04_contract_assessment/replay_export.py

Never imports either companion into the test parent process (preserving parent
audit-hook and Decimal-context isolation). Writes disposable output only under
an owned subdirectory of REPO_ROOT / ".temp", preserving that directory on
failure and cleaning only that owned subdirectory when all tests pass.
"""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any
import unittest


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMP_BASE = REPO_ROOT / ".temp"

ASSESSMENT_DIR_REL = Path("ref/research/1sar_attempt04_contract_assessment")
REPLAY_BINS_REL = ASSESSMENT_DIR_REL / "replay_bins.py"
REPLAY_EXPORT_REL = ASSESSMENT_DIR_REL / "replay_export.py"
REPLAY_BINS_PATH = REPO_ROOT / REPLAY_BINS_REL
REPLAY_EXPORT_PATH = REPO_ROOT / REPLAY_EXPORT_REL

REPLAY_BINS_SHA256 = (
    "2a35ce849572e8074c1759c5e7e4dcbe1591a790670d74346145a956dba4edf2"
)
REPLAY_EXPORT_SHA256 = (
    "12d8e730fbc0c7d910386570a148cc271a263dd2eff5309c59b3e3a9feead88a"
)

R_REL = "data/coscientists/openscientist/retained_1sar_pr1007_R4_rfactors_attempt04"
A_REL = "data/coscientists/openscientist/retained_1sar_pr1007_R4_rfactors_attempt04_analysis/current"
FIRST_PINNED_TRACE_REL = f"{R_REL}/refmac/refmac_native_trace.jsonl"

EXPECTED_BINS_PIN_PATHS: tuple[str, ...] = (
    f"{R_REL}/refmac/refmac_native_trace.jsonl",
    f"{R_REL}/refmac/refmac.log",
    f"{A_REL}/native_bin_bounds.json",
    f"{A_REL}/residual_members.json",
    f"{A_REL}/completeness_members.json",
    f"{A_REL}/native_slot_records.json",
    f"{A_REL}/completeness_slot_records.json",
)

EXPECTED_EXPORT_PIN_PATHS: tuple[str, ...] = (
    f"{R_REL}/refmac/refmac_native_trace.jsonl",
    f"{R_REL}/refmac/refmac_hklout.mtz",
    f"{R_REL}/refmac/refmac_hklout_raw_export.json",
    f"{A_REL}/residual_members.json",
)

ALL_NINE_INPUT_PATHS: tuple[str, ...] = (
    f"{R_REL}/refmac/refmac_native_trace.jsonl",
    f"{R_REL}/refmac/refmac.log",
    f"{R_REL}/refmac/refmac_hklout.mtz",
    f"{R_REL}/refmac/refmac_hklout_raw_export.json",
    f"{A_REL}/native_bin_bounds.json",
    f"{A_REL}/residual_members.json",
    f"{A_REL}/completeness_members.json",
    f"{A_REL}/native_slot_records.json",
    f"{A_REL}/completeness_slot_records.json",
)

EXPECTED_BINS_OUTPUT_FILES: frozenset[str] = frozenset(
    {
        "result.json",
        "shared_bounds.json",
        "endpoint_touches.json",
        "multiple_inclusive_matches.json",
        "no_inclusive_matches.json",
        "cross_namespace_hkl_rows.json",
        "cross_namespace_RHO_word_differences.json",
        "log_table_diagnostic.json",
        "mismatches.json",
    }
)

CHILD_TIMEOUT_SECONDS = 60


def _sha256_file(path: Path) -> str:
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise RuntimeError(f"Expected regular non-symlink file: {path}")
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_regular_json(path: Path) -> Any:
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
        raise RuntimeError(f"Expected regular non-symlink JSON file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _ensure_safe_temp_base() -> Path:
    try:
        st = os.lstat(TEMP_BASE)
    except FileNotFoundError:
        TEMP_BASE.mkdir(parents=False, exist_ok=False)
        st = os.lstat(TEMP_BASE)
    if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
        raise RuntimeError(
            f"Refusing symlink or non-directory scratch root: {TEMP_BASE}"
        )
    resolved_base = TEMP_BASE.resolve(strict=True)
    if resolved_base.parent != REPO_ROOT.resolve(strict=True):
        raise RuntimeError(
            f"Scratch root does not resolve directly under REPO_ROOT: {resolved_base}"
        )
    return TEMP_BASE


def _run_companion_cli(
    script_path: Path, destination: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", "-B", str(script_path), str(destination)],
        cwd=REPO_ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=CHILD_TIMEOUT_SECONDS,
        check=False,
    )


def _format_proc_failure(
    label: str,
    proc: subprocess.CompletedProcess[str],
    owned_root: Path,
) -> str:
    stdout_tail = (proc.stdout or "")[-2000:]
    stderr_tail = (proc.stderr or "")[-2000:]
    return (
        f"{label} failed (returncode={proc.returncode}, "
        f"owned_run_root={owned_root})\n"
        f"stdout:\n{stdout_tail}\n"
        f"stderr:\n{stderr_tail}"
    )


class TestAttempt04ContractReplay(unittest.TestCase):
    """Hermetic offline CI replay suite for retained 1SAR Attempt 04 companions."""

    owned_run_root: Path
    bins_out_dir: Path
    export_out_json: Path
    companion_digests_before: dict[str, str]
    companion_digests_after: dict[str, str]
    input_digests_before: dict[str, str]
    input_digests_after: dict[str, str]
    bins_stdout_summary: dict[str, Any]
    bins_outputs: dict[str, Any]
    export_output: dict[str, Any]

    _setup_succeeded: bool = False
    _any_failure_or_error: bool = False
    _started_test_methods: set[str]
    _passed_test_methods: set[str]

    @classmethod
    def setUpClass(cls) -> None:
        cls._setup_succeeded = False
        cls._any_failure_or_error = False
        cls._started_test_methods = set()
        cls._passed_test_methods = set()

        temp_base = _ensure_safe_temp_base()
        cls.owned_run_root = Path(
            tempfile.mkdtemp(
                prefix="attempt04-contract-replay-", dir=temp_base
            )
        )
        root_st = os.lstat(cls.owned_run_root)
        if stat.S_ISLNK(root_st.st_mode) or not stat.S_ISDIR(root_st.st_mode):
            raise RuntimeError(
                f"Allocated scratch root is not a regular directory: {cls.owned_run_root}"
            )

        try:
            cls.companion_digests_before = {
                str(REPLAY_BINS_REL): _sha256_file(REPLAY_BINS_PATH),
                str(REPLAY_EXPORT_REL): _sha256_file(REPLAY_EXPORT_PATH),
            }
            if (
                cls.companion_digests_before[str(REPLAY_BINS_REL)]
                != REPLAY_BINS_SHA256
            ):
                raise AssertionError(
                    f"Unexpected replay_bins.py SHA-256: "
                    f"{cls.companion_digests_before[str(REPLAY_BINS_REL)]} "
                    f"(expected {REPLAY_BINS_SHA256}); owned_run_root={cls.owned_run_root}"
                )
            if (
                cls.companion_digests_before[str(REPLAY_EXPORT_REL)]
                != REPLAY_EXPORT_SHA256
            ):
                raise AssertionError(
                    f"Unexpected replay_export.py SHA-256: "
                    f"{cls.companion_digests_before[str(REPLAY_EXPORT_REL)]} "
                    f"(expected {REPLAY_EXPORT_SHA256}); owned_run_root={cls.owned_run_root}"
                )

            cls.input_digests_before = {}
            for rel_path in ALL_NINE_INPUT_PATHS:
                full_path = REPO_ROOT / rel_path
                if not full_path.exists():
                    raise AssertionError(
                        f"Missing required retained Attempt 04 input: {rel_path} "
                        f"(owned_run_root={cls.owned_run_root})"
                    )
                cls.input_digests_before[rel_path] = _sha256_file(full_path)

            cls.bins_out_dir = cls.owned_run_root / "bins"
            cls.export_out_json = cls.owned_run_root / "export.json"

            bins_proc = _run_companion_cli(REPLAY_BINS_PATH, cls.bins_out_dir)
            if bins_proc.returncode != 0:
                raise AssertionError(
                    _format_proc_failure(
                        "replay_bins.py positive run",
                        bins_proc,
                        cls.owned_run_root,
                    )
                )
            cls.bins_stdout_summary = json.loads(bins_proc.stdout)

            export_proc = _run_companion_cli(
                REPLAY_EXPORT_PATH, cls.export_out_json
            )
            if export_proc.returncode != 0:
                raise AssertionError(
                    _format_proc_failure(
                        "replay_export.py positive run",
                        export_proc,
                        cls.owned_run_root,
                    )
                )

            cls.companion_digests_after = {
                str(REPLAY_BINS_REL): _sha256_file(REPLAY_BINS_PATH),
                str(REPLAY_EXPORT_REL): _sha256_file(REPLAY_EXPORT_PATH),
            }
            cls.input_digests_after = {
                rel_path: _sha256_file(REPO_ROOT / rel_path)
                for rel_path in ALL_NINE_INPUT_PATHS
            }

            bins_dir_st = os.lstat(cls.bins_out_dir)
            if stat.S_ISLNK(bins_dir_st.st_mode) or not stat.S_ISDIR(
                bins_dir_st.st_mode
            ):
                raise AssertionError(
                    f"Expected regular bins output directory: {cls.bins_out_dir}"
                )
            emitted_names = [p.name for p in cls.bins_out_dir.iterdir()]
            if len(emitted_names) != len(EXPECTED_BINS_OUTPUT_FILES) or set(
                emitted_names
            ) != set(EXPECTED_BINS_OUTPUT_FILES):
                raise AssertionError(
                    f"Unexpected bins output file set in {cls.bins_out_dir}: "
                    f"{sorted(emitted_names)} != {sorted(EXPECTED_BINS_OUTPUT_FILES)}"
                )
            cls.bins_outputs = {
                name: _load_regular_json(cls.bins_out_dir / name)
                for name in sorted(EXPECTED_BINS_OUTPUT_FILES)
            }
            cls.export_output = _load_regular_json(cls.export_out_json)
            cls._setup_succeeded = True
        except BaseException:
            cls._any_failure_or_error = True
            raise

    @classmethod
    def tearDownClass(cls) -> None:
        if (
            cls._setup_succeeded
            and not cls._any_failure_or_error
            and len(cls._passed_test_methods) > 0
            and cls._started_test_methods == cls._passed_test_methods
        ):
            root_st = os.lstat(cls.owned_run_root)
            if (
                not stat.S_ISLNK(root_st.st_mode)
                and stat.S_ISDIR(root_st.st_mode)
                and cls.owned_run_root.resolve(strict=True).parent
                == TEMP_BASE.resolve(strict=True)
            ):
                shutil.rmtree(cls.owned_run_root)

    def setUp(self) -> None:
        self._current_test_passed = False
        type(self)._started_test_methods.add(self._testMethodName)

    def tearDown(self) -> None:
        if not getattr(self, "_current_test_passed", False):
            type(self)._any_failure_or_error = True

    def _mark_test_passed(self) -> None:
        self._current_test_passed = True
        type(self)._passed_test_methods.add(self._testMethodName)

    def test_source_pins_and_nine_input_digest_bindings(self) -> None:
        """Companion recipe SHA-256 pins and all nine retained input digests match before and after replay."""
        self.assertNotIn("replay_bins", sys.modules)
        self.assertNotIn("replay_export", sys.modules)

        self.assertEqual(
            self.companion_digests_before,
            {
                str(REPLAY_BINS_REL): REPLAY_BINS_SHA256,
                str(REPLAY_EXPORT_REL): REPLAY_EXPORT_SHA256,
            },
        )
        self.assertEqual(
            self.companion_digests_after, self.companion_digests_before
        )
        self.assertEqual(len(ALL_NINE_INPUT_PATHS), 9)
        self.assertEqual(len(set(ALL_NINE_INPUT_PATHS)), 9)
        self.assertEqual(len(self.input_digests_before), 9)
        self.assertEqual(self.input_digests_after, self.input_digests_before)

        bins_result = self.bins_outputs["result.json"]
        export_result = self.export_output

        self.assertEqual(bins_result["recipe_sha256"], REPLAY_BINS_SHA256)
        self.assertEqual(export_result["recipe_sha256"], REPLAY_EXPORT_SHA256)

        bins_pins = bins_result["pins"]
        export_pins = export_result["pins"]
        self.assertIsInstance(bins_pins, dict)
        self.assertIsInstance(export_pins, dict)
        self.assertEqual(len(bins_pins), 7)
        self.assertEqual(len(export_pins), 4)
        self.assertEqual(set(bins_pins.keys()), set(EXPECTED_BINS_PIN_PATHS))
        self.assertEqual(
            set(export_pins.keys()), set(EXPECTED_EXPORT_PIN_PATHS)
        )
        self.assertEqual(
            set(bins_pins.keys()) | set(export_pins.keys()),
            set(ALL_NINE_INPUT_PATHS),
        )

        overlap_keys = set(bins_pins.keys()) & set(export_pins.keys())
        self.assertEqual(
            overlap_keys,
            {
                f"{R_REL}/refmac/refmac_native_trace.jsonl",
                f"{A_REL}/residual_members.json",
            },
        )
        for shared_key in overlap_keys:
            self.assertEqual(bins_pins[shared_key], export_pins[shared_key])

        for rel_path, digest in bins_pins.items():
            self.assertEqual(digest, self.input_digests_before[rel_path])
        for rel_path, digest in export_pins.items():
            self.assertEqual(digest, self.input_digests_before[rel_path])

        self._mark_test_passed()

    def test_replay_bins_outputs_and_crosswalk_invariants(self) -> None:
        """Positive replay_bins.py run emits all nine JSON artifacts and satisfies crosswalk, bound, endpoint, and count invariants."""
        self.assertEqual(
            set(self.bins_outputs.keys()), set(EXPECTED_BINS_OUTPUT_FILES)
        )
        bins_result = self.bins_outputs["result.json"]
        shared_bounds = self.bins_outputs["shared_bounds.json"]
        endpoint_touches = self.bins_outputs["endpoint_touches.json"]
        multiple_matches = self.bins_outputs["multiple_inclusive_matches.json"]
        no_matches = self.bins_outputs["no_inclusive_matches.json"]
        crosswalk = self.bins_outputs["cross_namespace_hkl_rows.json"]
        rho_diffs = self.bins_outputs[
            "cross_namespace_RHO_word_differences.json"
        ]
        log_table = self.bins_outputs["log_table_diagnostic.json"]
        mismatches = self.bins_outputs["mismatches.json"]

        self.assertEqual(bins_result["mismatch_count"], 0)
        self.assertEqual(mismatches, [])
        self.assertIs(bins_result["raw_inputs_unchanged"], True)
        self.assertIs(bins_result["native_bin_membership_proven"], False)
        self.assertIs(bins_result["scientific_admission"], False)
        self.assertIs(bins_result["batch_eligible"], False)

        self.assertEqual(self.bins_stdout_summary["mismatch_count"], 0)
        self.assertEqual(self.bins_stdout_summary["endpoint_touch_rows"], 3)
        self.assertEqual(self.bins_stdout_summary["multiple_match_rows"], 0)
        self.assertEqual(self.bins_stdout_summary["no_match_rows"], 0)
        self.assertEqual(
            self.bins_stdout_summary[
                "cross_namespace_RHO_word_difference_count"
            ],
            2939,
        )
        self.assertIs(self.bins_stdout_summary["raw_inputs_unchanged"], True)
        self.assertIs(
            self.bins_stdout_summary["native_bin_membership_proven"], False
        )
        self.assertIs(self.bins_stdout_summary["scientific_admission"], False)

        self.assertEqual(bins_result["endpoint_touch_rows"], 3)
        self.assertEqual(len(endpoint_touches), 3)
        self.assertEqual(bins_result["multiple_match_rows"], 0)
        self.assertEqual(multiple_matches, [])
        self.assertEqual(bins_result["no_match_rows"], 0)
        self.assertEqual(no_matches, [])
        self.assertEqual(
            bins_result["cross_namespace_RHO_word_difference_count"], 2939
        )
        self.assertEqual(len(rho_diffs), 2939)

        self.assertEqual(len(shared_bounds), 21)
        shared_bound_js = [row["J"] for row in shared_bounds]
        self.assertEqual(shared_bound_js, list(range(1, 22)))
        self.assertEqual(len(set(shared_bound_js)), 21)

        self.assertEqual(len(log_table), 20)
        log_table_js = [row["J"] for row in log_table]
        self.assertEqual(log_table_js, list(range(1, 21)))
        self.assertEqual(len(set(log_table_js)), 20)

        checks = bins_result["checks"]
        self.assertEqual(
            checks["active_residual_to_observed_exact_HKL_J"], 7217
        )
        self.assertEqual(
            checks["observed_to_active_residual_exact_HKL_J"], 7217
        )
        self.assertEqual(checks["retained_bound_matches_raw"], 21)
        self.assertEqual(checks["bounds_same_words"], 21)
        self.assertEqual(checks["adjacent_shared_endpoint"], 19)
        self.assertEqual(checks["retained_array_length"], 2)
        self.assertEqual(checks["retained_member_matches_raw"], 14510)
        self.assertEqual(checks["residual_slot_population"], 42)
        self.assertEqual(checks["completeness_slot_population"], 42)
        self.assertEqual(
            checks["printed_count_matches_completeness_slot"], 20
        )
        self.assertEqual(checks["captured_J_matches_source_comparison"], 14510)
        self.assertEqual(checks["residual_sigma_and_first_match"], 7248)
        self.assertEqual(checks["completeness_terminal"], 7262)

        count_rows = bins_result["counts"]
        self.assertIsInstance(count_rows, list)
        count_keys = [
            (
                row["namespace"],
                row["IFREE"],
                row["included_or_observed"],
                row["slot"],
            )
            for row in count_rows
        ]
        self.assertEqual(len(count_rows), len(set(count_keys)))
        for row in count_rows:
            self.assertIsInstance(row["included_or_observed"], bool)

        slot21_rows = [row for row in count_rows if row["slot"] == 21]
        self.assertEqual(len(slot21_rows), 6)
        slot21_map = {
            (
                row["namespace"],
                row["IFREE"],
                row["included_or_observed"],
            ): row["count"]
            for row in slot21_rows
        }
        self.assertEqual(len(slot21_map), 6)
        self.assertEqual(
            slot21_map,
            {
                ("residual_lsq", 1, False): 31,
                ("residual_lsq", 1, True): 6494,
                ("residual_lsq", 2, True): 723,
                ("reporting_completeness", 1, False): 45,
                ("reporting_completeness", 1, True): 6494,
                ("reporting_completeness", 2, True): 723,
            },
        )

        self.assertEqual(len(crosswalk), 7262)
        crosswalk_hkls = [tuple(row["hkl"]) for row in crosswalk]
        self.assertEqual(len(set(crosswalk_hkls)), 7262)

        shared_rows = [
            row
            for row in crosswalk
            if row["residual"] is not None and row["completeness"] is not None
        ]
        completeness_only_rows = [
            row
            for row in crosswalk
            if row["residual"] is None and row["completeness"] is not None
        ]
        residual_only_rows = [
            row
            for row in crosswalk
            if row["residual"] is not None and row["completeness"] is None
        ]
        self.assertEqual(len(shared_rows), 7248)
        self.assertEqual(len(completeness_only_rows), 14)
        self.assertEqual(len(residual_only_rows), 0)

        for row in shared_rows:
            res_side = row["residual"]
            comp_side = row["completeness"]
            self.assertIsInstance(res_side["included"], bool)
            self.assertIsInstance(comp_side["included"], bool)
            self.assertIsInstance(res_side["J"], list)
            self.assertIsInstance(comp_side["J"], list)
            self.assertEqual(res_side["J"], comp_side["J"])
            self.assertEqual(len(res_side["J"]), 1)
            self.assertIsInstance(res_side["input_record"], dict)
            self.assertIsInstance(comp_side["input_record"], dict)
            self.assertEqual(res_side["IFREE"], comp_side["IFREE"])
            self.assertIs(res_side["included"], comp_side["included"])

        active_residual_rows = [
            row
            for row in crosswalk
            if row["residual"] is not None
            and row["residual"]["included"] is True
        ]
        observed_completeness_rows = [
            row
            for row in crosswalk
            if row["completeness"] is not None
            and row["completeness"]["included"] is True
        ]
        self.assertEqual(len(active_residual_rows), 7217)
        self.assertEqual(len(observed_completeness_rows), 7217)
        self.assertEqual(
            [tuple(r["hkl"]) for r in active_residual_rows],
            [tuple(r["hkl"]) for r in observed_completeness_rows],
        )

        missing_completeness_rows = [
            row
            for row in crosswalk
            if row["completeness"] is not None
            and row["completeness"]["included"] is False
        ]
        shared_excluded_rows = [
            row
            for row in missing_completeness_rows
            if row["residual"] is not None
            and row["residual"]["included"] is False
        ]
        extra_asu_rows = [
            row for row in missing_completeness_rows if row["residual"] is None
        ]
        self.assertEqual(len(missing_completeness_rows), 45)
        self.assertEqual(len(shared_excluded_rows), 31)
        self.assertEqual(len(extra_asu_rows), 14)

        for diff_row in rho_diffs:
            self.assertIsNotNone(diff_row["residual"])
            self.assertIsNotNone(diff_row["completeness"])
            self.assertNotEqual(
                diff_row["residual"]["RHO"]["bits_hex"],
                diff_row["completeness"]["RHO"]["bits_hex"],
            )
            self.assertEqual(
                diff_row["residual"]["J"], diff_row["completeness"]["J"]
            )

        endpoint_summary = [
            (
                row["record"]["namespace"],
                tuple(row["hkl"]),
                row["row_index"],
                row["record"]["sequence"],
                row["record"]["_line"],
                tuple(row["actual_J"]),
                tuple((ep["J"], ep["side"]) for ep in row["endpoints"]),
            )
            for row in endpoint_touches
        ]
        self.assertEqual(len(endpoint_summary), 3)
        self.assertEqual(
            endpoint_summary,
            [
                (
                    "reporting_completeness",
                    (12, 25, 6),
                    4368,
                    17491,
                    17492,
                    (20,),
                    ((20, "SMAXB"),),
                ),
                (
                    "residual_lsq",
                    (1, 1, 0),
                    13,
                    29226,
                    29227,
                    (1,),
                    ((1, "SMINB"),),
                ),
                (
                    "residual_lsq",
                    (12, 25, 6),
                    4361,
                    68273,
                    68274,
                    (20,),
                    ((20, "SMAXB"),),
                ),
            ],
        )

        event_counts = bins_result["event_counts"]
        self.assertEqual(sum(event_counts.values()), 94283)
        self.assertEqual(event_counts["header"], 1)
        self.assertEqual(event_counts["writer_close"], 1)
        self.assertEqual(
            sum(event_counts.values())
            - event_counts["header"]
            - event_counts["writer_close"],
            94281,
        )
        self.assertEqual(event_counts["completeness_begin"], 1)
        self.assertEqual(event_counts["completeness_end"], 1)
        self.assertEqual(event_counts["lsq_coef_begin"], 1)
        self.assertEqual(event_counts["lsq_coef_end"], 1)
        self.assertEqual(event_counts["refmac_normal_termination"], 1)

        self._mark_test_passed()

    def test_replay_export_outputs_and_numerical_invariants(self) -> None:
        """Positive replay_export.py run emits exact rationals, distinct carriers, Decimal70 diagnostics, and row-error provenance."""
        export_result = self.export_output
        self.assertIsInstance(export_result, dict)

        self.assertIs(export_result["scientific_admission"], False)
        self.assertIs(export_result["native_fp_equivalence"], False)
        self.assertIs(export_result["native_print_read_observed"], False)
        self.assertIs(export_result["raw_inputs_unchanged"], True)

        self.assertEqual(
            export_result["counts"],
            {
                "included_1": 6494,
                "included_2": 723,
                "excluded_original_domain": 31,
            },
        )
        self.assertEqual(export_result["distinct_captured_EXPAN_words"], 7207)

        event_counts = export_result["event_counts"]
        self.assertEqual(sum(event_counts.values()), 94283)
        self.assertEqual(event_counts["header"], 1)
        self.assertEqual(event_counts["writer_close"], 1)
        self.assertEqual(
            sum(event_counts.values())
            - event_counts["header"]
            - event_counts["writer_close"],
            94281,
        )
        self.assertEqual(event_counts["completeness_begin"], 1)
        self.assertEqual(event_counts["completeness_end"], 1)
        self.assertEqual(event_counts["lsq_coef_begin"], 1)
        self.assertEqual(event_counts["lsq_coef_end"], 1)
        self.assertEqual(event_counts["refmac_normal_termination"], 1)
        self.assertEqual(
            event_counts, self.bins_outputs["result.json"]["event_counts"]
        )

        results = export_result["results"]
        self.assertEqual(set(results.keys()), {"work", "free"})

        expected_rationals = {
            ("work", "export"): (
                "573914156947/2097152",
                "6771678021525/4194304",
                "1147828313894/6771678021525",
            ),
            ("free", "export"): (
                "38960352489/1048576",
                "91401113563/524288",
                "38960352489/182802227126",
            ),
            ("work", "captured_operand"): (
                "1147753088519/4194304",
                "211869291659/131072",
                "1147753088519/6779817333088",
            ),
            ("free", "captured_operand"): (
                "155910436577/4194304",
                "183176551473/1048576",
                "155910436577/732706205892",
            ),
        }
        for (part, family), (exp_num, exp_den, exp_ratio) in (
            expected_rationals.items()
        ):
            fam_obj = results[part][family]
            self.assertEqual(fam_obj["numerator"], exp_num)
            self.assertEqual(fam_obj["signed_denominator"], exp_den)
            self.assertEqual(fam_obj["ratio_fraction"], exp_ratio)
            num_f = Fraction(fam_obj["numerator"])
            den_f = Fraction(fam_obj["signed_denominator"])
            ratio_f = Fraction(fam_obj["ratio_fraction"])
            self.assertGreater(den_f, 0)
            self.assertEqual(num_f / den_f, ratio_f)

        self.assertEqual(
            results["work"]["source_normalized_decimal70_diagnostic"],
            "0.1695042658878123837046935232356538785926731765034921625279295250921786",
        )
        self.assertEqual(
            results["free"]["source_normalized_decimal70_diagnostic"],
            "0.2131284345044351190212637056497967058205567321069025976561843268438724",
        )
        self.assertEqual(
            results["work"]["export_reweighted_decimal70_diagnostic"],
            "0.1692896776513226396858089506352541338740467390579404214304510621715800",
        )
        self.assertEqual(
            results["free"]["export_reweighted_decimal70_diagnostic"],
            "0.2127871106762674140232984791105544381135007481759794189990877631246237",
        )

        carriers = export_result["carrier_rendering"]
        self.assertEqual(len(carriers), 2)
        self.assertEqual(
            carriers[0],
            {
                "line": 94279,
                "sequence": 94278,
                "event": "lsq_final_carrier_work",
                "source_hook_id": "final_carrier_work",
                "bits_hex": "3E2D5A39",
                "exact_fraction": "11360825/67108864",
                "exact_decimal": "0.16928948462009429931640625",
                "F10_4_nearest": "    0.1693",
                "F10_3_nearest": "     0.169",
            },
        )
        self.assertEqual(
            carriers[1],
            {
                "line": 94280,
                "sequence": 94279,
                "event": "lsq_final_carrier_free",
                "source_hook_id": "final_carrier_free",
                "bits_hex": "3E59E4E1",
                "exact_fraction": "14279905/67108864",
                "exact_decimal": "0.21278716623783111572265625",
                "F10_4_nearest": "    0.2128",
                "F10_3_nearest": "     0.213",
            },
        )
        for carrier_item, part_key in (
            (carriers[0], "work"),
            (carriers[1], "free"),
        ):
            self.assertNotEqual(
                carrier_item["line"], carrier_item["sequence"]
            )
            carrier_frac = Fraction(carrier_item["exact_fraction"])
            captured_frac = Fraction(
                results[part_key]["captured_operand"]["ratio_fraction"]
            )
            export_frac = Fraction(
                results[part_key]["export"]["ratio_fraction"]
            )
            self.assertNotEqual(carrier_frac, captured_frac)
            self.assertNotEqual(captured_frac, export_frac)
            self.assertNotEqual(carrier_frac, export_frac)

        max_errors = export_result["source_relation_max_errors"]
        self.assertEqual(
            set(max_errors.keys()),
            {
                "export_fo_minus_YOS_div_EXPAN",
                "export_fc_minus_YC_div_EXPAN",
            },
        )
        fo_err = max_errors["export_fo_minus_YOS_div_EXPAN"]
        self.assertEqual(
            fo_err,
            {
                "absolute": "0.000084774432870319411272550855185332696623370627195408834077040874",
                "signed": "-0.000084774432870319411272550855185332696623370627195408834077040874",
                "hkl": [4, 3, 0],
                "native_row": 67,
                "trace_line": 29714,
                "trace_sequence": 29713,
                "export_row_index": 1619,
            },
        )
        self.assertNotEqual(fo_err["trace_line"], fo_err["trace_sequence"])
        fo_signed_dec = Decimal(fo_err["signed"])
        fo_abs_dec = Decimal(fo_err["absolute"])
        self.assertIs(fo_signed_dec.is_signed(), True)
        self.assertEqual(fo_signed_dec.copy_abs(), fo_abs_dec)
        self.assertGreater(fo_abs_dec, Decimal(0))

        fc_err = max_errors["export_fc_minus_YC_div_EXPAN"]
        self.assertEqual(
            fc_err,
            {
                "absolute": "0.001005530697907463136582135721496329401617086077297248816382299453",
                "signed": "0.001005530697907463136582135721496329401617086077297248816382299453",
                "hkl": [0, 2, 1],
                "native_row": 683,
                "trace_line": 35223,
                "trace_sequence": 35222,
                "export_row_index": 22,
            },
        )
        self.assertNotEqual(fc_err["trace_line"], fc_err["trace_sequence"])
        fc_signed_dec = Decimal(fc_err["signed"])
        fc_abs_dec = Decimal(fc_err["absolute"])
        self.assertIs(fc_signed_dec.is_signed(), False)
        self.assertEqual(fc_signed_dec.copy_abs(), fc_abs_dec)
        self.assertGreater(fc_abs_dec, Decimal(0))

        self._mark_test_passed()

    def test_negative_control_existing_output_refused_preserving_sentinel(
        self,
    ) -> None:
        """Both companions refuse preexisting output targets and preserve owned sentinel bytes and inodes."""
        neg_root = self.owned_run_root / "neg_existing_output"
        neg_root.mkdir(parents=False, exist_ok=False)

        existing_bins_dir = neg_root / "existing_bins"
        existing_bins_dir.mkdir(parents=False, exist_ok=False)
        bins_sentinel_file = existing_bins_dir / "sentinel.txt"
        bins_sentinel_bytes = b"OWNED BINS SENTINEL DO NOT OVERWRITE\n"
        bins_sentinel_file.write_bytes(bins_sentinel_bytes)
        bins_sentinel_st_before = os.lstat(bins_sentinel_file)

        bins_proc = _run_companion_cli(REPLAY_BINS_PATH, existing_bins_dir)
        self.assertNotEqual(bins_proc.returncode, 0)
        self.assertIn("Refusing existing output path", bins_proc.stderr)
        self.assertEqual(
            [p.name for p in existing_bins_dir.iterdir()], ["sentinel.txt"]
        )
        bins_sentinel_st_after = os.lstat(bins_sentinel_file)
        self.assertEqual(
            (bins_sentinel_st_after.st_dev, bins_sentinel_st_after.st_ino),
            (bins_sentinel_st_before.st_dev, bins_sentinel_st_before.st_ino),
        )
        self.assertEqual(bins_sentinel_file.read_bytes(), bins_sentinel_bytes)

        existing_export_json = neg_root / "existing_export.json"
        export_sentinel_bytes = (
            b'{"sentinel": "owned-export-do-not-overwrite"}\n'
        )
        existing_export_json.write_bytes(export_sentinel_bytes)
        export_sentinel_st_before = os.lstat(existing_export_json)

        export_proc = _run_companion_cli(
            REPLAY_EXPORT_PATH, existing_export_json
        )
        self.assertNotEqual(export_proc.returncode, 0)
        self.assertIn("Refusing existing output path", export_proc.stderr)
        self.assertEqual(
            sorted(p.name for p in neg_root.iterdir()),
            ["existing_bins", "existing_export.json"],
        )
        export_sentinel_st_after = os.lstat(existing_export_json)
        self.assertEqual(
            (export_sentinel_st_after.st_dev, export_sentinel_st_after.st_ino),
            (
                export_sentinel_st_before.st_dev,
                export_sentinel_st_before.st_ino,
            ),
        )
        self.assertEqual(
            existing_export_json.read_bytes(), export_sentinel_bytes
        )

        self._mark_test_passed()

    def test_negative_control_corrupt_first_pinned_trace_fails_before_output(
        self,
    ) -> None:
        """Unchanged companions copied into a tiny isolated mirror fail on a corrupt first pinned trace before creating output."""
        neg_mirror_base = self.owned_run_root / "neg_corrupt_trace_mirror"
        neg_mirror_base.mkdir(parents=False, exist_ok=False)

        for label, companion_path, expected_sha, out_name in (
            ("bins", REPLAY_BINS_PATH, REPLAY_BINS_SHA256, "bins_out"),
            (
                "export",
                REPLAY_EXPORT_PATH,
                REPLAY_EXPORT_SHA256,
                "export_out.json",
            ),
        ):
            case_dir = neg_mirror_base / label
            mirror_root = case_dir / "mirror_workspace"
            copied_script = (
                mirror_root / ASSESSMENT_DIR_REL / companion_path.name
            )
            copied_script.parent.mkdir(parents=True, exist_ok=False)
            shutil.copyfile(companion_path, copied_script)
            self.assertEqual(_sha256_file(copied_script), expected_sha)

            corrupt_trace_path = mirror_root / FIRST_PINNED_TRACE_REL
            corrupt_trace_path.parent.mkdir(parents=True, exist_ok=False)
            corrupt_trace_path.write_bytes(b'{"corrupt_trace": true}\n')

            out_parent = case_dir / "external_output_parent"
            out_parent.mkdir(parents=True, exist_ok=False)
            out_target = out_parent / out_name

            proc = _run_companion_cli(copied_script, out_target)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn(
                f"SHA-256 mismatch for {FIRST_PINNED_TRACE_REL}",
                proc.stderr,
            )
            self.assertFalse(os.path.lexists(out_target))
            self.assertEqual(list(out_parent.iterdir()), [])

        self._mark_test_passed()

    def test_negative_control_child_audit_hook_rejects_prohibited_events(
        self,
    ) -> None:
        """Synthetic sys.audit notifications in isolated child processes confirm subprocess and socket rejection."""
        probe_code = (
            "import json, runpy, sys\n"
            "runpy.run_path(sys.argv[1], run_name='__audit_probe__')\n"
            "observed = []\n"
            "for ev, args in (\n"
            "    ('subprocess.Popen', ('/nonexistent', ['/nonexistent'], None, None)),\n"
            "    ('socket.connect', (None, ('127.0.0.1', 9))),\n"
            "):\n"
            "    try:\n"
            "        sys.audit(ev, *args)\n"
            "    except RuntimeError as exc:\n"
            "        observed.append({'event': ev, 'type': type(exc).__name__, 'message': str(exc)})\n"
            "print(json.dumps(observed))\n"
        )
        for companion_path in (REPLAY_BINS_PATH, REPLAY_EXPORT_PATH):
            proc = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-B",
                    "-c",
                    probe_code,
                    str(companion_path),
                ],
                cwd=REPO_ROOT,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=CHILD_TIMEOUT_SECONDS,
                check=False,
            )
            self.assertEqual(
                proc.returncode,
                0,
                _format_proc_failure(
                    f"audit probe for {companion_path.name}",
                    proc,
                    self.owned_run_root,
                ),
            )
            observed = json.loads(proc.stdout)
            self.assertEqual(
                observed,
                [
                    {
                        "event": "subprocess.Popen",
                        "type": "RuntimeError",
                        "message": "Prohibited operation: subprocess.Popen",
                    },
                    {
                        "event": "socket.connect",
                        "type": "RuntimeError",
                        "message": "Prohibited operation: socket.connect",
                    },
                ],
            )

        self._mark_test_passed()


if __name__ == "__main__":
    unittest.main()
