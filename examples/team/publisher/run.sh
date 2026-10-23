#!/usr/bin/env bash
set +x
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ -z "${CJREPO_PUBLISH_TOKEN:-}" || -z "${CJREPOMESH_CJPM:-}" ]]; then
    printf 'Publisher needs CJREPO_PUBLISH_TOKEN and an enhanced CJREPOMESH_CJPM.\n' >&2
    exit 2
fi
unset CJPM_CONFIG CJREPO_READ_TOKEN
export HOME="$PWD/.home" USERPROFILE="$PWD/.home"
# Optional process trust is configured by prepare.py.
"$CJREPOMESH_CJPM" bundle
"$CJREPOMESH_CJPM" publish
