#!/usr/bin/env python3
"""Focused hermetic unit tests for diagnostic profile wiring in scripts/onesar_refmac.py (Tasks 639, 765, 775, 777, 778).

Covers:
1. Legacy default behavior (diagnostic_profile=None) remains schema_version 1,
   collector_stage "stage2_invocation_raw_retention_log_parse_and_output_audits",
   6 helper sources, stock CCP4 executable, and Gate 1 proven on clean synthetic capture.
2. Positive diagnostic capture with RefmacDiagnosticProfile:
   - Single runner call with unchanged 7-line NCYC 0 keywords, ccp4=False, and
     selected diagnostic executable distinct from preserved stock toolchain["refmac5_binary"].
   - Fixed child activation (REFMAC_DIAGNOSTIC_TRACE, DYLD_PRINT_LIBRARIES="1"),
     caller os.environ / sourced_env / diagnostic_profile immutability, and
     stripped secret environment markers in persisted JSON artifacts.
   - Combined refmac.log with dyld loader lines still parses cleanly and
     reconciles Gate 2.
   - All 4 collector-owned envelopes use schema_version 2 and collector_stage
     "instrumented_native_trace_capture_v1", while nested XML/HKL/XYZ audit
     JSONs remain schema_version 1.
   - Gate 1 proven is False with explicit separate-producer reason while
     operational_immutability_and_profile_checks_verified is True; all scientific,
     EVAL, QDS, canary, and batch eligibility flags are False.
   - onesar_records.verify_retained_refmac_rfactor_evidence rejects both the v2
     diagnostic manifest and a v1 manifest carrying the diagnostic collector_stage.
3. Symlink-alias helper entry in collector_helpers resolving to the actual
   imported module target, and structurally closed empty trace (event_count == 0)
   proving no scientific coverage.
4. Preflight rejections with zero runner calls and retained requested pins:
   - Untyped diagnostic_profile or non-R4 subject_id rejected before staging.
   - Unsupported profile_id rejected at validate_diagnostic_profile.
   - Writer-incompatible native_trace path rejected at validate_native_trace_path.
   - Conflicting inherited environment rejected at reject_conflicting_environment
     with plain ValueError (not ProfileValidationError) before _resolve_ccp4_refmac_toolchain.
   - Outside-prefix stock refmac5 rejected at resolve_ccp4_refmac_toolchain.
   - Mismatched caller manifest Pin (failed_check == "manifest_pin") and
     mismatched caller executable Pin (failed_check == "outer_manifest_shape")
     rejected at validate_diagnostic_profile with ProfileValidationError as primary_cause.
   - Independently repinned copy of a collector helper at a different path
     (passing generic validate_profile) rejected at
     verify_diagnostic_helper_role_join with both helper_source_baseline and
     profile_collector_helpers retained (#1163).
   - Pre-existing refmac_native_trace.jsonl collision rejected at
     verify_fresh_output_paths.
5. Post-launch failure retention (single runner call, no retry, raw trace bytes
   and first failure preserved):
   - Nonzero runner exit (refmac_returncode) with valid native trace.
   - Runner timeout (refmac_timeout) with omitted ordinary raw outputs (xyzout,
     hklout) and partial unclosed trace/log, preserving explicit missing output
     metadata, written log/trace hashes, and TimeoutExpired as primary_cause.
   - Truncated/unclosed native trace after returncode 0 failing at
     refmac_raw_outputs while preserving raw trace bytes and SHA-256.
   - Postflight profile file mutation and distinct profile file deletion
     detected by recheck_profile and joined into verify_input_immutability.
   - XMLOUT audit exception and unwritable child refmac_dir fallback to
     parent_retention_dir preserving reopened v2 envelope diagnostic provenance,
     requested pins, activation environment, primary failure metadata, and trace bytes.
   - Direct regression for _inspect_retained_native_trace_envelope failure paths
     (#1185): unknown progress on unexpected reader exception and zero streamed
     bytes / no prefix digest or size on skipped reader, with separate earlier
     raw observation preserved.
   - Integration regression proving all five distinct raw output observations
     precede both recheck_profile and inspect_native_trace_envelope (#1184), and
     combined runner/profile/trace failures retain the original runner exception
     as primary while both later audits run and retain their original causes.

No licensed CCP4/PHENIX tools or native processes are executed.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import ModuleType
from typing import Any, Callable, Mapping
import unittest
from unittest.mock import patch

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import audit_1sar_retained_evidence  # noqa: E402
import onesar_records  # noqa: E402
import onesar_refmac  # noqa: E402
import onesar_refmac_log  # noqa: E402
import onesar_rerun  # noqa: E402
import refmac_diagnostic_profile  # noqa: E402
from refmac_diagnostic_profile import (  # noqa: E402
    EXPECTED_RUNTIME_ABSENT_KEYS,
    EXPECTED_RUNTIME_ENV_KEYS,
    PROFILE_SCHEMA_ID,
    PROFILE_SUBJECT_ID,
    SUPPORTED_PROFILE_ID,
    UPSTREAM_COMMIT,
    UPSTREAM_TAG,
    FilePin,
    ProfileValidationError,
    RefmacDiagnosticProfile,
    _observe_regular_file_pin,
)
import refmac_diagnostic_trace  # noqa: E402
import t03_reflection_retention  # noqa: E402
import toolchain  # noqa: E402


REPO_ROOT = _SCRIPTS_DIR.parent
COMMITTED_ARCHIVE = REPO_ROOT / onesar_rerun.ARCHIVE_REL_PATH

ORDERED_HELPER_MODULES_AND_KEYS: tuple[tuple[str, str, ModuleType], ...] = (
    (
        "audit_1sar_retained_evidence.py",
        "audit_1sar_retained_evidence_py",
        audit_1sar_retained_evidence,
    ),
    ("onesar_refmac.py", "onesar_refmac_py", onesar_refmac),
    ("onesar_refmac_log.py", "onesar_refmac_log_py", onesar_refmac_log),
    ("onesar_rerun.py", "onesar_rerun_py", onesar_rerun),
    (
        "t03_reflection_retention.py",
        "t03_reflection_retention_py",
        t03_reflection_retention,
    ),
    ("toolchain.py", "toolchain_py", toolchain),
    (
        "refmac_diagnostic_profile.py",
        "refmac_diagnostic_profile_py",
        refmac_diagnostic_profile,
    ),
    (
        "refmac_diagnostic_trace.py",
        "refmac_diagnostic_trace_py",
        refmac_diagnostic_trace,
    ),
)

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

SYNTHETIC_DYLD_NCYC0_LOG = (
    "dyld[41234]: <11223344-5566-7788-99AA-BBCCDDEEFF00> /tmp/build/subdir/refmac5\n"
    "dyld[41234]: <AABBCCDD-EEFF-0011-2233-445566778899> /tmp/installed/lib/libccp4.dylib\n"
    + SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_file_pin_on_disk(path: Path | str) -> FilePin:
    obs = _observe_regular_file_pin(str(path))
    return FilePin(path=obs.path, sha256=obs.sha256, size_bytes=obs.size_bytes)


def _build_valid_native_trace_bytes(*, include_events: bool = True) -> bytes:
    header = {
        "record_type": "header",
        "schema_id": refmac_diagnostic_trace.TRACE_SCHEMA_ID,
        "decimal_encoding": refmac_diagnostic_trace.TRACE_DECIMAL_ENCODING,
        "default_real_kind": 4,
        "default_integer_kind": 4,
        "default_real_storage_size": 32,
        "default_integer_storage_size": 32,
        "radix": 2,
        "digits": 24,
        "minexponent": -125,
        "maxexponent": 128,
        "default_real_radix": 2,
        "default_real_digits": 24,
        "default_real_minexponent": -125,
        "default_real_maxexponent": 128,
        "default_integer_radix": 2,
        "default_integer_digits": 31,
    }
    lines: list[str] = [json.dumps(header, separators=(",", ":"))]
    if include_events:
        events = [
            {
                "sequence": 1,
                "event": "Cycle_Entry",
                "ncyc": 0,
                "rfactor": {"bits_hex": "3E400000", "decimal": "0.1875"},
            },
            {
                "sequence": 2,
                "event": "Cycle_Summary",
                "nref_used": 6532,
                "rfree": {"bits_hex": "3E800000", "decimal": "0.25"},
            },
        ]
        for ev in events:
            lines.append(json.dumps(ev, separators=(",", ":")))
        footer_count = len(events)
    else:
        footer_count = 0
    footer = {
        "record_type": "writer_close",
        "schema_id": refmac_diagnostic_trace.TRACE_SCHEMA_ID,
        "event": "writer_close",
        "record_count": footer_count,
    }
    lines.append(json.dumps(footer, separators=(",", ":")))
    return ("\n".join(lines) + "\n").encode("ascii")


class _DiagnosticCollectorFixture:
    """Self-contained fake CCP4 installation and validated diagnostic profile fixture."""

    def __init__(self, base_dir: Path) -> None:
        raw_root = base_dir / "diag_fixture"
        raw_root.mkdir(parents=True, exist_ok=True)
        self.root = raw_root.resolve(strict=True)
        self.support_dir = self.root / "support"
        self.support_dir.mkdir(parents=True, exist_ok=True)
        self.trees = {
            "vendor": self.root / "vendor",
            "prepared": self.root / "prepared",
            "build": self.root / "build",
        }
        for p in self.trees.values():
            p.mkdir(parents=True, exist_ok=True)

        self.installed_prefix = self.root / "installed"
        self.bin_dir = self.installed_prefix / "bin"
        self.lib_dir = self.installed_prefix / "lib"
        self.data_dir = self.lib_dir / "data"
        self.monomers_dir = self.data_dir / "monomers"
        self.include_dir = self.installed_prefix / "include"
        self.scr_dir = self.installed_prefix / "scr"
        for d in (
            self.bin_dir,
            self.lib_dir,
            self.data_dir,
            self.monomers_dir,
            self.include_dir,
            self.scr_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)

        self.setup_script = self.bin_dir / "ccp4.setup-sh"
        self.setup_script.write_text(
            "#!/bin/sh\n# Hermetic fake ccp4.setup-sh\n",
            encoding="utf-8",
        )
        self.installed_refmac = self.bin_dir / "refmac5"
        self.installed_refmac.write_text(
            "#!/bin/sh\n# Hermetic stock refmac5 binary\nexit 0\n",
            encoding="utf-8",
        )
        self.installed_refmac.chmod(0o755)

        self.secret_markers: dict[str, str] = {
            "GITHUB_TOKEN": "ghp_secret_marker_never_persist_9911",
            "OPENAI_API_KEY": "sk_secret_marker_never_persist_9913",
        }
        self.env_values: dict[str, str] = {
            "CBIN": str(self.bin_dir),
            "CCP4": str(self.installed_prefix),
            "CCP4_MASTER": str(self.installed_prefix.parent),
            "CCP4_OPEN": "UNKNOWN",
            "CCP4_SCR": str(self.scr_dir),
            "CETC": str(self.installed_prefix / "etc"),
            "CINCL": str(self.include_dir),
            "CLIB": str(self.lib_dir),
            "CLIBD": str(self.data_dir),
            "CLIBD_MON": str(self.monomers_dir) + "/",
            "GFORTRAN_UNBUFFERED_PRECONNECTED": "Y",
            "MMCIFDIC": str(self.lib_dir / "ccp4" / "cif_mmdic.lib"),
            "PATH": f"{self.bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin",
            "warpbin": str(self.installed_prefix / "arp_warp" / "bin"),
            "warpdoc": str(self.installed_prefix / "arp_warp" / "doc"),
        }
        assert set(self.env_values.keys()) == set(EXPECTED_RUNTIME_ENV_KEYS)
        self.sourced_env: dict[str, str] = {
            **self.env_values,
            **self.secret_markers,
        }

        with (
            patch.dict(
                os.environ,
                {"PROTSTRUCT_CCP4_SETUP": str(self.setup_script)},
                clear=False,
            ),
            patch.object(toolchain, "CCP4_SETUP", self.setup_script),
            patch.object(
                toolchain,
                "ccp4_environment",
                return_value=dict(self.sourced_env),
            ),
        ):
            self.installed_record, self.resolved_ccp4_env, _ = (
                onesar_refmac._resolve_ccp4_refmac_toolchain()
            )

        self.files: dict[str, dict[str, Any]] = {}
        self.roles: dict[str, list[str]] = {}
        self._by_lexical_path: dict[str, str] = {}
        self._build_profile_files_and_manifest()

    def _create_file(
        self,
        rel_path: str,
        content: str | None = None,
        *,
        executable: bool = False,
    ) -> Path:
        target = self.root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        text = content if content is not None else f"synthetic:{rel_path}\n"
        target.write_text(text, encoding="utf-8")
        if executable:
            target.chmod(0o755)
        return target

    def register_path(self, raw_path: Path | str) -> str:
        raw_str = str(raw_path)
        if raw_str not in self._by_lexical_path:
            self._by_lexical_path[raw_str] = f"item_{len(self._by_lexical_path)}"
        ident = self._by_lexical_path[raw_str]
        obs = _observe_regular_file_pin(raw_str)
        self.files[ident] = obs.to_manifest_row()
        return ident

    def _add_single_role(
        self,
        role_name: str,
        rel_path: str,
        content: str | None = None,
        *,
        executable: bool = False,
    ) -> Path:
        created = self._create_file(rel_path, content, executable=executable)
        self.roles[role_name] = [self.register_path(created)]
        return created

    def _build_profile_files_and_manifest(self) -> None:
        vendor_src = self._create_file("vendor/source.f", "C synthetic upstream\n")
        self._create_file("vendor/.hidden_vendor_cfg", "vendor_hidden=1\n")
        self._create_file(
            "prepared/source.f", vendor_src.read_text(encoding="utf-8")
        )
        self._create_file("prepared/.hidden_prepared_cfg", "prepared_hidden=1\n")
        self._create_file(
            "prepared/refmac_diagnostic_hooks.patch", "synthetic patch\n"
        )
        self._add_single_role(
            "source_manifest",
            "prepared/refmac_diagnostic_source_manifest.json",
            '{"schema_id": "protstruct_refmac_diagnostic_source_manifest_v1"}\n',
        )

        writer = self._add_single_role(
            "writer_input", "support/input/trace_writer.f90", "synthetic writer\n"
        )
        hooks = self._add_single_role(
            "hooks_input", "support/input/trace_hooks.f90", "synthetic hooks\n"
        )
        self._create_file(
            "prepared/trace_writer.f90", writer.read_text(encoding="utf-8")
        )
        self._create_file(
            "prepared/trace_hooks.f90", hooks.read_text(encoding="utf-8")
        )

        for role_name, fname in (
            ("preparation_receipt", "preparation-completed.json"),
            ("preparer", "prepare_refmac_diagnostic.py"),
            ("preparation_interpreter", "preparation-python"),
            ("source_auditor", "check-prepared-source.py"),
            ("source_audit", "source-audit.json"),
            ("source_audit_interpreter", "audit-python"),
            ("build_launch", "build-completed.json"),
            ("build_interpreter", "build-python"),
            ("build_qc", "composition-qc.json"),
            ("build_qc_implementation", "compose-diagnostic-profile.py"),
            ("runtime_observation", "runtime-observation.json"),
            ("runtime_observer", "observe-runtime.py"),
            ("launcher", "launch-attempt04.py"),
            ("collection_interpreter", "collection-python"),
        ):
            self._add_single_role(
                role_name,
                f"support/{fname}",
                "{}\n" if fname.endswith(".json") else None,
            )

        for role_name, orig_name, copy_name in (
            ("build_driver", "build-instrumented-v2.py", "build-driver.py"),
            ("build_journal", "build-journal.py", "build-journal.py"),
            (
                "build_runtime_config",
                "installed-runtime.cmake",
                "installed-runtime.cmake",
            ),
        ):
            pair_text = f"pair:{role_name}:{copy_name}\n"
            orig_p = self._create_file(f"support/originals/{orig_name}", pair_text)
            copy_p = self._create_file(f"build/{copy_name}", pair_text)
            self.roles[role_name] = [
                self.register_path(orig_p),
                self.register_path(copy_p),
            ]

        self.roles["build_inventories"] = []
        for inv_name in (
            "toolchain-inventory.json",
            "effective-build-tools.json",
            "assembler-tool.json",
            "post-link-tools.json",
        ):
            inv_text = f'{{"inventory": "{inv_name}"}}\n'
            orig_inv = self._create_file(f"support/originals/{inv_name}", inv_text)
            copy_inv = self._create_file(f"build/{inv_name}", inv_text)
            self.roles["build_inventories"].extend(
                [self.register_path(orig_inv), self.register_path(copy_inv)]
            )

        self.roles["build_external_inputs"] = [
            self.register_path(self._create_file("support/compiler-input.txt"))
        ]
        self._add_single_role(
            "build_receipt",
            "build/build-receipt.json",
            '{"contract": "protstruct_instrumented_build_receipt_v2"}\n',
        )
        self._add_single_role(
            "linked_executable",
            "build/refmac5.linked-unrelocated",
            "synthetic linked binary\n",
            executable=True,
        )
        self.diagnostic_executable_path = self._add_single_role(
            "diagnostic_executable",
            "build/subdir/refmac5",
            "#!/bin/sh\n# Hermetic instrumented diagnostic refmac5 binary\nexit 0\n",
            executable=True,
        )
        self._create_file(
            "build/ordinary_object.o", "ordinary build object without role\n"
        )

        self.roles["ccp4_setup"] = [self.register_path(self.setup_script)]
        self.roles["installed_reference"] = [
            self.register_path(self.installed_refmac)
        ]
        self.roles["ccp4_setup_dependencies"] = [
            self.register_path(self._create_file("installed/setup-dep.sh"))
        ]
        self.roles["runtime_images"] = [
            self.register_path(self._create_file("installed/lib/libccp4.dylib"))
        ]

        # Bind collector_helpers directly to the 8 imported repository helper modules
        self.roles["collector_helpers"] = [
            self.register_path(Path(mod.__file__).resolve(strict=True))
            for _mod_name, _key, mod in ORDERED_HELPER_MODULES_AND_KEYS
        ]

        qc_base = self._create_file("support/qc-item.json", "{}\n")
        self.roles["qc_evidence"] = [self.register_path(qc_base)]

        for tree_path in self.trees.values():
            for member in sorted(tree_path.rglob("*")):
                if ".git" in member.parts:
                    continue
                if member.is_file():
                    self.register_path(member)

        sm_path = self.trees["prepared"] / "refmac_diagnostic_source_manifest.json"
        sm_payload: dict[str, Any] = {
            "schema_id": "protstruct_refmac_diagnostic_source_manifest_v1",
            "source_verification_status": "verified_upstream_commit_tree",
            "upstream_source": {
                "expected_commit": UPSTREAM_COMMIT,
                "expected_tag": UPSTREAM_TAG,
                "git_commit": UPSTREAM_COMMIT,
                "git_tag": UPSTREAM_TAG,
            },
        }
        sm_path.write_text(json.dumps(sm_payload, indent=2) + "\n", encoding="utf-8")
        self.register_path(sm_path)

        rt_path = self.support_dir / "runtime-observation.json"
        rt_observer_row = self.files[self.roles["runtime_observer"][0]]
        ccp4_setup_row = self.files[self.roles["ccp4_setup"][0]]
        setup_dep_rows = [
            self.files[fid] for fid in self.roles["ccp4_setup_dependencies"]
        ]
        rt_img_rows = [self.files[fid] for fid in self.roles["runtime_images"]]
        rt_payload: dict[str, Any] = {
            "contract": "primary_ccp4_runtime_configuration_observation_v1",
            "selected_nonsecret_environment": dict(self.env_values),
            "resolver_record": copy.deepcopy(self.installed_record),
            "observation_script": {
                "path": rt_observer_row["path"],
                "resolved": rt_observer_row["resolved_path"],
                "sha256": rt_observer_row["sha256"],
                "size_bytes": rt_observer_row["size_bytes"],
            },
            "setup_source_files": [
                {
                    "path": r["path"],
                    "resolved": r["resolved_path"],
                    "sha256": r["sha256"],
                    "size_bytes": r["size_bytes"],
                }
                for r in [ccp4_setup_row, *setup_dep_rows]
            ],
            "static_library_load_commands": [
                {
                    "index": idx,
                    "library": {
                        "path": r["path"],
                        "resolved": r["resolved_path"],
                        "sha256": r["sha256"],
                        "size_bytes": r["size_bytes"],
                    },
                }
                for idx, r in enumerate(rt_img_rows)
            ],
        }
        rt_path.write_text(json.dumps(rt_payload, indent=2) + "\n", encoding="utf-8")
        self.register_path(rt_path)

        br_path = self.trees["build"] / "build-receipt.json"
        diag_row = self.files[self.roles["diagnostic_executable"][0]]
        driver_row = self.files[self.roles["build_driver"][0]]
        journal_row = self.files[self.roles["build_journal"][0]]
        rt_cfg_row = self.files[self.roles["build_runtime_config"][0]]
        linked_row = self.files[self.roles["linked_executable"][0]]
        br_payload: dict[str, Any] = {
            "contract": "protstruct_instrumented_build_receipt_v2",
            "passed": True,
            "source": str(self.trees["prepared"]),
            "output": str(self.trees["build"]),
            "executable": {
                "path": diag_row["path"],
                "sha256": diag_row["sha256"],
                "size_bytes": diag_row["size_bytes"],
            },
            "driver_sha256": driver_row["sha256"],
            "journal_sha256": journal_row["sha256"],
            "runtime_config_sha256": rt_cfg_row["sha256"],
            "linked_executable_sha256": linked_row["sha256"],
        }
        br_path.write_text(json.dumps(br_payload, indent=2) + "\n", encoding="utf-8")
        self.register_path(br_path)

        sa_path = self.support_dir / "source-audit.json"
        sm_row = self.files[self.roles["source_manifest"][0]]
        auditor_row = self.files[self.roles["source_auditor"][0]]
        audit_interp_row = self.files[self.roles["source_audit_interpreter"][0]]
        patch_obs = _observe_regular_file_pin(
            str(self.trees["prepared"] / "refmac_diagnostic_hooks.patch")
        )
        vendor_inv: dict[str, dict[str, Any]] = {}
        prepared_inv: dict[str, dict[str, Any]] = {}
        for _fid, frow in sorted(self.files.items()):
            fpath = Path(str(frow["path"]))
            if fpath.is_relative_to(self.trees["vendor"]):
                rel_p = fpath.relative_to(self.trees["vendor"]).as_posix()
                vendor_inv[rel_p] = {
                    "sha256": frow["sha256"],
                    "size_bytes": frow["size_bytes"],
                    "git_mode": "100644",
                }
            elif fpath.is_relative_to(self.trees["prepared"]):
                rel_p = fpath.relative_to(self.trees["prepared"]).as_posix()
                prepared_inv[rel_p] = {
                    "sha256": frow["sha256"],
                    "size_bytes": frow["size_bytes"],
                }
        sa_payload: dict[str, Any] = {
            "contract": "primary_refmac_source_audit_v1",
            "passed": True,
            "source_root": str(self.trees["vendor"]),
            "prepared_root": str(self.trees["prepared"]),
            "upstream_commit": UPSTREAM_COMMIT,
            "python_optimization": 0,
            "literal_git_objects": True,
            "manifest_sha256": sm_row["sha256"],
            "auditor_sha256": auditor_row["sha256"],
            "auditor_path": auditor_row["path"],
            "patch_sha256": patch_obs.sha256,
            "interpreter": {
                "path": audit_interp_row["path"],
                "resolved_path": audit_interp_row["resolved_path"],
                "sha256": audit_interp_row["sha256"],
                "size_bytes": audit_interp_row["size_bytes"],
            },
            "original_git_blob_inventory": vendor_inv,
            "complete_prepared_inventory": prepared_inv,
        }
        sa_path.write_text(json.dumps(sa_payload, indent=2) + "\n", encoding="utf-8")
        self.register_path(sa_path)

        self.manifest_payload: dict[str, Any] = {
            "schema_id": PROFILE_SCHEMA_ID,
            "profile_id": SUPPORTED_PROFILE_ID,
            "subject_id": PROFILE_SUBJECT_ID,
            "upstream": {
                "commit": UPSTREAM_COMMIT,
                "tag": UPSTREAM_TAG,
            },
            "roots": {
                name: {
                    "path": str(tree_path),
                    "file_ids": [
                        fid
                        for fid, frow in sorted(self.files.items())
                        if Path(str(frow["path"])).is_relative_to(tree_path)
                    ],
                }
                for name, tree_path in self.trees.items()
            },
            "files": copy.deepcopy(self.files),
            "roles": copy.deepcopy(self.roles),
            "runtime_environment": {
                "observation_file_id": self.roles["runtime_observation"][0],
                "expected_values": dict(self.env_values),
                "expected_absent": list(EXPECTED_RUNTIME_ABSENT_KEYS),
            },
        }
        self.manifest_path = self.root / "diagnostic-profile.json"
        self.manifest_path.write_text(
            json.dumps(self.manifest_payload, indent=2) + "\n",
            encoding="utf-8",
        )
        self.profile = RefmacDiagnosticProfile(
            profile_id=SUPPORTED_PROFILE_ID,
            manifest=_make_file_pin_on_disk(self.manifest_path),
            executable=_make_file_pin_on_disk(self.diagnostic_executable_path),
        )


class TestOnesarRefmacDiagnosticWiring(unittest.TestCase):
    """Focused unit tests for RefmacDiagnosticProfile integration in onesar_refmac.py."""

    _tmp_dir: tempfile.TemporaryDirectory[str]
    base_dir: Path
    repo_root: Path
    fx: _DiagnosticCollectorFixture

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp_dir = tempfile.TemporaryDirectory()
        cls.base_dir = Path(cls._tmp_dir.name).resolve(strict=True)
        cls.repo_root = cls.base_dir / "repo"
        cls.repo_root.mkdir(parents=True, exist_ok=True)
        cls.fx = _DiagnosticCollectorFixture(cls.base_dir)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp_dir.cleanup()

    def _clean_ambient_env(
        self, extra: Mapping[str, str] | None = None
    ) -> dict[str, str]:
        cleaned = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("PROTSTRUCT_")
            and not k.startswith("DYLD_")
            and not k.startswith("LD_")
            and not k.startswith("GFORTRAN_")
            and k not in refmac_diagnostic_profile.FORBIDDEN_ENV_KEYS
            and k not in EXPECTED_RUNTIME_ABSENT_KEYS
        }
        cleaned["PROTSTRUCT_CCP4_SETUP"] = str(self.fx.setup_script)
        if extra is not None:
            cleaned.update(extra)
        return cleaned

    def _run_collector(
        self,
        case_name: str,
        runner: Callable[..., subprocess.CompletedProcess[str]],
        *,
        diagnostic_profile: RefmacDiagnosticProfile | None = None,
        subject_id: str = "R4",
        timeout: float = 900.0,
        evidence_root: Path | None = None,
        ambient_env_extra: Mapping[str, str] | None = None,
        sourced_env_override: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        target_root = (
            evidence_root
            if evidence_root is not None
            else (self.repo_root / "runs" / case_name)
        )
        env_to_return = (
            dict(sourced_env_override)
            if sourced_env_override is not None
            else dict(self.fx.sourced_env)
        )
        sourced_env_snapshot = copy.deepcopy(env_to_return)
        profile_snapshot = (
            (
                diagnostic_profile.profile_id,
                diagnostic_profile.manifest.to_dict(),
                diagnostic_profile.executable.to_dict(),
            )
            if isinstance(diagnostic_profile, RefmacDiagnosticProfile)
            else None
        )
        patched_ambient = self._clean_ambient_env(ambient_env_extra)
        with (
            patch.dict(
                os.environ,
                patched_ambient,
                clear=True,
            ),
            patch.object(toolchain, "CCP4_SETUP", self.fx.setup_script),
            patch.object(
                toolchain,
                "ccp4_environment",
                return_value=env_to_return,
            ),
        ):
            ambient_before = dict(os.environ)
            try:
                return onesar_refmac.run_refmac_rfactor_operation(
                    target_root,
                    subject_id=subject_id,
                    repo_root=self.repo_root,
                    archive_path=COMMITTED_ARCHIVE,
                    timeout=timeout,
                    require_no_protstruct_overrides=False,
                    runner=runner,
                    diagnostic_profile=diagnostic_profile,
                )
            finally:
                self.assertEqual(dict(os.environ), ambient_before)
                self.assertEqual(env_to_return, sourced_env_snapshot)
                if profile_snapshot is not None:
                    assert isinstance(diagnostic_profile, RefmacDiagnosticProfile)
                    self.assertEqual(
                        (
                            diagnostic_profile.profile_id,
                            diagnostic_profile.manifest.to_dict(),
                            diagnostic_profile.executable.to_dict(),
                        ),
                        profile_snapshot,
                    )

    @staticmethod
    def _reopen_json(artifact_ref: Mapping[str, Any] | None) -> dict[str, Any]:
        assert isinstance(artifact_ref, Mapping)
        path = Path(str(artifact_ref["path"]))
        raw = path.read_bytes()
        assert _sha256_bytes(raw) == artifact_ref["sha256"]
        assert len(raw) == artifact_ref["size_bytes"]
        return json.loads(raw.decode("utf-8"))

    @staticmethod
    def _expected_argv(executable_path: Path, evidence_root: Path) -> list[str]:
        inputs_dir = evidence_root / "inputs"
        refmac_dir = evidence_root / "refmac"
        return [
            str(executable_path),
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
    def _write_standard_outputs(
        xyzin_path: Path,
        hklin_path: Path,
        xyzout_path: Path,
        hklout_path: Path,
        log_path: Path,
        *,
        log_text: str = SYNTHETIC_DYLD_NCYC0_LOG,
        trace_path: Path | None = None,
        trace_bytes: bytes | None = None,
    ) -> None:
        xyzout_path.write_bytes(xyzin_path.read_bytes())
        hklout_path.write_bytes(hklin_path.read_bytes())
        log_path.write_text(log_text, encoding="utf-8")
        if trace_path is not None and trace_bytes is not None:
            trace_path.write_bytes(trace_bytes)

    def test_legacy_default_mode_remains_unchanged(self) -> None:
        """Default diagnostic_profile=None preserves schema_version 1, 6 helpers, and stock CCP4 executable."""
        evidence_root = self.repo_root / "runs" / "legacy_default"
        calls: list[dict[str, Any]] = []

        def fake_runner(
            xyzin: Path,
            hklin: Path,
            xyzout: Path,
            hklout: Path,
            log_path: Path,
            keywords: str,
            *,
            cwd: Path | None = None,
            timeout: float = 900.0,
            xml_output: Path | None = None,
            executable: Path | None = None,
            env: Mapping[str, str] | None = None,
            ccp4: bool = True,
        ) -> subprocess.CompletedProcess[str]:
            calls.append(
                {
                    "executable": executable,
                    "env": dict(env) if env is not None else None,
                    "keywords": keywords,
                    "timeout": timeout,
                    "ccp4": ccp4,
                    "cwd": cwd,
                    "xml_output": xml_output,
                }
            )
            self._write_standard_outputs(
                xyzin,
                hklin,
                xyzout,
                hklout,
                log_path,
                log_text=SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG,
            )
            return subprocess.CompletedProcess(
                args=self._expected_argv(self.fx.installed_refmac, evidence_root),
                returncode=0,
                stdout="",
                stderr="",
            )

        result = self._run_collector(
            "legacy_default",
            fake_runner,
            diagnostic_profile=None,
            evidence_root=evidence_root,
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["executable"], self.fx.installed_refmac)
        self.assertNotIn("REFMAC_DIAGNOSTIC_TRACE", calls[0]["env"])
        self.assertNotIn("DYLD_PRINT_LIBRARIES", calls[0]["env"])

        for envelope_ref in (
            result["pre_execution_checkpoint_json"],
            result["post_execution_checkpoint_json"],
            result["diagnostics_json"],
            result["manifest_json"],
        ):
            env_doc = self._reopen_json(envelope_ref)
            self.assertEqual(env_doc["schema_version"], 1)
            self.assertEqual(
                env_doc["collector_stage"],
                "stage2_invocation_raw_retention_log_parse_and_output_audits",
            )
            self.assertNotIn("diagnostic_profile", env_doc)
            self.assertNotIn("diagnostic_producer", env_doc)
            self.assertNotIn("native_trace_envelope", env_doc)

        self.assertEqual(len(result["helper_sources"]), 6)
        self.assertNotIn("refmac_diagnostic_profile_py", result["helper_sources"])
        self.assertNotIn("refmac_diagnostic_trace_py", result["helper_sources"])
        self.assertNotIn("native_trace", result["raw_outputs"])
        self.assertTrue(
            result["preregistered_gates"][
                "gate_1_immutable_input_and_toolchain_admission"
            ]["proven"]
        )

    def test_positive_diagnostic_capture_and_non_promotion_guards(self) -> None:
        """Positive diagnostic capture runs once with instrumented binary, dyld log, v2 envelopes, and false Gate 1 / admission flags."""
        direct_validated = refmac_diagnostic_profile.validate_profile(
            self.fx.profile,
            self.fx.installed_record,
            self.fx.resolved_ccp4_env,
            self.base_dir / "direct_validate_ev",
        )
        self.assertEqual(direct_validated.profile_id, SUPPORTED_PROFILE_ID)
        self.assertTrue(direct_validated.profile_files_verified)

        evidence_root = self.repo_root / "runs" / "diag_positive"
        calls: list[dict[str, Any]] = []
        valid_trace_bytes = _build_valid_native_trace_bytes(include_events=True)
        expected_trace_sha = _sha256_bytes(valid_trace_bytes)

        def fake_runner(
            xyzin: Path,
            hklin: Path,
            xyzout: Path,
            hklout: Path,
            log_path: Path,
            keywords: str,
            *,
            cwd: Path | None = None,
            timeout: float = 900.0,
            xml_output: Path | None = None,
            executable: Path | None = None,
            env: Mapping[str, str] | None = None,
            ccp4: bool = True,
        ) -> subprocess.CompletedProcess[str]:
            calls.append(
                {
                    "executable": executable,
                    "env": dict(env) if env is not None else None,
                    "keywords": keywords,
                    "timeout": timeout,
                    "ccp4": ccp4,
                    "cwd": cwd,
                    "xml_output": xml_output,
                }
            )
            assert env is not None
            trace_path = Path(env["REFMAC_DIAGNOSTIC_TRACE"])
            self._write_standard_outputs(
                xyzin,
                hklin,
                xyzout,
                hklout,
                log_path,
                log_text=SYNTHETIC_DYLD_NCYC0_LOG,
                trace_path=trace_path,
                trace_bytes=valid_trace_bytes,
            )
            return subprocess.CompletedProcess(
                args=self._expected_argv(
                    self.fx.diagnostic_executable_path, evidence_root
                ),
                returncode=0,
                stdout="",
                stderr="",
            )

        result = self._run_collector(
            "diag_positive",
            fake_runner,
            diagnostic_profile=self.fx.profile,
            evidence_root=evidence_root,
        )
        self.assertEqual(len(calls), 1)
        call = calls[0]
        self.assertEqual(call["executable"], self.fx.diagnostic_executable_path)
        self.assertNotEqual(call["executable"], self.fx.installed_refmac)

        expected_keywords_lines = [
            "LABIN FP=F-obs SIGFP=SIGF-obs FREE=R-free-flags",
            "FREE 1",
            "REFI BREF MIXED",
            "NCYC 0",
            "MONI MANY",
            "LABOUT FC=FC PHIC=PHIC FWT=FWT PHWT=PHWT DELFWT=DELFWT PHDELWT=PHDELWT FOM=FOM",
            "END",
        ]
        expected_keywords_text = "\n".join(expected_keywords_lines) + "\n"
        self.assertEqual(call["keywords"], expected_keywords_text)
        self.assertEqual(
            result["invocation"]["stdin_keywords"], expected_keywords_text
        )
        self.assertEqual(
            result["invocation"]["stdin_keywords_lines"], expected_keywords_lines
        )
        self.assertEqual(call["timeout"], 900.0)
        self.assertIs(call["ccp4"], False)

        expected_trace_path = evidence_root / "refmac" / "refmac_native_trace.jsonl"
        self.assertEqual(
            call["env"]["REFMAC_DIAGNOSTIC_TRACE"], str(expected_trace_path)
        )
        self.assertEqual(call["env"]["DYLD_PRINT_LIBRARIES"], "1")
        for env_k, env_v in self.fx.env_values.items():
            self.assertEqual(call["env"][env_k], env_v)
        for absent_k in EXPECTED_RUNTIME_ABSENT_KEYS:
            if absent_k != "REFMAC_DIAGNOSTIC_TRACE":
                self.assertNotIn(absent_k, call["env"])

        # Stock installed CCP4 binary remains in toolchain["refmac5_binary"]
        self.assertEqual(
            result["toolchain"]["refmac5_binary"]["resolved_path"],
            str(self.fx.installed_refmac.resolve(strict=True)),
        )
        for secret_key in self.fx.secret_markers:
            self.assertNotIn(
                secret_key, result["toolchain"]["bound_ccp4_configuration"]
            )

        # Separate diagnostic_producer record carries selected diagnostic executable
        producer = result["diagnostic_producer"]
        self.assertEqual(producer["profile_id"], SUPPORTED_PROFILE_ID)
        self.assertTrue(producer["profile_files_verified"])
        self.assertTrue(producer["helper_role_join_verified"])
        self.assertEqual(producer["runtime_image_coverage"], "not_assessed")
        self.assertTrue(producer["distinct_from_installed_reference"])
        self.assertEqual(
            producer["selected_executable"]["path"],
            str(self.fx.diagnostic_executable_path),
        )
        self.assertEqual(
            producer["installed_reference"]["path"],
            str(self.fx.installed_refmac.resolve(strict=True)),
        )

        # Helper source baseline has all 8 helpers and literal 8-role helper order verified
        self.assertEqual(len(result["helper_sources"]), 8)
        role_join = result["diagnostic_profile"]["collector_helper_role_join"]
        self.assertTrue(role_join["verified"])
        self.assertEqual(role_join["expected_count"], 8)
        self.assertEqual(len(role_join["entries"]), 8)
        self.assertEqual(role_join["mismatches"], [])
        expected_helper_order = [
            (
                "audit_1sar_retained_evidence.py",
                "audit_1sar_retained_evidence_py",
                Path(audit_1sar_retained_evidence.__file__).resolve(strict=True),
            ),
            (
                "onesar_refmac.py",
                "onesar_refmac_py",
                Path(onesar_refmac.__file__).resolve(strict=True),
            ),
            (
                "onesar_refmac_log.py",
                "onesar_refmac_log_py",
                Path(onesar_refmac_log.__file__).resolve(strict=True),
            ),
            (
                "onesar_rerun.py",
                "onesar_rerun_py",
                Path(onesar_rerun.__file__).resolve(strict=True),
            ),
            (
                "t03_reflection_retention.py",
                "t03_reflection_retention_py",
                Path(t03_reflection_retention.__file__).resolve(strict=True),
            ),
            (
                "toolchain.py",
                "toolchain_py",
                Path(toolchain.__file__).resolve(strict=True),
            ),
            (
                "refmac_diagnostic_profile.py",
                "refmac_diagnostic_profile_py",
                Path(refmac_diagnostic_profile.__file__).resolve(strict=True),
            ),
            (
                "refmac_diagnostic_trace.py",
                "refmac_diagnostic_trace_py",
                Path(refmac_diagnostic_trace.__file__).resolve(strict=True),
            ),
        ]
        for idx, (exp_mod_name, exp_key, exp_path) in enumerate(
            expected_helper_order
        ):
            entry = role_join["entries"][idx]
            self.assertEqual(entry["index"], idx)
            self.assertEqual(entry["expected_module_name"], exp_mod_name)
            self.assertEqual(entry["helper_baseline_key"], exp_key)
            self.assertEqual(
                entry["actual_helper"]["path"], str(exp_path)
            )
            self.assertEqual(
                entry["profile_role_observation"]["resolved_path"], str(exp_path)
            )
            self.assertTrue(entry["matches"])

        # All 4 collector-owned envelopes use literal schema_version 2 and literal stage
        pre_cp = self._reopen_json(result["pre_execution_checkpoint_json"])
        post_cp = self._reopen_json(result["post_execution_checkpoint_json"])
        diag_doc = self._reopen_json(result["diagnostics_json"])
        manifest_doc = self._reopen_json(result["manifest_json"])
        for env_doc in (pre_cp, post_cp, diag_doc, manifest_doc):
            self.assertEqual(env_doc["schema_version"], 2)
            self.assertEqual(
                env_doc["collector_stage"],
                "instrumented_native_trace_capture_v1",
            )
            self.assertEqual(
                env_doc["diagnostic_activation_environment"],
                {
                    "REFMAC_DIAGNOSTIC_TRACE": str(expected_trace_path),
                    "DYLD_PRINT_LIBRARIES": "1",
                },
            )
            self.assertEqual(
                env_doc["invocation"]["diagnostic_profile_id"],
                SUPPORTED_PROFILE_ID,
            )
            self.assertEqual(
                env_doc["invocation"]["native_trace_path"],
                str(expected_trace_path),
            )
            serialized = json.dumps(env_doc, sort_keys=True)
            for secret_key, secret_val in self.fx.secret_markers.items():
                self.assertNotIn(secret_key, serialized)
                self.assertNotIn(secret_val, serialized)

        # Nested audit artifacts remain schema_version 1
        for audit_ref in (
            result["xmlout_audit_json"],
            result["hklout_raw_export_json"],
            result["hklout_audit_json"],
            result["xyzout_audit_json"],
        ):
            audit_doc = self._reopen_json(audit_ref)
            self.assertEqual(audit_doc["schema_version"], 1)

        # Raw native trace and streaming envelope
        self.assertEqual(
            result["paths"]["native_trace_path"], str(expected_trace_path)
        )
        raw_trace = result["raw_outputs"]["native_trace"]
        self.assertTrue(raw_trace["exists"])
        self.assertTrue(raw_trace["is_regular_file"])
        self.assertFalse(raw_trace["is_symlink"])
        self.assertEqual(raw_trace["sha256"], expected_trace_sha)
        self.assertEqual(raw_trace["size_bytes"], len(valid_trace_bytes))

        trace_env = result["native_trace_envelope"]
        self.assertTrue(trace_env["valid"])
        self.assertTrue(trace_env["closed"])
        self.assertTrue(trace_env["has_events"])
        self.assertEqual(trace_env["event_count"], 2)
        self.assertEqual(trace_env["footer_record_count"], 2)
        self.assertIs(trace_env["scientific_coverage_proven"], False)
        self.assertEqual(result["audits"]["native_trace_envelope"], trace_env)

        # Dyld lines in refmac.log did not break log parsing or Gate 2
        self.assertTrue(result["operation_checks"]["native_r_pair_parsed"])
        self.assertTrue(result["operation_checks"]["ncyc_zero_requested_and_echoed"])
        self.assertTrue(
            result["preregistered_gates"][
                "gate_2_native_log_extraction_and_internal_reconciliation"
            ]["proven"]
        )

        # Gate 1 is False because a distinct diagnostic producer was executed
        gate1 = result["preregistered_gates"][
            "gate_1_immutable_input_and_toolchain_admission"
        ]
        self.assertIs(gate1["proven"], False)
        self.assertIs(
            gate1["operational_immutability_and_profile_checks_verified"], True
        )
        self.assertIn("separate instrumented producer binary", gate1["reason"])
        self.assertIs(result["all_preregistered_gates_passed"], False)
        self.assertEqual(result["status"], "diagnostic_captured_gates_unproven")

        # Non-promotion / eligibility flags are all False
        for doc in (diag_doc, manifest_doc):
            for flag in (
                "canonical_eval_qds_eligible",
                "eval_admission_eligible",
                "qds_admission_eligible",
                "canary_admission_eligible",
                "scientific_admission_proven",
                "batch_execution_eligible",
                "all_preregistered_gates_passed",
            ):
                self.assertIs(doc[flag], False, f"{flag} must be False")

        # 1. onesar_records.verify_retained_refmac_rfactor_evidence rejects the v2 diagnostic manifest
        with self.assertRaisesRegex(
            onesar_records.RefmacRetainedVerificationError,
            r"refmac_operation_manifest: expected integer schema_version == 1, got 2",
        ):
            onesar_records.verify_retained_refmac_rfactor_evidence(
                evidence_root,
                subject_id="R4",
                manifest_reference=result["manifest_json"],
                repo_root=self.repo_root,
            )

        # 2. Independently test schema_version == 1 + diagnostic collector_stage refusal
        v1_diag_stage_manifest = dict(manifest_doc)
        v1_diag_stage_manifest["schema_version"] = 1
        copied_v1_path = (
            evidence_root / "refmac" / "copied_v1_diag_stage_manifest.json"
        )
        copied_v1_bytes = (
            json.dumps(v1_diag_stage_manifest, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        copied_v1_path.write_bytes(copied_v1_bytes)
        copied_v1_ref = {
            "path": str(copied_v1_path),
            "sha256": _sha256_bytes(copied_v1_bytes),
            "size_bytes": len(copied_v1_bytes),
        }
        with self.assertRaisesRegex(
            onesar_records.RefmacRetainedVerificationError,
            r"refmac_operation_manifest\.collector_stage: expected 'stage2_invocation_raw_retention_log_parse_and_output_audits', got 'instrumented_native_trace_capture_v1'",
        ):
            onesar_records.verify_retained_refmac_rfactor_evidence(
                evidence_root,
                subject_id="R4",
                manifest_reference=copied_v1_ref,
                repo_root=self.repo_root,
            )

    def test_symlink_helper_alias_and_empty_closed_trace_prove_no_coverage(
        self,
    ) -> None:
        """Symlink alias in collector_helpers passes role join if resolved target matches; closed empty trace has has_events=False."""
        with tempfile.TemporaryDirectory() as tmp:
            custom_fx = _DiagnosticCollectorFixture(Path(tmp))
            # Replace collector_helpers[2] (onesar_refmac_log.py) with a symlink in support/alias_helpers/
            alias_dir = custom_fx.support_dir / "alias_helpers"
            alias_dir.mkdir(parents=True, exist_ok=True)
            alias_link = alias_dir / "onesar_refmac_log.py"
            os.symlink(
                Path(onesar_refmac_log.__file__).resolve(strict=True),
                alias_link,
            )
            old_fid = custom_fx.manifest_payload["roles"]["collector_helpers"][2]
            del custom_fx.manifest_payload["files"][old_fid]
            alias_fid = custom_fx.register_path(alias_link)
            custom_fx.manifest_payload["files"][alias_fid] = copy.deepcopy(
                custom_fx.files[alias_fid]
            )
            custom_fx.manifest_payload["roles"]["collector_helpers"][2] = alias_fid
            custom_fx.manifest_path.write_text(
                json.dumps(custom_fx.manifest_payload, indent=2) + "\n",
                encoding="utf-8",
            )
            alias_profile = RefmacDiagnosticProfile(
                profile_id=SUPPORTED_PROFILE_ID,
                manifest=_make_file_pin_on_disk(custom_fx.manifest_path),
                executable=custom_fx.profile.executable,
            )

            evidence_root = self.repo_root / "runs" / "empty_closed_trace"
            empty_closed_bytes = _build_valid_native_trace_bytes(include_events=False)

            def fake_runner(
                xyzin: Path,
                hklin: Path,
                xyzout: Path,
                hklout: Path,
                log_path: Path,
                keywords: str,
                *,
                cwd: Path | None = None,
                timeout: float = 900.0,
                xml_output: Path | None = None,
                executable: Path | None = None,
                env: Mapping[str, str] | None = None,
                ccp4: bool = True,
            ) -> subprocess.CompletedProcess[str]:
                assert env is not None
                _ = (keywords, cwd, timeout, xml_output, executable, ccp4)
                self._write_standard_outputs(
                    xyzin,
                    hklin,
                    xyzout,
                    hklout,
                    log_path,
                    trace_path=Path(env["REFMAC_DIAGNOSTIC_TRACE"]),
                    trace_bytes=empty_closed_bytes,
                )
                return subprocess.CompletedProcess(
                    args=self._expected_argv(
                        custom_fx.diagnostic_executable_path, evidence_root
                    ),
                    returncode=0,
                    stdout="",
                    stderr="",
                )

            with (
                patch.dict(
                    os.environ,
                    {
                        **self._clean_ambient_env(),
                        "PROTSTRUCT_CCP4_SETUP": str(custom_fx.setup_script),
                    },
                    clear=True,
                ),
                patch.object(toolchain, "CCP4_SETUP", custom_fx.setup_script),
                patch.object(
                    toolchain,
                    "ccp4_environment",
                    return_value=dict(custom_fx.sourced_env),
                ),
            ):
                result = onesar_refmac.run_refmac_rfactor_operation(
                    evidence_root,
                    subject_id="R4",
                    repo_root=self.repo_root,
                    archive_path=COMMITTED_ARCHIVE,
                    require_no_protstruct_overrides=False,
                    runner=fake_runner,
                    diagnostic_profile=alias_profile,
                )

            role_join = result["diagnostic_profile"]["collector_helper_role_join"]
            self.assertTrue(role_join["verified"])
            self.assertEqual(
                role_join["entries"][2]["profile_role_observation"]["path"],
                str(alias_link),
            )
            self.assertTrue(role_join["entries"][2]["resolved_path_matches"])

            empty_post_cp = self._reopen_json(
                result["post_execution_checkpoint_json"]
            )
            empty_diag = self._reopen_json(result["diagnostics_json"])
            empty_manifest = self._reopen_json(result["manifest_json"])
            for empty_doc in (result, empty_post_cp, empty_diag, empty_manifest):
                trace_env = empty_doc["native_trace_envelope"]
                self.assertTrue(trace_env["valid"])
                self.assertTrue(trace_env["closed"])
                self.assertIs(trace_env["has_events"], False)
                self.assertIsNotNone(trace_env["event_count"])
                self.assertEqual(trace_env["event_count"], 0)
                self.assertIs(trace_env["scientific_coverage_proven"], False)
                self.assertIn(
                    "zero event records",
                    trace_env["scientific_coverage_unproven_reason"],
                )
                self.assertIs(
                    empty_doc["operation_checks"]["native_trace_has_events"],
                    False,
                )
                self.assertIsNotNone(
                    empty_doc["operation_checks"]["native_trace_event_count"]
                )
                self.assertEqual(
                    empty_doc["operation_checks"]["native_trace_event_count"], 0
                )
                self.assertIs(
                    empty_doc["operation_checks"][
                        "native_trace_scientific_coverage_proven"
                    ],
                    False,
                )

    def test_preflight_rejects_untyped_profile_and_non_r4_subject_before_staging(
        self,
    ) -> None:
        """Untyped diagnostic_profile or subject_id != 'R4' raises ValueError before staging."""
        evidence_root = self.repo_root / "runs" / "never_staged"

        def fail_if_called(*_args: Any, **_kwargs: Any) -> Any:
            self.fail("Runner must not be called")

        with self.assertRaisesRegex(
            ValueError, "diagnostic_profile must be a RefmacDiagnosticProfile"
        ):
            self._run_collector(
                "untyped_profile",
                fail_if_called,
                diagnostic_profile={"profile_id": SUPPORTED_PROFILE_ID},  # type: ignore[arg-type]
                evidence_root=evidence_root,
            )
        self.assertFalse(evidence_root.exists())

        with self.assertRaisesRegex(
            ValueError, "diagnostic_profile requires subject_id 'R4'"
        ):
            self._run_collector(
                "bad_subject",
                fail_if_called,
                diagnostic_profile=self.fx.profile,
                subject_id="R1",
                evidence_root=evidence_root,
            )
        self.assertFalse(evidence_root.exists())

    def test_preflight_rejects_conflicting_environment_before_toolchain_resolver(
        self,
    ) -> None:
        """Conflicting inherited environment is rejected with ValueError before _resolve_ccp4_refmac_toolchain with zero runner calls."""
        evidence_root = self.repo_root / "runs" / "preflight_conflict_env"
        runner_calls = 0

        def fake_runner(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
            nonlocal runner_calls
            runner_calls += 1
            raise AssertionError("Runner must not be called")

        with patch.object(
            onesar_refmac,
            "_resolve_ccp4_refmac_toolchain",
            side_effect=AssertionError("Resolver must not run on dirty environment"),
        ):
            with self.assertRaises(onesar_refmac.RefmacCollectorError) as cm:
                self._run_collector(
                    "preflight_conflict_env",
                    fake_runner,
                    diagnostic_profile=self.fx.profile,
                    evidence_root=evidence_root,
                    ambient_env_extra={"DYLD_INSERT_LIBRARIES": "/tmp/evil.dylib"},
                )

        self.assertEqual(runner_calls, 0)
        err = cm.exception
        self.assertEqual(err.failed_stage, "reject_conflicting_environment")
        self.assertIsInstance(err.primary_cause, ValueError)
        self.assertNotIsInstance(err.primary_cause, ProfileValidationError)
        self.assertIs(err.__cause__, err.primary_cause)
        self.assertIn(
            "Conflicting environment variable(s) present: DYLD_INSERT_LIBRARIES",
            str(err.primary_cause),
        )
        assert err.manifest_payload is not None
        self.assertEqual(
            err.manifest_payload["failures"][0]["failed_stage"],
            "reject_conflicting_environment",
        )
        self.assertEqual(
            err.manifest_payload["failures"][0]["exception_type"],
            "ValueError",
        )
        self.assertEqual(
            err.manifest_payload["diagnostic_profile"]["failed_check"],
            "reject_conflicting_environment",
        )
        self.assertEqual(
            err.manifest_payload["diagnostic_profile"]["error"]["type"],
            "ValueError",
        )
        self.assertFalse(err.manifest_payload["operation_checks"]["worker_launched"])
        self.assertEqual(
            err.manifest_payload["diagnostic_profile"]["requested"]["manifest"]["sha256"],
            self.fx.profile.manifest.sha256,
        )
        self.assertEqual(
            err.manifest_payload["diagnostic_profile"]["requested"]["executable"]["sha256"],
            self.fx.profile.executable.sha256,
        )

    def test_preflight_rejects_outside_prefix_resolver_and_bad_profile_pins(
        self,
    ) -> None:
        """Outside-prefix stock resolver and bad caller manifest/executable pins fail at preflight with zero runner calls."""
        runner_calls = 0

        def fake_runner(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
            nonlocal runner_calls
            runner_calls += 1
            raise AssertionError("Runner must not be called")

        # 1. Outside-prefix stock refmac5
        outside_dir = self.base_dir / "outside_bin"
        outside_dir.mkdir(parents=True, exist_ok=True)
        outside_refmac = outside_dir / "refmac5"
        outside_refmac.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        outside_refmac.chmod(0o755)
        bad_sourced_env = {
            **self.fx.sourced_env,
            "PATH": f"{outside_dir}{os.pathsep}{self.fx.env_values['PATH']}",
        }
        with self.assertRaises(onesar_refmac.RefmacCollectorError) as cm_res:
            self._run_collector(
                "preflight_outside_prefix",
                fake_runner,
                diagnostic_profile=self.fx.profile,
                sourced_env_override=bad_sourced_env,
            )
        self.assertEqual(runner_calls, 0)
        self.assertEqual(
            cm_res.exception.failed_stage, "resolve_ccp4_refmac_toolchain"
        )
        assert cm_res.exception.manifest_payload is not None
        self.assertEqual(
            cm_res.exception.manifest_payload["diagnostic_profile"]["requested"][
                "executable"
            ]["sha256"],
            self.fx.profile.executable.sha256,
        )

        # 2. Bad independent caller manifest pin
        bad_manifest_pin = FilePin(
            path=self.fx.profile.manifest.path,
            sha256="f" * 64,
            size_bytes=self.fx.profile.manifest.size_bytes,
        )
        bad_manifest_profile = RefmacDiagnosticProfile(
            profile_id=SUPPORTED_PROFILE_ID,
            manifest=bad_manifest_pin,
            executable=self.fx.profile.executable,
        )
        with self.assertRaises(onesar_refmac.RefmacCollectorError) as cm_mpin:
            self._run_collector(
                "preflight_bad_manifest_pin",
                fake_runner,
                diagnostic_profile=bad_manifest_profile,
            )
        self.assertEqual(runner_calls, 0)
        self.assertEqual(
            cm_mpin.exception.failed_stage, "validate_diagnostic_profile"
        )
        self.assertIsInstance(
            cm_mpin.exception.primary_cause, ProfileValidationError
        )
        assert isinstance(
            cm_mpin.exception.primary_cause, ProfileValidationError
        )
        self.assertEqual(
            cm_mpin.exception.primary_cause.failed_check, "manifest_pin"
        )
        assert cm_mpin.exception.manifest_payload is not None
        self.assertEqual(
            cm_mpin.exception.manifest_payload["failures"][0]["failed_stage"],
            "validate_diagnostic_profile",
        )
        self.assertEqual(
            cm_mpin.exception.manifest_payload["failures"][0]["exception_type"],
            "ProfileValidationError",
        )
        self.assertEqual(
            cm_mpin.exception.manifest_payload["failures"][0]["failed_check"],
            "manifest_pin",
        )
        self.assertEqual(
            cm_mpin.exception.manifest_payload["diagnostic_profile"]["failed_check"],
            "manifest_pin",
        )
        self.assertEqual(
            cm_mpin.exception.manifest_payload["diagnostic_profile"]["requested"][
                "manifest"
            ]["sha256"],
            "f" * 64,
        )

        # 3. Bad independent caller executable pin
        bad_exe_pin = FilePin(
            path=self.fx.profile.executable.path,
            sha256="0" * 64,
            size_bytes=self.fx.profile.executable.size_bytes,
        )
        bad_profile = RefmacDiagnosticProfile(
            profile_id=SUPPORTED_PROFILE_ID,
            manifest=self.fx.profile.manifest,
            executable=bad_exe_pin,
        )
        with self.assertRaises(onesar_refmac.RefmacCollectorError) as cm_pin:
            self._run_collector(
                "preflight_bad_exe_pin",
                fake_runner,
                diagnostic_profile=bad_profile,
            )
        self.assertEqual(runner_calls, 0)
        self.assertEqual(cm_pin.exception.failed_stage, "validate_diagnostic_profile")
        self.assertIsInstance(cm_pin.exception.primary_cause, ProfileValidationError)
        assert isinstance(cm_pin.exception.primary_cause, ProfileValidationError)
        self.assertEqual(
            cm_pin.exception.primary_cause.failed_check, "outer_manifest_shape"
        )
        assert cm_pin.exception.manifest_payload is not None
        self.assertEqual(
            cm_pin.exception.manifest_payload["diagnostic_profile"]["requested"][
                "executable"
            ]["sha256"],
            "0" * 64,
        )

        # 4. Unsupported profile_id (mutated on frozen instance via object.__setattr__)
        tampered_id_profile = RefmacDiagnosticProfile(
            profile_id=SUPPORTED_PROFILE_ID,
            manifest=self.fx.profile.manifest,
            executable=self.fx.profile.executable,
        )
        object.__setattr__(tampered_id_profile, "profile_id", "unsupported_profile_v99")
        with self.assertRaises(onesar_refmac.RefmacCollectorError) as cm_id:
            self._run_collector(
                "preflight_bad_profile_id",
                fake_runner,
                diagnostic_profile=tampered_id_profile,
            )
        self.assertEqual(runner_calls, 0)
        self.assertEqual(cm_id.exception.failed_stage, "validate_diagnostic_profile")

    def test_preflight_rejects_collector_helper_role_join_mismatch_1163(self) -> None:
        """Independently repinned copy of a helper module at a different path passes validate_profile but fails verify_diagnostic_helper_role_join (#1163)."""
        with tempfile.TemporaryDirectory() as tmp:
            custom_fx = _DiagnosticCollectorFixture(Path(tmp))
            # Create a byte-identical copy of onesar_refmac_log.py under support/copied_helpers/
            copied_helper = (
                custom_fx.support_dir
                / "copied_helpers"
                / "onesar_refmac_log.py"
            )
            copied_helper.parent.mkdir(parents=True, exist_ok=True)
            copied_helper.write_bytes(
                Path(onesar_refmac_log.__file__).resolve(strict=True).read_bytes()
            )
            old_fid = custom_fx.manifest_payload["roles"]["collector_helpers"][2]
            del custom_fx.manifest_payload["files"][old_fid]
            copied_fid = custom_fx.register_path(copied_helper)
            custom_fx.manifest_payload["files"][copied_fid] = copy.deepcopy(
                custom_fx.files[copied_fid]
            )
            custom_fx.manifest_payload["roles"]["collector_helpers"][2] = copied_fid
            custom_fx.manifest_path.write_text(
                json.dumps(custom_fx.manifest_payload, indent=2) + "\n",
                encoding="utf-8",
            )
            repinned_profile = RefmacDiagnosticProfile(
                profile_id=SUPPORTED_PROFILE_ID,
                manifest=_make_file_pin_on_disk(custom_fx.manifest_path),
                executable=custom_fx.profile.executable,
            )

            # Confirm generic validate_profile succeeds on this repinned profile
            validated = refmac_diagnostic_profile.validate_profile(
                repinned_profile,
                custom_fx.installed_record,
                custom_fx.resolved_ccp4_env,
                Path(tmp) / "dummy_ev",
            )
            self.assertEqual(validated.profile_id, SUPPORTED_PROFILE_ID)

            runner_calls = 0

            def fake_runner(
                *_args: Any, **_kwargs: Any
            ) -> subprocess.CompletedProcess[str]:
                nonlocal runner_calls
                runner_calls += 1
                raise AssertionError("Runner must not be called")

            evidence_root = self.repo_root / "runs" / "helper_join_mismatch"
            with (
                patch.dict(
                    os.environ,
                    {
                        **self._clean_ambient_env(),
                        "PROTSTRUCT_CCP4_SETUP": str(custom_fx.setup_script),
                    },
                    clear=True,
                ),
                patch.object(toolchain, "CCP4_SETUP", custom_fx.setup_script),
                patch.object(
                    toolchain,
                    "ccp4_environment",
                    return_value=dict(custom_fx.sourced_env),
                ),
            ):
                with self.assertRaises(onesar_refmac.RefmacCollectorError) as cm:
                    onesar_refmac.run_refmac_rfactor_operation(
                        evidence_root,
                        subject_id="R4",
                        repo_root=self.repo_root,
                        archive_path=COMMITTED_ARCHIVE,
                        require_no_protstruct_overrides=False,
                        runner=fake_runner,
                        diagnostic_profile=repinned_profile,
                    )

            self.assertEqual(runner_calls, 0)
            err = cm.exception
            self.assertEqual(err.failed_stage, "verify_diagnostic_helper_role_join")
            assert err.manifest_payload is not None
            self.assertFalse(
                err.manifest_payload["operation_checks"]["worker_launched"]
            )
            self.assertFalse(
                err.manifest_payload["operation_checks"][
                    "diagnostic_helper_role_join_verified"
                ]
            )
            join_report = err.manifest_payload["diagnostic_profile"][
                "collector_helper_role_join"
            ]
            self.assertFalse(join_report["verified"])
            self.assertEqual(len(join_report["mismatches"]), 1)
            mismatch = join_report["mismatches"][0]
            self.assertEqual(mismatch["index"], 2)
            self.assertEqual(
                mismatch["expected_module_name"], "onesar_refmac_log.py"
            )
            self.assertEqual(
                mismatch["helper_baseline_key"], "onesar_refmac_log_py"
            )
            self.assertFalse(mismatch["resolved_path_matches"])
            self.assertTrue(mismatch["sha256_matches"])
            self.assertTrue(mismatch["size_bytes_matches"])
            self.assertIn("helper_source_baseline", join_report)
            self.assertIn("profile_collector_helpers", join_report)
            self.assertEqual(len(join_report["profile_collector_helpers"]), 8)

    def test_preflight_rejects_non_ascii_trace_path_and_fresh_trace_collision(
        self,
    ) -> None:
        """Non-ASCII native_trace path and pre-existing refmac_native_trace.jsonl are rejected before launch."""
        runner_calls = 0

        def fake_runner(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
            nonlocal runner_calls
            runner_calls += 1
            raise AssertionError("Runner must not be called")

        # 1. Non-ASCII evidence_root -> non-ASCII native_trace path
        non_ascii_root = self.repo_root / "runs" / "diag_non_ascii_é"
        with self.assertRaises(onesar_refmac.RefmacCollectorError) as cm_ascii:
            self._run_collector(
                "diag_non_ascii",
                fake_runner,
                diagnostic_profile=self.fx.profile,
                evidence_root=non_ascii_root,
            )
        self.assertEqual(runner_calls, 0)
        self.assertEqual(
            cm_ascii.exception.failed_stage, "validate_native_trace_path"
        )

        # 2. Pre-existing refmac_native_trace.jsonl collision at verify_fresh_output_paths
        collision_root = self.repo_root / "runs" / "diag_trace_collision"
        orig_validate = refmac_diagnostic_profile.validate_profile

        def inject_colliding_trace(*args: Any, **kwargs: Any) -> Any:
            res = orig_validate(*args, **kwargs)
            (collision_root / "refmac" / "refmac_native_trace.jsonl").write_text(
                "preexisting\n", encoding="utf-8"
            )
            return res

        with patch.object(
            refmac_diagnostic_profile,
            "validate_profile",
            side_effect=inject_colliding_trace,
        ):
            with self.assertRaises(onesar_refmac.RefmacCollectorError) as cm_col:
                self._run_collector(
                    "diag_trace_collision",
                    fake_runner,
                    diagnostic_profile=self.fx.profile,
                    evidence_root=collision_root,
                )
        self.assertEqual(runner_calls, 0)
        self.assertEqual(
            cm_col.exception.failed_stage, "verify_fresh_output_paths"
        )

    def test_post_launch_nonzero_exit_timeout_and_truncated_trace_retention(
        self,
    ) -> None:
        """Post-launch failures retain raw native_trace bytes/SHA-256 and preserve first failure stage and cause."""
        valid_trace_bytes = _build_valid_native_trace_bytes(include_events=True)
        truncated_trace_bytes = valid_trace_bytes.splitlines(keepends=True)[0]
        truncated_sha = _sha256_bytes(truncated_trace_bytes)

        # 1. Nonzero returncode with valid native trace
        rc_root = self.repo_root / "runs" / "diag_nonzero_rc"
        rc_calls = 0

        def rc_runner(
            xyzin: Path,
            hklin: Path,
            xyzout: Path,
            hklout: Path,
            log_path: Path,
            keywords: str,
            *,
            env: Mapping[str, str] | None = None,
            **_kwargs: Any,
        ) -> subprocess.CompletedProcess[str]:
            nonlocal rc_calls
            rc_calls += 1
            _ = keywords
            assert env is not None
            self._write_standard_outputs(
                xyzin,
                hklin,
                xyzout,
                hklout,
                log_path,
                trace_path=Path(env["REFMAC_DIAGNOSTIC_TRACE"]),
                trace_bytes=valid_trace_bytes,
            )
            return subprocess.CompletedProcess(
                args=self._expected_argv(
                    self.fx.diagnostic_executable_path, rc_root
                ),
                returncode=2,
                stdout="",
                stderr="",
            )

        with self.assertRaises(onesar_refmac.RefmacCollectorError) as cm_rc:
            self._run_collector(
                "diag_nonzero_rc",
                rc_runner,
                diagnostic_profile=self.fx.profile,
                evidence_root=rc_root,
            )
        self.assertEqual(rc_calls, 1)
        self.assertEqual(cm_rc.exception.failed_stage, "refmac_returncode")
        self.assertEqual(cm_rc.exception.returncode, 2)
        assert cm_rc.exception.manifest_payload is not None
        self.assertTrue(
            cm_rc.exception.manifest_payload["native_trace_envelope"]["valid"]
        )
        self.assertEqual(
            cm_rc.exception.manifest_payload["raw_outputs"]["native_trace"]["sha256"],
            _sha256_bytes(valid_trace_bytes),
        )

        # 2. TimeoutExpired with omitted xyzout/hklout and partial/truncated trace preserves TimeoutExpired as primary_cause
        to_root = self.repo_root / "runs" / "diag_timeout"
        to_calls = 0
        partial_log_bytes = b"partial log before timeout\n"
        partial_log_sha = _sha256_bytes(partial_log_bytes)
        timeout_exc = subprocess.TimeoutExpired(
            cmd=[str(self.fx.diagnostic_executable_path)],
            timeout=15.0,
        )

        def to_runner(
            xyzin: Path,
            hklin: Path,
            xyzout: Path,
            hklout: Path,
            log_path: Path,
            keywords: str,
            *,
            env: Mapping[str, str] | None = None,
            **_kwargs: Any,
        ) -> subprocess.CompletedProcess[str]:
            nonlocal to_calls
            to_calls += 1
            _ = (xyzin, hklin, xyzout, hklout, keywords)
            assert env is not None
            Path(env["REFMAC_DIAGNOSTIC_TRACE"]).write_bytes(truncated_trace_bytes)
            log_path.write_bytes(partial_log_bytes)
            raise timeout_exc

        with self.assertRaises(onesar_refmac.RefmacCollectorError) as cm_to:
            self._run_collector(
                "diag_timeout",
                to_runner,
                diagnostic_profile=self.fx.profile,
                evidence_root=to_root,
                timeout=15.0,
            )
        self.assertEqual(to_calls, 1)
        self.assertEqual(cm_to.exception.failed_stage, "refmac_timeout")
        self.assertIs(cm_to.exception.primary_cause, timeout_exc)
        self.assertIs(cm_to.exception.__cause__, timeout_exc)
        assert cm_to.exception.manifest_payload is not None
        to_mp = cm_to.exception.manifest_payload
        self.assertEqual(
            to_mp["raw_outputs"]["log"]["sha256"],
            partial_log_sha,
        )
        self.assertEqual(
            to_mp["raw_outputs"]["log"]["size_bytes"],
            len(partial_log_bytes),
        )
        self.assertEqual(
            to_mp["raw_outputs"]["native_trace"]["sha256"],
            truncated_sha,
        )
        self.assertEqual(
            to_mp["raw_outputs"]["native_trace"]["size_bytes"],
            len(truncated_trace_bytes),
        )
        for omitted_key in ("xyzout", "hklout"):
            raw_omitted = to_mp["raw_outputs"][omitted_key]
            self.assertFalse(raw_omitted["exists"])
            self.assertFalse(raw_omitted["is_regular_file"])
            self.assertFalse(raw_omitted["is_symlink"])
            self.assertTrue(raw_omitted["within_refmac_dir"])
            self.assertIsNone(raw_omitted["sha256"])
            self.assertIsNone(raw_omitted["size_bytes"])
        raw_fail_row = next(
            row
            for row in to_mp["failures"]
            if row["failed_stage"] == "refmac_raw_outputs"
        )
        missing_by_key = {
            item["output_key"]: item
            for item in raw_fail_row["missing_or_invalid_outputs"]
        }
        for omitted_key in ("xyzout", "hklout"):
            self.assertIn(omitted_key, missing_by_key)
            self.assertFalse(missing_by_key[omitted_key]["exists"])
            self.assertFalse(missing_by_key[omitted_key]["is_regular_file"])
            self.assertIsNone(missing_by_key[omitted_key]["size_bytes"])
            self.assertEqual(
                missing_by_key[omitted_key]["error"], "missing_output_file"
            )
        self.assertFalse(to_mp["native_trace_envelope"]["valid"])
        self.assertFalse(to_mp["native_trace_envelope"]["closed"])

        # 3. Truncated native trace after returncode == 0 fails at refmac_raw_outputs while retaining raw bytes
        tr_root = self.repo_root / "runs" / "diag_truncated_trace"

        def tr_runner(
            xyzin: Path,
            hklin: Path,
            xyzout: Path,
            hklout: Path,
            log_path: Path,
            keywords: str,
            *,
            env: Mapping[str, str] | None = None,
            **_kwargs: Any,
        ) -> subprocess.CompletedProcess[str]:
            _ = keywords
            assert env is not None
            self._write_standard_outputs(
                xyzin,
                hklin,
                xyzout,
                hklout,
                log_path,
                trace_path=Path(env["REFMAC_DIAGNOSTIC_TRACE"]),
                trace_bytes=truncated_trace_bytes,
            )
            return subprocess.CompletedProcess(
                args=self._expected_argv(
                    self.fx.diagnostic_executable_path, tr_root
                ),
                returncode=0,
                stdout="",
                stderr="",
            )

        with self.assertRaises(onesar_refmac.RefmacCollectorError) as cm_tr:
            self._run_collector(
                "diag_truncated_trace",
                tr_runner,
                diagnostic_profile=self.fx.profile,
                evidence_root=tr_root,
            )
        self.assertEqual(cm_tr.exception.failed_stage, "refmac_raw_outputs")
        assert cm_tr.exception.manifest_payload is not None
        self.assertEqual(
            cm_tr.exception.manifest_payload["raw_outputs"]["native_trace"]["sha256"],
            truncated_sha,
        )
        self.assertFalse(
            cm_tr.exception.manifest_payload["native_trace_envelope"]["valid"]
        )
        self.assertEqual(
            (tr_root / "refmac" / "refmac_native_trace.jsonl").read_bytes(),
            truncated_trace_bytes,
        )

    def test_postflight_profile_mutation_and_fallback_retention(self) -> None:
        """Postflight profile mutation, audit exception, and unwritable child refmac_dir fallback preserve trace and provenance."""
        valid_trace_bytes = _build_valid_native_trace_bytes(include_events=True)

        # 1. Postflight profile file mutation during child execution
        with tempfile.TemporaryDirectory() as tmp:
            mut_fx = _DiagnosticCollectorFixture(Path(tmp))
            mut_root = self.repo_root / "runs" / "profile_mutated"
            target_file = mut_fx.trees["build"] / "ordinary_object.o"
            orig_bytes = target_file.read_bytes()

            def mutating_runner(
                xyzin: Path,
                hklin: Path,
                xyzout: Path,
                hklout: Path,
                log_path: Path,
                keywords: str,
                *,
                env: Mapping[str, str] | None = None,
                **_kwargs: Any,
            ) -> subprocess.CompletedProcess[str]:
                _ = keywords
                assert env is not None
                self._write_standard_outputs(
                    xyzin,
                    hklin,
                    xyzout,
                    hklout,
                    log_path,
                    trace_path=Path(env["REFMAC_DIAGNOSTIC_TRACE"]),
                    trace_bytes=valid_trace_bytes,
                )
                target_file.write_bytes(orig_bytes + b"mutated\n")
                return subprocess.CompletedProcess(
                    args=self._expected_argv(
                        mut_fx.diagnostic_executable_path, mut_root
                    ),
                    returncode=0,
                    stdout="",
                    stderr="",
                )

            with (
                patch.dict(
                    os.environ,
                    {
                        **self._clean_ambient_env(),
                        "PROTSTRUCT_CCP4_SETUP": str(mut_fx.setup_script),
                    },
                    clear=True,
                ),
                patch.object(toolchain, "CCP4_SETUP", mut_fx.setup_script),
                patch.object(
                    toolchain,
                    "ccp4_environment",
                    return_value=dict(mut_fx.sourced_env),
                ),
            ):
                with self.assertRaises(onesar_refmac.RefmacCollectorError) as cm_mut:
                    onesar_refmac.run_refmac_rfactor_operation(
                        mut_root,
                        subject_id="R4",
                        repo_root=self.repo_root,
                        archive_path=COMMITTED_ARCHIVE,
                        require_no_protstruct_overrides=False,
                        runner=mutating_runner,
                        diagnostic_profile=mut_fx.profile,
                    )

            self.assertEqual(
                cm_mut.exception.failed_stage, "verify_input_immutability"
            )
            self.assertIsNone(cm_mut.exception.primary_cause)
            assert cm_mut.exception.manifest_payload is not None
            mp = cm_mut.exception.manifest_payload
            self.assertFalse(mp["input_immutability"]["verified"])
            self.assertFalse(mp["diagnostic_profile_post_run"]["verified"])
            self.assertFalse(
                mp["operation_checks"]["diagnostic_profile_post_run_verified"]
            )
            self.assertTrue(
                any(
                    m.get("category") == "diagnostic_profile_file"
                    and m.get("path") == str(target_file)
                    and m.get("error") is None
                    for m in mp["input_immutability"]["mutations"]
                )
            )
            self.assertTrue(mp["native_trace_envelope"]["valid"])

        # 1b. Distinct postflight profile file deletion during child execution
        with tempfile.TemporaryDirectory() as tmp_del:
            del_fx = _DiagnosticCollectorFixture(Path(tmp_del))
            del_root = self.repo_root / "runs" / "profile_deleted"
            del_target = del_fx.trees["build"] / "ordinary_object.o"
            del_fid = del_fx._by_lexical_path[str(del_target)]

            def deleting_runner(
                xyzin: Path,
                hklin: Path,
                xyzout: Path,
                hklout: Path,
                log_path: Path,
                keywords: str,
                *,
                env: Mapping[str, str] | None = None,
                **_kwargs: Any,
            ) -> subprocess.CompletedProcess[str]:
                _ = keywords
                assert env is not None
                self._write_standard_outputs(
                    xyzin,
                    hklin,
                    xyzout,
                    hklout,
                    log_path,
                    trace_path=Path(env["REFMAC_DIAGNOSTIC_TRACE"]),
                    trace_bytes=valid_trace_bytes,
                )
                del_target.unlink()
                return subprocess.CompletedProcess(
                    args=self._expected_argv(
                        del_fx.diagnostic_executable_path, del_root
                    ),
                    returncode=0,
                    stdout="",
                    stderr="",
                )

            with (
                patch.dict(
                    os.environ,
                    {
                        **self._clean_ambient_env(),
                        "PROTSTRUCT_CCP4_SETUP": str(del_fx.setup_script),
                    },
                    clear=True,
                ),
                patch.object(toolchain, "CCP4_SETUP", del_fx.setup_script),
                patch.object(
                    toolchain,
                    "ccp4_environment",
                    return_value=dict(del_fx.sourced_env),
                ),
            ):
                with self.assertRaises(onesar_refmac.RefmacCollectorError) as cm_del:
                    onesar_refmac.run_refmac_rfactor_operation(
                        del_root,
                        subject_id="R4",
                        repo_root=self.repo_root,
                        archive_path=COMMITTED_ARCHIVE,
                        require_no_protstruct_overrides=False,
                        runner=deleting_runner,
                        diagnostic_profile=del_fx.profile,
                    )

            self.assertEqual(
                cm_del.exception.failed_stage, "verify_input_immutability"
            )
            self.assertIsInstance(
                cm_del.exception.primary_cause, FileNotFoundError
            )
            self.assertIs(
                cm_del.exception.__cause__, cm_del.exception.primary_cause
            )
            assert cm_del.exception.manifest_payload is not None
            del_mp = cm_del.exception.manifest_payload
            self.assertFalse(del_mp["input_immutability"]["verified"])
            del_post = del_mp["diagnostic_profile_post_run"]
            self.assertFalse(del_post["verified"])
            self.assertFalse(
                del_mp["operation_checks"][
                    "diagnostic_profile_post_run_verified"
                ]
            )
            self.assertIsNone(del_post["files"][del_fid]["observed"])
            self.assertFalse(del_post["files"][del_fid]["matches_baseline"])
            self.assertEqual(
                del_post["files"][del_fid]["errors"][0]["type"],
                "FileNotFoundError",
            )
            self.assertIn(
                "ordinary_object.o",
                del_post["roots"]["build"]["member_diff"]["removed"],
            )
            self.assertTrue(
                any(
                    m.get("category") == "diagnostic_profile_file"
                    and m.get("path") == str(del_target)
                    and isinstance(m.get("error"), Mapping)
                    and m["error"].get("type") == "FileNotFoundError"
                    for m in del_mp["input_immutability"]["mutations"]
                )
            )
            self.assertTrue(del_mp["native_trace_envelope"]["valid"])

        # 2. Audit exception + unwritable child refmac_dir fallback to parent_retention_dir
        fb_root = self.repo_root / "runs" / "diag_fallback_and_audit_exc"
        audit_boom = RuntimeError("synthetic xmlout audit failure")

        def fb_runner(
            xyzin: Path,
            hklin: Path,
            xyzout: Path,
            hklout: Path,
            log_path: Path,
            keywords: str,
            *,
            env: Mapping[str, str] | None = None,
            **_kwargs: Any,
        ) -> subprocess.CompletedProcess[str]:
            _ = keywords
            assert env is not None
            self._write_standard_outputs(
                xyzin,
                hklin,
                xyzout,
                hklout,
                log_path,
                trace_path=Path(env["REFMAC_DIAGNOSTIC_TRACE"]),
                trace_bytes=valid_trace_bytes,
            )
            return subprocess.CompletedProcess(
                args=self._expected_argv(
                    self.fx.diagnostic_executable_path, fb_root
                ),
                returncode=0,
                stdout="",
                stderr="",
            )

        with patch.object(
            onesar_refmac,
            "_audit_refmac_xmlout",
            side_effect=audit_boom,
        ):
            with self.assertRaises(onesar_refmac.RefmacCollectorError) as cm_aud:
                self._run_collector(
                    "diag_fallback_and_audit_exc",
                    fb_runner,
                    diagnostic_profile=self.fx.profile,
                    evidence_root=fb_root,
                )
        self.assertEqual(cm_aud.exception.failed_stage, "audit_refmac_xmlout")
        self.assertIs(cm_aud.exception.primary_cause, audit_boom)
        assert cm_aud.exception.manifest_payload is not None
        self.assertTrue(
            cm_aud.exception.manifest_payload["native_trace_envelope"]["valid"]
        )

        # 3. Unwritable child refmac_dir falls back to parent_retention_dir while retaining diagnostic fields and trace bytes
        ro_root = self.repo_root / "runs" / "diag_child_readonly"

        def ro_runner(
            xyzin: Path,
            hklin: Path,
            xyzout: Path,
            hklout: Path,
            log_path: Path,
            keywords: str,
            *,
            cwd: Path | None = None,
            env: Mapping[str, str] | None = None,
            **_kwargs: Any,
        ) -> subprocess.CompletedProcess[str]:
            _ = keywords
            assert env is not None
            assert cwd is not None
            self._write_standard_outputs(
                xyzin,
                hklin,
                xyzout,
                hklout,
                log_path,
                trace_path=Path(env["REFMAC_DIAGNOSTIC_TRACE"]),
                trace_bytes=valid_trace_bytes,
            )
            cwd.chmod(0o555)
            return subprocess.CompletedProcess(
                args=self._expected_argv(
                    self.fx.diagnostic_executable_path, ro_root
                ),
                returncode=0,
                stdout="",
                stderr="",
            )

        try:
            with self.assertRaises(onesar_refmac.RefmacCollectorError) as cm_ro:
                self._run_collector(
                    "diag_child_readonly",
                    ro_runner,
                    diagnostic_profile=self.fx.profile,
                    evidence_root=ro_root,
                )
            self.assertEqual(
                cm_ro.exception.failed_stage,
                "persist_collector_artifacts_in_refmac_dir",
            )
            self.assertIsInstance(
                cm_ro.exception.primary_cause, PermissionError
            )
            self.assertIs(
                cm_ro.exception.__cause__, cm_ro.exception.primary_cause
            )
            assert cm_ro.exception.manifest_payload is not None
            assert cm_ro.exception.manifest_path is not None
            assert cm_ro.exception.diagnostics_path is not None
            ro_mp = cm_ro.exception.manifest_payload
            self.assertTrue(ro_mp["parent_retention_used"])
            self.assertEqual(
                ro_mp["actual_parent_retention_anchor_kind"],
                "parent_retention_dir",
            )
            self.assertTrue(ro_mp["native_trace_envelope"]["valid"])
            self.assertEqual(
                ro_mp["raw_outputs"]["native_trace"]["sha256"],
                _sha256_bytes(valid_trace_bytes),
            )

            ro_manifest_path = Path(cm_ro.exception.manifest_path)
            ro_manifest_raw = ro_manifest_path.read_bytes()
            ro_manifest_doc = self._reopen_json(
                {
                    "path": str(ro_manifest_path),
                    "sha256": _sha256_bytes(ro_manifest_raw),
                    "size_bytes": len(ro_manifest_raw),
                }
            )
            ro_diag_doc = self._reopen_json(ro_manifest_doc["diagnostics_json"])
            ro_post_cp = self._reopen_json(
                ro_manifest_doc["post_execution_checkpoint_json"]
            )
            ro_pre_cp = self._reopen_json(
                ro_manifest_doc["pre_execution_checkpoint_json"]
            )
            self.assertEqual(ro_manifest_doc, ro_mp)
            self.assertEqual(ro_diag_doc, cm_ro.exception.diagnostics_payload)
            self.assertEqual(
                Path(
                    str(ro_manifest_doc["pre_execution_checkpoint_json"]["path"])
                ).parent,
                ro_root / "refmac",
            )
            for fallback_ref_path in (
                ro_manifest_path,
                Path(str(ro_manifest_doc["diagnostics_json"]["path"])),
                Path(
                    str(
                        ro_manifest_doc["post_execution_checkpoint_json"]["path"]
                    )
                ),
            ):
                self.assertEqual(
                    fallback_ref_path.parent,
                    ro_root / "refmac_parent_retention",
                )
            expected_requested = {
                "manifest": self.fx.profile.manifest.to_dict(),
                "executable": self.fx.profile.executable.to_dict(),
            }
            expected_ro_trace = ro_root / "refmac" / "refmac_native_trace.jsonl"
            for env_doc in (ro_pre_cp, ro_post_cp, ro_diag_doc, ro_manifest_doc):
                self.assertEqual(env_doc["schema_version"], 2)
                self.assertEqual(
                    env_doc["collector_stage"],
                    "instrumented_native_trace_capture_v1",
                )
                self.assertEqual(
                    env_doc["diagnostic_producer"]["profile_id"],
                    SUPPORTED_PROFILE_ID,
                )
                self.assertEqual(
                    env_doc["diagnostic_producer"]["selected_executable"]["path"],
                    str(self.fx.diagnostic_executable_path),
                )
                self.assertEqual(
                    env_doc["diagnostic_profile"]["profile_id"],
                    self.fx.profile.profile_id,
                )
                self.assertEqual(
                    env_doc["diagnostic_profile"]["requested"],
                    expected_requested,
                )
                self.assertEqual(
                    env_doc["diagnostic_activation_environment"],
                    {
                        "REFMAC_DIAGNOSTIC_TRACE": str(expected_ro_trace),
                        "DYLD_PRINT_LIBRARIES": "1",
                    },
                )
            for post_doc in (ro_post_cp, ro_diag_doc, ro_manifest_doc):
                self.assertEqual(post_doc["status"], "failed")
                self.assertEqual(
                    post_doc["failed_stage"],
                    "persist_collector_artifacts_in_refmac_dir",
                )
                self.assertEqual(
                    post_doc["failures"][0]["failed_stage"],
                    "persist_collector_artifacts_in_refmac_dir",
                )
                self.assertEqual(
                    post_doc["failures"][0]["exception_type"],
                    type(cm_ro.exception.primary_cause).__name__,
                )
                self.assertTrue(post_doc["parent_retention_used"])
                self.assertEqual(
                    post_doc["actual_parent_retention_anchor_kind"],
                    "parent_retention_dir",
                )
                self.assertTrue(
                    post_doc["diagnostic_profile_post_run"]["verified"]
                )
                self.assertTrue(post_doc["native_trace_envelope"]["valid"])
        finally:
            if (ro_root / "refmac").exists():
                (ro_root / "refmac").chmod(0o755)

    def test_inspect_retained_native_trace_envelope_failure_progress_1185(
        self,
    ) -> None:
        """Unexpected reader exception exposes unknown progress while skipped reader records zero bytes and no prefix digest/size (#1185)."""
        trace_dir = self.base_dir / "trace_progress_1185"
        trace_dir.mkdir(parents=True, exist_ok=True)
        trace_path = trace_dir / "literal-raw-trace.txt"
        raw_bytes = b"actual raw observation\n"
        trace_path.write_bytes(raw_bytes)
        raw_sha = _sha256_bytes(raw_bytes)

        base_raw_obs: dict[str, Any] = {
            "exists": True,
            "is_regular_file": True,
            "is_symlink": False,
            "within_refmac_dir": True,
            "error": None,
            "sha256": raw_sha,
            "size_bytes": len(raw_bytes),
        }
        sentinel = RuntimeError(
            "sentinel reader failed without exposing progress"
        )
        reader_calls: list[dict[str, Any]] = []

        def fail_reader(path: Path, **kwargs: Any) -> dict[str, Any]:
            reader_calls.append({"path": str(path), "pins": dict(kwargs)})
            raise sentinel

        with patch.object(
            refmac_diagnostic_trace,
            "inspect_native_trace_envelope",
            side_effect=fail_reader,
        ):
            caught: list[Exception] = []
            raised_result, returned_cause = (
                onesar_refmac._inspect_retained_native_trace_envelope(
                    trace_path,
                    trace_info=base_raw_obs,
                    caught_exceptions=caught,
                )
            )
            self.assertEqual(len(reader_calls), 1)
            self.assertEqual(
                reader_calls[0],
                {
                    "path": str(trace_path),
                    "pins": {
                        "expected_sha256": raw_sha,
                        "expected_size_bytes": len(raw_bytes),
                    },
                },
            )
            self.assertEqual(caught, [sentinel])
            self.assertIs(returned_cause, sentinel)
            self.assertFalse(raised_result["valid"])
            self.assertFalse(raised_result["closed"])
            self.assertFalse(raised_result["read_complete"])
            self.assertFalse(raised_result["has_events"])
            self.assertIsNone(raised_result["bytes_read"])
            self.assertIsNone(raised_result["event_count"])
            self.assertIsNone(raised_result["record_count"])
            self.assertIsNone(raised_result["partial_sha256"])
            self.assertIsNone(raised_result["partial_size_bytes"])
            self.assertIsNone(raised_result["observed_sha256"])
            self.assertIsNone(raised_result["observed_size_bytes"])
            self.assertEqual(raised_result["expected_sha256"], raw_sha)
            self.assertEqual(
                raised_result["expected_size_bytes"], len(raw_bytes)
            )
            self.assertEqual(raised_result["raw_observation"], base_raw_obs)
            self.assertIsNot(raised_result["raw_observation"], base_raw_obs)
            self.assertEqual(
                raised_result["first_failure"],
                {
                    "code": "envelope_inspection_exception",
                    "message": f"RuntimeError: {sentinel}",
                },
            )
            self.assertFalse(raised_result["scientific_coverage_proven"])

            unread_raw_obs: dict[str, Any] = {
                **base_raw_obs,
                "sha256": None,
                "error": "PermissionError: synthetic shape of a failed earlier raw read",
            }
            skipped_caught: list[Exception] = []
            skipped_result, skipped_cause = (
                onesar_refmac._inspect_retained_native_trace_envelope(
                    trace_path,
                    trace_info=unread_raw_obs,
                    caught_exceptions=skipped_caught,
                )
            )
            self.assertEqual(len(reader_calls), 1)
            self.assertEqual(skipped_caught, [])
            self.assertIsNone(skipped_cause)
            self.assertFalse(skipped_result["valid"])
            self.assertFalse(skipped_result["closed"])
            self.assertFalse(skipped_result["read_complete"])
            self.assertFalse(skipped_result["has_events"])
            self.assertEqual(skipped_result["bytes_read"], 0)
            self.assertEqual(skipped_result["event_count"], 0)
            self.assertEqual(skipped_result["record_count"], 0)
            self.assertIsNone(skipped_result["partial_sha256"])
            self.assertIsNone(skipped_result["partial_size_bytes"])
            self.assertIsNone(skipped_result["expected_sha256"])
            self.assertIsNone(skipped_result["expected_size_bytes"])
            self.assertEqual(skipped_result["raw_observation"], unread_raw_obs)
            self.assertIsNot(skipped_result["raw_observation"], unread_raw_obs)
            self.assertEqual(
                skipped_result["first_failure"],
                {
                    "code": "raw_trace_missing_or_invalid",
                    "message": unread_raw_obs["error"],
                },
            )
            self.assertFalse(skipped_result["scientific_coverage_proven"])

        self.assertEqual(trace_path.read_bytes(), raw_bytes)

    def test_raw_observations_precede_audits_and_combined_failures_retain_causes_1184(
        self,
    ) -> None:
        """All five raw observations precede both diagnostic audits and combined runner/profile/trace failures retain original causes (#1184)."""
        evidence_root = self.repo_root / "runs" / "diag_raw_first_and_combined_1184"
        native_trace_path = (
            evidence_root / "refmac" / "refmac_native_trace.jsonl"
        )
        raw_trace_bytes = b'{"control_767":"raw-before-new-audits"}\n'
        log_bytes = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.encode("utf-8")
        xml_bytes = b"<control767/>\n"

        runner_error = RuntimeError("primary runner failure 1184")
        profile_error = OSError("later profile recheck failure 1184")
        trace_error = ValueError("later trace envelope failure 1184")

        expected_raw_pins: dict[str, dict[str, Any]] = {}
        observations: dict[str, dict[str, Any]] = {}
        first_raw_event_index: dict[str, int] = {}
        events: list[str] = []
        runner_calls: list[dict[str, Any]] = []
        audits = {"profile": 0, "trace": 0}
        captured_lists: dict[str, list[Any]] = {}

        def combined_runner(
            xyzin: Path,
            hklin: Path,
            xyzout: Path,
            hklout: Path,
            log_path: Path,
            keywords: str,
            *,
            cwd: Path | None = None,
            timeout: float = 900.0,
            xml_output: Path | None = None,
            executable: Path | None = None,
            env: Mapping[str, str] | None = None,
            ccp4: bool = True,
        ) -> subprocess.CompletedProcess[str]:
            events.append("runner")
            runner_calls.append(
                {
                    "executable": executable,
                    "cwd": cwd,
                    "timeout": timeout,
                    "xml_output": xml_output,
                    "ccp4": ccp4,
                    "keywords": keywords,
                    "env": dict(env) if env is not None else None,
                }
            )
            assert xml_output is not None
            assert env is not None
            self.assertEqual(
                env.get("REFMAC_DIAGNOSTIC_TRACE"), str(native_trace_path)
            )
            self.assertEqual(env.get("DYLD_PRINT_LIBRARIES"), "1")
            for out_path, payload in (
                (xyzout, xyzin.read_bytes()),
                (hklout, hklin.read_bytes()),
                (log_path, log_bytes),
                (xml_output, xml_bytes),
                (native_trace_path, raw_trace_bytes),
            ):
                out_path.write_bytes(payload)
                expected_raw_pins[str(out_path)] = {
                    "sha256": _sha256_bytes(payload),
                    "size_bytes": len(payload),
                }
            raise runner_error

        real_inspect_output = onesar_refmac._inspect_output_artifact
        real_verify_immutable = (
            onesar_refmac._verify_immutable_baselines_post_run
        )

        def observe_raw(path: Path, **kwargs: Any) -> dict[str, Any]:
            res = real_inspect_output(path, **kwargs)
            if str(path) in expected_raw_pins:
                events.append(f"raw:{path.name}")
                first_raw_event_index.setdefault(str(path), len(events) - 1)
                observations[str(path)] = copy.deepcopy(res)
                self.assertEqual(
                    res["sha256"], expected_raw_pins[str(path)]["sha256"]
                )
                self.assertEqual(
                    res["size_bytes"],
                    expected_raw_pins[str(path)]["size_bytes"],
                )
            return res

        def observe_profile(
            baseline: Any, **kwargs: Any
        ) -> dict[str, Any]:
            _ = (baseline, kwargs)
            audits["profile"] += 1
            events.append("profile_inspection")
            self.assertEqual(len(expected_raw_pins), 5)
            self.assertTrue(set(expected_raw_pins) <= set(observations))
            self.assertEqual(native_trace_path.read_bytes(), raw_trace_bytes)
            raise profile_error

        def observe_trace(path: Path, **kwargs: Any) -> dict[str, Any]:
            audits["trace"] += 1
            events.append("trace_inspection")
            self.assertEqual(len(expected_raw_pins), 5)
            self.assertTrue(set(expected_raw_pins) <= set(observations))
            self.assertEqual(str(path), str(native_trace_path))
            self.assertEqual(
                kwargs,
                {
                    "expected_sha256": _sha256_bytes(raw_trace_bytes),
                    "expected_size_bytes": len(raw_trace_bytes),
                },
            )
            self.assertEqual(native_trace_path.read_bytes(), raw_trace_bytes)
            raise trace_error

        def observe_immutable(*args: Any, **kwargs: Any) -> dict[str, Any]:
            captured_lists["mutations"] = kwargs["mutation_causes_out"]
            captured_lists["inspection"] = kwargs["caught_exceptions"]
            return real_verify_immutable(*args, **kwargs)

        with (
            patch.object(
                onesar_refmac,
                "_inspect_output_artifact",
                side_effect=observe_raw,
            ),
            patch.object(
                refmac_diagnostic_profile,
                "recheck_profile",
                side_effect=observe_profile,
            ),
            patch.object(
                refmac_diagnostic_trace,
                "inspect_native_trace_envelope",
                side_effect=observe_trace,
            ),
            patch.object(
                onesar_refmac,
                "_verify_immutable_baselines_post_run",
                side_effect=observe_immutable,
            ),
        ):
            with self.assertRaises(onesar_refmac.RefmacCollectorError) as cm:
                self._run_collector(
                    "diag_raw_first_and_combined_1184",
                    combined_runner,
                    diagnostic_profile=self.fx.profile,
                    evidence_root=evidence_root,
                )

        self.assertEqual(len(runner_calls), 1)
        self.assertEqual(audits, {"profile": 1, "trace": 1})
        self.assertEqual(len(expected_raw_pins), 5)
        self.assertEqual(set(observations.keys()), set(expected_raw_pins.keys()))
        self.assertEqual(
            set(first_raw_event_index.keys()), set(expected_raw_pins.keys())
        )
        self.assertLess(
            max(first_raw_event_index.values()),
            events.index("profile_inspection"),
        )
        self.assertLess(
            max(first_raw_event_index.values()),
            events.index("trace_inspection"),
        )

        err = cm.exception
        self.assertEqual(err.failed_stage, "refmac_runner_invocation")
        self.assertIs(err.primary_cause, runner_error)
        self.assertIs(err.__cause__, runner_error)
        self.assertTrue(err.publication_pair_complete)
        self.assertTrue(
            any(item is profile_error for item in captured_lists["mutations"])
        )
        self.assertTrue(
            any(item is profile_error for item in captured_lists["inspection"])
        )
        self.assertTrue(
            any(item is trace_error for item in captured_lists["inspection"])
        )

        assert err.manifest_path is not None
        assert err.diagnostics_path is not None
        manifest_path = Path(err.manifest_path)
        manifest_raw = manifest_path.read_bytes()
        manifest = self._reopen_json(
            {
                "path": str(manifest_path),
                "sha256": _sha256_bytes(manifest_raw),
                "size_bytes": len(manifest_raw),
            }
        )
        diagnostics = self._reopen_json(manifest["diagnostics_json"])
        post_cp = self._reopen_json(manifest["post_execution_checkpoint_json"])
        pre_cp = self._reopen_json(manifest["pre_execution_checkpoint_json"])
        self.assertEqual(manifest, err.manifest_payload)
        self.assertEqual(diagnostics, err.diagnostics_payload)
        self.assertEqual(pre_cp["schema_version"], 2)
        self.assertEqual(
            pre_cp["collector_stage"],
            "instrumented_native_trace_capture_v1",
        )

        for doc in (post_cp, diagnostics, manifest):
            self.assertEqual(doc["schema_version"], 2)
            self.assertEqual(
                doc["collector_stage"],
                "instrumented_native_trace_capture_v1",
            )
            self.assertEqual(
                doc["diagnostic_producer"]["profile_id"], SUPPORTED_PROFILE_ID
            )
            self.assertEqual(
                doc["diagnostic_producer"]["selected_executable"]["path"],
                str(self.fx.diagnostic_executable_path),
            )
            self.assertEqual(
                doc["diagnostic_activation_environment"],
                {
                    "REFMAC_DIAGNOSTIC_TRACE": str(native_trace_path),
                    "DYLD_PRINT_LIBRARIES": "1",
                },
            )
            raw_nt = doc["raw_outputs"]["native_trace"]
            self.assertEqual(raw_nt["path"], str(native_trace_path))
            self.assertEqual(
                raw_nt["sha256"], _sha256_bytes(raw_trace_bytes)
            )
            self.assertEqual(raw_nt["size_bytes"], len(raw_trace_bytes))
            self.assertEqual(
                native_trace_path.read_bytes(), raw_trace_bytes
            )

            post_prof = doc["diagnostic_profile_post_run"]
            self.assertFalse(post_prof["verified"])
            self.assertTrue(
                any(
                    row.get("type") == "OSError"
                    and row.get("message") == str(profile_error)
                    for row in post_prof["errors"]
                )
            )

            env_doc = doc["native_trace_envelope"]
            self.assertEqual(
                env_doc["first_failure"],
                {
                    "code": "envelope_inspection_exception",
                    "message": f"ValueError: {trace_error}",
                },
            )
            self.assertIsNone(env_doc["event_count"])
            self.assertIsNone(env_doc["record_count"])
            self.assertIsNone(env_doc["bytes_read"])
            self.assertIsNone(env_doc["partial_sha256"])
            self.assertIsNone(env_doc["partial_size_bytes"])
            self.assertIsNone(
                doc["operation_checks"]["native_trace_event_count"]
            )

            stages = [row["failed_stage"] for row in doc["failures"]]
            self.assertEqual(stages[0], "refmac_runner_invocation")
            self.assertIn("refmac_raw_outputs", stages)
            self.assertIn("verify_input_immutability", stages)
            self.assertIs(doc["scientific_admission_proven"], False)

        for doc in (diagnostics, manifest):
            for flag in (
                "canonical_eval_qds_eligible",
                "eval_admission_eligible",
                "qds_admission_eligible",
                "canary_admission_eligible",
                "scientific_admission_proven",
                "batch_execution_eligible",
                "all_preregistered_gates_passed",
            ):
                self.assertIs(doc[flag], False)


if __name__ == "__main__":
    unittest.main()
