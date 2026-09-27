# Tolerance benchmark — Asn/Gln/His flip sets (phenix.reduce vs standalone reduce)

Closes the other gap PR #28 opened. The H-placement tolerance in
`ref/thresholds_and_standards.md` requires the two H builders to produce the "same Asn/Gln/His flip
set", but PR #28 measured only H count and clashscore, because `phenix.clashscore` does not emit flip
records. `reduce` does.

Reproduce with:

```bash
python3 scripts/bench_t14_flip_sets.py --ids-file <ids.json> --cache <dir> --json <out.json>
```

## Configuration

Both builders write `USER  MOD` records into the output PDB, one per flippable residue:

```
USER  MOD Single : A  32 GLN     :FLIP  amide:sc=   0.435  F(o=-0.2,f=0.44)
USER  MOD Single : A   2 GLN     :      amide:sc=   1.61   X(o=1.6,f=1.2)
```

The letter before `(o=` is the flip category — `F` flipped, `K` keep, `C` clashes either way,
`X` uncertain. Both the **decision** and the **category** are compared: an `X`-vs-`K` disagreement is
two builders hedging differently on an ambiguous residue, while `F`-vs-`K` is a real conflict about
the model.

Test set: 17 deposited X-ray models (the PR #28 set), **634** flippable Asn/Gln/His residues.

## Results

| | |
|---|---:|
| Models compared | 17 |
| Flippable residues compared | 634 |
| Models with identical flip calls | 13 / 17 |
| **Flip-decision disagreements** | **0** |
| Category-only disagreements | 1 |
| Residues recorded by only one builder | 6 |
| Residues flipped (PHENIX / standalone) | 56 / 54 |

The 2-flip difference in the totals comes entirely from the 6 residues that appear in only one
builder's records — among the 634 **shared** residues there is not a single decision disagreement.

## Findings

**1. Same program, *different chemical dictionaries*.** Version strings are identical:

```
$ phenix.reduce -version   → reduce.4.16.250520
$ reduce -version          → reduce.4.16.250520
```

`phenix.reduce` is the Richardson `reduce` binary, redistributed — so the flip *logic* is one
implementation run twice. But the two distributions do **not** ship the same het dictionary, and the
`USER  MOD` header records it:

```
30TW  phenix.reduce  ... std=5902, adj=71
30TW  standalone     ... std=5155, adj=53
```

That difference is invisible on protein residues and decisive on ligands — see finding 4.

> **Correction (2026-09-27, #799).** The two distributions' het dictionary files are **byte-identical**
> (`~/tools/reduce-src/reduce_wwPDB_het_dict.txt` and PHENIX's `reduce/reduce_wwPDB_het_dict.txt`). The
> standalone build's compiled default path (`/usr/local/reduce_wwPDB_het_dict.txt`) does not exist here,
> `REDUCE_HET_DICT` is unset, the bench scripts pass no `-DB`, and they discarded `reduce`'s stderr
> (originally with `2>/dev/null`, now through `scripts/toolchain.py`'s `run_to_file`, #805) — so, as invoked, the standalone path most likely loaded **no** het dictionary and
> added no hydrogens to non-standard hetero groups (it prints `could not open` and `Hydrogens not added`
> when run that way today; the benchmark-time configuration was not recorded). The `std=`/`adj=` values
> are `reduce`'s hydrogen tallies, not dictionary contents. Read every attribution below to "different
> het dictionaries" as "standalone build without a dictionary": the ligand-model divergence and the
> void rule stand; their stated reason does not. Re-measurement with the dictionary loaded is #799.

> **Superseded in part (round 6).** This section concluded that a genuine flip comparison was
> unavailable because `mmtbx.reduce2` "reports no flip information". That was true of the *run* and
> wrong about the tool: `add_flip_movers` defaults to **False**, so reduce2 built no flip movers and
> had nothing to report. With `approach=add add_flip_movers=True` it reports every group's final
> pose, and the comparison shows **48 disagreements over 639 residues (7.5 %)** — see
> `ref/research/tolerance_benchmark_round6.md`. The clause is not vacuous; it needed a rate rather
> than an identity, and the identity result below is an artefact of comparing a binary with itself.

**2. So the "same flip set" clause checks nothing for this tool pair.** A tolerance clause that is
satisfied by construction gives false assurance: it reads as cross-tool corroboration and provides
none. It should be stated as a same-implementation identity check, and a genuine flip-set comparison
needs a *different* H builder — `phenix.reduce2` (the cctbx reimplementation) or Molprobity's
`reduce2` are the candidates on this machine.

**3. This also sharpens PR #28's clashscore result.** That benchmark measured a median 0.115
clashscore difference between the "cctbx path" and the "standalone path" under a matched H
convention, and left the cause open. Since both paths build hydrogens with the *same binary*, the
0.115 cannot come from H placement — it must come from the clash-counting step
(`phenix.clashscore`'s internal contact analysis vs the `probe` summation in
`scripts/bench_t05_clashscore_h.py`). The H-build convention still dominates when it is
*mismatched* (median 9.95); it is the matched-case residual that is now attributed correctly.

> **Correction (2026-09-26, #776/#793/#794; the attribution was withdrawn in #728).** Point 3 is
> withdrawn. The 0-disagreement flip result shows the two names reach the same `reduce` release; it
> does not show that the clashscore benchmark's two paths scored the same hydrogens. `phenix.clashscore`
> builds its own H internally with flips disabled by default (`-pen9999`) and with the het dictionary
> loaded, while the benchmark ran standalone `reduce -build` (flips enabled), which as invoked most
> likely loaded no het dictionary (see the #799 correction under finding 1). The H coordinates were not
> compared, so the
> 0.115 residual cannot be assigned to the clash-counting step; see the matching correction in
> `tolerance_benchmark_clashscore_h.md` and `ASSUM_molprobity_h_atom_placement_2026_09_23`.

**4. The H-count half of the tolerance was measured on the wrong pair, and fails on the right one.**
PR #28 set "H-atom count within ± 0.1 %" from a comparison of *one builder in two conventions*
(standalone `reduce` electron-cloud vs nuclear). The tolerance names a different pair — standalone
`reduce` vs `phenix.reduce` — and on that pair:

| Subset | n | median \|Δ\| | p90 | max | exceeding 0.1 % |
|---|---:|---:|---:|---:|---:|
| Protein-only models | 4 | 0.000 % | 0.000 % | **0.000 %** | 0 |
| Models with non-water hetero | 13 | 0.058 % | 2.467 % | **3.955 %** | 6 |

Protein hydrogens agree **exactly** — 12 of 18 models are identical to the atom. Every model that
diverges is ligand-bearing (37AP/37AS: ADP, AMP, PEG, PG4; 37BG: ZN, BTB, SAM; 28SZ: NA, DXC;
24MR: CA, GAL, NDG), and the divergence traces to the het-dictionary difference in finding 1. Three
models exceed even the *original* ±2 %.

**5. Flips are rare in deposited models, which limits the flip half of the test.** Only 7 of 17
models had any flips at all, and one (24MR) contributes 49 of the 56. Most deposited structures have
already been flip-optimised before deposition, so deposited coordinates under-sample exactly the
residues this tolerance is about.

## Applied

> **Asn/Gln/His flip-set agreement — SUPERSEDED by round 6.** Exact match holds only between
> `phenix.reduce` and standalone `reduce`, which are the same binary (reduce.4.16.250520; 0 of 634).
> Against the independent `mmtbx.reduce2` the disagreement rate is **7.5 %**, and the applied
> tolerance is now **≤ 10 % of flippable residues may differ**. See
> `ref/research/tolerance_benchmark_round6.md`.
>
> **H-atom count: identical (Δ = 0) for protein-only models.** When non-water hetero components are
> present the two distributions' het dictionaries differ and the count diverges by up to **3.96 %**,
> so the comparison is **void unless both builders use the same het dictionary**. This replaces the
> ± 0.1 % from PR #28, which was measured on one builder in two conventions rather than on the two
> builders the tolerance names.

## Scope limits

- One implementation, run twice, so this measures redistribution integrity rather than method
  agreement. That *is* the finding, but it means no cross-tool flip tolerance has been established.
- Deposited models are flip-optimised before deposition, so the 634 residues include few genuinely
  ambiguous cases. A perturbed or freshly-built model set would exercise the decision boundary much
  harder.
- 6 residues appeared in only one builder's records, in 3 ligand-bearing models (30TW, 24MR, 28SV).
  This is the same het-dictionary difference: the distributions build different numbers of hydrogens
  on hetero groups, which changes which nearby residues get a `USER  MOD` record. It is also where
  the "56 vs 54 flipped" difference comes from — among *shared* residues there is not one
  disagreement.
- The flip-record parser keys on `(chain, resseq, resname)` and **ignores insertion codes**, so
  models using them could mis-key. None of the 6 discrepancies traced to this, but it is untested.
- One version: reduce 4.16.250520 on both sides.
