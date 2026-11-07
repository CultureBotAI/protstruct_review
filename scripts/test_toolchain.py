#!/usr/bin/env python3
"""Regression tests for shell-free tool execution and centralized config."""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

import toolchain


def check(label: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"PASS  {label}")


with tempfile.TemporaryDirectory(prefix="tool path ; $() ") as tmp:
    root = Path(tmp)
    helper = root / "helper ; $(never-run).py"
    output = root / "output ; literal.log"
    argument = "value ; $(touch SHOULD_NOT_EXIST) with spaces"
    helper.write_text(
        "import json, sys\n"
        "print(json.dumps({'argument': sys.argv[1], 'cwd': __import__('os').getcwd()}))\n"
    )
    result = toolchain.run_logged(
        [sys.executable, helper, argument], output, cwd=root, timeout=10
    )
    record = json.loads(output.read_text())
    check("metacharacter path executes successfully", result.returncode == 0)
    check("argument reaches the child literally", record["argument"] == argument)
    check(
        "cwd with spaces/metacharacters is preserved",
        Path(record["cwd"]).resolve() == root.resolve(),
    )
    check("shell command substitution never runs", not (root / "SHOULD_NOT_EXIST").exists())

    tmalign = root / "TM align ; $(never-run)"
    tmalign.write_text(
        "#!/usr/bin/env python3\n"
        "print('Aligned length= 3, RMSD= 1.25')\n"
        "print('TM-score= 0.8000 (if normalized by length of Chain_2')\n"
    )
    tmalign.chmod(0o755)
    spec = importlib.util.spec_from_file_location(
        "bench_t01_shell_safety", Path(__file__).with_name("bench_t01_superposition.py")
    )
    bench_t01 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bench_t01)
    bench_t01.TMALIGN = tmalign
    fixed = root / "fixed ; model.pdb"
    moving = root / "moving $(literal).pdb"
    fixed.write_text("MODEL\n")
    moving.write_text("MODEL\n")
    parsed = bench_t01.run_tmalign(fixed, moving, root, all_chains=True)
    check(
        "representative benchmark output remains parseable",
        parsed == {"n_aligned": 3, "rmsd": 1.25, "tm_score": 0.8},
    )

with tempfile.TemporaryDirectory(prefix="ccp4 setup ; ") as tmp:
    setup = Path(tmp) / "vendor setup ; literal.sh"
    setup.write_text("export PROTSTRUCT_ADAPTER_TEST='literal ; $() value'\n")
    environment = toolchain.ccp4_environment(setup)
    check(
        "CCP4 setup path and exported metacharacters remain literal",
        environment["PROTSTRUCT_ADAPTER_TEST"] == "literal ; $() value",
    )

with tempfile.TemporaryDirectory(prefix="tool version evidence ") as tmp:
    root = Path(tmp)
    expected_dir = root / "suite-1.2.3"
    expected_dir.mkdir()
    lying_tool = expected_dir / "tool-version"
    lying_tool.write_text("#!/bin/sh\necho 'tool version 9.9.9'\n")
    lying_tool.chmod(0o755)
    setup_file = expected_dir / "ccp4.setup-sh"
    setup_file.write_text("export CCP4='configured'\n")
    original_specs = toolchain.EXTERNAL_TOOL_SPECS
    try:
        toolchain.EXTERNAL_TOOL_SPECS = {
            "measured": {
                "expected_version": "1.2.3",
                "configured_path": lying_tool,
                "executables": ("tool-version",),
                "version_args": (),
            },
            "empty-directory": {
                "expected_version": "1.2.3",
                "configured_path": expected_dir,
                "executables": ("missing-tool",),
                "version_args": None,
            },
            "configured-artifact": {
                "expected_version": "1.2.3",
                "configured_path": setup_file,
                "executables": ("missing-until-setup",),
                "version_args": None,
                "availability_probe": "configured_file",
            },
        }
        report = toolchain.external_tool_report()
    finally:
        toolchain.EXTERNAL_TOOL_SPECS = original_specs
    check(
        "measured version output is never replaced by the configured path",
        report["measured"]["reported_version"] == "tool version 9.9.9",
    )
    check(
        "measured version provenance is labeled",
        report["measured"]["reported_version_source"] == "command_output",
    )
    check(
        "measured mismatch overrides a matching path hint",
        report["measured"]["version_divergence"] is True,
    )
    check(
        "empty expected-version directory is not an available tool",
        report["empty-directory"]["available"] is False,
    )
    check(
        "configured-file availability is an explicit CCP4-style exception",
        report["configured-artifact"]["available"] is True
        and report["configured-artifact"]["availability_probe"] == "configured_file",
    )
    check(
        "configured-file path inference is kept out of reported_version",
        report["configured-artifact"]["reported_version"] is None
        and report["configured-artifact"]["configured_path_version_hint"] == "1.2.3",
    )

with tempfile.TemporaryDirectory(prefix="bare executable cwd trap ") as tmp:
    root = Path(tmp)
    cwd_tool = root / "mkdssp"
    cwd_tool.write_text("#!/bin/sh\necho wrong-cwd-tool\n")
    cwd_tool.chmod(0o755)
    old_cwd = Path.cwd()
    old_path = os.environ.get("PATH", "")
    try:
        os.chdir(root)
        os.environ["PATH"] = ""
        discovered = toolchain._discover_executable(Path("mkdssp"), ("mkdssp",))
    finally:
        os.chdir(old_cwd)
        os.environ["PATH"] = old_path
    check("bare configured names are PATH-only, never cwd files", discovered is None)

with tempfile.TemporaryDirectory(prefix="foreign import cwd ") as tmp:
    root = Path(tmp)
    driver = Path(__file__).with_name("bench_t01_superposition.py")
    import_probe = (
        "import importlib.util, pathlib, sys; "
        "p=pathlib.Path(sys.argv[1]); "
        "s=importlib.util.spec_from_file_location('foreign_driver', p); "
        "m=importlib.util.module_from_spec(s); s.loader.exec_module(m); "
        "print(m.__name__)"
    )
    loaded = toolchain.run_capture(
        [sys.executable, "-I", "-c", import_probe, driver], cwd=root, timeout=10
    )
    check(
        "driver imports toolchain from an isolated foreign cwd",
        loaded.returncode == 0 and loaded.stdout.strip() == "foreign_driver",
    )

scripts_dir = Path(__file__).resolve().parent
shell_calls = []
duplicate_constants = []
for script in sorted(scripts_dir.glob("*.py")):
    tree = ast.parse(script.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            has_bash_c = any(
                isinstance(child, (ast.List, ast.Tuple))
                and len(child.elts) >= 2
                and isinstance(child.elts[0], ast.Constant)
                and child.elts[0].value in {"bash", "/bin/bash"}
                and isinstance(child.elts[1], ast.Constant)
                and child.elts[1].value == "-c"
                for child in ast.walk(node)
            )
            has_shell_true = any(
                keyword.arg == "shell"
                and isinstance(keyword.value, ast.Constant)
                and keyword.value.value is True
                for keyword in node.keywords
            )
            if script.name != "toolchain.py" and (has_bash_c or has_shell_true):
                shell_calls.append(f"{script.name}:{node.lineno}")
        if (
            script.name != "toolchain.py"
            and not script.name.startswith("test_")
            and isinstance(node, (ast.Assign, ast.AnnAssign))
        ):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id in {
                    "PHENIX_BIN",
                    "CCP4_SETUP",
                    "TMALIGN",
                    "REDUCE",
                    "PROBE",
                    "GEMMI",
                }:
                    duplicate_constants.append(f"{script.name}:{target.id}")
check("no runner invokes bash -c", not shell_calls)
# #496: no script builds an argv that starts with a bare "gemmi" — the CLI is
# resolved once through toolchain.gemmi_executable() so the manifest and the
# measurements name the same binary even under the ccp4 environment rewrite.
bare_gemmi = []
for script in sorted(Path(__file__).parent.glob("*.py")):
    if script.name in {"toolchain.py"} or script.name.startswith("test_"):
        continue
    for node in ast.walk(ast.parse(script.read_text())):
        # argv literals are lists here; ("gemmi", fn) label tuples are not argv.
        if (isinstance(node, ast.List) and node.elts
                and isinstance(node.elts[0], ast.Constant)
                and node.elts[0].value == "gemmi"):
            bare_gemmi.append(f"{script.name}:{node.lineno}")
        # shutil.which("gemmi") re-introduces a second resolver (#505).
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "which" and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "gemmi"):
            bare_gemmi.append(f"{script.name}:{node.lineno} (shutil.which)")
check("no script invokes a bare 'gemmi' argv (#496)", not bare_gemmi)

with tempfile.TemporaryDirectory(prefix="gemmi resolver ") as tmp:
    root = Path(tmp)
    fake = root / "gemmi"
    fake.write_text("#!/bin/sh\necho gemmi 9.9.9\n")
    fake.chmod(0o755)
    old_gemmi = toolchain.GEMMI
    old_path = os.environ.get("PATH", "")
    try:
        toolchain.GEMMI = fake
        check("PROTSTRUCT_GEMMI absolute path is honoured",
              toolchain.gemmi_executable() == fake.resolve())
        toolchain.GEMMI = Path("gemmi")
        os.environ["PATH"] = str(root)
        check("bare default resolves the PATH binary to an absolute path",
              toolchain.gemmi_executable() == fake.resolve())
        rel = Path(os.path.relpath(fake))
        toolchain.GEMMI = rel
        check("a relative PROTSTRUCT_GEMMI resolves to an absolute path (#503)",
              toolchain.gemmi_executable().is_absolute()
              and toolchain.gemmi_executable() == fake.resolve())
        toolchain.GEMMI = Path("gemmi")
        os.environ["PATH"] = ""
        check("absent CLI: required=False returns None",
              toolchain.gemmi_executable(required=False) is None)
        try:
            toolchain.gemmi_executable()
            named = False
        except FileNotFoundError as exc:
            named = "PROTSTRUCT_GEMMI" in str(exc)
        check("absent CLI: required raises a failure naming PROTSTRUCT_GEMMI", named)
    finally:
        toolchain.GEMMI = old_gemmi
        os.environ["PATH"] = old_path
check("gemmi is in the external tool report",
      "gemmi" in toolchain.EXTERNAL_TOOL_SPECS
      and toolchain.EXTERNAL_TOOL_SPECS["gemmi"]["expected_version"] == toolchain.GEMMI_VERSION)
check("tool paths are defined only in toolchain.py", not duplicate_constants)

with tempfile.TemporaryDirectory(prefix="refmac wrapper ; $() ") as tmp:
    root = Path(tmp)
    spaced_py_dir = root / "spaced python interpreter ; dir"
    spaced_py_dir.mkdir()
    spaced_python = spaced_py_dir / "python3"
    spaced_python.symlink_to(Path(sys.executable))
    fake_refmac = root / "refmac5 ; $(never-run)"
    fake_refmac.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "print(json.dumps({\n"
        "    'argv': sys.argv,\n"
        "    'stdin': sys.stdin.read(),\n"
        "    'marker': os.environ.get('PROTSTRUCT_REFMAC_ENV_MARKER'),\n"
        "    'executable': sys.executable,\n"
        "    'path_head': os.environ.get('PATH', '').split(os.pathsep)[0],\n"
        "}))\n"
    )
    fake_refmac.chmod(0o755)
    xyzin = root / "in ; model.pdb"
    hklin = root / "in $(obs).mtz"
    xyzout = root / "out ; model.pdb"
    hklout = root / "out $(obs).mtz"
    xmlout = root / "out ; xml $(literal).xml"
    log_path = root / "refmac ; run.log"
    custom_env = dict(os.environ)
    custom_env["PATH"] = f"{spaced_py_dir}{os.pathsep}{os.environ.get('PATH', '')}"
    custom_env["PROTSTRUCT_REFMAC_ENV_MARKER"] = "explicit-ccp4-env ; $()"

    ccp4_env_calls = 0
    orig_ccp4_environment = toolchain.ccp4_environment
    try:
        def _stub_ccp4_environment(setup_path=toolchain.CCP4_SETUP):
            global ccp4_env_calls
            ccp4_env_calls += 1
            env_copy = dict(os.environ)
            env_copy["PATH"] = f"{spaced_py_dir}{os.pathsep}{os.environ.get('PATH', '')}"
            env_copy["PROTSTRUCT_REFMAC_ENV_MARKER"] = "stubbed-ccp4-default-env"
            return env_copy

        toolchain.ccp4_environment = _stub_ccp4_environment

        proc = toolchain.run_refmac(
            xyzin,
            hklin,
            xyzout,
            hklout,
            log_path,
            "NCYC 0\nEND\n",
            cwd=root,
            timeout=10,
            xml_output=xmlout,
            executable=fake_refmac,
            env=custom_env,
        )
        payload = json.loads(log_path.read_text())
        check("run_refmac with explicit executable and xml_output succeeds", proc.returncode == 0)
        check(
            "fake executable runs under whitespace-safe shebang via spaced interpreter PATH",
             payload["path_head"] == str(spaced_py_dir)
            and Path(payload["executable"]).resolve() == Path(sys.executable).resolve(),
        )
        check(
            "run_refmac passes XMLOUT and metacharacter paths literally",
            payload["argv"]
            == [
                str(fake_refmac),
                "XYZIN",
                str(xyzin),
                "HKLIN",
                str(hklin),
                "XYZOUT",
                str(xyzout),
                "HKLOUT",
                str(hklout),
                "XMLOUT",
                str(xmlout),
            ],
        )
        check(
            "run_refmac forwards stdin keywords and explicit env without calling ccp4_environment",
            payload["stdin"] == "NCYC 0\nEND\n"
            and payload["marker"] == "explicit-ccp4-env ; $()"
            and ccp4_env_calls == 0,
        )

        # Explicit env with ccp4=False is also authoritative and never calls ccp4_environment
        log_path_false = root / "refmac ; ccp4-false.log"
        proc_false = toolchain.run_refmac(
            xyzin,
            hklin,
            xyzout,
            hklout,
            log_path_false,
            "NCYC 0\nEND\n",
            cwd=root,
            timeout=10,
            executable=fake_refmac,
            env=custom_env,
            ccp4=False,
        )
        payload_false = json.loads(log_path_false.read_text())
        check(
            "run_refmac with explicit env and ccp4=False preserves supplied env",
            proc_false.returncode == 0
            and payload_false["marker"] == "explicit-ccp4-env ; $()"
            and ccp4_env_calls == 0,
        )

        # Explicit env combined with ccp4=True must raise ValueError without calling ccp4_environment
        rejected_combo = False
        try:
            toolchain.run_refmac(
                xyzin,
                hklin,
                xyzout,
                hklout,
                root / "refmac ; should-not-run.log",
                "NCYC 0\nEND\n",
                cwd=root,
                timeout=10,
                executable=fake_refmac,
                env=custom_env,
                ccp4=True,
            )
        except ValueError as exc:
            rejected_combo = "ccp4=True" in str(exc) and "env" in str(exc)
        check(
            "run_refmac rejects explicit env combined with ccp4=True",
            rejected_combo
            and ccp4_env_calls == 0
            and not (root / "refmac ; should-not-run.log").exists(),
        )

        # Legacy neither option (env=None, ccp4=None) loads ccp4_environment()
        log_path_legacy = root / "refmac ; legacy-ccp4.log"
        proc_legacy = toolchain.run_refmac(
            xyzin,
            hklin,
            xyzout,
            hklout,
            log_path_legacy,
            "END\n",
            cwd=root,
            timeout=10,
            executable=fake_refmac,
        )
        payload_legacy = json.loads(log_path_legacy.read_text())
        check(
            "legacy run_refmac without env loads ccp4_environment by default",
            proc_legacy.returncode == 0
            and ccp4_env_calls == 1
            and payload_legacy["marker"] == "stubbed-ccp4-default-env",
        )
    finally:
        toolchain.ccp4_environment = orig_ccp4_environment

    captured_calls: list[dict[str, object]] = []
    orig_run_logged = toolchain.run_logged
    try:
        def _fake_run_logged(arguments, log_p, *, cwd=None, timeout=None, env=None, ccp4=False, input_text=None):
            captured_calls.append(
                {
                    "arguments": list(arguments),
                    "log_path": log_p,
                    "cwd": cwd,
                    "timeout": timeout,
                    "env": env,
                    "ccp4": ccp4,
                    "input_text": input_text,
                }
            )
            return toolchain.subprocess.CompletedProcess(["refmac5"], 0, "", "")

        toolchain.run_logged = _fake_run_logged
        toolchain.run_refmac(
            "in.pdb",
            "in.mtz",
            "out.pdb",
            "out.mtz",
            "refmac.log",
            "END\n",
            cwd=root,
        )
    finally:
        toolchain.run_logged = orig_run_logged
    check(
        "default run_refmac call preserves legacy argv and ccp4=True",
        len(captured_calls) == 1
        and captured_calls[0]["arguments"]
        == [
            "refmac5",
            "XYZIN",
            "in.pdb",
            "HKLIN",
            "in.mtz",
            "XYZOUT",
            "out.pdb",
            "HKLOUT",
            "out.mtz",
        ]
        and captured_calls[0]["ccp4"] is True
        and captured_calls[0]["env"] is None,
    )

print("\nall toolchain unit tests passed")
