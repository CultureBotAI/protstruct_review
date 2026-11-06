#!/usr/bin/env python3
"""Hermetic #954 tests for configured-install PHENIX vendor setup identity."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from refinement_cache import (
    CacheEvidenceError,
    OutputTemplate,
    _build_is_measured,
    cached_operation,
    cached_phenix_operation,
    sha256,
)
import toolchain


EXACT_023_BARE_BANNER = (
    "-------------------------------------------------------------------------------\n"
    "  Phenix: Python-based Hierarchical ENvironment for Integrated Xtallography\n"
    "  User: marcin\n"
    "-------------------------------------------------------------------------------\n\n"
)

VALID_VENDOR_BANNER = (
    "-------------------------------------------------------------------------------\n"
    "  Phenix: Python-based Hierarchical ENvironment for Integrated Xtallography\n"
    "  Version: 2.0\n"
    "  Release tag: 5936\n"
    "  User: marcin\n"
    "-------------------------------------------------------------------------------\n\n"
)


def _write_fake_dispatcher(path: Path) -> None:
    """Create a synthetic phenix.version matching phenix_info.py's env/TAG behavior."""
    path.write_text(
        f"#!{sys.executable}\n"
        "import os\n"
        "rule = '-' * 79\n"
        "title = 'Phenix: Python-based Hierarchical ENvironment for Integrated Xtallography'\n"
        "version = os.environ.get('PHENIX_VERSION')\n"
        "release_tag = os.environ.get('PHENIX_RELEASE_TAG')\n"
        "if version is not None and release_tag is None and '-' in version:\n"
        "    version, release_tag = version.split('-', 1)\n"
        "print(rule)\n"
        "print('  ' + title)\n"
        "if version is not None:\n"
        "    print('  Version: ' + version)\n"
        "if release_tag is not None:\n"
        "    print('  Release tag: ' + release_tag)\n"
        "print('  User: marcin')\n"
        "print(rule)\n"
        "print()\n"
    )
    path.chmod(0o755)


class PhenixVendorSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="phenix-954-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.prefix = self.root / "phenix-2.0-5936"
        self.phenix_bin = self.prefix / "phenix_bin"
        self.internal_bin = self.prefix / "bin"
        self.phenix_bin.mkdir(parents=True)
        self.internal_bin.mkdir(parents=True)
        self.setup_file = self.prefix / "phenix_env.sh"
        self.setup_file.write_text(
            "#!/usr/bin/env bash\n"
            f"export PHENIX={self.prefix}\n"
            f"export PHENIX_PREFIX={self.prefix}\n"
            "export PHENIX_VERSION=2.0-5936\n"
            f"export PATH={self.phenix_bin}:$PATH\n"
        )
        self.real_dispatcher = self.internal_bin / "phenix.version"
        _write_fake_dispatcher(self.real_dispatcher)
        self.configured_dispatcher = self.phenix_bin / "phenix.version"
        self.configured_dispatcher.symlink_to("../bin/phenix.version")

        self.fake_refine = self.internal_bin / "phenix.refine"
        self.fake_refine.write_text("#!/bin/sh\nexit 0\n")
        self.fake_refine.chmod(0o755)
        (self.phenix_bin / "phenix.refine").symlink_to("../bin/phenix.refine")

        self.model = self.root / "model.pdb"
        self.data = self.root / "data.mtz"
        self.model.write_text("ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00 10.00           N\n")
        self.data.write_text("MTZ synthetic bytes\n")
        self.work = self.root / "work"
        self.work.mkdir()
        self.calls: list[tuple[list[str], Path]] = []

        patcher = mock.patch.object(toolchain, "PHENIX_BIN", self.phenix_bin)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _runner(self, argv, log, *, cwd, timeout):
        self.calls.append((list(argv), Path(cwd)))
        Path(log).write_text("synthetic refinement log\n")
        (Path(cwd) / "refined_001.pdb").write_text("refined coordinates\n")
        return subprocess.CompletedProcess(argv, 0)

    def _run_cached(self) -> dict[str, Path]:
        return cached_phenix_operation(
            self.work,
            "xray-refine",
            executable="phenix.refine",
            inputs={"model": self.model, "data": self.data},
            arguments=[
                self.model,
                self.data,
                OutputTemplate("output.prefix={operation_dir}/refined"),
            ],
            required_outputs={"model": "refined_001.pdb"},
            timeout=10,
            runner=self._runner,
        )

    def test_exact_023_empty_field_banner_stays_unknown_and_non_reusable(self) -> None:
        self.assertIsNone(toolchain.parse_phenix_build(EXACT_023_BARE_BANNER))
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("PHENIX_VERSION", None)
            os.environ.pop("PHENIX_RELEASE_TAG", None)
            bare = toolchain.phenix_bare_build_evidence()
        self.assertIsNone(bare["reported_version_source"])
        self.assertIsNone(bare["reported_version"])
        self.assertIsNone(bare["parsed_build"])
        self.assertEqual(bare["version_probe"]["stdout"], EXACT_023_BARE_BANNER)
        self.assertEqual(bare["version_probe"]["returncode"], 0)
        self.assertIsNone(bare["version_probe"]["parsed_build"])
        self.assertFalse(_build_is_measured(bare))
        self.assertFalse(
            _build_is_measured(
                {
                    "reported_version_source": "command_output",
                    "reported_version": EXACT_023_BARE_BANNER.strip(),
                }
            )
        )
        first = cached_operation(
            self.work,
            "bare-023",
            inputs={"model": self.model, "data": self.data},
            launcher=self.phenix_bin / "phenix.refine",
            measured_build=bare,
            arguments=[self.model],
            required_outputs={"model": "refined_001.pdb"},
            execute=lambda argv, cwd, log: self._runner(argv, log, cwd=cwd, timeout=10).returncode,
        )
        second = cached_operation(
            self.work,
            "bare-023",
            inputs={"model": self.model, "data": self.data},
            launcher=self.phenix_bin / "phenix.refine",
            measured_build=bare,
            arguments=[self.model],
            required_outputs={"model": "refined_001.pdb"},
            execute=lambda argv, cwd, log: self._runner(argv, log, cwd=cwd, timeout=10).returncode,
        )
        self.assertNotEqual(first["model"], second["model"])
        self.assertEqual(first["manifest"].name, "uncached_success.json")
        self.assertFalse(json.loads(first["manifest"].read_text())["reusable"])

    def test_installed_phenix_bin_to_bin_layout_and_vendor_setup_accepted(self) -> None:
        evidence = toolchain.phenix_build_evidence()
        self.assertEqual(evidence["reported_version_source"], "vendor_setup_environment")
        self.assertEqual(evidence["parsed_build"], "2.0-5936")
        self.assertEqual(evidence["reported_version"], VALID_VENDOR_BANNER.strip())
        probe = evidence["version_probe"]
        self.assertEqual(probe["probe_mode"], "vendor_setup_environment")
        self.assertEqual(probe["configured_prefix"], str(self.prefix))
        self.assertEqual(probe["resolved_prefix"], str(self.prefix.resolve()))
        self.assertEqual(probe["setup_configured_path"], str(self.setup_file))
        self.assertEqual(probe["setup_resolved_path"], str(self.setup_file.resolve()))
        self.assertEqual(probe["setup_sha256"], sha256(self.setup_file.resolve()))
        self.assertEqual(
            probe["setup_argv"],
            toolchain.phenix_setup_argv(self.setup_file.resolve()),
        )
        self.assertEqual(probe["setup_returncode"], 0)
        self.assertEqual(probe["setup_stdout"], "")
        self.assertEqual(probe["setup_stderr"], "")
        self.assertEqual(
            probe["setup_version_fields"],
            {"PHENIX_VERSION": "2.0-5936", "PHENIX_RELEASE_TAG": None},
        )
        self.assertEqual(probe["setup_parsed_build"], "2.0-5936")
        self.assertEqual(probe["configured_path"], str(self.configured_dispatcher))
        self.assertEqual(probe["resolved_path"], str(self.real_dispatcher.resolve()))
        self.assertEqual(probe["sha256"], sha256(self.real_dispatcher.resolve()))
        self.assertEqual(probe["argv"], [str(self.real_dispatcher.resolve())])
        self.assertEqual(probe["returncode"], 0)
        self.assertEqual(probe["stdout"], VALID_VENDOR_BANNER)
        self.assertEqual(probe["stderr"], "")
        self.assertEqual(probe["parsed_build"], "2.0-5936")
        self.assertTrue(_build_is_measured(evidence))

        first = self._run_cached()
        second = self._run_cached()
        self.assertEqual(first, second)
        self.assertEqual(len(self.calls), 1)
        manifest = json.loads(first["manifest"].read_text())
        self.assertTrue(manifest["reusable"])
        self.assertEqual(
            manifest["invocation"]["measured_build"]["version_probe"]["setup_sha256"],
            sha256(self.setup_file.resolve()),
        )

    def test_missing_or_invalid_setup_and_symlink_escapes_and_path_impostor_reject(self) -> None:
        # 1. Missing setup does not fall back to bare dispatcher output even if bare prints a tag.
        _write_fake_dispatcher(self.real_dispatcher)
        self.real_dispatcher.write_text(
            "#!/bin/sh\n"
            "echo 'Phenix: bare with tag'\n"
            "echo '  Version: 2.0-5936'\n"
        )
        self.real_dispatcher.chmod(0o755)
        self.setup_file.unlink()
        missing = toolchain.phenix_build_evidence()
        self.assertIsNone(missing["reported_version_source"])
        self.assertIsNone(missing["reported_version"])
        self.assertFalse(_build_is_measured(missing))

        # 2. Non-file (directory) setup rejects.
        self.setup_file.mkdir()
        non_file = toolchain.phenix_build_evidence()
        self.assertIsNone(non_file["reported_version_source"])
        self.assertFalse(_build_is_measured(non_file))
        self.setup_file.rmdir()

        # Restore setup and dispatcher.
        self.setup_file.write_text("export PHENIX_VERSION=2.0-5936\n")
        _write_fake_dispatcher(self.real_dispatcher)

        # 3. Setup symlink escape outside prefix (and inside prefix) rejects.
        outside = self.root / "outside"
        outside.mkdir()
        outside_setup = outside / "phenix_env.sh"
        outside_setup.write_text("export PHENIX_VERSION=2.0-5936\n")
        self.setup_file.unlink()
        self.setup_file.symlink_to(outside_setup)
        setup_escape = toolchain.phenix_build_evidence()
        self.assertIsNone(setup_escape["reported_version_source"])
        self.assertFalse(_build_is_measured(setup_escape))
        self.setup_file.unlink()
        self.setup_file.write_text("export PHENIX_VERSION=2.0-5936\n")

        # 4. Outside-prefix parent setup when configured directory is not phenix_bin/bin rejects.
        nested_parent = self.root / "parent-with-setup"
        nested_bin = nested_parent / "custom_dir"
        nested_bin.mkdir(parents=True)
        (nested_parent / "phenix_env.sh").write_text("export PHENIX_VERSION=2.0-5936\n")
        _write_fake_dispatcher(nested_bin / "phenix.version")
        with mock.patch.object(toolchain, "PHENIX_BIN", nested_bin):
            outside_parent = toolchain.phenix_build_evidence()
        self.assertIsNone(outside_parent["reported_version_source"])
        self.assertFalse(_build_is_measured(outside_parent))

        # 5. Parent / phenix_bin directory symlink escape rejects.
        fake_prefix = self.root / "fake-prefix"
        fake_prefix.mkdir()
        (fake_prefix / "phenix_env.sh").write_text("export PHENIX_VERSION=2.0-5936\n")
        (fake_prefix / "phenix_bin").symlink_to(self.phenix_bin)
        with mock.patch.object(toolchain, "PHENIX_BIN", fake_prefix / "phenix_bin"):
            bin_symlink_escape = toolchain.phenix_build_evidence()
        self.assertIsNone(bin_symlink_escape["reported_version_source"])
        self.assertFalse(_build_is_measured(bin_symlink_escape))

        symlink_prefix = self.root / "symlink-prefix"
        symlink_prefix.symlink_to(self.prefix)
        with mock.patch.object(toolchain, "PHENIX_BIN", symlink_prefix / "phenix_bin"):
            prefix_symlink_escape = toolchain.phenix_build_evidence()
        self.assertIsNone(prefix_symlink_escape["reported_version_source"])
        self.assertFalse(_build_is_measured(prefix_symlink_escape))

        # 6. Dispatcher symlink escape outside prefix rejects.
        outside_bin = outside / "bin"
        outside_bin.mkdir()
        outside_dispatcher = outside_bin / "phenix.version"
        _write_fake_dispatcher(outside_dispatcher)
        self.configured_dispatcher.unlink()
        self.configured_dispatcher.symlink_to(outside_dispatcher)
        dispatcher_escape = toolchain.phenix_build_evidence()
        self.assertIsNone(dispatcher_escape["reported_version_source"])
        self.assertFalse(_build_is_measured(dispatcher_escape))

        # Intermediate hop escaping prefix and returning back into prefix also rejects.
        hop_link = outside / "hop-back"
        hop_link.symlink_to(self.real_dispatcher)
        self.configured_dispatcher.unlink()
        self.configured_dispatcher.symlink_to(hop_link)
        hop_escape = toolchain.phenix_build_evidence()
        self.assertIsNone(hop_escape["reported_version_source"])
        self.assertFalse(_build_is_measured(hop_escape))

        # 7. PATH impostor when configured dispatcher is missing rejects without running impostor.
        self.configured_dispatcher.unlink()
        impostor_marker = self.root / "impostor-ran"
        impostor = outside_bin / "phenix.version"
        impostor.write_text(
            f"#!{sys.executable}\n"
            f"from pathlib import Path\nPath({str(impostor_marker)!r}).write_text('ran')\n"
            "print('PHENIX 2.0-5936')\n"
        )
        impostor.chmod(0o755)
        with mock.patch.dict(os.environ, {"PATH": f"{outside_bin}:{os.environ.get('PATH', '')}"}):
            path_impostor = toolchain.phenix_build_evidence()
            bare_impostor = toolchain.phenix_bare_build_evidence()
        self.assertIsNone(path_impostor["reported_version_source"])
        self.assertIsNone(bare_impostor["reported_version_source"])
        self.assertFalse(impostor_marker.exists())

    def test_spoofed_inherited_vars_and_shell_hook_tripwires_are_neutralized(self) -> None:
        tripwire_marker = self.root / "tripwire-triggered"
        tripwire_script = self.root / "tripwire.sh"
        tripwire_script.write_text(
            f"echo triggered > {str(tripwire_marker)!r}\n"
            "export PHENIX_VERSION=8.8-8888\n"
            "export PHENIX_RELEASE_TAG=8888\n"
        )
        inherited = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PHENIX_VERSION": "9.9",
            "PHENIX_RELEASE_TAG": "9999",
            "BASH_ENV": str(tripwire_script),
            "ENV": str(tripwire_script),
            "SHELLOPTS": "posix",
            "BASHOPTS": "extdebug",
            "POSIXLY_CORRECT": "1",
            "CDPATH": str(self.root),
            "GLOBIGNORE": "*",
            "PROMPT_COMMAND": f"touch {tripwire_marker}",
            "PS4": "$(touch " + str(tripwire_marker) + ") ",
            "BASH_FUNC_export%%": f"() {{ touch {tripwire_marker}; }}",
            "BASH_FUNC_printf%%": f"() {{ touch {tripwire_marker}; }}",
            "LEGACY_FUNC": f"() {{ touch {tripwire_marker}; }}",
            "PROTSTRUCT_NORMAL_VAR": "kept-value",
        }
        snapshot = dict(inherited)
        with mock.patch.dict(os.environ, inherited, clear=True):
            clean = toolchain.phenix_version_environment()
            self.assertEqual(clean.get("PROTSTRUCT_NORMAL_VAR"), "kept-value")
            for forbidden in (
                "PHENIX_VERSION",
                "PHENIX_RELEASE_TAG",
                "BASH_ENV",
                "ENV",
                "SHELLOPTS",
                "BASHOPTS",
                "POSIXLY_CORRECT",
                "CDPATH",
                "GLOBIGNORE",
                "PROMPT_COMMAND",
                "PS4",
                "BASH_FUNC_export%%",
                "BASH_FUNC_printf%%",
                "LEGACY_FUNC",
            ):
                self.assertNotIn(forbidden, clean)
            evidence = toolchain.phenix_build_evidence()
            self.assertEqual(dict(os.environ), snapshot)
            first = self._run_cached()
            second = self._run_cached()
            self.assertEqual(dict(os.environ), snapshot)

        self.assertFalse(tripwire_marker.exists())
        self.assertEqual(evidence["reported_version_source"], "vendor_setup_environment")
        self.assertEqual(evidence["parsed_build"], "2.0-5936")
        self.assertTrue(_build_is_measured(evidence))
        self.assertEqual(first["model"], second["model"])
        self.assertEqual(first["manifest"].name, "success.json")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(
            evidence["version_probe"]["ignored_inherited_version_variables"],
            ["PHENIX_RELEASE_TAG", "PHENIX_VERSION"],
        )
        self.assertIn("BASH_ENV", evidence["version_probe"]["ignored_inherited_shell_hooks"])
        self.assertIn("ENV", evidence["version_probe"]["ignored_inherited_shell_hooks"])
        self.assertIn(
            "BASH_FUNC_export%%",
            evidence["version_probe"]["ignored_inherited_shell_hooks"],
        )
        self.assertIn(
            "LEGACY_FUNC",
            evidence["version_probe"]["ignored_inherited_shell_hooks"],
        )

        # #956: An inherited legacy exported function alone (LEGACY_FUNC='() { :; }')
        # is removed, recorded in ignored_inherited_shell_hooks, accepted by
        # _build_is_measured, and reuses cached outputs across identical requests.
        legacy_only_env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LEGACY_FUNC": f"() {{ touch {tripwire_marker}; }}",
        }
        self.calls.clear()
        self.work_dir = self.root / "work-legacy-only"
        self.work_dir.mkdir()
        with mock.patch.dict(os.environ, legacy_only_env, clear=True):
            legacy_evidence = toolchain.phenix_build_evidence()
            legacy_first = self._run_cached()
            legacy_second = self._run_cached()
        self.assertFalse(tripwire_marker.exists())
        self.assertEqual(
            legacy_evidence["version_probe"]["ignored_inherited_shell_hooks"],
            ["LEGACY_FUNC"],
        )
        self.assertTrue(_build_is_measured(legacy_evidence))
        self.assertEqual(legacy_first["model"], legacy_second["model"])
        self.assertEqual(legacy_first["manifest"].name, "success.json")
        self.assertEqual(len(self.calls), 1)

    def test_metacharacter_and_quote_paths_remain_literal(self) -> None:
        marker = self.root / "shell-injection-ran"
        weird_prefix = (
            self.root
            / f"phenix 'quoted' \"double\" ; $(touch {marker.name}) `touch {marker.name}`"
        )
        weird_phenix_bin = weird_prefix / "phenix_bin"
        weird_internal_bin = weird_prefix / "bin"
        weird_phenix_bin.mkdir(parents=True)
        weird_internal_bin.mkdir(parents=True)
        (weird_prefix / "phenix_env.sh").write_text("export PHENIX_VERSION='2.0-5936'\n")
        _write_fake_dispatcher(weird_internal_bin / "phenix.version")
        (weird_phenix_bin / "phenix.version").symlink_to("../bin/phenix.version")
        with mock.patch.object(toolchain, "PHENIX_BIN", weird_phenix_bin):
            evidence = toolchain.phenix_build_evidence()
        self.assertFalse(marker.exists())
        self.assertEqual(evidence["reported_version_source"], "vendor_setup_environment")
        self.assertEqual(evidence["parsed_build"], "2.0-5936")
        self.assertTrue(_build_is_measured(evidence))

    def test_setup_and_dispatcher_failures_chatter_conflicts_and_split_streams_reject(
        self,
    ) -> None:
        # 1. Setup nonzero exit.
        self.setup_file.write_text("echo 'setup error' >&2\nreturn 3 2>/dev/null || exit 3\n")
        failed_setup = toolchain.phenix_build_evidence()
        self.assertIsNone(failed_setup["reported_version_source"])
        self.assertEqual(failed_setup["version_probe"]["setup_returncode"], 3)
        self.assertIn("setup error", failed_setup["version_probe"]["setup_stderr"])
        self.assertFalse(_build_is_measured(failed_setup))

        # 2. Setup early exit 0 before reporting variables.
        self.setup_file.write_text("export PHENIX_VERSION=2.0-5936\nexit 0\n")
        early_exit = toolchain.phenix_build_evidence()
        self.assertIsNone(early_exit["reported_version_source"])
        self.assertIsNone(early_exit["version_probe"]["setup_version_fields"])
        self.assertFalse(_build_is_measured(early_exit))

        # 3. Setup stdout chatter.
        self.setup_file.write_text("echo 'Phenix: fake banner'\nexport PHENIX_VERSION=2.0-5936\n")
        stdout_chatter = toolchain.phenix_build_evidence()
        self.assertIsNone(stdout_chatter["reported_version_source"])
        self.assertEqual(stdout_chatter["version_probe"]["setup_stdout"], "Phenix: fake banner\n")
        self.assertFalse(_build_is_measured(stdout_chatter))

        # 4. Setup stderr chatter.
        self.setup_file.write_text("echo 'setup warning' >&2\nexport PHENIX_VERSION=2.0-5936\n")
        stderr_chatter = toolchain.phenix_build_evidence()
        self.assertIsNone(stderr_chatter["reported_version_source"])
        self.assertEqual(stderr_chatter["version_probe"]["setup_stderr"], "setup warning\n")
        self.assertFalse(_build_is_measured(stderr_chatter))

        # 5. Duplicate setup assignments.
        for duplicate_script in (
            "export PHENIX_VERSION=2.0-5936\nexport PHENIX_VERSION=2.0-5936\n",
            "export PHENIX_VERSION=2.0-5936\nexport PHENIX_VERSION=2.0-9999\n",
            "export PHENIX_VERSION=2.0\nexport PHENIX_RELEASE_TAG=5936\nexport PHENIX_RELEASE_TAG=9999\n",
        ):
            with self.subTest(duplicate_script=duplicate_script):
                self.setup_file.write_text(duplicate_script)
                dup = toolchain.phenix_build_evidence()
                self.assertIsNone(dup["reported_version_source"])
                self.assertFalse(_build_is_measured(dup))

        # 6. Malformed or contradictory setup version fields.
        for bad_setup in (
            "# no version exported\n",
            "export PHENIX_VERSION=''\n",
            "export PHENIX_VERSION=2.0\n",
            "export PHENIX_RELEASE_TAG=5936\n",
            "export PHENIX_VERSION=2.0-5936\nexport PHENIX_RELEASE_TAG=9999\n",
            "export PHENIX_VERSION=2.0-5936+SVN\n",
            "export PHENIX_VERSION=unknown\n",
        ):
            with self.subTest(bad_setup=bad_setup):
                self.setup_file.write_text(bad_setup)
                bad = toolchain.phenix_build_evidence()
                self.assertIsNone(bad["reported_version_source"])
                self.assertFalse(_build_is_measured(bad))

        self.setup_file.write_text("export PHENIX_VERSION=2.0-5936\n")

        # 7. Setup timeout and dispatcher timeout.
        with mock.patch.object(
            toolchain,
            "_run_phenix_setup",
            side_effect=subprocess.TimeoutExpired(["/bin/bash"], 10),
        ):
            setup_timeout = toolchain.phenix_build_evidence()
        self.assertIsNone(setup_timeout["reported_version_source"])
        self.assertIn("TimeoutExpired", setup_timeout["version_probe"]["error"])
        self.assertFalse(_build_is_measured(setup_timeout))

        with mock.patch.object(
            toolchain,
            "run_capture",
            side_effect=subprocess.TimeoutExpired([str(self.real_dispatcher)], 10),
        ):
            dispatcher_timeout = toolchain.phenix_build_evidence()
        self.assertIsNone(dispatcher_timeout["reported_version_source"])
        self.assertIn("TimeoutExpired", dispatcher_timeout["version_probe"]["error"])
        self.assertFalse(_build_is_measured(dispatcher_timeout))

        # 8. Dispatcher failure, empty output, unparseable output, stderr-only output,
        # conflicting setup/banner identity, duplicate fields/headers, cross-banner and
        # cross-stream split fragments.
        bad_dispatchers = [
            (1, VALID_VENDOR_BANNER, ""),
            (0, "", ""),
            (0, "unparseable output\n", ""),
            (0, "", VALID_VENDOR_BANNER),
            (
                0,
                "Phenix: title\n  Version: 2.0\n  Release tag: 9999\n",
                "",
            ),
            (
                0,
                "Phenix: first\n  Version: 2.0-5936\nPhenix: second\n",
                "",
            ),
            (
                0,
                "Phenix: title\n  Version: 2.0\n  Version: 2.0\n  Release tag: 5936\n",
                "",
            ),
            (
                0,
                "Phenix: title\n  Version: 2.0\n  Release tag: 5936\n  Release tag: 5936\n",
                "",
            ),
            (
                0,
                "-------------------------------------------------------------------------------\n"
                "  Phenix: Banner One\n"
                "  Version: 2.0\n"
                "-------------------------------------------------------------------------------\n"
                "  Release tag: 5936\n"
                "-------------------------------------------------------------------------------\n",
                "",
            ),
            (
                0,
                "Phenix: Banner One\n  Version: 2.0\nPhenix: Banner Two\n  Release tag: 5936\n",
                "",
            ),
            (
                0,
                "Phenix: title\n  Version: 2.0\n",
                "  Release tag: 5936\n",
            ),
            (
                0,
                VALID_VENDOR_BANNER,
                "Version: 2.0-9999\n",
            ),
        ]
        for code, stdout, stderr in bad_dispatchers:
            with self.subTest(code=code, stdout=stdout, stderr=stderr), mock.patch.object(
                toolchain,
                "run_capture",
                return_value=subprocess.CompletedProcess(
                    [str(self.real_dispatcher.resolve())], code, stdout, stderr
                ),
            ):
                bad_disp = toolchain.phenix_build_evidence()
                self.assertIsNone(bad_disp["reported_version_source"])
                self.assertIsNone(bad_disp["reported_version"])
                self.assertFalse(_build_is_measured(bad_disp))

        # 9. File mutation during measurement rejects.
        def mutate_setup_during_capture(argv, **kwargs):
            self.setup_file.write_text("export PHENIX_VERSION=2.0-5936\n# mutated\n")
            return subprocess.CompletedProcess(argv, 0, VALID_VENDOR_BANNER, "")

        with mock.patch.object(toolchain, "run_capture", side_effect=mutate_setup_during_capture):
            mutated = toolchain.phenix_build_evidence()
        self.assertIsNone(mutated["reported_version_source"])
        self.assertIn("changed during measurement", mutated["version_probe"]["error"])
        self.assertFalse(_build_is_measured(mutated))

    def test_every_required_evidence_binding_mutation_is_rejected_by_cache_gate(self) -> None:
        valid = toolchain.phenix_build_evidence()
        self.assertTrue(_build_is_measured(valid))

        def mutate_copy(fn):
            candidate = copy.deepcopy(valid)
            fn(candidate)
            return candidate

        mutations = [
            lambda d: d.update(reported_version_source=None),
            lambda d: d.update(reported_version_source="command_output"),
            lambda d: d.update(reported_version_source="configured_path_version_hint"),
            lambda d: d.update(reported_version=None),
            lambda d: d.update(reported_version=""),
            lambda d: d.update(reported_version="Phenix: title\nVersion: 2.0-5936"),
            lambda d: d.update(parsed_build=None),
            lambda d: d.update(parsed_build="2.0-9999"),
            lambda d: d.pop("version_probe"),
            lambda d: d["version_probe"].update(error="unexpected error"),
            lambda d: d["version_probe"].update(probe_mode="command_output"),
            lambda d: d["version_probe"].update(configured_prefix="relative/prefix"),
            lambda d: d["version_probe"].update(configured_prefix=str(self.root / "wrong-prefix")),
            lambda d: d["version_probe"].update(resolved_prefix=str(self.root / "outside")),
            lambda d: d["version_probe"].update(
                setup_configured_path=str(self.prefix / "other_env.sh")
            ),
            lambda d: d["version_probe"].update(
                setup_resolved_path=str(self.root / "phenix_env.sh")
            ),
            lambda d: d["version_probe"].update(
                configured_path=str(self.phenix_bin / "phenix.refine")
            ),
            lambda d: d["version_probe"].update(
                resolved_path=str(self.root / "bin" / "phenix.version")
            ),
            lambda d: d["version_probe"].update(setup_sha256="abc"),
            lambda d: d["version_probe"].update(setup_sha256="0" * 63 + "G"),
            lambda d: d["version_probe"].update(sha256=None),
            lambda d: d["version_probe"].update(sha256="A" * 64),
            lambda d: d["version_probe"].update(setup_argv=["/bin/bash", "--norc", "bad"]),
            lambda d: d["version_probe"].update(setup_argv="not-a-list"),
            lambda d: d["version_probe"].update(argv=[str(self.configured_dispatcher)]),
            lambda d: d["version_probe"].update(argv=[]),
            lambda d: d["version_probe"].update(setup_returncode=1),
            lambda d: d["version_probe"].update(setup_returncode=True),
            lambda d: d["version_probe"].update(setup_returncode=None),
            lambda d: d["version_probe"].update(returncode=1),
            lambda d: d["version_probe"].update(returncode=True),
            lambda d: d["version_probe"].update(returncode=None),
            lambda d: d["version_probe"].update(setup_stdout="chatter\n"),
            lambda d: d["version_probe"].update(setup_stderr="warning\n"),
            lambda d: d["version_probe"].update(stdout=""),
            lambda d: d["version_probe"].update(stdout=EXACT_023_BARE_BANNER),
            lambda d: d["version_probe"].update(stderr="Release tag: 5936\n"),
            lambda d: d["version_probe"].update(setup_version_fields=None),
            lambda d: d["version_probe"].update(
                setup_version_fields={"PHENIX_VERSION": "2.0-5936"}
            ),
            lambda d: d["version_probe"].update(
                setup_version_fields={
                    "PHENIX_VERSION": "2.0-5936",
                    "PHENIX_RELEASE_TAG": None,
                    "EXTRA": "1",
                }
            ),
            lambda d: d["version_probe"].update(
                setup_version_fields={
                    "PHENIX_VERSION": "2.0-9999",
                    "PHENIX_RELEASE_TAG": None,
                }
            ),
            lambda d: d["version_probe"].update(setup_parsed_build="2.0-9999"),
            lambda d: d["version_probe"].update(parsed_build="2.0-9999"),
            lambda d: d["version_probe"].update(
                ignored_inherited_version_variables=["UNKNOWN_VAR"]
            ),
            lambda d: d["version_probe"].update(
                ignored_inherited_version_variables=["PHENIX_VERSION", "PHENIX_RELEASE_TAG"]
            ),
            lambda d: d["version_probe"].update(
                ignored_inherited_shell_hooks="not-a-list"
            ),
            lambda d: d["version_probe"].update(
                ignored_inherited_shell_hooks=[""]
            ),
            lambda d: d["version_probe"].update(
                ignored_inherited_shell_hooks=["BAD=HOOK"]
            ),
            lambda d: d["version_probe"].update(
                ignored_inherited_shell_hooks=["BAD HOOK"]
            ),
            lambda d: d["version_probe"].update(
                ignored_inherited_shell_hooks=["PHENIX_VERSION"]
            ),
            lambda d: d["version_probe"].update(
                ignored_inherited_shell_hooks=["Z_HOOK", "A_HOOK"]
            ),
            lambda d: d["version_probe"].update(
                ignored_inherited_shell_hooks=["BASH_ENV", "BASH_ENV"]
            ),
        ]
        for index, mutate in enumerate(mutations):
            mutated = mutate_copy(mutate)
            with self.subTest(mutation_index=index):
                self.assertFalse(_build_is_measured(mutated))

        # Also verify on-disk cache bundle rejection when a stored vendor_setup_environment
        # binding is tampered with after caching.
        first = self._run_cached()
        manifest_path = first["manifest"]
        invocation_path = first["model"].parent / "invocation.json"
        original_manifest = json.loads(manifest_path.read_text())
        original_invocation = json.loads(invocation_path.read_text())

        for mutate in (
            lambda d: d["version_probe"].update(setup_sha256="bad"),
            lambda d: d["version_probe"].update(
                setup_version_fields={
                    "PHENIX_VERSION": "2.0-9999",
                    "PHENIX_RELEASE_TAG": None,
                }
            ),
            lambda d: d["version_probe"].update(setup_returncode=1),
            lambda d: d["version_probe"].update(setup_stdout="chatter"),
        ):
            tampered_manifest = copy.deepcopy(original_manifest)
            tampered_invocation = copy.deepcopy(original_invocation)
            mutate(tampered_manifest["invocation"]["measured_build"])
            mutate(tampered_invocation["measured_build"])
            manifest_path.write_text(json.dumps(tampered_manifest))
            invocation_path.write_text(json.dumps(tampered_invocation))
            with self.assertRaises(CacheEvidenceError):
                self._run_cached()

        manifest_path.write_text(json.dumps(original_manifest))
        invocation_path.write_text(json.dumps(original_invocation))
        self.assertEqual(self._run_cached(), first)

    def test_setup_and_dispatcher_byte_changes_invalidate_cache_reuse(self) -> None:
        first = self._run_cached()["model"]
        self.assertEqual(self._run_cached()["model"], first)
        self.assertEqual(len(self.calls), 1)

        # Changing setup bytes (even with a comment that preserves PHENIX_VERSION=2.0-5936)
        # changes setup_sha256 and invalidates cache reuse.
        self.setup_file.write_text(self.setup_file.read_text() + "# setup byte change\n")
        second = self._run_cached()["model"]
        self.assertNotEqual(second, first)
        self.assertEqual(len(self.calls), 2)

        # Changing dispatcher bytes changes dispatcher sha256 and invalidates cache reuse.
        self.real_dispatcher.write_text(self.real_dispatcher.read_text() + "# dispatcher change\n")
        self.real_dispatcher.chmod(0o755)
        third = self._run_cached()["model"]
        self.assertNotEqual(third, second)
        self.assertEqual(len(self.calls), 3)

    def test_external_tool_report_is_honest_for_vendor_and_unverified_phenix(self) -> None:
        spec = {
            "expected_version": "2.0-5936",
            "configured_path": self.phenix_bin,
            "executables": ("phenix.version", "phenix.refine"),
            "version_args": (),
        }
        with mock.patch.object(toolchain, "EXTERNAL_TOOL_SPECS", {"PHENIX": spec}):
            verified = toolchain.external_tool_report()["PHENIX"]
        self.assertTrue(verified["available"])
        self.assertEqual(verified["reported_version_source"], "vendor_setup_environment")
        self.assertIn("Release tag: 5936", verified["reported_version"])
        self.assertFalse(verified["version_divergence"])

        # Removing phenix_env.sh causes the probe to fail closed: reported_version is None
        # (never a truncated bare banner) and version_divergence is True despite the path hint.
        self.setup_file.unlink()
        with mock.patch.object(toolchain, "EXTERNAL_TOOL_SPECS", {"PHENIX": spec}):
            unverified = toolchain.external_tool_report()["PHENIX"]
        self.assertTrue(unverified["available"])
        self.assertIsNone(unverified["reported_version"])
        self.assertIsNone(unverified["reported_version_source"])
        self.assertEqual(unverified["configured_path_version_hint"], "2.0-5936")
        self.assertTrue(unverified["version_divergence"])


if __name__ == "__main__":
    unittest.main()
