# Math Polish

Use this reference for `math-heavy` or `encoded-math` work and whenever included source contains rough glyph or display-math artifacts. A compiling PDF with unresolved readable math is still a draft.

## Contents

- Blocking Artifacts
- Math Tracking
- Artifact Census
- Reconstruction Workflow
- Visual Identification
- Environment Selection
- Math Review

## Blocking Artifacts

Unless the user explicitly selected rough draft or approved a localized unresolved item, final included source must not contain:

- `\pdfglyph{...}` or equivalent raw-glyph macros;
- `extracteddisplay` or placeholder display wrappers;
- raw encoded math copied from a text layer;
- `TODO math`, `unresolved glyph`, `raw glyph`, or equivalent placeholders;
- legible display equations left as plain paragraphs or transcript text;
- ordinary page images used to hide unreconstructed formulas.

Scratch transcripts and evidence may retain extraction artifacts. Artifact scans should cover final included LaTeX and bibliography source while excluding evidence, transcripts, logs, and temporary build output.

## Math Tracking

For systematic math work, maintain `math-inventory.md` and `glyph-map.md` as required by `workflow-contract.json`.

A math item should record:

```text
ID or visible number:
Source page and evidence:
Surrounding text:
Target source file:
Reconstruction status:
Compile check:
Visual review:
Labels and references:
Uncertainty or blocker:
```

Use contract lifecycle values for reconstruction status. Keep compile and visual review separate; do not encode `compiled` or `visually reviewed` as reconstruction states.

A glyph decision should record:

```text
Raw marker or recurring pattern:
Visible symbol:
LaTeX replacement:
Source pages:
Context and scope:
Confidence:
Decision status:
```

Do not perform a global replacement until visual evidence proves the marker is context-invariant. One encoded glyph may represent different symbols in different fonts or formula contexts.

## Artifact Census

Count rough artifacts before editing and after every cleanup batch. Prefer the bundled scanner:

```bash
"$SKILL_DIR/scripts/check_latex_artifacts.sh" PROJECT_DIR
```

Also search for project-specific placeholder macros, comments, or environments discovered during analysis. Record counts and affected files. A lower count is progress; only a clean applicable scan supports completion.

Treat `Missing character:` build findings as content-loss errors, even if source scans are clean. Verify CJK, Greek, mathematical alphabets, relation symbols, and uncommon operators in rendered output.

## Reconstruction Workflow

1. Inventory display equations, inline hotspots, equation numbers, glyph families, theorem-like blocks, and cross-references.
2. Render formula regions at sufficient resolution. Use neighboring prose and repeated notation to constrain interpretation.
3. Resolve high-confidence recurring glyphs in bounded batches.
4. Replace placeholder displays with semantic math environments.
5. Preserve equation punctuation, alignment, numbering, labels, and textual dependencies.
6. Compile after each batch under safe settings.
7. Render and compare affected pages against source evidence.
8. Update inventory, glyph decisions, artifact counts, and remaining uncertainty.

Work chapter-by-chapter or notation-family-by-notation-family for long documents. Keep edits small enough to isolate a bad replacement.

## Visual Identification

Identify a symbol from multiple signals:

- shape in high-resolution source evidence;
- formula grammar and surrounding prose;
- repeated use elsewhere in the document;
- visible equation number and cross-reference;
- notation lists, definitions, units, and domain conventions;
- public versions or standard formulas when clearly identifiable.

Record public evidence separately. Do not silently substitute a plausible symbol when the source remains ambiguous.

If a required symbol remains unreadable after higher-resolution inspection and contextual comparison, create a localized blocker with the exact page, region, candidate interpretations, and user-facing question. Do not block an entire document for an optional or explicitly omittable symbol.

## Environment Selection

Choose the smallest semantic environment that preserves source intent:

- inline math for short expressions in prose;
- `equation` for one numbered display;
- `align` for aligned relations or multi-line derivations;
- `gather` for independent centered lines;
- `multline` for one long expression;
- `split` within a numbered equation;
- `cases` for piecewise definitions;
- matrices, arrays, theorem, definition, lemma, proposition, proof, or exercise environments when structurally visible.

Avoid `$$`, manual equation numbers, and alignment based on spaces. Use `\label`, `\ref`, and `\eqref` consistently. Preserve visible chapter-scoped numbering through class and counter strategy rather than hard-coded labels.

## Math Review

Before clean-semantic delivery, confirm:

- major formulas are present and semantic;
- extracted superscripts, subscripts, fractions, delimiters, and operators were visually checked;
- equation numbers and references remain coherent;
- no broad rough artifact remains in included source;
- affected pages compile and render readably;
- each required inventory item is rebuilt and reviewed or has a specific blocker;
- glyph-map replacements have evidence and bounded scope.

Publication polish also requires an independent math/object reviewer, a clean artifact scan, missing-character-free build findings, representative source comparison when source-aware, and a clean-environment rebuild. `not-applicable` is valid only when math is absent, not when visible math was skipped.
