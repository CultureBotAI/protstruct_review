"""Portable offline captured-word/HKL bin reconciliation for Attempt 04; no native math replay.

Reads only pinned repository-relative retained inputs under data/coscientists/openscientist
and writes verification JSON artifacts to a single new caller-supplied output directory
outside protected repository trees (data/, ref/, scripts/, schemas/, protstruct_review/, prompts/).
Source edges and J are observed fields; this never creates inferred/native bins or gates.
"""
from collections import Counter
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
W = HERE.parents[2].resolve()
R_REL = "data/coscientists/openscientist/retained_1sar_pr1007_R4_rfactors_attempt04"
A_REL = "data/coscientists/openscientist/retained_1sar_pr1007_R4_rfactors_attempt04_analysis/current"

PINS = {
    f"{R_REL}/refmac/refmac_native_trace.jsonl": "4dd312bf512d32cdf4095f1e3ee0c5471cb2ad91deb602b2c60d4f210216505d",
    f"{R_REL}/refmac/refmac.log": "28d3b231b242c24e2051500d870356ca5d4cdb7655d862cb25c66e018d6f21b2",
    f"{A_REL}/native_bin_bounds.json": "e339889022147a613a64dfbdd784a10e2c404c029a4dc2b84cb7bfee86da6be9",
    f"{A_REL}/residual_members.json": "8034bfc5a9ed2e64fd8c21298904263b6317260588341154d16ce65a2e7bcb82",
    f"{A_REL}/completeness_members.json": "ce1a6c17334a8fd114c37da0841baae0d5805ad17b8358ef972837f6d57c773f",
    f"{A_REL}/native_slot_records.json": "a01f979d0326f76e65776b0f7b43b82ced1feb6b387cd98910b3e5f5cec05efd",
    f"{A_REL}/completeness_slot_records.json": "76404a64df3cc9876794b7caf8acee66eab5eb3a29754fe47b50c90b0c9981ff",
}

PROTECTED_TREES = ("data", "ref", "scripts", "schemas", "protstruct_review", "prompts", ".git")


def guard(event, args):
    if event.startswith(("socket.", "subprocess.", "os.exec", "os.spawn", "os.posix_spawn", "os.fork")) or event == "os.system":
        raise RuntimeError("Prohibited operation: " + event)


sys.addaudithook(guard)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1048576), b""):
            h.update(block)
    return h.hexdigest()


def validate_new_output_dir(arg: str) -> Path:
    if not arg or not arg.strip():
        raise ValueError("Output directory argument must be non-empty")
    raw_path = Path(arg).expanduser()
    if raw_path.exists() or raw_path.is_symlink():
        raise FileExistsError(f"Refusing existing output path: {raw_path}")
    out = raw_path.resolve(strict=False)
    if out.exists() or out.is_symlink():
        raise FileExistsError(f"Refusing existing resolved output path: {out}")
    if out == W or out.parent == W or W.is_relative_to(out):
        raise ValueError(f"Refusing repository root, top-level repository path, or ancestor as output directory: {out}")
    for name in PROTECTED_TREES:
        protected = (W / name).resolve(strict=False)
        if out == protected or out.is_relative_to(protected) or protected.is_relative_to(out):
            raise ValueError(f"Refusing output path inside or overlapping protected tree {protected}: {out}")
    for rel in PINS:
        inp = (W / rel).resolve(strict=False)
        if out == inp or out.is_relative_to(inp) or inp.is_relative_to(out):
            raise ValueError(f"Refusing output path overlapping consumed input {inp}: {out}")
    if not out.parent.is_dir():
        raise FileNotFoundError(f"Output parent directory does not exist: {out.parent}")
    return out


def verify_pins() -> None:
    for rel, expected in PINS.items():
        path = W / rel
        actual = sha(path)
        if actual != expected:
            raise RuntimeError(f"SHA-256 mismatch for {rel}: expected {expected}, got {actual}")


def word(v):
    value = int(v["bits_hex"], 16)
    assert value < 0x7F800000, "Expected finite nonnegative captured resolution"
    return value


def positive(v):
    return Fraction(v["decimal"]) > 0


def ref(d):
    return {k: d[k] for k in ("namespace", "call_id", "sequence", "_line")}


def main() -> None:
    if len(sys.argv) != 2:
        raise ValueError("Usage: python replay_bins.py <new-output-directory>")
    out = validate_new_output_dir(sys.argv[1])
    verify_pins()
    out.mkdir(parents=False, exist_ok=False)

    R = W / R_REL
    A = W / A_REL
    checks = Counter()
    bad = []

    def check(name, ok, detail):
        checks[name] += 1
        if not ok:
            bad.append({"check": name, "detail": detail})

    starts, bounds, rows, slots = {}, {"residual_lsq": {}, "reporting_completeness": {}}, {}, {}
    events = Counter()
    with (R / "refmac/refmac_native_trace.jsonl").open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            d = json.loads(line)
            ev = d.get("event")
            events[ev or d["record_type"]] += 1
            if ev is None or d.get("namespace") not in bounds:
                continue
            d["_line"] = line_no
            ns, call = d["namespace"], d["call_id"]
            key = (ns, call)
            if ev in {"completeness_begin", "lsq_coef_begin"}:
                assert key not in starts
                starts[key] = d
            elif ev in {"completeness_bin_bounds", "lsq_coef_bin_bounds"}:
                slot = (call, d["slot_index"])
                assert slot not in bounds[ns]
                bounds[ns][slot] = d
            elif ev in {"completeness_row_input", "lsq_row_input"}:
                rk = key + (d["row_index"],)
                assert rk not in rows
                cols = ("H", "K", "L") if ns == "residual_lsq" else ("asu_H", "asu_K", "asu_L")
                rows[rk] = {"input": d, "hkl": tuple(d[c] for c in cols), "shells": []}
            elif ev in {"completeness_shell_increment", "lsq_shell_match_before"}:
                rows[key + (d["row_index"],)]["shells"].append(d)
            elif ev in {"completeness_row_terminal", "lsq_row_terminal"}:
                row = rows[key + (d["row_index"],)]
                assert "terminal" not in row
                row["terminal"] = d
            elif ev in {"completeness_summary_slot", "lsq_raw_accumulator_slot"}:
                sk = key + (d.get("IFREE", 0), d["slot_index"])
                assert sk not in slots
                slots[sk] = d

    assert set(starts) == {("residual_lsq", 1), ("reporting_completeness", 1)}
    for ns in bounds:
        assert set(bounds[ns]) == {(1, j) for j in range(1, 22)}
        expected_rows = starts[ns, 1]["NREF" if ns == "residual_lsq" else "NASYM"]
        assert {i for (n, c, i) in rows if n == ns and c == 1} == set(range(1, expected_rows + 1))
    for item in json.loads((A / "native_bin_bounds.json").read_text(encoding="utf-8")):
        d = item["record"]
        raw = bounds["residual_lsq"][d["call_id"], d["slot_index"]]
        check(
            "retained_bound_matches_raw",
            d == {k: v for k, v in raw.items() if k != "_line"} and item["line"] == raw["_line"],
            d["slot_index"],
        )
    joined_bounds = []
    for j in range(1, 22):
        c = bounds["reporting_completeness"][1, j]
        r = bounds["residual_lsq"][1, j]
        check("bounds_same_words", all(word(c[k]) == word(r[k]) for k in ("SMINB", "SMAXB")), j)
        joined_bounds.append(
            {"J": j, "SMINB": r["SMINB"], "SMAXB": r["SMAXB"], "completeness_record": ref(c), "residual_record": ref(r)}
        )
        if j < 20:
            check("adjacent_shared_endpoint", word(r["SMAXB"]) == word(bounds["residual_lsq"][1, j + 1]["SMINB"]), j)

    touches, multiple, no_match, crosswalk = [], [], [], []
    by_hkl = {"residual_lsq": {}, "reporting_completeness": {}}
    counts = Counter()
    for (ns, call, i), row in rows.items():
        d, t = row["input"], row["terminal"]
        assert row["hkl"] not in by_hkl[ns], (ns, row["hkl"])
        by_hkl[ns][row["hkl"]] = row
        rho = word(d["RHO"])
        exact_matches = [
            j for j in range(1, 21) if word(bounds[ns][call, j]["SMINB"]) <= rho <= word(bounds[ns][call, j]["SMAXB"])
        ]
        actual_matches = [s["J"] for s in row["shells"]]
        expect = exact_matches[:1] if ns == "residual_lsq" else exact_matches
        check(
            "captured_J_matches_source_comparison",
            actual_matches == expect,
            {"record": ref(d), "expected": expect, "actual": actual_matches},
        )
        for s in row["shells"]:
            b = bounds[ns][call, s["J"]]
            check(
                "shell_hook_bound_words",
                word(s["SMINB_J"]) == word(b["SMINB"]) and word(s["SMAXB_J"]) == word(b["SMAXB"]),
                ref(s),
            )
        endpoints = [
            {"J": j, "side": side}
            for j in range(1, 21)
            for side in ("SMINB", "SMAXB")
            if rho == word(bounds[ns][call, j][side])
        ]
        descriptor = {
            "record": ref(d),
            "row_index": i,
            "hkl": row["hkl"],
            "RHO": d["RHO"],
            "comparisons_matching": exact_matches,
            "actual_J": actual_matches,
        }
        if endpoints:
            touches.append({**descriptor, "endpoints": endpoints})
        if len(exact_matches) > 1:
            multiple.append(descriptor)
        if not exact_matches:
            no_match.append(descriptor)
        if ns == "residual_lsq":
            included = t["overall_added"]
            check(
                "residual_sigma_and_first_match",
                included == (positive(d["SO"]) and bool(exact_matches))
                and t["shell_added"] == included
                and t["matched_bin_index"] == (expect[0] if expect else 0),
                ref(t),
            )
        else:
            included = d["completeness_observed_code"] > 0
            check(
                "completeness_terminal",
                t["matched_shell_count"] == len(actual_matches)
                and t["overall_incremented"]
                and t["observed_incremented"] == included,
                ref(t),
            )
        row["included"] = included
        row["actual_J"] = actual_matches
        counts[ns, d["IFREE"], included, 21] += 1
        for j in actual_matches:
            counts[ns, d["IFREE"], included, j] += 1

    for ns in by_hkl:
        for j in range(1, 22):
            for part in (1, 2):
                if ns == "residual_lsq":
                    slot = slots[ns, 1, part, j]
                    check("residual_slot_population", counts[ns, part, True, j] == slot["nrefa_this"], ref(slot))
                else:
                    slot = slots[ns, 1, 0, j]
                    suffix = "work" if part == 1 else "free"
                    check(
                        "completeness_slot_population",
                        counts[ns, part, True, j] == slot["NREFA_" + suffix]
                        and counts[ns, part, False, j] == slot["NREFM_" + suffix],
                        ref(slot),
                    )

    for hkl in sorted(set(by_hkl["residual_lsq"]) | set(by_hkl["reporting_completeness"])):
        r, c = (by_hkl[ns].get(hkl) for ns in ("residual_lsq", "reporting_completeness"))
        entry = {"hkl": hkl}
        for label, row in (("residual", r), ("completeness", c)):
            entry[label] = (
                None
                if row is None
                else {
                    "input_record": ref(row["input"]),
                    "terminal_record": ref(row["terminal"]),
                    "row_index": row["input"]["row_index"],
                    "IFREE": row["input"]["IFREE"],
                    "included": row["included"],
                    "J": row["actual_J"],
                    "RHO": row["input"]["RHO"],
                }
            )
        if r and r["included"]:
            check(
                "active_residual_to_observed_exact_HKL_J",
                c is not None
                and c["included"]
                and r["actual_J"] == c["actual_J"]
                and r["input"]["IFREE"] == c["input"]["IFREE"],
                entry,
            )
        if c and c["included"]:
            check(
                "observed_to_active_residual_exact_HKL_J",
                r is not None
                and r["included"]
                and r["actual_J"] == c["actual_J"]
                and r["input"]["IFREE"] == c["input"]["IFREE"],
                entry,
            )
        crosswalk.append(entry)

    for name, ns in (("residual_members.json", "residual_lsq"), ("completeness_members.json", "reporting_completeness")):
        old = json.loads((A / name).read_text(encoding="utf-8"))
        check("retained_array_length", len(old) == len(by_hkl[ns]), name)
        for member in old:
            row = rows[ns, member["call_id"], member["row_index"]]
            expected_j = (
                [member["matched_bin_index"]]
                if ns == "residual_lsq" and member["matched_bin_index"]
                else member.get("matched_bins", [])
            )
            included = member["overall_added"] if ns == "residual_lsq" else member["observed_code"] > 0
            check(
                "retained_member_matches_raw",
                tuple(member["hkl"]) == row["hkl"]
                and member["IFREE"] == row["input"]["IFREE"]
                and expected_j == row["actual_J"]
                and included == row["included"],
                {"array": name, "row_index": member["row_index"]},
            )

    log_lines = (R / "refmac/refmac.log").read_text(encoding="utf-8").splitlines()
    log_table = []
    for j, line_no in enumerate(range(1117, 1137), 1):
        parts = log_lines[line_no - 1].split()
        assert len(parts) == 12
        slot = slots["reporting_completeness", 1, 0, j]
        check(
            "printed_count_matches_completeness_slot",
            int(parts[1]) == slot["HNREF_SHELL_WORK"] and int(parts[7]) == slot["HNREF_SHELL_FREE"],
            {"J": j, "log_line": line_no},
        )
        log_table.append({"J": j, "log_line": line_no, "tokens": parts, "completeness_slot": ref(slot)})

    def dump(name: str, value) -> None:
        target = out / name
        with target.open("x", encoding="utf-8") as fh:
            fh.write(json.dumps(value, indent=2) + "\n")

    dump("cross_namespace_hkl_rows.json", crosswalk)
    dump("shared_bounds.json", joined_bounds)
    dump("endpoint_touches.json", touches)
    dump("multiple_inclusive_matches.json", multiple)
    dump("no_inclusive_matches.json", no_match)
    dump("log_table_diagnostic.json", log_table)
    dump("mismatches.json", bad)
    rho_differences = [
        x
        for x in crosswalk
        if x["residual"] and x["completeness"] and x["residual"]["RHO"]["bits_hex"] != x["completeness"]["RHO"]["bits_hex"]
    ]
    dump("cross_namespace_RHO_word_differences.json", rho_differences)

    raw_unchanged = all(sha(W / rel) == expected for rel, expected in PINS.items())
    if not raw_unchanged:
        raise RuntimeError("Consumed input SHA-256 changed during replay")

    summary = {
        "scope": "Captured-word comparisons and exact-HKL observed J join only; no native arithmetic rerun/equivalence or admission",
        "pins": dict(PINS),
        "recipe_sha256": sha(Path(__file__).resolve()),
        "event_counts": dict(events),
        "checks": dict(checks),
        "mismatch_count": len(bad),
        "counts": [
            {"namespace": ns, "IFREE": p, "included_or_observed": inc, "slot": j, "count": n}
            for (ns, p, inc, j), n in sorted(counts.items())
        ],
        "endpoint_touch_rows": len(touches),
        "multiple_match_rows": len(multiple),
        "no_match_rows": len(no_match),
        "cross_namespace_RHO_word_difference_count": len(rho_differences),
        "raw_inputs_unchanged": raw_unchanged,
        "native_bin_membership_proven": False,
        "scientific_admission": False,
        "batch_eligible": False,
        "limits": [
            "No native FP mode/evaluation equivalence claim.",
            "No direct print-site/cycle runtime memory read captured.",
            "No bin-generation runtime operands or BINT branch event captured.",
            "No external dataset/symmetry equivalence admitted by an exact HKL join.",
            "Printed count agreement is diagnostic only.",
        ],
    }
    dump("result.json", summary)
    print(
        json.dumps(
            {
                k: summary[k]
                for k in (
                    "mismatch_count",
                    "endpoint_touch_rows",
                    "multiple_match_rows",
                    "no_match_rows",
                    "cross_namespace_RHO_word_difference_count",
                    "raw_inputs_unchanged",
                    "native_bin_membership_proven",
                    "scientific_admission",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
