# Remaining single-instance engineering hardening

> **For agentic workers:** Execute the scoped tasks below using systematic-debugging and test-driven-development; compile only one Cangjie group at a time. The user has explicitly requested autonomous completion of remaining engineering work.

**Goal:** Close reproducible local integrity/resource gaps and expand safely executable acceptance without changing the solver, lock format or deployment architecture.

**Architecture:** Preserve the existing client and file-backed single-process server. Add extracted-cache receipts, opt-in server storage byte accounting, and controlled acceptance for reviewed Maple cases and credential/CA replacement. All real acceptance uses owned synthetic data.

**Tech Stack:** Existing Cangjie SDK/stdx, Python standard library, existing Linux OpenSSL. Windows remains the source checkout; WSL is validation only.

**Spec:** Existing hardening roadmap and the user's 2026-10-27 instruction to complete as many remaining engineering gaps as possible.

## Constraints and review focus

- No Windows Cangjie execution, installs, real credentials, policy changes, upstream origin pushes, Releases, tags or rewritten history.
- Preserve all old candidates and failures. New binaries and acceptance have distinct identities; old counts are never transferred.
- Cache revalidation must detect changed file bytes, added/missing entries, links, invalid/missing receipts and a changed selected archive digest before compilation. An unsigned writable local receipt is not an attacker-proof trust anchor.
- Optional disk quota must cover every shared storage writer and temporary replacement peaks, including concurrent writes and recovery; no silent data deletion or quota-as-filesystem guarantee.
- Maple admissions require per-case dependency/input review and actual commands. Existing assertion failures remain failures.
- Rotation acceptance must exercise rejection of retired credentials/trust and persistence with owned processes; loopback results do not prove a physical receiver or production CA rollout.

## Tasks

- [x] Cache: old1a46 tampering and install-source contamination reproduced; new9d35 receipts19/19 and immutable-install3/3. Legacy caches fail closed; full tree and selected archive digest checked without forced online access.
- [x] Storage: old7f8b quota failures reproduced; opt-in shared accounting and Mirror new-artifact rollback implemented; final52ce18/18. A reviewer dangling-link hypothesis actually passed before changes and is retained as a regression, not called a fix.
- [x] Maple: multiple-dependency freezing and explicitly reviewed fake-tool line normalization added. New9d35 cases12/12, no overlap with previous1179 or changes to official assertions. Old14 failures retain their candidate identity.
- [x] Rotation: offline private candidate preparation and verification implemented; CR-only false replacement reproduced and fixed. Actual new bundle participates in stopped token/CA-overlap/cold-build acceptance12/12; this is not production CA rollout.
- [x] Freeze changed inputs, build serially, run scoped acceptance, obtain independent reviews, refresh candidate/verification/delivery docs and perform authorized ordinary dual-main synchronization. Source/AtomGit b83ebfa8 and GitHub mirror8b3706b5 have the same3790bf2d tree; both remote main heads were read back. No origin push, Release or tag.

Native four suites passed across two batches; the first staging-path failure and600-second combined-controller interruption remain recorded. Same final archives independently passed receiver34/34,restore23/23,snapshot18/18,upgrade22/22 after one retained20/34 timeout. New/old pure-bundle differential both passed without confirming that timeout's root cause. The receiver now retains redacted timeout output and best-effort owned-container diagnostics; diagnostic writes do not block subsequent cleanup steps. Review findings were addressed via RED-to-GREEN tests. Final audit checked frozen client/server source, both archives and members, actual summaries,266 relative links and changes; this image's test containers/volumes and owned Linux test processes were empty. This completes this scoped hardening stage, not the external/architectural boundaries below.

## Remaining external or architectural boundaries

Cross-physical-host HTTPS, Windows security-policy diagnosis, actual enterprise CA distribution and hour/day production stability need their real environments. Multi-instance failover, online backup consistency, build sandboxing and signatures require separate designs and trust/deployment choices; do not improvise them into this patch or call them complete.
