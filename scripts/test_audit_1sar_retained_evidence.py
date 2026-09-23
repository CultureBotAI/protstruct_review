#!/usr/bin/env python3
"""Stdlib-only tests of retained-byte parsing; no scientific executable runs.

Real-data expectations below were independently recounted from fixed PDB slices
and MTZ IEEE words. They are not new refinement, map, or validation results.
Synthetic fixtures live entirely in memory; this suite writes no evidence files.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import struct
import sys
import unittest
from unittest import mock
import zipfile

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import audit_1sar_retained_evidence as audit  # noqa: E402


MTZ_CONTEXT_HEADERS = [
    "CELL 10 20 30 90 90 90", "SYMINF 1 1 P 1 'P1' 1", "SYMM X,Y,Z",
    "RESO 0.001 0.16", "NDIF 1", "DATASET 0 synthetic", "DCELL 0 10 20 30 90 90 90",
]


def atom_line(*, serial: int = 1, record: str = "ATOM", name: str = "CA",
              residue: str = "ALA", chain: str = "A", number: int = 1,
              insertion: str = " ", altloc: str = " ", element: str = "C",
              x: float = 1.25, y: float = -2.5, z: float = 3.75,
              occupancy: float = 1.0, b_factor: float = 20.0) -> str:
    """Build an explicit 80-column PDB atom, without a PDB library."""
    fields = list(" " * 80)
    for start, end, text in (
        (0, 6, f"{record:<6}"), (6, 11, f"{serial:5d}"),
        (12, 16, f"{name:>4}"), (16, 17, altloc), (17, 20, f"{residue:>3}"),
        (21, 22, chain), (22, 26, f"{number:4d}"), (26, 27, insertion),
        (30, 38, f"{x:8.3f}"), (38, 46, f"{y:8.3f}"), (46, 54, f"{z:8.3f}"),
        (54, 60, f"{occupancy:6.2f}"), (60, 66, f"{b_factor:6.2f}"),
        (76, 78, f"{element:>2}"),
    ):
        if len(text) != end - start:
            raise ValueError("test field does not fit its fixed-column width")
        fields[start:end] = text
    return "".join(fields)


def mtz_blob(rows: list[list[float | bytes]], *,
             columns: tuple[str, ...] = ("H", "K", "L", "F", "SIGF"),
             headers: list[str] | None = None) -> bytes:
    """Build minimal little-endian MTZ bytes; byte cells preserve NaN payloads."""
    if any(len(row) != len(columns) for row in rows):
        raise ValueError("synthetic row width differs from the declared columns")
    table = b"".join(value if isinstance(value, bytes) else struct.pack("<f", value)
                     for row in rows for value in row)
    preamble = bytearray(80)
    preamble[:4] = b"MTZ "
    preamble[4:8] = struct.pack("<i", (80 + len(table)) // 4 + 1)
    preamble[8:12] = bytes.fromhex("44410000")
    if headers is None:
        headers = [f"NCOL {len(columns)} {len(rows)} 0"]
        headers += [f"COLUMN {name} {'H' if index < 3 else 'F'} 0 0 0"
                    for index, name in enumerate(columns)]
        headers += [*MTZ_CONTEXT_HEADERS, "END"]
    return bytes(preamble) + table + b"".join(line.encode("ascii").ljust(80, b" ")
                                             for line in headers)


def header_records(blob: bytes) -> list[str]:
    offset = (int.from_bytes(blob[4:8], "little") - 1) * 4
    lines = []
    for index in range(offset, len(blob), 80):
        line = blob[index:index + 80].decode("ascii").strip()
        lines.append(line)
        if line == "END":
            break
    return lines


def with_headers(blob: bytes, headers: list[str]) -> bytes:
    offset = (int.from_bytes(blob[4:8], "little") - 1) * 4
    if any(len(line.encode("ascii")) > 80 for line in headers):
        raise ValueError("synthetic header exceeds its fixed width")
    return blob[:offset] + b"".join(line.encode("ascii").ljust(80, b" ") for line in headers)


class PdbAtomTests(unittest.TestCase):
    def test_fixed_columns_element_identity_and_hydrogen_exclusion(self) -> None:
        text = "\n".join([
            "HEADER synthetic coordinate parser fixture", atom_line(),
            atom_line(serial=2, record="HETATM", name="CA", residue="CA",
                      number=98, element="Ca", occupancy=0.5, b_factor=42.73),
            atom_line(serial=3, name="H", element="H"),
            atom_line(serial=4, name="D", element="D"), "TER", "END",
        ])
        result = audit.pdb_atoms(text)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], {
            "key": ("A", "1", "", "ALA", "CA"), "element": "C",
            "xyz": [1.25, -2.5, 3.75], "occupancy": 1.0, "b_factor": 20.0,
        })
        self.assertEqual(result[1]["element"], "Ca")
        self.assertEqual(result[1]["occupancy"], 0.5)
        self.assertEqual(result[1]["b_factor"], 42.73)

    def test_atom_record_type_is_not_a_protein_selector(self) -> None:
        result = audit.pdb_atoms("\n".join([
            atom_line(record="ATOM", name="O", residue="HOH", element="O"),
            atom_line(record="HETATM", residue="ALA", serial=2),
        ]))
        self.assertEqual([row["key"][3] for row in result], ["HOH", "ALA"])

    def test_insertion_chain_residue_and_atom_name_distinguish_keys(self) -> None:
        lines = [atom_line(), atom_line(serial=2, insertion="A"),
                 atom_line(serial=3, chain="B"), atom_line(serial=4, residue="GLY"),
                 atom_line(serial=5, name="N", element="N")]
        self.assertEqual(len(audit.pdb_atoms("\n".join(lines))), 5)

    def test_duplicate_key_rejected_even_when_serial_or_record_differs(self) -> None:
        for second in [atom_line(serial=2), atom_line(serial=3, record="HETATM")]:
            with self.subTest(second=second[:11]):
                with self.assertRaisesRegex(ValueError, "duplicate atom key"):
                    audit.pdb_atoms(atom_line() + "\n" + second)

    def test_altloc_missing_element_and_truncated_columns_rejected(self) -> None:
        for text, message in [
            (atom_line(altloc="A"), "without altlocs"),
            (atom_line(element=""), "explicit element"),
            (atom_line()[:77], "complete fixed-column"),
        ]:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    audit.pdb_atoms(text)

    def test_explicit_model_block_rejected_even_for_one_model(self) -> None:
        for text in ["MODEL        1\n" + atom_line() + "\nENDMDL",
                     atom_line() + "\nMODEL        2\n" + atom_line(chain="B")]:
            with self.assertRaisesRegex(ValueError, "implicit single PDB model"):
                audit.pdb_atoms(text)

    def test_all_selected_float_fields_reject_nonfinite_values(self) -> None:
        for field in ("x", "y", "z", "occupancy", "b_factor"):
            for value in (math.nan, math.inf, -math.inf):
                with self.subTest(field=field, value=value):
                    with self.assertRaisesRegex(ValueError, "nonfinite"):
                        audit.pdb_atoms(atom_line(**{field: value}))

    def test_malformed_selected_numeric_fields_fail(self) -> None:
        for start, end in ((30, 38), (38, 46), (46, 54), (54, 60), (60, 66)):
            for token in ("", "bad"):
                text = atom_line()
                malformed = text[:start] + token.rjust(end - start) + text[end:]
                with self.subTest(start=start, token=token):
                    with self.assertRaises(ValueError):
                        audit.pdb_atoms(malformed)

    def test_empty_or_only_hydrogen_selection_rejected(self) -> None:
        for text in ("", "HEADER no coordinates", atom_line(element="H", name="H"),
                     atom_line(element="D", name="D")):
            with self.assertRaisesRegex(ValueError, "empty coordinate selection"):
                audit.pdb_atoms(text)


class DistributionTests(unittest.TestCase):
    def test_population_distribution_not_sample_or_occupancy_weighted(self) -> None:
        self.assertEqual(audit.distribution([2.0, 4.0]), {
            "count": 2, "mean": 3.0, "population_std_dev": 1.0, "min": 2.0, "max": 4.0,
        })
        self.assertEqual(audit.distribution([7.0])["population_std_dev"], 0.0)

    def test_empty_distribution_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "empty distribution"):
            audit.distribution([])


class MtzObservationTests(unittest.TestCase):
    def test_selected_columns_and_hkl_identity_ignore_row_and_extra_column_order(self) -> None:
        first = mtz_blob([[2, 0, -1, 20, 2, 7], [1, 0, 0, 10, 1, 9]],
                         columns=("H", "K", "L", "F-obs", "SIGF-obs", "FLAG"))
        second = mtz_blob([[1, 0, 0, 99, 1, 10], [2, 0, -1, 88, 2, 20]],
                          columns=("H", "K", "L", "UNUSED", "SIGF", "F"))
        a = audit.mtz_observations(first, ("F-obs", "SIGF-obs"))
        b = audit.mtz_observations(second, ("F", "SIGF"))
        self.assertEqual(a, b)
        self.assertEqual(a, {(2, 0, -1): (struct.pack("<f", 20), struct.pack("<f", 2)),
                             (1, 0, 0): (struct.pack("<f", 10), struct.pack("<f", 1))})
        self.assertEqual(audit.observation_digest(a), audit.observation_digest(b))

    def test_digest_has_explicit_sorted_signed_hkl_and_selected_byte_contract(self) -> None:
        rows = {(2, -1, 0): (b"abcd", b"efgh"), (-1, 0, 3): (b"ijkl", b"mnop")}
        expected_bytes = (struct.pack("<iii", -1, 0, 3) + b"ijklmnop"
                          + struct.pack("<iii", 2, -1, 0) + b"abcdefgh")
        self.assertEqual(audit.observation_digest(rows), hashlib.sha256(expected_bytes).hexdigest())
        self.assertEqual(audit.observation_digest(dict(reversed(list(rows.items())))),
                         audit.observation_digest(rows))

    def test_nan_payload_and_signed_zero_are_preserved_not_float_normalized(self) -> None:
        nan1, nan2 = bytes.fromhex("0100c07f"), bytes.fromhex("0200c07f")
        a = audit.mtz_observations(mtz_blob([[1, 2, 3, nan1, -0.0]]), ("F", "SIGF"))
        b = audit.mtz_observations(mtz_blob([[1, 2, 3, nan2, -0.0]]), ("F", "SIGF"))
        c = audit.mtz_observations(mtz_blob([[1, 2, 3, nan1, 0.0]]), ("F", "SIGF"))
        self.assertEqual(a[(1, 2, 3)], (nan1, bytes.fromhex("00000080")))
        self.assertNotEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertNotEqual(audit.observation_digest(a), audit.observation_digest(b))
        self.assertNotEqual(audit.observation_digest(a), audit.observation_digest(c))

    def test_missing_nonpair_or_duplicate_selectors_rejected(self) -> None:
        blob = mtz_blob([[1, 2, 3, 10, 1]])
        for labels in (("missing", "SIGF"), (), ("F",), ("F", "SIGF", "H"), ("F", "F")):
            with self.subTest(labels=labels):
                with self.assertRaises(ValueError):
                    audit.mtz_observations(blob, labels)

    def test_wrong_magic_endianness_and_truncated_preamble_rejected(self) -> None:
        blob = mtz_blob([[1, 2, 3, 10, 1]])
        for malformed in (b"", b"MTZ ", blob[:9], b"BAD " + blob[4:],
                          blob[:8] + bytes.fromhex("1111") + blob[10:]):
            with self.subTest(length=len(malformed)):
                with self.assertRaisesRegex(ValueError, "little-endian IEEE"):
                    audit.mtz_observations(malformed, ("F", "SIGF"))

    def test_header_offset_outside_table_or_not_matching_dimensions_rejected(self) -> None:
        blob = mtz_blob([[1, 2, 3, 10, 1]])
        for word in (-5, 0, 1, 20, 25, 10000):
            malformed = blob[:4] + struct.pack("<i", word) + blob[8:]
            with self.subTest(word=word):
                with self.assertRaises(ValueError):
                    audit.mtz_observations(malformed, ("F", "SIGF"))

    def test_missing_or_truncated_end_record_rejected(self) -> None:
        blob = mtz_blob([[1, 2, 3, 10, 1]])
        for malformed in (blob[:-80], blob[:-77], blob[:-1]):
            with self.subTest(length=len(malformed)):
                with self.assertRaises(ValueError):
                    audit.mtz_observations(malformed, ("F", "SIGF"))

    def test_non_ascii_header_rejected(self) -> None:
        blob = mtz_blob([[1, 2, 3, 10, 1]])
        with self.assertRaises(ValueError):
            audit.mtz_observations(blob[:100] + b"\xff" + blob[101:], ("F", "SIGF"))

    def test_ncol_and_column_identity_failures(self) -> None:
        columns = [f"COLUMN {label} F 0 0 0" for label in ("H", "K", "L", "F", "SIGF")]
        variants = [columns, ["NCOL 5 1 0", "NCOL 5 1 0", *columns],
                    ["NCOL 6 1 0", *columns], ["NCOL 5 2 0", *columns],
                    ["NCOL 5 0 0", *columns], ["NCOL 5 -1 0", *columns],
                    ["NCOL bad 1 0", *columns], ["NCOL 5", *columns],
                    ["NCOL 5 1 0", *columns[:-1]],
                    ["NCOL 5 1 0", *columns[:-1], columns[-2]],
                    ["NCOL 5 1 0", columns[1], columns[0], *columns[2:]]]
        for headers in variants:
            with self.subTest(headers=headers):
                with self.assertRaises(ValueError):
                    audit.mtz_observations(mtz_blob([[1, 2, 3, 10, 1]],
                                                    headers=[*headers, "END"]), ("F", "SIGF"))

    def test_empty_reflection_table_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "dimensions"):
            audit.mtz_observations(mtz_blob([]), ("F", "SIGF"))

    def test_nonintegral_or_nonfinite_hkl_rejected_in_each_position(self) -> None:
        for position in range(3):
            for value in (0.5, math.nan, math.inf, -math.inf):
                row = [1, 2, 3, 10, 1]
                row[position] = value
                with self.subTest(position=position, value=value):
                    with self.assertRaisesRegex(ValueError, "non-integral reflection"):
                        audit.mtz_observations(mtz_blob([row]), ("F", "SIGF"))

    def test_duplicate_hkl_rejected_even_when_observations_differ(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate reflection key"):
            audit.mtz_observations(mtz_blob([[1, 2, 3, 10, 1], [1, 2, 3, 11, 2]]), ("F", "SIGF"))


class MtzContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.blob = mtz_blob([[1, 2, 3, 10, 1]])
        self.headers = header_records(self.blob)

    def test_formatting_and_dataset_ids_are_not_crystallographic_differences(self) -> None:
        changed = []
        replacements = {
            "CELL": "CELL 10.000 20.0 30 90.00 90 90",
            "SYMINF": "SYMINF 1 1 p 1 'P 1' PG1 X",
            "SYMM": "SYMM x, y, z", "RESO": "RESO 0.001000 0.1600",
            "DATASET": "DATASET 7 renamed", "DCELL": "DCELL 7 10.0 20 30 90 90 90",
        }
        for line in self.headers:
            if line.startswith("COLUMN "):
                changed.append(line.rsplit(" ", 1)[0] + " 7")
            else:
                changed.append(replacements.get(line.split()[0], line))
        self.assertEqual(audit.mtz_crystallographic_context(self.blob),
                         audit.mtz_crystallographic_context(with_headers(self.blob, changed)))

    def test_cell_symmetry_resolution_and_sub_float_decimal_changes_are_distinct(self) -> None:
        baseline = audit.mtz_crystallographic_context(self.blob)
        variants = [
            [line.replace("10 20 30", "11 20 30") for line in self.headers],
            ["SYMINF 1 1 P 2 'P-1' 1" if line.startswith("SYMINF ") else line
             for line in self.headers],
            ["SYMM -X,Y,Z" if line.startswith("SYMM ") else line for line in self.headers],
            ["RESO 0.001 0.17" if line.startswith("RESO ") else line for line in self.headers],
            ["RESO 0.001000000000000000000000000000001 0.16"
             if line.startswith("RESO ") else line for line in self.headers],
        ]
        for headers in variants:
            with self.subTest(headers=headers):
                altered = with_headers(self.blob, headers)
                self.assertEqual(audit.mtz_observations(self.blob, ("F", "SIGF")),
                                 audit.mtz_observations(altered, ("F", "SIGF")))
                self.assertNotEqual(baseline, audit.mtz_crystallographic_context(altered))

    def test_required_context_headers_cannot_be_missing_or_duplicated(self) -> None:
        for key in ("CELL", "SYMINF", "RESO", "NDIF"):
            row = next(line for line in self.headers if line.startswith(key + " "))
            for replacement in ([], [row, row]):
                headers = [line for line in self.headers if line != row]
                headers[-1:-1] = replacement
                with self.subTest(key=key, replacement=replacement):
                    with self.assertRaisesRegex(ValueError, f"exactly one {key}"):
                        audit.mtz_crystallographic_context(with_headers(self.blob, headers))

    def test_invalid_context_shapes_and_incomplete_dataset_binding_fail(self) -> None:
        mutations = [
            ("CELL", "CELL 10 20 30 90 90"), ("CELL", "CELL NaN 20 30 90 90 90"),
            ("CELL", "CELL 0 20 30 90 90 90"), ("CELL", "CELL 10 20 30 180 90 90"),
            ("RESO", "RESO 0.16 0.001"), ("RESO", "RESO 0 0.16"),
            ("RESO", "RESO NaN 0.16"), ("RESO", "RESO bad 0.16"),
            ("RESO", "RESO 0.001 0.16 extra"),
            ("SYMINF", "SYMINF 1 1 P"), ("SYMINF", "SYMINF 0 1 P 1 'P1' 1"),
            ("SYMINF", "SYMINF 1 2 P 1 'P1' 1"), ("SYMINF", "SYMINF 1 1 Z 1 'P1' 1"),
            ("SYMINF", "SYMINF 1 1 P 231 'P1' 1"), ("SYMINF", "SYMINF 1 1 P 1 'P1' 1 Y"),
            ("SYMM", "SYMM X,Y"), ("SYMM", "SYMM X,X,Z"),
            ("SYMM", "SYMM X+1/0,Y,Z"), ("SYMM", "SYMM ?X,Y,Z"),
            ("NDIF", "NDIF 2"), ("NDIF", "NDIF 0"), ("NDIF", "NDIF 1 extra"),
            ("DATASET", "DATASET 0"), ("DATASET", "DATASET -1 synthetic"),
            ("DCELL", "DCELL 0 11 20 30 90 90 90"), ("DCELL", "DCELL 0 10 20 30 90 90"),
            ("DCELL", "DCELL 3 10 20 30 90 90 90"), ("DCELL", "DCELL 0 NaN 20 30 90 90 90"),
            ("COLUMN", "COLUMN F F 0 0 3"), ("COLUMN", "COLUMN F F 0 0"),
        ]
        for key, bad in mutations:
            headers = [bad if line.startswith(key + " ") else line for line in self.headers]
            with self.subTest(mutation=bad):
                with self.assertRaises(ValueError):
                    audit.mtz_crystallographic_context(with_headers(self.blob, headers))
        for key in ("SYMM", "DATASET", "DCELL", "COLUMN"):
            selected = next(line for line in self.headers if line.startswith(key + " "))
            variants = [[line for line in self.headers if not line.startswith(key + " ")]]
            if key != "COLUMN":
                variants.append([*self.headers[:-1], selected, "END"])
            for headers in variants:
                with self.subTest(key=key, headers=headers):
                    with self.assertRaises(ValueError):
                        audit.mtz_crystallographic_context(with_headers(self.blob, headers))


class RetainedArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with mock.patch("subprocess.run", side_effect=AssertionError("external execution forbidden")), \
                mock.patch("subprocess.Popen", side_effect=AssertionError("external execution forbidden")):
            cls.report = audit.audit(REPO)
        with zipfile.ZipFile(REPO / audit.ARCHIVE) as archive:
            cls.model_bytes = archive.read("data/1sar_final.pdb")
            cls.dataset_bytes = archive.read("data/1sar.mtz")
        cls.output_bytes = (REPO / audit.BASE / "t13_oracle_logs/ctruncate_out.mtz").read_bytes()

    def test_exact_retained_artifact_identities_and_scope(self) -> None:
        self.assertEqual(self.report["archive"]["member_count"], 241)
        self.assertEqual(self.report["archive"]["sha256"],
                         "9fc5352284b7ffa7763c633a3eb4d3d0db96b8c25a1be9bcea361722d2c53054")
        self.assertEqual(self.report["model"]["sha256"],
                         "8cbc1650f8be5a3833f98833fa514ec7d490c2c3bb9aa930413abac05e2a510b")
        self.assertEqual(self.report["dataset"]["sha256"],
                         "f36d5fe685a3e524e8809d17d19ce12073acdf339eba2cfd3b0347a818850ab2")
        self.assertEqual(self.report["dataset"]["subject_ref"],
                         "mtz:sha256:f36d5fe685a3e524e8809d17d19ce12073acdf339eba2cfd3b0347a818850ab2")
        self.assertIn("no external oracle invocation", self.report["audit_kind"])
        json.dumps(self.report, allow_nan=False)

    def test_all_heavy_protein_and_water_counts_have_independent_fixed_column_baseline(self) -> None:
        lines = [line for line in self.model_bytes.decode("ascii").splitlines()
                 if line[:6] in ("ATOM  ", "HETATM") and line[76:78].strip() not in ("H", "D")]
        self.assertEqual(len(lines), 1641)
        self.assertEqual(sum(Decimal(line[60:66]) for line in lines), Decimal("26225.50"))
        self.assertEqual(Counter(line[76:78].strip() for line in lines),
                         {"C": 930, "N": 244, "O": 458, "S": 7, "Ca": 1, "Na": 1})
        self.assertEqual(sum(line[:6] == "ATOM  " for line in lines), 1493)
        selected = self.report["coordinate_selections"]
        self.assertEqual(selected["all_heavy_atoms_b_a2"]["count"], 1641)
        self.assertEqual(selected["standard_amino_acid_atoms_b_a2"]["count"], 1488)
        self.assertEqual(selected["waters_b_a2"]["count"], 146)
        self.assertEqual(selected["water_residue_count"], 146)
        self.assertEqual(1488 + 146 + 1 + 1 + 5, 1641)

    def test_exact_population_b_summaries_not_historical_mislabelled_protein_mean(self) -> None:
        selected = self.report["coordinate_selections"]
        expected = {
            "all_heavy_atoms_b_a2": (15.981413772090189, 8.942857928772892, 3.83, 80.68),
            "standard_amino_acid_atoms_b_a2": (15.484670698924731, 8.810525384609656, 3.83, 80.68),
            "waters_b_a2": (20.758835616438358, 8.778393190121715, 6.62, 53.76),
        }
        for key, values in expected.items():
            for field, expected_value in zip(("mean", "population_std_dev", "min", "max"), values):
                with self.subTest(selection=key, field=field):
                    self.assertAlmostEqual(selected[key][field], expected_value, places=12)
        self.assertAlmostEqual(selected["standard_amino_acid_atoms_b_a2"]["mean"], 23041.19 / 1488)
        self.assertAlmostEqual(selected["waters_b_a2"]["mean"], 3030.79 / 146)
        self.assertNotAlmostEqual(selected["standard_amino_acid_atoms_b_a2"]["mean"], 15.98, places=2)

    def test_component_coordinates_occupancy_and_global_protein_denominator(self) -> None:
        ligands = {row["modelled_component"]: row
                   for row in self.report["coordinate_selections"]["ligands"]}
        expected = {"CA": (1, 42.73, 2.7595033069038535),
                    "NA": (1, 22.85, 1.4756529502165472),
                    "SO4": (5, 17.588, 1.1358330016809028)}
        for component, (count, b_mean, ratio) in expected.items():
            with self.subTest(component=component):
                self.assertEqual(ligands[component]["atom_count"], count)
                self.assertAlmostEqual(ligands[component]["mean_b_factor_a2"], b_mean, places=12)
                self.assertAlmostEqual(ligands[component]["mean_b_over_global_protein_mean"], ratio, places=12)
                self.assertTrue(all(atom["occupancy"] == 1 for atom in ligands[component]["atoms"]))
        self.assertEqual(ligands["CA"]["atoms"][0]["xyz"], [66.752, 3.733, 13.397])
        self.assertEqual(ligands["NA"]["atoms"][0]["xyz"], [37.743, 11.865, 11.598])
        self.assertIn("not a local surrounding shell", self.report["coordinate_selections"]["ratio_interpretation"])

    def test_all_7248_selected_observations_and_nan_payloads_match(self) -> None:
        original = audit.mtz_observations(self.dataset_bytes, ("F-obs", "SIGF-obs"))
        retained = audit.mtz_observations(self.output_bytes, ("F", "SIGF"))
        self.assertEqual(len(original), 7248)
        self.assertEqual(original, retained)
        self.assertEqual(sum(math.isnan(struct.unpack("<f", values[0])[0])
                             for values in original.values()), 20)
        self.assertEqual(sum(math.isnan(struct.unpack("<f", values[1])[0])
                             for values in original.values()), 20)
        expected_digest = "927d368a4d9d3b29588813c304b45b3c47bafa51f2cd6585cf93ebc9e61c937d"
        self.assertEqual(audit.observation_digest(original), expected_digest)
        self.assertEqual(self.report["t13"]["selected_observation_equivalence"][
            "canonical_hkl_f_sigf_sha256"], expected_digest)
        self.assertNotEqual(self.dataset_bytes, self.output_bytes)

    def test_real_mtz_equivalence_has_independent_ieee_word_recount(self) -> None:
        # Independently read known retained table widths and column positions;
        # this does not use mtz_observations or observation_digest.
        observed = []
        for blob, width in ((self.dataset_bytes, 16), (self.output_bytes, 5)):
            header_offset = (int.from_bytes(blob[4:8], "little") - 1) * 4
            rows = {}
            for words in struct.iter_unpack("<" + "I" * width, blob[80:header_offset]):
                key = tuple(int(struct.unpack("<f", word.to_bytes(4, "little"))[0]) for word in words[:3])
                self.assertNotIn(key, rows)
                rows[key] = tuple(word.to_bytes(4, "little") for word in words[3:5])
            self.assertEqual(len(rows), 7248)
            digest = hashlib.sha256()
            for key, values in sorted(rows.items()):
                for index in key:
                    digest.update(index.to_bytes(4, "little", signed=True))
                for value in values:
                    digest.update(value)
            self.assertEqual(digest.hexdigest(),
                             "927d368a4d9d3b29588813c304b45b3c47bafa51f2cd6585cf93ebc9e61c937d")
            observed.append(rows)
        self.assertEqual(observed[0], observed[1])

    def test_real_context_matches_with_distinct_dataset_and_symmetry_header_spelling(self) -> None:
        original = audit.mtz_crystallographic_context(self.dataset_bytes)
        retained = audit.mtz_crystallographic_context(self.output_bytes)
        self.assertEqual(original, retained)
        self.assertEqual(original["cell_a_b_c_alpha_beta_gamma"],
                         ["64.897", "78.323", "38.792", "9E+1", "9E+1", "9E+1"])
        self.assertEqual(original["resolution_limits_inverse_a2"],
                         ["0.0004004509537481", "0.1599971801042557"])
        self.assertEqual(original["symmetry"], {
            "operator_count": 4, "primitive_operator_count": 4, "lattice": "P",
            "space_group_number": 19, "space_group_symbol": "P212121", "point_group": "222",
            "operators_xyz": sorted(["X,Y,Z", "X+1/2,-Y+1/2,-Z", "-X,Y+1/2,-Z+1/2",
                                     "-X+1/2,-Y,Z+1/2"]),
        })
        context = self.report["t13"]["crystallographic_context_equivalence"]
        self.assertTrue(context["normalized_context_equal"])
        self.assertEqual(context["normalized_context"], original)
        for label, blob in (("archived_input", self.dataset_bytes), ("ctruncate_output", self.output_bytes)):
            rows = context["retained_header_records"][label]
            self.assertTrue(all(line in header_records(blob) for line in rows))
        self.assertNotEqual(context["retained_header_records"]["archived_input"],
                            context["retained_header_records"]["ctruncate_output"])
        self.assertIn("does not recover the historical input file bytes", context["limitation"])

    def test_real_symmetry_operator_order_and_whitespace_are_not_differences(self) -> None:
        headers = header_records(self.output_bytes)
        operators = [line for line in headers if line.startswith("SYMM ")]
        other = [line for line in headers if not line.startswith("SYMM ")]
        other[-1:-1] = ["SYMM " + line[5:].lower().replace(" ", "") for line in reversed(operators)]
        self.assertEqual(audit.mtz_crystallographic_context(self.output_bytes),
                         audit.mtz_crystallographic_context(with_headers(self.output_bytes, other)))

    def test_audit_rejects_changed_context_even_with_identical_selected_observations(self) -> None:
        output_path = REPO / audit.BASE / "t13_oracle_logs/ctruncate_out.mtz"
        headers = header_records(self.output_bytes)
        variants = [
            [line.replace("64.8970", "65.8970") for line in headers],
            [line.replace("X+1/2", "X+1/3") if line.startswith("SYMM ") else line for line in headers],
            [line.replace("0.1599971801042557", "0.1699971801042557") for line in headers],
            [line.replace("64.8970", "65.8970") if line.startswith("DCELL ") else line for line in headers],
        ]
        original_read = Path.read_bytes
        for changed_headers in variants:
            changed = with_headers(self.output_bytes, changed_headers)
            self.assertEqual(audit.mtz_observations(changed, ("F", "SIGF")),
                             audit.mtz_observations(self.output_bytes, ("F", "SIGF")))

            def read(path: Path) -> bytes:
                return changed if path == output_path else original_read(path)

            with self.subTest(headers=changed_headers), mock.patch.object(Path, "read_bytes", read):
                with self.assertRaisesRegex(ValueError, "context"):
                    audit.audit(REPO)

    def test_t13_is_saved_may_log_parsing_not_new_execution(self) -> None:
        t13 = self.report["t13"]
        self.assertEqual(t13["execution_date_in_retained_logs"], "2026-05-04")
        self.assertEqual(t13["aimless_status"], "failed: hkl_unmerge_list::prepare - EMPTY")
        self.assertEqual(t13["ctruncate_parsed"]["wilson_b"], 14.542)
        self.assertEqual(t13["ctruncate_parsed"]["twin_fraction_l"], 0.03)
        self.assertEqual(t13["ctruncate_parsed"]["twin_fraction_moments"], 0.02)
        self.assertEqual(t13["ctruncate_parsed"]["moment_2_acentric"], 1.968)
        self.assertEqual(t13["ctruncate_parsed"]["ice_ring_resolutions_flagged"], [3.44])
        self.assertFalse(t13["ctruncate_parsed"]["tncs_flag"])
        self.assertIn("not the full bytes", t13["selected_observation_equivalence"]["limitation"])
        self.assertIn("or a new execution", t13["selected_observation_equivalence"]["limitation"])
        for record in [*t13["logs"], t13["ctruncate_output"]]:
            self.assertEqual(record["sha256"], hashlib.sha256((REPO / record["path"]).read_bytes()).hexdigest())

    def test_archive_hash_mismatch_is_rejected_before_member_reading(self) -> None:
        with mock.patch.object(audit, "ARCHIVE_SHA256", "0" * 64), \
                mock.patch.object(audit.zipfile, "ZipFile") as reader:
            with self.assertRaisesRegex(ValueError, "differs from the reviewed exact artifact"):
                audit.audit(REPO)
            reader.assert_not_called()

    def test_archive_member_missing_or_duplicate_rejected(self) -> None:
        for names in ([audit.MODEL_MEMBER], [audit.DATA_MEMBER],
                      [audit.MODEL_MEMBER, audit.MODEL_MEMBER, audit.DATA_MEMBER],
                      [audit.MODEL_MEMBER, audit.DATA_MEMBER, audit.DATA_MEMBER]):
            with self.subTest(names=names):
                with mock.patch.object(audit.zipfile, "ZipFile") as reader:
                    archive = reader.return_value.__enter__.return_value
                    archive.infolist.return_value = [zipfile.ZipInfo(name) for name in names]
                    with self.assertRaisesRegex(ValueError, "missing or duplicated"):
                        audit.audit(REPO)
                    archive.read.assert_not_called()

    def test_water_selection_requires_one_heavy_atom_per_residue(self) -> None:
        atoms = audit.pdb_atoms("\n".join([
            atom_line(),
            atom_line(record="HETATM", residue="HOH", chain="S", name="O", element="O"),
            atom_line(record="HETATM", residue="HOH", chain="S", name="O2", element="O"),
        ]))
        with mock.patch.object(audit, "pdb_atoms", return_value=atoms):
            with self.assertRaisesRegex(ValueError, "one heavy atom per residue"):
                audit.audit(REPO)

    def test_saved_output_changed_selected_observation_is_rejected(self) -> None:
        output_path = REPO / audit.BASE / "t13_oracle_logs/ctruncate_out.mtz"
        altered = bytearray(self.output_bytes)
        altered[92] ^= 1  # First row F IEEE word, without changing valid table layout.
        original_read = Path.read_bytes

        def read(path: Path) -> bytes:
            return bytes(altered) if path == output_path else original_read(path)

        with mock.patch.object(Path, "read_bytes", read):
            with self.assertRaisesRegex(ValueError, "selected observations differ"):
                audit.audit(REPO)

    def test_saved_aimless_failure_marker_is_required(self) -> None:
        aimless_path = REPO / audit.BASE / "t13_oracle_logs/aimless.log"
        original_read = Path.read_bytes

        def read(path: Path) -> bytes:
            return b"synthetic unrelated log\n" if path == aimless_path else original_read(path)

        with mock.patch.object(Path, "read_bytes", read):
            with self.assertRaisesRegex(ValueError, "does not show the recorded failure"):
                audit.audit(REPO)


if __name__ == "__main__":
    unittest.main()
