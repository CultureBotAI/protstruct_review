#!/usr/bin/env python3
"""Hermetic #846 grammar, coverage, identity and retained-byte controls.

All tool/network calls in bundle fixtures are denied or synthetic. Actual
upstream test strings are static grammar examples, not scientific executions.
"""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import re
import unittest
from unittest import mock

import bench_dictionary_loaded_reduce as driver
import recount_standalone_reduce_flips as recount
import test_bench_dictionary_loaded_reduce as driver_fixtures

HIS_HD1 = "USER  MOD Single : B   4 HIS     :FLIP no HD1:sc=   0.634  F(o=-2.1!,f=0.63)"
HIS_HE2 = "USER  MOD Single : B   4 HIS     :FLIP no HE2:sc=   0.911  F(o=-2.8!,f=0.91)"
ASN = "USER  MOD Single : B   3 ASN     :FLIP  amide:sc=   -4.98! C(o=-12!,f=-5!)"
GLN = "USER  MOD Single : B   9 GLN     :FLIP  amide:sc=   0.716  F(o=-4.8!,f=0.72)"


def line(*, chain=" A", number=32, icode=" ", name="GLN", alt=" ",
         orientation="FLIP  amide", prefix="Single ", category="F", atom="    "):
    clash = "!" if category == "C" else ""
    return (f"USER  MOD {prefix}:{chain}{number:4d}{icode}{name}{atom}{alt}:"
            f"{orientation}:sc=   0.435  {category}(o=-0.2{clash},f=0.44{clash})")


def atom(key, serial=1, atom_name=" CA "):
    fields = list(" " * 80)
    def put(start, end, value):
        fields[start:end] = value
    put(0, 6, "ATOM  "); put(6, 11, f"{serial:5d}"); put(12, 16, atom_name)
    fields[16] = key["altloc"]; put(17, 20, key["resname"])
    put(20, 22, key["chain_raw"]); put(22, 26, f"{key['resnum']:4d}"); fields[26] = key["icode"]
    for start in (30, 38, 46):
        put(start, start + 8, "   0.000")
    put(54, 60, "  1.00"); put(60, 66, " 20.00"); put(76, 78, " C")
    return "".join(fields) + "\n"


def data(lines, *, keys=None, model=None):
    raw = ("\n".join(lines) + ("\n" if lines else "")).encode()
    if keys is None:
        keys = list({recount.full_key(recount.parse_line(item)["key"]): recount.parse_line(item)["key"]
                     for item in lines if "key" in recount.parse_line(item)}.values())
    coordinates = "".join(atom(key, n) for n, key in enumerate(keys, 1))
    if model is not None:
        coordinates = f"MODEL     {model:4d}\n" + coordinates + "ENDMDL\n"
    return raw + coordinates.encode() + b"END\n", raw


def source_recount(h_bytes, raw_bytes):
    """Grammar fixtures explicitly supply synthetic input without annotations.

    This is not authenticated execution; bundle tests cover actual admission.
    The separate output-only test must call the public pure function directly.
    """
    clean_input = b"".join(row for row in h_bytes.splitlines(keepends=True)
                           if not row.startswith(b"USER"))
    return recount.recount(h_bytes, raw_bytes, input_bytes=clean_input)


class GrammarTests(unittest.TestCase):
    def test_all_ten_source_orientations(self):
        self.assertEqual(len(recount.ORIENTATIONS), 10)
        for orientation, (kind, flipped) in recount.ORIENTATIONS.items():
            for name in (("ASN", "GLN") if kind == "amide" else ("HIS",)):
                with self.subTest(orientation=orientation, name=name):
                    item = recount.parse_line(line(name=name, orientation=orientation, category="F" if flipped else "K"))
                    self.assertEqual(item["status"], "parsed_flip")
                    self.assertIs(item["flipped"], flipped)
                    self.assertEqual(item["orientation"], orientation)

    def test_actual_upstream_his_and_wholeflip_examples(self):
        # reduce-src/test/test_reduce.py:416-418,502: literals, not a new run.
        result = source_recount(*data([ASN, HIS_HD1, GLN]))
        self.assertTrue(result["counts_admitted"])
        self.assertEqual(result["parsed_mover_count"], 3)
        self.assertEqual(result["parsed_flipped_mover_count"], 3)
        self.assertEqual(result["category_counts"], {"C": 1, "F": 2})
        self.assertEqual(recount.parse_line(HIS_HE2)["status"], "parsed_flip")

    def test_original_regex_negative_controls(self):
        # Captured verbatim at #846 audit from bench_t14_flip_sets.py:59-63,
        # SHA256 39da5654e22df714419e74b340a832d3e03895f14458a0805dcd5c3a16ab27c2.
        # This historical control must not require future production to stay broken.
        legacy = re.compile(
            r"^USER  MOD \S+\s*:\s*(?P<chain>.)\s*(?P<resseq>\d+)\s+(?P<resname>\S+)\s*:"
            r"(?P<decision>FLIP|\s*)\s*(?P<kind>amide|his)\s*:sc=\s*(?P<score>\S+)\s+"
            r"(?P<category>[A-Z])\(")
        self.assertIsNotNone(legacy.match(GLN))
        for raw in (HIS_HD1, HIS_HE2, line(prefix="Set 1.1")):
            self.assertIsNone(legacy.match(raw))
            self.assertEqual(recount.parse_line(raw)["status"], "parsed_flip")
        self.assertIsNotNone(legacy.match(line(prefix="Set10.1")))

    def test_set_numbers_and_full_identity(self):
        for prefix in ("Single ", "Set 1.1", "Set 9.2", "Set10.1", "Set100.123"):
            for chain in ("  ", " A", "AB"):
                item = recount.parse_line(line(prefix=prefix, chain=chain, number=-2, icode="C", alt="D"))
                self.assertEqual(item["status"], "parsed_flip")
                self.assertEqual(item["key"], {"model_ordinal": 1, "chain_raw": chain, "resnum": -2,
                                               "icode": "C", "resname": "GLN", "altloc": "D"})

    def test_c_and_x_not_directions_and_printed_scores_not_reclassified(self):
        for category in ("C", "X"):
            for orientation in ("FLIP  amide", "      amide"):
                item = recount.parse_line(line(category=category, orientation=orientation))
                self.assertEqual(item["status"], "parsed_flip")
                self.assertEqual(item["flipped"], orientation.startswith("FLIP"))
        raw = line().replace("0.435  F(o=-0.2,f=0.44)", "+1e-3! C(o=-2E+2!,f=.2!)")
        item = recount.parse_line(raw)
        self.assertEqual(item["score_text"], "+1e-3")
        self.assertEqual(item["original_score_text"], "-2E+2")
        self.assertEqual(item["flipped_score_text"], ".2")
        self.assertTrue(all(item[field] for field in ("clash_selected", "clash_original", "clash_flipped")))

    def test_output_only_counts_never_claim_new_call_attribution(self):
        h, raw = data([line()])
        result = recount.recount(h, raw)
        self.assertEqual(result["status"], "output_only_unattributed")
        self.assertFalse(result["counts_admitted"])
        self.assertIsNone(result["input_sha256"])
        self.assertEqual(result["input_annotation_check"], "not_supplied")
        self.assertEqual(result["parsed_flipped_mover_count"], 1)

    def test_input_annotation_origin_check_covers_spacing_and_metadata(self):
        h, raw = data([line()])
        for annotation in (line(), line().replace("USER  MOD", "USER MOD"),
                           line().replace("USER  MOD", "USER\tMOD"),
                           "USER  MOD reduce.4.16.250520 H: found=0, std=0, add=1, rem=0, adj=0"):
            with self.subTest(annotation=annotation), self.assertRaisesRegex(ValueError, "input contains USER MOD"):
                recount.recount(h, raw, input_bytes=annotation.encode() + b"\n" + h[len(raw):])

    def test_category_C_exactly_matches_both_clash_flags(self):
        for category in ("C", "X", "F", "K"):
            for orientation in ("FLIP  amide", "      amide"):
                for original, flipped in (("", ""), ("!", ""), ("", "!"), ("!", "!")):
                    row = line(category=category, orientation=orientation)
                    row = row[:row.index("(o=")] + f"(o=-0.2{original},f=0.44{flipped})"
                    with self.subTest(row=row):
                        item = recount.parse_line(row)
                        valid = ((category == "C") == (original == flipped == "!"))
                        valid = valid and not (category == "F" and not orientation.startswith("FLIP"))
                        valid = valid and not (category == "K" and orientation.startswith("FLIP"))
                        self.assertEqual(item["status"], "parsed_flip" if valid else "rejected")
                        if not ((category == "C") == (original == flipped == "!")):
                            self.assertEqual(item["reason"], "category_clash_contradiction")

    def test_all_known_metadata_and_rotation_families(self):
        metadata = [*recount.HEADERS,
                    "USER  MOD reduce.3.3.160422 H: found=0, std=0, add=78, rem=0, adj=5",
                    'USER  MOD "!" flags a clash with an overlap of 0.40A or greater']
        rotations = ["USER  MOD Single : A  68 THR OG1 :   rot  -40:sc= 0.00645",
                     "USER  MOD Set 1.2: A  68 THR CG2 :methyl  180:sc=       1   (180deg=0.3)",
                     "USER  MOD Set10.2: A  68 LYS NZ  :NH3+    -40:sc=       1!  (180deg=-0.3!)"]
        for raw in metadata:
            self.assertEqual(recount.parse_line(raw)["status"], "metadata", raw)
        for raw in rotations:
            self.assertEqual(recount.parse_line(raw)["status"], "non_flip_rotation", raw)
        result = source_recount(*data(metadata + rotations + [line()]))
        self.assertFalse(result["counts_admitted"])  # CA-only fixture lacks named rotation atoms.
        h, raw = data(metadata + rotations + [line()])
        h += "".join(atom(recount.parse_line(row)["key"], 100 + n,
                           recount.parse_line(row)["atom_name_raw"])
                      for n, row in enumerate(rotations)).encode()
        result = source_recount(h, raw)
        self.assertTrue(result["counts_admitted"])
        self.assertEqual(sum(result["record_counts"].values()), result["raw_line_count"])
        self.assertEqual(result["record_counts"]["non_flip_rotation"], 3)

    def test_unknown_malformed_forced_and_unsupported_never_disappear(self):
        bad = [line(prefix="Unknown"), line(orientation="FLIP his"), line(name="ALA"),
               line(category="Y"), line(category="K"), line(orientation="      amide"),
               line().replace("0.435", "nan"), line().replace("0.435", "1e999"),
               line()[:-1], line() + " trailing", line().replace(" A  32", "ABCD  32"),
               line().replace("  32", "A001"), line(prefix="Fix    "),
               "USER  MOD not a known header", line(atom=" CA "),
               "USER  MOD Single : A  68 THR CG2 :methyl  180:sc=       1 "]
        for raw in bad:
            item = recount.parse_line(raw, 9)
            self.assertEqual(item["status"], "rejected", raw)
            self.assertEqual((item["raw"], item["line_number"]), (raw, 9))
        good_h, good_raw = data([line()])
        for raw in bad:
            extension = (raw + "\n").encode()
            result = source_recount(good_h + extension, good_raw + extension)
            self.assertFalse(result["counts_admitted"])
            self.assertEqual(result["record_counts"]["rejected"], 1)

    def test_identity_residue_counts_duplicate_and_candidate_coverage(self):
        for values, field in ((("A", "B"), "icode"), (("A", "B"), "alt")):
            rows = [line(**{field: value}) for value in values]
            result = source_recount(*data(rows, model=7))
            self.assertTrue(result["counts_admitted"])
            self.assertEqual(result["parsed_mover_count"], 2)
            self.assertEqual(result["parsed_distinct_residue_count"], 2 if field == "icode" else 1)
            self.assertEqual(result["model_label_raw"], "   7")
        duplicate = source_recount(*data([line(), line()]))
        self.assertFalse(duplicate["counts_admitted"])
        self.assertEqual(duplicate["records"][1]["reason"], "duplicate_mover_key")
        one = recount.parse_line(line())["key"]
        other = {**one, "resnum": 33}
        result = source_recount(*data([line()], keys=[one, other]))
        self.assertEqual(result["unadjudicated_coordinate_keys"], [other])
        self.assertTrue(result["counts_admitted"])
        zero = source_recount(*data([], keys=[one]))
        self.assertEqual(zero["status"], "needs_review_no_calls")
        self.assertEqual(zero["unadjudicated_coordinate_keys"], [one])

    def test_coordinate_binding_is_exact_and_ambiguous_blank_fails(self):
        one = recount.parse_line(line())["key"]
        for change in ({"chain_raw": "BA"}, {"resnum": -32}, {"icode": "A"},
                       {"resname": "ASN"}, {"altloc": "A"}):
            result = source_recount(*data([line()], keys=[{**one, **change}]))
            self.assertFalse(result["counts_admitted"], change)
        result = source_recount(*data([line()], keys=[one, {**one, "altloc": "A"}]))
        self.assertFalse(result["counts_admitted"])
        result = source_recount(*data([line(alt="A")], keys=[one, {**one, "altloc": "A"}]))
        self.assertTrue(result["counts_admitted"])
        h, raw = data([line()])
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            source_recount(h + atom(one, 99).encode(), raw)
        with self.assertRaisesRegex(ValueError, "MODEL"):
            source_recount(h + b"MODEL        2\nENDMDL\nMODEL        3\nENDMDL\n", raw)
        # Non-candidate ions must not make an otherwise admitted PDB unparseable.
        ion = {**one, "resnum": 90, "resname": " ZN"}
        self.assertTrue(source_recount(h + atom(ion, 99).encode(), raw)["counts_admitted"])

    def test_exact_raw_bytes_alternate_spelling_and_legacy_domain(self):
        h, raw = data([line()])
        with self.assertRaisesRegex(ValueError, "USER MOD bytes"):
            source_recount(h, raw[:-1])
        result = source_recount(h + b"USER MOD renamed 1 ambiguous 'A' atoms (marked in segID field)\n", raw)
        self.assertFalse(result["counts_admitted"])
        self.assertEqual(len(result["unsupported_USER_MOD_spellings"]), 1)
        with self.assertRaisesRegex(ValueError, "paired adapter"):
            recount.legacy_comparison_keys(source_recount(h, raw))


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = driver_fixtures.DictionaryLoadedDriverTests(methodName="runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.model.write_bytes(self.fixture.model.read_bytes().replace(b"ALA A   1", b"GLN A   1"))
        original = self.fixture.fake_command
        def fake_command(arguments, output, **kwargs):
            result = original(arguments, output, **kwargs)
            if Path(arguments[0]) == self.fixture.reduce:
                path = Path(output)
                path.write_text(path.read_text().replace("USER  MOD synthetic raw record", line(number=1)))
            return result
        for owner in (driver.toolchain, driver.clash):
            patch = mock.patch.object(owner, "run_to_file", side_effect=fake_command)
            patch.start(); self.addCleanup(patch.stop)
        self.assertEqual(self.fixture.cli(), 0)
        self.directory = self.fixture.root / "evidence/24MR"
        self.before = {str(path): path.read_bytes() for path in self.fixture.root.rglob("*") if path.is_file()}
        # Recount must never execute anything, even the synthetic tool stubs.
        for owner, name in ((driver.toolchain, "run_capture"), (driver.toolchain, "run_to_file"),
                            (driver.clash, "run_to_file"), (driver, "execute"), (driver, "worker")):
            patch = mock.patch.object(owner, name, side_effect=AssertionError("recount must be read-only"))
            patch.start(); self.addCleanup(patch.stop)

    def test_complete_bundle_and_cli_are_read_only(self):
        result = recount.recount_bundle(self.directory)
        self.assertTrue(result["counts_admitted"])
        self.assertEqual(result["input_sha256"], recount.digest((self.directory / "input.pdb").read_bytes()))
        self.assertEqual(result["input_annotation_check"], "no_preexisting_USER_MOD")
        self.assertEqual(result["parsed_mover_count"], 1)
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(recount.main([str(self.directory)]), 0)
        self.assertEqual(json.loads(output.getvalue()), result)
        self.assertEqual(self.before, {str(path): path.read_bytes() for path in self.fixture.root.rglob("*") if path.is_file()})

    def test_original_pins_reject_h_raw_worker_manifest_source_mutations(self):
        worker = json.loads((self.directory / "worker-result.json").read_text())
        paths = [Path(worker["h_model"]["path"]), self.directory / "raw-user-mod.txt",
                 self.directory / "worker-result.json", Path(worker["h_model"]["path"]).parent / "manifest.json",
                 self.directory / "sources/standalone_reduce.py", self.fixture.root / "scripts/standalone_reduce.py",
                 self.directory / "commands/01/stderr.bin"]
        for path in paths:
            original = path.read_bytes()
            with self.subTest(path=path):
                path.write_bytes(original + b"\n")
                try:
                    with self.assertRaises(ValueError):
                        recount.recount_bundle(self.directory)
                finally:
                    path.write_bytes(original)

    def test_changed_h_or_raw_during_interpretation_is_rejected(self):
        real_recount = recount.recount
        worker = json.loads((self.directory / "worker-result.json").read_text())
        for path in (Path(worker["h_model"]["path"]), self.directory / "raw-user-mod.txt",
                     self.directory / "result.json", self.directory / "input.pdb"):
            original = path.read_bytes()
            def mutate(h, raw, **kwargs):
                result = real_recount(h, raw, **kwargs)
                path.write_bytes(original + b"\n")
                return result
            with self.subTest(path=path), mock.patch.object(recount, "recount", side_effect=mutate):
                try:
                    with self.assertRaises(ValueError):
                        recount.recount_bundle(self.directory)
                finally:
                    path.write_bytes(original)

    def test_failed_parent_and_missing_parent_pin_refuse(self):
        path = self.directory / "result.json"
        parent = json.loads(path.read_text())
        parent["status"] = "failed"
        path.write_text(json.dumps(parent))
        with redirect_stderr(io.StringIO()):
            self.assertEqual(recount.main([str(self.directory)]), 1)
        parent["status"] = "complete"
        del parent["retained_files"]["worker-result.json"]
        path.write_text(json.dumps(parent))
        with self.assertRaisesRegex(ValueError, "omits"):
            recount.recount_bundle(self.directory)

    def test_parent_timeout_does_not_become_admitted_by_status_alone(self):
        path = self.directory / "result.json"
        parent = json.loads(path.read_text())
        parent["process"]["timed_out"] = True
        path.write_text(json.dumps(parent))
        with self.assertRaisesRegex(ValueError, "process"):
            recount.recount_bundle(self.directory)


class AdmissionRegressionTests(unittest.TestCase):
    def make_attempt(self, *, input_annotation=None, output_annotation=None):
        fixture = driver_fixtures.DictionaryLoadedDriverTests(methodName="runTest")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        model = fixture.model.read_bytes().replace(b"ALA A   1", b"GLN A   1")
        if input_annotation is not None:
            header, rest = model.split(b"\n", 1)
            model = header + b"\n" + input_annotation.encode() + b"\n" + rest
        fixture.model.write_bytes(model)
        original = fixture.fake_command

        def fake_command(arguments, output, **kwargs):
            outcome = original(arguments, output, **kwargs)
            if Path(arguments[0]) == fixture.reduce:
                path = Path(output)
                replacement = b"" if output_annotation is None else output_annotation.encode() + b"\n"
                path.write_bytes(path.read_bytes().replace(b"USER  MOD synthetic raw record\n", replacement))
            return outcome

        with (mock.patch.object(driver.toolchain, "run_to_file", side_effect=fake_command),
              mock.patch.object(driver.clash, "run_to_file", side_effect=fake_command),
              mock.patch("subprocess.run", side_effect=AssertionError("No child permitted")),
              mock.patch("subprocess.Popen", side_effect=AssertionError("No child permitted"))):
            self.assertEqual(fixture.cli(), 0)
        for owner, name in ((driver.toolchain, "run_capture"), (driver.toolchain, "run_to_file"),
                            (driver.clash, "run_to_file"), (driver, "execute"), (driver, "worker")):
            patch = mock.patch.object(owner, name, side_effect=AssertionError("Read-only recount required"))
            patch.start()
            self.addCleanup(patch.stop)
        return fixture.root / "evidence/24MR"

    def test_public_cli_rejects_inherited_call_in_valid_driver_bundle(self):
        annotation = line(number=1)
        directory = self.make_attempt(input_annotation=annotation)
        self.assertEqual((directory / "raw-user-mod.txt").read_bytes(), annotation.encode() + b"\n")
        before = {str(path): path.read_bytes() for path in directory.rglob("*") if path.is_file()}
        with redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()) as error:
            self.assertEqual(recount.main([str(directory)]), 1)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("input contains USER MOD", error.getvalue())
        self.assertEqual(before, {str(path): path.read_bytes() for path in directory.rglob("*") if path.is_file()})

    def test_public_cli_rejects_input_metadata_even_with_new_call(self):
        directory = self.make_attempt(
            input_annotation="USER  MOD reduce.4.16.250520 H: found=0, std=0, add=1, rem=0, adj=0",
            output_annotation=line(number=1),
        )
        with redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()) as error:
            self.assertEqual(recount.main([str(directory)]), 1)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("input contains USER MOD", error.getvalue())

    def test_public_cli_rejects_case_normalized_inherited_records(self):
        # libpdb/pdb_type.cpp:303-305 normalizes the first four characters;
        # write_format.i:55 emits USER. The MOD body is not case-normalized.
        original = driver_fixtures.DictionaryLoadedDriverTests.fake_command

        def normalized_command(fixture, arguments, output, **kwargs):
            result = original(fixture, arguments, output, **kwargs)
            if Path(arguments[0]) == fixture.reduce:
                path = Path(output)
                path.write_bytes(b"".join(
                    b"USER" + row[4:] if row[:4].upper() == b"USER" else row
                    for row in path.read_bytes().splitlines(keepends=True)
                ))
            return result

        # Each case gets separate fixture mocks and cleanup; neither generates
        # a new call. Exercise real parent/worker inventories and the public CLI.
        for record_name in ("uSeR", "user"):
            case = AdmissionRegressionTests(methodName="runTest")
            try:
                inherited = line(number=1).replace("USER", record_name, 1)
                with mock.patch.object(driver_fixtures.DictionaryLoadedDriverTests,
                                       "fake_command", normalized_command):
                    directory = case.make_attempt(input_annotation=inherited)
                self.assertEqual((directory / "raw-user-mod.txt").read_bytes(),
                                 line(number=1).encode() + b"\n")
                before = {str(p): p.read_bytes() for p in directory.rglob("*") if p.is_file()}
                with (self.subTest(record_name=record_name),
                      redirect_stdout(io.StringIO()) as output,
                      redirect_stderr(io.StringIO()) as error):
                    self.assertEqual(recount.main([str(directory)]), 1)
                    self.assertEqual(output.getvalue(), "")
                    self.assertIn("input contains USER MOD", error.getvalue())
                    self.assertEqual(before, {str(p): p.read_bytes()
                                              for p in directory.rglob("*") if p.is_file()})
            finally:
                case.doCleanups()

    def assert_category_cli_rejected(self, annotation):
        directory = self.make_attempt(output_annotation=annotation)
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(recount.main([str(directory)]), 1)
        result = json.loads(output.getvalue())
        self.assertFalse(result["counts_admitted"])
        self.assertEqual(result["parsed_mover_count"], 0)
        self.assertEqual(result["records"][0]["reason"], "category_clash_contradiction")

    def test_public_cli_rejects_C_without_both_clashes(self):
        self.assert_category_cli_rejected(line(number=1, category="C").replace("!", ""))

    def test_public_cli_rejects_non_C_with_both_clashes(self):
        self.assert_category_cli_rejected(line(number=1, category="C").replace(" C(o=", " F(o="))


if __name__ == "__main__":
    unittest.main()
