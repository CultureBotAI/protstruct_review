#!/usr/bin/env python3
"""Result-free Stage 2 PHENIX development exclusion and provider metadata witness generators.

Scope and epistemic boundary:
- Registration status remains ``selected_decisions_recorded`` (NOT ``frozen_result_free``).
- :func:`build_dev_exclusions` compiles the deterministic 23-accession development exclusion
  manifest from the committed Round-2 negative-control record (22 source-attested entries)
  and the committed ``1SAR`` assessment provenance record (1 accession with 6 locally
  byte-verified retained subjects: starting model, packaged R4 final model, retained R5 and
  R6 intermediate models, original input MTZ, and deposited reference coordinate file).
  It copies only whitelisted identity, hash, and column-selector provenance fields, never
  copying refinement outcomes, R-factor values, or atom/B-factor inventories.
- :func:`inspect_provider_metadata` performs a static, read-only filesystem walk of
  ``prefix/lib/python3.9/site-packages`` (including hidden and gitignored entries) without
  importing vendor modules, calling ``importlib.metadata``, executing ``.pth`` files,
  instantiating provider clients, or running external commands. It parses ``METADATA`` and
  ``PKG-INFO`` files via stdlib ``email.parser`` (requiring a single non-empty ``Name`` and
  ``Version`` header per file and retaining only portable ``PHENIX_PREFIX`` path, SHA-256,
  name, and version), inspects exact top-level native adapter paths
  (``langchain_openai``, ``langchain_google_genai``, ``langchain_ollama``), and fails closed
  on escaping symlinks, broken/cyclic/ambiguous symlinks, or traversal/read errors.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import email.parser
import email.policy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from typing import Any
import zipfile

REPO_ROOT = Path(__file__).resolve().parent.parent

REGISTRATION_STATUS = "selected_decisions_recorded"
PORTABLE_PHENIX_PREFIX = "PHENIX_PREFIX"
SITE_PACKAGES_REL_PATH = "lib/python3.9/site-packages"

APPROVED_SELECTIONS_PATH = (
    "ref/research/phenix_step1_user_selections_2026-11-15.md"
)
APPROVED_SELECTIONS_SHA256 = (
    "14bbb0c9dc1883c2404f40193e135a4aaa974d8ab605fe95bb78d44c6a704a7b"
)

ROUND2_ENROLLED_PATH = "ref/research/data/negative_control_round2_enrolled.json"
ROUND2_ENROLLED_SHA256 = (
    "02fc974da9d1f8a2d8fb3c496c13196c200b31d182f1b7323cb25dcc59cbe7da"
)
ROUND2_EXPECTED_COUNT = 22

ASSESSMENT_1SAR_PATH = (
    "ref/research/data/refinement_assessment_1sar_and_controls_2026-10-18.json"
)
ASSESSMENT_1SAR_SHA256 = (
    "db100e926bfcf6331c303087846c4d51117a4411c6afdf58877aada5dbf14245"
)

TOTAL_EXCLUDED_ACCESSIONS_COUNT = 23
ONESAR_ACCESSION = "1SAR"
ONESAR_CASE_ID = "1sar_cdba2c07_2026-09-23"
ONESAR_ARTIFACT_ID = "cdba2c07-daff-4f60-ae96-12452b3a5fbb"
ONESAR_ARCHIVE_PATH = (
    "data/coscientists/openscientist/"
    "cdba2c07-daff-4f60-ae96-12452b3a5fbb_artifacts.zip"
)
ONESAR_ARCHIVE_SHA256 = (
    "9fc5352284b7ffa7763c633a3eb4d3d0db96b8c25a1be9bcea361722d2c53054"
)
ONESAR_START_MEMBER = "data/1sar.pdb"
ONESAR_START_SHA256 = (
    "6b34c5d0dec6647df20eae9021ff7d511d6dedc03b4349c0b634d8e5b1f869e4"
)
ONESAR_R4_FINAL_MEMBER = "data/1sar_final.pdb"
ONESAR_R4_FINAL_SHA256 = (
    "8cbc1650f8be5a3833f98833fa514ec7d490c2c3bb9aa930413abac05e2a510b"
)
ONESAR_R5_MEMBER = "data/1sar_round5.pdb"
ONESAR_R5_SHA256 = (
    "25c140b46e18a1d1ec211d985868894f227c827ea0c76f7187d41e1f75c03733"
)
ONESAR_R6_MEMBER = "data/1sar_round6.pdb"
ONESAR_R6_SHA256 = (
    "5d01ce3645d1295a42f620987785fd8368441418e82a0b6d6992d7f79500c110"
)
ONESAR_R7_MEMBER = "data/1sar_round7.pdb"
ONESAR_INPUT_MTZ_MEMBER = "data/1sar.mtz"
ONESAR_INPUT_MTZ_SHA256 = (
    "f36d5fe685a3e524e8809d17d19ce12073acdf339eba2cfd3b0347a818850ab2"
)
ONESAR_DEPOSITED_PDB_PATH = "data/pdb_mtz/1sar_deposited.pdb"
ONESAR_DEPOSITED_PDB_SHA256 = (
    "e60e5db6c7eb554a3ac4e184bdf7cbb7d69b682e287579bdcf5f8bf279d51f86"
)

STATIC_LANGCHAIN_WITNESS_PATH = (
    "ref/research/data/phenix_langchain_static_witness_2026-11-15.json"
)
STATIC_LANGCHAIN_WITNESS_SHA256 = (
    "692a0b4e082ac5f56622ca6c61b457120efa00542545c12e1672f66c01c9ec0f"
)
STATIC_LANGCHAIN_WITNESS_FILE_COUNT = 44

METADATA_FILENAMES: tuple[str, str] = ("METADATA", "PKG-INFO")
PROVIDER_QUERY_SUBSTRINGS: tuple[str, ...] = (
    "openai",
    "google",
    "ollama",
    "langchain",
)
NATIVE_ADAPTER_NAMES: tuple[str, ...] = (
    "langchain_openai",
    "langchain_google_genai",
    "langchain_ollama",
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}\Z")
_PDB_ID_RE = re.compile(r"^[1-9][A-Z0-9]{3}\Z")
_ROUND2_HASH_KEYS: tuple[str, ...] = ("model", "mtz", "cif", "validation_xml")
_MAX_SYMLINK_HOPS = 40


def _validate_sha256(value: Any, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or _SHA256_RE.fullmatch(value) is None
    ):
        raise ValueError(
            f"{field_name} must be a 64-character lowercase hex SHA-256 digest, "
            f"got {value!r}."
        )
    return value


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, val in pairs:
        if key in out:
            raise ValueError(f"Duplicate JSON object key {key!r}.")
        out[key] = val
    return out


def _normalize_strict_json_value(value: Any, *, field_name: str) -> Any:
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{field_name} contains non-finite float {value!r}.")
        return value
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if not isinstance(k, str) or not k.strip():
                raise ValueError(
                    f"{field_name} mapping keys must be non-empty strings, got {k!r}."
                )
            out[k] = _normalize_strict_json_value(v, field_name=f"{field_name}.{k}")
        return out
    if isinstance(value, (list, tuple)):
        return [
            _normalize_strict_json_value(item, field_name=f"{field_name}[{idx}]")
            for idx, item in enumerate(value)
        ]
    raise ValueError(
        f"{field_name} contains unsupported non-JSON value {value!r} "
        f"({type(value).__name__})."
    )


def canonical_json_bytes(record: Mapping[str, Any]) -> bytes:
    """Serialize a strict JSON mapping deterministically to UTF-8 bytes."""
    if not isinstance(record, Mapping):
        raise ValueError(
            f"canonical_json_bytes requires a mapping, got {type(record).__name__}."
        )
    normalized = _normalize_strict_json_value(record, field_name="record")
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_json_sha256(record: Mapping[str, Any]) -> str:
    """Return the lowercase 64-hex SHA-256 digest of :func:`canonical_json_bytes`."""
    return hashlib.sha256(canonical_json_bytes(record)).hexdigest()


def _read_verified_repo_bytes(
    root: Path,
    rel_path: str,
    expected_sha256: str,
) -> bytes:
    full_path = root / rel_path
    try:
        st = os.stat(full_path)
        if not stat.S_ISREG(st.st_mode):
            raise ValueError(f"Expected regular file at {rel_path!r}.")
        raw = full_path.read_bytes()
    except OSError as exc:
        raise ValueError(f"Could not read required source file {rel_path!r}.") from exc

    actual_sha = hashlib.sha256(raw).hexdigest()
    if actual_sha != expected_sha256:
        raise ValueError(
            f"SHA-256 mismatch for {rel_path!r}: expected {expected_sha256}, "
            f"got {actual_sha}."
        )
    return raw


def _parse_round2_exclusions(
    round2_doc: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[str], set[str]]:
    if round2_doc.get("n_enrolled") != ROUND2_EXPECTED_COUNT:
        raise ValueError(
            f"{ROUND2_ENROLLED_PATH} n_enrolled must be {ROUND2_EXPECTED_COUNT}, "
            f"got {round2_doc.get('n_enrolled')!r}."
        )
    entries = round2_doc.get("entries")
    if not isinstance(entries, list) or len(entries) != ROUND2_EXPECTED_COUNT:
        raise ValueError(
            f"{ROUND2_ENROLLED_PATH} entries must be a list of length "
            f"{ROUND2_EXPECTED_COUNT}."
        )

    rows: list[dict[str, Any]] = []
    pdb_ids: list[str] = []
    seen_pdb_ids: set[str] = set()
    all_round2_hashes: set[str] = set()

    for idx, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            raise ValueError(f"Round-2 entry[{idx}] must be a mapping.")
        pdb_id = entry.get("pdb_id")
        if not isinstance(pdb_id, str) or _PDB_ID_RE.fullmatch(pdb_id) is None:
            raise ValueError(
                f"Round-2 entry[{idx}] pdb_id must be a 4-character uppercase PDB ID, "
                f"got {pdb_id!r}."
            )
        if pdb_id in seen_pdb_ids:
            raise ValueError(
                f"Duplicate pdb_id {pdb_id!r} in {ROUND2_ENROLLED_PATH} at index {idx}."
            )
        if pdb_id == ONESAR_ACCESSION:
            raise ValueError(
                f"{ONESAR_ACCESSION!r} must be a separate exclusion and cannot appear "
                f"in {ROUND2_ENROLLED_PATH}."
            )
        if entry.get("enrolled") is not True:
            raise ValueError(
                f"Round-2 entry[{idx}] ({pdb_id}) must have enrolled=True."
            )

        input_hashes_raw = entry.get("input_hashes")
        if not isinstance(input_hashes_raw, Mapping) or set(
            input_hashes_raw.keys()
        ) != set(_ROUND2_HASH_KEYS):
            raise ValueError(
                f"Round-2 entry[{idx}] ({pdb_id}) input_hashes must contain exact keys "
                f"{_ROUND2_HASH_KEYS}."
            )
        input_hashes: dict[str, str] = {}
        for k in _ROUND2_HASH_KEYS:
            digest = _validate_sha256(
                input_hashes_raw[k],
                field_name=f"entries[{idx}].input_hashes.{k}",
            )
            input_hashes[k] = digest
            all_round2_hashes.add(digest)

        array_sel_raw = entry.get("array_selection")
        if not isinstance(array_sel_raw, Mapping) or set(array_sel_raw.keys()) != {
            "obs",
            "free_flag",
        }:
            raise ValueError(
                f"Round-2 entry[{idx}] ({pdb_id}) array_selection must contain exact "
                "keys ('obs', 'free_flag')."
            )
        obs_raw = array_sel_raw.get("obs")
        free_flag_raw = array_sel_raw.get("free_flag")
        if (
            not isinstance(obs_raw, list)
            or len(obs_raw) != 2
            or not all(
                isinstance(lbl, str) and bool(lbl.strip()) and lbl == lbl.strip()
                for lbl in obs_raw
            )
            or obs_raw[0] == obs_raw[1]
        ):
            raise ValueError(
                f"Round-2 entry[{idx}] ({pdb_id}) array_selection.obs must be two "
                f"distinct non-empty strings, got {obs_raw!r}."
            )
        if (
            not isinstance(free_flag_raw, str)
            or not free_flag_raw.strip()
            or free_flag_raw != free_flag_raw.strip()
            or free_flag_raw in obs_raw
        ):
            raise ValueError(
                f"Round-2 entry[{idx}] ({pdb_id}) array_selection.free_flag must be a "
                f"distinct non-empty string, got {free_flag_raw!r}."
            )

        seen_pdb_ids.add(pdb_id)
        pdb_ids.append(pdb_id)
        rows.append(
            {
                "entry_index": idx,
                "pdb_id": pdb_id,
                "exclusion_group": "negative_control_round2_enrolled",
                "source_path": ROUND2_ENROLLED_PATH,
                "source_sha256": ROUND2_ENROLLED_SHA256,
                "source_pointer": f"/entries/{idx}",
                "verification_mode": "source_attested",
                "local_bytes_verified": False,
                "execution_ready_input_bundle": False,
                "input_hashes": input_hashes,
                "input_hash_pointers": {
                    "model": f"/entries/{idx}/input_hashes/model",
                    "mtz": f"/entries/{idx}/input_hashes/mtz",
                    "cif": f"/entries/{idx}/input_hashes/cif",
                    "validation_xml": f"/entries/{idx}/input_hashes/validation_xml",
                },
                "cif_role": "deposited_structural_mmcif_not_ligand_restraint_cif",
                "array_selection": {
                    "obs": [obs_raw[0], obs_raw[1]],
                    "free_flag": free_flag_raw,
                },
                "column_selector_pointers": {
                    "obs": f"/entries/{idx}/array_selection/obs",
                    "obs_f": f"/entries/{idx}/array_selection/obs/0",
                    "obs_sigf": f"/entries/{idx}/array_selection/obs/1",
                    "free_flag": f"/entries/{idx}/array_selection/free_flag",
                },
                "test_flag_values_recorded_in_source": False,
            }
        )

    return rows, pdb_ids, all_round2_hashes


def _build_onesar_exclusion(
    root: Path,
    assessment_doc: Mapping[str, Any],
    round2_hashes: set[str],
) -> dict[str, Any]:
    case_block = assessment_doc.get("case_study_1sar")
    if not isinstance(case_block, Mapping):
        raise ValueError(f"{ASSESSMENT_1SAR_PATH} missing case_study_1sar mapping.")
    if case_block.get("case_id") != ONESAR_CASE_ID:
        raise ValueError(
            f"Unexpected case_study_1sar.case_id {case_block.get('case_id')!r}."
        )
    prov = case_block.get("provenance")
    if not isinstance(prov, Mapping):
        raise ValueError(
            f"{ASSESSMENT_1SAR_PATH} missing case_study_1sar.provenance mapping."
        )

    if prov.get("archive_path") != ONESAR_ARCHIVE_PATH:
        raise ValueError(
            f"Provenance archive_path mismatch: {prov.get('archive_path')!r}."
        )
    if prov.get("archive_sha256") != ONESAR_ARCHIVE_SHA256:
        raise ValueError(
            f"Provenance archive_sha256 mismatch: {prov.get('archive_sha256')!r}."
        )

    start_prov = prov.get("starting_model")
    final_prov = prov.get("packaged_final_model")
    dep_prov = prov.get("deposited_reference_model")
    refl_prov = prov.get("reflection_data")
    if (
        not isinstance(start_prov, Mapping)
        or not isinstance(final_prov, Mapping)
        or not isinstance(dep_prov, Mapping)
        or not isinstance(refl_prov, Mapping)
    ):
        raise ValueError("Missing required 1SAR provenance sub-blocks.")

    expected_start_ref = f"artifact:{ONESAR_ARTIFACT_ID}#{ONESAR_START_MEMBER}"
    if (
        start_prov.get("subject_ref") != expected_start_ref
        or start_prov.get("archive_member") != ONESAR_START_MEMBER
        or start_prov.get("sha256") != ONESAR_START_SHA256
    ):
        raise ValueError("1SAR starting_model provenance mismatch.")

    expected_r4_ref = f"artifact:{ONESAR_ARTIFACT_ID}#{ONESAR_R4_FINAL_MEMBER}"
    if (
        final_prov.get("subject_ref") != expected_r4_ref
        or final_prov.get("archive_member") != ONESAR_R4_FINAL_MEMBER
        or final_prov.get("sha256") != ONESAR_R4_FINAL_SHA256
    ):
        raise ValueError("1SAR packaged_final_model provenance mismatch.")

    if (
        dep_prov.get("subject_ref") != "pdb:1SAR"
        or dep_prov.get("path") != ONESAR_DEPOSITED_PDB_PATH
        or dep_prov.get("sha256") != ONESAR_DEPOSITED_PDB_SHA256
    ):
        raise ValueError("1SAR deposited_reference_model provenance mismatch.")

    if (
        refl_prov.get("input_mtz_member") != ONESAR_INPUT_MTZ_MEMBER
        or refl_prov.get("input_mtz_sha256") != ONESAR_INPUT_MTZ_SHA256
    ):
        raise ValueError("1SAR reflection_data provenance mismatch.")

    # Verify archive bytes and read member streams in-memory without extraction
    _read_verified_repo_bytes(root, ONESAR_ARCHIVE_PATH, ONESAR_ARCHIVE_SHA256)
    archive_full_path = root / ONESAR_ARCHIVE_PATH

    required_archive_members: tuple[tuple[str, str], ...] = (
        (ONESAR_START_MEMBER, ONESAR_START_SHA256),
        (ONESAR_R4_FINAL_MEMBER, ONESAR_R4_FINAL_SHA256),
        (ONESAR_R5_MEMBER, ONESAR_R5_SHA256),
        (ONESAR_R6_MEMBER, ONESAR_R6_SHA256),
        (ONESAR_INPUT_MTZ_MEMBER, ONESAR_INPUT_MTZ_SHA256),
    )

    try:
        with zipfile.ZipFile(archive_full_path, "r") as zf:
            namelist = zf.namelist()
            name_counts: dict[str, int] = {}
            for name in namelist:
                name_counts[name] = name_counts.get(name, 0) + 1

            duplicate_names = sorted(
                name for name, count in name_counts.items() if count > 1
            )
            if ONESAR_R7_MEMBER in name_counts:
                raise ValueError(
                    f"Unexpected {ONESAR_R7_MEMBER!r} found in {ONESAR_ARCHIVE_PATH!r}; "
                    "Round 7 must be absent and never measured."
                )

            for member_name, expected_member_sha in required_archive_members:
                count = name_counts.get(member_name, 0)
                if count != 1:
                    raise ValueError(
                        f"Required 1SAR archive member {member_name!r} must appear "
                        f"exactly once in {ONESAR_ARCHIVE_PATH!r}, found {count}."
                    )
                member_bytes = zf.read(member_name)
                actual_member_sha = hashlib.sha256(member_bytes).hexdigest()
                if actual_member_sha != expected_member_sha:
                    raise ValueError(
                        f"1SAR archive member {member_name!r} SHA-256 mismatch: "
                        f"expected {expected_member_sha}, got {actual_member_sha}."
                    )
    except zipfile.BadZipFile as exc:
        raise ValueError(
            f"Corrupted 1SAR artifact zip archive {ONESAR_ARCHIVE_PATH!r}."
        ) from exc

    # Verify standalone deposited coordinate reference file bytes
    _read_verified_repo_bytes(
        root,
        ONESAR_DEPOSITED_PDB_PATH,
        ONESAR_DEPOSITED_PDB_SHA256,
    )

    retained_subjects: list[dict[str, Any]] = [
        {
            "subject_id": "starting_model",
            "subject_ref": expected_start_ref,
            "carrier_kind": "archive_member",
            "archive_path": ONESAR_ARCHIVE_PATH,
            "archive_member": ONESAR_START_MEMBER,
            "sha256": ONESAR_START_SHA256,
            "role": "principal_starting_model",
            "hash_ancestry": "assessment_provenance_and_archive_member_bytes",
            "source_pointer": "/case_study_1sar/provenance/starting_model",
            "verification_mode": "locally_byte_verified",
            "local_bytes_verified": True,
        },
        {
            "subject_id": "packaged_round4_final_model",
            "subject_ref": expected_r4_ref,
            "carrier_kind": "archive_member",
            "archive_path": ONESAR_ARCHIVE_PATH,
            "archive_member": ONESAR_R4_FINAL_MEMBER,
            "sha256": ONESAR_R4_FINAL_SHA256,
            "role": "packaged_round4_refinement_output",
            "hash_ancestry": "assessment_provenance_and_archive_member_bytes",
            "source_pointer": "/case_study_1sar/provenance/packaged_final_model",
            "verification_mode": "locally_byte_verified",
            "local_bytes_verified": True,
        },
        {
            "subject_id": "retained_round5_model",
            "subject_ref": f"artifact:{ONESAR_ARTIFACT_ID}#{ONESAR_R5_MEMBER}",
            "carrier_kind": "archive_member",
            "archive_path": ONESAR_ARCHIVE_PATH,
            "archive_member": ONESAR_R5_MEMBER,
            "sha256": ONESAR_R5_SHA256,
            "role": "retained_round5_intermediate_coordinate_model",
            "hash_ancestry": "direct_archive_member_bytes",
            "source_pointer": None,
            "verification_mode": "locally_byte_verified",
            "local_bytes_verified": True,
        },
        {
            "subject_id": "retained_round6_model",
            "subject_ref": f"artifact:{ONESAR_ARTIFACT_ID}#{ONESAR_R6_MEMBER}",
            "carrier_kind": "archive_member",
            "archive_path": ONESAR_ARCHIVE_PATH,
            "archive_member": ONESAR_R6_MEMBER,
            "sha256": ONESAR_R6_SHA256,
            "role": "retained_round6_intermediate_coordinate_model",
            "hash_ancestry": "direct_archive_member_bytes",
            "source_pointer": None,
            "verification_mode": "locally_byte_verified",
            "local_bytes_verified": True,
        },
        {
            "subject_id": "original_input_mtz",
            "subject_ref": f"artifact:{ONESAR_ARTIFACT_ID}#{ONESAR_INPUT_MTZ_MEMBER}",
            "carrier_kind": "archive_member",
            "archive_path": ONESAR_ARCHIVE_PATH,
            "archive_member": ONESAR_INPUT_MTZ_MEMBER,
            "sha256": ONESAR_INPUT_MTZ_SHA256,
            "role": "original_input_reflection_mtz",
            "hash_ancestry": "assessment_provenance_and_archive_member_bytes",
            "source_pointer": (
                "/case_study_1sar/provenance/reflection_data/input_mtz_sha256"
            ),
            "verification_mode": "locally_byte_verified",
            "local_bytes_verified": True,
        },
        {
            "subject_id": "deposited_reference_model",
            "subject_ref": "pdb:1SAR",
            "carrier_kind": "repository_file",
            "path": ONESAR_DEPOSITED_PDB_PATH,
            "sha256": ONESAR_DEPOSITED_PDB_SHA256,
            "role": "deposited_reference_only",
            "coordinate_file_available": True,
            "hash_ancestry": "assessment_provenance_and_repository_file_bytes",
            "source_pointer": "/case_study_1sar/provenance/deposited_reference_model",
            "verification_mode": "locally_byte_verified",
            "local_bytes_verified": True,
        },
    ]

    onesar_hashes = {item["sha256"] for item in retained_subjects} | {
        ONESAR_ARCHIVE_SHA256
    }
    if len(onesar_hashes) != len(retained_subjects) + 1:
        raise ValueError("Duplicate SHA-256 detected among 1SAR retained subjects.")
    if not onesar_hashes.isdisjoint(round2_hashes):
        raise ValueError(
            "Locally verified 1SAR byte hashes must be disjoint from the 22 "
            "source-attested Round-2 hash sets."
        )

    return {
        "pdb_id": ONESAR_ACCESSION,
        "accession_level_exclusion_count": 1,
        "exclusion_group": "case_study_1sar_separate_accession_exclusion",
        "case_id": ONESAR_CASE_ID,
        "source_path": ASSESSMENT_1SAR_PATH,
        "source_sha256": ASSESSMENT_1SAR_SHA256,
        "source_pointer": "/case_study_1sar/provenance",
        "verification_mode": "locally_byte_verified",
        "local_bytes_verified": True,
        "execution_ready_input_bundle": False,
        "artifact_archive": {
            "artifact_id": ONESAR_ARTIFACT_ID,
            "archive_path": ONESAR_ARCHIVE_PATH,
            "archive_sha256": ONESAR_ARCHIVE_SHA256,
            "source_pointer": "/case_study_1sar/provenance/archive_sha256",
            "total_archive_entries": len(namelist),
            "unique_archive_entry_names": len(name_counts),
            "duplicate_archive_entry_names": duplicate_names,
            "extracted_to_disk": False,
        },
        "retained_subjects": retained_subjects,
        "round7_status": "absent_from_archive_never_measured",
    }


def build_dev_exclusions(repo_root: str | Path = REPO_ROOT) -> dict[str, Any]:
    """Build the deterministic 23-accession Stage 2 development exclusion manifest."""
    if not isinstance(repo_root, (str, Path)):
        raise ValueError(
            f"repo_root must be a str or Path, got {type(repo_root).__name__}."
        )
    root = Path(repo_root)
    if not root.is_dir():
        raise ValueError("repo_root does not exist or is not a directory.")

    _read_verified_repo_bytes(
        root, APPROVED_SELECTIONS_PATH, APPROVED_SELECTIONS_SHA256
    )
    round2_bytes = _read_verified_repo_bytes(
        root, ROUND2_ENROLLED_PATH, ROUND2_ENROLLED_SHA256
    )
    assessment_bytes = _read_verified_repo_bytes(
        root, ASSESSMENT_1SAR_PATH, ASSESSMENT_1SAR_SHA256
    )

    round2_doc = json.loads(
        round2_bytes.decode("utf-8"),
        object_pairs_hook=_reject_duplicate_json_keys,
    )
    assessment_doc = json.loads(
        assessment_bytes.decode("utf-8"),
        object_pairs_hook=_reject_duplicate_json_keys,
    )
    if not isinstance(round2_doc, Mapping) or not isinstance(assessment_doc, Mapping):
        raise ValueError("Committed exclusion sources must parse as JSON objects.")

    round2_rows, round2_pdb_ids, round2_hashes = _parse_round2_exclusions(round2_doc)
    onesar_block = _build_onesar_exclusion(root, assessment_doc, round2_hashes)

    excluded_accessions = [*round2_pdb_ids, ONESAR_ACCESSION]
    if (
        len(excluded_accessions) != TOTAL_EXCLUDED_ACCESSIONS_COUNT
        or len(set(excluded_accessions)) != TOTAL_EXCLUDED_ACCESSIONS_COUNT
    ):
        raise ValueError(
            f"Expected {TOTAL_EXCLUDED_ACCESSIONS_COUNT} unique excluded accessions, "
            f"got {len(excluded_accessions)} ({len(set(excluded_accessions))} unique)."
        )

    payload: dict[str, Any] = {
        "schema": "phenix_stage2_development_exclusions_v1",
        "registration_status": REGISTRATION_STATUS,
        "manifest_role": (
            "development_exclusion_manifest_not_execution_ready_input_bundles"
        ),
        "execution_authorized": False,
        "frozen_result_free": False,
        "outcomes_included": False,
        "sources": {
            "approved_policy_selections": {
                "path": APPROVED_SELECTIONS_PATH,
                "sha256": APPROVED_SELECTIONS_SHA256,
                "sections": ["U02", "U04"],
            },
            "negative_control_round2_enrolled": {
                "path": ROUND2_ENROLLED_PATH,
                "sha256": ROUND2_ENROLLED_SHA256,
                "enrolled_count": ROUND2_EXPECTED_COUNT,
            },
            "refinement_assessment_1sar": {
                "path": ASSESSMENT_1SAR_PATH,
                "sha256": ASSESSMENT_1SAR_SHA256,
                "provenance_pointer": "/case_study_1sar/provenance",
            },
        },
        "counts": {
            "round2_negative_control_accessions": len(round2_rows),
            "separate_1sar_accessions": 1,
            "total_excluded_accessions": len(excluded_accessions),
            "onesar_retained_subject_count": len(onesar_block["retained_subjects"]),
        },
        "excluded_accessions": excluded_accessions,
        "round2_negative_controls": round2_rows,
        "onesar_exclusion": onesar_block,
        "verification_boundary": {
            "round2_input_hashes": "source_attested_not_locally_byte_verified",
            "round2_cif_role": (
                "deposited_structural_mmcif_not_ligand_restraint_cif"
            ),
            "onesar_retained_subjects": (
                "locally_byte_verified_against_retained_archive_and_deposited_pdb"
            ),
            "onesar_hashes_disjoint_from_round2_sets": True,
        },
    }
    manifest_sha256 = canonical_json_sha256(payload)
    return {
        **payload,
        "manifest_sha256": manifest_sha256,
    }


def _to_portable_path(lexical_path: Path, prefix_root: Path) -> str:
    rel = lexical_path.relative_to(prefix_root).as_posix()
    if not rel or rel == ".":
        return PORTABLE_PHENIX_PREFIX
    return f"{PORTABLE_PHENIX_PREFIX}/{rel}"


def _resolve_within_prefix(lexical_path: Path, prefix_root: Path) -> Path:
    portable_label = _to_portable_path(lexical_path, prefix_root)
    try:
        st = os.lstat(lexical_path)
    except OSError as exc:
        raise ValueError(f"Cannot lstat {portable_label!r}.") from exc

    if stat.S_ISLNK(st.st_mode):
        cur = lexical_path
        for _ in range(_MAX_SYMLINK_HOPS):
            try:
                link_st = os.lstat(cur)
            except OSError as exc:
                raise ValueError(
                    f"Broken symlink chain from {portable_label!r}."
                ) from exc
            if not stat.S_ISLNK(link_st.st_mode):
                break
            try:
                raw_target = os.readlink(cur)
            except OSError as exc:
                raise ValueError(
                    f"Cannot read symlink target at {portable_label!r}."
                ) from exc
            if os.path.isabs(raw_target):
                next_path = Path(raw_target)
            else:
                next_path = cur.parent / raw_target
            try:
                if next_path.name in ("", ".", ".."):
                    candidate = next_path.resolve(strict=True)
                else:
                    resolved_parent = next_path.parent.resolve(strict=True)
                    candidate = resolved_parent / next_path.name
            except (OSError, RuntimeError) as exc:
                raise ValueError(
                    f"Broken symlink chain from {portable_label!r}."
                ) from exc
            if not candidate.is_relative_to(prefix_root):
                raise ValueError(
                    f"Symlink {portable_label!r} escapes {PORTABLE_PHENIX_PREFIX} boundary."
                )
            cur = candidate
        else:
            raise ValueError(f"Symlink loop detected at {portable_label!r}.")

    try:
        resolved = lexical_path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError(
            f"Cannot resolve {portable_label!r} within {PORTABLE_PHENIX_PREFIX}."
        ) from exc

    if not resolved.is_relative_to(prefix_root):
        raise ValueError(
            f"Resolved target for {portable_label!r} escapes {PORTABLE_PHENIX_PREFIX}."
        )
    return resolved


def _parse_metadata_file(
    real_file_path: Path,
    portable_path: str,
) -> dict[str, str]:
    try:
        raw_bytes = real_file_path.read_bytes()
    except OSError as exc:
        raise ValueError(f"Cannot read metadata file {portable_path!r}.") from exc

    msg = email.parser.BytesParser(policy=email.policy.compat32).parsebytes(raw_bytes)
    if msg.defects:
        defect_names = sorted({type(defect).__name__ for defect in msg.defects})
        raise ValueError(
            f"Metadata file {portable_path!r} has malformed header structure "
            f"(defects: {', '.join(defect_names)})."
        )

    names = msg.get_all("Name") or []
    versions = msg.get_all("Version") or []
    if len(names) != 1:
        raise ValueError(
            f"Metadata file {portable_path!r} must have exactly one Name header, "
            f"found {len(names)}."
        )
    if len(versions) != 1:
        raise ValueError(
            f"Metadata file {portable_path!r} must have exactly one Version header, "
            f"found {len(versions)}."
        )

    name_val = str(names[0]).strip()
    version_val = str(versions[0]).strip()
    if (
        not name_val
        or not version_val
        or "\ufffd" in name_val
        or "\ufffd" in version_val
        or not name_val.isascii()
        or not version_val.isascii()
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in name_val)
        or any(ord(ch) < 32 or ord(ch) == 127 for ch in version_val)
    ):
        raise ValueError(
            f"Metadata file {portable_path!r} has empty, non-ASCII, or multiline "
            "Name/Version header."
        )

    return {
        "name": name_val,
        "path": portable_path,
        "sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "version": version_val,
    }


def _inspect_top_level_adapters(
    site_packages_dir: Path,
    prefix_root: Path,
    top_level_names: set[str],
) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for adapter_name in NATIVE_ADAPTER_NAMES:
        py_name = f"{adapter_name}.py"
        has_py = py_name in top_level_names
        has_dir = adapter_name in top_level_names

        # Reject ambiguous compiled/other sibling artifacts like langchain_openai.so
        other_matches = [
            n
            for n in top_level_names
            if n.startswith(f"{adapter_name}.") and n != py_name
        ]
        if other_matches:
            raise ValueError(
                f"Ambiguous top-level adapter artifact(s) for {adapter_name!r}: "
                f"{sorted(other_matches)!r}."
            )
        if has_py and has_dir:
            raise ValueError(
                f"Ambiguous top-level adapter representation for {adapter_name!r}: "
                f"both {py_name!r} and {adapter_name!r}/ exist."
            )

        if has_py:
            py_lexical = site_packages_dir / py_name
            py_portable = _to_portable_path(py_lexical, prefix_root)
            py_real = _resolve_within_prefix(py_lexical, prefix_root)
            try:
                py_st = os.stat(py_real)
            except OSError as exc:
                raise ValueError(f"Cannot stat {py_portable!r}.") from exc
            if not stat.S_ISREG(py_st.st_mode):
                raise ValueError(
                    f"Top-level adapter {py_portable!r} is not a regular file."
                )
            results[adapter_name] = {
                "adapter_name": adapter_name,
                "present": True,
                "kind": "module_file",
                "path": py_portable,
                "init_py_path": None,
                "importability_proven": False,
            }
        elif has_dir:
            dir_lexical = site_packages_dir / adapter_name
            dir_portable = _to_portable_path(dir_lexical, prefix_root)
            dir_real = _resolve_within_prefix(dir_lexical, prefix_root)
            try:
                dir_st = os.stat(dir_real)
            except OSError as exc:
                raise ValueError(f"Cannot stat {dir_portable!r}.") from exc
            if not stat.S_ISDIR(dir_st.st_mode):
                raise ValueError(
                    f"Top-level adapter path {dir_portable!r} is not a directory."
                )
            try:
                with os.scandir(dir_lexical) as it:
                    pkg_entry_names = {e.name for e in it}
            except OSError as exc:
                raise ValueError(
                    f"Cannot read adapter directory {dir_portable!r}."
                ) from exc

            unsupported_inits = sorted(
                n
                for n in pkg_entry_names
                if (n == "__init__" or n.startswith("__init__."))
                and n != "__init__.py"
            )
            if unsupported_inits:
                raise ValueError(
                    f"Unsupported direct package initializer artifact(s) in {dir_portable!r}: "
                    f"{unsupported_inits!r}."
                )

            if "__init__.py" in pkg_entry_names:
                init_lexical = dir_lexical / "__init__.py"
                init_portable = _to_portable_path(init_lexical, prefix_root)
                init_real = _resolve_within_prefix(init_lexical, prefix_root)
                try:
                    init_st = os.stat(init_real)
                except OSError as exc:
                    raise ValueError(f"Cannot stat {init_portable!r}.") from exc
                if not stat.S_ISREG(init_st.st_mode):
                    raise ValueError(
                        f"Adapter {init_portable!r} is not a regular file."
                    )
                results[adapter_name] = {
                    "adapter_name": adapter_name,
                    "present": True,
                    "kind": "regular_package",
                    "path": dir_portable,
                    "init_py_path": init_portable,
                    "importability_proven": False,
                }
            else:
                results[adapter_name] = {
                    "adapter_name": adapter_name,
                    "present": True,
                    "kind": "namespace_only_directory",
                    "path": dir_portable,
                    "init_py_path": None,
                    "importability_proven": False,
                }
        else:
            results[adapter_name] = {
                "adapter_name": adapter_name,
                "present": False,
                "kind": "absent",
                "path": None,
                "init_py_path": None,
                "importability_proven": False,
            }

    return results


def inspect_provider_metadata(
    prefix: str | Path,
    *,
    repo_root: str | Path = REPO_ROOT,
) -> dict[str, Any]:
    """Statically inspect ``prefix/lib/python3.9/site-packages`` for provider metadata and adapters."""
    if not isinstance(prefix, (str, Path)) or not str(prefix).strip():
        raise ValueError("prefix must be a non-empty str or Path.")
    if not isinstance(repo_root, (str, Path)):
        raise ValueError("repo_root must be a str or Path.")

    root = Path(repo_root)
    if not root.is_dir():
        raise ValueError("repo_root does not exist or is not a directory.")

    # Verify linked static source witness and approved selections document
    _read_verified_repo_bytes(
        root, APPROVED_SELECTIONS_PATH, APPROVED_SELECTIONS_SHA256
    )
    witness_bytes = _read_verified_repo_bytes(
        root, STATIC_LANGCHAIN_WITNESS_PATH, STATIC_LANGCHAIN_WITNESS_SHA256
    )
    witness_doc = json.loads(
        witness_bytes.decode("utf-8"),
        object_pairs_hook=_reject_duplicate_json_keys,
    )
    if (
        not isinstance(witness_doc, Mapping)
        or not isinstance(witness_doc.get("files"), list)
        or len(witness_doc["files"]) != STATIC_LANGCHAIN_WITNESS_FILE_COUNT
    ):
        raise ValueError("Committed static source witness file count mismatch.")

    raw_prefix = Path(prefix)
    try:
        prefix_root = raw_prefix.resolve(strict=True)
        prefix_st = os.stat(prefix_root)
    except (OSError, RuntimeError) as exc:
        raise ValueError("Configured PHENIX prefix does not exist or is unreadable.") from exc
    if not stat.S_ISDIR(prefix_st.st_mode):
        raise ValueError("Configured PHENIX prefix is not a directory.")

    # Verify intermediate path components lib/python3.9/site-packages stay within prefix_root
    cur_check = prefix_root
    for part in ("lib", "python3.9", "site-packages"):
        cur_check = cur_check / part
        resolved_part = _resolve_within_prefix(cur_check, prefix_root)
        try:
            part_st = os.stat(resolved_part)
        except OSError as exc:
            raise ValueError(
                f"Cannot stat {_to_portable_path(cur_check, prefix_root)!r}."
            ) from exc
        if not stat.S_ISDIR(part_st.st_mode):
            raise ValueError(
                f"{_to_portable_path(cur_check, prefix_root)!r} is not a directory."
            )

    site_packages_dir = prefix_root / "lib" / "python3.9" / "site-packages"

    directories_traversed = 0
    files_traversed = 0
    dist_info_metadata_files_inspected = 0
    pkg_info_metadata_files_inspected = 0
    visited_real_dirs: dict[Path, str] = {}
    visited_real_metadata_files: dict[Path, str] = {}
    matched_distributions: list[dict[str, str]] = []
    top_level_entry_names: set[str] = set()

    def _walk_dir(lexical_dir: Path, *, is_top_level: bool = False) -> None:
        nonlocal directories_traversed
        nonlocal files_traversed
        nonlocal dist_info_metadata_files_inspected
        nonlocal pkg_info_metadata_files_inspected

        portable_dir = _to_portable_path(lexical_dir, prefix_root)
        real_dir = _resolve_within_prefix(lexical_dir, prefix_root)
        if real_dir in visited_real_dirs:
            raise ValueError(
                f"Symlink ambiguity: {portable_dir!r} resolves to already-traversed "
                f"directory {visited_real_dirs[real_dir]!r}."
            )
        visited_real_dirs[real_dir] = portable_dir
        directories_traversed += 1

        try:
            with os.scandir(lexical_dir) as it:
                entries = sorted(list(it), key=lambda e: e.name)
        except OSError as exc:
            raise ValueError(
                f"Directory traversal failed at {portable_dir!r}."
            ) from exc

        entry_names = {e.name for e in entries}
        if is_top_level:
            top_level_entry_names.update(entry_names)

        if lexical_dir.name.endswith(".dist-info") or lexical_dir.name.endswith(
            ".egg-info"
        ):
            if not any(m in entry_names for m in METADATA_FILENAMES):
                raise ValueError(
                    f"Metadata directory {portable_dir!r} is missing METADATA/PKG-INFO."
                )

        for entry in entries:
            child_lexical = lexical_dir / entry.name
            child_portable = _to_portable_path(child_lexical, prefix_root)
            child_real = _resolve_within_prefix(child_lexical, prefix_root)
            try:
                child_st = os.stat(child_real)
            except OSError as exc:
                raise ValueError(f"Cannot stat {child_portable!r}.") from exc

            if entry.name in METADATA_FILENAMES and not stat.S_ISREG(
                child_st.st_mode
            ):
                raise ValueError(
                    f"Metadata entry {child_portable!r} must resolve to a regular file."
                )

            if stat.S_ISDIR(child_st.st_mode):
                _walk_dir(child_lexical, is_top_level=False)
            elif stat.S_ISREG(child_st.st_mode):
                files_traversed += 1
                if entry.name in METADATA_FILENAMES:
                    if child_real in visited_real_metadata_files:
                        raise ValueError(
                            f"Symlink ambiguity: {child_portable!r} resolves to "
                            "already-inspected metadata file "
                            f"{visited_real_metadata_files[child_real]!r}."
                        )
                    visited_real_metadata_files[child_real] = child_portable
                    if entry.name == "METADATA":
                        dist_info_metadata_files_inspected += 1
                    else:
                        pkg_info_metadata_files_inspected += 1

                    parsed_meta = _parse_metadata_file(child_real, child_portable)
                    lower_name = parsed_meta["name"].lower()
                    if any(sub in lower_name for sub in PROVIDER_QUERY_SUBSTRINGS):
                        matched_distributions.append(parsed_meta)
            else:
                raise ValueError(
                    f"Unsupported non-regular filesystem entry at {child_portable!r}."
                )

    _walk_dir(site_packages_dir, is_top_level=True)

    adapter_records = _inspect_top_level_adapters(
        site_packages_dir,
        prefix_root,
        top_level_entry_names,
    )

    matched_distributions.sort(
        key=lambda item: (
            item["path"],
            item["name"],
            item["version"],
            item["sha256"],
        )
    )
    total_metadata_inspected = (
        dist_info_metadata_files_inspected + pkg_info_metadata_files_inspected
    )
    present_adapter_count = sum(
        1 for rec in adapter_records.values() if rec["present"] is True
    )

    payload: dict[str, Any] = {
        "schema": "phenix_stage2_provider_metadata_witness_v1",
        "registration_status": REGISTRATION_STATUS,
        "portable_prefix": PORTABLE_PHENIX_PREFIX,
        "inspected_root": f"{PORTABLE_PHENIX_PREFIX}/{SITE_PACKAGES_REL_PATH}",
        "query_scope": {
            "inspected_subtree": f"{PORTABLE_PHENIX_PREFIX}/{SITE_PACKAGES_REL_PATH}",
            "include_hidden_and_ignored": True,
            "metadata_filenames": list(METADATA_FILENAMES),
            "distribution_name_substrings": list(PROVIDER_QUERY_SUBSTRINGS),
            "native_adapter_names": list(NATIVE_ADAPTER_NAMES),
            "native_adapter_lookup_scope": "exact_top_level_site_packages_only",
            "vendor_imports_executed": False,
            "importlib_metadata_used": False,
            "pth_files_executed": False,
            "commands_executed": False,
            "network_or_provider_calls": False,
        },
        "inspection_counts": {
            "directories_traversed": directories_traversed,
            "files_traversed": files_traversed,
            "metadata_files_inspected": total_metadata_inspected,
            "dist_info_metadata_files_inspected": dist_info_metadata_files_inspected,
            "pkg_info_metadata_files_inspected": pkg_info_metadata_files_inspected,
            "matched_distribution_count": len(matched_distributions),
            "present_native_adapter_count": present_adapter_count,
        },
        "matched_distributions": matched_distributions,
        "native_adapter_modules": adapter_records,
        "epistemic_boundary": {
            "absence_interpretation": (
                "no_matching_metadata_or_top_level_adapter_under_inspected_"
                "site_packages_tree_not_universal_runtime_absence"
            ),
            "presence_interpretation": (
                "filesystem_presence_or_metadata_header_only_does_not_prove_"
                "importability_or_runtime_binding"
            ),
            "full_freeze_status": (
                "shared_dated_snapshot_prompt_effective_config_and_dependency_"
                "freeze_pending_stage2"
            ),
        },
        "shared_dated_snapshot": {
            "selected_identifier": None,
            "availability": "not_assessed",
            "runtime_binding": "not_assessed",
        },
        "static_source_witness": {
            "path": STATIC_LANGCHAIN_WITNESS_PATH,
            "sha256": STATIC_LANGCHAIN_WITNESS_SHA256,
            "inspected_python_file_count": STATIC_LANGCHAIN_WITNESS_FILE_COUNT,
        },
        "approved_policy_source": {
            "path": APPROVED_SELECTIONS_PATH,
            "sha256": APPROVED_SELECTIONS_SHA256,
            "section": "U12",
        },
    }

    witness_sha256 = canonical_json_sha256(payload)
    result = {
        **payload,
        "witness_sha256": witness_sha256,
    }

    serialized_check = canonical_json_bytes(result).decode("utf-8")
    forbidden_prefixes = {
        str(prefix_root),
        str(raw_prefix.absolute()),
        os.path.abspath(raw_prefix),
    }
    if raw_prefix.name not in ("", ".", ".."):
        forbidden_prefixes.add(
            str(raw_prefix.parent.resolve(strict=True) / raw_prefix.name)
        )
    if raw_prefix.is_absolute():
        forbidden_prefixes.add(str(raw_prefix))
    for forbidden_prefix in forbidden_prefixes:
        if forbidden_prefix and forbidden_prefix != PORTABLE_PHENIX_PREFIX:
            if forbidden_prefix in serialized_check:
                raise ValueError(
                    "Refusing to serialize absolute PHENIX prefix path in witness output."
                )

    return result


def _write_json_output(record: Mapping[str, Any], out_path: Path | None) -> None:
    formatted = (
        json.dumps(
            _normalize_strict_json_value(record, field_name="record"),
            indent=2,
            sort_keys=False,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )
    if out_path is None:
        print(formatted, end="")
    else:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(formatted, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    """Explicit CLI entry point for emitting Stage 2 exclusion or package witness JSON."""
    parser = argparse.ArgumentParser(
        description=(
            "Generate result-free Stage 2 PHENIX development exclusion manifest "
            "or static provider metadata witness."
        )
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="Repository root directory (default: REPO_ROOT from __file__).",
    )
    parser.add_argument(
        "--dev-exclusions",
        action="store_true",
        help="Emit the 23-accession development exclusion manifest.",
    )
    parser.add_argument(
        "--dev-exclusions-out",
        type=Path,
        default=None,
        help="Write the development exclusion manifest JSON to this file path.",
    )
    parser.add_argument(
        "--prefix",
        type=Path,
        default=None,
        help=(
            "Explicit PHENIX installation prefix to inspect "
            "(inspects <prefix>/lib/python3.9/site-packages)."
        ),
    )
    parser.add_argument(
        "--provider-metadata-out",
        type=Path,
        default=None,
        help="Write the provider metadata witness JSON to this file path.",
    )

    args = parser.parse_args(list(argv) if argv is not None else None)
    did_work = False

    if args.dev_exclusions or args.dev_exclusions_out is not None:
        exclusions = build_dev_exclusions(args.repo_root)
        _write_json_output(exclusions, args.dev_exclusions_out)
        did_work = True

    if args.prefix is not None or args.provider_metadata_out is not None:
        if args.prefix is None:
            parser.error("--provider-metadata-out requires an explicit --prefix.")
        witness = inspect_provider_metadata(args.prefix, repo_root=args.repo_root)
        _write_json_output(witness, args.provider_metadata_out)
        did_work = True

    if not did_work:
        parser.error(
            "Specify --dev-exclusions / --dev-exclusions-out and/or --prefix."
        )
    return 0


__all__ = [
    "APPROVED_SELECTIONS_PATH",
    "APPROVED_SELECTIONS_SHA256",
    "ASSESSMENT_1SAR_PATH",
    "ASSESSMENT_1SAR_SHA256",
    "METADATA_FILENAMES",
    "NATIVE_ADAPTER_NAMES",
    "ONESAR_ACCESSION",
    "ONESAR_ARCHIVE_PATH",
    "ONESAR_ARCHIVE_SHA256",
    "ONESAR_ARTIFACT_ID",
    "ONESAR_CASE_ID",
    "ONESAR_DEPOSITED_PDB_PATH",
    "ONESAR_DEPOSITED_PDB_SHA256",
    "ONESAR_INPUT_MTZ_MEMBER",
    "ONESAR_INPUT_MTZ_SHA256",
    "ONESAR_R4_FINAL_MEMBER",
    "ONESAR_R4_FINAL_SHA256",
    "ONESAR_R5_MEMBER",
    "ONESAR_R5_SHA256",
    "ONESAR_R6_MEMBER",
    "ONESAR_R6_SHA256",
    "ONESAR_START_MEMBER",
    "ONESAR_START_SHA256",
    "PORTABLE_PHENIX_PREFIX",
    "PROVIDER_QUERY_SUBSTRINGS",
    "REGISTRATION_STATUS",
    "REPO_ROOT",
    "ROUND2_ENROLLED_PATH",
    "ROUND2_ENROLLED_SHA256",
    "ROUND2_EXPECTED_COUNT",
    "SITE_PACKAGES_REL_PATH",
    "STATIC_LANGCHAIN_WITNESS_FILE_COUNT",
    "STATIC_LANGCHAIN_WITNESS_PATH",
    "STATIC_LANGCHAIN_WITNESS_SHA256",
    "TOTAL_EXCLUDED_ACCESSIONS_COUNT",
    "build_dev_exclusions",
    "canonical_json_bytes",
    "canonical_json_sha256",
    "inspect_provider_metadata",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
