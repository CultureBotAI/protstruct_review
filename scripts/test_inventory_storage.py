#!/usr/bin/env python3
"""Hermetic safety tests for the read-only storage inventory; no network, tools or science."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import unicodedata
import unittest
from unittest import mock

sys.dont_write_bytecode = True  # importing the helper must not write scripts/__pycache__
import inventory_storage as inventory  # noqa: E402

SCRIPT = Path(__file__).resolve().with_name("inventory_storage.py")
SKILL = SCRIPT.parent.parent / ".claude/skills/review-data-retention/SKILL.md"
READ_ONLY_GIT = {("rev-parse",), ("symbolic-ref",), ("ls-files",), ("diff-index", "--cached"),
                 ("count-objects",), ("worktree", "list"), ("config", "--get")}
VERDICT_WORDS = ("delet", "remov", "dispos", "safe", "junk", "clean", "reclaim", "obsolete")


def snapshot(base: Path) -> dict:
    """Every entry's type, mode, size, mtime, inode, links and content or link target."""
    state = {}
    for directory, dirnames, filenames in os.walk(base):
        for name in dirnames + filenames:
            path = Path(directory, name)
            info = path.lstat()
            row = (stat.S_IFMT(info.st_mode), stat.S_IMODE(info.st_mode), info.st_size,
                   info.st_mtime_ns, info.st_ino, info.st_nlink)
            if stat.S_ISLNK(info.st_mode):
                row += (os.readlink(path),)
            elif stat.S_ISREG(info.st_mode):
                row += (hashlib.sha256(path.read_bytes()).hexdigest(),)
            state[str(path.relative_to(base))] = row
    return state


def keys(value) -> set:
    if isinstance(value, dict):
        return set(value).union(*(keys(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(keys(item) for item in value))
    return set()


@contextlib.contextmanager
def deadline(seconds: int):
    """Fail instead of hanging if a regression makes a call block."""
    def expire(signum, frame):
        raise TimeoutError("call blocked")
    previous = signal.signal(signal.SIGALRM, expire)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


class Tree:
    """A temporary repository plus a sibling directory outside the audited root.

    The path carries spaces and shell metacharacters, and Git sees no inherited
    GIT_* variables, user or system configuration, or global excludes."""

    def __init__(self, test: unittest.TestCase, *, repository: bool = True):
        holder = tempfile.TemporaryDirectory(prefix="inventory storage $(x) ;'")
        test.addCleanup(holder.cleanup)
        self.base = Path(holder.name).resolve()
        self.root, self.outside, home = self.base / "repo", self.base / "outside", self.base / "home"
        for path in (self.root, self.outside, home):
            path.mkdir()
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update(HOME=str(home), XDG_CONFIG_HOME=str(home), GIT_CONFIG_GLOBAL=os.devnull,
                   GIT_CONFIG_NOSYSTEM="1", GIT_ATTR_NOSYSTEM="1", GIT_CEILING_DIRECTORIES=str(self.base),
                   PYTHONDONTWRITEBYTECODE="1", GIT_AUTHOR_NAME="fixture", GIT_AUTHOR_EMAIL="fixture",
                   GIT_COMMITTER_NAME="fixture", GIT_COMMITTER_EMAIL="fixture")
        test.enterContext(mock.patch.dict(os.environ, env, clear=True))
        if repository:
            self.git("init", "-q", "-b", "main")

    def write(self, rel: str, data: bytes = b"data\n", base: Path | None = None) -> Path:
        path = (base or self.root) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def git(self, *args: str, cwd: Path | None = None) -> str:
        return subprocess.run(["git", "-C", str(cwd or self.root), *args], check=True, capture_output=True,
                              text=True, timeout=60).stdout

    def report(self, **kwargs) -> dict:
        return inventory.build_report(self.root, **kwargs)

    def cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-B", str(SCRIPT), "--root", str(self.root), *args],
                              capture_output=True, text=True, timeout=120)


def failing_git(fail):
    """Wrap run_git so that queries chosen by fail(args) return a given result."""
    real = inventory.run_git
    def run(root, *args):
        result = fail(args)
        return result if result is not None else real(root, *args)
    return mock.patch.object(inventory, "run_git", side_effect=run)


class ClassificationTests(unittest.TestCase):
    def test_tracked_untracked_ignored_hidden_nested_and_git_storage(self):
        tree = Tree(self)
        ignore = tree.write(".gitignore", b"ignored_dir/\n*.log\n.private/\n")
        source = tree.write("src/a.py", b"print(1)\n")
        tree.git("add", ".gitignore", "src/a.py")
        tree.write("notes.txt", b"n" * 10)
        tree.write(".hidden/stage.tmp", b"h" * 7)
        tree.write("ignored_dir/x.bin", b"i" * 100)
        tree.write("run.log", b"l" * 3)
        tree.write(".private/conf", b"p" * 5)
        tree.write("vendor/lib/file.c", b"c" * 11)
        tree.git("init", "-q", "-b", "main", cwd=tree.root / "vendor/lib")
        (tree.root / "empty_dir").mkdir()
        report = tree.report(list_entries=True)
        totals = report["totals_by_class"]
        expected = {"tracked": (2, ignore.stat().st_size + source.stat().st_size), "untracked": (2, 17),
                    "ignored": (3, 108), "nested_repository": (1, 11), "unclassified": (0, 0)}
        for name, values in expected.items():
            self.assertEqual((totals[name]["files"], totals[name]["logical_bytes"]), values, name)
        classes = {row["path"]: row["class"] for row in report["entries"]}
        self.assertEqual(classes["vendor/lib/.git/HEAD"], "git_storage")  # nested Git storage, never hashed
        self.assertIsNone(classes["empty_dir"])  # directories are not classified by Git
        self.assertEqual(report["nested_repositories"], ["vendor/lib"])
        self.assertEqual(report["empty_directories"], ["empty_dir"])
        self.assertEqual(report["hidden_by_class"]["untracked"]["logical_bytes"], 7)
        self.assertEqual(report["hidden_by_class"]["ignored"]["logical_bytes"], 5)
        self.assertTrue(report["git_classification_complete"])
        self.assertTrue(report["inventory_complete_within_root"])
        ignored_dir = next(row for row in report["directories"] if row["path"] == "ignored_dir")
        self.assertEqual(ignored_dir["by_class"], {"ignored": {"files": 1, "logical_bytes": 100,
                                                               "allocated_bytes": ignored_dir["allocated_bytes"]}})

    def test_nested_repositories_follow_git_not_bare_dot_git_names(self):
        tree = Tree(self)
        tree.write("evidence/run1/model.pdb", b"m" * 20)
        tree.git("add", "evidence/run1/model.pdb")
        tree.git("commit", "-q", "-m", "fixture")
        tree.git("init", "-q", "-b", "main", cwd=tree.root / "evidence/run1")  # initialized after tracking
        (tree.root / "data/extract/.git").mkdir(parents=True)  # not a repository
        tree.write("data/extract/a.txt", b"a")
        tree.write("data/gitfile/.git", b"not a gitfile\n")
        tree.write("data/gitfile/b.txt", b"b")
        sub = tree.root / "sub"
        tree.write("sub/inner.txt", b"inner")
        tree.git("init", "-q", "-b", "main", cwd=sub)
        tree.git("add", "inner.txt", cwd=sub)
        tree.git("commit", "-q", "-m", "inner", cwd=sub)
        tree.git("update-index", "--add", "--cacheinfo", f"160000,{tree.git('rev-parse', 'HEAD', cwd=sub).strip()},sub")
        report = tree.report(list_entries=True)
        classes = {row["path"]: row["class"] for row in report["entries"]}
        self.assertEqual(classes["evidence/run1/model.pdb"], "tracked")
        self.assertEqual((classes["data/extract/a.txt"], classes["data/gitfile/b.txt"]), ("untracked", "untracked"))
        self.assertEqual(classes["data/gitfile/.git"], "git_storage")
        self.assertEqual(classes["sub/inner.txt"], "nested_repository")  # inside a tracked gitlink
        self.assertIn("sub", report["nested_repositories"])
        self.assertFalse({"data/extract", "data/gitfile"} & set(report["nested_repositories"]))
        self.assertTrue(report["git_classification_complete"])

    def test_unreadable_ignore_rules_make_classification_partial(self):
        tree = Tree(self)
        tree.write(".gitignore", b"*.log\n")
        tree.git("add", ".gitignore")
        tree.write("rules/patterns", b"!*.log\n")
        (tree.root / "evidence").mkdir()
        os.symlink("../rules/patterns", tree.root / "evidence/.gitignore")  # Git refuses symlinked ignore files
        tree.write("evidence/run.log", b"unique")
        report = tree.report()
        self.assertIn(("git ls-files (ignored)", "."), {(e["operation"], e["path"]) for e in report["errors"]})
        self.assertFalse(report["git_classification_complete"])
        self.assertEqual(tree.cli().returncode, 1)

    def test_logical_allocated_and_git_storage_are_distinct(self):
        tree = Tree(self)
        sparse = tree.root / "sparse.bin"
        with sparse.open("wb") as handle:
            handle.truncate(8 * 1024 * 1024)
        for name, data in (("one.txt", b"one\n"), ("two.txt", b"two\n"), ("copy.txt", b"one\n")):
            tree.write(name, data)
        tree.git("add", "one.txt", "two.txt", "copy.txt")
        report = tree.report(list_entries=True)
        entry = next(row for row in report["entries"] if row["path"] == "sparse.bin")
        info = sparse.lstat()
        self.assertEqual((entry["logical_bytes"], entry["allocated_bytes"]), (info.st_size, info.st_blocks * 512))
        if info.st_blocks * 512 < info.st_size:  # only where the filesystem actually left a hole
            self.assertLess(entry["allocated_bytes"], entry["logical_bytes"])
        self.assertEqual(report["git"]["count_objects"]["count"], 2)  # two distinct staged blobs
        self.assertIn("size_kib", report["git"]["count_objects"])
        self.assertNotIn(".git", {row["path"].split("/")[0] for row in report["entries"]
                                  if row["class"] in ("tracked", "untracked", "ignored")})
        root_row = next(row for row in report["directories"] if row["path"] == ".")
        self.assertEqual((root_row["depth"], root_row["files"]), (0, sum(v["files"] for v in report["totals_by_class"].values())))

    def test_conventional_names_are_exact_disjoint_and_not_verdicts(self):
        tree = Tree(self)
        tree.write("pkg/__pycache__/m.cpython-312.pyc", b"pyc")
        tree.write(".pytest_cache/v/__pycache__/x.pyc", b"x")
        tree.write("evidence/cache/result.json", b"{}")  # a retained directory named cache
        tree.write("docs/.DS_Store", b"ds")
        report = tree.report()
        matches = report["name_matches"]
        self.assertEqual([row["path"] for row in matches["__pycache__"]], ["pkg/__pycache__"])
        self.assertEqual([(row["path"], row["files"]) for row in matches[".pytest_cache"]], [(".pytest_cache", 1)])
        self.assertEqual([row["path"] for row in matches[".DS_Store"]], ["docs/.DS_Store"])
        self.assertFalse(any("evidence" in row["path"] for rows in matches.values() for row in rows))
        facts = {**report, "git": {k: v for k, v in report["git"].items() if k != "count_objects"}}
        offending = {key for key in keys(facts) if any(word in key.lower() for word in VERDICT_WORDS)}
        self.assertEqual(offending, set())  # raw Git count-objects field names are exempt

    def test_unicode_and_case_variants_match_git(self):
        tree = Tree(self)
        setting = subprocess.run(["git", "-C", str(tree.root), "config", "--get", "--type=bool",
                                  "core.precomposeunicode"], capture_output=True, text=True, timeout=60)
        if setting.stdout.strip() != "true":
            self.skipTest("Git does not precompose Unicode on this platform")
        name = unicodedata.normalize("NFD", "résumé.txt")
        tree.write(name, b"cv")
        tree.git("add", "--", name)
        report = tree.report()
        self.assertEqual(report["totals_by_class"]["tracked"]["files"], 1)
        self.assertEqual(report["tracked_paths_not_inventoried"], [])
        self.assertEqual([m["set"] for m in report["name_mismatches"]], ["tracked"])
        variant = str(tree.root).swapcase()
        if os.path.exists(variant):  # case-insensitive filesystem: a differently cased root is canonicalized
            other = inventory.build_report(variant)
            self.assertEqual(other["root"], str(tree.root))
            self.assertEqual([e for e in other["exclusions"] if not e["within_root"]], [])


class EvidenceShapeTests(unittest.TestCase):
    def test_empty_evidence_is_inventoried_and_not_grouped_as_duplicates(self):
        tree = Tree(self)
        tree.write("run/stderr.txt", b"")
        tree.write("run/.staging/stdout.txt", b"")
        tree.git("add", "run/stderr.txt")
        report = tree.report(hash_paths=["run"])
        self.assertEqual({(row["path"], row["class"], row["hidden"]) for row in report["empty_files"]},
                         {("run/stderr.txt", "tracked", False), ("run/.staging/stdout.txt", "untracked", True)})
        self.assertEqual(report["duplicates"]["groups"], [])
        self.assertEqual(report["duplicates"]["empty_files_not_grouped"], 2)
        self.assertEqual(report["totals_by_class"]["tracked"]["files"], 1)

    def test_duplicates_stay_within_selection_and_keep_each_role(self):
        tree = Tree(self)
        model = b"ATOM      1  CA  ALA A   1\n" * 50
        tree.write("run/out/model.pdb", model)
        tree.write("run/.staging/model.pdb", model)
        tree.write("other/model.pdb", model)  # identical but outside the selection
        tree.write("run/out/unique.pdb", b"x" * len(model))  # same size, different bytes
        tree.git("add", "run/out/model.pdb")
        duplicates = tree.report(hash_paths=["run", "run/out"])["duplicates"]
        self.assertEqual(len(duplicates["groups"]), 1)
        group = duplicates["groups"][0]
        self.assertEqual(group["sha256"], hashlib.sha256(model).hexdigest())
        self.assertEqual([(c["path"], c["class"], c["hidden"]) for c in group["copies"]],
                         [("run/.staging/model.pdb", "untracked", True), ("run/out/model.pdb", "tracked", False)])
        self.assertEqual(group["distinct_inodes"], 2)
        self.assertIn("not a reclaim estimate", duplicates["note"])
        both = tree.report(hash_paths=["run", "other"])["duplicates"]["groups"][0]
        self.assertEqual(len(both["copies"]), 3)

    def test_hardlinks_count_once_and_outside_links_are_reported(self):
        tree = Tree(self)
        first = tree.write("a.bin", b"a" * 5000)
        os.link(first, tree.root / "b.bin")
        tree.write("d.bin", b"a" * 5000)  # same bytes, separate inode
        os.link(tree.write("c.bin", b"c" * 3000, base=tree.outside), tree.root / "c.bin")
        report = tree.report(hash_paths=["."])
        groups = {tuple(group["paths"]): group for group in report["hardlinks"]}
        self.assertEqual(groups[("a.bin", "b.bin")]["links_not_inventoried"], 0)
        self.assertEqual(groups[("c.bin",)]["links_not_inventoried"], 1)
        seen, oracle, files = set(), 0, 0
        for directory, dirnames, filenames in os.walk(tree.root):
            for name in dirnames + filenames:
                info = os.lstat(os.path.join(directory, name))
                if (info.st_dev, info.st_ino) not in seen:
                    seen.add((info.st_dev, info.st_ino))
                    oracle += info.st_blocks * 512
                    files += info.st_blocks * 512 if stat.S_ISREG(info.st_mode) else 0
        self.assertEqual(report["filesystem"]["unique_inode_allocated_bytes_all_entries"], oracle)
        self.assertEqual(report["filesystem"]["unique_inode_regular_file_allocated_bytes"], files)
        per_path = sum((tree.root / name).lstat().st_blocks * 512 for name in ("a.bin", "b.bin", "c.bin", "d.bin"))
        self.assertEqual(report["totals_by_class"]["untracked"]["allocated_bytes"], per_path)
        group = next(g for g in report["duplicates"]["groups"] if g["size_bytes"] == 5000)
        allocated = first.lstat().st_blocks * 512
        self.assertEqual((group["distinct_inodes"], group["allocated_bytes_in_additional_inodes"]), (2, allocated))
        self.assertEqual(len(group["copies"]), 3)

    def test_duplicate_allocation_is_measured_per_copy(self):
        tree = Tree(self)
        size = 4 * 1024 * 1024
        tree.write("dense.bin", b"\0" * size)
        with (tree.root / "sparse.bin").open("wb") as handle:
            handle.truncate(size)
        dense, sparse = ((tree.root / name).lstat().st_blocks * 512 for name in ("dense.bin", "sparse.bin"))
        if dense == sparse:
            self.skipTest("filesystem left no hole")
        group = tree.report(hash_paths=["."])["duplicates"]["groups"][0]
        self.assertEqual({c["path"]: c["allocated_bytes"] for c in group["copies"]},
                         {"dense.bin": dense, "sparse.bin": sparse})
        self.assertEqual(group["allocated_bytes_in_additional_inodes"], min(dense, sparse))


class BoundaryTests(unittest.TestCase):
    def test_symlinks_are_never_followed_outside_root(self):
        tree = Tree(self)
        secret = tree.write("secret_dir/big.bin", b"s" * 65536, base=tree.outside)
        tree.write("data/file.txt", b"inside\n")
        os.symlink("../outside/secret_dir", tree.root / "ext")
        os.symlink(str(secret), tree.root / "abs_ext")
        os.symlink("data/file.txt", tree.root / "alias.txt")
        os.symlink("data", tree.root / "dirlink")
        os.symlink("missing.txt", tree.root / "broken")
        os.symlink("loop_b", tree.root / "loop_a")
        os.symlink("loop_a", tree.root / "loop_b")
        opened, real_open = [], os.open
        def opener(path, flags, *args, **kwargs):
            opened.append(os.path.basename(path))
            return real_open(path, flags, *args, **kwargs)
        with mock.patch.object(inventory.os, "open", side_effect=opener):
            report = tree.report(hash_paths=[".", "ext", "dirlink/file.txt"], list_entries=True)
        self.assertFalse({"big.bin", "secret_dir", "ext", "dirlink", "abs_ext"} & set(opened))
        paths = {row["path"] for row in report["entries"]}
        self.assertFalse(any(path.startswith(("ext/", "dirlink/", "abs_ext/")) for path in paths))
        self.assertEqual(report["filesystem"]["regular_file_logical_bytes"] -
                         report["totals_by_class"]["git_storage"]["logical_bytes"], len(b"inside\n"))
        links = {row["path"]: row for row in report["symlinks"]}
        self.assertEqual({name: row["scope"] for name, row in links.items()},
                         {"ext": "outside_root", "abs_ext": "outside_root", "alias.txt": "inside_root",
                          "dirlink": "inside_root", "broken": "inside_root", "loop_a": "inside_root",
                          "loop_b": "inside_root"})
        self.assertIsNone(links["ext"]["target_inventoried"])
        self.assertFalse(links["broken"]["target_inventoried"])
        self.assertTrue(links["alias.txt"]["target_inventoried"])
        outside = {row["path"] for row in report["exclusions"] if not row["within_root"]}
        self.assertTrue({"ext", "abs_ext"} <= outside)
        self.assertIn({"path": "ext", "reason": "symlink not followed"}, report["duplicates"]["skipped"])
        self.assertEqual([(e["path"], e["operation"]) for e in report["errors"]], [("dirlink/file.txt", "hash-select")])
        self.assertFalse(report["inventory_complete_within_root"])  # the unresolvable selection is an error

    def test_directory_swapped_for_symlink_is_not_followed(self):
        tree = Tree(self)
        tree.write("work/inside.txt", b"in")
        tree.write("work2/inside.txt", b"in")
        tree.write("private/outside_secret_name.txt", b"s" * 777, base=tree.outside)
        tree.write("realdir/outside_two.txt", b"z", base=tree.outside)
        real = inventory.open_directory
        def swap(root_fd, rel):
            if rel == "work":  # swapped for a symlink: O_NOFOLLOW refuses it
                os.rename(tree.root / "work", tree.base / "work.moved")
                os.symlink(str(tree.outside / "private"), tree.root / "work")
            elif rel == "work2":  # swapped for another real directory: the inode check refuses it
                os.rename(tree.root / "work2", tree.base / "work2.moved")
                os.rename(tree.outside / "realdir", tree.root / "work2")
            return real(root_fd, rel)
        with mock.patch.object(inventory, "open_directory", side_effect=swap):
            report = tree.report(list_entries=True)
        self.assertFalse(any("outside_secret_name" in row["path"] or "outside_two" in row["path"]
                             for row in report["entries"]))
        self.assertTrue({("work", "scandir"), ("work2", "scandir")} <=
                        {(e["path"], e["operation"]) for e in report["errors"]})
        self.assertFalse(report["inventory_complete_within_root"])

    def test_missing_files_are_reported_not_fatal(self):
        tree = Tree(self)
        tree.write("kept.txt", b"k")
        gone = tree.write("gone.txt", b"g")
        tree.git("add", "kept.txt", "gone.txt")
        tree.git("commit", "-q", "-m", "fixture")
        gone.unlink()
        tree.write("staged.txt", b"s")
        tree.git("add", "staged.txt")
        tree.write("vanishing.txt", b"v")
        real_scandir = os.scandir

        class Vanished:
            def __init__(self, entry):
                self.name = entry.name

            def stat(self, follow_symlinks=True):
                raise FileNotFoundError(2, "No such file or directory", self.name)

        @contextlib.contextmanager
        def scandir(path):
            with real_scandir(path) as listing:
                yield [Vanished(entry) if entry.name == "vanishing.txt" else entry for entry in listing]
        with mock.patch.object(inventory.os, "scandir", side_effect=scandir):
            report = tree.report(hash_paths=["absent", "../outside"])
        self.assertEqual(report["tracked_paths_not_inventoried"], ["gone.txt"])
        self.assertEqual(report["git"]["staged_changes"], [{"status": "A", "paths": ["staged.txt"]}])
        self.assertEqual({(row["path"], row["operation"]) for row in report["errors"]},
                         {("vanishing.txt", "lstat"), ("absent", "hash-select"), ("../outside", "hash-select")})
        self.assertFalse(report["inventory_complete_within_root"])

    def test_traversal_failures_mark_inventory_incomplete(self):
        tree = Tree(self)
        tree.write("open/file.txt", b"o")
        tree.write("injected/file.txt", b"i")
        real = inventory.open_directory
        def failing(root_fd, rel):
            if rel == "injected":
                raise PermissionError(13, "Permission denied", rel)
            return real(root_fd, rel)
        with mock.patch.object(inventory, "open_directory", side_effect=failing):
            report = tree.report()
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(inventory.main(["--root", str(tree.root)]), 1)
        self.assertEqual([(e["path"], e["operation"]) for e in report["errors"]], [("injected", "scandir")])
        self.assertFalse(report["inventory_complete_within_root"])
        self.assertIn("Traversal within root: INCOMPLETE", inventory.render_text(report))
        if os.geteuid() == 0:
            self.skipTest("root bypasses directory permissions; the injected failure above still ran")
        locked = tree.write("locked/file.txt", b"l").parent
        locked.chmod(0)
        self.addCleanup(locked.chmod, 0o755)
        self.assertIn(("locked", "scandir"), {(e["path"], e["operation"]) for e in tree.report()["errors"]})
        self.assertEqual(tree.cli().returncode, 1)  # a partial report exits nonzero

    def test_mount_points_are_excluded_and_partial(self):
        tree = Tree(self)
        tree.write("mnt/inner.txt", b"m")
        real_scandir = os.scandir

        class OtherDevice:
            def __init__(self, entry):
                self.entry, self.name = entry, entry.name

            def stat(self, follow_symlinks=True):
                info = self.entry.stat(follow_symlinks=follow_symlinks)
                return mock.Mock(wraps=info, st_mode=info.st_mode, st_size=info.st_size, st_blocks=info.st_blocks,
                                 st_dev=info.st_dev + 1, st_ino=info.st_ino, st_nlink=info.st_nlink,
                                 st_mtime_ns=info.st_mtime_ns)

        @contextlib.contextmanager
        def scandir(path):
            with real_scandir(path) as listing:
                yield [OtherDevice(entry) if entry.name == "mnt" else entry for entry in listing]
        with mock.patch.object(inventory.os, "scandir", side_effect=scandir):
            report = tree.report(list_entries=True)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(inventory.main(["--root", str(tree.root)]), 1)
        self.assertIn({"path": "mnt", "within_root": True, "reason": "different filesystem (mount point); not traversed"},
                      report["exclusions"])
        self.assertFalse(any(row["path"].startswith("mnt/") for row in report["entries"]))
        self.assertFalse(report["inventory_complete_within_root"])

    def test_git_query_failures_make_reports_partial(self):
        tree = Tree(self)
        tree.write("a.txt", b"a")
        tree.git("add", "a.txt")
        tree.git("commit", "-q", "-m", "fixture")
        cases = {
            "ls-files failure": (lambda args: (128, b"", 0) if args[:3] == ("ls-files", "-z", "--cached") else None,
                                 "git ls-files (tracked)", "git_classification_complete"),
            "unterminated listing": (lambda args: (0, b"a.txt", 0) if "--ignored" in args else None,
                                     "git ls-files (ignored)", "git_classification_complete"),
            "ls-files warning": (lambda args: (0, b"", 1) if args[-1:] == ("--exclude-standard",) and "--ignored" not in args
                                 else None, "git ls-files (untracked)", "git_classification_complete"),
            "diff-index failure": (lambda args: (128, b"", 0) if args[0] == "diff-index" else None,
                                   "git diff-index --cached", "inventory_complete_within_root"),
            "count-objects failure": (lambda args: (128, b"", 0) if args[0] == "count-objects" else None,
                                      "git count-objects", "inventory_complete_within_root"),
            "worktree failure": (lambda args: (129, b"", 0) if args[0] == "worktree" else None,
                                 "git worktree list", "inventory_complete_within_root"),
        }
        for label, (fail, operation, flag) in cases.items():
            with self.subTest(label), failing_git(fail):
                report = tree.report()
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(inventory.main(["--root", str(tree.root)]), 1)
            self.assertIn(operation, {e["operation"] for e in report["errors"]})
            self.assertFalse(report[flag])
        with failing_git(lambda args: (129, b"", 0) if args[:4] == ("worktree", "list", "--porcelain", "-z") else None):
            report = tree.report()  # Git before 2.36 lacks -z; newline porcelain is used instead
        self.assertEqual([w["path"] for w in report["git"]["worktrees"]], [str(tree.root)])
        self.assertTrue(report["inventory_complete_within_root"])

    def test_unclassified_file_makes_classification_partial(self):
        tree = Tree(self)
        tree.write("a.txt", b"a")
        def fail(args):
            if "--ignored" in args:  # appears after Git has listed the tree
                tree.write("late.txt", b"late")
            return None
        with failing_git(fail):
            report = tree.report()
        self.assertEqual((report["unclassified_entries"], report["git_classification_complete"]), (1, False))
        self.assertTrue(report["inventory_complete_within_root"])
        with failing_git(lambda args: tree.write("later.txt", b"l") and None if "--ignored" in args else None), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(inventory.main(["--root", str(tree.root)]), 1)

    def test_hash_and_readlink_failures_are_reported(self):
        tree = Tree(self)
        tree.write("a.bin", b"x" * 100)
        tree.write("b.bin", b"x" * 100)
        os.symlink("a.bin", tree.root / "link")
        with mock.patch.object(inventory, "sha256_file", side_effect=OSError("injected")):
            report = tree.report(hash_paths=["."])
        self.assertIn(("a.bin", "hash"), {(e["path"], e["operation"]) for e in report["errors"]})
        self.assertFalse(report["inventory_complete_within_root"])
        with mock.patch.object(inventory.os, "readlink", side_effect=OSError("injected")):
            report = tree.report()
        self.assertIn(("link", "readlink"), {(e["path"], e["operation"]) for e in report["errors"]})
        self.assertFalse(report["inventory_complete_within_root"])

    def test_hashing_never_follows_swapped_symlinks_or_blocks_on_fifos(self):
        tree = Tree(self)
        for name in ("dir/a.bin", "dir/b.bin", "c.bin", "d.bin", "e.bin", "f.bin", "g.bin"):
            tree.write(name, b"x" * 100)
        tree.write("dir/a.bin", b"y" * 100, base=tree.outside)
        tree.write("g.bin", b"y" * 100, base=tree.outside)
        real, opened = inventory.sha256_file, []
        real_open = os.open
        def opener(path, flags, *args, **kwargs):
            opened.append((os.path.basename(path), kwargs.get("dir_fd")))
            return real_open(path, flags, *args, **kwargs)
        def swap(root, rel, expected):
            if rel == "dir/a.bin":  # parent directory becomes a symlink to the outside tree
                os.rename(tree.root / "dir", tree.base / "dir.moved")
                os.symlink(str(tree.outside / "dir"), tree.root / "dir")
            elif rel == "c.bin":  # a symlink to the same inode moved outside: only O_NOFOLLOW stops it
                os.rename(tree.root / "c.bin", tree.outside / "c.moved")
                os.symlink(str(tree.outside / "c.moved"), tree.root / "c.bin")
            elif rel == "g.bin":  # a different regular file of the same size: only the inode check stops it
                os.rename(tree.root / "g.bin", tree.base / "g.moved")
                os.rename(tree.outside / "g.bin", tree.root / "g.bin")
            elif rel == "e.bin":  # the file becomes a FIFO with no writer
                os.rename(tree.root / "e.bin", tree.base / "e.moved")
                os.mkfifo(tree.root / "e.bin")
            return real(root, rel, expected)
        with mock.patch.object(inventory, "sha256_file", side_effect=swap), \
                mock.patch.object(inventory.os, "open", side_effect=opener), deadline(30):
            report = tree.report(hash_paths=["."])
        self.assertNotIn("a.bin", {name for name, _ in opened})  # never reached through the swapped parent
        failed = {e["path"] for e in report["errors"] if e["operation"] == "hash"}
        self.assertTrue({"dir/a.bin", "c.bin", "e.bin", "g.bin"} <= failed, report["errors"])
        grouped = {c["path"] for g in report["duplicates"]["groups"] for c in g["copies"]}
        self.assertTrue({"d.bin", "f.bin"} <= grouped)
        self.assertFalse({"dir/a.bin", "c.bin", "e.bin", "g.bin"} & grouped)


class ReadOnlyTests(unittest.TestCase):
    def build_rich_tree(self) -> Tree:
        tree = Tree(self)
        tree.write(".gitignore", b"cache/\n")
        tracked = tree.write("tracked.txt", b"t\n")
        tree.write("cache/blob.bin", b"b" * 4096)
        tree.write("run/stderr.txt", b"")
        tree.write("run/.staging/out.pdb", b"model\n")
        tree.write("run/out.pdb", b"model\n")
        os.symlink("../outside", tree.root / "escape")
        os.link(tree.write("hard.bin", b"h" * 100), tree.root / "hard2.bin")
        os.mkfifo(tree.root / "run/pipe")  # must never be opened
        tree.git("add", ".gitignore", "tracked.txt", "run/stderr.txt")
        tree.git("commit", "-q", "-m", "fixture")
        tree.git("worktree", "add", "-q", "--detach", str(tree.outside / "wt"))
        shutil.rmtree(tree.outside / "wt")  # leaves prunable worktree metadata behind
        later = tracked.stat().st_mtime_ns + 5_000_000_000
        os.utime(tracked, ns=(later, later))  # stale index stat data invites an index refresh
        return tree

    def test_audit_leaves_input_tree_unchanged(self):
        tree = self.build_rich_tree()
        before = snapshot(tree.base)
        writes = [mock.patch.object(Path, name, side_effect=AssertionError(f"write: {name}"))
                  for name in ("write_text", "write_bytes", "mkdir", "touch", "unlink", "rename", "replace")]
        with contextlib.ExitStack() as stack:
            for patch in writes:
                stack.enter_context(patch)
            report = tree.report(hash_paths=["."], list_entries=True)
            inventory.render_text(report)
            with contextlib.redirect_stdout(io.StringIO()) as captured:
                self.assertEqual(inventory.main(["--root", str(tree.root), "--format", "json", "--hash", "."]), 0)
        json.loads(captured.getvalue())
        result = tree.cli("--hash", ".", "--entries")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("filesystem facts only", result.stdout)
        self.assertEqual(snapshot(tree.base), before)
        self.assertEqual([(s["path"], s["type"]) for s in report["special_files"]], [("run/pipe", "fifo")])
        prunable = [w for w in report["git"]["worktrees"] if w["prunable"]]
        self.assertEqual(len(prunable), 1)
        self.assertIn({"path": prunable[0]["path"], "within_root": False,
                       "reason": "linked worktree outside root; not inventoried"}, report["exclusions"])
        # The detector is live: Git's own opportunistic index refresh changes the snapshot.
        subprocess.run(["git", "-C", str(tree.root), "status"], check=True, capture_output=True, timeout=60)
        self.assertNotEqual(snapshot(tree.base), before)

    def test_configured_content_filters_never_run(self):
        tree = Tree(self)
        sentinel = tree.base / "filter-ran"
        tree.git("config", "filter.trip.clean", f"touch {shlex.quote(str(sentinel))}; cat")
        tree.git("config", "filter.trip.smudge", "cat")
        tree.write(".gitattributes", b"*.txt filter=trip\n")
        tracked = tree.write("tracked.txt", b"t\n")
        tree.git("add", ".gitattributes", "tracked.txt")
        tree.git("commit", "-q", "-m", "fixture")
        sentinel.unlink(missing_ok=True)  # git add ran the filter once, legitimately
        later = tracked.stat().st_mtime_ns + 5_000_000_000
        os.utime(tracked, ns=(later, later))
        tree.report(hash_paths=["."])
        self.assertEqual(tree.cli("--hash", ".").returncode, 0)
        self.assertFalse(sentinel.exists())
        # The tripwire is armed: git status hashes the stat-dirty file through the filter.
        subprocess.run(["git", "--no-optional-locks", "-C", str(tree.root), "status"], check=True,
                       capture_output=True, timeout=60)
        self.assertTrue(sentinel.exists())

    def test_fsmonitor_hooks_and_trace2_targets_never_fire(self):
        tree = Tree(self)
        plain = Path(tempfile.mkdtemp()).resolve()  # Git runs hooks through sh: keep metacharacters out
        self.addCleanup(shutil.rmtree, plain)
        hook, ran = plain / "fsmonitor-hook", tree.base / "fsmonitor-ran"
        hook.write_text(f"#!/bin/sh\n: > {shlex.quote(str(ran))}\n")
        hook.chmod(0o755)
        tree.git("config", "core.fsmonitor", str(hook))
        tree.write("a.txt", b"a")
        tree.git("add", "a.txt")
        ran.unlink(missing_ok=True)
        config = tree.base / "global.gitconfig"
        targets = [tree.base / f"trace-{kind}" for kind in ("normal", "perf", "event")]
        for kind, target in zip(("normalTarget", "perfTarget", "eventTarget"), targets):
            subprocess.run(["git", "config", "--file", str(config), f"trace2.{kind}", str(target)], check=True,
                           capture_output=True, timeout=60)
        with mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(config)}):
            tree.report()
            self.assertEqual(tree.cli().returncode, 0)
            self.assertFalse(ran.exists() or any(target.exists() for target in targets))
            # Both tripwires are armed for ordinary Git index reads.
            subprocess.run(["git", "-C", str(tree.root), "ls-files"], check=True, capture_output=True, timeout=60)
        self.assertTrue(ran.exists() and all(target.exists() for target in targets))

    def test_only_read_only_git_queries_run_with_a_clean_environment(self):
        tree = self.build_rich_tree()
        decoy = Tree(self)  # a different repository that inherited variables point at
        decoy.write("decoy.txt", b"d")
        decoy.git("add", "decoy.txt")
        calls, real_run = [], subprocess.run
        def recorder(command, *args, **kwargs):
            calls.append((list(command), dict(kwargs.get("env") or {}), kwargs.get("stdin")))
            return real_run(command, *args, **kwargs)
        inherited = {"GIT_DIR": str(decoy.root / ".git"), "GIT_INDEX_FILE": str(decoy.root / ".git/index"),
                     "GIT_WORK_TREE": str(decoy.root), "GIT_OBJECT_DIRECTORY": str(decoy.root / ".git/objects"),
                     "GIT_ALLOW_PROTOCOL": "file:https"}
        with mock.patch.dict(os.environ, inherited), \
                mock.patch.object(inventory.subprocess, "run", side_effect=recorder):
            report = tree.report(hash_paths=["."])
        self.assertEqual(report["totals_by_class"]["tracked"]["files"], 3)  # the audited repository
        self.assertTrue(calls)
        expected_env = {"GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "GIT_NO_LAZY_FETCH": "1",
                        "GIT_ALLOW_PROTOCOL": "", "GIT_TRACE2": "0", "GIT_TRACE2_EVENT": "0", "GIT_TRACE2_PERF": "0"}
        for command, env, stdin in calls:
            self.assertEqual(command[:6], ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(tree.root)])
            self.assertTrue(tuple(command[6:7]) in READ_ONLY_GIT or tuple(command[6:8]) in READ_ONLY_GIT, command)
            self.assertEqual({key: env.get(key) for key in expected_env}, expected_env)
            self.assertEqual(stdin, subprocess.DEVNULL)
            self.assertFalse({"GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE", "GIT_OBJECT_DIRECTORY"} & set(env))
        source = SCRIPT.read_text()
        for forbidden in ("os.remove", "os.unlink", "os.rmdir", "os.rename", "os.replace", "write_bytes",
                          "write_text", "os.chmod", "os.utime", "os.link(", "os.symlink", "truncate", "O_WRONLY",
                          "O_RDWR", "O_CREAT", "import shutil", "import socket", "import urllib", " open("):
            self.assertNotIn(forbidden, source, forbidden)

    def test_sensitive_contents_are_never_read_or_printed(self):
        tree = Tree(self)
        secret = b"SECRET-VALUE-123\n"
        private = (".env", ".envrc", "config/service-credentials.json", "CLAUDE.local.md", "docs/agents/tracker.md",
                   "deploy/terraform.tfvars", "keys/signing.asc", ".claude/settings.json")
        for name in private + ("public.txt",):
            tree.write(name, secret)
        for clone in ("vendor/tool_a", "vendor/tool_b"):  # nested clones with identical .git/config
            tree.git("init", "-q", "-b", "main", cwd=tree.write(f"{clone}/x.txt", b"x").parent)
            (tree.root / clone / ".git/config").write_bytes(b"[remote]\n\turl = https://SECRET-VALUE-123@host\n")
        opened, real_open = [], os.open
        def opener(path, flags, *args, **kwargs):
            if not flags & os.O_DIRECTORY:  # file opens only; the walker opens every directory
                opened.append(os.path.basename(path))
            return real_open(path, flags, *args, **kwargs)
        with mock.patch.object(inventory.os, "open", side_effect=opener):
            report = tree.report(hash_paths=["."], list_entries=True)
        self.assertIn("x.txt", opened)  # the recorder is live: nested working files are hashed
        self.assertFalse({Path(name).name for name in private} & set(opened))
        self.assertNotIn("config", opened)
        skipped = {row["path"] for row in report["duplicates"]["skipped"]}
        self.assertTrue(set(private) <= skipped)
        self.assertIn("vendor/tool_a/.git/config", skipped)
        result = tree.cli("--format", "json", "--hash", ".", "--entries")
        self.assertNotIn("SECRET-VALUE", result.stdout + inventory.render_text(report))

    def test_text_output_escapes_control_characters(self):
        tree = Tree(self)
        tree.write("x\x1b[2KErrors: 0\x07", b"")
        tree.write("spoof\nTraversal within root: complete", b"")
        text = inventory.render_text(tree.report())
        self.assertNotIn("\x1b", text)
        self.assertNotIn("\x07", text)
        self.assertEqual(sum(line.startswith("Traversal within root:") for line in text.splitlines()), 1)


class CliTests(unittest.TestCase):
    def test_text_and_json_reports_label_units_and_completeness(self):
        tree = Tree(self)
        tree.write("a.txt", b"a")
        with contextlib.redirect_stdout(io.StringIO()) as captured:
            self.assertEqual(inventory.main(["--root", str(tree.root)]), 0)
        for phrase in ("KiB/MiB/GiB are 1024-based", "Traversal within root: complete",
                       "Git classification complete: True", "facts only", "unstaged modifications not computed",
                       "KiB allocated); packs=", "KiB logical .pack+.idx"):
            self.assertIn(phrase, captured.getvalue())
        with contextlib.redirect_stdout(io.StringIO()) as captured:
            inventory.main(["--root", str(tree.root), "--format", "json"])
        report = json.loads(captured.getvalue())
        self.assertEqual(report["contract"], inventory.CONTRACT)
        self.assertIsNone(report["duplicates"])
        with self.assertRaises(SystemExit) as raised, contextlib.redirect_stderr(io.StringIO()):
            inventory.main(["--root", str(tree.root / "missing")])
        self.assertEqual(raised.exception.code, 2)

    def test_non_repository_root_is_partial_and_unclassified(self):
        tree = Tree(self, repository=False)
        tree.write("file.txt", b"x")
        report = tree.report()
        self.assertFalse(report["git"]["available"])
        self.assertEqual(report["totals_by_class"]["unclassified"]["files"], 1)
        self.assertFalse(report["git_classification_complete"])
        self.assertIn("git rev-parse", {error["operation"] for error in report["errors"]})
        self.assertEqual(tree.cli().returncode, 1)

    def test_undecodable_file_names_are_inventoried(self):
        tree = Tree(self)
        try:
            descriptor = os.open(os.fsencode(tree.root) + b"/bad-\xff.txt", os.O_WRONLY | os.O_CREAT, 0o644)
        except OSError:
            self.skipTest("filesystem rejects non-UTF-8 names")
        os.close(descriptor)
        result = tree.cli("--format", "json", "--entries")
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = [row for row in json.loads(result.stdout)["entries"] if row["path"].startswith("bad-")]
        self.assertEqual([(row["class"], row["logical_bytes"]) for row in rows], [("untracked", 0)])

    def test_skill_matches_the_helper_interface(self):
        text = SKILL.read_text(encoding="utf-8")
        commands = [line for line in text.splitlines() if "inventory_storage.py" in line]
        self.assertTrue(commands, "the retention skill must show how to run the helper")
        options = set(inventory.build_parser()._option_string_actions)
        documented = set(re.findall(r"(?<![\w-])--(?:hash|format|entries|root|depth|top)\b", text))
        documented |= {flag for line in commands for flag in re.findall(r"(?<![\w-])--[a-z][a-z-]*", line)}
        self.assertTrue(documented, "the skill should show at least one helper flag")
        self.assertEqual(documented - options, set())
        tree = Tree(self)
        tree.write("a.txt", b"a")
        report_keys = keys(tree.report()) | set(inventory.CLASSES)
        for name in ("inventory_complete_within_root", "git_classification_complete", "tracked_paths_not_inventoried",
                     "unclassified", "hardlinks"):
            self.assertTrue(name in text, f"the skill no longer names {name}")
            self.assertTrue(name in report_keys, f"the helper no longer reports {name}")
        self.assertIn("Exit status 1", text)
        self.assertIn("1 when the\nreport is partial", inventory.__doc__)


if __name__ == "__main__":
    unittest.main()
