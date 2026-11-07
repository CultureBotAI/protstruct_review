#!/usr/bin/env python3
"""Pure native REFMAC5 log parser for 1SAR verification.

This module parses only what a REFMAC5 log text reports:
- Named CCP4 loggraph ``$TABLE:`` blocks by title, column headers, and four
  ``$$`` delimiters, preserving raw tokens and 1-based line numbers.
- Every cycle-summary row from ``$TABLE: Rfactor analysis, stats vs cycle :``.
- Every paired detailed ``Overall R factor`` / ``Free R factor`` block, kept
  strictly distinct from weighted R (``WR_used``, ``WR_free``,
  ``Overall weighted R factor``, ``Free weighted R factor``), weighted R2
  (``Overall weighted R2 factor``, ``Free weighted R2 factor``), and FOM, plus
  optional ``CGMAT cycle number`` markers and recognized optional correlation,
  DPI, and ML-uncertainty fields when present.
- Per-bin ``NR_used`` / ``NR_free`` integer reflection counts and ``Rf_used`` /
  ``Rf_free`` tokens from every resolution R-factor table (initial,
  intermediate, and final cycles), and per-bin ``NREFall == NREFa + NREFc``
  counts from resolution FOM tables.
- The ``$TEXT:Result: $$ Final results $$`` summary R-factor and R-free pair.

Reconciles duplicate reporting locations across detailed cycle blocks, the
cycle-summary table, and the final-results block by exact ``Decimal`` value
equality while preserving each location's original token and printed decimal
precision (recognizing that detailed ``Cycle 1`` corresponds to summary
``Ncyc 0`` and detailed ``Cycle N+1`` to summary ``Ncyc N``). Rejects
contradictions, malformed or truncated tables, nonfinite or overflow R tokens,
out-of-domain percentages, invalid counts, and ambiguous cycles.

This parser reports only what the log text states. It never proves process
termination/returncode, effective HKL membership, cross-table free-percentage
denominator arithmetic, model preservation, residual reconstruction, or EVAL
admission.
"""

from __future__ import annotations

import math
import re
from decimal import Decimal, InvalidOperation
from typing import Any


RESOLUTION_RFACTOR_HEADER_TOKENS: tuple[str, ...] = (
    "M(4SSQ/LL)",
    "NR_used",
    "%_obs",
    "M(Fo_used)",
    "M(Fc_used)",
    "Rf_used",
    "WR_used",
    "NR_free",
    "M(Fo_free)",
    "M(Fc_free)",
    "Rf_free",
    "WR_free",
)

RESOLUTION_FOM_HEADER_TOKENS: tuple[str, ...] = (
    "<4SSQ/LL>",
    "NREFa",
    "FOMa",
    "NREFc",
    "FOMc",
    "NREFall",
    "FOMall",
    "SigmaA_Fc1",
)

CYCLE_SUMMARY_HEADER_TOKENS: tuple[str, ...] = (
    "Ncyc",
    "Rfact",
    "Rfree",
    "FOM",
    "-LL",
    "-LLfree",
    "rmsBOND",
    "zBOND",
    "rmsANGL",
    "zANGL",
    "rmsCHIRAL",
)

_TABLE_START_RE = re.compile(r"^\s*\$TABLE\s*:(.*)$")
_TEXT_START_RE = re.compile(r"^\s*\$TEXT\s*:([^:]+):\s*\$\$(.*?)\$\$\s*$")
_SUMMARY_DIRECTIVE_RE = re.compile(r"^\s*\$SUMMARY\s*:[^:]+:\s*\$\$.*\$\$\s*$")
_TEXT_REF_DIRECTIVE_RE = re.compile(r"^\s*:TEXT:[^:]+:\s*\$\$\s*$")

_RESLN_RFACTOR_TITLE_RE = re.compile(
    r"^\s*Cycle\s+(\S+)\.\s*Rfactor analysis,\s*F distribution v(?:s\.?)?\s+resln\s*:?\s*$"
)
_RESLN_FOM_TITLE_RE = re.compile(
    r"^\s*Cycle\s+(\S+)\.\s*Fom\(<cos\(DelPhi\)>-acentric,\s*centric,\s*overall v(?:s\.?)?\s+resln\s*:?\s*$"
)
_CYCLE_SUMMARY_TITLE_RE = re.compile(
    r"^\s*Rfactor analysis,\s*stats vs\.?\s+cycle\s*:?\s*$"
)
_GRAPH_CYCLE_RE = re.compile(r"(?:^|:)\s*Cycle\s+(\S+?)\.(?=\s|$)")
_GRAPH_VS_CYCLE_RE = re.compile(r"\bvs\.?\s+cycle\b", re.IGNORECASE)
_GRAPH_ANY_CYCLE_WORD_RE = re.compile(r"\bcycle\b", re.IGNORECASE)

_NONNEGATIVE_INT_RE = re.compile(r"^[0-9]+$")
_R_TOKEN_RE = re.compile(r"^[0-9]+\.[0-9]+$")
_FINITE_FLOAT_TOKEN_RE = re.compile(
    r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$"
)

_BANNER_VERSION_RE = re.compile(
    r"###\s*(CCP4\s+\S+)\s*:\s*Refmac_\S+\s+version\s+(\S+)\s*:"
)
_RUN_DATE_RE = re.compile(r"Run date:\s*(\d{1,2}/\s*\d{1,2}/\d{4})")
_DATA_NCYC_RE = re.compile(r"^\s*Data line---\s+NCYC\s+(\S+)(?:\s+(.*))?$")
_REFINEMENT_CYCLES_RE = re.compile(r"^\s*Refinement cycles\s*:\s*(\S+)(?:\s+(.*))?$")


def _parse_nonnegative_int_token(token: str, *, context: str, line_no: int) -> int:
    """Validate and parse a non-negative integer token, rejecting decimals/negatives."""
    if not isinstance(token, str) or not _NONNEGATIVE_INT_RE.fullmatch(token):
        raise ValueError(
            f"Invalid non-negative integer count token {token!r} for {context} at line {line_no}"
        )
    return int(token)


def _parse_positive_int_token(token: str, *, context: str, line_no: int) -> int:
    """Validate and parse a strictly positive integer token (>= 1)."""
    value = _parse_nonnegative_int_token(token, context=context, line_no=line_no)
    if value <= 0:
        raise ValueError(
            f"Positive integer required for {context} at line {line_no}, got {token!r}"
        )
    return value


def _parse_r_token(
    token: str, *, context: str, line_no: int
) -> tuple[Decimal, float, int]:
    """Validate a printed unweighted R token.

    R must be a finite, non-negative decimal token with explicit fractional
    digits and no overflow/invalid markers. No arbitrary upper bound (such as 1
    or 99) is imposed on finite unweighted R values.
    """
    if not isinstance(token, str) or not _R_TOKEN_RE.fullmatch(token):
        raise ValueError(
            f"Invalid or nonfinite/sentinel R token {token!r} for {context} at line {line_no}"
        )
    try:
        dec_value = Decimal(token)
    except InvalidOperation as exc:
        raise ValueError(
            f"Unparseable R token {token!r} for {context} at line {line_no}"
        ) from exc
    if not dec_value.is_finite() or dec_value < Decimal("0"):
        raise ValueError(
            f"Non-finite or negative R token {token!r} for {context} at line {line_no}"
        )
    float_value = float(dec_value)
    if not math.isfinite(float_value) or float_value < 0.0:
        raise ValueError(
            f"Non-finite R value {token!r} for {context} at line {line_no}"
        )
    decimal_places = len(token.partition(".")[2])
    return dec_value, float_value, decimal_places


def _parse_finite_float_token(
    token: str,
    *,
    context: str,
    line_no: int,
    nonnegative: bool = False,
) -> float:
    """Validate a finite numeric token, rejecting NaN, infinity, and '*' overflow tokens."""
    if not isinstance(token, str) or not token or "*" in token:
        raise ValueError(
            f"Invalid numeric token {token!r} for {context} at line {line_no}"
        )
    lowered = token.lower()
    if lowered in {"nan", "+nan", "-nan", "inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"}:
        raise ValueError(
            f"Non-finite numeric token {token!r} for {context} at line {line_no}"
        )
    if not _FINITE_FLOAT_TOKEN_RE.fullmatch(token):
        raise ValueError(
            f"Malformed numeric token {token!r} for {context} at line {line_no}"
        )
    try:
        dec_value = Decimal(token)
    except InvalidOperation as exc:
        raise ValueError(
            f"Malformed numeric token {token!r} for {context} at line {line_no}"
        ) from exc
    if not dec_value.is_finite():
        raise ValueError(
            f"Non-finite numeric token {token!r} for {context} at line {line_no}"
        )
    if nonnegative and dec_value < Decimal("0"):
        raise ValueError(
            f"Negative numeric token {token!r} for {context} at line {line_no}"
        )
    value = float(dec_value)
    if not math.isfinite(value):
        raise ValueError(
            f"Overflow numeric token {token!r} for {context} at line {line_no}"
        )
    return value


def _parse_percentage_token(
    token: str,
    *,
    context: str,
    line_no: int,
) -> tuple[Decimal, float, int]:
    """Validate a finite percentage token in the closed physical domain [0, 100].

    Returns ``(dec_value, float_value, effective_decimal_places)`` where
    ``effective_decimal_places`` is the number of fractional decimal places
    after applying any scientific-notation exponent (bounded below by 0),
    preserving significant trailing zeros while retaining the raw token.
    """
    value = _parse_finite_float_token(
        token,
        context=context,
        line_no=line_no,
        nonnegative=True,
    )
    dec_value = Decimal(token)
    if dec_value < Decimal("0") or dec_value > Decimal("100"):
        raise ValueError(
            f"Percentage token {token!r} out of [0, 100] domain for {context} at line {line_no}"
        )
    exp = dec_value.as_tuple().exponent
    if not isinstance(exp, int):
        raise ValueError(
            f"Non-finite percentage token {token!r} for {context} at line {line_no}"
        )
    decimal_places = max(0, -exp)
    return dec_value, value, decimal_places


def _looks_like_numeric_or_invalid_value_token(token: str) -> bool:
    """Return True if a token parses as a Decimal/NaN/Inf or contains '*'."""
    if "*" in token:
        return True
    try:
        Decimal(token)
        return True
    except InvalidOperation:
        return False


def _parse_table_block(
    lines: list[str], start_idx: int
) -> tuple[dict[str, Any], int]:
    """Parse one ``$TABLE:`` block starting at 0-based ``start_idx``.

    Enforces the four-``$$`` CCP4 loggraph delimiter structure:
    1. ``header_start_line``: standalone ``$$`` line after ``$GRAPHS`` lines
    2. ``header_end_line``: ``$$`` closing the header tokens (at the end of the
       last header line or on its own ``$$`` line)
    3. ``data_start_line``: standalone ``$$`` line immediately following
       ``header_end_line``
    4. ``data_end_line``: standalone ``$$`` line closing the data rows
    """
    title_line_no = start_idx + 1
    title_line_text = lines[start_idx]
    title_match = _TABLE_START_RE.match(title_line_text)
    if not title_match:
        raise ValueError(f"Expected $TABLE: at line {title_line_no}")
    raw_title_body = title_match.group(1).strip()
    if not raw_title_body or raw_title_body == ":" or "$$" in title_line_text:
        raise ValueError(
            f"Malformed $TABLE title at line {title_line_no}: {title_line_text!r}"
        )

    total_lines = len(lines)
    idx = start_idx + 1
    graph_declaration_lines: list[dict[str, Any]] = []
    header_start_line: int | None = None

    # Phase 1: $GRAPHS declarations up to header_start_line ($$)
    while idx < total_lines:
        line_no = idx + 1
        raw_line = lines[idx]
        stripped = raw_line.strip()
        if raw_line.count("$$") > 1:
            raise ValueError(
                f"Multiple $$ delimiters on line {line_no} in $TABLE starting at line {title_line_no}"
            )
        if stripped == "$$":
            header_start_line = line_no
            idx += 1
            break
        if "$$" in raw_line:
            raise ValueError(
                f"Malformed header_start $$ delimiter at line {line_no} in $TABLE starting at line {title_line_no}"
            )
        if stripped.startswith("$GRAPHS") or (
            graph_declaration_lines and stripped.startswith(":")
        ):
            graph_declaration_lines.append({"line": line_no, "text": raw_line})
            idx += 1
            continue
        raise ValueError(
            f"Unexpected line {line_no} before header_start $$ in $TABLE starting at line {title_line_no}: {raw_line!r}"
        )

    if header_start_line is None:
        raise ValueError(
            f"Unclosed $TABLE starting at line {title_line_no}: missing header_start $$"
        )

    # Phase 2: Header lines up to header_end_line ($$)
    header_lines: list[dict[str, Any]] = []
    header_tokens: list[str] = []
    header_end_line: int | None = None

    while idx < total_lines:
        line_no = idx + 1
        raw_line = lines[idx]
        stripped = raw_line.strip()
        if raw_line.count("$$") > 1:
            raise ValueError(
                f"Multiple $$ delimiters on header line {line_no} in $TABLE starting at line {title_line_no}"
            )
        if stripped.startswith(("$TABLE", "$GRAPHS", "$TEXT", "$SUMMARY", ":TEXT:")) or stripped.startswith("----"):
            raise ValueError(
                f"Malformed $TABLE starting at line {title_line_no}: unexpected boundary at line {line_no} before header_end $$"
            )
        if "$$" in raw_line:
            before_dd, _, after_dd = raw_line.partition("$$")
            if after_dd.strip():
                raise ValueError(
                    f"Trailing tokens after header_end $$ at line {line_no} in $TABLE starting at line {title_line_no}"
                )
            if before_dd.strip():
                header_lines.append({"line": line_no, "text": raw_line})
                header_tokens.extend(before_dd.split())
            header_end_line = line_no
            idx += 1
            break
        if not stripped:
            raise ValueError(
                f"Blank line {line_no} inside header of $TABLE starting at line {title_line_no}"
            )
        header_lines.append({"line": line_no, "text": raw_line})
        header_tokens.extend(stripped.split())
        idx += 1

    if header_end_line is None:
        raise ValueError(
            f"Unclosed $TABLE header starting at line {title_line_no}: missing header_end $$"
        )
    if not header_tokens:
        raise ValueError(
            f"Empty header tokens in $TABLE starting at line {title_line_no}"
        )

    # Phase 3: data_start_line must immediately follow header_end_line and be standalone $$
    if idx >= total_lines:
        raise ValueError(
            f"Truncated $TABLE starting at line {title_line_no}: missing data_start $$ after line {header_end_line}"
        )
    data_start_line = idx + 1
    raw_data_start = lines[idx]
    if raw_data_start.count("$$") != 1 or raw_data_start.strip() != "$$":
        raise ValueError(
            f"Expected standalone data_start $$ at line {data_start_line} in $TABLE starting at line {title_line_no}, got {raw_data_start!r}"
        )
    idx += 1

    # Phase 4: Data rows up to data_end_line (standalone $$)
    data_rows: list[dict[str, Any]] = []
    data_end_line: int | None = None
    expected_col_count = len(header_tokens)

    while idx < total_lines:
        line_no = idx + 1
        raw_line = lines[idx]
        stripped = raw_line.strip()
        if raw_line.count("$$") > 1:
            raise ValueError(
                f"Multiple $$ delimiters on line {line_no} in $TABLE starting at line {title_line_no}"
            )
        if stripped == "$$":
            data_end_line = line_no
            idx += 1
            break
        if "$$" in raw_line:
            raise ValueError(
                f"Malformed data_end $$ delimiter at line {line_no} in $TABLE starting at line {title_line_no}"
            )
        if stripped.startswith(("$TABLE", "$GRAPHS", "$TEXT", "$SUMMARY", ":TEXT:")) or stripped.startswith("----"):
            raise ValueError(
                f"Unclosed data block in $TABLE starting at line {title_line_no}: unexpected boundary at line {line_no} before data_end $$"
            )
        if not stripped:
            raise ValueError(
                f"Blank line {line_no} inside data rows of $TABLE starting at line {title_line_no}"
            )
        tokens = stripped.split()
        if len(tokens) != expected_col_count:
            raise ValueError(
                f"Row width mismatch at line {line_no} in $TABLE starting at line {title_line_no}: "
                f"expected {expected_col_count} columns ({header_tokens}), got {len(tokens)} tokens ({tokens})"
            )
        data_rows.append({"line": line_no, "text": raw_line, "tokens": tokens})
        idx += 1

    if data_end_line is None:
        raise ValueError(
            f"Unclosed $TABLE starting at line {title_line_no}: missing data_end $$"
        )
    if not data_rows:
        raise ValueError(
            f"Empty data rows in $TABLE starting at line {title_line_no}"
        )

    table_block: dict[str, Any] = {
        "title": {"line": title_line_no, "text": title_line_text},
        "title_body": raw_title_body,
        "graph_declaration_lines": graph_declaration_lines,
        "header_lines": header_lines,
        "header_tokens": header_tokens,
        "double_dollar_roles": {
            "header_start_line": header_start_line,
            "header_end_line": header_end_line,
            "data_start_line": data_start_line,
            "data_end_line": data_end_line,
        },
        "data_line_range_inclusive": [
            data_rows[0]["line"],
            data_rows[-1]["line"],
        ],
        "row_count": len(data_rows),
        "column_count": expected_col_count,
        "rows": data_rows,
    }
    return table_block, idx


def _validate_graph_declaration_cycles(
    table_block: dict[str, Any], *, expected_cycle: int | None, context: str
) -> list[dict[str, Any]]:
    """Validate explicit ``Cycle <N>.`` labels on ``$GRAPHS`` and continuation lines."""
    title_line_no = table_block["title"]["line"]
    graph_cycles: list[dict[str, Any]] = []
    for g_entry in table_block["graph_declaration_lines"]:
        g_line = g_entry["line"]
        g_text = g_entry["text"]
        matches = list(_GRAPH_CYCLE_RE.finditer(g_text))
        residual = _GRAPH_CYCLE_RE.sub("", g_text)
        residual = _GRAPH_VS_CYCLE_RE.sub("", residual)
        if _GRAPH_ANY_CYCLE_WORD_RE.search(residual):
            raise ValueError(
                f"Malformed Cycle label in $GRAPHS declaration at line {g_line} "
                f"for {context} (table at line {title_line_no}): {g_text!r}"
            )
        for m in matches:
            cyc_tok = m.group(1)
            g_cycle = _parse_positive_int_token(
                cyc_tok,
                context=f"{context} $GRAPHS Cycle label (table at line {title_line_no})",
                line_no=g_line,
            )
            if expected_cycle is None:
                raise ValueError(
                    f"Unexpected explicit Cycle {g_cycle} in $GRAPHS declaration at line {g_line} "
                    f"for {context} (table at line {title_line_no})"
                )
            if g_cycle != expected_cycle:
                raise ValueError(
                    f"Conflicting $GRAPHS Cycle {g_cycle} at line {g_line} vs {context} "
                    f"table title Cycle {expected_cycle} at line {title_line_no}"
                )
            graph_cycles.append(
                {
                    "line": g_line,
                    "token": cyc_tok,
                    "cycle_number": g_cycle,
                }
            )
    return graph_cycles


def _classify_and_validate_table(table_block: dict[str, Any]) -> str:
    """Classify a parsed ``$TABLE:`` block by title and header tokens."""
    title_line_no = table_block["title"]["line"]
    title_body = table_block["title_body"]
    header_tokens = tuple(table_block["header_tokens"])

    rfactor_title_match = _RESLN_RFACTOR_TITLE_RE.match(title_body)
    fom_title_match = _RESLN_FOM_TITLE_RE.match(title_body)
    summary_title_match = _CYCLE_SUMMARY_TITLE_RE.match(title_body)

    looks_like_resln_rfactor_title = (
        "rfactor analysis" in title_body.lower()
        and "f distribution" in title_body.lower()
    )
    looks_like_cycle_summary_title = (
        "rfactor analysis" in title_body.lower()
        and "stats vs" in title_body.lower()
    )

    if (
        rfactor_title_match
        or looks_like_resln_rfactor_title
        or header_tokens == RESOLUTION_RFACTOR_HEADER_TOKENS
    ):
        if not rfactor_title_match:
            raise ValueError(
                f"Malformed resolution R-factor table title at line {title_line_no}: {title_body!r}"
            )
        cycle_token = rfactor_title_match.group(1)
        cycle_number = _parse_positive_int_token(
            cycle_token,
            context="resolution R-factor table cycle label",
            line_no=title_line_no,
        )
        if header_tokens != RESOLUTION_RFACTOR_HEADER_TOKENS:
            raise ValueError(
                f"Unexpected resolution R-factor table header at line {title_line_no}: "
                f"expected {list(RESOLUTION_RFACTOR_HEADER_TOKENS)}, got {list(header_tokens)}"
            )
        _validate_graph_declaration_cycles(
            table_block,
            expected_cycle=cycle_number,
            context="resolution R-factor",
        )
        table_block["table_kind"] = "resolution_rfactor"
        table_block["cycle_number"] = cycle_number
        return "resolution_rfactor"

    if (
        summary_title_match
        or looks_like_cycle_summary_title
        or header_tokens == CYCLE_SUMMARY_HEADER_TOKENS
    ):
        if not summary_title_match:
            raise ValueError(
                f"Malformed cycle-summary table title at line {title_line_no}: {title_body!r}"
            )
        if header_tokens != CYCLE_SUMMARY_HEADER_TOKENS:
            raise ValueError(
                f"Unexpected cycle-summary table header at line {title_line_no}: "
                f"expected {list(CYCLE_SUMMARY_HEADER_TOKENS)}, got {list(header_tokens)}"
            )
        _validate_graph_declaration_cycles(
            table_block,
            expected_cycle=None,
            context="cycle-summary",
        )
        table_block["table_kind"] = "cycle_summary"
        table_block["cycle_number"] = None
        return "cycle_summary"

    looks_like_resln_fom_title = (
        "fom(" in title_body.lower() or "delphi" in title_body.lower()
    )
    if (
        fom_title_match
        or looks_like_resln_fom_title
        or header_tokens == RESOLUTION_FOM_HEADER_TOKENS
    ):
        if not fom_title_match or header_tokens != RESOLUTION_FOM_HEADER_TOKENS:
            raise ValueError(
                f"Malformed FOM resolution table title/header at line {title_line_no}"
            )
        cycle_token = fom_title_match.group(1)
        cycle_number = _parse_positive_int_token(
            cycle_token,
            context="resolution FOM table cycle label",
            line_no=title_line_no,
        )
        _validate_graph_declaration_cycles(
            table_block,
            expected_cycle=cycle_number,
            context="resolution FOM",
        )
        prev_fom_s2: float | None = None
        for row in table_block["rows"]:
            row_line = row["line"]
            (
                s2_tok,
                nref_a_tok,
                fom_a_tok,
                nref_c_tok,
                fom_c_tok,
                nref_all_tok,
                fom_all_tok,
                sigmaa_tok,
            ) = row["tokens"]
            s2_val = _parse_finite_float_token(
                s2_tok,
                context="FOM table <4SSQ/LL>",
                line_no=row_line,
                nonnegative=True,
            )
            if prev_fom_s2 is not None and s2_val <= prev_fom_s2:
                raise ValueError(
                    f"Non-increasing FOM <4SSQ/LL> bin coordinate {s2_tok!r} at line {row_line}"
                )
            prev_fom_s2 = s2_val
            nref_a = _parse_nonnegative_int_token(
                nref_a_tok, context="FOM table NREFa", line_no=row_line
            )
            _parse_finite_float_token(
                fom_a_tok, context="FOM table FOMa", line_no=row_line
            )
            nref_c = _parse_nonnegative_int_token(
                nref_c_tok, context="FOM table NREFc", line_no=row_line
            )
            _parse_finite_float_token(
                fom_c_tok, context="FOM table FOMc", line_no=row_line
            )
            nref_all = _parse_nonnegative_int_token(
                nref_all_tok, context="FOM table NREFall", line_no=row_line
            )
            _parse_finite_float_token(
                fom_all_tok, context="FOM table FOMall", line_no=row_line
            )
            _parse_finite_float_token(
                sigmaa_tok, context="FOM table SigmaA_Fc1", line_no=row_line
            )
            if nref_all != nref_a + nref_c:
                raise ValueError(
                    f"FOM table row NREFall ({nref_all}) != NREFa ({nref_a}) + NREFc ({nref_c}) "
                    f"at line {row_line}"
                )
        table_block["table_kind"] = "resolution_fom"
        table_block["cycle_number"] = cycle_number
        return "resolution_fom"

    # Competing unrelated table: reject NaN/Inf/sentinel tokens, keep distinct from R tables
    for row in table_block["rows"]:
        row_line = row["line"]
        for col_name, tok in zip(header_tokens, row["tokens"]):
            _parse_finite_float_token(
                tok, context=f"table {title_body!r} column {col_name}", line_no=row_line
            )
    table_block["table_kind"] = "other"
    table_block["cycle_number"] = None
    return "other"


def _parse_resolution_rfactor_table(
    table_block: dict[str, Any], *, phase: str, summary_ncyc: int
) -> dict[str, Any]:
    """Validate and structure one per-bin resolution R-factor table."""
    bins: list[dict[str, Any]] = []
    compact_rows: list[list[Any]] = []
    nr_used_sum = 0
    nr_free_sum = 0
    rf_used_places: set[int] = set()
    rf_free_places: set[int] = set()
    prev_s2: float | None = None

    for ordinal, row in enumerate(table_block["rows"], start=1):
        line_no = row["line"]
        tokens = row["tokens"]
        (
            m_4ssq_ll_tok,
            nr_used_tok,
            pct_obs_tok,
            m_fo_used_tok,
            m_fc_used_tok,
            rf_used_tok,
            wr_used_tok,
            nr_free_tok,
            m_fo_free_tok,
            m_fc_free_tok,
            rf_free_tok,
            wr_free_tok,
        ) = tokens

        m_4ssq_ll = _parse_finite_float_token(
            m_4ssq_ll_tok,
            context="M(4SSQ/LL)",
            line_no=line_no,
            nonnegative=True,
        )
        if prev_s2 is not None and m_4ssq_ll <= prev_s2:
            raise ValueError(
                f"Non-increasing M(4SSQ/LL) bin coordinate {m_4ssq_ll_tok!r} at line {line_no}"
            )
        prev_s2 = m_4ssq_ll

        nr_used = _parse_nonnegative_int_token(
            nr_used_tok, context="NR_used", line_no=line_no
        )
        _, pct_obs_val, pct_obs_dp = _parse_percentage_token(
            pct_obs_tok, context="%_obs", line_no=line_no
        )
        _parse_finite_float_token(
            m_fo_used_tok, context="M(Fo_used)", line_no=line_no, nonnegative=True
        )
        _parse_finite_float_token(
            m_fc_used_tok, context="M(Fc_used)", line_no=line_no, nonnegative=True
        )
        _, rf_used_val, rf_used_dp = _parse_r_token(
            rf_used_tok, context="Rf_used", line_no=line_no
        )
        wr_used_val = _parse_finite_float_token(
            wr_used_tok,
            context="WR_used",
            line_no=line_no,
            nonnegative=True,
        )

        nr_free = _parse_nonnegative_int_token(
            nr_free_tok, context="NR_free", line_no=line_no
        )
        _parse_finite_float_token(
            m_fo_free_tok, context="M(Fo_free)", line_no=line_no, nonnegative=True
        )
        _parse_finite_float_token(
            m_fc_free_tok, context="M(Fc_free)", line_no=line_no, nonnegative=True
        )
        _, rf_free_val, rf_free_dp = _parse_r_token(
            rf_free_tok, context="Rf_free", line_no=line_no
        )
        wr_free_val = _parse_finite_float_token(
            wr_free_tok,
            context="WR_free",
            line_no=line_no,
            nonnegative=True,
        )

        nr_used_sum += nr_used
        nr_free_sum += nr_free
        rf_used_places.add(rf_used_dp)
        rf_free_places.add(rf_free_dp)

        bins.append(
            {
                "bin_ordinal": ordinal,
                "line": line_no,
                "text": row["text"],
                "tokens": list(tokens),
                "m_4ssq_ll_token": m_4ssq_ll_tok,
                "m_4ssq_ll": m_4ssq_ll,
                "nr_used_token": nr_used_tok,
                "nr_used": nr_used,
                "pct_obs_token": pct_obs_tok,
                "pct_obs": pct_obs_val,
                "pct_obs_decimal_places": pct_obs_dp,
                "m_fo_used_token": m_fo_used_tok,
                "m_fc_used_token": m_fc_used_tok,
                "rf_used_token": rf_used_tok,
                "rf_used": rf_used_val,
                "rf_used_decimal_places": rf_used_dp,
                "wr_used_token": wr_used_tok,
                "wr_used": wr_used_val,
                "nr_free_token": nr_free_tok,
                "nr_free": nr_free,
                "m_fo_free_token": m_fo_free_tok,
                "m_fc_free_token": m_fc_free_tok,
                "rf_free_token": rf_free_tok,
                "rf_free": rf_free_val,
                "rf_free_decimal_places": rf_free_dp,
                "wr_free_token": wr_free_tok,
                "wr_free": wr_free_val,
            }
        )
        compact_rows.append(
            [
                ordinal,
                line_no,
                m_4ssq_ll_tok,
                nr_used,
                nr_free,
                rf_used_tok,
                rf_free_tok,
            ]
        )

    if nr_used_sum <= 0:
        raise ValueError(
            f"Resolution R-factor table at line {table_block['title']['line']} has zero total NR_used"
        )
    if nr_free_sum <= 0:
        raise ValueError(
            f"Resolution R-factor table at line {table_block['title']['line']} has zero total NR_free"
        )

    return {
        "phase": phase,
        "detailed_cycle": table_block["cycle_number"],
        "summary_ncyc": summary_ncyc,
        "title": dict(table_block["title"]),
        "graph_declaration_lines": list(table_block["graph_declaration_lines"]),
        "header_lines": list(table_block["header_lines"]),
        "header_tokens": list(table_block["header_tokens"]),
        "double_dollar_roles": dict(table_block["double_dollar_roles"]),
        "data_line_range_inclusive": list(table_block["data_line_range_inclusive"]),
        "bin_count": len(bins),
        "nr_used_sum": nr_used_sum,
        "nr_free_sum": nr_free_sum,
        "combined_reported_count": nr_used_sum + nr_free_sum,
        "rf_used_printed_decimal_places": (
            next(iter(rf_used_places)) if len(rf_used_places) == 1 else sorted(rf_used_places)
        ),
        "rf_free_printed_decimal_places": (
            next(iter(rf_free_places)) if len(rf_free_places) == 1 else sorted(rf_free_places)
        ),
        "bins": bins,
        "rows": compact_rows,
    }


def _parse_cycle_summary_table(table_block: dict[str, Any]) -> dict[str, Any]:
    """Validate and structure ``$TABLE: Rfactor analysis, stats vs cycle :``."""
    structured_rows: list[dict[str, Any]] = []
    rfact_places: set[int] = set()
    rfree_places: set[int] = set()

    for expected_ncyc, row in enumerate(table_block["rows"]):
        line_no = row["line"]
        tokens = row["tokens"]
        (
            ncyc_tok,
            rfact_tok,
            rfree_tok,
            fom_tok,
            ll_tok,
            llfree_tok,
            rmsbond_tok,
            zbond_tok,
            rmsangl_tok,
            zangl_tok,
            rmschiral_tok,
        ) = tokens

        ncyc = _parse_nonnegative_int_token(
            ncyc_tok, context="summary Ncyc", line_no=line_no
        )
        if ncyc != expected_ncyc:
            raise ValueError(
                f"Non-contiguous or out-of-order summary Ncyc at line {line_no}: "
                f"expected {expected_ncyc}, got {ncyc}"
            )

        rfact_dec, rfact_val, rfact_dp = _parse_r_token(
            rfact_tok, context=f"summary Rfact (Ncyc {ncyc})", line_no=line_no
        )
        rfree_dec, rfree_val, rfree_dp = _parse_r_token(
            rfree_tok, context=f"summary Rfree (Ncyc {ncyc})", line_no=line_no
        )
        fom_val = _parse_finite_float_token(
            fom_tok,
            context=f"summary FOM (Ncyc {ncyc})",
            line_no=line_no,
            nonnegative=True,
        )
        for col_label, col_tok in (
            ("-LL", ll_tok),
            ("-LLfree", llfree_tok),
            ("rmsBOND", rmsbond_tok),
            ("zBOND", zbond_tok),
            ("rmsANGL", rmsangl_tok),
            ("zANGL", zangl_tok),
            ("rmsCHIRAL", rmschiral_tok),
        ):
            _parse_finite_float_token(
                col_tok,
                context=f"summary {col_label} (Ncyc {ncyc})",
                line_no=line_no,
            )

        rfact_places.add(rfact_dp)
        rfree_places.add(rfree_dp)

        structured_rows.append(
            {
                "ncyc": ncyc,
                "ncyc_token": ncyc_tok,
                "line": line_no,
                "text": row["text"],
                "tokens": list(tokens),
                "rfact_token": rfact_tok,
                "rfact": rfact_val,
                "rfact_decimal": rfact_dec,
                "rfact_decimal_places": rfact_dp,
                "rfree_token": rfree_tok,
                "rfree": rfree_val,
                "rfree_decimal": rfree_dec,
                "rfree_decimal_places": rfree_dp,
                "fom_token": fom_tok,
                "fom": fom_val,
                "ll_token": ll_tok,
                "llfree_token": llfree_tok,
                "rmsbond_token": rmsbond_tok,
                "zbond_token": zbond_tok,
                "rmsangl_token": rmsangl_tok,
                "zangl_token": zangl_tok,
                "rmschiral_token": rmschiral_tok,
            }
        )

    return {
        "title": dict(table_block["title"]),
        "graph_declaration_lines": list(table_block["graph_declaration_lines"]),
        "header_lines": list(table_block["header_lines"]),
        "header_tokens": list(table_block["header_tokens"]),
        "double_dollar_roles": dict(table_block["double_dollar_roles"]),
        "data_line_range_inclusive": list(table_block["data_line_range_inclusive"]),
        "row_count": len(structured_rows),
        "summary_cycle_min": structured_rows[0]["ncyc"],
        "summary_cycle_max": structured_rows[-1]["ncyc"],
        "rfact_printed_decimal_places": (
            next(iter(rfact_places)) if len(rfact_places) == 1 else sorted(rfact_places)
        ),
        "rfree_printed_decimal_places": (
            next(iter(rfree_places)) if len(rfree_places) == 1 else sorted(rfree_places)
        ),
        "rows": structured_rows,
    }


def _parse_text_block(
    lines: list[str], start_idx: int
) -> tuple[dict[str, Any], int]:
    """Parse one ``$TEXT:<name>: $$ <subtitle> $$`` block closed by ``$$``."""
    title_line_no = start_idx + 1
    title_line_text = lines[start_idx]
    match = _TEXT_START_RE.match(title_line_text)
    if not match or title_line_text.count("$$") != 2:
        raise ValueError(
            f"Malformed $TEXT directive at line {title_line_no}: {title_line_text!r}"
        )
    text_name = match.group(1).strip()
    subtitle = match.group(2).strip()

    idx = start_idx + 1
    body_lines: list[dict[str, Any]] = []
    end_line_no: int | None = None
    end_line_text: str | None = None

    while idx < len(lines):
        line_no = idx + 1
        raw_line = lines[idx]
        stripped = raw_line.strip()
        if raw_line.count("$$") > 1:
            raise ValueError(
                f"Multiple $$ delimiters on line {line_no} inside $TEXT:{text_name}:"
            )
        if stripped == "$$":
            end_line_no = line_no
            end_line_text = raw_line
            idx += 1
            break
        if "$$" in raw_line:
            raise ValueError(
                f"Malformed closing $$ at line {line_no} inside $TEXT:{text_name}:"
            )
        if stripped.startswith(("$TABLE", "$GRAPHS", "$TEXT", "$SUMMARY", ":TEXT:")):
            raise ValueError(
                f"Unclosed $TEXT:{text_name}: starting at line {title_line_no} before line {line_no}"
            )
        body_lines.append({"line": line_no, "text": raw_line})
        idx += 1

    if end_line_no is None or end_line_text is None:
        raise ValueError(
            f"Unclosed $TEXT:{text_name}: starting at line {title_line_no}: missing closing $$"
        )

    return (
        {
            "name": text_name,
            "subtitle": subtitle,
            "title": {"line": title_line_no, "text": title_line_text},
            "body_lines": body_lines,
            "end_delimiter": {"line": end_line_no, "text": end_line_text},
        },
        idx,
    )


_KNOWN_FINAL_RESULTS_LABELS: tuple[str, ...] = (
    "R factor",
    "R free",
    "Rms BondLength",
    "Rms BondAngle",
    "Rms ChirVolume",
)


def _parse_final_results_block(text_block: dict[str, Any]) -> dict[str, Any]:
    """Validate and structure ``$TEXT:Result: $$ Final results $$``."""
    title_line_no = text_block["title"]["line"]
    if text_block["subtitle"] != "Final results":
        raise ValueError(
            f"Unexpected $TEXT:Result: subtitle at line {title_line_no}: {text_block['subtitle']!r}"
        )
    non_empty_lines = [
        entry for entry in text_block["body_lines"] if entry["text"].strip()
    ]
    if len(non_empty_lines) < 3:
        raise ValueError(
            f"Truncated Final results block starting at line {title_line_no}"
        )

    header_entry = non_empty_lines[0]
    header_tokens = header_entry["text"].split()
    if header_tokens != ["Initial", "Final"]:
        raise ValueError(
            f"Unexpected Final results header at line {header_entry['line']}: "
            f"expected ['Initial', 'Final'], got {header_tokens}"
        )

    parsed_rows: list[dict[str, Any]] = []
    by_label: dict[str, dict[str, Any]] = {}
    for entry in non_empty_lines[1:]:
        line_no = entry["line"]
        tokens = entry["text"].split()
        if not tokens:
            continue

        matched_known_label: str | None = None
        value_tokens: list[str] = []
        for known_label in _KNOWN_FINAL_RESULTS_LABELS:
            known_parts = known_label.split()
            n_parts = len(known_parts)
            if len(tokens) >= n_parts and [t.lower() for t in tokens[:n_parts]] == [
                k.lower() for k in known_parts
            ]:
                if tokens[:n_parts] != known_parts:
                    raise ValueError(
                        f"Malformed label casing in Final results block at line {line_no}: {entry['text']!r}"
                    )
                matched_known_label = known_label
                value_tokens = tokens[n_parts:]
                break

        if matched_known_label is not None:
            label = matched_known_label
        else:
            first_val_idx: int | None = None
            for idx_tok, tok in enumerate(tokens):
                if _looks_like_numeric_or_invalid_value_token(tok):
                    first_val_idx = idx_tok
                    break
            if first_val_idx is None or first_val_idx == 0:
                raise ValueError(
                    f"Truncated or malformed row in Final results block at line {line_no}: {entry['text']!r}"
                )
            label_tokens = tokens[:first_val_idx]
            value_tokens = tokens[first_val_idx:]
            label = " ".join(label_tokens)
            if "r factor" in label.lower() or "r free" in label.lower():
                raise ValueError(
                    f"Unrecognized R label {label!r} in Final results block at line {line_no}"
                )

        if len(value_tokens) != 2:
            raise ValueError(
                f"Expected exactly 2 values (Initial, Final) for {label!r} in Final results block "
                f"at line {line_no}, got {len(value_tokens)}: {entry['text']!r}"
            )
        initial_tok, final_tok = value_tokens
        if label in by_label:
            raise ValueError(
                f"Duplicate {label!r} row in Final results block at line {line_no}"
            )
        row_record: dict[str, Any] = {
            "line": line_no,
            "text": entry["text"],
            "label": label,
            "initial_token": initial_tok,
            "final_token": final_tok,
        }
        if label in {"R factor", "R free"}:
            init_dec, init_val, init_dp = _parse_r_token(
                initial_tok, context=f"Final results {label} Initial", line_no=line_no
            )
            fin_dec, fin_val, fin_dp = _parse_r_token(
                final_tok, context=f"Final results {label} Final", line_no=line_no
            )
            row_record.update(
                initial_decimal=init_dec,
                initial_value=init_val,
                initial_decimal_places=init_dp,
                final_decimal=fin_dec,
                final_value=fin_val,
                final_decimal_places=fin_dp,
            )
        else:
            init_val = _parse_finite_float_token(
                initial_tok,
                context=f"Final results {label} Initial",
                line_no=line_no,
                nonnegative=(label in _KNOWN_FINAL_RESULTS_LABELS),
            )
            fin_val = _parse_finite_float_token(
                final_tok,
                context=f"Final results {label} Final",
                line_no=line_no,
                nonnegative=(label in _KNOWN_FINAL_RESULTS_LABELS),
            )
            row_record.update(
                initial_value=init_val,
                final_value=fin_val,
            )
        parsed_rows.append(row_record)
        by_label[label] = row_record

    if "R factor" not in by_label or "R free" not in by_label:
        raise ValueError(
            f"Final results block starting at line {title_line_no} is missing 'R factor' or 'R free'"
        )

    rfactor_row = by_label["R factor"]
    rfree_row = by_label["R free"]
    return {
        "title": dict(text_block["title"]),
        "header": {
            "line": header_entry["line"],
            "text": header_entry["text"],
            "tokens": header_tokens,
        },
        "rows": [
            {
                "line": r["line"],
                "text": r["text"],
                "label": r["label"],
                "initial_token": r["initial_token"],
                "final_token": r["final_token"],
            }
            for r in parsed_rows
        ],
        "end_delimiter": dict(text_block["end_delimiter"]),
        "r_factor_line": rfactor_row["line"],
        "r_free_line": rfree_row["line"],
        "Rfactor_initial_token": rfactor_row["initial_token"],
        "Rfactor_final_token": rfactor_row["final_token"],
        "Rfree_initial_token": rfree_row["initial_token"],
        "Rfree_final_token": rfree_row["final_token"],
        "Rfactor_printed_decimal_places": rfactor_row["final_decimal_places"],
        "Rfree_printed_decimal_places": rfree_row["final_decimal_places"],
        "rfactor_initial_token": rfactor_row["initial_token"],
        "rfactor_initial": rfactor_row["initial_value"],
        "rfactor_initial_decimal": rfactor_row["initial_decimal"],
        "rfactor_initial_decimal_places": rfactor_row["initial_decimal_places"],
        "rfactor_final_token": rfactor_row["final_token"],
        "rfactor_final": rfactor_row["final_value"],
        "rfactor_final_decimal": rfactor_row["final_decimal"],
        "rfactor_final_decimal_places": rfactor_row["final_decimal_places"],
        "rfree_initial_token": rfree_row["initial_token"],
        "rfree_initial": rfree_row["initial_value"],
        "rfree_initial_decimal": rfree_row["initial_decimal"],
        "rfree_initial_decimal_places": rfree_row["initial_decimal_places"],
        "rfree_final_token": rfree_row["final_token"],
        "rfree_final": rfree_row["final_value"],
        "rfree_final_decimal": rfree_row["final_decimal"],
        "rfree_final_decimal_places": rfree_row["final_decimal_places"],
    }


_KNOWN_DETAIL_LABELS: frozenset[str] = frozenset(
    {
        "Resolution limits",
        "Number of used reflections",
        "Percentage observed",
        "Percentage of free reflections",
        "Overall R factor",
        "Free R factor",
        "Overall weighted R factor",
        "Free weighted R factor",
        "Overall weighted R2 factor",
        "Free weighted R2 factor",
        "Overall correlation coefficient",
        "Free correlation coefficient",
        "Cruickshanks DPI for coordinate error",
        "DPI based on free R factor",
        "Overall figure of merit",
        "ML based su of positional parameters",
        "ML based su of thermal parameters",
    }
)


def _finalize_detail_group(
    entries: list[tuple[int, str, str, str]]
) -> dict[str, Any] | None:
    """Validate one contiguous group of detailed cycle key=value lines."""
    if not entries:
        return None
    labels_present = {label for _, _, label, _ in entries}

    seen: dict[str, tuple[int, str, str]] = {}
    for line_no, raw_line, label, rhs in entries:
        if label in seen:
            raise ValueError(
                f"Duplicate {label!r} in detailed cycle block at line {line_no}"
            )
        seen[label] = (line_no, raw_line, rhs)

    if "Overall R factor" not in seen or "Free R factor" not in seen:
        first_line = entries[0][0]
        raise ValueError(
            f"Detailed cycle block starting at line {first_line} is missing paired "
            f"unweighted 'Overall R factor' / 'Free R factor' (found {sorted(labels_present)})"
        )

    overall_line, overall_raw, overall_rhs = seen["Overall R factor"]
    free_line, free_raw, free_rhs = seen["Free R factor"]
    if overall_line >= free_line:
        raise ValueError(
            f"Detailed 'Free R factor' (line {free_line}) precedes 'Overall R factor' (line {overall_line})"
        )

    overall_tokens = overall_rhs.split()
    free_tokens = free_rhs.split()
    if len(overall_tokens) != 1:
        raise ValueError(
            f"Expected single R token for 'Overall R factor' at line {overall_line}, got {overall_rhs!r}"
        )
    if len(free_tokens) != 1:
        raise ValueError(
            f"Expected single R token for 'Free R factor' at line {free_line}, got {free_rhs!r}"
        )

    overall_dec, overall_val, overall_dp = _parse_r_token(
        overall_tokens[0], context="Overall R factor", line_no=overall_line
    )
    free_dec, free_val, free_dp = _parse_r_token(
        free_tokens[0], context="Free R factor", line_no=free_line
    )

    detail: dict[str, Any] = {
        "cgmat_cycle_line": None,
        "cgmat_cycle_token": None,
        "cgmat_cycle_number": None,
        "overall_r_line": overall_line,
        "overall_r_text": overall_raw,
        "overall_r_token": overall_tokens[0],
        "overall_r": overall_val,
        "overall_r_decimal": overall_dec,
        "overall_r_decimal_places": overall_dp,
        "free_r_line": free_line,
        "free_r_text": free_raw,
        "free_r_token": free_tokens[0],
        "free_r": free_val,
        "free_r_decimal": free_dec,
        "free_r_decimal_places": free_dp,
        "overall_weighted_r_line": None,
        "overall_weighted_r_token": None,
        "overall_weighted_r": None,
        "free_weighted_r_line": None,
        "free_weighted_r_token": None,
        "free_weighted_r": None,
        "overall_weighted_r2_line": None,
        "overall_weighted_r2_token": None,
        "overall_weighted_r2": None,
        "free_weighted_r2_line": None,
        "free_weighted_r2_token": None,
        "free_weighted_r2": None,
        "overall_fom_line": None,
        "overall_fom_token": None,
        "overall_fom": None,
        "overall_correlation_coefficient_line": None,
        "overall_correlation_coefficient_token": None,
        "overall_correlation_coefficient": None,
        "free_correlation_coefficient_line": None,
        "free_correlation_coefficient_token": None,
        "free_correlation_coefficient": None,
        "cruickshanks_dpi_line": None,
        "cruickshanks_dpi_token": None,
        "cruickshanks_dpi": None,
        "dpi_free_r_line": None,
        "dpi_free_r_token": None,
        "dpi_free_r": None,
        "ml_su_positional_line": None,
        "ml_su_positional_token": None,
        "ml_su_positional": None,
        "ml_su_thermal_line": None,
        "ml_su_thermal_token": None,
        "ml_su_thermal": None,
        "number_of_used_reflections_line": None,
        "number_of_used_reflections_token": None,
        "number_of_used_reflections": None,
        "resolution_limits_line": None,
        "resolution_limits_tokens": None,
        "percentage_observed_line": None,
        "percentage_observed_token": None,
        "percentage_observed": None,
        "percentage_observed_decimal_places": None,
        "percentage_free_line": None,
        "percentage_free_token": None,
        "percentage_free": None,
        "percentage_free_decimal_places": None,
        "endpoint_lines": [
            {"line": line_no, "text": raw_line}
            for line_no, raw_line, label, _ in entries
            if label
            in {
                "Resolution limits",
                "Number of used reflections",
                "Percentage observed",
                "Percentage of free reflections",
                "Overall R factor",
                "Free R factor",
            }
        ],
        "distinct_weighted_metric_lines": [
            {"line": line_no, "text": raw_line}
            for line_no, raw_line, label, _ in entries
            if label
            in {
                "Overall weighted R factor",
                "Free weighted R factor",
                "Overall weighted R2 factor",
                "Free weighted R2 factor",
            }
        ],
    }

    for metric_label, line_key, tok_key, val_key in (
        (
            "Overall weighted R factor",
            "overall_weighted_r_line",
            "overall_weighted_r_token",
            "overall_weighted_r",
        ),
        (
            "Free weighted R factor",
            "free_weighted_r_line",
            "free_weighted_r_token",
            "free_weighted_r",
        ),
        (
            "Overall weighted R2 factor",
            "overall_weighted_r2_line",
            "overall_weighted_r2_token",
            "overall_weighted_r2",
        ),
        (
            "Free weighted R2 factor",
            "free_weighted_r2_line",
            "free_weighted_r2_token",
            "free_weighted_r2",
        ),
        (
            "Overall figure of merit",
            "overall_fom_line",
            "overall_fom_token",
            "overall_fom",
        ),
    ):
        if metric_label in seen:
            m_line, _, m_rhs = seen[metric_label]
            m_toks = m_rhs.split()
            if len(m_toks) != 1:
                raise ValueError(
                    f"Expected single token for {metric_label!r} at line {m_line}, got {m_rhs!r}"
                )
            m_val = _parse_finite_float_token(
                m_toks[0],
                context=metric_label,
                line_no=m_line,
                nonnegative=True,
            )
            detail[line_key] = m_line
            detail[tok_key] = m_toks[0]
            detail[val_key] = m_val

    for opt_label, line_key, tok_key, val_key in (
        (
            "Overall correlation coefficient",
            "overall_correlation_coefficient_line",
            "overall_correlation_coefficient_token",
            "overall_correlation_coefficient",
        ),
        (
            "Free correlation coefficient",
            "free_correlation_coefficient_line",
            "free_correlation_coefficient_token",
            "free_correlation_coefficient",
        ),
        (
            "Cruickshanks DPI for coordinate error",
            "cruickshanks_dpi_line",
            "cruickshanks_dpi_token",
            "cruickshanks_dpi",
        ),
        (
            "DPI based on free R factor",
            "dpi_free_r_line",
            "dpi_free_r_token",
            "dpi_free_r",
        ),
        (
            "ML based su of positional parameters",
            "ml_su_positional_line",
            "ml_su_positional_token",
            "ml_su_positional",
        ),
        (
            "ML based su of thermal parameters",
            "ml_su_thermal_line",
            "ml_su_thermal_token",
            "ml_su_thermal",
        ),
    ):
        if opt_label in seen:
            o_line, _, o_rhs = seen[opt_label]
            o_toks = o_rhs.split()
            if len(o_toks) != 1:
                raise ValueError(
                    f"Expected single scalar value for {opt_label!r} at line {o_line}, got {o_rhs!r}"
                )
            o_val = _parse_finite_float_token(
                o_toks[0],
                context=opt_label,
                line_no=o_line,
            )
            detail[line_key] = o_line
            detail[tok_key] = o_toks[0]
            detail[val_key] = o_val

    if "Number of used reflections" in seen:
        u_line, _, u_rhs = seen["Number of used reflections"]
        u_toks = u_rhs.split()
        if len(u_toks) != 1:
            raise ValueError(
                f"Expected single integer for 'Number of used reflections' at line {u_line}"
            )
        u_val = _parse_positive_int_token(
            u_toks[0], context="Number of used reflections", line_no=u_line
        )
        detail["number_of_used_reflections_line"] = u_line
        detail["number_of_used_reflections_token"] = u_toks[0]
        detail["number_of_used_reflections"] = u_val

    if "Resolution limits" in seen:
        r_line, _, r_rhs = seen["Resolution limits"]
        r_toks = r_rhs.split()
        if len(r_toks) != 2:
            raise ValueError(
                f"Expected 2 resolution limits at line {r_line}, got {r_rhs!r}"
            )
        for tok in r_toks:
            _parse_finite_float_token(
                tok, context="Resolution limits", line_no=r_line, nonnegative=True
            )
        detail["resolution_limits_line"] = r_line
        detail["resolution_limits_tokens"] = r_toks

    if "Percentage observed" in seen:
        p_line, _, p_rhs = seen["Percentage observed"]
        p_toks = p_rhs.split()
        if len(p_toks) != 1:
            raise ValueError(
                f"Expected 1 value for 'Percentage observed' at line {p_line}"
            )
        _, p_val, p_dp = _parse_percentage_token(
            p_toks[0], context="Percentage observed", line_no=p_line
        )
        detail["percentage_observed_line"] = p_line
        detail["percentage_observed_token"] = p_toks[0]
        detail["percentage_observed"] = p_val
        detail["percentage_observed_decimal_places"] = p_dp

    if "Percentage of free reflections" in seen:
        pf_line, _, pf_rhs = seen["Percentage of free reflections"]
        pf_toks = pf_rhs.split()
        if len(pf_toks) != 1:
            raise ValueError(
                f"Expected 1 value for 'Percentage of free reflections' at line {pf_line}"
            )
        _, pf_val, pf_dp = _parse_percentage_token(
            pf_toks[0],
            context="Percentage of free reflections",
            line_no=pf_line,
        )
        detail["percentage_free_line"] = pf_line
        detail["percentage_free_token"] = pf_toks[0]
        detail["percentage_free"] = pf_val
        detail["percentage_free_decimal_places"] = pf_dp

    return detail


def _reconcile_r_pair(
    *,
    cycle_label: str,
    detail_overall_tok: str,
    detail_overall_dec: Decimal,
    detail_overall_line: int,
    detail_free_tok: str,
    detail_free_dec: Decimal,
    detail_free_line: int,
    summary_rfact_tok: str,
    summary_rfact_dec: Decimal,
    summary_rfree_tok: str,
    summary_rfree_dec: Decimal,
    summary_line: int,
    final_results_rfactor_tok: str | None = None,
    final_results_rfactor_dec: Decimal | None = None,
    final_results_rfactor_line: int | None = None,
    final_results_rfree_tok: str | None = None,
    final_results_rfree_dec: Decimal | None = None,
    final_results_rfree_line: int | None = None,
) -> None:
    """Require exact Decimal value agreement across reporting locations for a cycle."""
    if detail_overall_dec != summary_rfact_dec:
        raise ValueError(
            f"Conflicting R-work for {cycle_label}: detailed Overall R factor "
            f"{detail_overall_tok!r} (line {detail_overall_line}) != cycle summary Rfact "
            f"{summary_rfact_tok!r} (line {summary_line})"
        )
    if detail_free_dec != summary_rfree_dec:
        raise ValueError(
            f"Conflicting R-free for {cycle_label}: detailed Free R factor "
            f"{detail_free_tok!r} (line {detail_free_line}) != cycle summary Rfree "
            f"{summary_rfree_tok!r} (line {summary_line})"
        )
    if final_results_rfactor_tok is not None and final_results_rfactor_dec is not None:
        if final_results_rfactor_dec != summary_rfact_dec:
            raise ValueError(
                f"Conflicting R-work for {cycle_label}: Final results R factor "
                f"{final_results_rfactor_tok!r} (line {final_results_rfactor_line}) != "
                f"cycle summary Rfact {summary_rfact_tok!r} (line {summary_line})"
            )
    if final_results_rfree_tok is not None and final_results_rfree_dec is not None:
        if final_results_rfree_dec != summary_rfree_dec:
            raise ValueError(
                f"Conflicting R-free for {cycle_label}: Final results R free "
                f"{final_results_rfree_tok!r} (line {final_results_rfree_line}) != "
                f"cycle summary Rfree {summary_rfree_tok!r} (line {summary_line})"
            )


def parse_refmac_log(text: str) -> dict[str, Any]:
    """Parse and reconcile a native REFMAC5 log string.

    Parameters
    ----------
    text:
        Complete REFMAC5 log content as a string.

    Returns
    -------
    dict
        Structured dictionary containing parsed ``table_blocks``,
        ``cycle_summary``, ``detailed_cycles``, ``cycle_r_values``,
        ``resolution_bin_values``, ``initial_resolution_bins``,
        ``final_resolution_bins``, ``endpoint_detail``, ``final_results_block``,
        ``reconciled_initial_cycle``, ``reconciled_final_cycle``, and
        ``consistency_checks``.
    """
    if not isinstance(text, str) or not text.strip():
        raise ValueError("REFMAC log text must be a non-empty string")

    lines = text.splitlines()
    total_lines = len(lines)

    raw_tables: list[dict[str, Any]] = []
    text_blocks: list[dict[str, Any]] = []
    detailed_cycles: list[dict[str, Any]] = []
    current_detail_entries: list[tuple[int, str, str, str]] = []
    cgmat_markers_raw: list[dict[str, Any]] = []

    reported_suite: str | None = None
    reported_refmac_version: str | None = None
    reported_run_date_token: str | None = None
    data_ncyc_values: list[tuple[int, int]] = []
    refinement_cycles_values: list[tuple[int, int]] = []

    def _flush_detail_group() -> None:
        nonlocal current_detail_entries
        if current_detail_entries:
            finalized = _finalize_detail_group(current_detail_entries)
            current_detail_entries = []
            if finalized is not None:
                detailed_cycles.append(finalized)

    idx = 0
    while idx < total_lines:
        line_no = idx + 1
        raw_line = lines[idx]
        stripped = raw_line.strip()

        banner_match = _BANNER_VERSION_RE.search(raw_line)
        if banner_match and reported_refmac_version is None:
            reported_suite = banner_match.group(1)
            reported_refmac_version = banner_match.group(2)

        date_match = _RUN_DATE_RE.search(raw_line)
        if date_match and reported_run_date_token is None:
            reported_run_date_token = date_match.group(1)

        ncyc_match = _DATA_NCYC_RE.match(raw_line)
        if ncyc_match:
            if ncyc_match.group(2):
                raise ValueError(
                    f"Unexpected trailing tokens on NCYC line {line_no}: {raw_line!r}"
                )
            ncyc_val = _parse_nonnegative_int_token(
                ncyc_match.group(1), context="Data line--- NCYC", line_no=line_no
            )
            data_ncyc_values.append((line_no, ncyc_val))

        ref_cyc_match = _REFINEMENT_CYCLES_RE.match(raw_line)
        if ref_cyc_match:
            if ref_cyc_match.group(2):
                raise ValueError(
                    f"Unexpected trailing tokens on Refinement cycles line {line_no}: {raw_line!r}"
                )
            ref_cyc_val = _parse_nonnegative_int_token(
                ref_cyc_match.group(1), context="Refinement cycles", line_no=line_no
            )
            refinement_cycles_values.append((line_no, ref_cyc_val))

        if stripped.startswith("$TABLE"):
            _flush_detail_group()
            table_block, idx = _parse_table_block(lines, idx)
            _classify_and_validate_table(table_block)
            table_block["preceding_detailed_cycle_count"] = len(detailed_cycles)
            raw_tables.append(table_block)
            continue

        if stripped.startswith("$TEXT"):
            _flush_detail_group()
            text_block, idx = _parse_text_block(lines, idx)
            text_block["preceding_detailed_cycle_count"] = len(detailed_cycles)
            text_blocks.append(text_block)
            continue

        if _SUMMARY_DIRECTIVE_RE.match(raw_line) or _TEXT_REF_DIRECTIVE_RE.match(raw_line):
            _flush_detail_group()
            idx += 1
            continue

        if "$$" in raw_line or stripped.startswith(("$GRAPHS", "$SUMMARY", ":TEXT:")):
            raise ValueError(
                f"Stray or malformed loggraph delimiter/directive at line {line_no}: {raw_line!r}"
            )

        if not stripped or stripped.startswith("----"):
            _flush_detail_group()
            idx += 1
            continue

        if "=" in raw_line:
            lhs, _, rhs = raw_line.partition("=")
            label = " ".join(lhs.strip().split())
            if label.lower() == "cgmat cycle number":
                if label != "CGMAT cycle number":
                    raise ValueError(
                        f"Malformed CGMAT cycle marker label {label!r} at line {line_no}"
                    )
                _flush_detail_group()
                rhs_tokens = rhs.split()
                if len(rhs_tokens) != 1:
                    raise ValueError(
                        f"Expected single integer token for 'CGMAT cycle number' at line {line_no}, got {rhs!r}"
                    )
                cgmat_num = _parse_positive_int_token(
                    rhs_tokens[0], context="CGMAT cycle number", line_no=line_no
                )
                cgmat_markers_raw.append(
                    {
                        "line": line_no,
                        "text": raw_line,
                        "token": rhs_tokens[0],
                        "cycle_number": cgmat_num,
                        "preceding_detailed_cycle_count": len(detailed_cycles),
                    }
                )
                idx += 1
                continue
            if label in _KNOWN_DETAIL_LABELS:
                current_detail_entries.append((line_no, raw_line, label, rhs.strip()))
                idx += 1
                continue
            if label.lower() in {k.lower() for k in _KNOWN_DETAIL_LABELS}:
                raise ValueError(
                    f"Malformed detail label {label!r} at line {line_no}"
                )
            if "r factor" in label.lower() or "r2 factor" in label.lower():
                raise ValueError(
                    f"Unrecognized R-factor detail label {label!r} at line {line_no}"
                )

        _flush_detail_group()
        idx += 1

    _flush_detail_group()

    # Validate NCYC declarations if present
    requested_ncyc: int | None = None
    for src_line, val in data_ncyc_values + refinement_cycles_values:
        if requested_ncyc is None:
            requested_ncyc = val
        elif val != requested_ncyc:
            raise ValueError(
                f"Contradictory requested NCYC count {val} at line {src_line} vs {requested_ncyc}"
            )

    # Locate required cycle_summary table
    cycle_summary_blocks = [
        t for t in raw_tables if t["table_kind"] == "cycle_summary"
    ]
    if not cycle_summary_blocks:
        raise ValueError(
            "Missing required '$TABLE: Rfactor analysis, stats vs cycle :' block"
        )
    if len(cycle_summary_blocks) > 1:
        raise ValueError(
            f"Ambiguous REFMAC log: found {len(cycle_summary_blocks)} cycle-summary tables"
        )
    cycle_summary_raw = cycle_summary_blocks[0]
    cycle_summary = _parse_cycle_summary_table(cycle_summary_raw)
    summary_rows = cycle_summary["rows"]
    num_cycles = len(summary_rows)

    if requested_ncyc is not None and cycle_summary["summary_cycle_max"] != requested_ncyc:
        raise ValueError(
            f"Cycle summary max Ncyc ({cycle_summary['summary_cycle_max']}) contradicts "
            f"declared NCYC ({requested_ncyc})"
        )

    # Validate detailed cycles count and ordering relative to cycle_summary
    if len(detailed_cycles) != num_cycles:
        raise ValueError(
            f"Cycle count mismatch: found {len(detailed_cycles)} detailed Overall/Free R pairs "
            f"but {num_cycles} cycle-summary rows"
        )
    if cycle_summary_raw["preceding_detailed_cycle_count"] != num_cycles:
        raise ValueError(
            "Ambiguous cycle ordering: detailed Overall/Free R pairs appear after the cycle-summary table"
        )

    # Validate and associate optional CGMAT cycle number markers when present
    cgmat_cycle_markers: list[dict[str, Any]] = []
    prev_cgmat_cycle: int | None = None
    seen_cgmat_detail_indices: set[int] = set()
    for marker in cgmat_markers_raw:
        m_line = marker["line"]
        m_cyc = marker["cycle_number"]
        prec_detail = marker["preceding_detailed_cycle_count"]
        if prev_cgmat_cycle is not None and m_cyc <= prev_cgmat_cycle:
            raise ValueError(
                f"Non-increasing or duplicate CGMAT cycle number {m_cyc} at line {m_line} "
                f"after CGMAT cycle number {prev_cgmat_cycle}"
            )
        if prec_detail in seen_cgmat_detail_indices:
            raise ValueError(
                f"Multiple CGMAT cycle number markers before detailed cycle {prec_detail + 1} (at line {m_line})"
            )
        if prec_detail >= num_cycles:
            raise ValueError(
                f"CGMAT cycle number {m_cyc} at line {m_line} appears after all {num_cycles} detailed cycles"
            )
        expected_detailed_cycle = prec_detail + 1
        if m_cyc != expected_detailed_cycle:
            raise ValueError(
                f"CGMAT cycle number {m_cyc} at line {m_line} does not match associated detailed Cycle {expected_detailed_cycle}"
            )
        prev_cgmat_cycle = m_cyc
        seen_cgmat_detail_indices.add(prec_detail)
        detail_target = detailed_cycles[prec_detail]
        detail_target["cgmat_cycle_line"] = m_line
        detail_target["cgmat_cycle_token"] = marker["token"]
        detail_target["cgmat_cycle_number"] = m_cyc
        cgmat_cycle_markers.append(
            {
                "line": m_line,
                "text": marker["text"],
                "token": marker["token"],
                "cycle_number": m_cyc,
                "detailed_cycle": expected_detailed_cycle,
                "summary_ncyc": summary_rows[prec_detail]["ncyc"],
            }
        )

    # Locate required Final results ($TEXT:Result:) block
    result_text_blocks = [b for b in text_blocks if b["name"] == "Result"]
    if not result_text_blocks:
        raise ValueError(
            "Missing required '$TEXT:Result: $$ Final results $$' block"
        )
    if len(result_text_blocks) > 1:
        raise ValueError(
            f"Ambiguous REFMAC log: found {len(result_text_blocks)} '$TEXT:Result:' blocks"
        )
    if result_text_blocks[0]["preceding_detailed_cycle_count"] != num_cycles:
        raise ValueError(
            "Ambiguous cycle ordering: detailed Overall/Free R pairs appear after Final results block"
        )
    final_results_block = _parse_final_results_block(result_text_blocks[0])

    # Validate resolution_rfactor tables and resolve initial, intermediate, and final cycle tables
    resln_rfactor_blocks = [
        t for t in raw_tables if t["table_kind"] == "resolution_rfactor"
    ]
    if not resln_rfactor_blocks:
        raise ValueError(
            "Missing required '$TABLE: Cycle <N>. Rfactor analysis, F distribution v resln :' block"
        )

    seen_resln_cycles: list[int] = []
    for block in resln_rfactor_blocks:
        cyc_num = block["cycle_number"]
        if seen_resln_cycles and cyc_num <= seen_resln_cycles[-1]:
            raise ValueError(
                f"Non-increasing or duplicate resolution R-factor table Cycle {cyc_num} "
                f"at line {block['title']['line']} after Cycle {seen_resln_cycles[-1]}"
            )
        if cyc_num < 1 or cyc_num > num_cycles:
            raise ValueError(
                f"Resolution R-factor table Cycle {cyc_num} at line {block['title']['line']} "
                f"is out of range for 1..{num_cycles} detailed cycles"
            )
        # Table for detailed cycle C must precede the C-th detailed Overall/Free pair
        if block["preceding_detailed_cycle_count"] != cyc_num - 1:
            raise ValueError(
                f"Resolution R-factor table Cycle {cyc_num} at line {block['title']['line']} "
                f"is misaligned with detailed cycle pairs (preceded by "
                f"{block['preceding_detailed_cycle_count']} pairs, expected {cyc_num - 1})"
            )
        seen_resln_cycles.append(cyc_num)

    if resln_rfactor_blocks[0]["cycle_number"] != 1:
        raise ValueError(
            f"First resolution R-factor table must be Cycle 1 (corresponding to Ncyc 0), "
            f"got Cycle {resln_rfactor_blocks[0]['cycle_number']}"
        )
    if resln_rfactor_blocks[-1]["cycle_number"] != num_cycles:
        raise ValueError(
            f"Ambiguous or missing final resolution R-factor table: last table is "
            f"Cycle {resln_rfactor_blocks[-1]['cycle_number']}, expected final detailed Cycle {num_cycles} "
            f"(for summary Ncyc {num_cycles - 1})"
        )

    parsed_resln_rfactor_tables: list[dict[str, Any]] = []
    for block in resln_rfactor_blocks:
        cyc_num = block["cycle_number"]
        if num_cycles == 1:
            phase_label = "final"
        elif cyc_num == 1:
            phase_label = "initial"
        elif cyc_num == num_cycles:
            phase_label = "final"
        else:
            phase_label = "intermediate"
        parsed_table = _parse_resolution_rfactor_table(
            block, phase=phase_label, summary_ncyc=cyc_num - 1
        )
        detail_for_cyc = detailed_cycles[cyc_num - 1]
        if detail_for_cyc["number_of_used_reflections"] is not None:
            if (
                detail_for_cyc["number_of_used_reflections"]
                != parsed_table["nr_used_sum"]
            ):
                raise ValueError(
                    f"Detailed Cycle {cyc_num} Number of used reflections "
                    f"({detail_for_cyc['number_of_used_reflections']} at line "
                    f"{detail_for_cyc['number_of_used_reflections_line']}) != "
                    f"Cycle {cyc_num} resolution table NR_used sum ({parsed_table['nr_used_sum']})"
                )
        parsed_resln_rfactor_tables.append(parsed_table)

    if num_cycles == 1:
        initial_resolution_bins = _parse_resolution_rfactor_table(
            resln_rfactor_blocks[0], phase="initial", summary_ncyc=0
        )
        final_resolution_bins = parsed_resln_rfactor_tables[-1]
    else:
        initial_resolution_bins = parsed_resln_rfactor_tables[0]
        final_resolution_bins = parsed_resln_rfactor_tables[-1]

    # Validate resolution_fom tables cycle uniqueness, ordering, and association
    fom_blocks = [t for t in raw_tables if t["table_kind"] == "resolution_fom"]
    seen_fom_cycles: list[int] = []
    for f_block in fom_blocks:
        f_cyc = f_block["cycle_number"]
        if seen_fom_cycles and f_cyc <= seen_fom_cycles[-1]:
            raise ValueError(
                f"Non-increasing or duplicate resolution FOM table Cycle {f_cyc} "
                f"at line {f_block['title']['line']} after Cycle {seen_fom_cycles[-1]}"
            )
        if f_cyc < 1 or f_cyc > num_cycles:
            raise ValueError(
                f"Resolution FOM table Cycle {f_cyc} at line {f_block['title']['line']} "
                f"is out of range for 1..{num_cycles} detailed cycles"
            )
        if f_block["preceding_detailed_cycle_count"] != f_cyc - 1:
            raise ValueError(
                f"Resolution FOM table Cycle {f_cyc} at line {f_block['title']['line']} "
                f"is misaligned with detailed cycle pairs (preceded by "
                f"{f_block['preceding_detailed_cycle_count']} pairs, expected {f_cyc - 1})"
            )
        seen_fom_cycles.append(f_cyc)

    # Assign table_block IDs matching 141-refmac-parser-truth.json conventions
    table_blocks_out: list[dict[str, Any]] = []
    other_idx = 0
    for block in raw_tables:
        kind = block["table_kind"]
        cyc = block["cycle_number"]
        if kind == "resolution_rfactor":
            if num_cycles == 1:
                block_id = "final_resolution_rfactor"
            elif cyc == 1:
                block_id = "initial_resolution_rfactor"
            elif cyc == num_cycles:
                block_id = "final_resolution_rfactor"
            else:
                block_id = f"cycle_{cyc}_resolution_rfactor"
        elif kind == "resolution_fom":
            if num_cycles == 1:
                block_id = "final_resolution_fom"
            elif cyc == 1:
                block_id = "initial_resolution_fom"
            elif cyc == num_cycles:
                block_id = "final_resolution_fom"
            else:
                block_id = f"cycle_{cyc}_resolution_fom"
        elif kind == "cycle_summary":
            block_id = "cycle_summary"
        else:
            other_idx += 1
            block_id = f"other_table_{other_idx}"

        table_blocks_out.append(
            {
                "id": block_id,
                "table_kind": kind,
                "cycle_number": cyc,
                "title": dict(block["title"]),
                "graph_declaration_lines": list(block["graph_declaration_lines"]),
                "header_lines": list(block["header_lines"]),
                "header_tokens": list(block["header_tokens"]),
                "double_dollar_roles": dict(block["double_dollar_roles"]),
                "data_line_range_inclusive": list(block["data_line_range_inclusive"]),
                "row_count": block["row_count"],
                "column_count": block["column_count"],
                "rows": [
                    {
                        "line": r["line"],
                        "text": r["text"],
                        "tokens": list(r["tokens"]),
                    }
                    for r in block["rows"]
                ],
            }
        )

    # Reconcile every cycle i in 0..num_cycles-1 across detailed_cycles, cycle_summary, and final_results
    cycle_r_rows: list[list[Any]] = []
    for i in range(num_cycles):
        detail = detailed_cycles[i]
        summary = summary_rows[i]
        detailed_cycle_num = i + 1
        summary_ncyc = summary["ncyc"]
        detail["detailed_cycle"] = detailed_cycle_num
        detail["summary_ncyc"] = summary_ncyc

        is_initial = i == 0
        is_final = i == num_cycles - 1

        _reconcile_r_pair(
            cycle_label=f"detailed Cycle {detailed_cycle_num} / summary Ncyc {summary_ncyc}",
            detail_overall_tok=detail["overall_r_token"],
            detail_overall_dec=detail["overall_r_decimal"],
            detail_overall_line=detail["overall_r_line"],
            detail_free_tok=detail["free_r_token"],
            detail_free_dec=detail["free_r_decimal"],
            detail_free_line=detail["free_r_line"],
            summary_rfact_tok=summary["rfact_token"],
            summary_rfact_dec=summary["rfact_decimal"],
            summary_rfree_tok=summary["rfree_token"],
            summary_rfree_dec=summary["rfree_decimal"],
            summary_line=summary["line"],
            final_results_rfactor_tok=(
                final_results_block["rfactor_initial_token"] if is_initial else None
            ),
            final_results_rfactor_dec=(
                final_results_block["rfactor_initial_decimal"] if is_initial else None
            ),
            final_results_rfactor_line=(
                final_results_block["r_factor_line"] if is_initial else None
            ),
            final_results_rfree_tok=(
                final_results_block["rfree_initial_token"] if is_initial else None
            ),
            final_results_rfree_dec=(
                final_results_block["rfree_initial_decimal"] if is_initial else None
            ),
            final_results_rfree_line=(
                final_results_block["r_free_line"] if is_initial else None
            ),
        )

        if is_final:
            _reconcile_r_pair(
                cycle_label=f"final detailed Cycle {detailed_cycle_num} / summary Ncyc {summary_ncyc}",
                detail_overall_tok=detail["overall_r_token"],
                detail_overall_dec=detail["overall_r_decimal"],
                detail_overall_line=detail["overall_r_line"],
                detail_free_tok=detail["free_r_token"],
                detail_free_dec=detail["free_r_decimal"],
                detail_free_line=detail["free_r_line"],
                summary_rfact_tok=summary["rfact_token"],
                summary_rfact_dec=summary["rfact_decimal"],
                summary_rfree_tok=summary["rfree_token"],
                summary_rfree_dec=summary["rfree_decimal"],
                summary_line=summary["line"],
                final_results_rfactor_tok=final_results_block["rfactor_final_token"],
                final_results_rfactor_dec=final_results_block["rfactor_final_decimal"],
                final_results_rfactor_line=final_results_block["r_factor_line"],
                final_results_rfree_tok=final_results_block["rfree_final_token"],
                final_results_rfree_dec=final_results_block["rfree_final_decimal"],
                final_results_rfree_line=final_results_block["r_free_line"],
            )

        cycle_r_rows.append(
            [
                summary_ncyc,
                summary["rfact_token"],
                summary["rfree_token"],
                summary["line"],
                detail["overall_r_line"],
                detail["free_r_line"],
            ]
        )

    initial_detail = detailed_cycles[0]
    final_detail = detailed_cycles[-1]

    # Strip internal Decimal objects before returning JSON-serializable dict
    for row in summary_rows:
        row.pop("rfact_decimal", None)
        row.pop("rfree_decimal", None)
    for detail in detailed_cycles:
        detail.pop("overall_r_decimal", None)
        detail.pop("free_r_decimal", None)
    final_results_block.pop("rfactor_initial_decimal", None)
    final_results_block.pop("rfactor_final_decimal", None)
    final_results_block.pop("rfree_initial_decimal", None)
    final_results_block.pop("rfree_final_decimal", None)

    initial_summary = summary_rows[0]
    final_summary = summary_rows[-1]

    resolution_tables_list = parsed_resln_rfactor_tables
    initial_count_vector = [
        (b["m_4ssq_ll_token"], b["nr_used"], b["nr_free"])
        for b in initial_resolution_bins["bins"]
    ]
    final_count_vector = [
        (b["m_4ssq_ll_token"], b["nr_used"], b["nr_free"])
        for b in final_resolution_bins["bins"]
    ]

    reconciled_initial_cycle: dict[str, Any] = {
        "summary_ncyc": 0,
        "detailed_cycle": 1,
        "resolution_table_cycle": initial_resolution_bins["detailed_cycle"],
        "r_work_token": initial_summary["rfact_token"],
        "r_work": initial_summary["rfact"],
        "r_work_decimal_places": initial_summary["rfact_decimal_places"],
        "r_free_token": initial_summary["rfree_token"],
        "r_free": initial_summary["rfree"],
        "r_free_decimal_places": initial_summary["rfree_decimal_places"],
        "detailed_r_work_token": initial_detail["overall_r_token"],
        "detailed_r_work_decimal_places": initial_detail["overall_r_decimal_places"],
        "detailed_r_free_token": initial_detail["free_r_token"],
        "detailed_r_free_decimal_places": initial_detail["free_r_decimal_places"],
        "summary_r_work_token": initial_summary["rfact_token"],
        "summary_r_work_decimal_places": initial_summary["rfact_decimal_places"],
        "summary_r_free_token": initial_summary["rfree_token"],
        "summary_r_free_decimal_places": initial_summary["rfree_decimal_places"],
        "final_results_r_work_token": final_results_block["rfactor_initial_token"],
        "final_results_r_work_decimal_places": final_results_block[
            "rfactor_initial_decimal_places"
        ],
        "final_results_r_free_token": final_results_block["rfree_initial_token"],
        "final_results_r_free_decimal_places": final_results_block[
            "rfree_initial_decimal_places"
        ],
        "nr_used_sum": initial_resolution_bins["nr_used_sum"],
        "nr_free_sum": initial_resolution_bins["nr_free_sum"],
        "combined_reported_count": initial_resolution_bins["combined_reported_count"],
        "sources": {
            "detailed_overall_line": initial_detail["overall_r_line"],
            "detailed_free_line": initial_detail["free_r_line"],
            "cycle_summary_line": initial_summary["line"],
            "final_results_r_factor_line": final_results_block["r_factor_line"],
            "final_results_r_free_line": final_results_block["r_free_line"],
            "resolution_rfactor_title_line": initial_resolution_bins["title"]["line"],
        },
    }

    reconciled_final_cycle: dict[str, Any] = {
        "summary_ncyc": final_summary["ncyc"],
        "detailed_cycle": num_cycles,
        "resolution_table_cycle": final_resolution_bins["detailed_cycle"],
        "r_work_token": final_summary["rfact_token"],
        "r_work": final_summary["rfact"],
        "r_work_decimal_places": final_summary["rfact_decimal_places"],
        "r_free_token": final_summary["rfree_token"],
        "r_free": final_summary["rfree"],
        "r_free_decimal_places": final_summary["rfree_decimal_places"],
        "detailed_r_work_token": final_detail["overall_r_token"],
        "detailed_r_work_decimal_places": final_detail["overall_r_decimal_places"],
        "detailed_r_free_token": final_detail["free_r_token"],
        "detailed_r_free_decimal_places": final_detail["free_r_decimal_places"],
        "summary_r_work_token": final_summary["rfact_token"],
        "summary_r_work_decimal_places": final_summary["rfact_decimal_places"],
        "summary_r_free_token": final_summary["rfree_token"],
        "summary_r_free_decimal_places": final_summary["rfree_decimal_places"],
        "final_results_r_work_token": final_results_block["rfactor_final_token"],
        "final_results_r_work_decimal_places": final_results_block[
            "rfactor_final_decimal_places"
        ],
        "final_results_r_free_token": final_results_block["rfree_final_token"],
        "final_results_r_free_decimal_places": final_results_block[
            "rfree_final_decimal_places"
        ],
        "nr_used_sum": final_resolution_bins["nr_used_sum"],
        "nr_free_sum": final_resolution_bins["nr_free_sum"],
        "combined_reported_count": final_resolution_bins["combined_reported_count"],
        "sources": {
            "detailed_overall_line": final_detail["overall_r_line"],
            "detailed_free_line": final_detail["free_r_line"],
            "cycle_summary_line": final_summary["line"],
            "final_results_r_factor_line": final_results_block["r_factor_line"],
            "final_results_r_free_line": final_results_block["r_free_line"],
            "resolution_rfactor_title_line": final_resolution_bins["title"]["line"],
        },
    }

    return {
        "source_metadata": {
            "line_count": total_lines,
            "reported_suite": reported_suite,
            "reported_refmac_version": reported_refmac_version,
            "reported_run_date_token": reported_run_date_token,
            "requested_ncyc": requested_ncyc,
        },
        "table_blocks": table_blocks_out,
        "cycle_summary": cycle_summary,
        "detailed_cycles": detailed_cycles,
        "cgmat_cycle_markers": cgmat_cycle_markers,
        "cycle_r_values": {
            "row_fields": [
                "summary_Ncyc",
                "Rfact_token",
                "Rfree_token",
                "summary_line",
                "matching_ordered_overall_detail_line",
                "matching_ordered_free_detail_line",
            ],
            "rows": cycle_r_rows,
            "summary_cycle_min": cycle_summary["summary_cycle_min"],
            "summary_cycle_max": cycle_summary["summary_cycle_max"],
            "summary_row_count": num_cycles,
            "Rfact_printed_decimal_places": cycle_summary[
                "rfact_printed_decimal_places"
            ],
            "Rfree_printed_decimal_places": cycle_summary[
                "rfree_printed_decimal_places"
            ],
            "all_ordered_detail_pairs_equal_summary_values": True,
            "detail_rfactor_table_cycle_labels": seen_resln_cycles,
        },
        "resolution_bin_values": {
            "row_fields": [
                "bin_ordinal",
                "line",
                "M(4SSQ/LL)_token",
                "NR_used",
                "NR_free",
                "Rf_used_token",
                "Rf_free_token",
            ],
            "tables": resolution_tables_list,
            "Rf_used_printed_decimal_places": final_resolution_bins[
                "rf_used_printed_decimal_places"
            ],
            "Rf_free_printed_decimal_places": final_resolution_bins[
                "rf_free_printed_decimal_places"
            ],
            "initial_and_final_count_vectors_equal": (
                initial_count_vector == final_count_vector
            ),
        },
        "initial_resolution_bins": initial_resolution_bins,
        "final_resolution_bins": final_resolution_bins,
        "endpoint_detail": {
            "initial": initial_detail["endpoint_lines"],
            "final": final_detail["endpoint_lines"],
            "final_distinct_weighted_metrics": final_detail[
                "distinct_weighted_metric_lines"
            ],
            "Rwork_label": "Overall R factor",
            "Rfree_label": "Free R factor",
            "Rwork_final_token": final_detail["overall_r_token"],
            "Rfree_final_token": final_detail["free_r_token"],
            "Rwork_printed_decimal_places": final_detail["overall_r_decimal_places"],
            "Rfree_printed_decimal_places": final_detail["free_r_decimal_places"],
        },
        "final_results_block": final_results_block,
        "reconciled_initial_cycle": reconciled_initial_cycle,
        "reconciled_final_cycle": reconciled_final_cycle,
        "consistency_checks": {
            "initial_detail_summary_and_final_results_initial_values_equal": True,
            "final_detail_summary_and_final_results_final_values_equal": True,
            "final_nr_used_sum": final_resolution_bins["nr_used_sum"],
            "final_nr_free_sum": final_resolution_bins["nr_free_sum"],
            "final_combined_reported_count": final_resolution_bins[
                "combined_reported_count"
            ],
            "final_nr_used_sum_matches_reported_used_reflections": (
                final_detail["number_of_used_reflections"]
                == final_resolution_bins["nr_used_sum"]
                if final_detail["number_of_used_reflections"] is not None
                else None
            ),
        },
    }
