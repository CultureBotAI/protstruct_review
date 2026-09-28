# Refinement cache integrity — 2026-09-27

Engineering prerequisite for #777 / the pending #760 cross-version experiment.
Reviewed baseline: `f9565347`. No PHENIX, CCP4 or gemmi scientific executable was
run. No historical measurements, thresholds, registrations or issued QDS records
were changed. This is code verification, not a cross-version scientific result.

## Contract and scope

Both refinement runners now bind reuse to declared input bytes, exact arguments,
configured/resolved executable identity and same-installation measured PHENIX
build evidence. They retain combined stdout/stderr, status, exact execution
metadata and hashed required products in per-invocation bundles. Unknown build
evidence permits fresh execution only. Legacy bare output files are preserved
but not adopted; corrupted success evidence is rejected without repair. Failed
attempts retain diagnostics. EM determinacy consumes the returned authenticated
FSC path instead of reconstructing the obsolete cache filename.

This does not fingerprint every installed library. An unversioned in-place
library change requires a fresh cache directory. Input hashes identify currently
supplied bytes, not whether newly fetched deposition data equal a historical
input whose digest was never retained. Other benchmark cache implementations are
outside this change; the separately filed perturbation seed/source bug is #812.

## Adversarial review and regression evidence

Round 1 was an independent, read-only pass over the frozen implementation:

- #814: a permissive contiguous-version search rejected PHENIX's real split
  `Version` / `Release tag` banner, while recognizing an unrelated warning token.
  The fixture is grounded in the installed vendor's `phenix_info.py` and
  `phenix_env.sh` source, read without executing either. The fix parses explicit,
  unambiguous PHENIX fields and keeps stderr as separate raw evidence.
- #813: a cached manifest with missing or contradictory `executed_argv` was
  accepted. The fix validates the retained invocation, execution directory and
  exactly expanded argument vector before reuse, including literal versus
  explicitly templated arguments.

Both findings were filed before their fixes and independently reproduced by the
primary reviewer. The original X-ray implementation was also loaded from git into
memory and exercised with the new input/build/options regression: it produced
only three distinct output paths where nine were required. That assertion failed
as expected without checkout or source-file restoration. Mock argv normalization
matches the real adapter's Path-to-string conversion.

Focused coverage spans core evidence corruption, version probing, X-ray callers,
EM callers, exact-resolution changes, nonzero commands with plausible output,
legacy caches, failure diagnostics, and the downstream FSC consumer. All tool
executions in these tests are mocked. Full hermetic validation and the subsequent
review result are reported in the implementation PR; they do not substitute for
the licensed canary and registered experiment still required by #760.
