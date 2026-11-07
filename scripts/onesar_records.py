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
from datetime import date, datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
from typing import Any, Mapping, Sequence


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RetainedReferenceError(ValueError):
    """Raised when a retained file reference or artifact fails integrity verification."""


class PhenixRetainedVerificationError(RetainedReferenceError):
    """Raised when retained PHENIX R-factor evidence fails provenance or reconciliation verification."""


class RefmacRetainedVerificationError(RetainedReferenceError):
    """Raised when retained REFMAC R-factor evidence fails provenance, integrity, or admission verification."""


class RefmacScientificAdmissionRefusedError(RefmacRetainedVerificationError):
    """Raised when retained REFMAC R-factor evidence is refused for scientific admission.

    Distinguishes retained file/collector integrity (``integrity_verified``) from
    native scientific proof (``scientific_proof_established=False``) and carries
    structured refusal details for the three unproven native REFMAC premises
    (``effective_hkls_proven``, ``native_bin_membership_proven``,
    ``native_residual_reconstruction_proven``) plus any rejected forged/unsupported
    proof claims.
    """

    def __init__(
        self,
        message: str,
        *,
        refusal_record: Mapping[str, Any],
    ) -> None:
        super().__init__(message)
        copied = copy.deepcopy(dict(refusal_record))
        self.refusal_record: dict[str, Any] = copied
        self.unknown_native_premises: dict[str, dict[str, Any]] = copy.deepcopy(
            dict(copied.get("unknown_native_premises", {}))
        )
        self.refusal_reasons: tuple[str, ...] = tuple(
            str(item) for item in copied.get("refusal_reasons", ())
        )
        self.unsupported_proof_claims: tuple[str, ...] = tuple(
            str(item) for item in copied.get("unsupported_proof_claims", ())
        )
        self.integrity_verified: bool = bool(copied.get("integrity_verified", False))
        self.scientific_proof_established: bool = False
        self.verified_references: dict[str, Any] = copy.deepcopy(
            dict(copied.get("verified_references", {}))
        )


class ParentExecutionBindingError(RetainedReferenceError):
    """Raised when a retained common-parent execution checkpoint or cross-producer binding fails validation."""


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


REFMAC_UNKNOWN_NATIVE_PREMISE_KEYS: tuple[str, ...] = (
    "effective_hkls_proven",
    "native_bin_membership_proven",
    "native_residual_reconstruction_proven",
)

REFMAC_PROOF_TO_REASON_KEYS: tuple[tuple[str, str], ...] = (
    ("effective_hkls_proven", "effective_hkls_unproven_reason"),
    ("native_bin_membership_proven", "native_bin_membership_unproven_reason"),
    (
        "native_residual_reconstruction_proven",
        "native_residual_reconstruction_unproven_reason",
    ),
)

_REFMAC_DEFAULT_UNPROVEN_REASONS: dict[str, str] = {
    "effective_hkls_proven": (
        "Candidate HKLOUT columns/counts do not prove effective REFMAC internal "
        "reflection membership or active-mask exclusions"
    ),
    "native_bin_membership_proven": (
        "HKLOUT does not emit native per-reflection resolution-bin assignments and "
        "candidate d-spacing bin counts do not prove REFMAC native bin membership or "
        "boundary conventions"
    ),
    "native_residual_reconstruction_proven": (
        "Candidate |FP - FC_ALL_LS| / FP ratio does not prove REFMAC internal unweighted "
        "residual denominators, effective active HKL mask, or native shell aggregation"
    ),
}

REFMAC_FALSE_ADMISSION_ELIGIBILITY_KEYS: tuple[str, ...] = (
    "all_preregistered_gates_passed",
    "canonical_eval_qds_eligible",
    "eval_admission_eligible",
    "qds_admission_eligible",
    "canary_admission_eligible",
    "scientific_admission_proven",
)

_REQUIRED_REFMAC_RAW_OUTPUT_FILENAMES: dict[str, str] = {
    "log": "refmac.log",
    "xyzout": "refmac_xyzout.pdb",
    "hklout": "refmac_hklout.mtz",
}

_REQUIRED_REFMAC_LINKED_JSON_SPECS: tuple[tuple[str, str], ...] = (
    ("pre_execution_checkpoint_json", "pre_execution_checkpoint_json_path"),
    ("post_execution_checkpoint_json", "post_execution_checkpoint_json_path"),
    ("parsed_log_json", "parsed_log_json_path"),
    ("xmlout_audit_json", "xmlout_audit_json_path"),
    ("hklout_raw_export_json", "hklout_raw_export_json_path"),
    ("hklout_audit_json", "hklout_audit_json_path"),
    ("xyzout_audit_json", "xyzout_audit_json_path"),
    ("diagnostics_json", "diagnostics_json_path"),
)

_REQUIRED_REFMAC_PREREGISTERED_GATE_KEYS = frozenset(
    {
        "gate_1_immutable_input_and_toolchain_admission",
        "gate_2_native_log_extraction_and_internal_reconciliation",
        "gate_3_effective_hkls_proven",
        "gate_4_native_bin_membership_proven",
        "gate_5_native_residual_reconstruction_proven",
        "gate_6_model_preservation_proven",
    }
)

_REFMAC_UNPROVEN_GATE_TO_PREMISE: dict[str, str] = {
    "gate_3_effective_hkls_proven": "effective_hkls_proven",
    "gate_4_native_bin_membership_proven": "native_bin_membership_proven",
    "gate_5_native_residual_reconstruction_proven": (
        "native_residual_reconstruction_proven"
    ),
}

_REQUIRED_HKLOUT_AUDIT_KEYS: frozenset[str] = frozenset(
    {
        "schema_version",
        "path",
        "raw_export_json",
        "word_hex_convention",
        "status",
        "valid",
        "errors",
        "crystallographic_context",
        "output_layout_summary",
        "one_to_one_hkl_audit",
        "populations",
        "fc_all_ls_audit",
        "effective_hkls_proven",
        "effective_hkls_unproven_reason",
        "native_bin_membership_proven",
        "native_bin_membership_unproven_reason",
        "native_residual_reconstruction_proven",
        "native_residual_reconstruction_unproven_reason",
    }
)

_ALLOWED_HKLOUT_AUDIT_KEYS: frozenset[str] = _REQUIRED_HKLOUT_AUDIT_KEYS

_REQUIRED_REFMAC_OPERATION_MANIFEST_KEYS: frozenset[str] = frozenset(
    {
        "actual_parent_retention_anchor_baseline",
        "actual_parent_retention_anchor_dir",
        "actual_parent_retention_anchor_kind",
        "additional_refmac_dir_files",
        "all_preregistered_gates_passed",
        "audits",
        "canary_admission_eligible",
        "canonical_eval_qds_eligible",
        "child_dir_persistence_failures",
        "collector_stage",
        "diagnostics_json",
        "effective_hkls_proven",
        "effective_hkls_unproven_reason",
        "eval_admission_eligible",
        "evidence_root",
        "failed_stage",
        "failures",
        "helper_sources",
        "hklout_audit_json",
        "hklout_raw_export_json",
        "input_admission_json_path",
        "input_admission_json_sha256",
        "input_hkl_ledger_json_path",
        "input_hkl_ledger_json_sha256",
        "input_immutability",
        "inputs_dir",
        "inspection_errors",
        "intended_parent_retention_dir",
        "invocation",
        "model_preservation_proven",
        "model_preservation_unproven_reason",
        "mtz",
        "native_bin_membership_proven",
        "native_bin_membership_unproven_reason",
        "native_log_diagnostics",
        "native_residual_reconstruction_proven",
        "native_residual_reconstruction_unproven_reason",
        "operation_checks",
        "parent_retention_dir",
        "parent_retention_directory_baseline",
        "parent_retention_directory_post_run",
        "parent_retention_fallback_anchor",
        "parent_retention_used",
        "parsed_log",
        "parsed_log_json",
        "paths",
        "post_execution_checkpoint_json",
        "pre_execution_checkpoint_initial_json",
        "pre_execution_checkpoint_json",
        "pre_execution_checkpoint_post_run",
        "pre_execution_checkpoint_recovery_json",
        "pre_execution_checkpoint_verified",
        "preregistered_gates",
        "publication_history",
        "publication_pair_complete",
        "publication_terminal_failure",
        "qds_admission_eligible",
        "raw_outputs",
        "refmac_dir",
        "refmac_directory_baseline",
        "refmac_directory_post_run",
        "schema_version",
        "scientific_admission_proven",
        "staged_files",
        "status",
        "subject",
        "subject_id",
        "toolchain",
        "unexpected_symlinks",
        "xmlout_audit_json",
        "xyzout_audit_json",
    }
)

_REQUIRED_REFMAC_DIAGNOSTICS_KEYS: frozenset[str] = frozenset(
    {
        "actual_parent_retention_anchor_baseline",
        "actual_parent_retention_anchor_dir",
        "actual_parent_retention_anchor_kind",
        "additional_refmac_dir_files",
        "all_preregistered_gates_passed",
        "audits",
        "canary_admission_eligible",
        "canonical_eval_qds_eligible",
        "child_dir_persistence_failures",
        "collector_stage",
        "effective_hkls_proven",
        "effective_hkls_unproven_reason",
        "eval_admission_eligible",
        "evidence_root",
        "failed_stage",
        "failures",
        "hklout_audit_json",
        "hklout_raw_export_json",
        "input_immutability",
        "inputs_dir",
        "inspection_errors",
        "intended_parent_retention_dir",
        "invocation",
        "log_parse_error",
        "log_utf8_exact",
        "model_preservation_proven",
        "model_preservation_unproven_reason",
        "mtz",
        "native_bin_membership_proven",
        "native_bin_membership_unproven_reason",
        "native_log_diagnostics",
        "native_residual_reconstruction_proven",
        "native_residual_reconstruction_unproven_reason",
        "operation_checks",
        "parent_retention_dir",
        "parent_retention_directory_baseline",
        "parent_retention_directory_post_run",
        "parent_retention_fallback_anchor",
        "parent_retention_used",
        "parsed_log_json",
        "post_execution_checkpoint_json",
        "pre_execution_checkpoint_initial_json",
        "pre_execution_checkpoint_json",
        "pre_execution_checkpoint_post_run",
        "pre_execution_checkpoint_recovery_json",
        "pre_execution_checkpoint_verified",
        "preregistered_gates",
        "publication_history",
        "publication_pair_complete",
        "publication_terminal_failure",
        "qds_admission_eligible",
        "raw_outputs",
        "refmac_dir",
        "refmac_directory_baseline",
        "refmac_directory_post_run",
        "schema_version",
        "scientific_admission_proven",
        "status",
        "subject",
        "subject_id",
        "toolchain",
        "unexpected_symlinks",
        "xmlout_audit_json",
        "xyzout_audit_json",
    }
)


def _admit_and_hash_regular_file_under_root(
    admitted_root: Path,
    target_path: Path,
    *,
    label: str,
) -> tuple[Path, str, int]:
    """Verify lexical containment, symlink-free ancestry, and regular-file identity before reading or hashing bytes."""
    resolved_root = _ensure_no_symlink_chain_to_directory(
        admitted_root, label=f"{label}.admitted_root"
    )
    raw_target_str = os.fspath(target_path)
    raw_target = Path(raw_target_str)
    if ".." in raw_target.parts:
        raise RetainedReferenceError(
            f"{label}: parent-directory traversal ('..') is not permitted in path {raw_target_str!r}"
        )
    candidate_path = (
        raw_target if raw_target.is_absolute() else (resolved_root / raw_target)
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

    open_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(resolved_target, open_flags)
    except OSError as exc:
        raise RetainedReferenceError(
            f"{label}: failed to open retained regular file {resolved_target} "
            f"({type(exc).__name__}): {exc}"
        ) from exc
    try:
        with os.fdopen(fd, "rb") as fh:
            fd_st = os.fstat(fh.fileno())
            if stat.S_ISLNK(fd_st.st_mode) or not stat.S_ISREG(fd_st.st_mode):
                raise RetainedReferenceError(
                    f"{label}: opened descriptor is not a regular file at {resolved_target}"
                )
            if (fd_st.st_dev, fd_st.st_ino) != (leaf_st.st_dev, leaf_st.st_ino):
                raise RetainedReferenceError(
                    f"{label}: file identity changed during open at {resolved_target}"
                )
            raw_bytes = fh.read()
    except RetainedReferenceError:
        raise
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
    actual_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    return resolved_target, actual_sha256, actual_size_bytes


_VERIFIED_ROOT_FALLBACK_DIR_NAME_RE = re.compile(
    r"^refmac_parent_retention\.verified_root_fallback\.[0-9]+(?:\.[0-9]+)?$"
)

_REFMAC_LINKED_JSON_KEYS: tuple[str, ...] = (
    "pre_execution_checkpoint_json",
    "post_execution_checkpoint_json",
    "parsed_log_json",
    "xmlout_audit_json",
    "hklout_raw_export_json",
    "hklout_audit_json",
    "xyzout_audit_json",
    "diagnostics_json",
)


def _resolve_and_validate_refmac_actual_anchor(
    manifest_doc: Mapping[str, Any],
    *,
    attempt_root: Path,
    refmac_dir: Path,
    parent_retention_dir: Path,
    error_cls: type[Exception],
    label_prefix: str,
) -> Path | None:
    """Resolve and validate ``actual_parent_retention_anchor_dir`` and ``actual_parent_retention_anchor_kind``."""
    actual_anchor_raw = manifest_doc.get("actual_parent_retention_anchor_dir")
    actual_anchor_kind = manifest_doc.get("actual_parent_retention_anchor_kind")
    if actual_anchor_raw is None:
        if actual_anchor_kind is not None:
            raise error_cls(
                f"{label_prefix}.actual_parent_retention_anchor_kind: "
                f"expected None when actual_parent_retention_anchor_dir is None, got {actual_anchor_kind!r}"
            )
        return None
    if not isinstance(actual_anchor_raw, str) or not actual_anchor_raw.strip():
        raise error_cls(
            f"{label_prefix}.actual_parent_retention_anchor_dir: "
            f"expected non-empty string path or None, got {actual_anchor_raw!r}"
        )
    try:
        resolved_anchor = _ensure_no_symlink_chain_to_directory(
            Path(actual_anchor_raw),
            label=f"{label_prefix}.actual_parent_retention_anchor_dir",
        )
    except RetainedReferenceError as exc:
        raise error_cls(str(exc)) from exc
    if not resolved_anchor.is_relative_to(attempt_root):
        raise error_cls(
            f"{label_prefix}.actual_parent_retention_anchor_dir: "
            f"{resolved_anchor} is outside attempt root {attempt_root}"
        )
    if actual_anchor_kind == "parent_retention_dir":
        if resolved_anchor != parent_retention_dir:
            raise error_cls(
                f"{label_prefix}.actual_parent_retention_anchor_dir: "
                f"expected {parent_retention_dir} for actual_parent_retention_anchor_kind="
                f"'parent_retention_dir', got {resolved_anchor}"
            )
    elif actual_anchor_kind == "verified_evidence_root_exclusive_dir":
        if (
            resolved_anchor.parent != attempt_root
            or resolved_anchor
            in {
                attempt_root,
                refmac_dir,
                parent_retention_dir,
                attempt_root / "inputs",
            }
            or _VERIFIED_ROOT_FALLBACK_DIR_NAME_RE.match(resolved_anchor.name)
            is None
        ):
            raise error_cls(
                f"{label_prefix}.actual_parent_retention_anchor_dir: "
                f"invalid verified_evidence_root_exclusive_dir anchor {resolved_anchor}"
            )
    else:
        raise error_cls(
            f"{label_prefix}.actual_parent_retention_anchor_kind: "
            f"unexpected anchor kind {actual_anchor_kind!r}"
        )
    return resolved_anchor


def _validate_refmac_publication_pair_complete(
    manifest_doc: Mapping[str, Any],
    diagnostics_doc: Mapping[str, Any] | None = None,
    *,
    require_diagnostics: bool = True,
    error_cls: type[RetainedReferenceError] = RefmacRetainedVerificationError,
) -> None:
    """Require complete, terminal-failure-free publication state on manifest and diagnostics."""
    if manifest_doc.get("publication_pair_complete") is not True:
        raise error_cls(
            "refmac_operation_manifest: refusing incomplete publication pair "
            f"(publication_pair_complete={manifest_doc.get('publication_pair_complete')!r})"
        )
    if "publication_terminal_failure" not in manifest_doc:
        raise error_cls(
            "refmac_operation_manifest: missing required publication_terminal_failure key"
        )
    if manifest_doc["publication_terminal_failure"] is not None:
        raise error_cls(
            "refmac_operation_manifest: refusing manifest with publication_terminal_failure="
            f"{manifest_doc['publication_terminal_failure']!r}"
        )
    if require_diagnostics or diagnostics_doc is not None:
        if not isinstance(diagnostics_doc, Mapping):
            raise error_cls(
                "refmac_diagnostics: refusing missing or non-mapping diagnostics document "
                "for publication pair"
            )
        if diagnostics_doc.get("publication_pair_complete") is not True:
            raise error_cls(
                "refmac_diagnostics: refusing incomplete publication pair "
                f"(publication_pair_complete={diagnostics_doc.get('publication_pair_complete')!r})"
            )
        if "publication_terminal_failure" not in diagnostics_doc:
            raise error_cls(
                "refmac_diagnostics: missing required publication_terminal_failure key"
            )
        if diagnostics_doc["publication_terminal_failure"] is not None:
            raise error_cls(
                "refmac_diagnostics: refusing diagnostics with publication_terminal_failure="
                f"{diagnostics_doc['publication_terminal_failure']!r}"
            )


def _classify_refmac_fallback_failures(
    failures_list: Any,
    *,
    manifest_doc: Mapping[str, Any] | None = None,
    diagnostics_doc: Mapping[str, Any] | None = None,
    attempt_root: Path | None = None,
    refmac_dir: Path | None = None,
    parent_retention_dir: Path | None = None,
    resolved_actual_anchor: Path | None = None,
    reopened_manifest_path: Path | None = None,
    reopened_diagnostics_path: Path | None = None,
) -> tuple[bool, bool, bool]:
    """Return ``(is_supported_fallback_only, has_persist_failure, has_collision_failure)``."""
    if not isinstance(failures_list, list) or not failures_list:
        return False, False, False
    if manifest_doc is not None and (
        manifest_doc.get("publication_pair_complete") is not True
        or "publication_terminal_failure" not in manifest_doc
        or manifest_doc["publication_terminal_failure"] is not None
    ):
        return False, False, False
    if diagnostics_doc is not None and (
        diagnostics_doc.get("publication_pair_complete") is not True
        or "publication_terminal_failure" not in diagnostics_doc
        or diagnostics_doc["publication_terminal_failure"] is not None
    ):
        return False, False, False
    has_persist_failure = False
    has_collision_failure = False
    has_parent_dir_failure = False
    persist_rows: list[Mapping[str, Any]] = []
    parent_dir_rows: list[Mapping[str, Any]] = []
    for fail_item in failures_list:
        if not isinstance(fail_item, Mapping):
            return False, False, False
        stage_name = fail_item.get("failed_stage")
        if stage_name == "persist_collector_artifacts_in_refmac_dir":
            has_persist_failure = True
            persist_rows.append(fail_item)
            continue
        if stage_name == "refmac_raw_outputs":
            bad_outputs = fail_item.get("missing_or_invalid_outputs")
            if (
                isinstance(bad_outputs, list)
                and bad_outputs
                and all(
                    isinstance(bo, Mapping)
                    and isinstance(bo.get("output_key"), str)
                    and bool(bo["output_key"].strip())
                    and bo.get("output_key")
                    not in ("log", "xyzout", "hklout", "xmlout")
                    for bo in bad_outputs
                )
            ):
                has_collision_failure = True
                continue
            return False, False, False
        if stage_name == "verify_parent_retention_directory":
            has_parent_dir_failure = True
            parent_dir_rows.append(fail_item)
            continue
        return False, False, False

    if has_parent_dir_failure:
        if (
            not has_persist_failure
            or len(parent_dir_rows) != 1
            or len(persist_rows) != 1
            or manifest_doc is None
            or diagnostics_doc is None
            or attempt_root is None
            or refmac_dir is None
            or parent_retention_dir is None
            or resolved_actual_anchor is None
            or reopened_manifest_path is None
            or reopened_diagnostics_path is None
        ):
            return False, False, False
        if (
            resolved_actual_anchor.parent != attempt_root
            or resolved_actual_anchor
            in {
                attempt_root,
                refmac_dir,
                parent_retention_dir,
                attempt_root / "inputs",
            }
            or _VERIFIED_ROOT_FALLBACK_DIR_NAME_RE.match(
                resolved_actual_anchor.name
            )
            is None
            or reopened_manifest_path.parent != reopened_diagnostics_path.parent
            or reopened_manifest_path.parent
            not in {refmac_dir, resolved_actual_anchor}
        ):
            return False, False, False
        saw_artifact_in_actual_anchor = (
            reopened_manifest_path.parent == resolved_actual_anchor
            or reopened_diagnostics_path.parent == resolved_actual_anchor
        )
        for linked_key in _REFMAC_LINKED_JSON_KEYS:
            linked_ref = manifest_doc.get(linked_key)
            if not isinstance(linked_ref, Mapping):
                continue
            linked_path_raw = linked_ref.get("path")
            if not isinstance(linked_path_raw, str) or not linked_path_raw.strip():
                return False, False, False
            linked_parent = Path(linked_path_raw).parent
            if linked_parent not in {refmac_dir, resolved_actual_anchor}:
                return False, False, False
            if linked_parent == resolved_actual_anchor:
                saw_artifact_in_actual_anchor = True
                if (
                    linked_ref.get("actual_retention_anchor_kind")
                    != "verified_evidence_root_exclusive_dir"
                    or linked_ref.get("actual_retention_anchor_dir")
                    != str(resolved_actual_anchor)
                    or linked_ref.get("intended_parent_retention_dir")
                    != str(parent_retention_dir)
                    or linked_ref.get(
                        "fallback_for_unwritable_or_damaged_child_dir"
                    )
                    is not True
                    or linked_ref.get(
                        "fallback_for_damaged_or_replaced_parent_retention_dir"
                    )
                    is not True
                ):
                    return False, False, False
        if not saw_artifact_in_actual_anchor:
            return False, False, False
        if (
            manifest_doc.get("actual_parent_retention_anchor_kind")
            != "verified_evidence_root_exclusive_dir"
            or manifest_doc.get("actual_parent_retention_anchor_dir")
            != str(resolved_actual_anchor)
            or manifest_doc.get("intended_parent_retention_dir")
            != str(parent_retention_dir)
        ):
            return False, False, False
        anchor_baseline = manifest_doc.get(
            "actual_parent_retention_anchor_baseline"
        )
        fb_anchor = manifest_doc.get("parent_retention_fallback_anchor")
        parent_post = manifest_doc.get("parent_retention_directory_post_run")
        refmac_post = manifest_doc.get("refmac_directory_post_run")
        op_checks = manifest_doc.get("operation_checks")
        child_failures = manifest_doc.get("child_dir_persistence_failures")
        if (
            not isinstance(anchor_baseline, Mapping)
            or anchor_baseline.get("path") != str(resolved_actual_anchor)
            or anchor_baseline.get("resolved_path")
            != str(resolved_actual_anchor)
            or anchor_baseline.get("evidence_root") != str(attempt_root)
            or anchor_baseline.get("evidence_root_resolved_path")
            != str(attempt_root)
            or not isinstance(fb_anchor, Mapping)
            or fb_anchor.get("used") is not True
            or fb_anchor.get("evidence_root_verified") is not True
            or fb_anchor.get("no_verified_anchor_available") is not False
            or fb_anchor.get("evidence_root_failure_reason") is not None
            or fb_anchor.get("unpersisted_reason") is not None
            or fb_anchor.get("actual_anchor_kind")
            != "verified_evidence_root_exclusive_dir"
            or fb_anchor.get("actual_anchor_dir")
            != str(resolved_actual_anchor)
            or fb_anchor.get("failed_intended_parent_retention_dir")
            != str(parent_retention_dir)
            or not isinstance(
                fb_anchor.get("parent_retention_dir_failure_reason"), str
            )
            or not fb_anchor["parent_retention_dir_failure_reason"].strip()
            or fb_anchor.get("actual_anchor_baseline") != anchor_baseline
            or not isinstance(parent_post, Mapping)
            or (
                parent_post.get("identity_verified") is not False
                and parent_post.get("writable_post_run") is not False
            )
            or not isinstance(refmac_post, Mapping)
            or (
                refmac_post.get("identity_verified") is not False
                and refmac_post.get("writable_post_run") is not False
            )
            or not isinstance(op_checks, Mapping)
            or (
                op_checks.get("parent_retention_dir_identity_verified")
                is not False
                and op_checks.get("parent_retention_dir_writable_post_run")
                is not False
            )
            or op_checks.get("parent_retention_dir_identity_verified")
            is not bool(parent_post.get("identity_verified"))
            or op_checks.get("parent_retention_dir_writable_post_run")
            is not bool(parent_post.get("writable_post_run"))
            or (
                op_checks.get("refmac_dir_identity_verified") is not False
                and op_checks.get("refmac_dir_writable_post_run")
                is not False
            )
            or not isinstance(child_failures, list)
            or not child_failures
        ):
            return False, False, False
        p_row = parent_dir_rows[0]
        c_row = persist_rows[0]
        if (
            p_row.get("intended_parent_retention_dir")
            != str(parent_retention_dir)
            or p_row.get("parent_retention_directory_post_run") != parent_post
            or p_row.get("parent_retention_fallback_anchor") != fb_anchor
            or not isinstance(p_row.get("exception_type"), str)
            or not p_row["exception_type"].strip()
            or not isinstance(p_row.get("exception_message"), str)
            or not p_row["exception_message"].strip()
            or c_row.get("actual_parent_retention_anchor_kind")
            != "verified_evidence_root_exclusive_dir"
            or c_row.get("actual_parent_retention_anchor_dir")
            != str(resolved_actual_anchor)
            or c_row.get("actual_parent_retention_anchor_baseline")
            != anchor_baseline
            or c_row.get("intended_parent_retention_dir")
            != str(parent_retention_dir)
            or c_row.get("parent_retention_dir") != str(parent_retention_dir)
            or c_row.get("parent_retention_directory_post_run") != parent_post
            or c_row.get("refmac_directory_post_run") != refmac_post
            or c_row.get("parent_retention_fallback_anchor") != fb_anchor
            or c_row.get("child_dir_persistence_failures") != child_failures
        ):
            return False, False, False
    elif manifest_doc is not None:
        fb_anchor = manifest_doc.get("parent_retention_fallback_anchor")
        if (
            manifest_doc.get("actual_parent_retention_anchor_kind")
            == "verified_evidence_root_exclusive_dir"
            or (isinstance(fb_anchor, Mapping) and bool(fb_anchor.get("used")))
            or reopened_manifest_path is None
            or reopened_diagnostics_path is None
        ):
            return False, False, False
        if has_persist_failure:
            if (
                refmac_dir is None
                or parent_retention_dir is None
                or resolved_actual_anchor != parent_retention_dir
                or manifest_doc.get("actual_parent_retention_anchor_kind")
                != "parent_retention_dir"
                or manifest_doc.get("actual_parent_retention_anchor_dir")
                != str(parent_retention_dir)
                or reopened_manifest_path.parent
                != reopened_diagnostics_path.parent
                or reopened_manifest_path.parent
                not in {refmac_dir, parent_retention_dir}
            ):
                return False, False, False
            saw_artifact_in_parent_retention = (
                reopened_manifest_path.parent == parent_retention_dir
                or reopened_diagnostics_path.parent == parent_retention_dir
            )
            for linked_key in _REFMAC_LINKED_JSON_KEYS:
                linked_ref = manifest_doc.get(linked_key)
                if not isinstance(linked_ref, Mapping):
                    continue
                linked_path_raw = linked_ref.get("path")
                if (
                    not isinstance(linked_path_raw, str)
                    or not linked_path_raw.strip()
                ):
                    return False, False, False
                linked_parent = Path(linked_path_raw).parent
                if linked_parent not in {refmac_dir, parent_retention_dir}:
                    return False, False, False
                if linked_parent == parent_retention_dir:
                    saw_artifact_in_parent_retention = True
            if not saw_artifact_in_parent_retention:
                return False, False, False
        else:
            if (
                refmac_dir is None
                or resolved_actual_anchor is not None
                or manifest_doc.get("actual_parent_retention_anchor_kind")
                is not None
                or manifest_doc.get("actual_parent_retention_anchor_dir")
                is not None
                or reopened_manifest_path.parent != refmac_dir
                or reopened_diagnostics_path.parent != refmac_dir
            ):
                return False, False, False

    return True, has_persist_failure, has_collision_failure


def _load_refmac_verification_deps() -> tuple[Any, Any, Any]:
    """Import pure REFMAC verification dependencies lazily to avoid import-time cycles."""
    scripts_dir = Path(__file__).resolve().parent
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import onesar_refmac
    import onesar_rerun
    import toolchain

    return onesar_refmac, onesar_rerun, toolchain


def _select_refmac_manifest_reference(
    manifest_reference: Any,
    *,
    manifest_path: str | os.PathLike[str] | None,
    manifest_sha256: str | None,
    manifest_size_bytes: int | None,
    label: str = "refmac_operation_manifest",
) -> Mapping[str, Any] | None:
    """Validate and extract the persisted REFMAC manifest reference, refusing payload-only records."""
    if isinstance(manifest_reference, Exception):
        raise RefmacRetainedVerificationError(
            f"{label}: refusing collector exception {type(manifest_reference).__name__} "
            "at retained reference boundary (diagnostic-only failure record)"
        )
    if manifest_reference is None:
        return None
    if not isinstance(manifest_reference, Mapping):
        raise RefmacRetainedVerificationError(
            f"{label}: manifest_reference must be a mapping when provided, "
            f"got {type(manifest_reference).__name__}"
        )

    if manifest_reference.get("persisted") is False:
        unpersisted_reason = (
            manifest_reference.get("unpersisted_reason")
            or manifest_reference.get("child_dir_persistence_error")
            or "artifact record reports persisted=False"
        )
        raise RefmacRetainedVerificationError(
            f"{label}: refusing payload-only or unpersisted REFMAC artifact reference "
            f"({unpersisted_reason})"
        )

    if "manifest_json" in manifest_reference:
        if manifest_reference.get("publication_pair_complete") is False:
            raise RefmacRetainedVerificationError(
                f"{label}: refusing REFMAC collector record with publication_pair_complete=False"
            )
        if manifest_reference.get("publication_terminal_failure") is not None:
            raise RefmacRetainedVerificationError(
                f"{label}: refusing REFMAC collector record with publication_terminal_failure="
                f"{manifest_reference.get('publication_terminal_failure')!r}"
            )
        nested = manifest_reference.get("manifest_json")
        if not isinstance(nested, Mapping):
            raise RefmacRetainedVerificationError(
                f"{label}: refusing payload-only or unpersisted REFMAC collector record "
                f"(manifest_json={nested!r})"
            )
        if nested.get("persisted") is False:
            unpersisted_reason = (
                nested.get("unpersisted_reason")
                or nested.get("child_dir_persistence_error")
                or "manifest_json reports persisted=False"
            )
            raise RefmacRetainedVerificationError(
                f"{label}: refusing payload-only or unpersisted REFMAC manifest_json "
                f"({unpersisted_reason})"
            )
        return nested

    if (
        "path" not in manifest_reference
        and manifest_path is None
        and (
            "collector_stage" in manifest_reference
            or "raw_outputs" in manifest_reference
            or "diagnostics_json" in manifest_reference
            or "operation_checks" in manifest_reference
        )
    ):
        raise RefmacRetainedVerificationError(
            f"{label}: refusing payload-only in-memory REFMAC manifest dictionary without "
            "persisted file reference (explicit path and sha256 are required)"
        )

    return manifest_reference


def _verify_staged_inputs_and_admission_for_attempt(
    resolved_admitted_root: Path,
    attempt_root: Path,
    *,
    subject_id: str,
    expected_subject: Mapping[str, Any],
    expected_mtz: Mapping[str, Any],
    staged_files: Any,
    admission_reference: Mapping[str, Any] | None,
    admission_path: str | os.PathLike[str] | None,
    admission_sha256: str | None,
    admission_path_key: str = "path",
    admission_sha256_key: str = "sha256",
    resolved_repo_root: Path,
    onesar_rerun: Any,
    error_cls: type[RetainedReferenceError],
    label_prefix: str,
) -> dict[str, Any]:
    """Reopen and verify staged inputs, ``input_admission.json``, and pure MTZ projection/ledger."""
    if (
        not isinstance(staged_files, Mapping)
        or set(staged_files.keys()) != _REQUIRED_STAGED_FILES_KEYS
    ):
        raise error_cls(
            f"{label_prefix}.staged_files: must be a mapping with exact keys "
            f"{sorted(_REQUIRED_STAGED_FILES_KEYS)}"
        )

    inputs_dir = _ensure_no_symlink_chain_to_directory(
        attempt_root / "inputs",
        label=f"{label_prefix}.inputs_dir",
    )

    loaded_pdb = load_retained_reference(
        resolved_admitted_root,
        staged_files,
        path_key="original_model_pdb",
        sha256_key="original_model_pdb_sha256",
        size_bytes_key=None,
        label=f"{label_prefix}.staged_files.original_model_pdb",
    )
    if (
        Path(loaded_pdb["verified_reference"]["path"])
        != inputs_dir / "original_model.pdb"
    ):
        raise error_cls(
            f"{label_prefix}.staged_files.original_model_pdb: expected path "
            f"{inputs_dir / 'original_model.pdb'}, got "
            f"{loaded_pdb['verified_reference']['path']}"
        )
    if loaded_pdb["verified_reference"]["sha256"] != expected_subject["sha256"]:
        raise error_cls(
            f"{label_prefix}.staged_files.original_model_pdb: sha256 disagrees with "
            f"preregistered subject {subject_id!r} digest {expected_subject['sha256']}"
        )

    loaded_orig_mtz = load_retained_reference(
        resolved_admitted_root,
        staged_files,
        path_key="original_data_mtz",
        sha256_key="original_data_mtz_sha256",
        size_bytes_key=None,
        label=f"{label_prefix}.staged_files.original_data_mtz",
    )
    if (
        Path(loaded_orig_mtz["verified_reference"]["path"])
        != inputs_dir / "original_data.mtz"
    ):
        raise error_cls(
            f"{label_prefix}.staged_files.original_data_mtz: expected path "
            f"{inputs_dir / 'original_data.mtz'}, got "
            f"{loaded_orig_mtz['verified_reference']['path']}"
        )
    if loaded_orig_mtz["verified_reference"]["sha256"] != onesar_rerun.MTZ_SHA256:
        raise error_cls(
            f"{label_prefix}.staged_files.original_data_mtz: sha256 disagrees with "
            f"preregistered 1SAR MTZ digest {onesar_rerun.MTZ_SHA256}"
        )

    loaded_proj_mtz = load_retained_reference(
        resolved_admitted_root,
        staged_files,
        path_key="projected_observations_mtz",
        sha256_key="projected_observations_mtz_sha256",
        size_bytes_key=None,
        label=f"{label_prefix}.staged_files.projected_observations_mtz",
    )
    if (
        Path(loaded_proj_mtz["verified_reference"]["path"])
        != inputs_dir / "projected_observations.mtz"
    ):
        raise error_cls(
            f"{label_prefix}.staged_files.projected_observations_mtz: expected path "
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
        label=f"{label_prefix}.staged_files.input_hkl_ledger_json",
    )
    if (
        Path(loaded_ledger["verified_reference"]["path"])
        != inputs_dir / "input_hkl_ledger.json"
    ):
        raise error_cls(
            f"{label_prefix}.staged_files.input_hkl_ledger_json: expected path "
            f"{inputs_dir / 'input_hkl_ledger.json'}, got "
            f"{loaded_ledger['verified_reference']['path']}"
        )

    loaded_admission = load_retained_reference(
        resolved_admitted_root,
        admission_reference,
        path=admission_path,
        sha256=admission_sha256,
        path_key=admission_path_key,
        sha256_key=admission_sha256_key,
        size_bytes_key=(
            "size_bytes"
            if isinstance(admission_reference, Mapping)
            and "size_bytes" in admission_reference
            else None
        ),
        parse_json=True,
        label=f"{label_prefix}.input_admission_json",
    )
    if (
        Path(loaded_admission["verified_reference"]["path"])
        != inputs_dir / "input_admission.json"
    ):
        raise error_cls(
            f"{label_prefix}.input_admission_json: expected path "
            f"{inputs_dir / 'input_admission.json'}, got "
            f"{loaded_admission['verified_reference']['path']}"
        )
    admission_doc = loaded_admission["json"]
    assert isinstance(admission_doc, dict)
    expected_admission_keys = {
        "schema_version",
        "archive",
        "subject",
        "mtz",
        "staged_files",
        "projection",
        "input_ledger_counts",
    }
    if set(admission_doc.keys()) != expected_admission_keys:
        raise error_cls(
            f"{label_prefix}.input_admission_json: top-level key mismatch "
            f"(expected {sorted(expected_admission_keys)}, got {sorted(admission_doc.keys())})"
        )
    if (
        type(admission_doc.get("schema_version")) is not int
        or admission_doc["schema_version"] != 1
    ):
        raise error_cls(
            f"{label_prefix}.input_admission_json: expected integer schema_version == 1, "
            f"got {admission_doc.get('schema_version')!r}"
        )
    expected_archive_path = str(resolved_repo_root / onesar_rerun.ARCHIVE_REL_PATH)
    expected_archive_block = {
        "archive_id": onesar_rerun.ARCHIVE_ID,
        "archive_path": expected_archive_path,
        "archive_sha256": onesar_rerun.ARCHIVE_SHA256,
    }
    if admission_doc.get("archive") != expected_archive_block:
        raise error_cls(
            f"{label_prefix}.input_admission_json.archive: disagrees with preregistered "
            f"1SAR archive specification {expected_archive_block}"
        )
    if admission_doc.get("subject") != expected_subject:
        raise error_cls(
            f"{label_prefix}.input_admission_json.subject: disagrees with preregistered "
            f"subject specification for {subject_id!r}"
        )
    if admission_doc.get("mtz") != expected_mtz:
        raise error_cls(
            f"{label_prefix}.input_admission_json.mtz: disagrees with preregistered "
            "1SAR MTZ specification"
        )
    if admission_doc.get("staged_files") != dict(staged_files):
        raise error_cls(
            f"{label_prefix}.input_admission_json.staged_files: disagrees with manifest staged_files"
        )

    try:
        reprojected_mtz_bytes, projection_summary = onesar_rerun.project_observation_mtz(
            loaded_orig_mtz["bytes"],
            labels=onesar_rerun.OBSERVATION_LABELS,
            flag_values=onesar_rerun.DECLARED_FLAG_VALUES,
            free_value=onesar_rerun.FREE_FLAG_VALUE,
        )
        projection_summary_norm = json.loads(
            json.dumps(projection_summary, sort_keys=True, allow_nan=False)
        )
    except Exception as exc:
        raise error_cls(
            f"{label_prefix}.project_observation_mtz: failed on staged original_data.mtz ({exc})"
        ) from exc

    if (
        reprojected_mtz_bytes != loaded_proj_mtz["bytes"]
        or projection_summary_norm.get("input_sha256")
        != loaded_orig_mtz["verified_reference"]["sha256"]
        or projection_summary_norm.get("projected_sha256")
        != loaded_proj_mtz["verified_reference"]["sha256"]
        or projection_summary_norm.get("retention_audit", {}).get("audit_status")
        != "preserved"
        or admission_doc.get("projection") != projection_summary_norm
    ):
        raise error_cls(
            f"{label_prefix}.staged_files.projected_observations_mtz: retained bytes, "
            "digest, or input_admission.json projection summary disagree with pure "
            "observation-only MTZ projection from original_data.mtz"
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
        raise error_cls(
            f"{label_prefix}.build_input_hkl_ledger: failed on staged projected_observations.mtz ({exc})"
        ) from exc

    if (
        rebuilt_ledger_norm.get("mtz_sha256")
        != loaded_proj_mtz["verified_reference"]["sha256"]
        or rebuilt_ledger_norm != loaded_ledger["json"]
        or admission_doc.get("input_ledger_counts")
        != rebuilt_ledger_norm.get("counts")
    ):
        raise error_cls(
            f"{label_prefix}.staged_files.input_hkl_ledger_json: retained ledger or "
            "input_admission.json counts disagree with pure rebuild from "
            "projected_observations.mtz"
        )

    return {
        "inputs_dir": inputs_dir,
        "archive": copy.deepcopy(expected_archive_block),
        "loaded_pdb": loaded_pdb,
        "loaded_orig_mtz": loaded_orig_mtz,
        "loaded_proj_mtz": loaded_proj_mtz,
        "loaded_ledger": loaded_ledger,
        "loaded_admission": loaded_admission,
        "projection_summary": projection_summary_norm,
        "rebuilt_ledger": rebuilt_ledger_norm,
    }


def _collect_refmac_unsupported_proof_claims(
    *,
    manifest_doc: Mapping[str, Any],
    diagnostics_doc: Mapping[str, Any],
    hklout_audit_doc: Mapping[str, Any],
    required_manifest_keys: frozenset[str],
    required_diagnostics_keys: frozenset[str],
    fallback_persisted_status_ok: bool,
) -> list[str]:
    """Identify any forged boolean, forged status string, or unsupported proof carrier key."""
    claims: list[str] = []

    extra_manifest_keys = sorted(set(manifest_doc.keys()) - required_manifest_keys)
    if extra_manifest_keys:
        claims.append(
            f"refmac_operation_manifest contains unexpected/unsupported top-level key(s): {extra_manifest_keys}"
        )
    extra_diag_keys = sorted(set(diagnostics_doc.keys()) - required_diagnostics_keys)
    if extra_diag_keys:
        claims.append(
            f"refmac_diagnostics contains unexpected/unsupported top-level key(s): {extra_diag_keys}"
        )
    extra_hklout_keys = sorted(
        set(hklout_audit_doc.keys()) - _ALLOWED_HKLOUT_AUDIT_KEYS
    )
    if extra_hklout_keys:
        claims.append(
            f"refmac_hklout_audit contains unexpected/unsupported key(s): {extra_hklout_keys}"
        )

    for doc_label, doc in (
        ("refmac_operation_manifest", manifest_doc),
        ("refmac_diagnostics", diagnostics_doc),
    ):
        status_val = doc.get("status")
        if status_val != "diagnostic_captured_gates_unproven" and not (
            status_val == "failed" and fallback_persisted_status_ok
        ):
            claims.append(
                f"{doc_label}.status={status_val!r} claims unsupported non-unproven status "
                "(only 'diagnostic_captured_gates_unproven' has a supported retained contract)"
            )
        for proof_key, reason_key in REFMAC_PROOF_TO_REASON_KEYS:
            if doc.get(proof_key) is not False:
                claims.append(
                    f"{doc_label}.{proof_key}={doc.get(proof_key)!r} "
                    "(must be False; no supported native REFMAC proof contract exists)"
                )
            reason_val = doc.get(reason_key)
            if (
                not isinstance(reason_val, str)
                or not reason_val.strip()
                or reason_val.strip().lower() == "none"
            ):
                claims.append(
                    f"{doc_label}.{reason_key}={reason_val!r} "
                    f"(must be a non-empty unproven reason string for {proof_key})"
                )
        for elig_key in REFMAC_FALSE_ADMISSION_ELIGIBILITY_KEYS:
            if doc.get(elig_key) is not False:
                claims.append(
                    f"{doc_label}.{elig_key}={doc.get(elig_key)!r} "
                    "(must be False; REFMAC diagnostic capture is never eligible for scientific admission)"
                )

        gates = doc.get("preregistered_gates")
        if isinstance(gates, Mapping):
            extra_gate_keys = sorted(
                set(gates.keys()) - _REQUIRED_REFMAC_PREREGISTERED_GATE_KEYS
            )
            if extra_gate_keys:
                claims.append(
                    f"{doc_label}.preregistered_gates contains unexpected gate key(s): {extra_gate_keys}"
                )
            for gate_key, premise_key in _REFMAC_UNPROVEN_GATE_TO_PREMISE.items():
                gate_obj = gates.get(gate_key)
                if isinstance(gate_obj, Mapping):
                    if gate_obj.get("proven") is not False:
                        claims.append(
                            f"{doc_label}.preregistered_gates.{gate_key}.proven="
                            f"{gate_obj.get('proven')!r} (must be False for {premise_key})"
                        )
                    if gate_obj.get("status") != "unproven":
                        claims.append(
                            f"{doc_label}.preregistered_gates.{gate_key}.status="
                            f"{gate_obj.get('status')!r} (must be 'unproven')"
                        )
                    gate_reason = gate_obj.get("reason")
                    if (
                        not isinstance(gate_reason, str)
                        or not gate_reason.strip()
                        or gate_reason.strip().lower() == "none"
                    ):
                        claims.append(
                            f"{doc_label}.preregistered_gates.{gate_key}.reason="
                            f"{gate_reason!r} (must be a non-empty unproven reason string)"
                        )

        audits_obj = doc.get("audits")
        if isinstance(audits_obj, Mapping):
            embedded_hkl = audits_obj.get("hklout_mtz_audit")
            if isinstance(embedded_hkl, Mapping):
                for proof_key, reason_key in REFMAC_PROOF_TO_REASON_KEYS:
                    if embedded_hkl.get(proof_key) is not False:
                        claims.append(
                            f"{doc_label}.audits.hklout_mtz_audit.{proof_key}="
                            f"{embedded_hkl.get(proof_key)!r} (must be False)"
                        )
                    emb_reason = embedded_hkl.get(reason_key)
                    if (
                        not isinstance(emb_reason, str)
                        or not emb_reason.strip()
                        or emb_reason.strip().lower() == "none"
                    ):
                        claims.append(
                            f"{doc_label}.audits.hklout_mtz_audit.{reason_key}="
                            f"{emb_reason!r} (must be a non-empty unproven reason string)"
                        )

    for proof_key, reason_key in REFMAC_PROOF_TO_REASON_KEYS:
        if hklout_audit_doc.get(proof_key) is not False:
            claims.append(
                f"refmac_hklout_audit.{proof_key}={hklout_audit_doc.get(proof_key)!r} "
                "(must be False; HKLOUT cannot prove native REFMAC active mask, bins, or residual reconstruction)"
            )
        hkl_reason = hklout_audit_doc.get(reason_key)
        if (
            not isinstance(hkl_reason, str)
            or not hkl_reason.strip()
            or hkl_reason.strip().lower() == "none"
        ):
            claims.append(
                f"refmac_hklout_audit.{reason_key}={hkl_reason!r} "
                f"(must be a non-empty unproven reason string for {proof_key})"
            )

    return claims


def _verify_retained_refmac_rfactor_evidence_impl(
    admitted_root: str | os.PathLike[str],
    *,
    subject_id: str,
    manifest_reference: Any = None,
    manifest_path: str | os.PathLike[str] | None = None,
    manifest_sha256: str | None = None,
    manifest_size_bytes: int | None = None,
    repo_root: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    onesar_refmac, onesar_rerun, toolchain = _load_refmac_verification_deps()

    try:
        admitted_root_path = Path(os.fspath(admitted_root))
    except TypeError as exc:
        raise RefmacRetainedVerificationError(
            f"admitted_root: must be path-like, got {admitted_root!r}"
        ) from exc
    resolved_admitted_root = _ensure_no_symlink_chain_to_directory(
        admitted_root_path, label="admitted_root"
    )

    try:
        expected_subject = onesar_rerun.resolve_subject_spec(subject_id)
    except ValueError as exc:
        raise RefmacRetainedVerificationError(f"subject_id: {exc}") from exc
    expected_mtz = {
        "member": onesar_rerun.MTZ_MEMBER,
        "sha256": onesar_rerun.MTZ_SHA256,
        "subject_ref": onesar_rerun.MTZ_SUBJECT_REF,
    }

    raw_repo_root = onesar_rerun.REPO_ROOT if repo_root is None else repo_root
    try:
        repo_root_path = Path(os.fspath(raw_repo_root))
    except TypeError as exc:
        raise RefmacRetainedVerificationError(
            f"repo_root: must be path-like, got {raw_repo_root!r}"
        ) from exc
    resolved_repo_root = _ensure_no_symlink_chain_to_directory(
        repo_root_path, label="repo_root"
    )

    active_manifest_ref = _select_refmac_manifest_reference(
        manifest_reference,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        manifest_size_bytes=manifest_size_bytes,
        label="refmac_operation_manifest",
    )
    manifest_size_key = (
        "size_bytes"
        if isinstance(active_manifest_ref, Mapping)
        and "size_bytes" in active_manifest_ref
        else None
    )
    manifest_loaded = load_retained_reference(
        resolved_admitted_root,
        active_manifest_ref,
        path=manifest_path,
        sha256=manifest_sha256,
        size_bytes=manifest_size_bytes,
        size_bytes_key=manifest_size_key,
        parse_json=True,
        label="refmac_operation_manifest",
    )
    manifest_doc = manifest_loaded["json"]
    assert isinstance(manifest_doc, dict)
    reopened_manifest_path = Path(manifest_loaded["verified_reference"]["path"])

    required_manifest_keys = _REQUIRED_REFMAC_OPERATION_MANIFEST_KEYS
    missing_manifest_keys = sorted(required_manifest_keys - set(manifest_doc.keys()))
    if missing_manifest_keys:
        raise RefmacRetainedVerificationError(
            "refmac_operation_manifest: missing required top-level key(s): "
            f"{missing_manifest_keys}"
        )
    if (
        type(manifest_doc.get("schema_version")) is not int
        or manifest_doc["schema_version"] != 1
    ):
        raise RefmacRetainedVerificationError(
            "refmac_operation_manifest: expected integer schema_version == 1, "
            f"got {manifest_doc.get('schema_version')!r}"
        )
    if manifest_doc.get("collector_stage") != onesar_refmac.COLLECTOR_STAGE:
        raise RefmacRetainedVerificationError(
            "refmac_operation_manifest.collector_stage: expected "
            f"{onesar_refmac.COLLECTOR_STAGE!r}, got {manifest_doc.get('collector_stage')!r}"
        )
    _validate_refmac_publication_pair_complete(
        manifest_doc,
        None,
        require_diagnostics=False,
        error_cls=RefmacRetainedVerificationError,
    )

    if manifest_doc.get("subject_id") != subject_id:
        raise RefmacRetainedVerificationError(
            f"refmac_operation_manifest.subject_id: expected {subject_id!r}, "
            f"got {manifest_doc.get('subject_id')!r}"
        )
    if manifest_doc.get("subject") != expected_subject:
        raise RefmacRetainedVerificationError(
            "refmac_operation_manifest.subject: disagrees with preregistered "
            f"subject specification for {subject_id!r}"
        )
    if manifest_doc.get("mtz") != expected_mtz:
        raise RefmacRetainedVerificationError(
            "refmac_operation_manifest.mtz: disagrees with preregistered 1SAR MTZ specification"
        )

    raw_evidence_root = manifest_doc.get("evidence_root")
    if not isinstance(raw_evidence_root, str) or not raw_evidence_root.strip():
        raise RefmacRetainedVerificationError(
            "refmac_operation_manifest.evidence_root: must be a non-empty string path"
        )
    attempt_root = _ensure_no_symlink_chain_to_directory(
        Path(raw_evidence_root),
        label="refmac_operation_manifest.evidence_root",
    )
    if not attempt_root.is_relative_to(resolved_admitted_root):
        raise RefmacRetainedVerificationError(
            f"refmac_operation_manifest.evidence_root: attempt root {attempt_root} is "
            f"outside admitted root {resolved_admitted_root}"
        )

    refmac_dir = _ensure_no_symlink_chain_to_directory(
        attempt_root / "refmac",
        label="refmac_operation_manifest.refmac_dir",
    )
    if (
        manifest_doc.get("actual_parent_retention_anchor_kind")
        == "verified_evidence_root_exclusive_dir"
    ):
        parent_retention_dir = attempt_root / "refmac_parent_retention"
        admitted_retention_dirs: set[Path] = {refmac_dir}
    else:
        parent_retention_dir = _ensure_no_symlink_chain_to_directory(
            attempt_root / "refmac_parent_retention",
            label="refmac_operation_manifest.parent_retention_dir",
        )
        admitted_retention_dirs = {refmac_dir, parent_retention_dir}
    if manifest_doc.get("inputs_dir") != str(attempt_root / "inputs"):
        raise RefmacRetainedVerificationError(
            "refmac_operation_manifest.inputs_dir: expected "
            f"{attempt_root / 'inputs'}, got {manifest_doc.get('inputs_dir')!r}"
        )
    if manifest_doc.get("refmac_dir") != str(refmac_dir):
        raise RefmacRetainedVerificationError(
            f"refmac_operation_manifest.refmac_dir: expected {refmac_dir}, "
            f"got {manifest_doc.get('refmac_dir')!r}"
        )
    if manifest_doc.get("parent_retention_dir") != str(parent_retention_dir):
        raise RefmacRetainedVerificationError(
            f"refmac_operation_manifest.parent_retention_dir: expected {parent_retention_dir}, "
            f"got {manifest_doc.get('parent_retention_dir')!r}"
        )

    resolved_anchor = _resolve_and_validate_refmac_actual_anchor(
        manifest_doc,
        attempt_root=attempt_root,
        refmac_dir=refmac_dir,
        parent_retention_dir=parent_retention_dir,
        error_cls=RefmacRetainedVerificationError,
        label_prefix="refmac_operation_manifest",
    )
    if resolved_anchor is not None:
        admitted_retention_dirs.add(resolved_anchor)

    paths_block = manifest_doc.get("paths")
    if not isinstance(paths_block, Mapping):
        raise RefmacRetainedVerificationError(
            "refmac_operation_manifest.paths: must be a mapping"
        )
    if paths_block.get("manifest_json_path") != str(reopened_manifest_path):
        raise RefmacRetainedVerificationError(
            "refmac_operation_manifest.paths.manifest_json_path: expected "
            f"{reopened_manifest_path}, got {paths_block.get('manifest_json_path')!r}"
        )
    if reopened_manifest_path.parent not in admitted_retention_dirs:
        raise RefmacRetainedVerificationError(
            f"refmac_operation_manifest: reopened path {reopened_manifest_path} does not "
            f"reside in an admitted retention directory of {attempt_root}"
        )

    staged_verified = _verify_staged_inputs_and_admission_for_attempt(
        resolved_admitted_root,
        attempt_root,
        subject_id=subject_id,
        expected_subject=expected_subject,
        expected_mtz=expected_mtz,
        staged_files=manifest_doc.get("staged_files"),
        admission_reference=manifest_doc,
        admission_path=None,
        admission_sha256=None,
        admission_path_key="input_admission_json_path",
        admission_sha256_key="input_admission_json_sha256",
        resolved_repo_root=resolved_repo_root,
        onesar_rerun=onesar_rerun,
        error_cls=RefmacRetainedVerificationError,
        label_prefix="refmac_operation_manifest",
    )
    loaded_pdb = staged_verified["loaded_pdb"]
    loaded_orig_mtz = staged_verified["loaded_orig_mtz"]
    loaded_proj_mtz = staged_verified["loaded_proj_mtz"]
    loaded_ledger = staged_verified["loaded_ledger"]
    loaded_admission = staged_verified["loaded_admission"]

    if (
        manifest_doc.get("input_hkl_ledger_json_path")
        != loaded_ledger["verified_reference"]["path"]
        or manifest_doc.get("input_hkl_ledger_json_sha256")
        != loaded_ledger["verified_reference"]["sha256"]
    ):
        raise RefmacRetainedVerificationError(
            "refmac_operation_manifest: top-level input_hkl_ledger_json_path/sha256 "
            "disagrees with staged_files.input_hkl_ledger_json"
        )
    if (
        paths_block.get("original_pdb_path") != loaded_pdb["verified_reference"]["path"]
        or paths_block.get("original_mtz_path")
        != loaded_orig_mtz["verified_reference"]["path"]
        or paths_block.get("projected_mtz_path")
        != loaded_proj_mtz["verified_reference"]["path"]
        or paths_block.get("input_ledger_path")
        != loaded_ledger["verified_reference"]["path"]
        or paths_block.get("admission_json_path")
        != loaded_admission["verified_reference"]["path"]
    ):
        raise RefmacRetainedVerificationError(
            "refmac_operation_manifest.paths: staged input paths disagree with "
            "verified staged_files and input_admission.json paths"
        )

    immutability = manifest_doc.get("input_immutability")
    if (
        not isinstance(immutability, Mapping)
        or immutability.get("verified") is not True
        or immutability.get("mutations") != []
    ):
        raise RefmacRetainedVerificationError(
            "refmac_operation_manifest.input_immutability: expected verified=True "
            f"and empty mutations list, got {immutability!r}"
        )

    kw_baseline = immutability.get("keywords_file_baseline")
    kw_post = immutability.get("keywords_file_post_run")
    if not isinstance(kw_baseline, Mapping) or not isinstance(kw_post, Mapping):
        raise RefmacRetainedVerificationError(
            "refmac_operation_manifest.input_immutability: missing keywords_file_baseline/post_run"
        )
    loaded_keywords = load_retained_reference(
        resolved_admitted_root,
        kw_baseline,
        label="refmac_keywords_txt",
    )
    expected_keywords_path = refmac_dir / "refmac_keywords.txt"
    if (
        Path(loaded_keywords["verified_reference"]["path"]) != expected_keywords_path
        or paths_block.get("keywords_path") != str(expected_keywords_path)
    ):
        raise RefmacRetainedVerificationError(
            f"refmac_keywords_txt: expected path {expected_keywords_path}, "
            f"got {loaded_keywords['verified_reference']['path']}"
        )
    try:
        keywords_text = loaded_keywords["bytes"].decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise RefmacRetainedVerificationError(
            f"refmac_keywords_txt: invalid UTF-8 content ({exc})"
        ) from exc
    if keywords_text != onesar_refmac.REFMAC_KEYWORDS:
        raise RefmacRetainedVerificationError(
            "refmac_keywords_txt: content disagrees with preregistered REFMAC_KEYWORDS"
        )
    if (
        kw_post.get("matches_baseline") is not True
        or kw_post.get("sha256") != loaded_keywords["verified_reference"]["sha256"]
    ):
        raise RefmacRetainedVerificationError(
            "refmac_operation_manifest.input_immutability.keywords_file_post_run: "
            "failed post-run keywords immutability verification"
        )

    toolchain_block = manifest_doc.get("toolchain")
    if (
        not isinstance(toolchain_block, Mapping)
        or toolchain_block.get("expected_ccp4_version") != toolchain.CCP4_VERSION
        or not isinstance(toolchain_block.get("setup_script"), Mapping)
        or not isinstance(toolchain_block.get("refmac5_binary"), Mapping)
    ):
        raise RefmacRetainedVerificationError(
            "refmac_operation_manifest.toolchain: expected expected_ccp4_version == "
            f"{toolchain.CCP4_VERSION!r} with setup_script and refmac5_binary mappings"
        )

    invocation = manifest_doc.get("invocation")
    if not isinstance(invocation, Mapping):
        raise RefmacRetainedVerificationError(
            "refmac_operation_manifest.invocation: must be a mapping"
        )
    if (
        invocation.get("wrapper") != "toolchain.run_refmac"
        or type(invocation.get("returncode")) is not int
        or invocation.get("returncode") != 0
        or invocation.get("timed_out") is not False
        or invocation.get("launch_or_timeout_failure") is not None
        or invocation.get("completed_argv_available") is not True
        or invocation.get("argv_matches_expected") is not True
    ):
        raise RefmacRetainedVerificationError(
            "refmac_operation_manifest.invocation: REFMAC execution did not complete "
            "cleanly with returncode==0 and verified argv"
        )
    if (
        invocation.get("stdin_keywords") != onesar_refmac.REFMAC_KEYWORDS
        or invocation.get("stdin_keywords_lines")
        != list(onesar_refmac.REFMAC_KEYWORDS_LINES)
        or invocation.get("stdin_keywords_sha256")
        != loaded_keywords["verified_reference"]["sha256"]
        or invocation.get("keywords_file_path") != str(expected_keywords_path)
    ):
        raise RefmacRetainedVerificationError(
            "refmac_operation_manifest.invocation: stdin_keywords or keywords_file_path "
            "disagrees with preregistered NCYC 0 keywords"
        )

    expected_xyzout_path = refmac_dir / "refmac_xyzout.pdb"
    expected_hklout_path = refmac_dir / "refmac_hklout.mtz"
    expected_xmlout_path = refmac_dir / "refmac_xmlout.xml"
    expected_log_path = refmac_dir / "refmac.log"
    if (
        invocation.get("xyzin_path") != loaded_pdb["verified_reference"]["path"]
        or invocation.get("hklin_path") != loaded_proj_mtz["verified_reference"]["path"]
        or invocation.get("xyzout_path") != str(expected_xyzout_path)
        or invocation.get("hklout_path") != str(expected_hklout_path)
        or invocation.get("xmlout_path") != str(expected_xmlout_path)
        or invocation.get("log_path") != str(expected_log_path)
    ):
        raise RefmacRetainedVerificationError(
            "refmac_operation_manifest.invocation: input/output file bindings disagree "
            "with staged inputs or refmac_dir output locations (outputs must never replace inputs)"
        )
    executable_str = invocation.get("executable")
    if not isinstance(executable_str, str) or not executable_str.strip():
        raise RefmacRetainedVerificationError(
            "refmac_operation_manifest.invocation.executable: must be a non-empty string"
        )
    expected_argv = [
        executable_str,
        "XYZIN",
        loaded_pdb["verified_reference"]["path"],
        "HKLIN",
        loaded_proj_mtz["verified_reference"]["path"],
        "XYZOUT",
        str(expected_xyzout_path),
        "HKLOUT",
        str(expected_hklout_path),
        "XMLOUT",
        str(expected_xmlout_path),
    ]
    if (
        invocation.get("expected_argv") != expected_argv
        or invocation.get("completed_argv") != expected_argv
    ):
        raise RefmacRetainedVerificationError(
            "refmac_operation_manifest.invocation: expected_argv/completed_argv "
            "disagrees with bound XYZIN/HKLIN/XYZOUT/HKLOUT/XMLOUT arguments"
        )

    raw_outputs = manifest_doc.get("raw_outputs")
    if not isinstance(raw_outputs, Mapping) or set(raw_outputs.keys()) != {
        "log",
        "xyzout",
        "hklout",
        "xmlout",
    }:
        raise RefmacRetainedVerificationError(
            "refmac_operation_manifest.raw_outputs: must be a mapping with keys "
            "['hklout', 'log', 'xmlout', 'xyzout']"
        )
    loaded_raw_outputs: dict[str, dict[str, Any]] = {}
    for out_key, expected_name in _REQUIRED_REFMAC_RAW_OUTPUT_FILENAMES.items():
        out_entry = raw_outputs.get(out_key)
        loaded_out = load_retained_reference(
            resolved_admitted_root,
            out_entry if isinstance(out_entry, Mapping) else None,
            label=f"raw_outputs.{out_key}",
        )
        expected_out_path = refmac_dir / expected_name
        if (
            Path(loaded_out["verified_reference"]["path"]) != expected_out_path
            or paths_block.get(f"{out_key}_path") != str(expected_out_path)
            or loaded_out["verified_reference"]["size_bytes"] <= 0
        ):
            raise RefmacRetainedVerificationError(
                f"raw_outputs.{out_key}: expected non-empty regular file at {expected_out_path}, "
                f"got {loaded_out['verified_reference']['path']}"
            )
        loaded_raw_outputs[out_key] = loaded_out

    xmlout_entry = raw_outputs.get("xmlout")
    if not isinstance(xmlout_entry, Mapping):
        raise RefmacRetainedVerificationError(
            "raw_outputs.xmlout: must be a mapping"
        )
    loaded_xmlout: dict[str, Any] | None = None
    if xmlout_entry.get("exists") is True:
        loaded_xmlout = load_retained_reference(
            resolved_admitted_root,
            xmlout_entry,
            label="raw_outputs.xmlout",
        )
        if Path(loaded_xmlout["verified_reference"]["path"]) != expected_xmlout_path:
            raise RefmacRetainedVerificationError(
                f"raw_outputs.xmlout: expected path {expected_xmlout_path}, "
                f"got {loaded_xmlout['verified_reference']['path']}"
            )
    elif xmlout_entry.get("exists") is False:
        if (
            xmlout_entry.get("path") != str(expected_xmlout_path)
            or xmlout_entry.get("sha256") is not None
            or xmlout_entry.get("size_bytes") is not None
            or os.path.lexists(expected_xmlout_path)
        ):
            raise RefmacRetainedVerificationError(
                "raw_outputs.xmlout: exists=False record disagrees with path/digest "
                f"or on-disk state at {expected_xmlout_path}"
            )
    else:
        raise RefmacRetainedVerificationError(
            f"raw_outputs.xmlout: expected boolean exists, got {xmlout_entry.get('exists')!r}"
        )

    loaded_linked_jsons: dict[str, dict[str, Any]] = {}
    for json_key, path_field_key in _REQUIRED_REFMAC_LINKED_JSON_SPECS:
        ref_obj = manifest_doc.get(json_key)
        if not isinstance(ref_obj, Mapping):
            raise RefmacRetainedVerificationError(
                f"refmac_operation_manifest.{json_key}: must be a persisted reference mapping"
            )
        loaded_json_item = load_retained_reference(
            resolved_admitted_root,
            ref_obj,
            parse_json=True,
            label=f"refmac_operation_manifest.{json_key}",
        )
        reopened_item_path = Path(loaded_json_item["verified_reference"]["path"])
        if reopened_item_path.parent not in admitted_retention_dirs:
            raise RefmacRetainedVerificationError(
                f"refmac_operation_manifest.{json_key}: reopened path {reopened_item_path} "
                f"is not in an admitted retention directory of {attempt_root}"
            )
        if paths_block.get(path_field_key) != str(reopened_item_path):
            raise RefmacRetainedVerificationError(
                f"refmac_operation_manifest.paths.{path_field_key}: expected "
                f"{reopened_item_path}, got {paths_block.get(path_field_key)!r}"
            )
        loaded_linked_jsons[json_key] = loaded_json_item

    pre_cp_doc = loaded_linked_jsons["pre_execution_checkpoint_json"]["json"]
    post_cp_doc = loaded_linked_jsons["post_execution_checkpoint_json"]["json"]
    parsed_log_doc = loaded_linked_jsons["parsed_log_json"]["json"]
    xmlout_audit_doc = loaded_linked_jsons["xmlout_audit_json"]["json"]
    hklout_raw_doc = loaded_linked_jsons["hklout_raw_export_json"]["json"]
    hklout_audit_doc = loaded_linked_jsons["hklout_audit_json"]["json"]
    xyzout_audit_doc = loaded_linked_jsons["xyzout_audit_json"]["json"]
    diagnostics_doc = loaded_linked_jsons["diagnostics_json"]["json"]
    assert isinstance(pre_cp_doc, dict)
    assert isinstance(post_cp_doc, dict)
    assert isinstance(parsed_log_doc, dict)
    assert isinstance(xmlout_audit_doc, dict)
    assert isinstance(hklout_raw_doc, dict)
    assert isinstance(hklout_audit_doc, dict)
    assert isinstance(xyzout_audit_doc, dict)
    assert isinstance(diagnostics_doc, dict)

    required_diag_keys = _REQUIRED_REFMAC_DIAGNOSTICS_KEYS
    missing_diag_keys = sorted(required_diag_keys - set(diagnostics_doc.keys()))
    if missing_diag_keys:
        raise RefmacRetainedVerificationError(
            f"refmac_diagnostics: missing required top-level key(s): {missing_diag_keys}"
        )
    _validate_refmac_publication_pair_complete(
        manifest_doc,
        diagnostics_doc,
        require_diagnostics=True,
        error_cls=RefmacRetainedVerificationError,
    )

    if (
        pre_cp_doc.get("checkpoint_stage") != "pre_execution"
        or pre_cp_doc.get("subject_id") != subject_id
        or pre_cp_doc.get("subject") != expected_subject
        or pre_cp_doc.get("mtz") != expected_mtz
        or pre_cp_doc.get("staged_files") != manifest_doc.get("staged_files")
        or pre_cp_doc.get("input_admission_json_sha256")
        != loaded_admission["verified_reference"]["sha256"]
    ):
        raise RefmacRetainedVerificationError(
            "pre_execution_checkpoint_json: identity or staged input bindings disagree with manifest"
        )
    if (
        post_cp_doc.get("checkpoint_stage") != "post_execution"
        or post_cp_doc.get("subject_id") != subject_id
        or post_cp_doc.get("subject") != expected_subject
        or post_cp_doc.get("mtz") != expected_mtz
        or post_cp_doc.get("staged_files") != manifest_doc.get("staged_files")
    ):
        raise RefmacRetainedVerificationError(
            "post_execution_checkpoint_json: identity or staged input bindings disagree with manifest"
        )

    op_checks = manifest_doc.get("operation_checks")
    if not isinstance(op_checks, Mapping):
        raise RefmacRetainedVerificationError(
            "refmac_operation_manifest.operation_checks: must be a mapping"
        )
    failures_list = manifest_doc.get("failures")
    if not isinstance(failures_list, list):
        raise RefmacRetainedVerificationError(
            "refmac_operation_manifest.failures: must be a list"
        )
    canonical_linked_names = {
        "pre_execution_checkpoint_json": "refmac_pre_execution_checkpoint.json",
        "post_execution_checkpoint_json": "refmac_post_execution_checkpoint.json",
        "parsed_log_json": "refmac_parsed_log.json",
        "xmlout_audit_json": "refmac_xmlout_audit.json",
        "hklout_raw_export_json": "refmac_hklout_raw_export.json",
        "hklout_audit_json": "refmac_hklout_audit.json",
        "xyzout_audit_json": "refmac_xyzout_audit.json",
        "diagnostics_json": "refmac_diagnostics.json",
    }
    reopened_diagnostics_path = Path(
        loaded_linked_jsons["diagnostics_json"]["verified_reference"]["path"]
    )
    fallback_anchor_meta = manifest_doc.get("parent_retention_fallback_anchor")
    is_any_fallback_ref = bool(
        reopened_manifest_path != refmac_dir / "refmac_operation_manifest.json"
        or manifest_loaded["verified_reference"]["is_fallback"]
        or any(
            item["verified_reference"]["is_fallback"]
            or Path(item["verified_reference"]["path"]).parent != refmac_dir
            or Path(item["verified_reference"]["path"]).name
            != canonical_linked_names[json_key]
            for json_key, item in loaded_linked_jsons.items()
        )
        or manifest_doc.get("parent_retention_used") is True
        or bool(manifest_doc.get("child_dir_persistence_failures"))
        or manifest_doc.get("actual_parent_retention_anchor_dir") is not None
        or manifest_doc.get("actual_parent_retention_anchor_kind") is not None
        or (
            isinstance(fallback_anchor_meta, Mapping)
            and bool(fallback_anchor_meta.get("used"))
        )
    )
    (
        supported_fallback_only,
        has_persist_failure,
        has_collision_failure,
    ) = _classify_refmac_fallback_failures(
        failures_list,
        manifest_doc=manifest_doc,
        diagnostics_doc=diagnostics_doc,
        attempt_root=attempt_root,
        refmac_dir=refmac_dir,
        parent_retention_dir=parent_retention_dir,
        resolved_actual_anchor=resolved_anchor,
        reopened_manifest_path=reopened_manifest_path,
        reopened_diagnostics_path=reopened_diagnostics_path,
    )

    if failures_list and not supported_fallback_only:
        raise RefmacRetainedVerificationError(
            f"refmac_operation_manifest: collector reported failure(s) at "
            f"failed_stage={manifest_doc.get('failed_stage')!r}: {failures_list!r}"
        )
    if failures_list and not is_any_fallback_ref:
        raise RefmacRetainedVerificationError(
            "refmac_operation_manifest: fallback failure stage reported without "
            "retained fallback artifact reference or parent-retention evidence"
        )
    if not failures_list and is_any_fallback_ref:
        raise RefmacRetainedVerificationError(
            "refmac_operation_manifest: relocated clean payload at fallback path or "
            "with fallback metadata is not permitted without producer fallback failure state "
            "(fallback manifest location or metadata requires supported fallback failure stage in failures)"
        )
    fallback_only_failures = bool(supported_fallback_only and is_any_fallback_ref)

    for req_true_check in (
        "preflight_toolchain_resolved",
        "worker_launched",
        "process_returncode_zero",
        "completed_argv_available",
        "argv_matches_expected",
        "pre_execution_checkpoint_verified",
        "native_r_pair_parsed",
        "ncyc_zero_requested_and_echoed",
        "xmlout_audit_valid",
        "hklout_audit_valid",
        "xyzout_audit_valid",
        "input_immutability_verified",
    ):
        if op_checks.get(req_true_check) is not True:
            raise RefmacRetainedVerificationError(
                f"refmac_operation_manifest.operation_checks.{req_true_check}: "
                f"expected True, got {op_checks.get(req_true_check)!r}"
            )

    if fallback_only_failures:
        expected_failed_stage = failures_list[0].get("failed_stage")
        if (
            manifest_doc.get("failed_stage") != expected_failed_stage
            or diagnostics_doc.get("failed_stage") != expected_failed_stage
            or diagnostics_doc.get("failures") != failures_list
            or diagnostics_doc.get("actual_parent_retention_anchor_dir")
            != manifest_doc.get("actual_parent_retention_anchor_dir")
            or diagnostics_doc.get("actual_parent_retention_anchor_kind")
            != manifest_doc.get("actual_parent_retention_anchor_kind")
            or diagnostics_doc.get("intended_parent_retention_dir")
            != manifest_doc.get("intended_parent_retention_dir")
            or diagnostics_doc.get("parent_retention_fallback_anchor")
            != manifest_doc.get("parent_retention_fallback_anchor")
            or diagnostics_doc.get("parent_retention_directory_post_run")
            != manifest_doc.get("parent_retention_directory_post_run")
            or diagnostics_doc.get("refmac_directory_post_run")
            != manifest_doc.get("refmac_directory_post_run")
            or diagnostics_doc.get("child_dir_persistence_failures")
            != manifest_doc.get("child_dir_persistence_failures")
        ):
            raise RefmacRetainedVerificationError(
                "refmac_operation_manifest: inconsistent failed_stage or failures "
                "between manifest and diagnostics for fallback capture"
            )
        if (
            manifest_doc.get("status") == "diagnostic_captured_gates_unproven"
            or diagnostics_doc.get("status") == "diagnostic_captured_gates_unproven"
        ):
            raise RefmacRetainedVerificationError(
                "refmac_operation_manifest: fallback capture cannot claim "
                "status='diagnostic_captured_gates_unproven' (expected 'failed')"
            )
        expected_parent_retention_used = bool(has_persist_failure)
        expected_raw_outputs_regular = not has_collision_failure
        if (
            op_checks.get("collector_succeeded") is not False
            or op_checks.get("stage1_collection_succeeded") is not False
            or type(op_checks.get("stage2_audits_succeeded")) is not bool
            or (
                not has_persist_failure
                and op_checks.get("stage2_audits_succeeded") is not True
            )
            or op_checks.get("parent_retention_used") is not expected_parent_retention_used
            or manifest_doc.get("parent_retention_used")
            is not expected_parent_retention_used
            or diagnostics_doc.get("parent_retention_used")
            is not expected_parent_retention_used
            or op_checks.get("all_raw_outputs_present_and_regular")
            is not expected_raw_outputs_regular
        ):
            raise RefmacRetainedVerificationError(
                "refmac_operation_manifest.operation_checks: inconsistent fallback "
                "summary flags for persisted fallback capture"
            )
    else:
        if (
            manifest_doc.get("failed_stage") is not None
            or diagnostics_doc.get("failed_stage") is not None
            or diagnostics_doc.get("failures") != []
            or manifest_doc.get("parent_retention_used") is not False
            or diagnostics_doc.get("parent_retention_used") is not False
            or manifest_doc.get("actual_parent_retention_anchor_dir") is not None
            or manifest_doc.get("actual_parent_retention_anchor_kind") is not None
            or diagnostics_doc.get("actual_parent_retention_anchor_dir")
            is not None
            or diagnostics_doc.get("actual_parent_retention_anchor_kind")
            is not None
            or op_checks.get("parent_retention_used") is not False
            or op_checks.get("all_raw_outputs_present_and_regular") is not True
            or op_checks.get("stage1_collection_succeeded") is not True
            or op_checks.get("stage2_audits_succeeded") is not True
            or op_checks.get("collector_succeeded") is not True
        ):
            raise RefmacRetainedVerificationError(
                "refmac_operation_manifest: inconsistent failed_stage, "
                "parent_retention_used, or operation_checks for failure-free capture"
            )

    reconciled_final_cycle = parsed_log_doc.get("reconciled_final_cycle")
    if (
        not isinstance(reconciled_final_cycle, Mapping)
        or not isinstance(reconciled_final_cycle.get("r_work"), (int, float))
        or isinstance(reconciled_final_cycle.get("r_work"), bool)
        or not isinstance(reconciled_final_cycle.get("r_free"), (int, float))
        or isinstance(reconciled_final_cycle.get("r_free"), bool)
    ):
        raise RefmacRetainedVerificationError(
            "parsed_log_json: missing finite reconciled_final_cycle r_work/r_free"
        )

    if xmlout_audit_doc.get("valid") is not True:
        raise RefmacRetainedVerificationError(
            f"xmlout_audit_json: expected valid=True, got {xmlout_audit_doc.get('valid')!r}"
        )
    if (
        hklout_raw_doc.get("path") != str(expected_hklout_path)
        or hklout_raw_doc.get("sha256")
        != loaded_raw_outputs["hklout"]["verified_reference"]["sha256"]
        or hklout_raw_doc.get("raw_export_error") is not None
    ):
        raise RefmacRetainedVerificationError(
            "hklout_raw_export_json: path/sha256 mismatch or raw_export_error present"
        )
    hklout_ctx = hklout_audit_doc.get("crystallographic_context")
    if (
        hklout_audit_doc.get("valid") is not True
        or hklout_audit_doc.get("path") != str(expected_hklout_path)
        or not isinstance(hklout_ctx, Mapping)
        or hklout_ctx.get("hklin_verified_post_run") is not True
        or hklout_ctx.get("hklin_baseline_sha256")
        != loaded_proj_mtz["verified_reference"]["sha256"]
        or hklout_ctx.get("hklin_post_run_sha256")
        != loaded_proj_mtz["verified_reference"]["sha256"]
        or hklout_audit_doc.get("raw_export_json")
        != manifest_doc.get("hklout_raw_export_json")
    ):
        raise RefmacRetainedVerificationError(
            "hklout_audit_json: failed validity or HKLOUT/HKLIN/raw_export_json binding check"
        )
    if (
        xyzout_audit_doc.get("valid") is not True
        or xyzout_audit_doc.get("model_preservation_proven") is not True
        or xyzout_audit_doc.get("xyzin_path") != loaded_pdb["verified_reference"]["path"]
        or xyzout_audit_doc.get("xyzin_sha256")
        != loaded_pdb["verified_reference"]["sha256"]
        or xyzout_audit_doc.get("xyzout_path") != str(expected_xyzout_path)
        or xyzout_audit_doc.get("xyzout_sha256")
        != loaded_raw_outputs["xyzout"]["verified_reference"]["sha256"]
    ):
        raise RefmacRetainedVerificationError(
            "xyzout_audit_json: failed validity, model_preservation_proven, or XYZIN/XYZOUT binding check"
        )
    if (
        diagnostics_doc.get("subject_id") != subject_id
        or diagnostics_doc.get("subject") != expected_subject
        or diagnostics_doc.get("mtz") != expected_mtz
        or diagnostics_doc.get("evidence_root") != str(attempt_root)
    ):
        raise RefmacRetainedVerificationError(
            "diagnostics_json: identity or evidence_root disagrees with manifest"
        )

    unsupported_proof_claims = _collect_refmac_unsupported_proof_claims(
        manifest_doc=manifest_doc,
        diagnostics_doc=diagnostics_doc,
        hklout_audit_doc=hklout_audit_doc,
        required_manifest_keys=required_manifest_keys,
        required_diagnostics_keys=required_diag_keys,
        fallback_persisted_status_ok=fallback_only_failures,
    )

    if not unsupported_proof_claims:
        audits_block = manifest_doc.get("audits")
        if (
            not isinstance(audits_block, Mapping)
            or audits_block.get("xmlout_audit") != xmlout_audit_doc
            or audits_block.get("hklout_mtz_audit") != hklout_audit_doc
            or audits_block.get("xyzout_pdb_audit") != xyzout_audit_doc
            or diagnostics_doc.get("audits") != audits_block
        ):
            raise RefmacRetainedVerificationError(
                "refmac_operation_manifest.audits: embedded audits in manifest/diagnostics "
                "disagree with reopened xmlout/hklout/xyzout audit JSON artifacts"
            )
        gates_map = manifest_doc.get("preregistered_gates")
        if not isinstance(gates_map, Mapping):
            raise RefmacRetainedVerificationError(
                "refmac_operation_manifest.preregistered_gates: must be a mapping"
            )
        gate_2_entry = gates_map.get(
            "gate_2_native_log_extraction_and_internal_reconciliation"
        )
        if not isinstance(gate_2_entry, Mapping) or gate_2_entry.get("proven") is not True:
            raise RefmacRetainedVerificationError(
                "refmac_operation_manifest.preregistered_gates."
                "gate_2_native_log_extraction_and_internal_reconciliation: "
                f"expected proven=True, got {gate_2_entry!r}"
            )
        gate_1_entry = gates_map.get(
            "gate_1_immutable_input_and_toolchain_admission"
        )
        gate_6_entry = gates_map.get("gate_6_model_preservation_proven")
        if fallback_only_failures:
            expected_gate_1_proven = not has_persist_failure
            if (
                not isinstance(gate_1_entry, Mapping)
                or gate_1_entry.get("proven") is not expected_gate_1_proven
            ):
                raise RefmacRetainedVerificationError(
                    "refmac_operation_manifest.preregistered_gates."
                    "gate_1_immutable_input_and_toolchain_admission: "
                    f"expected proven={expected_gate_1_proven!r}, got {gate_1_entry!r}"
                )
            mp_reason = manifest_doc.get("model_preservation_unproven_reason")
            diag_mp_reason = diagnostics_doc.get("model_preservation_unproven_reason")
            if (
                manifest_doc.get("model_preservation_proven") is not False
                or diagnostics_doc.get("model_preservation_proven") is not False
                or not isinstance(mp_reason, str)
                or not mp_reason.strip()
                or not isinstance(diag_mp_reason, str)
                or not diag_mp_reason.strip()
                or not isinstance(gate_6_entry, Mapping)
                or gate_6_entry.get("proven") is not False
                or gate_6_entry.get("status") != "unproven"
                or not isinstance(gate_6_entry.get("reason"), str)
                or not gate_6_entry["reason"].strip()
            ):
                raise RefmacRetainedVerificationError(
                    "refmac_operation_manifest: persisted fallback capture must "
                    "retain public model_preservation_proven=False and "
                    "gate_6_model_preservation_proven.proven=False"
                )
        else:
            if (
                manifest_doc.get("model_preservation_proven") is not True
                or diagnostics_doc.get("model_preservation_proven") is not True
                or manifest_doc.get("model_preservation_unproven_reason") is not None
                or diagnostics_doc.get("model_preservation_unproven_reason") is not None
            ):
                raise RefmacRetainedVerificationError(
                    "refmac_operation_manifest.model_preservation_proven: expected "
                    "True with None unproven_reason for failure-free capture"
                )
            for gate_req_true in (
                "gate_1_immutable_input_and_toolchain_admission",
                "gate_6_model_preservation_proven",
            ):
                gate_entry = gates_map.get(gate_req_true)
                if not isinstance(gate_entry, Mapping) or gate_entry.get("proven") is not True:
                    raise RefmacRetainedVerificationError(
                        f"refmac_operation_manifest.preregistered_gates.{gate_req_true}: "
                        f"expected proven=True, got {gate_entry!r}"
                    )

    unknown_native_premises: dict[str, dict[str, Any]] = {}
    refusal_reasons: list[str] = []
    for proof_key, reason_key in REFMAC_PROOF_TO_REASON_KEYS:
        raw_reason = hklout_audit_doc.get(reason_key) or manifest_doc.get(reason_key)
        selected_reason = (
            raw_reason.strip()
            if isinstance(raw_reason, str)
            and raw_reason.strip()
            and raw_reason.strip().lower() != "none"
            and hklout_audit_doc.get(proof_key) is False
            and manifest_doc.get(proof_key) is False
            and diagnostics_doc.get(proof_key) is False
            else _REFMAC_DEFAULT_UNPROVEN_REASONS[proof_key]
        )
        unknown_native_premises[proof_key] = {
            "proven": False,
            "unproven_reason": selected_reason,
            "manifest_claimed_value": manifest_doc.get(proof_key),
            "diagnostics_claimed_value": diagnostics_doc.get(proof_key),
            "hklout_audit_claimed_value": hklout_audit_doc.get(proof_key),
        }
        refusal_reasons.append(f"{proof_key}=False: {selected_reason}")

    if unsupported_proof_claims:
        refusal_reasons.append(
            "Unsupported or forged REFMAC proof claim(s) rejected (no supported "
            "successful aggregate native REFMAC proof contract exists): "
            + "; ".join(unsupported_proof_claims)
        )

    integrity_verified = len(unsupported_proof_claims) == 0
    verified_references: dict[str, Any] = {
        "refmac_operation_manifest": manifest_loaded["verified_reference"],
        "staged_files": {
            "original_model_pdb": loaded_pdb["verified_reference"],
            "original_data_mtz": loaded_orig_mtz["verified_reference"],
            "projected_observations_mtz": loaded_proj_mtz["verified_reference"],
            "input_hkl_ledger_json": loaded_ledger["verified_reference"],
        },
        "input_admission_json": loaded_admission["verified_reference"],
        "refmac_keywords_txt": loaded_keywords["verified_reference"],
        "raw_outputs": {
            "log": loaded_raw_outputs["log"]["verified_reference"],
            "xyzout": loaded_raw_outputs["xyzout"]["verified_reference"],
            "hklout": loaded_raw_outputs["hklout"]["verified_reference"],
            "xmlout": (
                loaded_xmlout["verified_reference"]
                if loaded_xmlout is not None
                else None
            ),
        },
        **{
            json_key: item["verified_reference"]
            for json_key, item in loaded_linked_jsons.items()
        },
    }

    public_model_preservation_proven = bool(
        not fallback_only_failures
        and manifest_doc.get("model_preservation_proven") is True
        and xyzout_audit_doc.get("model_preservation_proven") is True
    )
    refusal_record: dict[str, Any] = {
        "producer": "refmac",
        "verification_status": (
            "refused_unsupported_proof_claim"
            if unsupported_proof_claims
            else "diagnostic_captured_scientific_admission_refused"
        ),
        "admitted_root": str(resolved_admitted_root),
        "evidence_root": str(attempt_root),
        "repo_root": str(resolved_repo_root),
        "subject_id": subject_id,
        "subject": copy.deepcopy(expected_subject),
        "mtz": copy.deepcopy(expected_mtz),
        "archive": copy.deepcopy(staged_verified["archive"]),
        "manifest_path": manifest_loaded["verified_reference"]["path"],
        "manifest_sha256": manifest_loaded["verified_reference"]["sha256"],
        "manifest_status": manifest_doc.get("status"),
        "manifest_failed_stage": manifest_doc.get("failed_stage"),
        "manifest_failures": copy.deepcopy(failures_list),
        "fallback_persistence_used": fallback_only_failures,
        "actual_parent_retention_anchor_dir": manifest_doc.get(
            "actual_parent_retention_anchor_dir"
        ),
        "actual_parent_retention_anchor_kind": manifest_doc.get(
            "actual_parent_retention_anchor_kind"
        ),
        "diagnostics_path": loaded_linked_jsons["diagnostics_json"][
            "verified_reference"
        ]["path"],
        "diagnostics_sha256": loaded_linked_jsons["diagnostics_json"][
            "verified_reference"
        ]["sha256"],
        "integrity_verified": integrity_verified,
        "scientific_proof_established": False,
        "unknown_native_premises": unknown_native_premises,
        "unsupported_proof_claims": list(unsupported_proof_claims),
        "refusal_reasons": refusal_reasons,
        "verified_references": verified_references,
        "verification_boundaries": {
            "refmac_retained_evidence_integrity_verified": integrity_verified,
            "effective_hkls_proven": False,
            "native_bin_membership_proven": False,
            "native_residual_reconstruction_proven": False,
            "model_preservation_proven": public_model_preservation_proven,
            "xyzout_audit_model_preservation_proven": bool(
                xyzout_audit_doc.get("model_preservation_proven") is True
            ),
            "scientific_admission_proven": False,
            "canary_scientific_admission_established": False,
            "eval_or_qds_published": False,
        },
    }
    raise RefmacScientificAdmissionRefusedError(
        "REFMAC scientific admission refused: native active reflection mask "
        "(effective_hkls_proven), native resolution-bin membership "
        "(native_bin_membership_proven), and native residual reconstruction "
        "(native_residual_reconstruction_proven) remain unproven ("
        + "; ".join(refusal_reasons)
        + ")",
        refusal_record=refusal_record,
    )


def verify_retained_refmac_rfactor_evidence(
    admitted_root: str | os.PathLike[str],
    *,
    subject_id: str,
    manifest_reference: Any = None,
    manifest_path: str | os.PathLike[str] | None = None,
    manifest_sha256: str | None = None,
    manifest_size_bytes: int | None = None,
    repo_root: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Bounded retained REFMAC admission/refusal boundary.

    Consumes the actual explicit ``manifest_json`` artifact reference (including a
    legitimate collision or parent-retention fallback), reopens and hashes the
    manifest and all required linked retained evidence (staged inputs,
    ``input_admission.json``, ``refmac_keywords.txt``, raw outputs ``log``,
    ``xyzout``, ``hklout``, optional ``xmlout``, and all 8 collector/audit JSON
    files), and binds subject/stage/original-data/operation identity without
    replacing any reference with a constructed canonical filename.

    Refuses payload-only or unpersisted records with
    :class:`RefmacRetainedVerificationError`. Keeps file-integrity verification
    distinct from scientific proof and always refuses scientific admission with
    :class:`RefmacScientificAdmissionRefusedError` reporting the three unproven
    native premises (``effective_hkls_proven``, ``native_bin_membership_proven``,
    ``native_residual_reconstruction_proven``) and any forged/unsupported proof
    claims.
    """
    try:
        return _verify_retained_refmac_rfactor_evidence_impl(
            admitted_root,
            subject_id=subject_id,
            manifest_reference=manifest_reference,
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha256,
            manifest_size_bytes=manifest_size_bytes,
            repo_root=repo_root,
        )
    except RefmacRetainedVerificationError:
        raise
    except RetainedReferenceError as exc:
        raise RefmacRetainedVerificationError(str(exc)) from exc


PARENT_COMPLETED_EXECUTION_CHECKPOINT_SCHEMA_VERSION = 1
PARENT_COMPLETED_EXECUTION_CHECKPOINT_STAGE = (
    "parent_completed_execution_checkpoint_v1"
)
EXPECTED_FAMILY_ID = "rfactors"

REQUIRED_PARENT_EXECUTION_CHECKPOINT_KEYS = frozenset(
    {
        "schema_version",
        "checkpoint_stage",
        "family",
        "subject_id",
        "subject",
        "mtz",
        "parent_evidence_root",
        "phenix_evidence_root",
        "refmac_evidence_root",
        "phenix_reconciled_manifest",
        "refmac_operation_manifest",
        "started_at_utc",
        "finished_at_utc",
        "run_date",
    }
)

FORBIDDEN_PARENT_CHECKPOINT_AUTHORING_OUTCOME_KEYS = frozenset(
    {
        "authoring_outcome",
        "final_outcome",
        "eval_record",
        "qds_record",
        "canonical_records_written",
        "publication_status",
        "canary_admitted",
        "scientific_admission_proven",
    }
)

_ISO8601_TZ_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_strict_tz_datetime(raw_value: Any, *, label: str) -> datetime:
    """Parse a timezone-qualified ISO-8601 timestamp string and convert to UTC."""
    if not isinstance(raw_value, str) or not _ISO8601_TZ_DATETIME_RE.fullmatch(
        raw_value
    ):
        raise ParentExecutionBindingError(
            f"{label}: expected full timezone-qualified ISO-8601 timestamp "
            f"(YYYY-MM-DDTHH:MM:SS[.ffffff](Z|±HH:MM)), got {raw_value!r}"
        )
    normalized = (
        raw_value[:-1] + "+00:00" if raw_value.endswith("Z") else raw_value
    )
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ParentExecutionBindingError(
            f"{label}: malformed ISO-8601 timestamp {raw_value!r} ({exc})"
        ) from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ParentExecutionBindingError(
            f"{label}: naive timestamp without timezone offset is not permitted: {raw_value!r}"
        )
    return dt.astimezone(timezone.utc)


def _parse_strict_iso_date(raw_value: Any, *, label: str) -> date:
    """Parse a strict ``YYYY-MM-DD`` calendar date string."""
    if not isinstance(raw_value, str) or not _ISO_DATE_RE.fullmatch(raw_value):
        raise ParentExecutionBindingError(
            f"{label}: expected YYYY-MM-DD calendar date string, got {raw_value!r}"
        )
    try:
        return date.fromisoformat(raw_value)
    except ValueError as exc:
        raise ParentExecutionBindingError(
            f"{label}: invalid calendar date {raw_value!r} ({exc})"
        ) from exc


def validate_parent_execution_timing(
    started_at_utc: Any,
    finished_at_utc: Any,
    run_date: Any,
    *,
    expected_run_date: str | None = None,
    label: str = "parent_execution_checkpoint",
) -> dict[str, Any]:
    """Validate parent execution timestamps and ``run_date`` binding in UTC.

    Enforces:
    1. Both ``started_at_utc`` and ``finished_at_utc`` are full timezone-qualified
       ISO-8601 timestamps (rejecting naive, date-only, or malformed strings).
    2. Chronological order in UTC: ``finished_utc >= started_utc``.
    3. ``run_date`` is a valid ``YYYY-MM-DD`` calendar date equal to ``started_at_utc``
       converted to UTC (``started_utc.date().isoformat()``), preserving a
       midnight-spanning interval where ``finished_utc.date() > started_utc.date()``.
    4. When ``expected_run_date`` is provided, ``run_date == expected_run_date``.
    """
    started_utc = _parse_strict_tz_datetime(
        started_at_utc, label=f"{label}.started_at_utc"
    )
    finished_utc = _parse_strict_tz_datetime(
        finished_at_utc, label=f"{label}.finished_at_utc"
    )
    if finished_utc < started_utc:
        raise ParentExecutionBindingError(
            f"{label}: reversed execution interval: finished_at_utc ({finished_at_utc!r} -> "
            f"{finished_utc.isoformat()}) precedes started_at_utc ({started_at_utc!r} -> "
            f"{started_utc.isoformat()})"
        )

    parsed_run_date = _parse_strict_iso_date(run_date, label=f"{label}.run_date")
    expected_utc_start_date = started_utc.date()
    if parsed_run_date != expected_utc_start_date:
        raise ParentExecutionBindingError(
            f"{label}.run_date: run_date {run_date!r} disagrees with started_at_utc "
            f"converted to UTC date {expected_utc_start_date.isoformat()!r} "
            f"(started_at_utc={started_at_utc!r}, finished_at_utc={finished_at_utc!r})"
        )

    if expected_run_date is not None:
        parsed_expected = _parse_strict_iso_date(
            expected_run_date, label=f"{label}.expected_run_date"
        )
        if parsed_run_date != parsed_expected:
            raise ParentExecutionBindingError(
                f"{label}.run_date: checkpoint run_date {run_date!r} disagrees with "
                f"forwarded expected_run_date {expected_run_date!r}"
            )

    elapsed_seconds = (finished_utc - started_utc).total_seconds()
    return {
        "started_at_utc": str(started_at_utc),
        "finished_at_utc": str(finished_at_utc),
        "started_at_utc_normalized": started_utc.isoformat(),
        "finished_at_utc_normalized": finished_utc.isoformat(),
        "started_utc_date": expected_utc_start_date.isoformat(),
        "finished_utc_date": finished_utc.date().isoformat(),
        "run_date": parsed_run_date.isoformat(),
        "elapsed_seconds": float(elapsed_seconds),
        "spans_utc_midnight": expected_utc_start_date != finished_utc.date(),
    }


def build_parent_completed_execution_checkpoint_payload(
    *,
    subject_id: str,
    family: str = EXPECTED_FAMILY_ID,
    parent_evidence_root: str | os.PathLike[str],
    phenix_evidence_root: str | os.PathLike[str],
    refmac_evidence_root: str | os.PathLike[str],
    phenix_reconciled_manifest: Mapping[str, Any],
    refmac_operation_manifest: Mapping[str, Any],
    started_at_utc: str,
    finished_at_utc: str,
    run_date: str,
) -> dict[str, Any]:
    """Construct the canonical Task 179 immutable completed parent execution checkpoint JSON payload.

    Binds:
    - ``schema_version = 1`` and ``checkpoint_stage = "parent_completed_execution_checkpoint_v1"``
    - ``family = "rfactors"`` and preregistered ``subject_id``, ``subject``, and ``mtz``
    - ``parent_evidence_root`` and distinct non-overlapping ``phenix_evidence_root``
      and ``refmac_evidence_root`` child directories
    - Explicit persisted ``phenix_reconciled_manifest`` and ``refmac_operation_manifest``
      references
    - Validated ``started_at_utc``, ``finished_at_utc``, and ``run_date``
     Keeps final authoring-outcome writing strictly separate from this hashed
    execution checkpoint.
    """
    _, onesar_rerun, _ = _load_refmac_verification_deps()
    if family != EXPECTED_FAMILY_ID:
        raise ParentExecutionBindingError(
            f"parent_execution_checkpoint.family: expected {EXPECTED_FAMILY_ID!r}, got {family!r}"
        )
    try:
        expected_subject = onesar_rerun.resolve_subject_spec(subject_id)
    except ValueError as exc:
        raise ParentExecutionBindingError(
            f"parent_execution_checkpoint.subject_id: {exc}"
        ) from exc
    expected_mtz = {
        "member": onesar_rerun.MTZ_MEMBER,
        "sha256": onesar_rerun.MTZ_SHA256,
        "subject_ref": onesar_rerun.MTZ_SUBJECT_REF,
    }

    try:
        parent_root = _ensure_no_symlink_chain_to_directory(
            Path(os.fspath(parent_evidence_root)),
            label="parent_execution_checkpoint.parent_evidence_root",
        )
        phenix_root = _ensure_no_symlink_chain_to_directory(
            Path(os.fspath(phenix_evidence_root)),
            label="parent_execution_checkpoint.phenix_evidence_root",
        )
        refmac_root = _ensure_no_symlink_chain_to_directory(
            Path(os.fspath(refmac_evidence_root)),
            label="parent_execution_checkpoint.refmac_evidence_root",
        )
    except (TypeError, RetainedReferenceError) as exc:
        raise ParentExecutionBindingError(str(exc)) from exc

    if (
        phenix_root == parent_root
        or not phenix_root.is_relative_to(parent_root)
        or refmac_root == parent_root
        or not refmac_root.is_relative_to(parent_root)
        or phenix_root == refmac_root
        or phenix_root.is_relative_to(refmac_root)
        or refmac_root.is_relative_to(phenix_root)
    ):
        raise ParentExecutionBindingError(
            "parent_execution_checkpoint: phenix_evidence_root and refmac_evidence_root "
            f"must be distinct non-overlapping child directories inside {parent_root}, "
            f"got phenix={phenix_root}, refmac={refmac_root}"
        )

    timing = validate_parent_execution_timing(
        started_at_utc,
        finished_at_utc,
        run_date,
        label="parent_execution_checkpoint",
    )

    try:
        phx_norm = normalize_retained_reference(
            phenix_reconciled_manifest,
            size_bytes_key=(
                "size_bytes"
                if isinstance(phenix_reconciled_manifest, Mapping)
                and "size_bytes" in phenix_reconciled_manifest
                else None
            ),
            label="parent_execution_checkpoint.phenix_reconciled_manifest",
        )
        selected_rm_ref = _select_refmac_manifest_reference(
            refmac_operation_manifest,
            manifest_path=None,
            manifest_sha256=None,
            manifest_size_bytes=None,
            label="parent_execution_checkpoint.refmac_operation_manifest",
        )
        rm_norm = normalize_retained_reference(
            selected_rm_ref,
            size_bytes_key=(
                "size_bytes"
                if isinstance(selected_rm_ref, Mapping)
                and "size_bytes" in selected_rm_ref
                else None
            ),
            label="parent_execution_checkpoint.refmac_operation_manifest",
        )
    except RetainedReferenceError as exc:
        raise ParentExecutionBindingError(str(exc)) from exc

    phx_ref_dict: dict[str, Any] = {
        "path": phx_norm["path"],
        "sha256": phx_norm["sha256"],
        "persisted": True,
    }
    if phx_norm["size_bytes"] is not None:
        phx_ref_dict["size_bytes"] = phx_norm["size_bytes"]

    assert isinstance(selected_rm_ref, Mapping)
    rm_ref_dict: dict[str, Any] = copy.deepcopy(dict(selected_rm_ref))
    rm_ref_dict["path"] = rm_norm["path"]
    rm_ref_dict["sha256"] = rm_norm["sha256"]
    rm_ref_dict["persisted"] = True
    if rm_norm["size_bytes"] is not None:
        rm_ref_dict["size_bytes"] = rm_norm["size_bytes"]

    return {
        "schema_version": PARENT_COMPLETED_EXECUTION_CHECKPOINT_SCHEMA_VERSION,
        "checkpoint_stage": PARENT_COMPLETED_EXECUTION_CHECKPOINT_STAGE,
        "family": family,
        "subject_id": subject_id,
        "subject": copy.deepcopy(expected_subject),
        "mtz": copy.deepcopy(expected_mtz),
        "parent_evidence_root": str(parent_root),
        "phenix_evidence_root": str(phenix_root),
        "refmac_evidence_root": str(refmac_root),
        "phenix_reconciled_manifest": phx_ref_dict,
        "refmac_operation_manifest": rm_ref_dict,
        "started_at_utc": timing["started_at_utc"],
        "finished_at_utc": timing["finished_at_utc"],
        "run_date": timing["run_date"],
    }


def _verify_retained_parent_execution_checkpoint_impl(
    admitted_root: str | os.PathLike[str],
    *,
    subject_id: str,
    checkpoint_reference: Mapping[str, Any] | None = None,
    checkpoint_path: str | os.PathLike[str] | None = None,
    checkpoint_sha256: str | None = None,
    checkpoint_size_bytes: int | None = None,
    expected_family: str = EXPECTED_FAMILY_ID,
    expected_run_date: str | None = None,
    repo_root: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    onesar_refmac, onesar_rerun, _ = _load_refmac_verification_deps()

    try:
        admitted_root_path = Path(os.fspath(admitted_root))
    except TypeError as exc:
        raise ParentExecutionBindingError(
            f"admitted_root: must be path-like, got {admitted_root!r}"
        ) from exc
    resolved_admitted_root = _ensure_no_symlink_chain_to_directory(
        admitted_root_path, label="admitted_root"
    )

    if expected_family != EXPECTED_FAMILY_ID:
        raise ParentExecutionBindingError(
            f"expected_family: only {EXPECTED_FAMILY_ID!r} is registered, got {expected_family!r}"
        )
    try:
        expected_subject = onesar_rerun.resolve_subject_spec(subject_id)
    except ValueError as exc:
        raise ParentExecutionBindingError(f"subject_id: {exc}") from exc
    expected_mtz = {
        "member": onesar_rerun.MTZ_MEMBER,
        "sha256": onesar_rerun.MTZ_SHA256,
        "subject_ref": onesar_rerun.MTZ_SUBJECT_REF,
    }

    raw_repo_root = onesar_rerun.REPO_ROOT if repo_root is None else repo_root
    try:
        repo_root_path = Path(os.fspath(raw_repo_root))
    except TypeError as exc:
        raise ParentExecutionBindingError(
            f"repo_root: must be path-like, got {raw_repo_root!r}"
        ) from exc
    resolved_repo_root = _ensure_no_symlink_chain_to_directory(
        repo_root_path, label="repo_root"
    )

    cp_size_key = (
        "size_bytes"
        if isinstance(checkpoint_reference, Mapping)
        and "size_bytes" in checkpoint_reference
        else None
    )
    checkpoint_loaded = load_retained_reference(
        resolved_admitted_root,
        checkpoint_reference,
        path=checkpoint_path,
        sha256=checkpoint_sha256,
        size_bytes=checkpoint_size_bytes,
        size_bytes_key=cp_size_key,
        parse_json=True,
        label="parent_execution_checkpoint",
    )
    checkpoint_doc = checkpoint_loaded["json"]
    assert isinstance(checkpoint_doc, dict)
    reopened_checkpoint_path = Path(checkpoint_loaded["verified_reference"]["path"])

    forbidden_outcome_present = sorted(
        FORBIDDEN_PARENT_CHECKPOINT_AUTHORING_OUTCOME_KEYS.intersection(
            checkpoint_doc.keys()
        )
    )
    if forbidden_outcome_present:
        raise ParentExecutionBindingError(
            "parent_execution_checkpoint: final authoring-outcome field(s) must remain "
            "separate from the hashed execution checkpoint, found: "
            f"{forbidden_outcome_present}"
        )
    if set(checkpoint_doc.keys()) != REQUIRED_PARENT_EXECUTION_CHECKPOINT_KEYS:
        missing_cp_keys = sorted(
            REQUIRED_PARENT_EXECUTION_CHECKPOINT_KEYS - set(checkpoint_doc.keys())
        )
        extra_cp_keys = sorted(
            set(checkpoint_doc.keys()) - REQUIRED_PARENT_EXECUTION_CHECKPOINT_KEYS
        )
        raise ParentExecutionBindingError(
            "parent_execution_checkpoint: top-level key mismatch "
            f"(missing={missing_cp_keys}, unexpected={extra_cp_keys})"
        )

    if (
        type(checkpoint_doc.get("schema_version")) is not int
        or checkpoint_doc["schema_version"]
        != PARENT_COMPLETED_EXECUTION_CHECKPOINT_SCHEMA_VERSION
    ):
        raise ParentExecutionBindingError(
            "parent_execution_checkpoint.schema_version: expected integer "
            f"{PARENT_COMPLETED_EXECUTION_CHECKPOINT_SCHEMA_VERSION}, "
            f"got {checkpoint_doc.get('schema_version')!r}"
        )
    if (
        checkpoint_doc.get("checkpoint_stage")
        != PARENT_COMPLETED_EXECUTION_CHECKPOINT_STAGE
    ):
        raise ParentExecutionBindingError(
            "parent_execution_checkpoint.checkpoint_stage: expected "
            f"{PARENT_COMPLETED_EXECUTION_CHECKPOINT_STAGE!r}, "
            f"got {checkpoint_doc.get('checkpoint_stage')!r}"
        )
    if checkpoint_doc.get("family") != expected_family:
        raise ParentExecutionBindingError(
            f"parent_execution_checkpoint.family: expected {expected_family!r}, "
            f"got {checkpoint_doc.get('family')!r}"
        )
    if checkpoint_doc.get("subject_id") != subject_id:
        raise ParentExecutionBindingError(
            f"parent_execution_checkpoint.subject_id: expected {subject_id!r}, "
            f"got {checkpoint_doc.get('subject_id')!r}"
        )
    if checkpoint_doc.get("subject") != expected_subject:
        raise ParentExecutionBindingError(
            "parent_execution_checkpoint.subject: disagrees with preregistered "
            f"subject specification for {subject_id!r}"
        )
    if checkpoint_doc.get("mtz") != expected_mtz:
        raise ParentExecutionBindingError(
            "parent_execution_checkpoint.mtz: disagrees with preregistered 1SAR MTZ specification"
        )

    raw_parent_root = checkpoint_doc.get("parent_evidence_root")
    raw_phenix_root = checkpoint_doc.get("phenix_evidence_root")
    raw_refmac_root = checkpoint_doc.get("refmac_evidence_root")
    if (
        not isinstance(raw_parent_root, str)
        or not raw_parent_root.strip()
        or not isinstance(raw_phenix_root, str)
        or not raw_phenix_root.strip()
        or not isinstance(raw_refmac_root, str)
        or not raw_refmac_root.strip()
    ):
        raise ParentExecutionBindingError(
            "parent_execution_checkpoint: parent_evidence_root, phenix_evidence_root, "
            "and refmac_evidence_root must be non-empty string paths"
        )
    parent_root = _ensure_no_symlink_chain_to_directory(
        Path(raw_parent_root),
        label="parent_execution_checkpoint.parent_evidence_root",
    )
    phenix_root = _ensure_no_symlink_chain_to_directory(
        Path(raw_phenix_root),
        label="parent_execution_checkpoint.phenix_evidence_root",
    )
    refmac_root = _ensure_no_symlink_chain_to_directory(
        Path(raw_refmac_root),
        label="parent_execution_checkpoint.refmac_evidence_root",
    )
    if not parent_root.is_relative_to(resolved_admitted_root):
        raise ParentExecutionBindingError(
            f"parent_execution_checkpoint: parent_evidence_root {parent_root} is "
            f"outside admitted_root {resolved_admitted_root}"
        )
    if (
        phenix_root == parent_root
        or not phenix_root.is_relative_to(parent_root)
        or refmac_root == parent_root
        or not refmac_root.is_relative_to(parent_root)
        or phenix_root == refmac_root
        or phenix_root.is_relative_to(refmac_root)
        or refmac_root.is_relative_to(phenix_root)
    ):
        raise ParentExecutionBindingError(
            "parent_execution_checkpoint: phenix_evidence_root and refmac_evidence_root "
            f"must be distinct non-overlapping child directories under {parent_root}, "
            f"got phenix={phenix_root}, refmac={refmac_root}"
        )
    if (
        not reopened_checkpoint_path.is_relative_to(parent_root)
        or reopened_checkpoint_path.is_relative_to(phenix_root)
        or reopened_checkpoint_path.is_relative_to(refmac_root)
    ):
        raise ParentExecutionBindingError(
            f"parent_execution_checkpoint: checkpoint file {reopened_checkpoint_path} "
            f"must reside under parent_evidence_root {parent_root} outside producer child roots"
        )

    timing = validate_parent_execution_timing(
        checkpoint_doc.get("started_at_utc"),
        checkpoint_doc.get("finished_at_utc"),
        checkpoint_doc.get("run_date"),
        expected_run_date=expected_run_date,
        label="parent_execution_checkpoint",
    )

    phx_ref_obj = checkpoint_doc.get("phenix_reconciled_manifest")
    if not isinstance(phx_ref_obj, Mapping):
        raise ParentExecutionBindingError(
            "parent_execution_checkpoint.phenix_reconciled_manifest: must be a reference mapping"
        )
    phenix_manifest_loaded = load_retained_reference(
        phenix_root,
        phx_ref_obj,
        size_bytes_key=(
            "size_bytes" if "size_bytes" in phx_ref_obj else None
        ),
        parse_json=True,
        reject_cache_manifest_as_phenix_reconciled=True,
        label="parent_execution_checkpoint.phenix_reconciled_manifest",
    )
    phenix_doc = phenix_manifest_loaded["json"]
    assert isinstance(phenix_doc, dict)
    expected_phx_manifest_path = (
        phenix_root / "phenix" / "phenix_reconciled_manifest.json"
    )
    if (
        Path(phenix_manifest_loaded["verified_reference"]["path"])
        != expected_phx_manifest_path
    ):
        raise ParentExecutionBindingError(
            "parent_execution_checkpoint.phenix_reconciled_manifest: expected path "
            f"{expected_phx_manifest_path}, got "
            f"{phenix_manifest_loaded['verified_reference']['path']}"
        )

    raw_rm_ref_obj = _select_refmac_manifest_reference(
        checkpoint_doc.get("refmac_operation_manifest"),
        manifest_path=None,
        manifest_sha256=None,
        manifest_size_bytes=None,
        label="parent_execution_checkpoint.refmac_operation_manifest",
    )
    if not isinstance(raw_rm_ref_obj, Mapping):
        raise ParentExecutionBindingError(
            "parent_execution_checkpoint.refmac_operation_manifest: must be a persisted reference mapping"
        )
    refmac_manifest_loaded = load_retained_reference(
        refmac_root,
        raw_rm_ref_obj,
        size_bytes_key=(
            "size_bytes" if "size_bytes" in raw_rm_ref_obj else None
        ),
        parse_json=True,
        label="parent_execution_checkpoint.refmac_operation_manifest",
    )
    refmac_doc = refmac_manifest_loaded["json"]
    assert isinstance(refmac_doc, dict)
    reopened_refmac_manifest_path = Path(
        refmac_manifest_loaded["verified_reference"]["path"]
    )

    refmac_child_dir = _ensure_no_symlink_chain_to_directory(
        refmac_root / "refmac",
        label="parent_execution_checkpoint.refmac_dir",
    )
    admitted_rm_dirs: set[Path] = {refmac_child_dir}
    parent_ret_candidate = refmac_root / "refmac_parent_retention"
    if (
        refmac_doc.get("actual_parent_retention_anchor_kind")
        == "verified_evidence_root_exclusive_dir"
    ):
        parent_ret_dir = parent_ret_candidate
    elif os.path.lexists(parent_ret_candidate):
        parent_ret_dir = _ensure_no_symlink_chain_to_directory(
            parent_ret_candidate,
            label="parent_execution_checkpoint.refmac_parent_retention",
        )
        admitted_rm_dirs.add(parent_ret_dir)
    else:
        parent_ret_dir = parent_ret_candidate
    resolved_rm_anchor = _resolve_and_validate_refmac_actual_anchor(
        refmac_doc,
        attempt_root=refmac_root,
        refmac_dir=refmac_child_dir,
        parent_retention_dir=parent_ret_dir,
        error_cls=ParentExecutionBindingError,
        label_prefix="refmac_operation_manifest",
    )
    if resolved_rm_anchor is not None:
        admitted_rm_dirs.add(resolved_rm_anchor)
    if reopened_refmac_manifest_path.parent not in admitted_rm_dirs:
        raise ParentExecutionBindingError(
            f"parent_execution_checkpoint.refmac_operation_manifest: path "
            f"{reopened_refmac_manifest_path} is not in an admitted retention directory "
            f"of {refmac_root}"
        )
    rm_paths_block = refmac_doc.get("paths")
    if (
        not isinstance(rm_paths_block, Mapping)
        or rm_paths_block.get("manifest_json_path")
        != str(reopened_refmac_manifest_path)
    ):
        raise ParentExecutionBindingError(
            "refmac_operation_manifest.paths.manifest_json_path: disagrees with "
            f"reopened manifest path {reopened_refmac_manifest_path}"
        )

    if phenix_doc.get("subject") != expected_subject:
        raise ParentExecutionBindingError(
            "phenix_reconciled_manifest.subject: disagrees with parent/preregistered "
            f"subject specification for {subject_id!r}"
        )
    if phenix_doc.get("mtz") != expected_mtz:
        raise ParentExecutionBindingError(
            "phenix_reconciled_manifest.mtz: disagrees with parent/preregistered 1SAR MTZ specification"
        )
    if (
        refmac_doc.get("subject_id") != subject_id
        or refmac_doc.get("subject") != expected_subject
    ):
        raise ParentExecutionBindingError(
            "refmac_operation_manifest.subject: disagrees with parent/preregistered "
            f"subject specification for {subject_id!r}"
        )
    if refmac_doc.get("mtz") != expected_mtz:
        raise ParentExecutionBindingError(
            "refmac_operation_manifest.mtz: disagrees with parent/preregistered 1SAR MTZ specification"
        )
    if refmac_doc.get("collector_stage") != onesar_refmac.COLLECTOR_STAGE:
        raise ParentExecutionBindingError(
            "refmac_operation_manifest.collector_stage: expected "
            f"{onesar_refmac.COLLECTOR_STAGE!r}, got {refmac_doc.get('collector_stage')!r}"
        )
    _validate_refmac_publication_pair_complete(
        refmac_doc,
        None,
        require_diagnostics=False,
        error_cls=ParentExecutionBindingError,
    )

    # Verify both children's staged inputs, input_admission.json, and pure projection/ledger rebuilds.
    phx_admission_path = phenix_root / "inputs" / "input_admission.json"
    try:
        phx_admission_path, phx_adm_sha, _ = (
            _admit_and_hash_regular_file_under_root(
                phenix_root,
                phx_admission_path,
                label="phenix_child.input_admission_json",
            )
        )
    except RetainedReferenceError as exc:
        raise ParentExecutionBindingError(str(exc)) from exc

    phenix_inputs = _verify_staged_inputs_and_admission_for_attempt(
        phenix_root,
        phenix_root,
        subject_id=subject_id,
        expected_subject=expected_subject,
        expected_mtz=expected_mtz,
        staged_files=phenix_doc.get("staged_files"),
        admission_reference=None,
        admission_path=phx_admission_path,
        admission_sha256=phx_adm_sha,
        resolved_repo_root=resolved_repo_root,
        onesar_rerun=onesar_rerun,
        error_cls=ParentExecutionBindingError,
        label_prefix="phenix_child",
    )
    if (
        phenix_doc.get("input_hkl_ledger_json_path")
        != phenix_inputs["loaded_ledger"]["verified_reference"]["path"]
        or phenix_doc.get("input_hkl_ledger_json_sha256")
        != phenix_inputs["loaded_ledger"]["verified_reference"]["sha256"]
    ):
        raise ParentExecutionBindingError(
            "phenix_reconciled_manifest: top-level input_hkl_ledger_json_path/sha256 "
            "disagrees with phenix_child.staged_files.input_hkl_ledger_json"
        )

    refmac_inputs = _verify_staged_inputs_and_admission_for_attempt(
        refmac_root,
        refmac_root,
        subject_id=subject_id,
        expected_subject=expected_subject,
        expected_mtz=expected_mtz,
        staged_files=refmac_doc.get("staged_files"),
        admission_reference=refmac_doc,
        admission_path=None,
        admission_sha256=None,
        admission_path_key="input_admission_json_path",
        admission_sha256_key="input_admission_json_sha256",
        resolved_repo_root=resolved_repo_root,
        onesar_rerun=onesar_rerun,
        error_cls=ParentExecutionBindingError,
        label_prefix="refmac_child",
    )
    if (
        refmac_doc.get("input_hkl_ledger_json_path")
        != refmac_inputs["loaded_ledger"]["verified_reference"]["path"]
        or refmac_doc.get("input_hkl_ledger_json_sha256")
        != refmac_inputs["loaded_ledger"]["verified_reference"]["sha256"]
    ):
        raise ParentExecutionBindingError(
            "refmac_operation_manifest: top-level input_hkl_ledger_json_path/sha256 "
            "disagrees with refmac_child.staged_files.input_hkl_ledger_json"
        )

    for staged_role in (
        "loaded_pdb",
        "loaded_orig_mtz",
        "loaded_proj_mtz",
        "loaded_ledger",
    ):
        phx_item = phenix_inputs[staged_role]
        rm_item = refmac_inputs[staged_role]
        if (
            phx_item["verified_reference"]["sha256"]
            != rm_item["verified_reference"]["sha256"]
            or phx_item["bytes"] != rm_item["bytes"]
        ):
            raise ParentExecutionBindingError(
                f"parent_execution_checkpoint: cross-producer staged input mismatch on "
                f"{staged_role} between PHENIX child and REFMAC child"
            )

    # Verify REFMAC outputs never replace inputs.
    rm_invocation = refmac_doc.get("invocation")
    rm_raw_outputs = refmac_doc.get("raw_outputs")
    if not isinstance(rm_invocation, Mapping) or not isinstance(rm_raw_outputs, Mapping):
        raise ParentExecutionBindingError(
            "refmac_operation_manifest: missing invocation or raw_outputs mapping"
        )
    expected_rm_xyzout = refmac_child_dir / "refmac_xyzout.pdb"
    expected_rm_hklout = refmac_child_dir / "refmac_hklout.mtz"
    expected_rm_log = refmac_child_dir / "refmac.log"
    if (
        rm_invocation.get("xyzin_path")
        != refmac_inputs["loaded_pdb"]["verified_reference"]["path"]
        or rm_invocation.get("hklin_path")
        != refmac_inputs["loaded_proj_mtz"]["verified_reference"]["path"]
        or rm_invocation.get("xyzout_path") != str(expected_rm_xyzout)
        or rm_invocation.get("hklout_path") != str(expected_rm_hklout)
        or rm_paths_block.get("original_pdb_path")
        != refmac_inputs["loaded_pdb"]["verified_reference"]["path"]
        or rm_paths_block.get("original_mtz_path")
        != refmac_inputs["loaded_orig_mtz"]["verified_reference"]["path"]
        or rm_paths_block.get("projected_mtz_path")
        != refmac_inputs["loaded_proj_mtz"]["verified_reference"]["path"]
        or rm_paths_block.get("xyzout_path") != str(expected_rm_xyzout)
        or rm_paths_block.get("hklout_path") != str(expected_rm_hklout)
    ):
        raise ParentExecutionBindingError(
            "refmac_operation_manifest: input/output path binding violation "
            "(REFMAC outputs must reside in refmac_dir and never replace staged inputs)"
        )

    loaded_rm_raw_outputs: dict[str, dict[str, Any]] = {}
    for out_key, expected_out_path in (
        ("log", expected_rm_log),
        ("xyzout", expected_rm_xyzout),
        ("hklout", expected_rm_hklout),
    ):
        out_ref = rm_raw_outputs.get(out_key)
        if not isinstance(out_ref, Mapping):
            raise ParentExecutionBindingError(
                f"refmac_operation_manifest.raw_outputs.{out_key}: must be a mapping"
            )
        loaded_out = load_retained_reference(
            refmac_root,
            out_ref,
            label=f"refmac_child.raw_outputs.{out_key}",
        )
        if Path(loaded_out["verified_reference"]["path"]) != expected_out_path:
            raise ParentExecutionBindingError(
                f"refmac_child.raw_outputs.{out_key}: expected {expected_out_path}, "
                f"got {loaded_out['verified_reference']['path']}"
            )
        loaded_rm_raw_outputs[out_key] = loaded_out

    # Ensure REFMAC child manifest is either a clean unproven diagnostic capture
    # or a coherent persisted fallback capture, and never claims scientific admission.
    rm_failures = refmac_doc.get("failures")
    rm_diag_ref = refmac_doc.get("diagnostics_json")
    rm_diag_noncanonical = (
        isinstance(rm_diag_ref, Mapping)
        and isinstance(rm_diag_ref.get("path"), str)
        and (
            Path(rm_diag_ref["path"])
            != refmac_child_dir / "refmac_diagnostics.json"
            or bool(
                rm_diag_ref.get("fallback_for_unwritable_or_damaged_child_dir")
                or rm_diag_ref.get(
                    "fallback_for_damaged_or_replaced_parent_retention_dir"
                )
                or rm_diag_ref.get("collision_fallback_used")
            )
        )
    )
    rm_fallback_anchor_meta = refmac_doc.get("parent_retention_fallback_anchor")
    has_rm_fallback_evidence = bool(
        reopened_refmac_manifest_path
        != refmac_child_dir / "refmac_operation_manifest.json"
        or refmac_manifest_loaded["verified_reference"]["is_fallback"]
        or refmac_doc.get("parent_retention_used") is True
        or bool(refmac_doc.get("child_dir_persistence_failures"))
        or refmac_doc.get("actual_parent_retention_anchor_dir") is not None
        or refmac_doc.get("actual_parent_retention_anchor_kind") is not None
        or (
            isinstance(rm_fallback_anchor_meta, Mapping)
            and bool(rm_fallback_anchor_meta.get("used"))
        )
        or rm_diag_noncanonical
    )
    reopened_rm_diag_path: Path | None = None
    rm_diag_doc: Mapping[str, Any] | None = None
    if isinstance(rm_diag_ref, Mapping):
        loaded_rm_diag = load_retained_reference(
            refmac_root,
            rm_diag_ref,
            parse_json=True,
            label="refmac_child.diagnostics_json",
        )
        reopened_rm_diag_path = Path(
            loaded_rm_diag["verified_reference"]["path"]
        )
        if reopened_rm_diag_path.parent not in admitted_rm_dirs:
            raise ParentExecutionBindingError(
                f"refmac_child.diagnostics_json: path {reopened_rm_diag_path} "
                f"is not in an admitted retention directory of {refmac_root}"
            )
        if rm_paths_block.get("diagnostics_json_path") != str(
            reopened_rm_diag_path
        ):
            raise ParentExecutionBindingError(
                "refmac_operation_manifest.paths.diagnostics_json_path: "
                f"disagrees with reopened diagnostics path {reopened_rm_diag_path}"
            )
        if isinstance(loaded_rm_diag.get("json"), Mapping):
            rm_diag_doc = loaded_rm_diag["json"]
        _validate_refmac_publication_pair_complete(
            refmac_doc,
            rm_diag_doc,
            require_diagnostics=True,
            error_cls=ParentExecutionBindingError,
        )

    (
        rm_supported_fallback_only,
        rm_has_persist_failure,
        rm_has_collision_failure,
    ) = _classify_refmac_fallback_failures(
        rm_failures,
        manifest_doc=(
            refmac_doc
            if (has_rm_fallback_evidence or bool(rm_failures))
            else None
        ),
        diagnostics_doc=(
            rm_diag_doc
            if (has_rm_fallback_evidence or bool(rm_failures))
            else None
        ),
        attempt_root=refmac_root,
        refmac_dir=refmac_child_dir,
        parent_retention_dir=parent_ret_dir,
        resolved_actual_anchor=resolved_rm_anchor,
        reopened_manifest_path=reopened_refmac_manifest_path,
        reopened_diagnostics_path=reopened_rm_diag_path,
    )
    if has_rm_fallback_evidence:
        if not rm_supported_fallback_only:
            raise ParentExecutionBindingError(
                "refmac_operation_manifest: fallback manifest location or metadata "
                "requires supported fallback failure stage in failures"
            )
        if not isinstance(rm_diag_doc, Mapping):
            raise ParentExecutionBindingError(
                "refmac_operation_manifest.diagnostics_json: fallback capture requires "
                "a persisted and verified diagnostics_json publication pair"
            )
        _validate_refmac_publication_pair_complete(
            refmac_doc,
            rm_diag_doc,
            require_diagnostics=True,
            error_cls=ParentExecutionBindingError,
        )
        if (
            refmac_doc.get("status") != "failed"
            or rm_diag_doc.get("status") != "failed"
        ):
            raise ParentExecutionBindingError(
                "refmac_operation_manifest.status: expected 'failed' for persisted "
                f"fallback capture, got {refmac_doc.get('status')!r}"
            )
        assert isinstance(rm_failures, list)
        expected_rm_failed_stage = rm_failures[0].get("failed_stage")
        if (
            refmac_doc.get("failed_stage") != expected_rm_failed_stage
            or rm_diag_doc.get("failed_stage") != expected_rm_failed_stage
            or rm_diag_doc.get("failures") != rm_failures
            or rm_diag_doc.get("parent_retention_used")
            != refmac_doc.get("parent_retention_used")
            or rm_diag_doc.get("actual_parent_retention_anchor_dir")
            != refmac_doc.get("actual_parent_retention_anchor_dir")
            or rm_diag_doc.get("actual_parent_retention_anchor_kind")
            != refmac_doc.get("actual_parent_retention_anchor_kind")
            or rm_diag_doc.get("intended_parent_retention_dir")
            != refmac_doc.get("intended_parent_retention_dir")
            or rm_diag_doc.get("parent_retention_fallback_anchor")
            != refmac_doc.get("parent_retention_fallback_anchor")
            or rm_diag_doc.get("parent_retention_directory_post_run")
            != refmac_doc.get("parent_retention_directory_post_run")
            or rm_diag_doc.get("refmac_directory_post_run")
            != refmac_doc.get("refmac_directory_post_run")
            or rm_diag_doc.get("child_dir_persistence_failures")
            != refmac_doc.get("child_dir_persistence_failures")
        ):
            raise ParentExecutionBindingError(
                "refmac_operation_manifest.failed_stage: disagrees with primary "
                "fallback failure stage or diagnostics_json fallback metadata"
            )
        rm_op_checks = refmac_doc.get("operation_checks")
        if not isinstance(rm_op_checks, Mapping):
            raise ParentExecutionBindingError(
                "refmac_operation_manifest.operation_checks: must be a mapping for fallback capture"
            )
        for req_true_check in (
            "preflight_toolchain_resolved",
            "worker_launched",
            "process_returncode_zero",
            "completed_argv_available",
            "argv_matches_expected",
            "pre_execution_checkpoint_verified",
            "native_r_pair_parsed",
            "ncyc_zero_requested_and_echoed",
            "xmlout_audit_valid",
            "hklout_audit_valid",
            "xyzout_audit_valid",
            "input_immutability_verified",
        ):
            if rm_op_checks.get(req_true_check) is not True:
                raise ParentExecutionBindingError(
                    f"refmac_operation_manifest.operation_checks.{req_true_check}: "
                    f"expected True, got {rm_op_checks.get(req_true_check)!r}"
                )
        if (
            rm_op_checks.get("collector_succeeded") is not False
            or rm_op_checks.get("stage1_collection_succeeded") is not False
            or type(rm_op_checks.get("stage2_audits_succeeded")) is not bool
            or (
                not rm_has_persist_failure
                and rm_op_checks.get("stage2_audits_succeeded") is not True
            )
            or rm_op_checks.get("parent_retention_used")
            is not bool(rm_has_persist_failure)
            or refmac_doc.get("parent_retention_used")
            is not bool(rm_has_persist_failure)
            or rm_op_checks.get("all_raw_outputs_present_and_regular")
            is not (not rm_has_collision_failure)
            or refmac_doc.get("model_preservation_proven") is not False
            or not isinstance(refmac_doc.get("model_preservation_unproven_reason"), str)
            or not refmac_doc["model_preservation_unproven_reason"].strip()
        ):
            raise ParentExecutionBindingError(
                "refmac_operation_manifest: inconsistent operation_checks or "
                "model_preservation_proven for persisted fallback capture"
            )
        for linked_key in _REFMAC_LINKED_JSON_KEYS:
            if linked_key == "diagnostics_json":
                continue
            linked_ref = refmac_doc.get(linked_key)
            if not isinstance(linked_ref, Mapping):
                raise ParentExecutionBindingError(
                    f"refmac_child.{linked_key}: missing persisted reference mapping"
                )
            loaded_linked = load_retained_reference(
                refmac_root,
                linked_ref,
                parse_json=True,
                label=f"refmac_child.{linked_key}",
            )
            reopened_linked_path = Path(
                loaded_linked["verified_reference"]["path"]
            )
            if reopened_linked_path.parent not in admitted_rm_dirs:
                raise ParentExecutionBindingError(
                    f"refmac_child.{linked_key}: path {reopened_linked_path} "
                    f"is not in an admitted retention directory of {refmac_root}"
                )
            if linked_key == "xyzout_audit_json":
                rm_xyz_audit_doc = loaded_linked["json"]
                if (
                    not isinstance(rm_xyz_audit_doc, Mapping)
                    or rm_xyz_audit_doc.get("valid") is not True
                    or rm_xyz_audit_doc.get("model_preservation_proven")
                    is not True
                ):
                    raise ParentExecutionBindingError(
                        "refmac_child.xyzout_audit_json: expected valid=True and "
                        "model_preservation_proven=True"
                    )
    else:
        if rm_failures not in (None, []) or refmac_doc.get("failed_stage") is not None:
            raise ParentExecutionBindingError(
                "refmac_operation_manifest: non-fallback capture reported failure(s): "
                f"{rm_failures!r}"
            )
        if refmac_doc.get("status") != "diagnostic_captured_gates_unproven":
            raise ParentExecutionBindingError(
                "refmac_operation_manifest.status: expected "
                f"'diagnostic_captured_gates_unproven', got {refmac_doc.get('status')!r}"
            )
    for proof_key, reason_key in REFMAC_PROOF_TO_REASON_KEYS:
        if refmac_doc.get(proof_key) is not False:
            raise ParentExecutionBindingError(
                f"refmac_operation_manifest.{proof_key}: must be False "
                f"(got {refmac_doc.get(proof_key)!r})"
            )
        reason_val = refmac_doc.get(reason_key)
        if (
            not isinstance(reason_val, str)
            or not reason_val.strip()
            or reason_val.strip().lower() == "none"
        ):
            raise ParentExecutionBindingError(
                f"refmac_operation_manifest.{reason_key}: must be a non-empty unproven reason string"
            )
    for elig_key in REFMAC_FALSE_ADMISSION_ELIGIBILITY_KEYS:
        if refmac_doc.get(elig_key) is not False:
            raise ParentExecutionBindingError(
                f"refmac_operation_manifest.{elig_key}: must be False "
                f"(got {refmac_doc.get(elig_key)!r})"
            )

    return {
        "verification_status": "verified",
        "admitted_root": str(resolved_admitted_root),
        "repo_root": str(resolved_repo_root),
        "family": expected_family,
        "subject_id": subject_id,
        "subject": copy.deepcopy(expected_subject),
        "mtz": copy.deepcopy(expected_mtz),
        "archive": copy.deepcopy(phenix_inputs["archive"]),
        "parent_evidence_root": str(parent_root),
        "phenix_evidence_root": str(phenix_root),
        "refmac_evidence_root": str(refmac_root),
        "checkpoint_path": checkpoint_loaded["verified_reference"]["path"],
        "checkpoint_sha256": checkpoint_loaded["verified_reference"]["sha256"],
        "timing": timing,
        "common_inputs": {
            "original_model_pdb_sha256": phenix_inputs["loaded_pdb"][
                "verified_reference"
            ]["sha256"],
            "original_data_mtz_sha256": phenix_inputs["loaded_orig_mtz"][
                "verified_reference"
            ]["sha256"],
            "projected_observations_mtz_sha256": phenix_inputs["loaded_proj_mtz"][
                "verified_reference"
            ]["sha256"],
            "input_hkl_ledger_json_sha256": phenix_inputs["loaded_ledger"][
                "verified_reference"
            ]["sha256"],
            "projection_summary": copy.deepcopy(phenix_inputs["projection_summary"]),
            "input_ledger_counts": copy.deepcopy(
                phenix_inputs["rebuilt_ledger"]["counts"]
            ),
        },
        "verified_references": {
            "parent_execution_checkpoint": checkpoint_loaded["verified_reference"],
            "phenix_reconciled_manifest": phenix_manifest_loaded["verified_reference"],
            "refmac_operation_manifest": refmac_manifest_loaded["verified_reference"],
            "phenix_staged_inputs": {
                "original_model_pdb": phenix_inputs["loaded_pdb"]["verified_reference"],
                "original_data_mtz": phenix_inputs["loaded_orig_mtz"][
                    "verified_reference"
                ],
                "projected_observations_mtz": phenix_inputs["loaded_proj_mtz"][
                    "verified_reference"
                ],
                "input_hkl_ledger_json": phenix_inputs["loaded_ledger"][
                    "verified_reference"
                ],
                "input_admission_json": phenix_inputs["loaded_admission"][
                    "verified_reference"
                ],
            },
            "refmac_staged_inputs": {
                "original_model_pdb": refmac_inputs["loaded_pdb"]["verified_reference"],
                "original_data_mtz": refmac_inputs["loaded_orig_mtz"][
                    "verified_reference"
                ],
                "projected_observations_mtz": refmac_inputs["loaded_proj_mtz"][
                    "verified_reference"
                ],
                "input_hkl_ledger_json": refmac_inputs["loaded_ledger"][
                    "verified_reference"
                ],
                "input_admission_json": refmac_inputs["loaded_admission"][
                    "verified_reference"
                ],
            },
            "refmac_raw_outputs": {
                k: v["verified_reference"] for k, v in loaded_rm_raw_outputs.items()
            },
        },
        "verification_boundaries": {
            "parent_execution_checkpoint_verified": True,
            "common_subject_and_projected_inputs_bound": True,
            "authoring_outcome_separated_from_execution_checkpoint": True,
            "scientific_proof_established": False,
            "canary_scientific_admission_established": False,
            "eval_or_qds_published": False,
        },
    }


def verify_retained_parent_execution_checkpoint(
    admitted_root: str | os.PathLike[str],
    *,
    subject_id: str,
    checkpoint_reference: Mapping[str, Any] | None = None,
    checkpoint_path: str | os.PathLike[str] | None = None,
    checkpoint_sha256: str | None = None,
    checkpoint_size_bytes: int | None = None,
    expected_family: str = EXPECTED_FAMILY_ID,
    expected_run_date: str | None = None,
    repo_root: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Pure verifier for Task 179's immutable completed parent execution checkpoint.

    Reopens and hashes the parent completed execution checkpoint JSON under
    ``admitted_root``, validates that final authoring-outcome fields are absent
    from the execution checkpoint, validates timezone-qualified UTC start/finish
    timestamps and ``run_date == started_utc.date().isoformat()`` (preserving
    midnight-spanning intervals), reopens both bound producer manifest references
    (``phenix_reconciled_manifest`` and ``refmac_operation_manifest``), and binds
    common registered subject/stage/archive/member, original coordinate/MTZ, and
    projected MTZ / input HKL ledger identities across both producer child roots
    while ensuring REFMAC outputs never replace inputs.
    """
    try:
        return _verify_retained_parent_execution_checkpoint_impl(
            admitted_root,
            subject_id=subject_id,
            checkpoint_reference=checkpoint_reference,
            checkpoint_path=checkpoint_path,
            checkpoint_sha256=checkpoint_sha256,
            checkpoint_size_bytes=checkpoint_size_bytes,
            expected_family=expected_family,
            expected_run_date=expected_run_date,
            repo_root=repo_root,
        )
    except ParentExecutionBindingError:
        raise
    except RetainedReferenceError as exc:
        raise ParentExecutionBindingError(str(exc)) from exc


DEFAULT_RECORD_DESTINATION_REL: str = "data/coscientists/openscientist"

_SUPPLEMENTAL_SUBJECT_TAGS: dict[str, str] = {
    "start": "start",
    "R5": "r5",
    "R6": "r6",
}

_T03_METRIC_IDS: tuple[str, ...] = (
    "T03_r-work",
    "T03_r-free",
    "T03_r-free_r-work_gap",
)

_T03_ORACLE_TOOL_IDS: tuple[str, ...] = (
    "phenix.model_vs_data",
    "REFMAC5",
)

_COMMITTED_R4_EVAL_REL_PATH: str = (
    "data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-09-23.yaml"
)

_FORBIDDEN_T03_INFORMATIONAL_FIELDS: tuple[str, ...] = (
    "agent_claim",
    "delta",
    "delta_from_measurement_ref",
    "pass_criterion",
    "pass_criterion_ref",
    "criterion_preconditions",
)


class RfactorRecordAssemblyError(RetainedReferenceError):
    """Raised when private 1SAR R-factor EVAL/QDS assembly, live emission, or replay pinning fails."""


def _load_record_assembly_deps() -> tuple[Any, Any, Any, Any, Any, Any, Any]:
    """Import pure record-assembly, live-emitter, pin, and model dependencies lazily."""
    scripts_dir = Path(__file__).resolve().parent
    repo_root = scripts_dir.parent
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    import check_qds_trust_invariant
    import onesar_rerun
    from pydantic import ValidationError
    from protstruct_review import models
    import qds_emit
    import qds_emit_contract_v4
    import yaml

    return (
        onesar_rerun,
        qds_emit,
        qds_emit_contract_v4,
        check_qds_trust_invariant,
        models,
        ValidationError,
        yaml,
    )


def _validate_finite_non_bool_number(
    value: Any,
    *,
    label: str,
    allow_negative: bool = True,
) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
    ):
        raise RfactorRecordAssemblyError(
            f"{label}: expected finite non-boolean numeric value, got {value!r}"
        )
    numeric = float(value)
    if not allow_negative and numeric < 0.0:
        raise RfactorRecordAssemblyError(
            f"{label}: expected non-negative finite number, got {value!r}"
        )
    return numeric


def _validate_positive_non_bool_int(value: Any, *, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise RfactorRecordAssemblyError(
            f"{label}: expected positive integer count (bool/float rejected), got {value!r}"
        )
    return int(value)


def _validate_hkl_triple_list(
    hkls_raw: Any,
    *,
    expected_count: int | None,
    label: str,
) -> list[list[int]]:
    if not isinstance(hkls_raw, list) or not hkls_raw:
        raise RfactorRecordAssemblyError(
            f"{label}: expected non-empty list of [h, k, l] integer triples"
        )
    if expected_count is not None:
        checked_count = _validate_positive_non_bool_int(
            expected_count, label=f"{label}.expected_count"
        )
        if len(hkls_raw) != checked_count:
            raise RfactorRecordAssemblyError(
                f"{label}: HKL list length {len(hkls_raw)} disagrees with count {checked_count}"
            )
    seen: set[tuple[int, int, int]] = set()
    normalized: list[list[int]] = []
    for idx, item in enumerate(hkls_raw):
        if (
            not isinstance(item, (list, tuple))
            or len(item) != 3
            or any(type(coord) is not int for coord in item)
        ):
            raise RfactorRecordAssemblyError(
                f"{label}[{idx}]: expected 3-element integer Miller index (bool rejected), got {item!r}"
            )
        triple = (int(item[0]), int(item[1]), int(item[2]))
        if triple == (0, 0, 0):
            raise RfactorRecordAssemblyError(
                f"{label}[{idx}]: (0, 0, 0) Miller index is invalid"
            )
        if triple in seen:
            raise RfactorRecordAssemblyError(
                f"{label}[{idx}]: duplicate Miller index {list(triple)}"
            )
        seen.add(triple)
        normalized.append([triple[0], triple[1], triple[2]])
    return sorted(normalized, key=lambda row: (row[0], row[1], row[2]))


def _compute_cross_tool_hkl_set_comparison(
    phenix_work_hkls: Any,
    phenix_free_hkls: Any,
    refmac_work_hkls: Any,
    refmac_free_hkls: Any,
    *,
    phenix_work_count: int | None = None,
    phenix_free_count: int | None = None,
    refmac_work_count: int | None = None,
    refmac_free_count: int | None = None,
) -> dict[str, Any]:
    """Validate both producers' work/free HKL lists and compute exact set differences."""
    phx_work = _validate_hkl_triple_list(
        phenix_work_hkls,
        expected_count=phenix_work_count,
        label="phenix.actual_work_hkls",
    )
    phx_free = _validate_hkl_triple_list(
        phenix_free_hkls,
        expected_count=phenix_free_count,
        label="phenix.actual_free_hkls",
    )
    rm_work = _validate_hkl_triple_list(
        refmac_work_hkls,
        expected_count=refmac_work_count,
        label="refmac.actual_work_hkls",
    )
    rm_free = _validate_hkl_triple_list(
        refmac_free_hkls,
        expected_count=refmac_free_count,
        label="refmac.actual_free_hkls",
    )
    phx_work_set = {(h, k, l) for h, k, l in phx_work}
    phx_free_set = {(h, k, l) for h, k, l in phx_free}
    if phx_work_set & phx_free_set:
        raise RfactorRecordAssemblyError(
            "phenix: actual_work_hkls and actual_free_hkls are not disjoint"
        )
    rm_work_set = {(h, k, l) for h, k, l in rm_work}
    rm_free_set = {(h, k, l) for h, k, l in rm_free}
    if rm_work_set & rm_free_set:
        raise RfactorRecordAssemblyError(
            "refmac: actual_work_hkls and actual_free_hkls are not disjoint"
        )

    work_only_in_phenix = [
        [h, k, l] for h, k, l in sorted(phx_work_set - rm_work_set)
    ]
    work_only_in_refmac = [
        [h, k, l] for h, k, l in sorted(rm_work_set - phx_work_set)
    ]
    free_only_in_phenix = [
        [h, k, l] for h, k, l in sorted(phx_free_set - rm_free_set)
    ]
    free_only_in_refmac = [
        [h, k, l] for h, k, l in sorted(rm_free_set - phx_free_set)
    ]
    work_sets_equal = not work_only_in_phenix and not work_only_in_refmac
    free_sets_equal = not free_only_in_phenix and not free_only_in_refmac
    effective_sets_equal = work_sets_equal and free_sets_equal
    return {
        "phenix_work_count": len(phx_work),
        "phenix_free_count": len(phx_free),
        "refmac_work_count": len(rm_work),
        "refmac_free_count": len(rm_free),
        "work_intersection_count": len(phx_work_set & rm_work_set),
        "free_intersection_count": len(phx_free_set & rm_free_set),
        "work_only_in_phenix": work_only_in_phenix,
        "work_only_in_refmac": work_only_in_refmac,
        "free_only_in_phenix": free_only_in_phenix,
        "free_only_in_refmac": free_only_in_refmac,
        "work_sets_equal": work_sets_equal,
        "free_sets_equal": free_sets_equal,
        "effective_sets_equal": effective_sets_equal,
        "comparability_label": (
            "comparable_identical_effective_hkl_sets"
            if effective_sets_equal
            else "non-comparable"
        ),
    }


def _resolve_rfactor_record_identities(
    subject_id: str,
    *,
    run_date: str,
    destination_rel: str = DEFAULT_RECORD_DESTINATION_REL,
) -> dict[str, Any]:
    """Resolve canonical EVAL/QDS stems, relative paths, and IDs from subject and parent UTC start date."""
    onesar_rerun, *_ = _load_record_assembly_deps()
    try:
        subject_spec = onesar_rerun.resolve_subject_spec(subject_id)
    except ValueError as exc:
        raise RfactorRecordAssemblyError(f"subject_id: {exc}") from exc
    if not isinstance(run_date, str) or not _ISO_DATE_RE.fullmatch(run_date):
        raise RfactorRecordAssemblyError(
            f"run_date: expected canonical YYYY-MM-DD date string, got {run_date!r}"
        )
    try:
        parsed_date = _parse_strict_iso_date(run_date, label="run_date")
    except ParentExecutionBindingError as exc:
        raise RfactorRecordAssemblyError(str(exc)) from exc
    if parsed_date.isoformat() != run_date:
        raise RfactorRecordAssemblyError(
            f"run_date: non-canonical date string {run_date!r}"
        )
    if (
        not isinstance(destination_rel, str)
        or not destination_rel.strip()
        or destination_rel.startswith("/")
        or "\\" in destination_rel
    ):
        raise RfactorRecordAssemblyError(
            f"destination_rel: must be a relative POSIX path under data/, got {destination_rel!r}"
        )
    norm_dest = destination_rel.strip("/")
    dest_parts = [part for part in norm_dest.split("/") if part]
    if not dest_parts or dest_parts[0] != "data" or ".." in dest_parts or "." in dest_parts:
        raise RfactorRecordAssemblyError(
            f"destination_rel: must reside under data/ without '.' or '..' components, got {destination_rel!r}"
        )
    norm_dest = "/".join(dest_parts)

    if subject_id == "R4":
        eval_stem = f"EVAL_1sar_cdba2c07_{run_date}"
        qds_id: str | None = f"QDS_1sar_cdba2c07_{run_date}"
        emits_qds = True
    elif subject_id in _SUPPLEMENTAL_SUBJECT_TAGS:
        stage_tag = _SUPPLEMENTAL_SUBJECT_TAGS[subject_id]
        eval_stem = f"EVAL_1sar_cdba2c07-{stage_tag}_{run_date}"
        qds_id = None
        emits_qds = False
    else:
        raise RfactorRecordAssemblyError(
            f"subject_id: unsupported 1SAR subject {subject_id!r}"
        )

    return {
        "subject_id": subject_id,
        "subject": copy.deepcopy(subject_spec),
        "stage": subject_spec["stage"],
        "run_date": run_date,
        "destination_rel": norm_dest,
        "eval_filename_stem": eval_stem,
        "eval_run_id": eval_stem,
        "eval_rel_path": f"{norm_dest}/{eval_stem}.yaml",
        "emits_qds": emits_qds,
        "qds_id": qds_id,
        "qds_rel_path": (
            f"{norm_dest}/{qds_id}.yaml" if qds_id is not None else None
        ),
        "emission_context_id": (
            f"CTX_{qds_id}" if qds_id is not None else None
        ),
        "replay_pin_id": (
            f"PIN_{qds_id}" if qds_id is not None else None
        ),
    }


def _validate_repo_relative_evidence_refs(
    evidence_refs_raw: Any,
    *,
    label: str,
) -> list[str]:
    if not isinstance(evidence_refs_raw, (list, tuple)) or not evidence_refs_raw:
        raise RfactorRecordAssemblyError(
            f"{label}: expected non-empty list of repository-relative evidence_refs"
        )
    validated: list[str] = []
    seen: set[str] = set()
    for idx, ref in enumerate(evidence_refs_raw):
        if (
            not isinstance(ref, str)
            or not ref.strip()
            or ref.startswith("/")
            or "\\" in ref
        ):
            raise RfactorRecordAssemblyError(
                f"{label}[{idx}]: expected relative POSIX path string, got {ref!r}"
            )
        parts = [part for part in ref.split("/") if part]
        if not parts or ".." in parts or "." in parts:
            raise RfactorRecordAssemblyError(
                f"{label}[{idx}]: invalid relative evidence path {ref!r}"
            )
        norm_ref = "/".join(parts)
        if norm_ref not in seen:
            seen.add(norm_ref)
            validated.append(norm_ref)
    return validated


def _validate_optional_provenance_ref(
    provenance_ref: Any,
    *,
    label: str,
) -> str | None:
    if provenance_ref is None:
        return None
    if not isinstance(provenance_ref, str) or not provenance_ref.strip():
        raise RfactorRecordAssemblyError(
            f"{label}: provenance_ref must be a non-empty string or None (object/non-string rejected), "
            f"got {provenance_ref!r}"
        )
    return provenance_ref.strip()


def _assemble_six_row_t03_measurements(
    *,
    parent_binding: Mapping[str, Any],
    phenix_bundle: Mapping[str, Any],
    refmac_bundle: Mapping[str, Any],
    eval_run_id: str | None = None,
    cross_tool_comparison_evidence_ref: str | None = None,
    destination_rel: str = DEFAULT_RECORD_DESTINATION_REL,
) -> dict[str, Any]:
    """Assemble the 6 informational T03 MeasurementValue rows from verified parent and producer bundles.

    This is a private internal record-mechanics helper. It requires an already
    verified parent execution checkpoint binding, a verified PHENIX measurement
    bundle, and a verified REFMAC measurement bundle with explicit active work
    and free HKL sets. It never infers REFMAC native effective sets from
    candidate counts or PHENIX single-producer results.
    """
    onesar_rerun, *_ = _load_record_assembly_deps()
    if not isinstance(parent_binding, Mapping):
        raise RfactorRecordAssemblyError(
            "parent_binding: must be a verified parent checkpoint result mapping"
        )
    if parent_binding.get("verification_status") != "verified":
        raise RfactorRecordAssemblyError(
            "parent_binding.verification_status: expected 'verified', "
            f"got {parent_binding.get('verification_status')!r}"
        )
    if parent_binding.get("family") != EXPECTED_FAMILY_ID:
        raise RfactorRecordAssemblyError(
            f"parent_binding.family: expected {EXPECTED_FAMILY_ID!r}, "
            f"got {parent_binding.get('family')!r}"
        )
    subject_id = parent_binding.get("subject_id")
    if not isinstance(subject_id, str):
        raise RfactorRecordAssemblyError(
            f"parent_binding.subject_id: expected registered subject string, got {subject_id!r}"
        )
    try:
        expected_subject = onesar_rerun.resolve_subject_spec(subject_id)
    except ValueError as exc:
        raise RfactorRecordAssemblyError(
            f"parent_binding.subject_id: {exc}"
        ) from exc
    expected_mtz = {
        "member": onesar_rerun.MTZ_MEMBER,
        "sha256": onesar_rerun.MTZ_SHA256,
        "subject_ref": onesar_rerun.MTZ_SUBJECT_REF,
    }
    if parent_binding.get("subject") != expected_subject:
        raise RfactorRecordAssemblyError(
            f"parent_binding.subject: disagrees with registered specification for {subject_id!r}"
        )
    if parent_binding.get("mtz") != expected_mtz:
        raise RfactorRecordAssemblyError(
            "parent_binding.mtz: disagrees with registered 1SAR MTZ specification"
        )

    timing_block = parent_binding.get("timing")
    if not isinstance(timing_block, Mapping):
        raise RfactorRecordAssemblyError(
            "parent_binding.timing: missing timing block from verified parent checkpoint"
        )
    try:
        validated_timing = validate_parent_execution_timing(
            timing_block.get("started_at_utc"),
            timing_block.get("finished_at_utc"),
            timing_block.get("run_date"),
            label="parent_binding.timing",
        )
    except ParentExecutionBindingError as exc:
        raise RfactorRecordAssemblyError(str(exc)) from exc
    run_date = validated_timing["run_date"]
    if (
        "run_date" in parent_binding
        and parent_binding.get("run_date") != run_date
    ):
        raise RfactorRecordAssemblyError(
            f"parent_binding.run_date: {parent_binding.get('run_date')!r} disagrees with "
            f"parent_binding.timing.run_date {run_date!r}"
        )

    identities = _resolve_rfactor_record_identities(
        subject_id,
        run_date=run_date,
        destination_rel=destination_rel,
    )
    if eval_run_id is not None and eval_run_id != identities["eval_run_id"]:
        raise RfactorRecordAssemblyError(
            f"eval_run_id: expected {identities['eval_run_id']!r} for subject {subject_id!r} "
            f"and run_date {run_date!r}, got {eval_run_id!r}"
        )

    if not isinstance(phenix_bundle, Mapping):
        raise RfactorRecordAssemblyError("phenix_bundle: must be a mapping")
    if not isinstance(refmac_bundle, Mapping):
        raise RfactorRecordAssemblyError("refmac_bundle: must be a mapping")
    if phenix_bundle.get("producer") != "phenix":
        raise RfactorRecordAssemblyError(
            f"phenix_bundle.producer: expected 'phenix', got {phenix_bundle.get('producer')!r}"
        )
    if refmac_bundle.get("producer") != "refmac":
        raise RfactorRecordAssemblyError(
            f"refmac_bundle.producer: expected 'refmac', got {refmac_bundle.get('producer')!r}"
        )
    if phenix_bundle.get("verification_status") != "verified":
        raise RfactorRecordAssemblyError(
            "phenix_bundle.verification_status: expected 'verified', "
            f"got {phenix_bundle.get('verification_status')!r}"
        )
    if refmac_bundle.get("verification_status") != "verified":
        raise RfactorRecordAssemblyError(
            "refmac_bundle.verification_status: expected 'verified' (diagnostic-only or refused "
            f"REFMAC capture cannot assemble R-factor rows), got {refmac_bundle.get('verification_status')!r}"
        )
    if (
        "cross_tool_symmetric_differences" in phenix_bundle
        and phenix_bundle.get("cross_tool_symmetric_differences") is not None
    ):
        raise RfactorRecordAssemblyError(
            "phenix_bundle.cross_tool_symmetric_differences: must be None on single-producer PHENIX result"
        )

    for prod_label, bundle in (
        ("phenix_bundle", phenix_bundle),
        ("refmac_bundle", refmac_bundle),
    ):
        if (
            bundle.get("subject_id") != subject_id
            or bundle.get("subject") != expected_subject
        ):
            raise RfactorRecordAssemblyError(
                f"{prod_label}.subject: disagrees with parent subject {subject_id!r}"
            )
        if bundle.get("mtz") != expected_mtz:
            raise RfactorRecordAssemblyError(
                f"{prod_label}.mtz: disagrees with parent 1SAR MTZ specification"
            )
        for forbidden_gap_count_key in (
            "gap_count",
            "r_free_gap_count",
            "r_free_r_work_gap_count",
        ):
            if bundle.get(forbidden_gap_count_key) is not None:
                raise RfactorRecordAssemblyError(
                    f"{prod_label}.{forbidden_gap_count_key}: gap measurement must not carry a fabricated count"
                )
            rf_map = bundle.get("rfactors")
            if isinstance(rf_map, Mapping) and rf_map.get(forbidden_gap_count_key) is not None:
                raise RfactorRecordAssemblyError(
                    f"{prod_label}.rfactors.{forbidden_gap_count_key}: gap measurement must not carry a fabricated count"
                )

    phx_work_count = _validate_positive_non_bool_int(
        phenix_bundle.get("work_count"), label="phenix_bundle.work_count"
    )
    phx_free_count = _validate_positive_non_bool_int(
        phenix_bundle.get("free_count"), label="phenix_bundle.free_count"
    )
    rm_work_count = _validate_positive_non_bool_int(
        refmac_bundle.get("work_count"), label="refmac_bundle.work_count"
    )
    rm_free_count = _validate_positive_non_bool_int(
        refmac_bundle.get("free_count"), label="refmac_bundle.free_count"
    )

    hkl_comparison = _compute_cross_tool_hkl_set_comparison(
        phenix_bundle.get("actual_work_hkls"),
        phenix_bundle.get("actual_free_hkls"),
        refmac_bundle.get("actual_work_hkls"),
        refmac_bundle.get("actual_free_hkls"),
        phenix_work_count=phx_work_count,
        phenix_free_count=phx_free_count,
        refmac_work_count=rm_work_count,
        refmac_free_count=rm_free_count,
    )

    comp_ev_ref: list[str] = []
    if cross_tool_comparison_evidence_ref is not None:
        comp_ev_ref = _validate_repo_relative_evidence_refs(
            [cross_tool_comparison_evidence_ref],
            label="cross_tool_comparison_evidence_ref",
        )

    producer_specs = (
        (
            "phenix",
            "phenix_mvd",
            "phenix.model_vs_data",
            "cctbx",
            phenix_bundle,
            phx_work_count,
            phx_free_count,
        ),
        (
            "refmac",
            "refmac5",
            "REFMAC5",
            "non_cctbx",
            refmac_bundle,
            rm_work_count,
            rm_free_count,
        ),
    )

    measurements: list[dict[str, Any]] = []
    bundle_refs_by_producer: dict[str, str] = {}
    for (
        prod_key,
        prod_slug,
        oracle_tool_ref,
        oracle_family,
        bundle,
        work_count,
        free_count,
    ) in producer_specs:
        rfactors = bundle.get("rfactors")
        if not isinstance(rfactors, Mapping):
            raise RfactorRecordAssemblyError(
                f"{prod_key}_bundle.rfactors: must be a mapping"
            )
        r_work = _validate_finite_non_bool_number(
            rfactors.get("r_work"),
            label=f"{prod_key}_bundle.rfactors.r_work",
            allow_negative=False,
        )
        r_free = _validate_finite_non_bool_number(
            rfactors.get("r_free"),
            label=f"{prod_key}_bundle.rfactors.r_free",
            allow_negative=False,
        )
        r_gap = _validate_finite_non_bool_number(
            rfactors.get("r_free_r_work_gap"),
            label=f"{prod_key}_bundle.rfactors.r_free_r_work_gap",
            allow_negative=True,
        )
        expected_gap = r_free - r_work
        if abs(r_gap - expected_gap) > 1e-9:
            raise RfactorRecordAssemblyError(
                f"{prod_key}_bundle.rfactors.r_free_r_work_gap: recorded gap {r_gap!r} "
                f"disagrees with r_free ({r_free!r}) - r_work ({r_work!r}) = {expected_gap!r}"
            )

        raw_bundle_ref = bundle.get("bundle_ref")
        if raw_bundle_ref is None:
            bundle_ref = f"{identities['eval_run_id']}_{prod_slug}_t03_bundle"
        elif isinstance(raw_bundle_ref, str) and raw_bundle_ref.strip():
            bundle_ref = raw_bundle_ref.strip()
        else:
            raise RfactorRecordAssemblyError(
                f"{prod_key}_bundle.bundle_ref: must be a non-empty string"
            )
        bundle_refs_by_producer[prod_key] = bundle_ref

        provenance_ref = _validate_optional_provenance_ref(
            bundle.get("provenance_ref"),
            label=f"{prod_key}_bundle.provenance_ref",
        )
        raw_evidence_refs = bundle.get("evidence_refs")
        base_evidence_refs = _validate_repo_relative_evidence_refs(
            raw_evidence_refs,
            label=f"{prod_key}_bundle.evidence_refs",
        )
        shared_evidence_refs = list(base_evidence_refs)
        for extra_ref in comp_ev_ref:
            if extra_ref not in shared_evidence_refs:
                shared_evidence_refs.append(extra_ref)

        if hkl_comparison["effective_sets_equal"]:
            comparison_clause = (
                "Effective work and free reflection sets match across "
                f"phenix.model_vs_data and REFMAC5 (n_work={work_count}, n_free={free_count})."
            )
        else:
            comparison_clause = (
                "Cross-tool effective reflection sets are non-comparable without set-difference "
                f"qualification: phenix.model_vs_data (n_work={phx_work_count}, n_free={phx_free_count}) vs "
                f"REFMAC5 (n_work={rm_work_count}, n_free={rm_free_count}); symmetric differences "
                f"work_only_in_phenix={len(hkl_comparison['work_only_in_phenix'])}, "
                f"work_only_in_refmac={len(hkl_comparison['work_only_in_refmac'])}, "
                f"free_only_in_phenix={len(hkl_comparison['free_only_in_phenix'])}, "
                f"free_only_in_refmac={len(hkl_comparison['free_only_in_refmac'])}."
            )
        base_note = (
            f"Fixed-coordinate T03 evaluation on archived 1SAR {subject_id} ({expected_subject['member']}, "
            f"2.50 A archived trajectory dataset; distinct from 1.80 A deposited pdb:1sar_deposited) "
            f"by {oracle_tool_ref} ({oracle_family}); component reflection counts n_work={work_count}, "
            f"n_free={free_count}. {comparison_clause}"
        )

        r_work_id = f"{identities['eval_run_id']}_{prod_slug}_T03_r_work"
        r_free_id = f"{identities['eval_run_id']}_{prod_slug}_T03_r_free"
        r_gap_id = f"{identities['eval_run_id']}_{prod_slug}_T03_r_free_r_work_gap"

        row_specs = (
            (
                r_work_id,
                "T03_r-work",
                {"value_numeric": r_work, "count": work_count},
                None,
            ),
            (
                r_free_id,
                "T03_r-free",
                {"value_numeric": r_free, "count": free_count},
                None,
            ),
            (
                r_gap_id,
                "T03_r-free_r-work_gap",
                {"value_numeric": r_gap},
                [r_work_id, r_free_id],
            ),
        )
        for row_id, metric_id, oracle_measure, derived_refs in row_specs:
            row_doc: dict[str, Any] = {
                "id": row_id,
                "catalog_task_ref": "T03",
                "metric_definition_ref": metric_id,
                "oracle_tool_ref": oracle_tool_ref,
                "oracle_family": oracle_family,
                "subject_ref": expected_subject["subject_ref"],
                "stage": expected_subject["stage"],
                "scope": "complex",
                "oracle_measure": oracle_measure,
                "pass_status": "informational",
                "bundle_ref": bundle_ref,
                "evidence_refs": list(shared_evidence_refs),
                "notes": base_note,
            }
            if provenance_ref is not None:
                row_doc["provenance_ref"] = provenance_ref
            if derived_refs is not None:
                row_doc["derived_from_measurement_refs"] = list(derived_refs)
            measurements.append(row_doc)

    if bundle_refs_by_producer["phenix"] == bundle_refs_by_producer["refmac"]:
        raise RfactorRecordAssemblyError(
            "bundle_ref: phenix.model_vs_data and REFMAC5 triples must have distinct bundle_ref identifiers"
        )

    return {
        "identities": identities,
        "measurements": measurements,
        "cross_tool_hkl_comparison": hkl_comparison,
        "phenix_bundle_ref": bundle_refs_by_producer["phenix"],
        "refmac_bundle_ref": bundle_refs_by_producer["refmac"],
    }


def _build_1sar_structure_snapshot(
    subject_id: str,
    *,
    repo_root: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Return the 1SAR Structure snapshot row for ``subject_id``."""
    onesar_rerun, _, qds_emit_contract_v4, *_ = _load_record_assembly_deps()
    try:
        subject_spec = onesar_rerun.resolve_subject_spec(subject_id)
    except ValueError as exc:
        raise RfactorRecordAssemblyError(f"subject_id: {exc}") from exc
    raw_repo_root = onesar_rerun.REPO_ROOT if repo_root is None else repo_root
    resolved_repo_root = _ensure_no_symlink_chain_to_directory(
        Path(os.fspath(raw_repo_root)), label="repo_root"
    )
    if subject_id == "R4":
        r4_eval_path = resolved_repo_root / _COMMITTED_R4_EVAL_REL_PATH
        doc = qds_emit_contract_v4.strict_yaml_load(
            r4_eval_path.read_text(encoding="utf-8")
        )
        structures = doc.get("structures") if isinstance(doc, Mapping) else None
        if not isinstance(structures, list) or not structures or not isinstance(structures[0], Mapping):
            raise RfactorRecordAssemblyError(
                f"committed R4 EVAL {r4_eval_path} has no structures[0] snapshot"
            )
        row = copy.deepcopy(dict(structures[0]))
        if (
            row.get("id") != "1sar"
            or row.get("id_kind") != "pdb"
            or row.get("method") != "xray"
            or row.get("resolution_a") != 2.5
            or row.get("space_group") != "P 21 21 21"
        ):
            raise RfactorRecordAssemblyError(
                f"committed R4 Structure snapshot has unexpected identity fields: {row!r}"
            )
        return row

    return {
        "id": "1sar",
        "id_kind": "pdb",
        "method": "xray",
        "description": (
            f"Ribonuclease Sa packaged {subject_id} ({subject_spec['stage']}) model "
            f"({subject_spec['member']}). Archived trajectory resolution 2.50 Å and space group "
            "P 21 21 21 reflect the packaged 1SAR evaluation dataset and retained input admission "
            "(distinct from the 1.80 Å deposited pdb:1sar_deposited entry)."
        ),
        "resolution_a": 2.5,
        "space_group": "P 21 21 21",
    }


def _select_live_t03_registry_and_tool_snapshots(
    *,
    issued_at: str,
    measured_metric_ids: Sequence[str] = _T03_METRIC_IDS,
    measured_tool_ids: Sequence[str] = _T03_ORACLE_TOOL_IDS,
    repo_root: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Select issue-time applicable T03 recommendations, assumptions (with predecessors), and canonical Tools."""
    try:
        _parse_strict_tz_datetime(issued_at, label="issued_at")
    except ParentExecutionBindingError as exc:
        raise RfactorRecordAssemblyError(str(exc)) from exc
    onesar_rerun, qds_emit, qds_emit_contract_v4, *_ = _load_record_assembly_deps()
    raw_repo_root = onesar_rerun.REPO_ROOT if repo_root is None else repo_root
    resolved_repo_root = _ensure_no_symlink_chain_to_directory(
        Path(os.fspath(raw_repo_root)), label="repo_root"
    )
    metric_set = set(measured_metric_ids)
    tool_set = set(measured_tool_ids)

    rec_rows = qds_emit_contract_v4._load_live_registry_rows(
        resolved_repo_root,
        "tool_recommendations.yaml",
        "tool_recommendations",
    )
    active_recs = qds_emit._active_registry_rows(
        rec_rows,
        issued_at=issued_at,
        registry_name="live tool_recommendations registry",
        supersedes_field="supersedes_recommendation_ref",
    )
    rec_by_id = {row["id"]: row for row in rec_rows}
    active_applicable_rec_ids = [
        row["id"]
        for row in active_recs
        if row.get("metric_definition_ref") in metric_set
    ]
    required_rec_ids: set[str] = set()
    for row_id in active_applicable_rec_ids:
        cursor: str | None = row_id
        while cursor is not None and cursor not in required_rec_ids:
            required_rec_ids.add(cursor)
            cursor = rec_by_id[cursor].get("supersedes_recommendation_ref")
    selected_recommendations = [
        copy.deepcopy(row) for row in rec_rows if row.get("id") in required_rec_ids
    ]

    assum_rows = qds_emit_contract_v4._load_live_registry_rows(
        resolved_repo_root,
        "tool_assumptions.yaml",
        "assumptions",
    )
    active_assumptions = qds_emit._active_registry_rows(
        assum_rows,
        issued_at=issued_at,
        registry_name="live assumptions registry",
        supersedes_field="supersedes_assumption_ref",
    )
    assum_by_id = {row["id"]: row for row in assum_rows}
    active_applicable_assum_ids = [
        row["id"]
        for row in active_assumptions
        if row.get("tool_ref") in tool_set
    ]
    required_assum_ids: set[str] = set()
    for row_id in active_applicable_assum_ids:
        cursor = row_id
        while cursor is not None and cursor not in required_assum_ids:
            required_assum_ids.add(cursor)
            cursor = assum_by_id[cursor].get("supersedes_assumption_ref")
    selected_assumptions = [
        copy.deepcopy(row) for row in assum_rows if row.get("id") in required_assum_ids
    ]

    referenced_tool_ids: set[str] = set(tool_set)
    for row in selected_recommendations:
        t_ref = row.get("tool_ref")
        if isinstance(t_ref, str) and t_ref.strip():
            referenced_tool_ids.add(t_ref)
    for row in selected_assumptions:
        t_ref = row.get("tool_ref")
        if isinstance(t_ref, str) and t_ref.strip():
            referenced_tool_ids.add(t_ref)

    catalog_doc = qds_emit_contract_v4.strict_yaml_load(
        (resolved_repo_root / "ref" / "catalog.yaml").read_text(encoding="utf-8")
    )
    catalog_tools = (
        catalog_doc.get("tools") if isinstance(catalog_doc, Mapping) else None
    )
    if not isinstance(catalog_tools, list):
        raise RfactorRecordAssemblyError(
            "ref/catalog.yaml: missing tools list"
        )
    selected_tools = [
        copy.deepcopy(row)
        for row in catalog_tools
        if isinstance(row, Mapping) and row.get("id") in referenced_tool_ids
    ]
    found_tool_ids = {row["id"] for row in selected_tools}
    missing_tools = sorted(referenced_tool_ids - found_tool_ids)
    if missing_tools:
        raise RfactorRecordAssemblyError(
            f"ref/catalog.yaml: missing referenced Tool row(s): {missing_tools}"
        )

    return {
        "issued_at": issued_at,
        "tools": selected_tools,
        "tool_recommendations": selected_recommendations,
        "active_recommendation_ids": active_applicable_rec_ids,
        "assumptions": selected_assumptions,
        "active_assumption_ids": active_applicable_assum_ids,
    }


def _validate_override_tools_against_canonical(
    override_tools: Any,
    canonical_tools: Sequence[Mapping[str, Any]],
    *,
    label: str = "registry_snapshots_override.tools",
) -> list[dict[str, Any]]:
    """Validate supplied override Tool rows against the complete canonical selected catalog rows."""
    if not isinstance(override_tools, list):
        raise RfactorRecordAssemblyError(
            f"{label}: expected list of Tool mappings, got {type(override_tools).__name__}"
        )
    canonical_by_id: dict[str, dict[str, Any]] = {
        str(row["id"]): copy.deepcopy(dict(row)) for row in canonical_tools
    }
    required_ids = set(canonical_by_id.keys())
    seen_ids: set[str] = set()
    override_by_id: dict[str, dict[str, Any]] = {}
    for idx, item in enumerate(override_tools):
        if not isinstance(item, Mapping):
            raise RfactorRecordAssemblyError(
                f"{label}[{idx}]: expected Tool mapping, got {type(item).__name__}"
            )
        raw_id = item.get("id")
        if not isinstance(raw_id, str) or not raw_id.strip():
            raise RfactorRecordAssemblyError(
                f"{label}[{idx}]: Tool row must carry a non-empty string id"
            )
        if raw_id in seen_ids:
            raise RfactorRecordAssemblyError(
                f"{label}: duplicate Tool row id {raw_id!r}"
            )
        seen_ids.add(raw_id)
        override_by_id[raw_id] = copy.deepcopy(dict(item))

    missing_ids = sorted(required_ids - seen_ids)
    if missing_ids:
        raise RfactorRecordAssemblyError(
            f"{label}: missing required canonical Tool row(s): {missing_ids}"
        )
    extra_ids = sorted(seen_ids - required_ids)
    if extra_ids:
        raise RfactorRecordAssemblyError(
            f"{label}: unexpected extra Tool row(s) not in canonical selection: {extra_ids}"
        )
    for row in canonical_tools:
        tool_id = str(row["id"])
        canonical_row = canonical_by_id[tool_id]
        supplied_row = override_by_id[tool_id]
        if supplied_row != canonical_row:
            missing_keys = sorted(set(canonical_row.keys()) - set(supplied_row.keys()))
            extra_keys = sorted(set(supplied_row.keys()) - set(canonical_row.keys()))
            altered_keys = sorted(
                k
                for k in canonical_row.keys() & supplied_row.keys()
                if supplied_row[k] != canonical_row[k]
            )
            raise RfactorRecordAssemblyError(
                f"{label}[{tool_id!r}]: Tool row disagrees with complete canonical catalog Tool row "
                f"(missing_keys={missing_keys}, extra_keys={extra_keys}, altered_keys={altered_keys})"
            )
    return [copy.deepcopy(override_by_id[str(row["id"])]) for row in canonical_tools]


def _write_exclusive_staged_leaf_bytes(
    leaf_path: Path,
    payload: bytes,
    *,
    staging_dir: Path,
    label: str,
) -> Path:
    """Create ``leaf_path`` inside ``staging_dir`` exclusively with ``O_CREAT | O_EXCL`` and write ``payload``.

    Requires an exclusive fresh attempt leaf in ``staging_dir``: refuses any
    pre-existing regular file, symlink (including dangling), hardlink, or
    non-regular entry without opening, truncating, unlinking, or modifying it.
    Private ``.txt`` staging artifacts are diagnostic evidence; on post-create
    check or write failure, the owned descriptor is closed and any created partial
    ``.txt`` file or replacement is retained untouched while the original
    exception propagates. If ``os.close(fd)`` also fails after a primary
    exception, the primary exception object and traceback are preserved with a
    close diagnostic note; a close-only ``OSError`` propagates directly.
    """
    if not isinstance(payload, (bytes, bytearray)):
        raise RfactorRecordAssemblyError(
            f"{label}: expected bytes payload, got {type(payload).__name__}"
        )
    resolved_staging_dir = _ensure_no_symlink_chain_to_directory(
        staging_dir, label=f"{label}.staging_dir"
    )
    leaf_name = leaf_path.name
    if (
        not leaf_name
        or leaf_name in (".", "..")
        or "/" in leaf_name
        or "\\" in leaf_name
        or leaf_path.parent != resolved_staging_dir
    ):
        raise RfactorRecordAssemblyError(
            f"{label}: staged leaf {leaf_path} must be a direct child of {resolved_staging_dir}"
        )
    target_path = resolved_staging_dir / leaf_name
    try:
        existing_st = os.lstat(target_path)
    except FileNotFoundError:
        existing_st = None
    except OSError as exc:
        raise RfactorRecordAssemblyError(
            f"{label}: unable to inspect staged leaf {target_path} ({type(exc).__name__}): {exc}"
        ) from exc
    if existing_st is not None:
        if stat.S_ISLNK(existing_st.st_mode):
            raise RfactorRecordAssemblyError(
                f"{label}: refusing to overwrite pre-existing symlink at staged leaf {target_path}"
            )
        if existing_st.st_nlink > 1:
            raise RfactorRecordAssemblyError(
                f"{label}: refusing to overwrite pre-existing hardlinked file "
                f"(st_nlink={existing_st.st_nlink}) at staged leaf {target_path}"
            )
        raise RfactorRecordAssemblyError(
            f"{label}: refusing to overwrite pre-existing file at staged leaf {target_path}"
        )

    open_flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    try:
        fd = os.open(target_path, open_flags, 0o600)
    except FileExistsError as exc:
        raise RfactorRecordAssemblyError(
            f"{label}: refusing to overwrite pre-existing path at staged leaf {target_path}"
        ) from exc
    except OSError as exc:
        raise RfactorRecordAssemblyError(
            f"{label}: exclusive creation failed for staged leaf {target_path} "
            f"({type(exc).__name__}): {exc}"
        ) from exc

    primary_exc: BaseException | None = None
    try:
        fd_st = os.fstat(fd)
        path_st = os.lstat(target_path)
        if (
            not stat.S_ISREG(fd_st.st_mode)
            or stat.S_ISLNK(path_st.st_mode)
            or fd_st.st_ino != path_st.st_ino
            or fd_st.st_dev != path_st.st_dev
            or fd_st.st_nlink != 1
        ):
            raise RfactorRecordAssemblyError(
                f"{label}: staged leaf {target_path} failed post-create regular single-link inode check"
            )
        view = memoryview(bytes(payload))
        total_written = 0
        while total_written < len(view):
            written = os.write(fd, view[total_written:])
            if written <= 0:
                raise RfactorRecordAssemblyError(
                    f"{label}: short write on staged leaf {target_path}"
                )
            total_written += written
    except BaseException as exc:
        primary_exc = exc
        raise
    finally:
        try:
            os.close(fd)
        except OSError as close_exc:
            if primary_exc is None:
                raise
            primary_exc.add_note(
                f"{label}: os.close({fd}) also failed on staged leaf {target_path} "
                f"({type(close_exc).__name__}): {close_exc}"
            )
    return target_path


def _validate_original_container_mapping(
    document: Mapping[str, Any],
    *,
    label: str,
) -> None:
    """Validate an original YAML document mapping before coercion and via Container.model_validate."""
    *_, models, ValidationError, _ = _load_record_assembly_deps()
    if not isinstance(document, Mapping):
        raise RfactorRecordAssemblyError(f"{label}: expected mapping document")
    eval_runs = document.get("evaluation_runs")
    if isinstance(eval_runs, list):
        for run_idx, run in enumerate(eval_runs):
            if not isinstance(run, Mapping):
                raise RfactorRecordAssemblyError(
                    f"{label}.evaluation_runs[{run_idx}]: expected mapping"
                )
            measurements = run.get("measurements")
            if isinstance(measurements, list):
                for m_idx, row in enumerate(measurements):
                    row_label = f"{label}.evaluation_runs[{run_idx}].measurements[{m_idx}]"
                    if not isinstance(row, Mapping):
                        raise RfactorRecordAssemblyError(
                            f"{row_label}: expected mapping"
                        )
                    _validate_optional_provenance_ref(
                        row.get("provenance_ref"),
                        label=f"{row_label}.provenance_ref",
                    )
                    om = row.get("oracle_measure")
                    if not isinstance(om, Mapping):
                        raise RfactorRecordAssemblyError(
                            f"{row_label}.oracle_measure: expected mapping"
                        )
                    if "value_numeric" in om and om["value_numeric"] is not None:
                        _validate_finite_non_bool_number(
                            om["value_numeric"],
                            label=f"{row_label}.oracle_measure.value_numeric",
                        )
                    metric_ref = row.get("metric_definition_ref")
                    if metric_ref in ("T03_r-work", "T03_r-free"):
                        _validate_positive_non_bool_int(
                            om.get("count"),
                            label=f"{row_label}.oracle_measure.count",
                        )
                    elif metric_ref == "T03_r-free_r-work_gap":
                        if om.get("count") is not None:
                            raise RfactorRecordAssemblyError(
                                f"{row_label}.oracle_measure.count: gap row must not carry a fabricated count"
                            )
                    if row.get("catalog_task_ref") == "T03":
                        if row.get("pass_status") != "informational":
                            raise RfactorRecordAssemblyError(
                                f"{row_label}.pass_status: expected 'informational' for T03 row, "
                                f"got {row.get('pass_status')!r}"
                            )
                        for forbidden_key in _FORBIDDEN_T03_INFORMATIONAL_FIELDS:
                            if row.get(forbidden_key) is not None:
                                raise RfactorRecordAssemblyError(
                                    f"{row_label}.{forbidden_key}: forbidden on informational T03 row"
                                )
    try:
        models.Container.model_validate(dict(document))
    except ValidationError as exc:
        raise RfactorRecordAssemblyError(
            f"{label}: Container schema validation failed: {exc}"
        ) from exc


def _build_contract4_replay_pin(
    *,
    pin_id: str,
    qds: Mapping[str, Any],
    projection: Mapping[str, Any],
) -> dict[str, Any]:
    """Compute the owner-carried Contract-4 QDS replay pin from the emitted QDS and projection."""
    _, _, qds_emit_contract_v4, check_qds_trust_invariant, *_ = (
        _load_record_assembly_deps()
    )
    if not isinstance(pin_id, str) or not pin_id.strip():
        raise RfactorRecordAssemblyError("pin_id: must be a non-empty string")
    context = projection["context"]
    canonical_qds_bytes = check_qds_trust_invariant._canonical_qds_text(
        dict(qds)
    ).encode("utf-8")
    emitter_bytes = Path(qds_emit_contract_v4.__file__).read_bytes()
    return {
        "id": pin_id.strip(),
        "qds_ref": str(qds["id"]),
        "source_evaluation_run_refs": [
            str(run["id"]) for run in projection["raw_runs"]
        ],
        "qds_emission_context_ref": str(context["id"]),
        "emitter_contract_version": "4",
        "canonical_qds_sha256": hashlib.sha256(canonical_qds_bytes).hexdigest(),
        "emitter_source_sha256": hashlib.sha256(emitter_bytes).hexdigest(),
        "source_tools_sha256": check_qds_trust_invariant._snapshot_digest(
            "tools", projection["tools"]
        ),
        "source_structures_sha256": check_qds_trust_invariant._snapshot_digest(
            "structures", projection["structures"]
        ),
        "source_tool_recommendations_sha256": (
            check_qds_trust_invariant._snapshot_digest(
                "tool_recommendations", projection["tool_recommendations"]
            )
        ),
        "source_tool_assumptions_sha256": (
            check_qds_trust_invariant._snapshot_digest(
                "assumptions", projection["assumptions"]
            )
        ),
        "source_qds_emission_context_sha256": (
            check_qds_trust_invariant._snapshot_digest(
                "qds_emission_contexts", [context]
            )
        ),
        "source_evaluation_runs_sha256": (
            check_qds_trust_invariant._snapshot_digest(
                "evaluation_runs", projection["raw_runs"]
            )
        ),
    }


def _prepare_rfactor_eval_and_live_qds_records(
    *,
    parent_binding: Mapping[str, Any],
    phenix_bundle: Mapping[str, Any],
    refmac_bundle: Mapping[str, Any],
    staging_dir: str | os.PathLike[str],
    issued_at: str | None = None,
    destination_rel: str = DEFAULT_RECORD_DESTINATION_REL,
    repo_root: str | os.PathLike[str] | None = None,
    cross_tool_comparison_evidence_ref: str | None = None,
    registry_snapshots_override: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble and validate 1SAR T03 EVAL (and for R4, live partial QDS + Contract-4 replay pin).

    Requires an exclusive fresh attempt ``staging_dir`` (no pre-existing staged
    ``.txt`` leaves). Stages pre-pin and post-pin YAML bytes exclusively under
    ``staging_dir`` as ``.txt`` files without writing any canonical ``EVAL_*.yaml``
    or ``QDS_*.yaml`` files, and retains any created ``.txt`` staging artifacts as
    diagnostic evidence on emitter, replay-pin, or subsequent leaf failure rather
    than rolling them back or unlinking them. Calls public ``qds_emit.emit_qds``
    with default live admission (Contract 4, ``require_pinned_tool_snapshot=False``)
    for R4, and preserves ``QdsCompletenessError`` and ``SystemExit`` without
    swallowing ``KeyboardInterrupt``.
    """
    (
        onesar_rerun,
        qds_emit,
        qds_emit_contract_v4,
        check_qds_trust_invariant,
        _,
        _,
        yaml,
    ) = _load_record_assembly_deps()

    raw_repo_root = onesar_rerun.REPO_ROOT if repo_root is None else repo_root
    resolved_repo_root = _ensure_no_symlink_chain_to_directory(
        Path(os.fspath(raw_repo_root)), label="repo_root"
    )
    resolved_staging_dir = _ensure_no_symlink_chain_to_directory(
        Path(os.fspath(staging_dir)), label="staging_dir"
    )

    assembled = _assemble_six_row_t03_measurements(
        parent_binding=parent_binding,
        phenix_bundle=phenix_bundle,
        refmac_bundle=refmac_bundle,
        cross_tool_comparison_evidence_ref=cross_tool_comparison_evidence_ref,
        destination_rel=destination_rel,
    )
    identities = assembled["identities"]
    subject_id = identities["subject_id"]
    run_date = identities["run_date"]
    hkl_comparison = assembled["cross_tool_hkl_comparison"]

    effective_issued_at = (
        issued_at
        if issued_at is not None
        else str(parent_binding["timing"]["finished_at_utc"])
    )
    try:
        parsed_issued_at = _parse_strict_tz_datetime(
            effective_issued_at,
            label="issued_at",
        )
    except ParentExecutionBindingError as exc:
        raise RfactorRecordAssemblyError(str(exc)) from exc
    issued_utc_date = parsed_issued_at.astimezone(timezone.utc).date().isoformat()
    if issued_utc_date < run_date:
        raise RfactorRecordAssemblyError(
            f"issued_at UTC date {issued_utc_date!r} precedes evaluation run_date {run_date!r}"
        )

    structure_row = _build_1sar_structure_snapshot(
        subject_id, repo_root=resolved_repo_root
    )
    canonical_registry_snapshots = _select_live_t03_registry_and_tool_snapshots(
        issued_at=effective_issued_at,
        repo_root=resolved_repo_root,
    )
    if registry_snapshots_override is not None:
        if not isinstance(registry_snapshots_override, Mapping):
            raise RfactorRecordAssemblyError(
                "registry_snapshots_override: must be a mapping when provided"
            )
        for req_key in ("tools", "tool_recommendations", "assumptions"):
            if req_key not in registry_snapshots_override or not isinstance(
                registry_snapshots_override[req_key], list
            ):
                raise RfactorRecordAssemblyError(
                    f"registry_snapshots_override.{req_key}: must be a list"
                )
        validated_override_tools = _validate_override_tools_against_canonical(
            registry_snapshots_override["tools"],
            canonical_registry_snapshots["tools"],
            label="registry_snapshots_override.tools",
        )
        registry_snapshots = {
            "issued_at": effective_issued_at,
            "tools": validated_override_tools,
            "tool_recommendations": copy.deepcopy(
                list(registry_snapshots_override["tool_recommendations"])
            ),
            "assumptions": copy.deepcopy(
                list(registry_snapshots_override["assumptions"])
            ),
            "active_recommendation_ids": list(
                registry_snapshots_override.get(
                    "active_recommendation_ids",
                    canonical_registry_snapshots["active_recommendation_ids"],
                )
            ),
            "active_assumption_ids": list(
                registry_snapshots_override.get(
                    "active_assumption_ids",
                    canonical_registry_snapshots["active_assumption_ids"],
                )
            ),
        }
    else:
        registry_snapshots = canonical_registry_snapshots

    eval_document: dict[str, Any] = {
        "structures": [structure_row],
        "tools": copy.deepcopy(registry_snapshots["tools"]),
        "tool_recommendations": copy.deepcopy(
            registry_snapshots["tool_recommendations"]
        ),
        "assumptions": copy.deepcopy(registry_snapshots["assumptions"]),
        "evaluation_runs": [
            {
                "id": identities["eval_run_id"],
                "eval_filename_stem": identities["eval_filename_stem"],
                "structure_ref": "1sar",
                "run_date": run_date,
                "catalog_tasks_applied": ["T03"],
                "measurements": copy.deepcopy(assembled["measurements"]),
            }
        ],
    }

    if identities["emits_qds"]:
        assert identities["qds_id"] is not None
        assert identities["emission_context_id"] is not None
        assert identities["replay_pin_id"] is not None
        if hkl_comparison["effective_sets_equal"]:
            set_note = (
                "Both producers evaluated identical work and free reflection sets "
                f"(n_work={hkl_comparison['phenix_work_count']}, n_free={hkl_comparison['phenix_free_count']})."
            )
        else:
            set_note = (
                "Cross-tool effective reflection sets are non-comparable without set-difference "
                f"qualification (phenix.model_vs_data n_work={hkl_comparison['phenix_work_count']}, "
                f"n_free={hkl_comparison['phenix_free_count']} vs REFMAC5 "
                f"n_work={hkl_comparison['refmac_work_count']}, n_free={hkl_comparison['refmac_free_count']})."
            )
        scope_notes = (
            "Partial R4 T03 R-factor-only sheet on archived data/1sar_final.pdb (2.50 A archived "
            "trajectory dataset; distinct from 1.80 A deposited pdb:1sar_deposited). Covers T03 "
            "(R-work, R-free, R-free-R-work gap) across phenix.model_vs_data (cctbx) and REFMAC5 "
            f"(non_cctbx) only. {set_note}"
        )
        headline_verdict = (
            "Informational T03 R-factor capture on archived 1SAR R4 final model across "
            "phenix.model_vs_data (cctbx) and REFMAC5 (non_cctbx); no quality pass verdict or "
            f"cross-producer averaging is claimed. {set_note}"
        )
        eval_document["qds_emission_contexts"] = [
            {
                "id": identities["emission_context_id"],
                "qds_ref": identities["qds_id"],
                "owner_evaluation_run_ref": identities["eval_run_id"],
                "snapshot_owner_evaluation_run_ref": identities["eval_run_id"],
                "structure_ref": "1sar",
                "subject_ref": identities["subject"]["subject_ref"],
                "source_evaluation_run_refs": [identities["eval_run_id"]],
                "issued_at": effective_issued_at,
                "coverage_scope": "partial",
                "scope_notes": scope_notes,
                "identity_description": structure_row["description"],
                "headline_verdict": headline_verdict,
            }
        ]

    _validate_original_container_mapping(
        eval_document, label="pre_pin_eval_document"
    )
    pre_pin_yaml_text = yaml.safe_dump(
        eval_document,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )

    staged_pre_pin_txt_path = _write_exclusive_staged_leaf_bytes(
        resolved_staging_dir / f"{identities['eval_filename_stem']}.pre_pin.txt",
        pre_pin_yaml_text.encode("utf-8"),
        staging_dir=resolved_staging_dir,
        label="staged_pre_pin_eval_txt_path",
    )

    qds_doc: dict[str, Any] | None = None
    qds_yaml_text: str | None = None
    qds_yaml_bytes: bytes | None = None
    qds_sha256: str | None = None
    staged_qds_txt_path: Path | None = None
    projection: dict[str, Any] | None = None
    replay_pin: dict[str, Any] | None = None

    if identities["emits_qds"]:
        assert identities["qds_id"] is not None
        assert identities["replay_pin_id"] is not None
        qds_doc = qds_emit.emit_qds(
            [staged_pre_pin_txt_path],
            qds_id=identities["qds_id"],
            structure_id="1sar",
        )
        _validate_original_container_mapping(
            {"quality_data_sheets": [qds_doc]},
            label="emitted_qds_document",
        )
        projection = qds_emit_contract_v4.prepare_projection(
            [copy.deepcopy(eval_document)],
            identities["qds_id"],
            "1sar",
            repo_root=resolved_repo_root,
        )
        replay_pin = _build_contract4_replay_pin(
            pin_id=identities["replay_pin_id"],
            qds=qds_doc,
            projection=projection,
        )
        eval_document["qds_replay_pins"] = [copy.deepcopy(replay_pin)]
        _validate_original_container_mapping(
            eval_document, label="pinned_eval_document",
        )
        qds_yaml_text = check_qds_trust_invariant._canonical_qds_text(qds_doc)
        qds_yaml_bytes = qds_yaml_text.encode("utf-8")
        qds_sha256 = hashlib.sha256(qds_yaml_bytes).hexdigest()
        staged_qds_txt_path = _write_exclusive_staged_leaf_bytes(
            resolved_staging_dir / f"{identities['qds_id']}.staged.txt",
            qds_yaml_bytes,
            staging_dir=resolved_staging_dir,
            label="staged_qds_txt_path",
        )
        pin_errors = check_qds_trust_invariant._validate_contract_4_pin(
            staged_qds_txt_path,
            qds_doc,
            projection,
            eval_document["qds_replay_pins"],
        )
        if pin_errors:
            raise RfactorRecordAssemblyError(
                f"contract-4 replay pin validation failed: {pin_errors}"
            )

    eval_yaml_text = yaml.safe_dump(
        eval_document,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )
    eval_yaml_bytes = eval_yaml_text.encode("utf-8")
    eval_sha256 = hashlib.sha256(eval_yaml_bytes).hexdigest()
    staged_eval_txt_path = _write_exclusive_staged_leaf_bytes(
        resolved_staging_dir / f"{identities['eval_filename_stem']}.staged.txt",
        eval_yaml_bytes,
        staging_dir=resolved_staging_dir,
        label="staged_eval_txt_path",
    )

    return {
        "identities": identities,
        "eval_document": copy.deepcopy(eval_document),
        "eval_yaml_text": eval_yaml_text,
        "eval_yaml_bytes": eval_yaml_bytes,
        "eval_sha256": eval_sha256,
        "staged_pre_pin_eval_txt_path": staged_pre_pin_txt_path,
        "staged_eval_txt_path": staged_eval_txt_path,
        "qds_document": copy.deepcopy(qds_doc) if qds_doc is not None else None,
        "qds_yaml_text": qds_yaml_text,
        "qds_yaml_bytes": qds_yaml_bytes,
        "qds_sha256": qds_sha256,
        "staged_qds_txt_path": staged_qds_txt_path,
        "projection": projection,
        "replay_pin": copy.deepcopy(replay_pin) if replay_pin is not None else None,
        "cross_tool_hkl_comparison": hkl_comparison,
        "registry_snapshots": registry_snapshots,
    }

