# Approved dependency snapshot implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline, with one independent final review. The user authorizes ordinary implementation and stage commit/push without additional approval gates.

**Goal:** Export only one independently approved repository package set from a verified stopped backup, then seed a new isolated portable registry and prove a protected cold build with the original registry unavailable.

**Architecture:** Add a Python standard-library receiver entry point alongside maintenance. Reuse backup/archive validation, protected file creation and new-volume Docker helpers. Preserve the approved registry identity and original index objects; leave version solving and build admission to the existing client.

**Tech stack:** Python 3.10+, existing Docker/Compose, unchanged 067b client, 8fc3 server and bad0 image.

**Spec:** The bounded design presented in this conversation and the contracts below; existing source-baseline and maintenance contracts remain in force.

## Contracts and constraints

- Windows is authoritative source; Linux validation only. No installs, pulls, security changes, solver/lockfile changes or additional services.
- Version one accepts a nonempty provenance-v1 approval with unique packages, safe storage identities, lowercase SHA-256 and one exact credential-free HTTP(S) registry URL. Do not merge multiple origins or rewrite approvals for relocation.
- `export --backup DIR --baseline FILE --output NEW_DIR` verifies a stopped backup, selects exactly each approved CJP and index version, and checks their identities and artifact hashes before writing. Index versions not selected and unrelated packages/configuration/CA are excluded.
- Check that unconditional runtime index dependency names occur in the approved set. Do not interpret version expressions, target selection or replacements in a second solver. Original client cold verification decides build compatibility; scripts/test/target graphs are not newly certified.
- Output contains only `snapshot.json` and `data.tar`, created privately. It includes internal addresses and source artifacts and still requires private handling/review; arbitrary package/index contents may themselves contain secrets.
- `verify --snapshot DIR --baseline FILE` requires the external approved file with the exact original bytes, exact storage membership, index identity and CJP hashes. A bundled/current output is never auto-approved. JSON duplicate keys, links, traversal, duplicate members, extra files, malformed/oversized metadata and mismatches fail closed.
- `seed --snapshot DIR --baseline FILE` runs in a newly configured verified complete bundle. It only creates a new labelled empty volume for that configuration, checks the exact backed-up image, validates before extraction, re-exports and compares, and leaves the service stopped. Never adopt/overwrite an existing volume or change credentials/CA/approval.
- Input directories, Docker administration and the maintenance interval must be protected from concurrent mutation. No signatures, online backup, disk quota or crash-durability claims. Failure keeps owned diagnostic resources and partial output.
- New complete bundles declare `dependencySnapshot=approved-set-v1`; genuine legacy seven/eight-file bundles retain their previous exact file-list verification. No binary rebuild.
- Use the specified clean checkout/branch. Keep evidence, failed runs and all archives outside Git. Push only atomgit/main and the independent same-tree GitHub mirror main after acceptance.

## Review focus

- A forged manifest must not introduce unapproved storage paths or bypass CJP/independent-baseline checks.
- Different repository origins, missing dependencies, duplicate versions or wrong organizations must not silently collapse into one source.
- No credentials, unrelated package or unselected version should be copied from the full backup.
- Corrupt input must fail before target Docker mutation; an already initialized target must remain intact.
- New-volume extraction must use the existing ownership and stopped-writer protections, retain failure evidence and never start/cut over a service.

## Task 1: Snapshot receiver tool and bundle compatibility

**Files:** Add `deployment/portable/snapshot.py`, `integration-tests/deployment/test_dependency_snapshot.py`; update portable `verify.py`, `package.py`, `README.md`.

**Interfaces:** `export_snapshot(backup: Path, baseline: Path, output: Path) -> dict`, `verify_snapshot(root: Path, baseline: Path) -> dict`, `seed(root: Path, source: Path, baseline: Path) -> dict`.

- [x] Write focused format/subset/closure/integrity/rejection tests; observe missing-entry-point RED.
- [x] Implement exact selection, bounded metadata parsing, independent approval validation and streamed artifact export.
- [x] Implement offline verification and new-volume seed using maintenance helpers. Add capability-aware old/new bundle verification.
- [x] Run targeted Windows/POSIX Python tests, retaining genuine permission skips separately.

## Task 2: Real isolated dependency snapshot acceptance

**Files:** Add a focused acceptance entry point under `integration-tests/deployment/` and document its existing input/tool requirements.

- [x] Freeze existing real CJP inputs: company::baselineparent -> meshdep, plus unrelated company::teamhello. Publish to an owned single registry and take an actual stopped backup.
- [x] Export the independently approved two-package set; confirm unrelated package/configuration and unselected versions are absent, source/approval unchanged, and reject missing dependency/corruption/drift.
- [x] Seed a newly configured complete bundle, refuse repeat seed, keep original registry stopped, and cold-build/run through the unchanged full client with a read-only external approval.
- [x] Use an internal Docker network without upstream routes for the consumer. Preserve the exact registry URL via a controlled alias; do not claim arbitrary address migration or full host air-gap coverage.
- [x] Check denied anonymous reads, unavailable unselected packages, recreation and clean owned-resource teardown; keep failures locally.

## Task 3: Review, evidence and stage delivery

- [x] Independent whole-stage review; reproduce and fix substantive findings with focused RED/GREEN verification.
- [x] Freeze the complete tested bundle/archive and record exact results, hashes, limits and failure evidence in existing delivery documents.
- [ ] Inspect explicit staged paths, commit once, append the GitHub same-tree mirror commit, ordinary-push only the two authorized main refs, and read back their identities.

## Execution record

- Started clean at source `1d956218b68bc0464eadb027a368d2ce8d63c8c0`, mirror `792ba41eeb78b2d8d40a473e5bd135e7e094f96a`; existing worktrees and previous evidence retained.
- Evidence root: `test-runs/dependency-snapshot-20261023`, outside the public source checkout. No new worktree or downloaded toolchain is necessary.
- A selected set and byte integrity are guaranteed by the tool; the dependency-name check is conservative and deliberately does not reproduce the original solver's version/target/replacement semantics.
- Ruling: keep the new snapshot acceptance separate from the CA/full-recovery runner, reusing its process/diagnostic helpers. This graph, exact-subset and internal-network contract differs from full configuration/CA recovery; adding flags there would combine two separate acceptance surfaces.
- Ruling: seed rejects nonempty upstream configuration before creating a volume. A new Hosted receiver is needed to keep missing snapshot packages from silently falling back to an online Proxy. A focused RED/GREEN pins this condition.
- Initial entry-point RED: 12 failures; capability and Hosted-only REDs retained. Snapshot tests Windows/Linux14/14, related portable tests Linux65/65 and Windows61 passed plus four link-permission skips. An initial sandbox run could not reach its two HTTP fixtures; the unchanged health tests passed with loopback access, then the full related Windows suite passed.
- First Docker run stopped before the first check because the new runner used the wrong publication route. Second run completed eight checks and built/ran the application but its integrity assertion looked only at stdout, while the launcher writes it to stderr. Both failed runs and data remain; a fresh corrected run completed12/12,76.80s,cleanupErrors=[] using the complete bundle and unchanged full client.
- WSL inline quoting failed before Python tests; switching to a saved validation script succeeded in a fresh validation directory. No host security changes or Windows Cangjie execution occurred.
- Independent final review: one Important cleanup issue confirmed by RED, fixed by separating diagnostic capture from stopping owned resources, and GREEN15/15 on Windows. Seven independent resealed-input probes passed; no unresolved Critical/Important/Minor findings. All explicitly declined scope items retain the contracts above.
- Final identical nine-file bundle acceptance after the cleanup fix:12/12,78.70s,cleanupErrors=[]. Archive/manifest identities are recorded in the candidate and verification documents; old archives remain unchanged.
- The added cleanup unit is host-independent control flow and exercised on the Windows orchestrator, including the final real Docker run. Its WSL supplement did not execute after an input-line-ending problem and subsequent distro startup error0x8007274c. Keep Linux core snapshot14/14 as its own evidence; do not claim Linux15 or expand into unrelated WSL repair.
- This plan is frozen before the stage commit; final Git/remote identities belong to the task result and private delivery record rather than a self-referential checklist.
