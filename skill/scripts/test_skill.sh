#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf 'Usage: %s (--portable|--integration|--extended) [--require-tools]\n' "$0" >&2
  printf '  --portable    Run deterministic tests that need only Python 3.10+ and Bash.\n' >&2
  printf '  --integration Add real XeLaTeX, latexmk, and Poppler pipeline tests.\n' >&2
  printf '  --extended    Add bibliography, index, glossary, CJK, and book tests.\n' >&2
}

mode=
require_tools=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --portable|--integration|--extended)
      if [[ -n "$mode" ]]; then
        usage
        exit 2
      fi
      mode=${1#--}
      ;;
    --require-tools)
      require_tools=true
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      exit 2
      ;;
  esac
  shift
done

if [[ -z "$mode" || ( "$mode" == portable && "$require_tools" == true ) ]]; then
  usage
  exit 2
fi

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
skill_dir=$(CDPATH='' cd -- "$script_dir/.." && pwd)
repo_dir=$(CDPATH='' cd -- "$skill_dir/.." && pwd)
export PYTHONDONTWRITEBYTECODE=1

python3 - <<'PY'
import sys

if sys.version_info < (3, 10):
    raise SystemExit("Python 3.10 or newer is required for the test suite.")
PY

python3 "$script_dir/workflow_contract.py" validate-contract >/dev/null
python3 "$script_dir/workflow_contract.py" validate-package "$skill_dir" >/dev/null
if [[ -f "$repo_dir/README.md" ]]; then
  grep -Fq 'Prefer Goal-backed execution by default' "$repo_dir/README.md" || {
    printf 'README.md must document the default Goal-backed execution policy.\n' >&2
    exit 1
  }
  grep -Fq '更新 skill pdf-to-latex' "$repo_dir/README.md" || {
    printf 'README.md must document the fast self-update command.\n' >&2
    exit 1
  }
fi
if [[ -f "$repo_dir/INSTALL.md" ]]; then
  grep -Fq '更新 skill pdf-to-latex' "$repo_dir/INSTALL.md" || {
    printf 'INSTALL.md must document the fast self-update command.\n' >&2
    exit 1
  }
fi

bash -n "$script_dir"/*.sh
if command -v shellcheck >/dev/null 2>&1; then
  shellcheck --shell=bash "$script_dir"/*.sh
else
  printf 'Skipping ShellCheck; shellcheck is not installed.\n'
fi

python3 - "$script_dir" <<'PY'
import ast
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
for path in sorted(root.glob("*.py")):
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
print("Python syntax checks passed.")
PY

python3 "$script_dir/toolchain_probe.py" --json >/dev/null
"$script_dir/test_workflow_contract.sh"
"$script_dir/test_skill_update.sh"
"$script_dir/test_project_scaffold.sh"
"$script_dir/test_evidence_pipeline.sh"
"$script_dir/test_merge_shards.sh"
"$script_dir/test_batch_planning.sh"
"$script_dir/test_worker_usage.sh"
if [[ "$mode" == portable ]]; then
  "$script_dir/test_latex_pipeline.sh" --portable
else
  if [[ "$require_tools" == true ]]; then
    "$script_dir/test_latex_pipeline.sh" --integration --require-tools
  else
    "$script_dir/test_latex_pipeline.sh" --integration
  fi
fi

if [[ "$mode" == extended ]]; then
  if [[ "$require_tools" == true ]]; then
    "$script_dir/test_extended_pipeline.sh" --require-tools
  else
    "$script_dir/test_extended_pipeline.sh"
  fi
fi

python3 "$script_dir/workflow_contract.py" validate-package "$skill_dir" >/dev/null
printf 'PDF-to-LaTeX %s tests passed.\n' "$mode"
