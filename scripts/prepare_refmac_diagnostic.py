#!/usr/bin/env python3
"""Prepare a standalone instrumented REFMAC 5.8.0431 diagnostic source tree.

Verifies the immutable upstream REFMAC 5.8.0431 checkout (commit, tag, clean
tracked tree, full commit-tree Git blob SHA-1 inventory across every tracked
file, five hardcoded SHA-256 pins on hook-target files, and absence of extra
working-tree files), copies verified in-memory sources into a fresh destination
directory inside an authorized repository/worktree preparation area, copies
``trace_writer.f90`` and ``trace_hooks.f90``, applies additive hook insertions
by exact original line position without modifying or reordering any original
scientific line, and writes ``refmac_diagnostic_hooks.patch`` and
``refmac_diagnostic_source_manifest.json``.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parent.parent
DIAGNOSTIC_MODULE_DIR = REPO_ROOT / "scripts" / "refmac_diagnostic"
TRACE_WRITER_SOURCE = DIAGNOSTIC_MODULE_DIR / "trace_writer.f90"
TRACE_HOOKS_SOURCE = DIAGNOSTIC_MODULE_DIR / "trace_hooks.f90"

UPSTREAM_GIT_COMMIT = "be25e793829952f4f177d7dfd0c10a1eb6bbd180"
UPSTREAM_GIT_TAG = "5.8.0431"

PINNED_ORIGINAL_FILE_SHA256: dict[str, str] = {
    "subcf_scale1.f": "9cce606df4ef1bcdaf767f7fd16afa8027cef6fa062a231b18aaae9b55431f47",
    "refmac_completeness.f90": "ebd67e547eca2fa696047e443ebb4a23db0beca1a87b9ae2ee417ae4b1b788ef",
    "ls_scaling_double.f": "7e5c5edf8d751861ebb325240e331f85e4d5deed21e9b360ca72d93d772959d5",
    "refmac_xml.f": "baff00a370cd761caeba8838cdf8fd4246f7c223d78c87a6f520ef8f788baac8",
    "CMakeLists.txt": "708473c90a8ab98a09a1d32cd2049cb0b0b84281859f698ddacb25bab13c97c2",
}

PATCH_FILENAME = "refmac_diagnostic_hooks.patch"
MANIFEST_FILENAME = "refmac_diagnostic_source_manifest.json"
MANIFEST_SCHEMA_ID = "protstruct_refmac_diagnostic_source_manifest_v1"

FORBIDDEN_DIR_NAMES = frozenset(
    {".git", "build", "CMakeFiles", "_build", ".cmake", "__pycache__"}
)

ALLOWED_GIT_BLOB_MODES = frozenset({"100644", "100755"})

AUTHORIZED_PREPARATION_SUBPATHS: tuple[tuple[str, ...], ...] = (
    (".orchestration", "evidence", "601-instrumented-build"),
    (".temp",),
)


@dataclass(frozen=True)
class CommitTreeEntry:
    """One regular-file blob entry from the immutable pinned commit tree."""

    rel_path: str
    mode: str
    obj_type: str
    blob_id: str


@dataclass(frozen=True)
class HookInsertionSpec:
    """One additive source insertion anchored to an exact original line."""

    source_hook_id: str
    namespace: str
    rel_path: str
    original_line: int
    phase: str  # "before" or "after"
    anchor_text: str
    context_before: tuple[str, ...]
    context_after: tuple[str, ...]
    inserted_lines: tuple[str, ...]
    description: str


HOOK_INSERTION_SPECS: tuple[HookInsertionSpec, ...] = (
    # --- subcf_scale1.f (fixed-form Fortran, <= 72 columns) ---
    HookInsertionSpec(
        source_hook_id="L_import",
        namespace="residual_lsq",
        rel_path="subcf_scale1.f",
        original_line=19,
        phase="after",
        anchor_text="      use consts",
        context_before=("      use atomcom", "      use vitals"),
        context_after=("c", "c----Subroutine to calculate coefficients for fourie transformation"),
        inserted_lines=(
            "      use protstruct_diagnostic_hooks, only:",
            "     &  trace_hook_lsq_l0_begin, trace_hook_lsq_l0_freer,",
            "     &  trace_hook_lsq_l0_aniso, trace_hook_lsq_l0_bulk,",
            "     &  trace_hook_lsq_l0_parts, trace_hook_lsq_l0_end,",
            "     &  trace_hook_lsq_l1, trace_hook_lsq_l2_with_freer,",
            "     &  trace_hook_lsq_l2_no_freer, trace_hook_lsq_l3,",
            "     &  trace_hook_lsq_l4_valid, trace_hook_lsq_l4_invalid,",
            "     &  trace_hook_lsq_l5_valid, trace_hook_lsq_l5_invalid,",
            "     &  trace_hook_lsq_l6a_valid, trace_hook_lsq_l6a_invalid,",
            "     &  trace_hook_lsq_l6b_valid, trace_hook_lsq_l6b_invalid,",
            "     &  trace_hook_lsq_l7, trace_hook_lsq_l8_valid,",
            "     &  trace_hook_lsq_l8_invalid, trace_hook_lsq_l9_work_valid,",
            "     &  trace_hook_lsq_l9_work_invalid, trace_hook_lsq_l9_free_valid,",
            "     &  trace_hook_lsq_l9_free_invalid,",
            "     &  trace_hook_lsq_final_carrier_work_valid,",
            "     &  trace_hook_lsq_final_carrier_work_invalid,",
            "     &  trace_hook_lsq_final_carrier_free_valid,",
            "     &  trace_hook_lsq_final_carrier_free_invalid,",
            "     &  trace_hook_lsq_l_end, trace_lsq_accumulators_valid,",
            "     &  trace_lsq_can_capture_addition",
        ),
        description="Import diagnostic hook procedures in LSQ_COEF.",
    ),
    HookInsertionSpec(
        source_hook_id="L0",
        namespace="residual_lsq",
        rel_path="subcf_scale1.f",
        original_line=94,
        phase="after",
        anchor_text="      CALL FIND_NREFINED_ATOMS(N_REFINED_ATOMS)",
        context_before=("      IF(LREFIN.AND.REFS.EQ.'LSQF') IMODE = 2",),
        context_after=("      DO     I=1,NREF",),
        inserted_lines=(
            "      CALL trace_hook_lsq_l0_begin(NREF,NOBS,NPART,ndens,NBIN,NB1,",
            "     &  IMODE,N_REFINED_ATOMS,NREF_PARS,NSMULT,IFACTOR_CC,LREFIN,",
            "     &  REFS,FREER_FLAG,LEXPUSE,DataSource,phase_flag,MIR_FLAG,",
            "     &  SMINB,SMAXB,SCALE_LS_OVER,B_LS_OVER,B_LS_OVER_FLAG,",
            "     &  B_LS_OVER_REFINE_FLAG,B_LS_ANISO_OVER_FLAG,",
            "     &  B_LS_ANISO_OVER_REFINE_FLAG,BULK_LS_FLAG,",
            "     &  SCALE_LS_BULK_REFINE_FLAG,B_LS_BULK_REFINE_FLAG)",
            "      IF(FREER_FLAG) THEN",
            "        CALL trace_hook_lsq_l0_freer(LFreeRexcludeVal)",
            "      ENDIF",
            "      IF(B_LS_ANISO_OVER_FLAG) THEN",
            "        CALL trace_hook_lsq_l0_aniso(B_LS_ANISO_OVER,RCELL)",
            "      ENDIF",
            "      IF(BULK_LS_FLAG) THEN",
            "        CALL trace_hook_lsq_l0_bulk(SCALE_LS_BULK,B_LS_BULK)",
            "      ENDIF",
            "      IF(NPART.GT.0) THEN",
            "        CALL trace_hook_lsq_l0_parts(NPART,SCALE_LS_PART,",
            "     &    B_LS_PART,SCALE_LS_PART_REFINE_FLAG,",
            "     &    B_LS_PART_REFINE_FLAG)",
            "      ENDIF",
            "      CALL trace_hook_lsq_l0_end()",
        ),
        description="Emit LSQ_COEF call header with conditionally guarded scale state and bounds.",
    ),
    HookInsertionSpec(
        source_hook_id="L1",
        namespace="residual_lsq",
        rel_path="subcf_scale1.f",
        original_line=95,
        phase="after",
        anchor_text="      DO     I=1,NREF",
        context_before=("      CALL FIND_NREFINED_ATOMS(N_REFINED_ATOMS)",),
        context_after=("        YO  = FO(I)",),
        inserted_lines=(
            "        CALL trace_hook_lsq_l1(I)",
        ),
        description="Reset per-row trace-owned state at start of reflection loop iteration.",
    ),
    HookInsertionSpec(
        source_hook_id="L2",
        namespace="residual_lsq",
        rel_path="subcf_scale1.f",
        original_line=108,
        phase="after",
        anchor_text="        DY    = 0.0",
        context_before=(
            "        RSQ   = LSTLSQ(1,IHH(1),IHH(2),IHH(3))",
            "        RHO   = SQRT(RSQ)",
        ),
        context_after=("        IF(SO.GT.0.0) then",),
        inserted_lines=(
            "        IF(FREER_FLAG) THEN",
            "          CALL trace_hook_lsq_l2_with_freer(I,IHH,YO,SO,JMN,",
            "     &      IFREE,FREER(I),RSQ,RHO,DY)",
            "        ELSE",
            "          CALL trace_hook_lsq_l2_no_freer(I,IHH,YO,SO,JMN,",
            "     &      IFREE,RSQ,RHO,DY)",
            "        ENDIF",
        ),
        description="Capture per-row input state in LSQ_COEF with FREER(I) guarded by FREER_FLAG.",
    ),
    HookInsertionSpec(
        source_hook_id="L3",
        namespace="residual_lsq",
        rel_path="subcf_scale1.f",
        original_line=123,
        phase="after",
        anchor_text="           WDY    = SQRTW*DY",
        context_before=(
            "           SQRTW  = 1.0/SIGAPP",
            "           DY     = YOS-YC_ALL",
        ),
        context_after=("        else",),
        inserted_lines=(
            "           CALL trace_hook_lsq_l3(I,YOS,YC_ALL,PHASE_ALL,SIGOS,",
            "     &       SIGEXPER,SIGAPP,SQRTW,DY,WDY,F_VALUE_C)",
        ),
        description="Capture operand state inside actual SO > 0 branch.",
    ),
    HookInsertionSpec(
        source_hook_id="L4",
        namespace="residual_lsq",
        rel_path="subcf_scale1.f",
        original_line=136,
        phase="before",
        anchor_text="            IF(SO.LE.0.0)  GO TO 100",
        context_before=(
            "        DO     J=1,NBIN",
            "          IF(RHO.GE.SMINB(J).AND.RHO.LE.SMAXB(J)) THEN",
        ),
        context_after=("            AFOMFC(IFREE,J) = AFOMFC(IFREE,J) + ABS(DY)",),
        inserted_lines=(
            "            IF(trace_lsq_accumulators_valid()) THEN",
            "              CALL trace_hook_lsq_l4_valid(I,J,IFREE,SMINB(J),",
            "     &          SMAXB(J),nrefa_this(IFREE,J),AFOMFC(IFREE,J),",
            "     &          AFOFO(IFREE,J),AFOFC(IFREE,J),AFCFC(IFREE,J),",
            "     &          AFC(IFREE,J),AFO(IFREE,J),ASIG(IFREE,J),",
            "     &          WFOMFC(IFREE,J),wfomfc2(ifree,j),WFO(IFREE,J),",
            "     &          WFOFO(IFREE,J))",
            "            ELSE",
            "              CALL trace_hook_lsq_l4_invalid(I,J,IFREE,SMINB(J),",
            "     &          SMAXB(J),nrefa_this(IFREE,J))",
            "            ENDIF",
        ),
        description="Capture matched shell J and pre-addition shell accumulators before sigma guard.",
    ),
    HookInsertionSpec(
        source_hook_id="L5",
        namespace="residual_lsq",
        rel_path="subcf_scale1.f",
        original_line=148,
        phase="after",
        anchor_text="            WFOFO(IFREE,J)  = WFOFO(IFREE,J)  + (SQRTW*YOS)**2",
        context_before=(
            "            wfomfc2(ifree,j) = wfomfc2(ifree,j) + wdy**2",
            "            WFO(IFREE,J)    = WFO(IFREE,J)    + SQRTW*YOS",
        ),
        context_after=("            if(Datasource.eq.'EM'.and.phase_flag) then",),
        inserted_lines=(
            "            IF(trace_lsq_can_capture_addition()) THEN",
            "              CALL trace_hook_lsq_l5_valid(I,J,IFREE,",
            "     &          nrefa_this(IFREE,J),AFOMFC(IFREE,J),AFOFO(IFREE,J),",
            "     &          AFOFC(IFREE,J),AFCFC(IFREE,J),AFC(IFREE,J),",
            "     &          AFO(IFREE,J),ASIG(IFREE,J),WFOMFC(IFREE,J),",
            "     &          wfomfc2(ifree,j),WFO(IFREE,J),WFOFO(IFREE,J))",
            "            ELSE",
            "              CALL trace_hook_lsq_l5_invalid(I,J,IFREE,",
            "     &          nrefa_this(IFREE,J))",
            "            ENDIF",
        ),
        description="Capture post-addition shell accumulators, or latch call-wide invalidity if L3 did not run.",
    ),
    HookInsertionSpec(
        source_hook_id="L6a",
        namespace="residual_lsq",
        rel_path="subcf_scale1.f",
        original_line=171,
        phase="before",
        anchor_text="        AFOMFC(IFREE,NB1) = AFOMFC(IFREE,NB1) + ABS(DY)",
        context_before=(
            "        IF(SO.LE.0.0) GOTO 101",
            "C",
            "C---  Totals",
        ),
        context_after=("        AFOFO(IFREE,NB1)  = AFOFO(IFREE,NB1)  + YOS*YOS",),
        inserted_lines=(
            "        IF(trace_lsq_can_capture_addition()) THEN",
            "          CALL trace_hook_lsq_l6a_valid(I,NB1,IFREE,",
            "     &      nrefa_this(IFREE,NB1),AFOMFC(IFREE,NB1),",
            "     &      AFOFO(IFREE,NB1),AFOFC(IFREE,NB1),AFCFC(IFREE,NB1),",
            "     &      AFC(IFREE,NB1),AFO(IFREE,NB1),ASIG(IFREE,NB1),",
            "     &      WFOMFC(IFREE,NB1),wfomfc2(ifree,nb1),WFO(IFREE,NB1),",
            "     &      WFOFO(IFREE,NB1))",
            "        ELSE",
            "          CALL trace_hook_lsq_l6a_invalid(I,NB1,IFREE,",
            "     &      nrefa_this(IFREE,NB1))",
            "        ENDIF",
        ),
        description="Capture overall (NB1) pre-addition state guarded by L3 and call validity.",
    ),
    HookInsertionSpec(
        source_hook_id="L6b",
        namespace="residual_lsq",
        rel_path="subcf_scale1.f",
        original_line=185,
        phase="after",
        anchor_text="        WFOFO(IFREE,NB1)  = WFOFO(IFREE,NB1)  + (SQRTW*YOS)**2",
        context_before=(
            "        wfomfc2(ifree,nb1) = wfomfc2(ifree,nb1) + wdy**2",
            "        WFO(IFREE,NB1)    = WFO(IFREE,NB1)    + SQRTW*YOS",
        ),
        context_after=(
            "C",
            "C---  Coefficients for gradient and second derivative calculation",
        ),
        inserted_lines=(
            "        IF(trace_lsq_can_capture_addition()) THEN",
            "          CALL trace_hook_lsq_l6b_valid(I,NB1,IFREE,",
            "     &      nrefa_this(IFREE,NB1),AFOMFC(IFREE,NB1),",
            "     &      AFOFO(IFREE,NB1),AFOFC(IFREE,NB1),AFCFC(IFREE,NB1),",
            "     &      AFC(IFREE,NB1),AFO(IFREE,NB1),ASIG(IFREE,NB1),",
            "     &      WFOMFC(IFREE,NB1),wfomfc2(ifree,nb1),WFO(IFREE,NB1),",
            "     &      WFOFO(IFREE,NB1))",
            "        ELSE",
            "          CALL trace_hook_lsq_l6b_invalid(I,NB1,IFREE,",
            "     &      nrefa_this(IFREE,NB1))",
            "        ENDIF",
        ),
        description="Capture overall (NB1) post-addition state guarded by L3 and call validity.",
    ),
    HookInsertionSpec(
        source_hook_id="L7",
        namespace="residual_lsq",
        rel_path="subcf_scale1.f",
        original_line=209,
        phase="after",
        anchor_text=" 101    CONTINUE",
        context_before=("        ENDIF",),
        context_after=("      ENDDO",),
        inserted_lines=(
            "        CALL trace_hook_lsq_l7(I)",
        ),
        description="Emit terminal per-row outcome in LSQ_COEF from trace-owned branch flags only.",
    ),
    HookInsertionSpec(
        source_hook_id="L8",
        namespace="residual_lsq",
        rel_path="subcf_scale1.f",
        original_line=210,
        phase="after",
        anchor_text="      ENDDO",
        context_before=(" 101    CONTINUE",),
        context_after=("", "C", "c---Compile statistics"),
        inserted_lines=(
            "      IF(trace_lsq_accumulators_valid()) THEN",
            "        CALL trace_hook_lsq_l8_valid(NBIN,NB1,NBM,nrefa_this,",
            "     &    NREFA,NREFM,AFOMFC,AFOFO,AFOFC,AFCFC,AFC,AFO,ASIG,",
            "     &    WFOMFC,wfomfc2,WFO,WFOFO,FXRAY,FXFREE)",
            "      ELSE",
            "        CALL trace_hook_lsq_l8_invalid(NBIN,NB1,NBM,nrefa_this,",
            "     &    NREFA,NREFM)",
            "      ENDIF",
        ),
        description="Capture raw 2xNB1 sums/counts before statistics divide AFO/AFC into means.",
    ),
    HookInsertionSpec(
        source_hook_id="L9_work",
        namespace="residual_lsq",
        rel_path="subcf_scale1.f",
        original_line=233,
        phase="after",
        anchor_text="          HRFAC_SHELL_WORK(I)  = AFOMFC(1,I)/AFO(1,I)",
        context_before=("        IF(NREFA_this(1,I).GT.0) THEN",),
        context_after=("          HRFAC_SHELL_ALL(I)   = (AFOMFC(1,I) + AFOMFC(2,I))/",),
        inserted_lines=(
            "          IF(trace_lsq_accumulators_valid()) THEN",
            "            CALL trace_hook_lsq_l9_work_valid(I,NB1,",
            "     &        nrefa_this(1,I),AFOMFC(1,I),AFO(1,I),",
            "     &        HRFAC_SHELL_WORK(I))",
            "          ELSE",
            "            CALL trace_hook_lsq_l9_work_invalid(I,NB1,",
            "     &        nrefa_this(1,I))",
            "          ENDIF",
        ),
        description="Capture fresh work-partition division inside NREFA_this(1,I) > 0 branch.",
    ),
    HookInsertionSpec(
        source_hook_id="L9_free",
        namespace="residual_lsq",
        rel_path="subcf_scale1.f",
        original_line=294,
        phase="after",
        anchor_text="          HRFAC_SHELL_FREE(I)  = AFOMFC(2,I)/AFO(2,I)",
        context_before=("        IF(NREFA_this(2,I).GT.0) THEN",),
        context_after=("          HWRFAC_SHELL_FREE(I)  = WFOMFC(2,I)/WFO(2,I)",),
        inserted_lines=(
            "          IF(trace_lsq_accumulators_valid()) THEN",
            "            CALL trace_hook_lsq_l9_free_valid(I,NB1,",
            "     &        nrefa_this(2,I),AFOMFC(2,I),AFO(2,I),",
            "     &        HRFAC_SHELL_FREE(I))",
            "          ELSE",
            "            CALL trace_hook_lsq_l9_free_invalid(I,NB1,",
            "     &        nrefa_this(2,I))",
            "          ENDIF",
        ),
        description="Capture fresh free-partition division inside NREFA_this(2,I) > 0 branch.",
    ),
    HookInsertionSpec(
        source_hook_id="final_carrier_work",
        namespace="residual_lsq",
        rel_path="subcf_scale1.f",
        original_line=384,
        phase="after",
        anchor_text="      RFACTOR_WORK      = HRFAC_SHELL_WORK(NB1)",
        context_before=("c      NHREFL_WORK       = NREFA(1,NB1)",),
        context_after=("      RWFACTOR_WORK     = HWRFAC_SHELL_WORK(NB1)",),
        inserted_lines=(
            "      IF(nrefa_this(1,NB1).GT.0.AND.",
            "     &   trace_lsq_accumulators_valid()) THEN",
            "        CALL trace_hook_lsq_final_carrier_work_valid(NB1,",
            "     &    nrefa_this(1,NB1),NREFA(1,NB1),HRFAC_SHELL_WORK(NB1),",
            "     &    RFACTOR_WORK)",
            "      ELSE",
            "        CALL trace_hook_lsq_final_carrier_work_invalid(NB1,",
            "     &    nrefa_this(1,NB1),NREFA(1,NB1))",
            "      ENDIF",
        ),
        description="Record RFACTOR_WORK carrier assignment guarded by current-call nrefa_this(1,NB1) > 0 and numeric validity.",
    ),
    HookInsertionSpec(
        source_hook_id="final_carrier_free",
        namespace="residual_lsq",
        rel_path="subcf_scale1.f",
        original_line=392,
        phase="after",
        anchor_text="         RFACTOR_FREE    = HRFAC_SHELL_FREE(NB1)",
        context_before=(
            "      IF(FREER_FLAG.AND.NREFA(2,NB1).GT.0) THEN",
            "         NHREFL_FREE     = NREFA(2,NB1)",
        ),
        context_after=("         RWFACTOR_FREE   = HWRFAC_SHELL_FREE(NB1)",),
        inserted_lines=(
            "         IF(trace_lsq_accumulators_valid()) THEN",
            "           CALL trace_hook_lsq_final_carrier_free_valid(NB1,",
            "     &       nrefa_this(2,NB1),NREFA(2,NB1),NHREFL_FREE,",
            "     &       HRFAC_SHELL_FREE(NB1),RFACTOR_FREE)",
            "         ELSE",
            "           CALL trace_hook_lsq_final_carrier_free_invalid(NB1,",
            "     &       nrefa_this(2,NB1),NREFA(2,NB1),NHREFL_FREE)",
            "         ENDIF",
        ),
        description="Record RFACTOR_FREE carrier assignment separately from fresh L9_free division.",
    ),
    HookInsertionSpec(
        source_hook_id="L_end",
        namespace="residual_lsq",
        rel_path="subcf_scale1.f",
        original_line=421,
        phase="before",
        anchor_text="      RETURN",
        context_before=("C-----", "      !stop"),
        context_after=("      END",),
        inserted_lines=(
            "      CALL trace_hook_lsq_l_end()",
        ),
        description="Emit mandatory LSQ_COEF call end record and clear active invocation state.",
    ),
    # --- ls_scaling_double.f (fixed-form Fortran, <= 72 columns) ---
    HookInsertionSpec(
        source_hook_id="S_import",
        namespace="residual_lsq",
        rel_path="ls_scaling_double.f",
        original_line=520,
        phase="after",
        anchor_text="      use refi_flags",
        context_before=(
            "      SUBROUTINE SUMSFS_LS_DERIV(IR,NREF,ndens,hkl_asym,FO,SIGO,",
            "     &     FC,PHC,YOS,",
            "     &     YC_ALL,PHI_ALL,SIGOS,DFA,DFB,D2FDA2,D2FDB2,F_VALUE_C,IMODE)",
            "      use weights",
            "      use agreem",
            "      use CellAndSymmetry",
        ),
        context_after=("      IMPLICIT NONE",),
        inserted_lines=(
            "      use protstruct_diagnostic_hooks, only:",
            "     &  trace_hook_sumsfs_ls_deriv",
        ),
        description="Import SUMSFS_LS_DERIV hook in ls_scaling_double.f.",
    ),
    HookInsertionSpec(
        source_hook_id="S0_sumsfs_ls_deriv",
        namespace="residual_lsq",
        rel_path="ls_scaling_double.f",
        original_line=631,
        phase="after",
        anchor_text="      DELTA  = YOS - YC_ALL",
        context_before=("      YC_ALL = YC_ALL0*EXPAN_BULK_SCALE",),
        context_after=("      sig_l = sigo(ir)", "      sig_l = 1.0"),
        inserted_lines=(
            "      CALL trace_hook_sumsfs_ls_deriv(IR,NREF,ndens,IMODE,NPART,",
            "     &  NOBS,IHH,RSQ,RHO,YO,YOS,SIGOS,EXPAN,DBULK,EXPAN_BULK,",
            "     &  EXP_PROT,EXPAN_BULK_SCALE,YC0,YC_ALL0,PHI0,PHI_ALL,",
            "     &  AC_ALL,BC_ALL,YC_ALL,DELTA)",
        ),
        description="Capture assigned SUMSFS_LS_DERIV scale/structure-factor terms when called from active LSQ_COEF row.",
    ),
    # --- refmac_completeness.f90 (free-form Fortran) ---
    HookInsertionSpec(
        source_hook_id="C_import",
        namespace="reporting_completeness",
        rel_path="refmac_completeness.f90",
        original_line=9,
        phase="after",
        anchor_text="    use refi_flags",
        context_before=("    use agreem", "    use rharvest"),
        context_after=("    ", "    real, intent(in) :: rot(:,:,:), tr(:,:)"),
        inserted_lines=(
            "    use protstruct_diagnostic_hooks, only: &",
            "      trace_hook_comp_c0, trace_hook_comp_c1, trace_hook_comp_c2, &",
            "      trace_hook_comp_c3, trace_hook_comp_c4, &",
            "      trace_hook_comp_c5_with_free, trace_hook_comp_c5_no_free, &",
            "      trace_hook_comp_c_end",
        ),
        description="Import completeness diagnostic hooks in calc_completeness.",
    ),
    HookInsertionSpec(
        source_hook_id="C0",
        namespace="reporting_completeness",
        rel_path="refmac_completeness.f90",
        original_line=123,
        phase="after",
        anchor_text="    call define_res_pars(cell_l,ast,bst,cst,cosast,cosbst,coscst)",
        context_before=("    if(maxval(abs(cell_l(4:6))).gt.pi) then", "       cell_l(4:6) = cell_l(4:6)*degtor", "    endif"),
        context_after=("", "    do i=1,nasym"),
        inserted_lines=(
            "    call trace_hook_comp_c0(nsym,nasym,nref,nbin,nb1,res_max, &",
            "      freer_flag,cell,cell_l,ast,bst,cst,cosast,cosbst,coscst, &",
            "      sminb,smaxb)",
        ),
        description="Emit completeness_begin call header before ASU loop.",
    ),
    HookInsertionSpec(
        source_hook_id="C1",
        namespace="reporting_completeness",
        rel_path="refmac_completeness.f90",
        original_line=132,
        phase="after",
        anchor_text="       rho = sqrt(rsq/4.0)",
        context_before=(
            "       if(freer_observed(i).eq.0) ifree=2",
            "       call define_res(hkl_asym(1,i),hkl_asym(2,i),hkl_asym(3,i),ast,bst,cst,cosast,cosbst,coscst,rsq) ",
        ),
        context_after=("       do  j=1,nbin",),
        inserted_lines=(
            "       call trace_hook_comp_c1(i,hkl_asym(1,i),hkl_asym(2,i), &",
            "         hkl_asym(3,i),hkl_observed(i),freer_observed(i),jmn, &",
            "         ifree,rsq,rho)",
        ),
        description="Emit generated-ASU reflection row input in calc_completeness.",
    ),
    HookInsertionSpec(
        source_hook_id="C2",
        namespace="reporting_completeness",
        rel_path="refmac_completeness.f90",
        original_line=139,
        phase="after",
        anchor_text="             endif",
        context_before=(
            "             if(hkl_observed(i).gt.0) then",
            "                nrefa(ifree,j) = nrefa(ifree,j) + 1",
            "             else",
            "                nrefm(ifree,j) = nrefm(ifree,j) + 1",
        ),
        context_after=("          endif", "       enddo"),
        inserted_lines=(
            "             call trace_hook_comp_c2(i,j,ifree,hkl_observed(i), &",
            "               sminb(j),smaxb(j),nrefa(ifree,j),nrefm(ifree,j))",
        ),
        description="Capture every matching shell increment in calc_completeness (preserving all-match shell semantics).",
    ),
    HookInsertionSpec(
        source_hook_id="C3",
        namespace="reporting_completeness",
        rel_path="refmac_completeness.f90",
        original_line=146,
        phase="after",
        anchor_text="       endif",
        context_before=(
            "       if(hkl_observed(i).gt.0) then",
            "          nrefa(ifree,nb1) = nrefa(ifree,nb1) + 1",
            "       else",
            "          nrefm(ifree,nb1) = nrefm(ifree,nb1) + 1",
        ),
        context_after=("    enddo",),
        inserted_lines=(
            "       call trace_hook_comp_c3(i,nb1,ifree,hkl_observed(i), &",
            "         nrefa(ifree,nb1),nrefm(ifree,nb1))",
        ),
        description="Capture separate overall (NB1) observed/missing increment in calc_completeness.",
    ),
    HookInsertionSpec(
        source_hook_id="C4",
        namespace="reporting_completeness",
        rel_path="refmac_completeness.f90",
        original_line=147,
        phase="before",
        anchor_text="    enddo",
        context_before=(
            "       else",
            "          nrefm(ifree,nb1) = nrefm(ifree,nb1) + 1",
            "       endif",
        ),
        context_after=(
            "    !",
            "    !  finalise calculation by copying all necessary info to harvest files",
        ),
        inserted_lines=(
            "       call trace_hook_comp_c4(i,ifree,hkl_observed(i))",
        ),
        description="Emit per-ASU-row terminal outcome in calc_completeness.",
    ),
    HookInsertionSpec(
        source_hook_id="C5",
        namespace="reporting_completeness",
        rel_path="refmac_completeness.f90",
        original_line=174,
        phase="after",
        anchor_text="    endif",
        context_before=(
            "    if(freer_flag.and.nrefa(2,nb1).gt.0) then",
            "       nhrefl_free = nrefa(2,nb1)",
            "       if(nhrefl_work + nhrefl_free.gt.0) then",
            "          perc_free = float(nhrefl_free)/float(nhrefl_work+nhrefl_free)*100.0",
            "       endif",
        ),
        context_after=("", "    ", "    deallocate(hkl_asym)"),
        inserted_lines=(
            "    if(freer_flag.and.nrefa(2,nb1).gt.0) then",
            "       call trace_hook_comp_c5_with_free(nbin,nb1,NBM,HMAXSHELL, &",
            "         freer_flag,nrefa,nrefm,hnref_shell_work,hnref_shell_free, &",
            "         hnref_shell_obs,hnref_shell_all,hperc_shell_refl, &",
            "         nhrefl_work,nhrefl_free,perc_free)",
            "    else",
            "       call trace_hook_comp_c5_no_free(nbin,nb1,NBM,HMAXSHELL, &",
            "         freer_flag,nrefa,nrefm,hnref_shell_work,hnref_shell_free, &",
            "         hnref_shell_obs,hnref_shell_all,hperc_shell_refl, &",
            "         nhrefl_work,perc_free)",
            "    endif",
        ),
        description="Emit completeness summary after harvest array assignments.",
    ),
    HookInsertionSpec(
        source_hook_id="C_end",
        namespace="reporting_completeness",
        rel_path="refmac_completeness.f90",
        original_line=177,
        phase="before",
        anchor_text="    deallocate(hkl_asym)",
        context_before=("", "    "),
        context_after=(
            "    deallocate(hkl_observed)",
            "    deallocate(freer_observed)",
        ),
        inserted_lines=(
            "    call trace_hook_comp_c_end()",
        ),
        description="Emit mandatory completeness call end before deallocation.",
    ),
    # --- refmac_xml.f (fixed-form Fortran, <= 72 columns) ---
    HookInsertionSpec(
        source_hook_id="T_import",
        namespace="lifecycle",
        rel_path="refmac_xml.f",
        original_line=28,
        phase="after",
        anchor_text="      use hd_mixtures",
        context_before=("      use coords",),
        context_after=("C------------------------------------------------------------------------",),
        inserted_lines=(
            "      use protstruct_diagnostic_hooks, only:",
            "     &  trace_hook_normal_termination",
        ),
        description="Import normal termination wrapper in PROGRAM refmac5.",
    ),
    HookInsertionSpec(
        source_hook_id="T_close",
        namespace="lifecycle",
        rel_path="refmac_xml.f",
        original_line=297,
        phase="after",
        anchor_text="      CALL REFMAC_CLEAN_UP_FILES",
        context_before=(
            "      ierr = 0",
            "      call write_xml(ierr,'normal termination')",
        ),
        context_after=(
            "      CALL CCPERR(0,'End of Refmac_'//R_VERSNO)",
            "      END",
        ),
        inserted_lines=(
            "      CALL trace_hook_normal_termination()",
        ),
        description="Close native diagnostic trace on normal refmac5 termination path only.",
    ),
    # --- CMakeLists.txt ---
    HookInsertionSpec(
        source_hook_id="CMake_refmac5_sources",
        namespace="build",
        rel_path="CMakeLists.txt",
        original_line=33,
        phase="after",
        anchor_text="add_executable(refmac5",
        context_before=("",),
        context_after=("stats_calc.f90", "makecif_pars.f90"),
        inserted_lines=(
            "trace_writer.f90",
            "trace_hooks.f90",
        ),
        description="Add trace_writer.f90 and trace_hooks.f90 to refmac5 target only.",
    ),
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compute_git_blob_sha1(data: bytes) -> str:
    """Compute canonical Git blob SHA-1 digest over ('blob <size>\\0' + data)."""
    header = f"blob {len(data)}\x00".encode("ascii")
    hasher = hashlib.sha1()
    hasher.update(header)
    hasher.update(data)
    return hasher.hexdigest()


def _regular_file_bytes_and_sha256(path: Path) -> tuple[bytes, int, str]:
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode):
        raise ValueError(f"Symlink file rejected: {path}")
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"Regular file required: {path}")
    raw = path.read_bytes()
    return raw, len(raw), _sha256_bytes(raw)


def _reject_symlink_chain(path: Path, *, allow_missing_leaf: bool) -> Path:
    expanded = path.expanduser()
    if not expanded.is_absolute():
        expanded = Path.cwd() / expanded
    current = Path(expanded.root)
    parts = expanded.parts[1:]
    for idx, part in enumerate(parts):
        if part in ("", "."):
            continue
        if part == "..":
            raise ValueError(f"Parent traversal '..' not allowed in path: {path}")
        current = current / part
        is_last = idx == len(parts) - 1
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            if is_last and allow_missing_leaf:
                continue
            raise ValueError(f"Required path component does not exist: {current}") from None
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(f"Symlink component rejected in path: {current}")
    return current


def _normalize_allowed_area_root(path: Path) -> Path:
    """Validate an authorized preparation area root, rejecting '..' and symlinks."""
    expanded = path.expanduser()
    if not expanded.is_absolute():
        expanded = Path.cwd() / expanded
    current = Path(expanded.root)
    parts = expanded.parts[1:]
    missing_tail: list[str] = []
    for part in parts:
        if part in ("", "."):
            continue
        if part == "..":
            raise ValueError(
                f"Parent traversal '..' not allowed in allowed output root: {path}"
            )
        if missing_tail:
            missing_tail.append(part)
            continue
        next_path = current / part
        try:
            info = os.lstat(next_path)
        except FileNotFoundError:
            missing_tail.append(part)
            continue
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(
                f"Symlink component rejected in allowed output root: {next_path}"
            )
        current = next_path
    resolved = current.resolve(strict=True)
    for part in missing_tail:
        resolved = resolved / part
    return resolved


def _git_clean_environment() -> dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("GIT_")
    }
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    env["GIT_NO_REPLACE_OBJECTS"] = "1"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return env


def discover_authorized_preparation_roots(
    repo_root: Path = REPO_ROOT,
) -> tuple[Path, ...]:
    """Return authorized preparation base directories for PRIMARY and active worktree."""
    resolved_repo = Path(repo_root).resolve()
    candidate_repo_roots: list[Path] = [resolved_repo]
    env = _git_clean_environment()

    try:
        top_proc = subprocess.run(
            ["git", "-C", str(resolved_repo), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        if top_proc.returncode == 0 and top_proc.stdout.strip():
            top_root = Path(top_proc.stdout.strip()).resolve()
            if top_root not in candidate_repo_roots:
                candidate_repo_roots.append(top_root)

        common_proc = subprocess.run(
            ["git", "-C", str(resolved_repo), "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        if common_proc.returncode == 0 and common_proc.stdout.strip():
            raw_common = Path(common_proc.stdout.strip())
            if not raw_common.is_absolute():
                raw_common = resolved_repo / raw_common
            resolved_common = raw_common.resolve()
            primary_root = (
                resolved_common.parent
                if resolved_common.name == ".git"
                else resolved_common
            )
            if primary_root not in candidate_repo_roots:
                candidate_repo_roots.append(primary_root)
    except OSError:
        pass

    allowed_areas: list[Path] = []
    for base_root in candidate_repo_roots:
        for subpath in AUTHORIZED_PREPARATION_SUBPATHS:
            area = base_root.joinpath(*subpath)
            if area not in allowed_areas:
                allowed_areas.append(area)
    return tuple(allowed_areas)


def _validate_source_and_output_paths(
    source_dir: Path | str,
    output_dir: Path | str,
    *,
    allowed_output_roots: Sequence[Path] | None = None,
) -> tuple[Path, Path]:
    """Validate source/output paths, rejecting symlinks, existing output, overlap, and out-of-boundary destinations."""
    source_path = _reject_symlink_chain(Path(source_dir), allow_missing_leaf=False)
    if not source_path.is_dir():
        raise ValueError(f"Source path must be an existing directory: {source_path}")

    output_path = _reject_symlink_chain(Path(output_dir), allow_missing_leaf=True)
    if output_path.exists():
        raise FileExistsError(f"Output path already exists: {output_path}")

    resolved_source = source_path.resolve(strict=True)
    resolved_output_parent = output_path.parent.resolve(strict=True)
    resolved_output = resolved_output_parent / output_path.name

    if (
        resolved_output == resolved_source
        or resolved_output.is_relative_to(resolved_source)
        or resolved_source.is_relative_to(resolved_output)
    ):
        raise ValueError(
            f"Source and output paths must not overlap: source={resolved_source}, output={resolved_output}"
        )

    raw_allowed_roots = (
        discover_authorized_preparation_roots()
        if allowed_output_roots is None
        else tuple(Path(p) for p in allowed_output_roots)
    )
    if not raw_allowed_roots:
        raise ValueError("No authorized diagnostic preparation roots configured")

    normalized_allowed_roots = tuple(
        _normalize_allowed_area_root(area) for area in raw_allowed_roots
    )
    if not any(
        resolved_output != area_root and resolved_output.is_relative_to(area_root)
        for area_root in normalized_allowed_roots
    ):
        allowed_str = ", ".join(str(p) for p in normalized_allowed_roots)
        raise ValueError(
            f"Output path {resolved_output} is outside authorized diagnostic "
            f"preparation areas ({allowed_str})"
        )

    return resolved_source, resolved_output


def validate_source_and_output_paths(
    source_dir: Path | str, output_dir: Path | str
) -> tuple[Path, Path]:
    """Validate source/output paths against the repository's authorized preparation areas."""
    return _validate_source_and_output_paths(
        source_dir, output_dir, allowed_output_roots=None
    )


def verify_vendor_git_checkout(
    source_root: Path,
    *,
    expected_commit: str = UPSTREAM_GIT_COMMIT,
    expected_tag: str = UPSTREAM_GIT_TAG,
) -> tuple[dict[str, Any], dict[str, CommitTreeEntry]]:
    """Verify exact Git commit, tag, clean status, and immutable commit-tree blob map via shell-free git."""
    env = _git_clean_environment()

    head_proc = subprocess.run(
        ["git", "-C", str(source_root), "rev-parse", "--verify", "HEAD"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if head_proc.returncode != 0:
        raise ValueError(
            f"Failed to verify git HEAD in {source_root}: {head_proc.stderr.strip()}"
        )
    actual_commit = head_proc.stdout.strip()
    if actual_commit != expected_commit:
        raise ValueError(
            f"Upstream git commit mismatch: expected {expected_commit!r}, got {actual_commit!r}"
        )

    tag_proc = subprocess.run(
        [
            "git",
            "-C",
            str(source_root),
            "rev-parse",
            "--verify",
            f"refs/tags/{expected_tag}^{{commit}}",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if tag_proc.returncode != 0:
        raise ValueError(
            f"Failed to verify git tag {expected_tag!r} in {source_root}: {tag_proc.stderr.strip()}"
        )
    tag_commit = tag_proc.stdout.strip()
    if tag_commit != expected_commit:
        raise ValueError(
            f"Upstream git tag {expected_tag!r} resolves to {tag_commit!r}, expected {expected_commit!r}"
        )

    status_proc = subprocess.run(
        [
            "git",
            "-C",
            str(source_root),
            "status",
            "--porcelain",
            "--untracked-files=all",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    if status_proc.returncode != 0:
        raise ValueError(
            f"Failed to check git status in {source_root}: {status_proc.stderr.strip()}"
        )
    if status_proc.stdout != "":
        raise ValueError(
            f"Vendor git working tree is not clean in {source_root}: {status_proc.stdout.strip()!r}"
        )

    tree_spec = f"{expected_commit}^{{tree}}"
    ls_tree_proc = subprocess.run(
        ["git", "-C", str(source_root), "ls-tree", "-r", "-z", tree_spec],
        capture_output=True,
        text=False,
        env=env,
        check=False,
    )
    if ls_tree_proc.returncode != 0:
        raise ValueError(
            f"Failed to enumerate commit tree {tree_spec} in {source_root}: "
            f"{ls_tree_proc.stderr.decode('utf-8', errors='replace').strip()}"
        )

    raw_entries = [entry for entry in ls_tree_proc.stdout.split(b"\x00") if entry]
    if not raw_entries:
        raise ValueError(f"No tracked files found in commit tree {tree_spec} for {source_root}")

    unsorted_entries: dict[str, CommitTreeEntry] = {}
    for raw_entry in raw_entries:
        entry_text = raw_entry.decode("utf-8")
        if "\t" not in entry_text:
            raise ValueError(
                f"Malformed git ls-tree entry in {source_root}: {entry_text!r}"
            )
        header_part, rel_path = entry_text.split("\t", 1)
        header_fields = header_part.split(" ")
        if len(header_fields) != 3:
            raise ValueError(
                f"Malformed git ls-tree header in {source_root}: {header_part!r}"
            )
        mode, obj_type, blob_id = header_fields
        if not rel_path:
            raise ValueError(f"Empty path in git ls-tree output for {source_root}")
        if rel_path in unsorted_entries:
            raise ValueError(
                f"Duplicate path {rel_path!r} in git ls-tree output for {source_root}"
            )
        if obj_type != "blob" or mode not in ALLOWED_GIT_BLOB_MODES:
            raise ValueError(
                f"Unsupported git tree entry in {source_root} for {rel_path!r}: "
                f"mode={mode!r}, type={obj_type!r} (only regular file blobs 100644/100755 are allowed)"
            )
        if len(blob_id) != 40 or any(c not in "0123456789abcdef" for c in blob_id):
            raise ValueError(
                f"Invalid git blob SHA-1 {blob_id!r} for {rel_path!r} in {source_root}"
            )
        unsorted_entries[rel_path] = CommitTreeEntry(
            rel_path=rel_path,
            mode=mode,
            obj_type=obj_type,
            blob_id=blob_id,
        )

    commit_tree_entries = {
        rel_path: unsorted_entries[rel_path]
        for rel_path in sorted(unsorted_entries)
    }

    git_metadata = {
        "verified_via_git": True,
        "verification_status": "verified_upstream_commit_tree",
        "upstream_commit": actual_commit,
        "upstream_tag": expected_tag,
        "tag_commit": tag_commit,
        "working_tree_clean": True,
        "commit_tree_spec": tree_spec,
        "all_tracked_blobs_verified": True,
        "tracked_file_count": len(commit_tree_entries),
    }
    return git_metadata, commit_tree_entries


def _make_source_walk_onerror(
    source_root: Path, scan_context: str
) -> Callable[[OSError], None]:
    """Return an os.walk onerror callback that raises a contextual ValueError."""

    def _onerror(exc: OSError) -> None:
        failed_path = getattr(exc, "filename", None) or str(source_root)
        raise ValueError(
            f"Source directory traversal failed during {scan_context} "
            f"under {source_root} at {failed_path}: {exc}"
        ) from exc

    return _onerror


def _verify_no_unexpected_working_tree_entries(
    source_root: Path, expected_rel_paths: set[str]
) -> None:
    """Verify source_root has no symlinks, forbidden build dirs, or extra files outside .git."""
    discovered_paths: set[str] = set()
    walk_onerror = _make_source_walk_onerror(
        source_root, "verified extra-file inventory"
    )
    for root, dirs, files in os.walk(
        source_root, topdown=True, onerror=walk_onerror, followlinks=False
    ):
        root_path = Path(root)
        for d_name in list(dirs):
            d_path = root_path / d_name
            d_info = os.lstat(d_path)
            if stat.S_ISLNK(d_info.st_mode):
                raise ValueError(f"Symlink directory rejected in source tree: {d_path}")
            if d_name == ".git" and root_path == source_root:
                dirs.remove(d_name)
                continue
            if d_name in FORBIDDEN_DIR_NAMES:
                raise ValueError(
                    f"Forbidden directory {d_name!r} present in source tree: {d_path}"
                )
        for f_name in files:
            f_path = root_path / f_name
            f_info = os.lstat(f_path)
            if stat.S_ISLNK(f_info.st_mode):
                raise ValueError(f"Symlink file rejected in source tree: {f_path}")
            if not stat.S_ISREG(f_info.st_mode):
                raise ValueError(f"Non-regular file rejected in source tree: {f_path}")
            rel = f_path.relative_to(source_root).as_posix()
            discovered_paths.add(rel)

    extra_paths = sorted(discovered_paths - expected_rel_paths)
    if extra_paths:
        raise ValueError(
            f"Unexpected untracked or ignored files in source tree: {extra_paths}"
        )


def _discover_regular_source_files_without_git(source_root: Path) -> list[str]:
    """Enumerate regular files in a synthetic test tree while rejecting .git/build/symlinks."""
    rel_paths: list[str] = []
    walk_onerror = _make_source_walk_onerror(
        source_root, "unverified synthetic source inventory"
    )
    for root, dirs, files in os.walk(
        source_root, topdown=True, onerror=walk_onerror, followlinks=False
    ):
        root_path = Path(root)
        for d_name in list(dirs):
            d_path = root_path / d_name
            d_info = os.lstat(d_path)
            if stat.S_ISLNK(d_info.st_mode):
                raise ValueError(f"Symlink directory rejected in source tree: {d_path}")
            if d_name in FORBIDDEN_DIR_NAMES:
                raise ValueError(
                    f"Forbidden directory {d_name!r} present in unverified source tree: {d_path}"
                )
        for f_name in files:
            f_path = root_path / f_name
            f_info = os.lstat(f_path)
            if stat.S_ISLNK(f_info.st_mode):
                raise ValueError(f"Symlink file rejected in source tree: {f_path}")
            if not stat.S_ISREG(f_info.st_mode):
                raise ValueError(f"Non-regular file rejected in source tree: {f_path}")
            rel = f_path.relative_to(source_root).as_posix()
            rel_paths.append(rel)
    rel_paths.sort()
    if not rel_paths:
        raise ValueError(f"No source files found in {source_root}")
    return rel_paths


def collect_and_verify_source_inventory(
    source_root: Path,
    tracked_rel_paths: Sequence[str],
    *,
    pinned_hashes: Mapping[str, str] = PINNED_ORIGINAL_FILE_SHA256,
    commit_tree_entries: Mapping[str, CommitTreeEntry] | None = None,
    require_commit_blobs: bool = False,
) -> tuple[dict[str, bytes], list[dict[str, Any]]]:
    """Read all tracked regular source files once and verify commit-blob SHA-1s and pinned SHA-256s."""
    if require_commit_blobs and commit_tree_entries is None:
        raise ValueError(
            "commit_tree_entries is required when require_commit_blobs=True"
        )

    rel_set = set(tracked_rel_paths)
    if len(rel_set) != len(tracked_rel_paths):
        raise ValueError("Duplicate paths in tracked_rel_paths inventory")

    if commit_tree_entries is not None and set(commit_tree_entries) != rel_set:
        raise ValueError(
            "Tracked path set does not match commit_tree_entries path set"
        )

    missing_pins = sorted(set(pinned_hashes) - rel_set)
    if missing_pins:
        raise ValueError(f"Pinned source files missing from inventory: {missing_pins}")

    for rel_path in sorted(tracked_rel_paths):
        rel_obj = Path(rel_path)
        if rel_obj.is_absolute() or ".." in rel_obj.parts:
            raise ValueError(f"Invalid relative path in source inventory: {rel_path!r}")
        if any(part in FORBIDDEN_DIR_NAMES for part in rel_obj.parts):
            raise ValueError(f"Forbidden path component in tracked source inventory: {rel_path!r}")

    _verify_no_unexpected_working_tree_entries(source_root, rel_set)

    source_bytes_by_rel: dict[str, bytes] = {}
    inventory_records: list[dict[str, Any]] = []

    for rel_path in sorted(tracked_rel_paths):
        rel_obj = Path(rel_path)
        full_path = _reject_symlink_chain(source_root / rel_obj, allow_missing_leaf=False)
        raw, size_bytes, digest = _regular_file_bytes_and_sha256(full_path)
        actual_blob_id = compute_git_blob_sha1(raw)

        git_mode: str | None = None
        if commit_tree_entries is not None:
            tree_entry = commit_tree_entries[rel_path]
            if (
                tree_entry.obj_type != "blob"
                or tree_entry.mode not in ALLOWED_GIT_BLOB_MODES
            ):
                raise ValueError(
                    f"Unsupported git tree entry for {rel_path!r}: "
                    f"mode={tree_entry.mode!r}, type={tree_entry.obj_type!r}"
                )
            if actual_blob_id != tree_entry.blob_id:
                raise ValueError(
                    f"Pinned commit blob mismatch for {rel_path}: "
                    f"expected {tree_entry.blob_id}, got {actual_blob_id}"
                )
            git_mode = tree_entry.mode

        if rel_path in pinned_hashes:
            expected_digest = pinned_hashes[rel_path]
            if digest != expected_digest:
                raise ValueError(
                    f"Pinned source SHA-256 mismatch for {rel_path}: "
                    f"expected {expected_digest}, got {digest}"
                )

        source_bytes_by_rel[rel_path] = raw
        inventory_records.append(
            {
                "path": rel_path,
                "size_bytes": size_bytes,
                "sha256": digest,
                "git_blob_id": actual_blob_id,
                "git_mode": git_mode,
                "commit_blob_verified": commit_tree_entries is not None,
                "is_pinned_target": rel_path in pinned_hashes,
            }
        )

    return source_bytes_by_rel, inventory_records


def _find_context_matches(
    lines: Sequence[str], spec: HookInsertionSpec
) -> list[int]:
    """Return all 1-based line indices matching spec.anchor_text and surrounding context."""
    matches: list[int] = []
    n_lines = len(lines)
    before_len = len(spec.context_before)
    after_len = len(spec.context_after)

    for idx0 in range(n_lines):
        if lines[idx0] != spec.anchor_text:
            continue
        if idx0 < before_len or idx0 + 1 + after_len > n_lines:
            continue
        if tuple(lines[idx0 - before_len : idx0]) != spec.context_before:
            continue
        if tuple(lines[idx0 + 1 : idx0 + 1 + after_len]) != spec.context_after:
            continue
        matches.append(idx0 + 1)
    return matches


def verify_original_is_ordered_subsequence(
    original_lines: Sequence[str],
    patched_lines: Sequence[str],
    expected_added_count: int,
) -> None:
    """Verify original_lines is an exact ordered subsequence of patched_lines."""
    if len(patched_lines) - len(original_lines) != expected_added_count:
        raise ValueError(
            f"Line count delta {len(patched_lines) - len(original_lines)} "
            f"does not equal expected inserted line count {expected_added_count}"
        )
    orig_idx = 0
    orig_len = len(original_lines)
    for line in patched_lines:
        if orig_idx < orig_len and line == original_lines[orig_idx]:
            orig_idx += 1
    if orig_idx != orig_len:
        raise ValueError(
            f"Original scientific lines are not an unchanged ordered subsequence "
            f"(matched {orig_idx} of {orig_len} lines)"
        )


def apply_hook_insertions_to_lines(
    rel_path: str,
    original_lines: Sequence[str],
    specs: Sequence[HookInsertionSpec],
) -> tuple[list[str], list[dict[str, Any]]]:
    """Validate exact line/context anchors and insert hook lines without altering original lines."""
    file_specs = [spec for spec in specs if spec.rel_path == rel_path]
    if not file_specs:
        return list(original_lines), []

    is_fixed_form = rel_path.endswith(".f")
    n_lines = len(original_lines)

    seen_hook_ids: set[str] = set()
    before_by_line: dict[int, list[HookInsertionSpec]] = {}
    after_by_line: dict[int, list[HookInsertionSpec]] = {}

    for spec in file_specs:
        if spec.source_hook_id in seen_hook_ids:
            raise ValueError(f"Duplicate source_hook_id {spec.source_hook_id!r} in {rel_path}")
        seen_hook_ids.add(spec.source_hook_id)

        if spec.phase not in ("before", "after"):
            raise ValueError(
                f"Invalid phase {spec.phase!r} for hook {spec.source_hook_id!r}"
            )
        if spec.original_line < 1 or spec.original_line > n_lines:
            raise ValueError(
                f"Anchor line {spec.original_line} out of range (1..{n_lines}) "
                f"for hook {spec.source_hook_id!r} in {rel_path}"
            )

        context_matches = _find_context_matches(original_lines, spec)
        if not context_matches:
            raise ValueError(
                f"Missing anchor for hook {spec.source_hook_id!r} in {rel_path} "
                f"at original line {spec.original_line}"
            )
        if len(context_matches) > 1:
            raise ValueError(
                f"Duplicate anchor matches {context_matches} for hook "
                f"{spec.source_hook_id!r} in {rel_path}"
            )
        if context_matches[0] != spec.original_line:
            raise ValueError(
                f"Anchor for hook {spec.source_hook_id!r} in {rel_path} matched at "
                f"line {context_matches[0]}, expected exact original line {spec.original_line}"
            )
        if original_lines[spec.original_line - 1] != spec.anchor_text:
            raise ValueError(
                f"Exact line mismatch at {rel_path}:{spec.original_line} for "
                f"{spec.source_hook_id!r}"
            )

        if is_fixed_form:
            for ins_line in spec.inserted_lines:
                if len(ins_line) > 72:
                    raise ValueError(
                        f"Fixed-form Fortran line exceeds 72 columns ({len(ins_line)}) "
                        f"in hook {spec.source_hook_id!r}: {ins_line!r}"
                    )

        if spec.phase == "before":
            before_by_line.setdefault(spec.original_line, []).append(spec)
        else:
            after_by_line.setdefault(spec.original_line, []).append(spec)

    patched_lines: list[str] = []
    hook_records: list[dict[str, Any]] = []
    total_inserted = 0

    for line_num in range(1, n_lines + 1):
        for spec in before_by_line.get(line_num, ()):
            start_line = len(patched_lines) + 1
            patched_lines.extend(spec.inserted_lines)
            end_line = len(patched_lines)
            total_inserted += len(spec.inserted_lines)
            hook_records.append(
                {
                    "source_hook_id": spec.source_hook_id,
                    "namespace": spec.namespace,
                    "file": spec.rel_path,
                    "original_line": spec.original_line,
                    "phase": spec.phase,
                    "anchor_text": spec.anchor_text,
                    "patched_start_line": start_line,
                    "patched_end_line": end_line,
                    "inserted_line_count": len(spec.inserted_lines),
                    "description": spec.description,
                }
            )

        patched_lines.append(original_lines[line_num - 1])

        for spec in after_by_line.get(line_num, ()):
            start_line = len(patched_lines) + 1
            patched_lines.extend(spec.inserted_lines)
            end_line = len(patched_lines)
            total_inserted += len(spec.inserted_lines)
            hook_records.append(
                {
                    "source_hook_id": spec.source_hook_id,
                    "namespace": spec.namespace,
                    "file": spec.rel_path,
                    "original_line": spec.original_line,
                    "phase": spec.phase,
                    "anchor_text": spec.anchor_text,
                    "patched_start_line": start_line,
                    "patched_end_line": end_line,
                    "inserted_line_count": len(spec.inserted_lines),
                    "description": spec.description,
                }
            )

    verify_original_is_ordered_subsequence(
        original_lines, patched_lines, total_inserted
    )
    return patched_lines, hook_records


def _verify_cmake_changes_confined_to_refmac5(
    original_cmake_text: str, patched_cmake_text: str
) -> None:
    """Verify CMakeLists.txt changes only add trace_writer.f90 and trace_hooks.f90 to refmac5."""
    orig_lines = original_cmake_text.splitlines()
    patched_lines = patched_cmake_text.splitlines()
    verify_original_is_ordered_subsequence(orig_lines, patched_lines, 2)

    refmac_idx = patched_lines.index("add_executable(refmac5")
    libcheck_idx = patched_lines.index("add_executable(libcheck")
    header_idx = patched_lines.index("add_executable(header2matr header2matr.f90)")

    if patched_lines[refmac_idx + 1 : refmac_idx + 3] != [
        "trace_writer.f90",
        "trace_hooks.f90",
    ]:
        raise ValueError(
            "trace_writer.f90 and trace_hooks.f90 must be added immediately inside add_executable(refmac5 ...)"
        )

    after_libcheck = "\n".join(patched_lines[libcheck_idx:])
    if "trace_writer.f90" in after_libcheck or "trace_hooks.f90" in after_libcheck:
        raise ValueError(
            "Diagnostic modules must not be added to libcheck or header2matr targets"
        )
    if header_idx <= libcheck_idx:
        raise ValueError("Unexpected target ordering in CMakeLists.txt")


def prepare_refmac_diagnostic_source(
    source_dir: Path | str,
    output_dir: Path | str,
    *,
    verify_git: bool = True,
    pinned_hashes: Mapping[str, str] = PINNED_ORIGINAL_FILE_SHA256,
    hook_specs: Sequence[HookInsertionSpec] = HOOK_INSERTION_SPECS,
    trace_writer_path: Path = TRACE_WRITER_SOURCE,
    trace_hooks_path: Path = TRACE_HOOKS_SOURCE,
    _allowed_output_roots: Sequence[Path] | None = None,
) -> dict[str, Any]:
    """Verify upstream REFMAC source, prepare patched diagnostic tree, and write manifest/patch."""
    source_root, output_root = _validate_source_and_output_paths(
        source_dir,
        output_dir,
        allowed_output_roots=_allowed_output_roots,
    )

    writer_bytes, writer_size, writer_sha256 = _regular_file_bytes_and_sha256(
        _reject_symlink_chain(trace_writer_path, allow_missing_leaf=False)
    )
    hooks_bytes, hooks_size, hooks_sha256 = _regular_file_bytes_and_sha256(
        _reject_symlink_chain(trace_hooks_path, allow_missing_leaf=False)
    )

    commit_tree_entries: Mapping[str, CommitTreeEntry] | None
    if verify_git:
        git_metadata, commit_tree_entries = verify_vendor_git_checkout(source_root)
        tracked_rel_paths = list(commit_tree_entries)
    else:
        commit_tree_entries = None
        tracked_rel_paths = _discover_regular_source_files_without_git(source_root)
        git_metadata = {
            "verified_via_git": False,
            "verification_status": "unverified_synthetic_source",
            "upstream_commit": None,
            "upstream_tag": None,
            "tag_commit": None,
            "working_tree_clean": None,
            "commit_tree_spec": None,
            "all_tracked_blobs_verified": False,
            "tracked_file_count": len(tracked_rel_paths),
        }

    for extra_name in (
        "trace_writer.f90",
        "trace_hooks.f90",
        PATCH_FILENAME,
        MANIFEST_FILENAME,
    ):
        if extra_name in tracked_rel_paths:
            raise ValueError(
                f"Generated filename {extra_name!r} collides with tracked source file"
            )

    source_bytes_by_rel, source_inventory = collect_and_verify_source_inventory(
        source_root,
        tracked_rel_paths,
        pinned_hashes=pinned_hashes,
        commit_tree_entries=commit_tree_entries,
        require_commit_blobs=verify_git,
    )

    spec_files = sorted({spec.rel_path for spec in hook_specs})
    for rel_path in spec_files:
        if rel_path not in source_bytes_by_rel:
            raise ValueError(f"Hook target file {rel_path!r} missing from source inventory")

    # Prepare all patched content and unified diffs in memory before creating output_root
    patched_bytes_by_rel: dict[str, bytes] = dict(source_bytes_by_rel)
    modified_files_manifest: list[dict[str, Any]] = []
    all_hook_bindings: list[dict[str, Any]] = []
    unified_diff_chunks: list[str] = []

    for rel_path in sorted(pinned_hashes):
        orig_bytes = source_bytes_by_rel[rel_path]
        orig_sha256 = _sha256_bytes(orig_bytes)
        orig_text = orig_bytes.decode("utf-8")
        if "\r" in orig_text:
            raise ValueError(f"CR line endings not supported in pinned file {rel_path}")
        orig_lines = orig_text.split("\n")
        has_trailing_newline = orig_text.endswith("\n")
        if has_trailing_newline:
            orig_lines = orig_lines[:-1]

        patched_lines, file_hook_records = apply_hook_insertions_to_lines(
            rel_path, orig_lines, hook_specs
        )
        patched_text = "\n".join(patched_lines) + ("\n" if has_trailing_newline else "")

        if rel_path == "CMakeLists.txt":
            _verify_cmake_changes_confined_to_refmac5(orig_text, patched_text)

        patched_bytes = patched_text.encode("utf-8")
        patched_sha256 = _sha256_bytes(patched_bytes)
        patched_bytes_by_rel[rel_path] = patched_bytes
        all_hook_bindings.extend(file_hook_records)

        diff_lines = list(
            difflib.unified_diff(
                orig_text.splitlines(keepends=True),
                patched_text.splitlines(keepends=True),
                fromfile=f"a/{rel_path}",
                tofile=f"b/{rel_path}",
                n=3,
            )
        )
        unified_diff_chunks.append("".join(diff_lines))

        modified_files_manifest.append(
            {
                "path": rel_path,
                "before_sha256": orig_sha256,
                "before_size_bytes": len(orig_bytes),
                "after_sha256": patched_sha256,
                "after_size_bytes": len(patched_bytes),
                "original_line_count": len(orig_lines),
                "patched_line_count": len(patched_lines),
                "inserted_line_count": len(patched_lines) - len(orig_lines),
                "hook_ids": [rec["source_hook_id"] for rec in file_hook_records],
            }
        )

    patch_text = "".join(unified_diff_chunks)
    patch_bytes = patch_text.encode("utf-8")
    patch_sha256 = _sha256_bytes(patch_bytes)

    output_inventory: list[dict[str, Any]] = []
    for rel_path in sorted(patched_bytes_by_rel):
        data = patched_bytes_by_rel[rel_path]
        output_inventory.append(
            {
                "path": rel_path,
                "size_bytes": len(data),
                "sha256": _sha256_bytes(data),
                "modified": rel_path in pinned_hashes,
            }
        )

    manifest_payload: dict[str, Any] = {
        "schema_id": MANIFEST_SCHEMA_ID,
        "preparation_only": True,
        "native_execution_performed": False,
        "source_verification_status": (
            "verified_upstream_commit_tree"
            if verify_git
            else "unverified_synthetic_source"
        ),
        "upstream_source": {
            "expected_commit": UPSTREAM_GIT_COMMIT,
            "expected_tag": UPSTREAM_GIT_TAG,
            "git_verification": git_metadata,
            "pinned_original_file_sha256": dict(sorted(pinned_hashes.items())),
        },
        "diagnostic_modules": {
            "trace_writer.f90": {
                "destination_path": "trace_writer.f90",
                "size_bytes": writer_size,
                "sha256": writer_sha256,
                "fortran_module": "protstruct_diagnostic_trace",
            },
            "trace_hooks.f90": {
                "destination_path": "trace_hooks.f90",
                "size_bytes": hooks_size,
                "sha256": hooks_sha256,
                "fortran_module": "protstruct_diagnostic_hooks",
            },
        },
        "modified_vendor_files": modified_files_manifest,
        "hook_bindings": all_hook_bindings,
        "unified_patch": {
            "path": PATCH_FILENAME,
            "size_bytes": len(patch_bytes),
            "sha256": patch_sha256,
        },
        "source_inventory": source_inventory,
        "output_source_inventory": output_inventory,
    }
    manifest_bytes = (
        json.dumps(manifest_payload, indent=2, sort_keys=False) + "\n"
    ).encode("utf-8")

    # Materialize fresh output directory and write all files exclusively
    os.mkdir(output_root, 0o755)
    for rel_path, content in sorted(patched_bytes_by_rel.items()):
        dest_file = output_root / Path(rel_path)
        dest_file.parent.mkdir(parents=True, exist_ok=True)
        _write_new_regular_file(dest_file, content)

    _write_new_regular_file(output_root / "trace_writer.f90", writer_bytes)
    _write_new_regular_file(output_root / "trace_hooks.f90", hooks_bytes)
    _write_new_regular_file(output_root / PATCH_FILENAME, patch_bytes)
    _write_new_regular_file(output_root / MANIFEST_FILENAME, manifest_bytes)

    return manifest_payload


def _write_new_regular_file(path: Path, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags, 0o644)
    try:
        view = memoryview(data)
        written = 0
        while written < len(view):
            n = os.write(fd, view[written:])
            if n <= 0:
                raise OSError(f"Short write to {path}")
            written += n
        os.fsync(fd)
    finally:
        os.close(fd)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare instrumented REFMAC 5.8.0431 diagnostic source tree."
    )
    parser.add_argument(
        "--source",
        required=True,
        help="Read-only upstream REFMAC 5.8.0431 checkout directory.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Non-existing destination directory for prepared diagnostic source tree.",
    )
    return parser


def parse_cli_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = build_arg_parser()
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_cli_args(argv)
    prepare_refmac_diagnostic_source(
        Path(args.source),
        Path(args.output),
        verify_git=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
