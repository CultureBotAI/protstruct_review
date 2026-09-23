"""T13 non-cctbx data-quality oracle wrapper.

Drives CCP4 aimless first (canonical recommendation); when the input MTZ
is merged-only (no unmerged intensities), aimless aborts and we fall
back to ctruncate, which does work on merged amplitudes and is also
non_cctbx.

Parses Wilson B, L-test twin fraction, moments-based twin estimate,
anisotropy ΔB, tNCS flag, and ice-ring flags.
Prints a YAML fragment of EvaluationMeasurement rows ready to paste
into an existing EvaluationRun's `measurements:` section.
These single-oracle diagnostics are informational: the registry's T13
agreement rules require matched cross-tool measurements, which this wrapper
does not accept. Text flags are descriptive, never numeric verdicts.

Usage:
    python scripts/t13_data_quality.py <mtz> --eval-id <EVAL-id> \
        --columns 'F-obs,SIGF-obs' [--logdir <dir>]

Notes:
    - aimless requires unmerged intensities (M/ISYM column). On merged-F
      input it errors with "hkl_unmerge_list::prepare - EMPTY"; that
      branch is captured in the printed YAML as a noted limitation.
    - ctruncate outputs are persisted under <logdir> (default:
      adjacent to <mtz>) and cited by repository-relative evidence_refs. Use a
      new repository-local log directory for every invocation; retained
      evidence is never overwritten. External input MTZs require --logdir
      pointing inside the repository.
"""
from __future__ import annotations

import argparse
import hashlib
import math
import re
import shutil
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from toolchain import ccp4_environment, run_capture

REPO_ROOT = Path(__file__).resolve().parent.parent


def _repository_location(path: Path) -> tuple[Path, str]:
    """Resolve execution paths without admitting external or nonportable evidence."""
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(REPO_ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"retained evidence must be inside the repository: {path}") from exc
    if any(character in relative for character in "#\\:"):
        raise ValueError(f"retained evidence path is not portable: {path}")
    return resolved, relative


def _retained_log_ref(path_text: str | None) -> str:
    if not path_text:
        raise ValueError("measurement output requires a retained log")
    path = Path(path_text)
    resolved, relative = _repository_location(path if path.is_absolute() else REPO_ROOT / path)
    if not resolved.is_file():
        raise ValueError(f"retained evidence log is missing or not a file: {path_text}")
    return relative


def _run(cmd: list[str], stdin: str = "", env: dict | None = None,
         cwd: str | None = None, log_path: Path | None = None) -> tuple[int, str]:
    # Reserve the evidence path before running; an existing log must not be
    # replaced even when the caller bypasses main's fresh-directory check.
    if log_path is None:
        proc = run_capture(cmd, input_text=stdin, env=env, cwd=cwd)
        return proc.returncode, proc.stdout + proc.stderr
    with log_path.open("x") as handle:
        proc = run_capture(cmd, input_text=stdin, env=env, cwd=cwd)
        out = proc.stdout + proc.stderr
        handle.write(out)
    return proc.returncode, out


def _require_new_output(path: Path) -> None:
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to replace retained output: {path}")


def try_aimless(mtz: Path, logdir: Path) -> dict:
    """Run aimless against the input MTZ. Returns a dict with keys:
        status: "ran" | "failed" | "missing"
        reason: short explanation
        log: path to stored log
    """
    logdir, _relative = _repository_location(logdir)
    try:
        environment = ccp4_environment()
    except (OSError, RuntimeError) as exc:
        return {"status": "missing", "reason": str(exc), "log": None}
    executable = shutil.which("aimless", path=environment.get("PATH", ""))
    if not executable:
        return {"status": "missing",
                "reason": "aimless binary absent from configured CCP4 environment",
                "log": None}
    mtz, logdir = mtz.resolve(), logdir.resolve()
    executable = str(Path(executable).resolve())
    log = logdir / "aimless.log"
    out_mtz = logdir / "aimless_scaled.mtz"
    _require_new_output(out_mtz)
    rc, output = _run(
        [executable, "HKLIN", str(mtz), "HKLOUT", str(out_mtz)],
        stdin="END\n",
        env=environment,
        cwd=str(logdir),
        log_path=log,
    )
    if rc != 0:
        if "hkl_unmerge_list::prepare - EMPTY" in output:
            reason = "MTZ has merged amplitudes only; aimless requires unmerged intensities"
        else:
            reason = "aimless exited non-zero"
        return {"status": "failed", "reason": reason, "log": str(log)}
    return {"status": "ran", "reason": "ok", "log": str(log)}


def run_ctruncate(mtz: Path, columns: str, logdir: Path) -> dict:
    logdir, _relative = _repository_location(logdir)
    try:
        environment = ccp4_environment()
    except (OSError, RuntimeError) as exc:
        raise SystemExit(f"CCP4 setup unavailable: {exc}") from exc
    executable = shutil.which("ctruncate", path=environment.get("PATH", ""))
    if not executable:
        raise SystemExit("ctruncate absent from configured CCP4 environment")
    mtz, logdir = mtz.resolve(), logdir.resolve()
    executable = str(Path(executable).resolve())
    log = logdir / "ctruncate.log"
    out_mtz = logdir / "ctruncate_out.mtz"
    _require_new_output(out_mtz)
    rc, output = _run(
        [
            executable,
            "-hklin", str(mtz),
            "-hklout", str(out_mtz),
            "-colin", f"/*/*/[{columns}]",
        ],
        env=environment,
        cwd=str(logdir),
        log_path=log,
    )
    if rc != 0:
        raise SystemExit(f"ctruncate failed (rc={rc}); see {log}")
    return parse_ctruncate(output, str(log))


def _section_blocks(text: str, title: str) -> list[tuple[str, bool]]:
    """Return each named section and whether a following section bounds it.

    A header or unrelated later prose is not evidence of a table. Preserve
    separate repeated sections so one complete result cannot hide a truncated
    or contradictory result from a concatenated log.
    """
    headers = list(re.finditer(
        r"^[ \t]*(?:Twin fraction estimates by twinning operator|"
        r"[A-Z][A-Z0-9 /()_-]{3,}):?[ \t]*$", text, flags=re.MULTILINE,
    ))
    blocks = []
    for index, header in enumerate(headers):
        if header.group().strip().rstrip(":") != title:
            continue
        bounded = index + 1 < len(headers)
        end = headers[index + 1].start() if bounded else len(text)
        blocks.append((text[header.end():end], bounded))
    return blocks


def _explicit_flag(text: str, title: str, positive: str, negative: str) -> tuple[bool | None, str]:
    blocks = _section_blocks(text, title) or [(text, False)]
    results = []
    for block, _bounded in blocks:
        positive_seen = bool(re.search(positive, block, flags=re.MULTILINE | re.IGNORECASE))
        negative_seen = bool(re.search(negative, block, flags=re.MULTILINE | re.IGNORECASE))
        if positive_seen and negative_seen:
            return None, "conflicting explicit reports"
        if not (positive_seen or negative_seen):
            return None, "no recognized explicit report in a section"
        results.append(positive_seen)
    if len(set(results)) != 1:
        return None, "conflicting repeated sections"
    return results[0], "explicit report"


def _twin_operator_result(text: str) -> tuple[int | None, str]:
    blocks = _section_blocks(text, "Twin fraction estimates by twinning operator")
    if not blocks:
        return None, "operator section missing"
    # Recognize a Miller-index operator triplet followed by numeric estimates.
    # Unknown layouts remain unavailable, rather than becoming positive merely
    # because they do not contain the known negative sentence (#721).
    component = r"[+-]?(?:\d+)?[hkl](?:[+-](?:\d+)?[hkl])*"
    number = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
    table_row = re.compile(
        rf"^[ \t]*{component}[ \t]*,[ \t]*{component}[ \t]*,[ \t]*{component}"
        rf"(?:[ \t]+{number}){{2,}}[ \t]*$", re.MULTILINE,
    )
    results = []
    for block, _bounded in blocks:
        candidates = re.findall(r"^[ \t]*[+\-hkl][^\n]*,[^\n]*$", block, re.MULTILINE)
        if any(table_row.fullmatch(line) is None for line in candidates):
            return None, "unrecognized operator table row"
        negative = bool(re.search(r"^[ \t]*No operators found[ \t]*$", block, re.MULTILINE))
        positive = bool(table_row.search(block))
        if positive == negative:
            return None, "incomplete, unrecognized, or conflicting operator section"
        results.append(int(positive))
    if len(set(results)) != 1:
        return None, "conflicting repeated operator sections"
    return results[0], "recognized operator table" if results[0] else "explicit no-operator report"


def _ice_ring_result(text: str) -> tuple[list[tuple[float, str]] | None, str]:
    blocks = _section_blocks(text, "ICE RING SUMMARY")
    if not blocks:
        return None, "ice-ring section missing"
    results = []
    for block, bounded in blocks:
        header = re.search(r"^[ \t]*reso[ \t]+ice_ring[ \t]+[^\n]+$", block, re.MULTILINE)
        if not bounded or header is None:
            return None, "incomplete or unrecognized ice-ring section"
        rows: list[tuple[float, str]] = []
        for line in block[header.end():].splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.startswith("The ice rings table") or stripped.startswith("<"):
                break
            fields = stripped.split()
            if len(fields) != 9 or fields[1] not in {"yes", "no"}:
                return None, "malformed ice-ring table row"
            try:
                values = [float(fields[0]), *(float(value) for value in fields[2:])]
            except ValueError:
                return None, "malformed ice-ring table row"
            if not all(math.isfinite(value) for value in values) or values[0] <= 0:
                return None, "invalid numeric ice-ring table row"
            rows.append((values[0], fields[1]))
        if not rows or len({row[0] for row in rows}) != len(rows):
            return None, "empty or duplicate-resolution ice-ring table"
        results.append(sorted(rows))
    if any(rows != results[0] for rows in results[1:]):
        return None, "conflicting repeated ice-ring sections"
    return results[0], "recognized complete ice-ring table"


def parse_ctruncate(text: str, log_path: str) -> dict:
    """Pull the T13-relevant scalars out of ctruncate's stdout."""
    out = {"log": log_path}

    # Resolution range
    m = re.search(r"Resolution range of data:\s*([\d.]+)\s*-\s*([\d.]+)\s*A", text)
    if m:
        out["resolution_low_a"] = float(m.group(1))
        out["resolution_high_a"] = float(m.group(2))

    # Wilson B
    m = re.search(r"Estimate of Wilson B factor:\s*([-\d.]+)\s*A\^\(-2\)"
                  r"(?:,\s*with sigma\s*([\d.]+))?", text)
    if m:
        out["wilson_b"] = float(m.group(1))
        if m.group(2):
            out["wilson_b_sigma"] = float(m.group(2))

    # Anisotropy eigenvalues
    m = re.search(r"Eigenvalues:\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)", text)
    if m:
        eigs = [float(x) for x in m.groups()]
        out["aniso_eigenvalues"] = eigs
        out["delta_b_aniso"] = max(eigs) - min(eigs)
    aniso, explanation = _explicit_flag(
        text, "ANISOTROPY ANALYSIS", r"^[ \t]*Some anisotropy (?:detetect|detected)(?:\.|[ \t]*$)",
        r"^[ \t]*No (?:significant )?anisotropy detected(?:\.|[ \t]*$)",
    )
    out["aniso_flag"] = "unavailable" if aniso is None else "some" if aniso else "none_flagged"
    out["aniso_diagnostic"] = explanation

    # Twinning — L-test fraction
    m = re.search(r"Twin fraction estimate from L-test:\s*([\d.]+)", text)
    if m:
        out["twin_fraction_l"] = float(m.group(1))
    m = re.search(r"Twin fraction estimate from moments:\s*([\d.]+)", text)
    if m:
        out["twin_fraction_moments"] = float(m.group(1))
    m = re.search(r"L statistic\s*=\s*([\d.]+)", text)
    if m:
        out["l_statistic"] = float(m.group(1))
    out["twin_operators_found"], out["twin_operators_diagnostic"] = _twin_operator_result(text)

    # Moments of I
    m = re.search(r"<I\^2>/<I>\^2\s*=\s*([\d.]+)", text)
    if m:
        out["moment_2_acentric"] = float(m.group(1))

    # tNCS
    tncs_suffix = r"[ \t]*(?:\([^\n)]*\))?[ \t]*[.!]?[ \t]*$"
    out["tncs_flag"], out["tncs_diagnostic"] = _explicit_flag(
        text, "TRANSLATIONAL NCS", r"^[ \t]*Translational NCS detected" + tncs_suffix,
        r"^[ \t]*(?:No translational NCS detected|Translational NCS (?:was )?not detected)" + tncs_suffix,
    )

    ice_rows, explanation = _ice_ring_result(text)
    out["ice_ring_diagnostic"] = explanation
    if ice_rows is not None:
        out["ice_ring_resolutions_flagged"] = [r[0] for r in ice_rows if r[1] == "yes"]
        out["ice_ring_count_total"] = len(ice_rows)

    return out


# ---------------------------------------------------------------------------
# Render YAML fragment
# ---------------------------------------------------------------------------

@dataclass
class Measurement:
    """One EvaluationMeasurement row emitted by the T13 oracle.

    `suffix` is appended to `<eval_id>_M_t13_` to form the row id; `value`
    is written as `value_numeric` when `kind == "numeric"` and as
    `value_text` otherwise.
    """

    suffix: str
    metric_definition_ref: str
    value: Any
    kind: str = "numeric"
    unit: str | None = None
    notes: str | None = None
    oracle_tool_ref: str = "ctruncate"
    evidence_refs: list[str] = field(default_factory=list)
    scope_selector: str | None = None

    def to_row(self, eval_id: str, *, subject_ref: str,
               scope_selector: str) -> dict[str, Any]:
        """Render as a plain dict in the field order the EVAL YAML uses."""
        measure: dict[str, Any] = {}
        if self.kind == "numeric":
            if (isinstance(self.value, bool)
                    or not isinstance(self.value, (int, float))
                    or not math.isfinite(self.value)):
                raise ValueError(f"{self.suffix}: expected a finite numeric measurement")
            measure["value_numeric"] = self.value
        elif self.kind == "text" and isinstance(self.value, str) and self.value.strip():
            measure["value_text"] = self.value
        else:
            raise ValueError(f"{self.suffix}: expected a nonblank text measurement")
        if self.unit:
            measure["unit"] = self.unit

        row: dict[str, Any] = {
            "id": f"{eval_id}_M_t13_{self.suffix}",
            "catalog_task_ref": "T13",
            "stage": "all",
            "scope": "dataset",
            "scope_selector": self.scope_selector or scope_selector,
            "subject_ref": subject_ref,
            "metric_definition_ref": self.metric_definition_ref,
            "oracle_tool_ref": self.oracle_tool_ref,
            "oracle_family": "non_cctbx",
            "agent_claim": {"is_not_applicable": True},
            "oracle_measure": measure,
            "pass_status": "informational",
        }
        if self.evidence_refs:
            row["evidence_refs"] = self.evidence_refs
        if self.notes:
            row["notes"] = self.notes
        return row


def build_measurements(stats: dict, aimless: dict) -> list[Measurement]:
    """Select the measurement rows supported by what ctruncate reported."""
    measurements: list[Measurement] = []

    if "wilson_b" in stats:
        measurements.append(Measurement(
            suffix="wilson_b",
            metric_definition_ref="T13_wilson_b",
            value=stats["wilson_b"],
            unit="Å²",
            notes=(f"ctruncate Wilson scaling; "
                   f"sigma {stats.get('wilson_b_sigma', '?')}."),
        ))

    if "twin_fraction_l" in stats:
        operator_status = {0: "absent", 1: "present"}.get(
            stats.get("twin_operators_found"), "unavailable",
        )
        measurements.append(Measurement(
            suffix="twin_fraction_l",
            metric_definition_ref="T13_l-test_twinning",
            value=stats["twin_fraction_l"],
            unit="fraction",
            notes=(f"L-test-derived twin fraction, not the mean absolute L statistic. "
                   f"L statistic {stats.get('l_statistic')}; moments-based twin fraction "
                   f"{stats.get('twin_fraction_moments')}; "
                   f"twinning-operator presence: {operator_status} "
                   f"({stats.get('twin_operators_diagnostic', 'not reported')})."),
        ))

    if "delta_b_aniso" in stats:
        measurements.append(Measurement(
            suffix="delta_b_aniso",
            metric_definition_ref="T13_anisotropy_δb_aniso",
            value=stats["delta_b_aniso"],
            unit="Å²",
            notes=(f"ctruncate anisotropy eigenvalues "
                   f"{stats.get('aniso_eigenvalues')}; "
                   f"flag = {stats.get('aniso_flag', 'unavailable')} "
                   f"({stats.get('aniso_diagnostic', 'not reported')})."),
        ))

    if "tncs_flag" in stats:
        measurements.append(Measurement(
            suffix="tncs_flag",
            metric_definition_ref="T13_tncs_flag",
            value="unavailable" if stats["tncs_flag"] is None else str(stats["tncs_flag"]).lower(),
            kind="text",
            notes=("ctruncate Patterson-search flag; consult retained log for search settings. "
                   f"{stats.get('tncs_diagnostic', 'Explicit supplied flag')}."),
        ))
    if "ice_ring_resolutions_flagged" in stats:
        flagged = stats["ice_ring_resolutions_flagged"]
        measurements.append(Measurement(
            suffix="ice_ring_flags",
            metric_definition_ref="T13_ice-ring_flags",
            value=(",".join(f"{r:.2f}Å" for r in flagged) if flagged else "none"),
            kind="text",
            notes=(f"ctruncate ice-ring summary: "
                   f"{stats.get('ice_ring_count_total')} "
                   f"sensitive bins scanned; "
                   f"{len(flagged)} labelled yes by ctruncate. "
                   f"Flags are retained diagnostics, not a calibrated quality verdict."),
        ))
    elif "ice_ring_diagnostic" in stats:
        measurements.append(Measurement(
            suffix="ice_ring_flags",
            metric_definition_ref="T13_ice-ring_flags",
            value="unavailable",
            kind="text",
            notes=f"ctruncate ice-ring summary unavailable: {stats['ice_ring_diagnostic']}.",
        ))

    if measurements:
        evidence_ref = _retained_log_ref(stats.get("log"))
        for measurement in measurements:
            measurement.evidence_refs = [evidence_ref]

    if aimless["status"] == "missing":
        if aimless.get("log"):
            raise ValueError("missing aimless must not claim a retained execution log")
        aimless_evidence = []
    else:
        aimless_evidence = [_retained_log_ref(aimless.get("log"))]

    # Provenance row about the aimless attempt
    measurements.append(Measurement(
        suffix="aimless_attempt",
        metric_definition_ref="T13_aimless_status",
        value=aimless["status"],
        kind="text",
        oracle_tool_ref="CCP4 aimless",
        scope_selector="all input reflections",
        notes=aimless["reason"],
        evidence_refs=aimless_evidence,
    ))

    return measurements


def render_yaml(stats: dict, eval_id: str, aimless: dict, *,
                subject_ref: str, scope_selector: str) -> str:
    """Produce the snippet of measurement rows for the EVAL yaml."""
    if not subject_ref.strip() or not scope_selector.strip():
        raise ValueError("dataset subject and column selector must be explicit")
    rows = [m.to_row(eval_id, subject_ref=subject_ref, scope_selector=scope_selector)
            for m in build_measurements(stats, aimless)]
    body = yaml.safe_dump(
        rows,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        # Never fold long notes onto continuation lines: the fragment is
        # pasted into an EVAL file by hand and must stay one row per field.
        width=10 ** 9,
    )
    # Two-space lead-in so the block drops straight under `measurements:`.
    return textwrap.indent(body, "  ")


def main() -> int:
    p = argparse.ArgumentParser(
        description="Run aimless then ctruncate as the T13 non-cctbx oracle.")
    p.add_argument("mtz", type=Path, help="Input MTZ file.")
    p.add_argument("--eval-id", required=True,
                   help="EvaluationRun id whose measurement rows to emit "
                        "(e.g. EVAL_1sar_cdba2c07_2026-04-24).")
    p.add_argument("--columns", default="F-obs,SIGF-obs",
                   help="MTZ amplitude column pair (default: F-obs,SIGF-obs).")
    p.add_argument("--logdir", type=Path,
                   help="New repository-local directory for stdout / output MTZs "
                        "(default: <mtz parent>/t13_oracle_logs/).")
    args = p.parse_args()

    if not args.mtz.is_file():
        raise SystemExit(f"input MTZ not found: {args.mtz}")
    if not args.columns.strip():
        raise SystemExit("MTZ columns must be explicit")
    with args.mtz.open("rb") as handle:
        input_digest = hashlib.file_digest(handle, "sha256").hexdigest()
    logdir = args.logdir or (args.mtz.parent / "t13_oracle_logs")
    try:
        logdir, _relative = _repository_location(logdir)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    try:
        logdir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise SystemExit(f"use a new --logdir; refusing to overwrite {logdir}") from exc

    aimless = try_aimless(args.mtz, logdir)
    print(f"# aimless: {aimless['status']} ({aimless['reason']})", file=sys.stderr)
    if aimless["log"]:
        print(f"# aimless log: {aimless['log']}", file=sys.stderr)

    stats = run_ctruncate(args.mtz, args.columns, logdir)
    print(f"# ctruncate log: {stats['log']}", file=sys.stderr)
    print(f"# parsed: {stats}", file=sys.stderr)

    with args.mtz.open("rb") as handle:
        if hashlib.file_digest(handle, "sha256").hexdigest() != input_digest:
            raise SystemExit("input MTZ changed during execution; no measurements emitted")
    print(render_yaml(
        stats, args.eval_id, aimless, subject_ref=f"mtz:sha256:{input_digest}",
        scope_selector=f"/*/*/[{args.columns}]",
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
