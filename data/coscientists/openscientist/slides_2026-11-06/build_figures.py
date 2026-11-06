#!/usr/bin/env python3
"""Deterministic figure and manifest builder for slides_2026-11-06.

Reads only committed Git blobs at SOURCE_REVISION (f3cfad326f28ddbf652dcdb0c5858443bee6e413)
without invoking external scientific binaries, network calls, or untracked caches.
Generates all seven PNG figures (3328 x 1360 px = 2x of 1664 x 680 logical slide canvas)
and writes figures.json with full provenance, SHA-256 digests, selectors, and derived summaries.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
from pathlib import Path
import re
import statistics
import subprocess
import tempfile
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.text import Text
from matplotlib.transforms import Bbox
import numpy as np
from PIL import Image
import yaml

DECK_DIR = Path(__file__).resolve().parent
REPO_ROOT = DECK_DIR.parents[3]
SOURCE_REVISION = "f3cfad326f28ddbf652dcdb0c5858443bee6e413"

# Canvas specification: logical 1664 x 680 at 1x -> rendered at 2x = 3328 x 1360 px
LOGICAL_WIDTH_PX = 1664
LOGICAL_HEIGHT_PX = 680
RENDER_SCALE = 2
DPI = 200
FIGSIZE_IN = (LOGICAL_WIDTH_PX / 100.0, LOGICAL_HEIGHT_PX / 100.0)  # (16.64, 6.80)
EXPECTED_PNG_SIZE = (
    LOGICAL_WIDTH_PX * RENDER_SCALE,
    LOGICAL_HEIGHT_PX * RENDER_SCALE,
)  # (3328, 1360)

# Palette (Okabe-Ito fixed tool mapping + slide theme)
BG_COLOR = "#fbfbf8"
PANEL_BG = "#f4f4ee"
INK_COLOR = "#1a1a2e"
MUTED_COLOR = "#5a6071"
ACCENT_COLOR = "#1f4e8c"
GRID_COLOR = "#d8dad3"

COLOR_PHENIX = "#0072B2"
COLOR_PHENIX_LIGHT = "#7fbce0"
COLOR_GEMMI = "#E69F00"
COLOR_REFMAC = "#009E73"
COLOR_REFMAC_LIGHT = "#7fd1b9"
COLOR_WWPDB = "#CC79A7"
COLOR_COHORT = "#1a1a2e"
COLOR_ALERT = "#b23a22"

# Shared y-axis limits for all three ΔR-free figures (covers min -0.0122 through max +0.0324)
DELTA_RFREE_YLIM = (-0.016, 0.036)


def configure_matplotlib() -> None:
    """Configure Matplotlib to use bundled DejaVu Sans and >=24px logical text sizes."""
    # At 100 logical px per inch, 18.0 pt = 18 * (100 / 72) = 25.0 px at 1x (50.0 px at 2x).
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.sans-serif": ["DejaVu Sans"],
            "font.size": 18.0,
            "axes.titlesize": 19.0,
            "axes.titleweight": "bold",
            "axes.labelsize": 18.5,
            "axes.labelweight": "bold",
            "xtick.labelsize": 18.0,
            "ytick.labelsize": 18.0,
            "legend.fontsize": 18.0,
            "figure.titlesize": 20.0,
            "figure.dpi": DPI,
            "savefig.dpi": DPI,
            "figure.facecolor": BG_COLOR,
            "axes.facecolor": PANEL_BG,
            "axes.edgecolor": MUTED_COLOR,
            "axes.linewidth": 1.4,
            "xtick.color": INK_COLOR,
            "ytick.color": INK_COLOR,
            "text.color": INK_COLOR,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "svg.hashsalt": "protstruct_slides_2026_11_06",
        }
    )


def read_git_blob(rel_path: str) -> tuple[bytes, str]:
    """Read a committed blob from SOURCE_REVISION via git show and return (bytes, sha256)."""
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", f"{SOURCE_REVISION}:{rel_path}"],
        check=True,
        capture_output=True,
    )
    raw = proc.stdout
    sha = hashlib.sha256(raw).hexdigest()
    return raw, sha


def deterministic_offsets(n: int, half_width: float = 0.14) -> np.ndarray:
    """Return deterministic symmetric horizontal jitter offsets based on index rank."""
    if n <= 1:
        return np.zeros(n, dtype=float)
    phi = 0.6180339887498949
    vals = np.array([((i * phi) % 1.0) for i in range(n)], dtype=float)
    return (vals - 0.5) * 2.0 * half_width


def summary_stats(values: list[float]) -> dict[str, Any]:
    """Compute exact summary statistics for a numeric list."""
    arr = np.asarray(values, dtype=float)
    q25, med, q75 = np.percentile(arr, [25, 50, 75])
    return {
        "n": int(arr.size),
        "min": round(float(np.min(arr)), 6),
        "q25": round(float(q25), 6),
        "median": round(float(med), 6),
        "q75": round(float(q75), 6),
        "max": round(float(np.max(arr)), 6),
        "mean": round(float(np.mean(arr)), 6),
    }


def draw_box_and_strip(
    ax: plt.Axes,
    pos: float,
    values: list[float],
    color: str,
    marker: str,
    face_color: str | None = None,
    box_width: float = 0.34,
    jitter_width: float = 0.11,
    point_size: float = 78.0,
    zorder: int = 4,
) -> dict[str, Any]:
    """Draw a standardized boxplot (median + IQR + whiskers) overlaid with all individual strip points."""
    stats = summary_stats(values)
    fill = face_color if face_color is not None else color
    bp = ax.boxplot(
        [values],
        positions=[pos],
        widths=box_width,
        orientation="vertical",
        patch_artist=True,
        showfliers=False,
        whis=(0, 100),
        zorder=zorder - 1,
    )
    for patch in bp["boxes"]:
        patch.set_facecolor(fill)
        patch.set_alpha(0.22)
        patch.set_edgecolor(color)
        patch.set_linewidth(2.0)
    for median_line in bp["medians"]:
        median_line.set_color(INK_COLOR)
        median_line.set_linewidth(3.0)
    for whisker in bp["whiskers"]:
        whisker.set_color(color)
        whisker.set_linewidth(1.6)
        whisker.set_linestyle("-")
    for cap in bp["caps"]:
        cap.set_color(color)
        cap.set_linewidth(1.6)

    offsets = deterministic_offsets(len(values), half_width=jitter_width)
    xs = pos + offsets
    ax.scatter(
        xs,
        values,
        s=point_size,
        marker=marker,
        facecolor=fill,
        edgecolor=color if face_color is not None else INK_COLOR,
        linewidth=1.3,
        alpha=0.92,
        zorder=zorder,
    )
    plotted_groups = getattr(ax, "_plotted_groups", None)
    if plotted_groups is None:
        plotted_groups = []
        setattr(ax, "_plotted_groups", plotted_groups)
    plotted_groups.append(
        {"pos": float(pos), "values": [float(v) for v in values], "stats": stats}
    )
    return stats


def verify_figure_geometry(fig: plt.Figure, fig_name: str) -> None:
    """Verify rendered text font sizes (>=18pt / >=25px logical), canvas bounds, non-overlap, and unclipped box populations."""
    for ax in fig.axes:
        ymin, ymax = ax.get_ylim()
        for group in getattr(ax, "_plotted_groups", []):
            g_min = float(group["stats"]["min"])
            g_max = float(group["stats"]["max"])
            if g_min < ymin or g_max > ymax:
                raise ValueError(
                    f"{fig_name}: plotted group at x={group['pos']} has range [{g_min}, {g_max}] outside ylim=({ymin}, {ymax})"
                )

    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    w_px, h_px = EXPECTED_PNG_SIZE
    margin_px = 6.0

    visible_texts: list[ tuple[str, Bbox, float] ] = []
    for t in fig.findobj(Text):
        if not t.get_visible():
            continue
        txt = t.get_text().strip()
        if not txt:
            continue
        pt_size = float(t.get_fontsize())
        logical_px = pt_size * (100.0 / 72.0)
        if logical_px < 24.0 - 1e-6:
            raise ValueError(
                f"{fig_name}: text {txt!r} has logical size {logical_px:.2f}px (<24px; {pt_size}pt)"
            )
        bbox = t.get_window_extent(renderer=renderer)
        if (
            bbox.x0 < margin_px
            or bbox.y0 < margin_px
            or bbox.x1 > w_px - margin_px
            or bbox.y1 > h_px - margin_px
        ):
            raise ValueError(
                f"{fig_name}: text {txt!r} clipped/too close to edge: "
                f"bbox=({bbox.x0:.1f}, {bbox.y0:.1f}, {bbox.x1:.1f}, {bbox.y1:.1f}) vs {w_px}x{h_px}"
            )
        visible_texts.append((txt, bbox, logical_px))

    # Check pairwise text overlaps (shrinking each box by 2 px so touching line-spacing doesn't false-trigger)
    for i in range(len(visible_texts)):
        t1, b1, _ = visible_texts[i]
        s1 = Bbox.from_extents(b1.x0 + 2.0, b1.y0 + 2.0, b1.x1 - 2.0, b1.y1 - 2.0)
        for j in range(i + 1, len(visible_texts)):
            t2, b2, _ = visible_texts[j]
            s2 = Bbox.from_extents(b2.x0 + 2.0, b2.y0 + 2.0, b2.x1 - 2.0, b2.y1 - 2.0)
            if s1.overlaps(s2):
                raise ValueError(
                    f"{fig_name}: text overlap between {t1!r} and {t2!r}"
                )


def save_deterministic_png(fig: plt.Figure, out_path: Path) -> tuple[str, list[int]]:
    """Verify geometry, render figure to PNG with stripped metadata, and verify pixel dimensions."""
    verify_figure_geometry(fig, out_path.name)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=DPI, facecolor=BG_COLOR)
    plt.close(fig)
    buf.seek(0)
    with Image.open(buf) as im:
        im_rgb = im.convert("RGB")
        width, height = im_rgb.size
        if (width, height) != EXPECTED_PNG_SIZE:
            raise ValueError(
                f"Expected PNG size {EXPECTED_PNG_SIZE}, got {(width, height)} for {out_path}"
            )
        out_buf = io.BytesIO()
        im_rgb.save(out_buf, format="PNG", optimize=False)
    png_bytes = out_buf.getvalue()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(png_bytes)
    return hashlib.sha256(png_bytes).hexdigest(), [width, height]


def style_axes(ax: plt.Axes) -> None:
    """Apply clean grid and spine styling."""
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", color=GRID_COLOR, linestyle="--", linewidth=1.0, alpha=0.85, zorder=1)
    ax.set_axisbelow(True)


def build_fig01_cohort_resolution(out_dir: Path, source_hashes: dict[str, str]) -> dict[str, Any]:
    """Figure 1: Enrolled extreme-resolution cohort d_min distribution and stratum vs actual d_min."""
    enrolled_raw, enrolled_sha = read_git_blob(
        "ref/research/data/negative_control_round2_enrolled.json"
    )
    screen_raw, screen_sha = read_git_blob(
        "ref/research/data/negative_control_round2_screen.json"
    )
    source_hashes["ref/research/data/negative_control_round2_enrolled.json"] = enrolled_sha
    source_hashes["ref/research/data/negative_control_round2_screen.json"] = screen_sha

    enrolled_doc = json.loads(enrolled_raw.decode("utf-8"))
    screen_doc = json.loads(screen_raw.decode("utf-8"))
    entries = enrolled_doc["entries"]

    all_ids = [e["pdb_id"] for e in entries]
    all_dmin = [float(e["d_min"]) for e in entries]
    actual_le_090 = [float(e["d_min"]) for e in entries if float(e["d_min"]) <= 0.90]
    actual_gt_090 = [float(e["d_min"]) for e in entries if float(e["d_min"]) > 0.90]
    stratum_true = [float(e["d_min"]) for e in entries if bool(e["stratum"])]
    stratum_false = [float(e["d_min"]) for e in entries if not bool(e["stratum"])]
    inherited_above_090 = [
        e for e in entries if bool(e["stratum"]) and float(e["d_min"]) > 0.90
    ]

    screen_rows = screen_doc["rows"]
    n_attempts = len(screen_rows)
    n_initial = sum(1 for r in screen_rows if r.get("initial_representative"))
    n_replacements = n_attempts - n_initial
    n_floor = sum(1 for r in screen_rows if r.get("status") == "floor")
    n_defect = sum(1 for r in screen_rows if r.get("status") == "data_defect")
    n_screened = sum(1 for r in screen_rows if r.get("status") == "screened")
    n_headroom = int(screen_doc["d6"]["n_excluded_headroom"])
    n_enrolled = int(screen_doc["d6"]["n_enrolled"])

    fig, (ax_left, ax_right) = plt.subplots(
        1, 2, figsize=FIGSIZE_IN, gridspec_kw={"width_ratios": [1.15, 1.0]}
    )
    fig.subplots_adjust(left=0.075, right=0.975, bottom=0.22, top=0.81, wspace=0.24)

    style_axes(ax_left)
    style_axes(ax_right)

    s_all = draw_box_and_strip(
        ax_left, 1.0, all_dmin, COLOR_COHORT, "o", box_width=0.34, jitter_width=0.11
    )
    s_le09 = draw_box_and_strip(
        ax_left, 2.0, actual_le_090, COLOR_PHENIX, "o", box_width=0.34, jitter_width=0.11
    )
    s_gt09 = draw_box_and_strip(
        ax_left, 3.0, actual_gt_090, COLOR_GEMMI, "D", box_width=0.34, jitter_width=0.09
    )
    s_str_t = draw_box_and_strip(
        ax_left,
        4.0,
        stratum_true,
        COLOR_REFMAC,
        "^",
        face_color=COLOR_REFMAC_LIGHT,
        box_width=0.34,
        jitter_width=0.11,
    )
    s_str_f = draw_box_and_strip(
        ax_left, 5.0, stratum_false, COLOR_WWPDB, "s", box_width=0.30, jitter_width=0.05
    )

    ax_left.axhline(0.90, color=ACCENT_COLOR, linestyle=":", linewidth=2.0, zorder=2)
    ax_left.text(
        2.05,
        0.906,
        "0.90 Å boundary",
        fontsize=18.0,
        color=ACCENT_COLOR,
        fontweight="bold",
    )

    ax_left.set_xticks([1.0, 2.0, 3.0, 4.0, 5.0])
    ax_left.set_xticklabels(
        [
            f"All\n(n={len(all_dmin)})",
            f"≤0.90 Å\n(n={len(actual_le_090)})",
            f"0.90–1.00\n(n={len(actual_gt_090)})",
            f"stratum=T\n(n={len(stratum_true)})",
            f"stratum=F\n(n={len(stratum_false)})",
        ]
    )
    ax_left.set_ylabel("Resolution d_min (Å)")
    ax_left.set_ylim(0.76, 1.035)
    ax_left.set_xlim(0.42, 5.58)
    ax_left.set_title("A. Actual d_min vs Stored Stratum")

    sorted_entries = sorted(entries, key=lambda e: (float(e["d_min"]), e["pdb_id"]))
    for idx, entry in enumerate(sorted_entries):
        d_val = float(entry["d_min"])
        st = bool(entry["stratum"])
        if d_val <= 0.90:
            mk, fc = "o", COLOR_PHENIX
        elif st:
            mk, fc = "^", COLOR_ALERT
        else:
            mk, fc = "s", COLOR_WWPDB
        ax_right.scatter(
            [idx],
            [d_val],
            s=88,
            marker=mk,
            facecolor=fc,
            edgecolor=INK_COLOR,
            linewidth=1.3,
            zorder=4,
        )

    ax_right.axhline(0.90, color=ACCENT_COLOR, linestyle=":", linewidth=2.0, zorder=2)
    ax_right.axhline(
        s_all["median"], color=INK_COLOR, linestyle="--", linewidth=1.8, zorder=2
    )
    ax_right.text(
        8.5,
        0.805,
        f"Median d_min = {s_all['median']:.3f} Å\n5 replacements >0.90 Å\ninherit stratum=true",
        fontsize=18.0,
        color=INK_COLOR,
        fontweight="bold",
    )

    ax_right.set_xticks([0, 7, 14, 21])
    ax_right.set_xticklabels(
        [
            f"{sorted_entries[0]['pdb_id']}\n{sorted_entries[0]['d_min']:.2f}",
            f"{sorted_entries[7]['pdb_id']}\n{sorted_entries[7]['d_min']:.2f}",
            f"{sorted_entries[14]['pdb_id']}\n{sorted_entries[14]['d_min']:.2f}",
            f"{sorted_entries[21]['pdb_id']}\n{sorted_entries[21]['d_min']:.2f}",
        ]
    )
    ax_right.set_xlabel("Enrolled structures ranked by d_min (n = 22)")
    ax_right.set_ylabel("Resolution d_min (Å)")
    ax_right.set_ylim(0.76, 1.075)
    ax_right.set_xlim(-1.2, 22.2)
    ax_right.set_title("B. Ranked Profile (0.79–1.00 Å)")

    legend_handles = [
        Line2D(
            [0],
            [0],
            marker="o",
            color="none",
            markerfacecolor=COLOR_PHENIX,
            markeredgecolor=INK_COLOR,
            markersize=10,
            label="d_min ≤ 0.90 Å (n = 15)",
        ),
        Line2D(
            [0],
            [0],
            marker="^",
            color="none",
            markerfacecolor=COLOR_ALERT,
            markeredgecolor=INK_COLOR,
            markersize=10,
            label=">0.90 Å, stratum=true (n = 5)",
        ),
        Line2D(
            [0],
            [0],
            marker="s",
            color="none",
            markerfacecolor=COLOR_WWPDB,
            markeredgecolor=INK_COLOR,
            markersize=10,
            label=">0.90 Å, stratum=false (n = 2)",
        ),
    ]
    ax_right.legend(
        handles=legend_handles,
        loc="upper left",
        bbox_to_anchor=(0.01, 0.99),
        borderpad=0.35,
        labelspacing=0.28,
        handletextpad=0.35,
        frameon=True,
        facecolor=BG_COLOR,
        edgecolor=MUTED_COLOR,
        fontsize=18.0,
    )

    fig.suptitle(
        "Enrolled Extreme-Resolution Control Cohort (n = 22, 0.79–1.00 Å; 58 Screened Attempts)",
        y=0.94,
        fontweight="bold",
    )

    out_path = out_dir / "figures" / "fig01_cohort_resolution.png"
    png_sha, dims = save_deterministic_png(fig, out_path)
    return {
        "id": "fig01_cohort_resolution",
        "file": "figures/fig01_cohort_resolution.png",
        "sha256": png_sha,
        "dimensions_px": dims,
        "what_it_shows": (
            "Diffraction resolution d_min (Å) distribution of the 22 enrolled extreme-resolution "
            "X-ray control proteins, comparing actual d_min <= 0.90 Å (n=15) vs (0.90, 1.00] Å (n=7) "
            "against the stored cluster-inherited stratum flag (stratum=true n=20 vs false n=2)."
        ),
        "unit": "Å",
        "selection": (
            "22 enrolled cluster representatives surviving Round-2 D3 (>=50 unmasked residues) "
            "and D6 two-path headroom screening out of 58 attempts (30 initial + 28 replacements)."
        ),
        "n_groups": {
            "all_enrolled": len(all_dmin),
            "actual_d_min_le_0_90": len(actual_le_090),
            "actual_d_min_gt_0_90": len(actual_gt_090),
            "stored_stratum_true": len(stratum_true),
            "stored_stratum_false": len(stratum_false),
            "inherited_stratum_true_above_0_90": len(inherited_above_090),
        },
        "pdb_ids": all_ids,
        "inherited_stratum_true_above_0_90_pdb_ids": [
            e["pdb_id"] for e in inherited_above_090
        ],
        "record_selectors": [
            "ref/research/data/negative_control_round2_enrolled.json#/entries[*]/pdb_id",
            "ref/research/data/negative_control_round2_enrolled.json#/entries[*]/d_min",
            "ref/research/data/negative_control_round2_enrolled.json#/entries[*]/stratum",
            "ref/research/data/negative_control_round2_screen.json#/rows[*]/status",
            "ref/research/data/negative_control_round2_screen.json#/d6",
        ],
        "sources": [
            {
                "path": "ref/research/data/negative_control_round2_enrolled.json",
                "revision": SOURCE_REVISION,
                "sha256": enrolled_sha,
            },
            {
                "path": "ref/research/data/negative_control_round2_screen.json",
                "revision": SOURCE_REVISION,
                "sha256": screen_sha,
            },
        ],
        "thresholds_used": [
            {
                "label": "Subatomic stratum boundary",
                "value": 0.90,
                "unit": "Å",
                "kind": "selection_stratum_boundary",
                "source": "ref/research/negative_control_round2_preregistration.md:105-119",
            }
        ],
        "derived_summaries": {
            "all_enrolled_d_min_a": s_all,
            "actual_le_0_90_d_min_a": s_le09,
            "actual_gt_0_90_d_min_a": s_gt09,
            "stored_stratum_true_d_min_a": s_str_t,
            "stored_stratum_false_d_min_a": s_str_f,
            "screen_attrition": {
                "n_attempts": n_attempts,
                "n_initial": n_initial,
                "n_replacements": n_replacements,
                "n_floor_excluded": n_floor,
                "n_data_defects": n_defect,
                "n_screened": n_screened,
                "n_headroom_excluded": n_headroom,
                "n_enrolled": n_enrolled,
            },
        },
    }


def build_fig02_r9_null_delta_rfree(out_dir: Path, source_hashes: dict[str, str]) -> dict[str, Any]:
    """Figure 2: Clean Round-9 null re-refinement ΔR-free across PHENIX, Gemmi, and REFMAC5 (ANIS)."""
    r9_raw, r9_sha = read_git_blob("ref/research/data/negative_control_round9_anis.json")
    thresh_raw, thresh_sha = read_git_blob("ref/thresholds_and_standards.md")
    source_hashes["ref/research/data/negative_control_round9_anis.json"] = r9_sha
    source_hashes["ref/thresholds_and_standards.md"] = thresh_sha

    r9_doc = json.loads(r9_raw.decode("utf-8"))
    rows = r9_doc["rows"]

    phx_vals = [float(r["paths"]["phenix"]["delta"]) for r in rows]
    gem_vals = [float(r["paths"]["gemmi"]["delta"]) for r in rows]
    ref_rows = [r for r in rows if r.get("refmac") and r["refmac"].get("anis")]
    ref_anis_vals = [float(r["refmac"]["anis"]["delta"]) for r in ref_rows]

    phx_common21 = [float(r["paths"]["phenix"]["delta"]) for r in ref_rows]
    gem_common21 = [float(r["paths"]["gemmi"]["delta"]) for r in ref_rows]

    t_phx = 0.01200
    t_gem = 0.01025
    t_ref = 0.01150

    fig, ax = plt.subplots(1, 1, figsize=FIGSIZE_IN)
    fig.subplots_adjust(left=0.095, right=0.97, bottom=0.20, top=0.80)
    style_axes(ax)

    ax.axhline(0.0, color=INK_COLOR, linestyle="-", linewidth=2.2, zorder=2)
    ax.text(
        3.22,
        -0.0028,
        "ΔR-free = 0",
        fontsize=18.0,
        color=INK_COLOR,
        fontweight="bold",
    )

    s_phx = draw_box_and_strip(
        ax, 1.0, phx_vals, COLOR_PHENIX, "o", box_width=0.38, jitter_width=0.12
    )
    s_gem = draw_box_and_strip(
        ax, 2.0, gem_vals, COLOR_GEMMI, "D", box_width=0.38, jitter_width=0.12
    )
    s_ref = draw_box_and_strip(
        ax, 3.0, ref_anis_vals, COLOR_REFMAC, "^", box_width=0.38, jitter_width=0.12
    )

    for pos, thresh, col, lbl in [
        (1.0, t_phx, COLOR_PHENIX, "+0.01200"),
        (2.0, t_gem, COLOR_GEMMI, "+0.01025"),
        (3.0, t_ref, COLOR_REFMAC, "+0.01150"),
    ]:
        ax.plot(
            [pos - 0.25, pos + 0.25],
            [thresh, thresh],
            color=col,
            linestyle="--",
            linewidth=2.8,
            zorder=5,
        )
        ax.text(
            pos + 0.26,
            thresh - 0.0005,
            f"§6: {lbl}",
            fontsize=18.0,
            color=col,
            fontweight="bold",
        )

    row_by_id = {r["pdb_id"]: r for r in rows}
    ax.annotate(
        (
            f"2VXN (+{row_by_id['2VXN']['paths']['phenix']['delta']:.4f} / "
            f"+{row_by_id['2VXN']['paths']['gemmi']['delta']:.4f} / "
            f"+{row_by_id['2VXN']['refmac']['anis']['delta']:.4f})"
        ),
        xy=(2.0, float(row_by_id["2VXN"]["paths"]["gemmi"]["delta"])),
        xytext=(1.35, 0.0285),
        fontsize=18.0,
        fontweight="bold",
        color=INK_COLOR,
        arrowprops={"arrowstyle": "->", "color": INK_COLOR, "lw": 1.6},
    )
    ax.annotate(
        f"6XVM (+{row_by_id['6XVM']['refmac']['anis']['delta']:.4f})",
        xy=(3.0, float(row_by_id["6XVM"]["refmac"]["anis"]["delta"])),
        xytext=(2.85, 0.0225),
        fontsize=18.0,
        fontweight="bold",
        color=INK_COLOR,
        arrowprops={"arrowstyle": "->", "color": INK_COLOR, "lw": 1.6},
    )

    ax.set_xticks([1.0, 2.0, 3.0])
    ax.set_xticklabels(
        [
            f"PHENIX model_vs_data\n(n = {s_phx['n']}; med +{s_phx['median']:.5f})",
            f"Gemmi sfcalc\n(n = {s_gem['n']}; med +{s_gem['median']:.5f})",
            f"REFMAC5 (ANIS, 9YGW absent)\n(n = {s_ref['n']}; med +{s_ref['median']:.5f})",
        ]
    )
    ax.set_ylabel("ΔR-free (post − baseline)")
    ax.set_ylim(*DELTA_RFREE_YLIM)
    ax.set_xlim(0.42, 3.72)
    ax.set_title(
        "Clean Regenerated Round-9 Null Re-refinement ΔR-free Across Independent Evaluators"
    )
    fig.suptitle(
        "Positive ΔR-free = Worse Fit; Dashed Segments = §6 Refinement-Change Benchmark Thresholds",
        y=0.94,
        fontsize=18.5,
        fontweight="bold",
        color=MUTED_COLOR,
    )

    out_path = out_dir / "figures" / "fig02_r9_null_delta_rfree.png"
    png_sha, dims = save_deterministic_png(fig, out_path)
    return {
        "id": "fig02_r9_null_delta_rfree",
        "file": "figures/fig02_r9_null_delta_rfree.png",
        "sha256": png_sha,
        "dimensions_px": dims,
        "what_it_shows": (
            "Distribution of Round-9 regenerated null-refinement ΔR-free (post minus deposited baseline) "
            "across PHENIX model_vs_data (n=22), Gemmi sfcalc (n=22), and CCP4 REFMAC5 BREF ANIS (n=21, 9YGW absent)."
        ),
        "unit": "dimensionless fraction (ΔR-free)",
        "selection": "22 enrolled extreme-resolution control structures; 9YGW absent in REFMAC5 (n=21).",
        "n_groups": {
            "phenix_native": len(phx_vals),
            "gemmi_native": len(gem_vals),
            "refmac_anis_native": len(ref_anis_vals),
            "common_subset": len(ref_rows),
        },
        "pdb_ids": [r["pdb_id"] for r in rows],
        "refmac_pdb_ids": [r["pdb_id"] for r in ref_rows],
        "record_selectors": [
            "ref/research/data/negative_control_round9_anis.json#/rows[*]/paths/phenix/delta",
            "ref/research/data/negative_control_round9_anis.json#/rows[*]/paths/gemmi/delta",
            "ref/research/data/negative_control_round9_anis.json#/rows[*]/refmac/anis/delta",
            "ref/research/data/negative_control_round9_anis.json#/j2_anis",
        ],
        "sources": [
            {
                "path": "ref/research/data/negative_control_round9_anis.json",
                "revision": SOURCE_REVISION,
                "sha256": r9_sha,
            },
            {
                "path": "ref/thresholds_and_standards.md",
                "revision": SOURCE_REVISION,
                "sha256": thresh_sha,
            },
        ],
        "thresholds_used": [
            {
                "label": "§6 FIT refinement-change benchmark threshold (d_phenix)",
                "value": t_phx,
                "unit": "dimensionless fraction",
                "kind": "refinement_change_benchmark_threshold",
                "source": "ref/thresholds_and_standards.md:263",
            },
            {
                "label": "§6 FIT refinement-change benchmark threshold (d_gemmi)",
                "value": t_gem,
                "unit": "dimensionless fraction",
                "kind": "refinement_change_benchmark_threshold",
                "source": "ref/thresholds_and_standards.md:263",
            },
            {
                "label": "§6 FIT refinement-change benchmark threshold (d_refmac, ANIS)",
                "value": t_ref,
                "unit": "dimensionless fraction",
                "kind": "refinement_change_benchmark_threshold",
                "source": "ref/thresholds_and_standards.md:263",
            },
        ],
        "derived_summaries": {
            "phenix_native_n22": s_phx,
            "gemmi_native_n22": s_gem,
            "refmac_anis_native_n21": s_ref,
            "phenix_common_n21": summary_stats(phx_common21),
            "gemmi_common_n21": summary_stats(gem_common21),
        },
    }


def build_fig03_r9_isot_vs_anis_paired(
    out_dir: Path, source_hashes: dict[str, str]
) -> dict[str, Any]:
    """Figure 3: Paired REFMAC5 ISOT vs ANIS ΔR-free on the n=21 matched structures alongside PHENIX/Gemmi."""
    r9_raw, r9_sha = read_git_blob("ref/research/data/negative_control_round9_anis.json")
    source_hashes["ref/research/data/negative_control_round9_anis.json"] = r9_sha
    r9_doc = json.loads(r9_raw.decode("utf-8"))
    rows = r9_doc["rows"]
    matched_rows = [r for r in rows if r.get("refmac") and r["refmac"].get("anis")]

    phx_21 = [float(r["paths"]["phenix"]["delta"]) for r in matched_rows]
    gem_21 = [float(r["paths"]["gemmi"]["delta"]) for r in matched_rows]
    isot_21 = [float(r["refmac"]["isot"]["delta"]) for r in matched_rows]
    anis_21 = [float(r["refmac"]["anis"]["delta"]) for r in matched_rows]

    phx_22 = [float(r["paths"]["phenix"]["delta"]) for r in rows]
    gem_22 = [float(r["paths"]["gemmi"]["delta"]) for r in rows]

    fig, ax = plt.subplots(1, 1, figsize=FIGSIZE_IN)
    fig.subplots_adjust(left=0.095, right=0.97, bottom=0.22, top=0.80)
    style_axes(ax)

    ax.axhline(0.0, color=INK_COLOR, linestyle="-", linewidth=2.2, zorder=2)

    for r in matched_rows:
        y_isot = float(r["refmac"]["isot"]["delta"])
        y_anis = float(r["refmac"]["anis"]["delta"])
        is_2vxn = r["pdb_id"] == "2VXN"
        ax.plot(
            [3.0, 4.0],
            [y_isot, y_anis],
            color=COLOR_ALERT if is_2vxn else COLOR_REFMAC,
            linewidth=3.0 if is_2vxn else 1.3,
            linestyle="-" if is_2vxn else "--",
            alpha=0.95 if is_2vxn else 0.45,
            zorder=5 if is_2vxn else 3,
        )

    s_phx21 = draw_box_and_strip(
        ax, 1.0, phx_21, COLOR_PHENIX, "o", box_width=0.34, jitter_width=0.10
    )
    s_gem21 = draw_box_and_strip(
        ax, 2.0, gem_21, COLOR_GEMMI, "D", box_width=0.34, jitter_width=0.10
    )
    s_isot = draw_box_and_strip(
        ax,
        3.0,
        isot_21,
        COLOR_REFMAC,
        "v",
        face_color=COLOR_REFMAC_LIGHT,
        box_width=0.34,
        jitter_width=0.04,
        zorder=5,
    )
    s_anis = draw_box_and_strip(
        ax,
        4.0,
        anis_21,
        COLOR_REFMAC,
        "^",
        box_width=0.34,
        jitter_width=0.04,
        zorder=5,
    )

    row_2vxn = next(r for r in matched_rows if r["pdb_id"] == "2VXN")
    ax.annotate(
        f"2VXN ISOT: {row_2vxn['refmac']['isot']['delta']:+.4f} (aniso-collapse artifact)",
        xy=(2.95, float(row_2vxn["refmac"]["isot"]["delta"])),
        xytext=(2.68, -0.0128),
        ha="right",
        fontsize=18.0,
        fontweight="bold",
        color=COLOR_ALERT,
        arrowprops={"arrowstyle": "->", "color": COLOR_ALERT, "lw": 2.0},
    )
    ax.annotate(
        (
            f"2VXN ANIS: {row_2vxn['refmac']['anis']['delta']:+.4f} "
            f"(PHENIX +{row_2vxn['paths']['phenix']['delta']:.4f}, Gemmi +{row_2vxn['paths']['gemmi']['delta']:.4f})"
        ),
        xy=(4.0, float(row_2vxn["refmac"]["anis"]["delta"])),
        xytext=(2.18, 0.0265),
        fontsize=18.0,
        fontweight="bold",
        color=COLOR_ALERT,
        arrowprops={"arrowstyle": "->", "color": COLOR_ALERT, "lw": 2.0},
    )

    ax.set_xticks([1.0, 2.0, 3.0, 4.0])
    ax.set_xticklabels(
        [
            f"PHENIX (n=21)\nmed +{s_phx21['median']:.5f}\n(n=22: +{summary_stats(phx_22)['median']:.5f})",
            f"Gemmi (n=21)\nmed +{s_gem21['median']:.5f}\n(n=22: +{summary_stats(gem_22)['median']:.5f})",
            f"REFMAC ISOT (n=21)\nmed +{s_isot['median']:.5f}\nsign agree: 17/21",
            f"REFMAC ANIS (n=21)\nmed +{s_anis['median']:.5f}\nsign agree: 20/21",
        ]
    )
    ax.set_ylabel("ΔR-free (post − baseline)")
    ax.set_ylim(*DELTA_RFREE_YLIM)
    ax.set_xlim(0.45, 4.55)
    ax.set_title(
        "Paired ADP-Convention Comparison on Common 21-Structure Subset (9YGW Absent)"
    )
    fig.suptitle(
        "Preserving Deposited Anisotropic ADPs (BREF ANIS) Raises Sign Agreement from 17/21 to 20/21",
        y=0.94,
        fontsize=18.5,
        fontweight="bold",
        color=MUTED_COLOR,
    )

    out_path = out_dir / "figures" / "fig03_r9_isot_vs_anis_paired.png"
    png_sha, dims = save_deterministic_png(fig, out_path)
    return {
        "id": "fig03_r9_isot_vs_anis_paired",
        "file": "figures/fig03_r9_isot_vs_anis_paired.png",
        "sha256": png_sha,
        "dimensions_px": dims,
        "what_it_shows": (
            "Paired per-PDB comparison on the common 21-structure subset (9YGW absent in REFMAC5) "
            "between REFMAC5 BREF ISOT (collapsing deposited ANISOU) and REFMAC5 BREF ANIS "
            "(preserving ANISOU on both sides), alongside common-subset PHENIX and Gemmi ΔR-free."
        ),
        "unit": "dimensionless fraction (ΔR-free)",
        "selection": "21 REFMAC-measurable structures from the 22-entry cohort (9YGW excluded due to REFMAC absence).",
        "n_groups": {
            "phenix_common": len(phx_21),
            "gemmi_common": len(gem_21),
            "refmac_isot_paired": len(isot_21),
            "refmac_anis_paired": len(anis_21),
        },
        "pdb_ids": [r["pdb_id"] for r in matched_rows],
        "record_selectors": [
            "ref/research/data/negative_control_round9_anis.json#/rows[*]/refmac/isot/delta",
            "ref/research/data/negative_control_round9_anis.json#/rows[*]/refmac/anis/delta",
            "ref/research/data/negative_control_round9_anis.json#/x3_direction_agreement",
        ],
        "sources": [
            {
                "path": "ref/research/data/negative_control_round9_anis.json",
                "revision": SOURCE_REVISION,
                "sha256": r9_sha,
            }
        ],
        "thresholds_used": [],
        "derived_summaries": {
            "phenix_common_n21": s_phx21,
            "gemmi_common_n21": s_gem21,
            "phenix_native_n22": summary_stats(phx_22),
            "gemmi_native_n22": summary_stats(gem_22),
            "refmac_isot_n21": s_isot,
            "refmac_anis_n21": s_anis,
            "direction_agreement": r9_doc["x3_direction_agreement"],
            "highlight_2VXN": {
                "phenix_delta": row_2vxn["paths"]["phenix"]["delta"],
                "gemmi_delta": row_2vxn["paths"]["gemmi"]["delta"],
                "refmac_isot_delta": row_2vxn["refmac"]["isot"]["delta"],
                "refmac_anis_delta": row_2vxn["refmac"]["anis"]["delta"],
            },
        },
    }


def build_fig04_r10_recovery_delta_rfree(
    out_dir: Path, source_hashes: dict[str, str]
) -> dict[str, Any]:
    """Figure 4: Round-10 multi-factor recovery (osol_h) ΔR-free across PHENIX, Gemmi, and REFMAC5 (ANIS)."""
    r10_raw, r10_sha = read_git_blob(
        "ref/research/data/negative_control_round10_recover.json"
    )
    thresh_raw, thresh_sha = read_git_blob("ref/thresholds_and_standards.md")
    source_hashes["ref/research/data/negative_control_round10_recover.json"] = r10_sha
    source_hashes["ref/thresholds_and_standards.md"] = thresh_sha

    r10_doc = json.loads(r10_raw.decode("utf-8"))
    rows = r10_doc["rows"]

    phx_vals = [float(r["recovered"]["numbers"]["d_phenix"]) for r in rows]
    gem_vals = [float(r["recovered"]["numbers"]["d_gemmi"]) for r in rows]
    ref_rows = [
        r for r in rows if r["recovered"]["numbers"].get("d_refmac") is not None
    ]
    ref_vals = [float(r["recovered"]["numbers"]["d_refmac"]) for r in ref_rows]

    phx_common21 = [float(r["recovered"]["numbers"]["d_phenix"]) for r in ref_rows]
    gem_common21 = [float(r["recovered"]["numbers"]["d_gemmi"]) for r in ref_rows]

    t_phx = float(r10_doc["run"]["fit_thresholds"]["d_phenix"])
    t_gem = float(r10_doc["run"]["fit_thresholds"]["d_gemmi"])
    t_ref = float(r10_doc["run"]["fit_thresholds"]["d_refmac"])

    fig, ax = plt.subplots(1, 1, figsize=FIGSIZE_IN)
    fig.subplots_adjust(left=0.095, right=0.97, bottom=0.20, top=0.80)
    style_axes(ax)

    ax.axhline(0.0, color=INK_COLOR, linestyle="-", linewidth=2.2, zorder=2)
    ax.text(
        3.22,
        -0.0028,
        "ΔR-free = 0",
        fontsize=18.0,
        color=INK_COLOR,
        fontweight="bold",
    )

    s_phx = draw_box_and_strip(
        ax, 1.0, phx_vals, COLOR_PHENIX, "o", box_width=0.38, jitter_width=0.12
    )
    s_gem = draw_box_and_strip(
        ax, 2.0, gem_vals, COLOR_GEMMI, "D", box_width=0.38, jitter_width=0.12
    )
    s_ref = draw_box_and_strip(
        ax, 3.0, ref_vals, COLOR_REFMAC, "^", box_width=0.38, jitter_width=0.12
    )

    for pos, thresh, col, lbl in [
        (1.0, t_phx, COLOR_PHENIX, "+0.01200"),
        (2.0, t_gem, COLOR_GEMMI, "+0.01025"),
        (3.0, t_ref, COLOR_REFMAC, "+0.01150"),
    ]:
        ax.plot(
            [pos - 0.25, pos + 0.25],
            [thresh, thresh],
            color=col,
            linestyle="--",
            linewidth=2.8,
            zorder=5,
        )
        ax.text(
            pos + 0.26,
            thresh - 0.0005,
            f"§6: {lbl}",
            fontsize=18.0,
            color=col,
            fontweight="bold",
        )

    row_2vxn = next(r for r in rows if r["pdb_id"] == "2VXN")
    ax.annotate(
        (
            f"2VXN (+{row_2vxn['recovered']['numbers']['d_phenix']:.4f} / "
            f"+{row_2vxn['recovered']['numbers']['d_gemmi']:.4f} vs REFMAC "
            f"{row_2vxn['recovered']['numbers']['d_refmac']:+.4f})"
        ),
        xy=(3.0, float(row_2vxn["recovered"]["numbers"]["d_refmac"])),
        xytext=(1.35, -0.0142),
        fontsize=18.0,
        fontweight="bold",
        color=COLOR_ALERT,
        arrowprops={"arrowstyle": "->", "color": COLOR_ALERT, "lw": 1.8},
    )

    ax.set_xticks([1.0, 2.0, 3.0])
    ax.set_xticklabels(
        [
            f"PHENIX model_vs_data\n(n = {s_phx['n']}; med +{s_phx['median']:.5f})",
            f"Gemmi sfcalc\n(n = {s_gem['n']}; med +{s_gem['median']:.5f})",
            f"REFMAC5 (ANIS, 9YGW absent)\n(n = {s_ref['n']}; med +{s_ref['median']:.5f})",
        ]
    )
    ax.set_ylabel("ΔR-free (recovered − baseline)")
    ax.set_ylim(*DELTA_RFREE_YLIM)
    ax.set_xlim(0.42, 3.72)
    ax.set_title(
        "Round-10 Recovery ΔR-free vs Deposited Baseline (Multi-Factor osol_h Regimen)"
    )
    fig.suptitle(
        "Regimen: Regenerated Dynamics + ready_set Hydrogens + Ordered Solvent + REFMAC ANIS",
        y=0.94,
        fontsize=18.5,
        fontweight="bold",
        color=MUTED_COLOR,
    )

    out_path = out_dir / "figures" / "fig04_r10_recovery_delta_rfree.png"
    png_sha, dims = save_deterministic_png(fig, out_path)
    return {
        "id": "fig04_r10_recovery_delta_rfree",
        "file": "figures/fig04_r10_recovery_delta_rfree.png",
        "sha256": png_sha,
        "dimensions_px": dims,
        "what_it_shows": (
            "Distribution of Round-10 multi-factor recovery (osol_h) ΔR-free relative to the deposited "
            "baseline across PHENIX (n=22), Gemmi (n=22), and REFMAC5 BREF ANIS (n=21, 9YGW absent). "
            "JSON retains delta values only."
        ),
        "unit": "dimensionless fraction (ΔR-free)",
        "selection": (
            "22 enrolled extreme-resolution control structures under Round-10 osol_h regimen "
            "(regenerated phenix.dynamics stop_at_diff=0.5 seed=42 + phenix.ready_set hydrogens "
            "+ phenix.refine ordered_solvent=True hydrogens.refine=riding + REFMAC5 ANIS)."
        ),
        "n_groups": {
            "phenix_native": len(phx_vals),
            "gemmi_native": len(gem_vals),
            "refmac_anis_native": len(ref_vals),
            "common_subset": len(ref_rows),
        },
        "pdb_ids": [r["pdb_id"] for r in rows],
        "refmac_pdb_ids": [r["pdb_id"] for r in ref_rows],
        "record_selectors": [
            "ref/research/data/negative_control_round10_recover.json#/rows[*]/recovered/numbers/d_phenix",
            "ref/research/data/negative_control_round10_recover.json#/rows[*]/recovered/numbers/d_gemmi",
            "ref/research/data/negative_control_round10_recover.json#/rows[*]/recovered/numbers/d_refmac",
            "ref/research/data/negative_control_round10_recover.json#/run/fit_thresholds",
        ],
        "sources": [
            {
                "path": "ref/research/data/negative_control_round10_recover.json",
                "revision": SOURCE_REVISION,
                "sha256": r10_sha,
            },
            {
                "path": "ref/thresholds_and_standards.md",
                "revision": SOURCE_REVISION,
                "sha256": thresh_sha,
            },
        ],
        "thresholds_used": [
            {
                "label": "§6 FIT refinement-change benchmark threshold (d_phenix)",
                "value": t_phx,
                "unit": "dimensionless fraction",
                "kind": "refinement_change_benchmark_threshold",
                "source": "ref/research/data/negative_control_round10_recover.json#/run/fit_thresholds/d_phenix",
            },
            {
                "label": "§6 FIT refinement-change benchmark threshold (d_gemmi)",
                "value": t_gem,
                "unit": "dimensionless fraction",
                "kind": "refinement_change_benchmark_threshold",
                "source": "ref/research/data/negative_control_round10_recover.json#/run/fit_thresholds/d_gemmi",
            },
            {
                "label": "§6 FIT refinement-change benchmark threshold (d_refmac, ANIS)",
                "value": t_ref,
                "unit": "dimensionless fraction",
                "kind": "refinement_change_benchmark_threshold",
                "source": "ref/research/data/negative_control_round10_recover.json#/run/fit_thresholds/d_refmac",
            },
        ],
        "derived_summaries": {
            "phenix_native_n22": s_phx,
            "gemmi_native_n22": s_gem,
            "refmac_anis_native_n21": s_ref,
            "phenix_common_n21": summary_stats(phx_common21),
            "gemmi_common_n21": summary_stats(gem_common21),
            "highlight_2VXN": {
                "d_phenix": row_2vxn["recovered"]["numbers"]["d_phenix"],
                "d_gemmi": row_2vxn["recovered"]["numbers"]["d_gemmi"],
                "d_refmac": row_2vxn["recovered"]["numbers"]["d_refmac"],
            },
        },
    }


def parse_bond_rmsd_tables() -> tuple[list[dict[str, Any]], str, str]:
    """Parse the 17-row committed tables from tolerance_benchmark_restraint_library.md and tolerance_benchmark_bond_rmsd.md."""
    lib_raw, lib_sha = read_git_blob(
        "ref/research/tolerance_benchmark_restraint_library.md"
    )
    cnt_raw, cnt_sha = read_git_blob("ref/research/tolerance_benchmark_bond_rmsd.md")

    lib_text = lib_raw.decode("utf-8")
    cnt_text = cnt_raw.decode("utf-8")

    counts_by_id: dict[str, dict[str, Any]] = {}
    cnt_row_re = re.compile(
        r"^\|\s*([0-9A-Z]{4})\s*\|\s*([0-9.]+)\s*\|\s*(\d+)\s*\|\s*([0-9.]+)\s*\|\s*(\d+)\s*\|\s*([+−-]?[0-9.]+)\s*\|\s*(\*\*yes\*\*|no)\s*\|$"
    )
    for line in cnt_text.splitlines():
        m = cnt_row_re.match(line.strip())
        if m:
            pdb_id = m.group(1)
            counts_by_id[pdb_id] = {
                "n_bonds_phenix": int(m.group(3)),
                "n_bonds_gemmi": int(m.group(5)),
                "same_bond_count": m.group(7) == "**yes**",
            }

    rows: list[dict[str, Any]] = []
    lib_row_re = re.compile(
        r"^\|\s*([0-9A-Z]{4})\s*\|\s*([0-9.]+)\s*\|\s*([0-9.]+)\s*\|\s*([0-9.]+)\s*\|\s*([+−-][0-9.]+)\s*\|\s*([+−-][0-9.]+)\s*\|$"
    )
    for line in lib_text.splitlines():
        m = lib_row_re.match(line.strip())
        if m:
            pdb_id = m.group(1)
            a_val = float(m.group(2))
            b_val = float(m.group(3))
            c_val = float(m.group(4))
            b_minus_a = float(m.group(5).replace("−", "-"))
            c_minus_b = float(m.group(6).replace("−", "-"))
            cinfo = counts_by_id[pdb_id]
            rows.append(
                {
                    "pdb_id": pdb_id,
                    "a_phenix_cdl": a_val,
                    "b_phenix_eh": b_val,
                    "c_gemmi_ccp4": c_val,
                    "b_minus_a": b_minus_a,
                    "c_minus_b": c_minus_b,
                    "n_bonds_phenix": cinfo["n_bonds_phenix"],
                    "n_bonds_gemmi": cinfo["n_bonds_gemmi"],
                    "same_bond_count": cinfo["same_bond_count"],
                }
            )
    if len(rows) != 17:
        raise RuntimeError(f"Expected 17 rows in restraint library table, got {len(rows)}")
    return rows, lib_sha, cnt_sha


def build_fig05_bond_rmsd_abc(out_dir: Path, source_hashes: dict[str, str]) -> dict[str, Any]:
    """Figure 5: Bond-length RMSD (Å) across A (PHENIX CDL), B (PHENIX E&H), and C (Gemmi CCP4 monomer library)."""
    rows, lib_sha, cnt_sha = parse_bond_rmsd_tables()
    source_hashes["ref/research/tolerance_benchmark_restraint_library.md"] = lib_sha
    source_hashes["ref/research/tolerance_benchmark_bond_rmsd.md"] = cnt_sha

    a_all = [r["a_phenix_cdl"] for r in rows]
    b_all = [r["b_phenix_eh"] for r in rows]
    c_all = [r["c_gemmi_ccp4"] for r in rows]

    matched_rows = [r for r in rows if r["same_bond_count"]]
    mismatched_rows = [r for r in rows if not r["same_bond_count"]]

    fig, (ax_left, ax_right) = plt.subplots(
        1, 2, figsize=FIGSIZE_IN, gridspec_kw={"width_ratios": [1.05, 1.05]}
    )
    fig.subplots_adjust(left=0.085, right=0.975, bottom=0.22, top=0.80, wspace=0.26)
    style_axes(ax_left)
    style_axes(ax_right)

    for r in rows:
        col = COLOR_COHORT if r["same_bond_count"] else MUTED_COLOR
        ls = "-" if r["same_bond_count"] else ":"
        ax_left.plot(
            [1.0, 2.0, 3.0],
            [r["a_phenix_cdl"], r["b_phenix_eh"], r["c_gemmi_ccp4"]],
            color=col,
            linestyle=ls,
            linewidth=1.6 if r["same_bond_count"] else 1.1,
            alpha=0.55,
            zorder=2,
        )

    s_a = draw_box_and_strip(
        ax_left, 1.0, a_all, COLOR_PHENIX, "o", box_width=0.34, jitter_width=0.06
    )
    s_b = draw_box_and_strip(
        ax_left,
        2.0,
        b_all,
        COLOR_PHENIX,
        "s",
        face_color=COLOR_PHENIX_LIGHT,
        box_width=0.34,
        jitter_width=0.06,
    )
    s_c = draw_box_and_strip(
        ax_left, 3.0, c_all, COLOR_GEMMI, "D", box_width=0.34, jitter_width=0.06
    )
    row_30tw = next(r for r in rows if r["pdb_id"] == "30TW")
    ax_left.annotate(
        f"30TW: C = {row_30tw['c_gemmi_ccp4']:.5f} Å\n(PHENIX {row_30tw['n_bonds_phenix']:,}; Gemmi {row_30tw['n_bonds_gemmi']:,})",
        xy=(3.0, float(row_30tw["c_gemmi_ccp4"])),
        xytext=(0.55, 0.065),
        fontsize=18.0,
        fontweight="bold",
        color=COLOR_ALERT,
        arrowprops={"arrowstyle": "->", "color": COLOR_ALERT, "lw": 1.8},
    )

    ax_left.set_xticks([1.0, 2.0, 3.0])
    ax_left.set_xticklabels(
        [
            f"A: PHENIX CDL\n(n=17)\n{s_a['median']:.5f} Å",
            f"B: PHENIX E&H\n(n=17)\n{s_b['median']:.5f} Å",
            f"C: Gemmi 0.7.4\n(n=17)\n{s_c['median']:.5f} Å",
        ]
    )
    ax_left.set_yticks([0.00, 0.02, 0.04, 0.06, 0.08])
    ax_left.set_ylabel("Bond RMSD (Å, not RMSZ)")
    ax_left.set_ylim(-0.004, 0.090)
    ax_left.set_xlim(0.45, 3.55)
    ax_left.set_title("A. Three Configurations (n = 17)")

    ba_eq = [abs(r["b_minus_a"]) for r in matched_rows]
    cb_eq = [abs(r["c_minus_b"]) for r in matched_rows]
    ba_neq = [abs(r["b_minus_a"]) for r in mismatched_rows]
    cb_neq = [abs(r["c_minus_b"]) for r in mismatched_rows]

    s_ba_eq = draw_box_and_strip(
        ax_right, 1.0, ba_eq, COLOR_PHENIX, "o", box_width=0.34, jitter_width=0.08
    )
    s_cb_eq = draw_box_and_strip(
        ax_right, 2.0, cb_eq, COLOR_GEMMI, "D", box_width=0.34, jitter_width=0.08
    )
    s_ba_neq = draw_box_and_strip(
        ax_right,
        3.0,
        ba_neq,
        COLOR_PHENIX,
        "s",
        face_color=COLOR_PHENIX_LIGHT,
        box_width=0.34,
        jitter_width=0.08,
    )
    s_cb_neq = draw_box_and_strip(
        ax_right,
        4.0,
        cb_neq,
        COLOR_GEMMI,
        "D",
        box_width=0.34,
        jitter_width=0.08,
    )
    ax_right.annotate(
        f"30TW |C−B| = {abs(row_30tw['c_minus_b']):.5f} Å\n(count-mismatch void)",
        xy=(4.0, float(abs(row_30tw["c_minus_b"]))),
        xytext=(0.65, 0.054),
        fontsize=18.0,
        fontweight="bold",
        color=COLOR_ALERT,
        arrowprops={"arrowstyle": "->", "color": COLOR_ALERT, "lw": 1.8},
    )

    ax_right.text(
        0.58,
        0.025,
        "Equal bond count (n=6):\n|B−A| med 0.00085 Å\n|C−B| med 0.00320 Å",
        fontsize=18.0,
        color=ACCENT_COLOR,
        fontweight="bold",
    )

    ax_right.set_xticks([1.0, 2.0, 3.0, 4.0])
    ax_right.set_xticklabels(
        [
            f"|B−A| eq\n(n=6)\n{s_ba_eq['median']:.5f}",
            f"|C−B| eq\n(n=6)\n{s_cb_eq['median']:.5f}",
            f"|B−A| diff\n(n=11)\n{s_ba_neq['median']:.5f}",
            f"|C−B| diff\n(n=11)\n{s_cb_neq['median']:.5f}",
        ]
    )
    ax_right.set_yticks([0.00, 0.02, 0.04, 0.06])
    ax_right.set_ylabel("Absolute shift |Δ| (Å)")
    ax_right.set_ylim(-0.003, 0.075)
    ax_right.set_xlim(0.45, 4.55)
    ax_right.set_title("B. Within-PHENIX Library (|B−A|) vs |C−B|")

    fig.suptitle(
        "Reconstructed from Committed Benchmark Table at Published Precision (No New Benchmark)",
        y=0.94,
        fontsize=18.5,
        fontweight="bold",
        color=MUTED_COLOR,
    )

    out_path = out_dir / "figures" / "fig05_bond_rmsd_abc.png"
    png_sha, dims = save_deterministic_png(fig, out_path)
    return {
        "id": "fig05_bond_rmsd_abc",
        "file": "figures/fig05_bond_rmsd_abc.png",
        "sha256": png_sha,
        "dimensions_px": dims,
        "what_it_shows": (
            "Bond-length RMSD (Å, not RMSZ) reconstructed from the committed 17-model benchmark table "
            "at published precision across A (phenix.model_statistics CDL), B (phenix.model_statistics E&H), "
            "and C (gemmi rmsz CCP4 monomer library, historical gemmi 0.7.4 per #502 disclosure), "
            "separating the n=6 equal-bond-count subset from the n=11 different-bond-count subset."
        ),
        "unit": "Å",
        "selection": (
            "17 deposited X-ray structures from tolerance_benchmark_restraint_library.md:38-56; "
            "6 with equal restrained bond counts (9LLR, 9PN7, 30IZ, 12LO, 37AP, 37AS) and "
            "11 with differing bond counts."
        ),
        "n_groups": {
            "all_models": len(rows),
            "equal_bond_count_subset": len(matched_rows),
            "different_bond_count_subset": len(mismatched_rows),
        },
        "pdb_ids": [r["pdb_id"] for r in rows],
        "equal_bond_count_pdb_ids": [r["pdb_id"] for r in matched_rows],
        "different_bond_count_pdb_ids": [r["pdb_id"] for r in mismatched_rows],
        "record_selectors": [
            "ref/research/tolerance_benchmark_restraint_library.md:38-56",
            "ref/research/tolerance_benchmark_bond_rmsd.md:35-53",
        ],
        "sources": [
            {
                "path": "ref/research/tolerance_benchmark_restraint_library.md",
                "revision": SOURCE_REVISION,
                "sha256": lib_sha,
            },
            {
                "path": "ref/research/tolerance_benchmark_bond_rmsd.md",
                "revision": SOURCE_REVISION,
                "sha256": cnt_sha,
            },
        ],
        "thresholds_used": [],
        "derived_summaries": {
            "a_phenix_cdl_all_n17": s_a,
            "b_phenix_eh_all_n17": s_b,
            "c_gemmi_ccp4_all_n17": s_c,
            "abs_b_minus_a_equal_count_n6": s_ba_eq,
            "abs_c_minus_b_equal_count_n6": s_cb_eq,
            "abs_b_minus_a_diff_count_n11": s_ba_neq,
            "abs_c_minus_b_diff_count_n11": s_cb_neq,
        },
    }


def build_fig06_round46_rotamer_outlier_pct(
    out_dir: Path, source_hashes: dict[str, str]
) -> dict[str, Any]:
    """Figure 6: Round-46 PHENIX vs wwPDB rotamer outlier % and denominator vs classification agreement."""
    r46_raw, r46_sha = read_git_blob("ref/research/data/round46_vs_deposited.json")
    source_hashes["ref/research/data/round46_vs_deposited.json"] = r46_sha
    r46_doc = json.loads(r46_raw.decode("utf-8"))
    all_rows = r46_doc["rows"]

    protein_rows = [
        r
        for r in all_rows
        if r.get("wwpdb_rota_outlier_pct") is not None
        and int(r.get("rotamer_n_shared", 0)) > 0
    ]
    excluded_rows = [r["pdb_id"] for r in all_rows if r not in protein_rows]

    phx_rota = [float(r["phenix_rota_outlier_pct"]) for r in protein_rows]
    wwpdb_rota = [float(r["wwpdb_rota_outlier_pct"]) for r in protein_rows]
    delta_pp = [float(r["rota_outlier_delta_pp"]) for r in protein_rows]
    name_agree = [float(r["rotamer_rotamer_agreement"]) for r in protein_rows]

    fig, (ax_left, ax_right) = plt.subplots(
        1, 2, figsize=FIGSIZE_IN, gridspec_kw={"width_ratios": [1.05, 1.05]}
    )
    fig.subplots_adjust(left=0.08, right=0.975, bottom=0.22, top=0.80, wspace=0.26)
    style_axes(ax_left)
    style_axes(ax_right)

    for r in protein_rows:
        y1 = float(r["phenix_rota_outlier_pct"])
        y2 = float(r["wwpdb_rota_outlier_pct"])
        diff = abs(float(r["rota_outlier_delta_pp"]))
        ax_left.plot(
            [1.0, 2.0],
            [y1, y2],
            color=COLOR_ALERT if diff > 0.0 else MUTED_COLOR,
            linewidth=2.4 if diff > 0.0 else 1.1,
            alpha=0.9 if diff > 0.0 else 0.4,
            zorder=4 if diff > 0.0 else 2,
        )

    s_phx = draw_box_and_strip(
        ax_left, 1.0, phx_rota, COLOR_PHENIX, "o", box_width=0.34, jitter_width=0.07
    )
    s_ww = draw_box_and_strip(
        ax_left, 2.0, wwpdb_rota, COLOR_WWPDB, "s", box_width=0.34, jitter_width=0.07
    )

    ax_left.text(
        1.50,
        24.5,
        "39/41 match to 0.00 pp (Both MolProbity)",
        ha="center",
        fontsize=18.0,
        fontweight="bold",
        color=INK_COLOR,
    )

    ax_left.set_xticks([1.0, 2.0])
    ax_left.set_xticklabels(
        [
            f"PHENIX rotalyze\n(n = {s_phx['n']} proteins)\nmed {s_phx['median']:.2f}%",
            f"wwPDB report\n(n = {s_ww['n']} proteins)\nmed {s_ww['median']:.2f}%",
        ]
    )
    ax_left.set_yticks([0, 5, 10, 15, 20, 25])
    ax_left.set_ylabel("Rotamer outliers (%)")
    ax_left.set_ylim(-1.0, 28.5)
    ax_left.set_xlim(0.22, 2.78)
    ax_left.set_title("A. Paired Rotamer Outlier % (n = 41)")

    s_delta = draw_box_and_strip(
        ax_right, 0.85, delta_pp, COLOR_WWPDB, "s", box_width=0.32, jitter_width=0.11
    )
    ax_right.axhline(0.0, color=INK_COLOR, linestyle="-", linewidth=2.0, zorder=2)

    row_14zz = next(r for r in protein_rows if r["pdb_id"] == "14ZZ")
    row_2yol = next(r for r in protein_rows if r["pdb_id"] == "2YOL")
    ax_right.annotate(
        f"2YOL: {row_2yol['rota_outlier_delta_pp']:+.2f} pp (altloc count)",
        xy=(0.85, float(row_2yol["rota_outlier_delta_pp"])),
        xytext=(1.08, 0.56),
        fontsize=18.0,
        fontweight="bold",
        color=COLOR_ALERT,
        arrowprops={"arrowstyle": "->", "color": COLOR_ALERT, "lw": 1.8},
    )
    ax_right.annotate(
        f"14ZZ: {row_14zz['rota_outlier_delta_pp']:+.2f} pp (402 vs 459;\n402/402 shared names match)",
        xy=(0.85, float(row_14zz["rota_outlier_delta_pp"])),
        xytext=(1.08, -1.48),
        fontsize=18.0,
        fontweight="bold",
        color=COLOR_ALERT,
        arrowprops={"arrowstyle": "->", "color": COLOR_ALERT, "lw": 1.8},
    )
    ax_right.text(
        1.14,
        -0.46,
        "Shared-key OUTLIER verdict:\n41/41 = 1.0000 (38,744 keys)\nExact name: 40/41 = 1.0000,\n15C8 = 0.9919 (368/371)",
        fontsize=18.0,
        color=ACCENT_COLOR,
        fontweight="bold",
        bbox={"facecolor": PANEL_BG, "edgecolor": "none", "pad": 1.5, "alpha": 0.94},
        zorder=4,
    )

    ax_right.set_xticks([0.85])
    ax_right.set_xticklabels(
        [f"Raw Δ (PHENIX − wwPDB)\n(n = {s_delta['n']} proteins)"]
    )
    ax_right.set_yticks([-1.5, -1.0, -0.5, 0.0, 0.5])
    ax_right.set_ylabel("Outlier % difference (pp)")
    ax_right.set_ylim(-1.75, 0.92)
    ax_right.set_xlim(0.18, 2.62)
    ax_right.set_title("B. Raw % Shift vs Shared-Key Agreement")

    fig.suptitle(
        "Round-46 Deposited Comparison (41 Proteins, 12CI Excluded; Shared MolProbity Reference)",
        y=0.94,
        fontsize=18.5,
        fontweight="bold",
        color=MUTED_COLOR,
    )

    out_path = out_dir / "figures" / "fig06_round46_rotamer_outlier_pct.png"
    png_sha, dims = save_deterministic_png(fig, out_path)
    return {
        "id": "fig06_round46_rotamer_outlier_pct",
        "file": "figures/fig06_round46_rotamer_outlier_pct.png",
        "sha256": png_sha,
        "dimensions_px": dims,
        "what_it_shows": (
            "Paired comparison of PHENIX rotalyze vs wwPDB validation report rotamer outlier percentage "
            "across the n=41 protein entries in Round 46 (12CI nucleic-acid entry excluded for zero shared "
            "protein denominator), contrasting altloc denominator shifts on 14ZZ (-1.52 pp) and 2YOL (+0.57 pp) "
            "against 1.0000 shared-key binary OUTLIER agreement across all 41 proteins (38,744/38,744 residues)."
        ),
        "unit": "percentage (%) and percentage points (pp)",
        "selection": (
            "41 protein entries with positive shared rotamer denominators out of 42 total entries in "
            "ref/research/data/round46_vs_deposited.json (12CI excluded: rotamer_n_shared = 0)."
        ),
        "n_groups": {
            "total_json_rows": len(all_rows),
            "excluded_nucleic_acid_rows": len(excluded_rows),
            "phenix_proteins": len(phx_rota),
            "wwpdb_proteins": len(wwpdb_rota),
        },
        "pdb_ids": [r["pdb_id"] for r in protein_rows],
        "excluded_pdb_ids": excluded_rows,
        "record_selectors": [
            "ref/research/data/round46_vs_deposited.json#/rows[*]/phenix_rota_outlier_pct",
            "ref/research/data/round46_vs_deposited.json#/rows[*]/wwpdb_rota_outlier_pct",
            "ref/research/data/round46_vs_deposited.json#/rows[*]/rota_outlier_delta_pp",
            "ref/research/data/round46_vs_deposited.json#/rows[*]/rotamer_rotamer_agreement",
            "ref/research/data/round46_vs_deposited.json#/summary",
        ],
        "sources": [
            {
                "path": "ref/research/data/round46_vs_deposited.json",
                "revision": SOURCE_REVISION,
                "sha256": r46_sha,
            }
        ],
        "thresholds_used": [],
        "derived_summaries": {
            "phenix_rota_outlier_pct_n41": s_phx,
            "wwpdb_rota_outlier_pct_n41": s_ww,
            "rota_outlier_delta_pp_n41": s_delta,
            "exact_zero_delta_count": sum(1 for d in delta_pp if d == 0.0),
            "shared_rotamer_keys_total": int(
                r46_doc["summary"]["rotamer_name_agreement"]["n_residues"]
            ),
            "shared_rotamer_exact_name_matches": int(
                r46_doc["summary"]["rotamer_name_agreement"]["n_same"]
            ),
            "shared_rotamer_outlier_verdict_agreement_all_41": 1.0,
            "shared_ramachandran_keys_total": sum(
                int(r["ramachandran_n_shared"]) for r in protein_rows
            ),
            "shared_ramachandran_verdict_agreement_all_41": 1.0,
            "rotamer_name_agreement_n41": summary_stats(name_agree),
        },
    }


def _extract_ast_constants(py_source: str, names: set[str]) -> dict[str, Any]:
    """Extract top-level literal assignments by name from Python source text via AST without importing."""
    tree = ast.parse(py_source)
    extracted: dict[str, Any] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in names:
                    extracted[target.id] = ast.literal_eval(node.value)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id in names
            and node.value is not None
        ):
            extracted[node.target.id] = ast.literal_eval(node.value)
    missing = names - set(extracted.keys())
    if missing:
        raise RuntimeError(f"Missing AST constants in bench_recover_leg.py: {sorted(missing)}")
    return extracted


def _compute_null_threshold(values: list[float], mad_floor: float) -> dict[str, Any]:
    """Compute median(signed null deltas) + 3 * max(MAD, mad_floor), rounded to 5 decimals."""
    med = float(statistics.median(values))
    mad = float(statistics.median(abs(v - med) for v in values))
    floored_mad = float(max(mad, mad_floor))
    threshold = round(med + 3.0 * floored_mad, 5)
    return {
        "n": len(values),
        "median": med,
        "mad": mad,
        "floored_mad": floored_mad,
        "threshold": threshold,
    }


def _list_research_markdown_inventory() -> dict[str, Any]:
    """Derive committed file inventory under ref/research at SOURCE_REVISION via argument-list git ls-tree."""
    proc = subprocess.run(
        [
            "git",
            "-C",
            str(REPO_ROOT),
            "ls-tree",
            "-r",
            "--name-only",
            SOURCE_REVISION,
            "ref/research",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    all_paths = sorted(
        line.strip() for line in proc.stdout.splitlines() if line.strip()
    )
    patterns = {
        "tolerance_glob": r"ref/research/tolerance_benchmark_round[^/]*\.md",
        "tolerance_numbered_reports": r"ref/research/tolerance_benchmark_round\d+\.md",
        "tolerance_preregistrations": r"ref/research/tolerance_benchmark_round\d+_preregistration\.md",
        "negative_control_numbered_reports": r"ref/research/negative_control_round\d+\.md",
        "preregistration_named_markdown": r"ref/research/[^/]*preregistration[^/]*\.md",
    }
    counted_paths: dict[str, list[str]] = {
        key: [p for p in all_paths if re.fullmatch(pat, p)]
        for key, pat in patterns.items()
    }
    file_counts = {key: len(paths) for key, paths in counted_paths.items()}
    if (
        file_counts["tolerance_glob"]
        != file_counts["tolerance_numbered_reports"]
        + file_counts["tolerance_preregistrations"]
    ):
        raise RuntimeError(
            f"Tolerance glob count {file_counts['tolerance_glob']} != numbered "
            f"{file_counts['tolerance_numbered_reports']} + preregs {file_counts['tolerance_preregistrations']}"
        )
    return {
        "source_revision": SOURCE_REVISION,
        "count_patterns": patterns,
        "file_counts": file_counts,
        "counted_paths": counted_paths,
        "overlap_note": (
            "Counts overlap: tolerance_glob (60) is the union of tolerance_numbered_reports (40) "
            "and tolerance_preregistrations (20), and tolerance_preregistrations (20) are also "
            "counted inside preregistration_named_markdown (34)."
        ),
    }


def _parse_r4_prereg_thresholds(r4_prereg_text: str) -> dict[str, float]:
    """Scope to ## C1 in negative_control_round4_preregistration.md and parse the 3 tool threshold rows."""
    sec_match = re.search(
        r"^## C1 — the fit verdict, re-registered and NULL-CENTERED\b.*?(?=^## |\Z)",
        r4_prereg_text,
        re.S | re.M,
    )
    if sec_match is None:
        raise RuntimeError(
            "R4 registration mismatch: missing '## C1 — the fit verdict, re-registered and NULL-CENTERED' section in negative_control_round4_preregistration.md"
        )
    sec_text = sec_match.group(0)
    row_label_map = {
        "phenix path": "d_phenix",
        "gemmi path": "d_gemmi",
        "REFMAC": "d_refmac",
    }
    parsed: dict[str, float] = {}
    table_lines = [
        ln.strip() for ln in sec_text.splitlines() if ln.strip().startswith("|")
    ]
    if len(table_lines) < 5:
        raise RuntimeError(
            "R4 registration mismatch: C1 threshold table in negative_control_round4_preregistration.md has fewer than 5 table lines"
        )
    header_cells = [
        c.strip() for c in re.split(r"(?<!\\)\|", table_lines[0].strip("|"))
    ]
    if header_cells != ["tool", "null median", "null MAD", "threshold"]:
        raise RuntimeError(
            f"R4 registration mismatch: unexpected C1 table header {header_cells!r}"
        )
    for line in table_lines[2:]:
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", line.strip("|"))]
        if len(cells) != 4:
            raise RuntimeError(
                f"R4 registration mismatch: malformed C1 table row {line!r}"
            )
        row_label, med_cell, mad_cell, thresh_cell = cells
        if row_label not in row_label_map:
            raise RuntimeError(
                f"R4 registration mismatch: unexpected C1 tool row {row_label!r}"
            )
        tool_key = row_label_map[row_label]
        if tool_key in parsed:
            raise RuntimeError(
                f"R4 registration mismatch: duplicate C1 row for {row_label!r}"
            )
        if not re.fullmatch(r"\+\d+\.\d+", med_cell) or not re.fullmatch(
            r"\d+\.\d+", mad_cell
        ):
            raise RuntimeError(
                f"R4 registration mismatch: invalid median/MAD cells in row {line!r}"
            )
        m_thresh = re.fullmatch(r"\*\*\+(\d+\.\d+)\*\*", thresh_cell)
        if m_thresh is None:
            raise RuntimeError(
                f"R4 registration mismatch: threshold cell {thresh_cell!r} for {row_label!r} must be bold '+<decimal>'"
            )
        parsed[tool_key] = round(float(m_thresh.group(1)), 5)

    expected_keys = ("d_phenix", "d_gemmi", "d_refmac")
    if set(parsed.keys()) != set(expected_keys):
        missing = [k for k in expected_keys if k not in parsed]
        raise RuntimeError(
            f"R4 registration mismatch: missing C1 tool rows {missing}"
        )
    return {k: parsed[k] for k in expected_keys}


def _parse_registry_section6_fit_thresholds(
    thresh_text: str,
) -> dict[str, dict[str, float]]:
    """Scope to §6 in ref/thresholds_and_standards.md and parse the ISOT, ANIS, and retired-R4 threshold maps."""
    sec_match = re.search(
        r"^## 6\. Negative-control verdict rules\b.*?(?=^## |\Z)",
        thresh_text,
        re.S | re.M,
    )
    if sec_match is None:
        raise RuntimeError(
            "Registry §6 mismatch: missing '## 6. Negative-control verdict rules' section in ref/thresholds_and_standards.md"
        )
    sec_text = sec_match.group(0)
    target_rules = {
        "FIT thresholds — ISOT convention (history, rounds 3–8)": "isot_r7",
        "FIT thresholds — ANIS convention (current, round 9 on)": "anis_r9",
    }
    reg_cells: dict[str, str] = {}
    for line in sec_text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in re.split(r"(?<!\\)\|", s.strip("|"))]
        if len(cells) < 2:
            continue
        rule_name = cells[0]
        if rule_name in target_rules:
            if len(cells) != 3:
                raise RuntimeError(
                    f"Registry §6 mismatch: malformed table row for {rule_name!r}"
                )
            key = target_rules[rule_name]
            if key in reg_cells:
                raise RuntimeError(
                    f"Registry §6 mismatch: duplicate row for {rule_name!r}"
                )
            reg_cells[key] = cells[1]

    if set(reg_cells.keys()) != {"isot_r7", "anis_r9"}:
        missing = [
            rule for rule, k in target_rules.items() if k not in reg_cells
        ]
        raise RuntimeError(
            f"Registry §6 mismatch: missing FIT threshold row(s) {missing}"
        )

    expected_keys = ("d_phenix", "d_gemmi", "d_refmac")
    parsed_maps: dict[str, dict[str, float]] = {}
    for key, cell_text in reg_cells.items():
        pairs = re.findall(
            r"\b(d_phenix|d_gemmi|d_refmac)\s+\*\*(\d+\.\d+)\*\*", cell_text
        )
        if [p[0] for p in pairs] != list(expected_keys):
            raise RuntimeError(
                f"Registry §6 mismatch: {key} Registered form cell must state bold d_phenix, d_gemmi, d_refmac in order, got {[p[0] for p in pairs]}"
            )
        parsed_maps[key] = {
            tool_k: round(float(val_s), 5) for tool_k, val_s in pairs
        }

    retired_matches = re.findall(
        r"round-4 values\s+(\d+\.\d+)\s*/\s*(\d+\.\d+)\s*/\s*(\d+\.\d+)\s+were retired",
        reg_cells["isot_r7"],
    )
    if len(retired_matches) != 1:
        raise RuntimeError(
            "Registry §6 mismatch: ISOT convention Registered form cell must state exact retired round-4 triple once"
        )
    r4_phx, r4_gem, r4_ref = retired_matches[0]
    parsed_maps["retired_r4"] = {
        "d_phenix": round(float(r4_phx), 5),
        "d_gemmi": round(float(r4_gem), 5),
        "d_refmac": round(float(r4_ref), 5),
    }
    return parsed_maps


def _compute_and_verify_section6_fit_history(
    r3_doc: dict[str, Any],
    r6_doc: dict[str, Any],
    r9_doc: dict[str, Any],
    recover_text: str,
    thresh_text: str,
    r4_prereg_text: str,
) -> dict[str, Any]:
    """Derive R4/R7/R9 §6 FIT thresholds from raw records and assert equality against preregistration, §6 registry, and AST."""
    ast_consts = _extract_ast_constants(
        recover_text,
        {"REGISTERED_FIT_THRESHOLDS", "REGISTERED_FIT_THRESHOLDS_ANIS", "MAD_FLOOR"},
    )
    mad_floor = float(ast_consts["MAD_FLOOR"])
    reg_fit_r7 = {
        str(k): round(float(v), 5)
        for k, v in ast_consts["REGISTERED_FIT_THRESHOLDS"].items()
    }
    reg_fit_r9_anis = {
        str(k): round(float(v), 5)
        for k, v in ast_consts["REGISTERED_FIT_THRESHOLDS_ANIS"].items()
    }

    prereg_r4_map = _parse_r4_prereg_thresholds(r4_prereg_text)
    registry_s6 = _parse_registry_section6_fit_thresholds(thresh_text)

    clean_8r5k = r6_doc["g3_8r5k_rescreen"]["clean_null_deltas"]
    null_rows = [
        r
        for r in r3_doc["rows"]
        if r.get("subject") == "null" and r.get("status") == "benched"
    ]

    r4_stats: dict[str, dict[str, Any]] = {}
    r7_stats: dict[str, dict[str, Any]] = {}
    for tool_key in ("d_phenix", "d_gemmi", "d_refmac"):
        vals_r4 = [
            float(r["numbers"][tool_key])
            for r in null_rows
            if r["numbers"].get(tool_key) is not None
        ]
        vals_r7 = []
        for r in null_rows:
            v = (
                clean_8r5k[tool_key]
                if r["pdb_id"] == "8R5K"
                else r["numbers"].get(tool_key)
            )
            if v is not None:
                vals_r7.append(float(v))
        r4_stats[tool_key] = _compute_null_threshold(vals_r4, mad_floor)
        r7_stats[tool_key] = _compute_null_threshold(vals_r7, mad_floor)

    r9_anis_deltas = [
        float(r["refmac"]["anis"]["delta"])
        for r in r9_doc["rows"]
        if isinstance(r.get("refmac"), dict)
        and isinstance(r["refmac"].get("anis"), dict)
        and r["refmac"]["anis"].get("delta") is not None
    ]
    r9_anis_refmac = _compute_null_threshold(r9_anis_deltas, mad_floor)
    r9_stats: dict[str, dict[str, Any]] = {
        "d_phenix": dict(r7_stats["d_phenix"]),
        "d_gemmi": dict(r7_stats["d_gemmi"]),
        "d_refmac": r9_anis_refmac,
    }

    recomputed_r4_map = {k: v["threshold"] for k, v in r4_stats.items()}
    recomputed_r7_map = {k: v["threshold"] for k, v in r7_stats.items()}
    recomputed_r9_map = {k: v["threshold"] for k, v in r9_stats.items()}

    if recomputed_r4_map != prereg_r4_map:
        raise RuntimeError(
            f"R4 registration mismatch: recomputed R4 thresholds {recomputed_r4_map} != "
            f"negative_control_round4_preregistration.md C1 table {prereg_r4_map}"
        )
    if (
        recomputed_r4_map != registry_s6["retired_r4"]
        or prereg_r4_map != registry_s6["retired_r4"]
    ):
        raise RuntimeError(
            f"R4 registration mismatch: recomputed/preregistered R4 thresholds {recomputed_r4_map} != "
            f"thresholds_and_standards.md §6 retired round-4 triple {registry_s6['retired_r4']}"
        )
    if recomputed_r7_map != reg_fit_r7:
        raise RuntimeError(
            f"R7 registration mismatch: recomputed R7 thresholds {recomputed_r7_map} != "
            f"AST REGISTERED_FIT_THRESHOLDS {reg_fit_r7}"
        )
    if (
        recomputed_r7_map != registry_s6["isot_r7"]
        or reg_fit_r7 != registry_s6["isot_r7"]
    ):
        raise RuntimeError(
            f"R7 registration mismatch: recomputed/AST R7 thresholds {recomputed_r7_map} != "
            f"thresholds_and_standards.md §6 ISOT row {registry_s6['isot_r7']}"
        )
    if recomputed_r9_map != reg_fit_r9_anis:
        raise RuntimeError(
            f"R9 registration mismatch: recomputed R9 ANIS thresholds {recomputed_r9_map} != "
            f"AST REGISTERED_FIT_THRESHOLDS_ANIS {reg_fit_r9_anis}"
        )
    if (
        recomputed_r9_map != registry_s6["anis_r9"]
        or reg_fit_r9_anis != registry_s6["anis_r9"]
    ):
        raise RuntimeError(
            f"R9 registration mismatch: recomputed/AST R9 ANIS thresholds {recomputed_r9_map} != "
            f"thresholds_and_standards.md §6 ANIS row {registry_s6['anis_r9']}"
        )

    j2_anis = r9_doc["j2_anis"]
    if round(float(j2_anis["d_refmac_anis"]), 5) != r9_anis_refmac["threshold"]:
        raise RuntimeError(
            f"R9 j2_anis d_refmac_anis ({j2_anis['d_refmac_anis']}) disagrees with derived threshold ({r9_anis_refmac['threshold']})"
        )
    if int(j2_anis["n"]) != int(r9_anis_refmac["n"]):
        raise RuntimeError(
            f"R9 j2_anis n ({j2_anis['n']}) disagrees with derived count ({r9_anis_refmac['n']})"
        )

    return {
        "mad_floor": mad_floor,
        "null_rows": null_rows,
        "r4_stats": r4_stats,
        "r7_stats": r7_stats,
        "r9_stats": r9_stats,
        "r9_anis_refmac": r9_anis_refmac,
        "recomputed_r4_map": recomputed_r4_map,
        "recomputed_r7_map": recomputed_r7_map,
        "recomputed_r9_map": recomputed_r9_map,
        "reg_fit_r7": reg_fit_r7,
        "reg_fit_r9_anis": reg_fit_r9_anis,
        "prereg_r4_map": prereg_r4_map,
        "registry_s6": registry_s6,
        "j2_anis": {
            "n": int(j2_anis["n"]),
            "median_abs_delta": float(j2_anis["median_abs_delta"]),
            "d_refmac_anis": round(float(j2_anis["d_refmac_anis"]), 5),
        },
    }


def build_fig07_threshold_evidence_history(
    out_dir: Path, source_hashes: dict[str, str]
) -> dict[str, Any]:
    """Figure 7: Threshold evidence/policy ledger (41 components across 21 §3/§4 rows) and §6 FIT threshold history."""
    ledger_raw, ledger_sha = read_git_blob("ref/threshold_evidence_status.yaml")
    r3_raw, r3_sha = read_git_blob("ref/research/data/negative_control_round3_bench.json")
    r6_raw, r6_sha = read_git_blob("ref/research/data/negative_control_round6_hygiene.json")
    r9_raw, r9_sha = read_git_blob("ref/research/data/negative_control_round9_anis.json")
    recover_raw, recover_sha = read_git_blob("scripts/bench_recover_leg.py")
    thresh_raw, thresh_sha = read_git_blob("ref/thresholds_and_standards.md")
    r4_prereg_raw, r4_prereg_sha = read_git_blob(
        "ref/research/negative_control_round4_preregistration.md"
    )

    source_hashes["ref/threshold_evidence_status.yaml"] = ledger_sha
    source_hashes["ref/research/data/negative_control_round3_bench.json"] = r3_sha
    source_hashes["ref/research/data/negative_control_round6_hygiene.json"] = r6_sha
    source_hashes["ref/research/data/negative_control_round9_anis.json"] = r9_sha
    source_hashes["scripts/bench_recover_leg.py"] = recover_sha
    source_hashes["ref/thresholds_and_standards.md"] = thresh_sha
    source_hashes["ref/research/negative_control_round4_preregistration.md"] = r4_prereg_sha

    # 1. Parse ref/threshold_evidence_status.yaml
    ledger_doc = yaml.safe_load(ledger_raw.decode("utf-8"))
    ledger_rows = ledger_doc["rows"]
    n_rows = len(ledger_rows)
    rows_by_section: dict[str, int] = {}
    evidence_counts_raw: dict[str, int] = {}
    policy_counts_raw: dict[str, int] = {}
    components_flat: list[dict[str, Any]] = []

    for row in ledger_rows:
        sec_key = str(row["section"])
        rows_by_section[sec_key] = rows_by_section.get(sec_key, 0) + 1
        for comp in row["components"]:
            ev_state = str(comp["evidence_state"])
            pol_state = str(comp["policy_state"])
            evidence_counts_raw[ev_state] = evidence_counts_raw.get(ev_state, 0) + 1
            policy_counts_raw[pol_state] = policy_counts_raw.get(pol_state, 0) + 1
            components_flat.append(
                {
                    "component_key": f"{row['id']}.{comp['id']}",
                    "row_id": row["id"],
                    "section": int(row["section"]),
                    "component_id": comp["id"],
                    "evidence_state": ev_state,
                    "policy_state": pol_state,
                    "scope": comp["scope"],
                }
            )

    n_components = len(components_flat)
    if sum(evidence_counts_raw.values()) != n_components or sum(policy_counts_raw.values()) != n_components:
        raise RuntimeError("Orthogonal state counts do not sum to total components")

    evidence_sorted = sorted(
        evidence_counts_raw.items(), key=lambda kv: (-kv[1], kv[0])
    )
    policy_sorted = sorted(
        policy_counts_raw.items(), key=lambda kv: (-kv[1], kv[0])
    )

    # 2. Independently derive and verify registered §6 FIT threshold history (R4 -> R7 -> R9)
    s6_history = _compute_and_verify_section6_fit_history(
        r3_doc=json.loads(r3_raw.decode("utf-8")),
        r6_doc=json.loads(r6_raw.decode("utf-8")),
        r9_doc=json.loads(r9_raw.decode("utf-8")),
        recover_text=recover_raw.decode("utf-8"),
        thresh_text=thresh_raw.decode("utf-8"),
        r4_prereg_text=r4_prereg_raw.decode("utf-8"),
    )
    mad_floor = s6_history["mad_floor"]
    null_rows = s6_history["null_rows"]
    r4_stats = s6_history["r4_stats"]
    r7_stats = s6_history["r7_stats"]
    r9_stats = s6_history["r9_stats"]
    r9_anis_refmac = s6_history["r9_anis_refmac"]
    recomputed_r4_map = s6_history["recomputed_r4_map"]
    recomputed_r7_map = s6_history["recomputed_r7_map"]
    recomputed_r9_map = s6_history["recomputed_r9_map"]
    reg_fit_r7 = s6_history["reg_fit_r7"]
    reg_fit_r9_anis = s6_history["reg_fit_r9_anis"]
    prereg_r4_map = s6_history["prereg_r4_map"]
    registry_s6 = s6_history["registry_s6"]
    j2_anis_summary = s6_history["j2_anis"]

    # 3. Committed file inventory under ref/research
    inventory = _list_research_markdown_inventory()

    # 4. Render Figure 7 (Panel A: Evidence states; Panel B: Policy states; Panel C: 3 aligned §6 FIT threshold panels)
    fig = plt.figure(figsize=FIGSIZE_IN)
    ax_evid = fig.add_axes([0.165, 0.22, 0.165, 0.57])
    ax_pol = fig.add_axes([0.485, 0.22, 0.165, 0.57])
    ax_phx = fig.add_axes([0.725, 0.625, 0.255, 0.165])
    ax_gem = fig.add_axes([0.725, 0.4225, 0.255, 0.165])
    ax_ref = fig.add_axes([0.725, 0.22, 0.255, 0.165])

    ev_label_map = {
        "retained_record": "retained record",
        "unmeasured": "unmeasured",
        "partial_record": "partial record",
        "denominator_unproven": "denom. unproven",
        "external_standard_cited": "ext. standard",
        "limited_controls": "limited controls",
        "producer_mismatch": "prod. mismatch",
        "unverified_ancillary": "unverif. ancill.",
    }
    pol_label_map = {
        "active_conditional": "active cond.",
        "informational": "informational",
        "provisional_informational": "prov. inform.",
        "not_evaluable": "not evaluable",
        "policy_unresolved": "unresolved",
        "provisional_conditional": "prov. cond.",
        "suspended": "suspended",
    }

    for ax_bar in (ax_evid, ax_pol):
        ax_bar.spines["top"].set_visible(False)
        ax_bar.spines["right"].set_visible(False)
        ax_bar.grid(
            axis="x", color=GRID_COLOR, linestyle="--", linewidth=1.0, alpha=0.85, zorder=1
        )
        ax_bar.set_axisbelow(True)

    y_ev = np.arange(len(evidence_sorted), dtype=float)
    ev_vals = [cnt for _, cnt in evidence_sorted]
    ev_colors = [
        ACCENT_COLOR if key == "retained_record" else MUTED_COLOR
        for key, _ in evidence_sorted
    ]
    ax_evid.barh(
        y_ev,
        ev_vals,
        height=0.60,
        color=ev_colors,
        edgecolor=INK_COLOR,
        linewidth=1.3,
        alpha=0.88,
        zorder=3,
    )
    for idx, (_, cnt) in enumerate(evidence_sorted):
        ax_evid.text(
            float(cnt) + 0.8,
            float(idx),
            str(cnt),
            va="center",
            ha="left",
            fontsize=18.0,
            fontweight="bold",
            color=INK_COLOR,
        )
    ax_evid.set_yticks(y_ev)
    ax_evid.set_yticklabels([ev_label_map[k] for k, _ in evidence_sorted])
    ax_evid.set_xlim(0, 31)
    ax_evid.set_xticks([0, 10, 20, 30])
    ax_evid.set_ylim(len(evidence_sorted) - 0.4, -0.6)
    ax_evid.set_title("A. Evidence State (n=41)", fontsize=18.5, fontweight="bold", pad=10)

    y_pol = np.arange(len(policy_sorted), dtype=float)
    pol_vals = [cnt for _, cnt in policy_sorted]
    pol_colors = [
        ACCENT_COLOR if key == "active_conditional" else MUTED_COLOR
        for key, _ in policy_sorted
    ]
    ax_pol.barh(
        y_pol,
        pol_vals,
        height=0.58,
        color=pol_colors,
        edgecolor=INK_COLOR,
        linewidth=1.3,
        alpha=0.88,
        zorder=3,
    )
    for idx, (_, cnt) in enumerate(policy_sorted):
        ax_pol.text(
            float(cnt) + 0.9,
            float(idx),
            str(cnt),
            va="center",
            ha="left",
            fontsize=18.0,
            fontweight="bold",
            color=INK_COLOR,
        )
    ax_pol.set_yticks(y_pol)
    ax_pol.set_yticklabels([pol_label_map[k] for k, _ in policy_sorted])
    ax_pol.set_xlim(0, 37)
    ax_pol.set_xticks([0, 10, 20, 30])
    ax_pol.set_ylim(len(policy_sorted) - 0.4, -0.6)
    ax_pol.set_title("B. Policy State (n=41)", fontsize=18.5, fontweight="bold", pad=10)

    xs_hist = [1.0, 2.0, 3.0]
    tool_specs = [
        (
            ax_phx,
            "d_phenix",
            "PHENIX (o, n=22)",
            COLOR_PHENIX,
            "o",
            [0.0062, 0.0062, 0.0062],
        ),
        (
            ax_gem,
            "d_gemmi",
            "Gemmi (D, n=22)",
            COLOR_GEMMI,
            "D",
            [0.0062, 0.0062, 0.0062],
        ),
        (
            ax_ref,
            "d_refmac",
            "REFMAC (^, n=19/20/21)",
            COLOR_REFMAC,
            "^",
            [0.0086, 0.0086, 0.0062],
        ),
    ]
    for ax_t, tool_key, header_lbl, col, mk, label_ys in tool_specs:
        style_axes(ax_t)
        ys_t = [
            float(r4_stats[tool_key]["threshold"]),
            float(r7_stats[tool_key]["threshold"]),
            float(r9_stats[tool_key]["threshold"]),
        ]
        ax_t.plot(
            xs_hist,
            ys_t,
            color=col,
            linestyle="-",
            linewidth=2.6,
            zorder=3,
        )
        ax_t.scatter(
            xs_hist,
            ys_t,
            s=95,
            marker=mk,
            facecolor=col,
            edgecolor=INK_COLOR,
            linewidth=1.4,
            zorder=4,
        )
        ax_t.text(
            0.55,
            0.0148,
            header_lbl,
            fontsize=18.0,
            fontweight="bold",
            color=col,
            va="center",
            ha="left",
        )
        for x_pos, y_val, y_txt in zip(xs_hist, ys_t, label_ys):
            ax_t.text(
                x_pos,
                y_txt,
                f".{int(round(y_val * 100000)):05d}",
                fontsize=18.0,
                fontweight="bold",
                color=INK_COLOR,
                va="center",
                ha="center",
            )
        ax_t.set_xlim(0.45, 3.55)
        ax_t.set_ylim(0.0030, 0.0170)
        ax_t.set_yticks([0.005, 0.012])
        ax_t.set_yticklabels([".005", ".012"])
        ax_t.set_xticks(xs_hist)

    ax_phx.set_xticklabels([])
    ax_gem.set_xticklabels([])
    ax_ref.set_xticklabels(["R4 (ret)\nISOT", "R7 (hist)\nISOT", "R9 (cur)\nANIS"])
    ax_phx.set_title(
        "C. ΔR-free Thresholds\n(unitless fraction)",
        fontsize=18.0,
        fontweight="bold",
        pad=8,
    )

    fig.suptitle(
        "Threshold Ledger (21 Rows: 17 §3 + 4 §4; 41 Components) & §6 FIT History",
        y=0.955,
        fontsize=19.0,
        fontweight="bold",
        color=INK_COLOR,
    )
    fig.text(
        0.50,
        0.035,
        "Ledger (§3/§4): retained_record ≠ calibration · §6: protocol regimes, not a trend",
        ha="center",
        va="center",
        fontsize=18.0,
        fontweight="bold",
        color=MUTED_COLOR,
    )

    out_path = out_dir / "figures" / "fig07_threshold_evidence_history.png"
    png_sha, dims = save_deterministic_png(fig, out_path)
    return {
        "id": "fig07_threshold_evidence_history",
        "file": "figures/fig07_threshold_evidence_history.png",
        "sha256": png_sha,
        "dimensions_px": dims,
        "what_it_shows": (
            "Orthogonal evidence-state (8 states, n=41) and policy-state (7 states, n=41) counts across "
            "the 21 rendered threshold-registry rows (17 in §3 + 4 in §4) in ref/threshold_evidence_status.yaml, "
            "paired with the §6 FIT ΔR-free threshold registration history (unitless fraction, "
            "median_null + 3*max(MAD_null, 0.0005)) across R4 retired (ISOT, n=22/22/19), "
            "R7 history (ISOT with 8R5K clean null, n=22/22/20), and R9 current (REFI BREF ANIS, n=22/22/21)."
        ),
        "unit": "component count (n = 41) and unitless fraction (ΔR-free threshold)",
        "selection": (
            "All 21 rows (41 components) in ref/threshold_evidence_status.yaml (§3 and §4 scope) "
            "and all benched null ΔR-free observations in negative_control_round3_bench.json, "
            "negative_control_round6_hygiene.json (g3_8r5k_rescreen.clean_null_deltas), and "
            "negative_control_round9_anis.json (§6 scope)."
        ),
        "n_groups": {
            "ledger_rows_total": n_rows,
            "ledger_rows_section_3": rows_by_section["3"],
            "ledger_rows_section_4": rows_by_section["4"],
            "ledger_components_total": n_components,
            "r4_null_phenix": r4_stats["d_phenix"]["n"],
            "r4_null_gemmi": r4_stats["d_gemmi"]["n"],
            "r4_null_refmac_isot": r4_stats["d_refmac"]["n"],
            "r7_null_phenix": r7_stats["d_phenix"]["n"],
            "r7_null_gemmi": r7_stats["d_gemmi"]["n"],
            "r7_null_refmac_isot": r7_stats["d_refmac"]["n"],
            "r9_null_refmac_anis": r9_stats["d_refmac"]["n"],
        },
        "pdb_ids": [r["pdb_id"] for r in null_rows],
        "record_selectors": [
            "ref/threshold_evidence_status.yaml#/rows[*]/components[*]/evidence_state",
            "ref/threshold_evidence_status.yaml#/rows[*]/components[*]/policy_state",
            "ref/research/data/negative_control_round3_bench.json#/rows[*]/numbers",
            "ref/research/data/negative_control_round6_hygiene.json#/g3_8r5k_rescreen/clean_null_deltas",
            "ref/research/data/negative_control_round9_anis.json#/rows[*]/refmac/anis/delta",
            "ref/research/data/negative_control_round9_anis.json#/j2_anis",
            "scripts/bench_recover_leg.py:44-55,82-129",
            "ref/thresholds_and_standards.md:261-263",
            "ref/research/negative_control_round4_preregistration.md:20-28",
        ],
        "sources": [
            {
                "path": "ref/threshold_evidence_status.yaml",
                "revision": SOURCE_REVISION,
                "sha256": ledger_sha,
            },
            {
                "path": "ref/research/data/negative_control_round3_bench.json",
                "revision": SOURCE_REVISION,
                "sha256": r3_sha,
            },
            {
                "path": "ref/research/data/negative_control_round6_hygiene.json",
                "revision": SOURCE_REVISION,
                "sha256": r6_sha,
            },
            {
                "path": "ref/research/data/negative_control_round9_anis.json",
                "revision": SOURCE_REVISION,
                "sha256": r9_sha,
            },
            {
                "path": "scripts/bench_recover_leg.py",
                "revision": SOURCE_REVISION,
                "sha256": recover_sha,
            },
            {
                "path": "ref/thresholds_and_standards.md",
                "revision": SOURCE_REVISION,
                "sha256": thresh_sha,
            },
            {
                "path": "ref/research/negative_control_round4_preregistration.md",
                "revision": SOURCE_REVISION,
                "sha256": r4_prereg_sha,
            },
        ],
        "thresholds_used": [
            {
                "label": "R4 retired §6 FIT thresholds (d_phenix / d_gemmi / d_refmac ISOT)",
                "value": recomputed_r4_map,
                "unit": "dimensionless fraction",
                "kind": "retired_refinement_change_benchmark_threshold",
                "source": "ref/research/negative_control_round4_preregistration.md:24-28; ref/thresholds_and_standards.md:262",
            },
            {
                "label": "R7 history §6 FIT thresholds (d_phenix / d_gemmi / d_refmac ISOT)",
                "value": recomputed_r7_map,
                "unit": "dimensionless fraction",
                "kind": "historical_isot_refinement_change_benchmark_threshold",
                "source": "scripts/bench_recover_leg.py:44-45; ref/thresholds_and_standards.md:262",
            },
            {
                "label": "R9 current §6 FIT thresholds (d_phenix / d_gemmi / d_refmac ANIS)",
                "value": recomputed_r9_map,
                "unit": "dimensionless fraction",
                "kind": "current_anis_refinement_change_benchmark_threshold",
                "source": "scripts/bench_recover_leg.py:53-54; ref/thresholds_and_standards.md:263",
            },
        ],
        "derived_summaries": {
            "ledger_metadata": {
                "as_of_date": str(ledger_doc["as_of_date"]),
                "scope": str(ledger_doc["scope"]).strip(),
                "policy_state_definition": str(ledger_doc["policy_state_definition"]).strip(),
                "evidence_state_definition": str(ledger_doc["evidence_state_definition"]).strip(),
                "historical_inventory_definition": str(
                    ledger_doc["historical_inventory_definition"]
                ).strip(),
            },
            "n_rows": n_rows,
            "rows_by_section": rows_by_section,
            "n_components": n_components,
            "evidence_state": {k: v for k, v in evidence_sorted},
            "policy_state": {k: v for k, v in policy_sorted},
            "components": components_flat,
            "formula": "median(signed null deltas)+3*max(MAD,.0005)",
            "mad_floor": mad_floor,
            "R4": r4_stats,
            "R7": r7_stats,
            "R9": r9_stats,
            "R9_ANIS_REF": r9_anis_refmac,
            "registered_thresholds_ast": {
                "REGISTERED_FIT_THRESHOLDS": reg_fit_r7,
                "REGISTERED_FIT_THRESHOLDS_ANIS": reg_fit_r9_anis,
            },
            "parsed_registrations": {
                "r4_preregistration_c1": {
                    "source": "ref/research/negative_control_round4_preregistration.md:24-28",
                    "section": "## C1 — the fit verdict, re-registered and NULL-CENTERED",
                    "rows": {
                        "phenix path": "d_phenix",
                        "gemmi path": "d_gemmi",
                        "REFMAC": "d_refmac",
                    },
                    "thresholds": prereg_r4_map,
                },
                "registry_section_6_isot_history": {
                    "source": "ref/thresholds_and_standards.md:262",
                    "section": "## 6. Negative-control verdict rules",
                    "rule_row": "FIT thresholds — ISOT convention (history, rounds 3–8)",
                    "thresholds": registry_s6["isot_r7"],
                    "retired_r4_thresholds": registry_s6["retired_r4"],
                },
                "registry_section_6_anis_current": {
                    "source": "ref/thresholds_and_standards.md:263",
                    "section": "## 6. Negative-control verdict rules",
                    "rule_row": "FIT thresholds — ANIS convention (current, round 9 on)",
                    "thresholds": registry_s6["anis_r9"],
                },
                "bench_recover_leg_ast": {
                    "source": "scripts/bench_recover_leg.py:44-55",
                    "REGISTERED_FIT_THRESHOLDS": reg_fit_r7,
                    "REGISTERED_FIT_THRESHOLDS_ANIS": reg_fit_r9_anis,
                    "MAD_FLOOR": mad_floor,
                },
                "r9_j2_anis_summary": {
                    "source": "ref/research/data/negative_control_round9_anis.json#/j2_anis",
                    **j2_anis_summary,
                },
            },
            "research_file_inventory": inventory,
        },
    }


def generate_all(out_dir: Path) -> dict[str, Any]:
    """Render all seven figures and write figures.json under out_dir."""
    configure_matplotlib()
    source_hashes: dict[str, str] = {}
    figures = [
        build_fig01_cohort_resolution(out_dir, source_hashes),
        build_fig02_r9_null_delta_rfree(out_dir, source_hashes),
        build_fig03_r9_isot_vs_anis_paired(out_dir, source_hashes),
        build_fig04_r10_recovery_delta_rfree(out_dir, source_hashes),
        build_fig05_bond_rmsd_abc(out_dir, source_hashes),
        build_fig06_round46_rotamer_outlier_pct(out_dir, source_hashes),
        build_fig07_threshold_evidence_history(out_dir, source_hashes),
    ]
    manifest = {
        "package": "data/coscientists/openscientist/slides_2026-11-06",
        "source_revision": SOURCE_REVISION,
        "canvas": {
            "logical_px": [LOGICAL_WIDTH_PX, LOGICAL_HEIGHT_PX],
            "render_scale": RENDER_SCALE,
            "rendered_px": list(EXPECTED_PNG_SIZE),
            "dpi": DPI,
            "font_family": "DejaVu Sans",
            "min_font_pt_at_100dpi": 18.0,
            "min_font_px_at_1x": 25.0,
            "palette": {
                "background": BG_COLOR,
                "panel_background": PANEL_BG,
                "ink": INK_COLOR,
                "muted": MUTED_COLOR,
                "accent": ACCENT_COLOR,
                "PHENIX": {"color": COLOR_PHENIX, "marker": "circle (o)"},
                "Gemmi": {"color": COLOR_GEMMI, "marker": "diamond (D)"},
                "REFMAC": {"color": COLOR_REFMAC, "marker": "triangle (^ / v)"},
                "wwPDB": {"color": COLOR_WWPDB, "marker": "square (s)"},
                "reference_cohort": {"color": COLOR_COHORT, "marker": "circle (o)"},
            },
        },
        "source_blobs": [
            {"path": k, "revision": SOURCE_REVISION, "sha256": v}
            for k, v in sorted(source_hashes.items())
        ],
        "figures": figures,
    }
    manifest_path = out_dir / "figures.json"
    manifest_bytes = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )
    manifest_path.write_bytes(manifest_bytes)
    return manifest


def check_deterministic(target_dir: Path) -> None:
    """Re-render into a fresh temporary directory and verify byte-for-byte SHA-256 identity."""
    existing_manifest_path = target_dir / "figures.json"
    if not existing_manifest_path.is_file():
        raise SystemExit(f"Missing manifest: {existing_manifest_path}")
    existing_manifest_bytes = existing_manifest_path.read_bytes()
    existing_manifest = json.loads(existing_manifest_bytes.decode("utf-8"))

    with tempfile.TemporaryDirectory(prefix="slides_2026_11_06_check_") as tmp:
        tmp_dir = Path(tmp)
        fresh_manifest = generate_all(tmp_dir)
        fresh_manifest_bytes = (tmp_dir / "figures.json").read_bytes()
        if fresh_manifest_bytes != existing_manifest_bytes:
            raise SystemExit(
                "Determinism check FAILED: regenerated figures.json differs from committed file."
            )
        for fig_entry in existing_manifest["figures"]:
            rel_file = fig_entry["file"]
            committed_png = target_dir / rel_file
            fresh_png = tmp_dir / rel_file
            if not committed_png.is_file():
                raise SystemExit(f"Missing committed PNG: {committed_png}")
            c_sha = hashlib.sha256(committed_png.read_bytes()).hexdigest()
            f_sha = hashlib.sha256(fresh_png.read_bytes()).hexdigest()
            if c_sha != fig_entry["sha256"] or c_sha != f_sha:
                raise SystemExit(
                    f"Determinism check FAILED for {rel_file}: committed={c_sha}, fresh={f_sha}, manifest={fig_entry['sha256']}"
                )
    print(
        f"OK: {len(fresh_manifest['figures'])} figures and figures.json verified deterministic at {SOURCE_REVISION[:12]}."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DECK_DIR,
        help="Output directory for figures.json and figures/*.png (default: deck folder).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify that committed figures.json and figures/*.png match a fresh deterministic render.",
    )
    args = parser.parse_args(argv)
    if args.check:
        check_deterministic(args.out_dir.resolve())
    else:
        manifest = generate_all(args.out_dir.resolve())
        print(
            f"Generated {len(manifest['figures'])} figures and figures.json in {args.out_dir.resolve()}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
