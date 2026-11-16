# Order 5 Review: 1SAR MTZ `COLUMN` Header Extrema vs Data-Word Audit (`#1189`)

Date: 2026-11-09
Issue reference: `https://github.com/CultureBotAI/protstruct_review/issues/1189`
Scope: `scripts/onesar_rerun.py`, `scripts/test_onesar_rerun.py`

## 1. Retained 1SAR Observation

In the committed 1SAR archive member `data/1sar.mtz` (staged as `inputs/original_data.mtz`, SHA-256 `f36d5fe685a3e524e8809d17d19ce12073acdf339eba2cfd3b0347a818850ab2`, `ncols = 16`, `nrows = 7248`, header byte offset `463952`) and its six-column observation projection `inputs/projected_observations.mtz` (SHA-256 `6edbe54b2ec7b815f30b6bd20a7264a7c978721189670e39e20d876d9b4fece7`, `ncols = 6`, `nrows = 7248`, header byte offset `174032`), the `COLUMN` header cards for the three Miller index columns (`H`, `K`, `L`, all `type = "H"`, `dataset_id = 1`) carry stale extrema tokens that do not match the actual 4-byte IEEE-754 float32 Miller index words stored across the 7,248 reflection rows (`7228` observation-eligible rows plus `20` `VALM NAN` unassigned padding rows, `0` non-integral or non-finite HKL words):

| Axis | Column Index | Declared `COLUMN` Tokens (`min_token`, `max_token`) | Declared Integer Bounds | Actual All-Row Bounds (`7248` rows) | Original `COLUMN` Card Offset | Projected `COLUMN` Card Offset | Status |
| --- | ---: | --- | --- | --- | ---: | ---: | --- |
| `H` | `0` | `("0", "0")` | `(0, 0)` | `(0, 25)` | `464912` | `174992` | `mismatch` |
| `K` | `1` | `("0", "0")` | `(0, 0)` | `(0, 31)` | `465072` | `175072` | `mismatch` |
| `L` | `2` | `("2", "2")` | `(2, 2)` | `(0, 15)` | `465232` | `175152` | `mismatch` |

Raw 80-byte `COLUMN` card hex (identical in `original_data.mtz` and `projected_observations.mtz`):

- `H`: `434f4c554d4e2048202020202020202020202020202020202020202020202020202020202020482020202020202020202020202020202020302020202020202020202020202020202020302020202031`
- `K`: `434f4c554d4e204b202020202020202020202020202020202020202020202020202020202020482020202020202020202020202020202020302020202020202020202020202020202020302020202031`
- `L`: `434f4c554d4e204c202020202020202020202020202020202020202020202020202020202020482020202020202020202020202020202020322020202020202020202020202020202020322020202031`

Committed Attempt 04 input-side evidence and selectors:

- `data/coscientists/openscientist/retained_1sar_pr1007_R4_rfactors_attempt04_analysis/raw-side-effects.json::mtz_headers[0..1].extrema` (summarized in `ref/research/1sar_rerun_2026_11_09_attempt04_readiness.md:108`) records `declared_min` / `declared_max` tokens `"0".."0"`, `"0".."0"`, `"2".."2"` alongside `actual_min` / `actual_max` `0.0..25.0`, `0.0..31.0`, `0.0..15.0` for `inputs/original_data.mtz` (`mtz_headers[0]`, `dataset_id = 1`) and `inputs/projected_observations.mtz` (`mtz_headers[1]`, `dataset_id = 1`).
- `data/coscientists/openscientist/retained_1sar_pr1007_R4_rfactors_attempt04/inputs/input_hkl_ledger.json` (SHA-256 `35543c5821665de8f65b5fbd153669556dfef766ac8b156dc001a0c5b667a51e`, `raw_rows` / `eligible_by_hkl` / `ineligible_rows`) records all `7248` decoded reflection rows spanning `H: 0..25`, `K: 0..31`, `L: 0..15`, while `data/coscientists/openscientist/retained_1sar_pr1007_R4_rfactors_attempt04/inputs/input_admission.json::projection` previously omitted an `H`/`K`/`L` `COLUMN` header-extrema-vs-data diagnostic.
- Separately, the native REFMAC output artifact `data/coscientists/openscientist/retained_1sar_pr1007_R4_rfactors_attempt04/refmac/refmac_hklout.mtz` (SHA-256 `e21ce039b11e8b83c5deebfa3059fafeef7906cf1d10a1d3cf20b57f56b578e2`, exported in `data/coscientists/openscientist/retained_1sar_pr1007_R4_rfactors_attempt04/refmac/refmac_hklout_raw_export.json::header_parse.columns[0..2]` and summarized in `raw-side-effects.json::mtz_headers[2].extrema`) is a distinct output file whose `H`, `K`, and `L` columns belong to `dataset_id = "0"` (`dataset_name = "HKL_base"`) with regenerated header tokens `"0".."25"`, `"0".."31"`, `"0".."15"` (and `refmac_hklout_raw_export.json` has no top-level `column_summaries` field).

## 2. Additive Diagnostic Contract in `scripts/onesar_rerun.py`

1. **`inspect_mtz_hkl_header_extrema(mtz_bytes)`**:
   - Slices the raw 80-byte `COLUMN` cards directly from `mtz_bytes[card_offset : card_offset + 80]` at their exact header byte offsets (preserving exact card padding and hex without reconstructing from whitespace-stripped strings).
   - Parses `min_token` and `max_token` via `_parse_mtz_hkl_extrema_token` using exact `Decimal.as_tuple()` decomposition (independent of ambient `Decimal` context precision and binary float rounding) with bounded digit/exponent span (`<= 39` integer digits). Numerically equal integral representations (`"0"`, `"0.0"`, `"-0.0"`, `"+0.000"`, `"1e0"`, `"2.0000"`) evaluate to their exact integer value, whereas malformed, non-ASCII, underscore-containing, non-finite (`NAN`, `INF`, `-INF`), or non-integral (`1.5`, `1.00000000000000000001`, 36-digit `1.000...001`) tokens are classified as `"invalid_metadata"` with `declared_min = None` / `declared_max = None`.
   - Independently unpacks all `nrows` IEEE-754 float32 words in columns `0`, `1`, and `2` (`H`, `K`, `L`) across **all** rows in the data block (`80 .. header_byte_offset`), including observation-ineligible `VALM NAN` padding rows, recording `row_count`, `invalid_word_count`, `actual_min`, and `actual_max`.
   - Assigns an explicit status (`"consistent"`, `"mismatch"`, or `"invalid_metadata"`) to each axis (`H`, `K`, `L`) and to the artifact record.
2. **Sibling attachment in `project_observation_mtz` and `stage_subject_inputs`**:
   - `project_observation_mtz` attaches `"hkl_header_extrema_diagnostic"` as a sibling field in its returned `summary` dictionary (containing overall `status`, `consistent`, `input`, and `projected` diagnostic blocks), which `stage_subject_inputs` persists under `admission_record["projection"]["hkl_header_extrema_diagnostic"]` in `inputs/input_admission.json`.
   - `crystallographic_context` keys (`cell_a_b_c_alpha_beta_gamma`, `resolution_limits_inverse_a2`, `symmetry`) and `projected_observations.mtz` bytes remain completely unchanged.

## 3. Why Stale Header Extrema Are Diagnostic Only

- Within the audited repository code paths, the local ledger and retention paths (`build_input_hkl_ledger` in `scripts/onesar_rerun.py`, `mtz_observations` in `scripts/audit_1sar_retained_evidence.py`, and `audit_mtz_retention` in `scripts/t03_reflection_retention.py`) derive reflection keys and selection from the decoded binary IEEE-754 data words rather than reading `COLUMN` card min/max summary tokens, while `inspect_mtz_hkl_header_extrema` derives actual all-row ranges from those data words (`scripts/onesar_rerun.py:561-570`) and separately reads and parses the `COLUMN` extrema tokens (`scripts/onesar_rerun.py:552-557`) for comparison.
- Consistent with `ref/research/1sar_rerun_2026_11_09_attempt04_readiness.md:108` and `#1189`, this offline input-admission diagnostic establishes **no** native PHENIX or REFMAC numerical effect, reflection-selection effect, R-factor explanation, or native failure cause.
- Rewriting `COLUMN` cards during `project_observation_mtz` would alter the projected MTZ byte stream (`6edbe54b2ec7b815f30b6bd20a7264a7c978721189670e39e20d876d9b4fece7`) and erase the provenance link to the upstream archive's raw `COLUMN` cards.
- Conversely, structural header defects (wrong `COLUMN` token count, missing `H, K, L` prefix, unmerged columns) and data-word defects (non-integral or non-finite Miller index words, duplicate HKL keys) continue to fail closed.

## 4. Candidate-0 Review Audit (`#1209`, `#1210`, `#1211`) and Verification Status

Fresh independent static review of candidate 0 identified three bounded issues (all triaged in-scope by PRIMARY; `#1209` reviewer priority P1 was triaged P2 by PRIMARY because the uncommitted test fixture safely blocks acceptance without affecting runtime scientific data):

1. **`#1209` (`scripts/test_onesar_rerun.py`)**: The 38-character high-precision fractional token `"1." + ("0" * 35) + "1"` (`37` significant digits `> 28`) combined with `{name:<30s}` padding in `_build_synthetic_mtz` produced an 82-byte `COLUMN` card, causing candidate-0 focused test execution (`28` tests) to fail with `1` structural-admission error at `scripts/test_onesar_rerun.py:1762` before reaching `_parse_mtz_hkl_extrema_token`. `_build_synthetic_mtz` now uses compact single-space `COLUMN` formatting only when an explicit `column_extrema` override would exceed 80 characters (preserving default builder bytes and all existing structural negative tests), rejects any synthetic `COLUMN` card exceeding 80 characters, and `test_hkl_header_extrema_diagnostic_synthetic_matrix` asserts 80-byte card width and header alignment before calling `project_observation_mtz`.
2. **`#1210` (Section 1 of this note)**: Replaced the nonexistent `refmac_5_8_0430/refmac_raw_mtz_export.json` and `column_summaries` reference with the actual committed Attempt 04 input-side artifacts and selectors (`inputs/original_data.mtz`, `inputs/projected_observations.mtz`, `inputs/input_hkl_ledger.json`, `inputs/input_admission.json::projection`, `retained_1sar_pr1007_R4_rfactors_attempt04_analysis/raw-side-effects.json::mtz_headers[0..1].extrema`, and `ref/research/1sar_rerun_2026_11_09_attempt04_readiness.md:108`), and explicitly distinguished the separate native output artifact `refmac/refmac_hklout.mtz` (`refmac/refmac_hklout_raw_export.json::header_parse.columns[0..2]`, `dataset_id = "0"` / `HKL_base`, `"0".."25"`, `"0".."31"`, `"0".."15"`).
3. **`#1211` (Section 3 of this note)**: Restricted affirmative statements about binary row decoding to the audited repository functions, stated explicitly that this diagnostic establishes no native numerical/selection effect, R-factor explanation, or native failure cause, and resolved the candidate-1 P3 wording residual so that `inspect_mtz_hkl_header_extrema` is described as deriving actual all-row ranges from data words while separately reading/parsing `COLUMN` extrema tokens (`scripts/onesar_rerun.py:552-557`) for comparison rather than not reading those tokens.

**Verification status boundary**:
- Unchanged production module `scripts/onesar_rerun.py` (SHA-256 `8d023bc3e9a4dbd1e936d13a1683106ac647c2bce293f605f581098464b7ffe9`) already **passed** PRIMARY's independent exact projection, ledger, retained-byte, and persisted-admission checks as well as old-source missing-public-field sensitivity.
- Candidate 0's focused test suite failed (`28` tests, `1` error at `test_onesar_rerun.py:1762`) due to `#1209`; candidate 1's corrected `scripts/test_onesar_rerun.py` focused suite (`28` tests) **passed**, and PRIMARY's independent fixture-width proof confirmed the old 82-byte overflow, the corrected 80-byte card with the complete 38-character token, and unchanged default builder bytes.
- Independent re-review of the corrected note and the combined full hermetic QC gate (`scripts/validate.sh`) remain pending PRIMARY execution.

## 5. Non-Extrapolation Statement

This change adds an offline input-admission diagnostic for future `project_observation_mtz` and `stage_subject_inputs` runs and unit tests. Existing retained evidence bundles under `data/coscientists/openscientist/` and existing `EVAL_*` / `QDS_*` records are preserved byte-for-byte without retroactive modification.
