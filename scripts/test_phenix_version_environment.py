#!/usr/bin/env python3
"""Hermetic #816 tests; fake version dispatchers, never licensed executables."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import toolchain


class PhenixVersionEnvironmentTests(unittest.TestCase):
    def test_every_adapter_distinguishes_empty_environment_from_none(self) -> None:
        with tempfile.TemporaryDirectory(prefix="empty-subprocess-env-") as temporary:
            destination = Path(temporary) / "stdout.txt"
            adapters = (
                (toolchain.run_capture, ([sys.executable, "--version"],)),
                (toolchain.run_logged, ([sys.executable, "--version"], destination)),
                (toolchain.run_to_file, ([sys.executable, "--version"], destination)),
            )
            for adapter, arguments in adapters:
                for supplied in (None, {}, {"KEEP": "value"}):
                    with self.subTest(adapter=adapter.__name__, supplied=supplied), patch.object(
                        toolchain.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)
                    ) as execute:
                        adapter(*arguments, env=supplied)
                        self.assertEqual(execute.call_args.kwargs["env"], supplied)

    def test_build_probe_can_pass_an_empty_sanitized_environment(self) -> None:
        given = {"PHENIX_VERSION": "2.0", "PHENIX_RELEASE_TAG": "5936"}
        with patch.dict(os.environ, given, clear=True), patch.object(toolchain, "PHENIX_BIN", self.root), \
                patch.object(toolchain.subprocess, "run", return_value=subprocess.CompletedProcess(
                    [], 0, "PHENIX 2.1-7000\n", ""
                )) as execute:
            report = toolchain.phenix_build_evidence()
            self.assertEqual(execute.call_args.kwargs["env"], {})
            self.assertEqual(report["reported_version"], "PHENIX 2.1-7000")
            self.assertEqual(dict(os.environ), given)

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="phenix-env-guard-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.dispatcher = self.root / "phenix.version"
        # Match the relevant vendor behavior: environment overrides installation TAG.
        self.dispatcher.write_text(
            f"#!{sys.executable}\n"
            "import os\n"
            "version = os.environ.get('PHENIX_VERSION', '2.1-7000')\n"
            "tag = os.environ.get('PHENIX_RELEASE_TAG')\n"
            "assert os.environ.get('PROTSTRUCT_TEST_KEEP') == 'preserved'\n"
            "print('Phenix: test-only version dispatcher')\n"
            "print('Version: ' + version)\n"
            "if tag is not None: print('Release tag: ' + tag)\n"
        )
        self.dispatcher.chmod(0o755)

    def test_environment_copy_strips_only_banner_overrides(self) -> None:
        given = {"PHENIX_VERSION": "2.0", "PHENIX_RELEASE_TAG": "5936",
                 "PATH": "/preserve/path", "KEEP": "yes"}
        with patch.dict(os.environ, given, clear=True):
            clean = toolchain.phenix_version_environment()
            self.assertEqual(clean, {"PATH": "/preserve/path", "KEEP": "yes"})
            self.assertEqual(dict(os.environ), given)
            clean["KEEP"] = "changed"
            self.assertEqual(os.environ["KEEP"], "yes")

    def test_build_probe_uses_installation_not_inherited_banner(self) -> None:
        overrides = (
            {}, {"PHENIX_VERSION": "2.0-5936"},
            {"PHENIX_RELEASE_TAG": "5936"},
            {"PHENIX_VERSION": "2.0", "PHENIX_RELEASE_TAG": "5936"},
        )
        for inherited in overrides:
            given = {**inherited, "PROTSTRUCT_TEST_KEEP": "preserved"}
            with self.subTest(inherited=inherited), patch.dict(os.environ, given, clear=True), \
                    patch.object(toolchain, "PHENIX_BIN", self.root):
                report = toolchain.phenix_build_evidence()
                self.assertEqual(toolchain.parse_phenix_build(report["reported_version"]), "2.1-7000")
                self.assertEqual(report["reported_version_source"], "command_output")
                self.assertEqual(report["version_probe"]["returncode"], 0)
                self.assertEqual(report["version_probe"]["ignored_inherited_version_variables"], sorted(inherited))
                self.assertEqual(dict(os.environ), given)

    def test_external_report_strips_only_for_phenix(self) -> None:
        specification = {
            "expected_version": "2.1-7000", "configured_path": self.root,
            "executables": ("phenix.version",), "version_args": (),
        }
        given = {"PHENIX_VERSION": "2.0", "PHENIX_RELEASE_TAG": "5936",
                 "PROTSTRUCT_TEST_KEEP": "preserved"}
        with patch.dict(os.environ, given, clear=True), patch.object(
            toolchain, "EXTERNAL_TOOL_SPECS", {"PHENIX": specification, "unrelated": specification}
        ):
            report = toolchain.external_tool_report()
            self.assertIn("Version: 2.1-7000", report["PHENIX"]["reported_version"])
            self.assertFalse(report["PHENIX"]["version_divergence"])
            self.assertIn("Version: 2.0", report["unrelated"]["reported_version"])
            self.assertIn("Release tag: 5936", report["unrelated"]["reported_version"])
            self.assertEqual(dict(os.environ), given)


if __name__ == "__main__":
    unittest.main()
