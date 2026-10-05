---
name: review-data-retention
description: Audit protstruct_review storage for disposable caches, duplicates, and compression opportunities while preserving scientific evidence and replay, including failed, excluded, and superseded runs. Use for any disk-space, cleanup, deletion, deduplication, compression, or data-retention request in this repository, before generic cleanup skills act here. Produce a read-only, evidence-backed cleanup proposal; deletion, compression, relocation, and Git housekeeping require separate explicit authorization.
---

# Review data retention and cleanup opportunities

## Scope and authority

Find worthwhile space savings without erasing the experiment's history. A failed,
excluded, withdrawn, superseded, duplicate, empty, or ignored file is not thereby
useless. Finding nothing to delete is a valid result; say so when no scientific-data
deletion is justified.

Read `CLAUDE.md` and `CODING_STANDARDS.md`. For scientific evidence, additionally
read the relevant sections of `.claude/skills/protstruct-eval/SKILL.md` and the
relevant records and guards. Paths below are repository-root-relative; run from the
root. In this repository this review comes before generic cleanup tools, including
the user-level `repo-crud-cleanup`, `safe-delete` and `disk-usage-report` skills when
installed: their name, age, access-time and extension rules are leads, not decisions.
Use such tools only to carry out exact items approved from this proposal.

A review does not authorize changing the repository, its linked worktrees, `.git`,
`.venv` or any other inspected path; installing dependencies (including via `uv run`
or `uv sync`); downloads; scientific execution; running tests or the validation gate;
GitHub changes; or Git-state changes. Do not rerun an experiment to establish that
its original evidence is replaceable. Use read-only standard-library Python with
`-B`; apart from the inventory helper, read repository code instead of importing or
running it. Keep output on stdout or in a scratch directory outside the repository
(the user's location when given); write a durable report only where the user asks,
and upload nothing. Stores outside the tree that scripts or records name (for
example `/tmp/nc_*` or the negative-control input store in
`ref/research/negative_control_round6.md`) are out of scope unless the user includes
them; list those you find under coverage and limits, by metadata only.

## 1. Inventory actual storage

Record the date, repository root, branch, HEAD and working-tree state. Inventory
with the read-only standard-library helper, using any Python 3.11+ and `-B`:

```bash
review_dir=$(mktemp -d "${TMPDIR:-/tmp}/protstruct-retention.XXXXXX")  # or the user's location
python3 -B scripts/inventory_storage.py --format text
python3 -B scripts/inventory_storage.py --format json --entries > "$review_dir/inventory.json"
python3 -B scripts/inventory_storage.py --format json --hash data/agents/round5 > "$review_dir/duplicates.json"
```

The helper classifies every entry as tracked, untracked, ignored, Git storage
(including nested repositories' `.git`), nested repository or unclassified without
following symlinks, and reports branch, HEAD, staged changes, logical bytes
(`st_size`), allocated bytes (`st_blocks` x 512), unique-inode totals, hardlinks,
symlinks, empty and special files, conventional cache-name matches, Git storage and
worktrees. Exit status 1, `inventory_complete_within_root: false`,
`git_classification_complete: false` or any `tracked_paths_not_inventoried` entry
makes the inventory partial, never clean. `--hash` groups exact SHA-256 duplicates
only within the selected paths, skipping Git storage, empty files and a best-effort
list of sensitive names; never select private configuration, and try a small
selection first. Name matches and duplicate groups are leads for section 2, not
conclusions. Cross-check totals that matter with `du -sk` or
`git --no-optional-locks count-objects -v` (loose size is allocated KiB, pack size
logical KiB), and inventory linked worktrees without treating them as cleanup targets.

The helper does not compute unstaged modifications, because Git's content comparison
can run filters. Only where no attribute source (`.gitattributes`,
`.git/info/attributes`, `core.attributesFile`, `$XDG_CONFIG_HOME/git/attributes`)
assigns `filter=`, add `git --no-optional-locks -c core.fsmonitor=false status --short
--branch`; plain `git status` can also rewrite `.git/index` or start an fsmonitor
daemon. Keep untracked or locally modified work and local configuration unless
their owner decides otherwise.

Separate working-tree data, research records, installed environments, software
caches, and Git storage. Report logical bytes and allocated disk space distinctly
(label KiB/MiB versus decimal units). A hardlinked file frees nothing while another
link survives. APFS clones, snapshots and shared package caches are invisible to
`stat`, so physical reclaim can be smaller than allocated size; `.venv` files may
share blocks with the uv cache. Do not promise measured reclamation from a
pre-cleanup estimate, and do not compare totals from a shallow or different checkout.

Prioritize large categories. Count and size candidates before spending effort on
tiny duplicates. Compare equal-size files by SHA-256 before calling them exact
duplicates; similar filenames or equal scientific values are insufficient. An exact
duplicate inside evidence is still evidence: never replace it with a symlink or
hardlink. Retained-evidence guards (for example `scripts/check_fixture_provenance.py`
and `scripts/recount_t13_t15_canaries.py`) reject symlinks, but none detects
hardlinks, so a green gate cannot catch that mistake.

## 2. Establish whether each candidate is dispensable

For each candidate or coherent group, identify the following. For familiar tool
caches whose every descendant is tool output (`__pycache__/`, `.ruff_cache/`,
`.DS_Store`), Git status, ownership and one ignore-independent reference search are
enough.

- Git status and ownership; experimental role; source and acquisition time;
  unique inputs, outputs, raw streams, tool identities, and run/attempt identity.
- Callers in scripts/tests, dataset and archive-member references, hashes,
  manifests, exact directory-membership checks, filename-based discovery,
  EVAL/QDS source pins, correction ancestry, and generated/published consumers.
- Registration, attrition and failure ledgers, diagnostic/replay uses, and any
  issue or PR that promises preservation. Verify current issue state read-only
  if relying on it; a closed issue alone does not release its evidence.
- Whether exact bytes can actually be recovered, with which pinned tools and
  source snapshots, and at what cost. A URL, a script, or Git history alone is
  not a tested restoration plan or a substitute for required live paths.

An absence claim requires an ignored/hidden-inclusive search that also reads binary
and gzip content, such as `rg -uuu -z -l -F -- 'candidate-path' .` (file names only;
read matching lines only in non-private files). Also search basename, record IDs,
hashes, directory/glob consumers and archive-member references; list ZIP members in
memory with Python's `zipfile` rather than extracting. Literal-path absence cannot
establish independence. State exclusions, including unsearched history or external
publications. Never conclude "unreferenced" from ordinary `rg` or `git grep` alone.
Inventory sensitive local config by metadata; do not print credentials or sweep
private configuration into an evidence bundle.

Classify the result:

| Class | Decision |
|---|---|
| Disposable/rebuildable local cache | Propose specific paths, regeneration cost and active-use caveats. |
| Optional environment teardown | Treat `.venv` as a working toolchain, not a failed experiment; establish reinstall requirements and offline needs; its allocated size is only an upper bound on reclaim. |
| Required evidence | Keep, even when unsuccessful, obsolete, duplicated or empty. |
| Compression/archive migration | Quantify benefit; identify path/hash/discovery changes and restoration requirements. |
| Uncertain | Keep pending named evidence or owner decision; do not infer permission from age. |

Ignored status is not a retention policy. For example, `CLAUDE.local.md`,
`.claude/settings.local.json`, `docs/agents/`, and ignored benchmark caches may
contain local work or unique evidence. Generated files can also be committed
contract products: inspect their consumers before proposing removal.

## 3. Repository-specific evidence traps

Read the applicable sources rather than freezing current issue statuses or byte
counts into a cleanup rule:

- `ref/research/data/README.md` and the EM ledgers keep one row per attempted
  entry (kept, rejected, skipped, screened-only, unrecorded and `LOST`).
  Rejections alone give only the attrition numerator. Clearing a historical
  temporary cache lost measured entries' identities and values; their `LOST`
  rows still count toward published totals.
- `ref/research/t13_t15_canaries_execution_2026-09-27.md`,
  `scripts/recount_t13_t15_canaries.py` and the #799 campaign records treat
  separate execution roots as separate attempts. Keep attempted, admitted, failed
  and not-launched members explicit; never splice successes into a success-only
  cohort.
- `ref/research/standalone_dictionary_canary_execution_2026-09-28.md` and
  `data/coscientists/openscientist/retained_799_24MR_attempt01/24MR/result.json`:
  the failed Reduce attempt pins files inside a dot-prefixed staging directory and
  stores two identical pairs at different paths (stdout copies and empty stderr
  copies). The preregistration requires keeping them unchanged, but no gate check
  protects them. Keep its campaign registration and stopped-run partition
  (`data/coscientists/openscientist/retained_799_campaign_2026-09-28/registration.json`
  and `stopped-after-canary.json`) too.
- `scripts/recount_t13_t15_canaries.py` replays both canary roots, including their
  failed attempts, against exact entry and file sets that include gitignored files,
  source snapshots and launch receipts. The separate T15 diagnostic root of
  `ref/research/t15_failed_attempt_diagnostic_execution_2026-09-28.md` is protected
  only by its own manifest and record, and its presence blocks reuse of its run id.
  Retained `t15_cache` directories hold manifest-pinned inputs that gate tests
  read; a retained directory named `cache` is not necessarily a software cache.
- `scripts/audit_1sar_retained_evidence.py` and `scripts/test_t15_ss_agreement.py`
  pin the original 1SAR ZIP by the SHA-256 of its complete bytes; other consumers
  bind its path, the artifact id in its filename and its member set. Do not repack,
  rename, relocate or edit it: identical members keep its identity only if the
  complete-archive digest is unchanged. Byte-identical extracted members and failed
  oracle logs can have independent live consumers.
- `ref/research/negative_control_round5.md` and `scripts/bench_round5.py`:
  `data/agents/round5/` holds models, decision logs and transcripts, including
  excluded evidence and the agents' records of provenance incidents. No file there
  is a replaceable endpoint: agent generation is not reproducible, and the round
  record pins SHA-256 for every final model and transcript, which no guard
  re-checks.
- `CODING_STANDARDS.md` (13b-13i) and the retained-emitter guards make historical,
  superseded and correction-targeted EVAL/QDS carriers immutable. Do not rewrite,
  re-serialize, rename, move, compress, symlink or deduplicate them, or the
  hash-pinned retained contract modules. A `.yaml.gz` carrier silently drops out of
  every gate discovery route, and path-keyed allowlists stop edits but not removal.
  A green gate does not prove equal coverage.
- `ref/README.md`, `THIRD_PARTY_NOTICES.md` and `LICENSE-DOCS.md` keep the PHENIX
  documentation cache local-only and leave third-party bundles and fixtures under
  upstream terms. Never put licensed tools or documentation, credentials, local
  configuration or environments into an archive or upload. Publishing, uploading or
  sharing third-party bundles or the PHENIX cache is redistribution; moving them to
  storage the user controls is a section 4 migration.

These are examples of load-bearing evidence, not a whitelist: investigate new
experiments with the same provenance checks.

## 4. Evaluate compression and Git storage separately

Estimate lossless compression with bounded streaming or in-memory processing
without writing archives during review. State codec/level, total input bytes,
output estimate, and whether the estimate is per file or one aggregate stream.
Do not assume ZIP/PDF/MTZ files are incompressible or count the same bytes twice.
Inspect archives by listing members or reading them in memory; do not extract them.

For scientific-data migration, require an original-path/size/SHA-256 inventory
including hidden and empty files, archive checksum, a storage destination the user
names (an off-machine destination is an external upload that needs its own approval
and a licence and privacy check), verified byte-for-byte restoration, and consumers
that can still access evidence. Preserve relevant modes and link semantics. Account
for temporary capacity for source, archive and restoration; keep originals until
verification and approval. `data/pdb_mtz/fixture_provenance.yaml` and
`scripts/check_fixture_provenance.py` pin compressed bytes and, for gzip fixtures,
decompressed content, together with an exact directory listing; that precedent
neither permits changing those fixtures without a same-commit manifest change nor
extends to other immutable artifacts. If a frozen contract cannot support
migration, keep that evidence in place and report the constraint.

Working-tree compression/deletion does not remove old blobs from Git history;
committing a compressed duplicate adds new objects that stay in every clone.
Report loose-object and pack sizes separately, and measure a packed size instead of
assuming one (`git --no-optional-locks -c core.fsmonitor=false pack-objects --stdout
--all --reflog --indexed-objects </dev/null | wc -c` writes nothing). Inventory
recovery state read-only: for each prunable worktree record, the commits only it
keeps reachable
(`git --no-optional-locks rev-list --single-worktree <its HEAD and the SHAs in
.git/worktrees/<id>/logs/HEAD> --not --all <every other record's HEAD and reflog
SHAs>`), since a record whose HEAD a branch contains can still hold the only
reference in its reflog; and unreachable commits
(`git --no-optional-locks fsck --unreachable --no-progress`), flagging dropped
stashes (`WIP on`, `index on`, `untracked files on`) with their ages. Recording SHAs
preserves nothing. Do not delete `.git` objects, expire reflogs, drop stashes, run
GC/prune/repack, rewrite history, or remove branches/worktrees as part of a data
review. A default `git gc`, including the auto-gc that ordinary commits and fetches
can trigger, prunes unreachable loose objects older than two weeks, expires
unreachable reflog entries after 30 days and stale worktree records after three
months; `git worktree prune` and `--prune=now` act at once. Report how close
auto-gc is, and while recovery state is undecided make any commit or fetch you are
authorized to run with `-c gc.auto=0 -c maintenance.auto=false`. Any later Git
maintenance needs distinct scope and a recovery plan. "Prunable" metadata is not
authorization to destroy user recovery state.

## 5. Present the proposal

Give one row per path or coherent group, in three groups: low-risk local cleanup,
engineering migration, and keep (required or uncertain).

| Path(s) | Class (Git status) | Logical / allocated bytes (basis) | Expected savings (bound) | Evidence and consumers checked | Regeneration or restoration | Risk |
|---|---|---|---|---|---|---|

State the basis of every number: logical or allocated, and a helper measurement
(complete or partial) or an estimate (codec, level, per file or aggregate). Savings
are upper bounds until an authorized action is measured as the helper's before/after
allocated bytes for the exact paths; `df` on a shared volume is only context.
Explain why each retained failed or excluded run stays. Close with coverage and
limits: roots scanned and excluded, traversal errors, each search and whether it
included ignored, hidden, binary and compressed files, and evidence not checked
(history, publications, licensed reruns). Mark claims measured, inferred or
unverified. Confirm nothing changed by rerunning the helper with `--entries` and
comparing paths, kinds, classes, sizes, link counts and `mtime_ns` with the saved
JSON, along with count-objects and the worktree list; then give the smallest useful
next action.

## 6. Act only when separately authorized

A cleanup request is a request for a proposal. Authorization counts only when given
after the user has seen the proposal rows it covers, and it names those rows or
literal paths; a request that itself names literal paths authorizes only those
paths, after the review confirms them. It never reaches required-evidence or
uncertain rows; `.venv` teardown, migrations and Git maintenance each need their own
approval. Before acting, recheck the tree and each target against the saved helper
JSON, and follow repository branch/review/validation rules for tracked changes.

Dry-run the exact list, then act on the smallest approved item alone as a canary and
verify its side effects (target absent or archive restored byte-for-byte, helper
allocated bytes recorded, siblings and Git state unchanged) before the rest, one
literal path at a time; if the canary needed a fix, run a new canary. Prefer
recoverable removal: a quarantine on the same volume outside the repository frees no
space until a separately approved purge. Never use broad globs or unresolved
destructive targets. Stop if files changed, references remain unresolved, or
restoration fails; for evidence migrations verify original hashes, full inventory
and before/after discovery sets, not just a successful gate. Afterwards rerun the
helper, compare with the saved JSON, and report actual changes, recovery location
and measured space change. Do not extend approval to any unnamed item (a neighbour, a parent
directory or the rest of a group), to external uploads, or to Git housekeeping.
