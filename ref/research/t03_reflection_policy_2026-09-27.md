# T03 applicability and retained-reflection policy — 2026-09-27

Issue #764 is a rubric-definition change, not a new refinement run or a rewrite of
issued EVAL/QDS records. The user approved keeping missing deposited R-free
unevaluable even when REFMAC5 exists, and rejecting unexplained loss from an
input-defined observation domain instead of grading only surviving HKLs.

## Policy and scope

The registry §3 policy is authoritative. Select the input F/SIGF/flag columns
explicitly. Retain finite F, including zero and negative values, with finite
positive SIGF. Negative amplitudes are disclosed quality diagnostics, not an
excuse to drop rows. Missing/nonintegral/out-of-encoding flags on otherwise
eligible input, duplicate/nonintegral HKLs, ambiguous columns, or unmatched
crystallographic/indexing context make the audit unevaluable. Do not silently
exclude those defects and pass a remaining subset.

The helper reports complete-input losses, surviving keys made unusable, changed
flags or F/SIGF, and newly usable output keys. None automatically passes.
Nonfinite observations/nonpositive uncertainty and padding are counted separately.
A preservation result is only an unchanged-input integrity observation, not an
R-factor calculation or a complete T03 grade. Selected F/SIGF must have the same
declared MTZ dataset association; the selected flag association is also retained.
Column labels and associations are interpreted only within the pinned file, not
as cross-file dataset identities.

The new helper reuses the narrow stdlib MTZ reader/context checks in
`scripts/audit_1sar_retained_evidence.py`. It adds no external scientific tool.
That existing script compares selected F/SIGF in archived input with the saved
T13 ctruncate MTZ, including NaN payloads; it does **not** check PHENIX refinement
output retention or R-free flags. Its source and retained JSON remain unchanged.

### Independently reviewed format admission (#833, #834)

Review findings were filed and independently reproduced before these fixes:
#833 showed that ignoring a numeric `VALM` sentinel could report a missing
observation as a retained negative amplitude; #834 showed that ignoring the
third `NCOL` field admitted positive-batch metadata as merged data.
The [CCP4 MTZ format](https://ftp.ccp4.ac.uk/ccp4/6.3.0/unpacked/html/mtzformat.html)
defines the missing-value indicator, the batch-count field, and unmerged
`BATCH` / `M/ISYM` column semantics.

The new helper now requires exactly one literal `VALM NAN` record and exactly
one complete `NCOL ncols nrows nbatches` record with positive dimensions and
zero batches. It rejects absent, duplicate, malformed, or numeric `VALM`,
incomplete/duplicate/malformed `NCOL`, any `BATCH` header, column types B/Y,
and column names `BATCH` or `M/ISYM`, on either side before observation
selection. It does not guess a default when `VALM` is absent, implement finite
sentinel conversion, or expand into a general unmerged MTZ parser.

Read-only header inspection confirms that all seven archived MTZ members have
one explicit `VALM NAN` and zero batches: input `NCOL 16 7248 0`, each output
`NCOL 16 7262 0`. None uses the rejected unmerged markers. Thus the admission
checks leave the actual retained-byte recount below unchanged. The original
audit reader remains untouched.

## New read-only recount of existing bytes

Source archive:
`data/coscientists/openscientist/cdba2c07-daff-4f60-ae96-12452b3a5fbb_artifacts.zip`.

Input member: `data/1sar.mtz`, selected columns
`F-obs,SIGF-obs,R-free-flags`. The input SHA-256 is
`f36d5fe685a3e524e8809d17d19ce12073acdf339eba2cfd3b0347a818850ab2`.

The input has 7248 raw rows: 7228 finite-F/positive-finite-SIGF observations with
valid flags, including eleven F=0 rows; twenty rows have nonfinite observations.
There are no negative F values in this concrete input.

Every one of the six archived outputs (`1sar_refined.mtz`, `1sar_round2.mtz`,
`1sar_round3.mtz`, `1sar_final.mtz`, `1sar_round5.mtz`, `1sar_round6.mtz`,
all under `data/`) contains 7262 raw rows but only 7217 eligible observations.
Each preserves every original HKL and flag, adds fourteen all-NaN F/SIGF/flag rows,
and invalidates exactly the eleven originally finite zero-amplitude observations.
No newly eligible output key appears. Padding explains the raw-count increase,
not those eleven losses. Equal positive-F counts would conceal them.

The old September narrative's 7217 “positive-F” count is not the new input-led
domain. This recount does not retroactively alter that narrative or any issued
EVAL/QDS, and does not assign an issued T03 pass_status. Deposition applicability
remains independently unresolved: `data/pdb_mtz/1sar_deposited.pdb:48` explicitly
records `FREE R VALUE : NULL`.

## Read-only replay

For two existing local MTZ paths, the CLI writes JSON only to stdout:

```bash
uv run --locked -- python -B scripts/t03_reflection_retention.py input.mtz output.mtz \
  --input-columns F-obs,SIGF-obs,R-free-flags \
  --output-columns F-obs,SIGF-obs,R-free-flags --flag-values 0,1 --free-value 1
```

Its exit codes distinguish preserved (0), not preserved (1), and unevaluable
input/context (2). These are audit outcomes, not QDS pass_status values.

From the repository root after integrating the proposal:

```bash
uv run --locked -- python -B - <<'PY'
import hashlib
import json
from pathlib import Path
import sys
import zipfile
sys.path.insert(0, str(Path.cwd() / "scripts"))
from audit_1sar_retained_evidence import ARCHIVE
from t03_reflection_retention import audit_mtz_retention

labels = ("F-obs", "SIGF-obs", "R-free-flags")
print("archive_sha256", hashlib.sha256(ARCHIVE.read_bytes()).hexdigest())
with zipfile.ZipFile(ARCHIVE) as archive:
    before = archive.read("data/1sar.mtz")
    for member in sorted(archive.namelist()):
        if member.endswith(".mtz") and member != "data/1sar.mtz":
            result = audit_mtz_retention(
                before, archive.read(member),
                input_labels=labels, output_labels=labels,
                flag_values={0, 1}, free_value=1,
            )
            print(member, json.dumps(result, sort_keys=True, allow_nan=False))
PY
```

The encoding and free value above are explicit replay parameters, not inferred
from the output or a claim of recovered historical invocation settings.
The retention result compares identical original flag values and does not depend
on which of the two valid partitions is called free. The helper reports per-file
digests, selected column associations, reason counts, and all affected HKLs.

## Tests and limitations

Synthetic tests cover missing deposition despite REFMAC availability, valid zero
and negative amplitudes, padding, missing rows despite agreeing shared flags,
same-count replacement, zero-to-NaN loss, changed flags/observations, invalid flags,
nonpositive uncertainty, ambiguous HKLs, changed context, and empty domains.
Metadata regressions cover both input and output, finite missing-value sentinels,
missing/duplicate/malformed admission records, unmerged headers/columns even
with zero declared batches, and CLI exit 2 with no result JSON.
The retained-byte regression independently expects the observed six-output counts.
Registry/driver regressions reject the original under-specified guidance.

This deliberately does not implement reindexing, symmetry expansion, intensity
conversion, or preprocessing exceptions. Unsupported inputs fail closed. The
helper emits no MeasurementValue, rewrites no evidence, and supplies no new
empirical threshold.

Focused validation passed 21 tests, the 24-entry driver/registry guard, and
repository-configured Ruff. In-memory negative controls produce two assertion
failures when the helper is changed to a surviving-intersection domain and six
when REFMAC is allowed to substitute for missing/invalid deposition evidence,
with zero errors in both cases. The original registry fails both new policy
read-pattern checks. No scientific executables or full gate were run here.
Running the five new metadata tests against the pre-#833/#834 helper produces
45 assertion failures and zero errors. The revised scratch proposal still needs
the parent's final independent re-review and integration validation.
