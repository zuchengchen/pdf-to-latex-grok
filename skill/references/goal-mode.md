# Continuity: Resumable Primary, Goal Opportunistic

Continuity is project-file-first. Keep `conversion-state.md` authoritative for durable progress; Goal state never replaces project state, evidence, or verification gates. Execution mode controls continuity only, never delivery quality.

On Grok, agent tools cannot create a Goal. `update_goal` reports progress only when a Goal is already active. Users may start Goal mode with `/goal`, but that is optional multi-session pinning, not a gate to begin work.

## Auto-Start Rule (Hard)

Prefer auto-start **run-to-completion**: when the user issues a complete `/pdf-to-latex` (or equivalent) task request, begin reconstruction immediately and keep going until a terminal outcome.

**Never block on Goal startup.** Do not pause, yield, or wait for the user to run `/goal` before scaffolding, evidence, workers, compilation, or the next checkpoint. Do not treat a long `/goal` objective template as the default next user action. Do not pause for the user to say 继续 / continue between batches or stages.

Do not ask for separate Goal confirmation.

## Mode Selection

Choose `one-turn` only for work that is genuinely bounded and can finish now: localized `repair`, ordinary read-only `review`, initial triage without reconstruction, or an explicitly requested one-turn rough draft. Reclassify a repair that expands into broad project improvement as `refine`.

For full `convert`, broad `resume` or `refine`, writable `publication-polish`, and multi-batch work:

1. Check current Goal state when Goal tools are available.
2. If an unfinished Goal matches the same PDF-derived task, continue it as `goal-backed` and report progress with `update_goal` when useful.
3. Else if the host can create or activate a Goal without user slash-command ceremony, do so and record `goal-backed`.
4. Else use `resumable` by default and start work now. On Grok this is the normal path for a fresh convert.
5. Fall back to `resumable` when Goal tools are unavailable, startup is disallowed, create is impossible, or an activation attempt fails—without lowering the delivery level.

Record `Execution mode: goal-backed` only after a matching Goal is actually active. Until then record `resumable` and keep working.

Do not set a token budget unless the user explicitly requested one.

An unfinished **unrelated** Goal is a real user-decision boundary: ask which objective should remain active instead of replacing it silently. Goal attachment must never authorize project overwrite, source replacement, unsafe build capabilities, a delivery downgrade, or a material approximation.

## Optional Goal Pinning (Non-Blocking)

If a multi-session pin would help and no matching Goal is active, you may mention once that the user can pin progress with:

```text
/goal Use /pdf-to-latex to OPERATION SOURCE into TARGET at DELIVERY_LEVEL. Treat TARGET/conversion-state.md as the durable source of progress. Run until complete, approved downgrade, or true blocker without waiting for continue prompts.
```

Keep any such tip optional, brief, and non-blocking. Never require it. Never wait for it. Prefer finishing the conversion over discussing Goal mode.

When a matching Goal is active, use an objective equivalent to:

```text
Use /pdf-to-latex to OPERATION SOURCE into TARGET at DELIVERY_LEVEL. Treat TARGET/conversion-state.md as the durable source of progress. Run to completion in one continuous loop: verify source identity, follow the recorded Next action, dispatch remaining batches, preserve user edits, complete the gates derived from workflow-contract.json, and run scripts/workflow_contract.py to validate the project. Do not stop for user continue/继续 prompts. Continue automatically until the project reaches a valid complete outcome, a user-approved downgraded outcome, or a true blocker that requires user action.
```

## Parallel Worker Protocol

### Prefer Subagents (Token-Saving Default)

For multi-page `convert`, broad `resume` / `refine`, and other batchable reconstruction, **prefer `spawn_subagent` workers** whenever Grok subagents are enabled. Do not keep page-IR reconstruction inside the parent context when batches exist. Parent-only reconstruction is reserved for true `one-turn` local repair, tiny one-page fixes, or when subagents are disabled.

Keep one parent controller (the main agent session, optionally with an active Goal). Do not create a Goal per page. The parent owns `conversion-state.md`, `conversion-notes.md`, `batch-manifest.json`, shared LaTeX source, compilation, merge, and the terminal outcome.

Run `scripts/plan_batches.py` once source text-layer evidence exists and dispatch every planned batch from `work/page-index.json`. Prefer a **bounded concurrent pool** of workers (spawn several in background, merge as they finish) over one long-lived mega-agent. Do not default to one worker per page for ordinary prose; use the planner batch sizes. Use one-page or one-region workers only for high-risk pages.

### Minimal Worker Context (Hard)

Launch each worker with Grok `spawn_subagent` in an **isolated context**. Omit child `model` overrides when inheritance is available. Pass only a **compact context packet**—nothing else.

**Include (and only these, as short bullets or a tiny JSON block):**

- batch id and owned page/region numbers;
- source PDF path + SHA-256 digest + page count;
- read-only neighbor page numbers (at most ±1 page, or omit if not needed);
- absolute or project-relative paths to evidence for owned pages only (renders, text extracts);
- style/document-IR **snapshot hashes** (not full IR dumps);
- route labels for owned pages;
- shard output directory / expected shard path;
- pointer to `assets/schemas/page-ir.schema.json` (path only);
- 5–15 line standing orders: write shard only; page-IR v2; no shared edits; prefer original figure extract/crop; max summary length.

**Exclude from every worker prompt (do not paste):**

- full `SKILL.md`, reference manuals, or long workflow essays;
- full Goal objective, chat history, or parent transcript;
- entire `conversion-notes.md`, full inventories, or full document IR;
- unrelated chapters, full `main.tex`, or whole-project tree listings;
- all-page evidence dumps; only owned (+ optional neighbor) paths;
- large base64 images; workers open image **paths** themselves;
- prior batch transcripts or other workers' detail artifacts.

Prefer **paths over content**: tell the worker where files are; let it read only what it needs. Prefer **hashes and page lists over prose**. Cap the worker prompt body so the packet stays small (aim well under a few thousand tokens of instruction text excluding tool-fetched files).

Point workers at `assets/templates/worker-brief.md` (or a project copy under `work/worker-brief.md`) for standing orders instead of pasting long manuals. Packet = page lists + paths + hashes + brief path.

Workers write only their own shard under `work/shards/` or return a compact artifact manifest. New workers must use page-IR schema version 2: each page carries counts and status, `worker_summary.text` is at most 1200 characters, and detailed blocks, objects, continuity, and uncertainties live in a hashed `detail_artifact` on disk. Legacy v1 shards remain readable for migration. Workers must not edit `main.tex`, shared chapter files, inventories, state, notes, or Goal status. A page is an evidence unit, not necessarily a semantic boundary: workers report continuity, object candidates, uncertainties, and proposed lifecycle status for the parent reducer to resolve in the detail artifact.

### Parent Merge Discipline

Merge shards through `scripts/merge_shards.py` at one integration point. The merger verifies source identity, unique page ownership, artifact hashes, snapshot compatibility, and idempotency before updating `batch-manifest.json`. Cross-page blocks, global labels and references, glyph maps, bibliography, index, glossary, shared preamble, and final compilation remain serialized parent work.

Keep child responses short and durable. The parent should record only batch IDs, coverage, compact summaries, hashes, blockers, usage, and the next action in its working context; full transcripts and detail artifacts remain in project files. **Do not read every detail artifact after a successful merge.** Load detail only for a blocker, uncertainty, cross-page reconciliation, or failed integration. Close completed workers, retry only failed or stale shards, and invalidate shards when the source digest or referenced snapshot changes.

## Continuation And Run-To-Completion

**Run until complete (hard default).** One user convert/resume/refine request means finish the whole pipeline in that session when the host allows: triage → scaffold → evidence → all planned batches → merge/integration → refinement → required gates → terminal outcome. Do not treat batch boundaries, chapter boundaries, or the first successful compile as natural places to stop and wait for the user.

**Never ask the user to type 继续, continue, next, or equivalent just to proceed.** Those are not valid stop reasons. Do not end a turn with “say continue to proceed,” a partial progress dump, or only the next batch id while open work remains and no true boundary has been reached.

On every continuation (same session, resume request, or active Goal), and while outcome remains `in-progress` in the initial session:

1. Read `conversion-state.md` first when it exists.
2. Verify the recorded source identity before source-aware work.
3. Check that active files and evidence for the recorded checkpoint still exist.
4. Perform the next concrete milestone, then **loop** to the following milestones without waiting for the user.
5. If workers are needed, dispatch **all remaining non-overlapping batches** from `work/page-index.json` via a bounded concurrent `spawn_subagent` pool (not one batch then stop). Merge validated results before editing shared source, and keep only the merger summary in parent context.
6. Compile and inspect the affected output when the milestone changes final LaTeX (scale-aware cadence).
7. Update state, notes, manifests, inventories, and the batch ledger only after supporting files or checks exist. Run `scripts/report_worker_usage.py PROJECT_DIR` when worker usage data is available. When a matching Goal is active, report intermediate progress with `update_goal` messages when useful; never treat progress updates as completion or as a reason to stop the parent loop.
8. Run the applicable workflow query or validation command and **immediately continue** while the valid outcome remains `in-progress`.

Do not yield merely because one batch, one chapter, a midpoint review, or the first successful compile finished. Continue automatically while meaningful work remains and no user-decision boundary has been reached. End the user-facing reply only when the outcome is terminal or a true stop condition applies.

## Forced Stops Only

Voluntary mid-pipeline yield is forbidden. Stop early only for:

1. A true **user-decision boundary** (overwrite risk, source replacement, unsafe build capability, material approximation, delivery downgrade, conflicting unrelated Goal, unreadable required region, or another authorization boundary), **or**
2. A **hard environment failure** that blocks further work (missing required tool, unreadable source, unrecoverable build environment), **or**
3. A **genuine host runtime limit** that prevents more tool calls in this turn (budget exhausted mid-work).

If forced to stop mid-work, finish the current merge when possible, write a concrete Next action into `conversion-state.md` (batch id / pages / file), set outcome `in-progress`, and report only what was completed plus how to resume—without requiring a special phrase beyond re-invoking the skill or saying resume. On the next turn, resume and again run to completion for remaining work.

While still running, each loop iteration must make **material progress** (not status-only narration): complete planned batches (dispatch → shard → merge), advance a structural unit under edit, or move scaffold/identity/evidence to the next durable checkpoint. Do not end a turn after only re-reading state or a single compile with no new reconstructed content when open batches remain.

## Compile Cadence (Scale-Aware)

Compile frequency follows project scale, not a fixed per-page rule:

- **Small** (roughly ≤30 pages or a one-turn repair): compile after meaningful edits as needed.
- **Medium**: compile after each major section or chapter file update.
- **Large** (long-document/book or many open batches): compile primarily at **chapter** (or large structural) boundaries; skip full-project compiles after every worker batch.
- Always compile before claiming `complete` and before publication gates.

Representative source-page fidelity checks are **sampled** at structural milestones, not required after every page.

## Quality Independence

Never lower delivery quality merely because Goal mode is inactive or could not start. The same delivery level, gates, compile checks, artifact scans, and completion rules apply to `resumable` and `goal-backed` work.

## Completion And Blockers

Mark a matching Goal complete only after the project satisfies the completion rules in `SKILL.md` and the workflow validator accepts the terminal project state. On Grok, complete with `update_goal` (`completed: true` and a short summary). A `downgraded` outcome also requires explicit downgrade approval.

A project blocker does not automatically permit an immediate Goal `blocked` update. Follow the current Goal tool's blocker threshold and terminal-state rules. On Grok, mark blocked only with a genuine `blocked_reason` when the task is truly stuck. While that threshold is not met, keep the project blocker specific and preserve its next action without falsely marking completion.

When no Goal is active, still set the project outcome (`complete`, `blocked`, `downgraded`, or `in-progress`) from evidence alone.
