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
unalias git_ro 2>/dev/null || true
git_ro() { GIT_OPTIONAL_LOCKS=0 GIT_NO_LAZY_FETCH=1 GIT_ALLOW_PROTOCOL= command git --no-optional-locks -c core.fsmonitor=false "$@"; }
python3 -B scripts/inventory_storage.py --format text
python3 -B scripts/inventory_storage.py --format json --entries > "$review_dir/inventory.json"
python3 -B scripts/inventory_storage.py --format json --hash data/agents/round5 > "$review_dir/duplicates.json"
```

Run every local Git query in this skill through `git_ro`, which carries the helper's
guards against index rewrites, fsmonitor hooks and daemons, lazy fetches and
transports, and bypasses any `git` alias or function.
The helper classifies every file and symlink as tracked, untracked, ignored, Git
storage (including nested repositories' `.git`), nested repository or unclassified
without following symlinks (directories and special files elsewhere have class
`null`), and reports branch, HEAD, staged changes, logical bytes
(`st_size`), allocated bytes (`st_blocks` x 512), unique-inode totals, hardlinks,
symlinks, empty and special files, conventional cache-name matches, Git storage and
worktrees. Exit status 1, `inventory_complete_within_root: false`,
`git_classification_complete: false` or any `tracked_paths_not_inventoried` entry
makes the inventory partial, never clean. `--hash` groups exact SHA-256 duplicates
only within the selected paths, skipping Git storage, empty files and a best-effort
list of sensitive names; never select private configuration, and try a small
selection first. Name matches and duplicate groups are leads for section 2, not
conclusions. Cross-check totals that matter with `du -sk` or `git_ro count-objects -v`
(loose size is allocated KiB, pack size logical KiB), and inventory linked worktrees
without treating them as cleanup targets.

The helper does not compute unstaged modifications, because Git's content comparison
can run filters, which can be assigned from in-tree `.gitattributes`,
`.git/info/attributes`, the global and system attribute files or `attr.tree`. Run
`git_ro status --short --branch --ignore-submodules=all` only after
`set -o pipefail; git_ro ls-files -z | git_ro check-attr --stdin -z filter`
succeeds and every NUL-delimited attribute value is `unspecified` or `unset`.
An error leaves unstaged status unverified; `--ignore-submodules=all` prevents
submodules' unchecked filters from running. Keep untracked or locally modified work
and local configuration unless their owner decides otherwise.

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
  hash-pinned retained contract modules. A `.yaml.gz` carrier drops out of every gate
  discovery route. `scripts/check_qds_trust_invariant.py`'s path-keyed QDS allowlists
  stop edits but not removal; `scripts/check_pass_status.py`'s exceptions also fail as
  stale when their file is removed, renamed or compressed. A green gate does not prove
  equal coverage.
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
assuming one. The following skips partial-clone configuration and never treats a
failed producer's zero-byte output as a measurement:

```bash
if git_ro config --get-regexp '^(remote\..*\.promisor|extensions\.partialclone)$' >/dev/null; then
    printf '%s\n' 'Packed size: not measured (partial-clone configuration)'
else
    config_status=$?
    if [ "$config_status" -ne 1 ]; then
        printf '%s\n' 'Packed size: not measured (configuration query failed)'
    elif packed_bytes=$(set -o pipefail; git_ro pack-objects --stdout --all --reflog --indexed-objects </dev/null | wc -c); then
        printf 'Packed size: %s bytes\n' "$packed_bytes"
    else
        printf '%s\n' 'Packed size: not measured (pack command failed)'
    fi
fi
```

Inventory recovery state read-only. Resolve Git's administrative paths instead of
assuming `.git` is a directory; a linked worktree has a `.git` file:

```bash
git_dir=$(git_ro rev-parse --absolute-git-dir) &&
common_dir=$(git_ro rev-parse --path-format=absolute --git-common-dir) &&
object_dir=$(git_ro rev-parse --path-format=absolute --git-path objects)
```

Proceed with these paths only if all three queries succeed; otherwise report the
affected recovery checks as unverified. Recovery checks may inspect this
repository's Git administrative metadata outside the selected root, including
linked-worktree records. This does not include the contents of external working
trees or add them to the helper's filesystem inventory.

`git_ro rev-list --all --reflog --not --branches
--tags --remotes` lists commits not reachable from branches, tags or remote-tracking
refs, including those held by HEADs, reflogs, stashes or other refs and by every
prunable worktree record; pruning removes all such records at once, and a record
whose HEAD a branch contains can still hold the
only reference in its reflog. Date each commit by the newest reflog entry that
reaches it: inspect shared-ref and main-worktree logs under `"$common_dir/logs"`,
and each linked record's `logs/HEAD` under `"$common_dir/worktrees"` (the current
linked worktree's log is `"$git_dir/logs/HEAD"`)
(`git_ro rev-list <entry> --not --branches --tags --remotes` for both old and new
object IDs, skipping all-zero IDs), since stash index commits and interior commits
are named by no entry. Use the entry timestamp, not the commit date; a failed
reachability query leaves attribution unverified. `refs/stash` entries never expire
by default, and commits held by other refs (`refs/notes`, `refs/prefetch`, recovery
refs) are listed but not at risk from reflog expiry while those refs remain.
Whether GitHub still has a commit needs a network query, the one Git command run
outside `git_ro` and only with the
user's consent: `GIT_TERMINAL_PROMPT=0 command git --no-optional-locks -c
core.fsmonitor=false ls-remote origin 'refs/pull/*/head'`; if it fails, record
"not checked", never "not held". Also list
unreachable commits (`git_ro fsck --unreachable --no-progress`), flagging dropped stashes
(`WIP on`, `index on`, `untracked files on`) with their ages.

Check staged-only work against each record's own HEAD. Set
`record_git_dir="$common_dir"` for the main worktree, then repeat for each literal
administrative directory found under `"$common_dir/worktrees"`; for the current
linked worktree use `record_git_dir="$git_dir"`. This includes the main index at
`"$common_dir/index"`, which is absent from the linked-record directories:

```bash
if [ -f "$record_git_dir/index" ] &&
   record_head=$(git_ro --git-dir="$record_git_dir" rev-parse --verify -q 'HEAD^{commit}') &&
   record_staged=$(GIT_INDEX_FILE="$record_git_dir/index" git_ro --git-dir="$record_git_dir" diff-index --cached --name-status "$record_head"); then
    printf '%s\n' "$record_staged"
else
    printf '%s\n' 'Staged changes: unverified (missing index, missing or unborn HEAD, or Git query failure)'
fi
```

Only a successful comparison with empty output establishes no staged changes;
retain an unverified record for further investigation. Recording SHAs preserves
nothing. Do not delete
`.git` objects, expire reflogs, drop stashes, run GC/prune/repack, rewrite history,
or remove branches/worktrees as part of a data review.

A default `git gc` prunes unreachable loose objects older than two weeks, expires
unreachable reflog entries after 30 days (other entries after 90 days, except the
stash default above) and stale worktree records after three months. Check effective
`gc.reflogExpire`, `gc.reflogExpireUnreachable`, their `gc.<pattern>.*` overrides,
`gc.pruneExpire` and `gc.worktreePruneExpire` with `git_ro config --show-origin
--get-regexp '^gc\.'` before predicting loss. Matching per-ref settings or explicit
expiry options can override stash protection; global expiry defaults alone do not.
Entry age and the newest protecting entry alone do not prove what the next GC will
remove: account for every protecting ref/reflog and the applicable
expiry and object-pruning thresholds. `git worktree prune` removes eligible stale
records when run, and explicit `--expire=now`/`--prune=now` bypass the respective age
thresholds. Auto-gc runs from commit, fetch, pull, merge, am and rebase, and `gh pr merge`
can pull locally. It fires when `"$object_dir/17"` holds more than ceil(gc.auto/256)
loose objects (27 by default) or more than gc.autoPackLimit local packs without
`.keep` protection (50 by default);
`count-objects` totals understate how close that is, so report the resolved directory's
count. While recovery state is undecided, run any write command you are authorized
to run under a guard every Git child inherits: `export GIT_CONFIG_COUNT=2
GIT_CONFIG_KEY_0=gc.auto GIT_CONFIG_VALUE_0=0 GIT_CONFIG_KEY_1=maintenance.auto
GIT_CONFIG_VALUE_1=false`. Any later Git maintenance needs distinct scope and a
recovery plan. "Prunable" metadata is not authorization to destroy user recovery
state.

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
unverified. Check for changes by rerunning the helper with `--entries` and
comparing paths, kinds, classes, sizes, link counts and `mtime_ns` with the saved
JSON, along with count-objects and the worktree list. Git itself may refresh an
active split index's shared-index mtime during these reads. Report any such observed
timestamp changes explicitly; a listed `shared_index_files` path alone may be stale
and does not prove an active split index. Do not claim an unchanged snapshot when
metadata changed, or excuse other differences as this timestamp refresh. Then give
the smallest useful next action.

## 6. Act only when separately authorized

A cleanup request is a request for a proposal. Authorization counts only when given
after the user has seen the proposal rows it covers, and it names those rows or
literal paths. A request that itself names literal paths still needs the user's
approval of the proposal rows for exactly those paths. Authorization never reaches
required-evidence or uncertain rows; `.venv` teardown, migrations and Git maintenance
each need their own approval. Before acting, recheck the tree and each target
against the saved helper JSON, and follow repository branch/review/validation rules
for tracked changes.

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
