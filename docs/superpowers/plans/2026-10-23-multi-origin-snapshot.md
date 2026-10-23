# Multi-origin dependency snapshot implementation plan

> **For agentic workers:** Use superpowers:executing-plans inline, TDD and one independent final review. The user authorizes ordinary phase decisions and stage commit/push without additional approval gates.

**Goal:** Preserve multiple original registry identities in a complete approved snapshot set, then demonstrate a protected cold build whose genuine parent and transitive dependency come from different isolated restored origins.

**Architecture:** Extend the existing offline snapshot tool. A set contains one data snapshot per exact original registry URL; every component binds the same full external approval bytes. The set validates complete origin coverage, while each existing single-instance receiver seeds one component independently. No client, solver, lockfile, approval-relocation or runtime-service change.

**Tech stack:** Existing Python3.10+ standard library, Docker/Compose and fixed067b/8fc3/bad0 client/server/image. Windows source remains authoritative. Reuse existing SDK/native tools; no downloads, Windows Cangjie or security changes.

**Spec:** The bounded source-preserving snapshot-set design presented in this conversation, expanded by the following contracts.

## Contracts

- Keep the existing `export` single-URL format-v1 behavior and old genuine seven/eight/nine-file bundle validation.
- Add `export-set --source REPOSITORY BACKUP_DIR ... --baseline FULL_FILE --output NEW_DIR` and `verify-set --snapshot-set DIR --baseline FULL_FILE`. Sources identify approved repository config names and exactly cover original URLs; multiple config aliases for the same URL require one backup, not separate runtime instances.
- An approved repository name must identify one exact URL. One package occurs once in the full approval. Do not merge different original URLs or rewrite original repository names/addresses/checksums.
- Preflight every source backup, selected index and artifact against the full independently approved graph before creating set output. Missing/extra/ambiguous mappings or later source mismatch leave the requested output absent.
- A set has only `snapshot-set.json` and `origin-NNNN` component directories. Set format-v1 records exact original URLs, component directories and manifest hashes, plus the full external approval byte hash. Verification requires complete origin coverage and rejects duplicate/missing/extra origins/directories or inconsistent component bindings.
- Components use snapshot format-v2 with explicit `selection=exact-registry-v1`, the exact URL and the full approval byte hash. Their storage contains exactly approved entries for that URL. Dependency-name inclusion checks use the full approved graph, allowing a genuine cross-origin edge without weakening build admission.
- The original full approval is always supplied externally and mounted read-only to the final client. No derived approvals are generated or used for multi-origin client admission. Version/target/replacement semantics remain the original client's responsibility.
- New bundles declare `dependencySnapshot=approved-origins-v2`; they read v1 and v2. New-format seed requires this capability. Old genuine v1 bundles reject new components instead of silently treating them as a single-origin snapshot.
- `seed` keeps the existing same-image/new-Hosted-config/new-volume/read-back/stopped-service contract. Each component is imported separately; no automatic multi-service deployment, start, DNS change or traffic switch.
- Source archives, full approval, old artifacts and failed evidence remain intact. Output still contains private source/address information. Preserve existing no-signature/no-index-authorship/no-CJP-internal-inspection/no-concurrent-mutation/no-quota boundaries.
- Continue the clean specified checkout/branch. Only push atomgit/main and the append-only same-tree GitHub mirror main after acceptance. Never push origin, force, create PR/Release or publish binaries/evidence.

## Review focus

- A forged component must not change its selected original URL, expand its package subset or substitute a narrowed approval.
- Missing or duplicate sources must not make a partial set appear complete, even if the set manifest is recomputed.
- Same package/version with different bytes at two origins must stay separate; swapped backups must fail before output.
- Every backup must pass preflight before output creation; subsequent failures retain partial output and original inputs.
- Old single-origin format, old bundles, seed refusal/ownership and failure-log cleanup must retain their existing behavior.

## Task 1: Full-graph approval and origin-set tool

**Files:** Modify portable `snapshot.py`, `verify.py`, `package.py`, `README.md` and `integration-tests/deployment/test_dependency_snapshot.py`.

**Interfaces:** `approved_graph(path) -> (raw_bytes, package_map)`, `export_set(backups: dict[str, Path], baseline: Path, output: Path) -> dict`, `verify_set(root: Path, baseline: Path) -> dict`. Existing `export_snapshot`, `verify_snapshot` and `seed` signatures stay unchanged.

- [x] Write failing origin-set/cross-origin/full-approval/preflight/membership/legacy-capability tests and observe RED.
- [x] Share strict full-graph parsing, add v2 origin-specific verification and the set export/completeness check, retaining v1 semantics.
- [x] Integrate the new bundle capability and CLI; verify private outputs and static diagnostics.
- [x] Run focused Windows/POSIX tests and directly related bundle compatibility regression. Existing Linux Docker/native tools are a fallback if WSL remains unavailable; do not expand into host repair.

## Task 2: Real cross-origin acceptance

**Files:** Extend the existing `integration-tests/deployment/dependency_snapshot.py` runner with an explicit multi-origin mode, reusing its current resource ownership and independent log/cleanup paths.

- [x] Freeze real CJP inputs and set up two owned source registries: parent/internal and transitive/home, including an alternate same-name/version CJP and unselected data.
- [x] Take actual stopped backups; export and verify a complete set using one independently constructed full approval, and reject swapped sources, missing origins and corruption without mutation.
- [x] Seed separate new receiver volumes/configurations, keep original sources stopped, and attach both targets plus the cold consumer only to one internal network with original URL aliases preserved.
- [x] Use current complete client to compile/run parent→meshdep, assert each provenance entry retains its own original name/URL/SHA, reject drift and unavailable unselected data, and verify recreation plus unchanged originals.
- [x] Include real v1 export/verify interoperability with the genuine previous bundle; do not count its historical12 checks as new execution. Retain failure evidence and clean only owned runtime resources.

## Task 3: Review and stage delivery

- [x] One independent final review, then targeted RED/GREEN corrections for substantive findings.
- [x] Freeze the actually tested new complete bundle/archive, record exact hashes/results/limits in existing candidate, verification, delivery and usage documents.
- [ ] Audit explicit staged paths, commit once, append the identical-tree GitHub mirror commit, ordinary push to the two authorized main refs and read back both heads.

## Execution record

- Clean source start `0e212bf183f3ad5f84b7a5d27e449e564761bd99`, mirror `4e59825ecffee6e06aa3182aad27c279808c4526`; both main heads read back unchanged. Docker Linux29.8.0 available.
- Evidence root is a new `test-runs/multi-origin-snapshot-20261023`, outside the public checkout. Reuse the specified branch; no new worktree or runtime service.
- Ruling: preserve separate origin snapshots and full approval. Combining all content into a new URL would change source identity and require independent relocation approval; allowing URL/subset admission would weaken the existing trust contract.
- Existing output-inside-backup pollution was reproduced with a synthetic v1 RED. Both v1 and set export now reject such output paths before any write, including canonical parent aliases; original files stay unchanged.
- Initial API/capability RED had7 failures and1 error across22 tests. After the output-pollution regression, Windows23/23 and Linux Docker tmpfs23/23 passed; related portable tests Linux65/65 and Windows61 passed plus4 link-permission skips. Reused existing image/Python with no external network; no WSL repair or Windows Cangjie execution.
- First real multi-origin run16/16,cleanupErrors=[]; frozen inputs include the current full client, current/new and genuine legacy bundles, existing SDK/native tools and real CJP bytes. Only the dedicated v1 data interoperability check uses its own independently specified single-package fixture approval; the multi-origin build and all components bind the original full two-origin approval.
- Independent read-only review found no Critical/Important/Minor issues; nine synthetic origin/approval/preflight probes passed. No runtime-code changes followed acceptance, so the final nine-file archive is byte-identical to the tested bundle. Archive SHA-256 `cb5e7241ce553baa44d248c67204feba7b37f3d98d8e9bf210bb8f451d5a4292`; old artifacts remain unchanged.
- Scope ruling retains the documented exclusions: no publisher/index-author authentication, CJP internal inspection, cache revalidation, adversarial concurrency/quota or whole-host air-gap guarantee. Existing resource-creation/log-registration failure window is outside this change; a single component seed does not certify full multi-origin deployment. Git delivery identities are recorded after commit in private delivery evidence and the task result rather than a self-referential follow-up commit.
