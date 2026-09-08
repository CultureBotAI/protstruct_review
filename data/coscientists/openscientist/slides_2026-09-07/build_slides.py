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
        "Headline claim re-graded against calibrated bands, not templates",
        "Three catalog tasks covered for the first time: T14, T15, T16",
        "First 1SAR sheet to meet the trust invariant without grandfathering",
    ]
    for i, b in enumerate(bullets):
        ry = 540 + i * 52
        out.append(f'  <circle cx="132" cy="{ry-7}" r="6" fill="{ACCENT}"/>')
        out.append(f'  <text x="158" y="{ry}" font-size="24" fill="{INK}">{escape(b)}</text>')

    out.append(panel(120, 800, 1680, 130, ACCENT_LIGHT))
    out.append(paragraph(
        150, 848,
        "The refinement was sound. The report was not — and the number it reported "
        "belongs to no model the agent produced.",
        width=95, size=26, color=ACCENT, weight="700", leading=34))

    out.append(
        f'  <text x="120" y="{H-70}" font-size="20" fill="{MUTED}">'
        f'openscientist artefact cdba2c07-daff-4f60-ae96-12452b3a5fbb · '
        f'protstruct_review · {DECK_DATE}</text>'
    )
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------
# 02 — What this re-run was for
# ------------------------------------------------------------------
def slide_02_why():
    out = [header("Why re-run at all",
                  "The model never changed — the instruments did")]

    out.append(paragraph(
        80, 210,
        "The May review was issued before the tolerance-benchmark series. It graded its "
        "load-bearing claim with a flat, pre-benchmark rule and read a spread across four "
        "oracles as tool disagreement. Both of those are now measured quantities.",
        width=118, size=23, color=INK, leading=34))

    rows = [
        ["May 2026", "48-round tolerance series not yet run",
         "flat “< 0.05 R-work/R-free gap” template"],
        ["Since", "Registry §3/§4/§6 bands measured and governed",
         "calibrated |Δ| bands with named preconditions"],
        ["Since", "gemmi routed through toolchain.py, pinned 0.7.5",
         "mask-radii convention made explicit"],
        ["Since", "Trust invariant enforceable (cutover 2026-08-13)",
         "cctbx-only tasks must be waived or closed"],
        ["Today", "Same artefact, five oracle code paths",
         "re-graded, plus three never-run tasks"],
    ]
    out.append(table(
        80, 350, [200, 700, 860],
        ["When", "What changed in the harness", "Effect on how 1SAR is graded"],
        rows, row_height=54, font_size=20))

    out.append(panel(80, 700, 1760, 200, WARN_LIGHT))
    out.append(paragraph(
        110, 750,
        "No-clobber was structural, not careful: outputs are date-keyed, the artefact zip was "
        "extracted read-only into a scratch directory, and all 102 pre-existing files were "
        "checksummed before and after the run. Every one is byte-identical. April and May "
        "records stand exactly as issued.",
        width=100, size=22, color=INK, leading=34))
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------
# 03 — The headline, sharpened
# ------------------------------------------------------------------
def slide_03_headline():
    out = [header("The R-free finding, sharpened",
                  "Same verdict. Much better attribution.")]

    # Three-column story
    cols = [
        ("May said", BAD, BAD_LIGHT,
         "“R-free is reproducibly ~0.21, not 0.199.” Four code paths, "
         "0.2114–0.2209. Three of four fail the < 0.05 gap criterion."),
        ("Now measured", ACCENT, ACCENT_LIGHT,
         "The agent's own model header records FREE R VALUE 0.2114. The oracle "
         "recomputes 0.2116 — agreement to 0.0002."),
        ("So the defect is", GOOD, GOOD_LIGHT,
         "in the write-up, not the refinement. The report says 0.199 in eight "
         "places; the model it describes does not."),
    ]
    for i, (title, color, fill, body) in enumerate(cols):
        cx = 80 + i * 590
        out.append(panel(cx, 200, 550, 300, fill))
        out.append(
            f'  <text x="{cx+30}" y="252" font-size="26" font-weight="700" '
            f'fill="{color}">{escape(title)}</text>')
        out.append(paragraph(cx + 30, 300, body, width=42, size=20, leading=30))

    out.append(
        f'  <text x="80" y="580" font-size="28" font-weight="700" fill="{INK}">'
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
        80, 620, [340, 200],
        ["Model in the artefact", "R-free"],
        rounds, row_height=46, font_size=20,
        cell_fills=fills, cell_text_colors=colors,
        align=["left", "right"]))

    out.append(panel(700, 620, 1140, 322, ROW_ALT))
    out.append(paragraph(
        730, 672,
        "Every round model carries its R-free in its own PDB header. Measured across all "
        "six, the range is 0.2068–0.2364. The reported 0.199 is not a stale value carried "
        "from an earlier round — it is below the best round the agent ever produced, by "
        "0.008.",
        width=68, size=22, leading=32))
    out.append(paragraph(
        730, 830,
        "This matters for how the failure is described. “Understated by ~0.012” implies a "
        "measurement disagreement. “Corresponds to no model produced” is a reporting-integrity "
        "problem, and a different thing to fix.",
        width=68, size=22, color=BAD, leading=32))
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------
# 04 — Re-graded under calibrated bands
# ------------------------------------------------------------------
def slide_04_regrade():
    out = [header("Re-graded under the current registry",
                  "One verdict flips — because the May gap was mask convention, not code")]

    rows = [
        ["R-free 0.199 vs oracle",
         "flat “< 0.05 gap”; 3 of 4 paths fail",
         "§4 recomputed-reference band |Δ| ≤ 0.01; measured 0.0126",
         "still fails"],
        ["gemmi vs PHENIX R-free",
         "0.217 vs 0.2116 (Δ 0.0054), read as disagreement",
         "§4 independent-code-path band |ΔR| ≤ 0.02, matched radii; measured +0.0020",
         "now passes"],
        ["Round 6 better than final",
         "Δ 0.0048 by oracle",
         "Δ 0.0046 from artefact headers",
         "reproduces"],
    ]
    fills = [[None, None, None, BAD_LIGHT],
             [None, None, None, GOOD_LIGHT],
             [None, None, None, WARN_LIGHT]]
    colors = [[INK, MUTED, INK, BAD],
              [INK, MUTED, INK, GOOD],
              [INK, MUTED, INK, WARN]]
    out.append(table(
        80, 200, [330, 460, 700, 270],
        ["Claim", "May grading", "2026-09-07 grading", "Verdict"],
        rows, row_height=88, font_size=18,
        cell_fills=fills, cell_text_colors=colors,
        align=["left", "left", "left", "center"]))

    out.append(
        f'  <text x="80" y="620" font-size="28" font-weight="700" fill="{INK}">'
        f'The dissolved disagreement</text>')
    out.append(paragraph(
        80, 668,
        "May measured gemmi under its default vdw mask on gemmi 0.7.4 and got 0.217. Re-run "
        "with radii matched to cctbx as the registry now requires, gemmi gives 0.2136 — a "
        "0.0034 shift. The registry records the default-vdw penalty as median +0.0043, "
        "measured over 15 entries. The May number was not wrong; it was taken under the "
        "convention the benchmark later showed to be the larger of the two effects.",
        width=118, size=22, leading=33))

    vals = [("PHENIX model_vs_data", "0.2116", ACCENT),
            ("gemmi, matched radii", "0.2136", GOOD),
            ("gemmi, default vdw (May)", "0.217", WARN),
            ("agent report", "0.199", BAD)]
    for i, (name, val, color) in enumerate(vals):
        cx = 80 + i * 440
        out.append(panel(cx, 850, 410, 110, ROW_ALT, stroke=color))
        out.append(
            f'  <text x="{cx+22}" y="892" font-size="19" fill="{INK}">{escape(name)}</text>')
        out.append(
            f'  <text x="{cx+22}" y="932" font-size="28" font-weight="700" '
            f'fill="{color}">{escape(val)}</text>')
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------
# 05 — New task coverage
# ------------------------------------------------------------------
def slide_05_new_tasks():
    out = [header("Three tasks covered for the first time",
                  "T14 hydrogen placement · T15 structural classification · T16 interface quality")]

    rows = [
        ["T14", "confident Asn/Gln/His flip-set conflicts", "0 of 14 shared", "pass"],
        ["T14", "H atoms added (Richardson reduce)", "1386", "informational"],
        ["T15", "three-state SS agreement — agent model", "0.8802", "informational"],
        ["T15", "same metric — deposited reference", "0.8646", "baseline"],
        ["T16", "DockQ vs deposited assembly", "0.9445", "pass"],
        ["T16", "CAPRI interface quality class", "High", "pass"],
        ["T16", "buried surface area, chains A/B", "437.8 Å²", "informational"],
    ]
    fills = [[ACCENT_LIGHT, None, None, GOOD_LIGHT],
             [ACCENT_LIGHT, None, None, None],
             [ACCENT_LIGHT, None, None, None],
             [ACCENT_LIGHT, None, None, None],
             [ACCENT_LIGHT, None, None, GOOD_LIGHT],
             [ACCENT_LIGHT, None, None, GOOD_LIGHT],
             [ACCENT_LIGHT, None, None, None]]
    colors = [[ACCENT, INK, INK, GOOD],
              [ACCENT, INK, INK, MUTED],
              [ACCENT, INK, INK, MUTED],
              [ACCENT, INK, INK, MUTED],
              [ACCENT, INK, INK, GOOD],
              [ACCENT, INK, INK, GOOD],
              [ACCENT, INK, INK, MUTED]]
    out.append(table(
        80, 200, [110, 720, 300, 280],
        ["Task", "Metric", "Value", "Status"],
        rows, row_height=52, font_size=20,
        cell_fills=fills, cell_text_colors=colors,
        align=["center", "left", "right", "center"]))

    notes = [
        (GOOD, "T16 applies because 1SAR's asymmetric unit carries two protein chains. The agent's "
               "A/B pairing reproduces the deposited assembly at CAPRI High — there is no PHENIX "
               "interface scorer, so this task is oracle-only by construction."),
        (ACCENT, "T14 compares two genuinely independent H builders (Richardson reduce vs "
                 "mmtbx.reduce2, add_flip_movers=True). They agree on every confident call. "
                 "phenix.reduce is the same binary as reduce, so its identical count is a "
                 "redistribution check, not a second opinion."),
        (WARN, "T15's agreement number is a property of the fold and the two algorithms, not a "
               "quality score. It is only meaningful as a difference — which is why the deposited "
               "reference was measured too. The agent model sits 0.0156 above it."),
    ]
    y = 680
    for color, text in notes:
        lines = wrap(text, 108)
        out.append(f'  <rect x="80" y="{y-24}" width="5" height="{len(lines)*30+10}" fill="{color}"/>')
        out.append(paragraph(105, y, text, width=108, size=20, leading=30))
        y += len(lines) * 30 + 34
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------
# 06 — Coverage map
# ------------------------------------------------------------------
def slide_06_coverage():
    out = [header("Coverage on the example structure",
                  "Where the harness has actually been pointed at 1SAR")]

    groups = [
        ("Covered in May", GOOD, GOOD_LIGHT,
         ["T01 superposition", "T03 X-ray refinement", "T05 geometry",
          "T06 model-vs-data", "T07 map/model", "T10 ligand/site", "T13 data quality"]),
        ("Covered today", ACCENT, ACCENT_LIGHT,
         ["T14 hydrogen placement", "T15 structural classification",
          "T16 interface quality"]),
        ("Not applicable", MUTED, ROW_ALT,
         ["T09 molecular replacement — the model was already placed",
          "T11 loop fitting — no chain gaps (A 1–96, B 1–96)"]),
        ("Still uncovered", BAD, BAD_LIGHT,
         ["T02 per-residue comparison — blocked, see next slide"]),
    ]
    y = 190
    for title, color, fill, items in groups:
        h = 54 + len(items) * 32
        out.append(panel(80, y, 1760, h, fill))
        out.append(
            f'  <text x="110" y="{y+38}" font-size="26" font-weight="700" '
            f'fill="{color}">{escape(title)}</text>')
        for i, item in enumerate(items):
            iy = y + 70 + i * 32
            out.append(f'  <circle cx="122" cy="{iy-7}" r="5" fill="{color}"/>')
            out.append(
                f'  <text x="146" y="{iy}" font-size="21" fill="{INK}">{escape(item)}</text>')
        y += h + 18

    out.append(paragraph(
        80, y + 30,
        "13 of 17 catalog tasks are now settled on this structure: 10 measured, 2 ruled "
        "not applicable with a stated reason, 1 blocked by tooling.",
        width=118, size=22, color=ACCENT, weight="700", leading=32))
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------
# 07 — Two new findings
# ------------------------------------------------------------------
def slide_07_findings():
    out = [header("Two findings the May run did not have",
                  "One about the model, one about the harness")]

    out.append(panel(80, 200, 860, 400, BAD_LIGHT))
    out.append(
        f'  <text x="112" y="252" font-size="28" font-weight="700" fill="{BAD}">'
        f'1 · SO4 A 97 is written as ATOM</text>')
    out.append(paragraph(
        112, 300,
        "The deposition writes the sulfate as HETATM; the agent's final model writes it as "
        "ATOM. Not cosmetic: a parser that treats ATOM as polymer counts chain A as 97 "
        "residues instead of 96. That happened during this run, with gemmi, before the cause "
        "was identified.",
        width=62, size=21, leading=31))
    out.append(paragraph(
        112, 470,
        "Related and also new: the agent placed CA A 98 and NA B 98 — both correctly HETATM, "
        "and both absent from the deposition, which contains only the sulfate. May assessed "
        "their identity; it did not record that neither is in the reference at all.",
        width=62, size=21, color=INK, leading=31))

    out.append(panel(980, 200, 860, 400, WARN_LIGHT))
    out.append(
        f'  <text x="1012" y="252" font-size="28" font-weight="700" fill="{WARN}">'
        f'2 · T02 has no headless path</text>')
    out.append(paragraph(
        1012, 300,
        "T02's catalog PHENIX tool, phenix.structure_comparison, is GUI-only in PHENIX 2.0. "
        "Its source carries the comment “launches Stucture Comparision GUI by itself, still "
        "requires project”. Run headlessly it exits 1 with no output — and raises a project "
        "dialog on the user's desktop.",
        width=62, size=21, leading=31))
    out.append(paragraph(
        1012, 470,
        "ProSMART, the CCP4 oracle the catalog names for T02, is not installed here. So T02 "
        "is not currently satisfiable on this machine by any route the catalog lists.",
        width=62, size=21, leading=31))

    out.append(panel(80, 640, 1760, 300, ROW_ALT))
    out.append(
        f'  <text x="112" y="692" font-size="26" font-weight="700" fill="{INK}">'
        f'What the gate caught, unprompted</text>')
    out.append(paragraph(
        112, 740,
        "The hermetic gate rejected this run's first record because four oracle_tool_ref values "
        "did not resolve against ref/catalog.yaml — including a combined “reduce vs "
        "mmtbx.reduce2” label. The refs were corrected to registered ids. The underlying gap is "
        "real and now filed: mmtbx.reduce2 is a dependency of bench_t14_flip_sets.py but is not "
        "a registered tool, so no T14 record can name the builder that produced its second "
        "opinion.",
        width=108, size=21, leading=31))
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------
# 08 — Trust invariant
# ------------------------------------------------------------------
def slide_08_trust():
    out = [header("Trust invariant: closed on merit",
                  "The first 1SAR sheet that needs no grandfathering")]

    out.append(paragraph(
        80, 210,
        "The trust model forbids grading PHENIX solely with PHENIX. Since the 2026-08-13 "
        "cutover that is enforced: a sheet carrying a cctbx-only task must either waive it "
        "explicitly or close it with an independent oracle. Sheets issued before the cutover "
        "are grandfathered and listed by name — history is history.",
        width=118, size=23, leading=34))

    rows = [
        ["QDS_1sar…2026-04-24", "T06", "open — cctbx only", "grandfathered"],
        ["QDS_1sar…2026-04-26", "T06, T13", "open — cctbx only", "grandfathered"],
        ["QDS_1sar…2026-04-30", "T06, T13", "open — cctbx only", "grandfathered"],
        ["QDS_1sar…2026-05-01", "T06, T13", "open — cctbx only", "grandfathered"],
        ["QDS_1sar…2026-05-04", "T06", "open — cctbx only", "grandfathered"],
        ["QDS_1sar…2026-05-05", "T06", "open — cctbx only", "grandfathered"],
        ["QDS_1sar…2026-09-07", "T03", "closed", "satisfied"],
        ["QDS_1sar…2026-09-07", "T14, T15, T16", "non-cctbx only", "satisfied"],
    ]
    fills = [[None, None, WARN_LIGHT, WARN_LIGHT] for _ in range(6)] + \
            [[None, None, GOOD_LIGHT, GOOD_LIGHT] for _ in range(2)]
    colors = [[INK, INK, WARN, WARN] for _ in range(6)] + \
             [[INK, INK, GOOD, GOOD] for _ in range(2)]
    out.append(table(
        80, 370, [460, 340, 480, 380],
        ["Sheet", "Tasks", "Gap status", "Invariant"],
        rows, row_height=48, font_size=20,
        cell_fills=fills, cell_text_colors=colors,
        align=["left", "left", "left", "center"]))

    out.append(panel(80, 830, 1760, 110, GOOD_LIGHT))
    out.append(paragraph(
        110, 878,
        "Today's sheet carries no open cctbx-only row and needs no waiver: T03 has both a "
        "cctbx and a non-cctbx R path; T14, T15 and T16 are non-cctbx throughout.",
        width=104, size=22, color=GOOD, weight="700", leading=32))
    return "\n".join(out) + "\n"


# ------------------------------------------------------------------
# 09 — The harness since May
# ------------------------------------------------------------------
def slide_09_harness():
    out = [header("The harness since May",
                  "Why the same artefact grades differently now")]

    items = [
        ("48-round tolerance series", ACCENT,
         "Every [template] threshold that mattered here replaced by a measured band with "
         "stated preconditions — including the R offset that dissolved the May gemmi gap."),
        ("Negative-control track", GOOD,
         "0 of 22 false verdicts on the control set; agents 21/21; the 2VXN case attributed "
         "and stood down rather than quietly dropped."),
        ("Gate consolidation", ACCENT,
         "Negative-control headlines, governed thresholds and round-count claims are now data "
         "checked by the gate, not prose the gate hopes someone re-read."),
        ("Toolchain routing", MUTED,
         "gemmi pinned at 0.7.5 and routed through toolchain.py — which is how this run knew "
         "the May legs had run under 0.7.4, and could say so."),
        ("Transfer, CI, licensing", MUTED,
         "Repository public under CultureBotAI with CI green; BSD-3-Clause code, CC-BY-4.0 "
         "docs and records."),
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
                  "What holds, what fails, what is still open")]

    out.append(panel(80, 200, 860, 330, GOOD_LIGHT))
    out.append(
        f'  <text x="112" y="252" font-size="28" font-weight="700" fill="{GOOD}">Holds</text>')
    holds = [
        "The refinement is a real, large improvement",
        "Geometry, waters, disulfides, ion identity defensible",
        "A/B interface reproduces the deposition (CAPRI High)",
        "Both H builders agree on every confident flip",
        "SS agreement at the deposited baseline",
        "Oracle R-free reproduces May to four decimals",
    ]
    for i, t in enumerate(holds):
        out.append(
            f'  <text x="112" y="{300 + i*38}" font-size="20" fill="{INK}">'
            f'✓ {escape(t)}</text>')

    out.append(panel(980, 200, 860, 330, BAD_LIGHT))
    out.append(
        f'  <text x="1012" y="252" font-size="28" font-weight="700" fill="{BAD}">Fails</text>')
    fails = [
        "Reported R-free 0.199 matches no model produced",
        "…and no round: best was 0.2068 (round 6)",
        "The shipped final is not the best round",
        "SO4 written as ATOM, not HETATM",
    ]
    for i, t in enumerate(fails):
        out.append(
            f'  <text x="1012" y="{300 + i*38}" font-size="20" fill="{INK}">'
            f'✗ {escape(t)}</text>')

    out.append(panel(80, 570, 1760, 150, WARN_LIGHT))
    out.append(
        f'  <text x="112" y="618" font-size="26" font-weight="700" fill="{WARN}">Open</text>')
    out.append(paragraph(
        112, 660,
        "T02 blocked on tooling · mmtbx.reduce2 unregistered in the catalog · the T05 rmsz legs "
        "still carry their disclosed gemmi 0.7.4 measurement and have not been re-run under 0.7.5.",
        width=104, size=21, leading=30))

    out.append(panel(80, 760, 1760, 180, ACCENT_LIGHT))
    out.append(paragraph(
        112, 812,
        "The one failing claim is unchanged in verdict and clearer in cause. Five code paths now "
        "bracket R-free at 0.2114–0.2136 once mask conventions are matched. The gap is not "
        "between oracles, and not between the oracle and the model — it is between the model and "
        "the report written about it.",
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
