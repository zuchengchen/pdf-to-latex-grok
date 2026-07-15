# Repository Guidelines

## Project Structure & Module Organization

This repository publishes a PDF-to-LaTeX Grok skill. The installable skill lives in `skill/`; do not treat the repository root as the skill root. Keep human-facing docs in `README.md` and `INSTALL.md`, and keep development goal records in `dev-goals/`.

Inside `skill/`, `SKILL.md` is the trigger and workflow entry point. Detailed procedural guidance belongs in `skill/references/`. Helper utilities live in `skill/scripts/`.

## Build, Test, and Development Commands

- `python3 skill/scripts/workflow_contract.py validate-package skill` validates the installable package, workflow contract, bundled templates, executable bits, and artifact hygiene.
- `bash -n skill/scripts/*.sh` and `shellcheck --shell=bash skill/scripts/*.sh` check helper scripts for syntax and common shell errors.
- `skill/scripts/test_skill.sh --portable` runs deterministic contract, package, scaffold, and helper tests without requiring a TeX installation.
- `skill/scripts/test_skill.sh --integration --require-tools` runs the real XeLaTeX, `latexmk`, Poppler, evidence, and publication pipeline tests.
- `skill/scripts/test_skill.sh --extended --require-tools` adds the longer bibliography, index, glossary, CJK, book, and forward-test corpus.
- `skill/scripts/init_latex_project.sh source.pdf latex --operation convert --source-kind digital --traits none --delivery-level clean-semantic --execution-mode resumable --verification-scope source-aware` creates a contract-derived conversion scaffold from bundled templates.
- `skill/scripts/render_pdf_pages.sh source.pdf latex 180` renders durable page evidence for a sample PDF.
- `skill/scripts/latex_healthcheck.sh latex main.tex` compiles a generated XeLaTeX project with project rc files and shell escape disabled by default, then summarizes findings.
- `skill/scripts/publication_gate.sh latex main.tex` runs strict publication checks, dependency-closure checks, and a sanitized clean-room rebuild.
- `skill/scripts/check_latex_artifacts.sh latex` scans final LaTeX source for extraction artifacts.

There is no package build step; the deliverable is `skill/`.

## Coding Style & Naming Conventions

Write Markdown instructions in clear imperative language. Keep `SKILL.md` concise and route details to one-level reference files under `skill/references/`. Use lowercase hyphenated names for skill and reference files, and snake_case for generated conversion artifacts such as `conversion-state.md` and `glyph-map.md`.

Python helpers require Python 3.10+ and must use the standard library unless the project direction changes explicitly. Shell entrypoints must remain compatible with Bash 3.2, use `set -euo pipefail`, quote variables, validate arguments, and avoid hidden network or OCR dependencies.

## Testing Guidelines

Run the package validator and `skill/scripts/test_skill.sh --portable` after changes to `skill/SKILL.md`, the contract, templates, or package layout. Run `bash -n` and ShellCheck after shell edits. Every pull request must pass `skill/scripts/test_skill.sh --integration --require-tools` with real XeLaTeX, `latexmk`, Poppler, and Noto CJK fonts; scheduled and release validation must also run the extended suite with biber and the index/glossary tools. For workflow changes, test against a small real PDF or generated LaTeX project when practical, and record manual verification in the PR.

## Commit & Pull Request Guidelines

Use concise imperative commit subjects, matching the existing history: `Add ...`, `Refine ...`, `Document ...`, `Restructure ...`. Keep the first line focused and under about 72 characters.

Pull requests should describe the behavioral change, list validation commands run, and call out install-path changes such as `skill/` versus repository root. Include before/after examples when changing prompts, metadata, or workflow rules.

## Agent-Specific Instructions

Do not add local OCR, cloud OCR, pixel-perfect facsimile workflows, full-page screenshot wrapping, or a bundled converter unless the project direction changes explicitly. Keep generated PDF conversion outputs out of the repository; the repo should contain reusable skill instructions, references, metadata, and helper scripts only.

Make repository changes only under this checkout. Never edit an installed copy under `${GROK_HOME:-$HOME/.grok}/skills`; installation testing must use a temporary staging directory.

After completing repository changes, run relevant validation, stage only task-related files, and create a git commit automatically unless the user explicitly says not to. Do not push unless asked.
