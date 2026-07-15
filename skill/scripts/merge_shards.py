#!/usr/bin/env python3
"""Validate page-IR shards and atomically register them in a batch ledger."""

from __future__ import annotations

import argparse
from collections import Counter
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


MANIFEST_SCHEMA_VERSION = 1
LEGACY_SHARD_SCHEMA_VERSION = 1
COMPACT_SHARD_SCHEMA_VERSION = 2
SUPPORTED_SHARD_SCHEMA_VERSIONS = {LEGACY_SHARD_SCHEMA_VERSION, COMPACT_SHARD_SCHEMA_VERSION}
MANIFEST_NAME = "batch-manifest.json"
LOCK_NAME = ".batch-manifest.lock"
BATCH_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
STATUSES = {"pending", "in-progress", "rebuilt", "blocked", "omitted-with-reason"}


class MergeError(RuntimeError):
    """A user-facing shard merge failure."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise MergeError(f"Could not read file {path}: {exc}") from exc
    return digest.hexdigest()


def is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def is_nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def require_nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MergeError(f"Shard field {field} must be a non-empty string.")
    return value.strip()


def require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise MergeError(f"Shard field {field} must be a lowercase SHA-256 digest.")
    return value


def read_json(path: Path, description: str) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MergeError(f"Could not read {description} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise MergeError(f"{description.capitalize()} must contain a JSON object: {path}")
    return value


def reject_symlink_components(root: Path, relative: Path, description: str) -> None:
    current = root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise MergeError(f"{description} must not be a symbolic link: {current}")


def project_relative(project: Path, raw: Any, description: str) -> tuple[Path, str]:
    if not isinstance(raw, str) or not raw.strip():
        raise MergeError(f"{description} must be a non-empty project-relative path.")
    raw_path = Path(raw).expanduser()
    if raw_path.is_absolute():
        try:
            raw_relative = raw_path.relative_to(project)
        except ValueError as exc:
            raise MergeError(f"{description} must stay inside the project: {raw}") from exc
        if ".." in raw_relative.parts:
            raise MergeError(f"{description} must stay inside the project: {raw}")
        reject_symlink_components(project, raw_relative, description)
        candidate = raw_path
        relative = raw_relative
    else:
        relative = raw_path
        if ".." in relative.parts:
            raise MergeError(f"{description} must stay inside the project: {raw}")
        reject_symlink_components(project, relative, description)
        candidate = project / relative
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(project)
    except ValueError as exc:
        raise MergeError(f"{description} must stay inside the project: {raw}") from exc
    return candidate, relative.as_posix()


def require_regular_nonempty(path: Path, description: str) -> None:
    if path.is_symlink():
        raise MergeError(f"{description} must not be a symbolic link: {path}")
    try:
        mode = path.stat().st_mode
    except OSError as exc:
        raise MergeError(f"Missing {description}: {path}") from exc
    if not stat.S_ISREG(mode):
        raise MergeError(f"{description} must be a regular file: {path}")
    if path.stat().st_size <= 0:
        raise MergeError(f"{description} must not be empty: {path}")


def validate_identity(source: Any, expected: dict[str, Any], description: str) -> None:
    if not isinstance(source, dict):
        raise MergeError(f"{description} is missing a source identity object.")
    sha256 = require_sha256(source.get("sha256"), f"{description}.sha256")
    size_bytes = source.get("size_bytes")
    page_count = source.get("page_count")
    if not is_positive_int(size_bytes):
        raise MergeError(f"{description}.size_bytes must be a positive integer.")
    if not is_positive_int(page_count):
        raise MergeError(f"{description}.page_count must be a positive integer.")
    actual = (sha256, size_bytes, page_count)
    recorded = (expected["sha256"], expected["size_bytes"], expected["page_count"])
    if actual != recorded:
        raise MergeError(
            f"{description} does not match the project source identity: "
            f"expected {recorded[0]}/{recorded[1]}/{recorded[2]}, "
            f"found {actual[0]}/{actual[1]}/{actual[2]}"
        )


def validate_page_list(value: Any, field: str, page_count: int) -> list[int]:
    if not isinstance(value, list):
        raise MergeError(f"Shard field {field} must be an array.")
    pages: list[int] = []
    seen: set[int] = set()
    for page in value:
        if not is_positive_int(page) or page > page_count:
            raise MergeError(f"Shard field {field} contains an invalid page: {page!r}")
        if page in seen:
            raise MergeError(f"Shard field {field} contains duplicate page {page}.")
        seen.add(page)
        pages.append(page)
    return sorted(pages)


def validate_status(status: Any, field: str) -> str:
    if not isinstance(status, str) or status not in STATUSES:
        allowed = ", ".join(sorted(STATUSES))
        raise MergeError(f"{field} must be one of {allowed}; reviewed is parent-owned.")
    return status


def validate_blocker_fields(record: dict[str, Any], status: str, prefix: str) -> None:
    if status == "blocked":
        require_nonempty_string(record.get("reason"), f"{prefix}.reason")
        require_nonempty_string(record.get("next_action"), f"{prefix}.next_action")
    elif status == "omitted-with-reason":
        require_nonempty_string(record.get("reason"), f"{prefix}.reason")


def validate_snapshot(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return require_sha256(value, field)


def validate_usage(value: Any, field: str) -> dict[str, int] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise MergeError(f"{field} must be an object when present.")
    allowed = {
        "input_tokens",
        "output_tokens",
        "cached_input_tokens",
        "reasoning_tokens",
        "duration_ms",
        "retry_count",
    }
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise MergeError(f"{field} contains unknown fields: {', '.join(unknown)}")
    result: dict[str, int] = {}
    for name, raw in value.items():
        if not is_nonnegative_int(raw):
            raise MergeError(f"{field}.{name} must be a non-negative integer.")
        result[name] = raw
    if (
        result.get("cached_input_tokens", 0) > result.get("input_tokens", 0)
        and "cached_input_tokens" in result
        and "input_tokens" in result
    ):
        raise MergeError(f"{field}.cached_input_tokens exceeds input_tokens.")
    return result


def summarize_page_records(
    page_records: dict[int, dict[str, Any]], schema_version: int
) -> dict[str, Any]:
    status_counts = Counter(record["status"] for record in page_records.values())
    summary = {
        "owned_page_count": len(page_records),
        "status_counts": {status: status_counts.get(status, 0) for status in sorted(STATUSES)},
        "blocked_page_count": status_counts.get("blocked", 0),
        "uncertain_page_count": 0,
        "block_count": 0,
        "object_count": 0,
        "continuity_count": 0,
        "uncertainty_count": 0,
    }
    for record in page_records.values():
        if schema_version == COMPACT_SHARD_SCHEMA_VERSION:
            block_count = record["block_count"]
            object_count = record["object_count"]
            continuity_count = record["continuity_count"]
            uncertainty_count = record["uncertainty_count"]
        else:
            block_count = len(record["blocks"])
            object_count = len(record["objects"])
            continuity_count = len(record["continuity"])
            uncertainty_count = len(record["uncertainties"])
        summary["block_count"] += block_count
        summary["object_count"] += object_count
        summary["continuity_count"] += continuity_count
        summary["uncertainty_count"] += uncertainty_count
        if uncertainty_count > 0:
            summary["uncertain_page_count"] += 1
    summary["review_required"] = bool(
        summary["blocked_page_count"] or summary["uncertain_page_count"]
    )
    return summary


def validate_worker_summary(
    value: Any,
    expected: dict[str, Any],
    required: bool,
) -> dict[str, Any] | None:
    if value is None:
        if required:
            raise MergeError("Compact shard must include worker_summary.")
        return None
    if not isinstance(value, dict):
        raise MergeError("worker_summary must be an object.")
    text = value.get("text")
    if not isinstance(text, str) or not text.strip():
        raise MergeError("worker_summary.text must be a non-empty string.")
    if len(text) > 1200:
        raise MergeError("worker_summary.text must be at most 1200 characters.")
    for field in ("owned_page_count", "blocked_page_count", "uncertain_page_count"):
        if not is_nonnegative_int(value.get(field)):
            raise MergeError(f"worker_summary.{field} must be a non-negative integer.")
        if value[field] != expected[field]:
            raise MergeError(
                f"worker_summary.{field} does not match page records: "
                f"expected {expected[field]}, found {value[field]}"
            )
    return {
        "text": text.strip(),
        "owned_page_count": value["owned_page_count"],
        "blocked_page_count": value["blocked_page_count"],
        "uncertain_page_count": value["uncertain_page_count"],
    }


def validate_shard(project: Path, shard_path: Path, expected: dict[str, Any]) -> dict[str, Any]:
    require_regular_nonempty(shard_path, "Shard")
    shard = read_json(shard_path, "shard")
    shard_schema_version = shard.get("schema_version")
    if shard_schema_version not in SUPPORTED_SHARD_SCHEMA_VERSIONS:
        allowed = ", ".join(str(item) for item in sorted(SUPPORTED_SHARD_SCHEMA_VERSIONS))
        raise MergeError(f"Shard schema_version must be one of {allowed}: {shard_path}")
    if shard.get("kind") != "page-ir-shard":
        raise MergeError(f"Shard kind must be page-ir-shard: {shard_path}")
    batch_id = require_nonempty_string(shard.get("batch_id"), "batch_id")
    if BATCH_ID_RE.fullmatch(batch_id) is None:
        raise MergeError(f"Shard batch_id contains unsafe characters: {batch_id}")
    validate_identity(shard.get("source"), expected, "Shard source")
    owned_pages = validate_page_list(shard.get("owned_pages"), "owned_pages", expected["page_count"])
    if not owned_pages:
        raise MergeError("Shard owned_pages must contain at least one page.")
    context_pages = validate_page_list(
        shard.get("context_pages"), "context_pages", expected["page_count"]
    )
    snapshots = {
        "style_profile_sha256": validate_snapshot(
            shard.get("style_profile_sha256"), "style_profile_sha256"
        ),
        "document_ir_sha256": validate_snapshot(
            shard.get("document_ir_sha256"), "document_ir_sha256"
        ),
    }
    status = validate_status(shard.get("status"), "Shard status")
    validate_blocker_fields(shard, status, "Shard")

    raw_pages = shard.get("pages")
    if not isinstance(raw_pages, list):
        raise MergeError("Shard field pages must be an array.")
    page_records: dict[int, dict[str, Any]] = {}
    for index, record in enumerate(raw_pages):
        if not isinstance(record, dict):
            raise MergeError(f"Shard page record {index} must be an object.")
        page = record.get("page")
        if not is_positive_int(page):
            raise MergeError(f"Shard page record {index} has an invalid page number.")
        if page in page_records:
            raise MergeError(f"Shard contains duplicate page record {page}.")
        if page not in owned_pages:
            raise MergeError(f"Shard page {page} is not in owned_pages.")
        require_nonempty_string(record.get("route"), f"page {page}.route")
        page_status = validate_status(record.get("status"), f"page {page}.status")
        if shard_schema_version == COMPACT_SHARD_SCHEMA_VERSION:
            for field in ("block_count", "object_count", "continuity_count", "uncertainty_count"):
                if not is_nonnegative_int(record.get(field)):
                    raise MergeError(f"Shard page {page}.{field} must be a non-negative integer.")
        else:
            for field in ("blocks", "objects", "continuity", "uncertainties"):
                if not isinstance(record.get(field), list):
                    raise MergeError(f"Shard page {page}.{field} must be an array.")
        validate_blocker_fields(record, page_status, f"page {page}")
        page_records[page] = record
    missing_pages = sorted(set(owned_pages) - set(page_records))
    if missing_pages:
        raise MergeError(f"Shard does not contain page records for owned pages: {missing_pages}")

    summary = summarize_page_records(page_records, shard_schema_version)
    worker_summary = validate_worker_summary(
        shard.get("worker_summary"), summary, shard_schema_version == COMPACT_SHARD_SCHEMA_VERSION
    )
    usage = validate_usage(shard.get("usage"), "Shard usage")

    artifacts = shard.get("artifacts")
    if not isinstance(artifacts, list):
        raise MergeError("Shard field artifacts must be an array.")
    artifact_records: list[dict[str, str]] = []
    seen_artifacts: set[str] = set()
    for raw_artifact in artifacts:
        artifact_path, relative = project_relative(project, raw_artifact, "Artifact path")
        if relative in seen_artifacts:
            raise MergeError(f"Shard lists duplicate artifact path: {relative}")
        seen_artifacts.add(relative)
        require_regular_nonempty(artifact_path, "Artifact")
        artifact_records.append({"path": relative, "sha256": sha256_file(artifact_path)})

    detail_artifact = None
    if shard_schema_version == COMPACT_SHARD_SCHEMA_VERSION:
        raw_detail_artifact = require_nonempty_string(
            shard.get("detail_artifact"), "detail_artifact"
        )
        _, detail_artifact = project_relative(project, raw_detail_artifact, "detail_artifact")
        if detail_artifact not in seen_artifacts:
            raise MergeError("Compact shard detail_artifact must be listed in artifacts.")

    try:
        shard_relative = shard_path.relative_to(project).as_posix()
    except ValueError as exc:
        raise MergeError(f"Shard must stay inside the project: {shard_path}") from exc
    return {
        "schema_version": shard_schema_version,
        "batch_id": batch_id,
        "owned_pages": owned_pages,
        "context_pages": context_pages,
        "snapshots": snapshots,
        "status": status,
        "shard": shard,
        "shard_path": shard_path,
        "shard_relative": shard_relative,
        "shard_sha256": sha256_file(shard_path),
        "artifacts": artifact_records,
        "summary": summary,
        "worker_summary": worker_summary,
        "usage": usage,
        "detail_artifact": detail_artifact,
    }


def validate_manifest(project: Path, manifest_path: Path) -> dict[str, Any]:
    if manifest_path.is_symlink():
        raise MergeError(f"Batch manifest must not be a symbolic link: {manifest_path}")
    require_regular_nonempty(manifest_path, "Batch manifest")
    manifest = read_json(manifest_path, "batch manifest")
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise MergeError(f"Batch manifest schema_version must be {MANIFEST_SCHEMA_VERSION}.")
    source = manifest.get("source")
    if not isinstance(source, dict):
        raise MergeError("Batch manifest is missing source identity.")
    sha256 = require_sha256(source.get("sha256"), "Manifest source.sha256")
    size_bytes = source.get("size_bytes")
    page_count = source.get("page_count")
    if not is_positive_int(size_bytes) or not is_positive_int(page_count):
        raise MergeError("Manifest source size_bytes and page_count must be positive integers.")
    context = manifest.get("context", {})
    if not isinstance(context, dict):
        raise MergeError("Batch manifest context must be an object.")
    for field in ("style_profile_sha256", "document_ir_sha256"):
        validate_snapshot(context.get(field), f"Manifest context.{field}")
    batches = manifest.get("batches")
    if not isinstance(batches, list):
        raise MergeError("Batch manifest batches must be an array.")
    expected = {"sha256": sha256, "size_bytes": size_bytes, "page_count": page_count}
    seen_ids: set[str] = set()
    owned_pages: dict[int, str] = {}
    for index, record in enumerate(batches):
        if not isinstance(record, dict):
            raise MergeError(f"Manifest batch record {index} must be an object.")
        batch_id = require_nonempty_string(record.get("batch_id"), f"Manifest batch {index}.batch_id")
        if BATCH_ID_RE.fullmatch(batch_id) is None:
            raise MergeError(f"Manifest batch id contains unsafe characters: {batch_id}")
        if batch_id in seen_ids:
            raise MergeError(f"Manifest contains duplicate batch_id: {batch_id}")
        seen_ids.add(batch_id)
        pages = validate_page_list(record.get("owned_pages"), f"Manifest batch {batch_id}.owned_pages", page_count)
        if not pages:
            raise MergeError(f"Manifest batch {batch_id}.owned_pages must contain at least one page.")
        status = validate_status(record.get("status"), f"Manifest batch {batch_id}.status")
        validate_blocker_fields(record, status, f"Manifest batch {batch_id}")
        validate_usage(record.get("usage"), f"Manifest batch {batch_id}.usage")
        for page in pages:
            previous = owned_pages.get(page)
            if previous is not None:
                raise MergeError(f"Manifest page {page} is owned by both {previous} and {batch_id}.")
            owned_pages[page] = batch_id
        validate_identity(record.get("source", source), expected, f"Manifest batch {batch_id}.source")
    return {
        "manifest": manifest,
        "expected": expected,
        "context": context,
        "batches_by_id": {record["batch_id"]: record for record in batches},
        "owned_pages": owned_pages,
    }


def merge_snapshots(context: dict[str, Any], shard_infos: list[dict[str, Any]]) -> None:
    for field in ("style_profile_sha256", "document_ir_sha256"):
        value = context.get(field)
        for info in shard_infos:
            candidate = info["snapshots"][field]
            if candidate is None:
                continue
            if value is not None and value != candidate:
                raise MergeError(f"Shard {field} does not match the batch manifest context.")
            value = candidate
        if value is not None:
            context[field] = value


def build_batch_record(info: dict[str, Any]) -> dict[str, Any]:
    record: dict[str, Any] = {
        "batch_id": info["batch_id"],
        "shard_schema_version": info["schema_version"],
        "owned_pages": info["owned_pages"],
        "context_pages": info["context_pages"],
        "source": {
            "sha256": info["shard"]["source"]["sha256"],
            "size_bytes": info["shard"]["source"]["size_bytes"],
            "page_count": info["shard"]["source"]["page_count"],
        },
        "shard": info["shard_relative"],
        "shard_sha256": info["shard_sha256"],
        "artifacts": info["artifacts"],
        "status": info["status"],
        "summary": info["summary"],
        "attempt": 1,
        "merged_at": utc_now(),
    }
    for field in ("style_profile_sha256", "document_ir_sha256"):
        if info["snapshots"][field] is not None:
            record[field] = info["snapshots"][field]
    for field in ("reason", "next_action"):
        if field in info["shard"]:
            record[field] = info["shard"][field]
    if info["worker_summary"] is not None:
        record["worker_summary"] = info["worker_summary"]
    if info["usage"] is not None:
        record["usage"] = info["usage"]
    if info["detail_artifact"] is not None:
        record["detail_artifact"] = info["detail_artifact"]
    return record


def acquire_lock(project: Path) -> int:
    lock_path = project / LOCK_NAME
    if lock_path.is_symlink():
        raise MergeError(f"Batch manifest lock must not be a symbolic link: {lock_path}")
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
    except OSError as exc:
        raise MergeError(f"Could not acquire batch manifest lock {lock_path}: {exc}") from exc
    return descriptor


@contextmanager
def manifest_lock(project: Path) -> Iterator[None]:
    descriptor = acquire_lock(project)
    try:
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def write_manifest_atomic(path: Path, manifest: dict[str, Any]) -> None:
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError as exc:
        raise MergeError(f"Could not stat batch manifest {path}: {exc}") from exc
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".batch-manifest.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            os.chmod(temporary, mode)
            json.dump(manifest, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    except OSError as exc:
        raise MergeError(f"Could not atomically update batch manifest {path}: {exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def merge(project_dir: str, raw_shards: list[str]) -> tuple[int, int]:
    project = Path(project_dir).expanduser().resolve(strict=True)
    if not project.is_dir():
        raise MergeError(f"Project directory is not a directory: {project}")
    manifest_path = project / MANIFEST_NAME
    with manifest_lock(project):
        manifest_info = validate_manifest(project, manifest_path)
        shard_paths: list[Path] = []
        seen_inputs: set[str] = set()
        for raw in raw_shards:
            candidate, relative = project_relative(project, raw, "Shard path")
            if relative in seen_inputs:
                raise MergeError(f"Shard listed more than once: {relative}")
            seen_inputs.add(relative)
            shard_paths.append(candidate)

        infos = [validate_shard(project, path, manifest_info["expected"]) for path in shard_paths]
        merge_snapshots(manifest_info["context"], infos)
        existing = manifest_info["batches_by_id"]
        owned_pages = dict(manifest_info["owned_pages"])
        new_records: list[dict[str, Any]] = []
        skipped = 0
        pending_ids: dict[str, str] = {}
        pending_pages: dict[int, str] = {}
        for info in infos:
            batch_id = info["batch_id"]
            existing_record = existing.get(batch_id)
            if existing_record is not None:
                if existing_record.get("shard_sha256") != info["shard_sha256"]:
                    raise MergeError(f"Batch {batch_id} already exists with a different shard hash.")
                if existing_record.get("artifacts") != info["artifacts"]:
                    raise MergeError(f"Batch {batch_id} has changed artifact hashes.")
                skipped += 1
                continue
            previous_pending = pending_ids.get(batch_id)
            if previous_pending is not None:
                if previous_pending != info["shard_sha256"]:
                    raise MergeError(f"Batch {batch_id} appears more than once with different shard hashes.")
                raise MergeError(f"Batch {batch_id} appears more than once in one merge request.")
            pending_ids[batch_id] = info["shard_sha256"]
            for page in info["owned_pages"]:
                previous = owned_pages.get(page) or pending_pages.get(page)
                if previous is not None:
                    raise MergeError(f"Page {page} is already owned by batch {previous}.")
                pending_pages[page] = batch_id
            new_records.append(build_batch_record(info))

        if not new_records:
            return 0, skipped
        manifest = manifest_info["manifest"]
        manifest["context"] = manifest_info["context"]
        manifest.setdefault("batches", []).extend(new_records)
        write_manifest_atomic(manifest_path, manifest)
        return len(new_records), skipped


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project_dir", help="Project containing batch-manifest.json")
    parser.add_argument("shards", nargs="+", help="Project-relative or absolute shard JSON paths")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        merged, skipped = merge(args.project_dir, args.shards)
    except MergeError as exc:
        print(f"Shard merge failed: {exc}", file=sys.stderr)
        return 1
    print(f"Merged {merged} shard(s); skipped {skipped} idempotent shard(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
