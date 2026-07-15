# PDF to LaTeX Skill

`pdf-to-latex` is a Grok skill for rebuilding user-provided PDFs as editable,
semantic XeLaTeX projects. It supports new conversions, resumable work, broad
refinement, localized repairs, and read-only reviews of PDF-derived projects.

The normal target is maintainable LaTeX with faithful structure, text, math,
tables, figures, citations, and book apparatus. Pixel-perfect facsimiles,
full-page screenshot wrapping, OCR services, and generic PDF editing are outside
the skill's scope.

The installable skill is [`skill/`](skill/). The repository root contains
publishing, installation, and development material and is not itself a skill.

## Install In Grok

In Grok, install with:

```text
安装skill https://github.com/zuchengchen/pdf-to-latex-grok.git
```

Equivalent forms:

```text
安装 skill https://github.com/zuchengchen/pdf-to-latex-grok.git
install skill https://github.com/zuchengchen/pdf-to-latex-grok.git
```

Grok should clone this repository, run
`skill/scripts/update_installed_skill.sh`, and place the package at
`${GROK_HOME:-$HOME/.grok}/skills/pdf-to-latex`. Start a new Grok session after
installation if the skill list remains stale (skills often auto-reload).

Optional tag, branch, or commit:

```text
安装skill https://github.com/zuchengchen/pdf-to-latex-grok.git 到 v1.0.0
```

Shell equivalent (fresh machine):

```bash
tmp_dir=$(mktemp -d)
git clone --depth 1 https://github.com/zuchengchen/pdf-to-latex-grok.git "$tmp_dir/repo"
bash "$tmp_dir/repo/skill/scripts/update_installed_skill.sh" \
  --url https://github.com/zuchengchen/pdf-to-latex-grok.git
rm -rf "$tmp_dir"
```

See [INSTALL.md](INSTALL.md) for atomic manual procedures, verification, and
uninstall.

## Update In Grok

```text
更新skill https://github.com/zuchengchen/pdf-to-latex-grok.git
```

Equivalent forms:

```text
更新 skill https://github.com/zuchengchen/pdf-to-latex-grok.git
update skill https://github.com/zuchengchen/pdf-to-latex-grok.git
```

Optional ref:

```text
更新skill https://github.com/zuchengchen/pdf-to-latex-grok.git 到 main
```

The bare update defaults to branch `main`. It downloads into same-filesystem
staging under `${GROK_HOME:-$HOME/.grok}/skills`, repairs executable bits, runs
one package validation, and swaps directories by rename with rollback.

## Workflow Model

The skill records independent workflow dimensions instead of a combined task
profile:

```text
Operation:          convert | resume | refine | repair | review
Source kind:        digital | scanned | mixed | unknown
Document traits:    book, long-document, math-heavy, encoded-math, cjk, visual-complex
Delivery level:     rough-draft | clean-semantic | publication-polish
Execution mode:     one-turn | resumable | goal-backed
Verification scope: source-aware | project-only
Outcome:            in-progress | complete | blocked | downgraded
```

File layout is derived from these fields. For example, book traits add stable
front/main/back matter boundaries, while math traits add math and glyph tracking.
Read-only `review` operations compile and render only in temporary copies and do
not update the user's project.

Prefer auto-start **run-to-completion**: never block on Goal startup, and never
pause mid-pipeline waiting for the user to say 继续 / continue. A single
`/pdf-to-latex …` request should drive full conversions, broad resume or
refinement, publication-scale work, and multi-batch tasks through all planned
batches, integration, gates, and a terminal outcome in one continuous session
when the host allows. When a matching Goal is already active, continue it with
`update_goal`; otherwise use `resumable` by default at the same delivery
quality. Project files such as `conversion-state.md` remain the durable progress
record for forced mid-run stops and later resume. Optional `/goal` pinning is
never required before reconstruction starts.

## Parallel Reconstruction

Long resumable and goal-backed conversions **prefer** one parent controller plus a bounded pool of `spawn_subagent` workers to save parent tokens. Each worker gets a compact context packet (page lists, evidence paths, hashes, path to `worker-brief.md`—not full skill/Goal/chat dumps), writes only a page-IR shard, and does not edit shared LaTeX, workflow state, or the final PDF. Page ownership is non-overlapping; neighboring pages are optional read-only context because page boundaries are not semantic boundaries.

Before dispatch, `skill/scripts/plan_batches.py` uses local `pdfinfo` and `pdftotext` evidence to write a source-bound `work/page-index.json`. Batch sizes adapt by source kind and traits: digital prose uses larger batches; scanned and mixed empty text layers stay multi-page visual batches (not one worker per page by default); one-page workers are reserved for true high-risk pages. Multi-page work runs until complete by default (dispatch remaining batches in a bounded concurrent pool; no continue prompts); large projects compile mainly at chapter boundaries.

New workers should emit compact page-IR v2 shards: page status and counts stay in the shard, while detailed IR is a hashed detail artifact. The parent reads the summary in `batch-manifest.json` and opens detail only when a blocker, uncertainty, cross-page boundary, or failed integration requires it. `skill/scripts/report_worker_usage.py` aggregates optional input, cached-input, output, reasoning, retry, and duration telemetry.

The scaffold records worker ownership and artifact hashes in `batch-manifest.json`, stores shards under `work/shards/`, and merges them through `skill/scripts/merge_shards.py`. Cross-page continuity, global labels and references, bibliography/index/glossary, final source edits, compilation, and terminal outcomes remain parent-agent responsibilities. On Grok, workers are launched with `spawn_subagent` in an isolated context; the parent passes a compact snapshot and evidence packet instead of the full parent history.

## Safety And Quality

- Ignores project `.latexmkrc` files and disables shell escape by default.
- Requires explicit approval to enable project rc execution or shell escape.
- Compiles in a temporary staged project and rejects project symlinks, hard links,
  special files, and project-external TeX inputs during final verification.
- Forces restrictive Kpathsea input/output policy and sanitizes runtime startup
  variables before invoking the toolchain.
- Classifies missing characters, missing files, undefined references, and package
  failures as blocking findings.
- Treats ordinary font substitution and box warnings as reviewable warnings.
- Uses project-closure reports and a sanitized clean-room rebuild for publication
  polish.
- Records source PDF SHA-256 identity and refuses to reuse stale page evidence.
- Writes page renders and text-layer evidence transactionally with JSON manifests.
- Makes publication findings strict by default; diagnostic overrides cannot be
  reported as a passing final gate.

## Runtime Capabilities

| Capability | Requirement | When needed |
| --- | --- | --- |
| Contract, state, evidence | Python 3.10+ | All deterministic helpers |
| Shell entrypoints | Bash 3.2+ | Wrapper commands; macOS system Bash is supported |
| Simple compilation | XeLaTeX | Rough draft and simple clean-semantic work |
| Full compilation | `latexmk` + XeLaTeX | Publication polish and complex build chains |
| PDF metadata/pages | `pdfinfo` | Full conversion, source identity, publication checks |
| Page rendering | `pdftoppm` or `mutool` | Visual analysis and comparison |
| Digital text layer | `pdftotext` | Digital evidence and output verification |
| Single-page PDFs | `pdfseparate` | Only with explicit `--single-page-pdf` |
| Bibliography/index/glossary | biber/BibTeX, makeindex, makeglossaries as used | Project-dependent |

The skill does not use `tesseract`, `ocrmypdf`, cloud OCR APIs, or a bundled
converter. Scanned pages are visually transcribed by Grok from rendered page
evidence.

## Repository Structure

```text
pdf-to-latex-grok/
├── CHANGELOG.md
├── INSTALL.md
├── LICENSE
├── README.md
├── dev-goals/
└── skill/
    ├── SKILL.md
    ├── assets/templates/
    ├── assets/schemas/
    ├── references/
    └── scripts/
```

## Development Validation

Fast portable checks:

```bash
skill/scripts/test_skill.sh --portable
```

Required local integration checks:

```bash
skill/scripts/test_skill.sh --integration --require-tools
```

Package validation:

```bash
python3 skill/scripts/workflow_contract.py validate-package skill
```

## Usage Examples

```text
/pdf-to-latex 把 ./paper.pdf 重建成可编辑 XeLaTeX 项目并完成语义检查；立刻开工，不要等待 /goal，持续执行到工作流完成或遇到必须由我决定的问题
```

```text
/pdf-to-latex 继续 ./latex 中上次中断的转换
```

```text
/pdf-to-latex 只读审查 ./latex，对照 ./paper.pdf 给出问题，不要修改项目
```

```text
/pdf-to-latex 修复 ./latex 中这个局部编译问题，不要展开成完整重建
```

## Versioning

Tagged releases such as `v1.0.0` are the stable installation channel. The
`main` branch is the development channel and may contain unreleased contract or
workflow changes. Workflow contract and state schema versions are recorded
separately inside `skill/references/workflow-contract.json`.

## License

MIT License. See [LICENSE](LICENSE).
