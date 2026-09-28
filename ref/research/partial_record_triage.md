# Partial-record triage (P3b, Codex review action plan)

> **Historical triage, retained 2026-09-27; not a current completeness claim.** This document
> records the through-round48 disposition of six then-marked rows. Later scope and evidence
> qualifications, including T15's unproven historical denominator (#765/#766) and suspension of
> T14's confident-flip grading for producer mismatch (#809), are not resolved by those dispositions.
> For the current descriptive inventory, see [the threshold registry](../thresholds_and_standards.md)
> and [`threshold_evidence_status.yaml`](../threshold_evidence_status.yaml). Its two axes distinguish
> existing policy from retained evidence; neither a historical “resolved” label nor a retained record
> establishes independent calibration. The historical narrative below remains unchanged.

Round 42 established a *third* route out of a `⚠ partial record` — beyond round 21's "re-measure on a
committed subset" (works only when the lost members were unremarkable) and round 22's "closed as
unfixable" — namely **retire the lost estimator and re-base the figure on a coverage/distribution bound
over named data.** This document triages the **6 remaining** marked rows (round 42 resolved the ΔRMSD
row) into one of three routes. **Status: round 44 resolved #1 (geometry/clashscore, #275); item #2 was
verified and reclassified REPLACE → RETAIN; round 45 resolved #3 (favored %) and committed #4's record;
round 46 resolved #4 (outlier %) by making the check classification agreement (#284 closed); rounds 47–48
resolved #5 (H-placement flip-set) — record on a fresh named set, then the confident-conflict measure
(#287 closed). So 2 rows remain marked: #2 and #6, both RETAIN — every *resolvable* partial record is
now resolved.**

- **REPLACE** — re-base on named data now (a round-42-style move); resolves the mark, changes the
  registry, so needs pre-registration + approval.
- **REMEASURE** — a small re-run on a freshly committed set to record what the lost set didn't; each is
  a mini-round.
- **RETAIN** — the mark is honest and not resolvable by re-measurement; keep it as a disclosed limit.

Every figure below was checked against the committed data before classifying.

## The six rows

| # | row | what is partial | route | resolvable now? |
|---|---|---|---|---|
| 1 | Geometry Δ clause — **clashscore** | the 4.26× null ratio and 17.2 starting clashscore come from the lost ~11 entries | **REPLACE — DONE (round 44, #275)** | resolved |
| 2 | **L-test** ⟨\|L\|⟩ | only 5 of 27 datasets named; set uncommitted | **RETAIN** (was REPLACE; verified — see below) | already stated |
| 3 | Ramachandran/rotamer **favored %** | aggregate median/p90/max sound, but no per-entry value recorded | REMEASURE — **DONE (round 45)** | resolved |
| 4 | Ramachandran/rotamer **outlier %** | only the nonzero entries named; input set uncommitted | REMEASURE — **DONE (round 45 record + round 46 band, #284 closed)** | resolved |
| 5 | **H-placement** agreement | "worst 16.4 %" from an uncommitted 17-model set; 0 % members unnamed | REMEASURE — **DONE (round 47 record + round 48 confident-conflict measure, #287)** | resolved |
| 6 | Map-model fit (EM **CC_mask + d_FSC_model**) | publishes its uncertainty as a *range* (17–22) rather than a point | **RETAIN** | already honest |

## Detail and evidence

**#1 clashscore — REPLACE, DONE (round 44, #275).** The geometry row's last partial figures were the
clashscore null ratio (4.26×) and the "starting clashscore up to 17.2", both from the lost set. Over the
**44 fresh named entries** (rounds 37/38/41, Cα-matched, 37 gate-valid at `1 ≤ clashscore_pre ≤ 20`) the
max null ratio is **4.25×** — essentially the same value, now on named data, still under the 5× gate;
the fresh starting clashscore reaches **38.70**, so the named basis is *more* comprehensive than the lost
"17.2". Round 44 re-based both figures exactly as round 42 did the favored figure, **fully resolving the
geometry row** (backed 14 → 15, marked 6 → 5). Pre-registered and approved like round 42.

**#2 L-test — RETAIN (verified; was tentatively REPLACE).** This entry was classified REPLACE-by-citation
on the assumption that the mark records a *lost-denominator* defect a citation could erase. On inspection
that is not what it records. **Round 21 already re-derived the L-test on a committed, re-runnable
24-dataset set** (`bench_t13_wilson_b.py`'s `DEFAULT_SET`, then `bench_t13_l_test.py` over the same
cache) — and the registry row **already cites it**. So there is nothing left to flip: the live tolerance
(⟨|L|⟩ within ±0.02, same twin/no-twin call) already rests on committed data, and the quoted numbers are
already regenerable from a clean checkout.

What the mark still records is *not* resolvable by citation, and round 21 said so deliberately:

> "The `⚠ partial record` mark stays on the row: the historical 27 is still unreconstructable, and the
> new 24 inherits rather than replaces that limitation." — `tolerance_benchmark_round21.md`

Three things the 24-set citation cannot fix:
- **The historical *rate* (2 in 27) can't be checked** against the new 2-in-24 — three-plus datasets of
  the original 27 remain unidentifiable, so the denominator the row quotes is still partly lost.
- **The 24 is a *subset re-run*, not corroboration.** Round 21's own self-review (#93) caught and
  corrected exactly this over-claim — the agreement is largely guaranteed because it is the same
  structures through the same two deterministic programs, so the 24 makes the figures *reproducible*, a
  more modest claim than *independently confirmed*.
- **The two oracles share the Padilla–Yeates method**, so even a full re-run checks consistent
  computation, not method-independence — already disclosed in the row as a scope caveat.

None of these is a lost-figure that named data would recover; they are honest, disclosed limits of what
this cross-check *can* establish — the same kind of mark as #6 (EM map-model), not the same kind as #1.
So #2 is **RETAIN**, and the registry row — which already carries this reasoning — needs no change. The
"verify the round-21 set before flipping" caveat did its job: verification showed the flip is not
warranted.

**#3 favored % / #4 outlier % / #5 H-placement — REMEASURE.** Each has a *sound aggregate* but an
*uncommitted input set* whose unremarkable members (the zeros / the un-tabulated majority) were never
named. Round 21's caveat applies: re-measuring helps *only if the lost members were unremarkable* — and
here they are (zeros and near-zeros), so a small re-run on a freshly committed named set records the
per-entry values and names all members. Each is a bounded mini-round (a `bench_vs_deposited` /
`bench_t14` / `bench_t05_clashscore_h` re-run on a committed set), not a project.

> **Round 45 did #3 + #4 together** (`bench_vs_deposited` over the 42 named entries in `round45_ids.json`).
> **#3 favored resolved** — band holds (median \|Δ\| 0.000), per-entry values committed, mark cleared
> (registry 15 → 16 backed). **#4 outlier is only half resolved**: the record is now named/committed, but
> the run first surfaced an oracle bug (#281/#282 — outlier % was read from the wrong wwPDB endpoint) and,
> once corrected, the rotamer ±0.5 pp band is breached by two **altloc** entries (14ZZ 1.52 pp, 2YOL 0.57
> pp) whose rotamer *names* agree exactly — a denominator sensitivity, not a classification failure. Per
> the decision rule a breached band is a finding, not a quiet widen, so **#4's mark stays** pending the
> band-semantics decision (#284). `tolerance_benchmark_round45.md`.

**#6 EM map-model — RETAIN.** This mark is different in kind: the row **publishes its own uncertainty as
a range** (17–22 degradations, denominators stated) rather than pretending completeness. It is not
hiding a lost extreme; it is honest about a genuinely uncertain count. Re-measuring on a fresh EM set
would *tighten* it (a real EM round, ~GB of downloads) but the mark is not a defect to erase — it is a
disclosed limit. Lowest priority; retain unless a fresh EM round is being run for other reasons.

## Recommended order

1. ~~**#1 clashscore (round 44)**~~ — **DONE (#275).** Re-based on 44 named entries; geometry row fully
   backed, marked 6 → 5.
2. ~~**#2 L-test**~~ — **verified → RETAIN.** The row already cites round 21's committed 24-set; the
   residual mark (unverifiable historical rate, subset re-run, shared method) is not citation-resolvable.
   No registry change. This is a documentation correction only.
3. ~~**#3 favored (round 45)**~~ — **DONE.** Re-based on 42 named entries; band holds, mark cleared
   (registry 15 → 16 backed, 5 → 4 marked).
4. ~~**#4 outlier (round 45 record + round 46 band)**~~ — **DONE (#284 closed).** Round 45 committed the
   record; round 46 made the load-bearing check per-shared-residue **classification agreement** (rotamer
   OUTLIER-verdict and Ramachandran verdict both 1.0000/41; stricter rotamer-name agreement 0.9919 on
   15C8, three insertion-code residues, all Favored), demoting the denominator-sensitive raw-% bands to
   diagnostics. Mark resolved (registry 16 → 17 backed, 4 → 3 marked).
5. ~~**#5 H-placement (round 47 record + round 48 measure)**~~ — **DONE (#287 closed).** Re-based the
   flip-set figure on the fresh named 42-set (not the lost 17 — round 22's trap), then made the check the
   **confident-conflict rate** (1.80 %, vs the raw 10.95 % inflated by one builder's `X`-hedges). Mark
   resolved (registry 17 → 18 backed, 3 → 2 marked).
6. **#6** — retain; revisit only alongside a fresh EM round.

**Every *resolvable* partial record is now resolved. The two that remain — #2 L-test and #6 EM
map-model — are RETAIN by nature (honest disclosed limits no re-measurement can erase).**

**After round 48: 2 rows remain marked — #2 L-test and #6 EM map-model, both RETAIN.** *(Historical — after round 46: 3 rows remained marked; #2 and #6 RETAIN, #5 the one clean REMEASURE left, since resolved.)*

No registry value is changed by this document; it is the plan. Executing #1 (or any REPLACE) changes a
`[benchmark]` row and requires the round-42 discipline: pre-register the method, compute from a committed
re-runnable script, and get explicit approval before the mark is flipped.
