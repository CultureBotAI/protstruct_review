# T15 1BNI rejected-pair diagnostic — 2026-09-28

The single registered invocation reproduced the predicted **unequal-domain
refusal**: DSSP returned 323 residue keys and Biotite P-SEA returned 324, with
only C/3/blank insertion code present in Biotite. The wrapper exited 1 and
emitted no measurements. The launcher exited 0 only because the expected
failure, evidence checks and prediction matched. This is successful failure
retention, not a T15 quality pass, complete benchmark or permission to resume.

## Registration and execution identity

PR #871 publishes the result-free registration commit
`f05783af4d2c0a50b9cae847fbd794cd33093ca2` before this execution. Its five-file
instrument/registration diff passed the locked Python 3.12 benchmark-extra
gate, external read-only Codex approval with 25 bounded offline/hermetic checks,
and both exact-head CI jobs in run 36394527274 (Ubuntu 108837677046, macOS
108837677297). Registration was not rewritten after observing the result.

Command from that clean registered checkout:

```sh
.venv/bin/python -B scripts/run_t15_failed_attempt_diagnostic.py \
  --repo . --registration-commit f05783af4d2c0a50b9cae847fbd794cd33093ca2 \
  --run-id 1bni01 --execute
```

The preceding plan-only command had the same arguments without `--execute`.
The one scientific invocation started at 2026-09-28T08:09:32.682140Z and its
terminal record was published at 08:09:35.566242Z. No download, PHENIX/CCP4,
atom repair, alternative input, second entry or automatic retry ran.

The retained root is
`data/coscientists/openscientist/retained_evidence_2026-09-27_t15-diagnostic-1bni01/`.
The date in that registered path is not its execution date. Its
`entries/T15_1BNI/launch-request.json` pins the execution commit, exact source
files, input, package metadata and resolved executable bytes. Source/input
snapshots are included. `launch-result.json` reports no identity drift, no
timeout, and verified absence of owned PID/PGID 20899 after wrapper exit 1.

## Recounted observations

| Population | Count |
|---|---:|
| Source ATOM protein residues | 324 |
| Source ATOM/HETATM coordinate records | 2763 |
| DSSP assigned keys | 323 |
| Biotite assigned keys | 324 |
| Shared keys | 323 |
| DSSP-only keys | 0 |
| Biotite-only keys | 1 |

The full source protein domain is chains A/B/C, residues 3 through 110, blank
insertion codes. Biotite covers that entire domain; DSSP covers exactly that
domain minus C3. These counts are recomputed from retained assignment streams
and raw DSSP columns, not inferred from the old log's asymmetric counts.
No agreement/content scalar is calculated or emitted for this unequal pair.

The source bytes are the exact 263,574-byte input from the stopped second
attempt in PR #831, SHA-256
`e7a0612d97d3b9f52f2ab6efcaa94b8baa410c37e30107992e4e2564b5385796`.
Read-only fixed-column extraction confirms that normalized and original inputs
preserve all 2763 atom identities, coordinates, occupancy, B values and elements.
All 324 protein residues have finite positive-occupancy CA; C3 alone lacks N
among the N/CA/C/O names. Missing N remains a plausible mechanism, not a
controlled causal result. No missing atom was filled or residue removed.

Observed version strings are `gemmi 0.7.5`, `mkdssp version 4.6.1`, and Biotite
`1.7.1`. Both normalization and DSSP returned 0. DSSP stderr nevertheless says
`parse error at line 1: This file does not seem to be an mmCIF file`; the exact
warning is retained, not suppressed. Return status, the complete raw table and
source-linked admission are separate evidence; this report does not establish
the internal cause of that diagnostic message.

Normalized bytes SHA-256:
`a245e591e182494e7902f07d3933b752c2f154a90d154676c7a209d7b680f958`.
Raw DSSP bytes SHA-256:
`7ff9af7276105bb68af51f6cc56db8a0537944cb88bac38e3fd932ca77e4dfd1`.
The raw document has a UTF-8 preamble and fixed-column ASCII data rows; a
whole-document ASCII-only reader is not appropriate. The wrapper's complete
failed bundle is 822,873 bytes, SHA-256
`c7ae165111f000ea976a831ee739c4c30b4616e2019fe596bc1df851c0c81b04`.

## Evidence and interpretation boundary

`final-file-manifest.json` has 17 complete file/size/SHA-256 entries, totaling
1,421,140 retained bytes. It excludes only its own bytes; its SHA-256 is
`2aa81d2748a77f9e35046cc578332d3e938e7e29e93f067fc5e935db8fa689b5`.
Every listed hash and the exact file set were rechecked after execution. The
empty wrapper stdout, failure stderr, actual argv, request pin, worker context,
owned-group receipt and unchanged snapshots are retained. The original
registered launcher implements the full admission; a separate read-only stdlib
cross-check independently recounts hashes, key/state equality, domains and
source/normalized coordinate fields. Neither recomputes the DSSP algorithm.

The retained instrument's admission can be replayed without scientific execution
or dependence on the live wrapper. From the repository root:

```python
import importlib.util
import json
from pathlib import Path

root = Path("data/coscientists/openscientist/retained_evidence_2026-09-27_t15-diagnostic-1bni01")
entry = root / "entries/T15_1BNI"
spec = importlib.util.spec_from_file_location(
    "retained_diagnostic", root / "source_snapshot/scripts/run_t15_failed_attempt_diagnostic.py"
)
instrument = importlib.util.module_from_spec(spec)
spec.loader.exec_module(instrument)
print(json.dumps(instrument.audit_failed_bundle(
    json.loads((entry / "failed-attempt.json").read_bytes()),
    json.loads((entry / "launch-request.json").read_bytes()),
    (root / "input_snapshot/1bni.pdb").read_bytes(),
), indent=2))
```

Use Python's `-B` option when running this read-only snippet. This replays the
registered admission implementation, not an independent secondary-structure
algorithm or a fresh measurement. Its numeric output supplies the table above;
independent raw/hash/coordinate recounts additionally checked these observations.

A separate reviewer verified the complete raw header, 323 residue rows and two
break rows, unique serials/keys, supported states and every raw amino-acid/CA
link to the normalized source at DSSP's printed precision. All eight retained
source snapshots match the registered Git blobs. The reviewer then performed
one explicitly allowed Biotite 1.7.1 same-implementation replay on the unchanged
retained source. All 324 labels match; every native code is a/b/c, with no empty
or unsupported value. C3 is native `c`, not a fallback conversion. All 18 root
files, including the manifest, remained unchanged across that replay. This is
implementation replay, not a second independent algorithm, new cohort entry or
additional scientific replicate.

This diagnostic fixes the future failure-retention gap tracked in #829 and
provides auditable evidence for this new invocation. It cannot recover or
authenticate the raw outputs discarded during the old 1BNI attempt. The two
earlier execution roots remain unchanged and separate; eight previously admitted
entries plus this rejection are not nine successful measurements, and the seven
unstarted entries remain unrun.

The preregistered decision is **STOP**. #765 remains incomplete and its
calibration non-gradeable. Further work requires a separately reviewed decision:
retain the failed exact-domain calibration, register a coverage study that
preserves unequal-domain outcomes, or explicitly choose a different input-led
comparison population. An output intersection, invented coil call, missing-atom
repair or success-only union is not an unchanged continuation.

Separate #874 concerns the pre-existing conversion of unassigned/unknown native
Biotite codes into coil on other possible inputs; the native-code replay excludes
that path for this input. It is not evidence that C3's
missing N explains this result and is not grounds to relax this registration.
