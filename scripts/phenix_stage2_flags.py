#!/usr/bin/env python3
"""Result-free Stage 2 PHENIX flag-generation and per-HKL/sleep membership guards (U08).

Scope and epistemic boundary:
- Registration status remains ``selected_decisions_recorded`` (NOT ``frozen_result_free``).
- This module implements two pure Python 3.12 standard-library validators:
  1. A restrictive, documented PHIL / ``argv`` flag-generation guard
     (:func:`verify_flag_generation_guard`) for accepted Stage 2 input records.
     It is NOT a general or full PHIL parser and NOT a runtime-ready executor.
     Full native effective-file compatibility is ``"unassessed"``.
  2. An exact per-HKL R-free flag map and sleep-set membership preservation guard
     (:func:`verify_hkl_and_sleep_membership`) that independently compares keyed
     ``(h, k, l)`` integer flag mappings before/after and sleep HKL sets before/after
     without count-only or intersection-only shortcuts. It proves preservation of
     supplied maps/sets only, not scientific mask construction or source-role admission.
- Witnessed generation parameter spellings (traced in
  ``ref/research/data/phenix_stage2_flag_static_witness_2026-11-16.json``):
  - ``r_free_flags.generate``
  - ``xray_data.r_free_flags.generate``
  - ``data_manager.fmodel.xray_data.r_free_flags.generate``
  Equivalent brace-scoped forms of these three paths are accepted and normalized to
  ``data_manager.fmodel.xray_data.r_free_flags.generate``. Unwitnessed aliases (such as
  ``refinement.input.xray_data.r_free_flags.generate``), abbreviations, and unknown
  parameter paths fail closed.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
import hashlib
import re
from typing import Any

REGISTRATION_STATUS = "selected_decisions_recorded"
STAGE2_FLAGS_STATUS = "prospective_flag_guard_not_development_frozen"
NATIVE_EFFECTIVE_FILE_COMPATIBILITY = "unassessed"

STATIC_WITNESS_PATH = (
    "ref/research/data/phenix_stage2_flag_static_witness_2026-11-16.json"
)

CANONICAL_ARM_IDS: tuple[str, ...] = (
    "1a",
    "1b",
    "2",
    "3a",
    "3b-refine-only",
    "3b-plus-readyset",
)

CANONICAL_SOURCE_LAYERS: tuple[str, ...] = (
    "primary_command",
    "mechanical_backup",
    "actual_command",
    "effective_eff",
)
COMMAND_SOURCE_LAYERS: frozenset[str] = frozenset(
    {"primary_command", "mechanical_backup", "actual_command"}
)
ALLOWED_SOURCE_STATES: frozenset[str] = frozenset(
    {"supplied", "not_applicable", "unavailable"}
)

CANONICAL_GENERATION_KEY = "data_manager.fmodel.xray_data.r_free_flags.generate"
WITNESSED_GENERATION_PATHS: frozenset[str] = frozenset(
    {
        "r_free_flags.generate",
        "xray_data.r_free_flags.generate",
        "data_manager.fmodel.xray_data.r_free_flags.generate",
    }
)

SUPPORTED_NON_GENERATION_PATHS: frozenset[str] = frozenset(
    {
        "main.number_of_macro_cycles",
        "refinement.main.number_of_macro_cycles",
        "main.nqh_flips",
        "refinement.main.nqh_flips",
        "main.nproc",
        "refinement.main.nproc",
        "strategy",
        "refine.strategy",
        "refinement.refine.strategy",
        "refine.adp.individual.isotropic",
        "refinement.refine.adp.individual.isotropic",
        "refine.adp.individual.anisotropic",
        "refinement.refine.adp.individual.anisotropic",
        "refine.adp.tls",
        "refinement.refine.adp.tls",
        "output.prefix",
        "refinement.output.prefix",
        "output.write_eff_file",
        "refinement.output.write_eff_file",
        "r_free_flags.label",
        "xray_data.r_free_flags.label",
        "data_manager.fmodel.xray_data.r_free_flags.label",
        "r_free_flags.test_flag_value",
        "xray_data.r_free_flags.test_flag_value",
        "data_manager.fmodel.xray_data.r_free_flags.test_flag_value",
        "data_manager.model.file",
        "data_manager.miller_array.file",
    }
)

MODEL_FILE_EXTENSIONS: tuple[str, ...] = (".pdb", ".cif", ".mmcif")
REFLECTION_FILE_EXTENSIONS: tuple[str, ...] = (".mtz", ".sca", ".hkl")
PARAMETER_FILE_EXTENSIONS: tuple[str, ...] = (
    ".eff",
    ".phil",
    ".def",
    ".params",
    ".param",
    ".par",
)

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*\Z")
_SHELL_META_RE = re.compile(r"[;|&`$><*?\[\]~\n\r\x00]")

_MISSING = object()


def _validate_nonempty_str(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string, got {value!r}.")
    return value.strip()


def _validate_strict_source_id(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(
            f"{field_name} must be a non-empty string without leading or trailing "
            f"whitespace, got {value!r}."
        )
    return value


def _validate_strict_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            f"{field_name} must be a strict int (not bool/float/str), "
            f"got {value!r} ({type(value).__name__})."
        )
    return value


def _tokenize_bounded_phil(
    text: str, *, source_id: str
) -> list[tuple[str, str, int]]:
    """Tokenize bounded PHIL text into (kind, value, line_no) tuples.

    Supported token kinds:
    - ``IDENT``: bare identifier or dotted path (``[A-Za-z_][A-Za-z0-9_.]*``) or
      unquoted scalar value (``[A-Za-z0-9_.+-]+``).
    - ``STRING``: single- or double-quoted single-line string literal (with ``#``
      and braces preserved as literal characters inside quotes).
    - ``LBRACE``: ``{``
    - ``RBRACE``: ``}``
    - ``EQUALS``: ``=``
    - ``SEP``: ``;`` or newline statement separator.

    Fails closed on unterminated quotes, shell/interpolation markers (``$``, `` ` ``),
    or unsupported characters.
    """
    if not isinstance(text, str):
        raise ValueError(f"{source_id} content must be a string, got {type(text).__name__}.")
    if "\x00" in text:
        raise ValueError(f"{source_id} contains NUL byte.")

    tokens: list[tuple[str, str, int]] = []
    n = len(text)
    i = 0
    line_no = 1

    while i < n:
        ch = text[i]
        if ch in (" ", "\t", "\r"):
            i += 1
            continue
        if ch == "\n":
            tokens.append(("SEP", "\n", line_no))
            line_no += 1
            i += 1
            continue
        if ch == ";":
            tokens.append(("SEP", ";", line_no))
            i += 1
            continue
        if ch == "#":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "{":
            tokens.append(("LBRACE", "{", line_no))
            i += 1
            continue
        if ch == "}":
            tokens.append(("RBRACE", "}", line_no))
            i += 1
            continue
        if ch == "=":
            tokens.append(("EQUALS", "=", line_no))
            i += 1
            continue
        if ch in ('"', "'"):
            quote_ch = ch
            start_line = line_no
            i += 1
            buf: list[str] = []
            closed = False
            while i < n:
                c = text[i]
                if c == "\n" or c == "\r":
                    raise ValueError(
                        f"{source_id}:{start_line}: multiline or unterminated quoted string "
                        "is unsupported in bounded PHIL grammar."
                    )
                if c == "\\":
                    if i + 1 >= n:
                        raise ValueError(
                            f"{source_id}:{start_line}: trailing backslash in quoted string."
                        )
                    nxt = text[i + 1]
                    if nxt in (quote_ch, "\\"):
                        buf.append(nxt)
                        i += 2
                        continue
                    raise ValueError(
                        f"{source_id}:{start_line}: unsupported escape sequence '\\{nxt}' "
                        "in quoted string."
                    )
                if c in ("$", "`"):
                    raise ValueError(
                        f"{source_id}:{start_line}: dynamic expansion/interpolation character "
                        f"{c!r} is forbidden inside quoted PHIL value."
                    )
                if c == quote_ch:
                    closed = True
                    i += 1
                    break
                buf.append(c)
                i += 1
            if not closed:
                raise ValueError(
                    f"{source_id}:{start_line}: unterminated {quote_ch} quoted string."
                )
            tokens.append(("STRING", "".join(buf), start_line))
            continue

        if ch in ("$", "`", "|", "&", "<", ">", "*", "?", "[", "]", "(", ")", "~", "!"):
            raise ValueError(
                f"{source_id}:{line_no}: unsupported or shell/interpolation character {ch!r} "
                "in bounded PHIL input."
            )

        if ch.isalnum() or ch in ("_", "+", "-", "."):
            start = i
            while i < n and (text[i].isalnum() or text[i] in ("_", ".", "+", "-")):
                i += 1
            word = text[start:i]
            tokens.append(("WORD", word, line_no))
            continue

        raise ValueError(
            f"{source_id}:{line_no}: unexpected character {ch!r} in bounded PHIL input."
        )

    return tokens


def _validate_scope_segments(dotted: str, *, source_id: str, line_no: int) -> tuple[str, ...]:
    if not _IDENT_RE.fullmatch(dotted) or dotted.startswith(".") or dotted.endswith(".") or ".." in dotted:
        raise ValueError(
            f"{source_id}:{line_no}: invalid PHIL identifier path {dotted!r}."
        )
    return tuple(dotted.split("."))


def _parse_generation_bool(
    tok_kind: str, tok_val: str, *, source_id: str, line_no: int, full_path: str
) -> bool:
    if tok_kind != "WORD":
        raise ValueError(
            f"{source_id}:{line_no}: {full_path} requires an unquoted boolean literal "
            f"(True or False), got {tok_kind} {tok_val!r}."
        )
    if tok_val in ("True", "true"):
        return True
    if tok_val in ("False", "false"):
        return False
    raise ValueError(
        f"{source_id}:{line_no}: unknown or unsupported truth value {tok_val!r} for "
        f"{full_path}; only exact True/False/true/false are accepted."
    )


def _parse_bounded_phil_text(
    text: str,
    *,
    source_id: str,
    layer_name: str,
    token_index: int | None = None,
    parameter_files: Mapping[str, str],
    consumed_parameter_files: set[str],
    inclusion_stack: tuple[str, ...],
    source_digests: dict[str, str],
    reference_edges: list[dict[str, Any]],
    generation_occurrences: list[dict[str, Any]],
    non_generation_assignments: list[dict[str, Any]],
) -> None:
    error_ctx = (
        f"{source_id} (argv[{token_index}])"
        if token_index is not None
        else source_id
    )
    tokens = _tokenize_bounded_phil(text, source_id=error_ctx)
    scope_stack: list[tuple[str, ...]] = []
    idx = 0
    total = len(tokens)

    while idx < total:
        kind, val, line_no = tokens[idx]
        if kind == "SEP":
            idx += 1
            continue
        if kind == "RBRACE":
            if not scope_stack:
                raise ValueError(
                    f"{error_ctx}:{line_no}: unbalanced closing brace '}}' at top level."
                )
            scope_stack.pop()
            idx += 1
            continue
        if kind != "WORD":
            raise ValueError(
                f"{error_ctx}:{line_no}: expected identifier or '}}', got {kind} {val!r}."
            )

        # Handle 'include file <target>'
        if val == "include":
            if scope_stack:
                raise ValueError(
                    f"{error_ctx}:{line_no}: 'include' inside a brace scope is unsupported."
                )
            if idx + 2 >= total:
                raise ValueError(
                    f"{error_ctx}:{line_no}: incomplete 'include' directive."
                )
            sub_kind, sub_val, _ = tokens[idx + 1]
            target_kind, target_val, _ = tokens[idx + 2]
            if sub_kind != "WORD" or sub_val != "file":
                raise ValueError(
                    f"{error_ctx}:{line_no}: unsupported include form 'include {sub_val}'; "
                    "only 'include file <filename>' with supplied literal contents is supported."
                )
            if target_kind not in ("WORD", "STRING") or not target_val.strip():
                raise ValueError(
                    f"{error_ctx}:{line_no}: invalid include target {target_val!r}."
                )
            idx += 3
            if idx < total and tokens[idx][0] not in ("SEP", "RBRACE"):
                raise ValueError(
                    f"{error_ctx}:{line_no}: unexpected trailing token {tokens[idx][1]!r} "
                    "after 'include file' directive."
                )
            _resolve_and_parse_parameter_file(
                target_file=target_val,
                parent_source_id=source_id,
                layer_name=layer_name,
                token_index=token_index,
                parameter_files=parameter_files,
                consumed_parameter_files=consumed_parameter_files,
                inclusion_stack=inclusion_stack,
                source_digests=source_digests,
                reference_edges=reference_edges,
                generation_occurrences=generation_occurrences,
                non_generation_assignments=non_generation_assignments,
            )
            continue

        segs = _validate_scope_segments(val, source_id=error_ctx, line_no=line_no)
        if idx + 1 >= total:
            raise ValueError(
                f"{error_ctx}:{line_no}: bare identifier {val!r} without '=' or '{{...}}'."
            )
        next_kind, next_val, next_line = tokens[idx + 1]
        if next_kind == "LBRACE":
            scope_stack.append(segs)
            idx += 2
            continue
        if next_kind == "EQUALS":
            if idx + 2 >= total:
                raise ValueError(
                    f"{error_ctx}:{line_no}: missing value after '=' for {val!r}."
                )
            val_kind, val_str, val_line = tokens[idx + 2]
            if val_kind not in ("WORD", "STRING"):
                raise ValueError(
                    f"{error_ctx}:{val_line}: invalid assignment value token {val_kind} "
                    f"({val_str!r}) for {val!r}."
                )
            idx += 3
            if idx < total and tokens[idx][0] not in ("SEP", "RBRACE"):
                raise ValueError(
                    f"{error_ctx}:{val_line}: unexpected unquoted multi-token value or "
                    f"missing separator after '{val} = {val_str}' (got {tokens[idx][1]!r})."
                )

            flat_segs = tuple(s for grp in scope_stack for s in grp) + segs
            full_path = ".".join(flat_segs)

            if full_path in WITNESSED_GENERATION_PATHS:
                bval = _parse_generation_bool(
                    val_kind,
                    val_str,
                    source_id=error_ctx,
                    line_no=val_line,
                    full_path=full_path,
                )
                generation_occurrences.append(
                    {
                        "source_id": source_id,
                        "layer": layer_name,
                        "token_index": token_index,
                        "line": val_line,
                        "raw_path": full_path,
                        "canonical_key": CANONICAL_GENERATION_KEY,
                        "value": bval,
                    }
                )
            elif full_path in SUPPORTED_NON_GENERATION_PATHS:
                if val_str.lower().endswith(PARAMETER_FILE_EXTENSIONS):
                    raise ValueError(
                        f"{error_ctx}:{val_line}: parameter file path {val_str!r} assigned "
                        f"to {full_path!r} is unsupported; supply parameter files as positional "
                        "inputs or 'include file' with literal contents."
                    )
                non_generation_assignments.append(
                    {
                        "source_id": source_id,
                        "layer": layer_name,
                        "token_index": token_index,
                        "line": val_line,
                        "path": full_path,
                        "value": val_str,
                    }
                )
            else:
                raise ValueError(
                    f"{error_ctx}:{val_line}: unsupported, unknown, or abbreviated PHIL "
                    f"parameter path {full_path!r}."
                )
            continue

        raise ValueError(
            f"{error_ctx}:{next_line}: expected '=' or '{{' after {val!r}, got {next_val!r}."
        )

    if scope_stack:
        unclosed = ".".join(".".join(g) for g in scope_stack)
        raise ValueError(
            f"{error_ctx}: unclosed brace scope(s) at end of input: {unclosed!r}."
        )


def _resolve_and_parse_parameter_file(
    *,
    target_file: str,
    parent_source_id: str,
    layer_name: str,
    token_index: int | None = None,
    parameter_files: Mapping[str, str],
    consumed_parameter_files: set[str],
    inclusion_stack: tuple[str, ...],
    source_digests: dict[str, str],
    reference_edges: list[dict[str, Any]],
    generation_occurrences: list[dict[str, Any]],
    non_generation_assignments: list[dict[str, Any]],
) -> None:
    if target_file in inclusion_stack:
        cycle_chain = " -> ".join((*inclusion_stack, target_file))
        raise ValueError(
            f"Cyclic parameter file reference detected in {layer_name}: {cycle_chain}."
        )
    if target_file not in parameter_files:
        raise ValueError(
            f"Unresolved parameter file reference {target_file!r} from {parent_source_id!r} "
            f"(layer {layer_name!r}): literal contents were not supplied in parameter_files."
        )
    file_content = parameter_files[target_file]
    if not isinstance(file_content, str) or not file_content.strip():
        raise ValueError(
            f"parameter_files[{target_file!r}] must be a non-empty literal PHIL string."
        )
    consumed_parameter_files.add(target_file)
    file_sha = hashlib.sha256(file_content.encode("utf-8")).hexdigest()
    source_digests[target_file] = file_sha
    reference_edges.append(
        {
            "from_source_id": parent_source_id,
            "to_source_id": target_file,
            "layer": layer_name,
            "token_index": token_index,
        }
    )
    _parse_bounded_phil_text(
        file_content,
        source_id=target_file,
        layer_name=layer_name,
        token_index=None,
        parameter_files=parameter_files,
        consumed_parameter_files=consumed_parameter_files,
        inclusion_stack=(*inclusion_stack, target_file),
        source_digests=source_digests,
        reference_edges=reference_edges,
        generation_occurrences=generation_occurrences,
        non_generation_assignments=non_generation_assignments,
    )


def _parse_argv_tokens(
    argv: Sequence[str],
    *,
    source_id: str,
    layer_name: str,
    parameter_files: Mapping[str, str],
    consumed_parameter_files: set[str],
    source_digests: dict[str, str],
    reference_edges: list[dict[str, Any]],
    generation_occurrences: list[dict[str, Any]],
    non_generation_assignments: list[dict[str, Any]],
    positional_inputs: list[dict[str, Any]],
) -> None:
    if (
        isinstance(argv, (str, bytes, Mapping))
        or not isinstance(argv, Sequence)
        or len(argv) == 0
    ):
        raise ValueError(
            f"{layer_name} ({source_id}) argv must be a non-empty sequence of string tokens "
            "(opaque command strings are rejected)."
        )

    for idx, raw_tok in enumerate(argv):
        if not isinstance(raw_tok, str) or not raw_tok.strip() or raw_tok != raw_tok.strip():
            raise ValueError(
                f"{layer_name} ({source_id}) argv[{idx}] must be a non-empty stripped string "
                f"token, got {raw_tok!r}."
            )
        if _SHELL_META_RE.search(raw_tok):
            raise ValueError(
                f"{layer_name} ({source_id}) argv[{idx}]={raw_tok!r} contains forbidden "
                "shell metacharacters, wildcards, newlines, or interpolation syntax."
            )

        if idx == 0 and raw_tok == "phenix.refine":
            if raw_tok in parameter_files:
                raise ValueError(
                    f"Classification conflict in {layer_name} ({source_id}) argv[{idx}]={raw_tok!r}: "
                    "program executable token cannot also be supplied in parameter_files."
                )
            positional_inputs.append(
                {
                    "source_id": source_id,
                    "layer": layer_name,
                    "token_index": idx,
                    "token": raw_tok,
                    "classification": "program_executable",
                }
            )
            continue

        if raw_tok.startswith("-"):
            raise ValueError(
                f"{layer_name} ({source_id}) argv[{idx}]={raw_tok!r}: dash-prefixed CLI options "
                "are unsupported in bounded Stage 2 argv grammar."
            )

        if "=" in raw_tok:
            if "{" in raw_tok or "}" in raw_tok or "#" in raw_tok:
                # Delegate through bounded PHIL parser while rejecting comments/unbalanced braces in argv
                if "#" in raw_tok:
                    raise ValueError(
                        f"{layer_name} ({source_id}) argv[{idx}]={raw_tok!r} contains inline '#' comment."
                    )
            _parse_bounded_phil_text(
                raw_tok,
                source_id=source_id,
                layer_name=layer_name,
                token_index=idx,
                parameter_files=parameter_files,
                consumed_parameter_files=consumed_parameter_files,
                inclusion_stack=(source_id,),
                source_digests=source_digests,
                reference_edges=reference_edges,
                generation_occurrences=generation_occurrences,
                non_generation_assignments=non_generation_assignments,
            )
            continue

        lower_tok = raw_tok.lower()
        if lower_tok.endswith(MODEL_FILE_EXTENSIONS):
            if raw_tok in parameter_files:
                raise ValueError(
                    f"Classification conflict in {layer_name} ({source_id}) argv[{idx}]={raw_tok!r}: "
                    "token has model file extension and is classified as positional_model_input, "
                    "but was also supplied in parameter_files."
                )
            positional_inputs.append(
                {
                    "source_id": source_id,
                    "layer": layer_name,
                    "token_index": idx,
                    "token": raw_tok,
                    "classification": "positional_model_input",
                }
            )
        elif lower_tok.endswith(REFLECTION_FILE_EXTENSIONS):
            if raw_tok in parameter_files:
                raise ValueError(
                    f"Classification conflict in {layer_name} ({source_id}) argv[{idx}]={raw_tok!r}: "
                    "token has reflection file extension and is classified as positional_reflection_input, "
                    "but was also supplied in parameter_files."
                )
            positional_inputs.append(
                {
                    "source_id": source_id,
                    "layer": layer_name,
                    "token_index": idx,
                    "token": raw_tok,
                    "classification": "positional_reflection_input",
                }
            )
        elif lower_tok.endswith(PARAMETER_FILE_EXTENSIONS):
            positional_inputs.append(
                {
                    "source_id": source_id,
                    "layer": layer_name,
                    "token_index": idx,
                    "token": raw_tok,
                    "classification": "parameter_file_reference",
                }
            )
            _resolve_and_parse_parameter_file(
                target_file=raw_tok,
                parent_source_id=source_id,
                layer_name=layer_name,
                token_index=idx,
                parameter_files=parameter_files,
                consumed_parameter_files=consumed_parameter_files,
                inclusion_stack=(source_id,),
                source_digests=source_digests,
                reference_edges=reference_edges,
                generation_occurrences=generation_occurrences,
                non_generation_assignments=non_generation_assignments,
            )
        else:
            raise ValueError(
                f"{layer_name} ({source_id}) argv[{idx}]={raw_tok!r} is an unclassified "
                "positional argument or unsupported parameter file reference."
            )


def verify_flag_generation_guard(
    *,
    arm: str,
    sources: Mapping[str, Mapping[str, Any]],
    parameter_files: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Verify the restrictive Stage 2 R-free flag generation guard across all four source layers.

    Accepted grammar and epistemic limits:
    - This function is a restrictive guard for bounded Stage 2 inputs, NOT a general PHIL
      parser and NOT a runtime executor (``native_effective_file_compatibility="unassessed"``).
    - Requires explicit ``arm`` in ``CANONICAL_ARM_IDS`` and ``sources`` covering all four
      canonical layers (``primary_command``, ``mechanical_backup``, ``actual_command``,
      ``effective_eff``) with unique ``source_id`` values and explicit ``state`` in
      ``{'supplied', 'not_applicable', 'unavailable'}``.
    - Executed ``Arm 1b`` requires all four layers ``supplied`` (unused ``mechanical_backup``
      is still inspected). ``Arm 1a`` may mark ``mechanical_backup`` ``not_applicable`` ONLY
      with an explicit non-empty ``controller_contract_justification``.
    - Any ``r_free_flags.generate = True`` at ANY layer or referenced parameter file
      (even if later overridden by ``False`` or inside an unused ``mechanical_backup``)
      raises ``ValueError``.
    - Requires explicit ``r_free_flags.generate = False`` in the ``effective_eff`` layer;
      omission raises ``ValueError`` (static source ``False`` default is never inferred).
    - Source digests in ``source_digests`` hash the exact unstripped UTF-8 text of
      ``effective_eff`` (``phil_text.encode('utf-8')``) and each resolved entry in
      ``parameter_files``, and the NUL-delimited UTF-8 token sequence
      (``'\\x00'.join(argv).encode('utf-8')``) of command layers. Leading blank lines in
      ``effective_eff`` and ``parameter_files`` are preserved so reported line numbers
      match the exact supplied text.
    - If ``actual_command`` or ``effective_eff`` (or any required layer) is ``unavailable``,
      returns ``guard_ok=False`` and ``incomplete=True`` with preserved diagnostics rather
      than a passing receipt.
    """
    if not isinstance(arm, str) or arm not in CANONICAL_ARM_IDS:
        raise ValueError(f"arm must be one of {CANONICAL_ARM_IDS}, got {arm!r}.")

    if not isinstance(sources, Mapping):
        raise ValueError("sources must be a mapping covering all four canonical source layers.")

    expected_layers = set(CANONICAL_SOURCE_LAYERS)
    actual_layers = set(sources.keys())
    if actual_layers != expected_layers:
        missing = sorted(expected_layers - actual_layers)
        extra = sorted(actual_layers - expected_layers)
        raise ValueError(
            f"sources must contain exact layer keys {list(CANONICAL_SOURCE_LAYERS)}; "
            f"missing={missing}, unknown={extra}."
        )

    param_files_map: dict[str, str] = {}
    if parameter_files is not None:
        if not isinstance(parameter_files, Mapping):
            raise ValueError("parameter_files must be a mapping of filename -> literal PHIL text.")
        for pf_name, pf_text in parameter_files.items():
            if (
                not isinstance(pf_name, str)
                or not pf_name.strip()
                or pf_name != pf_name.strip()
            ):
                raise ValueError(
                    f"parameter_files key must be a non-empty stripped string, got {pf_name!r}."
                )
            if _SHELL_META_RE.search(pf_name):
                raise ValueError(
                    f"parameter_files key {pf_name!r} contains forbidden shell metacharacters."
                )
            lower_pf = pf_name.lower()
            if (
                pf_name == "phenix.refine"
                or lower_pf.endswith(MODEL_FILE_EXTENSIONS)
                or lower_pf.endswith(REFLECTION_FILE_EXTENSIONS)
            ):
                raise ValueError(
                    f"Classification conflict for parameter_files[{pf_name!r}]: key has a "
                    "model/reflection/executable classification rather than a parameter file extension."
                )
            if not lower_pf.endswith(PARAMETER_FILE_EXTENSIONS):
                raise ValueError(
                    f"Unsupported parameter_files key {pf_name!r}: must end with one of "
                    f"{PARAMETER_FILE_EXTENSIONS}."
                )
            if not isinstance(pf_text, str) or not pf_text.strip():
                raise ValueError(
                    f"parameter_files[{pf_name!r}] must be a non-empty literal PHIL string."
                )
            param_files_map[pf_name] = pf_text

    seen_source_ids: set[str] = set()
    consumed_parameter_files: set[str] = set()
    source_digests: dict[str, str] = {}
    layer_states: dict[str, str] = {}
    unavailable_sources: dict[str, dict[str, str]] = {}
    not_applicable_sources: dict[str, dict[str, str]] = {}
    reference_edges: list[dict[str, Any]] = []
    generation_occurrences: list[dict[str, Any]] = []
    non_generation_assignments: list[dict[str, Any]] = []
    positional_inputs: list[dict[str, Any]] = []

    allowed_record_keys = {
        "source_id",
        "state",
        "argv",
        "phil_text",
        "reason",
        "controller_contract_justification",
    }

    for layer_name in CANONICAL_SOURCE_LAYERS:
        rec = sources[layer_name]
        if not isinstance(rec, Mapping):
            raise ValueError(f"sources[{layer_name!r}] must be a mapping.")
        unknown_rec_keys = sorted(set(rec.keys()) - allowed_record_keys)
        if unknown_rec_keys:
            raise ValueError(
                f"sources[{layer_name!r}] contains unknown keys: {unknown_rec_keys}."
            )
        if "source_id" not in rec:
            raise ValueError(f"sources[{layer_name!r}] is missing required 'source_id'.")
        source_id = _validate_strict_source_id(
            rec["source_id"], field_name=f"sources[{layer_name!r}].source_id"
        )
        if source_id in seen_source_ids or source_id in param_files_map:
            raise ValueError(
                f"Duplicate source_id {source_id!r} on layer {layer_name!r}; every source "
                "and parameter file must have a unique identifier."
            )
        seen_source_ids.add(source_id)

        if "state" not in rec:
            raise ValueError(f"sources[{layer_name!r}] is missing required 'state'.")
        state = rec["state"]
        if not isinstance(state, str) or state not in ALLOWED_SOURCE_STATES:
            raise ValueError(
                f"sources[{layer_name!r}].state must be one of {sorted(ALLOWED_SOURCE_STATES)}, "
                f"got {state!r}."
            )
        layer_states[layer_name] = state

        if state == "not_applicable":
            if rec.get("argv") is not None or rec.get("phil_text") is not None:
                raise ValueError(
                    f"sources[{layer_name!r}] with state='not_applicable' cannot carry argv or phil_text."
                )
            if layer_name in ("actual_command", "effective_eff"):
                raise ValueError(
                    f"sources[{layer_name!r}] cannot be 'not_applicable'; actual_command and "
                    "effective_eff are mandatory on every arm."
                )
            if arm == "1b":
                raise ValueError(
                    f"Arm 1b requires all four source layers; {layer_name!r} cannot be 'not_applicable'."
                )
            if arm == "1a":
                if layer_name == "primary_command":
                    raise ValueError(
                        "Arm 1a requires 'primary_command'; it cannot be 'not_applicable'."
                    )
                if "controller_contract_justification" not in rec:
                    raise ValueError(
                        "Arm 1a 'mechanical_backup' applicability is not established by W3/W4: "
                        "marking it 'not_applicable' requires an explicit non-empty "
                        "'controller_contract_justification'."
                    )
                just = _validate_nonempty_str(
                    rec["controller_contract_justification"],
                    field_name=f"sources[{layer_name!r}].controller_contract_justification",
                )
                not_applicable_sources[layer_name] = {
                    "source_id": source_id,
                    "justification": just,
                }
            else:
                reason = _validate_nonempty_str(
                    rec.get("reason") or rec.get("controller_contract_justification"),
                    field_name=f"sources[{layer_name!r}].reason",
                )
                not_applicable_sources[layer_name] = {
                    "source_id": source_id,
                    "justification": reason,
                }
            continue

        if state == "unavailable":
            if rec.get("argv") is not None or rec.get("phil_text") is not None:
                raise ValueError(
                    f"sources[{layer_name!r}] with state='unavailable' cannot carry argv or phil_text."
                )
            reason = _validate_nonempty_str(
                rec.get("reason"), field_name=f"sources[{layer_name!r}].reason"
            )
            unavailable_sources[layer_name] = {
                "source_id": source_id,
                "reason": reason,
            }
            continue

        # state == "supplied"
        if layer_name in COMMAND_SOURCE_LAYERS:
            if "argv" not in rec or rec["argv"] is None:
                raise ValueError(
                    f"sources[{layer_name!r}] with state='supplied' requires 'argv' token list."
                )
            if rec.get("phil_text") is not None:
                raise ValueError(
                    f"sources[{layer_name!r}] command layer must supply 'argv', not 'phil_text'."
                )
            argv_val = rec["argv"]
            _parse_argv_tokens(
                argv_val,
                source_id=source_id,
                layer_name=layer_name,
                parameter_files=param_files_map,
                consumed_parameter_files=consumed_parameter_files,
                source_digests=source_digests,
                reference_edges=reference_edges,
                generation_occurrences=generation_occurrences,
                non_generation_assignments=non_generation_assignments,
                positional_inputs=positional_inputs,
            )
            joined_argv = "\x00".join(argv_val)
            source_digests[source_id] = hashlib.sha256(
                joined_argv.encode("utf-8")
            ).hexdigest()
        else:
            # effective_eff
            if "phil_text" not in rec or rec["phil_text"] is None:
                raise ValueError(
                    "sources['effective_eff'] with state='supplied' requires 'phil_text'."
                )
            if rec.get("argv") is not None:
                raise ValueError(
                    "sources['effective_eff'] must supply 'phil_text', not 'argv'."
                )
            phil_text = rec["phil_text"]
            if not isinstance(phil_text, str) or not phil_text.strip():
                raise ValueError(
                    "sources['effective_eff'].phil_text must be a non-empty string, "
                    f"got {phil_text!r}."
                )
            source_digests[source_id] = hashlib.sha256(
                phil_text.encode("utf-8")
            ).hexdigest()
            _parse_bounded_phil_text(
                phil_text,
                source_id=source_id,
                layer_name=layer_name,
                parameter_files=param_files_map,
                consumed_parameter_files=consumed_parameter_files,
                inclusion_stack=(source_id,),
                source_digests=source_digests,
                reference_edges=reference_edges,
                generation_occurrences=generation_occurrences,
                non_generation_assignments=non_generation_assignments,
            )

    # Every supplied parameter_files entry must be consumed through reference traversal;
    # inspect any unconsumed entries for malformed syntax or generate=True and fail closed.
    unconsumed_files = sorted(set(param_files_map.keys()) - consumed_parameter_files)
    for orphan_file in unconsumed_files:
        _parse_bounded_phil_text(
            param_files_map[orphan_file],
            source_id=orphan_file,
            layer_name="unconsumed_parameter_files",
            parameter_files=param_files_map,
            consumed_parameter_files=set(consumed_parameter_files),
            inclusion_stack=(orphan_file,),
            source_digests={},
            reference_edges=[],
            generation_occurrences=generation_occurrences,
            non_generation_assignments=[],
        )

    # Fail closed if ANY occurrence in ANY layer or parameter file requested generate=True
    true_occurrences = [occ for occ in generation_occurrences if occ["value"] is True]
    if true_occurrences:
        first_true = true_occurrences[0]
        tok_ctx = (
            f", token_index={first_true['token_index']}"
            if first_true["token_index"] is not None
            else ""
        )
        raise ValueError(
            f"Forbidden R-free flag generation request ({first_true['raw_path']} = True) "
            f"detected in layer={first_true['layer']!r}, source_id={first_true['source_id']!r}"
            f"{tok_ctx} (line {first_true['line']}); any True request fails closed even if "
            "overridden later by False or in an unused backup."
        )

    if unconsumed_files:
        raise ValueError(
            "Unconsumed parameter_files entries were supplied but never referenced by any "
            f"source layer: {unconsumed_files}."
        )

    # Check effective_eff explicit False requirement when effective_eff is supplied
    effective_false_occurrences = [
        occ
        for occ in generation_occurrences
        if occ["layer"] == "effective_eff" and occ["value"] is False
    ]
    if layer_states["effective_eff"] == "supplied" and not effective_false_occurrences:
        raise ValueError(
            "sources['effective_eff'] is missing an explicit r_free_flags.generate = False "
            "assignment (under a witnessed path); omission is unresolved and never inferred "
            "as False from static defaults."
        )

    if unavailable_sources:
        return {
            "guard_ok": False,
            "passed": False,
            "incomplete": True,
            "status": "INCOMPLETE_UNAVAILABLE_SOURCES",
            "arm": arm,
            "layer_states": layer_states,
            "unavailable_sources": unavailable_sources,
            "not_applicable_sources": not_applicable_sources,
            "source_digests": source_digests,
            "reference_edges": tuple(reference_edges),
            "generation_occurrences": tuple(generation_occurrences),
            "non_generation_assignments": tuple(non_generation_assignments),
            "positional_inputs": tuple(positional_inputs),
            "effective_generation_explicit_false": bool(effective_false_occurrences),
            "native_effective_file_compatibility": NATIVE_EFFECTIVE_FILE_COMPATIBILITY,
            "epistemic_note": (
                "Incomplete receipt: one or more required sources are unavailable. "
                "Proves only supplied-source consistency, not hidden-default coverage or execution."
            ),
            "registration_status": REGISTRATION_STATUS,
            "stage2_status": STAGE2_FLAGS_STATUS,
            "executed": False,
        }

    return {
        "guard_ok": True,
        "passed": True,
        "incomplete": False,
        "status": "VERIFIED_SUPPLIED_SOURCES_FALSE",
        "arm": arm,
        "layer_states": layer_states,
        "unavailable_sources": {},
        "not_applicable_sources": not_applicable_sources,
        "source_digests": source_digests,
        "reference_edges": tuple(reference_edges),
        "generation_occurrences": tuple(generation_occurrences),
        "non_generation_assignments": tuple(non_generation_assignments),
        "positional_inputs": tuple(positional_inputs),
        "effective_generation_explicit_false": True,
        "native_effective_file_compatibility": NATIVE_EFFECTIVE_FILE_COMPATIBILITY,
        "epistemic_note": (
            "Proves only supplied input consistency across declared sources under the "
            "bounded Stage 2 grammar; does not prove hidden-default coverage or runtime execution."
        ),
        "registration_status": REGISTRATION_STATUS,
        "stage2_status": STAGE2_FLAGS_STATUS,
        "executed": False,
    }


def _validate_hkl_tuple(hkl: Any, *, field_name: str) -> tuple[int, int, int]:
    if not isinstance(hkl, tuple) or len(hkl) != 3:
        raise ValueError(
            f"{field_name} key must be a 3-tuple of strict ints (h, k, l), got {hkl!r}."
        )
    h = _validate_strict_int(hkl[0], field_name=f"{field_name}[0]")
    k = _validate_strict_int(hkl[1], field_name=f"{field_name}[1]")
    l_idx = _validate_strict_int(hkl[2], field_name=f"{field_name}[2]")
    if h == 0 and k == 0 and l_idx == 0:
        raise ValueError(f"{field_name} cannot contain Miller index (0, 0, 0).")
    return (h, k, l_idx)


def _normalize_hkl_flag_map(
    raw_map: Any, *, field_name: str
) -> dict[tuple[int, int, int], int]:
    if not isinstance(raw_map, Mapping) or len(raw_map) == 0:
        raise ValueError(
            f"{field_name} must be a non-empty mapping of (h, k, l) -> int flag "
            "(absent or empty reflection flag maps are rejected)."
        )
    normalized: dict[tuple[int, int, int], int] = {}
    for raw_k, raw_v in raw_map.items():
        hkl = _validate_hkl_tuple(raw_k, field_name=f"{field_name}.key")
        flag_val = _validate_strict_int(raw_v, field_name=f"{field_name}[{hkl}]")
        if flag_val < 0:
            raise ValueError(
                f"{field_name}[{hkl}] must be a non-negative integer flag, got {flag_val}."
            )
        normalized[hkl] = flag_val
    return normalized


def _normalize_sleep_hkl_set(
    raw_sleep: Any,
    *,
    field_name: str,
) -> set[tuple[int, int, int]]:
    if (
        raw_sleep is _MISSING
        or raw_sleep is None
        or isinstance(raw_sleep, (str, bytes, Mapping))
        or not isinstance(raw_sleep, Collection)
    ):
        raise ValueError(
            f"{field_name} must be an explicit collection/set of (h, k, l) tuples "
            "(cannot be omitted or None)."
        )
    result: set[tuple[int, int, int]] = set()
    for idx, item in enumerate(raw_sleep):
        hkl = _validate_hkl_tuple(item, field_name=f"{field_name}[{idx}]")
        if hkl in result:
            raise ValueError(f"{field_name} contains duplicate HKL {hkl}.")
        result.add(hkl)
    return result


def _hash_hkl_map(hkl_map: Mapping[tuple[int, int, int], int]) -> str:
    payload = "\n".join(
        f"{h},{k},{l_idx}:{ hkl_map[(h, k, l_idx)] }"
        for h, k, l_idx in sorted(hkl_map.keys())
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _hash_hkl_set(hkl_set: set[tuple[int, int, int]]) -> str:
    payload = "\n".join(f"{h},{k},{l_idx}" for h, k, l_idx in sorted(hkl_set))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def verify_hkl_and_sleep_membership(
    *,
    before_hkl_flags: Mapping[tuple[int, int, int], int],
    after_hkl_flags: Mapping[tuple[int, int, int], int],
    before_sleep_hkls: Collection[tuple[int, int, int]] = _MISSING,  # type: ignore[assignment]
    after_sleep_hkls: Collection[tuple[int, int, int]] = _MISSING,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Verify exact preservation of supplied per-HKL R-free flag maps and sleep sets.

    Scope and epistemic boundary:
    - Proves exact before/after preservation of supplied ``(h, k, l) -> flag`` maps and
      supplied ``(h, k, l)`` sleep sets ONLY; does NOT prove scientific mask construction
      or source-role admission.
    - Per U09 (``ref/research/phenix_step1_user_selections_2026-11-15.md:185-189``),
      sealed ``R_sleep`` reflections are physically removed from ``common_analysis_derivative``
      before comparative refinement arms, whereas parent/pre-sleep controls retain them.
      Therefore this generic preservation comparator validates flag-map identity and
      sleep-set identity independently, without imposing an unconditional subset or
      disjointness requirement between the active flag map and the sealed sleep set.

    Enforces:
    - Non-empty ``before_hkl_flags`` and ``after_hkl_flags`` mappings with strict 3-tuple
      integer Miller indices ``(h, k, l)`` and strict non-negative integer flag values
      (rejecting ``bool``, ``float``, ``str``, ``None``, and ``(0, 0, 0)``).
    - Mandatory explicit ``before_sleep_hkls`` and ``after_sleep_hkls`` sets/collections
      (never inferred safe from absent sleep sets), independently validated for strict
      3-tuple integer Miller indices and no duplicates.
    - Exact per-HKL key-set equality and per-HKL flag value equality (rejecting missing
      HKLs, extra HKLs, same-count HKL replacements, and same-count flag swaps).
    - Exact sleep-set HKL membership equality before and after.
    """
    before_map = _normalize_hkl_flag_map(
        before_hkl_flags, field_name="before_hkl_flags"
    )
    after_map = _normalize_hkl_flag_map(after_hkl_flags, field_name="after_hkl_flags")
    before_sleep = _normalize_sleep_hkl_set(
        before_sleep_hkls, field_name="before_sleep_hkls"
    )
    after_sleep = _normalize_sleep_hkl_set(
        after_sleep_hkls, field_name="after_sleep_hkls"
    )

    before_keys = set(before_map.keys())
    after_keys = set(after_map.keys())

    missing_hkls = sorted(before_keys - after_keys)
    extra_hkls = sorted(after_keys - before_keys)
    common_hkls = before_keys & after_keys
    mutated_flag_hkls = sorted(
        hkl for hkl in common_hkls if before_map[hkl] != after_map[hkl]
    )

    missing_sleep_hkls = sorted(before_sleep - after_sleep)
    extra_sleep_hkls = sorted(after_sleep - before_sleep)

    if (
        missing_hkls
        or extra_hkls
        or mutated_flag_hkls
        or missing_sleep_hkls
        or extra_sleep_hkls
    ):
        raise ValueError(
            "HKL flag map or sleep-set membership mutation detected "
            "(INCOMMENSURABLE_REFLECTION_DROP_OR_DOMAIN_CHANGE / "
            "INCOMMENSURABLE_FREE_OR_SLEEP_FLAG_MUTATION): "
            f"missing_hkls={missing_hkls}, extra_hkls={extra_hkls}, "
            f"mutated_flag_hkls={mutated_flag_hkls}, "
            f"missing_sleep_hkls={missing_sleep_hkls}, extra_sleep_hkls={extra_sleep_hkls}."
        )

    return {
        "membership_ok": True,
        "hkl_count": len(before_map),
        "sleep_hkl_count": len(before_sleep),
        "before_hkl_flags_sha256": _hash_hkl_map(before_map),
        "after_hkl_flags_sha256": _hash_hkl_map(after_map),
        "before_sleep_sha256": _hash_hkl_set(before_sleep),
        "after_sleep_sha256": _hash_hkl_set(after_sleep),
        "missing_hkls": (),
        "extra_hkls": (),
        "mutated_flag_hkls": (),
        "missing_sleep_hkls": (),
        "extra_sleep_hkls": (),
        "registration_status": REGISTRATION_STATUS,
        "stage2_status": STAGE2_FLAGS_STATUS,
        "executed": False,
    }


__all__ = [
    "ALLOWED_SOURCE_STATES",
    "CANONICAL_ARM_IDS",
    "CANONICAL_GENERATION_KEY",
    "CANONICAL_SOURCE_LAYERS",
    "NATIVE_EFFECTIVE_FILE_COMPATIBILITY",
    "REGISTRATION_STATUS",
    "STAGE2_FLAGS_STATUS",
    "STATIC_WITNESS_PATH",
    "SUPPORTED_NON_GENERATION_PATHS",
    "WITNESSED_GENERATION_PATHS",
    "verify_flag_generation_guard",
    "verify_hkl_and_sleep_membership",
]
