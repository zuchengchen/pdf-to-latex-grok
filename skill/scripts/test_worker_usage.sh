#!/usr/bin/env bash
set -euo pipefail

script_dir=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
merge="$script_dir/merge_shards.py"
report="$script_dir/report_worker_usage.py"
tmp_dir=$(mktemp -d "${TMPDIR:-/tmp}/pdf-to-latex-worker-usage.XXXXXX")
trap 'rm -rf "$tmp_dir"' EXIT HUP INT TERM
export PYTHONDONTWRITEBYTECODE=1

fail() {
  printf 'Worker usage test failed: %s\n' "$*" >&2
  exit 1
}

project="$tmp_dir/project"
mkdir -p "$project/work/shards/batch-v2"
python3 - "$project" <<'PY'
import json
import pathlib
import sys

project = pathlib.Path(sys.argv[1])
detail = project / "work/shards/batch-v2/details.json"
detail.write_text(json.dumps({"pages": [1, 2]}) + "\n", encoding="utf-8")
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
shard = {
    "schema_version": 2,
    "kind": "page-ir-shard",
    "batch_id": "batch-v2",
    "source": {
        "path": "/tmp/source.pdf",
        "sha256": "a" * 64,
        "size_bytes": 123,
        "page_count": 8,
    },
    "owned_pages": [1, 2],
    "context_pages": [3],
    "style_profile_sha256": "b" * 64,
    "document_ir_sha256": "c" * 64,
    "pages": [
        {
            "page": 1,
            "route": "digital-text",
            "status": "rebuilt",
            "block_count": 3,
            "object_count": 0,
            "continuity_count": 1,
            "uncertainty_count": 0,
        },
        {
            "page": 2,
            "route": "math-heavy",
            "status": "rebuilt",
            "block_count": 5,
            "object_count": 1,
            "continuity_count": 1,
            "uncertainty_count": 1,
        },
    ],
    "artifacts": ["work/shards/batch-v2/details.json"],
    "detail_artifact": "work/shards/batch-v2/details.json",
    "worker_summary": {
        "text": "Pages 1-2 rebuilt; page 2 needs parent math continuity review.",
        "owned_page_count": 2,
        "blocked_page_count": 0,
        "uncertain_page_count": 1,
    },
    "usage": {
        "input_tokens": 1000,
        "output_tokens": 300,
        "cached_input_tokens": 200,
        "reasoning_tokens": 400,
        "duration_ms": 2500,
        "retry_count": 1,
    },
    "status": "rebuilt",
}
(project / "work/shards/batch-v2/shard.json").write_text(
    json.dumps(shard, indent=2) + "\n", encoding="utf-8"
)
PY

"$merge" "$project" "$project/work/shards/batch-v2/shard.json" >/dev/null
python3 - "$project/batch-manifest.json" <<'PY'
import json
import pathlib
import sys

record = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))["batches"][0]
assert record["shard_schema_version"] == 2
assert record["summary"]["block_count"] == 8
assert record["summary"]["uncertain_page_count"] == 1
assert record["summary"]["review_required"] is True
assert record["usage"]["cached_input_tokens"] == 200
assert record["detail_artifact"] == "work/shards/batch-v2/details.json"
PY

report_json=$("$report" "$project" --format json)
python3 - "$report_json" <<'PY'
import json
import sys

report = json.loads(sys.argv[1])
assert report["input_tokens"] == 1000
assert report["cached_input_tokens"] == 200
assert report["uncached_input_tokens"] == 800
assert report["output_tokens"] == 300
assert report["retry_count"] == 1
assert report["usage_coverage"] == 1.0
assert report["cache_hit_ratio"] == 0.2
PY

printf 'Worker usage tests passed.\n'
