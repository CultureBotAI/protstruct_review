# Preregistration: T13 operational canary and T15 denominator rerun

This commit contains no new execution results. Protocol date: 2026-09-27. Engineering baseline:
main `fbacb660d59802545df54b14489a43fe43e9bfce` (PR #823). Issues: #767 and #765.
Execution is opt-in and user-authorized. No registry threshold is changed by this preregistration.

## Prior information and bounded claims

The historical T13 logs and T15 report have already been inspected. This is not a blind prediction
or an independent replication of previously unseen data. The historical T15 report lists 16 model
agreements between 0.6792 and 0.8497, but does not prove today's exact per-assigner denominator.
Freshly fetched coordinates are new retained inputs, not assumed identical to those historical bytes.

T13 tests the wrapper's installed-tool integration, not model quality or cross-tool agreement.
T15 tests exact denominator preservation and the previously stated provisional expectation in the
same named cohort. It cannot validate the sparse bad-end controls or a model-quality threshold.

## Common execution controls

- Use the locked Python 3.12 benchmark-extra environment and the unchanged public script entry
  points. Keep one fresh repository-local evidence destination inside the isolated worktree.
- Launch each entry through `scripts/entry_sandbox.py::EntrySandbox.run_logged` with a new
  per-entry directory, retained combined launcher output, argv, return code, PID/PGID and timeout
  result. Enforce a 15-minute outer limit per entry; terminate only that recorded process group.
- Inspect one entry end to end before any batch. No successful exit alone admits a result.
- Retain original input hashes and every evidence file/log actually produced; do not overwrite old evidence or repair a
  failure in place. Any instrument change requires a filed issue, reviewed fix and new destination.
- A missing executable, fetch error, unmatched denominator, malformed evidence or timeout stops the
  affected protocol. Report the failure; do not replace a failed member or silently shrink the cohort.
- Version probes may run through the shared configuration; record actual measured tool versions.
  Configured version constants and executable filenames alone do not authenticate installations.

## T13: one retained merged-amplitude MTZ (#767)

Input: `data/coscientists/openscientist/retained_evidence_2026-09-23/data/1sar.mtz`.
SHA-256: `f36d5fe685a3e524e8809d17d19ce12073acdf339eba2cfd3b0347a818850ab2`.
Invoke `scripts/t13_data_quality.py` with explicit `--columns F-obs,SIGF-obs`,
`--eval-id EVAL_T13_OPERATIONAL_CANARY`, and a new worktree-local `--logdir`.
Use the configured CCP4 installation; this protocol does not install or license software.

Expectation, based on the retained input and prior logs: aimless rejects merged-only data and the
wrapper then runs ctruncate successfully. The operational acceptance criteria are:

1. The input hash is identical before and after; the emitted dataset subject embeds that hash.
2. Both attempted-command logs exist and are nonempty. The ctruncate output MTZ exists, is nonempty,
   and can be read with the installed Gemmi library; requested amplitude column names are recorded.
3. All emitted evidence refs resolve to the exact retained logs. YAML rows are parseable and use
   dataset scope, explicit column selection and informational status, without grading criteria.
4. Aimless failure is represented as the expected limitation, not a successful unmerged-data result.
   Check each available/unavailable flag against fresh log text; no missing/truncated evidence may
   become a negative scientific flag. A synthetic truncated-log parser check is not new tool execution.
5. A repeat targeting the same output directory must refuse before tool execution and preserve all
   retained bytes. This tests overwrite refusal, not repeatability of the scientific calculation.

No numerical T13 diagnostic will be promoted into a new published scientific finding without the
normal EvaluationRun/QDS path. The operational report may state whether the wrapper ran, retained
evidence and preserved unavailable states. No unmerged-intensity coverage is claimed by this input.

## T15: fixed 16-entry exact-denominator cohort (#765)

Use `scripts/bench_t15_ss_agreement.py` with explicit `--cache`, repository-local `--evidence-dir`
and `--json`. Canary **1UBQ** first. The fixed cohort is:

`1UBQ 1LYZ 1LZ1 2PTN 7RSA 1CA2 1MBN 3EST 1BNI 2CI2 9PAP 1HEW 4PTI 1CRN 2LYZ 1TIM`.

After inspecting the canary, execute the same script/launcher on each of the remaining 15 entries,
**one CLI invocation with exactly one ID at a time**, using the same fresh cache/evidence root.
Inspect the per-entry outcome and evidence before launching the next; stop immediately if either
fails. Do not use a multi-ID invocation: the unchanged collector continues after skipped members
and can return success when only a subset succeeds (#828). Retain 1UBQ's original canary evidence
once; do not count it twice.
Construct the final 16-entry record from those per-entry records with a deterministic union that
rejects missing or duplicate IDs. Preserve skipped records and every available launcher/runner log
even if the protocol stops.

**Failure-evidence limit (#829):** the unchanged T15 wrapper deletes temporary normalized/raw-DSSP
files and publishes its bundle only after denominator admission. A failed entry may therefore lack
raw assignment evidence. Retain all available diagnostics, explicitly report unavailable raw or
normalized evidence, and stop to file/review any needed instrument fix before retrying in a new
destination. Do not describe such a failure as independently replayable denominator evidence.

Acceptance per entry requires the nonempty retained evidence JSON, normalized coordinate bytes,
raw DSSP output, actual tool-version metadata and both full residue-key assignment streams. Recount
the streams independently: key sets must match exactly (including insertion codes),
`n_dssp == n_biotite == n_scored`, `n_dropped == 0`, and the agreement numerator and DSSP H+E content
must equal the retained assignments. Validate every bound hash and the runner's reported values.

Registered prediction: all 16 entries satisfy exact-key admission, have DSSP H+E content at least
the existing provisional 0.20 precondition, and agreement at least the provisional 0.65 expectation.
This is a cohort-specific prediction motivated by the already-read historical data, not a prospective
validation in a new cohort. Count arithmetic uses raw integers, not rounded table values.

Decision rule: any qualified entry below 0.65 falsifies this cohort-wide expectation; do not lower
the floor post hoc. Any denominator/evidence failure leaves the complete-cohort calibration
unestablished. If all 16 qualify and meet the prediction, report that limited exact-denominator
support and ask for a separately reviewed policy decision before making a gradeable registry rule.
In all outcomes, keep both oracle-pair measurements informational, keep the 0.20 content condition
provisional, and leave the separate agent-versus-DSSP comparison unmeasured. No claim of general
model-quality discrimination, new bad-end controls or STRIDE corroboration follows from this run.

## Completion and review

Commit this protocol after the hermetic gate and before any canary result. Retain the preregistration
commit/PR lineage, then review the actual artifacts and failure paths, file any discovered defects
before fixes, and publish only the outcomes the evidence supports. #767 can close on demonstrated
operational acceptance; #765 requires the retained exact-denominator cohort or a documented failed
attempt and explicit disposition of the remaining work, not a canary alone.

Independent preregistration review identified #828 (multi-ID launch would not enforce the stated
per-entry stop/timeout rule) and #829 (raw failure evidence was overpromised). The protocol above
addresses both before any scientific execution; no observed scientific outcome is implied.
