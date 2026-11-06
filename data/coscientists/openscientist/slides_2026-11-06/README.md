# `slides_2026-11-06` — Slide Content Package for XMechBay / Claude Slides

Content-only slide narrative and figure package for the `protstruct_review` technical review presentation, derived from committed scientific records pinned to `main` commit `f3cfad326f28ddbf652dcdb0c5858443bee6e413`.

## Package Paths & Inventory

All package files in `data/coscientists/openscientist/slides_2026-11-06/`:

| Path | Purpose |
| :--- | :--- |
| `outline.md` | 5-section outline with one-sentence section summaries and 39 slides (`S01`–`S09`, triplet `S09a`/`S09f`/`S09b`, `S10`–`S12`, triplets `S13a`/`S13`/`S13b`–`S18a`/`S18`/`S18b`, `S19`–`S24`), each carrying `title_general` and `subtitle_technical` |
| `slides.md` | Full 39-slide specification: slide ID, section, `title_general`, `subtitle_technical`, one-line message, `Terms` panel where present (`S05`, `S09a`, `S13a`–`S18a`), concise slide body, figure path/caption, pinned `Sources` (`file:line` and JSON pointers at `f3cfad326f28ddbf652dcdb0c5858443bee6e413`), separate `Package artifacts`, and speaker notes (`<= 1,500` characters) |
| `questions.md` | User-input specifications for open framing questions `Q1`, `Q2`, and `Q4` (matching `[USER INPUT: Q<N> ...]` placeholders on `S02` and `S24`) plus the recorded `2026-11-06` `Q3` decision on `S06` and `S24` |
| `README.md` | Package guide, source pin, historical three-deck source context, figure build/check commands, design specifications, XMechBay two-column handoff instructions, and scope limitations |
| `build_figures.py` | Deterministic single-command figure builder and `--check` verifier reading committed blobs at `f3cfad326f28ddbf652dcdb0c5858443bee6e413` via `git show` |
| `figures.json` | Machine-readable manifest recording per-figure SHA-256 digests, pixel dimensions (`[3328, 1360]`), units, selection criteria, sample sizes, PDB IDs, source blob hashes, thresholds, and derived summary statistics across the 6 protein-distribution figures (`fig01`–`fig06`) and 1 threshold-ledger/registration-history figure (`fig07`) |
| `figures/fig01_cohort_resolution.png` | Figure 1 (`Slide S13`, triplet `S13a`/`S13`/`S13b`): Enrolled extreme-resolution control cohort (`n = 22`, `0.79–1.00 Å`, `median 0.895 Å`) actual `d_min` (`15 ≤ 0.90 Å`, `7 > 0.90 Å`) vs stored `stratum` (`20 true`, `2 false`) |
| `figures/fig02_r9_null_delta_rfree.png` | Figure 2 (`Slide S14`, triplet `S14a`/`S14`/`S14b`): Regenerated Round-9 null `ΔR-free` (`post − deposited baseline`) across `PHENIX` (`n = 22`, `median +0.00330`), `Gemmi` (`n = 22`, `median +0.00365`), and `REFMAC5 BREF ANIS` (`n = 21`, `median +0.00370`, `9YGW` absent) |
| `figures/fig03_r9_isot_vs_anis_paired.png` | Figure 3 (`Slide S15`, triplet `S15a`/`S15`/`S15b`): Paired `n = 21` `REFMAC5 BREF ISOT` (`median +0.00180`, `17/21` sign agreement) vs `BREF ANIS` (`median +0.00370`, `20/21` sign agreement; `9YGW` absent), highlighting `2VXN` (`-0.0122 → +0.0130`) |
| `figures/fig04_r10_recovery_delta_rfree.png` | Figure 4 (`Slide S16`, triplet `S16a`/`S16`/`S16b`): Round-10 `osol_h` recovery `ΔR-free` relative to deposited baselines (`n = 22` / `n = 21`; medians `+0.00630`, `+0.00800`, `+0.00730`), highlighting `2VXN` (`+0.0221 / +0.0211` vs `REFMAC -0.0095`) |
| `figures/fig05_bond_rmsd_abc.png` | Figure 5 (`Slide S17`, triplet `S17a`/`S17`/`S17b`): Reconstructed 17-model bond-length RMSD (`Å`, not `RMSZ`) across `A: PHENIX CDL` (`0.00872 Å`), `B: PHENIX E&H` (`0.00914 Å`), and `C: Gemmi 0.7.4` (`0.01100 Å`), split by equal (`n = 6`) vs different (`n = 11`) bond counts |
| `figures/fig06_round46_rotamer_outlier_pct.png` | Figure 6 (`Slide S18`, triplet `S18a`/`S18`/`S18b`): Separate 41-protein Round-46 cohort (`12CI` excluded for zero shared rotamer and Ramachandran keys) raw reported rotamer outlier `%` (`14ZZ -1.52 pp`, `2YOL +0.57 pp`) vs `1.0000` shared-key binary `OUTLIER` verdict agreement (`38,744 / 38,744`) |
| `figures/fig07_threshold_evidence_history.png` | Figure 7 (`Slide S09f`, triplet `S09a`/`S09f`/`S09b`): Documentary threshold-ledger inventory (`41` components across `21` `§3`/`§4` rows = `17 §3 + 4 §4`, classified orthogonally by `8` evidence states and `7` policy states) paired with registered `§6` `FIT` `ΔR-free` threshold history (`R4` retired `.01220 / .01090 / .00540` on `n = 22/22/19`, `R7` `ISOT` history `.01200 / .01025 / .00560` on `n = 22/22/20`, and `R9` `ANIS` current `.01200 / .01025 / .01150` with `REFMAC n = 21`), distinct from the per-protein distributions in `fig01`–`fig06` |

Companion records in `ref/research/`:
- `ref/research/slides_content_package_review_2026-11-06.md` — Narrative, figure-population, CI-provenance, and source audit documenting the 36 in-scope issue dispositions (`#965`–`#986`, `#988`–`#997`, and `#999`–`#1002`, with `#999` under CI diagnosis) and separate open repository follow-ups (`#964`, `#987`, `#1003`).
- `ref/research/geometry_tool_presence_2026-11-06.json` — Dated metadata-only filesystem presence check on configured default paths (no version probes run) supporting the `Slide S06` (`Q3`) installation-presence note.

## Source Pin & Historical Deck Series Context

- **Pinned scientific source revision**: `f3cfad326f28ddbf652dcdb0c5858443bee6e413` (`main`). All entries listed under `Sources (pinned to f3cfad326f28ddbf652dcdb0c5858443bee6e413)` in `slides.md` refer exclusively to committed repository files existing at that revision; new files introduced by this branch (`questions.md`, `figures.json`, `build_figures.py`, `figures/*.png`, and `ref/research/geometry_tool_presence_2026-11-06.json`) are listed separately under `Package artifacts`.
- **Local clone & CI history requirement (`#988`)**: `build_figures.py` and `scripts/test_slides_2026_11_06.py` read committed blobs at `f3cfad326f28ddbf652dcdb0c5858443bee6e413` via `git show` with no network fetch inside the figure generator or hermetic gate. A local clone must contain commit `f3cfad326f28ddbf652dcdb0c5858443bee6e413` (not a shallow clone missing that object), and `.github/workflows/validate.yml` configures `fetch-depth: 0` on its `actions/checkout` step so the pinned source revision is present before validation.
- **Original three-deck source series (`#977`)**:
  - `data/coscientists/openscientist/slides_2026-05-04/`
  - `data/coscientists/openscientist/slides_2026-05-05/`
  - `data/coscientists/openscientist/slides_2026-09-07/`
  These three committed directories are the original historical slide series and are preserved read-only. This `slides_2026-11-06/` directory is a new derivative content package synthesized from that series together with current repository evidence (`ref/research/refinement_assessment_case_study_2026-10-18.md`, `ref/quality_reporting.md:196-204`, the extreme-resolution control series through Round 11, the 17-model bond-RMSD benchmark, the 41-protein Round-46 classification comparison, and the `#911` `ProSMART` capability correction).

## Figure Generation & Check Commands

Bootstrap the locked Python 3.12 environment (including the `slides` optional extra with `matplotlib==3.11.2` and `pillow==11.3.0`; optional dependency installation is handled by `uv` outside scientific scripts):

```bash
uv sync --locked --extra benchmark --extra slides
```

Regenerate all 7 PNG figures and `figures.json` from committed Git blobs at `f3cfad326f28ddbf652dcdb0c5858443bee6e413`:

```bash
uv run --locked --extra benchmark --extra slides -- python data/coscientists/openscientist/slides_2026-11-06/build_figures.py
```

Verify byte-for-byte SHA-256 determinism without mutating files on disk (pass `--diagnostics-dir <new-external-dir>` — or set `SLIDES_DIAGNOSTICS_DIR=<new-external-dir>` when running `scripts/test_slides_2026_11_06.py` — to write `diagnostics.json` and fresh check artifacts to a new directory outside the deck that must not already exist):

```bash
uv run --locked --extra benchmark --extra slides -- python data/coscientists/openscientist/slides_2026-11-06/build_figures.py --check
```

Run the focused slide-package consistency test (which also runs `build_figures.py --check` when the `slides` extra is installed, as configured in `.github/workflows/validate.yml` after the hermetic gate, `#989`):

```bash
uv run --locked --extra benchmark --extra slides -- python scripts/test_slides_2026_11_06.py
```

## Design Specifications

- **39-slide triplet architecture and dual titles**: 39 slides (`S01`–`S09`, adjacent intro–figure–results triplet `S09a`/`S09f`/`S09b`, `S10`–`S12`, adjacent triplets `S13a`/`S13`/`S13b` through `S18a`/`S18`/`S18b`, and `S19`–`S24`) across 5 sections. Every slide in `outline.md` and `slides.md` carries an identical pair of title fields: `title_general` (a concise declarative sentence in plain general-audience language ending in `.`) and `subtitle_technical` (specialist terms, cohorts, and tool names).
- **Terms blocks and intro, figure, and results triplet roles**:
  - **Slide `S05` (`Terms` + tools table)**: Defines `R-factors`, `map-model FSC`, and `RMSD vs RMSZ` in a compact `Terms` panel rendered before or beside the 6-row tools table.
  - **Intro slides (`S09a`, `S13a`–`S18a`)**: Define every measure, unit, and acronym in a `Terms` block before the figure appears, paired with `**The experiment**:` and `**Reading the figure**:` sections in `Slide body`.
  - **Figure slides (`S09f`, `S13`–`S18`)**: Pair the full-width PNG figure (`figures/fig07_threshold_evidence_history.png` and `figures/fig01_*.png`–`figures/fig06_*.png`) with a single-sentence reading note in `Slide body`. Figure 7 (`S09f`) summarizes documentary `§3`/`§4` ledger components (`41` components across `21` rows) and `§6` `FIT` registration history (`R4`, `R7`, `R9`), whereas Figures 1–6 (`S13`–`S18`) plot empirical per-protein distributions.
  - **Results slides (`S09b`, `S13b`–`S18b`)**: State 3–5 concise bullets summarizing the measured results and their scoped implications.
- **Speaker notes**: Self-contained presenter notes (`<= 1,500` characters per slide) recording exact provenance and scope qualifiers.
- **Figure canvas**: `1664 × 680` px logical (`16.64 × 6.80` in at `100` logical px/in), rendered at `2x` (`200` DPI) to `3328 × 1360` px PNGs using bundled `DejaVu Sans` (`>= 18.0 pt` = `25.0 px` logical at `1x`, exceeding the `>= 24 px` logical minimum), `antialiased=False` on the nine `ax.annotate` `arrowprops` dictionaries (`fig02`–`fig06`), and canonical platform-independent RGB8 PNG encoding (`_encode_canonical_rgb8_png`: PNG `Sub` filter type `1` + RFC 1951 fixed-Huffman distance-1 RLE DEFLATE in a `0x78 0x01` RFC 1950 zlib stream, `#999`).

## Content-Only Handoff to XMechBay / Claude Slides

This directory is a **content-only package** (`outline.md`, `slides.md`, `questions.md`, `figures/*.png`, `figures.json`); XMechBay builds the HTML/Claude Slides presentation from these files, and this PR ships content and PNGs only. When rendering:

1. **Visual slide canvas**: Place `title_general`, `subtitle_technical`, `One-line message`, `Terms` (on every slide that defines a `Terms` block: `S05`, `S09a`, and `S13a`–`S18a`; do not invent `Terms` on slides that lack a block), `Slide body`, and `Figure` (for `S09f` and `S13`–`S18`) on the slide canvas.
2. **Rendering every present `Terms` block (`S05`, `S09a`, `S13a`–`S18a`)**: Render every present `Terms` block on the slide canvas. On `Slide S05`, render `Terms` as a compact terms panel before or beside the tools table; on figure intros (`S09a`, `S13a`–`S18a`), keep the two-column layout with `Terms` in the left column and `**The experiment**` + `**Reading the figure**` in the right column.
3. **Slide `S06` layout (`Q3` decision)**: Render three larger top panels (`A`, `B`, `C`), each with its own `Benchmarked · 17 models` badge, followed by three smaller category panels below, each with its own `not yet benchmarked` badge scoped to this 17-model comparison.
4. **Provenance and notes**: Place `Sources` and `Package artifacts` in a slide footer/provenance drawer and `Speaker notes` in the presenter notes track.
5. **Open placeholders (`Q1`, `Q2`, `Q4`)**: Three bracketed placeholders (`[USER INPUT: Q1]`, `[USER INPUT: Q2]`, `[USER INPUT: Q4]`) appear on `S02` and `S24` and are specified in `questions.md` (`Q3` is marked `DECIDED` as of `2026-11-06`).

## Limitations & Verification Status

- **Retained-evidence boundaries**:
  - `scripts/assess_refinement.py` currently resolves verdicts to `"informational"` because `ref/structural_criteria.yaml` sets `pass_criterion_bindings: []` (`Slide S10`).
  - Figure 7 (`Slides S09a–S09b`) summarizes the committed `ref/threshold_evidence_status.yaml` ledger at `f3cfad326f28ddbf652dcdb0c5858443bee6e413` (`21` rows = `17 §3 + 4 §4`, `41` components, where `23/41` `retained_record` and `29/41` `active_conditional` are orthogonal classifications of the same `41` components and `retained_record` does not establish complete provenance or independent calibration) alongside the registered `§6` `FIT` `ΔR-free` threshold history (`R4` retired `.01220 / .01090 / .00540` on `n = 22/22/19`, `R7` `ISOT` history `.01200 / .01025 / .00560` on `n = 22/22/20`, and `R9` `ANIS` current `.01200 / .01025 / .01150` with `REFMAC n = 21`).
  - `ref/research/data/negative_control_round10_recover.json` retains deltas relative to deposited baselines (`Slides S16a–S16b`); no absolute pre/post `R-work`/`R-free` endpoints are stored in the Round-10 JSON, and Round 10 changed multiple protocol factors simultaneously (`ref/research/negative_control_round10.md:22-49,92-94`).
  - Figure 5 (`Slides S17a–S17b`) is reconstructed from the committed 17-model published table (`ref/research/tolerance_benchmark_restraint_library.md:38-56`) at published precision without a raw rerun; restraint lists are not diffed on the `11/17` unequal-count models (`ref/research/tolerance_benchmark_bond_rmsd.md:104-105`), no single cross-tool agreement threshold applies across the `A−B`, `B−C`, and count-mismatched groups (`#975`), the adopted conditional matched-library policy band (`|Δ| ≤ 0.006 Å`) is retained while distinguishing policy from the unmeasured matched-library cross-engine contrast (`#976`), and separate open follow-ups `#964`, `#987`, and `#1003` remain tracked on existing repository sources.
  - Figure 6 (`Slides S18a–S18b`) plots raw reported rotamer outlier percentages on the 41-protein Round-46 set (`12CI` excluded); both `phenix` and `wwPDB` validation reports share `MolProbity` lineage, and the binary `OUTLIER` agreement (`38,744 / 38,744`) is reconstructed from summarized producer output rather than a fresh XML/log audit (`ref/research/t05_classification_floor_adoption_2026-09-27.md:43-56`).
  - In the `1SAR` archive (`Slides S19–S20`), `data/1sar_final.pdb` is Round 4 (`146` waters) while `data/1sar_round5.pdb` (`1,640` non-H atoms, `145` waters, `REMARK 3` header `0.1555 / 0.2109`, historical `phenix` `0.1555 / 0.2104`) and `data/1sar_round6.pdb` (`1,646` non-H atoms, `151` waters, `REMARK 3` header `0.1539 / 0.2068`, historical `phenix` `0.1539 / 0.2068`) are separate archive intermediates (`#1002`), logged Round 7 (`159` waters, logged `1 SO4 + 1 Ca + 1 Na` after chain-B sulfate removal in `claude_iterations.log:510,752` and `final_report.md:66,70,150`, `#1000`) and historical raw evaluator outputs/denominators are absent (`ref/research/refinement_assessment_case_study_2026-10-18.md:44-51,59-67`), and open follow-up `#1003` tracks the unchanged `scripts/assess_refinement.py:1651` and `ref/research/data/refinement_assessment_1sar_and_controls_2026-10-18.json:828` Round-7 note for future generator/dated-evidence correction in the queued `1SAR` project.
  - In `ref/threshold_evidence_status.yaml`, `T15` exact-denominator recalibration (`lines 360-377`, open issue `#765`) and `T14` flip-grading policy (`lines 567-575`) remain documented calibration items (`Slide S23`).
- **Authoring & verification status**: (1) **Historical scientific inputs pinned to `f3cfad326f28ddbf652dcdb0c5858443bee6e413`**: Scientific claims, benchmark provenance, and plotted distributions across `outline.md`, `slides.md`, and `build_figures.py` (`#974` full `n = 17` and `n = 11` populations, `#975` threshold removal, and `fig07_threshold_evidence_history` with `#994`–`#996` fixes), `#976` explanatory prose in `ref/thresholds_and_standards.md`, `ref/structural_criteria.yaml`, `ref/research/tolerance_benchmark_bond_rmsd.md`, and `ref/research/tolerance_benchmark_restraint_library.md` (`lines 30-32`, `97-99`, and `109-110`) with refreshed SHA-256 fingerprint pins in `ref/threshold_evidence_status.yaml` (`86dcd91b42298c64cb003cfd99e1805252f2c75fd3885cbdc6dd33f47726f8ab` at `lines 210, 237`), and `#1000` / `#1002` `1SAR` Round-5/Round-6 archive-member inventory and Round-7 logged-sulfate attribution corrections in `slides.md` (`Slide S20`) and `ref/research/refinement_assessment_case_study_2026-10-18.md:46-48,51,134-135` were authored by read-only inspection against committed repository blobs at `f3cfad326f28ddbf652dcdb0c5858443bee6e413`. (2) **Current-branch package content and dated M5 metadata**: `questions.md` (including the `Q3` layout decision), `README.md`, `figures.json`, `figures/*.png`, and the metadata-only filesystem-presence record `ref/research/geometry_tool_presence_2026-11-06.json` are current package artifacts created on this branch (`#977`, matching `Slide S24`). (3) **Current PR `#998` CI, safety, and portable-encoding engineering**: `.github/workflows/validate.yml` (`#988` `fetch-depth: 0`, `#989` `--extra slides` check step, and `#999` diagnostic artifact upload), `build_figures.py` (`#999` `--diagnostics-dir` cross-platform determinism diagnostics, `antialiased=False` on all nine `ax.annotate` `arrowprops` dictionaries, and canonical fixed-Huffman RGB8 PNG writer `_encode_canonical_rgb8_png`, plus `#1001` exclusive new-directory diagnostic write guard), and `scripts/test_slides_2026_11_06.py` (`39`-slide / `7`-figure triplet checks, `#991` Ruff-clean `historical_filtered_fig05` fixture, `#997` schema/tolerance fixes, `#999` `SLIDES_DIAGNOSTICS_DIR` forwarding and `test_canonical_rgb8_png_encoder_when_slides_extra_installed`, and `#1001` `test_diagnostics_destination_safety_when_slides_extra_installed`) were authored on this branch in response to PR `#998` CI and review findings. Shell commands (`validate.sh`, `build_figures.py --check`, test suites, and CI workflows) were not run by the authoring worker under the worker execution rules; PRIMARY owns figure regeneration (`figures.json`, `figures/*.png`), focused checks, the hermetic gate, slide-package tests, cross-platform CI (`ubuntu-latest`, `macos-latest`) verification for `#999`, and PR review recording.
