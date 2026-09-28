# Dictionary-loaded standalone canary — stopped, 2026-09-28

**#799 remains incomplete.** The preregistered 24MR canary was rejected before
Probe scoring. No clashscore or admitted component inventory exists for this
attempt; no later cohort member ran. The rejected raw output is evidence of the
attempt, not a successful H build or a benchmark result. No grade, threshold,
historical EVAL/QDS record, or published benchmark number changes.

## Registration and actual scope

PR #875 published the reviewed result-free execution commit
`efef43c7ba029d32a4e088202c23e8f3d9a81892` before execution. The locked full gate
passed before that commit; GitHub run 36396229776 passed Linux and macOS before
launch. The source tree was clean before writing the separately retained
pre-execution registration record. Source hashes, the fixed 51-member order,
CI jobs and launch argv are in
`data/coscientists/openscientist/retained_799_campaign_2026-09-28/registration.json`.
The registered method and source files remained unchanged during execution.

Exactly one fresh-input driver invocation ran, using the command in that
registration. The evidence root is
`data/coscientists/openscientist/retained_799_24MR_attempt01/24MR/`.
The parent started at `2026-09-28T08:22:23.945605+00:00` and finished at
`2026-09-28T08:22:31.683864+00:00`. Source acquisition was HTTP 200 from the
registered RCSB URL; `input-provenance.json` retains URL, UTC times and headers.
Reduce 4.16.250520 and Probe 2.26.021123 version commands ran. Probe's version
check is **not** a clashscore execution. The only scientific command receipt is
the explicit-dictionary electron-cloud Reduce `-quiet -build -DB` call.

That command exited 1 with empty stderr. The worker and parent both exited 1.
There was no timeout or termination signal. PID and PGID 28485 match the retained
worker/launch receipts; cleanup confirmed the owned group absent without a
signal attempt. The parent retained 28 inventoried files plus `result.json`:
29 files, 3,944,549 bytes. Root and independent review checked the retained hashes.
The original failed bundle is unchanged, including its hidden staging directory.

The required component sidecar was invoked and refused this unsuccessful
parent, returning 1 with no JSON. Its observed refusal and the exhaustive
launched/admitted/not-launched partition are recorded in
`retained_799_campaign_2026-09-28/stopped-after-canary.json`. Thus one of 51 entries
was launched, zero admitted, and 50 not launched. No retry or flip recount ran.

## What the emitted bytes establish — and what they do not

The source contains 9,128 ATOM/HETATM records and no H records. The rejected
Reduce stdout contains 17,501 coordinate records and 8,373 explicit-element H
records; all those H records are non-HOH. These are direct fixed-column byte
counts, not chemically verified hydrogens. Output's USER MOD header instead
says `add=8400`: that internal tally is not substituted for the emitted-record
count. The output H count matching an earlier reported loaded-dictionary count
does not override the failed status or establish completed optimization.

| Retained bytes | SHA-256 |
|---|---|
| `input.pdb` (807,408 bytes) | `07c2ccd02d074878d51eac543877e4f4ce2b4e87f88532ca4a6d811f537a0563` |
| `commands/01/stdout.bin` (1,508,367 bytes) | `1d921580797d23892ecc57184941334510f5a5151541d1d210361595119637f0` |
| `result.json` | `caa7b5361f1af6b488cb54746c4ffde127142ae6b1d603af1bf231e858a6b4d8` |

The status cannot safely be reinterpreted as either ordinary success or proven
abandonment. Static inspection of the installed Reduce source checkout at
`d723303c0ae7a9991a4f723b74f9bfa268d33e87` found:

- `reduce_src/main.cpp:785,822,830` obtains the optimizer status, emits coordinate
  records regardless, then returns that status.
- `reduce_src/reduce.cpp:70,237–241` names 1 `ABANDONED_RC` and sets it whenever
  a clique result is **less than or equal to zero**.
- `reduce_src/AtomPositions.cpp:875,961–969` returns -1 for failed initialization
  or abandoned optimization. But its completed path returns the number of
  non-default orientations at line 1238; that count can be zero. The status-1
  branch therefore conflates different outcomes. The abandonment diagnostic is
  conditional on `_outputNotice`, disabled by the registered quiet invocation.

These are static source semantics, not proof of which branch the installed
binary took on 24MR. The source checkout's tracked files were clean; its build
directory was untracked. No reproducible source-to-binary attestation is claimed.
The exact executable hash is retained in `tool-identities.json`. Inspected source
SHA-256 values are `9dcd81951ebd1b2811c5e5a174a4a2e90677d30899524ee510f948dfc27b523b`
(`main.cpp`), `0bbda07a7cc0dff77bf9a5fe5602a346c1810fea7a99fc59d9a1152e32d13bf1`
(`reduce.cpp`) and `71b1f820895ff94afc2fb3932eb1a0ada04aa3ff26428aaa0595cee212770949`
(`AtomPositions.cpp`). Do not patch the installed binary or accept status 1
merely because output exists. A separate reviewed diagnostic is needed to
resolve the ambiguity before any new-destination retry or cohort expansion.

## Offline recount

Run from the repository root; this uses only the standard library, no scientific
tool, imports of the retained instrument, network or writes:

```sh
.venv/bin/python -B - <<'PY'
from pathlib import Path
import hashlib, json
p = Path('data/coscientists/openscientist/retained_799_24MR_attempt01/24MR')
r = json.loads((p / 'result.json').read_bytes())
for name, digest in r['retained_files'].items():
    assert hashlib.sha256((p / name).read_bytes()).hexdigest() == digest, name
files = [f for f in p.rglob('*') if f.is_file()]
assert {str(f.relative_to(p)) for f in files} == set(r['retained_files']) | {'result.json'}
print('files, bytes:', len(files), sum(f.stat().st_size for f in files))
for name in ('input.pdb', 'commands/01/stdout.bin'):
    data = (p / name).read_bytes()
    atoms = [x for x in data.splitlines() if x[:6] in (b'ATOM  ', b'HETATM')]
    h = [x for x in atoms if x[76:78].strip() == b'H']
    print(name, len(data), hashlib.sha256(data).hexdigest(),
          'atoms/H_all/H_nonwater:', len(atoms), len(h),
          sum(x[17:20] != b'HOH' for x in h))
w = json.loads((p / 'worker-result.json').read_bytes())
assert r['status'] == w['status'] == 'failed'
assert len(w['command_receipts']) == 1
print(w['command_receipts'][0]['result'])
print(r['process'])
PY
```

This verifies retained-byte consistency and recounts available records. It does
not authenticate historical inputs, certify full optimization, admit the rejected
build, or answer the registered residual prediction. The run is stopped and
partial; #799 and the separate #790 study remain open.
