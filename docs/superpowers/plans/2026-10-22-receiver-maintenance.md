# Receiver maintenance implementation plan

> **For agentic workers:** Use superpowers:executing-plans for inline implementation and one independent final review. Steps use checkbox syntax for tracking.

**Goal:** Give a portable-bundle receiver a stopped backup and new-volume restore tool, then exercise the current client with an independently approved source baseline after recovery.

**Architecture:** Add one standard-library Python entry point to the portable bundle. Reuse bundle verification, credential-file protection and the existing local image; stream Docker tar output and validate every archive member before restore. Never stop a deployment, overwrite an existing target, switch traffic or remove a business volume automatically.

**Tech stack:** Python 3.10+, existing Docker Engine / Compose v2; unchanged Linux client 067b92c8, server 8fc30842 and image bad02ad7.

**Spec:** The accepted maintenance-stage proposal in this conversation, expanded by the contracts below.

## Global constraints

- Windows remains the source checkout; execute Cangjie only in Linux validation environments.
- Keep existing inputs, old archives and failed evidence. Use a unique local evidence directory outside the public repository.
- No solver, lockfile, source-baseline or server-storage format changes; no downloads, automatic image pulls or host security changes.
- Backup only a verified portable deployment with its writers stopped. Restore only into an unconfigured verified bundle and a newly created volume; retain the original volume.
- Backup contains private data and credentials. Create protected files before writing bytes; never print Docker inspect/config output or secret values.
- Version one accepts literal generated-style dotenv lines, rejecting duplicate keys, interpolation and ambiguous quoting. Preserve original credentials and settings; change only the new project identity and an explicitly supplied port.
- A backup is an integrity-checked stopped snapshot, not a signature, online backup or guaranteed crash-durable transaction. Do not operate concurrently with deployment management.

## Review focus

- Archive traversal, links, duplicates and file/directory collisions must fail before any extraction.
- A running foreign container mounting the source volume read-write must block backup.
- Existing output/config/trust/volume identities must not be overwritten or adopted.
- Unknown capability metadata, corrupt backup entries and image mismatch must fail closed.
- Failures must not echo credentials or discard original data and diagnostic evidence.

## Task 1: Receiver maintenance and bundle integration

**Files:** Create `deployment/portable/maintenance.py` and `integration-tests/deployment/test_portable_maintenance.py`; modify portable `verify.py`, `package.py`, `README.md`.

**Interfaces:** `archive_manifest(path: Path) -> dict`, `verify_backup(root: Path) -> dict`, `backup(root: Path, output: Path) -> dict`, `restore(root: Path, source: Path, port: int | None = None) -> dict`. CLI: `backup --output NEW_DIRECTORY`, `verify-backup --backup DIRECTORY`, `restore --backup DIRECTORY [--port PORT]`.

- [x] Write rejection/format/credential-preservation tests and observe expected failure for the absent entry point.
- [x] Implement strict archive and backup validation, protected output files and the Docker stopped-writer checks.
- [x] Implement backup, then restore to a new labelled volume without starting the service. Verify restored file identities by a second streamed export; preserve failed restore resources.
- [x] Declare `maintenance=cold-backup-v1` and include the new file in new packages; retain strict verification of genuine legacy seven-file packages.
- [x] Run the related portable deployment tests; exercise actual backup/restore and rejection paths against isolated Docker resources.

## Task 2: Failure evidence and protected recovery acceptance

**Files:** Modify `integration-tests/run.py`, `integration-tests/lib/harness.py`, `integration-tests/lib/suites.py`; add targeted harness tests and extend the existing `integration-tests/deployment/portable_ca.py --cold-restore --maintenance` acceptance runner.

**Interfaces:** Failed core runs retain their own temporary directory; health readiness accepts the owned child process/log identity and reports early exit without printing the log body.

- [x] Reproduce lost failure logs and missing early-exit information with small synthetic child processes, then implement the targeted fix.
- [x] Prepare a new complete server bundle using the same image. Use current complete client and existing SDK/native tools only.
- [x] Run real private publication/consumption, stopped backup, restore and empty-cache protected build/run with the original registry URL preserved; test baseline drift refusal and unchanged approvals.
- [x] Confirm old data/backup retention, restored-instance recreation, tool rejection paths and resource ownership during cleanup. This is same-host isolated validation, not a fresh-host or inbound-HTTPS claim.

## Task 3: Review and delivery

**Files:** Update current sections of `docs/candidate-acceptance.md`, `docs/verification-report.md`, `docs/delivery-record.md`, `docs/upgrade-and-rollback.md`, and integration test instructions.

- [x] Review the complete diff independently and fix substantive findings with targeted red/green verification.
- [x] Record exact unchanged binary/image identities, new bundle/archive identity, actual results and remaining limits.
- [ ] Inspect explicit staged paths for private inputs, commit the completed stage, append the GitHub mirror commit with the identical tree, push only atomgit/main and github/main, and read back both remote heads.

## Execution record

- Initial checkout clean at `010f7a9f2d84f5bf044feebdc5b04f51b9b98641`; both remote main heads match the prior delivered source/mirror pair.
- Reuse the user-specified feature branch and checkout; no new worktree or dependencies are needed. Commit once at the completed stage, as authorized.
- Local evidence root: a newly created `test-runs/maintenance-tools-20261022` outside the source repository.
- Reuse the existing CA/cold-recovery runner instead of creating a second orchestration implementation. Maintenance mode adds actual tool calls, real Hosted organization publication and a two-package independently approved cold consumer.
- The prototype completed its 20 functional checks but failed cleanup log collection because Windows selected GBK for UTF-8 Docker output. Keep that failed record and its volumes; explicit UTF-8 decoding now has a red/green regression. The 2026-10-23 continuation found the Docker engine stopped before the next run's first container; that preparation failure is also retained.
- Independent review found two Important issues: unchecked root tar headers and erased helper failure diagnostics. Both reproduced in red tests and were fixed in one pass; maintenance units 18/18 and real Docker failure/timeout retention 2/2. No Critical or Minor findings. Documented exclusions remain unchanged.
- Final complete package acceptance: 21/21, 88.03s, cleanup errors zero; Linux portable tests 65/65, Windows 61 passed plus four link-permission skips; harness tests 4/4 on each platform, native Sync 1/1, 38.80s. New archive identities and precise limits are in the candidate/verification records.
- This plan is frozen before the stage commit. The final Git commit/push/read-back operation is recorded in the task result and private delivery record, not inferred from this checklist.
