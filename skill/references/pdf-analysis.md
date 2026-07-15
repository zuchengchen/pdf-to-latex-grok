# PDF Analysis

Use this reference for source-aware inspection, evidence planning, source identity, and semantic coverage. Analyze enough to choose a reliable reconstruction route; do not reverse-engineer PDF drawing commands.

## Contents

- First Pass
- Source Identity
- Source Classification
- Book Signals
- Evidence Generation
- Reading Order And Objects
- Route Map
- Source Completeness
- Long Documents
- Analysis Output

## First Pass

1. Confirm the PDF and target paths. Inspect an existing target before creating or replacing anything.
2. Set `SKILL_DIR` to the directory containing `SKILL.md` before invoking helpers.
3. Check available capabilities such as `pdfinfo`, `pdftoppm` or `mutool`, `pdftotext`, optional `pdfimages` for figure extract, and XeLaTeX. Do not invoke OCR.
4. Read metadata and page count when possible. Record page size, orientation, encryption, and mixed-size evidence.
5. Sample the digital text layer and representative rendered pages. Include the first page, an early body page, a middle page, the final page, and visible formula-, table-, appendix-, or reference-heavy pages.
6. Set `Source kind`, applicable `Document traits`, `Delivery level`, `Execution mode`, and `Verification scope` using `workflow-contract.json`.
7. Estimate unreadable or visually complex regions, useful batch size, first milestone, and required tools before broad work. After the scaffold and page-bounded text evidence exist, run:

   ```bash
   python3 "$SKILL_DIR/scripts/plan_batches.py" SOURCE.pdf PROJECT_DIR \
     --source-kind digital --traits none
   ```

   Treat `PROJECT_DIR/work/page-index.json` as a source-bound routing artifact. It uses local `pdftotext` statistics only; it does not replace visual inspection or invoke OCR.

Keep pre-scaffold work small. Its purpose is to choose a safe target and viable route. Write durable findings after the scaffold exists, except for a read-only `review`, which keeps all working notes outside the project.

## Source Identity

Bind resumable source-aware work to content, not only a pathname. Record:

```text
Source PDF path:
Source PDF SHA-256:
Source PDF size bytes:
Source PDF page count:
```

Recheck identity before resume, render, text extraction, publication review, or source comparison.

- If the source moved but the digest matches, update the path and continue. For an existing source-aware scaffold, pass the new path through `"$SKILL_DIR/scripts/ensure_latex_project.sh" PROJECT_DIR --source-pdf MOVED.pdf` together with the recorded canonical context so state, records, and evidence manifests are rebound transactionally.
- If the digest changes, stop before reusing evidence. Require explicit acceptance of the new source; use `--accept-source-change` only after that approval, then invalidate and regenerate affected page evidence, text evidence, manifests, inventories, and fidelity status.
- If a manifest digest or page count disagrees with the bound source, treat the evidence as stale.

Do not silently bind an existing project to a different PDF. Initializers should be idempotent only when source identity and canonical workflow fields match.

## Source Classification

Use one source kind:

- `digital`: selectable text is mostly usable, though visual correction remains necessary.
- `scanned`: pages are image-based or the text layer is unusable.
- `mixed`: route differs across pages or regions.
- `unknown`: evidence is insufficient. Do not keep this value for completed source-aware work.

Add independent traits only when evidence supports them:

- `book`: established by the signals below.
- `long-document`: requires batching and durable restart state.
- `math-heavy`: formulas require systematic inventory and review.
- `encoded-math`: glyph mappings or extraction damage make the text layer unreliable for math.
- `cjk`: CJK language, fonts, line breaking, or punctuation need explicit handling.
- `visual-complex`: reading order or objects cannot be reconstructed reliably from text extraction alone.

For scanned, mixed, encoded, damaged, or visually complex regions, use Grok visual reading from rendered pages. `pdftotext` is optional evidence for digital regions, never authoritative transcription and never OCR.

## Book Signals

Set the `book` trait when the document is explicitly a book, textbook, monograph, thesis, dissertation, or proceedings volume. Otherwise require multiple structural signals, such as:

- parts or chapters;
- front/main/back matter transitions;
- chapter-scoped numbering;
- recto/verso page style or running heads;
- Roman-numbered front matter;
- several back-matter classes;
- long cross-chapter references.

A bibliography, references section, appendix, table of contents, or long page count alone is not enough. Read `book-production.md` only after the trait is established.

## Evidence Generation

Store durable evidence under the project for resumable work:

```text
evidence/
  source-pages/
  text-layer/
  crops/
```

Render PNG by default. Create single-page PDFs only when explicitly useful and requested through `--single-page-pdf`. For large documents, render representative pages first and later render bounded batches.

Use helper paths through `SKILL_DIR`:

```bash
"$SKILL_DIR/scripts/render_pdf_pages.sh" --help
"$SKILL_DIR/scripts/extract_text_pages.sh" --help
```

Evidence generation must be transactional:

1. Validate the source, page selection, and required tools.
2. Write into a staging directory on the target filesystem.
3. Verify every expected output exists and is nonempty.
4. Replace only the selected outputs after full success.
5. On failure, delete staging and preserve previous evidence.

Treat `--force` as permission to replace after success, never permission to delete first. Never normalize or rewrite pages outside the current selection.

Maintain machine-readable manifests for rendered and extracted evidence. Include source digest, page count, selected pages, resolution or extraction mode, tool identity, and generation time. Keep manifests consistent with actual files.

For resumable or goal-backed parallel work, keep worker output separate from final source. Store an `assets/schemas/page-ir.schema.json`-conforming shard under `work/shards/` with non-overlapping owned pages, read-only context pages, source identity, snapshot hashes, artifact paths, and uncertainties. Register successful shards through `scripts/merge_shards.py`; do not let workers update the shared manifest or state directly.

## Reading Order And Objects

Determine logical reading order before final LaTeX:

- columns, sidebars, footnotes, floats, captions, and continuation across pages;
- headings, parts, chapters, sections, appendices, and generated lists;
- repeated headers, footers, page numbers, watermarks, and marginalia;
- formulas, theorem-like blocks, figures, tables, citations, bibliography, glossary, and index.

Usually omit repeated navigation furniture from semantic body text. Preserve marginal or decorative content only when it conveys meaning.

For figures, prefer genuine extractable assets from the source PDF (embedded image extract, then tight crop). Classify each object as: embedded extract, crop, blocker, or—only as last resort—semantic recreation. Do not plan TikZ/LaTeX redraws of source figures by default. Rebuild legible **tables** as LaTeX tables (data, not pictorial figures). Read formulas visually and route systematic math work through `math-polish.md`.

## Route Map

For broad source-aware conversion, maintain a compact page or region route map. Each entry should identify:

```text
Page or region:
Route: digital-text | visual-transcription | asset-crop | semantic-object | blocked
Evidence:
Batch:
Shard:
Owner:
Target source file:
Reconstruction status:
Compile check:
Visual review:
Uncertainty or next action:
```

Use lifecycle statuses, compile values, and visual-review values exactly as defined by `workflow-contract.json`. Do not use `compiled` or `visually reviewed` as reconstruction statuses.

Digital prose may use page-bounded text evidence plus visual correction. Scanned and damaged regions require visual transcription. Encoded math uses visual evidence plus a glyph map. A visually unreadable required region becomes a localized blocker; do not replace it with an ordinary page screenshot.

## Source Completeness

Run a completeness audit before broad publication drafting and again before final source-aware delivery:

- Every meaningful page or region has a route, owner, target, and status.
- Every worker-owned page set has one shard owner, a source-identity match, and a merge record; context pages do not create a second owner.
- Every required figure, table, formula group, citation block, appendix, front/back-matter item, glossary/index item, and unresolved visual region appears in an inventory or documented compact equivalent.
- The document model covers the routed content without duplicating page fragments.
- Every blocked item names source evidence, reason, and concrete next action.
- Every omission records why it is allowed by the delivery contract.
- Compile and visual-review fields reflect actual checks.

Do not mark source-aware completion while required content remains unowned, pending, in progress, or blocked.

## Long Documents

Use `resumable` or `goal-backed` execution for work that cannot reliably finish in one turn. Batch by structural boundary when possible. **Prefer spawning subagents for each planned batch** so the parent does not hold all page content.

- Use roughly 5-10 pages for scanned, formula-heavy, table-heavy, or visually complex batches.
- Use roughly 20-50 pages for mostly digital prose after page-bounded evidence exists.
- Use one-page or one-region shards only for high-risk pages; use a bounded concurrent worker pool instead of one long-lived agent per source page or one parent-only mega-pass.
- Use the generated plan as the default routing policy: ordinary digital prose is batched at roughly 20-50 pages, complex pages at roughly 5-10 pages, and critical or image-only pages at one page or one region. Override the batch sizes only when evidence shows that a different boundary is safer.
- Give each worker a minimal packet (owned pages, evidence paths, digest, hashes, output path)—not the full skill, Goal, notes, or whole-project text.
- Update source identity, manifest coverage, batch ownership, shard hashes, completed ranges, blockers, and the next concrete batch after each milestone.
- Sample every structural area during review, not only early pages.

Goal mode may improve continuity, but its availability does not change delivery quality. A resumable state file remains the authoritative restart point.

## Analysis Output

For writable resumable work, leave enough durable information to reconstruct the decision:

- canonical workflow fields and source identity;
- metadata, page-size plan, source classification, traits, and tool capabilities;
- representative-page findings and evidence manifests;
- route map, reading order, object plan, and document model;
- batch plan, first milestone, blockers, and next action;
- derivation labels for PDF evidence, visual inference, approximation, and public metadata.

For `review`, return these findings to the user without changing project files.
