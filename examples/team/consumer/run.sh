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
"$CJREPOMESH_CJPM" build
./target/release/bin/main
"$CJREPOMESH_CJPM" repo explain company::teamhello --recorded
