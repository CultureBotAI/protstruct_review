# Backlog loop — 2026-09-27

## Scope and baseline

The user requested resolution of #799, #777, #762, #798, #760, #785, #786,
#764, #766, #765, #767 and #790, plus related review findings, with review/fix
iterations, escalation after five unsuccessful rounds, and eventual merge and
branch cleanup. This is not a declaration that the measurement tasks are done.

The complete GitHub queue and comments were read on 2026-09-27: **12 open
issues**, exactly this set, and **zero open PRs**. Local clean `main` and the
GitHub default branch both identified `f9565347e61a0a3635481d7641e2be933cb0fbdc`.
Work branched to `reduce-dictionary-integrity-2026-09-27` before edits.
The `review-open-issues` skill supplied the full-queue and evidence/disposition
discipline; GenomeExplainer-specific data paths do not apply to this repository.

## Prioritization and remaining requirements

| Priority | Issue | Observed state / next requirement |
|---|---|---|
| P1 | #799 | T05/T14 standalone Reduce omitted `-DB`; shared `run_to_file` discarded stderr. Fix execution/evidence first, then a preregistered canary and explicitly scoped remeasurement. Historical outputs remain unchanged. |
| P1 | #777 | X-ray `refine()` trusts output existence and `run_tool()` trusts a matching log. Neither binds the PHENIX build. EM sibling also has unbound caches. Prerequisite for #760; mocked cache-reuse tests can be implemented without PHENIX execution. |
| P1 | #762 | Backlog prompt says there is no CI and uses bare commands. The observed workflow actually runs Ubuntu/macOS with the locked benchmark extra; README/CLAUDE local commands omit that extra. Reconcile commands and merge/survey checks. |
| P1 | #809 | Newly found: the round-48 producer computes PHENIX-distributed Reduce versus reduce2, not the standalone pair named by current grading guidance. See below; policy correction remains pending. |
| P2 | #785 | Active recommendations still name `gemmi validate`; canonical tool registrations and dated successor recommendations need capability-specific review, not a blanket rename. |
| P2 | #786 | Round-46 preregistration explicitly sets classification agreement at least 0.99; current registry describes the load-bearing classification check without that decision boundary. Reconcile scope, provenance and governed threshold tests. |
| P2 | #764 | T03 still requires all rubric bullets to pass, including deposited R-free, while retained 1SAR REMARK3 has `FREE R VALUE : NULL`. Reflection-count/usable-set semantics also need an explicit tested definition. |
| P2 | #766 | Registry header still claims 18 fully backed rows and only two retained partial rows; its T15 basis is explicitly historical/denominator-unproven. Recount categories with a guard; include any #809 policy change. |
| P2 | #798 | Version restriction differs between clashscore guidance rows. User decision requested: pin both to benchmarked versions (recommended), broaden both, or justify distinct restrictions. No policy silently chosen. |
| P2 | #765 | Benchmark script contains exact-denominator checks, but its published T15 evidence is still historical. Needs a preregistered, canaried DSSP/Biotite rerun with complete retained evidence, not another recount. |
| P2 | #767 | Real CCP4 canary remains unverified. Mocked T13 tests establish behavior but not execution against the installed licensed tool. |
| P2 | #790 | Matched-convention residual decomposition remains a separate experiment; loading a dictionary alone does not isolate flips or counting. |
| P2, external prerequisite | #760 | Needs a second licensed PHENIX build, #777 first, and the registered cross-version experiment. Scoped ignored-inclusive installation searches found only the configured 2.0-5936 tree; this is not a machine-wide absence proof. |

## Execution fix and adversarial review trail

The #799 implementation routes standalone Reduce from both benchmark scripts
through `standalone_reduce.build_hydrogens()`. It explicitly passes the centrally
configured dictionary, retains stderr, rejects dictionary errors even with exit
zero, and binds cached output to input/binary/dictionary/argv and output/log
hashes. Old bare PDB caches are not adopted or overwritten. Failed attempts
remain diagnostic evidence; only complete successful bundles are reusable.

Review passes are separate read-only phases; findings are filed before fixes.

1. **Round 1, #807:** aliases of the same canonical model shared a cache key but
   used different output filenames. A new regression reproduced the exception
   before the fix. Output names now derive from the resolved identity; 14 focused
   tests passed. The review also exposed the pre-existing Probe failure path
   filed as #808: nonzero/empty output could become a cached zero-clash score.
2. **Round 2, #810:** after fixing #808 and passing 21 tests, review showed that
   successful but unrecognized stdout and missing atom identifiers could still
   produce scores. The parser now requires the retained Probe raw-contact shape,
   known contact types, present atom IDs and finite numeric fields. Successful
   empty output remains a legitimate zero; recognized non-clash contacts remain
   valid. A measured manifest retains unique clash pairs and the atom denominator.

Probe now executes into a fresh evidence directory rather than trusting bare
cached stdout. It retains argv, executable/input hashes, return status, raw output
and stderr hashes, and explicit parse/score status. No scientific executables have
been run for this change so far. A hermetic negative control ran the **old main
Probe function in memory** against the new failure-path test: the test failed
because no error was raised; the corrected function passes. No checkout or
restoration was used for that control.

The locked benchmark-extra gate launched during initial work exited zero, but
edits occurred while it ran; it is **not** the final pre-commit verification of
this diff. A fresh gate is required after the final review fixes.

## Scientific evidence boundaries discovered during #799

Independent JSON recount of `ref/research/data/round48_flip_sets.json`:

- 41 measured rows; the named exclusion is 12CI (no flip records).
- PHENIX-distributed Reduce versus reduce2: 3105 shared residues, 340 raw
  disagreements and 56 confident conflicts.
- PHENIX-distributed versus standalone Reduce: 3101 shared, four PHENIX-only
  and one standalone-only; two decision and two category-only differences.
  Nonidentical maps occur in 1W1I, 3MIU, 4FN9 and 5MAC.
- 31 ligand-bearing and ten protein-only models; 22 H-count differences.
  The maximum relative H-count difference is 6.779661% at 3MIU. The old 3.96%
  belongs to the older study, not this named cohort.

The producer's `a = flip_calls(phx)` is what enters every reduce2 comparison.
The historical producer commit `cc36747` makes the same choice. This is #809,
not a reason to relabel the independent 1SAR measurement records automatically.
Both PHENIX-distributed Reduce and reduce2 are currently classified `cctbx` in
the catalog, notwithstanding their distinct underlying implementations. A
producer-label correction alone cannot create non-cctbx coverage or validate
the unmeasured standalone criterion. The recommended policy decision is to
retain the historical comparison informationally and suspend its asserted
support for the standalone grading band until matched independent evidence
exists; no such policy change has yet been made in this branch.

The installed dictionary files are byte-identical (66,390,773 bytes;
SHA-256 `0da5ec87a909bb0eb8df480c42ce74bef92e710ff939764f960a62b0d9b38ab9`).
Recounting saved reviewer outputs, without re-execution, gives:

| Saved case | No dictionary | Explicit dictionary |
|---|---:|---:|
| 24MR H atoms | 8327 | 8373 |
| 24MR clash pairs / atoms | 197 / 17377 | 200 / 17423 |
| 37AP H atoms | 1770 | 1840 |
| 37AP clash pairs / atoms | 8 / 3539 | 9 / 3609 |

These are **local saved-output recounts**, not new committed benchmark results.
They support the issue's disclosed canary expectations, so a new preregistration
must not call those predictions blind. The 24MR scores are 11.3368245 and
11.4790794; a comparison with the historical PHENIX value 13.61 remains a
historical-reference comparison, not proof of a matched fresh two-tool run.

The committed flip JSON does not retain complete per-residue reduce2 call maps
or original input digests. Ignored-inclusive repository and targeted historical
cache searches did not locate the complete original builds/reports; they did
not prove global absence. A standalone rerun cannot reconstruct those missing
calls from aggregate counts. New coordinate inputs must be pinned, and any
comparison with old PHENIX aggregates must disclose unverified input equality.
Original raw evidence or a newly authorized matched run is needed for a complete
new standalone-versus-reduce2 benchmark. #799 therefore remains open beyond the
execution fix; neither a green gate nor a code merge would complete it.
