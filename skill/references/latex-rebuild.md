# LaTeX Rebuild

Use this reference to turn analyzed PDF evidence into maintainable XeLaTeX. Reconstruct the document model, not a sequence of page snapshots.

## Contents

- Reconstruction Principles
- Project Shape
- Document Model
- Production Specification
- Skeleton Compile
- Asset Discovery
- Content Reconstruction
- Objects And References
- Batch Integration
- Durable Records

## Reconstruction Principles

- Preserve meaning, reading order, hierarchy, formulas, objects, captions, citations, and relevant layout.
- Use semantic LaTeX environments instead of manual spacing or absolute positioning.
- Treat page boundaries as evidence boundaries, not normal source-file boundaries.
- Remove running headers, footers, repeated page numbers, and extraction artifacts from body content.
- Use rendered pages to correct digital extraction and to transcribe scanned or damaged regions.
- Keep genuine figures as local image assets extracted from the source PDF; rebuild legible text, math, and tables as editable source.
- Prefer source page size and broad hierarchy when practical, but do not chase pixel identity.
- Label inference, approximation, public metadata, and unresolved source content.

Do not embed ordinary full pages to make a conversion appear complete. A full-page image is appropriate only when the source object itself is a plate, poster, illustration, or similar indivisible visual.

### Figure Policy (Default)

**Prefer original PDF visuals over LaTeX redraws.**

1. Extract embedded images from the source PDF when possible (`pdfimages`, `mutool extract`, or equivalent).
2. Otherwise crop the figure region from a high-resolution page render (`pdftoppm` / `mutool`) into `figures/`.
3. Include assets with `\includegraphics` (or similar) under project-relative paths.
4. **Do not** redraw source figures, photos, plots, schematics, or diagrams in TikZ, PGFPlots, `picture`, Asymptote, or hand-coded vector LaTeX by default.
5. Semantic redraw is allowed only when the user explicitly requests it, or when no usable raster/vector asset can be obtained and a simple, faithful recreation is clearly better than a blank or blocker—and only after recording that approximation.
6. Never invent visual data. Never replace a complex figure with a simplified TikZ sketch “for neatness.”

## Project Shape

Derive files and directories from `Operation`, `Document traits`, `Delivery level`, and `Execution mode` according to `workflow-contract.json`. There is no task profile.

A broad resumable project may use:

```text
main.tex
frontmatter/
chapters/
backmatter/
figures/
tables/
evidence/
logs/
conversion-state.md
conversion-notes.md
page-manifest.md
object-inventory.md
style-profile.md
document-ir.md
math-inventory.md
glyph-map.md
```

Create only required or useful artifacts. A bounded repair may need only the existing project and temporary diagnostics. A read-only review must not create any project artifact.

Use project-relative paths. Keep final source separate from transcripts, evidence, crops, logs, and generated build files. Split long content at stable structural boundaries rather than arbitrary page ranges.

## Document Model

Build or infer a document model before broad final drafting. Capture:

```text
Document class and language plan:
Front, main, and back matter:
Section hierarchy:
Blocks and source-page coverage:
Figures, tables, formulas, and theorem-like objects:
Labels, citations, and cross-references:
File ownership:
Uncertainties and blockers:
```

For small one-turn work, this may be a concise plan rather than a standalone file. For broad source-aware publication work, keep `document-ir.md` and reconcile it with the route map and object inventory.

Do not concatenate page transcripts directly into chapters. Merge cross-page paragraphs, restore structural boundaries, associate captions with objects, and remove repeated page furniture first.

## Production Specification

Before broad publication drafting, record:

- class family and maintainable file layout;
- source and target paper sizes, geometry, sidedness, and page-number policy;
- Unicode, language, CJK, font, and fallback strategy;
- sectioning, theorem, equation, figure, table, and appendix numbering;
- figure, crop, diagram, table, and float strategy;
- citation, bibliography, generated-list, index, and glossary strategy when present;
- exact-pagination goal, allowed approximations, and non-goals;
- toolchain capabilities and conditional dependencies.

Use portable defaults unless the source or existing project requires more. Do not add packages speculatively. Do not emit bibliography, index, or glossary commands without corresponding data and a supported build path.

## Skeleton Compile

Create the production preamble and a minimal structural skeleton before drafting most content. Include representative inputs, language and fonts, numbering, generated-list hooks, bibliography/index/glossary hooks when actually used, and sample high-risk environments.

Read `security-and-build.md` first. Compile existing or user-provided projects initially in a temporary copy under safe defaults. Record the command, generated PDF, relevant findings, and required external tools.

Resolve class, package, font, Unicode, path, and toolchain failures before broad reconstruction. A skeleton that compiles only because of stale auxiliary files or user-local configuration has not passed.

## Asset Discovery

Before drafting chapters around missing objects, locate and classify assets:

- embedded image extracted from the source PDF (preferred for figures);
- project-local image or font asset already in the target tree;
- cropped genuine figure region from a page render (fallback when embedded extract fails);
- semantic table (text/data tables, not pictorial figures);
- formula reconstruction;
- bibliography or metadata source;
- unreadable or unavailable blocker;
- allowed omission with reason;
- semantic diagram or plot recreation (**last resort only**, with explicit reason).

Record source page, target file, ownership, status, and derivation. Prefer native embedded extraction, then tight crops of the figure object; avoid screenshots that include surrounding body text, captions already typeset in LaTeX, or page furniture. Do not default to TikZ or other LaTeX redraws.

Publication work requires project-specific inputs to be localized inside the project. System TeX packages and system fonts may remain environmental dependencies and should be recorded.

## Content Reconstruction

### Text And Structure

- Convert visible headings into `\part`, `\chapter`, `\section`, or the appropriate semantic level.
- Join paragraphs split across pages and columns.
- Restore lists, quotations, footnotes, sidebars, abstracts, appendices, and theorem-like blocks.
- Escape LaTeX special characters in text while preserving intentional commands.
- Use comments only for concise source uncertainty, not as a substitute for reconstruction.

### Figures

- Default path: extract original graphics from the source PDF → store under `figures/` → `\includegraphics`.
- Prefer `pdfimages -all` (or `mutool extract`) for embedded bitmaps/vectors; fall back to a cropped high-DPI page render of that figure only.
- Store assets under project-relative paths; do not use absolute image paths in final source.
- Preserve captions, labels, credits, and in-text references as LaTeX text (not burned into the image when the caption is separate body text).
- Crop to the actual source object and verify readability against the source page.
- Use stable sizing such as `\linewidth` or a fixed fraction of it; avoid brittle absolute coordinates.
- Do not rebuild photos, scanned plates, plotted curves, circuit drawings, or book illustrations as TikZ/PGFPlots unless the user asked for editable vector redraws.
- If extraction yields multiple candidates, pick the asset that matches the figure’s visual content; record the mapping in `object-inventory.md`.

### Tables

- Rebuild legible content with `tabular`, `tabularx`, `longtable`, or another justified environment.
- Preserve headers, units, notes, captions, labels, and meaningful alignment.
- Mark uncertain cells with a localized note rather than fabricating values.
- Use a cropped table image only when semantic reconstruction is infeasible and the delivery contract allows that approximation.

### Mathematics

- Use standard math and theorem environments.
- Preserve visible numbering, labels, references, punctuation, and surrounding prose.
- Route systematic formulas, encoded glyphs, or placeholders through `math-polish.md`.
- Do not trust extracted superscripts, subscripts, operators, or delimiters without visual comparison.

### Citations And Bibliography

- Preserve source citation identity and visible bibliography content.
- Choose `thebibliography`, BibTeX, or `biblatex` according to project size and available tools.
- Use public metadata only to correct or complete identifiable public records, and label it separately from PDF-derived content.
- Do not silently replace the source's citation scheme.

## Objects And References

Use stable, descriptive labels such as `sec:methods`, `fig:architecture`, `tab:results`, and `eq:balance`. Reconcile every referenced object with the object inventory and final source.

Audit:

- missing, duplicate, or stale labels;
- undefined `\ref`, `\pageref`, `\eqref`, and `\cite` targets;
- captions detached from objects;
- source page references invalidated by repagination;
- appendix, theorem, figure, table, and equation numbering;
- generated lists inconsistent with final headings or captions.

Prefer structural references over source page numbers after semantic reflow unless exact pagination is an explicit goal.

## Batch Integration

Reconstruct by chapter, section, or high-risk object batch. After each batch:

1. Validate and merge the batch's compact page-IR shards through the single integration point. Read the summary in `batch-manifest.json`; open a detail artifact only for blockers, uncertainties, cross-page continuity, or integration failures.
2. Merge page evidence into semantic source, joining cross-page blocks before emitting final fragments.
3. Reconcile route, document-model, object, and batch-ledger statuses.
4. Compile under safe settings.
5. Inspect relevant log findings and rendered pages.
6. Record the completed batch and next concrete action.

Keep batches small enough that regressions can be attributed to recent changes. A page or region shard may contain a local `.tex` fragment, but it must not be treated as a semantic page boundary or copied directly into `main.tex` without continuity and object reconciliation. The main agent owns shared files, merges, compilation, and final decisions. Subagents may return bounded transcripts, page-IR artifacts, or findings, but should not independently edit shared source or state.

Use `scripts/merge_shards.py` to enforce source identity, non-overlapping page ownership, artifact hashes, snapshot compatibility, compact-summary consistency, usage-field validity, and idempotent retries before a shard changes the batch ledger. Run `scripts/report_worker_usage.py` to inspect batch cost data. Compile only after the merged source is updated; do not run concurrent builds against shared auxiliary files or the final PDF.

## Durable Records

For writable resumable work, keep `conversion-state.md` concise and factual. Record canonical fields, source identity, current phase, completed checkpoints, latest successful command, active files, next action, and specific blockers. Use `conversion-notes.md` for evidence, decisions, substitutions, approximations, commands, review results, and public sources.

Update state only after the corresponding file, log, manifest, or PDF exists. Preserve user edits. If state and filesystem disagree, inspect reality first and correct the state rather than repeating completed work.
