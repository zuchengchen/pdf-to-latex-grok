#!/usr/bin/env python3
"""Report token, cache, retry, and latency telemetry recorded in batch-manifest.json."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence

sys.dont_write_bytecode = True


class UsageReportError(RuntimeError):
    """A user-facing worker usage report failure."""


USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cached_input_tokens",
    "reasoning_tokens",
    "duration_ms",
    "retry_count",
)


def require_nonnegative(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise UsageReportError(f"{field} must be a non-negative integer.")
    return value


def read_manifest(project_dir: str) -> dict[str, Any]:
    raw_project = Path(project_dir).expanduser()
    if raw_project.is_symlink():
        raise UsageReportError(f"Project directory must not be a symbolic link: {raw_project}")
    project = raw_project.resolve(strict=True)
    if not project.is_dir():
        raise UsageReportError(f"Project directory must be a real directory: {project}")
    path = project / "batch-manifest.json"
    if path.is_symlink() or not path.is_file():
        raise UsageReportError(f"Batch manifest must be a regular file: {path}")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UsageReportError(f"Could not read batch manifest {path}: {exc}") from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get("batches"), list):
        raise UsageReportError(f"Batch manifest has no valid batches array: {path}")
    return manifest


def aggregate(manifest: dict[str, Any]) -> dict[str, Any]:
    totals = {field: 0 for field in USAGE_FIELDS}
    batches = manifest["batches"]
    page_count = 0
    batches_with_usage = 0
    missing_usage_batches: list[str] = []
    for index, record in enumerate(batches):
        if not isinstance(record, dict):
            raise UsageReportError(f"Manifest batch {index} is not an object.")
        batch_id = record.get("batch_id", f"batch-{index + 1}")
        pages = record.get("owned_pages", [])
        if not isinstance(pages, list):
            raise UsageReportError(f"Manifest batch {batch_id}.owned_pages is not an array.")
        page_count += len(pages)
        usage = record.get("usage")
        if usage is None:
            missing_usage_batches.append(str(batch_id))
            continue
        if not isinstance(usage, dict):
            raise UsageReportError(f"Manifest batch {batch_id}.usage is not an object.")
        batches_with_usage += 1
        values = {}
        for field in USAGE_FIELDS:
            raw = usage.get(field, 0)
            values[field] = require_nonnegative(raw, f"Manifest batch {batch_id}.usage.{field}")
            totals[field] += values[field]
        if values["cached_input_tokens"] > values["input_tokens"]:
            raise UsageReportError(
                f"Manifest batch {batch_id}.usage.cached_input_tokens exceeds input_tokens."
            )

    input_tokens = totals["input_tokens"]
    cached_tokens = totals["cached_input_tokens"]
    return {
        "batch_count": len(batches),
        "batches_with_usage": batches_with_usage,
        "missing_usage_batches": missing_usage_batches,
        "page_count": page_count,
        **totals,
        "uncached_input_tokens": input_tokens - cached_tokens,
        "usage_coverage": round(batches_with_usage / len(batches), 4) if batches else 0.0,
        "cache_hit_ratio": round(cached_tokens / input_tokens, 4) if input_tokens else 0.0,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_dir")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    return parser


def print_text(report: dict[str, Any]) -> None:
    print("Worker usage report")
    print(f"Batches: {report['batch_count']} ({report['batches_with_usage']} with usage)")
    print(f"Pages: {report['page_count']}")
    print(f"Input tokens: {report['input_tokens']}")
    print(f"Cached input tokens: {report['cached_input_tokens']}")
    print(f"Uncached input tokens: {report['uncached_input_tokens']}")
    print(f"Output tokens: {report['output_tokens']}")
    print(f"Reasoning tokens: {report['reasoning_tokens']}")
    print(f"Retries: {report['retry_count']}")
    print(f"Duration ms: {report['duration_ms']}")
    print(f"Usage coverage: {report['usage_coverage']:.1%}")
    print(f"Cache hit ratio: {report['cache_hit_ratio']:.1%}")
    if report["missing_usage_batches"]:
        print("Missing usage: " + ", ".join(report["missing_usage_batches"]))


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        report = aggregate(read_manifest(args.project_dir))
    except (OSError, UsageReportError, ValueError) as exc:
        print(f"Worker usage report failed: {exc}", file=sys.stderr)
        return 1
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    else:
        print_text(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
