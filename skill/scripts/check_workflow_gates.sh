#!/usr/bin/env bash
set -euo pipefail

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)

if ! command -v python3 >/dev/null 2>&1; then
  printf 'Python 3.10 or newer is required for workflow validation.\n' >&2
  exit 1
fi

exec python3 "$script_dir/workflow_contract.py" validate "$@"
