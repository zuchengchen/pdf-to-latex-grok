#!/usr/bin/env bash
set -euo pipefail

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
skill_dir=$(CDPATH='' cd -- "$script_dir/.." && pwd)
updater="$script_dir/update_installed_skill.sh"

tmp_dir=$(mktemp -d)
cleanup() {
  rm -rf "$tmp_dir"
}
trap cleanup EXIT HUP INT TERM

fail() {
  printf 'Skill update test failed: %s\n' "$*" >&2
  exit 1
}

assert_file() {
  [[ -f "$1" ]] || fail "missing file: $1"
}

assert_absent() {
  [[ ! -e "$1" && ! -L "$1" ]] || fail "unexpected path: $1"
}

tree_digest() {
  python3 - "$1" <<'PY'
import hashlib
import os
import pathlib
import stat
import sys

root = pathlib.Path(sys.argv[1])
digest = hashlib.sha256()
for path in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
    relative = path.relative_to(root).as_posix()
    metadata = path.lstat()
    digest.update(relative.encode("utf-8"))
    digest.update(b"\0")
    digest.update(str(stat.S_IMODE(metadata.st_mode)).encode("ascii"))
    digest.update(b"\0")
    if path.is_symlink():
        digest.update(b"link\0")
        digest.update(os.readlink(path).encode("utf-8"))
    elif path.is_file():
        digest.update(b"file\0")
        digest.update(path.read_bytes())
    elif path.is_dir():
        digest.update(b"dir\0")
print(digest.hexdigest())
PY
}

prepare_installed_case() {
  case_root=$1
  target="$case_root/home/skills/pdf-to-latex"
  mkdir -p "$target"
  cp -R "$skill_dir"/. "$target"/
  printf 'old installation\n' >"$target/old-marker"
}

assert_clean_auxiliary_paths() {
  skills=$1
  for path in \
    "$skills"/.pdf-to-latex.update.* \
    "$skills"/.pdf-to-latex.rollback.* \
    "$skills"/.pdf-to-latex.install.lock; do
    if [[ -e "$path" || -L "$path" ]]; then
      fail "update left staging, rollback, or lock path: $path"
    fi
  done
}

assert_installed_modes() {
  python3 - "$1" <<'PY'
import pathlib
import stat
import sys

root = pathlib.Path(sys.argv[1])
for path in (root / "scripts").iterdir():
    if path.is_file() and path.suffix in {".sh", ".py"}:
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode != 0o755:
            raise SystemExit(f"helper mode is not 0755: {path}: {mode:o}")
if stat.S_IMODE((root / "SKILL.md").stat().st_mode) & 0o111:
    raise SystemExit("SKILL.md unexpectedly became executable")
PY
}

assert_installer_request() {
  python3 - "$1" "$2" "$3" <<'PY'
import json
import pathlib
import sys

record = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
expected_ref = sys.argv[2]
skills = pathlib.Path(sys.argv[3]).resolve()
assert record["url"] == "https://github.com/zuchengchen/pdf-to-latex"
assert record["path"] == "skill"
assert record["ref"] == expected_ref
assert record["name"] == "pdf-to-latex"
assert record["method"] == "download"
dest = pathlib.Path(record["dest"]).resolve()
assert dest.parent == skills
assert dest.name.startswith(".pdf-to-latex.update.")
PY
}

expect_failure() {
  set +e
  "$@" >"$tmp_dir/last.stdout" 2>"$tmp_dir/last.stderr"
  status=$?
  set -e
  [[ $status -ne 0 ]] || fail "expected failure from: $*"
}

fake_installer="$tmp_dir/fake-installer.py"
cat >"$fake_installer" <<'PY'
#!/usr/bin/env python3
import json
import os
import pathlib
import shutil
import sys


def value(flag: str) -> str:
    try:
        return sys.argv[sys.argv.index(flag) + 1]
    except (ValueError, IndexError) as exc:
        raise SystemExit(f"Missing fake installer argument: {flag}") from exc


dest = pathlib.Path(value("--dest"))
name = value("--name")
ref = value("--ref")
source = pathlib.Path(os.environ["SOURCE_SKILL"])
log = pathlib.Path(os.environ["FAKE_INSTALLER_LOG"])
mode = os.environ.get("FAKE_INSTALLER_MODE", "success")

record = {
    "url": value("--url"),
    "path": value("--path"),
    "ref": ref,
    "dest": str(dest),
    "name": name,
    "method": value("--method"),
}
log.write_text(json.dumps(record, sort_keys=True) + "\n", encoding="utf-8")
if mode == "fail":
    raise SystemExit(17)

target = dest / name
shutil.copytree(source, target)
for path in (target / "scripts").iterdir():
    if path.is_file() and path.suffix in {".sh", ".py"}:
        path.chmod(0o644)

if mode == "invalid":
    (target / "references" / "goal-mode.md").unlink()
PY
chmod 755 "$fake_installer"

run_update() {
  local case_root=$1
  local mode=$2
  local ref=$3
  local runner=${4:-$updater}
  mkdir -p "$case_root/home/skills"
  if [[ -n "$ref" ]]; then
    GROK_HOME="$case_root/home" \
      PDF_TO_LATEX_INSTALLER="$fake_installer" \
      SOURCE_SKILL="$skill_dir" \
      FAKE_INSTALLER_LOG="$case_root/installer-request.json" \
      FAKE_INSTALLER_MODE="$mode" \
      "$runner" --ref "$ref"
  else
    GROK_HOME="$case_root/home" \
      PDF_TO_LATEX_INSTALLER="$fake_installer" \
      SOURCE_SKILL="$skill_dir" \
      FAKE_INSTALLER_LOG="$case_root/installer-request.json" \
      FAKE_INSTALLER_MODE="$mode" \
      "$runner"
  fi
}

install_case="$tmp_dir/install"
run_update "$install_case" success '' >"$tmp_dir/install.stdout"
assert_file "$install_case/home/skills/pdf-to-latex/SKILL.md"
assert_installed_modes "$install_case/home/skills/pdf-to-latex"
assert_installer_request "$install_case/installer-request.json" main "$install_case/home/skills"
assert_clean_auxiliary_paths "$install_case/home/skills"

update_case="$tmp_dir/update"
prepare_installed_case "$update_case"
installed_updater="$update_case/home/skills/pdf-to-latex/scripts/update_installed_skill.sh"
run_update "$update_case" success update-ref "$installed_updater" >"$tmp_dir/update.stdout"
assert_file "$update_case/home/skills/pdf-to-latex/SKILL.md"
assert_absent "$update_case/home/skills/pdf-to-latex/old-marker"
assert_installed_modes "$update_case/home/skills/pdf-to-latex"
assert_installer_request "$update_case/installer-request.json" update-ref "$update_case/home/skills"
assert_clean_auxiliary_paths "$update_case/home/skills"

installer_failure_case="$tmp_dir/installer-failure"
prepare_installed_case "$installer_failure_case"
before=$(tree_digest "$installer_failure_case/home/skills/pdf-to-latex")
expect_failure run_update "$installer_failure_case" fail failure-ref "$installer_failure_case/home/skills/pdf-to-latex/scripts/update_installed_skill.sh"
after=$(tree_digest "$installer_failure_case/home/skills/pdf-to-latex")
[[ "$before" == "$after" ]] || fail 'installer failure changed the old installation'
assert_clean_auxiliary_paths "$installer_failure_case/home/skills"

validation_failure_case="$tmp_dir/validation-failure"
prepare_installed_case "$validation_failure_case"
before=$(tree_digest "$validation_failure_case/home/skills/pdf-to-latex")
expect_failure run_update "$validation_failure_case" invalid invalid-ref "$validation_failure_case/home/skills/pdf-to-latex/scripts/update_installed_skill.sh"
after=$(tree_digest "$validation_failure_case/home/skills/pdf-to-latex")
[[ "$before" == "$after" ]] || fail 'validation failure changed the old installation'
assert_file "$validation_failure_case/installer-request.json"
assert_clean_auxiliary_paths "$validation_failure_case/home/skills"

swap_failure_case="$tmp_dir/swap-failure"
prepare_installed_case "$swap_failure_case"
before=$(tree_digest "$swap_failure_case/home/skills/pdf-to-latex")
fake_bin="$swap_failure_case/fake-bin"
mkdir -p "$fake_bin"
real_mv=$(command -v mv)
cat >"$fake_bin/mv" <<'SH'
#!/usr/bin/env bash
set -euo pipefail

count=0
if [[ -f "$FAKE_MV_COUNT" ]]; then
  count=$(cat "$FAKE_MV_COUNT")
fi
count=$((count + 1))
printf '%s\n' "$count" >"$FAKE_MV_COUNT"
if [[ $count -eq 2 ]]; then
  exit 19
fi
exec "$REAL_MV" "$@"
SH
chmod 755 "$fake_bin/mv"
PATH="$fake_bin:$PATH" \
  REAL_MV="$real_mv" \
  FAKE_MV_COUNT="$swap_failure_case/mv-count" \
  expect_failure run_update "$swap_failure_case" success swap-ref "$swap_failure_case/home/skills/pdf-to-latex/scripts/update_installed_skill.sh"
after=$(tree_digest "$swap_failure_case/home/skills/pdf-to-latex")
[[ "$before" == "$after" ]] || fail 'swap failure did not restore the old installation'
grep -Fxq '3' "$swap_failure_case/mv-count" || fail 'swap failure did not execute the rollback rename'
assert_clean_auxiliary_paths "$swap_failure_case/home/skills"

lock_case="$tmp_dir/lock"
prepare_installed_case "$lock_case"
mkdir -p "$lock_case/home/skills/.pdf-to-latex.install.lock"
before=$(tree_digest "$lock_case/home/skills/pdf-to-latex")
expect_failure run_update "$lock_case" success lock-ref "$lock_case/home/skills/pdf-to-latex/scripts/update_installed_skill.sh"
after=$(tree_digest "$lock_case/home/skills/pdf-to-latex")
[[ "$before" == "$after" ]] || fail 'lock conflict changed the old installation'
assert_absent "$lock_case/installer-request.json"
[[ -d "$lock_case/home/skills/.pdf-to-latex.install.lock" ]] || fail 'updater removed another process lock'

symlink_case="$tmp_dir/symlink"
mkdir -p "$symlink_case/home/skills/real-skill"
ln -s "$symlink_case/home/skills/real-skill" "$symlink_case/home/skills/pdf-to-latex"
expect_failure run_update "$symlink_case" success symlink-ref
[[ -L "$symlink_case/home/skills/pdf-to-latex" ]] || fail 'updater replaced a symlink installation'
assert_absent "$symlink_case/installer-request.json"
[[ ! -d "$symlink_case/home/skills/.pdf-to-latex.install.lock" ]] || fail 'symlink rejection left its update lock'

file_case="$tmp_dir/file-target"
mkdir -p "$file_case/home/skills"
printf 'not a directory\n' >"$file_case/home/skills/pdf-to-latex"
expect_failure run_update "$file_case" success file-ref
[[ -f "$file_case/home/skills/pdf-to-latex" ]] || fail 'updater replaced a non-directory installation path'
assert_absent "$file_case/installer-request.json"
[[ ! -d "$file_case/home/skills/.pdf-to-latex.install.lock" ]] || fail 'file-target rejection left its update lock'

unrelated_directory_case="$tmp_dir/unrelated-directory"
unrelated_target="$unrelated_directory_case/home/skills/pdf-to-latex"
mkdir -p "$unrelated_target"
printf '%s\n' '---' 'name: unrelated-skill' '---' >"$unrelated_target/SKILL.md"
printf 'preserve this directory\n' >"$unrelated_target/sentinel"
before=$(tree_digest "$unrelated_target")
expect_failure run_update "$unrelated_directory_case" success unrelated-ref
after=$(tree_digest "$unrelated_target")
[[ "$before" == "$after" ]] || fail 'identity rejection changed the unrelated directory'
assert_absent "$unrelated_directory_case/installer-request.json"
[[ ! -d "$unrelated_directory_case/home/skills/.pdf-to-latex.install.lock" ]] || fail 'identity rejection left its update lock'

"$updater" --help >/dev/null 2>&1
expect_failure "$updater" --ref
expect_failure "$updater" --ref --help
expect_failure "$updater" --ref=--help
expect_failure "$updater" --unknown

printf 'Skill update tests passed.\n'
