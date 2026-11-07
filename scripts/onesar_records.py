"""Retained-file reference verification boundary for 1SAR record authoring.

Task 357 (first bounded slice of Task 168): provides the pure, execution-free
retained-reference loader and refusal exception used to reopen and verify
producer manifests and artifacts under an admitted attempt root.

Key invariants of this boundary:
- Never invokes PHENIX, CCP4/REFMAC, or producer collectors.
- Never infers artifact paths from expected filenames or substitutes unchecked
  in-memory mappings for disk evidence.
- Requires an explicit path and lowercase 64-hex SHA-256 digest (plus byte size
  when declared by the producer reference).
- Verifies that the admitted root and every component from the admitted root to
  the target file are free of symlinks, that the target remains strictly inside
  the admitted root both lexically and after resolution, and that the target is
  a regular file whose reopened bytes match the declared SHA-256 and size.
- Optionally decodes strict UTF-8 JSON mappings while rejecting duplicate keys
  and non-finite numbers (``NaN``, ``Infinity``, ``-Infinity``).
- Treats path and digest agreement strictly as file-integrity evidence
  (``integrity_verified=True``, ``scientific_proof_established=False``), never
  as native scientific proof.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from typing import Any, Mapping


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RetainedReferenceError(ValueError):
    """Raised when a retained file reference or artifact fails integrity verification."""


def _validate_sha256_hex(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise RetainedReferenceError(
            f"{label}: expected 64-character lowercase hex sha256 digest, got {value!r}"
        )
    return value


def _validate_optional_size_bytes(value: Any, *, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RetainedReferenceError(
            f"{label}: expected non-negative int size_bytes, got {value!r}"
        )
    return int(value)


def _ensure_no_symlink_chain_to_directory(dir_path: Path, *, label: str) -> Path:
    """Verify ``dir_path`` exists, is a directory, and has no symlink or ``..`` component."""
    raw_text = os.fspath(dir_path)
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise RetainedReferenceError(f"{label}: directory path must be a non-empty string")
    raw_path = Path(raw_text)
    raw_split_parts = [part for part in re.split(r"[/\\]+", raw_text) if part]
    if ".." in raw_path.parts or ".." in raw_split_parts:
        raise RetainedReferenceError(
            f"{label}: parent-directory traversal ('..') is not permitted in directory path {raw_text!r}"
        )
    if raw_path.is_absolute():
        current = Path(raw_path.anchor)
        walk_parts = [part for part in raw_path.parts[1:] if part not in ("", ".")]
    else:
        current = _ensure_no_symlink_chain_to_directory(
            Path(os.getcwd()), label=f"{label}.cwd"
        )
        walk_parts = [part for part in raw_path.parts if part not in ("", ".")]
    for part in walk_parts:
        current = current / part
        try:
            st = os.lstat(current)
        except OSError as exc:
            raise RetainedReferenceError(
                f"{label}: directory component {current} is unavailable ({type(exc).__name__}): {exc}"
            ) from exc
        if stat.S_ISLNK(st.st_mode):
            raise RetainedReferenceError(
                f"{label}: symlink component is not permitted at {current}"
            )
        if not stat.S_ISDIR(st.st_mode):
            raise RetainedReferenceError(
                f"{label}: path component is not a directory at {current}"
            )
    try:
        resolved = current.resolve(strict=True)
    except OSError as exc:
        raise RetainedReferenceError(
            f"{label}: failed to resolve directory {current} ({type(exc).__name__}): {exc}"
        ) from exc
    if resolved != current:
        raise RetainedReferenceError(
            f"{label}: directory path {current} resolved to unexpected target {resolved}"
        )
    return resolved


def normalize_retained_reference(
    reference: Mapping[str, Any] | None = None,
    *,
    path: str | os.PathLike[str] | None = None,
    sha256: str | None = None,
    size_bytes: int | None = None,
    path_key: str = "path",
    sha256_key: str = "sha256",
    size_bytes_key: str | None = "size_bytes",
    label: str = "artifact",
) -> dict[str, Any]:
    """Normalize an explicit producer artifact reference without guessing filenames.

    Supports the actual reference shapes produced by PHENIX and REFMAC:
    - Direct explicit bindings ``path=...`` and ``sha256=...`` (plus optional
      ``size_bytes=...``), such as PRIMARY/CLI binding of
      ``phenix_reconciled_manifest.json``.
    - Producer artifact dicts such as REFMAC ``manifest_json`` / ``diagnostics_json``
      / ``raw_outputs[key]`` (``{"path": ..., "sha256": ..., "size_bytes": ...,
      "persisted": ...}``) or PHENIX cache manifest ``artifacts[key]``
      (``{"path": ..., "sha256": ...}``).
    - Carrier dicts using explicit key names via ``path_key`` / ``sha256_key``
      (e.g. ``manifest_path`` / ``manifest_sha256`` or
      ``preflight_build_evidence_json_path`` / ``preflight_build_evidence_sha256``).
    """
    if reference is not None and not isinstance(reference, Mapping):
        raise RetainedReferenceError(
            f"{label}: reference must be a mapping when provided, got {type(reference).__name__}"
        )
    if reference is None and path is None and sha256 is None:
        raise RetainedReferenceError(
            f"{label}: explicit reference mapping or (path, sha256) pair is required"
        )

    is_fallback = False
    fallback_anchor_dir: str | None = None
    ref_path_val: Any = None
    ref_sha_val: Any = None
    ref_size_val: Any = None

    if reference is not None:
        if reference.get("persisted") is False:
            unpersisted_reason = (
                reference.get("unpersisted_reason")
                or reference.get("child_dir_persistence_error")
                or "artifact record reports persisted=False"
            )
            raise RetainedReferenceError(
                f"{label}: refusing payload-only or unpersisted artifact reference "
                f"({unpersisted_reason})"
            )
        if reference.get("no_verified_anchor_available") is True:
            raise RetainedReferenceError(
                f"{label}: refusing artifact reference with no_verified_anchor_available=True"
            )
        if reference.get("payload_materialized") is False:
            raise RetainedReferenceError(
                f"{label}: refusing artifact reference with payload_materialized=False"
            )
        if reference.get("error") is not None:
            raise RetainedReferenceError(
                f"{label}: refusing artifact reference carrying error={reference.get('error')!r}"
            )
        if reference.get("is_symlink") is True:
            raise RetainedReferenceError(
                f"{label}: refusing artifact reference flagged with is_symlink=True"
            )
        if (
            "is_regular_file" in reference
            and reference.get("is_regular_file") is not True
        ):
            raise RetainedReferenceError(
                f"{label}: refusing artifact reference with is_regular_file={reference.get('is_regular_file')!r}"
            )
        if "exists" in reference and reference.get("exists") is not True:
            raise RetainedReferenceError(
                f"{label}: refusing artifact reference with exists={reference.get('exists')!r}"
            )

        if path_key not in reference and path is None:
            raise RetainedReferenceError(
                f"{label}: reference mapping is missing required path key {path_key!r}"
            )
        if sha256_key not in reference and sha256 is None:
            raise RetainedReferenceError(
                f"{label}: reference mapping is missing required sha256 key {sha256_key!r}"
            )
        ref_path_val = reference.get(path_key)
        ref_sha_val = reference.get(sha256_key)
        if size_bytes_key is not None and size_bytes_key in reference:
            ref_size_val = reference.get(size_bytes_key)

        preexisting_fallback = reference.get("fallback_for_preexisting_path")
        has_preexisting_fallback = (
            isinstance(preexisting_fallback, str)
            and bool(preexisting_fallback.strip())
        )
        is_fallback = bool(
            has_preexisting_fallback
            or reference.get("fallback_for_unwritable_or_damaged_child_dir")
            or reference.get("fallback_for_damaged_or_replaced_parent_retention_dir")
            or reference.get("collision_avoided_in_parent_retention_dir")
            or reference.get("collision_avoided_in_actual_retention_anchor_dir")
        )
        raw_anchor = (
            reference.get("actual_retention_anchor_dir")
            or reference.get("parent_retention_dir")
        )
        if isinstance(raw_anchor, str) and raw_anchor.strip():
            fallback_anchor_dir = raw_anchor

    if path is not None:
        try:
            explicit_path_str = os.fspath(path)
        except TypeError as exc:
            raise RetainedReferenceError(
                f"{label}: path must be a path-like or string, got {path!r}"
            ) from exc
        if not isinstance(explicit_path_str, str) or not explicit_path_str.strip():
            raise RetainedReferenceError(
                f"{label}: explicit path must be a non-empty string, got {path!r}"
            )
        if ref_path_val is not None and str(ref_path_val) != explicit_path_str:
            raise RetainedReferenceError(
                f"{label}: explicit path {explicit_path_str!r} disagrees with "
                f"reference[{path_key!r}]={ref_path_val!r}"
            )
        selected_path_str = explicit_path_str
    else:
        if not isinstance(ref_path_val, str) or not ref_path_val.strip():
            raise RetainedReferenceError(
                f"{label}: reference[{path_key!r}] must be a non-empty string path, "
                f"got {ref_path_val!r}"
            )
        selected_path_str = ref_path_val

    if sha256 is not None:
        validated_explicit_sha = _validate_sha256_hex(sha256, label=f"{label}.sha256")
        if ref_sha_val is not None:
            validated_ref_sha = _validate_sha256_hex(
                ref_sha_val, label=f"{label}.reference[{sha256_key!r}]"
            )
            if validated_explicit_sha != validated_ref_sha:
                raise RetainedReferenceError(
                    f"{label}: explicit sha256 {validated_explicit_sha!r} disagrees with "
                    f"reference[{sha256_key!r}]={validated_ref_sha!r}"
                )
        selected_sha256 = validated_explicit_sha
    else:
        selected_sha256 = _validate_sha256_hex(
            ref_sha_val, label=f"{label}.reference[{sha256_key!r}]"
        )

    validated_explicit_size = _validate_optional_size_bytes(
        size_bytes, label=f"{label}.size_bytes"
    )
    validated_ref_size = _validate_optional_size_bytes(
        ref_size_val,
        label=f"{label}.reference[{size_bytes_key!r}]"
        if size_bytes_key is not None
        else f"{label}.size_bytes",
    )
    if (
        validated_explicit_size is not None
        and validated_ref_size is not None
        and validated_explicit_size != validated_ref_size
    ):
        raise RetainedReferenceError(
            f"{label}: explicit size_bytes {validated_explicit_size} disagrees with "
            f"reference[{size_bytes_key!r}]={validated_ref_size}"
        )
    selected_size_bytes = (
        validated_explicit_size
        if validated_explicit_size is not None
        else validated_ref_size
    )

    return {
        "path": selected_path_str,
        "sha256": selected_sha256,
        "size_bytes": selected_size_bytes,
        "is_fallback": is_fallback,
        "fallback_anchor_dir": fallback_anchor_dir,
    }


def decode_strict_json_mapping(
    raw_bytes: bytes,
    *,
    label: str = "artifact",
) -> dict[str, Any]:
    """Decode strict UTF-8 JSON mapping, rejecting duplicate keys and non-finite numbers."""
    if not isinstance(raw_bytes, (bytes, bytearray)):
        raise RetainedReferenceError(
            f"{label}: expected raw bytes for JSON decoding, got {type(raw_bytes).__name__}"
        )
    try:
        text = bytes(raw_bytes).decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise RetainedReferenceError(
            f"{label}: file is not valid UTF-8 ({exc})"
        ) from exc

    def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        obj: dict[str, Any] = {}
        for key, value in pairs:
            if key in obj:
                raise RetainedReferenceError(
                    f"{label}: duplicate JSON object key {key!r} is not permitted"
                )
            obj[key] = value
        return obj

    def _reject_nonfinite_constant(token: str) -> Any:
        raise RetainedReferenceError(
            f"{label}: non-finite JSON constant {token!r} is not permitted"
        )

    def _reject_nonfinite_float(token: str) -> float:
        value = float(token)
        if not math.isfinite(value):
            raise RetainedReferenceError(
                f"{label}: non-finite JSON float token {token!r} is not permitted"
            )
        return value

    def _ensure_all_values_finite(node: Any) -> None:
        if isinstance(node, float):
            if not math.isfinite(node):
                raise RetainedReferenceError(
                    f"{label}: non-finite JSON float value {node!r} is not permitted"
                )
        elif isinstance(node, dict):
            for val in node.values():
                _ensure_all_values_finite(val)
        elif isinstance(node, list):
            for item in node:
                _ensure_all_values_finite(item)

    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_constant,
            parse_float=_reject_nonfinite_float,
        )
    except RetainedReferenceError:
        raise
    except (json.JSONDecodeError, ValueError) as exc:
        raise RetainedReferenceError(
            f"{label}: malformed JSON content ({exc})"
        ) from exc

    if not isinstance(parsed, dict):
        raise RetainedReferenceError(
            f"{label}: expected top-level JSON object mapping, got {type(parsed).__name__}"
        )
    _ensure_all_values_finite(parsed)
    return parsed


def load_retained_reference(
    admitted_root: str | os.PathLike[str],
    reference: Mapping[str, Any] | None = None,
    *,
    path: str | os.PathLike[str] | None = None,
    sha256: str | None = None,
    size_bytes: int | None = None,
    path_key: str = "path",
    sha256_key: str = "sha256",
    size_bytes_key: str | None = "size_bytes",
    parse_json: bool = False,
    reject_cache_manifest_as_phenix_reconciled: bool = False,
    label: str = "artifact",
) -> dict[str, Any]:
    """Reopen and verify a retained file reference under ``admitted_root``.

    Verifies that:
    1. ``admitted_root`` is an existing directory with no symlink component.
    2. The reference supplies an explicit path and 64-hex SHA-256 (and optional
       non-negative integer ``size_bytes``), and is not an unpersisted or
       payload-only record.
    3. The target path contains no ``..`` traversal component, remains strictly
       inside ``admitted_root`` both lexically and after resolution, has no
       symlink component along its relative path from ``admitted_root``, and is
       a regular file.
    4. The reopened bytes match ``st_size``, ``sha256``, and any declared
       ``size_bytes``.
    5. When ``parse_json=True`` (or ``reject_cache_manifest_as_phenix_reconciled=True``),
       the file decodes as a strict UTF-8 JSON mapping with no duplicate keys or
       non-finite values.
    6. When ``reject_cache_manifest_as_phenix_reconciled=True``, rejects raw
       ``refinement_cache`` ``success.json`` manifests passed in place of
       ``phenix_reconciled_manifest.json``.
    """
    try:
        root_Input = Path(os.fspath(admitted_root))
    except TypeError as exc:
        raise RetainedReferenceError(
            f"{label}: admitted_root must be path-like, got {admitted_root!r}"
        ) from exc
    resolved_root = _ensure_no_symlink_chain_to_directory(
        root_Input, label=f"{label}.admitted_root"
    )

    norm_ref = normalize_retained_reference(
        reference,
        path=path,
        sha256=sha256,
        size_bytes=size_bytes,
        path_key=path_key,
        sha256_key=sha256_key,
        size_bytes_key=size_bytes_key,
        label=label,
    )
    raw_target_str: str = norm_ref["path"]
    expected_sha256: str = norm_ref["sha256"]
    expected_size_bytes: int | None = norm_ref["size_bytes"]

    raw_target_path = Path(raw_target_str)
    if ".." in raw_target_path.parts:
        raise RetainedReferenceError(
            f"{label}: parent-directory traversal ('..') is not permitted in path {raw_target_str!r}"
        )

    candidate_path = (
        raw_target_path
        if raw_target_path.is_absolute()
        else (resolved_root / raw_target_path)
    )
    lexical_abs = Path(os.path.abspath(os.fspath(candidate_path)))
    if lexical_abs == resolved_root or not lexical_abs.is_relative_to(resolved_root):
        raise RetainedReferenceError(
            f"{label}: path {raw_target_str!r} (lexical {lexical_abs}) is outside "
            f"admitted root {resolved_root}"
        )

    rel_parts = lexical_abs.relative_to(resolved_root).parts
    current = resolved_root
    for part in rel_parts[:-1]:
        current = current / part
        try:
            anc_st = os.lstat(current)
        except OSError as exc:
            raise RetainedReferenceError(
                f"{label}: missing or inaccessible ancestor directory {current} "
                f"({type(exc).__name__}): {exc}"
            ) from exc
        if stat.S_ISLNK(anc_st.st_mode):
            raise RetainedReferenceError(
                f"{label}: ancestor component is a symlink at {current}"
            )
        if not stat.S_ISDIR(anc_st.st_mode):
            raise RetainedReferenceError(
                f"{label}: ancestor component is not a directory at {current}"
            )

    try:
        leaf_st = os.lstat(lexical_abs)
    except FileNotFoundError as exc:
        raise RetainedReferenceError(
            f"{label}: retained file does not exist on disk at {lexical_abs}"
        ) from exc
    except OSError as exc:
        raise RetainedReferenceError(
            f"{label}: failed to lstat retained file at {lexical_abs} "
            f"({type(exc).__name__}): {exc}"
        ) from exc

    if stat.S_ISLNK(leaf_st.st_mode):
        raise RetainedReferenceError(
            f"{label}: retained file path is a symlink at {lexical_abs}"
        )
    if not stat.S_ISREG(leaf_st.st_mode):
        raise RetainedReferenceError(
            f"{label}: retained path is not a regular file at {lexical_abs}"
        )

    try:
        resolved_target = lexical_abs.resolve(strict=True)
    except OSError as exc:
        raise RetainedReferenceError(
            f"{label}: failed to resolve retained path {lexical_abs} "
            f"({type(exc).__name__}): {exc}"
        ) from exc

    if (
        resolved_target != lexical_abs
        or resolved_target == resolved_root
        or not resolved_target.is_relative_to(resolved_root)
    ):
        raise RetainedReferenceError(
            f"{label}: resolved path {resolved_target} escaped admitted root {resolved_root}"
        )

    try:
        raw_bytes = resolved_target.read_bytes()
    except OSError as exc:
        raise RetainedReferenceError(
            f"{label}: failed to read retained regular file {resolved_target} "
            f"({type(exc).__name__}): {exc}"
        ) from exc

    actual_size_bytes = len(raw_bytes)
    stat_size_bytes = int(leaf_st.st_size)
    if actual_size_bytes != stat_size_bytes:
        raise RetainedReferenceError(
            f"{label}: byte length {actual_size_bytes} disagrees with stat size "
            f"{stat_size_bytes} at {resolved_target}"
        )
    if expected_size_bytes is not None and actual_size_bytes != expected_size_bytes:
        raise RetainedReferenceError(
            f"{label}: size_bytes mismatch at {resolved_target}: "
            f"expected {expected_size_bytes}, observed {actual_size_bytes}"
        )

    actual_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    if actual_sha256 != expected_sha256:
        raise RetainedReferenceError(
            f"{label}: sha256 mismatch at {resolved_target}: "
            f"expected {expected_sha256}, observed {actual_sha256}"
        )

    should_parse_json = bool(
        parse_json or reject_cache_manifest_as_phenix_reconciled
    )
    parsed_json: dict[str, Any] | None = None
    if should_parse_json:
        parsed_json = decode_strict_json_mapping(raw_bytes, label=label)

    if reject_cache_manifest_as_phenix_reconciled:
        assert parsed_json is not None
        nested_manifest_path = parsed_json.get("manifest_path")
        has_reconciled_shape = (
            isinstance(parsed_json.get("reconciliation"), Mapping)
            and isinstance(parsed_json.get("operation_manifest"), Mapping)
            and isinstance(nested_manifest_path, str)
            and bool(nested_manifest_path.strip())
        )
        if not has_reconciled_shape:
            raise RetainedReferenceError(
                f"{label}: expected PHENIX reconciled manifest "
                f"(phenix_reconciled_manifest.json with 'reconciliation', "
                f"'operation_manifest', and cache 'manifest_path'), but {resolved_target} "
                f"does not have the reconciled manifest structure (cache success.json "
                f"must not be substituted for phenix_reconciled_manifest.json)"
            )
        nested_manifest_abs = Path(os.path.abspath(nested_manifest_path))
        if nested_manifest_abs == resolved_target:
            raise RetainedReferenceError(
                f"{label}: reconciled manifest at {resolved_target} has self-referential "
                f"cache manifest_path={nested_manifest_path!r}"
            )

    return {
        "label": label,
        "verified_reference": {
            "admitted_root": str(resolved_root),
            "path": str(resolved_target),
            "relative_path": resolved_target.relative_to(resolved_root).as_posix(),
            "sha256": actual_sha256,
            "size_bytes": actual_size_bytes,
            "declared_size_bytes": expected_size_bytes,
            "persisted": True,
            "is_fallback": bool(norm_ref["is_fallback"]),
            "fallback_anchor_dir": norm_ref["fallback_anchor_dir"],
            "integrity_verified": True,
            "scientific_proof_established": False,
        },
        "bytes": raw_bytes,
        "json": parsed_json,
    }
