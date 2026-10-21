# Hosted and Sync interruption recovery regressions

Load the existing Cangjie runtime and build the server, then run from the repository root:

```cmd
python integration-tests\recovery\run.py
```

The runner uses Python's standard library and the shared process/HTTP harness. It starts only its own server on `127.0.0.1:39610`, uses a unique storage directory under `integration-tests/.tmp`, and stops its own processes. A successful run removes its directory; failures retain storage and server logs for inspection. `--server` and `--port` override the defaults.

The 23 cases cover:

- complete publication and immutable duplicates;
- artifact-only recovery, including authentication and checksum conflicts;
- index-only recovery without changing existing metadata;
- prior-version preservation and indexes without a final newline;
- concurrent retries of both incomplete states;
- malformed, ambiguous, wrong-SHA and unsafe-version stored indexes;
- index-write failures: retaining existing bytes versus rolling back only newly written bytes;
- organization isolation and retained data after restart;
- neighboring package names ending in `.tmp`;
- private, stale temporary files and a subsequent successful retry;
- an actual forced termination during an incomplete HTTP upload, followed by restart and publication.

Persisted intermediate states are injected deterministically. The actual process kill tests an incomplete upload; it does not claim to time a kill exactly between two filesystem renames. Small synthetic protocol payloads isolate storage behavior; the normal Hosted/Proxy/Sync suites separately exercise real cjpm archives and builds.

These checks establish the tested single-process recovery behavior, not power-loss durability, filesystem `fsync` guarantees, or coordination between multiple processes sharing one storage directory.

## Cold filesystem backup and restore

Load the matching SDK and stdx environment, then use the existing server and enhanced cjpm binaries:

```cmd
python integration-tests\recovery\backup.py --cjpm cjpm\target\release\bin\cjpm.exe
```

On Linux use the same Python entry point with `--cjpm cjpm/target/release/bin/cjpm`. The server defaults to the corresponding platform binary. `--server` and `--port` override the defaults; the default port is `39630`. Optional `--evidence-dir` must name a new directory outside the test's temporary storage and retains bundle, server and consumer logs plus the backup hash manifest. Without it, logs are removed along with successful test storage. Failures retain the owned storage directory.

The 10 checkpoints use real `cjpm bundle` archives and cover:

- private publication and reads of two default-organization versions and a named-organization package;
- stopping the owned source before copying its complete storage, with file-set and SHA-256 equality;
- detecting a modified artifact and a missing index by comparing deliberately damaged copies with the original manifest;
- making the original storage path unavailable and restoring the backup into a new directory;
- downloading, building and running default and named-organization consumers with fresh project caches;
- immutable duplicate rejection, publication of another real version and persistence after restart;
- verifying that restored writes do not change the backup or the offline original.

The runner only starts its own processes and uses a unique directory under `integration-tests/.tmp`, including an isolated HOME/USERPROFILE and local repository/cache configuration for every package fixture. The damage checks exercise the test's manifest comparison, not an automatic backup-validation service. This is a stopped-instance filesystem copy drill; it does not test Docker-volume backup, live snapshots, deployment cutover, power-loss durability or automatic scheduling. Credentials are synthetic process configuration and are not included in the package-storage backup.

## Docker volume cold backup

```cmd
python integration-tests\recovery\docker_backup.py --image cjrepomesh:local --cjpm cjpm\target\release\bin\cjpm.exe
```

This separate runner requires an existing local Linux CjRepo image and the matching host cjpm environment. It pins the local image ID and uses `--pull=never`. Nine checkpoints cover real package publication, a stopped source volume exported as tar, validated extraction into a different volume, complete file-set/SHA-256 equality before startup, private reads, two fresh-cache client builds, duplicate rejection/new publication, restart and preservation of the original volume and archive. Helpers have no network, export mounts are read-only, and the restored server uses the image's non-root account.

It binds only `127.0.0.1:39640` by default (`--port` overrides it), isolates client HOME/USERPROFILE and per-fixture repository/cache configuration, and never loads the deployment `.env`. All Docker resources are uniquely labeled; only owned container IDs and matching labeled volumes are removed. Failed runs capture container inspect data and combined logs before removing containers and retain volumes plus local fixtures; a diagnostic-capture failure keeps the affected container after attempting to stop it. Optional `--evidence-dir` names a new directory retaining logs, runtime identity, the manifest and synthetic `backup.tar`. Without it, successful local evidence is removed.

This is an isolated deployment test, not a command to back up an existing business volume. It does not establish online backup consistency, automatic scheduling, production cutover or power-loss durability.

## Repository Sync

```cmd
python integration-tests\recovery\sync.py
```

This separate runner uses a real private CjRepo destination, a synthetic source registry, and an HTTP relay with explicit event gates. It binds three consecutive loopback ports starting at `39620`; `--server` and `--port` override the defaults. It uses unique storage, stops only processes it created, cleans successful runs and retains failure evidence.

The 12 checks cover fresh transfer, a verified rerun without downloading the source artifact, artifact-only and index-only destination recovery (including a named organization), corrupt artifact rejection, conflicting versions, index-commit failure and retry, destination read authentication and artifact permission failures, and three real forced-termination scenarios:

- kill the Sync worker while a source artifact response is incomplete;
- kill the worker after the destination commits but before it receives acknowledgement;
- kill the destination after the relay forwards only part of the upload, then restart and rerun.

Persisted destination states are injected between requests. HTTP gates control the tested interruption points, rather than relying on sleeps or claiming a kill between filesystem renames. Payloads are synthetic protocol fixtures; the normal Sync suite separately validates real cjpm packages, builds, manifests and watchers. These tests do not establish power-loss durability, distributed coordination, byte-range resume, or every possible timing interleaving.
