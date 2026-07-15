#!/usr/bin/env python3
"""Build a source-bound page complexity index and adaptive worker batch plan."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

sys.dont_write_bytecode = True

from pdf_evidence import EvidenceError, SourceIdentity, source_identity  # noqa: E402


SCHEMA_VERSION = 1
PAGE_INDEX_RELATIVE = Path("work/page-index.json")
VALID_SOURCE_KINDS = {"digital", "scanned", "mixed", "unknown"}
VALID_TRAITS = {
    "book",
    "long-document",
    "math-heavy",
    "encoded-math",
    "cjk",
    "visual-complex",
}
# Base sizes by complexity. Adaptive scaling by source_kind/traits is applied in
# resolve_batch_sizes(). Scanned empties must not collapse to critical/1-page.
DEFAULT_BATCH_SIZES = {"low": 35, "medium": 12, "high": 6, "critical": 1}
FORMULA_RE = re.compile(
    r"(?:\\(?:alpha|begin|beta|corollary|end|equation|frac|gamma|int|lambda|lemma|proof|sqrt|sum|theorem)\b)"
    r"|(?:[=<>^_])|(?:\b(?:equation|theorem|lemma|proof|corollary)\b)",
    re.IGNORECASE,
)
WORD_RE = re.compile(r"\b\w+\b", re.UNICODE)


class TriageError(RuntimeError):
    """A user-facing page triage failure."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def require_project(path: str) -> Path:
    raw_project = Path(path).expanduser()
    if raw_project.is_symlink():
        raise TriageError(f"Project directory must not be a symbolic link: {raw_project}")
    project = raw_project.resolve(strict=True)
    if not project.is_dir():
        raise TriageError(f"Project directory is not a directory: {project}")
    return project


def require_source_kind(value: str) -> str:
    if value not in VALID_SOURCE_KINDS:
        raise TriageError(
            f"--source-kind must be one of {', '.join(sorted(VALID_SOURCE_KINDS))}: {value}"
        )
    return value


def parse_traits(value: str) -> list[str]:
    if value == "none":
        return []
    traits = [item.strip() for item in value.split(",") if item.strip()]
    invalid = sorted(set(traits) - VALID_TRAITS)
    if invalid:
        raise TriageError(f"Unknown document traits: {', '.join(invalid)}")
    return sorted(set(traits))


def positive_int(value: str) -> int:
    try:
        parsed = int(value, 10)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"must be a positive integer: {value}") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive integer: {value}")
    return parsed


def append_log(log_path: Path, message: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(message)
        if not message.endswith("\n"):
            handle.write("\n")


def tool_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["LC_ALL"] = "C"
    return environment


def run_pdftotext(command: Sequence[str], log_path: Path) -> str:
    append_log(log_path, f"$ {shlex.join(command)}")
    completed = subprocess.run(
        list(command),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=tool_environment(),
    )
    if completed.stderr:
        append_log(log_path, completed.stderr)
    if completed.returncode != 0:
        detail = completed.stderr.strip()
        suffix = f": {detail}" if detail else ""
        raise TriageError(f"pdftotext failed with exit code {completed.returncode}{suffix}")
    return completed.stdout


def split_page_text(output: str, page_count: int) -> list[str] | None:
    pages = output.split("\f")
    while len(pages) > page_count and not pages[-1].strip():
        pages.pop()
    if len(pages) != page_count:
        return None
    return pages


def extract_page_texts(source: Path, page_count: int, log_path: Path) -> tuple[list[str], str]:
    pdftotext = shutil.which("pdftotext")
    if pdftotext is None:
        raise TriageError("pdftotext is required to build the page complexity index.")

    output = run_pdftotext([pdftotext, "-layout", str(source), "-"], log_path)
    pages = split_page_text(output, page_count)
    if pages is not None:
        return pages, "pdftotext"

    append_log(log_path, "Page separators were not usable; falling back to bounded extraction.")
    pages = []
    for page in range(1, page_count + 1):
        page_output = run_pdftotext(
            [pdftotext, "-f", str(page), "-l", str(page), "-layout", str(source), "-"],
            log_path,
        )
        pages.append(page_output.rstrip("\f"))
    return pages, "pdftotext-per-page"


def resolve_batch_sizes(
    source_kind: str,
    traits: Sequence[str],
    base: dict[str, int] | None = None,
) -> dict[str, int]:
    """Scale batch sizes by document class without requiring per-document hardcoding."""
    sizes = dict(base or DEFAULT_BATCH_SIZES)
    trait_set = set(traits)

    if source_kind == "scanned":
        # Scanned books usually lack a text layer; keep multi-page visual batches.
        sizes["high"] = max(sizes["high"], 6)
        sizes["medium"] = max(sizes["medium"], 8)
        sizes["low"] = max(sizes["low"], 12)
    elif source_kind == "mixed":
        sizes["high"] = max(sizes["high"], 5)
        sizes["medium"] = max(sizes["medium"], 10)
    elif source_kind == "digital":
        sizes["low"] = max(sizes["low"], 30)

    if "long-document" in trait_set or "book" in trait_set:
        sizes["low"] = max(sizes["low"], 40)
        sizes["medium"] = max(sizes["medium"], 12)
        if source_kind in {"scanned", "mixed"}:
            sizes["high"] = max(sizes["high"], 6)

    if "math-heavy" in trait_set or "encoded-math" in trait_set:
        sizes["low"] = min(sizes["low"], 25)
        sizes["medium"] = min(sizes["medium"], 10)
        sizes["high"] = min(max(sizes["high"], 4), 5)

    if "visual-complex" in trait_set:
        sizes["high"] = min(sizes["high"], 4)
        sizes["medium"] = min(sizes["medium"], 8)

    # Critical stays single-page (or caller override) for true high-risk pages only.
    sizes["critical"] = max(1, sizes.get("critical", 1))
    return sizes


def classify_page(
    text: str,
    source_kind: str,
    traits: Sequence[str],
    batch_sizes: dict[str, int],
) -> dict[str, Any]:
    normalized = text.replace("\r", "")
    lines = normalized.splitlines()
    nonempty_lines = [line for line in lines if line.strip()]
    text_chars = len(normalized.strip())
    word_count = len(WORD_RE.findall(normalized))
    formula_markers = len(FORMULA_RE.findall(normalized))
    empty_text = not normalized.strip()
    table_lines = sum(
        1
        for line in nonempty_lines
        if "\t" in line
        or len(re.findall(r" {3,}", line)) >= 2
        or re.search(r"\|.+\|", line) is not None
    )

    reasons: list[str] = []
    score = 0
    if empty_text:
        reasons.append("empty-text-layer")
    if source_kind == "scanned":
        score += 4
        reasons.append("scanned-source")
    elif source_kind == "mixed":
        score += 2
        reasons.append("mixed-source")
    if text_chars < 240 and not empty_text:
        score += 2
        reasons.append("short-text-layer")
    if formula_markers >= 2:
        score += 3
        reasons.append("formula-markers")
    if table_lines >= 2:
        score += 3
        reasons.append("table-markers")
    if "math-heavy" in traits or "encoded-math" in traits:
        score += 2
        reasons.append("math-trait")
    if "visual-complex" in traits:
        score += 2
        reasons.append("visual-complex-trait")

    # Empty text on scanned (or image-only mixed) pages is expected — do not force
    # critical/single-page batches for every page of a scan.
    if empty_text and source_kind == "scanned":
        complexity = "high"
    elif empty_text and source_kind == "mixed":
        complexity = "high"
        reasons.append("mixed-empty-page")
    elif empty_text:
        complexity = "critical"
    elif source_kind == "scanned":
        complexity = "high"
    elif score >= 7:
        complexity = "high"
    elif score >= 3:
        complexity = "medium"
    else:
        complexity = "low"
    if complexity == "low" and {
        "math-heavy",
        "encoded-math",
        "visual-complex",
    }.intersection(traits):
        complexity = "medium"

    if empty_text or source_kind == "scanned":
        route = "visual-transcription"
        evidence_policy = "rendered-page-required"
    elif formula_markers >= 2 or "math-heavy" in traits or "encoded-math" in traits:
        route = "math-heavy"
        evidence_policy = "text-layer-plus-rendered-page"
    elif table_lines >= 2:
        route = "table-heavy"
        evidence_policy = "text-layer-plus-rendered-page"
    elif complexity == "low":
        route = "digital-text"
        evidence_policy = "text-layer-first"
    else:
        route = "mixed-review"
        evidence_policy = "text-layer-plus-rendered-page"

    if not reasons:
        reasons.append("ordinary-digital-text")
    return {
        "text_chars": text_chars,
        "nonempty_lines": len(nonempty_lines),
        "word_count": word_count,
        "formula_markers": formula_markers,
        "table_lines": table_lines,
        "complexity_score": score,
        "complexity": complexity,
        "route": route,
        "evidence_policy": evidence_policy,
        "recommended_batch_size": batch_sizes[complexity],
        "reason_codes": reasons,
    }


def build_batches(page_records: Sequence[dict[str, Any]], page_count: int) -> list[dict[str, Any]]:
    batches: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []

    def flush() -> None:
        if not current:
            return
        owned_pages = [record["page"] for record in current]
        start = owned_pages[0]
        end = owned_pages[-1]
        context_pages = []
        if start > 1:
            context_pages.append(start - 1)
        if end < page_count:
            context_pages.append(end + 1)
        complexity = current[0]["complexity"]
        batches.append(
            {
                "batch_id": f"plan-{len(batches) + 1:03d}",
                "owned_pages": owned_pages,
                "context_pages": context_pages,
                "complexity": complexity,
                "route": current[0]["route"],
                "worker_mode": "single-page" if len(owned_pages) == 1 else "batch",
                "detail_policy": "summary-first; load detail only for blockers, uncertainties, or integration",
                "text_chars": sum(record["text_chars"] for record in current),
            }
        )
        current.clear()

    for record in page_records:
        if not current:
            current.append(record)
            continue
        same_route = record["route"] == current[0]["route"]
        same_complexity = record["complexity"] == current[0]["complexity"]
        target = current[0]["recommended_batch_size"]
        if same_route and same_complexity and len(current) < target:
            current.append(record)
        else:
            flush()
            current.append(record)
    flush()
    return batches


def validate_project_manifest(project: Path, identity: SourceIdentity) -> None:
    manifest_path = project / "batch-manifest.json"
    if not manifest_path.exists() and not manifest_path.is_symlink():
        return
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise TriageError(f"Project batch manifest must be a regular file: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TriageError(f"Could not read project batch manifest: {manifest_path}: {exc}") from exc
    source = manifest.get("source") if isinstance(manifest, dict) else None
    if not isinstance(source, dict):
        raise TriageError(f"Project batch manifest is missing source identity: {manifest_path}")
    actual = (identity.sha256, identity.size_bytes, identity.page_count)
    recorded = (source.get("sha256"), source.get("size_bytes"), source.get("page_count"))
    if actual != recorded:
        raise TriageError(
            "Source identity does not match the project batch manifest: "
            f"expected {recorded[0]}/{recorded[1]}/{recorded[2]}, "
            f"found {actual[0]}/{actual[1]}/{actual[2]}"
        )


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    if path.is_symlink():
        raise TriageError(f"Page index must not be a symbolic link: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, ensure_ascii=True, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    except OSError as exc:
        raise TriageError(f"Could not atomically write page index {path}: {exc}") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def build_index(
    identity: SourceIdentity,
    pages: Sequence[str],
    source_kind: str,
    traits: Sequence[str],
    batch_sizes: dict[str, int],
    extractor: str,
) -> dict[str, Any]:
    page_records = []
    for number, text in enumerate(pages, start=1):
        record = {"page": number}
        record.update(classify_page(text, source_kind, traits, batch_sizes))
        page_records.append(record)
    batches = build_batches(page_records, identity.page_count)
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "page-complexity-index",
        "created_at": utc_now(),
        "extractor": extractor,
        "source": {
            "path": identity.path,
            "sha256": identity.sha256,
            "size_bytes": identity.size_bytes,
            "page_count": identity.page_count,
        },
        "policy": {
            "source_kind": source_kind,
            "traits": list(traits),
            "batch_sizes": batch_sizes,
            "worker_output": "compact-summary-with-detail-artifact",
            "evidence": "local-text-triage-before-rendered-page-escalation",
        },
        "pages": page_records,
        "batches": batches,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_pdf")
    parser.add_argument("project_dir")
    parser.add_argument("--source-kind", default="unknown")
    parser.add_argument("--traits", default="none", help="Comma-separated traits or 'none'.")
    parser.add_argument("--low-batch-size", type=positive_int, default=DEFAULT_BATCH_SIZES["low"])
    parser.add_argument(
        "--medium-batch-size", type=positive_int, default=DEFAULT_BATCH_SIZES["medium"]
    )
    parser.add_argument("--high-batch-size", type=positive_int, default=DEFAULT_BATCH_SIZES["high"])
    parser.add_argument(
        "--critical-batch-size", type=positive_int, default=DEFAULT_BATCH_SIZES["critical"]
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    if sys.version_info < (3, 10):
        print("Python 3.10 or newer is required.", file=sys.stderr)
        return 1
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        project = require_project(args.project_dir)
        source_kind = require_source_kind(args.source_kind)
        traits = parse_traits(args.traits)
        work_dir = project / "work"
        if work_dir.is_symlink() or (work_dir.exists() and not work_dir.is_dir()):
            raise TriageError(f"Project work directory must be a real directory: {work_dir}")
        work_dir.mkdir(parents=True, exist_ok=True)
        log_path = project / "logs" / "page-triage.log"
        identity = source_identity(args.source_pdf, log_path)
        validate_project_manifest(project, identity)
        page_texts, extractor = extract_page_texts(
            Path(identity.path), identity.page_count, log_path
        )
        # Start from CLI sizes (defaults or user overrides), then adapt by class.
        batch_sizes = resolve_batch_sizes(
            source_kind,
            traits,
            {
                "low": args.low_batch_size,
                "medium": args.medium_batch_size,
                "high": args.high_batch_size,
                "critical": args.critical_batch_size,
            },
        )
        index = build_index(identity, page_texts, source_kind, traits, batch_sizes, extractor)
        output = project / PAGE_INDEX_RELATIVE
        write_json_atomic(output, index)
    except (EvidenceError, OSError, TriageError, ValueError) as exc:
        print(f"Batch planning failed: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote adaptive page index and batch plan: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
