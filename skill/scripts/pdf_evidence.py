#!/usr/bin/env python3
"""Create source and rebuilt PDF evidence without partial replacement."""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


SCHEMA_VERSION = 1
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PAGE_FILE_RE = re.compile(r"^page-([0-9]+)\.(png|pdf|txt)$")


class EvidenceError(RuntimeError):
    """A user-facing evidence pipeline failure."""


class RecoveryRequiredError(EvidenceError):
    """A failed commit whose retained staging tree is required for recovery."""


@dataclass(frozen=True)
class SourceIdentity:
    path: str
    sha256: str
    size_bytes: int
    page_count: int

    @property
    def content_key(self) -> tuple[str, int, int]:
        return (self.sha256, self.size_bytes, self.page_count)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def require_python() -> None:
    if sys.version_info < (3, 10):
        raise EvidenceError("Python 3.10 or newer is required for the PDF evidence pipeline.")


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise EvidenceError(f"Missing tool: {name} is required for this operation.")
    return path


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


def log_tail(log_path: Path, line_count: int = 20) -> str:
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-line_count:])


def run_logged(command: Sequence[str], log_path: Path, description: str) -> None:
    append_log(log_path, f"$ {shlex.join(command)}")
    with log_path.open("ab") as handle:
        result = subprocess.run(
            command,
            stdout=handle,
            stderr=subprocess.STDOUT,
            check=False,
            env=tool_environment(),
        )
    if result.returncode != 0:
        tail = log_tail(log_path)
        detail = f"\n{tail}" if tail else ""
        raise EvidenceError(f"{description} failed with exit code {result.returncode}.{detail}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_pdf_header(path: Path) -> None:
    try:
        with path.open("rb") as handle:
            header = handle.read(1024)
    except OSError as exc:
        raise EvidenceError(f"Could not read source PDF: {path}: {exc}") from exc
    if b"%PDF-" not in header:
        raise EvidenceError(f"Source file does not look like a PDF: {path}")


def pdf_page_count(path: Path, log_path: Path) -> int:
    pdfinfo = require_tool("pdfinfo")
    command = [pdfinfo, str(path)]
    append_log(log_path, f"$ {shlex.join(command)}")
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=tool_environment(),
    )
    append_log(log_path, result.stdout)
    if result.returncode != 0:
        raise EvidenceError(f"pdfinfo could not read source PDF: {path}\n{result.stdout.strip()}")
    match = re.search(r"(?m)^Pages:\s*([0-9]+)\s*$", result.stdout)
    if match is None or int(match.group(1)) <= 0:
        raise EvidenceError(f"pdfinfo did not report a positive page count for: {path}")
    return int(match.group(1))


def source_identity(source_pdf: str, log_path: Path) -> SourceIdentity:
    path = Path(source_pdf).expanduser()
    if not path.is_file():
        raise EvidenceError(f"Source PDF not found: {source_pdf}")
    path = path.resolve(strict=True)
    verify_pdf_header(path)
    stat_before = path.stat()
    digest = sha256_file(path)
    page_count = pdf_page_count(path, log_path)
    stat_after = path.stat()
    before = (stat_before.st_dev, stat_before.st_ino, stat_before.st_size, stat_before.st_mtime_ns)
    after = (stat_after.st_dev, stat_after.st_ino, stat_after.st_size, stat_after.st_mtime_ns)
    if before != after:
        raise EvidenceError(f"Source PDF changed while its identity was being computed: {path}")
    return SourceIdentity(str(path), digest, stat_after.st_size, page_count)


def validate_expected_identity(args: argparse.Namespace, identity: SourceIdentity) -> list[str]:
    mismatches: list[str] = []
    expected_sha = getattr(args, "source_sha256", None)
    expected_size = getattr(args, "source_size", None)
    expected_pages = getattr(args, "source_page_count", None)
    if expected_sha is not None and expected_sha.lower() != identity.sha256:
        mismatches.append(f"SHA-256 expected {expected_sha.lower()}, found {identity.sha256}")
    if expected_size is not None and expected_size != identity.size_bytes:
        mismatches.append(f"size expected {expected_size}, found {identity.size_bytes}")
    if expected_pages is not None and expected_pages != identity.page_count:
        mismatches.append(f"page count expected {expected_pages}, found {identity.page_count}")
    return mismatches


def positive_int(value: str) -> int:
    try:
        parsed = int(value, 10)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"must be a positive integer: {value}") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError(f"must be a positive integer: {value}")
    return parsed


def sha256_argument(value: str) -> str:
    normalized = value.lower()
    if SHA256_RE.fullmatch(normalized) is None:
        raise argparse.ArgumentTypeError("must be a 64-character hexadecimal SHA-256 digest")
    return normalized


def parse_pages(args: argparse.Namespace, page_count: int) -> list[int]:
    pages_arg = getattr(args, "pages", None)
    from_page = getattr(args, "from_page", None)
    to_page = getattr(args, "to_page", None)
    if pages_arg is not None and (from_page is not None or to_page is not None):
        raise EvidenceError("Use either --pages or --from/--to, not both.")
    if (from_page is None) != (to_page is None):
        raise EvidenceError("Use --from and --to together.")

    selected: set[int] = set()
    if pages_arg is not None:
        for raw_token in pages_arg.split(","):
            token = "".join(raw_token.split())
            if not token:
                raise EvidenceError(f"Empty page token in --pages: {pages_arg}")
            match = re.fullmatch(r"([0-9]+)(?:-([0-9]+))?", token)
            if match is None:
                raise EvidenceError(f"Invalid page token in --pages: {token}")
            start = int(match.group(1), 10)
            end = int(match.group(2), 10) if match.group(2) is not None else start
            if start <= 0 or end <= 0:
                raise EvidenceError(f"Page numbers must be positive: {token}")
            if start > end:
                raise EvidenceError(f"Page range start must be before end: {token}")
            if end > page_count:
                raise EvidenceError(f"Selected page {end} exceeds PDF page count {page_count}.")
            selected.update(range(start, end + 1))
    elif from_page is not None and to_page is not None:
        if from_page > to_page:
            raise EvidenceError(f"Page range start must be before end: {from_page}-{to_page}")
        if to_page > page_count:
            raise EvidenceError(f"Selected page {to_page} exceeds PDF page count {page_count}.")
        selected.update(range(from_page, to_page + 1))
    else:
        selected.update(range(1, page_count + 1))

    ordered = sorted(selected)
    if not ordered:
        raise EvidenceError("At least one page must be selected.")
    if ordered[-1] > page_count:
        raise EvidenceError(f"Selected page {ordered[-1]} exceeds PDF page count {page_count}.")
    return ordered


def contiguous_ranges(pages: Sequence[int]) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    start = previous = pages[0]
    for page in pages[1:]:
        if page == previous + 1:
            previous = page
            continue
        ranges.append((start, previous))
        start = previous = page
    ranges.append((start, previous))
    return ranges


def evidence_kind_name(kind: str) -> str:
    return {"source": "source-pages", "rebuilt": "rebuilt-pages", "text": "text-layer"}[kind]


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def acquire_evidence_lock(evidence_root: Path) -> int:
    lock_path = evidence_root / ".pipeline.lock"
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise EvidenceError(f"Could not open evidence transaction lock {lock_path}: {exc}") from exc
    try:
        if lock_path.is_symlink():
            raise EvidenceError(f"Evidence transaction lock must not be a symbolic link: {lock_path}")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
    except (OSError, EvidenceError):
        os.close(descriptor)
        raise
    return descriptor


def release_evidence_lock(descriptor: int) -> None:
    try:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


@contextmanager
def evidence_transaction(evidence_root: Path):
    descriptor = acquire_evidence_lock(evidence_root)
    try:
        yield
    finally:
        release_evidence_lock(descriptor)


def prepare_log_path(target_dir: Path, filename: str) -> Path:
    log_dir = target_dir / "logs"
    if log_dir.is_symlink():
        raise EvidenceError(f"Log directory must not be a symbolic link: {log_dir}")
    if log_dir.exists() and not log_dir.is_dir():
        raise EvidenceError(f"Log path is not a directory: {log_dir}")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / filename
    if log_path.is_symlink():
        raise EvidenceError(f"Evidence log must not be a symbolic link: {log_path}")
    if log_path.exists() and not log_path.is_file():
        raise EvidenceError(f"Evidence log is not a regular file: {log_path}")
    return log_path


def expected_page_filename(page: int, extension: str) -> str:
    return f"page-{page:03d}.{extension}"


def manifest_identity(manifest: dict[str, Any]) -> SourceIdentity:
    return SourceIdentity(
        manifest["source_path"],
        manifest["source_sha256"],
        manifest["source_size_bytes"],
        manifest["page_count"],
    )


def require_exact_int(value: Any, field: str, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise EvidenceError(f"Evidence manifest field {field!r} must be an integer >= {minimum}.")
    return value


def load_manifest(out_dir: Path, kind: str) -> dict[str, Any] | None:
    manifest_path = out_dir / "manifest.json"
    artifacts: list[Path] = []
    if out_dir.exists():
        if out_dir.is_symlink():
            raise EvidenceError(f"Evidence directory must not be a symbolic link: {out_dir}")
        if not out_dir.is_dir():
            raise EvidenceError(f"Evidence path must be a directory: {out_dir}")
        for path in out_dir.iterdir():
            if path.name == "manifest.json":
                continue
            if path.is_symlink() or not path.is_file() or not path.name.startswith("page-"):
                raise EvidenceError(
                    f"Unexpected entry in managed evidence directory {out_dir}: {path.name}"
                )
            artifacts.append(path)
    if not manifest_path.exists():
        if artifacts:
            raise EvidenceError(
                f"Evidence files exist without a manifest in {out_dir}; regenerate the complete evidence set explicitly."
            )
        return None
    if manifest_path.is_symlink():
        raise EvidenceError(f"Evidence manifest must not be a symbolic link: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"Invalid evidence manifest {manifest_path}: {exc}") from exc
    if not isinstance(manifest, dict):
        raise EvidenceError(f"Evidence manifest must contain a JSON object: {manifest_path}")

    expected_kind = evidence_kind_name(kind)
    if type(manifest.get("schema_version")) is not int or manifest["schema_version"] != SCHEMA_VERSION:
        raise EvidenceError(f"Unsupported evidence manifest schema in {manifest_path}.")
    if manifest.get("evidence_kind") != expected_kind:
        raise EvidenceError(f"Evidence manifest kind does not match {out_dir}: {manifest_path}")
    source_path = manifest.get("source_path")
    source_sha = manifest.get("source_sha256")
    if not isinstance(source_path, str) or not source_path:
        raise EvidenceError(f"Evidence manifest has an invalid source_path: {manifest_path}")
    if not isinstance(source_sha, str) or SHA256_RE.fullmatch(source_sha) is None:
        raise EvidenceError(f"Evidence manifest has an invalid source_sha256: {manifest_path}")
    require_exact_int(manifest.get("source_size_bytes"), "source_size_bytes")
    page_count = require_exact_int(manifest.get("page_count"), "page_count")

    pages = manifest.get("pages")
    records = manifest.get("page_records")
    if not isinstance(pages, list) or not isinstance(records, dict):
        raise EvidenceError(f"Evidence manifest must contain pages and page_records: {manifest_path}")
    if any(isinstance(page, bool) or not isinstance(page, int) for page in pages):
        raise EvidenceError(f"Evidence manifest pages must be integers: {manifest_path}")
    if pages != sorted(set(pages)) or any(page <= 0 or page > page_count for page in pages):
        raise EvidenceError(f"Evidence manifest pages are not sorted, unique, and in range: {manifest_path}")
    if set(records) != {str(page) for page in pages}:
        raise EvidenceError(f"Evidence manifest pages do not match page_records: {manifest_path}")

    expected_artifacts: set[str] = set()
    for page in pages:
        record = records[str(page)]
        if not isinstance(record, dict):
            raise EvidenceError(f"Evidence manifest record for page {page} is invalid: {manifest_path}")
        if kind in {"source", "rebuilt"}:
            png_name = record.get("png")
            if png_name != expected_page_filename(page, "png"):
                raise EvidenceError(f"Evidence manifest PNG record for page {page} is invalid: {manifest_path}")
            require_exact_int(record.get("dpi"), f"page_records.{page}.dpi")
            if not isinstance(record.get("renderer"), str) or not record["renderer"]:
                raise EvidenceError(f"Evidence manifest renderer for page {page} is invalid: {manifest_path}")
            expected_artifacts.add(png_name)
            pdf_name = record.get("pdf")
            if pdf_name is not None:
                if pdf_name != expected_page_filename(page, "pdf"):
                    raise EvidenceError(f"Evidence manifest PDF record for page {page} is invalid: {manifest_path}")
                expected_artifacts.add(pdf_name)
        else:
            text_name = record.get("text")
            if text_name != expected_page_filename(page, "txt"):
                raise EvidenceError(f"Evidence manifest text record for page {page} is invalid: {manifest_path}")
            if record.get("extractor") != "pdftotext":
                raise EvidenceError(f"Evidence manifest extractor for page {page} is invalid: {manifest_path}")
            expected_artifacts.add(text_name)

    actual_artifacts: set[str] = set()
    for artifact in artifacts:
        if artifact.is_symlink():
            raise EvidenceError(f"Page evidence must not be a symbolic link: {artifact}")
        match = PAGE_FILE_RE.fullmatch(artifact.name)
        if match is None:
            raise EvidenceError(f"Non-canonical page evidence filename in {out_dir}: {artifact.name}")
        if artifact.stat().st_size <= 0:
            raise EvidenceError(f"Empty page evidence file in {out_dir}: {artifact.name}")
        actual_artifacts.add(artifact.name)
    if actual_artifacts != expected_artifacts:
        missing = sorted(expected_artifacts - actual_artifacts)
        extra = sorted(actual_artifacts - expected_artifacts)
        detail = []
        if missing:
            detail.append(f"missing: {', '.join(missing)}")
        if extra:
            detail.append(f"untracked: {', '.join(extra)}")
        raise EvidenceError(f"Evidence manifest does not match files in {out_dir} ({'; '.join(detail)}).")
    return manifest


def related_manifests(target_dir: Path, kind: str) -> list[tuple[Path, str, dict[str, Any]]]:
    specs = [(target_dir / "evidence" / "rebuilt-pages", "rebuilt")] if kind == "rebuilt" else [
        (target_dir / "evidence" / "source-pages", "source"),
        (target_dir / "evidence" / "text-layer", "text"),
    ]
    loaded: list[tuple[Path, str, dict[str, Any]]] = []
    for out_dir, manifest_kind in specs:
        manifest = load_manifest(out_dir, manifest_kind)
        if manifest is not None:
            loaded.append((out_dir, manifest_kind, manifest))
    return loaded


def identity_mismatches(
    identity: SourceIdentity,
    manifests: Sequence[tuple[Path, str, dict[str, Any]]],
    expected_mismatches: Sequence[str],
) -> list[str]:
    mismatches = list(expected_mismatches)
    for out_dir, _, manifest in manifests:
        bound = manifest_identity(manifest)
        if bound.content_key != identity.content_key:
            mismatches.append(
                f"{out_dir / 'manifest.json'} is bound to {bound.sha256}, current source is {identity.sha256}"
            )
    bound_keys = {manifest_identity(manifest).content_key for _, _, manifest in manifests}
    if len(bound_keys) > 1:
        mismatches.append("Existing source and text evidence manifests are bound to different PDF content.")
    return mismatches


def manifest_base(kind: str, identity: SourceIdentity, generated_at: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "evidence_kind": evidence_kind_name(kind),
        "source_path": identity.path,
        "source_sha256": identity.sha256,
        "source_size_bytes": identity.size_bytes,
        "page_count": identity.page_count,
        "pages": [],
        "page_records": {},
        "generated_at": generated_at,
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def verify_nonempty(path: Path, description: str) -> None:
    if path.is_symlink() or not path.is_file() or path.stat().st_size <= 0:
        raise EvidenceError(f"{description} was not created or is empty: {path}")


def normalize_staged_pngs(stage_out: Path, selected_pages: Sequence[int]) -> None:
    found: dict[int, Path] = {}
    for path in list(stage_out.glob("page-*.png")):
        match = PAGE_FILE_RE.fullmatch(path.name)
        if match is None or match.group(2) != "png":
            raise EvidenceError(f"Renderer created an unexpected PNG filename: {path.name}")
        page = int(match.group(1), 10)
        if page in found:
            raise EvidenceError(f"Renderer created duplicate PNG evidence for page {page}.")
        found[page] = path
    selected_set = set(selected_pages)
    if set(found) != selected_set:
        missing = sorted(selected_set - set(found))
        extra = sorted(set(found) - selected_set)
        parts = []
        if missing:
            parts.append(f"missing pages {missing}")
        if extra:
            parts.append(f"unexpected pages {extra}")
        raise EvidenceError(f"Renderer output did not match the selected pages: {'; '.join(parts)}")
    for page, path in found.items():
        destination = stage_out / expected_page_filename(page, "png")
        if path != destination:
            if destination.exists():
                raise EvidenceError(f"Renderer created colliding PNG names for page {page}.")
            os.replace(path, destination)
        verify_nonempty(destination, f"Rendered page {page}")


def render_to_stage(
    identity: SourceIdentity,
    pages: Sequence[int],
    dpi: int,
    single_page_pdf: bool,
    stage_out: Path,
    log_path: Path,
) -> str:
    pdftoppm = shutil.which("pdftoppm")
    mutool = shutil.which("mutool")
    if pdftoppm is None and mutool is None:
        raise EvidenceError("Missing renderer: install or provide pdftoppm or mutool.")
    renderer = "pdftoppm" if pdftoppm is not None else "mutool"
    ranges = contiguous_ranges(pages)
    stage_out.mkdir(parents=True, exist_ok=True)
    for start, end in ranges:
        if renderer == "pdftoppm":
            command = [
                str(pdftoppm),
                "-png",
                "-r",
                str(dpi),
                "-f",
                str(start),
                "-l",
                str(end),
                identity.path,
                str(stage_out / "page"),
            ]
        else:
            page_spec = str(start) if start == end else f"{start}-{end}"
            command = [
                str(mutool),
                "draw",
                "-o",
                str(stage_out / "page-%03d.png"),
                "-r",
                str(dpi),
                identity.path,
                page_spec,
            ]
        run_logged(command, log_path, f"{renderer} rendering pages {start}-{end}")
    normalize_staged_pngs(stage_out, pages)

    if single_page_pdf:
        pdfseparate = require_tool("pdfseparate")
        for start, end in ranges:
            command = [
                pdfseparate,
                "-f",
                str(start),
                "-l",
                str(end),
                identity.path,
                str(stage_out / "page-%03d.pdf"),
            ]
            run_logged(command, log_path, f"pdfseparate pages {start}-{end}")
        expected_pdfs = {expected_page_filename(page, "pdf") for page in pages}
        actual_pdfs = {path.name for path in stage_out.glob("page-*.pdf")}
        if actual_pdfs != expected_pdfs:
            raise EvidenceError("pdfseparate output did not match the selected pages.")
        for page in pages:
            verify_nonempty(stage_out / expected_page_filename(page, "pdf"), f"Single-page PDF {page}")
    return renderer


def extract_to_stage(
    identity: SourceIdentity,
    pages: Sequence[int],
    stage_out: Path,
    log_path: Path,
) -> None:
    pdftotext = require_tool("pdftotext")
    stage_out.mkdir(parents=True, exist_ok=True)
    for page in pages:
        output_path = stage_out / expected_page_filename(page, "txt")
        command = [
            pdftotext,
            "-f",
            str(page),
            "-l",
            str(page),
            "-layout",
            identity.path,
            str(output_path),
        ]
        run_logged(command, log_path, f"pdftotext extraction for page {page}")
        verify_nonempty(output_path, f"Text-layer page {page}")


def build_render_manifest(
    existing: dict[str, Any] | None,
    identity: SourceIdentity,
    pages: Sequence[int],
    dpi: int,
    renderer: str,
    single_page_pdf: bool,
    generated_at: str,
    kind: str,
    reset: bool,
) -> dict[str, Any]:
    manifest = manifest_base(kind, identity, generated_at) if existing is None or reset else copy.deepcopy(existing)
    manifest.update(
        source_path=identity.path,
        source_sha256=identity.sha256,
        source_size_bytes=identity.size_bytes,
        page_count=identity.page_count,
        generated_at=generated_at,
    )
    records = manifest.setdefault("page_records", {})
    for page in pages:
        previous = records.get(str(page), {})
        record: dict[str, Any] = {
            "png": expected_page_filename(page, "png"),
            "dpi": dpi,
            "renderer": renderer,
            "generated_at": generated_at,
        }
        if single_page_pdf:
            record["pdf"] = expected_page_filename(page, "pdf")
        elif isinstance(previous, dict) and previous.get("pdf") == expected_page_filename(page, "pdf"):
            record["pdf"] = previous["pdf"]
        records[str(page)] = record
    manifest["pages"] = sorted(int(page) for page in records)
    dpis = {record["dpi"] for record in records.values()}
    renderers = {record["renderer"] for record in records.values()}
    manifest["dpi"] = next(iter(dpis)) if len(dpis) == 1 else None
    manifest["renderer"] = next(iter(renderers)) if len(renderers) == 1 else "mixed"
    manifest["single_page_pdf_pages"] = sorted(
        int(page) for page, record in records.items() if record.get("pdf") is not None
    )
    return manifest


def build_text_manifest(
    existing: dict[str, Any] | None,
    identity: SourceIdentity,
    pages: Sequence[int],
    generated_at: str,
    reset: bool,
) -> dict[str, Any]:
    manifest = manifest_base("text", identity, generated_at) if existing is None or reset else copy.deepcopy(existing)
    manifest.update(
        source_path=identity.path,
        source_sha256=identity.sha256,
        source_size_bytes=identity.size_bytes,
        page_count=identity.page_count,
        generated_at=generated_at,
        extractor="pdftotext",
        layout=True,
    )
    records = manifest.setdefault("page_records", {})
    for page in pages:
        records[str(page)] = {
            "text": expected_page_filename(page, "txt"),
            "extractor": "pdftotext",
            "layout": True,
            "generated_at": generated_at,
        }
    manifest["pages"] = sorted(int(page) for page in records)
    return manifest


def ensure_no_conflicts(
    out_dir: Path,
    pages: Sequence[int],
    extensions: Sequence[str],
    force: bool,
    reset: bool,
) -> None:
    if force or reset:
        return
    conflicts = [
        out_dir / expected_page_filename(page, extension)
        for page in pages
        for extension in extensions
        if (out_dir / expected_page_filename(page, extension)).exists()
    ]
    if conflicts:
        raise EvidenceError(
            f"Evidence already exists for at least one selected page in {out_dir}; "
            "re-run with --force to replace selected evidence."
        )


def write_recovery_marker(stage_root: Path, recovery_errors: list[str]) -> None:
    marker = stage_root / "RECOVERY_REQUIRED.txt"
    try:
        marker.write_text("\n".join(recovery_errors) + "\n", encoding="utf-8")
    except OSError as exc:
        recovery_errors.append(f"write {marker}: {exc}")


def incremental_commit(
    stage_root: Path,
    stage_out: Path,
    staged_manifest: Path,
    staged_log: Path,
    out_dir: Path,
    log_path: Path,
    pages: Sequence[int],
    extensions: Sequence[str],
    extra_replacements: Sequence[tuple[Path, Path]] = (),
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    replacements: list[tuple[Path, Path]] = []
    for page in pages:
        for extension in extensions:
            source = stage_out / expected_page_filename(page, extension)
            if source.exists():
                replacements.append((source, out_dir / source.name))
    replacements.extend(extra_replacements)
    replacements.extend([(staged_log, log_path), (staged_manifest, out_dir / "manifest.json")])

    backup_dir = stage_root / "backup-files"
    backup_dir.mkdir()
    backups: list[tuple[Path, Path]] = []
    installed: list[Path] = []
    try:
        for index, (source, destination) in enumerate(replacements):
            if destination.exists() or destination.is_symlink():
                backup = backup_dir / f"{index:04d}-{destination.name}"
                os.replace(destination, backup)
                backups.append((backup, destination))
            os.replace(source, destination)
            installed.append(destination)
    except OSError as exc:
        recovery_errors: list[str] = []
        for destination in reversed(installed):
            try:
                if destination.is_dir():
                    shutil.rmtree(destination)
                else:
                    destination.unlink(missing_ok=True)
            except OSError as recovery_exc:
                recovery_errors.append(f"remove {destination}: {recovery_exc}")
        for backup, destination in reversed(backups):
            try:
                os.replace(backup, destination)
            except OSError as recovery_exc:
                recovery_errors.append(f"restore {destination}: {recovery_exc}")
        if recovery_errors:
            write_recovery_marker(stage_root, recovery_errors)
            raise RecoveryRequiredError(
                f"Evidence commit failed and automatic recovery was incomplete. "
                f"Backups were retained at {stage_root}: {'; '.join(recovery_errors)}"
            ) from exc
        raise EvidenceError(f"Could not commit evidence transaction: {exc}") from exc


def reset_commit(
    stage_root: Path,
    stage_out: Path,
    staged_manifest: Path,
    staged_log: Path,
    out_dir: Path,
    log_path: Path,
    related_dirs: Sequence[Path],
) -> None:
    os.replace(staged_manifest, stage_out / "manifest.json")
    backup_dirs = stage_root / "backup-dirs"
    backup_dirs.mkdir()
    moved_dirs: list[tuple[Path, Path]] = []
    new_dir_installed = False
    log_backup: Path | None = None
    log_installed = False
    try:
        for index, directory in enumerate(related_dirs):
            if directory.exists() or directory.is_symlink():
                backup = backup_dirs / f"{index:02d}-{directory.name}"
                os.replace(directory, backup)
                moved_dirs.append((backup, directory))
        out_dir.parent.mkdir(parents=True, exist_ok=True)
        os.replace(stage_out, out_dir)
        new_dir_installed = True

        log_path.parent.mkdir(parents=True, exist_ok=True)
        if log_path.exists() or log_path.is_symlink():
            log_backup = stage_root / "previous-operation.log"
            os.replace(log_path, log_backup)
        os.replace(staged_log, log_path)
        log_installed = True
    except OSError as exc:
        recovery_errors: list[str] = []
        if log_installed:
            try:
                log_path.unlink(missing_ok=True)
            except OSError as recovery_exc:
                recovery_errors.append(f"remove {log_path}: {recovery_exc}")
        if log_backup is not None and log_backup.exists():
            try:
                os.replace(log_backup, log_path)
            except OSError as recovery_exc:
                recovery_errors.append(f"restore {log_path}: {recovery_exc}")
        if new_dir_installed:
            try:
                shutil.rmtree(out_dir)
            except OSError as recovery_exc:
                recovery_errors.append(f"remove {out_dir}: {recovery_exc}")
        for backup, directory in reversed(moved_dirs):
            try:
                os.replace(backup, directory)
            except OSError as recovery_exc:
                recovery_errors.append(f"restore {directory}: {recovery_exc}")
        if recovery_errors:
            write_recovery_marker(stage_root, recovery_errors)
            raise RecoveryRequiredError(
                f"Source-change commit failed and automatic recovery was incomplete. "
                f"Backups were retained at {stage_root}: {'; '.join(recovery_errors)}"
            ) from exc
        raise EvidenceError(f"Could not commit source-change transaction: {exc}") from exc


def stable_identity_after_generation(identity: SourceIdentity, source_pdf: str, log_path: Path) -> None:
    current = source_identity(source_pdf, log_path)
    if current.content_key != identity.content_key or current.path != identity.path:
        raise EvidenceError("Source PDF changed while evidence was being generated; existing evidence was preserved.")


def stage_manifest_path_rebindings(
    stage_root: Path,
    manifests: Sequence[tuple[Path, str, dict[str, Any]]],
    identity: SourceIdentity,
    out_dir: Path,
) -> list[tuple[Path, Path]]:
    replacements: list[tuple[Path, Path]] = []
    for index, (directory, _, manifest) in enumerate(manifests):
        if directory == out_dir or manifest.get("source_path") == identity.path:
            continue
        updated = copy.deepcopy(manifest)
        updated["source_path"] = identity.path
        staged = stage_root / f"rebind-manifest-{index:02d}.json"
        write_json(staged, updated)
        replacements.append((staged, directory / "manifest.json"))
    return replacements


def run_render(args: argparse.Namespace) -> None:
    target_dir = Path(args.target_dir).expanduser().resolve()
    evidence_root = target_dir / "evidence"
    try:
        evidence_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise EvidenceError(f"Could not create evidence directory {evidence_root}: {exc}") from exc
    if evidence_root.is_symlink() or not evidence_root.is_dir():
        raise EvidenceError(f"Evidence root must be a real directory: {evidence_root}")
    kind = args.kind
    kind_name = evidence_kind_name(kind)
    out_dir = evidence_root / kind_name
    if out_dir.is_symlink():
        raise EvidenceError(f"Evidence directory must not be a symbolic link: {out_dir}")
    lock_descriptor = acquire_evidence_lock(evidence_root)
    try:
        stage_root = Path(tempfile.mkdtemp(prefix=f".{kind_name}-staging-", dir=evidence_root))
    except OSError:
        release_evidence_lock(lock_descriptor)
        raise
    stage_out = stage_root / "out"
    staged_log = stage_root / "operation.log"
    staged_manifest = stage_root / "manifest.json"
    preserve_stage = False
    try:
        log_path = prepare_log_path(target_dir, f"render-{kind_name}.log")
        identity = source_identity(args.source_pdf, staged_log)
        if is_within(Path(identity.path), evidence_root) or is_within(
            Path(identity.path), target_dir / "logs"
        ):
            raise EvidenceError(
                f"Input PDF must not be stored inside a managed evidence or log tree: {identity.path}"
            )
        pages = parse_pages(args, identity.page_count)
        manifests = related_manifests(target_dir, kind)
        expected_mismatches = validate_expected_identity(args, identity)
        if expected_mismatches:
            raise EvidenceError(
                "Current PDF does not match the explicitly asserted source identity.\n"
                + "\n".join(f"- {item}" for item in expected_mismatches)
            )
        mismatches = identity_mismatches(identity, manifests, [])
        accept_change = args.accept_source_change or (kind == "rebuilt" and args.force)
        if mismatches and not accept_change:
            raise EvidenceError(
                "Source PDF identity changed or does not match existing evidence. "
                "Use --accept-source-change to invalidate old evidence after reviewing the change.\n"
                + "\n".join(f"- {item}" for item in mismatches)
            )
        reset = bool(mismatches)
        existing = next((manifest for directory, _, manifest in manifests if directory == out_dir), None)
        extensions = ["png"] + (["pdf"] if args.single_page_pdf else [])
        ensure_no_conflicts(out_dir, pages, extensions, args.force, reset)
        renderer = render_to_stage(
            identity, pages, args.dpi, args.single_page_pdf, stage_out, staged_log
        )
        stable_identity_after_generation(identity, args.source_pdf, staged_log)
        generated_at = utc_now()
        manifest = build_render_manifest(
            existing,
            identity,
            pages,
            args.dpi,
            renderer,
            args.single_page_pdf,
            generated_at,
            kind,
            reset,
        )
        append_log(staged_log, f"Committed pages: {','.join(str(page) for page in pages)}")
        append_log(staged_log, f"Source SHA-256: {identity.sha256}")
        write_json(staged_manifest, manifest)
        path_rebindings = stage_manifest_path_rebindings(
            stage_root, manifests, identity, out_dir
        )
        if reset:
            related_dirs = [directory for directory, _, _ in manifests]
            if out_dir not in related_dirs:
                related_dirs.append(out_dir)
            reset_commit(
                stage_root,
                stage_out,
                staged_manifest,
                staged_log,
                out_dir,
                log_path,
                related_dirs,
            )
        else:
            incremental_commit(
                stage_root,
                stage_out,
                staged_manifest,
                staged_log,
                out_dir,
                log_path,
                pages,
                extensions,
                path_rebindings,
            )
        print(f"Rendered {kind} page evidence in {out_dir}")
    except RecoveryRequiredError:
        preserve_stage = True
        raise
    finally:
        if not preserve_stage:
            shutil.rmtree(stage_root, ignore_errors=True)
        release_evidence_lock(lock_descriptor)


def run_extract(args: argparse.Namespace) -> None:
    target_dir = Path(args.target_dir).expanduser().resolve()
    evidence_root = target_dir / "evidence"
    try:
        evidence_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise EvidenceError(f"Could not create evidence directory {evidence_root}: {exc}") from exc
    if evidence_root.is_symlink() or not evidence_root.is_dir():
        raise EvidenceError(f"Evidence root must be a real directory: {evidence_root}")
    out_dir = evidence_root / "text-layer"
    if out_dir.is_symlink():
        raise EvidenceError(f"Evidence directory must not be a symbolic link: {out_dir}")
    lock_descriptor = acquire_evidence_lock(evidence_root)
    try:
        stage_root = Path(tempfile.mkdtemp(prefix=".text-layer-staging-", dir=evidence_root))
    except OSError:
        release_evidence_lock(lock_descriptor)
        raise
    stage_out = stage_root / "out"
    staged_log = stage_root / "operation.log"
    staged_manifest = stage_root / "manifest.json"
    preserve_stage = False
    try:
        log_path = prepare_log_path(target_dir, "extract-text-pages.log")
        identity = source_identity(args.source_pdf, staged_log)
        if is_within(Path(identity.path), evidence_root) or is_within(
            Path(identity.path), target_dir / "logs"
        ):
            raise EvidenceError(
                f"Input PDF must not be stored inside a managed evidence or log tree: {identity.path}"
            )
        pages = parse_pages(args, identity.page_count)
        manifests = related_manifests(target_dir, "text")
        expected_mismatches = validate_expected_identity(args, identity)
        if expected_mismatches:
            raise EvidenceError(
                "Current PDF does not match the explicitly asserted source identity.\n"
                + "\n".join(f"- {item}" for item in expected_mismatches)
            )
        mismatches = identity_mismatches(identity, manifests, [])
        if mismatches and not args.accept_source_change:
            raise EvidenceError(
                "Source PDF identity changed or does not match existing evidence. "
                "Use --accept-source-change to invalidate old source evidence after reviewing the change.\n"
                + "\n".join(f"- {item}" for item in mismatches)
            )
        reset = bool(mismatches)
        existing = next((manifest for directory, _, manifest in manifests if directory == out_dir), None)
        ensure_no_conflicts(out_dir, pages, ["txt"], args.force, reset)
        extract_to_stage(identity, pages, stage_out, staged_log)
        stable_identity_after_generation(identity, args.source_pdf, staged_log)
        generated_at = utc_now()
        manifest = build_text_manifest(existing, identity, pages, generated_at, reset)
        append_log(staged_log, f"Committed pages: {','.join(str(page) for page in pages)}")
        append_log(staged_log, f"Source SHA-256: {identity.sha256}")
        write_json(staged_manifest, manifest)
        path_rebindings = stage_manifest_path_rebindings(
            stage_root, manifests, identity, out_dir
        )
        if reset:
            related_dirs = [directory for directory, _, _ in manifests]
            if out_dir not in related_dirs:
                related_dirs.append(out_dir)
            reset_commit(
                stage_root,
                stage_out,
                staged_manifest,
                staged_log,
                out_dir,
                log_path,
                related_dirs,
            )
        else:
            incremental_commit(
                stage_root,
                stage_out,
                staged_manifest,
                staged_log,
                out_dir,
                log_path,
                pages,
                ["txt"],
                path_rebindings,
            )
        print(f"Extracted text-layer evidence in {out_dir}")
    except RecoveryRequiredError:
        preserve_stage = True
        raise
    finally:
        if not preserve_stage:
            shutil.rmtree(stage_root, ignore_errors=True)
        release_evidence_lock(lock_descriptor)


def resolve_rebuilt_pdf(project_dir: Path, pdf_file: str) -> Path:
    if not project_dir.is_dir():
        raise EvidenceError(f"Project directory not found: {project_dir}")
    requested = Path(pdf_file).expanduser()
    pdf_path = requested if requested.is_absolute() else project_dir / requested
    if not pdf_path.is_file() and pdf_file == "main.pdf":
        candidates = sorted(path for path in project_dir.glob("*.pdf") if path.is_file())
        if len(candidates) == 1:
            pdf_path = candidates[0]
    if not pdf_path.is_file():
        raise EvidenceError(f"Compiled PDF not found: {pdf_path}")
    return pdf_path


def run_render_rebuilt(args: argparse.Namespace) -> None:
    project_dir = Path(args.project_dir).expanduser().resolve()
    pdf_path = resolve_rebuilt_pdf(project_dir, args.pdf_file)
    args.source_pdf = str(pdf_path)
    args.target_dir = str(project_dir)
    args.kind = "rebuilt"
    run_render(args)


def add_selection_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--pages", help="Comma-separated pages and ranges, such as 1,3,5-8.")
    parser.add_argument("--from", dest="from_page", type=positive_int, help="First page in a contiguous range.")
    parser.add_argument("--to", dest="to_page", type=positive_int, help="Last page in a contiguous range.")


def add_identity_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source-sha256", type=sha256_argument, help="Expected source PDF SHA-256.")
    parser.add_argument("--source-size", type=positive_int, help="Expected source PDF size in bytes.")
    parser.add_argument("--source-page-count", type=positive_int, help="Expected source PDF page count.")
    parser.add_argument(
        "--accept-source-change",
        action="store_true",
        help="Accept new PDF content and invalidate prior source/text evidence after generation succeeds.",
    )


def add_render_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--force", action="store_true", help="Replace selected evidence only after rendering succeeds.")
    parser.add_argument(
        "--single-page-pdf",
        action="store_true",
        help="Also retain a single-page PDF for every selected page.",
    )
    add_selection_arguments(parser)
    add_identity_arguments(parser)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    render = subparsers.add_parser("render", help="Render source or rebuilt PDF page evidence.")
    render.add_argument("source_pdf")
    render.add_argument("target_dir", nargs="?", default="latex")
    render.add_argument("dpi", nargs="?", default=180, type=positive_int)
    render.add_argument("--kind", "--evidence-kind", choices=("source", "rebuilt"), default="source")
    add_render_options(render)
    render.set_defaults(handler=run_render)

    extract = subparsers.add_parser("extract", help="Extract page-bounded digital text-layer evidence.")
    extract.add_argument("source_pdf")
    extract.add_argument("target_dir", nargs="?", default="latex")
    extract.add_argument("--force", action="store_true", help="Replace selected evidence only after extraction succeeds.")
    add_selection_arguments(extract)
    add_identity_arguments(extract)
    extract.set_defaults(handler=run_extract)

    rebuilt = subparsers.add_parser("render-rebuilt", help="Render a compiled project PDF.")
    rebuilt.add_argument("project_dir", nargs="?", default=".")
    rebuilt.add_argument("pdf_file", nargs="?", default="main.pdf")
    rebuilt.add_argument("dpi", nargs="?", default=140, type=positive_int)
    add_render_options(rebuilt)
    rebuilt.set_defaults(handler=run_render_rebuilt)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        require_python()
        args = build_parser().parse_args(argv)
        args.handler(args)
    except EvidenceError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
