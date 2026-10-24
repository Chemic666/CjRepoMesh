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

When host Cangjie execution is unavailable, use the complete Linux client delivery in owned job containers:

```cmd
python integration-tests\recovery\test_docker_client.py
python integration-tests\recovery\docker_backup.py --image <existing-local-image> --client-bundle <complete-client-directory> --client-sdk <existing-Linux-SDK> --client-native <existing-native-tools-directory> --evidence-dir <new-evidence-directory>
```

`--client-bundle` and `--cjpm` are mutually exclusive. The bundle is checked with the source repository's trusted verifier before Docker or evidence writes; the candidate verifier is not executed during preflight. Linux jobs still need the matching SDK, Python 3, ar/ld and system link inputs. The optional native-tools directory uses the same `bin/`, `lib/` and `system/` layout as the [team acceptance runner](../README.md); it mounts existing tools read-only and never installs or downloads them. All client commands run through the complete bundle's `run.sh`, with stdout and stderr retained and the actual container exit checked.

Bundling jobs have no network. Each consumer starts with its own HOME/cache and shares only the owned restored server's network namespace, reaching its internal loopback port. The host server remains bound to `127.0.0.1`; no WSL-to-host networking changes are needed. This is an isolated container recovery drill, not cross-host deployment. In bundle mode, `runtime.json` records the image/server/client identities; `summary.json` records checkpoints and cleanup status in both modes. The client bundle is rechecked after all operations; tools and credentials remain separate from the storage backup.

## Portable CA configuration and data cold restore

The standard CA-capable seven-file server bundle has a separate combined acceptance path:

```cmd
python integration-tests\deployment\portable_ca.py --bundle <unconfigured-server-directory> --package-dir <real-default-meshdep-CJP-directory> --native <existing-Linux-tools-directory> --openssl <existing-Linux-OpenSSL-file> --evidence-dir <new-private-evidence-directory> --cold-restore --client-bundle <complete-Linux-client-directory> --client-sdk <existing-Linux-SDK> --expected-output high-1.0.0
```

Use the real `meshdep` fixture whose `registryMarker()` returns the supplied output marker. The default marker matches the existing high-priority 1.0.0 fixture. Inputs must already exist; no image pulls, dependency installation, host Cangjie or system trust changes occur. The source repository's trusted verifiers check both deliveries before evidence creation. The native tools use the same `bin/`, `lib/`, `system/` layout as the container-client runner above. Keep evidence outside the public checkout: it retains synthetic credentials and backup data.

Without `--cold-restore`, the runner keeps its ten-stage CA/HTTPS acceptance. The optional fifteen-stage path first populates a genuine CJP cache through an owned HTTPS upstream, then removes that upstream. It creates a protected configuration backup with the existing configure tool, stops the source Compose project, and exports/validates the full data volume. Another unconfigured copy receives the backed-up CA and credentials; only its randomly generated project identity changes. A separate volume must match the archive file set and hashes before startup.

The recovered standard Compose deployment passes `verify.py --running` and private reads while the source remains stopped. A fresh consumer uses the complete client's `run.sh`, with the existing Linux SDK/tools read-only, and actually builds/runs from the restored cache. The final recreation checks credentials/CA/cache retention and unchanged original data/configuration/archive. Runtime summaries and logs hide the generated tokens. Cleanup targets only recorded owned containers/projects; retained `.env` files are private, not ordinary log material.

This is a stopped synthetic configuration/data recovery drill for one default-organization proxy-cache package. It does not replace the separate organization/publication checks, test live snapshots, business cutover, power-loss durability or cross-host recovery, or provide automatic business backup, CA rotation or upgrade/rollback. See the [actual verification record](../../docs/verification-report.md).

## Stopped-volume upgrade and rollback

Use two existing local Linux amd64 server images and two genuine prebuilt CJP fixtures. The seed is a default-organization package; the new package belongs to a named organization. No SDK execution or downloads are required:

```cmd
python integration-tests\recovery\upgrade.py --previous-image <old-local-image> --candidate-image <new-local-image> --seed-package <default-package-target> --new-package <organization-package-target> --evidence-dir <new-evidence-directory>
```

This creates three new labeled volumes and an ephemeral loopback port. The 14 checkpoints pin distinct image and server identities; publish the old seed; stop all owned writers before a complete archive; restore a byte-identical candidate volume; check new reads/writes and old-version reads of candidate data; reject a controlled invalid startup configuration; restore the original snapshot into another empty volume; verify that later writes are absent; publish again, recreate the recovered server, and preserve original/candidate/backup bytes independently. The same generated read/publish credentials are checked across switches, without recording raw container environments.

Only owned, label-verified resources are removed on success. Failures retain volumes and evidence and attempt to stop owned writers. The runner does not accept existing business volumes and is not an automatic production upgrade command. Snapshot rollback deliberately excludes post-snapshot writes; real maintenance must pause publishers or reconcile later data. The controlled startup failure is not a post-write crash or format migration. The default 14-check mode reads real archives without compiling client projects. See the [maintenance procedure](../../docs/upgrade-and-rollback.md) and [actual verification scope](../../docs/verification-report.md).

To include the current complete Linux client, append these existing read-only inputs to the same command:

```cmd
--client-bundle <complete-Linux-client-directory> --client-sdk <existing-Linux-SDK> --client-native <existing-Linux-tools-directory> --expected-output high-1.0.0
```

This optional mode requires a default-organization `meshdep` fixture with `registryMarker()` and the real `company::teamhello 1.0.0` fixture with `teamGreeting()`. The expected marker must match the seed CJP. Argument checks and complete-client verification run before Docker operations or evidence creation. No Windows Cangjie executes.

The extended 18-check mode adds four distinct cold consumers: candidate after publication, old server reading candidate data, snapshot rollback before republishing (seed-only graph), and rollback after republishing (both packages). Every consumer starts without cache/target/lock, requires `source-baseline-v1`, builds and runs an actual application, and checks complete provenance against an independent exact graph made from the trusted input CJP identities. Its approval is outside the job and mounted read-only; it is never copied from generated provenance. Separate approvals are needed for the seed-only and two-package graphs.

Consumers use the selected candidate image only as an existing tool container and share the owned server's network namespace at its internal loopback address. The client, SDK and native tools are mounted read-only; only the fresh job and temporary filesystem are writable. Only the generated reading credential is injected, by environment-variable name rather than command-line value. This does not migrate the portable Compose/CA configuration, test HTTPS or any real service cutover, or prove arbitrary older versions compatible. Private evidence retains synthetic data and approvals outside the public checkout.

For four additional single-use replay checks, add `--single-use-clients` to that complete-client command. This option requires `--client-bundle` before any fixture/evidence/Docker operation. The22-stage mode copies the existing team `job.py` guard into each fresh consumer and pins its generated repository configuration. Each task claims once before build, then retains its claim and outputs. The application checks that example read/publish credential variables are absent; only its process loses those variables, so recorded source explanation still uses the read credential.

After each successful build/run and exact provenance check, the runner starts the same stopped consumer again. It requires exit2 and the guard's refusal diagnostic, no application output, and identical task entry types/file bytes plus unchanged independent approval. A wrong exit status, unrelated error or modified state fails the drill. The four refusals are separate checkpoints from the four real builds. Ordinary14/18-stage modes remain available; no task reset or deletion is provided. This is accidental-reuse protection for controlled tasks, not cache-content attestation, hostile concurrency isolation or a measured zero-request guarantee.

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
