# Standalone dictionary-loaded rerun — preregistration for #799

Dated 2026-09-28. **Result-free registration; no new measurements.** This document
must be committed and published with the reviewed instrument before execution.
Execution requires the already authorized scoped workflow and one-entry canary.

This registers only the standalone #799 execution portion of the earlier combined
799–790 planning draft. #790 remains a separate future study. Do not copy the
earlier draft's PHENIX, shared-coordinate, nuclear, or dictionary-ablation arms
into this run. Root must register the reviewed plan and pin a clean result-free
execution commit before collecting any new results.

## Question, scope, and claims permitted

Measure the explicitly dictionary-loaded standalone Reduce electron-cloud
pipeline on fresh, retained inputs for the original 10 clashscore accessions and
41 protein flip-set accessions. Determine the new standalone H counts and EC
Probe scores, and retain complete, safely parsed new standalone flip-call
evidence. Reconcile the published standalone numbers in a new dated report.

This is a new-input rerun of named entries, **not a same-input reproduction**:
the committed historical tables/JSON do not authenticate the original input
bytes. The new input may differ despite sharing an accession. Dictionary
loading is explicit now, but this study does not isolate its causal effect from
input revision, settings, or previously unrecorded execution differences.
There is no no-dictionary control, no PHENIX/reduce2 execution, no new paired
cross-tool benchmark, no #790 decomposition, and no independent quality grade.

Preserve all old raw records, EVAL/QDS files, and historical numbers. #798's
declared version match is necessary but not sufficient to validate changed
settings. No threshold is fitted, widened, certified, or applied as a grade;
#809's T14 flip-grading suspension remains in force. #846's parser omissions
must be disclosed before comparing old and new flip-call denominators.

## Prior observations disclosed before this run

This is not a blinded prediction. Saved #799 comment
`https://github.com/CultureBotAI/protstruct_review/issues/799#issuecomment-5854584332`
reports a reviewer's fresh-download bare-versus-explicit-dictionary experiment.
These are already-seen reports, not measurements performed for this plan:

| Entry | Reported bare → loaded H count | Reported bare → loaded EC Probe score |
|---|---:|---:|
| 24MR | 8327 → 8373 | 11.34 → 11.48 |
| 37AP | 1770 → 1840 | 2.26 → 2.49 |
| 28SZ | 2367 → 2406 | not reported |
| 37BG | 7999 → 8181 | not reported |
| 3G7M | 1056 → 1072 | not reported |
| 1OWJ | 1878 → 1902 | not reported |
| 12OC | 4827 → 4870 | not reported |
| 5T9A | 24569 → 24611 | not reported |

The first four H counts correspond to the historical clashscore non-water
definition; the last four correspond to the flip study's all-record H definition.
Do not mix them. The prior report makes a smaller 24MR published-reference
residual plausible, but its sign/magnitude are not independent predictions now.
The expected direction is a smaller absolute contextual residual than the old
2.27; this is a descriptive preregistered expectation, not an acceptance gate.
Contrary or unchanged values are valid results and must not cause a substitute
canary or threshold change.

For 24MR, old published PHENIX C=13.61 and standalone S=11.34 imply S−C=−2.27.
The already-seen loaded value 11.48 would imply 11.48−13.61=−2.13. Those are
subtractions from published, rounded, unmatched-input numbers; **0.14 is not an
authenticated causal dictionary contribution**. This run will not establish
that the remaining difference is caused by flips or counting.

Historical round48's 56/3105 confident conflicts compare PHENIX-distributed
Reduce with reduce2, not standalone with reduce2. The old numerator is not a
target of this standalone-only rerun. No new conflict fraction can be inferred
from the old aggregate decision summaries.

## Fixed cohorts, sequence, and stop rule

The integrated one-entry driver defines these exact cohorts; do not replace
members, pool retries, or publish only successes as a complete cohort.

1. Canary: **24MR**, clashscore mode, fresh fetch. Inspect the entire retained
   bundle, independently recount its H/Probe evidence, and require the admitted
   component inventory described below before approving any expansion. A successful exit alone is not operational acceptance.
2. Remaining clashscore entries, in order: **37AS 37AP 11AF 28SZ 37BG 12LO 30IZ
   9LLR 9PN7**. The admitted canary is the first of ten, not an extra eleventh
   observation; do not fetch/re-run 24MR merely for aggregation.
3. Flip cohort, in order: **12OC 14ZZ 15C8 1A0C 1B9B 1BDJ 1OWJ 1RH7 1TIJ 1VYJ
   1W1I 1ZY2 2I4M 2IEF 2IY0 2QIZ 2QTU 2YOL 3A01 3G7M 3MIU 3ZM5 4DYT 4FN9 4MH1
   4NJD 4Q9R 4W7P 5DZK 5MAC 5T9A 5URQ 5X6C 6ABT 6LE5 6QGY 6TPW 7D6N 7LMC
   7P4U 7PLN**. These are the 41 rows of `round48_flip_sets.json`. 12CI was a
   separate historical no-record exclusion, not a missing forty-second member.

Launch **one entry at a time**, each in an entirely new repository-local
evidence root. The parent records planned, launched, admitted, failed, and not
launched states explicitly. Stop on the first execution, evidence-integrity,
input-identity, or required-recount failure. Every retry requires a new root
and a documented reviewed reason; retain the failed attempt unchanged. Do not
combine successful fragments into a fictitious uninterrupted run. An unexpected
but valid scientific number is not an execution failure.

This fixed 51-entry descriptive rerun is not a statistically powered calibration
or a random sample of structures; it supplies no population confidence bound or
new threshold. At 900 seconds per worker, the maximum summed worker budget is
45,900 seconds (12 hours 45 minutes), plus fetch/preflight/recount/cleanup and
review time. Actual canary runtime and retained output sizes inform operational
feasibility before expansion, not selection or replacement of cohort members.
A stopped prefix cannot answer the full-cohort question and remains partial.

The driver retains raw collection separately from parsed flips. After every flip
entry, run the reviewed `recount_standalone_reduce_flips.py <entry-directory>`
and retain its JSON separately from the immutable driver bundle. Require
`counts_admitted: true`; unknown, ambiguous, rejected or zero-call outcomes stop
for review. Complete parse accounting means every emitted USER MOD record, not
every chemically flippable residue. Input annotations, including case-normalized
USER records, prevent new-invocation attribution. Do not relabel the driver's
`parsed_flip_conclusions: unavailable` as a parsed result.

## Exact launch interface and input admission

Use `scripts/bench_dictionary_loaded_reduce.py` only; its inspected SHA-256 was
`0fdc7f0193c0890058c005331941cadb283b4f30152503fc8567a95f85773d04`.
Reconfirm the reviewed integrated source at registration; a source hash is not
the result-free Git commit, which the parent must separately record.

Example **plan-only** invocation, after the preregistration exists:

```sh
.venv/bin/python -B scripts/bench_dictionary_loaded_reduce.py \
  --cohort clashscore --entry 24MR \
  --evidence-root data/coscientists/openscientist/retained_799_24MR_attempt01 \
  --preregistration ref/research/standalone_dictionary_rerun_preregistration_2026-09-28.md
```

The evidence-root parent must already exist. Only after review, required gate,
result-free commit and execution approval does the parent add `--execute`.
There is no batch or automatic fan-out flag. Flip entries use `--cohort flip`.
Every invocation owns a fresh root containing `<ENTRY>/...`.

For this registered new-input run **omit `--input`**: each entry fetches
`https://files.rcsb.org/download/<ENTRY>.pdb` once and retains requested/final URL,
actual UTC retrieval time, response headers, exact source bytes and SHA-256.
Retained-local mode is an available engineering feature, not the acquisition
mode of this preregistration. A future reuse of retained bytes requires explicit
origin metadata and a separate documented attempt; it is not a new download.

The driver requires one matching HEADER accession and one unambiguous model,
finite coordinates/occupancy/B, explicit elements, integer residue numbers,
unique atom identities, and no pre-existing H/D. Multi-model, malformed,
ambiguous, or already-hydrogenated inputs stop for review. No silent first-model
selection, H stripping, residue renumbering, or substitution. Altlocs, insertion
codes and non-water hetero components remain inventoried, not silently removed.

## Standalone method and evidence

Configured expected versions are Reduce **4.16.250520** and Probe **2.26.021123**.
The driver measures their exact version banners and records executable and
dictionary identities. Reduce's source-defined version command intentionally
exits 2; that exception applies only to the exact version command/banner.
Scientific builds still require exit 0. Flip-only mode does not invoke Probe.

Use the existing `standalone_reduce.build_hydrogens(..., nuclear=False)`:
`reduce -quiet -build -DB <dictionary> <input>`. This is flips-enabled,
electron-cloud construction. Retain the actual dictionary byte hash; do not
assume that today's dictionary is authenticated historical material.

Clashscore mode calls the unchanged standalone Probe helper, exactly
`probe -u -q -mc -het -once 'ogt33 not water' 'ogt33' <H.pdb>`.
Its legacy score is 1000 times the number of unique unordered bo/wo pairs whose
raw **min-gap** is at most −0.4, divided by all non-HOH ATOM/HETATM records.
It is not a newly standardized MolProbity score, and it does not remove every
pair also labelled a hydrogen bond. Do not change the selection, radii flags,
denominator, or parser to improve agreement. No nuclear arm is included.

The worker is launched through the reviewed #858/#865 `EntrySandbox.run_logged`,
owns its PID/PGID, and has a 900-second timeout plus TERM grace and bounded
post-escalation observation. Require the matching PGID's cleanup receipt to say
`status: group_absent` and `group_absent_verified: true` before evidence admission.
Missing cleanup metadata is not proof of termination. Diagnostic errors can raise
instead of returning a process result; such attempts stop. Requests are retained
before spawning. Keep source/preregistration snapshots, input/provenance,
measured versions, executable/dictionary hashes, all argv/status/stdout/stderr,
helper manifests, H PDB, raw USER MOD bytes, and the final hash inventory.
Worker and parent must both admit the complete consistent evidence chain
(#841); canonical and aliased temporary paths must behave identically (#844).
No PHENIX/CCP4, all-tools environment probe, old benchmark `main()` or `collect()`.

Distinguish H counts explicitly: `h_nonwater_records` for the clashscore record,
`h_all_records` for historical T14 H counts. Loaded dictionary does not prove
complete ligand hydrogenation. For each non-water hetero component, retain its
input/output atom and H counts plus the retained warning streams. Report observed
component instances and ambiguous warning attribution, without calling an instance
chemically covered or uncovered from counts. Missing warning text is not proof of
full coverage, and zero H on an ion is not automatically an error. Fatal dictionary
loading diagnostics stop the run even when Reduce exits zero. The current
driver's component-coverage field remains explicitly unavailable. After EVERY
entry, including 24MR, invoke the reviewed read-only sidecar:

```sh
.venv/bin/python -B scripts/inventory_standalone_components.py ENTRY_DIRECTORY
```

Require exit 0, `status: complete_observed_inventory`, and `bundle_admitted: true`
before proceeding. Retain its complete JSON in a new, separately dated sidecar
file outside the immutable entry bundle, with its bytes/hash and command. A
missing or refused inventory stops the run; H/Probe recount alone is insufficient.
Sidecar SHA-256 is
`dc6c7179e2f5f0a8547c321f52a919585a0e161cc6fe134dc07523383488c5b3`.
The owned-process adapter SHA-256 is
`abeeb0f2307b1ea13e4aa45057137f799a80428b0b3c5036c7b8f931bb9c50cd`.
The result-free execution commit must contain these exact reviewed driver,
parser/inventory-helper, adapter and sidecar bytes; record its full Git SHA
before the first scientific launch. The sidecar's cleanup check binds the
retained worker-start/launch, not just a self-consistent parent receipt (#869),
and uses strict regular-file readers through all admission helpers (#870).
These are observed-record and evidence-consistency checks, not chemical coverage.

## Prespecified informational comparison

For every clashscore entry, retain unrounded new standalone score S_new, its
pair count/denominator, and the non-water H count. Beside them transcribe the
old published standalone EC score S_old, PHENIX score C_old, and EC H count from
`ref/research/tolerance_benchmark_clashscore_h.md::Results` (all ten rows).
Label the old scores as rounded historical values. Compute separately:

- `S_new − S_old`: new-versus-published standalone difference;
- `S_new − C_old`: contextual residual against the old PHENIX number;
- `abs(S_new − C_old) − abs(S_old − C_old)`: contextual residual change;
- `H_new_nonwater − H_old_ec`: count change under the stated definitions.

For the 24MR expectation, a negative contextual residual change means smaller
relative to the published reference numbers; zero/positive means unchanged/
larger at that precision. Near the historical rounding boundary, label the
direction rounding-limited rather than claim high precision. Preserve actual
values regardless of expectation. Do not call these paired-input causal
effects, regrade the old envelope, or infer the missing-dictionary contribution.

For the flip cohort, report new all-record H counts, parsed emitted-mover counts,
distinct residue counts, decision counts, confidence counts and parse coverage.
Compare H totals to each old row's `n_h_standalone`. Show old
`n_flippable_standalone` and `n_flipped_standalone` only in a clearly separate
**legacy-parser summary** column. #846 means they are not equivalent denominators
to a complete new parser. Do not attribute their differences to dictionary
loading or silently repair the old JSON. Do not recompute the old 56/3105
PHENIX-Reduce/reduce2 fraction using new standalone results.

## Required new flip recount and completion boundary

Use the PR #866 parser `scripts/recount_standalone_reduce_flips.py`, observed
SHA-256 `4bc811d410b104195d6159ed17fed084de7cbbc1678ddd164f3bd490ea701dd7`.
Reconfirm that pin in the result-free execution commit. It preserves signed
residue numbers, insertion codes, altlocs, chain identity,
model identity, all documented HIS states, and Single/Set prefixes. It separates
emitted flip calls from headers and non-flip rotation records; every raw USER MOD
line is accounted for, unknown/ambiguous lines and duplicate keys stop admission.
Emitted movers are not a census of all chemically flippable residues; unadjudicated
coordinate candidates remain visible and are never inferred to be keep calls.
Reported score strings and C/X/F/K categories are preserved, not reconstructed
from rounded scores. A separate dated/hash-bound recount must not overwrite the
driver's immutable raw-only worker result. No broad driver rewrite is required.

Raw bytes and H counts suffice for retaining the new H-build observations and
for future reanalysis; they **do not suffice for a claim that flip-set analysis
has been reconciled**. To propose #799 closure, require all planned outcomes
explicit, the ten-entry EC and 41-entry flip deliverables or a separately agreed
scope adjustment, complete new parse coverage, and reviewed scientific
reconciliation. A stopped prefix is partial work. #790, independent calibration,
and any decision to resume T14 grading remain separate and uncompleted.
