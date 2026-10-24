# Separate script source admission

> **For agentic workers:** Use superpowers:executing-plans inline under the user's existing autonomous development and dual-main publication authorization; obtain one final independent review.

**Goal:** Allow a build script and its application to use different independently approved complete repository graphs.

**Architecture:** Add optional `CJREPOMESH_SCRIPT_SOURCE_BASELINE`, selected only for the existing `isScriptDep` analysis context. Require the ordinary `CJREPOMESH_SOURCE_BASELINE` whenever the script override is set. Unset override preserves v1 behavior; both documents retain provenance-v1 format and exact set/source/SHA matching. Reject either configured path if it aliases this analysis's final or temporary provenance output. Advertise `script-source-baseline-v1` through the existing offline capability query.

**Tech Stack:** Existing Cangjie 1.1.3/STDX, Python regression runners and Linux validation copy. Windows remains the source; no new dependencies, solver/lockfile changes, server rebuild or physical receiver access.

**Spec:** Existing source-admission contract in `docs/repository-source-baseline.md` and the user's instruction to choose useful connected stages autonomously. Separate explicit approvals are chosen over set union/subset matching or a new multi-graph document format: they preserve exact matching and existing snapshot compatibility.

## Constraints and review focus

- Propagate the existing script-analysis context, never mutate process environment to select an approval.
- Empty override or missing main setting refuses; invalid selected documents refuse before that graph's artifact downloads.
- Protect both configured approval paths during either analysis, including canonical final/temporary aliases.
- Earlier approved script actions are not rolled back if the main graph later refuses; cached/relocated scripts remain governed by the existing lifecycle, not a sandbox or whole-command transaction.
- A script-specific document is shared by all script analyses in that command; arbitrary different nested script graphs remain unsupported.
- Old artifacts, logs and approved files remain intact. New client binary/package identities receive fresh results; historical results are not transferred.

## Tasks

- [x] Extend graph and offline capability runners; observe old-client failures for separate approvals, drift, missing/invalid override and inactive-path aliases. Old graph3/12 plus1/3 and capability21/25 retained.
- [x] Propagate script context and implement explicit selection, path guards and capability token. Final expanded graphs29/29, baseline37/37, capability25/25, recorded13/13, TLS19/19 and native core4/4 on the frozen source copy. Windows team17 passed7 skipped, Linux24/24; sandbox failures retained.
- [x] Package exact tested f433 client; eight archive members verified, real launcher split graphs3/3 and offline dual capability passed. New client plus existing server bundle actual maintenance/preflight recovery23/23,103.98s,cleanup empty. Old artifacts retained; no server/image rebuild.
- [x] Independent final read-only review: no material findings; 15 stage files and result identities checked. Usage/candidate/verification/delivery records updated; archive and frozen executable inputs checked, including the unchanged old binary.

Publish only these verified stage files: audit staged paths, commit, append the same-tree GitHub mirror, ordinary push and read back both main heads. Final commit identities and delivery result are recorded separately after publication.
