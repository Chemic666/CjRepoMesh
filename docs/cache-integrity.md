# Extracted repository source cache integrity

The client verifies repository source caches before reuse. A successful archive download is checked against the selected index SHA-256, extracted, and given a small sidecar receipt. The receipt binds that archive digest to the sorted relative directory/file set and each regular file's content digest. File hashes use a 64 KiB read buffer; receipt reads are limited to 513 bytes and reject content larger than 512 bytes.

An unchanged cache and local index remain reusable without artifact network access. A changed, added, missing, truncated or linked entry, malformed/missing receipt, changed selected archive digest, or occupied extraction path fails admission before compilation. The client preserves the existing files instead of silently deleting or overwriting them.

## Existing caches

Older extracted caches have no receipt and are deliberately not trusted automatically. Choose a **new** `[repository.cache].path` in `cangjie-repo.toml` and warm that cache from the intended repository. Keep the previous directory for inspection; do not remove its receipt or copy a receipt from another cache to bypass an error. Auth/route/source-baseline checks still apply to the new download.

Repository installation uses a unique temporary build copy. Generated targets, lockfiles and provenance stay in that copy; the original extracted source and its receipt remain unchanged. Only the work directory created by that installation is cleaned up.

## Official legacy-cache compatibility

The historical original-mode replay retains four failing fixtures: `check/coverage/central_dependency_cached`, `check/coverage/central_dependency_transitive`, `install/coverage/repository_cached`, and `update/coverage/central_dependency_cached_update`. All preseed bare extracted source without a matching CJP or receipt. The three check/update inputs contain empty selected `sha256sum` values; installation also lacks the package index and is rejected before receipt verification. The configured closed loopback endpoint cannot supply those missing trusted materials. This does not prove the existing source is corrupt.

Keep the original FAIL records and previous directories. Configure a new cache path and download from the intended trusted repository; do not manufacture receipts or relax admission. `integration-tests/compatibility/maple_verified_cache.py` separately prepares real bundled CJP artifacts, obtains indexes with matching SHA values, and lets actual client download/extraction create receipts. It then checks the four original business expectations, including offline reuse and installed program output. Package metadata/README preparation and every input hash are recorded; the original fixture trees remain unchanged.

```bash
python3 -B integration-tests/compatibility/maple_verified_cache.py \
  --cjpm /path/to/cjpm --suite-root /path/to/cangjie-test/testsuites/LLT/Tools/cjpm/CJNATIVE \
  --evidence-dir /path/to/new-prepared-cache-report
```

The final candidate passed this separate prepared 4/4 check. These results are not original Maple passes, and the final candidate's 72-case targeted replay is not a replay of the historical 1248-case suite. Exact identities and retained failures are in the [verification report](verification-report.md).

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
