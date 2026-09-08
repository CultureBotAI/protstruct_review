#!/usr/bin/env python3
"""
Generate landscape SVG slides for the 2026-09-07 1SAR update deck.

This is an *update* deck: it assumes the 2026-05-05 deck as the prior state and
covers what changed since — the re-measurement under calibrated registry bands,
three newly covered catalog tasks, and the harness work that happened in between.

Self-contained by convention (see the sibling slides_2026-05-0{4,5} directories):
all data is hardcoded here, so the deck rebuilds byte-identically without the
artefact, the oracles, or the repository's runtime.

Output dimensions: 1920 x 1080 (16:9 landscape).
No external Python deps; SVG is built as text. rsvg-convert merges to PDF:

    python3 build_slides.py
    rsvg-convert -f pdf -o 1SAR_update_slides_2026-09-07.pdf svg/*.svg
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
        f'1SAR refinement review · openscientist artefact cdba2c07 · re-run {REVIEW_DATE}</text>'
    )
    out.append(
        f'  <text x="{W-80}" y="{H-30}" font-size="16" fill="{MUTED}" text-anchor="end">'
        f'protstruct_review · update deck {DECK_DATE}</text>'
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
def slide_01_title():
    out = [f'  <rect x="0" y="0" width="{W}" height="6" fill="{ACCENT}"/>']
    out.append(
        f'  <text x="120" y="330" font-size="72" font-weight="700" fill="{INK}">'
        f'1SAR refinement review</text>'
    )
    out.append(
        f'  <text x="120" y="410" font-size="46" font-weight="400" fill="{ACCENT}">'
        f'Update: what changed since {PRIOR_DATE}</text>'
    )
    out.append(
        f'  <line x1="120" y1="470" x2="820" y2="470" stroke="{ACCENT}" stroke-width="3"/>'
    )

    bullets = [
        "Same artefact, re-measured: every prior record left byte-identical",
        "R-free has no governing criterion here — the 1990 deposition records no R-free",
        "T14, T15 and T16 exercised on this artefact for the first time",
        "Partial re-run — T01/T05/T06/T10/T13 carried from May, not re-measured",
    ]
    for i, b in enumerate(bullets):
        ry = 540 + i * 52
        out.append(f'  <circle cx="132" cy="{ry-7}" r="6" fill="{ACCENT}"/>')
        out.append(f'  <text x="158" y="{ry}" font-size="24" fill="{INK}">{escape(b)}</text>')

    out.append(panel(120, 790, 1680, 145, ACCENT_LIGHT))
    out.append(paragraph(
        150, 840,
        "The refinement was sound. The report was not — it is written about a different "
        "protein, and its headline R-free belongs to no model the agent produced.",
        width=88, size=26, color=ACCENT, weight="700", leading=36))

    out.append(
        f'  <text x="120" y="{H-70}" font-size="20" fill="{MUTED}">'
        f'openscientist artefact cdba2c07-daff-4f60-ae96-12452b3a5fbb · '
        f'protstruct_review · {DECK_DATE}</text>'
    )
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------
# 02 — Scope of this re-run
# ------------------------------------------------------------------
def slide_02_why():
    out = [header("What this re-run covers",
                  "A partial re-measurement — read the scope before the headline")]

    out.append(paragraph(
        80, 205,
        "The May review predates the tolerance-benchmark series and graded its headline with a "
        "flat rule. This run re-measures the R-factor claims against the rules T03 declares — and "
        "finds the R-free rule cannot be applied to this structure at all — then exercises three "
        "never-run tasks. It does not re-run everything.",
        width=118, size=22, color=INK, leading=32))

    rows = [
        ["Re-measured here", "T03 (two code paths), T14, T15, T16",
         "graded against the current registry and driver rubric"],
        ["Carried from May", "T01, T05, T06, T10, T13",
         "geometry, waters, disulfides, ligands, ions, data quality"],
    ]
    fills = [[GOOD_LIGHT, None, None], [WARN_LIGHT, None, None]]
    colors = [[GOOD, INK, MUTED], [WARN, INK, MUTED]]
    out.append(table(
        80, 320, [330, 620, 810],
        ["Scope", "Tasks", "What that means"],
        rows, row_height=64, font_size=20,
        cell_fills=fills, cell_text_colors=colors))

    out.append(paragraph(
        80, 555,
        "Every conclusion about geometry, water placement, disulfides and ion identity in this "
        "deck is May's, not re-measured today. QDS_1sar_cdba2c07_2026-05-05.yaml remains the "
        "sheet of record for anything outside T03, T14, T15 and T16.",
        width=112, size=22, color=WARN, weight="700", leading=32))

    out.append(panel(80, 655, 1760, 170, ACCENT_LIGHT))
    out.append(paragraph(
        110, 703,
        "No-clobber was structural, not careful: outputs are date-keyed, the artefact zip was "
        "extracted read-only into a scratch directory, and all 102 pre-existing files were "
        "checksummed before and after. Every one is byte-identical.",
        width=100, size=22, color=INK, leading=32))

    out.append(panel(80, 845, 1760, 120, ROW_ALT))
    out.append(paragraph(
        110, 889,
        "Cost of that choice: this run issues a new dated .yaml where May updated the canonical "
        "one in place, so the current sheet is 274 lines against May's 1270. That is a new "
        "convention adopted here, not an existing one followed.",
        width=104, size=20, color=MUTED, leading=30))
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------
# 03 — The headline, sharpened
# ------------------------------------------------------------------
def slide_03_headline():
    out = [header("The R-free number, sharpened",
                  "The refinement agrees with the oracle; the report does not")]

    cols = [
        ("May said", BAD, BAD_LIGHT,
         "“R-free is reproducibly ~0.21, not 0.199.” Four code paths, "
         "0.2116–0.2209, read as convergent corroboration."),
        ("Now measured", ACCENT, ACCENT_LIGHT,
         "The agent's own model header records FREE R VALUE 0.2114. The oracle "
         "recomputes 0.2116 — agreement to 0.0002."),
        ("So the defect is", GOOD, GOOD_LIGHT,
         "in the write-up, not the refinement. The report says 0.199 in seven "
         "places; the model it describes does not."),
    ]
    for i, (title, color, fill, body) in enumerate(cols):
        cx = 80 + i * 590
        out.append(panel(cx, 195, 550, 290, fill))
        out.append(
            f'  <text x="{cx+30}" y="245" font-size="26" font-weight="700" '
            f'fill="{color}">{escape(title)}</text>')
        out.append(paragraph(cx + 30, 292, body, width=42, size=20, leading=30))

    out.append(
        f'  <text x="80" y="565" font-size="28" font-weight="700" fill="{INK}">'
        f'Where does 0.199 come from? No round the agent ran.</text>')

    rounds = [
        ["1sar_refined", "0.2364"], ["round 2", "0.2293"], ["round 3", "0.2165"],
        ["final (shipped)", "0.2114"], ["round 5", "0.2109"], ["round 6", "0.2068"],
        ["report claim", "0.199"],
    ]
    fills = [[None, None] for _ in rounds]
    colors = [[INK, INK] for _ in rounds]
    fills[3] = [ACCENT_LIGHT, ACCENT_LIGHT]
    fills[5] = [GOOD_LIGHT, GOOD_LIGHT]
    fills[6] = [BAD_LIGHT, BAD_LIGHT]
    colors[6] = [BAD, BAD]
    out.append(table(
        80, 605, [340, 200],
        ["Model in the artefact", "R-free"],
        rounds, row_height=44, font_size=20,
        cell_fills=fills, cell_text_colors=colors,
        align=["left", "right"]))

    out.append(panel(700, 605, 1140, 308, ROW_ALT))
    out.append(paragraph(
        730, 655,
        "Every round model carries its R-free in its own PDB header, and where the oracle was "
        "re-run it agrees with the header. The range is 0.2068–0.2364. The reported 0.199 is "
        "below the best round the agent ever produced, by 0.008.",
        width=68, size=21, leading=30))
    out.append(paragraph(
        730, 790,
        "“Understated by ~0.012” implies a measurement disagreement. “Corresponds to no model "
        "produced” is a reporting-integrity problem, and a different thing to fix.",
        width=68, size=21, color=BAD, leading=30))
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------
# 04 — Re-graded against the driver's own rule
# ------------------------------------------------------------------
def slide_04_regrade():
    out = [header("The R-free claim has no governing criterion",
                  "1SAR was deposited in 1990 and its REMARK 3 records FREE R VALUE : NULL — rule 1 has no reference to compare against")]

    rows = [
        ["R-free value, 0.199 vs 0.2116",
         "all four May paths sat above 0.199",
         "rule 1 inapplicable — no deposited R-free",
         "no criterion"],
        ["R-work/R-free gap < 0.05",
         "0.0552 / 0.0526 / 0.0504 / 0.0435 (“3 of 4 fail”)",
         "0.0552 PHENIX, 0.0515 gemmi",
         "still fails"],
        ["R offset, rule 2 (R-WORK)",
         "not graded as such",
         "gemmi 0.1622 vs PHENIX 0.1564 = +0.0058",
         "passes"],
        ["Round 6 better than final",
         "Δ 0.0048 by oracle",
         "Δ 0.0048, same instrument",
         "reproduces exactly"],
    ]
    # SVG text has no wrapping; flatten the embedded newlines.
    rows = [[c.replace("\n", " ") for c in r] for r in rows]
    fills = [[None, None, None, WARN_LIGHT],
             [None, None, None, BAD_LIGHT],
             [None, None, None, GOOD_LIGHT],
             [None, None, None, GOOD_LIGHT]]
    colors = [[INK, MUTED, INK, WARN],
              [INK, MUTED, INK, BAD],
              [INK, MUTED, INK, GOOD],
              [INK, MUTED, INK, GOOD]]
    out.append(table(
        80, 195, [360, 520, 540, 340],
        ["Claim", "What May actually graded", "2026-09-07 grading", "Verdict"],
        rows, row_height=72, font_size=17,
        cell_fills=fills, cell_text_colors=colors,
        align=["left", "left", "left", "center"]))

    out.append(
        f'  <text x="80" y="600" font-size="26" font-weight="700" fill="{INK}">'
        f'What the independent code path did — and did not — settle</text>')
    out.append(paragraph(
        80, 644,
        "Re-run with mask radii matched to cctbx, gemmi 0.7.5 gives R-free 0.2136 against PHENIX's "
        "0.2116 — Δ +0.0020, inside the ± 0.02 band. That settles the gemmi leg only. May's spread "
        "was 0.2116–0.2209 and its upper bound was Servalcat, which was not re-run and is not "
        "retracted; REFMAC5 likewise stands. Across every source the widest range recorded is "
        "0.2114–0.2209 — but that lower bound is the model's own PDB header, not a code path.",
        width=116, size=21, leading=31))

    out.append(panel(80, 800, 1760, 140, WARN_LIGHT))
    out.append(paragraph(
        110, 846,
        "Two cautions: the shift from May's gemmi number is confounded three ways (mask radii, "
        "version, and #316's work-only scale fit), not one. And the 0.005–0.015 expectation is "
        "about R-WORK, not R-free: measured correctly that offset is +0.0058 and in band. No "
        "benchmarked R-free offset band exists.",
        width=104, size=21, color=INK, leading=31))
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------
# 05 — Newly exercised tasks
# ------------------------------------------------------------------
def slide_05_new_tasks():
    out = [header("Three tasks exercised on this artefact",
                  "T14 hydrogen placement · T15 structural classification · T16 interface quality")]

    rows = [
        ["T14", "flippable Asn/Gln/His scored — reduce / reduce2", "14 / 18", "0 conflicts"],
        ["T14", "H atoms added (Richardson reduce)", "1386", "band void"],
        ["T15", "three-state SS agreement — agent model", "0.8802", "uninterpretable"],
        ["T15", "same metric — deposited reference", "0.8646", "reproduces calibration"],
        ["T16", "DockQ vs deposited, AB:AB", "0.9445", "low information"],
        ["T16", "CAPRI interface quality class", "High", "low information"],
        ["T16", "buried surface area, chains A/B", "437.8 Å²", "informational"],
    ]
    fills = [[ACCENT_LIGHT, None, None, GOOD_LIGHT],
             [ACCENT_LIGHT, None, None, ROW_ALT],
             [ACCENT_LIGHT, None, None, WARN_LIGHT],
             [ACCENT_LIGHT, None, None, GOOD_LIGHT],
             [ACCENT_LIGHT, None, None, ROW_ALT],
             [ACCENT_LIGHT, None, None, ROW_ALT],
             [ACCENT_LIGHT, None, None, ROW_ALT]]
    colors = [[ACCENT, INK, INK, GOOD],
              [ACCENT, INK, INK, MUTED],
              [ACCENT, INK, INK, WARN],
              [ACCENT, INK, INK, GOOD],
              [ACCENT, INK, INK, MUTED],
              [ACCENT, INK, INK, MUTED],
              [ACCENT, INK, INK, MUTED]]
    out.append(table(
        80, 190, [110, 700, 300, 340],
        ["Task", "Metric", "Value", "Reading"],
        rows, row_height=50, font_size=19,
        cell_fills=fills, cell_text_colors=colors,
        align=["center", "left", "right", "center"]))

    notes = [
        (WARN, "T15 is NOT a pass. The registry gates on secondary-structure CONTENT (DSSP H+E "
               "≥ 0.20), not on agreement, because agreement is degenerate at the bad end — noise "
               "raises it. The driver does not compute content, so the governed gate could not be "
               "applied. 0.8802 is above every one of the 16 benchmark entries (0.679–0.850), and "
               "1SAR is β-containing where the benchmark expects 0.68–0.72. A flag, not comfort."),
        (WARN, "T16 exercises the path; it does not certify an assembly. structural_criteria.yaml "
               "already classifies this contact as 1SAR's crystallographic dimer — a demonstration, "
               "not a biological assembly. With a 0.41 Å start-to-final Cα RMSD a high DockQ is "
               "near-guaranteed. Only the AB:AB mapping was scored; the swap is unmeasured."),
        (GOOD, "T14 compares two genuinely independent builders (Richardson reduce, non-cctbx; "
               "mmtbx.reduce2, cctbx). Zero confident conflicts over the 14 shared residues. The "
               "H-count band is void here because the model carries SO4, CA and NA."),
    ]
    y = 630
    for color, text in notes:
        lines = wrap(text, 112)
        out.append(f'  <rect x="80" y="{y-22}" width="5" height="{len(lines)*28+8}" fill="{color}"/>')
        out.append(paragraph(105, y, text, width=112, size=19, leading=28))
        y += len(lines) * 28 + 26
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------
# 06 — Coverage map
# ------------------------------------------------------------------
def slide_06_coverage():
    out = [header("Coverage on the example structure",
                  "9 tasks measured · 16 of 17 settled · 1 uncovered")]

    groups = [
        ("Measured — May, carried into this deck", WARN, WARN_LIGHT,
         ["T01 superposition", "T05 geometry", "T06 model-vs-data",
          "T10 ligand/site", "T13 data quality"]),
        ("Measured — this run", ACCENT, ACCENT_LIGHT,
         ["T03 X-ray refinement (re-measured, two code paths)",
          "T14 hydrogen placement", "T15 structural classification",
          "T16 interface quality"]),
        ("Not applicable", MUTED, ROW_ALT,
         ["T04 real-space refinement · T07 predicted-model processing · T08 docking into a map · "
          "T12 cryo-EM map quality · T17 NMR ensembles — none apply to an X-ray artefact",
          "T09 molecular replacement — the model was already placed",
          "T11 loop fitting — no chain gaps (A 1–96, B 1–96)"]),
        ("Uncovered", BAD, BAD_LIGHT,
         ["T02 per-residue comparison — no driver written; see next slide"]),
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
            out.append(
                f'  <text x="146" y="{iy}" font-size="20" fill="{INK}">{escape(item)}</text>')
        y += h + 18

    out.append(paragraph(
        80, y + 34,
        "An earlier draft of this deck listed T07 as covered in May. It never has been — the "
        "canonical eval carries zero T07 rows, and T07 is predicted-model processing.",
        width=118, size=21, color=MUTED, leading=30))
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------
# 07 — Findings
# ------------------------------------------------------------------
def slide_07_findings():
    out = [header("Three findings the May run did not have",
                  "The first one is bigger than the R-free number")]

    out.append(panel(80, 185, 1760, 300, BAD_LIGHT))
    out.append(
        f'  <text x="112" y="235" font-size="30" font-weight="700" fill="{BAD}">'
        f'1 · The report is about the wrong protein</text>')
    out.append(paragraph(
        112, 285,
        "The artefact's final report calls 1SAR staphylococcal nuclease (SNase) — in its title, "
        "summary and discussion, 27 times. 1SAR is ribonuclease Sa from Streptomyces "
        "aureofaciens; the deposited TITLE says so. RNase Sa is 96 residues, SNase is 149.",
        width=108, size=21, leading=30))
    out.append(paragraph(
        112, 385,
        "Not a naming slip: the entire Ca²⁺ justification rests on it — “the known SNase "
        "metal-binding pocket near Asp33”, and citations to two genuine SNase papers offered as "
        "the reference for this structure's coordination. So “the ion decisions remain "
        "defensible” cannot be asserted, and this deck does not assert it.",
        width=108, size=21, color=BAD, leading=30))

    out.append(panel(80, 515, 860, 300, WARN_LIGHT))
    out.append(
        f'  <text x="112" y="563" font-size="26" font-weight="700" fill="{WARN}">'
        f'2 · SO4 A 97 is written as ATOM</text>')
    out.append(paragraph(
        112, 610,
        "The deposition writes the sulfate as HETATM; the agent's model writes it as ATOM. A "
        "parser treating ATOM as polymer counts chain A as 97 residues instead of 96 — which "
        "happened with gemmi during this run. The agent also placed CA A 98 and NA B 98, both "
        "absent from the deposition.",
        width=62, size=20, leading=29))

    out.append(panel(980, 515, 860, 300, ROW_ALT))
    out.append(
        f'  <text x="1012" y="563" font-size="26" font-weight="700" fill="{ACCENT}">'
        f'3 · T02 has no headless PHENIX tool</text>')
    out.append(paragraph(
        1012, 610,
        "phenix.structure_comparison is GUI-only in PHENIX 2.0 — run headlessly it exits 1 with "
        "no output and raises a project dialog. But T02 is blocked on that tool ONLY: ProSMART "
        "ships with the documented CCP4 install and May ran it on this structure, and gemmi is "
        "listed as a T02 oracle too. The gap is a missing driver, not missing tooling.",
        width=62, size=20, leading=29))

    out.append(panel(80, 845, 1760, 95, ROW_ALT))
    out.append(paragraph(
        110, 890,
        "An earlier draft of this deck claimed ProSMART was not installed. That was wrong — the "
        "check was run without sourcing the CCP4 environment. Corrected above.",
        width=108, size=20, color=MUTED, leading=30))
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------
# 08 — Trust invariant
# ------------------------------------------------------------------
def slide_08_trust():
    out = [header("Trust invariant: passes, by omission",
                  "Worth stating plainly rather than claiming a win")]

    out.append(paragraph(
        80, 200,
        "The trust model forbids grading PHENIX solely with PHENIX. Since the 2026-08-13 cutover "
        "a sheet carrying a cctbx-only task must waive it explicitly or close it with an "
        "independent oracle. Sheets issued before the cutover are grandfathered and listed by name.",
        width=118, size=22, leading=32))

    rows = [
        ["QDS_1sar…04-24 through 05-05", "T06 (and T13 on three sheets)",
         "open — cctbx only", "grandfathered"],
        ["QDS_1sar…2026-09-07", "T03, T14", "closed", "satisfied"],
        ["QDS_1sar…2026-09-07", "T15, T16", "non-cctbx only", "satisfied"],
    ]
    fills = [[None, None, WARN_LIGHT, WARN_LIGHT],
             [None, None, GOOD_LIGHT, GOOD_LIGHT],
             [None, None, GOOD_LIGHT, GOOD_LIGHT]]
    colors = [[INK, INK, WARN, WARN],
              [INK, INK, GOOD, GOOD],
              [INK, INK, GOOD, GOOD]]
    out.append(table(
        80, 340, [500, 460, 420, 380],
        ["Sheet", "Tasks", "Gap status", "Invariant"],
        rows, row_height=56, font_size=20,
        cell_fills=fills, cell_text_colors=colors,
        align=["left", "left", "left", "center"]))

    out.append(panel(80, 590, 1760, 190, WARN_LIGHT))
    out.append(paragraph(
        110, 640,
        "The new sheet passes because it does not grade T06 — the row that was open on every "
        "prior 1SAR sheet — since this run did not re-measure T06. Nothing that was open was "
        "closed. The sheet is 274 lines where May's was 1270, and no longer carries geometry, "
        "data quality, ions, waters or pairwise comparisons.",
        width=104, size=21, color=INK, leading=31))

    out.append(panel(80, 810, 1760, 130, GOOD_LIGHT))
    out.append(paragraph(
        110, 858,
        "What did genuinely improve: mmtbx.reduce2 is now a registered tool. It was a dependency "
        "of the T14 benchmark but had never been in the catalog, so until now no T14 record could "
        "name the builder that produced its second opinion.",
        width=104, size=21, color=GOOD, leading=31))
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------
# 09 — The harness since May
# ------------------------------------------------------------------
def slide_09_harness():
    out = [header("The harness since May",
                  "Why the same artefact grades differently now")]

    items = [
        ("48-round tolerance series", ACCENT,
         "Every [template] threshold that mattered here replaced by a measured band with stated "
         "preconditions — including the R offset that scoped the gemmi comparison."),
        ("Negative-control track", GOOD,
         "0 of 22 false verdicts on the control set. Separately, 21 of 21 agent cases judged — a "
         "different denominator, since 6XVM was never judged."),
        ("Gate consolidation", ACCENT,
         "Negative-control headlines, governed thresholds and round-count claims are now data "
         "checked by the gate, not prose the gate hopes someone re-read."),
        ("Toolchain routing", MUTED,
         "gemmi pinned at 0.7.5 and routed through toolchain.py, so a run can state which binary "
         "produced a number instead of inferring it."),
        ("Transfer, CI, licensing", MUTED,
         "Repository public under CultureBotAI with CI green — achieved by the transfer, which "
         "escaped a personal-account Actions billing lock. BSD-3-Clause code, CC-BY-4.0 docs."),
    ]
    y = 205
    for title, color, body in items:
        lines = wrap(body, 104)
        h = 42 + len(lines) * 28
        out.append(f'  <rect x="80" y="{y}" width="6" height="{h}" fill="{color}"/>')
        out.append(
            f'  <text x="110" y="{y+28}" font-size="24" font-weight="700" '
            f'fill="{color}">{escape(title)}</text>')
        out.append(paragraph(110, y + 62, body, width=104, size=20, leading=28))
        y += h + 28
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------
# 10 — Net assessment
# ------------------------------------------------------------------
def slide_10_net():
    out = [header("Net assessment",
                  "What holds, what fails, what is still open")]

    out.append(panel(80, 190, 860, 320, GOOD_LIGHT))
    out.append(
        f'  <text x="112" y="240" font-size="28" font-weight="700" fill="{GOOD}">'
        f'Holds (re-measured)</text>')
    holds = [
        "Oracle R-free reproduces May to four decimals",
        "Rule 2's R-work offset passes at +0.0058",
        "Both H builders agree on every confident flip",
        "Deposited T15 leg reproduces its calibration exactly",
        "Round-6-vs-final delta reproduces exactly",
    ]
    for i, t in enumerate(holds):
        out.append(
            f'  <text x="112" y="{292 + i*40}" font-size="20" fill="{INK}">'
            f'✓ {escape(t)}</text>')

    out.append(panel(980, 190, 860, 320, BAD_LIGHT))
    out.append(
        f'  <text x="1012" y="240" font-size="28" font-weight="700" fill="{BAD}">Fails</text>')
    fails = [
        "The report describes the wrong protein",
        "…so the stated basis for the Ca²⁺ call is void",
        "Reported R-free 0.199 matches no model produced",
        "The shipped final is not the best round",
        "SO4 written as ATOM, not HETATM",
    ]
    for i, t in enumerate(fails):
        out.append(
            f'  <text x="1012" y="{292 + i*40}" font-size="20" fill="{INK}">'
            f'✗ {escape(t)}</text>')

    out.append(panel(80, 540, 1760, 180, WARN_LIGHT))
    out.append(
        f'  <text x="112" y="588" font-size="26" font-weight="700" fill="{WARN}">'
        f'Open</text>')
    out.append(paragraph(
        112, 630,
        "T02 has no driver · T15 needs a secondary-structure content figure before its number "
        "means anything · the T16 swapped chain mapping is unmeasured · REFMAC5 and Servalcat "
        "R-free legs were not re-run · geometry, waters, ions and data quality are carried from "
        "May, not re-measured.",
        width=104, size=21, leading=30))

    out.append(panel(80, 750, 1760, 190, ACCENT_LIGHT))
    out.append(paragraph(
        112, 800,
        "The one R-factor rule that is satisfiable on this structure — rule 2's independent-code-"
        "path R-work offset — passes at +0.0058. The R-free claim has no governing criterion at "
        "all. What does not pass is the write-up: a headline number that describes no model in "
        "the artefact, and a report written about a different protein than the one it refined.",
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
