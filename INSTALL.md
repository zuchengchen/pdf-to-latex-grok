# Installation

The installable Grok skill is the repository's `skill/` directory. Do not
install the repository root as the skill root.

Canonical repository:

```text
https://github.com/zuchengchen/pdf-to-latex-grok.git
```

Destination: `${GROK_HOME:-$HOME/.grok}/skills/pdf-to-latex`.

## Install In Grok

Type one of:

```text
安装skill https://github.com/zuchengchen/pdf-to-latex-grok.git
安装 skill https://github.com/zuchengchen/pdf-to-latex-grok.git
install skill https://github.com/zuchengchen/pdf-to-latex-grok.git
```

Grok should:

1. Clone the repository (default branch `main`, or a named ref).
2. Run `skill/scripts/update_installed_skill.sh --url https://github.com/zuchengchen/pdf-to-latex-grok.git`.
3. Confirm the package lands at `${GROK_HOME:-$HOME/.grok}/skills/pdf-to-latex`.
4. Tell the user to start a new session if the skill list does not refresh.

Optional ref:

```text
安装skill https://github.com/zuchengchen/pdf-to-latex-grok.git 到 v1.0.0
```

## Update In Grok

```text
更新skill https://github.com/zuchengchen/pdf-to-latex-grok.git
更新 skill https://github.com/zuchengchen/pdf-to-latex-grok.git
update skill https://github.com/zuchengchen/pdf-to-latex-grok.git
```

Optional ref:

```text
更新skill https://github.com/zuchengchen/pdf-to-latex-grok.git 到 main
```

When the skill is already installed, Grok should run the bundled updater from
the installed copy with the same URL (and optional `--ref`).

Direct command:

```bash
skill_dir="${GROK_HOME:-$HOME/.grok}/skills/pdf-to-latex"
bash "$skill_dir/scripts/update_installed_skill.sh" \
  --url https://github.com/zuchengchen/pdf-to-latex-grok.git \
  --ref main
```

The updater downloads the repository `skill/` tree, writes into same-filesystem
staging, restores executable bits, runs one package validation, and swaps
directories by rename with rollback.

## Shell Bootstrap (No Prior Install)

Prerequisites: Git, Python 3.10+, Bash 3.2+.

```bash
set -euo pipefail
tmp_dir=$(mktemp -d)
git clone --depth 1 https://github.com/zuchengchen/pdf-to-latex-grok.git "$tmp_dir/repo"
bash "$tmp_dir/repo/skill/scripts/update_installed_skill.sh" \
  --url https://github.com/zuchengchen/pdf-to-latex-grok.git
rm -rf "$tmp_dir"
```

## Atomic Manual Install

This procedure validates a staged copy before placing it at the final path. It
never overwrites an existing installation.

```bash
set -euo pipefail

grok_home=${GROK_HOME:-$HOME/.grok}
skills_dir="$grok_home/skills"
skill_dir="$skills_dir/pdf-to-latex"
ref=main
tmp_dir=$(mktemp -d)
staging=
lock_dir="$skills_dir/.pdf-to-latex.install.lock"
lock_active=false

cleanup() {
  status=$?
  trap - EXIT HUP INT TERM
  set +e
  if ! rm -rf "$tmp_dir"; then
    printf 'Failed to remove temporary repository: %s\n' "$tmp_dir" >&2
    status=1
  fi
  if [[ -n "$staging" ]]; then
    if ! rm -rf "$staging"; then
      printf 'Failed to remove staging directory: %s\n' "$staging" >&2
      status=1
    fi
  fi
  if [[ "$lock_active" == true ]]; then
    if ! rmdir "$lock_dir" 2>/dev/null; then
      printf 'Failed to release install lock: %s\n' "$lock_dir" >&2
      status=1
    fi
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
if [[ -e "$skill_dir" || -L "$skill_dir" ]]; then
  printf 'Destination already exists; use the update procedure: %s\n' "$skill_dir" >&2
  exit 1
fi
staging=$(mktemp -d "$skills_dir/.pdf-to-latex.staging.XXXXXX")
git clone --depth 1 --branch "$ref" \
  https://github.com/zuchengchen/pdf-to-latex-grok.git \
  "$tmp_dir/repository"

source_skill="$tmp_dir/repository/skill"
bash -n "$source_skill"/scripts/*.sh
python3 "$source_skill/scripts/workflow_contract.py" validate-package "$source_skill"

cp -R "$source_skill"/. "$staging"/
python3 "$staging/scripts/workflow_contract.py" validate-package "$staging"
mv "$staging" "$skill_dir"
staging=
```

## Atomic Update

```bash
set -euo pipefail

grok_home=${GROK_HOME:-$HOME/.grok}
skills_dir="$grok_home/skills"
skill_dir="$skills_dir/pdf-to-latex"
ref=main
tmp_dir=$(mktemp -d)
staging=
rollback_root=
rollback=
lock_dir="$skills_dir/.pdf-to-latex.install.lock"
lock_active=false
rollback_active=false
committed=false

cleanup() {
  status=$?
  trap - EXIT HUP INT TERM
  set +e
  if ! rm -rf "$tmp_dir"; then
    printf 'Failed to remove temporary repository: %s\n' "$tmp_dir" >&2
    status=1
  fi
  if [[ -n "$staging" ]]; then
    if ! rm -rf "$staging"; then
      printf 'Failed to remove staging directory: %s\n' "$staging" >&2
      status=1
    fi
  fi
  if [[ "$rollback_active" == true && "$committed" != true && -d "$rollback" ]]; then
    if rm -rf "$skill_dir" && mv "$rollback" "$skill_dir"; then
      rollback_active=false
    else
      printf 'Failed to restore the previous installation from: %s\n' "$rollback" >&2
      status=1
    fi
  fi
  if [[ -n "$rollback_root" ]]; then
    if [[ "$committed" == true || "$rollback_active" != true || ! -d "$rollback" ]]; then
      if ! rm -rf "$rollback_root"; then
        printf 'Failed to remove rollback directory: %s\n' "$rollback_root" >&2
        status=1
      fi
    fi
  fi
  if [[ "$lock_active" == true ]]; then
    if ! rmdir "$lock_dir" 2>/dev/null; then
      printf 'Failed to release install lock: %s\n' "$lock_dir" >&2
      status=1
    fi
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

if ! mkdir "$lock_dir" 2>/dev/null; then
  printf 'Another pdf-to-latex install or update is active: %s\n' "$lock_dir" >&2
  exit 1
fi
lock_active=true
if [[ -L "$skill_dir" ]]; then
  printf 'Installed skill path must be a real directory, not a symlink: %s\n' "$skill_dir" >&2
  exit 1
fi
if [[ ! -d "$skill_dir" ]]; then
  printf 'Installed skill not found; use the install procedure: %s\n' "$skill_dir" >&2
  exit 1
fi

staging=$(mktemp -d "$skills_dir/.pdf-to-latex.staging.XXXXXX")
rollback_root=$(mktemp -d "$skills_dir/.pdf-to-latex.rollback.XXXXXX")
rollback="$rollback_root/installed"

git clone --depth 1 --branch "$ref" \
  https://github.com/zuchengchen/pdf-to-latex-grok.git \
  "$tmp_dir/repository"

source_skill="$tmp_dir/repository/skill"
bash -n "$source_skill"/scripts/*.sh
python3 "$source_skill/scripts/workflow_contract.py" validate-package "$source_skill"

cp -R "$source_skill"/. "$staging"/
python3 "$staging/scripts/workflow_contract.py" validate-package "$staging"
rollback_active=true
mv "$skill_dir" "$rollback"
mv "$staging" "$skill_dir"
staging=
python3 "$skill_dir/scripts/workflow_contract.py" validate-package "$skill_dir"
committed=true
rm -rf "$rollback_root"
rollback_active=false
```

## Verify Installation

```bash
skill_dir="${GROK_HOME:-$HOME/.grok}/skills/pdf-to-latex"
python3 "$skill_dir/scripts/workflow_contract.py" validate-package "$skill_dir"
```

Then start a new Grok session, type `/`, and confirm that `pdf-to-latex`
appears. A direct invocation is:

```text
/pdf-to-latex 把这个 PDF 重建成可编辑 LaTeX 项目
```

## Uninstall

```bash
rm -rf "${GROK_HOME:-$HOME/.grok}/skills/pdf-to-latex"
```

## Troubleshooting

- Install and update commands must use
  `https://github.com/zuchengchen/pdf-to-latex-grok.git` (a trailing `.git` is
  optional for the helper script).
- The installable package is the repository `skill/` directory, not the repo root.
- Manual install and update reject a symlink destination and serialize through
  `.pdf-to-latex.install.lock`.
- If an update reports that restoration failed, keep the printed
  `.pdf-to-latex.rollback.*` directory until its `installed/` copy has been
  restored or inspected manually.
- Python 3.10+ is required by deterministic workflow helpers.
- Override the install root with `GROK_HOME` when testing in a temporary tree.
