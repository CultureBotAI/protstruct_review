#!/usr/bin/env python3
"""Focused consistency and provenance tests for data/coscientists/openscientist/slides_2026-11-06."""

from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import statistics
import struct
import subprocess
import sys
import tempfile
from typing import Any
import unittest
import zlib

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = REPO_ROOT / "data" / "coscientists" / "openscientist" / "slides_2026-11-06"
SOURCE_REVISION = "f3cfad326f28ddbf652dcdb0c5858443bee6e413"
EXPECTED_DIMENSIONS = [3328, 1360]
EXPECTED_SLIDE_IDS = [
    "S01",
    "S02",
    "S03",
    "S04",
    "S05",
    "S06",
    "S07",
    "S08",
    "S09",
    "S09a",
    "S09f",
    "S09b",
    "S10",
    "S11",
    "S12",
    "S13a",
    "S13",
    "S13b",
    "S14a",
    "S14",
    "S14b",
    "S15a",
    "S15",
    "S15b",
    "S16a",
    "S16",
    "S16b",
    "S17a",
    "S17",
    "S17b",
    "S18a",
    "S18",
    "S18b",
    "S19",
    "S20",
    "S21",
    "S22",
    "S23",
    "S24",
]
NEW_PACKAGE_ARTIFACTS = (
    "slides_2026-11-06/questions.md",
    "slides_2026-11-06/figures.json",
    "slides_2026-11-06/build_figures.py",
    "slides_2026-11-06/figures/",
    "ref/research/geometry_tool_presence_2026-11-06.json",
)


def read_png_dimensions(path: Path) -> list[int]:
    """Read width and height from a PNG IHDR chunk using the standard library."""
    raw = path.read_bytes()
    if len(raw) < 24 or raw[:8] != b"\x89PNG\r\n\x1a\n" or raw[12:16] != b"IHDR":
        raise ValueError(f"{path} is not a valid PNG file")
    width, height = struct.unpack(">II", raw[16:24])
    return [int(width), int(height)]


def git_blob_bytes(rel_path: str, rev: str = SOURCE_REVISION) -> bytes:
    """Read a committed blob at rev:rel_path via git show."""
    proc = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", f"{rev}:{rel_path}"],
        check=True,
        capture_output=True,
    )
    return proc.stdout


class TestSlides20261106Package(unittest.TestCase):
    """Verify structure, provenance, figures, and constraints of slides_2026-11-06."""

    def test_required_files_exist(self) -> None:
        for name in (
            "outline.md",
            "slides.md",
            "questions.md",
            "README.md",
            "build_figures.py",
            "figures.json",
        ):
            path = PACKAGE_DIR / name
            self.assertTrue(path.is_file(), f"Missing required package file: {path}")

        presence_path = REPO_ROOT / "ref" / "research" / "geometry_tool_presence_2026-11-06.json"
        self.assertTrue(
            presence_path.is_file(),
            f"Missing metadata-only geometry tool presence record: {presence_path}",
        )
        presence_payload = json.loads(presence_path.read_text(encoding="utf-8"))
        self.assertEqual(
            set(presence_payload.keys()),
            {"checked_at", "method", "overrides", "tools", "schrodinger_openeye"},
        )
        self.assertIsInstance(presence_payload["checked_at"], str)
        self.assertIsInstance(presence_payload["method"], str)
        self.assertIsInstance(presence_payload["overrides"], list)
        self.assertIsInstance(presence_payload["schrodinger_openeye"], str)
        tools_list = presence_payload["tools"]
        self.assertIsInstance(tools_list, list)
        self.assertEqual(len(tools_list), 5)
        expected_tool_fields = {"tool", "configured_path", "exists", "executable", "resolved_path"}
        seen_tools: list[str] = []
        for entry in tools_list:
            self.assertEqual(set(entry.keys()), expected_tool_fields)
            self.assertIsInstance(entry["tool"], str)
            self.assertTrue(entry["tool"].strip())
            self.assertIsInstance(entry["configured_path"], str)
            self.assertIsInstance(entry["resolved_path"], str)
            self.assertIsInstance(entry["exists"], bool)
            self.assertIsInstance(entry["executable"], bool)
            seen_tools.append(entry["tool"])
        self.assertEqual(len(seen_tools), len(set(seen_tools)))
        self.assertEqual(
            seen_tools,
            ["phenix.amber", "phenix.elbow", "phenix.ready_set", "acedrg", "libcheck"],
        )

    def test_outline_and_slides_structure_and_bounds(self) -> None:
        outline_text = (PACKAGE_DIR / "outline.md").read_text(encoding="utf-8")
        slides_text = (PACKAGE_DIR / "slides.md").read_text(encoding="utf-8")
        questions_text = (PACKAGE_DIR / "questions.md").read_text(encoding="utf-8")

        # 5 sections in outline.md, each with a one-sentence Section summary
        section_headers = re.findall(r"^## Section (\d+) — .+$", outline_text, flags=re.M)
        self.assertEqual(section_headers, ["1", "2", "3", "4", "5"])
        section_summaries = re.findall(
            r"^\*\*Section summary\*\*: (.+)$", outline_text, flags=re.M
        )
        self.assertEqual(len(section_summaries), 5)
        for summary in section_summaries:
            self.assertTrue(summary.strip().endswith("."))

        # Outline slide entries with dual titles (title_general and subtitle_technical)
        outline_slides = re.findall(
            r"^\d+\.\s+\*\*`(S\d{2}[abf]?)`\s+\(`(S\d{2}[abf]?-[a-z0-9-]+)`\)\*\*(?:\s+\*\([^*\n]+\)\*)?\n"
            r"\s+-\s+\*\*title_general\*\*:\s+(.+)\n"
            r"\s+-\s+\*\*subtitle_technical\*\*:\s+(.+)$",
            outline_text,
            flags=re.M,
        )
        self.assertEqual(len(outline_slides), len(EXPECTED_SLIDE_IDS))
        self.assertEqual([item[0] for item in outline_slides], EXPECTED_SLIDE_IDS)

        # Parse slides.md blocks
        slide_blocks = re.split(
            r"(?m)^### Slide (S\d{2}[abf]?) \(`(S\d{2}[abf]?-[a-z0-9-]+)`\)\n",
            slides_text,
        )
        parsed_slides: list[tuple[str, str, str]] = []
        for idx in range(1, len(slide_blocks), 3):
            parsed_slides.append(
                (slide_blocks[idx], slide_blocks[idx + 1], slide_blocks[idx + 2])
            )
        self.assertEqual(len(parsed_slides), len(EXPECTED_SLIDE_IDS))

        figure_slides_seen: dict[str, str] = {}
        for (o_id, o_slug, o_title_gen, o_sub_tech), (s_id, s_slug, block) in zip(
            outline_slides, parsed_slides, strict=True
        ):
            self.assertEqual(o_id, s_id)
            self.assertEqual(o_slug, s_slug)
            self.assertTrue(
                o_title_gen.strip().endswith("."),
                f"Outline title_general for {o_id} must be a declarative sentence ending in '.': {o_title_gen}",
            )
            self.assertGreater(
                len(o_sub_tech.strip()),
                10,
                f"Outline subtitle_technical too short in {o_id}",
            )

            id_m = re.search(
                r"^- \*\*Slide ID\*\*: `(S\d{2}[abf]?)` \(`(S\d{2}[abf]?-[a-z0-9-]+)`\)$",
                block,
                flags=re.M,
            )
            self.assertIsNotNone(id_m, f"Missing or malformed Slide ID line in {s_id}")
            assert id_m is not None
            self.assertEqual((id_m.group(1), id_m.group(2)), (s_id, s_slug))

            sec_m = re.search(r"^- \*\*Section\*\*: `Section \d+ — [^`]+`$", block, flags=re.M)
            self.assertIsNotNone(sec_m, f"Missing Section line in {s_id}")

            title_gen_m = re.search(r"^- \*\*title_general\*\*: (.+)$", block, flags=re.M)
            self.assertIsNotNone(title_gen_m, f"Missing title_general in {s_id}")
            assert title_gen_m is not None
            self.assertEqual(title_gen_m.group(1).strip(), o_title_gen.strip())

            sub_tech_m = re.search(r"^- \*\*subtitle_technical\*\*: (.+)$", block, flags=re.M)
            self.assertIsNotNone(sub_tech_m, f"Missing subtitle_technical in {s_id}")
            assert sub_tech_m is not None
            self.assertEqual(sub_tech_m.group(1).strip(), o_sub_tech.strip())

            msg_m = re.search(r"^- \*\*One-line message\*\*: (.+)$", block, flags=re.M)
            self.assertIsNotNone(msg_m, f"Missing One-line message in {s_id}")
            assert msg_m is not None
            self.assertGreater(len(msg_m.group(1).strip()), 20)

            body_m = re.search(
                r"^- \*\*Slide body\*\*:\n((?:  .+\n)+)",
                block,
                flags=re.M,
            )
            self.assertIsNotNone(body_m, f"Missing Slide body in {s_id}")
            assert body_m is not None
            body_text = body_m.group(1)

            if s_id.endswith("a"):
                terms_m = re.search(
                    r"^- \*\*Terms\*\*:\n((?:  - .+\n)+)",
                    block,
                    flags=re.M,
                )
                self.assertIsNotNone(terms_m, f"Intro slide {s_id} missing Terms block")
                assert terms_m is not None
                term_lines = [
                    ln.strip()
                    for ln in terms_m.group(1).splitlines()
                    if ln.strip().startswith("- ")
                ]
                self.assertGreaterEqual(
                    len(term_lines), 4, f"Intro slide {s_id} has too few Terms entries"
                )
                self.assertIn("**The experiment**:", body_text, f"Intro {s_id} missing The experiment")
                self.assertIn(
                    "**Reading the figure**:", body_text, f"Intro {s_id} missing Reading the figure"
                )
            elif s_id.endswith("b"):
                top_bullets = [
                    ln for ln in body_text.splitlines() if re.match(r"^  - \S", ln)
                ]
                self.assertGreaterEqual(
                    len(top_bullets),
                    3,
                    f"Results slide {s_id} must have 3-5 bullets, got {len(top_bullets)}",
                )
                self.assertLessEqual(
                    len(top_bullets),
                    5,
                    f"Results slide {s_id} must have 3-5 bullets, got {len(top_bullets)}",
                )

            fig_m = re.search(r"^- \*\*Figure\*\*: `([^`]+)`", block, flags=re.M)
            self.assertIsNotNone(fig_m, f"Missing Figure line in {s_id}")
            assert fig_m is not None
            fig_ref = fig_m.group(1).strip()
            if fig_ref != "None":
                fig_path = PACKAGE_DIR / fig_ref
                self.assertTrue(
                    fig_path.is_file(), f"Slide {s_id} references missing figure {fig_ref}"
                )
                figure_slides_seen[s_id] = fig_ref

            # Sources section must be non-empty, pinned to SOURCE_REVISION, and not list new package files
            sources_m = re.search(
                r"^- \*\*Sources\*\* \(pinned to `"
                + re.escape(SOURCE_REVISION)
                + r"`\):\n((?:  - .+\n)+)",
                block,
                flags=re.M,
            )
            self.assertIsNotNone(sources_m, f"Missing or unpinned Sources block in {s_id}")
            assert sources_m is not None
            source_lines = [
                line.strip()
                for line in sources_m.group(1).splitlines()
                if line.strip().startswith("- ")
            ]
            self.assertGreaterEqual(len(source_lines), 1, f"Slide {s_id} has no source items")
            for src_line in source_lines:
                for pkg_artifact in NEW_PACKAGE_ARTIFACTS:
                    self.assertNotIn(
                        pkg_artifact,
                        src_line,
                        f"New package artifact {pkg_artifact} must be in Package artifacts, not pinned Sources, on {s_id}",
                    )

            # Speaker notes must be non-empty and <= 1,500 chars
            notes_m = re.search(
                r"^- \*\*Speaker notes\*\*:\n((?:  .+\n?)+)", block, flags=re.M
            )
            self.assertIsNotNone(notes_m, f"Missing Speaker notes in {s_id}")
            assert notes_m is not None
            notes_text = " ".join(line.strip() for line in notes_m.group(1).splitlines()).strip()
            self.assertGreater(len(notes_text), 50, f"Speaker notes too short in {s_id}")
            self.assertLessEqual(
                len(notes_text),
                1500,
                f"Speaker notes in {s_id} exceed 1,500 chars ({len(notes_text)})",
            )

        self.assertEqual(
            figure_slides_seen,
            {
                "S09f": "figures/fig07_threshold_evidence_history.png",
                "S13": "figures/fig01_cohort_resolution.png",
                "S14": "figures/fig02_r9_null_delta_rfree.png",
                "S15": "figures/fig03_r9_isot_vs_anis_paired.png",
                "S16": "figures/fig04_r10_recovery_delta_rfree.png",
                "S17": "figures/fig05_bond_rmsd_abc.png",
                "S18": "figures/fig06_round46_rotamer_outlier_pct.png",
            },
        )

        # Check [USER INPUT: Q<N>] placeholders distinguish open Q1/Q2/Q4 from decided Q3
        slide_q_ids = sorted(set(re.findall(r"\[USER INPUT:\s*(Q\d+)\b", slides_text)))
        outline_q_ids = sorted(set(re.findall(r"\[USER INPUT:\s*(Q\d+)\b", outline_text)))
        question_q_ids = sorted(set(re.findall(r"^## `(Q\d+)`", questions_text, flags=re.M)))
        open_q_ids = sorted(
            re.findall(
                r"^## `(Q\d+)`[^\n]*\n- \*\*Status\*\*: `OPEN`",
                questions_text,
                flags=re.M,
            )
        )
        decided_q_ids = sorted(
            re.findall(
                r"^## `(Q\d+)`[^\n]*\n- \*\*Status\*\*: `DECIDED`",
                questions_text,
                flags=re.M,
            )
        )
        self.assertEqual(question_q_ids, ["Q1", "Q2", "Q3", "Q4"])
        self.assertEqual(open_q_ids, ["Q1", "Q2", "Q4"])
        self.assertEqual(decided_q_ids, ["Q3"])
        self.assertEqual(slide_q_ids, ["Q1", "Q2", "Q4"])
        self.assertEqual(outline_q_ids, ["Q1", "Q2", "Q4"])

        # Ensure prohibited stale values / invented paths / uncalibrated W4 headlines are absent
        for filename in ("outline.md", "slides.md", "questions.md", "README.md", "figures.json"):
            content = (PACKAGE_DIR / filename).read_text(encoding="utf-8")
            self.assertNotIn("0.0053", content, f"Stale 2VXN value 0.0053 found in {filename}")
            self.assertNotIn("0.0067", content, f"Stale 2VXN value 0.0067 found in {filename}")
            self.assertNotIn("w4_contradiction", content, f"w4_contradiction found in {filename}")
            self.assertNotIn(
                "slides_2026-09-23",
                content,
                f"Invented deck path slides_2026-09-23 found in {filename}",
            )

    def test_figures_manifest_hashes_dimensions_and_sources(self) -> None:
        manifest = json.loads((PACKAGE_DIR / "figures.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["source_revision"], SOURCE_REVISION)
        self.assertEqual(manifest["canvas"]["rendered_px"], EXPECTED_DIMENSIONS)

        figures = manifest["figures"]
        self.assertEqual(len(figures), 7)
        fig_by_id = {fig["id"]: fig for fig in figures}
        self.assertEqual(
            set(fig_by_id.keys()),
            {
                "fig01_cohort_resolution",
                "fig02_r9_null_delta_rfree",
                "fig03_r9_isot_vs_anis_paired",
                "fig04_r10_recovery_delta_rfree",
                "fig05_bond_rmsd_abc",
                "fig06_round46_rotamer_outlier_pct",
                "fig07_threshold_evidence_history",
            },
        )

        for fig_id, fig in fig_by_id.items():
            fig_path = PACKAGE_DIR / fig["file"]
            self.assertTrue(fig_path.is_file(), f"Missing figure file: {fig_path}")
            actual_sha = hashlib.sha256(fig_path.read_bytes()).hexdigest()
            self.assertEqual(
                actual_sha,
                fig["sha256"],
                f"SHA-256 mismatch for {fig['file']}",
            )
            dims = read_png_dimensions(fig_path)
            self.assertEqual(dims, EXPECTED_DIMENSIONS)
            self.assertEqual(fig["dimensions_px"], EXPECTED_DIMENSIONS)
            if fig_id != "fig07_threshold_evidence_history":
                self.assertGreater(len(fig["pdb_ids"]), 0)
            self.assertGreater(len(fig["record_selectors"]), 0)

            for src in fig["sources"]:
                self.assertEqual(src["revision"], SOURCE_REVISION)
                blob = git_blob_bytes(src["path"], SOURCE_REVISION)
                blob_sha = hashlib.sha256(blob).hexdigest()
                self.assertEqual(
                    blob_sha,
                    src["sha256"],
                    f"Committed blob SHA-256 mismatch for {src['path']}",
                )

        # Cross-check key derived summaries against committed records by figure ID
        f0 = fig_by_id["fig01_cohort_resolution"]["derived_summaries"]
        self.assertEqual(f0["all_enrolled_d_min_a"]["n"], 22)
        self.assertAlmostEqual(f0["all_enrolled_d_min_a"]["min"], 0.79, places=5)
        self.assertAlmostEqual(f0["all_enrolled_d_min_a"]["median"], 0.895, places=5)
        self.assertAlmostEqual(f0["all_enrolled_d_min_a"]["max"], 1.00, places=5)
        self.assertEqual(f0["actual_le_0_90_d_min_a"]["n"], 15)
        self.assertEqual(f0["actual_gt_0_90_d_min_a"]["n"], 7)
        self.assertEqual(f0["stored_stratum_true_d_min_a"]["n"], 20)
        self.assertEqual(f0["stored_stratum_false_d_min_a"]["n"], 2)
        self.assertEqual(f0["screen_attrition"]["n_attempts"], 58)
        self.assertEqual(f0["screen_attrition"]["n_enrolled"], 22)

        f1 = fig_by_id["fig02_r9_null_delta_rfree"]["derived_summaries"]
        self.assertAlmostEqual(f1["phenix_native_n22"]["median"], 0.00330, places=6)
        self.assertAlmostEqual(f1["gemmi_native_n22"]["median"], 0.00365, places=6)
        self.assertAlmostEqual(f1["refmac_anis_native_n21"]["median"], 0.00370, places=6)

        f2 = fig_by_id["fig03_r9_isot_vs_anis_paired"]["derived_summaries"]
        self.assertAlmostEqual(f2["refmac_isot_n21"]["median"], 0.00180, places=6)
        self.assertAlmostEqual(f2["refmac_anis_n21"]["median"], 0.00370, places=6)
        self.assertEqual(f2["direction_agreement"]["isot"]["agree"], 17)
        self.assertEqual(f2["direction_agreement"]["anis"]["agree"], 20)

        f3 = fig_by_id["fig04_r10_recovery_delta_rfree"]["derived_summaries"]
        self.assertAlmostEqual(f3["phenix_native_n22"]["median"], 0.00630, places=6)
        self.assertAlmostEqual(f3["gemmi_native_n22"]["median"], 0.00800, places=6)
        self.assertAlmostEqual(f3["refmac_anis_native_n21"]["median"], 0.00730, places=6)

        fig05 = fig_by_id["fig05_bond_rmsd_abc"]
        f4 = fig05["derived_summaries"]
        self.assertAlmostEqual(f4["a_phenix_cdl_all_n17"]["median"], 0.00872, places=6)
        self.assertAlmostEqual(f4["b_phenix_eh_all_n17"]["median"], 0.00914, places=6)
        self.assertAlmostEqual(f4["c_gemmi_ccp4_all_n17"]["median"], 0.01100, places=6)
        self.assertEqual(fig05["n_groups"]["equal_bond_count_subset"], 6)
        self.assertEqual(fig05["n_groups"]["different_bond_count_subset"], 11)

        fig06 = fig_by_id["fig06_round46_rotamer_outlier_pct"]
        f5 = fig06["derived_summaries"]
        self.assertEqual(f5["phenix_rota_outlier_pct_n41"]["n"], 41)
        self.assertEqual(fig06["excluded_pdb_ids"], ["12CI"])
        self.assertEqual(f5["shared_rotamer_outlier_verdict_agreement_all_41"], 1.0)

    def test_fig07_ledger_inventory_and_threshold_history_and_guards(self) -> None:
        """Independently verify fig07 ledger counts, research file inventory, R4/R7/R9 threshold history, and #996 guards."""
        manifest = json.loads((PACKAGE_DIR / "figures.json").read_text(encoding="utf-8"))
        fig_by_id = {fig["id"]: fig for fig in manifest["figures"]}
        fig07 = fig_by_id["fig07_threshold_evidence_history"]
        ds = fig07["derived_summaries"]

        # 1. Independently parse pinned ref/threshold_evidence_status.yaml at SOURCE_REVISION
        ledger_doc = yaml.safe_load(
            git_blob_bytes("ref/threshold_evidence_status.yaml", SOURCE_REVISION).decode("utf-8")
        )
        rows = ledger_doc["rows"]
        self.assertEqual(len(rows), 21)
        sec3_rows = [r for r in rows if int(r["section"]) == 3]
        sec4_rows = [r for r in rows if int(r["section"]) == 4]
        self.assertEqual(len(sec3_rows), 17)
        self.assertEqual(len(sec4_rows), 4)

        ev_counts: dict[str, int] = {}
        pol_counts: dict[str, int] = {}
        comp_records: list[dict[str, Any]] = []
        for r in rows:
            for c in r["components"]:
                ev = str(c["evidence_state"])
                pol = str(c["policy_state"])
                ev_counts[ev] = ev_counts.get(ev, 0) + 1
                pol_counts[pol] = pol_counts.get(pol, 0) + 1
                comp_records.append(
                    {
                        "component_key": f"{r['id']}.{c['id']}",
                        "row_id": r["id"],
                        "section": int(r["section"]),
                        "component_id": c["id"],
                        "evidence_state": ev,
                        "policy_state": pol,
                        "scope": c["scope"],
                    }
                )
        self.assertEqual(len(comp_records), 41)
        self.assertEqual(sum(ev_counts.values()), 41)
        self.assertEqual(sum(pol_counts.values()), 41)
        self.assertEqual(
            ev_counts,
            {
                "retained_record": 23,
                "unmeasured": 9,
                "partial_record": 4,
                "denominator_unproven": 1,
                "external_standard_cited": 1,
                "limited_controls": 1,
                "producer_mismatch": 1,
                "unverified_ancillary": 1,
            },
        )
        self.assertEqual(
            pol_counts,
            {
                "active_conditional": 29,
                "informational": 6,
                "provisional_informational": 2,
                "not_evaluable": 1,
                "policy_unresolved": 1,
                "provisional_conditional": 1,
                "suspended": 1,
            },
        )
        self.assertEqual(ds["n_rows"], 21)
        self.assertEqual(ds["rows_by_section"], {"3": 17, "4": 4})
        self.assertEqual(ds["n_components"], 41)
        self.assertEqual(ds["evidence_state"], ev_counts)
        self.assertEqual(ds["policy_state"], pol_counts)
        self.assertEqual(ds["components"], comp_records)

        # 2. Independently enumerate committed ref/research paths via git ls-tree at SOURCE_REVISION
        ls_proc = subprocess.run(
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
        all_paths = sorted(ln.strip() for ln in ls_proc.stdout.splitlines() if ln.strip())
        tol_glob = [
            p for p in all_paths if re.fullmatch(r"ref/research/tolerance_benchmark_round[^/]*\.md", p)
        ]
        tol_num = [
            p for p in all_paths if re.fullmatch(r"ref/research/tolerance_benchmark_round\d+\.md", p)
        ]
        tol_pre = [
            p
            for p in all_paths
            if re.fullmatch(r"ref/research/tolerance_benchmark_round\d+_preregistration\.md", p)
        ]
        nc_num = [
            p for p in all_paths if re.fullmatch(r"ref/research/negative_control_round\d+\.md", p)
        ]
        all_pre = [
            p for p in all_paths if re.fullmatch(r"ref/research/[^/]*preregistration[^/]*\.md", p)
        ]
        self.assertEqual(len(tol_glob), 60)
        self.assertEqual(len(tol_num), 40)
        self.assertEqual(len(tol_pre), 20)
        self.assertEqual(len(nc_num), 11)
        self.assertEqual(len(all_pre), 34)
        self.assertEqual(sorted(tol_num + tol_pre), tol_glob)
        self.assertTrue(set(tol_pre).issubset(set(all_pre)))

        inv = ds["research_file_inventory"]
        self.assertEqual(inv["source_revision"], SOURCE_REVISION)
        self.assertEqual(
            inv["file_counts"],
            {
                "tolerance_glob": 60,
                "tolerance_numbered_reports": 40,
                "tolerance_preregistrations": 20,
                "negative_control_numbered_reports": 11,
                "preregistration_named_markdown": 34,
            },
        )
        self.assertEqual(inv["counted_paths"]["tolerance_glob"], tol_glob)
        self.assertEqual(inv["counted_paths"]["tolerance_numbered_reports"], tol_num)
        self.assertEqual(inv["counted_paths"]["tolerance_preregistrations"], tol_pre)
        self.assertEqual(inv["counted_paths"]["negative_control_numbered_reports"], nc_num)
        self.assertEqual(inv["counted_paths"]["preregistration_named_markdown"], all_pre)

        # 3. Independently recompute R4 / R7 / R9 §6 FIT thresholds from raw JSON blobs
        r3_doc = json.loads(
            git_blob_bytes("ref/research/data/negative_control_round3_bench.json").decode("utf-8")
        )
        r6_doc = json.loads(
            git_blob_bytes("ref/research/data/negative_control_round6_hygiene.json").decode("utf-8")
        )
        r9_doc = json.loads(
            git_blob_bytes("ref/research/data/negative_control_round9_anis.json").decode("utf-8")
        )
        recover_text = git_blob_bytes("scripts/bench_recover_leg.py").decode("utf-8")
        thresh_text = git_blob_bytes("ref/thresholds_and_standards.md").decode("utf-8")
        r4_prereg_text = git_blob_bytes(
            "ref/research/negative_control_round4_preregistration.md"
        ).decode("utf-8")

        def _indep_fit_threshold(deltas: list[float], floor: float = 0.0005) -> dict[str, Any]:
            med = float(statistics.median(deltas))
            mad = float(statistics.median([abs(x - med) for x in deltas]))
            floored_mad = float(max(mad, floor))
            return {
                "n": len(deltas),
                "median": med,
                "mad": mad,
                "floored_mad": floored_mad,
                "threshold": round(med + 3.0 * floored_mad, 5),
            }

        def _assert_stat_block_matches(
            actual: dict[str, Any], expected: dict[str, Any], label: str
        ) -> None:
            expected_fields = {"n", "median", "mad", "floored_mad", "threshold"}
            self.assertEqual(set(actual.keys()), expected_fields, f"{label}: unexpected field set")
            self.assertEqual(set(expected.keys()), expected_fields)
            self.assertEqual(actual["n"], expected["n"], f"{label}: n mismatch")
            self.assertEqual(
                actual["threshold"], expected["threshold"], f"{label}: threshold mismatch"
            )
            for stat_key in ("median", "mad", "floored_mad"):
                self.assertAlmostEqual(
                    float(actual[stat_key]),
                    float(expected[stat_key]),
                    delta=1e-12,
                    msg=f"{label}.{stat_key} mismatch",
                )

        def _assert_round_map_matches(
            actual_map: dict[str, dict[str, Any]],
            expected_map: dict[str, dict[str, Any]],
            round_label: str,
        ) -> None:
            expected_tools = ("d_phenix", "d_gemmi", "d_refmac")
            self.assertEqual(set(actual_map.keys()), set(expected_tools))
            self.assertEqual(set(expected_map.keys()), set(expected_tools))
            for tk in expected_tools:
                _assert_stat_block_matches(
                    actual_map[tk], expected_map[tk], f"{round_label}.{tk}"
                )

        benched_nulls = [
            r for r in r3_doc["rows"] if r.get("subject") == "null" and r.get("status") == "benched"
        ]
        self.assertEqual(len(benched_nulls), 22)
        clean_8r5k = r6_doc["g3_8r5k_rescreen"]["clean_null_deltas"]

        indep_r4: dict[str, dict[str, Any]] = {}
        indep_r7: dict[str, dict[str, Any]] = {}
        for tk in ("d_phenix", "d_gemmi", "d_refmac"):
            v4 = [float(r["numbers"][tk]) for r in benched_nulls if r["numbers"].get(tk) is not None]
            v7 = [
                float(clean_8r5k[tk] if r["pdb_id"] == "8R5K" else r["numbers"][tk])
                for r in benched_nulls
                if (clean_8r5k[tk] if r["pdb_id"] == "8R5K" else r["numbers"].get(tk)) is not None
            ]
            indep_r4[tk] = _indep_fit_threshold(v4)
            indep_r7[tk] = _indep_fit_threshold(v7)

        v9_anis_ref = [
            float(r["refmac"]["anis"]["delta"])
            for r in r9_doc["rows"]
            if isinstance(r.get("refmac"), dict)
            and isinstance(r["refmac"].get("anis"), dict)
            and r["refmac"]["anis"].get("delta") is not None
        ]
        indep_r9 = {
            "d_phenix": dict(indep_r7["d_phenix"]),
            "d_gemmi": dict(indep_r7["d_gemmi"]),
            "d_refmac": _indep_fit_threshold(v9_anis_ref),
        }

        self.assertEqual(
            {k: (v["threshold"], v["n"]) for k, v in indep_r4.items()},
            {"d_phenix": (0.01220, 22), "d_gemmi": (0.01090, 22), "d_refmac": (0.00540, 19)},
        )
        self.assertEqual(
            {k: (v["threshold"], v["n"]) for k, v in indep_r7.items()},
            {"d_phenix": (0.01200, 22), "d_gemmi": (0.01025, 22), "d_refmac": (0.00560, 20)},
        )
        self.assertEqual(
            {k: (v["threshold"], v["n"]) for k, v in indep_r9.items()},
            {"d_phenix": (0.01200, 22), "d_gemmi": (0.01025, 22), "d_refmac": (0.01150, 21)},
        )
        _assert_round_map_matches(ds["R4"], indep_r4, "R4")
        _assert_round_map_matches(ds["R7"], indep_r7, "R7")
        _assert_round_map_matches(ds["R9"], indep_r9, "R9")
        _assert_stat_block_matches(ds["R9_ANIS_REF"], indep_r9["d_refmac"], "R9_ANIS_REF")
        self.assertNotIn("r9_isot_comparison_only_not_registered", ds)
        self.assertEqual(
            fig07["n_groups"],
            {
                "ledger_rows_total": 21,
                "ledger_rows_section_3": 17,
                "ledger_rows_section_4": 4,
                "ledger_components_total": 41,
                "r4_null_phenix": 22,
                "r4_null_gemmi": 22,
                "r4_null_refmac_isot": 19,
                "r7_null_phenix": 22,
                "r7_null_gemmi": 22,
                "r7_null_refmac_isot": 20,
                "r9_null_refmac_anis": 21,
            },
        )
        self.assertGreaterEqual(len(fig07["record_selectors"]), 9)
        preg = ds["parsed_registrations"]
        self.assertEqual(
            preg["r4_preregistration_c1"]["thresholds"],
            {k: v["threshold"] for k, v in indep_r4.items()},
        )
        self.assertEqual(
            preg["registry_section_6_isot_history"]["retired_r4_thresholds"],
            {k: v["threshold"] for k, v in indep_r4.items()},
        )
        self.assertEqual(
            preg["registry_section_6_isot_history"]["thresholds"],
            {k: v["threshold"] for k, v in indep_r7.items()},
        )
        self.assertEqual(
            preg["registry_section_6_anis_current"]["thresholds"],
            {k: v["threshold"] for k, v in indep_r9.items()},
        )
        self.assertEqual(
            preg["r9_j2_anis_summary"]["d_refmac_anis"],
            indep_r9["d_refmac"]["threshold"],
        )

        # 4. Compile real fig07 verification and builder functions from build_figures.py AST and prove #996 guards
        bf_source = (PACKAGE_DIR / "build_figures.py").read_text(encoding="utf-8")
        bf_tree = ast.parse(bf_source, filename=str(PACKAGE_DIR / "build_figures.py"))
        needed_fn_names = {
            "_extract_ast_constants",
            "_compute_null_threshold",
            "_parse_r4_prereg_thresholds",
            "_parse_registry_section6_fit_thresholds",
            "_compute_and_verify_section6_fit_history",
            "build_fig07_threshold_evidence_history",
        }
        fn_nodes = [
            node
            for node in bf_tree.body
            if isinstance(node, ast.FunctionDef) and node.name in needed_fn_names
        ]
        self.assertEqual({n.name for n in fn_nodes}, needed_fn_names)
        mod_ast = ast.Module(body=fn_nodes, type_ignores=[])
        ast.fix_missing_locations(mod_ast)

        blob_store = {
            "ref/threshold_evidence_status.yaml": (
                git_blob_bytes("ref/threshold_evidence_status.yaml"),
                "sha_ledger",
            ),
            "ref/research/data/negative_control_round3_bench.json": (
                git_blob_bytes("ref/research/data/negative_control_round3_bench.json"),
                "sha_r3",
            ),
            "ref/research/data/negative_control_round6_hygiene.json": (
                git_blob_bytes("ref/research/data/negative_control_round6_hygiene.json"),
                "sha_r6",
            ),
            "ref/research/data/negative_control_round9_anis.json": (
                git_blob_bytes("ref/research/data/negative_control_round9_anis.json"),
                "sha_r9",
            ),
            "scripts/bench_recover_leg.py": (recover_text.encode("utf-8"), "sha_rec"),
            "ref/thresholds_and_standards.md": (thresh_text.encode("utf-8"), "sha_thresh"),
            "ref/research/negative_control_round4_preregistration.md": (
                r4_prereg_text.encode("utf-8"),
                "sha_r4p",
            ),
        }

        class _FailIfPlottingPlt:
            def figure(self, *_a: Any, **_kw: Any) -> None:
                raise AssertionError("Builder reached plt.figure instead of rejecting mismatch before plotting")

        compiled_ns: dict[str, Any] = {
            "ast": ast,
            "json": json,
            "re": re,
            "statistics": statistics,
            "yaml": yaml,
            "Path": Path,
            "Any": Any,
            "SOURCE_REVISION": SOURCE_REVISION,
            "FIGSIZE_IN": (16.64, 6.80),
            "read_git_blob": lambda rel_path: blob_store[rel_path],
            "_list_research_markdown_inventory": lambda: inv,
            "plt": _FailIfPlottingPlt(),
        }
        exec(compile(mod_ast, str(PACKAGE_DIR / "build_figures.py"), "exec"), compiled_ns)
        verify_fn = compiled_ns["_compute_and_verify_section6_fit_history"]
        build_fig07_fn = compiled_ns["build_fig07_threshold_evidence_history"]

        # Unmodified inputs pass verification
        verified = verify_fn(
            r3_doc=r3_doc,
            r6_doc=r6_doc,
            r9_doc=r9_doc,
            recover_text=recover_text,
            thresh_text=thresh_text,
            r4_prereg_text=r4_prereg_text,
        )
        self.assertEqual(verified["recomputed_r4_map"]["d_phenix"], 0.01220)
        self.assertEqual(verified["recomputed_r7_map"]["d_phenix"], 0.01200)

        # #996 Counterexample: mutate ONLY R3 null 8R5K d_phenix to 0.0 -> R4 becomes 0.01215 while R7 stays 0.01200
        r3_mut = copy.deepcopy(r3_doc)
        for row in r3_mut["rows"]:
            if row.get("pdb_id") == "8R5K" and row.get("subject") == "null":
                row["numbers"]["d_phenix"] = 0.0
        mut_v4_phx = [
            float(r["numbers"]["d_phenix"])
            for r in r3_mut["rows"]
            if r.get("subject") == "null" and r.get("status") == "benched"
        ]
        self.assertEqual(_indep_fit_threshold(mut_v4_phx)["threshold"], 0.01215)
        blob_store["ref/research/data/negative_control_round3_bench.json"] = (
            json.dumps(r3_mut).encode("utf-8"),
            "sha_r3_mut",
        )
        with self.assertRaisesRegex(RuntimeError, r"R4 registration mismatch.*0\.01215"):
            build_fig07_fn(PACKAGE_DIR, {})
        blob_store["ref/research/data/negative_control_round3_bench.json"] = (
            git_blob_bytes("ref/research/data/negative_control_round3_bench.json"),
            "sha_r3",
        )

        # Mutate R4 preregistration C1 table row while leaving **+0.01220** outside C1
        r4_prereg_mut = (
            r4_prereg_text.replace(
                "| phenix path | +0.00350 | 0.00290 | **+0.01220** |",
                "| phenix path | +0.00350 | 0.00290 | **+0.01215** |",
                1,
            )
            + "\n## C2 — extra note\nRetained text **+0.01220** outside C1.\n"
        )
        with self.assertRaisesRegex(RuntimeError, "R4 registration mismatch"):
            verify_fn(
                r3_doc=r3_doc,
                r6_doc=r6_doc,
                r9_doc=r9_doc,
                recover_text=recover_text,
                thresh_text=thresh_text,
                r4_prereg_text=r4_prereg_mut,
            )

        # Mutate §6 ISOT retired R4 triple while leaving "0.01220 / 0.01090 / 0.00540" outside §6
        thresh_mut_r4 = (
            "Outside §6 note: 0.01220 / 0.01090 / 0.00540\n"
            + thresh_text.replace(
                "round-4 values 0.01220 / 0.01090 / 0.00540 were retired",
                "round-4 values 0.01215 / 0.01090 / 0.00540 were retired",
                1,
            )
        )
        with self.assertRaisesRegex(RuntimeError, "R4 registration mismatch"):
            verify_fn(
                r3_doc=r3_doc,
                r6_doc=r6_doc,
                r9_doc=r9_doc,
                recover_text=recover_text,
                thresh_text=thresh_mut_r4,
                r4_prereg_text=r4_prereg_text,
            )

        # Mutate §6 ISOT R7 row while leaving original triple outside §6
        thresh_mut_r7 = (
            "Outside §6 note: d_phenix **0.01200**, d_gemmi **0.01025**, d_refmac **0.00560**\n"
            + thresh_text.replace(
                "d_phenix **0.01200**, d_gemmi **0.01025**, d_refmac **0.00560**",
                "d_phenix **0.01200**, d_gemmi **0.01025**, d_refmac **0.00599**",
                1,
            )
        )
        with self.assertRaisesRegex(RuntimeError, "R7 registration mismatch"):
            verify_fn(
                r3_doc=r3_doc,
                r6_doc=r6_doc,
                r9_doc=r9_doc,
                recover_text=recover_text,
                thresh_text=thresh_mut_r7,
                r4_prereg_text=r4_prereg_text,
            )

        # Mutate §6 ANIS R9 row while leaving "d_refmac **0.01150**" outside §6
        thresh_mut_r9 = (
            "Outside §6 note: d_refmac **0.01150**\n"
            + thresh_text.replace(
                "d_refmac **0.01150** from the round-9 null",
                "d_refmac **0.01199** from the round-9 null",
                1,
            )
        )
        with self.assertRaisesRegex(RuntimeError, "R9 registration mismatch"):
            verify_fn(
                r3_doc=r3_doc,
                r6_doc=r6_doc,
                r9_doc=r9_doc,
                recover_text=recover_text,
                thresh_text=thresh_mut_r9,
                r4_prereg_text=r4_prereg_text,
            )

    def test_fig05_source_population_and_threshold_integrity(self) -> None:
        """Verify fig05 renders all 17/6/11 source observations without pre-box filtering or an inapplicable 0.008 Å line."""
        lib_text = git_blob_bytes(
            "ref/research/tolerance_benchmark_restraint_library.md", SOURCE_REVISION
        ).decode("utf-8")
        cnt_text = git_blob_bytes(
            "ref/research/tolerance_benchmark_bond_rmsd.md", SOURCE_REVISION
        ).decode("utf-8")

        counts_by_id: dict[str, dict[str, Any]] = {}
        cnt_re = re.compile(
            r"^\|\s*([0-9A-Z]{4})\s*\|\s*([0-9.]+)\s*\|\s*(\d+)\s*\|\s*([0-9.]+)\s*\|\s*(\d+)\s*\|\s*([+−-]?[0-9.]+)\s*\|\s*(\*\*yes\*\*|no)\s*\|$"
        )
        for line in cnt_text.splitlines():
            m = cnt_re.match(line.strip())
            if m:
                counts_by_id[m.group(1)] = {
                    "n_bonds_phenix": int(m.group(3)),
                    "n_bonds_gemmi": int(m.group(5)),
                    "same_bond_count": m.group(7) == "**yes**",
                }
        self.assertEqual(len(counts_by_id), 17)

        rows: list[dict[str, Any]] = []
        lib_re = re.compile(
            r"^\|\s*([0-9A-Z]{4})\s*\|\s*([0-9.]+)\s*\|\s*([0-9.]+)\s*\|\s*([0-9.]+)\s*\|\s*([+−-][0-9.]+)\s*\|\s*([+−-][0-9.]+)\s*\|$"
        )
        for line in lib_text.splitlines():
            m = lib_re.match(line.strip())
            if m:
                pid = m.group(1)
                cinfo = counts_by_id[pid]
                rows.append(
                    {
                        "pdb_id": pid,
                        "a_phenix_cdl": float(m.group(2)),
                        "b_phenix_eh": float(m.group(3)),
                        "c_gemmi_ccp4": float(m.group(4)),
                        "b_minus_a": float(m.group(5).replace("−", "-")),
                        "c_minus_b": float(m.group(6).replace("−", "-")),
                        "n_bonds_phenix": cinfo["n_bonds_phenix"],
                        "n_bonds_gemmi": cinfo["n_bonds_gemmi"],
                        "same_bond_count": cinfo["same_bond_count"],
                    }
                )
        self.assertEqual(len(rows), 17)

        expected_a = [r["a_phenix_cdl"] for r in rows]
        expected_b = [r["b_phenix_eh"] for r in rows]
        expected_c = [r["c_gemmi_ccp4"] for r in rows]
        expected_ba_eq = [abs(r["b_minus_a"]) for r in rows if r["same_bond_count"]]
        expected_cb_eq = [abs(r["c_minus_b"]) for r in rows if r["same_bond_count"]]
        expected_ba_neq = [abs(r["b_minus_a"]) for r in rows if not r["same_bond_count"]]
        expected_cb_neq = [abs(r["c_minus_b"]) for r in rows if not r["same_bond_count"]]

        self.assertEqual(len(expected_c), 17)
        self.assertAlmostEqual(max(expected_c), 0.08100, places=6)
        self.assertEqual(len(expected_cb_neq), 11)
        self.assertAlmostEqual(statistics.median(expected_cb_neq), 0.00495, places=6)
        self.assertAlmostEqual(max(expected_cb_neq), 0.06673, places=6)

        class _StubAx:
            def __init__(self) -> None:
                self.plots: list[tuple[list[float], list[float]]] = []
                self.boxes: list[tuple[float, list[float]]] = []
                self.scatters: list[tuple[list[float], list[float]]] = []
                self.hlines: list[float] = []
                self.ylim: tuple[float, float] = (0.0, 1.0)
                self.xticks: list[float] = []
                self.xticklabels: list[str] = []

            def plot(self, xs: Any, ys: Any, **_kw: Any) -> None:
                self.plots.append(([float(x) for x in xs], [float(y) for y in ys]))

            def scatter(self, xs: Any, ys: Any, **_kw: Any) -> None:
                self.scatters.append(([float(x) for x in xs], [float(y) for y in ys]))

            def axhline(self, y: float, **_kw: Any) -> None:
                self.hlines.append(float(y))

            def annotate(self, *_a: Any, **_kw: Any) -> None:
                pass

            def text(self, *_a: Any, **_kw: Any) -> None:
                pass

            def set_xticks(self, xs: Any) -> None:
                self.xticks = [float(x) for x in xs]

            def set_xticklabels(self, labels: Any) -> None:
                self.xticklabels = [str(lbl) for lbl in labels]

            def set_yticks(self, *_a: Any) -> None:
                pass

            def set_ylabel(self, *_a: Any) -> None:
                pass

            def set_ylim(self, ymin: float, ymax: float) -> None:
                self.ylim = (float(ymin), float(ymax))

            def set_xlim(self, *_a: Any) -> None:
                pass

            def set_title(self, *_a: Any) -> None:
                pass

        class _StubFig:
            def subplots_adjust(self, **_kw: Any) -> None:
                pass

            def suptitle(self, *_a: Any, **_kw: Any) -> None:
                pass

        class _StubPlt:
            def __init__(self) -> None:
                self.ax_left = _StubAx()
                self.ax_right = _StubAx()
                self.fig = _StubFig()

            def subplots(self, *_a: Any, **_kw: Any) -> tuple[_StubFig, tuple[_StubAx, _StubAx]]:
                return self.fig, (self.ax_left, self.ax_right)

        def _summary_stats_std(values: list[float]) -> dict[str, Any]:
            s_vals = sorted(float(v) for v in values)
            return {
                "n": len(s_vals),
                "min": round(min(s_vals), 6),
                "median": round(statistics.median(s_vals), 6),
                "max": round(max(s_vals), 6),
            }

        def _draw_box_stub(
            ax: _StubAx, pos: float, values: list[float], *_a: Any, **_kw: Any
        ) -> dict[str, Any]:
            vals = [float(v) for v in values]
            ax.boxes.append((float(pos), vals))
            return _summary_stats_std(vals)

        def audit_fig05_function(fn_obj: Any) -> None:
            stub_plt = _StubPlt()
            ns = {
                "parse_bond_rmsd_tables": lambda: (rows, "sha_lib", "sha_cnt"),
                "plt": stub_plt,
                "FIGSIZE_IN": (16.64, 6.80),
                "style_axes": lambda _ax: None,
                "COLOR_COHORT": "#1a1a2e",
                "MUTED_COLOR": "#5a6071",
                "COLOR_PHENIX": "#0072B2",
                "COLOR_PHENIX_LIGHT": "#7fbce0",
                "COLOR_GEMMI": "#E69F00",
                "COLOR_ALERT": "#b23a22",
                "ACCENT_COLOR": "#1f4e8c",
                "SOURCE_REVISION": SOURCE_REVISION,
                "draw_box_and_strip": _draw_box_stub,
                "summary_stats": _summary_stats_std,
                "save_deterministic_png": lambda _f, _p: ("sha_png", [3328, 1360]),
            }
            bound_fn = type(fn_obj)(
                fn_obj.__code__, ns, fn_obj.__name__, fn_obj.__defaults__, fn_obj.__closure__
            )
            meta = bound_fn(PACKAGE_DIR, {})

            ax_l, ax_r = stub_plt.ax_left, stub_plt.ax_right
            self.assertEqual(len(ax_l.boxes), 3, "Panel A must plot exactly 3 box distributions")
            self.assertEqual(ax_l.boxes[0][1], expected_a)
            self.assertEqual(ax_l.boxes[1][1], expected_b)
            self.assertEqual(
                ax_l.boxes[2][1],
                expected_c,
                f"Panel A group C filtered observations: got n={len(ax_l.boxes[2][1])}, max={max(ax_l.boxes[2][1])}",
            )
            self.assertEqual(
                len(ax_l.scatters),
                0,
                "Panel A must not add synthetic out-of-frame scatter proxy markers",
            )
            plotted_c_lines = [ys[2] for _xs, ys in ax_l.plots if len(ys) == 3]
            self.assertEqual(
                plotted_c_lines,
                expected_c,
                "Panel A paired lines must use unclipped C values including 30TW 0.08100 Å",
            )
            for _pos, bvals in ax_l.boxes:
                self.assertLessEqual(ax_l.ylim[0], min(bvals))
                self.assertGreaterEqual(ax_l.ylim[1], max(bvals))

            self.assertEqual(len(ax_r.boxes), 4, "Panel B must plot exactly 4 box distributions")
            self.assertEqual(ax_r.boxes[0][1], expected_ba_eq)
            self.assertEqual(ax_r.boxes[1][1], expected_cb_eq)
            self.assertEqual(ax_r.boxes[2][1], expected_ba_neq)
            self.assertEqual(
                ax_r.boxes[3][1],
                expected_cb_neq,
                (
                    f"Panel B |C-B| diff filtered observations: got n={len(ax_r.boxes[3][1])}, "
                    f"median={statistics.median(ax_r.boxes[3][1]):.6f} vs expected 0.004950"
                ),
            )
            self.assertEqual(
                len(ax_r.scatters),
                0,
                "Panel B must not add synthetic out-of-frame scatter proxy markers",
            )
            for _pos, bvals in ax_r.boxes:
                self.assertLessEqual(ax_r.ylim[0], min(bvals))
                self.assertGreaterEqual(ax_r.ylim[1], max(bvals))

            for ax in (ax_l, ax_r):
                self.assertEqual(len(ax.xticklabels), len(ax.boxes))
                for lbl, (_pos, bvals) in zip(ax.xticklabels, ax.boxes, strict=True):
                    self.assertIn(f"(n={len(bvals)})", lbl)
                    self.assertIn(f"{statistics.median(bvals):.5f}", lbl)
                for h_y in ax.hlines:
                    self.assertNotAlmostEqual(
                        h_y, 0.008, places=6, msg="Inapplicable 0.008 Å threshold line must not be drawn"
                    )
                for _xs, ys in ax.plots:
                    if len(ys) == 2 and ys[0] == ys[1]:
                        self.assertNotAlmostEqual(
                            ys[0], 0.008, places=6, msg="Inapplicable 0.008 Å segment must not be drawn"
                        )
            self.assertEqual(meta["thresholds_used"], [])

        # Extract build_fig05_bond_rmsd_abc AST node from build_figures.py and compile it without importing matplotlib
        bf_source = (PACKAGE_DIR / "build_figures.py").read_text(encoding="utf-8")
        bf_tree = ast.parse(bf_source, filename=str(PACKAGE_DIR / "build_figures.py"))
        fig05_node = next(
            node
            for node in bf_tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "build_fig05_bond_rmsd_abc"
        )
        mod_ast = ast.Module(body=[fig05_node], type_ignores=[])
        ast.fix_missing_locations(mod_ast)
        compiled_env: dict[str, Any] = {}
        exec(compile(mod_ast, str(PACKAGE_DIR / "build_figures.py"), "exec"), compiled_env)
        audit_fig05_function(compiled_env["build_fig05_bond_rmsd_abc"])

        # Compile a source fixture of the historical 17->16 / 11->10 filtered draft (and 0.008 Å line)
        # into a controlled namespace (#991) and prove audit_fig05_function rejects it on the population assertion.
        historical_fixture_src = """
def historical_filtered_fig05(out_dir, source_hashes):
    r_rows, lib_sha, cnt_sha = parse_bond_rmsd_tables()
    a_all = [r["a_phenix_cdl"] for r in r_rows]
    b_all = [r["b_phenix_eh"] for r in r_rows]
    c_all = [r["c_gemmi_ccp4"] for r in r_rows]
    matched = [r for r in r_rows if r["same_bond_count"]]
    mismatched = [r for r in r_rows if not r["same_bond_count"]]
    fig, (ax_left, ax_right) = plt.subplots(1, 2)
    for r in r_rows:
        ax_left.plot([1.0, 2.0, 3.0], [r["a_phenix_cdl"], r["b_phenix_eh"], min(r["c_gemmi_ccp4"], 0.0268)])
    s_a = draw_box_and_strip(ax_left, 1.0, a_all, "#0072B2", "o")
    s_b = draw_box_and_strip(ax_left, 2.0, b_all, "#0072B2", "s")
    s_c = summary_stats(c_all)
    draw_box_and_strip(ax_left, 3.0, [v for v in c_all if v <= 0.026], "#E69F00", "D")
    ax_left.scatter([3.0], [0.0268])
    ax_left.set_xticklabels([f"(n=17)\\n{s_a['median']:.5f}", f"(n=17)\\n{s_b['median']:.5f}", f"(n=17)\\n{s_c['median']:.5f}"])
    ax_left.set_ylim(0.0, 0.0285)
    ba_eq = [abs(r["b_minus_a"]) for r in matched]
    cb_eq = [abs(r["c_minus_b"]) for r in matched]
    ba_neq = [abs(r["b_minus_a"]) for r in mismatched]
    cb_neq_raw = [abs(r["c_minus_b"]) for r in mismatched]
    s_ba_eq = draw_box_and_strip(ax_right, 1.0, ba_eq, "#0072B2", "o")
    s_cb_eq = draw_box_and_strip(ax_right, 2.0, cb_eq, "#E69F00", "D")
    s_ba_neq = draw_box_and_strip(ax_right, 3.0, ba_neq, "#0072B2", "s")
    draw_box_and_strip(ax_right, 4.0, [v for v in cb_neq_raw if v <= 0.016], "#E69F00", "D")
    s_cb_neq = summary_stats(cb_neq_raw)
    ax_right.scatter([4.0], [0.0162])
    ax_right.axhline(0.008)
    ax_right.set_xticklabels([
        f"(n=6)\\n{s_ba_eq['median']:.5f}",
        f"(n=6)\\n{s_cb_eq['median']:.5f}",
        f"(n=11)\\n{s_ba_neq['median']:.5f}",
        f"(n=11)\\n{s_cb_neq['median']:.5f}",
    ])
    ax_right.set_ylim(0.0, 0.0172)
    save_deterministic_png(fig, out_dir)
    return {"thresholds_used": [{"value": 0.008}]}
"""
        hist_env: dict[str, Any] = {}
        exec(compile(historical_fixture_src, "<historical_filtered_fig05>", "exec"), hist_env)
        with self.assertRaisesRegex(AssertionError, "Panel A group C filtered observations"):
            audit_fig05_function(hist_env["historical_filtered_fig05"])

    def test_diagnostics_destination_safety_when_slides_extra_installed(self) -> None:
        if (
            importlib.util.find_spec("matplotlib") is None
            or importlib.util.find_spec("PIL") is None
        ):
            self.skipTest("Optional 'slides' extra (matplotlib/pillow) not installed in current env")

        spec = importlib.util.spec_from_file_location(
            "slides_2026_11_06_build_figures", PACKAGE_DIR / "build_figures.py"
        )
        self.assertIsNotNone(spec)
        assert spec is not None and spec.loader is not None
        bf_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bf_mod)

        with tempfile.TemporaryDirectory(prefix="test_slides_diag_safety_") as tmp:
            root = Path(tmp)
            target_dir = root / "surrogate_target_deck"
            (target_dir / "figures").mkdir(parents=True)
            target_manifest = target_dir / "figures.json"
            target_png = target_dir / "figures" / "fig01_cohort_resolution.png"
            orig_manifest_bytes = b'{"surrogate": "committed_target_manifest"}\n'
            orig_png_bytes = b"COMMITTED_TARGET_PNG_BYTES"
            target_manifest.write_bytes(orig_manifest_bytes)
            target_png.write_bytes(orig_png_bytes)

            fresh_dir = root / "surrogate_fresh_render"
            (fresh_dir / "figures").mkdir(parents=True)
            fresh_manifest = fresh_dir / "figures.json"
            fresh_png = fresh_dir / "figures" / "fig01_cohort_resolution.png"
            fresh_manifest_bytes = b'{"surrogate": "fresh_regenerated_manifest"}\n'
            fresh_png_bytes = b"FRESH_REGENERATED_PNG_BYTES"
            fresh_manifest.write_bytes(fresh_manifest_bytes)
            fresh_png.write_bytes(fresh_png_bytes)

            sample_report: dict[str, Any] = {
                "status": "FAILED",
                "source_revision": SOURCE_REVISION,
                "failures": ["simulated mismatch"],
            }

            # 1. Existing external diagnostic root with child symlinks into target deck (#1001)
            existing_diag = root / "existing_external_diag"
            existing_diag.mkdir()
            (existing_diag / "figures.json").symlink_to(target_manifest)
            (existing_diag / "figures").symlink_to(target_dir / "figures")
            existing_note = existing_diag / "existing_note.txt"
            existing_note.write_bytes(b"KEEP_EXISTING_DIAG_CONTENT")

            with self.assertRaisesRegex(SystemExit, "existing destination"):
                bf_mod._persist_diagnostics(
                    existing_diag, target_dir, sample_report, fresh_dir
                )
            self.assertEqual(target_manifest.read_bytes(), orig_manifest_bytes)
            self.assertEqual(target_png.read_bytes(), orig_png_bytes)
            self.assertTrue((existing_diag / "figures.json").is_symlink())
            self.assertTrue((existing_diag / "figures").is_symlink())
            self.assertEqual(existing_note.read_bytes(), b"KEEP_EXISTING_DIAG_CONTENT")
            self.assertFalse((existing_diag / "diagnostics.json").exists())

            with self.assertRaisesRegex(SystemExit, "existing destination"):
                bf_mod.check_deterministic(target_dir, diagnostics_dir=existing_diag)
            self.assertEqual(target_manifest.read_bytes(), orig_manifest_bytes)
            self.assertEqual(target_png.read_bytes(), orig_png_bytes)

            # 2. Existing symlink or dangling symlink as destination itself
            other_dir = root / "other_external_dir"
            other_dir.mkdir()
            symlink_diag = root / "symlink_diag"
            symlink_diag.symlink_to(other_dir)
            with self.assertRaisesRegex(SystemExit, "existing destination"):
                bf_mod._persist_diagnostics(
                    symlink_diag, target_dir, sample_report, fresh_dir
                )
            with self.assertRaisesRegex(SystemExit, "existing destination"):
                bf_mod.check_deterministic(target_dir, diagnostics_dir=symlink_diag)
            self.assertEqual(list(other_dir.iterdir()), [])

            dangling_diag = root / "dangling_diag"
            dangling_target = root / "nonexistent_dangling_target"
            dangling_diag.symlink_to(dangling_target)
            with self.assertRaisesRegex(SystemExit, "existing destination"):
                bf_mod._persist_diagnostics(
                    dangling_diag, target_dir, sample_report, fresh_dir
                )
            with self.assertRaisesRegex(SystemExit, "existing destination"):
                bf_mod.check_deterministic(target_dir, diagnostics_dir=dangling_diag)
            self.assertFalse(dangling_target.exists())
            self.assertTrue(dangling_diag.is_symlink())

            # 3. Destination inside target deck (directly or as deck root)
            inside_diag = target_dir / "nested_diag"
            with self.assertRaisesRegex(SystemExit, "inside target deck directory"):
                bf_mod._persist_diagnostics(
                    inside_diag, target_dir, sample_report, fresh_dir
                )
            with self.assertRaisesRegex(SystemExit, "inside target deck directory"):
                bf_mod.check_deterministic(target_dir, diagnostics_dir=inside_diag)
            self.assertFalse(inside_diag.exists())

            with self.assertRaisesRegex(SystemExit, "inside target deck directory"):
                bf_mod._persist_diagnostics(
                    target_dir, target_dir, sample_report, fresh_dir
                )
            self.assertEqual(target_manifest.read_bytes(), orig_manifest_bytes)
            self.assertEqual(target_png.read_bytes(), orig_png_bytes)

            # 4. Brand-new external diagnostic destination persists fresh manifest, PNG, and report
            new_diag = root / "brand_new_diag"
            self.assertFalse(new_diag.exists())
            bf_mod._persist_diagnostics(
                new_diag, target_dir, sample_report, fresh_dir
            )
            self.assertTrue(new_diag.is_dir())
            self.assertEqual(
                (new_diag / "figures.json").read_bytes(), fresh_manifest_bytes
            )
            self.assertEqual(
                (new_diag / "figures" / "fig01_cohort_resolution.png").read_bytes(),
                fresh_png_bytes,
            )
            self.assertEqual(
                json.loads((new_diag / "diagnostics.json").read_text(encoding="utf-8")),
                sample_report,
            )
            self.assertEqual(target_manifest.read_bytes(), orig_manifest_bytes)
            self.assertEqual(target_png.read_bytes(), orig_png_bytes)

    def test_canonical_rgb8_png_encoder_when_slides_extra_installed(self) -> None:
        # 1. AST verification that all 9 ax.annotate calls in build_figures.py set "antialiased": False in arrowprops (#999).
        bf_source = (PACKAGE_DIR / "build_figures.py").read_text(encoding="utf-8")
        bf_tree = ast.parse(bf_source, filename=str(PACKAGE_DIR / "build_figures.py"))
        annotate_calls = [
            node
            for node in ast.walk(bf_tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "annotate"
        ]
        self.assertEqual(
            len(annotate_calls),
            9,
            f"Expected 9 ax.annotate calls in build_figures.py, found {len(annotate_calls)}",
        )
        for call in annotate_calls:
            arrowprops_kw = next(
                (kw for kw in call.keywords if kw.arg == "arrowprops"), None
            )
            self.assertIsNotNone(
                arrowprops_kw,
                f"ax.annotate at line {call.lineno} missing arrowprops keyword",
            )
            assert arrowprops_kw is not None
            self.assertIsInstance(
                arrowprops_kw.value,
                ast.Dict,
                f"ax.annotate arrowprops at line {call.lineno} must be a dict literal",
            )
            assert isinstance(arrowprops_kw.value, ast.Dict)
            antialiased_vals = [
                v
                for k, v in zip(
                    arrowprops_kw.value.keys, arrowprops_kw.value.values, strict=True
                )
                if isinstance(k, ast.Constant) and k.value == "antialiased"
            ]
            self.assertEqual(
                len(antialiased_vals),
                1,
                f"ax.annotate arrowprops at line {call.lineno} must define 'antialiased' exactly once",
            )
            aa_node = antialiased_vals[0]
            self.assertIsInstance(
                aa_node,
                ast.Constant,
                f"ax.annotate arrowprops['antialiased'] at line {call.lineno} must be a literal Constant",
            )
            assert isinstance(aa_node, ast.Constant)
            self.assertIs(
                aa_node.value,
                False,
                f"ax.annotate arrowprops at line {call.lineno} must set 'antialiased': False",
            )

        if (
            importlib.util.find_spec("matplotlib") is None
            or importlib.util.find_spec("PIL") is None
        ):
            self.skipTest("Optional 'slides' extra (matplotlib/pillow) not installed in current env")

        from PIL import Image

        spec = importlib.util.spec_from_file_location(
            "slides_2026_11_06_build_figures_png", PACKAGE_DIR / "build_figures.py"
        )
        self.assertIsNotNone(spec)
        assert spec is not None and spec.loader is not None
        bf_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bf_mod)

        def ref_sub_filter(rgb: bytes, w: int, h: int) -> bytes:
            row_stride = w * 3
            self.assertEqual(len(rgb), h * row_stride)
            out = bytearray()
            for r in range(h):
                row = rgb[r * row_stride : (r + 1) * row_stride]
                out.append(1)
                for i in range(row_stride):
                    prev = row[i - 3] if i >= 3 else 0
                    out.append((row[i] - prev) & 0xFF)
            return bytes(out)

        def parse_png_chunks(png_raw: bytes) -> list[tuple[bytes, bytes, int]]:
            self.assertEqual(png_raw[:8], b"\x89PNG\r\n\x1a\n")
            pos = 8
            chunks: list[tuple[bytes, bytes, int]] = []
            while pos < len(png_raw):
                self.assertLessEqual(pos + 12, len(png_raw))
                (length,) = struct.unpack(">I", png_raw[pos : pos + 4])
                ctype = png_raw[pos + 4 : pos + 8]
                cdata = png_raw[pos + 8 : pos + 8 + length]
                self.assertEqual(len(cdata), length)
                (crc_stored,) = struct.unpack(
                    ">I", png_raw[pos + 8 + length : pos + 12 + length]
                )
                crc_calc = zlib.crc32(ctype + cdata) & 0xFFFFFFFF
                self.assertEqual(
                    crc_stored,
                    crc_calc,
                    f"CRC-32 mismatch in chunk {ctype!r}",
                )
                chunks.append((ctype, cdata, crc_stored))
                pos += 12 + length
            return chunks

        def verify_png_roundtrip(rgb: bytes, w: int, h: int) -> bytes:
            png_bytes = bf_mod._encode_canonical_rgb8_png(rgb, w, h)
            chunks = parse_png_chunks(png_bytes)
            self.assertEqual([c[0] for c in chunks], [b"IHDR", b"IDAT", b"IEND"])
            ihdr_data = chunks[0][1]
            idat_data = chunks[1][1]
            iend_data = chunks[2][1]
            self.assertEqual(
                ihdr_data, struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
            )
            self.assertEqual(iend_data, b"")
            self.assertEqual(idat_data[:2], b"\x78\x01")
            decompressed_zlib = zlib.decompress(idat_data)
            decompressed_raw = zlib.decompress(idat_data[2:-4], -15)
            self.assertEqual(decompressed_zlib, decompressed_raw)
            (adler_stored,) = struct.unpack(">I", idat_data[-4:])
            self.assertEqual(
                adler_stored, zlib.adler32(decompressed_zlib) & 0xFFFFFFFF
            )
            expected_filtered = ref_sub_filter(rgb, w, h)
            self.assertEqual(bf_mod._png_sub_filter_rgb8(rgb, w, h), expected_filtered)
            self.assertEqual(decompressed_zlib, expected_filtered)
            with Image.open(io.BytesIO(png_bytes)) as im:
                self.assertEqual(im.format, "PNG")
                self.assertEqual(im.mode, "RGB")
                self.assertEqual(im.size, (w, h))
                self.assertEqual(im.tobytes(), rgb)
            return png_bytes

        # 2. Empty stream and all 256 literal byte values (0..255) on raw DEFLATE + zlib helpers
        empty_deflate = bf_mod._deflate_fixed_rle_dist1(b"")
        self.assertEqual(zlib.decompress(empty_deflate, -15), b"")
        empty_zlib = bf_mod._zlib_wrap_fixed_rle_dist1(b"")
        self.assertEqual(empty_zlib[:2], b"\x78\x01")
        self.assertEqual(zlib.decompress(empty_zlib), b"")
        self.assertEqual(
            struct.unpack(">I", empty_zlib[-4:])[0], zlib.adler32(b"") & 0xFFFFFFFF
        )

        all_literals_stream = bytes(range(256)) + bytes(reversed(range(256)))
        all_literals_zlib = bf_mod._zlib_wrap_fixed_rle_dist1(all_literals_stream)
        self.assertEqual(zlib.decompress(all_literals_zlib), all_literals_stream)

        # 3. Exhaustive equal-byte run lengths: 1..265 (covers 1, 2, 3, 4 and every match length 3..258
        # including boundary lengths 257, 258, 259) plus repeated max matches (516..520, 775..778)
        # across zero and non-zero byte values (<144 8-bit and >=144 9-bit fixed Huffman literals).
        run_lengths_to_test = [
            *range(1, 266),
            516,
            517,
            518,
            519,
            520,
            775,
            776,
            777,
            778,
        ]
        segments: list[bytes] = []
        prev_byte = -1
        for idx, rlen in enumerate(run_lengths_to_test):
            bval = (idx * 73 + 19) & 0xFF
            if bval == prev_byte:
                bval = (bval + 1) & 0xFF
            segments.append(bytes([bval]) * rlen)
            prev_byte = bval
        for special_bval in (0x00, 0x01, 0x8F, 0x90, 0xFE, 0xFF):
            for boundary_len in (1, 2, 3, 4, 257, 258, 259, 517, 518, 775):
                sep = 0x55 if special_bval != 0x55 else 0xAA
                segments.append(bytes([sep]))
                segments.append(bytes([special_bval]) * boundary_len)
        rle_payload = b"".join(segments)
        rle_zlib = bf_mod._zlib_wrap_fixed_rle_dist1(rle_payload)
        self.assertEqual(zlib.decompress(rle_zlib), rle_payload)
        self.assertEqual(
            zlib.decompress(rle_zlib[2:-4], -15),
            rle_payload,
        )

        # 4. Full PNG round-trips via Pillow and independent chunk/Sub-filter verification:
        # 4a. 256x2 image where Sub-filtered deltas exercise all 256 byte values (0..255) and mod-256 wrap-around.
        row0 = bytearray()
        row1 = bytearray()
        acc_r, acc_g, acc_b = 0, 0, 0
        for k in range(256):
            acc_r = (acc_r + k) & 0xFF
            acc_g = (acc_g + (255 - k)) & 0xFF
            acc_b = (acc_b + ((k * 37 + 11) & 0xFF)) & 0xFF
            row0.extend((acc_r, acc_g, acc_b))
            row1.extend(((255 - acc_r) & 0xFF, (acc_g ^ 0xA5) & 0xFF, (acc_b + 129) & 0xFF))
        rgb_all_256 = bytes(row0 + row1)
        filtered_256 = bf_mod._png_sub_filter_rgb8(rgb_all_256, 256, 2)
        self.assertEqual(set(filtered_256), set(range(256)))
        verify_png_roundtrip(rgb_all_256, 256, 2)

        # 4b. Multi-row image whose Sub-filtered scanlines contain long runs (up to 795 bytes > 3*258)
        # of zero (constant color) and non-zero (<144 and >=144) repeated Sub-filter bytes.
        w_long, h_long = 265, 4
        long_rows = bytearray()
        for step_c in (0, 23, 144, 211):
            for k in range(w_long):
                v = ((k + 1) * step_c) & 0xFF
                long_rows.extend((v, v, v))
        valid_png = verify_png_roundtrip(bytes(long_rows), w_long, h_long)

        # 5. Dimension/length validation and corrupted-output rejection
        with self.assertRaises(ValueError):
            bf_mod._encode_canonical_rgb8_png(b"\x00\x00", 1, 1)
        with self.assertRaises(ValueError):
            bf_mod._encode_canonical_rgb8_png(b"", 0, 1)

        # Corrupt the zlib header byte inside the IDAT payload (offset 41) and verify both CRC check and decoder reject it.
        corrupted_idat = bytearray(valid_png)
        corrupted_idat[41] ^= 0xFF
        with self.assertRaises(AssertionError):
            parse_png_chunks(bytes(corrupted_idat))
        with self.assertRaises(Exception):
            with Image.open(io.BytesIO(bytes(corrupted_idat))) as bad_im:
                bad_im.load()

    def test_build_figures_check_mode_when_slides_extra_installed(self) -> None:
        if (
            importlib.util.find_spec("matplotlib") is None
            or importlib.util.find_spec("PIL") is None
        ):
            self.skipTest("Optional 'slides' extra (matplotlib/pillow) not installed in current env")
        cmd = [sys.executable, str(PACKAGE_DIR / "build_figures.py"), "--check"]
        diag_dir = os.environ.get("SLIDES_DIAGNOSTICS_DIR", "").strip()
        if diag_dir:
            cmd.extend(["--diagnostics-dir", diag_dir])
        proc = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            proc.returncode,
            0,
            f"build_figures.py --check failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
