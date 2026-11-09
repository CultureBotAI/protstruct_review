#!/usr/bin/env python3
"""Focused synthetic unit tests for scripts/refmac_diagnostic_profile.py (Tasks 653, 657, 663, and 658)."""

from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError
import errno
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import refmac_diagnostic_profile as profile_mod  # noqa: E402
from refmac_diagnostic_profile import (  # noqa: E402
    EXPECTED_COLLECTOR_HELPER_NAMES,
    EXPECTED_RUNTIME_ABSENT_KEYS,
    EXPECTED_RUNTIME_ENV_KEYS,
    FORBIDDEN_ENV_KEYS,
    PROFILE_SCHEMA_ID,
    PROFILE_SUBJECT_ID,
    SUPPORTED_PROFILE_ID,
    UPSTREAM_COMMIT,
    UPSTREAM_TAG,
    FilePin,
    RefmacDiagnosticProfile,
    _CheckedOuterManifest,
    _CheckedOuterProfileState,
    _ObservedRegularFilePin,
    _OuterProfileRecheckResult,
    _PartialProfileObservation,
    _PinnedJsonDocument,
    _ProfileObservationError,
    _SymlinkEdge,
    _observe_controlled_root,
    _observe_regular_file_pin,
    _parse_verified_json_bytes,
    _read_pinned_json,
    _reobserve_outer_profile_state,
    _validate_and_observe_outer_profile,
    _validate_outer_manifest_shape,
    reject_conflicting_environment,
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class TestPublicDataclassesAndSliceBoundary(unittest.TestCase):
    """Verify frozen FilePin, RefmacDiagnosticProfile, and absence of premature stubs."""

    def test_validate_and_recheck_stubs_are_deliberately_absent(self) -> None:
        self.assertFalse(hasattr(profile_mod, "validate_profile"))
        self.assertFalse(hasattr(profile_mod, "recheck_profile"))

    def test_file_pin_preserves_lexical_alias_and_is_frozen(self) -> None:
        raw_alias = "/opt/tools/bin/../libexec/refmac5"
        digest = "a" * 64
        pin = FilePin(path=raw_alias, sha256=digest, size_bytes=0)
        self.assertEqual(pin.path, raw_alias)
        self.assertEqual(pin.sha256, digest)
        self.assertEqual(pin.size_bytes, 0)
        with self.assertRaises(FrozenInstanceError):
            pin.size_bytes = 10  # type: ignore[misc]

    def test_file_pin_rejects_invalid_fields(self) -> None:
        valid_sha = "0123456789abcdef" * 4
        for bad_path in (
            "",
            "   ",
            "relative/path.json",
            "/abs/with\x00nul",
            None,
            123,
            Path("/abs/path"),
        ):
            with self.subTest(bad_path=bad_path):
                with self.assertRaises(ValueError):
                    FilePin(path=bad_path, sha256=valid_sha, size_bytes=1)  # type: ignore[arg-type]

        for bad_sha in (
            "",
            "a" * 63,
            "a" * 65,
            "A" * 64,
            "g" * 64,
            123,
            None,
        ):
            with self.subTest(bad_sha=bad_sha):
                with self.assertRaises(ValueError):
                    FilePin(path="/abs/file.txt", sha256=bad_sha, size_bytes=1)  # type: ignore[arg-type]

        for bad_size in (True, False, -1, 1.5, "10", None):
            with self.subTest(bad_size=bad_size):
                with self.assertRaises(ValueError):
                    FilePin(path="/abs/file.txt", sha256=valid_sha, size_bytes=bad_size)  # type: ignore[arg-type]

    def test_refmac_diagnostic_profile_accepts_only_supported_id_and_distinct_pins(self) -> None:
        manifest_pin = FilePin(
            path="/tmp/profile/diagnostic-profile.json",
            sha256="b" * 64,
            size_bytes=128,
        )
        exe_pin = FilePin(
            path="/tmp/build/refmac5",
            sha256="c" * 64,
            size_bytes=256,
        )
        profile = RefmacDiagnosticProfile(
            profile_id=SUPPORTED_PROFILE_ID,
            manifest=manifest_pin,
            executable=exe_pin,
        )
        self.assertEqual(profile.profile_id, SUPPORTED_PROFILE_ID)
        self.assertEqual(profile.manifest, manifest_pin)
        self.assertEqual(profile.executable, exe_pin)
        with self.assertRaises(FrozenInstanceError):
            profile.profile_id = "other"  # type: ignore[misc]

        for bad_id in ("", "wrong_profile_v1", None, 42):
            with self.subTest(bad_id=bad_id):
                with self.assertRaises(ValueError):
                    RefmacDiagnosticProfile(
                        profile_id=bad_id,  # type: ignore[arg-type]
                        manifest=manifest_pin,
                        executable=exe_pin,
                    )

        with self.assertRaises(ValueError):
            RefmacDiagnosticProfile(
                profile_id=SUPPORTED_PROFILE_ID,
                manifest=manifest_pin,
                executable=manifest_pin,
            )

        with self.assertRaises(ValueError):
            RefmacDiagnosticProfile(
                profile_id=SUPPORTED_PROFILE_ID,
                manifest={"path": "/a", "sha256": "b" * 64, "size_bytes": 1},  # type: ignore[arg-type]
                executable=exe_pin,
            )


class TestRejectConflictingEnvironment(unittest.TestCase):
    """Verify environment guard rejects forbidden names/prefixes without mutating mappings."""

    def test_clean_environment_passes_unchanged(self) -> None:
        clean = {
            "PATH": "/usr/bin:/bin",
            "CCP4": "/opt/ccp4",
            "GFORTRAN_UNBUFFERED_PRECONNECTED": "Y",
            "LD": "/usr/bin/ld",
            "DYLD": "not_a_prefix",
        }
        snapshot = dict(clean)
        ambient_before = dict(os.environ)
        reject_conflicting_environment(clean)
        self.assertEqual(clean, snapshot)
        self.assertEqual(dict(os.environ), ambient_before)

    def test_rejects_named_and_prefixed_keys_including_empty_values(self) -> None:
        forbidden_cases = [
            *FORBIDDEN_ENV_KEYS,
            "LD_LIBRARY_PATH",
            "LD_PRELOAD",
            "LD_ANYTHING",
            "DYLD_LIBRARY_PATH",
            "DYLD_PRINT_LIBRARIES",
            "DYLD_INSERT_LIBRARIES",
        ]
        for key in forbidden_cases:
            for val in ("", "1", "/some/path"):
                with self.subTest(key=key, val=val):
                    env = {"PATH": "/usr/bin:/bin", key: val}
                    before = dict(env)
                    with self.assertRaises(ValueError) as ctx:
                        reject_conflicting_environment(env)
                    self.assertIn(key, str(ctx.exception))
                    self.assertEqual(env, before)

    def test_rejects_non_mapping_and_non_string_entries(self) -> None:
        with self.assertRaises(ValueError):
            reject_conflicting_environment(["PATH=/usr/bin"])  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            reject_conflicting_environment({"": "val"})
        with self.assertRaises(ValueError):
            reject_conflicting_environment({"PATH": None})  # type: ignore[dict-item]
        with self.assertRaises(ValueError):
            reject_conflicting_environment({123: "val"})  # type: ignore[dict-item]


class TestObserveRegularFilePin(unittest.TestCase):
    """Verify bounded streaming regular-file observation and external alias preservation."""

    def test_streams_regular_file_and_preserves_bin_dotdot_libexec_and_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(strict=True)
            real_dir = root / "libexec" / "gcc"
            bin_dir = root / "bin"
            real_dir.mkdir(parents=True)
            bin_dir.mkdir(parents=True)

            payload = b'{"profile": "instrumented", "count": 17}\n'
            target_file = real_dir / "f951.json"
            target_file.write_bytes(payload)

            alias_link = root / "libexec" / "f951-link.json"
            os.symlink("gcc/f951.json", alias_link)

            lexical_alias = f"{root}/bin/../libexec/f951-link.json"
            expected_sha = _sha256_bytes(payload)
            expected_pin = FilePin(
                path=lexical_alias,
                sha256=expected_sha,
                size_bytes=len(payload),
            )

            obs = _observe_regular_file_pin(
                lexical_alias,
                expected_pin=expected_pin,
                chunk_size=13,
            )
            self.assertIsInstance(obs, _ObservedRegularFilePin)
            self.assertEqual(obs.path, lexical_alias)
            self.assertEqual(obs.resolved_path, str(target_file))
            self.assertEqual(obs.sha256, expected_sha)
            self.assertEqual(obs.size_bytes, len(payload))
            self.assertEqual(obs.as_file_pin(), expected_pin)
            self.assertEqual(len(obs.identity_tuple), 5)
            self.assertTrue(all(type(x) is int for x in obs.identity_tuple))

            expected_edge_path = str(alias_link)
            self.assertEqual(
                obs.symlinks,
                (_SymlinkEdge(path=expected_edge_path, target="gcc/f951.json"),),
            )
            row = obs.to_manifest_row()
            self.assertEqual(
                row,
                {
                    "path": lexical_alias,
                    "resolved_path": str(target_file),
                    "sha256": expected_sha,
                    "size_bytes": len(payload),
                    "symlinks": [{"path": expected_edge_path, "target": "gcc/f951.json"}],
                },
            )

            doc = _read_pinned_json(expected_pin, chunk_size=13)
            self.assertEqual(doc.pin.path, lexical_alias)
            self.assertEqual(doc.observation.path, lexical_alias)
            self.assertEqual(doc.observation.resolved_path, str(target_file))
            self.assertEqual(doc.observation.symlinks, obs.symlinks)
            self.assertEqual(doc.payload, {"profile": "instrumented", "count": 17})

    def test_rejects_missing_directory_nonregular_and_mismatched_pins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(strict=True)
            reg = root / "file.txt"
            data = b"hello world\n"
            reg.write_bytes(data)
            sha = _sha256_bytes(data)

            # Missing file
            with self.assertRaises(ValueError):
                _observe_regular_file_pin(str(root / "missing.txt"))

            # Directory rejected
            with self.assertRaises(ValueError):
                _observe_regular_file_pin(str(root))

            # Dangling symlink rejected
            dangling = root / "dangling.lnk"
            os.symlink(root / "nonexistent.target", dangling)
            with self.assertRaises(ValueError):
                _observe_regular_file_pin(str(dangling))

            # Symlink loop rejected
            loop_a = root / "loop_a"
            loop_b = root / "loop_b"
            os.symlink(loop_b, loop_a)
            os.symlink(loop_a, loop_b)
            with self.assertRaises(ValueError):
                _observe_regular_file_pin(str(loop_a))

            # FIFO rejected when supported by OS
            fifo_path = root / "named.fifo"
            try:
                os.mkfifo(fifo_path)
            except (AttributeError, OSError):
                fifo_path = None
            if fifo_path is not None:
                with self.assertRaises(ValueError):
                    _observe_regular_file_pin(str(fifo_path))

            # Wrong expected_pin.path
            wrong_path_pin = FilePin(
                path=str(root / "other.txt"),
                sha256=sha,
                size_bytes=len(data),
            )
            with self.assertRaises(ValueError):
                _observe_regular_file_pin(str(reg), expected_pin=wrong_path_pin)

            # Wrong expected_pin.sha256
            wrong_sha_pin = FilePin(
                path=str(reg),
                sha256="f" * 64,
                size_bytes=len(data),
            )
            with self.assertRaises(ValueError):
                _observe_regular_file_pin(str(reg), expected_pin=wrong_sha_pin)

            # Wrong expected_pin.size_bytes
            wrong_size_pin = FilePin(
                path=str(reg),
                sha256=sha,
                size_bytes=len(data) + 1,
            )
            with self.assertRaises(ValueError):
                _observe_regular_file_pin(str(reg), expected_pin=wrong_size_pin)


class TestPinnedJsonReader(unittest.TestCase):
    """Verify hash-before-parse ordering, duplicate-key rejection, and constant rejection."""

    def test_valid_pinned_json_returns_tied_document(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(strict=True)
            json_path = root / "manifest.json"
            raw = b'{"schema_id": "protstruct_refmac_diagnostic_profile_v1", "count": 3}\n'
            json_path.write_bytes(raw)
            pin = FilePin(
                path=str(json_path),
                sha256=_sha256_bytes(raw),
                size_bytes=len(raw),
            )
            doc = _read_pinned_json(pin, chunk_size=11)
            self.assertIsInstance(doc, _PinnedJsonDocument)
            self.assertEqual(doc.pin, pin)
            self.assertEqual(doc.observation.as_file_pin(), pin)
            self.assertEqual(
                doc.payload,
                {"schema_id": "protstruct_refmac_diagnostic_profile_v1", "count": 3},
            )

    def test_hash_and_size_checked_before_json_loads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(strict=True)
            bad_json_path = root / "corrupt.json"
            # Syntactically broken JSON with duplicate keys and NaN
            raw = b'{"a": 1, "a": NaN, BROKEN'
            bad_json_path.write_bytes(raw)

            wrong_sha_pin = FilePin(
                path=str(bad_json_path),
                sha256="0" * 64,
                size_bytes=len(raw),
            )
            wrong_size_pin = FilePin(
                path=str(bad_json_path),
                sha256=_sha256_bytes(raw),
                size_bytes=len(raw) + 5,
            )

            with mock.patch("refmac_diagnostic_profile.json.loads") as mocked_loads:
                with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                    _read_pinned_json(wrong_sha_pin)
                with self.assertRaisesRegex(ValueError, "size mismatch"):
                    _read_pinned_json(wrong_size_pin)
                with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                    _parse_verified_json_bytes(raw, expected_pin=wrong_sha_pin)
                mocked_loads.assert_not_called()

    def test_rejects_duplicate_keys_and_nonstandard_constants_after_pin_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(strict=True)
            cases = [
                ("dup_top.json", b'{"a": 1, "a": 2}\n', "Duplicate JSON object key"),
                ("dup_nested.json", b'{"outer": {"k": "x", "k": "y"}}\n', "Duplicate JSON object key"),
                ("nan.json", b'{"x": NaN}\n', "Non-standard JSON numeric constant"),
                ("inf.json", b'{"x": Infinity}\n', "Non-standard JSON numeric constant"),
                ("neginf.json", b'{"x": -Infinity}\n', "Non-standard JSON numeric constant"),
                ("syntax.json", b'{"x": }\n', "Invalid JSON syntax"),
                ("utf8.json", b'\xff\xfe\x00\x00', "not valid UTF-8"),
            ]
            for name, raw, pattern in cases:
                with self.subTest(name=name):
                    path = root / name
                    path.write_bytes(raw)
                    pin = FilePin(
                        path=str(path),
                        sha256=_sha256_bytes(raw),
                        size_bytes=len(raw),
                    )
                    with self.assertRaisesRegex(ValueError, pattern):
                        _read_pinned_json(pin)


class TestReaderBoundaryRegressions(unittest.TestCase):
    """Focused synthetic regressions for Task 657 (#1158, #1159, #1160, #1161)."""

    def _assert_fd_is_closed(self, fd: int) -> None:
        self.assertGreaterEqual(fd, 0)
        with self.assertRaises(OSError) as ctx:
            os.fstat(fd)
        self.assertEqual(ctx.exception.errno, errno.EBADF)

    def test_1158_rejects_trailing_slash_and_dot_regular_file_spellings_and_symlink_targets(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(strict=True)
            regular = root / "regular.json"
            raw = b'{"ok": true}\n'
            regular.write_bytes(raw)
            sha = _sha256_bytes(raw)

            # Direct regular-file spellings with directory suffixes must fail.
            bad_direct_spellings = [
                f"{regular}/",
                f"{regular}/.",
                f"{regular}/..",
            ]
            for bad_spelling in bad_direct_spellings:
                with self.subTest(direct_spelling=bad_spelling):
                    pin = FilePin(path=bad_spelling, sha256=sha, size_bytes=len(raw))
                    with self.assertRaises(ValueError):
                        _observe_regular_file_pin(bad_spelling)
                    with self.assertRaises(ValueError):
                        _read_pinned_json(pin)

            # Symlinks whose target ends in regular.json/ or regular.json/. must also fail.
            bad_link_targets = [
                ("link_rel_slash.json", "regular.json/"),
                ("link_rel_dot.json", "regular.json/."),
                ("link_abs_slash.json", f"{regular}/"),
                ("link_abs_dot.json", f"{regular}/."),
            ]
            for link_name, target_spelling in bad_link_targets:
                with self.subTest(link_name=link_name, target=target_spelling):
                    link_path = root / link_name
                    os.symlink(target_spelling, link_path)
                    pin = FilePin(
                        path=str(link_path),
                        sha256=sha,
                        size_bytes=len(raw),
                    )
                    with self.assertRaises(ValueError):
                        _observe_regular_file_pin(str(link_path))
                    with self.assertRaises(ValueError):
                        _read_pinned_json(pin)

            # Positive direct and valid symlink aliases still succeed and preserve lexical string.
            good_link = root / "valid_link.json"
            os.symlink("regular.json", good_link)
            for valid_lexical in (str(regular), str(good_link)):
                with self.subTest(valid_lexical=valid_lexical):
                    pin = FilePin(
                        path=valid_lexical,
                        sha256=sha,
                        size_bytes=len(raw),
                    )
                    obs = _observe_regular_file_pin(valid_lexical, expected_pin=pin)
                    self.assertEqual(obs.path, valid_lexical)
                    self.assertEqual(obs.resolved_path, str(regular))
                    doc = _read_pinned_json(pin)
                    self.assertEqual(doc.observation.path, valid_lexical)
                    self.assertEqual(doc.payload, {"ok": True})

    def test_1159_closes_fd_on_wrong_size_identity_fstat_and_fdopen_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(strict=True)
            target = root / "payload.json"
            raw = b'{"value": 42}\n'
            target.write_bytes(raw)
            sha = _sha256_bytes(raw)
            valid_pin = FilePin(path=str(target), sha256=sha, size_bytes=len(raw))
            wrong_size_pin = FilePin(
                path=str(target),
                sha256=sha,
                size_bytes=len(raw) + 7,
            )

            real_open = os.open
            real_close = os.close
            real_fstat = os.fstat

            def run_with_fd_tracking(call):
                opened_fds: list[int] = []
                closed_fds: list[int] = []

                def tracked_open(path, flags, *args, **kwargs):
                    fd = real_open(path, flags, *args, **kwargs)
                    opened_fds.append(fd)
                    return fd

                def tracked_close(fd):
                    closed_fds.append(fd)
                    return real_close(fd)

                with (
                    mock.patch("refmac_diagnostic_profile.os.open", side_effect=tracked_open),
                    mock.patch("refmac_diagnostic_profile.os.close", side_effect=tracked_close),
                ):
                    call()
                return opened_fds, closed_fds

            # 1. Wrong-size ValueError before fdopen in both readers.
            for reader_name, invoke in (
                (
                    "observe_wrong_size",
                    lambda: _observe_regular_file_pin(
                        str(target), expected_pin=wrong_size_pin
                    ),
                ),
                ("read_json_wrong_size", lambda: _read_pinned_json(wrong_size_pin)),
            ):
                with self.subTest(case=reader_name):
                    with mock.patch("refmac_diagnostic_profile.os.fdopen") as mocked_fdopen:
                        opened, closed = run_with_fd_tracking(
                            lambda: self.assertRaisesRegex(
                                ValueError, r"[Ss]ize mismatch", invoke
                            )
                        )
                        mocked_fdopen.assert_not_called()
                    self.assertEqual(len(opened), 1)
                    self.assertEqual(closed, opened)
                    self._assert_fd_is_closed(opened[0])

            # 2. Identity mismatch ValueError before fdopen in both readers.
            real_target_st = os.lstat(target)
            mutated_st = os.stat_result(
                (
                    real_target_st.st_mode,
                    real_target_st.st_ino + 99999,
                    real_target_st.st_dev,
                    real_target_st.st_nlink,
                    real_target_st.st_uid,
                    real_target_st.st_gid,
                    real_target_st.st_size,
                    real_target_st.st_atime,
                    real_target_st.st_mtime,
                    real_target_st.st_ctime,
                )
            )
            for reader_name, invoke in (
                ("observe_identity_mismatch", lambda: _observe_regular_file_pin(str(target))),
                ("read_json_identity_mismatch", lambda: _read_pinned_json(valid_pin)),
            ):
                with self.subTest(case=reader_name):
                    with (
                        mock.patch(
                            "refmac_diagnostic_profile.os.fstat",
                            return_value=mutated_st,
                        ),
                        mock.patch("refmac_diagnostic_profile.os.fdopen") as mocked_fdopen,
                    ):
                        opened, closed = run_with_fd_tracking(
                            lambda: self.assertRaisesRegex(
                                ValueError,
                                "File identity changed between lstat and open",
                                invoke,
                            )
                        )
                        mocked_fdopen.assert_not_called()
                    self.assertEqual(len(opened), 1)
                    self.assertEqual(closed, opened)
                    self._assert_fd_is_closed(opened[0])

            # 3. os.fstat OSError before fdopen in both readers (must not mask original failure).
            for reader_name, invoke in (
                ("observe_fstat_oserror", lambda: _observe_regular_file_pin(str(target))),
                ("read_json_fstat_oserror", lambda: _read_pinned_json(valid_pin)),
            ):
                with self.subTest(case=reader_name):
                    with mock.patch(
                        "refmac_diagnostic_profile.os.fstat",
                        side_effect=OSError(errno.EIO, "synthetic fstat I/O error"),
                    ):
                        opened, closed = run_with_fd_tracking(
                            lambda: self.assertRaisesRegex(
                                ValueError,
                                "synthetic fstat I/O error",
                                invoke,
                            )
                        )
                    self.assertEqual(len(opened), 1)
                    self.assertEqual(closed, opened)
                    self._assert_fd_is_closed(opened[0])

            # 4. os.fdopen failure in both readers (ownership not transferred; finally closes fd).
            for reader_name, invoke in (
                ("observe_fdopen_failure", lambda: _observe_regular_file_pin(str(target))),
                ("read_json_fdopen_failure", lambda: _read_pinned_json(valid_pin)),
            ):
                with self.subTest(case=reader_name):
                    with mock.patch(
                        "refmac_diagnostic_profile.os.fdopen",
                        side_effect=OSError(errno.EINVAL, "synthetic fdopen failure"),
                    ):
                        opened, closed = run_with_fd_tracking(
                            lambda: self.assertRaisesRegex(
                                ValueError,
                                "synthetic fdopen failure",
                                invoke,
                            )
                        )
                    self.assertEqual(len(opened), 1)
                    self.assertEqual(closed, opened)
                    self._assert_fd_is_closed(opened[0])

            # 5. Open failure itself never closes a bystander descriptor; post-fdopen error
            # does not double-close via os.close(fd) after fileobj took ownership.
            bystander_fd = real_open(str(target), os.O_RDONLY)
            try:
                with mock.patch(
                    "refmac_diagnostic_profile.os.open",
                    side_effect=OSError(errno.EACCES, "synthetic open denied"),
                ):
                    with mock.patch(
                        "refmac_diagnostic_profile.os.close",
                        side_effect=real_close,
                    ) as mocked_close:
                        with self.assertRaisesRegex(ValueError, "synthetic open denied"):
                            _observe_regular_file_pin(str(target))
                        mocked_close.assert_not_called()
                # Bystander fd remains open and valid.
                self.assertEqual(real_fstat(bystander_fd).st_ino, real_target_st.st_ino)
            finally:
                real_close(bystander_fd)

            # 6. Post-fdopen streaming failure closes via fileobj context manager without
            # finally calling os.close(fd) a second time.
            stream_grow_pin = FilePin(
                path=str(target),
                sha256=sha,
                size_bytes=len(raw),
            )
            real_fdopen = os.fdopen

            def fdopen_with_extra_bytes(fd, mode="rb", *args, **kwargs):
                handle = real_fdopen(fd, mode, *args, **kwargs)
                orig_read = handle.read

                def oversized_read(n=-1):
                    data = orig_read(n)
                    return data + b"extra" if data else b""

                handle.read = oversized_read  # type: ignore[method-assign]
                return handle

            with mock.patch(
                "refmac_diagnostic_profile.os.fdopen",
                side_effect=fdopen_with_extra_bytes,
            ):
                opened, closed = run_with_fd_tracking(
                    lambda: self.assertRaisesRegex(
                        ValueError,
                        "streamed bytes exceeded expected",
                        lambda: _read_pinned_json(stream_grow_pin),
                    )
                )
            self.assertEqual(len(opened), 1)
            # finally did not call os.close(fd) because fd_owned_by_fileobj was True;
            # the context manager on handle closed the underlying descriptor.
            self.assertEqual(closed, [])
            self._assert_fd_is_closed(opened[0])

    def test_1160_nonblocking_open_rejects_regular_to_fifo_replacement_without_blocking(
        self,
    ) -> None:
        if not hasattr(os, "mkfifo") or not hasattr(os, "O_NONBLOCK"):
            self.skipTest("POSIX mkfifo and O_NONBLOCK required")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(strict=True)
            raw = b'{"fifo_test": 1}\n'
            sha = _sha256_bytes(raw)

            real_open = os.open
            real_close = os.close

            for reader_name in ("observe", "read_json"):
                with self.subTest(reader=reader_name):
                    victim = root / f"victim_{reader_name}.json"
                    victim.write_bytes(raw)
                    pin = FilePin(path=str(victim), sha256=sha, size_bytes=len(raw))

                    opened_fds: list[int] = []
                    closed_fds: list[int] = []
                    observed_flags: list[int] = []

                    def replace_with_fifo_then_open(path, flags, *args, **kwargs):
                        observed_flags.append(flags)
                        # Assert O_NONBLOCK and O_NOFOLLOW are set before opening FIFO
                        self.assertTrue(flags & os.O_NONBLOCK)
                        if hasattr(os, "O_NOFOLLOW"):
                            self.assertTrue(flags & os.O_NOFOLLOW)
                        os.unlink(path)
                        os.mkfifo(path)
                        fd = real_open(path, flags, *args, **kwargs)
                        opened_fds.append(fd)
                        return fd

                    def tracked_close(fd):
                        closed_fds.append(fd)
                        return real_close(fd)

                    with (
                        mock.patch(
                            "refmac_diagnostic_profile.os.open",
                            side_effect=replace_with_fifo_then_open,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.close",
                            side_effect=tracked_close,
                        ),
                        mock.patch("refmac_diagnostic_profile.os.fdopen") as mocked_fdopen,
                    ):
                        with self.assertRaisesRegex(
                            ValueError, "Opened descriptor is not a regular file"
                        ):
                            if reader_name == "observe":
                                _observe_regular_file_pin(str(victim), expected_pin=pin)
                            else:
                                _read_pinned_json(pin)
                        mocked_fdopen.assert_not_called()

                    self.assertEqual(len(observed_flags), 1)
                    self.assertEqual(len(opened_fds), 1)
                    self.assertEqual(closed_fds, opened_fds)
                    self._assert_fd_is_closed(opened_fds[0])

    def test_1161_rejects_persistent_symlink_retarget_after_precheck_in_both_readers(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve(strict=True)
            raw = b'{"same_content": true}\n'
            sha = _sha256_bytes(raw)

            target_a = root / "target_a.json"
            target_b = root / "target_b.json"
            target_a.write_bytes(raw)
            target_b.write_bytes(raw)

            real_fdopen = os.fdopen

            for reader_name in ("observe", "read_json"):
                with self.subTest(reader=reader_name, level="outer"):
                    alias = root / f"alias_{reader_name}.json"
                    os.symlink("target_a.json", alias)
                    pin = FilePin(path=str(alias), sha256=sha, size_bytes=len(raw))

                    def retarget_symlink_on_fdopen(fd, mode="rb", *args, **kwargs):
                        handle = real_fdopen(fd, mode, *args, **kwargs)
                        replacement_link = root / f"alias_{reader_name}.tmp"
                        os.symlink("target_b.json", replacement_link)
                        os.replace(replacement_link, alias)
                        return handle

                    with mock.patch(
                        "refmac_diagnostic_profile.os.fdopen",
                        side_effect=retarget_symlink_on_fdopen,
                    ):
                        with self.assertRaisesRegex(
                            ValueError,
                            "(Lexical path identity changed|Symlink edges changed|Resolved target path changed)",
                        ):
                            if reader_name == "observe":
                                _observe_regular_file_pin(str(alias), expected_pin=pin)
                            else:
                                _read_pinned_json(pin)

                with self.subTest(reader=reader_name, level="inner_hop"):
                    inner = root / f"inner_{reader_name}.json"
                    outer = root / f"outer_{reader_name}.json"
                    os.symlink("target_a.json", inner)
                    os.symlink(f"inner_{reader_name}.json", outer)
                    pin = FilePin(path=str(outer), sha256=sha, size_bytes=len(raw))

                    def retarget_inner_hop_on_fdopen(fd, mode="rb", *args, **kwargs):
                        handle = real_fdopen(fd, mode, *args, **kwargs)
                        replacement_inner = root / f"inner_{reader_name}.tmp"
                        os.symlink("target_b.json", replacement_inner)
                        os.replace(replacement_inner, inner)
                        return handle

                    with mock.patch(
                        "refmac_diagnostic_profile.os.fdopen",
                        side_effect=retarget_inner_hop_on_fdopen,
                    ):
                        with self.assertRaisesRegex(
                            ValueError,
                            "Symlink edges changed during read",
                        ):
                            if reader_name == "observe":
                                _observe_regular_file_pin(str(outer), expected_pin=pin)
                            else:
                                _read_pinned_json(pin)


def _make_file_pin_on_disk(path: Path | str) -> FilePin:
    raw_lexical = str(path)
    resolved = Path(raw_lexical).resolve(strict=True)
    data = resolved.read_bytes()
    return FilePin(
        path=raw_lexical,
        sha256=_sha256_bytes(data),
        size_bytes=len(data),
    )


def _build_synthetic_outer_profile_fixture(base_dir: Path) -> dict[str, object]:
    """Construct a small self-contained synthetic profile tree on disk with opaque IDs."""
    root = base_dir.resolve(strict=True) / "fixture"
    root.mkdir()
    trees = {name: root / name for name in ("vendor", "prepared", "build")}
    for tree_path in trees.values():
        tree_path.mkdir()

    # Include root-level vendor/.git metadata (sole permitted exclusion)
    vendor_git = trees["vendor"] / ".git"
    vendor_git.mkdir()
    (vendor_git / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")

    files: dict[str, dict[str, object]] = {}
    roles: dict[str, list[str]] = {}
    by_lexical_path: dict[str, str] = {}

    def create_file(
        rel_path: str,
        content: str | None = None,
        *,
        executable: bool = False,
    ) -> Path:
        target = root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        text = content if content is not None else f"synthetic:{rel_path}\n"
        target.write_text(text, encoding="utf-8")
        if executable:
            target.chmod(0o755)
        return target

    def register_path(raw_path: Path | str) -> str:
        raw_str = str(raw_path)
        if raw_str not in by_lexical_path:
            by_lexical_path[raw_str] = f"opaque_item_{len(by_lexical_path)}"
        ident = by_lexical_path[raw_str]
        obs = _observe_regular_file_pin(raw_str)
        files[ident] = obs.to_manifest_row()
        return ident

    def add_single_role(
        role_name: str,
        rel_path: str,
        content: str | None = None,
        *,
        executable: bool = False,
    ) -> Path:
        created = create_file(rel_path, content, executable=executable)
        roles[role_name] = [register_path(created)]
        return created

    # Controlled root members (including hidden files and ordinary tree files without explicit roles)
    vendor_src = create_file("vendor/source.f", "C synthetic upstream\n")
    create_file("vendor/.hidden_vendor_cfg", "vendor_hidden=1\n")
    create_file("prepared/source.f", vendor_src.read_text(encoding="utf-8"))
    create_file("prepared/.hidden_prepared_cfg", "prepared_hidden=1\n")
    create_file("prepared/refmac_diagnostic_hooks.patch", "synthetic patch\n")
    add_single_role(
        "source_manifest",
        "prepared/refmac_diagnostic_source_manifest.json",
        '{"schema_id": "protstruct_refmac_diagnostic_source_manifest_v1"}\n',
    )

    writer = add_single_role(
        "writer_input", "support/input/trace_writer.f90", "synthetic writer\n"
    )
    hooks = add_single_role(
        "hooks_input", "support/input/trace_hooks.f90", "synthetic hooks\n"
    )
    create_file("prepared/trace_writer.f90", writer.read_text(encoding="utf-8"))
    create_file("prepared/trace_hooks.f90", hooks.read_text(encoding="utf-8"))

    for role_name, fname in (
        ("preparation_receipt", "preparation-completed.json"),
        ("preparer", "prepare_refmac_diagnostic.py"),
        ("preparation_interpreter", "preparation-python"),
        ("source_auditor", "check-prepared-source.py"),
        ("source_audit", "source-audit.json"),
        ("source_audit_interpreter", "audit-python"),
        ("build_launch", "build-completed.json"),
        ("build_interpreter", "build-python"),
        ("build_qc", "composition-qc.json"),
        ("build_qc_implementation", "compose-diagnostic-profile.py"),
        ("runtime_observation", "runtime-observation.json"),
        ("runtime_observer", "observe-runtime.py"),
        ("ccp4_setup", "installed/bin/ccp4.setup-sh"),
        ("launcher", "launch-attempt04.py"),
        ("collection_interpreter", "collection-python"),
    ):
        add_single_role(
            role_name,
            f"support/{fname}",
            "{}\n" if fname.endswith(".json") else None,
        )

    for role_name, orig_name, copy_name in (
        ("build_driver", "build-instrumented-v2.py", "build-driver.py"),
        ("build_journal", "build-journal.py", "build-journal.py"),
        (
            "build_runtime_config",
            "installed-runtime.cmake",
            "installed-runtime.cmake",
        ),
    ):
        pair_text = f"pair:{role_name}:{copy_name}\n"
        orig_p = create_file(f"support/originals/{orig_name}", pair_text)
        copy_p = create_file(f"build/{copy_name}", pair_text)
        roles[role_name] = [register_path(orig_p), register_path(copy_p)]

    roles["build_inventories"] = []
    for inv_name in (
        "toolchain-inventory.json",
        "effective-build-tools.json",
        "assembler-tool.json",
        "post-link-tools.json",
    ):
        inv_text = f'{{"inventory": "{inv_name}"}}\n'
        orig_inv = create_file(f"support/originals/{inv_name}", inv_text)
        copy_inv = create_file(f"build/{inv_name}", inv_text)
        roles["build_inventories"].extend(
            [register_path(orig_inv), register_path(copy_inv)]
        )

    roles["build_external_inputs"] = [
        register_path(create_file("support/compiler-input.txt"))
    ]
    add_single_role(
        "build_receipt",
        "build/build-receipt.json",
        '{"contract": "protstruct_instrumented_build_receipt_v2"}\n',
    )
    add_single_role(
        "linked_executable",
        "build/refmac5.linked-unrelocated",
        "synthetic linked binary\n",
        executable=True,
    )
    executable_path = add_single_role(
        "diagnostic_executable",
        "build/subdir/refmac5",
        "synthetic diagnostic binary\n",
        executable=True,
    )
    create_file("build/ordinary_object.o", "ordinary build object without role\n")
    create_file("build/.hidden_build_marker", "build_hidden=1\n")

    installed_ref = add_single_role(
        "installed_reference",
        "installed/bin/refmac5",
        "synthetic installed stock binary\n",
        executable=True,
    )
    roles["ccp4_setup_dependencies"] = [
        register_path(create_file("installed/setup-dep.sh"))
    ]
    roles["runtime_images"] = [
        register_path(create_file("installed/lib/libccp4.dylib"))
    ]
    roles["collector_helpers"] = [
        register_path(create_file(f"support/scripts/{helper_name}"))
        for helper_name in EXPECTED_COLLECTOR_HELPER_NAMES
    ]

    qc_base = create_file("support/qc-item.json", "{}\n")
    alias_symlink = root / "support" / "python-alias"
    os.symlink("collection-python", alias_symlink)
    (root / "support" / "bin").mkdir(parents=True, exist_ok=True)
    alias_dotdot = f"{root}/support/bin/../collection-python"

    roles["qc_evidence"] = sorted(
        [
            register_path(qc_base),
            roles["collection_interpreter"][0],
            register_path(alias_symlink),
            register_path(alias_dotdot),
        ]
    )

    for tree_path in trees.values():
        for member in sorted(tree_path.rglob("*")):
            if ".git" in member.parts:
                continue
            if member.is_file():
                register_path(member)

    env_values = {key: f"val-{key}" for key in sorted(EXPECTED_RUNTIME_ENV_KEYS)}
    manifest_payload: dict[str, object] = {
        "schema_id": PROFILE_SCHEMA_ID,
        "profile_id": SUPPORTED_PROFILE_ID,
        "subject_id": PROFILE_SUBJECT_ID,
        "upstream": {
            "commit": UPSTREAM_COMMIT,
            "tag": UPSTREAM_TAG,
        },
        "roots": {
            name: {
                "path": str(tree_path),
                "file_ids": [
                    fid
                    for fid, frow in sorted(files.items())
                    if Path(str(frow["path"])).is_relative_to(tree_path)
                ],
            }
            for name, tree_path in trees.items()
        },
        "files": files,
        "roles": roles,
        "runtime_environment": {
            "observation_file_id": roles["runtime_observation"][0],
            "expected_values": env_values,
            "expected_absent": list(EXPECTED_RUNTIME_ABSENT_KEYS),
        },
    }

    manifest_path = root / "diagnostic-profile.json"
    manifest_bytes = (json.dumps(manifest_payload, indent=2) + "\n").encode("utf-8")
    manifest_path.write_bytes(manifest_bytes)
    manifest_pin = _make_file_pin_on_disk(manifest_path)
    executable_pin = _make_file_pin_on_disk(executable_path)
    profile = RefmacDiagnosticProfile(
        profile_id=SUPPORTED_PROFILE_ID,
        manifest=manifest_pin,
        executable=executable_pin,
    )
    return {
        "root": root,
        "trees": trees,
        "manifest_path": manifest_path,
        "manifest_payload": manifest_payload,
        "profile": profile,
        "executable_path": executable_path,
        "installed_ref": installed_ref,
        "alias_symlink": alias_symlink,
        "alias_dotdot": alias_dotdot,
    }


def _rewrite_manifest_and_profile(
    fixture: dict[str, object],
    payload: dict[str, object],
) -> RefmacDiagnosticProfile:
    manifest_path = fixture["manifest_path"]
    assert isinstance(manifest_path, Path)
    raw = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
    manifest_path.write_bytes(raw)
    manifest_pin = _make_file_pin_on_disk(manifest_path)
    orig_profile = fixture["profile"]
    assert isinstance(orig_profile, RefmacDiagnosticProfile)
    return RefmacDiagnosticProfile(
        profile_id=orig_profile.profile_id,
        manifest=manifest_pin,
        executable=orig_profile.executable,
    )


class TestOuterManifestAndFileRootObservations(unittest.TestCase):
    """Focused synthetic tests for Task 658 closed outer manifest shape and file/root observations."""

    def test_valid_outer_manifest_and_observations_preserve_aliases_and_immutability(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = _build_synthetic_outer_profile_fixture(Path(tmp))
            profile = fx["profile"]
            assert isinstance(profile, RefmacDiagnosticProfile)
            manifest_payload = fx["manifest_payload"]
            assert isinstance(manifest_payload, dict)
            absent_ev = fx["root"] / "absent-evidence-root"  # type: ignore[operator]
            staged_ev = fx["root"] / "staged-evidence-root"  # type: ignore[operator]
            staged_ev.mkdir()

            checked_shape = _validate_outer_manifest_shape(
                manifest_payload,
                expected_profile_id=profile.profile_id,
                expected_executable_pin=profile.executable,
            )
            self.assertIsInstance(checked_shape, _CheckedOuterManifest)
            self.assertEqual(checked_shape.schema_id, PROFILE_SCHEMA_ID)
            self.assertEqual(checked_shape.profile_id, SUPPORTED_PROFILE_ID)
            self.assertEqual(checked_shape.subject_id, PROFILE_SUBJECT_ID)
            self.assertEqual(checked_shape.upstream_commit, UPSTREAM_COMMIT)
            self.assertEqual(checked_shape.upstream_tag, UPSTREAM_TAG)
            self.assertEqual(len(checked_shape.roles), 31)

            # Mutating input dict after validation does not affect frozen _CheckedOuterManifest
            mutated_input = copy.deepcopy(manifest_payload)
            _validate_outer_manifest_shape(mutated_input)
            mutated_input["schema_id"] = "mutated"
            self.assertEqual(checked_shape.schema_id, PROFILE_SCHEMA_ID)

            # Observe with absent evidence_root (launcher mode) and existing evidence_root (collector mode)
            for ev_root in (absent_ev, staged_ev):
                with self.subTest(evidence_root=str(ev_root)):
                    state = _validate_and_observe_outer_profile(
                        profile,
                        evidence_root=ev_root,
                        chunk_size=64,
                    )
                    self.assertIsInstance(state, _CheckedOuterProfileState)
                    self.assertEqual(state.selected_executable, profile.executable)
                    self.assertEqual(state.evidence_root, str(ev_root))
                    self.assertGreaterEqual(
                        len(state.evidence_root_ancestor_identities), 1
                    )
                    self.assertTrue(state.outer_files_verified)
                    self.assertEqual(
                        state.inner_receipt_joins_status, "deferred_to_next_slice"
                    )
                    self.assertEqual(state.runtime_image_coverage, "not_assessed")
                    self.assertTrue(
                        state.observed_roots["vendor"].excluded_root_git_present
                    )
                    self.assertFalse(
                        state.observed_roots["prepared"].excluded_root_git_present
                    )
                    self.assertFalse(
                        state.observed_roots["build"].excluded_root_git_present
                    )

                    # Verify external symlink alias and bin/../collection-python lexical preservation
                    alias_symlink_str = str(fx["alias_symlink"])
                    alias_dotdot_str = str(fx["alias_dotdot"])
                    obs_by_lex = {
                        obs.path: obs for obs in state.observed_files.values()
                    }
                    self.assertIn(alias_symlink_str, obs_by_lex)
                    self.assertIn(alias_dotdot_str, obs_by_lex)
                    self.assertEqual(
                        obs_by_lex[alias_symlink_str].symlinks,
                        (
                            _SymlinkEdge(
                                path=alias_symlink_str, target="collection-python"
                            ),
                        ),
                    )
                    self.assertEqual(obs_by_lex[alias_dotdot_str].symlinks, ())
                    self.assertEqual(
                        obs_by_lex[alias_symlink_str].resolved_path,
                        obs_by_lex[alias_dotdot_str].resolved_path,
                    )
                    self.assertIn(alias_symlink_str, state.observed_symlinks)

                    # Deep immutability checks on returned structures
                    with self.assertRaises(FrozenInstanceError):
                        state.outer_files_verified = False  # type: ignore[misc]
                    with self.assertRaises(TypeError):
                        state.observed_files["new"] = obs_by_lex[alias_symlink_str]  # type: ignore[index]
                    with self.assertRaises(TypeError):
                        state.outer_manifest.roles["qc_evidence"] = ()  # type: ignore[index]
                    with self.assertRaises(TypeError):
                        state.outer_manifest.runtime_environment.expected_values["CBIN"] = "x"  # type: ignore[index]
                    with self.assertRaises(TypeError):
                        state.observed_roots["vendor"].member_pins["x"] = profile.executable  # type: ignore[index]

                    recheck = _reobserve_outer_profile_state(state, chunk_size=64)
                    self.assertIsInstance(recheck, _OuterProfileRecheckResult)
                    self.assertTrue(recheck.verified)
                    self.assertEqual(recheck.errors, ())
                    with self.assertRaises(TypeError):
                        recheck.observed_files["x"] = obs_by_lex[alias_symlink_str]  # type: ignore[index]

    def test_outer_manifest_rejects_shape_type_role_and_pin_violations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = _build_synthetic_outer_profile_fixture(Path(tmp))
            base_payload = fx["manifest_payload"]
            assert isinstance(base_payload, dict)
            profile = fx["profile"]
            assert isinstance(profile, RefmacDiagnosticProfile)

            def assert_shape_fails(mutator, pattern: str) -> None:
                candidate = copy.deepcopy(base_payload)
                mutator(candidate)
                with self.assertRaisesRegex(ValueError, pattern):
                    _validate_outer_manifest_shape(
                        candidate,
                        expected_profile_id=profile.profile_id,
                        expected_executable_pin=profile.executable,
                    )

            # 1. Extra and missing top-level keys
            assert_shape_fails(
                lambda d: d.update({"extra_top": 1}), "top-level keys mismatch"
            )
            assert_shape_fails(
                lambda d: d.pop("upstream"), "top-level keys mismatch"
            )

            # 2. Discriminators and upstream
            assert_shape_fails(
                lambda d: d.update({"schema_id": "wrong"}), "schema_id"
            )
            assert_shape_fails(
                lambda d: d.update({"profile_id": "wrong"}), "profile_id"
            )
            assert_shape_fails(
                lambda d: d.update({"subject_id": "R3"}), "subject_id"
            )
            assert_shape_fails(
                lambda d: d["upstream"].update({"commit": "0" * 40}),
                "upstream.commit",
            )
            assert_shape_fails(
                lambda d: d["upstream"].update({"tag": "5.8.0000"}),
                "upstream.tag",
            )
            assert_shape_fails(
                lambda d: d["upstream"].update({"extra": "1"}),
                "upstream must be an object",
            )

            # 3. bool-as-int in size_bytes
            first_fid = next(iter(base_payload["files"]))  # type: ignore[arg-type]
            assert_shape_fails(
                lambda d: d["files"][first_fid].update({"size_bytes": True}),
                "non-boolean int",
            )

            # 4. Duplicate lexical path across two file IDs
            second_fid = list(base_payload["files"])[1]  # type: ignore[arg-type]
            assert_shape_fails(
                lambda d: d["files"][second_fid].update(
                    {"path": d["files"][first_fid]["path"]}
                ),
                "Duplicate lexical file path",
            )

            # 5. Conflicting target pins for shared resolved_path
            alias_fid = next(
                fid
                for fid, row in base_payload["files"].items()  # type: ignore[union-attr]
                if row["path"] == str(fx["alias_symlink"])
            )
            assert_shape_fails(
                lambda d: d["files"][alias_fid].update({"size_bytes": 999999}),
                "Conflicting sha256/size_bytes pins for resolved target",
            )

            # 6. Inconsistent symlink declarations on canonical or non-matching paths
            assert_shape_fails(
                lambda d: d["files"][first_fid].update(
                    {
                        "symlinks": [
                            {
                                "path": d["files"][first_fid]["path"],
                                "target": "/tmp/nowhere",
                            }
                        ]
                    }
                ),
                "declares symlinks but path == resolved_path",
            )
            assert_shape_fails(
                lambda d: d["files"][alias_fid].update({"symlinks": []}),
                "declares no symlinks",
            )

            # 7. Role count, order, pair mismatch, and unsorted variable roles
            assert_shape_fails(
                lambda d: d["roles"].pop("qc_evidence"),
                "roles mismatch",
            )
            assert_shape_fails(
                lambda d: d["roles"].update({"custom_role": [first_fid]}),
                "roles mismatch",
            )
            assert_shape_fails(
                lambda d: d["roles"].update(
                    {"collector_helpers": list(reversed(d["roles"]["collector_helpers"]))}
                ),
                "collector_helpers",
            )
            assert_shape_fails(
                lambda d: d["roles"].update(
                    {"build_inventories": list(reversed(d["roles"]["build_inventories"]))}
                ),
                "build_inventories",
            )
            assert_shape_fails(
                lambda d: d["roles"].update(
                    {"qc_evidence": list(reversed(d["roles"]["qc_evidence"]))}
                ),
                "Variable role 'qc_evidence' IDs must be sorted lexically",
            )
            driver_orig_id = base_payload["roles"]["build_driver"][0]  # type: ignore[index]
            assert_shape_fails(
                lambda d: d["files"][driver_orig_id].update({"sha256": "e" * 64}),
                "Pair role 'build_driver' original .* and copy .* must have identical sha256",
            )

            # 8. Unused external file row
            def add_unused_external(d: dict) -> None:
                d["files"]["unused_ext"] = {
                    "path": f"{fx['root']}/support/unused.txt",
                    "resolved_path": f"{fx['root']}/support/unused.txt",
                    "sha256": "a" * 64,
                    "size_bytes": 1,
                    "symlinks": [],
                }

            assert_shape_fails(
                add_unused_external,
                "unused external file row",
            )

            # 9. runtime_environment mismatches
            assert_shape_fails(
                lambda d: d["runtime_environment"].update(
                    {"observation_file_id": first_fid}
                ),
                "observation_file_id must equal roles\\['runtime_observation'\\]\\[0\\]",
            )
            assert_shape_fails(
                lambda d: d["runtime_environment"]["expected_values"].pop("CBIN"),
                "expected_values keys mismatch",
            )
            assert_shape_fails(
                lambda d: d["runtime_environment"]["expected_values"].update(
                    {"CBIN": 123}
                ),
                "must be a str",
            )
            assert_shape_fails(
                lambda d: d["runtime_environment"].update(
                    {"expected_absent": ["BASH_ENV"]}
                ),
                "expected_absent must equal",
            )

    def test_rejects_wrong_caller_pins_and_invalid_diagnostic_executable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = _build_synthetic_outer_profile_fixture(Path(tmp))
            profile = fx["profile"]
            assert isinstance(profile, RefmacDiagnosticProfile)
            exe_path = fx["executable_path"]
            assert isinstance(exe_path, Path)
            installed_ref = fx["installed_ref"]
            assert isinstance(installed_ref, Path)

            # 1. Wrong caller manifest SHA-256 pin (within size bound: actual manifest observation is retained,
            # while outer_manifest remains None because JSON parsing is blocked before parse)
            bad_manifest_profile = RefmacDiagnosticProfile(
                profile_id=profile.profile_id,
                manifest=FilePin(
                    path=profile.manifest.path,
                    sha256="0" * 64,
                    size_bytes=profile.manifest.size_bytes,
                ),
                executable=profile.executable,
            )
            with self.assertRaises(_ProfileObservationError) as ctx:
                _validate_and_observe_outer_profile(bad_manifest_profile)
            self.assertIsNotNone(ctx.exception.partial_observation.manifest_observation)
            self.assertEqual(
                ctx.exception.partial_observation.manifest_observation.sha256,
                profile.manifest.sha256,
            )
            self.assertIsNone(ctx.exception.partial_observation.outer_manifest)

            # 2. Wrong caller executable pin
            bad_exe_profile = RefmacDiagnosticProfile(
                profile_id=profile.profile_id,
                manifest=profile.manifest,
                executable=FilePin(
                    path=profile.executable.path,
                    sha256="f" * 64,
                    size_bytes=profile.executable.size_bytes,
                ),
            )
            with self.assertRaisesRegex(
                _ProfileObservationError,
                "does not match caller-held executable FilePin",
            ) as ctx:
                _validate_and_observe_outer_profile(bad_exe_profile)
            # Manifest observation was already obtained and is retained on partial_observation
            self.assertIsNotNone(ctx.exception.partial_observation.manifest_observation)

            # 3. Non-executable diagnostic_executable on disk
            exe_path.chmod(0o644)
            try:
                with self.assertRaisesRegex(
                    _ProfileObservationError,
                    "diagnostic_executable is not executable on disk",
                ):
                    _validate_and_observe_outer_profile(profile)
            finally:
                exe_path.chmod(0o755)

            # 4. diagnostic_executable identical content/hash to installed_reference
            same_bytes = installed_ref.read_bytes()
            exe_path.write_bytes(same_bytes)
            exe_path.chmod(0o755)
            payload = copy.deepcopy(fx["manifest_payload"])
            assert isinstance(payload, dict)
            diag_id = payload["roles"]["diagnostic_executable"][0]  # type: ignore[index]
            payload["files"][diag_id]["sha256"] = _sha256_bytes(same_bytes)  # type: ignore[index]
            payload["files"][diag_id]["size_bytes"] = len(same_bytes)  # type: ignore[index]
            same_exe_profile = RefmacDiagnosticProfile(
                profile_id=profile.profile_id,
                manifest=_rewrite_manifest_and_profile(fx, payload).manifest,
                executable=_make_file_pin_on_disk(exe_path),
            )
            with self.assertRaisesRegex(
                _ProfileObservationError,
                "roles\\['diagnostic_executable'\\] sha256 must differ from roles\\['installed_reference'\\] sha256",
            ):
                _validate_and_observe_outer_profile(same_exe_profile)

    def test_controlled_roots_enforce_hidden_files_exact_git_exclusion_and_scan_errors(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = _build_synthetic_outer_profile_fixture(Path(tmp))
            trees = fx["trees"]
            assert isinstance(trees, dict)
            profile = fx["profile"]
            assert isinstance(profile, RefmacDiagnosticProfile)

            # 1. Undeclared hidden file in prepared fails root enumeration
            extra_hidden = trees["prepared"] / ".unexpected_hidden"
            extra_hidden.write_text("hidden\n", encoding="utf-8")
            try:
                with self.assertRaisesRegex(
                    _ProfileObservationError,
                    "member set mismatch.*extra_on_disk=\\['\\.unexpected_hidden'\\]",
                ) as ctx:
                    _validate_and_observe_outer_profile(profile)
                # Vendor root was already observed and retained before prepared failed!
                self.assertIn("vendor", ctx.exception.partial_observation.observed_roots)
            finally:
                extra_hidden.unlink()

            # 2. .git inside prepared or nested vendor/sub/.git is NOT excluded
            prepared_git = trees["prepared"] / ".git"
            prepared_git.mkdir()
            (prepared_git / "config").write_text("bad\n", encoding="utf-8")
            try:
                with self.assertRaisesRegex(
                    _ProfileObservationError,
                    "member set mismatch.*\\.git/config",
                ):
                    _validate_and_observe_outer_profile(profile)
            finally:
                (prepared_git / "config").unlink()
                prepared_git.rmdir()

            nested_vendor_git = trees["vendor"] / "sub" / ".git"
            nested_vendor_git.mkdir(parents=True)
            (nested_vendor_git / "HEAD").write_text("bad\n", encoding="utf-8")
            try:
                with self.assertRaisesRegex(
                    _ProfileObservationError,
                    "member set mismatch.*sub/\\.git/HEAD",
                ):
                    _validate_and_observe_outer_profile(profile)
            finally:
                (nested_vendor_git / "HEAD").unlink()
                nested_vendor_git.rmdir()
                (trees["vendor"] / "sub").rmdir()

            # 3. Symlink inside controlled root fails
            bad_sym = trees["build"] / "bad_link"
            os.symlink(trees["build"] / "ordinary_object.o", bad_sym)
            try:
                with self.assertRaisesRegex(
                    _ProfileObservationError,
                    "Controlled root 'build' contains forbidden symlink",
                ):
                    _validate_and_observe_outer_profile(profile)
            finally:
                bad_sym.unlink()

            # 4. Walk scan error via os.walk onerror raises ValueError
            outer = _validate_outer_manifest_shape(
                fx["manifest_payload"],  # type: ignore[arg-type]
                expected_profile_id=profile.profile_id,
                expected_executable_pin=profile.executable,
            )

            def fake_walk(top, topdown=True, onerror=None, followlinks=False):
                if onerror is not None:
                    onerror(PermissionError(errno.EACCES, "synthetic walk permission denied"))
                return
                yield  # pragma: no cover

            with mock.patch("refmac_diagnostic_profile.os.walk", side_effect=fake_walk):
                with self.assertRaisesRegex(
                    ValueError, "Incomplete controlled root enumeration"
                ):
                    _observe_controlled_root(
                        "vendor",
                        outer.roots["vendor"]["path"],
                        outer.roots["vendor"]["file_ids"],
                        declared_files=outer.files,
                        exclude_root_git=True,
                    )

    def test_rejects_root_and_evidence_root_overlaps_and_retains_partial_observations(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = _build_synthetic_outer_profile_fixture(Path(tmp))
            profile = fx["profile"]
            assert isinstance(profile, RefmacDiagnosticProfile)
            trees = fx["trees"]
            assert isinstance(trees, dict)

            # 1. evidence_root overlapping build root (even when absent subdir inside build)
            overlapping_ev = trees["build"] / "future-evidence-subdir"
            with self.assertRaisesRegex(
                _ProfileObservationError,
                "Controlled root 'build' .* overlaps evidence_root",
            ):
                _validate_and_observe_outer_profile(
                    profile, evidence_root=overlapping_ev
                )

            # 2. Tamper one external file after roots succeed: partial_observation retains all 3 roots
            # and all other observed files!
            tampered_helper = fx["root"] / "support" / "scripts" / "toolchain.py"  # type: ignore[operator]
            orig_bytes = tampered_helper.read_bytes()
            tampered_helper.write_bytes(orig_bytes + b"# tampered\n")
            try:
                with self.assertRaises(_ProfileObservationError) as ctx:
                    _validate_and_observe_outer_profile(profile)
                partial = ctx.exception.partial_observation
                self.assertIsInstance(partial, _PartialProfileObservation)
                self.assertIsNotNone(partial.manifest_observation)
                self.assertIsNotNone(partial.outer_manifest)
                self.assertEqual(
                    set(partial.observed_roots.keys()),
                    {"vendor", "prepared", "build"},
                )
                self.assertGreater(len(partial.observed_files), 20)
                self.assertGreaterEqual(len(partial.errors), 1)
            finally:
                tampered_helper.write_bytes(orig_bytes)

    def test_reobserve_continues_after_errors_and_resists_manifest_replacement(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = _build_synthetic_outer_profile_fixture(Path(tmp))
            profile = fx["profile"]
            assert isinstance(profile, RefmacDiagnosticProfile)
            manifest_path = fx["manifest_path"]
            assert isinstance(manifest_path, Path)
            trees = fx["trees"]
            assert isinstance(trees, dict)

            state = _validate_and_observe_outer_profile(profile)

            # Replace a file on disk AND rewrite the on-disk manifest to match the replacement,
            # plus add an extra file in prepared root. Recheck must still fail against original baseline
            # and continue collecting remaining observations.
            helper_file = fx["root"] / "support" / "scripts" / "onesar_rerun.py"  # type: ignore[operator]
            helper_file.write_text("# replaced post-baseline\n", encoding="utf-8")
            manifest_path.write_text('{"replaced": true}\n', encoding="utf-8")
            extra_prepared = trees["prepared"] / "unexpected_post_run.txt"
            extra_prepared.write_text("rogue\n", encoding="utf-8")

            recheck = _reobserve_outer_profile_state(state)
            self.assertFalse(recheck.verified)
            self.assertGreaterEqual(len(recheck.errors), 3)
            joined_errors = "\n".join(recheck.errors)
            self.assertIn("Manifest recheck failed", joined_errors)
            self.assertIn("Controlled root 'prepared' recheck failed", joined_errors)
            self.assertIn("onesar_rerun.py", joined_errors)
            # Unaffected roots and files are still re-observed and retained
            self.assertIn("vendor", recheck.observed_roots)
            self.assertIn("build", recheck.observed_roots)
            self.assertGreater(len(recheck.observed_files), 20)


class TestTask668FilesystemRegressions(unittest.TestCase):
    """Focused regressions for Task 668 (#1166, #1165, #1167, #1168, #1164, #1162)."""

    def test_1166_root_slash_ancestor_admitted_while_file_root_and_evidence_reject_slash(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = _build_synthetic_outer_profile_fixture(Path(tmp))
            profile = fx["profile"]
            assert isinstance(profile, RefmacDiagnosticProfile)
            root = fx["root"]
            assert isinstance(root, Path)
            absent_ev = root / "absent-evidence-dir" / "nested"
            staged_ev = root / "staged-evidence-dir"
            staged_ev.mkdir()

            # 1. Valid private observation succeeds with evidence_root=None, absent, and staged
            for ev_arg in (None, absent_ev, staged_ev):
                with self.subTest(evidence_root=str(ev_arg)):
                    state = _validate_and_observe_outer_profile(
                        profile, evidence_root=ev_arg
                    )
                    self.assertIn("/", state.observed_ancestors)
                    self.assertEqual(state.observed_ancestors["/"].path, "/")
                    self.assertEqual(state.observed_ancestors["/"].resolved_path, "/")
                    recheck = _reobserve_outer_profile_state(state)
                    self.assertTrue(recheck.verified)
                    self.assertIn("/", recheck.observed_ancestors)

            # 2. '/' is still rejected for file paths, controlled-root paths, and evidence_root
            with self.assertRaises(ValueError):
                _observe_regular_file_pin("/")
            with self.assertRaises(_ProfileObservationError):
                _validate_and_observe_outer_profile(profile, evidence_root="/")

            bad_root_payload = copy.deepcopy(fx["manifest_payload"])
            assert isinstance(bad_root_payload, dict)
            bad_root_payload["roots"]["vendor"]["path"] = "/"  # type: ignore[index]
            with self.assertRaises(ValueError):
                _validate_outer_manifest_shape(
                    bad_root_payload,
                    expected_profile_id=profile.profile_id,
                    expected_executable_pin=profile.executable,
                )

    def test_1165_lexical_controlled_root_membership_allows_external_alias_to_listed_member(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = _build_synthetic_outer_profile_fixture(Path(tmp))
            root = fx["root"]
            assert isinstance(root, Path)
            payload = copy.deepcopy(fx["manifest_payload"])
            assert isinstance(payload, dict)

            # Create role-backed external symlink and '..' aliases resolving to a listed controlled member
            expected_member_target = (root / "build" / "build-receipt.json").resolve(
                strict=True
            )
            self.assertTrue(expected_member_target.is_file())
            ext_link = root / "support" / "build-receipt-link.json"
            os.symlink("../build/build-receipt.json", ext_link)
            ext_dotdot = f"{root}/support/bin/../../build/build-receipt.json"
            self.assertEqual(ext_link.resolve(strict=True), expected_member_target)
            self.assertEqual(
                Path(ext_dotdot).resolve(strict=True), expected_member_target
            )

            link_obs = _observe_regular_file_pin(str(ext_link))
            dotdot_obs = _observe_regular_file_pin(ext_dotdot)
            self.assertEqual(link_obs.resolved_path, str(expected_member_target))
            self.assertEqual(dotdot_obs.resolved_path, str(expected_member_target))
            payload["files"]["ext_build_link"] = link_obs.to_manifest_row()  # type: ignore[index]
            payload["files"]["ext_build_dotdot"] = dotdot_obs.to_manifest_row()  # type: ignore[index]
            payload["roles"]["qc_evidence"] = sorted(  # type: ignore[index]
                [*payload["roles"]["qc_evidence"], "ext_build_link", "ext_build_dotdot"]  # type: ignore[index]
            )

            # roots["build"]["file_ids"] remains strictly lexical (does NOT list external aliases)
            self.assertNotIn("ext_build_link", payload["roots"]["build"]["file_ids"])  # type: ignore[index]
            self.assertNotIn("ext_build_dotdot", payload["roots"]["build"]["file_ids"])  # type: ignore[index]

            aliased_profile = _rewrite_manifest_and_profile(fx, payload)
            state = _validate_and_observe_outer_profile(aliased_profile)
            self.assertIn("ext_build_link", state.observed_files)
            self.assertIn("ext_build_dotdot", state.observed_files)
            self.assertNotIn("ext_build_link", state.outer_manifest.tree_member_ids)
            self.assertNotIn("ext_build_dotdot", state.outer_manifest.tree_member_ids)

            # Negative 1: external alias resolving inside controlled root to an UNLISTED target is rejected
            unlisted_payload = copy.deepcopy(payload)
            unlisted_payload["files"]["ext_build_link"]["resolved_path"] = (  # type: ignore[index]
                f"{root}/build/unlisted-target.json"
            )
            with self.assertRaisesRegex(
                ValueError, "resolves inside controlled root 'build' to unlisted target"
            ):
                _validate_outer_manifest_shape(
                    unlisted_payload,
                    expected_profile_id=aliased_profile.profile_id,
                    expected_executable_pin=aliased_profile.executable,
                )

            # Negative 2: external alias with conflicting target pin is rejected
            conflict_pin_payload = copy.deepcopy(payload)
            conflict_pin_payload["files"]["ext_build_link"]["sha256"] = "0" * 64  # type: ignore[index]
            with self.assertRaisesRegex(
                ValueError, "Conflicting sha256/size_bytes pins for resolved target"
            ):
                _validate_outer_manifest_shape(
                    conflict_pin_payload,
                    expected_profile_id=aliased_profile.profile_id,
                    expected_executable_pin=aliased_profile.executable,
                )

            # Negative 3: external alias with wrong declared symlink edge fails outer observation
            wrong_edge_payload = copy.deepcopy(payload)
            wrong_edge_payload["files"]["ext_build_link"]["symlinks"] = [  # type: ignore[index]
                {
                    "path": str(ext_link),
                    "target": "../build/./build-receipt.json",
                }
            ]
            wrong_edge_profile = _rewrite_manifest_and_profile(fx, wrong_edge_payload)
            with self.assertRaisesRegex(
                _ProfileObservationError, "symlink edges mismatch"
            ) as edge_ctx:
                _validate_and_observe_outer_profile(wrong_edge_profile)
            self.assertIn(
                "ext_build_link", edge_ctx.exception.partial_observation.observed_files
            )
            self.assertIn(
                "ext_build_link",
                edge_ctx.exception.partial_observation.unverified_files,
            )

    def test_1167_recursively_expanded_symlink_target_records_dotdot_traversed_directory(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = _build_synthetic_outer_profile_fixture(Path(tmp))
            root = fx["root"]
            assert isinstance(root, Path)
            alias_symlink = fx["alias_symlink"]
            assert isinstance(alias_symlink, Path)
            payload = copy.deepcopy(fx["manifest_payload"])
            assert isinstance(payload, dict)

            bridge = root / "support" / "bridge"
            bridge.mkdir()
            alias_symlink.unlink()
            # Literal symlink target uses both './' and 'bridge/..' traversal
            os.symlink("./bridge/../collection-python", alias_symlink)

            # Direct './' lexical alias to regular leaf file
            direct_dot_slash = f"{root}/support/./collection-python"

            # Component-link './' with remaining suffix (dir_link -> ./hop_dir -> ./nested_dir/inner_link -> ./collection-python)
            nested_dir = root / "support" / "nested_dir"
            nested_dir.mkdir()
            inner_link = nested_dir / "inner_link"
            os.symlink(".././collection-python", inner_link)
            hop_dir = root / "support" / "hop_dir"
            os.symlink("./nested_dir", hop_dir)
            dir_link = root / "support" / "dir_link"
            os.symlink("./hop_dir", dir_link)
            comp_link_with_suffix = f"{root}/support/./dir_link/inner_link"

            # Unusable regular_file/.. path must still be rejected and never normalized into a valid path
            unusable_file_dotdot = (
                f"{root}/support/collection-python/../collection-python"
            )
            with self.assertRaises(ValueError):
                _observe_regular_file_pin(unusable_file_dotdot)

            alias_fid = next(
                fid
                for fid, row in payload["files"].items()  # type: ignore[union-attr]
                if row["path"] == str(alias_symlink)
            )
            payload["files"][alias_fid] = _observe_regular_file_pin(  # type: ignore[index]
                str(alias_symlink)
            ).to_manifest_row()
            payload["files"]["direct_dot_slash_alias"] = _observe_regular_file_pin(  # type: ignore[index]
                direct_dot_slash
            ).to_manifest_row()
            payload["files"]["comp_link_suffix_alias"] = _observe_regular_file_pin(  # type: ignore[index]
                comp_link_with_suffix
            ).to_manifest_row()
            payload["roles"]["qc_evidence"] = sorted(  # type: ignore[index]
                [
                    *payload["roles"]["qc_evidence"],  # type: ignore[index]
                    "direct_dot_slash_alias",
                    "comp_link_suffix_alias",
                ]
            )

            bridged_profile = _rewrite_manifest_and_profile(fx, payload)
            state = _validate_and_observe_outer_profile(bridged_profile)
            self.assertIn(str(bridge), state.observed_ancestors)
            self.assertIn(str(nested_dir), state.observed_ancestors)
            self.assertIn("direct_dot_slash_alias", state.observed_files)
            self.assertEqual(
                state.observed_files["direct_dot_slash_alias"].path,
                direct_dot_slash,
            )
            self.assertIn("comp_link_suffix_alias", state.observed_files)
            self.assertEqual(
                state.observed_files["comp_link_suffix_alias"].path,
                comp_link_with_suffix,
            )
            self.assertEqual(
                state.observed_files["comp_link_suffix_alias"].symlinks,
                tuple(
                    sorted(
                        (
                            _SymlinkEdge(path=str(dir_link), target="./hop_dir"),
                            _SymlinkEdge(path=str(hop_dir), target="./nested_dir"),
                            _SymlinkEdge(
                                path=str(inner_link), target=".././collection-python"
                            ),
                        ),
                        key=lambda e: e.path,
                    )
                ),
            )

            # Replace bridge directory with a fresh directory of the same mode (different inode)
            old_mode = stat_mode = os.lstat(bridge).st_mode & 0o7777
            bridge.rename(root / "support" / "bridge-old")
            bridge.mkdir(mode=old_mode)
            os.chmod(bridge, stat_mode)

            recheck = _reobserve_outer_profile_state(state)
            self.assertFalse(recheck.verified)
            self.assertTrue(
                any(str(bridge) in err for err in recheck.errors),
                msg=f"Expected bridge ancestor mismatch in {recheck.errors}",
            )

    def test_1167_bounded_component_traversal_handles_6_and_12_nested_relative_directory_symlinks(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = _build_synthetic_outer_profile_fixture(Path(tmp))
            root = fx["root"]
            assert isinstance(root, Path)
            payload = copy.deepcopy(fx["manifest_payload"])
            assert isinstance(payload, dict)

            chain_root = root / "support" / "nested_chain"
            chain_root.mkdir()
            real_dirs: list[Path] = []
            link_paths: list[Path] = []
            expected_edges_all: list[_SymlinkEdge] = []
            cur_dir = chain_root
            bridge_hop = chain_root / "unused"

            for idx in range(1, 13):
                next_real = cur_dir / f"real_{idx}"
                next_real.mkdir()
                link_p = cur_dir / f"link_{idx}"
                if idx == 6:
                    bridge_hop = cur_dir / "bridge_hop_6"
                    bridge_hop.mkdir()
                    target_str = f"./bridge_hop_6/../real_{idx}"
                else:
                    target_str = f"real_{idx}"
                os.symlink(target_str, link_p)
                real_dirs.append(next_real)
                link_paths.append(link_p)
                expected_edges_all.append(
                    _SymlinkEdge(path=str(link_p), target=target_str)
                )
                cur_dir = next_real

            target_bytes = b'{"nested_chain_target": 12}\n'
            target_sha = _sha256_bytes(target_bytes)
            canonical_target = cur_dir / "nested-target.json"
            canonical_target.write_bytes(target_bytes)

            canonical_str = str(canonical_target)
            single_link_str = str(
                chain_root
                / "link_1"
                / Path(*[f"real_{i}" for i in range(2, 13)])
                / "nested-target.json"
            )
            six_links_str = str(
                chain_root
                / Path(*[f"link_{i}" for i in range(1, 7)])
                / Path(*[f"real_{i}" for i in range(7, 13)])
                / "nested-target.json"
            )
            twelve_links_str = str(
                chain_root
                / Path(*[f"link_{i}" for i in range(1, 13)])
                / "nested-target.json"
            )

            expected_cases = (
                ("nested_canonical_ctrl", canonical_str, ()),
                (
                    "nested_single_link_ctrl",
                    single_link_str,
                    (expected_edges_all[0],),
                ),
                (
                    "nested_six_links",
                    six_links_str,
                    tuple(sorted(expected_edges_all[:6], key=lambda e: e.path)),
                ),
                (
                    "nested_twelve_links",
                    twelve_links_str,
                    tuple(sorted(expected_edges_all[:12], key=lambda e: e.path)),
                ),
            )

            for fid, lex_path, exp_edges in expected_cases:
                with self.subTest(file_id=fid):
                    # Verify kernel path resolution and direct reading succeed
                    self.assertEqual(
                        Path(lex_path).resolve(strict=True), canonical_target
                    )
                    self.assertEqual(Path(lex_path).read_bytes(), target_bytes)

                    exact_pin = FilePin(
                        path=lex_path,
                        sha256=target_sha,
                        size_bytes=len(target_bytes),
                    )
                    obs = _observe_regular_file_pin(lex_path, expected_pin=exact_pin)
                    self.assertEqual(obs.path, lex_path)
                    self.assertEqual(obs.resolved_path, canonical_str)
                    self.assertEqual(obs.symlinks, exp_edges)

                    doc = _read_pinned_json(exact_pin)
                    self.assertEqual(doc.observation.path, lex_path)
                    self.assertEqual(doc.observation.symlinks, exp_edges)
                    self.assertEqual(doc.payload, {"nested_chain_target": 12})

                    payload["files"][fid] = obs.to_manifest_row()  # type: ignore[index]

            payload["roles"]["qc_evidence"] = sorted(  # type: ignore[index]
                [
                    *payload["roles"]["qc_evidence"],  # type: ignore[index]
                    *(fid for fid, _, _ in expected_cases),
                ]
            )

            nested_profile = _rewrite_manifest_and_profile(fx, payload)
            state = _validate_and_observe_outer_profile(nested_profile)
            self.assertIs(state.outer_files_verified, True)

            for fid, lex_path, exp_edges in expected_cases:
                self.assertIn(fid, state.observed_files)
                self.assertEqual(state.observed_files[fid].path, lex_path)
                self.assertEqual(state.observed_files[fid].resolved_path, canonical_str)
                self.assertEqual(state.observed_files[fid].symlinks, exp_edges)

            # Verify all 12 literal symlink edges and all traversed directories are recorded
            for edge in expected_edges_all:
                self.assertIn(edge.path, state.observed_symlinks)
                self.assertEqual(state.observed_symlinks[edge.path].target, edge.target)
            for rdir in (chain_root, bridge_hop, *real_dirs):
                self.assertIn(str(rdir), state.observed_ancestors)

            baseline_recheck = _reobserve_outer_profile_state(state)
            self.assertTrue(baseline_recheck.verified)
            self.assertEqual(baseline_recheck.errors, ())

            # 1. Persistent directory replacement on bridge_hop_6 is rejected on recheck
            bridge_mode = os.lstat(bridge_hop).st_mode & 0o7777
            bridge_backup = bridge_hop.parent / "bridge_hop_6_backup"
            bridge_hop.rename(bridge_backup)
            bridge_hop.mkdir(mode=bridge_mode)
            os.chmod(bridge_hop, bridge_mode)
            try:
                recheck_dir = _reobserve_outer_profile_state(state)
                self.assertFalse(recheck_dir.verified)
                self.assertTrue(
                    any(str(bridge_hop) in err for err in recheck_dir.errors),
                    msg=f"Expected {bridge_hop} mismatch in {recheck_dir.errors}",
                )
            finally:
                bridge_hop.rmdir()
                bridge_backup.rename(bridge_hop)

            self.assertTrue(_reobserve_outer_profile_state(state).verified)

            # 2. Persistent symlink replacement (same target, new inode) on link_6 is rejected on recheck
            link6 = link_paths[5]
            link6_target = os.readlink(link6)
            link6_backup = link6.parent / "link_6_backup"
            link6.rename(link6_backup)
            os.symlink(link6_target, link6)
            try:
                recheck_sym = _reobserve_outer_profile_state(state)
                self.assertFalse(recheck_sym.verified)
                self.assertTrue(
                    any(str(link6) in err for err in recheck_sym.errors),
                    msg=f"Expected {link6} symlink mismatch in {recheck_sym.errors}",
                )
            finally:
                link6.unlink()
                link6_backup.rename(link6)

            self.assertTrue(_reobserve_outer_profile_state(state).verified)

    def test_1168_retains_actual_file_and_root_observations_across_mismatches_and_interrupted_scans(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = _build_synthetic_outer_profile_fixture(Path(tmp))
            root = fx["root"]
            assert isinstance(root, Path)
            trees = fx["trees"]
            assert isinstance(trees, dict)
            alias_symlink = fx["alias_symlink"]
            assert isinstance(alias_symlink, Path)
            base_payload = fx["manifest_payload"]
            assert isinstance(base_payload, dict)
            profile = fx["profile"]
            assert isinstance(profile, RefmacDiagnosticProfile)

            alias_fid = next(
                fid
                for fid, row in base_payload["files"].items()  # type: ignore[union-attr]
                if row["path"] == str(alias_symlink)
            )

            # 1. Wrong declared symlink edge on a valid regular file retains actual file observation
            bad_edge_payload = copy.deepcopy(base_payload)
            bad_edge_payload["files"][alias_fid]["symlinks"] = [  # type: ignore[index]
                {"path": str(alias_symlink), "target": "./collection-python"}
            ]
            bad_edge_profile = _rewrite_manifest_and_profile(fx, bad_edge_payload)
            with self.assertRaises(_ProfileObservationError) as ctx:
                _validate_and_observe_outer_profile(bad_edge_profile)
            partial_edge = ctx.exception.partial_observation
            self.assertIn(alias_fid, partial_edge.observed_files)
            self.assertIn(alias_fid, partial_edge.unverified_files)
            self.assertNotIn(alias_fid, partial_edge.verified_files)
            self.assertEqual(
                partial_edge.observed_files[alias_fid].symlinks,
                (_SymlinkEdge(path=str(alias_symlink), target="collection-python"),),
            )
            # Restore valid manifest on disk
            _rewrite_manifest_and_profile(fx, base_payload)

            # 2. Complete controlled-tree scan with hidden/extra files retains root and extra file observations
            # under observed_roots["vendor"].member_observations without synthetic IDs in observed_files (#1172)
            hidden = trees["vendor"] / ".hidden-unregistered"
            ignore = trees["vendor"] / ".gitignore"
            hidden.write_text("inert hidden extra\n", encoding="utf-8")
            ignore.write_text(".hidden-unregistered\n", encoding="utf-8")
            try:
                with self.assertRaises(_ProfileObservationError) as ctx:
                    _validate_and_observe_outer_profile(profile)
                partial_extra = ctx.exception.partial_observation
                self.assertIn("vendor", partial_extra.observed_roots)
                self.assertIn("vendor", partial_extra.failed_roots)
                self.assertNotIn("vendor", partial_extra.verified_roots)
                self.assertNotIn("vendor", partial_extra.incomplete_roots)
                self.assertTrue(partial_extra.observed_roots["vendor"].scan_complete)
                self.assertFalse(partial_extra.observed_roots["vendor"].verified)
                self.assertIn(
                    ".hidden-unregistered",
                    partial_extra.observed_roots["vendor"].member_observations,
                )
                self.assertEqual(
                    partial_extra.observed_roots["vendor"]
                    .member_observations[".hidden-unregistered"]
                    .path,
                    str(hidden),
                )
                self.assertEqual(
                    set(partial_extra.observed_files.keys()),
                    set(base_payload["files"].keys()),  # type: ignore[union-attr]
                )
                self.assertIn("prepared", partial_extra.verified_roots)
                self.assertIn("build", partial_extra.verified_roots)
            finally:
                hidden.unlink()
                ignore.unlink()

            # 3. Interrupted controlled-tree scan retains incomplete root inventory with scan_complete=False
            real_walk = os.walk

            def interrupted_vendor_walk(top, topdown=True, onerror=None, followlinks=False):
                if str(top) == str(trees["vendor"]):
                    for idx, item in enumerate(
                        real_walk(
                            top,
                            topdown=topdown,
                            onerror=onerror,
                            followlinks=followlinks,
                        )
                    ):
                        if idx == 0:
                            yield item
                            if onerror is not None:
                                onerror(
                                    PermissionError(
                                        errno.EACCES,
                                        "synthetic permission denied in subdir",
                                    )
                                )
                            return
                else:
                    yield from real_walk(
                        top,
                        topdown=topdown,
                        onerror=onerror,
                        followlinks=followlinks,
                    )

            with mock.patch(
                "refmac_diagnostic_profile.os.walk",
                side_effect=interrupted_vendor_walk,
            ):
                with self.assertRaises(_ProfileObservationError) as ctx:
                    _validate_and_observe_outer_profile(profile)
                partial_inc = ctx.exception.partial_observation
                self.assertIn("vendor", partial_inc.observed_roots)
                self.assertIn("vendor", partial_inc.incomplete_roots)
                self.assertIn("vendor", partial_inc.failed_roots)
                self.assertNotIn("vendor", partial_inc.verified_roots)
                self.assertFalse(partial_inc.observed_roots["vendor"].scan_complete)
                self.assertFalse(partial_inc.observed_roots["vendor"].verified)
                self.assertGreaterEqual(
                    len(partial_inc.observed_roots["vendor"].member_pins), 1
                )
                # Later roots and files are still observed
                self.assertIn("prepared", partial_inc.verified_roots)
                self.assertIn("build", partial_inc.verified_roots)
                self.assertGreater(len(partial_inc.verified_files), 20)

            # 4. _reobserve_outer_profile_state retains completed-read hash-mismatch observations
            # when changed bytes and repinned manifest have equal byte lengths (#1171)
            state = _validate_and_observe_outer_profile(profile)
            manifest_path = fx["manifest_path"]
            assert isinstance(manifest_path, Path)
            qc_path = root / "support" / "qc-item.json"
            qc_fid = next(
                fid
                for fid, row in base_payload["files"].items()  # type: ignore[union-attr]
                if row["path"] == str(qc_path)
            )
            orig_qc_len = len(qc_path.read_bytes())
            orig_manifest_len = len(manifest_path.read_bytes())
            self.assertEqual(orig_qc_len, 3)

            qc_path.write_text("[]\n", encoding="utf-8")
            self.assertEqual(len(qc_path.read_bytes()), orig_qc_len)
            equal_len_payload = copy.deepcopy(base_payload)
            equal_len_payload["files"][qc_fid] = _observe_regular_file_pin(  # type: ignore[index]
                str(qc_path)
            ).to_manifest_row()
            _rewrite_manifest_and_profile(fx, equal_len_payload)
            self.assertEqual(len(manifest_path.read_bytes()), orig_manifest_len)

            recheck = _reobserve_outer_profile_state(state)
            self.assertFalse(recheck.verified)
            self.assertIsNotNone(recheck.manifest_observation)
            self.assertIn(qc_fid, recheck.observed_files)
            self.assertIn(qc_fid, recheck.unverified_files)
            self.assertNotIn(qc_fid, recheck.verified_files)
            self.assertEqual(
                recheck.observed_files[qc_fid].sha256,
                _sha256_bytes(b"[]\n"),
            )

            # 5. Longer file and longer manifest are rejected before read by bounded reader:
            # unavailable observations remain absent while later roots and files are still observed (#1171)
            qc_path.write_text('{"replacement": true}\n', encoding="utf-8")
            self.assertGreater(len(qc_path.read_bytes()), orig_qc_len)
            longer_payload = copy.deepcopy(base_payload)
            longer_payload["files"][qc_fid] = _observe_regular_file_pin(  # type: ignore[index]
                str(qc_path)
            ).to_manifest_row()
            _rewrite_manifest_and_profile(fx, longer_payload)
            self.assertGreater(len(manifest_path.read_bytes()), orig_manifest_len)

            recheck_longer = _reobserve_outer_profile_state(state)
            self.assertFalse(recheck_longer.verified)
            self.assertIsNone(recheck_longer.manifest_observation)
            self.assertNotIn(qc_fid, recheck_longer.observed_files)
            self.assertNotIn(qc_fid, recheck_longer.verified_files)
            self.assertNotIn(qc_fid, recheck_longer.unverified_files)
            self.assertEqual(
                set(recheck_longer.verified_roots.keys()),
                {"vendor", "prepared", "build"},
            )
            self.assertGreater(len(recheck_longer.verified_files), 20)

    def test_1172_opaque_file_id_colliding_with_unregistered_prefix_has_no_cross_map_aliasing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = _build_synthetic_outer_profile_fixture(Path(tmp))
            trees = fx["trees"]
            assert isinstance(trees, dict)
            payload = copy.deepcopy(fx["manifest_payload"])
            assert isinstance(payload, dict)

            # Rename writer_input's opaque file_id to "unregistered:build:extra.txt"
            old_writer_id = payload["roles"]["writer_input"][0]  # type: ignore[index]
            colliding_id = "unregistered:build:extra.txt"
            writer_row = payload["files"].pop(old_writer_id)  # type: ignore[union-attr]
            writer_path_str = writer_row["path"]
            payload["files"][colliding_id] = writer_row  # type: ignore[index]
            payload["roles"]["writer_input"] = [colliding_id]  # type: ignore[index]

            colliding_profile = _rewrite_manifest_and_profile(fx, payload)
            baseline_state = _validate_and_observe_outer_profile(colliding_profile)
            self.assertIn(colliding_id, baseline_state.observed_files)
            self.assertEqual(
                baseline_state.observed_files[colliding_id].path, writer_path_str
            )

            # Add extra unregistered file build/extra.txt on disk
            extra_build_file = trees["build"] / "extra.txt"
            extra_build_file.write_text("rogue build extra\n", encoding="utf-8")
            try:
                # 1. Validate path rejects extra member while keeping colliding_id bound ONLY to writer_input
                with self.assertRaises(_ProfileObservationError) as ctx:
                    _validate_and_observe_outer_profile(colliding_profile)
                partial = ctx.exception.partial_observation
                self.assertIn(colliding_id, partial.observed_files)
                self.assertIn(colliding_id, partial.verified_files)
                self.assertNotIn(colliding_id, partial.unverified_files)
                self.assertEqual(
                    partial.observed_files[colliding_id].path, writer_path_str
                )
                self.assertEqual(
                    partial.verified_files[colliding_id].path, writer_path_str
                )
                self.assertTrue(
                    set(partial.verified_files.keys()).isdisjoint(
                        set(partial.unverified_files.keys())
                    )
                )
                self.assertIn("build", partial.failed_roots)
                self.assertIn(
                    "extra.txt",
                    partial.observed_roots["build"].member_observations,
                )
                self.assertEqual(
                    partial.observed_roots["build"]
                    .member_observations["extra.txt"]
                    .path,
                    str(extra_build_file),
                )

                # 2. Recheck path also rejects extra member with no cross-map ID aliasing
                recheck = _reobserve_outer_profile_state(baseline_state)
                self.assertFalse(recheck.verified)
                self.assertIn(colliding_id, recheck.observed_files)
                self.assertIn(colliding_id, recheck.verified_files)
                self.assertNotIn(colliding_id, recheck.unverified_files)
                self.assertEqual(
                    recheck.observed_files[colliding_id].path, writer_path_str
                )
                self.assertEqual(
                    recheck.verified_files[colliding_id].path, writer_path_str
                )
                self.assertTrue(
                    set(recheck.verified_files.keys()).isdisjoint(
                        set(recheck.unverified_files.keys())
                    )
                )
                self.assertIn("build", recheck.failed_roots)
                self.assertIn(
                    "extra.txt",
                    recheck.observed_roots["build"].member_observations,
                )
                self.assertEqual(
                    recheck.observed_roots["build"]
                    .member_observations["extra.txt"]
                    .path,
                    str(extra_build_file),
                )
            finally:
                extra_build_file.unlink()

    def test_1164_deep_frozen_manifest_payload_with_tuple_expected_absent_is_accepted(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = _build_synthetic_outer_profile_fixture(Path(tmp))
            profile = fx["profile"]
            assert isinstance(profile, RefmacDiagnosticProfile)
            manifest_payload = fx["manifest_payload"]
            assert isinstance(manifest_payload, dict)

            frozen_payload = profile_mod._deep_freeze_json_value(manifest_payload)
            self.assertIsInstance(
                frozen_payload["runtime_environment"]["expected_absent"], tuple
            )
            checked = _validate_outer_manifest_shape(
                frozen_payload,
                expected_profile_id=profile.profile_id,
                expected_executable_pin=profile.executable,
            )
            self.assertEqual(
                checked.runtime_environment.expected_absent,
                EXPECTED_RUNTIME_ABSENT_KEYS,
            )


if __name__ == "__main__":
    unittest.main()
