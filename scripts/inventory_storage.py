#!/usr/bin/env python3
"""Read-only storage inventory for data-retention reviews.

Reports filesystem facts, never retention judgments: Git class, hidden and empty
paths, logical versus allocated bytes with hardlinks counted once, symlinks
(never followed), conventional tool-cache/OS-metadata name matches, Git object
storage and worktrees, traversal errors and exclusions, and optional SHA-256
exact-duplicate groups within explicitly selected paths.

It writes nothing itself: no cleanup, archive, installation, scientific
execution or Git mutation. Directories are opened through descriptors without
following symlinks. Git runs without optional locks, fsmonitor, transports,
lazy fetch or trace output, and only through queries that cannot execute
repository content filters, so unstaged modifications are not computed. (On a
split-index repository Git itself refreshes the shared index's mtime when the
index is read; the report says so.) A name match, duplicate, empty file, failed
run or ignored status is not evidence that anything is disposable.

Exit status: 0 when traversal and Git classification are complete, 1 when the
report is partial (see errors/exclusions), 2 for usage errors. Tracked paths
missing from the traversal are listed separately and do not change the status.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import fcntl
import glob
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import unicodedata

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACT = "storage-inventory/1"
BLOCK_BYTES = 512  # st_blocks unit on Linux and macOS
CHUNK = 1024 * 1024
GIT_TIMEOUT = 300
CLASSES = ("tracked", "untracked", "ignored", "git_storage", "nested_repository", "unclassified")
GIT_PREFIX = ("git", "--no-optional-locks", "-c", "core.fsmonitor=false")
# Inherited GIT_* variables can redirect a query to another repository, index or
# object store (GIT_DIR, GIT_INDEX_FILE, ...); keep only config-file selection.
GIT_ENV_KEPT = frozenset({"GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM",
                          "GIT_ATTR_NOSYSTEM", "GIT_CEILING_DIRECTORIES"})
GIT_ENV = {"GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "GIT_NO_LAZY_FETCH": "1",
           "GIT_ALLOW_PROTOCOL": "", "GIT_TRACE2": "0", "GIT_TRACE2_EVENT": "0", "GIT_TRACE2_PERF": "0",
           "LC_ALL": "C"}
# Each listing reads only the index and directory entries. Git status, diff-files
# and ls-files --modified can hash working-tree files through configured clean
# filters, so they are deliberately absent.
GIT_LISTINGS = {
    "tracked": ("ls-files", "-z", "--cached"),
    "untracked": ("ls-files", "-z", "--others", "--exclude-standard"),
    "ignored": ("ls-files", "-z", "--others", "--ignored", "--exclude-standard"),
}
# Exact basenames only. Generic names such as "cache" are deliberately absent:
# retained evidence directories can carry them.
NAME_GROUPS = {"__pycache__": "dir", ".pytest_cache": "dir", ".mypy_cache": "dir",
               ".ruff_cache": "dir", ".ipynb_checkpoints": "dir", ".DS_Store": "file",
               "._*": "file"}
# Best-effort names whose contents are never read; a miss only means the file can be hashed.
SENSITIVE_NAME = re.compile(
    r"(^\.env(rc)?([.-]|$)|\.env$|\.local\.|netrc$|^\.?authinfo|^\.pgpass$|^\.npmrc$|^\.pypirc$|^\.yarnrc"
    r"|^\.condarc$|^pip\.conf$|^\.?renviron$|^\.my\.cnf$|^\.boto$|^\.s3cfg$|^\.dockercfg$|kubeconfig"
    r"|^\.terraformrc$|\.tf(vars|state)$|_history$|^\.mcp\.json$|^auth\.json$|^\.git-credentials$"
    r"|^id_(rsa|dsa|ecdsa|ed25519)|^deploy_key|\.(pem|key|p8|p12|pfx|ppk|jks|keystore|kdbx|gpg|asc|der|ovpn)$"
    r"|keychain|credential|secret|token|passw|api[_-]?key|service[_-]?account)", re.IGNORECASE)
SENSITIVE_DIRS = frozenset({".ssh", ".gnupg", ".aws", ".azure", ".docker", ".kube", ".password-store"})
SENSITIVE_PREFIXES = ("docs/agents/", ".config/gh/", ".config/gcloud/", ".claude/settings")
NOTES = (
    "Facts only: nothing is classified as disposable, and nothing was deleted, compressed or moved.",
    "Logical bytes are st_size; allocated bytes are st_blocks x 512. KiB/MiB/GiB are 1024-based.",
    "Unique-inode totals count each inode once. APFS clones, snapshots and shared package caches "
    "are invisible to stat, so physically reclaimable space can be smaller than allocated bytes.",
    "A hardlinked file frees no space while another link survives; see links_not_inventoried.",
    "Symlinks are reported, never followed; targets are resolved lexically and targets outside "
    "the root are not inspected.",
    "Ignored status reflects the effective Git configuration, including global excludes; Git "
    "warnings about unreadable ignore rules make classification partial.",
    "Unstaged modifications are not computed: Git content comparison can execute configured "
    "filters. Tracked paths missing from the traversal are listed.",
    "Git count-objects reports loose objects as allocated KiB and packs as logical .pack+.idx KiB. "
    "Git history is reported only as object storage; it is not attributed to working-tree paths.",
    "Name matches and duplicate groups are candidates for review, not evidence that content is "
    "regenerable, unreferenced or redundant. Duplicate hashing skips Git storage (including nested "
    "repositories' .git), empty files and a best-effort list of sensitive names.",
)


def error(path: str, operation: str, detail: BaseException | str) -> dict:
    if isinstance(detail, BaseException):
        detail = f"{type(detail).__name__}: {detail}"
    return {"path": path, "operation": operation, "error": detail}


def git_env() -> dict:
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("GIT_") or key in GIT_ENV_KEPT}
    env.update(GIT_ENV)
    return env


def run_git(root: str, *args: str) -> tuple[int, bytes, int]:
    """Run one read-only Git query. Returns (exit status, stdout, stderr line
    count); -1 if Git could not run or timed out. stderr text is never kept
    because it can hold configured URLs or credentials."""
    try:
        result = subprocess.run([*GIT_PREFIX, "-C", root, *args], stdin=subprocess.DEVNULL,
                                capture_output=True, env=git_env(), timeout=GIT_TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return -1, b"", 0
    return result.returncode, result.stdout, len([line for line in result.stderr.splitlines() if line.strip()])


def nul_fields(output: bytes, terminator: bytes = b"\0") -> list[str] | None:
    """Split NUL-delimited Git output; None if it is not properly terminated."""
    if output and not output.endswith(terminator):
        return None
    return [os.fsdecode(item) for item in output.split(b"\0")]


def inside(path: str, root: str) -> bool:
    return os.path.commonpath([path, root]) == root


def relpath(path: str, root: str) -> str:
    rel = os.path.relpath(path, root).replace(os.sep, "/")
    return "" if rel == "." else rel


def canonical_root(path: str | os.PathLike) -> str:
    """Resolve symlinks and, where the platform can report it (macOS), the
    on-disk letter case, so containment matches the paths Git prints."""
    real = os.path.realpath(path)
    getpath = getattr(fcntl, "F_GETPATH", None)
    if getpath is None:
        return real
    try:
        descriptor = os.open(real, os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return real
    try:
        return os.fsdecode(fcntl.fcntl(descriptor, getpath, bytes(1024)).split(b"\0", 1)[0]) or real
    except OSError:
        return real
    finally:
        os.close(descriptor)


def git_bool(root: str, key: str) -> bool:
    code, out, _ = run_git(root, "config", "--get", "--type=bool", key)
    return code == 0 and out.strip() == b"true"


def parse_worktrees(fields: list[str], root: str) -> list[dict]:
    worktrees, current = [], None
    for field in fields:
        key, _, value = field.partition(" ")
        if key == "worktree":
            path = os.path.normpath(value)
            current = {"path": value, "inside_root": inside(path, root), "contains_root": inside(root, path),
                       "head": None, "branch": None, "detached": False, "bare": False,
                       "locked": False, "prunable": False}
            worktrees.append(current)
        elif current is not None and key in ("HEAD", "branch"):
            current[key.lower()] = value
        elif current is not None and key in ("detached", "bare", "locked", "prunable"):
            current[key] = True  # lock/prune reasons are free text and are not copied
    return worktrees


def git_facts(root: str, errors: list) -> dict:
    """HEAD, branch, Git-class path sets, staged changes, object storage and worktrees."""
    facts = {"available": False, "branch": None, "head": None, "git_dir": None, "common_dir": None,
             "split_index": False, "staged_changes": None, "count_objects": {}, "worktrees": [],
             "sets": {}, "storage_paths": set(), "precompose_unicode": False, "ignore_case": False}
    code, out, _ = run_git(root, "rev-parse", "--absolute-git-dir", "--git-common-dir")
    lines = os.fsdecode(out).splitlines()
    if code or len(lines) < 2:
        errors.append(error(".", "git rev-parse", f"not a Git work tree or Git unavailable (exit {code})"))
        return facts
    # Git prints real absolute paths; normalize lexically so nothing outside the root is stat'ed.
    git_dir, common_dir = (os.path.normpath(os.path.join(root, line)) for line in lines[:2])
    facts.update(available=True, git_dir=git_dir, common_dir=common_dir,
                 split_index=any(glob.glob(os.path.join(glob.escape(path), "sharedindex.*"))
                                 for path in {git_dir, common_dir}),
                 precompose_unicode=git_bool(root, "core.precomposeunicode"),
                 ignore_case=git_bool(root, "core.ignorecase"))
    facts["storage_paths"] = {relpath(path, root) for path in (git_dir, common_dir) if inside(path, root)}
    facts["storage_paths"].discard("")
    code, out, _ = run_git(root, "rev-parse", "--verify", "-q", "HEAD")
    facts["head"] = os.fsdecode(out).strip() if code == 0 else None
    code, out, _ = run_git(root, "symbolic-ref", "--short", "-q", "HEAD")
    facts["branch"] = os.fsdecode(out).strip() if code == 0 else None
    for name, args in GIT_LISTINGS.items():
        code, out, warnings = run_git(root, *args)
        fields = nul_fields(out) if code == 0 else None
        if fields is None or warnings:
            detail = (f"Git reported {warnings} warning line(s); ignore rules may be incomplete" if fields is not None
                      else f"failed or unterminated output (exit {code})")
            errors.append(error(".", f"git ls-files ({name})", detail))
            facts["available"] = False
        if fields is not None:
            facts["sets"][name] = {field for field in fields if field}
    if facts["head"]:
        code, out, _ = run_git(root, "diff-index", "--cached", "--name-status", "-z", "HEAD")
        fields = nul_fields(out) if code == 0 else None
        if fields is None:
            errors.append(error(".", "git diff-index --cached", f"failed or unterminated output (exit {code})"))
        else:
            fields, staged = [field for field in fields if field], []
            while fields:
                status = fields.pop(0)
                paths = [fields.pop(0) for _ in range(2 if status[:1] in "RC" else 1) if fields]
                staged.append({"status": status, "paths": paths})
            facts["staged_changes"] = staged
    code, out, _ = run_git(root, "count-objects", "-v")
    if code:
        errors.append(error(".", "git count-objects", f"exit {code}"))
    for line in os.fsdecode(out).splitlines():
        key, _, value = line.partition(":")
        if value.strip().isdigit():
            key = key.strip().replace("-", "_")
            facts["count_objects"][key + ("_kib" if key.startswith("size") else "")] = int(value)
    code, out, _ = run_git(root, "worktree", "list", "--porcelain", "-z")
    fields = nul_fields(out, b"\0\0") if code == 0 else None
    if fields is None:  # Git before 2.36 has no -z; newline porcelain is ambiguous only for newline paths
        code, out, _ = run_git(root, "worktree", "list", "--porcelain")
        fields = os.fsdecode(out).splitlines() if code == 0 else None
    if fields is None:
        errors.append(error(".", "git worktree list", f"failed (exit {code})"))
    facts["worktrees"] = parse_worktrees(fields or [], root)
    return facts


def open_directory(root_fd: int, rel: str) -> int:
    """Open rel below root_fd one component at a time, never following a symlink."""
    descriptor = os.dup(root_fd)
    try:
        for part in rel.split("/") if rel else ():
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def walk(root: str, errors: list, exclusions: list, empty_dirs: list):
    """Yield (relative path, lstat result, symlink target) below root.

    Every directory is reopened through descriptors and must still be the inode
    seen in its parent's listing, so a directory swapped for a symlink during the
    walk is reported as an error instead of being followed."""
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        root_info = os.fstat(root_fd)
        pending = [("", (root_info.st_dev, root_info.st_ino))]
        while pending:
            directory, identity = pending.pop()
            found, children, listed = [], [], 0
            try:
                descriptor = open_directory(root_fd, directory)
                try:
                    opened = os.fstat(descriptor)
                    if (opened.st_dev, opened.st_ino) != identity:
                        raise OSError(f"directory changed during traversal: {directory}")
                    with os.scandir(descriptor) as listing:
                        entries = sorted(listing, key=lambda entry: entry.name)
                    listed = len(entries)
                    for entry in entries:
                        rel = f"{directory}/{entry.name}" if directory else entry.name
                        try:
                            info = entry.stat(follow_symlinks=False)
                        except OSError as exc:
                            errors.append(error(rel, "lstat", exc))
                            continue
                        target = None
                        if stat.S_ISLNK(info.st_mode):
                            try:
                                target = os.readlink(entry.name, dir_fd=descriptor)
                            except OSError as exc:
                                errors.append(error(rel, "readlink", exc))
                        found.append((rel, info, target))
                        if stat.S_ISDIR(info.st_mode):
                            if info.st_dev == root_info.st_dev:
                                children.append((rel, (info.st_dev, info.st_ino)))
                            else:
                                exclusions.append({"path": rel, "within_root": True,
                                                   "reason": "different filesystem (mount point); not traversed"})
                finally:
                    os.close(descriptor)
            except OSError as exc:
                errors.append(error(directory or ".", "scandir", exc))
                continue
            if not listed and directory and ".git" not in directory.split("/"):
                empty_dirs.append(directory)  # Git's own empty internals are not reported
            yield from found
            pending.extend(reversed(children))
    finally:
        os.close(root_fd)


def kind_of(mode: int) -> str:
    kinds = {stat.S_IFREG: "file", stat.S_IFDIR: "dir", stat.S_IFLNK: "symlink", stat.S_IFIFO: "fifo",
             stat.S_IFSOCK: "socket", stat.S_IFBLK: "block_device", stat.S_IFCHR: "char_device"}
    return kinds.get(stat.S_IFMT(mode), "unknown")


def under(rel: str, prefixes: set) -> bool:
    parts = rel.split("/")
    return any("/".join(parts[:index]) in prefixes for index in range(1, len(parts) + 1))


class Matcher:
    """Match on-disk names to Git's path sets. Where the repository precomposes
    Unicode or ignores case, Git's names can differ from directory entries, so
    those forms match too and the difference is recorded."""

    def __init__(self, sets: dict, precompose: bool, ignore_case: bool):
        self.sets, self.precompose, self.ignore_case = sets, precompose, ignore_case
        self.keys = {name: {self.key(path): path for path in paths} for name, paths in sets.items()}
        self.mismatches = []

    def key(self, path: str) -> str:
        path = unicodedata.normalize("NFC", path) if self.precompose else path
        return path.casefold() if self.ignore_case else path

    def find(self, name: str, rel: str) -> bool:
        if rel in self.sets.get(name, ()):
            return True
        match = self.keys.get(name, {}).get(self.key(rel))
        if match is not None:
            self.mismatches.append({"disk": rel, "git": match, "set": name})
        return match is not None


def classify(rel: str, kind: str, matcher: Matcher, storage: set, nested: set) -> str | None:
    if ".git" in rel.split("/") or under(rel, storage):
        return "git_storage"  # the root's Git directory and every nested repository's .git
    if kind in ("file", "symlink") and matcher.find("tracked", rel):
        return "tracked"
    if under(rel, nested):
        return "nested_repository"
    if kind not in ("file", "symlink"):
        return None  # directories and special files are not classified by Git
    return next((name for name in ("ignored", "untracked") if matcher.find(name, rel)), "unclassified")


def sensitive(rel: str) -> bool:
    parts = rel.split("/")
    return (bool(SENSITIVE_NAME.search(parts[-1])) or any(part in SENSITIVE_DIRS for part in parts)
            or rel.startswith(SENSITIVE_PREFIXES))


def symlink_fact(root: str, rel: str, target: str | None, records: dict, exclusions: list) -> dict:
    """Describe a symlink from its target string alone; nothing is followed."""
    fact = {"path": rel, "class": records[rel]["class"], "target": target, "scope": "unknown",
            "resolved": None, "target_inventoried": None}
    if target is None:
        return fact
    resolved = os.path.normpath(os.path.join(root, os.path.dirname(rel), target))
    if not inside(resolved, root):
        exclusions.append({"path": rel, "within_root": False,
                           "reason": "symlink target outside root; not inspected"})
        fact["scope"] = "outside_root"
        return fact
    target = relpath(resolved, root)
    fact.update(scope="inside_root", resolved=target or ".", target_inventoried=not target or target in records)
    return fact


def open_regular(root: str, rel: str, expected: dict) -> int:
    """Open rel below root through directory descriptors, never following a
    symlink, and require the inode seen during traversal (after
    regular_bytes in inventory_standalone_components.py)."""
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        parts = rel.split("/")
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    finally:
        os.close(directory)
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or (info.st_dev, info.st_ino, info.st_size) != (
            expected["dev"], expected["ino"], expected["size"]):
        os.close(descriptor)
        raise OSError(f"changed since traversal: {rel}")
    return descriptor


def sha256_file(root: str, rel: str, expected: dict) -> str:
    descriptor = open_regular(root, rel, expected)
    digest, total = hashlib.sha256(), 0
    try:
        before = os.fstat(descriptor)
        while chunk := os.read(descriptor, CHUNK):
            digest.update(chunk)
            total += len(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if total != expected["size"] or (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise OSError(f"changed while reading: {rel}")
    return digest.hexdigest()


def duplicates(root: str, records: dict, selections: list, errors: list) -> dict:
    """SHA-256 exact-duplicate groups among regular files below explicit selections."""
    chosen, skipped, empty = {}, [], set()
    for raw in selections:
        candidate = os.path.normpath(os.path.join(root, raw))
        if not inside(candidate, root):
            errors.append(error(raw, "hash-select", "selection outside root"))
            continue
        rel = relpath(candidate, root)
        if rel and rel not in records:
            errors.append(error(raw, "hash-select", "selection not found in inventory"))
            continue
        if rel and records[rel]["kind"] == "symlink":
            skipped.append({"path": rel, "reason": "symlink not followed"})
            continue
        for path, record in records.items():
            if record["kind"] != "file" or not (not rel or path == rel or path.startswith(rel + "/")):
                continue
            if record["class"] == "git_storage":
                skipped.append({"path": path, "reason": "Git storage is not hashed"})
            elif sensitive(path):
                skipped.append({"path": path, "reason": "sensitive or private-configuration name; not read"})
            elif record["size"] == 0:
                empty.add(path)
            else:
                chosen[path] = record
    skipped = [{"path": path, "reason": reason}  # overlapping selections reach a file twice
               for path, reason in sorted({(item["path"], item["reason"]) for item in skipped})]
    by_size = defaultdict(list)
    for path, record in chosen.items():
        by_size[record["size"]].append(path)
    by_digest, inode_digest, hashed_bytes = defaultdict(list), {}, 0
    for size, paths in sorted(by_size.items()):
        if len(paths) < 2:
            continue
        for path in sorted(paths):
            key = (chosen[path]["dev"], chosen[path]["ino"])
            if key not in inode_digest:
                try:
                    inode_digest[key] = sha256_file(root, path, chosen[path])
                except OSError as exc:
                    errors.append(error(path, "hash", exc))
                    continue
                hashed_bytes += size
            by_digest[inode_digest[key]].append(path)
    groups = []
    for digest, paths in by_digest.items():
        if len(paths) < 2:
            continue
        allocations = {(chosen[path]["dev"], chosen[path]["ino"]): chosen[path]["allocated"] for path in paths}
        groups.append({
            "sha256": digest, "size_bytes": chosen[paths[0]]["size"], "distinct_inodes": len(allocations),
            "allocated_bytes_all_inodes": sum(allocations.values()),
            # keeping the largest inode is the bound; sparse or compressed copies differ
            "allocated_bytes_in_additional_inodes": sum(allocations.values()) - max(allocations.values()),
            "copies": [{"path": path, "class": chosen[path]["class"], "hidden": chosen[path]["hidden"],
                        "allocated_bytes": chosen[path]["allocated"],
                        "inode": f"{chosen[path]['dev']}:{chosen[path]['ino']}"} for path in sorted(paths)],
        })
    groups.sort(key=lambda group: (-group["allocated_bytes_in_additional_inodes"], group["sha256"]))
    return {
        "selections": list(selections), "candidate_files": len(chosen), "hashed_inodes": len(inode_digest),
        "hashed_bytes": hashed_bytes, "empty_files_not_grouped": len(empty), "skipped": skipped,
        "groups": groups,
        "allocated_bytes_in_additional_inodes": sum(g["allocated_bytes_in_additional_inodes"] for g in groups),
        "note": "Copies can hold distinct evidence roles; this total is not a reclaim estimate.",
    }


def bucket(classes: bool = False) -> dict:
    values = {"files": 0, "logical_bytes": 0, "allocated_bytes": 0}
    if classes:
        values["by_class"] = defaultdict(lambda: {"files": 0, "logical_bytes": 0, "allocated_bytes": 0})
    return values


def tally(values: dict, record: dict) -> None:
    for target in [values] + ([values["by_class"][record["class"]]] if "by_class" in values else []):
        target["files"] += 1
        target["logical_bytes"] += record["size"]
        target["allocated_bytes"] += record["allocated"]


def name_group(parts: list) -> tuple[str, str] | None:
    """The single outermost conventional name a path falls under, so groups never overlap."""
    for index, part in enumerate(parts[:-1]):
        if NAME_GROUPS.get(part) == "dir":
            return part, "/".join(parts[:index + 1])
    name = parts[-1]
    if name == ".DS_Store" or name.startswith("._"):
        return (".DS_Store" if name == ".DS_Store" else "._*"), "/".join(parts)
    return None


def build_report(root: str | os.PathLike = REPO_ROOT, *, depth: int = 2, top: int = 20,
                 hash_paths=(), list_entries: bool = False) -> dict:
    root = canonical_root(root)
    if not os.path.isdir(root):
        raise NotADirectoryError(root)
    errors, exclusions, empty_dirs = [], [], []
    git = git_facts(root, errors)
    entries = list(walk(root, errors, exclusions, empty_dirs))
    kinds_by_path = {rel: kind_of(info.st_mode) for rel, info, _ in entries}
    storage = git["storage_paths"]
    sets = {name: {path for path in paths if not path.endswith("/")} for name, paths in git["sets"].items()}
    # Nested repositories as Git sees them: "dir/" entries in the untracked or ignored
    # listings, and tracked gitlinks that are directories on disk.
    nested = {path.rstrip("/") for name in ("untracked", "ignored")
              for path in git["sets"].get(name, ()) if path.endswith("/")}
    nested |= {path for path in sets.get("tracked", ()) if kinds_by_path.get(path) == "dir"}
    matcher = Matcher(sets, git["precompose_unicode"], git["ignore_case"])
    records = {rel: {"kind": kinds_by_path[rel], "size": info.st_size,
                     "allocated": info.st_blocks * BLOCK_BYTES, "dev": info.st_dev, "ino": info.st_ino,
                     "nlink": info.st_nlink, "mtime_ns": info.st_mtime_ns,
                     "hidden": any(p.startswith(".") for p in rel.split("/")),
                     "class": classify(rel, kinds_by_path[rel], matcher, storage, nested)}
               for rel, info, _ in entries}
    targets = {rel: target for rel, _, target in entries if target is not None}
    for worktree in git["worktrees"]:
        if not worktree["inside_root"] and not worktree["contains_root"]:
            exclusions.append({"path": worktree["path"], "within_root": False,
                               "reason": "linked worktree outside root; not inventoried"})
    for label in ("git_dir", "common_dir"):
        if git[label] and not inside(git[label], root) and not any(e["path"] == git[label] for e in exclusions):
            exclusions.append({"path": git[label], "within_root": False,
                               "reason": "Git directory outside root; summarized by count-objects only"})

    by_class = {name: bucket() for name in CLASSES}
    hidden = {name: bucket() for name in CLASSES}
    directories = defaultdict(lambda: bucket(classes=True))
    matches = {name: defaultdict(lambda: bucket(classes=True)) for name in NAME_GROUPS}
    kinds, inodes, file_inodes, links = defaultdict(int), {}, {}, defaultdict(list)
    empty, symlinks, special = [], [], []
    for rel, record in records.items():
        kinds[record["kind"]] += 1
        inodes.setdefault((record["dev"], record["ino"]), record["allocated"])
        parts = rel.split("/")
        if record["kind"] == "dir":
            group = name_group(parts + [""])
            if group and group[1] == rel:
                matches[group[0]].setdefault(rel, bucket(classes=True))
            continue
        if record["kind"] == "symlink":
            symlinks.append(symlink_fact(root, rel, targets.get(rel), records, exclusions))
            continue
        if record["kind"] != "file":
            special.append({"path": rel, "type": record["kind"], "class": record["class"]})
            continue
        file_inodes.setdefault((record["dev"], record["ino"]), (record["size"], record["allocated"]))
        tally(by_class[record["class"]], record)
        if record["hidden"]:
            tally(hidden[record["class"]], record)
        tally(directories["."], record)
        for level in range(1, min(depth, len(parts) - 1) + 1):
            tally(directories["/".join(parts[:level])], record)
        if record["size"] == 0:
            empty.append({"path": rel, "class": record["class"], "hidden": record["hidden"]})
        if record["nlink"] > 1:
            links[(record["dev"], record["ino"])].append(rel)
        group = name_group(parts)
        if group:
            tally(matches[group[0]][group[1]], record)

    def rows(table: dict) -> list:
        return [{"path": path, "depth": 0 if path == "." else path.count("/") + 1,
                 "files": v["files"], "logical_bytes": v["logical_bytes"],
                 "allocated_bytes": v["allocated_bytes"], "by_class": dict(v["by_class"])}
                for path, v in sorted(table.items(), key=lambda item: (-item[1]["allocated_bytes"], item[0]))]

    files = [rel for rel, record in records.items() if record["kind"] == "file"]
    largest = sorted(files, key=lambda rel: (-records[rel]["allocated"], -records[rel]["size"], rel))[:top]
    unclassified = sum(1 for r in records.values() if r["kind"] in ("file", "symlink") and r["class"] == "unclassified")
    walked = {matcher.key(rel) for rel in records}
    report = {
        "contract": CONTRACT,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "root": root,
        "git": {key: git[key] for key in ("available", "branch", "head", "git_dir", "common_dir", "split_index",
                                           "precompose_unicode", "ignore_case", "staged_changes",
                                           "count_objects", "worktrees")},
        "totals_by_class": by_class,
        "hidden_by_class": hidden,
        "unclassified_entries": unclassified,
        "name_mismatches": matcher.mismatches,
        "filesystem": {
            "entries_by_kind": dict(kinds),
            "regular_file_logical_bytes": sum(v["logical_bytes"] for v in by_class.values()),
            "regular_file_allocated_bytes": sum(v["allocated_bytes"] for v in by_class.values()),
            "unique_inode_regular_file_logical_bytes": sum(size for size, _ in file_inodes.values()),
            "unique_inode_regular_file_allocated_bytes": sum(alloc for _, alloc in file_inodes.values()),
            "unique_inode_allocated_bytes_all_entries": sum(inodes.values()),
        },
        "directories": rows(directories),
        "largest_files": [{"path": rel, "class": records[rel]["class"], "hidden": records[rel]["hidden"],
                           "logical_bytes": records[rel]["size"], "allocated_bytes": records[rel]["allocated"],
                           "nlink": records[rel]["nlink"]} for rel in largest],
        "empty_files": empty,
        "empty_directories": sorted(empty_dirs),
        "symlinks": symlinks,
        "hardlinks": [{"inode": f"{dev}:{ino}", "nlink": records[paths[0]]["nlink"], "paths": paths,
                       "links_not_inventoried": records[paths[0]]["nlink"] - len(paths),
                       "allocated_bytes": records[paths[0]]["allocated"]}
                      for (dev, ino), paths in sorted(links.items(), key=lambda item: item[1])],
        "special_files": special,
        "nested_repositories": sorted(nested),
        "name_matches": {name: rows(table) for name, table in matches.items()},
        "tracked_paths_not_inventoried": sorted(p for p in sets.get("tracked", ())
                                                if p not in records and matcher.key(p) not in walked),
        "duplicates": duplicates(root, records, list(hash_paths), errors) if hash_paths else None,
        "entries": [{"path": rel, "kind": r["kind"], "class": r["class"], "hidden": r["hidden"],
                     "logical_bytes": r["size"], "allocated_bytes": r["allocated"], "nlink": r["nlink"],
                     "mtime_ns": r["mtime_ns"]} for rel, r in records.items()] if list_entries else None,
        "errors": errors,
        "exclusions": exclusions,
        "notes": list(NOTES) + (["Split index present: Git refreshes the shared index's mtime whenever "
                                 "these queries read the index; nothing else is written."]
                                if git["split_index"] else []),
    }
    report["inventory_complete_within_root"] = not errors and not any(e["within_root"] for e in exclusions)
    report["git_classification_complete"] = git["available"] and not unclassified
    return report


def iec(value: float) -> str:
    if abs(value) < 1024:
        return f"{int(value):,} B"
    for unit in ("KiB", "MiB", "GiB", "TiB"):
        value /= 1024
        if abs(value) < 1024 or unit == "TiB":
            return f"{value:,.1f} {unit}"
    raise AssertionError("unreachable")


def limited(rows: list, top: int, render) -> list:
    lines = [render(row) for row in rows[:top]] or ["  (none)"]
    if len(rows) > top:
        lines.append(f"  ... {len(rows) - top:,} more not shown; use --format json for all")
    return lines


def printable(line: str) -> str:
    """Escape control characters from file names so they cannot rewrite the report."""
    return "".join(char if char.isprintable() else char.encode("unicode_escape").decode("ascii") for char in line)


def classes(row: dict) -> str:
    return " ".join(f"{k}={v['files']:,}" for k, v in sorted(row["by_class"].items(), key=lambda kv: str(kv[0])))


def render_text(report: dict, top: int = 20) -> str:
    git, fs = report["git"], report["filesystem"]
    within = sum(e["within_root"] for e in report["exclusions"])
    staged = git["staged_changes"]
    hidden = {k: sum(v[k] for v in report["hidden_by_class"].values())
              for k in ("files", "logical_bytes", "allocated_bytes")}
    lines = [
        "Storage inventory: filesystem facts only; nothing was deleted, compressed or moved.",
        f"Generated: {report['generated_at']}",
        f"Root: {report['root']}",
        f"Git: branch={git['branch']} head={git['head']} available={git['available']} "
        f"staged changes={'n/a' if staged is None else len(staged)} (unstaged modifications not computed)",
        "Units: logical = st_size; allocated = st_blocks x 512; KiB/MiB/GiB are 1024-based.",
        f"Traversal within root: {'complete' if report['inventory_complete_within_root'] else 'INCOMPLETE'} "
        f"({len(report['errors'])} errors, {within} excluded subtrees within root); "
        f"Git classification complete: {report['git_classification_complete']} "
        f"({report['unclassified_entries']} unclassified files/symlinks)",
        "", "Regular files by class (hardlinks counted per path):",
        f"  {'class':<18}{'files':>10}{'logical':>14}{'allocated':>14}",
    ]
    lines += [f"  {name:<18}{v['files']:>10,}{iec(v['logical_bytes']):>14}{iec(v['allocated_bytes']):>14}"
              for name, v in report["totals_by_class"].items()]
    lines += [
        f"  hidden-path files: {hidden['files']:,}; {iec(hidden['logical_bytes'])} logical; "
        f"{iec(hidden['allocated_bytes'])} allocated",
        f"Entries: {', '.join(f'{k}={v:,}' for k, v in sorted(fs['entries_by_kind'].items()))}",
        f"Unique inodes (regular files): {iec(fs['unique_inode_regular_file_logical_bytes'])} logical; "
        f"{iec(fs['unique_inode_regular_file_allocated_bytes'])} allocated; all entries including directories "
        f"and symlinks: {iec(fs['unique_inode_allocated_bytes_all_entries'])} allocated",
        "", "Largest directories by allocated bytes (regular files per path; dN = depth; '.' is the whole "
        "root and deeper rows nest in shallower ones):",
    ]
    lines += limited(report["directories"], top, lambda d: f"  d{d['depth']} {iec(d['allocated_bytes']):>11} "
                     f"alloc {iec(d['logical_bytes']):>11} logical {d['files']:>8,} files  {d['path']}  {classes(d)}")
    lines += ["", "Largest files by allocated bytes:"]
    lines += limited(report["largest_files"], top, lambda f: f"  {iec(f['allocated_bytes']):>11} alloc "
                     f"{iec(f['logical_bytes']):>11} logical  [{f['class']}] {f['path']}")
    lines += ["", f"Empty regular files: {len(report['empty_files']):,}"]
    lines += limited(report["empty_files"], top, lambda e: f"  [{e['class']}] {e['path']}")
    lines += [f"Empty directories: {len(report['empty_directories']):,}"]
    lines += limited(report["empty_directories"], top, lambda path: f"  {path}")
    lines += ["", f"Symlinks (not followed): {len(report['symlinks']):,}"]
    lines += limited(report["symlinks"], top, lambda s: f"  [{s['scope']}] [{s['class']}] {s['path']} -> {s['target']}"
                     + (" (target not inventoried)" if s["target_inventoried"] is False else ""))
    lines += ["", f"Hardlink groups: {len(report['hardlinks']):,}"]
    lines += limited(report["hardlinks"], top, lambda h: f"  nlink={h['nlink']} links-not-inventoried="
                     f"{h['links_not_inventoried']} {iec(h['allocated_bytes'])}  {', '.join(h['paths'])}")
    lines += ["", f"Special files (never opened): {len(report['special_files']):,}"]
    lines += limited(report["special_files"], top, lambda s: f"  [{s['type']}] {s['path']}")
    lines += ["", "Conventional tool-cache/OS-metadata names (each file in one group; facts, not "
              "disposability judgments):"]
    for name, rows in report["name_matches"].items():
        totals = {"files": sum(r["files"] for r in rows), "by_class": defaultdict(lambda: {"files": 0})}
        for row in rows:
            for key, value in row["by_class"].items():
                totals["by_class"][key]["files"] += value["files"]
        lines.append(f"  {name}: {len(rows):,} paths; {totals['files']:,} files; "
                     f"{iec(sum(r['logical_bytes'] for r in rows))} logical; "
                     f"{iec(sum(r['allocated_bytes'] for r in rows))} allocated  {classes(totals)}")
    counts = git["count_objects"]
    lines += ["", "Git storage:",
              f"  loose objects={counts.get('count')} ({counts.get('size_kib')} KiB allocated); "
              f"packs={counts.get('packs')} ({counts.get('size_pack_kib')} KiB logical .pack+.idx); "
              f"prune-packable={counts.get('prune_packable')}; garbage={counts.get('garbage')} "
              f"({counts.get('size_garbage_kib')} KiB); split index={git['split_index']}",
              f"  git_storage class walked: {iec(report['totals_by_class']['git_storage']['allocated_bytes'])} allocated",
              f"Worktrees: {len(git['worktrees'])}"]
    lines += limited(git["worktrees"], top, lambda w: f"  {w['path']} head={w['head']} branch={w['branch']} "
                     f"detached={w['detached']} prunable={w['prunable']} locked={w['locked']} "
                     f"inside_root={w['inside_root']}")
    lines += [f"Nested repositories: {len(report['nested_repositories'])}"]
    lines += limited(report["nested_repositories"], top, lambda path: f"  {path}")
    lines += [f"Names matched to Git only after Unicode/case normalization: {len(report['name_mismatches'])}"]
    lines += limited(report["name_mismatches"], top, lambda m: f"  disk {m['disk']} = git {m['git']} [{m['set']}]")
    lines += [f"Tracked paths not inventoried (missing, unreadable parent, or excluded): "
              f"{len(report['tracked_paths_not_inventoried'])}"]
    lines += limited(report["tracked_paths_not_inventoried"], top, lambda path: f"  {path}")
    dup = report["duplicates"]
    if dup is not None:
        lines += ["", f"Exact duplicates (SHA-256) within {', '.join(dup['selections'])}: {len(dup['groups']):,} "
                  f"groups; {dup['candidate_files']:,} candidate files; {dup['empty_files_not_grouped']:,} empty "
                  f"files not grouped; {iec(dup['allocated_bytes_in_additional_inodes'])} allocated in "
                  f"additional inodes", f"  {dup['note']}"]
        lines += limited(dup["groups"], top, lambda g: f"  {g['sha256'][:12]} {iec(g['size_bytes'])} "
                         f"x{len(g['copies'])} ({g['distinct_inodes']} inodes): "
                         + ", ".join(f"{c['path']} [{c['class']}]" for c in g["copies"]))
        lines += [f"  Skipped: {len(dup['skipped'])}"]
        lines += limited(dup["skipped"], top, lambda s: f"    {s['path']}: {s['reason']}")
    lines += ["", f"Errors: {len(report['errors'])}"]
    lines += limited(report["errors"], top, lambda e: f"  {e['operation']} {e['path']}: {e['error']}")
    lines += [f"Exclusions: {len(report['exclusions'])}"]
    lines += limited(report["exclusions"], top, lambda e: f"  {e['path']}: {e['reason']}")
    lines += ["", "Notes:"] + [f"  - {note}" for note in report["notes"]]
    return "\n".join(printable(line) for line in lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=str(REPO_ROOT), help="directory to inventory (default: repository root)")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--depth", type=int, default=2, help="directory aggregation depth (default 2)")
    parser.add_argument("--top", type=int, default=20,
                        help="largest files recorded and rows per text list (default 20)")
    parser.add_argument("--hash", action="append", default=[], metavar="PATH",
                        help="root-relative file or directory to search for exact duplicates; repeatable")
    parser.add_argument("--entries", action="store_true", help="include every inventoried entry in JSON output")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.depth < 1 or args.top < 1:
        parser.error("--depth and --top must be positive")
    if not os.path.isdir(args.root):
        parser.error(f"--root is not a directory: {args.root}")
    report = build_report(args.root, depth=args.depth, top=args.top, hash_paths=args.hash,
                          list_entries=args.entries)
    if args.format == "json":
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True, allow_nan=False, ensure_ascii=True) + "\n")
    else:
        sys.stdout.write(render_text(report, args.top))
    return 0 if report["inventory_complete_within_root"] and report["git_classification_complete"] else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="backslashreplace")
    raise SystemExit(main())
