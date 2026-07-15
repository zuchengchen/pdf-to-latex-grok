#!/usr/bin/env python3
"""Create or complete a contract-derived PDF-to-LaTeX project scaffold."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True

from pdf_evidence import (  # noqa: E402
    EvidenceError,
    SourceIdentity,
    evidence_transaction,
    load_manifest,
    manifest_identity,
    source_identity,
)
from workflow_contract import (  # noqa: E402
    DEFAULT_CONTRACT,
    EXPECTED_FIELDS,
    WorkflowError,
    active_lines,
    context_from_values,
    load_contract,
    validate_context_constraints,
    validate_final_checks,
)


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
TEMPLATE_DIR = SKILL_DIR / "assets" / "templates"
CONTRACT_TOOL = SCRIPT_DIR / "workflow_contract.py"
FIELD_RE = re.compile(r"^([A-Za-z][^:#]*?):[ \t]*(.*)$")
TEMPLATE_PLACEHOLDER_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
SOURCE_RECORD_FILES = (
    "conversion-state.md",
    "conversion-notes.md",
    "page-manifest.md",
    "object-inventory.md",
    "style-profile.md",
    "document-ir.md",
    "math-inventory.md",
    "glyph-map.md",
)
BATCH_MANIFEST_FILE = "batch-manifest.json"
PAGE_INDEX_FILE = "work/page-index.json"
BATCHED_OPERATIONS = {"convert", "resume", "refine"}
BATCHED_EXECUTION_MODES = {"resumable", "goal-backed"}


class ScaffoldError(RuntimeError):
    """A user-facing scaffold failure."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def context_arguments(args: argparse.Namespace) -> list[str]:
    return [
        "--operation",
        args.operation,
        "--source-kind",
        args.source_kind,
        "--traits",
        args.traits,
        "--delivery-level",
        args.delivery_level,
        "--execution-mode",
        args.execution_mode,
        "--verification-scope",
        args.verification_scope,
    ]


def contract_query(command: str, args: argparse.Namespace) -> str:
    completed = subprocess.run(
        [sys.executable, str(CONTRACT_TOOL), command, *context_arguments(args)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if completed.returncode != 0:
        raise ScaffoldError(completed.stdout.strip() or f"Contract query failed: {command}")
    return completed.stdout.rstrip()


def required_files(args: argparse.Namespace) -> list[str]:
    output = contract_query("required-files", args)
    return [line for line in output.splitlines() if line]


def required_gates(args: argparse.Namespace) -> str:
    return contract_query("render-gates", args)


def normalize_context(args: argparse.Namespace) -> None:
    try:
        values = json.loads(contract_query("normalize-context", args))
    except json.JSONDecodeError as exc:
        raise ScaffoldError(f"Contract returned invalid normalized context: {exc}") from exc
    args.operation = values["operation"]
    args.source_kind = values["source_kind"]
    args.traits = values["document_traits"]
    args.delivery_level = values["delivery_level"]
    args.execution_mode = values["execution_mode"]
    args.verification_scope = values["verification_scope"]


def read_metadata(path: Path) -> dict[str, str]:
    metadata: dict[str, str] = {}
    if path.is_symlink():
        raise ScaffoldError(f"Project metadata must not be a symbolic link: {path}")
    if not path.is_file():
        return metadata
    try:
        lines = active_lines(path)
    except WorkflowError as exc:
        raise ScaffoldError(str(exc)) from exc
    for line_number, line in lines:
        if line.startswith("## "):
            break
        match = FIELD_RE.match(line)
        if match:
            label = match.group(1).strip()
            if label in metadata:
                raise ScaffoldError(f"Duplicate project metadata field {label}: {path}:{line_number}")
            metadata[label] = match.group(2).strip()
    return metadata


def update_metadata_field(path: Path, label: str, value: str) -> bytes | None:
    metadata = read_metadata(path)
    if label not in metadata:
        raise ScaffoldError(f"Project record is missing {label} metadata: {path}")
    if metadata[label] == value:
        return None
    raw_lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    for line_number, line in active_lines(path):
        if line.startswith("## "):
            break
        match = FIELD_RE.match(line)
        if match and match.group(1).strip() == label:
            original = raw_lines[line_number - 1]
            line_content = original.rstrip("\r\n")
            ending = original[len(line_content) :]
            raw_lines[line_number - 1] = f"{label}: {value}{ending}"
            return "".join(raw_lines).encode("utf-8")
    raise ScaffoldError(f"Project record is missing active {label} metadata: {path}")


def validate_complete_state_metadata(path: Path, metadata: dict[str, str]) -> None:
    try:
        contract = load_contract(DEFAULT_CONTRACT)
    except WorkflowError as exc:
        raise ScaffoldError(str(exc)) from exc
    missing = [
        label
        for label in contract["state"]["required_metadata"]
        if not metadata.get(label) or "{{" in metadata[label] or "}}" in metadata[label]
    ]
    if missing:
        raise ScaffoldError(
            f"Existing project state is missing concrete schema-2 metadata in {path}: "
            + ", ".join(missing)
        )
    values = {
        name: metadata[contract["canonical_fields"][name]["markdown_label"]]
        for name in EXPECTED_FIELDS
    }
    try:
        context = context_from_values(values, contract)
    except WorkflowError as exc:
        raise ScaffoldError(f"Invalid existing project state {path}: {exc}") from exc
    errors = validate_context_constraints(context, contract)
    errors.extend(
        validate_final_checks(
            context,
            metadata["Compile check"],
            metadata["Visual review"],
            metadata["Source fidelity"],
            metadata["Next action"],
            metadata.get("Previous delivery level", ""),
            metadata.get("Downgrade approval", ""),
            contract,
        )
    )
    if errors:
        raise ScaffoldError(
            f"Existing project state metadata is invalid in {path}: " + "; ".join(errors)
        )


def default_file_mode() -> int:
    current_umask = os.umask(0)
    os.umask(current_umask)
    return 0o666 & ~current_umask


def prepare_file_update(path: Path, content: bytes, mode: int) -> Path:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "wb", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            temporary = Path(handle.name)
            os.fchmod(handle.fileno(), mode)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise
    assert temporary is not None
    return temporary


def commit_file_updates(target: Path, updates: dict[Path, bytes]) -> None:
    if not updates:
        return
    backup_root = Path(tempfile.mkdtemp(prefix=".scaffold-rebind-", dir=target))
    prepared: list[tuple[Path, Path, Path]] = []
    installed: list[tuple[Path, Path]] = []
    preserve_backup = False
    try:
        for index, (path, content) in enumerate(updates.items()):
            if path.is_symlink() or not path.is_file():
                raise ScaffoldError(f"Project provenance file must be regular: {path}")
            mode = stat.S_IMODE(path.stat(follow_symlinks=False).st_mode)
            temporary = prepare_file_update(path, content, mode)
            prepared.append((path, temporary, backup_root / f"{index:02d}-{path.name}"))
        for path, temporary, backup in prepared:
            os.replace(path, backup)
            try:
                os.replace(temporary, path)
            except OSError as install_exc:
                try:
                    os.replace(backup, path)
                except OSError as restore_exc:
                    preserve_backup = True
                    raise ScaffoldError(
                        "Could not install updated project provenance or restore the original; "
                        f"backups were retained at {backup_root}: {path}: {restore_exc}"
                    ) from install_exc
                raise
            installed.append((path, backup))
    except (OSError, ScaffoldError) as exc:
        recovery_errors: list[str] = []
        for path, backup in reversed(installed):
            try:
                path.unlink(missing_ok=True)
                os.replace(backup, path)
            except OSError as recovery_exc:
                recovery_errors.append(f"{path}: {recovery_exc}")
        if recovery_errors:
            preserve_backup = True
            raise ScaffoldError(
                "Could not roll back project provenance; backups were retained at "
                f"{backup_root}: {'; '.join(recovery_errors)}"
            ) from exc
        if isinstance(exc, ScaffoldError):
            raise
        raise ScaffoldError(f"Could not update project provenance transactionally: {exc}") from exc
    finally:
        for _, temporary, _ in prepared:
            temporary.unlink(missing_ok=True)
        if not preserve_backup:
            for _, backup in installed:
                backup.unlink(missing_ok=True)
            try:
                backup_root.rmdir()
            except OSError:
                pass


def evidence_manifest_updates(
    target: Path, identity: SourceIdentity
) -> list[tuple[Path, dict[str, object]]]:
    updates: list[tuple[Path, dict[str, object]]] = []
    for relative, kind in (
        ("evidence/source-pages", "source"),
        ("evidence/text-layer", "text"),
    ):
        out_dir = target / relative
        manifest = load_manifest(out_dir, kind)
        if manifest is None:
            continue
        bound = manifest_identity(manifest)
        if bound.content_key != identity.content_key:
            raise ScaffoldError(
                f"Evidence manifest does not match the source identity: {out_dir / 'manifest.json'}"
            )
        if manifest.get("source_path") != identity.path:
            updated = dict(manifest)
            updated["source_path"] = identity.path
            updates.append((out_dir / "manifest.json", updated))
    return updates


def page_size(source_pdf: Path) -> str:
    environment = os.environ.copy()
    environment["LC_ALL"] = "C"
    completed = subprocess.run(
        ["pdfinfo", str(source_pdf)],
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
        env=environment,
    )
    if completed.returncode == 0:
        match = re.search(r"^Page size:\s*(.+)$", completed.stdout, re.MULTILINE)
        if match:
            return match.group(1).strip()
    return "unknown"


def template_values(
    args: argparse.Namespace,
    *,
    target: Path,
    identity: SourceIdentity,
    source_page_size: str,
) -> dict[str, str]:
    values = {
        "SOURCE_PDF": identity.path,
        "SOURCE_SHA256": identity.sha256,
        "SOURCE_SIZE_BYTES": str(identity.size_bytes),
        "SOURCE_PAGE_COUNT": str(identity.page_count),
        "TARGET_DIR": str(target),
        "DATE_UTC": utc_now(),
        "OPERATION": args.operation,
        "SOURCE_KIND": args.source_kind,
        "DOCUMENT_TRAITS": args.traits,
        "DELIVERY_LEVEL": args.delivery_level,
        "EXECUTION_MODE": args.execution_mode,
        "VERIFICATION_SCOPE": args.verification_scope,
        "SOURCE_PAGE_SIZE": source_page_size,
        "REQUIRED_GATES": required_gates(args),
    }
    for name, value in values.items():
        if name != "REQUIRED_GATES":
            validate_template_scalar(name, value)
    for name, value in list(values.items()):
        if name != "REQUIRED_GATES":
            values[f"{name}_JSON"] = json.dumps(value, ensure_ascii=True)
    return values


def validate_template_scalar(name: str, value: str) -> None:
    if value != value.strip():
        raise ScaffoldError(f"Template value {name} must not have leading or trailing whitespace.")
    if value.splitlines() != [value] or any(
        token in value for token in ("{{", "}}", "<!--", "-->")
    ):
        raise ScaffoldError(
            f"Template value {name} cannot be represented safely in project Markdown metadata."
        )


def render_template(template: Path, values: dict[str, str]) -> str:
    text = template.read_text(encoding="utf-8")
    placeholders = set(TEMPLATE_PLACEHOLDER_RE.findall(text))
    unresolved = sorted(placeholders - set(values))
    if unresolved:
        raise ScaffoldError(
            f"Template {template.name} contains unresolved placeholders: "
            + ", ".join(f"{{{{{name}}}}}" for name in unresolved)
        )
    return TEMPLATE_PLACEHOLDER_RE.sub(lambda match: values[match.group(1)], text)


def target_has_entries(target: Path) -> bool:
    return target.is_dir() and any(target.iterdir())


def validate_existing_state(
    target: Path, args: argparse.Namespace, identity: SourceIdentity
) -> bool:
    state = target / "conversion-state.md"
    if not state.is_file():
        return False
    metadata = read_metadata(state)
    validate_complete_state_metadata(state, metadata)
    expected = {
        "State schema": "2",
        "Skill version": "1.0.0",
        "Contract version": "1",
        "Source PDF SHA-256": identity.sha256,
        "Source PDF size bytes": str(identity.size_bytes),
        "Source PDF page count": str(identity.page_count),
        "Operation": args.operation,
        "Source kind": args.source_kind,
        "Document traits": args.traits,
        "Delivery level": args.delivery_level,
        "Execution mode": args.execution_mode,
        "Verification scope": args.verification_scope,
    }
    mismatches = [
        f"{label}: expected {value!r}, found {metadata.get(label, '<missing>')!r}"
        for label, value in expected.items()
        if (
            metadata.get(label, "").lower() != value.lower()
            if label == "Source PDF SHA-256"
            else metadata.get(label) != value
        )
    ]
    if mismatches:
        raise ScaffoldError(
            "Existing project state does not match the requested scaffold context:\n"
            + "\n".join(f"- {item}" for item in mismatches)
        )
    return True


def support_files(args: argparse.Namespace) -> list[str]:
    if (
        args.operation in BATCHED_OPERATIONS
        and args.execution_mode in BATCHED_EXECUTION_MODES
        and args.verification_scope == "source-aware"
    ):
        return [BATCH_MANIFEST_FILE]
    return []


def project_files(args: argparse.Namespace) -> list[str]:
    files = required_files(args)
    for relative in support_files(args):
        if relative not in files:
            files.append(relative)
    return files


def update_batch_manifest_source(path: Path, identity: SourceIdentity) -> bytes | None:
    if path.is_symlink():
        raise ScaffoldError(f"Project batch manifest must not be a symbolic link: {path}")
    if not path.is_file():
        return None
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScaffoldError(f"Could not read batch manifest {path}: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ScaffoldError(f"Batch manifest has unsupported schema: {path}")
    source = manifest.get("source")
    if not isinstance(source, dict):
        raise ScaffoldError(f"Batch manifest is missing source identity: {path}")
    recorded = (
        source.get("sha256"),
        source.get("size_bytes"),
        source.get("page_count"),
    )
    expected = (identity.sha256, identity.size_bytes, identity.page_count)
    if recorded != expected:
        raise ScaffoldError(f"Batch manifest source identity does not match the project source: {path}")
    if source.get("path") == identity.path:
        return None
    source["path"] = identity.path
    return (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")


def update_page_index_source(path: Path, identity: SourceIdentity) -> bytes | None:
    if path.is_symlink():
        raise ScaffoldError(f"Project page index must not be a symbolic link: {path}")
    if not path.is_file():
        return None
    try:
        index = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScaffoldError(f"Could not read page index {path}: {exc}") from exc
    if not isinstance(index, dict) or index.get("schema_version") != 1:
        raise ScaffoldError(f"Page index has unsupported schema: {path}")
    if index.get("kind") != "page-complexity-index":
        raise ScaffoldError(f"Page index has unsupported kind: {path}")
    source = index.get("source")
    if not isinstance(source, dict):
        raise ScaffoldError(f"Page index is missing source identity: {path}")
    recorded = (source.get("sha256"), source.get("size_bytes"), source.get("page_count"))
    expected = (identity.sha256, identity.size_bytes, identity.page_count)
    if recorded != expected:
        raise ScaffoldError(f"Page index source identity does not match the project source: {path}")
    if source.get("path") == identity.path:
        return None
    source["path"] = identity.path
    return (json.dumps(index, indent=2, sort_keys=True) + "\n").encode("utf-8")


def rebind_source_path(target: Path, identity: SourceIdentity) -> None:
    evidence_root = target / "evidence"

    def collect_updates() -> dict[Path, bytes]:
        updates: dict[Path, bytes] = {}
        for relative in SOURCE_RECORD_FILES:
            path = target / relative
            if path.is_symlink():
                raise ScaffoldError(f"Project record must not be a symbolic link: {path}")
            if path.exists() and not path.is_file():
                raise ScaffoldError(f"Project record must be a regular file: {path}")
            if not path.is_file():
                continue
            updated = update_metadata_field(path, "Source PDF", identity.path)
            if updated is not None:
                updates[path] = updated
        batch_manifest = target / BATCH_MANIFEST_FILE
        if batch_manifest.exists() or batch_manifest.is_symlink():
            updated = update_batch_manifest_source(batch_manifest, identity)
            if updated is not None:
                updates[batch_manifest] = updated
        page_index = target / PAGE_INDEX_FILE
        if page_index.exists() or page_index.is_symlink():
            updated = update_page_index_source(page_index, identity)
            if updated is not None:
                updates[page_index] = updated
        for path, manifest in evidence_manifest_updates(target, identity):
            updates[path] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(
                "utf-8"
            )
        return updates

    if evidence_root.is_symlink():
        raise ScaffoldError(f"Project evidence directory must not be a symbolic link: {evidence_root}")
    if evidence_root.exists() and not evidence_root.is_dir():
        raise ScaffoldError(f"Project evidence path must be a directory: {evidence_root}")
    if evidence_root.is_dir():
        with evidence_transaction(evidence_root):
            commit_file_updates(target, collect_updates())
    else:
        commit_file_updates(target, collect_updates())


def validate_existing_context(target: Path, args: argparse.Namespace) -> dict[str, str]:
    state = target / "conversion-state.md"
    if not state.exists() and not state.is_symlink():
        return {}
    metadata = read_metadata(state)
    validate_complete_state_metadata(state, metadata)
    expected = {
        "State schema": "2",
        "Skill version": "1.0.0",
        "Contract version": "1",
        "Operation": args.operation,
        "Source kind": args.source_kind,
        "Document traits": args.traits,
        "Delivery level": args.delivery_level,
        "Execution mode": args.execution_mode,
        "Verification scope": args.verification_scope,
    }
    mismatches = [
        f"{label}: expected {value!r}, found {metadata.get(label, '<missing>')!r}"
        for label, value in expected.items()
        if metadata.get(label) != value
    ]
    if mismatches:
        raise ScaffoldError(
            "Existing project state does not match the requested ensure context:\n"
            + "\n".join(f"- {item}" for item in mismatches)
        )
    for label in (
        "Source PDF",
        "Source PDF SHA-256",
        "Source PDF size bytes",
        "Source PDF page count",
    ):
        if label not in metadata or not metadata[label]:
            raise ScaffoldError(f"Existing project state is missing required field: {label}")
    return metadata


def planned_directories(target: Path, files: list[str], traits: set[str]) -> set[Path]:
    directories = {target / "logs"}
    directories.update(
        target / Path(relative).parent
        for relative in files
        if Path(relative).parent != Path(".")
    )
    if any(name in files for name in ("page-manifest.md", "object-inventory.md", "document-ir.md")):
        directories.update(
            {
                target / "chapters",
                target / "transcripts",
                target / "evidence" / "source-pages",
                target / "evidence" / "rebuilt-pages",
                target / "evidence" / "text-layer",
                target / "evidence" / "crops",
            }
        )
    if "object-inventory.md" in files:
        directories.update({target / "figures", target / "tables"})
    if "book" in traits:
        directories.update({target / "frontmatter", target / "chapters", target / "backmatter"})
    if BATCH_MANIFEST_FILE in files:
        directories.update(
            {
                target / "work" / "shards",
                target / "work" / "merged",
                target / "work" / "review-findings",
            }
        )
    expanded: set[Path] = set()
    for directory in directories:
        current = directory
        while current != target:
            expanded.add(current)
            current = current.parent
    return expanded


def validate_managed_paths(target: Path, files: list[str], directories: set[Path]) -> None:
    for directory in sorted(directories):
        current = target
        for part in directory.relative_to(target).parts:
            current /= part
            if current.is_symlink():
                raise ScaffoldError(f"Project directory must not be a symbolic link: {current}")
            if current.exists() and not current.is_dir():
                raise ScaffoldError(f"Project directory path is not a directory: {current}")
    for relative in files:
        destination = target / relative
        current = target
        for part in Path(relative).parts[:-1]:
            current /= part
            if current.is_symlink():
                raise ScaffoldError(f"Required file parent must not be a symbolic link: {current}")
            if current.exists() and not current.is_dir():
                raise ScaffoldError(f"Required file parent is not a directory: {current}")
        if destination.is_symlink():
            raise ScaffoldError(f"Required project file must not be a symbolic link: {destination}")
        if destination.exists() and not destination.is_file():
            raise ScaffoldError(f"Required project file is not a regular file: {destination}")


def create_directories(directories: set[Path]) -> None:
    for directory in sorted(directories, key=lambda path: (len(path.parts), str(path))):
        directory.mkdir(parents=True, exist_ok=True)


def write_required_files(
    target: Path, files: list[str], values: dict[str, str]
) -> list[Path]:
    created: list[Path] = []
    try:
        for relative in files:
            destination = target / relative
            if destination.is_file():
                continue
            template = TEMPLATE_DIR / relative
            if not template.is_file():
                raise ScaffoldError(f"Bundled template not found for required file: {relative}")
            rendered = render_template(template, values).encode("utf-8")
            temporary: Path | None = None
            try:
                temporary = prepare_file_update(destination, rendered, default_file_mode())
                os.replace(temporary, destination)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            created.append(destination)
    except (OSError, ScaffoldError):
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise
    return created


def confirm_source_identity(source_pdf: str, expected: SourceIdentity) -> None:
    with tempfile.TemporaryDirectory(prefix="pdf-to-latex-identity-confirm-") as temp_dir:
        current = source_identity(source_pdf, Path(temp_dir) / "source-identity.log")
    if current.path != expected.path or current.content_key != expected.content_key:
        raise ScaffoldError("Source PDF changed while the project scaffold was being created.")


def remove_created_paths(created: list[Path], created_directories: list[Path]) -> None:
    for path in reversed(created):
        path.unlink(missing_ok=True)
    for directory in sorted(created_directories, key=lambda path: len(path.parts), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass


def init_project(args: argparse.Namespace) -> int:
    if args.operation == "review":
        raise ScaffoldError("Review is stateless and must use a temporary copy, not a project scaffold.")
    if args.operation != "convert":
        raise ScaffoldError("A new scaffold uses operation convert; use ensure for an existing project.")
    if args.verification_scope != "source-aware":
        raise ScaffoldError("A new conversion requires verification scope source-aware.")

    target = Path(args.target_dir).expanduser().resolve(strict=False)
    if target.exists() and not target.is_dir():
        raise ScaffoldError(f"Target path exists but is not a directory: {target}")

    with tempfile.TemporaryDirectory(prefix="pdf-to-latex-identity-") as temp_dir:
        identity = source_identity(args.source_pdf, Path(temp_dir) / "source-identity.log")

    existing_state = validate_existing_state(target, args, identity) if target.exists() else False
    if target_has_entries(target) and not existing_state:
        raise ScaffoldError(
            f"Target directory is non-empty and has no matching schema-2 project state: {target}"
        )

    files = project_files(args)
    target_created = not target.exists()
    target.mkdir(parents=True, exist_ok=True)
    created: list[Path] = []
    created_directories: list[Path] = []
    try:
        traits = set(args.traits.split(",")) if args.traits != "none" else set()
        directories = planned_directories(target, files, traits)
        validate_managed_paths(target, files, directories)
        created_directories = [directory for directory in directories if not directory.exists()]
        create_directories(directories)
        values = template_values(
            args,
            target=target,
            identity=identity,
            source_page_size=page_size(Path(identity.path)),
        )
        created = write_required_files(target, files, values)
        confirm_source_identity(args.source_pdf, identity)
        if existing_state and read_metadata(target / "conversion-state.md").get("Source PDF") != identity.path:
            rebind_source_path(target, identity)
    except (EvidenceError, OSError, ScaffoldError):
        remove_created_paths(created, created_directories)
        if target_created:
            try:
                target.rmdir()
            except OSError:
                pass
        raise
    print(f"Initialized contract-derived LaTeX project in {target}")
    for path in created:
        print(f"Created {path.relative_to(target)}")
    return 0


def ensure_project(args: argparse.Namespace) -> int:
    target = Path(args.target_dir).expanduser().resolve(strict=True)
    if not target.is_dir():
        raise ScaffoldError(f"Project directory not found: {target}")
    if args.operation == "review":
        raise ScaffoldError("Review is stateless and does not add project files.")

    state_metadata = validate_existing_context(target, args)
    recorded_source_path = state_metadata.get("Source PDF") or "unavailable"
    source_path = recorded_source_path
    if args.verification_scope == "source-aware":
        recorded_source = Path(source_path).expanduser()
        if not recorded_source.is_absolute():
            recorded_source = target / recorded_source
        source_path = str(recorded_source.resolve(strict=False))
    raw_size = state_metadata.get("Source PDF size bytes", "0") or "0"
    raw_pages = state_metadata.get("Source PDF page count", "0") or "0"
    identity = SourceIdentity(
        source_path,
        (state_metadata.get("Source PDF SHA-256") or "unavailable").lower(),
        int(raw_size),
        int(raw_pages),
    )
    if args.verification_scope == "source-aware" and (
        identity.size_bytes <= 0 or identity.page_count <= 0
    ):
        raise ScaffoldError("Existing state is missing a valid source size or page count.")
    rebind_needed = (
        args.verification_scope == "source-aware" and source_path != recorded_source_path
    )
    if args.source_pdf:
        if args.verification_scope != "source-aware":
            raise ScaffoldError("--source-pdf is only valid for a source-aware ensure operation.")
        with tempfile.TemporaryDirectory(prefix="pdf-to-latex-ensure-rebind-") as temp_dir:
            current = source_identity(
                args.source_pdf, Path(temp_dir) / "source-identity.log"
            )
        if current.content_key != identity.content_key:
            raise ScaffoldError("Replacement Source PDF does not match the recorded source identity.")
        rebind_needed = rebind_needed or current.path != identity.path
        identity = current
    elif args.verification_scope == "source-aware":
        with tempfile.TemporaryDirectory(prefix="pdf-to-latex-ensure-identity-") as temp_dir:
            current = source_identity(
                identity.path, Path(temp_dir) / "source-identity.log"
            )
        if current.content_key != identity.content_key:
            raise ScaffoldError("Existing state source identity does not match the current PDF.")

    files = project_files(args)
    created: list[Path] = []
    created_directories: list[Path] = []
    try:
        traits = set(args.traits.split(",")) if args.traits != "none" else set()
        directories = planned_directories(target, files, traits)
        validate_managed_paths(target, files, directories)
        created_directories = [directory for directory in directories if not directory.exists()]
        create_directories(directories)
        values = template_values(
            args,
            target=target,
            identity=identity,
            source_page_size="unknown",
        )
        created = write_required_files(target, files, values)
        if args.verification_scope == "source-aware":
            confirm_source_identity(identity.path, identity)
        if rebind_needed:
            rebind_source_path(target, identity)
    except (EvidenceError, OSError, ScaffoldError):
        remove_created_paths(created, created_directories)
        raise
    print(f"Contract-required project files are present in {target}")
    for path in created:
        print(f"Created {path.relative_to(target)}")
    return 0


def add_context_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--operation", required=True)
    parser.add_argument("--source-kind", required=True)
    parser.add_argument("--traits", required=True, help="Comma-separated traits or 'none'.")
    parser.add_argument("--delivery-level", required=True)
    parser.add_argument("--execution-mode", required=True)
    parser.add_argument("--verification-scope", required=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Create a new conversion project.")
    init.add_argument("source_pdf")
    init.add_argument("target_dir", nargs="?", default="latex")
    add_context_arguments(init)

    ensure = subparsers.add_parser("ensure", help="Add missing contract-derived project files.")
    ensure.add_argument("target_dir")
    ensure.add_argument(
        "--source-pdf",
        help="Rebind a moved source-aware PDF only when its recorded content identity matches.",
    )
    add_context_arguments(ensure)
    return parser


def main() -> int:
    if sys.version_info < (3, 10):
        print("Python 3.10 or newer is required.", file=sys.stderr)
        return 1
    parser = build_parser()
    args = parser.parse_args()
    try:
        normalize_context(args)
        if args.command == "init":
            return init_project(args)
        return ensure_project(args)
    except (EvidenceError, ScaffoldError, FileNotFoundError, ValueError) as exc:
        print(f"Scaffold error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
