#!/usr/bin/env bash
set -euo pipefail

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
merge="$script_dir/merge_shards.py"
tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/pdf-to-latex-shards.XXXXXX")
trap 'rm -rf "$tmp_dir"' EXIT HUP INT TERM
export PYTHONDONTWRITEBYTECODE=1

fail() {
  printf 'Shard merge test failed: %s\n' "$*" >&2
  exit 1
}

expect_failure() {
  if "$@" >"$tmp_dir/last.stdout" 2>"$tmp_dir/last.stderr"; then
    fail "expected command to fail: $*"
  fi
}

assert_hash() {
  expected=$1
  path=$2
  actual=$(python3 - "$path" <<'PY'
import hashlib
import pathlib
import sys

print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())
PY
)
  [[ "$actual" == "$expected" ]] || fail "manifest changed unexpectedly: $path"
}

hash_file() {
  python3 - "$1" <<'PY'
import hashlib
import pathlib
import sys

print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())
PY
}

make_project() {
  project=$1
  mkdir -p "$project/work/shards"
  python3 - "$project" <<'PY'
import json
import pathlib
import sys

project = pathlib.Path(sys.argv[1])
manifest = {
    "schema_version": 1,
    "source": {
        "path": "/tmp/source.pdf",
        "sha256": "a" * 64,
        "size_bytes": 123,
        "page_count": 8,
    },
    "project": {"target_directory": str(project)},
    "context": {"style_profile_sha256": "b" * 64, "document_ir_sha256": "c" * 64},
    "batches": [],
}
(project / "batch-manifest.json").write_text(
    json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
)
PY
}

write_shard() {
  project=$1
  relative=$2
  batch_id=$3
  owned_pages=$4
  source_sha=${5:-$(printf '%064d' 0)}
  artifact_relative=${6:-"$relative.artifact"}
  status=${7:-rebuilt}
  python3 - "$project" "$relative" "$batch_id" "$owned_pages" "$source_sha" "$artifact_relative" "$status" <<'PY'
import json
import pathlib
import sys

project = pathlib.Path(sys.argv[1])
relative = pathlib.Path(sys.argv[2])
batch_id = sys.argv[3]
pages = [int(item) for item in sys.argv[4].split(",") if item]
source_sha = sys.argv[5]
artifact = pathlib.Path(sys.argv[6])
status = sys.argv[7]
shard_path = project / relative
artifact_path = project / artifact
shard_path.parent.mkdir(parents=True, exist_ok=True)
artifact_path.parent.mkdir(parents=True, exist_ok=True)
artifact_path.write_text("artifact for " + batch_id, encoding="utf-8")
records = [
    {
        "page": page,
        "route": "digital-text",
        "status": status,
        "blocks": [],
        "objects": [],
        "continuity": [],
        "uncertainties": [],
    }
    for page in pages
]
shard = {
    "schema_version": 1,
    "kind": "page-ir-shard",
    "batch_id": batch_id,
    "source": {
        "path": "/tmp/source.pdf",
        "sha256": source_sha,
        "size_bytes": 123,
        "page_count": 8,
    },
    "owned_pages": pages,
    "context_pages": [],
    "style_profile_sha256": "b" * 64,
    "document_ir_sha256": "c" * 64,
    "pages": records,
    "artifacts": [artifact.as_posix()],
    "status": status,
}
shard_path.write_text(json.dumps(shard, indent=2) + "\n", encoding="utf-8")
PY
}

[[ -x "$merge" ]] || fail 'merge_shards.py must be executable'

project="$tmp_dir/project"
make_project "$project"
source_sha=$(printf 'a%.0s' {1..64})
other_sha=$(printf 'b%.0s' {1..64})
write_shard "$project" work/shards/batch-a/shard.json batch-a 1,2 "$source_sha" \
  work/shards/batch-a/page-001.json
write_shard "$project" work/shards/batch-b/shard.json batch-b 3 "$source_sha" \
  work/shards/batch-b/page-003.json
"$merge" "$project" \
  "$project/work/shards/batch-a/shard.json" \
  "$project/work/shards/batch-b/shard.json" >/dev/null
python3 - "$project/batch-manifest.json" <<'PY'
import json
import pathlib
import sys

manifest = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
assert [record["batch_id"] for record in manifest["batches"]] == ["batch-a", "batch-b"]
assert manifest["batches"][0]["owned_pages"] == [1, 2]
assert manifest["batches"][1]["owned_pages"] == [3]
assert manifest["batches"][0]["shard"] == "work/shards/batch-a/shard.json"
assert len(manifest["batches"][0]["artifacts"][0]["sha256"]) == 64
PY

before=$(python3 - "$project/batch-manifest.json" <<'PY'
import hashlib
import pathlib
import sys

print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())
PY
)
"$merge" "$project" "$project/work/shards/batch-a/shard.json" >/dev/null
assert_hash "$before" "$project/batch-manifest.json"

write_shard "$project" work/shards/batch-c/shard.json batch-c 2 "$source_sha" \
  work/shards/batch-c/page-002.json
before=$(hash_file "$project/batch-manifest.json")
expect_failure "$merge" "$project" "$project/work/shards/batch-c/shard.json"
assert_hash "$before" "$project/batch-manifest.json"

write_shard "$project" work/shards/batch-bad-source/shard.json batch-bad-source 4 "$other_sha" \
  work/shards/batch-bad-source/page-004.json
before=$(hash_file "$project/batch-manifest.json")
expect_failure "$merge" "$project" "$project/work/shards/batch-bad-source/shard.json"
assert_hash "$before" "$project/batch-manifest.json"

write_shard "$project" work/shards/batch-missing/shard.json batch-missing 5,6 "$source_sha" \
  work/shards/batch-missing/page-005.json
python3 - "$project/work/shards/batch-missing/shard.json" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
shard = json.loads(path.read_text(encoding="utf-8"))
shard["pages"] = shard["pages"][:1]
path.write_text(json.dumps(shard, indent=2) + "\n", encoding="utf-8")
PY
before=$(hash_file "$project/batch-manifest.json")
expect_failure "$merge" "$project" "$project/work/shards/batch-missing/shard.json"
assert_hash "$before" "$project/batch-manifest.json"

outside="$tmp_dir/outside-artifact.txt"
printf 'outside\n' >"$outside"
symlink_shard="$project/work/shards/batch-symlink/shard.json"
write_shard "$project" work/shards/batch-symlink/shard.json batch-symlink 7 "$source_sha" \
  work/shards/batch-symlink/link.txt
rm "$project/work/shards/batch-symlink/link.txt"
ln -s "$outside" "$project/work/shards/batch-symlink/link.txt"
before=$(hash_file "$project/batch-manifest.json")
expect_failure "$merge" "$project" "$symlink_shard"
assert_hash "$before" "$project/batch-manifest.json"

printf 'Shard merge tests passed.\n'
