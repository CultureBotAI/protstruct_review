# protstruct_review

Quality-assessment harness for agent-refined or generated protein structures. It records
cross-tool measurements, applies independent-oracle checks, and emits LinkML-validated evaluation
and Quality Data Sheet records.

## Setup

Install [uv](https://docs.astral.sh/uv/), then bootstrap a clean checkout with the same locked
development and benchmark dependencies as CI:

```bash
uv sync --locked --extra benchmark
```

The checked-in `.python-version` selects Python 3.12 (the supported range is Python 3.11–3.12).
Use this repository-selected version for CI-equivalent validation. `uv.lock` fixes the environment
used for validation, tests, linting, LinkML model generation, and retained numerical replays.
Python 3.11 remains supported, but its lock selects Biotite 1.6.0 rather than the retained T15/T16
evidence's 1.7.1, so those exact replays skip. A clean no-extra environment also skips them; neither
is a substitute for the required Python 3.12 benchmark-extra gate.

PHENIX and CCP4 are separate licensed installations and are not installed by `uv`; see
[`ref/oracle_tools.md`](ref/oracle_tools.md) for pinned versions and activation rules.

External-tool discovery is centralized in `scripts/toolchain.py`. Its defaults preserve the pinned
macOS toolchain; override them without editing runners:

| Variable | Meaning |
|---|---|
| `PROTSTRUCT_PHENIX_BIN` | directory containing the PHENIX entry points |
| `PROTSTRUCT_CCP4_SETUP` | CCP4 `ccp4.setup-sh` file |
| `PROTSTRUCT_TMALIGN` | TM-align executable |
| `PROTSTRUCT_DSSP` | `mkdssp` executable |
| `PROTSTRUCT_GEMMI` | `gemmi` CLI executable (optional; the locked wheel provides only the Python module). Like the other overrides, a value that does not resolve falls back to PATH — check `benchmark_environment`'s `configured_path` vs `discovered_executable` |
| `PROTSTRUCT_PROBE` | Richardson-lab `probe` executable |
| `PROTSTRUCT_REDUCE` | Richardson-lab `reduce` executable |

Benchmark runners emit the resolved paths and version evidence as their first stderr JSON record.
Measured version output, weaker configured-path hints, and any `version_divergence` are separate
fields; an override never masquerades as measured version evidence.
Only the fixed CCP4 environment adapter sources a vendor shell file; model/data paths and all tool
arguments are passed directly as subprocess argument vectors.

## Validation

After the locked dependencies are installed, the hermetic gate itself needs no network, PHENIX,
or CCP4. The `uv` wrapper may download missing dependencies before starting it:

```bash
uv run --locked --extra benchmark -- bash scripts/validate.sh
```

For focused checks while iterating, use
`uv run --locked --extra benchmark -- python scripts/test_<area>.py`.

External-tool and online benchmarks are opt-in. Each benchmark's module documentation identifies
its required binaries, data downloads, and command line.

## Sources of truth

- `ref/catalog.yaml` generates `ref/tasks_and_evaluations.tsv`; never hand-edit the TSV.
- `schemas/protstruct_review.yaml` generates `protstruct_review/models.py`; never hand-edit the
  generated model.
- `CODING_STANDARDS.md` defines enforceable repository invariants.
- `.claude/skills/protstruct-eval/SKILL.md` explains the scientific workflow and trust rationale.

See [`ref/README.md`](ref/README.md) for the reference-material map and [`schemas/README.md`](schemas/README.md)
for schema authoring and regeneration details.

## Current 1SAR evidence correction

The [September 23 correction](data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-09-23.md)
and its [cumulative QDS](data/coscientists/openscientist/QDS_1sar_cdba2c07_2026-09-23.yaml)
correct earlier 1SAR interpretations without rewriting frozen records. They concern the packaged
round-4 ribonuclease Sa model, not the missing reported round-7 coordinates. This is a retained-evidence
correction with fresh coordinate recounts and saved-log parsing, not a full scientific rerun or
an overall model-quality pass. Historical numbers with unavailable raw output are identified explicitly.

## Reuse, provenance, and citation

Code is licensed under BSD-3-Clause ([`LICENSE`](LICENSE)); documentation, the LinkML schema and
catalog, and the authored scientific records under `ref/research/` and `data/` are CC-BY-4.0
([`LICENSE-DOCS.md`](LICENSE-DOCS.md), which lists the scope per content class). Cite the repository
as given in [`CITATION.cff`](CITATION.cff).
Third-party materials retain their upstream terms. See [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)
and [`data/README.md`](data/README.md) before redistributing data fixtures. The repository does not
ship a PHENIX documentation mirror; `ref/download_phenix_docs.sh` creates an ignored, opt-in local
cache after the user reviews the upstream terms. Retained deposited fixtures are source- and
checksum-pinned in `data/pdb_mtz/fixture_provenance.yaml`, and the hermetic gate rejects inventory
or checksum drift. Citation metadata lives in [`CITATION.cff`](CITATION.cff) (#402, closed).

The hermetic gate runs in GitHub Actions on Linux and macOS (`.github/workflows/validate.yml`) on every
pull request and push to `main`. CI uses the repository-selected Python 3.12 and locked `benchmark`
extra so retained Biotite evidence is numerically replayed, then runs `scripts/validate.sh`; it does
not invoke DockQ, PHENIX, CCP4, or an online benchmark. Both green Linux/macOS checks on the reviewed
PR head and a CI-equivalent local exit 0 are required before a merge. PHENIX/CCP4 and online
benchmarks remain deliberate, manual workflows.
