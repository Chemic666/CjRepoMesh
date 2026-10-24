# Offline restore input preflight

> **For agentic workers:** Use superpowers:executing-plans inline under the existing autonomous stage and dual-main delivery authorization, with one final independent review.

**Goal:** Let operators check a backup against an unconfigured target bundle without Docker or deployment writes, then use the same input checks for actual restoration.

**Architecture:** Add `maintenance.py restore --check-only`, sharing input validation with normal restore. Emit only a small non-sensitive JSON result; do not reserve a project, volume or port. New bundles advertise `restorePreflight=offline-inputs-v1`; legacy manifests remain supported. Refuse existing restore.json as well as configuration/trust before any restore-side operations.

**Tech Stack:** Existing Python standard library, fixed bad0/8fc3 server and 067b client, existing Docker Desktop/SDK/native tools. No installs or binary rebuilds.

**Spec:** Existing stopped-backup/new-volume-restore contract and the user's request to continue complete connected stages before reporting.

## Constraints and review focus

- Check-only must not invoke Docker, allocate identities, write target/config/approval files or output credentials, upstream URLs or archive paths.
- Validate full backup integrity, exact image/server identity, target freshness and explicit port; invalid inputs leave original files intact.
- Normal restore reuses checks, still revalidates runtime/archive, creates only a new owned volume and remains stopped.
- Offline success does not establish runtime image availability, available ports/space, permissions or future concurrent state.
- Preserve old deliveries/evidence and expose the new option only in a newly verified tool bundle. No physical receiver, Windows Cangjie or system/network/security changes.

## Tasks

- [x] Add RED/GREEN offline/read-only, malformed/legacy capability, port/image/backup and stale marker tests; implement shared checks and minimal JSON CLI. Include real CLI Python-cache RED/GREEN.
- [x] Add optional `--restore-preflight` to the existing maintenance acceptance, proving execution without Docker on PATH and subsequent actual cold restoration.
- [x] Run affected Python tools on Windows/WSL; export a new nine-file bundle and exercise actual maintenance preflight/restore plus receiver runtime on fixed binaries. Windows98 passed/4 skipped, Linux102/102; actual23/23 and18/18, cleanup empty; new archive frozen, old archives preserved.
- [x] Obtain one final read-only review; record exact new bundle identities, results and remaining limits in existing delivery documents. No material findings; 16 frozen source inputs and archive/manifest/nine members matched the actual tested package.

Publish only verified stage files to atomgit/main and github/main through ordinary pushes. Final Git identities and same-tree readback are recorded separately after publication.
