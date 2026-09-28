#!/usr/bin/env python3
"""Hermetic observed-component inventories; no scientific processes/network."""
from __future__ import annotations

from contextlib import ExitStack, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

import inventory_standalone_components as inventory
import test_bench_dictionary_loaded_reduce as fixtures

driver = inventory.driver


def atom(*, name="C1", element="C", residue="ATP", chain=" A", number=1,
         icode=" ", alt=" ", record="HETATM", serial=1):
    fields = list(" " * 80)
    def put(start, end, value):
        fields[start:end] = value
    put(0, 6, f"{record:<6}"); put(6, 11, f"{serial:5d}"); put(12, 16, f"{name:^4}")
    fields[16] = alt; put(17, 20, residue); put(20, 22, chain)
    put(22, 26, f"{number:4d}"); fields[26] = icode
    for start in (30, 38, 46):
        put(start, start + 8, "   0.000")
    put(54, 60, "  1.00"); put(60, 66, " 20.00"); put(76, 78, f"{element:>2}")
    return "".join(fields) + "\n"


def pdb(rows, *, entry="24MR", model=None):
    header = fixtures.pdb(entry).splitlines()[0].decode() + "\n"
    body = "".join(rows)
    if model is not None:
        body = f"MODEL     {model:4d}\n" + body + "ENDMDL\n"
    return (header + body + "END\n").encode()


def deny_execution():
    stack = ExitStack()
    for owner, name in ((driver.toolchain, "run_capture"), (driver.toolchain, "run_to_file"),
                        (driver.clash, "run_to_file"), (driver, "execute"), (driver, "worker"),
                        (inventory.retained, "recount_bundle"), (inventory.retained, "recount"),
                        (inventory.retained, "parse_line"), (driver.urllib.request, "urlopen")):
        stack.enter_context(mock.patch.object(owner, name, side_effect=AssertionError(f"Forbidden: {name}")))
    for name in ("subprocess.run", "subprocess.Popen"):
        stack.enter_context(mock.patch(name, side_effect=AssertionError(f"Forbidden: {name}")))
    return stack


class CoordinateTests(unittest.TestCase):
    def test_exact_instances_not_component_name_collapsed(self):
        rows = [atom(chain="AB", number=-2, icode="I"), atom(chain="AB", number=-2, icode="J"),
                atom(chain="CD", number=-2, icode="I"), atom(chain="AB", number=2)]
        result = inventory.inventory_bytes(pdb(rows, model=7), pdb(rows, model=7), "24MR")
        self.assertFalse(result["bundle_admitted"])
        self.assertEqual((result["input_model_label_raw"], result["output_model_label_raw"]), ("   7", "   7"))
        keys = [row["identity"] for row in result["nonwater_hetero_instances"]]
        self.assertEqual(len(keys), 4)
        self.assertEqual({key["chain_raw"] for key in keys}, {"AB", "CD"})
        self.assertEqual({key["resnum"] for key in keys}, {-2, 2})
        self.assertEqual({key["icode"] for key in keys}, {" ", "I", "J"})
        self.assertTrue(all(key["model_ordinal"] == 1 for key in keys))

    def test_model_label_changes_are_not_silently_joined(self):
        for input_model in (None, 7):
            result = inventory.inventory_bytes(pdb([atom()], model=input_model), pdb([atom()], model=9), "24MR")
            rows = result["nonwater_hetero_instances"]
            self.assertEqual(len(rows), 2)
            self.assertEqual({row["observed_presence"] for row in rows}, {"input_only", "output_only"})
            self.assertEqual({row["identity"]["model_label_raw"] for row in rows},
                             {None if input_model is None else "   7", "   9"})

    def test_literal_altlocs_common_blank_once_and_record_partitions(self):
        common = [atom(name="C1"), atom(name="C2", alt="A"), atom(name="C2", alt="B"),
                  atom(name="N1", element="N", record="ATOM")]
        added = [atom(name="H1", element="H"), atom(name="H2", element="H", alt="A"),
                 atom(name="H2", element="H", alt="B"), atom(name="D1", element="D")]
        result = inventory.inventory_bytes(pdb(common), pdb(common + added), "24MR")
        row = result["nonwater_hetero_instances"][0]
        self.assertEqual(row["observed_presence"], "both")
        self.assertEqual(row["output"]["counts"], {"atom_records": 8, "h_records": 3,
                                                      "d_records": 1, "other_element_records": 4})
        self.assertEqual(row["output"]["record_types"]["ATOM"]["atom_records"], 1)
        self.assertEqual(row["output"]["record_types"]["HETATM"]["atom_records"], 7)
        altlocs = {item["altloc"]: item["counts"] for item in row["output"]["altlocs"]}
        self.assertEqual({alt: count["atom_records"] for alt, count in altlocs.items()}, {" ": 4, "A": 2, "B": 2})
        self.assertEqual(sum(item["h_records"] for item in altlocs.values()), 3)
        self.assertEqual(row["chemical_coverage"], "unassessed")

    def test_exact_HOH_H_vs_D_and_no_element_inference(self):
        rows = [atom(residue="HOH", element="O", name="O"), atom(residue="HOH", element="H", name="H1"),
                atom(residue="DOD", element="D", name="D1"), atom(residue="ATP", name="H1", element="C"),
                atom(residue="ATP", name="X1", element="H")]
        result = inventory.inventory_bytes(pdb(rows), pdb(rows), "24MR")
        totals = result["output_totals"]
        self.assertEqual(totals["all"]["counts"], {"atom_records": 5, "h_records": 2,
                                                  "d_records": 1, "other_element_records": 2})
        self.assertEqual(totals["non_HOH"]["counts"]["h_records"], 1)
        self.assertEqual(totals["non_HOH"]["counts"]["d_records"], 1)
        self.assertEqual({row["identity"]["resname_raw"] for row in result["nonwater_hetero_instances"]}, {"ATP", "DOD"})

    def test_observed_presence_does_not_classify_missing_chemistry(self):
        before = [atom(residue="ATP", number=1), atom(residue="MG ", element="MG", number=2)]
        after = [atom(residue="ATP", number=1, record="ATOM"), atom(residue="NA ", element="NA", number=3)]
        result = inventory.inventory_bytes(pdb(before), pdb(after), "24MR")
        rows = {item["identity"]["resname_raw"]: item for item in result["nonwater_hetero_instances"]}
        self.assertEqual({key: item["observed_presence"] for key, item in rows.items()},
                         {"ATP": "both", "MG ": "input_only", "NA ": "output_only"})
        self.assertTrue(all(item["chemical_coverage"] == "unassessed" for item in rows.values()))
        self.assertEqual(rows["NA "]["output"]["counts"]["h_records"], 0)
        self.assertEqual(rows["MG "]["output"]["counts"]["atom_records"], 0)

    def test_no_hetero_components_is_valid_observation(self):
        data = pdb([atom(record="ATOM", residue="ALA")])
        result = inventory.inventory_bytes(data, data, "24MR")
        self.assertEqual(result["nonwater_hetero_instances"], [])
        self.assertEqual(result["chemical_coverage"], "unassessed")

    def test_invalid_or_duplicate_identity_never_becomes_counts(self):
        good = pdb([atom()])
        cases = [pdb([atom(), atom()]), pdb([atom(element="")]), good.replace(b"   1 ", b"A001 "),
                 good.replace(b"   0.000", b"     nan", 1), pdb([atom()], entry="37AS"),
                 pdb([atom()], model=1).replace(b"ENDMDL\n", b"ENDMDL\nMODEL        2\nENDMDL\n")]
        for data in cases:
            with self.subTest(data=data), self.assertRaises(ValueError):
                inventory.inventory_bytes(good, data, "24MR")

    def test_global_count_reconciliation_guard(self):
        data = pdb([atom(element="H")])
        original = driver.pdb_inventory
        def mismatch(*args, **kwargs):
            return {**original(*args, **kwargs), "h_all_records": 99}
        with mock.patch.object(driver, "pdb_inventory", side_effect=mismatch):
            with self.assertRaisesRegex(ValueError, "component/global"):
                inventory.inventory_bytes(data, data, "24MR")


class BundleTests(unittest.TestCase):
    def make_bundle(self, *, cohort="clashscore", entry="24MR"):
        fixture = fixtures.DictionaryLoadedDriverTests(methodName="runTest")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.model.write_bytes(pdb([atom(record="ATOM", residue="ALA"), atom(number=2)], entry=entry))
        fixture.build_stderr = "Warning: synthetic unmatched component\nUnclassified message\n"
        fixture.probe_stderr = "Synthetic Probe diagnostic\n"
        launch = fixture.fake_launch
        def clean_launch(*args, **kwargs):
            result = launch(*args, **kwargs)
            started = json.loads((args[0].path / "worker-start.json").read_bytes())
            record = {**result.to_record(), "pid": started["pid"], "pgid": started["pgid"],
                      "cleanup": {"status": "group_absent", "pgid": started["pgid"],
                                                       "group_absent_verified": True, "signal_attempts": []}}
            return SimpleNamespace(**record, to_record=lambda: record)
        fixture.fake_launch = clean_launch
        with mock.patch("subprocess.run", side_effect=AssertionError("No process")), \
                mock.patch("subprocess.Popen", side_effect=AssertionError("No process")), \
                mock.patch.object(driver, "__file__", str(fixture.root / "scripts/bench_dictionary_loaded_reduce.py")):
            self.assertEqual(fixture.cli(cohort=cohort, entry=entry), 0)
        return fixture, fixture.root / "evidence" / entry

    def test_public_both_cohorts_need_no_flip_calls_and_are_read_only(self):
        for cohort, entry in (("clashscore", "24MR"), ("flip", "12OC")):
            fixture, directory = self.make_bundle(cohort=cohort, entry=entry)
            self.assertIn(b"synthetic raw record", (directory / "raw-user-mod.txt").read_bytes())
            before = {str(path): path.read_bytes() for path in fixture.root.rglob("*") if path.is_file()}
            with deny_execution(), redirect_stdout(io.StringIO()) as output:
                self.assertEqual(inventory.main([str(directory)]), 0)
            result = json.loads(output.getvalue())
            self.assertTrue(result["bundle_admitted"])
            self.assertEqual(result["status"], "complete_observed_inventory")
            self.assertEqual(result["chemical_coverage"], "unassessed")
            self.assertEqual(result["nonwater_hetero_instances"][0]["output"]["counts"]["h_records"], 0)
            diagnostics = result["unassigned_diagnostics"]
            self.assertTrue(all(item["assignment"] == "unassigned" for item in diagnostics))
            self.assertIn("Warning: synthetic unmatched component\nUnclassified message\n",
                          [item["text"] for item in diagnostics])
            for item in diagnostics:
                self.assertEqual(item["sha256"], driver.digest((directory / item["path"]).read_bytes()))
            self.assertEqual(len([item for item in diagnostics if item["path"].startswith("commands/")]),
                             2 if cohort == "clashscore" else 1)
            self.assertEqual(before, {str(path): path.read_bytes() for path in fixture.root.rglob("*") if path.is_file()})

    def test_parent_process_and_cleanup_are_required(self):
        _, directory = self.make_bundle()
        path = directory / "result.json"
        original = path.read_bytes()
        for change in (lambda x: x.update(status="failed"),
                       lambda x: x["process"].update(returncode=1),
                       lambda x: x["process"].update(timed_out=True),
                       lambda x: x["process"].update(cleanup=None),
                       lambda x: x["process"]["cleanup"].update(group_absent_verified=False),
                       lambda x: x["process"]["cleanup"].update(pgid=9876)):
            parent = json.loads(original); change(parent); path.write_text(json.dumps(parent))
            with deny_execution(), redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()) as error:
                self.assertEqual(inventory.main([str(directory)]), 1)
            self.assertEqual(output.getvalue(), "")
            self.assertIn("Inventory refused", error.getvalue())
        path.write_bytes(original)

    def test_original_evidence_mutations_and_missing_pins_reject(self):
        fixture, directory = self.make_bundle()
        worker = json.loads((directory / "worker-result.json").read_bytes())
        h_path = Path(worker["h_model"]["path"])
        paths = [directory / "input.pdb", h_path, directory / "commands/01/stderr.bin",
                 directory / "worker.log", directory / "worker-start.json", directory / "worker-result.json", directory / "input-provenance.json",
                 h_path.parent / "manifest.json", fixture.prereg, fixture.reduce, fixture.dictionary,
                 directory / "sources/standalone_reduce.py", fixture.root / "scripts/entry_sandbox.py"]
        for path in paths:
            original = path.read_bytes(); path.write_bytes(original + b"\n")
            try:
                with self.subTest(path=path), deny_execution(), self.assertRaises(ValueError):
                    inventory.inventory_bundle(directory)
            finally:
                path.write_bytes(original)
        path = directory / "result.json"
        original = path.read_bytes()
        for relative in ("request.json", "worker-result.json", "input.pdb", "worker.log"):
            parent = json.loads(original); del parent["retained_files"][relative]
            path.write_text(json.dumps(parent))
            with self.subTest(relative=relative), deny_execution(), self.assertRaises(ValueError):
                inventory.inventory_bundle(directory)
        parent = json.loads(original); parent["retained_files"]["../outside"] = "0" * 64
        path.write_text(json.dumps(parent))
        with deny_execution(), self.assertRaisesRegex(ValueError, "escapes"):
            inventory.inventory_bundle(directory)
        path.write_bytes(original)

    def test_mid_inventory_changes_refuse_not_repin(self):
        fixture, directory = self.make_bundle()
        worker = json.loads((directory / "worker-result.json").read_bytes())
        fake_source = fixture.root / "inventory-source.py"
        fake_source.write_text("# synthetic immutable sidecar source\n")
        paths = [directory / "input.pdb", Path(worker["h_model"]["path"]), directory / "result.json",
                 directory / "commands/01/stderr.bin", fixture.root / "scripts/standalone_reduce.py", fake_source]
        original_inventory = inventory.inventory_bytes
        for path in paths:
            original = path.read_bytes()
            def mutate(*args, **kwargs):
                result = original_inventory(*args, **kwargs)
                path.write_bytes(original + b"\n")
                return result
            try:
                with (self.subTest(path=path), deny_execution(),
                      mock.patch.object(inventory, "__file__", str(fake_source)),
                      mock.patch.object(inventory, "inventory_bytes", side_effect=mutate),
                      self.assertRaises(ValueError)):
                    inventory.inventory_bundle(directory)
            finally:
                path.write_bytes(original)

    def test_alias_resolves_same_entry_without_writes(self):
        fixture, directory = self.make_bundle()
        alias = fixture.root / "entry-alias"
        alias.symlink_to(directory, target_is_directory=True)
        with deny_execution():
            self.assertEqual(inventory.inventory_bundle(alias), inventory.inventory_bundle(directory))

    def assert_cli_refuses(self, directory):
        with deny_execution(), redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()) as error:
            self.assertEqual(inventory.main([str(directory)]), 1)
        self.assertEqual(output.getvalue(), "")
        self.assertIn("Inventory refused", error.getvalue())

    def test_worker_cleanup_identity_and_literal_types(self):
        _, directory = self.make_bundle()
        path = directory / "result.json"
        original = path.read_bytes()
        changes = [lambda x: x["process"].update(start_new_session=False),
                   lambda x: x["process"].update(start_new_session=1),
                   lambda x: x["process"].update(pid=987650),
                   lambda x: x["process"].update(pid=987650, pgid=987650,
                       cleanup={"pgid": 987650, "status": "group_absent", "group_absent_verified": True}),
                   lambda x: x["process"].update(arguments=["unrelated-program", "--unrelated-request"]),
                   lambda x: x["process"].update(pid=True),
                   lambda x: x["process"].update(pgid=False),
                   lambda x: x["process"].update(pid=0),
                   lambda x: x["process"].update(pgid=-1),
                   lambda x: x["process"].update(returncode=False),
                   lambda x: x["process"].update(timed_out=0),
                   lambda x: x["process"]["cleanup"].update(group_absent_verified=1),
                   lambda x: x["process"]["cleanup"].update(pgid=True)]
        for index, change in enumerate(changes):
            with self.subTest(case=index):
                parent = json.loads(original); change(parent); path.write_text(json.dumps(parent))
                self.assert_cli_refuses(directory)
        path.write_bytes(original)

    def test_coherently_repinned_launch_or_worker_start_still_must_bind(self):
        _, directory = self.make_bundle()
        parent_path, worker_path = directory / "result.json", directory / "worker-result.json"
        original_parent, original_worker = parent_path.read_bytes(), worker_path.read_bytes()
        changes = [("worker-start.json", lambda x: x.update(pid=987650, pgid=987650)),
                   ("worker-start.json", lambda x: x.update(pid=True, pgid=True)),
                   ("worker-start.json", lambda x: x.update(pgid=0)),
                   ("launch-request.json", lambda x: x.update(timeout_seconds=True)),
                   ("launch-request.json", lambda x: x.update(timeout_seconds=899)),
                   ("launch-request.json", lambda x: x["argv"].__setitem__(1, "-c")),
                   ("launch-request.json", lambda x: x["argv"].__setitem__(2, "/unrelated/worker.py")),
                   ("launch-request.json", lambda x: x["argv"].__setitem__(3, "--execute")),
                   ("launch-request.json", lambda x: x["argv"].__setitem__(4, str(directory / "launch-plan.json")))]
        for relative, change in changes:
            path = directory / relative
            original = path.read_bytes()
            try:
                document = json.loads(original); change(document); path.write_text(json.dumps(document))
                parent, worker = json.loads(original_parent), json.loads(original_worker)
                worker["evidence_files"][relative] = parent["retained_files"][relative] = driver.digest(path.read_bytes())
                if relative == "launch-request.json":
                    parent["process"]["arguments"] = document["argv"]
                worker_path.write_text(json.dumps(worker))
                parent["retained_files"]["worker-result.json"] = driver.digest(worker_path.read_bytes())
                parent_path.write_text(json.dumps(parent))
                with self.subTest(relative=relative, changed=document):
                    self.assert_cli_refuses(directory)
            finally:
                path.write_bytes(original); parent_path.write_bytes(original_parent); worker_path.write_bytes(original_worker)

    def test_public_subprocess_nonregular_artifacts_refuse_without_blocking(self):
        fixture, directory = self.make_bundle()
        worker = json.loads((directory / "worker-result.json").read_bytes())
        h_path = Path(worker["h_model"]["path"])
        paths = [directory / "result.json", directory / "commands/01/stderr.bin", directory / "input.pdb",
                 directory / "raw-user-mod.txt", h_path.parent / "manifest.json", fixture.prereg,
                 fixture.root / "scripts/standalone_reduce.py", fixture.model, fixture.dictionary]
        child = ("import sys; from test_inventory_standalone_components import deny_execution; "
                 "import inventory_standalone_components as i; "
                 "\nwith deny_execution(): raise SystemExit(i.main(sys.argv[1:]))")
        environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
                       "PYTHONPATH": os.pathsep.join(dict.fromkeys([str(Path(__file__).resolve().parent), *sys.path]))}
        for path in paths:
            original = path.read_bytes()
            for kind in ("fifo", "symlink", "directory"):
                target = path.with_name(path.name + ".regular-target")
                try:
                    path.unlink()
                    if kind == "fifo":
                        os.mkfifo(path)
                    elif kind == "symlink":
                        target.write_bytes(original); path.symlink_to(target)
                    else:
                        path.mkdir()
                    with self.subTest(path=path, kind=kind):
                        try:
                            process = subprocess.run([sys.executable, "-B", "-c", child, str(directory)],
                                                     capture_output=True, text=True, timeout=5, env=environment)
                        except subprocess.TimeoutExpired:
                            self.fail("Read-only inventory blocked on a non-regular artifact")
                        self.assertEqual(process.returncode, 1, process.stderr)
                        self.assertEqual(process.stdout, "")
                        self.assertIn("Inventory refused", process.stderr)
                finally:
                    if kind == "directory":
                        path.rmdir()
                    else:
                        path.unlink()
                    if target.exists():
                        target.unlink()
                    path.write_bytes(original)

    def test_no_follow_source_reads_inner_directory_alias_and_device(self):
        fixture, directory = self.make_bundle()
        for path in (fixture.root / "source.fifo", fixture.root / "source.link"):
            if path.suffix == ".fifo":
                os.mkfifo(path)
            else:
                path.symlink_to(fixture.prereg)
            for module in (inventory, driver, inventory.retained):
                with self.subTest(path=path, module=module.__name__), mock.patch.object(module, "__file__", str(path)):
                    self.assert_cli_refuses(directory)
        with self.assertRaisesRegex(ValueError, "Regular evidence file"):
            inventory.regular_bytes(Path("/dev/null"))
        real = directory / "commands/01"
        moved = directory / "commands/01-original"
        real.rename(moved); real.symlink_to(moved, target_is_directory=True)
        try:
            self.assert_cli_refuses(directory)
        finally:
            real.unlink(); moved.rename(real)

    def test_mid_inventory_nonregular_replacements_are_rejected(self):
        fixture, directory = self.make_bundle()
        original_inventory = inventory.inventory_bytes
        for path in (directory / "raw-user-mod.txt", directory / "result.json", fixture.prereg,
                     fixture.root / "scripts/standalone_reduce.py"):
            original = path.read_bytes()
            target = path.with_name(path.name + ".target")
            def mutate(*args, **kwargs):
                result = original_inventory(*args, **kwargs)
                target.write_bytes(original); path.unlink(); path.symlink_to(target)
                return result
            try:
                with self.subTest(path=path), mock.patch.object(inventory, "inventory_bytes", side_effect=mutate):
                    self.assert_cli_refuses(directory)
            finally:
                path.unlink(); target.unlink(); path.write_bytes(original)

    def test_injected_reader_covers_all_admission_reads(self):
        _, directory = self.make_bundle()
        parent = json.loads((directory / "result.json").read_bytes())
        request = json.loads((directory / "request.json").read_bytes())
        worker = json.loads((directory / "worker-result.json").read_bytes())
        calls = []
        def reader(path):
            calls.append(Path(path))
            return inventory.regular_bytes(path)
        # A new direct Path read inside either helper must fail this test.
        with deny_execution(), mock.patch.object(Path, "read_bytes", side_effect=AssertionError("uninjected bytes")), \
                mock.patch.object(Path, "read_text", side_effect=AssertionError("uninjected text")):
            driver.admit_evidence(request, directory, worker, read_bytes=reader)
            inventory.retained.checked_inventory(directory, parent["retained_files"], read_bytes=reader)
        self.assertIn(directory / "raw-user-mod.txt", calls)
        self.assertIn(Path(worker["h_model"]["path"]), calls)
        self.assertTrue(all(directory / name in calls for name in parent["retained_files"]))


if __name__ == "__main__":
    unittest.main()
