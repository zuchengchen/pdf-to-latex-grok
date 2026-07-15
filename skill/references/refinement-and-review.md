# Refinement And Review

Use this reference to improve a PDF-derived LaTeX project, conduct a strictly read-only review, run reviewer gates, and decide whether the selected delivery contract is complete.

## Contents

- Authorization Boundary
- Delivery Levels
- Refinement Loop
- Focused Passes
- Issue Priority
- Reviewer Gates
- Visual And Source Review
- Workflow And Outcome
- Acceptance Checklist
- Delivery Report

## Authorization Boundary

Honor `Operation` before doing anything else.

- `review` is strictly read-only. Do not edit source, update state or notes, create inventories, run formatters in place, or leave logs and auxiliary files in the project. Copy the project to a temporary directory for compilation, rendering, extraction, or experiments. Delete temporary artifacts before returning the review.
- `repair` permits only the requested bounded changes and proportionate verification.
- `refine` permits broad quality changes within the project and requires durable state when resumable.
- `resume` continues only after source identity and state are verified.

Do not turn a review into a repair because a fix appears obvious. If the user later authorizes changes, reclassify the operation and state the new scope.

Review can be `source-aware` or `project-only`. Project-only review may assess compile health, semantics, maintainability, typography, references, and internal consistency, but must not claim fidelity to an unavailable source.

## Delivery Levels

Use the exact canonical value:

- `rough-draft`: use only when the user requests a partial, fast, or preliminary result. Compile when practical and list unfinished clean-semantic checks.
- `clean-semantic`: default for ordinary complete work. Require editable semantic source, successful compilation, main-content coverage, transcript cleanup, object and structure checks, and representative visual review.
- `publication-polish`: require a recorded acceptance contract, complete applicable inventories, focused production passes, independent reviewer gates, strict artifact and workflow checks, dependency closure, clean-environment rebuild, and source comparison when verification is source-aware.

Do not silently lower delivery. If the requested standard cannot be met, continue fixing what is reasonably resolvable, then either report `blocked` or obtain explicit approval for a downgrade. Record the prior level, accepted level, reason, and skipped gates. A downgrade outcome is not ordinary completion at the original level.

## Refinement Loop

1. Confirm operation, delivery, verification scope, source identity when applicable, and user-stated issues.
2. For writable work, read state and notes; verify them against source files, logs, manifests, and compiled output.
3. Read `security-and-build.md`, then compile safely. For review, compile only the temporary copy.
4. Fix hard build, content-loss, and missing-dependency errors before visual polish.
5. Apply one focused pass at a time. Recompile and inspect the affected pages after each high-risk batch.
6. Reconcile final source with the route map, document model, object inventory, math files, and book structure that apply.
7. Run reviewer, workflow, artifact, output, dependency, and clean-build checks required by the delivery level.
8. Repeat until all required checks pass or a specific blocker remains.

The first compiling PDF is a checkpoint. Do not deliver it as clean semantic or publication polish without the applicable refinement floor.

## Focused Passes

### Transcript And Structure

- Join cross-page paragraphs and remove transcript boundaries.
- Remove repeated headers, footers, page numbers, duplicated headings, and extraction debris.
- Restore semantic titles, abstracts, sections, lists, footnotes, appendices, and citations.
- Reconcile reading order and document-model coverage.

### LaTeX Idiom And Objects

- Replace visual formatting hacks with semantic environments.
- Restore tables, figures, captions, labels, units, notes, and cross-references.
- Fix missing assets and project-relative paths.
- Keep genuine visual assets extracted from the source PDF; do not replace source figures with TikZ or other LaTeX redraws during polish.
- Replace legible text or data-table screenshots with semantic source; leave pictorial figures as image assets.

### Math

- Rebuild formulas with standard environments and visible numbering.
- Clear raw glyph, placeholder display, and extraction artifacts from final included source.
- Reconcile formula and glyph tracking with rendered high-risk pages.
- Use `math-polish.md` for systematic work.

### Book Production

- Preserve front, main, and back matter boundaries.
- Reconcile chapters, appendices, generated lists, bibliography, index, glossary, numbering, and cross-references.
- Inspect early, middle, and late structural areas.
- Use `book-production.md` when the `book` trait is established.

### Typography And Layout

- Match the recorded paper and geometry strategy.
- Fix clipping, unreadable type, severe overfull boxes, blank pages, excessive whitespace, poor float placement, and table overflow.
- Tune headings, paragraph flow, object sizes, and page breaks without absolute page tracing.
- Review CJK fonts, punctuation, line breaking, and missing-character findings when applicable.

### Final Cleanup

- Remove stale inputs, unused labels, duplicate macros, temporary comments, and resolved placeholders.
- Preserve concise comments for genuine source uncertainty.
- Confirm included source is maintainable and free of generated evidence artifacts.

For a bounded repair, run only relevant passes plus regression checks. For clean semantic work, complete at least transcript/structure, idiom/object, typography, visual, and build-reproducibility checks. Add all applicable book and math passes. Publication polish also requires the gates below.

## Issue Priority

Resolve findings in this order:

1. Unsafe build requirements or unauthorized execution capability.
2. Compile failure, missing output, missing character, missing source, or external project dependency.
3. Missing, duplicated, reordered, or unreadable required content.
4. Broken document hierarchy, page-route coverage, or document-model ownership.
5. Math, table, figure, caption, citation, bibliography, and cross-reference defects.
6. Book apparatus, numbering, generated-list, appendix, index, or glossary defects.
7. Raw transcript, full-page-placeholder, encoded-glyph, and page-boundary artifacts.
8. Clipping, blank pages, severe overflow, unreadable objects, and bad float placement.
9. Non-blocking warnings and cosmetic differences.

Do not spend time on harmless warning cleanup while semantic or content-loss defects remain.

## Reviewer Gates

For publication polish, run a midpoint review after route mapping, production specification, completeness audit, skeleton compile, and asset discovery, but before most final drafting. Look for:

- missing or unowned source regions;
- an unsuitable class, package, font, or object strategy;
- incomplete book, math, bibliography, index, or glossary planning;
- unsafe or unavailable build requirements;
- a mismatch between the delivery contract and planned architecture;
- blockers that require user input before more work is invested.

After drafting and focused passes, conduct separate final reviews:

- `structure/content`: reading order, completeness, hierarchy, duplication, document model, and book matter.
- `math/object`: formulas, theorem-like material, tables, figures, captions, citations, labels, and inventory coverage.
- `build/layout`: safe compile findings, missing assets, references, fonts, clipping, blank pages, floats, readability, dependency closure, and clean rebuild.

Use subagents for bounded independent reviews or isolated page-IR reconstruction when useful. Give reconstruction workers only their non-overlapping pages or regions, read-only neighbor context, raw evidence, the delivery contract, and the current snapshot hashes; give reviewers raw evidence and the delivery contract, not expected findings. Workers return shard artifacts or findings only; the main agent owns shard merging, edits, compilation, state, and the completion decision.

Use a concrete finding format:

```text
Gate:
Severity: error | warning
Evidence: file, page, object, log line, or rendered page
Finding:
Impact:
Required action:
```

Report a gate as passed only when it has no unresolved required finding. Use `not-applicable` only where the contract permits and the source truly lacks that category. Unreadable or skipped visible content is blocked, not not-applicable.

## Visual And Source Review

Render representative rebuilt pages and inspect the actual pixels, not only command success. Verify:

- pages are nonblank, readable, and unclipped;
- hierarchy, columns, figures, tables, formulas, and captions are coherent;
- raw transcript boundaries and repeated page furniture are gone;
- no ordinary source page is embedded as a full-page shortcut;
- CJK and formula-heavy pages retain visible characters and symbols;
- book front matter, chapters, appendices, bibliography, and index/glossary areas are coherent when present;
- key high-risk objects render at useful size near their references.

For `source-aware` work, compare source and rebuilt evidence for semantic coverage, object identity, math, and broad layout. Do not require identical line breaks or pagination unless the acceptance contract explicitly requires them.

For `project-only` work, inspect internal consistency and output quality only. State `Source fidelity: not verified; source unavailable` or the equivalent. If source fidelity is a user requirement, the outcome is blocked.

## Workflow And Outcome

For writable publication work, run the deterministic workflow checker through `SKILL_DIR`:

```bash
"$SKILL_DIR/scripts/check_workflow_gates.sh" PROJECT_DIR
```

The checker validates canonical fields, required files, gate values, blockers, and obvious unfinished statuses. It does not replace semantic review. Honor the exit meanings in `workflow-contract.json`; a valid blocked record must remain distinguishable from success.

Run the artifact and strict publication helpers as applicable:

```bash
"$SKILL_DIR/scripts/check_latex_artifacts.sh" PROJECT_DIR
"$SKILL_DIR/scripts/publication_gate.sh" PROJECT_DIR main.tex
```

Use outcomes consistently:

- `complete`: every required gate passes for the selected scope and no required item is pending, in progress, or blocked.
- `blocked`: state is valid but a specific required item cannot be resolved; include reason and next action.
- `downgraded`: the user explicitly accepted a lower delivery contract and its required gates pass.
- `in-progress`: work remains and has a concrete next action.

Missing canonical fields, `unknown` final classification, malformed state, or a silently skipped gate is validation failure, not a blocker and not completion.

## Acceptance Checklist

Before clean-semantic or publication delivery, confirm the applicable items:

- Latest safe compile succeeds and produces the expected nonempty PDF.
- Missing-character, font, file, command, package, reference, and citation errors are resolved.
- Final included source contains no broad transcript, full-page-image, raw glyph, or placeholder math artifacts.
- Required source regions and objects have complete lifecycle ownership.
- Document model, source, inventories, and generated structure agree.
- User edits and project-local assets are preserved.
- Representative output pages are readable and nonblank.
- High-risk book, math, table, figure, CJK, and visually complex areas were reviewed.
- Required workflow and artifact checks pass.
- Publication polish additionally passes strict findings, dependency closure, clean-environment rebuild, final reviewer gates, and source comparison when source-aware.
- State and notes match actual files and checks for writable resumable work.
- Review left the project byte-for-byte untouched except for external filesystem metadata outside Grok's control.

Do not claim publication completion when render or clean-build checks were skipped. Do not treat a documented blocker as a successful gate.

## Delivery Report

Lead with the outcome. Name:

- operation, delivery level, verification scope, and outcome;
- project and compiled PDF paths when applicable;
- source-fidelity status;
- compile, artifact, workflow, dependency, clean-build, text, and visual checks actually run;
- material fixes or findings;
- remaining blockers, approved approximations, or downgraded requirements;
- the next action for in-progress or blocked work.

For review, report findings in severity order and do not imply that fixes were applied.
