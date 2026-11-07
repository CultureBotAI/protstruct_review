#!/usr/bin/env python3
"""Focused hermetic tests for scripts/onesar_refmac.py (Tasks 302, 306, 309).

Covers the shared fixture foundation and bounded collector cases 1-11:
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

No CCP4, PHENIX, or gemmi binaries are executed.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable, Mapping
from unittest.mock import patch

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import onesar_refmac  # noqa: E402
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

_DECLARED_HKLOUT_LABEL_MAP: dict[str, str] = {
    "F-obs": "FP",
    "SIGF-obs": "SIGFP",
    "R-free-flags": "FREE",
}
_COLUMN_OR_COLSRC_RE = re.compile(
    r"^(COLUMN\s+|COLSRC\s+)(F-obs|SIGF-obs|R-free-flags)(\s+.*)$"
)

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


def _rewrite_projected_mtz_labels_for_capture_success(
    projected_mtz_bytes: bytes,
) -> tuple[bytes, int]:
    """Apply only the 6 declared COLUMN/COLSRC label-token edits to projected MTZ bytes.

    Leaves the 80-byte preamble and all reflection data words completely unchanged.
    """
    (hdr_loc_words,) = struct.unpack_from("<I", projected_mtz_bytes, 4)
    hdr_byte_offset = (hdr_loc_words - 1) * 4
    if hdr_byte_offset < 80 or hdr_byte_offset >= len(projected_mtz_bytes):
        raise ValueError(f"Invalid MTZ header offset {hdr_byte_offset}")

    prefix = projected_mtz_bytes[:hdr_byte_offset]
    rewritten_cards: list[bytes] = []
    edit_count = 0
    pos = hdr_byte_offset
    while pos + 80 <= len(projected_mtz_bytes):
        raw_card = projected_mtz_bytes[pos : pos + 80]
        card_str = raw_card.decode("ascii")
        match = _COLUMN_OR_COLSRC_RE.match(card_str)
        if match is not None:
            kw_prefix, old_label, suffix = match.groups()
            new_label = _DECLARED_HKLOUT_LABEL_MAP[old_label]
            padded_new_label = new_label.ljust(len(old_label))
            new_card_str = f"{kw_prefix}{padded_new_label}{suffix}"
            if len(new_card_str) != 80:
                raise AssertionError(
                    f"Rewritten MTZ card length {len(new_card_str)} != 80"
                )
            rewritten_cards.append(new_card_str.encode("ascii"))
            edit_count += 1
        else:
            rewritten_cards.append(raw_card)
        pos += 80

    trailer = projected_mtz_bytes[pos:]
    out_bytes = prefix + b"".join(rewritten_cards) + trailer
    return out_bytes, edit_count


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
        loaded = json.loads(raw_bytes.decode("utf-8"))
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
        hklout_bytes, edit_count = _rewrite_projected_mtz_labels_for_capture_success(
            hklin_path.read_bytes()
        )
        hklout_path.write_bytes(hklout_bytes)
        log_path.write_text(SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG, encoding="utf-8")
        return edit_count

    def test_actual_archive_complete_capture(self) -> None:
        """Case 1: Actual-archive complete capture, env/secret filtering, and false admission flags."""
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
        self.assertEqual(call["header_edit_count"], 6)
        self.assertEqual(call["keywords"], onesar_refmac.REFMAC_KEYWORDS)
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
            result["invocation"]["stdin_keywords"], onesar_refmac.REFMAC_KEYWORDS
        )
        self.assertEqual(
            result["invocation"]["stdin_keywords_lines"],
            list(onesar_refmac.REFMAC_KEYWORDS_LINES),
        )

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


if __name__ == "__main__":
    unittest.main()
