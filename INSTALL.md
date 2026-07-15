# Installation

The installable Grok skill is the repository's `skill/` directory. Do not
install the repository root.

Destination: `${GROK_HOME:-$HOME/.grok}/skills/pdf-to-latex`.

## Stable Grok Install

Prerequisites: Git, Python 3.10+, Bash 3.2+.

```bash
set -euo pipefail

grok_home=${GROK_HOME:-$HOME/.grok}
skills_dir="$grok_home/skills"
skill_dir="$skills_dir/pdf-to-latex"
ref=v1.0.0
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
  https://github.com/zuchengchen/pdf-to-latex \
  "$tmp_dir/repository"

source_skill="$tmp_dir/repository/skill"
bash -n "$source_skill"/scripts/*.sh
python3 "$source_skill/scripts/workflow_contract.py" validate-package "$source_skill"

cp -R "$source_skill"/. "$staging"/
python3 "$staging/scripts/workflow_contract.py" validate-package "$staging"
mv "$staging" "$skill_dir"
staging=
```

Start a new Grok session after installation. Skills often auto-reload when files
change on disk.

## Fast Grok Update

After installing a version that contains `scripts/update_installed_skill.sh`,
the normal update command is:

```text
更新 skill pdf-to-latex
```

The skill routes this exact command to its bundled updater instead of the
conversion workflow or the conservative atomic procedure below. The bare
command updates from the development branch `main`; use
`更新 skill pdf-to-latex 到 REF` for a tag, branch, or commit.

The fast path downloads the repository `skill/` tree (Git clone or archive),
writes into same-filesystem staging under
`${GROK_HOME:-$HOME/.grok}/skills`, restores executable bits, runs exactly one
bundled package validation, and swaps directories by rename with rollback. It
does not run `bash -n`, portable, integration, or extended tests. Those checks
belong in repository CI and release validation.

The equivalent direct command from an existing installed copy is:

```bash
skill_dir="${GROK_HOME:-$HOME/.grok}/skills/pdf-to-latex"
bash "$skill_dir/scripts/update_installed_skill.sh" --ref main
```

An older installation that does not contain the updater must use Atomic Update
once. Start a new Grok session after the fast update if the skill list remains
stale.

## Atomic Update

The update uses unique same-filesystem staging and rollback directories. It
attempts to restore the old installation after any failure or interruption
before final package validation succeeds. A successful update or restoration
removes the rollback immediately. If restoration itself fails, cleanup retains
the rollback path and prints it for manual recovery.

```bash
set -euo pipefail

grok_home=${GROK_HOME:-$HOME/.grok}
skills_dir="$grok_home/skills"
skill_dir="$skills_dir/pdf-to-latex"
ref=v1.0.0
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
  https://github.com/zuchengchen/pdf-to-latex \
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

Start a new Grok session after updating if needed.

## Development Channel

To test unreleased changes, replace `v1.0.0` with `main`. Development installs
are not the stable channel and may contain contract changes.

## Verify Installation

Run the installed package validator:

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

Start a new Grok session after uninstalling if the skill list remains stale.

## Troubleshooting

- Pass `skill/` as the installable path; the repository root does not contain
  the installable `SKILL.md`.
- If the destination exists, use the atomic update procedure instead of
  overwriting it in place.
- Manual install and update reject a symlink destination and serialize through
  `.pdf-to-latex.install.lock`. Remove that directory only after confirming no
  install or update process is still running.
- If an update reports that restoration failed, keep the printed
  `.pdf-to-latex.rollback.*` directory until its `installed/` copy has been
  restored or inspected manually.
- If archive download is rate-limited, the manual Git procedure remains safe
  because it validates staging before moving the installed directory.
- Python 3.10+ is required by deterministic workflow helpers.
- Override the install root with `GROK_HOME` when testing in a temporary tree.
