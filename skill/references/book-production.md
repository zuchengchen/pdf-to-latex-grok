# Book Production

Use this reference only after the `book` trait is established. It adds long-document and book-apparatus guidance without redefining the workflow contract or general acceptance gates.

## Contents

- Establish The Trait
- Book Model
- Class And File Strategy
- Front Matter
- Main Matter
- Back Matter
- Generated Apparatus
- Cross-Reference Audit
- Book Review

## Establish The Trait

Treat an explicitly identified book, textbook, monograph, thesis, dissertation, or proceedings volume as book work. Otherwise require several signals:

- parts or chapters;
- distinct front, main, and back matter;
- chapter-scoped figure, table, equation, theorem, example, or exercise numbering;
- Roman-numbered front matter;
- recto/verso layout or running heads;
- multiple back-matter classes;
- long chapter-to-chapter reference chains.

A bibliography, references section, appendix, table of contents, or long page count alone does not establish the trait.

## Book Model

Extend the document model with:

```text
Book type and class target:
Front matter and order:
Main-matter parts and chapters:
Back matter and order:
Numbering policy:
Generated-list policy:
Bibliography policy:
Index and glossary policy:
Cross-reference policy:
File ownership:
Unresolved book objects:
```

Map source pages to front, main, and back matter before final drafting. Use stable source files such as `frontmatter/preface.tex`, `chapters/03-methods.tex`, and `backmatter/appendix-a.tex` when they improve maintainability. Short theses or manuals may use fewer files if structural ownership remains clear.

## Class And File Strategy

- Use `book` for ordinary books and monographs when no stronger class is required.
- Use `report` for thesis-like or technical structures that do not need book matter switches.
- Use an institution-specific class only when the user supplies it or it already belongs to the project.
- Use `ctexbook`, `xeCJK`, or another CJK strategy only when language and installed fonts support it.
- Prefer portable class and package choices over speculative production frameworks.

For a true book class, use semantic matter transitions when appropriate:

```tex
\frontmatter
\tableofcontents

\mainmatter
\input{chapters/01-introduction}

\appendix
\input{backmatter/appendix-a}

\backmatter
```

Add `\listoffigures`, `\listoftables`, bibliography, index, or glossary commands only when corresponding content and build tooling exist. Compile the structural skeleton before drafting most chapters.

## Front Matter

Preserve visible front matter semantically:

- half title, title page, subtitle, authors, editors, affiliations, publisher, edition, and date;
- copyright, ISBN, license, series, printing, and edition notes;
- dedication, epigraph, foreword, preface, acknowledgements, abstract, and notation list;
- table of contents, list of figures, and list of tables.

Prefer generated contents and lists when final headings and captions support them. Do not hand-type a static source TOC to imitate source pagination. Record intentional changes to page numbering.

## Main Matter

- Preserve parts, chapters, sections, examples, exercises, summaries, and theorem-like structures.
- Use repeated semantic environments for theorem, definition, lemma, proposition, corollary, proof, example, and exercise when the source supports them.
- Preserve chapter-scoped numbering and visible labels.
- Remove running heads and page numbers from body text; implement page style only when it adds value.
- Preserve meaningful footnotes, endnotes, and sidebars.

For proceedings, keep editor-level front matter and per-paper chapter boundaries. Preserve each paper's title, authors, abstract, local sections, references, and appendices where visible.

Batch long reconstruction by structural boundary. Update durable state after each chapter or apparatus group and compile before proceeding to the next high-risk batch.

## Back Matter

- Use `\appendix` or class-equivalent behavior and preserve appendix identifiers.
- Preserve bibliography identity and citation associations. Keep per-chapter bibliographies distinct when the source does.
- Rebuild visible glossary, notation, index, colophon, biography, and edition notes without inventing entries.
- Use semantic manual lists when index or glossary tooling is unavailable; record the limitation.

Public lookup may correct identifiable DOI, arXiv, author, title, venue, or BibTeX metadata. Label public metadata separately from PDF-derived content.

## Generated Apparatus

Generated apparatus is valid only when its underlying structure exists:

- A table of contents must agree with final parts, chapters, and sections.
- Lists of figures and tables must agree with visible objects and captions.
- Bibliography commands require data and a supported build stage.
- Index terms must derive from a visible source index or explicit user direction.
- Glossary entries must preserve visible terms, definitions, symbols, units, and first-use context.

Do not use a generated list as the only proof that source objects were reconstructed. Reconcile it with the object inventory and rendered PDF.

## Cross-Reference Audit

Audit:

- chapters, sections, appendices, figures, tables, equations, theorem-like blocks, examples, and exercises;
- citations, bibliography entries, footnotes, generated lists, index, and glossary;
- undefined, duplicate, and stale labels;
- source wording such as "see page" that became false after repagination;
- numbering after matter switches and `\appendix`.

When exact source page references cannot survive semantic reflow, prefer chapter, section, figure, table, or equation references and document the change.

## Book Review

Add these focused passes to the general refinement workflow:

1. Structure: verify front/main/back boundaries and correct order.
2. Numbering: reconcile chapter-scoped objects and appendices.
3. Generated apparatus: rebuild and inspect contents, lists, bibliography, index, and glossary.
4. Cross-references: clear undefined, stale, and source-page-dependent references.
5. Long-document typography: inspect chapter openings, blank pages, running heads, long tables, large floats, and severe overflow.
6. Clean build: verify all generated apparatus from a clean environment without stale auxiliary files.

Sample every structural area: front matter, early and middle chapters, dense object pages, late chapters, appendices, bibliography, and index or glossary when present. Publication completion requires maintainable semantic structure, coherent apparatus, resolved build stages, and no required book object left pending or blocked.
