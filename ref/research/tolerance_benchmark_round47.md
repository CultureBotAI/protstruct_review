# Tolerance benchmark — round 47: the flip-set figure re-measured on named data; the raw band breaches, and why

> **Current status (2026-09-27, #809): historical record, not current grading authority.**
> The executed producer pair was PHENIX-distributed Reduce versus mmtbx.reduce2, not the
> claimed standalone pair. Flip grading is suspended; see the dated correction below.

Re-bases **P3b triage item #5** — the H-placement row's Asn/Gln/His flip-set figure — onto a fresh named
set, resolving the *record* but surfacing that the raw ≤ 10 % band **fails** on named data, for a reason
the row already anticipated. Pre-registered in
[`tolerance_benchmark_round47_preregistration.md`](tolerance_benchmark_round47_preregistration.md).

## Method

`bench_t14_flip_sets.py` over the **42 committed named entries** (`round45_ids.json`), comparing standalone
Richardson `reduce` against `mmtbx.reduce2` (`approach=add add_flip_movers=True`) on the per-residue
Asn/Gln/His flip decision. Fresh named set, **not** a subset re-run of the lost 17 (round 22 established
that would mislead — the lost members are the zero-disagreement ones). 12CI (nucleic) has no flippable
residues and is named-excluded; 41 protein entries carry flip records. Per-entry data in
`round47_flip_sets.json`.

## Result against the registered predictions

| prediction | verdict |
|---|---|
| **P1** aggregate named flip-disagreement rate ≤ 10 % | **falsified** — **340 / 3105 = 10.95 %** |
| **P2** a single model may exceed 10 % | **confirmed, and then some** — **25 of 41** models exceed 10 %; worst **1TIJ 40 %** (8/20) |
| **P3** most disagreements are the weaker uncertain category, not genuine conflicts | **confirmed** — **279 of 340 (82 %)** are reduce category **X** (uncertain); only **56 are confident** (F/K) |
| **P4** every model named, per-residue disagreements committed | **met** — `round47_flip_sets.json` |

## The raw band fails, but the failure is one builder's own uncertainty

The raw disagreement rate is **10.95 %**, above the ≤ 10 % band — so **P1 is falsified**, and per the
registered decision rule (a band failing on a named set is a finding, not a quiet widen) the H-placement
row's `⚠ partial record` mark **stays**. But P3, also registered, explains the breach: of the 340
disagreements, **279 (82 %) are residues reduce itself flagged category `X` (uncertain)** and 5 are `C`
(clashes either way). Only **56 are confident** reduce calls (55 `F`, 1 `K`). The registry row already
names this distinction — "an `X`-vs-`K` disagreement is two builders hedging differently on an ambiguous
residue; an `F`-vs-`K` is a genuine conflict about the model."

So the raw rate counts one builder's *own* hedging as a "disagreement." The **genuine-conflict rate — a
residue where reduce is confident but reduce2 still disagrees — is 56 / 3105 = 1.80 %**, far under the
band. The raw 10.95 % breach is not evidence the two builders genuinely conflict on 11 % of residues; it
is evidence that ~9 % of flippable residues are *ambiguous enough that reduce declines to commit*, and on
those reduce2's independent call lands differently often enough.

## What this round settles, and what it defers

- **The record is resolved** — the set is named (`round45_ids.json`, 41 protein) and every per-residue
  disagreement is committed. The lost 17-model set is retired, not recounted (round-21/22 caveat: this is
  a fresh named basis, not a subset re-run of the lost set).
- **The raw band does not hold** on named data (10.95 %), so **the mark stays** — this round does not
  resolve #5.
- **The measure is the question.** Whether the flip-set check should count raw disagreements (10.95 %,
  breached) or genuine confident conflicts (1.80 %, holds) is a tolerance-semantics decision, filed
  separately and approved for a follow-up round (the confident-conflict direction) — the same shape as
  round 45 → 46 (#284): re-measurement resolves the record, then a follow-up fixes the measure. Round 48
  applies it.

## Scope limits

- **`reduce` vs `reduce2` only** — the two builders the tolerance names; not a claim about other H builders.
- **Same-binary for `reduce2`** — `phenix-2.0-5936` pinned (round 43 registers the cross-version test).
- **Flip decision, not H position** — the count is nearly insensitive to the electron-cloud/nuclear
  convention; the row already warns the count must not be read as evidence two H builds match on position.


## Producer attribution and grading correction (2026-09-27, #809)

The original text above is retained as the historical report/registration, not rewritten evidence.
`bench_t14_flip_sets.py::collect` assigns `a = flip_calls(phx)` and compares `a` with reduce2;
`b = flip_calls(std)` does not produce `n_reduce2_shared` or the reduce2 disagreement fields.
Consequently the retained counts are PHENIX-distributed Reduce versus mmtbx.reduce2. Both producer
Tool identities are catalogued cctbx-family. Distinct builders do not establish the independently
benchmarked standalone pair that the later grading rule claimed.

The retained round48 row counts still recount to 56/3105 confident conflicts and 340/3105 raw
disagreements across 41 protein entries (12CI is the named exclusion from the 42-entry set).
These are historical informational numbers, not an independent calibration. The historical cohort
band is suspended at every scope pending a matched independent benchmark. No raw JSON, original
execution date, issued Eval/QDS, or frozen emitter implementation is changed by this correction.
See `t14_flip_grading_suspension_2026-09-27.md` for the rerunnable recount and current policy.
