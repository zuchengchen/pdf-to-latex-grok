# Goal: Port pdf-to-latex skill to Grok

## Objective

Convert this repository from a Codex-hosted skill package into a Grok-only skill
package under `skill/`, with install path `${GROK_HOME:-$HOME/.grok}/skills/pdf-to-latex`,
slash invocation `/pdf-to-latex`, and Grok Goal/worker tooling.

## Scope

- Rewrite host docs, `SKILL.md`, Goal reference, updater, package contract, and tests.
- Delete Codex UI metadata (`agents/openai.yaml`) and all Codex install/runtime wording.
- Keep conversion workflow, TeX helpers, templates, and publication gates unchanged.

## Verification

- `python3 skill/scripts/workflow_contract.py validate-package skill`
- `skill/scripts/test_skill.sh --portable`
- No Codex / `$pdf-to-latex` / `openai.yaml` residue in `skill/`, README, INSTALL, AGENTS.

## Status

Completed in this checkout as the Grok-only packaging port.
