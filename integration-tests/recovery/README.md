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
