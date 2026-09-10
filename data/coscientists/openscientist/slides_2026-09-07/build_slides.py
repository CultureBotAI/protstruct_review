#!/usr/bin/env python3
"""
Generate landscape SVG slides for the 2026-09-07 1SAR artefact audit deck.

This is an *audit* deck. The 1SAR artefact was found not to contain the model its
own report describes: the file shipped as `1sar_final.pdb` is the round-4 output,
and the reported round 7 was never packaged. The deck documents what the artefact
actually contains and withdraws the conclusions that assumed otherwise.

Self-contained by convention (see the sibling slides_2026-05-0{4,5} directories):
all data is hardcoded here, so the deck rebuilds byte-identically without the
artefact, the oracles, or the repository's runtime.

Output dimensions: 1920 x 1080 (16:9 landscape).
No external Python deps; SVG is built as text. rsvg-convert merges to PDF:

    python3 build_slides.py
    rsvg-convert -f pdf -o 1SAR_artefact_audit_2026-09-07.pdf svg/*.svg
"""
from pathlib import Path

W, H = 1920, 1080

# Palette — identical to the 2026-05-05 deck so the two read as one series.
BG = "#ffffff"
INK = "#1a1a2e"
MUTED = "#5a6071"
ACCENT = "#1f4e8c"
ACCENT_LIGHT = "#dce6f4"
GOOD = "#1f7a3f"
GOOD_LIGHT = "#dff0e1"
WARN = "#b07c00"
WARN_LIGHT = "#fbeecb"
BAD = "#a8201a"
BAD_LIGHT = "#f5d6d4"
GRID = "#e3e6ee"
ROW_ALT = "#f7f8fb"

REVIEW_DATE = "2026-09-07"
DECK_DATE = "2026-09-07"
PRIOR_DATE = "2026-05-05"

OUT = Path(__file__).parent / "svg"
OUT.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------------
# Primitives
# ------------------------------------------------------------------
def svg_open(width=W, height=H):
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'font-family="Helvetica, Arial, sans-serif">\n'
        f'  <rect width="100%" height="100%" fill="{BG}"/>\n'
    )


def svg_close():
    return "</svg>\n"


def escape(s):
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def header(title, subtitle=None):
    out = []
    out.append(f'  <rect x="0" y="0" width="{W}" height="6" fill="{ACCENT}"/>')
    out.append(
        f'  <text x="80" y="86" font-size="44" font-weight="700" fill="{INK}">{escape(title)}</text>'
    )
    if subtitle:
        out.append(
            f'  <text x="80" y="128" font-size="22" font-weight="400" fill="{MUTED}">{escape(subtitle)}</text>'
        )
    out.append(f'  <line x1="80" y1="{H-60}" x2="{W-80}" y2="{H-60}" stroke="{GRID}" stroke-width="1"/>')
    out.append(
        f'  <text x="80" y="{H-30}" font-size="16" fill="{MUTED}">'
        f'1SAR artefact audit · openscientist artefact cdba2c07 · {REVIEW_DATE}</text>'
    )
    out.append(
        f'  <text x="{W-80}" y="{H-30}" font-size="16" fill="{MUTED}" text-anchor="end">'
        f'protstruct_review · artefact audit {DECK_DATE}</text>'
    )
    return "\n".join(out) + "\n"


def table(x, y, col_widths, header_row, data_rows, row_height=42,
          header_fill=ACCENT, header_text="#ffffff",
          cell_fills=None, cell_text_colors=None,
          font_size=20, header_font_size=20, header_weight="700",
          align=None):
    """Render a styled table. cell_fills/cell_text_colors are 2D lists matching data_rows."""
    out = []
    n_cols = len(col_widths)
    total_w = sum(col_widths)
    align = align or ["left"] * n_cols

    cur_x = x
    out.append(f'  <rect x="{x}" y="{y}" width="{total_w}" height="{row_height}" fill="{header_fill}"/>')
    for i, cell in enumerate(header_row):
        cw = col_widths[i]
        if align[i] == "center":
            tx, anchor = cur_x + cw / 2, "middle"
        elif align[i] == "right":
            tx, anchor = cur_x + cw - 14, "end"
        else:
            tx, anchor = cur_x + 14, "start"
        out.append(
            f'  <text x="{tx}" y="{y + row_height/2 + header_font_size/3}" '
            f'font-size="{header_font_size}" font-weight="{header_weight}" '
            f'fill="{header_text}" text-anchor="{anchor}">{escape(cell)}</text>'
        )
        cur_x += cw

    for r, row in enumerate(data_rows):
        ry = y + row_height * (r + 1)
        bg = ROW_ALT if r % 2 == 1 else BG
        out.append(f'  <rect x="{x}" y="{ry}" width="{total_w}" height="{row_height}" fill="{bg}"/>')
        cur_x = x
        for c, cell in enumerate(row):
            cw = col_widths[c]
            if cell_fills and cell_fills[r][c]:
                out.append(
                    f'  <rect x="{cur_x}" y="{ry}" width="{cw}" height="{row_height}" '
                    f'fill="{cell_fills[r][c]}"/>'
                )
            color = INK
            if cell_text_colors and cell_text_colors[r][c]:
                color = cell_text_colors[r][c]
            if align[c] == "center":
                tx, anchor = cur_x + cw / 2, "middle"
            elif align[c] == "right":
                tx, anchor = cur_x + cw - 14, "end"
            else:
                tx, anchor = cur_x + 14, "start"
            out.append(
                f'  <text x="{tx}" y="{ry + row_height/2 + font_size/3}" '
                f'font-size="{font_size}" fill="{color}" text-anchor="{anchor}">{escape(cell)}</text>'
            )
            cur_x += cw

    total_h = row_height * (len(data_rows) + 1)
    out.append(
        f'  <rect x="{x}" y="{y}" width="{total_w}" height="{total_h}" '
        f'fill="none" stroke="{GRID}" stroke-width="1"/>'
    )
    cur_x = x
    for cw in col_widths[:-1]:
        cur_x += cw
        out.append(
            f'  <line x1="{cur_x}" y1="{y}" x2="{cur_x}" y2="{y+total_h}" '
            f'stroke="{GRID}" stroke-width="1"/>'
        )
    return "\n".join(out) + "\n"


def chip(x, y, text, fill, text_color="#ffffff", height=36, font_size=16, pad=14):
    w = max(80, int(len(text) * 8.5) + pad * 2)
    out = (
        f'  <rect x="{x}" y="{y}" width="{w}" height="{height}" rx="6" ry="6" fill="{fill}"/>\n'
        f'  <text x="{x + w/2}" y="{y + height/2 + font_size/3}" font-size="{font_size}" '
        f'font-weight="700" fill="{text_color}" text-anchor="middle">{escape(text)}</text>\n'
    )
    return out, w


def panel(x, y, w, h, fill=ACCENT_LIGHT, stroke=None):
    s = f' stroke="{stroke}" stroke-width="2"' if stroke else ""
    return (f'  <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" ry="10" '
            f'fill="{fill}"{s}/>\n')


def wrap(text, width):
    """Greedy wrap by character count; returns a list of lines."""
    lines, cur, cur_len = [], [], 0
    for word in text.split():
        if cur_len and cur_len + 1 + len(word) > width:
            lines.append(" ".join(cur))
            cur, cur_len = [word], len(word)
        else:
            cur.append(word)
            cur_len += len(word) + (1 if cur_len else 0)
    if cur:
        lines.append(" ".join(cur))
    return lines


def paragraph(x, y, text, width=100, size=20, color=INK, leading=30, weight="400"):
    out = []
    for i, line in enumerate(wrap(text, width)):
        out.append(
            f'  <text x="{x}" y="{y + i*leading}" font-size="{size}" '
            f'font-weight="{weight}" fill="{color}">{escape(line)}</text>'
        )
    return "\n".join(out) + "\n"


def write_svg(name, body):
    p = OUT / f"{name}.svg"
    p.write_text(svg_open() + body + svg_close())
    return p


# ------------------------------------------------------------------
# 01 — Title
# ------------------------------------------------------------------
# ------------------------------------------------------------------
# 01 — Title
# ------------------------------------------------------------------
def slide_01_title():
    out = [f'  <rect x="0" y="0" width="{W}" height="6" fill="{ACCENT}"/>']
    out.append(
        f'  <text x="120" y="320" font-size="72" font-weight="700" fill="{INK}">'
        f'1SAR artefact audit</text>')
    out.append(
        f'  <text x="120" y="400" font-size="44" font-weight="400" fill="{BAD}">'
        f'The archive does not contain the model its report describes</text>')
    out.append(f'  <line x1="120" y1="460" x2="1100" y2="460" stroke="{BAD}" stroke-width="3"/>')

    bullets = [
        "Seven rounds were run · round 7 was reported · round 4 was shipped as 1sar_final.pdb",
        "The round-7 coordinates are absent from the archive entirely",
        "So the reported R-free of 0.199 is real — it rounds from round 7's 0.1989",
        "Five earlier review passes compared the report against the wrong model",
    ]
    for i, b in enumerate(bullets):
        ry = 530 + i * 52
        out.append(f'  <circle cx="132" cy="{ry-7}" r="6" fill="{ACCENT}"/>')
        out.append(f'  <text x="158" y="{ry}" font-size="24" fill="{INK}">{escape(b)}</text>')

    out.append(panel(120, 780, 1680, 150, BAD_LIGHT))
    out.append(paragraph(
        150, 832,
        "The defect is packaging, not reporting. An artefact that cannot substantiate its own "
        "report is indistinguishable, from the coordinates alone, from one that lies.",
        width=86, size=26, color=BAD, weight="700", leading=36))

    out.append(
        f'  <text x="120" y="{H-70}" font-size="20" fill="{MUTED}">'
        f'openscientist artefact cdba2c07-daff-4f60-ae96-12452b3a5fbb · '
        f'protstruct_review · {DECK_DATE}</text>')
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------
# 02 — The packaging failure
# ------------------------------------------------------------------
def slide_02_why():
    out = [header("What the archive actually contains",
                  "Every row below is from the artefact's own provenance")]

    rows = [
        ["packaged 1sar_final.pdb", "0.1563", "0.2114", "yes — labelled final", "round-4 output"],
        ["round 5", "0.1555", "0.2109", "yes", ""],
        ["round 6", "0.1539", "0.2068", "yes", ""],
        ["round 7 — the reported final", "0.1488", "0.1989", "NO — coordinates absent", "transcripts only"],
    ]
    fills = [[WARN_LIGHT, None, None, WARN_LIGHT, WARN_LIGHT],
             [None, None, None, None, None],
             [None, None, None, None, None],
             [BAD_LIGHT, BAD_LIGHT, BAD_LIGHT, BAD_LIGHT, BAD_LIGHT]]
    colors = [[WARN, INK, INK, WARN, MUTED],
              [INK, INK, INK, MUTED, MUTED],
              [INK, INK, INK, MUTED, MUTED],
              [BAD, BAD, BAD, BAD, BAD]]
    out.append(table(
        80, 190, [460, 200, 200, 480, 320],
        ["Model", "R-work", "R-free", "In the archive?", "Provenance"],
        rows, row_height=58, font_size=19,
        cell_fills=fills, cell_text_colors=colors,
        align=["left", "right", "right", "left", "left"]))

    out.append(
        f'  <text x="80" y="524" font-size="26" font-weight="700" fill="{INK}">Evidence</text>')
    ev = [
        "iter4_transcript.json records the copy that made the packaged file: cp 1sar_final_001.pdb → data/1sar_final.pdb",
        "Its header (0.1563 / 0.2114) matches data/1sar_round5_input.pdb — the packaged “final” is what round 5 was handed",
        "claude_iterations.log:510 records round 7 at R-work 0.1488, R-free 0.1989, 159 waters, 1 Ca²⁺, 1 Na⁺, 1 SO4",
        "claude_iterations.log:752 names /agent/job/1sar_round7_001.pdb as the final deliverable (1654 atoms)",
        "0.1989 / 0.1488 appear in four provenance transcripts; iter10 runs model_vs_data against the round-7 path",
        "An ignore-independent search of every archive member finds no round-7 PDB or MTZ",
    ]
    for i, e in enumerate(ev):
        ry = 570 + i * 34
        out.append(f'  <circle cx="94" cy="{ry-7}" r="4" fill="{ACCENT}"/>')
        out.append(f'  <text x="114" y="{ry}" font-size="19" fill="{INK}">{escape(e)}</text>')

    out.append(panel(80, 790, 1760, 140, ACCENT_LIGHT))
    out.append(paragraph(
        110, 840,
        "So 0.199 is not fabricated — it rounds from the agent's own round 7. The deliverable was "
        "simply never written into the archive, and a three-round-stale file was shipped under the "
        "name the report cites.",
        width=100, size=22, color=ACCENT, weight="700", leading=32))
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------
# 03 — What the report got right, and the one real defect
# ------------------------------------------------------------------
def slide_03_headline():
    out = [header("The report's numbers, re-examined",
                  "The clearest surviving defect is not the one we filed")]

    cols = [
        ("Not a misreport", GOOD, GOOD_LIGHT,
         "0.199 rounds from round 7's 0.1989, and 0.149 from 0.1488. Both are the "
         "agent's own measured values for the model it describes."),
        ("A packaging failure", WARN, WARN_LIGHT,
         "The model those numbers describe was never packaged. Measuring the shipped "
         "file gives 0.2116 — 0.0127 worse — with no way to tell why."),
        ("A real defect", BAD, BAD_LIGHT,
         "Round 7's gap is 0.1989 − 0.1488 = 0.0501, failing the < 0.05 criterion the task "
         "prompt set. The report states “gap=0.050”."),
    ]
    for i, (title, color, fill, body) in enumerate(cols):
        cx = 80 + i * 590
        out.append(panel(cx, 190, 550, 300, fill))
        out.append(
            f'  <text x="{cx+30}" y="242" font-size="26" font-weight="700" '
            f'fill="{color}">{escape(title)}</text>')
        out.append(paragraph(cx + 30, 292, body, width=42, size=20, leading=30))

    out.append(
        f'  <text x="80" y="565" font-size="28" font-weight="700" fill="{INK}">'
        f'What five review passes got wrong</text>')
    out.append(paragraph(
        80, 612,
        "This harness filed, and defended across five rounds, the conclusion that 0.199 "
        "“corresponds to no model the agent produced”. That conclusion came from comparing a "
        "reported number against a file whose name said final, without once checking the file's "
        "provenance. The decisive check was object identity — not another comparison of the same "
        "headline numbers, which is what each round performed.",
        width=112, size=22, leading=32))

    out.append(panel(80, 790, 1760, 140, BAD_LIGHT))
    out.append(paragraph(
        110, 842,
        "An accusation that an agent invented a number is a serious claim. It was wrong, it was "
        "checkable from the archive throughout, and it survived five adversarial passes.",
        width=96, size=23, color=BAD, weight="700", leading=33))
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------
# 04 — What was measured, on which model
# ------------------------------------------------------------------
def slide_04_regrade():
    out = [header("What was measured — and on which model",
                  "A valid audit of the packaged round-4 model; NOT a measurement of the reported final")]

    rows = [
        ["T03", "R-work / R-free, phenix.model_vs_data", "0.1564 / 0.2116", "matches packaged header"],
        ["T03", "R-work / R-free, gemmi matched radii", "0.1622 / 0.2136", "independent code path"],
        ["T03", "gemmi − PHENIX R-work offset (rule 2)", "+0.0058", "passes"],
        ["T03", "R-work/R-free gap", "0.0552", "no criterion applied"],
        ["T14", "flip sets — reduce / mmtbx.reduce2", "14 / 18", "0 confident conflicts"],
        ["T15", "SS agreement — packaged / deposited", "0.8802 / 0.8646", "uninterpretable"],
        ["T16", "DockQ vs deposited, AB:AB", "0.9445", "crystallographic dimer"],
    ]
    fills = [[ACCENT_LIGHT, None, None, None] for _ in rows]
    colors = [[ACCENT, INK, INK, MUTED] for _ in rows]
    colors[2][3] = GOOD; fills[2][3] = GOOD_LIGHT
    colors[3][3] = MUTED; fills[3][3] = ROW_ALT
    colors[5][3] = WARN; fills[5][3] = WARN_LIGHT
    out.append(table(
        80, 190, [110, 700, 380, 460],
        ["Task", "Metric", "Value", "Reading"],
        rows, row_height=52, font_size=19,
        cell_fills=fills, cell_text_colors=colors,
        align=["center", "left", "right", "center"]))

    notes = [
        (BAD, "T03 is NOT settled. driving_example_T03 is conjunctive — “all must pass for green”. Only "
              "the R-value rules were run. Rule 1's deposition reference does not exist for 1SAR (the "
              "1990 entry records FREE R VALUE : NULL); rule 4 was not re-run; and rule 3 does not hold "
              "as written — input NREF 7248 against 7262 in every output MTZ (see #584)."),
        (WARN, "Neither the accusation nor the exoneration is oracled. Raw oracle output was not "
               "committed, so 0.1564 / 0.2116 need a licensed PHENIX rerun to reproduce — and round 7's "
               "numbers are attested only by the agent's own log, so they can never be re-measured."),
    ]
    y = 640
    for color, text in notes:
        lines = wrap(text, 112)
        out.append(f'  <rect x="80" y="{y-22}" width="5" height="{len(lines)*29+8}" fill="{color}"/>')
        out.append(paragraph(105, y, text, width=112, size=20, leading=29))
        y += len(lines) * 29 + 30
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------
# 05 — Findings about the artefact
# ------------------------------------------------------------------
def slide_05_new_tasks():
    out = [header("Three findings about the artefact",
                  "The first is a defect in our own benchmark")]

    out.append(panel(80, 180, 1760, 250, BAD_LIGHT))
    out.append(
        f'  <text x="112" y="230" font-size="28" font-weight="700" fill="{BAD}">'
        f'1 · The wrong protein identity came from our own prompt</text>')
    out.append(paragraph(
        112, 278,
        "The report calls 1SAR staphylococcal nuclease; it is ribonuclease Sa. But the harness "
        "prompt says so first — claude_iterations.log:5: “Perform crystallographic refinement and "
        "validation of staphylococcal nuclease (PDB: 1SAR)”. Line 21 primes the Ca²⁺ site, and the "
        "supplied 1sar.pdb carries no HEADER/TITLE metadata, so the prompt was the only identity cue.",
        width=108, size=20, leading=29))
    out.append(paragraph(
        112, 390,
        "The agent failed to challenge a false premise it was handed. It did not originate it.",
        width=108, size=20, color=BAD, weight="700", leading=29))

    out.append(panel(80, 455, 860, 250, WARN_LIGHT))
    out.append(
        f'  <text x="112" y="503" font-size="25" font-weight="700" fill="{WARN}">'
        f'2 · Both ions sit on deposited water sites</text>')
    out.append(paragraph(
        112, 548,
        "On the packaged model, HOH A164 is 0.18 Å from CA A98 and HOH B143 is 0.31 Å from NA B98. "
        "The starting model has no waters, so these peaks may be restored or retyped deposited "
        "waters rather than new ions. The ion assignments are not established either way.",
        width=60, size=19, leading=28))

    out.append(panel(980, 455, 860, 250, ROW_ALT))
    out.append(
        f'  <text x="1012" y="503" font-size="25" font-weight="700" fill="{ACCENT}">'
        f'3 · The starting model had two sulfates</text>')
    out.append(paragraph(
        1012, 548,
        "data/1sar.pdb contains SO4 A97 and B97 — as ATOM records. The agent inherited chain A, "
        "kept the convention, and removed chain B, exactly as its report says. Record type is not "
        "chemical identity; this harness miscounted it before noticing.",
        width=60, size=19, leading=28))

    out.append(panel(80, 730, 1760, 200, ACCENT_LIGHT))
    out.append(
        f'  <text x="112" y="778" font-size="25" font-weight="700" fill="{ACCENT}">'
        f'What this changes about the May assessment</text>')
    out.append(paragraph(
        112, 822,
        "May concluded the ion decisions were defensible and the refinement sound. Neither survives: "
        "the ion sites coincide with deposited waters, the protein-specific reasoning rests on an "
        "identity our prompt supplied, and the sulfate edit the report describes was correct. Those "
        "conclusions are withdrawn pending re-measurement.",
        width=104, size=20, leading=29))
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------
# 06 — Coverage
# ------------------------------------------------------------------
def slide_06_coverage():
    out = [header("Coverage on the packaged artefact",
                  "9 tasks measured · T03 incomplete · 1 uncovered")]

    groups = [
        ("Measured — May, carried, not re-run", WARN, WARN_LIGHT,
         ["T01 superposition", "T05 geometry", "T06 model-vs-data",
          "T10 ligand/site", "T13 data quality"]),
        ("Measured — this audit, on the packaged round-4 model", ACCENT, ACCENT_LIGHT,
         ["T03 X-ray refinement — R-value rules only; rubric NOT satisfied",
          "T14 hydrogen placement", "T15 structural classification",
          "T16 interface quality"]),
        ("Not applicable", MUTED, ROW_ALT,
         ["T04 real-space refinement · T07 predicted-model processing · T08 docking into a map · "
          "T12 cryo-EM map quality · T17 NMR ensembles — none apply to an X-ray artefact",
          "T09 molecular replacement — the model was already placed",
          "T11 loop fitting — no chain gaps (A 1–96, B 1–96)"]),
        ("Uncovered", BAD, BAD_LIGHT,
         ["T02 per-residue comparison — no driver written"]),
    ]
    y = 190
    for title, color, fill, items in groups:
        h = 54 + len(items) * 32
        out.append(panel(80, y, 1760, h, fill))
        out.append(
            f'  <text x="110" y="{y+38}" font-size="25" font-weight="700" '
            f'fill="{color}">{escape(title)}</text>')
        for i, item in enumerate(items):
            iy = y + 70 + i * 32
            out.append(f'  <circle cx="122" cy="{iy-7}" r="5" fill="{color}"/>')
            out.append(f'  <text x="146" y="{iy}" font-size="20" fill="{INK}">{escape(item)}</text>')
        y += h + 18

    out.append(paragraph(
        80, y + 34,
        "No task is claimed as settled for the agent's reported final model — that model is not in "
        "the archive, so nothing here measures it.",
        width=118, size=21, color=BAD, weight="700", leading=30))
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------
# 07 — Correction history
# ------------------------------------------------------------------
def slide_07_findings():
    out = [header("Correction history",
                  "What this record withdraws, and why")]

    rows = [
        ["“0.199 corresponds to no model the agent produced”", "withdrawn — false",
         "Round 7 produced 0.1989; it was never packaged"],
        ["“The report describes the wrong protein” (agent's error)", "reattributed",
         "The harness prompt supplied the identity"],
        ["“The starting model has zero heteroatoms”", "withdrawn — false",
         "It has two sulfates, written as ATOM"],
        ["“Ion decisions remain defensible” (May)", "withdrawn",
         "Both ions sit on deposited water sites"],
        ["“T03 settled / refinement sound”", "withdrawn",
         "Only the R-value rules of a conjunctive rubric were run"],
        ["Five successive gradings of the R-free claim", "superseded",
         "All compared the report against the wrong model"],
    ]
    fills = [[None, BAD_LIGHT, None] for _ in rows]
    colors = [[INK, BAD, MUTED] for _ in rows]
    fills[1][1] = WARN_LIGHT; colors[1][1] = WARN
    fills[5][1] = WARN_LIGHT; colors[5][1] = WARN
    out.append(table(
        80, 190, [700, 320, 740],
        ["Claim", "Status", "Why"],
        rows, row_height=64, font_size=19,
        cell_fills=fills, cell_text_colors=colors,
        align=["left", "center", "left"]))

    out.append(panel(80, 660, 1760, 270, ROW_ALT))
    out.append(
        f'  <text x="112" y="710" font-size="26" font-weight="700" fill="{INK}">'
        f'The shared blind spot</text>')
    out.append(paragraph(
        112, 756,
        "Five review passes treated three things as ground truth that were not: the filename "
        "1sar_final.pdb, the ATOM/HETATM record type as a proxy for chemical identity, and the "
        "harness prompt's statement of what protein this is. Each pass re-examined the same headline "
        "numbers more carefully than the last. None asked whether the object being measured was the "
        "object under discussion.",
        width=108, size=21, leading=30))
    out.append(paragraph(
        112, 880,
        "The check that resolved it — following provenance through the archive — cost minutes.",
        width=108, size=21, color=ACCENT, weight="700", leading=30))
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------
# 08 — Trust and reporting caveats
# ------------------------------------------------------------------
def slide_08_trust():
    out = [header("Trust and reporting caveats",
                  "What this record's own numbers can and cannot support")]

    items = [
        ("No verdict rests on cctbx grading cctbx", GOOD,
         "After the demotions, the only rows still carrying a verdict are the two gemmi offset rows "
         "— both non-cctbx. The cctbx rows that compared a round-7 claim against the round-4 "
         "packaged model are now informational."),
        ("Neither the accusation nor the exoneration is oracled", WARN,
         "Raw oracle output was not committed, so 0.1564 / 0.2116 need a licensed PHENIX rerun to "
         "reproduce. And round 7's 0.1488 / 0.1989 are attested only by the agent's own cctbx log "
         "— the coordinates are gone, so the number that clears the report can never be checked."),
        ("The QDS carries no verdicts", WARN,
         "qds_emit.py does not propagate pass_status, so no status in this record reaches the sheet, "
         "and its headline R-factors are the gemmi triple. Read verdicts from the eval, not the sheet."),
        ("The trust invariant passes by omission", MUTED,
         "The sheet carries no open cctbx-only row because it does not grade T06 — the row open on "
         "every prior 1SAR sheet. Nothing that was open was closed."),
    ]
    y = 200
    for title, color, body in items:
        lines = wrap(body, 106)
        h = 42 + len(lines) * 29
        out.append(f'  <rect x="80" y="{y}" width="6" height="{h}" fill="{color}"/>')
        out.append(
            f'  <text x="110" y="{y+28}" font-size="24" font-weight="700" '
            f'fill="{color}">{escape(title)}</text>')
        out.append(paragraph(110, y + 64, body, width=106, size=20, leading=29))
        y += h + 26
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------
# 09 — The harness since May
# ------------------------------------------------------------------
def slide_09_harness():
    out = [header("The harness since May",
                  "Real progress — and the check none of it performed")]

    items = [
        ("48-round tolerance series", ACCENT,
         "Every [template] threshold that mattered here replaced by a measured band with stated "
         "preconditions."),
        ("Negative-control track", GOOD,
         "0 of 22 false verdicts on the control set. Separately, 21 of 21 agent cases judged — a "
         "different denominator, since 6XVM was never judged."),
        ("Gate consolidation", ACCENT,
         "Negative-control headlines, governed thresholds and round-count claims are checked as data "
         "by the gate rather than trusted as prose."),
        ("What none of it checked", BAD,
         "Whether the file under evaluation is the file the report describes. No guard ties an "
         "artefact's measured model to the model its provenance names as final — which is how a "
         "false accusation survived five adversarial review passes."),
    ]
    y = 210
    for title, color, body in items:
        lines = wrap(body, 104)
        h = 44 + len(lines) * 29
        out.append(f'  <rect x="80" y="{y}" width="6" height="{h}" fill="{color}"/>')
        out.append(
            f'  <text x="110" y="{y+30}" font-size="25" font-weight="700" '
            f'fill="{color}">{escape(title)}</text>')
        out.append(paragraph(110, y + 66, body, width=104, size=20, leading=29))
        y += h + 30
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------
# 10 — Net assessment
# ------------------------------------------------------------------
def slide_10_net():
    out = [header("Net assessment",
                  "What the artefact supports, what it does not, what is still open")]

    out.append(panel(80, 190, 860, 300, GOOD_LIGHT))
    out.append(
        f'  <text x="112" y="240" font-size="27" font-weight="700" fill="{GOOD}">'
        f'Supported</text>')
    holds = [
        "The reported R-factors match the agent's round 7",
        "The sulfate edit the report describes was correct",
        "Both H builders agree on every confident flip",
        "The deposited T15 leg reproduces its calibration",
        "gemmi−PHENIX R-work offset passes at +0.0058",
    ]
    for i, t in enumerate(holds):
        out.append(
            f'  <text x="112" y="{292 + i*38}" font-size="20" fill="{INK}">✓ {escape(t)}</text>')

    out.append(panel(980, 190, 860, 300, BAD_LIGHT))
    out.append(
        f'  <text x="1012" y="240" font-size="27" font-weight="700" fill="{BAD}">Not supported</text>')
    fails = [
        "The archive does not contain the reported model",
        "Round 7's gap is 0.0501 — fails the task's < 0.05",
        "The protein identity — supplied by our prompt",
        "Ion assignments — both on deposited water sites",
        "“T03 settled” and “refinement sound”",
    ]
    for i, t in enumerate(fails):
        out.append(
            f'  <text x="1012" y="{292 + i*38}" font-size="20" fill="{INK}">✗ {escape(t)}</text>')

    out.append(panel(80, 520, 1760, 170, WARN_LIGHT))
    out.append(
        f'  <text x="112" y="568" font-size="25" font-weight="700" fill="{WARN}">Open</text>')
    out.append(paragraph(
        112, 610,
        "Recover or re-run the round-7 model before any claim about the agent's final refinement · "
        "fix the upstream prompt · T02 has no driver · T15 needs a content figure · the T16 swapped "
        "mapping is unmeasured · geometry, waters and data quality are carried from May, not "
        "re-measured.",
        width=104, size=20, leading=29))

    out.append(panel(80, 720, 1760, 210, ACCENT_LIGHT))
    out.append(paragraph(
        112, 772,
        "The agent's largest visible failure — a headline number that did not match its own shipped "
        "model — was an artefact-packaging failure. Its real failure was accepting a protein identity "
        "the benchmark handed it without checking the coordinates. This harness made the mirror-image "
        "error: it trusted a filename for five review rounds, and nearly published the accusation.",
        width=100, size=23, color=ACCENT, weight="700", leading=33))
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------
# Driver
# ------------------------------------------------------------------
def main():
    slides = [
        ("01_title", slide_01_title),
        ("02_why", slide_02_why),
        ("03_headline", slide_03_headline),
        ("04_regrade", slide_04_regrade),
        ("05_new_tasks", slide_05_new_tasks),
        ("06_coverage", slide_06_coverage),
        ("07_findings", slide_07_findings),
        ("08_trust", slide_08_trust),
        ("09_harness", slide_09_harness),
        ("10_net", slide_10_net),
    ]
    for name, fn in slides:
        path = write_svg(name, fn())
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
