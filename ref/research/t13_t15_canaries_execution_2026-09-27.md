# T13/T15 operational canaries — 2026-09-27

Protocol: `ref/research/t13_t15_canaries_preregistration_2026-09-27.md`,
result-free [PR #831 preregistration](https://github.com/CultureBotAI/protstruct_review/pull/831)
commit `4a150693dd64b79c38e9e57561667215994a35a1`.
Execution timestamps below are **2026-09-28 UTC** (2026-09-27 America/Los_Angeles).
This is a read-only reconstruction of retained results, not another scientific run.

**Outcome:** the T13 merged-amplitude wrapper produced its expected operational
result. The T15 protocol is incomplete: the second root admitted eight entries,
then stopped on 1BNI's reported unequal residue-key sets. Seven later entries were
not launched. No complete-cohort calibration, new model-quality verdict, threshold
change, or 16-entry success union is supported.

## Retained roots and complete attempt inventory

Repository-relative aliases used below:

- **E01** = `data/coscientists/openscientist/retained_evidence_2026-09-27_canaries01`
- **E02** = `data/coscientists/openscientist/retained_evidence_2026-09-27_canaries02`

Both roots' `launch-root.json` bind the same preregistration commit and identical
scientific-script/lockfile hashes. Each attempted entry retains
`entries/<entry>/launch-request.json`, `launcher.log`, and `launch-result.json`.
All request start times are at line 40 of their request file. The last column
below identifies the exact `returncode` line in that entry's result file.
All sixteen launcher attempts have `timed_out: false`, `launcher_error: null`,
`sources_unchanged: true`, and `t13_input_unchanged: true`.
Here “admitted” means the retained-data evidence checks passed, **not** a model
quality pass or an accepted complete-cohort calibration.

| Root | Entry | Start UTC | Retained outcome | Result returncode line |
|---|---|---|---|---:|
| E01 | T13_1SAR | 05:00:29.416372 | operational output; exit 0 | 48 |
| E01 | T15_1UBQ | 05:01:50.560494 | admitted; exit 0 | 76 |
| E01 | T15_1LYZ | 05:03:25.895972 | admitted; exit 0 | 104 |
| E01 | T15_1LZ1 | 05:04:29.759408 | admitted; exit 0 | 132 |
| E01 | T15_2PTN | 05:05:22.014978 | admitted; exit 0 | 160 |
| E01 | T15_7RSA | 05:06:03.778996 | admitted; exit 0 | 188 |
| E01 | T15_1CA2 | 05:07:45.595894 | fetch/DNS failure; exit 1; protocol stopped | 200 |
| E02 | T15_1UBQ | 05:09:24.495461 | admitted; exit 0 | 52 |
| E02 | T15_1LYZ | 05:10:09.715989 | admitted; exit 0 | 80 |
| E02 | T15_1LZ1 | 05:10:32.580772 | admitted; exit 0 | 108 |
| E02 | T15_2PTN | 05:10:50.105206 | admitted; exit 0 | 136 |
| E02 | T15_7RSA | 05:11:04.363186 | admitted; exit 0 | 164 |
| E02 | T15_1CA2 | 05:11:18.489183 | admitted; exit 0 | 192 |
| E02 | T15_1MBN | 05:11:36.631791 | admitted; exit 0 | 220 |
| E02 | T15_3EST | 05:11:50.715023 | admitted; exit 0 | 248 |
| E02 | T15_1BNI | 05:12:06.095925 | exact-denominator refusal; exit 1; protocol stopped | 272 |

E01 has one T13 attempt plus six T15 attempts: five admitted and one failed.
Its ten unstarted T15 entries are 1MBN, 3EST, 1BNI, 2CI2, 9PAP, 1HEW, 4PTI,
1CRN, 2LYZ and 1TIM. E02 has nine T15 attempts: eight admitted and one failed.
Its seven unstarted entries are 2CI2, 9PAP, 1HEW, 4PTI, 1CRN, 2LYZ and 1TIM.
T13 was not rerun in E02. Directory traversal included every file under both
roots, independent of gitignore; no unstarted entry directory was present.

E01 and E02 are separate execution attempts. The five repeated successful IDs
are not five additional cohort members. Keep all fifteen T15 attempts, including
both failures; do not splice their successes into a purported sixteen-ID run.
E01 contains 45 files and E02 63 files at this review snapshot. Every file
listed by every retained launch-result inventory was re-hashed and matched its
recorded size/SHA-256. The manifests exclude their own creation, so these full
root file counts differ from the last manifests' 44 and 62 inventoried files.

E01's 1CA2 attempt failed before either assigner ran:
`E01/entries/T15_1CA2/launcher.log:61` records
`urllib.error.URLError: <urlopen error [Errno 8] nodename nor servname provided, or not known>`.
Its PDB, wrapper log and evidence JSON were not produced. The orchestration
record attributes this to the default network-restricted sandbox; the retained
log itself establishes the DNS/fetch failure. A separately authorized fresh
E02 root used network-enabled launches; E01 was neither cleaned up nor repaired.

## T13: operational acceptance scope, not a quality grade

Source: `data/coscientists/openscientist/retained_evidence_2026-09-23/data/1sar.mtz`,
SHA-256 `f36d5fe685a3e524e8809d17d19ce12073acdf339eba2cfd3b0347a818850ab2`.
The result records unchanged input/source hashes and outer exit 0
(`E01/entries/T13_1SAR/launch-result.json:48,63,65`).

The attempted tool logs identify AIMLESS 0.8.3 with CCP4 9.0.015
(`tool_logs/aimless.log:5`) and ctruncate 1.17.29 with CCP4 9.0.015
(`tool_logs/ctruncate.log:9`). AIMLESS reports
`hkl_unmerge_list::prepare - EMPTY` at lines 51 and 66; this is retained as the
expected merged-only limitation, not successful unmerged-data analysis.
The ctruncate output is nonempty (147760 bytes), with MTZ header
`NCOL 5 7248 0` and F/SIGF columns. Its SHA-256 is
`a0bc6078b7d007bfb5002d546956c154dc67f01ab8bf8a0d1419ae3fe7201dd1`.

The six YAML measurement-shaped rows in the T13 launcher log are informational,
dataset-scoped, bound to the input digest, and cite retained tool logs
(`launcher.log:5–109`). Five use the explicit F-obs/SIGF-obs selector; the
attempt-status row names all input reflections. Available outputs are retained
as diagnostics, not as paired agreement verdicts. The status-bearing fields were checked against explicit fresh-log sections;
missing text was not interpreted as a negative scientific finding. This operational
record does not republish the new diagnostic values as evaluated structure-quality
claims; those would require the normal EVAL/QDS workflow.

This demonstrates the installed merged-amplitude path and retained-output
provenance only. It does not supply unmerged CC½/Rmerge/Rmeas coverage, paired
agent agreement, or model-quality acceptance. No diagnostic is promoted into
an issued EvaluationRun/QDS by this report. The original read-only verifier also exercised existing-destination refusal with
tool calls mocked to fail if reached and confirmed that retained bytes did not
change. The committed replay and tests separately check the preserved operational
evidence; no scientific command is invoked by replay.

## T15 admitted evidence, without a success-only cohort conclusion

For each successful attempt the read-only verifier checked the fetched input
digest; retained normalized-coordinate and raw-DSSP byte size/hash; complete
unique residue-key assignment streams; raw DSSP reparse; exact denominators;
aggregate/count arithmetic; content-bound bundle identity; collector rows;
and both informational wrapper rows/evidence references.
All thirteen successful T15 attempts across E01/E02 were rechecked during this
report preparation, without invoking Gemmi, DSSP or Biotite computation.

Every successful bundle records normalization `gemmi 0.7.5`,
`mkdssp version 4.6.1`, and Biotite `1.7.1`. Raw DSSP headers independently name
DSSP 4.6.1. These are actual recorded outputs/distribution versions, not inferred
from configured path names. Each successful entry has zero dropped keys.

| E02 entry | Equal DSSP/Biotite/scored count | Agreements | DSSP H+E count | E01 status |
|---|---:|---:|---:|---|
| 1UBQ | 76 | 57 | 44 | same integer counts; separate admitted attempt |
| 1LYZ | 129 | 93 | 64 | same integer counts; separate admitted attempt |
| 1LZ1 | 130 | 98 | 67 | same integer counts; separate admitted attempt |
| 2PTN | 223 | 154 | 104 | same integer counts; separate admitted attempt |
| 7RSA | 124 | 98 | 70 | same integer counts; separate admitted attempt |
| 1CA2 | 256 | 181 | 119 | fetch failure |
| 1MBN | 153 | 130 | 120 | not launched |
| 3EST | 240 | 163 | 116 | not launched |
| 1BNI | unavailable | unavailable | unavailable | not launched |
| 2CI2, 9PAP, 1HEW, 4PTI, 1CRN, 2LYZ, 1TIM | not launched | — | — | not launched |

Each successful count is grounded in
`E02/t15_evidence/<lowercase-id>.t15-evidence.json::aggregate`, independently
recounted from `per_residue_assignments` and retained raw DSSP; its runner mirror
is `E02/entries/T15_<ID>/benchmark.json::rows[0]`.
For these eight entries, raw integer checks satisfy
`100 * agreements >= 65 * scored` and `100 * (H+E) >= 20 * scored`.
This describes only admitted entries. The predeclared expectation that all
sixteen would achieve exact-key admission was not realized by this attempt,
and the full-cohort agreement expectation remains unestablished. No floor was
lowered, member replaced, denominator intersected, or excluded failure called a
success. Neither oracle-pair scalar is a gradeable model-quality finding.

## 1BNI failure: what is known and what is not

`E02/t15_cache/t15_1bni.log:1` states:

> t15_ss_agreement: assigners scored different residue sets: DSSP-only=0, biotite-only=1; T15 agreement and its DSSP H+E interpretability diagnostic require the same denominator.

The collector preserves `rows: []` and a skipped 1BNI row
(`E02/entries/T15_1BNI/benchmark.json:2–10`); the outer launcher records exit 1,
PID/PGID 1547, and no timeout (`launch-result.json:270–275`).
This is the wrapper's intended fail-closed behavior under
`scripts/t15_ss_agreement.py:300–319`, not evidence that the guard should relax.

Retained source PDB: 263574 bytes, SHA-256
`e7a0612d97d3b9f52f2ab6efcaa94b8baa410c37e30107992e4e2564b5385796`.
The failed wrapper log is 177 bytes, SHA-256
`e24f8c8eb8c6eebfe74c09ec8f30523a5007f03f33bebe423c131544fd2ea81a`.
No `1bni.t15-evidence.json`, normalized PDB, raw DSSP file, or assignment stream
survives in this attempt's complete retained directory inventory. This is the
failure-evidence limitation disclosed before execution (#829), not a newly
discovered failure mode: raw DSSP is deleted at script line 158, normalized
coordinates at line 719; `agreement()` can exit at line 723 before bundle
construction/publication at lines 746–762. The log reports counts but omits the
actual asymmetric residue keys, although they exist in memory at lines 311–312.

Read-only fixed-column inspection finds a concrete input clue, **not a cause**.
`E02/t15_cache/1bni.pdb:265` lists VAL C3 missing N/CB/CG1/CG2; its actual
coordinate lines 2184–2186 contain CA/C/O, followed by ILE C4 at 2187.
Across all 324 ATOM residues (108 each in chains A/B/C, numbered 3–110),
C3 alone lacks any of N/CA/C/O. The file also lists missing ALA1/GLN2 for each
chain at lines 244–249. Whole-file stdlib inspection found no ATOM altlocs,
insertion codes, zero-occupancy backbone atoms, or MODEL/ENDMDL records.
These are statements about the saved input, not either assigner's choices.

It is plausible to investigate C3's incomplete backbone, but this evidence does
**not** establish that DSSP omitted C3, identify the actual unmatched key, or
distinguish an algorithmic limitation from normalization/parser/selection
behavior. DSSP reads normalized coordinates while Biotite reads the original
source (`scripts/t15_ss_agreement.py:710–723`). Do not call 1BNI intrinsically
incompatible, assign a secondary-structure quality verdict, or “fix” the result
by dropping a residue or substituting a different model.

## Disposition

Preserve and publish both complete attempt roots, including the failed and
unstarted states; keep T15 informational and #765's complete-cohort work
unresolved. #829 remains open for retaining the rejected invocation's
available raw bytes, both assignment streams and exact asymmetric keys while
keeping the failure exit/no-grade behavior. Its protocol-overclaim portion was
corrected before execution; its instrument acceptance criteria now include this
observed failure. No diagnostic rerun is claimed here.

## Replay boundary

The two attempt roots are immutable. Exact execution-source snapshots, verified
against both launch-root manifests, are retained separately under
`data/coscientists/openscientist/retained_canary_sources_2026-09-27/`.
The original scratch launcher and read-only verifier are preserved there as
`execution_helpers/*.py.txt`; they are execution-method history, not current
entry points or a license to replay external tools. The source snapshots allow
byte-level provenance checking without requiring the preregistration commit in
a shallow checkout.

Use the committed read-only `scripts/recount_t13_t15_canaries.py` to reconstruct
attempt counts and verify retained evidence. Failed and unstarted members remain
explicit; no successful-subset union or complete-cohort calibration is generated.

## Independent review and regression checks

A separate read-only reviewer checked both complete attempt sequences, all
thirteen successful raw-DSSP streams and integer counts, both failure states,
the original result-free preregistration chronology, and the eight source
snapshots against the original Git objects. The T13 operational evidence and
1BNI input-only inspection also matched the report; no merge blocker was found.

Twenty-seven hermetic tests pass, including a separate replay of the actual
retained roots with subprocesses and file writes denied. Four independent
in-memory guard-removal controls each fail one intended assertion with no
errors: raw-DSSP comparison, file-hash verification, historical source pinning,
and benchmark subject identity. These establish replay behavior, not additional
scientific executions or a completed T15 cohort. Full local validation and
exact-head Linux/macOS CI remain prerequisites for merging the record.
