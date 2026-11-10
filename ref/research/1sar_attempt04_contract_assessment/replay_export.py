"""Portable offline residual/export representation-weighting replay for Attempt 04.

Uses only pinned repository-relative retained bytes under data/coscientists/openscientist.
No fitted scale, inferred bins, clipping, native tool, compilation, scientific admission,
or product writes. The source-derived EXPAN change of representation is evaluated in
Decimal precision 70 as a bounded diagnostic; it is NOT a native floating-point
emulation, an export-ancestry proof, or a direct runtime print-memory read.
Run with Python 3.12 and one new output JSON path outside protected repository trees.
"""
import collections
from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import struct
import sys

HERE = Path(__file__).resolve().parent
W = HERE.parents[2].resolve()
R_REL = "data/coscientists/openscientist/retained_1sar_pr1007_R4_rfactors_attempt04/refmac"
A_REL = "data/coscientists/openscientist/retained_1sar_pr1007_R4_rfactors_attempt04_analysis/current"

PINS = {
    f"{R_REL}/refmac_native_trace.jsonl": "4dd312bf512d32cdf4095f1e3ee0c5471cb2ad91deb602b2c60d4f210216505d",
    f"{R_REL}/refmac_hklout.mtz": "e21ce039b11e8b83c5deebfa3059fafeef7906cf1d10a1d3cf20b57f56b578e2",
    f"{R_REL}/refmac_hklout_raw_export.json": "a3eb72b40f029fe7f0219b63b58e53d29cf96525b3b21126134a0d6517a8aa22",
    f"{A_REL}/residual_members.json": "8034bfc5a9ed2e64fd8c21298904263b6317260588341154d16ce65a2e7bcb82",
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


def validate_new_output_json(arg: str) -> Path:
    if not arg or not arg.strip():
        raise ValueError("Output JSON path argument must be non-empty")
    raw_path = Path(arg).expanduser()
    if raw_path.exists() or raw_path.is_symlink():
        raise FileExistsError(f"Refusing existing output path: {raw_path}")
    out = raw_path.resolve(strict=False)
    if out.exists() or out.is_symlink():
        raise FileExistsError(f"Refusing existing resolved output path: {out}")
    if out == W or out.parent == W or W.is_relative_to(out):
        raise ValueError(f"Refusing repository root, top-level repository path, or ancestor as output path: {out}")
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


def wordfrac(word: str) -> Fraction:
    value = struct.unpack("!f", bytes.fromhex(word))[0]
    assert math.isfinite(value), word
    return Fraction(value)


def dec(fraction: Fraction) -> Decimal:
    return Decimal(fraction.numerator) / Decimal(fraction.denominator)


def tracefrac(record, key: str) -> Fraction:
    value = wordfrac(record[key]["bits_hex"])
    assert dec(value) == Decimal(record[key]["decimal"])
    return value


def main() -> None:
    if len(sys.argv) != 2:
        raise ValueError("Usage: python replay_export.py <new-output-json-path>")
    output = validate_new_output_json(sys.argv[1])
    verify_pins()

    R = W / R_REL
    A = W / A_REL
    members = json.loads((A / "residual_members.json").read_text(encoding="utf-8"))
    raw = json.loads((R / "refmac_hklout_raw_export.json").read_text(encoding="utf-8"))
    mtz = (R / "refmac_hklout.mtz").read_bytes()
    cols = raw["header_parse"]["columns"]
    by_hkl = {}
    # Validate every raw-export column word directly against retained MTZ.
    for row in raw["rows"]:
        key = tuple(row["hkl"])
        assert key not in by_hkl and row["is_integral_hkl"]
        for col in cols:
            index = col["column_index"]
            offset = raw["data_start_byte_offset"] + 4 * (len(cols) * row["row_index"] + index)
            actual = f"{struct.unpack_from('<I', mtz, offset)[0]:08x}"
            assert actual == row["column_words_hex"][col["column_key"]].lower()
        by_hkl[key] = row

    s0 = {}
    carriers = []
    event_counts = collections.Counter()
    with (R / "refmac_native_trace.jsonl").open(encoding="utf-8") as stream:
        for line, content in enumerate(stream, 1):
            record = json.loads(content)
            event_counts[record.get("event", "header")] += 1
            if record.get("event") == "sumsfs_ls_deriv_row":
                key = (record["call_id"], record["row_index"])
                assert key not in s0
                s0[key] = (line, record)
            if record.get("event") in ("lsq_final_carrier_work", "lsq_final_carrier_free"):
                key = "RFACTOR_WORK" if record["event"].endswith("work") else "RFACTOR_FREE"
                value = tracefrac(record, key)
                carriers.append(
                    {
                        "line": line,
                        "sequence": record["sequence"],
                        "event": record["event"],
                        "source_hook_id": record["source_hook_id"],
                        "bits_hex": record[key]["bits_hex"],
                        "exact_fraction": str(value),
                        "exact_decimal": str(dec(value)),
                        "F10_4_nearest": format(dec(value), "10.4f"),
                        "F10_3_nearest": format(dec(value), "10.3f"),
                    }
                )

    sums = {p: collections.defaultdict(Decimal) for p in (1, 2)}
    exact = {p: collections.defaultdict(Fraction) for p in (1, 2)}
    counts = collections.Counter()
    maxima = {}
    examples = []
    expan_words = set()
    for member in members:
        if not member["overall_added"]:
            counts["excluded_original_domain"] += 1
            continue
        p = member["IFREE"]
        counts[f"included_{p}"] += 1
        line, record = s0[(member["call_id"], member["row_index"])]
        assert [record[x] for x in ("H", "K", "L")] == member["hkl"]
        out = by_hkl[tuple(member["hkl"])]
        words = out["column_words_hex"]
        fo, fc = wordfrac(words["F-obs"]), wordfrac(words["FC_ALL_LS"])
        flag = wordfrac(words["R-free-flags"])
        assert flag == (1 if p == 2 else 0)
        yos, yc = tracefrac(record, "YOS"), tracefrac(record, "YC_ALL")
        expan = tracefrac(record, "EXPAN")
        dbulk = tracefrac(record, "DBULK")
        assert expan > 0 and dbulk == 1
        expan_words.add(record["EXPAN"]["bits_hex"])
        # Domain is the exact retained native membership (overall_added == True). No fp>0 admission.
        exact[p]["export_num"] += abs(fo - fc)
        exact[p]["export_den"] += fo
        exact[p]["captured_operand_num"] += abs(yos - yc)
        exact[p]["captured_operand_den"] += yos
        dfo, dfc, dyos, dyc, dexp = map(dec, (fo, fc, yos, yc, expan))
        sums[p]["source_normalized_num"] += abs(dyos - dyc) / dexp
        sums[p]["source_normalized_den"] += dyos / dexp
        sums[p]["export_reweighted_num"] += abs(dfo - dfc) * dexp
        sums[p]["export_reweighted_den"] += dfo * dexp
        differences = {
            "export_fo_minus_YOS_div_EXPAN": dfo - dyos / dexp,
            "export_fc_minus_YC_div_EXPAN": dfc - dyc / dexp,
        }
        for name, difference in differences.items():
            if name not in maxima or abs(difference) > Decimal(maxima[name]["absolute"]):
                maxima[name] = {
                    "absolute": str(abs(difference)),
                    "signed": str(difference),
                    "hkl": member["hkl"],
                    "native_row": member["row_index"],
                    "trace_line": line,
                    "trace_sequence": record["sequence"],
                    "export_row_index": out["row_index"],
                }
        if len(examples) < 5:
            examples.append(
                {
                    "hkl": member["hkl"],
                    "native_row": member["row_index"],
                    "trace_line": line,
                    "export_row_index": out["row_index"],
                    "EXPAN_word": record["EXPAN"]["bits_hex"],
                    "output_fo_word": words["F-obs"],
                    "output_fc_word": words["FC_ALL_LS"],
                    "differences": {k: str(v) for k, v in differences.items()},
                }
            )

    results = {}
    for p, name in ((1, "work"), (2, "free")):
        part_result = {}
        for family in ("export", "captured_operand"):
            numerator, denominator = exact[p][family + "_num"], exact[p][family + "_den"]
            assert denominator != 0
            ratio = numerator / denominator
            part_result[family] = {
                "numerator": str(numerator),
                "signed_denominator": str(denominator),
                "ratio_fraction": str(ratio),
                "ratio_decimal": str(dec(ratio)),
                "float": float(ratio),
            }
        for family in ("source_normalized", "export_reweighted"):
            numerator, denominator = sums[p][family + "_num"], sums[p][family + "_den"]
            assert denominator != 0
            part_result[family + "_decimal70_diagnostic"] = str(numerator / denominator)
        results[name] = part_result

    raw_unchanged = all(sha(W / rel) == expected for rel, expected in PINS.items())
    if not raw_unchanged:
        raise RuntimeError("Consumed input SHA-256 changed during replay")

    result = {
        "scope": __doc__,
        "scientific_admission": False,
        "native_fp_equivalence": False,
        "native_print_read_observed": False,
        "raw_inputs_unchanged": raw_unchanged,
        "pins": dict(PINS),
        "recipe_sha256": sha(Path(__file__).resolve()),
        "methods": {
            "carrier_rendering": "Exact IEEE-754 binary32 final carrier words (RFACTOR_WORK, RFACTOR_FREE) captured at final_carrier_work / final_carrier_free.",
            "captured_operand": "Exact rational (fractions.Fraction) sum of captured binary32 YOS and YC_ALL over the 6,494 work / 723 free native overall_added domain.",
            "export": "Exact rational (fractions.Fraction) sum of exported binary32 F-obs and FC_ALL_LS in refmac_hklout.mtz over the same 6,494 work / 723 free domain.",
            "source_normalized_decimal70_diagnostic": "Bounded Decimal(prec=70) diagnostic evaluating sum(|YOS - YC_ALL| / EXPAN) / sum(YOS / EXPAN) from captured S0 binary32 words.",
            "export_reweighted_decimal70_diagnostic": "Bounded Decimal(prec=70) diagnostic evaluating sum(|F-obs - FC_ALL_LS| * EXPAN) / sum(F-obs * EXPAN) from exported HKLOUT words and captured S0 EXPAN.",
        },
        "counts": dict(counts),
        "event_counts": dict(event_counts),
        "distinct_captured_EXPAN_words": len(expan_words),
        "results": results,
        "source_relation_max_errors": maxima,
        "examples": examples,
        "carrier_rendering": carriers,
    }
    with output.open("x", encoding="utf-8") as fh:
        fh.write(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    with localcontext() as ctx:
        ctx.prec = 70
        main()
