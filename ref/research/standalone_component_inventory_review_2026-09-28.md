# Standalone component inventory: result-free engineering review, 2026-09-28

This is the bounded #799 postprocessor for **observed coordinate-record counts**,
not a dictionary-coverage assay or new scientific execution. The driver admission
helpers and PR866 checked-inventory utility gain an optional byte-reader argument
for #870; their default behavior, counting rules, raw-only flip result and parser
are unchanged. Historical numbers and grading rules are untouched. #790 remains
a separate future causal study and T14 grading remains suspended.

## Interface and boundary

`python scripts/inventory_standalone_components.py <existing-entry-directory>`
prints one JSON document to stdout after successful admission. It writes no
files and invokes no executable, version command, network or flip parser. The
caller should retain this JSON separately from the immutable input bundle, with
its own dated provenance. Both clashscore and flip driver modes are supported;
zero emitted flip calls do not prevent an observed component inventory.

The CLI requires a complete one-entry parent and worker, successful non-timeout
process outcome, and a matching verified-absent owned-PGID cleanup receipt from
the #858/#865 boundary. #869 binds that receipt to the retained worker-start PID
and PGID, the parent's leader PID and PGID, and the exact launch request. All
identifiers must be positive integers, not booleans; all five must agree. The
parent must literally record `start_new_session: true`, `timed_out: false`,
integer return code zero and `group_absent_verified: true`. Its `arguments` must
equal the retained launch argv: the recorded Python executable (allowing its
original executable alias), `-B`, the exact retained driver source path,
`--worker`, and this entry's request path, with the driver's prescribed timeout.
Missing historical cleanup metadata is not upgraded to proof.
The original parent and worker inventories must agree; the existing
driver's `admit_evidence()` validates the helper/input/output chain before and
after interpretation. The PR866 `checked_inventory()` utility is reused solely
for retained-byte checks, without parsing flip calls.

#870 routes every sidecar-controlled file read, including nested driver and
inventory-helper reads, through one explicit regular-file reader. Descriptor-
relative directory traversal refuses inner symlinks; the final open is no-follow
and nonblocking, with `fstat` regular-file admission before reading. Reads are
bounded to the observed file size plus one byte and reject size/time changes.
FIFOs, devices, directories and artifact symlinks cannot become retained input.
The caller's entry-directory alias is still canonicalized once; aliases inside
that entry and original artifact/source paths are not followed. This is POSIX
local-file admission, not a general hostile-filesystem availability guarantee.
The injected callable leaves default driver/recount callers unchanged; no global
monkeypatch or duplicate evidence-admission implementation is used.

Every interpreted input, H output and diagnostic stream is checked against its
original pins, not a newly generated replacement inventory. The parent JSON and
the running sidecar/driver/inventory-helper source files are also checked for
change during interpretation. Output evidence identifies the exact input/output,
parent, retained inventory and postprocessor source hashes.

Original input, executable, dictionary, preregistration and execution-source
paths must still exist with unchanged bytes, as required by the driver. This is
local consistency and mutation detection, not malicious-manifest authentication,
historical execution attestation, or a portable relocated-bundle verifier. Freeze
the reviewed execution checkout and preserve the original evidence paths.

## Counts and identity

For each file, totals count literal ATOM/HETATM records, partitioned by record
type and exact residue name `HOH` versus non-HOH. H and D are separate explicit
element-column counts; atom names do not infer elements. DOD is not silently
included in the exact-HOH water category. No occupancy weighting, chemical atom
deduplication or alternate-conformer expansion is performed. Global atom/H
totals must reproduce the driver's retained inventory definition.

Reported component instances are the union of exact non-HOH residue identities
having at least one HETATM record in either file. Both ATOM and HETATM records at
each selected identity remain separately visible. The identity retains model
ordinal, raw MODEL label (or null when implicit), the two-column chain field,
signed decimal residue number, insertion code and raw residue name. Within each
instance, separate literal altloc counts keep common blank atoms exactly once.
The existing driver's narrow PDB admission still applies; this is not a new
SEGID, hybrid-36, multiple-model or ambiguous-input compatibility layer.

Input-only/output-only means that **the exact recorded identity** occurs in only
one file, not that chemistry appeared or disappeared. Changed MODEL labels or
residue identities are not silently mapped together. Protein-only inputs with
no selected hetero instances remain valid observed inventories. Zero H on an ion
is a number, not a failure. Every instance and the overall result retain
`chemical_coverage: unassessed` regardless of the counts.

## Diagnostics without invented causes

All retained helper stderr copies, captured version-stderr fields, and the
parent-inventoried combined worker log are surfaced with original path, complete
file hash, byte count and an unassigned text view. Version stderr identifies its
field inside the pinned JSON. UTF-8 replacement decoding is only for display;
the original bytes and their hashes remain authoritative. Duplicate retained
stderr copies are not counted as distinct warnings.

No message classifier or residue attribution is attempted. A warning need not
identify an exact component instance, and silence cannot establish that every
ligand received chemically complete hydrogenation. Dictionary presence, loaded
dictionary diagnostics, observed H additions, and chemical completeness remain
different claims. The driver's fatal-diagnostic handling is unchanged.

## Hermetic verification

Nineteen focused sidecar tests and 49 existing driver/recount tests pass with
candidate-first imports. Fixtures cover full chain/signed residue/insertion
identity, raw model-label changes, repeated component names, record-type changes,
blank and named altlocs, exact HOH versus DOD, H versus D and misleading atom
names, input-only/output-only instances, zero-H ions and protein-only models.
Malformed or duplicate identities fail; global counts reconcile with the driver.

Both cohort modes exercise complete synthetic public driver bundles through the
sidecar CLI, with subprocesses, network, scientific entrypoints and flip parsing
denied. Unknown synthetic USER MOD text therefore cannot accidentally turn this
into a flip-analysis gate. Tests cover failed/timeout/missing-cleanup parents,
missing pins, changed original source/tool/preregistration/evidence, path escape,
alias equivalence, mid-interpretation byte changes and zero bundle mutation.
New public CLI regressions reject contradictory or coherently repinned launch
and worker receipts, integer/boolean lookalikes, and missing isolated-session
proof. Twenty-seven non-regular-file cases (nine retained/original paths, each
as FIFO, symlink and directory) use timeout-bounded ordinary Python children;
those children deny tool execution and network. Source-file reads, inner-directory
symlinks, `/dev/null`, and mid-interpretation substitutions are also checked.
A reader-injection regression forbids direct Path reads throughout both reused
admission helpers, so a missed nested reader call cannot silently pass.

Scratch-only controls remove original inventory verification, the final
admission boundary or the cleanup-receipt requirement, remove worker/launch
binding (including coherently repinned receipts), substitute plain Path reads,
or double-count blank altloc records. They produce respectively 2, 5, 1, 11, 9,
2 and 1 intended assertion failures, with no setup errors. The exact reviewed
pre-fix sidecar, tests, helper sources, patch and reproducer are retained in
scratch `reviewed-original/`; they reproduce both filed defects, rather than
inferring the old failure from a broken API fixture.
Repository-configured Ruff correctness checks pass. No scientific executable,
network fetch, cohort run, Git operation or
repository-wide gate was performed for this proposal. Independent review, the
integration gate, CI and a registered result-free execution commit remain
prerequisites to #799 execution.

The #799 result-free preregistration must refresh the driver, recount-helper and
sidecar hashes after integration. These helper-signature changes are prospective
engineering dependencies, not grounds to rewrite old source pins or results.
