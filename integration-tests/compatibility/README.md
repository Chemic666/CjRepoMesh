# Reviewed Maple compatibility runs

`maple_reviewed.py` runs an explicit allowlist of official `.info` files with the
official Maple framework. It never discovers or automatically approves an entire
suite. Review each command, `DEPENDENCE`, called script, source and configuration
before creating the manifest. Network addresses, publication, credentials,
platform tools and paths outside the owned fixture need separate review.

A schema-1 manifest freezes `clientSha256`, all `frameworkFiles`, the relative
`config` and `configSha256`, and a nonempty `cases` list. Each case contains its
upstream-relative `path`, a review `reason`, and every fixture file's SHA-256 in
`files`. Dependencies outside that case directory must also be explicitly frozen
under `dependencies`, keyed by upstream-relative directory. Added, removed or
changed fixture/helper files fail preflight. Unsupported dependency directives
also fail closed. The manifest is an approval record, not a security sandbox;
hashes establish reviewed input identity rather than making arbitrary code safe.

Load the existing Linux SDK and stdx environment, then verify without execution:

```bash
python3 integration-tests/compatibility/maple_reviewed.py \
  --manifest /owned/reviewed-allowlist.json \
  --upstream /existing/official-tests \
  --framework /existing/official-framework \
  --client /existing/frozen/cjpm
```

Add `--execute --results /owned/new-results` to execute. `--stage-parent` may
name an existing owned Linux scratch directory to avoid WSL filesystem overhead;
otherwise temporary files live under `integration-tests/.tmp`. Windows execution
is rejected. No dependencies are installed or downloaded by the runner.

Each case receives a fresh HOME/USERPROFILE and config directory, with inherited
`CJPM_CONFIG` and CjRepoMesh overrides removed. The framework and fixtures are
copied into an owned stage. Only CRLF line endings in `.sh`, `.py`, `.toml` and
`.cj` copies are normalized; official assertion files are preserved. This
normalization is recorded per case. The runner records PASS, FAIL, SKIP, timeouts,
exit codes and private logs separately, continues after an ordinary case failure,
and removes only its owned temporary directories/process groups. Source inputs
are checked again after the run. Fixture stabilizations that change behavior
must use a separately reviewed manifest and be reported separately.
Temporary stage names use an underscore prefix so a random leading character
cannot become a spurious compiler-option match such as `-g` in verbose paths.

`summary.json` includes the binary, manifest, runner and per-log hashes. Paths and
raw diagnostic logs are private evidence; publish a reviewed aggregate rather
than uploading logs. A selected run, an interrupted run and a stabilized fixture
are not full Maple acceptance. Differential diagnosis should rerun the relevant
failing cases with the official binary rather than silently dropping failures.

Fast Python regressions (no Cangjie process):

```bash
python3 -m unittest discover -s integration-tests/compatibility -p 'test_*.py' -v
```

`source_set_compiler.py` exercises CHIR argument capability handling with the
separately reviewed official `source_sets/always_enabled_check` fixture. Its six
checks cover an invalid-option diagnostic with exit zero, supported named-option
syntax, probe execution failure, ambiguous output, two independent source-set
libraries sharing the capability cache, and ordinary builds that must not probe.
The named-option test records cjpm's real argument list, then uses a
synthetic compiler adapter to run it on the existing legacy SDK; this establishes
argument selection, not actual acceptance on a newer compiler.
The concurrent sample did not reproduce duplicate probes before synchronization;
the dedicated cache mutex addresses the static check/probe/set race without a
claim of an observed failing concurrency sample.

Each capability case uses its own Linux process group. Timeouts kill that group;
normal completion also cleans up remaining descendants before removing the
stage. Timeouts and absent or malformed compiler-call records are explicit
failures with logs and a summary. `test_source_set_compiler.py` checks this with
synthetic parent/child/grandchild processes and never invokes Cangjie; these
process-group tests are skipped on Windows. `--case` selects a named capability
case without changing its assertions.

```bash
python3 integration-tests/compatibility/source_set_compiler.py \
  --cjpm /existing/candidate/cjpm --cjc /existing/sdk/bin/cjc \
  --fixture /existing/official-tests/testsuites/LLT/Tools/cjpm/CJNATIVE/source_sets/always_enabled_check \
  --results /owned/new-chir-results --stage-parent /owned/linux-scratch
```
