# Changelog

## Unreleased

- Adaptive batch planning: scanned/mixed empty text layers stay multi-page
  batches (not automatic single-page critical); scale sizes by source kind and
  traits; add `worker-brief.md` template.
- Enforce minimum progress per turn and scale-aware compile cadence for
  multi-page work.
- Prefer spawning subagents for multi-page reconstruction with minimal
  per-worker context packets to reduce token use.
- Prefer original PDF figure assets (extract/crop + `\includegraphics`) over
  TikZ or other LaTeX redraws by default.
- Make continuity auto-start: never block on Goal startup; use `resumable` by
  default when no matching Goal is active; keep delivery quality independent
  of Goal; optional `/goal` pin is non-blocking.
- Make Grok install/update URL-based:
  `安装skill https://github.com/zuchengchen/pdf-to-latex-grok.git` and
  `更新skill https://github.com/zuchengchen/pdf-to-latex-grok.git`.
- Point the bundled installer default source at
  `https://github.com/zuchengchen/pdf-to-latex-grok` and accept `--url`.
- Port the skill packaging, install path, docs, Goal runtime, and updater to
  Grok only (`~/.grok/skills`, `/pdf-to-latex`, `update_goal`, `spawn_subagent`).
- Remove Codex-only surfaces (`agents/openai.yaml`, `$pdf-to-latex`,
  `CODEX_HOME`, system skill-installer / quick_validate dependencies).
- Prefer automatic Goal-backed execution for full, broad, multi-batch, and
  publication-scale writable work without a separate confirmation prompt.
- Add a concise Goal startup, continuation, completion, and resumable-fallback
  protocol while keeping project state authoritative.

## 1.0.0 - 2026-07-10

- Replace the combined task-profile model with explicit operation, source,
  document-trait, delivery, execution, verification, and outcome fields.
- Add a machine-readable workflow contract and deterministic state validation.
- Make review operations read-only and decouple Goal mode from delivery quality.
- Compile from temporary staged projects with sanitized startup environments,
  restrictive Kpathsea I/O, and rejection of symlinks, hard links, and special
  files.
- Make publication findings strict by default, including missing-glyph,
  visible-pixel, normalized-text, dependency-closure, and clean-room checks.
- Add atomic scaffold updates, source fingerprints, transactional page evidence,
  recovery handling, and evidence manifests.
- Add atomic install/update guidance, stable release installation, and expanded
  integration validation.
- Clarify that the skill performs editable semantic reconstruction, not
  pixel-perfect facsimile generation or OCR.
