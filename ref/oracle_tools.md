# Independent oracle tools — install status and per-metric recommendations

<!-- catalog-state: tasks=T01–T17; count=17; drivers=17 -->

The protstruct_review trust model requires that PHENIX outputs be cross-checked by **at least one non-cctbx tool** per task (see `tasks_and_evaluations.md` philosophy section). This page records which oracles are installed locally on this machine and how to invoke them. The **canonical per-metric recommendations** live in `ref/tool_recommendations.yaml` (LinkML-validated, schema-class `ToolRecommendation`).

## Recommendations vocabulary

For each metric in the catalog we track up to four kinds of tool record:

| Role | Meaning | Source |
|---|---|---|
| **`top_considered`** | The canonical tool the literature / community consensus says to use for this metric. | Citations in `ref/quality_reporting.md` and `ref/tool_recommendations.yaml`. |
| **`top_performing`** | The tool that has empirically done best on this metric **in this harness**. Often the same tool as `top_considered`; when they differ both rows exist. | Evidence is an `EvaluationRun.id` from `data/.../EVAL_*.yaml`. |
| **`alternative`** | Acceptable second-line oracle. Used when the primary tool is unavailable or as a corroborating check. | Same. |
| **`deprecated`** | Was recommended; no longer is. Kept for historical comparison. | Same; `notes` field carries the deprecation reason. |

When a `MeasurementValue.oracle_tool_ref` doesn't match any `top_considered` or `top_performing` recommendation for that metric, downstream tooling should flag it. The `QualityDataSheet.tool_recommendations_applied[]` slot snapshots the recommendations active at the time the QDS was issued, since recommendations evolve and the QDS is immutable.

To browse / query recommendations:

```bash
linkml-validate --schema schemas/protstruct_review.yaml ref/tool_recommendations.yaml
python -c "
import yaml; d = yaml.safe_load(open('ref/tool_recommendations.yaml'))
for r in d['tool_recommendations']:
    if r['role'] == 'top_considered':
        print(f\"{r['metric_definition_ref']:40} -> {r['tool_ref']}\")
"
```

## Installed

| Oracle | Version | Path | Catalog tasks served |
|---|---|---|---|
| **gemmi** | 0.7.5 | PATH or `PROTSTRUCT_GEMMI` (locally `/opt/homebrew/bin/gemmi`, brew tap `brewsci/bio`); resolved per call by `toolchain.gemmi_executable()` to an absolute path | T01 (`gemmi align`), T06 (`gemmi sfcalc`), T14 (`gemmi h`), T05 (**`gemmi rmsz`** — there is no `gemmi validate` subcommand) |
| **TM-align** | 20220412 | `$HOME/tools/tmalign/TMalign` | T01 (TM-score, sequence-independent superposition) |
| **probe** (Richardson lab) | 2.26.021123 | `$HOME/tools/probe-src/probe` | T05 (clash detection — feeds clashscore) |
| **reduce** (Richardson lab) | 4.16.250520 | `$HOME/tools/reduce-src/build/reduce_src/reduce` | T14 (H-atom placement); T05 (input prep for clashscore) |
| **Servalcat** | 0.4.131 | conda env `cryst-oracles` (`mamba activate cryst-oracles`) | T03 (`servalcat refine_xtal_norefmac`), T06 (`servalcat fsc`, `fofc`, `sigmaa`), T12 |
| **OpenStructure (OST)** | 2.11.1 | conda env `cryst-oracles` (CLI `lddt`, Python `import ost`) | T01 (`lddt` — CASP15+ reference implementation, global + per-residue), T02 (per-residue Cα distance + structural comparison), T05 (Ramachandran φ/ψ extraction; outlier classification needs external Top8000 contour data), T07 (per-residue lDDT for predicted-vs-experimental) |
| **CCP4 suite** (REFMAC5, ProSMART, aimless, ctruncate, pointless) | 9.0.015 | `/Applications/ccp4-9.0.015-shelx-arpwarp-macosarm/ccp4-9/` (source `bin/ccp4.setup-sh` first) | T02/T05 (ProSMART — Procrustes per-residue geometry; non-cctbx Ramachandran-Z for T05), T03 (REFMAC5 — independent refiner / R-factors), T13 (ctruncate — Wilson B / twinning / anisotropy / tNCS / ice rings on merged data; aimless — canonical when unmerged intensities are available; pointless — space-group sanity) |
| **DSSP** (`mkdssp`) | 4.6.1 | `/opt/homebrew/bin/mkdssp` (`brew install brewsci/bio/dssp`) | T15 (secondary-structure assignment; H-bond energetics half of the agreement metric) |
| **biotite** | 1.7.1 | locked `benchmark` extra (`uv sync --locked --extra benchmark`) | T15 (P-SEA Cα-geometry secondary structure, `scripts/t15_ss_agreement.py`); T16 (Shrake-Rupley SASA buried surface area, `scripts/t16_interface_quality.py`); T17 (ensemble Cα-RMSF precision, `scripts/t17_nmr_ensemble.py`) |
| **DockQ** | 2.1.3 | locked `benchmark` extra (`uv sync --locked --extra benchmark`; pins numpy < 2) | T16 (interface DockQ score + CAPRI class via `scripts/t16_interface_quality.py`) |

Together, `probe` + `reduce` constitute the standalone Richardson-lab MolProbity pipeline that the catalog calls "MolProbity standalone" — these are the same binaries the MolProbity web service runs.

Servalcat ships a no-REFMAC refinement mode (`refine_xtal_norefmac`, `refine_spa_norefmac`) so it can serve as a T03 second-opinion oracle even without CCP4.

For **T13** the practical layering is: **aimless** is the canonical recommendation but requires *unmerged* intensities (M/ISYM column). When the artefact ships only merged amplitudes (the 1SAR case — F-obs / SIGF-obs only), aimless aborts with `hkl_unmerge_list::prepare - EMPTY`. **ctruncate** is the merged-data fallback for the metrics it can still compute (Wilson B, L-test twinning, ΔB anisotropy, tNCS, ice rings); CC½, ⟨I/σ⟩ outer, and Rmerge / Rmeas remain unobtainable without raw integration intensities. The wrapper at `scripts/t13_data_quality.py` runs both and emits parsed measurement rows.

## Not installed (recorded gaps)

| Tool | Why not installed | Catalog tasks affected | Recommendation |
|---|---|---|---|
| **ChimeraX** | Heavy GUI install; useful for `matchmaker` (T01) and `fitmap` (T08) | T01, T08 | <https://www.cgl.ucsf.edu/chimerax/download.html> |
| **MoRDa** | Specialised MR pipeline | T09 only | Install only if T09 becomes a regression target |
| **STRIDE** | Homebrew no longer ships it; biotite P-SEA stands in as the second assigner (see Installed) | T15 | Optional: build from <https://webclu.bio.wzw.tum.de/stride/>. DSSP + biotite already give a runnable agreement metric. |
| **CATH / SCOPe / ECOD** | Database lookups rather than local binaries | T15 | Query the web APIs, or cache per-domain assignments alongside the example datasets |
| **PISA/PDBePISA** | No local build — but the **PDBe REST API** serves the same PISA 2.0 result machine-readably, so T16 BSA is no longer web-form-blocked | T16 (buried surface area only) | `https://www.ebi.ac.uk/pdbe/api/pisa/interfaces/<pdb_id>/1` (assembly 1). `interface_area` is **per side** — double it to compare with ΣSASA(chains) − SASA(complex). Used by `scripts/bench_t16_bsa_vs_pisa.py` |
| **wwPDB NMR validation / PROCHECK-NMR / RPF** | No local install; wwPDB validation reports are fetched per entry | T17 | Fetch the deposited validation report; install PROCHECK-NMR only if T17 becomes a regression target |

## Quick activation snippets

All benchmark runners consume the shared configuration in `scripts/toolchain.py`. The defaults below
match the pinned macOS installation; on another machine set `PROTSTRUCT_PHENIX_BIN`,
`PROTSTRUCT_CCP4_SETUP`, `PROTSTRUCT_TMALIGN`, `PROTSTRUCT_DSSP`, `PROTSTRUCT_GEMMI`, `PROTSTRUCT_PROBE`, or
`PROTSTRUCT_REDUCE`. Do not edit individual runners. Each benchmark emits expected versions,
resolved paths, measured version output, separately labeled configured-path hints, and a
`version_divergence` flag before measurements begin. An override that does not match the registered
version is therefore explicit in the benchmark record.

**Crystallography oracle env (Servalcat):**
```bash
source /opt/homebrew/Caskroom/miniforge/base/etc/profile.d/conda.sh
conda activate cryst-oracles
```

**CCP4 (REFMAC5, ProSMART, aimless, ctruncate, pointless):**
```bash
source /Applications/ccp4-9.0.015-shelx-arpwarp-macosarm/ccp4-9/bin/ccp4.setup-sh
```

**Richardson-lab tools on PATH:**
```bash
export PATH="$HOME/tools/probe-src:$HOME/tools/reduce-src/build/reduce_src:$HOME/tools/tmalign:$PATH"
```

(Add to `~/.bashrc` or wrap in a project-local `env.sh` — not committed.)

## Verifying after install

```bash
gemmi --version            # 0.7.5  (needs zlib-ng: `brew install zlib-ng`, else dyld fails to load libz-ng)
TMalign | head -2          # TM-align Version 20220412
probe -version             # probe.2.26.021123
reduce -version            # reduce.4.16.250520
conda activate cryst-oracles && servalcat --version  # 0.4.131
```

## Cross-tool oracle assignment per catalog task

| Task | Primary PHENIX tool | Oracle (now installed) | Oracle (still missing) |
|---|---|---|---|
| T01 | `phenix.superpose_models` | TM-align, `gemmi align`, OpenStructure (`lddt`), CCP4 ProSMART | ChimeraX matchmaker, US-align |
| T02 | `phenix.structure_comparison` (PHENIX 2.0-5936 launcher is GUI/project-bound; a headless two-file invocation exits without a report) | OpenStructure, CCP4 ProSMART, gemmi coordinate analysis, DSSP | — |
| T03 | `phenix.refine` | `servalcat refine_xtal_norefmac`, CCP4 REFMAC5 (`NCYC=0` for in-place R-factors) | BUSTER |
| T05 | `phenix.holton_geometry_validation` | `probe` + `reduce` (std MolProbity), `gemmi rmsz`, CCP4 ProSMART | wwPDB validation pipeline |
| T06 | `phenix.model_vs_data` | `gemmi sfcalc`, `servalcat fsc`/`fofc`/`sigmaa`, CCP4 REFMAC5 | CCP4 sfcheck |
| T12 | `phenix.mtriage` | `servalcat fsc`, `servalcat localcc` | RELION postprocess, ResMap |
| T13 | `phenix.model_vs_data` (completeness, resolution range) | CCP4 ctruncate (Wilson B, L-test twinning, ΔB aniso, tNCS, ice rings); CCP4 aimless when unmerged intensities exist; wrapper `scripts/t13_data_quality.py` | (CC½ / ⟨I/σ⟩ / Rmerge require unmerged intensities — gap when artefact ships merged-only) |
| T14 | `phenix.reduce`; `mmtbx.reduce2` | standalone Richardson `reduce`: same-binary dispatcher/distribution check against `phenix.reduce`, but a distinct-builder flip-conflict comparison against `mmtbx.reduce2` | propka3, OpenBabel; neutron evidence |
| T15 | *(none — PHENIX has no fold/domain classifier)* | DSSP + biotite (`scripts/t15_ss_agreement.py`) | STRIDE (optional); CATH, SCOPe, ECOD (domain/fold) |
| T16 | *(none — no PHENIX interface scorer)* | DockQ (interface score + CAPRI class), biotite SASA (buried surface area) | PISA/PDBePISA (deposition-grade BSA reference) |
| T17 | *(none — no PHENIX NMR restraint validator)* | biotite ensemble precision (`scripts/t17_nmr_ensemble.py`); wwPDB report parser (`scripts/t17_restraint_summary.py`) | PROCHECK-NMR, RPF |

Runnable independent-oracle coverage now spans T01–T17. CCP4/REFMAC hardens T03/T06, while
the metric-specific gaps listed below remain explicit rather than being filled by a cctbx-only
substitute.

**T14 independence is metric-specific.** In the measured installation, `phenix.reduce` and
standalone `reduce` both dispatch Richardson `reduce.4.16.250520`; comparing them checks packaging,
defaults, and distribution dictionaries, not independent H-placement reasoning. The registered
confident flip-conflict comparison instead pairs standalone `reduce 4.16.250520` with the distinct
`mmtbx.reduce2` builder from PHENIX 2.0-5936, using
`approach=add add_flip_movers=True`. Its ≤ 10 % band governs only a preregistered cohort aggregate
from that exact pipeline. A single structure or a different executable, version, or mover setting is
informational pending a matched benchmark. Protonation-state corroboration still needs an
algorithmically distinct source such as propka3 or, where available, neutron evidence.

**T15 is now runnable** for its paired oracle-side check
(`T15_secondary_structure_content` alongside `T15_secondary_structure_agreement`).
`scripts/t15_ss_agreement.py` runs two independent, non-cctbx secondary-structure assigners on a
model and reports DSSP H+E content plus the three-state (H/E/C) agreement fraction:

- **DSSP** (`mkdssp` 4.6.1, `brew install brewsci/bio/dssp`) — Kabsch & Sander H-bond energetics.
- **biotite P-SEA** (`pip install biotite`, 1.7.1) — Labesse Cα-geometry method; a different
  algorithm family, so agreement is informative rather than tautological. Stands in for STRIDE,
  which Homebrew no longer ships. Demonstrated: DSSP vs biotite on the verified archive download
  `data/pdb_mtz/1sar_deposited.pdb` → **166/192 = 0.8646** agreement, with DSSP H+E content
  **75/192 = 0.3906**. Report both values informationally. Content ≥ 0.20 provisionally supports
  interpreting the exact-denominator agreement; content below 0.20 warns that coil/coil calls may
  dominate but does not fail model quality. The historical 0.65 expectation is provisional and
  non-gradeable until recalibration. The separate agent-vs-DSSP ≥ 0.85 clause is unevaluable
  unless an agent supplies a per-residue assignment.

  The wrapper requires `--evidence-out` naming a new repository-local JSON file and never
  overwrites it. That bundle retains exact normalized-input and raw-DSSP bytes, source and
  normalized hashes, DSSP/P-SEA per-residue assignments, and measured versions; both emitted rows
  cite it in `evidence_refs`.

**T16 is fully runnable.** `scripts/t16_interface_quality.py` emits all three metrics:

- `T16_interface_buried_surface_area` — always, from the model alone, via **biotite** Shrake-Rupley
  SASA (ΣSASA(chains) − SASA(complex); an installable stand-in for the PISA web service). This is
  the **total two-sided** BSA. Demonstrated: deposited `1sar` A/B → 442.1 Å² total (221.05 Å² per
  side).
- `T16_interface_dockq_score` + `T16_capri_interface_quality_class` — when a `--native` reference is
  given, via **DockQ** (2.1.3), CAPRI class derived from the score (Basu & Wallner 2016 bands).
  Identity calibration on deposited `1sar` A/B → DockQ 1.000, class High. DockQ runs require
  typed candidate and native subjects, an explicit selected native-interface pair via
  `--native-chains A:B`, plus one repeated mapping/interface-id/raw-JSON triple per mapping;
  every sequence-equivalent bijection within that declared native pair is explicit and every raw
  JSON output is retained. Every invocation also requires a new repository-local
  `--bsa-evidence` JSON destination; the wrapper records the model hash, measured Biotite version,
  chains, 1.4 Å probe, 1000-point quadrature, raw SASAs, and derived BSA, and publishes that file
  atomically with all DockQ evidence. A required `--headline-interface-id` selects one declared
  mapping for the emitted scalar bundle without assigning scientific meaning to CLI order; all
  mappings remain in structured `InterfaceQuality` rows. Native runs require `--structure-id` and
  emit a pasteable EvaluationRun fragment with separate `measurements` and
  `interface_qualities` lists. The wrapper currently accepts PDB input only.

PISA/PDBePISA stays the `top_considered` oracle for buried surface area (the deposition-grade
reference); its `interface_area` is per side and must be doubled before comparison with the
harness's total two-sided value. Biotite SASA is the installed `top_performing` stand-in. The two
have now been benchmarked head-to-head over 25 interfaces — biotite runs **1.2 % high (median),
one-sided in 25/25** — with agreement required within **max(3 % of the mean, 30 Å²)** under a
matched 1.4 Å probe. The measured selection is intentionally asymmetric: biotite is protein-only,
whereas the PISA API assembly surface may include ligand/hetero atoms; the envelope includes that
difference and is not a matched-protein-only PISA claim:
`ref/research/tolerance_benchmark_interface_bsa.md`.

> **numpy pin:** DockQ requires `numpy < 2`; the locked benchmark environment uses numpy 1.26.4. If a
> future oracle needs numpy ≥ 2, isolate DockQ in its own venv/conda env rather than changing the
> locked benchmark environment.

**T17 is fully runnable.** Two scripts, two metrics:

- `scripts/t17_nmr_ensemble.py` computes `T17_nmr_ensemble_precision_rmsd` — the mean per-residue Cα
  RMSF about the ensemble mean — from a multi-model NMR PDB alone, via **biotite** (no restraints or
  report needed). Reports an **ordered-core** mean (the tool-comparable figure, residues with RMSF ≤ 2 Å) alongside the whole-chain mean — `data/pdb_mtz/1d3z.pdb` (ubiquitin, 10 models): core 0.316 Å, whole-chain 0.428 Å.
- `scripts/t17_restraint_summary.py` computes `T17_nmr_restraint_violation_summary` (informational)
  by parsing the restraint-analysis section of the deposited **wwPDB validation report**. Needs an
  entry whose report carries restraint data — older entries (1D3Z, 1998) predate it and the tool
  says so loudly. Demonstrated on `data/pdb_mtz/2n54_validation.xml.gz` → 1301 distance + 108
  dihedral restraints, violations by band.

This closes the runnable-oracle side of issue #3: T15's informational pair and the gradeable
T16/T17 metrics have real measurement paths (only informational T16 BSA still prefers PISA over
the biotite stand-in). T15 still lacks a calibrated gradeable oracle-pair criterion.

### Metrics with no independent oracle (deliberate gaps)

A few metrics are **method-specific scores or process metrics with no external equivalent**, so
`ref/tool_recommendations.yaml` deliberately carries no `top_considered` row for them — a false
oracle would be worse than an honest gap:

| Metric | Why no oracle |
|---|---|
| `T09_phaser_tfz`, `T09_llg` | Phaser translation-function Z / log-likelihood gain are Phaser-internal scores; MoRDa/MOLREP/ARCIMBOLDO produce their own, non-comparable scores. MR *success* is instead cross-checked at the outcome level via `T09_translation_rotation` (independent superposition to the deposited pose) and `T09_post-mr_r-free` (REFMAC5). |
| `T08_em_placement_llg` | `phenix.em_placement` log-likelihood is PHENIX-specific; placement is cross-checked via `T08_placement_cc` (ChimeraX/Situs) and `T08_rmsd_to_deposited_position` instead. |
| `T09_time-to-solution` | A wall-clock process metric measured directly by the harness, not a structural quantity to cross-check. |

## Build notes (for reproducibility)

**TM-align** — single C++ source. `malloc.h` include must be commented out on macOS:
```bash
mkdir -p $HOME/tools/tmalign && cd $HOME/tools/tmalign
curl -sL -o TMalign.cpp https://zhanggroup.org/TM-align/TMalign.cpp
sed -i.bak 's|^#include <malloc.h>|// #include <malloc.h>|' TMalign.cpp
c++ -O3 -ffast-math -o TMalign TMalign.cpp
```

**probe** — use the default `Makefile`, NOT `Makefile.macOSX` (the latter hardcodes a stale 10.8 SDK):
```bash
cd $HOME/tools && git clone --depth=1 https://github.com/rlabduke/probe.git probe-src
cd probe-src && make
```

**reduce** — CMake build:
```bash
cd $HOME/tools && git clone --depth=1 https://github.com/rlabduke/reduce.git reduce-src
cd reduce-src && mkdir build && cd build && cmake .. && make
```

**Servalcat** — conda-forge:
```bash
mamba create -n cryst-oracles -c conda-forge python=3.11 servalcat
```

> **Two gemmi gotchas, both found by running it** (`ref/research/tolerance_benchmark_bond_rmsd.md`,
> `ref/research/tolerance_benchmark_r_offset.md`):
> - The Homebrew build links against `libz-ng`, which is **not** pulled in as a dependency. Without
>   `brew install zlib-ng` every `gemmi` invocation dies in dyld — the binary is on PATH and still
>   unusable, so "installed" is not the same as "runnable" here.
> - `gemmi rmsz` prints **rmsZ** (unitless) and **rmsD** (Å) on separate lines. Only rmsD compares
>   to a PHENIX RMSD; reading the rmsZ line instead is a units error, not a disagreement.
> - The Python module is separate from the CLI (`pip install gemmi`); the CLI recipes above do not
>   need it, but `scripts/bench_t06_r_offset.py` does.

**gemmi** — Homebrew (the `brewsci/bio` tap):
```bash
brew install brewsci/bio/gemmi
```
