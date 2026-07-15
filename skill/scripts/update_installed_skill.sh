#!/usr/bin/env bash
set -euo pipefail

DEFAULT_REPO_URL='https://github.com/zuchengchen/pdf-to-latex-grok'
DEFAULT_REPO_PATH='skill'

usage() {
  printf 'Usage: %s [--ref REF] [--url REPO_URL]\n' "$0" >&2
  printf 'Install or update pdf-to-latex from GitHub into ~/.grok/skills.\n' >&2
  printf 'Default URL: %s (also accepts a trailing .git).\n' "$DEFAULT_REPO_URL" >&2
  printf 'REF defaults to development branch main.\n' >&2
}

normalize_repo_url() {
  local url=$1
  url=${url%%[[:space:]]*}
  url=${url%"${url##*[![:space:]]}"}
  case "$url" in
    *.git) url=${url%.git} ;;
  esac
  printf '%s\n' "$url"
}

is_pdf_to_latex_installation() {
  python3 - "$1/SKILL.md" <<'PY'
import pathlib
import re
import sys

try:
    lines = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
except (OSError, UnicodeDecodeError):
    raise SystemExit(1)

if not lines or lines[0].strip() != "---":
    raise SystemExit(1)

name_pattern = re.compile(r"name:\s*(?:pdf-to-latex|'pdf-to-latex'|\"pdf-to-latex\")\s*")
found_name = False
for line in lines[1:]:
    if line.strip() == "---":
        raise SystemExit(0 if found_name else 1)
    if name_pattern.fullmatch(line.strip()):
        found_name = True
raise SystemExit(1)
PY
}

download_skill_package() {
  # Args: ref dest name repo_url
  # Produces: "$dest/$name" containing the skill package (SKILL.md at root).
  local ref=$1
  local dest=$2
  local name=$3
  local repo_url=$4
  local repo_path=${PDF_TO_LATEX_REPO_PATH:-$DEFAULT_REPO_PATH}
  local work=
  work=$(mktemp -d "$dest/.download-src.XXXXXX")
  if command -v git >/dev/null 2>&1; then
    if ! git clone --depth 1 --branch "$ref" "$repo_url" "$work/repository" >/dev/null 2>&1; then
      # Tags and some refs need an unshallow-style fallback without --branch.
      rm -rf "$work/repository"
      git clone --depth 1 "$repo_url" "$work/repository" >/dev/null 2>&1 || true
      if [[ -d "$work/repository/.git" ]]; then
        git -C "$work/repository" fetch --depth 1 origin "$ref" >/dev/null 2>&1 || true
        git -C "$work/repository" checkout "$ref" >/dev/null 2>&1 || true
      fi
    fi
  fi
  if [[ ! -f "$work/repository/$repo_path/SKILL.md" ]]; then
    # Archive fallback for environments without git or when clone fails.
    local archive="$work/archive.tgz"
    local archive_url="${repo_url}/archive/refs/heads/${ref}.tar.gz"
    if [[ "$ref" == v* || "$ref" =~ ^[0-9a-fA-F]{7,40}$ ]]; then
      archive_url="${repo_url}/archive/refs/tags/${ref}.tar.gz"
    fi
    if command -v curl >/dev/null 2>&1; then
      curl -fsSL "$archive_url" -o "$archive" || true
    elif command -v wget >/dev/null 2>&1; then
      wget -q -O "$archive" "$archive_url" || true
    fi
    if [[ -f "$archive" ]]; then
      mkdir -p "$work/extracted"
      tar -xzf "$archive" -C "$work/extracted" 2>/dev/null || true
      local found=
      found=$(find "$work/extracted" -type f -path "*/${repo_path}/SKILL.md" 2>/dev/null | head -n 1 || true)
      if [[ -n "$found" ]]; then
        mkdir -p "$work/repository"
        cp -R "$(dirname "$found")" "$work/repository/${repo_path}"
      fi
    fi
  fi
  if [[ ! -f "$work/repository/$repo_path/SKILL.md" ]]; then
    printf 'Failed to download skill package from %s at ref %s\n' "$repo_url" "$ref" >&2
    rm -rf "$work"
    return 1
  fi
  mkdir -p "$dest"
  cp -R "$work/repository/$repo_path" "$dest/$name"
  rm -rf "$work"
}

ref=main
repo_url=${PDF_TO_LATEX_REPO_URL:-$DEFAULT_REPO_URL}
while [[ $# -gt 0 ]]; do
  case "$1" in
    --ref)
      if [[ $# -lt 2 || -z "$2" || "$2" == -* ]]; then
        usage
        exit 2
      fi
      ref=$2
      shift 2
      ;;
    --ref=*)
      ref=${1#--ref=}
      if [[ -z "$ref" || "$ref" == -* ]]; then
        usage
        exit 2
      fi
      shift
      ;;
    --url)
      if [[ $# -lt 2 || -z "$2" || "$2" == -* ]]; then
        usage
        exit 2
      fi
      repo_url=$2
      shift 2
      ;;
    --url=*)
      repo_url=${1#--url=}
      if [[ -z "$repo_url" || "$repo_url" == -* ]]; then
        usage
        exit 2
      fi
      shift
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
done

repo_url=$(normalize_repo_url "$repo_url")
export PYTHONDONTWRITEBYTECODE=1

grok_home=${GROK_HOME:-$HOME/.grok}
skills_dir="$grok_home/skills"
skill_dir="$skills_dir/pdf-to-latex"
installer=${PDF_TO_LATEX_INSTALLER:-}
repo_path=${PDF_TO_LATEX_REPO_PATH:-$DEFAULT_REPO_PATH}
lock_dir="$skills_dir/.pdf-to-latex.install.lock"
staging_root=
rollback_root=
rollback=
lock_active=false
rollback_active=false
committed=false

cleanup() {
  status=$?
  trap - EXIT HUP INT TERM
  set +e

  if [[ "$rollback_active" == true && "$committed" != true && -d "$rollback" ]]; then
    if rm -rf "$skill_dir"; then
      if mv "$rollback" "$skill_dir"; then
        rollback_active=false
      else
        printf 'Failed to restore the previous installation from: %s\n' "$rollback" >&2
        status=1
      fi
    else
      printf 'Failed to remove the incomplete installation at: %s\n' "$skill_dir" >&2
      printf 'Previous installation retained at: %s\n' "$rollback" >&2
      status=1
    fi
  fi

  if [[ -n "$staging_root" ]]; then
    rm -rf "$staging_root" || status=1
  fi
  if [[ -n "$rollback_root" ]]; then
    if [[ "$committed" == true || "$rollback_active" != true || ! -d "$rollback" ]]; then
      rm -rf "$rollback_root" || status=1
    fi
  fi
  if [[ "$lock_active" == true ]]; then
    rmdir "$lock_dir" 2>/dev/null || status=1
  fi
  exit "$status"
}

trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

mkdir -p "$skills_dir"
if ! mkdir "$lock_dir" 2>/dev/null; then
  printf 'Another pdf-to-latex install or update is active: %s\n' "$lock_dir" >&2
  exit 1
fi
lock_active=true

if [[ -L "$skill_dir" ]]; then
  printf 'Installed skill path must be a real directory, not a symlink: %s\n' "$skill_dir" >&2
  exit 1
fi
if [[ -e "$skill_dir" && ! -d "$skill_dir" ]]; then
  printf 'Installed skill path is not a directory: %s\n' "$skill_dir" >&2
  exit 1
fi
if [[ -d "$skill_dir" ]] && ! is_pdf_to_latex_installation "$skill_dir"; then
  printf 'Refusing to replace a directory that is not an installed pdf-to-latex skill: %s\n' "$skill_dir" >&2
  exit 1
fi

staging_root=$(mktemp -d "$skills_dir/.pdf-to-latex.update.XXXXXX")

if [[ -n "$installer" ]]; then
  if [[ ! -f "$installer" ]]; then
    printf 'Skill download helper not found: %s\n' "$installer" >&2
    exit 1
  fi
  python3 "$installer" \
    --url "$repo_url" \
    --path "$repo_path" \
    --ref "$ref" \
    --dest "$staging_root" \
    --name pdf-to-latex \
    --method download
else
  download_skill_package "$ref" "$staging_root" pdf-to-latex "$repo_url"
fi

fresh="$staging_root/pdf-to-latex"
if [[ ! -f "$fresh/SKILL.md" ]]; then
  printf 'Downloaded skill is missing SKILL.md: %s\n' "$fresh" >&2
  exit 1
fi

for helper in "$fresh"/scripts/*.sh "$fresh"/scripts/*.py; do
  if [[ -f "$helper" ]]; then
    chmod 755 "$helper"
  fi
done

python3 "$fresh/scripts/workflow_contract.py" validate-package "$fresh"

cd "$skills_dir"
action=Installed
if [[ -d "$skill_dir" ]]; then
  rollback_root=$(mktemp -d "$skills_dir/.pdf-to-latex.rollback.XXXXXX")
  rollback="$rollback_root/installed"
  rollback_active=true
  mv "$skill_dir" "$rollback"
  action=Updated
fi

if ! mv "$fresh" "$skill_dir"; then
  printf 'Failed to place the staged skill at: %s\n' "$skill_dir" >&2
  exit 1
fi
committed=true

if [[ "$rollback_active" == true ]]; then
  rm -rf "$rollback_root"
  rollback_active=false
fi

printf '%s pdf-to-latex from %s (ref %s) at %s\n' "$action" "$repo_url" "$ref" "$skill_dir"
printf 'Start a new Grok session, or wait for skill auto-reload, to load the skill.\n'
