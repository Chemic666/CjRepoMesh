#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd -- "${script_dir}/.." && pwd)"
cjpm_path="${CJREPOMESH_CJPM:-${project_root}/cjpm/dist/cjpm}"
server_path="${CJREPOMESH_SERVER:-${project_root}/server/target/release/bin/main}"

if [[ -z "${CANGJIE_HOME:-}" ]]; then
    echo "CANGJIE_HOME is not set. Source the Cangjie SDK envsetup.sh before running Linux tests." >&2
    exit 2
fi
if [[ -z "${CANGJIE_STDX_PATH:-}" ]]; then
    echo "CANGJIE_STDX_PATH is not set. Point it at the Linux static stdx directory." >&2
    exit 2
fi

exec python3 "${script_dir}/run.py" --cjpm "${cjpm_path}" --server "${server_path}" "$@"
