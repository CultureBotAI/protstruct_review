# Before/After Refinement Assessment Case Study: Retained 1SAR X-Ray Run and 22-Structure Control Cohorts (`2026-10-18`)

- **Date:** `2026-10-18`
- **Executable implementation:** `scripts/assess_refinement.py`
- **Machine-readable output:** `ref/research/data/refinement_assessment_1sar_and_controls_2026-10-18.json`
- **Regression test suite:** `scripts/test_assess_refinement.py`
- **Primary retained inputs:**
  - `data/coscientists/openscientist/cdba2c07-daff-4f60-ae96-12452b3a5fbb_artifacts.zip` (`sha256: 9fc5352284b7ffa7763c633a3eb4d3d0db96b8c25a1be9bcea361722d2c53054`)
  - `data/pdb_mtz/1sar_deposited.pdb` (`sha256: e60e5db6c7eb554a3ac4e184bdf7cbb7d69b682e287579bdcf5f8bf279d51f86`)
  - `data/coscientists/openscientist/EVAL_1sar_cdba2c07_2026-09-23.yaml`
  - `data/coscientists/openscientist/QDS_1sar_cdba2c07_2026-09-23.yaml`
  - `data/coscientists/openscientist/retained_evidence_2026-09-23/coordinate_and_t13_audit.json`
  - `ref/research/data/negative_control_round3_bench.json` (`sha256: 3635bd878d160c770594c2c5ed92a1139dbbd8d63daa28a48aa249656d7f6dee`)
  - `ref/research/data/negative_control_round4_recover.json` (`sha256: dee4b3994c81ec2e5aecfe86569c36b720f8fd0a9c04581dc96585edb275afdf`)
  - `ref/research/data/negative_control_round10_recover.json` (`sha256: 1c6e710e87bb08c23d77b1fa3a7aea2fe18a136b00cec6d35d40e2d171b78bb7`)

---

## 1. Design: Separating Three Distinct Assessment Questions

Earlier evaluation artifacts and ad-hoc negative-control scripts conflated solver conventions, absolute model quality, and refinement progress into single composite flags (`DEGRADED` / `FIT-DEGRADED` / `not-degraded`). `scripts/assess_refinement.py` separates every before/after refinement assessment into three orthogonal questions:

1. **Question 1 — Implementation agreement (`implementation_agreement`):** *Do independent implementations agree on the same observable when given the exact same model and reflection inputs?*
   - Isolates bulk-solvent masking, scaling conventions, reflection-flag handling, covalent restraint dictionaries (`CCP4/Monomer Library` vs `cctbx/GeoStd`), riding-hydrogen placement (`Reduce` vs internal), and secondary-structure boundary definitions (`mkdssp` H-bond energy vs `biotite` P-SEA distance/torsion criteria).
2. **Question 2 — Final-model quality support (`final_model_quality_support`):** *What supports the final model's quality for its intended use?*
   - Evaluates the packaged output model (`data/1sar_final.pdb`) on experimental data completeness/anomalies (`T13`), crystal-lattice fit (`T03`), covalent and conformational stereochemistry (`T05`), fold/secondary-structure conservation (`T01`, `T15`), and quaternary dimer interface integrity (`T16`), with explicit resolution and applicability context (packaged `REMARK 3` header and `data/1sar.mtz` reflection range `49.972–2.500 Å`, `1.5–2.5 Å` medium-resolution bin; deposited `1SAR` reference at `1.80 Å`).
3. **Question 3 — Change relative to input (`change_relative_to_input`):** *What improved or regressed relative to the actual starting model?*
   - Compares the packaged output directly against the actual input (`data/1sar.pdb` and `data/1sar.mtz`), quantifying reflection-set retention, unsuperposed and Kabsch-superposed coordinate shifts, $B$-factor redistributions, solvent/ligand/ion inventory changes, and paired before/after deltas on $R_{\text{work}}$, $R_{\text{free}}$, clashscore, Ramachandran outliers, and Holton geometry energy.

### Uncalibrated Verdict Policy

In accordance with `ref/quality_reporting.md`, `scripts/assess_refinement.py` does **not** emit uncalibrated `PASS` / `WARN` / `FAIL` verdicts when `pass_criterion_bindings` is empty (`[]`). When `pass_criterion_bindings: []`, `resolve_verdict_status()` unconditionally returns `assessment_verdict_status: "informational"`. A non-informational verdict (`"pass"`, `"fail"`, or `"unevaluable"`) is produced only when an explicit caller-supplied `pass_criterion_bindings` list is bound to concrete metric paths and thresholds.

---

## 2. Case Study: Retained OpenScientist 1SAR X-Ray Refinement (`cdba2c07`)

### 2.1 Provenance Inventory and Packaging Discrepancy Audit

| Artifact Role | Path / Archive Member | SHA-256 | Non-H Atoms | Protein Atoms / Residues | Waters (`HOH`) | Non-Water Heterogens | Header / Evaluated $R_{\text{work}} / R_{\text{free}}$ |
|---|---|---|---:|---:|---:|---|---|
| Retained archive | `data/coscientists/openscientist/cdba2c07-daff-4f60-ae96-12452b3a5fbb_artifacts.zip` | `9fc5352284b7ffa7763c633a3eb4d3d0db96b8c25a1be9bcea361722d2c53054` | — | — | — | — | — |
| Actual starting model | `data/1sar.pdb` (in zip) | `6b34c5d0dec6647df20eae9021ff7d511d6dedc03b4349c0b634d8e5b1f869e4` | `1,498` | `1,488` (`192` res: `96` A, `96` B) | `0` | `A:97:SO4` (5 atoms, mean $B = 15.99\text{ \AA}^2$), `B:97:SO4` (5 atoms, mean $B = 43.16\text{ \AA}^2$) | None (`REMARK 3` absent; `phenix` `0.3334 / 0.3956`) |
| Packaged final model | `data/1sar_final.pdb` (in zip) | `8cbc1650f8be5a3833f98833fa514ec7d490c2c3bb9aa930413abac05e2a510b` | `1,641` | `1,488` (`192` res: `96` A, `96` B) | `146` (mean $B = 20.76\text{ \AA}^2$, median $19.69\text{ \AA}^2$) | `A:97:SO4` (5 atoms, mean $B = 17.59\text{ \AA}^2$), `A:98:CA` (1 atom, $B = 42.73\text{ \AA}^2$), `B:98:NA` (1 atom, $B = 22.85\text{ \AA}^2$) | `0.1563 / 0.2114` header (`0.1564 / 0.2116` `phenix`, round 4) |
| Retained round 5 | `data/1sar_round5.pdb` (in zip) | `eb726f377ff6abfdba66ef5b311d85a9899fb5c20fd349c36e2c2bd92014c939` | `1,622` | `1,488` (`192` res: `96` A, `96` B) | `127` | `A:97:SO4` (5 atoms), `A:98:CA` (1 atom), `B:98:NA` (1 atom) | `0.1551 / 0.2143` header (`0.1555 / 0.2104` `phenix`) |
| Retained round 6 | `data/1sar_round6.pdb` (in zip) | `fcdf53d2224d6c4e369b53aa2ff53e04258b775b80172b5be2d8cf8410c21c60` | `1,648` | `1,488` (`192` res: `96` A, `96` B) | `152` | `A:97:SO4` (5 atoms), `B:97:SO4` (5 atoms), `B:98:NA` (1 atom) | `0.1544 / 0.2104` header (`0.1539 / 0.2068` `phenix`) |
| Log-reported round 7 | Absent from zip (`claude_iterations.log:510, :752`) | — | `1,654` claimed | `192` res claimed | `159` claimed | Restored `B:97:SO4` (`2 SO4 + CA + NA`) claimed | `0.1488 / 0.1989` logged (`0.149 / 0.199` report) |
| Deposited PDB reference | `data/pdb_mtz/1sar_deposited.pdb` | `e60e5db6c7eb554a3ac4e184bdf7cbb7d69b682e287579bdcf5f8bf279d51f86` | `1,636` | `1,488` (`192` res: `96` A, `96` B) | `138` | `A:97:SO4` (5 atoms), `B:97:SO4` (5 atoms) | `R = 0.172` (work+test), `FREE R VALUE : NULL` |

**Packaging discrepancy finding:** The OpenScientist trajectory log (`claude_iterations.log:510, :752`) and narrative report claim a **round-7** final model (`R_work = 0.1488`, `R_free = 0.1989`, rounded to `0.149 / 0.199` in the report; `159` waters, `1,654` heavy atoms, restored `B:97:SO4`). Byte-level inspection proves that `data/1sar_final.pdb` is actually the **round-4** model (`REMARK 3 R VALUE (WORKING SET) : 0.1563`, `FREE R VALUE : 0.2114`; `phenix.model_vs_data` `0.1564 / 0.2116`; `146` waters, `1,641` heavy atoms, `A:97:SO4`, `A:98:CA`, `B:98:NA`), while intermediate rounds 5 and 6 exist separately in the zip (`data/1sar_round5.pdb` header `0.1551 / 0.2143`, `phenix.model_vs_data` `0.1555 / 0.2104`; `data/1sar_round6.pdb` header `0.1544 / 0.2104`, `phenix.model_vs_data` `0.1539 / 0.2068`) and the round-7 coordinate file is absent from the archive. All independent oracle measurements in `scripts/assess_refinement.py` are anchored to the actual packaged bytes of `data/1sar_final.pdb` (`sha256: 8cbc1650...`).

---

### 2.2 Question 1: Do Implementations Agree on the Same Observable? (`data/1sar_final.pdb`)

#### `T03` Reciprocal-Space $R$-Factors Across Solvers

| Implementation | Role | $R_{\text{work}}$ | $R_{\text{free}}$ | $R_{\text{free}} - R_{\text{work}}$ | $n_{\text{work}}$ | $n_{\text{free}}$ | Notes |
|---|---|---:|---:|---:|---:|---:|---|
| `gemmi sfcalc` (`1sar.mtz`) | Primary fast diagnostic | `0.1622` | `0.2136` | `0.0515` | `6,494` | `723` | Direct bulk-solvent/anisotropic scaling on input `1sar.mtz` |
| `gemmi sfcalc` (`1sar_final.mtz`) | Cross-MTZ check | `0.1622` | `0.2136` | `0.0515` | `6,494` | `723` | Identical to $10^{-6}$ on positive-$F$ reflections |
| `phenix.model_vs_data` (`1.21.2_5419`) | Primary full solver | `0.1564` | `0.2116` | `0.0552` | `6,494` | `723` | Matches `REMARK 3` header (`0.1563 / 0.2114`) within `0.0002` |
| `REFMAC5` (`5.8.0430`, 0 cycles) | Orthogonal CCP4 solver | `0.1693` | `0.2128` | `0.0435` | `6,494` | `723` | Orthogonal CCP4 bulk-solvent mask |
| `Servalcat` (`0.4.101`, `sigmaa`) | Orthogonal diagnostic | `0.1705` | `0.2209` | `0.0504` | `6,855` | `362` | `FREE=0` convention splits free set differently (`n_free = 362`) |

- Across the three solvers using the identical `723`-reflection free set (`gemmi sfcalc`, `phenix.model_vs_data`, and `REFMAC5`), $R_{\text{free}}$ spans `0.2116` to `0.2136` (`spread = 0.0020`), and $R_{\text{work}}$ spans `0.1564` to `0.1693` (`spread = 0.0129`) due to bulk-solvent masking differences.
- `Servalcat` reports `R_free = 0.2209` (`spread = 0.0093` across all four tools) because its `FREE=0` flag interpretation selects `362` free reflections rather than `723`.

#### `T05` Stereochemical Agreement (`MolProbity` vs `mmtbx` vs `REFMAC5`)

- **All-atom clashscore:** Standalone `MolProbity` (`4.2`, with fresh `Reduce` hydrogen placement) reports `3.63` (`11` clashes $\ge 0.4\text{ \AA}$), whereas `mmtbx.validation_summary` reports `3.13` (`|\Delta| = 0.50` clashscore units).
- **Covalent bond/angle RMSDs:** `REFMAC5` (0 cycles, CCP4 Monomer Library) reports bond RMSD `0.0105 Å` (`RMSZ = 0.884`) and angle RMSD `1.4957°` (`RMSZ = 0.864`), whereas `mmtbx.validation_summary` (cctbx GeoStd) reports bond RMSD `0.007 Å` and angle RMSD `0.85°` (`|\Delta| = 0.0035 Å` and `0.6457°`). Both dictionaries agree that covalent geometry is well within normal target bounds (`RMSZ < 1.0`).

#### `T15` Secondary-Structure Assignment Agreement (`mkdssp` vs `biotite`)

- `mkdssp` (`4.4.0`, 8-state reduced to 3-state) assigns `29` H (`15.10%`), `43` E (`22.40%`), and `120` C (`62.50%`) across `192` residues (`37.50%` H+E).
- `biotite.structure.annotate_sse` (`1.6.0`, P-SEA `Cα` criteria) assigns `28` `a` (`14.58%`), `39` `b` (`20.31%`), and `125` `c` (`65.10%`) (`34.90%` H+E).
- Residue-by-residue Q3 agreement is `169 / 192` (`88.02%`), with `23` boundary differences at helix/strand termini (`11` in chain A, `12` in chain B).

---

### 2.3 Question 2: What Supports the Final Model's Quality for Its Intended Use?

1. **Experimental Reflection Data (`T13` on `data/1sar.mtz`):**
   - Space group `P 21 21 21` (`a = 64.897 Å, b = 78.323 Å, c = 38.792 Å, α = β = γ = 90°`), retained dataset resolution range `49.972–2.500 Å` (`7,228` non-`NaN` reflections out of `7,248` stored rows; packaged `REMARK 3` header also reports `2.50 Å`, whereas deposited native `1SAR` is at `1.80 Å`).
   - Completeness: `99.38%` (historical `phenix.model_vs_data`), free-$R$ fraction `10.00%` (`723 / 7,228`).
   - Wilson $B = 14.542\text{ \AA}^2$ (fitted $\sigma = 21.119$, `ctruncate.log`); Padilla-Yeates $L$-test $\langle |L| \rangle = 0.505$, acentric second moment $\langle I^2 \rangle / \langle I \rangle^2 = 1.968$, twin fraction `0.03` ($L$-test) / `0.02` (moments), `0` twin operators found; no translational NCS (`tncs_flag: false`); mild anisotropy (eigenvalues `10.5625, 17.8813, 14.6262 Å²`, $\Delta B_{\text{aniso}} = 7.3188\text{ \AA}^2$).
   - **Data anomaly:** `ctruncate` flags one of four ice-ring sensitive shells at `3.44 Å` (`mean I/sigma Z-score = 5.21`, completeness `1.00`, intensity ratio `1.17`).
   - **Inapplicable clause (`aimless`):** Running `aimless` on `data/1sar.mtz` is inapplicable (`not_applicable_merged_input`) because `1sar.mtz` contains already-merged structure-factor amplitudes (`F-obs, SIGF-obs`), not unmerged intensities.
2. **Reciprocal-Space Fit (`T03`):**
   - `phenix.model_vs_data` $R_{\text{work}} = 0.1564$, $R_{\text{free}} = 0.2116$, gap `0.0552` (`723` free reflections).
   - Deposited `1SAR` (`1991`) has `REMARK 3 FREE R VALUE : NULL` (`R VALUE (WORKING + TEST SET) : 0.172`), so any comparison against a deposited $R_{\text{free}}$ is recorded as `deposition_clause: "unevaluable"`.
3. **Stereochemistry (`T05`):**
   - Ramachandran (`mmtbx` Top8000): `98.40%` favored (`185/188` non-terminal residues), `1.06%` allowed, `0.53%` outlier (`1` residue: `1sar:A:39` Asn39 (`Asn A 39`) in a surface loop).
   - Rotamer outliers: `4.88%` (`8/164` sidechains: `A:17:TYR`, `A:31:SER`, `A:42:LYS`, `B:12:SER`, `B:41:GLU`, `B:54:GLU`, `B:64:THR`, `B:86:ARG`); `Cβ` deviations: `0`; `cis`/`twisted` non-proline peptides: `0` (`4` `cis`-prolines: `A:27`, `A:60`, `B:27`, `B:60`).
   - All-atom clashscore: `3.63` (`MolProbity`) / `3.13` (`mmtbx`); MolProbity composite score: `1.63`.
   - Holton `refinement_check.py` overall geometry energy ratio: `1.33 σ` (`bonds = 0.89`, `angles = 1.07`, `torsions = 1.54`, `rama = 1.15`, `chiral = 0.56`, `planes = 1.03`, `nonbond = 1.88`).
4. **Fold and Quaternary Interface Conservation vs Deposited `1SAR` (`T01`, `T15`, `T16`):**
   - Monomer Kabsch $C_\alpha$ RMSD vs `data/pdb_mtz/1sar_deposited.pdb`: `0.191 Å` on chain A (`96` $C_\alpha$) and `0.180 Å` on chain B (`96` $C_\alpha$).
   - Dimer interface (`DockQ v2.1.3` vs `data/pdb_mtz/1sar_deposited.pdb`): native mapping `AB:AB` achieves `DockQ = 0.9445` (`High`, `fnat = 0.960`, `fnonnat = 0.143`, `iRMSD = 0.155 Å`, `LRMSD = 0.340 Å`, `F1 = 0.906`); swapped mapping `AB:BA` scores `0.0063` (confirming asymmetric crystal-packing contact).

---

### 2.4 Question 3: What Improved or Regressed Relative to the Actual Input (`data/1sar.pdb` -> `data/1sar_final.pdb`)?

#### Reflection-Set Retention Audit (`data/1sar.mtz` -> `data/1sar_final.mtz`)

| Metric | `data/1sar.mtz` (Input) | `data/1sar_final.mtz` (Packaged Output) | Audit Status / Interpretation |
|---|---:|---:|---|
| Total HKL rows | `7,248` (`20` all-`NaN`) | `7,262` (`45` `NaN` in `F-obs`) | `+14` all-`NaN` HKL rows appended |
| Non-`NaN` (`F-obs`) reflections | `7,228` | `7,217` | `-11` reflections (`audit_status: "not_preserved"`) |
| Positive-$F$ work reflections (`R-free-flags == 0`, $F > 0$) | `6,494` | `6,494` | `100%` preserved (`max |\Delta F| = 3.64 \times 10^{-5}`) |
| Zero-$F$ work reflections (`R-free-flags == 0`, $F = 0$) | `11` | `0` (`NaN`) | `11` zero-$F$ work reflections converted to `NaN` by PHENIX |
| Free-$R$ reflections (`R-free-flags == 1`, $F > 0$) | `723` | `723` | `100%` preserved (`0` free reflections lost or swapped) |

Because `11` zero-$F$ work reflections were invalidated to `NaN` (`7,228` -> `7,217`), `audit_mtz_retention()` flags `audit_status = "not_preserved"`, while confirming that all `723` free reflections and all `6,494` positive-$F$ work reflections are intact and yield identical `gemmi sfcalc` $R_{\text{work}} = 0.162165$ and $R_{\text{free}} = 0.213638$ on both MTZ files.

#### Coordinate, $B$-Factor, and Inventory Shifts (`data/1sar.pdb` -> `data/1sar_final.pdb`)

- **Shared heavy atoms (`1,493` matched atoms: `1,488` protein + `5` in `A:97:SO4`):**
  - Unsuperposed coordinate RMSD: `0.8460 Å` (mean shift `0.6356 Å`, median `0.4596 Å`, 95th percentile `2.1843 Å`, max `2.9227 Å` at `B:77:GLN:NE2`).
  - Shared $C_\alpha$ atoms (`192` residues): unsuperposed RMSD `0.4229 Å`, Kabsch-superposed RMSD `0.4191 Å` (mean shift `0.3791 Å`, median `0.3525 Å`, max `0.9549 Å` at `A:34:GLY:CA`; chain A unsuperposed RMSD `0.4168 Å` / Kabsch `0.4102 Å`, chain B unsuperposed RMSD `0.4288 Å` / Kabsch `0.4211 Å`).
  - $B$-factor shift on `1,493` shared heavy atoms: mean $\Delta B = +0.1932\text{ \AA}^2$, median $\Delta B = -1.480\text{ \AA}^2$.
- **Solvent and ligand inventory changes:**
  - Waters (`HOH`): `0 -> 146` (`+146` waters added, mean $B = 20.759\text{ \AA}^2$).
  - Heterogens removed: `B:97:SO4` (`5` atoms, input mean $B = 43.164\text{ \AA}^2$).
  - Heterogens added: `A:98:CA` (`1` atom, $B = 42.73\text{ \AA}^2$) and `B:98:NA` (`1` atom, $B = 22.85\text{ \AA}^2$).
  - Heterogens retained: `A:97:SO4` (`5` atoms, mean $B$: `15.992 -> 17.588\text{ \AA}^2`, unsuperposed RMSD `0.2179 Å`).

#### Before/After Quality Deltas (`data/1sar.pdb` -> `data/1sar_final.pdb`)

| Observable | Starting Model (`data/1sar.pdb`) | Packaged Final (`data/1sar_final.pdb`, R4) | Retained Round 6 (`data/1sar_round6.pdb`) | Delta (Start -> Packaged R4) | Direction |
|---|---:|---:|---:|---:|---|
| `phenix` $R_{\text{work}}$ | `0.3334` | `0.1564` (`0.1563` header) | `0.1539` (`0.1544` header) | `-0.1770` | Improved |
| `phenix` $R_{\text{free}}$ | `0.3956` | `0.2116` (`0.2114` header) | `0.2068` (`0.2104` header) | `-0.1840` | Improved |
| `mmtbx` Clashscore | `31.66` | `3.13` (`3.63` MolProbity) | `4.64` | `-28.53` | Improved |
| Ramachandran outliers (`%`) | `9.04%` (`17/188`) | `0.53%` (`1/188`) | `0.53%` (`1/188`) | `-8.51 pp` | Improved |
| Ramachandran favored (`%`) | `78.19%` | `98.40%` | `98.40%` | `+20.21 pp` | Improved |
| Rotamer outliers (`%`) | `19.51%` | `4.88%` (`8/164`) | `1.83%` (`3/164`) | `-14.63 pp` | Improved |
| Holton geometry energy (`σ`) | `3.32` | `1.33` | `1.39` | `-1.99 σ` | Improved |

---

## 3. Evaluation Across the 5 Retained 22-Structure Control Cohorts

To verify that separating Question 1 (implementation agreement), Question 2 (final-model quality support), and Question 3 (change relative to input) generalizes beyond a single target, `scripts/assess_refinement.py` evaluates all five 22-structure control cohorts from `ref/research/data/negative_control_round3_bench.json`, `ref/research/data/negative_control_round4_recover.json`, and `ref/research/data/negative_control_round10_recover.json`:

| Cohort ID | Source File / State | Targets (`n`) | REFMAC-Evaluable / Two-Path-Only | Q1: Median $\|\Delta R_{\text{free}}^{\text{phenix}} - \Delta R_{\text{free}}^{\text{gemmi}}\|$ | Q1: Median $\|\Delta R_{\text{free}}^{\text{phenix}} - \Delta R_{\text{free}}^{\text{refmac}}\|$ | Q1: Conflict Targets | Q2: Median Post $R_{\text{free}}$ (`phenix` / `gemmi` / `refmac`) | Q2: Median Post Clashscore | Q3: Median $\Delta R_{\text{free}}^{\text{phenix}}$ (Improved / Regressed) | Q3: Median $\Delta$ Clashscore | Q3: Median All-Residue Shift (`Å`) | Diagnostic Flags (`F-data` / `F-geom` / `F-prot` / `F-shift`) |
|---|---|---:|---:|---:|---:|---:|---|---:|---|---:|---:|---|
| `unchanged_null` | `round3_bench.json` (`subject="null"`) | `22` | `19 / 3` (`9YGW, 8R5K, 8QXQ`) | `0.0007` (max `0.0019`) | `0.0024` (max `0.0336`) | `2` (`8RFF`, `9TXE`) | `0.1459 / 0.1499 / 0.1676` | `1.045` | `+0.0035` (`4 / 18`) | `-0.095` | `0.0139` | `3 / 0 / 0 / 0` |
| `damaged_sa` | `round3_bench.json` (`subject="sa"`) | `22` | `19 / 3` | `0.0008` (max `0.0045`) | `0.0094` (max `0.0477`) | `2` | `0.1679 / 0.1702 / 0.1845` | `1.275` | `+0.0209` (`0 / 22`) | `0.000` | `0.0244` (mean `0.1780`, max `1.6486`) | `18 / 1 / 0 / 2` |
| `damaged_dynamics` | `round4_recover.json` (`state="perturbed"`) | `22` | `19 / 3` | `0.0011` (max `0.0144`) | `0.0256` (max `0.0636`) | `9` | `0.3906 / 0.3922 / 0.3941` | `7.555` | `+0.2629` (`0 / 22`) | `+6.270` | `0.2465` | `22 / 13 / 2 / 22` |
| `recovered_unprotonated_solvent` | `round4_recover.json` (`state="recovered"`) | `22` | `19 / 3` | `0.0007` (max `0.0020`) | `0.0059` (max `0.0419`) | `1` | `0.1601 / 0.1633 / 0.1825` | `1.675` | `+0.0188` (`0 / 22`) | `+0.315` | `0.0435` | `22 / 1 / 0 / 0` |
| `recovered_protonated_ordered_solvent` | `round10_recover.json` (`state="osol_h"`) | `22` | `21 / 1` (`9YGW`) | `0.0009` (max `0.0045`) | `0.0021` (max `0.0316`) | `3` | `0.1482 / 0.1508 / 0.1792` | `2.615` | `+0.0063` (`8 / 14`) | `+0.880` | `0.0422` | `9 / 0 / 2 / 0` |

### Key Cross-Cohort Findings

1. **Unchanged control invariance and solver-disagreement isolation (`unchanged_null`, `n=22`):**
   - `phenix.model_vs_data` and `gemmi sfcalc` agree tightly on before/after $\Delta R_{\text{free}}$ (`median |d_phenix - d_gemmi| = 0.0007`, max `0.0019`), whereas `REFMAC5` (`19/22` evaluable; `3/22` two-path-only targets `9YGW`, `8R5K`, `8QXQ`) exhibits a smaller median delta (`+0.0018` vs `+0.0035`) and records solver-disagreement notes on `2/22` targets (`8RFF` on `F-data` where PHENIX/gemmi exceed $+0.005$ while REFMAC is $+0.0020$, and `9TXE` on `F-geom` where cctbx clashscore/rotamer deltas stand down against improved REFMAC `zBOND = -0.043`). Keeping Question 1 separate from Question 3 prevents solver-convention differences from being misclassified as physical model changes.
2. **Damaged control sensitivity (`damaged_sa` and `damaged_dynamics`, `n=22`):**
   - Simulated-annealing perturbation (`damaged_sa`) produces `22/22` $R_{\text{free}}$ regressions (`median d_phenix = +0.0209`, `18/22` `F-data` flags, `2/22` `F-shift` flags).
   - Controlled Cartesian-dynamics perturbation (`damaged_dynamics`, `stop_at_diff = 0.5 Å`) triggers `22/22` `F-data` flags (`median d_phenix = +0.2629`, `median d_gemmi = +0.2656`, `median d_refmac = +0.2247`), `22/22` `F-shift` flags (`median all-residue shift = 0.2465 Å`), and `13/22` `F-geom` flags (`median clashscore delta = +6.27`, `median Ramachandran favored delta = -5.695 pp`), while also surfacing `9/22` targets where cctbx local geometry worsens (`clashscore`/`Ramachandran`/`rotamers`) even as REFMAC `zBOND` improves or stays neutral (`median d_zbond = 0.000`).
3. **Recovery refinement and protonation/ordered-solvent contrast (`round 4` vs `round 10`, `n=22`):**
   - Unprotonated default recovery refinement (`recovered_unprotonated_solvent`, round 4) recovers coordinates to `median shift = 0.0435 Å` from deposited (`0/22` `F-shift` flags) and reduces `F-geom` flags from `13/22` to `1/22`, but leaves a systematic $R_{\text{free}}$ offset (`median d_phenix = +0.0188`, `22/22` `F-data` flags) because riding hydrogens and ordered-solvent updates were omitted.
   - Adding `phenix.ready_set` riding hydrogens followed by `ordered_solvent=True` (`recovered_protonated_ordered_solvent`, round 10) cuts the median $R_{\text{free}}$ offset threefold (`median d_phenix = +0.0063`, `median d_gemmi = +0.0080`, `median d_refmac = +0.0073`), reduces `F-data` flags from `22/22` to `9/22`, and improves $R_{\text{free}}$ below the deposited baseline on `8/22` targets (`0/22` in round 4) while maintaining tight coordinate recovery (`median all-residue shift = 0.0422 Å`).
