# Runtime and perturbation input integrity — 2026-09-27

## Full-queue checkpoint

Main is `15edb68456577efbfbe416284678f83b14716312` after PRs #811, #820 and #818.
The complete GitHub survey returned 15 open issues, matching the API total, and zero open PRs.
Bodies and comments were read, including the producer correction needed in #799. The original
12-item goal is not narrowed to the engineering fixes in this slice.

| Original issue | Current disposition at this checkpoint |
|---|---|
| #799 | P1: engineering prerequisite merged in #811; fresh dictionary-loaded measurements remain. |
| #777 | Fixed on main by #818; scientific cross-version validation is not implied. |
| #762 | Fixed on main by #820; Ubuntu/macOS CI passed on the reviewed head. |
| #798 | P2: user approved both clashscore version pins; policy change is prepared, not merged. |
| #760 | External dependency: a second licensed PHENIX build is still not located; #816 is also a prerequisite. |
| #785 | P2: capability-specific recommendation correction prepared, not merged. |
| #786 | P2: scoped preregistered-floor adoption is awaiting the user's policy choice. |
| #764 | P2: pre-free-R and usable-reflection definitions remain unresolved. |
| #766 | P2: current evidence-status ledger/count reconciliation remains unresolved. |
| #765 | P2: exact-denominator T15 rerun remains; execution authorized, preregistration/canary required. |
| #767 | P2: real CCP4 T13 canary remains; execution authorized, no completed canary claimed. |
| #790 | P2 optional analysis: clashscore decomposition remains; execution authorized with preregistration/canary. |

The highest-priority new issue, #809, suspends an unsupported published flip-grading rule and is
being handled on a separate policy branch. This slice handles the four remaining reproducible
engineering defects: #812, #816, #821 and #822. New issues #821/#822 were filed before their fixes.

## Changes and limits

- PHENIX version probes remove only inherited `PHENIX_VERSION` and `PHENIX_RELEASE_TAG`, preserving
  other launch variables and the caller's environment. Build evidence records removed variable
  names, not values. Both the configured-build probe and general PHENIX environment report use it.
- All three shared subprocess adapters distinguish `env=None` (inherit) from `env={}` (explicitly
  empty). CCP4's separate setup behavior is unchanged.
- PDB and mmCIF perturbations regenerate the inexpensive expected coordinates before lookup.
  One shared deterministic-product cache binds source bytes/path, exact parameters, producing
  script/runtime and actual output bytes. mmCIF additionally names the Gemmi version/module.
  The original random-number and coordinate-rounding algorithms are preserved, including mmCIF's
  sigma string spelling in its random seed. Callers use the returned authenticated path.
- Old requested filenames are not adopted or overwritten. Corrupt or incomplete verified bundles
  fail closed without repair. Identical calls reuse the same verified bytes without rewriting.

This is not a full installed-library fingerprint or a scientific cross-version result. A producing
script change conservatively creates a fresh perturbation bundle even if its coordinate algorithm
did not change. No assertion is made that a retained historical experiment used stale coordinates.
Raw measurements, issued Eval/QDS sheets and frozen emitter implementations are unchanged.

## Review and regression evidence

The PHENIX/environment patch passed independent read-only review, five focused tests and 49 existing
cache tests with the updated adapter loaded. Its actual pre-fix code reproduces the inherited fake
old-version banner and the empty-environment defect in all three adapters (four intended assertion
failures, no setup errors). The fake dispatchers are not PHENIX executables.

The perturbation patch passed an independent source review and 23 synthetic fixture tests. Loading
the original PDB and mmCIF functions into memory causes all four seed/source guards to fail with
assertion failures, not import/setup errors. Old/new output bytes match, including mmCIF sigma 0.2,
integer 1 and float 1.0. No active checkout was reverted for these negative controls.

The full integrated gate and final integration review must pass before this slice is committed.
