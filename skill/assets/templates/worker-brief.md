# Worker Brief (compact standing orders)

Copy or point workers at this file path only. Do not paste full skill references into worker prompts.

## Role

- You own only the listed pages/regions for this batch.
- Write a page-IR v2 shard under the given output path.
- Do not edit `main.tex`, shared chapters, inventories, conversion-state, notes, or Goal status.

## Output

- Schema: `assets/schemas/page-ir.schema.json` (path relative to skill root or project copy).
- Keep `worker_summary.text` ≤ 1200 characters.
- Put detailed blocks, objects, continuity, and uncertainties in a hashed `detail_artifact` on disk.
- Report proposed status, blockers, and cross-page continuity hints for the parent.

## Evidence

- Open only evidence paths for owned pages (and optional ±1 neighbor if listed).
- Prefer paths over pasted content; do not request whole-project dumps.

## Figures

- Prefer original PDF assets: `pdfimages` / tight crop + `\includegraphics` mapping notes.
- Do not redraw source figures in TikZ/PGFPlots unless extraction is impossible and noted.

## Text / Math / Tables

- Rebuild legible body text and math semantically.
- Rebuild legible data tables as LaTeX tables; pictorial tables may be crops.
- Do not invent unreadable content; mark uncertainties and blockers.

## Stop Conditions For This Worker

- Unreadable required region → blocker with page and reason.
- Ownership conflict or missing evidence path → fail the shard with a clear error, do not guess.
