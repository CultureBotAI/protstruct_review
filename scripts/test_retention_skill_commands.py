#!/usr/bin/env python3
"""Execute the retention skill's Git recipes on isolated, disposable fixtures."""
from __future__ import annotations

import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import unittest
from unittest import mock

from test_inventory_storage import SKILL, Tree, snapshot


TEXT = SKILL.read_text()
BLOCKS = re.findall(r"```bash\n(.*?)\n```", TEXT, re.DOTALL)
WRAPPER = "\n".join(line for line in BLOCKS[0].splitlines()
                    if line.startswith(("unalias ", "git_ro()")))
PACK_RECIPE = next(block for block in BLOCKS if "pack-objects" in block)
PATH_RECIPE = next(block for block in BLOCKS if "common_dir=$(git_ro" in block)
INDEX_RECIPE = next(block for block in BLOCKS if "record_staged=" in block)


def inline_recipe(prefix: str) -> str:
    """Read a literal documented command, normalizing Markdown line wrapping."""
    return next(command for raw in re.findall(r"(?<!`)`([^`]+)`(?!`)", TEXT)
                if (command := " ".join(raw.split())).startswith(prefix))


class SkillCommandTests(unittest.TestCase):
    def setUp(self):
        self.tree = Tree(self)
        self.tree.write("data.txt")
        self.tree.git("add", "data.txt")
        self.tree.git("commit", "-qm", "base")

    def shell(self, command: str, *, shell: str = "bash", prelude: str = "", cwd=None):
        return subprocess.run([shell, "-c", prelude + "\n" + WRAPPER + "\n" + command],
                              cwd=cwd or self.tree.root, capture_output=True, text=True, timeout=15)

    def linked_worktree(self):
        linked = self.tree.outside / "linked worktree"
        self.tree.git("worktree", "add", "-q", "--detach", str(linked))
        return linked

    def test_git_paths_resolve_recovery_metadata_from_linked_worktree(self):
        linked = self.linked_worktree()
        self.assertTrue((linked / ".git").is_file())
        expressions = [inline_recipe(prefix) for prefix in
                       ('"$common_dir/logs"', '"$git_dir/logs/HEAD"', '"$object_dir/17"')]
        before = snapshot(self.tree.base)
        result = self.shell(PATH_RECIPE + " && printf '%s\\n' " + " ".join(expressions), cwd=linked)
        self.assertEqual(result.returncode, 0, result.stderr)
        shared_logs, linked_head_log, sample_dir = map(Path, result.stdout.splitlines())
        self.assertEqual(shared_logs, self.tree.root / ".git/logs")
        self.assertEqual(sample_dir, self.tree.root / ".git/objects/17")
        self.assertTrue((shared_logs / "HEAD").is_file())
        self.assertTrue((shared_logs / "refs/heads/main").is_file())
        self.assertTrue(linked_head_log.is_file())
        self.assertEqual(linked_head_log.parent.parent.parent, self.tree.root / ".git/worktrees")
        self.assertEqual(snapshot(self.tree.base), before)

    def test_main_and_linked_indexes_use_their_own_head_from_linked_worktree(self):
        tree = self.tree
        linked = self.linked_worktree()
        tree.write("main-committed.txt")
        tree.git("add", "main-committed.txt")
        tree.git("commit", "-qm", "main advances")
        tree.write("main-staged.txt")
        tree.git("add", "main-staged.txt")
        tree.write("linked-staged.txt", base=linked)
        tree.git("add", "linked-staged.txt", cwd=linked)
        before = snapshot(tree.base)
        for assignment, expected in (("record_git_dir=\"$common_dir\"", "A\tmain-staged.txt\n"),
                                     ("record_git_dir=\"$git_dir\"", "A\tlinked-staged.txt\n")):
            with self.subTest(assignment=assignment):
                command = PATH_RECIPE + " && " + inline_recipe(assignment) + "\n" + INDEX_RECIPE
                result = self.shell(command, cwd=linked)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, expected)
        self.assertEqual(snapshot(tree.base), before)

    def test_missing_or_unborn_head_and_index_failure_are_unverified(self):
        tree = self.tree
        linked = self.linked_worktree()
        paths = self.shell(PATH_RECIPE + " && printf '%s\\n' \"$git_dir\"", cwd=linked)
        self.assertEqual(paths.returncode, 0, paths.stderr)
        admin = Path(paths.stdout.strip())
        head_path, index_path = admin / "HEAD", admin / "index"
        saved_head, saved_index = head_path.read_bytes(), index_path.read_bytes()
        command = PATH_RECIPE + " && " + inline_recipe('record_git_dir="$git_dir"') + "\n" + INDEX_RECIPE
        for condition in ("missing HEAD", "unborn HEAD", "missing index", "invalid index"):
            with self.subTest(condition=condition):
                if condition == "missing HEAD":
                    head_path.unlink()
                elif condition == "unborn HEAD":
                    tree.git("--git-dir=" + str(admin), "symbolic-ref", "HEAD", "refs/heads/unborn")
                elif condition == "missing index":
                    index_path.unlink()
                else:
                    index_path.write_bytes(b"invalid index\n")
                # Use already resolved paths: a missing HEAD may also break path discovery.
                prelude = "record_git_dir=" + shlex.quote(str(admin))
                before = snapshot(tree.base)
                result = self.shell(INDEX_RECIPE, prelude=prelude, cwd=linked)
                self.assertIn("Staged changes: unverified", result.stdout)
                self.assertEqual(snapshot(tree.base), before)
                head_path.write_bytes(saved_head)
                index_path.write_bytes(saved_index)
        # A valid, clean linked index produces empty comparison output.
        result = self.shell(command, cwd=linked)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "")

    def test_wrapper_bypasses_aliases_functions_and_fsmonitor(self):
        tree = self.tree
        marker = tree.outside / "unexpected-command"
        hook = tree.write("fsmonitor", ("#!/bin/sh\ntouch " + shlex.quote(str(marker)) + "\n").encode(),
                          base=tree.outside)
        hook.chmod(0o755)
        tree.git("config", "core.fsmonitor", str(hook))
        before = snapshot(tree.root)
        for shell in ("bash", "zsh"):
            if not shutil.which(shell):
                continue
            with self.subTest(shell=shell):
                prelude = ("shopt -s expand_aliases\n" if shell == "bash" else "")
                prelude += ("git() { touch " + shlex.quote(str(marker)) + "; return 79; }\n"
                            "alias g='git'\nalias git='false'\nalias git_ro='git'\n")
                result = self.shell("git_ro fsck --unreachable --no-progress", shell=shell, prelude=prelude)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(marker.exists())
        self.assertEqual(snapshot(tree.root), before)

    def test_local_protocol_guard_and_explicit_remote_exception(self):
        tree = self.tree
        head = tree.git("rev-parse", "HEAD").strip()
        tree.git("update-ref", "refs/pull/1/head", head)
        tree.git("remote", "add", "origin", str(tree.root))
        before = snapshot(tree.root)
        blocked = self.shell("git_ro ls-remote origin 'refs/pull/*/head'")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("not allowed", blocked.stderr)
        permitted = self.shell(inline_recipe("GIT_TERMINAL_PROMPT=0"),
                               prelude="git() { return 79; }\n")
        self.assertEqual(permitted.returncode, 0, permitted.stderr)
        self.assertIn(head + "\trefs/pull/1/head", permitted.stdout)
        self.assertEqual(snapshot(tree.root), before)

    def test_status_does_not_run_unchecked_submodule_filter(self):
        tree = self.tree
        sub = tree.root / "sub"
        sub.mkdir()
        tree.git("init", "-q", "-b", "main", cwd=sub)
        tree.write(".gitattributes", b"*.txt filter=side_effect\n", base=sub)
        tree.write("nested.txt", base=sub)
        tree.git("add", ".", cwd=sub)
        tree.git("commit", "-qm", "nested", cwd=sub)
        tree.git("add", "sub")
        tree.git("commit", "-qm", "gitlink")
        marker = tree.outside / "filter-ran"
        tree.git("config", "filter.side_effect.clean", "touch " + shlex.quote(str(marker)) + "; cat", cwd=sub)
        tree.write("nested.txt", b"edit\n", base=sub)
        attrs = self.shell(inline_recipe("set -o pipefail; git_ro ls-files"))
        self.assertEqual(attrs.returncode, 0, attrs.stderr)
        self.assertTrue(all(value in ("unspecified", "unset") for value in attrs.stdout.split("\0")[2::3]))
        before = snapshot(tree.root)
        result = self.shell(inline_recipe("git_ro status"))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(marker.exists())
        self.assertEqual(snapshot(tree.root), before)
        # Positive control: recursive status really would execute the fixture filter.
        self.assertEqual(self.shell("git_ro status --short --branch").returncode, 0)
        self.assertTrue(marker.exists())

    def test_pack_recipe_measures_without_writing_objects(self):
        before = snapshot(self.tree.root)
        result = self.shell(PACK_RECIPE)
        self.assertEqual(result.returncode, 0, result.stderr)
        measured = re.fullmatch(r"Packed size:\s+(\d+) bytes\n", result.stdout)
        self.assertIsNotNone(measured, result.stdout)
        self.assertGreater(int(measured.group(1)), 32)
        self.assertEqual(snapshot(self.tree.root), before)

    def test_pack_recipe_skips_partial_clone(self):
        self.tree.git("config", "remote.origin.promisor", "true")
        before = snapshot(self.tree.root)
        result = self.shell(PACK_RECIPE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("not measured (partial-clone configuration)", result.stdout)
        self.assertEqual(snapshot(self.tree.root), before)

    def test_pack_recipe_propagates_producer_failure(self):
        blob = self.tree.git("rev-parse", "HEAD:data.txt").strip()
        (self.tree.root / ".git/objects" / blob[:2] / blob[2:]).unlink()
        before = snapshot(self.tree.root)
        result = self.shell(PACK_RECIPE)
        self.assertIn("not measured (pack command failed)", result.stdout)
        self.assertNotIn(" bytes", result.stdout)
        self.assertTrue(result.stderr)
        self.assertEqual(snapshot(self.tree.root), before)

    def test_pack_recipe_does_not_treat_config_failure_as_no_promisor(self):
        self.tree.write(".git/config", b"[broken\n")
        result = self.shell(PACK_RECIPE)
        self.assertIn("not measured (configuration query failed)", result.stdout)
        self.assertNotIn(" bytes", result.stdout)

    def test_reflog_attribution_reaches_unnamed_ancestors_from_old_side(self):
        tree = self.tree
        base = tree.git("rev-parse", "HEAD").strip()
        root_tree = tree.git("rev-parse", "HEAD^{tree}").strip()
        ancestor = tree.git("commit-tree", root_tree, "-p", base, "-m", "interior").strip()
        tip = tree.git("commit-tree", root_tree, "-p", ancestor, "-m", "tip").strip()
        for sha, timestamp in ((tip, 1700000000), (base, 1700000100)):
            with mock.patch.dict(os.environ, GIT_COMMITTER_DATE=f"{timestamp} +0000"):
                tree.git("update-ref", "--create-reflog", "refs/heads/fixture", sha)
        candidates = self.shell(inline_recipe("git_ro rev-list --all"))
        self.assertEqual(candidates.returncode, 0, candidates.stderr)
        self.assertTrue({ancestor, tip}.issubset(candidates.stdout.splitlines()))
        entries = (tree.root / ".git/logs/refs/heads/fixture").read_text().splitlines()
        self.assertFalse(any(ancestor in row.split()[:2] for row in entries))
        attributed = {}
        for row in entries:
            fields = row.split("\t", 1)[0].split()
            for sha in fields[:2]:
                if set(sha) == {"0"}:
                    continue
                reached = self.shell(inline_recipe("git_ro rev-list <entry>").replace("<entry>", sha))
                self.assertEqual(reached.returncode, 0, reached.stderr)
                for commit in reached.stdout.splitlines():
                    attributed[commit] = max(attributed.get(commit, 0), int(fields[-2]))
        self.assertEqual(attributed[ancestor], 1700000100)
        self.assertEqual(attributed[tip], 1700000100)

    def test_stash_ancestors_are_listed_and_reached_by_stash_entry(self):
        tree = self.tree
        tree.write("data.txt", b"work in progress\n")
        tree.write("untracked.txt", b"unique input\n")
        tree.git("stash", "push", "-qu")
        stash = tree.git("rev-parse", "refs/stash").strip()
        index_commit = tree.git("rev-parse", "refs/stash^2").strip()
        untracked_commit = tree.git("rev-parse", "refs/stash^3").strip()
        for recipe in (inline_recipe("git_ro rev-list --all"),
                       inline_recipe("git_ro rev-list <entry>").replace("<entry>", stash)):
            result = self.shell(recipe)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue({stash, index_commit, untracked_commit}.issubset(result.stdout.splitlines()))

    def test_stash_default_protection_yields_to_explicit_expiry_config(self):
        tree = self.tree
        tree.write("data.txt", b"older work\n")
        with mock.patch.dict(os.environ, GIT_COMMITTER_DATE="1700000000 +0000",
                             GIT_AUTHOR_DATE="1700000000 +0000"):
            tree.git("stash", "push", "-qm", "older")
        tree.write("data.txt", b"newer work\n")
        tree.git("stash", "push", "-qm", "newer")
        stash_log = tree.root / ".git/logs/refs/stash"
        before = stash_log.read_bytes()
        default = tree.git("reflog", "expire", "--dry-run", "--verbose", "--all")
        self.assertIn("keep On main: older", default)
        self.assertEqual(stash_log.read_bytes(), before)
        tree.git("config", "gc.reflogExpireUnreachable", "now")
        global_only = tree.git("reflog", "expire", "--dry-run", "--verbose", "--all")
        self.assertIn("keep On main: older", global_only)
        tree.git("config", "gc.refs/stash.reflogExpireUnreachable", "now")
        configured = tree.git("reflog", "expire", "--dry-run", "--verbose", "--all")
        self.assertIn("would prune On main: older", configured)
        self.assertEqual(stash_log.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
