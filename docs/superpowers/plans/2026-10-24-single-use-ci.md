# Single-use cold consumer tasks

> **For agentic workers:** Use superpowers:executing-plans inline under the existing autonomous development authorization, followed by one final independent review and the established ordinary dual-main delivery.

**Goal:** Make an explicitly selected fresh CI workspace refuse cached/reused execution and concurrent starts without deleting previous data.

**Architecture:** Extend existing `examples/team/prepare.py` with consumer-only `--single-use`. Copy a small standard-library `job.py` guard, pin the generated repository configuration's actual bytes, and inject the guard after capability/CA checks but before build. Require a nonempty main source baseline, ordinary empty task HOME and absent cache/build/lock/provenance paths; atomically create a permanent task claim directory. Keep the claim on success or failure; operators prepare a new task instead of resetting it. Ordinary tasks remain unchanged.

**Tech Stack:** Existing Python/Bash templates and fixed f433 Linux client/8fc3 server. No downloads, binary/image rebuild, physical receiver, system policy or approval changes.

**Spec:** Existing isolated CI task contract and the user's authorized reliability work. Existing source caches are reused without retained CJP revalidation. Choose explicit refusal of pre-existing CI state over a new cache attestation/retained-archive design; this mode is not unpacked-cache verification or a script sandbox.

## Constraints and review focus

- Failures before claim do not alter existing files, links or state; do not read/write credentials or approval contents.
- Configuration pin and cold-state checks precede atomic claim; concurrent attempts may query static capabilities but at most one proceeds to build.
- Keep claim and failed outputs; no reset/cleanup/retry automation, lock leases or transactional claims about power loss/concurrent hostile edits.
- Do not expose a final run.sh if preparing the helper/metadata/script fails. Preserve normal HTTP/HTTPS, source admission, script override and application exit status behavior.
- Pin only the generated repository configuration, not arbitrary task code/toolchain; prepared task files and environment remain trusted inputs.

## Tasks

- [x] Add focused RED tests for API/CLI preparation, default compatibility, helper preparation failure, configuration/state refusal, dangling links, atomic claims, repeated launches and build/application failure retention.
- [x] Implement guard and consumer-only preparation mode; final related Windows51 tests38 passed13 skipped, Linux51/51; complete bundle capability25/25, no registry requests. Default tasks retained; initial50-test evidence retained.
- [x] Fixed complete client through real owned HTTPS publication and independent approved cold CI: final9/9,176.70s,cleanup empty. Repeated/state refusals made no new connection; twin starts yielded one real build; source/application failures preserved the claim.202 inputs and review overlay frozen; initial WSL startup failure and initial9/9 retained; no host change.
- [x] One final read-only review; its P2 evidence-creator race reproduced RED1 then fixed with explicit directory ownership. Fresh51-test suite and new-directory9-stage acceptance passed; public usage/results updated, no deferred material findings.

Publish after auditing explicit stage files: commit, append same-tree GitHub mirror, ordinary dual push and readback. Final publication identities are recorded separately after pushing.
