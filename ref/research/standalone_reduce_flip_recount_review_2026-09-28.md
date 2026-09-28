# Standalone Reduce flip recount: engineering review, 2026-09-28

This is a result-free parser and evidence-admission change for #846, with the
independently reproduced defects #853, #854 and #861 addressed before integration.
No scientific executable, network fetch, historical rerun, cohort aggregation,
new QDS, conflict rate, threshold or T14 grade is part of this change.

## What the parser admits

`scripts/recount_standalone_reduce_flips.py` reads one existing complete
dictionary-explicit driver entry. It verifies the original parent and worker
inventories, reuses the driver's read-only evidence checks, and binds the exact
H-PDB, raw USER MOD stream and retained input bytes before interpretation and
again afterward. Its stdout JSON is separate informational evidence; it does
not rewrite the driver, the retained bundle, or the driver's raw-only claim.

Full mover identity retains model ordinal, the two-column chain field, signed
decimal residue number, insertion code, residue name and alternate conformer.
All ten source-defined ASN/GLN/HIS orientations are recognized; Single and Set
prefixes, known metadata and non-flip rotations are explicitly classified.
Unknown records, unsupported identities, duplicate movers and ambiguous
coordinate bindings refuse admission. Blank common atoms can support a named
conformer but do not create a separate blank conformer.

Counts cover emitted eligible movers, not every chemically flippable residue.
Unadjudicated coordinate candidates remain visible and are never inferred to be
keep calls. Rejected and zero-call counts are diagnostic only. This one-sided
parser cannot establish a standalone-versus-reduce2 conflict denominator.

## #853: inherited annotations cannot become new observations

The installed upstream source retains input USER records: `reduce_src/reduce.cpp`
`inputRecords()` leaves them in the default branch and appends active records
(lines 460–465); `outputRecords()` prints valid retained records (lines 344–347).
Thus an output hash, matching raw stream and zero process status do not establish
that a flip annotation was generated in the retained invocation.

The reviewed candidate admitted a fully hash-consistent mocked bundle containing
one input flip annotation and no newly generated calls. Its public recount CLI
returned success with one admitted flipped mover. The correction refuses any
retained input line matching `(?i:USER)\s+MOD\b`, including known metadata,
alternate spacing and case-normalized record names. It does not silently strip,
subtract or assign provenance to
inherited annotations. Such an input needs a separately reviewed preparation or
attribution protocol; existing records remain untouched.

The pure two-argument `recount(h_bytes, raw_bytes)` function now reports successful
grammar-only parsing as `output_only_unattributed`, with `counts_admitted: false`.
Supplying input bytes permits only an annotation-origin check in that pure
function; authenticated bundle admission remains the responsibility of
`recount_bundle()`. The returned input digest identifies the checked bytes.

## #854: category and clash flags must agree

`reduce_src/FlipMemo.cpp:1035–1053` selects category C if and only if both
original-state and flipped-state clash flags are true, and emits those flags
alongside the scores. The reviewed candidate admitted C with neither flag and F
with both flags through the public bundle CLI. The correction rejects these
contradictions and all equivalent combinations.

C and X remain independent of orientation: either may accompany a flipped or
unflipped mover. The parser does not reconstruct confidence from rounded printed
scores. Exact clash-flag consistency is distinct from such an unsafe numerical
reclassification. Existing F/K direction consistency is retained.

## Offline verification and limits

The focused suite has 23 tests covering grammar, identities, coverage, original
evidence pins, immutability, public-CLI refusal and input mutation during
interpretation. Three in-memory guard-removal controls produce respectively two,
two and one assertion failures, with no setup/import errors: inherited-input
admission, category/clash consistency and output-only attribution. No production
file is mutated by these controls. Ruff correctness checks pass.

Static Python string literals from upstream `test/test_reduce.py` are syntax
examples, not new observations or evidence that the installed executable was
built from those exact sources. Source anchors include `FlipMemo.cpp:206–216`
and `1031–1053`, `AtomPositions.cpp:385–417` and `1293–1328`, and
`CliqueList.cpp:63–100`. The independently reviewed pre-fix reproducer and
candidate are preserved separately from the corrected overlay.

Actual bundle admission still requires unchanged original source, executable,
dictionary, preregistration and retained-input paths, as required by the existing
driver. This is not a relocated/offline authentication protocol, malicious
manifest-forgery detector, new scientific execution or independent cross-tool
validation. SEGID, hybrid-36 and ambiguous conformer cases remain unsupported.
The repository-wide gate and CI remain integration requirements; focused tests
and Ruff do not substitute for them.

## Legacy-parser annotation

The legacy parser's module/function documentation and the round48 report now
carry the following scope limitation; the historical algorithm and totals are
not changed:

> Legacy standalone parsing omits source-defined HIS and small-Set records and
> cannot represent signed, insertion-code and alternate-conformer identities
> completely; duplicate short keys overwrite. Retained totals describe that
> parser's output, not an authenticated complete population. New standalone
> recounts must not be joined to the legacy reduce2 stream without a separately
> reviewed paired identity and coverage contract. Historical numbers remain
> immutable; a new dated recount requires the exact retained underlying bytes.

The new `legacy_comparison_keys()` adapter therefore refuses every projection to
the old three-part identity. No one-sided regex repair or historical total
correction is included.

## Integration finding #860

The first full gate rejected the round48 annotation because the descriptive
evidence ledger still pinned its previous complete file. Review confirmed the
diff consists solely of the dated parser-scope warning and this note's link;
historical text, values and the producer correction are otherwise unchanged.
Only that evidence fingerprint is refreshed. Ledger policy, evidence states,
component counts and the fingerprint guard are unchanged. Matching this reviewed
annotation's hash is not new scientific validation.

## Integration finding #861

An independent review reproduced an input-origin bypass after Reduce's record
name normalization. `libpdb/pdb_type.cpp:303–305,518–528` uppercases the first four
characters for USER classification; `libpdb/write_format.i:55` serializes literal
uppercase USER. The MOD body remains case-preserved. A synthetic command doing
only that normalization admitted an inherited `uSeR  MOD` or `user  MOD` call as
new, while the uppercase control was refused. No new flip decision was generated.

The input check now normalizes only the USER name. Public-bundle regressions
cover both spellings, unchanged evidence, empty success output and the refusal
message. Restoring the previous case-sensitive guard makes both cases fail by
assertion, not setup error. This is a future-admission correction, not evidence
of a new scientific run or damage to historical retained results.
