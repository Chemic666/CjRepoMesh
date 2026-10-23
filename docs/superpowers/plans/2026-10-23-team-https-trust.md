# Team HTTPS process trust

> **For agentic workers:** Use superpowers:executing-plans inline; follow the user's existing autonomous stage and dual-main delivery authorization.

**Goal:** Prepare standalone team publisher/consumer tasks for an approved HTTPS CA without manual SSL environment wiring or system trust changes.

**Architecture:** Add optional `--ca-file` / `--ca-sha256` to the existing preparer. Validate a bounded regular certificate-only PEM before output creation, copy public trust plus a standalone verifier, and generate a fixed trust-preflight block in the existing run scripts. Explicit CA tasks pin the copied bytes and an empty CA directory before any client call. Default preparation remains unchanged.

**Tech Stack:** Existing Python standard library, Bash, fixed Linux client/SDK/server; no downloads or new dependencies.

**Spec:** Existing team example and source-baseline contracts, plus the actual manual CA wiring needed by the completed cross-host cold-consumer trial.

## Constraints and review focus

- No physical receiver involvement, real credentials, network/security policy changes, system CA install, old approval rewrites or Windows Cangjie execution.
- CA options require HTTPS; SHA without CA, invalid/oversized/linked/private-key PEM and mismatched digest must fail before workspace creation, without reflecting file contents.
- Prepared scripts remain standalone and movable; missing/modified CA or a nonempty extra trust directory must fail before any client call.
- Override SSL_CERT_FILE/SSL_CERT_DIR only for explicitly prepared CA tasks; never weaken strict TLS. This is process configuration, not a sandbox against malicious job edits/toolchains.
- Preserve baseline admission and read/publish credential separation. Never derive approvals from current provenance.

## Tasks

- [x] Add focused prep and Bash subprocess regressions; observe RED then GREEN. Windows10 passed/5 environment skips; WSL15/15.
- [x] Implement optional bounded public CA import, pinning and generated script preflight; preserve default API calls.
- [x] Run Python tests on Windows/WSL and actual Linux publisher/consumer through an owned loopback HTTPS gateway, including wrong CA/IP and missing/modified trust rejection. Native6/6,14.13s,cleanupErrors=[].
- [x] Obtain one final read-only review with no material issues and record actual scope. Authorized ordinary dual-main delivery identities are recorded separately after Commit/Push.

Stop after this stage; no production certificate rotation, hostname service, custom PKI or new transfer product.
