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

import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Mapping


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RetainedReferenceError(ValueError):
    """Raised when a retained file reference or artifact fails integrity verification."""


class PhenixRetainedVerificationError(RetainedReferenceError):
    """Raised when retained PHENIX R-factor evidence fails provenance or reconciliation verification."""


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


_REQUIRED_PHENIX_RECONCILED_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "subject",
        "mtz",
        "staged_files",
        "input_hkl_ledger_json_path",
        "input_hkl_ledger_json_sha256",
        "preflight_build_evidence_json_path",
        "preflight_build_evidence_sha256",
        "cache_artifacts",
        "manifest_path",
        "manifest_sha256",
        "stdout_log_path",
        "phenix_rfactors_json_path",
        "phenix_diagnostics_json_path",
        "phenix_partial_evidence_json_path",
        "phenix_partial_evidence_sha256",
        "phx_maps_mtz_path",
        "phx_obs_pair_only_mtz_path",
        "operation_manifest",
        "reconciliation",
    }
)

_REQUIRED_STAGED_FILES_KEYS = frozenset(
    {
        "original_model_pdb",
        "original_model_pdb_sha256",
        "original_data_mtz",
        "original_data_mtz_sha256",
        "projected_observations_mtz",
        "projected_observations_mtz_sha256",
        "input_hkl_ledger_json",
        "input_hkl_ledger_json_sha256",
    }
)

_EXPECTED_PHENIX_REQUIRED_OUTPUTS: dict[str, str] = {
    "phenix_rfactors_json": "phenix_rfactors.json",
    "phx_maps_mtz": "phx_maps.mtz",
    "phx_obs_pair_only_mtz": "PHX_OBS_PAIR_ONLY.mtz",
    "phenix_diagnostics_json": "phenix_diagnostics.json",
}

_EXPECTED_PHENIX_BUNDLE_RELPATHS: dict[str, str] = {
    "stdout": "stdout.log",
    **_EXPECTED_PHENIX_REQUIRED_OUTPUTS,
}


def _load_phenix_verification_deps() -> tuple[Any, Any, Any, Any]:
    """Import pure PHENIX verification dependencies lazily to avoid import-time cycles."""
    scripts_dir = Path(__file__).resolve().parent
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import onesar_phenix_measure
    import onesar_rerun
    import refinement_cache
    import toolchain

    return onesar_phenix_measure, onesar_rerun, refinement_cache, toolchain


def _extract_validated_hkl_list(
    records: Any,
    *,
    expected_count: int,
    label: str,
) -> list[list[int]]:
    """Extract and validate canonical sorted ``[h, k, l]`` integer triples from a stage array."""
    if not isinstance(records, list) or not records:
        raise PhenixRetainedVerificationError(
            f"{label}: expected non-empty list of reflection records"
        )
    if len(records) != expected_count:
        raise PhenixRetainedVerificationError(
            f"{label}: record count {len(records)} disagrees with expected count {expected_count}"
        )
    seen: set[tuple[int, int, int]] = set()
    hkls: list[list[int]] = []
    for idx, rec in enumerate(records):
        if not isinstance(rec, Mapping):
            raise PhenixRetainedVerificationError(
                f"{label}[{idx}]: expected mapping record, got {type(rec).__name__}"
            )
        raw_hkl = rec.get("hkl")
        if (
            not isinstance(raw_hkl, list)
            or len(raw_hkl) != 3
            or any(type(v) is not int for v in raw_hkl)
            or raw_hkl == [0, 0, 0]
        ):
            raise PhenixRetainedVerificationError(
                f"{label}[{idx}]: invalid Miller index hkl={raw_hkl!r}"
            )
        triple = (int(raw_hkl[0]), int(raw_hkl[1]), int(raw_hkl[2]))
        if triple in seen:
            raise PhenixRetainedVerificationError(
                f"{label}[{idx}]: duplicate Miller index {list(triple)}"
            )
        seen.add(triple)
        hkls.append([triple[0], triple[1], triple[2]])
    return sorted(hkls, key=lambda item: (item[0], item[1], item[2]))


def _verify_retained_phenix_rfactor_evidence_impl(
    admitted_root: str | os.PathLike[str],
    *,
    subject_id: str,
    reconciled_manifest_reference: Mapping[str, Any] | None = None,
    reconciled_manifest_path: str | os.PathLike[str] | None = None,
    reconciled_manifest_sha256: str | None = None,
    reconciled_manifest_size_bytes: int | None = None,
    repo_root: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    onesar_phenix_measure, onesar_rerun, refinement_cache, toolchain = (
        _load_phenix_verification_deps()
    )

    try:
        admitted_root_path = Path(os.fspath(admitted_root))
    except TypeError as exc:
        raise PhenixRetainedVerificationError(
            f"admitted_root: must be path-like, got {admitted_root!r}"
        ) from exc
    resolved_admitted_root = _ensure_no_symlink_chain_to_directory(
        admitted_root_path, label="admitted_root"
    )

    try:
        expected_subject = onesar_rerun.resolve_subject_spec(subject_id)
    except ValueError as exc:
        raise PhenixRetainedVerificationError(f"subject_id: {exc}") from exc
    expected_mtz = {
        "member": onesar_rerun.MTZ_MEMBER,
        "sha256": onesar_rerun.MTZ_SHA256,
        "subject_ref": onesar_rerun.MTZ_SUBJECT_REF,
    }

    raw_repo_root = onesar_rerun.REPO_ROOT if repo_root is None else repo_root
    try:
        repo_root_path = Path(os.fspath(raw_repo_root))
    except TypeError as exc:
        raise PhenixRetainedVerificationError(
            f"repo_root: must be path-like, got {raw_repo_root!r}"
        ) from exc
    resolved_repo_root = _ensure_no_symlink_chain_to_directory(
        repo_root_path, label="repo_root"
    )

    reconciled_size_key = (
        "size_bytes"
        if isinstance(reconciled_manifest_reference, Mapping)
        and "size_bytes" in reconciled_manifest_reference
        else None
    )
    reconciled_loaded = load_retained_reference(
        resolved_admitted_root,
        reconciled_manifest_reference,
        path=reconciled_manifest_path,
        sha256=reconciled_manifest_sha256,
        size_bytes=reconciled_manifest_size_bytes,
        size_bytes_key=reconciled_size_key,
        parse_json=True,
        reject_cache_manifest_as_phenix_reconciled=True,
        label="phenix_reconciled_manifest",
    )
    reconciled_doc = reconciled_loaded["json"]
    assert isinstance(reconciled_doc, dict)
    reconciled_path = Path(reconciled_loaded["verified_reference"]["path"])
    if (
        reconciled_path.name != "phenix_reconciled_manifest.json"
        or reconciled_path.parent.name != "phenix"
    ):
        raise PhenixRetainedVerificationError(
            "phenix_reconciled_manifest: expected path ending in "
            f"'phenix/phenix_reconciled_manifest.json', got {reconciled_path}"
        )
    phenix_dir = reconciled_path.parent
    attempt_root = phenix_dir.parent
    if not attempt_root.is_relative_to(resolved_admitted_root):
        raise PhenixRetainedVerificationError(
            f"phenix_reconciled_manifest: attempt root {attempt_root} is outside "
            f"admitted root {resolved_admitted_root}"
        )

    for failure_marker_name in (
        "phenix_build_admission_failure.json",
        "phenix_operation_failure.json",
    ):
        failure_marker_path = phenix_dir / failure_marker_name
        if os.path.lexists(failure_marker_path):
            raise PhenixRetainedVerificationError(
                f"phenix_reconciled_manifest: refusing retained PHENIX directory with "
                f"failure record present at {failure_marker_path}"
            )

    if set(reconciled_doc.keys()) != _REQUIRED_PHENIX_RECONCILED_MANIFEST_KEYS:
        missing_keys = sorted(
            _REQUIRED_PHENIX_RECONCILED_MANIFEST_KEYS - set(reconciled_doc.keys())
        )
        extra_keys = sorted(
            set(reconciled_doc.keys()) - _REQUIRED_PHENIX_RECONCILED_MANIFEST_KEYS
        )
        raise PhenixRetainedVerificationError(
            "phenix_reconciled_manifest: top-level key mismatch "
            f"(missing={missing_keys}, unexpected={extra_keys})"
        )
    if (
        type(reconciled_doc.get("schema_version")) is not int
        or reconciled_doc["schema_version"] != 1
    ):
        raise PhenixRetainedVerificationError(
            "phenix_reconciled_manifest: expected integer schema_version == 1, "
            f"got {reconciled_doc.get('schema_version')!r}"
        )

    if reconciled_doc.get("subject") != expected_subject:
        raise PhenixRetainedVerificationError(
            "phenix_reconciled_manifest.subject: disagrees with preregistered "
            f"subject specification for {subject_id!r}"
        )
    if reconciled_doc.get("mtz") != expected_mtz:
        raise PhenixRetainedVerificationError(
            "phenix_reconciled_manifest.mtz: disagrees with preregistered 1SAR MTZ specification"
        )

    staged_files = reconciled_doc.get("staged_files")
    if (
        not isinstance(staged_files, Mapping)
        or set(staged_files.keys()) != _REQUIRED_STAGED_FILES_KEYS
    ):
        raise PhenixRetainedVerificationError(
            "phenix_reconciled_manifest.staged_files: must be a mapping with exact keys "
            f"{sorted(_REQUIRED_STAGED_FILES_KEYS)}"
        )

    inputs_dir = attempt_root / "inputs"
    loaded_pdb = load_retained_reference(
        resolved_admitted_root,
        staged_files,
        path_key="original_model_pdb",
        sha256_key="original_model_pdb_sha256",
        size_bytes_key=None,
        label="staged_files.original_model_pdb",
    )
    if Path(loaded_pdb["verified_reference"]["path"]) != inputs_dir / "original_model.pdb":
        raise PhenixRetainedVerificationError(
            "staged_files.original_model_pdb: expected path "
            f"{inputs_dir / 'original_model.pdb'}, got {loaded_pdb['verified_reference']['path']}"
        )
    if loaded_pdb["verified_reference"]["sha256"] != expected_subject["sha256"]:
        raise PhenixRetainedVerificationError(
            "staged_files.original_model_pdb: sha256 disagrees with preregistered "
            f"subject {subject_id!r} digest {expected_subject['sha256']}"
        )

    loaded_orig_mtz = load_retained_reference(
        resolved_admitted_root,
        staged_files,
        path_key="original_data_mtz",
        sha256_key="original_data_mtz_sha256",
        size_bytes_key=None,
        label="staged_files.original_data_mtz",
    )
    if Path(loaded_orig_mtz["verified_reference"]["path"]) != inputs_dir / "original_data.mtz":
        raise PhenixRetainedVerificationError(
            "staged_files.original_data_mtz: expected path "
            f"{inputs_dir / 'original_data.mtz'}, got {loaded_orig_mtz['verified_reference']['path']}"
        )
    if loaded_orig_mtz["verified_reference"]["sha256"] != onesar_rerun.MTZ_SHA256:
        raise PhenixRetainedVerificationError(
            "staged_files.original_data_mtz: sha256 disagrees with preregistered "
            f"1SAR MTZ digest {onesar_rerun.MTZ_SHA256}"
        )

    loaded_proj_mtz = load_retained_reference(
        resolved_admitted_root,
        staged_files,
        path_key="projected_observations_mtz",
        sha256_key="projected_observations_mtz_sha256",
        size_bytes_key=None,
        label="staged_files.projected_observations_mtz",
    )
    if (
        Path(loaded_proj_mtz["verified_reference"]["path"])
        != inputs_dir / "projected_observations.mtz"
    ):
        raise PhenixRetainedVerificationError(
            "staged_files.projected_observations_mtz: expected path "
            f"{inputs_dir / 'projected_observations.mtz'}, got "
            f"{loaded_proj_mtz['verified_reference']['path']}"
        )

    loaded_ledger = load_retained_reference(
        resolved_admitted_root,
        staged_files,
        path_key="input_hkl_ledger_json",
        sha256_key="input_hkl_ledger_json_sha256",
        size_bytes_key=None,
        parse_json=True,
        label="staged_files.input_hkl_ledger_json",
    )
    if (
        Path(loaded_ledger["verified_reference"]["path"])
        != inputs_dir / "input_hkl_ledger.json"
    ):
        raise PhenixRetainedVerificationError(
            "staged_files.input_hkl_ledger_json: expected path "
            f"{inputs_dir / 'input_hkl_ledger.json'}, got "
            f"{loaded_ledger['verified_reference']['path']}"
        )
    if (
        reconciled_doc.get("input_hkl_ledger_json_path")
        != loaded_ledger["verified_reference"]["path"]
        or reconciled_doc.get("input_hkl_ledger_json_sha256")
        != loaded_ledger["verified_reference"]["sha256"]
    ):
        raise PhenixRetainedVerificationError(
            "phenix_reconciled_manifest: top-level input_hkl_ledger_json_path/sha256 "
            "disagrees with staged_files.input_hkl_ledger_json"
        )

    try:
        reprojected_mtz_bytes, projection_summary = onesar_rerun.project_observation_mtz(
            loaded_orig_mtz["bytes"],
            labels=onesar_rerun.OBSERVATION_LABELS,
            flag_values=onesar_rerun.DECLARED_FLAG_VALUES,
            free_value=onesar_rerun.FREE_FLAG_VALUE,
        )
    except Exception as exc:
        raise PhenixRetainedVerificationError(
            f"project_observation_mtz: failed on staged original_data.mtz ({exc})"
        ) from exc

    if (
        reprojected_mtz_bytes != loaded_proj_mtz["bytes"]
        or projection_summary.get("input_sha256")
        != loaded_orig_mtz["verified_reference"]["sha256"]
        or projection_summary.get("projected_sha256")
        != loaded_proj_mtz["verified_reference"]["sha256"]
        or projection_summary.get("retention_audit", {}).get("audit_status")
        != "preserved"
    ):
        raise PhenixRetainedVerificationError(
            "staged_files.projected_observations_mtz: retained bytes or digest "
            "disagree with pure observation-only MTZ projection from original_data.mtz"
        )

    try:
        rebuilt_ledger = onesar_rerun.build_input_hkl_ledger(
            loaded_proj_mtz["bytes"],
            labels=onesar_rerun.OBSERVATION_LABELS,
            flag_values=onesar_rerun.DECLARED_FLAG_VALUES,
            free_value=onesar_rerun.FREE_FLAG_VALUE,
        )
        rebuilt_ledger_norm = json.loads(
            json.dumps(rebuilt_ledger, sort_keys=True, allow_nan=False)
        )
    except Exception as exc:
        raise PhenixRetainedVerificationError(
            f"build_input_hkl_ledger: failed on staged projected_observations.mtz ({exc})"
        ) from exc

    if (
        rebuilt_ledger_norm.get("mtz_sha256")
        != loaded_proj_mtz["verified_reference"]["sha256"]
        or rebuilt_ledger_norm != loaded_ledger["json"]
    ):
        raise PhenixRetainedVerificationError(
            "staged_files.input_hkl_ledger_json: retained ledger disagrees with "
            "pure rebuild from projected_observations.mtz"
        )

    loaded_preflight = load_retained_reference(
        resolved_admitted_root,
        reconciled_doc,
        path_key="preflight_build_evidence_json_path",
        sha256_key="preflight_build_evidence_sha256",
        size_bytes_key=None,
        parse_json=True,
        label="preflight_build_evidence_json",
    )
    if (
        Path(loaded_preflight["verified_reference"]["path"])
        != phenix_dir / "phenix_preflight_build_evidence.json"
    ):
        raise PhenixRetainedVerificationError(
            "preflight_build_evidence_json: expected path "
            f"{phenix_dir / 'phenix_preflight_build_evidence.json'}, got "
            f"{loaded_preflight['verified_reference']['path']}"
        )
    try:
        validated_preflight = onesar_rerun.validate_measured_phenix_build(
            loaded_preflight["json"],
            expected_version=toolchain.PHENIX_VERSION,
        )
    except ValueError as exc:
        raise PhenixRetainedVerificationError(
            f"validate_measured_phenix_build (preflight): {exc}"
        ) from exc

    expected_resolved_prefix = validated_preflight["resolved_prefix"]
    resolved_prefix_path = _ensure_no_symlink_chain_to_directory(
        Path(expected_resolved_prefix),
        label="measured_build.resolved_prefix",
    )

    preflight_probe = loaded_preflight["json"].get("version_probe")
    assert isinstance(preflight_probe, Mapping)
    loaded_setup_script = load_retained_reference(
        resolved_prefix_path,
        preflight_probe,
        path_key="setup_resolved_path",
        sha256_key="setup_sha256",
        size_bytes_key=None,
        label="measured_build.version_probe.setup",
    )
    loaded_version_dispatcher = load_retained_reference(
        resolved_prefix_path,
        preflight_probe,
        path_key="resolved_path",
        sha256_key="sha256",
        size_bytes_key=None,
        label="measured_build.version_probe.dispatcher",
    )

    loaded_cache_manifest = load_retained_reference(
        resolved_admitted_root,
        reconciled_doc,
        path_key="manifest_path",
        sha256_key="manifest_sha256",
        size_bytes_key=None,
        parse_json=True,
        label="cache_operation_manifest",
    )
    cache_manifest_path = Path(loaded_cache_manifest["verified_reference"]["path"])
    if cache_manifest_path == reconciled_path:
        raise PhenixRetainedVerificationError(
            "cache_operation_manifest: manifest_path must point to cache bundle/success.json, "
            "never phenix_reconciled_manifest.json"
        )
    if (
        cache_manifest_path.name != "success.json"
        or cache_manifest_path.parent.name != "bundle"
    ):
        raise PhenixRetainedVerificationError(
            "cache_operation_manifest: expected cache manifest at "
            f"<destination>/bundle/success.json, got {cache_manifest_path}"
        )
    bundle_dir = cache_manifest_path.parent
    destination_dir = bundle_dir.parent
    operation_dir = destination_dir.parent
    cache_namespace_dir = operation_dir.parent
    expected_operation_name = f"onesar_phenix_first_block_rfactors_{subject_id}"
    if (
        cache_namespace_dir != phenix_dir / "cache" / "refinement_cache_v1"
        or operation_dir.name != expected_operation_name
    ):
        raise PhenixRetainedVerificationError(
            "cache_operation_manifest: unexpected cache hierarchy for "
            f"{cache_manifest_path} (expected under "
            f"{phenix_dir / 'cache' / 'refinement_cache_v1' / expected_operation_name})"
        )

    cache_manifest_doc = loaded_cache_manifest["json"]
    assert isinstance(cache_manifest_doc, dict)
    if cache_manifest_doc != reconciled_doc.get("operation_manifest"):
        raise PhenixRetainedVerificationError(
            "phenix_reconciled_manifest.operation_manifest: disagrees with reopened "
            "cache bundle/success.json"
        )
    if (
        type(cache_manifest_doc.get("returncode")) is not int
        or cache_manifest_doc["returncode"] != 0
        or cache_manifest_doc.get("reusable") is not True
    ):
        raise PhenixRetainedVerificationError(
            "cache_operation_manifest: expected returncode == 0 and reusable is True, "
            f"got returncode={cache_manifest_doc.get('returncode')!r}, "
            f"reusable={cache_manifest_doc.get('reusable')!r}"
        )

    raw_invocation = cache_manifest_doc.get("invocation")
    if not isinstance(raw_invocation, Mapping):
        raise PhenixRetainedVerificationError(
            "cache_operation_manifest.invocation: must be a mapping"
        )
    try:
        validated_cache_build = onesar_rerun.validate_measured_phenix_build(
            raw_invocation.get("measured_build", {}),
            expected_version=toolchain.PHENIX_VERSION,
        )
    except ValueError as exc:
        raise PhenixRetainedVerificationError(
            f"validate_measured_phenix_build (cache_manifest): {exc}"
        ) from exc

    if (
        validated_cache_build["build_info"] != validated_preflight["build_info"]
        or validated_cache_build["resolved_prefix"] != expected_resolved_prefix
    ):
        raise PhenixRetainedVerificationError(
            "cache_operation_manifest.invocation.measured_build: drifted from "
            "preflight PHENIX build evidence"
        )

    raw_inputs = raw_invocation.get("inputs")
    expected_input_keys = {
        "model_pdb",
        "projected_observations_mtz",
        "helper_script",
        "parameters_json",
        *onesar_rerun.PHENIX_VENDOR_SOURCE_RELPATHS.keys(),
    }
    if not isinstance(raw_inputs, Mapping) or set(raw_inputs.keys()) != expected_input_keys:
        raise PhenixRetainedVerificationError(
            "cache_operation_manifest.invocation.inputs: must be a mapping with exact keys "
            f"{sorted(expected_input_keys)}"
        )
    for input_key, input_val in raw_inputs.items():
        if not isinstance(input_val, Mapping) or set(input_val.keys()) != {"path", "sha256"}:
            raise PhenixRetainedVerificationError(
                f"cache_operation_manifest.invocation.inputs.{input_key}: must be a mapping "
                "with exact keys {'path', 'sha256'}"
            )

    loaded_params = load_retained_reference(
        resolved_admitted_root,
        raw_inputs["parameters_json"],
        size_bytes_key=None,
        parse_json=True,
        label="invocation.inputs.parameters_json",
    )
    if (
        Path(loaded_params["verified_reference"]["path"])
        != phenix_dir / "phenix_operation_parameters.json"
    ):
        raise PhenixRetainedVerificationError(
            "invocation.inputs.parameters_json: expected path "
            f"{phenix_dir / 'phenix_operation_parameters.json'}, got "
            f"{loaded_params['verified_reference']['path']}"
        )
    params_doc = loaded_params["json"]
    assert isinstance(params_doc, dict)
    try:
        onesar_phenix_measure.validate_parameters_contract(params_doc)
    except ValueError as exc:
        raise PhenixRetainedVerificationError(
            f"validate_parameters_contract: {exc}"
        ) from exc
    if (
        type(params_doc.get("schema_version")) is not int
        or params_doc.get("schema_version") != 1
        or params_doc.get("subject_id") != subject_id
        or params_doc.get("expected_resolved_prefix") != expected_resolved_prefix
        or params_doc.get("expected_phenix_version") != toolchain.PHENIX_VERSION
    ):
        raise PhenixRetainedVerificationError(
            "phenix_operation_parameters.json: metadata binding mismatch "
            f"(schema_version={params_doc.get('schema_version')!r}, "
            f"subject_id={params_doc.get('subject_id')!r}, "
            f"expected_resolved_prefix={params_doc.get('expected_resolved_prefix')!r}, "
            f"expected_phenix_version={params_doc.get('expected_phenix_version')!r})"
        )

    expected_helper_path = resolved_repo_root / "scripts" / "onesar_phenix_measure.py"
    loaded_helper = load_retained_reference(
        resolved_repo_root,
        raw_inputs["helper_script"],
        size_bytes_key=None,
        label="invocation.inputs.helper_script",
    )
    if Path(loaded_helper["verified_reference"]["path"]) != expected_helper_path:
        raise PhenixRetainedVerificationError(
            "invocation.inputs.helper_script: expected repository helper path "
            f"{expected_helper_path}, got {loaded_helper['verified_reference']['path']}"
        )
    if loaded_helper["verified_reference"]["size_bytes"] <= 0:
        raise PhenixRetainedVerificationError(
            "invocation.inputs.helper_script: helper script must be non-empty"
        )

    try:
        resolved_vendor_sources = onesar_rerun.resolve_phenix_vendor_source_files(
            resolved_prefix_path
        )
    except Exception as exc:
        raise PhenixRetainedVerificationError(
            f"resolve_phenix_vendor_source_files: {exc}"
        ) from exc

    loaded_vendor_modules: dict[str, dict[str, Any]] = {}
    expected_vendor_source_sha256: dict[str, str] = {}
    expected_vendor_module_paths: dict[str, Path] = {}
    for mod_key, expected_mod_path in resolved_vendor_sources.items():
        loaded_mod = load_retained_reference(
            resolved_prefix_path,
            raw_inputs[mod_key],
            size_bytes_key=None,
            label=f"invocation.inputs.{mod_key}",
        )
        if Path(loaded_mod["verified_reference"]["path"]) != expected_mod_path:
            raise PhenixRetainedVerificationError(
                f"invocation.inputs.{mod_key}: path {loaded_mod['verified_reference']['path']} "
                f"disagrees with resolved vendor module {expected_mod_path}"
            )
        if loaded_mod["verified_reference"]["size_bytes"] <= 0:
            raise PhenixRetainedVerificationError(
                f"invocation.inputs.{mod_key}: vendor source file must be non-empty"
            )
        loaded_vendor_modules[mod_key] = loaded_mod
        expected_vendor_source_sha256[mod_key] = loaded_mod["verified_reference"]["sha256"]
        expected_vendor_module_paths[mod_key] = expected_mod_path

    raw_launcher = raw_invocation.get("launcher")
    if (
        not isinstance(raw_launcher, Mapping)
        or set(raw_launcher.keys()) != {"configured_path", "path", "sha256"}
        or not isinstance(raw_launcher.get("configured_path"), str)
        or not raw_launcher["configured_path"].strip()
    ):
        raise PhenixRetainedVerificationError(
            "invocation.launcher: must be a mapping with keys "
            "{'configured_path', 'path', 'sha256'}"
        )
    loaded_launcher = load_retained_reference(
        resolved_prefix_path,
        raw_launcher,
        size_bytes_key=None,
        label="invocation.launcher",
    )
    launcher_resolved_path = Path(loaded_launcher["verified_reference"]["path"])
    launcher_configured_path = Path(raw_launcher["configured_path"])
    if (
        launcher_resolved_path.name != "phenix.python"
        or launcher_configured_path.name != "phenix.python"
        or launcher_resolved_path.parent
        not in {
            resolved_prefix_path,
            resolved_prefix_path / "bin",
            resolved_prefix_path / "phenix_bin",
        }
        or not launcher_configured_path.is_absolute()
    ):
        raise PhenixRetainedVerificationError(
            f"invocation.launcher: invalid PHENIX python launcher {raw_launcher!r} "
            f"under {resolved_prefix_path}"
        )
    try:
        if launcher_configured_path.resolve(strict=True) != launcher_resolved_path:
            raise PhenixRetainedVerificationError(
                f"invocation.launcher: configured_path {launcher_configured_path} "
                f"does not resolve to {launcher_resolved_path}"
            )
    except OSError as exc:
        raise PhenixRetainedVerificationError(
            f"invocation.launcher: failed to resolve configured_path {launcher_configured_path} ({exc})"
        ) from exc

    expected_invocation_inputs = {
        "model_pdb": {
            "path": loaded_pdb["verified_reference"]["path"],
            "sha256": loaded_pdb["verified_reference"]["sha256"],
        },
        "projected_observations_mtz": {
            "path": loaded_proj_mtz["verified_reference"]["path"],
            "sha256": loaded_proj_mtz["verified_reference"]["sha256"],
        },
        "helper_script": {
            "path": loaded_helper["verified_reference"]["path"],
            "sha256": loaded_helper["verified_reference"]["sha256"],
        },
        "parameters_json": {
            "path": loaded_params["verified_reference"]["path"],
            "sha256": loaded_params["verified_reference"]["sha256"],
        },
        **{
            mod_key: {
                "path": item["verified_reference"]["path"],
                "sha256": item["verified_reference"]["sha256"],
            }
            for mod_key, item in loaded_vendor_modules.items()
        },
    }
    expected_argv_template = [
        {"literal": loaded_launcher["verified_reference"]["path"]},
        {"literal": loaded_helper["verified_reference"]["path"]},
        {"literal": "--pdb"},
        {"literal": loaded_pdb["verified_reference"]["path"]},
        {"literal": "--mtz"},
        {"literal": loaded_proj_mtz["verified_reference"]["path"]},
        {"literal": "--params-json"},
        {"literal": loaded_params["verified_reference"]["path"]},
        {"literal": "--out-json"},
        {"output_template": "{operation_dir}/phenix_rfactors.json"},
        {"literal": "--out-maps-mtz"},
        {"output_template": "{operation_dir}/phx_maps.mtz"},
        {"literal": "--out-obs-pair-mtz"},
        {"output_template": "{operation_dir}/PHX_OBS_PAIR_ONLY.mtz"},
        {"literal": "--out-diagnostics-json"},
        {"output_template": "{operation_dir}/phenix_diagnostics.json"},
        {"literal": "--out-partial-json"},
        {"output_template": "{operation_dir}/phenix_rfactors_partial_evidence.json"},
    ]
    expected_invocation_raw = {
        "contract": 1,
        "name": expected_operation_name,
        "inputs": expected_invocation_inputs,
        "launcher": {
            "configured_path": str(launcher_configured_path),
            "path": loaded_launcher["verified_reference"]["path"],
            "sha256": loaded_launcher["verified_reference"]["sha256"],
        },
        "measured_build": validated_preflight["build_info"],
        "argv_template": expected_argv_template,
        "required_outputs": dict(_EXPECTED_PHENIX_REQUIRED_OUTPUTS),
    }
    expected_invocation_serialized = json.dumps(
        expected_invocation_raw, sort_keys=True, allow_nan=False
    )
    expected_invocation = json.loads(expected_invocation_serialized)
    expected_cache_key = hashlib.sha256(
        expected_invocation_serialized.encode("utf-8")
    ).hexdigest()

    if dict(raw_invocation) != expected_invocation:
        raise PhenixRetainedVerificationError(
            "cache_operation_manifest.invocation: disagrees with independently "
            "constructed expected invocation contract"
        )
    if destination_dir.name != expected_cache_key:
        raise PhenixRetainedVerificationError(
            f"cache_operation_manifest: cache directory key {destination_dir.name!r} "
            f"disagrees with expected invocation SHA-256 {expected_cache_key!r}"
        )

    invocation_json_path = bundle_dir / "invocation.json"
    try:
        inv_st = os.lstat(invocation_json_path)
    except OSError as exc:
        raise PhenixRetainedVerificationError(
            f"cache_bundle.invocation_json: missing or inaccessible at {invocation_json_path} ({exc})"
        ) from exc
    if stat.S_ISLNK(inv_st.st_mode) or not stat.S_ISREG(inv_st.st_mode):
        raise PhenixRetainedVerificationError(
            f"cache_bundle.invocation_json: must be a regular non-symlink file at {invocation_json_path}"
        )
    invocation_json_sha256 = hashlib.sha256(invocation_json_path.read_bytes()).hexdigest()
    loaded_invocation_json = load_retained_reference(
        resolved_admitted_root,
        path=invocation_json_path,
        sha256=invocation_json_sha256,
        size_bytes_key=None,
        parse_json=True,
        label="cache_bundle.invocation_json",
    )
    if loaded_invocation_json["json"] != expected_invocation:
        raise PhenixRetainedVerificationError(
            "cache_bundle.invocation_json: disagrees with expected invocation contract"
        )

    try:
        cache_verified_paths = refinement_cache._read_success(
            destination_dir, expected_invocation
        )
    except Exception as exc:
        raise PhenixRetainedVerificationError(
            f"refinement_cache._read_success: {exc}"
        ) from exc

    manifest_artifacts = cache_manifest_doc.get("artifacts")
    if (
        not isinstance(manifest_artifacts, Mapping)
        or set(manifest_artifacts.keys()) != set(_EXPECTED_PHENIX_BUNDLE_RELPATHS.keys())
    ):
        raise PhenixRetainedVerificationError(
            "cache_operation_manifest.artifacts: must be a mapping with exact keys "
            f"{sorted(_EXPECTED_PHENIX_BUNDLE_RELPATHS.keys())}"
        )

    loaded_bundle_artifacts: dict[str, dict[str, Any]] = {}
    for role, expected_rel_name in _EXPECTED_PHENIX_BUNDLE_RELPATHS.items():
        art_entry = manifest_artifacts.get(role)
        if (
            not isinstance(art_entry, Mapping)
            or set(art_entry.keys()) != {"path", "sha256"}
            or art_entry.get("path") != expected_rel_name
        ):
            raise PhenixRetainedVerificationError(
                f"cache_operation_manifest.artifacts.{role}: expected bundle-relative "
                f"path {expected_rel_name!r} with sha256, got {art_entry!r}"
            )
        loaded_art = load_retained_reference(
            resolved_admitted_root,
            path=bundle_dir / expected_rel_name,
            sha256=art_entry["sha256"],
            size_bytes_key=None,
            parse_json=role in ("phenix_rfactors_json", "phenix_diagnostics_json"),
            label=f"cache_operation_manifest.artifacts.{role}",
        )
        if role != "stdout" and loaded_art["verified_reference"]["size_bytes"] <= 0:
            raise PhenixRetainedVerificationError(
                f"cache_operation_manifest.artifacts.{role}: required output must be non-empty"
            )
        if Path(loaded_art["verified_reference"]["path"]) != cache_verified_paths.get(role):
            raise PhenixRetainedVerificationError(
                f"cache_operation_manifest.artifacts.{role}: path disagrees with "
                "refinement_cache._read_success"
            )
        loaded_bundle_artifacts[role] = loaded_art

    expected_cache_artifacts_map = {
        "manifest": loaded_cache_manifest["verified_reference"]["path"],
        **{
            role: item["verified_reference"]["path"]
            for role, item in loaded_bundle_artifacts.items()
        },
    }
    if reconciled_doc.get("cache_artifacts") != expected_cache_artifacts_map:
        raise PhenixRetainedVerificationError(
            "phenix_reconciled_manifest.cache_artifacts: disagrees with verified "
            "cache bundle artifact paths"
        )

    top_level_path_bindings = (
        ("stdout_log_path", "stdout"),
        ("phenix_rfactors_json_path", "phenix_rfactors_json"),
        ("phenix_diagnostics_json_path", "phenix_diagnostics_json"),
        ("phx_maps_mtz_path", "phx_maps_mtz"),
        ("phx_obs_pair_only_mtz_path", "phx_obs_pair_only_mtz"),
    )
    for field_name, role in top_level_path_bindings:
        if (
            reconciled_doc.get(field_name)
            != loaded_bundle_artifacts[role]["verified_reference"]["path"]
        ):
            raise PhenixRetainedVerificationError(
                f"phenix_reconciled_manifest.{field_name}: disagrees with verified "
                f"cache bundle artifact {role!r}"
            )

    expected_partial_path = bundle_dir / "phenix_rfactors_partial_evidence.json"
    partial_path_val = reconciled_doc.get("phenix_partial_evidence_json_path")
    partial_sha_val = reconciled_doc.get("phenix_partial_evidence_sha256")
    loaded_partial_evidence: dict[str, Any] | None = None
    if partial_path_val is None and partial_sha_val is None:
        if os.path.lexists(expected_partial_path):
            raise PhenixRetainedVerificationError(
                "phenix_reconciled_manifest: partial evidence path/sha256 are None "
                f"but {expected_partial_path} exists on disk"
            )
    elif partial_path_val is not None and partial_sha_val is not None:
        loaded_partial_evidence = load_retained_reference(
            resolved_admitted_root,
            reconciled_doc,
            path_key="phenix_partial_evidence_json_path",
            sha256_key="phenix_partial_evidence_sha256",
            size_bytes_key=None,
            parse_json=True,
            label="phenix_partial_evidence_json",
        )
        if (
            Path(loaded_partial_evidence["verified_reference"]["path"])
            != expected_partial_path
        ):
            raise PhenixRetainedVerificationError(
                "phenix_partial_evidence_json: expected path "
                f"{expected_partial_path}, got "
                f"{loaded_partial_evidence['verified_reference']['path']}"
            )
        partial_doc = loaded_partial_evidence["json"]
        assert isinstance(partial_doc, dict)
        if (
            partial_doc.get("status") != "completed_superseded_by_verified_payload"
            or partial_doc.get("failure") is not None
            or partial_doc.get("nonfinite_raw_values") not in (None, [])
        ):
            raise PhenixRetainedVerificationError(
                "phenix_partial_evidence_json: partial checkpoint is not a clean "
                "completed_superseded_by_verified_payload record "
                f"(status={partial_doc.get('status')!r}, failure={partial_doc.get('failure')!r})"
            )
    else:
        raise PhenixRetainedVerificationError(
            "phenix_reconciled_manifest: phenix_partial_evidence_json_path and "
            "phenix_partial_evidence_sha256 must either both be None or both be set"
        )

    phenix_payload = loaded_bundle_artifacts["phenix_rfactors_json"]["json"]
    assert isinstance(phenix_payload, dict)
    diagnostics_payload = loaded_bundle_artifacts["phenix_diagnostics_json"]["json"]
    assert isinstance(diagnostics_payload, dict)

    try:
        fresh_reconciliation = onesar_rerun.reconcile_phenix_rfactor_output(
            phenix_payload,
            rebuilt_ledger_norm,
            expected_vendor_source_sha256=expected_vendor_source_sha256,
            expected_vendor_module_paths=expected_vendor_module_paths,
            expected_resolved_prefix=expected_resolved_prefix,
            expected_phenix_version=toolchain.PHENIX_VERSION,
            measured_build=validated_preflight["build_info"],
            phx_maps_mtz_path=Path(
                loaded_bundle_artifacts["phx_maps_mtz"]["verified_reference"]["path"]
            ),
            phx_maps_mtz_bytes=loaded_bundle_artifacts["phx_maps_mtz"]["bytes"],
            phx_obs_pair_only_mtz_path=Path(
                loaded_bundle_artifacts["phx_obs_pair_only_mtz"]["verified_reference"]["path"]
            ),
            phx_obs_pair_only_mtz_bytes=loaded_bundle_artifacts["phx_obs_pair_only_mtz"]["bytes"],
            phenix_diagnostics_path=Path(
                loaded_bundle_artifacts["phenix_diagnostics_json"]["verified_reference"]["path"]
            ),
            phenix_diagnostics_payload=diagnostics_payload,
            cache_manifest_artifacts=manifest_artifacts,
        )
        fresh_reconciliation_norm = json.loads(
            json.dumps(fresh_reconciliation, sort_keys=True, allow_nan=False)
        )
    except Exception as exc:
        raise PhenixRetainedVerificationError(
            f"reconcile_phenix_rfactor_output: {exc}"
        ) from exc

    if fresh_reconciliation_norm.get("reconciliation_status") != "verified":
        raise PhenixRetainedVerificationError(
            "reconcile_phenix_rfactor_output: expected reconciliation_status == 'verified', "
            f"got {fresh_reconciliation_norm.get('reconciliation_status')!r}"
        )
    if fresh_reconciliation_norm != reconciled_doc.get("reconciliation"):
        raise PhenixRetainedVerificationError(
            "phenix_reconciled_manifest.reconciliation: retained reconciliation "
            "summary disagrees with fresh full-precision reconciliation"
        )

    counts = fresh_reconciliation_norm["counts"]
    work_count = counts.get("actual_work_total")
    free_count = counts.get("actual_free_total")
    if (
        type(work_count) is not int
        or work_count <= 0
        or type(free_count) is not int
        or free_count <= 0
    ):
        raise PhenixRetainedVerificationError(
            f"counts: actual_work_total ({work_count!r}) and actual_free_total ({free_count!r}) "
            "must be positive integers"
        )

    actual_work_hkls = _extract_validated_hkl_list(
        phenix_payload.get("actual_work"),
        expected_count=work_count,
        label="phenix_rfactors_json.actual_work",
    )
    actual_free_hkls = _extract_validated_hkl_list(
        phenix_payload.get("actual_free"),
        expected_count=free_count,
        label="phenix_rfactors_json.actual_free",
    )
    work_set = {tuple(hkl) for hkl in actual_work_hkls}
    free_set = {tuple(hkl) for hkl in actual_free_hkls}
    if not work_set.isdisjoint(free_set):
        raise PhenixRetainedVerificationError(
            "phenix_rfactors_json: actual_work and actual_free HKL sets are not disjoint"
        )

    rfactors_summary = fresh_reconciliation_norm["rfactors"]
    r_work = float(rfactors_summary["r_work"])
    r_free = float(rfactors_summary["r_free"])
    r_all = float(rfactors_summary["r_all"])
    r_free_r_work_gap = float(rfactors_summary["r_free_r_work_gap"])
    if not math.isclose(
        r_free - r_work,
        r_free_r_work_gap,
        rel_tol=1e-12,
        abs_tol=1e-12,
    ):
        raise PhenixRetainedVerificationError(
            f"rfactors: r_free_r_work_gap ({r_free_r_work_gap!r}) is not "
            f"coherent with r_free - r_work ({r_free - r_work!r})"
        )

    verified_references: dict[str, Any] = {
        "reconciled_manifest": reconciled_loaded["verified_reference"],
        "staged_files": {
            "original_model_pdb": loaded_pdb["verified_reference"],
            "original_data_mtz": loaded_orig_mtz["verified_reference"],
            "projected_observations_mtz": loaded_proj_mtz["verified_reference"],
            "input_hkl_ledger_json": loaded_ledger["verified_reference"],
        },
        "preflight_build_evidence_json": loaded_preflight["verified_reference"],
        "parameters_json": loaded_params["verified_reference"],
        "cache_operation_manifest": loaded_cache_manifest["verified_reference"],
        "cache_invocation_json": loaded_invocation_json["verified_reference"],
        "cache_artifacts": {
            role: item["verified_reference"]
            for role, item in loaded_bundle_artifacts.items()
        },
        "partial_evidence_json": (
            loaded_partial_evidence["verified_reference"]
            if loaded_partial_evidence is not None
            else None
        ),
        "external_provenance": {
            "helper_script": loaded_helper["verified_reference"],
            "launcher": loaded_launcher["verified_reference"],
            "vendor_setup_script": loaded_setup_script["verified_reference"],
            "vendor_version_dispatcher": loaded_version_dispatcher["verified_reference"],
            "vendor_modules": {
                mod_key: item["verified_reference"]
                for mod_key, item in loaded_vendor_modules.items()
            },
        },
    }

    return {
        "producer": "phenix",
        "verification_status": "verified",
        "admitted_root": str(resolved_admitted_root),
        "evidence_root": str(attempt_root),
        "repo_root": str(resolved_repo_root),
        "subject_id": subject_id,
        "subject": copy.deepcopy(expected_subject),
        "mtz": copy.deepcopy(expected_mtz),
        "reconciled_manifest_path": reconciled_loaded["verified_reference"]["path"],
        "reconciled_manifest_sha256": reconciled_loaded["verified_reference"]["sha256"],
        "manifest_path": loaded_cache_manifest["verified_reference"]["path"],
        "manifest_sha256": loaded_cache_manifest["verified_reference"]["sha256"],
        "measured_build": copy.deepcopy(validated_preflight),
        "parameters": copy.deepcopy(params_doc),
        "rfactors": {
            "r_work": r_work,
            "r_free": r_free,
            "r_all": r_all,
            "r_free_r_work_gap": r_free_r_work_gap,
            "replayed_r_work": float(rfactors_summary["replayed_r_work"]),
            "replayed_r_free": float(rfactors_summary["replayed_r_free"]),
            "replayed_r_all": float(rfactors_summary["replayed_r_all"]),
            "replayed_r_free_r_work_gap": float(
                rfactors_summary["replayed_r_free_r_work_gap"]
            ),
            "work_numerator": float(rfactors_summary["work_numerator"]),
            "work_denominator": float(rfactors_summary["work_denominator"]),
            "free_numerator": float(rfactors_summary["free_numerator"]),
            "free_denominator": float(rfactors_summary["free_denominator"]),
            "all_numerator": float(rfactors_summary["all_numerator"]),
            "all_denominator": float(rfactors_summary["all_denominator"]),
            "scale_k1_w": float(rfactors_summary["scale_k1_w"]),
            "scale_k1_t": float(rfactors_summary["scale_k1_t"]),
            "scale_k1": float(rfactors_summary["scale_k1"]),
        },
        "counts": copy.deepcopy(counts),
        "work_count": work_count,
        "free_count": free_count,
        "actual_work_hkls": actual_work_hkls,
        "actual_free_hkls": actual_free_hkls,
        "intra_phenix_set_differences": copy.deepcopy(
            fresh_reconciliation_norm["set_differences"]
        ),
        "cross_tool_symmetric_differences": None,
        "projection_summary": json.loads(
            json.dumps(projection_summary, sort_keys=True, allow_nan=False)
        ),
        "input_hkl_ledger_summary": {
            "path": loaded_ledger["verified_reference"]["path"],
            "sha256": loaded_ledger["verified_reference"]["sha256"],
            "mtz_sha256": rebuilt_ledger_norm["mtz_sha256"],
            "counts": copy.deepcopy(rebuilt_ledger_norm["counts"]),
            "crystallographic_context": copy.deepcopy(
                rebuilt_ledger_norm["crystallographic_context"]
            ),
        },
        "reconciliation": copy.deepcopy(fresh_reconciliation_norm),
        "verified_references": verified_references,
        "verification_boundaries": {
            "phenix_retained_evidence_verified": True,
            "independent_oracle_cross_check_established": False,
            "refmac_native_proof_established": False,
            "canary_scientific_admission_established": False,
            "eval_or_qds_published": False,
        },
    }


def verify_retained_phenix_rfactor_evidence(
    admitted_root: str | os.PathLike[str],
    *,
    subject_id: str,
    reconciled_manifest_reference: Mapping[str, Any] | None = None,
    reconciled_manifest_path: str | os.PathLike[str] | None = None,
    reconciled_manifest_sha256: str | None = None,
    reconciled_manifest_size_bytes: int | None = None,
    repo_root: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Pure verifier for retained PHENIX first-block R-factor evidence.

    Reopens and validates an externally bound ``phenix_reconciled_manifest.json``
    and its complete staged, preflight, cache-bundle, and supplement artifact chain
    under ``admitted_root`` without invoking PHENIX, ``cached_phenix_operation``,
    or any live build/version probe.
    """
    try:
        return _verify_retained_phenix_rfactor_evidence_impl(
            admitted_root,
            subject_id=subject_id,
            reconciled_manifest_reference=reconciled_manifest_reference,
            reconciled_manifest_path=reconciled_manifest_path,
            reconciled_manifest_sha256=reconciled_manifest_sha256,
            reconciled_manifest_size_bytes=reconciled_manifest_size_bytes,
            repo_root=repo_root,
        )
    except PhenixRetainedVerificationError:
        raise
    except RetainedReferenceError as exc:
        raise PhenixRetainedVerificationError(str(exc)) from exc

