"""Hermetic cache regressions: every external execution is a Python callback."""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from refinement_cache import CacheEvidenceError, OutputTemplate, cached_operation


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cache777-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.model, self.data, self.launcher = [self.root / name for name in ("model.pdb", "data.map", "phenix.fake")]
        for path in (self.model, self.data, self.launcher):
            path.write_text(path.name + " original bytes\n")
        self.build = {"reported_version_source": "command_output", "reported_version": "PHENIX 2.0-5936"}
        self.calls = []
        self.code = 0
        self.outputs = {"model.cif": "coordinates", "fsc_model.masked.mtriage.log": "0.1 0.5\n"}
        self.options = [str(self.model), str(self.data), "resolution=3.2000001",
                        OutputTemplate("output.prefix={operation_dir}/model")]

    def execute(self, argv, work, log):
        self.calls.append((argv, work))
        log.write_text("process log\n")
        for name, value in self.outputs.items():
            (work / name).write_text(value)
        return self.code

    def run_op(self, **changes):
        kwargs = dict(inputs={"model": self.model, "data": self.data}, launcher=self.launcher,
                      measured_build=self.build, arguments=self.options,
                      required_outputs={"model": "model*.cif", "curve": "fsc_model.masked.mtriage.log"},
                      execute=self.execute)
        kwargs.update(changes)
        return cached_operation(self.root / "work", "em", **kwargs)

    def test_identical_invocation_reuses_verified_artifacts(self):
        first = self.run_op()
        self.assertEqual(first, self.run_op())
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(first["curve"].read_text(), self.outputs["fsc_model.masked.mtriage.log"])

    def test_execution_metadata_corruption_is_refused_without_rerun(self):
        first = self.run_op()
        original = json.loads(first["manifest"].read_text())
        mutations = [
            {"executed_argv": ["/wrong-build/refine", "/wrong/model", "resolution=99"]},
            {"executed_argv": None}, {"execution_directory": None},
            {"execution_directory": "/different/attempt"},
            {"execution_directory": original["execution_directory"] + "/../elsewhere"},
        ]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                payload = {**original, **mutation}
                first["manifest"].write_text(json.dumps(payload))
                with self.assertRaises(CacheEvidenceError):
                    self.run_op()
                self.assertEqual(len(self.calls), 1)
                self.assertEqual(json.loads(first["manifest"].read_text()), payload)
        for key in ("executed_argv", "execution_directory"):
            payload = {k: v for k, v in original.items() if k != key}
            first["manifest"].write_text(json.dumps(payload))
            with self.assertRaises(CacheEvidenceError):
                self.run_op()

    def test_original_invocation_evidence_is_required_and_consistent(self):
        first = self.run_op()
        original = first["model"].parent / "invocation.json"
        original.write_text('{}')
        with self.assertRaises(CacheEvidenceError):
            self.run_op()
        original.unlink()
        with self.assertRaises(CacheEvidenceError):
            self.run_op()
        self.assertEqual(len(self.calls), 1)

    def test_every_input_byte_change_separates_operation(self):
        seen = [self.run_op()["model"]]
        for path in (self.model, self.data, self.launcher):
            path.write_text(path.read_text() + "updated")
            seen.append(self.run_op()["model"])
        self.assertEqual(len(set(seen)), 4)

    def test_exact_resolution_and_options_and_build_separate_operations(self):
        seen = [self.run_op()["model"]]
        self.options[2] = "resolution=3.2000002"
        seen.append(self.run_op()["model"])
        self.options.append("main.number_of_macro_cycles=8")
        seen.append(self.run_op()["model"])
        self.build["reported_version"] = "PHENIX 2.0-9999"
        seen.append(self.run_op()["model"])
        self.assertEqual(len(set(seen)), 4)

    def test_measured_record_sequence_is_normalized_to_json(self):
        self.build["version_argv"] = ("phenix.version",)
        self.assertEqual(self.run_op(), self.run_op())
        self.assertEqual(len(self.calls), 1)

    def test_literal_operation_dir_in_model_and_options_is_preserved(self):
        literal_model = self.root / "literal-{operation_dir}.pdb"
        literal_model.write_text("literal path model bytes\n")
        arguments = [literal_model, str(literal_model), "literal={operation_dir}",
                     OutputTemplate("output.prefix={operation_dir}/model")]
        first = self.run_op(inputs={"model": literal_model, "data": self.data}, arguments=arguments)
        argv, operation_dir = self.calls[0]
        self.assertEqual(argv[1], str(literal_model.resolve()))
        self.assertEqual(argv[2], str(literal_model))
        self.assertEqual(argv[3], "literal={operation_dir}")
        self.assertEqual(argv[4], f"output.prefix={operation_dir}/model")
        self.assertEqual(first, self.run_op(inputs={"model": literal_model, "data": self.data},
                                           arguments=arguments))
        self.assertEqual(len(self.calls), 1)

    def test_literal_and_output_template_are_distinct_invocation_identities(self):
        literal = self.run_op(arguments=["output.prefix={operation_dir}/model"])
        templated = self.run_op(arguments=[OutputTemplate("output.prefix={operation_dir}/model")])
        self.assertNotEqual(literal["model"], templated["model"])
        self.assertEqual(self.calls[0][0][1], "output.prefix={operation_dir}/model")
        self.assertNotIn("{operation_dir}", self.calls[1][0][1])

    def test_model_symlink_aliases_have_stable_input_identity(self):
        alias = self.root / "alias.pdb"
        alias.symlink_to(self.model)
        first = self.run_op()
        second = self.run_op(inputs={"model": alias, "data": self.data})
        self.assertEqual(first, second)

    def test_configured_launcher_alias_is_recorded(self):
        alias = self.root / "launcher-alias"
        alias.symlink_to(self.launcher)
        self.assertNotEqual(self.run_op()["model"], self.run_op(launcher=alias)["model"])

    def test_unknown_and_path_hint_builds_never_reuse(self):
        for evidence in ({}, {"reported_version_source": "configured_path_version_hint", "reported_version": "2.0-5936"},
                         {"reported_version_source": "command_output", "reported_version": "unknown"}):
            self.assertNotEqual(self.run_op(measured_build=evidence)["model"],
                                self.run_op(measured_build=evidence)["model"])
        self.assertEqual(len(self.calls), 6)
        self.assertFalse(list(self.root.rglob("success.json")))

    def test_legacy_outputs_neither_reused_nor_overwritten(self):
        legacy = self.root / "work" / "model.cif"
        legacy.parent.mkdir()
        legacy.write_text("legacy coordinates")
        self.assertNotEqual(self.run_op()["model"], legacy)
        self.assertEqual(legacy.read_text(), "legacy coordinates")

    def test_corrupt_or_missing_artifacts_refused_without_execution(self):
        for name in ("model", "curve", "stdout"):
            with self.subTest(name=name):
                self.options.append("case=" + name)
                paths = self.run_op()
                count = len(self.calls)
                paths[name].write_text("tampered")
                with self.assertRaises(CacheEvidenceError):
                    self.run_op()
                self.assertEqual(len(self.calls), count)
                self.assertEqual(paths[name].read_text(), "tampered")

    def test_incomplete_or_corrupt_manifest_refused(self):
        paths = self.run_op()
        manifest = paths["model"].parent / "success.json"
        manifest.write_text("{")
        with self.assertRaises(CacheEvidenceError):
            self.run_op()
        self.assertEqual(len(self.calls), 1)

    def test_failed_status_cannot_be_reused(self):
        paths = self.run_op()
        record = json.loads(paths["manifest"].read_text())
        record["returncode"] = 1
        paths["manifest"].write_text(json.dumps(record))
        with self.assertRaises(CacheEvidenceError):
            self.run_op()
        self.assertEqual(len(self.calls), 1)

    def test_incomplete_directory_cannot_be_reused(self):
        paths = self.run_op()
        paths["manifest"].unlink()
        with self.assertRaises(CacheEvidenceError):
            self.run_op()
        self.assertEqual(len(self.calls), 1)

    def test_unknown_build_manifest_is_explicitly_not_reusable(self):
        paths = self.run_op(measured_build={})
        self.assertFalse(json.loads(paths["manifest"].read_text())["reusable"])
        self.assertEqual(paths["manifest"].name, "uncached_success.json")

    def test_missing_output_and_nonzero_exit_cannot_publish_success(self):
        self.outputs.pop("model.cif")
        with self.assertRaises(CacheEvidenceError):
            self.run_op()
        self.outputs["model.cif"] = "plausible partial"
        self.code = 1
        with self.assertRaises(CacheEvidenceError):
            self.run_op()
        self.assertFalse(list(self.root.rglob("success.json")))
        self.code = 0
        self.run_op()
        self.assertEqual(len(self.calls), 3)

    def test_multiple_candidates_fail_closed(self):
        self.outputs["model_extra.cif"] = "ambiguous"
        with self.assertRaises(CacheEvidenceError):
            self.run_op()

    def test_missing_stdout_refuses_success(self):
        def missing_log(argv, work, log):
            result = self.execute(argv, work, log)
            log.unlink()
            return result
        with self.assertRaises(CacheEvidenceError):
            self.run_op(execute=missing_log)

    def test_output_symlink_cannot_authenticate_an_outside_artifact(self):
        def linked_output(argv, work, log):
            result = self.execute(argv, work, log)
            output = work / "model.cif"
            output.unlink()
            output.symlink_to(self.model)
            return result
        with self.assertRaises(CacheEvidenceError):
            self.run_op(execute=linked_output)

    def test_inputs_changed_during_execution_fail_closed(self):
        def change(argv, work, log):
            result = self.execute(argv, work, log)
            self.data.write_text("changed during process")
            return result
        with self.assertRaises(CacheEvidenceError):
            self.run_op(execute=change)
        self.assertFalse(list(self.root.rglob("success.json")))

    def test_timeout_preserves_identity_without_success(self):
        def timeout(argv, work, log):
            self.execute(argv, work, log)
            raise subprocess.TimeoutExpired(argv, 1)
        with self.assertRaises(subprocess.TimeoutExpired):
            self.run_op(execute=timeout)
        self.assertEqual(len(list(self.root.rglob("invocation.json"))), 1)
        self.assertFalse(list(self.root.rglob("success.json")))

    def test_manifest_records_real_argv_and_all_artifact_hashes(self):
        paths = self.run_op()
        record = json.loads((paths["model"].parent / "success.json").read_text())
        self.assertEqual(record["executed_argv"], self.calls[0][0])
        self.assertNotIn("{operation_dir}", " ".join(record["executed_argv"]))
        self.assertEqual(set(record["artifacts"]), {"model", "curve", "stdout"})

    def test_output_patterns_cannot_escape_operation(self):
        for pattern in ("../old.pdb", "/tmp/old.pdb", ""):
            with self.assertRaises(ValueError):
                self.run_op(required_outputs={"model": pattern})
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
