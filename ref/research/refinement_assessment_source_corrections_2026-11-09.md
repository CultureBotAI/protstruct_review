# Source-Derived Narrative Corrections and Retained-Evidence Audit Trail (`2026-11-09`)

- **Date:** `2026-11-09`
- **Scope:** Source-derived narrative and attribution corrections for `#964`, `#1003`, and `#987` across `scripts/assess_refinement.py`, `scripts/test_assess_refinement.py`, `ref/research/refinement_assessment_case_study_2026-10-18.md`, and `ref/research/negative_control_round2.md`.
- **Frozen retained assessment artifact (byte-identical on disk):**
  - **Path:** `ref/research/data/refinement_assessment_1sar_and_controls_2026-10-18.json`
  - **SHA-256:** `db100e926bfcf6331c303087846c4d51117a4411c6afdf58877aada5dbf14245`
- **Provenance boundary:** This document records a source-attribution correction and reinterpretation of historical narrative fields against already-committed archive and benchmark records. No new scientific or oracle execution was run; the claimed `1SAR` Round 7 coordinate file is absent from the retained archive, so its reported inventory cannot be independently verified from retained coordinates; log/report claims are never treated as measured coordinate inventories, no canonical `EVAL-*` or `QDS-*` record is emitted or modified, and no admission gate or threshold policy is relaxed.

---

## 1. Frozen Assessment JSON Corrections (`#1003` and `#964`)

In accordance with repository immutability rules for dated retained records, `ref/research/data/refinement_assessment_1sar_and_controls_2026-10-18.json` (`sha256: db100e926bfcf6331c303087846c4d51117a4411c6afdf58877aada5dbf14245`) is preserved byte-for-byte on disk. Future output from `scripts/assess_refinement.py` (`build_full_assessment_report()`) is identical to that frozen artifact across all numerical metrics, per-target rows, and provenance digests, and differs **only** at the two narrative string pointers documented below.

### 1.1 `#1003` — `1SAR` Round 7 Unarchived Log/Report Attribution

- **Target artifact:** `ref/research/data/refinement_assessment_1sar_and_controls_2026-10-18.json` (`sha256: db100e926bfcf6331c303087846c4d51117a4411c6afdf58877aada5dbf14245`)
- **Affected JSON pointer:** `/case_study_1sar/missing_conflicting_and_inapplicable_evidence/0/description` (line `828`)
- **Record identifier:** `id = "1sar_round7_coordinates_absent_from_archive"` (`category = "missing_final_artifact"`, `severity = "critical_provenance_boundary"`)
- **Pinned source archive and members:**
  - **Archive path:** `data/coscientists/openscientist/cdba2c07-daff-4f60-ae96-12452b3a5fbb_artifacts.zip`
  - **Archive SHA-256:** `9fc5352284b7ffa7763c633a3eb4d3d0db96b8c25a1be9bcea361722d2c53054` (`0` `*round7*` coordinate members present in the archive).
  - **Member `claude_iterations.log` SHA-256:** `9ba0fddf49e97f0725de084167a640563473b750d7a7fff78782af207c9fcd1c`
    - **Line `510`:**
      `- **Round 7 with NCS restraints achieves R-free=0.199 with zero Ramachandran outliers**: Round 7 (NCS torsion restraints, NQH flip of Gln A38, NCS rotamer consistency): R-work=0.1488, R-free=0.1989, gap=0.050. Clashscore=3.12, Ramachandran outliers=0.00% (zero!), favored=99.47%, rotamer outliers=6.71%, Cbeta deviations=0, MolProbity score=1.73. 159 waters, 1 Ca²⁺, 1 Na⁺, 1 SO4. NCS group: chain A (res 1-96) ↔ chain B (res 1-96), 846 torsion NCS restraints. Improvement from starting model: R-free 0.396→0.199 (Δ=0.197). All 5 success criteria now met or exceeded.`
    - **Line `752`:**
      `1. **Final refined model**: `/agent/job/1sar_round7_001.pdb` (1654 atoms, 192 residues, 159 waters, 1 Ca²⁺, 1 Na⁺, 1 SO₄)`
  - **Member `final_report.md` SHA-256:** `a296f07513a5e05c085b1639632a0a2f48e1c7ab0cce1b7596b230cae110b5a2`
    - **Line `70`:**
      `Addition of Ca²⁺ at the 6.52σ peak position (66.611, 3.895, 13.404) and removal of the disordered chain B sulfate, followed by further refinement rounds, yielded steady improvement. A Na⁺ ion was also identified and modeled at a crystal contact involving chain B.`
    - **Line `150`:**
      `| **Ligands (SO₄)** | 2 | 1 | −1 (removed disordered) |`
- **Original erroneous narrative in frozen JSON (`line 828`):**
  > `"The trajectory log (claude_iterations.log:510, :752) reports a round-7 model with R-work = 0.1488, R-free = 0.1989, 159 waters (1,654 heavy atoms), and restored B:97:SO4, but that coordinate file was never packaged into cdba2c07-daff-4f60-ae96-12452b3a5fbb_artifacts.zip. Instead, data/1sar_final.pdb is the round-4 PHENIX model (SHA-256 8cbc1650f8be5a3833f98833fa514ec7d490c2c3bb9aa930413abac05e2a510b, 146 waters, 1,641 heavy atoms), while intermediate rounds 5 and 6 were saved separately as data/1sar_round5.pdb and data/1sar_round6.pdb."`
- **Defect and corrected attribution:**
  - Neither `claude_iterations.log:510, :752` nor `final_report.md:70, :150` claims a restored `B:97:SO4` in Round 7 (`claude_iterations.log:510, :752` each log `1 SO4` / `1 SO₄`, and `final_report.md:70, :150` states that the disordered chain-B sulfate was removed, reducing `SO4` ligands `2 -> 1`). Furthermore, `claude_iterations.log:752` writes `1654 atoms` without certifying a heavy-atom coordinate selection.
  - Corrected `description` emitted by `scripts/assess_refinement.py` (`assess_1sar_case_study`):
    > `"The trajectory log (claude_iterations.log:510, :752) claims an unarchived round-7 model with R-work = 0.1488, R-free = 0.1989, 1,654 atoms reported in the log (192 residues, 159 waters, 1 Ca2+, 1 Na+, and 1 SO4), and final_report.md:70, :150 describes removal of the disordered chain-B sulfate (ligand SO4 count 2 -> 1), not a restored B:97:SO4; because that round-7 coordinate file was never packaged into cdba2c07-daff-4f60-ae96-12452b3a5fbb_artifacts.zip, all round-7 counts remain unverified log/report claims rather than measured coordinate inventory. Instead, data/1sar_final.pdb is the round-4 PHENIX model (SHA-256 8cbc1650f8be5a3833f98833fa514ec7d490c2c3bb9aa930413abac05e2a510b, 146 waters, 1,641 heavy atoms), while intermediate rounds 5 and 6 were saved separately as data/1sar_round5.pdb and data/1sar_round6.pdb."`

### 1.2 `#964` — `2VXN` Null-Control (`unchanged_null`) $\Delta R_{\text{free}}$ Narrative

- **Target artifact:** `ref/research/data/refinement_assessment_1sar_and_controls_2026-10-18.json` (`sha256: db100e926bfcf6331c303087846c4d51117a4411c6afdf58877aada5dbf14245`) and `ref/research/refinement_assessment_case_study_2026-10-18.md:159`
- **Affected JSON pointer:** `/control_cohorts_evaluation/cross_cohort_findings/unchanged_control_invariance` (line `5849`)
- **Pinned source record:**
  - **Source path:** `ref/research/data/negative_control_round3_bench.json`
  - **Source SHA-256:** `3635bd878d160c770594c2c5ed92a1139dbbd8d63daa28a48aa249656d7f6dee`
  - **Row:** `rows[2]` (`pdb_id = "2VXN"`, `subject = "null"`, `d_min = 0.82`, lines `138–179`; also replicated in `/control_cohorts_evaluation/cohorts/unchanged_null/per_target_rows/2` of the frozen assessment JSON):
    - `numbers.d_phenix = 0.0214` (`pre.rfree_phenix = 0.1043` $\to$ `post.rfree_phenix = 0.1257`)
    - `numbers.d_gemmi = 0.022` (`+0.0220`; `pre.rfree_gemmi = 0.1059` $\to$ `post.rfree_gemmi = 0.1279`)
    - `numbers.d_refmac = -0.0122` (`pre.refmac.r_free = 0.1712` $\to$ `post.refmac.r_free = 0.159` under historical `BREF ISOT`)
- **Original erroneous narrative in frozen JSON (`line 5849`):**
  > `"In unchanged_null (subject='null', n=22), phenix and gemmi delta R-free agree tightly (median |d_phenix - d_gemmi| = 0.0007), while REFMAC5 (evaluable on 19/22 targets; 3/22 two-path-only: 9YGW, 8R5K, 8QXQ) shows smaller deltas (median d_refmac = +0.0018 vs median d_phenix = +0.0035) and triggers solver-disagreement notes on 2/22 targets (2VXN on F-data, where PHENIX/gemmi are positive (+0.0053 / +0.0067) while REFMAC sign is negative (-0.0122); 9TXE on F-geom, where cctbx worsening stands down against improved REFMAC zBOND (-0.043)). Separating Question 1 (implementation agreement) from Question 3 (change relative to input) keeps solver-convention differences distinct from physical model changes."`
- **Defect and corrected source-derived narrative:**
  - The summary string misquoted `+0.0053 / +0.0067` for `2VXN` PHENIX/Gemmi $\Delta R_{\text{free}}$ instead of `+0.0214 / +0.0220`.
  - In `scripts/assess_refinement.py` (`evaluate_control_cohorts`), the three formatted `2VXN` deltas (`+0.0214`, `+0.0220`, `-0.0122`) are now derived directly from the admitted `2VXN` `subject == "null"` row in `null_rows`, producing:
    > `"In unchanged_null (subject='null', n=22), phenix and gemmi delta R-free agree tightly (median |d_phenix - d_gemmi| = 0.0007), while REFMAC5 (evaluable on 19/22 targets; 3/22 two-path-only: 9YGW, 8R5K, 8QXQ) shows smaller deltas (median d_refmac = +0.0018 vs median d_phenix = +0.0035) and triggers solver-disagreement notes on 2/22 targets (2VXN on F-data, where PHENIX/gemmi are positive (+0.0214 / +0.0220) while REFMAC sign is negative (-0.0122); 9TXE on F-geom, where cctbx worsening stands down against improved REFMAC zBOND (-0.043)). Separating Question 1 (implementation agreement) from Question 3 (change relative to input) keeps solver-convention differences distinct from physical model changes."`
  - **Historical `BREF ISOT` vs. regenerated `BREF ANIS` distinction preserved:** In `ref/research/data/negative_control_round9_anis.json` (`pdb_id = "2VXN"`, lines `96–134`), PHENIX (`0.1043 -> 0.1257`, `delta = 0.0214`) and Gemmi (`0.1059 -> 0.1279`, `delta = 0.022`) endpoints and deltas are identical, while `refmac.isot` has `0.1712 -> 0.159` (`delta = -0.0122`) and `refmac.anis` has `0.1371 -> 0.1501` (`delta = +0.013`). The `BREF ISOT` $\to$ `BREF ANIS` convention change explains the historical `REFMAC5` sign disagreement on `2VXN`, not the erroneous `+0.0053 / +0.0067` transcription.

---

## 2. Round-2 Negative-Control Stratum vs. Actual Resolution Clarification (`#987`)

- **Updated document:** `ref/research/negative_control_round2.md` (`## Stratum-specific reporting (registered estimand)`)
- **Pinned sources:**
  - `ref/research/data/negative_control_round2_screen.json` (`sha256: dfebc4b131a8df1ceac4190c00bc1d60eeaba00846167530e5a4d1a2152cb313`): `23` rows with `status == "screened"` split `21` `stratum = true` and `2` `stratum = false`.
  - `ref/research/data/negative_control_round2_enrolled.json` (`sha256: 02fc974da9d1f8a2d8fb3c496c13196c200b31d182f1b7323cb25dcc59cbe7da`): `22` enrolled entries in `entries` split **20** `stratum = true` and **2** `stratum = false` by inherited registered stratum label (`scripts/screen_round1.py:668–669` propagates `stratum` onto D4 cluster replacements while `scripts/screen_round1.py:402` records the replacement's `d_min`), whereas actual enrolled `d_min` values split **15** `d_min <= 0.90 Å` and **7** `d_min > 0.90 Å` (all `<= 1.00 Å`), because **5** `stratum = true` D4 replacements have `d_min > 0.90 Å`: `7ATV` (`0.96 Å`), `6ZWY` (`1.00 Å`), `8QXQ` (`0.94 Å`), `6F1O` (`0.96 Å`), and `5KXV` (`0.98 Å`).

---

## 3. Known Sibling Record (`#1000` / Open PR #998)

- On `main`, `ref/research/refinement_assessment_case_study_2026-10-18.md` lines `48` and `51` contain the same historical Round 7 sulfate/atom-count wording (`Restored B:97:SO4` and `1,654` heavy atoms).
- That case-study prose sibling is tracked separately under `#1000` and has a prepared correction on open PR #998 (available on that branch, not yet landed on `main`).
- To preserve clean branch separation and avoid merge conflicts with PR #998, this change edits `ref/research/refinement_assessment_case_study_2026-10-18.md` only at the header audit-trail list and the `#964` `2VXN` paragraph (`line 160`), leaving lines `48–51` to land via PR #998.

---

## 4. Independent Pre-Commit Review Audit Trail (`#1003`)

- Fresh independent reviews (`841` and `842`) of the initial uncommitted branch identified a single in-scope provenance overclaim on line `8` of this note (`"no unarchived coordinate file exists"`), which was deduplicated and recorded on `#1003` (`https://github.com/CultureBotAI/protstruct_review/issues/1003#issuecomment-6756154678`) before correction; source and code changes otherwise had no findings.
- Line `8` was updated to state the bounded archive-absence fact (`"the claimed 1SAR Round 7 coordinate file is absent from the retained archive, so its reported inventory cannot be independently verified from retained coordinates"`) without asserting global nonexistence outside the retained archive, and `test_round7_archive_attribution_and_dated_correction_audit_trail` in `scripts/test_assess_refinement.py` now enforces this provenance-boundary statement and rejects the earlier phrasing on that boundary line.
- PRIMARY's initial `18` focused tests and original-defect / unrelated-drift sensitivity checks passed prior to this narrow correction; final focused and full hermetic QC and acceptance remain pending PRIMARY.
