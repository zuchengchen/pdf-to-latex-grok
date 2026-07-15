# Goal-Backed Execution

Use Goal mode as a continuity controller around the canonical PDF-to-LaTeX workflow. Keep `conversion-state.md` authoritative for durable project progress; Goal state does not replace project state, evidence, or verification gates.

On Grok, progress and terminal Goal status use the `update_goal` tool. Goal creation is normally a `/goal` slash-command handoff when no create tool is available. Workers use `spawn_subagent` with isolated context.

## Automatic Selection

Prefer Goal-backed execution by default for:

- a full `convert` whose requested result is a completed project rather than an explicitly bounded one-turn draft;
- broad `resume` or `refine` work;
- writable `publication-polish` work;
- long, book-scale, scanned, mixed, math-heavy, encoded-math, or visual-complex work expected to require multiple batches.

Use `one-turn` for work that is genuinely bounded and can finish now. This normally includes a localized `repair`, an ordinary read-only `review`, initial triage without reconstruction, and an explicitly requested one-turn rough draft. Reclassify a repair that expands into broad project improvement as `refine`.

Do not ask for separate Goal confirmation. Start or continue Goal mode immediately when Goal tools are available and the current request, surface-provided starter prompt, or runtime policy permits creation. If the runtime requires Goal intent that the active request does not provide, do not manufacture authorization and do not ask only for Goal permission; fall back to `resumable` and continue at the same delivery level.

## Startup

Resolve Goal state before broad analysis, scaffolding, or writable project work:

1. Resolve the source PDF, target directory, operation, delivery level, and verification scope with minimal read-only inspection. Default ordinary complete work to `clean-semantic`.
2. Check current Goal state when Goal tools are available.
3. Continue an unfinished Goal when its objective matches the same PDF-derived task. Report progress with `update_goal` messages when useful.
4. When no unfinished Goal conflicts and the host can activate a Goal, create or activate a concise Goal immediately if runtime policy permits it. On Grok, when no create tool is callable, provide the exact handoff:
   ```text
   /goal <concise objective>
   ```
   and continue only after the user confirms activation or observable Goal state shows the matching Goal is active. Until then, do not record `goal-backed`.
5. Do not set a token budget unless the user explicitly requested one.
6. Record `Execution mode: goal-backed` only after a matching Goal was created, continued, or confirmed active successfully.
7. If Goal tools are unavailable, startup is disallowed, or the user declines the handoff, record the reason and use `resumable`.

An unfinished unrelated Goal is a real conflict. Ask the user which objective should remain active instead of replacing it silently. Goal activation must never authorize project overwrite, source replacement, unsafe build capabilities, a delivery downgrade, or a material approximation.

Use an objective equivalent to:

```text
Use /pdf-to-latex to OPERATION SOURCE into TARGET at DELIVERY_LEVEL. Treat TARGET/conversion-state.md as the durable source of progress. On every continuation, verify source identity, follow the recorded Next action, preserve user edits, complete the gates derived from workflow-contract.json, and run scripts/workflow_contract.py to validate the project. Continue automatically until the project reaches a valid complete outcome, a user-approved downgraded outcome, or a true blocker that requires user action.
```

Keep the objective concise. Reference the skill and workflow contract instead of copying every reconstruction and publication rule into the Goal.

## Parallel Worker Protocol

For resumable or goal-backed reconstruction, keep one parent Goal as the controller. Do not create a Goal per page. The parent owns `conversion-state.md`, `conversion-notes.md`, `batch-manifest.json`, shared LaTeX source, compilation, and the terminal outcome.

Use subagents only for bounded work with disjoint ownership. Run `scripts/plan_batches.py` once the source text-layer evidence exists and dispatch the batches recorded in `work/page-index.json`; do not default to one worker per page. Launch workers with Grok `spawn_subagent` using an isolated context rather than copying the full Goal history. When the runtime supports model inheritance, omit child `model` overrides so the worker uses the parent capability. Give each worker a compact context packet: source digest, owned pages or regions, read-only neighbor pages, evidence paths, style/document-IR snapshot hashes, route, output directory, and the page-IR schema.

Workers write only their own shard under `work/shards/` or return a compact artifact manifest. New workers should use page-IR schema version 2: each page carries counts and status, `worker_summary.text` is at most 1200 characters, and detailed blocks, objects, continuity, and uncertainties live in a hashed `detail_artifact`. Legacy v1 shards remain readable for migration. Workers must not edit `main.tex`, shared chapter files, inventories, state, notes, or Goal status. A page is an evidence unit, not necessarily a semantic boundary: workers report continuity, object candidates, uncertainties, and proposed lifecycle status for the parent reducer to resolve in the detail artifact.

Merge shards through `scripts/merge_shards.py` at one integration point. The merger verifies source identity, unique page ownership, artifact hashes, snapshot compatibility, and idempotency before updating `batch-manifest.json`. Cross-page blocks, global labels and references, glyph maps, bibliography, index, glossary, shared preamble, and final compilation remain serialized parent work.

Keep child responses short and durable. The parent should record only batch IDs, coverage, compact summaries, hashes, blockers, usage, and the next action in Goal context; full transcripts and detail artifacts remain in project files. Do not read every detail artifact after a successful merge. Load detail only for a blocker, uncertainty, cross-page reconciliation, or failed integration. Close completed workers, retry only failed or stale shards, and invalidate shards when the source digest or referenced snapshot changes.

## Continuation

On every Goal continuation:

1. Read `conversion-state.md` first when it exists.
2. Verify the recorded source identity before source-aware work.
3. Check that active files and evidence for the recorded checkpoint still exist.
4. Perform the next concrete milestone or bounded batch.
5. If the milestone uses workers, dispatch the non-overlapping batches from `work/page-index.json` via `spawn_subagent`, merge their validated results before editing shared source, and keep only the merger summary in Goal context.
6. Compile and inspect the affected output when the milestone changes final LaTeX.
7. Update state, notes, manifests, inventories, and the batch ledger only after supporting files or checks exist. Run `scripts/report_worker_usage.py PROJECT_DIR` when worker usage data is available. Report intermediate progress with `update_goal` messages when useful; never treat progress updates as completion.
8. Run the applicable workflow query or validation command and continue while the valid outcome remains `in-progress`.

Do not yield merely because one batch or the first successful compile finished. Continue automatically while meaningful work remains and no user-decision boundary has been reached.

## Completion And Fallback

Mark a matching Goal complete only after the project satisfies the completion rules in `SKILL.md` and the workflow validator accepts the terminal project state. On Grok, complete with `update_goal` (`completed: true` and a short summary). A `downgraded` outcome also requires explicit downgrade approval.

A project blocker does not automatically permit an immediate Goal `blocked` update. Follow the current Goal tool's blocker threshold and terminal-state rules. On Grok, mark blocked only with a genuine `blocked_reason` when the task is truly stuck. While that threshold is not met, keep the project blocker specific and preserve its next action without falsely marking completion.

When Goal startup or continuation is unavailable, fall back to `resumable`, keep `conversion-state.md` current, and continue as far as the runtime permits. Never lower delivery quality merely because Goal mode could not start.
