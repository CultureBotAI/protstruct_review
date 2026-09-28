"""Hermetic regressions for dictionary-bound Reduce evidence (#799, #807)."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import bench_t05_clashscore_h as t05
import bench_t14_flip_sets as t14
import standalone_reduce as reduce
import toolchain


PDB = "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 20.00           C  \n"


def contact(kind="bo", gap="-0.5", source=" A  46 GLY  HA3 "):
    """Probe 2.26 writeRaw shape, based on a retained -u -q contact row."""
    return ":".join(["", "1->2", kind, source, " A  85 GLY  C   ", gap,
                     "0.269", "53.311", "-20.358", "-26.137", "0.000", "0.0196",
                     "C", "C", "53.311", "-20.358", "-26.137", "61.91", "65.95"]) + "\n"


class ReduceEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="reduce evidence ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.model = self.root / "input.pdb"
        self.binary = self.root / "reduce fake"
        self.dictionary = self.root / "het dictionary.txt"
        self.model.write_text(PDB)
        self.binary.write_text("fake binary identity")
        self.dictionary.write_text("fake dictionary identity")
        self.work = self.root / "cache"
        self.work.mkdir()
        self.stderr = "diagnostic retained\n"
        self.stdout = PDB
        self.returncode = 0
        self.calls = []
        for name, path in [("REDUCE", self.binary), ("REDUCE_HET_DICT", self.dictionary)]:
            patcher = mock.patch.object(toolchain, name, path)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(toolchain, "run_to_file", side_effect=self.run_fake)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_fake(self, arguments, output, **kwargs):
        self.calls.append(arguments)
        Path(output).write_text(self.stdout)
        if hasattr(kwargs.get("stderr"), "write"):
            kwargs["stderr"].write(self.stderr)
        return subprocess.CompletedProcess(arguments, self.returncode)

    def build(self, **kwargs):
        return reduce.build_hydrogens(self.model, self.work, **kwargs)

    def test_explicit_dictionary_and_reusable_bound_evidence(self):
        out = self.build()
        manifest = json.loads((out.parent / "manifest.json").read_text())
        args = self.calls[0]
        self.assertEqual(args[args.index("-DB") + 1], str(self.dictionary.resolve()))
        self.assertEqual((out.parent / "stderr.log").read_text(), self.stderr)
        self.assertEqual(manifest["invocation"]["inputs"]["dictionary"]["sha256"],
                         reduce._sha256(self.dictionary))
        self.assertEqual(self.build(), out)
        self.assertEqual(len(self.calls), 1)

    def test_legacy_bare_cache_is_not_reused_or_overwritten(self):
        old = self.work / "input_h_ec.pdb"
        old.write_text("historical no-dictionary output")
        self.assertNotEqual(self.build(), old)
        self.assertEqual(old.read_text(), "historical no-dictionary output")
        self.assertEqual(len(self.calls), 1)

    def test_aliases_reuse_one_canonical_output(self):
        first = self.root / "alias_a.pdb"
        second = self.root / "alias_b.pdb"
        first.symlink_to(self.model)
        second.symlink_to(self.model)
        out = reduce.build_hydrogens(first, self.work)
        self.assertEqual(reduce.build_hydrogens(second, self.work), out)
        self.assertEqual(len(self.calls), 1)

    def test_input_dictionary_binary_and_convention_separate_caches(self):
        paths = [self.build()]
        for source in [self.model, self.dictionary, self.binary]:
            source.write_text(source.read_text() + "changed\n")
            paths.append(self.build())
        paths.append(self.build(nuclear=True))
        self.assertEqual(len(set(paths)), 5)
        self.assertEqual(len(self.calls), 5)
        self.assertIn("-nuclear", self.calls[-1])

    def test_missing_dictionary_fails_before_execution(self):
        self.dictionary.unlink()
        with self.assertRaises(FileNotFoundError):
            self.build()
        self.assertEqual(self.calls, [])

    def test_empty_dictionary_fails_before_execution(self):
        self.dictionary.write_text("")
        with self.assertRaisesRegex(ValueError, "nonempty"):
            self.build()
        self.assertEqual(self.calls, [])

    def test_zero_exit_dictionary_error_never_publishes_a_cache(self):
        self.stderr = "ERROR CTab(het): could not open\n"
        with self.assertRaisesRegex(RuntimeError, "retained stderr"):
            self.build()
        attempts = list((self.work / "reduce_dictionary_v1").iterdir())
        self.assertEqual(len(attempts), 1)
        self.assertTrue(attempts[0].name.startswith("."))
        self.assertEqual((attempts[0] / "stderr.log").read_text(), self.stderr)
        self.assertFalse((attempts[0] / "manifest.json").exists())
        self.stderr = "now successful"
        self.build()
        self.assertEqual(len(self.calls), 2)

    def test_nonzero_exit_with_plausible_coordinates_is_refused(self):
        self.returncode = 2
        with self.assertRaisesRegex(RuntimeError, "exit 2"):
            self.build()

    def test_no_coordinate_output_is_refused(self):
        self.stdout = "REMARK incomplete\n"
        with self.assertRaisesRegex(RuntimeError, "no coordinate"):
            self.build()

    def test_changed_input_during_execution_is_refused(self):
        original = self.run_fake

        def change_source(*args, **kwargs):
            result = original(*args, **kwargs)
            self.dictionary.write_text("changed mid-run")
            return result

        with mock.patch.object(toolchain, "run_to_file", side_effect=change_source):
            with self.assertRaisesRegex(RuntimeError, "changed during"):
                self.build()

    def test_corrupt_output_is_refused_without_overwrite(self):
        out = self.build()
        out.write_text("tampered")
        with self.assertRaisesRegex(RuntimeError, "Invalid Reduce cache"):
            self.build()
        self.assertEqual(out.read_text(), "tampered")
        self.assertEqual(len(self.calls), 1)

    def test_corrupt_stderr_is_refused(self):
        out = self.build()
        (out.parent / "stderr.log").write_text("tampered")
        with self.assertRaisesRegex(RuntimeError, "Invalid Reduce cache"):
            self.build()

    def test_missing_manifest_is_refused(self):
        out = self.build()
        (out.parent / "manifest.json").unlink()
        with self.assertRaisesRegex(RuntimeError, "Invalid Reduce cache"):
            self.build()

    def test_both_benchmarks_use_dictionary_bound_runner(self):
        out = t05.run_reduce(self.model, self.work, nuclear=False)
        with mock.patch.object(t14, "phenix_executable", side_effect=AssertionError("not allowed")):
            self.assertEqual(t14.build(self.model, self.work, phenix=False), out)
        self.assertEqual(len(self.calls), 1)


class ProbeEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="probe evidence ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.model = self.root / "input.pdb"
        self.binary = self.root / "probe fake"
        self.model.write_text(PDB)
        self.binary.write_text("fake probe binary")
        self.calls = []
        self.stdout, self.stderr, self.returncode = "", "", 0
        for patcher in [mock.patch.object(t05, "PROBE", self.binary),
                        mock.patch.object(t05, "run_to_file", side_effect=self.run_fake)]:
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_fake(self, arguments, output, **kwargs):
        self.calls.append(arguments)
        Path(output).write_text(self.stdout)
        if hasattr(kwargs.get("stderr"), "write"):
            kwargs["stderr"].write(self.stderr)
        return subprocess.CompletedProcess(arguments, self.returncode)

    def test_failed_empty_probe_cannot_become_zero_clashes(self):
        self.returncode = 1
        with self.assertRaisesRegex(RuntimeError, "Probe failed"):
            t05.run_probe_clashscore(self.model, self.root)
        logs = list(self.root.glob("probe_evidence_*/manifest.json"))
        self.assertEqual(len(logs), 1)
        self.assertEqual(json.loads(logs[0].read_text())["returncode"], 1)

    def test_failed_plausible_probe_cannot_become_a_score(self):
        self.returncode = 1
        self.stdout = contact()
        with self.assertRaisesRegex(RuntimeError, "Probe failed"):
            t05.run_probe_clashscore(self.model, self.root)

    def test_error_stderr_is_not_ignored_on_zero_exit(self):
        self.stderr = "ERROR: cannot load model\n"
        with self.assertRaisesRegex(RuntimeError, "Probe failed"):
            t05.run_probe_clashscore(self.model, self.root)
        logs = list(self.root.glob("probe_evidence_*/stderr.log"))
        self.assertEqual(logs[0].read_text(), self.stderr)

    def test_successful_zero_clashes_and_bound_evidence(self):
        evidence = {}
        self.assertEqual(t05.run_probe_clashscore(self.model, self.root, evidence), 0.0)
        manifest = json.loads(Path(evidence["manifest"]).read_text())
        self.assertEqual(manifest["returncode"], 0)
        self.assertEqual(manifest["model_sha256"], reduce._sha256(self.model))
        self.assertEqual(manifest["executable_sha256"], reduce._sha256(self.binary))

    def test_old_empty_cache_is_neither_reused_nor_overwritten(self):
        old = self.root / "probe_input.txt"
        old.write_text("")
        self.stdout = contact()
        self.assertEqual(t05.run_probe_clashscore(self.model, self.root), 1000.0)
        self.assertEqual(old.read_text(), "")
        self.assertEqual(len(self.calls), 1)

    def test_changed_probe_and_repeat_calls_reexecute_with_new_evidence(self):
        first, second = {}, {}
        t05.run_probe_clashscore(self.model, self.root, first)
        self.binary.write_text("changed probe")
        t05.run_probe_clashscore(self.model, self.root, second)
        a, b = [json.loads(Path(row["manifest"]).read_text()) for row in (first, second)]
        self.assertNotEqual(a["executable_sha256"], b["executable_sha256"])
        self.assertNotEqual(first["manifest"], second["manifest"])
        self.assertEqual(len(self.calls), 2)

    def test_unrecognized_output_and_missing_atom_ids_are_not_scores(self):
        for output in ["Usage: probe [options] input.pdb\n", contact(kind="BO"),
                       contact(source=""), "name:pat:bo::-0.5:-0.5:-0.5\n"]:
            with self.subTest(output=output):
                self.stdout = output
                evidence = {}
                with self.assertRaisesRegex(RuntimeError, "Malformed Probe contact"):
                    t05.run_probe_clashscore(self.model, self.root, evidence)
                self.assertEqual(evidence, {})

    def test_valid_nonclash_contact_types_are_zero(self):
        self.stdout = "".join(contact(kind=kind) for kind in ["wc", "cc", "wh", "so", "hb"])
        self.assertEqual(t05.run_probe_clashscore(self.model, self.root), 0.0)

    def test_retained_score_records_pairs_and_denominator(self):
        self.stdout = contact() + contact(kind="wo")
        evidence = {}
        self.assertEqual(t05.run_probe_clashscore(self.model, self.root, evidence), 1000.0)
        manifest = json.loads(Path(evidence["manifest"]).read_text())
        self.assertEqual(manifest["score_status"], "measured")
        self.assertEqual(manifest["clash_pair_count"], 1)
        self.assertEqual(manifest["atom_count"], 1)
        self.assertEqual(len(manifest["clash_pairs"]), 1)

    def test_invalid_overlap_never_becomes_a_zero_score(self):
        for value in ["nan", "inf", "not-a-number"]:
            with self.subTest(value=value):
                self.stdout = contact(gap=value)
                with self.assertRaisesRegex(RuntimeError, "Probe overlap"):
                    t05.run_probe_clashscore(self.model, self.root)
        self.stdout = "name:pat:bo\n"
        with self.assertRaisesRegex(RuntimeError, "Malformed Probe contact"):
            t05.run_probe_clashscore(self.model, self.root)


if __name__ == "__main__":
    unittest.main()
