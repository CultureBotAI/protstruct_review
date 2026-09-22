# `EVAL_*` filename convention

Evaluation reports produced by the protstruct_review harness sit next to the artifact they evaluate (typically under `data/<provider>/<system>/`). To keep them sortable, groupable, and traceable to a specific input, all eval files use the same name shape.

## Format

```
EVAL_<structure>_<artifact-short-id>_<YYYY-MM-DD>.yaml
EVAL_<structure>_<artifact-short-id>_<YYYY-MM-DD>.md
```

| Field | Definition | Example |
|---|---|---|
| `<structure>` | The PDB / EMDB / target identifier the agent was asked to refine or generate. Lowercase, no spaces. | `1sar`, `7a4m`, `af-p00698-f1` |
| `<artifact-short-id>` | First 8 hex characters of the agent run's UUID (or any other stable, short, unique tag for the agent run). Disambiguates multiple agent runs on the same structure. | `cdba2c07` |
| `<YYYY-MM-DD>` | Date the evaluation was *run*, ISO 8601. Sorts chronologically when an artifact is re-evaluated (e.g. after a new oracle is added). | `2026-04-24` |

The schema-validated YAML is the canonical machine-readable evaluation record. The Markdown file is
its human-readable narrative when one is published. They share the same stem so a single glob
(`EVAL_1sar_cdba2c07_2026-04-24*`) returns the record, narrative, and any optional exports. Historical
narrative-only reissues may point to an earlier canonical YAML record; new structured re-runs should
instead publish a date-matched YAML record so their measurements and scope are immutable.

### Optional parallel `_<view>.tsv` exports

A single eval may export one or more denormalized TSV views of the canonical YAML. Add a `_<view>`
suffix to disambiguate. These exports are optional; their absence does not make an otherwise complete
YAML/Markdown evaluation incomplete. Two suffixes are reserved:

| Suffix | Content | Row count |
|---|---|---|
| `_metrics.tsv` | One row per (catalog_task, metric, oracle_tool, stage) — a denormalized long-format export. | many (10s–100s) |
| `_headline.tsv` | One row per top-level finding for the eval — a chat-summary / leaderboard export. Each row collapses one or more measurement rows according to its export policy. | few (5–10) |

When present, both share the same date-stamped stem so
`EVAL_1sar_cdba2c07_2026-04-24*.tsv` returns both.

If you add a new view (e.g. `_per_round.tsv`, `_per_residue.tsv`), keep the same stem and pick a noun-shaped suffix.

## Example

```
data/coscientists/openscientist/
├── cdba2c07-...-artifacts.zip                    # input artifact (UUID-named by agent)
├── cdba2c07-...-report.pdf                       # input artifact
├── EVAL_1sar_cdba2c07_2026-04-24.yaml            # canonical, schema-validated record
├── EVAL_1sar_cdba2c07_2026-04-24.md              # human-readable eval report
├── EVAL_1sar_cdba2c07_2026-04-24_metrics.tsv     # optional denormalized export
└── gemmi_rfactor.py                              # eval helper script (not date-stamped — reused)
```

## Why this shape

- **Structure first** — within an agent-run directory, all evals of the same target cluster together. `ls EVAL_1sar*` returns every 1SAR eval at a glance.
- **Artifact short-id second** — when the same structure is refined by multiple independent agent runs (different seeds, different prompt variants, different agent versions), each run's eval is unambiguous without reading file contents.
- **Date last** — when an existing eval is **re-run** because a new oracle was installed (e.g. CCP4/REFMAC5 finally available), the new file gets a later date and lives alongside the older one. Don't overwrite — append.

## When to bump the date

Re-run produces a new file (don't overwrite) if:

- A new oracle was added to the catalog and re-running closes a previously-open gap.
- The agent re-ran and produced a new artifact (different `<artifact-short-id>` — separate record bundle, no collision).
- A bug in an oracle invocation was fixed.

Re-run **may overwrite the same date** if:

- Just fixing typos or formatting in the same eval.
- Adding a section to a still-fresh report on the same day.

## When the convention doesn't apply

- `EVAL_metrics.tsv` aggregated across many runs (e.g. a leaderboard) → use a separate name like `LEADERBOARD_*.tsv` or put it in a top-level `results/` directory. Don't reuse the `EVAL_` prefix for cross-run summaries.
- Catalog-level documents (`tasks_and_evaluations.md`, `oracle_tools.md`) → `ref/`, no date stamp; they evolve under git history.

## Loading canonical records by glob

```python
from pathlib import Path
import yaml

for record_path in Path("data").rglob("EVAL_*.yaml"):
    record = yaml.safe_load(record_path.read_text())
    structure, run_id, run_date = record_path.stem.split("_")[1:]
    # ... validate or aggregate record["evaluation_runs"] ...
```
