#!/usr/bin/env python3
"""Safe XeLaTeX health checks and publication gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import selectors
import signal
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


MIN_PYTHON = (3, 10)
DEFAULT_BUILD_TIMEOUT = 300
MAX_COMPILE_LOG_BYTES = 10 * 1024 * 1024
AUXILIARY_SUFFIXES = {
    ".aux",
    ".bbl",
    ".bcf",
    ".blg",
    ".fdb_latexmk",
    ".fls",
    ".glg",
    ".glo",
    ".gls",
    ".idx",
    ".ilg",
    ".ind",
    ".lof",
    ".log",
    ".lot",
    ".out",
    ".run.xml",
    ".synctex.gz",
    ".toc",
    ".xdv",
    ".dvi",
    ".ps",
}
AUXILIARY_LOG_SUFFIXES = {".blg", ".ilg", ".glg"}
UNSAFE_ENVIRONMENT_VARIABLES = {
    "BASHOPTS",
    "GCONV_PATH",
    "LD_AUDIT",
    "LD_DEBUG",
    "LD_LIBRARY_PATH",
    "LD_PRELOAD",
    "LOCPATH",
    "NLSPATH",
    "PERL5DB",
    "PERL5OPT",
    "PERL_LOCAL_LIB_ROOT",
    "PERL_MB_OPT",
    "PERL_MM_OPT",
    "PYTHONINSPECT",
    "PYTHONSTARTUP",
    "RUBYOPT",
    "SHELLOPTS",
    "ZDOTDIR",
}
UNSAFE_ENVIRONMENT_PREFIXES = ("BASH_FUNC_", "DYLD_", "LD_")

ERROR_PATTERNS = (
    ("missing-character", re.compile(r"Missing character: There is no ")),
    ("undefined-control-sequence", re.compile(r"Undefined control sequence")),
    ("undefined-citation", re.compile(r"Citation .* undefined", re.IGNORECASE)),
    ("undefined-reference", re.compile(r"Reference .* undefined", re.IGNORECASE)),
    ("undefined-reference", re.compile(r"There were undefined references")),
    ("rerun-required", re.compile(r"Rerun to get cross-references right")),
    ("package-error", re.compile(r"Package .* Error")),
    ("fontspec-error", re.compile(r"fontspec.*Error", re.IGNORECASE)),
    ("missing-file", re.compile(r"File .* not found")),
    ("fatal-error", re.compile(r"Fatal error|Emergency stop|No pages of output")),
)

WARNING_PATTERNS = (
    ("font-warning", re.compile(r"LaTeX Font Warning")),
    ("overfull-hbox", re.compile(r"Overfull \\hbox")),
    ("overfull-vbox", re.compile(r"Overfull \\vbox")),
    ("underfull-box", re.compile(r"Underfull \\[hv]box")),
)

RERUN_PATTERNS = (
    re.compile(r"Rerun to get cross-references right"),
    re.compile(r"Label\(s\) may have changed"),
    re.compile(r"Please \(re\)run Biber"),
)

SOURCE_SUFFIXES = {
    ".bbx",
    ".bib",
    ".cbx",
    ".cfg",
    ".clo",
    ".cls",
    ".def",
    ".dtx",
    ".fd",
    ".inc",
    ".lbx",
    ".ldf",
    ".ltx",
    ".pgf",
    ".sty",
    ".tex",
    ".tikz",
}
RESERVED_OUTPUT_DIRS = {"logs", "evidence", "transcripts"}
DECLARED_BUILD_TOOLS = (
    "latexmk",
    "xelatex",
    "kpsewhich",
    "xdvipdfmx",
    "bibtex",
    "biber",
    "makeindex",
    "makeglossaries",
    "xindy",
    "perl",
    "pdfinfo",
    "pdftotext",
    "pdftoppm",
    "mutool",
    "pdfseparate",
)
SAFE_EXECUTABLE_ROOTS = (
    Path("/bin"),
    Path("/sbin"),
    Path("/usr/bin"),
    Path("/usr/sbin"),
    Path("/usr/local/bin"),
    Path("/usr/local/sbin"),
    Path("/usr/local/texlive"),
    Path("/Library/TeX"),
    Path("/opt/texlive"),
    Path("/opt/homebrew/bin"),
    Path("/opt/homebrew/sbin"),
    Path("/nix/store"),
    Path("/nix/var/nix/profiles/default/bin"),
    Path("/run/current-system/sw/bin"),
)
REFERENCE_PATTERN = re.compile(
    r"\\(?P<command>input|include|includegraphics|addbibresource|bibliography|bibliographystyle)"
    r"(?:\s*\[[^\]]*\])?\s*\{(?P<value>[^{}]+)\}"
)
SHELL_ESCAPE_PATTERN = re.compile(
    r"\\(?:immediate\s*)?write18\b|\\input\s*\|", re.IGNORECASE
)
COMPLEX_BUILD_PATTERN = re.compile(
    r"\\(?:addbibresource|bibliography|makeindex|makeglossaries)\b"
)
ARTIFACT_PATTERN = re.compile(
    r"\\pdfglyph\s*\{|extracteddisplay|TODO[\s_-]*math|"
    r"unresolved[\s_-]+glyph|MATH_PLACEHOLDER|"
    r"raw[\s_-]+glyph\s*:|math[\s_-]*placeholder|"
    r"Replace this scaffold with semantic content",
    re.IGNORECASE,
)
AUXILIARY_INPUT_PATTERNS = (
    re.compile(r"^(?:The style file|Database file #[0-9]+):\s*(.+?)\s*$"),
    re.compile(r"Found .*?(?:data source|control file) ['\"]([^'\"]+)['\"]"),
    re.compile(r"Scanning (?:input|style) file\s+(.+?)\.\.\."),
)


@dataclass(frozen=True)
class Finding:
    severity: str
    category: str
    message: str
    source: str


@dataclass
class BuildResult:
    ok: bool
    pdf_path: Path | None
    findings: list[Finding]
    compile_log: Path
    tex_log: Path
    fls_file: Path
    error: str = ""
    dependencies: dict[str, list[str]] | None = None


class PipelineError(RuntimeError):
    """A deterministic build-pipeline safety or execution failure."""


def require_python() -> None:
    if sys.version_info < MIN_PYTHON:
        version = ".".join(str(value) for value in MIN_PYTHON)
        raise SystemExit(f"Python {version}+ is required.")


def run_command(
    command: list[str], cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def ensure_log_directory(project: Path) -> Path:
    log_dir = project / "logs"
    if log_dir.is_symlink():
        raise PipelineError(f"Log directory must not be a symbolic link: {log_dir}")
    if log_dir.exists() and not log_dir.is_dir():
        raise PipelineError(f"Log path is not a directory: {log_dir}")
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def validate_output_path(path: Path) -> None:
    if path.is_symlink():
        raise PipelineError(f"Build output must not be a symbolic link: {path}")
    if path.exists():
        if not path.is_file():
            raise PipelineError(f"Build output is not a regular file: {path}")
        if path.stat().st_nlink > 1:
            raise PipelineError(f"Build output must not be a hard link: {path}")


def atomic_write_text(path: Path, text: str) -> None:
    validate_output_path(path)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            temporary = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def atomic_copy_file(source: Path, destination: Path) -> None:
    validate_output_path(destination)
    temporary: Path | None = None
    try:
        with source.open("rb") as source_handle, tempfile.NamedTemporaryFile(
            "wb", dir=destination.parent, prefix=f".{destination.name}.", delete=False
        ) as destination_handle:
            temporary = Path(destination_handle.name)
            os.fchmod(destination_handle.fileno(), source.stat().st_mode & 0o777)
            shutil.copyfileobj(source_handle, destination_handle)
            destination_handle.flush()
            os.fsync(destination_handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def normalized_recorder_text(fls_file: Path, build_project: Path, project: Path) -> str:
    normalized: list[str] = []
    for line in fls_file.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(("INPUT ", "OUTPUT ")):
            label, raw_path = line.split(" ", 1)
            candidate = Path(raw_path)
            if candidate.is_absolute() and is_within(
                candidate.resolve(strict=False), build_project
            ):
                relative = candidate.resolve(strict=False).relative_to(build_project)
                line = f"{label} {project / relative}"
        normalized.append(line)
    return "\n".join(normalized) + "\n"


def remap_findings(
    findings: Iterable[Finding], build_project: Path, project: Path
) -> list[Finding]:
    build_prefix = str(build_project)
    project_prefix = str(project)
    return [
        Finding(
            finding.severity,
            finding.category,
            finding.message.replace(build_prefix, project_prefix),
            finding.source.replace(build_prefix, project_prefix),
        )
        for finding in findings
    ]


def validate_build_outputs(project: Path, main_tex: str) -> None:
    log_dir = ensure_log_directory(project)
    stem = Path(Path(main_tex).name).stem
    for suffix in sorted(AUXILIARY_SUFFIXES | {".pdf"}):
        validate_output_path(project / f"{stem}{suffix}")
    for name in (
        "latex_healthcheck.log",
        "latex_healthcheck_findings.json",
        "latex_healthcheck_findings.txt",
        "publication_gate.log",
        "publication_gate_summary.txt",
        "publication_gate_output.txt",
        "publication_clean_output.txt",
        "publication_primary_dependencies.txt",
        "publication_clean_dependencies.txt",
    ):
        validate_output_path(log_dir / name)


def process_group_exists(process_group: int) -> bool:
    try:
        os.killpg(process_group, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def wait_for_process_group_exit(
    process_group: int, timeout: float, process: subprocess.Popen[bytes]
) -> bool:
    deadline = time.monotonic() + timeout
    while process_group_exists(process_group):
        process.poll()
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)
    return True


def terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    process_group = process.pid
    try:
        os.killpg(process_group, signal.SIGTERM)
    except ProcessLookupError:
        pass
    if not wait_for_process_group_exit(process_group, 3.0, process):
        try:
            os.killpg(process_group, signal.SIGKILL)
        except ProcessLookupError:
            pass
        wait_for_process_group_exit(process_group, 1.0, process)
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass


def run_streamed_command(
    command: list[str],
    cwd: Path,
    log_path: Path,
    *,
    env: dict[str, str],
    timeout: int,
    append: bool = False,
) -> tuple[int, bool, bool]:
    mode = "ab" if append else "wb"
    written = log_path.stat().st_size if append and log_path.exists() else 0
    truncated = written >= MAX_COMPILE_LOG_BYTES
    timed_out = False
    with log_path.open(mode) as handle:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        if process.stdout is None:
            raise PipelineError("Compiler output pipe was not created.")
        os.set_blocking(process.stdout.fileno(), False)
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        deadline = time.monotonic() + timeout
        pipe_open = True
        try:
            while process.poll() is None or pipe_open:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    terminate_process_group(process)
                    break
                events = (
                    selector.select(timeout=min(0.25, remaining)) if pipe_open else []
                )
                if not pipe_open and process.poll() is None:
                    time.sleep(min(0.05, remaining))
                for key, _ in events:
                    try:
                        chunk = os.read(key.fileobj.fileno(), 65536)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(key.fileobj)
                        pipe_open = False
                        continue
                    allowed = max(0, MAX_COMPILE_LOG_BYTES - written)
                    if allowed:
                        handle.write(chunk[:allowed])
                        written += min(len(chunk), allowed)
                    if len(chunk) > allowed:
                        truncated = True
            if not timed_out and process.poll() is None:
                try:
                    process.wait(timeout=max(0.1, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    timed_out = True
                    terminate_process_group(process)
        finally:
            selector.close()
            process.stdout.close()
        if timed_out:
            handle.write(f"\nBuild timed out after {timeout} seconds.\n".encode())
        if truncated:
            handle.write(
                f"\nCompiler output exceeded {MAX_COMPILE_LOG_BYTES} bytes and was truncated.\n".encode()
            )
        handle.flush()
        os.fsync(handle.fileno())
    return process.returncode if process.returncode is not None else 124, timed_out, truncated


def strip_tex_comment(line: str) -> str:
    for index, character in enumerate(line):
        if character != "%":
            continue
        backslashes = 0
        cursor = index - 1
        while cursor >= 0 and line[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        if backslashes % 2 == 0:
            return line[:index]
    return line


def iter_source_files(project: Path, extra: Iterable[Path] = ()) -> Iterable[Path]:
    yielded: set[Path] = set()
    for path in project.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        relative_parts = path.relative_to(project).parts
        if relative_parts and relative_parts[0] in RESERVED_OUTPUT_DIRS:
            continue
        yielded.add(path)
        yield path
    for path in extra:
        if path.is_file() and path not in yielded:
            yield path


def preflight_project(
    project: Path,
    *,
    main_path: Path,
    allow_project_rc: bool,
    allow_shell_escape: bool,
) -> list[Finding]:
    findings: list[Finding] = []
    rc_file = project / ".latexmkrc"
    if rc_file.is_symlink():
        findings.append(
            Finding(
                "ERROR",
                "project-rc-symlink",
                "Project .latexmkrc must be a regular file, not a symbolic link.",
                str(rc_file),
            )
        )
    elif rc_file.exists():
        if allow_project_rc:
            findings.append(
                Finding(
                    "WARN",
                    "project-rc-enabled",
                    "Project .latexmkrc execution was explicitly enabled.",
                    str(rc_file),
                )
            )
        else:
            findings.append(
                Finding(
                    "WARN",
                    "project-rc-ignored",
                    "Project .latexmkrc exists but will be ignored by latexmk -norc.",
                    str(rc_file),
                )
            )

    for path in project.rglob("*"):
        if path.is_symlink():
            resolved = path.resolve(strict=False)
            category = "external-symlink" if not is_within(resolved, project) else "project-symlink"
            findings.append(
                Finding(
                    "ERROR",
                    category,
                    f"Project symlinks are unsafe compile targets: {path} -> {resolved}",
                    str(path),
                )
            )
            continue
        if not path.is_file():
            if not path.is_dir():
                findings.append(
                    Finding(
                        "ERROR",
                        "project-special-file",
                        "Project entries must be regular files or directories.",
                        str(path),
                    )
                )
            continue
        try:
            link_count = path.stat(follow_symlinks=False).st_nlink
        except OSError as exc:
            findings.append(
                Finding(
                    "ERROR",
                    "project-file-stat",
                    f"Could not inspect project file links: {exc}",
                    str(path),
                )
            )
            continue
        if link_count > 1:
            findings.append(
                Finding(
                    "ERROR",
                    "project-hardlink",
                    "Project files with multiple hard links are unsafe compile targets.",
                    str(path),
                )
            )

    for source_file in iter_source_files(project, (main_path,)):
        try:
            text = source_file.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            findings.append(
                Finding("ERROR", "source-read-error", str(exc), str(source_file))
            )
            continue

        active_text = "\n".join(strip_tex_comment(line) for line in text.splitlines())
        if SHELL_ESCAPE_PATTERN.search(active_text) and not allow_shell_escape:
            findings.append(
                Finding(
                    "ERROR",
                    "shell-escape-source",
                    "Source uses shell escape or pipe input; explicit approval is required.",
                    str(source_file),
                )
            )

        for match in REFERENCE_PATTERN.finditer(active_text):
            command = match.group("command")
            raw_values = match.group("value").split(",") if command == "bibliography" else [match.group("value")]
            for raw_value in raw_values:
                value = raw_value.strip()
                if not value or "\\" in value or "#" in value:
                    continue
                candidate = Path(value).expanduser()
                if not candidate.is_absolute():
                    candidate = source_file.parent / candidate
                resolved = candidate.resolve(strict=False)
                if not is_within(resolved, project):
                    findings.append(
                        Finding(
                            "ERROR",
                            "external-source-reference",
                            f"\\{command} references a path outside the project: {value}",
                            str(source_file),
                        )
                    )
    return deduplicate_findings(findings)


def deduplicate_findings(findings: Iterable[Finding]) -> list[Finding]:
    unique: dict[tuple[str, str, str, str], Finding] = {}
    for finding in findings:
        key = (finding.severity, finding.category, finding.message, finding.source)
        unique[key] = finding
    return sorted(
        unique.values(),
        key=lambda item: (item.severity != "ERROR", item.category, item.message),
    )


def scan_log(path: Path) -> list[Finding]:
    if not path.is_file():
        return []
    findings: list[Finding] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
    ):
        normalized = line.strip()
        if not normalized:
            continue
        for category, pattern in ERROR_PATTERNS:
            if pattern.search(normalized):
                findings.append(
                    Finding("ERROR", category, normalized, f"{path}:{line_number}")
                )
                break
        else:
            for category, pattern in WARNING_PATTERNS:
                if pattern.search(normalized):
                    findings.append(
                        Finding("WARN", category, normalized, f"{path}:{line_number}")
                    )
                    break
    return findings


def iter_auxiliary_logs(project: Path) -> Iterable[Path]:
    for path in sorted(project.rglob("*")):
        if path.is_symlink() or not path.is_file() or path.suffix.lower() not in AUXILIARY_LOG_SUFFIXES:
            continue
        relative_parts = path.relative_to(project).parts
        if relative_parts and relative_parts[0] in RESERVED_OUTPUT_DIRS:
            continue
        yield path


def write_findings(project: Path, findings: list[Finding]) -> None:
    log_dir = ensure_log_directory(project)
    json_path = log_dir / "latex_healthcheck_findings.json"
    text_path = log_dir / "latex_healthcheck_findings.txt"
    payload = {
        "errors": sum(finding.severity == "ERROR" for finding in findings),
        "warnings": sum(finding.severity == "WARN" for finding in findings),
        "findings": [asdict(finding) for finding in findings],
    }
    atomic_write_text(json_path, json.dumps(payload, indent=2) + "\n")
    atomic_write_text(
        text_path,
        "".join(
            f"{finding.severity} {finding.category}: {finding.message} [{finding.source}]\n"
            for finding in findings
        ),
    )


def detect_complex_build(project: Path) -> bool:
    for source_file in iter_source_files(project):
        text = source_file.read_text(encoding="utf-8", errors="replace")
        active_text = "\n".join(strip_tex_comment(line) for line in text.splitlines())
        if COMPLEX_BUILD_PATTERN.search(active_text):
            return True
    return False


def latexmk_bibliography_option(project: Path, main_tex: str) -> str:
    bbl_name = f"{Path(Path(main_tex).name).stem}.bbl"
    frozen_bbl = False
    managed_bibliography = False
    for source_file in iter_source_files(project):
        text = source_file.read_text(encoding="utf-8", errors="replace")
        active_text = "\n".join(strip_tex_comment(line) for line in text.splitlines())
        for match in REFERENCE_PATTERN.finditer(active_text):
            command = match.group("command")
            value = match.group("value").strip()
            if command in {"addbibresource", "bibliography"}:
                managed_bibliography = True
            elif command in {"input", "include"} and "\\" not in value:
                frozen_bbl = frozen_bbl or Path(value).name == bbl_name
    return "-bibtex-" if frozen_bbl and not managed_bibliography else "-bibtex-cond"


def sanitized_executable_path(raw_path: str) -> str:
    roots = [root.resolve(strict=False) for root in SAFE_EXECUTABLE_ROOTS]
    selected: list[str] = []
    for raw in raw_path.split(os.pathsep):
        if not raw:
            continue
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        path = candidate.resolve(strict=False)
        if not path.is_dir():
            continue
        safe_root = any(is_within(path, root) for root in roots)
        declared_tool = any(
            shutil.which(tool, path=str(path)) is not None for tool in DECLARED_BUILD_TOOLS
        )
        value = str(path)
        if (safe_root or declared_tool) and value not in selected:
            selected.append(value)
    return os.pathsep.join(selected)


def clean_environment(base: dict[str, str] | None = None, home: Path | None = None) -> dict[str, str]:
    environment = dict(os.environ if base is None else base)
    for name in (
        "BIBINPUTS",
        "BSTINPUTS",
        "BIBER_CACHE",
        "BIBER_CONF",
        "CDPATH",
        "ENV",
        "BASH_ENV",
        "FONTCONFIG_FILE",
        "FONTCONFIG_PATH",
        "GEM_HOME",
        "GEM_PATH",
        "LATEXMKRC",
        "OLDPWD",
        "PERL5LIB",
        "PERLLIB",
        "PWD",
        "PYTHONHOME",
        "PYTHONPATH",
        "RUBYLIB",
        "TEXINPUTS",
        "TEXMF",
        "TEXMFCONFIG",
        "TEXMFDBS",
        "TEXMFDIST",
        "TEXMFHOME",
        "TEXMFLOCAL",
        "TEXMFOUTPUT",
        "TEXMFCNF",
        "TEXMFSYSCONFIG",
        "TEXMFSYSVAR",
        "TEXMFVAR",
        "VARTEXFONTS",
        "XDG_CACHE_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
    ):
        environment.pop(name, None)
    for name in list(environment):
        if name in UNSAFE_ENVIRONMENT_VARIABLES or name.startswith(
            UNSAFE_ENVIRONMENT_PREFIXES
        ):
            environment.pop(name, None)
    environment["PATH"] = sanitized_executable_path(environment.get("PATH", ""))
    environment["openin_any"] = "p"
    environment["openout_any"] = "p"
    if home is not None:
        home.mkdir(parents=True, exist_ok=True)
        texmf_home = home / "texmf"
        texmf_home.mkdir(parents=True, exist_ok=True)
        texmf_var = home / "texmf-var"
        texmf_var.mkdir(parents=True, exist_ok=True)
        texmf_config = home / "texmf-config"
        texmf_config.mkdir(parents=True, exist_ok=True)
        cache_home = home / ".cache"
        cache_home.mkdir(parents=True, exist_ok=True)
        config_home = home / ".config"
        config_home.mkdir(parents=True, exist_ok=True)
        data_home = home / ".local" / "share"
        data_home.mkdir(parents=True, exist_ok=True)
        temp_home = home / "tmp"
        temp_home.mkdir(parents=True, exist_ok=True)
        environment["HOME"] = str(home)
        environment["TEXMFHOME"] = str(texmf_home)
        environment["TEXMFVAR"] = str(texmf_var)
        environment["TEXMFCONFIG"] = str(texmf_config)
        environment["XDG_CACHE_HOME"] = str(cache_home)
        environment["XDG_CONFIG_HOME"] = str(config_home)
        environment["XDG_DATA_HOME"] = str(data_home)
        environment["TMPDIR"] = str(temp_home)
    return environment


def compile_project(
    project: Path,
    main_tex: str,
    *,
    allow_project_rc: bool,
    allow_shell_escape: bool,
    require_latexmk: bool,
    build_timeout: int,
    environment: dict[str, str] | None = None,
) -> tuple[bool, str]:
    log_dir = ensure_log_directory(project)
    compile_log = log_dir / "latex_healthcheck.log"
    main_base = Path(main_tex).name
    pdf_path = project / f"{Path(main_base).stem}.pdf"
    pdf_path.unlink(missing_ok=True)

    latexmk = shutil.which("latexmk", path=(environment or os.environ).get("PATH"))
    xelatex = shutil.which("xelatex", path=(environment or os.environ).get("PATH"))
    shell_option = "-shell-escape" if allow_shell_escape else "-no-shell-escape"

    if latexmk:
        command = [latexmk]
        if not allow_project_rc:
            command.append("-norc")
        command.extend(
            [
                "-g",
                latexmk_bibliography_option(project, main_tex),
                "-xelatex",
                "-interaction=nonstopmode",
                "-halt-on-error",
                "-file-line-error",
                "-latexoption=-recorder",
                f"-latexoption={shell_option}",
                main_tex,
            ]
        )
        returncode, timed_out, truncated = run_streamed_command(
            command,
            project,
            compile_log,
            env=environment or clean_environment(),
            timeout=build_timeout,
        )
        if timed_out:
            return False, f"XeLaTeX compile timed out; see {compile_log}"
        if truncated:
            return False, f"XeLaTeX compile log exceeded the safety limit; see {compile_log}"
        if returncode != 0:
            return False, f"XeLaTeX compile failed; see {compile_log}"
        return True, ""

    if require_latexmk:
        atomic_write_text(compile_log, "latexmk is required for publication polish.\n")
        return False, "Missing compiler: publication polish requires latexmk and xelatex."
    if not xelatex:
        atomic_write_text(compile_log, "xelatex is unavailable.\n")
        return False, "Missing compiler: install latexmk or xelatex."
    if detect_complex_build(project):
        atomic_write_text(
            compile_log,
            "Complex bibliography/index/glossary features require latexmk.\n",
        )
        return False, "latexmk is required for bibliography, index, or glossary builds."

    atomic_write_text(compile_log, "")
    tex_log = project / f"{Path(main_base).stem}.log"
    for pass_number in range(1, 6):
        command = [
            xelatex,
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            "-recorder",
            shell_option,
            main_tex,
        ]
        with compile_log.open("ab") as handle:
            handle.write(f"== XeLaTeX pass {pass_number} ==\n".encode())
        returncode, timed_out, truncated = run_streamed_command(
            command,
            project,
            compile_log,
            env=environment or clean_environment(),
            timeout=build_timeout,
            append=True,
        )
        if timed_out:
            return False, f"XeLaTeX compile timed out; see {compile_log}"
        if truncated:
            return False, f"XeLaTeX compile log exceeded the safety limit; see {compile_log}"
        if returncode != 0:
            return False, f"XeLaTeX compile failed; see {compile_log}"
        if pass_number >= 2 and tex_log.is_file():
            current_log = tex_log.read_text(encoding="utf-8", errors="replace")
            if not any(pattern.search(current_log) for pattern in RERUN_PATTERNS):
                break
    return True, ""


def healthcheck_project(
    project: Path,
    main_tex: str,
    *,
    allow_project_rc: bool = False,
    allow_shell_escape: bool = False,
    fail_on_findings: bool = False,
    require_latexmk: bool = False,
    build_timeout: int = DEFAULT_BUILD_TIMEOUT,
    environment: dict[str, str] | None = None,
) -> BuildResult:
    project = project.resolve()
    main_path = (project / main_tex).resolve(strict=False)
    compile_log = project / "logs" / "latex_healthcheck.log"
    main_base = Path(main_tex).name
    stem = Path(main_base).stem
    tex_log = project / f"{stem}.log"
    fls_file = project / f"{stem}.fls"

    if not project.is_dir():
        return BuildResult(False, None, [], compile_log, tex_log, fls_file, f"Project directory not found: {project}")
    if not is_within(main_path, project) or not main_path.is_file():
        return BuildResult(False, None, [], compile_log, tex_log, fls_file, f"Main TeX file not found inside project: {main_tex}")
    try:
        validate_build_outputs(project, main_tex)
    except (OSError, PipelineError) as exc:
        return BuildResult(False, None, [], compile_log, tex_log, fls_file, str(exc))

    environment = clean_environment(environment)

    preflight = preflight_project(
        project,
        main_path=main_path,
        allow_project_rc=allow_project_rc,
        allow_shell_escape=allow_shell_escape,
    )
    if any(finding.severity == "ERROR" for finding in preflight):
        try:
            write_findings(project, preflight)
        except (OSError, PipelineError) as exc:
            return BuildResult(False, None, preflight, compile_log, tex_log, fls_file, str(exc))
        return BuildResult(False, None, preflight, compile_log, tex_log, fls_file, "Security preflight failed.")

    try:
        with tempfile.TemporaryDirectory(prefix="pdf-to-latex-build-") as temp_dir:
            build_project = Path(temp_dir) / "project"
            copy_clean_project(
                project,
                build_project,
                f"{stem}.pdf",
                None,
            )
            build_compile_log = build_project / "logs" / "latex_healthcheck.log"
            build_tex_log = build_project / f"{stem}.log"
            build_fls_file = build_project / f"{stem}.fls"
            build_pdf = build_project / f"{stem}.pdf"
            compiled, error = compile_project(
                build_project,
                main_tex,
                allow_project_rc=allow_project_rc,
                allow_shell_escape=allow_shell_escape,
                require_latexmk=require_latexmk,
                build_timeout=build_timeout,
                environment=environment,
            )
            if build_compile_log.is_file():
                atomic_copy_file(build_compile_log, compile_log)
            if not compiled:
                write_findings(project, preflight)
                return BuildResult(
                    False,
                    None,
                    preflight,
                    compile_log,
                    tex_log,
                    fls_file,
                    error.replace(str(build_project), str(project)),
                )

            findings = list(preflight)
            findings.extend(remap_findings(scan_log(build_tex_log), build_project, project))
            for extra_log in iter_auxiliary_logs(build_project):
                findings.extend(
                    remap_findings(scan_log(extra_log), build_project, project)
                )
            findings = deduplicate_findings(findings)
            if not build_pdf.is_file() or build_pdf.stat().st_size == 0:
                write_findings(project, findings)
                return BuildResult(
                    False,
                    None,
                    findings,
                    compile_log,
                    tex_log,
                    fls_file,
                    f"Compile command succeeded but expected PDF was not found: {project / f'{stem}.pdf'}",
                )
            dependencies = classify_dependencies(
                build_fls_file, build_project, environment=environment
            )
            atomic_copy_file(build_pdf, project / f"{stem}.pdf")
            if build_tex_log.is_file():
                atomic_copy_file(build_tex_log, tex_log)
            if build_fls_file.is_file():
                atomic_write_text(
                    fls_file,
                    normalized_recorder_text(build_fls_file, build_project, project),
                )
            write_findings(project, findings)
    except (OSError, PipelineError, shutil.Error) as exc:
        return BuildResult(False, None, preflight, compile_log, tex_log, fls_file, str(exc))

    pdf_path = project / f"{stem}.pdf"
    if fail_on_findings and any(finding.severity == "ERROR" for finding in findings):
        return BuildResult(
            False,
            pdf_path,
            findings,
            compile_log,
            tex_log,
            fls_file,
            "Compile completed with blocking findings.",
            dependencies,
        )
    return BuildResult(
        True,
        pdf_path,
        findings,
        compile_log,
        tex_log,
        fls_file,
        dependencies=dependencies,
    )


def print_healthcheck(result: BuildResult) -> None:
    if result.pdf_path:
        print(f"Output PDF: {result.pdf_path.name}")
    errors = [finding for finding in result.findings if finding.severity == "ERROR"]
    warnings = [finding for finding in result.findings if finding.severity == "WARN"]
    print(f"Findings: {len(errors)} error(s), {len(warnings)} warning(s)")
    for finding in result.findings:
        print(f"{finding.severity} {finding.category}: {finding.message}")
    if result.error:
        print(result.error, file=sys.stderr)


def split_kpathsea_paths(value: str) -> list[Path]:
    paths: list[Path] = []
    for raw_component in value.split(os.pathsep):
        component = raw_component.strip()
        while component.startswith("!!"):
            component = component[2:]
        components = [component]
        if component.startswith("{") and component.endswith("}"):
            components = component[1:-1].split(",")
        for item in components:
            normalized = item.strip()
            while normalized.startswith("!!"):
                normalized = normalized[2:]
            if normalized.endswith("//"):
                normalized = normalized[:-2]
            candidate = Path(os.path.expandvars(normalized)).expanduser()
            if normalized and candidate.is_absolute():
                paths.append(candidate.resolve(strict=False))
    return paths


def system_roots(environment: dict[str, str] | None = None) -> list[Path]:
    roots = {
        Path("/etc/fonts"),
        Path("/etc/texmf"),
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
        Path("/var/cache/fontconfig"),
        Path("/var/lib/texmf"),
        Path("/System/Library/Fonts"),
        Path("/Library/Fonts"),
        Path("/Network/Library/Fonts"),
        Path("/opt/homebrew/share/fonts"),
        Path("/opt/texlive"),
    }
    probe_environment = clean_environment(environment)
    kpsewhich = shutil.which("kpsewhich", path=probe_environment.get("PATH"))
    if kpsewhich:
        for variable in ("TEXMFDIST", "TEXMFLOCAL", "TEXMFSYSVAR", "TEXMFSYSCONFIG"):
            completed = subprocess.run(
                [kpsewhich, f"-var-value={variable}"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=probe_environment,
                check=False,
            )
            value = completed.stdout.strip()
            if completed.returncode == 0 and value:
                roots.update(split_kpathsea_paths(value))
    return sorted(root.resolve(strict=False) for root in roots if root.exists())


def classify_dependencies(
    fls_file: Path, project: Path, *, environment: dict[str, str] | None = None
) -> dict[str, list[str]]:
    report: dict[str, list[str]] = {"project": [], "system": [], "external": []}
    if not fls_file.is_file():
        report["external"].append(f"Missing recorder file: {fls_file}")

    roots = system_roots(environment)
    seen: set[Path] = set()
    fls_lines = (
        fls_file.read_text(encoding="utf-8", errors="replace").splitlines()
        if fls_file.is_file()
        else []
    )
    for line in fls_lines:
        if not line.startswith("INPUT "):
            continue
        raw_path = line[6:].strip()
        if not raw_path:
            continue
        path = Path(raw_path)
        if not path.is_absolute():
            path = project / path
        path = path.resolve(strict=False)
        if path in seen:
            continue
        seen.add(path)
        if is_within(path, project):
            report["project"].append(str(path.relative_to(project)))
        elif any(is_within(path, root) for root in roots) or str(path).startswith("/dev/"):
            report["system"].append(str(path))
        else:
            report["external"].append(str(path))

    probe_environment = clean_environment(environment)
    kpsewhich = shutil.which("kpsewhich", path=probe_environment.get("PATH"))
    for log_path in iter_auxiliary_logs(project):
        for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
            value = None
            for pattern in AUXILIARY_INPUT_PATTERNS:
                match = pattern.search(line)
                if match:
                    value = match.group(1).strip().strip("'\"")
                    break
            if not value:
                continue
            candidate = Path(value).expanduser()
            if not candidate.is_absolute():
                log_candidate = (log_path.parent / candidate).resolve(strict=False)
                project_candidate = (project / candidate).resolve(strict=False)
                if log_candidate.exists():
                    path = log_candidate
                elif project_candidate.exists():
                    path = project_candidate
                elif kpsewhich:
                    completed = subprocess.run(
                        [kpsewhich, value],
                        text=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        env=probe_environment,
                        check=False,
                    )
                    resolved = completed.stdout.strip()
                    path = (
                        Path(resolved).resolve(strict=False)
                        if completed.returncode == 0 and resolved
                        else project_candidate
                    )
                else:
                    path = project_candidate
            else:
                path = candidate.resolve(strict=False)
            if path in seen:
                continue
            seen.add(path)
            if is_within(path, project):
                report["project"].append(str(path.relative_to(project)))
            elif path.exists() and any(is_within(path, root) for root in roots):
                report["system"].append(str(path))
            else:
                report["external"].append(str(path))
    for key in report:
        report[key] = sorted(set(report[key]))
    return report


def write_dependency_report(
    project: Path, report: dict[str, list[str]], filename: str
) -> Path:
    destination = project / "logs" / filename
    ensure_log_directory(project)
    lines: list[str] = []
    for category in ("project", "system", "external"):
        lines.append(f"[{category}]\n")
        entries = report[category]
        if entries:
            lines.extend(f"{entry}\n" for entry in entries)
        else:
            lines.append("none\n")
        lines.append("\n")
    atomic_write_text(destination, "".join(lines))
    return destination


def recorder_outputs(fls_file: Path, project: Path) -> set[Path]:
    outputs: set[Path] = set()
    if not fls_file.is_file():
        return outputs
    for line in fls_file.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("OUTPUT "):
            continue
        candidate = Path(line[7:].strip())
        if not candidate.is_absolute():
            candidate = project / candidate
        resolved = candidate.resolve(strict=False)
        if is_within(resolved, project):
            outputs.add(resolved.relative_to(project))
    return outputs


def recorder_project_inputs(fls_file: Path, project: Path) -> set[Path]:
    inputs: set[Path] = set()
    if not fls_file.is_file():
        return inputs
    for line in fls_file.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("INPUT "):
            continue
        candidate = Path(line[6:].strip())
        if not candidate.is_absolute():
            candidate = project / candidate
        resolved = candidate.resolve(strict=False)
        if is_within(resolved, project) and resolved.is_file():
            inputs.add(resolved)
    return inputs


def copy_clean_project(
    source: Path,
    destination: Path,
    compiled_pdf_name: str,
    fls_file: Path | None,
) -> None:
    generated = recorder_outputs(fls_file, source) if fls_file is not None else set()
    generated.add(Path(compiled_pdf_name))

    def ignore(directory: str, names: list[str]) -> set[str]:
        directory_path = Path(directory)
        ignored: set[str] = set()
        if directory_path == source:
            ignored.update(name for name in names if name in {"logs", "evidence"})
        relative_directory = directory_path.relative_to(source)
        for name in names:
            relative = relative_directory / name
            if relative in generated:
                ignored.add(name)
        return ignored

    shutil.copytree(source, destination, symlinks=True, ignore=ignore)


def run_artifact_scan(
    project: Path,
    script_dir: Path,
    fls_file: Path,
    environment: dict[str, str] | None = None,
) -> tuple[bool, str]:
    script = script_dir / "check_latex_artifacts.sh"
    completed = run_command(
        [str(script), str(project), "--fls-file", str(fls_file)],
        project,
        env=clean_environment(environment),
    )
    return completed.returncode == 0, completed.stdout.strip()


def artifact_scan(project: Path, fls_file: Path | None = None) -> int:
    project = project.resolve()
    if not project.is_dir():
        print(f"Project directory not found: {project}", file=sys.stderr)
        return 1

    external_symlinks = []
    for path in project.rglob("*"):
        if path.is_symlink() and not is_within(path.resolve(strict=False), project):
            external_symlinks.append(path)
    if external_symlinks:
        for path in external_symlinks:
            print(f"External source symlink is not allowed: {path}", file=sys.stderr)
        return 1

    paths = set(iter_source_files(project))
    if fls_file is not None:
        paths.update(recorder_project_inputs(fls_file, project))
    text_paths: list[Path] = []
    for path in sorted(paths):
        try:
            prefix = path.read_bytes()[:8192]
        except OSError as exc:
            print(f"Could not read artifact-scan input {path}: {exc}", file=sys.stderr)
            return 1
        if b"\x00" not in prefix:
            text_paths.append(path)
    if not text_paths:
        print(f"No LaTeX source or bibliography files found in {project}", file=sys.stderr)
        return 1

    matches = 0
    for path in text_paths:
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
        ):
            if ARTIFACT_PATTERN.search(line):
                matches += 1
                print(f"{path.relative_to(project)}:{line_number}:{line}")
    if matches:
        print("Artifact scan found blocking matches.", file=sys.stderr)
        return 1
    print("Artifact scan clean.")
    return 0


def read_pgm(path: Path) -> tuple[list[int], int]:
    data = path.read_bytes()
    position = 0

    def token() -> bytes:
        nonlocal position
        while True:
            while position < len(data) and data[position] in b" \t\r\n":
                position += 1
            if position < len(data) and data[position] == ord("#"):
                newline = data.find(b"\n", position)
                position = len(data) if newline < 0 else newline + 1
                continue
            break
        start = position
        while position < len(data) and data[position] not in b" \t\r\n":
            position += 1
        if start == position:
            raise PipelineError(f"Invalid PGM header: {path}")
        return data[start:position]

    magic = token()
    try:
        width = int(token())
        height = int(token())
        maximum = int(token())
    except ValueError as exc:
        raise PipelineError(f"Invalid PGM dimensions: {path}") from exc
    if width <= 0 or height <= 0 or maximum <= 0 or maximum > 65535:
        raise PipelineError(f"Invalid PGM image metadata: {path}")
    expected = width * height
    if magic == b"P5":
        if position >= len(data) or data[position] not in b" \t\r\n":
            raise PipelineError(f"Invalid PGM raster separator: {path}")
        if data[position : position + 2] == b"\r\n":
            position += 2
        else:
            position += 1
        bytes_per_sample = 1 if maximum < 256 else 2
        payload = data[position : position + expected * bytes_per_sample]
        if len(payload) != expected * bytes_per_sample:
            raise PipelineError(f"Truncated PGM raster: {path}")
        if bytes_per_sample == 1:
            return list(payload), maximum
        return [
            (payload[index] << 8) | payload[index + 1]
            for index in range(0, len(payload), 2)
        ], maximum
    if magic == b"P2":
        samples: list[int] = []
        for _ in range(expected):
            try:
                samples.append(int(token()))
            except ValueError as exc:
                raise PipelineError(f"Invalid ASCII PGM sample: {path}") from exc
        return samples, maximum
    raise PipelineError(f"Unsupported PGM format in {path}: {magic!r}")


def visible_pixel_coverage(samples: list[int], maximum: int) -> float:
    histogram: dict[int, int] = {}
    for sample in samples:
        histogram[sample] = histogram.get(sample, 0) + 1
    background = max(histogram, key=histogram.get)
    threshold = max(1, maximum // 64)
    visible = sum(abs(sample - background) > threshold for sample in samples)
    return visible / len(samples)


def validate_pdf_pixels(
    pdf_path: Path, environment: dict[str, str] | None = None
) -> tuple[bool, str]:
    effective_environment = clean_environment(environment)
    pdfinfo = shutil.which("pdfinfo", path=effective_environment.get("PATH"))
    pdftoppm = shutil.which("pdftoppm", path=effective_environment.get("PATH"))
    mutool = shutil.which("mutool", path=effective_environment.get("PATH"))
    if not pdfinfo or not (pdftoppm or mutool):
        return False, "Pixel verification requires pdfinfo and pdftoppm or mutool."
    info = run_command([pdfinfo, str(pdf_path)], pdf_path.parent, env=effective_environment)
    match = re.search(r"^Pages:\s*(\d+)\s*$", info.stdout, re.MULTILINE)
    if info.returncode != 0 or not match or int(match.group(1)) <= 0:
        return False, "Pixel verification could not determine a positive PDF page count."
    page_count = int(match.group(1))
    pages = sorted({1, (page_count + 1) // 2, page_count})
    coverage: dict[int, float] = {}
    try:
        with tempfile.TemporaryDirectory(prefix="pdf-to-latex-pixels-") as temp_dir:
            temp_root = Path(temp_dir)
            for page in pages:
                output = temp_root / f"page-{page}.pgm"
                if pdftoppm:
                    prefix = output.with_suffix("")
                    command = [
                        pdftoppm,
                        "-f",
                        str(page),
                        "-l",
                        str(page),
                        "-r",
                        "36",
                        "-gray",
                        "-singlefile",
                        str(pdf_path),
                        str(prefix),
                    ]
                else:
                    command = [
                        mutool,
                        "draw",
                        "-q",
                        "-F",
                        "pgm",
                        "-r",
                        "36",
                        "-o",
                        str(output),
                        str(pdf_path),
                        str(page),
                    ]
                rendered = run_command(command, temp_root, env=effective_environment)
                if rendered.returncode != 0 or not output.is_file():
                    return False, f"Pixel verification failed for page {page}: {rendered.stdout.strip()}"
                samples, maximum = read_pgm(output)
                coverage[page] = visible_pixel_coverage(samples, maximum)
    except (OSError, PipelineError) as exc:
        return False, str(exc)
    minimum_coverage = 0.0001
    visible_pages = [page for page, ratio in coverage.items() if ratio >= minimum_coverage]
    if not visible_pages:
        detail = ", ".join(f"page {page}: {ratio:.6f}" for page, ratio in coverage.items())
        return False, f"All representative pages appear visually blank ({detail})."
    return True, "Representative pages contain visible pixel variation: " + ", ".join(
        str(page) for page in visible_pages
    )


def run_render(
    project: Path,
    pdf_name: str,
    script_dir: Path,
    dpi: int,
    render_args: list[str],
    environment: dict[str, str] | None = None,
) -> tuple[bool, str]:
    script = script_dir / "render_rebuilt_pages.sh"
    command = [str(script), str(project), pdf_name, str(dpi), "--force", *render_args]
    effective_environment = clean_environment(environment)
    completed = run_command(command, project, env=effective_environment)
    if completed.returncode != 0:
        return False, completed.stdout.strip()
    pixels_ok, pixels_detail = validate_pdf_pixels(project / pdf_name, effective_environment)
    if not pixels_ok:
        return False, pixels_detail
    output = completed.stdout.strip()
    return True, f"{output}\n{pixels_detail}".strip()


def validate_pdf_text(
    pdf_path: Path,
    output_path: Path,
    *,
    allow_empty_text: bool,
    environment: dict[str, str] | None = None,
) -> tuple[bool, str]:
    effective_environment = clean_environment(environment)
    pdfinfo = shutil.which("pdfinfo", path=effective_environment.get("PATH"))
    pdftotext = shutil.which("pdftotext", path=effective_environment.get("PATH"))
    if not pdfinfo or not pdftotext:
        return False, "publication polish requires pdfinfo and pdftotext."

    try:
        validate_output_path(output_path)
        output_path.unlink(missing_ok=True)
    except (OSError, PipelineError) as exc:
        return False, str(exc)

    info = subprocess.run(
        [pdfinfo, str(pdf_path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        env=effective_environment,
    )
    if info.returncode != 0:
        return False, f"pdfinfo could not read the compiled PDF: {info.stdout.strip()}"
    page_match = re.search(r"^Pages:\s*(\d+)\s*$", info.stdout, re.MULTILINE)
    if not page_match or int(page_match.group(1)) <= 0:
        return False, "Compiled PDF has no readable positive page count."

    extracted = subprocess.run(
        [pdftotext, str(pdf_path), str(output_path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        env=effective_environment,
    )
    if extracted.returncode != 0:
        return False, f"pdftotext failed: {extracted.stdout.strip()}"
    text = output_path.read_text(encoding="utf-8", errors="replace")
    visible = text.replace("\f", "").strip()
    if not visible and not allow_empty_text:
        return False, "Compiled PDF text extraction is empty."
    if not visible:
        return True, "Compiled PDF text is empty but explicitly allowed."
    return True, f"Compiled PDF text extraction contains {len(visible)} visible character(s)."


def normalized_extracted_text(path: Path) -> str:
    return re.sub(
        r"\s+", " ", path.read_text(encoding="utf-8", errors="replace").replace("\f", " ")
    ).strip()


class GateSummary:
    def __init__(self, project: Path) -> None:
        self.project = project
        log_dir = ensure_log_directory(project)
        self.log_path = log_dir / "publication_gate.log"
        self.summary_path = log_dir / "publication_gate_summary.txt"
        atomic_write_text(self.log_path, "")
        atomic_write_text(self.summary_path, "")

    def add(self, status: str, label: str, detail: str = "") -> None:
        line = f"{status}: {label}"
        if detail:
            line += f" - {detail}"
        line += "\n"
        with self.summary_path.open("a", encoding="utf-8") as handle:
            handle.write(line)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(line)
        print(line, end="")


def publication_gate(args: argparse.Namespace) -> int:
    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"Project directory not found: {project}", file=sys.stderr)
        return 1
    try:
        summary = GateSummary(project)
    except (OSError, PipelineError) as exc:
        print(f"Unsafe publication output path: {exc}", file=sys.stderr)
        return 1
    script_dir = Path(__file__).resolve().parent
    primary_environment = clean_environment()
    incomplete = False
    render_args: list[str] = []
    if args.pages:
        render_args.extend(["--pages", args.pages])
    if args.from_page is not None:
        render_args.extend(["--from", str(args.from_page)])
    if args.to_page is not None:
        render_args.extend(["--to", str(args.to_page)])
    if args.single_page_pdf:
        render_args.append("--single-page-pdf")

    result = healthcheck_project(
        project,
        args.main_tex,
        allow_project_rc=args.allow_project_rc,
        allow_shell_escape=args.allow_shell_escape,
        fail_on_findings=not args.allow_findings,
        require_latexmk=True,
        build_timeout=args.build_timeout,
        environment=primary_environment,
    )
    if not result.ok:
        print_healthcheck(result)
        summary.add("FAIL", "XeLaTeX healthcheck", result.error)
        return 1
    errors = sum(finding.severity == "ERROR" for finding in result.findings)
    warnings = sum(finding.severity == "WARN" for finding in result.findings)
    summary.add("PASS", "XeLaTeX healthcheck", f"{errors} error(s), {warnings} warning(s)")
    if errors and args.allow_findings:
        summary.add("WARN", "Blocking compile findings were explicitly allowed")
        incomplete = True

    if args.allow_project_rc or args.allow_shell_escape:
        summary.add("INCOMPLETE", "Unsafe build override used; clean isolation cannot be claimed")
        incomplete = True

    dependency_report = result.dependencies or classify_dependencies(
        result.fls_file, project, environment=primary_environment
    )
    report_path = write_dependency_report(
        project, dependency_report, "publication_primary_dependencies.txt"
    )
    if dependency_report["external"]:
        summary.add("FAIL", "Project dependency closure", f"external inputs listed in {report_path}")
        return 1
    summary.add("PASS", "Project dependency closure", str(report_path))

    artifact_ok, artifact_output = run_artifact_scan(
        project, script_dir, result.fls_file, primary_environment
    )
    if not artifact_ok:
        summary.add("FAIL", "Final source artifact scan", artifact_output)
        return 1
    summary.add("PASS", "Final source artifact scan")

    if args.skip_render:
        summary.add("INCOMPLETE", "Rendered rebuilt page evidence was skipped")
        incomplete = True
    else:
        render_ok, render_output = run_render(
            project,
            result.pdf_path.name,
            script_dir,
            args.render_dpi,
            render_args,
            primary_environment,
        )
        if not render_ok:
            summary.add("FAIL", "Rendered rebuilt page evidence", render_output)
            return 1
        summary.add("PASS", "Rendered rebuilt page evidence")

    text_output = project / "logs" / "publication_gate_output.txt"
    text_ok, text_detail = validate_pdf_text(
        result.pdf_path,
        text_output,
        allow_empty_text=args.allow_empty_text,
        environment=primary_environment,
    )
    if not text_ok:
        summary.add("FAIL", "Compiled PDF text extraction", text_detail)
        return 1
    status = "WARN" if "explicitly allowed" in text_detail else "PASS"
    summary.add(status, "Compiled PDF text extraction", text_detail)

    if args.skip_clean:
        summary.add("INCOMPLETE", "Clean-room XeLaTeX rebuild was skipped")
        incomplete = True
    else:
        with tempfile.TemporaryDirectory(prefix="pdf-to-latex-clean-") as temp_dir:
            temp_root = Path(temp_dir)
            clean_project = temp_root / "project"
            try:
                copy_clean_project(
                    project, clean_project, result.pdf_path.name, result.fls_file
                )
            except (OSError, PipelineError, shutil.Error) as exc:
                summary.add("FAIL", "Clean-room project copy", str(exc))
                return 1
            environment = clean_environment(home=temp_root / "home")
            clean_result = healthcheck_project(
                clean_project,
                args.main_tex,
                allow_project_rc=args.allow_project_rc,
                allow_shell_escape=args.allow_shell_escape,
                fail_on_findings=not args.allow_findings,
                require_latexmk=True,
                build_timeout=args.build_timeout,
                environment=environment,
            )
            if not clean_result.ok:
                summary.add("FAIL", "Clean-room XeLaTeX rebuild", clean_result.error)
                return 1
            clean_errors = sum(
                finding.severity == "ERROR" for finding in clean_result.findings
            )
            clean_warnings = sum(
                finding.severity == "WARN" for finding in clean_result.findings
            )
            if clean_errors and args.allow_findings:
                summary.add(
                    "WARN",
                    "Clean-room build has explicitly allowed blocking findings",
                    f"{clean_errors} error(s), {clean_warnings} warning(s)",
                )
                incomplete = True
            clean_dependencies = clean_result.dependencies or classify_dependencies(
                clean_result.fls_file, clean_project, environment=environment
            )
            clean_report_path = write_dependency_report(
                project,
                clean_dependencies,
                "publication_clean_dependencies.txt",
            )
            if clean_dependencies["external"]:
                summary.add(
                    "FAIL",
                    "Clean-room dependency closure",
                    f"external inputs listed in {clean_report_path}",
                )
                return 1
            clean_text_temp = clean_project / "logs" / "publication_gate_output.txt"
            clean_text_ok, clean_text_detail = validate_pdf_text(
                clean_result.pdf_path,
                clean_text_temp,
                allow_empty_text=args.allow_empty_text,
                environment=environment,
            )
            if not clean_text_ok:
                summary.add("FAIL", "Clean-room PDF text extraction", clean_text_detail)
                return 1
            if normalized_extracted_text(text_output) != normalized_extracted_text(
                clean_text_temp
            ):
                summary.add(
                    "FAIL",
                    "Primary and clean-room semantic output",
                    "Extracted text differs between the two builds.",
                )
                return 1
            atomic_write_text(
                project / "logs" / "publication_clean_output.txt",
                clean_text_temp.read_text(encoding="utf-8", errors="replace"),
            )
            clean_text_status = (
                "WARN" if "explicitly allowed" in clean_text_detail else "PASS"
            )
            summary.add(
                clean_text_status,
                "Clean-room PDF text extraction",
                clean_text_detail,
            )
            if not args.skip_render:
                clean_render_ok, clean_render_output = run_render(
                    clean_project,
                    clean_result.pdf_path.name,
                    script_dir,
                    args.render_dpi,
                    render_args,
                    environment,
                )
                if not clean_render_ok:
                    summary.add(
                        "FAIL", "Clean-room rendered page evidence", clean_render_output
                    )
                    return 1
                summary.add("PASS", "Clean-room rendered page evidence")
            summary.add(
                "PASS",
                "Clean-room XeLaTeX rebuild",
                str(clean_report_path),
            )

    if incomplete:
        summary.add("INCOMPLETE", "Publication gate completed but is not a passing final gate")
        return 2
    summary.add("PASS", "Publication gate")
    print(f"Publication gate passed. Summary: {summary.summary_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    health = subparsers.add_parser("healthcheck", help="Compile and classify XeLaTeX findings.")
    health.add_argument("project_dir", nargs="?", default=".")
    health.add_argument("main_tex", nargs="?", default="main.tex")
    health.add_argument("--allow-project-rc", action="store_true")
    health.add_argument("--allow-shell-escape", action="store_true")
    health.add_argument("--fail-on-findings", action="store_true")
    health.add_argument("--require-latexmk", action="store_true")
    health.add_argument("--build-timeout", type=int, default=DEFAULT_BUILD_TIMEOUT)

    publication = subparsers.add_parser("publication", help="Run the strict publication gate.")
    publication.add_argument("project_dir", nargs="?", default=".")
    publication.add_argument("main_tex", nargs="?", default="main.tex")
    publication.add_argument("--allow-findings", action="store_true")
    publication.add_argument("--allow-empty-text", action="store_true")
    publication.add_argument("--allow-project-rc", action="store_true")
    publication.add_argument("--allow-shell-escape", action="store_true")
    publication.add_argument("--strict-findings", action="store_true", help=argparse.SUPPRESS)
    publication.add_argument("--skip-render", action="store_true")
    publication.add_argument("--skip-clean", action="store_true")
    publication.add_argument("--render-dpi", type=int, default=140)
    publication.add_argument("--build-timeout", type=int, default=DEFAULT_BUILD_TIMEOUT)
    publication.add_argument("--pages")
    publication.add_argument("--from", dest="from_page", type=int)
    publication.add_argument("--to", dest="to_page", type=int)
    publication.add_argument("--single-page-pdf", action="store_true")

    artifact = subparsers.add_parser("artifact", help="Scan final source for extraction artifacts.")
    artifact.add_argument("project_dir", nargs="?", default=".")
    artifact.add_argument("--fls-file", type=Path)
    return parser


def main() -> int:
    require_python()
    parser = build_parser()
    args = parser.parse_args()
    if args.command in {"healthcheck", "publication"} and args.build_timeout <= 0:
        parser.error("--build-timeout must be a positive integer")
    if args.command == "healthcheck":
        result = healthcheck_project(
            Path(args.project_dir),
            args.main_tex,
            allow_project_rc=args.allow_project_rc,
            allow_shell_escape=args.allow_shell_escape,
            fail_on_findings=args.fail_on_findings,
            require_latexmk=args.require_latexmk,
            build_timeout=args.build_timeout,
        )
        print_healthcheck(result)
        return 0 if result.ok else 1
    if args.command == "artifact":
        return artifact_scan(Path(args.project_dir), args.fls_file)
    if args.render_dpi <= 0:
        parser.error("--render-dpi must be a positive integer")
    return publication_gate(args)


if __name__ == "__main__":
    raise SystemExit(main())
