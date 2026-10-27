# Extracted repository source cache integrity

The client verifies repository source caches before reuse. A successful archive download is checked against the selected index SHA-256, extracted, and given a small sidecar receipt. The receipt binds that archive digest to the sorted relative directory/file set and each regular file's content digest. File hashes use a 64 KiB read buffer; receipt reads are limited to 513 bytes and reject content larger than 512 bytes.

An unchanged cache and local index remain reusable without artifact network access. A changed, added, missing, truncated or linked entry, malformed/missing receipt, changed selected archive digest, or occupied extraction path fails admission before compilation. The client preserves the existing files instead of silently deleting or overwriting them.

## Existing caches

Older extracted caches have no receipt and are deliberately not trusted automatically. Choose a **new** `[repository.cache].path` in `cangjie-repo.toml` and warm that cache from the intended repository. Keep the previous directory for inspection; do not remove its receipt or copy a receipt from another cache to bypass an error. Auth/route/source-baseline checks still apply to the new download.

Repository installation uses a unique temporary build copy. Generated targets, lockfiles and provenance stay in that copy; the original extracted source and its receipt remain unchanged. Only the work directory created by that installation is cleaned up.

## Scope

This detects source-cache inconsistency after an archive-verified extraction. It does not authenticate a publisher, sign a package, or resist an actor who can modify both the source and its receipt under the same account. It does not cover generated compiler artifacts, permissions, hard-link identity, concurrent same-account mutation after verification, or multiple CLI processes sharing extraction destinations. Use separately owned job caches for concurrent jobs.

The solver and official lockfile format are unchanged. Recorded provenance is still an explanation record, not a signed build attestation or a substitute for source verification.

## Reproduce

With the existing Linux SDK/stdx environment and a newly built client:

```bash
python3 -B integration-tests/compatibility/cache_integrity.py --cjpm /path/to/cjpm --evidence-dir /path/to/new-cache-report
python3 -B integration-tests/compatibility/cache_install_integrity.py --cjpm /path/to/cjpm --evidence-dir /path/to/new-install-report
```

Both commands use owned synthetic fixtures. They preserve failed evidence and do not access an existing user cache. Exact binary identities and actual results are recorded separately in the verification report.
