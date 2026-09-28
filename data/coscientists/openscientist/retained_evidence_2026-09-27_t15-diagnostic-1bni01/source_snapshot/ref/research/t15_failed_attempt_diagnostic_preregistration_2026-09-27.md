# T15 rejected-pair diagnostic amendment — 2026-09-27

Result-free registration for #829, following the stopped #765 rerun in PR #831.
This is one diagnostic invocation on the **same retained 1BNI bytes**, not a
replacement cohort, completed benchmark, independent quality grade, or permission
to relax the exact-key denominator rule. The earlier two execution roots remain
unchanged. The registration and reviewed instrument must be committed before
launch; the exact execution commit and source digests are retained in its request.

## Known evidence and prediction

The registered original run `4a150693dd64b79c38e9e57561667215994a35a1` stopped its
second attempt after eight admitted entries. Its 1BNI log says DSSP-only=0 and
Biotite-only=1, but the old wrapper did not retain the assignment streams or raw
DSSP on that failure. Therefore it cannot identify the asymmetric residue.

The retained original PDB has 324 ATOM protein residues (108 per chain A/B/C).
The complete source key domain is A/B/C, residue numbers 3 through 110 inclusive,
all with blank insertion codes. The predicted Biotite domain is all 324 keys;
the predicted DSSP domain is those same keys except C/3/blank (323 shared keys).
Common omissions do not confirm the prediction merely because the asymmetric
set still names C3. These domains are a result-free source-derived prediction,
not newly observed assignment counts.
Read-only input inspection found VAL C3 has CA/C/O but lacks backbone N; its
REMARK 470 also identifies that missing atom. **Hypothesis, not a finding:** the
new instrument will reproduce the unequal-key rejection, with exactly one
Biotite-only key C/3/blank insertion code. The missing N may explain that outcome,
but matching the predicted key alone is not a controlled causal intervention.
Do not fill the atom, remove that residue/chain, take a surviving intersection,
or rerun alternatives to obtain agreement. Any other outcome is retained and
reported as a prediction failure or an unresolved difference.

## Frozen input and execution boundary

- Input: `data/coscientists/openscientist/retained_evidence_2026-09-27_canaries02/t15_cache/1bni.pdb`.
- Exact SHA-256: `e7a0612d97d3b9f52f2ab6efcaa94b8baa410c37e30107992e4e2564b5385796`;
  263,574 bytes. PR #831 must have delivered these bytes before this invocation.
- No download, input preparation, model selection, atom repair or cohort expansion.
- Invoke only `scripts/t15_ss_agreement.py` on this file, with explicit eval ID
  `EVAL_T15_1BNI_DENOMINATOR_DIAGNOSTIC`, subject
  `retained:1BNI:sha256:e7a0612d97d3b9f52f2ab6efcaa94b8baa410c37e30107992e4e2564b5385796`,
  and a new repository-local `--evidence-out` JSON path. It is a diagnostic bundle,
  not a new EvaluationRun or QDS publication. Do not invoke the cohort collector.
- Use the locked Python 3.12 benchmark environment. Expected measured versions
  are Gemmi 0.7.5, DSSP 4.6.1 and Biotite 1.7.1, as in the original attempt.
  Record actual versions; a difference prevents claiming an instrument-only replay.
- The one entry runs inside a recorded `EntrySandbox.run_logged` owned process
  group with a 900-second outer timeout. Retain the actual argv, PID/PGID, return
  code, timeout/termination status and timestamps. Scientific subprocesses inherit
  that group. No name-based process termination or licensed PHENIX/CCP4 work.
- Use a wholly new root under `data/coscientists/openscientist/`, with a unique
  diagnostic suffix, atomically reserved before execution. Reject an existing
  destination or symlink. Every retry needs a new root and a recorded reason;
  this protocol authorizes no automatic retry.

Retain the invocation request before spawning, the exact launch helper, the
registered plan and copies/digests of `t15_ss_agreement.py`, `toolchain.py`,
`entry_sandbox.py` and `uv.lock`. Record Python/package versions and the resolved
Gemmi/DSSP executable identities without dumping unrelated environment secrets.
Preserve separate wrapper stdout/stderr, available failure diagnostics, and a
complete final file/size/hash inventory. Check input and source hashes before
and after execution. Execution is stopped if these identities drift.

## Expected failure and evidence acceptance

The expected wrapper exit is nonzero with empty stdout and a typed
`protstruct-review-t15-failed-attempt-v1` JSON. That diagnostic contains the exact
source, normalized input and raw DSSP bytes with hashes, measured versions,
captured normalization/DSSP argv/status/text, both complete collapsed H/E/C
assignment streams, and separate insertion-code-preserving shared/asymmetric
keys and counts. The failed bundle must have `measurements_emitted: false` and
must contain no agreement/content scalar or grading metadata.

Independently decode/re-hash the bytes and parse the raw DSSP fixed columns;
reconstruct every retained DSSP key/state and set difference from the two streams.
Verify the normalized single-model atom identities, coordinates, occupancy,
B values and elements against the frozen source; documentary records and atom
serials are not atom identity. Require assignment keys to belong to the source
protein domain. A coherent subset remains diagnostic evidence but fails the
complete-domain prediction; unrelated keys or changed normalization invalidate
retention admission. Validate the complete DSSP 4.6.1 row grammar, declared total,
unique serials/keys and supported nine-state alphabet before collapsing states.
Require the complete pinned table header, including all coordinate labels.
Bind each raw residue's amino-acid identity and CA triplet to the same CA
conformer in the normalized source. The 20 standard amino-acid mappings are
explicit; lowercase DSSP disulfide labels map to cysteine. Unsupported source
identities fail closed. DSSP prints CA values to one decimal place, so each
reported coordinate must lie within one half print step (0.05 Å, inclusive for
ties) of the source coordinate. This is representation rounding, not a new
scientific agreement threshold. Matching keys alone cannot authenticate raw
output for the input. These consistency checks do not independently recompute
DSSP's secondary-structure algorithm or prove the origin of fabricated evidence.
P/T/S/space remain C; no scientific state definition is changed. Malformed raw
output fails before publication of any completed-pair failure bundle.
Compare the predicted asymmetric key to the observed one. A version-exact P-SEA
replay may independently reconstruct its recorded stream from the unchanged
source after the canary has stopped; this is disclosed as same-implementation
replay, not an independent algorithm or a second cohort measurement.

If admission unexpectedly succeeds, retain its outputs and stop: do not call that
the historical missing evidence recovered or continue the cohort. Earlier-phase
failure, missing bundle, nonempty measurement stdout on rejection, timeout,
changed source, unverified version or inconsistent replay also stops work and
remains explicit evidence of an unresolved attempt. Do not replace a failed
output with a fabricated successful measurement.

## Decision boundary

Successful retention/recount establishes only that the new failure instrument
works on this known failure. It cannot retroactively authenticate the discarded
old streams, establish that missing N caused the mismatch, calibrate a threshold,
or finish #765. Resuming or changing the 16-entry protocol requires a separately
reviewed decision after this diagnostic. #829's retention requirement and #839's
destination-alias correction can be accepted through implementation, hermetic
negative controls and this scoped evidence audit; no model-quality claim follows.

## Registered single-entry launcher

Commit `scripts/run_t15_failed_attempt_diagnostic.py` and its hermetic test with
this amendment and the reviewed failure-retention instrument, after PR #831 has
delivered the frozen input. Use the exact resulting reviewed, published **40-character
registration commit**; it is a runtime argument, not the older cohort commit
`4a150693dd64b79c38e9e57561667215994a35a1`. The helper rejects that old registration,
a different HEAD, changed registered source bytes, changed input bytes, an
unregistered helper, an existing output root, or any output-path symlink component.

The default is a read-only plan. From the registered repository's locked Python
3.12 benchmark environment:

```bash
.venv/bin/python -B scripts/run_t15_failed_attempt_diagnostic.py \
  --repo . --registration-commit FULL_REVIEWED_40_CHARACTER_COMMIT --run-id 1bni01
```

After reviewing that exact plan, append `--execute` to launch the **one** authorized
entry. The helper creates only a wholly new
`data/coscientists/openscientist/retained_evidence_2026-09-27_t15-diagnostic-<run-id>/`.
It never downloads inputs, installs dependencies, invokes the cohort collector,
selects another model, retries or proceeds to another entry.

The owned `EntrySandbox.run_logged` process execs the registered wrapper after
opening exclusive, separate `wrapper.stdout` and `wrapper.stderr` files. Exec
preserves its recorded PID/PGID; the wrapper and its scientific children remain
in the single owned group under the 900-second timeout. The request, actual
outer argv, wrapper argv, request digest, worker PID/PGID and timestamps are
retained separately. The parent retains timeout/termination/exit information even
when the expected failed bundle is absent.

Only Gemmi and DSSP executables are resolved; no general tool report or
PHENIX/CCP4 version probe is invoked. Their resolved paths, byte sizes and SHA-256
identities are pinned before launch, forced through the wrapper's configured
`PROTSTRUCT_GEMMI`/`PROTSTRUCT_DSSP` overrides, and checked afterwards. Actual
scientific version text must be Gemmi 0.7.5, DSSP 4.6.1 and Biotite 1.7.1 for
instrument-only comparison. Current executable hashes do not retroactively
authenticate the older run's executable bytes. Python/package metadata is checked
against the retained lock, including the exact current Biotite/Gemmi Python pins.
Preflight pins the regular installed METADATA files by path, size and digest,
with unambiguous Name/Version fields. After execution, reread only those pinned
files; do not rediscover distributions or follow changed metadata aliases.
The supported lock shape requires a nonempty package array with string
name/version fields. A post-worker malformed lock is retained as failed
environment verification alongside the original identity drift, not an
uncaught parse/shape exception that loses the terminal record (#868).

Retain byte-exact source and input snapshots. Check the registered input and
source identities immediately before execution and after it, and retain observed
post-execution identities. Check the retained snapshot copies against those same
registered pins, both before acceptance and in the final inventory. A changed or
missing copy invalidates diagnostic retention even when the live originals are
unchanged; keep the failed result and inventory without repairing the evidence.
Bind the exact bundle, stdout, stderr, launch-request and worker-context bytes
consumed by admission to their final inventory hashes before publishing the
outcome. A post-audit mutation or removal invalidates admission; do not publish an
accepted result and overwrite it later to match changed evidence.
Freeze the exact serialized request and owned-launch record in parent memory
before writing/spawning. Require the retained request, actual argv, owned-launch
record and worker-context digest to match those original pins, not just each other.
The final file/size/SHA-256 manifest includes the
request, worker context, separate streams, bundle (when present), snapshots and
launch result. Its one declared exclusion is the final manifest itself, whose
self-digest cannot be included.
Symlinks and unreadable/non-file evidence objects are not followed or repaired:
retain explicit per-path errors, mark the inventory incomplete and the diagnostic
invalid, and publish a stopped terminal result where the destination remains
writable. Error entries have no substitute hash; the manifest separately counts
hashed files and inventory entries. A wholly unwritable destination cannot promise
an on-disk terminal record and must remain an explicit external execution error.
Every post-worker identity/admission read, including lock and package metadata,
uses descriptor-relative, no-follow regular-file admission before reading.
Nonblocking open and a second descriptor check reject an ordinary FIFO/file-swap
without waiting for a producer. This is not a deadline for arbitrary regular-file
I/O or a defense against hostile kernel/filesystem behavior.

For this instrument, the expected wrapper exit is specifically **1**, not an
arbitrary nonzero status. Launcher exit 0 means only that exit 1, empty wrapper
stdout, the typed failed bundle, version/identity checks, raw-DSSP replay and the
registered asymmetric-key prediction all matched. It is not scientific admission
or a quality grade. A consistent retained bundle with a different asymmetric key
is explicitly a failed prediction; unexpected admission, timeout, missing or
inconsistent evidence, changed identities and version mismatches all produce a
stopped diagnostic with launcher exit 1. No outcome authorizes cohort continuation.

## Independent escalation amendment (2026-09-28; still result-free)

Six defective review rounds triggered the installed external Codex review. Its
read-only controls found coordinated request/context mutation (#856), incomplete
whole-input coverage (#857), surviving children after wrapper exit (#858), and
loss of terminal records on inventory errors (#859), besides raw-state admission
(#852). Root independently reproduced all four new findings before correction.
Related internal review found the zero-shared prediction error (#851) and malformed
row/duplicate admission (#855). No scientific invocation had occurred under this
registration. The corrections strengthen evidence acceptance; they do not repair
the old missing raw outputs, confirm missing-N causality or permit cohort resumption.

Before execution the reviewed owned-process adapter must clean and verify the
recorded group on every wrapper exit, not only timeout/exception. If group absence
is unresolved, evidence audit cannot report clean completion. Preserve its cleanup
status/error and the original return status. Deliberately detached new process
groups are outside this POSIX-group mechanism; this diagnostic does not authorize
tools to daemonize. #858 must be delivered and pinned before this run.
The launcher requires the returned cleanup record to state `group_absent`,
with `group_absent_verified: true` and the exact owned PGID. Missing historical
or mocked cleanup fields cannot certify a new invocation. A propagated exception
retains its cleanup record and notes in the terminal outcome, including cleanup
or diagnostic-log failures (#865).

A subsequent read-only adversarial round found blocking post-worker reads (#862),
raw DSSP geometry/amino-acid fields unbound to the source (#863), and a truncated
table header accepted by the independent launcher parser (#864). Each was
independently reproduced and filed before correction. The new public-entrypoint
negative controls reject those cases and retain a stopped result where writable;
the full-header and raw/source checks replay the eight already saved successful
raw outputs against their retained normalized and original coordinates.
That replay is an offline instrument check, not a new scientific invocation or
a completed 1BNI diagnostic. The frozen 1BNI prediction above remains untested
under this registration, and the old missing raw failure evidence remains absent.
The adjacent malformed-lock terminal-loss defect (#868) was also independently
reproduced and filed before correction. Hermetic public-entrypoint controls cover
missing and wrong-shaped package tables; they do not execute any scientific tool.
