#!/usr/bin/env python3
"""Focused synthetic unit tests for scripts/refmac_diagnostic_profile.py (Tasks 653, 657, 663, 658, 668, 673, 677, 681, 685, 661, 734, 739, 742, 744, 749, 751, 737, and 851)."""

from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError
import errno
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from typing import Any
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
    FileObservation,
    FilePin,
    LookupStatObservation,
    PartialFileReadObservation,
    PreOpenLookupSnapshot,
    ProfileValidationError,
    RefmacDiagnosticProfile,
    RootObservation,
    ValidatedProfile,
    _CheckedOuterManifest,
    _CheckedOuterProfileState,
    _FrozenPairTable,
    _ObservedRegularFilePin,
    _OuterProfileRecheckResult,
    _PartialFileReadError,
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
    recheck_profile,
    reject_conflicting_environment,
    validate_profile,
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class TestPublicDataclassesAndSliceBoundary(unittest.TestCase):
    """Verify frozen FilePin, RefmacDiagnosticProfile, and public entrypoints (validate_profile and recheck_profile)."""

    def test_validate_and_recheck_stubs_are_deliberately_absent(self) -> None:
        self.assertTrue(hasattr(profile_mod, "validate_profile"))
        self.assertTrue(callable(profile_mod.validate_profile))
        self.assertTrue(hasattr(profile_mod, "recheck_profile"))
        self.assertTrue(callable(profile_mod.recheck_profile))

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

    add_single_role(
        "ccp4_setup",
        "installed/bin/ccp4.setup-sh",
    )
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
    ccp4_env = dict(env_values)
    installed_prefix = str(root / "installed")
    ccp4_setup_row = files[roles["ccp4_setup"][0]]
    inst_ref_row = files[roles["installed_reference"][0]]
    installed_record: dict[str, object] = {
        "configured_installation_prefix": installed_prefix,
        "setup_script": {
            "configured_path": str(ccp4_setup_row["path"]),
            "resolved_path": str(ccp4_setup_row["resolved_path"]),
            "is_symlink": bool(
                ccp4_setup_row["path"] != ccp4_setup_row["resolved_path"]
            ),
            "within_prefix": True,
            "sha256": str(ccp4_setup_row["sha256"]),
            "size_bytes": int(ccp4_setup_row["size_bytes"]),  # type: ignore[arg-type]
        },
        "refmac5_binary": {
            "discovered_path": str(inst_ref_row["path"]),
            "resolved_path": str(inst_ref_row["resolved_path"]),
            "is_symlink": bool(
                inst_ref_row["path"] != inst_ref_row["resolved_path"]
            ),
            "within_prefix": True,
            "executable": True,
            "sha256": str(inst_ref_row["sha256"]),
            "size_bytes": int(inst_ref_row["size_bytes"]),  # type: ignore[arg-type]
        },
        "bound_ccp4_configuration": {
            k: env_values[k]
            for k in (
                "CBIN",
                "CCP4",
                "CCP4_MASTER",
                "CCP4_SCR",
                "CINCL",
                "CLIB",
                "CLIBD",
                "CLIBD_MON",
            )
        },
    }

    # Populate self-consistent inner receipts (source_manifest, runtime_observation, build_receipt, source_audit)
    sm_path = trees["prepared"] / "refmac_diagnostic_source_manifest.json"
    sm_payload: dict[str, object] = {
        "schema_id": "protstruct_refmac_diagnostic_source_manifest_v1",
        "source_verification_status": "verified_upstream_commit_tree",
        "upstream_source": {
            "expected_commit": UPSTREAM_COMMIT,
            "expected_tag": UPSTREAM_TAG,
            "git_commit": UPSTREAM_COMMIT,
            "git_tag": UPSTREAM_TAG,
        },
        "extra_opaque_metadata": {"synthetic": True},
    }
    sm_path.write_text(json.dumps(sm_payload, indent=2) + "\n", encoding="utf-8")
    register_path(sm_path)

    rt_path = root / "support" / "runtime-observation.json"
    rt_observer_row = files[roles["runtime_observer"][0]]
    setup_dep_rows = [files[fid] for fid in roles["ccp4_setup_dependencies"]]
    rt_img_rows = [files[fid] for fid in roles["runtime_images"]]
    rt_payload: dict[str, object] = {
        "contract": "primary_ccp4_runtime_configuration_observation_v1",
        "selected_nonsecret_environment": dict(env_values),
        "resolver_record": copy.deepcopy(installed_record),
        "observation_script": {
            "path": rt_observer_row["path"],
            "resolved": rt_observer_row["resolved_path"],
            "sha256": rt_observer_row["sha256"],
            "size_bytes": rt_observer_row["size_bytes"],
        },
        "setup_source_files": [
            {
                "path": r["path"],
                "resolved": r["resolved_path"],
                "sha256": r["sha256"],
                "size_bytes": r["size_bytes"],
            }
            for r in [ccp4_setup_row, *setup_dep_rows]
        ],
        "static_library_load_commands": [
            {
                "index": idx,
                "library": {
                    "path": r["path"],
                    "resolved": r["resolved_path"],
                    "sha256": r["sha256"],
                    "size_bytes": r["size_bytes"],
                },
            }
            for idx, r in enumerate(rt_img_rows)
        ],
    }
    rt_path.write_text(json.dumps(rt_payload, indent=2) + "\n", encoding="utf-8")
    register_path(rt_path)

    br_path = trees["build"] / "build-receipt.json"
    diag_row = files[roles["diagnostic_executable"][0]]
    driver_row = files[roles["build_driver"][0]]
    journal_row = files[roles["build_journal"][0]]
    rt_cfg_row = files[roles["build_runtime_config"][0]]
    linked_row = files[roles["linked_executable"][0]]
    br_payload: dict[str, object] = {
        "contract": "protstruct_instrumented_build_receipt_v2",
        "passed": True,
        "source": str(trees["prepared"]),
        "output": str(trees["build"]),
        "executable": {
            "path": diag_row["path"],
            "sha256": diag_row["sha256"],
            "size_bytes": diag_row["size_bytes"],
        },
        "driver_sha256": driver_row["sha256"],
        "journal_sha256": journal_row["sha256"],
        "runtime_config_sha256": rt_cfg_row["sha256"],
        "linked_executable_sha256": linked_row["sha256"],
    }
    br_path.write_text(json.dumps(br_payload, indent=2) + "\n", encoding="utf-8")
    register_path(br_path)

    sa_path = root / "support" / "source-audit.json"
    sm_row = files[roles["source_manifest"][0]]
    auditor_row = files[roles["source_auditor"][0]]
    audit_interp_row = files[roles["source_audit_interpreter"][0]]
    patch_obs = _observe_regular_file_pin(
        str(trees["prepared"] / "refmac_diagnostic_hooks.patch")
    )
    vendor_inv: dict[str, dict[str, object]] = {}
    prepared_inv: dict[str, dict[str, object]] = {}
    for _fid, frow in sorted(files.items()):
        fpath = Path(str(frow["path"]))
        if fpath.is_relative_to(trees["vendor"]):
            rel_p = fpath.relative_to(trees["vendor"]).as_posix()
            vendor_inv[rel_p] = {
                "sha256": frow["sha256"],
                "size_bytes": frow["size_bytes"],
                "git_mode": "100644",
            }
        elif fpath.is_relative_to(trees["prepared"]):
            rel_p = fpath.relative_to(trees["prepared"]).as_posix()
            prepared_inv[rel_p] = {
                "sha256": frow["sha256"],
                "size_bytes": frow["size_bytes"],
            }
    sa_payload: dict[str, object] = {
        "contract": "primary_refmac_source_audit_v1",
        "passed": True,
        "source_root": str(trees["vendor"]),
        "prepared_root": str(trees["prepared"]),
        "upstream_commit": UPSTREAM_COMMIT,
        "python_optimization": 0,
        "literal_git_objects": True,
        "manifest_sha256": sm_row["sha256"],
        "auditor_sha256": auditor_row["sha256"],
        "auditor_path": auditor_row["path"],
        "patch_sha256": patch_obs.sha256,
        "interpreter": {
            "path": audit_interp_row["path"],
            "resolved_path": audit_interp_row["resolved_path"],
            "sha256": audit_interp_row["sha256"],
            "size_bytes": audit_interp_row["size_bytes"],
        },
        "original_git_blob_inventory": vendor_inv,
        "complete_prepared_inventory": prepared_inv,
    }
    sa_path.write_text(json.dumps(sa_payload, indent=2) + "\n", encoding="utf-8")
    register_path(sa_path)

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
    evidence_root = root / "evidence-output"
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
        "installed_record": installed_record,
        "ccp4_env": ccp4_env,
        "evidence_root": evidence_root,
        "source_manifest_payload": sm_payload,
        "source_audit_payload": sa_payload,
        "build_receipt_payload": br_payload,
        "runtime_observation_payload": rt_payload,
    }


def _rewrite_manifest_and_profile(
    fixture: dict[str, object],
    payload: dict[str, object],
    *,
    executable_pin: FilePin | None = None,
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
        executable=(
            executable_pin if executable_pin is not None else orig_profile.executable
        ),
    )


def _mutate_inner_receipt_and_repin(
    fixture: dict[str, object],
    role_name: str,
    mutator,
    *,
    sync_source_audit_manifest_sha: bool = True,
) -> tuple[RefmacDiagnosticProfile, callable]:
    """Mutate an inner receipt JSON on disk, update its outer file pin and caller manifest pin, and return a restore hook."""
    base_payload = fixture["manifest_payload"]
    assert isinstance(base_payload, dict)
    payload = copy.deepcopy(base_payload)
    role_fid = payload["roles"][role_name][0]  # type: ignore[index]
    role_path = Path(str(payload["files"][role_fid]["path"]))  # type: ignore[index]
    orig_role_bytes = role_path.read_bytes()

    sa_fid = payload["roles"]["source_audit"][0]  # type: ignore[index]
    sa_path = Path(str(payload["files"][sa_fid]["path"]))  # type: ignore[index]
    orig_sa_bytes = sa_path.read_bytes()

    inner_obj = json.loads(orig_role_bytes.decode("utf-8"))
    mutator(inner_obj)
    role_path.write_text(json.dumps(inner_obj, indent=2) + "\n", encoding="utf-8")
    new_role_obs = _observe_regular_file_pin(str(role_path))
    payload["files"][role_fid] = new_role_obs.to_manifest_row()  # type: ignore[index]

    if role_name == "source_manifest" and sync_source_audit_manifest_sha:
        sa_obj = json.loads(orig_sa_bytes.decode("utf-8"))
        sa_obj["manifest_sha256"] = new_role_obs.sha256
        sa_obj["complete_prepared_inventory"][
            "refmac_diagnostic_source_manifest.json"
        ] = {
            "sha256": new_role_obs.sha256,
            "size_bytes": new_role_obs.size_bytes,
        }
        sa_path.write_text(json.dumps(sa_obj, indent=2) + "\n", encoding="utf-8")
        payload["files"][sa_fid] = _observe_regular_file_pin(  # type: ignore[index]
            str(sa_path)
        ).to_manifest_row()

    new_profile = _rewrite_manifest_and_profile(fixture, payload)

    def restore() -> None:
        role_path.write_bytes(orig_role_bytes)
        sa_path.write_bytes(orig_sa_bytes)
        _rewrite_manifest_and_profile(fixture, base_payload)

    return new_profile, restore


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


class TestValidateProfileAndInnerReceiptJoins(unittest.TestCase):
    """Focused synthetic tests for Task 661 public validate_profile and scoped inner receipt joins."""

    def test_valid_profile_admission_concrete_observations_detached_provenance_and_immutability(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = _build_synthetic_outer_profile_fixture(Path(tmp))
            profile = fx["profile"]
            assert isinstance(profile, RefmacDiagnosticProfile)
            installed_record = copy.deepcopy(fx["installed_record"])
            assert isinstance(installed_record, dict)
            installed_record["extra_caller_metadata"] = {"note": "retained"}
            ccp4_env = copy.deepcopy(fx["ccp4_env"])
            assert isinstance(ccp4_env, dict)
            absent_ev = fx["root"] / "absent-run-dir"  # type: ignore[operator]
            staged_ev = fx["root"] / "staged-run-dir"  # type: ignore[operator]
            staged_ev.mkdir()

            for ev_root in (absent_ev, staged_ev):
                with self.subTest(evidence_root=str(ev_root)):
                    validated = validate_profile(
                        profile,
                        installed_record,
                        ccp4_env,
                        ev_root,
                        chunk_size=128,
                    )
                    self.assertIsInstance(validated, ValidatedProfile)
                    self.assertEqual(validated.profile_id, SUPPORTED_PROFILE_ID)
                    self.assertEqual(validated.subject_id, PROFILE_SUBJECT_ID)
                    self.assertTrue(validated.profile_files_verified)
                    self.assertEqual(
                        validated.runtime_image_coverage, "not_assessed"
                    )
                    self.assertEqual(
                        validated.selected_executable, profile.executable
                    )
                    self.assertNotEqual(
                        validated.selected_executable,
                        validated.installed_reference,
                    )
                    self.assertEqual(validated.evidence_root, str(ev_root))

                    # Concrete FileObservation checks on manifest_identity and files
                    self.assertIsInstance(
                        validated.manifest_identity, FileObservation
                    )
                    self.assertGreaterEqual(
                        len(validated.manifest_identity.ancestors), 1
                    )
                    self.assertEqual(
                        validated.manifest_identity.as_file_pin(),
                        profile.manifest,
                    )

                    files_map = dict(validated.files)
                    self.assertGreater(len(files_map), 30)
                    for fid, fobs in validated.files:
                        self.assertIsInstance(fobs, FileObservation)
                        self.assertEqual(validated.files[fid], fobs)
                        self.assertGreaterEqual(len(fobs.ancestors), 1)
                        fdict = fobs.to_dict()
                        for req_key in (
                            "path",
                            "resolved_path",
                            "sha256",
                            "size_bytes",
                            "dev",
                            "ino",
                            "mode",
                            "uid",
                            "gid",
                            "symlinks",
                            "symlink_identities",
                            "ancestors",
                        ):
                            self.assertIn(req_key, fdict)

                    # Verify external symlink alias has populated symlink_identities
                    alias_symlink_str = str(fx["alias_symlink"])
                    alias_fobs = next(
                        fobs
                        for _fid, fobs in validated.files
                        if fobs.path == alias_symlink_str
                    )
                    self.assertEqual(len(alias_fobs.symlinks), 1)
                    self.assertEqual(len(alias_fobs.symlink_identities), 1)
                    self.assertEqual(
                        alias_fobs.symlink_identities[0].path, alias_symlink_str
                    )
                    self.assertEqual(
                        alias_fobs.symlink_identities[0].target,
                        "collection-python",
                    )

                    # Concrete RootObservation checks on vendor, prepared, build
                    roots_map = dict(validated.roots)
                    self.assertEqual(
                        set(roots_map.keys()), {"vendor", "prepared", "build"}
                    )
                    for rname, robs in validated.roots:
                        self.assertIsInstance(robs, RootObservation)
                        self.assertEqual(validated.roots[rname], robs)
                        self.assertEqual(robs.name, rname)
                        self.assertGreaterEqual(len(robs.ancestors), 1)
                        self.assertGreaterEqual(len(robs.members), 1)
                        rdict = robs.to_dict()
                        for req_key in (
                            "name",
                            "path",
                            "resolved_path",
                            "dev",
                            "ino",
                            "mode",
                            "uid",
                            "gid",
                            "ancestors",
                            "members",
                        ):
                            self.assertIn(req_key, rdict)
                        for m in robs.members:
                            rel_p, m_fid = m
                            self.assertEqual(m.relative_path, rel_p)
                            self.assertEqual(m.file_id, m_fid)
                            self.assertEqual(m["relative_path"], rel_p)
                            self.assertEqual(m["file_id"], m_fid)
                            self.assertIn(m_fid, files_map)

                    # Caller mutations after validate_profile do not mutate ValidatedProfile
                    caller_inst_copy = copy.deepcopy(installed_record)
                    caller_env_copy = copy.deepcopy(ccp4_env)
                    val2 = validate_profile(
                        profile, caller_inst_copy, caller_env_copy, ev_root
                    )
                    caller_inst_copy["configured_installation_prefix"] = "/mutated"
                    caller_inst_copy["setup_script"]["sha256"] = "0" * 64  # type: ignore[index]
                    caller_env_copy["CBIN"] = "mutated"

                    prov1 = val2.to_provenance()
                    self.assertTrue(prov1["profile_files_verified"])
                    self.assertEqual(
                        prov1["runtime_image_coverage"], "not_assessed"
                    )
                    self.assertEqual(
                        prov1["selected_executable"],
                        profile.executable.to_dict(),
                    )
                    self.assertEqual(
                        prov1["installed_record"][
                            "configured_installation_prefix"
                        ],
                        installed_record["configured_installation_prefix"],
                    )
                    self.assertEqual(
                        prov1["installed_record"]["extra_caller_metadata"],
                        {"note": "retained"},
                    )
                    self.assertEqual(
                        prov1["expected_environment"]["CBIN"], "val-CBIN"
                    )

                    # Mutating prov1 does not affect subsequent to_provenance() calls
                    prov1["files"].clear()
                    prov1["roots"].clear()
                    prov1["installed_record"]["setup_script"]["sha256"] = "bad"
                    prov2 = val2.to_provenance()
                    self.assertEqual(len(prov2["files"]), len(files_map))
                    self.assertEqual(len(prov2["roots"]), 3)
                    self.assertEqual(
                        prov2["installed_record"]["setup_script"]["sha256"],
                        installed_record["setup_script"]["sha256"],  # type: ignore[index]
                    )

                    # Deep immutability of ValidatedProfile
                    with self.assertRaises(FrozenInstanceError):
                        validated.evidence_root = "/other"  # type: ignore[misc]
                    with self.assertRaises(TypeError):
                        validated.files["new"] = validated.manifest_identity  # type: ignore[index]
                    with self.assertRaises(TypeError):
                        validated.roots["vendor"] = validated.roots["build"]  # type: ignore[index]
                    with self.assertRaises(TypeError):
                        validated.roles["source_manifest"] = ()  # type: ignore[index]
                    with self.assertRaises(TypeError):
                        validated.expected_environment["CBIN"] = "x"  # type: ignore[index]

    def test_source_manifest_join_rejects_semantic_mismatches_with_repinned_outer_manifest(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = _build_synthetic_outer_profile_fixture(Path(tmp))
            installed_record = fx["installed_record"]
            assert isinstance(installed_record, dict)
            ccp4_env = fx["ccp4_env"]
            assert isinstance(ccp4_env, dict)
            ev_root = fx["evidence_root"]
            assert isinstance(ev_root, Path)

            cases = (
                (
                    "schema_id",
                    lambda d: d.update({"schema_id": "wrong_schema"}),
                ),
                (
                    "source_verification_status",
                    lambda d: d.update(
                        {"source_verification_status": "unverified"}
                    ),
                ),
                (
                    "expected_commit",
                    lambda d: d["upstream_source"].update(
                        {"expected_commit": "0" * 40}
                    ),
                ),
                (
                    "expected_tag",
                    lambda d: d["upstream_source"].update(
                        {"expected_tag": "5.8.9999"}
                    ),
                ),
                (
                    "git_commit",
                    lambda d: d["upstream_source"].update(
                        {"git_commit": "1" * 40}
                    ),
                ),
                (
                    "git_tag",
                    lambda d: d["upstream_source"].update(
                        {"git_tag": "5.8.0000"}
                    ),
                ),
            )
            for pattern, mutator in cases:
                with self.subTest(pattern=pattern):
                    bad_prof, restore = _mutate_inner_receipt_and_repin(
                        fx, "source_manifest", mutator
                    )
                    try:
                        with self.assertRaisesRegex(
                            ProfileValidationError, pattern
                        ) as ctx:
                            validate_profile(
                                bad_prof, installed_record, ccp4_env, ev_root
                            )
                        err = ctx.exception
                        self.assertEqual(
                            err.failed_check, "source_manifest_join"
                        )
                        self.assertIsNone(err.selected_executable)
                        self.assertIsNotNone(err.manifest_identity)
                        self.assertGreater(len(err.files), 30)
                        self.assertEqual(len(err.roots), 3)
                        err_prov = err.to_provenance()
                        self.assertFalse(err_prov["profile_files_verified"])
                        self.assertIsNone(err_prov["selected_executable"])
                        self.assertEqual(
                            err_prov["failed_check"], "source_manifest_join"
                        )
                    finally:
                        restore()

    def test_source_audit_join_rejects_semantic_and_strict_type_mismatches(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = _build_synthetic_outer_profile_fixture(Path(tmp))
            installed_record = fx["installed_record"]
            assert isinstance(installed_record, dict)
            ccp4_env = fx["ccp4_env"]
            assert isinstance(ccp4_env, dict)
            ev_root = fx["evidence_root"]
            assert isinstance(ev_root, Path)

            cases = (
                (
                    "source_audit.contract",
                    lambda d: d.update({"contract": "wrong_contract"}),
                ),
                (
                    "source_audit.passed",
                    lambda d: d.update({"passed": False}),
                ),
                (
                    "source_audit.passed",
                    lambda d: d.update({"passed": 1}),
                ),
                (
                    "source_audit.python_optimization",
                    lambda d: d.update({"python_optimization": False}),
                ),
                (
                    "source_audit.python_optimization",
                    lambda d: d.update({"python_optimization": 1}),
                ),
                (
                    "source_audit.literal_git_objects",
                    lambda d: d.update({"literal_git_objects": 1}),
                ),
                (
                    "source_audit.literal_git_objects",
                    lambda d: d.update({"literal_git_objects": False}),
                ),
                (
                    "source_audit.source_root",
                    lambda d: d.update({"source_root": "/wrong/vendor"}),
                ),
                (
                    "source_audit.prepared_root",
                    lambda d: d.update({"prepared_root": "/wrong/prepared"}),
                ),
                (
                    "source_audit.upstream_commit",
                    lambda d: d.update({"upstream_commit": "0" * 40}),
                ),
                (
                    "source_audit.manifest_sha256",
                    lambda d: d.update({"manifest_sha256": "a" * 64}),
                ),
                (
                    "source_audit.auditor_sha256",
                    lambda d: d.update({"auditor_sha256": "b" * 64}),
                ),
                (
                    "source_audit.auditor_path",
                    lambda d: d.update({"auditor_path": "/wrong/auditor.py"}),
                ),
                (
                    "source_audit.patch_sha256",
                    lambda d: d.update({"patch_sha256": "c" * 64}),
                ),
                (
                    "source_audit.interpreter",
                    lambda d: d["interpreter"].update({"sha256": "d" * 64}),
                ),
                (
                    "source_audit.interpreter.resolved contradicts",
                    lambda d: d["interpreter"].update(
                        {"resolved": "/contradictory/python"}
                    ),
                ),
                (
                    "source_audit.interpreter.size_bytes",
                    lambda d: d["interpreter"].update({"size_bytes": True}),
                ),
                (
                    "original_git_blob_inventory keys mismatch",
                    lambda d: d["original_git_blob_inventory"].pop("source.f"),
                ),
                (
                    "original_git_blob_inventory\\['source.f'\\] pin mismatch",
                    lambda d: d["original_git_blob_inventory"][
                        "source.f"
                    ].update({"sha256": "e" * 64}),
                ),
                (
                    "original_git_blob_inventory\\['source.f'\\].size_bytes",
                    lambda d: d["original_git_blob_inventory"][
                        "source.f"
                    ].update({"size_bytes": True}),
                ),
                (
                    "complete_prepared_inventory keys mismatch",
                    lambda d: d["complete_prepared_inventory"].update(
                        {
                            "extra.f": {
                                "sha256": "f" * 64,
                                "size_bytes": 1,
                            }
                        }
                    ),
                ),
                (
                    "complete_prepared_inventory\\['source.f'\\] pin mismatch",
                    lambda d: d["complete_prepared_inventory"][
                        "source.f"
                    ].update({"size_bytes": 999999}),
                ),
            )
            for pattern, mutator in cases:
                with self.subTest(pattern=pattern):
                    bad_prof, restore = _mutate_inner_receipt_and_repin(
                        fx, "source_audit", mutator
                    )
                    try:
                        with self.assertRaisesRegex(
                            ProfileValidationError, pattern
                        ) as ctx:
                            validate_profile(
                                bad_prof, installed_record, ccp4_env, ev_root
                            )
                        self.assertEqual(
                            ctx.exception.failed_check, "source_audit_join"
                        )
                    finally:
                        restore()

    def test_build_receipt_join_and_pair_role_ordering_reject_mismatches(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = _build_synthetic_outer_profile_fixture(Path(tmp))
            installed_record = fx["installed_record"]
            assert isinstance(installed_record, dict)
            ccp4_env = fx["ccp4_env"]
            assert isinstance(ccp4_env, dict)
            ev_root = fx["evidence_root"]
            assert isinstance(ev_root, Path)
            base_payload = fx["manifest_payload"]
            assert isinstance(base_payload, dict)

            cases = (
                (
                    "build_receipt.contract",
                    lambda d: d.update({"contract": "wrong"}),
                ),
                (
                    "build_receipt.passed",
                    lambda d: d.update({"passed": False}),
                ),
                (
                    "build_receipt.passed",
                    lambda d: d.update({"passed": 1}),
                ),
                (
                    "build_receipt.source",
                    lambda d: d.update({"source": "/wrong/prepared"}),
                ),
                (
                    "build_receipt.output",
                    lambda d: d.update({"output": "/wrong/build"}),
                ),
                (
                    "build_receipt.executable",
                    lambda d: d["executable"].update({"sha256": "0" * 64}),
                ),
                (
                    "build_receipt.executable.size_bytes",
                    lambda d: d["executable"].update({"size_bytes": True}),
                ),
                (
                    "build_receipt.driver_sha256",
                    lambda d: d.update({"driver_sha256": "1" * 64}),
                ),
                (
                    "build_receipt.journal_sha256",
                    lambda d: d.update({"journal_sha256": "2" * 64}),
                ),
                (
                    "build_receipt.runtime_config_sha256",
                    lambda d: d.update({"runtime_config_sha256": "3" * 64}),
                ),
                (
                    "build_receipt.linked_executable_sha256",
                    lambda d: d.update({"linked_executable_sha256": "4" * 64}),
                ),
            )
            for pattern, mutator in cases:
                with self.subTest(pattern=pattern):
                    bad_prof, restore = _mutate_inner_receipt_and_repin(
                        fx, "build_receipt", mutator
                    )
                    try:
                        with self.assertRaisesRegex(
                            ProfileValidationError, pattern
                        ) as ctx:
                            validate_profile(
                                bad_prof, installed_record, ccp4_env, ev_root
                            )
                        self.assertEqual(
                            ctx.exception.failed_check, "build_receipt_join"
                        )
                    finally:
                        restore()

            # Pair role reversal [copy_id, orig_id] on build_driver, build_journal, build_runtime_config, build_inventories
            for pair_role in (
                "build_driver",
                "build_journal",
                "build_runtime_config",
            ):
                with self.subTest(reversed_pair_role=pair_role):
                    rev_payload = copy.deepcopy(base_payload)
                    rev_payload["roles"][pair_role] = list(  # type: ignore[index]
                        reversed(rev_payload["roles"][pair_role])  # type: ignore[index]
                    )
                    rev_prof = _rewrite_manifest_and_profile(fx, rev_payload)
                    try:
                        with self.assertRaisesRegex(
                            ProfileValidationError, pair_role
                        ) as ctx:
                            validate_profile(
                                rev_prof, installed_record, ccp4_env, ev_root
                            )
                        self.assertIsNone(ctx.exception.selected_executable)
                    finally:
                        _rewrite_manifest_and_profile(fx, base_payload)

            rev_inv_payload = copy.deepcopy(base_payload)
            inv_ids = list(rev_inv_payload["roles"]["build_inventories"])  # type: ignore[index]
            inv_ids[0], inv_ids[1] = inv_ids[1], inv_ids[0]
            rev_inv_payload["roles"]["build_inventories"] = inv_ids  # type: ignore[index]
            rev_inv_prof = _rewrite_manifest_and_profile(fx, rev_inv_payload)
            try:
                with self.assertRaisesRegex(
                    ProfileValidationError, "build_inventories"
                ):
                    validate_profile(
                        rev_inv_prof, installed_record, ccp4_env, ev_root
                    )
            finally:
                _rewrite_manifest_and_profile(fx, base_payload)

    def test_runtime_observation_join_installed_record_and_ccp4_env_reject_mismatches(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = _build_synthetic_outer_profile_fixture(Path(tmp))
            profile = fx["profile"]
            assert isinstance(profile, RefmacDiagnosticProfile)
            installed_record = fx["installed_record"]
            assert isinstance(installed_record, dict)
            ccp4_env = fx["ccp4_env"]
            assert isinstance(ccp4_env, dict)
            ev_root = fx["evidence_root"]
            assert isinstance(ev_root, Path)

            rt_cases = (
                (
                    "runtime_observation.contract",
                    lambda d: d.update({"contract": "wrong"}),
                ),
                (
                    "selected_nonsecret_environment keys mismatch",
                    lambda d: d["selected_nonsecret_environment"].pop("CBIN"),
                ),
                (
                    "selected_nonsecret_environment\\['CBIN'\\] mismatch",
                    lambda d: d["selected_nonsecret_environment"].update(
                        {"CBIN": "wrong"}
                    ),
                ),
                (
                    "resolver_record projection does not match",
                    lambda d: d["resolver_record"]["setup_script"].update(
                        {"sha256": "0" * 64}
                    ),
                ),
                (
                    "resolver_record.setup_script.is_symlink must be a strict bool",
                    lambda d: d["resolver_record"]["setup_script"].update(
                        {"is_symlink": 0}
                    ),
                ),
                (
                    "resolver_record.refmac5_binary.executable must be strict bool True",
                    lambda d: d["resolver_record"]["refmac5_binary"].update(
                        {"executable": 1}
                    ),
                ),
                (
                    "observation_script does not match",
                    lambda d: d["observation_script"].update(
                        {"sha256": "1" * 64}
                    ),
                ),
                (
                    "observation_script.resolved_path contradicts",
                    lambda d: d["observation_script"].update(
                        {"resolved_path": "/contradictory/observer.py"}
                    ),
                ),
                (
                    "setup_source_files does not include roles\\['ccp4_setup'\\]",
                    lambda d: d.update(
                        {"setup_source_files": d["setup_source_files"][1:]}
                    ),
                ),
                (
                    "setup_source_files unique IDs minus ccp4_setup",
                    lambda d: d.update(
                        {"setup_source_files": d["setup_source_files"][:1]}
                    ),
                ),
                (
                    "static_library_load_commands\\[0\\].library pin mismatch",
                    lambda d: d["static_library_load_commands"][0][
                        "library"
                    ].update({"sha256": "2" * 64}),
                ),
            )
            for pattern, mutator in rt_cases:
                with self.subTest(pattern=pattern):
                    bad_prof, restore = _mutate_inner_receipt_and_repin(
                        fx, "runtime_observation", mutator
                    )
                    try:
                        with self.assertRaisesRegex(
                            ProfileValidationError, pattern
                        ) as ctx:
                            validate_profile(
                                bad_prof, installed_record, ccp4_env, ev_root
                            )
                        self.assertEqual(
                            ctx.exception.failed_check,
                            "runtime_observation_join",
                        )
                    finally:
                        restore()

            # Supplied installed_record disagreements
            bad_inst = copy.deepcopy(installed_record)
            bad_inst["refmac5_binary"]["sha256"] = "9" * 64  # type: ignore[index]
            with self.assertRaisesRegex(
                ProfileValidationError,
                "resolver_record projection does not match supplied installed_record",
            ) as ctx:
                validate_profile(profile, bad_inst, ccp4_env, ev_root)
            self.assertEqual(
                ctx.exception.failed_check, "runtime_observation_join"
            )

            bad_inst_bool = copy.deepcopy(installed_record)
            bad_inst_bool["setup_script"]["within_prefix"] = 1  # type: ignore[index]
            with self.assertRaisesRegex(
                ProfileValidationError, "within_prefix must be strict bool True"
            ) as ctx:
                validate_profile(profile, bad_inst_bool, ccp4_env, ev_root)
            self.assertEqual(ctx.exception.failed_check, "installed_record")

            # Supplied ccp4_env disagreements and forbidden variables
            for env_label, bad_env, pattern in (
                (
                    "forbidden_dyld",
                    {**ccp4_env, "DYLD_INSERT_LIBRARIES": "foo.dylib"},
                    "Conflicting environment variable",
                ),
                (
                    "expected_absent_ld",
                    {**ccp4_env, "LD_LIBRARY_PATH": "/tmp"},
                    "Conflicting environment variable",
                ),
                (
                    "missing_key",
                    {k: v for k, v in ccp4_env.items() if k != "CLIBD"},
                    "missing required variable 'CLIBD'",
                ),
                (
                    "wrong_value",
                    {**ccp4_env, "CLIBD": "wrong-clibd"},
                    "ccp4_env\\['CLIBD'\\] mismatch",
                ),
            ):
                with self.subTest(env_case=env_label):
                    with self.assertRaisesRegex(
                        ProfileValidationError, pattern
                    ) as ctx:
                        validate_profile(
                            profile, installed_record, bad_env, ev_root
                        )
                    self.assertEqual(ctx.exception.failed_check, "ccp4_env")
                    self.assertIsNotNone(ctx.exception.manifest_identity)
                    self.assertGreater(len(ctx.exception.files), 30)

    def test_partial_observation_retention_on_outer_and_pin_failures(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = _build_synthetic_outer_profile_fixture(Path(tmp))
            profile = fx["profile"]
            assert isinstance(profile, RefmacDiagnosticProfile)
            installed_record = fx["installed_record"]
            assert isinstance(installed_record, dict)
            ccp4_env = fx["ccp4_env"]
            assert isinstance(ccp4_env, dict)
            ev_root = fx["evidence_root"]
            assert isinstance(ev_root, Path)

            # 1. Tamper one file on disk (longer size -> rejected before full read, while all other files and all 3 roots are retained)
            qc_path = fx["root"] / "support" / "qc-item.json"  # type: ignore[operator]
            orig_qc = qc_path.read_bytes()
            qc_path.write_bytes(b'{"tampered_longer": true}\n')
            try:
                with self.assertRaises(ProfileValidationError) as ctx:
                    validate_profile(
                        profile, installed_record, ccp4_env, ev_root
                    )
                err = ctx.exception
                self.assertEqual(
                    err.failed_check, "outer_profile_files_and_roots"
                )
                self.assertIsNone(err.selected_executable)
                self.assertIsNotNone(err.manifest_identity)
                self.assertEqual(len(err.roots), 3)
                self.assertGreater(len(err.files), 25)
                prov = err.to_provenance()
                self.assertFalse(prov["profile_files_verified"])
                self.assertIsNone(prov["selected_executable"])
                self.assertIn("type", prov["error"])
                self.assertIn("message", prov["error"])
                self.assertIn("errno", prov["error"])
                for fdict in prov["files"].values():
                    self.assertNotEqual(fdict, {})
                    self.assertIn("sha256", fdict)
            finally:
                qc_path.write_bytes(orig_qc)

    def test_1175_frozen_tuple_wrappers_use_empty_slots_without_instance_dict_or_cache(
        self,
    ) -> None:
        self.assertEqual(profile_mod._FrozenMemberTuple.__slots__, ())
        self.assertEqual(profile_mod._FrozenPairTable.__slots__, ())

        members = profile_mod._FrozenMemberTuple(
            [
                ("a/one.f", "fid_1"),
                {"relative_path": "b/two.f", "file_id": "fid_2"},
                profile_mod._RootMember("c/three.f", "fid_3"),
            ]
        )
        self.assertIsInstance(members, tuple)
        self.assertFalse(hasattr(members, "__dict__"))
        self.assertFalse(hasattr(members, "_by_rel"))
        self.assertEqual(len(members), 3)
        self.assertEqual(members[0], ("a/one.f", "fid_1"))
        self.assertEqual(members[-1], ("c/three.f", "fid_3"))
        self.assertEqual(
            members[:2],
            (
                profile_mod._RootMember("a/one.f", "fid_1"),
                profile_mod._RootMember("b/two.f", "fid_2"),
            ),
        )
        self.assertEqual(
            list(members),
            [
                profile_mod._RootMember("a/one.f", "fid_1"),
                profile_mod._RootMember("b/two.f", "fid_2"),
                profile_mod._RootMember("c/three.f", "fid_3"),
            ],
        )
        self.assertEqual(members["b/two.f"], "fid_2")
        self.assertEqual(members.get("b/two.f"), "fid_2")
        self.assertIsNone(members.get("missing.f"))
        self.assertIn("a/one.f", members)
        self.assertIn(("a/one.f", "fid_1"), members)
        self.assertEqual(
            members.keys(), ("a/one.f", "b/two.f", "c/three.f")
        )
        self.assertEqual(members.values(), ("fid_1", "fid_2", "fid_3"))
        self.assertEqual(
            members.items(),
            (("a/one.f", "fid_1"), ("b/two.f", "fid_2"), ("c/three.f", "fid_3")),
        )
        self.assertEqual(
            dict(members),
            {"a/one.f": "fid_1", "b/two.f": "fid_2", "c/three.f": "fid_3"},
        )
        with self.assertRaises(KeyError):
            _ = members["missing.f"]
        with self.assertRaises(ValueError):
            profile_mod._FrozenMemberTuple(
                [("dup.f", "fid_1"), ("dup.f", "fid_2")]
            )
        with self.assertRaises(AttributeError):
            members.extra_attr = 1  # type: ignore[attr-defined]

        pairs = profile_mod._FrozenPairTable(
            [("k1", 10), ("k2", 20), ("k3", 30)]
        )
        self.assertIsInstance(pairs, tuple)
        self.assertFalse(hasattr(pairs, "__dict__"))
        self.assertFalse(hasattr(pairs, "_by_key"))
        self.assertEqual(len(pairs), 3)
        self.assertEqual(pairs[0], ("k1", 10))
        self.assertEqual(pairs[-1], ("k3", 30))
        self.assertEqual(pairs[1:], (("k2", 20), ("k3", 30)))
        self.assertEqual(list(pairs), [("k1", 10), ("k2", 20), ("k3", 30)])
        self.assertEqual(pairs["k2"], 20)
        self.assertEqual(pairs.get("k2"), 20)
        self.assertEqual(pairs.get("missing", -1), -1)
        self.assertIn("k1", pairs)
        self.assertIn(("k1", 10), pairs)
        self.assertEqual(pairs.keys(), ("k1", "k2", "k3"))
        self.assertEqual(pairs.values(), (10, 20, 30))
        self.assertEqual(pairs.items(), (("k1", 10), ("k2", 20), ("k3", 30)))
        self.assertEqual(dict(pairs), {"k1": 10, "k2": 20, "k3": 30})
        self.assertEqual(pairs, {"k1": 10, "k2": 20, "k3": 30})
        with self.assertRaises(KeyError):
            _ = pairs["missing"]
        with self.assertRaises(ValueError):
            profile_mod._FrozenPairTable([("dup", 1), ("dup", 2)])
        with self.assertRaises(AttributeError):
            pairs.extra_attr = 1  # type: ignore[attr-defined]

    def test_1176_in_memory_installed_record_json_detachment_and_strict_parsing(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = _build_synthetic_outer_profile_fixture(Path(tmp))
            profile = fx["profile"]
            assert isinstance(profile, RefmacDiagnosticProfile)
            installed_record = copy.deepcopy(fx["installed_record"])
            assert isinstance(installed_record, dict)
            ccp4_env = fx["ccp4_env"]
            assert isinstance(ccp4_env, dict)
            ev_root = fx["evidence_root"]
            assert isinstance(ev_root, Path)

            # 1. In-memory detachment helper preserves full content and freezes returned mapping
            installed_record["custom_nested"] = {"items": [1, 2, 3]}
            canonical_json, detached_map = (
                profile_mod._serialize_detached_installed_record(
                    installed_record
                )
            )
            installed_record["custom_nested"]["items"].append(4)  # type: ignore[index]
            self.assertEqual(detached_map["custom_nested"]["items"], (1, 2, 3))
            with self.assertRaises(TypeError):
                detached_map["new_key"] = "x"  # type: ignore[index]

            # 2. Direct ValidatedProfile construction and to_provenance() with installed_record_json
            validated = validate_profile(
                profile, fx["installed_record"], ccp4_env, ev_root  # type: ignore[arg-type]
            )
            direct_validated = ValidatedProfile(
                request=validated.request,
                manifest_identity=validated.manifest_identity,
                files=validated.files,
                roots=validated.roots,
                roles=validated.roles,
                installed_reference=validated.installed_reference,
                selected_executable=validated.selected_executable,
                installed_record_json=canonical_json,
                expected_environment=validated.expected_environment,
                requested_absences=validated.requested_absences,
                evidence_root=validated.evidence_root,
            )
            prov = direct_validated.to_provenance()
            self.assertEqual(
                prov["installed_record"]["custom_nested"]["items"], [1, 2, 3]
            )

            # 3. Malformed, non-object, duplicate-key, and nonstandard-constant JSON rejected in
            # ValidatedProfile, ProfileValidationError, and _parse_in_memory_json_object
            for bad_json in (
                "",
                "{malformed",
                "[]",
                "123",
                '"string"',
                '{"a": 1, "a": 2}',
                '{"nan_val": NaN}',
                '{"inf_val": Infinity}',
                '{"neg_inf": -Infinity}',
            ):
                with self.subTest(bad_json=bad_json):
                    with self.assertRaises(ValueError):
                        profile_mod._parse_in_memory_json_object(
                            bad_json, label="test_json"
                        )
                    with self.assertRaises(ValueError):
                        ValidatedProfile(
                            request=validated.request,
                            manifest_identity=validated.manifest_identity,
                            files=validated.files,
                            roots=validated.roots,
                            roles=validated.roles,
                            installed_reference=validated.installed_reference,
                            selected_executable=validated.selected_executable,
                            installed_record_json=bad_json,
                            expected_environment=validated.expected_environment,
                            requested_absences=validated.requested_absences,
                            evidence_root=validated.evidence_root,
                        )
                    with self.assertRaises(ValueError):
                        ProfileValidationError(
                            "bad json",
                            failed_check="installed_record",
                            installed_record_json=bad_json,
                        )

            # 4. _parse_verified_json_bytes remains strictly tied to an independent expected_pin
            with self.assertRaises(TypeError):
                _parse_verified_json_bytes(b"{}")  # type: ignore[call-arg]

    def test_1177_and_1178_installed_setup_prefix_and_inner_opaque_metadata_controls(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = _build_synthetic_outer_profile_fixture(Path(tmp))
            root = fx["root"]
            assert isinstance(root, Path)
            profile = fx["profile"]
            assert isinstance(profile, RefmacDiagnosticProfile)
            installed_record = fx["installed_record"]
            assert isinstance(installed_record, dict)
            ccp4_env = fx["ccp4_env"]
            assert isinstance(ccp4_env, dict)
            ev_root = fx["evidence_root"]
            assert isinstance(ev_root, Path)
            base_payload = fx["manifest_payload"]
            assert isinstance(base_payload, dict)

            # 1. #1177: unmodified positive fixture places ccp4_setup under root/installed/bin/ccp4.setup-sh
            setup_fid = base_payload["roles"]["ccp4_setup"][0]  # type: ignore[index]
            setup_row = base_payload["files"][setup_fid]  # type: ignore[index]
            expected_setup_path = str(root / "installed" / "bin" / "ccp4.setup-sh")
            self.assertEqual(setup_row["path"], expected_setup_path)
            self.assertEqual(setup_row["resolved_path"], expected_setup_path)
            self.assertEqual(
                installed_record["configured_installation_prefix"],
                str(root / "installed"),
            )
            baseline_validated = validate_profile(
                profile, installed_record, ccp4_env, ev_root
            )
            self.assertIsInstance(baseline_validated, ValidatedProfile)

            # Setup script resolved_path outside configured_installation_prefix is rejected
            outside_inst = copy.deepcopy(installed_record)
            outside_path = str(root / "support" / "installed" / "bin" / "ccp4.setup-sh")
            outside_inst["setup_script"]["configured_path"] = outside_path  # type: ignore[index]
            outside_inst["setup_script"]["resolved_path"] = outside_path  # type: ignore[index]
            with self.assertRaisesRegex(
                ProfileValidationError,
                "outside configured_installation_prefix",
            ) as out_ctx:
                validate_profile(profile, outside_inst, ccp4_env, ev_root)
            self.assertEqual(out_ctx.exception.failed_check, "installed_record")

            # 2. #1178 positive: opaque extra keys (including empty-string key "" and consistent recognized aliases) admitted on:
            # - source_audit.interpreter
            # - runtime_observation.observation_script
            # - runtime_observation.setup_source_files[*]
            # - runtime_observation.static_library_load_commands[*].library
            # - build_receipt.executable
            prof_sa, restore_sa = _mutate_inner_receipt_and_repin(
                fx,
                "source_audit",
                lambda d: d["interpreter"].update(
                    {
                        "resolved": d["interpreter"]["resolved_path"],
                        "python_version": "3.12.7",
                        "opaque_meta": {"implementation": "CPython", "tier": 1},
                        "": {"empty_key_meta": True},
                    }
                ),
            )
            try:
                val_sa = validate_profile(
                    prof_sa, installed_record, ccp4_env, ev_root
                )
                self.assertTrue(val_sa.profile_files_verified)
            finally:
                restore_sa()

            prof_rt, restore_rt = _mutate_inner_receipt_and_repin(
                fx,
                "runtime_observation",
                lambda d: (
                    d["observation_script"].update(
                        {
                            "resolved_path": d["observation_script"]["resolved"],
                            "script_role": "observer",
                            "opaque_meta": {"version": 1},
                            "": {"empty_key_meta": "observer"},
                        }
                    ),
                    [
                        entry.update(
                            {
                                "resolved_path": entry["resolved"],
                                "shell": "sh",
                                "source_index": idx,
                                "": {"empty_key_meta": idx},
                            }
                        )
                        for idx, entry in enumerate(d["setup_source_files"])
                    ],
                    [
                        cmd["library"].update(
                            {
                                "resolved_path": cmd["library"]["resolved"],
                                "macho_cmd": "LC_LOAD_DYLIB",
                                "compat_version": "1.0.0",
                                "": {"empty_key_meta": "library"},
                            }
                        )
                        for cmd in d["static_library_load_commands"]
                    ],
                ),
            )
            try:
                val_rt = validate_profile(
                    prof_rt, installed_record, ccp4_env, ev_root
                )
                self.assertTrue(val_rt.profile_files_verified)
            finally:
                restore_rt()

            diag_fid = base_payload["roles"]["diagnostic_executable"][0]  # type: ignore[index]
            diag_resolved = str(base_payload["files"][diag_fid]["resolved_path"])  # type: ignore[index]
            prof_br, restore_br = _mutate_inner_receipt_and_repin(
                fx,
                "build_receipt",
                lambda d: d["executable"].update(
                    {
                        "resolved_path": diag_resolved,
                        "resolved": diag_resolved,
                        "executable": True,
                        "arch": "arm64",
                        "opaque_meta": {"stripped": False},
                        "": {"empty_key_meta": "executable"},
                    }
                ),
            )
            try:
                val_br = validate_profile(
                    prof_br, installed_record, ccp4_env, ev_root
                )
                self.assertTrue(val_br.profile_files_verified)
            finally:
                restore_br()

            # 3. #1178 negative controls: missing required keys, contradictory recognized aliases,
            # and unknown extra fields never replacing known comparisons
            neg_sa_cases = (
                (
                    "source_audit.interpreter must contain required keys",
                    lambda d: d["interpreter"].pop("resolved_path"),
                ),
                (
                    "source_audit.interpreter.resolved contradicts resolved_path",
                    lambda d: d["interpreter"].update(
                        {
                            "resolved": "/contradictory/python",
                            "extra_meta": "ignored",
                        }
                    ),
                ),
                (
                    "source_audit.interpreter does not match",
                    lambda d: d["interpreter"].update(
                        {
                            "true_sha256": d["interpreter"]["sha256"],
                            "sha256": "0" * 64,
                        }
                    ),
                ),
            )
            for pattern, mutator in neg_sa_cases:
                with self.subTest(neg_sa=pattern):
                    bad_p, rest = _mutate_inner_receipt_and_repin(
                        fx, "source_audit", mutator
                    )
                    try:
                        with self.assertRaisesRegex(
                            ProfileValidationError, pattern
                        ) as ctx:
                            validate_profile(
                                bad_p, installed_record, ccp4_env, ev_root
                            )
                        self.assertEqual(
                            ctx.exception.failed_check, "source_audit_join"
                        )
                    finally:
                        rest()

            neg_rt_cases = (
                (
                    "runtime_observation.observation_script must contain required keys",
                    lambda d: d["observation_script"].pop("resolved"),
                ),
                (
                    "runtime_observation.setup_source_files\\[0\\].resolved_path contradicts resolved",
                    lambda d: d["setup_source_files"][0].update(
                        {
                            "resolved_path": "/contradictory/setup",
                            "extra_meta": 1,
                        }
                    ),
                ),
                (
                    "runtime_observation.static_library_load_commands\\[0\\].library.resolved_path contradicts resolved",
                    lambda d: d["static_library_load_commands"][0][
                        "library"
                    ].update(
                        {
                            "resolved_path": "/contradictory/lib.dylib",
                            "extra_meta": 1,
                        }
                    ),
                ),
                (
                    "runtime_observation.static_library_load_commands\\[0\\].library pin mismatch",
                    lambda d: d["static_library_load_commands"][0][
                        "library"
                    ].update(
                        {
                            "real_sha256": d["static_library_load_commands"][0][
                                "library"
                            ]["sha256"],
                            "sha256": "9" * 64,
                        }
                    ),
                ),
            )
            for pattern, mutator in neg_rt_cases:
                with self.subTest(neg_rt=pattern):
                    bad_p, rest = _mutate_inner_receipt_and_repin(
                        fx, "runtime_observation", mutator
                    )
                    try:
                        with self.assertRaisesRegex(
                            ProfileValidationError, pattern
                        ) as ctx:
                            validate_profile(
                                bad_p, installed_record, ccp4_env, ev_root
                            )
                        self.assertEqual(
                            ctx.exception.failed_check,
                            "runtime_observation_join",
                        )
                    finally:
                        rest()

            neg_br_cases = (
                (
                    "build_receipt.executable must contain required keys",
                    lambda d: d["executable"].pop("sha256"),
                ),
                (
                    "build_receipt.executable.resolved_path contradicts",
                    lambda d: d["executable"].update(
                        {"resolved_path": "/contradictory/refmac5"}
                    ),
                ),
                (
                    "build_receipt.executable.resolved contradicts",
                    lambda d: d["executable"].update(
                        {"resolved": "/contradictory/refmac5"}
                    ),
                ),
                (
                    "build_receipt.executable does not match",
                    lambda d: d["executable"].update(
                        {
                            "authoritative_sha256": d["executable"]["sha256"],
                            "sha256": "a" * 64,
                        }
                    ),
                ),
            )
            for pattern, mutator in neg_br_cases:
                with self.subTest(neg_br=pattern):
                    bad_p, rest = _mutate_inner_receipt_and_repin(
                        fx, "build_receipt", mutator
                    )
                    try:
                        with self.assertRaisesRegex(
                            ProfileValidationError, pattern
                        ) as ctx:
                            validate_profile(
                                bad_p, installed_record, ccp4_env, ev_root
                            )
                        self.assertEqual(
                            ctx.exception.failed_check, "build_receipt_join"
                        )
                    finally:
                        rest()

            # 4. Outer manifest remains CLOSED (extra key on outer manifest file entry rejected)
            closed_outer_payload = copy.deepcopy(base_payload)
            closed_outer_payload["files"][setup_fid]["extra_opaque"] = 1  # type: ignore[index]
            closed_outer_prof = _rewrite_manifest_and_profile(
                fx, closed_outer_payload
            )
            try:
                with self.assertRaisesRegex(
                    ProfileValidationError,
                    r"File row .* must have exact keys",
                ) as closed_ctx:
                    validate_profile(
                        closed_outer_prof, installed_record, ccp4_env, ev_root
                    )
                self.assertEqual(
                    closed_ctx.exception.failed_check, "outer_manifest_shape"
                )
            finally:
                _rewrite_manifest_and_profile(fx, base_payload)

    def test_1168_retains_traversed_dotdot_ancestors_without_retraversal_and_never_fabricates_zero_symlink_identity(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = _build_synthetic_outer_profile_fixture(Path(tmp))
            root = fx["root"]
            assert isinstance(root, Path)
            profile = fx["profile"]
            assert isinstance(profile, RefmacDiagnosticProfile)
            installed_record = fx["installed_record"]
            assert isinstance(installed_record, dict)
            ccp4_env = fx["ccp4_env"]
            assert isinstance(ccp4_env, dict)
            ev_root = fx["evidence_root"]
            assert isinstance(ev_root, Path)
            base_payload = fx["manifest_payload"]
            assert isinstance(base_payload, dict)
            alias_symlink = fx["alias_symlink"]
            assert isinstance(alias_symlink, Path)
            alias_dotdot = str(fx["alias_dotdot"])

            support_bin = root / "support" / "bin"
            self.assertTrue(support_bin.is_dir())
            dotdot_fid = next(
                fid
                for fid, row in base_payload["files"].items()  # type: ignore[union-attr]
                if row["path"] == alias_dotdot
            )
            symlink_fid = next(
                fid
                for fid, row in base_payload["files"].items()  # type: ignore[union-attr]
                if row["path"] == str(alias_symlink)
            )

            # 1. Positive baseline: support/bin is retained in FileObservation.ancestors for bin/../collection-python
            validated = validate_profile(
                profile, installed_record, ccp4_env, ev_root
            )
            dotdot_fobs = validated.files[dotdot_fid]
            self.assertTrue(dotdot_fobs.dependencies_complete)
            self.assertTrue(dotdot_fobs.complete)
            self.assertTrue(dotdot_fobs.verified)
            self.assertEqual(dotdot_fobs.errors, ())
            self.assertEqual(dotdot_fobs.unavailable_symlinks, ())
            self.assertIn(
                str(support_bin),
                [anc.path for anc in dotdot_fobs.ancestors],
            )

            # 2. If support/bin disappears after file observation, public conversion and _build_file_observation
            # project in memory from retained observations without re-traversing the filesystem or losing support/bin
            outer_state = _validate_and_observe_outer_profile(
                profile, evidence_root=ev_root
            )
            support_bin.rmdir()
            try:
                with (
                    mock.patch(
                        "refmac_diagnostic_profile._traverse_path_components",
                        side_effect=AssertionError(
                            "_build_file_observation must not re-traverse filesystem"
                        ),
                    ),
                    mock.patch(
                        "refmac_diagnostic_profile.os.lstat",
                        side_effect=AssertionError(
                            "_build_file_observation must not call os.lstat"
                        ),
                    ),
                ):
                    projected_with_deps = profile_mod._build_file_observation(
                        outer_state.observed_files[dotdot_fid],
                        observed_ancestors=outer_state.observed_ancestors,
                        observed_symlinks=outer_state.observed_symlinks,
                        file_dependencies=outer_state.file_dependencies[
                            dotdot_fid
                        ],
                    )
                    projected_from_pin = profile_mod._build_file_observation(
                        outer_state.observed_files[dotdot_fid],
                        observed_ancestors=outer_state.observed_ancestors,
                        observed_symlinks=outer_state.observed_symlinks,
                    )
                for proj in (projected_with_deps, projected_from_pin):
                    self.assertTrue(proj.dependencies_complete)
                    self.assertTrue(proj.verified)
                    self.assertIn(
                        str(support_bin),
                        [anc.path for anc in proj.ancestors],
                    )
            finally:
                support_bin.mkdir(parents=True, exist_ok=True)

            # Also verify when support/bin disappears during validate_profile right after dotdot_fid is observed
            real_observe_pin = profile_mod._observe_regular_file_pin

            def observe_pin_then_remove_support_bin(path, *args, **kwargs):
                res = real_observe_pin(path, *args, **kwargs)
                if str(path) == alias_dotdot and support_bin.exists():
                    support_bin.rmdir()
                return res

            bad_env = {**ccp4_env, "CLIBD": "force-post-outer-failure"}
            try:
                with mock.patch(
                    "refmac_diagnostic_profile._observe_regular_file_pin",
                    side_effect=observe_pin_then_remove_support_bin,
                ):
                    with self.assertRaises(ProfileValidationError) as ctx_rm:
                        validate_profile(
                            profile, installed_record, bad_env, ev_root
                        )
                retained_dotdot = ctx_rm.exception.files[dotdot_fid]
                self.assertTrue(retained_dotdot.dependencies_complete)
                self.assertTrue(retained_dotdot.verified)
                self.assertIn(
                    str(support_bin),
                    [anc.path for anc in retained_dotdot.ancestors],
                )
            finally:
                support_bin.mkdir(parents=True, exist_ok=True)

            # 3. Unavailable symlink identity is represented as incomplete/unverified without fabricated zero identities
            real_observe_symlink = profile_mod._observe_symlink_identity

            def fail_symlink_identity(edge: _SymlinkEdge):
                if edge.path == str(alias_symlink):
                    cause = PermissionError(
                        errno.EACCES, "symlink lstat denied after read"
                    )
                    err = ValueError(
                        f"Cannot inspect symlink {edge.path!r} (PermissionError): {cause}"
                    )
                    err.__cause__ = cause
                    raise err
                return real_observe_symlink(edge)

            with mock.patch(
                "refmac_diagnostic_profile._observe_symlink_identity",
                side_effect=fail_symlink_identity,
            ):
                with self.assertRaises(ProfileValidationError) as sym_ctx:
                    validate_profile(
                        profile, installed_record, ccp4_env, ev_root
                    )
            sym_err = sym_ctx.exception
            self.assertEqual(
                sym_err.failed_check, "outer_profile_files_and_roots"
            )
            self.assertEqual(sym_err.error_type, "PermissionError")
            self.assertEqual(sym_err.error_errno, errno.EACCES)
            incomplete_fobs = sym_err.files[symlink_fid]
            self.assertFalse(incomplete_fobs.dependencies_complete)
            self.assertFalse(incomplete_fobs.complete)
            self.assertFalse(incomplete_fobs.verified)
            self.assertEqual(
                incomplete_fobs.symlinks,
                (_SymlinkEdge(path=str(alias_symlink), target="collection-python"),),
            )
            self.assertEqual(incomplete_fobs.symlink_identities, ())
            self.assertEqual(
                incomplete_fobs.unavailable_symlinks,
                (_SymlinkEdge(path=str(alias_symlink), target="collection-python"),),
            )
            self.assertGreaterEqual(len(incomplete_fobs.errors), 1)
            fobs_dict = incomplete_fobs.to_dict()
            self.assertFalse(fobs_dict["dependencies_complete"])
            self.assertFalse(fobs_dict["verified"])
            self.assertEqual(fobs_dict["symlink_identities"], [])
            self.assertTrue(fobs_dict["errors"])

            # Direct _build_file_observation with empty observed_symlinks also marks incomplete without touching disk
            with (
                mock.patch(
                    "refmac_diagnostic_profile.os.lstat",
                    side_effect=AssertionError("must not lstat"),
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.readlink",
                    side_effect=AssertionError("must not readlink"),
                ),
            ):
                direct_incomplete = profile_mod._build_file_observation(
                    outer_state.observed_files[symlink_fid],
                    observed_ancestors=outer_state.observed_ancestors,
                    observed_symlinks={},
                )
            self.assertFalse(direct_incomplete.dependencies_complete)
            self.assertFalse(direct_incomplete.verified)
            self.assertEqual(direct_incomplete.symlink_identities, ())
            self.assertEqual(
                direct_incomplete.unavailable_symlinks,
                (_SymlinkEdge(path=str(alias_symlink), target="collection-python"),),
            )
            self.assertGreaterEqual(len(direct_incomplete.errors), 1)

            # Fabricated zero identities are rejected by _ObservedSymlinkIdentity, _ObservedDirectoryIdentity,
            # FileObservation, and ValidatedProfile rejects incomplete FileObservation
            with self.assertRaisesRegex(
                ValueError, "fabricated zero or non-positive"
            ):
                profile_mod._ObservedSymlinkIdentity(
                    path=str(alias_symlink),
                    target="collection-python",
                    dev=0,
                    ino=0,
                    mode=0,
                    uid=0,
                    gid=0,
                )
            with self.assertRaisesRegex(
                ValueError, "fabricated zero or non-positive"
            ):
                profile_mod._ObservedDirectoryIdentity(
                    path="/",
                    resolved_path="/",
                    dev=0,
                    ino=0,
                    mode=0,
                    uid=0,
                    gid=0,
                )
            with self.assertRaisesRegex(
                ValueError, "must have dependencies_complete=True"
            ):
                ValidatedProfile(
                    request=validated.request,
                    manifest_identity=direct_incomplete,
                    files=validated.files,
                    roots=validated.roots,
                    roles=validated.roles,
                    installed_reference=validated.installed_reference,
                    selected_executable=validated.selected_executable,
                    installed_record_json=validated.installed_record_json,
                    expected_environment=validated.expected_environment,
                    requested_absences=validated.requested_absences,
                    evidence_root=validated.evidence_root,
                )

    def test_1179_preserves_actual_caught_exception_objects_and_walks_cause_chain_at_evidence_root_and_other_boundaries(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = _build_synthetic_outer_profile_fixture(Path(tmp))
            profile = fx["profile"]
            assert isinstance(profile, RefmacDiagnosticProfile)
            installed_record = fx["installed_record"]
            assert isinstance(installed_record, dict)
            ccp4_env = fx["ccp4_env"]
            assert isinstance(ccp4_env, dict)
            ev_root = fx["evidence_root"]
            assert isinstance(ev_root, Path)

            perm_err = PermissionError(errno.EACCES, "Permission denied")
            chained_val_err = ValueError(
                f"Cannot inspect evidence_root component {str(ev_root)!r} (PermissionError): {perm_err}"
            )
            chained_val_err.__cause__ = perm_err

            with mock.patch(
                "refmac_diagnostic_profile._validate_and_observe_evidence_root",
                side_effect=chained_val_err,
            ):
                with self.assertRaises(ProfileValidationError) as ctx:
                    validate_profile(
                        profile, installed_record, ccp4_env, ev_root
                    )

            err = ctx.exception
            self.assertEqual(err.failed_check, "evidence_root")
            # Later manifest, roots, and files were still observed and retained
            self.assertIsNotNone(err.manifest_identity)
            self.assertEqual(len(err.roots), 3)
            self.assertGreater(len(err.files), 30)

            # Exact exception objects are preserved across the __cause__ chain
            self.assertIsInstance(err.__cause__, _ProfileObservationError)
            self.assertIs(err.__cause__.__cause__, chained_val_err)
            self.assertIs(err.__cause__.__cause__.__cause__, perm_err)
            self.assertIs(err.cause_exception, perm_err)
            self.assertEqual(len(err.error_records), 1)
            self.assertEqual(err.error_records[0].stage, "evidence_root")
            self.assertIs(err.error_records[0].exception, chained_val_err)

            # Public error fields come consistently from the single selected PermissionError cause
            self.assertEqual(err.error_type, "PermissionError")
            self.assertEqual(err.error_errno, errno.EACCES)
            self.assertEqual(err.error_message, str(perm_err))
            self.assertEqual(err.wrapper_message, str(chained_val_err))

            prov = err.to_provenance()
            self.assertEqual(prov["failed_check"], "evidence_root")
            self.assertEqual(prov["error"]["type"], "PermissionError")
            self.assertEqual(prov["error"]["errno"], errno.EACCES)
            self.assertEqual(prov["error"]["message"], str(perm_err))
            self.assertEqual(
                prov["error"]["wrapper_message"], str(chained_val_err)
            )

    def test_1180_explicit_failed_check_stage_recording_without_message_substring_classification(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = _build_synthetic_outer_profile_fixture(Path(tmp))
            profile = fx["profile"]
            assert isinstance(profile, RefmacDiagnosticProfile)
            installed_record = fx["installed_record"]
            assert isinstance(installed_record, dict)
            ccp4_env = fx["ccp4_env"]
            assert isinstance(ccp4_env, dict)
            ev_root = fx["evidence_root"]
            assert isinstance(ev_root, Path)
            base_payload = fx["manifest_payload"]
            assert isinstance(base_payload, dict)
            manifest_path = fx["manifest_path"]
            assert isinstance(manifest_path, Path)

            # 1. Repinned manifest with wrong schema_id has "Profile manifest schema_id..." in message
            # and MUST classify as "outer_manifest_shape" (never misclassified as "manifest_pin")
            wrong_schema_payload = copy.deepcopy(base_payload)
            wrong_schema_payload["schema_id"] = "wrong_schema_id"
            wrong_schema_prof = _rewrite_manifest_and_profile(
                fx, wrong_schema_payload
            )
            try:
                with self.assertRaisesRegex(
                    ProfileValidationError,
                    "Profile manifest schema_id must be",
                ) as schema_ctx:
                    validate_profile(
                        wrong_schema_prof, installed_record, ccp4_env, ev_root
                    )
                self.assertEqual(
                    schema_ctx.exception.failed_check, "outer_manifest_shape"
                )
                self.assertEqual(
                    schema_ctx.exception.to_provenance()["failed_check"],
                    "outer_manifest_shape",
                )
            finally:
                _rewrite_manifest_and_profile(fx, base_payload)

            # 2. Repinned manifest with invalid JSON syntax, duplicate keys, or NaN classifies as "manifest_json"
            orig_manifest_bytes = manifest_path.read_bytes()
            try:
                for raw_bad_json, exp_err_type in (
                    (b'{"schema_id": \n', "JSONDecodeError"),
                    (b'{"a": 1, "a": 2}\n', "ValueError"),
                    (b'{"a": NaN}\n', "ValueError"),
                ):
                    with self.subTest(raw_bad_json=raw_bad_json):
                        manifest_path.write_bytes(raw_bad_json)
                        bad_json_pin = _make_file_pin_on_disk(manifest_path)
                        bad_json_prof = RefmacDiagnosticProfile(
                            profile_id=profile.profile_id,
                            manifest=bad_json_pin,
                            executable=profile.executable,
                        )
                        with self.assertRaises(
                            ProfileValidationError
                        ) as json_ctx:
                            validate_profile(
                                bad_json_prof,
                                installed_record,
                                ccp4_env,
                                ev_root,
                            )
                        self.assertEqual(
                            json_ctx.exception.failed_check, "manifest_json"
                        )
                        self.assertEqual(
                            json_ctx.exception.error_type, exp_err_type
                        )
                        self.assertIsNotNone(
                            json_ctx.exception.manifest_identity
                        )

                # 3. Wrong caller manifest SHA-256 digest fails at "manifest_pin" before file JSON parsing
                untrusted_manifest_bytes = b'{"broken_syntax": \n'
                manifest_path.write_bytes(untrusted_manifest_bytes)
                wrong_sha_prof = RefmacDiagnosticProfile(
                    profile_id=profile.profile_id,
                    manifest=FilePin(
                        path=str(manifest_path),
                        sha256="0" * 64,
                        size_bytes=len(untrusted_manifest_bytes),
                    ),
                    executable=profile.executable,
                )
                real_json_loads = json.loads
                manifest_json_loads_calls: list[object] = []

                def trap_manifest_json_loads(s, *args, **kwargs):
                    if "broken_syntax" in str(s):
                        manifest_json_loads_calls.append(s)
                    return real_json_loads(s, *args, **kwargs)

                with (
                    mock.patch(
                        "refmac_diagnostic_profile._parse_verified_json_bytes",
                        wraps=profile_mod._parse_verified_json_bytes,
                    ) as mocked_parse_file_json,
                    mock.patch(
                        "refmac_diagnostic_profile.json.loads",
                        side_effect=trap_manifest_json_loads,
                    ),
                ):
                    with self.assertRaises(ProfileValidationError) as pin_ctx:
                        validate_profile(
                            wrong_sha_prof,
                            installed_record,
                            ccp4_env,
                            ev_root,
                        )
                    mocked_parse_file_json.assert_not_called()
                self.assertEqual(manifest_json_loads_calls, [])
                self.assertEqual(pin_ctx.exception.failed_check, "manifest_pin")
                self.assertIsNotNone(pin_ctx.exception.installed_record_json)
            finally:
                manifest_path.write_bytes(orig_manifest_bytes)

            # 4. Multiple failures preserve ordered errors and aligned stage/exception error_records
            extra_vendor = fx["trees"]["vendor"] / ".extra_multi_err"  # type: ignore[index]
            extra_vendor.write_text("extra\n", encoding="utf-8")
            perm_err = PermissionError(errno.EACCES, "denied on evidence_root")
            ev_val_err = ValueError(f"evidence_root error: {perm_err}")
            ev_val_err.__cause__ = perm_err
            try:
                with mock.patch(
                    "refmac_diagnostic_profile._validate_and_observe_evidence_root",
                    side_effect=ev_val_err,
                ):
                    with self.assertRaises(ProfileValidationError) as multi_ctx:
                        validate_profile(
                            profile, installed_record, ccp4_env, ev_root
                        )
                m_err = multi_ctx.exception
                self.assertEqual(m_err.failed_check, "evidence_root")
                self.assertEqual(m_err.error_type, "PermissionError")
                self.assertEqual(m_err.error_errno, errno.EACCES)
                self.assertGreaterEqual(len(m_err.errors), 2)
                self.assertEqual(len(m_err.error_records), len(m_err.errors))
                self.assertEqual(m_err.error_records[0].stage, "evidence_root")
                self.assertIs(m_err.error_records[0].exception, ev_val_err)
                self.assertEqual(
                    m_err.error_records[1].stage,
                    "outer_profile_files_and_roots",
                )
            finally:
                extra_vendor.unlink()

            # 5. Primary manifest JSON error is recorded before secondary dependency recovery error (#1180)
            manifest_alias = fx["root"] / "manifest-bad-json-alias.json"  # type: ignore[operator]
            os.symlink("diagnostic-profile.json", manifest_alias)
            try:
                manifest_path.write_bytes(b'{"schema_id": \n')
                bad_alias_pin = _make_file_pin_on_disk(manifest_alias)
                bad_alias_prof = RefmacDiagnosticProfile(
                    profile_id=profile.profile_id,
                    manifest=bad_alias_pin,
                    executable=profile.executable,
                )
                real_observe_symlink = profile_mod._observe_symlink_identity
                dep_perm_err = PermissionError(
                    errno.EACCES, "symlink lstat denied during manifest recovery"
                )

                def fail_manifest_alias_symlink(edge: _SymlinkEdge):
                    if edge.path == str(manifest_alias):
                        err = ValueError(
                            f"Cannot inspect symlink {edge.path!r} (PermissionError): {dep_perm_err}"
                        )
                        err.__cause__ = dep_perm_err
                        raise err
                    return real_observe_symlink(edge)

                with mock.patch(
                    "refmac_diagnostic_profile._observe_symlink_identity",
                    side_effect=fail_manifest_alias_symlink,
                ):
                    with self.assertRaises(ProfileValidationError) as rec_ctx:
                        validate_profile(
                            bad_alias_prof,
                            installed_record,
                            ccp4_env,
                            ev_root,
                        )
                rec_err = rec_ctx.exception
                self.assertEqual(rec_err.failed_check, "manifest_json")
                self.assertEqual(rec_err.error_type, "JSONDecodeError")
                self.assertIsInstance(rec_err.cause_exception, json.JSONDecodeError)
                self.assertEqual(len(rec_err.errors), 2)
                self.assertEqual(len(rec_err.error_records), 2)
                self.assertEqual(rec_err.error_records[0].stage, "manifest_json")
                self.assertIs(
                    rec_err.error_records[0].exception.__cause__.__cause__,
                    rec_err.cause_exception,
                )
                self.assertEqual(rec_err.error_records[1].stage, "manifest_pin")
                self.assertIs(
                    rec_err.error_records[1].exception.__cause__, dep_perm_err
                )
                self.assertIsNotNone(rec_err.manifest_identity)
                assert rec_err.manifest_identity is not None
                self.assertFalse(rec_err.manifest_identity.dependencies_complete)
                self.assertFalse(rec_err.manifest_identity.verified)
                self.assertEqual(len(rec_err.manifest_identity.errors), 2)
            finally:
                manifest_path.write_bytes(orig_manifest_bytes)
                if manifest_alias.is_symlink() or manifest_alias.exists():
                    manifest_alias.unlink()

    def test_1168_retains_conflicting_symlink_measurements_and_continues_valid_manifest_dependency_failure(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = _build_synthetic_outer_profile_fixture(Path(tmp))
            root = fx["root"]
            assert isinstance(root, Path)
            profile = fx["profile"]
            assert isinstance(profile, RefmacDiagnosticProfile)
            installed_record = fx["installed_record"]
            assert isinstance(installed_record, dict)
            ccp4_env = fx["ccp4_env"]
            assert isinstance(ccp4_env, dict)
            ev_root = fx["evidence_root"]
            assert isinstance(ev_root, Path)
            base_payload = fx["manifest_payload"]
            assert isinstance(base_payload, dict)
            alias_symlink = fx["alias_symlink"]
            assert isinstance(alias_symlink, Path)

            # 1. Positive baseline has 59 verified files and 3 verified controlled roots
            baseline_val = validate_profile(
                profile, installed_record, ccp4_env, ev_root
            )
            self.assertEqual(len(baseline_val.files), 59)
            self.assertEqual(len(baseline_val.roots), 3)
            self.assertEqual(
                set(dict(baseline_val.roots).keys()),
                {"vendor", "prepared", "build"},
            )

            # 2. Valid manifest through symlink alias with only alias metadata denial retains
            # all 59 obtainable files and all 3 controlled roots while rejecting admission
            manifest_alias = root / "manifest-valid-alias.json"
            os.symlink("diagnostic-profile.json", manifest_alias)
            try:
                alias_profile = RefmacDiagnosticProfile(
                    profile_id=profile.profile_id,
                    manifest=_make_file_pin_on_disk(manifest_alias),
                    executable=profile.executable,
                )
                alias_val = validate_profile(
                    alias_profile, installed_record, ccp4_env, ev_root
                )
                self.assertEqual(len(alias_val.files), 59)
                self.assertEqual(len(alias_val.roots), 3)
                self.assertEqual(
                    alias_val.manifest_identity.symlink_identities[0].path,
                    str(manifest_alias),
                )

                real_observe_symlink = profile_mod._observe_symlink_identity
                alias_perm_err = PermissionError(
                    errno.EACCES, "manifest alias symlink metadata denied"
                )

                def deny_only_manifest_alias(edge: _SymlinkEdge):
                    if edge.path == str(manifest_alias):
                        err = ValueError(
                            f"Cannot inspect symlink {edge.path!r} (PermissionError): {alias_perm_err}"
                        )
                        err.__cause__ = alias_perm_err
                        raise err
                    return real_observe_symlink(edge)

                with mock.patch(
                    "refmac_diagnostic_profile._observe_symlink_identity",
                    side_effect=deny_only_manifest_alias,
                ):
                    with self.assertRaises(ProfileValidationError) as mdep_ctx:
                        validate_profile(
                            alias_profile, installed_record, ccp4_env, ev_root
                        )
                mdep_err = mdep_ctx.exception
                self.assertIsNone(mdep_err.selected_executable)
                self.assertFalse(mdep_err.profile_files_verified)
                self.assertEqual(mdep_err.failed_check, "manifest_pin")
                self.assertEqual(mdep_err.error_type, "PermissionError")
                self.assertEqual(mdep_err.error_errno, errno.EACCES)
                self.assertIs(mdep_err.cause_exception, alias_perm_err)
                self.assertIsNotNone(mdep_err.manifest_identity)
                assert mdep_err.manifest_identity is not None
                self.assertFalse(mdep_err.manifest_identity.dependencies_complete)
                self.assertFalse(mdep_err.manifest_identity.verified)
                self.assertEqual(
                    mdep_err.manifest_identity.unavailable_symlinks,
                    (
                        _SymlinkEdge(
                            path=str(manifest_alias),
                            target="diagnostic-profile.json",
                        ),
                    ),
                )
                self.assertEqual(len(mdep_err.files), 59)
                self.assertTrue(
                    all(
                        fobs.verified and fobs.dependencies_complete
                        for _fid, fobs in mdep_err.files
                    )
                )
                self.assertEqual(len(mdep_err.roots), 3)
                self.assertEqual(
                    set(dict(mdep_err.roots).keys()),
                    {"vendor", "prepared", "build"},
                )
                self.assertTrue(
                    all(
                        robs.verified and robs.scan_complete
                        for _rname, robs in mdep_err.roots
                    )
                )
                mdep_prov = mdep_err.to_provenance()
                self.assertFalse(mdep_prov["profile_files_verified"])
                self.assertIsNone(mdep_prov["selected_executable"])
                self.assertEqual(mdep_prov["failed_check"], "manifest_pin")
                self.assertEqual(len(mdep_prov["files"]), 59)
                self.assertEqual(len(mdep_prov["roots"]), 3)
            finally:
                if manifest_alias.is_symlink() or manifest_alias.exists():
                    manifest_alias.unlink()

            # 3. Two files traversing the same symlink where the symlink is renamed (keeping old inode alive)
            # and replaced with a new same-target symlink between the two files: both files retain their
            # respective measured symlink identities, while the second file is incomplete/unverified and
            # its measured edge is NOT labelled unavailable.
            symlink_fid_1 = next(
                fid
                for fid, row in base_payload["files"].items()  # type: ignore[union-attr]
                if row["path"] == str(alias_symlink)
            )
            symlink_fid_2 = "zz_second_shared_symlink_user"
            second_lexical_via_link = f"{root}/support/bin/../python-alias"
            second_obs_initial = _observe_regular_file_pin(second_lexical_via_link)
            self.assertEqual(
                second_obs_initial.symlinks,
                (_SymlinkEdge(path=str(alias_symlink), target="collection-python"),),
            )

            shared_payload = copy.deepcopy(base_payload)
            shared_payload["files"][symlink_fid_2] = (  # type: ignore[index]
                second_obs_initial.to_manifest_row()
            )
            shared_payload["roles"]["qc_evidence"] = sorted(  # type: ignore[index]
                [*shared_payload["roles"]["qc_evidence"], symlink_fid_2]  # type: ignore[index]
            )
            shared_profile = _rewrite_manifest_and_profile(fx, shared_payload)

            retained_old_link = root / "support" / "python-alias.retained-old"
            real_collect_deps = profile_mod._collect_file_dependencies
            ino_first_holder: list[int] = []
            ino_second_holder: list[int] = []

            def collect_deps_and_replace_shared_symlink(
                file_obs, *, ancestors_out, symlinks_out
            ):
                res = real_collect_deps(
                    file_obs,
                    ancestors_out=ancestors_out,
                    symlinks_out=symlinks_out,
                )
                if file_obs.path == str(alias_symlink):
                    ino_first_holder.append(os.lstat(alias_symlink).st_ino)
                    os.rename(alias_symlink, retained_old_link)
                    os.symlink("collection-python", alias_symlink)
                    ino_second_holder.append(os.lstat(alias_symlink).st_ino)
                return res

            try:
                with mock.patch(
                    "refmac_diagnostic_profile._collect_file_dependencies",
                    side_effect=collect_deps_and_replace_shared_symlink,
                ):
                    with self.assertRaises(ProfileValidationError) as conf_ctx:
                        validate_profile(
                            shared_profile, installed_record, ccp4_env, ev_root
                        )
                conf_err = conf_ctx.exception
                self.assertEqual(len(ino_first_holder), 1)
                self.assertEqual(len(ino_second_holder), 1)
                self.assertNotEqual(ino_first_holder[0], ino_second_holder[0])

                self.assertEqual(
                    conf_err.failed_check, "outer_profile_files_and_roots"
                )
                fobs_1 = conf_err.files[symlink_fid_1]
                fobs_2 = conf_err.files[symlink_fid_2]

                # First file has the original symlink inode and complete dependencies
                self.assertTrue(fobs_1.dependencies_complete)
                self.assertTrue(fobs_1.verified)
                self.assertEqual(len(fobs_1.symlink_identities), 1)
                self.assertEqual(
                    fobs_1.symlink_identities[0].ino, ino_first_holder[0]
                )
                self.assertEqual(fobs_1.unavailable_symlinks, ())

                # Second file retains its newly measured symlink inode, is incomplete/unverified,
                # and does NOT label the measured edge as unavailable
                self.assertFalse(fobs_2.dependencies_complete)
                self.assertFalse(fobs_2.complete)
                self.assertFalse(fobs_2.verified)
                self.assertEqual(len(fobs_2.symlink_identities), 1)
                self.assertEqual(
                    fobs_2.symlink_identities[0].ino, ino_second_holder[0]
                )
                self.assertEqual(fobs_2.unavailable_symlinks, ())
                self.assertTrue(
                    any(
                        "Symlink identity changed during observation" in e
                        for e in fobs_2.errors
                    )
                )

                # Global observed_symlinks kept the earlier observation, and _build_file_observation
                # projects both files in memory with zero filesystem calls
                partial = conf_err.partial_observation
                assert partial is not None
                self.assertEqual(
                    partial.observed_symlinks[str(alias_symlink)].ino,
                    ino_first_holder[0],
                )
                with (
                    mock.patch(
                        "refmac_diagnostic_profile.os.lstat",
                        side_effect=AssertionError("must not lstat"),
                    ),
                    mock.patch(
                        "refmac_diagnostic_profile.os.stat",
                        side_effect=AssertionError("must not stat"),
                    ),
                    mock.patch(
                        "refmac_diagnostic_profile.os.readlink",
                        side_effect=AssertionError("must not readlink"),
                    ),
                    mock.patch(
                        "refmac_diagnostic_profile.os.open",
                        side_effect=AssertionError("must not open"),
                    ),
                ):
                    reproj_2 = profile_mod._build_file_observation(
                        partial.observed_files[symlink_fid_2],
                        observed_ancestors=partial.observed_ancestors,
                        observed_symlinks=partial.observed_symlinks,
                        file_dependencies=partial.file_dependencies[symlink_fid_2],
                        verified=False,
                    )
                self.assertEqual(
                    reproj_2.symlink_identities[0].ino, ino_second_holder[0]
                )
                self.assertFalse(reproj_2.dependencies_complete)
                self.assertFalse(reproj_2.verified)
                self.assertEqual(reproj_2.unavailable_symlinks, ())
            finally:
                if retained_old_link.is_symlink():
                    os.replace(retained_old_link, alias_symlink)
                _rewrite_manifest_and_profile(fx, base_payload)

    def test_1168_retains_partial_file_read_observations_across_eio_and_initial_size_mismatches(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = _build_synthetic_outer_profile_fixture(Path(tmp))
            root = fx["root"]
            assert isinstance(root, Path)
            profile = fx["profile"]
            assert isinstance(profile, RefmacDiagnosticProfile)
            installed_record = fx["installed_record"]
            assert isinstance(installed_record, dict)
            ccp4_env = fx["ccp4_env"]
            assert isinstance(ccp4_env, dict)
            ev_root = fx["evidence_root"]
            assert isinstance(ev_root, Path)
            base_payload = fx["manifest_payload"]
            assert isinstance(base_payload, dict)
            manifest_path = fx["manifest_path"]
            assert isinstance(manifest_path, Path)

            launcher_fid = base_payload["roles"]["launcher"][0]  # type: ignore[index]
            launcher_row = base_payload["files"][launcher_fid]  # type: ignore[index]
            launcher_path = Path(str(launcher_row["path"]))
            launcher_resolved = launcher_path.resolve(strict=True)
            launcher_bytes = launcher_resolved.read_bytes()
            launcher_st = os.lstat(launcher_resolved)
            orig_manifest_bytes = manifest_path.read_bytes()
            caller_inst_snapshot = copy.deepcopy(installed_record)
            caller_env_snapshot = copy.deepcopy(ccp4_env)

            # 1. Positive control: complete observations only, no PartialFileReadObservation
            pos_val = validate_profile(
                profile, installed_record, ccp4_env, ev_root
            )
            self.assertIsInstance(pos_val.manifest_identity, FileObservation)
            self.assertEqual(len(pos_val.files), 59)
            self.assertTrue(
                all(type(fobs) is FileObservation for _fid, fobs in pos_val.files)
            )
            self.assertEqual(len(pos_val.roots), 3)

            # 2. External declared file (launcher) raises EIO on first read after successful fstat
            real_open = os.open
            real_fdopen = os.fdopen
            first_read_eio = OSError(
                errno.EIO, "synthetic launcher first-read EIO"
            )
            launcher_fds_case2: list[int] = []
            current_fd_to_path_case2: dict[int, str] = {}
            pending_target_fds_case2: set[int] = set()
            injected_paths_case2: list[str] = []

            def track_open_case2(path, flags, *args, **kwargs):
                fd = real_open(path, flags, *args, **kwargs)
                path_str = str(path)
                current_fd_to_path_case2[fd] = path_str
                if path_str == str(launcher_resolved):
                    launcher_fds_case2.append(fd)
                    pending_target_fds_case2.add(fd)
                else:
                    pending_target_fds_case2.discard(fd)
                return fd

            def fdopen_fail_first_read(fd, mode="rb", *args, **kwargs):
                handle = real_fdopen(fd, mode, *args, **kwargs)
                if (
                    fd in pending_target_fds_case2
                    and current_fd_to_path_case2.get(fd)
                    == str(launcher_resolved)
                ):
                    pending_target_fds_case2.remove(fd)
                    injected_paths_case2.append(current_fd_to_path_case2[fd])

                    def raise_eio_first(_n=-1):
                        raise first_read_eio

                    handle.read = raise_eio_first  # type: ignore[method-assign]
                return handle

            with (
                mock.patch(
                    "refmac_diagnostic_profile.os.open",
                    side_effect=track_open_case2,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.fdopen",
                    side_effect=fdopen_fail_first_read,
                ),
            ):
                with self.assertRaises(ProfileValidationError) as eio1_ctx:
                    validate_profile(
                        profile, installed_record, ccp4_env, ev_root
                    )
            self.assertEqual(len(launcher_fds_case2), 1)
            self.assertEqual(injected_paths_case2, [str(launcher_resolved)])
            self.assertEqual(pending_target_fds_case2, set())
            with self.assertRaises(OSError) as closed_ctx:
                os.fstat(launcher_fds_case2[0])
            self.assertEqual(closed_ctx.exception.errno, errno.EBADF)

            eio1_err = eio1_ctx.exception
            self.assertEqual(
                eio1_err.failed_check, "outer_profile_files_and_roots"
            )
            self.assertIs(eio1_err.cause_exception, first_read_eio)
            self.assertIsInstance(
                eio1_err.error_records[0].exception, _PartialFileReadError
            )
            self.assertIs(
                eio1_err.error_records[0].exception.__cause__, first_read_eio
            )
            self.assertEqual(eio1_err.error_type, "OSError")
            self.assertEqual(eio1_err.error_errno, errno.EIO)
            self.assertIsNone(eio1_err.selected_executable)
            self.assertFalse(eio1_err.profile_files_verified)
            self.assertEqual(len(eio1_err.roots), 3)
            self.assertEqual(len(eio1_err.files), 59)

            partial_launcher_1 = eio1_err.files[launcher_fid]
            self.assertIsInstance(
                partial_launcher_1, PartialFileReadObservation
            )
            assert isinstance(partial_launcher_1, PartialFileReadObservation)
            self.assertEqual(partial_launcher_1.path, str(launcher_path))
            self.assertEqual(
                partial_launcher_1.resolved_path, str(launcher_resolved)
            )
            self.assertIsNone(partial_launcher_1.sha256)
            self.assertIsNone(partial_launcher_1.size_bytes)
            self.assertEqual(
                partial_launcher_1.stat_size_bytes, len(launcher_bytes)
            )
            self.assertEqual(partial_launcher_1.streamed_size_bytes, 0)
            self.assertFalse(partial_launcher_1.read_complete)
            self.assertFalse(partial_launcher_1.complete)
            self.assertFalse(partial_launcher_1.verified)
            self.assertTrue(partial_launcher_1.dependencies_complete)
            self.assertEqual(partial_launcher_1.dev, int(launcher_st.st_dev))
            self.assertEqual(partial_launcher_1.ino, int(launcher_st.st_ino))
            self.assertEqual(
                partial_launcher_1.mode, int(launcher_st.st_mode & 0o7777)
            )
            self.assertEqual(partial_launcher_1.uid, int(launcher_st.st_uid))
            self.assertEqual(partial_launcher_1.gid, int(launcher_st.st_gid))
            self.assertGreaterEqual(len(partial_launcher_1.ancestors), 1)
            self.assertGreaterEqual(len(partial_launcher_1.errors), 1)

            # All other 58 files (including files ordered after launcher_fid) are complete FileObservations
            later_fids = [
                fid for fid, _ in eio1_err.files if fid > launcher_fid
            ]
            self.assertGreaterEqual(len(later_fids), 1)
            for fid, fobs in eio1_err.files:
                if fid == launcher_fid:
                    self.assertIsInstance(fobs, PartialFileReadObservation)
                else:
                    self.assertIsInstance(fobs, FileObservation)
                    self.assertTrue(fobs.verified)

            # Private partial_observation stores partial_launcher_1 in partial_files and file_observations,
            # never in observed_files / verified_files / unverified_files
            priv_1 = eio1_err.partial_observation
            assert priv_1 is not None
            self.assertNotIn(launcher_fid, priv_1.observed_files)
            self.assertNotIn(launcher_fid, priv_1.verified_files)
            self.assertNotIn(launcher_fid, priv_1.unverified_files)
            self.assertIn(launcher_fid, priv_1.partial_files)
            self.assertIs(priv_1.partial_files[launcher_fid], partial_launcher_1)
            self.assertIs(
                priv_1.file_observations[launcher_fid], partial_launcher_1
            )

            # Serialization is JSON-safe with null sha256/size_bytes and zero filesystem calls
            with (
                mock.patch(
                    "refmac_diagnostic_profile.os.lstat",
                    side_effect=AssertionError("must not lstat"),
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.stat",
                    side_effect=AssertionError("must not stat"),
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.open",
                    side_effect=AssertionError("must not open"),
                ),
            ):
                prov_1 = eio1_err.to_provenance()
            json.dumps(prov_1)
            pdict_1 = prov_1["files"][launcher_fid]
            self.assertIsNone(pdict_1["sha256"])
            self.assertIsNone(pdict_1["size_bytes"])
            self.assertEqual(pdict_1["stat_size_bytes"], len(launcher_bytes))
            self.assertEqual(pdict_1["streamed_size_bytes"], 0)
            self.assertFalse(pdict_1["read_complete"])
            self.assertFalse(pdict_1["verified"])

            # Verify fallback merge in validate_profile when partial.file_observations is empty
            priv_without_preprojected = _PartialProfileObservation(
                profile=priv_1.profile,
                evidence_root=priv_1.evidence_root,
                evidence_root_ancestor_identities=priv_1.evidence_root_ancestor_identities,
                manifest_observation=priv_1.manifest_observation,
                outer_manifest=priv_1.outer_manifest,
                observed_roots=priv_1.observed_roots,
                observed_files=priv_1.observed_files,
                observed_ancestors=priv_1.observed_ancestors,
                observed_symlinks=priv_1.observed_symlinks,
                errors=priv_1.errors,
                verified_files=priv_1.verified_files,
                unverified_files=priv_1.unverified_files,
                manifest_dependencies=priv_1.manifest_dependencies,
                file_dependencies=priv_1.file_dependencies,
                partial_manifest_observation=priv_1.partial_manifest_observation,
                partial_files=priv_1.partial_files,
                manifest_file_observation=None,
                file_observations={},
                error_records=priv_1.error_records,
            )
            with mock.patch(
                "refmac_diagnostic_profile._validate_and_observe_outer_profile",
                side_effect=_ProfileObservationError(
                    str(eio1_err),
                    partial_observation=priv_without_preprojected,
                    errors=priv_1.errors,
                    failed_check="outer_profile_files_and_roots",
                    error_records=priv_1.error_records,
                ),
            ):
                with self.assertRaises(ProfileValidationError) as fb_ctx:
                    validate_profile(
                        profile, installed_record, ccp4_env, ev_root
                    )
            self.assertEqual(len(fb_ctx.exception.files), 59)
            self.assertIs(
                fb_ctx.exception.files[launcher_fid], partial_launcher_1
            )

            # 3. Same target (launcher) returns one 5-byte chunk followed by EIO on the second read
            chunk_eio = OSError(
                errno.EIO, "synthetic launcher second-chunk EIO"
            )
            launcher_fds_case3: list[int] = []
            current_fd_to_path_case3: dict[int, str] = {}
            pending_target_fds_case3: set[int] = set()
            injected_paths_case3: list[str] = []

            def track_open_case3(path, flags, *args, **kwargs):
                fd = real_open(path, flags, *args, **kwargs)
                path_str = str(path)
                current_fd_to_path_case3[fd] = path_str
                if path_str == str(launcher_resolved):
                    launcher_fds_case3.append(fd)
                    pending_target_fds_case3.add(fd)
                else:
                    pending_target_fds_case3.discard(fd)
                return fd

            def fdopen_fail_second_chunk(fd, mode="rb", *args, **kwargs):
                handle = real_fdopen(fd, mode, *args, **kwargs)
                if (
                    fd in pending_target_fds_case3
                    and current_fd_to_path_case3.get(fd)
                    == str(launcher_resolved)
                ):
                    pending_target_fds_case3.remove(fd)
                    injected_paths_case3.append(current_fd_to_path_case3[fd])
                    orig_read = handle.read
                    calls = 0

                    def read_one_chunk_then_eio(_n=-1):
                        nonlocal calls
                        calls += 1
                        if calls == 1:
                            return orig_read(5)
                        raise chunk_eio

                    handle.read = read_one_chunk_then_eio  # type: ignore[method-assign]
                return handle

            with (
                mock.patch(
                    "refmac_diagnostic_profile.os.open",
                    side_effect=track_open_case3,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.fdopen",
                    side_effect=fdopen_fail_second_chunk,
                ),
            ):
                with self.assertRaises(ProfileValidationError) as eio2_ctx:
                    validate_profile(
                        profile,
                        installed_record,
                        ccp4_env,
                        ev_root,
                        chunk_size=5,
                    )
            self.assertEqual(len(launcher_fds_case3), 1)
            self.assertEqual(injected_paths_case3, [str(launcher_resolved)])
            self.assertEqual(pending_target_fds_case3, set())
            with self.assertRaises(OSError):
                os.fstat(launcher_fds_case3[0])

            eio2_err = eio2_ctx.exception
            self.assertIs(eio2_err.cause_exception, chunk_eio)
            self.assertEqual(eio2_err.error_errno, errno.EIO)
            partial_launcher_2 = eio2_err.files[launcher_fid]
            self.assertIsInstance(
                partial_launcher_2, PartialFileReadObservation
            )
            assert isinstance(partial_launcher_2, PartialFileReadObservation)
            self.assertIsNone(partial_launcher_2.sha256)
            self.assertIsNone(partial_launcher_2.size_bytes)
            self.assertEqual(
                partial_launcher_2.stat_size_bytes, len(launcher_bytes)
            )
            self.assertEqual(partial_launcher_2.streamed_size_bytes, 5)
            self.assertNotEqual(
                partial_launcher_2.streamed_size_bytes,
                partial_launcher_2.stat_size_bytes,
            )
            self.assertFalse(partial_launcher_2.read_complete)
            self.assertFalse(partial_launcher_2.verified)
            self.assertEqual(len(eio2_err.files), 59)
            for fid, fobs in eio2_err.files:
                if fid == launcher_fid:
                    self.assertIsInstance(fobs, PartialFileReadObservation)
                else:
                    self.assertIsInstance(fobs, FileObservation)
                    self.assertTrue(fobs.verified)
            self.assertEqual(len(eio2_err.roots), 3)

            # 4. Pinned manifest read EIO after fstat retains partial manifest without parsing or inspecting refs
            manifest_resolved = manifest_path.resolve(strict=True)
            manifest_eio = OSError(errno.EIO, "synthetic manifest read EIO")
            manifest_fds: list[int] = []
            current_fd_to_path_case4: dict[int, str] = {}
            pending_target_fds_case4: set[int] = set()
            injected_paths_case4: list[str] = []

            def track_open_manifest(path, flags, *args, **kwargs):
                fd = real_open(path, flags, *args, **kwargs)
                path_str = str(path)
                current_fd_to_path_case4[fd] = path_str
                if path_str == str(manifest_resolved):
                    manifest_fds.append(fd)
                    pending_target_fds_case4.add(fd)
                else:
                    pending_target_fds_case4.discard(fd)
                return fd

            def fdopen_fail_manifest_after_chunk(fd, mode="rb", *args, **kwargs):
                handle = real_fdopen(fd, mode, *args, **kwargs)
                if (
                    fd in pending_target_fds_case4
                    and current_fd_to_path_case4.get(fd)
                    == str(manifest_resolved)
                ):
                    pending_target_fds_case4.remove(fd)
                    injected_paths_case4.append(current_fd_to_path_case4[fd])
                    orig_read = handle.read
                    calls = 0

                    def read_16_then_eio(_n=-1):
                        nonlocal calls
                        calls += 1
                        if calls == 1:
                            return orig_read(16)
                        raise manifest_eio

                    handle.read = read_16_then_eio  # type: ignore[method-assign]
                return handle

            with (
                mock.patch(
                    "refmac_diagnostic_profile.os.open",
                    side_effect=track_open_manifest,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.fdopen",
                    side_effect=fdopen_fail_manifest_after_chunk,
                ),
                mock.patch(
                    "refmac_diagnostic_profile._parse_verified_json_bytes",
                    side_effect=AssertionError("must not parse JSON"),
                ) as mocked_parse,
                mock.patch(
                    "refmac_diagnostic_profile._validate_outer_manifest_shape",
                    side_effect=AssertionError("must not validate shape"),
                ) as mocked_shape,
                mock.patch(
                    "refmac_diagnostic_profile._observe_controlled_root",
                    side_effect=AssertionError("must not inspect roots"),
                ) as mocked_root,
            ):
                with self.assertRaises(ProfileValidationError) as meio_ctx:
                    validate_profile(
                        profile,
                        installed_record,
                        ccp4_env,
                        ev_root,
                        chunk_size=16,
                    )
                mocked_parse.assert_not_called()
                mocked_shape.assert_not_called()
                mocked_root.assert_not_called()
            self.assertEqual(len(manifest_fds), 1)
            self.assertEqual(injected_paths_case4, [str(manifest_resolved)])
            self.assertEqual(pending_target_fds_case4, set())
            with self.assertRaises(OSError):
                os.fstat(manifest_fds[0])

            meio_err = meio_ctx.exception
            self.assertEqual(meio_err.failed_check, "manifest_pin")
            self.assertIs(meio_err.cause_exception, manifest_eio)
            self.assertEqual(meio_err.error_errno, errno.EIO)
            self.assertIsInstance(
                meio_err.manifest_identity, PartialFileReadObservation
            )
            assert isinstance(
                meio_err.manifest_identity, PartialFileReadObservation
            )
            self.assertIsNone(meio_err.manifest_identity.sha256)
            self.assertIsNone(meio_err.manifest_identity.size_bytes)
            self.assertEqual(
                meio_err.manifest_identity.stat_size_bytes,
                len(orig_manifest_bytes),
            )
            self.assertEqual(meio_err.manifest_identity.streamed_size_bytes, 16)
            self.assertFalse(meio_err.manifest_identity.read_complete)
            self.assertEqual(len(meio_err.files), 0)
            self.assertEqual(len(meio_err.roots), 0)

            # 5. 3-byte inert manifest with expected 4-byte pin rejects before content read, retaining
            # stat_size_bytes=3, streamed_size_bytes=0, sha256=None, size_bytes=None while requested stays 4
            short_manifest_path = root / "inert-3byte-manifest.json"
            short_manifest_path.write_bytes(b"{}\n")
            short_manifest_st = os.lstat(short_manifest_path)
            self.assertEqual(short_manifest_st.st_size, 3)
            expected_4_pin = FilePin(
                path=str(short_manifest_path),
                sha256=_sha256_bytes(b"{}\n"),
                size_bytes=4,
            )
            short_manifest_prof = RefmacDiagnosticProfile(
                profile_id=profile.profile_id,
                manifest=expected_4_pin,
                executable=profile.executable,
            )
            with (
                mock.patch(
                    "refmac_diagnostic_profile.os.fdopen",
                    side_effect=AssertionError("must not fdopen or stream on initial size mismatch"),
                ) as mocked_fdopen_short,
                mock.patch(
                    "refmac_diagnostic_profile._parse_verified_json_bytes",
                    side_effect=AssertionError("must not parse JSON"),
                ),
                mock.patch(
                    "refmac_diagnostic_profile._validate_outer_manifest_shape",
                    side_effect=AssertionError("must not validate shape"),
                ),
                mock.patch(
                    "refmac_diagnostic_profile._observe_controlled_root",
                    side_effect=AssertionError("must not inspect roots"),
                ),
            ):
                with self.assertRaises(ProfileValidationError) as sz_ctx:
                    validate_profile(
                        short_manifest_prof,
                        installed_record,
                        ccp4_env,
                        ev_root,
                    )
                mocked_fdopen_short.assert_not_called()

            sz_err = sz_ctx.exception
            self.assertEqual(sz_err.failed_check, "manifest_pin")
            self.assertEqual(sz_err.error_type, "ValueError")
            self.assertIsNotNone(sz_err.request)
            assert sz_err.request is not None
            self.assertEqual(sz_err.request.manifest.size_bytes, 4)
            self.assertIsInstance(
                sz_err.manifest_identity, PartialFileReadObservation
            )
            assert isinstance(
                sz_err.manifest_identity, PartialFileReadObservation
            )
            self.assertEqual(
                sz_err.manifest_identity.path, str(short_manifest_path)
            )
            self.assertEqual(sz_err.manifest_identity.stat_size_bytes, 3)
            self.assertEqual(sz_err.manifest_identity.streamed_size_bytes, 0)
            self.assertIsNone(sz_err.manifest_identity.sha256)
            self.assertIsNone(sz_err.manifest_identity.size_bytes)
            self.assertFalse(sz_err.manifest_identity.read_complete)
            self.assertEqual(
                sz_err.manifest_identity.ino, int(short_manifest_st.st_ino)
            )
            sz_prov = sz_err.to_provenance()
            self.assertEqual(sz_prov["requested"]["manifest"]["size_bytes"], 4)
            self.assertEqual(sz_prov["manifest"]["stat_size_bytes"], 3)
            self.assertEqual(sz_prov["manifest"]["streamed_size_bytes"], 0)
            self.assertIsNone(sz_prov["manifest"]["sha256"])
            self.assertIsNone(sz_prov["manifest"]["size_bytes"])
            short_manifest_path.unlink()

            # 6. Declared-file initial size mismatch vs completed-read hash mismatch on launcher
            try:
                # 6a. 3-byte launcher vs expected 38-byte pin: PartialFileReadObservation with stat=3, streamed=0
                launcher_resolved.write_bytes(b"#a\n")
                with self.assertRaises(ProfileValidationError) as dsz_ctx:
                    validate_profile(
                        profile, installed_record, ccp4_env, ev_root
                    )
                dsz_fobs = dsz_ctx.exception.files[launcher_fid]
                self.assertIsInstance(dsz_fobs, PartialFileReadObservation)
                assert isinstance(dsz_fobs, PartialFileReadObservation)
                self.assertEqual(dsz_fobs.stat_size_bytes, 3)
                self.assertEqual(dsz_fobs.streamed_size_bytes, 0)
                self.assertIsNone(dsz_fobs.sha256)
                self.assertIsNone(dsz_fobs.size_bytes)
                self.assertFalse(dsz_fobs.read_complete)
                self.assertEqual(len(dsz_ctx.exception.files), 59)
                self.assertEqual(len(dsz_ctx.exception.roots), 3)

                # 6b. Equal-length (38-byte) modified launcher: completed FileObservation with actual digest/size
                alt_bytes = b"# modified equal-length launcher file\n"
                self.assertEqual(len(alt_bytes), len(launcher_bytes))
                launcher_resolved.write_bytes(alt_bytes)
                with self.assertRaises(ProfileValidationError) as dhash_ctx:
                    validate_profile(
                        profile, installed_record, ccp4_env, ev_root
                    )
                dhash_fobs = dhash_ctx.exception.files[launcher_fid]
                self.assertIsInstance(dhash_fobs, FileObservation)
                assert isinstance(dhash_fobs, FileObservation)
                self.assertEqual(dhash_fobs.sha256, _sha256_bytes(alt_bytes))
                self.assertEqual(dhash_fobs.size_bytes, len(alt_bytes))
                self.assertFalse(dhash_fobs.verified)
            finally:
                launcher_resolved.write_bytes(launcher_bytes)

            # 7. Strict rejection boundaries: PartialFileReadObservation cannot become a FilePin,
            # _PinnedJsonDocument, _CheckedOuterProfileState, or ValidatedProfile
            with self.assertRaisesRegex(
                ValueError, "cannot be converted to a FilePin"
            ):
                partial_launcher_1.as_file_pin()
            with self.assertRaises(ValueError):
                _PinnedJsonDocument(
                    pin=profile.manifest,
                    observation=partial_launcher_1,  # type: ignore[arg-type]
                    payload={},
                )
            with self.assertRaises(ValueError):
                ValidatedProfile(
                    request=pos_val.request,
                    manifest_identity=partial_launcher_1,  # type: ignore[arg-type]
                    files=pos_val.files,
                    roots=pos_val.roots,
                    roles=pos_val.roles,
                    installed_reference=pos_val.installed_reference,
                    selected_executable=pos_val.selected_executable,
                    installed_record_json=pos_val.installed_record_json,
                    expected_environment=pos_val.expected_environment,
                    requested_absences=pos_val.requested_absences,
                    evidence_root=pos_val.evidence_root,
                )
            with self.assertRaises(ValueError):
                ValidatedProfile(
                    request=pos_val.request,
                    manifest_identity=pos_val.manifest_identity,
                    files=((launcher_fid, partial_launcher_1),),  # type: ignore[arg-type]
                    roots=pos_val.roots,
                    roles=pos_val.roles,
                    installed_reference=pos_val.installed_reference,
                    selected_executable=pos_val.selected_executable,
                    installed_record_json=pos_val.installed_record_json,
                    expected_environment=pos_val.expected_environment,
                    requested_absences=pos_val.requested_absences,
                    evidence_root=pos_val.evidence_root,
                )

            # 8. Post-fstat os.fdopen failure and mid-stream handle.read ValueError retain
            # PartialFileReadObservation across both declared-file and manifest-pin paths
            launcher_fdopen_eio = OSError(
                errno.EIO, "synthetic launcher fdopen EIO"
            )
            launcher_fdopen_fds: list[int] = []
            current_fd_to_path_fdopen_l: dict[int, str] = {}
            pending_target_fds_fdopen_l: set[int] = set()
            injected_paths_fdopen_l: list[str] = []

            def track_open_launcher_fdopen(path, flags, *args, **kwargs):
                fd = real_open(path, flags, *args, **kwargs)
                path_str = str(path)
                current_fd_to_path_fdopen_l[fd] = path_str
                if path_str == str(launcher_resolved):
                    launcher_fdopen_fds.append(fd)
                    pending_target_fds_fdopen_l.add(fd)
                else:
                    pending_target_fds_fdopen_l.discard(fd)
                return fd

            def fail_fdopen_for_launcher(fd, mode="rb", *args, **kwargs):
                if (
                    fd in pending_target_fds_fdopen_l
                    and current_fd_to_path_fdopen_l.get(fd)
                    == str(launcher_resolved)
                ):
                    pending_target_fds_fdopen_l.remove(fd)
                    injected_paths_fdopen_l.append(
                        current_fd_to_path_fdopen_l[fd]
                    )
                    raise launcher_fdopen_eio
                return real_fdopen(fd, mode, *args, **kwargs)

            with (
                mock.patch(
                    "refmac_diagnostic_profile.os.open",
                    side_effect=track_open_launcher_fdopen,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.fdopen",
                    side_effect=fail_fdopen_for_launcher,
                ),
            ):
                with self.assertRaises(ProfileValidationError) as lfdo_ctx:
                    validate_profile(
                        profile, installed_record, ccp4_env, ev_root
                    )
            self.assertEqual(len(launcher_fdopen_fds), 1)
            self.assertEqual(
                injected_paths_fdopen_l, [str(launcher_resolved)]
            )
            self.assertEqual(pending_target_fds_fdopen_l, set())
            with self.assertRaises(OSError):
                os.fstat(launcher_fdopen_fds[0])
            lfdo_err = lfdo_ctx.exception
            self.assertEqual(
                lfdo_err.failed_check, "outer_profile_files_and_roots"
            )
            self.assertIs(lfdo_err.cause_exception, launcher_fdopen_eio)
            self.assertEqual(lfdo_err.error_type, "OSError")
            self.assertEqual(lfdo_err.error_errno, errno.EIO)
            lfdo_obs = lfdo_err.files[launcher_fid]
            self.assertIsInstance(lfdo_obs, PartialFileReadObservation)
            assert isinstance(lfdo_obs, PartialFileReadObservation)
            self.assertEqual(lfdo_obs.stat_size_bytes, len(launcher_bytes))
            self.assertEqual(lfdo_obs.streamed_size_bytes, 0)
            self.assertIsNone(lfdo_obs.sha256)
            self.assertIsNone(lfdo_obs.size_bytes)
            self.assertFalse(lfdo_obs.read_complete)
            self.assertFalse(lfdo_obs.verified)
            self.assertEqual(lfdo_obs.ino, int(launcher_st.st_ino))
            self.assertEqual(len(lfdo_err.files), 59)
            for fid, fobs in lfdo_err.files:
                if fid == launcher_fid:
                    self.assertIsInstance(fobs, PartialFileReadObservation)
                else:
                    self.assertIsInstance(fobs, FileObservation)
                    self.assertTrue(fobs.verified)
            self.assertEqual(len(lfdo_err.roots), 3)

            manifest_fdopen_eio = OSError(
                errno.EIO, "synthetic manifest fdopen EIO"
            )
            manifest_fdopen_fds: list[int] = []
            current_fd_to_path_fdopen_m: dict[int, str] = {}
            pending_target_fds_fdopen_m: set[int] = set()
            injected_paths_fdopen_m: list[str] = []

            def track_open_manifest_fdopen(path, flags, *args, **kwargs):
                fd = real_open(path, flags, *args, **kwargs)
                path_str = str(path)
                current_fd_to_path_fdopen_m[fd] = path_str
                if path_str == str(manifest_resolved):
                    manifest_fdopen_fds.append(fd)
                    pending_target_fds_fdopen_m.add(fd)
                else:
                    pending_target_fds_fdopen_m.discard(fd)
                return fd

            def fail_fdopen_for_manifest(fd, mode="rb", *args, **kwargs):
                if (
                    fd in pending_target_fds_fdopen_m
                    and current_fd_to_path_fdopen_m.get(fd)
                    == str(manifest_resolved)
                ):
                    pending_target_fds_fdopen_m.remove(fd)
                    injected_paths_fdopen_m.append(
                        current_fd_to_path_fdopen_m[fd]
                    )
                    raise manifest_fdopen_eio
                return real_fdopen(fd, mode, *args, **kwargs)

            with (
                mock.patch(
                    "refmac_diagnostic_profile.os.open",
                    side_effect=track_open_manifest_fdopen,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.fdopen",
                    side_effect=fail_fdopen_for_manifest,
                ),
                mock.patch(
                    "refmac_diagnostic_profile._parse_verified_json_bytes",
                    side_effect=AssertionError("must not parse JSON"),
                ) as mocked_parse_fdo,
                mock.patch(
                    "refmac_diagnostic_profile._validate_outer_manifest_shape",
                    side_effect=AssertionError("must not validate shape"),
                ) as mocked_shape_fdo,
                mock.patch(
                    "refmac_diagnostic_profile._observe_controlled_root",
                    side_effect=AssertionError("must not inspect roots"),
                ) as mocked_root_fdo,
            ):
                with self.assertRaises(ProfileValidationError) as mfdo_ctx:
                    validate_profile(
                        profile, installed_record, ccp4_env, ev_root
                    )
                mocked_parse_fdo.assert_not_called()
                mocked_shape_fdo.assert_not_called()
                mocked_root_fdo.assert_not_called()
            self.assertEqual(len(manifest_fdopen_fds), 1)
            self.assertEqual(
                injected_paths_fdopen_m, [str(manifest_resolved)]
            )
            self.assertEqual(pending_target_fds_fdopen_m, set())
            with self.assertRaises(OSError):
                os.fstat(manifest_fdopen_fds[0])
            mfdo_err = mfdo_ctx.exception
            self.assertEqual(mfdo_err.failed_check, "manifest_pin")
            self.assertIs(mfdo_err.cause_exception, manifest_fdopen_eio)
            self.assertEqual(mfdo_err.error_type, "OSError")
            self.assertEqual(mfdo_err.error_errno, errno.EIO)
            self.assertIsInstance(
                mfdo_err.manifest_identity, PartialFileReadObservation
            )
            assert isinstance(
                mfdo_err.manifest_identity, PartialFileReadObservation
            )
            self.assertEqual(
                mfdo_err.manifest_identity.stat_size_bytes,
                len(orig_manifest_bytes),
            )
            self.assertEqual(mfdo_err.manifest_identity.streamed_size_bytes, 0)
            self.assertIsNone(mfdo_err.manifest_identity.sha256)
            self.assertIsNone(mfdo_err.manifest_identity.size_bytes)
            self.assertFalse(mfdo_err.manifest_identity.read_complete)
            self.assertEqual(len(mfdo_err.files), 0)
            self.assertEqual(len(mfdo_err.roots), 0)

            launcher_read_val_err = ValueError(
                "synthetic launcher mid-stream read ValueError"
            )
            launcher_rve_fds: list[int] = []
            current_fd_to_path_rve_l: dict[int, str] = {}
            pending_target_fds_rve_l: set[int] = set()
            injected_paths_rve_l: list[str] = []

            def track_open_launcher_rve(path, flags, *args, **kwargs):
                fd = real_open(path, flags, *args, **kwargs)
                path_str = str(path)
                current_fd_to_path_rve_l[fd] = path_str
                if path_str == str(launcher_resolved):
                    launcher_rve_fds.append(fd)
                    pending_target_fds_rve_l.add(fd)
                else:
                    pending_target_fds_rve_l.discard(fd)
                return fd

            def fdopen_launcher_read_val_err(fd, mode="rb", *args, **kwargs):
                handle = real_fdopen(fd, mode, *args, **kwargs)
                if (
                    fd in pending_target_fds_rve_l
                    and current_fd_to_path_rve_l.get(fd)
                    == str(launcher_resolved)
                ):
                    pending_target_fds_rve_l.remove(fd)
                    injected_paths_rve_l.append(current_fd_to_path_rve_l[fd])
                    orig_read = handle.read
                    calls = 0

                    def read_5_then_val_err(_n=-1):
                        nonlocal calls
                        calls += 1
                        if calls == 1:
                            return orig_read(5)
                        raise launcher_read_val_err

                    handle.read = read_5_then_val_err  # type: ignore[method-assign]
                return handle

            with (
                mock.patch(
                    "refmac_diagnostic_profile.os.open",
                    side_effect=track_open_launcher_rve,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.fdopen",
                    side_effect=fdopen_launcher_read_val_err,
                ),
            ):
                with self.assertRaises(ProfileValidationError) as lrve_ctx:
                    validate_profile(
                        profile,
                        installed_record,
                        ccp4_env,
                        ev_root,
                        chunk_size=5,
                    )
            self.assertEqual(len(launcher_rve_fds), 1)
            self.assertEqual(injected_paths_rve_l, [str(launcher_resolved)])
            self.assertEqual(pending_target_fds_rve_l, set())
            with self.assertRaises(OSError):
                os.fstat(launcher_rve_fds[0])
            lrve_err = lrve_ctx.exception
            self.assertEqual(
                lrve_err.failed_check, "outer_profile_files_and_roots"
            )
            self.assertIs(lrve_err.cause_exception, launcher_read_val_err)
            self.assertEqual(lrve_err.error_type, "ValueError")
            self.assertIsNone(lrve_err.error_errno)
            lrve_obs = lrve_err.files[launcher_fid]
            self.assertIsInstance(lrve_obs, PartialFileReadObservation)
            assert isinstance(lrve_obs, PartialFileReadObservation)
            self.assertEqual(lrve_obs.stat_size_bytes, len(launcher_bytes))
            self.assertEqual(lrve_obs.streamed_size_bytes, 5)
            self.assertIsNone(lrve_obs.sha256)
            self.assertIsNone(lrve_obs.size_bytes)
            self.assertFalse(lrve_obs.read_complete)
            self.assertFalse(lrve_obs.verified)
            self.assertEqual(len(lrve_err.files), 59)
            for fid, fobs in lrve_err.files:
                if fid == launcher_fid:
                    self.assertIsInstance(fobs, PartialFileReadObservation)
                else:
                    self.assertIsInstance(fobs, FileObservation)
                    self.assertTrue(fobs.verified)
            self.assertEqual(len(lrve_err.roots), 3)

            manifest_read_val_err = ValueError(
                "synthetic manifest mid-stream read ValueError"
            )
            manifest_rve_fds: list[int] = []
            current_fd_to_path_rve_m: dict[int, str] = {}
            pending_target_fds_rve_m: set[int] = set()
            injected_paths_rve_m: list[str] = []

            def track_open_manifest_rve(path, flags, *args, **kwargs):
                fd = real_open(path, flags, *args, **kwargs)
                path_str = str(path)
                current_fd_to_path_rve_m[fd] = path_str
                if path_str == str(manifest_resolved):
                    manifest_rve_fds.append(fd)
                    pending_target_fds_rve_m.add(fd)
                else:
                    pending_target_fds_rve_m.discard(fd)
                return fd

            def fdopen_manifest_read_val_err(fd, mode="rb", *args, **kwargs):
                handle = real_fdopen(fd, mode, *args, **kwargs)
                if (
                    fd in pending_target_fds_rve_m
                    and current_fd_to_path_rve_m.get(fd)
                    == str(manifest_resolved)
                ):
                    pending_target_fds_rve_m.remove(fd)
                    injected_paths_rve_m.append(current_fd_to_path_rve_m[fd])
                    orig_read = handle.read
                    calls = 0

                    def read_16_then_val_err(_n=-1):
                        nonlocal calls
                        calls += 1
                        if calls == 1:
                            return orig_read(16)
                        raise manifest_read_val_err

                    handle.read = read_16_then_val_err  # type: ignore[method-assign]
                return handle

            with (
                mock.patch(
                    "refmac_diagnostic_profile.os.open",
                    side_effect=track_open_manifest_rve,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.fdopen",
                    side_effect=fdopen_manifest_read_val_err,
                ),
                mock.patch(
                    "refmac_diagnostic_profile._parse_verified_json_bytes",
                    side_effect=AssertionError("must not parse JSON"),
                ) as mocked_parse_rve,
                mock.patch(
                    "refmac_diagnostic_profile._validate_outer_manifest_shape",
                    side_effect=AssertionError("must not validate shape"),
                ) as mocked_shape_rve,
                mock.patch(
                    "refmac_diagnostic_profile._observe_controlled_root",
                    side_effect=AssertionError("must not inspect roots"),
                ) as mocked_root_rve,
            ):
                with self.assertRaises(ProfileValidationError) as mrve_ctx:
                    validate_profile(
                        profile,
                        installed_record,
                        ccp4_env,
                        ev_root,
                        chunk_size=16,
                    )
                mocked_parse_rve.assert_not_called()
                mocked_shape_rve.assert_not_called()
                mocked_root_rve.assert_not_called()
            self.assertEqual(len(manifest_rve_fds), 1)
            self.assertEqual(injected_paths_rve_m, [str(manifest_resolved)])
            self.assertEqual(pending_target_fds_rve_m, set())
            with self.assertRaises(OSError):
                os.fstat(manifest_rve_fds[0])
            mrve_err = mrve_ctx.exception
            self.assertEqual(mrve_err.failed_check, "manifest_pin")
            self.assertIs(mrve_err.cause_exception, manifest_read_val_err)
            self.assertEqual(mrve_err.error_type, "ValueError")
            self.assertIsNone(mrve_err.error_errno)
            self.assertIsInstance(
                mrve_err.manifest_identity, PartialFileReadObservation
            )
            assert isinstance(
                mrve_err.manifest_identity, PartialFileReadObservation
            )
            self.assertEqual(
                mrve_err.manifest_identity.stat_size_bytes,
                len(orig_manifest_bytes),
            )
            self.assertEqual(mrve_err.manifest_identity.streamed_size_bytes, 16)
            self.assertIsNone(mrve_err.manifest_identity.sha256)
            self.assertIsNone(mrve_err.manifest_identity.size_bytes)
            self.assertFalse(mrve_err.manifest_identity.read_complete)
            self.assertEqual(len(mrve_err.files), 0)
            self.assertEqual(len(mrve_err.roots), 0)

            # Verify caller inputs and fixture bytes remained completely untouched
            self.assertEqual(installed_record, caller_inst_snapshot)
            self.assertEqual(ccp4_env, caller_env_snapshot)
            self.assertEqual(manifest_path.read_bytes(), orig_manifest_bytes)
            self.assertEqual(launcher_resolved.read_bytes(), launcher_bytes)

    def test_1181_profile_validation_error_evidence_is_deeply_immutable_and_provenance_is_detached(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = _build_synthetic_outer_profile_fixture(Path(tmp))
            profile = fx["profile"]
            assert isinstance(profile, RefmacDiagnosticProfile)
            installed_record = fx["installed_record"]
            assert isinstance(installed_record, dict)
            ccp4_env = fx["ccp4_env"]
            assert isinstance(ccp4_env, dict)
            ev_root = fx["evidence_root"]
            assert isinstance(ev_root, Path)
            base_payload = fx["manifest_payload"]
            assert isinstance(base_payload, dict)

            launcher_fid = base_payload["roles"]["launcher"][0]  # type: ignore[index]
            launcher_row = base_payload["files"][launcher_fid]  # type: ignore[index]
            launcher_resolved = Path(str(launcher_row["path"])).resolve(
                strict=True
            )

            real_open = os.open
            real_fdopen = os.fdopen
            eio_cause = OSError(errno.EIO, "synthetic #1181 mid-stream EIO")
            current_fd_to_path: dict[int, str] = {}
            pending_target_fds: set[int] = set()

            def track_open(path, flags, *args, **kwargs):
                fd = real_open(path, flags, *args, **kwargs)
                path_str = str(path)
                current_fd_to_path[fd] = path_str
                if path_str == str(launcher_resolved):
                    pending_target_fds.add(fd)
                else:
                    pending_target_fds.discard(fd)
                return fd

            def fdopen_with_eio(fd, mode="rb", *args, **kwargs):
                handle = real_fdopen(fd, mode, *args, **kwargs)
                if (
                    fd in pending_target_fds
                    and current_fd_to_path.get(fd) == str(launcher_resolved)
                ):
                    pending_target_fds.remove(fd)
                    orig_read = handle.read
                    calls = 0

                    def read_5_then_eio(_n=-1):
                        nonlocal calls
                        calls += 1
                        if calls == 1:
                            return orig_read(5)
                        raise eio_cause

                    handle.read = read_5_then_eio  # type: ignore[method-assign]
                return handle

            mutable_installed = copy.deepcopy(installed_record)
            mutable_env = copy.deepcopy(ccp4_env)

            with (
                mock.patch(
                    "refmac_diagnostic_profile.os.open",
                    side_effect=track_open,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.fdopen",
                    side_effect=fdopen_with_eio,
                ),
            ):
                with self.assertRaises(ProfileValidationError) as ctx:
                    validate_profile(
                        profile,
                        mutable_installed,
                        mutable_env,
                        ev_root,
                        chunk_size=5,
                    )

            err = ctx.exception
            self.assertEqual(len(err.files), 59)
            self.assertEqual(len(err.roots), 3)
            self.assertIs(err.cause_exception, eio_cause)
            self.assertEqual(err.error_type, "OSError")
            self.assertEqual(err.error_errno, errno.EIO)
            self.assertIsInstance(
                err.files[launcher_fid], PartialFileReadObservation
            )

            initial_prov = copy.deepcopy(err.to_provenance())
            self.assertEqual(len(initial_prov["files"]), 59)

            # 1. Direct writes and deletions to all public evidence fields and internal _payload fail with AttributeError
            readonly_attrs = (
                "failed_check",
                "request",
                "profile_id",
                "subject_id",
                "manifest_identity",
                "files",
                "roots",
                "roles",
                "installed_reference",
                "selected_executable",
                "profile_files_verified",
                "runtime_image_coverage",
                "installed_record_json",
                "installed_record",
                "expected_environment",
                "requested_absences",
                "evidence_root",
                "cause_exception",
                "wrapper_message",
                "error_type",
                "error_message",
                "error_errno",
                "errors",
                "error_records",
                "partial_observation",
                "_payload",
                "arbitrary_new_attribute",
            )
            for attr in readonly_attrs:
                with self.subTest(write_attr=attr):
                    with self.assertRaises(AttributeError):
                        setattr(err, attr, ())
                with self.subTest(delete_attr=attr):
                    with self.assertRaises(AttributeError):
                        delattr(err, attr)

            # 2. Nested field mutations on payload, request, observations, tables,installed_record, and carrier exceptions fail
            with self.assertRaises(AttributeError):
                err._payload.files = _FrozenPairTable(())  # type: ignore[misc]
            with self.assertRaises(AttributeError):
                del err._payload.files  # type: ignore[misc]
            assert err.request is not None
            with self.assertRaises(AttributeError):
                err.request.profile_id = "tampered"  # type: ignore[misc]
            with self.assertRaises(AttributeError):
                err.request.manifest.sha256 = "0" * 64  # type: ignore[misc]
            assert err.manifest_identity is not None
            with self.assertRaises(AttributeError):
                err.manifest_identity.verified = True  # type: ignore[misc]
            with self.assertRaises(AttributeError):
                err.manifest_identity.ancestors[0].ino = 1  # type: ignore[misc]
            with self.assertRaises(TypeError):
                err.files[launcher_fid] = err.manifest_identity  # type: ignore[index]
            with self.assertRaises(TypeError):
                del err.files[launcher_fid]  # type: ignore[attr-defined]
            with self.assertRaises(AttributeError):
                err.files.extra = 1  # type: ignore[attr-defined]
            with self.assertRaises(AttributeError):
                del err.files.extra  # type: ignore[attr-defined]
            with self.assertRaises(AttributeError):
                err.files[launcher_fid].streamed_size_bytes = 999  # type: ignore[misc,union-attr]
            other_fid = next(
                fid for fid, _ in err.files if fid != launcher_fid
            )
            with self.assertRaises(AttributeError):
                err.files[other_fid].verified = False  # type: ignore[misc]
            with self.assertRaises(TypeError):
                err.roots["vendor"] = err.roots["prepared"]  # type: ignore[index]
            with self.assertRaises(AttributeError):
                err.roots["vendor"].verified = False  # type: ignore[misc]
            with self.assertRaises(AttributeError):
                err.roots["vendor"].members[0].file_id = "tampered"  # type: ignore[misc]
            with self.assertRaises(AttributeError):
                err.roots["vendor"].members.extra = 1  # type: ignore[attr-defined]
            with self.assertRaises(AttributeError):
                del err.roots["vendor"].members.extra  # type: ignore[attr-defined]
            with self.assertRaises(TypeError):
                err.roles["launcher"] = ("tampered",)  # type: ignore[index]
            assert err.installed_reference is not None
            with self.assertRaises(AttributeError):
                err.installed_reference.sha256 = "0" * 64  # type: ignore[misc]
            assert err.installed_record is not None
            with self.assertRaises(TypeError):
                err.installed_record["configured_installation_prefix"] = "/tampered"  # type: ignore[index]
            with self.assertRaises(TypeError):
                err.installed_record["setup_script"]["sha256"] = "0" * 64  # type: ignore[index]
            with self.assertRaises(TypeError):
                err.expected_environment["CCP4"] = "/tampered"  # type: ignore[index]
            assert err.partial_observation is not None
            with self.assertRaises(AttributeError):
                err.partial_observation.errors = ()  # type: ignore[misc]
            with self.assertRaises(TypeError):
                err.partial_observation.partial_files[launcher_fid] = None  # type: ignore[index]
            with self.assertRaises(AttributeError):
                err.error_records[0].stage = "tampered"  # type: ignore[misc]
            with self.assertRaises(AttributeError):
                err.error_records[0].error_type = "TamperedError"  # type: ignore[misc]
            with self.assertRaises(AttributeError):
                err.__cause__.partial_observation = None  # type: ignore[union-attr]
            with self.assertRaises(AttributeError):
                err.error_records[0].exception.observation = None  # type: ignore[attr-defined]

            # 3. Caller-owned mapping mutations after failure do not affect retained evidence or provenance
            mutable_installed["configured_installation_prefix"] = "/mutated/prefix"
            mutable_installed["setup_script"]["sha256"] = "f" * 64
            mutable_installed["bound_ccp4_configuration"]["CCP4"] = "/mutated/ccp4"
            mutable_env["CCP4"] = "/mutated/ccp4"
            mutable_env["NEW_KEY"] = "mutated"

            self.assertEqual(
                err.installed_record["configured_installation_prefix"],
                installed_record["configured_installation_prefix"],
            )
            self.assertEqual(
                err.installed_record["setup_script"]["sha256"],
                installed_record["setup_script"]["sha256"],
            )
            self.assertEqual(
                err.expected_environment["CCP4"], ccp4_env["CCP4"]
            )

            # 4. Mutating a returned provenance dict leaves subsequent to_provenance() calls and retained state unchanged
            mutated_prov = err.to_provenance()
            mutated_prov["profile_id"] = "tampered"
            mutated_prov["profile_files_verified"] = True
            mutated_prov["selected_executable"] = {"path": "/fake"}
            mutated_prov["requested"]["manifest"]["sha256"] = "0" * 64
            mutated_prov["installed_reference"]["sha256"] = "0" * 64
            mutated_prov["installed_record"]["setup_script"]["sha256"] = "0" * 64
            mutated_prov["manifest"]["sha256"] = "0" * 64
            mutated_prov["files"].clear()
            mutated_prov["roots"]["vendor"]["members"].clear()
            mutated_prov["roles"]["launcher"].append("extra")
            mutated_prov["expected_environment"]["CCP4"] = "/tampered"
            mutated_prov["requested_absences"].append("EXTRA_ABSENT")
            mutated_prov["failed_check"] = "tampered"
            mutated_prov["error"]["type"] = "TamperedError"
            mutated_prov["error"]["errno"] = 999
            mutated_prov["errors"].clear()

            fresh_prov = err.to_provenance()
            self.assertEqual(fresh_prov, initial_prov)
            self.assertEqual(len(err.files), 59)
            self.assertEqual(len(fresh_prov["files"]), 59)

            # 5. Raising and chaining the same exception works normally and preserves #1179 cause/errno/type metadata
            # even if caller mutates Exception.args or cause_exception.args/errno afterwards
            try:
                try:
                    raise err
                except ProfileValidationError as caught_once:
                    self.assertIs(caught_once, err)
                    raise RuntimeError("outer wrapper") from caught_once
            except RuntimeError as wrapped_err:
                self.assertIs(wrapped_err.__cause__, err)

            orig_err_msg = err.error_message
            orig_wrap_msg = err.wrapper_message
            err.args = ("caller mutated wrapper args",)
            eio_cause.args = (errno.ENOENT, "caller mutated cause args")
            eio_cause.errno = errno.ENOENT
            self.assertEqual(err.error_type, "OSError")
            self.assertEqual(err.error_errno, errno.EIO)
            self.assertEqual(err.error_message, orig_err_msg)
            self.assertEqual(err.wrapper_message, orig_wrap_msg)
            self.assertEqual(err.error_records[0].error_type, "OSError")
            self.assertEqual(err.error_records[0].error_errno, errno.EIO)
            self.assertEqual(
                err.error_records[0].to_dict(),
                {
                    "stage": "outer_profile_files_and_roots",
                    "message": orig_wrap_msg,
                    "type": "OSError",
                    "errno": errno.EIO,
                },
            )
            self.assertEqual(err.to_provenance(), initial_prov)


class TestTask734PrivatePostflightObservations(unittest.TestCase):
    """Focused synthetic tests for Task 734 private postflight observation collection and cause distinction."""

    def test_private_reobserve_distinguishes_comparison_mismatches_from_actual_observation_causes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = _build_synthetic_outer_profile_fixture(Path(tmp))
            root = fx["root"]
            assert isinstance(root, Path)
            trees = fx["trees"]
            assert isinstance(trees, dict)
            profile = fx["profile"]
            assert isinstance(profile, RefmacDiagnosticProfile)
            base_payload = fx["manifest_payload"]
            assert isinstance(base_payload, dict)

            state = _validate_and_observe_outer_profile(profile)

            # 1. Unchanged state: verified=True, no errors, no causes
            unchanged = _reobserve_outer_profile_state(state)
            self.assertTrue(unchanged.verified)
            self.assertEqual(unchanged.errors, ())
            self.assertEqual(unchanged.manifest_errors, ())
            self.assertIsNone(unchanged.manifest_cause)
            self.assertIsNone(unchanged.partial_manifest_observation)
            self.assertEqual(len(unchanged.partial_files), 0)
            self.assertEqual(len(unchanged.file_errors), 0)
            self.assertEqual(len(unchanged.file_causes), 0)
            self.assertEqual(len(unchanged.root_errors), 0)
            self.assertEqual(len(unchanged.root_causes), 0)
            self.assertEqual(len(unchanged.observation_causes), 0)
            self.assertIsInstance(unchanged.manifest_file_observation, FileObservation)
            self.assertTrue(unchanged.manifest_file_observation.verified)
            self.assertEqual(
                set(unchanged.file_observations.keys()),
                set(state.observed_files.keys()),
            )

            # 2. Complete same-byte file inode replacement and same-byte root directory replacement are comparison-only (None cause)
            qc_path = root / "support" / "qc-item.json"
            qc_fid = next(
                fid
                for fid, row in base_payload["files"].items()  # type: ignore[union-attr]
                if row["path"] == str(qc_path)
            )
            orig_qc_bytes = qc_path.read_bytes()
            orig_qc_ino = qc_path.stat().st_ino
            replacement_tmp = root / "support" / "qc-item.new-inode"
            replacement_tmp.write_bytes(orig_qc_bytes)
            qc_backup = root / "support" / "qc-item.orig-inode"
            os.link(qc_path, qc_backup)
            os.replace(replacement_tmp, qc_path)
            self.assertNotEqual(qc_path.stat().st_ino, orig_qc_ino)

            prepared_dir = trees["prepared"]
            orig_prepared_ino = prepared_dir.stat().st_ino
            prepared_backup = root / "prepared-orig-backup"
            os.rename(prepared_dir, prepared_backup)
            prepared_dir.mkdir(mode=prepared_backup.stat().st_mode & 0o777)
            for member in sorted(prepared_backup.iterdir()):
                if member.is_file():
                    (prepared_dir / member.name).write_bytes(member.read_bytes())
            self.assertNotEqual(prepared_dir.stat().st_ino, orig_prepared_ino)
            try:
                same_byte = _reobserve_outer_profile_state(state)
                self.assertFalse(same_byte.verified)
                self.assertIn(qc_fid, same_byte.unverified_files)
                self.assertIn(qc_fid, same_byte.file_errors)
                self.assertIn(qc_fid, same_byte.file_causes)
                self.assertIsNone(same_byte.file_causes[qc_fid])
                self.assertIsNone(
                    same_byte.observation_causes[f"profile:file:{qc_fid}"]
                )
                self.assertIn("prepared", same_byte.failed_roots)
                self.assertNotIn("prepared", same_byte.incomplete_roots)
                self.assertTrue(same_byte.observed_roots["prepared"].scan_complete)
                self.assertFalse(same_byte.observed_roots["prepared"].verified)
                self.assertIn("prepared", same_byte.root_errors)
                self.assertIn("prepared", same_byte.root_causes)
                self.assertIsNone(same_byte.root_causes["prepared"])
                self.assertIsNone(
                    same_byte.observation_causes["profile:root:prepared"]
                )
            finally:
                for member in list(prepared_dir.iterdir()):
                    member.unlink()
                prepared_dir.rmdir()
                os.rename(prepared_backup, prepared_dir)
                os.replace(qc_backup, qc_path)
                self.assertEqual(qc_path.stat().st_ino, orig_qc_ino)
                self.assertEqual(prepared_dir.stat().st_ino, orig_prepared_ino)

            # 3. Multi-error continuation: missing early file (FileNotFoundError), later equal-length corrupt file (comparison-only),
            # longer size-mismatched file (is_size_mismatch=True -> comparison-only), post-fstat read OSError/ValueError
            # (is_size_mismatch=False -> actual cause + PartialFileReadObservation), and child scan failure (PermissionError + completed members)
            external_fids = sorted(
                fid
                for fid, fobs in state.observed_files.items()
                if fid not in state.outer_manifest.tree_member_ids
                and not fobs.symlinks
                and ".." not in Path(fobs.path).parts
            )
            self.assertGreaterEqual(len(external_fids), 4)
            missing_fid = external_fids[0]
            corrupt_same_len_fid = external_fids[1]
            longer_size_fid = external_fids[2]
            io_read_fid = external_fids[3]

            missing_path = Path(state.observed_files[missing_fid].path)
            corrupt_path = Path(state.observed_files[corrupt_same_len_fid].path)
            longer_path = Path(state.observed_files[longer_size_fid].path)
            io_read_path = Path(state.observed_files[io_read_fid].path)

            missing_backup = root / "missing.orig-inode"
            os.link(missing_path, missing_backup)
            missing_path.unlink()

            orig_corrupt_bytes = corrupt_path.read_bytes()
            corrupt_backup = root / "corrupt.orig-inode"
            os.link(corrupt_path, corrupt_backup)
            corrupt_tmp = root / "corrupt.same-len-tmp"
            corrupt_tmp.write_bytes(
                (b"X" if orig_corrupt_bytes[:1] != b"X" else b"Y")
                + orig_corrupt_bytes[1:]
            )
            os.replace(corrupt_tmp, corrupt_path)

            longer_backup = root / "longer.orig-inode"
            os.link(longer_path, longer_backup)
            longer_tmp = root / "longer.size-tmp"
            longer_tmp.write_bytes(longer_path.read_bytes() + b"extra-longer-bytes\n")
            os.replace(longer_tmp, longer_path)

            io_stat = io_read_path.stat()
            target_dev_ino = (int(io_stat.st_dev), int(io_stat.st_ino))
            injected_eio = OSError(errno.EIO, "simulated post-fstat stream read error")
            injected_walk_perm = PermissionError(
                errno.EACCES, "simulated child directory walk permission denied"
            )
            real_fdopen = os.fdopen
            real_walk = os.walk

            class _FaultAfterFirstByteReader:
                def __init__(self, inner) -> None:
                    self._inner = inner
                    self._calls = 0

                def __enter__(self):
                    self._inner.__enter__()
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return self._inner.__exit__(exc_type, exc, tb)

                def read(self, size: int = -1) -> bytes:
                    self._calls += 1
                    if self._calls == 1:
                        return self._inner.read(1)
                    raise injected_eio

                def fileno(self) -> int:
                    return self._inner.fileno()

            def fault_fdopen(fd: int, *args, **kwargs):
                st = os.fstat(fd)
                fh = real_fdopen(fd, *args, **kwargs)
                if (int(st.st_dev), int(st.st_ino)) == target_dev_ino:
                    return _FaultAfterFirstByteReader(fh)
                return fh

            def fault_vendor_child_walk(top, topdown=True, onerror=None, followlinks=False):
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
                                onerror(injected_walk_perm)
                            return
                else:
                    yield from real_walk(
                        top,
                        topdown=topdown,
                        onerror=onerror,
                        followlinks=followlinks,
                    )

            try:
                with (
                    mock.patch(
                        "refmac_diagnostic_profile.os.fdopen",
                        side_effect=fault_fdopen,
                    ),
                    mock.patch(
                        "refmac_diagnostic_profile.os.walk",
                        side_effect=fault_vendor_child_walk,
                    ),
                ):
                    multi = _reobserve_outer_profile_state(state, chunk_size=4)

                self.assertFalse(multi.verified)
                # Manifest and unaffected roots/files still observed and verified
                self.assertIsNotNone(multi.manifest_observation)
                self.assertIsNone(multi.manifest_cause)
                self.assertIn("prepared", multi.verified_roots)
                self.assertIn("build", multi.verified_roots)
                self.assertGreater(len(multi.verified_files), 20)

                # Early missing file: absent from observed_files and partial_files, FileNotFoundError cause preserved
                self.assertNotIn(missing_fid, multi.observed_files)
                self.assertNotIn(missing_fid, multi.partial_files)
                self.assertNotIn(missing_fid, multi.file_observations)
                self.assertIsInstance(
                    multi.file_causes[missing_fid], FileNotFoundError
                )
                self.assertEqual(
                    getattr(multi.file_causes[missing_fid], "errno", None),
                    errno.ENOENT,
                )

                # Equal-length corrupt file: completed observation retained, comparison-only (None cause)
                self.assertIn(corrupt_same_len_fid, multi.observed_files)
                self.assertIn(corrupt_same_len_fid, multi.unverified_files)
                self.assertIsNone(multi.file_causes[corrupt_same_len_fid])
                self.assertIsInstance(
                    multi.file_observations[corrupt_same_len_fid], FileObservation
                )
                self.assertFalse(
                    multi.file_observations[corrupt_same_len_fid].verified
                )

                # Longer size-mismatched file: PartialFileReadObservation retained via is_size_mismatch=True, comparison-only (None cause)
                self.assertNotIn(longer_size_fid, multi.observed_files)
                self.assertIn(longer_size_fid, multi.partial_files)
                self.assertEqual(
                    multi.partial_files[longer_size_fid].streamed_size_bytes, 0
                )
                self.assertIsNone(multi.file_causes[longer_size_fid])

                # Post-fstat read failure: PartialFileReadObservation retained with streamed_size_bytes=1 and exact OSError cause
                self.assertNotIn(io_read_fid, multi.observed_files)
                self.assertIn(io_read_fid, multi.partial_files)
                p_obs = multi.partial_files[io_read_fid]
                self.assertEqual(p_obs.stat_size_bytes, int(io_stat.st_size))
                self.assertEqual(p_obs.streamed_size_bytes, 1)
                self.assertIsNone(p_obs.sha256)
                self.assertIsNone(p_obs.size_bytes)
                self.assertFalse(p_obs.read_complete)
                self.assertIs(multi.file_causes[io_read_fid], injected_eio)
                self.assertIs(
                    multi.observation_causes[f"profile:file:{io_read_fid}"],
                    injected_eio,
                )

                # Child scan failure on vendor: scan_complete=False, retains actual root identity and completed members, preserves exact PermissionError
                self.assertIn("vendor", multi.incomplete_roots)
                self.assertIn("vendor", multi.failed_roots)
                vendor_inv = multi.observed_roots["vendor"]
                self.assertFalse(vendor_inv.scan_complete)
                self.assertFalse(vendor_inv.verified)
                self.assertEqual(
                    vendor_inv.directory_identity,
                    state.observed_roots["vendor"].directory_identity,
                )
                self.assertEqual(
                    vendor_inv.ancestor_identities,
                    state.observed_roots["vendor"].ancestor_identities,
                )
                self.assertGreaterEqual(len(vendor_inv.member_pins), 1)
                self.assertTrue(
                    set(vendor_inv.member_pins.keys()).issubset(
                        set(state.observed_roots["vendor"].member_pins.keys())
                    )
                )
                self.assertIs(multi.root_causes["vendor"], injected_walk_perm)
                self.assertIs(
                    multi.observation_causes["profile:root:vendor"],
                    injected_walk_perm,
                )
            finally:
                os.replace(missing_backup, missing_path)
                os.replace(corrupt_backup, corrupt_path)
                os.replace(longer_backup, longer_path)

    def test_739_retargeted_symlink_sole_observer_new_ancestor_and_root_ancestor_prefix_retention(
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
            profile = fx["profile"]
            assert isinstance(profile, RefmacDiagnosticProfile)
            base_payload = fx["manifest_payload"]
            assert isinstance(base_payload, dict)

            state = _validate_and_observe_outer_profile(profile)
            alias_fid = next(
                fid
                for fid, row in base_payload["files"].items()  # type: ignore[union-attr]
                if row["path"] == str(alias_symlink)
            )
            orig_target = os.readlink(alias_symlink)
            orig_bytes = alias_symlink.read_bytes()

            # 1 & 3. Retarget alias_symlink into a new parent directory support/new-targets/python:
            # sole symlink observer is called once (no fallback second lstat/readlink), retains actual target,
            # retains new parent directory in raw AND projected observations with complete dependencies,
            # and keeps comparison mismatch cause as None.
            new_target_dir = root / "support" / "new-targets"
            new_target_file = new_target_dir / "python"
            new_target_dir.mkdir(parents=True, exist_ok=True)
            new_target_file.write_bytes(orig_bytes)
            alias_symlink.unlink()
            os.symlink("new-targets/python", alias_symlink)

            real_observe_symlink = profile_mod._observe_symlink_identity
            symlink_observer_calls: list[tuple[str, bool]] = []

            def spy_observe_symlink(
                edge: _SymlinkEdge,
                *,
                check_expected_target: bool = True,
            ):
                symlink_observer_calls.append(
                    (edge.path, check_expected_target)
                )
                return real_observe_symlink(
                    edge,
                    check_expected_target=check_expected_target,
                )

            try:
                with mock.patch(
                    "refmac_diagnostic_profile._observe_symlink_identity",
                    side_effect=spy_observe_symlink,
                ):
                    retargeted = _reobserve_outer_profile_state(state)

                self.assertFalse(retargeted.verified)
                self.assertEqual(
                    symlink_observer_calls,
                    [(str(alias_symlink), False)],
                )
                self.assertIn(str(alias_symlink), retargeted.observed_symlinks)
                self.assertEqual(
                    retargeted.observed_symlinks[str(alias_symlink)].target,
                    "new-targets/python",
                )
                self.assertIsNone(
                    retargeted.symlink_causes[str(alias_symlink)]
                )
                self.assertIsNone(
                    retargeted.observation_causes[
                        f"profile:symlink:{alias_symlink}"
                    ]
                )
                self.assertIsNone(retargeted.file_causes[alias_fid])
                self.assertIsNone(
                    retargeted.observation_causes[f"profile:file:{alias_fid}"]
                )

                raw_anc_paths = {
                    d.path
                    for d in retargeted.observed_files[
                        alias_fid
                    ].traversed_directory_identities
                }
                dep_anc_paths = {
                    d.path
                    for d in retargeted.file_dependencies[alias_fid].ancestors
                }
                proj_obs = retargeted.file_observations[alias_fid]
                self.assertIsInstance(proj_obs, FileObservation)
                proj_anc_paths = {d.path for d in proj_obs.ancestors}
                self.assertIn(str(new_target_dir), raw_anc_paths)
                self.assertIn(str(new_target_dir), dep_anc_paths)
                self.assertIn(str(new_target_dir), proj_anc_paths)
                self.assertIn(str(new_target_dir), retargeted.observed_ancestors)
                self.assertTrue(
                    retargeted.file_dependencies[alias_fid].complete
                )
                self.assertEqual(
                    retargeted.file_dependencies[alias_fid].errors, ()
                )
                self.assertTrue(proj_obs.dependencies_complete)
                self.assertFalse(proj_obs.verified)
                self.assertEqual(
                    len(proj_obs.symlink_identities), 1
                )
                self.assertEqual(
                    proj_obs.symlink_identities[0].target,
                    "new-targets/python",
                )

                # 1b. Actual readlink failure inside sole symlink observer preserves exact OSError cause
                # and propagates it to symlink_causes, file_causes, and observation_causes
                injected_sym_eio = OSError(
                    errno.EIO,
                    "simulated symlink readlink failure in sole observer",
                    str(alias_symlink),
                )
                real_readlink = os.readlink
                in_step5 = {"active": False, "injections": 0}

                def observe_sym_trigger(
                    edge: _SymlinkEdge,
                    *,
                    check_expected_target: bool = True,
                ):
                    if edge.path == str(alias_symlink):
                        in_step5["active"] = True
                    try:
                        return real_observe_symlink(
                            edge,
                            check_expected_target=check_expected_target,
                        )
                    finally:
                        in_step5["active"] = False

                def readlink_fail_in_step5(path, *args, **kwargs):
                    if (
                        in_step5["active"]
                        and os.fsdecode(path) == str(alias_symlink)
                    ):
                        in_step5["injections"] += 1
                        raise injected_sym_eio
                    return real_readlink(path, *args, **kwargs)

                with (
                    mock.patch(
                        "refmac_diagnostic_profile._observe_symlink_identity",
                        side_effect=observe_sym_trigger,
                    ),
                    mock.patch(
                        "refmac_diagnostic_profile.os.readlink",
                        side_effect=readlink_fail_in_step5,
                    ),
                ):
                    sym_failed = _reobserve_outer_profile_state(state)

                self.assertEqual(in_step5["injections"], 1)
                self.assertFalse(sym_failed.verified)
                self.assertNotIn(
                    str(alias_symlink), sym_failed.observed_symlinks
                )
                self.assertIs(
                    sym_failed.symlink_causes[str(alias_symlink)],
                    injected_sym_eio,
                )
                self.assertIs(
                    sym_failed.observation_causes[
                        f"profile:symlink:{alias_symlink}"
                    ],
                    injected_sym_eio,
                )
                self.assertIs(
                    sym_failed.file_causes[alias_fid], injected_sym_eio
                )
                self.assertIs(
                    sym_failed.observation_causes[f"profile:file:{alias_fid}"],
                    injected_sym_eio,
                )
                self.assertFalse(
                    sym_failed.file_dependencies[alias_fid].complete
                )
                self.assertFalse(
                    sym_failed.file_observations[alias_fid].dependencies_complete
                )
                self.assertFalse(
                    sym_failed.file_observations[alias_fid].verified
                )
            finally:
                if alias_symlink.exists() or alias_symlink.is_symlink():
                    alias_symlink.unlink()
                os.symlink(orig_target, alias_symlink)
                if new_target_file.exists():
                    new_target_file.unlink()
                if new_target_dir.exists():
                    new_target_dir.rmdir()

            # 2. Controlled root failure AFTER successful root identity and non-empty ancestor prefix
            # retains incomplete_inv with exact root identity, completed ancestor prefix, scan_complete=False,
            # and exact PermissionError cause while continuing later roots and files.
            # Start a separate experiment with a fresh admission baseline after fixture restoration.
            state = _validate_and_observe_outer_profile(profile)
            vendor_dir = trees["vendor"]
            parent_dir = root
            grandparent_dir = root.parent
            injected_anc_perm = PermissionError(
                errno.EACCES,
                "simulated root ancestor lstat failure after root and parent observed",
                str(grandparent_dir),
            )
            real_dir_obs = profile_mod._observe_directory_identity
            real_lstat = os.lstat
            anc_probe_state = {
                "vendor_and_parent_observed": False,
                "seen_vendor": False,
                "injections": 0,
            }

            def dir_obs_tracker(path_str: str, *args, **kwargs):
                val = real_dir_obs(path_str, *args, **kwargs)
                if str(path_str) == str(vendor_dir):
                    anc_probe_state["seen_vendor"] = True
                elif (
                    anc_probe_state["seen_vendor"]
                    and str(path_str) == str(parent_dir)
                ):
                    anc_probe_state["vendor_and_parent_observed"] = True
                return val

            def lstat_fail_on_grandparent(path, *args, **kwargs):
                if (
                    anc_probe_state["vendor_and_parent_observed"]
                    and anc_probe_state["injections"] == 0
                    and os.fsdecode(path) == str(grandparent_dir)
                ):
                    anc_probe_state["injections"] += 1
                    raise injected_anc_perm
                return real_lstat(path, *args, **kwargs)

            with (
                mock.patch(
                    "refmac_diagnostic_profile._observe_directory_identity",
                    side_effect=dir_obs_tracker,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.lstat",
                    side_effect=lstat_fail_on_grandparent,
                ),
            ):
                root_anc_failed = _reobserve_outer_profile_state(state)

            self.assertEqual(anc_probe_state["injections"], 1)
            self.assertFalse(root_anc_failed.verified)
            self.assertIn("vendor", root_anc_failed.observed_roots)
            self.assertIn("vendor", root_anc_failed.incomplete_roots)
            self.assertIn("vendor", root_anc_failed.failed_roots)
            retained_vendor = root_anc_failed.observed_roots["vendor"]
            self.assertFalse(retained_vendor.scan_complete)
            self.assertFalse(retained_vendor.verified)
            self.assertEqual(
                retained_vendor.directory_identity,
                state.observed_roots["vendor"].directory_identity,
            )
            self.assertEqual(
                retained_vendor.ancestor_identities,
                state.observed_roots["vendor"].ancestor_identities[:2],
            )
            self.assertEqual(len(retained_vendor.member_pins), 0)
            self.assertIs(
                root_anc_failed.root_causes["vendor"], injected_anc_perm
            )
            self.assertIs(
                root_anc_failed.observation_causes["profile:root:vendor"],
                injected_anc_perm,
            )
            # Later roots and files still completed
            self.assertIn("prepared", root_anc_failed.verified_roots)
            self.assertIn("build", root_anc_failed.verified_roots)
            self.assertEqual(
                len(root_anc_failed.verified_files),
                len(state.observed_files),
            )

    def test_744_new_hop_eio_propagation_retarget_retention_and_per_file_ancestor_retention(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = _build_synthetic_outer_profile_fixture(Path(tmp))
            root = fx["root"]
            assert isinstance(root, Path)
            alias_symlink = fx["alias_symlink"]
            assert isinstance(alias_symlink, Path)
            profile = fx["profile"]
            assert isinstance(profile, RefmacDiagnosticProfile)
            base_payload = fx["manifest_payload"]
            assert isinstance(base_payload, dict)

            alias_fid = next(
                fid
                for fid, row in base_payload["files"].items()  # type: ignore[union-attr]
                if row["path"] == str(alias_symlink)
            )
            orig_target = os.readlink(alias_symlink)
            orig_bytes = alias_symlink.read_bytes()
            support_dir = root / "support"
            new_hop = support_dir / "new-hop"
            second_target = support_dir / "collection-python-second"

            # 1. New-hop EIO at dedicated symlink observer after raw file traversal succeeds:
            # symlink and owner keyed causes both retain identical EIO (preferred over comparison None),
            # while continuing other files and roots.
            state = _validate_and_observe_outer_profile(profile)
            os.symlink("collection-python", new_hop)
            alias_symlink.unlink()
            os.symlink("new-hop", alias_symlink)
            try:
                injected_new_hop_eio = OSError(
                    errno.EIO,
                    "simulated EIO inside dedicated new-hop symlink observer",
                    str(new_hop),
                )
                real_observe_symlink = profile_mod._observe_symlink_identity
                real_readlink = os.readlink
                new_hop_obs_state = {
                    "active": False,
                    "injections": 0,
                    "calls": [],
                }

                def observe_sym_new_hop_trigger(
                    edge: _SymlinkEdge,
                    *,
                    check_expected_target: bool = True,
                ):
                    new_hop_obs_state["calls"].append(
                        (edge.path, check_expected_target)
                    )
                    if edge.path == str(new_hop):
                        new_hop_obs_state["active"] = True
                    try:
                        return real_observe_symlink(
                            edge,
                            check_expected_target=check_expected_target,
                        )
                    finally:
                        new_hop_obs_state["active"] = False

                def readlink_fail_on_new_hop(path, *args, **kwargs):
                    if (
                        new_hop_obs_state["active"]
                        and new_hop_obs_state["injections"] == 0
                        and os.fsdecode(path) == str(new_hop)
                    ):
                        new_hop_obs_state["injections"] += 1
                        raise injected_new_hop_eio
                    return real_readlink(path, *args, **kwargs)

                with (
                    mock.patch(
                        "refmac_diagnostic_profile._observe_symlink_identity",
                        side_effect=observe_sym_new_hop_trigger,
                    ),
                    mock.patch(
                        "refmac_diagnostic_profile.os.readlink",
                        side_effect=readlink_fail_on_new_hop,
                    ),
                ):
                    res_eio = _reobserve_outer_profile_state(state)

                self.assertEqual(new_hop_obs_state["injections"], 1)
                self.assertEqual(
                    new_hop_obs_state["calls"],
                    [
                        (str(alias_symlink), False),
                        (str(new_hop), False),
                    ],
                )
                self.assertFalse(res_eio.verified)
                self.assertIn(str(alias_symlink), res_eio.observed_symlinks)
                self.assertEqual(
                    res_eio.observed_symlinks[str(alias_symlink)].target,
                    "new-hop",
                )
                self.assertNotIn(str(new_hop), res_eio.observed_symlinks)
                self.assertIsNone(res_eio.symlink_causes[str(alias_symlink)])
                self.assertIs(
                    res_eio.symlink_causes[str(new_hop)],
                    injected_new_hop_eio,
                )
                self.assertIs(
                    res_eio.observation_causes[f"profile:symlink:{new_hop}"],
                    injected_new_hop_eio,
                )
                self.assertIs(
                    res_eio.file_causes[alias_fid],
                    injected_new_hop_eio,
                )
                self.assertIs(
                    res_eio.observation_causes[f"profile:file:{alias_fid}"],
                    injected_new_hop_eio,
                )
                self.assertTrue(
                    any(
                        str(new_hop) in m
                        for m in res_eio.file_errors[alias_fid]
                    )
                )
                self.assertFalse(res_eio.file_dependencies[alias_fid].complete)
                self.assertEqual(
                    res_eio.file_dependencies[alias_fid].symlink_identities,
                    (res_eio.observed_symlinks[str(alias_symlink)],),
                )
                proj_eio = res_eio.file_observations[alias_fid]
                self.assertIsInstance(proj_eio, FileObservation)
                self.assertFalse(proj_eio.dependencies_complete)
                self.assertFalse(proj_eio.verified)
                self.assertEqual(
                    proj_eio.symlink_identities,
                    (res_eio.observed_symlinks[str(alias_symlink)],),
                )
                self.assertEqual(
                    proj_eio.unavailable_symlinks,
                    (
                        _SymlinkEdge(
                            path=str(new_hop), target="collection-python"
                        ),
                    ),
                )
                self.assertEqual(
                    len(res_eio.verified_files),
                    len(state.observed_files) - 1,
                )
                self.assertEqual(
                    set(res_eio.verified_roots.keys()),
                    {"vendor", "prepared", "build"},
                )
            finally:
                if alias_symlink.exists() or alias_symlink.is_symlink():
                    alias_symlink.unlink()
                os.symlink(orig_target, alias_symlink)
                if new_hop.exists() or new_hop.is_symlink():
                    new_hop.unlink()

            # 2. New-hop retargeted to same-byte second target between raw file read and dedicated observer:
            # observer-only mode retains actual new-hop identity in raw and dependency/FileObservation projections
            # with comparison-only None cause, incomplete/unverified status, and conflict error.
            state = _validate_and_observe_outer_profile(profile)
            second_target.write_bytes(orig_bytes)
            os.symlink("collection-python", new_hop)
            alias_symlink.unlink()
            os.symlink("new-hop", alias_symlink)
            try:
                real_observe_pin = profile_mod._observe_regular_file_pin
                real_observe_symlink = profile_mod._observe_symlink_identity
                retarget_observer_calls: list[tuple[str, bool]] = []
                new_hop_ino_after_retarget: list[int] = []

                def observe_pin_then_retarget_new_hop(path, *args, **kwargs):
                    pin_obs = real_observe_pin(path, *args, **kwargs)
                    if str(path) == str(alias_symlink):
                        new_hop.unlink()
                        os.symlink("collection-python-second", new_hop)
                        new_hop_ino_after_retarget.append(
                            int(os.lstat(new_hop).st_ino)
                        )
                    return pin_obs

                def spy_observe_symlink_retarget(
                    edge: _SymlinkEdge,
                    *,
                    check_expected_target: bool = True,
                ):
                    retarget_observer_calls.append(
                        (edge.path, check_expected_target)
                    )
                    return real_observe_symlink(
                        edge,
                        check_expected_target=check_expected_target,
                    )

                with (
                    mock.patch(
                        "refmac_diagnostic_profile._observe_regular_file_pin",
                        side_effect=observe_pin_then_retarget_new_hop,
                    ),
                    mock.patch(
                        "refmac_diagnostic_profile._observe_symlink_identity",
                        side_effect=spy_observe_symlink_retarget,
                    ),
                ):
                    res_ret = _reobserve_outer_profile_state(state)

                self.assertEqual(len(new_hop_ino_after_retarget), 1)
                self.assertEqual(
                    retarget_observer_calls,
                    [
                        (str(alias_symlink), False),
                        (str(new_hop), False),
                    ],
                )
                self.assertFalse(res_ret.verified)
                self.assertIn(str(new_hop), res_ret.observed_symlinks)
                retained_new_hop = res_ret.observed_symlinks[str(new_hop)]
                self.assertEqual(
                    retained_new_hop.target, "collection-python-second"
                )
                self.assertEqual(
                    retained_new_hop.ino, new_hop_ino_after_retarget[0]
                )
                self.assertIsNone(res_ret.symlink_causes[str(new_hop)])
                self.assertIsNone(
                    res_ret.observation_causes[f"profile:symlink:{new_hop}"]
                )
                self.assertIsNone(res_ret.file_causes[alias_fid])
                self.assertIsNone(
                    res_ret.observation_causes[f"profile:file:{alias_fid}"]
                )
                self.assertTrue(
                    any(
                        "Symlink target changed during observation" in m
                        for m in res_ret.symlink_errors[str(new_hop)]
                    )
                )
                self.assertTrue(
                    any(
                        "Symlink target changed during observation" in m
                        for m in res_ret.file_errors[alias_fid]
                    )
                )
                fdeps_ret = res_ret.file_dependencies[alias_fid]
                self.assertFalse(fdeps_ret.complete)
                self.assertEqual(
                    fdeps_ret.symlink_identities,
                    (
                        retained_new_hop,
                        res_ret.observed_symlinks[str(alias_symlink)],
                    ),
                )
                proj_ret = res_ret.file_observations[alias_fid]
                self.assertIsInstance(proj_ret, FileObservation)
                self.assertFalse(proj_ret.dependencies_complete)
                self.assertFalse(proj_ret.verified)
                self.assertEqual(proj_ret.unavailable_symlinks, ())
                self.assertEqual(
                    proj_ret.symlink_identities,
                    (
                        retained_new_hop,
                        res_ret.observed_symlinks[str(alias_symlink)],
                    ),
                )
            finally:
                if alias_symlink.exists() or alias_symlink.is_symlink():
                    alias_symlink.unlink()
                os.symlink(orig_target, alias_symlink)
                if new_hop.exists() or new_hop.is_symlink():
                    new_hop.unlink()
                if second_target.exists():
                    second_target.unlink()

            # 3. Support directory mode change after file traversal and before dedicated ancestor observation:
            # global observed_ancestors retains dedicated observation, while per-file dependency and FileObservation
            # projections retain their own traversal identity, marked incomplete/unverified with None cause.
            state = _validate_and_observe_outer_profile(profile)
            orig_support_mode = stat.S_IMODE(os.lstat(support_dir).st_mode)
            alt_support_mode = orig_support_mode ^ 0o005
            real_dir_obs = profile_mod._observe_directory_identity
            step4_chmod_done = {"done": False}

            def dir_obs_chmod_support_in_step4(
                dir_path_str: str,
                *,
                require_no_symlink_ancestors: bool = False,
            ):
                if (
                    not step4_chmod_done["done"]
                    and str(dir_path_str) == str(support_dir)
                ):
                    # Step 3 traversal happens inside _traverse_path_components before Step 4;
                    # trigger mode change only once Step 3 has already observed alias_fid.
                    if step4_chmod_done.get("files_done", False):
                        step4_chmod_done["done"] = True
                        os.chmod(support_dir, alt_support_mode)
                return real_dir_obs(
                    dir_path_str,
                    require_no_symlink_ancestors=require_no_symlink_ancestors,
                )

            real_observe_pin = profile_mod._observe_regular_file_pin
            last_fid = sorted(state.observed_files.keys())[-1]
            last_fpath = state.observed_files[last_fid].path

            def observe_pin_mark_files_done(path, *args, **kwargs):
                res = real_observe_pin(path, *args, **kwargs)
                if str(path) == str(last_fpath):
                    step4_chmod_done["files_done"] = True
                return res

            try:
                with (
                    mock.patch(
                        "refmac_diagnostic_profile._observe_regular_file_pin",
                        side_effect=observe_pin_mark_files_done,
                    ),
                    mock.patch(
                        "refmac_diagnostic_profile._observe_directory_identity",
                        side_effect=dir_obs_chmod_support_in_step4,
                    ),
                ):
                    res_dir_conf = _reobserve_outer_profile_state(state)

                self.assertTrue(step4_chmod_done["done"])
                self.assertFalse(res_dir_conf.verified)
                global_support = res_dir_conf.observed_ancestors[
                    str(support_dir)
                ]
                self.assertEqual(global_support.mode, alt_support_mode)

                raw_file_support = next(
                    d
                    for d in res_dir_conf.observed_files[
                        alias_fid
                    ].traversed_directory_identities
                    if d.path == str(support_dir)
                )
                dep_file_support = next(
                    d
                    for d in res_dir_conf.file_dependencies[alias_fid].ancestors
                    if d.path == str(support_dir)
                )
                proj_dir_conf = res_dir_conf.file_observations[alias_fid]
                self.assertIsInstance(proj_dir_conf, FileObservation)
                proj_file_support = next(
                    d
                    for d in proj_dir_conf.ancestors
                    if d.path == str(support_dir)
                )
                self.assertEqual(raw_file_support.mode, orig_support_mode)
                self.assertEqual(dep_file_support, raw_file_support)
                self.assertEqual(proj_file_support, raw_file_support)
                self.assertNotEqual(dep_file_support, global_support)
                self.assertFalse(
                    res_dir_conf.file_dependencies[alias_fid].complete
                )
                self.assertFalse(proj_dir_conf.dependencies_complete)
                self.assertFalse(proj_dir_conf.verified)
                self.assertIsNone(
                    res_dir_conf.ancestor_causes[str(support_dir)]
                )
                self.assertIsNone(res_dir_conf.file_causes[alias_fid])
                self.assertTrue(
                    any(
                        "Directory identity changed during observation" in m
                        for m in res_dir_conf.ancestor_errors[str(support_dir)]
                    )
                )
                self.assertTrue(
                    any(
                        "Directory identity changed during observation" in m
                        for m in res_dir_conf.file_errors[alias_fid]
                    )
                )
            finally:
                os.chmod(support_dir, orig_support_mode)

            # 4. Support directory lookup failure in dedicated ancestor observation after file traversal:
            # per-file dependency and FileObservation projections retain their own traversal identity
            # while global observed_ancestors omits support_dir and preserves exact PermissionError cause.
            state = _validate_and_observe_outer_profile(profile)
            injected_support_perm = PermissionError(
                errno.EACCES,
                "simulated Step 4 support directory lstat failure after file traversal",
                str(support_dir),
            )
            real_lstat = os.lstat
            step4_fail_state = {"files_done": False, "injections": 0}

            def observe_pin_mark_done_for_fail(path, *args, **kwargs):
                res = real_observe_pin(path, *args, **kwargs)
                if str(path) == str(last_fpath):
                    step4_fail_state["files_done"] = True
                return res

            def lstat_fail_support_in_step4(path, *args, **kwargs):
                if (
                    step4_fail_state["files_done"]
                    and step4_fail_state["injections"] == 0
                    and os.fsdecode(path) == str(support_dir)
                ):
                    step4_fail_state["injections"] += 1
                    raise injected_support_perm
                return real_lstat(path, *args, **kwargs)

            with (
                mock.patch(
                    "refmac_diagnostic_profile._observe_regular_file_pin",
                    side_effect=observe_pin_mark_done_for_fail,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.lstat",
                    side_effect=lstat_fail_support_in_step4,
                ),
            ):
                res_dir_fail = _reobserve_outer_profile_state(state)

            self.assertEqual(step4_fail_state["injections"], 1)
            self.assertFalse(res_dir_fail.verified)
            self.assertNotIn(str(support_dir), res_dir_fail.observed_ancestors)
            self.assertIs(
                res_dir_fail.ancestor_causes[str(support_dir)],
                injected_support_perm,
            )
            self.assertIs(
                res_dir_fail.observation_causes[
                    f"profile:ancestor:{support_dir}"
                ],
                injected_support_perm,
            )
            self.assertIs(
                res_dir_fail.file_causes[alias_fid],
                injected_support_perm,
            )
            self.assertIs(
                res_dir_fail.observation_causes[f"profile:file:{alias_fid}"],
                injected_support_perm,
            )
            raw_fail_support = next(
                d
                for d in res_dir_fail.observed_files[
                    alias_fid
                ].traversed_directory_identities
                if d.path == str(support_dir)
            )
            dep_fail_support = next(
                d
                for d in res_dir_fail.file_dependencies[alias_fid].ancestors
                if d.path == str(support_dir)
            )
            proj_dir_fail = res_dir_fail.file_observations[alias_fid]
            self.assertIsInstance(proj_dir_fail, FileObservation)
            proj_fail_support = next(
                d
                for d in proj_dir_fail.ancestors
                if d.path == str(support_dir)
            )
            self.assertEqual(dep_fail_support, raw_fail_support)
            self.assertEqual(proj_fail_support, raw_fail_support)
            self.assertFalse(res_dir_fail.file_dependencies[alias_fid].complete)
            self.assertFalse(proj_dir_fail.dependencies_complete)
            self.assertFalse(proj_dir_fail.verified)

    def test_751_partial_owner_file_and_manifest_dependency_failure_association(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fx = _build_synthetic_outer_profile_fixture(Path(tmp))
            root = fx["root"]
            assert isinstance(root, Path)
            alias_symlink = fx["alias_symlink"]
            assert isinstance(alias_symlink, Path)
            installed_record = fx["installed_record"]
            assert isinstance(installed_record, dict)
            ccp4_env = fx["ccp4_env"]
            assert isinstance(ccp4_env, dict)
            ev_root = fx["evidence_root"]
            assert isinstance(ev_root, Path)
            manifest_path = fx["manifest_path"]
            assert isinstance(manifest_path, Path)
            base_payload = copy.deepcopy(fx["manifest_payload"])
            assert isinstance(base_payload, dict)

            support_dir = root / "support"
            orig_alias_target = os.readlink(alias_symlink)
            orig_alias_bytes = alias_symlink.read_bytes()
            alias_fid = next(
                fid
                for fid, row in base_payload["files"].items()  # type: ignore[union-attr]
                if row["path"] == str(alias_symlink)
            )

            # 1. Shared new-hop EIO propagation to a partial file owner (1-byte baseline redirected to longer target)
            partial_alias = support_dir / "z-partial-alias"
            short_target = support_dir / "short-target"
            new_hop = support_dir / "new-hop"
            partial_id = "task751_partial_owner"
            short_target.write_bytes(b"x")
            os.symlink("short-target", partial_alias)
            try:
                payload_1 = copy.deepcopy(base_payload)
                partial_obs_init = _observe_regular_file_pin(str(partial_alias))
                payload_1["files"][partial_id] = (  # type: ignore[index]
                    partial_obs_init.to_manifest_row()
                )
                payload_1["roles"]["qc_evidence"] = sorted(  # type: ignore[index]
                    [*payload_1["roles"]["qc_evidence"], partial_id]  # type: ignore[index]
                )
                profile_1 = _rewrite_manifest_and_profile(fx, payload_1)
                validated_1 = validate_profile(
                    profile_1, installed_record, ccp4_env, ev_root
                )
                state_1 = validated_1._outer_state
                assert state_1 is not None
                before_repr_1 = repr(state_1)
                before_prov_1 = copy.deepcopy(validated_1.to_provenance())

                os.symlink("collection-python", new_hop)
                for a_path in (alias_symlink, partial_alias):
                    a_path.unlink()
                    os.symlink("new-hop", a_path)

                injected_hop_eio = OSError(
                    errno.EIO,
                    "task751 dedicated new-hop readlink failure",
                    str(new_hop),
                )
                real_observe_symlink = profile_mod._observe_symlink_identity
                real_readlink = os.readlink
                trace_1 = {
                    "inside_new_hop": False,
                    "observer_calls": 0,
                    "injections": 0,
                }

                def observe_sym_1(edge: _SymlinkEdge, *args, **kwargs):
                    monitored = edge.path == str(new_hop)
                    if monitored:
                        trace_1["observer_calls"] += 1
                        trace_1["inside_new_hop"] = True
                    try:
                        return real_observe_symlink(edge, *args, **kwargs)
                    finally:
                        if monitored:
                            trace_1["inside_new_hop"] = False

                def readlink_1(path, *args, **kwargs):
                    if (
                        trace_1["inside_new_hop"]
                        and trace_1["injections"] == 0
                        and os.fsdecode(path) == str(new_hop)
                    ):
                        trace_1["injections"] += 1
                        raise injected_hop_eio
                    return real_readlink(path, *args, **kwargs)

                with (
                    mock.patch(
                        "refmac_diagnostic_profile._observe_symlink_identity",
                        side_effect=observe_sym_1,
                    ),
                    mock.patch(
                        "refmac_diagnostic_profile.os.readlink",
                        side_effect=readlink_1,
                    ),
                ):
                    res_1 = _reobserve_outer_profile_state(state_1)

                self.assertEqual(trace_1["observer_calls"], 1)
                self.assertEqual(trace_1["injections"], 1)
                self.assertFalse(res_1.verified)
                self.assertIn(alias_fid, res_1.observed_files)
                self.assertIn(partial_id, res_1.partial_files)
                partial_fobs = res_1.partial_files[partial_id]
                self.assertIsInstance(partial_fobs, PartialFileReadObservation)
                self.assertIs(res_1.file_observations[partial_id], partial_fobs)
                self.assertIsNone(partial_fobs.sha256)
                self.assertIsNone(partial_fobs.size_bytes)
                self.assertEqual(
                    partial_fobs.stat_size_bytes, len(orig_alias_bytes)
                )
                self.assertEqual(partial_fobs.streamed_size_bytes, 0)
                self.assertFalse(partial_fobs.read_complete)
                self.assertFalse(partial_fobs.verified)
                self.assertTrue(
                    any(e.path == str(new_hop) for e in partial_fobs.symlinks)
                )
                self.assertGreater(len(partial_fobs.ancestors), 0)

                hop_errs_1 = res_1.symlink_errors[str(new_hop)]
                self.assertGreater(len(hop_errs_1), 0)
                self.assertIs(
                    res_1.symlink_causes[str(new_hop)], injected_hop_eio
                )
                self.assertIs(
                    res_1.observation_causes[f"profile:symlink:{new_hop}"],
                    injected_hop_eio,
                )
                self.assertIs(res_1.file_causes[alias_fid], injected_hop_eio)
                self.assertIs(res_1.file_causes[partial_id], injected_hop_eio)
                self.assertIs(
                    res_1.observation_causes[f"profile:file:{partial_id}"],
                    injected_hop_eio,
                )
                self.assertTrue(
                    all(
                        err in res_1.file_errors[partial_id]
                        for err in hop_errs_1
                    )
                )
                self.assertTrue(
                    all(err in res_1.errors for err in hop_errs_1)
                )
                self.assertEqual(
                    set(res_1.observed_files) | set(res_1.partial_files),
                    set(state_1.observed_files),
                )
                self.assertEqual(
                    set(res_1.observed_roots), set(state_1.observed_roots)
                )
                self.assertIs(validated_1._outer_state, state_1)
                self.assertEqual(repr(state_1), before_repr_1)
                self.assertEqual(validated_1.to_provenance(), before_prov_1)
            finally:
                if alias_symlink.exists() or alias_symlink.is_symlink():
                    alias_symlink.unlink()
                os.symlink(orig_alias_target, alias_symlink)
                for p in (partial_alias, new_hop, short_target):
                    if p.exists() or p.is_symlink():
                        p.unlink()
                _rewrite_manifest_and_profile(fx, base_payload)

            # 2. Analogous partial manifest owner sharing new-hop with a complete QC alias to a longer opaque target
            long_qc_alias = support_dir / "z-long-qc-alias"
            long_opaque_target = support_dir / "long-opaque-target"
            new_hop_m = support_dir / "new-hop-manifest"
            long_qc_id = "task751_long_qc_owner"
            orig_manifest_bytes_base = manifest_path.read_bytes()
            long_opaque_bytes = (
                b"opaque-non-json-header-" * 64 + orig_manifest_bytes_base
            )
            long_opaque_target.write_bytes(long_opaque_bytes)
            os.symlink("long-opaque-target", long_qc_alias)
            try:
                payload_2 = copy.deepcopy(base_payload)
                long_qc_obs_init = _observe_regular_file_pin(str(long_qc_alias))
                payload_2["files"][long_qc_id] = (  # type: ignore[index]
                    long_qc_obs_init.to_manifest_row()
                )
                payload_2["roles"]["qc_evidence"] = sorted(  # type: ignore[index]
                    [*payload_2["roles"]["qc_evidence"], long_qc_id]  # type: ignore[index]
                )
                profile_2 = _rewrite_manifest_and_profile(fx, payload_2)
                saved_manifest_bytes = manifest_path.read_bytes()
                self.assertGreater(
                    len(long_opaque_bytes), len(saved_manifest_bytes)
                )

                validated_2 = validate_profile(
                    profile_2, installed_record, ccp4_env, ev_root
                )
                state_2 = validated_2._outer_state
                assert state_2 is not None
                before_repr_2 = repr(state_2)
                before_prov_2 = copy.deepcopy(validated_2.to_provenance())

                os.symlink("long-opaque-target", new_hop_m)
                long_qc_alias.unlink()
                os.symlink("new-hop-manifest", long_qc_alias)
                manifest_path.unlink()
                os.symlink(str(new_hop_m), manifest_path)

                injected_hop_m_eio = OSError(
                    errno.EIO,
                    "task751 dedicated manifest new-hop readlink failure",
                    str(new_hop_m),
                )
                real_observe_symlink = profile_mod._observe_symlink_identity
                real_readlink = os.readlink
                trace_2 = {
                    "inside_new_hop": False,
                    "observer_calls": 0,
                    "injections": 0,
                }

                def observe_sym_2(edge: _SymlinkEdge, *args, **kwargs):
                    monitored = edge.path == str(new_hop_m)
                    if monitored:
                        trace_2["observer_calls"] += 1
                        trace_2["inside_new_hop"] = True
                    try:
                        return real_observe_symlink(edge, *args, **kwargs)
                    finally:
                        if monitored:
                            trace_2["inside_new_hop"] = False

                def readlink_2(path, *args, **kwargs):
                    if (
                        trace_2["inside_new_hop"]
                        and trace_2["injections"] == 0
                        and os.fsdecode(path) == str(new_hop_m)
                    ):
                        trace_2["injections"] += 1
                        raise injected_hop_m_eio
                    return real_readlink(path, *args, **kwargs)

                with (
                    mock.patch(
                        "refmac_diagnostic_profile._observe_symlink_identity",
                        side_effect=observe_sym_2,
                    ),
                    mock.patch(
                        "refmac_diagnostic_profile.os.readlink",
                        side_effect=readlink_2,
                    ),
                ):
                    res_2 = _reobserve_outer_profile_state(state_2)

                self.assertEqual(trace_2["observer_calls"], 1)
                self.assertEqual(trace_2["injections"], 1)
                self.assertFalse(res_2.verified)
                self.assertIsNone(res_2.manifest_observation)
                self.assertIsNotNone(res_2.partial_manifest_observation)
                p_man = res_2.partial_manifest_observation
                assert p_man is not None
                self.assertIsInstance(p_man, PartialFileReadObservation)
                self.assertIs(res_2.manifest_file_observation, p_man)
                self.assertIsNone(p_man.sha256)
                self.assertIsNone(p_man.size_bytes)
                self.assertEqual(
                    p_man.stat_size_bytes, len(long_opaque_bytes)
                )
                self.assertEqual(p_man.streamed_size_bytes, 0)
                self.assertFalse(p_man.read_complete)
                self.assertFalse(p_man.verified)
                self.assertTrue(
                    any(e.path == str(new_hop_m) for e in p_man.symlinks)
                )
                self.assertGreater(len(p_man.ancestors), 0)

                hop_errs_2 = res_2.symlink_errors[str(new_hop_m)]
                self.assertGreater(len(hop_errs_2), 0)
                self.assertIs(
                    res_2.symlink_causes[str(new_hop_m)], injected_hop_m_eio
                )
                self.assertIs(
                    res_2.observation_causes[f"profile:symlink:{new_hop_m}"],
                    injected_hop_m_eio,
                )
                self.assertIs(
                    res_2.file_causes[long_qc_id], injected_hop_m_eio
                )
                self.assertIs(res_2.manifest_cause, injected_hop_m_eio)
                self.assertIs(
                    res_2.observation_causes["profile:manifest"],
                    injected_hop_m_eio,
                )
                self.assertTrue(
                    all(err in res_2.manifest_errors for err in hop_errs_2)
                )
                self.assertTrue(
                    all(err in res_2.errors for err in hop_errs_2)
                )
                self.assertEqual(
                    set(res_2.observed_files) | set(res_2.partial_files),
                    set(state_2.observed_files),
                )
                self.assertEqual(
                    set(res_2.observed_roots), set(state_2.observed_roots)
                )
                self.assertIs(validated_2._outer_state, state_2)
                self.assertEqual(repr(state_2), before_repr_2)
                self.assertEqual(validated_2.to_provenance(), before_prov_2)
            finally:
                if manifest_path.exists() or manifest_path.is_symlink():
                    manifest_path.unlink()
                manifest_path.write_bytes(orig_manifest_bytes_base)
                for p in (long_qc_alias, new_hop_m, long_opaque_target):
                    if p.exists() or p.is_symlink():
                        p.unlink()
                _rewrite_manifest_and_profile(fx, base_payload)


class TestTask737PublicRecheckProfile(unittest.TestCase):
    """Focused synthetic tests for public recheck_profile projection (Tasks 662 and 737)."""

    def test_recheck_profile_positive_baseline_single_call_and_detachment(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fx = _build_synthetic_outer_profile_fixture(Path(tmpdir))
            root = fx["root"]
            assert isinstance(root, Path)
            profile = fx["profile"]
            assert isinstance(profile, RefmacDiagnosticProfile)
            installed_record = fx["installed_record"]
            assert isinstance(installed_record, dict)
            ccp4_env = fx["ccp4_env"]
            assert isinstance(ccp4_env, dict)
            ev_root = fx["evidence_root"]
            assert isinstance(ev_root, Path)

            validated = validate_profile(
                profile, installed_record, ccp4_env, ev_root
            )
            baseline_prov = copy.deepcopy(validated.to_provenance())

            for bad_baseline in (None, "not_a_profile", profile, {}):
                with self.assertRaises(ValueError):
                    recheck_profile(bad_baseline)  # type: ignore[arg-type]

            for bad_causes in ("not_a_list", (), {}, 42):
                with self.assertRaises(ValueError):
                    recheck_profile(
                        validated,
                        mutation_causes_out=bad_causes,  # type: ignore[arg-type]
                    )

            real_reobserve = profile_mod._reobserve_outer_profile_state
            reobserve_calls = {"count": 0, "done": False}
            real_lstat = os.lstat
            real_stat = os.stat
            real_open = os.open
            real_walk = os.walk
            real_readlink = os.readlink

            def wrapped_reobserve(state, *args, **kwargs):
                reobserve_calls["count"] += 1
                res = real_reobserve(state, *args, **kwargs)
                reobserve_calls["done"] = True
                return res

            def forbid_fs_after_reobserve(fn, name: str):
                def _wrapper(*args, **kwargs):
                    if reobserve_calls["done"]:
                        raise AssertionError(
                            f"Filesystem call {name} invoked after _reobserve_outer_profile_state during in-memory projection"
                        )
                    return fn(*args, **kwargs)

                return _wrapper

            causes: list[Exception | None] = [RuntimeError("stale")]
            with (
                mock.patch(
                    "refmac_diagnostic_profile._reobserve_outer_profile_state",
                    side_effect=wrapped_reobserve,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.lstat",
                    side_effect=forbid_fs_after_reobserve(
                        real_lstat, "os.lstat"
                    ),
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.stat",
                    side_effect=forbid_fs_after_reobserve(real_stat, "os.stat"),
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.open",
                    side_effect=forbid_fs_after_reobserve(real_open, "os.open"),
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.walk",
                    side_effect=forbid_fs_after_reobserve(real_walk, "os.walk"),
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.readlink",
                    side_effect=forbid_fs_after_reobserve(
                        real_readlink, "os.readlink"
                    ),
                ),
            ):
                report = recheck_profile(validated, mutation_causes_out=causes)

            self.assertEqual(reobserve_calls["count"], 1)
            self.assertEqual(causes, [])
            self.assertEqual(
                set(report.keys()),
                {
                    "profile_id",
                    "verified",
                    "runtime_image_coverage",
                    "manifest",
                    "files",
                    "roots",
                    "mutations",
                    "errors",
                },
            )
            self.assertEqual(report["profile_id"], SUPPORTED_PROFILE_ID)
            self.assertTrue(report["verified"])
            self.assertEqual(report["runtime_image_coverage"], "not_assessed")
            self.assertEqual(report["mutations"], [])
            self.assertEqual(report["errors"], [])

            self.assertEqual(
                set(report["manifest"].keys()),
                {"expected", "observed", "matches_baseline", "errors"},
            )
            self.assertTrue(report["manifest"]["matches_baseline"])
            self.assertEqual(report["manifest"]["errors"], [])
            self.assertEqual(
                report["manifest"]["expected"], baseline_prov["manifest"]
            )
            self.assertEqual(
                report["manifest"]["observed"], baseline_prov["manifest"]
            )

            self.assertEqual(
                list(report["files"].keys()),
                sorted(baseline_prov["files"].keys()),
            )
            self.assertEqual(len(report["files"]), 59)
            for fid, frow in report["files"].items():
                self.assertEqual(
                    set(frow.keys()),
                    {"expected", "observed", "matches_baseline", "errors"},
                )
                self.assertTrue(frow["matches_baseline"])
                self.assertEqual(frow["errors"], [])
                self.assertEqual(frow["expected"], baseline_prov["files"][fid])
                self.assertEqual(frow["observed"], baseline_prov["files"][fid])

            self.assertEqual(
                list(report["roots"].keys()),
                sorted(baseline_prov["roots"].keys()),
            )
            self.assertEqual(len(report["roots"]), 3)
            for rname, rrow in report["roots"].items():
                self.assertEqual(
                    set(rrow.keys()),
                    {
                        "expected",
                        "observed",
                        "matches_baseline",
                        "scan_complete",
                        "member_diff",
                        "errors",
                    },
                )
                self.assertTrue(rrow["matches_baseline"])
                self.assertTrue(rrow["scan_complete"])
                self.assertEqual(
                    rrow["member_diff"], {"added": [], "removed": []}
                )
                self.assertEqual(rrow["errors"], [])
                self.assertEqual(rrow["expected"], baseline_prov["roots"][rname])
                self.assertEqual(rrow["observed"], baseline_prov["roots"][rname])

            # Parent directory mtime change and unrelated sibling file outside controlled roots do not fail
            sibling_outside = root / "unrelated_outside_sibling.tmp"
            sibling_outside.write_bytes(b"unrelated sibling outside roots\n")
            os.utime(root, None)
            try:
                causes_sibling: list[Exception | None] = []
                report_sibling = recheck_profile(
                    validated, mutation_causes_out=causes_sibling
                )
                self.assertTrue(report_sibling["verified"])
                self.assertEqual(report_sibling["mutations"], [])
                self.assertEqual(report_sibling["errors"], [])
                self.assertEqual(causes_sibling, [])
            finally:
                sibling_outside.unlink()

            # Mutating returned dict does not alter baseline or subsequent recheck_profile calls
            report["verified"] = False
            report["manifest"]["expected"]["sha256"] = "0" * 64
            report["manifest"]["observed"]["ino"] = -1
            first_fid = sorted(report["files"].keys())[0]
            report["files"][first_fid]["expected"]["size_bytes"] = 999999
            report["roots"]["build"]["member_diff"]["added"].append("tampered")
            report["mutations"].append({"tampered": True})
            report["errors"].append({"tampered": True})

            self.assertEqual(validated.to_provenance(), baseline_prov)
            fresh_report = recheck_profile(validated)
            self.assertTrue(fresh_report["verified"])
            self.assertEqual(
                fresh_report["manifest"]["expected"], baseline_prov["manifest"]
            )
            self.assertEqual(
                fresh_report["files"][first_fid]["expected"],
                baseline_prov["files"][first_fid],
            )
            self.assertEqual(
                fresh_report["roots"]["build"]["member_diff"],
                {"added": [], "removed": []},
            )
            self.assertEqual(fresh_report["mutations"], [])
            self.assertEqual(fresh_report["errors"], [])

    def test_recheck_profile_comparison_only_mutations_have_null_error_and_none_cause(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fx = _build_synthetic_outer_profile_fixture(Path(tmpdir))
            root = fx["root"]
            assert isinstance(root, Path)
            profile = fx["profile"]
            assert isinstance(profile, RefmacDiagnosticProfile)
            installed_record = fx["installed_record"]
            assert isinstance(installed_record, dict)
            ccp4_env = fx["ccp4_env"]
            assert isinstance(ccp4_env, dict)
            ev_root = fx["evidence_root"]
            assert isinstance(ev_root, Path)
            alias_symlink = fx["alias_symlink"]
            assert isinstance(alias_symlink, Path)
            base_payload = copy.deepcopy(fx["manifest_payload"])
            assert isinstance(base_payload, dict)

            validated = validate_profile(
                profile, installed_record, ccp4_env, ev_root
            )
            baseline_prov = copy.deepcopy(validated.to_provenance())

            # 1. Same-byte file replacement with new inode on an external file
            ext_fid = base_payload["roles"]["installed_reference"][0]  # type: ignore[index]
            ext_path = Path(base_payload["files"][ext_fid]["path"])  # type: ignore[index]
            orig_ext_bytes = ext_path.read_bytes()
            orig_ext_mode = stat.S_IMODE(os.lstat(ext_path).st_mode)
            orig_ext_ino = os.lstat(ext_path).st_ino
            replacement_hold = root / "hold_inode_ext.tmp"
            try:
                ext_path.rename(replacement_hold)
                ext_path.write_bytes(orig_ext_bytes)
                os.chmod(ext_path, orig_ext_mode)
                self.assertNotEqual(os.lstat(ext_path).st_ino, orig_ext_ino)

                causes_1: list[Exception | None] = []
                rep_1 = recheck_profile(
                    validated, mutation_causes_out=causes_1
                )
                self.assertFalse(rep_1["verified"])
                self.assertEqual(rep_1["errors"], [])
                self.assertFalse(rep_1["files"][ext_fid]["matches_baseline"])
                self.assertEqual(rep_1["files"][ext_fid]["errors"], [])
                self.assertEqual(
                    rep_1["files"][ext_fid]["expected"],
                    baseline_prov["files"][ext_fid],
                )
                self.assertNotEqual(
                    rep_1["files"][ext_fid]["observed"]["ino"],
                    baseline_prov["files"][ext_fid]["ino"],
                )
                self.assertEqual(len(rep_1["mutations"]), 1)
                mut_1 = rep_1["mutations"][0]
                self.assertEqual(
                    mut_1["category"], "diagnostic_profile_file"
                )
                self.assertEqual(mut_1["key"], f"profile:file:{ext_fid}")
                self.assertEqual(mut_1["path"], str(ext_path))
                self.assertIsNone(mut_1["error"])
                self.assertEqual(
                    mut_1["expected"], rep_1["files"][ext_fid]["expected"]
                )
                self.assertEqual(
                    mut_1["observed"], rep_1["files"][ext_fid]["observed"]
                )
                self.assertEqual(causes_1, [None])
            finally:
                if replacement_hold.exists():
                    if ext_path.exists():
                        ext_path.unlink()
                    replacement_hold.rename(ext_path)
                    os.chmod(ext_path, orig_ext_mode)

            # 2. Controlled root comparison mismatch (extra file added in build root)
            build_root = Path(base_payload["roots"]["build"]["path"])  # type: ignore[index]
            extra_build_file = build_root / "extra_comparison_probe.txt"
            extra_build_file.write_bytes(b"extra probe\n")
            try:
                causes_2: list[Exception | None] = []
                rep_2 = recheck_profile(
                    validated, mutation_causes_out=causes_2
                )
                self.assertFalse(rep_2["verified"])
                self.assertEqual(rep_2["errors"], [])
                self.assertFalse(rep_2["roots"]["build"]["matches_baseline"])
                self.assertTrue(rep_2["roots"]["build"]["scan_complete"])
                self.assertEqual(
                    rep_2["roots"]["build"]["member_diff"],
                    {"added": ["extra_comparison_probe.txt"], "removed": []},
                )
                self.assertEqual(rep_2["roots"]["build"]["errors"], [])
                self.assertEqual(len(rep_2["mutations"]), 1)
                self.assertEqual(
                    rep_2["mutations"][0]["key"], "profile:root:build"
                )
                self.assertEqual(
                    rep_2["mutations"][0]["category"],
                    "diagnostic_profile_root",
                )
                self.assertIsNone(rep_2["mutations"][0]["error"])
                self.assertEqual(causes_2, [None])
            finally:
                if extra_build_file.exists():
                    extra_build_file.unlink()

            # 3. Ancestor directory identity change (mode change on support directory)
            support_dir = root / "support"
            orig_support_mode = stat.S_IMODE(os.lstat(support_dir).st_mode)
            os.chmod(support_dir, orig_support_mode ^ 0o005)
            try:
                causes_3: list[Exception | None] = []
                rep_3 = recheck_profile(
                    validated, mutation_causes_out=causes_3
                )
                self.assertFalse(rep_3["verified"])
                self.assertEqual(rep_3["errors"], [])
                self.assertGreater(len(rep_3["mutations"]), 0)
                self.assertTrue(
                    all(m["error"] is None for m in rep_3["mutations"])
                )
                self.assertEqual(causes_3, [None] * len(rep_3["mutations"]))
            finally:
                os.chmod(support_dir, orig_support_mode)

            # 4. Symlink replacement with new inode pointing to the same target
            alias_fid = next(
                fid
                for fid, row in base_payload["files"].items()  # type: ignore[union-attr]
                if row["path"] == str(alias_symlink)
            )
            orig_sym_target = os.readlink(alias_symlink)
            orig_sym_ino = os.lstat(alias_symlink).st_ino
            sym_hold = root / "hold_sym_inode.tmp"
            try:
                alias_symlink.rename(sym_hold)
                os.symlink(orig_sym_target, alias_symlink)
                self.assertNotEqual(
                    os.lstat(alias_symlink).st_ino, orig_sym_ino
                )

                causes_4: list[Exception | None] = []
                rep_4 = recheck_profile(
                    validated, mutation_causes_out=causes_4
                )
                self.assertFalse(rep_4["verified"])
                self.assertEqual(rep_4["errors"], [])
                self.assertFalse(rep_4["files"][alias_fid]["matches_baseline"])
                self.assertEqual(rep_4["files"][alias_fid]["errors"], [])
                self.assertEqual(len(rep_4["mutations"]), 1)
                self.assertEqual(
                    rep_4["mutations"][0]["key"], f"profile:file:{alias_fid}"
                )
                self.assertIsNone(rep_4["mutations"][0]["error"])
                self.assertEqual(causes_4, [None])
            finally:
                if sym_hold.exists() or sym_hold.is_symlink():
                    if alias_symlink.exists() or alias_symlink.is_symlink():
                        alias_symlink.unlink()
                    sym_hold.rename(alias_symlink)

            # 5. diagnostic_executable chmodded 0o644 (non-executable)
            diag_id = base_payload["roles"]["diagnostic_executable"][0]  # type: ignore[index]
            diag_path = Path(base_payload["files"][diag_id]["path"])  # type: ignore[index]
            orig_diag_mode = stat.S_IMODE(os.lstat(diag_path).st_mode)
            os.chmod(diag_path, 0o644)
            try:
                causes_5: list[Exception | None] = []
                rep_5 = recheck_profile(
                    validated, mutation_causes_out=causes_5
                )
                self.assertFalse(rep_5["verified"])
                self.assertEqual(rep_5["errors"], [])
                self.assertFalse(rep_5["files"][diag_id]["matches_baseline"])
                self.assertEqual(rep_5["files"][diag_id]["errors"], [])
                diag_muts = [
                    m
                    for m in rep_5["mutations"]
                    if m["key"] == f"profile:file:{diag_id}"
                ]
                self.assertEqual(len(diag_muts), 1)
                self.assertIsNone(diag_muts[0]["error"])
                self.assertIn(
                    "no longer executable", diag_muts[0]["reason"]
                )
                self.assertEqual(causes_5, [None] * len(rep_5["mutations"]))
            finally:
                os.chmod(diag_path, orig_diag_mode)

    def test_recheck_profile_mutually_replaced_manifest_and_file_cannot_change_expected_authority(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fx = _build_synthetic_outer_profile_fixture(Path(tmpdir))
            profile = fx["profile"]
            assert isinstance(profile, RefmacDiagnosticProfile)
            installed_record = fx["installed_record"]
            assert isinstance(installed_record, dict)
            ccp4_env = fx["ccp4_env"]
            assert isinstance(ccp4_env, dict)
            ev_root = fx["evidence_root"]
            assert isinstance(ev_root, Path)
            manifest_path = fx["manifest_path"]
            assert isinstance(manifest_path, Path)
            base_payload = copy.deepcopy(fx["manifest_payload"])
            assert isinstance(base_payload, dict)

            validated = validate_profile(
                profile, installed_record, ccp4_env, ev_root
            )
            baseline_prov = copy.deepcopy(validated.to_provenance())

            target_fid = base_payload["roles"]["installed_reference"][0]  # type: ignore[index]
            target_path = Path(base_payload["files"][target_fid]["path"])  # type: ignore[index]
            orig_file_bytes = target_path.read_bytes()
            orig_manifest_bytes = manifest_path.read_bytes()

            new_file_bytes = (
                bytes([orig_file_bytes[0] ^ 0x01]) + orig_file_bytes[1:]
            )
            self.assertEqual(len(new_file_bytes), len(orig_file_bytes))
            self.assertNotEqual(new_file_bytes, orig_file_bytes)

            forged_payload = copy.deepcopy(base_payload)
            forged_payload["files"][target_fid]["sha256"] = _sha256_bytes(  # type: ignore[index]
                new_file_bytes
            )
            forged_payload["files"][target_fid]["size_bytes"] = len(  # type: ignore[index]
                new_file_bytes
            )
            forged_manifest_bytes = (
                json.dumps(forged_payload, indent=2) + "\n"
            ).encode("utf-8")
            self.assertEqual(
                len(forged_manifest_bytes), len(orig_manifest_bytes)
            )
            self.assertNotEqual(forged_manifest_bytes, orig_manifest_bytes)

            try:
                target_path.write_bytes(new_file_bytes)
                manifest_path.write_bytes(forged_manifest_bytes)

                causes: list[Exception | None] = []
                report = recheck_profile(validated, mutation_causes_out=causes)
                self.assertFalse(report["verified"])
                self.assertEqual(report["errors"], [])
                self.assertFalse(report["manifest"]["matches_baseline"])
                self.assertFalse(
                    report["files"][target_fid]["matches_baseline"]
                )
                self.assertEqual(
                    report["manifest"]["expected"], baseline_prov["manifest"]
                )
                self.assertEqual(
                    report["files"][target_fid]["expected"],
                    baseline_prov["files"][target_fid],
                )
                self.assertEqual(
                    report["manifest"]["observed"]["sha256"],
                    _sha256_bytes(forged_manifest_bytes),
                )
                self.assertEqual(
                    report["files"][target_fid]["observed"]["sha256"],
                    _sha256_bytes(new_file_bytes),
                )
                mut_keys = [m["key"] for m in report["mutations"]]
                self.assertEqual(
                    mut_keys,
                    ["profile:manifest", f"profile:file:{target_fid}"],
                )
                self.assertEqual(causes, [None, None])
            finally:
                target_path.write_bytes(orig_file_bytes)
                manifest_path.write_bytes(orig_manifest_bytes)

    def test_recheck_profile_multi_error_continuation_partial_observations_and_distinct_causes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fx = _build_synthetic_outer_profile_fixture(Path(tmpdir))
            root = fx["root"]
            assert isinstance(root, Path)
            profile = fx["profile"]
            assert isinstance(profile, RefmacDiagnosticProfile)
            installed_record = fx["installed_record"]
            assert isinstance(installed_record, dict)
            ccp4_env = fx["ccp4_env"]
            assert isinstance(ccp4_env, dict)
            ev_root = fx["evidence_root"]
            assert isinstance(ev_root, Path)
            base_payload = copy.deepcopy(fx["manifest_payload"])
            assert isinstance(base_payload, dict)

            validated = validate_profile(
                profile, installed_record, ccp4_env, ev_root
            )
            baseline_prov = copy.deepcopy(validated.to_provenance())

            tree_fids = {
                fid
                for rdata in base_payload["roots"].values()  # type: ignore[union-attr]
                for fid in rdata["file_ids"]
            }
            external_fids = sorted(
                fid
                for fid in base_payload["files"].keys()  # type: ignore[union-attr]
                if fid not in tree_fids
                and not base_payload["files"][fid]["symlinks"]  # type: ignore[index]
            )
            early_fid = external_fids[0]
            later_fid = external_fids[-1]
            self.assertLess(early_fid, later_fid)

            early_path = Path(base_payload["files"][early_fid]["path"])  # type: ignore[index]
            later_path = Path(base_payload["files"][later_fid]["path"])  # type: ignore[index]
            orig_early_bytes = early_path.read_bytes()
            orig_later_bytes = later_path.read_bytes()

            build_root = Path(base_payload["roots"]["build"]["path"])  # type: ignore[index]
            added_before_err = build_root / "00_added_before_walk_err.txt"
            walk_sub = build_root / "zz_locked_subdir"
            walk_sub.mkdir()
            added_before_err.write_bytes(b"observed before walk error\n")
            injected_walk_perm = PermissionError(
                errno.EACCES,
                "simulated walk permission denied after first root member",
                str(walk_sub),
            )

            real_walk = os.walk

            def walk_fail_on_sub(top, *args, **kwargs):
                onerror = kwargs.get("onerror")
                for dirpath, dirnames, filenames in real_walk(
                    top, *args, **kwargs
                ):
                    if Path(dirpath) == walk_sub:
                        if onerror is not None:
                            onerror(injected_walk_perm)
                        return
                    yield dirpath, dirnames, filenames

            try:
                early_path.unlink()
                later_path.write_bytes(
                    orig_later_bytes + b"\n# modified later file\n"
                )
                causes_multi: list[Exception | None] = []
                with mock.patch(
                    "refmac_diagnostic_profile.os.walk",
                    side_effect=walk_fail_on_sub,
                ):
                    rep_multi = recheck_profile(
                        validated, mutation_causes_out=causes_multi
                    )

                self.assertFalse(rep_multi["verified"])
                self.assertEqual(len(rep_multi["files"]), 59)
                self.assertEqual(len(rep_multi["roots"]), 3)

                # Early missing file
                early_row = rep_multi["files"][early_fid]
                self.assertIsNone(early_row["observed"])
                self.assertFalse(early_row["matches_baseline"])
                self.assertEqual(len(early_row["errors"]), 1)
                self.assertEqual(
                    early_row["errors"][0]["type"], "FileNotFoundError"
                )
                self.assertEqual(early_row["errors"][0]["errno"], errno.ENOENT)

                # Later changed file
                later_row = rep_multi["files"][later_fid]
                self.assertIsNotNone(later_row["observed"])
                self.assertFalse(later_row["matches_baseline"])
                self.assertEqual(later_row["errors"], [])

                # Incomplete build root scan
                build_row = rep_multi["roots"]["build"]
                self.assertIsNotNone(build_row["observed"])
                self.assertFalse(build_row["matches_baseline"])
                self.assertFalse(build_row["scan_complete"])
                self.assertEqual(
                    build_row["member_diff"],
                    {
                        "added": ["00_added_before_walk_err.txt"],
                        "removed": [],
                    },
                )
                self.assertEqual(len(build_row["errors"]), 1)
                self.assertEqual(
                    build_row["errors"][0]["type"], "PermissionError"
                )
                self.assertEqual(build_row["errors"][0]["errno"], errno.EACCES)

                # Aligned mutations and causes: (FileNotFoundError, None, PermissionError)
                self.assertEqual(len(rep_multi["mutations"]), 3)
                self.assertEqual(len(causes_multi), 3)
                self.assertEqual(
                    [m["key"] for m in rep_multi["mutations"]],
                    [
                        f"profile:file:{early_fid}",
                        f"profile:file:{later_fid}",
                        "profile:root:build",
                    ],
                )
                self.assertIsInstance(causes_multi[0], FileNotFoundError)
                self.assertIsNone(causes_multi[1])
                self.assertIs(causes_multi[2], injected_walk_perm)
                self.assertIsNotNone(rep_multi["mutations"][0]["error"])
                self.assertIsNone(rep_multi["mutations"][1]["error"])
                self.assertIsNotNone(rep_multi["mutations"][2]["error"])
                self.assertEqual(len(rep_multi["errors"]), 2)
                json.dumps(rep_multi, allow_nan=False)
            finally:
                early_path.write_bytes(orig_early_bytes)
                later_path.write_bytes(orig_later_bytes)
                if added_before_err.exists():
                    added_before_err.unlink()
                if walk_sub.exists():
                    walk_sub.rmdir()

            # Subcase 2: Partial file read (post-fstat EIO) + distinct Step 4 ancestor PermissionError
            support_dir = root / "support"
            alias_symlink = fx["alias_symlink"]
            assert isinstance(alias_symlink, Path)
            alias_fid = next(
                fid
                for fid, row in base_payload["files"].items()  # type: ignore[union-attr]
                if row["path"] == str(alias_symlink)
            )
            alias_resolved = Path(
                base_payload["files"][alias_fid]["resolved_path"]  # type: ignore[index]
            )
            injected_read_eio = OSError(
                errno.EIO,
                "simulated post-fstat read EIO for public recheck",
                str(alias_resolved),
            )
            injected_anc_perm = PermissionError(
                errno.EACCES,
                "simulated Step 4 support dir PermissionError for public recheck",
                str(support_dir),
            )

            real_fdopen = os.fdopen
            real_dir_obs = profile_mod._observe_directory_identity
            step_state = {
                "current_lexical_path": None,
                "eio_injected": False,
                "files_done": False,
            }
            last_fid = sorted(baseline_prov["files"].keys())[-1]
            last_fpath = baseline_prov["files"][last_fid]["path"]
            real_obs_pin = profile_mod._observe_regular_file_pin

            def obs_pin_track(path, *args, **kwargs):
                prev_lexical_path = step_state["current_lexical_path"]
                step_state["current_lexical_path"] = str(path)
                try:
                    return real_obs_pin(path, *args, **kwargs)
                finally:
                    step_state["current_lexical_path"] = prev_lexical_path
                    if str(path) == str(last_fpath):
                        step_state["files_done"] = True

            class _FailingReader:
                def __init__(self, wrapped):
                    self._wrapped = wrapped

                def read(self, size=-1):
                    raise injected_read_eio

                def fileno(self):
                    return self._wrapped.fileno()

                def __enter__(self):
                    self._wrapped.__enter__()
                    return self

                def __exit__(self, exc_type, exc_val, exc_tb):
                    return self._wrapped.__exit__(exc_type, exc_val, exc_tb)

            def fdopen_inject_on_alias(fd, *args, **kwargs):
                fobj = real_fdopen(fd, *args, **kwargs)
                st = os.fstat(fd)
                target_st = os.lstat(alias_resolved)
                if (
                    not step_state["eio_injected"]
                    and step_state["current_lexical_path"] == str(alias_symlink)
                    and (st.st_dev, st.st_ino)
                    == (target_st.st_dev, target_st.st_ino)
                ):
                    step_state["eio_injected"] = True
                    return _FailingReader(fobj)
                return fobj

            def dir_obs_fail_support_in_step4(
                dir_path_str: str,
                *,
                require_no_symlink_ancestors: bool = False,
            ):
                if (
                    step_state["files_done"]
                    and str(dir_path_str) == str(support_dir)
                ):
                    raise ValueError(
                        f"Cannot lstat directory {dir_path_str!r} (PermissionError): {injected_anc_perm}"
                    ) from injected_anc_perm
                return real_dir_obs(
                    dir_path_str,
                    require_no_symlink_ancestors=require_no_symlink_ancestors,
                )

            causes_sub2: list[Exception | None] = []
            with (
                mock.patch(
                    "refmac_diagnostic_profile._observe_regular_file_pin",
                    side_effect=obs_pin_track,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.fdopen",
                    side_effect=fdopen_inject_on_alias,
                ),
                mock.patch(
                    "refmac_diagnostic_profile._observe_directory_identity",
                    side_effect=dir_obs_fail_support_in_step4,
                ),
            ):
                rep_sub2 = recheck_profile(
                    validated, mutation_causes_out=causes_sub2
                )

            self.assertTrue(step_state["eio_injected"])
            self.assertFalse(rep_sub2["verified"])
            alias_row = rep_sub2["files"][alias_fid]
            self.assertFalse(alias_row["matches_baseline"])
            self.assertIsNotNone(alias_row["observed"])
            self.assertFalse(alias_row["observed"]["read_complete"])
            self.assertIsNone(alias_row["observed"]["sha256"])
            self.assertIsNone(alias_row["observed"]["size_bytes"])
            self.assertEqual(len(alias_row["errors"]), 2)
            self.assertEqual(
                [e["type"] for e in alias_row["errors"]],
                ["OSError", "PermissionError"],
            )

            alias_muts = [
                (idx, m)
                for idx, m in enumerate(rep_sub2["mutations"])
                if m["key"] == f"profile:file:{alias_fid}"
            ]
            self.assertEqual(len(alias_muts), 2)
            self.assertIs(causes_sub2[alias_muts[0][0]], injected_read_eio)
            self.assertIs(causes_sub2[alias_muts[1][0]], injected_anc_perm)
            json.dumps(rep_sub2, allow_nan=False)

    def test_recheck_profile_custom_baseexception_cause_chain_and_descriptor(
        self,
    ) -> None:
        class OriginalSignal(BaseException):
            def __init__(
                self, message: str, errno_val: int | None = None
            ) -> None:
                super().__init__(message)
                self.errno = errno_val

        with tempfile.TemporaryDirectory() as tmpdir:
            fx = _build_synthetic_outer_profile_fixture(Path(tmpdir))
            profile = fx["profile"]
            assert isinstance(profile, RefmacDiagnosticProfile)
            installed_record = fx["installed_record"]
            assert isinstance(installed_record, dict)
            ccp4_env = fx["ccp4_env"]
            assert isinstance(ccp4_env, dict)
            ev_root = fx["evidence_root"]
            assert isinstance(ev_root, Path)

            validated = validate_profile(
                profile, installed_record, ccp4_env, ev_root
            )
            state = validated._outer_state
            assert state is not None
            clean_recheck = _reobserve_outer_profile_state(state)

            # 1. Pure projection with an actual caught ValueError explicitly chained from a custom BaseException
            orig_signal = OriginalSignal("original signal object")
            try:
                try:
                    raise orig_signal
                except OriginalSignal as sig_exc:
                    raise ValueError("actual caught wrapper") from sig_exc
            except ValueError as err:
                caught_wrapper = err

            self.assertIs(caught_wrapper.__cause__, orig_signal)
            mutations_1: list[dict[str, object]] = []
            causes_1: list[Exception | None] = []
            top_errors_1: list[dict[str, object]] = []
            row_errors_1 = profile_mod._collect_owner_postflight_findings(
                owner_key="profile:file:example",
                owner_category="diagnostic_profile_file",
                owner_path="/inert/example",
                expected_payload={},
                observed_payload=None,
                matches_baseline=False,
                owner_errors=("actual caught wrapper",),
                direct_cause=caught_wrapper,
                all_ancs=(),
                all_syms=(),
                recheck=clean_recheck,
                mutations_out=mutations_1,  # type: ignore[arg-type]
                causes_out=causes_1,
                top_errors_out=top_errors_1,  # type: ignore[arg-type]
            )
            expected_desc_1 = {
                "key": "profile:file:example",
                "type": "OriginalSignal",
                "message": "original signal object",
                "errno": None,
            }
            self.assertEqual(row_errors_1, [expected_desc_1])
            self.assertEqual(top_errors_1, [expected_desc_1])
            self.assertEqual(len(mutations_1), 1)
            self.assertEqual(len(causes_1), 1)
            self.assertEqual(mutations_1[0]["error"], expected_desc_1)
            self.assertIs(causes_1[0], caught_wrapper)
            self.assertIsInstance(causes_1[0], Exception)
            assert causes_1[0] is not None
            self.assertIs(causes_1[0].__cause__, orig_signal)

            # 2. End-to-end recheck_profile with an actual caught ValueError explicitly chained from custom BaseException
            # alongside a comparison-only mismatch, preserving original reachability, accurate descriptor, and alignment
            qc_fid = sorted(validated.roles["qc_evidence"])[0]
            qc_path = Path(validated.files[qc_fid].path)
            other_fid = sorted(validated.roles["qc_evidence"])[1]
            other_path = Path(validated.files[other_fid].path)
            other_path.write_bytes(other_path.read_bytes() + b"\n")

            orig_signal_eio = OriginalSignal(
                "custom signal during file pin observation", errno.EIO
            )
            real_obs_pin = profile_mod._observe_regular_file_pin
            caught_in_observer: list[ValueError] = []

            def obs_pin_raise_chained_signal(path, *args, **kwargs):
                if str(path) == str(qc_path):
                    try:
                        raise orig_signal_eio
                    except OriginalSignal as sig_exc:
                        try:
                            raise ValueError(
                                f"observer wrapper for {path!r}: {sig_exc}"
                            ) from sig_exc
                        except ValueError as wrapped_exc:
                            caught_in_observer.append(wrapped_exc)
                            raise
                return real_obs_pin(path, *args, **kwargs)

            causes_2: list[Exception | None] = []
            with mock.patch(
                "refmac_diagnostic_profile._observe_regular_file_pin",
                side_effect=obs_pin_raise_chained_signal,
            ):
                rep_2 = recheck_profile(validated, mutation_causes_out=causes_2)

            self.assertEqual(len(caught_in_observer), 1)
            self.assertIs(caught_in_observer[0].__cause__, orig_signal_eio)
            self.assertFalse(rep_2["verified"])
            self.assertEqual(len(rep_2["mutations"]), len(causes_2))

            expected_desc_2 = {
                "key": f"profile:file:{qc_fid}",
                "type": "OriginalSignal",
                "message": "custom signal during file pin observation",
                "errno": errno.EIO,
            }
            self.assertEqual(rep_2["files"][qc_fid]["errors"], [expected_desc_2])
            self.assertIn(expected_desc_2, rep_2["errors"])

            qc_mut_indices = [
                idx
                for idx, m in enumerate(rep_2["mutations"])
                if m["key"] == f"profile:file:{qc_fid}"
            ]
            self.assertEqual(len(qc_mut_indices), 1)
            qc_idx = qc_mut_indices[0]
            self.assertEqual(
                rep_2["mutations"][qc_idx]["error"], expected_desc_2
            )
            qc_cause = causes_2[qc_idx]
            self.assertIsInstance(qc_cause, Exception)
            assert qc_cause is not None
            self.assertTrue(
                profile_mod._cause_chain_reaches(qc_cause, orig_signal_eio)
            )
            self.assertIs(
                profile_mod._select_original_cause_exception(qc_cause),
                orig_signal_eio,
            )

            other_mut_indices = [
                idx
                for idx, m in enumerate(rep_2["mutations"])
                if m["key"] == f"profile:file:{other_fid}"
            ]
            self.assertEqual(len(other_mut_indices), 1)
            other_idx = other_mut_indices[0]
            self.assertIsNone(rep_2["mutations"][other_idx]["error"])
            self.assertIsNone(causes_2[other_idx])
            json.dumps(rep_2, allow_nan=False)


class TestTask851Issue1168PreOpenObservations(unittest.TestCase):
    """Focused synthetic tests for #1168 pre-open/initial-fstat lookup and traversal observation retention (Task 851)."""

    def _assert_pre_fstat_partial_obs(
        self,
        obs: PartialFileReadObservation,
        *,
        expected_lexical: str,
        expected_resolved: str,
        expected_lex_lstat: os.stat_result,
        expected_lex_stat: os.stat_result,
        expected_target_lstat: os.stat_result,
        expected_symlinks: tuple[_SymlinkEdge, ...],
        expected_ancestors_subset: set[str],
        expected_failure_phase: str,
    ) -> None:
        self.assertIsInstance(obs, PartialFileReadObservation)
        self.assertEqual(obs.path, expected_lexical)
        self.assertEqual(obs.resolved_path, expected_resolved)
        self.assertIsNone(obs.sha256)
        self.assertIsNone(obs.size_bytes)
        self.assertIsNone(obs.stat_size_bytes)
        self.assertEqual(obs.streamed_size_bytes, 0)
        self.assertFalse(obs.read_complete)
        self.assertFalse(obs.complete)
        self.assertFalse(obs.verified)
        self.assertFalse(obs.observed_eof)
        self.assertIsNone(obs.observed_stream_sha256)
        self.assertIsNone(obs.observed_eof_sha256)
        self.assertIsNone(obs.initial_fstat)
        self.assertIsNone(obs.end_fstat)
        self.assertEqual(obs.failure_phase, expected_failure_phase)
        self.assertIsNone(obs.post_read_observation)
        self.assertIsNone(obs.final_traversal_observation)
        self.assertIsNone(obs.final_resolution_observation)
        self.assertIsNone(obs.dev)
        self.assertIsNone(obs.ino)
        self.assertIsNone(obs.mode)
        self.assertIsNone(obs.uid)
        self.assertIsNone(obs.gid)
        self.assertIsNone(obs.identity_tuple)
        self.assertEqual(obs.symlinks, expected_symlinks)
        self.assertEqual(len(obs.symlink_identities), len(expected_symlinks))
        self.assertEqual(obs.unavailable_symlinks, ())
        self.assertEqual(
            [(s.path, s.target) for s in obs.symlink_identities],
            [(e.path, e.target) for e in expected_symlinks],
        )
        self.assertGreaterEqual(len(obs.ancestors), 1)
        self.assertTrue(
            expected_ancestors_subset.issubset({d.path for d in obs.ancestors})
        )
        self.assertTrue(obs.dependencies_complete)
        self.assertGreaterEqual(len(obs.errors), 1)

        snap = obs.lookup_snapshot
        self.assertIsInstance(snap, PreOpenLookupSnapshot)
        assert isinstance(snap, PreOpenLookupSnapshot)
        self.assertEqual(snap.lexical_path, expected_lexical)
        self.assertEqual(snap.path, expected_lexical)
        self.assertEqual(snap.resolved_path, expected_resolved)
        self.assertEqual(
            snap.lexical_lstat,
            LookupStatObservation.from_stat_result(expected_lex_lstat),
        )
        self.assertEqual(
            snap.lexical_stat,
            LookupStatObservation.from_stat_result(expected_lex_stat),
        )
        self.assertEqual(
            snap.resolved_target_lstat,
            LookupStatObservation.from_stat_result(expected_target_lstat),
        )
        self.assertEqual(snap.target_lstat, snap.resolved_target_lstat)
        self.assertEqual(snap.symlinks, expected_symlinks)
        self.assertEqual(snap.symlink_edges, expected_symlinks)
        self.assertEqual(snap.symlink_identities, obs.symlink_identities)
        self.assertEqual(snap.traversed_directories, obs.ancestors)
        self.assertEqual(snap.directory_identities, obs.ancestors)

        with self.assertRaisesRegex(
            ValueError, "cannot be converted to a FilePin"
        ):
            obs.as_file_pin()

    def test_1168_open_and_initial_fstat_failures_across_ordinary_intermediate_and_terminal_symlink_paths(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fx = _build_synthetic_outer_profile_fixture(Path(tmpdir))
            root = fx["root"]
            assert isinstance(root, Path)
            support_dir = root / "support"
            installed_record = fx["installed_record"]
            assert isinstance(installed_record, dict)
            ccp4_env = fx["ccp4_env"]
            assert isinstance(ccp4_env, dict)
            ev_root = fx["evidence_root"]
            assert isinstance(ev_root, Path)
            alias_symlink = fx["alias_symlink"]
            assert isinstance(alias_symlink, Path)
            base_payload = copy.deepcopy(fx["manifest_payload"])
            assert isinstance(base_payload, dict)

            # Prepare three declared external paths:
            # (a) ordinary regular-file path (launcher)
            launcher_fid = base_payload["roles"]["launcher"][0]  # type: ignore[index]
            launcher_lexical = str(base_payload["files"][launcher_fid]["path"])  # type: ignore[index]
            launcher_resolved = str(
                Path(launcher_lexical).resolve(strict=True)
            )

            # (b) intermediate symlink + '..' path: support/inter-link/sub/../inter-target.txt
            inter_real_dir = support_dir / "inter-real"
            inter_sub_dir = inter_real_dir / "sub"
            inter_sub_dir.mkdir(parents=True)
            inter_target = inter_real_dir / "inter-target.txt"
            inter_target.write_bytes(b"intermediate symlink dotdot payload\n")
            inter_link = support_dir / "inter-link"
            os.symlink("inter-real", inter_link)
            inter_lexical = f"{inter_link}/sub/../inter-target.txt"
            inter_resolved = str(inter_target.resolve(strict=True))
            inter_fid = "task851_inter_dotdot"

            # (c) terminal symlink path: alias_symlink -> collection-python
            alias_fid = next(
                fid
                for fid, row in base_payload["files"].items()  # type: ignore[union-attr]
                if row["path"] == str(alias_symlink)
            )
            alias_lexical = str(alias_symlink)
            alias_resolved = str(alias_symlink.resolve(strict=True))

            payload = copy.deepcopy(base_payload)
            inter_obs_init = _observe_regular_file_pin(inter_lexical)
            payload["files"][inter_fid] = inter_obs_init.to_manifest_row()  # type: ignore[index]
            payload["roles"]["qc_evidence"] = sorted(  # type: ignore[index]
                [*payload["roles"]["qc_evidence"], inter_fid]  # type: ignore[index]
            )
            profile = _rewrite_manifest_and_profile(fx, payload)

            validated = validate_profile(
                profile, installed_record, ccp4_env, ev_root
            )
            state = validated._outer_state
            assert state is not None
            baseline_prov = copy.deepcopy(validated.to_provenance())

            path_cases = (
                (
                    "ordinary",
                    launcher_fid,
                    launcher_lexical,
                    launcher_resolved,
                    (),
                    {str(root), str(support_dir)},
                    False,
                ),
                (
                    "intermediate_symlink_dotdot",
                    inter_fid,
                    inter_lexical,
                    inter_resolved,
                    (_SymlinkEdge(path=str(inter_link), target="inter-real"),),
                    {
                        str(root),
                        str(support_dir),
                        str(inter_real_dir),
                        str(inter_sub_dir),
                    },
                    False,
                ),
                (
                    "terminal_symlink",
                    alias_fid,
                    alias_lexical,
                    alias_resolved,
                    (
                        _SymlinkEdge(
                            path=str(alias_symlink),
                            target=os.readlink(alias_symlink),
                        ),
                    ),
                    {str(root), str(support_dir)},
                    True,
                ),
            )

            real_open = os.open
            real_fstat = os.fstat
            real_close = os.close

            for (
                case_name,
                target_fid,
                lexical_str,
                resolved_str,
                exp_symlinks,
                exp_anc_subset,
                expect_symlink_lstat,
            ) in path_cases:
                exp_lex_lstat = os.lstat(lexical_str)
                exp_lex_stat = os.stat(lexical_str)
                exp_target_lstat = os.lstat(resolved_str)
                self.assertEqual(
                    stat.S_ISLNK(exp_lex_lstat.st_mode), expect_symlink_lstat
                )
                self.assertTrue(stat.S_ISREG(exp_lex_stat.st_mode))
                self.assertTrue(stat.S_ISREG(exp_target_lstat.st_mode))
                if expect_symlink_lstat:
                    self.assertNotEqual(
                        int(exp_lex_lstat.st_ino), int(exp_lex_stat.st_ino)
                    )

                for stage_kind in ("open_fail", "initial_fstat_fail"):
                    expected_phase = (
                        "open"
                        if stage_kind == "open_fail"
                        else "initial_fstat"
                    )
                    with self.subTest(path_case=case_name, stage=stage_kind):
                        bystander_fd = real_open(launcher_resolved, os.O_RDONLY)
                        try:
                            if stage_kind == "open_fail":
                                injected_exc: OSError = PermissionError(
                                    errno.EACCES,
                                    f"synthetic #1168 open EACCES for {case_name}",
                                    resolved_str,
                                )
                            else:
                                injected_exc = OSError(
                                    errno.EIO,
                                    f"synthetic #1168 initial fstat EIO for {case_name}",
                                    resolved_str,
                                )

                            active_state = {
                                "in_target_lexical": False,
                                "target_fd": -1,
                                "opened_target_fds": [],
                                "closed_fds": [],
                                "injections": 0,
                            }
                            real_obs_pin = profile_mod._observe_regular_file_pin

                            def track_obs_pin(path, *args, **kwargs):
                                is_target = str(path) == lexical_str
                                if is_target:
                                    active_state["in_target_lexical"] = True
                                try:
                                    return real_obs_pin(path, *args, **kwargs)
                                finally:
                                    if is_target:
                                        active_state["in_target_lexical"] = False

                            def hooked_open(path, flags, *args, **kwargs):
                                if (
                                    active_state["in_target_lexical"]
                                    and active_state["injections"] == 0
                                    and str(path) == resolved_str
                                ):
                                    if stage_kind == "open_fail":
                                        active_state["injections"] += 1
                                        raise injected_exc
                                    fd = real_open(path, flags, *args, **kwargs)
                                    active_state["target_fd"] = fd
                                    active_state["opened_target_fds"].append(fd)
                                    return fd
                                return real_open(path, flags, *args, **kwargs)

                            def hooked_fstat(fd, *args, **kwargs):
                                if (
                                    stage_kind == "initial_fstat_fail"
                                    and active_state["in_target_lexical"]
                                    and active_state["injections"] == 0
                                    and fd == active_state["target_fd"]
                                ):
                                    active_state["injections"] += 1
                                    raise injected_exc
                                return real_fstat(fd, *args, **kwargs)

                            def hooked_close(fd):
                                active_state["closed_fds"].append(fd)
                                return real_close(fd)

                            # 1. Admission via validate_profile
                            with (
                                mock.patch(
                                    "refmac_diagnostic_profile._observe_regular_file_pin",
                                    side_effect=track_obs_pin,
                                ),
                                mock.patch(
                                    "refmac_diagnostic_profile.os.open",
                                    side_effect=hooked_open,
                                ),
                                mock.patch(
                                    "refmac_diagnostic_profile.os.fstat",
                                    side_effect=hooked_fstat,
                                ),
                                mock.patch(
                                    "refmac_diagnostic_profile.os.close",
                                    side_effect=hooked_close,
                                ),
                            ):
                                with self.assertRaises(
                                    ProfileValidationError
                                ) as adm_ctx:
                                    validate_profile(
                                        profile,
                                        installed_record,
                                        ccp4_env,
                                        ev_root,
                                    )

                            self.assertEqual(active_state["injections"], 1)
                            self.assertNotIn(
                                bystander_fd, active_state["closed_fds"]
                            )
                            self.assertEqual(
                                real_fstat(bystander_fd).st_ino,
                                os.lstat(launcher_resolved).st_ino,
                            )
                            if stage_kind == "open_fail":
                                self.assertEqual(
                                    active_state["opened_target_fds"], []
                                )
                            else:
                                self.assertEqual(
                                    len(active_state["opened_target_fds"]), 1
                                )
                                closed_target_fd = active_state[
                                    "opened_target_fds"
                                ][0]
                                self.assertIn(
                                    closed_target_fd, active_state["closed_fds"]
                                )
                                with self.assertRaises(OSError) as ebadf_ctx:
                                    real_fstat(closed_target_fd)
                                self.assertEqual(
                                    ebadf_ctx.exception.errno, errno.EBADF
                                )

                            adm_err = adm_ctx.exception
                            self.assertEqual(
                                adm_err.failed_check,
                                "outer_profile_files_and_roots",
                            )
                            self.assertIs(adm_err.cause_exception, injected_exc)
                            self.assertEqual(
                                adm_err.error_type, type(injected_exc).__name__
                            )
                            self.assertEqual(
                                adm_err.error_errno, injected_exc.errno
                            )
                            self.assertIsNone(adm_err.selected_executable)
                            self.assertFalse(adm_err.profile_files_verified)
                            self.assertEqual(len(adm_err.roots), 3)
                            self.assertEqual(
                                len(adm_err.files), len(payload["files"])  # type: ignore[arg-type]
                            )
                            adm_fobs = adm_err.files[target_fid]
                            assert isinstance(
                                adm_fobs, PartialFileReadObservation
                            )
                            self._assert_pre_fstat_partial_obs(
                                adm_fobs,
                                expected_lexical=lexical_str,
                                expected_resolved=resolved_str,
                                expected_lex_lstat=exp_lex_lstat,
                                expected_lex_stat=exp_lex_stat,
                                expected_target_lstat=exp_target_lstat,
                                expected_symlinks=exp_symlinks,
                                expected_ancestors_subset=exp_anc_subset,
                                expected_failure_phase=expected_phase,
                            )
                            if expect_symlink_lstat:
                                assert adm_fobs.lookup_snapshot is not None
                                self.assertTrue(
                                    adm_fobs.lookup_snapshot.lexical_lstat.is_symlink
                                )
                                self.assertFalse(
                                    adm_fobs.lookup_snapshot.lexical_lstat.is_regular
                                )
                                self.assertTrue(
                                    adm_fobs.lookup_snapshot.lexical_stat.is_regular
                                )
                                self.assertNotEqual(
                                    adm_fobs.lookup_snapshot.lexical_lstat.ino,
                                    adm_fobs.lookup_snapshot.lexical_stat.ino,
                                )

                            for fid, fobs in adm_err.files:
                                if fid == target_fid:
                                    self.assertIsInstance(
                                        fobs, PartialFileReadObservation
                                    )
                                else:
                                    self.assertIsInstance(fobs, FileObservation)
                                    self.assertTrue(fobs.verified)

                            adm_priv = adm_err.partial_observation
                            assert adm_priv is not None
                            self.assertNotIn(
                                target_fid, adm_priv.observed_files
                            )
                            self.assertNotIn(
                                target_fid, adm_priv.verified_files
                            )
                            self.assertNotIn(
                                target_fid, adm_priv.unverified_files
                            )
                            self.assertIn(target_fid, adm_priv.partial_files)
                            self.assertIs(
                                adm_priv.partial_files[target_fid], adm_fobs
                            )
                            for sym_edge in exp_symlinks:
                                self.assertIn(
                                    sym_edge.path, adm_priv.observed_symlinks
                                )

                            # Pure in-memory provenance serialization
                            with (
                                mock.patch(
                                    "refmac_diagnostic_profile.os.lstat",
                                    side_effect=AssertionError("no lstat"),
                                ),
                                mock.patch(
                                    "refmac_diagnostic_profile.os.stat",
                                    side_effect=AssertionError("no stat"),
                                ),
                                mock.patch(
                                    "refmac_diagnostic_profile.os.open",
                                    side_effect=AssertionError("no open"),
                                ),
                                mock.patch(
                                    "refmac_diagnostic_profile.os.readlink",
                                    side_effect=AssertionError("no readlink"),
                                ),
                            ):
                                adm_prov = adm_err.to_provenance()
                                adm_dict = adm_fobs.to_dict()
                            json.dumps(adm_prov, allow_nan=False)
                            self.assertEqual(
                                adm_prov["files"][target_fid], adm_dict
                            )
                            self.assertIsNone(adm_dict["dev"])
                            self.assertIsNone(adm_dict["ino"])
                            self.assertIsNone(adm_dict["mode"])
                            self.assertIsNone(adm_dict["uid"])
                            self.assertIsNone(adm_dict["gid"])
                            self.assertIsNone(adm_dict["stat_size_bytes"])
                            self.assertIsNone(adm_dict["sha256"])
                            self.assertIsNone(adm_dict["size_bytes"])
                            self.assertEqual(
                                adm_dict["streamed_size_bytes"], 0
                            )
                            self.assertFalse(adm_dict["read_complete"])
                            self.assertFalse(adm_dict["verified"])
                            self.assertFalse(adm_dict["observed_eof"])
                            self.assertIsNone(
                                adm_dict["observed_stream_sha256"]
                            )
                            self.assertIsNone(adm_dict["observed_eof_sha256"])
                            self.assertIsNone(adm_dict["initial_fstat"])
                            self.assertIsNone(adm_dict["end_fstat"])
                            self.assertEqual(
                                adm_dict["failure_phase"], expected_phase
                            )
                            self.assertIsNone(
                                adm_dict["post_read_observation"]
                            )
                            self.assertIsNone(
                                adm_dict["final_traversal_observation"]
                            )
                            self.assertIsNone(
                                adm_dict["final_resolution_observation"]
                            )
                            self.assertIsNotNone(adm_dict["lookup_snapshot"])
                            self.assertEqual(
                                adm_dict["lookup_snapshot"]["lexical_path"],
                                lexical_str,
                            )
                            self.assertEqual(
                                adm_dict["lookup_snapshot"]["resolved_path"],
                                resolved_str,
                            )

                            # 2. Private _reobserve_outer_profile_state and public recheck_profile
                            active_state["target_fd"] = -1
                            active_state["opened_target_fds"].clear()
                            active_state["closed_fds"].clear()
                            active_state["injections"] = 0

                            recheck_causes: list[Exception | None] = []
                            with (
                                mock.patch(
                                    "refmac_diagnostic_profile._observe_regular_file_pin",
                                    side_effect=track_obs_pin,
                                ),
                                mock.patch(
                                    "refmac_diagnostic_profile.os.open",
                                    side_effect=hooked_open,
                                ),
                                mock.patch(
                                    "refmac_diagnostic_profile.os.fstat",
                                    side_effect=hooked_fstat,
                                ),
                                mock.patch(
                                    "refmac_diagnostic_profile.os.close",
                                    side_effect=hooked_close,
                                ),
                            ):
                                priv_recheck = _reobserve_outer_profile_state(
                                    state
                                )
                                active_state["target_fd"] = -1
                                active_state["injections"] = 0
                                pub_report = recheck_profile(
                                    validated,
                                    mutation_causes_out=recheck_causes,
                                )

                            self.assertFalse(priv_recheck.verified)
                            self.assertNotIn(
                                target_fid, priv_recheck.observed_files
                            )
                            self.assertIn(
                                target_fid, priv_recheck.partial_files
                            )
                            priv_pobs = priv_recheck.partial_files[target_fid]
                            self.assertIs(
                                priv_recheck.file_observations[target_fid],
                                priv_pobs,
                            )
                            self._assert_pre_fstat_partial_obs(
                                priv_pobs,
                                expected_lexical=lexical_str,
                                expected_resolved=resolved_str,
                                expected_lex_lstat=exp_lex_lstat,
                                expected_lex_stat=exp_lex_stat,
                                expected_target_lstat=exp_target_lstat,
                                expected_symlinks=exp_symlinks,
                                expected_ancestors_subset=exp_anc_subset,
                                expected_failure_phase=expected_phase,
                            )
                            self.assertIs(
                                priv_recheck.file_causes[target_fid],
                                injected_exc,
                            )
                            self.assertIs(
                                priv_recheck.observation_causes[
                                    f"profile:file:{target_fid}"
                                ],
                                injected_exc,
                            )

                            self.assertFalse(pub_report["verified"])
                            frow = pub_report["files"][target_fid]
                            self.assertFalse(frow["matches_baseline"])
                            self.assertEqual(
                                frow["expected"],
                                baseline_prov["files"][target_fid],
                            )
                            self.assertIsNotNone(frow["observed"])
                            self.assertIsNone(frow["observed"]["dev"])
                            self.assertIsNone(frow["observed"]["ino"])
                            self.assertIsNone(
                                frow["observed"]["stat_size_bytes"]
                            )
                            self.assertFalse(frow["observed"]["observed_eof"])
                            self.assertIsNone(
                                frow["observed"]["initial_fstat"]
                            )
                            self.assertIsNone(frow["observed"]["end_fstat"])
                            self.assertEqual(
                                frow["observed"]["failure_phase"],
                                expected_phase,
                            )
                            self.assertIsNone(
                                frow["observed"]["post_read_observation"]
                            )
                            self.assertIsNone(
                                frow["observed"]["final_traversal_observation"]
                            )
                            self.assertIsNone(
                                frow["observed"][
                                    "final_resolution_observation"
                                ]
                            )
                            self.assertIsNotNone(
                                frow["observed"]["lookup_snapshot"]
                            )
                            self.assertEqual(
                                frow["errors"],
                                [
                                    {
                                        "key": f"profile:file:{target_fid}",
                                        "type": type(injected_exc).__name__,
                                        "message": str(injected_exc),
                                        "errno": injected_exc.errno,
                                    }
                                ],
                            )
                            self.assertEqual(len(pub_report["mutations"]), 1)
                            self.assertEqual(recheck_causes, [injected_exc])
                            self.assertIs(recheck_causes[0], injected_exc)
                            json.dumps(pub_report, allow_nan=False)
                        finally:
                            real_close(bystander_fd)

    def test_1168_manifest_open_and_initial_fstat_failures_across_admission_and_recheck(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fx = _build_synthetic_outer_profile_fixture(Path(tmpdir))
            root = fx["root"]
            assert isinstance(root, Path)
            installed_record = fx["installed_record"]
            assert isinstance(installed_record, dict)
            ccp4_env = fx["ccp4_env"]
            assert isinstance(ccp4_env, dict)
            ev_root = fx["evidence_root"]
            assert isinstance(ev_root, Path)
            manifest_path = fx["manifest_path"]
            assert isinstance(manifest_path, Path)
            profile = fx["profile"]
            assert isinstance(profile, RefmacDiagnosticProfile)

            # Create a terminal symlink to the manifest as well so we test both direct and symlinked manifest pins
            manifest_symlink = root / "manifest-link.json"
            os.symlink(manifest_path.name, manifest_symlink)
            symlink_profile = RefmacDiagnosticProfile(
                profile_id=profile.profile_id,
                manifest=FilePin(
                    path=str(manifest_symlink),
                    sha256=profile.manifest.sha256,
                    size_bytes=profile.manifest.size_bytes,
                ),
                executable=profile.executable,
            )
            validated_sym = validate_profile(
                symlink_profile, installed_record, ccp4_env, ev_root
            )
            state_sym = validated_sym._outer_state
            assert state_sym is not None

            real_open = os.open
            real_fstat = os.fstat
            manifest_resolved = str(manifest_path.resolve(strict=True))
            exp_lex_lstat = os.lstat(manifest_symlink)
            exp_lex_stat = os.stat(manifest_symlink)
            exp_target_lstat = os.lstat(manifest_resolved)
            exp_symlinks = (
                _SymlinkEdge(
                    path=str(manifest_symlink), target=manifest_path.name
                ),
            )

            for stage_kind in ("open_fail", "initial_fstat_fail"):
                expected_phase = (
                    "open"
                    if stage_kind == "open_fail"
                    else "initial_fstat"
                )
                with self.subTest(stage=stage_kind):
                    if stage_kind == "open_fail":
                        injected_exc: OSError = PermissionError(
                            errno.EACCES,
                            "synthetic #1168 manifest open EACCES",
                            manifest_resolved,
                        )
                    else:
                        injected_exc = OSError(
                            errno.EIO,
                            "synthetic #1168 manifest initial fstat EIO",
                            manifest_resolved,
                        )

                    m_state = {
                        "target_fd": -1,
                        "opened_fds": [],
                        "injections": 0,
                    }

                    def hooked_open_m(path, flags, *args, **kwargs):
                        if (
                            m_state["injections"] == 0
                            and str(path) == manifest_resolved
                        ):
                            if stage_kind == "open_fail":
                                m_state["injections"] += 1
                                raise injected_exc
                            fd = real_open(path, flags, *args, **kwargs)
                            m_state["target_fd"] = fd
                            m_state["opened_fds"].append(fd)
                            return fd
                        return real_open(path, flags, *args, **kwargs)

                    def hooked_fstat_m(fd, *args, **kwargs):
                        if (
                            stage_kind == "initial_fstat_fail"
                            and m_state["injections"] == 0
                            and fd == m_state["target_fd"]
                        ):
                            m_state["injections"] += 1
                            raise injected_exc
                        return real_fstat(fd, *args, **kwargs)

                    with (
                        mock.patch(
                            "refmac_diagnostic_profile.os.open",
                            side_effect=hooked_open_m,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.fstat",
                            side_effect=hooked_fstat_m,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile._parse_verified_json_bytes",
                            side_effect=AssertionError("must not parse JSON"),
                        ) as mocked_parse,
                        mock.patch(
                            "refmac_diagnostic_profile._validate_outer_manifest_shape",
                            side_effect=AssertionError(
                                "must not validate shape"
                            ),
                        ) as mocked_shape,
                        mock.patch(
                            "refmac_diagnostic_profile._observe_controlled_root",
                            side_effect=AssertionError(
                                "must not inspect roots"
                            ),
                        ) as mocked_root,
                    ):
                        with self.assertRaises(
                            ProfileValidationError
                        ) as m_ctx:
                            validate_profile(
                                symlink_profile,
                                installed_record,
                                ccp4_env,
                                ev_root,
                            )
                        mocked_parse.assert_not_called()
                        mocked_shape.assert_not_called()
                        mocked_root.assert_not_called()

                    if stage_kind == "initial_fstat_fail":
                        self.assertEqual(len(m_state["opened_fds"]), 1)
                        with self.assertRaises(OSError) as ebadf_ctx:
                            real_fstat(m_state["opened_fds"][0])
                        self.assertEqual(ebadf_ctx.exception.errno, errno.EBADF)

                    m_err = m_ctx.exception
                    self.assertEqual(m_err.failed_check, "manifest_pin")
                    self.assertIs(m_err.cause_exception, injected_exc)
                    self.assertEqual(
                        m_err.error_type, type(injected_exc).__name__
                    )
                    self.assertEqual(m_err.error_errno, injected_exc.errno)
                    self.assertEqual(len(m_err.files), 0)
                    self.assertEqual(len(m_err.roots), 0)
                    assert isinstance(
                        m_err.manifest_identity, PartialFileReadObservation
                    )
                    self._assert_pre_fstat_partial_obs(
                        m_err.manifest_identity,
                        expected_lexical=str(manifest_symlink),
                        expected_resolved=manifest_resolved,
                        expected_lex_lstat=exp_lex_lstat,
                        expected_lex_stat=exp_lex_stat,
                        expected_target_lstat=exp_target_lstat,
                        expected_symlinks=exp_symlinks,
                        expected_ancestors_subset={str(root)},
                        expected_failure_phase=expected_phase,
                    )
                    assert m_err.manifest_identity.lookup_snapshot is not None
                    self.assertTrue(
                        m_err.manifest_identity.lookup_snapshot.lexical_lstat.is_symlink
                    )
                    m_prov = m_err.to_provenance()
                    self.assertEqual(
                        m_prov["manifest"]["failure_phase"], expected_phase
                    )
                    self.assertIsNone(m_prov["manifest"]["initial_fstat"])
                    self.assertIsNone(m_prov["manifest"]["end_fstat"])
                    self.assertIsNone(
                        m_prov["manifest"]["post_read_observation"]
                    )

                    # Also verify postflight recheck on symlink_profile
                    m_state["target_fd"] = -1
                    m_state["opened_fds"].clear()
                    m_state["injections"] = 0
                    causes_m: list[Exception | None] = []
                    with (
                        mock.patch(
                            "refmac_diagnostic_profile.os.open",
                            side_effect=hooked_open_m,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.fstat",
                            side_effect=hooked_fstat_m,
                        ),
                    ):
                        priv_m = _reobserve_outer_profile_state(state_sym)
                        m_state["target_fd"] = -1
                        m_state["injections"] = 0
                        rep_m = recheck_profile(
                            validated_sym, mutation_causes_out=causes_m
                        )

                    self.assertFalse(priv_m.verified)
                    self.assertIsNone(priv_m.manifest_observation)
                    assert isinstance(
                        priv_m.partial_manifest_observation,
                        PartialFileReadObservation,
                    )
                    self._assert_pre_fstat_partial_obs(
                        priv_m.partial_manifest_observation,
                        expected_lexical=str(manifest_symlink),
                        expected_resolved=manifest_resolved,
                        expected_lex_lstat=exp_lex_lstat,
                        expected_lex_stat=exp_lex_stat,
                        expected_target_lstat=exp_target_lstat,
                        expected_symlinks=exp_symlinks,
                        expected_ancestors_subset={str(root)},
                        expected_failure_phase=expected_phase,
                    )
                    self.assertIs(priv_m.manifest_cause, injected_exc)
                    self.assertFalse(rep_m["verified"])
                    self.assertFalse(rep_m["manifest"]["matches_baseline"])
                    self.assertIsNone(rep_m["manifest"]["observed"]["dev"])
                    self.assertIsNone(
                        rep_m["manifest"]["observed"]["stat_size_bytes"]
                    )
                    self.assertFalse(
                        rep_m["manifest"]["observed"]["observed_eof"]
                    )
                    self.assertIsNone(
                        rep_m["manifest"]["observed"]["initial_fstat"]
                    )
                    self.assertIsNone(
                        rep_m["manifest"]["observed"]["end_fstat"]
                    )
                    self.assertEqual(
                        rep_m["manifest"]["observed"]["failure_phase"],
                        expected_phase,
                    )
                    self.assertIsNone(
                        rep_m["manifest"]["observed"]["post_read_observation"]
                    )
                    self.assertIsNotNone(
                        rep_m["manifest"]["observed"]["lookup_snapshot"]
                    )
                    self.assertEqual(causes_m, [injected_exc])
                    self.assertIs(causes_m[0], injected_exc)
                    json.dumps(rep_m, allow_nan=False)

    def test_1168_shared_dependency_failure_association_and_guardrail_boundaries(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fx = _build_synthetic_outer_profile_fixture(Path(tmpdir))
            root = fx["root"]
            assert isinstance(root, Path)
            support_dir = root / "support"
            installed_record = fx["installed_record"]
            assert isinstance(installed_record, dict)
            ccp4_env = fx["ccp4_env"]
            assert isinstance(ccp4_env, dict)
            ev_root = fx["evidence_root"]
            assert isinstance(ev_root, Path)
            alias_symlink = fx["alias_symlink"]
            assert isinstance(alias_symlink, Path)
            profile = fx["profile"]
            assert isinstance(profile, RefmacDiagnosticProfile)
            base_payload = fx["manifest_payload"]
            assert isinstance(base_payload, dict)

            validated = validate_profile(
                profile, installed_record, ccp4_env, ev_root
            )
            alias_fid = next(
                fid
                for fid, row in base_payload["files"].items()  # type: ignore[union-attr]
                if row["path"] == str(alias_symlink)
            )
            alias_resolved = str(alias_symlink.resolve(strict=True))
            last_fid = sorted(validated.files.keys())[-1]
            last_fpath = validated.files[last_fid].path

            open_eacces = PermissionError(
                errno.EACCES,
                "synthetic #1168 open EACCES on alias_symlink target",
                alias_resolved,
            )
            step4_support_perm = PermissionError(
                errno.EACCES,
                "synthetic #1168 Step 4 support_dir PermissionError",
                str(support_dir),
            )

            real_open = os.open
            real_obs_pin = profile_mod._observe_regular_file_pin
            real_dir_obs = profile_mod._observe_directory_identity
            step_state = {
                "current_lexical": None,
                "open_injected": False,
                "files_done": False,
            }

            def track_pin(path, *args, **kwargs):
                prev = step_state["current_lexical"]
                step_state["current_lexical"] = str(path)
                try:
                    return real_obs_pin(path, *args, **kwargs)
                finally:
                    step_state["current_lexical"] = prev
                    if str(path) == str(last_fpath):
                        step_state["files_done"] = True

            def open_fail_on_alias(path, flags, *args, **kwargs):
                if (
                    not step_state["open_injected"]
                    and step_state["current_lexical"] == str(alias_symlink)
                    and str(path) == alias_resolved
                ):
                    step_state["open_injected"] = True
                    raise open_eacces
                return real_open(path, flags, *args, **kwargs)

            def dir_obs_fail_support_in_step4(
                dir_path_str: str,
                *,
                require_no_symlink_ancestors: bool = False,
            ):
                if (
                    step_state["files_done"]
                    and str(dir_path_str) == str(support_dir)
                ):
                    raise ValueError(
                        f"Cannot lstat directory {dir_path_str!r} (PermissionError): {step4_support_perm}"
                    ) from step4_support_perm
                return real_dir_obs(
                    dir_path_str,
                    require_no_symlink_ancestors=require_no_symlink_ancestors,
                )

            causes: list[Exception | None] = []
            with (
                mock.patch(
                    "refmac_diagnostic_profile._observe_regular_file_pin",
                    side_effect=track_pin,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.open",
                    side_effect=open_fail_on_alias,
                ),
                mock.patch(
                    "refmac_diagnostic_profile._observe_directory_identity",
                    side_effect=dir_obs_fail_support_in_step4,
                ),
            ):
                rep = recheck_profile(validated, mutation_causes_out=causes)

            self.assertTrue(step_state["open_injected"])
            self.assertFalse(rep["verified"])
            alias_row = rep["files"][alias_fid]
            self.assertFalse(alias_row["matches_baseline"])
            self.assertIsNotNone(alias_row["observed"])
            self.assertIsNone(alias_row["observed"]["dev"])
            self.assertIsNone(alias_row["observed"]["stat_size_bytes"])
            self.assertFalse(alias_row["observed"]["observed_eof"])
            self.assertIsNone(alias_row["observed"]["initial_fstat"])
            self.assertIsNone(alias_row["observed"]["end_fstat"])
            self.assertEqual(alias_row["observed"]["failure_phase"], "open")
            self.assertIsNone(alias_row["observed"]["post_read_observation"])
            self.assertIsNotNone(alias_row["observed"]["lookup_snapshot"])
            self.assertEqual(len(alias_row["errors"]), 2)
            alias_muts = [
                (idx, m)
                for idx, m in enumerate(rep["mutations"])
                if m["key"] == f"profile:file:{alias_fid}"
            ]
            self.assertEqual(len(alias_muts), 2)
            self.assertIs(causes[alias_muts[0][0]], open_eacces)
            self.assertIs(causes[alias_muts[1][0]], step4_support_perm)

            # Verify validation guardrails on LookupStatObservation, PreOpenLookupSnapshot, and PartialFileReadObservation
            valid_stat = LookupStatObservation.from_stat_result(
                os.stat(alias_resolved)
            )
            with self.assertRaises(FrozenInstanceError):
                valid_stat.size_bytes = 0  # type: ignore[misc]
            with self.assertRaises(ValueError):
                LookupStatObservation(
                    dev=1,
                    ino=1,
                    mode=0o644,
                    uid=0,
                    gid=0,
                    size_bytes=1,
                    is_symlink=True,
                    is_regular=True,
                )
            with self.assertRaises(ValueError):
                PartialFileReadObservation(
                    path=alias_resolved,
                    resolved_path=alias_resolved,
                    stat_size_bytes=10,
                    dev=None,
                    ino=None,
                    mode=None,
                    uid=None,
                    gid=None,
                    errors=("stat_size without fstat identity must fail",),
                )

            # Verify out-of-scope boundaries stay plain ValueError (NOT _PartialFileReadError):
            # 1) Initial lookup failure before traversal completes
            with mock.patch(
                "refmac_diagnostic_profile.os.lstat",
                side_effect=FileNotFoundError(
                    errno.ENOENT, "missing", str(alias_symlink)
                ),
            ):
                with self.assertRaises(ValueError) as lstat_ctx:
                    profile_mod._stream_observe_regular_file(str(alias_symlink))
                self.assertNotIsInstance(
                    lstat_ctx.exception, profile_mod._PartialFileReadError
                )

            # 2) Incomplete traversal failure
            with mock.patch(
                "refmac_diagnostic_profile._traverse_path_components",
                side_effect=ValueError("synthetic mid-traversal failure"),
            ):
                with self.assertRaises(ValueError) as trav_ctx:
                    profile_mod._stream_observe_regular_file(str(alias_symlink))
                self.assertNotIsInstance(
                    trav_ctx.exception, profile_mod._PartialFileReadError
                )

            # 3) Descriptor identity mismatch after initial fstat succeeds
            real_fstat = os.fstat
            base_st = os.stat(alias_resolved)
            mismatch_st = os.stat_result(
                (
                    base_st.st_mode,
                    base_st.st_ino + 999999,
                    base_st.st_dev,
                    base_st.st_nlink,
                    base_st.st_uid,
                    base_st.st_gid,
                    base_st.st_size,
                    base_st.st_atime,
                    base_st.st_mtime,
                    base_st.st_ctime,
                )
            )
            with mock.patch(
                "refmac_diagnostic_profile.os.fstat",
                side_effect=lambda fd: mismatch_st,
            ):
                with self.assertRaises(ValueError) as id_mismatch_ctx:
                    profile_mod._stream_observe_regular_file(str(alias_symlink))
                self.assertNotIsInstance(
                    id_mismatch_ctx.exception, profile_mod._PartialFileReadError
                )

            # 4) Post-EOF fstat_after failure retains PartialFileReadObservation with observed_eof=True (#1168 Task 990)
            fstat_calls = {"count": 0}
            fstat_after_eio = OSError(errno.EIO, "synthetic fstat_after EIO")
            expected_alias_bytes = Path(alias_resolved).read_bytes()
            expected_alias_sha = _sha256_bytes(expected_alias_bytes)

            def fstat_fail_second(fd: int):
                fstat_calls["count"] += 1
                if fstat_calls["count"] == 2:
                    raise fstat_after_eio
                return real_fstat(fd)

            with mock.patch(
                "refmac_diagnostic_profile.os.fstat",
                side_effect=fstat_fail_second,
            ):
                with self.assertRaises(
                    profile_mod._PartialFileReadError
                ) as post_eof_ctx:
                    profile_mod._stream_observe_regular_file(str(alias_symlink))
                self.assertIs(post_eof_ctx.exception.__cause__, fstat_after_eio)
                post_eof_obs = post_eof_ctx.exception.observation
                self.assertTrue(post_eof_obs.observed_eof)
                self.assertEqual(
                    post_eof_obs.streamed_size_bytes, len(expected_alias_bytes)
                )
                self.assertEqual(
                    post_eof_obs.observed_stream_sha256, expected_alias_sha
                )
                self.assertEqual(
                    post_eof_obs.observed_eof_sha256, expected_alias_sha
                )
                self.assertIsNone(post_eof_obs.end_fstat)
                self.assertEqual(post_eof_obs.failure_phase, "end_fstat")
                self.assertIsNone(post_eof_obs.sha256)
                self.assertIsNone(post_eof_obs.size_bytes)
                self.assertFalse(post_eof_obs.read_complete)

    def test_1168_partial_owner_dependency_conflicts_across_declared_file_and_manifest_stages(
        self,
    ) -> None:
        # 1. Declared-file partial owner (open and initial_fstat) with shared-symlink inode conflict
        for stage in ("open", "initial_fstat"):
            with self.subTest(owner="declared_file", stage=stage):
                with tempfile.TemporaryDirectory() as tmpdir:
                    fx = _build_synthetic_outer_profile_fixture(Path(tmpdir))
                    root = fx["root"]
                    assert isinstance(root, Path)
                    alias_symlink = fx["alias_symlink"]
                    assert isinstance(alias_symlink, Path)
                    installed_record = fx["installed_record"]
                    assert isinstance(installed_record, dict)
                    ccp4_env = fx["ccp4_env"]
                    assert isinstance(ccp4_env, dict)
                    ev_root = fx["evidence_root"]
                    assert isinstance(ev_root, Path)
                    payload = copy.deepcopy(fx["manifest_payload"])
                    assert isinstance(payload, dict)

                    first_fid = next(
                        fid
                        for fid, row in payload["files"].items()  # type: ignore[union-attr]
                        if row["path"] == str(alias_symlink)
                    )
                    second_fid = "zz_second_shared_symlink_user"
                    second_path = f"{root}/support/bin/../python-alias"
                    payload["files"][second_fid] = (  # type: ignore[index]
                        _observe_regular_file_pin(second_path).to_manifest_row()
                    )
                    payload["roles"]["qc_evidence"] = sorted(  # type: ignore[index]
                        [*payload["roles"]["qc_evidence"], second_fid]  # type: ignore[index]
                    )
                    profile = _rewrite_manifest_and_profile(fx, payload)

                    positive = validate_profile(
                        profile, installed_record, ccp4_env, ev_root
                    )
                    self.assertEqual(len(positive.files), 60)
                    self.assertEqual(len(positive.roots), 3)

                    target_resolved = str(alias_symlink.resolve(strict=True))
                    park_link = alias_symlink.with_name(
                        "python-alias.owned-old"
                    )
                    real_deps = profile_mod._collect_file_dependencies
                    real_observe = profile_mod._observe_regular_file_pin
                    real_open = os.open
                    real_fstat = os.fstat
                    armed: list[bool] = []
                    inodes: list[int] = []
                    fds: list[int] = []
                    fired: list[bool] = []
                    injected = OSError(
                        errno.EIO, f"owned late-alias {stage}"
                    )

                    def deps_replace_link(file_obs, **kw):
                        res = real_deps(file_obs, **kw)
                        if file_obs.path == str(alias_symlink):
                            inodes.append(os.lstat(alias_symlink).st_ino)
                            alias_symlink.rename(park_link)
                            alias_symlink.symlink_to("collection-python")
                            inodes.append(os.lstat(alias_symlink).st_ino)
                        return res

                    def observe_track_second(path, *a, **kw):
                        if path != second_path:
                            return real_observe(path, *a, **kw)
                        armed.append(True)
                        try:
                            return real_observe(path, *a, **kw)
                        finally:
                            armed.pop()

                    def open_inject(path, flags, *a, **kw):
                        if (
                            armed
                            and str(path) == target_resolved
                            and stage == "open"
                            and not fired
                        ):
                            fired.append(True)
                            raise injected
                        fd = real_open(path, flags, *a, **kw)
                        if armed and str(path) == target_resolved:
                            fds.append(fd)
                        return fd

                    def fstat_inject(fd):
                        if (
                            armed
                            and fd in fds
                            and stage == "initial_fstat"
                            and not fired
                        ):
                            fired.append(True)
                            raise injected
                        return real_fstat(fd)

                    with (
                        mock.patch(
                            "refmac_diagnostic_profile._collect_file_dependencies",
                            side_effect=deps_replace_link,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile._observe_regular_file_pin",
                            side_effect=observe_track_second,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.open",
                            side_effect=open_inject,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.fstat",
                            side_effect=fstat_inject,
                        ),
                    ):
                        with self.assertRaises(
                            ProfileValidationError
                        ) as fail_ctx:
                            validate_profile(
                                profile, installed_record, ccp4_env, ev_root
                            )

                    self.assertEqual(fired, [True])
                    self.assertEqual(len(inodes), 2)
                    self.assertNotEqual(inodes[0], inodes[1])
                    if stage == "initial_fstat":
                        self.assertEqual(len(fds), 1)
                        with self.assertRaises(OSError) as ebadf_ctx:
                            real_fstat(fds[0])
                        self.assertEqual(
                            ebadf_ctx.exception.errno, errno.EBADF
                        )

                    failure = fail_ctx.exception
                    self.assertEqual(
                        failure.failed_check, "outer_profile_files_and_roots"
                    )
                    self.assertIs(failure.cause_exception, injected)
                    self.assertEqual(failure.error_type, "OSError")
                    self.assertEqual(failure.error_errno, errno.EIO)
                    self.assertIsNone(failure.selected_executable)
                    self.assertFalse(failure.profile_files_verified)
                    self.assertEqual(len(failure.roots), 3)
                    self.assertEqual(len(failure.files), 60)

                    for fid, fobs in failure.files:
                        if fid == second_fid:
                            self.assertIsInstance(
                                fobs, PartialFileReadObservation
                            )
                        else:
                            self.assertIsInstance(fobs, FileObservation)
                            self.assertTrue(fobs.verified)
                            self.assertTrue(fobs.dependencies_complete)

                    fobs_first = failure.files[first_fid]
                    self.assertEqual(
                        fobs_first.symlink_identities[0].ino, inodes[0]
                    )
                    fobs_second = failure.files[second_fid]
                    assert isinstance(fobs_second, PartialFileReadObservation)
                    partial = failure.partial_observation
                    assert partial is not None
                    self.assertIs(partial.partial_files[second_fid], fobs_second)
                    self.assertIs(
                        partial.file_observations[second_fid], fobs_second
                    )
                    self.assertEqual(
                        partial.observed_symlinks[str(alias_symlink)].ino,
                        inodes[0],
                    )
                    dep = partial.file_dependencies[second_fid]
                    self.assertFalse(dep.complete)
                    self.assertEqual(len(dep.errors), 1)
                    self.assertIn(
                        "Symlink identity changed during observation",
                        dep.errors[0],
                    )

                    self.assertFalse(fobs_second.dependencies_complete)
                    self.assertFalse(fobs_second.complete)
                    self.assertFalse(fobs_second.verified)
                    self.assertFalse(fobs_second.read_complete)
                    self.assertIsNone(fobs_second.sha256)
                    self.assertIsNone(fobs_second.size_bytes)
                    self.assertIsNone(fobs_second.stat_size_bytes)
                    self.assertEqual(fobs_second.streamed_size_bytes, 0)
                    self.assertIsNone(fobs_second.dev)
                    self.assertIsNone(fobs_second.ino)
                    self.assertIsNone(fobs_second.mode)
                    self.assertIsNone(fobs_second.uid)
                    self.assertIsNone(fobs_second.gid)
                    self.assertIsNone(fobs_second.identity_tuple)
                    self.assertFalse(fobs_second.observed_eof)
                    self.assertIsNone(fobs_second.initial_fstat)
                    self.assertIsNone(fobs_second.end_fstat)
                    self.assertEqual(fobs_second.failure_phase, stage)
                    self.assertIsNone(fobs_second.post_read_observation)
                    self.assertIsNone(fobs_second.final_traversal_observation)
                    self.assertIsNone(fobs_second.final_resolution_observation)
                    self.assertEqual(
                        fobs_second.symlink_identities[0].ino, inodes[1]
                    )
                    self.assertEqual(fobs_second.unavailable_symlinks, ())
                    assert fobs_second.lookup_snapshot is not None
                    self.assertEqual(
                        fobs_second.lookup_snapshot.symlink_identities[0].ino,
                        inodes[1],
                    )
                    self.assertEqual(len(fobs_second.errors), 2)
                    self.assertTrue(
                        fobs_second.errors[0].startswith(
                            "Failed reading regular file "
                        )
                    )
                    self.assertFalse(
                        profile_mod._is_size_mismatch_partial_observation(
                            fobs_second
                        )
                    )
                    self.assertEqual(fobs_second.errors[1], dep.errors[0])
                    self.assertEqual(
                        list(failure.errors), list(fobs_second.errors)
                    )
                    self.assertEqual(len(failure.error_records), 2)
                    self.assertIs(
                        failure.error_records[0].exception.__cause__, injected
                    )
                    self.assertEqual(
                        failure.error_records[0].error_type, "OSError"
                    )
                    self.assertEqual(
                        failure.error_records[0].error_errno, errno.EIO
                    )
                    self.assertEqual(
                        failure.error_records[1].error_type, "ValueError"
                    )
                    self.assertIsNone(failure.error_records[1].error_errno)
                    self.assertIsNone(
                        failure.error_records[1].exception.__cause__
                    )

                    # Pure in-memory projection with poisoned filesystem entry points
                    with (
                        mock.patch(
                            "refmac_diagnostic_profile.os.lstat",
                            side_effect=AssertionError("no lstat"),
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.stat",
                            side_effect=AssertionError("no stat"),
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.readlink",
                            side_effect=AssertionError("no readlink"),
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.open",
                            side_effect=AssertionError("no open"),
                        ),
                    ):
                        public = failure.to_provenance()
                        reproj_with_deps = (
                            profile_mod._build_partial_file_observation(
                                fobs_second,
                                observed_ancestors=partial.observed_ancestors,
                                observed_symlinks=partial.observed_symlinks,
                                file_dependencies=dep,
                            )
                        )
                        reproj_from_maps = (
                            profile_mod._build_partial_file_observation(
                                PartialFileReadObservation(
                                    path=fobs_second.path,
                                    resolved_path=fobs_second.resolved_path,
                                    symlinks=fobs_second.symlinks,
                                    symlink_identities=fobs_second.symlink_identities,
                                    ancestors=fobs_second.ancestors,
                                    dependencies_complete=True,
                                    errors=(fobs_second.errors[0],),
                                    lookup_snapshot=fobs_second.lookup_snapshot,
                                    failure_phase=fobs_second.failure_phase,
                                ),
                                observed_ancestors=partial.observed_ancestors,
                                observed_symlinks=partial.observed_symlinks,
                            )
                        )
                        incomplete_preserved = (
                            profile_mod._build_partial_file_observation(
                                PartialFileReadObservation(
                                    path=fobs_second.path,
                                    resolved_path=fobs_second.resolved_path,
                                    symlinks=fobs_second.symlinks,
                                    symlink_identities=(),
                                    ancestors=fobs_second.ancestors,
                                    dependencies_complete=False,
                                    errors=(fobs_second.errors[0],),
                                    failure_phase=fobs_second.failure_phase,
                                ),
                                observed_ancestors=partial.observed_ancestors,
                                observed_symlinks=partial.observed_symlinks,
                            )
                        )

                    self.assertIs(reproj_with_deps, fobs_second)
                    self.assertEqual(reproj_from_maps, fobs_second)
                    self.assertFalse(
                        incomplete_preserved.dependencies_complete
                    )
                    self.assertEqual(incomplete_preserved.failure_phase, stage)
                    pub_fobs = public["files"][second_fid]
                    self.assertFalse(pub_fobs["dependencies_complete"])
                    self.assertFalse(pub_fobs["verified"])
                    self.assertEqual(pub_fobs["failure_phase"], stage)
                    self.assertIsNone(pub_fobs["initial_fstat"])
                    self.assertIsNone(pub_fobs["end_fstat"])
                    self.assertIsNone(pub_fobs["post_read_observation"])
                    self.assertEqual(
                        pub_fobs["symlink_identities"][0]["ino"], inodes[1]
                    )
                    self.assertEqual(
                        public["files"][first_fid]["symlink_identities"][0][
                            "ino"
                        ],
                        inodes[0],
                    )
                    self.assertEqual(
                        pub_fobs["errors"], list(fobs_second.errors)
                    )
                    self.assertEqual(
                        public["errors"], list(fobs_second.errors)
                    )

        # 2. Manifest partial owner (open and initial_fstat) with shared ancestor-directory mode conflict
        for stage in ("open", "initial_fstat"):
            with self.subTest(owner="manifest", stage=stage):
                with tempfile.TemporaryDirectory() as tmpdir:
                    owned = Path(tmpdir).resolve(strict=True)
                    fx = _build_synthetic_outer_profile_fixture(owned)
                    installed_record = fx["installed_record"]
                    assert isinstance(installed_record, dict)
                    ccp4_env = fx["ccp4_env"]
                    assert isinstance(ccp4_env, dict)
                    ev_root = fx["evidence_root"]
                    assert isinstance(ev_root, Path)
                    manifest_path = fx["manifest_path"]
                    assert isinstance(manifest_path, Path)
                    profile = fx["profile"]
                    assert isinstance(profile, RefmacDiagnosticProfile)

                    positive_m = validate_profile(
                        profile, installed_record, ccp4_env, ev_root
                    )
                    self.assertEqual(len(positive_m.files), 59)
                    self.assertEqual(len(positive_m.roots), 3)

                    target_m = str(manifest_path.resolve(strict=True))
                    oldmode = stat.S_IMODE(owned.stat().st_mode)
                    newmode = oldmode ^ stat.S_IXOTH
                    real_ev = profile_mod._validate_and_observe_evidence_root
                    real_open = os.open
                    real_fstat = os.fstat
                    changed_m: list[bool] = []
                    fired_m: list[bool] = []
                    fds_m: list[int] = []
                    injected_m = OSError(
                        errno.EIO, f"owned manifest {stage}"
                    )

                    def ev_chmod_after(*a, **kw):
                        res = real_ev(*a, **kw)
                        self.assertTrue(
                            any(x.path == str(owned) for x in res[1])
                        )
                        owned.chmod(newmode)
                        changed_m.append(True)
                        return res

                    def open_m_inject(path, flags, *a, **kw):
                        if (
                            str(path) == target_m
                            and stage == "open"
                            and not fired_m
                        ):
                            fired_m.append(True)
                            raise injected_m
                        fd = real_open(path, flags, *a, **kw)
                        if str(path) == target_m:
                            fds_m.append(fd)
                        return fd

                    def fstat_m_inject(fd):
                        if (
                            fd in fds_m
                            and stage == "initial_fstat"
                            and not fired_m
                        ):
                            fired_m.append(True)
                            raise injected_m
                        return real_fstat(fd)

                    try:
                        with (
                            mock.patch(
                                "refmac_diagnostic_profile._validate_and_observe_evidence_root",
                                side_effect=ev_chmod_after,
                            ),
                            mock.patch(
                                "refmac_diagnostic_profile.os.open",
                                side_effect=open_m_inject,
                            ),
                            mock.patch(
                                "refmac_diagnostic_profile.os.fstat",
                                side_effect=fstat_m_inject,
                            ),
                            mock.patch(
                                "refmac_diagnostic_profile._parse_verified_json_bytes",
                                side_effect=AssertionError(
                                    "must not parse unverified manifest"
                                ),
                            ) as mocked_parse,
                            mock.patch(
                                "refmac_diagnostic_profile._observe_controlled_root",
                                side_effect=AssertionError(
                                    "must not inspect controlled roots"
                                ),
                            ) as mocked_root,
                        ):
                            with self.assertRaises(
                                ProfileValidationError
                            ) as m_ctx:
                                validate_profile(
                                    profile,
                                    installed_record,
                                    ccp4_env,
                                    ev_root,
                                )
                            mocked_parse.assert_not_called()
                            mocked_root.assert_not_called()
                    finally:
                        owned.chmod(oldmode)

                    self.assertEqual(changed_m, [True])
                    self.assertEqual(fired_m, [True])
                    if stage == "initial_fstat":
                        self.assertEqual(len(fds_m), 1)
                        with self.assertRaises(OSError) as ebadf_m_ctx:
                            real_fstat(fds_m[0])
                        self.assertEqual(
                            ebadf_m_ctx.exception.errno, errno.EBADF
                        )

                    m_fail = m_ctx.exception
                    self.assertEqual(m_fail.failed_check, "manifest_pin")
                    self.assertIs(m_fail.cause_exception, injected_m)
                    self.assertEqual(m_fail.error_type, "OSError")
                    self.assertEqual(m_fail.error_errno, errno.EIO)
                    self.assertEqual(len(m_fail.files), 0)
                    self.assertEqual(len(m_fail.roots), 0)
                    self.assertIsNone(m_fail.selected_executable)
                    self.assertFalse(m_fail.profile_files_verified)

                    m_partial = m_fail.partial_observation
                    assert m_partial is not None
                    self.assertEqual(
                        m_partial.observed_ancestors[str(owned)].mode, oldmode
                    )
                    m_dep = m_partial.manifest_dependencies
                    assert m_dep is not None
                    self.assertFalse(m_dep.complete)
                    self.assertEqual(len(m_dep.errors), 1)
                    self.assertIn(
                        "Directory identity changed during observation",
                        m_dep.errors[0],
                    )

                    m_obs = m_fail.manifest_identity
                    assert isinstance(m_obs, PartialFileReadObservation)
                    self.assertIs(m_partial.partial_manifest_observation, m_obs)
                    self.assertIs(m_partial.manifest_file_observation, m_obs)
                    self.assertFalse(m_obs.dependencies_complete)
                    self.assertFalse(m_obs.complete)
                    self.assertFalse(m_obs.verified)
                    self.assertFalse(m_obs.read_complete)
                    self.assertIsNone(m_obs.sha256)
                    self.assertIsNone(m_obs.size_bytes)
                    self.assertIsNone(m_obs.stat_size_bytes)
                    self.assertEqual(m_obs.streamed_size_bytes, 0)
                    self.assertIsNone(m_obs.dev)
                    self.assertIsNone(m_obs.ino)
                    self.assertIsNone(m_obs.mode)
                    self.assertIsNone(m_obs.uid)
                    self.assertIsNone(m_obs.gid)
                    self.assertIsNone(m_obs.identity_tuple)
                    self.assertFalse(m_obs.observed_eof)
                    self.assertIsNone(m_obs.initial_fstat)
                    self.assertIsNone(m_obs.end_fstat)
                    self.assertEqual(m_obs.failure_phase, stage)
                    self.assertIsNone(m_obs.post_read_observation)
                    self.assertIsNone(m_obs.final_traversal_observation)
                    self.assertIsNone(m_obs.final_resolution_observation)
                    owned_anc_obs = next(
                        d for d in m_obs.ancestors if d.path == str(owned)
                    )
                    self.assertEqual(owned_anc_obs.mode, newmode)
                    assert m_obs.lookup_snapshot is not None
                    owned_snap_obs = next(
                        d
                        for d in m_obs.lookup_snapshot.traversed_directories
                        if d.path == str(owned)
                    )
                    self.assertEqual(owned_snap_obs.mode, newmode)
                    self.assertEqual(len(m_obs.errors), 2)
                    self.assertTrue(
                        m_obs.errors[0].startswith(
                            "Failed reading regular file "
                        )
                    )
                    self.assertEqual(m_obs.errors[1], m_dep.errors[0])
                    self.assertEqual(list(m_fail.errors), list(m_obs.errors))
                    self.assertEqual(len(m_fail.error_records), 2)
                    self.assertIs(
                        m_fail.error_records[0].exception.__cause__, injected_m
                    )
                    self.assertEqual(
                        m_fail.error_records[1].error_type, "ValueError"
                    )
                    self.assertIsNone(m_fail.error_records[1].error_errno)
                    self.assertIsNone(
                        m_fail.error_records[1].exception.__cause__
                    )

                    # Pure in-memory provenance serialization after fixture restoration
                    with (
                        mock.patch(
                            "refmac_diagnostic_profile.os.lstat",
                            side_effect=AssertionError("no lstat"),
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.stat",
                            side_effect=AssertionError("no stat"),
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.readlink",
                            side_effect=AssertionError("no readlink"),
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.open",
                            side_effect=AssertionError("no open"),
                        ),
                    ):
                        m_pub = m_fail.to_provenance()

                    self.assertFalse(
                        m_pub["manifest"]["dependencies_complete"]
                    )
                    self.assertFalse(m_pub["manifest"]["verified"])
                    self.assertEqual(m_pub["manifest"]["failure_phase"], stage)
                    self.assertIsNone(m_pub["manifest"]["initial_fstat"])
                    self.assertIsNone(m_pub["manifest"]["end_fstat"])
                    self.assertIsNone(
                        m_pub["manifest"]["post_read_observation"]
                    )
                    self.assertEqual(
                        m_pub["manifest"]["errors"], list(m_obs.errors)
                    )
                    self.assertEqual(m_pub["errors"], list(m_obs.errors))
                    self.assertEqual(m_pub["files"], {})
                    self.assertEqual(m_pub["roots"], {})
                    self.assertFalse(m_pub["profile_files_verified"])


class TestTask990Issue1168PostEofObservations(unittest.TestCase):
    """Focused synthetic tests for #1168 post-EOF observation retention (Task 990)."""

    def test_task990_post_eof_observation_core_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve(strict=True)
            sub_dir = root / "sub"
            alt_dir = root / "alt"
            sub_dir.mkdir(parents=True)
            alt_dir.mkdir(parents=True)

            reg_file = sub_dir / "payload.txt"
            reg_bytes = b"0123456789abcdef-post-eof-payload\n"
            reg_sha = _sha256_bytes(reg_bytes)
            reg_file.write_bytes(reg_bytes)

            empty_file = sub_dir / "empty.txt"
            empty_file.write_bytes(b"")
            empty_sha = _sha256_bytes(b"")

            alt_file = alt_dir / "alt_payload.txt"
            alt_bytes = b"SameLengthReplacementForPostEof!!\n"
            self.assertEqual(len(alt_bytes), len(reg_bytes))
            alt_file.write_bytes(alt_bytes)

            sym_alias = root / "payload-link.txt"
            os.symlink("sub/payload.txt", sym_alias)

            # 1. Healthy regular-file, symlink-alias, and empty-file positive controls
            ok_reg, ok_reg_raw = profile_mod._stream_observe_regular_file(
                str(reg_file), retain_bytes=True
            )
            self.assertIsInstance(ok_reg, _ObservedRegularFilePin)
            self.assertEqual(ok_reg.sha256, reg_sha)
            self.assertEqual(ok_reg.size_bytes, len(reg_bytes))
            self.assertEqual(ok_reg_raw, reg_bytes)

            ok_empty, ok_empty_raw = profile_mod._stream_observe_regular_file(
                str(empty_file), retain_bytes=True
            )
            self.assertIsInstance(ok_empty, _ObservedRegularFilePin)
            self.assertEqual(ok_empty.sha256, empty_sha)
            self.assertEqual(ok_empty.size_bytes, 0)
            self.assertEqual(ok_empty_raw, b"")

            ok_sym, _ = profile_mod._stream_observe_regular_file(str(sym_alias))
            self.assertIsInstance(ok_sym, _ObservedRegularFilePin)
            self.assertEqual(ok_sym.path, str(sym_alias))
            self.assertEqual(ok_sym.resolved_path, str(reg_file))
            self.assertEqual(ok_sym.sha256, reg_sha)

            real_open = os.open
            real_fdopen = os.fdopen
            real_fstat = os.fstat

            # 2. True EOF (chunk == b"") followed by end_fstat EIO on both non-empty and 0-byte empty files
            # (with a bystander fd open so global fstat call count is not assumed)
            bystander_fd = real_open(str(reg_file), os.O_RDONLY)
            try:
                for case_label, target_lexical, target_resolved, exp_bytes in (
                    ("non_empty_symlink", str(sym_alias), str(reg_file), reg_bytes),
                    ("zero_byte_empty", str(empty_file), str(empty_file), b""),
                ):
                    with self.subTest(end_fstat_case=case_label):
                        exp_st_before = os.stat(target_resolved)
                        end_fstat_eio = OSError(
                            errno.EIO, f"synthetic end_fstat EIO ({case_label})"
                        )
                        fd_state: dict[str, Any] = {
                            "owned_fd": -1,
                            "fstat_count_for_owned": 0,
                        }

                        def open_for_end_fstat(path, flags, *a, **kw):
                            fd = real_open(path, flags, *a, **kw)
                            if str(path) == target_resolved:
                                fd_state["owned_fd"] = fd
                            return fd

                        def fstat_for_end_fstat(fd: int):
                            _ = real_fstat(bystander_fd)
                            if fd == fd_state["owned_fd"]:
                                fd_state["fstat_count_for_owned"] += 1
                                if fd_state["fstat_count_for_owned"] == 2:
                                    raise end_fstat_eio
                            return real_fstat(fd)

                        with (
                            mock.patch(
                                "refmac_diagnostic_profile.os.open",
                                side_effect=open_for_end_fstat,
                            ),
                            mock.patch(
                                "refmac_diagnostic_profile.os.fstat",
                                side_effect=fstat_for_end_fstat,
                            ),
                        ):
                            with self.assertRaises(
                                _PartialFileReadError
                            ) as ef_ctx:
                                profile_mod._stream_observe_regular_file(
                                    target_lexical,
                                    chunk_size=7,
                                    retain_bytes=True,
                                )
                        self.assertGreater(fd_state["owned_fd"], 0)
                        self.assertEqual(fd_state["fstat_count_for_owned"], 2)
                        with self.assertRaises(OSError) as ebadf_ef:
                            real_fstat(fd_state["owned_fd"])
                        self.assertEqual(ebadf_ef.exception.errno, errno.EBADF)

                        self.assertIs(ef_ctx.exception.__cause__, end_fstat_eio)
                        ef_obs = ef_ctx.exception.observation
                        self.assertTrue(ef_obs.observed_eof)
                        self.assertEqual(
                            ef_obs.streamed_size_bytes, len(exp_bytes)
                        )
                        self.assertEqual(
                            ef_obs.stat_size_bytes, int(exp_st_before.st_size)
                        )
                        self.assertEqual(
                            ef_obs.observed_stream_sha256,
                            _sha256_bytes(exp_bytes),
                        )
                        self.assertEqual(
                            ef_obs.observed_eof_sha256,
                            _sha256_bytes(exp_bytes),
                        )
                        self.assertEqual(
                            ef_obs.initial_fstat,
                            LookupStatObservation.from_stat_result(
                                exp_st_before
                            ),
                        )
                        self.assertIsNone(ef_obs.end_fstat)
                        self.assertEqual(ef_obs.failure_phase, "end_fstat")
                        self.assertIsNone(ef_obs.sha256)
                        self.assertIsNone(ef_obs.size_bytes)
                        self.assertFalse(ef_obs.read_complete)
                        self.assertFalse(ef_obs.verified)

                # 4. Descriptor identity conflict and descriptor size conflict at end_fstat
                base_reg_st = os.stat(reg_file)
                changed_ino_st = os.stat_result(
                    (
                        base_reg_st.st_mode,
                        base_reg_st.st_ino + 424242,
                        base_reg_st.st_dev,
                        base_reg_st.st_nlink,
                        base_reg_st.st_uid,
                        base_reg_st.st_gid,
                        base_reg_st.st_size,
                        base_reg_st.st_atime,
                        base_reg_st.st_mtime,
                        base_reg_st.st_ctime,
                    )
                )
                changed_size_st = os.stat_result(
                    (
                        base_reg_st.st_mode,
                        base_reg_st.st_ino,
                        base_reg_st.st_dev,
                        base_reg_st.st_nlink,
                        base_reg_st.st_uid,
                        base_reg_st.st_gid,
                        base_reg_st.st_size + 19,
                        base_reg_st.st_atime,
                        base_reg_st.st_mtime,
                        base_reg_st.st_ctime,
                    )
                )
                for conflict_phase, synthetic_after_st in (
                    ("descriptor_identity_comparison", changed_ino_st),
                    ("descriptor_size_comparison", changed_size_st),
                ):
                    with self.subTest(descriptor_conflict=conflict_phase):
                        d_state = {"owned_fd": -1, "owned_fstats": 0}

                        def open_d(path, flags, *a, **kw):
                            fd = real_open(path, flags, *a, **kw)
                            if str(path) == str(reg_file):
                                d_state["owned_fd"] = fd
                            return fd

                        def fstat_d(fd: int):
                            if fd == d_state["owned_fd"]:
                                d_state["owned_fstats"] += 1
                                if d_state["owned_fstats"] == 2:
                                    return synthetic_after_st
                            return real_fstat(fd)

                        with (
                            mock.patch(
                                "refmac_diagnostic_profile.os.open",
                                side_effect=open_d,
                            ),
                            mock.patch(
                                "refmac_diagnostic_profile.os.fstat",
                                side_effect=fstat_d,
                            ),
                        ):
                            with self.assertRaises(
                                _PartialFileReadError
                            ) as dc_ctx:
                                profile_mod._stream_observe_regular_file(
                                    str(sym_alias)
                                )
                        dc_obs = dc_ctx.exception.observation
                        self.assertTrue(dc_obs.observed_eof)
                        self.assertEqual(dc_obs.failure_phase, conflict_phase)
                        self.assertEqual(
                            dc_obs.streamed_size_bytes, len(reg_bytes)
                        )
                        self.assertEqual(
                            dc_obs.observed_eof_sha256, reg_sha
                        )
                        # Initial fstat identity/size preserved on top-level fields and initial_fstat
                        self.assertEqual(dc_obs.ino, int(base_reg_st.st_ino))
                        self.assertEqual(
                            dc_obs.stat_size_bytes, int(base_reg_st.st_size)
                        )
                        self.assertEqual(
                            dc_obs.initial_fstat,
                            LookupStatObservation.from_stat_result(base_reg_st),
                        )
                        # Conflicting end_fstat preserved separately
                        self.assertEqual(
                            dc_obs.end_fstat,
                            LookupStatObservation.from_stat_result(
                                synthetic_after_st
                            ),
                        )
                        self.assertNotEqual(
                            dc_obs.initial_fstat, dc_obs.end_fstat
                        )
                        self.assertIsNone(dc_obs.final_lexical_lstat)

                # 5. Final kernel lookup EIO and dangling-symlink ENOENT after EOF
                real_lstat = os.lstat
                real_stat = os.stat
                lookup_eio = OSError(
                    errno.EIO, "synthetic post-EOF final_kernel_lookup EIO"
                )
                l_state = {"eof_fstat_done": False, "owned_fd": -1, "owned_fstats": 0}

                def open_l(path, flags, *a, **kw):
                    fd = real_open(path, flags, *a, **kw)
                    if str(path) == str(reg_file):
                        l_state["owned_fd"] = fd
                    return fd

                def fstat_l(fd: int):
                    res = real_fstat(fd)
                    if fd == l_state["owned_fd"]:
                        l_state["owned_fstats"] += 1
                        if l_state["owned_fstats"] == 2:
                            l_state["eof_fstat_done"] = True
                    return res

                def lstat_fail_after_eof(path, *a, **kw):
                    if l_state["eof_fstat_done"] and str(path) == str(sym_alias):
                        raise lookup_eio
                    return real_lstat(path, *a, **kw)

                with (
                    mock.patch(
                        "refmac_diagnostic_profile.os.open",
                        side_effect=open_l,
                    ),
                    mock.patch(
                        "refmac_diagnostic_profile.os.fstat",
                        side_effect=fstat_l,
                    ),
                    mock.patch(
                        "refmac_diagnostic_profile.os.lstat",
                        side_effect=lstat_fail_after_eof,
                    ),
                ):
                    with self.assertRaises(_PartialFileReadError) as fk_ctx:
                        profile_mod._stream_observe_regular_file(str(sym_alias))
                fk_obs = fk_ctx.exception.observation
                self.assertIs(
                    profile_mod._select_original_cause_exception(
                        fk_ctx.exception
                    ),
                    lookup_eio,
                )
                self.assertTrue(fk_obs.observed_eof)
                self.assertEqual(fk_obs.failure_phase, "final_kernel_lookup")
                self.assertIsNotNone(fk_obs.end_fstat)
                self.assertIsNone(fk_obs.final_lexical_lstat)
                self.assertIsNone(fk_obs.final_lexical_stat)

                # 5b. os.lstat succeeds on sym_alias after EOF, then os.stat fails with ENOENT:
                # final_lexical_lstat is retained while final_lexical_stat is None
                stat_enoent = FileNotFoundError(
                    errno.ENOENT,
                    "synthetic dangling target on final os.stat",
                    str(sym_alias),
                )
                l_state_b = {
                    "eof_fstat_done": False,
                    "owned_fd": -1,
                    "owned_fstats": 0,
                }

                def open_lb(path, flags, *a, **kw):
                    fd = real_open(path, flags, *a, **kw)
                    if str(path) == str(reg_file):
                        l_state_b["owned_fd"] = fd
                    return fd

                def fstat_lb(fd: int):
                    res = real_fstat(fd)
                    if fd == l_state_b["owned_fd"]:
                        l_state_b["owned_fstats"] += 1
                        if l_state_b["owned_fstats"] == 2:
                            l_state_b["eof_fstat_done"] = True
                    return res

                def stat_fail_after_eof(path, *a, **kw):
                    if l_state_b["eof_fstat_done"] and str(path) == str(
                        sym_alias
                    ):
                        raise stat_enoent
                    return real_stat(path, *a, **kw)

                with (
                    mock.patch(
                        "refmac_diagnostic_profile.os.open",
                        side_effect=open_lb,
                    ),
                    mock.patch(
                        "refmac_diagnostic_profile.os.fstat",
                        side_effect=fstat_lb,
                    ),
                    mock.patch(
                        "refmac_diagnostic_profile.os.stat",
                        side_effect=stat_fail_after_eof,
                    ),
                ):
                    with self.assertRaises(_PartialFileReadError) as fkb_ctx:
                        profile_mod._stream_observe_regular_file(str(sym_alias))
                fkb_obs = fkb_ctx.exception.observation
                self.assertIs(
                    profile_mod._select_original_cause_exception(
                        fkb_ctx.exception
                    ),
                    stat_enoent,
                )
                self.assertTrue(fkb_obs.observed_eof)
                self.assertEqual(fkb_obs.failure_phase, "final_kernel_lookup")
                self.assertIsNotNone(fkb_obs.end_fstat)
                self.assertEqual(
                    fkb_obs.final_lexical_lstat,
                    LookupStatObservation.from_stat_result(
                        os.lstat(sym_alias)
                    ),
                )
                self.assertIsNone(fkb_obs.final_lexical_stat)

                # 6. Final path traversal failure after final_kernel_lookup succeeds
                real_readlink = os.readlink
                readlink_eio = OSError(
                    errno.EIO, "synthetic post-EOF readlink EIO"
                )
                t_state = {"eof_fstat_done": False, "owned_fd": -1, "owned_fstats": 0}

                def open_t(path, flags, *a, **kw):
                    fd = real_open(path, flags, *a, **kw)
                    if str(path) == str(reg_file):
                        t_state["owned_fd"] = fd
                    return fd

                def fstat_t(fd: int):
                    res = real_fstat(fd)
                    if fd == t_state["owned_fd"]:
                        t_state["owned_fstats"] += 1
                        if t_state["owned_fstats"] == 2:
                            t_state["eof_fstat_done"] = True
                    return res

                def readlink_fail_after_eof(path, *a, **kw):
                    if t_state["eof_fstat_done"] and str(path) == str(sym_alias):
                        raise readlink_eio
                    return real_readlink(path, *a, **kw)

                with (
                    mock.patch(
                        "refmac_diagnostic_profile.os.open",
                        side_effect=open_t,
                    ),
                    mock.patch(
                        "refmac_diagnostic_profile.os.fstat",
                        side_effect=fstat_t,
                    ),
                    mock.patch(
                        "refmac_diagnostic_profile.os.readlink",
                        side_effect=readlink_fail_after_eof,
                    ),
                ):
                    with self.assertRaises(_PartialFileReadError) as ft_ctx:
                        profile_mod._stream_observe_regular_file(str(sym_alias))
                ft_obs = ft_ctx.exception.observation
                self.assertIs(
                    profile_mod._select_original_cause_exception(
                        ft_ctx.exception
                    ),
                    readlink_eio,
                )
                self.assertTrue(ft_obs.observed_eof)
                self.assertEqual(ft_obs.failure_phase, "final_path_traversal")
                self.assertIsNotNone(ft_obs.end_fstat)
                self.assertIsNotNone(ft_obs.final_lexical_lstat)
                self.assertIsNotNone(ft_obs.final_lexical_stat)
                # Partial traversal progress up to root/parent directory before readlink failed is retained
                self.assertIsNotNone(ft_obs.final_traversed_directories)
                self.assertEqual(ft_obs.final_symlinks, ())
                self.assertIsNone(ft_obs.final_traversal_resolved_path)
                self.assertIsNone(ft_obs.final_resolved_path)

                # 7. Final target resolution failure after final_path_traversal succeeds
                res_err = OSError(
                    errno.EIO, "synthetic post-EOF strict resolve EIO"
                )
                real_resolve_strict = profile_mod._resolve_regular_target_strict
                r_calls = {"count": 0}

                def resolve_fail_second(raw_lex: str):
                    r_calls["count"] += 1
                    if r_calls["count"] == 2:
                        raise ValueError(
                            f"Failed to resolve path {raw_lex!r} (OSError): {res_err}"
                        ) from res_err
                    return real_resolve_strict(raw_lex)

                with mock.patch(
                    "refmac_diagnostic_profile._resolve_regular_target_strict",
                    side_effect=resolve_fail_second,
                ):
                    with self.assertRaises(_PartialFileReadError) as fr_ctx:
                        profile_mod._stream_observe_regular_file(str(sym_alias))
                fr_obs = fr_ctx.exception.observation
                self.assertIs(
                    profile_mod._select_original_cause_exception(
                        fr_ctx.exception
                    ),
                    res_err,
                )
                self.assertTrue(fr_obs.observed_eof)
                self.assertEqual(
                    fr_obs.failure_phase, "final_target_resolution"
                )
                self.assertIsNotNone(fr_obs.end_fstat)
                self.assertIsNotNone(fr_obs.final_lexical_lstat)
                self.assertIsNotNone(fr_obs.final_lexical_stat)
                self.assertEqual(
                    fr_obs.final_traversal_resolved_path, str(reg_file)
                )
                self.assertIsNotNone(fr_obs.final_traversal_target_lstat)
                self.assertEqual(
                    fr_obs.final_symlinks,
                    (
                        _SymlinkEdge(
                            path=str(sym_alias), target="sub/payload.txt"
                        ),
                    ),
                )
                self.assertIsNotNone(fr_obs.final_traversed_directories)
                self.assertIsNone(fr_obs.final_resolved_path)
                self.assertIsNone(fr_obs.final_resolved_target_lstat)

                # 8. Real on-disk post-EOF namespace mutations:
                # 8a. Same-bytes new-inode replacement on direct regular file and via symlink alias
                for via_symlink in (False, True):
                    with self.subTest(same_bytes_new_inode_via_symlink=via_symlink):
                        work_file = sub_dir / (
                            "swap_sym_target.txt"
                            if via_symlink
                            else "swap_direct.txt"
                        )
                        work_file.write_bytes(reg_bytes)
                        work_link = root / "swap-link.txt"
                        if via_symlink:
                            if work_link.exists() or work_link.is_symlink():
                                work_link.unlink()
                            os.symlink(f"sub/{work_file.name}", work_link)
                        lex_arg = str(work_link if via_symlink else work_file)
                        orig_st = os.lstat(work_file)
                        swap_tmp = sub_dir / "swap_replacement.tmp"
                        swap_tmp.write_bytes(reg_bytes)
                        new_st = os.lstat(swap_tmp)
                        self.assertEqual(swap_tmp.read_bytes(), reg_bytes)
                        self.assertEqual(work_file.read_bytes(), reg_bytes)
                        self.assertEqual(
                            _sha256_bytes(swap_tmp.read_bytes()), reg_sha
                        )
                        self.assertNotEqual(orig_st.st_ino, new_st.st_ino)
                        self.assertEqual(orig_st.st_size, new_st.st_size)

                        s_state = {
                            "owned_fd": -1,
                            "captured_fd": -1,
                            "observed_eof": False,
                            "owned_fstats": 0,
                        }

                        def open_swap(path, flags, *a, **kw):
                            fd = real_open(path, flags, *a, **kw)
                            if str(path) == str(work_file):
                                s_state["owned_fd"] = fd
                                s_state["captured_fd"] = fd
                            return fd

                        def fdopen_swap(fd, mode="rb", *a, **kw):
                            handle = real_fdopen(fd, mode, *a, **kw)
                            if fd == s_state["owned_fd"]:
                                orig_read = handle.read

                                def read_track_eof(n=-1):
                                    chunk = orig_read(n)
                                    if chunk == b"":
                                        s_state["observed_eof"] = True
                                    return chunk

                                handle.read = read_track_eof  # type: ignore[method-assign]
                            return handle

                        def fstat_swap_at_eof(fd: int):
                            res = real_fstat(fd)
                            if fd == s_state["owned_fd"]:
                                s_state["owned_fstats"] += 1
                                if s_state["owned_fstats"] == 2:
                                    self.assertTrue(s_state["observed_eof"])
                                    os.replace(swap_tmp, work_file)
                            return res

                        with (
                            mock.patch(
                                "refmac_diagnostic_profile.os.open",
                                side_effect=open_swap,
                            ),
                            mock.patch(
                                "refmac_diagnostic_profile.os.fdopen",
                                side_effect=fdopen_swap,
                            ),
                            mock.patch(
                                "refmac_diagnostic_profile.os.fstat",
                                side_effect=fstat_swap_at_eof,
                            ),
                        ):
                            with self.assertRaises(
                                _PartialFileReadError
                            ) as sw_ctx:
                                profile_mod._stream_observe_regular_file(
                                    lex_arg
                                )
                        self.assertTrue(s_state["observed_eof"])
                        self.assertGreaterEqual(s_state["captured_fd"], 0)
                        with self.assertRaises(OSError) as sw_ebadf:
                            real_fstat(s_state["captured_fd"])
                        self.assertEqual(sw_ebadf.exception.errno, errno.EBADF)
                        self.assertEqual(work_file.read_bytes(), reg_bytes)
                        self.assertEqual(
                            _sha256_bytes(work_file.read_bytes()), reg_sha
                        )
                        self.assertEqual(
                            os.lstat(work_file).st_ino, new_st.st_ino
                        )
                        sw_obs = sw_ctx.exception.observation
                        self.assertTrue(sw_obs.observed_eof)
                        self.assertEqual(
                            sw_obs.failure_phase,
                            "post_read_namespace_comparison",
                        )
                        # Streamed digest is the original opened inode's bytes (identical to replacement bytes)
                        self.assertEqual(
                            sw_obs.streamed_size_bytes, len(reg_bytes)
                        )
                        self.assertEqual(
                            sw_obs.observed_stream_sha256, reg_sha
                        )
                        self.assertEqual(sw_obs.observed_eof_sha256, reg_sha)
                        self.assertIsNone(sw_obs.sha256)
                        self.assertIsNone(sw_obs.size_bytes)
                        self.assertFalse(sw_obs.read_complete)
                        self.assertEqual(sw_obs.ino, int(orig_st.st_ino))
                        self.assertEqual(
                            sw_obs.initial_fstat.ino, int(orig_st.st_ino)
                        )
                        self.assertEqual(
                            sw_obs.lookup_snapshot.target_lstat.ino,
                            int(orig_st.st_ino),
                        )
                        assert sw_obs.end_fstat is not None
                        self.assertEqual(
                            sw_obs.end_fstat.ino, int(orig_st.st_ino)
                        )
                        # Final lookup/traversal/resolution captured the new replacement inode!
                        assert sw_obs.final_lexical_stat is not None
                        assert sw_obs.final_traversal_target_lstat is not None
                        assert sw_obs.final_resolved_target_lstat is not None
                        self.assertEqual(
                            sw_obs.final_lexical_stat.ino, int(new_st.st_ino)
                        )
                        self.assertEqual(
                            sw_obs.final_traversal_target_lstat.ino,
                            int(new_st.st_ino),
                        )
                        self.assertEqual(
                            sw_obs.final_resolved_target_lstat.ino,
                            int(new_st.st_ino),
                        )
                        self.assertNotEqual(
                            sw_obs.end_fstat.ino,
                            sw_obs.final_lexical_stat.ino,
                        )

                # 8b. Persistent symlink retarget to alt_file during read
                retarget_link = root / "retarget-link.txt"
                os.symlink("sub/payload.txt", retarget_link)
                rt_state = {"owned_fd": -1, "owned_fstats": 0}

                def open_rt(path, flags, *a, **kw):
                    fd = real_open(path, flags, *a, **kw)
                    if str(path) == str(reg_file):
                        rt_state["owned_fd"] = fd
                    return fd

                def fstat_rt(fd: int):
                    res = real_fstat(fd)
                    if fd == rt_state["owned_fd"]:
                        rt_state["owned_fstats"] += 1
                        if rt_state["owned_fstats"] == 2:
                            tmp_lnk = root / "retarget-link.tmp"
                            os.symlink("alt/alt_payload.txt", tmp_lnk)
                            os.replace(tmp_lnk, retarget_link)
                    return res

                with (
                    mock.patch(
                        "refmac_diagnostic_profile.os.open",
                        side_effect=open_rt,
                    ),
                    mock.patch(
                        "refmac_diagnostic_profile.os.fstat",
                        side_effect=fstat_rt,
                    ),
                ):
                    with self.assertRaises(_PartialFileReadError) as rt_ctx:
                        profile_mod._stream_observe_regular_file(
                            str(retarget_link)
                        )
                rt_obs = rt_ctx.exception.observation
                self.assertTrue(rt_obs.observed_eof)
                self.assertEqual(
                    rt_obs.failure_phase, "post_read_namespace_comparison"
                )
                # Initial symlink target and resolved path preserved
                self.assertEqual(rt_obs.resolved_path, str(reg_file))
                self.assertEqual(
                    rt_obs.symlinks,
                    (
                        _SymlinkEdge(
                            path=str(retarget_link), target="sub/payload.txt"
                        ),
                    ),
                )
                # Final retargeted symlink and resolved path also preserved
                self.assertEqual(
                    rt_obs.final_symlinks,
                    (
                        _SymlinkEdge(
                            path=str(retarget_link),
                            target="alt/alt_payload.txt",
                        ),
                    ),
                )
                self.assertEqual(
                    rt_obs.final_traversal_resolved_path, str(alt_file)
                )
                self.assertEqual(rt_obs.final_resolved_path, str(alt_file))
                assert rt_obs.final_resolved_target_lstat is not None
                self.assertEqual(
                    rt_obs.final_resolved_target_lstat.ino,
                    int(os.lstat(alt_file).st_ino),
                )
            finally:
                real_fstat(bystander_fd)
                os.close(bystander_fd)

            # 9. Pre-EOF partial prefix read EIO contrast and PostReadVerificationObservation guardrails
            prefix_eio = OSError(errno.EIO, "synthetic prefix read EIO")
            tracked_fds: list[int] = []

            def open_track_reg(path, flags, *a, **kw):
                fd = real_open(path, flags, *a, **kw)
                if str(path) == str(reg_file):
                    tracked_fds.append(fd)
                return fd

            def fdopen_prefix_5(fd, mode="rb", *a, **kw):
                handle = real_fdopen(fd, mode, *a, **kw)
                if fd in tracked_fds:
                    orig_read = handle.read
                    calls = 0

                    def read_5_then_eio(_n=-1):
                        nonlocal calls
                        calls += 1
                        if calls == 1:
                            return orig_read(5)
                        raise prefix_eio

                    handle.read = read_5_then_eio  # type: ignore[method-assign]
                return handle

            with (
                mock.patch(
                    "refmac_diagnostic_profile.os.open",
                    side_effect=open_track_reg,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.fdopen",
                    side_effect=fdopen_prefix_5,
                ),
            ):
                with self.assertRaises(_PartialFileReadError) as pre_ctx:
                    profile_mod._stream_observe_regular_file(
                        str(sym_alias), chunk_size=5
                    )
            self.assertEqual(len(tracked_fds), 1)
            with self.assertRaises(OSError) as ebadf_pre:
                real_fstat(tracked_fds[0])
            self.assertEqual(ebadf_pre.exception.errno, errno.EBADF)
            pre_obs = pre_ctx.exception.observation
            self.assertFalse(pre_obs.observed_eof)
            self.assertEqual(pre_obs.streamed_size_bytes, 5)
            self.assertEqual(
                pre_obs.observed_stream_sha256, _sha256_bytes(reg_bytes[:5])
            )
            self.assertIsNone(pre_obs.observed_eof_sha256)
            self.assertIsNone(pre_obs.end_fstat)
            self.assertEqual(pre_obs.failure_phase, "stream_read")
            self.assertIsNone(pre_obs.sha256)
            self.assertIsNone(pre_obs.size_bytes)
            self.assertFalse(pre_obs.read_complete)
            assert pre_obs.post_read_observation is not None
            self.assertFalse(pre_obs.post_read_observation.observed_eof)
            self.assertEqual(
                pre_obs.post_read_observation.observed_stream_sha256,
                _sha256_bytes(reg_bytes[:5]),
            )
            self.assertIsNone(
                pre_obs.post_read_observation.observed_eof_sha256
            )
            with self.assertRaises(FrozenInstanceError):
                pre_obs.post_read_observation.observed_eof = True  # type: ignore[misc]
            with self.assertRaisesRegex(
                ValueError, "cannot be converted to a FilePin"
            ):
                pre_obs.as_file_pin()

    def test_task990_post_eof_observation_admission_and_recheck_integration(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fx = _build_synthetic_outer_profile_fixture(Path(tmpdir))
            root = fx["root"]
            assert isinstance(root, Path)
            support_dir = root / "support"
            installed_record = fx["installed_record"]
            assert isinstance(installed_record, dict)
            ccp4_env = fx["ccp4_env"]
            assert isinstance(ccp4_env, dict)
            ev_root = fx["evidence_root"]
            assert isinstance(ev_root, Path)
            alias_symlink = fx["alias_symlink"]
            assert isinstance(alias_symlink, Path)
            manifest_path = fx["manifest_path"]
            assert isinstance(manifest_path, Path)
            profile = fx["profile"]
            assert isinstance(profile, RefmacDiagnosticProfile)
            base_payload = fx["manifest_payload"]
            assert isinstance(base_payload, dict)

            validated = validate_profile(
                profile, installed_record, ccp4_env, ev_root
            )
            state = validated._outer_state
            assert state is not None

            direct_fid = base_payload["roles"]["collection_interpreter"][0]  # type: ignore[index]
            alias_fid = next(
                fid
                for fid, row in base_payload["files"].items()  # type: ignore[union-attr]
                if row["path"] == str(alias_symlink)
            )
            dotdot_path_str = str(
                support_dir / "bin" / ".." / "collection-python"
            )
            dotdot_fid = next(
                fid
                for fid, row in base_payload["files"].items()  # type: ignore[union-attr]
                if row["path"] == dotdot_path_str
            )
            alias_resolved = str(alias_symlink.resolve(strict=True))
            self.assertLess(direct_fid, alias_fid)
            self.assertLess(alias_fid, dotdot_fid)
            self.assertEqual(
                validated.files[direct_fid].resolved_path, alias_resolved
            )
            self.assertEqual(
                validated.files[alias_fid].resolved_path, alias_resolved
            )
            self.assertEqual(
                validated.files[dotdot_fid].resolved_path, alias_resolved
            )
            alias_bytes = Path(alias_resolved).read_bytes()
            alias_sha = _sha256_bytes(alias_bytes)
            last_fid = sorted(validated.files.keys())[-1]
            last_fpath = validated.files[last_fid].path

            # 1. Declared-file owner post-EOF failure (end_fstat EIO and final_kernel_lookup ENOENT)
            # across validate_profile, _reobserve_outer_profile_state, and recheck_profile
            real_open = os.open
            real_fdopen = os.fdopen
            real_fstat = os.fstat
            real_lstat = os.lstat
            real_obs_pin = profile_mod._observe_regular_file_pin
            real_dir_obs = profile_mod._observe_directory_identity

            for failure_kind in ("end_fstat_eio", "final_lookup_enoent"):
                with self.subTest(declared_file_failure=failure_kind):
                    injected_exc: OSError = (
                        OSError(
                            errno.EIO,
                            "synthetic #1168 declared-file end_fstat EIO",
                        )
                        if failure_kind == "end_fstat_eio"
                        else FileNotFoundError(
                            errno.ENOENT,
                            "synthetic #1168 declared-file post-EOF lookup ENOENT",
                            str(alias_symlink),
                        )
                    )
                    run_state: dict[str, object] = {
                        "active_lexical": None,
                        "owned_fd": -1,
                        "captured_fd": -1,
                        "owned_fstats": 0,
                        "observed_eof_on_owned_fd": False,
                        "eof_fstat_done": False,
                        "injected": False,
                    }
                    recheck_track = {"files_done": False}

                    def reset_run_state() -> None:
                        run_state["active_lexical"] = None
                        run_state["owned_fd"] = -1
                        run_state["captured_fd"] = -1
                        run_state["owned_fstats"] = 0
                        run_state["observed_eof_on_owned_fd"] = False
                        run_state["eof_fstat_done"] = False
                        run_state["injected"] = False
                        recheck_track["files_done"] = False

                    def observe_pin_alias(path, *a, **kw):
                        prev_lexical = run_state["active_lexical"]
                        path_str = str(path)
                        run_state["active_lexical"] = path_str
                        if (
                            path_str == str(alias_symlink)
                            and not run_state["injected"]
                        ):
                            run_state["owned_fd"] = -1
                            run_state["owned_fstats"] = 0
                            run_state["observed_eof_on_owned_fd"] = False
                            run_state["eof_fstat_done"] = False
                        try:
                            return real_obs_pin(path, *a, **kw)
                        finally:
                            if path_str == str(alias_symlink):
                                run_state["owned_fd"] = -1
                                run_state["owned_fstats"] = 0
                                run_state["observed_eof_on_owned_fd"] = False
                                run_state["eof_fstat_done"] = False
                            if path_str == str(last_fpath):
                                recheck_track["files_done"] = True
                            run_state["active_lexical"] = prev_lexical

                    def open_alias(path, flags, *a, **kw):
                        fd = real_open(path, flags, *a, **kw)
                        if (
                            run_state["active_lexical"] == str(alias_symlink)
                            and not run_state["injected"]
                            and str(path) == alias_resolved
                        ):
                            run_state["owned_fd"] = fd
                            run_state["captured_fd"] = fd
                            run_state["owned_fstats"] = 0
                            run_state["observed_eof_on_owned_fd"] = False
                            run_state["eof_fstat_done"] = False
                        return fd

                    def fdopen_alias(fd, mode="rb", *a, **kw):
                        handle = real_fdopen(fd, mode, *a, **kw)
                        if (
                            run_state["active_lexical"] == str(alias_symlink)
                            and fd == run_state["owned_fd"]
                        ):
                            orig_read = handle.read

                            def read_track_alias_eof(n=-1):
                                chunk = orig_read(n)
                                if chunk == b"":
                                    run_state["observed_eof_on_owned_fd"] = True
                                return chunk

                            handle.read = read_track_alias_eof  # type: ignore[method-assign]
                        return handle

                    def fstat_alias(fd: int):
                        if (
                            run_state["active_lexical"] == str(alias_symlink)
                            and fd == run_state["owned_fd"]
                        ):
                            run_state["owned_fstats"] = (
                                int(run_state["owned_fstats"]) + 1  # type: ignore[arg-type]
                            )
                            if run_state["owned_fstats"] == 2:
                                self.assertTrue(
                                    run_state["observed_eof_on_owned_fd"]
                                )
                                if failure_kind == "end_fstat_eio":
                                    run_state["injected"] = True
                                    raise injected_exc
                                run_state["eof_fstat_done"] = True
                        return real_fstat(fd)

                    def lstat_alias(path, *a, **kw):
                        if (
                            failure_kind == "final_lookup_enoent"
                            and run_state["active_lexical"]
                            == str(alias_symlink)
                            and run_state["observed_eof_on_owned_fd"]
                            and run_state["eof_fstat_done"]
                            and not run_state["injected"]
                            and str(path) == str(alias_symlink)
                        ):
                            run_state["injected"] = True
                            raise injected_exc
                        return real_lstat(path, *a, **kw)

                    reset_run_state()
                    with (
                        mock.patch(
                            "refmac_diagnostic_profile._observe_regular_file_pin",
                            side_effect=observe_pin_alias,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.open",
                            side_effect=open_alias,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.fdopen",
                            side_effect=fdopen_alias,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.fstat",
                            side_effect=fstat_alias,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.lstat",
                            side_effect=lstat_alias,
                        ),
                    ):
                        with self.assertRaises(
                            ProfileValidationError
                        ) as val_ctx:
                            validate_profile(
                                profile, installed_record, ccp4_env, ev_root
                            )
                    self.assertTrue(run_state["injected"])
                    self.assertGreaterEqual(int(run_state["captured_fd"]), 0)  # type: ignore[arg-type]
                    with self.assertRaises(OSError) as val_ebadf:
                        real_fstat(int(run_state["captured_fd"]))  # type: ignore[arg-type]
                    self.assertEqual(val_ebadf.exception.errno, errno.EBADF)

                    val_err = val_ctx.exception
                    self.assertEqual(
                        val_err.failed_check, "outer_profile_files_and_roots"
                    )
                    self.assertIs(val_err.cause_exception, injected_exc)
                    self.assertEqual(val_err.error_errno, injected_exc.errno)
                    self.assertEqual(len(val_err.files), 59)
                    self.assertEqual(len(val_err.roots), 3)
                    # Earlier direct_fid and later dotdot_fid sharing alias_resolved completed as verified FileObservation
                    direct_obs = val_err.files[direct_fid]
                    assert isinstance(direct_obs, FileObservation)
                    self.assertTrue(direct_obs.verified)
                    self.assertEqual(direct_obs.resolved_path, alias_resolved)
                    self.assertEqual(direct_obs.sha256, alias_sha)
                    dotdot_obs = val_err.files[dotdot_fid]
                    assert isinstance(dotdot_obs, FileObservation)
                    self.assertTrue(dotdot_obs.verified)
                    self.assertEqual(dotdot_obs.resolved_path, alias_resolved)
                    self.assertEqual(dotdot_obs.sha256, alias_sha)
                    # Later files after alias_fid still completed as verified FileObservation
                    later_fids = [
                        fid for fid, _ in val_err.files if fid > alias_fid
                    ]
                    self.assertGreaterEqual(len(later_fids), 1)
                    for fid, fobs in val_err.files:
                        if fid == alias_fid:
                            self.assertIsInstance(
                                fobs, PartialFileReadObservation
                            )
                        else:
                            self.assertIsInstance(fobs, FileObservation)
                            self.assertTrue(fobs.verified)

                    pobs = val_err.files[alias_fid]
                    assert isinstance(pobs, PartialFileReadObservation)
                    self.assertEqual(pobs.path, str(alias_symlink))
                    self.assertEqual(pobs.resolved_path, alias_resolved)
                    self.assertTrue(pobs.observed_eof)
                    self.assertEqual(pobs.streamed_size_bytes, len(alias_bytes))
                    self.assertEqual(pobs.observed_stream_sha256, alias_sha)
                    self.assertEqual(pobs.observed_eof_sha256, alias_sha)
                    self.assertIsNone(pobs.sha256)
                    self.assertIsNone(pobs.size_bytes)
                    self.assertFalse(pobs.read_complete)
                    if failure_kind == "end_fstat_eio":
                        self.assertIsNone(pobs.end_fstat)
                        self.assertEqual(pobs.failure_phase, "end_fstat")
                    else:
                        self.assertIsNotNone(pobs.end_fstat)
                        self.assertEqual(
                            pobs.failure_phase, "final_kernel_lookup"
                        )

                    # Pure in-memory provenance projection with poisoned filesystem entry points
                    with (
                        mock.patch(
                            "refmac_diagnostic_profile.os.lstat",
                            side_effect=AssertionError("no lstat"),
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.stat",
                            side_effect=AssertionError("no stat"),
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.readlink",
                            side_effect=AssertionError("no readlink"),
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.open",
                            side_effect=AssertionError("no open"),
                        ),
                    ):
                        prov = val_err.to_provenance()
                    json.dumps(prov, allow_nan=False)
                    self.assertTrue(prov["files"][alias_fid]["observed_eof"])
                    self.assertEqual(
                        prov["files"][alias_fid]["observed_eof_sha256"],
                        alias_sha,
                    )
                    self.assertIsNone(prov["files"][alias_fid]["sha256"])
                    self.assertIsNone(prov["files"][alias_fid]["size_bytes"])
                    self.assertEqual(
                        prov["files"][direct_fid]["sha256"], alias_sha
                    )
                    self.assertEqual(
                        prov["files"][dotdot_fid]["sha256"], alias_sha
                    )

                    # Recheck integration + Step 4 shared dependency failure attachment
                    step4_perm = PermissionError(
                        errno.EACCES,
                        "synthetic Step 4 support_dir PermissionError",
                        str(support_dir),
                    )

                    def fail_support_in_step4(
                        dir_path_str: str,
                        *,
                        require_no_symlink_ancestors: bool = False,
                    ):
                        if (
                            recheck_track["files_done"]
                            and str(dir_path_str) == str(support_dir)
                        ):
                            raise ValueError(
                                f"Cannot lstat directory {dir_path_str!r} (PermissionError): {step4_perm}"
                            ) from step4_perm
                        return real_dir_obs(
                            dir_path_str,
                            require_no_symlink_ancestors=require_no_symlink_ancestors,
                        )

                    reset_run_state()
                    with (
                        mock.patch(
                            "refmac_diagnostic_profile._observe_regular_file_pin",
                            side_effect=observe_pin_alias,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.open",
                            side_effect=open_alias,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.fdopen",
                            side_effect=fdopen_alias,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.fstat",
                            side_effect=fstat_alias,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.lstat",
                            side_effect=lstat_alias,
                        ),
                    ):
                        priv_recheck = _reobserve_outer_profile_state(state)
                    self.assertTrue(run_state["injected"])
                    self.assertGreaterEqual(int(run_state["captured_fd"]), 0)  # type: ignore[arg-type]
                    with self.assertRaises(OSError) as priv_ebadf:
                        real_fstat(int(run_state["captured_fd"]))  # type: ignore[arg-type]
                    self.assertEqual(priv_ebadf.exception.errno, errno.EBADF)

                    self.assertFalse(priv_recheck.verified)
                    self.assertNotIn(direct_fid, priv_recheck.partial_files)
                    self.assertNotIn(dotdot_fid, priv_recheck.partial_files)
                    self.assertIsInstance(
                        priv_recheck.file_observations[direct_fid],
                        FileObservation,
                    )
                    self.assertTrue(
                        priv_recheck.file_observations[direct_fid].verified
                    )
                    self.assertIsInstance(
                        priv_recheck.file_observations[dotdot_fid],
                        FileObservation,
                    )
                    self.assertTrue(
                        priv_recheck.file_observations[dotdot_fid].verified
                    )
                    self.assertIn(alias_fid, priv_recheck.partial_files)
                    self.assertIs(
                        priv_recheck.file_observations[alias_fid],
                        priv_recheck.partial_files[alias_fid],
                    )
                    self.assertIs(
                        priv_recheck.file_causes[alias_fid], injected_exc
                    )
                    self.assertTrue(
                        priv_recheck.partial_files[alias_fid].observed_eof
                    )

                    # 1a. Public recheck EOF-only run (without Step 4 shared-dependency injection)
                    reset_run_state()
                    eof_only_causes: list[Exception | None] = []
                    with (
                        mock.patch(
                            "refmac_diagnostic_profile._observe_regular_file_pin",
                            side_effect=observe_pin_alias,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.open",
                            side_effect=open_alias,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.fdopen",
                            side_effect=fdopen_alias,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.fstat",
                            side_effect=fstat_alias,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.lstat",
                            side_effect=lstat_alias,
                        ),
                    ):
                        eof_only_report = recheck_profile(
                            validated, mutation_causes_out=eof_only_causes
                        )
                    self.assertTrue(run_state["injected"])
                    self.assertGreaterEqual(int(run_state["captured_fd"]), 0)  # type: ignore[arg-type]
                    with self.assertRaises(OSError) as eof_only_ebadf:
                        real_fstat(int(run_state["captured_fd"]))  # type: ignore[arg-type]
                    self.assertEqual(
                        eof_only_ebadf.exception.errno, errno.EBADF
                    )
                    self.assertFalse(eof_only_report["verified"])
                    self.assertTrue(
                        eof_only_report["files"][direct_fid][
                            "matches_baseline"
                        ]
                    )
                    self.assertEqual(
                        eof_only_report["files"][direct_fid]["errors"], []
                    )
                    self.assertEqual(
                        eof_only_report["files"][direct_fid]["observed"][
                            "sha256"
                        ],
                        alias_sha,
                    )
                    self.assertTrue(
                        eof_only_report["files"][direct_fid]["observed"][
                            "verified"
                        ]
                    )
                    self.assertTrue(
                        eof_only_report["files"][dotdot_fid][
                            "matches_baseline"
                        ]
                    )
                    self.assertEqual(
                        eof_only_report["files"][dotdot_fid]["errors"], []
                    )
                    self.assertEqual(
                        eof_only_report["files"][dotdot_fid]["observed"][
                            "sha256"
                        ],
                        alias_sha,
                    )
                    self.assertTrue(
                        eof_only_report["files"][dotdot_fid]["observed"][
                            "verified"
                        ]
                    )
                    eof_only_frow = eof_only_report["files"][alias_fid]
                    self.assertFalse(eof_only_frow["matches_baseline"])
                    self.assertTrue(eof_only_frow["observed"]["observed_eof"])
                    self.assertEqual(
                        eof_only_frow["observed"]["observed_eof_sha256"],
                        alias_sha,
                    )
                    self.assertIsNone(eof_only_frow["observed"]["sha256"])
                    self.assertIsNone(eof_only_frow["observed"]["size_bytes"])
                    self.assertEqual(len(eof_only_frow["errors"]), 1)
                    self.assertEqual(len(eof_only_report["mutations"]), 1)
                    self.assertEqual(
                        eof_only_report["mutations"][0]["key"],
                        f"profile:file:{alias_fid}",
                    )
                    self.assertEqual(len(eof_only_causes), 1)
                    self.assertIs(eof_only_causes[0], injected_exc)

                    # 1b. Combined Step 4 shared-dependency run (alias_fid post-EOF failure + support_dir Step 4 failure)
                    reset_run_state()
                    recheck_causes: list[Exception | None] = []
                    with (
                        mock.patch(
                            "refmac_diagnostic_profile._observe_regular_file_pin",
                            side_effect=observe_pin_alias,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.open",
                            side_effect=open_alias,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.fdopen",
                            side_effect=fdopen_alias,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.fstat",
                            side_effect=fstat_alias,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.lstat",
                            side_effect=lstat_alias,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile._observe_directory_identity",
                            side_effect=fail_support_in_step4,
                        ),
                    ):
                        pub_report = recheck_profile(
                            validated, mutation_causes_out=recheck_causes
                        )
                    self.assertTrue(run_state["injected"])
                    self.assertGreaterEqual(int(run_state["captured_fd"]), 0)  # type: ignore[arg-type]
                    with self.assertRaises(OSError) as pub_ebadf:
                        real_fstat(int(run_state["captured_fd"]))  # type: ignore[arg-type]
                    self.assertEqual(pub_ebadf.exception.errno, errno.EBADF)
                    self.assertFalse(pub_report["verified"])
                    for other_fid in (direct_fid, dotdot_fid):
                        other_row = pub_report["files"][other_fid]
                        self.assertFalse(other_row["matches_baseline"])
                        self.assertEqual(
                            other_row["observed"]["resolved_path"],
                            alias_resolved,
                        )
                        self.assertEqual(
                            other_row["observed"]["sha256"], alias_sha
                        )
                        self.assertEqual(
                            other_row["observed"]["size_bytes"],
                            len(alias_bytes),
                        )
                        self.assertFalse(
                            other_row["observed"]["dependencies_complete"]
                        )
                        self.assertFalse(other_row["observed"]["verified"])
                        self.assertEqual(len(other_row["errors"]), 1)
                        self.assertEqual(
                            other_row["errors"][0]["errno"], errno.EACCES
                        )
                        other_muts = [
                            (idx, m)
                            for idx, m in enumerate(pub_report["mutations"])
                            if m["key"] == f"profile:file:{other_fid}"
                        ]
                        self.assertEqual(len(other_muts), 1)
                        self.assertIs(
                            recheck_causes[other_muts[0][0]], step4_perm
                        )
                    frow = pub_report["files"][alias_fid]
                    self.assertFalse(frow["matches_baseline"])
                    self.assertTrue(frow["observed"]["observed_eof"])
                    self.assertEqual(
                        frow["observed"]["observed_eof_sha256"], alias_sha
                    )
                    self.assertEqual(len(frow["errors"]), 2)
                    alias_muts = [
                        (idx, m)
                        for idx, m in enumerate(pub_report["mutations"])
                        if m["key"] == f"profile:file:{alias_fid}"
                    ]
                    self.assertEqual(len(alias_muts), 2)
                    self.assertIs(recheck_causes[alias_muts[0][0]], injected_exc)
                    self.assertIs(recheck_causes[alias_muts[1][0]], step4_perm)

            # 2. Manifest owner post-EOF failure prevents JSON parsing and retains post-EOF observation
            real_stream_obs = profile_mod._stream_observe_regular_file
            manifest_resolved = str(manifest_path.resolve(strict=True))
            manifest_bytes = manifest_path.read_bytes()
            manifest_sha = _sha256_bytes(manifest_bytes)
            m_end_eio = OSError(
                errno.EIO, "synthetic #1168 manifest end_fstat EIO"
            )
            m_state: dict[str, object] = {
                "active_lexical": None,
                "owned_fd": -1,
                "captured_fd": -1,
                "owned_fstats": 0,
                "observed_eof_on_owned_fd": False,
                "injected": False,
            }

            def stream_obs_m(path, *a, **kw):
                prev_lex = m_state["active_lexical"]
                path_str = str(path)
                m_state["active_lexical"] = path_str
                try:
                    return real_stream_obs(path, *a, **kw)
                finally:
                    if path_str == str(manifest_path):
                        m_state["owned_fd"] = -1
                        m_state["owned_fstats"] = 0
                        m_state["observed_eof_on_owned_fd"] = False
                    m_state["active_lexical"] = prev_lex

            def open_m(path, flags, *a, **kw):
                fd = real_open(path, flags, *a, **kw)
                if (
                    m_state["active_lexical"] == str(manifest_path)
                    and not m_state["injected"]
                    and str(path) == manifest_resolved
                ):
                    m_state["owned_fd"] = fd
                    m_state["captured_fd"] = fd
                    m_state["owned_fstats"] = 0
                    m_state["observed_eof_on_owned_fd"] = False
                return fd

            def fdopen_m(fd, mode="rb", *a, **kw):
                handle = real_fdopen(fd, mode, *a, **kw)
                if (
                    m_state["active_lexical"] == str(manifest_path)
                    and fd == m_state["owned_fd"]
                ):
                    orig_read = handle.read

                    def read_track_m_eof(n=-1):
                        chunk = orig_read(n)
                        if chunk == b"":
                            m_state["observed_eof_on_owned_fd"] = True
                        return chunk

                    handle.read = read_track_m_eof  # type: ignore[method-assign]
                return handle

            def fstat_m(fd: int):
                if (
                    m_state["active_lexical"] == str(manifest_path)
                    and fd == m_state["owned_fd"]
                ):
                    m_state["owned_fstats"] = (
                        int(m_state["owned_fstats"]) + 1  # type: ignore[arg-type]
                    )
                    if m_state["owned_fstats"] == 2:
                        self.assertTrue(m_state["observed_eof_on_owned_fd"])
                        m_state["injected"] = True
                        raise m_end_eio
                return real_fstat(fd)

            with (
                mock.patch(
                    "refmac_diagnostic_profile._stream_observe_regular_file",
                    side_effect=stream_obs_m,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.open", side_effect=open_m
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.fdopen", side_effect=fdopen_m
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.fstat", side_effect=fstat_m
                ),
                mock.patch(
                    "refmac_diagnostic_profile._parse_verified_json_bytes",
                    side_effect=AssertionError("must not parse JSON"),
                ) as mocked_parse,
                mock.patch(
                    "refmac_diagnostic_profile._validate_outer_manifest_shape",
                    side_effect=AssertionError("must not validate shape"),
                ) as mocked_shape,
                mock.patch(
                    "refmac_diagnostic_profile._observe_controlled_root",
                    side_effect=AssertionError("must not inspect roots"),
                ) as mocked_root,
            ):
                with self.assertRaises(ProfileValidationError) as m_ctx:
                    validate_profile(
                        profile, installed_record, ccp4_env, ev_root
                    )
                mocked_parse.assert_not_called()
                mocked_shape.assert_not_called()
                mocked_root.assert_not_called()
            self.assertTrue(m_state["injected"])
            self.assertGreaterEqual(int(m_state["captured_fd"]), 0)  # type: ignore[arg-type]
            with self.assertRaises(OSError) as m_ebadf:
                real_fstat(int(m_state["captured_fd"]))  # type: ignore[arg-type]
            self.assertEqual(m_ebadf.exception.errno, errno.EBADF)

            m_err = m_ctx.exception
            self.assertEqual(m_err.failed_check, "manifest_pin")
            self.assertIs(m_err.cause_exception, m_end_eio)
            self.assertEqual(len(m_err.files), 0)
            self.assertEqual(len(m_err.roots), 0)
            assert isinstance(
                m_err.manifest_identity, PartialFileReadObservation
            )
            self.assertTrue(m_err.manifest_identity.observed_eof)
            self.assertEqual(
                m_err.manifest_identity.streamed_size_bytes, len(manifest_bytes)
            )
            self.assertEqual(
                m_err.manifest_identity.observed_eof_sha256, manifest_sha
            )
            self.assertIsNone(m_err.manifest_identity.end_fstat)
            self.assertEqual(m_err.manifest_identity.failure_phase, "end_fstat")
            self.assertIsNone(m_err.manifest_identity.sha256)
            self.assertIsNone(m_err.manifest_identity.size_bytes)

    def test_task990_post_eof_observation_contextual_dependency_conflict_copy(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fx = _build_synthetic_outer_profile_fixture(Path(tmpdir))
            root = fx["root"]
            assert isinstance(root, Path)
            alias_symlink = fx["alias_symlink"]
            assert isinstance(alias_symlink, Path)
            installed_record = fx["installed_record"]
            assert isinstance(installed_record, dict)
            ccp4_env = fx["ccp4_env"]
            assert isinstance(ccp4_env, dict)
            ev_root = fx["evidence_root"]
            assert isinstance(ev_root, Path)
            payload = copy.deepcopy(fx["manifest_payload"])
            assert isinstance(payload, dict)

            first_fid = next(
                fid
                for fid, row in payload["files"].items()  # type: ignore[union-attr]
                if row["path"] == str(alias_symlink)
            )
            second_fid = "zz_second_shared_symlink_post_eof"
            second_path = f"{root}/support/bin/../python-alias"
            payload["files"][second_fid] = (  # type: ignore[index]
                _observe_regular_file_pin(second_path).to_manifest_row()
            )
            payload["roles"]["qc_evidence"] = sorted(  # type: ignore[index]
                [*payload["roles"]["qc_evidence"], second_fid]  # type: ignore[index]
            )
            profile = _rewrite_manifest_and_profile(fx, payload)

            target_resolved = str(alias_symlink.resolve(strict=True))
            target_bytes = Path(target_resolved).read_bytes()
            target_sha = _sha256_bytes(target_bytes)
            park_link = alias_symlink.with_name("python-alias.post-eof-old")

            real_deps = profile_mod._collect_file_dependencies
            real_observe = profile_mod._observe_regular_file_pin
            real_open = os.open
            real_fstat = os.fstat
            real_lstat = os.lstat

            armed: list[bool] = []
            inodes: list[int] = []
            state_box = {
                "owned_fd": -1,
                "owned_fstats": 0,
                "eof_fstat_done": False,
                "fired": False,
            }
            lookup_eio = OSError(
                errno.EIO,
                "synthetic post-EOF final_kernel_lookup EIO on second shared-symlink owner",
            )

            def deps_replace_link(file_obs, **kw):
                res = real_deps(file_obs, **kw)
                if file_obs.path == str(alias_symlink):
                    inodes.append(real_lstat(alias_symlink).st_ino)
                    alias_symlink.rename(park_link)
                    alias_symlink.symlink_to("collection-python")
                    inodes.append(real_lstat(alias_symlink).st_ino)
                return res

            def observe_track_second(path, *a, **kw):
                if path != second_path:
                    return real_observe(path, *a, **kw)
                armed.append(True)
                try:
                    return real_observe(path, *a, **kw)
                finally:
                    armed.pop()

            def open_track_second(path, flags, *a, **kw):
                fd = real_open(path, flags, *a, **kw)
                if armed and str(path) == target_resolved:
                    state_box["owned_fd"] = fd
                    state_box["owned_fstats"] = 0
                return fd

            def fstat_track_second(fd: int):
                res = real_fstat(fd)
                if armed and fd == state_box["owned_fd"]:
                    state_box["owned_fstats"] += 1
                    if state_box["owned_fstats"] == 2:
                        state_box["eof_fstat_done"] = True
                return res

            def lstat_fail_post_eof_second(path, *a, **kw):
                if (
                    armed
                    and state_box["eof_fstat_done"]
                    and not state_box["fired"]
                    and str(path) == second_path
                ):
                    state_box["fired"] = True
                    raise lookup_eio
                return real_lstat(path, *a, **kw)

            with (
                mock.patch(
                    "refmac_diagnostic_profile._collect_file_dependencies",
                    side_effect=deps_replace_link,
                ),
                mock.patch(
                    "refmac_diagnostic_profile._observe_regular_file_pin",
                    side_effect=observe_track_second,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.open",
                    side_effect=open_track_second,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.fstat",
                    side_effect=fstat_track_second,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.lstat",
                    side_effect=lstat_fail_post_eof_second,
                ),
            ):
                with self.assertRaises(ProfileValidationError) as fail_ctx:
                    validate_profile(
                        profile, installed_record, ccp4_env, ev_root
                    )

            self.assertTrue(state_box["fired"])
            self.assertEqual(len(inodes), 2)
            self.assertNotEqual(inodes[0], inodes[1])

            failure = fail_ctx.exception
            self.assertIs(failure.cause_exception, lookup_eio)
            fobs_first = failure.files[first_fid]
            self.assertIsInstance(fobs_first, FileObservation)
            fobs_second = failure.files[second_fid]
            assert isinstance(fobs_second, PartialFileReadObservation)

            # Contextual copy allocated by _build_partial_file_observation preserves all post-EOF fields
            # while marking dependencies_complete=False and retaining both errors.
            self.assertFalse(fobs_second.dependencies_complete)
            self.assertFalse(fobs_second.verified)
            self.assertFalse(fobs_second.read_complete)
            self.assertTrue(fobs_second.observed_eof)
            self.assertEqual(
                fobs_second.streamed_size_bytes, len(target_bytes)
            )
            self.assertEqual(fobs_second.observed_stream_sha256, target_sha)
            self.assertEqual(fobs_second.observed_eof_sha256, target_sha)
            self.assertIsNotNone(fobs_second.initial_fstat)
            self.assertIsNotNone(fobs_second.end_fstat)
            self.assertEqual(fobs_second.failure_phase, "final_kernel_lookup")
            self.assertIsNotNone(fobs_second.post_read_observation)
            self.assertEqual(len(fobs_second.errors), 2)
            self.assertIn(
                "Kernel path lookup failed", fobs_second.errors[0]
            )
            self.assertIn(
                "Symlink identity changed during observation",
                fobs_second.errors[1],
            )

    def test_task1023_post_eof_kernel_lookup_nonregular_producer(self) -> None:
        real_fdopen = os.fdopen
        real_fstat = os.fstat
        real_lstat = os.lstat
        real_stat = os.stat
        payload = b"owned completed stream\n"
        digest = _sha256_bytes(payload)

        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir).resolve()
            for case in ("final_directory", "final_fifo"):
                with self.subTest(kernel_nonregular_case=case):
                    r = base_dir / case
                    r.mkdir()
                    p = r / "input.bin"
                    p.write_bytes(payload)
                    initial = real_lstat(p)
                    state: dict[str, object] = {
                        "eof": False,
                        "fd": -1,
                        "mutated": False,
                        "bytes_read": 0,
                        "facts": [],
                    }
                    stream_hash = hashlib.sha256()

                    def mutate_target() -> None:
                        self.assertFalse(state["mutated"])
                        p.rename(r / "original.bin")
                        if case == "final_directory":
                            p.mkdir()
                        else:
                            os.mkfifo(p)
                        state["mutated"] = True

                    def fdopen_hook(fd: int, *a, **kw):
                        state["fd"] = fd
                        handle = real_fdopen(fd, *a, **kw)
                        orig_read = handle.read

                        def read_hook(n: int = -1) -> bytes:
                            b = orig_read(n)
                            state["bytes_read"] = int(state["bytes_read"]) + len(b)  # type: ignore[arg-type]
                            stream_hash.update(b)
                            if not b:
                                state["eof"] = True
                                if not state["mutated"]:
                                    mutate_target()
                            return b

                        handle.read = read_hook  # type: ignore[method-assign]
                        return handle

                    def remember(stage_kind: str, path, s: os.stat_result):
                        if state["eof"] and state["mutated"] and str(path) == str(p):
                            facts_list = state["facts"]
                            assert isinstance(facts_list, list)
                            facts_list.append(
                                {
                                    "stage": stage_kind,
                                    "dev": int(s.st_dev),
                                    "ino": int(s.st_ino),
                                    "file_type": stat.S_IFMT(s.st_mode),
                                    "mode": int(s.st_mode),
                                    "uid": int(s.st_uid),
                                    "gid": int(s.st_gid),
                                    "size": int(s.st_size),
                                }
                            )
                        return s

                    def lstat_hook(path, *a, **kw):
                        return remember(
                            "lstat", path, real_lstat(path, *a, **kw)
                        )

                    def stat_hook(path, *a, **kw):
                        return remember("stat", path, real_stat(path, *a, **kw))

                    with (
                        mock.patch(
                            "refmac_diagnostic_profile.os.fdopen",
                            side_effect=fdopen_hook,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.lstat",
                            side_effect=lstat_hook,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.stat",
                            side_effect=stat_hook,
                        ),
                    ):
                        with self.assertRaises(_PartialFileReadError) as ctx:
                            profile_mod._stream_observe_regular_file(
                                str(p), retain_bytes=True, chunk_size=7
                            )

                    self.assertTrue(state["eof"])
                    self.assertTrue(state["mutated"])
                    self.assertEqual(state["bytes_read"], len(payload))
                    self.assertEqual(stream_hash.hexdigest(), digest)
                    fd_val = int(state["fd"])  # type: ignore[arg-type]
                    self.assertGreaterEqual(fd_val, 0)
                    with self.assertRaises(OSError) as ebadf_ctx:
                        real_fstat(fd_val)
                    self.assertEqual(ebadf_ctx.exception.errno, errno.EBADF)

                    err = ctx.exception
                    ob = err.observation
                    self.assertIs(type(ob), PartialFileReadObservation)
                    self.assertIsNone(ob.sha256)
                    self.assertIsNone(ob.size_bytes)
                    self.assertFalse(ob.verified)
                    self.assertFalse(ob.read_complete)
                    self.assertTrue(ob.observed_eof)
                    post = ob.post_read_observation
                    assert post is not None
                    self.assertTrue(post.observed_eof)
                    self.assertEqual(ob.streamed_size_bytes, len(payload))
                    self.assertEqual(post.streamed_size_bytes, len(payload))
                    self.assertEqual(ob.observed_stream_sha256, digest)
                    self.assertEqual(ob.observed_eof_sha256, digest)
                    self.assertEqual(post.observed_stream_sha256, digest)
                    self.assertEqual(post.observed_eof_sha256, digest)
                    self.assertEqual(ob.failure_phase, "final_kernel_lookup")
                    self.assertEqual(post.failure_phase, "final_kernel_lookup")
                    assert post.initial_fstat is not None
                    assert post.end_fstat is not None
                    self.assertEqual(
                        post.initial_fstat.ino, int(initial.st_ino)
                    )
                    self.assertEqual(post.end_fstat.ino, int(initial.st_ino))
                    self.assertEqual(
                        post.initial_fstat.dev, int(initial.st_dev)
                    )
                    self.assertEqual(post.end_fstat.dev, int(initial.st_dev))

                    facts_list = state["facts"]
                    assert isinstance(facts_list, list)
                    self.assertEqual(len(facts_list), 2)
                    self.assertEqual(
                        [f["stage"] for f in facts_list], ["lstat", "stat"]
                    )
                    expected_kind = (
                        "directory" if case == "final_directory" else "fifo"
                    )
                    for observed_snap, actual_fact in zip(
                        (post.final_lexical_lstat, post.final_lexical_stat),
                        facts_list,
                    ):
                        assert observed_snap is not None
                        self.assertNotEqual(
                            observed_snap.ino, int(initial.st_ino)
                        )
                        self.assertEqual(
                            (
                                observed_snap.dev,
                                observed_snap.ino,
                                observed_snap.mode,
                                observed_snap.uid,
                                observed_snap.gid,
                                observed_snap.size_bytes,
                                observed_snap.file_type,
                                observed_snap.raw_mode,
                            ),
                            (
                                actual_fact["dev"],
                                actual_fact["ino"],
                                stat.S_IMODE(actual_fact["mode"]),
                                actual_fact["uid"],
                                actual_fact["gid"],
                                actual_fact["size"],
                                actual_fact["file_type"],
                                actual_fact["mode"],
                            ),
                        )
                        self.assertEqual(observed_snap.kind, expected_kind)
                        self.assertFalse(observed_snap.is_regular)
                        self.assertFalse(observed_snap.is_symlink)
                        self.assertEqual(
                            observed_snap.is_directory,
                            case == "final_directory",
                        )
                        self.assertEqual(
                            observed_snap.is_fifo, case == "final_fifo"
                        )

                    self.assertIsNone(post.final_traversal_resolved_path)
                    self.assertIsNone(post.final_traversal_target_lstat)
                    self.assertIsNone(post.final_traversal_observation)
                    self.assertIsNone(post.final_resolved_path)
                    self.assertIsNone(post.final_resolved_target_lstat)
                    self.assertIsNone(post.final_resolution_observation)

                    with (
                        mock.patch(
                            "refmac_diagnostic_profile.os.stat",
                            side_effect=AssertionError("stat forbidden"),
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.lstat",
                            side_effect=AssertionError("lstat forbidden"),
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.open",
                            side_effect=AssertionError("open forbidden"),
                        ),
                    ):
                        orig_dict = ob.to_dict()
                        mut_dict = ob.to_dict()
                        mut_dict["post_read_observation"][
                            "final_lexical_lstat"
                        ]["ino"] = -1
                        self.assertEqual(ob.to_dict(), orig_dict)

                    # Pre-open exclusion control: non-regular path before open raises ValueError, not _PartialFileReadError
                    with self.assertRaises(ValueError) as pre_open_ctx:
                        profile_mod._stream_observe_regular_file(str(p))
                    self.assertNotIsInstance(
                        pre_open_ctx.exception, _PartialFileReadError
                    )

    def test_task1023_post_eof_target_resolution_stage_producer(self) -> None:
        real_fdopen = os.fdopen
        real_fstat = os.fstat
        real_lstat = os.lstat
        real_path_resolve = Path.resolve
        real_resolve = profile_mod._resolve_regular_target_strict
        real_traverse = profile_mod._traverse_path_components
        payload = b"owned resolution completed stream\n"
        digest = _sha256_bytes(payload)

        def stat_dict(st: os.stat_result) -> dict[str, int]:
            return {
                "dev": int(st.st_dev),
                "ino": int(st.st_ino),
                "raw_mode": int(st.st_mode),
                "mode": int(stat.S_IMODE(st.st_mode)),
                "file_type": int(stat.S_IFMT(st.st_mode)),
                "uid": int(st.st_uid),
                "gid": int(st.st_gid),
                "size_bytes": int(st.st_size),
            }

        def check_stat(ob, actual: dict[str, int]) -> None:
            self.assertIsNotNone(ob)
            self.assertEqual({k: getattr(ob, k) for k in actual}, actual)

        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir).resolve()
            for case in (
                "ancestor_eio",
                "final_target_symlink",
                "initial_component_symlink",
                "resolved_root_directory",
            ):
                with self.subTest(resolution_case=case):
                    root = (base_dir / case).resolve()
                    root.mkdir()
                    p = root / "input.bin"
                    p.write_bytes(payload)
                    initial = real_lstat(p)
                    injected = OSError(
                        errno.EIO, "owned post-EOF ancestor lstat failure"
                    )
                    state: dict[str, object] = {
                        "eof": False,
                        "fd": -1,
                        "in_resolve": False,
                        "in_path_resolve": False,
                        "target_calls": 0,
                        "events": [],
                        "path_resolve_events": [],
                        "path_resolve_returns": [],
                        "traversal_returns": [],
                        "failed_path": None,
                        "bytes_read": 0,
                        "mutated": False,
                        "resolver_error": None,
                    }
                    stream_hash = hashlib.sha256()

                    def fdopen_hook(fd: int, *a, **kw):
                        state["fd"] = fd
                        handle = real_fdopen(fd, *a, **kw)
                        orig_read = handle.read

                        def read_hook(n: int = -1) -> bytes:
                            b = orig_read(n)
                            stream_hash.update(b)
                            state["bytes_read"] = int(state["bytes_read"]) + len(b)  # type: ignore[arg-type]
                            if not b:
                                state["eof"] = True
                            return b

                        handle.read = read_hook  # type: ignore[method-assign]
                        return handle

                    def path_resolve_hook(path_obj: Path, *a, **kw):
                        prev = state["in_path_resolve"]
                        state["in_path_resolve"] = True
                        if (
                            state["eof"]
                            and state["in_resolve"]
                            and case == "resolved_root_directory"
                        ):
                            self.assertFalse(state["mutated"])
                            p.rename(root / "original.bin")
                            p.symlink_to("/")
                            state["mutated"] = True
                        try:
                            res_path = real_path_resolve(path_obj, *a, **kw)
                            if state["eof"] and state["in_resolve"]:
                                self.assertIs(kw.get("strict"), True)
                                pr_rets = state["path_resolve_returns"]
                                assert isinstance(pr_rets, list)
                                pr_rets.append(str(res_path))
                            return res_path
                        finally:
                            state["in_path_resolve"] = prev

                    def lstat_hook(path, *a, **kw):
                        explicit = bool(
                            state["eof"]
                            and state["in_resolve"]
                            and not state["in_path_resolve"]
                        )
                        if explicit:
                            if str(path) == str(p):
                                state["target_calls"] = (
                                    int(state["target_calls"]) + 1  # type: ignore[arg-type]
                                )
                                if (
                                    case == "ancestor_eio"
                                    and state["target_calls"] == 1
                                ):
                                    p.rename(root / "original.bin")
                                    p.write_bytes(payload)
                                    state["mutated"] = True
                                wanted = (
                                    1
                                    if case == "initial_component_symlink"
                                    else 2
                                )
                                if (
                                    case.endswith("symlink")
                                    and state["target_calls"] == wanted
                                ):
                                    self.assertFalse(state["mutated"])
                                    p.rename(root / "original.bin")
                                    p.symlink_to(root / "original.bin")
                                    state["mutated"] = True
                            if case == "ancestor_eio" and str(path) == str(
                                root.parent
                            ):
                                self.assertEqual(state["target_calls"], 1)
                                state["failed_path"] = str(path)
                                raise injected
                        s = real_lstat(path, *a, **kw)
                        row = {
                            "path": str(path),
                            "stat": stat_dict(s),
                            "target_call": state["target_calls"],
                        }
                        if explicit:
                            ev_list = state["events"]
                            assert isinstance(ev_list, list)
                            ev_list.append(row)
                        elif (
                            state["eof"]
                            and state["in_resolve"]
                            and state["in_path_resolve"]
                        ):
                            pr_evs = state["path_resolve_events"]
                            assert isinstance(pr_evs, list)
                            pr_evs.append(row)
                        return s

                    def resolve_hook(path_str: str):
                        prev = state["in_resolve"]
                        state["in_resolve"] = True
                        try:
                            return real_resolve(path_str)
                        except BaseException as exc:
                            if state["eof"]:
                                state["resolver_error"] = exc
                            raise
                        finally:
                            state["in_resolve"] = prev

                    def traverse_hook(path_str: str):
                        result = real_traverse(path_str)
                        if state["eof"]:
                            tr_rets = state["traversal_returns"]
                            assert isinstance(tr_rets, list)
                            tr_rets.append(
                                {
                                    "path": result.resolved_path,
                                    "stat": stat_dict(result.target_lstat),
                                }
                            )
                        return result

                    with (
                        mock.patch(
                            "refmac_diagnostic_profile.os.fdopen",
                            side_effect=fdopen_hook,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.lstat",
                            side_effect=lstat_hook,
                        ),
                        mock.patch.object(Path, "resolve", path_resolve_hook),
                        mock.patch.object(
                            profile_mod,
                            "_resolve_regular_target_strict",
                            side_effect=resolve_hook,
                        ),
                        mock.patch.object(
                            profile_mod,
                            "_traverse_path_components",
                            side_effect=traverse_hook,
                        ),
                    ):
                        with self.assertRaises(_PartialFileReadError) as ctx:
                            profile_mod._stream_observe_regular_file(
                                str(p), retain_bytes=True, chunk_size=7
                            )

                    self.assertTrue(state["eof"])
                    self.assertEqual(state["bytes_read"], len(payload))
                    self.assertEqual(stream_hash.hexdigest(), digest)
                    fd_val = int(state["fd"])  # type: ignore[arg-type]
                    self.assertGreaterEqual(fd_val, 0)
                    with self.assertRaises(OSError) as ebadf_ctx:
                        real_fstat(fd_val)
                    self.assertEqual(ebadf_ctx.exception.errno, errno.EBADF)

                    err = ctx.exception
                    ob = err.observation
                    post = ob.post_read_observation
                    assert post is not None
                    res = post.final_resolution_observation
                    assert res is not None
                    self.assertIs(ob.final_resolution_observation, res)
                    self.assertIs(err.__cause__, state["resolver_error"])
                    self.assertIsNone(ob.sha256)
                    self.assertIsNone(ob.size_bytes)
                    self.assertFalse(ob.read_complete)
                    self.assertFalse(ob.verified)
                    self.assertTrue(ob.observed_eof)
                    self.assertTrue(post.observed_eof)
                    self.assertEqual(ob.observed_eof_sha256, digest)
                    self.assertEqual(post.observed_eof_sha256, digest)
                    self.assertEqual(ob.observed_stream_sha256, digest)
                    self.assertEqual(post.observed_stream_sha256, digest)
                    self.assertEqual(ob.streamed_size_bytes, len(payload))
                    self.assertEqual(post.streamed_size_bytes, len(payload))
                    self.assertEqual(
                        ob.failure_phase, "final_target_resolution"
                    )
                    self.assertEqual(
                        post.failure_phase, "final_target_resolution"
                    )
                    check_stat(post.initial_fstat, stat_dict(initial))
                    check_stat(post.end_fstat, stat_dict(initial))

                    expected_target = (
                        "/" if case == "resolved_root_directory" else str(p)
                    )
                    self.assertEqual(res.lexical_path, str(p))
                    self.assertEqual(res.resolved_path, expected_target)
                    self.assertEqual(post.final_resolved_path, expected_target)
                    self.assertEqual(
                        state["path_resolve_returns"], [expected_target]
                    )
                    tr_rets = state["traversal_returns"]
                    assert isinstance(tr_rets, list)
                    self.assertEqual(len(tr_rets), 1)
                    self.assertEqual(tr_rets[0]["path"], str(p))
                    self.assertEqual(post.final_traversal_resolved_path, str(p))
                    check_stat(
                        post.final_traversal_target_lstat, tr_rets[0]["stat"]
                    )

                    events = state["events"]
                    assert isinstance(events, list)
                    self.assertEqual(events[0]["path"], expected_target)
                    check_stat(res.first_target_lstat, events[0]["stat"])

                    if case == "ancestor_eio":
                        self.assertEqual(len(events), 2)
                        self.assertEqual(
                            [e["path"] for e in events], [str(p), str(root)]
                        )
                        self.assertEqual(
                            state["failed_path"], str(root.parent)
                        )
                        self.assertEqual(state["target_calls"], 1)
                        self.assertEqual(
                            res.failed_stage, "ancestor_component_lstat"
                        )
                        self.assertEqual(
                            res.failed_component_path, str(root.parent)
                        )
                        self.assertIsNone(res.final_target_lstat)
                        self.assertIsNone(res.failed_component_lstat)
                        self.assertEqual(len(res.ancestor_lstats), 1)
                        self.assertIs(
                            state["resolver_error"].__cause__,  # type: ignore[union-attr]
                            injected,
                        )
                        self.assertIs(
                            profile_mod._select_original_cause_exception(err),
                            injected,
                        )
                        assert res.first_target_lstat is not None
                        assert post.final_traversal_target_lstat is not None
                        self.assertNotEqual(
                            res.first_target_lstat.ino, int(initial.st_ino)
                        )
                        self.assertEqual(
                            post.final_traversal_target_lstat.ino,
                            int(initial.st_ino),
                        )
                        self.assertEqual(p.read_bytes(), payload)
                        self.assertEqual(
                            (root / "original.bin").read_bytes(), payload
                        )
                        expected_components = events
                    elif case == "initial_component_symlink":
                        self.assertEqual(len(events), 1)
                        self.assertEqual(state["target_calls"], 1)
                        self.assertTrue(state["mutated"])
                        self.assertEqual(
                            res.failed_stage,
                            "initial_target_component_symlink",
                        )
                        self.assertEqual(res.failed_component_path, str(p))
                        assert res.first_target_lstat is not None
                        self.assertTrue(res.first_target_lstat.is_symlink)
                        self.assertIsNone(res.final_target_lstat)
                        self.assertEqual(res.ancestor_lstats, ())
                        self.assertTrue(
                            str(err.__cause__).startswith(
                                "Resolved path still contains a symlink component"
                            )
                        )
                        self.assertIsNone(err.__cause__.__cause__)  # type: ignore[union-attr]
                        self.assertIs(
                            profile_mod._select_original_cause_exception(err),
                            state["resolver_error"],
                        )
                        check_stat(
                            res.failed_component_lstat, events[0]["stat"]
                        )
                        expected_components = events
                    elif case == "resolved_root_directory":
                        self.assertTrue(state["mutated"])
                        self.assertEqual(
                            [e["path"] for e in events], ["/", "/"]
                        )
                        self.assertEqual(
                            res.failed_stage, "final_target_not_regular"
                        )
                        self.assertEqual(res.failed_component_path, "/")
                        self.assertEqual(res.ancestor_lstats, ())
                        assert res.first_target_lstat is not None
                        assert res.final_target_lstat is not None
                        self.assertTrue(res.first_target_lstat.is_directory)
                        self.assertTrue(res.final_target_lstat.is_directory)
                        check_stat(res.final_target_lstat, events[-1]["stat"])
                        check_stat(
                            res.failed_component_lstat, events[-1]["stat"]
                        )
                        self.assertEqual(
                            post.final_resolved_target_lstat,
                            res.final_target_lstat,
                        )
                        self.assertTrue(
                            str(err.__cause__).startswith(
                                "Target is not a regular file:"
                            )
                        )
                        self.assertIsNone(err.__cause__.__cause__)  # type: ignore[union-attr]
                        self.assertIs(
                            profile_mod._select_original_cause_exception(err),
                            state["resolver_error"],
                        )
                        expected_components = events[:-1]
                    else:
                        self.assertEqual(state["target_calls"], 2)
                        self.assertTrue(state["mutated"])
                        self.assertEqual(
                            [e["path"] for e in events],
                            [str(p), *(str(a) for a in p.parents), str(p)],
                        )
                        self.assertEqual(
                            res.failed_stage, "final_target_not_regular"
                        )
                        self.assertEqual(res.failed_component_path, str(p))
                        check_stat(res.final_target_lstat, events[-1]["stat"])
                        check_stat(
                            res.failed_component_lstat, events[-1]["stat"]
                        )
                        assert res.final_target_lstat is not None
                        assert res.first_target_lstat is not None
                        self.assertTrue(res.final_target_lstat.is_symlink)
                        self.assertTrue(res.first_target_lstat.is_regular)
                        self.assertTrue(
                            str(err.__cause__).startswith(
                                "Target is not a regular file:"
                            )
                        )
                        self.assertIsNone(err.__cause__.__cause__)  # type: ignore[union-attr]
                        self.assertIs(
                            profile_mod._select_original_cause_exception(err),
                            state["resolver_error"],
                        )
                        self.assertNotEqual(
                            res.final_target_lstat.ino,
                            res.first_target_lstat.ino,
                        )
                        self.assertEqual(
                            post.final_resolved_target_lstat,
                            res.final_target_lstat,
                        )
                        expected_components = events[:-1]

                    self.assertEqual(
                        len(res.component_observations),
                        len(expected_components),
                    )
                    for idx, (comp, ev) in enumerate(
                        zip(res.component_observations, expected_components)
                    ):
                        self.assertEqual(comp.path, ev["path"])
                        self.assertIs(comp.is_target, idx == 0)
                        check_stat(comp.lstat, ev["stat"])
                    self.assertEqual(
                        res.ancestor_lstats, res.component_observations[1:]
                    )
                    if case not in (
                        "final_target_symlink",
                        "resolved_root_directory",
                    ):
                        self.assertIsNone(post.final_resolved_target_lstat)

                    with self.assertRaises(FrozenInstanceError):
                        res.failed_stage = "fabricated"  # type: ignore[misc]

                    with (
                        mock.patch(
                            "refmac_diagnostic_profile.os.stat",
                            side_effect=AssertionError("stat forbidden"),
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.lstat",
                            side_effect=AssertionError("lstat forbidden"),
                        ),
                        mock.patch.object(
                            Path,
                            "resolve",
                            side_effect=AssertionError("resolve forbidden"),
                        ),
                    ):
                        original = ob.to_dict()
                        detached = ob.to_dict()
                        detached["post_read_observation"][
                            "final_resolution_observation"
                        ]["component_observations"][0]["lstat"]["ino"] = -1
                        self.assertEqual(ob.to_dict(), original)
                        rd = original["post_read_observation"][
                            "final_resolution_observation"
                        ]
                        self.assertEqual(
                            original["final_resolution_observation"], rd
                        )
                        self.assertEqual(rd["lexical_path"], str(p))
                        self.assertEqual(
                            rd["resolved_path"], expected_target
                        )
                        self.assertEqual(rd["failed_stage"], res.failed_stage)
                        self.assertEqual(
                            rd["failed_component_path"],
                            res.failed_component_path,
                        )
                        contextual = profile_mod._build_partial_file_observation(
                            ob, errors=("owned contextual marker",)
                        )
                        self.assertIsNot(contextual, ob)
                        self.assertIs(contextual.post_read_observation, post)
                        self.assertIs(
                            contextual.final_resolution_observation, res
                        )
                        public = ProfileValidationError(
                            "owned projection",
                            failed_check="owned_resolution_probe",
                            manifest_identity=contextual,
                            files={"owned_file": contextual},
                            cause_exception=err,
                        )
                        provenance = public.to_provenance()
                        self.assertFalse(provenance["profile_files_verified"])
                        self.assertIsNone(provenance["selected_executable"])
                        for row in (
                            provenance["manifest"],
                            provenance["files"]["owned_file"],
                        ):
                            self.assertEqual(
                                row["post_read_observation"],
                                original["post_read_observation"],
                            )
                            self.assertEqual(
                                row["final_resolution_observation"], rd
                            )
                        if case == "ancestor_eio":
                            self.assertIs(public.cause_exception, injected)
                        copied = public.to_provenance()
                        copied["files"]["owned_file"]["post_read_observation"][
                            "final_resolution_observation"
                        ]["component_observations"][0]["lstat"]["ino"] = -2
                        self.assertEqual(public.to_provenance(), provenance)

    def test_task1023_post_eof_opaque_and_legacy_resolution_producer(
        self,
    ) -> None:
        real_resolve = profile_mod._resolve_regular_target_strict
        real_fdopen = os.fdopen
        real_fstat = os.fstat
        payload = b"owned opaque resolver fixture\n"
        digest = _sha256_bytes(payload)

        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir).resolve()
            for case in (
                "opaque_no_attributes",
                "completed_helper_then_legacy_refusal",
            ):
                with self.subTest(opaque_resolution_case=case):
                    root = base_dir / case
                    root.mkdir()
                    path = root / "input.bin"
                    path.write_bytes(payload)
                    state = {
                        "eof": False,
                        "fd": -1,
                        "bytes": 0,
                        "helper_completed": False,
                    }
                    injected = ValueError(
                        "owned opaque post-EOF helper refusal"
                    )

                    def fdopen_hook(fd: int, *a, **kw):
                        state["fd"] = fd
                        handle = real_fdopen(fd, *a, **kw)
                        orig_read = handle.read

                        def read_hook(n: int = -1) -> bytes:
                            b = orig_read(n)
                            state["bytes"] = int(state["bytes"]) + len(b)
                            if not b:
                                state["eof"] = True
                            return b

                        handle.read = read_hook  # type: ignore[method-assign]
                        return handle

                    def resolve_hook(p_str: str):
                        if not state["eof"]:
                            return real_resolve(p_str)
                        if case == "completed_helper_then_legacy_refusal":
                            resolved, st = real_resolve(p_str)
                            state["helper_completed"] = True
                            injected._partial_resolved_path = resolved  # type: ignore[attr-defined]
                            injected._partial_target_lstat = st  # type: ignore[attr-defined]
                        raise injected

                    with (
                        mock.patch(
                            "refmac_diagnostic_profile.os.fdopen",
                            side_effect=fdopen_hook,
                        ),
                        mock.patch.object(
                            profile_mod,
                            "_resolve_regular_target_strict",
                            side_effect=resolve_hook,
                        ),
                    ):
                        with self.assertRaises(_PartialFileReadError) as ctx:
                            profile_mod._stream_observe_regular_file(
                                str(path), retain_bytes=True, chunk_size=7
                            )

                    self.assertTrue(state["eof"])
                    self.assertEqual(state["bytes"], len(payload))
                    fd_val = int(state["fd"])
                    self.assertGreaterEqual(fd_val, 0)
                    with self.assertRaises(OSError) as ebadf_ctx:
                        real_fstat(fd_val)
                    self.assertEqual(ebadf_ctx.exception.errno, errno.EBADF)

                    err = ctx.exception
                    self.assertIs(err.__cause__, injected)
                    ob = err.observation
                    self.assertFalse(ob.verified)
                    self.assertFalse(ob.read_complete)
                    self.assertIsNone(ob.sha256)
                    self.assertIsNone(ob.size_bytes)
                    self.assertEqual(
                        ob.failure_phase, "final_target_resolution"
                    )
                    self.assertTrue(ob.observed_eof)
                    self.assertEqual(ob.observed_eof_sha256, digest)
                    self.assertIsNone(ob.final_resolution_observation)
                    self.assertIsNone(ob.final_resolution_failed_stage)
                    post = ob.post_read_observation
                    assert post is not None
                    self.assertIsNone(post.final_resolution_observation)
                    self.assertIsNone(post.final_resolution_failed_stage)
                    if case == "completed_helper_then_legacy_refusal":
                        self.assertTrue(state["helper_completed"])
                        self.assertEqual(post.final_resolved_path, str(path))
                        assert post.final_resolved_target_lstat is not None
                        self.assertEqual(
                            post.final_resolved_target_lstat.ino,
                            int(injected._partial_target_lstat.st_ino),  # type: ignore[attr-defined]
                        )
                    else:
                        self.assertFalse(state["helper_completed"])
                        self.assertIsNone(post.final_resolved_path)
                        self.assertIsNone(post.final_resolved_target_lstat)

    def test_task1023_post_eof_resolution_entrypoint_admission_and_recheck(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fx = _build_synthetic_outer_profile_fixture(Path(tmpdir))
            root = fx["root"]
            assert isinstance(root, Path)
            support_dir = root / "support"
            installed_record = fx["installed_record"]
            assert isinstance(installed_record, dict)
            ccp4_env = fx["ccp4_env"]
            assert isinstance(ccp4_env, dict)
            ev_root = fx["evidence_root"]
            assert isinstance(ev_root, Path)
            alias_symlink = fx["alias_symlink"]
            assert isinstance(alias_symlink, Path)
            manifest_path = fx["manifest_path"]
            assert isinstance(manifest_path, Path)
            profile = fx["profile"]
            assert isinstance(profile, RefmacDiagnosticProfile)
            base_payload = fx["manifest_payload"]
            assert isinstance(base_payload, dict)

            validated = validate_profile(
                profile, installed_record, ccp4_env, ev_root
            )
            state = validated._outer_state
            assert state is not None

            direct_fid = base_payload["roles"]["collection_interpreter"][0]  # type: ignore[index]
            alias_fid = next(
                fid
                for fid, row in base_payload["files"].items()  # type: ignore[union-attr]
                if row["path"] == str(alias_symlink)
            )
            dotdot_path_str = str(
                support_dir / "bin" / ".." / "collection-python"
            )
            dotdot_fid = next(
                fid
                for fid, row in base_payload["files"].items()  # type: ignore[union-attr]
                if row["path"] == dotdot_path_str
            )
            alias_resolved = str(alias_symlink.resolve(strict=True))
            alias_bytes = Path(alias_resolved).read_bytes()
            alias_sha = _sha256_bytes(alias_bytes)
            alias_orig_ino = int(os.lstat(alias_resolved).st_ino)

            real_open = os.open
            real_fdopen = os.fdopen
            real_fstat = os.fstat
            real_lstat = os.lstat
            real_path_resolve = Path.resolve
            real_resolve = profile_mod._resolve_regular_target_strict
            real_obs_pin = profile_mod._observe_regular_file_pin
            real_stream_obs = profile_mod._stream_observe_regular_file

            # 1. Declared-file owner (alias_fid) post-EOF resolution ancestor_component_lstat EIO
            # across validate_profile, _reobserve_outer_profile_state, and recheck_profile
            injected_exc = OSError(
                errno.EIO,
                "synthetic #1168 declared-file post-EOF resolution ancestor EIO",
            )
            run_state: dict[str, object] = {
                "active_lexical": None,
                "owned_fd": -1,
                "captured_fd": -1,
                "observed_eof_on_owned_fd": False,
                "in_resolve": False,
                "in_path_resolve": False,
                "target_calls": 0,
                "injected": False,
            }

            def reset_run_state() -> None:
                run_state["active_lexical"] = None
                run_state["owned_fd"] = -1
                run_state["captured_fd"] = -1
                run_state["observed_eof_on_owned_fd"] = False
                run_state["in_resolve"] = False
                run_state["in_path_resolve"] = False
                run_state["target_calls"] = 0
                run_state["injected"] = False

            def observe_pin_alias(path, *a, **kw):
                prev_lex = run_state["active_lexical"]
                path_str = str(path)
                run_state["active_lexical"] = path_str
                if path_str == str(alias_symlink) and not run_state["injected"]:
                    run_state["owned_fd"] = -1
                    run_state["observed_eof_on_owned_fd"] = False
                    run_state["target_calls"] = 0
                try:
                    return real_obs_pin(path, *a, **kw)
                finally:
                    if path_str == str(alias_symlink):
                        run_state["owned_fd"] = -1
                        run_state["observed_eof_on_owned_fd"] = False
                        run_state["target_calls"] = 0
                    run_state["active_lexical"] = prev_lex

            def open_alias(path, flags, *a, **kw):
                fd = real_open(path, flags, *a, **kw)
                if (
                    run_state["active_lexical"] == str(alias_symlink)
                    and not run_state["injected"]
                    and str(path) == alias_resolved
                ):
                    run_state["owned_fd"] = fd
                    run_state["captured_fd"] = fd
                    run_state["observed_eof_on_owned_fd"] = False
                return fd

            def fdopen_alias(fd: int, mode: str = "rb", *a, **kw):
                handle = real_fdopen(fd, mode, *a, **kw)
                if (
                    run_state["active_lexical"] == str(alias_symlink)
                    and fd == run_state["owned_fd"]
                ):
                    orig_read = handle.read

                    def read_track_eof(n: int = -1) -> bytes:
                        chunk = orig_read(n)
                        if chunk == b"":
                            run_state["observed_eof_on_owned_fd"] = True
                        return chunk

                    handle.read = read_track_eof  # type: ignore[method-assign]
                return handle

            def path_resolve_alias(path_obj: Path, *a, **kw):
                prev = run_state["in_path_resolve"]
                run_state["in_path_resolve"] = True
                try:
                    return real_path_resolve(path_obj, *a, **kw)
                finally:
                    run_state["in_path_resolve"] = prev

            def resolve_alias(path_str: str):
                prev = run_state["in_resolve"]
                run_state["in_resolve"] = True
                try:
                    return real_resolve(path_str)
                finally:
                    run_state["in_resolve"] = prev

            def lstat_alias(path, *a, **kw):
                explicit = bool(
                    run_state["active_lexical"] == str(alias_symlink)
                    and run_state["observed_eof_on_owned_fd"]
                    and run_state["in_resolve"]
                    and not run_state["in_path_resolve"]
                    and not run_state["injected"]
                )
                if explicit:
                    if str(path) == alias_resolved:
                        run_state["target_calls"] = (
                            int(run_state["target_calls"]) + 1  # type: ignore[arg-type]
                        )
                    elif (
                        run_state["target_calls"] == 1
                        and str(path) == str(root)
                    ):
                        run_state["injected"] = True
                        raise injected_exc
                return real_lstat(path, *a, **kw)

            reset_run_state()
            with (
                mock.patch(
                    "refmac_diagnostic_profile._observe_regular_file_pin",
                    side_effect=observe_pin_alias,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.open",
                    side_effect=open_alias,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.fdopen",
                    side_effect=fdopen_alias,
                ),
                mock.patch.object(Path, "resolve", path_resolve_alias),
                mock.patch.object(
                    profile_mod,
                    "_resolve_regular_target_strict",
                    side_effect=resolve_alias,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.lstat",
                    side_effect=lstat_alias,
                ),
            ):
                with self.assertRaises(ProfileValidationError) as val_ctx:
                    validate_profile(
                        profile, installed_record, ccp4_env, ev_root
                    )
            self.assertTrue(run_state["injected"])
            self.assertGreaterEqual(int(run_state["captured_fd"]), 0)  # type: ignore[arg-type]
            with self.assertRaises(OSError) as val_ebadf:
                real_fstat(int(run_state["captured_fd"]))  # type: ignore[arg-type]
            self.assertEqual(val_ebadf.exception.errno, errno.EBADF)

            val_err = val_ctx.exception
            self.assertEqual(
                val_err.failed_check, "outer_profile_files_and_roots"
            )
            self.assertIs(val_err.cause_exception, injected_exc)
            self.assertIsInstance(val_err.files[direct_fid], FileObservation)
            self.assertTrue(val_err.files[direct_fid].verified)
            self.assertIsInstance(val_err.files[dotdot_fid], FileObservation)
            self.assertTrue(val_err.files[dotdot_fid].verified)

            pobs = val_err.files[alias_fid]
            assert isinstance(pobs, PartialFileReadObservation)
            self.assertTrue(pobs.observed_eof)
            self.assertEqual(pobs.observed_eof_sha256, alias_sha)
            self.assertEqual(pobs.failure_phase, "final_target_resolution")
            res_obs = pobs.final_resolution_observation
            assert res_obs is not None
            self.assertEqual(res_obs.failed_stage, "ancestor_component_lstat")
            self.assertEqual(res_obs.lexical_path, str(alias_symlink))
            self.assertEqual(res_obs.resolved_path, alias_resolved)
            assert res_obs.first_target_lstat is not None
            self.assertEqual(res_obs.first_target_lstat.ino, alias_orig_ino)
            self.assertEqual(len(res_obs.ancestor_lstats), 1)
            self.assertEqual(res_obs.ancestor_lstats[0].path, str(support_dir))
            self.assertIsNone(res_obs.final_target_lstat)
            self.assertEqual(res_obs.failed_component_path, str(root))
            self.assertIsNone(res_obs.failed_component_lstat)

            prov = val_err.to_provenance()
            self.assertEqual(
                prov["files"][alias_fid]["final_resolution_observation"][
                    "failed_stage"
                ],
                "ancestor_component_lstat",
            )
            self.assertEqual(
                prov["files"][alias_fid]["post_read_observation"][
                    "final_resolution_observation"
                ]["failed_component_path"],
                str(root),
            )

            reset_run_state()
            with (
                mock.patch(
                    "refmac_diagnostic_profile._observe_regular_file_pin",
                    side_effect=observe_pin_alias,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.open",
                    side_effect=open_alias,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.fdopen",
                    side_effect=fdopen_alias,
                ),
                mock.patch.object(Path, "resolve", path_resolve_alias),
                mock.patch.object(
                    profile_mod,
                    "_resolve_regular_target_strict",
                    side_effect=resolve_alias,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.lstat",
                    side_effect=lstat_alias,
                ),
            ):
                priv_recheck = _reobserve_outer_profile_state(state)
            self.assertTrue(run_state["injected"])
            with self.assertRaises(OSError) as priv_ebadf:
                real_fstat(int(run_state["captured_fd"]))  # type: ignore[arg-type]
            self.assertEqual(priv_ebadf.exception.errno, errno.EBADF)
            self.assertFalse(priv_recheck.verified)
            self.assertNotIn(direct_fid, priv_recheck.partial_files)
            self.assertNotIn(dotdot_fid, priv_recheck.partial_files)
            self.assertIn(alias_fid, priv_recheck.partial_files)
            self.assertIs(priv_recheck.file_causes[alias_fid], injected_exc)
            priv_res = priv_recheck.partial_files[
                alias_fid
            ].final_resolution_observation
            assert priv_res is not None
            self.assertEqual(priv_res.failed_stage, "ancestor_component_lstat")
            self.assertEqual(priv_res.failed_component_path, str(root))

            reset_run_state()
            pub_causes: list[Exception | None] = []
            with (
                mock.patch(
                    "refmac_diagnostic_profile._observe_regular_file_pin",
                    side_effect=observe_pin_alias,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.open",
                    side_effect=open_alias,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.fdopen",
                    side_effect=fdopen_alias,
                ),
                mock.patch.object(Path, "resolve", path_resolve_alias),
                mock.patch.object(
                    profile_mod,
                    "_resolve_regular_target_strict",
                    side_effect=resolve_alias,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.lstat",
                    side_effect=lstat_alias,
                ),
            ):
                pub_report = recheck_profile(
                    validated, mutation_causes_out=pub_causes
                )
            self.assertTrue(run_state["injected"])
            with self.assertRaises(OSError) as pub_ebadf:
                real_fstat(int(run_state["captured_fd"]))  # type: ignore[arg-type]
            self.assertEqual(pub_ebadf.exception.errno, errno.EBADF)
            self.assertFalse(pub_report["verified"])
            self.assertTrue(
                pub_report["files"][direct_fid]["matches_baseline"]
            )
            self.assertEqual(pub_report["files"][direct_fid]["errors"], [])
            self.assertTrue(
                pub_report["files"][dotdot_fid]["matches_baseline"]
            )
            self.assertEqual(pub_report["files"][dotdot_fid]["errors"], [])
            pub_frow = pub_report["files"][alias_fid]
            self.assertFalse(pub_frow["matches_baseline"])
            self.assertEqual(
                pub_frow["observed"]["final_resolution_observation"][
                    "failed_stage"
                ],
                "ancestor_component_lstat",
            )
            self.assertEqual(
                pub_frow["observed"]["final_resolution_observation"][
                    "failed_component_path"
                ],
                str(root),
            )
            self.assertEqual(len(pub_causes), 1)
            self.assertIs(pub_causes[0], injected_exc)

            # 2. Manifest owner (manifest_pin) post-EOF resolution final_target_not_regular
            manifest_resolved = str(manifest_path.resolve(strict=True))
            manifest_bytes = manifest_path.read_bytes()
            manifest_sha = _sha256_bytes(manifest_bytes)
            park_manifest = manifest_path.with_name(
                "diagnostic-profile.parked.json"
            )
            m_state: dict[str, object] = {
                "active_lexical": None,
                "owned_fd": -1,
                "captured_fd": -1,
                "observed_eof_on_owned_fd": False,
                "in_resolve": False,
                "in_path_resolve": False,
                "target_calls": 0,
                "mutated": False,
            }

            def stream_obs_m(path, *a, **kw):
                prev_lex = m_state["active_lexical"]
                path_str = str(path)
                m_state["active_lexical"] = path_str
                try:
                    return real_stream_obs(path, *a, **kw)
                finally:
                    if path_str == str(manifest_path):
                        m_state["owned_fd"] = -1
                        m_state["observed_eof_on_owned_fd"] = False
                        m_state["target_calls"] = 0
                    m_state["active_lexical"] = prev_lex

            def open_m(path, flags, *a, **kw):
                fd = real_open(path, flags, *a, **kw)
                if (
                    m_state["active_lexical"] == str(manifest_path)
                    and not m_state["mutated"]
                    and str(path) == manifest_resolved
                ):
                    m_state["owned_fd"] = fd
                    m_state["captured_fd"] = fd
                    m_state["observed_eof_on_owned_fd"] = False
                return fd

            def fdopen_m(fd: int, mode: str = "rb", *a, **kw):
                handle = real_fdopen(fd, mode, *a, **kw)
                if (
                    m_state["active_lexical"] == str(manifest_path)
                    and fd == m_state["owned_fd"]
                ):
                    orig_read = handle.read

                    def read_track_m_eof(n: int = -1) -> bytes:
                        chunk = orig_read(n)
                        if chunk == b"":
                            m_state["observed_eof_on_owned_fd"] = True
                        return chunk

                    handle.read = read_track_m_eof  # type: ignore[method-assign]
                return handle

            def path_resolve_m(path_obj: Path, *a, **kw):
                prev = m_state["in_path_resolve"]
                m_state["in_path_resolve"] = True
                try:
                    return real_path_resolve(path_obj, *a, **kw)
                finally:
                    m_state["in_path_resolve"] = prev

            def resolve_m(path_str: str):
                prev = m_state["in_resolve"]
                m_state["in_resolve"] = True
                try:
                    return real_resolve(path_str)
                finally:
                    m_state["in_resolve"] = prev

            def lstat_m(path, *a, **kw):
                explicit = bool(
                    m_state["active_lexical"] == str(manifest_path)
                    and m_state["observed_eof_on_owned_fd"]
                    and m_state["in_resolve"]
                    and not m_state["in_path_resolve"]
                )
                if explicit and str(path) == manifest_resolved:
                    m_state["target_calls"] = (
                        int(m_state["target_calls"]) + 1  # type: ignore[arg-type]
                    )
                    if m_state["target_calls"] == 2 and not m_state["mutated"]:
                        manifest_path.rename(park_manifest)
                        manifest_path.symlink_to(park_manifest)
                        m_state["mutated"] = True
                return real_lstat(path, *a, **kw)

            with (
                mock.patch(
                    "refmac_diagnostic_profile._stream_observe_regular_file",
                    side_effect=stream_obs_m,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.open", side_effect=open_m
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.fdopen", side_effect=fdopen_m
                ),
                mock.patch.object(Path, "resolve", path_resolve_m),
                mock.patch.object(
                    profile_mod,
                    "_resolve_regular_target_strict",
                    side_effect=resolve_m,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.lstat", side_effect=lstat_m
                ),
                mock.patch(
                    "refmac_diagnostic_profile._parse_verified_json_bytes",
                    side_effect=AssertionError("must not parse JSON"),
                ) as mocked_parse,
                mock.patch(
                    "refmac_diagnostic_profile._validate_outer_manifest_shape",
                    side_effect=AssertionError("must not validate shape"),
                ) as mocked_shape,
                mock.patch(
                    "refmac_diagnostic_profile._observe_controlled_root",
                    side_effect=AssertionError("must not inspect roots"),
                ) as mocked_root,
            ):
                with self.assertRaises(ProfileValidationError) as m_ctx:
                    validate_profile(
                        profile, installed_record, ccp4_env, ev_root
                    )
                mocked_parse.assert_not_called()
                mocked_shape.assert_not_called()
                mocked_root.assert_not_called()

            self.assertTrue(m_state["mutated"])
            with self.assertRaises(OSError) as m_ebadf:
                real_fstat(int(m_state["captured_fd"]))  # type: ignore[arg-type]
            self.assertEqual(m_ebadf.exception.errno, errno.EBADF)
            m_err = m_ctx.exception
            self.assertEqual(m_err.failed_check, "manifest_pin")
            assert isinstance(
                m_err.manifest_identity, PartialFileReadObservation
            )
            self.assertTrue(m_err.manifest_identity.observed_eof)
            self.assertEqual(
                m_err.manifest_identity.observed_eof_sha256, manifest_sha
            )
            self.assertEqual(
                m_err.manifest_identity.failure_phase,
                "final_target_resolution",
            )
            m_res = m_err.manifest_identity.final_resolution_observation
            assert m_res is not None
            self.assertEqual(m_res.failed_stage, "final_target_not_regular")
            assert m_res.first_target_lstat is not None
            assert m_res.final_target_lstat is not None
            self.assertTrue(m_res.first_target_lstat.is_regular)
            self.assertTrue(m_res.final_target_lstat.is_symlink)
            self.assertEqual(
                m_res.failed_component_lstat, m_res.final_target_lstat
            )

    def test_task1023_stat_and_resolution_carrier_invariants(self) -> None:
        from dataclasses import replace

        ObservedStatSnapshot = profile_mod.ObservedStatSnapshot
        ResolutionComponentObservation = (
            profile_mod.ResolutionComponentObservation
        )
        FinalTargetResolutionObservation = (
            profile_mod.FinalTargetResolutionObservation
        )
        PostReadVerificationObservation = (
            profile_mod.PostReadVerificationObservation
        )

        self.assertIsNone(profile_mod._stat_to_lookup_obs_or_none(None))
        self.assertIsNone(profile_mod._stat_to_observed_stat_or_none(None))

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir).resolve()
            (root / "regular").write_bytes(b"owned\n")
            (root / "directory").mkdir()
            os.mkfifo(root / "fifo")
            (root / "symlink").symlink_to(root / "regular")

            snaps: dict[str, object] = {}
            for kind in ("regular", "directory", "fifo", "symlink"):
                st = (root / kind).lstat()
                ob = profile_mod._stat_to_lookup_obs_or_none(st)
                self.assertIs(type(ob), ObservedStatSnapshot)
                self.assertEqual(
                    ob, profile_mod._stat_to_observed_stat_or_none(st)
                )
                assert ob is not None
                snaps[kind] = ob
                self.assertEqual(
                    (
                        ob.dev,
                        ob.ino,
                        ob.mode,
                        ob.uid,
                        ob.gid,
                        ob.size_bytes,
                    ),
                    (
                        int(st.st_dev),
                        int(st.st_ino),
                        int(stat.S_IMODE(st.st_mode)),
                        int(st.st_uid),
                        int(st.st_gid),
                        int(st.st_size),
                    ),
                )
                self.assertEqual(ob.file_type, stat.S_IFMT(st.st_mode))
                self.assertEqual(ob.raw_mode, int(st.st_mode))
                self.assertEqual(ob.kind, kind)
                if kind in ("directory", "fifo"):
                    with self.assertRaises(ValueError):
                        LookupStatObservation.from_stat_result(st)
                else:
                    legacy = LookupStatObservation.from_stat_result(st)
                    self.assertEqual(ob, legacy)
                    self.assertEqual(legacy, ob)
                    self.assertEqual(hash(ob), hash(legacy))
                    self.assertEqual(
                        {ob: "same-observation"}[legacy], "same-observation"
                    )
                with self.assertRaises(FrozenInstanceError):
                    ob.ino = 1  # type: ignore[misc]
                with (
                    mock.patch(
                        "refmac_diagnostic_profile.os.stat",
                        side_effect=AssertionError("stat forbidden"),
                    ),
                    mock.patch(
                        "refmac_diagnostic_profile.os.lstat",
                        side_effect=AssertionError("lstat forbidden"),
                    ),
                    mock.patch(
                        "refmac_diagnostic_profile.os.open",
                        side_effect=AssertionError("open forbidden"),
                    ),
                ):
                    projection = ob.to_dict()
                    json.dumps(projection, allow_nan=False)
                    projection["ino"] = -1
                    self.assertEqual(ob.to_dict()["ino"], int(st.st_ino))

            reg = snaps["regular"]
            dir_snap = snaps["directory"]
            fifo_snap = snaps["fifo"]
            sym_snap = snaps["symlink"]
            for bad_kw in (
                {"is_directory": True},
                {"file_type": stat.S_IFDIR},
                {"dev": True},
                {"mode": reg.raw_mode},
            ):
                with self.assertRaises(ValueError):
                    replace(reg, **bad_kw)

            # ResolutionComponentObservation & FinalTargetResolutionObservation invariants
            res_path = str(root / "regular")
            parent_paths = [str(p) for p in Path(res_path).parents]
            anc_comps = tuple(
                ResolutionComponentObservation(
                    path=p_str, is_target=False, lstat=dir_snap
                )
                for p_str in parent_paths
            )
            first_comp = ResolutionComponentObservation(
                path=res_path, is_target=True, lstat=reg
            )

            # Bidirectional population between (first_target_lstat, ancestor_lstats) and component_observations
            from_comps = FinalTargetResolutionObservation(
                failed_stage="final_target_not_regular",
                lexical_path=res_path,
                resolved_path=res_path,
                component_observations=(first_comp, *anc_comps),
                final_target_lstat=sym_snap,
            )
            self.assertEqual(from_comps.first_target_lstat, reg)
            self.assertEqual(from_comps.ancestor_lstats, anc_comps)
            self.assertEqual(from_comps.failed_component_path, res_path)
            self.assertEqual(from_comps.failed_component_lstat, sym_snap)

            # Empty-root parent chain valid when resolved_path == "/"
            root_res = FinalTargetResolutionObservation(
                failed_stage="final_target_not_regular",
                lexical_path=res_path,
                resolved_path="/",
                first_target_lstat=dir_snap,
                ancestor_lstats=(),
                final_target_lstat=dir_snap,
            )
            self.assertEqual(root_res.failed_component_path, "/")
            self.assertEqual(len(root_res.component_observations), 1)

            # Reject invalid stage, incomplete ancestors for non-root final_target_*, wrong failed_component_path,
            # non-trailing symlink/non-directory ancestor, and regular final_target_lstat on final_target_not_regular
            with self.assertRaises(ValueError):
                FinalTargetResolutionObservation(
                    failed_stage="unknown_stage",
                    resolved_path=res_path,
                )
            with self.assertRaises(ValueError):
                FinalTargetResolutionObservation(
                    failed_stage="final_target_not_regular",
                    resolved_path=res_path,
                    first_target_lstat=reg,
                    ancestor_lstats=anc_comps[:-1],
                    final_target_lstat=sym_snap,
                )
            with self.assertRaises(ValueError):
                FinalTargetResolutionObservation(
                    failed_stage="ancestor_component_lstat",
                    resolved_path=res_path,
                    first_target_lstat=reg,
                    ancestor_lstats=anc_comps[:1],
                    failed_component_path=parent_paths[0],
                )
            with self.assertRaises(ValueError):
                FinalTargetResolutionObservation(
                    failed_stage="ancestor_component_lstat",
                    resolved_path=res_path,
                    first_target_lstat=reg,
                    ancestor_lstats=(
                        ResolutionComponentObservation(
                            path=parent_paths[0],
                            is_target=False,
                            lstat=fifo_snap,
                        ),
                        ResolutionComponentObservation(
                            path=parent_paths[1],
                            is_target=False,
                            lstat=dir_snap,
                        ),
                    ),
                )
            with self.assertRaises(ValueError):
                FinalTargetResolutionObservation(
                    failed_stage="final_target_not_regular",
                    resolved_path=res_path,
                    first_target_lstat=reg,
                    ancestor_lstats=anc_comps,
                    final_target_lstat=reg,
                )
            prod_file = root / "prod_res.bin"
            prod_file.write_bytes(b"owned\n")
            prod_resolved = str(prod_file.resolve(strict=True))
            real_lstat = os.lstat
            real_path_resolve = Path.resolve
            real_resolve = profile_mod._resolve_regular_target_strict
            prod_state: dict[str, object] = {
                "resolve_calls": 0,
                "in_path_resolve": False,
                "target_calls": 0,
            }

            def prod_path_resolve(path_obj: Path, *a, **kw):
                prev = prod_state["in_path_resolve"]
                prod_state["in_path_resolve"] = True
                try:
                    return real_path_resolve(path_obj, *a, **kw)
                finally:
                    prod_state["in_path_resolve"] = prev

            def prod_resolve(path_str: str):
                prod_state["resolve_calls"] = (
                    int(prod_state["resolve_calls"]) + 1  # type: ignore[arg-type]
                )
                return real_resolve(path_str)

            def prod_lstat(path, *a, **kw):
                if (
                    prod_state["resolve_calls"] == 2
                    and not prod_state["in_path_resolve"]
                    and str(path) == prod_resolved
                ):
                    prod_state["target_calls"] = (
                        int(prod_state["target_calls"]) + 1  # type: ignore[arg-type]
                    )
                    if prod_state["target_calls"] == 2:
                        parked = root / "prod_res.parked"
                        prod_file.rename(parked)
                        prod_file.symlink_to(parked)
                return real_lstat(path, *a, **kw)

            with (
                mock.patch.object(Path, "resolve", prod_path_resolve),
                mock.patch.object(
                    profile_mod,
                    "_resolve_regular_target_strict",
                    side_effect=prod_resolve,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.lstat",
                    side_effect=prod_lstat,
                ),
                self.assertRaises(_PartialFileReadError) as prod_ctx,
            ):
                profile_mod._stream_observe_regular_file(str(prod_file))

            accepted_post = prod_ctx.exception.observation.post_read_observation
            assert isinstance(accepted_post, PostReadVerificationObservation)
            self.assertGreater(len(accepted_post.final_traversed_directories), 0)
            assert accepted_post.final_resolution_observation is not None
            self.assertEqual(
                accepted_post.final_resolved_target_lstat,
                accepted_post.final_resolution_observation.final_target_lstat,
            )
            self.assertEqual(replace(accepted_post), accepted_post)

            with self.assertRaisesRegex(
                ValueError,
                r"^PostReadVerificationObservation\.final_resolved_target_lstat must match final_resolution_observation\.final_target_lstat$",
            ):
                replace(accepted_post, final_resolved_target_lstat=dir_snap)

            with self.assertRaisesRegex(
                ValueError,
                r"^PostReadVerificationObservation\.final_traversed_directories must be a non-empty tuple of _ObservedDirectoryIdentity$",
            ):
                replace(accepted_post, final_traversed_directories=())

            valid_partial_no_post = PartialFileReadObservation(
                path=str(prod_file),
                resolved_path=prod_resolved,
                stat_size_bytes=reg.size_bytes,
                streamed_size_bytes=0,
                read_complete=False,
                dev=reg.dev,
                ino=reg.ino,
                mode=0o644,
                uid=reg.uid,
                gid=reg.gid,
                verified=False,
                errors=("owned partial read without post_read_observation",),
                observed_eof=False,
                failure_phase="pre_read_size_check",
                post_read_observation=None,
            )
            valid_partial_dict = valid_partial_no_post.to_dict()
            self.assertEqual(valid_partial_dict["mode"], 0o644)
            self.assertEqual(
                valid_partial_dict["initial_fstat"]["mode"], 0o644
            )
            self.assertEqual(
                valid_partial_dict["initial_fstat"]["raw_mode"],
                int(stat.S_IFREG | 0o644),
            )
            with self.assertRaisesRegex(
                ValueError,
                r"^PartialFileReadObservation\.mode must be permission bits only \(S_IMODE\), got 0o100644$",
            ):
                replace(valid_partial_no_post, mode=0o100644)
            with self.assertRaisesRegex(
                ValueError,
                r"^PartialFileReadObservation\.mode must be permission bits only \(S_IMODE\), got 0o100644$",
            ):
                replace(prod_ctx.exception.observation, mode=0o100644)

    def test_task1024_post_eof_path_traversal_stage_producer(self) -> None:
        from contextlib import ExitStack

        real_lstat = os.lstat
        real_stat = os.stat
        real_readlink = os.readlink
        real_fdopen = os.fdopen
        real_fstat = os.fstat
        real_traverse = profile_mod._traverse_path_components
        real_lookup = profile_mod._validate_kernel_regular_lookup
        real_resolve = profile_mod._resolve_regular_target_strict
        payload = b"owned exact traversal witness\n"
        payload_digest = _sha256_bytes(payload)

        def facts(st: os.stat_result) -> dict[str, int]:
            return {
                "dev": int(st.st_dev),
                "ino": int(st.st_ino),
                "mode": int(stat.S_IMODE(st.st_mode)),
                "uid": int(st.st_uid),
                "gid": int(st.st_gid),
                "size_bytes": int(st.st_size),
                "file_type": int(stat.S_IFMT(st.st_mode)),
                "raw_mode": int(st.st_mode),
            }

        def compare_stat(ob, ev: dict[str, object]) -> None:
            self.assertIsNotNone(ob)
            st_map = ev["stat"]
            assert isinstance(st_map, dict)
            self.assertEqual({k: getattr(ob, k) for k in st_map}, st_map)
            self.assertIs(ob.is_regular, stat.S_ISREG(st_map["raw_mode"]))
            self.assertIs(ob.is_symlink, stat.S_ISLNK(st_map["raw_mode"]))

        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir).resolve()
            for case in (
                "terminal_directory",
                "literal_suffix",
                "readlink_eio",
                "repeated_link_target",
                "repeated_link_inode",
                "repeated_directory",
            ):
                with self.subTest(traversal_case=case):
                    root = (base_dir / case).resolve()
                    root.mkdir()
                    repeated = case.startswith("repeated_")
                    if repeated:
                        for d_name in ("d", "e"):
                            (root / d_name).mkdir()
                            (root / d_name / "input.bin").write_bytes(payload)
                        if case == "repeated_directory":
                            mutation_path = root / "d"
                            lexical = f"{root}/d/../d/input.bin"
                        else:
                            mutation_path = root / "link"
                            mutation_path.symlink_to("d")
                            lexical = f"{root}/link/../link/input.bin"
                    else:
                        mutation_path = root / "input.bin"
                        mutation_path.write_bytes(payload)
                        (root / "suffix").mkdir()
                        lexical = str(mutation_path)

                    initial = real_stat(lexical)
                    state: dict[str, object] = {
                        "eof": False,
                        "in_traverse": False,
                        "in_preliminary": False,
                        "mutated": False,
                        "component_hits": 0,
                        "fd": -1,
                        "bytes_read": 0,
                        "in_lookup": False,
                        "post_eof_resolver_entries": 0,
                        "post_eof_traversal_invocations": 0,
                    }
                    events: list[dict[str, object]] = []
                    outer_events: list[dict[str, object]] = []
                    descriptor_events: list[dict[str, object]] = []
                    caught_helpers: list[Exception] = []
                    injected = OSError(
                        errno.EIO, "owned exact traversal readlink refusal"
                    )
                    digest = hashlib.sha256()

                    def record_event(call_name: str, path_val, **extra):
                        row = {
                            "index": len(events),
                            "call": call_name,
                            "path": str(path_val),
                            "preliminary": state["in_preliminary"],
                            "invocation": state[
                                "post_eof_traversal_invocations"
                            ],
                            **extra,
                        }
                        events.append(row)
                        return row

                    def mutate() -> None:
                        self.assertFalse(state["mutated"])
                        mutation_path.rename(root / "original-entry")
                        if case in ("terminal_directory", "repeated_directory"):
                            mutation_path.mkdir()
                        elif case == "literal_suffix":
                            mutation_path.symlink_to("suffix/")
                        elif case in ("readlink_eio", "repeated_link_inode"):
                            mutation_path.symlink_to(
                                "original-entry"
                                if case == "readlink_eio"
                                else "d"
                            )
                        else:
                            mutation_path.symlink_to("e")
                        state["mutated"] = True

                    def fdopen_hook(fd: int, *a, **kw):
                        state["fd"] = fd
                        handle = real_fdopen(fd, *a, **kw)
                        orig_read = handle.read

                        def read_hook(n: int = -1) -> bytes:
                            b = orig_read(n)
                            state["bytes_read"] = (
                                int(state["bytes_read"]) + len(b)  # type: ignore[arg-type]
                            )
                            digest.update(b)
                            if not b:
                                state["eof"] = True
                            return b

                        handle.read = read_hook  # type: ignore[method-assign]
                        return handle

                    def lstat_hook(path, *a, **kw):
                        active = bool(state["eof"] and state["in_traverse"])
                        if (
                            active
                            and not state["in_preliminary"]
                            and str(path) == str(mutation_path)
                        ):
                            state["component_hits"] = (
                                int(state["component_hits"]) + 1  # type: ignore[arg-type]
                            )
                            if state["component_hits"] == (2 if repeated else 1):
                                mutate()
                        st = real_lstat(path, *a, **kw)
                        if active:
                            record_event("lstat", path, stat=facts(st))
                        elif state["eof"] and state["in_lookup"]:
                            outer_events.append(
                                {
                                    "call": "lstat",
                                    "path": str(path),
                                    "stat": facts(st),
                                }
                            )
                        return st

                    def stat_hook(path, *a, **kw):
                        st = real_stat(path, *a, **kw)
                        if state["eof"] and state["in_traverse"]:
                            record_event("stat", path, stat=facts(st))
                        elif state["eof"] and state["in_lookup"]:
                            outer_events.append(
                                {
                                    "call": "stat",
                                    "path": str(path),
                                    "stat": facts(st),
                                }
                            )
                        return st

                    def fstat_hook(fd: int):
                        st = real_fstat(fd)
                        if (
                            st.st_dev == initial.st_dev
                            and st.st_ino == initial.st_ino
                        ):
                            descriptor_events.append(
                                {
                                    "fd": fd,
                                    "eof": state["eof"],
                                    "stat": facts(st),
                                }
                            )
                        return st

                    def readlink_hook(path, *a, **kw):
                        active = bool(state["eof"] and state["in_traverse"])
                        if (
                            active
                            and case == "readlink_eio"
                            and str(path) == str(mutation_path)
                        ):
                            record_event(
                                "readlink",
                                path,
                                returned=False,
                                errno=errno.EIO,
                            )
                            raise injected
                        val = real_readlink(path, *a, **kw)
                        if active:
                            record_event(
                                "readlink", path, returned=True, target=val
                            )
                        return val

                    def lookup_hook(path_str: str):
                        old_prelim = state["in_preliminary"]
                        old_lookup = state["in_lookup"]
                        state["in_lookup"] = True
                        state["in_preliminary"] = state["in_traverse"]
                        try:
                            return real_lookup(path_str)
                        finally:
                            state["in_preliminary"] = old_prelim
                            state["in_lookup"] = old_lookup

                    def resolve_hook(path_str: str):
                        if state["eof"]:
                            state["post_eof_resolver_entries"] = (
                                int(state["post_eof_resolver_entries"]) + 1  # type: ignore[arg-type]
                            )
                        return real_resolve(path_str)

                    def traverse_hook(path_str: str):
                        state["in_traverse"] = True
                        if state["eof"]:
                            state["post_eof_traversal_invocations"] = (
                                int(state["post_eof_traversal_invocations"]) + 1  # type: ignore[arg-type]
                            )
                        try:
                            return real_traverse(path_str)
                        except Exception as exc:
                            if state["eof"]:
                                caught_helpers.append(exc)
                            raise
                        finally:
                            state["in_traverse"] = False

                    with (
                        mock.patch(
                            "refmac_diagnostic_profile.os.fdopen",
                            side_effect=fdopen_hook,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.fstat",
                            side_effect=fstat_hook,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.lstat",
                            side_effect=lstat_hook,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.stat",
                            side_effect=stat_hook,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.readlink",
                            side_effect=readlink_hook,
                        ),
                        mock.patch.object(
                            profile_mod,
                            "_traverse_path_components",
                            side_effect=traverse_hook,
                        ),
                        mock.patch.object(
                            profile_mod,
                            "_validate_kernel_regular_lookup",
                            side_effect=lookup_hook,
                        ),
                        mock.patch.object(
                            profile_mod,
                            "_resolve_regular_target_strict",
                            side_effect=resolve_hook,
                        ),
                    ):
                        with self.assertRaises(_PartialFileReadError) as ctx:
                            profile_mod._stream_observe_regular_file(
                                lexical, retain_bytes=True, chunk_size=7
                            )

                    self.assertTrue(state["eof"])
                    self.assertTrue(state["mutated"])
                    self.assertEqual(state["bytes_read"], len(payload))
                    self.assertEqual(digest.hexdigest(), payload_digest)
                    fd_val = int(state["fd"])  # type: ignore[arg-type]
                    self.assertGreaterEqual(fd_val, 0)
                    with self.assertRaises(OSError) as ebadf_ctx:
                        real_fstat(fd_val)
                    self.assertEqual(ebadf_ctx.exception.errno, errno.EBADF)

                    err = ctx.exception
                    self.assertEqual(len(caught_helpers), 1)
                    self.assertIs(err.__cause__, caught_helpers[0])
                    ob = err.observation
                    post = ob.post_read_observation
                    assert post is not None
                    self.assertIsNone(ob.sha256)
                    self.assertIsNone(ob.size_bytes)
                    self.assertFalse(ob.verified)
                    self.assertFalse(ob.read_complete)
                    self.assertFalse(ob.complete)
                    with self.assertRaises(ValueError):
                        ob.as_file_pin()
                    self.assertTrue(ob.observed_eof)
                    self.assertTrue(post.observed_eof)
                    self.assertEqual(
                        ob.failure_phase, "final_path_traversal"
                    )
                    self.assertEqual(
                        post.failure_phase, "final_path_traversal"
                    )
                    self.assertEqual(ob.observed_eof_sha256, payload_digest)
                    self.assertEqual(post.observed_eof_sha256, payload_digest)
                    self.assertEqual(ob.observed_stream_sha256, payload_digest)
                    self.assertEqual(
                        post.observed_stream_sha256, payload_digest
                    )
                    self.assertEqual(ob.streamed_size_bytes, len(payload))
                    self.assertEqual(post.streamed_size_bytes, len(payload))
                    self.assertEqual(len(descriptor_events), 2)
                    self.assertEqual(
                        [e["eof"] for e in descriptor_events], [False, True]
                    )
                    compare_stat(post.initial_fstat, descriptor_events[0])
                    compare_stat(post.end_fstat, descriptor_events[1])
                    self.assertEqual(
                        [e["call"] for e in outer_events], ["lstat", "stat"]
                    )
                    self.assertTrue(
                        all(e["path"] == lexical for e in outer_events)
                    )
                    compare_stat(post.final_lexical_lstat, outer_events[0])
                    compare_stat(post.final_lexical_stat, outer_events[1])
                    self.assertEqual(state["post_eof_resolver_entries"], 0)
                    self.assertEqual(
                        state["post_eof_traversal_invocations"], 1
                    )
                    self.assertTrue(all(e["invocation"] == 1 for e in events))

                    t = post.final_traversal_observation
                    assert t is not None
                    self.assertIs(ob.final_traversal_observation, t)
                    self.assertEqual(t.lexical_path, lexical)
                    preliminary = [e for e in events if e["preliminary"]]
                    self.assertEqual(
                        [e["call"] for e in preliminary], ["lstat", "stat"]
                    )
                    compare_stat(t.preliminary_lexical_lstat, preliminary[0])
                    compare_stat(t.preliminary_lexical_stat, preliminary[1])

                    component_events = [
                        e
                        for e in events
                        if not e["preliminary"] and e["call"] == "lstat"
                    ]
                    self.assertEqual(component_events[0]["path"], "/")
                    compare_stat(t.root_lstat, component_events[0])
                    self.assertEqual(
                        len(t.component_observations), len(component_events)
                    )
                    for idx, (comp, actual) in enumerate(
                        zip(t.component_observations, component_events)
                    ):
                        self.assertEqual(comp.path, actual["path"])
                        compare_stat(comp.lstat, actual)
                        self.assertIs(
                            comp.accepted, idx < len(component_events) - 1
                        )
                    rejected = t.component_observations[-1]
                    self.assertEqual(t.rejected_component, rejected)
                    self.assertFalse(rejected.accepted)
                    self.assertEqual(
                        t.failed_component_path, str(mutation_path)
                    )
                    self.assertEqual(rejected.path, str(mutation_path))
                    compare_stat(
                        t.failed_component_lstat, component_events[-1]
                    )
                    self.assertEqual(t.failed_component_lstat, rejected.lstat)
                    self.assertIsNone(post.final_traversal_resolved_path)
                    self.assertIsNone(post.final_traversal_target_lstat)
                    self.assertIsNone(post.final_resolution_observation)
                    self.assertIsNone(post.final_resolved_path)
                    self.assertIsNone(post.final_resolved_target_lstat)

                    expected_stage = {
                        "terminal_directory": "leaf_component_directory",
                        "literal_suffix": "leaf_symlink_directory_suffix",
                        "readlink_eio": "symlink_readlink",
                        "repeated_link_target": "symlink_target_changed",
                        "repeated_link_inode": "symlink_identity_changed",
                        "repeated_directory": "directory_identity_changed",
                    }[case]
                    self.assertEqual(t.failed_stage, expected_stage)

                    links = [e for e in events if e["call"] == "readlink"]
                    for link_ev in links:
                        prev_ev = events[int(link_ev["index"]) - 1]  # type: ignore[arg-type]
                        self.assertEqual(prev_ev["call"], "lstat")
                        self.assertEqual(prev_ev["path"], link_ev["path"])
                        self.assertTrue(
                            stat.S_ISLNK(prev_ev["stat"]["raw_mode"])  # type: ignore[index]
                        )

                    if case == "literal_suffix":
                        self.assertEqual(len(links), 1)
                        self.assertEqual(
                            links[0]["path"], str(mutation_path)
                        )
                        self.assertEqual(links[0]["target"], "suffix/")
                        self.assertIs(links[0]["returned"], True)
                        self.assertEqual(rejected.readlink_target, "suffix/")
                        self.assertEqual(
                            t.failed_component_readlink_target, "suffix/"
                        )
                    if case == "readlink_eio":
                        self.assertEqual(len(links), 1)
                        self.assertIs(links[0]["returned"], False)
                        self.assertIsNone(rejected.readlink_target)
                        self.assertIsNone(t.failed_component_readlink_target)
                        self.assertIs(caught_helpers[0].__cause__, injected)
                        self.assertIs(
                            profile_mod._select_original_cause_exception(err),
                            injected,
                        )
                    if repeated:
                        previous = [
                            x
                            for x in t.component_observations[:-1]
                            if x.path == str(mutation_path)
                        ]
                        self.assertEqual(len(previous), 1)
                        self.assertNotEqual(
                            previous[0].lstat.ino, rejected.lstat.ino
                        )
                        self.assertEqual(
                            t.prior_component_lstat, previous[0].lstat
                        )
                        if case.startswith("repeated_link"):
                            self.assertEqual(len(links), 2)
                            self.assertEqual(
                                [e["target"] for e in links],
                                [
                                    "d",
                                    "e"
                                    if case == "repeated_link_target"
                                    else "d",
                                ],
                            )
                            self.assertEqual(previous[0].readlink_target, "d")
                            assert t.prior_symlink_edge is not None
                            self.assertEqual(t.prior_symlink_edge.target, "d")
                            self.assertEqual(
                                rejected.readlink_target, links[-1]["target"]
                            )
                            self.assertEqual(
                                next(
                                    x
                                    for x in t.accepted_symlinks
                                    if x.path == str(mutation_path)
                                ),
                                t.prior_symlink_edge,
                            )

                    accepted = t.component_observations[:-1]
                    expected_dirs = {
                        c.path: c
                        for c in accepted
                        if c.lstat.kind == "directory"
                    }
                    expected_links = {
                        c.path: c for c in accepted if c.lstat.is_symlink
                    }
                    self.assertEqual(
                        {x.path for x in t.accepted_directories},
                        set(expected_dirs),
                    )
                    self.assertEqual(
                        {x.path for x in t.accepted_symlinks},
                        set(expected_links),
                    )
                    self.assertEqual(
                        {x.path for x in t.accepted_symlink_identities},
                        set(expected_links),
                    )
                    self.assertEqual(post.final_symlinks, t.accepted_symlinks)
                    self.assertEqual(
                        post.final_symlink_identities,
                        t.accepted_symlink_identities,
                    )
                    self.assertEqual(
                        post.final_traversed_directories,
                        t.accepted_directories,
                    )

                    if case != "readlink_eio":
                        helper = caught_helpers[0]
                        self.assertIs(type(helper), ValueError)
                        self.assertIsNone(helper.__cause__)
                        expected_message = {
                            "terminal_directory": "Target is not a regular file",
                            "literal_suffix": "Regular-file target path must not end with a directory suffix",
                            "repeated_link_target": "Symlink target changed during traversal",
                            "repeated_link_inode": "Symlink identity changed during traversal",
                            "repeated_directory": "Directory identity changed during traversal",
                        }[case]
                        self.assertIn(expected_message, str(helper))
                        self.assertIs(
                            profile_mod._select_original_cause_exception(err),
                            helper,
                        )

                    selected_cause = (
                        injected if case == "readlink_eio" else caught_helpers[0]
                    )
                    with ExitStack() as stack:
                        for fn_name in (
                            "stat",
                            "lstat",
                            "fstat",
                            "open",
                            "readlink",
                        ):
                            stack.enter_context(
                                mock.patch(
                                    f"refmac_diagnostic_profile.os.{fn_name}",
                                    side_effect=AssertionError(
                                        "projection filesystem access forbidden"
                                    ),
                                )
                            )
                        contextual = profile_mod._build_partial_file_observation(
                            ob, errors=("owned contextual marker",)
                        )
                        self.assertIsNot(contextual, ob)
                        self.assertIn(
                            "owned contextual marker", contextual.errors
                        )
                        self.assertIs(contextual.post_read_observation, post)
                        self.assertIs(
                            contextual.final_traversal_observation, t
                        )
                        public = ProfileValidationError(
                            "owned projection",
                            failed_check="owned_traversal_probe",
                            manifest_identity=contextual,
                            files={"owned_file": contextual},
                            cause_exception=err,
                        )
                        projection = public.to_provenance()
                        self.assertFalse(projection["profile_files_verified"])
                        self.assertIsNone(projection["selected_executable"])
                        self.assertIs(public.cause_exception, selected_cause)
                        self.assertEqual(
                            projection["error"]["type"],
                            type(selected_cause).__name__,
                        )
                        self.assertEqual(
                            projection["error"]["message"],
                            str(selected_cause),
                        )
                        self.assertEqual(
                            projection["error"]["errno"],
                            errno.EIO if case == "readlink_eio" else None,
                        )
                        self.assertEqual(
                            projection["error"]["wrapper_message"],
                            "owned projection",
                        )
                        post_dict = post.to_dict()
                        for owner in (
                            projection["manifest"],
                            projection["files"]["owned_file"],
                        ):
                            self.assertEqual(
                                owner["post_read_observation"], post_dict
                            )
                            self.assertEqual(
                                owner["final_traversal_observation"],
                                post_dict["final_traversal_observation"],
                            )
                        fresh = public.to_provenance()
                        fresh["files"]["owned_file"]["post_read_observation"][
                            "final_traversal_observation"
                        ]["component_observations"][0]["lstat"]["ino"] = -1
                        fresh["manifest"]["post_read_observation"][
                            "final_traversal_observation"
                        ]["component_observations"][-1][
                            "readlink_target"
                        ] = "invented"
                        self.assertEqual(public.to_provenance(), projection)
                        detached = t.to_dict()
                        detached["component_observations"].clear()
                        self.assertEqual(
                            len(t.to_dict()["component_observations"]),
                            len(component_events),
                        )
                        with self.assertRaises(FrozenInstanceError):
                            rejected.readlink_target = "invented"  # type: ignore[misc]
                        with self.assertRaises(FrozenInstanceError):
                            rejected.lstat.ino = -1  # type: ignore[misc]
                        with self.assertRaises(TypeError):
                            t.component_observations[0] = rejected  # type: ignore[index]
                        with self.assertRaises(FrozenInstanceError):
                            t.failed_stage = "invented"  # type: ignore[misc]

                    if case in ("terminal_directory", "literal_suffix"):
                        with self.assertRaises(ValueError) as pre_open_ctx:
                            profile_mod._stream_observe_regular_file(lexical)
                        self.assertNotIsInstance(
                            pre_open_ctx.exception, _PartialFileReadError
                        )

    def test_task1024_post_eof_traversal_preliminary_non_oserror_producer(
        self,
    ) -> None:
        real_fdopen = os.fdopen
        real_lstat = os.lstat
        real_stat = os.stat
        real_fstat = os.fstat
        real_traverse = profile_mod._traverse_path_components
        real_lookup = profile_mod._validate_kernel_regular_lookup
        payload = b"owned preliminary actual EOF\n"
        digest = _sha256_bytes(payload)

        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir).resolve()
            # 1. Preliminary lstat succeeds then non-OSError stat failure (Report 1047 / Task 1049)
            target = base_dir / "owned.bin"
            target.write_bytes(payload)
            state: dict[str, object] = {
                "eof": False,
                "traverse": False,
                "preliminary": False,
                "fd": -1,
                "bytes_read": 0,
            }
            events: list[dict[str, object]] = []
            injected = RuntimeError(
                "owned non-OSError after preliminary lstat"
            )

            def fdopen_hook(fd: int, *a, **kw):
                state["fd"] = fd
                handle = real_fdopen(fd, *a, **kw)
                orig_read = handle.read

                def read_hook(n: int = -1) -> bytes:
                    b = orig_read(n)
                    state["bytes_read"] = int(state["bytes_read"]) + len(b)  # type: ignore[arg-type]
                    if not b:
                        state["eof"] = True
                    return b

                handle.read = read_hook  # type: ignore[method-assign]
                return handle

            def trav_hook(path_str: str):
                state["traverse"] = True
                try:
                    return real_traverse(path_str)
                finally:
                    state["traverse"] = False

            def look_hook(path_str: str):
                state["preliminary"] = state["traverse"]
                try:
                    return real_lookup(path_str)
                finally:
                    state["preliminary"] = False

            def lstat_hook(path, *a, **kw):
                st = real_lstat(path, *a, **kw)
                if state["eof"] and state["preliminary"]:
                    events.append(
                        {
                            "call": "lstat",
                            "path": str(path),
                            "dev": int(st.st_dev),
                            "ino": int(st.st_ino),
                            "mode": int(stat.S_IMODE(st.st_mode)),
                            "uid": int(st.st_uid),
                            "gid": int(st.st_gid),
                            "size_bytes": int(st.st_size),
                            "file_type": int(stat.S_IFMT(st.st_mode)),
                            "raw_mode": int(st.st_mode),
                        }
                    )
                return st

            def stat_hook(path, *a, **kw):
                if state["eof"] and state["preliminary"]:
                    events.append(
                        {"call": "stat", "path": str(path), "returned": False}
                    )
                    raise injected
                return real_stat(path, *a, **kw)

            with (
                mock.patch(
                    "refmac_diagnostic_profile.os.fdopen",
                    side_effect=fdopen_hook,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.lstat",
                    side_effect=lstat_hook,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.stat",
                    side_effect=stat_hook,
                ),
                mock.patch.object(
                    profile_mod,
                    "_traverse_path_components",
                    side_effect=trav_hook,
                ),
                mock.patch.object(
                    profile_mod,
                    "_validate_kernel_regular_lookup",
                    side_effect=look_hook,
                ),
            ):
                with self.assertRaises(_PartialFileReadError) as ctx:
                    profile_mod._stream_observe_regular_file(
                        str(target), retain_bytes=True, chunk_size=7
                    )

            self.assertTrue(state["eof"])
            self.assertEqual(state["bytes_read"], len(payload))
            fd_val = int(state["fd"])  # type: ignore[arg-type]
            self.assertGreaterEqual(fd_val, 0)
            with self.assertRaises(OSError) as ebadf_ctx:
                real_fstat(fd_val)
            self.assertEqual(ebadf_ctx.exception.errno, errno.EBADF)
            self.assertEqual([e["call"] for e in events], ["lstat", "stat"])
            self.assertTrue(all(e["path"] == str(target) for e in events))

            err = ctx.exception
            self.assertIs(err.__cause__, injected)
            ob = err.observation
            self.assertEqual(ob.failure_phase, "final_path_traversal")
            self.assertTrue(ob.observed_eof)
            self.assertEqual(ob.observed_eof_sha256, digest)
            self.assertIsNone(ob.sha256)
            self.assertFalse(ob.verified)
            self.assertFalse(ob.read_complete)
            t = ob.final_traversal_observation
            assert t is not None
            self.assertIsNone(t.preliminary_lexical_stat)
            self.assertEqual(t.failed_stage, "preliminary_kernel_stat")
            assert t.preliminary_lexical_lstat is not None
            expected_lstat = {
                k: v for k, v in events[0].items() if k not in ("call", "path")
            }
            self.assertEqual(
                {
                    k: getattr(t.preliminary_lexical_lstat, k)
                    for k in expected_lstat
                },
                expected_lstat,
            )

            # 2. Opaque traversal helper failure without _partial_traversal_observation stays None
            opaque_target = base_dir / "opaque_trav.bin"
            opaque_target.write_bytes(payload)
            opaque_state = {"eof": False, "fd": -1}
            opaque_exc = ValueError("owned opaque post-EOF traversal refusal")

            def fdopen_opaque(fd: int, *a, **kw):
                opaque_state["fd"] = fd
                handle = real_fdopen(fd, *a, **kw)
                orig_read = handle.read

                def read_opaque(n: int = -1) -> bytes:
                    b = orig_read(n)
                    if not b:
                        opaque_state["eof"] = True
                    return b

                handle.read = read_opaque  # type: ignore[method-assign]
                return handle

            def trav_opaque(path_str: str):
                if opaque_state["eof"]:
                    raise opaque_exc
                return real_traverse(path_str)

            with (
                mock.patch(
                    "refmac_diagnostic_profile.os.fdopen",
                    side_effect=fdopen_opaque,
                ),
                mock.patch.object(
                    profile_mod,
                    "_traverse_path_components",
                    side_effect=trav_opaque,
                ),
            ):
                with self.assertRaises(_PartialFileReadError) as op_ctx:
                    profile_mod._stream_observe_regular_file(
                        str(opaque_target), retain_bytes=True, chunk_size=7
                    )
            self.assertTrue(opaque_state["eof"])
            with self.assertRaises(OSError) as op_ebadf:
                real_fstat(int(opaque_state["fd"]))
            self.assertEqual(op_ebadf.exception.errno, errno.EBADF)
            op_err = op_ctx.exception
            self.assertIs(op_err.__cause__, opaque_exc)
            self.assertEqual(
                op_err.observation.failure_phase, "final_path_traversal"
            )
            self.assertIsNone(op_err.observation.final_traversal_observation)
            self.assertIsNone(op_err.observation.final_traversal_failed_stage)

    def test_task1024_post_eof_traversal_entrypoint_admission_and_recheck(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fx = _build_synthetic_outer_profile_fixture(Path(tmpdir))
            root = fx["root"]
            assert isinstance(root, Path)
            support_dir = root / "support"
            installed_record = fx["installed_record"]
            assert isinstance(installed_record, dict)
            ccp4_env = fx["ccp4_env"]
            assert isinstance(ccp4_env, dict)
            ev_root = fx["evidence_root"]
            assert isinstance(ev_root, Path)
            alias_symlink = fx["alias_symlink"]
            assert isinstance(alias_symlink, Path)
            manifest_path = fx["manifest_path"]
            assert isinstance(manifest_path, Path)
            profile = fx["profile"]
            assert isinstance(profile, RefmacDiagnosticProfile)
            base_payload = fx["manifest_payload"]
            assert isinstance(base_payload, dict)

            validated = validate_profile(
                profile, installed_record, ccp4_env, ev_root
            )
            state = validated._outer_state
            assert state is not None

            direct_fid = base_payload["roles"]["collection_interpreter"][0]  # type: ignore[index]
            alias_fid = next(
                fid
                for fid, row in base_payload["files"].items()  # type: ignore[union-attr]
                if row["path"] == str(alias_symlink)
            )
            dotdot_path_str = str(
                support_dir / "bin" / ".." / "collection-python"
            )
            dotdot_fid = next(
                fid
                for fid, row in base_payload["files"].items()  # type: ignore[union-attr]
                if row["path"] == dotdot_path_str
            )
            alias_resolved = str(alias_symlink.resolve(strict=True))
            alias_bytes = Path(alias_resolved).read_bytes()
            alias_sha = _sha256_bytes(alias_bytes)

            real_open = os.open
            real_fdopen = os.fdopen
            real_fstat = os.fstat
            real_lstat = os.lstat
            real_readlink = os.readlink
            real_traverse = profile_mod._traverse_path_components
            real_lookup = profile_mod._validate_kernel_regular_lookup
            real_obs_pin = profile_mod._observe_regular_file_pin
            real_stream_obs = profile_mod._stream_observe_regular_file

            # 1. Declared-file owner (alias_fid) post-EOF traversal symlink_readlink EIO
            # across validate_profile, _reobserve_outer_profile_state, and recheck_profile
            injected_exc = OSError(
                errno.EIO,
                "synthetic #1168 declared-file post-EOF traversal readlink EIO",
            )
            run_state: dict[str, object] = {
                "active_lexical": None,
                "owned_fd": -1,
                "captured_fd": -1,
                "observed_eof_on_owned_fd": False,
                "in_traverse": False,
                "in_preliminary": False,
                "injected": False,
            }

            def reset_run_state() -> None:
                run_state["active_lexical"] = None
                run_state["owned_fd"] = -1
                run_state["captured_fd"] = -1
                run_state["observed_eof_on_owned_fd"] = False
                run_state["in_traverse"] = False
                run_state["in_preliminary"] = False
                run_state["injected"] = False

            def observe_pin_alias(path, *a, **kw):
                prev_lex = run_state["active_lexical"]
                path_str = str(path)
                run_state["active_lexical"] = path_str
                if path_str == str(alias_symlink) and not run_state["injected"]:
                    run_state["owned_fd"] = -1
                    run_state["observed_eof_on_owned_fd"] = False
                try:
                    return real_obs_pin(path, *a, **kw)
                finally:
                    if path_str == str(alias_symlink):
                        run_state["owned_fd"] = -1
                        run_state["observed_eof_on_owned_fd"] = False
                    run_state["active_lexical"] = prev_lex

            def open_alias(path, flags, *a, **kw):
                fd = real_open(path, flags, *a, **kw)
                if (
                    run_state["active_lexical"] == str(alias_symlink)
                    and not run_state["injected"]
                    and str(path) == alias_resolved
                ):
                    run_state["owned_fd"] = fd
                    run_state["captured_fd"] = fd
                    run_state["observed_eof_on_owned_fd"] = False
                return fd

            def fdopen_alias(fd: int, mode: str = "rb", *a, **kw):
                handle = real_fdopen(fd, mode, *a, **kw)
                if (
                    run_state["active_lexical"] == str(alias_symlink)
                    and fd == run_state["owned_fd"]
                ):
                    orig_read = handle.read

                    def read_track_eof(n: int = -1) -> bytes:
                        chunk = orig_read(n)
                        if chunk == b"":
                            run_state["observed_eof_on_owned_fd"] = True
                        return chunk

                    handle.read = read_track_eof  # type: ignore[method-assign]
                return handle

            def traverse_alias(path_str: str):
                prev = run_state["in_traverse"]
                run_state["in_traverse"] = True
                try:
                    return real_traverse(path_str)
                finally:
                    run_state["in_traverse"] = prev

            def lookup_alias(path_str: str):
                prev = run_state["in_preliminary"]
                run_state["in_preliminary"] = run_state["in_traverse"]
                try:
                    return real_lookup(path_str)
                finally:
                    run_state["in_preliminary"] = prev

            def readlink_alias(path, *a, **kw):
                if (
                    run_state["active_lexical"] == str(alias_symlink)
                    and run_state["observed_eof_on_owned_fd"]
                    and run_state["in_traverse"]
                    and not run_state["in_preliminary"]
                    and not run_state["injected"]
                    and str(path) == str(alias_symlink)
                ):
                    run_state["injected"] = True
                    raise injected_exc
                return real_readlink(path, *a, **kw)

            reset_run_state()
            with (
                mock.patch(
                    "refmac_diagnostic_profile._observe_regular_file_pin",
                    side_effect=observe_pin_alias,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.open",
                    side_effect=open_alias,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.fdopen",
                    side_effect=fdopen_alias,
                ),
                mock.patch.object(
                    profile_mod,
                    "_traverse_path_components",
                    side_effect=traverse_alias,
                ),
                mock.patch.object(
                    profile_mod,
                    "_validate_kernel_regular_lookup",
                    side_effect=lookup_alias,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.readlink",
                    side_effect=readlink_alias,
                ),
            ):
                with self.assertRaises(ProfileValidationError) as val_ctx:
                    validate_profile(
                        profile, installed_record, ccp4_env, ev_root
                    )
            self.assertTrue(run_state["injected"])
            with self.assertRaises(OSError) as val_ebadf:
                real_fstat(int(run_state["captured_fd"]))  # type: ignore[arg-type]
            self.assertEqual(val_ebadf.exception.errno, errno.EBADF)

            val_err = val_ctx.exception
            self.assertEqual(
                val_err.failed_check, "outer_profile_files_and_roots"
            )
            self.assertIs(val_err.cause_exception, injected_exc)
            self.assertIsInstance(val_err.files[direct_fid], FileObservation)
            self.assertTrue(val_err.files[direct_fid].verified)
            self.assertIsInstance(val_err.files[dotdot_fid], FileObservation)
            self.assertTrue(val_err.files[dotdot_fid].verified)

            pobs = val_err.files[alias_fid]
            assert isinstance(pobs, PartialFileReadObservation)
            self.assertTrue(pobs.observed_eof)
            self.assertEqual(pobs.observed_eof_sha256, alias_sha)
            self.assertEqual(pobs.failure_phase, "final_path_traversal")
            trav_obs = pobs.final_traversal_observation
            assert trav_obs is not None
            self.assertEqual(trav_obs.failed_stage, "symlink_readlink")
            self.assertEqual(trav_obs.lexical_path, str(alias_symlink))
            self.assertEqual(
                trav_obs.failed_component_path, str(alias_symlink)
            )
            self.assertIs(trav_obs.failed_component_is_leaf, True)
            assert trav_obs.failed_component_lstat is not None
            self.assertTrue(trav_obs.failed_component_lstat.is_symlink)
            self.assertIsNone(trav_obs.failed_component_readlink_target)
            assert trav_obs.rejected_component is not None
            self.assertEqual(
                trav_obs.rejected_component.path, str(alias_symlink)
            )
            self.assertFalse(trav_obs.rejected_component.accepted)

            prov = val_err.to_provenance()
            self.assertEqual(
                prov["files"][alias_fid]["final_traversal_observation"][
                    "failed_stage"
                ],
                "symlink_readlink",
            )
            self.assertEqual(
                prov["files"][alias_fid]["post_read_observation"][
                    "final_traversal_observation"
                ]["failed_component_path"],
                str(alias_symlink),
            )

            reset_run_state()
            with (
                mock.patch(
                    "refmac_diagnostic_profile._observe_regular_file_pin",
                    side_effect=observe_pin_alias,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.open",
                    side_effect=open_alias,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.fdopen",
                    side_effect=fdopen_alias,
                ),
                mock.patch.object(
                    profile_mod,
                    "_traverse_path_components",
                    side_effect=traverse_alias,
                ),
                mock.patch.object(
                    profile_mod,
                    "_validate_kernel_regular_lookup",
                    side_effect=lookup_alias,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.readlink",
                    side_effect=readlink_alias,
                ),
            ):
                priv_recheck = _reobserve_outer_profile_state(state)
            self.assertTrue(run_state["injected"])
            with self.assertRaises(OSError) as priv_ebadf:
                real_fstat(int(run_state["captured_fd"]))  # type: ignore[arg-type]
            self.assertEqual(priv_ebadf.exception.errno, errno.EBADF)
            self.assertFalse(priv_recheck.verified)
            self.assertNotIn(direct_fid, priv_recheck.partial_files)
            self.assertNotIn(dotdot_fid, priv_recheck.partial_files)
            self.assertIn(alias_fid, priv_recheck.partial_files)
            self.assertIs(priv_recheck.file_causes[alias_fid], injected_exc)
            priv_trav = priv_recheck.partial_files[
                alias_fid
            ].final_traversal_observation
            assert priv_trav is not None
            self.assertEqual(priv_trav.failed_stage, "symlink_readlink")

            reset_run_state()
            pub_causes: list[Exception | None] = []
            with (
                mock.patch(
                    "refmac_diagnostic_profile._observe_regular_file_pin",
                    side_effect=observe_pin_alias,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.open",
                    side_effect=open_alias,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.fdopen",
                    side_effect=fdopen_alias,
                ),
                mock.patch.object(
                    profile_mod,
                    "_traverse_path_components",
                    side_effect=traverse_alias,
                ),
                mock.patch.object(
                    profile_mod,
                    "_validate_kernel_regular_lookup",
                    side_effect=lookup_alias,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.readlink",
                    side_effect=readlink_alias,
                ),
            ):
                pub_report = recheck_profile(
                    validated, mutation_causes_out=pub_causes
                )
            self.assertTrue(run_state["injected"])
            with self.assertRaises(OSError) as pub_ebadf:
                real_fstat(int(run_state["captured_fd"]))  # type: ignore[arg-type]
            self.assertEqual(pub_ebadf.exception.errno, errno.EBADF)
            self.assertFalse(pub_report["verified"])
            self.assertTrue(
                pub_report["files"][direct_fid]["matches_baseline"]
            )
            self.assertEqual(pub_report["files"][direct_fid]["errors"], [])
            self.assertTrue(
                pub_report["files"][dotdot_fid]["matches_baseline"]
            )
            self.assertEqual(pub_report["files"][dotdot_fid]["errors"], [])
            pub_frow = pub_report["files"][alias_fid]
            self.assertFalse(pub_frow["matches_baseline"])
            self.assertEqual(
                pub_frow["observed"]["final_traversal_observation"][
                    "failed_stage"
                ],
                "symlink_readlink",
            )
            self.assertEqual(
                pub_frow["observed"]["final_traversal_observation"][
                    "failed_component_path"
                ],
                str(alias_symlink),
            )
            self.assertEqual(len(pub_causes), 1)
            self.assertIs(pub_causes[0], injected_exc)

            # 2. Manifest owner (manifest_pin) post-EOF traversal leaf_component_directory
            manifest_resolved = str(manifest_path.resolve(strict=True))
            manifest_bytes = manifest_path.read_bytes()
            manifest_sha = _sha256_bytes(manifest_bytes)
            park_manifest = manifest_path.with_name(
                "diagnostic-profile.trav-parked.json"
            )
            m_state: dict[str, object] = {
                "active_lexical": None,
                "owned_fd": -1,
                "captured_fd": -1,
                "observed_eof_on_owned_fd": False,
                "in_traverse": False,
                "in_preliminary": False,
                "component_hits": 0,
                "mutated": False,
            }

            def stream_obs_m(path, *a, **kw):
                prev_lex = m_state["active_lexical"]
                path_str = str(path)
                m_state["active_lexical"] = path_str
                try:
                    return real_stream_obs(path, *a, **kw)
                finally:
                    if path_str == str(manifest_path):
                        m_state["owned_fd"] = -1
                        m_state["observed_eof_on_owned_fd"] = False
                        m_state["component_hits"] = 0
                    m_state["active_lexical"] = prev_lex

            def open_m(path, flags, *a, **kw):
                fd = real_open(path, flags, *a, **kw)
                if (
                    m_state["active_lexical"] == str(manifest_path)
                    and not m_state["mutated"]
                    and str(path) == manifest_resolved
                ):
                    m_state["owned_fd"] = fd
                    m_state["captured_fd"] = fd
                    m_state["observed_eof_on_owned_fd"] = False
                return fd

            def fdopen_m(fd: int, mode: str = "rb", *a, **kw):
                handle = real_fdopen(fd, mode, *a, **kw)
                if (
                    m_state["active_lexical"] == str(manifest_path)
                    and fd == m_state["owned_fd"]
                ):
                    orig_read = handle.read

                    def read_track_m_eof(n: int = -1) -> bytes:
                        chunk = orig_read(n)
                        if chunk == b"":
                            m_state["observed_eof_on_owned_fd"] = True
                        return chunk

                    handle.read = read_track_m_eof  # type: ignore[method-assign]
                return handle

            def traverse_m(path_str: str):
                prev = m_state["in_traverse"]
                m_state["in_traverse"] = True
                try:
                    return real_traverse(path_str)
                finally:
                    m_state["in_traverse"] = prev

            def lookup_m(path_str: str):
                prev = m_state["in_preliminary"]
                m_state["in_preliminary"] = m_state["in_traverse"]
                try:
                    return real_lookup(path_str)
                finally:
                    m_state["in_preliminary"] = prev

            def lstat_m(path, *a, **kw):
                if (
                    m_state["active_lexical"] == str(manifest_path)
                    and m_state["observed_eof_on_owned_fd"]
                    and m_state["in_traverse"]
                    and not m_state["in_preliminary"]
                    and str(path) == manifest_resolved
                ):
                    m_state["component_hits"] = (
                        int(m_state["component_hits"]) + 1  # type: ignore[arg-type]
                    )
                    if m_state["component_hits"] == 1 and not m_state["mutated"]:
                        manifest_path.rename(park_manifest)
                        manifest_path.mkdir()
                        m_state["mutated"] = True
                return real_lstat(path, *a, **kw)

            with (
                mock.patch(
                    "refmac_diagnostic_profile._stream_observe_regular_file",
                    side_effect=stream_obs_m,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.open", side_effect=open_m
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.fdopen", side_effect=fdopen_m
                ),
                mock.patch.object(
                    profile_mod,
                    "_traverse_path_components",
                    side_effect=traverse_m,
                ),
                mock.patch.object(
                    profile_mod,
                    "_validate_kernel_regular_lookup",
                    side_effect=lookup_m,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.lstat", side_effect=lstat_m
                ),
                mock.patch(
                    "refmac_diagnostic_profile._parse_verified_json_bytes",
                    side_effect=AssertionError("must not parse JSON"),
                ) as mocked_parse,
                mock.patch(
                    "refmac_diagnostic_profile._validate_outer_manifest_shape",
                    side_effect=AssertionError("must not validate shape"),
                ) as mocked_shape,
                mock.patch(
                    "refmac_diagnostic_profile._observe_controlled_root",
                    side_effect=AssertionError("must not inspect roots"),
                ) as mocked_root,
            ):
                with self.assertRaises(ProfileValidationError) as m_ctx:
                    validate_profile(
                        profile, installed_record, ccp4_env, ev_root
                    )
                mocked_parse.assert_not_called()
                mocked_shape.assert_not_called()
                mocked_root.assert_not_called()

            self.assertTrue(m_state["mutated"])
            with self.assertRaises(OSError) as m_ebadf:
                real_fstat(int(m_state["captured_fd"]))  # type: ignore[arg-type]
            self.assertEqual(m_ebadf.exception.errno, errno.EBADF)
            m_err = m_ctx.exception
            self.assertEqual(m_err.failed_check, "manifest_pin")
            assert isinstance(
                m_err.manifest_identity, PartialFileReadObservation
            )
            self.assertTrue(m_err.manifest_identity.observed_eof)
            self.assertEqual(
                m_err.manifest_identity.observed_eof_sha256, manifest_sha
            )
            self.assertEqual(
                m_err.manifest_identity.failure_phase,
                "final_path_traversal",
            )
            m_trav = m_err.manifest_identity.final_traversal_observation
            assert m_trav is not None
            self.assertEqual(m_trav.failed_stage, "leaf_component_directory")
            self.assertEqual(m_trav.failed_component_path, str(manifest_path))
            self.assertIs(m_trav.failed_component_is_leaf, True)
            assert m_trav.failed_component_lstat is not None
            self.assertTrue(m_trav.failed_component_lstat.is_directory)

    def test_task1024_traversal_carrier_invariants(self) -> None:
        from dataclasses import replace

        ObservedStatSnapshot = profile_mod.ObservedStatSnapshot
        TraversalComponentObservation = (
            profile_mod.TraversalComponentObservation
        )
        FinalPathTraversalObservation = (
            profile_mod.FinalPathTraversalObservation
        )
        _ObservedDirectoryIdentity = profile_mod._ObservedDirectoryIdentity

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir).resolve()
            root_snap = ObservedStatSnapshot.from_stat_result(os.lstat("/"))
            directory = _ObservedDirectoryIdentity(
                path="/",
                resolved_path="/",
                dev=root_snap.dev,
                ino=root_snap.ino,
                mode=root_snap.mode,
                uid=root_snap.uid,
                gid=root_snap.gid,
            )
            p = base / "owned-link"
            p.symlink_to("owned-target")
            s0 = ObservedStatSnapshot.from_stat_result(os.lstat(p))
            p.rename(base / "owned-original")
            p.symlink_to("owned-target")
            s1 = ObservedStatSnapshot.from_stat_result(os.lstat(p))
            self.assertNotEqual(s0.ino, s1.ino)

            root_component = TraversalComponentObservation(
                path="/",
                lstat=root_snap,
                is_root=True,
                directory_identity=directory,
            )
            leaf = TraversalComponentObservation(
                path="/link",
                lstat=s0,
                is_leaf=True,
                accepted=False,
            )
            prior = TraversalComponentObservation(
                path="/link",
                lstat=s0,
                is_leaf=False,
                readlink_target="d",
            )
            rejected = TraversalComponentObservation(
                path="/link",
                lstat=s1,
                is_leaf=False,
                readlink_target="d",
                accepted=False,
            )
            unknown_kwargs: dict[str, object] = {
                "failed_stage": "symlink_readlink",
                "lexical_path": "/link",
                "root_lstat": root_snap,
                "accepted_directories": (directory,),
                "failed_component_path": "/link",
                "failed_component_lstat": s0,
                "symlink_expansions_count": 1,
            }
            consistent_kwargs: dict[str, object] = {
                "failed_stage": "symlink_identity_changed",
                "lexical_path": "/link/../link/file",
                "root_lstat": root_snap,
                "accepted_directories": (directory,),
                "accepted_symlinks": (prior.symlink_edge,),
                "accepted_symlink_identities": (prior.symlink_identity,),
                "component_observations": (root_component, prior, rejected),
                "failed_component_path": "/link",
                "failed_component_is_leaf": False,
                "failed_component_lstat": s1,
                "rejected_component": rejected,
                "prior_symlink_identity": prior.symlink_identity,
                "prior_symlink_edge": prior.symlink_edge,
                "symlink_expansions_count": 2,
            }
            (base / "owned-directory").mkdir()
            ds = ObservedStatSnapshot.from_stat_result(
                os.lstat(base / "owned-directory")
            )
            self.assertNotEqual(s0, ds)
            dc = TraversalComponentObservation(
                path="/link",
                lstat=ds,
                is_leaf=False,
                accepted=True,
            )
            crosskind_kwargs: dict[str, object] = {
                **consistent_kwargs,
                "lexical_path": "/link/../link/../link/file",
                "accepted_directories": (directory, dc.directory_identity),
                "component_observations": (
                    root_component,
                    prior,
                    dc,
                    rejected,
                ),
                "prior_component_lstat": ds,
                "prior_directory_identity": dc.directory_identity,
            }

            with (
                mock.patch(
                    "refmac_diagnostic_profile.os.lstat",
                    side_effect=AssertionError("constructor filesystem call"),
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.stat",
                    side_effect=AssertionError("constructor filesystem call"),
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.open",
                    side_effect=AssertionError("constructor filesystem call"),
                ),
            ):
                for bad_name, bad_kw in (
                    ("unknown_position", unknown_kwargs),
                    (
                        "prior_wrong_kind",
                        {
                            **consistent_kwargs,
                            "prior_component_lstat": root_snap,
                        },
                    ),
                    (
                        "prior_wrong_size",
                        {
                            **consistent_kwargs,
                            "prior_component_lstat": replace(
                                s0, size_bytes=s0.size_bytes + 1
                            ),
                        },
                    ),
                    (
                        "unknown_failed_stage",
                        {
                            **consistent_kwargs,
                            "failed_stage": "unknown_traversal_stage",
                        },
                    ),
                ):
                    with self.subTest(bad_traversal_carrier=bad_name):
                        with self.assertRaises(ValueError):
                            FinalPathTraversalObservation(**bad_kw)  # type: ignore[arg-type]

                supplied_leaf_obs = FinalPathTraversalObservation(
                    **{  # type: ignore[arg-type]
                        **unknown_kwargs,
                        "component_observations": (root_component, leaf),
                    }
                )
                self.assertIs(supplied_leaf_obs.failed_component_is_leaf, True)
                self.assertEqual(supplied_leaf_obs.rejected_component, leaf)

                prior_consistent_obs = FinalPathTraversalObservation(
                    **{  # type: ignore[arg-type]
                        **consistent_kwargs,
                        "prior_component_lstat": s0,
                    }
                )
                self.assertEqual(
                    prior_consistent_obs.prior_component_lstat, s0
                )
                self.assertEqual(
                    prior_consistent_obs.symlink_expansions_count, 2
                )
                self.assertEqual(
                    prior_consistent_obs.to_dict()["symlink_expansions_count"],
                    2,
                )
                with self.assertRaisesRegex(
                    ValueError,
                    r"^FinalPathTraversalObservation\.symlink_expansions_count \(0\) must match non-root symlink components in component_observations \(2\)$",
                ):
                    replace(prior_consistent_obs, symlink_expansions_count=0)
                with self.assertRaisesRegex(
                    ValueError,
                    r"^FinalPathTraversalObservation\.symlink_expansions_count \(3\) must match non-root symlink components in component_observations \(2\)$",
                ):
                    replace(prior_consistent_obs, symlink_expansions_count=3)

                rejected_root_obs = FinalPathTraversalObservation(
                    failed_stage="root_component_not_canonical_directory",
                    lexical_path="/link",
                    root_lstat=s0,
                    component_observations=(
                        TraversalComponentObservation(
                            path="/",
                            lstat=s0,
                            is_root=True,
                            is_leaf=False,
                            accepted=False,
                        ),
                    ),
                    symlink_expansions_count=0,
                )
                self.assertEqual(
                    rejected_root_obs.symlink_expansions_count, 0
                )
                opaque_no_seq_obs = FinalPathTraversalObservation(
                    **{  # type: ignore[arg-type]
                        **unknown_kwargs,
                        "failed_component_is_leaf": True,
                    }
                )
                self.assertEqual(opaque_no_seq_obs.component_observations, ())
                self.assertEqual(
                    opaque_no_seq_obs.symlink_expansions_count, 1
                )

                prior_crosskind_obs = FinalPathTraversalObservation(
                    **crosskind_kwargs  # type: ignore[arg-type]
                )
                self.assertEqual(
                    [
                        c.lstat
                        for c in prior_crosskind_obs.component_observations
                        if c.accepted and c.path == "/link"
                    ],
                    [s0, ds],
                )
                self.assertEqual(
                    prior_crosskind_obs.prior_component_lstat, ds
                )
                self.assertEqual(
                    prior_crosskind_obs.prior_symlink_identity,
                    prior.symlink_identity,
                )
                self.assertEqual(
                    prior_crosskind_obs.prior_directory_identity,
                    dc.directory_identity,
                )
                with self.assertRaisesRegex(
                    ValueError,
                    r"^FinalPathTraversalObservation\.prior_component_lstat must match the latest accepted component lstat for failed_component_path$",
                ):
                    FinalPathTraversalObservation(
                        **{  # type: ignore[arg-type]
                            **crosskind_kwargs,
                            "prior_component_lstat": s0,
                        }
                    )

    def test_task1025_controlled_root_partial_member_producer_and_entrypoints(
        self,
    ) -> None:
        from contextlib import ExitStack

        real_open = os.open
        real_fdopen = os.fdopen
        real_fstat = os.fstat
        real_lstat = os.lstat
        real_obs_root = profile_mod._observe_controlled_root
        real_obs_pin = profile_mod._observe_regular_file_pin
        real_obs_dir = profile_mod._observe_directory_identity

        # 1. Direct _observe_controlled_root + _build_root_observation + later separate _observe_regular_file_pin
        # across ordinary ("member.dat"), single-space (" "), and tab ("\t") registered member names (#1168 / #1056)
        with tempfile.TemporaryDirectory() as tmpdir:
            base_tmp = Path(tmpdir).resolve()
            for label, member_name in (
                ("ordinary", "member.dat"),
                ("space", " "),
                ("tab", "\t"),
            ):
                with self.subTest(direct_root_member=label):
                    sub_root = (base_tmp / f"direct-{label}").resolve()
                    sub_root.mkdir()
                    member_path = sub_root / member_name
                    payload = b"owned inventory stream\n"
                    member_path.write_bytes(payload)
                    sha = _sha256_bytes(payload)
                    declared = {
                        "owned_member": {
                            "path": str(member_path),
                            "sha256": sha,
                            "size_bytes": len(payload),
                        }
                    }

                    healthy_inv = _observe_controlled_root(
                        "build",
                        str(sub_root),
                        ("owned_member",),
                        declared_files=declared,
                    )
                    self.assertIs(healthy_inv.scan_complete, True)
                    self.assertIs(healthy_inv.verified, True)
                    self.assertEqual(
                        dict(healthy_inv.partial_member_observations), {}
                    )
                    self.assertEqual(
                        healthy_inv.member_pins[member_name].path,
                        str(member_path),
                    )
                    self.assertEqual(
                        healthy_inv.member_observations[member_name].path,
                        str(member_path),
                    )
                    healthy_pub = profile_mod._build_root_observation(
                        healthy_inv, None
                    )
                    self.assertEqual(
                        healthy_pub.partial_member_observations, ()
                    )
                    self.assertNotIn(
                        "partial_member_observations", healthy_pub.to_dict()
                    )
                    self.assertEqual(
                        [m.relative_path for m in healthy_pub.members],
                        [member_name],
                    )

                    d_state: dict[str, object] = {
                        "fd": -1,
                        "eof": False,
                        "injected": False,
                        "bytes_read": 0,
                    }
                    stream_hash = hashlib.sha256()
                    injected_eio = OSError(
                        errno.EIO, f"owned {label} inventory end-fstat EIO"
                    )

                    def d_fdopen(fd: int, mode: str = "rb", *a, **kw):
                        d_state["fd"] = fd
                        handle = real_fdopen(fd, mode, *a, **kw)
                        orig_read = handle.read

                        def read_track(n: int = -1) -> bytes:
                            chunk = orig_read(n)
                            d_state["bytes_read"] = (
                                int(d_state["bytes_read"]) + len(chunk)  # type: ignore[arg-type]
                            )
                            stream_hash.update(chunk)
                            if chunk == b"":
                                d_state["eof"] = True
                            return chunk

                        handle.read = read_track  # type: ignore[method-assign]
                        return handle

                    def d_fstat(fd: int, *a, **kw):
                        if (
                            d_state["eof"]
                            and fd == d_state["fd"]
                            and not d_state["injected"]
                        ):
                            d_state["injected"] = True
                            raise injected_eio
                        return real_fstat(fd, *a, **kw)

                    with (
                        mock.patch(
                            "refmac_diagnostic_profile.os.fdopen",
                            side_effect=d_fdopen,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.fstat",
                            side_effect=d_fstat,
                        ),
                        self.assertRaises(
                            profile_mod._ControlledRootObservationError
                        ) as err_ctx,
                    ):
                        _observe_controlled_root(
                            "build",
                            str(sub_root),
                            ("owned_member",),
                            declared_files=declared,
                        )

                    self.assertIs(d_state["eof"], True)
                    self.assertIs(d_state["injected"], True)
                    self.assertEqual(d_state["bytes_read"], len(payload))
                    self.assertEqual(stream_hash.hexdigest(), sha)
                    with self.assertRaises(OSError) as ebadf_ctx:
                        real_fstat(int(d_state["fd"]))  # type: ignore[arg-type]
                    self.assertEqual(ebadf_ctx.exception.errno, errno.EBADF)

                    err = err_ctx.exception
                    chain: list[BaseException] = []
                    cur: BaseException | None = err
                    while cur is not None:
                        chain.append(cur)
                        cur = cur.__cause__
                    self.assertIn(injected_eio, chain)
                    partial_errs = [
                        e
                        for e in chain
                        if type(e) is _PartialFileReadError
                    ]
                    self.assertEqual(len(partial_errs), 1)
                    orig_partial = partial_errs[0].observation

                    inv = err.root_inventory
                    assert inv is not None
                    self.assertIs(inv.scan_complete, False)
                    self.assertIs(inv.verified, False)
                    self.assertNotIn(member_name, inv.member_pins)
                    self.assertNotIn(member_name, inv.member_observations)
                    self.assertEqual(
                        list(inv.partial_member_observations.keys()),
                        [member_name],
                    )
                    partial = inv.partial_member_observations[member_name]
                    self.assertIs(partial, orig_partial)
                    self.assertEqual(partial.path, str(member_path))
                    self.assertIs(partial.observed_eof, True)
                    self.assertIsNone(partial.sha256)
                    self.assertIsNone(partial.size_bytes)
                    self.assertIs(partial.verified, False)
                    self.assertIs(partial.read_complete, False)
                    self.assertEqual(partial.streamed_size_bytes, len(payload))
                    self.assertEqual(partial.observed_stream_sha256, sha)
                    self.assertEqual(partial.observed_eof_sha256, sha)
                    self.assertEqual(partial.failure_phase, "end_fstat")
                    assert partial.post_read_observation is not None
                    self.assertIsNotNone(
                        partial.post_read_observation.initial_fstat
                    )
                    self.assertIsNone(partial.post_read_observation.end_fstat)
                    with self.assertRaisesRegex(
                        ValueError,
                        r"^PartialFileReadObservation cannot be converted to a FilePin because stream read or post-read verification did not complete$",
                    ):
                        partial.as_file_pin()

                    with ExitStack() as poison:
                        for fn_name in ("stat", "lstat", "open", "readlink"):
                            poison.enter_context(
                                mock.patch(
                                    f"refmac_diagnostic_profile.os.{fn_name}",
                                    side_effect=AssertionError(
                                        f"projection {fn_name} forbidden"
                                    ),
                                )
                            )
                        pub_obs = profile_mod._build_root_observation(
                            inv, None
                        )
                        pub_dict = pub_obs.to_dict()
                        mut_dict = pub_obs.to_dict()
                        mut_dict["partial_member_observations"][member_name][
                            "observed_eof"
                        ] = False
                        self.assertEqual(pub_obs.to_dict(), pub_dict)

                    self.assertIs(pub_obs.scan_complete, False)
                    self.assertIs(pub_obs.verified, False)
                    self.assertEqual(pub_obs.members, ())
                    self.assertEqual(
                        list(pub_obs.partial_member_observations.keys()),
                        [member_name],
                    )
                    self.assertIs(
                        pub_obs.partial_member_observations[member_name],
                        partial,
                    )
                    self.assertEqual(
                        pub_dict["partial_member_observations"][member_name],
                        partial.to_dict(),
                    )
                    self.assertEqual(
                        pub_dict["partial_member_observations"][member_name][
                            "path"
                        ],
                        str(member_path),
                    )

                    later = _observe_regular_file_pin(str(member_path))
                    self.assertIsNot(later, partial)
                    self.assertEqual(later.sha256, sha)
                    self.assertEqual(later.as_file_pin().sha256, sha)

        # 2. Full profile entrypoints (_validate_and_observe_outer_profile, validate_profile,
        # _reobserve_outer_profile_state, recheck_profile)
        with tempfile.TemporaryDirectory() as tmpdir:
            fx = _build_synthetic_outer_profile_fixture(Path(tmpdir))
            root = fx["root"]
            assert isinstance(root, Path)
            trees = fx["trees"]
            assert isinstance(trees, dict)
            installed_record = fx["installed_record"]
            assert isinstance(installed_record, dict)
            ccp4_env = fx["ccp4_env"]
            assert isinstance(ccp4_env, dict)
            ev_root = fx["evidence_root"]
            assert isinstance(ev_root, Path)
            profile = fx["profile"]
            assert isinstance(profile, RefmacDiagnosticProfile)
            base_payload = fx["manifest_payload"]
            assert isinstance(base_payload, dict)

            validated = validate_profile(
                profile, installed_record, ccp4_env, ev_root
            )
            baseline_state = validated._outer_state
            assert baseline_state is not None
            baseline_prov = validated.to_provenance()
            for rname in ("vendor", "prepared", "build"):
                self.assertEqual(
                    dict(
                        baseline_state.observed_roots[
                            rname
                        ].partial_member_observations
                    ),
                    {},
                )
                self.assertEqual(
                    validated.roots[rname].partial_member_observations, ()
                )
                self.assertNotIn(
                    "partial_member_observations",
                    baseline_prov["roots"][rname],
                )
            healthy_recheck = recheck_profile(validated)
            self.assertIs(healthy_recheck["verified"], True)
            for rname in ("vendor", "prepared", "build"):
                self.assertNotIn(
                    "partial_member_observations",
                    healthy_recheck["roots"][rname]["observed"],
                )

            patch_path = trees["prepared"] / "refmac_diagnostic_hooks.patch"
            patch_resolved = str(patch_path.resolve(strict=True))
            patch_bytes = patch_path.read_bytes()
            patch_sha = _sha256_bytes(patch_bytes)
            patch_fid = next(
                fid
                for fid, row in base_payload["files"].items()  # type: ignore[union-attr]
                if row["path"] == str(patch_path)
            )
            park_patch = patch_path.with_name("refmac_diagnostic_hooks.parked")

            # Scenario A (post-EOF namespace directory replacement on inventory read; later declared-file read succeeds)
            # and Scenario B (pre-EOF stream_read EIO on inventory read; later declared-file read succeeds)
            for mode in ("post_eof_dir_swap", "pre_eof_stream_eio"):
                with self.subTest(entrypoint_inventory_only_mode=mode):
                    pre_eof_exc = OSError(
                        errno.EIO,
                        "owned pre-EOF prepared inventory stream_read EIO",
                    )
                    m_state: dict[str, object] = {
                        "in_prepared_root": False,
                        "active_lexical": None,
                        "inv_owned_fd": -1,
                        "inv_captured_fd": -1,
                        "file_reads": 0,
                        "inv_eof": False,
                        "inv_bytes": 0,
                        "mutated": False,
                    }

                    def reset_m_state() -> None:
                        if park_patch.exists():
                            if patch_path.is_dir():
                                patch_path.rmdir()
                            park_patch.rename(patch_path)
                        m_state["in_prepared_root"] = False
                        m_state["active_lexical"] = None
                        m_state["inv_owned_fd"] = -1
                        m_state["inv_captured_fd"] = -1
                        m_state["file_reads"] = 0
                        m_state["inv_eof"] = False
                        m_state["inv_bytes"] = 0
                        m_state["mutated"] = False

                    def obs_root_hook(name: str, *a, **kw):
                        prev = m_state["in_prepared_root"]
                        if name == "prepared":
                            m_state["in_prepared_root"] = True
                        try:
                            return real_obs_root(name, *a, **kw)
                        finally:
                            if name == "prepared":
                                m_state["in_prepared_root"] = prev
                                if park_patch.exists():
                                    if patch_path.is_dir():
                                        patch_path.rmdir()
                                    park_patch.rename(patch_path)

                    def obs_pin_hook(path, *a, **kw):
                        prev_lex = m_state["active_lexical"]
                        p_str = str(path)
                        m_state["active_lexical"] = p_str
                        if (
                            p_str == str(patch_path)
                            and not m_state["in_prepared_root"]
                        ):
                            m_state["file_reads"] = (
                                int(m_state["file_reads"]) + 1  # type: ignore[arg-type]
                            )
                        try:
                            return real_obs_pin(path, *a, **kw)
                        finally:
                            if p_str == str(patch_path):
                                m_state["inv_owned_fd"] = -1
                                m_state["inv_eof"] = False
                            m_state["active_lexical"] = prev_lex

                    def open_hook(path, flags, *a, **kw):
                        fd = real_open(path, flags, *a, **kw)
                        if (
                            m_state["in_prepared_root"]
                            and m_state["active_lexical"] == str(patch_path)
                            and str(path) == patch_resolved
                            and not m_state["mutated"]
                        ):
                            m_state["inv_owned_fd"] = fd
                            m_state["inv_captured_fd"] = fd
                            m_state["inv_eof"] = False
                            m_state["inv_bytes"] = 0
                        return fd

                    def fdopen_hook(fd: int, mode_str: str = "rb", *a, **kw):
                        handle = real_fdopen(fd, mode_str, *a, **kw)
                        if (
                            m_state["in_prepared_root"]
                            and fd == m_state["inv_owned_fd"]
                        ):
                            orig_read = handle.read

                            def read_hook(n: int = -1) -> bytes:
                                if (
                                    mode == "pre_eof_stream_eio"
                                    and int(m_state["inv_bytes"]) > 0  # type: ignore[arg-type]
                                    and not m_state["mutated"]
                                ):
                                    m_state["mutated"] = True
                                    raise pre_eof_exc
                                chunk = orig_read(
                                    5 if mode == "pre_eof_stream_eio" else n
                                )
                                m_state["inv_bytes"] = (
                                    int(m_state["inv_bytes"]) + len(chunk)  # type: ignore[arg-type]
                                )
                                if chunk == b"":
                                    m_state["inv_eof"] = True
                                return chunk

                            handle.read = read_hook  # type: ignore[method-assign]
                        return handle

                    def lstat_hook(path, *a, **kw):
                        if (
                            mode == "post_eof_dir_swap"
                            and m_state["in_prepared_root"]
                            and m_state["inv_eof"]
                            and not m_state["mutated"]
                            and str(path) == str(patch_path)
                        ):
                            patch_path.rename(park_patch)
                            patch_path.mkdir()
                            m_state["mutated"] = True
                        return real_lstat(path, *a, **kw)

                    def check_partial_member(
                        p_obs: PartialFileReadObservation,
                    ) -> None:
                        self.assertEqual(p_obs.path, str(patch_path))
                        self.assertIsNone(p_obs.sha256)
                        self.assertIsNone(p_obs.size_bytes)
                        self.assertIs(p_obs.read_complete, False)
                        self.assertIs(p_obs.verified, False)
                        with self.assertRaisesRegex(
                            ValueError,
                            r"^PartialFileReadObservation cannot be converted to a FilePin because stream read or post-read verification did not complete$",
                        ):
                            p_obs.as_file_pin()
                        assert p_obs.post_read_observation is not None
                        self.assertIsNotNone(
                            p_obs.post_read_observation.initial_fstat
                        )
                        if mode == "post_eof_dir_swap":
                            self.assertIs(p_obs.observed_eof, True)
                            self.assertEqual(
                                p_obs.streamed_size_bytes, len(patch_bytes)
                            )
                            self.assertEqual(
                                p_obs.observed_stream_sha256, patch_sha
                            )
                            self.assertEqual(
                                p_obs.observed_eof_sha256, patch_sha
                            )
                            self.assertEqual(
                                p_obs.failure_phase,
                                "final_kernel_lookup",
                            )
                            assert (
                                p_obs.post_read_observation.end_fstat
                                is not None
                            )
                            self.assertIs(
                                p_obs.post_read_observation.end_fstat.is_regular,
                                True,
                            )
                            assert p_obs.final_lexical_lstat is not None
                            assert p_obs.final_lexical_stat is not None
                            self.assertIs(
                                p_obs.final_lexical_lstat.is_directory, True
                            )
                            self.assertIs(
                                p_obs.final_lexical_stat.is_directory, True
                            )
                        else:
                            self.assertIs(p_obs.observed_eof, False)
                            self.assertIsNone(p_obs.observed_eof_sha256)
                            self.assertEqual(p_obs.streamed_size_bytes, 5)
                            self.assertEqual(
                                p_obs.observed_stream_sha256,
                                _sha256_bytes(patch_bytes[:5]),
                            )
                            self.assertEqual(
                                p_obs.failure_phase, "stream_read"
                            )
                            self.assertIsNone(
                                p_obs.post_read_observation.end_fstat
                            )

                    # 2a. Private admission (_validate_and_observe_outer_profile)
                    reset_m_state()
                    with (
                        mock.patch(
                            "refmac_diagnostic_profile._observe_controlled_root",
                            side_effect=obs_root_hook,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile._observe_regular_file_pin",
                            side_effect=obs_pin_hook,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.open",
                            side_effect=open_hook,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.fdopen",
                            side_effect=fdopen_hook,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.lstat",
                            side_effect=lstat_hook,
                        ),
                        self.assertRaises(_ProfileObservationError) as priv_ctx,
                    ):
                        _validate_and_observe_outer_profile(
                            profile, evidence_root=ev_root, chunk_size=5
                        )
                    self.assertIs(m_state["mutated"], True)
                    self.assertEqual(m_state["file_reads"], 1)
                    with self.assertRaises(OSError) as ebadf_a:
                        real_fstat(int(m_state["inv_captured_fd"]))  # type: ignore[arg-type]
                    self.assertEqual(ebadf_a.exception.errno, errno.EBADF)

                    priv_partial = priv_ctx.exception.partial_observation
                    self.assertIn("vendor", priv_partial.verified_roots)
                    self.assertIn("build", priv_partial.verified_roots)
                    self.assertIn("prepared", priv_partial.incomplete_roots)
                    self.assertIn("prepared", priv_partial.failed_roots)
                    self.assertNotIn("prepared", priv_partial.verified_roots)
                    prep_inv = priv_partial.observed_roots["prepared"]
                    self.assertIs(prep_inv.scan_complete, False)
                    self.assertIs(prep_inv.verified, False)
                    self.assertIn(".hidden_prepared_cfg", prep_inv.member_pins)
                    self.assertIn(
                        ".hidden_prepared_cfg", prep_inv.member_observations
                    )
                    self.assertNotIn(
                        "refmac_diagnostic_hooks.patch", prep_inv.member_pins
                    )
                    self.assertNotIn(
                        "refmac_diagnostic_hooks.patch",
                        prep_inv.member_observations,
                    )
                    p_member = prep_inv.partial_member_observations[
                        "refmac_diagnostic_hooks.patch"
                    ]
                    check_partial_member(p_member)
                    self.assertIn(patch_fid, priv_partial.verified_files)
                    self.assertNotIn(patch_fid, priv_partial.partial_files)
                    self.assertEqual(
                        priv_partial.observed_files[patch_fid].sha256,
                        patch_sha,
                    )
                    root_rec = next(
                        r
                        for r in priv_ctx.exception.error_records
                        if r.stage == "outer_profile_files_and_roots"
                        and isinstance(r.exception, _PartialFileReadError)
                        and r.exception.observation is p_member
                    )
                    assert isinstance(
                        root_rec.exception, _PartialFileReadError
                    )
                    self.assertIs(root_rec.exception.observation, p_member)
                    self.assertIsNotNone(root_rec.exception.__cause__)
                    self.assertIs(
                        profile_mod._select_original_cause_exception(
                            root_rec.exception
                        ),
                        root_rec.exception.__cause__,
                    )
                    if mode == "pre_eof_stream_eio":
                        self.assertIs(
                            root_rec.exception.__cause__, pre_eof_exc
                        )

                    # 2b. Public admission (validate_profile)
                    reset_m_state()
                    with (
                        mock.patch(
                            "refmac_diagnostic_profile._observe_controlled_root",
                            side_effect=obs_root_hook,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile._observe_regular_file_pin",
                            side_effect=obs_pin_hook,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.open",
                            side_effect=open_hook,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.fdopen",
                            side_effect=fdopen_hook,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.lstat",
                            side_effect=lstat_hook,
                        ),
                        self.assertRaises(ProfileValidationError) as pub_ctx,
                    ):
                        validate_profile(
                            profile,
                            installed_record,
                            ccp4_env,
                            ev_root,
                            chunk_size=5,
                        )
                    self.assertIs(m_state["mutated"], True)
                    self.assertEqual(m_state["file_reads"], 1)
                    with self.assertRaises(OSError) as ebadf_b:
                        real_fstat(int(m_state["inv_captured_fd"]))  # type: ignore[arg-type]
                    self.assertEqual(ebadf_b.exception.errno, errno.EBADF)

                    val_err = pub_ctx.exception
                    self.assertEqual(
                        val_err.failed_check, "outer_profile_files_and_roots"
                    )
                    if mode == "pre_eof_stream_eio":
                        self.assertIs(val_err.cause_exception, pre_eof_exc)
                    pub_prep = val_err.roots["prepared"]
                    self.assertIs(pub_prep.scan_complete, False)
                    self.assertIs(pub_prep.verified, False)
                    self.assertIn(".hidden_prepared_cfg", pub_prep.members)
                    self.assertNotIn(
                        "refmac_diagnostic_hooks.patch", pub_prep.members
                    )
                    check_partial_member(
                        pub_prep.partial_member_observations[
                            "refmac_diagnostic_hooks.patch"
                        ]
                    )
                    pub_file_obs = val_err.files[patch_fid]
                    assert isinstance(pub_file_obs, FileObservation)
                    self.assertIs(pub_file_obs.verified, True)
                    self.assertEqual(pub_file_obs.sha256, patch_sha)
                    with ExitStack() as poison:
                        for fn_name in ("stat", "lstat", "open", "readlink"):
                            poison.enter_context(
                                mock.patch(
                                    f"refmac_diagnostic_profile.os.{fn_name}",
                                    side_effect=AssertionError(
                                        f"provenance {fn_name} forbidden"
                                    ),
                                )
                            )
                        prov = val_err.to_provenance()
                        prov_mut = val_err.to_provenance()
                        prov_mut["roots"]["prepared"][
                            "partial_member_observations"
                        ]["refmac_diagnostic_hooks.patch"][
                            "observed_eof"
                        ] = None
                        self.assertEqual(val_err.to_provenance(), prov)
                    self.assertNotIn(
                        "partial_member_observations", prov["roots"]["vendor"]
                    )
                    self.assertNotIn(
                        "partial_member_observations", prov["roots"]["build"]
                    )
                    self.assertEqual(
                        prov["roots"]["prepared"][
                            "partial_member_observations"
                        ]["refmac_diagnostic_hooks.patch"]["failure_phase"],
                        (
                            "final_kernel_lookup"
                            if mode == "post_eof_dir_swap"
                            else "stream_read"
                        ),
                    )

                    # 2c. Private recheck (_reobserve_outer_profile_state)
                    reset_m_state()
                    with (
                        mock.patch(
                            "refmac_diagnostic_profile._observe_controlled_root",
                            side_effect=obs_root_hook,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile._observe_regular_file_pin",
                            side_effect=obs_pin_hook,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.open",
                            side_effect=open_hook,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.fdopen",
                            side_effect=fdopen_hook,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.lstat",
                            side_effect=lstat_hook,
                        ),
                    ):
                        priv_recheck = _reobserve_outer_profile_state(
                            baseline_state, chunk_size=5
                        )
                    self.assertIs(m_state["mutated"], True)
                    self.assertEqual(m_state["file_reads"], 1)
                    with self.assertRaises(OSError) as ebadf_c:
                        real_fstat(int(m_state["inv_captured_fd"]))  # type: ignore[arg-type]
                    self.assertEqual(ebadf_c.exception.errno, errno.EBADF)

                    self.assertIs(priv_recheck.verified, False)
                    self.assertIn("vendor", priv_recheck.verified_roots)
                    self.assertIn("build", priv_recheck.verified_roots)
                    self.assertIn("prepared", priv_recheck.incomplete_roots)
                    self.assertIn("prepared", priv_recheck.failed_roots)
                    check_partial_member(
                        priv_recheck.observed_roots[
                            "prepared"
                        ].partial_member_observations[
                            "refmac_diagnostic_hooks.patch"
                        ]
                    )
                    self.assertIn(patch_fid, priv_recheck.verified_files)
                    self.assertNotIn(patch_fid, priv_recheck.partial_files)
                    if mode == "pre_eof_stream_eio":
                        self.assertIs(
                            priv_recheck.root_causes["prepared"], pre_eof_exc
                        )
                        self.assertIs(
                            priv_recheck.observation_causes[
                                "profile:root:prepared"
                            ],
                            pre_eof_exc,
                        )

                    # 2d. Public recheck (recheck_profile)
                    reset_m_state()
                    pub_causes: list[BaseException | None] = []
                    with (
                        mock.patch(
                            "refmac_diagnostic_profile._observe_controlled_root",
                            side_effect=obs_root_hook,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile._observe_regular_file_pin",
                            side_effect=obs_pin_hook,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.open",
                            side_effect=open_hook,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.fdopen",
                            side_effect=fdopen_hook,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.lstat",
                            side_effect=lstat_hook,
                        ),
                    ):
                        pub_report = recheck_profile(
                            validated,
                            mutation_causes_out=pub_causes,
                        )
                    self.assertIs(m_state["mutated"], True)
                    self.assertEqual(m_state["file_reads"], 1)
                    with self.assertRaises(OSError) as ebadf_d:
                        real_fstat(int(m_state["inv_captured_fd"]))  # type: ignore[arg-type]
                    self.assertEqual(ebadf_d.exception.errno, errno.EBADF)

                    self.assertIs(pub_report["verified"], False)
                    self.assertIs(
                        pub_report["roots"]["vendor"]["matches_baseline"], True
                    )
                    self.assertIs(
                        pub_report["roots"]["build"]["matches_baseline"], True
                    )
                    prep_row = pub_report["roots"]["prepared"]
                    self.assertIs(prep_row["matches_baseline"], False)
                    self.assertEqual(
                        prep_row["member_diff"],
                        {"added": [], "removed": []},
                    )
                    self.assertEqual(
                        prep_row["observed"]["partial_member_observations"][
                            "refmac_diagnostic_hooks.patch"
                        ]["path"],
                        str(patch_path),
                    )
                    self.assertIs(
                        pub_report["files"][patch_fid]["matches_baseline"],
                        True,
                    )
                    self.assertEqual(
                        pub_report["files"][patch_fid]["errors"], []
                    )
                    self.assertEqual(
                        pub_report["files"][patch_fid]["observed"]["sha256"],
                        patch_sha,
                    )
                    self.assertEqual(len(pub_causes), 1)
                    if mode == "pre_eof_stream_eio":
                        self.assertIs(pub_causes[0], pre_eof_exc)

            # 3. Distinct inventory vs declared-file failures on the same path + ancestor-error reconstruction (#1035 Site 5)
            inv_eio = OSError(
                errno.EIO, "owned prepared inventory post-EOF end_fstat EIO"
            )
            file_eio = OSError(
                errno.EIO, "owned declared-file pre-EOF stream_read EIO"
            )
            anc_eio = OSError(
                errno.EACCES, "owned ancestor directory recheck EACCES"
            )
            dual_state: dict[str, object] = {
                "in_prepared_root": False,
                "active_lexical": None,
                "inv_fd": -1,
                "inv_captured_fd": -1,
                "inv_eof": False,
                "inv_injected": False,
                "file_fd": -1,
                "file_captured_fd": -1,
                "file_bytes": 0,
                "file_injected": False,
                "anc_injected": False,
            }

            def reset_dual_state() -> None:
                dual_state["in_prepared_root"] = False
                dual_state["active_lexical"] = None
                dual_state["inv_fd"] = -1
                dual_state["inv_captured_fd"] = -1
                dual_state["inv_eof"] = False
                dual_state["inv_injected"] = False
                dual_state["file_fd"] = -1
                dual_state["file_captured_fd"] = -1
                dual_state["file_bytes"] = 0
                dual_state["file_injected"] = False
                dual_state["anc_injected"] = False

            def dual_obs_root(name: str, *a, **kw):
                prev = dual_state["in_prepared_root"]
                if name == "prepared":
                    dual_state["in_prepared_root"] = True
                try:
                    return real_obs_root(name, *a, **kw)
                finally:
                    dual_state["in_prepared_root"] = prev

            def dual_obs_pin(path, *a, **kw):
                prev_lex = dual_state["active_lexical"]
                dual_state["active_lexical"] = str(path)
                try:
                    return real_obs_pin(path, *a, **kw)
                finally:
                    dual_state["inv_fd"] = -1
                    dual_state["file_fd"] = -1
                    dual_state["active_lexical"] = prev_lex

            def dual_open(path, flags, *a, **kw):
                fd = real_open(path, flags, *a, **kw)
                if (
                    dual_state["active_lexical"] == str(patch_path)
                    and str(path) == patch_resolved
                ):
                    if (
                        dual_state["in_prepared_root"]
                        and not dual_state["inv_injected"]
                    ):
                        dual_state["inv_fd"] = fd
                        dual_state["inv_captured_fd"] = fd
                        dual_state["inv_eof"] = False
                    elif (
                        not dual_state["in_prepared_root"]
                        and not dual_state["file_injected"]
                    ):
                        dual_state["file_fd"] = fd
                        dual_state["file_captured_fd"] = fd
                        dual_state["file_bytes"] = 0
                return fd

            def dual_fdopen(fd: int, mode_str: str = "rb", *a, **kw):
                handle = real_fdopen(fd, mode_str, *a, **kw)
                if fd == dual_state["inv_fd"]:
                    orig_read = handle.read

                    def read_inv(n: int = -1) -> bytes:
                        chunk = orig_read(n)
                        if chunk == b"":
                            dual_state["inv_eof"] = True
                        return chunk

                    handle.read = read_inv  # type: ignore[method-assign]
                elif fd == dual_state["file_fd"]:
                    orig_read_f = handle.read

                    def read_file(n: int = -1) -> bytes:
                        if (
                            int(dual_state["file_bytes"]) > 0  # type: ignore[arg-type]
                            and not dual_state["file_injected"]
                        ):
                            dual_state["file_injected"] = True
                            raise file_eio
                        chunk = orig_read_f(6)
                        dual_state["file_bytes"] = (
                            int(dual_state["file_bytes"]) + len(chunk)  # type: ignore[arg-type]
                        )
                        return chunk

                    handle.read = read_file  # type: ignore[method-assign]
                return handle

            def dual_fstat(fd: int, *a, **kw):
                if (
                    dual_state["inv_eof"]
                    and fd == dual_state["inv_fd"]
                    and not dual_state["inv_injected"]
                ):
                    dual_state["inv_injected"] = True
                    raise inv_eio
                return real_fstat(fd, *a, **kw)

            def dual_obs_dir(
                dir_path: str,
                *,
                require_no_symlink_ancestors: bool = True,
            ):
                if (
                    not require_no_symlink_ancestors
                    and dir_path == str(root)
                    and not dual_state["anc_injected"]
                ):
                    dual_state["anc_injected"] = True
                    raise ValueError(
                        f"Cannot inspect directory {dir_path!r}"
                    ) from anc_eio
                return real_obs_dir(
                    dir_path,
                    require_no_symlink_ancestors=require_no_symlink_ancestors,
                )

            reset_dual_state()
            with (
                mock.patch(
                    "refmac_diagnostic_profile._observe_controlled_root",
                    side_effect=dual_obs_root,
                ),
                mock.patch(
                    "refmac_diagnostic_profile._observe_regular_file_pin",
                    side_effect=dual_obs_pin,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.open",
                    side_effect=dual_open,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.fdopen",
                    side_effect=dual_fdopen,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.fstat",
                    side_effect=dual_fstat,
                ),
                self.assertRaises(ProfileValidationError) as dual_adm_ctx,
            ):
                validate_profile(
                    profile, installed_record, ccp4_env, ev_root, chunk_size=6
                )
            self.assertIs(dual_state["inv_injected"], True)
            self.assertIs(dual_state["file_injected"], True)
            dual_adm = dual_adm_ctx.exception
            adm_root_p = dual_adm.roots[
                "prepared"
            ].partial_member_observations["refmac_diagnostic_hooks.patch"]
            adm_file_p = dual_adm.files[patch_fid]
            assert isinstance(adm_file_p, PartialFileReadObservation)
            self.assertIsNot(adm_root_p, adm_file_p)
            self.assertEqual(adm_root_p.failure_phase, "end_fstat")
            self.assertIs(adm_root_p.observed_eof, True)
            self.assertEqual(adm_file_p.failure_phase, "stream_read")
            self.assertIs(adm_file_p.observed_eof, False)

            reset_dual_state()
            with (
                mock.patch(
                    "refmac_diagnostic_profile._observe_controlled_root",
                    side_effect=dual_obs_root,
                ),
                mock.patch(
                    "refmac_diagnostic_profile._observe_regular_file_pin",
                    side_effect=dual_obs_pin,
                ),
                mock.patch(
                    "refmac_diagnostic_profile._observe_directory_identity",
                    side_effect=dual_obs_dir,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.open",
                    side_effect=dual_open,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.fdopen",
                    side_effect=dual_fdopen,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.fstat",
                    side_effect=dual_fstat,
                ),
            ):
                dual_recheck = _reobserve_outer_profile_state(
                    baseline_state, chunk_size=6
                )
            self.assertIs(dual_state["inv_injected"], True)
            self.assertIs(dual_state["file_injected"], True)
            self.assertIs(dual_state["anc_injected"], True)
            for c_fd in (
                int(dual_state["inv_captured_fd"]),  # type: ignore[arg-type]
                int(dual_state["file_captured_fd"]),  # type: ignore[arg-type]
            ):
                with self.assertRaises(OSError) as ebadf_dual:
                    real_fstat(c_fd)
                self.assertEqual(ebadf_dual.exception.errno, errno.EBADF)

            prep_after = dual_recheck.observed_roots["prepared"]
            self.assertTrue(
                any(
                    "Controlled root 'prepared' recheck failed" in e
                    for e in prep_after.errors
                )
            )
            self.assertTrue(
                any(
                    f"Ancestor directory {str(root)!r} recheck failed" in e
                    for e in prep_after.errors
                )
            )
            inv_partial = prep_after.partial_member_observations[
                "refmac_diagnostic_hooks.patch"
            ]
            file_partial = dual_recheck.partial_files[patch_fid]
            self.assertIsNot(inv_partial, file_partial)
            self.assertIs(inv_partial.observed_eof, True)
            self.assertEqual(inv_partial.streamed_size_bytes, len(patch_bytes))
            self.assertEqual(inv_partial.observed_eof_sha256, patch_sha)
            self.assertEqual(inv_partial.failure_phase, "end_fstat")
            self.assertIs(file_partial.observed_eof, False)
            self.assertEqual(file_partial.streamed_size_bytes, 6)
            self.assertEqual(
                file_partial.observed_stream_sha256,
                _sha256_bytes(patch_bytes[:6]),
            )
            self.assertIsNone(file_partial.observed_eof_sha256)
            self.assertEqual(file_partial.failure_phase, "stream_read")
            self.assertIs(dual_recheck.root_causes["prepared"], inv_eio)
            self.assertIs(dual_recheck.file_causes[patch_fid], file_eio)
            self.assertIs(dual_recheck.ancestor_causes[str(root)], anc_eio)

            reset_dual_state()
            dual_pub_causes: list[BaseException | None] = []
            with (
                mock.patch(
                    "refmac_diagnostic_profile._observe_controlled_root",
                    side_effect=dual_obs_root,
                ),
                mock.patch(
                    "refmac_diagnostic_profile._observe_regular_file_pin",
                    side_effect=dual_obs_pin,
                ),
                mock.patch(
                    "refmac_diagnostic_profile._observe_directory_identity",
                    side_effect=dual_obs_dir,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.open",
                    side_effect=dual_open,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.fdopen",
                    side_effect=dual_fdopen,
                ),
                mock.patch(
                    "refmac_diagnostic_profile.os.fstat",
                    side_effect=dual_fstat,
                ),
            ):
                dual_pub = recheck_profile(
                    validated,
                    mutation_causes_out=dual_pub_causes,
                )
            self.assertEqual(
                dual_pub["roots"]["prepared"]["observed"][
                    "partial_member_observations"
                ]["refmac_diagnostic_hooks.patch"]["failure_phase"],
                "end_fstat",
            )
            self.assertEqual(
                dual_pub["files"][patch_fid]["observed"]["failure_phase"],
                "stream_read",
            )
            self.assertEqual(
                [
                    e["message"]
                    for e in dual_pub["roots"]["prepared"]["errors"]
                ],
                [str(inv_eio), str(anc_eio)],
            )
            self.assertEqual(
                [e["message"] for e in dual_pub["files"][patch_fid]["errors"]],
                [str(file_eio), str(anc_eio)],
            )
            self.assertIn(inv_eio, dual_pub_causes)
            self.assertIn(file_eio, dual_pub_causes)
            self.assertIn(anc_eio, dual_pub_causes)

            # 4. Hidden unregistered member partial failure + opaque-prefix file_id collision guard
            colliding_payload = copy.deepcopy(base_payload)
            old_writer_id = colliding_payload["roles"]["writer_input"][0]  # type: ignore[index]
            colliding_id = "unregistered:build:.hidden-extra.dat"
            writer_row = colliding_payload["files"].pop(old_writer_id)  # type: ignore[union-attr]
            writer_path_str = writer_row["path"]
            colliding_payload["files"][colliding_id] = writer_row  # type: ignore[index]
            colliding_payload["roles"]["writer_input"] = [colliding_id]  # type: ignore[index]
            colliding_profile = _rewrite_manifest_and_profile(
                fx, colliding_payload
            )
            colliding_validated = validate_profile(
                colliding_profile, installed_record, ccp4_env, ev_root
            )
            colliding_state = colliding_validated._outer_state
            assert colliding_state is not None

            hidden_extra = trees["build"] / ".hidden-extra.dat"
            hidden_bytes = b"hidden unregistered partial\n"
            hidden_sha = _sha256_bytes(hidden_bytes)
            hidden_extra.write_bytes(hidden_bytes)
            hidden_eio = OSError(
                errno.EIO, "owned hidden unregistered end_fstat EIO"
            )
            h_state: dict[str, object] = {
                "fd": -1,
                "eof": False,
                "injected": False,
            }

            def h_open(path, flags, *a, **kw):
                fd = real_open(path, flags, *a, **kw)
                if str(path) == str(hidden_extra) and not h_state["injected"]:
                    h_state["fd"] = fd
                    h_state["eof"] = False
                return fd

            def h_fdopen(fd: int, mode_str: str = "rb", *a, **kw):
                handle = real_fdopen(fd, mode_str, *a, **kw)
                if fd == h_state["fd"]:
                    orig_read = handle.read

                    def read_h(n: int = -1) -> bytes:
                        chunk = orig_read(n)
                        if chunk == b"":
                            h_state["eof"] = True
                        return chunk

                    handle.read = read_h  # type: ignore[method-assign]
                return handle

            def h_fstat(fd: int, *a, **kw):
                if (
                    h_state["eof"]
                    and fd == h_state["fd"]
                    and not h_state["injected"]
                ):
                    h_state["injected"] = True
                    raise hidden_eio
                return real_fstat(fd, *a, **kw)

            try:
                with (
                    mock.patch(
                        "refmac_diagnostic_profile.os.open",
                        side_effect=h_open,
                    ),
                    mock.patch(
                        "refmac_diagnostic_profile.os.fdopen",
                        side_effect=h_fdopen,
                    ),
                    mock.patch(
                        "refmac_diagnostic_profile.os.fstat",
                        side_effect=h_fstat,
                    ),
                    self.assertRaises(ProfileValidationError) as h_adm_ctx,
                ):
                    validate_profile(
                        colliding_profile, installed_record, ccp4_env, ev_root
                    )
                self.assertIs(h_state["injected"], True)
                with self.assertRaises(OSError) as h_ebadf_1:
                    real_fstat(int(h_state["fd"]))  # type: ignore[arg-type]
                self.assertEqual(h_ebadf_1.exception.errno, errno.EBADF)

                h_adm = h_adm_ctx.exception
                self.assertIs(h_adm.cause_exception, hidden_eio)
                h_build = h_adm.roots["build"]
                self.assertNotIn(".hidden-extra.dat", h_build.members)
                h_part = h_build.partial_member_observations[
                    ".hidden-extra.dat"
                ]
                self.assertEqual(h_part.path, str(hidden_extra))
                self.assertEqual(h_part.observed_eof_sha256, hidden_sha)
                self.assertEqual(
                    set(h_adm.files.keys()),
                    set(colliding_payload["files"].keys()),  # type: ignore[union-attr]
                )
                self.assertEqual(h_adm.files[colliding_id].path, writer_path_str)
                self.assertIs(h_adm.files[colliding_id].verified, True)

                h_state["fd"] = -1
                h_state["eof"] = False
                h_state["injected"] = False
                with (
                    mock.patch(
                        "refmac_diagnostic_profile.os.open",
                        side_effect=h_open,
                    ),
                    mock.patch(
                        "refmac_diagnostic_profile.os.fdopen",
                        side_effect=h_fdopen,
                    ),
                    mock.patch(
                        "refmac_diagnostic_profile.os.fstat",
                        side_effect=h_fstat,
                    ),
                ):
                    h_priv_rec = _reobserve_outer_profile_state(colliding_state)
                self.assertEqual(dict(h_priv_rec.partial_files), {})
                self.assertIn(colliding_id, h_priv_rec.verified_files)
                self.assertEqual(
                    h_priv_rec.observed_files[colliding_id].path,
                    writer_path_str,
                )
                self.assertEqual(
                    h_priv_rec.observed_roots[
                        "build"
                    ].partial_member_observations[".hidden-extra.dat"].path,
                    str(hidden_extra),
                )

                h_state["fd"] = -1
                h_state["eof"] = False
                h_state["injected"] = False
                h_causes: list[BaseException | None] = []
                with (
                    mock.patch(
                        "refmac_diagnostic_profile.os.open",
                        side_effect=h_open,
                    ),
                    mock.patch(
                        "refmac_diagnostic_profile.os.fdopen",
                        side_effect=h_fdopen,
                    ),
                    mock.patch(
                        "refmac_diagnostic_profile.os.fstat",
                        side_effect=h_fstat,
                    ),
                ):
                    h_pub_rec = recheck_profile(
                        colliding_validated, mutation_causes_out=h_causes
                    )
                self.assertEqual(
                    h_pub_rec["roots"]["build"]["member_diff"],
                    {"added": [], "removed": []},
                )
                self.assertEqual(
                    h_pub_rec["roots"]["build"]["observed"][
                        "partial_member_observations"
                    ][".hidden-extra.dat"]["observed_eof_sha256"],
                    hidden_sha,
                )
                self.assertIs(
                    h_pub_rec["files"][colliding_id]["matches_baseline"], True
                )
                self.assertEqual(h_causes, [hidden_eio])
            finally:
                if hidden_extra.exists():
                    hidden_extra.unlink()
                _rewrite_manifest_and_profile(fx, base_payload)

    def test_task1025_controlled_root_partial_member_carrier_invariants(
        self,
    ) -> None:
        from contextlib import ExitStack
        from dataclasses import replace

        real_fdopen = os.fdopen
        real_fstat = os.fstat

        for bad_rel, pattern in (
            (123, r"must be a str, got int"),
            ("", r"must be a non-empty relative POSIX path without NUL bytes"),
            (
                "a\x00b",
                r"must be a non-empty relative POSIX path without NUL bytes",
            ),
            (
                "/member.dat",
                r"must be a relative POSIX path without leading or trailing '/'",
            ),
            (
                "member.dat/",
                r"must be a relative POSIX path without leading or trailing '/'",
            ),
            (
                "sub//member.dat",
                r"must not contain empty, '\.', or '\.\.' path segments",
            ),
            (
                "./member.dat",
                r"must not contain empty, '\.', or '\.\.' path segments",
            ),
            (
                "../member.dat",
                r"must not contain empty, '\.', or '\.\.' path segments",
            ),
            (
                "sub/../member.dat",
                r"must not contain empty, '\.', or '\.\.' path segments",
            ),
        ):
            with self.subTest(bad_rel_key=repr(bad_rel)):
                with self.assertRaisesRegex(ValueError, pattern):
                    profile_mod._validate_root_relative_member_path(
                        bad_rel, field_name="test_rel"
                    )

        for good_rel in ("member.dat", " ", "\t", "sub/ ", "sub/\t"):
            with self.subTest(good_rel_key=repr(good_rel)):
                self.assertEqual(
                    profile_mod._validate_root_relative_member_path(
                        good_rel, field_name="test_rel"
                    ),
                    good_rel,
                )

        with tempfile.TemporaryDirectory() as tmpdir:
            base_tmp = Path(tmpdir).resolve()
            for label, member_name in (
                ("ordinary", "member.dat"),
                ("space", " "),
                ("tab", "\t"),
            ):
                with self.subTest(carrier_member=label):
                    root = (base_tmp / f"carrier-{label}").resolve()
                    root.mkdir()
                    member = root / member_name
                    payload = b"owned partial root carrier\n"
                    member.write_bytes(payload)
                    sha = _sha256_bytes(payload)

                    healthy = _observe_controlled_root(
                        "build",
                        str(root),
                        ("owned_member",),
                        declared_files={
                            "owned_member": {
                                "path": str(member),
                                "sha256": sha,
                                "size_bytes": len(payload),
                            }
                        },
                    )
                    public_healthy = profile_mod._build_root_observation(
                        healthy, None
                    )
                    self.assertNotIn(
                        "partial_member_observations", public_healthy.to_dict()
                    )

                    state: dict[str, object] = {
                        "fd": -1,
                        "eof": False,
                        "bytes_read": 0,
                        "injected": False,
                    }
                    injected = OSError(
                        errno.EIO, f"owned {label} carrier end_fstat EIO"
                    )

                    def c_fdopen(fd: int, mode: str = "rb", *a, **kw):
                        state["fd"] = fd
                        handle = real_fdopen(fd, mode, *a, **kw)
                        orig_read = handle.read

                        def read_track(n: int = -1) -> bytes:
                            b = orig_read(n)
                            state["bytes_read"] = (
                                int(state["bytes_read"]) + len(b)  # type: ignore[arg-type]
                            )
                            if b == b"":
                                state["eof"] = True
                            return b

                        handle.read = read_track  # type: ignore[method-assign]
                        return handle

                    def c_fstat(fd: int, *a, **kw):
                        if (
                            state["eof"]
                            and fd == state["fd"]
                            and not state["injected"]
                        ):
                            state["injected"] = True
                            raise injected
                        return real_fstat(fd, *a, **kw)

                    with (
                        mock.patch(
                            "refmac_diagnostic_profile.os.fdopen",
                            side_effect=c_fdopen,
                        ),
                        mock.patch(
                            "refmac_diagnostic_profile.os.fstat",
                            side_effect=c_fstat,
                        ),
                        self.assertRaises(_PartialFileReadError) as p_ctx,
                    ):
                        profile_mod._stream_observe_regular_file(
                            str(member), retain_bytes=True, chunk_size=7
                        )
                    self.assertIs(p_ctx.exception.__cause__, injected)
                    partial = p_ctx.exception.observation
                    self.assertIs(state["eof"], True)
                    self.assertEqual(state["bytes_read"], len(payload))
                    self.assertEqual(partial.observed_eof_sha256, sha)
                    with self.assertRaises(OSError) as ebadf_ctx:
                        real_fstat(int(state["fd"]))  # type: ignore[arg-type]
                    self.assertEqual(ebadf_ctx.exception.errno, errno.EBADF)

                    private_args: dict[str, object] = {
                        "member_pins": {},
                        "member_observations": {},
                        "scan_complete": False,
                        "verified": False,
                        "errors": ("owned interrupted inventory",),
                    }
                    public_args: dict[str, object] = {
                        "members": (),
                        "scan_complete": False,
                        "verified": False,
                        "errors": ("owned interrupted inventory",),
                    }
                    outside = PartialFileReadObservation(
                        path=str(root.parent / "outside.dat"),
                        resolved_path=None,
                        errors=("owned synthetic outside lexical owner",),
                        failure_phase="open",
                    )

                    with ExitStack() as stack:
                        for fn_name in (
                            "stat",
                            "lstat",
                            "fstat",
                            "open",
                            "readlink",
                        ):
                            stack.enter_context(
                                mock.patch(
                                    f"refmac_diagnostic_profile.os.{fn_name}",
                                    side_effect=AssertionError(
                                        "carrier/projection filesystem access forbidden"
                                    ),
                                )
                            )

                        # Positive accepted controls + input mapping detachment
                        source_map = {member_name: partial}
                        inv = replace(
                            healthy,
                            **private_args,  # type: ignore[arg-type]
                            partial_member_observations=source_map,
                        )
                        source_map.clear()
                        self.assertIs(
                            inv.partial_member_observations[member_name],
                            partial,
                        )
                        self.assertEqual(replace(inv), inv)

                        pub_map = {member_name: partial}
                        pub_from_map = replace(
                            public_healthy,
                            **public_args,  # type: ignore[arg-type]
                            partial_member_observations=pub_map,
                        )
                        pub_map.clear()
                        pub = replace(
                            public_healthy,
                            **public_args,  # type: ignore[arg-type]
                            partial_member_observations=(
                                (member_name, partial),
                            ),
                        )
                        self.assertEqual(pub_from_map, pub)
                        self.assertIs(
                            dict(pub.partial_member_observations)[member_name],
                            partial,
                        )
                        self.assertEqual(replace(pub), pub)
                        self.assertIs(inv.scan_complete, False)
                        self.assertIs(inv.verified, False)
                        self.assertIs(pub.scan_complete, False)
                        self.assertIs(pub.verified, False)
                        self.assertEqual(dict(inv.member_pins), {})
                        self.assertEqual(dict(inv.member_observations), {})
                        self.assertEqual(pub.members, ())

                        # Isolated single-fact negative guards from accepted inv and pub bases
                        for bad_key, priv_key_regex, pub_key_regex in (
                            (
                                "../member.dat",
                                r"must not contain empty, '\.', or '\.\.' path segments",
                                r"must not contain empty, '\.', or '\.\.' path segments",
                            ),
                            (
                                "/member.dat",
                                r"must be a relative POSIX path without leading or trailing '/'",
                                r"must be a relative POSIX path without leading or trailing '/'",
                            ),
                            (
                                "sub/../member.dat",
                                r"must not contain empty, '\.', or '\.\.' path segments",
                                r"must not contain empty, '\.', or '\.\.' path segments",
                            ),
                            (
                                "member.dat/",
                                r"must be a relative POSIX path without leading or trailing '/'",
                                r"must be a relative POSIX path without leading or trailing '/'",
                            ),
                            (
                                "sub//member.dat",
                                r"must not contain empty, '\.', or '\.\.' path segments",
                                r"must not contain empty, '\.', or '\.\.' path segments",
                            ),
                            (
                                "",
                                r"must be a non-empty relative POSIX path without NUL bytes",
                                r"^_FrozenPairTable entries must be \(non-empty str, value\) pairs",
                            ),
                            (
                                "a\x00b",
                                r"must be a non-empty relative POSIX path without NUL bytes",
                                r"must be a non-empty relative POSIX path without NUL bytes",
                            ),
                        ):
                            with self.assertRaisesRegex(
                                ValueError, priv_key_regex
                            ):
                                replace(
                                    inv,
                                    partial_member_observations={
                                        bad_key: partial
                                    },
                                )
                            with self.assertRaisesRegex(
                                ValueError, pub_key_regex
                            ):
                                replace(
                                    pub,
                                    partial_member_observations=(
                                        (bad_key, partial),
                                    ),
                                )

                        for bad_owner_map in (
                            {"other.dat": partial},
                            {member_name: outside},
                        ):
                            with self.assertRaisesRegex(
                                ValueError,
                                r"^_ObservedRootInventory\.partial_member_observations\[.*\]\.path .* must equal ",
                            ):
                                replace(
                                    inv,
                                    partial_member_observations=bad_owner_map,
                                )
                            with self.assertRaisesRegex(
                                ValueError,
                                r"^RootObservation\.partial_member_observations\[.*\]\.path .* must equal ",
                            ):
                                replace(
                                    pub,
                                    partial_member_observations=tuple(
                                        bad_owner_map.items()
                                    ),
                                )

                        for field_name, bad_val in (
                            ("scan_complete", True),
                            ("errors", ()),
                            ("errors", ("",)),
                        ):
                            with self.assertRaisesRegex(
                                ValueError,
                                r"^_ObservedRootInventory with non-empty partial_member_observations requires scan_complete=False, verified=False, and non-empty errors$",
                            ):
                                replace(inv, **{field_name: bad_val})
                            with self.assertRaisesRegex(
                                ValueError,
                                r"^RootObservation with non-empty partial_member_observations requires scan_complete=False, verified=False, and non-empty errors$",
                            ):
                                replace(pub, **{field_name: bad_val})

                        with self.assertRaisesRegex(
                            ValueError,
                            r"^_ObservedRootInventory cannot be verified when scan_complete is False or errors are present$",
                        ):
                            replace(inv, verified=True)
                        with self.assertRaisesRegex(
                            ValueError,
                            r"^RootObservation cannot have verified=True when scan_complete is False or errors are present$",
                        ):
                            replace(pub, verified=True)

                        with self.assertRaisesRegex(
                            ValueError,
                            r"^_ObservedRootInventory\.partial_member_observations key .* overlaps verified member_pins/member_observations$",
                        ):
                            replace(inv, member_pins=healthy.member_pins)
                        with self.assertRaisesRegex(
                            ValueError,
                            r"^_ObservedRootInventory\.partial_member_observations key .* overlaps verified member_pins/member_observations$",
                        ):
                            replace(
                                inv,
                                member_observations=healthy.member_observations,
                            )
                        with self.assertRaisesRegex(
                            ValueError,
                            r"^RootObservation\.partial_member_observations key .* overlaps RootObservation\.members$",
                        ):
                            replace(pub, members=public_healthy.members)

                        with self.assertRaisesRegex(
                            ValueError,
                            r"^_ObservedRootInventory\.partial_member_observations must map rel_posix -> PartialFileReadObservation$",
                        ):
                            replace(
                                inv,
                                partial_member_observations={
                                    member_name: None  # type: ignore[dict-item]
                                },
                            )
                        with self.assertRaisesRegex(
                            ValueError,
                            r"^RootObservation\.partial_member_observations values must be PartialFileReadObservation$",
                        ):
                            replace(
                                pub,
                                partial_member_observations=(
                                    (member_name, None),  # type: ignore[arg-type]
                                ),
                            )
                        with self.assertRaisesRegex(
                            ValueError,
                            r"^RootObservation\.partial_member_observations must be a Mapping or sequence of \(rel_posix, PartialFileReadObservation\) pairs$",
                        ):
                            replace(
                                pub,
                                partial_member_observations=123,  # type: ignore[arg-type]
                            )
                        with self.assertRaisesRegex(
                            ValueError, r"Duplicate key in _FrozenPairTable"
                        ):
                            replace(
                                pub,
                                partial_member_observations=(
                                    (member_name, partial),
                                    (member_name, partial),
                                ),
                            )

                        with self.assertRaises(TypeError):
                            inv.partial_member_observations[member_name] = (  # type: ignore[index]
                                partial
                            )
                        with self.assertRaises(TypeError):
                            pub.partial_member_observations[0] = (  # type: ignore[index]
                                member_name,
                                partial,
                            )
                        with self.assertRaises(FrozenInstanceError):
                            partial.verified = True  # type: ignore[misc]

                        actual = pub.to_dict()
                        self.assertEqual(
                            actual["partial_member_observations"][member_name][
                                "observed_eof_sha256"
                            ],
                            sha,
                        )
                        self.assertEqual(
                            actual["partial_member_observations"][member_name][
                                "streamed_size_bytes"
                            ],
                            len(payload),
                        )
                        self.assertEqual(
                            actual["partial_member_observations"][member_name][
                                "path"
                            ],
                            str(member),
                        )
                        detached = pub.to_dict()
                        detached["partial_member_observations"][member_name][
                            "observed_eof"
                        ] = False
                        self.assertEqual(pub.to_dict(), actual)
                        self.assertNotIn(
                            "partial_member_observations",
                            public_healthy.to_dict(),
                        )


if __name__ == "__main__":
    unittest.main()
