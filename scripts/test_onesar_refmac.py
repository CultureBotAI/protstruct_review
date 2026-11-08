#!/usr/bin/env python3
"""Focused hermetic tests for scripts/onesar_refmac.py (Tasks 302, 306, 309, 319, 311, 313, 331, 333, 314, 315, 338, 340, 316, 343, 317, 347).

Covers the shared fixture foundation, Group 1 operation/header cases 1-11,
Group 2 XML/exact-numeric cases 12-16 and MTZ mixed-summary/RESO case 22,
Groups 3-4 MTZ raw export, 1-to-1 HKL audit, cell/context representations, and
malformed-header promotion cases 17-21, Group 4 PDB comparison/inventory/
promotion cases 23-25, Group 5 / Group 8 admitted-path, checkpoint,
immutability, directory scanner, and restored-parent recheck cases 26-32,
Group 6 immutable writer and collision cases 33-36, and Groups 7-8 late
publication, bounded correction, failure/collision ordering, primary cause /
structured-None preservation, and outcome-derivation idempotency cases 37-40:
1. Actual-archive complete capture with exact argv/stdin/env subset, secret
   exclusion, raw output/setup/binary verification, and false scientific/EVAL/
   QDS/canary admission flags.
2. Malformed on-disk REFMAC log despite plausible CompletedProcess.stdout.
3. Nonzero runner exit with retained outputs and original process failure.
4. Timeout after partial output retaining partial bytes and original timeout
   exception identity as primary_cause.
5. Returned CompletedProcess(args=None, returncode=0) refused at
   refmac_argv_verification in both post-execution checkpoint and final records.
6. Self-contained MTZ header cases for native DWAVEL, legacy DWAV, absent
   wavelength, and present zero-valued wavelength (0.00000) across both
   _raw_export_mtz_file and _extract_mtz_raw_header_cell_context.
7. Existing evidence_root rejection at staging before any runner call while
   preserving an owned marker file inside that existing directory.
8. Fake refmac5 executable resolved outside the configured CCP4 prefix rejected
   at preflight before any runner call.
9. Runner mutates an owned staged input and raises a declared exception after
   retaining partial outputs, recording both the original runner failure and the
   distinct input-mutation failure while preserving the original exception as
   primary_cause.
10. Runner removes one owned staged input, retaining baseline identity,
    completed-child metadata, and raw outputs while distinguishing missing-input
    diagnostics from byte-content mutation.
11. Explicitly labelled unexpected exception at the narrow XMLOUT audit boundary
    after otherwise valid fake outputs, persisting contextual audit_exception
    failure and preserving the original exception identity.
12. Direct _audit_refmac_xmlout across supported literal, absent file,
    well-formed unsupported shape, malformed XML, explicit -999 sentinel,
    log-present unproven cycle/shared-scalar association, and finite R > 1.
13. Malformed XMLOUT through the full collector operation with persisted
    rejected_malformed_xml audit and final failure records.
14. Exact R-token comparisons: leading/trailing-zero identity vs Decimal
    equality, independently rounded 0.1235/0.123, exact-disjoint 28/29-place
    tokens, and large 10^28 pair under conditional interval arithmetic.
15. 4301-place valid XML token preserving raw/value identity with unavailable
    optional interval diagnostics, plus bounded compact exponent rejection and
    sentinel retention without mutating global Decimal/int-string settings.
16. Bounded exact integer/fraction text formatting beyond default 4300-digit
    int-string limits, and one unavailable-component MTZ cell tuple maximum.

No CCP4, PHENIX, or gemmi binaries are executed.
"""

from __future__ import annotations

import copy
import decimal
import errno
import hashlib
import json
import math
import os
import stat
import struct
import subprocess
import sys
import tempfile
import unittest
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence
from unittest.mock import patch

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import audit_1sar_retained_evidence  # noqa: E402
import onesar_refmac  # noqa: E402
import onesar_refmac_log  # noqa: E402
import onesar_rerun  # noqa: E402
import toolchain  # noqa: E402


REPO_ROOT = _SCRIPTS_DIR.parent
COMMITTED_ARCHIVE = REPO_ROOT / onesar_rerun.ARCHIVE_REL_PATH
COMMITTED_ARCHIVE_SHA256 = (
    "9fc5352284b7ffa7763c633a3eb4d3d0db96b8c25a1be9bcea361722d2c53054"
)

# Copied verbatim as text from scripts/test_onesar_refmac_log.py:359-410
# (2054 bytes, SHA-256 392992723c3a3f1f6f8368642bef28da317eacf5002556dd294e789e995449eb)
# so this suite never imports test_onesar_refmac_log.py or test_toolchain.py.
# Reflection populations in this synthetic log (6532 work, 344 free) remain
# explicitly synthetic and distinct from the genuine 1SAR archive.
SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG = """\
 ### CCP4 9.0: Refmac_5.8.0430     version 5.8.0430 : 01/01/24##
  Data line--- NCYC 0
  Refinement cycles       :     0

$TABLE: Cycle    1. Rfactor analysis, F distribution v resln  :
$GRAPHS:Cycle    1. <Rfactor> v. resln :N:1,6,7,11,12:
$$
M(4SSQ/LL) NR_used %_obs M(Fo_used) M(Fc_used) Rf_used WR_used
NR_free M(Fo_free) M(Fc_free) Rf_free   WR_free $$
$$
 0.050    3100  99.50    42.0    40.1  0.18  0.21     160    41.2    39.0  0.22  0.25
 0.150    3432  98.10    21.5    20.4  0.20  0.23     184    20.8    19.5  0.24  0.27
$$

 $TABLE: Cycle    1. Fom(<cos(DelPhi)>-acentric, centric, overall v resln:
 $GRAPHS:Cycle    1. M(Fom) v. resln :N:1,3,5,7,8:
 $$
 <4SSQ/LL> NREFa  FOMa  NREFc FOMc NREFall FOMall  SigmaA_Fc1 $$
 $$
  0.0500  3000   0.850   100   0.780  3100   0.848  0.910
  0.1500  3332   0.810   100   0.740  3432   0.808  0.885
 $$
Resolution limits                    =     35.000     1.800
Number of used reflections           =       6532
Percentage observed                  =    98.7500
Percentage of free reflections       =     5.0029
Overall R factor                     =     0.1912
Free R factor                        =     0.2315
Overall weighted R factor            =     0.2210
Free weighted R factor               =     0.2610
Overall weighted R2 factor           =     0.2890
Free weighted R2 factor              =     0.3310
Overall figure of merit              =     0.8270
-----------------------------------------------------------------------------

$TABLE: Rfactor analysis, stats vs cycle  :
$GRAPHS:<Rfactor> vs cycle :N:1,2,3:
$$
    Ncyc    Rfact    Rfree     FOM      -LL     -LLfree  rmsBOND  zBOND rmsANGL  zANGL rmsCHIRAL $$
$$
       0   0.1912   0.2315   0.827     12345.     654.3   0.0081  0.410   1.120  0.550   0.045
 $$
 $TEXT:Result: $$ Final results $$
                      Initial    Final
           R factor    0.1912   0.1912
             R free    0.2315   0.2315
     Rms BondLength    0.0081   0.0081
      Rms BondAngle    1.1200   1.1200
     Rms ChirVolume    0.0450   0.0450
 $$
"""

_FALSE_SCIENTIFIC_ADMISSION_KEYS: tuple[str, ...] = (
    "canonical_eval_qds_eligible",
    "eval_admission_eligible",
    "qds_admission_eligible",
    "canary_admission_eligible",
    "scientific_admission_proven",
    "all_preregistered_gates_passed",
)
_PROOF_TO_UNPROVEN_REASON_KEYS: tuple[tuple[str, str], ...] = (
    ("effective_hkls_proven", "effective_hkls_unproven_reason"),
    ("native_bin_membership_proven", "native_bin_membership_unproven_reason"),
    (
        "native_residual_reconstruction_proven",
        "native_residual_reconstruction_unproven_reason",
    ),
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _build_literal_mtz_bytes(
    *,
    columns: list[tuple[str, str, int]],
    rows: list[tuple[float, ...]],
    header_cards_before_columns: list[str],
) -> bytes:
    """Self-contained MTZ byte builder for pure header/metadata unit tests."""
    ncols = len(columns)
    nrows = len(rows)
    data_words: list[bytes] = []
    col_mins = [math.inf] * ncols
    col_maxs = [-math.inf] * ncols
    for row in rows:
        if len(row) != ncols:
            raise ValueError(f"Row length {len(row)} != ncols {ncols}")
        for idx, val in enumerate(row):
            fval = float(val)
            data_words.append(struct.pack("<f", fval))
            if math.isfinite(fval):
                col_mins[idx] = min(col_mins[idx], fval)
                col_maxs[idx] = max(col_maxs[idx], fval)
    for idx in range(ncols):
        if not math.isfinite(col_mins[idx]):
            col_mins[idx] = 0.0
            col_maxs[idx] = 0.0
    data_block = b"".join(data_words)
    header_record_1indexed = (80 + len(data_block)) // 4 + 1

    cards: list[str] = [
        "VERS MTZ:V1.1",
        "TITLE Literal test MTZ",
        f"NCOL {ncols:8d} {nrows:12d} {0:8d}",
        *header_cards_before_columns,
    ]
    for idx, (label, ctype, ds_id) in enumerate(columns):
        cards.append(
            f"COLUMN {label:<30s} {ctype} {col_mins[idx]:17.4f} {col_maxs[idx]:17.4f} {ds_id:>4d}"
        )
    cards.append("END")

    encoded_cards = b"".join(c.ljust(80).encode("ascii") for c in cards)
    preamble = (
        b"MTZ "
        + struct.pack("<I", header_record_1indexed)
        + bytes.fromhex("44410000")
        + b"\x00" * (80 - 12)
    )
    return preamble + data_block + encoded_cards


_STANDARD_HKLIN_COLUMNS: list[tuple[str, str, int]] = [
    ("H", "H", 0),
    ("K", "H", 0),
    ("L", "H", 0),
    ("F-obs", "F", 1),
    ("SIGF-obs", "Q", 1),
    ("R-free-flags", "I", 1),
]

_BASELINE_HKLOUT_COLUMNS: list[tuple[str, str, int]] = [
    ("H", "H", 0),
    ("K", "H", 0),
    ("L", "H", 0),
    ("F-obs", "F", 1),
    ("SIGF-obs", "Q", 1),
    ("R-free-flags", "I", 1),
    ("FC_ALL_LS", "F", 1),
]

_EXTENDED_HKLOUT_COLUMNS: list[tuple[str, str, int]] = [
    *_BASELINE_HKLOUT_COLUMNS,
    ("PHIC_ALL_LS", "P", 1),
    ("FC_ALL", "F", 1),
    ("FWT", "F", 1),
    ("PHWT", "P", 1),
]


def _build_standard_mtz_header_cards(
    *,
    cell_tokens: Sequence[str] = (
        "10.0000",
        "10.0000",
        "10.0000",
        "90.0000",
        "90.0000",
        "90.0000",
    ),
    dcell_0_tokens: Sequence[str] | None = None,
    dcell_1_tokens: Sequence[str] | None = None,
    reso_tokens: tuple[str, str] = ("0.0100000000000000", "0.2500000000000000"),
    valm_record: str | None = "VALM NAN",
    extra_cards: Sequence[str] = (),
) -> list[str]:
    """Build coherent two-dataset MTZ header cards before COLUMN records."""
    cell_str = " ".join(cell_tokens)
    dcell0_str = " ".join(dcell_0_tokens if dcell_0_tokens is not None else cell_tokens)
    dcell1_str = " ".join(dcell_1_tokens if dcell_1_tokens is not None else cell_tokens)
    cards: list[str] = []
    if valm_record is not None:
        cards.append(valm_record)
    cards.extend(
        [
            f"CELL {cell_str}",
            "SORT 1 2 3 0 0",
            "SYMINF 1 1 P 1 'P 1' PG1",
            "SYMM X,Y,Z",
            f"RESO {reso_tokens[0]} {reso_tokens[1]}",
            "NDIF 2",
            "PROJECT 0 HKL_base",
            "CRYSTAL 0 HKL_base",
            "DATASET 0 HKL_base",
            f"DCELL 0 {dcell0_str}",
            "DWAV 0 0.00000",
            "PROJECT 1 project",
            "CRYSTAL 1 crystal",
            "DATASET 1 dataset",
            f"DCELL 1 {dcell1_str}",
            "DWAV 1 1.54180",
            *extra_cards,
        ]
    )
    return cards


def _patch_mtz_data_words(
    mtz_bytes: bytes,
    *,
    ncols: int,
    nrows: int,
    patches: Sequence[tuple[int, int, int]],
) -> bytes:
    """Patch 32-bit little-endian data words at (row_index, col_index) with bounds checks."""
    if ncols <= 0 or nrows <= 0:
        raise ValueError(f"Invalid MTZ dimensions ncols={ncols}, nrows={nrows}")
    if len(mtz_bytes) < 80:
        raise ValueError(
            f"MTZ byte stream shorter than 80-byte preamble: {len(mtz_bytes)}"
        )
    (hdr_loc_words,) = struct.unpack_from("<I", mtz_bytes, 4)
    expected_hdr_offset = 80 + 4 * ncols * nrows
    actual_hdr_offset = (hdr_loc_words - 1) * 4
    if actual_hdr_offset != expected_hdr_offset:
        raise ValueError(
            f"Preamble hdr_loc_words={hdr_loc_words} byte offset {actual_hdr_offset} "
            f"!= expected {expected_hdr_offset} for ncols={ncols}, nrows={nrows}"
        )
    if len(mtz_bytes) < expected_hdr_offset:
        raise ValueError(
            f"MTZ byte length {len(mtz_bytes)} < data end offset {expected_hdr_offset}"
        )
    buf = bytearray(mtz_bytes)
    for row_index, col_index, word in patches:
        if not (0 <= row_index < nrows):
            raise ValueError(f"row_index {row_index} out of bounds [0, {nrows})")
        if not (0 <= col_index < ncols):
            raise ValueError(f"col_index {col_index} out of bounds [0, {ncols})")
        if not (0 <= word <= 0xFFFFFFFF):
            raise ValueError(f"word {word:#x} out of 32-bit unsigned range")
        byte_offset = 80 + 4 * (row_index * ncols + col_index)
        struct.pack_into("<I", buf, byte_offset, word)
    return bytes(buf)


class _FakeCcp4Fixture:
    """Hermetic fake CCP4 installation prefix, setup script, and refmac5 binary."""

    def __init__(self, base_dir: Path) -> None:
        self.prefix = (base_dir / "fake_ccp4").resolve()
        self.bin_dir = self.prefix / "bin"
        self.lib_dir = self.prefix / "lib"
        self.data_dir = self.lib_dir / "data"
        self.monomers_dir = self.data_dir / "monomers"
        self.include_dir = self.prefix / "include"
        for d in (
            self.bin_dir,
            self.lib_dir,
            self.data_dir,
            self.monomers_dir,
            self.include_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

        self.setup_script = self.bin_dir / "ccp4.setup-sh"
        self.setup_script.write_text(
            "#!/bin/sh\n# Hermetic fake ccp4.setup-sh for unit tests\n",
            encoding="utf-8",
        )
        self.refmac_bin = self.bin_dir / "refmac5"
        self.refmac_bin.write_text(
            "#!/bin/sh\n# Hermetic fake refmac5 binary for unit tests\nexit 0\n",
            encoding="utf-8",
        )
        self.refmac_bin.chmod(0o755)

        self.setup_sha256 = _sha256_bytes(self.setup_script.read_bytes())
        self.refmac_sha256 = _sha256_bytes(self.refmac_bin.read_bytes())

        self.secret_markers: dict[str, str] = {
            "GITHUB_TOKEN": "ghp_secret_marker_never_persist_9911",
            "AWS_SECRET_ACCESS_KEY": "aws_secret_marker_never_persist_9912",
            "OPENAI_API_KEY": "sk_secret_marker_never_persist_9913",
            "CUSTOM_SECRET_TOKEN": "tok_secret_marker_never_persist_9914",
        }
        self.allowed_ccp4_vars: dict[str, str] = {
            "CCP4_MASTER": str(self.prefix.parent),
            "CCP4": str(self.prefix),
            "CBIN": str(self.bin_dir),
            "CLIB": str(self.lib_dir),
            "CLIBD": str(self.data_dir),
            "CLIBD_MON": str(self.monomers_dir) + "/",
            "CINCL": str(self.include_dir),
        }
        self.sourced_env: dict[str, str] = {
            **self.allowed_ccp4_vars,
            "PATH": f"{self.bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin",
            **self.secret_markers,
        }


class TestRefmacCollectorFirstSlice(unittest.TestCase):
    """Task 166 Group 1 operation and header collector tests (Tasks 302, 306, 309: cases 1-11)."""

    _tmp_dir: tempfile.TemporaryDirectory[str]
    repo_root: Path
    fake_ccp4: _FakeCcp4Fixture

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp_dir = tempfile.TemporaryDirectory()
        base = Path(cls._tmp_dir.name).resolve(strict=True)
        cls.repo_root = base / "repo"
        cls.repo_root.mkdir(parents=True, exist_ok=True)
        cls.fake_ccp4 = _FakeCcp4Fixture(base)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp_dir.cleanup()

    def _run_with_fake_ccp4(
        self,
        case_name: str,
        runner: Callable[..., subprocess.CompletedProcess[str]],
        *,
        timeout: float = 60.0,
        sourced_env_override: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        evidence_root = self.repo_root / "runs" / case_name
        env_to_return = (
            dict(sourced_env_override)
            if sourced_env_override is not None
            else dict(self.fake_ccp4.sourced_env)
        )
        with (
            patch.dict(
                os.environ,
                {"PROTSTRUCT_CCP4_SETUP": str(self.fake_ccp4.setup_script)},
                clear=False,
            ),
            patch.object(toolchain, "CCP4_SETUP", self.fake_ccp4.setup_script),
            patch.object(
                toolchain,
                "ccp4_environment",
                return_value=env_to_return,
            ),
        ):
            return onesar_refmac.run_refmac_rfactor_operation(
                evidence_root,
                subject_id="R4",
                repo_root=self.repo_root,
                archive_path=COMMITTED_ARCHIVE,
                timeout=timeout,
                require_no_protstruct_overrides=False,
                runner=runner,
            )

    def _reopen_and_verify_json_artifact(
        self, artifact_ref: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        self.assertIsInstance(artifact_ref, Mapping)
        assert isinstance(artifact_ref, Mapping)
        path_str = artifact_ref.get("path")
        self.assertIsInstance(path_str, str)
        disk_path = Path(str(path_str))
        self.assertTrue(disk_path.is_file(), f"Missing artifact file: {disk_path}")
        self.assertFalse(disk_path.is_symlink(), f"Symlink artifact file: {disk_path}")
        raw_bytes = disk_path.read_bytes()
        self.assertEqual(_sha256_bytes(raw_bytes), artifact_ref["sha256"])
        self.assertEqual(len(raw_bytes), artifact_ref["size_bytes"])

        def _reject_nonfinite_json_constant(token: str) -> Any:
            self.fail(
                f"Non-standard JSON constant {token!r} persisted in {disk_path}"
            )

        loaded = json.loads(
            raw_bytes.decode("utf-8"),
            parse_constant=_reject_nonfinite_json_constant,
        )
        self.assertIsInstance(loaded, dict)
        return loaded

    def _assert_all_scientific_admission_flags_false(
        self, payload: Mapping[str, Any]
    ) -> None:
        for key in _FALSE_SCIENTIFIC_ADMISSION_KEYS:
            self.assertIs(
                payload.get(key),
                False,
                f"Expected {key} to be False, got {payload.get(key)!r}",
            )
        for proof_key, reason_key in _PROOF_TO_UNPROVEN_REASON_KEYS:
            self.assertIs(
                payload.get(proof_key),
                False,
                f"Expected {proof_key} to be False, got {payload.get(proof_key)!r}",
            )
            reason = payload.get(reason_key)
            self.assertIsInstance(
                reason,
                str,
                f"Expected {reason_key} to be a non-empty str, got {reason!r}",
            )
            self.assertTrue(bool(str(reason).strip()))

    def _expected_argv_for_evidence_root(self, evidence_root: Path) -> list[str]:
        inputs_dir = evidence_root / "inputs"
        refmac_dir = evidence_root / "refmac"
        return [
            str(self.fake_ccp4.refmac_bin),
            "XYZIN",
            str(inputs_dir / "original_model.pdb"),
            "HKLIN",
            str(inputs_dir / "projected_observations.mtz"),
            "XYZOUT",
            str(refmac_dir / "refmac_xyzout.pdb"),
            "HKLOUT",
            str(refmac_dir / "refmac_hklout.mtz"),
            "XMLOUT",
            str(refmac_dir / "refmac_xmlout.xml"),
        ]

    @staticmethod
    def _write_capture_success_outputs(
        xyzin_path: Path,
        hklin_path: Path,
        xyzout_path: Path,
        hklout_path: Path,
        log_path: Path,
    ) -> int:
        xyzout_path.write_bytes(xyzin_path.read_bytes())
        hklout_path.write_bytes(hklin_path.read_bytes())
        log_path.write_text(SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG, encoding="utf-8")
        return 0

    def test_actual_archive_complete_capture(self) -> None:
        """Case 1: Actual-archive complete capture, env/secret filtering, and false admission flags."""
        self.assertEqual(
            dict(onesar_refmac.HKLOUT_OBSERVATION_ROLE_TO_LABEL),
            {
                "FP": "F-obs",
                "SIGFP": "SIGF-obs",
                "FREE": "R-free-flags",
            },
        )
        self.assertEqual(
            onesar_refmac.HKLOUT_OBSERVATION_LABELS,
            ("F-obs", "SIGF-obs", "R-free-flags"),
        )
        log_fixture_bytes = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.encode("utf-8")
        self.assertEqual(len(log_fixture_bytes), 2054)
        self.assertEqual(
            _sha256_bytes(log_fixture_bytes),
            "392992723c3a3f1f6f8368642bef28da317eacf5002556dd294e789e995449eb",
        )
        captured_calls: list[dict[str, Any]] = []

        def runner(
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
            edit_count = self._write_capture_success_outputs(
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
            captured_calls.append(
                {
                    "xyzin": xyzin,
                    "hklin": hklin,
                    "xyzout": xyzout,
                    "hklout": hklout,
                    "log_path": log_path,
                    "xml_output": xml_output,
                    "keywords": keywords,
                    "cwd": cwd,
                    "timeout": timeout,
                    "executable": executable,
                    "env": dict(env),
                    "ccp4": ccp4,
                    "argv": argv,
                    "header_edit_count": edit_count,
                }
            )
            return subprocess.CompletedProcess(
                args=argv,
                returncode=0,
                stdout=SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG,
                stderr="",
            )

        result = self._run_with_fake_ccp4("case1_complete_capture", runner)
        self.assertEqual(len(captured_calls), 1)
        call = captured_calls[0]
        self.assertEqual(call["header_edit_count"], 0)
        # Independently fixed REFMAC5 stdin expectation per supported 7-key LABOUT
        # and native HKLIN observation label contract (scripts/onesar_refmac.py:70-89).
        expected_stdin_keywords = (
            "LABIN FP=F-obs SIGFP=SIGF-obs FREE=R-free-flags\n"
            "FREE 1\n"
            "REFI BREF MIXED\n"
            "NCYC 0\n"
            "MONI MANY\n"
            "LABOUT FC=FC PHIC=PHIC FWT=FWT PHWT=PHWT DELFWT=DELFWT PHDELWT=PHDELWT FOM=FOM\n"
            "END\n"
        )
        expected_stdin_lines = expected_stdin_keywords.splitlines()
        expected_stdin_bytes = expected_stdin_keywords.encode("utf-8")
        expected_stdin_sha256 = _sha256_bytes(expected_stdin_bytes)
        expected_stdin_size_bytes = len(expected_stdin_bytes)
        self.assertEqual(call["keywords"], expected_stdin_keywords)
        self.assertIs(call["ccp4"], False)
        self.assertEqual(call["executable"], self.fake_ccp4.refmac_bin)

        evidence_root = Path(result["evidence_root"])
        expected_argv = self._expected_argv_for_evidence_root(evidence_root)
        self.assertEqual(call["argv"], expected_argv)
        self.assertEqual(result["invocation"]["expected_argv"], expected_argv)
        self.assertEqual(result["invocation"]["completed_argv"], expected_argv)
        self.assertIs(result["invocation"]["completed_argv_available"], True)
        self.assertIs(result["invocation"]["argv_matches_expected"], True)
        self.assertEqual(
            result["invocation"]["stdin_keywords"], expected_stdin_keywords
        )
        self.assertEqual(
            result["invocation"]["stdin_keywords_lines"],
            expected_stdin_lines,
        )
        self.assertEqual(
            result["invocation"]["stdin_keywords_sha256"],
            expected_stdin_sha256,
        )
        keywords_file_path = Path(result["invocation"]["keywords_file_path"])
        self.assertEqual(
            keywords_file_path,
            evidence_root / "refmac" / "refmac_keywords.txt",
        )
        self.assertEqual(
            result["paths"]["keywords_path"], str(keywords_file_path)
        )
        self.assertTrue(keywords_file_path.is_file())
        self.assertFalse(keywords_file_path.is_symlink())
        keywords_file_bytes = keywords_file_path.read_bytes()
        self.assertEqual(keywords_file_bytes, expected_stdin_bytes)
        self.assertEqual(
            keywords_file_bytes.decode("utf-8"), expected_stdin_keywords
        )
        self.assertEqual(
            _sha256_bytes(keywords_file_bytes), expected_stdin_sha256
        )
        self.assertEqual(len(keywords_file_bytes), expected_stdin_size_bytes)
        kw_base = result["input_immutability"]["keywords_file_baseline"]
        kw_post = result["input_immutability"]["keywords_file_post_run"]
        self.assertEqual(kw_base["path"], str(keywords_file_path))
        self.assertEqual(kw_base["sha256"], expected_stdin_sha256)
        self.assertEqual(kw_base["size_bytes"], expected_stdin_size_bytes)
        self.assertEqual(kw_post["path"], str(keywords_file_path))
        self.assertEqual(kw_post["sha256"], expected_stdin_sha256)
        self.assertEqual(kw_post["size_bytes"], expected_stdin_size_bytes)
        self.assertIs(kw_post["matches_baseline"], True)

        # Verify setup/binary identities and bound CCP4 configuration subset.
        tc = result["toolchain"]
        self.assertEqual(
            tc["configured_installation_prefix"], str(self.fake_ccp4.prefix)
        )
        self.assertEqual(
            tc["setup_script"]["resolved_path"], str(self.fake_ccp4.setup_script)
        )
        self.assertEqual(
            tc["setup_script"]["sha256"], self.fake_ccp4.setup_sha256
        )
        self.assertEqual(
            tc["refmac5_binary"]["resolved_path"], str(self.fake_ccp4.refmac_bin)
        )
        self.assertEqual(
            tc["refmac5_binary"]["sha256"], self.fake_ccp4.refmac_sha256
        )
        self.assertEqual(
            tc["bound_ccp4_configuration"], self.fake_ccp4.allowed_ccp4_vars
        )
        for secret_key in self.fake_ccp4.secret_markers:
            self.assertNotIn(secret_key, tc["bound_ccp4_configuration"])

        # Reopen authoritative manifest, diagnostics, checkpoints, and audit JSONs from returned references.
        manifest_on_disk = self._reopen_and_verify_json_artifact(
            result["manifest_json"]
        )
        diagnostics_on_disk = self._reopen_and_verify_json_artifact(
            result["diagnostics_json"]
        )
        pre_ckpt = self._reopen_and_verify_json_artifact(
            result["pre_execution_checkpoint_json"]
        )
        self.assertEqual(
            pre_ckpt["keywords_file_baseline"]["path"],
            str(keywords_file_path),
        )
        self.assertEqual(
            pre_ckpt["keywords_file_baseline"]["sha256"],
            expected_stdin_sha256,
        )
        self.assertEqual(
            pre_ckpt["keywords_file_baseline"]["size_bytes"],
            expected_stdin_size_bytes,
        )
        post_ckpt = self._reopen_and_verify_json_artifact(
            result["post_execution_checkpoint_json"]
        )
        parsed_log_on_disk = self._reopen_and_verify_json_artifact(
            result["parsed_log_json"]
        )
        xmlout_audit_on_disk = self._reopen_and_verify_json_artifact(
            result["xmlout_audit_json"]
        )
        self._reopen_and_verify_json_artifact(result["hklout_raw_export_json"])
        self._reopen_and_verify_json_artifact(result["hklout_audit_json"])
        self._reopen_and_verify_json_artifact(result["xyzout_audit_json"])

        self.assertEqual(
            parsed_log_on_disk["reconciled_final_cycle"]["nr_used_sum"], 6532
        )
        self.assertEqual(
            parsed_log_on_disk["reconciled_final_cycle"]["nr_free_sum"], 344
        )
        self.assertIs(xmlout_audit_on_disk["present"], False)
        self.assertIs(xmlout_audit_on_disk["valid"], True)
        self.assertEqual(xmlout_audit_on_disk["status"], "absent")
        self.assertIsNone(xmlout_audit_on_disk["well_formed_xml"])

        for doc in (manifest_on_disk, diagnostics_on_disk, pre_ckpt, post_ckpt):
            serialized = json.dumps(doc, sort_keys=True)
            for secret_key, secret_val in self.fake_ccp4.secret_markers.items():
                self.assertNotIn(secret_key, serialized)
                self.assertNotIn(secret_val, serialized)

        # Verify reflection table bytes in HKLOUT are unchanged from projected_observations.mtz.
        proj_bytes = Path(result["paths"]["projected_mtz_path"]).read_bytes()
        hklout_bytes = Path(result["paths"]["hklout_path"]).read_bytes()
        (hdr_loc_words,) = struct.unpack_from("<I", proj_bytes, 4)
        hdr_offset = (hdr_loc_words - 1) * 4
        self.assertEqual(proj_bytes[:hdr_offset], hklout_bytes[:hdr_offset])
        self.assertFalse(Path(result["paths"]["xmlout_path"]).exists())

        # Verify status, operation_checks, and scientific/admission refusals.
        for payload in (result, manifest_on_disk, diagnostics_on_disk):
            self.assertEqual(
                payload["status"], "diagnostic_captured_gates_unproven"
            )
            self.assertIsNone(payload["failed_stage"])
            self.assertEqual(payload["failures"], [])
            self.assertIs(payload["publication_pair_complete"], True)
            self.assertIsNone(payload["publication_terminal_failure"])
            checks = payload["operation_checks"]
            self.assertIs(checks["preflight_toolchain_resolved"], True)
            self.assertIs(checks["worker_launched"], True)
            self.assertIs(checks["collector_succeeded"], True)
            self.assertIs(checks["stage1_collection_succeeded"], True)
            self.assertIs(checks["stage2_audits_succeeded"], True)
            self.assertIs(checks["process_returncode_zero"], True)
            self.assertIs(checks["completed_argv_available"], True)
            self.assertIs(checks["argv_matches_expected"], True)
            self.assertIs(checks["xmlout_audit_valid"], True)
            self.assertEqual(checks["xmlout_audit_status"], "absent")
            self.assertIs(checks["hklout_audit_valid"], True)
            self.assertIs(checks["xyzout_audit_valid"], True)
            self.assertIs(payload["model_preservation_proven"], True)
            self._assert_all_scientific_admission_flags_false(payload)

    def test_disk_log_malformed_despite_plausible_completed_process_stdout(
        self,
    ) -> None:
        """Case 2: Malformed on-disk log fails at parse_refmac_log despite plausible CompletedProcess.stdout."""
        malformed_log_bytes = b"### CCP4 9.0.015: Refmac_5.8.0430 : truncated malformed disk log\n"
        runner_calls: list[Path] = []

        def runner(
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
            runner_calls.append(executable)
            self._write_capture_success_outputs(
                xyzin, hklin, xyzout, hklout, log_path
            )
            log_path.write_bytes(malformed_log_bytes)
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
                stdout=SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG,
                stderr="",
            )

        with self.assertRaises(onesar_refmac.RefmacCollectorError) as ctx:
            self._run_with_fake_ccp4("case2_malformed_disk_log", runner)

        self.assertEqual(runner_calls, [self.fake_ccp4.refmac_bin])
        err = ctx.exception
        self.assertEqual(err.failed_stage, "parse_refmac_log")
        self.assertEqual(err.returncode, 0)
        self.assertIsInstance(err.primary_cause, ValueError)
        self.assertIs(err.__cause__, err.primary_cause)
        self.assertIs(err.publication_pair_complete, True)
        self.assertIsNotNone(err.manifest_path)
        self.assertIsNotNone(err.diagnostics_path)

        assert err.manifest_payload is not None
        assert err.diagnostics_payload is not None
        manifest_disk = self._reopen_and_verify_json_artifact(
            {
                "path": str(err.manifest_path),
                "sha256": _sha256_bytes(Path(err.manifest_path).read_bytes()),
                "size_bytes": Path(err.manifest_path).stat().st_size,
            }
        )
        diagnostics_disk = self._reopen_and_verify_json_artifact(
            err.manifest_payload["diagnostics_json"]
        )
        self.assertIs(
            manifest_disk["operation_checks"]["preflight_toolchain_resolved"],
            True,
        )
        self.assertIs(
            manifest_disk["operation_checks"]["worker_launched"], True
        )
        self.assertEqual(
            manifest_disk["raw_outputs"]["log"]["sha256"],
            _sha256_bytes(malformed_log_bytes),
        )
        self.assertEqual(
            manifest_disk["raw_outputs"]["log"]["size_bytes"],
            len(malformed_log_bytes),
        )
        self.assertIsNotNone(diagnostics_disk["log_parse_error"])
        self.assertIsNone(manifest_disk["parsed_log"])
        self.assertIs(
            manifest_disk["operation_checks"]["native_r_pair_parsed"], False
        )
        self.assertEqual(manifest_disk["failed_stage"], "parse_refmac_log")
        self.assertEqual(
            manifest_disk["failures"][0]["failed_stage"], "parse_refmac_log"
        )
        self.assertIs(manifest_disk["model_preservation_proven"], False)
        self._assert_all_scientific_admission_flags_false(manifest_disk)
        self._assert_all_scientific_admission_flags_false(diagnostics_disk)

    def test_nonzero_runner_exit_with_outputs(self) -> None:
        """Case 3: Nonzero runner exit retains outputs and records refmac_returncode as primary failure."""
        runner_calls: list[Path] = []

        def runner(
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
            runner_calls.append(executable)
            self._write_capture_success_outputs(
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
                returncode=7,
                stdout="",
                stderr="REFMAC exited with code 7",
            )

        with self.assertRaises(onesar_refmac.RefmacCollectorError) as ctx:
            self._run_with_fake_ccp4("case3_nonzero_exit", runner)

        self.assertEqual(runner_calls, [self.fake_ccp4.refmac_bin])
        err = ctx.exception
        self.assertEqual(err.failed_stage, "refmac_returncode")
        self.assertEqual(err.returncode, 7)
        self.assertIsNone(err.primary_cause)
        self.assertIsNone(err.__cause__)
        self.assertIs(err.publication_pair_complete, True)

        assert err.manifest_payload is not None
        diagnostics_disk = self._reopen_and_verify_json_artifact(
            err.manifest_payload["diagnostics_json"]
        )
        self.assertIs(
            diagnostics_disk["operation_checks"]["preflight_toolchain_resolved"],
            True,
        )
        self.assertIs(
            diagnostics_disk["operation_checks"]["worker_launched"], True
        )
        for key in ("log", "xyzout", "hklout"):
            raw_info = diagnostics_disk["raw_outputs"][key]
            self.assertIs(raw_info["exists"], True)
            self.assertIs(raw_info["is_regular_file"], True)
            disk_bytes = Path(raw_info["path"]).read_bytes()
            self.assertEqual(raw_info["sha256"], _sha256_bytes(disk_bytes))
            self.assertEqual(raw_info["size_bytes"], len(disk_bytes))

        self.assertEqual(diagnostics_disk["status"], "failed")
        self.assertEqual(diagnostics_disk["failed_stage"], "refmac_returncode")
        self.assertEqual(
            diagnostics_disk["failures"][0]["failed_stage"], "refmac_returncode"
        )
        self.assertEqual(diagnostics_disk["failures"][0]["returncode"], 7)
        self.assertIs(
            diagnostics_disk["operation_checks"]["process_returncode_zero"],
            False,
        )
        self.assertIs(
            diagnostics_disk["operation_checks"]["completed_argv_available"],
            True,
        )
        self.assertIs(
            diagnostics_disk["operation_checks"]["argv_matches_expected"], True
        )
        self.assertIs(diagnostics_disk["model_preservation_proven"], False)
        self._assert_all_scientific_admission_flags_false(diagnostics_disk)

    def test_timeout_after_partial_output(self) -> None:
        """Case 4: Timeout after partial output retains partial bytes and original TimeoutExpired cause."""
        partial_log_bytes = (
            b"### CCP4 9.0.015: Refmac_5.8.0430 : partial log before timeout\n"
        )
        partial_xyz_bytes = (
            b"REMARK partial xyzout written before timeout\nEND\n"
        )
        raised_timeout: list[subprocess.TimeoutExpired] = []

        def runner(
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
            log_path.write_bytes(partial_log_bytes)
            xyzout.write_bytes(partial_xyz_bytes)
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
            exc = subprocess.TimeoutExpired(cmd=argv, timeout=timeout)
            raised_timeout.append(exc)
            raise exc

        with self.assertRaises(onesar_refmac.RefmacCollectorError) as ctx:
            self._run_with_fake_ccp4(
                "case4_timeout_partial_output", runner, timeout=12.5
            )

        err = ctx.exception
        self.assertEqual(len(raised_timeout), 1)
        self.assertEqual(err.failed_stage, "refmac_timeout")
        self.assertIsNone(err.returncode)
        self.assertIs(err.primary_cause, raised_timeout[0])
        self.assertIs(err.__cause__, raised_timeout[0])
        self.assertIs(err.publication_pair_complete, True)

        assert err.manifest_payload is not None
        diagnostics_disk = self._reopen_and_verify_json_artifact(
            err.manifest_payload["diagnostics_json"]
        )
        post_ckpt = self._reopen_and_verify_json_artifact(
            diagnostics_disk["post_execution_checkpoint_json"]
        )
        self.assertIs(
            diagnostics_disk["operation_checks"]["preflight_toolchain_resolved"],
            True,
        )
        self.assertIs(
            diagnostics_disk["operation_checks"]["worker_launched"], True
        )
        self.assertEqual(
            diagnostics_disk["raw_outputs"]["log"]["sha256"],
            _sha256_bytes(partial_log_bytes),
        )
        self.assertEqual(
            diagnostics_disk["raw_outputs"]["xyzout"]["sha256"],
            _sha256_bytes(partial_xyz_bytes),
        )
        self.assertIs(diagnostics_disk["raw_outputs"]["hklout"]["exists"], False)
        self.assertIs(diagnostics_disk["invocation"]["timed_out"], True)
        self.assertIsNone(diagnostics_disk["invocation"]["completed_argv"])
        self.assertIs(
            diagnostics_disk["invocation"]["completed_argv_available"], False
        )
        self.assertIs(
            diagnostics_disk["invocation"]["argv_matches_expected"], False
        )
        for doc in (post_ckpt, diagnostics_disk):
            self.assertEqual(doc["failed_stage"], "refmac_timeout")
            self.assertEqual(doc["failures"][0]["failed_stage"], "refmac_timeout")
            self.assertIs(
                doc["operation_checks"]["completed_argv_available"], False
            )
            self.assertIs(doc["operation_checks"]["argv_matches_expected"], False)
            self.assertNotIn(
                "refmac_argv_verification",
                [f["failed_stage"] for f in doc["failures"]],
            )
        self._assert_all_scientific_admission_flags_false(diagnostics_disk)

    def test_returned_args_none_after_otherwise_successful_capture(self) -> None:
        """Case 5: CompletedProcess(args=None, returncode=0) is refused at refmac_argv_verification (#1053)."""
        runner_calls: list[Path] = []

        def runner(
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
            runner_calls.append(executable)
            self._write_capture_success_outputs(
                xyzin, hklin, xyzout, hklout, log_path
            )
            return subprocess.CompletedProcess(
                args=None,  # type: ignore[arg-type]
                returncode=0,
                stdout=SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG,
                stderr="",
            )

        with self.assertRaises(onesar_refmac.RefmacCollectorError) as ctx:
            self._run_with_fake_ccp4("case5_returned_args_none", runner)

        self.assertEqual(runner_calls, [self.fake_ccp4.refmac_bin])
        err = ctx.exception
        self.assertEqual(err.failed_stage, "refmac_argv_verification")
        self.assertEqual(err.returncode, 0)
        self.assertIsNone(err.primary_cause)
        self.assertIsNone(err.__cause__)
        self.assertIs(err.publication_pair_complete, True)

        assert err.manifest_payload is not None
        diagnostics_disk = self._reopen_and_verify_json_artifact(
            err.manifest_payload["diagnostics_json"]
        )
        post_ckpt = self._reopen_and_verify_json_artifact(
            diagnostics_disk["post_execution_checkpoint_json"]
        )
        self.assertIs(
            diagnostics_disk["operation_checks"]["preflight_toolchain_resolved"],
            True,
        )
        self.assertIs(
            diagnostics_disk["operation_checks"]["worker_launched"], True
        )
        self.assertIsNone(diagnostics_disk["invocation"]["completed_argv"])
        self.assertIs(
            diagnostics_disk["invocation"]["completed_argv_available"], False
        )
        self.assertIs(
            diagnostics_disk["invocation"]["argv_matches_expected"], False
        )
        for doc in (post_ckpt, diagnostics_disk):
            self.assertEqual(doc["status"], "failed")
            self.assertEqual(doc["failed_stage"], "refmac_argv_verification")
            self.assertEqual(
                doc["failures"][0]["failed_stage"], "refmac_argv_verification"
            )
            self.assertIn(
                "CompletedProcess.args is None (unavailable)",
                doc["failures"][0]["exception_message"],
            )
            self.assertIs(
                doc["operation_checks"]["completed_argv_available"], False
            )
            self.assertIs(doc["operation_checks"]["argv_matches_expected"], False)
            self.assertIs(
                doc["operation_checks"]["process_returncode_zero"], False
            )
        self.assertIs(
            diagnostics_disk["operation_checks"]["collector_succeeded"], False
        )
        self.assertIs(
            diagnostics_disk["preregistered_gates"][
                "gate_1_immutable_input_and_toolchain_admission"
            ]["proven"],
            False,
        )
        self.assertIs(diagnostics_disk["model_preservation_proven"], False)
        self._assert_all_scientific_admission_flags_false(diagnostics_disk)

    def test_dwavel_and_dwav_header_metadata_and_absent_vs_zero_wavelength(
        self,
    ) -> None:
        """Case 6: Literal MTZ header cases for DWAVEL, DWAV, absent wavelength, and 0.00000 (#1052)."""
        raw_dwavel_1 = "DWAVEL       1    1.54180"
        raw_dwav_2 = "DWAV         2    0.97950"
        raw_dwavel_4_zero = "DWAVEL       4    0.00000"
        raw_dwav_5_zero = "DWAV         5    0.00000"

        header_cards = [
            "CELL    50.0000   60.0000   70.0000   90.0000   90.0000   90.0000",
            "SORT    1 2 3 0 0",
            "SYMINF 4 2 P 19 'P 21 21 21' PG222",
            "SYMM X,  Y,  Z",
            "SYMM 1/2-X, -Y, 1/2+Z",
            "SYMM 1/2+X, 1/2-Y, -Z",
            "SYMM -X, 1/2+Y, 1/2-Z",
            "RESO 0.00100000 0.25000000",
            "VALM NAN",
            "NDIF        5",
            "PROJECT       1 PROJ1",
            "CRYSTAL       1 XTAL1",
            "DATASET       1 NATIVE_DWAVEL",
            "DCELL         1   50.0000   60.0000   70.0000   90.0000   90.0000   90.0000",
            raw_dwavel_1,
            "PROJECT       2 PROJ2",
            "CRYSTAL       2 XTAL2",
            "DATASET       2 LEGACY_DWAV",
            "DCELL         2   50.0000   60.0000   70.0000   90.0000   90.0000   90.0000",
            raw_dwav_2,
            "PROJECT       3 PROJ3",
            "CRYSTAL       3 XTAL3",
            "DATASET       3 ABSENT_WAVELENGTH",
            "DCELL         3   50.0000   60.0000   70.0000   90.0000   90.0000   90.0000",
            "PROJECT       4 PROJ4",
            "CRYSTAL       4 XTAL4",
            "DATASET       4 ZERO_DWAVEL",
            "DCELL         4   50.0000   60.0000   70.0000   90.0000   90.0000   90.0000",
            raw_dwavel_4_zero,
            "PROJECT       5 PROJ5",
            "CRYSTAL       5 XTAL5",
            "DATASET       5 ZERO_DWAV",
            "DCELL         5   50.0000   60.0000   70.0000   90.0000   90.0000   90.0000",
            raw_dwav_5_zero,
        ]
        mtz_bytes = _build_literal_mtz_bytes(
            columns=[
                ("H", "H", 1),
                ("K", "H", 1),
                ("L", "H", 1),
                ("FP", "F", 1),
                ("SIGFP", "Q", 1),
                ("FREE", "I", 1),
            ],
            rows=[(1.0, 0.0, 0.0, 10.0, 1.0, 0.0)],
            header_cards_before_columns=header_cards,
        )
        expected_sha256 = _sha256_bytes(mtz_bytes)

        mtz_dir = self.repo_root / "runs" / "case6_dwavel_literal"
        mtz_dir.mkdir(parents=True, exist_ok=True)
        mtz_path = mtz_dir / "literal_dwavel.mtz"
        mtz_path.write_bytes(mtz_bytes)

        mtz_info = onesar_refmac._inspect_output_artifact(mtz_path, root=mtz_dir)
        raw_export, exported_bytes = onesar_refmac._raw_export_mtz_file(
            mtz_path, mtz_info=mtz_info
        )
        raw_ctx = onesar_refmac._extract_mtz_raw_header_cell_context(
            mtz_bytes, label="LITERAL_MTZ"
        )

        # Raw MTZ bytes and raw keyword cards remain untouched.
        self.assertEqual(exported_bytes, mtz_bytes)
        self.assertEqual(_sha256_bytes(mtz_path.read_bytes()), expected_sha256)
        self.assertEqual(
            raw_export["keyword_records"]["DWAVEL"],
            [raw_dwavel_1, raw_dwavel_4_zero],
        )
        self.assertEqual(
            raw_export["keyword_records"]["DWAV"],
            [raw_dwav_2, raw_dwav_5_zero],
        )
        self.assertIs(raw_ctx["valid"], True)
        self.assertIs(
            raw_ctx["header_order_dcell_observation"][
                "native_crystal_or_dataset_selection_proven"
            ],
            False,
        )
        self.assertIs(
            raw_ctx["header_order_dcell_observation"][
                "executable_cmtzlib_linkage_proven"
            ],
            False,
        )

        expected_by_setid: dict[str, dict[str, Any]] = {
            "1": {
                "dataset": "NATIVE_DWAVEL",
                "dwav_tokens": ["1.54180"],
                "dwav_keyword": "DWAVEL",
                "dwav_raw_record": raw_dwavel_1,
                "wavelength_present": True,
            },
            "2": {
                "dataset": "LEGACY_DWAV",
                "dwav_tokens": ["0.97950"],
                "dwav_keyword": "DWAV",
                "dwav_raw_record": raw_dwav_2,
                "wavelength_present": True,
            },
            "3": {
                "dataset": "ABSENT_WAVELENGTH",
                "dwav_tokens": [],
                "dwav_keyword": None,
                "dwav_raw_record": None,
                "wavelength_present": False,
            },
            "4": {
                "dataset": "ZERO_DWAVEL",
                "dwav_tokens": ["0.00000"],
                "dwav_keyword": "DWAVEL",
                "dwav_raw_record": raw_dwavel_4_zero,
                "wavelength_present": True,
            },
            "5": {
                "dataset": "ZERO_DWAV",
                "dwav_tokens": ["0.00000"],
                "dwav_keyword": "DWAV",
                "dwav_raw_record": raw_dwav_5_zero,
                "wavelength_present": True,
            },
        }

        export_datasets = raw_export["header_parse"]["datasets"]
        ctx_dcell_by_setid = {
            rec["dataset_setid"]: rec for rec in raw_ctx["dcell_records"]
        }
        self.assertEqual(set(export_datasets.keys()), set(expected_by_setid.keys()))
        self.assertEqual(
            set(ctx_dcell_by_setid.keys()), set(expected_by_setid.keys())
        )

        for setid, exp in expected_by_setid.items():
            for source_name, ds_rec in (
                ("raw_export", export_datasets[setid]),
                ("header_ctx", ctx_dcell_by_setid[setid]),
            ):
                self.assertEqual(
                    ds_rec["dataset"], exp["dataset"], f"{source_name}[{setid}]"
                )
                self.assertEqual(
                    ds_rec["dwav_tokens"],
                    exp["dwav_tokens"],
                    f"{source_name}[{setid}]",
                )
                self.assertEqual(
                    ds_rec["dwavel_tokens"],
                    exp["dwav_tokens"],
                    f"{source_name}[{setid}]",
                )
                self.assertEqual(
                    ds_rec["dwav_keyword"],
                    exp["dwav_keyword"],
                    f"{source_name}[{setid}]",
                )
                self.assertEqual(
                    ds_rec["dwav_raw_record"],
                    exp["dwav_raw_record"],
                    f"{source_name}[{setid}]",
                )
                self.assertIs(
                    ds_rec["wavelength_present"],
                    exp["wavelength_present"],
                    f"{source_name}[{setid}]",
                )

    def test_existing_evidence_root_rejected_before_runner_preserving_marker(
        self,
    ) -> None:
        """Case 7: Existing evidence_root is rejected at staging before any runner call and preserves owned marker."""
        self.assertEqual(COMMITTED_ARCHIVE_SHA256, onesar_rerun.ARCHIVE_SHA256)
        pre_archive_sha256 = _sha256_bytes(COMMITTED_ARCHIVE.read_bytes())
        self.assertEqual(pre_archive_sha256, COMMITTED_ARCHIVE_SHA256)

        case_name = "case7_existing_evidence_root"
        evidence_root = self.repo_root / "runs" / case_name
        evidence_root.mkdir(parents=True, exist_ok=False)
        marker_path = evidence_root / "owned_marker.txt"
        marker_bytes = b"preserve-owned-marker-before-staging\n"
        marker_sha256 = _sha256_bytes(marker_bytes)
        marker_path.write_bytes(marker_bytes)
        runner_calls: list[Path] = []

        def runner(
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
            runner_calls.append(executable)
            raise AssertionError("runner must not be called when evidence_root exists")

        with self.assertRaises(FileExistsError) as ctx:
            self._run_with_fake_ccp4(case_name, runner)

        self.assertEqual(runner_calls, [])
        self.assertIn("Fresh evidence root required", str(ctx.exception))
        self.assertIn(str(evidence_root), str(ctx.exception))
        self.assertTrue(marker_path.is_file())
        self.assertFalse(marker_path.is_symlink())
        self.assertEqual(marker_path.read_bytes(), marker_bytes)
        self.assertEqual(_sha256_bytes(marker_path.read_bytes()), marker_sha256)
        self.assertEqual(
            sorted(p.name for p in evidence_root.iterdir()),
            ["owned_marker.txt"],
        )
        post_archive_sha256 = _sha256_bytes(COMMITTED_ARCHIVE.read_bytes())
        self.assertEqual(post_archive_sha256, pre_archive_sha256)
        self.assertEqual(post_archive_sha256, COMMITTED_ARCHIVE_SHA256)

    def test_executable_outside_configured_ccp4_prefix_rejected_at_preflight(
        self,
    ) -> None:
        """Case 8: Discovered refmac5 outside configured CCP4 prefix fails at preflight before runner call."""
        outside_bin_dir = self.repo_root / "outside_toolchain_bin"
        outside_bin_dir.mkdir(parents=True, exist_ok=True)
        outside_refmac = outside_bin_dir / "refmac5"
        outside_refmac.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        outside_refmac.chmod(0o755)
        resolved_outside_refmac = outside_refmac.resolve(strict=True)
        self.assertFalse(
            resolved_outside_refmac.is_relative_to(self.fake_ccp4.prefix)
        )

        expected_shared_path = (
            f"{self.fake_ccp4.bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin"
        )
        original_shared_path = self.fake_ccp4.sourced_env["PATH"]
        self.assertEqual(original_shared_path, expected_shared_path)

        scoped_env = dict(self.fake_ccp4.sourced_env)
        scoped_env["PATH"] = f"{outside_bin_dir}{os.pathsep}{original_shared_path}"
        self.assertEqual(
            self.fake_ccp4.sourced_env["PATH"], original_shared_path
        )
        self.assertEqual(
            self.fake_ccp4.sourced_env["PATH"], expected_shared_path
        )
        runner_calls: list[Path] = []

        def runner(
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
            runner_calls.append(executable)
            raise AssertionError("runner must not be called when preflight fails")

        with self.assertRaises(onesar_refmac.RefmacCollectorError) as ctx:
            self._run_with_fake_ccp4(
                "case8_outside_prefix_executable",
                runner,
                sourced_env_override=scoped_env,
            )

        self.assertEqual(
            self.fake_ccp4.sourced_env["PATH"], original_shared_path
        )
        self.assertEqual(
            self.fake_ccp4.sourced_env["PATH"], expected_shared_path
        )
        self.assertEqual(runner_calls, [])
        err = ctx.exception
        self.assertEqual(err.failed_stage, "resolve_ccp4_refmac_toolchain")
        self.assertIsNone(err.returncode)
        self.assertIsInstance(err.primary_cause, ValueError)
        self.assertIs(err.__cause__, err.primary_cause)
        self.assertIn("outside configured CCP4 prefix", str(err.primary_cause))
        self.assertIn(str(resolved_outside_refmac), str(err.primary_cause))
        self.assertIn(str(self.fake_ccp4.prefix), str(err.primary_cause))
        self.assertIs(err.publication_pair_complete, True)

        assert err.manifest_payload is not None
        manifest_disk = self._reopen_and_verify_json_artifact(
            {
                "path": str(err.manifest_path),
                "sha256": _sha256_bytes(Path(err.manifest_path).read_bytes()),
                "size_bytes": Path(err.manifest_path).stat().st_size,
            }
        )
        diagnostics_disk = self._reopen_and_verify_json_artifact(
            err.manifest_payload["diagnostics_json"]
        )
        pre_ckpt = self._reopen_and_verify_json_artifact(
            diagnostics_disk["pre_execution_checkpoint_json"]
        )
        post_ckpt = self._reopen_and_verify_json_artifact(
            diagnostics_disk["post_execution_checkpoint_json"]
        )

        self.assertEqual(pre_ckpt["status"], "preflight_failed")
        self.assertIsNone(pre_ckpt["toolchain"])
        self.assertIsInstance(pre_ckpt["preflight_error"], dict)
        self.assertEqual(
            pre_ckpt["preflight_error"]["failed_stage"],
            "resolve_ccp4_refmac_toolchain",
        )
        self.assertEqual(
            pre_ckpt["preflight_error"]["exception_type"], "ValueError"
        )
        self.assertIn(
            "outside configured CCP4 prefix",
            pre_ckpt["preflight_error"]["exception_message"],
        )
        self.assertIn(
            str(resolved_outside_refmac),
            pre_ckpt["preflight_error"]["exception_message"],
        )
        self.assertEqual(post_ckpt["preflight_error"], pre_ckpt["preflight_error"])

        for doc in (post_ckpt, diagnostics_disk, manifest_disk):
            self.assertEqual(doc["status"], "failed")
            self.assertEqual(
                doc["failed_stage"], "resolve_ccp4_refmac_toolchain"
            )
            self.assertEqual(doc["failures"], [pre_ckpt["preflight_error"]])
            self.assertEqual(doc["failures"][0], pre_ckpt["preflight_error"])
            self.assertEqual(
                doc["failures"][0]["failed_stage"],
                "resolve_ccp4_refmac_toolchain",
            )
            self.assertEqual(
                doc["failures"][0]["exception_type"], "ValueError"
            )
            self.assertIn(
                "outside configured CCP4 prefix",
                doc["failures"][0]["exception_message"],
            )
            self.assertIsNone(doc["toolchain"])
            self.assertIs(
                doc["operation_checks"]["preflight_toolchain_resolved"], False
            )
            self.assertIs(doc["operation_checks"]["worker_launched"], False)
            self.assertIs(doc["operation_checks"]["collector_succeeded"], False)

        self._assert_all_scientific_admission_flags_false(diagnostics_disk)
        self._assert_all_scientific_admission_flags_false(manifest_disk)

    def test_runner_mutates_staged_input_and_raises_declared_exception(
        self,
    ) -> None:
        """Case 9: Runner mutates an owned staged input and raises a declared exception after partial outputs."""
        self.assertEqual(COMMITTED_ARCHIVE_SHA256, onesar_rerun.ARCHIVE_SHA256)
        pre_archive_sha256 = _sha256_bytes(COMMITTED_ARCHIVE.read_bytes())
        self.assertEqual(pre_archive_sha256, COMMITTED_ARCHIVE_SHA256)

        partial_log_bytes = (
            b"### CCP4 9.0.015: Refmac_5.8.0430 : partial log before runner exception\n"
        )
        partial_xyz_bytes = (
            b"REMARK partial xyzout before runner exception\nEND\n"
        )
        declared_exc = RuntimeError(
            "declared runner failure after mutating owned staged input"
        )
        observed_mutation: dict[str, Any] = {}

        def runner(
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
            # xyzin is the owned staged input under evidence_root/inputs, never COMMITTED_ARCHIVE.
            self.assertNotEqual(
                xyzin.resolve(strict=True), COMMITTED_ARCHIVE
            )
            baseline_bytes = xyzin.read_bytes()
            mutated_bytes = (
                baseline_bytes
                + b"\nREMARK runner mutated owned staged input\n"
            )
            log_path.write_bytes(partial_log_bytes)
            xyzout.write_bytes(partial_xyz_bytes)
            xyzin.write_bytes(mutated_bytes)
            observed_mutation["xyzin_path"] = xyzin
            observed_mutation["baseline_bytes"] = baseline_bytes
            observed_mutation["baseline_sha256"] = _sha256_bytes(baseline_bytes)
            observed_mutation["mutated_bytes"] = mutated_bytes
            observed_mutation["mutated_sha256"] = _sha256_bytes(mutated_bytes)
            raise declared_exc

        with self.assertRaises(onesar_refmac.RefmacCollectorError) as ctx:
            self._run_with_fake_ccp4(
                "case9_mutated_staged_input_and_runner_exception", runner
            )

        err = ctx.exception
        self.assertEqual(err.failed_stage, "refmac_runner_invocation")
        self.assertIsNone(err.returncode)
        self.assertIs(err.primary_cause, declared_exc)
        self.assertIs(err.__cause__, declared_exc)
        self.assertIs(err.publication_pair_complete, True)

        # Committed archive remains untouched on disk.
        post_archive_sha256 = _sha256_bytes(COMMITTED_ARCHIVE.read_bytes())
        self.assertEqual(post_archive_sha256, pre_archive_sha256)
        self.assertEqual(post_archive_sha256, COMMITTED_ARCHIVE_SHA256)

        # Owned staged input on disk has the mutated bytes.
        xyzin_disk_path = Path(observed_mutation["xyzin_path"])
        self.assertEqual(
            xyzin_disk_path.read_bytes(), observed_mutation["mutated_bytes"]
        )
        self.assertNotEqual(
            observed_mutation["baseline_sha256"],
            observed_mutation["mutated_sha256"],
        )

        assert err.manifest_payload is not None
        manifest_disk = self._reopen_and_verify_json_artifact(
            {
                "path": str(err.manifest_path),
                "sha256": _sha256_bytes(Path(err.manifest_path).read_bytes()),
                "size_bytes": Path(err.manifest_path).stat().st_size,
            }
        )
        diagnostics_disk = self._reopen_and_verify_json_artifact(
            err.manifest_payload["diagnostics_json"]
        )
        pre_ckpt = self._reopen_and_verify_json_artifact(
            diagnostics_disk["pre_execution_checkpoint_json"]
        )
        post_ckpt = self._reopen_and_verify_json_artifact(
            diagnostics_disk["post_execution_checkpoint_json"]
        )

        # Reopen actual raw_outputs paths on disk and verify regular non-symlink files, exact bytes, sha256, and size.
        for key, expected_partial_bytes in (
            ("log", partial_log_bytes),
            ("xyzout", partial_xyz_bytes),
        ):
            raw_info = diagnostics_disk["raw_outputs"][key]
            self.assertIs(raw_info["exists"], True)
            self.assertIs(raw_info["is_regular_file"], True)
            self.assertIs(raw_info["is_symlink"], False)
            raw_disk_path = Path(raw_info["path"])
            self.assertTrue(raw_disk_path.is_file())
            self.assertFalse(raw_disk_path.is_symlink())
            disk_bytes = raw_disk_path.read_bytes()
            self.assertEqual(disk_bytes, expected_partial_bytes)
            self.assertEqual(
                raw_info["sha256"], _sha256_bytes(expected_partial_bytes)
            )
            self.assertEqual(_sha256_bytes(disk_bytes), raw_info["sha256"])
            self.assertEqual(
                raw_info["size_bytes"], len(expected_partial_bytes)
            )
            self.assertEqual(len(disk_bytes), raw_info["size_bytes"])
        self.assertIs(diagnostics_disk["raw_outputs"]["hklout"]["exists"], False)
        self.assertFalse(
            Path(diagnostics_disk["raw_outputs"]["hklout"]["path"]).exists()
        )

        # Pre-run baseline vs post-run mutated bytes recorded in immutability ledger.
        self.assertEqual(
            pre_ckpt["staged_inputs_baseline"]["original_model_pdb"]["sha256"],
            observed_mutation["baseline_sha256"],
        )
        immut = diagnostics_disk["input_immutability"]
        self.assertIs(immut["verified"], False)
        self.assertEqual(
            immut["staged_inputs_baseline"]["original_model_pdb"]["sha256"],
            observed_mutation["baseline_sha256"],
        )
        self.assertEqual(
            immut["staged_inputs_post_run"]["original_model_pdb"]["sha256"],
            observed_mutation["mutated_sha256"],
        )
        self.assertIs(
            immut["staged_inputs_post_run"]["original_model_pdb"][
                "matches_baseline"
            ],
            False,
        )
        self.assertEqual(len(immut["mutations"]), 1)
        mutation_entry = immut["mutations"][0]
        self.assertEqual(mutation_entry["category"], "staged_input")
        self.assertEqual(mutation_entry["key"], "original_model_pdb")
        self.assertEqual(
            mutation_entry["expected_sha256"],
            observed_mutation["baseline_sha256"],
        )
        self.assertEqual(
            mutation_entry["actual_sha256"],
            observed_mutation["mutated_sha256"],
        )
        self.assertEqual(
            mutation_entry["reason"],
            "Staged input file mutated during REFMAC operation",
        )

        # Both the original runner failure and the distinct input-mutation failure are persisted.
        for doc in (post_ckpt, diagnostics_disk, manifest_disk):
            self.assertEqual(doc["failed_stage"], "refmac_runner_invocation")
            failures_by_stage = {
                f["failed_stage"]: f for f in doc["failures"]
            }
            self.assertIn("refmac_runner_invocation", failures_by_stage)
            self.assertIn("verify_input_immutability", failures_by_stage)
            runner_fail = failures_by_stage["refmac_runner_invocation"]
            self.assertEqual(runner_fail["failure_kind"], "runner_exception")
            self.assertEqual(runner_fail["exception_type"], "RuntimeError")
            self.assertEqual(
                runner_fail["exception_message"], str(declared_exc)
            )
            immut_fail = failures_by_stage["verify_input_immutability"]
            self.assertEqual(len(immut_fail["mutations"]), 1)
            self.assertEqual(immut_fail["mutations"], immut["mutations"])
            self.assertIs(
                doc["operation_checks"]["input_immutability_verified"], False
            )

        self._assert_all_scientific_admission_flags_false(diagnostics_disk)
        self._assert_all_scientific_admission_flags_false(manifest_disk)

    def test_runner_removes_staged_input_retaining_baseline_and_outputs(
        self,
    ) -> None:
        """Case 10: Runner removes one owned staged input; baseline, child metadata, and raw outputs remain retained."""
        removed_info: dict[str, Any] = {}

        def runner(
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
            self._write_capture_success_outputs(
                xyzin, hklin, xyzout, hklout, log_path
            )
            staged_original_mtz = xyzin.parent / "original_data.mtz"
            baseline_bytes = staged_original_mtz.read_bytes()
            removed_info["path"] = staged_original_mtz
            removed_info["baseline_sha256"] = _sha256_bytes(baseline_bytes)
            removed_info["baseline_size_bytes"] = len(baseline_bytes)
            staged_original_mtz.unlink()
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
                stdout=SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG,
                stderr="",
            )

        with self.assertRaises(onesar_refmac.RefmacCollectorError) as ctx:
            self._run_with_fake_ccp4(
                "case10_removed_staged_input", runner
            )

        err = ctx.exception
        self.assertEqual(err.failed_stage, "verify_input_immutability")
        self.assertEqual(err.returncode, 0)
        self.assertIsInstance(err.primary_cause, FileNotFoundError)
        self.assertIs(err.__cause__, err.primary_cause)
        self.assertIs(err.publication_pair_complete, True)
        self.assertFalse(Path(removed_info["path"]).exists())

        assert err.manifest_payload is not None
        manifest_disk = self._reopen_and_verify_json_artifact(
            {
                "path": str(err.manifest_path),
                "sha256": _sha256_bytes(Path(err.manifest_path).read_bytes()),
                "size_bytes": Path(err.manifest_path).stat().st_size,
            }
        )
        diagnostics_disk = self._reopen_and_verify_json_artifact(
            err.manifest_payload["diagnostics_json"]
        )
        pre_ckpt = self._reopen_and_verify_json_artifact(
            diagnostics_disk["pre_execution_checkpoint_json"]
        )
        post_ckpt = self._reopen_and_verify_json_artifact(
            diagnostics_disk["post_execution_checkpoint_json"]
        )

        evidence_root = Path(diagnostics_disk["evidence_root"])
        expected_argv = self._expected_argv_for_evidence_root(evidence_root)

        # Completed-child metadata and raw outputs are retained and verified from reopened references.
        self.assertEqual(diagnostics_disk["invocation"]["returncode"], 0)
        self.assertEqual(
            diagnostics_disk["invocation"]["completed_argv"], expected_argv
        )
        self.assertIs(
            diagnostics_disk["invocation"]["completed_argv_available"], True
        )
        self.assertIs(
            diagnostics_disk["invocation"]["argv_matches_expected"], True
        )
        for key in ("log", "xyzout", "hklout"):
            raw_info = diagnostics_disk["raw_outputs"][key]
            self.assertIs(raw_info["exists"], True)
            self.assertIs(raw_info["is_regular_file"], True)
            disk_bytes = Path(raw_info["path"]).read_bytes()
            self.assertEqual(raw_info["sha256"], _sha256_bytes(disk_bytes))
            self.assertEqual(raw_info["size_bytes"], len(disk_bytes))

        # Baseline identity remains retained while missing-input diagnostic is distinct from byte mutation.
        self.assertEqual(
            pre_ckpt["staged_inputs_baseline"]["original_data_mtz"]["sha256"],
            removed_info["baseline_sha256"],
        )
        immut = diagnostics_disk["input_immutability"]
        self.assertIs(immut["verified"], False)
        self.assertEqual(
            immut["staged_inputs_baseline"]["original_data_mtz"]["sha256"],
            removed_info["baseline_sha256"],
        )
        self.assertEqual(
            immut["staged_inputs_baseline"]["original_data_mtz"]["size_bytes"],
            removed_info["baseline_size_bytes"],
        )
        post_mtz = immut["staged_inputs_post_run"]["original_data_mtz"]
        self.assertIsNone(post_mtz["sha256"])
        self.assertIsNone(post_mtz["size_bytes"])
        self.assertIs(post_mtz["matches_baseline"], False)
        self.assertIn("FileNotFoundError", str(post_mtz.get("error")))

        self.assertEqual(len(immut["mutations"]), 1)
        mutation_entry = immut["mutations"][0]
        self.assertEqual(mutation_entry["category"], "staged_input")
        self.assertEqual(mutation_entry["key"], "original_data_mtz")
        self.assertEqual(
            mutation_entry["expected_sha256"], removed_info["baseline_sha256"]
        )
        self.assertIsNone(mutation_entry["actual_sha256"])
        self.assertIn(
            "Staged input file missing or invalid after REFMAC operation",
            mutation_entry["reason"],
        )
        self.assertNotEqual(
            mutation_entry["reason"],
            "Staged input file mutated during REFMAC operation",
        )

        for doc in (post_ckpt, diagnostics_disk, manifest_disk):
            self.assertEqual(doc["failed_stage"], "verify_input_immutability")
            self.assertEqual(
                [f["failed_stage"] for f in doc["failures"]],
                ["verify_input_immutability"],
            )
            self.assertEqual(len(doc["failures"][0]["mutations"]), 1)
            self.assertEqual(doc["failures"][0]["mutations"], immut["mutations"])
            self.assertIs(
                doc["operation_checks"]["input_immutability_verified"], False
            )
            self.assertIs(
                doc["operation_checks"]["process_returncode_zero"], True
            )
            self.assertIs(
                doc["operation_checks"]["completed_argv_available"], True
            )
            self.assertIs(
                doc["operation_checks"]["argv_matches_expected"], True
            )

        self._assert_all_scientific_admission_flags_false(diagnostics_disk)
        self._assert_all_scientific_admission_flags_false(manifest_disk)

    def test_unexpected_audit_boundary_exception_persists_contextual_failure(
        self,
    ) -> None:
        """Case 11: Narrow unexpected exception at XMLOUT audit boundary persists contextual audit_exception while keeping staging, other audits, and publication real."""
        declared_audit_exc = RuntimeError(
            "declared unexpected xmlout audit boundary error"
        )

        def runner(
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
            self._write_capture_success_outputs(
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
                stdout=SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG,
                stderr="",
            )

        with (
            patch.object(
                onesar_refmac,
                "_audit_refmac_xmlout",
                side_effect=declared_audit_exc,
            ) as mock_xmlout_audit,
            self.assertRaises(onesar_refmac.RefmacCollectorError) as ctx,
        ):
            self._run_with_fake_ccp4(
                "case11_unexpected_xmlout_audit_exception", runner
            )

        self.assertEqual(mock_xmlout_audit.call_count, 1)
        err = ctx.exception
        self.assertEqual(err.failed_stage, "audit_refmac_xmlout")
        self.assertEqual(err.returncode, 0)
        self.assertIs(err.primary_cause, declared_audit_exc)
        self.assertIs(err.__cause__, declared_audit_exc)
        self.assertIs(err.publication_pair_complete, True)

        assert err.manifest_payload is not None
        manifest_disk = self._reopen_and_verify_json_artifact(
            {
                "path": str(err.manifest_path),
                "sha256": _sha256_bytes(Path(err.manifest_path).read_bytes()),
                "size_bytes": Path(err.manifest_path).stat().st_size,
            }
        )
        diagnostics_disk = self._reopen_and_verify_json_artifact(
            err.manifest_payload["diagnostics_json"]
        )
        post_ckpt = self._reopen_and_verify_json_artifact(
            diagnostics_disk["post_execution_checkpoint_json"]
        )
        xmlout_audit_disk = self._reopen_and_verify_json_artifact(
            diagnostics_disk["xmlout_audit_json"]
        )
        hklout_audit_disk = self._reopen_and_verify_json_artifact(
            diagnostics_disk["hklout_audit_json"]
        )
        xyzout_audit_disk = self._reopen_and_verify_json_artifact(
            diagnostics_disk["xyzout_audit_json"]
        )

        evidence_root = Path(diagnostics_disk["evidence_root"])
        expected_argv = self._expected_argv_for_evidence_root(evidence_root)

        # Post-execution checkpoint is saved BEFORE XML auditing and retains pre-audit completed-child state.
        self.assertEqual(post_ckpt["status"], "post_execution_checkpointed")
        self.assertIsNone(post_ckpt["failed_stage"])
        self.assertEqual(post_ckpt["failures"], [])
        self.assertIsNone(post_ckpt["operation_checks"]["collector_succeeded"])
        self.assertIs(
            post_ckpt["operation_checks"]["preflight_toolchain_resolved"], True
        )
        self.assertIs(post_ckpt["operation_checks"]["worker_launched"], True)
        self.assertIs(
            post_ckpt["operation_checks"]["process_returncode_zero"], True
        )
        self.assertIs(
            post_ckpt["operation_checks"]["completed_argv_available"], True
        )
        self.assertIs(
            post_ckpt["operation_checks"]["argv_matches_expected"], True
        )
        self.assertIs(
            post_ckpt["operation_checks"]["all_raw_outputs_present_and_regular"],
            True,
        )
        self.assertIs(
            post_ckpt["operation_checks"]["input_immutability_verified"], True
        )
        self.assertEqual(post_ckpt["invocation"]["returncode"], 0)
        self.assertEqual(
            post_ckpt["invocation"]["completed_argv"], expected_argv
        )
        for key in ("log", "xyzout", "hklout"):
            raw_info = post_ckpt["raw_outputs"][key]
            self.assertIs(raw_info["exists"], True)
            self.assertIs(raw_info["is_regular_file"], True)
            self.assertIs(raw_info["is_symlink"], False)

        # Persisted XMLOUT audit records contextual audit_exception with original exception details.
        expected_xmlout_errors = [
            f"Unexpected exception during XMLOUT audit (RuntimeError): {declared_audit_exc}"
        ]
        self.assertEqual(xmlout_audit_disk["status"], "audit_exception")
        self.assertIs(xmlout_audit_disk["valid"], False)
        self.assertEqual(xmlout_audit_disk["exception_type"], "RuntimeError")
        self.assertEqual(
            xmlout_audit_disk["exception_message"], str(declared_audit_exc)
        )
        self.assertEqual(xmlout_audit_disk["errors"], expected_xmlout_errors)

        # Other audits and Stage-1 collection ran normally and succeeded.
        self.assertIs(hklout_audit_disk["valid"], True)
        self.assertIs(xyzout_audit_disk["valid"], True)
        self.assertIs(
            diagnostics_disk["operation_checks"]["stage1_collection_succeeded"],
            True,
        )
        self.assertIs(
            diagnostics_disk["operation_checks"]["stage2_audits_succeeded"],
            False,
        )
        self.assertIs(
            diagnostics_disk["operation_checks"]["xmlout_audit_valid"], False
        )
        self.assertEqual(
            diagnostics_disk["operation_checks"]["xmlout_audit_status"],
            "audit_exception",
        )
        self.assertIs(
            diagnostics_disk["operation_checks"]["hklout_audit_valid"], True
        )
        self.assertIs(
            diagnostics_disk["operation_checks"]["xyzout_audit_valid"], True
        )

        # Final diagnostics and manifest record audit_refmac_xmlout failure and retain detailed errors in audits["xmlout_audit"]["errors"].
        for doc in (diagnostics_disk, manifest_disk):
            self.assertEqual(doc["status"], "failed")
            self.assertEqual(doc["failed_stage"], "audit_refmac_xmlout")
            self.assertEqual(
                [f["failed_stage"] for f in doc["failures"]],
                ["audit_refmac_xmlout"],
            )
            failure = doc["failures"][0]
            self.assertEqual(failure["xmlout_status"], "audit_exception")
            self.assertEqual(failure["exception_type"], "RuntimeError")
            self.assertEqual(
                failure["exception_message"], str(declared_audit_exc)
            )
            self.assertEqual(
                doc["audits"]["xmlout_audit"]["status"], "audit_exception"
            )
            self.assertIs(doc["audits"]["xmlout_audit"]["valid"], False)
            self.assertEqual(
                doc["audits"]["xmlout_audit"]["exception_type"], "RuntimeError"
            )
            self.assertEqual(
                doc["audits"]["xmlout_audit"]["exception_message"],
                str(declared_audit_exc),
            )
            self.assertEqual(
                doc["audits"]["xmlout_audit"]["errors"], expected_xmlout_errors
            )
            self.assertEqual(
                doc["audits"]["xmlout_audit"]["errors"],
                xmlout_audit_disk["errors"],
            )

        self._assert_all_scientific_admission_flags_false(diagnostics_disk)
        self._assert_all_scientific_admission_flags_false(manifest_disk)

    def test_xmlout_audit_states_log_unproven_association_and_values_above_one(
        self,
    ) -> None:
        """Group 2 (1-2): Direct _audit_refmac_xmlout across supported, absent, unsupported, malformed, -999 sentinel, log-present unproven association, and R > 1."""
        xml_dir = self.repo_root / "runs" / "group2_xml_audit_states"
        xml_dir.mkdir(parents=True, exist_ok=True)

        minimum_supported_xml = (
            "<Overall_stats><stats_vs_cycle><new_cycle>"
            "<cycle>0</cycle><r_factor>0.1816</r_factor><r_free>0.2156</r_free>"
            "</new_cycle></stats_vs_cycle></Overall_stats>"
        )

        def write_and_audit_xml(
            filename: str,
            raw_bytes: bytes,
            *,
            parsed_log: Mapping[str, Any] | None = None,
        ) -> dict[str, Any]:
            xml_path = xml_dir / filename
            xml_path.write_bytes(raw_bytes)
            xml_info = onesar_refmac._inspect_output_artifact(
                xml_path, root=xml_dir
            )
            audit = onesar_refmac._audit_refmac_xmlout(
                xml_path, xmlout_info=xml_info, parsed_log=parsed_log
            )
            self.assertIs(audit["present"], True)
            self.assertIs(audit["is_regular_file"], True)
            self.assertIs(audit["is_symlink"], False)
            self.assertIs(audit["within_refmac_dir"], True)
            self.assertEqual(audit["sha256"], _sha256_bytes(raw_bytes))
            self.assertEqual(audit["size_bytes"], len(raw_bytes))
            self.assertEqual(audit["raw_text"], raw_bytes.decode("utf-8"))
            self.assertEqual(audit["raw_bytes_hex"], raw_bytes.hex())
            self.assertIs(audit["utf8_exact"], True)
            return audit

        with self.subTest("supported_minimum_literal_without_parsed_log"):
            audit = write_and_audit_xml(
                "supported_min.xml", minimum_supported_xml.encode("utf-8")
            )
            self.assertEqual(
                audit["status"], "supported_parsed_log_unavailable"
            )
            self.assertIs(audit["well_formed_xml"], True)
            self.assertIs(audit["supported_shape"], True)
            self.assertIs(audit["valid"], True)
            self.assertIsNone(audit["reconciled_with_log"])
            self.assertEqual(audit["observed_cycle_numbers"], [0])
            self.assertIsNone(audit["overall_stats_top_level"])
            self.assertIs(audit["smartie_graphs_present"], False)
            self.assertIs(audit["smartie_graphs_required"], False)
            self.assertIsNone(audit["cycle_indexing_convention"])
            self.assertIs(audit["cycle_association_proven"], False)
            self.assertIs(audit["precision_association_proven"], False)
            self.assertIs(audit["top_vs_final_shared_scalar_proven"], False)
            self.assertIsNone(audit["log_reconciliation"])
            self.assertEqual(audit["errors"], [])
            self.assertEqual(
                audit["new_cycle_rows"],
                [
                    {
                        "ordinal": 0,
                        "cycle_token": "0",
                        "cycle": 0,
                        "r_factor_token": "0.1816",
                        "r_factor": "0.1816",
                        "r_factor_decimal_places": 4,
                        "r_free_token": "0.2156",
                        "r_free": "0.2156",
                        "r_free_decimal_places": 4,
                    }
                ],
            )

        with self.subTest("enclosing_root_with_single_direct_overall_stats"):
            enclosed_xml = f"<REFMAC>{minimum_supported_xml}</REFMAC>"
            audit = write_and_audit_xml(
                "supported_enclosed.xml", enclosed_xml.encode("utf-8")
            )
            self.assertEqual(
                audit["status"], "supported_parsed_log_unavailable"
            )
            self.assertEqual(audit["root_tag"], "REFMAC")
            self.assertEqual(audit["top_level_child_tags"], ["Overall_stats"])
            self.assertIs(audit["supported_shape"], True)
            self.assertIs(audit["valid"], True)
            self.assertEqual(audit["observed_cycle_numbers"], [0])

        with self.subTest("absent_xmlout_file"):
            absent_path = xml_dir / "absent_xmlout.xml"
            self.assertFalse(absent_path.exists())
            absent_info = onesar_refmac._inspect_output_artifact(
                absent_path, root=xml_dir
            )
            audit = onesar_refmac._audit_refmac_xmlout(
                absent_path, xmlout_info=absent_info, parsed_log=None
            )
            self.assertEqual(audit["status"], "absent")
            self.assertIs(audit["present"], False)
            self.assertIs(audit["valid"], True)
            self.assertIs(audit["supported_shape"], False)
            self.assertIsNone(audit["well_formed_xml"])
            self.assertIsNone(audit["reconciled_with_log"])
            self.assertIsNone(audit["raw_text"])
            self.assertIsNone(audit["raw_bytes_hex"])
            self.assertIsNone(audit["sha256"])
            self.assertIsNone(audit["size_bytes"])
            self.assertEqual(audit["errors"], [])

        with self.subTest("well_formed_unsupported_shape"):
            audit = write_and_audit_xml("unsupported.xml", b"<Other/>")
            self.assertEqual(audit["status"], "unsupported_shape")
            self.assertIs(audit["well_formed_xml"], True)
            self.assertIs(audit["supported_shape"], False)
            self.assertIs(audit["valid"], True)
            self.assertIsNone(audit["reconciled_with_log"])
            self.assertEqual(audit["new_cycle_rows"], [])
            self.assertEqual(audit["observed_cycle_numbers"], [])
            self.assertIsNone(audit["log_reconciliation"])
            self.assertIs(audit["cycle_association_proven"], False)
            self.assertEqual(audit["errors"], [])

        with self.subTest("malformed_xml_retains_raw_evidence"):
            audit = write_and_audit_xml("malformed.xml", b"<Overall_stats>")
            self.assertEqual(audit["status"], "rejected_malformed_xml")
            self.assertIs(audit["well_formed_xml"], False)
            self.assertIs(audit["supported_shape"], False)
            self.assertIs(audit["valid"], False)
            self.assertIs(audit["reconciled_with_log"], False)
            self.assertEqual(len(audit["errors"]), 1)
            self.assertIn("Malformed XMLOUT syntax", audit["errors"][0])

        with self.subTest("explicit_minus_999_sentinel_in_supported_r_field"):
            sentinel_xml = (
                "<Overall_stats><stats_vs_cycle><new_cycle>"
                "<cycle>0</cycle><r_factor>0.1816</r_factor><r_free>-999</r_free>"
                "</new_cycle></stats_vs_cycle></Overall_stats>"
            )
            audit = write_and_audit_xml(
                "sentinel_rfree.xml", sentinel_xml.encode("utf-8")
            )
            self.assertEqual(
                audit["status"], "rejected_invalid_or_contradictory"
            )
            self.assertIs(audit["well_formed_xml"], True)
            self.assertIs(audit["supported_shape"], True)
            self.assertIs(audit["valid"], False)
            self.assertIs(audit["reconciled_with_log"], False)
            self.assertEqual(len(audit["new_cycle_rows"]), 1)
            row = audit["new_cycle_rows"][0]
            self.assertEqual(row["r_factor_token"], "0.1816")
            self.assertEqual(row["r_factor"], "0.1816")
            self.assertEqual(row["r_factor_decimal_places"], 4)
            self.assertEqual(row["r_free_token"], "-999")
            self.assertIsNone(row["r_free"])
            self.assertIsNone(row["r_free_decimal_places"])
            self.assertTrue(
                any(
                    "Documented -999 missing-value sentinel" in err
                    for err in audit["errors"]
                )
            )

        with self.subTest(
            "log_present_differing_top_vs_final_and_finite_r_values_above_one"
        ):
            real_parsed_log = onesar_refmac_log.parse_refmac_log(
                SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG
            )
            above_one_xml = (
                "<Overall_stats>"
                "<r_factor>0.1900</r_factor><r_free>0.2300</r_free>"
                "<stats_vs_cycle><new_cycle>"
                "<cycle>0</cycle><r_factor>1.2000</r_factor><r_free>2.0000</r_free>"
                "</new_cycle></stats_vs_cycle>"
                "</Overall_stats>"
            )
            audit = write_and_audit_xml(
                "supported_log_present_above_one.xml",
                above_one_xml.encode("utf-8"),
                parsed_log=real_parsed_log,
            )
            self.assertEqual(
                audit["status"], "supported_cycle_association_unproven"
            )
            self.assertIs(audit["well_formed_xml"], True)
            self.assertIs(audit["supported_shape"], True)
            self.assertIs(audit["valid"], True)
            self.assertIs(audit["reconciled_with_log"], False)
            self.assertEqual(audit["errors"], [])

            # Finite nonnegative R values above 1.0 remain eligible with exact token/value retention.
            self.assertEqual(len(audit["new_cycle_rows"]), 1)
            row = audit["new_cycle_rows"][0]
            self.assertEqual(row["cycle_token"], "0")
            self.assertEqual(row["cycle"], 0)
            self.assertEqual(row["r_factor_token"], "1.2000")
            self.assertEqual(row["r_factor"], "1.2000")
            self.assertEqual(row["r_factor_decimal_places"], 4)
            self.assertEqual(row["r_free_token"], "2.0000")
            self.assertEqual(row["r_free"], "2.0000")
            self.assertEqual(row["r_free_decimal_places"], 4)

            # Matching cycle numbers (0 vs [0]) and differing top/final values never establish association or shared scalar.
            self.assertIsNone(audit["cycle_indexing_convention"])
            self.assertIs(audit["cycle_association_proven"], False)
            self.assertIs(audit["precision_association_proven"], False)
            self.assertIs(audit["top_vs_final_shared_scalar_proven"], False)

            log_rec = audit["log_reconciliation"]
            self.assertIsInstance(log_rec, dict)
            self.assertIs(log_rec["reconciled"], False)
            self.assertIs(log_rec["cycle_association_proven"], False)
            self.assertIs(log_rec["ordinal_pairing_performed"], False)
            self.assertEqual(log_rec["xml_new_cycle_count"], 1)
            self.assertEqual(log_rec["xml_cycles"][0]["cycle"], 0)
            self.assertEqual(log_rec["log_summary_row_count"], 1)
            self.assertEqual(log_rec["log_summary_ncyc_values"], [0])

            top_info = audit["overall_stats_top_level"]
            self.assertIsInstance(top_info, dict)
            self.assertEqual(top_info["r_factor_token"], "0.1900")
            self.assertEqual(top_info["r_factor"], "0.1900")
            self.assertEqual(top_info["r_free_token"], "0.2300")
            self.assertEqual(top_info["r_free"], "0.2300")
            self.assertIs(top_info["top_vs_final_shared_scalar_proven"], False)
            for cmp_key in (
                "final_new_cycle_r_factor_comparison",
                "final_new_cycle_r_free_comparison",
            ):
                cmp_rec = top_info[cmp_key]
                self.assertEqual(
                    cmp_rec["comparison_status"],
                    "same_precision_mismatch_source_association_unproven",
                )
                self.assertIs(cmp_rec["exact_token_equal"], False)
                self.assertIs(cmp_rec["exact_decimal_equal"], False)
                self.assertIs(cmp_rec["precision_association_proven"], False)
                self.assertIsNone(cmp_rec["compatible_at_source_precision"])
                self.assertIsNone(cmp_rec["contradicts_at_source_precision"])

    def test_malformed_xmlout_through_full_collector_operation(self) -> None:
        """Group 2 (3): Malformed XMLOUT through run_refmac_rfactor_operation fails at audit_refmac_xmlout and persists raw/audit evidence."""
        malformed_xml_bytes = b"<Overall_stats>"

        def runner(
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
            self._write_capture_success_outputs(
                xyzin, hklin, xyzout, hklout, log_path
            )
            xml_output.write_bytes(malformed_xml_bytes)
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
                stdout=SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG,
                stderr="",
            )

        with self.assertRaises(onesar_refmac.RefmacCollectorError) as ctx:
            self._run_with_fake_ccp4("group2_malformed_xmlout_full_op", runner)

        err = ctx.exception
        self.assertEqual(err.failed_stage, "audit_refmac_xmlout")
        self.assertEqual(err.returncode, 0)
        self.assertIsNone(err.primary_cause)
        self.assertIsNone(err.__cause__)
        self.assertIs(err.publication_pair_complete, True)

        assert err.manifest_payload is not None
        manifest_disk = self._reopen_and_verify_json_artifact(
            {
                "path": str(err.manifest_path),
                "sha256": _sha256_bytes(Path(err.manifest_path).read_bytes()),
                "size_bytes": Path(err.manifest_path).stat().st_size,
            }
        )
        diagnostics_disk = self._reopen_and_verify_json_artifact(
            err.manifest_payload["diagnostics_json"]
        )
        post_ckpt = self._reopen_and_verify_json_artifact(
            diagnostics_disk["post_execution_checkpoint_json"]
        )
        xmlout_audit_disk = self._reopen_and_verify_json_artifact(
            diagnostics_disk["xmlout_audit_json"]
        )
        hklout_audit_disk = self._reopen_and_verify_json_artifact(
            diagnostics_disk["hklout_audit_json"]
        )
        xyzout_audit_disk = self._reopen_and_verify_json_artifact(
            diagnostics_disk["xyzout_audit_json"]
        )

        # Reopen raw XMLOUT file on disk and verify exact bytes and digest.
        raw_xml_info = diagnostics_disk["raw_outputs"]["xmlout"]
        self.assertIs(raw_xml_info["exists"], True)
        self.assertIs(raw_xml_info["is_regular_file"], True)
        self.assertIs(raw_xml_info["is_symlink"], False)
        raw_xml_disk_path = Path(raw_xml_info["path"])
        self.assertTrue(raw_xml_disk_path.is_file())
        self.assertFalse(raw_xml_disk_path.is_symlink())
        self.assertEqual(raw_xml_disk_path.read_bytes(), malformed_xml_bytes)
        self.assertEqual(
            raw_xml_info["sha256"], _sha256_bytes(malformed_xml_bytes)
        )
        self.assertEqual(raw_xml_info["size_bytes"], len(malformed_xml_bytes))

        # Persisted XMLOUT audit retains raw bytes and rejected_malformed_xml status.
        self.assertEqual(xmlout_audit_disk["status"], "rejected_malformed_xml")
        self.assertIs(xmlout_audit_disk["well_formed_xml"], False)
        self.assertIs(xmlout_audit_disk["valid"], False)
        self.assertEqual(
            xmlout_audit_disk["sha256"], _sha256_bytes(malformed_xml_bytes)
        )
        self.assertEqual(
            xmlout_audit_disk["size_bytes"], len(malformed_xml_bytes)
        )
        self.assertEqual(xmlout_audit_disk["raw_text"], "<Overall_stats>")
        self.assertEqual(
            xmlout_audit_disk["raw_bytes_hex"], malformed_xml_bytes.hex()
        )
        self.assertEqual(len(xmlout_audit_disk["errors"]), 1)
        self.assertIn("Malformed XMLOUT syntax", xmlout_audit_disk["errors"][0])

        self.assertEqual(post_ckpt["status"], "post_execution_checkpointed")
        self.assertIsNone(post_ckpt["failed_stage"])
        self.assertEqual(post_ckpt["failures"], [])
        self.assertIs(hklout_audit_disk["valid"], True)
        self.assertIs(xyzout_audit_disk["valid"], True)

        for doc in (diagnostics_disk, manifest_disk):
            self.assertEqual(doc["status"], "failed")
            self.assertEqual(doc["failed_stage"], "audit_refmac_xmlout")
            self.assertEqual(
                [f["failed_stage"] for f in doc["failures"]],
                ["audit_refmac_xmlout"],
            )
            failure = doc["failures"][0]
            self.assertEqual(
                failure["xmlout_status"], "rejected_malformed_xml"
            )
            self.assertEqual(failure["exception_type"], "ValueError")
            self.assertIn(
                "Malformed XMLOUT syntax", failure["exception_message"]
            )
            self.assertEqual(
                doc["audits"]["xmlout_audit"]["status"],
                "rejected_malformed_xml",
            )
            self.assertEqual(
                doc["audits"]["xmlout_audit"]["errors"],
                xmlout_audit_disk["errors"],
            )
            self.assertIs(
                doc["operation_checks"]["xmlout_audit_valid"], False
            )
            self.assertEqual(
                doc["operation_checks"]["xmlout_audit_status"],
                "rejected_malformed_xml",
            )
            self.assertIs(
                doc["operation_checks"]["hklout_audit_valid"], True
            )
            self.assertIs(
                doc["operation_checks"]["xyzout_audit_valid"], True
            )
            self._assert_all_scientific_admission_flags_false(doc)

    def _assert_conditional_r_comparison_contract(
        self, cmp_rec: Mapping[str, Any]
    ) -> None:
        self.assertIs(cmp_rec["conditional_nearest_rounding_model"], True)
        self.assertIs(cmp_rec["double_rounding_performed"], False)
        self.assertIs(cmp_rec["precision_association_proven"], False)
        self.assertIsNone(cmp_rec["compatible_at_source_precision"])
        self.assertIsNone(cmp_rec["contradicts_at_source_precision"])

    def test_exact_token_and_conditional_interval_comparisons(self) -> None:
        """Group 2 (4): Exact R-token comparisons across leading/trailing zeros, 0.1235/0.123, disjoint 28/29-place tokens, and 10^28 pair."""
        xml_dir = self.repo_root / "runs" / "group2_token_comparisons"
        xml_dir.mkdir(parents=True, exist_ok=True)

        with self.subTest("leading_and_trailing_zero_identity_vs_decimal_equality"):
            dec_lead, dp_lead, err_lead = onesar_refmac._parse_xml_r_value_token(
                "00.2000", field_name="Overall_stats/r_factor", cycle_index=None
            )
            self.assertIsNone(err_lead)
            self.assertEqual(dec_lead, Decimal("0.2000"))
            self.assertEqual(dp_lead, 4)
            assert dec_lead is not None and dp_lead is not None

            cmp_lead = onesar_refmac._compare_r_decimal_with_log_precision(
                dec_lead, dp_lead, "0.2000", xml_token="00.2000"
            )
            self._assert_conditional_r_comparison_contract(cmp_lead)
            self.assertIs(cmp_lead["raw_xml_token_supplied"], True)
            self.assertEqual(cmp_lead["xml_raw_token"], "00.2000")
            self.assertEqual(cmp_lead["xml_token"], "00.2000")
            self.assertEqual(cmp_lead["xml_value"], "0.2000")
            self.assertEqual(
                cmp_lead["xml_reconstructed_fixed_token"], "0.2000"
            )
            self.assertEqual(cmp_lead["xml_decimal_places"], 4)
            self.assertEqual(cmp_lead["log_raw_token"], "0.2000")
            self.assertEqual(cmp_lead["log_value"], "0.2000")
            self.assertEqual(cmp_lead["log_decimal_places"], 4)
            self.assertIs(cmp_lead["exact_token_equal"], False)
            self.assertIs(cmp_lead["reconstructed_fixed_token_equal"], True)
            self.assertIs(cmp_lead["exact_decimal_equal"], True)
            self.assertEqual(cmp_lead["abs_difference"], "0")
            self.assertEqual(
                cmp_lead["comparison_status"], "exact_same_precision_match"
            )

            # Nested XML top-vs-final comparison also preserves raw leading-zero token vs Decimal equality.
            lead_xml_bytes = (
                b"<Overall_stats><r_factor>00.2000</r_factor><r_free>0.2156</r_free>"
                b"<stats_vs_cycle><new_cycle>"
                b"<cycle>0</cycle><r_factor>0.2000</r_factor><r_free>0.2156</r_free>"
                b"</new_cycle></stats_vs_cycle></Overall_stats>"
            )
            lead_xml_path = xml_dir / "leading_zero_top.xml"
            lead_xml_path.write_bytes(lead_xml_bytes)
            lead_info = onesar_refmac._inspect_output_artifact(
                lead_xml_path, root=xml_dir
            )
            lead_audit = onesar_refmac._audit_refmac_xmlout(
                lead_xml_path, xmlout_info=lead_info, parsed_log=None
            )
            self.assertIs(lead_audit["valid"], True)
            nested_cmp = lead_audit["overall_stats_top_level"][
                "final_new_cycle_r_factor_comparison"
            ]
            self.assertEqual(nested_cmp["xml_raw_token"], "00.2000")
            self.assertEqual(nested_cmp["xml_value"], "0.2000")
            self.assertEqual(
                nested_cmp["xml_reconstructed_fixed_token"], "0.2000"
            )
            self.assertIs(nested_cmp["exact_token_equal"], False)
            self.assertIs(nested_cmp["exact_decimal_equal"], True)
            self.assertEqual(nested_cmp["abs_difference"], "0")

            # Trailing-zero spelling difference (4 dp vs 3 dp).
            cmp_trail = onesar_refmac._compare_r_decimal_with_log_precision(
                Decimal("0.2000"), 4, "0.200", xml_token="0.2000"
            )
            self._assert_conditional_r_comparison_contract(cmp_trail)
            self.assertEqual(cmp_trail["xml_decimal_places"], 4)
            self.assertEqual(cmp_trail["log_decimal_places"], 3)
            self.assertEqual(cmp_trail["shared_decimal_places"], 3)
            self.assertIs(cmp_trail["same_decimal_places"], False)
            self.assertIs(cmp_trail["exact_token_equal"], False)
            self.assertIs(cmp_trail["exact_decimal_equal"], True)
            self.assertEqual(cmp_trail["abs_difference"], "0")

            # 3-argument call omitting xml_token leaves raw identity fields None.
            cmp_omitted = onesar_refmac._compare_r_decimal_with_log_precision(
                Decimal("0.2000"), 4, "0.2000"
            )
            self.assertIs(cmp_omitted["raw_xml_token_supplied"], False)
            self.assertIsNone(cmp_omitted["xml_raw_token"])
            self.assertIsNone(cmp_omitted["xml_token"])
            self.assertIsNone(cmp_omitted["exact_token_equal"])
            self.assertEqual(
                cmp_omitted["xml_reconstructed_fixed_token"], "0.2000"
            )
            self.assertIs(cmp_omitted["exact_decimal_equal"], True)

        with self.subTest("independently_rounded_0_1235_vs_0_123"):
            cmp_rounded = onesar_refmac._compare_r_decimal_with_log_precision(
                Decimal("0.1235"), 4, "0.123", xml_token="0.1235"
            )
            self._assert_conditional_r_comparison_contract(cmp_rounded)
            self.assertIs(
                cmp_rounded["optional_interval_diagnostics_available"], True
            )
            self.assertEqual(cmp_rounded["abs_difference"], "0.0005")
            self.assertEqual(cmp_rounded["combined_half_ulp"], "0.00055")
            self.assertEqual(
                cmp_rounded["reporting_interval_overlap"], ["0.12345", "0.1235"]
            )
            self.assertEqual(
                cmp_rounded["reporting_interval_overlap_width"], "0.00005"
            )
            self.assertEqual(cmp_rounded["positive_separation"], "0")
            self.assertEqual(cmp_rounded["positive_separation_fraction"], "0")
            self.assertIs(cmp_rounded["interval_interior_overlap"], True)
            self.assertIs(cmp_rounded["interval_boundary_touch_only"], False)
            self.assertIs(cmp_rounded["intervals_disjoint"], False)
            self.assertEqual(
                cmp_rounded["comparison_status"],
                "conditional_interval_interior_overlap_source_association_unproven",
            )

        with self.subTest("exact_disjoint_28_and_29_place_tokens"):
            x_tok = "1." + ("0" * 27) + "1"
            y_tok = "1." + ("0" * 29)
            expected_abs_diff = "0." + ("0" * 27) + "1"
            expected_combined_half_ulp = "0." + ("0" * 28) + "55"
            expected_pos_sep = "0." + ("0" * 28) + "45"
            expected_pos_sep_frac = f"9/{2 * (10**29)}"

            cmp_disjoint = onesar_refmac._compare_r_decimal_with_log_precision(
                Decimal(x_tok), 28, y_tok, xml_token=x_tok
            )
            self._assert_conditional_r_comparison_contract(cmp_disjoint)
            self.assertIs(
                cmp_disjoint["optional_interval_diagnostics_available"], True
            )
            self.assertEqual(cmp_disjoint["xml_raw_token"], x_tok)
            self.assertEqual(cmp_disjoint["xml_value"], x_tok)
            self.assertEqual(cmp_disjoint["xml_decimal_places"], 28)
            self.assertEqual(cmp_disjoint["log_raw_token"], y_tok)
            self.assertEqual(cmp_disjoint["log_value"], y_tok)
            self.assertEqual(cmp_disjoint["log_decimal_places"], 29)
            self.assertEqual(cmp_disjoint["abs_difference"], expected_abs_diff)
            self.assertEqual(
                cmp_disjoint["combined_half_ulp"], expected_combined_half_ulp
            )
            self.assertIs(cmp_disjoint["intervals_disjoint"], True)
            self.assertIs(cmp_disjoint["interval_interior_overlap"], False)
            self.assertIs(cmp_disjoint["interval_boundary_touch_only"], False)
            self.assertIsNone(cmp_disjoint["reporting_interval_overlap"])
            self.assertEqual(
                cmp_disjoint["reporting_interval_overlap_width"], "0"
            )
            self.assertEqual(
                cmp_disjoint["positive_separation"], expected_pos_sep
            )
            self.assertEqual(
                cmp_disjoint["positive_separation_fraction"],
                expected_pos_sep_frac,
            )
            self.assertEqual(
                cmp_disjoint["comparison_status"],
                "conditional_intervals_disjoint_source_association_unproven",
            )

        with self.subTest("large_10_pow_28_pair"):
            large_x = "10000000000000000000000000000.0"
            large_y = "10000000000000000000000000001.00"
            cmp_large = onesar_refmac._compare_r_decimal_with_log_precision(
                Decimal(large_x), 1, large_y, xml_token=large_x
            )
            self._assert_conditional_r_comparison_contract(cmp_large)
            self.assertIs(
                cmp_large["optional_interval_diagnostics_available"], True
            )
            self.assertEqual(cmp_large["xml_raw_token"], large_x)
            self.assertEqual(cmp_large["xml_value"], large_x)
            self.assertEqual(cmp_large["xml_decimal_places"], 1)
            self.assertEqual(cmp_large["log_raw_token"], large_y)
            self.assertEqual(cmp_large["log_value"], large_y)
            self.assertEqual(cmp_large["log_decimal_places"], 2)
            self.assertEqual(cmp_large["abs_difference"], "1")
            self.assertEqual(cmp_large["combined_half_ulp"], "0.055")
            self.assertIs(cmp_large["intervals_disjoint"], True)
            self.assertIsNone(cmp_large["reporting_interval_overlap"])
            self.assertEqual(
                cmp_large["reporting_interval_overlap_width"], "0"
            )
            self.assertEqual(cmp_large["positive_separation"], "0.945")
            self.assertEqual(
                cmp_large["positive_separation_fraction"], "189/200"
            )
            self.assertEqual(
                cmp_large["comparison_status"],
                "conditional_intervals_disjoint_source_association_unproven",
            )

    def test_resource_bounded_xml_token_and_compact_exponent_sentinel_handling(
        self,
    ) -> None:
        """Group 2 (5): 4301-place valid XML token and bounded compact exponent/sentinel handling without global setting mutation."""
        xml_dir = self.repo_root / "runs" / "group2_resource_bounded_xml"
        xml_dir.mkdir(parents=True, exist_ok=True)
        orig_dec_prec = decimal.getcontext().prec
        orig_int_max_str_digits = sys.get_int_max_str_digits()

        with self.subTest("valid_4301_place_xml_token_exceeds_optional_budget"):
            long_r = "0." + ("1" * 4301)
            long_xml = (
                f"<Overall_stats><r_factor>{long_r}</r_factor><r_free>0.2156</r_free>"
                f"<stats_vs_cycle><new_cycle>"
                f"<cycle>0</cycle><r_factor>{long_r}</r_factor><r_free>0.2156</r_free>"
                f"</new_cycle></stats_vs_cycle></Overall_stats>"
            )
            long_bytes = long_xml.encode("utf-8")
            long_path = xml_dir / "valid_4301_place.xml"
            long_path.write_bytes(long_bytes)
            long_info = onesar_refmac._inspect_output_artifact(
                long_path, root=xml_dir
            )
            audit = onesar_refmac._audit_refmac_xmlout(
                long_path, xmlout_info=long_info, parsed_log=None
            )
            self.assertEqual(
                audit["status"], "supported_parsed_log_unavailable"
            )
            self.assertIs(audit["valid"], True)
            self.assertEqual(audit["errors"], [])
            self.assertEqual(audit["sha256"], _sha256_bytes(long_bytes))
            self.assertEqual(audit["size_bytes"], len(long_bytes))
            self.assertEqual(audit["raw_text"], long_xml)
            self.assertEqual(audit["raw_bytes_hex"], long_bytes.hex())

            top = audit["overall_stats_top_level"]
            self.assertEqual(top["r_factor_token"], long_r)
            self.assertEqual(top["r_factor"], long_r)
            self.assertEqual(top["r_factor_decimal_places"], 4301)
            row = audit["new_cycle_rows"][0]
            self.assertEqual(row["r_factor_token"], long_r)
            self.assertEqual(row["r_factor"], long_r)
            self.assertEqual(row["r_factor_decimal_places"], 4301)

            cmp_rec = top["final_new_cycle_r_factor_comparison"]
            self._assert_conditional_r_comparison_contract(cmp_rec)
            self.assertEqual(cmp_rec["xml_raw_token"], long_r)
            self.assertEqual(cmp_rec["xml_token"], long_r)
            self.assertEqual(cmp_rec["xml_value"], long_r)
            self.assertEqual(cmp_rec["xml_decimal_places"], 4301)
            self.assertEqual(cmp_rec["log_raw_token"], long_r)
            self.assertEqual(cmp_rec["log_value"], long_r)
            self.assertEqual(cmp_rec["log_decimal_places"], 4301)
            self.assertIs(cmp_rec["exact_token_equal"], True)
            self.assertIs(cmp_rec["exact_decimal_equal"], True)
            self.assertIs(
                cmp_rec["optional_interval_diagnostics_available"], False
            )
            self.assertIsInstance(
                cmp_rec["optional_interval_diagnostics_unavailable_reason"], str
            )
            self.assertIn(
                "exceeds optional diagnostic resource budget",
                cmp_rec["optional_interval_diagnostics_unavailable_reason"],
            )
            self.assertIsNone(cmp_rec["xml_reconstructed_fixed_token"])
            self.assertIsNone(cmp_rec["reconstructed_fixed_token_equal"])
            self.assertIsNone(cmp_rec["xml_half_ulp"])
            self.assertIsNone(cmp_rec["xml_reporting_interval"])
            self.assertIsNone(cmp_rec["log_half_ulp"])
            self.assertIsNone(cmp_rec["log_reporting_interval"])
            self.assertIsNone(cmp_rec["abs_difference"])
            self.assertIsNone(cmp_rec["combined_half_ulp"])
            self.assertIsNone(cmp_rec["reporting_interval_overlap"])
            self.assertIsNone(cmp_rec["reporting_interval_overlap_width"])
            self.assertIsNone(cmp_rec["positive_separation"])
            self.assertIsNone(cmp_rec["positive_separation_fraction"])
            self.assertIsNone(cmp_rec["interval_interior_overlap"])
            self.assertIsNone(cmp_rec["interval_boundary_touch_only"])
            self.assertIsNone(cmp_rec["intervals_disjoint"])
            self.assertEqual(
                cmp_rec["comparison_status"], "exact_same_precision_match"
            )

        with self.subTest("bounded_compact_exponent_rejection_and_sentinel_retention"):
            compact_xml = (
                "<Overall_stats>"
                "<r_factor>1e-10000</r_factor><r_free>0.2156</r_free>"
                "<stats_vs_cycle><new_cycle>"
                "<cycle>0</cycle><r_factor>0.1816</r_factor><r_free>-9.99e2</r_free>"
                "<resource_probe>1e10000</resource_probe>"
                "<resource_sentinel>-9.99e2</resource_sentinel>"
                "</new_cycle></stats_vs_cycle>"
                "</Overall_stats>"
            )
            compact_bytes = compact_xml.encode("utf-8")
            compact_path = xml_dir / "compact_exponent_sentinel.xml"
            compact_path.write_bytes(compact_bytes)
            compact_info = onesar_refmac._inspect_output_artifact(
                compact_path, root=xml_dir
            )
            audit = onesar_refmac._audit_refmac_xmlout(
                compact_path, xmlout_info=compact_info, parsed_log=None
            )
            self.assertEqual(
                audit["status"], "rejected_invalid_or_contradictory"
            )
            self.assertIs(audit["well_formed_xml"], True)
            self.assertIs(audit["supported_shape"], True)
            self.assertIs(audit["valid"], False)
            self.assertIs(audit["reconciled_with_log"], False)
            self.assertEqual(audit["sha256"], _sha256_bytes(compact_bytes))
            self.assertEqual(audit["size_bytes"], len(compact_bytes))
            self.assertEqual(audit["raw_text"], compact_xml)
            self.assertEqual(audit["raw_bytes_hex"], compact_bytes.hex())

            top = audit["overall_stats_top_level"]
            self.assertEqual(top["r_factor_token"], "1e-10000")
            self.assertIsNone(top["r_factor"])
            self.assertIsNone(top["r_factor_decimal_places"])
            row = audit["new_cycle_rows"][0]
            self.assertEqual(row["r_free_token"], "-9.99e2")
            self.assertIsNone(row["r_free"])
            self.assertIsNone(row["r_free_decimal_places"])
            self.assertTrue(
                any(
                    "Invalid XML R-factor token '1e-10000' for Overall_stats/r_factor"
                    in err
                    for err in audit["errors"]
                )
            )
            self.assertTrue(
                any(
                    "Documented -999 missing-value sentinel in supported XML field new_cycle/r_free (cycle=0): '-9.99e2'"
                    in err
                    for err in audit["errors"]
                )
            )
            self.assertEqual(
                audit["other_new_cycle_sentinel_tags"],
                [
                    {
                        "new_cycle_ordinal": 0,
                        "cycle": 0,
                        "tag": "resource_sentinel",
                        "token": "-9.99e2",
                    }
                ],
            )

        self.assertEqual(decimal.getcontext().prec, orig_dec_prec)
        self.assertEqual(
            sys.get_int_max_str_digits(), orig_int_max_str_digits
        )

    def test_exact_int_fraction_formatting_and_unavailable_component_cell_tuple_maximum(
        self,
    ) -> None:
        """Group 2 (6): Bounded exact integer/fraction formatting beyond 4300 digits and one unavailable-component cell tuple maximum."""
        orig_dec_prec = decimal.getcontext().prec
        orig_int_max_str_digits = sys.get_int_max_str_digits()

        with self.subTest("exact_int_and_fraction_text_beyond_4300_digits"):
            num_int = (10**4300) + 1
            den_int = (10**4300) + 3
            expected_num_str = "1" + ("0" * 4299) + "1"
            expected_den_str = "1" + ("0" * 4299) + "3"
            expected_frac_str = f"{expected_num_str}/{expected_den_str}"
            self.assertEqual(len(expected_num_str), 4301)
            self.assertEqual(len(expected_den_str), 4301)

            self.assertEqual(
                onesar_refmac._exact_int_to_decimal_str(num_int),
                expected_num_str,
            )
            self.assertEqual(
                onesar_refmac._exact_int_to_decimal_str(den_int),
                expected_den_str,
            )
            self.assertEqual(
                onesar_refmac._exact_fraction_to_str(
                    Fraction(num_int, den_int)
                ),
                expected_frac_str,
            )
            self.assertEqual(
                onesar_refmac._exact_fraction_to_str(Fraction(num_int, 1)),
                expected_num_str,
            )
            self.assertEqual(
                onesar_refmac._format_exact_power_of_ten_fraction(
                    Fraction(num_int, 1), 0
                ),
                expected_num_str,
            )

        with self.subTest("one_unavailable_component_cell_tuple_maximum"):
            long_cell_a = "10." + ("0" * 4300) + "1"
            cell_tokens = [long_cell_a, "10", "10", "90", "90", "90"]
            tuple_cmp = onesar_refmac._compare_mtz_cell_tuple_representations(
                cell_tokens, cell_tokens, label="CELL"
            )
            self.assertEqual(tuple_cmp["label"], "CELL")
            self.assertEqual(tuple_cmp["input_raw_tokens"], cell_tokens)
            self.assertEqual(tuple_cmp["output_raw_tokens"], cell_tokens)
            self.assertIs(tuple_cmp["valid"], True)
            self.assertEqual(tuple_cmp["errors"], [])
            self.assertIs(tuple_cmp["exact_token_tuple_match"], True)
            self.assertIs(tuple_cmp["exact_decimal_tuple_match"], True)
            self.assertIs(
                tuple_cmp["normalized_exact_decimal_tuple_match"], True
            )
            self.assertIs(tuple_cmp["float32_word_tuple_match"], True)

            # Tuple maximum is explicitly None/unavailable, never substituted with another component's zero.
            self.assertIsNone(tuple_cmp["max_abs_exact_decimal_diff_str"])
            self.assertIs(
                tuple_cmp["max_abs_exact_decimal_diff_str_available"], False
            )
            self.assertIsInstance(
                tuple_cmp["max_abs_exact_decimal_diff_str_unavailable_reason"],
                str,
            )
            self.assertIn(
                "a: CELL.a",
                tuple_cmp["max_abs_exact_decimal_diff_str_unavailable_reason"],
            )
            self.assertIsNone(tuple_cmp["max_abs_exact_decimal_diff"])
            self.assertIs(
                tuple_cmp["max_abs_exact_decimal_diff_available"], False
            )
            self.assertIsInstance(
                tuple_cmp["max_abs_exact_decimal_diff_unavailable_reason"], str
            )
            self.assertIn(
                "a: CELL.a",
                tuple_cmp["max_abs_exact_decimal_diff_unavailable_reason"],
            )

            param_cmps = tuple_cmp["parameter_comparisons"]
            self.assertEqual(len(param_cmps), 6)
            comp_a = param_cmps[0]
            self.assertEqual(comp_a["parameter"], "a")
            self.assertEqual(comp_a["input_raw_token"], long_cell_a)
            self.assertEqual(comp_a["output_raw_token"], long_cell_a)
            self.assertIs(comp_a["exact_token_match"], True)
            self.assertIs(comp_a["exact_decimal_match"], True)
            self.assertIs(comp_a["valid"], True)
            self.assertIsNone(comp_a["abs_exact_decimal_diff_str"])
            self.assertIs(comp_a["abs_exact_decimal_diff_str_available"], False)
            self.assertIsNone(comp_a["abs_exact_decimal_diff"])
            self.assertIs(comp_a["abs_exact_decimal_diff_available"], False)

            for other_comp, exp_name in zip(
                param_cmps[1:], ("b", "c", "alpha", "beta", "gamma")
            ):
                self.assertEqual(other_comp["parameter"], exp_name)
                self.assertIs(other_comp["exact_token_match"], True)
                self.assertIs(other_comp["exact_decimal_match"], True)
                self.assertIs(other_comp["valid"], True)
                self.assertEqual(other_comp["abs_exact_decimal_diff_str"], "0")
                self.assertIs(
                    other_comp["abs_exact_decimal_diff_str_available"], True
                )
                self.assertEqual(other_comp["abs_exact_decimal_diff"], 0.0)
                self.assertIs(
                    other_comp["abs_exact_decimal_diff_available"], True
                )

        self.assertEqual(decimal.getcontext().prec, orig_dec_prec)
        self.assertEqual(
            sys.get_int_max_str_digits(), orig_int_max_str_digits
        )

    def _build_three_row_baseline_mtz_pair(
        self,
        *,
        hklin_header_cards: list[str] | None = None,
        hklout_header_cards: list[str] | None = None,
        hklout_columns: list[tuple[str, str, int]] | None = None,
        hklout_rows: list[tuple[float, ...]] | None = None,
    ) -> tuple[bytes, bytes, dict[str, Any]]:
        """Build the 3-row baseline HKLIN/HKLOUT pair and real input HKL ledger."""
        in_cards = (
            hklin_header_cards
            if hklin_header_cards is not None
            else _build_standard_mtz_header_cards()
        )
        out_cards = (
            hklout_header_cards
            if hklout_header_cards is not None
            else _build_standard_mtz_header_cards()
        )
        in_rows: list[tuple[float, ...]] = [
            (1.0, 0.0, 0.0, 10.0, 1.0, 0.0),
            (0.0, 1.0, 0.0, 20.0, 2.0, 0.0),
            (0.0, 0.0, 1.0, 10.0, 1.0, 1.0),
        ]
        out_cols = (
            hklout_columns
            if hklout_columns is not None
            else list(_BASELINE_HKLOUT_COLUMNS)
        )
        out_rows: list[tuple[float, ...]] = (
            hklout_rows
            if hklout_rows is not None
            else [
                (1.0, 0.0, 0.0, 10.0, 1.0, 0.0, 5.0),
                (0.0, 1.0, 0.0, 20.0, 2.0, 0.0, 10.0),
                (0.0, 0.0, 1.0, 10.0, 1.0, 1.0, 9.0),
            ]
        )
        hklin_bytes = _build_literal_mtz_bytes(
            columns=_STANDARD_HKLIN_COLUMNS,
            rows=in_rows,
            header_cards_before_columns=in_cards,
        )
        hklout_bytes = _build_literal_mtz_bytes(
            columns=out_cols,
            rows=out_rows,
            header_cards_before_columns=out_cards,
        )
        input_ledger = onesar_rerun.build_input_hkl_ledger(hklin_bytes)
        return hklin_bytes, hklout_bytes, input_ledger

    def _run_export_and_audit_pair(
        self,
        case_slug: str,
        *,
        hklin_bytes: bytes,
        hklout_bytes: bytes,
        input_ledger: dict[str, Any],
        parsed_log: dict[str, Any] | None = None,
        native_log_diagnostics: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        """Write HKLIN/HKLOUT pair to a fresh case directory, run _export_and_audit_refmac_hklout, and reopen persisted raw export."""
        case_dir = self.repo_root / "runs" / case_slug
        inputs_dir = case_dir / "inputs"
        refmac_dir = case_dir / "refmac"
        inputs_dir.mkdir(parents=True, exist_ok=True)
        refmac_dir.mkdir(parents=True, exist_ok=True)
        projected_mtz_path = inputs_dir / "projected_observations.mtz"
        hklout_path = refmac_dir / "refmac_hklout.mtz"
        raw_export_json_path = refmac_dir / "refmac_hklout_raw_export.json"
        projected_mtz_path.write_bytes(hklin_bytes)
        hklout_path.write_bytes(hklout_bytes)
        hklout_info = onesar_refmac._inspect_output_artifact(
            hklout_path, root=refmac_dir
        )
        hklout_audit, raw_export_artifact = (
            onesar_refmac._export_and_audit_refmac_hklout(
                projected_mtz_path=projected_mtz_path,
                hklout_path=hklout_path,
                hklout_info=hklout_info,
                input_ledger=input_ledger,
                parsed_log=parsed_log,
                native_log_diagnostics=native_log_diagnostics,
                raw_export_json_path=raw_export_json_path,
                refmac_dir=refmac_dir,
            )
        )
        reopened_raw_export = self._reopen_and_verify_json_artifact(
            raw_export_artifact
        )
        self.assertEqual(hklout_audit["raw_export_json"], raw_export_artifact)
        return hklout_audit, raw_export_artifact, reopened_raw_export

    def test_mtz_three_row_baseline_ledger_and_hklout_audit(self) -> None:
        """Group 3 baseline: 3-row exact ledger, raw export, 1-to-1 HKL audit, FC_ALL_LS residuals, and false native proofs."""
        hklin_bytes, hklout_bytes, input_ledger = (
            self._build_three_row_baseline_mtz_pair()
        )
        self.assertEqual(
            input_ledger["counts"],
            {
                "raw_total": 3,
                "raw_work": 2,
                "raw_free": 1,
                "raw_unassigned": 0,
                "eligible_total": 3,
                "eligible_work": 2,
                "eligible_free": 1,
                "eligible_zero_f": 0,
                "eligible_negative_f": 0,
                "ineligible_total": 0,
                "ineligible_nonfinite_f": 0,
                "ineligible_nonpositive_or_nonfinite_sigf": 0,
                "ineligible_unassigned_flag": 0,
            },
        )

        hklout_audit, _raw_art, reopened_raw = self._run_export_and_audit_pair(
            "group3_three_row_baseline",
            hklin_bytes=hklin_bytes,
            hklout_bytes=hklout_bytes,
            input_ledger=input_ledger,
        )
        self.assertEqual(reopened_raw["byte_length"], len(hklout_bytes))
        self.assertEqual(reopened_raw["sha256"], _sha256_bytes(hklout_bytes))
        self.assertIsNone(reopened_raw["raw_export_error"])
        self.assertEqual(reopened_raw["raw_export_warnings"], [])
        self.assertEqual(reopened_raw["row_count_exported"], 3)
        raw_rows = reopened_raw["rows"]
        self.assertEqual(len(raw_rows), 3)
        self.assertEqual(
            raw_rows[0]["column_words_hex"],
            {
                "H": "3f800000",
                "K": "00000000",
                "L": "00000000",
                "F-obs": "41200000",
                "SIGF-obs": "3f800000",
                "R-free-flags": "00000000",
                "FC_ALL_LS": "40a00000",
            },
        )
        self.assertEqual(
            raw_rows[0]["column_values"],
            {
                "H": 1.0,
                "K": 0.0,
                "L": 0.0,
                "F-obs": 10.0,
                "SIGF-obs": 1.0,
                "R-free-flags": 0.0,
                "FC_ALL_LS": 5.0,
            },
        )
        self.assertEqual(
            raw_rows[0]["column_value_classes"],
            {
                "H": "positive_finite",
                "K": "zero",
                "L": "zero",
                "F-obs": "positive_finite",
                "SIGF-obs": "positive_finite",
                "R-free-flags": "zero",
                "FC_ALL_LS": "positive_finite",
            },
        )

        self.assertEqual(hklout_audit["status"], "valid")
        self.assertIs(hklout_audit["valid"], True)
        self.assertEqual(hklout_audit["errors"], [])

        ctx = hklout_audit["crystallographic_context"]
        self.assertIs(ctx["symmetry_exact_match"], True)
        self.assertIs(ctx["cell_representation_valid"], True)
        self.assertIs(ctx["output_dcell_matches_output_cell"], True)
        self.assertEqual(ctx["max_abs_cell_parameter_diff_str"], "0")
        self.assertEqual(ctx["max_abs_cell_parameter_diff"], 0.0)
        self.assertEqual(ctx["max_abs_reso_diff_str"], "0")
        self.assertEqual(ctx["max_abs_reso_diff"], 0.0)

        one_to_one = hklout_audit["one_to_one_hkl_audit"]
        self.assertIs(one_to_one["row_order_preserved"], True)
        self.assertEqual(one_to_one["missing_observed_domain_hkl_keys"], [])
        self.assertEqual(one_to_one["missing_eligible_hkl_keys"], [])
        self.assertEqual(one_to_one["missing_ineligible_padding_hkl_keys"], [])
        self.assertEqual(one_to_one["unexpected_extra_output_hkl_keys"], [])
        self.assertEqual(one_to_one["output_duplicate_hkl_keys"], [])
        self.assertEqual(one_to_one["output_nonintegral_hkl_rows"], [])
        self.assertEqual(one_to_one["usable_flag_flips"], [])
        self.assertEqual(one_to_one["missing_or_invalid_usable_flags"], [])
        self.assertEqual(one_to_one["padding_nan_preserved_keys"], [])
        self.assertEqual(one_to_one["padding_nan_to_free_zero_keys"], [])
        scaling = one_to_one["fp_sigfp_scaling"]
        self.assertEqual(scaling["usable_fp_word_unchanged_count"], 3)
        self.assertEqual(scaling["usable_fp_rescaled_count"], 0)
        self.assertEqual(scaling["usable_sigfp_word_unchanged_count"], 3)
        self.assertEqual(scaling["usable_sigfp_rescaled_count"], 0)
        self.assertEqual(scaling["usable_free_word_unchanged_count"], 3)
        self.assertEqual(scaling["usable_free_word_changed_count"], 0)
        self.assertEqual(scaling["fp_ratio_min"], 1.0)
        self.assertEqual(scaling["fp_ratio_max"], 1.0)
        self.assertEqual(scaling["fp_ratio_mean"], 1.0)
        self.assertEqual(scaling["sigfp_ratio_min"], 1.0)
        self.assertEqual(scaling["sigfp_ratio_max"], 1.0)
        self.assertEqual(scaling["sigfp_ratio_mean"], 1.0)

        pops = hklout_audit["populations"]
        self.assertEqual(
            pops["input_mtz_population"],
            {
                "free_flag_value": 1,
                "work_flag_value": 0,
                "total_rows": 3,
                "observed_domain_rows": 3,
                "positive_amplitude_rows": 3,
                "zero_or_negative_f_rows": 0,
                "work_observed_rows": 2,
                "free_observed_rows": 1,
                "work_positive_rows": 2,
                "free_positive_rows": 1,
                "ineligible_all_nan_padding_rows": 0,
            },
        )
        self.assertEqual(
            pops["read_eligible_population"],
            {
                "free_flag_value": 1,
                "work_flag_value": 0,
                "observed_domain_total": 3,
                "positive_amplitude_total": 3,
                "zero_or_negative_f_total": 0,
                "work_read_eligible": 2,
                "free_read_eligible": 1,
            },
        )
        self.assertEqual(
            pops["output_mtz_population"],
            {
                "free_flag_value": 1,
                "work_flag_value": 0,
                "total_rows": 3,
                "integral_unique_hkl_rows": 3,
                "observed_domain_fp_sigfp_rows": 3,
                "positive_fp_sigfp_rows": 3,
                "zero_or_negative_fp_rows": 0,
                "work_positive_fp_sigfp_rows": 2,
                "free_positive_fp_sigfp_rows": 1,
                "nan_fp_sigfp_rows": 0,
                "padding_nan_preserved_rows": 0,
                "padding_nan_to_free_zero_rows": 0,
                "fc_all_ls_present": True,
                "fc_all_ls_finite_total_rows": 3,
                "fc_all_ls_finite_on_eligible_rows": 3,
                "fc_all_ls_finite_on_padding_rows": 0,
                "fwt_present": False,
                "fwt_finite_total_rows": 0,
            },
        )

        # Independently declared exact rational numerator/denominator on the 3-row baseline fixture:
        # Work rows (FREE == 0): |10 - 5| + |20 - 10| = 15 over 10 + 20 = 30 -> 15/30 = 1/2 = 0.5.
        # Free row (FREE == 1): |10 - 9| = 1 over 10 -> 1/10 = 0.1.
        expected_work_num = Fraction(15)
        expected_work_den = Fraction(30)
        expected_r_work_frac = expected_work_num / expected_work_den
        expected_free_num = Fraction(1)
        expected_free_den = Fraction(10)
        expected_r_free_frac = expected_free_num / expected_free_den
        self.assertEqual(expected_r_work_frac, Fraction(1, 2))
        self.assertEqual(expected_r_free_frac, Fraction(1, 10))
        observed_work_num = sum(
            abs(
                Fraction(r["column_values"]["F-obs"])
                - Fraction(r["column_values"]["FC_ALL_LS"])
            )
            for r in raw_rows
            if r["column_values"]["R-free-flags"] == 0.0
        )
        observed_work_den = sum(
            Fraction(r["column_values"]["F-obs"])
            for r in raw_rows
            if r["column_values"]["R-free-flags"] == 0.0
        )
        observed_free_num = sum(
            abs(
                Fraction(r["column_values"]["F-obs"])
                - Fraction(r["column_values"]["FC_ALL_LS"])
            )
            for r in raw_rows
            if r["column_values"]["R-free-flags"] == 1.0
        )
        observed_free_den = sum(
            Fraction(r["column_values"]["F-obs"])
            for r in raw_rows
            if r["column_values"]["R-free-flags"] == 1.0
        )
        self.assertEqual(observed_work_num, expected_work_num)
        self.assertEqual(observed_work_den, expected_work_den)
        self.assertEqual(observed_free_num, expected_free_num)
        self.assertEqual(observed_free_den, expected_free_den)

        fc_audit = hklout_audit["fc_all_ls_audit"]
        self.assertIs(fc_audit["fc_all_ls_present"], True)
        self.assertEqual(
            fc_audit["fc_all_ls_column_descriptor"]["type"], "F"
        )
        self.assertEqual(fc_audit["candidate_overall_work_count"], 2)
        self.assertEqual(fc_audit["candidate_overall_free_count"], 1)
        self.assertEqual(
            fc_audit["candidate_overall_r_work"], float(expected_r_work_frac)
        )
        self.assertEqual(fc_audit["candidate_overall_r_work"], 0.5)
        self.assertEqual(
            fc_audit["candidate_overall_r_free"], float(expected_r_free_frac)
        )
        self.assertEqual(fc_audit["candidate_overall_r_free"], 0.1)

        for proof_key, reason_key in _PROOF_TO_UNPROVEN_REASON_KEYS:
            self.assertIs(hklout_audit[proof_key], False)
            self.assertIsInstance(hklout_audit[reason_key], str)
            self.assertTrue(bool(str(hklout_audit[reason_key]).strip()))

    def _build_five_row_extended_mtz_pair(
        self,
        *,
        out_rows_override: list[tuple[float, ...]] | None = None,
    ) -> tuple[bytes, bytes, dict[str, Any]]:
        """Build the 5-row reorder/rescale/padding + special float32 word HKLIN/HKLOUT pair and ledger."""
        cards = _build_standard_mtz_header_cards()
        in_rows: list[tuple[float, ...]] = [
            (1.0, 0.0, 0.0, 10.0, 1.0, 0.0),
            (0.0, 1.0, 0.0, 0.0, 1.0, 1.0),
            (0.0, 0.0, 1.0, -2.0, 1.0, 0.0),
            (1.0, 1.0, 0.0, 20.0, 2.0, 1.0),
            (1.0, 1.0, 1.0, math.nan, math.nan, math.nan),
        ]
        hklin_unpatched = _build_literal_mtz_bytes(
            columns=_STANDARD_HKLIN_COLUMNS,
            rows=in_rows,
            header_cards_before_columns=cards,
        )
        hklin_bytes = _patch_mtz_data_words(
            hklin_unpatched,
            ncols=6,
            nrows=5,
            patches=[
                (4, 3, 0x7FC12345),
                (4, 4, 0x7FC12345),
                (4, 5, 0x7FC12345),
            ],
        )
        input_ledger = onesar_rerun.build_input_hkl_ledger(hklin_bytes)

        # Output columns: H(0), K(1), L(2), FP(3), SIGFP(4), FREE(5), FC_ALL_LS(6),
        # PHIC_ALL_LS(7), FC_ALL(8), FWT(9), PHWT(10).
        # Emitted in input-index order [4, 3, 2, 1, 0].
        out_rows: list[tuple[float, ...]] = (
            out_rows_override
            if out_rows_override is not None
            else [
                (
                    1.0,
                    1.0,
                    1.0,
                    math.nan,
                    math.nan,
                    0.0,
                    22.0,
                    0.0,
                    0.0,
                    math.nan,
                    0.0,
                ),
                (
                    1.0,
                    1.0,
                    0.0,
                    40.0,
                    4.0,
                    1.0,
                    36.0,
                    0.0,
                    0.0,
                    math.inf,
                    0.0,
                ),
                (
                    0.0,
                    0.0,
                    1.0,
                    -4.0,
                    2.0,
                    0.0,
                    18.0,
                    0.0,
                    0.0,
                    -math.inf,
                    0.0,
                ),
                (
                    0.0,
                    1.0,
                    0.0,
                    0.0,
                    2.0,
                    1.0,
                    14.0,
                    0.0,
                    0.0,
                    -0.0,
                    0.0,
                ),
                (
                    1.0,
                    0.0,
                    0.0,
                    20.0,
                    2.0,
                    0.0,
                    10.0,
                    0.0,
                    0.0,
                    12.0,
                    0.0,
                ),
            ]
        )
        hklout_unpatched = _build_literal_mtz_bytes(
            columns=_EXTENDED_HKLOUT_COLUMNS,
            rows=out_rows,
            header_cards_before_columns=cards,
        )
        hklout_bytes = _patch_mtz_data_words(
            hklout_unpatched,
            ncols=11,
            nrows=5,
            patches=[
                (0, 3, 0x7FC12345),
                (0, 4, 0x7FC12345),
                (0, 9, 0x7FC12345),
            ],
        )
        return hklin_bytes, hklout_bytes, input_ledger

    def test_mtz_five_row_reorder_rescale_padding_and_special_float32_words(
        self,
    ) -> None:
        """Group 3 (1): 5-row reorder, 2x FP/SIGFP rescaling, NaN->FREE=0 padding, and NaN/+Inf/-Inf/-0.0/+0.0 raw word classification."""
        hklin_bytes, hklout_bytes, input_ledger = (
            self._build_five_row_extended_mtz_pair()
        )

        # Verify bounded word-patch helper bounds checks.
        with self.assertRaises(ValueError):
            _patch_mtz_data_words(
                hklin_bytes, ncols=6, nrows=5, patches=[(5, 0, 0)]
            )
        with self.assertRaises(ValueError):
            _patch_mtz_data_words(
                hklin_bytes, ncols=6, nrows=5, patches=[(0, 6, 0)]
            )
        with self.assertRaises(ValueError):
            _patch_mtz_data_words(
                hklin_bytes, ncols=6, nrows=5, patches=[(0, 0, 0x100000000)]
            )
        with self.assertRaises(ValueError):
            _patch_mtz_data_words(
                hklin_bytes, ncols=7, nrows=5, patches=[(0, 0, 0)]
            )

        self.assertEqual(
            input_ledger["counts"],
            {
                "raw_total": 5,
                "raw_work": 2,
                "raw_free": 2,
                "raw_unassigned": 1,
                "eligible_total": 4,
                "eligible_work": 2,
                "eligible_free": 2,
                "eligible_zero_f": 1,
                "eligible_negative_f": 1,
                "ineligible_total": 1,
                "ineligible_nonfinite_f": 1,
                "ineligible_nonpositive_or_nonfinite_sigf": 0,
                "ineligible_unassigned_flag": 1,
            },
        )
        self.assertEqual(len(input_ledger["ineligible_rows"]), 1)
        inel_row = input_ledger["ineligible_rows"][0]
        self.assertEqual(inel_row["hkl"], [1, 1, 1])
        self.assertIsNone(inel_row["f_obs"])
        self.assertIsNone(inel_row["sigf_obs"])
        self.assertIsNone(inel_row["r_free_flag"])
        self.assertEqual(inel_row["partition"], "unassigned")
        self.assertEqual(inel_row["f_obs_word_hex"], "7fc12345")
        self.assertEqual(inel_row["sigf_obs_word_hex"], "7fc12345")
        self.assertEqual(inel_row["r_free_flag_word_hex"], "7fc12345")

        hklout_audit, _raw_art, reopened_raw = self._run_export_and_audit_pair(
            "group3_five_row_reorder_rescale_padding",
            hklin_bytes=hklin_bytes,
            hklout_bytes=hklout_bytes,
            input_ledger=input_ledger,
        )
        self.assertIsNone(reopened_raw["raw_export_error"])
        self.assertEqual(reopened_raw["raw_export_warnings"], [])
        self.assertEqual(reopened_raw["row_count_exported"], 5)
        raw_rows = reopened_raw["rows"]
        self.assertEqual(len(raw_rows), 5)

        # Output row 0 (input row 4, HKL [1, 1, 1]): patched NaN payload 7fc12345 in F-obs, SIGF-obs, FWT, and R-free-flags == +0.0 (00000000).
        self.assertEqual(raw_rows[0]["column_words_hex"]["F-obs"], "7fc12345")
        self.assertIsNone(raw_rows[0]["column_values"]["F-obs"])
        self.assertEqual(raw_rows[0]["column_value_classes"]["F-obs"], "nan")
        self.assertEqual(raw_rows[0]["column_words_hex"]["SIGF-obs"], "7fc12345")
        self.assertIsNone(raw_rows[0]["column_values"]["SIGF-obs"])
        self.assertEqual(raw_rows[0]["column_value_classes"]["SIGF-obs"], "nan")
        self.assertEqual(raw_rows[0]["column_words_hex"]["R-free-flags"], "00000000")
        self.assertEqual(raw_rows[0]["column_values"]["R-free-flags"], 0.0)
        self.assertEqual(raw_rows[0]["column_value_classes"]["R-free-flags"], "zero")
        self.assertEqual(raw_rows[0]["column_words_hex"]["FC_ALL"], "00000000")
        self.assertEqual(raw_rows[0]["column_values"]["FC_ALL"], 0.0)
        self.assertEqual(raw_rows[0]["column_value_classes"]["FC_ALL"], "zero")
        self.assertEqual(
            raw_rows[0]["column_values"]["FC_ALL_LS"], 22.0
        )
        self.assertEqual(
            raw_rows[0]["column_value_classes"]["FC_ALL_LS"], "positive_finite"
        )
        self.assertEqual(raw_rows[0]["column_words_hex"]["FWT"], "7fc12345")
        self.assertIsNone(raw_rows[0]["column_values"]["FWT"])
        self.assertEqual(raw_rows[0]["column_value_classes"]["FWT"], "nan")

        # Output row 1 (FWT = +Inf -> 7f800000, None, "pos_inf").
        self.assertEqual(raw_rows[1]["column_words_hex"]["FWT"], "7f800000")
        self.assertIsNone(raw_rows[1]["column_values"]["FWT"])
        self.assertEqual(raw_rows[1]["column_value_classes"]["FWT"], "pos_inf")

        # Output row 2 (F-obs = -4.0 -> "negative_finite"; FWT = -Inf -> ff800000, None, "neg_inf").
        self.assertEqual(raw_rows[2]["column_values"]["F-obs"], -4.0)
        self.assertEqual(
            raw_rows[2]["column_value_classes"]["F-obs"], "negative_finite"
        )
        self.assertEqual(raw_rows[2]["column_words_hex"]["FWT"], "ff800000")
        self.assertIsNone(raw_rows[2]["column_values"]["FWT"])
        self.assertEqual(raw_rows[2]["column_value_classes"]["FWT"], "neg_inf")

        # Output row 3 (F-obs = +0.0 -> 00000000/"zero"; FWT = -0.0 -> 80000000/"neg_zero").
        self.assertEqual(raw_rows[3]["column_words_hex"]["F-obs"], "00000000")
        self.assertEqual(raw_rows[3]["column_values"]["F-obs"], 0.0)
        self.assertEqual(raw_rows[3]["column_value_classes"]["F-obs"], "zero")
        self.assertEqual(raw_rows[3]["column_words_hex"]["FWT"], "80000000")
        self.assertEqual(raw_rows[3]["column_values"]["FWT"], 0.0)
        self.assertEqual(raw_rows[3]["column_value_classes"]["FWT"], "neg_zero")

        # Output row 4 (FWT = 12.0 -> 41400000/"positive_finite").
        self.assertEqual(raw_rows[4]["column_words_hex"]["FWT"], "41400000")
        self.assertEqual(raw_rows[4]["column_values"]["FWT"], 12.0)
        self.assertEqual(
            raw_rows[4]["column_value_classes"]["FWT"], "positive_finite"
        )

        self.assertEqual(hklout_audit["status"], "valid")
        self.assertIs(hklout_audit["valid"], True)
        self.assertEqual(hklout_audit["errors"], [])

        one_to_one = hklout_audit["one_to_one_hkl_audit"]
        self.assertIs(one_to_one["row_order_preserved"], False)
        self.assertEqual(one_to_one["missing_observed_domain_hkl_keys"], [])
        self.assertEqual(one_to_one["missing_eligible_hkl_keys"], [])
        self.assertEqual(one_to_one["missing_ineligible_padding_hkl_keys"], [])
        self.assertEqual(one_to_one["unexpected_extra_output_hkl_keys"], [])
        self.assertEqual(one_to_one["output_duplicate_hkl_keys"], [])
        self.assertEqual(one_to_one["output_nonintegral_hkl_rows"], [])
        self.assertEqual(one_to_one["usable_flag_flips"], [])
        self.assertEqual(one_to_one["missing_or_invalid_usable_flags"], [])
        self.assertEqual(one_to_one["padding_nan_preserved_keys"], [])
        self.assertEqual(one_to_one["padding_nan_to_free_zero_keys"], [[1, 1, 1]])
        self.assertEqual(len(one_to_one["padding_nan_to_free_zero_keys"]), 1)

        scaling = one_to_one["fp_sigfp_scaling"]
        self.assertEqual(scaling["usable_fp_word_unchanged_count"], 1)
        self.assertEqual(scaling["usable_fp_rescaled_count"], 3)
        self.assertEqual(scaling["usable_sigfp_word_unchanged_count"], 0)
        self.assertEqual(scaling["usable_sigfp_rescaled_count"], 4)
        self.assertEqual(scaling["usable_free_word_unchanged_count"], 4)
        self.assertEqual(scaling["usable_free_word_changed_count"], 0)
        self.assertEqual(scaling["fp_ratio_min"], 2.0)
        self.assertEqual(scaling["fp_ratio_max"], 2.0)
        self.assertEqual(scaling["fp_ratio_mean"], 2.0)
        self.assertEqual(scaling["sigfp_ratio_min"], 2.0)
        self.assertEqual(scaling["sigfp_ratio_max"], 2.0)
        self.assertEqual(scaling["sigfp_ratio_mean"], 2.0)

        pops = hklout_audit["populations"]
        self.assertEqual(
            pops["input_mtz_population"],
            {
                "free_flag_value": 1,
                "work_flag_value": 0,
                "total_rows": 5,
                "observed_domain_rows": 4,
                "positive_amplitude_rows": 2,
                "zero_or_negative_f_rows": 2,
                "work_observed_rows": 2,
                "free_observed_rows": 2,
                "work_positive_rows": 1,
                "free_positive_rows": 1,
                "ineligible_all_nan_padding_rows": 1,
            },
        )
        self.assertEqual(
            pops["read_eligible_population"],
            {
                "free_flag_value": 1,
                "work_flag_value": 0,
                "observed_domain_total": 4,
                "positive_amplitude_total": 2,
                "zero_or_negative_f_total": 2,
                "work_read_eligible": 1,
                "free_read_eligible": 1,
            },
        )
        self.assertEqual(
            pops["output_mtz_population"],
            {
                "free_flag_value": 1,
                "work_flag_value": 0,
                "total_rows": 5,
                "integral_unique_hkl_rows": 5,
                "observed_domain_fp_sigfp_rows": 4,
                "positive_fp_sigfp_rows": 2,
                "zero_or_negative_fp_rows": 2,
                "work_positive_fp_sigfp_rows": 1,
                "free_positive_fp_sigfp_rows": 1,
                "nan_fp_sigfp_rows": 1,
                "padding_nan_preserved_rows": 0,
                "padding_nan_to_free_zero_rows": 1,
                "fc_all_ls_present": True,
                "fc_all_ls_finite_total_rows": 5,
                "fc_all_ls_finite_on_eligible_rows": 4,
                "fc_all_ls_finite_on_padding_rows": 1,
                "fwt_present": True,
                "fwt_finite_total_rows": 2,
            },
        )

        # Candidate FC_ALL_LS residual uses only positive-amplitude eligible rows (1 work, 1 free) and never uses FC_ALL (all zeros).
        # Positive-amplitude work row [1, 0, 0]: |20 - 10| / 20 = 10/20 = 1/2 = 0.5.
        # Positive-amplitude free row [1, 1, 0]: |40 - 36| / 40 = 4/40 = 1/10 = 0.1.
        expected_5_work_num = Fraction(10)
        expected_5_work_den = Fraction(20)
        expected_5_r_work_frac = expected_5_work_num / expected_5_work_den
        expected_5_free_num = Fraction(4)
        expected_5_free_den = Fraction(40)
        expected_5_r_free_frac = expected_5_free_num / expected_5_free_den
        self.assertEqual(expected_5_r_work_frac, Fraction(1, 2))
        self.assertEqual(expected_5_r_free_frac, Fraction(1, 10))
        self.assertEqual(
            abs(
                Fraction(raw_rows[4]["column_values"]["F-obs"])
                - Fraction(raw_rows[4]["column_values"]["FC_ALL_LS"])
            ),
            expected_5_work_num,
        )
        self.assertEqual(
            Fraction(raw_rows[4]["column_values"]["F-obs"]),
            expected_5_work_den,
        )
        self.assertEqual(
            abs(
                Fraction(raw_rows[1]["column_values"]["F-obs"])
                - Fraction(raw_rows[1]["column_values"]["FC_ALL_LS"])
            ),
            expected_5_free_num,
        )
        self.assertEqual(
            Fraction(raw_rows[1]["column_values"]["F-obs"]),
            expected_5_free_den,
        )

        fc_audit = hklout_audit["fc_all_ls_audit"]
        self.assertIs(fc_audit["fc_all_ls_present"], True)
        self.assertEqual(
            fc_audit["fc_all_ls_column_descriptor"]["type"], "F"
        )
        self.assertEqual(fc_audit["candidate_overall_work_count"], 1)
        self.assertEqual(
            fc_audit["candidate_overall_r_work"], float(expected_5_r_work_frac)
        )
        self.assertEqual(fc_audit["candidate_overall_r_work"], 0.5)
        self.assertEqual(fc_audit["candidate_overall_free_count"], 1)
        self.assertEqual(
            fc_audit["candidate_overall_r_free"], float(expected_5_r_free_frac)
        )
        self.assertEqual(fc_audit["candidate_overall_r_free"], 0.1)

        for proof_key, reason_key in _PROOF_TO_UNPROVEN_REASON_KEYS:
            self.assertIs(hklout_audit[proof_key], False)
            self.assertIsInstance(hklout_audit[reason_key], str)
            self.assertTrue(bool(str(hklout_audit[reason_key]).strip()))

    def test_mtz_ledger_defects_hkl_domain_flag_violations_and_no_fc_all_fallback(
        self,
    ) -> None:
        """Group 3 (2): Missing/malformed input ledger, missing/new/duplicate/nonintegral HKLs, flag flip/NaN on zero/negative F, and no FC_ALL fallback."""
        hklin_bytes, hklout_bytes, input_ledger = (
            self._build_three_row_baseline_mtz_pair()
        )

        with self.subTest("empty_and_malformed_input_ledger"):
            empty_idx = onesar_refmac._validate_and_index_input_hkl_ledger({})
            self.assertIs(empty_idx["valid"], False)
            self.assertTrue(
                any(
                    "input_ledger missing required top-level key(s): ['raw_rows', 'eligible_by_hkl', 'ineligible_rows', 'declared_flag_values', 'work_flag_value', 'free_flag_value', 'counts']"
                    in err
                    for err in empty_idx["errors"]
                )
            )
            self.assertTrue(
                any(
                    "input_ledger['raw_rows'] must be a non-empty list" in err
                    for err in empty_idx["errors"]
                )
            )
            empty_audit, _, _ = self._run_export_and_audit_pair(
                "group3_empty_ledger",
                hklin_bytes=hklin_bytes,
                hklout_bytes=hklout_bytes,
                input_ledger={},
            )
            self.assertEqual(
                empty_audit["status"], "rejected_invalid_or_inconsistent"
            )
            self.assertIs(empty_audit["valid"], False)
            self.assertNotIn(
                "input_ledger_valid", empty_audit["one_to_one_hkl_audit"]
            )
            self.assertTrue(
                any(
                    "input_ledger['raw_rows'] must be a non-empty list" in err
                    for err in empty_audit["errors"]
                )
            )

            malformed_ledger = json.loads(json.dumps(input_ledger))
            del malformed_ledger["raw_rows"][0]["f_obs_word_hex"]
            mal_idx = onesar_refmac._validate_and_index_input_hkl_ledger(
                malformed_ledger
            )
            self.assertIs(mal_idx["valid"], False)
            self.assertTrue(
                any(
                    "input_ledger['raw_rows'][0] missing required key(s): ['f_obs_word_hex']"
                    in err
                    for err in mal_idx["errors"]
                )
            )
            mal_audit, _, _ = self._run_export_and_audit_pair(
                "group3_malformed_ledger",
                hklin_bytes=hklin_bytes,
                hklout_bytes=hklout_bytes,
                input_ledger=malformed_ledger,
            )
            self.assertEqual(
                mal_audit["status"], "rejected_invalid_or_inconsistent"
            )
            self.assertIs(mal_audit["valid"], False)
            self.assertNotIn(
                "input_ledger_valid", mal_audit["one_to_one_hkl_audit"]
            )
            self.assertTrue(
                any(
                    "input_ledger['raw_rows'][0] missing required key(s): ['f_obs_word_hex']"
                    in err
                    for err in mal_audit["errors"]
                )
            )

        with self.subTest("same_count_missing_and_unexpected_extra_hkl"):
            _, bad_hklout, _ = self._build_three_row_baseline_mtz_pair(
                hklout_rows=[
                    (2.0, 0.0, 0.0, 10.0, 1.0, 0.0, 5.0),
                    (0.0, 1.0, 0.0, 20.0, 2.0, 0.0, 10.0),
                    (0.0, 0.0, 1.0, 10.0, 1.0, 1.0, 9.0),
                ]
            )
            audit, _, _ = self._run_export_and_audit_pair(
                "group3_missing_and_extra_hkl",
                hklin_bytes=hklin_bytes,
                hklout_bytes=bad_hklout,
                input_ledger=input_ledger,
            )
            self.assertEqual(
                audit["status"], "rejected_invalid_or_inconsistent"
            )
            self.assertIs(audit["valid"], False)
            oto = audit["one_to_one_hkl_audit"]
            self.assertEqual(
                oto["missing_observed_domain_hkl_keys"], [[1, 0, 0]]
            )
            self.assertEqual(oto["missing_eligible_hkl_keys"], [[1, 0, 0]])
            self.assertEqual(oto["missing_ineligible_padding_hkl_keys"], [])
            self.assertEqual(oto["unexpected_extra_output_hkl_keys"], [[2, 0, 0]])

        with self.subTest("duplicate_output_hkl"):
            _, dup_hklout, _ = self._build_three_row_baseline_mtz_pair(
                hklout_rows=[
                    (1.0, 0.0, 0.0, 10.0, 1.0, 0.0, 5.0),
                    (1.0, 0.0, 0.0, 20.0, 2.0, 0.0, 10.0),
                    (0.0, 0.0, 1.0, 10.0, 1.0, 1.0, 9.0),
                ]
            )
            audit, _, _ = self._run_export_and_audit_pair(
                "group3_duplicate_output_hkl",
                hklin_bytes=hklin_bytes,
                hklout_bytes=dup_hklout,
                input_ledger=input_ledger,
            )
            self.assertEqual(
                audit["status"], "rejected_invalid_or_inconsistent"
            )
            self.assertIs(audit["valid"], False)
            oto = audit["one_to_one_hkl_audit"]
            self.assertEqual(oto["output_duplicate_hkl_keys"], [[1, 0, 0]])
            self.assertEqual(
                oto["missing_observed_domain_hkl_keys"], [[0, 1, 0]]
            )

        with self.subTest("nonintegral_output_hkl"):
            _, nonint_hklout, _ = self._build_three_row_baseline_mtz_pair(
                hklout_rows=[
                    (1.5, 0.0, 0.0, 10.0, 1.0, 0.0, 5.0),
                    (0.0, 1.0, 0.0, 20.0, 2.0, 0.0, 10.0),
                    (0.0, 0.0, 1.0, 10.0, 1.0, 1.0, 9.0),
                ]
            )
            audit, _, _ = self._run_export_and_audit_pair(
                "group3_nonintegral_output_hkl",
                hklin_bytes=hklin_bytes,
                hklout_bytes=nonint_hklout,
                input_ledger=input_ledger,
            )
            self.assertEqual(
                audit["status"], "rejected_invalid_or_inconsistent"
            )
            self.assertIs(audit["valid"], False)
            oto = audit["one_to_one_hkl_audit"]
            self.assertEqual(
                oto["output_nonintegral_hkl_rows"],
                [{"row_index": 0, "hkl_floats": [1.5, 0.0, 0.0]}],
            )

        with self.subTest("usable_flag_flip_on_zero_f_and_nan_flag_on_negative_f"):
            five_in, five_out_base, five_ledger = (
                self._build_five_row_extended_mtz_pair()
            )
            # In _build_five_row_extended_mtz_pair:
            # Output row 2 is HKL (0, 0, 1) (negative F = -2.0, input flag = 0), col 5 is FREE.
            # Output row 3 is HKL (0, 1, 0) (zero F = 0.0, input flag = 1), col 5 is FREE.
            # Patch output row 3 col 5 to 0.0 (0x00000000 -> flag flip 1 -> 0 on zero-F row)
            # and output row 2 col 5 to NaN (0x7fc12345 -> missing flag on negative-F row).
            flag_viol_hklout = _patch_mtz_data_words(
                five_out_base,
                ncols=11,
                nrows=5,
                patches=[
                    (3, 5, 0x00000000),
                    (2, 5, 0x7FC12345),
                ],
            )
            audit, _, _ = self._run_export_and_audit_pair(
                "group3_flag_flip_and_nan_on_zero_neg_f",
                hklin_bytes=five_in,
                hklout_bytes=flag_viol_hklout,
                input_ledger=five_ledger,
            )
            self.assertEqual(
                audit["status"], "rejected_invalid_or_inconsistent"
            )
            self.assertIs(audit["valid"], False)
            oto = audit["one_to_one_hkl_audit"]
            self.assertEqual(
                oto["usable_flag_flips"],
                [
                    {
                        "hkl": [0, 1, 0],
                        "input_r_free_flag": 1,
                        "output_free_flag": 0,
                        "output_free_word_hex": "00000000",
                    }
                ],
            )
            self.assertEqual(
                oto["missing_or_invalid_usable_flags"],
                [
                    {
                        "hkl": [0, 0, 1],
                        "input_r_free_flag": 0,
                        "output_free": None,
                        "output_free_word_hex": "7fc12345",
                        "output_free_class": "nan",
                    }
                ],
            )
            self.assertEqual(
                oto["fp_sigfp_scaling"]["usable_free_word_changed_count"], 2
            )

        with self.subTest("absent_fc_all_ls_never_falls_back_to_fc_all"):
            cols_no_fc_all_ls: list[tuple[str, str, int]] = [
                ("H", "H", 0),
                ("K", "H", 0),
                ("L", "H", 0),
                ("F-obs", "F", 1),
                ("SIGF-obs", "Q", 1),
                ("R-free-flags", "I", 1),
                ("FC_ALL", "F", 1),
            ]
            _, no_ls_hklout, _ = self._build_three_row_baseline_mtz_pair(
                hklout_columns=cols_no_fc_all_ls,
                hklout_rows=[
                    (1.0, 0.0, 0.0, 10.0, 1.0, 0.0, 5.0),
                    (0.0, 1.0, 0.0, 20.0, 2.0, 0.0, 10.0),
                    (0.0, 0.0, 1.0, 10.0, 1.0, 1.0, 9.0),
                ],
            )
            audit, _, _ = self._run_export_and_audit_pair(
                "group3_no_fc_all_ls_no_fallback",
                hklin_bytes=hklin_bytes,
                hklout_bytes=no_ls_hklout,
                input_ledger=input_ledger,
            )
            fc_audit = audit["fc_all_ls_audit"]
            self.assertIs(fc_audit["fc_all_ls_present"], False)
            self.assertIsNone(fc_audit["fc_all_ls_column_descriptor"])
            self.assertEqual(fc_audit["candidate_overall_work_count"], 0)
            self.assertEqual(fc_audit["candidate_overall_free_count"], 0)
            self.assertIsNone(fc_audit["candidate_overall_r_work"])
            self.assertIsNone(fc_audit["candidate_overall_r_free"])
            self.assertEqual(
                audit["populations"]["output_mtz_population"][
                    "fc_all_ls_finite_total_rows"
                ],
                0,
            )
            self.assertIs(audit["native_residual_reconstruction_proven"], False)
            self.assertIn(
                "preselected native LS column 'FC_ALL_LS' is absent from HKLOUT",
                audit["native_residual_reconstruction_unproven_reason"],
            )

        with self.subTest(
            "decoy_fp_sigfp_free_coexisting_with_declared_native_observation_columns"
        ):
            cols_with_decoy_fp: list[tuple[str, str, int]] = [
                ("H", "H", 0),
                ("K", "H", 0),
                ("L", "H", 0),
                ("FP", "F", 1),
                ("SIGFP", "Q", 1),
                ("FREE", "I", 1),
                ("F-obs", "F", 1),
                ("SIGF-obs", "Q", 1),
                ("R-free-flags", "I", 1),
                ("FC_ALL_LS", "F", 1),
            ]
            # Decoy FP/SIGFP/FREE columns precede F-obs/SIGF-obs/R-free-flags and carry
            # poisoned/contradictory amplitudes, non-positive sigmas, and flipped flags.
            # Declared F-obs/SIGF-obs carry 2x-scaled observations and preserved R-free-flags.
            _, decoy_coexist_hklout, _ = self._build_three_row_baseline_mtz_pair(
                hklout_columns=cols_with_decoy_fp,
                hklout_rows=[
                    (1.0, 0.0, 0.0, -999.0, 0.0, 1.0, 20.0, 2.0, 0.0, 10.0),
                    (0.0, 1.0, 0.0, 999.0, 99.0, 1.0, 40.0, 4.0, 0.0, 20.0),
                    (0.0, 0.0, 1.0, 0.0, -1.0, 0.0, 20.0, 2.0, 1.0, 18.0),
                ],
            )
            audit_decoy, _, raw_decoy = self._run_export_and_audit_pair(
                "group3_decoy_fp_sigfp_free_coexisting",
                hklin_bytes=hklin_bytes,
                hklout_bytes=decoy_coexist_hklout,
                input_ledger=input_ledger,
            )
            self.assertEqual(audit_decoy["status"], "valid")
            self.assertIs(audit_decoy["valid"], True)
            self.assertEqual(audit_decoy["errors"], [])
            self.assertEqual(
                audit_decoy["output_layout_summary"]["col_indices"],
                {
                    "H": 0,
                    "K": 1,
                    "L": 2,
                    "F-obs": 6,
                    "SIGF-obs": 7,
                    "R-free-flags": 8,
                },
            )
            decoy_row0_vals = raw_decoy["rows"][0]["column_values"]
            self.assertEqual(decoy_row0_vals["FP"], -999.0)
            self.assertEqual(decoy_row0_vals["SIGFP"], 0.0)
            self.assertEqual(decoy_row0_vals["FREE"], 1.0)
            self.assertEqual(decoy_row0_vals["F-obs"], 20.0)
            self.assertEqual(decoy_row0_vals["SIGF-obs"], 2.0)
            self.assertEqual(decoy_row0_vals["R-free-flags"], 0.0)
            self.assertEqual(decoy_row0_vals["FC_ALL_LS"], 10.0)

            decoy_oto = audit_decoy["one_to_one_hkl_audit"]
            self.assertEqual(
                decoy_oto["dropped_or_invalidated_eligible_observations"], []
            )
            self.assertEqual(decoy_oto["usable_flag_flips"], [])
            decoy_scaling = decoy_oto["fp_sigfp_scaling"]
            self.assertEqual(decoy_scaling["usable_fp_word_unchanged_count"], 0)
            self.assertEqual(decoy_scaling["usable_fp_rescaled_count"], 3)
            self.assertEqual(
                decoy_scaling["usable_sigfp_word_unchanged_count"], 0
            )
            self.assertEqual(decoy_scaling["usable_sigfp_rescaled_count"], 3)
            self.assertEqual(
                decoy_scaling["usable_free_word_unchanged_count"], 3
            )
            self.assertEqual(decoy_scaling["usable_free_word_changed_count"], 0)
            self.assertEqual(decoy_scaling["fp_ratio_min"], 2.0)
            self.assertEqual(decoy_scaling["fp_ratio_max"], 2.0)
            self.assertEqual(decoy_scaling["fp_ratio_mean"], 2.0)
            self.assertEqual(decoy_scaling["sigfp_ratio_min"], 2.0)
            self.assertEqual(decoy_scaling["sigfp_ratio_max"], 2.0)
            self.assertEqual(decoy_scaling["sigfp_ratio_mean"], 2.0)

            decoy_out_pop = audit_decoy["populations"]["output_mtz_population"]
            self.assertEqual(decoy_out_pop["observed_domain_fp_sigfp_rows"], 3)
            self.assertEqual(decoy_out_pop["positive_fp_sigfp_rows"], 3)
            self.assertEqual(decoy_out_pop["work_positive_fp_sigfp_rows"], 2)
            self.assertEqual(decoy_out_pop["free_positive_fp_sigfp_rows"], 1)

            decoy_fc = audit_decoy["fc_all_ls_audit"]
            self.assertEqual(decoy_fc["candidate_overall_work_count"], 2)
            self.assertEqual(decoy_fc["candidate_overall_free_count"], 1)
            self.assertEqual(decoy_fc["candidate_overall_r_work"], 0.5)
            self.assertEqual(decoy_fc["candidate_overall_r_free"], 0.1)

        with self.subTest(
            "decoy_only_fp_sigfp_free_without_declared_native_labels_is_rejected"
        ):
            cols_decoy_only: list[tuple[str, str, int]] = [
                ("H", "H", 0),
                ("K", "H", 0),
                ("L", "H", 0),
                ("FP", "F", 1),
                ("SIGFP", "Q", 1),
                ("FREE", "I", 1),
                ("FC_ALL_LS", "F", 1),
            ]
            _, decoy_only_hklout, _ = self._build_three_row_baseline_mtz_pair(
                hklout_columns=cols_decoy_only,
                hklout_rows=[
                    (1.0, 0.0, 0.0, 10.0, 1.0, 0.0, 5.0),
                    (0.0, 1.0, 0.0, 20.0, 2.0, 0.0, 10.0),
                    (0.0, 0.0, 1.0, 10.0, 1.0, 1.0, 9.0),
                ],
            )
            audit_decoy_only, _, raw_decoy_only = (
                self._run_export_and_audit_pair(
                    "group3_decoy_only_fp_sigfp_free_rejected",
                    hklin_bytes=hklin_bytes,
                    hklout_bytes=decoy_only_hklout,
                    input_ledger=input_ledger,
                )
            )
            self.assertEqual(
                audit_decoy_only["status"], "rejected_invalid_or_inconsistent"
            )
            self.assertIs(audit_decoy_only["valid"], False)
            self.assertIsNone(audit_decoy_only["output_layout_summary"])
            self.assertEqual(
                raw_decoy_only["rows"][0]["column_values"]["FP"], 10.0
            )
            for expected_err in (
                "HKLOUT failed strict MTZ layout/dataset inspection: ValueError: selected MTZ columns must have F/Q/I types",
                "HKLOUT missing unique required column 'F-obs' (found 0)",
                "HKLOUT missing unique required column 'SIGF-obs' (found 0)",
                "HKLOUT missing unique required column 'R-free-flags' (found 0)",
            ):
                self.assertIn(expected_err, audit_decoy_only["errors"])

        with self.subTest(
            "declared_observation_columns_wrong_type_duplicate_and_multi_dataset_rejected"
        ):
            cols_wrong_type: list[tuple[str, str, int]] = [
                ("H", "H", 0),
                ("K", "H", 0),
                ("L", "H", 0),
                ("F-obs", "J", 1),
                ("SIGF-obs", "Q", 1),
                ("R-free-flags", "I", 1),
                ("FC_ALL_LS", "F", 1),
            ]
            _, wrong_type_hklout, _ = self._build_three_row_baseline_mtz_pair(
                hklout_columns=cols_wrong_type,
            )
            audit_wrong_type, _, _ = self._run_export_and_audit_pair(
                "group3_declared_obs_wrong_type",
                hklin_bytes=hklin_bytes,
                hklout_bytes=wrong_type_hklout,
                input_ledger=input_ledger,
            )
            self.assertEqual(
                audit_wrong_type["status"], "rejected_invalid_or_inconsistent"
            )
            self.assertIs(audit_wrong_type["valid"], False)
            self.assertIn(
                "HKLOUT column 'F-obs' has type 'J', expected 'F'",
                audit_wrong_type["errors"],
            )

            cols_dup_fobs: list[tuple[str, str, int]] = [
                ("H", "H", 0),
                ("K", "H", 0),
                ("L", "H", 0),
                ("F-obs", "F", 1),
                ("F-obs", "F", 1),
                ("SIGF-obs", "Q", 1),
                ("R-free-flags", "I", 1),
                ("FC_ALL_LS", "F", 1),
            ]
            _, dup_fobs_hklout, _ = self._build_three_row_baseline_mtz_pair(
                hklout_columns=cols_dup_fobs,
                hklout_rows=[
                    (1.0, 0.0, 0.0, 10.0, 10.0, 1.0, 0.0, 5.0),
                    (0.0, 1.0, 0.0, 20.0, 20.0, 2.0, 0.0, 10.0),
                    (0.0, 0.0, 1.0, 10.0, 10.0, 1.0, 1.0, 9.0),
                ],
            )
            audit_dup_fobs, _, _ = self._run_export_and_audit_pair(
                "group3_declared_obs_duplicate_fobs",
                hklin_bytes=hklin_bytes,
                hklout_bytes=dup_fobs_hklout,
                input_ledger=input_ledger,
            )
            self.assertEqual(
                audit_dup_fobs["status"], "rejected_invalid_or_inconsistent"
            )
            self.assertIs(audit_dup_fobs["valid"], False)
            self.assertIn(
                "HKLOUT contains duplicate column label(s): ['F-obs']",
                audit_dup_fobs["errors"],
            )
            self.assertIn(
                "HKLOUT missing unique required column 'F-obs' (found 2)",
                audit_dup_fobs["errors"],
            )

            cols_multi_ds: list[tuple[str, str, int]] = [
                ("H", "H", 0),
                ("K", "H", 0),
                ("L", "H", 0),
                ("F-obs", "F", 1),
                ("SIGF-obs", "Q", 1),
                ("R-free-flags", "I", 0),
                ("FC_ALL_LS", "F", 1),
            ]
            _, multi_ds_hklout, _ = self._build_three_row_baseline_mtz_pair(
                hklout_columns=cols_multi_ds,
            )
            audit_multi_ds, _, _ = self._run_export_and_audit_pair(
                "group3_declared_obs_multi_dataset",
                hklin_bytes=hklin_bytes,
                hklout_bytes=multi_ds_hklout,
                input_ledger=input_ledger,
            )
            self.assertEqual(
                audit_multi_ds["status"], "rejected_invalid_or_inconsistent"
            )
            self.assertIs(audit_multi_ds["valid"], False)
            self.assertIn(
                "HKLOUT observation columns ('F-obs', 'SIGF-obs', 'R-free-flags') span multiple dataset IDs: ['0', '1']",
                audit_multi_ds["errors"],
            )

    def test_mtz_cell_context_representations_and_header_metadata(self) -> None:
        """Group 4 (MTZ cell/context): float32-to-4f emission match, 64.8970->64.8971 and 0.01 mismatches, and full pair DCELL/DWAV/dataset bindings."""
        with self.subTest("direct_parameter_and_tuple_representation_cases"):
            comp_f32 = onesar_refmac._compare_mtz_cell_parameter_representations(
                "10.00000001", "10.0000", parameter_name="a"
            )
            self.assertIs(comp_f32["valid"], True)
            self.assertEqual(
                comp_f32["representation_status"],
                "float32_to_4f_header_emission_match",
            )
            self.assertIs(comp_f32["exact_token_match"], False)
            self.assertIs(comp_f32["exact_decimal_match"], False)
            self.assertIs(comp_f32["float32_word_match"], True)
            self.assertEqual(
                comp_f32["input_representation"]["float32_word_hex"],
                "0x41200000",
            )
            self.assertEqual(
                comp_f32["output_representation"]["float32_word_hex"],
                "0x41200000",
            )
            self.assertEqual(
                comp_f32["input_representation"]["c_printf_4f_token"],
                "10.0000",
            )
            self.assertEqual(
                comp_f32["input_representation"]["normalized_exact_decimal"],
                "10.00000001",
            )
            self.assertEqual(
                comp_f32["output_representation"]["c_printf_4f_token"],
                "10.0000",
            )
            self.assertEqual(
                comp_f32["output_representation"]["normalized_exact_decimal"],
                "1E+1",
            )
            self.assertIs(
                comp_f32["output_matches_input_float32_4f_emission"], True
            )
            self.assertEqual(comp_f32["abs_exact_decimal_diff_str"], "0.00000001")
            self.assertIs(comp_f32["abs_exact_decimal_diff_str_available"], True)
            self.assertEqual(comp_f32["abs_exact_decimal_diff"], 1e-8)
            self.assertIs(comp_f32["abs_exact_decimal_diff_available"], True)

            comp_64 = onesar_refmac._compare_mtz_cell_parameter_representations(
                "64.8970", "64.8971", parameter_name="a"
            )
            self.assertIs(comp_64["valid"], False)
            self.assertEqual(
                comp_64["representation_status"],
                "rejected_representation_mismatch",
            )
            self.assertIs(comp_64["exact_token_match"], False)
            self.assertIs(comp_64["exact_decimal_match"], False)
            self.assertIs(
                comp_64["output_matches_input_float32_4f_emission"], False
            )
            self.assertEqual(comp_64["abs_exact_decimal_diff_str"], "0.0001")
            self.assertEqual(comp_64["abs_exact_decimal_diff"], 0.0001)
            self.assertIsInstance(comp_64["error"], str)

            for in_tok, out_tok in (("1.00", "1.01"), ("1.0000", "1.0100")):
                comp_001 = (
                    onesar_refmac._compare_mtz_cell_parameter_representations(
                        in_tok, out_tok, parameter_name="a"
                    )
                )
                self.assertIs(comp_001["valid"], False)
                self.assertEqual(
                    comp_001["representation_status"],
                    "rejected_representation_mismatch",
                )
                self.assertEqual(comp_001["abs_exact_decimal_diff_str"], "0.01")
                self.assertEqual(comp_001["abs_exact_decimal_diff"], 0.01)
                self.assertIs(
                    comp_001["abs_exact_decimal_diff_str_available"], True
                )
                self.assertIs(comp_001["abs_exact_decimal_diff_available"], True)

        with self.subTest("full_pair_float32_to_4f_emission_match_and_metadata"):
            in_cards_f32 = _build_standard_mtz_header_cards(
                cell_tokens=(
                    "10.00000001",
                    "10.0000",
                    "10.0000",
                    "90.0000",
                    "90.0000",
                    "90.0000",
                )
            )
            out_cards_f32 = _build_standard_mtz_header_cards(
                cell_tokens=(
                    "10.0000",
                    "10.0000",
                    "10.0000",
                    "90.0000",
                    "90.0000",
                    "90.0000",
                )
            )
            hklin_f32, hklout_f32, ledger_f32 = (
                self._build_three_row_baseline_mtz_pair(
                    hklin_header_cards=in_cards_f32,
                    hklout_header_cards=out_cards_f32,
                )
            )
            audit_f32, _, raw_f32 = self._run_export_and_audit_pair(
                "group4_cell_float32_to_4f_match",
                hklin_bytes=hklin_f32,
                hklout_bytes=hklout_f32,
                input_ledger=ledger_f32,
            )
            self.assertEqual(audit_f32["status"], "valid")
            self.assertIs(audit_f32["valid"], True)
            ctx_f32 = audit_f32["crystallographic_context"]
            self.assertIs(ctx_f32["exact_context_dictionary_equality"], False)
            self.assertIs(ctx_f32["exact_raw_cell_token_tuple_match"], False)
            self.assertIs(ctx_f32["exact_cell_tuple_match"], False)
            self.assertIs(ctx_f32["cell_representation_valid"], True)
            self.assertIs(ctx_f32["output_dcell_matches_output_cell"], True)
            self.assertEqual(
                ctx_f32["max_abs_cell_parameter_diff_str"], "0.00000001"
            )
            self.assertIs(
                ctx_f32["max_abs_cell_parameter_diff_str_available"], True
            )
            self.assertEqual(ctx_f32["max_abs_cell_parameter_diff"], 1e-8)
            self.assertIs(
                ctx_f32["max_abs_cell_parameter_diff_available"], True
            )

            pol_f32 = ctx_f32["cell_representation_policy"]
            self.assertIs(pol_f32["valid"], True)
            self.assertIs(pol_f32["fixed_tolerance_removed"], True)
            self.assertIs(
                pol_f32["native_crystal_or_dataset_selection_proven"], False
            )
            self.assertIs(pol_f32["executable_cmtzlib_linkage_proven"], False)
            self.assertIs(pol_f32["input_dcell_matches_input_cell"], True)
            self.assertIs(pol_f32["output_dcell_matches_output_cell"], True)
            self.assertIs(
                pol_f32["primary_cell_float32_word_tuple_match"], True
            )
            self.assertEqual(len(pol_f32["dcell_comparisons"]), 2)

            out_raw_ctx = ctx_f32["output_raw_header_context"]
            self.assertIs(out_raw_ctx["valid"], True)
            self.assertEqual(
                out_raw_ctx["dwav_records"],
                [
                    {
                        "ordinal": 0,
                        "keyword": "DWAV",
                        "dataset_setid": "0",
                        "dwav_tokens": ["0.00000"],
                        "dwavel_tokens": ["0.00000"],
                        "wavelength_present": True,
                        "raw_record": "DWAV 0 0.00000",
                    },
                    {
                        "ordinal": 1,
                        "keyword": "DWAV",
                        "dataset_setid": "1",
                        "dwav_tokens": ["1.54180"],
                        "dwavel_tokens": ["1.54180"],
                        "wavelength_present": True,
                        "raw_record": "DWAV 1 1.54180",
                    },
                ],
            )
            self.assertEqual(len(out_raw_ctx["dcell_records"]), 2)
            self.assertEqual(
                [r["dataset_setid"] for r in out_raw_ctx["dcell_records"]],
                ["0", "1"],
            )
            self.assertEqual(
                [r["dataset"] for r in out_raw_ctx["dcell_records"]],
                ["HKL_base", "dataset"],
            )
            self.assertTrue(
                all(
                    r["matches_primary_cell_exact_decimal"] is True
                    for r in out_raw_ctx["dcell_records"]
                )
            )
            for ds_map in (
                raw_f32["header_parse"]["datasets"],
                audit_f32["output_layout_summary"]["datasets"],
            ):
                self.assertEqual(set(ds_map.keys()), {"0", "1"})
                self.assertEqual(ds_map["0"]["project"], "HKL_base")
                self.assertEqual(ds_map["0"]["crystal"], "HKL_base")
                self.assertEqual(ds_map["0"]["dataset"], "HKL_base")
                self.assertEqual(ds_map["1"]["project"], "project")
                self.assertEqual(ds_map["1"]["crystal"], "crystal")
                self.assertEqual(ds_map["1"]["dataset"], "dataset")
            self.assertEqual(
                [
                    (c["label"], c["dataset_id"])
                    for c in raw_f32["header_parse"]["columns"]
                ],
                [
                    ("H", "0"),
                    ("K", "0"),
                    ("L", "0"),
                    ("F-obs", "1"),
                    ("SIGF-obs", "1"),
                    ("R-free-flags", "1"),
                    ("FC_ALL_LS", "1"),
                ],
            )

        with self.subTest("full_pair_rejected_64_8970_to_64_8971_mismatch"):
            in_cards_64 = _build_standard_mtz_header_cards(
                cell_tokens=(
                    "64.8970",
                    "10.0000",
                    "10.0000",
                    "90.0000",
                    "90.0000",
                    "90.0000",
                )
            )
            out_cards_64 = _build_standard_mtz_header_cards(
                cell_tokens=(
                    "64.8971",
                    "10.0000",
                    "10.0000",
                    "90.0000",
                    "90.0000",
                    "90.0000",
                )
            )
            hklin_64, hklout_64, ledger_64 = (
                self._build_three_row_baseline_mtz_pair(
                    hklin_header_cards=in_cards_64,
                    hklout_header_cards=out_cards_64,
                )
            )
            audit_64, _, _ = self._run_export_and_audit_pair(
                "group4_cell_64_8970_to_64_8971_rejected",
                hklin_bytes=hklin_64,
                hklout_bytes=hklout_64,
                input_ledger=ledger_64,
            )
            self.assertEqual(
                audit_64["status"], "rejected_invalid_or_inconsistent"
            )
            self.assertIs(audit_64["valid"], False)
            ctx_64 = audit_64["crystallographic_context"]
            self.assertIs(ctx_64["cell_representation_valid"], False)
            self.assertEqual(
                ctx_64["max_abs_cell_parameter_diff_str"], "0.0001"
            )
            self.assertEqual(ctx_64["max_abs_cell_parameter_diff"], 0.0001)
            pol_64 = ctx_64["cell_representation_policy"]
            self.assertIs(pol_64["valid"], False)
            self.assertIs(
                pol_64["native_crystal_or_dataset_selection_proven"], False
            )
            self.assertIs(pol_64["executable_cmtzlib_linkage_proven"], False)

    def test_mtz_malformed_headers_raw_retention_and_full_collector_promotion(
        self,
    ) -> None:
        """Group 4 (malformed MTZ headers): VALM -999, NCOL row mismatch, truncated END card raw retention + audit rejection, and full collector promotion."""
        hklin_bytes, base_hklout_bytes, input_ledger = (
            self._build_three_row_baseline_mtz_pair()
        )

        # 1. Unsupported VALM -999
        valm_bad_cards = _build_standard_mtz_header_cards(
            valm_record="VALM -999"
        )
        _, valm_bad_hklout, _ = self._build_three_row_baseline_mtz_pair(
            hklout_header_cards=valm_bad_cards
        )
        with self.subTest("unsupported_valm_minus_999"):
            audit_valm, _, raw_valm = self._run_export_and_audit_pair(
                "group4_valm_minus_999",
                hklin_bytes=hklin_bytes,
                hklout_bytes=valm_bad_hklout,
                input_ledger=input_ledger,
            )
            self.assertIsNone(raw_valm["raw_export_error"])
            self.assertEqual(raw_valm["row_count_exported"], 3)
            self.assertEqual(
                raw_valm["header_parse"]["valm_tokens"], ["-999"]
            )
            self.assertEqual(
                audit_valm["status"], "rejected_invalid_or_inconsistent"
            )
            self.assertIs(audit_valm["valid"], False)
            self.assertIn(
                "MTZ requires exactly one explicit VALM NAN record",
                str(
                    audit_valm["crystallographic_context"][
                        "output_layout_error"
                    ]
                ),
            )

        # 2. Declared NCOL row-count mismatch (nrows 3 -> 4 while data region has 3 rows = 84 bytes, header offset = 164)
        with self.subTest("declared_ncol_row_count_mismatch"):
            old_ncol_card = f"NCOL {7:8d} {3:12d} {0:8d}".ljust(80).encode(
                "ascii"
            )
            new_ncol_card = f"NCOL {7:8d} {4:12d} {0:8d}".ljust(80).encode(
                "ascii"
            )
            self.assertIn(old_ncol_card, base_hklout_bytes)
            ncol_bad_hklout = base_hklout_bytes.replace(
                old_ncol_card, new_ncol_card, 1
            )
            audit_ncol, _, raw_ncol = self._run_export_and_audit_pair(
                "group4_ncol_row_mismatch",
                hklin_bytes=hklin_bytes,
                hklout_bytes=ncol_bad_hklout,
                input_ledger=input_ledger,
            )
            self.assertIsNone(raw_ncol["raw_export_error"])
            self.assertEqual(raw_ncol["row_count_exported"], 3)
            self.assertEqual(raw_ncol["header_parse"]["nrows"], 4)
            self.assertEqual(
                raw_ncol["raw_export_warnings"],
                ["MTZ data block (80 + 112) exceeds header offset 164"],
            )
            self.assertEqual(
                audit_ncol["status"], "rejected_invalid_or_inconsistent"
            )
            self.assertIs(audit_ncol["valid"], False)
            self.assertIn(
                "MTZ table dimensions, column identities, or header offset are inconsistent",
                str(
                    audit_ncol["crystallographic_context"][
                        "output_layout_error"
                    ]
                ),
            )

        # 3. Truncated END card (drop final 1 byte of 80-byte END card -> 79-byte trailer)
        with self.subTest("truncated_end_card"):
            truncated_hklout = base_hklout_bytes[:-1]
            audit_trunc, _, raw_trunc = self._run_export_and_audit_pair(
                "group4_truncated_end_card",
                hklin_bytes=hklin_bytes,
                hklout_bytes=truncated_hklout,
                input_ledger=input_ledger,
            )
            self.assertEqual(raw_trunc["byte_length"], len(truncated_hklout))
            self.assertEqual(
                raw_trunc["sha256"], _sha256_bytes(truncated_hklout)
            )
            self.assertIsNone(raw_trunc["raw_export_error"])
            self.assertEqual(raw_trunc["row_count_exported"], 3)
            self.assertEqual(raw_trunc["trailer_byte_length"], 79)
            self.assertGreater(len(raw_trunc["primary_header_cards"]), 0)
            self.assertEqual(
                audit_trunc["status"], "rejected_invalid_or_inconsistent"
            )
            self.assertIs(audit_trunc["valid"], False)
            ctx_trunc = audit_trunc["crystallographic_context"]
            self.assertIs(
                ctx_trunc["output_raw_header_context"]["valid"], False
            )
            self.assertIn(
                "audit requires complete 80-byte MTZ header records",
                str(ctx_trunc["output_context_error"]),
            )
            self.assertIn(
                "audit requires complete 80-byte MTZ header records",
                str(ctx_trunc["output_layout_error"]),
            )

        # 4. Promote invalid MTZ (isolated VALM -999 on the staged-compatible 7248-row HKLOUT) through full run_refmac_rfactor_operation
        with self.subTest("full_collector_promotion_audit_refmac_hklout"):
            captured_patched_hklout: list[bytes] = []

            def runner(
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
                self._write_capture_success_outputs(
                    xyzin, hklin, xyzout, hklout, log_path
                )
                valid_hklout_bytes = hklout.read_bytes()
                old_valm_card = "VALM NAN".ljust(80).encode("ascii")
                new_valm_card = "VALM -999".ljust(80).encode("ascii")
                self.assertEqual(valid_hklout_bytes.count(old_valm_card), 1)
                patched_bytes = valid_hklout_bytes.replace(
                    old_valm_card, new_valm_card, 1
                )
                hklout.write_bytes(patched_bytes)
                captured_patched_hklout.append(patched_bytes)
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
                    stdout=SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG,
                    stderr="",
                )

            with self.assertRaises(onesar_refmac.RefmacCollectorError) as ctx:
                self._run_with_fake_ccp4(
                    "group4_promoted_invalid_hklout", runner
                )

            self.assertEqual(len(captured_patched_hklout), 1)
            patched_hklout_bytes = captured_patched_hklout[0]

            err = ctx.exception
            self.assertEqual(err.failed_stage, "audit_refmac_hklout")
            self.assertEqual(err.returncode, 0)
            self.assertIs(err.publication_pair_complete, True)
            self.assertIsNone(err.primary_cause)
            self.assertIsNone(err.__cause__)
            assert err.manifest_payload is not None
            assert err.diagnostics_payload is not None
            assert err.manifest_path is not None

            manifest_disk = self._reopen_and_verify_json_artifact(
                {
                    "path": str(err.manifest_path),
                    "sha256": _sha256_bytes(Path(err.manifest_path).read_bytes()),
                    "size_bytes": Path(err.manifest_path).stat().st_size,
                }
            )
            diagnostics_disk = self._reopen_and_verify_json_artifact(
                err.manifest_payload["diagnostics_json"]
            )
            post_ckpt_disk = self._reopen_and_verify_json_artifact(
                err.manifest_payload["post_execution_checkpoint_json"]
            )
            input_ledger_baseline = post_ckpt_disk["staged_inputs_baseline"][
                "input_hkl_ledger_json"
            ]
            self.assertEqual(
                manifest_disk["input_hkl_ledger_json_path"],
                input_ledger_baseline["path"],
            )
            self.assertEqual(
                manifest_disk["input_hkl_ledger_json_sha256"],
                input_ledger_baseline["sha256"],
            )
            input_ledger_disk = self._reopen_and_verify_json_artifact(
                input_ledger_baseline
            )
            raw_export_disk = self._reopen_and_verify_json_artifact(
                err.manifest_payload["hklout_raw_export_json"]
            )
            hklout_audit_disk = self._reopen_and_verify_json_artifact(
                err.manifest_payload["hklout_audit_json"]
            )

            expected_archive_row_count = input_ledger_disk["counts"]["raw_total"]
            self.assertEqual(expected_archive_row_count, 7248)

            hklout_meta = manifest_disk["raw_outputs"]["hklout"]
            self.assertEqual(
                err.manifest_payload["raw_outputs"]["hklout"], hklout_meta
            )
            hklout_disk_path = Path(str(hklout_meta["path"]))
            self.assertTrue(hklout_disk_path.exists())
            self.assertFalse(hklout_disk_path.is_symlink())
            self.assertTrue(hklout_disk_path.is_file())
            self.assertEqual(
                hklout_disk_path.read_bytes(), patched_hklout_bytes
            )
            self.assertEqual(
                hklout_meta["sha256"], _sha256_bytes(patched_hklout_bytes)
            )
            self.assertEqual(
                hklout_meta["size_bytes"], len(patched_hklout_bytes)
            )

            self.assertEqual(
                raw_export_disk["sha256"], _sha256_bytes(patched_hklout_bytes)
            )
            self.assertEqual(
                raw_export_disk["byte_length"], len(patched_hklout_bytes)
            )
            self.assertIsNone(raw_export_disk["raw_export_error"])
            self.assertEqual(
                raw_export_disk["row_count_exported"], expected_archive_row_count
            )
            self.assertEqual(
                raw_export_disk["header_parse"]["valm_tokens"], ["-999"]
            )
            self.assertIs(hklout_audit_disk["valid"], False)
            self.assertEqual(
                hklout_audit_disk["status"],
                "rejected_invalid_or_inconsistent",
            )
            ctx_disk = hklout_audit_disk["crystallographic_context"]
            self.assertIn(
                "MTZ requires exactly one explicit VALM NAN record",
                str(ctx_disk["output_layout_error"]),
            )
            self.assertIs(ctx_disk["cell_representation_valid"], True)
            self.assertIs(ctx_disk["symmetry_exact_match"], True)
            oto_disk = hklout_audit_disk["one_to_one_hkl_audit"]
            self.assertEqual(oto_disk["missing_observed_domain_hkl_keys"], [])
            self.assertEqual(oto_disk["missing_ineligible_padding_hkl_keys"], [])
            self.assertEqual(oto_disk["unexpected_extra_output_hkl_keys"], [])
            self.assertEqual(
                post_ckpt_disk["checkpoint_stage"], "post_execution"
            )
            self.assertEqual(manifest_disk["failed_stage"], "audit_refmac_hklout")
            self.assertEqual(
                manifest_disk["failures"][0]["failed_stage"],
                "audit_refmac_hklout",
            )
            self.assertIs(
                manifest_disk["operation_checks"]["hklout_audit_valid"], False
            )
            self._assert_all_scientific_admission_flags_false(manifest_disk)
            self._assert_all_scientific_admission_flags_false(diagnostics_disk)

    def test_mtz_mixed_fc_all_ls_summary_and_bounded_reso_1e400_2e400(
        self,
    ) -> None:
        """Group 2 remainder: mixed work-unavailable/free-mismatch FC_ALL_LS summary and bounded RESO 1E400 2E400 handling."""
        orig_dec_prec = decimal.getcontext().prec
        orig_int_max_str_digits = sys.get_int_max_str_digits()
        hklin_bytes, hklout_bytes, input_ledger = (
            self._build_three_row_baseline_mtz_pair()
        )

        with self.subTest("mixed_work_unavailable_and_free_mismatch_fc_all_ls"):
            # Explicit test-only supplied parsed_log Mapping (not a real REFMAC log parse):
            # r_work has 4301 decimal places (requested scale 4302 exceeds the 4096-expanded-digit optional diagnostic budget -> unavailable),
            # while r_free has 4 decimal places ("0.2000" vs candidate 1/10 = 0.1 -> outside interval).
            supplied_parsed_log: dict[str, Any] = {
                "reconciled_final_cycle": {
                    "r_work": 0.5,
                    "r_work_token": "0.5" + ("0" * 4300),
                    "r_work_decimal_places": 4301,
                    "r_free": 0.2,
                    "r_free_token": "0.2000",
                    "r_free_decimal_places": 4,
                    "nr_used_sum": 2,
                    "nr_free_sum": 1,
                    "combined_reported_count": 3,
                },
                "final_resolution_bins": {
                    "bins": [],
                    "nr_used_sum": 2,
                    "nr_free_sum": 1,
                    "combined_reported_count": 3,
                },
                "detailed_cycles": [
                    {
                        "number_of_used_reflections": 2,
                    }
                ],
            }
            audit_mix, _, _ = self._run_export_and_audit_pair(
                "group2_mixed_fc_all_ls_summary",
                hklin_bytes=hklin_bytes,
                hklout_bytes=hklout_bytes,
                input_ledger=input_ledger,
                parsed_log=supplied_parsed_log,
            )
            fc_mix = audit_mix["fc_all_ls_audit"]
            log_pop = audit_mix["populations"]["log_reported_population"]
            self.assertEqual(fc_mix["candidate_overall_r_work"], 0.5)
            self.assertEqual(fc_mix["candidate_overall_r_free"], 0.1)
            self.assertEqual(fc_mix["candidate_overall_work_count"], 2)
            self.assertEqual(fc_mix["candidate_overall_free_count"], 1)
            self.assertEqual(log_pop["final_nr_used_sum"], 2)
            self.assertEqual(log_pop["final_nr_free_sum"], 1)
            self.assertEqual(
                fc_mix["candidate_overall_work_count"],
                log_pop["final_nr_used_sum"],
            )
            self.assertEqual(
                fc_mix["candidate_overall_free_count"],
                log_pop["final_nr_free_sum"],
            )
            self.assertEqual(
                log_pop["deficit_vs_read_eligible_positive"],
                {"total_deficit": 0, "work_deficit": 0, "free_deficit": 0},
            )

            self.assertIs(
                fc_mix["candidate_overall_r_work_interval_diagnostic_available"],
                False,
            )
            self.assertIsInstance(
                fc_mix[
                    "candidate_overall_r_work_interval_diagnostic_unavailable_reason"
                ],
                str,
            )
            self.assertIn(
                "exceeds optional diagnostic resource budget (4096 expanded digits)",
                fc_mix[
                    "candidate_overall_r_work_interval_diagnostic_unavailable_reason"
                ],
            )
            self.assertIsNone(
                fc_mix[
                    "candidate_overall_r_work_within_log_reporting_interval_interior"
                ]
            )

            self.assertIs(
                fc_mix["candidate_overall_r_free_interval_diagnostic_available"],
                True,
            )
            self.assertIsNone(
                fc_mix[
                    "candidate_overall_r_free_interval_diagnostic_unavailable_reason"
                ]
            )
            self.assertIs(
                fc_mix[
                    "candidate_overall_r_free_within_log_reporting_interval_interior"
                ],
                False,
            )
            self.assertEqual(fc_mix["candidate_overall_r_work_abs_diff"], 0.0)
            self.assertEqual(fc_mix["candidate_overall_r_free_abs_diff"], 0.1)

            self.assertIs(
                audit_mix["native_residual_reconstruction_proven"], False
            )
            unproven_reason = audit_mix[
                "native_residual_reconstruction_unproven_reason"
            ]
            self.assertIn(
                "candidate unscaled FC_ALL_LS overall residuals (R_work=0.5, R_free=0.1) differ from log final_results (R_work=0.5, R_free=0.2)",
                unproven_reason,
            )
            self.assertIn(
                "candidate unscaled FC_ALL_LS overall residual log reporting interval comparison unavailable for R_work (log_rw_dec requested decimal scale (4302) exceeds optional diagnostic resource budget (4096 expanded digits))",
                unproven_reason,
            )

        with self.subTest("bounded_reso_1e400_2e400"):
            in_cards_reso = _build_standard_mtz_header_cards(
                reso_tokens=("0.01", "0.03")
            )
            out_cards_reso = _build_standard_mtz_header_cards(
                reso_tokens=("1E400", "2E400")
            )
            hklin_reso, hklout_reso, ledger_reso = (
                self._build_three_row_baseline_mtz_pair(
                    hklin_header_cards=in_cards_reso,
                    hklout_header_cards=out_cards_reso,
                )
            )
            audit_reso, _, raw_reso = self._run_export_and_audit_pair(
                "group2_bounded_reso_1e400_2e400",
                hklin_bytes=hklin_reso,
                hklout_bytes=hklout_reso,
                input_ledger=ledger_reso,
            )
            self.assertEqual(
                raw_reso["keyword_records"]["RESO"], ["RESO 1E400 2E400"]
            )
            ctx_reso = audit_reso["crystallographic_context"]
            self.assertEqual(ctx_reso["input_reso_tokens"], ["0.01", "0.03"])
            self.assertEqual(
                ctx_reso["output_reso_tokens"], ["1E400", "2E400"]
            )
            self.assertEqual(
                ctx_reso["output_raw_header_context"]["reso_raw_tokens"],
                ["1E400", "2E400"],
            )
            expected_reso_diff_str = "1" + ("9" * 400) + ".97"
            self.assertEqual(
                ctx_reso["max_abs_reso_diff_str"], expected_reso_diff_str
            )
            self.assertIs(ctx_reso["max_abs_reso_diff_str_available"], True)
            self.assertIsNone(
                ctx_reso["max_abs_reso_diff_str_unavailable_reason"]
            )
            self.assertIsNone(ctx_reso["max_abs_reso_diff"])
            self.assertIs(ctx_reso["max_abs_reso_diff_available"], False)
            self.assertIsInstance(
                ctx_reso["max_abs_reso_diff_unavailable_reason"], str
            )
            self.assertTrue(
                bool(ctx_reso["max_abs_reso_diff_unavailable_reason"].strip())
            )

            # Verify hklout_audit itself serializes cleanly under strict JSON (allow_nan=False) and re-parses without NaN/Infinity.
            serialized_audit = json.dumps(
                audit_reso, sort_keys=True, allow_nan=False
            )
            reloaded_audit = json.loads(
                serialized_audit,
                parse_constant=lambda tok: self.fail(
                    f"Unexpected non-standard JSON constant {tok!r}"
                ),
            )
            self.assertEqual(
                reloaded_audit["crystallographic_context"][
                    "max_abs_reso_diff_str"
                ],
                expected_reso_diff_str,
            )

        self.assertEqual(decimal.getcontext().prec, orig_dec_prec)
        self.assertEqual(
            sys.get_int_max_str_digits(), orig_int_max_str_digits
        )

    def _run_pdb_audit_pair(
        self,
        case_slug: str,
        *,
        xyzin_text: str,
        xyzout_text: str,
    ) -> dict[str, Any]:
        """Write literal XYZIN and XYZOUT texts to owned regular files and run _audit_refmac_xyzout."""
        case_dir = self.repo_root / "runs" / case_slug
        inputs_dir = case_dir / "inputs"
        refmac_dir = case_dir / "refmac"
        inputs_dir.mkdir(parents=True, exist_ok=True)
        refmac_dir.mkdir(parents=True, exist_ok=True)
        xyzin_path = inputs_dir / "original_model.pdb"
        xyzout_path = refmac_dir / "refmac_xyzout.pdb"
        xyzin_path.write_text(xyzin_text, encoding="utf-8")
        xyzout_path.write_text(xyzout_text, encoding="utf-8")
        xyzout_info = onesar_refmac._inspect_output_artifact(
            xyzout_path, root=refmac_dir
        )
        return onesar_refmac._audit_refmac_xyzout(
            original_pdb_path=xyzin_path,
            xyzout_path=xyzout_path,
            xyzout_info=xyzout_info,
        )

    def test_pdb_baseline_reorder_and_serial_only_distinction(self) -> None:
        """Group 4 (PDB baseline/reorder/serial): reader, adapter, supplemented inventory, unchanged baseline, reordered keys, and serial-only preservation."""
        pdb_n = (
            "ATOM      1 "
            " N  "
            " "
            "GLY"
            " A"
            "   1"
            "    "
            "   1.000"
            "   2.000"
            "   3.000"
            "  1.00"
            " 10.00"
            "          "
            " N"
        )
        pdb_ca = (
            "ATOM      2 "
            " CA "
            " "
            "GLY"
            " A"
            "   1"
            "    "
            "   4.000"
            "   5.000"
            "   6.000"
            "  0.50"
            " 20.00"
            "          "
            " C"
        )
        pdb_n_serial = (
            "ATOM      9 "
            " N  "
            " "
            "GLY"
            " A"
            "   1"
            "    "
            "   1.000"
            "   2.000"
            "   3.000"
            "  1.00"
            " 10.00"
            "          "
            " N"
        )
        base_text = pdb_n + "\n" + pdb_ca + "\nEND\n"
        expected_reader = [
            {
                "key": ("A", "1", "", "GLY", "N"),
                "element": "N",
                "xyz": [1.0, 2.0, 3.0],
                "occupancy": 1.0,
                "b_factor": 10.0,
            },
            {
                "key": ("A", "1", "", "GLY", "CA"),
                "element": "C",
                "xyz": [4.0, 5.0, 6.0],
                "occupancy": 0.5,
                "b_factor": 20.0,
            },
        ]
        k_n = ["A", 1, "", "GLY", "N", ""]
        k_ca = ["A", 1, "", "GLY", "CA", ""]
        k_n_tuple = ("A", 1, "", "GLY", "N", "")
        k_ca_tuple = ("A", 1, "", "GLY", "CA", "")

        reader_out = audit_1sar_retained_evidence.pdb_atoms(base_text)
        self.assertEqual(reader_out, expected_reader)

        adapted = onesar_refmac._adapt_pdb_atoms_records(
            reader_out, label="XYZIN"
        )
        self.assertEqual(set(adapted.keys()), {k_n_tuple, k_ca_tuple})
        self.assertEqual(
            adapted[k_n_tuple],
            {
                "order_index": 0,
                "pdb_atoms_key": ["A", "1", "", "GLY", "N"],
                "normalized_key": k_n,
                "element": "N",
                "xyz": [1.0, 2.0, 3.0],
                "occupancy": 1.0,
                "b_factor": 10.0,
            },
        )
        self.assertEqual(
            adapted[k_ca_tuple],
            {
                "order_index": 1,
                "pdb_atoms_key": ["A", "1", "", "GLY", "CA"],
                "normalized_key": k_ca,
                "element": "C",
                "xyz": [4.0, 5.0, 6.0],
                "occupancy": 0.5,
                "b_factor": 20.0,
            },
        )

        supp = onesar_refmac._inspect_pdb_supplemented(
            self.repo_root / "unused_baseline.pdb", raw_text=base_text
        )
        self.assertEqual(supp["line_count"], 3)
        self.assertEqual(supp["record_counts"], {"ATOM": 2, "END": 1})
        self.assertEqual(len(supp["heavy_atom_records"]), 2)
        self.assertEqual(supp["duplicate_heavy_keys"], [])
        self.assertEqual(supp["hd_records"], [])
        self.assertEqual(supp["anisou_records"], [])
        self.assertEqual(supp["unexpected_structural_records"], [])
        rec0 = supp["heavy_atom_records"][0]
        rec1 = supp["heavy_atom_records"][1]
        self.assertEqual(rec0["order_index"], 0)
        self.assertEqual(rec0["line_number"], 1)
        self.assertEqual(rec0["key"], k_n)
        self.assertEqual(rec0["serial_text"], "    1")
        self.assertEqual(rec0["x_text"], "   1.000")
        self.assertEqual(rec0["y_text"], "   2.000")
        self.assertEqual(rec0["z_text"], "   3.000")
        self.assertEqual(rec0["occupancy_text"], "  1.00")
        self.assertEqual(rec0["b_factor_text"], " 10.00")
        self.assertEqual(rec1["order_index"], 1)
        self.assertEqual(rec1["line_number"], 2)
        self.assertEqual(rec1["key"], k_ca)
        self.assertEqual(rec1["serial_text"], "    2")

        with self.subTest("unchanged_baseline"):
            audit_base = self._run_pdb_audit_pair(
                "group4_pdb_baseline",
                xyzin_text=base_text,
                xyzout_text=base_text,
            )
            self.assertIs(audit_base["valid"], True)
            self.assertEqual(audit_base["status"], "valid_model_preserved")
            self.assertEqual(audit_base["errors"], [])
            self.assertIs(audit_base["model_preservation_proven"], True)
            self.assertIsNone(
                audit_base["model_preservation_unproven_reason"]
            )
            self.assertIs(audit_base["byte_for_byte_identical"], True)
            for inv_key in ("xyzin_inventory", "xyzout_inventory"):
                inv = audit_base[inv_key]
                self.assertEqual(inv["line_count"], 3)
                self.assertEqual(inv["record_counts"], {"ATOM": 2, "END": 1})
                self.assertEqual(inv["heavy_atom_count"], 2)
                self.assertEqual(inv["hd_atom_count"], 0)
                self.assertEqual(inv["anisou_record_count"], 0)
                self.assertEqual(inv["hd_records"], [])
                self.assertEqual(inv["anisou_records"], [])
                self.assertEqual(inv["unexpected_structural_records"], [])
            comp = audit_base["comparison"]
            self.assertEqual(comp["added_heavy_atom_keys"], [])
            self.assertEqual(comp["removed_heavy_atom_keys"], [])
            self.assertIs(comp["key_order_preserved"], True)
            self.assertEqual(comp["reordered_heavy_atom_keys"], [])
            self.assertEqual(comp["record_type_difference_count"], 0)
            self.assertEqual(comp["record_type_differences"], [])
            self.assertEqual(comp["element_difference_count"], 0)
            self.assertEqual(comp["element_differences"], [])
            self.assertEqual(comp["coordinate_difference_count"], 0)
            self.assertEqual(comp["max_abs_coordinate_diff"], 0.0)
            self.assertEqual(comp["coordinate_differences"], [])
            self.assertEqual(comp["occupancy_difference_count"], 0)
            self.assertEqual(comp["max_abs_occupancy_diff"], 0.0)
            self.assertEqual(comp["occupancy_differences"], [])
            self.assertEqual(comp["b_factor_difference_count"], 0)
            self.assertEqual(comp["b_factor_delta_min"], 0.0)
            self.assertEqual(comp["b_factor_delta_max"], 0.0)
            self.assertEqual(comp["b_factor_delta_mean"], 0.0)
            self.assertEqual(comp["b_factor_differences"], [])
            self.assertEqual(comp["serial_or_segment_difference_count"], 0)
            self.assertEqual(comp["serial_or_segment_differences"], [])

        with self.subTest("reordered_heavy_atoms_same_coordinate_set_not_preserved"):
            reorder_text = pdb_ca + "\n" + pdb_n + "\nEND\n"
            reorder_reader = audit_1sar_retained_evidence.pdb_atoms(reorder_text)
            self.assertEqual(
                reorder_reader, [expected_reader[1], expected_reader[0]]
            )
            reorder_adapted = onesar_refmac._adapt_pdb_atoms_records(
                reorder_reader, label="XYZOUT"
            )
            self.assertEqual(reorder_adapted[k_ca_tuple]["order_index"], 0)
            self.assertEqual(reorder_adapted[k_n_tuple]["order_index"], 1)
            for k_tup in (k_n_tuple, k_ca_tuple):
                for field in ("element", "xyz", "occupancy", "b_factor"):
                    self.assertEqual(
                        reorder_adapted[k_tup][field], adapted[k_tup][field]
                    )

            audit_reorder = self._run_pdb_audit_pair(
                "group4_pdb_reordered",
                xyzin_text=base_text,
                xyzout_text=reorder_text,
            )
            self.assertIs(audit_reorder["byte_for_byte_identical"], False)
            self.assertIs(audit_reorder["valid"], True)
            self.assertEqual(
                audit_reorder["status"], "valid_with_model_differences"
            )
            self.assertEqual(audit_reorder["errors"], [])
            self.assertIs(audit_reorder["model_preservation_proven"], False)
            self.assertEqual(
                audit_reorder["model_preservation_unproven_reason"],
                "XYZOUT heavy-atom key order differs from XYZIN",
            )
            comp_r = audit_reorder["comparison"]
            self.assertEqual(comp_r["added_heavy_atom_keys"], [])
            self.assertEqual(comp_r["removed_heavy_atom_keys"], [])
            self.assertIs(comp_r["key_order_preserved"], False)
            self.assertEqual(
                comp_r["reordered_heavy_atom_keys"],
                [
                    {
                        "order_index": 0,
                        "xyzin_key": k_n,
                        "xyzout_key": k_ca,
                    },
                    {
                        "order_index": 1,
                        "xyzin_key": k_ca,
                        "xyzout_key": k_n,
                    },
                ],
            )
            self.assertEqual(comp_r["record_type_difference_count"], 0)
            self.assertEqual(comp_r["element_difference_count"], 0)
            self.assertEqual(comp_r["coordinate_difference_count"], 0)
            self.assertEqual(comp_r["max_abs_coordinate_diff"], 0.0)
            self.assertEqual(comp_r["occupancy_difference_count"], 0)
            self.assertEqual(comp_r["max_abs_occupancy_diff"], 0.0)
            self.assertEqual(comp_r["b_factor_difference_count"], 0)
            self.assertEqual(comp_r["b_factor_delta_min"], 0.0)
            self.assertEqual(comp_r["b_factor_delta_max"], 0.0)
            self.assertEqual(comp_r["b_factor_delta_mean"], 0.0)
            self.assertEqual(comp_r["serial_or_segment_difference_count"], 0)

        with self.subTest("serial_only_change_remains_preserved"):
            serial_text = pdb_n_serial + "\n" + pdb_ca + "\nEND\n"
            self.assertEqual(
                audit_1sar_retained_evidence.pdb_atoms(serial_text),
                expected_reader,
            )
            audit_serial = self._run_pdb_audit_pair(
                "group4_pdb_serial_only",
                xyzin_text=base_text,
                xyzout_text=serial_text,
            )
            self.assertIs(audit_serial["byte_for_byte_identical"], False)
            self.assertIs(audit_serial["valid"], True)
            self.assertEqual(audit_serial["status"], "valid_model_preserved")
            self.assertEqual(audit_serial["errors"], [])
            self.assertIs(audit_serial["model_preservation_proven"], True)
            self.assertIsNone(
                audit_serial["model_preservation_unproven_reason"]
            )
            comp_s = audit_serial["comparison"]
            self.assertIs(comp_s["key_order_preserved"], True)
            self.assertEqual(comp_s["reordered_heavy_atom_keys"], [])
            self.assertEqual(comp_s["record_type_difference_count"], 0)
            self.assertEqual(comp_s["element_difference_count"], 0)
            self.assertEqual(comp_s["coordinate_difference_count"], 0)
            self.assertEqual(comp_s["occupancy_difference_count"], 0)
            self.assertEqual(comp_s["b_factor_difference_count"], 0)
            self.assertEqual(comp_s["serial_or_segment_difference_count"], 1)
            self.assertEqual(
                comp_s["serial_or_segment_differences"],
                [
                    {
                        "key": k_n,
                        "xyzin_serial_text": "    1",
                        "xyzout_serial_text": "    9",
                        "xyzin_segid": "",
                        "xyzout_segid": "",
                        "xyzin_charge": "",
                        "xyzout_charge": "",
                    }
                ],
            )

    def test_pdb_coordinate_occupancy_element_b_factor_key_set_record_type_and_padding_variants(
        self,
    ) -> None:
        """Group 4 (PDB valid comparison variants): coordinate, occupancy, element, B-factor, uniform B-shift, added/removed keys, ATOM/HETATM, and atom-name padding."""
        pdb_n = (
            "ATOM      1 "
            " N  "
            " "
            "GLY"
            " A"
            "   1"
            "    "
            "   1.000"
            "   2.000"
            "   3.000"
            "  1.00"
            " 10.00"
            "          "
            " N"
        )
        pdb_ca = (
            "ATOM      2 "
            " CA "
            " "
            "GLY"
            " A"
            "   1"
            "    "
            "   4.000"
            "   5.000"
            "   6.000"
            "  0.50"
            " 20.00"
            "          "
            " C"
        )
        pdb_o = (
            "ATOM      3 "
            " O  "
            " "
            "GLY"
            " A"
            "   1"
            "    "
            "   7.000"
            "   8.000"
            "   9.000"
            "  1.00"
            " 30.00"
            "          "
            " O"
        )
        pdb_n_x = (
            "ATOM      1 "
            " N  "
            " "
            "GLY"
            " A"
            "   1"
            "    "
            "   1.250"
            "   2.000"
            "   3.000"
            "  1.00"
            " 10.00"
            "          "
            " N"
        )
        pdb_n_occ = (
            "ATOM      1 "
            " N  "
            " "
            "GLY"
            " A"
            "   1"
            "    "
            "   1.000"
            "   2.000"
            "   3.000"
            "  0.75"
            " 10.00"
            "          "
            " N"
        )
        pdb_n_element = (
            "ATOM      1 "
            " N  "
            " "
            "GLY"
            " A"
            "   1"
            "    "
            "   1.000"
            "   2.000"
            "   3.000"
            "  1.00"
            " 10.00"
            "          "
            " O"
        )
        pdb_n_b = (
            "ATOM      1 "
            " N  "
            " "
            "GLY"
            " A"
            "   1"
            "    "
            "   1.000"
            "   2.000"
            "   3.000"
            "  1.00"
            " 12.00"
            "          "
            " N"
        )
        pdb_n_b_shift = (
            "ATOM      1 "
            " N  "
            " "
            "GLY"
            " A"
            "   1"
            "    "
            "   1.000"
            "   2.000"
            "   3.000"
            "  1.00"
            " 15.00"
            "          "
            " N"
        )
        pdb_ca_b_shift = (
            "ATOM      2 "
            " CA "
            " "
            "GLY"
            " A"
            "   1"
            "    "
            "   4.000"
            "   5.000"
            "   6.000"
            "  0.50"
            " 25.00"
            "          "
            " C"
        )
        pdb_n_hetatm = (
            "HETATM    1 "
            " N  "
            " "
            "GLY"
            " A"
            "   1"
            "    "
            "   1.000"
            "   2.000"
            "   3.000"
            "  1.00"
            " 10.00"
            "          "
            " N"
        )
        pdb_n_padding = (
            "ATOM      1 "
            "N   "
            " "
            "GLY"
            " A"
            "   1"
            "    "
            "   1.000"
            "   2.000"
            "   3.000"
            "  1.00"
            " 10.00"
            "          "
            " N"
        )
        base_text = pdb_n + "\n" + pdb_ca + "\nEND\n"
        expected_reader = [
            {
                "key": ("A", "1", "", "GLY", "N"),
                "element": "N",
                "xyz": [1.0, 2.0, 3.0],
                "occupancy": 1.0,
                "b_factor": 10.0,
            },
            {
                "key": ("A", "1", "", "GLY", "CA"),
                "element": "C",
                "xyz": [4.0, 5.0, 6.0],
                "occupancy": 0.5,
                "b_factor": 20.0,
            },
        ]
        k_n = ["A", 1, "", "GLY", "N", ""]
        k_ca = ["A", 1, "", "GLY", "CA", ""]
        k_o = ["A", 1, "", "GLY", "O", ""]

        with self.subTest("coordinate_change"):
            audit = self._run_pdb_audit_pair(
                "group4_pdb_coord_change",
                xyzin_text=base_text,
                xyzout_text=pdb_n_x + "\n" + pdb_ca + "\nEND\n",
            )
            self.assertIs(audit["byte_for_byte_identical"], False)
            self.assertIs(audit["valid"], True)
            self.assertEqual(audit["errors"], [])
            self.assertEqual(audit["status"], "valid_with_model_differences")
            self.assertIs(audit["model_preservation_proven"], False)
            self.assertEqual(
                audit["model_preservation_unproven_reason"],
                "XYZOUT modified coordinates or coordinate text on 1 heavy atom(s) (max_abs_diff=0.250000)",
            )
            comp = audit["comparison"]
            self.assertEqual(comp["added_heavy_atom_keys"], [])
            self.assertEqual(comp["removed_heavy_atom_keys"], [])
            self.assertIs(comp["key_order_preserved"], True)
            self.assertEqual(comp["coordinate_difference_count"], 1)
            self.assertEqual(comp["max_abs_coordinate_diff"], 0.25)
            self.assertEqual(
                comp["coordinate_differences"],
                [
                    {
                        "key": k_n,
                        "xyzin_xyz": [1.0, 2.0, 3.0],
                        "xyzout_xyz": [1.25, 2.0, 3.0],
                        "xyzin_xyz_text": ["   1.000", "   2.000", "   3.000"],
                        "xyzout_xyz_text": ["   1.250", "   2.000", "   3.000"],
                        "max_abs_diff": 0.25,
                    }
                ],
            )
            self.assertEqual(comp["record_type_difference_count"], 0)
            self.assertEqual(comp["element_difference_count"], 0)
            self.assertEqual(comp["occupancy_difference_count"], 0)
            self.assertEqual(comp["b_factor_difference_count"], 0)
            self.assertEqual(comp["b_factor_delta_min"], 0.0)
            self.assertEqual(comp["b_factor_delta_max"], 0.0)
            self.assertEqual(comp["b_factor_delta_mean"], 0.0)
            self.assertEqual(comp["serial_or_segment_difference_count"], 0)

        with self.subTest("occupancy_change"):
            audit = self._run_pdb_audit_pair(
                "group4_pdb_occ_change",
                xyzin_text=base_text,
                xyzout_text=pdb_n_occ + "\n" + pdb_ca + "\nEND\n",
            )
            self.assertIs(audit["byte_for_byte_identical"], False)
            self.assertIs(audit["valid"], True)
            self.assertEqual(audit["errors"], [])
            self.assertEqual(audit["status"], "valid_with_model_differences")
            self.assertIs(audit["model_preservation_proven"], False)
            self.assertEqual(
                audit["model_preservation_unproven_reason"],
                "XYZOUT modified occupancy or occupancy text on 1 heavy atom(s) (max_abs_diff=0.250000)",
            )
            comp = audit["comparison"]
            self.assertEqual(comp["occupancy_difference_count"], 1)
            self.assertEqual(comp["max_abs_occupancy_diff"], 0.25)
            self.assertEqual(
                comp["occupancy_differences"],
                [
                    {
                        "key": k_n,
                        "xyzin_occupancy": 1.0,
                        "xyzout_occupancy": 0.75,
                        "xyzin_occupancy_text": "  1.00",
                        "xyzout_occupancy_text": "  0.75",
                        "abs_diff": 0.25,
                    }
                ],
            )
            self.assertEqual(comp["record_type_difference_count"], 0)
            self.assertEqual(comp["element_difference_count"], 0)
            self.assertEqual(comp["coordinate_difference_count"], 0)
            self.assertEqual(comp["b_factor_difference_count"], 0)
            self.assertEqual(comp["serial_or_segment_difference_count"], 0)

        with self.subTest("element_change"):
            audit = self._run_pdb_audit_pair(
                "group4_pdb_elem_change",
                xyzin_text=base_text,
                xyzout_text=pdb_n_element + "\n" + pdb_ca + "\nEND\n",
            )
            self.assertIs(audit["byte_for_byte_identical"], False)
            self.assertIs(audit["valid"], True)
            self.assertEqual(audit["errors"], [])
            self.assertEqual(audit["status"], "valid_with_model_differences")
            self.assertIs(audit["model_preservation_proven"], False)
            self.assertEqual(
                audit["model_preservation_unproven_reason"],
                "XYZOUT changed element symbol on 1 heavy atom(s)",
            )
            comp = audit["comparison"]
            self.assertEqual(comp["element_difference_count"], 1)
            self.assertEqual(
                comp["element_differences"],
                [{"key": k_n, "xyzin_element": "N", "xyzout_element": "O"}],
            )
            self.assertEqual(comp["record_type_difference_count"], 0)
            self.assertEqual(comp["coordinate_difference_count"], 0)
            self.assertEqual(comp["occupancy_difference_count"], 0)
            self.assertEqual(comp["b_factor_difference_count"], 0)
            self.assertEqual(comp["serial_or_segment_difference_count"], 0)

        with self.subTest("single_b_factor_change"):
            audit = self._run_pdb_audit_pair(
                "group4_pdb_single_b_change",
                xyzin_text=base_text,
                xyzout_text=pdb_n_b + "\n" + pdb_ca + "\nEND\n",
            )
            self.assertIs(audit["byte_for_byte_identical"], False)
            self.assertIs(audit["valid"], True)
            self.assertEqual(audit["errors"], [])
            self.assertEqual(audit["status"], "valid_with_model_differences")
            self.assertIs(audit["model_preservation_proven"], False)
            self.assertEqual(
                audit["model_preservation_unproven_reason"],
                "XYZOUT modified B-factor or B-factor text on 1/2 heavy atom(s) (delta_b range [0.0000, 2.0000]; no blanket B-shift license)",
            )
            comp = audit["comparison"]
            self.assertEqual(comp["b_factor_difference_count"], 1)
            self.assertEqual(comp["b_factor_delta_min"], 0.0)
            self.assertEqual(comp["b_factor_delta_max"], 2.0)
            self.assertEqual(comp["b_factor_delta_mean"], 1.0)
            self.assertEqual(
                comp["b_factor_differences"],
                [
                    {
                        "key": k_n,
                        "xyzin_b_factor": 10.0,
                        "xyzout_b_factor": 12.0,
                        "xyzin_b_factor_text": " 10.00",
                        "xyzout_b_factor_text": " 12.00",
                        "delta_b": 2.0,
                    }
                ],
            )
            self.assertEqual(comp["record_type_difference_count"], 0)
            self.assertEqual(comp["element_difference_count"], 0)
            self.assertEqual(comp["coordinate_difference_count"], 0)
            self.assertEqual(comp["occupancy_difference_count"], 0)
            self.assertEqual(comp["serial_or_segment_difference_count"], 0)

        with self.subTest("uniform_b_factor_shift"):
            audit = self._run_pdb_audit_pair(
                "group4_pdb_uniform_b_shift",
                xyzin_text=base_text,
                xyzout_text=pdb_n_b_shift + "\n" + pdb_ca_b_shift + "\nEND\n",
            )
            self.assertIs(audit["byte_for_byte_identical"], False)
            self.assertIs(audit["valid"], True)
            self.assertEqual(audit["errors"], [])
            self.assertEqual(audit["status"], "valid_with_model_differences")
            self.assertIs(audit["model_preservation_proven"], False)
            self.assertEqual(
                audit["model_preservation_unproven_reason"],
                "XYZOUT modified B-factor or B-factor text on 2/2 heavy atom(s) (delta_b range [5.0000, 5.0000]; no blanket B-shift license)",
            )
            comp = audit["comparison"]
            self.assertEqual(comp["b_factor_difference_count"], 2)
            self.assertEqual(comp["b_factor_delta_min"], 5.0)
            self.assertEqual(comp["b_factor_delta_max"], 5.0)
            self.assertEqual(comp["b_factor_delta_mean"], 5.0)
            self.assertEqual(
                comp["b_factor_differences"],
                [
                    {
                        "key": k_n,
                        "xyzin_b_factor": 10.0,
                        "xyzout_b_factor": 15.0,
                        "xyzin_b_factor_text": " 10.00",
                        "xyzout_b_factor_text": " 15.00",
                        "delta_b": 5.0,
                    },
                    {
                        "key": k_ca,
                        "xyzin_b_factor": 20.0,
                        "xyzout_b_factor": 25.0,
                        "xyzin_b_factor_text": " 20.00",
                        "xyzout_b_factor_text": " 25.00",
                        "delta_b": 5.0,
                    },
                ],
            )

        with self.subTest("added_heavy_atom_key"):
            audit = self._run_pdb_audit_pair(
                "group4_pdb_added_key",
                xyzin_text=base_text,
                xyzout_text=pdb_n + "\n" + pdb_ca + "\n" + pdb_o + "\nEND\n",
            )
            self.assertIs(audit["byte_for_byte_identical"], False)
            self.assertIs(audit["valid"], True)
            self.assertEqual(audit["errors"], [])
            self.assertEqual(audit["status"], "valid_with_model_differences")
            self.assertIs(audit["model_preservation_proven"], False)
            self.assertEqual(
                audit["model_preservation_unproven_reason"],
                "XYZOUT added 1 heavy-atom key(s); XYZOUT heavy-atom key order differs from XYZIN",
            )
            self.assertEqual(audit["xyzout_inventory"]["heavy_atom_count"], 3)
            comp = audit["comparison"]
            self.assertEqual(comp["added_heavy_atom_keys"], [k_o])
            self.assertEqual(comp["removed_heavy_atom_keys"], [])
            self.assertIs(comp["key_order_preserved"], False)
            self.assertEqual(comp["reordered_heavy_atom_keys"], [])
            self.assertEqual(comp["record_type_difference_count"], 0)
            self.assertEqual(comp["element_difference_count"], 0)
            self.assertEqual(comp["coordinate_difference_count"], 0)
            self.assertEqual(comp["occupancy_difference_count"], 0)
            self.assertEqual(comp["b_factor_difference_count"], 0)
            self.assertEqual(comp["serial_or_segment_difference_count"], 0)

        with self.subTest("removed_heavy_atom_key"):
            audit = self._run_pdb_audit_pair(
                "group4_pdb_removed_key",
                xyzin_text=base_text,
                xyzout_text=pdb_n + "\nEND\n",
            )
            self.assertIs(audit["byte_for_byte_identical"], False)
            self.assertIs(audit["valid"], True)
            self.assertEqual(audit["errors"], [])
            self.assertEqual(audit["status"], "valid_with_model_differences")
            self.assertIs(audit["model_preservation_proven"], False)
            self.assertEqual(
                audit["model_preservation_unproven_reason"],
                "XYZOUT removed 1 heavy-atom key(s); XYZOUT heavy-atom key order differs from XYZIN",
            )
            self.assertEqual(audit["xyzout_inventory"]["heavy_atom_count"], 1)
            comp = audit["comparison"]
            self.assertEqual(comp["added_heavy_atom_keys"], [])
            self.assertEqual(comp["removed_heavy_atom_keys"], [k_ca])
            self.assertIs(comp["key_order_preserved"], False)
            self.assertEqual(comp["reordered_heavy_atom_keys"], [])
            self.assertEqual(comp["record_type_difference_count"], 0)
            self.assertEqual(comp["element_difference_count"], 0)
            self.assertEqual(comp["coordinate_difference_count"], 0)
            self.assertEqual(comp["occupancy_difference_count"], 0)
            self.assertEqual(comp["b_factor_difference_count"], 0)
            self.assertEqual(comp["b_factor_delta_min"], 0.0)
            self.assertEqual(comp["b_factor_delta_max"], 0.0)
            self.assertEqual(comp["b_factor_delta_mean"], 0.0)
            self.assertEqual(comp["serial_or_segment_difference_count"], 0)

        with self.subTest("record_type_atom_to_hetatm"):
            hetatm_text = pdb_n_hetatm + "\n" + pdb_ca + "\nEND\n"
            self.assertEqual(
                audit_1sar_retained_evidence.pdb_atoms(hetatm_text),
                expected_reader,
            )
            audit = self._run_pdb_audit_pair(
                "group4_pdb_hetatm",
                xyzin_text=base_text,
                xyzout_text=hetatm_text,
            )
            self.assertIs(audit["byte_for_byte_identical"], False)
            self.assertIs(audit["valid"], True)
            self.assertEqual(audit["errors"], [])
            self.assertEqual(audit["status"], "valid_with_model_differences")
            self.assertIs(audit["model_preservation_proven"], False)
            self.assertEqual(
                audit["model_preservation_unproven_reason"],
                "XYZOUT changed record_type (ATOM/HETATM) on 1 heavy atom(s)",
            )
            self.assertEqual(
                audit["xyzout_inventory"]["record_counts"],
                {"HETATM": 1, "ATOM": 1, "END": 1},
            )
            comp = audit["comparison"]
            self.assertEqual(comp["record_type_difference_count"], 1)
            self.assertEqual(
                comp["record_type_differences"],
                [
                    {
                        "key": k_n,
                        "xyzin_record_type": "ATOM",
                        "xyzout_record_type": "HETATM",
                    }
                ],
            )
            self.assertEqual(comp["element_difference_count"], 0)
            self.assertEqual(comp["coordinate_difference_count"], 0)
            self.assertEqual(comp["occupancy_difference_count"], 0)
            self.assertEqual(comp["b_factor_difference_count"], 0)
            self.assertEqual(comp["serial_or_segment_difference_count"], 0)

        with self.subTest("atom_name_padding_preserved"):
            padding_text = pdb_n_padding + "\n" + pdb_ca + "\nEND\n"
            self.assertEqual(
                audit_1sar_retained_evidence.pdb_atoms(padding_text),
                expected_reader,
            )
            audit = self._run_pdb_audit_pair(
                "group4_pdb_name_padding",
                xyzin_text=base_text,
                xyzout_text=padding_text,
            )
            self.assertIs(audit["byte_for_byte_identical"], False)
            self.assertIs(audit["valid"], True)
            self.assertEqual(audit["errors"], [])
            self.assertEqual(audit["status"], "valid_model_preserved")
            self.assertIs(audit["model_preservation_proven"], True)
            self.assertIsNone(audit["model_preservation_unproven_reason"])
            comp = audit["comparison"]
            self.assertEqual(comp["added_heavy_atom_keys"], [])
            self.assertEqual(comp["removed_heavy_atom_keys"], [])
            self.assertIs(comp["key_order_preserved"], True)
            self.assertEqual(comp["record_type_difference_count"], 0)
            self.assertEqual(comp["element_difference_count"], 0)
            self.assertEqual(comp["coordinate_difference_count"], 0)
            self.assertEqual(comp["occupancy_difference_count"], 0)
            self.assertEqual(comp["b_factor_difference_count"], 0)
            self.assertEqual(comp["serial_or_segment_difference_count"], 0)

    def test_pdb_hd_anisou_model_altloc_numeric_representation_and_full_collector_promotion(
        self,
    ) -> None:
        """Group 4 (PDB evidence/representation boundaries + promotion): H/D, ANISOU, MODEL/ENDMDL, altloc, NaN, numeric text, and full operation promotion."""
        pdb_n = (
            "ATOM      1 "
            " N  "
            " "
            "GLY"
            " A"
            "   1"
            "    "
            "   1.000"
            "   2.000"
            "   3.000"
            "  1.00"
            " 10.00"
            "          "
            " N"
        )
        pdb_ca = (
            "ATOM      2 "
            " CA "
            " "
            "GLY"
            " A"
            "   1"
            "    "
            "   4.000"
            "   5.000"
            "   6.000"
            "  0.50"
            " 20.00"
            "          "
            " C"
        )
        pdb_n_x_text = (
            "ATOM      1 "
            " N  "
            " "
            "GLY"
            " A"
            "   1"
            "    "
            "  1.0000"
            "   2.000"
            "   3.000"
            "  1.00"
            " 10.00"
            "          "
            " N"
        )
        pdb_n_altloc = (
            "ATOM      1 "
            " N  "
            "A"
            "GLY"
            " A"
            "   1"
            "    "
            "   1.000"
            "   2.000"
            "   3.000"
            "  1.00"
            " 10.00"
            "          "
            " N"
        )
        pdb_n_nan = (
            "ATOM      1 "
            " N  "
            " "
            "GLY"
            " A"
            "   1"
            "    "
            "     nan"
            "   2.000"
            "   3.000"
            "  1.00"
            " 10.00"
            "          "
            " N"
        )
        pdb_h = (
            "ATOM      4 "
            " H  "
            " "
            "GLY"
            " A"
            "   1"
            "    "
            "   1.000"
            "   2.000"
            "   4.000"
            "  1.00"
            " 10.00"
            "          "
            " H"
        )
        pdb_d = (
            "ATOM      5 "
            " D  "
            " "
            "GLY"
            " A"
            "   1"
            "    "
            "   1.000"
            "   2.000"
            "   5.000"
            "  1.00"
            " 10.00"
            "          "
            " D"
        )
        pdb_anisou_n = (
            "ANISOU    1 "
            " N  "
            " "
            "GLY"
            " A"
            "   1"
            "  "
            "   1000"
            "   1100"
            "   1200"
            "    100"
            "    200"
            "    300"
            "      "
            " N"
        )
        base_text = pdb_n + "\n" + pdb_ca + "\nEND\n"
        expected_reader = [
            {
                "key": ("A", "1", "", "GLY", "N"),
                "element": "N",
                "xyz": [1.0, 2.0, 3.0],
                "occupancy": 1.0,
                "b_factor": 10.0,
            },
            {
                "key": ("A", "1", "", "GLY", "CA"),
                "element": "C",
                "xyz": [4.0, 5.0, 6.0],
                "occupancy": 0.5,
                "b_factor": 20.0,
            },
        ]
        k_n = ["A", 1, "", "GLY", "N", ""]

        with self.subTest("hd_records_retained_and_limit_preservation"):
            hd_text = (
                pdb_n + "\n" + pdb_ca + "\n" + pdb_h + "\n" + pdb_d + "\nEND\n"
            )
            self.assertEqual(
                audit_1sar_retained_evidence.pdb_atoms(hd_text), expected_reader
            )
            audit_hd = self._run_pdb_audit_pair(
                "group4_pdb_hd_records",
                xyzin_text=hd_text,
                xyzout_text=hd_text,
            )
            self.assertIs(audit_hd["byte_for_byte_identical"], True)
            self.assertIs(audit_hd["valid"], True)
            self.assertEqual(audit_hd["errors"], [])
            self.assertEqual(audit_hd["status"], "valid_with_model_differences")
            self.assertIs(audit_hd["model_preservation_proven"], False)
            self.assertEqual(
                audit_hd["model_preservation_unproven_reason"],
                "H/D records present (XYZIN=2, XYZOUT=2)",
            )
            expected_hd_records = [
                {
                    "line_number": 3,
                    "record_type": "ATOM",
                    "serial_text": "    4",
                    "chain_id": "A",
                    "resseq_text": "   1",
                    "icode": "",
                    "resname": "GLY",
                    "atom_name": "H",
                    "altloc": "",
                    "element": "H",
                    "x_text": "   1.000",
                    "y_text": "   2.000",
                    "z_text": "   4.000",
                    "occupancy_text": "  1.00",
                    "b_factor_text": " 10.00",
                    "raw_line": pdb_h,
                },
                {
                    "line_number": 4,
                    "record_type": "ATOM",
                    "serial_text": "    5",
                    "chain_id": "A",
                    "resseq_text": "   1",
                    "icode": "",
                    "resname": "GLY",
                    "atom_name": "D",
                    "altloc": "",
                    "element": "D",
                    "x_text": "   1.000",
                    "y_text": "   2.000",
                    "z_text": "   5.000",
                    "occupancy_text": "  1.00",
                    "b_factor_text": " 10.00",
                    "raw_line": pdb_d,
                },
            ]
            for inv_key in ("xyzin_inventory", "xyzout_inventory"):
                inv = audit_hd[inv_key]
                self.assertEqual(inv["line_count"], 5)
                self.assertEqual(inv["record_counts"], {"ATOM": 4, "END": 1})
                self.assertEqual(inv["heavy_atom_count"], 2)
                self.assertEqual(inv["hd_atom_count"], 2)
                self.assertEqual(inv["hd_records"], expected_hd_records)

        with self.subTest("anisou_records_retained_and_limit_preservation"):
            anisou_text = (
                pdb_n + "\n" + pdb_ca + "\n" + pdb_anisou_n + "\nEND\n"
            )
            self.assertEqual(
                audit_1sar_retained_evidence.pdb_atoms(anisou_text),
                expected_reader,
            )
            audit_ani = self._run_pdb_audit_pair(
                "group4_pdb_anisou_records",
                xyzin_text=anisou_text,
                xyzout_text=anisou_text,
            )
            self.assertIs(audit_ani["byte_for_byte_identical"], True)
            self.assertIs(audit_ani["valid"], True)
            self.assertEqual(audit_ani["errors"], [])
            self.assertEqual(
                audit_ani["status"], "valid_with_model_differences"
            )
            self.assertIs(audit_ani["model_preservation_proven"], False)
            self.assertEqual(
                audit_ani["model_preservation_unproven_reason"],
                "ANISOU records present (XYZIN=1, XYZOUT=1); mixed/anisotropic ADP proof is unsupported",
            )
            expected_anisou_records = [
                {
                    "line_number": 3,
                    "serial_text": "    1",
                    "chain_id": "A",
                    "resseq_text": "1",
                    "icode": "",
                    "resname": "GLY",
                    "atom_name": "N",
                    "altloc": "",
                    "element": "N",
                    "u_ij_texts": [
                        "   1000",
                        "   1100",
                        "   1200",
                        "    100",
                        "    200",
                        "    300",
                    ],
                    "raw_line": pdb_anisou_n,
                }
            ]
            for inv_key in ("xyzin_inventory", "xyzout_inventory"):
                inv = audit_ani[inv_key]
                self.assertEqual(inv["line_count"], 4)
                self.assertEqual(
                    inv["record_counts"], {"ATOM": 2, "ANISOU": 1, "END": 1}
                )
                self.assertEqual(inv["heavy_atom_count"], 2)
                self.assertEqual(inv["anisou_record_count"], 1)
                self.assertEqual(inv["anisou_records"], expected_anisou_records)

        with self.subTest("malformed_model_rejected"):
            model_text = "MODEL        1\n" + base_text
            with self.assertRaisesRegex(
                ValueError, "audit requires an implicit single PDB model"
            ):
                audit_1sar_retained_evidence.pdb_atoms(model_text)
            audit_model = self._run_pdb_audit_pair(
                "group4_pdb_malformed_model",
                xyzin_text=base_text,
                xyzout_text=model_text,
            )
            self.assertEqual(
                audit_model["status"], "rejected_invalid_or_unreadable"
            )
            self.assertIs(audit_model["valid"], False)
            self.assertIs(audit_model["model_preservation_proven"], False)
            expected_model_err = "XYZOUT failed pdb_atoms helper: ValueError: audit requires an implicit single PDB model"
            self.assertEqual(audit_model["errors"], [expected_model_err])
            self.assertEqual(
                audit_model["model_preservation_unproven_reason"],
                expected_model_err,
            )
            self.assertNotIn("comparison", audit_model)
            self.assertNotIn("xyzout_inventory", audit_model)

        with self.subTest("orphan_endmdl_retained_and_limits_preservation"):
            endmdl_text = pdb_n + "\n" + pdb_ca + "\nENDMDL\nEND\n"
            self.assertEqual(
                audit_1sar_retained_evidence.pdb_atoms(endmdl_text),
                expected_reader,
            )
            audit_endmdl = self._run_pdb_audit_pair(
                "group4_pdb_orphan_endmdl",
                xyzin_text=base_text,
                xyzout_text=endmdl_text,
            )
            self.assertIs(audit_endmdl["valid"], True)
            self.assertEqual(audit_endmdl["errors"], [])
            self.assertEqual(
                audit_endmdl["status"], "valid_with_model_differences"
            )
            self.assertIs(audit_endmdl["model_preservation_proven"], False)
            self.assertEqual(
                audit_endmdl["model_preservation_unproven_reason"],
                "Unexpected MODEL/ENDMDL structural records present",
            )
            self.assertEqual(
                audit_endmdl["xyzout_inventory"][
                    "unexpected_structural_records"
                ],
                [
                    {
                        "line_number": 3,
                        "record": "ENDMDL",
                        "raw_line": "ENDMDL",
                    }
                ],
            )

        with self.subTest("altloc_rejected"):
            altloc_text = pdb_n_altloc + "\n" + pdb_ca + "\nEND\n"
            with self.assertRaisesRegex(
                ValueError,
                "audit requires complete fixed-column atoms without altlocs",
            ):
                audit_1sar_retained_evidence.pdb_atoms(altloc_text)
            audit_altloc = self._run_pdb_audit_pair(
                "group4_pdb_altloc",
                xyzin_text=base_text,
                xyzout_text=altloc_text,
            )
            self.assertEqual(
                audit_altloc["status"], "rejected_invalid_or_unreadable"
            )
            self.assertIs(audit_altloc["valid"], False)
            self.assertIs(audit_altloc["model_preservation_proven"], False)
            expected_altloc_err = "XYZOUT failed pdb_atoms helper: ValueError: audit requires complete fixed-column atoms without altlocs"
            self.assertEqual(audit_altloc["errors"], [expected_altloc_err])
            self.assertEqual(
                audit_altloc["model_preservation_unproven_reason"],
                expected_altloc_err,
            )
            self.assertNotIn("comparison", audit_altloc)

        with self.subTest("nonfinite_nan_rejected"):
            nan_text = pdb_n_nan + "\n" + pdb_ca + "\nEND\n"
            with self.assertRaisesRegex(
                ValueError, "nonfinite coordinate, occupancy or B factor"
            ):
                audit_1sar_retained_evidence.pdb_atoms(nan_text)
            audit_nan = self._run_pdb_audit_pair(
                "group4_pdb_nan",
                xyzin_text=base_text,
                xyzout_text=nan_text,
            )
            self.assertEqual(
                audit_nan["status"], "rejected_invalid_or_unreadable"
            )
            self.assertIs(audit_nan["valid"], False)
            self.assertIs(audit_nan["model_preservation_proven"], False)
            expected_nan_err = "XYZOUT failed pdb_atoms helper: ValueError: nonfinite coordinate, occupancy or B factor"
            self.assertEqual(audit_nan["errors"], [expected_nan_err])
            self.assertEqual(
                audit_nan["model_preservation_unproven_reason"],
                expected_nan_err,
            )
            self.assertNotIn("comparison", audit_nan)

        with self.subTest("equal_value_changed_numeric_text_limits_preservation"):
            x_text_out = pdb_n_x_text + "\n" + pdb_ca + "\nEND\n"
            self.assertEqual(
                audit_1sar_retained_evidence.pdb_atoms(x_text_out),
                expected_reader,
            )
            audit_xtext = self._run_pdb_audit_pair(
                "group4_pdb_numeric_text_change",
                xyzin_text=base_text,
                xyzout_text=x_text_out,
            )
            self.assertIs(audit_xtext["byte_for_byte_identical"], False)
            self.assertIs(audit_xtext["valid"], True)
            self.assertEqual(audit_xtext["errors"], [])
            self.assertEqual(
                audit_xtext["status"], "valid_with_model_differences"
            )
            self.assertIs(audit_xtext["model_preservation_proven"], False)
            self.assertEqual(
                audit_xtext["model_preservation_unproven_reason"],
                "XYZOUT modified coordinates or coordinate text on 1 heavy atom(s) (max_abs_diff=0.000000)",
            )
            comp_xt = audit_xtext["comparison"]
            self.assertEqual(comp_xt["coordinate_difference_count"], 1)
            self.assertEqual(comp_xt["max_abs_coordinate_diff"], 0.0)
            self.assertEqual(
                comp_xt["coordinate_differences"],
                [
                    {
                        "key": k_n,
                        "xyzin_xyz": [1.0, 2.0, 3.0],
                        "xyzout_xyz": [1.0, 2.0, 3.0],
                        "xyzin_xyz_text": ["   1.000", "   2.000", "   3.000"],
                        "xyzout_xyz_text": ["  1.0000", "   2.000", "   3.000"],
                        "max_abs_diff": 0.0,
                    }
                ],
            )

        with self.subTest("full_collector_promotion_audit_refmac_xyzout"):
            nan_xyzout_bytes = (pdb_n_nan + "\n" + pdb_ca + "\nEND\n").encode(
                "utf-8"
            )

            def runner(
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
                self._write_capture_success_outputs(
                    xyzin, hklin, xyzout, hklout, log_path
                )
                xyzout.write_bytes(nan_xyzout_bytes)
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
                    stdout=SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG,
                    stderr="",
                )

            with self.assertRaises(onesar_refmac.RefmacCollectorError) as ctx:
                self._run_with_fake_ccp4(
                    "group4_promoted_invalid_xyzout", runner
                )

            err = ctx.exception
            self.assertEqual(err.failed_stage, "audit_refmac_xyzout")
            self.assertEqual(err.returncode, 0)
            self.assertIs(err.publication_pair_complete, True)
            self.assertIsNone(err.primary_cause)
            self.assertIsNone(err.__cause__)
            assert err.manifest_payload is not None
            assert err.diagnostics_payload is not None
            assert err.manifest_path is not None

            manifest_disk = self._reopen_and_verify_json_artifact(
                {
                    "path": str(err.manifest_path),
                    "sha256": _sha256_bytes(Path(err.manifest_path).read_bytes()),
                    "size_bytes": Path(err.manifest_path).stat().st_size,
                }
            )
            diagnostics_disk = self._reopen_and_verify_json_artifact(
                err.manifest_payload["diagnostics_json"]
            )
            post_ckpt_disk = self._reopen_and_verify_json_artifact(
                err.manifest_payload["post_execution_checkpoint_json"]
            )
            xyzout_audit_disk = self._reopen_and_verify_json_artifact(
                err.manifest_payload["xyzout_audit_json"]
            )
            hklout_audit_disk = self._reopen_and_verify_json_artifact(
                err.manifest_payload["hklout_audit_json"]
            )
            xmlout_audit_disk = self._reopen_and_verify_json_artifact(
                err.manifest_payload["xmlout_audit_json"]
            )

            self.assertEqual(manifest_disk, err.manifest_payload)
            self.assertEqual(
                post_ckpt_disk["checkpoint_stage"], "post_execution"
            )
            self.assertEqual(
                post_ckpt_disk["status"], "post_execution_checkpointed"
            )
            self.assertIsNone(post_ckpt_disk["failed_stage"])
            self.assertEqual(post_ckpt_disk["failures"], [])

            xyzout_meta = diagnostics_disk["raw_outputs"]["xyzout"]
            self.assertEqual(
                manifest_disk["raw_outputs"]["xyzout"], xyzout_meta
            )
            xyzout_disk_path = Path(str(xyzout_meta["path"]))
            self.assertTrue(xyzout_disk_path.exists())
            self.assertFalse(xyzout_disk_path.is_symlink())
            self.assertTrue(xyzout_disk_path.is_file())
            self.assertEqual(xyzout_disk_path.read_bytes(), nan_xyzout_bytes)
            expected_nan_sha256 = _sha256_bytes(nan_xyzout_bytes)
            expected_nan_size = len(nan_xyzout_bytes)
            self.assertEqual(xyzout_meta["sha256"], expected_nan_sha256)
            self.assertEqual(xyzout_meta["size_bytes"], expected_nan_size)

            expected_nan_err = "XYZOUT failed pdb_atoms helper: ValueError: nonfinite coordinate, occupancy or B factor"
            self.assertEqual(
                xyzout_audit_disk["xyzout_sha256"], expected_nan_sha256
            )
            self.assertEqual(
                xyzout_audit_disk["xyzout_size_bytes"], expected_nan_size
            )
            self.assertEqual(
                xyzout_audit_disk["status"], "rejected_invalid_or_unreadable"
            )
            self.assertIs(xyzout_audit_disk["valid"], False)
            self.assertEqual(xyzout_audit_disk["errors"], [expected_nan_err])
            self.assertIs(
                xyzout_audit_disk["model_preservation_proven"], False
            )
            self.assertEqual(
                xyzout_audit_disk["model_preservation_unproven_reason"],
                expected_nan_err,
            )

            self.assertIs(hklout_audit_disk["valid"], True)
            self.assertIs(xmlout_audit_disk["valid"], True)
            self.assertEqual(xmlout_audit_disk["status"], "absent")

            for doc in (manifest_disk, diagnostics_disk):
                self.assertEqual(doc["status"], "failed")
                self.assertEqual(doc["failed_stage"], "audit_refmac_xyzout")
                self.assertEqual(
                    doc["failures"],
                    [
                        {
                            "failed_stage": "audit_refmac_xyzout",
                            "exception_type": "ValueError",
                            "exception_message": expected_nan_err,
                            "xyzout_status": "rejected_invalid_or_unreadable",
                        }
                    ],
                )
                self.assertEqual(
                    doc["audits"]["xyzout_pdb_audit"], xyzout_audit_disk
                )
                ops = doc["operation_checks"]
                self.assertIs(ops["worker_launched"], True)
                self.assertIs(ops["process_returncode_zero"], True)
                self.assertIs(ops["all_raw_outputs_present_and_regular"], True)
                self.assertIs(ops["input_immutability_verified"], True)
                self.assertIs(ops["stage1_collection_succeeded"], True)
                self.assertIs(ops["hklout_audit_valid"], True)
                self.assertIs(ops["xmlout_audit_valid"], True)
                self.assertIs(ops["xyzout_audit_valid"], False)
                self.assertEqual(
                    ops["xyzout_audit_status"], "rejected_invalid_or_unreadable"
                )
                self.assertIs(ops["stage2_audits_succeeded"], False)
                self.assertIs(ops["collector_succeeded"], False)
                self.assertIs(doc["model_preservation_proven"], False)
                self.assertIn(
                    expected_nan_err,
                    str(doc["model_preservation_unproven_reason"]),
                )
                self._assert_all_scientific_admission_flags_false(doc)

    def test_pre_execution_checkpoint_overwrite_move_and_inode_replacement_recovery(
        self,
    ) -> None:
        # Subtest 1: Overwrite the pre-execution checkpoint in place with distinct known bytes
        # while keeping its original inode and admitted child directory.
        with self.subTest(case="overwrite_in_place"):
            overwritten_bytes = b'{"corrupted": "overwritten_in_place_by_runner"}\n'
            overwritten_sha256 = _sha256_bytes(overwritten_bytes)
            overwritten_size = len(overwritten_bytes)
            captured_pre: dict[str, Any] = {}

            def _overwrite_checkpoint_runner(
                xyzin: str | os.PathLike[str],
                hklin: str | os.PathLike[str],
                xyzout: str | os.PathLike[str],
                hklout: str | os.PathLike[str],
                log_path: str | os.PathLike[str],
                keywords: str | Sequence[str],
                *,
                cwd: str | os.PathLike[str] | None = None,
                timeout: float = 300.0,
                xml_output: str | os.PathLike[str] | None = None,
                executable: str | os.PathLike[str] | None = None,
                env: Mapping[str, str] | None = None,
                ccp4: bool = False,
            ) -> subprocess.CompletedProcess[str]:
                self._write_capture_success_outputs(
                    xyzin_path=Path(xyzin),
                    hklin_path=Path(hklin),
                    xyzout_path=Path(xyzout),
                    hklout_path=Path(hklout),
                    log_path=Path(log_path),
                )
                cp_path = Path(xyzout).parent / "refmac_pre_execution_checkpoint.json"
                st_before = os.lstat(cp_path)
                raw_before = cp_path.read_bytes()
                captured_pre["path"] = cp_path
                captured_pre["bytes"] = raw_before
                captured_pre["sha256"] = _sha256_bytes(raw_before)
                captured_pre["size_bytes"] = len(raw_before)
                captured_pre["dev_ino"] = (int(st_before.st_dev), int(st_before.st_ino))
                with open(cp_path, "wb") as handle:
                    handle.write(overwritten_bytes)
                st_after = os.lstat(cp_path)
                captured_pre["dev_ino_after"] = (
                    int(st_after.st_dev),
                    int(st_after.st_ino),
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
                    stdout=Path(log_path).read_text(encoding="utf-8"),
                    stderr="",
                )

            with self.assertRaises(
                onesar_refmac.RefmacCollectorError
            ) as cm:
                self._run_with_fake_ccp4(
                    "checkpoint_overwrite_in_place",
                    _overwrite_checkpoint_runner,
                )

            exc = cm.exception
            self.assertEqual(exc.failed_stage, "verify_pre_execution_checkpoint")
            self.assertEqual(exc.returncode, 0)
            self.assertIsInstance(exc.primary_cause, ValueError)
            self.assertIs(exc.__cause__, exc.primary_cause)
            self.assertIs(exc.publication_pair_complete, True)
            self.assertIsNotNone(exc.manifest_path)
            self.assertIsNotNone(exc.diagnostics_path)
            assert exc.manifest_path is not None
            assert exc.diagnostics_path is not None
            assert exc.manifest_payload is not None
            assert exc.diagnostics_payload is not None
            cp_path = captured_pre["path"]
            self.assertEqual(captured_pre["dev_ino"], captured_pre["dev_ino_after"])
            # Damaged file on disk remains damaged at its original path; recovery never overwrites it.
            st_post = os.lstat(cp_path)
            self.assertEqual(
                (int(st_post.st_dev), int(st_post.st_ino)),
                captured_pre["dev_ino"],
            )
            self.assertEqual(cp_path.read_bytes(), overwritten_bytes)

            manifest_disk = self._reopen_and_verify_json_artifact(
                {
                    "path": str(exc.manifest_path),
                    "sha256": _sha256_bytes(Path(exc.manifest_path).read_bytes()),
                    "size_bytes": Path(exc.manifest_path).stat().st_size,
                }
            )
            self.assertEqual(manifest_disk, exc.manifest_payload)
            diagnostics_disk = self._reopen_and_verify_json_artifact(
                manifest_disk["diagnostics_json"]
            )
            self.assertEqual(diagnostics_disk, exc.diagnostics_payload)
            post_ckpt_disk = self._reopen_and_verify_json_artifact(
                manifest_disk["post_execution_checkpoint_json"]
            )

            recovery_ref = manifest_disk["pre_execution_checkpoint_recovery_json"]
            self.assertIsNotNone(recovery_ref)
            self.assertNotEqual(Path(recovery_ref["path"]), cp_path)
            recovered_disk = self._reopen_and_verify_json_artifact(recovery_ref)
            recovered_raw_bytes = Path(recovery_ref["path"]).read_bytes()
            self.assertEqual(recovered_raw_bytes, captured_pre["bytes"])
            self.assertEqual(
                recovery_ref["sha256"],
                captured_pre["sha256"],
            )
            self.assertEqual(
                recovery_ref["size_bytes"],
                captured_pre["size_bytes"],
            )
            self.assertEqual(
                recovered_disk,
                json.loads(captured_pre["bytes"].decode("utf-8")),
            )

            eff_cp_ref = manifest_disk["pre_execution_checkpoint_json"]
            self.assertIs(eff_cp_ref["verified_at_original_path"], False)
            self.assertEqual(
                eff_cp_ref["recovered_for_damaged_checkpoint_path"],
                str(cp_path),
            )
            self.assertEqual(eff_cp_ref["path"], recovery_ref["path"])
            self.assertEqual(eff_cp_ref["sha256"], captured_pre["sha256"])
            self.assertEqual(eff_cp_ref["size_bytes"], captured_pre["size_bytes"])
            orig_recorded = eff_cp_ref["original_recorded_checkpoint"]
            self.assertEqual(orig_recorded["path"], str(cp_path))
            self.assertEqual(orig_recorded["sha256"], captured_pre["sha256"])
            self.assertEqual(orig_recorded["size_bytes"], captured_pre["size_bytes"])

            damaged_post = eff_cp_ref["damaged_checkpoint_post_run"]
            self.assertEqual(damaged_post["path"], str(cp_path))
            self.assertIs(damaged_post["exists"], True)
            self.assertIs(damaged_post["is_symlink"], False)
            self.assertIs(damaged_post["is_regular_file"], True)
            self.assertEqual(damaged_post["sha256"], overwritten_sha256)
            self.assertEqual(damaged_post["size_bytes"], overwritten_size)
            self.assertEqual(
                damaged_post["expected_sha256"], captured_pre["sha256"]
            )
            self.assertEqual(
                damaged_post["expected_size_bytes"], captured_pre["size_bytes"]
            )
            self.assertIs(damaged_post["ancestor_chain_verified"], True)
            self.assertIs(damaged_post["matches_baseline"], False)
            self.assertEqual(damaged_post["exception_type"], "ValueError")

            for doc in (manifest_disk, diagnostics_disk, post_ckpt_disk):
                self.assertEqual(doc["status"], "failed")
                self.assertEqual(
                    doc["failed_stage"], "verify_pre_execution_checkpoint"
                )
                self.assertIs(doc["pre_execution_checkpoint_verified"], False)
                self.assertEqual(
                    doc["pre_execution_checkpoint_recovery_json"],
                    recovery_ref,
                )
                self.assertEqual(
                    doc["input_immutability"][
                        "pre_execution_checkpoint_recovery_json"
                    ],
                    recovery_ref,
                )
                cp_failure = doc["failures"][0]
                self.assertEqual(
                    cp_failure["failed_stage"],
                    "verify_pre_execution_checkpoint",
                )
                self.assertEqual(
                    cp_failure["original_recorded_checkpoint"],
                    orig_recorded,
                )
                self.assertEqual(
                    cp_failure["damaged_checkpoint_post_run"],
                    damaged_post,
                )
                self.assertEqual(
                    cp_failure["recovery_checkpoint_json"],
                    recovery_ref,
                )
                mutations = doc["input_immutability"]["mutations"]
                self.assertEqual(len(mutations), 1)
                self.assertEqual(
                    mutations[0]["category"], "pre_execution_checkpoint"
                )
                self.assertEqual(
                    mutations[0]["key"],
                    "refmac_pre_execution_checkpoint_json",
                )
                self.assertEqual(
                    mutations[0]["expected_sha256"], captured_pre["sha256"]
                )
                self.assertEqual(
                    mutations[0]["actual_sha256"], overwritten_sha256
                )
                ops = doc["operation_checks"]
                self.assertIs(ops["pre_execution_checkpoint_verified"], False)
                self.assertIs(ops["input_immutability_verified"], False)
                self.assertIs(ops["collector_succeeded"], False)

            for final_doc in (manifest_disk, diagnostics_disk):
                self._assert_all_scientific_admission_flags_false(final_doc)

        # Subtest 2: Rename the pre-execution checkpoint aside so its original path is absent,
        # preserving the parked original file's inode and bytes and recovering via recovery_checkpoint_json.
        with self.subTest(case="move_aside_absent"):
            captured_move: dict[str, Any] = {}

            def _move_checkpoint_runner(
                xyzin: str | os.PathLike[str],
                hklin: str | os.PathLike[str],
                xyzout: str | os.PathLike[str],
                hklout: str | os.PathLike[str],
                log_path: str | os.PathLike[str],
                keywords: str | Sequence[str],
                *,
                cwd: str | os.PathLike[str] | None = None,
                timeout: float = 300.0,
                xml_output: str | os.PathLike[str] | None = None,
                executable: str | os.PathLike[str] | None = None,
                env: Mapping[str, str] | None = None,
                ccp4: bool = False,
            ) -> subprocess.CompletedProcess[str]:
                self._write_capture_success_outputs(
                    xyzin_path=Path(xyzin),
                    hklin_path=Path(hklin),
                    xyzout_path=Path(xyzout),
                    hklout_path=Path(hklout),
                    log_path=Path(log_path),
                )
                refmac_dir = Path(xyzout).parent
                cp_path = refmac_dir / "refmac_pre_execution_checkpoint.json"
                parked_path = (
                    refmac_dir.parent / "parked_pre_execution_checkpoint.json"
                )
                st_before = os.lstat(cp_path)
                raw_before = cp_path.read_bytes()
                captured_move["cp_path"] = cp_path
                captured_move["parked_path"] = parked_path
                captured_move["bytes"] = raw_before
                captured_move["sha256"] = _sha256_bytes(raw_before)
                captured_move["size_bytes"] = len(raw_before)
                captured_move["dev_ino"] = (
                    int(st_before.st_dev),
                    int(st_before.st_ino),
                )
                os.replace(cp_path, parked_path)
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
                    stdout=Path(log_path).read_text(encoding="utf-8"),
                    stderr="",
                )

            with self.assertRaises(
                onesar_refmac.RefmacCollectorError
            ) as cm_move:
                self._run_with_fake_ccp4(
                    "checkpoint_move_aside",
                    _move_checkpoint_runner,
                )

            exc_move = cm_move.exception
            self.assertEqual(
                exc_move.failed_stage, "verify_pre_execution_checkpoint"
            )
            self.assertEqual(exc_move.returncode, 0)
            self.assertIsInstance(exc_move.primary_cause, FileNotFoundError)
            self.assertEqual(exc_move.primary_cause.errno, errno.ENOENT)
            self.assertIs(exc_move.__cause__, exc_move.primary_cause)
            self.assertIs(exc_move.publication_pair_complete, True)
            self.assertIsNotNone(exc_move.manifest_path)
            self.assertIsNotNone(exc_move.diagnostics_path)
            assert exc_move.manifest_path is not None
            assert exc_move.diagnostics_path is not None
            assert exc_move.manifest_payload is not None
            assert exc_move.diagnostics_payload is not None

            cp_path_move = captured_move["cp_path"]
            parked_path_move = captured_move["parked_path"]
            self.assertFalse(os.path.lexists(cp_path_move))
            st_parked = os.lstat(parked_path_move)
            self.assertEqual(
                (int(st_parked.st_dev), int(st_parked.st_ino)),
                captured_move["dev_ino"],
            )
            self.assertEqual(
                parked_path_move.read_bytes(),
                captured_move["bytes"],
            )

            manifest_move = self._reopen_and_verify_json_artifact(
                {
                    "path": str(exc_move.manifest_path),
                    "sha256": _sha256_bytes(
                        Path(exc_move.manifest_path).read_bytes()
                    ),
                    "size_bytes": Path(exc_move.manifest_path).stat().st_size,
                }
            )
            self.assertEqual(manifest_move, exc_move.manifest_payload)
            diagnostics_move = self._reopen_and_verify_json_artifact(
                manifest_move["diagnostics_json"]
            )
            self.assertEqual(diagnostics_move, exc_move.diagnostics_payload)

            recovery_ref_move = manifest_move[
                "pre_execution_checkpoint_recovery_json"
            ]
            self.assertIsNotNone(recovery_ref_move)
            self._reopen_and_verify_json_artifact(recovery_ref_move)
            self.assertEqual(
                Path(recovery_ref_move["path"]).read_bytes(),
                captured_move["bytes"],
            )
            self.assertEqual(
                recovery_ref_move["sha256"],
                captured_move["sha256"],
            )

            damaged_move = manifest_move["pre_execution_checkpoint_post_run"]
            self.assertEqual(damaged_move["path"], str(cp_path_move))
            self.assertIs(damaged_move["exists"], False)
            self.assertIs(damaged_move["is_symlink"], False)
            self.assertIs(damaged_move["is_regular_file"], False)
            self.assertIsNone(damaged_move["sha256"])
            self.assertIsNone(damaged_move["size_bytes"])
            self.assertEqual(
                damaged_move["expected_sha256"], captured_move["sha256"]
            )
            self.assertEqual(
                damaged_move["expected_size_bytes"], captured_move["size_bytes"]
            )
            self.assertIs(damaged_move["ancestor_chain_verified"], True)
            self.assertIs(damaged_move["matches_baseline"], False)
            self.assertEqual(
                damaged_move["exception_type"], "FileNotFoundError"
            )
            self.assertEqual(damaged_move["errno"], errno.ENOENT)

            for final_doc in (manifest_move, diagnostics_move):
                self.assertEqual(final_doc["status"], "failed")
                self.assertEqual(
                    final_doc["failed_stage"], "verify_pre_execution_checkpoint"
                )
                self._assert_all_scientific_admission_flags_false(final_doc)

        # Subtest 3: Byte-identical replacement at a new inode (equal SHA-256 and size do not prove inode identity).
        with self.subTest(case="byte_identical_new_inode_replacement"):
            ev_root = self.repo_root.parent / "cp_inode_replace_root"
            refmac_dir = ev_root / "refmac"
            refmac_dir.mkdir(parents=True)
            kw_path = refmac_dir / "refmac_keywords.txt"
            kw_bytes = b"NCYC 0\nEND\n"
            kw_path.write_bytes(kw_bytes)
            kw_baseline = {
                "path": str(kw_path),
                "sha256": _sha256_bytes(kw_bytes),
                "size_bytes": len(kw_bytes),
                **onesar_refmac._build_file_ancestor_chain_baseline(
                    kw_path, evidence_root=ev_root
                ),
            }

            cp_file = refmac_dir / "refmac_pre_execution_checkpoint.json"
            cp_bytes = b'{"checkpoint_stage": "pre_execution", "schema_version": 1}\n'
            cp_file.write_bytes(cp_bytes)
            cp_baseline = {
                "path": str(cp_file),
                "sha256": _sha256_bytes(cp_bytes),
                "size_bytes": len(cp_bytes),
                **onesar_refmac._build_file_ancestor_chain_baseline(
                    cp_file, evidence_root=ev_root
                ),
            }
            orig_cp_dev_ino = (cp_baseline["dev"], cp_baseline["ino"])

            # Park original file to keep its inode alive, then write identical bytes to a new inode at cp_file.
            parked_cp = ev_root / "parked_orig_checkpoint.json"
            os.replace(cp_file, parked_cp)
            cp_file.write_bytes(cp_bytes)
            replacement_st = os.lstat(cp_file)
            replacement_dev_ino = (
                int(replacement_st.st_dev),
                int(replacement_st.st_ino),
            )
            self.assertNotEqual(replacement_dev_ino, orig_cp_dev_ino)
            self.assertEqual(_sha256_bytes(cp_file.read_bytes()), cp_baseline["sha256"])

            caught_cp: list[Exception] = []
            mut_causes: list[Exception | None] = []
            cp_causes: list[Exception | None] = []
            imm_report = onesar_refmac._verify_immutable_baselines_post_run(
                {},
                {},
                kw_baseline,
                pre_execution_checkpoint_baseline=cp_baseline,
                caught_exceptions=caught_cp,
                mutation_causes_out=mut_causes,
                pre_checkpoint_cause_out=cp_causes,
            )
            self.assertIs(imm_report["verified"], False)
            self.assertIs(imm_report["pre_execution_checkpoint_verified"], False)
            cp_post = imm_report["pre_execution_checkpoint_post_run"]
            self.assertEqual(cp_post["sha256"], cp_baseline["sha256"])
            self.assertEqual(cp_post["size_bytes"], cp_baseline["size_bytes"])
            self.assertIs(cp_post["matches_baseline"], False)
            self.assertEqual(cp_post["exception_type"], "ValueError")
            self.assertEqual(len(imm_report["mutations"]), 1)
            self.assertEqual(
                imm_report["mutations"][0]["category"],
                "pre_execution_checkpoint",
            )
            self.assertEqual(len(cp_causes), 1)
            self.assertIsInstance(cp_causes[0], ValueError)

    def test_child_refmac_dir_missing_by_rename_and_replacements_with_parent_fallback(
        self,
    ) -> None:
        # Three direct helper variants (missing by rename, ordinary-file replacement,
        # byte-identical directory replacement) plus one end-to-end operation check.
        for variant in (
            "missing_by_rename",
            "ordinary_file_replacement",
            "byte_identical_directory_replacement",
        ):
            with self.subTest(variant=variant):
                ev_root = self.repo_root.parent / f"child_replace_{variant}_root"
                refmac_dir = ev_root / "refmac"
                parent_retention_dir = ev_root / "refmac_parent_retention"
                refmac_dir.mkdir(parents=True)
                parent_retention_dir.mkdir(parents=True)

                known_files_bytes: dict[str, bytes] = {
                    "log": b"REFMAC_LOG_KNOWN_BYTES\n",
                    "xyzout": b"HEADER    TEST_PDB\nEND\n",
                    "hklout": b"MTZ_KNOWN_BYTES\n",
                    "keywords": b"NCYC 0\nEND\n",
                    "pre_execution_checkpoint_json": (
                        b'{"checkpoint_stage": "pre_execution"}\n'
                    ),
                }
                known_paths: dict[str, Path] = {}
                orig_file_identities: dict[str, tuple[int, int, str, int]] = {}
                for label, raw in known_files_bytes.items():
                    fname = (
                        "refmac_pre_execution_checkpoint.json"
                        if label == "pre_execution_checkpoint_json"
                        else f"1sar_{label}.dat"
                    )
                    fpath = refmac_dir / fname
                    fpath.write_bytes(raw)
                    fst = os.lstat(fpath)
                    known_paths[label] = fpath
                    orig_file_identities[fname] = (
                        int(fst.st_dev),
                        int(fst.st_ino),
                        _sha256_bytes(raw),
                        len(raw),
                    )

                child_baseline = onesar_refmac._capture_directory_identity_baseline(
                    refmac_dir, evidence_root=ev_root
                )
                parent_baseline = onesar_refmac._capture_directory_identity_baseline(
                    parent_retention_dir, evidence_root=ev_root
                )

                parked_child_dir = ev_root / f"parked_refmac_{variant}"
                os.replace(refmac_dir, parked_child_dir)

                ordinary_marker_bytes = b"ORDINARY_FILE_REPLACING_REFMAC_DIR\n"
                if variant == "ordinary_file_replacement":
                    refmac_dir.write_bytes(ordinary_marker_bytes)
                elif variant == "byte_identical_directory_replacement":
                    refmac_dir.mkdir()
                    for fname, (
                        orig_dev,
                        orig_ino,
                        orig_sha,
                        orig_sz,
                    ) in orig_file_identities.items():
                        parked_file = parked_child_dir / fname
                        copied_bytes = parked_file.read_bytes()
                        new_file = refmac_dir / fname
                        new_file.write_bytes(copied_bytes)
                        new_st = os.lstat(new_file)
                        # Equal SHA-256 and size, but distinct file inode.
                        self.assertEqual(_sha256_bytes(new_file.read_bytes()), orig_sha)
                        self.assertEqual(int(new_st.st_size), orig_sz)
                        self.assertNotEqual(
                            (int(new_st.st_dev), int(new_st.st_ino)),
                            (orig_dev, orig_ino),
                        )
                    rep_dir_st = os.lstat(refmac_dir)
                    self.assertNotEqual(
                        (int(rep_dir_st.st_dev), int(rep_dir_st.st_ino)),
                        (child_baseline["dev"], child_baseline["ino"]),
                    )

                dir_causes: list[Exception] = []
                dir_status = onesar_refmac._verify_refmac_directory_post_run(
                    refmac_dir,
                    refmac_dir_baseline=child_baseline,
                    caught_exceptions=dir_causes,
                )
                self.assertIs(dir_status["identity_verified"], False)
                self.assertIs(dir_status["writable_post_run"], False)
                self.assertEqual(len(dir_causes), 1)

                if variant == "missing_by_rename":
                    self.assertIs(dir_status["exists"], False)
                    self.assertIs(dir_status["is_directory"], False)
                    self.assertIs(dir_status["is_symlink"], False)
                    self.assertEqual(
                        dir_status["exception_type"], "FileNotFoundError"
                    )
                    self.assertEqual(dir_status["errno"], errno.ENOENT)
                    self.assertIsInstance(dir_causes[0], FileNotFoundError)
                elif variant == "ordinary_file_replacement":
                    self.assertIs(dir_status["exists"], True)
                    self.assertIs(dir_status["is_directory"], False)
                    self.assertIs(dir_status["is_symlink"], False)
                    self.assertEqual(dir_status["exception_type"], "ValueError")
                    self.assertIn(
                        "not a directory", str(dir_status["error"])
                    )
                    self.assertIsInstance(dir_causes[0], ValueError)
                else:
                    self.assertIs(dir_status["exists"], True)
                    self.assertIs(dir_status["is_directory"], True)
                    self.assertIs(dir_status["is_symlink"], False)
                    self.assertEqual(dir_status["exception_type"], "ValueError")
                    self.assertIn(
                        "inode changed", str(dir_status["error"])
                    )
                    self.assertIsInstance(dir_causes[0], ValueError)

                # Observe os.scandir during both status-supplied and expected_root_identity scanner calls.
                real_scandir = os.scandir
                scandir_targets: list[str] = []

                def _spy_scandir(path: Any = ".") -> Any:
                    scandir_targets.append(os.path.abspath(os.fspath(path)))
                    return real_scandir(path)

                scandir_causes_1: list[Exception | None] = []
                scandir_causes_2: list[Exception | None] = []
                with patch("onesar_refmac.os.scandir", side_effect=_spy_scandir):
                    scan_1 = onesar_refmac._scan_refmac_directory_entries(
                        refmac_dir,
                        known_paths=known_paths,
                        expected_root_identity=child_baseline,
                        refmac_dir_status=dir_status,
                        refmac_dir_initial_cause=dir_causes[0],
                        scandir_cause_out=scandir_causes_1,
                    )
                    scan_2 = onesar_refmac._scan_refmac_directory_entries(
                        refmac_dir,
                        known_paths=known_paths,
                        expected_root_identity=child_baseline,
                        scandir_cause_out=scandir_causes_2,
                    )

                self.assertEqual(scandir_targets, [])
                for scan_res in (scan_1, scan_2):
                    self.assertEqual(scan_res["additional_files"], {})
                    self.assertIsNotNone(scan_res["scandir_error"])
                    self.assertEqual(
                        scan_res["scandir_error"]["output_key"],
                        "refmac_dir_scan",
                    )
                    self.assertIs(
                        scan_res["scandir_error"]["within_refmac_dir"], False
                    )
                self.assertIs(scandir_causes_1[0], dir_causes[0])
                self.assertIsInstance(scandir_causes_2[0], type(dir_causes[0]))

                # Persist a collector JSON payload: must not write into absent/replacement child,
                # and must fall back to the surviving admitted parent_retention_dir.
                parent_status = onesar_refmac._verify_refmac_directory_post_run(
                    parent_retention_dir,
                    refmac_dir_baseline=parent_baseline,
                )
                self.assertIs(parent_status["identity_verified"], True)

                payload = {"schema_version": 1, "variant": variant}
                child_failures: list[dict[str, Any]] = []
                persist_causes: list[Exception] = []
                child_causes: list[Exception | None] = [dir_causes[0]]
                parent_causes: list[Exception | None] = []
                fallback_state: dict[str, Any] = {}
                target_in_child = refmac_dir / "refmac_manifest.json"

                artifact = onesar_refmac._persist_collector_json_with_fallback(
                    payload,
                    target_in_child,
                    root=refmac_dir,
                    parent_retention_dir=parent_retention_dir,
                    parent_retention_dir_baseline=parent_baseline,
                    parent_retention_dir_status=parent_status,
                    verified_root_fallback_state=fallback_state,
                    refmac_dir_status=dir_status,
                    child_dir_persistence_failures=child_failures,
                    caught_persistence_exceptions=persist_causes,
                    child_dir_persistence_causes=child_causes,
                    parent_retention_dir_cause_sink=parent_causes,
                )

                self.assertEqual(len(child_failures), 1)
                self.assertIs(
                    child_failures[0]["attempted_write_in_child_dir"], False
                )
                self.assertEqual(
                    child_failures[0]["intended_path"], str(target_in_child)
                )
                self.assertIs(
                    artifact["fallback_for_unwritable_or_damaged_child_dir"],
                    True,
                )
                self.assertEqual(
                    artifact["actual_retention_anchor_kind"],
                    "parent_retention_dir",
                )
                self.assertEqual(
                    artifact["actual_retention_anchor_dir"],
                    str(parent_retention_dir),
                )
                reopened = self._reopen_and_verify_json_artifact(artifact)
                self.assertEqual(reopened, payload)

                # Verify absent/replacement child was not written to and parked originals remain intact.
                if variant == "missing_by_rename":
                    self.assertFalse(os.path.lexists(refmac_dir))
                elif variant == "ordinary_file_replacement":
                    self.assertEqual(
                        refmac_dir.read_bytes(), ordinary_marker_bytes
                    )
                else:
                    self.assertFalse(os.path.lexists(target_in_child))

                parked_st = os.lstat(parked_child_dir)
                self.assertEqual(
                    (int(parked_st.st_dev), int(parked_st.st_ino)),
                    (child_baseline["dev"], child_baseline["ino"]),
                )
                for fname, (
                    orig_dev,
                    orig_ino,
                    orig_sha,
                    orig_sz,
                ) in orig_file_identities.items():
                    pf = parked_child_dir / fname
                    pf_st = os.lstat(pf)
                    self.assertEqual(
                        (int(pf_st.st_dev), int(pf_st.st_ino)),
                        (orig_dev, orig_ino),
                    )
                    self.assertEqual(_sha256_bytes(pf.read_bytes()), orig_sha)
                    self.assertEqual(int(pf_st.st_size), orig_sz)

        # End-to-end operation subtest: runner renames refmac_dir aside after writing outputs.
        with self.subTest(variant="end_to_end_runner_renames_child_aside"):
            parked_info: dict[str, Any] = {}

            def _rename_child_runner(
                xyzin: str | os.PathLike[str],
                hklin: str | os.PathLike[str],
                xyzout: str | os.PathLike[str],
                hklout: str | os.PathLike[str],
                log_path: str | os.PathLike[str],
                keywords: str | Sequence[str],
                *,
                cwd: str | os.PathLike[str] | None = None,
                timeout: float = 300.0,
                xml_output: str | os.PathLike[str] | None = None,
                executable: str | os.PathLike[str] | None = None,
                env: Mapping[str, str] | None = None,
                ccp4: bool = False,
            ) -> subprocess.CompletedProcess[str]:
                self._write_capture_success_outputs(
                    xyzin_path=Path(xyzin),
                    hklin_path=Path(hklin),
                    xyzout_path=Path(xyzout),
                    hklout_path=Path(hklout),
                    log_path=Path(log_path),
                )
                refmac_dir = Path(xyzout).parent
                cp_path = refmac_dir / "refmac_pre_execution_checkpoint.json"
                log_text = Path(log_path).read_text(encoding="utf-8")
                dir_st = os.lstat(refmac_dir)
                cp_st = os.lstat(cp_path)
                cp_raw = cp_path.read_bytes()
                parked_dir = refmac_dir.parent / "parked_child_from_runner"
                parked_info["refmac_dir"] = refmac_dir
                parked_info["parked_dir"] = parked_dir
                parked_info["dir_dev_ino"] = (
                    int(dir_st.st_dev),
                    int(dir_st.st_ino),
                )
                parked_info["cp_dev_ino"] = (
                    int(cp_st.st_dev),
                    int(cp_st.st_ino),
                )
                parked_info["cp_bytes"] = cp_raw
                parked_info["cp_sha256"] = _sha256_bytes(cp_raw)
                os.replace(refmac_dir, parked_dir)
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
                    stdout=log_text,
                    stderr="",
                )

            with self.assertRaises(
                onesar_refmac.RefmacCollectorError
            ) as cm_e2e:
                self._run_with_fake_ccp4(
                    "child_missing_by_rename_e2e",
                    _rename_child_runner,
                )

            exc_e2e = cm_e2e.exception
            self.assertEqual(
                exc_e2e.failed_stage, "verify_pre_execution_checkpoint"
            )
            self.assertEqual(exc_e2e.returncode, 0)
            self.assertIsInstance(exc_e2e.primary_cause, FileNotFoundError)
            self.assertEqual(exc_e2e.primary_cause.errno, errno.ENOENT)
            self.assertIs(exc_e2e.__cause__, exc_e2e.primary_cause)
            self.assertIs(exc_e2e.publication_pair_complete, True)
            self.assertIsNotNone(exc_e2e.manifest_path)
            self.assertIsNotNone(exc_e2e.diagnostics_path)
            assert exc_e2e.manifest_path is not None
            assert exc_e2e.diagnostics_path is not None
            assert exc_e2e.manifest_payload is not None
            assert exc_e2e.diagnostics_payload is not None
            self.assertFalse(os.path.lexists(parked_info["refmac_dir"]))
            parked_dir_st = os.lstat(parked_info["parked_dir"])
            self.assertEqual(
                (int(parked_dir_st.st_dev), int(parked_dir_st.st_ino)),
                parked_info["dir_dev_ino"],
            )
            parked_cp_path = (
                parked_info["parked_dir"]
                / "refmac_pre_execution_checkpoint.json"
            )
            parked_cp_st = os.lstat(parked_cp_path)
            self.assertEqual(
                (int(parked_cp_st.st_dev), int(parked_cp_st.st_ino)),
                parked_info["cp_dev_ino"],
            )
            self.assertEqual(
                parked_cp_path.read_bytes(), parked_info["cp_bytes"]
            )

            manifest_e2e = self._reopen_and_verify_json_artifact(
                {
                    "path": str(exc_e2e.manifest_path),
                    "sha256": _sha256_bytes(
                        Path(exc_e2e.manifest_path).read_bytes()
                    ),
                    "size_bytes": Path(exc_e2e.manifest_path).stat().st_size,
                }
            )
            self.assertEqual(manifest_e2e, exc_e2e.manifest_payload)
            diagnostics_e2e = self._reopen_and_verify_json_artifact(
                manifest_e2e["diagnostics_json"]
            )
            self.assertEqual(diagnostics_e2e, exc_e2e.diagnostics_payload)
            recovery_e2e = manifest_e2e["pre_execution_checkpoint_recovery_json"]
            self.assertIsNotNone(recovery_e2e)
            self._reopen_and_verify_json_artifact(recovery_e2e)
            self.assertEqual(
                Path(recovery_e2e["path"]).read_bytes(),
                parked_info["cp_bytes"],
            )
            for doc in (manifest_e2e, diagnostics_e2e):
                self.assertEqual(doc["status"], "failed")
                self.assertEqual(
                    doc["failed_stage"], "verify_pre_execution_checkpoint"
                )
                self.assertIs(doc["parent_retention_used"], True)
                self.assertEqual(
                    doc["actual_parent_retention_anchor_kind"],
                    "parent_retention_dir",
                )
                self.assertIs(
                    doc["refmac_directory_post_run"]["identity_verified"], False
                )
                self.assertIs(
                    doc["refmac_directory_post_run"]["exists"], False
                )
                self._assert_all_scientific_admission_flags_false(doc)

    def test_escaped_output_and_escaped_input_ancestor_symlinks_rejected_without_reading_target(
        self,
    ) -> None:
        # Placement 1: Escaped output leaf symlink inside an otherwise admitted child refmac_dir.
        with self.subTest(placement="escaped_output_leaf_symlink"):
            ev_root = self.repo_root.parent / "escaped_output_leaf_root"
            refmac_dir = ev_root / "refmac"
            refmac_dir.mkdir(parents=True)
            sentinel_path = self.repo_root.parent / "escaped_output_outside_sentinel.pdb"
            sentinel_bytes = b"HEADER    OUTSIDE_SENTINEL_NEVER_READ\nEND\n"
            sentinel_path.write_bytes(sentinel_bytes)
            sentinel_st_before = os.lstat(sentinel_path)
            sentinel_dev_ino = (
                int(sentinel_st_before.st_dev),
                int(sentinel_st_before.st_ino),
            )
            sentinel_sha256 = _sha256_bytes(sentinel_bytes)

            log_file = refmac_dir / "1sar_refmac_ncyc0.log"
            log_file.write_bytes(b"NORMAL_LOG\n")
            child_baseline = onesar_refmac._capture_directory_identity_baseline(
                refmac_dir, evidence_root=ev_root
            )

            escaped_xyzout = refmac_dir / "1sar_refmac_ncyc0.pdb"
            os.symlink(sentinel_path, escaped_xyzout)

            real_read_bytes = Path.read_bytes
            real_sha256_file = onesar_refmac._sha256_regular_file
            read_targets: list[str] = []
            hashed_targets: list[str] = []

            def _spy_read_bytes(path_self: Path) -> bytes:
                read_targets.append(os.path.abspath(os.fspath(path_self)))
                return real_read_bytes(path_self)

            def _spy_sha256_file(path_arg: Path) -> str:
                hashed_targets.append(os.path.abspath(os.fspath(path_arg)))
                return real_sha256_file(path_arg)

            with (
                patch.object(Path, "read_bytes", _spy_read_bytes),
                patch(
                    "onesar_refmac._sha256_regular_file",
                    side_effect=_spy_sha256_file,
                ),
            ):
                out_info = onesar_refmac._inspect_output_artifact(
                    escaped_xyzout,
                    root=refmac_dir,
                    expected_root_identity=child_baseline,
                )
                scan_res = onesar_refmac._scan_refmac_directory_entries(
                    refmac_dir,
                    known_paths={"log": log_file, "xyzout": escaped_xyzout},
                    expected_root_identity=child_baseline,
                )

            self.assertIs(out_info["exists"], True)
            self.assertIs(out_info["is_symlink"], True)
            self.assertIs(out_info["is_regular_file"], False)
            self.assertIs(out_info["within_refmac_dir"], False)
            self.assertIsNone(out_info["resolved_path"])
            self.assertIsNone(out_info["sha256"])
            self.assertIsNone(out_info["size_bytes"])
            self.assertIn(
                "Refusing to follow symlink at output path",
                str(out_info["error"]),
            )
            self.assertIn(str(escaped_xyzout), scan_res["unexpected_symlinks"])
            self.assertTrue(
                any(
                    err.get("path") == str(escaped_xyzout)
                    and err.get("is_symlink") is True
                    for err in scan_res["inspection_errors"]
                )
            )
            # Neither the symlink nor the outside sentinel was read or hashed.
            self.assertNotIn(
                os.path.abspath(os.fspath(escaped_xyzout)), read_targets
            )
            self.assertNotIn(
                os.path.abspath(os.fspath(sentinel_path)), read_targets
            )
            self.assertNotIn(
                os.path.abspath(os.fspath(escaped_xyzout)), hashed_targets
            )
            self.assertNotIn(
                os.path.abspath(os.fspath(sentinel_path)), hashed_targets
            )
            sentinel_st_after = os.lstat(sentinel_path)
            self.assertEqual(
                (int(sentinel_st_after.st_dev), int(sentinel_st_after.st_ino)),
                sentinel_dev_ino,
            )
            self.assertEqual(
                _sha256_bytes(sentinel_path.read_bytes()), sentinel_sha256
            )

        # Placement 2: Escaped input ancestor symlink (direct helper + end-to-end operation).
        with self.subTest(placement="escaped_input_ancestor_symlink"):
            ev_root = self.repo_root.parent / "escaped_input_ancestor_root"
            inputs_dir = ev_root / "inputs"
            refmac_dir = ev_root / "refmac"
            inputs_dir.mkdir(parents=True)
            refmac_dir.mkdir(parents=True)

            orig_input_pdb = inputs_dir / "1sar.pdb"
            orig_input_bytes = b"HEADER    ADMITTED_STAGED_INPUT\nEND\n"
            orig_input_pdb.write_bytes(orig_input_bytes)
            orig_input_st = os.lstat(orig_input_pdb)
            orig_input_dev_ino = (
                int(orig_input_st.st_dev),
                int(orig_input_st.st_ino),
            )
            orig_input_sha256 = _sha256_bytes(orig_input_bytes)

            input_baseline = {
                "path": str(orig_input_pdb),
                "sha256": orig_input_sha256,
                "size_bytes": len(orig_input_bytes),
                **onesar_refmac._build_file_ancestor_chain_baseline(
                    orig_input_pdb, evidence_root=ev_root
                ),
            }

            kw_path = refmac_dir / "refmac_keywords.txt"
            kw_bytes = b"NCYC 0\nEND\n"
            kw_path.write_bytes(kw_bytes)
            kw_baseline = {
                "path": str(kw_path),
                "sha256": _sha256_bytes(kw_bytes),
                "size_bytes": len(kw_bytes),
                **onesar_refmac._build_file_ancestor_chain_baseline(
                    kw_path, evidence_root=ev_root
                ),
            }

            outside_inputs_dir = self.repo_root.parent / "outside_escaped_inputs_dir"
            outside_inputs_dir.mkdir(parents=True)
            outside_pdb = outside_inputs_dir / "1sar.pdb"
            outside_bytes = b"HEADER    OUTSIDE_ESCAPED_INPUT_SENTINEL\nEND\n"
            outside_pdb.write_bytes(outside_bytes)
            outside_st_before = os.lstat(outside_pdb)
            outside_dev_ino = (
                int(outside_st_before.st_dev),
                int(outside_st_before.st_ino),
            )

            parked_inputs_dir = ev_root / "parked_admitted_inputs"
            os.replace(inputs_dir, parked_inputs_dir)
            os.symlink(outside_inputs_dir, inputs_dir)

            real_os_open = os.open
            real_read_bytes = Path.read_bytes
            real_sha256_file = onesar_refmac._sha256_regular_file
            opened_paths: list[str] = []
            read_paths: list[str] = []
            hashed_paths: list[str] = []

            def _spy_os_open(
                path: Any, flags: int, mode: int = 0o777, *, dir_fd: Any = None
            ) -> int:
                opened_paths.append(os.path.abspath(os.fspath(path)))
                if dir_fd is not None:
                    return real_os_open(path, flags, mode, dir_fd=dir_fd)
                return real_os_open(path, flags, mode)

            def _spy_read_bytes_anc(path_self: Path) -> bytes:
                read_paths.append(os.path.abspath(os.fspath(path_self)))
                return real_read_bytes(path_self)

            def _spy_sha256_anc(path_arg: Path) -> str:
                hashed_paths.append(os.path.abspath(os.fspath(path_arg)))
                return real_sha256_file(path_arg)

            caught_imm: list[Exception] = []
            mut_causes: list[Exception | None] = []
            with (
                patch("onesar_refmac.os.open", side_effect=_spy_os_open),
                patch.object(Path, "read_bytes", _spy_read_bytes_anc),
                patch(
                    "onesar_refmac._sha256_regular_file",
                    side_effect=_spy_sha256_anc,
                ),
            ):
                anc_check = onesar_refmac._verify_admitted_ancestor_chain(
                    orig_input_pdb, input_baseline
                )
                read_res = onesar_refmac._verify_and_read_admitted_input_file(
                    orig_input_pdb, input_baseline, label="XYzin PDB"
                )
                imm_report = onesar_refmac._verify_immutable_baselines_post_run(
                    {"original_model_pdb": input_baseline},
                    {},
                    kw_baseline,
                    caught_exceptions=caught_imm,
                    mutation_causes_out=mut_causes,
                )

            self.assertIs(anc_check["verified"], False)
            self.assertEqual(
                anc_check["damaged_ancestor_path"], str(inputs_dir)
            )
            self.assertIs(anc_check["damaged_ancestor_is_symlink"], True)
            self.assertIs(anc_check["damaged_ancestor_is_directory"], False)
            self.assertEqual(
                anc_check["damaged_ancestor_symlink_target"],
                str(outside_inputs_dir),
            )
            self.assertIsInstance(anc_check["exception"], ValueError)

            self.assertIs(read_res["verified"], False)
            self.assertIsNone(read_res["bytes"])
            self.assertEqual(read_res["baseline_sha256"], orig_input_sha256)
            self.assertEqual(
                read_res["baseline_size_bytes"], len(orig_input_bytes)
            )
            self.assertIsNone(read_res["post_run_sha256"])
            self.assertIsNone(read_res["post_run_size_bytes"])
            self.assertIs(read_res["ancestor_chain_verified"], False)
            self.assertEqual(
                read_res["ancestor_check"]["damaged_ancestor_symlink_target"],
                str(outside_inputs_dir),
            )

            self.assertIs(imm_report["verified"], False)
            staged_post = imm_report["staged_inputs_post_run"][
                "original_model_pdb"
            ]
            self.assertIs(staged_post["ancestor_chain_verified"], False)
            self.assertEqual(
                staged_post["damaged_ancestor_path"], str(inputs_dir)
            )
            self.assertIs(staged_post["damaged_ancestor_is_symlink"], True)
            self.assertIsNone(staged_post["sha256"])
            self.assertIsNone(staged_post["size_bytes"])
            self.assertIs(staged_post["matches_baseline"], False)
            self.assertEqual(len(imm_report["mutations"]), 1)
            self.assertEqual(
                imm_report["mutations"][0]["key"], "original_model_pdb"
            )
            self.assertIs(
                imm_report["mutations"][0]["ancestor_chain_verified"], False
            )
            self.assertEqual(len(mut_causes), 1)
            self.assertIsInstance(mut_causes[0], ValueError)

            # Verify no os.open, Path.read_bytes, or _sha256_regular_file accessed the rejected input or outside target.
            forbidden_input_paths = {
                os.path.abspath(os.fspath(orig_input_pdb)),
                os.path.abspath(os.fspath(outside_pdb)),
            }
            self.assertTrue(forbidden_input_paths.isdisjoint(opened_paths))
            self.assertTrue(forbidden_input_paths.isdisjoint(read_paths))
            self.assertTrue(forbidden_input_paths.isdisjoint(hashed_paths))

            parked_pdb = parked_inputs_dir / "1sar.pdb"
            parked_st = os.lstat(parked_pdb)
            self.assertEqual(
                (int(parked_st.st_dev), int(parked_st.st_ino)),
                orig_input_dev_ino,
            )
            self.assertEqual(
                _sha256_bytes(parked_pdb.read_bytes()), orig_input_sha256
            )
            outside_st_after = os.lstat(outside_pdb)
            self.assertEqual(
                (int(outside_st_after.st_dev), int(outside_st_after.st_ino)),
                outside_dev_ino,
            )
            self.assertEqual(outside_pdb.read_bytes(), outside_bytes)

            # End-to-end operation check: populate all 5 actual staged basenames in a dedicated
            # outside owned directory with the real staged bytes, park inputs_dir, and replace
            # inputs_dir with a symlink to that outside directory; post-action collector must not
            # access any lexical rejected-input path or outside target via os.open, Path.read_bytes,
            # or _sha256_regular_file.
            outside_e2e_inputs_dir = (
                self.repo_root.parent / "outside_escaped_e2e_inputs_dir"
            )
            outside_e2e_inputs_dir.mkdir(parents=True)
            expected_staged_basenames = (
                "original_model.pdb",
                "original_data.mtz",
                "projected_observations.mtz",
                "input_hkl_ledger.json",
                "input_admission.json",
            )
            post_action_input_accesses: list[tuple[str, str]] = []
            e2e_state: dict[str, Any] = {
                "active": False,
                "parked_records": {},
                "outside_records": {},
            }

            def _record_if_watched_input(kind: str, raw_path: Any) -> None:
                if not e2e_state["active"]:
                    return
                abs_p = os.path.abspath(os.fspath(raw_path))
                inputs_dir_str = str(e2e_state["inputs_dir"])
                outside_dir_str = str(outside_e2e_inputs_dir)
                if (
                    abs_p == inputs_dir_str
                    or abs_p.startswith(inputs_dir_str + os.sep)
                    or abs_p == outside_dir_str
                    or abs_p.startswith(outside_dir_str + os.sep)
                ):
                    post_action_input_accesses.append((kind, abs_p))

            def _spy_e2e_os_open(
                path: Any, flags: int, mode: int = 0o777, *, dir_fd: Any = None
            ) -> int:
                _record_if_watched_input("os.open", path)
                if dir_fd is not None:
                    return real_os_open(path, flags, mode, dir_fd=dir_fd)
                return real_os_open(path, flags, mode)

            def _spy_e2e_read_bytes(path_self: Path) -> bytes:
                _record_if_watched_input("Path.read_bytes", path_self)
                return real_read_bytes(path_self)

            def _spy_e2e_sha256_file(path_arg: Path) -> str:
                _record_if_watched_input("_sha256_regular_file", path_arg)
                return real_sha256_file(path_arg)

            def _escape_inputs_runner(
                xyzin: str | os.PathLike[str],
                hklin: str | os.PathLike[str],
                xyzout: str | os.PathLike[str],
                hklout: str | os.PathLike[str],
                log_path: str | os.PathLike[str],
                keywords: str | Sequence[str],
                *,
                cwd: str | os.PathLike[str] | None = None,
                timeout: float = 300.0,
                xml_output: str | os.PathLike[str] | None = None,
                executable: str | os.PathLike[str] | None = None,
                env: Mapping[str, str] | None = None,
                ccp4: bool = False,
            ) -> subprocess.CompletedProcess[str]:
                self._write_capture_success_outputs(
                    xyzin_path=Path(xyzin),
                    hklin_path=Path(hklin),
                    xyzout_path=Path(xyzout),
                    hklout_path=Path(hklout),
                    log_path=Path(log_path),
                )
                inp_dir = Path(xyzin).parent
                for bname in expected_staged_basenames:
                    src_f = inp_dir / bname
                    src_st = os.lstat(src_f)
                    src_bytes = real_read_bytes(src_f)
                    src_sha = _sha256_bytes(src_bytes)
                    e2e_state["parked_records"][bname] = {
                        "bytes": src_bytes,
                        "sha256": src_sha,
                        "size_bytes": len(src_bytes),
                        "dev_ino": (int(src_st.st_dev), int(src_st.st_ino)),
                    }
                    dst_f = outside_e2e_inputs_dir / bname
                    dst_f.write_bytes(src_bytes)
                    dst_st = os.lstat(dst_f)
                    e2e_state["outside_records"][bname] = {
                        "bytes": src_bytes,
                        "sha256": src_sha,
                        "size_bytes": len(src_bytes),
                        "dev_ino": (int(dst_st.st_dev), int(dst_st.st_ino)),
                    }
                    self.assertNotEqual(
                        e2e_state["outside_records"][bname]["dev_ino"],
                        e2e_state["parked_records"][bname]["dev_ino"],
                    )
                parked_inp = inp_dir.parent / "parked_inputs_from_runner"
                os.replace(inp_dir, parked_inp)
                os.symlink(outside_e2e_inputs_dir, inp_dir)
                log_stdout = real_read_bytes(Path(log_path)).decode("utf-8")
                e2e_state["inputs_dir"] = inp_dir
                e2e_state["parked_inp"] = parked_inp
                e2e_state["active"] = True
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
                    stdout=log_stdout,
                    stderr="",
                )

            with (
                patch("onesar_refmac.os.open", side_effect=_spy_e2e_os_open),
                patch.object(Path, "read_bytes", _spy_e2e_read_bytes),
                patch(
                    "onesar_refmac._sha256_regular_file",
                    side_effect=_spy_e2e_sha256_file,
                ),
            ):
                with self.assertRaises(
                    onesar_refmac.RefmacCollectorError
                ) as cm_anc_e2e:
                    self._run_with_fake_ccp4(
                        "escaped_input_ancestor_e2e",
                        _escape_inputs_runner,
                    )

            self.assertEqual(post_action_input_accesses, [])
            exc_anc = cm_anc_e2e.exception
            self.assertEqual(exc_anc.failed_stage, "audit_refmac_hklout")
            self.assertEqual(exc_anc.returncode, 0)
            self.assertIsNone(exc_anc.primary_cause)
            self.assertIsNone(exc_anc.__cause__)
            self.assertIs(exc_anc.publication_pair_complete, True)
            self.assertIsNotNone(exc_anc.manifest_path)
            self.assertIsNotNone(exc_anc.diagnostics_path)
            assert exc_anc.manifest_path is not None
            assert exc_anc.diagnostics_path is not None
            assert exc_anc.manifest_payload is not None
            assert exc_anc.diagnostics_payload is not None

            manifest_anc = self._reopen_and_verify_json_artifact(
                {
                    "path": str(exc_anc.manifest_path),
                    "sha256": _sha256_bytes(
                        Path(exc_anc.manifest_path).read_bytes()
                    ),
                    "size_bytes": Path(exc_anc.manifest_path).stat().st_size,
                }
            )
            self.assertEqual(manifest_anc, exc_anc.manifest_payload)
            diagnostics_anc = self._reopen_and_verify_json_artifact(
                manifest_anc["diagnostics_json"]
            )
            self.assertEqual(diagnostics_anc, exc_anc.diagnostics_payload)

            for doc in (manifest_anc, diagnostics_anc):
                self.assertEqual(doc["status"], "failed")
                self.assertEqual(doc["failed_stage"], "audit_refmac_hklout")
                self.assertEqual(
                    [f["failed_stage"] for f in doc["failures"]],
                    [
                        "audit_refmac_hklout",
                        "audit_refmac_xyzout",
                        "verify_input_immutability",
                    ],
                )
                self.assertIs(doc["input_immutability"]["verified"], False)
                for s_key, s_post in doc["input_immutability"][
                    "staged_inputs_post_run"
                ].items():
                    self.assertIs(
                        s_post["ancestor_chain_verified"],
                        False,
                        f"Expected ancestor_chain_verified=False for {s_key}",
                    )
                    self.assertEqual(
                        s_post["damaged_ancestor_path"],
                        str(e2e_state["inputs_dir"]),
                    )
                    self.assertIs(s_post["damaged_ancestor_is_symlink"], True)
                    self.assertIsNone(s_post["sha256"])
                    self.assertIsNone(s_post["size_bytes"])
                    self.assertIs(s_post["matches_baseline"], False)

                hkl_audit = doc["audits"]["hklout_mtz_audit"]
                self.assertEqual(
                    hkl_audit["status"],
                    "rejected_invalid_or_inconsistent",
                )
                self.assertIs(hkl_audit["valid"], False)
                self.assertTrue(
                    any(
                        "Failed to read HKLIN crystallographic context:" in err
                        and "HKLIN ancestor chain verification failed before read"
                        in err
                        and (
                            f"Ancestor directory was replaced by a symlink: {e2e_state['inputs_dir']}"
                            in err
                        )
                        and str(outside_e2e_inputs_dir) in err
                        for err in hkl_audit["errors"]
                    ),
                    f"Expected HKLIN ancestor chain rejection in MTZ errors, got: {hkl_audit['errors']!r}",
                )

                xyz_audit = doc["audits"]["xyzout_pdb_audit"]
                self.assertEqual(
                    xyz_audit["status"],
                    "rejected_invalid_or_unreadable",
                )
                self.assertIs(xyz_audit["valid"], False)
                self.assertIs(xyz_audit["xyzin_verified_post_run"], False)
                self.assertIs(
                    xyz_audit["xyzin_ancestor_chain_verified"], False
                )
                self.assertIsNone(xyz_audit["xyzin_post_run_sha256"])
                self.assertIn(
                    "XYZIN ancestor chain verification failed before read",
                    str(xyz_audit["xyzin_verification_error"]),
                )
                self.assertIn(
                    f"Ancestor directory was replaced by a symlink: {e2e_state['inputs_dir']}",
                    str(xyz_audit["xyzin_verification_error"]),
                )
                self._assert_all_scientific_admission_flags_false(doc)

            # Independently recheck all 5 files in both the parked original inputs directory
            # and the outside target directory after leaving spy scope.
            for bname in expected_staged_basenames:
                p_file = e2e_state["parked_inp"] / bname
                p_st = os.lstat(p_file)
                p_rec = e2e_state["parked_records"][bname]
                self.assertEqual(
                    (int(p_st.st_dev), int(p_st.st_ino)), p_rec["dev_ino"]
                )
                p_raw = p_file.read_bytes()
                self.assertEqual(p_raw, p_rec["bytes"])
                self.assertEqual(_sha256_bytes(p_raw), p_rec["sha256"])
                self.assertEqual(len(p_raw), p_rec["size_bytes"])

                o_file = outside_e2e_inputs_dir / bname
                o_st = os.lstat(o_file)
                o_rec = e2e_state["outside_records"][bname]
                self.assertEqual(
                    (int(o_st.st_dev), int(o_st.st_ino)), o_rec["dev_ino"]
                )
                o_raw = o_file.read_bytes()
                self.assertEqual(o_raw, o_rec["bytes"])
                self.assertEqual(_sha256_bytes(o_raw), o_rec["sha256"])
                self.assertEqual(len(o_raw), o_rec["size_bytes"])

    def test_unusable_owned_child_dir_falls_back_to_surviving_admitted_parent(
        self,
    ) -> None:
        # Subtest 1: Real OS chmod 0o555 on owned child refmac_dir, restoring mode in finally.
        with self.subTest(mode="real_os_chmod_unwritable_child"):
            ev_root = self.repo_root.parent / "unwritable_child_chmod_root"
            refmac_dir = ev_root / "refmac"
            parent_retention_dir = ev_root / "refmac_parent_retention"
            refmac_dir.mkdir(parents=True)
            parent_retention_dir.mkdir(parents=True)

            child_baseline = onesar_refmac._capture_directory_identity_baseline(
                refmac_dir, evidence_root=ev_root
            )
            parent_baseline = onesar_refmac._capture_directory_identity_baseline(
                parent_retention_dir, evidence_root=ev_root
            )
            orig_mode = child_baseline["mode"]

            try:
                os.chmod(refmac_dir, 0o555)
                dir_status = onesar_refmac._verify_refmac_directory_post_run(
                    refmac_dir,
                    refmac_dir_baseline=child_baseline,
                )
                # Directory verification checks identity, not write permission probe.
                self.assertIs(dir_status["identity_verified"], True)
                self.assertIs(dir_status["mode_changed"], True)
                self.assertIs(dir_status["writable_post_run"], True)

                parent_status = onesar_refmac._verify_refmac_directory_post_run(
                    parent_retention_dir,
                    refmac_dir_baseline=parent_baseline,
                )
                payload = {"schema_version": 1, "case": "chmod_0555_child"}
                child_failures: list[dict[str, Any]] = []
                persist_causes: list[Exception] = []
                child_causes: list[Exception | None] = []
                parent_causes: list[Exception | None] = []
                fallback_state: dict[str, Any] = {}
                target_path = refmac_dir / "refmac_manifest.json"

                artifact = onesar_refmac._persist_collector_json_with_fallback(
                    payload,
                    target_path,
                    root=refmac_dir,
                    parent_retention_dir=parent_retention_dir,
                    parent_retention_dir_baseline=parent_baseline,
                    parent_retention_dir_status=parent_status,
                    verified_root_fallback_state=fallback_state,
                    refmac_dir_status=dir_status,
                    child_dir_persistence_failures=child_failures,
                    caught_persistence_exceptions=persist_causes,
                    child_dir_persistence_causes=child_causes,
                    parent_retention_dir_cause_sink=parent_causes,
                )

                if artifact.get("fallback_for_unwritable_or_damaged_child_dir"):
                    self.assertIs(dir_status["identity_verified"], True)
                    self.assertIs(dir_status["writable_post_run"], False)
                    self.assertEqual(
                        dir_status["write_exception_type"], "PermissionError"
                    )
                    self.assertIn(
                        dir_status["write_errno"], (errno.EACCES, errno.EPERM)
                    )
                    self.assertEqual(len(child_failures), 1)
                    self.assertIs(
                        child_failures[0]["attempted_write_in_child_dir"], True
                    )
                    self.assertEqual(
                        child_failures[0]["exception_type"], "PermissionError"
                    )
                    self.assertEqual(len(child_causes), 1)
                    self.assertIsInstance(child_causes[0], PermissionError)
                    self.assertIs(child_causes[0], persist_causes[0])
                    self.assertEqual(
                        artifact["actual_retention_anchor_kind"],
                        "parent_retention_dir",
                    )
                    self.assertEqual(
                        artifact["actual_retention_anchor_dir"],
                        str(parent_retention_dir),
                    )
                    self.assertFalse(os.path.lexists(target_path))
                    reopened = self._reopen_and_verify_json_artifact(artifact)
                    self.assertEqual(reopened, payload)
                else:
                    # Privileged execution (e.g. root) bypassed mode 0o555; still verify artifact integrity.
                    reopened = self._reopen_and_verify_json_artifact(artifact)
                    self.assertEqual(reopened, payload)
            finally:
                os.chmod(refmac_dir, orig_mode)

        # Subtest 2: Explicitly labelled fault-injection at the child write boundary to verify
        # PermissionError cause retention even if OS chmod refusal is bypassed under privileged execution.
        with self.subTest(mode="labelled_injected_permission_error_propagation"):
            ev_root = self.repo_root.parent / "unwritable_child_injected_root"
            refmac_dir = ev_root / "refmac"
            parent_retention_dir = ev_root / "refmac_parent_retention"
            refmac_dir.mkdir(parents=True)
            parent_retention_dir.mkdir(parents=True)

            child_baseline = onesar_refmac._capture_directory_identity_baseline(
                refmac_dir, evidence_root=ev_root
            )
            parent_baseline = onesar_refmac._capture_directory_identity_baseline(
                parent_retention_dir, evidence_root=ev_root
            )
            dir_status = onesar_refmac._verify_refmac_directory_post_run(
                refmac_dir, refmac_dir_baseline=child_baseline
            )
            parent_status = onesar_refmac._verify_refmac_directory_post_run(
                parent_retention_dir, refmac_dir_baseline=parent_baseline
            )

            injected_perm_exc = PermissionError(
                errno.EACCES,
                "Explicitly labelled injected PermissionError in child refmac_dir",
                str(refmac_dir / "refmac_manifest.json"),
            )
            real_write_helper = (
                onesar_refmac._write_json_with_sibling_collision_fallback
            )

            def _fault_inject_child_write(
                payload_arg: Any, target_arg: Path, *, root: Path
            ) -> dict[str, Any]:
                if Path(os.path.abspath(os.fspath(root))) == Path(
                    os.path.abspath(os.fspath(refmac_dir))
                ):
                    raise injected_perm_exc
                return real_write_helper(payload_arg, target_arg, root=root)

            payload = {"schema_version": 1, "case": "injected_child_eacces"}
            child_failures: list[dict[str, Any]] = []
            persist_causes: list[Exception] = []
            child_causes: list[Exception | None] = []
            parent_causes: list[Exception | None] = []
            fallback_state: dict[str, Any] = {}

            with patch(
                "onesar_refmac._write_json_with_sibling_collision_fallback",
                side_effect=_fault_inject_child_write,
            ):
                artifact = onesar_refmac._persist_collector_json_with_fallback(
                    payload,
                    refmac_dir / "refmac_manifest.json",
                    root=refmac_dir,
                    parent_retention_dir=parent_retention_dir,
                    parent_retention_dir_baseline=parent_baseline,
                    parent_retention_dir_status=parent_status,
                    verified_root_fallback_state=fallback_state,
                    refmac_dir_status=dir_status,
                    child_dir_persistence_failures=child_failures,
                    caught_persistence_exceptions=persist_causes,
                    child_dir_persistence_causes=child_causes,
                    parent_retention_dir_cause_sink=parent_causes,
                )

            self.assertIs(dir_status["identity_verified"], True)
            self.assertIs(dir_status["writable_post_run"], False)
            self.assertEqual(
                dir_status["write_exception_type"], "PermissionError"
            )
            self.assertEqual(dir_status["write_errno"], errno.EACCES)
            self.assertEqual(len(child_failures), 1)
            self.assertIs(
                child_failures[0]["attempted_write_in_child_dir"], True
            )
            self.assertIs(child_causes[0], injected_perm_exc)
            self.assertIs(persist_causes[0], injected_perm_exc)
            self.assertEqual(
                artifact["actual_retention_anchor_kind"],
                "parent_retention_dir",
            )
            self.assertEqual(
                self._reopen_and_verify_json_artifact(artifact), payload
            )

    def test_rejected_parent_replacement_and_successful_recheck_after_restoring_original_inode(
        self,
    ) -> None:
        ev_root = self.repo_root.parent / "parent_replace_and_restore_root"
        refmac_dir = ev_root / "refmac"
        parent_retention_dir = ev_root / "refmac_parent_retention"
        refmac_dir.mkdir(parents=True)
        parent_retention_dir.mkdir(parents=True)

        orig_parent_marker = parent_retention_dir / "admitted_parent_marker.txt"
        orig_parent_marker_bytes = b"ORIGINAL_ADMITTED_PARENT_MARKER_BYTES\n"
        orig_parent_marker.write_bytes(orig_parent_marker_bytes)
        orig_marker_st = os.lstat(orig_parent_marker)
        orig_marker_dev_ino = (
            int(orig_marker_st.st_dev),
            int(orig_marker_st.st_ino),
        )
        orig_marker_sha256 = _sha256_bytes(orig_parent_marker_bytes)

        child_baseline = onesar_refmac._capture_directory_identity_baseline(
            refmac_dir, evidence_root=ev_root
        )
        parent_baseline = onesar_refmac._capture_directory_identity_baseline(
            parent_retention_dir, evidence_root=ev_root
        )

        # Make child unavailable by renaming it aside, and park the original parent_retention_dir
        # while creating a replacement directory at parent_retention_dir.
        parked_child = ev_root / "parked_refmac_child"
        parked_orig_parent = ev_root / "parked_orig_parent_retention"
        moved_replacement_parent = ev_root / "moved_replacement_parent_retention"
        os.replace(refmac_dir, parked_child)
        os.replace(parent_retention_dir, parked_orig_parent)

        try:
            parent_retention_dir.mkdir()
            rep_marker = parent_retention_dir / "replacement_parent_marker.txt"
            rep_marker_bytes = b"REPLACEMENT_PARENT_MARKER_BYTES\n"
            rep_marker.write_bytes(rep_marker_bytes)
            rep_parent_st = os.lstat(parent_retention_dir)
            self.assertNotEqual(
                (int(rep_parent_st.st_dev), int(rep_parent_st.st_ino)),
                (parent_baseline["dev"], parent_baseline["ino"]),
            )

            child_causes: list[Exception] = []
            parent_init_causes: list[Exception] = []
            child_status = onesar_refmac._verify_refmac_directory_post_run(
                refmac_dir,
                refmac_dir_baseline=child_baseline,
                caught_exceptions=child_causes,
            )
            parent_status = onesar_refmac._verify_refmac_directory_post_run(
                parent_retention_dir,
                refmac_dir_baseline=parent_baseline,
                caught_exceptions=parent_init_causes,
            )
            self.assertIs(child_status["identity_verified"], False)
            self.assertIs(parent_status["identity_verified"], False)
            self.assertIn("inode changed", str(parent_status["error"]))

            # Observe _write_json_with_sibling_collision_fallback during persistence while parent is replaced.
            real_write_helper = (
                onesar_refmac._write_json_with_sibling_collision_fallback
            )
            attempted_write_destinations: list[Path] = []

            def _spy_write_helper(
                payload_arg: Any, target_arg: Path, *, root: Path
            ) -> dict[str, Any]:
                attempted_write_destinations.append(
                    Path(os.path.abspath(os.fspath(target_arg)))
                )
                return real_write_helper(payload_arg, target_arg, root=root)

            payload_1 = {"schema_version": 1, "phase": "while_parent_replaced"}
            child_failures: list[dict[str, Any]] = []
            persist_causes: list[Exception] = []
            child_persist_causes: list[Exception | None] = [child_causes[0]]
            parent_cause_sink: list[Exception | None] = []
            fallback_state: dict[str, Any] = {}

            with patch(
                "onesar_refmac._write_json_with_sibling_collision_fallback",
                side_effect=_spy_write_helper,
            ):
                artifact_1 = onesar_refmac._persist_collector_json_with_fallback(
                    payload_1,
                    refmac_dir / "artifact_1.json",
                    root=refmac_dir,
                    parent_retention_dir=parent_retention_dir,
                    parent_retention_dir_baseline=parent_baseline,
                    parent_retention_dir_status=parent_status,
                    verified_root_fallback_state=fallback_state,
                    refmac_dir_status=child_status,
                    child_dir_persistence_failures=child_failures,
                    caught_persistence_exceptions=persist_causes,
                    child_dir_persistence_causes=child_persist_causes,
                    parent_retention_dir_cause_sink=parent_cause_sink,
                )

            # No fallback write was attempted inside the rejected child or inside the replacement parent.
            for dest in attempted_write_destinations:
                self.assertFalse(dest.is_relative_to(refmac_dir))
                self.assertFalse(dest.is_relative_to(parent_retention_dir))

            self.assertEqual(
                [p.name for p in parent_retention_dir.iterdir()],
                ["replacement_parent_marker.txt"],
            )
            self.assertEqual(rep_marker.read_bytes(), rep_marker_bytes)

            self.assertIs(
                artifact_1["fallback_for_unwritable_or_damaged_child_dir"],
                True,
            )
            self.assertIs(
                artifact_1[
                    "fallback_for_damaged_or_replaced_parent_retention_dir"
                ],
                True,
            )
            self.assertEqual(
                artifact_1["actual_retention_anchor_kind"],
                "verified_evidence_root_exclusive_dir",
            )
            self.assertEqual(
                self._reopen_and_verify_json_artifact(artifact_1), payload_1
            )
            self.assertEqual(len(parent_cause_sink), 1)
            self.assertIsInstance(parent_cause_sink[0], ValueError)

            captured_rejected_parent_status = dict(parent_status)
            captured_rejected_parent_cause = parent_cause_sink[0]
            self.assertIs(
                captured_rejected_parent_status["identity_verified"], False
            )

            # Now move the replacement parent aside and restore the original owned parent inode.
            os.replace(parent_retention_dir, moved_replacement_parent)
            os.replace(parked_orig_parent, parent_retention_dir)

            restored_parent_st = os.lstat(parent_retention_dir)
            self.assertEqual(
                (int(restored_parent_st.st_dev), int(restored_parent_st.st_ino)),
                (parent_baseline["dev"], parent_baseline["ino"]),
            )
            restored_marker_st = os.lstat(orig_parent_marker)
            self.assertEqual(
                (int(restored_marker_st.st_dev), int(restored_marker_st.st_ino)),
                orig_marker_dev_ino,
            )
            self.assertEqual(
                _sha256_bytes(orig_parent_marker.read_bytes()),
                orig_marker_sha256,
            )

            # Call persistence again with the same original baseline and previously rejected status dict.
            payload_2 = {
                "schema_version": 1,
                "phase": "after_original_parent_inode_restored",
            }
            artifact_2 = onesar_refmac._persist_collector_json_with_fallback(
                payload_2,
                refmac_dir / "artifact_2.json",
                root=refmac_dir,
                parent_retention_dir=parent_retention_dir,
                parent_retention_dir_baseline=parent_baseline,
                parent_retention_dir_status=parent_status,
                verified_root_fallback_state={},
                refmac_dir_status=child_status,
                child_dir_persistence_failures=child_failures,
                caught_persistence_exceptions=persist_causes,
                child_dir_persistence_causes=child_persist_causes,
                parent_retention_dir_cause_sink=parent_cause_sink,
            )

            # Live parent recheck succeeds, refreshes status, clears stale identity error, and sets cause sink to [None].
            self.assertIs(parent_status["identity_verified"], True)
            self.assertIs(parent_status["writable_post_run"], True)
            self.assertIsNone(parent_status["error"])
            self.assertIsNone(parent_status["exception_type"])
            self.assertEqual(parent_cause_sink, [None])
            self.assertEqual(
                artifact_2["actual_retention_anchor_kind"],
                "parent_retention_dir",
            )
            self.assertEqual(
                artifact_2["actual_retention_anchor_dir"],
                str(parent_retention_dir),
            )
            self.assertNotIn(
                "fallback_for_damaged_or_replaced_parent_retention_dir",
                artifact_2,
            )
            self.assertEqual(
                self._reopen_and_verify_json_artifact(artifact_2), payload_2
            )
            # Earlier captured rejection record and cause remain distinct and intact.
            self.assertIs(
                captured_rejected_parent_status["identity_verified"], False
            )
            self.assertIsInstance(captured_rejected_parent_cause, ValueError)
        finally:
            if os.path.lexists(parked_orig_parent) and not os.path.lexists(
                parent_retention_dir
            ):
                os.replace(parked_orig_parent, parent_retention_dir)

    def test_whole_root_replacement_rejects_scan_and_returns_truthful_memory_only_refusal(
        self,
    ) -> None:
        container_dir = self.repo_root.parent / "whole_root_replacement_container"
        ev_root = container_dir / "evidence_root"
        refmac_dir = ev_root / "refmac"
        parent_retention_dir = ev_root / "refmac_parent_retention"
        refmac_dir.mkdir(parents=True)
        parent_retention_dir.mkdir(parents=True)

        orig_child_file = refmac_dir / "orig_child_marker.txt"
        orig_child_bytes = b"ORIGINAL_CHILD_MARKER_BYTES\n"
        orig_child_file.write_bytes(orig_child_bytes)
        orig_child_file_st = os.lstat(orig_child_file)
        orig_child_file_dev_ino = (
            int(orig_child_file_st.st_dev),
            int(orig_child_file_st.st_ino),
        )

        child_baseline = onesar_refmac._capture_directory_identity_baseline(
            refmac_dir, evidence_root=ev_root
        )
        parent_baseline = onesar_refmac._capture_directory_identity_baseline(
            parent_retention_dir, evidence_root=ev_root
        )

        # Park the entire original evidence_root aside so its inodes remain alive,
        # and create a replacement directory tree at the same lexical path.
        parked_root = container_dir / "parked_original_evidence_root"
        os.replace(ev_root, parked_root)

        refmac_dir.mkdir(parents=True)
        parent_retention_dir.mkdir(parents=True)
        rep_child_marker = refmac_dir / "replacement_child_marker.txt"
        rep_child_marker_bytes = b"REPLACEMENT_CHILD_MARKER_BYTES\n"
        rep_child_marker.write_bytes(rep_child_marker_bytes)
        rep_parent_marker = (
            parent_retention_dir / "replacement_parent_marker.txt"
        )
        rep_parent_marker_bytes = b"REPLACEMENT_PARENT_MARKER_BYTES\n"
        rep_parent_marker.write_bytes(rep_parent_marker_bytes)

        rep_root_st = os.lstat(ev_root)
        self.assertNotEqual(
            (int(rep_root_st.st_dev), int(rep_root_st.st_ino)),
            (
                child_baseline["evidence_root_dev"],
                child_baseline["evidence_root_ino"],
            ),
        )

        real_scandir = os.scandir
        real_inspect = onesar_refmac._inspect_output_artifact
        real_write_helper = (
            onesar_refmac._write_json_with_sibling_collision_fallback
        )
        scandir_calls: list[str] = []
        inspect_calls: list[str] = []
        write_calls: list[str] = []

        def _spy_scandir(path: Any = ".") -> Any:
            scandir_calls.append(os.path.abspath(os.fspath(path)))
            return real_scandir(path)

        def _spy_inspect(path: Path, **kwargs: Any) -> dict[str, Any]:
            inspect_calls.append(os.path.abspath(os.fspath(path)))
            return real_inspect(path, **kwargs)

        def _spy_write(
            payload_arg: Any, target_arg: Path, *, root: Path
        ) -> dict[str, Any]:
            write_calls.append(os.path.abspath(os.fspath(target_arg)))
            return real_write_helper(payload_arg, target_arg, root=root)

        child_causes: list[Exception] = []
        parent_causes: list[Exception] = []
        scan_causes_1: list[Exception | None] = []
        scan_causes_2: list[Exception | None] = []
        persist_causes: list[Exception] = []
        child_failures: list[dict[str, Any]] = []
        retained_sink: list[dict[str, Any]] = []
        fallback_state: dict[str, Any] = {}
        payload = {
            "schema_version": 1,
            "case": "whole_root_rejected_memory_only",
        }

        with (
            patch("onesar_refmac.os.scandir", side_effect=_spy_scandir),
            patch(
                "onesar_refmac._inspect_output_artifact",
                side_effect=_spy_inspect,
            ),
            patch(
                "onesar_refmac._write_json_with_sibling_collision_fallback",
                side_effect=_spy_write,
            ),
        ):
            child_status = onesar_refmac._verify_refmac_directory_post_run(
                refmac_dir,
                refmac_dir_baseline=child_baseline,
                caught_exceptions=child_causes,
            )
            parent_status = onesar_refmac._verify_refmac_directory_post_run(
                parent_retention_dir,
                refmac_dir_baseline=parent_baseline,
                caught_exceptions=parent_causes,
            )
            scan_1 = onesar_refmac._scan_refmac_directory_entries(
                refmac_dir,
                known_paths={},
                expected_root_identity=child_baseline,
                refmac_dir_status=child_status,
                refmac_dir_initial_cause=child_causes[0],
                scandir_cause_out=scan_causes_1,
            )
            scan_2 = onesar_refmac._scan_refmac_directory_entries(
                refmac_dir,
                known_paths={},
                expected_root_identity=child_baseline,
                scandir_cause_out=scan_causes_2,
            )
            unpersisted_ref = (
                onesar_refmac._persist_collector_json_with_fallback(
                    payload,
                    refmac_dir / "refmac_manifest.json",
                    root=refmac_dir,
                    parent_retention_dir=parent_retention_dir,
                    parent_retention_dir_baseline=parent_baseline,
                    parent_retention_dir_status=parent_status,
                    verified_root_fallback_state=fallback_state,
                    allow_unpersisted_on_no_verified_anchor=True,
                    refmac_dir_status=child_status,
                    child_dir_persistence_failures=child_failures,
                    caught_persistence_exceptions=persist_causes,
                    retained_payload_sink=retained_sink,
                    child_dir_persistence_causes=[child_causes[0]],
                    parent_retention_dir_cause_sink=[],
                )
            )

        self.assertIs(child_status["identity_verified"], False)
        self.assertIn("Evidence root check failed", str(child_status["error"]))
        self.assertIs(parent_status["identity_verified"], False)
        self.assertIn("Evidence root check failed", str(parent_status["error"]))

        # No descendant scan and no write occurred beneath the rejected root/parent/child.
        self.assertEqual(scandir_calls, [])
        self.assertEqual(inspect_calls, [])
        self.assertEqual(write_calls, [])
        for scan_res in (scan_1, scan_2):
            self.assertEqual(scan_res["additional_files"], {})
            self.assertIsNotNone(scan_res["scandir_error"])
            self.assertEqual(
                scan_res["scandir_error"]["output_key"], "refmac_dir_scan"
            )

        # Truthful memory-only refusal fields and independently verified serialization digest/size.
        self.assertIsNone(unpersisted_ref["path"])
        self.assertIs(unpersisted_ref["persisted"], False)
        self.assertIs(unpersisted_ref["no_verified_anchor_available"], True)
        self.assertIsNone(unpersisted_ref["actual_retention_anchor_dir"])
        self.assertIsNone(unpersisted_ref["actual_retention_anchor_kind"])
        self.assertIsNone(unpersisted_ref["actual_retention_anchor_baseline"])
        self.assertTrue(
            isinstance(unpersisted_ref["unpersisted_reason"], str)
            and bool(unpersisted_ref["unpersisted_reason"].strip())
        )
        self.assertEqual(len(retained_sink), 1)
        self.assertEqual(retained_sink[0], payload)
        expected_serialized = (
            json.dumps(
                retained_sink[0], indent=2, sort_keys=True, allow_nan=False
            )
            + "\n"
        ).encode("utf-8")
        self.assertEqual(
            unpersisted_ref["sha256"], _sha256_bytes(expected_serialized)
        )
        self.assertEqual(
            unpersisted_ref["size_bytes"], len(expected_serialized)
        )

        # Replacement tree and container directory were not polluted by fallback directories or files.
        self.assertEqual(
            sorted(p.name for p in ev_root.iterdir()),
            ["refmac", "refmac_parent_retention"],
        )
        self.assertEqual(
            [p.name for p in refmac_dir.iterdir()],
            ["replacement_child_marker.txt"],
        )
        self.assertEqual(
            [p.name for p in parent_retention_dir.iterdir()],
            ["replacement_parent_marker.txt"],
        )
        self.assertEqual(rep_child_marker.read_bytes(), rep_child_marker_bytes)
        self.assertEqual(
            rep_parent_marker.read_bytes(), rep_parent_marker_bytes
        )
        self.assertEqual(
            sorted(p.name for p in container_dir.iterdir()),
            ["evidence_root", "parked_original_evidence_root"],
        )

        # Parked original tree and marker retain original identity and bytes.
        parked_root_st = os.lstat(parked_root)
        self.assertEqual(
            (int(parked_root_st.st_dev), int(parked_root_st.st_ino)),
            (
                child_baseline["evidence_root_dev"],
                child_baseline["evidence_root_ino"],
            ),
        )
        parked_marker = parked_root / "refmac" / "orig_child_marker.txt"
        parked_marker_st = os.lstat(parked_marker)
        self.assertEqual(
            (int(parked_marker_st.st_dev), int(parked_marker_st.st_ino)),
            orig_child_file_dev_ino,
        )
        self.assertEqual(parked_marker.read_bytes(), orig_child_bytes)

    def test_unreadable_owned_extra_file_retains_original_cause_and_restores_mode(
        self,
    ) -> None:
        ev_root = self.repo_root.parent / "unreadable_extra_file_root"
        refmac_dir = ev_root / "refmac"
        refmac_dir.mkdir(parents=True)

        known_log = refmac_dir / "1sar_refmac_ncyc0.log"
        known_log.write_bytes(b"KNOWN_LOG_BYTES\n")
        extra_name = "unexpected_extra_dump.dat"
        extra_path = refmac_dir / extra_name
        extra_bytes = b"UNREADABLE_EXTRA_FILE_KNOWN_BYTES\n"
        extra_path.write_bytes(extra_bytes)
        orig_st = os.lstat(extra_path)
        orig_mode = stat.S_IMODE(orig_st.st_mode)
        orig_dev_ino = (int(orig_st.st_dev), int(orig_st.st_ino))
        orig_sha256 = _sha256_bytes(extra_bytes)

        child_baseline = onesar_refmac._capture_directory_identity_baseline(
            refmac_dir, evidence_root=ev_root
        )

        # Subtest 1: Real OS chmod 0 on the owned extra file, restoring mode in finally.
        with self.subTest(mode="real_os_chmod_zero"):
            caught_scan: list[Exception] = []
            extra_causes: dict[str, Exception | None] = {}
            try:
                os.chmod(extra_path, 0)
                scan_res = onesar_refmac._scan_refmac_directory_entries(
                    refmac_dir,
                    known_paths={"log": known_log},
                    caught_exceptions=caught_scan,
                    expected_root_identity=child_baseline,
                    additional_file_causes_out=extra_causes,
                )
            finally:
                os.chmod(extra_path, orig_mode)

            self.assertIsNone(scan_res["scandir_error"])
            self.assertIn(extra_name, scan_res["additional_files"])
            extra_rec = scan_res["additional_files"][extra_name]
            if extra_rec.get("error") is not None:
                self.assertIs(extra_rec["exists"], True)
                self.assertIs(extra_rec["is_regular_file"], True)
                self.assertIs(extra_rec["is_symlink"], False)
                self.assertIs(extra_rec["within_refmac_dir"], True)
                self.assertIsNone(extra_rec["sha256"])
                self.assertEqual(extra_rec["size_bytes"], len(extra_bytes))
                self.assertEqual(
                    extra_rec["exception_type"], "PermissionError"
                )
                self.assertIn(
                    extra_rec["errno"], (errno.EACCES, errno.EPERM)
                )
                self.assertEqual(len(scan_res["inspection_errors"]), 1)
                self.assertEqual(
                    scan_res["inspection_errors"][0]["entry_name"], extra_name
                )
                cause_obj = extra_causes.get(extra_name)
                self.assertIsNotNone(cause_obj)
                self.assertIsInstance(cause_obj, PermissionError)
                self.assertIs(cause_obj, caught_scan[0])
                self.assertEqual(
                    extra_rec["exception_type"], type(cause_obj).__name__
                )
                self.assertEqual(
                    extra_rec["exception_message"], str(cause_obj)
                )
                self.assertEqual(extra_rec["errno"], cause_obj.errno)

            # After restoring mode in finally, independently reread and hash the owned extra file.
            restored_st = os.lstat(extra_path)
            self.assertEqual(
                (int(restored_st.st_dev), int(restored_st.st_ino)),
                orig_dev_ino,
            )
            self.assertEqual(
                _sha256_bytes(extra_path.read_bytes()), orig_sha256
            )

        # Subtest 2: Explicitly labelled read-boundary fault injection for extra_path so exact
        # exception-object retention is verified even when running under privileged execution.
        with self.subTest(mode="labelled_injected_read_permission_error"):
            injected_read_exc = PermissionError(
                errno.EACCES,
                "Explicitly labelled injected PermissionError reading extra file",
                str(extra_path),
            )
            real_read_bytes = Path.read_bytes

            def _fault_inject_extra_read(path_self: Path) -> bytes:
                if os.path.abspath(os.fspath(path_self)) == os.path.abspath(
                    os.fspath(extra_path)
                ):
                    raise injected_read_exc
                return real_read_bytes(path_self)

            caught_inj: list[Exception] = []
            extra_causes_inj: dict[str, Exception | None] = {}
            with patch.object(Path, "read_bytes", _fault_inject_extra_read):
                scan_inj = onesar_refmac._scan_refmac_directory_entries(
                    refmac_dir,
                    known_paths={"log": known_log},
                    caught_exceptions=caught_inj,
                    expected_root_identity=child_baseline,
                    additional_file_causes_out=extra_causes_inj,
                )

            self.assertIsNone(scan_inj["scandir_error"])
            rec_inj = scan_inj["additional_files"][extra_name]
            self.assertIs(rec_inj["exists"], True)
            self.assertIs(rec_inj["is_regular_file"], True)
            self.assertIs(rec_inj["within_refmac_dir"], True)
            self.assertIsNone(rec_inj["sha256"])
            self.assertEqual(rec_inj["size_bytes"], len(extra_bytes))
            self.assertEqual(rec_inj["exception_type"], "PermissionError")
            self.assertEqual(rec_inj["exception_message"], str(injected_read_exc))
            self.assertEqual(rec_inj["errno"], errno.EACCES)
            self.assertEqual(len(scan_inj["inspection_errors"]), 1)
            self.assertEqual(
                scan_inj["inspection_errors"][0]["entry_name"], extra_name
            )
            self.assertIs(extra_causes_inj[extra_name], injected_read_exc)
            self.assertIs(caught_inj[0], injected_read_exc)

    def test_atomic_write_new_json_file_canonical_and_preexisting_temp_collisions(
        self,
    ) -> None:
        """Case 33 (Fixtures 1a, 1b): _atomic_write_new_json_file preserves canonical and pre-existing temporary markers on collision."""
        pid = os.getpid()

        with self.subTest(fixture="1a_atomic_canonical_file"):
            root_1a = (
                self.repo_root.parent
                / f"atomic_canonical_collision_1a_{pid}"
            )
            root_1a.mkdir(parents=True, exist_ok=True)
            target_1a = root_1a / "record.json"
            tmp_1a = root_1a / f".record.json.tmp.{pid}"
            marker_1a_bytes = b'{"marker": "canonical-1a", "preserve": true}\n'
            target_1a.write_bytes(marker_1a_bytes)
            orig_1a_st = os.lstat(target_1a)
            orig_1a_sha = _sha256_bytes(marker_1a_bytes)

            factory_calls_1a: list[Path | None] = []

            def _factory_1a(dest: Path | None) -> Mapping[str, Any]:
                factory_calls_1a.append(dest)
                return {"unexpected": True, "destination_path": str(dest)}

            with self.assertRaises(FileExistsError):
                onesar_refmac._atomic_write_new_json_file(
                    _factory_1a,
                    target_1a,
                    root=root_1a,
                )

            self.assertEqual(factory_calls_1a, [])
            self.assertFalse(os.path.lexists(tmp_1a))
            after_1a_st = os.lstat(target_1a)
            self.assertTrue(stat.S_ISREG(after_1a_st.st_mode))
            self.assertEqual(
                (int(after_1a_st.st_dev), int(after_1a_st.st_ino)),
                (int(orig_1a_st.st_dev), int(orig_1a_st.st_ino)),
            )
            self.assertEqual(target_1a.read_bytes(), marker_1a_bytes)
            self.assertEqual(
                _sha256_bytes(target_1a.read_bytes()), orig_1a_sha
            )

        with self.subTest(fixture="1b_atomic_preexisting_temp"):
            root_1b = (
                self.repo_root.parent
                / f"atomic_preexisting_temp_1b_{pid}"
            )
            root_1b.mkdir(parents=True, exist_ok=True)
            target_1b = root_1b / "record.json"
            tmp_1b = root_1b / f".record.json.tmp.{pid}"
            tmp_marker_bytes = (
                b'{"marker": "preexisting-temp-1b", "unowned": true}\n'
            )
            tmp_1b.write_bytes(tmp_marker_bytes)
            orig_tmp_st = os.lstat(tmp_1b)
            orig_tmp_sha = _sha256_bytes(tmp_marker_bytes)

            factory_calls_1b: list[Path | None] = []

            def _factory_1b(dest: Path | None) -> Mapping[str, Any]:
                factory_calls_1b.append(dest)
                return {"unexpected": True, "destination_path": str(dest)}

            with self.assertRaises(FileExistsError):
                onesar_refmac._atomic_write_new_json_file(
                    _factory_1b,
                    target_1b,
                    root=root_1b,
                )

            self.assertEqual(factory_calls_1b, [])
            self.assertFalse(os.path.lexists(target_1b))
            self.assertTrue(os.path.lexists(tmp_1b))
            after_tmp_st = os.lstat(tmp_1b)
            self.assertTrue(stat.S_ISREG(after_tmp_st.st_mode))
            self.assertEqual(
                (int(after_tmp_st.st_dev), int(after_tmp_st.st_ino)),
                (int(orig_tmp_st.st_dev), int(orig_tmp_st.st_ino)),
            )
            self.assertEqual(tmp_1b.read_bytes(), tmp_marker_bytes)
            self.assertEqual(
                _sha256_bytes(tmp_1b.read_bytes()), orig_tmp_sha
            )

    def test_write_json_with_sibling_collision_fallback_regular_and_symlink_collisions(
        self,
    ) -> None:
        """Case 34 (Fixtures 2, 3): _write_json_with_sibling_collision_fallback handles canonical/sibling regular and symlink collisions across target and temp paths."""
        pid = os.getpid()

        with self.subTest(
            fixture="2_child_canonical_symlink_and_occupied_first_sibling"
        ):
            root_2 = (
                self.repo_root.parent
                / f"sibling_fallback_2_{pid}"
            )
            markers_2 = (
                self.repo_root.parent
                / f"sibling_fallback_2_markers_{pid}"
            )
            root_2.mkdir(parents=True, exist_ok=True)
            markers_2.mkdir(parents=True, exist_ok=True)

            sym_target_2 = markers_2 / "canonical_symlink_target.json"
            sym_target_2_bytes = (
                b'{"marker": "canonical-symlink-target-2", "preserve": true}\n'
            )
            sym_target_2.write_bytes(sym_target_2_bytes)
            orig_sym_target_2_st = os.lstat(sym_target_2)
            orig_sym_target_2_sha = _sha256_bytes(sym_target_2_bytes)

            record_2 = root_2 / "record.json"
            os.symlink(sym_target_2, record_2)
            orig_record_2_linktext = os.readlink(record_2)
            orig_record_2_lstat = os.lstat(record_2)

            first_sib_2 = root_2 / f"record.parent.{pid}.json"
            first_sib_2_bytes = (
                b'{"marker": "occupied-first-sibling-2", "preserve": true}\n'
            )
            first_sib_2.write_bytes(first_sib_2_bytes)
            orig_first_sib_2_st = os.lstat(first_sib_2)
            orig_first_sib_2_sha = _sha256_bytes(first_sib_2_bytes)

            second_sib_2 = root_2 / f"record.parent.{pid}.1.json"
            factory_calls_2: list[Path | None] = []

            def _factory_2(dest: Path | None) -> Mapping[str, Any]:
                factory_calls_2.append(dest)
                return {
                    "fixture": "child",
                    "destination_path": str(dest),
                }

            art_2 = onesar_refmac._write_json_with_sibling_collision_fallback(
                _factory_2,
                record_2,
                root=root_2,
            )

            self.assertEqual(factory_calls_2, [second_sib_2])
            self.assertEqual(art_2["path"], str(second_sib_2))
            self.assertEqual(
                art_2["fallback_for_preexisting_path"], str(record_2)
            )
            reopened_2 = self._reopen_and_verify_json_artifact(art_2)
            self.assertEqual(
                reopened_2,
                {
                    "fixture": "child",
                    "destination_path": str(second_sib_2),
                },
            )

            self.assertTrue(os.path.islink(record_2))
            self.assertEqual(os.readlink(record_2), orig_record_2_linktext)
            after_record_2_lstat = os.lstat(record_2)
            self.assertEqual(
                (
                    int(after_record_2_lstat.st_dev),
                    int(after_record_2_lstat.st_ino),
                ),
                (
                    int(orig_record_2_lstat.st_dev),
                    int(orig_record_2_lstat.st_ino),
                ),
            )
            after_sym_target_2_st = os.lstat(sym_target_2)
            self.assertEqual(
                (
                    int(after_sym_target_2_st.st_dev),
                    int(after_sym_target_2_st.st_ino),
                ),
                (
                    int(orig_sym_target_2_st.st_dev),
                    int(orig_sym_target_2_st.st_ino),
                ),
            )
            self.assertEqual(sym_target_2.read_bytes(), sym_target_2_bytes)
            self.assertEqual(
                _sha256_bytes(sym_target_2.read_bytes()),
                orig_sym_target_2_sha,
            )

            after_first_sib_2_st = os.lstat(first_sib_2)
            self.assertTrue(stat.S_ISREG(after_first_sib_2_st.st_mode))
            self.assertEqual(
                (
                    int(after_first_sib_2_st.st_dev),
                    int(after_first_sib_2_st.st_ino),
                ),
                (
                    int(orig_first_sib_2_st.st_dev),
                    int(orig_first_sib_2_st.st_ino),
                ),
            )
            self.assertEqual(first_sib_2.read_bytes(), first_sib_2_bytes)
            self.assertEqual(
                _sha256_bytes(first_sib_2.read_bytes()), orig_first_sib_2_sha
            )
            for cand_tmp in (
                root_2 / f".record.json.tmp.{pid}",
                root_2 / f".record.parent.{pid}.json.tmp.{pid}",
                root_2 / f".record.parent.{pid}.1.json.tmp.{pid}",
            ):
                self.assertFalse(os.path.lexists(cand_tmp))

        with self.subTest(
            fixture="3_temp_symlink_and_occupied_sibling_temp"
        ):
            root_3 = (
                self.repo_root.parent
                / f"sibling_fallback_3_{pid}"
            )
            markers_3 = (
                self.repo_root.parent
                / f"sibling_fallback_3_markers_{pid}"
            )
            root_3.mkdir(parents=True, exist_ok=True)
            markers_3.mkdir(parents=True, exist_ok=True)

            record_3 = root_3 / "record.json"
            first_sib_3 = root_3 / f"record.parent.{pid}.json"
            second_sib_3 = root_3 / f"record.parent.{pid}.1.json"

            tmp_sym_target_3 = (
                markers_3 / "canonical_tmp_symlink_target_3.json"
            )
            tmp_sym_target_3_bytes = (
                b'{"marker": "canonical-tmp-symlink-target-3", "preserve": true}\n'
            )
            tmp_sym_target_3.write_bytes(tmp_sym_target_3_bytes)
            orig_tmp_sym_target_3_st = os.lstat(tmp_sym_target_3)
            orig_tmp_sym_target_3_sha = _sha256_bytes(tmp_sym_target_3_bytes)

            canonical_tmp_3 = root_3 / f".record.json.tmp.{pid}"
            os.symlink(tmp_sym_target_3, canonical_tmp_3)
            orig_canonical_tmp_3_linktext = os.readlink(canonical_tmp_3)
            orig_canonical_tmp_3_lstat = os.lstat(canonical_tmp_3)

            first_sib_tmp_3 = (
                root_3 / f".record.parent.{pid}.json.tmp.{pid}"
            )
            first_sib_tmp_3_bytes = (
                b'{"marker": "first-sibling-temp-3", "preserve": true}\n'
            )
            first_sib_tmp_3.write_bytes(first_sib_tmp_3_bytes)
            orig_first_sib_tmp_3_st = os.lstat(first_sib_tmp_3)
            orig_first_sib_tmp_3_sha = _sha256_bytes(first_sib_tmp_3_bytes)

            factory_calls_3: list[Path | None] = []

            def _factory_3(dest: Path | None) -> Mapping[str, Any]:
                factory_calls_3.append(dest)
                return {
                    "fixture": "temp-collision",
                    "destination_path": str(dest),
                }

            art_3 = onesar_refmac._write_json_with_sibling_collision_fallback(
                _factory_3,
                record_3,
                root=root_3,
            )

            self.assertEqual(factory_calls_3, [second_sib_3])
            self.assertEqual(art_3["path"], str(second_sib_3))
            self.assertEqual(
                art_3["fallback_for_preexisting_path"], str(record_3)
            )
            self.assertFalse(os.path.lexists(record_3))
            self.assertFalse(os.path.lexists(first_sib_3))
            self.assertFalse(
                os.path.lexists(
                    root_3 / f".record.parent.{pid}.1.json.tmp.{pid}"
                )
            )

            reopened_3 = self._reopen_and_verify_json_artifact(art_3)
            self.assertEqual(
                reopened_3,
                {
                    "fixture": "temp-collision",
                    "destination_path": str(second_sib_3),
                },
            )

            self.assertTrue(os.path.islink(canonical_tmp_3))
            self.assertEqual(
                os.readlink(canonical_tmp_3), orig_canonical_tmp_3_linktext
            )
            after_canonical_tmp_3_lstat = os.lstat(canonical_tmp_3)
            self.assertEqual(
                (
                    int(after_canonical_tmp_3_lstat.st_dev),
                    int(after_canonical_tmp_3_lstat.st_ino),
                ),
                (
                    int(orig_canonical_tmp_3_lstat.st_dev),
                    int(orig_canonical_tmp_3_lstat.st_ino),
                ),
            )
            after_tmp_sym_target_3_st = os.lstat(tmp_sym_target_3)
            self.assertEqual(
                (
                    int(after_tmp_sym_target_3_st.st_dev),
                    int(after_tmp_sym_target_3_st.st_ino),
                ),
                (
                    int(orig_tmp_sym_target_3_st.st_dev),
                    int(orig_tmp_sym_target_3_st.st_ino),
                ),
            )
            self.assertEqual(
                tmp_sym_target_3.read_bytes(), tmp_sym_target_3_bytes
            )
            self.assertEqual(
                _sha256_bytes(tmp_sym_target_3.read_bytes()),
                orig_tmp_sym_target_3_sha,
            )

            after_first_sib_tmp_3_st = os.lstat(first_sib_tmp_3)
            self.assertTrue(stat.S_ISREG(after_first_sib_tmp_3_st.st_mode))
            self.assertEqual(
                (
                    int(after_first_sib_tmp_3_st.st_dev),
                    int(after_first_sib_tmp_3_st.st_ino),
                ),
                (
                    int(orig_first_sib_tmp_3_st.st_dev),
                    int(orig_first_sib_tmp_3_st.st_ino),
                ),
            )
            self.assertEqual(
                first_sib_tmp_3.read_bytes(), first_sib_tmp_3_bytes
            )
            self.assertEqual(
                _sha256_bytes(first_sib_tmp_3.read_bytes()),
                orig_first_sib_tmp_3_sha,
            )

    def test_persist_collector_json_with_fallback_child_write_denial_and_no_anchor_memory(
        self,
    ) -> None:
        """Case 35 (Fixtures 4, 5): _persist_collector_json_with_fallback handles child write denial with parent collisions, no-anchor memory, and immutable MappingProxyType caller payloads."""
        pid = os.getpid()

        with self.subTest(
            fixture="4_selected_child_write_denial_parent_collisions_immutable_mappingproxy"
        ):
            evidence_root_4 = (
                self.repo_root.parent
                / f"persist_child_write_denial_4_{pid}"
            )
            child_dir_4 = evidence_root_4 / "refmac"
            parent_dir_4 = evidence_root_4 / "refmac_parent_retention"
            markers_4 = (
                self.repo_root.parent
                / f"persist_child_write_denial_4_markers_{pid}"
            )
            child_dir_4.mkdir(parents=True, exist_ok=True)
            parent_dir_4.mkdir(parents=True, exist_ok=True)
            markers_4.mkdir(parents=True, exist_ok=True)

            child_baseline_4 = (
                onesar_refmac._capture_directory_identity_baseline(
                    child_dir_4, evidence_root=evidence_root_4
                )
            )
            parent_baseline_4 = (
                onesar_refmac._capture_directory_identity_baseline(
                    parent_dir_4, evidence_root=evidence_root_4
                )
            )
            child_status_4 = onesar_refmac._verify_refmac_directory_post_run(
                child_dir_4, refmac_dir_baseline=child_baseline_4
            )
            parent_status_4 = onesar_refmac._verify_refmac_directory_post_run(
                parent_dir_4, refmac_dir_baseline=parent_baseline_4
            )
            self.assertIs(child_status_4["identity_verified"], True)
            self.assertIs(child_status_4["writable_post_run"], True)
            self.assertIs(parent_status_4["identity_verified"], True)
            self.assertIs(parent_status_4["writable_post_run"], True)

            parent_canonical_4 = parent_dir_4 / "record.json"
            parent_canonical_4_bytes = (
                b'{"marker": "parent-canonical-4", "preserve": true}\n'
            )
            parent_canonical_4.write_bytes(parent_canonical_4_bytes)
            orig_parent_canonical_4_st = os.lstat(parent_canonical_4)
            orig_parent_canonical_4_sha = _sha256_bytes(
                parent_canonical_4_bytes
            )

            parent_sym_target_4 = (
                markers_4 / "parent_first_sib_symlink_target_4.json"
            )
            parent_sym_target_4_bytes = (
                b'{"marker": "parent-first-sib-symlink-target-4", "preserve": true}\n'
            )
            parent_sym_target_4.write_bytes(parent_sym_target_4_bytes)
            orig_parent_sym_target_4_st = os.lstat(parent_sym_target_4)
            orig_parent_sym_target_4_sha = _sha256_bytes(
                parent_sym_target_4_bytes
            )

            parent_first_sib_4 = parent_dir_4 / f"record.parent.{pid}.json"
            os.symlink(parent_sym_target_4, parent_first_sib_4)
            orig_parent_first_sib_4_linktext = os.readlink(parent_first_sib_4)
            orig_parent_first_sib_4_lstat = os.lstat(parent_first_sib_4)

            parent_second_sib_4 = parent_dir_4 / f"record.parent.{pid}.1.json"

            caller_dict_4: dict[str, Any] = {
                "fixture": "immutable-caller",
                "paths": {"sentinel": "unchanged"},
            }
            caller_proxy_4 = MappingProxyType(caller_dict_4)
            before_caller_4_sha = _sha256_bytes(
                json.dumps(
                    dict(caller_proxy_4), sort_keys=True, allow_nan=False
                ).encode("utf-8")
            )

            child_target_4 = child_dir_4 / "record.json"
            child_tmp_4 = child_dir_4 / f".record.json.tmp.{pid}"
            child_tmp_4_abs = os.path.abspath(os.fspath(child_tmp_4))
            injected_child_perm_4 = PermissionError(
                errno.EACCES,
                "OS-write boundary fixture: deny child canonical temp open",
                str(child_tmp_4),
            )
            real_os_open_4 = os.open

            def _os_open_deny_child_tmp_4(
                path_arg: str | os.PathLike[str],
                flags: int,
                mode: int = 0o777,
                *args: Any,
                **kwargs: Any,
            ) -> int:
                if os.path.abspath(os.fspath(path_arg)) == child_tmp_4_abs:
                    raise injected_child_perm_4
                return real_os_open_4(path_arg, flags, mode, *args, **kwargs)

            child_failures_4: list[dict[str, Any]] = []
            caught_exc_4: list[Exception] = []
            retained_sink_4: list[dict[str, Any]] = []
            child_causes_4: list[Exception | None] = []
            parent_cause_sink_4: list[Exception | None] = []
            fallback_state_4: dict[str, Any] = {}

            with patch.object(
                onesar_refmac.os, "open", _os_open_deny_child_tmp_4
            ):
                art_4 = onesar_refmac._persist_collector_json_with_fallback(
                    caller_proxy_4,
                    child_target_4,
                    root=child_dir_4,
                    parent_retention_dir=parent_dir_4,
                    parent_retention_dir_baseline=parent_baseline_4,
                    parent_retention_dir_status=parent_status_4,
                    verified_root_fallback_state=fallback_state_4,
                    allow_unpersisted_on_no_verified_anchor=False,
                    refmac_dir_status=child_status_4,
                    child_dir_persistence_failures=child_failures_4,
                    caught_persistence_exceptions=caught_exc_4,
                    on_child_dir_failure_transform=lambda m: copy.deepcopy(
                        dict(m)
                    ),
                    retained_payload_sink=retained_sink_4,
                    child_dir_persistence_causes=child_causes_4,
                    parent_retention_dir_cause_sink=parent_cause_sink_4,
                )

            after_caller_4_sha = _sha256_bytes(
                json.dumps(
                    dict(caller_proxy_4), sort_keys=True, allow_nan=False
                ).encode("utf-8")
            )
            self.assertEqual(after_caller_4_sha, before_caller_4_sha)
            self.assertEqual(
                caller_dict_4,
                {
                    "fixture": "immutable-caller",
                    "paths": {"sentinel": "unchanged"},
                },
            )
            self.assertFalse(os.path.lexists(child_target_4))
            self.assertFalse(os.path.lexists(child_tmp_4))

            self.assertEqual(art_4["path"], str(parent_second_sib_4))
            self.assertEqual(
                art_4["fallback_for_preexisting_path"], str(parent_canonical_4)
            )
            self.assertIs(
                art_4["fallback_for_unwritable_or_damaged_child_dir"], True
            )
            self.assertEqual(
                art_4["intended_child_dir_path"], str(child_target_4)
            )
            self.assertEqual(
                art_4["intended_parent_retention_dir"], str(parent_dir_4)
            )
            self.assertEqual(art_4["parent_retention_dir"], str(parent_dir_4))
            self.assertEqual(
                art_4["actual_retention_anchor_dir"], str(parent_dir_4)
            )
            self.assertEqual(
                art_4["actual_retention_anchor_kind"], "parent_retention_dir"
            )
            reopened_4 = self._reopen_and_verify_json_artifact(art_4)
            self.assertEqual(reopened_4, caller_dict_4)
            self.assertEqual(retained_sink_4, [caller_dict_4])

            self.assertIs(child_status_4["identity_verified"], True)
            self.assertIs(child_status_4["writable_post_run"], False)
            self.assertEqual(
                child_status_4["write_exception_type"], "PermissionError"
            )
            self.assertEqual(child_status_4["write_errno"], errno.EACCES)
            self.assertEqual(len(child_failures_4), 1)
            self.assertIs(
                child_failures_4[0]["attempted_write_in_child_dir"], True
            )
            self.assertEqual(
                child_failures_4[0]["intended_path"], str(child_target_4)
            )
            self.assertEqual(
                child_failures_4[0]["exception_type"], "PermissionError"
            )
            self.assertEqual(len(child_causes_4), 1)
            self.assertIs(child_causes_4[0], injected_child_perm_4)
            self.assertEqual(len(caught_exc_4), 1)
            self.assertIs(caught_exc_4[0], injected_child_perm_4)
            self.assertEqual(parent_cause_sink_4, [None])

            after_parent_canonical_4_st = os.lstat(parent_canonical_4)
            self.assertTrue(stat.S_ISREG(after_parent_canonical_4_st.st_mode))
            self.assertEqual(
                (
                    int(after_parent_canonical_4_st.st_dev),
                    int(after_parent_canonical_4_st.st_ino),
                ),
                (
                    int(orig_parent_canonical_4_st.st_dev),
                    int(orig_parent_canonical_4_st.st_ino),
                ),
            )
            self.assertEqual(
                parent_canonical_4.read_bytes(), parent_canonical_4_bytes
            )
            self.assertEqual(
                _sha256_bytes(parent_canonical_4.read_bytes()),
                orig_parent_canonical_4_sha,
            )

            self.assertTrue(os.path.islink(parent_first_sib_4))
            self.assertEqual(
                os.readlink(parent_first_sib_4),
                orig_parent_first_sib_4_linktext,
            )
            after_parent_first_sib_4_lstat = os.lstat(parent_first_sib_4)
            self.assertEqual(
                (
                    int(after_parent_first_sib_4_lstat.st_dev),
                    int(after_parent_first_sib_4_lstat.st_ino),
                ),
                (
                    int(orig_parent_first_sib_4_lstat.st_dev),
                    int(orig_parent_first_sib_4_lstat.st_ino),
                ),
            )
            after_parent_sym_target_4_st = os.lstat(parent_sym_target_4)
            self.assertEqual(
                (
                    int(after_parent_sym_target_4_st.st_dev),
                    int(after_parent_sym_target_4_st.st_ino),
                ),
                (
                    int(orig_parent_sym_target_4_st.st_dev),
                    int(orig_parent_sym_target_4_st.st_ino),
                ),
            )
            self.assertEqual(
                parent_sym_target_4.read_bytes(), parent_sym_target_4_bytes
            )
            self.assertEqual(
                _sha256_bytes(parent_sym_target_4.read_bytes()),
                orig_parent_sym_target_4_sha,
            )

        with self.subTest(
            fixture="5_no_anchor_memory_with_immutable_mappingproxy"
        ):
            base_5 = (
                self.repo_root.parent
                / f"persist_no_anchor_5_{pid}"
            )
            child_dir_5 = base_5 / "refmac"
            parent_dir_5 = base_5 / "refmac_parent_retention"
            child_dir_5.mkdir(parents=True, exist_ok=True)
            parent_dir_5.mkdir(parents=True, exist_ok=True)

            child_baseline_5 = (
                onesar_refmac._capture_directory_identity_baseline(
                    child_dir_5, evidence_root=base_5
                )
            )
            parent_baseline_5 = (
                onesar_refmac._capture_directory_identity_baseline(
                    parent_dir_5, evidence_root=None
                )
            )
            self.assertNotIn("evidence_root", parent_baseline_5)
            self.assertNotIn("evidence_root_dev", parent_baseline_5)
            self.assertNotIn("evidence_root_ino", parent_baseline_5)

            child_status_5 = onesar_refmac._verify_refmac_directory_post_run(
                child_dir_5, refmac_dir_baseline=child_baseline_5
            )
            parent_status_5 = onesar_refmac._verify_refmac_directory_post_run(
                parent_dir_5, refmac_dir_baseline=parent_baseline_5
            )

            caller_dict_5: dict[str, Any] = {
                "fixture": "no-anchor-immutable",
                "paths": {"sentinel": "unchanged"},
            }
            caller_proxy_5 = MappingProxyType(caller_dict_5)
            before_caller_5_sha = _sha256_bytes(
                json.dumps(
                    dict(caller_proxy_5), sort_keys=True, allow_nan=False
                ).encode("utf-8")
            )

            child_target_5 = child_dir_5 / "record.json"
            child_tmp_5 = child_dir_5 / f".record.json.tmp.{pid}"
            parent_tmp_5 = parent_dir_5 / f".record.json.tmp.{pid}"
            child_tmp_5_abs = os.path.abspath(os.fspath(child_tmp_5))
            parent_tmp_5_abs = os.path.abspath(os.fspath(parent_tmp_5))

            child_perm_5 = PermissionError(
                errno.EACCES,
                "OS-write boundary fixture: deny child canonical temp open (fixture 5)",
                str(child_tmp_5),
            )
            parent_perm_5 = PermissionError(
                errno.EPERM,
                "OS-write boundary fixture: deny parent canonical temp open (fixture 5)",
                str(parent_tmp_5),
            )
            real_os_open_5 = os.open

            def _os_open_deny_child_and_parent_tmp_5(
                path_arg: str | os.PathLike[str],
                flags: int,
                mode: int = 0o777,
                *args: Any,
                **kwargs: Any,
            ) -> int:
                abs_p = os.path.abspath(os.fspath(path_arg))
                if abs_p == child_tmp_5_abs:
                    raise child_perm_5
                if abs_p == parent_tmp_5_abs:
                    raise parent_perm_5
                return real_os_open_5(path_arg, flags, mode, *args, **kwargs)

            child_failures_5: list[dict[str, Any]] = []
            caught_exc_5: list[Exception] = []
            retained_sink_5: list[dict[str, Any]] = []
            child_causes_5: list[Exception | None] = []
            parent_cause_sink_5: list[Exception | None] = []
            fallback_state_5: dict[str, Any] = {}

            with patch.object(
                onesar_refmac.os, "open", _os_open_deny_child_and_parent_tmp_5
            ):
                art_5 = onesar_refmac._persist_collector_json_with_fallback(
                    caller_proxy_5,
                    child_target_5,
                    root=child_dir_5,
                    parent_retention_dir=parent_dir_5,
                    parent_retention_dir_baseline=parent_baseline_5,
                    parent_retention_dir_status=parent_status_5,
                    verified_root_fallback_state=fallback_state_5,
                    allow_unpersisted_on_no_verified_anchor=True,
                    refmac_dir_status=child_status_5,
                    child_dir_persistence_failures=child_failures_5,
                    caught_persistence_exceptions=caught_exc_5,
                    on_child_dir_failure_transform=lambda m: copy.deepcopy(
                        dict(m)
                    ),
                    retained_payload_sink=retained_sink_5,
                    child_dir_persistence_causes=child_causes_5,
                    parent_retention_dir_cause_sink=parent_cause_sink_5,
                )

            after_caller_5_sha = _sha256_bytes(
                json.dumps(
                    dict(caller_proxy_5), sort_keys=True, allow_nan=False
                ).encode("utf-8")
            )
            self.assertEqual(after_caller_5_sha, before_caller_5_sha)
            self.assertEqual(list(child_dir_5.iterdir()), [])
            self.assertEqual(list(parent_dir_5.iterdir()), [])

            self.assertIsNone(art_5["path"])
            self.assertIs(art_5["persisted"], False)
            self.assertIs(art_5["no_verified_anchor_available"], True)
            self.assertIs(
                art_5["fallback_for_unwritable_or_damaged_child_dir"], True
            )
            self.assertIs(
                art_5[
                    "fallback_for_damaged_or_replaced_parent_retention_dir"
                ],
                True,
            )
            self.assertEqual(
                art_5["intended_child_dir_path"], str(child_target_5)
            )
            self.assertEqual(
                art_5["intended_parent_retention_dir"], str(parent_dir_5)
            )
            self.assertIsNone(art_5["parent_retention_dir"])
            self.assertIsNone(art_5["actual_retention_anchor_dir"])
            self.assertIsNone(art_5["actual_retention_anchor_kind"])
            self.assertIsNone(art_5["actual_retention_anchor_baseline"])

            self.assertEqual(retained_sink_5, [caller_dict_5])
            expected_serialized_5 = (
                json.dumps(
                    caller_dict_5, indent=2, sort_keys=True, allow_nan=False
                )
                + "\n"
            ).encode("utf-8")
            self.assertEqual(
                art_5["sha256"], _sha256_bytes(expected_serialized_5)
            )
            self.assertEqual(art_5["size_bytes"], len(expected_serialized_5))

            self.assertEqual(len(child_causes_5), 1)
            self.assertIs(child_causes_5[0], child_perm_5)
            self.assertEqual(len(parent_cause_sink_5), 1)
            self.assertIs(parent_cause_sink_5[0], parent_perm_5)
            self.assertEqual(len(caught_exc_5), 3)
            self.assertIs(caught_exc_5[0], child_perm_5)
            self.assertIs(caught_exc_5[1], parent_perm_5)
            self.assertIsInstance(caught_exc_5[2], ValueError)
            self.assertIn(
                "No admitted evidence_root baseline identity available",
                str(caught_exc_5[2]),
            )

    def test_run_refmac_rfactor_operation_final_diagnostics_collision_e2e(
        self,
    ) -> None:
        """Case 36 (Fixture 6): Final canonical diagnostics collision during run_refmac_rfactor_operation writes sibling diagnostics, preserves marker, and fails at refmac_raw_outputs."""
        pid = os.getpid()
        case_name = f"case36_final_diag_collision_e2e_{pid}"
        evidence_root = self.repo_root / "runs" / case_name
        refmac_dir = evidence_root / "refmac"
        diag_canonical = refmac_dir / "refmac_diagnostics.json"
        diag_tmp = refmac_dir / f".refmac_diagnostics.json.tmp.{pid}"
        diag_sib = refmac_dir / f"refmac_diagnostics.parent.{pid}.json"
        manifest_canonical = refmac_dir / "refmac_operation_manifest.json"
        pre_ckpt_path = refmac_dir / "refmac_pre_execution_checkpoint.json"
        post_ckpt_path = refmac_dir / "refmac_post_execution_checkpoint.json"

        diag_tmp_abs = os.path.abspath(os.fspath(diag_tmp))
        marker_bytes = (
            b'{"marker": "canonical-diagnostics-collision-6", "preserve": true}\n'
        )
        marker_sha = _sha256_bytes(marker_bytes)
        marker_stat_holder: list[os.stat_result] = []
        pre_ckpt_before_holder: list[bytes] = []
        post_ckpt_before_holder: list[bytes] = []
        real_os_open = os.open

        def _os_open_create_canonical_diag_marker(
            path_arg: str | os.PathLike[str],
            flags: int,
            mode: int = 0o777,
            *args: Any,
            **kwargs: Any,
        ) -> int:
            if (
                not marker_stat_holder
                and os.path.abspath(os.fspath(path_arg)) == diag_tmp_abs
            ):
                pre_ckpt_before_holder.append(pre_ckpt_path.read_bytes())
                post_ckpt_before_holder.append(post_ckpt_path.read_bytes())
                m_fd = real_os_open(
                    diag_canonical,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o644,
                )
                try:
                    os.write(m_fd, marker_bytes)
                finally:
                    os.close(m_fd)
                marker_stat_holder.append(os.lstat(diag_canonical))
            return real_os_open(path_arg, flags, mode, *args, **kwargs)

        def runner(
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
            self._write_capture_success_outputs(
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
                stdout=SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG,
                stderr="",
            )

        with patch.object(
            onesar_refmac.os, "open", _os_open_create_canonical_diag_marker
        ):
            with self.assertRaises(onesar_refmac.RefmacCollectorError) as cm:
                self._run_with_fake_ccp4(case_name, runner)

        err = cm.exception
        self.assertEqual(len(marker_stat_holder), 1)
        self.assertEqual(err.failed_stage, "refmac_raw_outputs")
        self.assertIsNone(err.primary_cause)
        self.assertIsNone(err.__cause__)
        self.assertIs(err.publication_pair_complete, True)
        self.assertIsNone(err.publication_terminal_failure)
        self.assertEqual(err.publication_history, [])
        self.assertEqual(err.diagnostics_path, diag_sib)
        self.assertEqual(err.manifest_path, manifest_canonical)

        # Verify canonical marker survived byte-for-byte with unchanged inode, and canonical temp was removed.
        self.assertFalse(os.path.lexists(diag_tmp))
        after_marker_st = os.lstat(diag_canonical)
        self.assertTrue(stat.S_ISREG(after_marker_st.st_mode))
        self.assertEqual(
            (int(after_marker_st.st_dev), int(after_marker_st.st_ino)),
            (
                int(marker_stat_holder[0].st_dev),
                int(marker_stat_holder[0].st_ino),
            ),
        )
        self.assertEqual(diag_canonical.read_bytes(), marker_bytes)
        self.assertEqual(
            _sha256_bytes(diag_canonical.read_bytes()), marker_sha
        )

        # Verify pre-execution and post-execution checkpoints are unchanged on disk.
        self.assertEqual(pre_ckpt_path.read_bytes(), pre_ckpt_before_holder[0])
        self.assertEqual(
            post_ckpt_path.read_bytes(), post_ckpt_before_holder[0]
        )

        # Reopen and verify sibling diagnostics and canonical manifest on disk.
        self.assertIsInstance(err.manifest_payload, Mapping)
        assert isinstance(err.manifest_payload, Mapping)
        diag_ref = err.manifest_payload["diagnostics_json"]
        self.assertEqual(diag_ref["path"], str(diag_sib))
        self.assertEqual(
            diag_ref["fallback_for_preexisting_path"], str(diag_canonical)
        )
        diag_disk = self._reopen_and_verify_json_artifact(diag_ref)
        manifest_raw = manifest_canonical.read_bytes()
        manifest_disk = json.loads(manifest_raw.decode("utf-8"))
        self.assertEqual(manifest_disk, dict(err.manifest_payload))
        self.assertEqual(diag_disk, dict(err.diagnostics_payload or {}))

        self.assertEqual(
            manifest_disk["paths"]["diagnostics_json_path"], str(diag_sib)
        )
        self.assertEqual(
            manifest_disk["paths"]["manifest_json_path"],
            str(manifest_canonical),
        )

        for payload in (diag_disk, manifest_disk):
            self.assertEqual(payload["status"], "failed")
            self.assertEqual(payload["failed_stage"], "refmac_raw_outputs")
            self.assertIs(
                payload["refmac_directory_post_run"]["identity_verified"], True
            )
            self.assertIs(
                payload["refmac_directory_post_run"]["writable_post_run"], True
            )
            self.assertEqual(payload["child_dir_persistence_failures"], [])
            self.assertIs(payload["parent_retention_used"], False)
            self.assertIs(payload["publication_pair_complete"], True)
            self.assertIsNone(payload["publication_terminal_failure"])
            self.assertEqual(payload["publication_history"], [])
            self.assertGreaterEqual(len(payload["failures"]), 1)
            first_fail = payload["failures"][0]
            self.assertEqual(first_fail["failed_stage"], "refmac_raw_outputs")
            collided_entries = [
                item
                for item in first_fail["missing_or_invalid_outputs"]
                if item.get("output_key") == "diagnostics_json"
                and item.get("path") == str(diag_canonical)
            ]
            self.assertEqual(len(collided_entries), 1)
            self.assertIn(
                "Reserved collector JSON path or temp path collided and required fallback",
                str(collided_entries[0]["error"]),
            )
            self._assert_all_scientific_admission_flags_false(payload)

    def _assert_repeated_derivation_idempotent(
        self,
        first_payload: Mapping[str, Any],
        second_payload: Mapping[str, Any],
    ) -> None:
        for key in (
            "status",
            "failed_stage",
            "failures",
            "publication_history",
            "publication_pair_complete",
            "publication_terminal_failure",
            "child_dir_persistence_failures",
            "parent_retention_used",
            "actual_parent_retention_anchor_dir",
            "actual_parent_retention_anchor_kind",
            "actual_parent_retention_anchor_baseline",
            "refmac_directory_post_run",
            "parent_retention_directory_post_run",
            "parent_retention_fallback_anchor",
            "operation_checks",
            "input_immutability",
            "effective_hkls_proven",
            "effective_hkls_unproven_reason",
            "native_bin_membership_proven",
            "native_bin_membership_unproven_reason",
            "native_residual_reconstruction_proven",
            "native_residual_reconstruction_unproven_reason",
            "model_preservation_proven",
            "model_preservation_unproven_reason",
            "preregistered_gates",
            "all_preregistered_gates_passed",
        ):
            if key in first_payload or key in second_payload:
                self.assertEqual(
                    first_payload.get(key),
                    second_payload.get(key),
                    f"Repeated payload derivation drifted on key {key!r}",
                )
        self.assertEqual(dict(first_payload), dict(second_payload))
        for item in second_payload.get("failures", []):
            if (
                isinstance(item, Mapping)
                and item.get("failed_stage") == "refmac_raw_outputs"
            ):
                outputs = item.get("missing_or_invalid_outputs", [])
                pairs = [
                    (str(entry.get("output_key")), str(entry.get("path")))
                    for entry in outputs
                    if isinstance(entry, Mapping)
                ]
                self.assertEqual(len(pairs), len(set(pairs)))
        hist = second_payload.get("publication_history", [])
        if isinstance(hist, list):
            snap_ids = [
                str(entry.get("snapshot_id"))
                for entry in hist
                if isinstance(entry, Mapping)
            ]
            self.assertEqual(len(snap_ids), len(set(snap_ids)))

    def _assert_late_failure_proofs_and_gates(
        self,
        payload: Mapping[str, Any],
        *,
        expect_xyzout_audit_model_preserved: bool = True,
    ) -> None:
        self.assertEqual(payload.get("status"), "failed")
        failures = payload.get("failures")
        self.assertIsInstance(failures, list)
        assert isinstance(failures, list)
        self.assertGreaterEqual(len(failures), 1)
        self.assertEqual(
            payload.get("failed_stage"), failures[0].get("failed_stage")
        )
        self.assertIs(
            payload["operation_checks"]["collector_succeeded"], False
        )
        self._assert_all_scientific_admission_flags_false(payload)
        self.assertNotIn("manifest_json", payload)

        if expect_xyzout_audit_model_preserved:
            self.assertIs(
                payload["audits"]["xyzout_pdb_audit"][
                    "model_preservation_proven"
                ],
                True,
            )
            self.assertIn(
                "audit check passed, but public proof is gated false by collector/publication failure",
                str(payload.get("model_preservation_unproven_reason")),
            )

        gates = payload.get("preregistered_gates")
        self.assertIsInstance(gates, Mapping)
        assert isinstance(gates, Mapping)
        for proof_key, reason_key, gate_key in (
            (
                "effective_hkls_proven",
                "effective_hkls_unproven_reason",
                "gate_3_effective_hkls_proven",
            ),
            (
                "native_bin_membership_proven",
                "native_bin_membership_unproven_reason",
                "gate_4_native_bin_membership_proven",
            ),
            (
                "native_residual_reconstruction_proven",
                "native_residual_reconstruction_unproven_reason",
                "gate_5_native_residual_reconstruction_proven",
            ),
            (
                "model_preservation_proven",
                "model_preservation_unproven_reason",
                "gate_6_model_preservation_proven",
            ),
        ):
            self.assertIs(payload.get(proof_key), False)
            reason_val = payload.get(reason_key)
            self.assertIsInstance(reason_val, str)
            assert isinstance(reason_val, str)
            self.assertTrue(bool(reason_val.strip()))
            self.assertNotEqual(reason_val.strip().lower(), "none")
            gate_obj = gates.get(gate_key)
            self.assertIsInstance(gate_obj, Mapping)
            assert isinstance(gate_obj, Mapping)
            self.assertIs(gate_obj.get("proven"), False)
            self.assertEqual(gate_obj.get("status"), "unproven")
            self.assertEqual(gate_obj.get("reason"), reason_val)

    def _verify_prior_child_artifacts_preserved(
        self,
        payload: Mapping[str, Any],
        written_by_path: Mapping[str, dict[str, Any]],
    ) -> None:
        for art_key in (
            "pre_execution_checkpoint_json",
            "post_execution_checkpoint_json",
            "parsed_log_json",
            "xmlout_audit_json",
            "hklout_raw_export_json",
            "hklout_audit_json",
            "xyzout_audit_json",
        ):
            art_ref = payload.get(art_key)
            self.assertIsInstance(art_ref, Mapping)
            assert isinstance(art_ref, Mapping)
            reopened = self._reopen_and_verify_json_artifact(art_ref)
            art_path = str(art_ref["path"])
            if art_path in written_by_path:
                self.assertEqual(
                    art_ref["sha256"], written_by_path[art_path]["sha256"]
                )
                self.assertEqual(
                    art_ref["size_bytes"],
                    written_by_path[art_path]["size_bytes"],
                )
            if art_key == "xmlout_audit_json":
                self.assertIs(reopened["valid"], True)
                self.assertEqual(reopened["status"], "absent")
            elif art_key == "xyzout_audit_json":
                self.assertIs(reopened["valid"], True)
                self.assertIs(reopened["model_preservation_proven"], True)
            elif art_key == "hklout_audit_json":
                self.assertIs(reopened["valid"], True)

    def _verify_publication_history_rows(
        self,
        history: Sequence[Mapping[str, Any]],
        expected_specs: Sequence[tuple[str, str, Path]],
        written_by_path: Mapping[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        self.assertEqual(len(history), len(expected_specs))
        reopened_snapshots: list[dict[str, Any]] = []
        for row, (exp_id, exp_kind, exp_path) in zip(history, expected_specs):
            self.assertEqual(row.get("role"), exp_id)
            self.assertEqual(row.get("snapshot_id"), exp_id)
            self.assertEqual(row.get("artifact_kind"), exp_kind)
            self.assertEqual(row.get("path"), str(exp_path))
            self.assertIs(row.get("verified_on_disk"), True)
            self.assertIsNone(row.get("verification_error"))
            sup_reason = row.get("superseded_reason")
            self.assertIsInstance(sup_reason, str)
            self.assertTrue(bool(str(sup_reason).strip()))
            if str(exp_path) in written_by_path:
                self.assertEqual(
                    row.get("sha256"),
                    written_by_path[str(exp_path)]["sha256"],
                )
                self.assertEqual(
                    row.get("size_bytes"),
                    written_by_path[str(exp_path)]["size_bytes"],
                )
            snap_payload = self._reopen_and_verify_json_artifact(row)
            reopened_snapshots.append(snap_payload)
        return reopened_snapshots

    def test_late_publication_first_d0_and_m0_child_write_failures(
        self,
    ) -> None:
        """Case 37 (Fixtures F1, F2): First-late D0 and M0 child write failures produce honest public failure, authoritative final references, preserved audits/snapshots, and idempotent outcome derivation."""
        pid = os.getpid()

        def _capture_success_runner(
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
            self._write_capture_success_outputs(
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
                stdout=SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG,
                stderr="",
            )

        with self.subTest(fixture="F1_first_late_d0_child_write_failure"):
            case_f1 = f"case37_f1_late_d0_child_fail_{pid}"
            ev_root_f1 = self.repo_root / "runs" / case_f1
            refmac_dir_f1 = ev_root_f1 / "refmac"
            parent_dir_f1 = ev_root_f1 / "refmac_parent_retention"
            d0_child_target_f1 = refmac_dir_f1 / "refmac_diagnostics.json"
            m0_child_target_f1 = (
                refmac_dir_f1 / "refmac_operation_manifest.json"
            )
            d0_parent_target_f1 = parent_dir_f1 / "refmac_diagnostics.json"
            m0_parent_target_f1 = (
                parent_dir_f1 / "refmac_operation_manifest.json"
            )

            d0_exc_f1 = PermissionError(
                errno.EACCES,
                "F1 injected late D0 child write failure",
                str(d0_child_target_f1),
            )
            orig_atomic_f1 = onesar_refmac._atomic_write_new_json_file
            written_by_path_f1: dict[str, dict[str, Any]] = {}
            attempted_targets_f1: list[tuple[Path, Path]] = []
            double_eval_count_f1 = 0

            def _wrapped_atomic_f1(
                payload: Any,
                target_path: Path,
                *,
                root: Path,
            ) -> dict[str, Any]:
                nonlocal double_eval_count_f1
                attempted_targets_f1.append((target_path, root))
                if target_path == d0_child_target_f1 and root == refmac_dir_f1:
                    raise d0_exc_f1
                effective_payload = payload
                if callable(payload) and target_path.name in (
                    "refmac_diagnostics.json",
                    "refmac_operation_manifest.json",
                    "refmac_r_factor_diagnostics.corrected.json",
                    "refmac_operation_manifest.corrected.json",
                ):

                    def _double_eval(dest: Path) -> Mapping[str, Any]:
                        nonlocal double_eval_count_f1
                        first_map = copy.deepcopy(dict(payload(dest)))
                        second_raw = payload(dest)
                        second_map = copy.deepcopy(dict(second_raw))
                        self._assert_repeated_derivation_idempotent(
                            first_map, second_map
                        )
                        double_eval_count_f1 += 1
                        return second_raw

                    effective_payload = _double_eval
                res = orig_atomic_f1(
                    effective_payload, target_path, root=root
                )
                written_by_path_f1[str(res["path"])] = copy.deepcopy(res)
                return res

            with patch.object(
                onesar_refmac,
                "_atomic_write_new_json_file",
                _wrapped_atomic_f1,
            ):
                with self.assertRaises(
                    onesar_refmac.RefmacCollectorError
                ) as cm_f1:
                    self._run_with_fake_ccp4(case_f1, _capture_success_runner)

            err_f1 = cm_f1.exception
            self.assertEqual(double_eval_count_f1, 2)
            self.assertEqual(
                err_f1.failed_stage,
                "persist_collector_artifacts_in_refmac_dir",
            )
            self.assertIs(err_f1.primary_cause, d0_exc_f1)
            self.assertIs(err_f1.__cause__, d0_exc_f1)
            self.assertIsNone(err_f1.terminal_cause)
            self.assertIs(err_f1.publication_pair_complete, True)
            self.assertIsNone(err_f1.publication_terminal_failure)
            self.assertEqual(err_f1.publication_history, [])
            self.assertEqual(err_f1.diagnostics_path, d0_parent_target_f1)
            self.assertEqual(err_f1.manifest_path, m0_parent_target_f1)
            self.assertFalse(os.path.lexists(d0_child_target_f1))
            self.assertFalse(os.path.lexists(m0_child_target_f1))
            self.assertNotIn(
                (m0_child_target_f1, refmac_dir_f1), attempted_targets_f1
            )

            diag_disk_f1 = self._reopen_and_verify_json_artifact(
                written_by_path_f1[str(d0_parent_target_f1)]
            )
            manifest_disk_f1 = self._reopen_and_verify_json_artifact(
                written_by_path_f1[str(m0_parent_target_f1)]
            )
            self.assertEqual(
                diag_disk_f1, dict(err_f1.diagnostics_payload or {})
            )
            self.assertEqual(
                manifest_disk_f1, dict(err_f1.manifest_payload or {})
            )
            self.assertEqual(
                manifest_disk_f1["diagnostics_json"]["path"],
                str(d0_parent_target_f1),
            )
            self.assertEqual(
                manifest_disk_f1["paths"]["diagnostics_json_path"],
                str(d0_parent_target_f1),
            )
            self.assertEqual(
                manifest_disk_f1["paths"]["manifest_json_path"],
                str(m0_parent_target_f1),
            )
            self.assertEqual(
                self._reopen_and_verify_json_artifact(
                    manifest_disk_f1["diagnostics_json"]
                ),
                diag_disk_f1,
            )

            for payload_f1 in (diag_disk_f1, manifest_disk_f1):
                self._assert_late_failure_proofs_and_gates(payload_f1)
                self._verify_prior_child_artifacts_preserved(
                    payload_f1, written_by_path_f1
                )
                self.assertEqual(
                    payload_f1["failed_stage"],
                    "persist_collector_artifacts_in_refmac_dir",
                )
                self.assertEqual(
                    [f["failed_stage"] for f in payload_f1["failures"]],
                    ["persist_collector_artifacts_in_refmac_dir"],
                )
                self.assertIs(payload_f1["parent_retention_used"], True)
                self.assertEqual(
                    payload_f1["actual_parent_retention_anchor_dir"],
                    str(parent_dir_f1),
                )
                self.assertEqual(
                    payload_f1["actual_parent_retention_anchor_kind"],
                    "parent_retention_dir",
                )
                self.assertEqual(payload_f1["publication_history"], [])
                child_rows_f1 = payload_f1["child_dir_persistence_failures"]
                self.assertEqual(len(child_rows_f1), 2)
                self.assertEqual(
                    child_rows_f1[0]["intended_path"], str(d0_child_target_f1)
                )
                self.assertIs(
                    child_rows_f1[0]["attempted_write_in_child_dir"], True
                )
                self.assertEqual(
                    child_rows_f1[1]["intended_path"], str(m0_child_target_f1)
                )
                self.assertIs(
                    child_rows_f1[1]["attempted_write_in_child_dir"], False
                )
                self.assertIs(
                    payload_f1["operation_checks"]["stage2_audits_succeeded"],
                    False,
                )

        with self.subTest(fixture="F2_first_late_m0_child_write_failure"):
            case_f2 = f"case37_f2_late_m0_child_fail_{pid}"
            ev_root_f2 = self.repo_root / "runs" / case_f2
            refmac_dir_f2 = ev_root_f2 / "refmac"
            parent_dir_f2 = ev_root_f2 / "refmac_parent_retention"
            d0_child_target_f2 = refmac_dir_f2 / "refmac_diagnostics.json"
            m0_child_target_f2 = (
                refmac_dir_f2 / "refmac_operation_manifest.json"
            )
            m0_parent_target_f2 = (
                parent_dir_f2 / "refmac_operation_manifest.json"
            )
            d1_parent_target_f2 = (
                parent_dir_f2 / "refmac_r_factor_diagnostics.corrected.json"
            )
            m1_parent_target_f2 = (
                parent_dir_f2 / "refmac_operation_manifest.corrected.json"
            )

            m0_exc_f2 = PermissionError(
                errno.EACCES,
                "F2 injected late M0 child write failure",
                str(m0_child_target_f2),
            )
            orig_atomic_f2 = onesar_refmac._atomic_write_new_json_file
            written_by_path_f2: dict[str, dict[str, Any]] = {}
            double_eval_count_f2 = 0

            def _wrapped_atomic_f2(
                payload: Any,
                target_path: Path,
                *,
                root: Path,
            ) -> dict[str, Any]:
                nonlocal double_eval_count_f2
                if target_path == m0_child_target_f2 and root == refmac_dir_f2:
                    raise m0_exc_f2
                effective_payload = payload
                if callable(payload) and target_path.name in (
                    "refmac_diagnostics.json",
                    "refmac_operation_manifest.json",
                    "refmac_r_factor_diagnostics.corrected.json",
                    "refmac_operation_manifest.corrected.json",
                ):

                    def _double_eval(dest: Path) -> Mapping[str, Any]:
                        nonlocal double_eval_count_f2
                        first_map = copy.deepcopy(dict(payload(dest)))
                        second_raw = payload(dest)
                        second_map = copy.deepcopy(dict(second_raw))
                        self._assert_repeated_derivation_idempotent(
                            first_map, second_map
                        )
                        double_eval_count_f2 += 1
                        return second_raw

                    effective_payload = _double_eval
                res = orig_atomic_f2(
                    effective_payload, target_path, root=root
                )
                written_by_path_f2[str(res["path"])] = copy.deepcopy(res)
                return res

            with patch.object(
                onesar_refmac,
                "_atomic_write_new_json_file",
                _wrapped_atomic_f2,
            ):
                with self.assertRaises(
                    onesar_refmac.RefmacCollectorError
                ) as cm_f2:
                    self._run_with_fake_ccp4(case_f2, _capture_success_runner)

            err_f2 = cm_f2.exception
            self.assertEqual(double_eval_count_f2, 4)
            self.assertEqual(
                err_f2.failed_stage,
                "persist_collector_artifacts_in_refmac_dir",
            )
            self.assertIs(err_f2.primary_cause, m0_exc_f2)
            self.assertIs(err_f2.__cause__, m0_exc_f2)
            self.assertIsNone(err_f2.terminal_cause)
            self.assertIs(err_f2.publication_pair_complete, True)
            self.assertIsNone(err_f2.publication_terminal_failure)
            self.assertEqual(err_f2.diagnostics_path, d1_parent_target_f2)
            self.assertEqual(err_f2.manifest_path, m1_parent_target_f2)

            d1_disk_f2 = self._reopen_and_verify_json_artifact(
                written_by_path_f2[str(d1_parent_target_f2)]
            )
            m1_disk_f2 = self._reopen_and_verify_json_artifact(
                written_by_path_f2[str(m1_parent_target_f2)]
            )
            self.assertEqual(
                d1_disk_f2, dict(err_f2.diagnostics_payload or {})
            )
            self.assertEqual(m1_disk_f2, dict(err_f2.manifest_payload or {}))
            self.assertEqual(
                m1_disk_f2["diagnostics_json"]["path"],
                str(d1_parent_target_f2),
            )
            self.assertEqual(
                m1_disk_f2["paths"]["diagnostics_json_path"],
                str(d1_parent_target_f2),
            )
            self.assertEqual(
                m1_disk_f2["paths"]["manifest_json_path"],
                str(m1_parent_target_f2),
            )

            hist_snaps_f2 = self._verify_publication_history_rows(
                err_f2.publication_history,
                [
                    ("D0", "diagnostics_json", d0_child_target_f2),
                    ("M0", "manifest_json", m0_parent_target_f2),
                ],
                written_by_path_f2,
            )
            d0_snap_f2, m0_snap_f2 = hist_snaps_f2
            self.assertEqual(
                d0_snap_f2["status"], "diagnostic_captured_gates_unproven"
            )
            self.assertIsNone(d0_snap_f2["failed_stage"])
            self.assertEqual(d0_snap_f2["failures"], [])
            self.assertEqual(m0_snap_f2["status"], "failed")
            self.assertEqual(
                m0_snap_f2["failed_stage"],
                "persist_collector_artifacts_in_refmac_dir",
            )

            for payload_f2 in (d1_disk_f2, m1_disk_f2):
                self._assert_late_failure_proofs_and_gates(payload_f2)
                self._verify_prior_child_artifacts_preserved(
                    payload_f2, written_by_path_f2
                )
                self.assertEqual(
                    payload_f2["publication_history"],
                    err_f2.publication_history,
                )
                self.assertIs(payload_f2["parent_retention_used"], True)
                self.assertEqual(
                    payload_f2["actual_parent_retention_anchor_dir"],
                    str(parent_dir_f2),
                )
                self.assertEqual(
                    payload_f2["actual_parent_retention_anchor_kind"],
                    "parent_retention_dir",
                )
                child_rows_f2 = payload_f2["child_dir_persistence_failures"]
                self.assertEqual(len(child_rows_f2), 1)
                self.assertEqual(
                    child_rows_f2[0]["intended_path"], str(m0_child_target_f2)
                )
                self.assertIs(
                    child_rows_f2[0]["attempted_write_in_child_dir"], True
                )

    def test_late_publication_d0_exhaustion_same_child_m0_d1_collisions_and_mode_refresh(
        self,
    ) -> None:
        """Case 38 (Fixtures F3, F4, F5, F6): D0 write exhaustion without M0 fallback, same-child M0/D1 collisions, and current-child mode refresh with rejected D1 correction."""
        pid = os.getpid()

        def _capture_success_runner(
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
            self._write_capture_success_outputs(
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
                stdout=SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG,
                stderr="",
            )

        with self.subTest(
            fixture="F3_no_saved_d0_exhausted_admitted_writes"
        ):
            case_f3 = f"case38_f3_no_saved_d0_exhausted_{pid}"
            ev_root_f3 = self.repo_root / "runs" / case_f3
            refmac_dir_f3 = ev_root_f3 / "refmac"
            parent_dir_f3 = ev_root_f3 / "refmac_parent_retention"
            d0_child_target_f3 = refmac_dir_f3 / "refmac_diagnostics.json"
            d0_parent_target_f3 = parent_dir_f3 / "refmac_diagnostics.json"

            d0_child_exc_f3 = PermissionError(
                errno.EACCES,
                "F3 injected D0 child write failure",
                str(d0_child_target_f3),
            )
            d0_parent_exc_f3 = PermissionError(
                errno.EPERM,
                "F3 injected D0 parent write failure",
                str(d0_parent_target_f3),
            )
            d0_anchor_exc_f3 = PermissionError(
                errno.EACCES,
                "F3 injected D0 exclusive anchor write failure",
            )

            orig_atomic_f3 = onesar_refmac._atomic_write_new_json_file
            orig_persist_f3 = onesar_refmac._persist_collector_json_with_fallback
            orig_ensure_anchor_f3 = (
                onesar_refmac._ensure_verified_root_exclusive_fallback_dir
            )

            written_by_path_f3: dict[str, dict[str, Any]] = {}
            attempted_targets_f3: list[tuple[Path, Path]] = []
            observed_anchors_f3: list[Path | None] = []
            persister_records_f3: list[tuple[Path, dict[str, Any]]] = []
            double_eval_unpersisted_f3 = 0

            def _wrapped_ensure_anchor_f3(
                *args: Any, **kwargs: Any
            ) -> tuple[Path | None, dict[str, Any] | None, str | None]:
                anchor_dir, anchor_base, ev_err = orig_ensure_anchor_f3(
                    *args, **kwargs
                )
                observed_anchors_f3.append(anchor_dir)
                return anchor_dir, anchor_base, ev_err

            def _wrapped_persist_f3(
                payload: Any,
                target_path: Path,
                **kwargs: Any,
            ) -> dict[str, Any]:
                nonlocal double_eval_unpersisted_f3
                effective_payload = payload
                if (
                    callable(payload)
                    and target_path.name == "refmac_diagnostics.json"
                ):

                    def _wrapped_d0_builder(
                        dest: Path | None,
                    ) -> Mapping[str, Any]:
                        nonlocal double_eval_unpersisted_f3
                        first_map = copy.deepcopy(dict(payload(dest)))
                        second_raw = payload(dest)
                        second_map = copy.deepcopy(dict(second_raw))
                        self._assert_repeated_derivation_idempotent(
                            first_map, second_map
                        )
                        if dest is None:
                            double_eval_unpersisted_f3 += 1
                        return second_raw

                    effective_payload = _wrapped_d0_builder
                rec = orig_persist_f3(
                    effective_payload, target_path, **kwargs
                )
                if target_path.name in (
                    "refmac_diagnostics.json",
                    "refmac_operation_manifest.json",
                ):
                    persister_records_f3.append(
                        (target_path, copy.deepcopy(rec))
                    )
                return rec

            def _wrapped_atomic_f3(
                payload: Any,
                target_path: Path,
                *,
                root: Path,
            ) -> dict[str, Any]:
                attempted_targets_f3.append((target_path, root))
                if target_path.name == "refmac_diagnostics.json":
                    if root == refmac_dir_f3:
                        raise d0_child_exc_f3
                    if root == parent_dir_f3:
                        raise d0_parent_exc_f3
                    if (
                        observed_anchors_f3
                        and observed_anchors_f3[0] is not None
                        and root == observed_anchors_f3[0]
                    ):
                        raise d0_anchor_exc_f3
                res = orig_atomic_f3(payload, target_path, root=root)
                written_by_path_f3[str(res["path"])] = copy.deepcopy(res)
                return res

            with (
                patch.object(
                    onesar_refmac,
                    "_ensure_verified_root_exclusive_fallback_dir",
                    _wrapped_ensure_anchor_f3,
                ),
                patch.object(
                    onesar_refmac,
                    "_persist_collector_json_with_fallback",
                    _wrapped_persist_f3,
                ),
                patch.object(
                    onesar_refmac,
                    "_atomic_write_new_json_file",
                    _wrapped_atomic_f3,
                ),
            ):
                with self.assertRaises(
                    onesar_refmac.RefmacCollectorError
                ) as cm_f3:
                    self._run_with_fake_ccp4(case_f3, _capture_success_runner)

            err_f3 = cm_f3.exception
            self.assertEqual(double_eval_unpersisted_f3, 1)
            self.assertEqual(len(observed_anchors_f3), 1)
            anchor_dir_f3 = observed_anchors_f3[0]
            self.assertIsNotNone(anchor_dir_f3)
            assert anchor_dir_f3 is not None
            self.assertTrue(anchor_dir_f3.is_dir())
            self.assertEqual(list(anchor_dir_f3.iterdir()), [])
            self.assertEqual(len(persister_records_f3), 1)
            d0_rec_path_f3, d0_rec_f3 = persister_records_f3[0]
            self.assertEqual(d0_rec_path_f3, d0_child_target_f3)
            self.assertIs(d0_rec_f3["persisted"], False)
            self.assertIsNone(d0_rec_f3["path"])
            self.assertIs(d0_rec_f3["no_verified_anchor_available"], True)

            for attempted_path, _ in attempted_targets_f3:
                self.assertNotIn(
                    attempted_path.name,
                    (
                        "refmac_operation_manifest.json",
                        "refmac_r_factor_diagnostics.corrected.json",
                        "refmac_operation_manifest.corrected.json",
                    ),
                )

            self.assertIs(err_f3.publication_pair_complete, False)
            self.assertIsNone(err_f3.diagnostics_path)
            self.assertIsNone(err_f3.manifest_path)
            self.assertEqual(err_f3.publication_history, [])
            self.assertIsInstance(err_f3.unpersisted_reason, str)
            self.assertTrue(bool(str(err_f3.unpersisted_reason).strip()))
            self.assertIs(err_f3.terminal_cause, d0_anchor_exc_f3)
            self.assertEqual(
                err_f3.failed_stage, "verify_parent_retention_directory"
            )
            self.assertIs(err_f3.primary_cause, d0_parent_exc_f3)
            self.assertIs(err_f3.__cause__, d0_parent_exc_f3)

            term_f3 = err_f3.publication_terminal_failure
            self.assertIsInstance(term_f3, Mapping)
            assert isinstance(term_f3, Mapping)
            self.assertEqual(term_f3["stage"], "persist_diagnostics_d0")
            self.assertEqual(
                term_f3["rejected_destination"], str(d0_child_target_f3)
            )
            self.assertEqual(term_f3["exception_type"], "PermissionError")
            self.assertEqual(
                term_f3["exception_message"], str(d0_anchor_exc_f3)
            )
            self.assertEqual(term_f3["errno"], errno.EACCES)

            self.assertIsInstance(err_f3.diagnostics_payload, Mapping)
            self.assertIsInstance(err_f3.manifest_payload, Mapping)
            assert isinstance(err_f3.diagnostics_payload, Mapping)
            assert isinstance(err_f3.manifest_payload, Mapping)
            self.assertIsNone(err_f3.manifest_payload["diagnostics_json"])
            self.assertIsNone(
                err_f3.manifest_payload["paths"]["diagnostics_json_path"]
            )
            self.assertIsNone(
                err_f3.manifest_payload["paths"]["manifest_json_path"]
            )
            for payload_f3 in (
                err_f3.diagnostics_payload,
                err_f3.manifest_payload,
            ):
                self._assert_late_failure_proofs_and_gates(payload_f3)
                self._verify_prior_child_artifacts_preserved(
                    payload_f3, written_by_path_f3
                )
                self.assertIs(payload_f3["publication_pair_complete"], False)
                self.assertEqual(
                    payload_f3["publication_terminal_failure"], dict(term_f3)
                )
                self.assertIsNone(
                    payload_f3["actual_parent_retention_anchor_dir"]
                )
                self.assertIsNone(
                    payload_f3["actual_parent_retention_anchor_kind"]
                )
                self.assertIsNone(
                    payload_f3["actual_parent_retention_anchor_baseline"]
                )
                self.assertEqual(
                    [f["failed_stage"] for f in payload_f3["failures"]],
                    [
                        "verify_parent_retention_directory",
                        "persist_collector_artifacts_in_refmac_dir",
                        "persist_diagnostics_d0",
                    ],
                )

        with self.subTest(fixture="F4_actual_same_child_m0_collision"):
            case_f4 = f"case38_f4_same_child_m0_collision_{pid}"
            ev_root_f4 = self.repo_root / "runs" / case_f4
            refmac_dir_f4 = ev_root_f4 / "refmac"
            parent_dir_f4 = ev_root_f4 / "refmac_parent_retention"
            d0_child_f4 = refmac_dir_f4 / "refmac_diagnostics.json"
            m0_child_f4 = refmac_dir_f4 / "refmac_operation_manifest.json"
            m0_sib_f4 = (
                refmac_dir_f4 / f"refmac_operation_manifest.parent.{pid}.json"
            )
            d1_child_f4 = (
                refmac_dir_f4 / "refmac_r_factor_diagnostics.corrected.json"
            )
            m1_child_f4 = (
                refmac_dir_f4 / "refmac_operation_manifest.corrected.json"
            )

            m0_marker_bytes_f4 = (
                b'{"marker": "f4-same-child-m0-canonical", "preserve": true}\n'
            )
            m0_marker_sha_f4 = _sha256_bytes(m0_marker_bytes_f4)
            m0_marker_created_f4 = False
            orig_atomic_f4 = onesar_refmac._atomic_write_new_json_file
            written_by_path_f4: dict[str, dict[str, Any]] = {}
            writer_roots_f4: list[Path] = []
            double_eval_count_f4 = 0

            def _wrapped_atomic_f4(
                payload: Any,
                target_path: Path,
                *,
                root: Path,
            ) -> dict[str, Any]:
                nonlocal m0_marker_created_f4, double_eval_count_f4
                writer_roots_f4.append(root)
                if (
                    target_path == m0_child_f4
                    and root == refmac_dir_f4
                    and not m0_marker_created_f4
                ):
                    m0_child_f4.write_bytes(m0_marker_bytes_f4)
                    m0_marker_created_f4 = True
                effective_payload = payload
                if callable(payload) and target_path.name in (
                    "refmac_diagnostics.json",
                    "refmac_operation_manifest.json",
                    f"refmac_operation_manifest.parent.{pid}.json",
                    "refmac_r_factor_diagnostics.corrected.json",
                    "refmac_operation_manifest.corrected.json",
                ):

                    def _double_eval(dest: Path) -> Mapping[str, Any]:
                        nonlocal double_eval_count_f4
                        first_map = copy.deepcopy(dict(payload(dest)))
                        second_raw = payload(dest)
                        second_map = copy.deepcopy(dict(second_raw))
                        self._assert_repeated_derivation_idempotent(
                            first_map, second_map
                        )
                        double_eval_count_f4 += 1
                        return second_raw

                    effective_payload = _double_eval
                res = orig_atomic_f4(
                    effective_payload, target_path, root=root
                )
                written_by_path_f4[str(res["path"])] = copy.deepcopy(res)
                return res

            with patch.object(
                onesar_refmac,
                "_atomic_write_new_json_file",
                _wrapped_atomic_f4,
            ):
                with self.assertRaises(
                    onesar_refmac.RefmacCollectorError
                ) as cm_f4:
                    self._run_with_fake_ccp4(case_f4, _capture_success_runner)

            err_f4 = cm_f4.exception
            self.assertEqual(double_eval_count_f4, 4)
            self.assertTrue(
                all(r == refmac_dir_f4 for r in writer_roots_f4)
            )
            self.assertEqual(list(parent_dir_f4.iterdir()), [])
            self.assertEqual(err_f4.failed_stage, "refmac_raw_outputs")
            self.assertIsNone(err_f4.primary_cause)
            self.assertIsNone(err_f4.__cause__)
            self.assertIsNone(err_f4.terminal_cause)
            self.assertIs(err_f4.publication_pair_complete, True)
            self.assertIsNone(err_f4.publication_terminal_failure)
            self.assertEqual(err_f4.diagnostics_path, d1_child_f4)
            self.assertEqual(err_f4.manifest_path, m1_child_f4)

            self.assertEqual(m0_child_f4.read_bytes(), m0_marker_bytes_f4)
            self.assertEqual(
                _sha256_bytes(m0_child_f4.read_bytes()), m0_marker_sha_f4
            )

            d1_disk_f4 = self._reopen_and_verify_json_artifact(
                written_by_path_f4[str(d1_child_f4)]
            )
            m1_disk_f4 = self._reopen_and_verify_json_artifact(
                written_by_path_f4[str(m1_child_f4)]
            )
            self.assertEqual(
                d1_disk_f4, dict(err_f4.diagnostics_payload or {})
            )
            self.assertEqual(m1_disk_f4, dict(err_f4.manifest_payload or {}))
            self._verify_publication_history_rows(
                err_f4.publication_history,
                [
                    ("D0", "diagnostics_json", d0_child_f4),
                    ("M0", "manifest_json", m0_sib_f4),
                ],
                written_by_path_f4,
            )

            for payload_f4 in (d1_disk_f4, m1_disk_f4):
                self._assert_late_failure_proofs_and_gates(payload_f4)
                self._verify_prior_child_artifacts_preserved(
                    payload_f4, written_by_path_f4
                )
                self.assertEqual(
                    payload_f4["child_dir_persistence_failures"], []
                )
                self.assertIs(payload_f4["parent_retention_used"], False)
                self.assertIsNone(
                    payload_f4["actual_parent_retention_anchor_dir"]
                )
                self.assertEqual(
                    [f["failed_stage"] for f in payload_f4["failures"]],
                    ["refmac_raw_outputs"],
                )
                self.assertIs(
                    payload_f4["operation_checks"]["stage2_audits_succeeded"],
                    True,
                )
                self.assertIs(
                    payload_f4["preregistered_gates"][
                        "gate_1_immutable_input_and_toolchain_admission"
                    ]["proven"],
                    True,
                )
                self.assertIs(
                    payload_f4["preregistered_gates"][
                        "gate_2_native_log_extraction_and_internal_reconciliation"
                    ]["proven"],
                    True,
                )

        with self.subTest(
            fixture="F5_same_child_m0_then_d1_collision"
        ):
            case_f5 = f"case38_f5_same_child_m0_d1_collision_{pid}"
            ev_root_f5 = self.repo_root / "runs" / case_f5
            refmac_dir_f5 = ev_root_f5 / "refmac"
            parent_dir_f5 = ev_root_f5 / "refmac_parent_retention"
            d0_child_f5 = refmac_dir_f5 / "refmac_diagnostics.json"
            m0_child_f5 = refmac_dir_f5 / "refmac_operation_manifest.json"
            m0_sib_f5 = (
                refmac_dir_f5 / f"refmac_operation_manifest.parent.{pid}.json"
            )
            d1_child_f5 = (
                refmac_dir_f5 / "refmac_r_factor_diagnostics.corrected.json"
            )
            d1_sib_f5 = (
                refmac_dir_f5
                / f"refmac_r_factor_diagnostics.corrected.parent.{pid}.json"
            )
            m1_child_f5 = (
                refmac_dir_f5 / "refmac_operation_manifest.corrected.json"
            )

            m0_marker_bytes_f5 = (
                b'{"marker": "f5-m0-canonical", "preserve": true}\n'
            )
            d1_marker_bytes_f5 = (
                b'{"marker": "f5-d1-canonical", "preserve": true}\n'
            )
            m0_created_f5 = False
            d1_created_f5 = False
            orig_atomic_f5 = onesar_refmac._atomic_write_new_json_file
            written_by_path_f5: dict[str, dict[str, Any]] = {}
            attempted_targets_f5: list[tuple[Path, Path]] = []

            def _wrapped_atomic_f5(
                payload: Any,
                target_path: Path,
                *,
                root: Path,
            ) -> dict[str, Any]:
                nonlocal m0_created_f5, d1_created_f5
                attempted_targets_f5.append((target_path, root))
                if (
                    target_path == m0_child_f5
                    and root == refmac_dir_f5
                    and not m0_created_f5
                ):
                    m0_child_f5.write_bytes(m0_marker_bytes_f5)
                    m0_created_f5 = True
                elif (
                    target_path == d1_child_f5
                    and root == refmac_dir_f5
                    and not d1_created_f5
                ):
                    d1_child_f5.write_bytes(d1_marker_bytes_f5)
                    d1_created_f5 = True
                effective_payload = payload
                if callable(payload) and target_path.name.startswith(
                    (
                        "refmac_diagnostics",
                        "refmac_operation_manifest",
                        "refmac_r_factor_diagnostics",
                    )
                ):

                    def _double_eval_f5(dest: Path) -> Mapping[str, Any]:
                        first_map = copy.deepcopy(dict(payload(dest)))
                        second_raw = payload(dest)
                        second_map = copy.deepcopy(dict(second_raw))
                        self._assert_repeated_derivation_idempotent(
                            first_map, second_map
                        )
                        return second_raw

                    effective_payload = _double_eval_f5
                res = orig_atomic_f5(
                    effective_payload, target_path, root=root
                )
                written_by_path_f5[str(res["path"])] = copy.deepcopy(res)
                return res

            with patch.object(
                onesar_refmac,
                "_atomic_write_new_json_file",
                _wrapped_atomic_f5,
            ):
                with self.assertRaises(
                    onesar_refmac.RefmacCollectorError
                ) as cm_f5:
                    self._run_with_fake_ccp4(case_f5, _capture_success_runner)

            err_f5 = cm_f5.exception
            self.assertEqual(err_f5.failed_stage, "refmac_raw_outputs")
            self.assertIsNone(err_f5.primary_cause)
            self.assertIsNone(err_f5.__cause__)
            self.assertIsInstance(err_f5.terminal_cause, FileExistsError)
            self.assertIs(err_f5.publication_pair_complete, False)
            self.assertIsNone(err_f5.diagnostics_path)
            self.assertIsNone(err_f5.manifest_path)
            self.assertFalse(os.path.lexists(m1_child_f5))
            self.assertNotIn(
                (m1_child_f5, refmac_dir_f5), attempted_targets_f5
            )
            self.assertTrue(
                all(r == refmac_dir_f5 for _, r in attempted_targets_f5)
            )
            self.assertEqual(list(parent_dir_f5.iterdir()), [])
            self.assertEqual(m0_child_f5.read_bytes(), m0_marker_bytes_f5)
            self.assertEqual(d1_child_f5.read_bytes(), d1_marker_bytes_f5)

            term_f5 = err_f5.publication_terminal_failure
            self.assertIsInstance(term_f5, Mapping)
            assert isinstance(term_f5, Mapping)
            self.assertEqual(
                term_f5["stage"], "persist_corrected_diagnostics_d1"
            )
            self.assertEqual(
                term_f5["rejected_destination"], str(d1_child_f5)
            )
            self.assertEqual(term_f5["exception_type"], "FileExistsError")

            self._verify_publication_history_rows(
                err_f5.publication_history,
                [
                    ("D0", "diagnostics_json", d0_child_f5),
                    ("M0", "manifest_json", m0_sib_f5),
                    ("D1", "diagnostics_json", d1_sib_f5),
                ],
                written_by_path_f5,
            )

            assert isinstance(err_f5.diagnostics_payload, Mapping)
            assert isinstance(err_f5.manifest_payload, Mapping)
            for payload_f5 in (
                err_f5.diagnostics_payload,
                err_f5.manifest_payload,
            ):
                self._assert_late_failure_proofs_and_gates(payload_f5)
                self._verify_prior_child_artifacts_preserved(
                    payload_f5, written_by_path_f5
                )
                self.assertEqual(
                    payload_f5["child_dir_persistence_failures"], []
                )
                self.assertIs(payload_f5["parent_retention_used"], False)
                self.assertEqual(
                    [f["failed_stage"] for f in payload_f5["failures"]],
                    ["refmac_raw_outputs", "persist_corrected_diagnostics_d1"],
                )

        with self.subTest(
            fixture="F6_rejected_correction_write_plus_current_child_mode_refresh"
        ):
            case_f6 = f"case38_f6_rejected_d1_mode_refresh_{pid}"
            ev_root_f6 = self.repo_root / "runs" / case_f6
            refmac_dir_f6 = ev_root_f6 / "refmac"
            parent_dir_f6 = ev_root_f6 / "refmac_parent_retention"
            d0_child_f6 = refmac_dir_f6 / "refmac_diagnostics.json"
            m0_child_f6 = refmac_dir_f6 / "refmac_operation_manifest.json"
            m0_sib_f6 = (
                refmac_dir_f6 / f"refmac_operation_manifest.parent.{pid}.json"
            )
            d1_child_f6 = (
                refmac_dir_f6 / "refmac_r_factor_diagnostics.corrected.json"
            )
            m1_child_f6 = (
                refmac_dir_f6 / "refmac_operation_manifest.corrected.json"
            )

            m0_marker_bytes_f6 = (
                b'{"marker": "f6-m0-canonical", "preserve": true}\n'
            )
            d1_exc_f6 = PermissionError(
                errno.EACCES,
                "F6 injected D1 child write rejection after mode change",
                str(d1_child_f6),
            )
            m0_created_f6 = False
            d1_attempts_f6 = 0
            orig_mode_holder_f6: list[int] = []
            new_mode_holder_f6: list[int] = []
            orig_atomic_f6 = onesar_refmac._atomic_write_new_json_file
            written_by_path_f6: dict[str, dict[str, Any]] = {}
            attempted_targets_f6: list[tuple[Path, Path]] = []

            def _wrapped_atomic_f6(
                payload: Any,
                target_path: Path,
                *,
                root: Path,
            ) -> dict[str, Any]:
                nonlocal m0_created_f6, d1_attempts_f6
                attempted_targets_f6.append((target_path, root))
                if (
                    target_path == m0_child_f6
                    and root == refmac_dir_f6
                    and not m0_created_f6
                ):
                    m0_child_f6.write_bytes(m0_marker_bytes_f6)
                    m0_created_f6 = True
                elif target_path == d1_child_f6 and root == refmac_dir_f6:
                    d1_attempts_f6 += 1
                    cur_mode = stat.S_IMODE(os.lstat(refmac_dir_f6).st_mode)
                    orig_mode_holder_f6.append(cur_mode)
                    alt_mode = 0o700 if cur_mode != 0o700 else 0o750
                    new_mode_holder_f6.append(alt_mode)
                    os.chmod(refmac_dir_f6, alt_mode)
                    raise d1_exc_f6
                res = orig_atomic_f6(payload, target_path, root=root)
                written_by_path_f6[str(res["path"])] = copy.deepcopy(res)
                return res

            try:
                with patch.object(
                    onesar_refmac,
                    "_atomic_write_new_json_file",
                    _wrapped_atomic_f6,
                ):
                    with self.assertRaises(
                        onesar_refmac.RefmacCollectorError
                    ) as cm_f6:
                        self._run_with_fake_ccp4(
                            case_f6, _capture_success_runner
                        )
            finally:
                if orig_mode_holder_f6 and refmac_dir_f6.exists():
                    os.chmod(refmac_dir_f6, orig_mode_holder_f6[0])

            err_f6 = cm_f6.exception
            self.assertEqual(d1_attempts_f6, 1)
            self.assertFalse(os.path.lexists(d1_child_f6))
            self.assertFalse(os.path.lexists(m1_child_f6))
            self.assertNotIn(
                (m1_child_f6, refmac_dir_f6), attempted_targets_f6
            )
            self.assertTrue(
                all(r == refmac_dir_f6 for _, r in attempted_targets_f6)
            )
            self.assertEqual(list(parent_dir_f6.iterdir()), [])
            self.assertEqual(err_f6.failed_stage, "refmac_raw_outputs")
            self.assertIsNone(err_f6.primary_cause)
            self.assertIsNone(err_f6.__cause__)
            self.assertIs(err_f6.terminal_cause, d1_exc_f6)
            self.assertIs(err_f6.publication_pair_complete, False)
            self.assertIsNone(err_f6.diagnostics_path)
            self.assertIsNone(err_f6.manifest_path)

            term_f6 = err_f6.publication_terminal_failure
            self.assertIsInstance(term_f6, Mapping)
            assert isinstance(term_f6, Mapping)
            self.assertEqual(
                term_f6["stage"], "persist_corrected_diagnostics_d1"
            )
            self.assertEqual(
                term_f6["rejected_destination"], str(d1_child_f6)
            )
            self.assertEqual(term_f6["exception_type"], "PermissionError")
            self.assertEqual(
                term_f6["exception_message"], str(d1_exc_f6)
            )
            self.assertEqual(term_f6["errno"], errno.EACCES)

            self._verify_publication_history_rows(
                err_f6.publication_history,
                [
                    ("D0", "diagnostics_json", d0_child_f6),
                    ("M0", "manifest_json", m0_sib_f6),
                ],
                written_by_path_f6,
            )

            assert isinstance(err_f6.diagnostics_payload, Mapping)
            assert isinstance(err_f6.manifest_payload, Mapping)
            for payload_f6 in (
                err_f6.diagnostics_payload,
                err_f6.manifest_payload,
            ):
                self._assert_late_failure_proofs_and_gates(payload_f6)
                self._verify_prior_child_artifacts_preserved(
                    payload_f6, written_by_path_f6
                )
                post_child_f6 = payload_f6["refmac_directory_post_run"]
                self.assertIs(post_child_f6["identity_verified"], True)
                self.assertEqual(post_child_f6["mode"], new_mode_holder_f6[0])
                self.assertIs(post_child_f6["mode_changed"], True)
                self.assertIs(post_child_f6["writable_post_run"], False)
                self.assertEqual(
                    post_child_f6["write_error"],
                    f"PermissionError: {d1_exc_f6}",
                )
                self.assertEqual(
                    post_child_f6["write_exception_type"], "PermissionError"
                )
                self.assertEqual(
                    post_child_f6["write_exception_message"], str(d1_exc_f6)
                )
                self.assertEqual(post_child_f6["write_errno"], errno.EACCES)
                self.assertEqual(
                    payload_f6["child_dir_persistence_failures"], []
                )
                self.assertIs(payload_f6["parent_retention_used"], True)
                self.assertIsNone(
                    payload_f6["actual_parent_retention_anchor_dir"]
                )

    def test_late_publication_failure_and_collision_ordering_invariants(
        self,
    ) -> None:
        """Case 39 (Fixtures F7a, F7b, F8): Persistence/parent-identity before final collision vs collision before later manifest failure retain both facts and the first cause."""
        pid = os.getpid()

        def _capture_success_runner(
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
            self._write_capture_success_outputs(
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
                stdout=SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG,
                stderr="",
            )

        with self.subTest(fixture="F7a_persistence_before_final_collision"):
            case_f7a = f"case39_f7a_persistence_before_collision_{pid}"
            ev_root_f7a = self.repo_root / "runs" / case_f7a
            refmac_dir_f7a = ev_root_f7a / "refmac"
            parent_dir_f7a = ev_root_f7a / "refmac_parent_retention"
            d0_child_f7a = refmac_dir_f7a / "refmac_diagnostics.json"
            d0_parent_f7a = parent_dir_f7a / "refmac_diagnostics.json"
            m0_parent_f7a = parent_dir_f7a / "refmac_operation_manifest.json"
            m0_parent_sib_f7a = (
                parent_dir_f7a
                / f"refmac_operation_manifest.parent.{pid}.json"
            )
            d1_parent_f7a = (
                parent_dir_f7a / "refmac_r_factor_diagnostics.corrected.json"
            )
            m1_parent_f7a = (
                parent_dir_f7a / "refmac_operation_manifest.corrected.json"
            )

            d0_exc_f7a = PermissionError(
                errno.EACCES,
                "F7a D0 child write failure before parent M0 collision",
                str(d0_child_f7a),
            )
            m0_marker_bytes_f7a = (
                b'{"marker": "f7a-parent-m0-canonical", "preserve": true}\n'
            )
            m0_marker_created_f7a = False
            orig_atomic_f7a = onesar_refmac._atomic_write_new_json_file
            written_by_path_f7a: dict[str, dict[str, Any]] = {}

            def _wrapped_atomic_f7a(
                payload: Any,
                target_path: Path,
                *,
                root: Path,
            ) -> dict[str, Any]:
                nonlocal m0_marker_created_f7a
                if target_path == d0_child_f7a and root == refmac_dir_f7a:
                    raise d0_exc_f7a
                if (
                    target_path == m0_parent_f7a
                    and root == parent_dir_f7a
                    and not m0_marker_created_f7a
                ):
                    m0_parent_f7a.write_bytes(m0_marker_bytes_f7a)
                    m0_marker_created_f7a = True
                effective_payload = payload
                if callable(payload) and target_path.name.startswith(
                    (
                        "refmac_diagnostics",
                        "refmac_operation_manifest",
                        "refmac_r_factor_diagnostics",
                    )
                ):

                    def _double_eval_f7a(dest: Path) -> Mapping[str, Any]:
                        first_map = copy.deepcopy(dict(payload(dest)))
                        second_raw = payload(dest)
                        second_map = copy.deepcopy(dict(second_raw))
                        self._assert_repeated_derivation_idempotent(
                            first_map, second_map
                        )
                        return second_raw

                    effective_payload = _double_eval_f7a
                res = orig_atomic_f7a(
                    effective_payload, target_path, root=root
                )
                written_by_path_f7a[str(res["path"])] = copy.deepcopy(res)
                return res

            with patch.object(
                onesar_refmac,
                "_atomic_write_new_json_file",
                _wrapped_atomic_f7a,
            ):
                with self.assertRaises(
                    onesar_refmac.RefmacCollectorError
                ) as cm_f7a:
                    self._run_with_fake_ccp4(
                        case_f7a, _capture_success_runner
                    )

            err_f7a = cm_f7a.exception
            self.assertEqual(
                err_f7a.failed_stage,
                "persist_collector_artifacts_in_refmac_dir",
            )
            self.assertIs(err_f7a.primary_cause, d0_exc_f7a)
            self.assertIs(err_f7a.__cause__, d0_exc_f7a)
            self.assertIsNone(err_f7a.terminal_cause)
            self.assertIs(err_f7a.publication_pair_complete, True)
            self.assertEqual(err_f7a.diagnostics_path, d1_parent_f7a)
            self.assertEqual(err_f7a.manifest_path, m1_parent_f7a)
            self.assertEqual(
                m0_parent_f7a.read_bytes(), m0_marker_bytes_f7a
            )

            d1_disk_f7a = self._reopen_and_verify_json_artifact(
                written_by_path_f7a[str(d1_parent_f7a)]
            )
            m1_disk_f7a = self._reopen_and_verify_json_artifact(
                written_by_path_f7a[str(m1_parent_f7a)]
            )
            self._verify_publication_history_rows(
                err_f7a.publication_history,
                [
                    ("D0", "diagnostics_json", d0_parent_f7a),
                    ("M0", "manifest_json", m0_parent_sib_f7a),
                ],
                written_by_path_f7a,
            )
            for payload_f7a in (d1_disk_f7a, m1_disk_f7a):
                self._assert_late_failure_proofs_and_gates(payload_f7a)
                self._verify_prior_child_artifacts_preserved(
                    payload_f7a, written_by_path_f7a
                )
                self.assertEqual(
                    [f["failed_stage"] for f in payload_f7a["failures"]],
                    [
                        "persist_collector_artifacts_in_refmac_dir",
                        "refmac_raw_outputs",
                    ],
                )

        with self.subTest(fixture="F7b_parent_identity_before_final_collision"):
            case_f7b = f"case39_f7b_parent_id_before_collision_{pid}"
            ev_root_f7b = self.repo_root / "runs" / case_f7b
            refmac_dir_f7b = ev_root_f7b / "refmac"
            parent_dir_f7b = ev_root_f7b / "refmac_parent_retention"
            preserved_parent_f7b = (
                ev_root_f7b / f"refmac_parent_retention_preserved_{pid}"
            )
            d0_child_f7b = refmac_dir_f7b / "refmac_diagnostics.json"

            d0_exc_f7b = PermissionError(
                errno.EACCES,
                "F7b D0 child write failure after parent replacement",
                str(d0_child_f7b),
            )
            m0_marker_bytes_f7b = (
                b'{"marker": "f7b-anchor-m0-canonical", "preserve": true}\n'
            )
            parent_swapped_f7b = False
            m0_marker_created_f7b = False
            observed_anchors_f7b: list[Path | None] = []
            observed_parent_id_causes_f7b: list[Exception] = []

            orig_atomic_f7b = onesar_refmac._atomic_write_new_json_file
            orig_ensure_anchor_f7b = (
                onesar_refmac._ensure_verified_root_exclusive_fallback_dir
            )
            orig_verify_dir_f7b = (
                onesar_refmac._verify_refmac_directory_post_run
            )
            written_by_path_f7b: dict[str, dict[str, Any]] = {}

            def _wrapped_verify_dir_f7b(
                refmac_dir: Path,
                *,
                refmac_dir_baseline: Mapping[str, Any] | None = None,
                caught_exceptions: list[Exception] | None = None,
            ) -> dict[str, Any]:
                local_caught: list[Exception] = []
                res = orig_verify_dir_f7b(
                    refmac_dir,
                    refmac_dir_baseline=refmac_dir_baseline,
                    caught_exceptions=local_caught,
                )
                if caught_exceptions is not None:
                    caught_exceptions.extend(local_caught)
                if refmac_dir == parent_dir_f7b and local_caught:
                    observed_parent_id_causes_f7b.extend(local_caught)
                return res

            def _wrapped_ensure_anchor_f7b(
                *args: Any, **kwargs: Any
            ) -> tuple[Path | None, dict[str, Any] | None, str | None]:
                anchor_dir, anchor_base, ev_err = orig_ensure_anchor_f7b(
                    *args, **kwargs
                )
                observed_anchors_f7b.append(anchor_dir)
                return anchor_dir, anchor_base, ev_err

            def _wrapped_atomic_f7b(
                payload: Any,
                target_path: Path,
                *,
                root: Path,
            ) -> dict[str, Any]:
                nonlocal parent_swapped_f7b, m0_marker_created_f7b
                if (
                    target_path == d0_child_f7b
                    and root == refmac_dir_f7b
                    and not parent_swapped_f7b
                ):
                    os.rename(parent_dir_f7b, preserved_parent_f7b)
                    parent_dir_f7b.mkdir(mode=0o755)
                    parent_swapped_f7b = True
                    raise d0_exc_f7b
                if (
                    observed_anchors_f7b
                    and observed_anchors_f7b[0] is not None
                    and root == observed_anchors_f7b[0]
                    and target_path
                    == observed_anchors_f7b[0]
                    / "refmac_operation_manifest.json"
                    and not m0_marker_created_f7b
                ):
                    target_path.write_bytes(m0_marker_bytes_f7b)
                    m0_marker_created_f7b = True
                effective_payload = payload
                if callable(payload) and target_path.name.startswith(
                    (
                        "refmac_diagnostics",
                        "refmac_operation_manifest",
                        "refmac_r_factor_diagnostics",
                    )
                ):

                    def _double_eval_f7b(dest: Path) -> Mapping[str, Any]:
                        first_map = copy.deepcopy(dict(payload(dest)))
                        second_raw = payload(dest)
                        second_map = copy.deepcopy(dict(second_raw))
                        self._assert_repeated_derivation_idempotent(
                            first_map, second_map
                        )
                        return second_raw

                    effective_payload = _double_eval_f7b
                res = orig_atomic_f7b(
                    effective_payload, target_path, root=root
                )
                written_by_path_f7b[str(res["path"])] = copy.deepcopy(res)
                return res

            with (
                patch.object(
                    onesar_refmac,
                    "_verify_refmac_directory_post_run",
                    _wrapped_verify_dir_f7b,
                ),
                patch.object(
                    onesar_refmac,
                    "_ensure_verified_root_exclusive_fallback_dir",
                    _wrapped_ensure_anchor_f7b,
                ),
                patch.object(
                    onesar_refmac,
                    "_atomic_write_new_json_file",
                    _wrapped_atomic_f7b,
                ),
            ):
                with self.assertRaises(
                    onesar_refmac.RefmacCollectorError
                ) as cm_f7b:
                    self._run_with_fake_ccp4(
                        case_f7b, _capture_success_runner
                    )

            err_f7b = cm_f7b.exception
            self.assertEqual(len(observed_anchors_f7b), 1)
            anchor_dir_f7b = observed_anchors_f7b[0]
            self.assertIsNotNone(anchor_dir_f7b)
            assert anchor_dir_f7b is not None
            self.assertGreaterEqual(len(observed_parent_id_causes_f7b), 1)
            first_parent_id_exc_f7b = observed_parent_id_causes_f7b[0]

            self.assertEqual(
                err_f7b.failed_stage, "verify_parent_retention_directory"
            )
            self.assertIs(err_f7b.primary_cause, first_parent_id_exc_f7b)
            self.assertIs(err_f7b.__cause__, first_parent_id_exc_f7b)
            self.assertIsNone(err_f7b.terminal_cause)
            self.assertIs(err_f7b.publication_pair_complete, True)

            d0_anchor_f7b = anchor_dir_f7b / "refmac_diagnostics.json"
            m0_anchor_sib_f7b = (
                anchor_dir_f7b
                / f"refmac_operation_manifest.parent.{pid}.json"
            )
            d1_anchor_f7b = (
                anchor_dir_f7b / "refmac_r_factor_diagnostics.corrected.json"
            )
            m1_anchor_f7b = (
                anchor_dir_f7b / "refmac_operation_manifest.corrected.json"
            )
            self.assertEqual(err_f7b.diagnostics_path, d1_anchor_f7b)
            self.assertEqual(err_f7b.manifest_path, m1_anchor_f7b)
            self.assertEqual(list(parent_dir_f7b.iterdir()), [])

            d1_disk_f7b = self._reopen_and_verify_json_artifact(
                written_by_path_f7b[str(d1_anchor_f7b)]
            )
            m1_disk_f7b = self._reopen_and_verify_json_artifact(
                written_by_path_f7b[str(m1_anchor_f7b)]
            )
            self._verify_publication_history_rows(
                err_f7b.publication_history,
                [
                    ("D0", "diagnostics_json", d0_anchor_f7b),
                    ("M0", "manifest_json", m0_anchor_sib_f7b),
                ],
                written_by_path_f7b,
            )
            for payload_f7b in (d1_disk_f7b, m1_disk_f7b):
                self._assert_late_failure_proofs_and_gates(payload_f7b)
                self._verify_prior_child_artifacts_preserved(
                    payload_f7b, written_by_path_f7b
                )
                self.assertEqual(
                    payload_f7b["actual_parent_retention_anchor_dir"],
                    str(anchor_dir_f7b),
                )
                self.assertEqual(
                    payload_f7b["actual_parent_retention_anchor_kind"],
                    "verified_evidence_root_exclusive_dir",
                )
                self.assertEqual(
                    [f["failed_stage"] for f in payload_f7b["failures"]],
                    [
                        "verify_parent_retention_directory",
                        "persist_collector_artifacts_in_refmac_dir",
                        "refmac_raw_outputs",
                    ],
                )

        with self.subTest(
            fixture="F8_collision_before_later_manifest_failure"
        ):
            case_f8 = f"case39_f8_collision_before_m0_fail_{pid}"
            ev_root_f8 = self.repo_root / "runs" / case_f8
            refmac_dir_f8 = ev_root_f8 / "refmac"
            parent_dir_f8 = ev_root_f8 / "refmac_parent_retention"
            d0_child_f8 = refmac_dir_f8 / "refmac_diagnostics.json"
            d0_child_sib_f8 = (
                refmac_dir_f8 / f"refmac_diagnostics.parent.{pid}.json"
            )
            m0_child_f8 = refmac_dir_f8 / "refmac_operation_manifest.json"
            m0_parent_f8 = parent_dir_f8 / "refmac_operation_manifest.json"
            d1_parent_f8 = (
                parent_dir_f8 / "refmac_r_factor_diagnostics.corrected.json"
            )
            m1_parent_f8 = (
                parent_dir_f8 / "refmac_operation_manifest.corrected.json"
            )

            d0_marker_bytes_f8 = (
                b'{"marker": "f8-d0-canonical-collision", "preserve": true}\n'
            )
            m0_exc_f8 = PermissionError(
                errno.EACCES,
                "F8 M0 child write failure after D0 collision",
                str(m0_child_f8),
            )
            d0_marker_created_f8 = False
            orig_atomic_f8 = onesar_refmac._atomic_write_new_json_file
            written_by_path_f8: dict[str, dict[str, Any]] = {}

            def _wrapped_atomic_f8(
                payload: Any,
                target_path: Path,
                *,
                root: Path,
            ) -> dict[str, Any]:
                nonlocal d0_marker_created_f8
                if (
                    target_path == d0_child_f8
                    and root == refmac_dir_f8
                    and not d0_marker_created_f8
                ):
                    d0_child_f8.write_bytes(d0_marker_bytes_f8)
                    d0_marker_created_f8 = True
                elif target_path == m0_child_f8 and root == refmac_dir_f8:
                    raise m0_exc_f8
                effective_payload = payload
                if callable(payload) and target_path.name.startswith(
                    (
                        "refmac_diagnostics",
                        "refmac_operation_manifest",
                        "refmac_r_factor_diagnostics",
                    )
                ):

                    def _double_eval_f8(dest: Path) -> Mapping[str, Any]:
                        first_map = copy.deepcopy(dict(payload(dest)))
                        second_raw = payload(dest)
                        second_map = copy.deepcopy(dict(second_raw))
                        self._assert_repeated_derivation_idempotent(
                            first_map, second_map
                        )
                        return second_raw

                    effective_payload = _double_eval_f8
                res = orig_atomic_f8(
                    effective_payload, target_path, root=root
                )
                written_by_path_f8[str(res["path"])] = copy.deepcopy(res)
                return res

            with patch.object(
                onesar_refmac,
                "_atomic_write_new_json_file",
                _wrapped_atomic_f8,
            ):
                with self.assertRaises(
                    onesar_refmac.RefmacCollectorError
                ) as cm_f8:
                    self._run_with_fake_ccp4(case_f8, _capture_success_runner)

            err_f8 = cm_f8.exception
            self.assertEqual(err_f8.failed_stage, "refmac_raw_outputs")
            self.assertIsNone(err_f8.primary_cause)
            self.assertIsNone(err_f8.__cause__)
            self.assertIsNone(err_f8.terminal_cause)
            self.assertIs(err_f8.publication_pair_complete, True)
            self.assertEqual(err_f8.diagnostics_path, d1_parent_f8)
            self.assertEqual(err_f8.manifest_path, m1_parent_f8)
            self.assertEqual(d0_child_f8.read_bytes(), d0_marker_bytes_f8)

            d1_disk_f8 = self._reopen_and_verify_json_artifact(
                written_by_path_f8[str(d1_parent_f8)]
            )
            m1_disk_f8 = self._reopen_and_verify_json_artifact(
                written_by_path_f8[str(m1_parent_f8)]
            )
            self._verify_publication_history_rows(
                err_f8.publication_history,
                [
                    ("D0", "diagnostics_json", d0_child_sib_f8),
                    ("M0", "manifest_json", m0_parent_f8),
                ],
                written_by_path_f8,
            )
            for payload_f8 in (d1_disk_f8, m1_disk_f8):
                self._assert_late_failure_proofs_and_gates(payload_f8)
                self._verify_prior_child_artifacts_preserved(
                    payload_f8, written_by_path_f8
                )
                self.assertEqual(
                    [f["failed_stage"] for f in payload_f8["failures"]],
                    [
                        "refmac_raw_outputs",
                        "persist_collector_artifacts_in_refmac_dir",
                    ],
                )
                child_rows_f8 = payload_f8["child_dir_persistence_failures"]
                self.assertEqual(len(child_rows_f8), 1)
                self.assertEqual(
                    child_rows_f8[0]["intended_path"], str(m0_child_f8)
                )
                self.assertIs(
                    child_rows_f8[0]["attempted_write_in_child_dir"], True
                )

    def test_late_publication_original_cause_and_structured_none_preservation(
        self,
    ) -> None:
        """Case 40 (Fixture F9): Original runner, timeout, preflight, and structured-None causes survive later D0 child + selected-parent M0 terminal publication failures."""
        pid = os.getpid()

        outside_bin_dir_f9 = self.repo_root / f"outside_bin_f9_{pid}"
        outside_bin_dir_f9.mkdir(parents=True, exist_ok=True)
        outside_refmac_f9 = outside_bin_dir_f9 / "refmac5"
        outside_refmac_f9.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        outside_refmac_f9.chmod(0o755)
        scoped_outside_env_f9 = dict(self.fake_ccp4.sourced_env)
        scoped_outside_env_f9["PATH"] = (
            f"{outside_bin_dir_f9}{os.pathsep}{self.fake_ccp4.sourced_env['PATH']}"
        )

        subcases: list[tuple[str, str]] = [
            ("runner_invocation_exception", "refmac_runner_invocation"),
            ("runner_timeout_exception", "refmac_timeout"),
            ("preflight_outside_prefix_exception", "resolve_ccp4_refmac_toolchain"),
            ("structured_argv_none_rejection", "refmac_argv_verification"),
        ]

        for sub_label, expected_primary_stage in subcases:
            with self.subTest(subcase=sub_label):
                case_f9 = f"case40_f9_{sub_label}_{pid}"
                ev_root_f9 = self.repo_root / "runs" / case_f9
                refmac_dir_f9 = ev_root_f9 / "refmac"
                parent_dir_f9 = ev_root_f9 / "refmac_parent_retention"
                d0_child_f9 = refmac_dir_f9 / "refmac_diagnostics.json"
                d0_parent_f9 = parent_dir_f9 / "refmac_diagnostics.json"
                m0_parent_f9 = (
                    parent_dir_f9 / "refmac_operation_manifest.json"
                )

                d0_child_exc_f9 = PermissionError(
                    errno.EACCES,
                    f"F9 ({sub_label}) D0 child write failure",
                    str(d0_child_f9),
                )
                m0_parent_exc_f9 = PermissionError(
                    errno.EPERM,
                    f"F9 ({sub_label}) selected-parent M0 write failure",
                    str(m0_parent_f9),
                )
                expected_primary_exc_holder: list[Exception | None] = []
                orig_atomic_f9 = onesar_refmac._atomic_write_new_json_file
                orig_resolve_tc_f9 = (
                    onesar_refmac._resolve_ccp4_refmac_toolchain
                )
                written_by_path_f9: dict[str, dict[str, Any]] = {}
                attempted_targets_f9: list[tuple[Path, Path]] = []

                def _wrapped_atomic_f9(
                    payload: Any,
                    target_path: Path,
                    *,
                    root: Path,
                ) -> dict[str, Any]:
                    attempted_targets_f9.append((target_path, root))
                    if (
                        target_path == d0_child_f9
                        and root == refmac_dir_f9
                    ):
                        raise d0_child_exc_f9
                    if (
                        target_path == m0_parent_f9
                        and root == parent_dir_f9
                    ):
                        raise m0_parent_exc_f9
                    res = orig_atomic_f9(payload, target_path, root=root)
                    written_by_path_f9[str(res["path"])] = copy.deepcopy(res)
                    return res

                def _wrapped_resolve_tc_f9() -> tuple[
                    dict[str, Any], dict[str, str], Path
                ]:
                    try:
                        return orig_resolve_tc_f9()
                    except Exception as exc:
                        expected_primary_exc_holder.append(exc)
                        raise

                def _runner_f9(
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
                    if sub_label == "runner_invocation_exception":
                        run_exc = OSError(
                            errno.ENOEXEC,
                            "F9 retained runner invocation OSError",
                        )
                        expected_primary_exc_holder.append(run_exc)
                        raise run_exc
                    if sub_label == "runner_timeout_exception":
                        to_exc = subprocess.TimeoutExpired(
                            cmd=argv, timeout=timeout
                        )
                        expected_primary_exc_holder.append(to_exc)
                        raise to_exc
                    if sub_label == "structured_argv_none_rejection":
                        self._write_capture_success_outputs(
                            xyzin, hklin, xyzout, hklout, log_path
                        )
                        expected_primary_exc_holder.append(None)
                        return subprocess.CompletedProcess(
                            args=None,  # type: ignore[arg-type]
                            returncode=0,
                            stdout=SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG,
                            stderr="",
                        )
                    raise AssertionError(
                        "runner must not be invoked when preflight fails"
                    )

                env_override_f9 = (
                    scoped_outside_env_f9
                    if sub_label == "preflight_outside_prefix_exception"
                    else None
                )
                with (
                    patch.object(
                        onesar_refmac,
                        "_resolve_ccp4_refmac_toolchain",
                        _wrapped_resolve_tc_f9,
                    ),
                    patch.object(
                        onesar_refmac,
                        "_atomic_write_new_json_file",
                        _wrapped_atomic_f9,
                    ),
                ):
                    with self.assertRaises(
                        onesar_refmac.RefmacCollectorError
                    ) as cm_f9:
                        self._run_with_fake_ccp4(
                            case_f9,
                            _runner_f9,
                            sourced_env_override=env_override_f9,
                        )

                err_f9 = cm_f9.exception
                self.assertEqual(len(expected_primary_exc_holder), 1)
                expected_primary_exc = expected_primary_exc_holder[0]

                self.assertEqual(err_f9.failed_stage, expected_primary_stage)
                if expected_primary_exc is None:
                    self.assertIsNone(err_f9.primary_cause)
                    self.assertIsNone(err_f9.__cause__)
                else:
                    self.assertIs(err_f9.primary_cause, expected_primary_exc)
                    self.assertIs(err_f9.__cause__, expected_primary_exc)
                self.assertIs(err_f9.terminal_cause, m0_parent_exc_f9)
                self.assertIs(err_f9.publication_pair_complete, False)
                self.assertIsNone(err_f9.diagnostics_path)
                self.assertIsNone(err_f9.manifest_path)

                term_f9 = err_f9.publication_terminal_failure
                self.assertIsInstance(term_f9, Mapping)
                assert isinstance(term_f9, Mapping)
                self.assertEqual(term_f9["stage"], "persist_manifest_m0")
                self.assertEqual(
                    term_f9["rejected_destination"], str(m0_parent_f9)
                )
                self.assertEqual(
                    term_f9["exception_type"], "PermissionError"
                )
                self.assertEqual(
                    term_f9["exception_message"], str(m0_parent_exc_f9)
                )
                self.assertEqual(term_f9["errno"], errno.EPERM)

                # Verify D0 alone is in publication_history and no D1/M1 or new anchor was attempted.
                self._verify_publication_history_rows(
                    err_f9.publication_history,
                    [("D0", "diagnostics_json", d0_parent_f9)],
                    written_by_path_f9,
                )
                for attempted_path, attempted_root in attempted_targets_f9:
                    self.assertIn(
                        attempted_root, (refmac_dir_f9, parent_dir_f9)
                    )
                    self.assertNotIn(
                        attempted_path.name,
                        (
                            "refmac_r_factor_diagnostics.corrected.json",
                            "refmac_operation_manifest.corrected.json",
                        ),
                    )

                assert isinstance(err_f9.diagnostics_payload, Mapping)
                assert isinstance(err_f9.manifest_payload, Mapping)
                for payload_f9 in (
                    err_f9.diagnostics_payload,
                    err_f9.manifest_payload,
                ):
                    self._assert_late_failure_proofs_and_gates(
                        payload_f9,
                        expect_xyzout_audit_model_preserved=(
                            sub_label == "structured_argv_none_rejection"
                        ),
                    )
                    self.assertEqual(
                        payload_f9["failed_stage"], expected_primary_stage
                    )
                    self.assertEqual(
                        payload_f9["failures"][0]["failed_stage"],
                        expected_primary_stage,
                    )
                    self.assertEqual(
                        payload_f9["failures"][-1]["failed_stage"],
                        "persist_manifest_m0",
                    )
                    self.assertIsNone(
                        payload_f9["actual_parent_retention_anchor_dir"]
                    )


if __name__ == "__main__":
    unittest.main()
