#!/usr/bin/env bash
set -euo pipefail

script_dir=$(CDPATH='' cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
export PYTHONDONTWRITEBYTECODE=1
tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/pdf-evidence-test.XXXXXX")
trap 'rm -rf "$tmp_dir"' EXIT HUP INT TERM

fail() {
  printf 'Evidence pipeline test failed: %s\n' "$*" >&2
  exit 1
}

assert_file() {
  [[ -s "$1" ]] || fail "expected non-empty file: $1"
}

assert_absent() {
  [[ ! -e "$1" ]] || fail "expected path to be absent: $1"
}

file_hash() {
  python3 - "$1" <<'PY'
import hashlib
import pathlib
import sys

print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())
PY
}

assert_hash() {
  local expected=$1
  local path=$2
  local actual

  actual=$(file_hash "$path")
  [[ "$actual" == "$expected" ]] || fail "file changed unexpectedly: $path"
}

assert_manifest_pages() {
  local manifest=$1
  local expected=$2

  python3 - "$manifest" "$expected" <<'PY'
import json
import pathlib
import sys

manifest = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
actual = ",".join(str(page) for page in manifest["pages"])
if actual != sys.argv[2]:
    raise SystemExit(f"expected pages {sys.argv[2]}, found {actual}")
PY
}

assert_manifest_path() {
  local manifest=$1
  local expected=$2

  python3 - "$manifest" "$expected" <<'PY'
import json
import pathlib
import sys

manifest = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
expected = str(pathlib.Path(sys.argv[2]).resolve())
if manifest["source_path"] != expected:
    raise SystemExit(f"expected source_path {expected}, found {manifest['source_path']}")
PY
}

make_pdf() {
  local path=$1
  local pages=$2
  local token=$3

  printf '%%PDF-1.7\nPAGES=%s\nTOKEN=%s\n' "$pages" "$token" >"$path"
}

fake_bin="$tmp_dir/fake-bin"
mkdir -p "$fake_bin"

cat >"$fake_bin/pdfinfo" <<'PY'
#!/usr/bin/env python3
import pathlib
import re
import sys

data = pathlib.Path(sys.argv[-1]).read_text(encoding="utf-8")
match = re.search(r"^PAGES=([0-9]+)$", data, re.MULTILINE)
if match is None:
    raise SystemExit(2)
print(f"Pages: {match.group(1)}")
PY

cat >"$fake_bin/pdftoppm" <<'PY'
#!/usr/bin/env python3
import hashlib
import os
import pathlib
import sys
import time

args = sys.argv[1:]
if os.environ.get("FAIL_RENDER") == "1":
    print("simulated renderer failure", file=sys.stderr)
    raise SystemExit(19)
if os.environ.get("RENDER_DELAY"):
    time.sleep(float(os.environ["RENDER_DELAY"]))
start = int(args[args.index("-f") + 1])
end = int(args[args.index("-l") + 1])
source = pathlib.Path(args[-2])
prefix = pathlib.Path(args[-1])
marker = os.environ.get("RENDER_MARKER", "default")
digest = hashlib.sha256(source.read_bytes()).hexdigest()
for page in range(start, end + 1):
    pathlib.Path(f"{prefix}-{page}.png").write_bytes(
        f"PNG marker={marker} source={digest} page={page}\n".encode()
    )
PY

cat >"$fake_bin/pdftotext" <<'PY'
#!/usr/bin/env python3
import hashlib
import os
import pathlib
import sys

args = sys.argv[1:]
page = int(args[args.index("-f") + 1])
if os.environ.get("FAIL_TEXT") == "1" or os.environ.get("FAIL_TEXT_PAGE") == str(page):
    print("simulated text extraction failure", file=sys.stderr)
    raise SystemExit(23)
source = pathlib.Path(args[-2])
output = pathlib.Path(args[-1])
digest = hashlib.sha256(source.read_bytes()).hexdigest()
output.write_text(f"source={digest} page={page}\n", encoding="utf-8")
PY

cat >"$fake_bin/pdfseparate" <<'PY'
#!/usr/bin/env python3
import hashlib
import pathlib
import sys

args = sys.argv[1:]
start = int(args[args.index("-f") + 1])
end = int(args[args.index("-l") + 1])
source = pathlib.Path(args[-2])
template = args[-1]
digest = hashlib.sha256(source.read_bytes()).hexdigest()
for page in range(start, end + 1):
    pathlib.Path(template % page).write_bytes(f"%PDF-1.7\n{digest} page={page}\n".encode())
PY

chmod 755 "$fake_bin/pdfinfo" "$fake_bin/pdftoppm" "$fake_bin/pdftotext" "$fake_bin/pdfseparate"
PATH="$fake_bin:$PATH"
export PATH

render="$script_dir/render_pdf_pages.sh"
extract="$script_dir/extract_text_pages.sh"
render_rebuilt="$script_dir/render_rebuilt_pages.sh"

# Overlapping page ranges are normalized to one sorted page set. PNG is the default.
selection_source="$tmp_dir/selection.pdf"
selection_project="$tmp_dir/selection-project"
make_pdf "$selection_source" 5 selection
"$render" "$selection_source" "$selection_project" 90 --pages '1-3,2,3-4' >/dev/null
assert_manifest_pages "$selection_project/evidence/source-pages/manifest.json" '1,2,3,4'
assert_file "$selection_project/evidence/source-pages/page-001.png"
assert_file "$selection_project/evidence/source-pages/page-004.png"
assert_absent "$selection_project/evidence/source-pages/page-001.pdf"
assert_absent "$selection_project/evidence/source-pages/page-005.png"
if "$render" "$selection_source" "$selection_project" 90 --pages 6 >/dev/null 2>&1; then
  fail 'out-of-range page selection should fail'
fi
"$render" "$selection_source" "$selection_project" 90 --pages 5 --single-page-pdf >/dev/null
assert_file "$selection_project/evidence/source-pages/page-005.png"
assert_file "$selection_project/evidence/source-pages/page-005.pdf"
selection_manifest_hash=$(file_hash "$selection_project/evidence/source-pages/manifest.json")
if "$render" "$selection_source" "$selection_project" 90 --pages 5 --force \
  --accept-source-change \
  --source-sha256 aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa \
  >/dev/null 2>&1; then
  fail 'explicit source identity mismatch must not be bypassed by --accept-source-change'
fi
assert_hash "$selection_manifest_hash" "$selection_project/evidence/source-pages/manifest.json"

# Concurrent batches serialize manifest updates instead of losing one batch.
concurrent_source="$tmp_dir/concurrent.pdf"
concurrent_project="$tmp_dir/concurrent-project"
make_pdf "$concurrent_source" 3 concurrent
RENDER_DELAY=0.2 "$render" "$concurrent_source" "$concurrent_project" 90 --pages 1 >/dev/null &
render_one_pid=$!
RENDER_DELAY=0.2 "$render" "$concurrent_source" "$concurrent_project" 90 --pages 2 >/dev/null &
render_two_pid=$!
wait "$render_one_pid"
wait "$render_two_pid"
assert_manifest_pages "$concurrent_project/evidence/source-pages/manifest.json" '1,2'
assert_file "$concurrent_project/evidence/source-pages/page-001.png"
assert_file "$concurrent_project/evidence/source-pages/page-002.png"

# Moving the same bytes updates the recorded path without invalidating evidence.
move_source="$tmp_dir/move-source.pdf"
move_project="$tmp_dir/move-project"
make_pdf "$move_source" 4 move
"$render" "$move_source" "$move_project" 90 --pages 1 >/dev/null
"$extract" "$move_source" "$move_project" --pages 1 >/dev/null
moved_source="$tmp_dir/moved-source.pdf"
mv "$move_source" "$moved_source"
"$render" "$moved_source" "$move_project" 90 --pages 2 >/dev/null
assert_manifest_path "$move_project/evidence/text-layer/manifest.json" "$moved_source"
"$extract" "$moved_source" "$move_project" --pages 2 >/dev/null
assert_manifest_path "$move_project/evidence/source-pages/manifest.json" "$moved_source"
assert_manifest_path "$move_project/evidence/text-layer/manifest.json" "$moved_source"
assert_manifest_pages "$move_project/evidence/source-pages/manifest.json" '1,2'
assert_manifest_pages "$move_project/evidence/text-layer/manifest.json" '1,2'

# A forced selected-page refresh leaves every unselected page untouched.
transaction_source="$tmp_dir/transaction.pdf"
transaction_project="$tmp_dir/transaction-project"
make_pdf "$transaction_source" 3 transaction
RENDER_MARKER=first "$render" "$transaction_source" "$transaction_project" 90 --pages 1-2 >/dev/null
page_one_hash=$(file_hash "$transaction_project/evidence/source-pages/page-001.png")
page_two_before=$(file_hash "$transaction_project/evidence/source-pages/page-002.png")
RENDER_MARKER=second "$render" "$transaction_source" "$transaction_project" 90 --pages 2 --force >/dev/null
assert_hash "$page_one_hash" "$transaction_project/evidence/source-pages/page-001.png"
page_two_after=$(file_hash "$transaction_project/evidence/source-pages/page-002.png")
[[ "$page_two_after" != "$page_two_before" ]] || fail 'selected page was not refreshed'

# Renderer failure preserves selected evidence, manifest, and the previous successful log.
manifest_hash=$(file_hash "$transaction_project/evidence/source-pages/manifest.json")
render_log_hash=$(file_hash "$transaction_project/logs/render-source-pages.log")
if FAIL_RENDER=1 RENDER_MARKER=failed "$render" "$transaction_source" "$transaction_project" 90 --pages 2 --force >/dev/null 2>&1; then
  fail 'simulated renderer failure should fail'
fi
assert_hash "$page_one_hash" "$transaction_project/evidence/source-pages/page-001.png"
assert_hash "$page_two_after" "$transaction_project/evidence/source-pages/page-002.png"
assert_hash "$manifest_hash" "$transaction_project/evidence/source-pages/manifest.json"
assert_hash "$render_log_hash" "$transaction_project/logs/render-source-pages.log"

# Text extraction has the same transactional failure behavior.
"$extract" "$transaction_source" "$transaction_project" --pages 1 >/dev/null
text_hash=$(file_hash "$transaction_project/evidence/text-layer/page-001.txt")
text_manifest_hash=$(file_hash "$transaction_project/evidence/text-layer/manifest.json")
text_log_hash=$(file_hash "$transaction_project/logs/extract-text-pages.log")
if FAIL_TEXT=1 "$extract" "$transaction_source" "$transaction_project" --pages 1 --force >/dev/null 2>&1; then
  fail 'simulated text extraction failure should fail'
fi
assert_hash "$text_hash" "$transaction_project/evidence/text-layer/page-001.txt"
assert_hash "$text_manifest_hash" "$transaction_project/evidence/text-layer/manifest.json"
assert_hash "$text_log_hash" "$transaction_project/logs/extract-text-pages.log"

# Replacing bytes at the same path is rejected until explicitly accepted.
change_source="$tmp_dir/change.pdf"
change_project="$tmp_dir/change-project"
make_pdf "$change_source" 4 old-content
"$render" "$change_source" "$change_project" 90 --pages 1 >/dev/null
"$extract" "$change_source" "$change_project" --pages 1 >/dev/null
old_page_hash=$(file_hash "$change_project/evidence/source-pages/page-001.png")
make_pdf "$change_source" 4 new-content
if "$render" "$change_source" "$change_project" 90 --pages 2 >/dev/null 2>&1; then
  fail 'same-path source replacement should be rejected by default'
fi
assert_hash "$old_page_hash" "$change_project/evidence/source-pages/page-001.png"
assert_file "$change_project/evidence/text-layer/manifest.json"
printf 'user-owned evidence note\n' >"$change_project/evidence/source-pages/notes.md"
if "$render" "$change_source" "$change_project" 90 --pages 2 --accept-source-change >/dev/null 2>&1; then
  fail 'source change must reject untracked files in a managed evidence directory'
fi
assert_file "$change_project/evidence/source-pages/notes.md"
assert_hash "$old_page_hash" "$change_project/evidence/source-pages/page-001.png"
rm "$change_project/evidence/source-pages/notes.md"
"$render" "$change_source" "$change_project" 90 --pages 2 --accept-source-change >/dev/null
assert_absent "$change_project/evidence/source-pages/page-001.png"
assert_file "$change_project/evidence/source-pages/page-002.png"
assert_absent "$change_project/evidence/text-layer/manifest.json"
assert_manifest_pages "$change_project/evidence/source-pages/manifest.json" '2'

# The input PDF itself must never be placed under the managed evidence tree.
inside_project="$tmp_dir/inside-project"
inside_source="$inside_project/evidence/source-pages/source.pdf"
mkdir -p "$(dirname -- "$inside_source")"
make_pdf "$inside_source" 2 inside
if "$render" "$inside_source" "$inside_project" 90 --pages 1 --accept-source-change >/dev/null 2>&1; then
  fail 'input PDF inside the managed evidence tree should be rejected'
fi
assert_file "$inside_source"

log_collision_project="$tmp_dir/log-collision-project"
log_collision_source="$log_collision_project/logs/render-source-pages.log"
mkdir -p "$(dirname -- "$log_collision_source")"
make_pdf "$log_collision_source" 1 log-collision
if "$render" "$log_collision_source" "$log_collision_project" 90 --pages 1 >/dev/null 2>&1; then
  fail 'input PDF at the managed operation-log path should be rejected'
fi
assert_file "$log_collision_source"

# A replaced logs directory must not redirect evidence logs outside the project.
log_symlink_source="$tmp_dir/log-symlink.pdf"
log_symlink_project="$tmp_dir/log-symlink-project"
log_symlink_outside="$tmp_dir/log-symlink-outside"
make_pdf "$log_symlink_source" 1 log-symlink
mkdir -p "$log_symlink_project" "$log_symlink_outside"
ln -s "$log_symlink_outside" "$log_symlink_project/logs"
if "$render" "$log_symlink_source" "$log_symlink_project" 90 --pages 1 >/dev/null 2>&1; then
  fail 'logs directory symlink should be rejected'
fi
if find "$log_symlink_outside" -mindepth 1 -print -quit | grep -q .; then
  fail 'evidence pipeline wrote through a logs directory symlink'
fi
python3 - "$script_dir/pdf_evidence.py" "$log_symlink_source" "$log_symlink_project" <<'PY'
import contextlib
import fcntl
import importlib.util
import io
import os
import pathlib
import sys

script = pathlib.Path(sys.argv[1])
source = pathlib.Path(sys.argv[2])
project = pathlib.Path(sys.argv[3])
spec = importlib.util.spec_from_file_location("pdf_evidence_lock_test", script)
if spec is None or spec.loader is None:
    raise SystemExit("could not load pdf_evidence.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
with contextlib.redirect_stderr(io.StringIO()):
    status = module.main(["render", str(source), str(project), "90", "--pages", "1"])
if status != 1:
    raise SystemExit("in-process logs symlink rejection returned the wrong status")
staging = list(project.joinpath("evidence").glob(".source-pages-staging-*"))
if staging:
    raise SystemExit("logs symlink rejection leaked an evidence staging directory")
lock_path = project / "evidence" / ".pipeline.lock"
descriptor = os.open(lock_path, os.O_RDWR)
try:
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    fcntl.flock(descriptor, fcntl.LOCK_UN)
except BlockingIOError as exc:
    raise SystemExit("logs symlink rejection leaked the evidence transaction lock") from exc
finally:
    os.close(descriptor)
PY

# Structurally inconsistent manifests never authorize an incremental update.
bad_source="$tmp_dir/bad-manifest.pdf"
bad_project="$tmp_dir/bad-manifest-project"
make_pdf "$bad_source" 3 bad-manifest
"$render" "$bad_source" "$bad_project" 90 --pages 1 >/dev/null
python3 - "$bad_project/evidence/source-pages/manifest.json" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
manifest = json.loads(path.read_text(encoding="utf-8"))
manifest["pages"].append(2)
path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
PY
if "$render" "$bad_source" "$bad_project" 90 --pages 2 --force >/dev/null 2>&1; then
  fail 'manifest/page-record mismatch should fail'
fi
assert_absent "$bad_project/evidence/source-pages/page-002.png"

# Rebuilt evidence accepts a changed compiled PDF only with an explicit force refresh.
rebuilt_project="$tmp_dir/rebuilt-project"
mkdir -p "$rebuilt_project"
make_pdf "$rebuilt_project/main.pdf" 3 rebuilt-one
"$render_rebuilt" "$rebuilt_project" main.pdf 90 --pages 1 >/dev/null
make_pdf "$rebuilt_project/main.pdf" 3 rebuilt-two
if "$render_rebuilt" "$rebuilt_project" main.pdf 90 --pages 2 >/dev/null 2>&1; then
  fail 'changed rebuilt PDF should require an explicit refresh'
fi
"$render_rebuilt" "$rebuilt_project" main.pdf 90 --pages 2 --force >/dev/null
assert_absent "$rebuilt_project/evidence/rebuilt-pages/page-001.png"
assert_file "$rebuilt_project/evidence/rebuilt-pages/page-002.png"
assert_manifest_pages "$rebuilt_project/evidence/rebuilt-pages/manifest.json" '2'

# Incomplete recovery retains staging even when its diagnostic marker cannot be written.
incremental_recovery_source="$tmp_dir/incremental-recovery.pdf"
incremental_recovery_project="$tmp_dir/incremental-recovery-project"
make_pdf "$incremental_recovery_source" 1 incremental-recovery
"$render" "$incremental_recovery_source" "$incremental_recovery_project" 90 --pages 1 >/dev/null
reset_recovery_source="$tmp_dir/reset-recovery.pdf"
reset_recovery_project="$tmp_dir/reset-recovery-project"
make_pdf "$reset_recovery_source" 1 reset-old
"$render" "$reset_recovery_source" "$reset_recovery_project" 90 --pages 1 >/dev/null
make_pdf "$reset_recovery_source" 1 reset-new
python3 - \
  "$script_dir/pdf_evidence.py" \
  "$incremental_recovery_source" \
  "$incremental_recovery_project" \
  "$reset_recovery_source" \
  "$reset_recovery_project" <<'PY'
import fcntl
import importlib.util
import os
import pathlib
import sys
from unittest import mock

script = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("pdf_evidence_recovery_test", script)
if spec is None or spec.loader is None:
    raise SystemExit("could not load pdf_evidence.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
real_replace = os.replace
real_write_text = pathlib.Path.write_text

def exercise(source, project, arguments, failed_calls, backup_name):
    replace_calls = 0

    def fail_commit_and_restore(source_path, destination_path):
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls in failed_calls:
            raise OSError(f"injected replace failure {replace_calls}")
        return real_replace(source_path, destination_path)

    def fail_recovery_marker(path, *args, **kwargs):
        if path.name == "RECOVERY_REQUIRED.txt":
            raise OSError("injected recovery marker failure")
        return real_write_text(path, *args, **kwargs)

    parsed = module.build_parser().parse_args(
        ["render", str(source), str(project), "90", *arguments]
    )
    with mock.patch.object(module.os, "replace", side_effect=fail_commit_and_restore), mock.patch.object(
        pathlib.Path, "write_text", new=fail_recovery_marker
    ):
        try:
            parsed.handler(parsed)
        except module.RecoveryRequiredError as exc:
            message = str(exc)
        else:
            raise SystemExit("injected incomplete recovery unexpectedly succeeded")
    stages = list(project.joinpath("evidence").glob(".source-pages-staging-*"))
    if len(stages) != 1 or str(stages[0]) not in message:
        raise SystemExit("incomplete recovery did not retain and report its staging tree")
    if "injected recovery marker failure" not in message:
        raise SystemExit("recovery marker failure was not included in the diagnostic")
    if stages[0].joinpath("RECOVERY_REQUIRED.txt").exists():
        raise SystemExit("recovery marker failure unexpectedly created a marker")
    backup_root = stages[0] / backup_name
    if not backup_root.is_dir() or not any(backup_root.iterdir()):
        raise SystemExit("retained staging does not contain the original evidence backup")
    lock_path = project / "evidence" / ".pipeline.lock"
    descriptor = os.open(lock_path, os.O_RDWR)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    except BlockingIOError as exc:
        raise SystemExit("incomplete recovery did not release the evidence lock") from exc
    finally:
        os.close(descriptor)


exercise(
    pathlib.Path(sys.argv[2]),
    pathlib.Path(sys.argv[3]),
    ["--pages", "1", "--force"],
    {3, 4},
    "backup-files",
)
exercise(
    pathlib.Path(sys.argv[4]),
    pathlib.Path(sys.argv[5]),
    ["--pages", "1", "--accept-source-change"],
    {4, 5},
    "backup-dirs",
)
PY

printf 'Evidence pipeline tests passed.\n'
