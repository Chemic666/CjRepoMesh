#!/usr/bin/env bash
set +x
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ -z "${CJREPO_READ_TOKEN:-}" || -z "${CJREPOMESH_CJPM:-}" ]]; then
    printf 'Consumer needs CJREPO_READ_TOKEN and an enhanced CJREPOMESH_CJPM.\n' >&2
    exit 2
fi
unset CJPM_CONFIG CJREPO_PUBLISH_TOKEN
export HOME="$PWD/.home" USERPROFILE="$PWD/.home"
# Optional process trust is configured by prepare.py.
if [[ "${CJREPOMESH_SCRIPT_SOURCE_BASELINE+x}" && ! "${CJREPOMESH_SOURCE_BASELINE+x}" ]]; then
    printf 'Protected consumer requires a main source baseline with the script override.\n' >&2
    exit 2
fi
if [[ "${CJREPOMESH_SOURCE_BASELINE+x}" ]]; then
    if ! capability=$("$CJREPOMESH_CJPM" repo supports source-baseline-v1 2>/dev/null) ||
        [[ "$capability" != source-baseline-v1 ]]; then
        printf 'Protected consumer requires source-baseline-v1; use a verified compatible client.\n' >&2
        exit 2
    fi
fi
if [[ "${CJREPOMESH_SCRIPT_SOURCE_BASELINE+x}" ]]; then
    if ! capability=$("$CJREPOMESH_CJPM" repo supports script-source-baseline-v1 2>/dev/null) ||
        [[ "$capability" != script-source-baseline-v1 ]]; then
        printf 'Protected consumer requires script-source-baseline-v1; use a verified compatible client.\n' >&2
        exit 2
    fi
fi
# Optional single-use admission is configured by prepare.py.
"$CJREPOMESH_CJPM" build
(
    unset CJREPO_READ_TOKEN CJREPO_PUBLISH_TOKEN
    exec ./target/release/bin/main
)
"$CJREPOMESH_CJPM" repo explain company::teamhello --recorded
