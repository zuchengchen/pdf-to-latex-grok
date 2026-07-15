#!/usr/bin/env python3
"""Report PDF-to-LaTeX toolchain capabilities."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys


TOOLS = (
    "xelatex",
    "latexmk",
    "pdfinfo",
    "pdftoppm",
    "mutool",
    "pdftotext",
    "pdfimages",
    "pdfseparate",
    "biber",
    "bibtex",
    "makeindex",
    "makeglossaries",
)


def bash_capability() -> tuple[str | None, bool]:
    bash = shutil.which("bash")
    if not bash:
        return None, False
    completed = subprocess.run(
        [bash, "--version"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if completed.returncode != 0:
        return "unknown", False
    match = re.search(r"version\s+([0-9]+(?:\.[0-9]+)+)", completed.stdout)
    if not match:
        return "unknown", False
    version = match.group(1)
    parts = tuple(int(part) for part in version.split("."))
    return version, parts >= (3, 2)


def has_cjk_fonts() -> bool | None:
    fc_list = shutil.which("fc-list")
    if not fc_list:
        return None
    completed = subprocess.run(
        [fc_list, ":lang=zh", "family"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return completed.returncode == 0 and bool(completed.stdout.strip())


def capabilities() -> dict[str, object]:
    paths = {name: shutil.which(name) for name in TOOLS}
    bash_version, bash_supported = bash_capability()
    if paths["latexmk"] and paths["xelatex"]:
        compile_capability = "full"
    elif paths["xelatex"]:
        compile_capability = "simple-only"
    else:
        compile_capability = "unavailable"
    renderer = "pdftoppm" if paths["pdftoppm"] else "mutool" if paths["mutool"] else "unavailable"
    bibliography = [name for name in ("biber", "bibtex") if paths[name]]
    return {
        "python": {
            "version": ".".join(str(part) for part in sys.version_info[:3]),
            "supported": sys.version_info >= (3, 10),
            "executable": sys.executable,
        },
        "bash": {
            "version": bash_version,
            "supported": bash_supported,
        },
        "capabilities": {
            "compile": compile_capability,
            "render": renderer,
            "text_layer": "available" if paths["pdftotext"] else "unavailable",
            "pdf_metadata": "available" if paths["pdfinfo"] else "unavailable",
            "single_page_pdf": "available" if paths["pdfseparate"] else "unavailable",
            "bibliography": bibliography or ["unavailable"],
            "index": "available" if paths["makeindex"] else "unavailable",
            "glossary": "available" if paths["makeglossaries"] else "unavailable",
            "cjk_fonts": has_cjk_fonts(),
        },
        "tools": {name: path for name, path in paths.items()},
    }


def print_human(report: dict[str, object]) -> None:
    python = report["python"]
    bash = report["bash"]
    values = report["capabilities"]
    print(f"Python: {python['version']} ({'supported' if python['supported'] else 'unsupported'})")
    bash_status = "supported" if bash["supported"] else "unsupported"
    print(f"Bash: {bash['version'] or 'unavailable'} ({bash_status})")
    print(f"Compile: {values['compile']}")
    print(f"Render: {values['render']}")
    print(f"Text layer: {values['text_layer']}")
    print(f"PDF metadata: {values['pdf_metadata']}")
    print(f"Single-page PDF: {values['single_page_pdf']}")
    print(f"Bibliography: {', '.join(values['bibliography'])}")
    print(f"Index: {values['index']}")
    print(f"Glossary: {values['glossary']}")
    cjk = values["cjk_fonts"]
    print(f"CJK fonts: {'unknown' if cjk is None else 'available' if cjk else 'unavailable'}")


def required_failures(report: dict[str, object], requirement: str) -> list[str]:
    values = report["capabilities"]
    failures: list[str] = []
    if not report["python"]["supported"]:
        failures.append("Python 3.10+")
    if not report["bash"]["supported"]:
        failures.append("Bash 3.2+")
    if requirement in {"core", "publication"}:
        if values["compile"] == "unavailable":
            failures.append("XeLaTeX")
        if values["pdf_metadata"] == "unavailable":
            failures.append("pdfinfo")
        if values["render"] == "unavailable":
            failures.append("pdftoppm or mutool")
    if requirement == "publication":
        if values["compile"] != "full":
            failures.append("latexmk + XeLaTeX")
        if values["text_layer"] == "unavailable":
            failures.append("pdftotext")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--require", choices=("none", "core", "publication"), default="none")
    args = parser.parse_args()
    report = capabilities()
    if args.as_json:
        print(json.dumps(report, indent=2) + "\n", end="")
    else:
        print_human(report)
    failures = required_failures(report, args.require)
    if failures:
        print(f"Missing required capabilities: {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
