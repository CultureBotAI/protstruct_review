# T15 native Biotite state admission — 2026-09-28

Result-free engineering correction for filed issue #874, prepared separately
from the frozen T15 diagnostic/canary worktree. No scientific execution, saved
result mutation, denominator recalibration or grading change is included.

## Defect and source evidence

The previous `run_biotite()` used `_BIOTITE_TO_HEC.get(code, "C")`. Consequently
both the native empty string and unsupported values such as `Z` became coil.
An amino-acid residue without a CA can survive `filter_amino_acids()` and receive
the empty native assignment; filtering amino acids does not make that state
impossible. Converting it to coil fabricates an assignment and can turn an
unavailable comparison into an apparently complete common denominator.

Static installed Biotite source `biotite/structure/sse.py`, `annotate_sse()`
return-value documentation (lines 53–64), defines `a`, `b`, `c` as helix, strand
and coil, and `''` as a non-amino-acid residue or a residue without CA. The code
sets the native state to `''` for NaN CA-coordinate rows in both its short-chain
path (lines 98–106) and general path (line 201). This is source inspection, not
a newly executed Biotite result or authentication of an old execution.

## Bounded correction

`scripts/t15_ss_agreement.py::run_biotite` now accepts only exact native string
codes `a`, `b`, `c` before projecting to H/E/C. An empty string produces an
explicit **unavailable/no assignment** diagnostic. Other strings or unsupported
value types produce an unsupported-native-code diagnostic. Both include the
input model path, chain, residue number and insertion code.

Invalid native states terminate the call rather than becoming coil, disappearing
from the residue keys, or receiving padded labels. No partial assignment mapping
is returned. Existing residue selection, chain grouping, insertion-code keys,
assignment-length check and `a`/`b`/`c` projections are unchanged. The wrapper
does not invent a second CA-availability classifier or reinterpret a valid native
`c` according to its own geometry assumptions.

This is an earlier assigner-admission failure, not a completed two-stream
denominator mismatch. It therefore does not claim the failed-pair evidence
retention guarantee reserved for completed assigner streams. Extending retention
to earlier failures, if desired, is a separate task. All saved evidence and
historical results remain unchanged; this correction alone does not establish
which earlier inputs, if any, contained coerced native states.

## Hermetic verification

Eight focused tests mock every Biotite module touched by `run_biotite`; no actual
Biotite or numpy import, P-SEA assignment, scientific subprocess or network call
is performed. Tests cover exact a/b/c mapping, chain filtering and ordering,
signed residue/insertion keys, an N-only amino acid returning `''`, explicit
native `c` preservation, unknown strings and value types, mixed valid/invalid
streams, absent insertion-code annotation, existing length mismatch and no
amino-acid residues. Mocked invalid streams produce no stdout or partial result.

The exact saved pre-fix implementation fails the empty-state regression once
and the mixed empty/unknown regressions three times at assertion level, with no
setup/API errors. The same original implementation passes all five tests of
unchanged behavior. The candidate passes all eight tests. Repository-configured
Ruff checks pass. The full gate, any numerical replay using actual Biotite, and
scientific canaries were deliberately not run for this scratch proposal.

Integration must occur after the frozen diagnostic boundary and independent
review; source pins for future runs must identify the integrated wrapper.
