# Round 48 — pre-registration

> **Current status (2026-09-27, #809): historical record, not current grading authority.**
> The executed producer pair was PHENIX-distributed Reduce versus mmtbx.reduce2, not the
> claimed standalone pair. Flip grading is suspended; see the dated correction below.

Registered **before the flip-set check is re-defined**. Settles **#287**, the measure question round 47
opened: the raw `reduce`-vs-`reduce2` flip-disagreement rate on the named 42-set is **10.95 %**, over the
≤ 10 % band — but **82 % of that (279/340) is residues `reduce` itself flagged category `X` (uncertain)**,
not genuine conflict. The chosen, approved direction is **confident-conflict rate primary**.

## The tolerance change (this is the registered change)

The load-bearing flip-set check becomes the **genuine confident-conflict rate**: a residue counts as a
disagreement only when `reduce` is **confident** (category `F` = flipped or `K` = keep) *and* `reduce2`
still disagrees. Residues where `reduce` writes `X` (uncertain) or `C` (clashes either way) are one
builder declining to commit, not two builders conflicting about the model — the registry row already
draws this line ("`X`-vs-`K` is two builders hedging; `F`-vs-`K` is a genuine conflict"). The **raw
disagreement rate is retained as a reported diagnostic**, with its `X`/`C`/`F`/`K` breakdown. This
mirrors round 46 (#284): re-measurement (round 47) resolved the record; this round fixes the measure to
the robust signal.

## Method

Extend `bench_t14_flip_sets.py` to emit, per model and in aggregate, the **confident-conflict count** —
`reduce`-vs-`reduce2` decision disagreements restricted to `reduce` category ∈ {`F`, `K`} — alongside the
raw count it already reports. Add a unit test. Re-run over the **42 named entries** (`round45_ids.json`);
the `reduce2` reports and `reduce` builds are cached from round 47, so this recomputes rather than
rebuilds. No band value change: the band stays **≤ 10 %**, now read against the confident-conflict rate.

## Predictions — figure disclosed (computed from round 47's committed data)

As rounds 38/42/44/46 did, the figure already exists (round 47 committed `round47_flip_sets.json` and the
cached builds), so it is disclosed; the **registered change is the measure re-definition and the decision
rule**, not the number.

**P1 — the confident-conflict rate holds under the ≤ 10 % band.** Observed **56 / 3105 = 1.80 %** over
the 41 protein entries. *Falsified* if the recomputed confident-conflict aggregate exceeds 10 %.

**P2 — the confident conflicts are dominated by confident *flips* (`F`), not confident *keeps* (`K`).**
Observed **55 `F`, 1 `K`**. This says the residual genuine disagreement is `reduce` confidently flipping
where `reduce2` keeps — a real but rare model-level difference, nameable per residue.

**P3 — no single model's confident-conflict rate is alarming.** The raw per-model rates reached 40 %
(1TIJ), but those were `X`-driven; the confident-conflict per-model rates should be far lower.
*Recorded, and any model above 10 % on the confident measure is named.*

## Decision rule — registered before the recompute

- **P1 holds** (confident-conflict aggregate ≤ 10 %) → adopt the confident-conflict rate as the
  load-bearing flip-set check, demote the raw rate to a reported diagnostic, and **resolve the
  H-placement row's `⚠ partial record` mark** (round 47 committed its record; this settles the measure).
  Registry **17 → 18 fully backed, 3 → 2 marked** — and the two remaining marks (#2 L-test, #6 EM
  map-model) are both **RETAIN**, so the *resolvable* partial records are then exhausted. Close #287.
- **P1 fails** (confident-conflict aggregate > 10 %) → do **not** adopt; a genuine confident-conflict rate
  over the band would be a real finding about the two builders, mark stays.

## What this round does not do

- **It does not change the band value** — ≤ 10 % stays; only what it is measured against changes.
- **It does not retire the raw rate** — the raw 10.95 % and its `X`/`C`/`F`/`K` breakdown stay on record
  as a diagnostic, so the ambiguity of Asn/Gln/His flips is still visible.
- **`reduce` vs `reduce2`, same-binary `reduce2`** — the two named builders, `phenix-2.0-5936` pinned
  (round 43 registers the cross-version test).
- **No other row changes** — #2 L-test and #6 EM map-model (both RETAIN) are untouched.


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
