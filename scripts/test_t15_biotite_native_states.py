#!/usr/bin/env python3
"""Mocked native Biotite-state admission; no scientific imports or execution."""
from __future__ import annotations

from contextlib import contextmanager, redirect_stderr, redirect_stdout
import io
from pathlib import Path
import sys
from types import ModuleType
import unittest
from unittest import mock

import t15_ss_agreement as t15


class Column(list):
    def __eq__(self, other):
        return [value == other for value in self]


class Atoms:
    """Only the array operations used by run_biotite; no numpy/Biotite import."""

    def __init__(self, rows, *, with_icode=True):
        self.rows = list(rows)
        self.with_icode = with_icode
        for index, name in enumerate(("chain_id", "res_id", "ins_code", "atom_name", "res_name")):
            setattr(self, name, Column(row[index] for row in self.rows))

    def __getitem__(self, mask):
        assert len(mask) == len(self.rows)
        assert all(type(value) is bool for value in mask)
        return Atoms([row for row, keep in zip(self.rows, mask, strict=True) if keep], with_icode=self.with_icode)

    def get_annotation_categories(self):
        return ["chain_id", "res_id", "atom_name", "res_name"] + (["ins_code"] if self.with_icode else [])


@contextmanager
def mocked_biotite(rows, assignments, *, with_icode=True):
    modules = {name: ModuleType(name) for name in (
        "biotite", "biotite.structure", "biotite.structure.io", "biotite.structure.io.pdb")}
    for module in modules.values():
        module.__path__ = []
    modules["biotite"].structure = modules["biotite.structure"]
    modules["biotite.structure"].io = modules["biotite.structure.io"]
    modules["biotite.structure.io"].pdb = modules["biotite.structure.io.pdb"]
    structure, pdb = modules["biotite.structure"], modules["biotite.structure.io.pdb"]
    calls = []
    structure.filter_amino_acids = lambda array: [name == "ALA" for name in array.res_name]

    def starts(array):
        keys = [(row[0], row[1], row[2] if with_icode else "") for row in array.rows]
        return [index for index, key in enumerate(keys) if not index or keys[index - 1] != key]

    def annotate(array):
        assert array.rows and all(name == "ALA" for name in array.res_name)
        chain = array.chain_id[0]
        assert all(value == chain for value in array.chain_id)
        calls.append(tuple(array.rows))
        return assignments[chain]

    def get_structure(pdb_file, model):
        assert pdb_file == "mocked PDB" and model == 1
        return Atoms(rows, with_icode=with_icode)

    structure.get_residue_starts = starts
    structure.annotate_sse = annotate
    pdb.PDBFile = type("PDBFile", (), {"read": staticmethod(lambda _path: "mocked PDB")})
    pdb.get_structure = get_structure
    with (mock.patch.dict(sys.modules, modules),
          mock.patch("subprocess.run", side_effect=AssertionError("No subprocess")),
          mock.patch("subprocess.Popen", side_effect=AssertionError("No subprocess")),
          mock.patch("socket.create_connection", side_effect=AssertionError("No network")),
          mock.patch.object(t15, "run_capture", side_effect=AssertionError("No scientific tool"))):
        yield calls


class NativeBiotiteStateTests(unittest.TestCase):
    def test_exact_abc_mapping_preserves_keys_and_chain_selection(self):
        rows = [("B", 4, "I", "CA", "ALA"), ("A", -3, "", "N", "ALA"),
                ("A", -3, "", "CA", "ALA"), ("A", -3, "A", "CA", "ALA"),
                ("A", 9, "", "CA", "ALA"), ("W", 2, "", "O", "HOH")]
        with mocked_biotite(rows, {"A": ["a", "b", "c"], "B": ["c"]}) as calls:
            result = t15.run_biotite(Path("mocked-multichain.pdb"))
        self.assertEqual(result, {("A", "-3", ""): "H", ("A", "-3", "A"): "E",
                                  ("A", "9", ""): "C", ("B", "4", "I"): "C"})
        self.assertEqual([call[0][0] for call in calls], ["A", "B"])

    def test_native_c_without_ca_is_not_reinterpreted_by_wrapper(self):
        rows = [("A", 3, "", "N", "ALA")]
        with mocked_biotite(rows, {"A": ["c"]}):
            self.assertEqual(t15.run_biotite(Path("mocked-no-ca.pdb")), {("A", "3", ""): "C"})

    def test_empty_native_code_is_unavailable_not_coil(self):
        rows = [("AB", -3, "I", "N", "ALA")]
        with mocked_biotite(rows, {"AB": [""]}), self.assertRaises(SystemExit) as raised:
            t15.run_biotite(Path("mocked-no-ca.pdb"))
        message = str(raised.exception)
        for text in ("unavailable/no assignment", "empty native code", "mocked-no-ca.pdb",
                     "chain 'AB'", "residue '-3'", "insertion code 'I'", "refusing to coerce to coil"):
            self.assertIn(text, message)

    def test_unknown_native_values_are_contextual_failures(self):
        rows = [("A", 10, "B", "CA", "ALA")]
        for code in ("Z", " ", "H", "E", "C", "A", "a ", "ab", "?", None, 0, False, ["c"]):
            with self.subTest(code=code), mocked_biotite(rows, {"A": [code]}), self.assertRaises(SystemExit) as raised:
                t15.run_biotite(Path("mocked-unknown.pdb"))
            message = str(raised.exception)
            for text in ("unsupported native secondary-structure code", repr(code), "mocked-unknown.pdb",
                         "chain 'A'", "residue '10'", "insertion code 'B'"):
                self.assertIn(text, message)

    def test_mixed_stream_never_returns_partial_or_padded_assignments(self):
        rows = [("A", 1, "", "CA", "ALA"), ("A", 2, "", "N", "ALA"),
                ("B", 3, "", "CA", "ALA")]
        for codes in (("", "a"), ("a", ""), ("a", "Z")):
            with self.subTest(codes=codes):
                with mocked_biotite(rows, {"A": list(codes), "B": ["c"]}) as calls, \
                        redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()) as error, \
                        self.assertRaises(SystemExit):
                    t15.run_biotite(Path("mocked-mixed.pdb"))
                self.assertEqual(output.getvalue(), "")
                self.assertEqual(error.getvalue(), "")
                self.assertEqual([call[0][0] for call in calls], ["A"])

    def test_no_icode_annotation_preserves_existing_empty_key(self):
        rows = [("A", 4, "ignored", "CA", "ALA")]
        with mocked_biotite(rows, {"A": ["b"]}, with_icode=False):
            self.assertEqual(t15.run_biotite(Path("mocked-no-icode.pdb")), {("A", "4", ""): "E"})

    def test_existing_length_mismatch_refuses_before_native_projection(self):
        rows = [("A", 1, "", "CA", "ALA"), ("A", 2, "", "CA", "ALA")]
        for codes in ([], ["a"], ["a", "b", "c"]):
            with self.subTest(codes=codes), mocked_biotite(rows, {"A": codes}), \
                    self.assertRaisesRegex(SystemExit, "assignment/residue mismatch.*refusing to drop"):
                t15.run_biotite(Path("mocked-length.pdb"))

    def test_no_amino_acids_is_empty_not_fabricated_coil(self):
        rows = [("W", 1, "", "O", "HOH")]
        with mocked_biotite(rows, {}) as calls:
            self.assertEqual(t15.run_biotite(Path("mocked-water-only.pdb")), {})
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
