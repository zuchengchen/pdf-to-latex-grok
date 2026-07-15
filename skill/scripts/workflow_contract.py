#!/usr/bin/env python3
"""Validate and query the PDF-to-LaTeX workflow contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONTRACT = SCRIPT_DIR.parent / "references" / "workflow-contract.json"
EXPECTED_FIELDS = (
    "operation",
    "source_kind",
    "document_traits",
    "delivery_level",
    "execution_mode",
    "verification_scope",
    "outcome",
)
FINAL_OUTCOMES = {"complete", "downgraded"}
FIELD_RE = re.compile(r"^([A-Za-z][^:#]*?):[ \t]*(.*)$")
HEADING_RE = re.compile(r"^###[ \t]+(.+?)[ \t]*$")
FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})")
FENCE_CLOSE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})[ \t]*$")
SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
GOAL_POLICY_MARKER = "never block on goal startup"
GOAL_REFERENCE = "references/goal-mode.md"
GOAL_RESUMABLE_DEFAULT_MARKER = "use `resumable` by default"
SELF_UPDATE_SCRIPT = "scripts/update_installed_skill.sh"
SELF_UPDATE_COMMAND = 'bash "$SKILL_DIR/scripts/update_installed_skill.sh"'
SELF_UPDATE_EXACT_ROUTE_MARKER = (
    "only enter this route when the trimmed request matches exactly"
)
CANONICAL_SKILL_REPO = "https://github.com/zuchengchen/pdf-to-latex-grok.git"
SELF_UPDATE_TRIGGER = f"update skill {CANONICAL_SKILL_REPO}"
SELF_UPDATE_TRIGGER_ZH = f"更新skill {CANONICAL_SKILL_REPO}"
SELF_INSTALL_TRIGGER = f"install skill {CANONICAL_SKILL_REPO}"
SELF_INSTALL_TRIGGER_ZH = f"安装skill {CANONICAL_SKILL_REPO}"
RESOURCE_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])((?:references|scripts|assets)/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*)"
)
EXPECTED_RULES: dict[
    str, tuple[tuple[str, dict[str, list[str]], tuple[str, ...]], ...]
] = {
    "path_rules": (
        ("all-projects", {}, ("main.tex",)),
        (
            "stateful-workflow",
            {"operation": ["convert", "resume", "refine"]},
            ("conversion-state.md", "conversion-notes.md"),
        ),
        (
            "durable-repair-workflow",
            {
                "operation": ["repair"],
                "execution_mode": ["resumable", "goal-backed"],
            },
            ("conversion-state.md", "conversion-notes.md"),
        ),
        (
            "publication-repair-workflow",
            {"operation": ["repair"], "delivery_level": ["publication-polish"]},
            ("conversion-state.md", "conversion-notes.md"),
        ),
        (
            "full-reconstruction-model",
            {"operation": ["convert", "resume"]},
            (
                "page-manifest.md",
                "object-inventory.md",
                "style-profile.md",
                "document-ir.md",
            ),
        ),
        (
            "refinement-style-model",
            {"operation": ["refine"]},
            ("style-profile.md",),
        ),
        (
            "publication-refinement-model",
            {"operation": ["refine"], "delivery_level": ["publication-polish"]},
            ("page-manifest.md", "object-inventory.md", "document-ir.md"),
        ),
        (
            "publication-repair-style",
            {"operation": ["repair"], "delivery_level": ["publication-polish"]},
            ("style-profile.md",),
        ),
        (
            "visual-source-model",
            {
                "operation": ["convert", "resume", "refine"],
                "source_kind": ["scanned", "mixed"],
            },
            ("page-manifest.md", "object-inventory.md", "document-ir.md"),
        ),
        (
            "book-model",
            {"operation": ["convert", "resume", "refine"], "traits_any": ["book"]},
            (
                "page-manifest.md",
                "object-inventory.md",
                "style-profile.md",
                "document-ir.md",
            ),
        ),
        (
            "long-document-model",
            {
                "operation": ["convert", "resume", "refine"],
                "traits_any": ["long-document"],
            },
            ("page-manifest.md", "document-ir.md"),
        ),
        (
            "math-model",
            {
                "operation": ["convert", "resume", "refine"],
                "traits_any": ["math-heavy", "encoded-math"],
            },
            ("object-inventory.md", "math-inventory.md", "glyph-map.md"),
        ),
        (
            "durable-math-repair-model",
            {
                "operation": ["repair"],
                "execution_mode": ["resumable", "goal-backed"],
                "traits_any": ["math-heavy", "encoded-math"],
            },
            ("object-inventory.md", "math-inventory.md", "glyph-map.md"),
        ),
        (
            "publication-math-repair-model",
            {
                "operation": ["repair"],
                "delivery_level": ["publication-polish"],
                "traits_any": ["math-heavy", "encoded-math"],
            },
            ("object-inventory.md", "math-inventory.md", "glyph-map.md"),
        ),
        (
            "cjk-style-model",
            {"operation": ["convert", "resume", "refine"], "traits_any": ["cjk"]},
            ("style-profile.md",),
        ),
        (
            "durable-cjk-repair-model",
            {
                "operation": ["repair"],
                "execution_mode": ["resumable", "goal-backed"],
                "traits_any": ["cjk"],
            },
            ("style-profile.md",),
        ),
        (
            "publication-cjk-repair-model",
            {
                "operation": ["repair"],
                "delivery_level": ["publication-polish"],
                "traits_any": ["cjk"],
            },
            ("style-profile.md",),
        ),
        (
            "visual-complex-model",
            {
                "operation": ["convert", "resume", "refine"],
                "traits_any": ["visual-complex"],
            },
            ("page-manifest.md", "object-inventory.md", "style-profile.md"),
        ),
    ),
    "gate_rules": (
        (
            "stateful-base",
            {"operation": ["convert", "resume", "refine"]},
            ("workflow-setup", "build-verification", "final-state-review"),
        ),
        (
            "durable-repair-base",
            {
                "operation": ["repair"],
                "execution_mode": ["resumable", "goal-backed"],
            },
            ("workflow-setup", "build-verification", "final-state-review"),
        ),
        (
            "convert-gates",
            {"operation": ["convert"]},
            ("source-analysis", "semantic-reconstruction"),
        ),
        (
            "resume-gates",
            {"operation": ["resume"]},
            ("resume-integrity", "semantic-reconstruction"),
        ),
        ("refine-gates", {"operation": ["refine"]}, ("refinement-review",)),
        (
            "repair-gates",
            {
                "operation": ["repair"],
                "execution_mode": ["resumable", "goal-backed"],
            },
            ("repair-verification",),
        ),
        (
            "source-aware-gates",
            {
                "operation": ["convert", "resume", "refine", "review"],
                "verification_scope": ["source-aware"],
            },
            ("source-fidelity-review",),
        ),
        (
            "durable-source-aware-repair-gates",
            {
                "operation": ["repair"],
                "execution_mode": ["resumable", "goal-backed"],
                "verification_scope": ["source-aware"],
            },
            ("source-fidelity-review",),
        ),
        (
            "publication-source-aware-repair-gates",
            {
                "operation": ["repair"],
                "delivery_level": ["publication-polish"],
                "verification_scope": ["source-aware"],
            },
            ("source-fidelity-review",),
        ),
        (
            "publication-gates",
            {
                "operation": ["convert", "resume", "refine", "review"],
                "delivery_level": ["publication-polish"],
            },
            ("artifact-scan", "clean-room-build", "publication-review"),
        ),
        (
            "publication-repair-gates",
            {"operation": ["repair"], "delivery_level": ["publication-polish"]},
            (
                "workflow-setup",
                "build-verification",
                "final-state-review",
                "repair-verification",
                "artifact-scan",
                "clean-room-build",
                "publication-review",
            ),
        ),
        (
            "book-gates",
            {
                "operation": ["convert", "resume", "refine", "review"],
                "traits_any": ["book"],
            },
            ("book-structure-review",),
        ),
        (
            "math-gates",
            {
                "operation": ["convert", "resume", "refine", "review"],
                "traits_any": ["math-heavy", "encoded-math"],
            },
            ("math-object-review",),
        ),
        (
            "durable-math-repair-gates",
            {
                "operation": ["repair"],
                "execution_mode": ["resumable", "goal-backed"],
                "traits_any": ["math-heavy", "encoded-math"],
            },
            ("math-object-review",),
        ),
        (
            "publication-math-repair-gates",
            {
                "operation": ["repair"],
                "delivery_level": ["publication-polish"],
                "traits_any": ["math-heavy", "encoded-math"],
            },
            ("math-object-review",),
        ),
    ),
}


class WorkflowError(Exception):
    """A deterministic contract or workflow validation error."""


class ExitOneArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


@dataclass(frozen=True)
class Context:
    operation: str
    source_kind: str
    document_traits: tuple[str, ...]
    delivery_level: str
    execution_mode: str
    verification_scope: str
    outcome: str


@dataclass
class Record:
    path: Path
    heading: str
    line_number: int
    fields: dict[str, str]


def is_concrete(value: str | None) -> bool:
    return bool(value and value.strip() and "{{" not in value and "}}" not in value)


def require_python() -> None:
    if sys.version_info < (3, 10):
        raise WorkflowError("Python 3.10 or newer is required.")


def load_contract(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            contract = json.load(handle)
    except FileNotFoundError as exc:
        raise WorkflowError(f"Workflow contract not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise WorkflowError(
            f"Invalid workflow contract JSON at {path}:{exc.lineno}:{exc.colno}: {exc.msg}"
        ) from exc

    validate_contract_data(contract)
    return contract


def require_type(value: Any, expected: type, label: str) -> None:
    if not isinstance(value, expected):
        raise WorkflowError(f"Contract field {label} must be {expected.__name__}.")


def ensure_unique_strings(values: Any, label: str) -> list[str]:
    require_type(values, list, label)
    if not values or any(not isinstance(value, str) or not value for value in values):
        raise WorkflowError(f"Contract field {label} must contain non-empty strings.")
    if len(values) != len(set(values)):
        raise WorkflowError(f"Contract field {label} contains duplicate values.")
    return values


def validate_contract_data(contract: dict[str, Any]) -> None:
    require_type(contract, dict, "root")
    if contract.get("skill_version") != "1.0.0":
        raise WorkflowError("Contract skill_version must be 1.0.0.")
    if contract.get("contract_version") != 1:
        raise WorkflowError("Contract contract_version must be 1.")
    if contract.get("state_schema_version") != 2:
        raise WorkflowError("Contract state_schema_version must be 2.")
    if contract.get("minimum_python_version") != "3.10":
        raise WorkflowError("Contract minimum_python_version must be 3.10.")

    fields = contract.get("canonical_fields")
    require_type(fields, dict, "canonical_fields")
    if tuple(fields.keys()) != EXPECTED_FIELDS:
        raise WorkflowError(
            "Contract canonical_fields must define only operation, source_kind, "
            "document_traits, delivery_level, execution_mode, verification_scope, and outcome."
        )

    labels: list[str] = []
    values_by_field: dict[str, set[str]] = {}
    for name in EXPECTED_FIELDS:
        definition = fields[name]
        require_type(definition, dict, f"canonical_fields.{name}")
        label = definition.get("markdown_label")
        if not isinstance(label, str) or not label:
            raise WorkflowError(f"canonical_fields.{name}.markdown_label is required.")
        labels.append(label)
        values_by_field[name] = set(
            ensure_unique_strings(definition.get("values"), f"canonical_fields.{name}.values")
        )

    if len(labels) != len(set(labels)):
        raise WorkflowError("Canonical Markdown labels must be unique.")

    expected_values = {
        "operation": {"convert", "resume", "refine", "repair", "review"},
        "source_kind": {"digital", "scanned", "mixed", "unknown"},
        "delivery_level": {"rough-draft", "clean-semantic", "publication-polish"},
        "execution_mode": {"one-turn", "resumable", "goal-backed"},
        "verification_scope": {"source-aware", "project-only"},
        "outcome": {"complete", "blocked", "downgraded", "in-progress"},
    }
    for field, expected in expected_values.items():
        if values_by_field[field] != expected:
            raise WorkflowError(f"Contract values for {field} do not match schema 2.")
    expected_traits = {
        "book",
        "long-document",
        "math-heavy",
        "encoded-math",
        "cjk",
        "visual-complex",
    }
    if values_by_field["document_traits"] != expected_traits:
        raise WorkflowError("Contract values for document_traits do not match schema 2.")
    if fields["document_traits"].get("empty_value") != "none":
        raise WorkflowError("Document traits empty_value must be none.")

    exits = contract.get("outcome_exit_codes")
    expected_exits = {
        "complete": 0,
        "downgraded": 0,
        "in-progress": 1,
        "blocked": 2,
        "invalid": 1,
    }
    if exits != expected_exits:
        raise WorkflowError("outcome_exit_codes do not match the workflow contract.")

    tracking = contract.get("tracking")
    require_type(tracking, dict, "tracking")
    expected_tracking = {
        "statuses": {
            "pending",
            "in-progress",
            "rebuilt",
            "reviewed",
            "blocked",
            "omitted-with-reason",
        },
        "complete_statuses": {"rebuilt", "reviewed", "omitted-with-reason"},
        "required_gate_complete_statuses": {"reviewed"},
        "compile_checks": {"not-run", "pass", "fail"},
        "visual_reviews": {"not-run", "pass", "fail", "not-applicable"},
        "source_fidelity": {
            "in-progress",
            "verified",
            "not-verified-source-unavailable",
            "not-verified-by-scope",
        },
        "record_files": {
            "page-manifest.md",
            "object-inventory.md",
            "style-profile.md",
            "document-ir.md",
            "math-inventory.md",
            "glyph-map.md",
        },
    }
    if set(tracking) != set(expected_tracking):
        raise WorkflowError("Contract tracking fields do not match schema 2.")
    for name, expected in expected_tracking.items():
        actual = set(ensure_unique_strings(tracking.get(name), f"tracking.{name}"))
        if actual != expected:
            raise WorkflowError(f"tracking.{name} does not match schema 2.")

    state = contract.get("state")
    require_type(state, dict, "state")
    expected_state_keys = {
        "file",
        "notes_file",
        "state_required_operations",
        "state_optional_operations",
        "stateless_operations",
        "required_metadata",
        "notes_metadata",
        "conditional_metadata",
        "forbidden_metadata",
    }
    if set(state) != expected_state_keys:
        raise WorkflowError("Contract state fields do not match schema 2.")
    if state.get("file") != "conversion-state.md":
        raise WorkflowError("state.file must be conversion-state.md.")
    if state.get("notes_file") != "conversion-notes.md":
        raise WorkflowError("state.notes_file must be conversion-notes.md.")
    state_required = set(
        ensure_unique_strings(
            state.get("state_required_operations"), "state.state_required_operations"
        )
    )
    state_optional = set(
        ensure_unique_strings(
            state.get("state_optional_operations"), "state.state_optional_operations"
        )
    )
    stateless = set(ensure_unique_strings(state.get("stateless_operations"), "state.stateless_operations"))
    if (
        state_required != {"convert", "resume", "refine"}
        or state_optional != {"repair"}
        or stateless != {"review"}
    ):
        raise WorkflowError("Required, optional, and stateless operation sets do not match schema 2.")
    required_metadata = set(
        ensure_unique_strings(state.get("required_metadata"), "state.required_metadata")
    )
    expected_required_metadata = {
        "State schema",
        "Skill version",
        "Contract version",
        "Source PDF",
        "Source PDF SHA-256",
        "Source PDF size bytes",
        "Source PDF page count",
        *labels,
        "Compile check",
        "Visual review",
        "Source fidelity",
        "Next action",
    }
    if required_metadata != expected_required_metadata:
        raise WorkflowError("state.required_metadata does not match schema 2.")
    notes_metadata = set(
        ensure_unique_strings(state.get("notes_metadata"), "state.notes_metadata")
    )
    expected_notes_metadata = {
        "State schema",
        "Skill version",
        "Contract version",
        "Source PDF",
        *labels,
    }
    if notes_metadata != expected_notes_metadata:
        raise WorkflowError("state.notes_metadata does not match schema 2.")
    conditional = state.get("conditional_metadata")
    require_type(conditional, dict, "state.conditional_metadata")
    if set(conditional) != {"downgraded"}:
        raise WorkflowError("state.conditional_metadata must define only downgraded.")
    conditional_fields = set(
        ensure_unique_strings(
            conditional.get("downgraded"), "state.conditional_metadata.downgraded"
        )
    )
    if conditional_fields != {"Previous delivery level", "Downgrade approval"}:
        raise WorkflowError("Downgraded conditional metadata does not match schema 2.")
    forbidden = set(
        ensure_unique_strings(state.get("forbidden_metadata"), "state.forbidden_metadata")
    )
    if forbidden != {"Task profile"}:
        raise WorkflowError("state.forbidden_metadata does not match schema 2.")

    rule_maps: dict[str, dict[str, dict[str, Any]]] = {}
    for rules_name, output_name in (("path_rules", "require_files"), ("gate_rules", "require_gates")):
        rules = contract.get(rules_name)
        require_type(rules, list, rules_name)
        ids: list[str] = []
        for index, rule in enumerate(rules):
            require_type(rule, dict, f"{rules_name}[{index}]")
            rule_id = rule.get("id")
            if not isinstance(rule_id, str) or not rule_id:
                raise WorkflowError(f"{rules_name}[{index}].id is required.")
            ids.append(rule_id)
            validate_rule_condition(rule.get("when"), values_by_field, f"{rules_name}[{index}].when")
            outputs = ensure_unique_strings(rule.get(output_name), f"{rules_name}[{index}].{output_name}")
            if output_name == "require_files":
                for output in outputs:
                    candidate = Path(output)
                    if candidate.is_absolute() or ".." in candidate.parts:
                        raise WorkflowError(f"Unsafe required path in {rules_name}: {output}")
        if len(ids) != len(set(ids)):
            raise WorkflowError(f"{rules_name} contains duplicate rule ids.")
        expected_rules = EXPECTED_RULES[rules_name]
        expected_ids = [rule_id for rule_id, _, _ in expected_rules]
        if ids != expected_ids:
            raise WorkflowError(f"{rules_name} rule ids or order do not match schema 2.")
        for rule, (rule_id, expected_when, expected_outputs) in zip(rules, expected_rules):
            if rule["when"] != expected_when:
                raise WorkflowError(f"{rules_name} rule {rule_id} condition does not match schema 2.")
            if rule[output_name] != list(expected_outputs):
                raise WorkflowError(f"{rules_name} rule {rule_id} outputs do not match schema 2.")
        rule_maps[rules_name] = {rule["id"]: rule for rule in rules}

    path_map = rule_maps["path_rules"]
    gate_map = rule_maps["gate_rules"]
    if path_map["all-projects"]["when"] or "main.tex" not in path_map["all-projects"][
        "require_files"
    ]:
        raise WorkflowError("all-projects must require main.tex for every context.")
    if set(path_map["stateful-workflow"]["when"].get("operation", [])) != {
        "convert",
        "resume",
        "refine",
    }:
        raise WorkflowError("stateful-workflow operations do not match schema 2.")
    if not {"conversion-state.md", "conversion-notes.md"}.issubset(
        path_map["stateful-workflow"]["require_files"]
    ):
        raise WorkflowError("stateful-workflow must require state and notes.")
    if not {"conversion-state.md", "conversion-notes.md"}.issubset(
        path_map["publication-repair-workflow"]["require_files"]
    ):
        raise WorkflowError("Publication repair must require state and notes.")
    if "review" not in gate_map["publication-gates"]["when"].get("operation", []):
        raise WorkflowError("Publication review must derive publication gates.")
    if not {"artifact-scan", "clean-room-build", "publication-review"}.issubset(
        gate_map["publication-gates"]["require_gates"]
    ):
        raise WorkflowError("Publication gates are incomplete.")
    if "review" not in gate_map["source-aware-gates"]["when"].get("operation", []):
        raise WorkflowError("Source-aware review must derive source-fidelity-review.")
    if "source-fidelity-review" not in gate_map[
        "publication-source-aware-repair-gates"
    ]["require_gates"]:
        raise WorkflowError("Publication source-aware repair gate is missing.")
    if "math-object-review" not in gate_map["publication-math-repair-gates"][
        "require_gates"
    ]:
        raise WorkflowError("Publication math repair gate is missing.")
    if "review" not in gate_map["book-gates"]["when"].get("operation", []):
        raise WorkflowError("Book review must derive book-structure-review.")
    if "review" not in gate_map["math-gates"]["when"].get("operation", []):
        raise WorkflowError("Math review must derive math-object-review.")

    constraints = contract.get("constraints")
    require_type(constraints, dict, "constraints")
    if set(constraints) != {"source_required_operations", "delivery_rank"}:
        raise WorkflowError("Contract constraints do not match schema 2.")
    source_required = set(
        ensure_unique_strings(
            constraints.get("source_required_operations"),
            "constraints.source_required_operations",
        )
    )
    if source_required != {"convert"}:
        raise WorkflowError("constraints.source_required_operations must contain convert.")
    if constraints.get("delivery_rank") != {
        "rough-draft": 0,
        "clean-semantic": 1,
        "publication-polish": 2,
    }:
        raise WorkflowError("constraints.delivery_rank does not match schema 2.")


def validate_rule_condition(
    condition: Any, values_by_field: dict[str, set[str]], label: str
) -> None:
    require_type(condition, dict, label)
    permitted = {
        "operation",
        "source_kind",
        "delivery_level",
        "execution_mode",
        "verification_scope",
        "traits_any",
        "traits_all",
    }
    unknown = set(condition) - permitted
    if unknown:
        raise WorkflowError(f"{label} contains unsupported keys: {', '.join(sorted(unknown))}")
    for key, raw_values in condition.items():
        values = set(ensure_unique_strings(raw_values, f"{label}.{key}"))
        source_field = "document_traits" if key.startswith("traits_") else key
        invalid = values - values_by_field[source_field]
        if invalid:
            raise WorkflowError(
                f"{label}.{key} contains invalid values: {', '.join(sorted(invalid))}"
            )


def parse_traits(raw: str, contract: dict[str, Any]) -> tuple[str, ...]:
    value = raw.strip()
    definition = contract["canonical_fields"]["document_traits"]
    if value == definition["empty_value"]:
        return ()
    if not value:
        raise WorkflowError("Document traits is required; use 'none' when no traits apply.")
    traits = tuple(part.strip() for part in value.split(","))
    if any(not trait for trait in traits):
        raise WorkflowError("Document traits must be a comma-separated list without empty items.")
    if len(traits) != len(set(traits)):
        raise WorkflowError("Document traits contains duplicate values.")
    allowed = set(definition["values"])
    invalid = set(traits) - allowed
    if invalid:
        raise WorkflowError(f"Unsupported document traits: {', '.join(sorted(invalid))}")
    return traits


def format_traits(traits: Sequence[str], contract: dict[str, Any]) -> str:
    if not traits:
        return contract["canonical_fields"]["document_traits"]["empty_value"]
    order = contract["canonical_fields"]["document_traits"]["values"]
    selected = set(traits)
    return ",".join(value for value in order if value in selected)


def context_from_values(values: dict[str, str], contract: dict[str, Any]) -> Context:
    parsed: dict[str, Any] = {}
    for name in EXPECTED_FIELDS:
        definition = contract["canonical_fields"][name]
        label = definition["markdown_label"]
        raw = values.get(name)
        if raw is None or not raw.strip():
            raise WorkflowError(f"Missing required workflow field: {label}")
        if "{{" in raw or "}}" in raw:
            raise WorkflowError(f"Workflow field still contains an unresolved placeholder: {label}")
        if name == "document_traits":
            parsed[name] = parse_traits(raw, contract)
            continue
        value = raw.strip()
        if value not in definition["values"]:
            raise WorkflowError(f"Unsupported {label}: {value}")
        parsed[name] = value
    return Context(**parsed)


def context_values(context: Context, contract: dict[str, Any]) -> dict[str, str]:
    return {
        "operation": context.operation,
        "source_kind": context.source_kind,
        "document_traits": format_traits(context.document_traits, contract),
        "delivery_level": context.delivery_level,
        "execution_mode": context.execution_mode,
        "verification_scope": context.verification_scope,
        "outcome": context.outcome,
    }


def rule_matches(condition: dict[str, list[str]], context: Context) -> bool:
    simple = {
        "operation": context.operation,
        "source_kind": context.source_kind,
        "delivery_level": context.delivery_level,
        "execution_mode": context.execution_mode,
        "verification_scope": context.verification_scope,
    }
    for key, values in condition.items():
        if key == "traits_any":
            if not set(values).intersection(context.document_traits):
                return False
        elif key == "traits_all":
            if not set(values).issubset(context.document_traits):
                return False
        elif simple[key] not in values:
            return False
    return True


def derived_values(contract: dict[str, Any], rules_name: str, output_name: str, context: Context) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for rule in contract[rules_name]:
        if rule_matches(rule["when"], context):
            for value in rule[output_name]:
                if value not in seen:
                    result.append(value)
                    seen.add(value)
    return result


def required_files(contract: dict[str, Any], context: Context) -> list[str]:
    return derived_values(contract, "path_rules", "require_files", context)


def required_gates(contract: dict[str, Any], context: Context) -> list[str]:
    return derived_values(contract, "gate_rules", "require_gates", context)


def leading_indentation_columns(line: str) -> int:
    columns = 0
    for character in line:
        if character == " ":
            columns += 1
        elif character == "\t":
            columns += 4 - (columns % 4)
        else:
            break
    return columns


def strip_html_comments(
    line: str, html_comment: bool, inline_ticks: int
) -> tuple[str, bool, int]:
    visible: list[str] = []
    cursor = 0
    while cursor < len(line):
        if html_comment:
            end = line.find("-->", cursor)
            if end < 0:
                return "".join(visible), True, inline_ticks
            html_comment = False
            cursor = end + 3
            continue
        if line[cursor] == "`":
            end = cursor + 1
            while end < len(line) and line[end] == "`":
                end += 1
            run_length = end - cursor
            if inline_ticks == 0:
                inline_ticks = run_length
            elif inline_ticks == run_length:
                inline_ticks = 0
            visible.append(" " * run_length)
            cursor = end
            continue
        if inline_ticks:
            visible.append(" ")
            cursor += 1
            continue
        if inline_ticks == 0 and line.startswith("<!--", cursor):
            html_comment = True
            cursor += 4
            continue
        visible.append(line[cursor])
        cursor += 1
    return "".join(visible), html_comment, inline_ticks


def active_lines(path: Path) -> list[tuple[int, str]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise WorkflowError(f"Markdown file is not valid UTF-8: {path}") from exc
    active: list[tuple[int, str]] = []
    fence: str | None = None
    html_comment = False
    inline_ticks = 0
    for line_number, line in enumerate(lines, start=1):
        raw_indentation = leading_indentation_columns(line)
        raw_fence = FENCE_RE.match(line)
        if fence is not None:
            closing_match = FENCE_CLOSE_RE.match(line)
            if closing_match and raw_indentation < 4:
                closing = closing_match.group(1)
                if closing[0] == fence[0] and len(closing) >= len(fence):
                    fence = None
            continue
        if not html_comment and inline_ticks == 0:
            if raw_indentation >= 4:
                continue
            if raw_fence and raw_indentation < 4:
                fence = raw_fence.group(1)
                continue
        visible_line, html_comment, inline_ticks = strip_html_comments(
            line, html_comment, inline_ticks
        )
        indentation = leading_indentation_columns(visible_line)
        if indentation >= 4:
            continue
        match = FENCE_RE.match(visible_line)
        if match and indentation < 4:
            fence = match.group(1)
            continue
        active.append((line_number, visible_line))
    if inline_ticks:
        raise WorkflowError(f"Markdown file contains an unterminated inline code span: {path}")
    return active


def parse_metadata(path: Path, recognized: Iterable[str]) -> tuple[dict[str, str], list[str]]:
    recognized_set = set(recognized)
    values: dict[str, str] = {}
    errors: list[str] = []
    for line_number, line in active_lines(path):
        if line.startswith("## "):
            break
        match = FIELD_RE.match(line)
        if not match:
            continue
        label = match.group(1).strip()
        if label not in recognized_set:
            continue
        if label in values:
            errors.append(f"{path}:{line_number}: duplicate metadata field: {label}")
            continue
        values[label] = match.group(2).strip()
    return values, errors


def parse_records(path: Path) -> tuple[list[Record], list[str]]:
    records: list[Record] = []
    errors: list[str] = []
    current: Record | None = None
    record_fields = {"Status", "Reason", "Next action", "Compile check", "Visual review"}

    for line_number, line in active_lines(path):
        heading_match = HEADING_RE.match(line)
        if heading_match:
            if current is not None:
                records.append(current)
            current = Record(path, heading_match.group(1).strip(), line_number, {})
            continue
        if line.startswith("## "):
            if current is not None:
                records.append(current)
                current = None
            continue
        match = FIELD_RE.match(line)
        if not match:
            continue
        label = match.group(1).strip()
        if label not in record_fields:
            continue
        if current is None:
            if label == "Status":
                errors.append(f"{path}:{line_number}: Status must belong to a level-three record.")
            continue
        if label in current.fields:
            errors.append(
                f"{path}:{line_number}: duplicate {label} in record '{current.heading}'."
            )
            continue
        current.fields[label] = match.group(2).strip()

    if current is not None:
        records.append(current)
    return records, errors


def validate_context_constraints(context: Context, contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    source_required = set(contract["constraints"]["source_required_operations"])
    if context.operation in source_required and context.verification_scope != "source-aware":
        errors.append(f"Operation {context.operation} requires verification scope source-aware.")
    if context.outcome in FINAL_OUTCOMES and context.verification_scope == "source-aware":
        if context.source_kind == "unknown":
            errors.append("A source-aware final outcome requires a known source kind.")
    return errors


def validate_record(
    record: Record, contract: dict[str, Any], require_status: bool = False
) -> list[str]:
    errors: list[str] = []
    status = record.fields.get("Status")
    location = f"{record.path}:{record.line_number} ({record.heading})"
    if require_status and status is None:
        errors.append(f"{location}: record is missing Status.")
        return errors
    if status is None:
        return errors
    if status not in contract["tracking"]["statuses"]:
        errors.append(f"{location}: unsupported or empty Status: {status or '<empty>'}")
        return errors
    if status == "blocked":
        if not is_concrete(record.fields.get("Reason")):
            errors.append(f"{location}: blocked record requires a non-empty Reason.")
        if not is_concrete(record.fields.get("Next action")):
            errors.append(f"{location}: blocked record requires a non-empty Next action.")
    if status == "omitted-with-reason" and not is_concrete(record.fields.get("Reason")):
        errors.append(f"{location}: omitted-with-reason record requires a non-empty Reason.")

    compile_check = record.fields.get("Compile check")
    if compile_check is not None and compile_check not in contract["tracking"]["compile_checks"]:
        errors.append(f"{location}: unsupported or empty Compile check: {compile_check or '<empty>'}")
    visual_review = record.fields.get("Visual review")
    if visual_review is not None and visual_review not in contract["tracking"]["visual_reviews"]:
        errors.append(f"{location}: unsupported or empty Visual review: {visual_review or '<empty>'}")
    return errors


def validate_final_checks(
    context: Context,
    compile_check: str,
    visual_review: str,
    source_fidelity: str,
    next_action: str,
    previous_delivery: str,
    downgrade_approval: str,
    contract: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    if compile_check not in contract["tracking"]["compile_checks"]:
        errors.append(f"Unsupported or missing Compile check: {compile_check or '<empty>'}")
    if visual_review not in contract["tracking"]["visual_reviews"]:
        errors.append(f"Unsupported or missing Visual review: {visual_review or '<empty>'}")
    if source_fidelity not in contract["tracking"]["source_fidelity"]:
        errors.append(f"Unsupported or missing Source fidelity: {source_fidelity or '<empty>'}")
    if not is_concrete(next_action):
        errors.append("Next action must be non-empty and concrete.")

    if context.outcome in FINAL_OUTCOMES:
        if compile_check != "pass":
            errors.append("A final outcome requires Compile check: pass.")
        if context.delivery_level == "publication-polish" and visual_review != "pass":
            errors.append("Publication polish requires Visual review: pass.")
        if (
            context.delivery_level == "clean-semantic"
            and context.operation != "repair"
            and visual_review != "pass"
        ):
            errors.append(
                "Clean-semantic convert, resume, refine, and review require Visual review: pass."
            )
        if context.verification_scope == "source-aware":
            if visual_review != "pass":
                errors.append("A source-aware final outcome requires Visual review: pass.")
            if source_fidelity != "verified":
                errors.append("A source-aware final outcome requires Source fidelity: verified.")
        else:
            if visual_review not in {"pass", "not-applicable"}:
                errors.append(
                    "A project-only final outcome requires Visual review pass or not-applicable."
                )
            if source_fidelity not in {
                "not-verified-source-unavailable",
                "not-verified-by-scope",
            }:
                errors.append(
                    "A project-only final outcome must explicitly record unverified source fidelity."
                )

    if context.outcome == "downgraded":
        allowed_delivery = contract["canonical_fields"]["delivery_level"]["values"]
        if previous_delivery not in allowed_delivery:
            errors.append("Downgraded outcome requires a valid Previous delivery level.")
        else:
            rank = contract["constraints"]["delivery_rank"]
            if rank[previous_delivery] <= rank[context.delivery_level]:
                errors.append("Previous delivery level must be higher than the downgraded level.")
        if not is_concrete(downgrade_approval):
            errors.append("Downgraded outcome requires non-empty Downgrade approval.")
    return errors


def inspect_source_identity(source_pdf: str, base_dir: Path) -> tuple[str, int, int]:
    source_path = Path(source_pdf).expanduser()
    if not source_path.is_absolute():
        source_path = base_dir / source_path
    if not source_path.is_file():
        raise WorkflowError(f"Source PDF not found: {source_path}")
    source_path = source_path.resolve(strict=True)
    try:
        stat_before = source_path.stat()
        with source_path.open("rb") as handle:
            header = handle.read(1024)
            digest = hashlib.sha256()
            digest.update(header)
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise WorkflowError(f"Could not read Source PDF {source_path}: {exc}") from exc
    if b"%PDF-" not in header:
        raise WorkflowError(f"Source PDF does not have a PDF header: {source_path}")

    pdfinfo = shutil.which("pdfinfo")
    if pdfinfo is None:
        raise WorkflowError("Source-aware validation requires pdfinfo.")
    environment = os.environ.copy()
    environment["LC_ALL"] = "C"
    completed = subprocess.run(
        [pdfinfo, str(source_path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
        check=False,
        env=environment,
    )
    if completed.returncode != 0:
        raise WorkflowError(
            f"pdfinfo could not read Source PDF {source_path}: {completed.stdout.strip()}"
        )
    match = re.search(r"(?m)^Pages:\s*([0-9]+)\s*$", completed.stdout)
    if match is None or int(match.group(1)) <= 0:
        raise WorkflowError(f"pdfinfo did not report a positive page count: {source_path}")
    stat_after = source_path.stat()
    before = (
        stat_before.st_dev,
        stat_before.st_ino,
        stat_before.st_size,
        stat_before.st_mtime_ns,
    )
    after = (
        stat_after.st_dev,
        stat_after.st_ino,
        stat_after.st_size,
        stat_after.st_mtime_ns,
    )
    if before != after:
        raise WorkflowError(f"Source PDF changed during validation: {source_path}")
    return digest.hexdigest(), stat_after.st_size, int(match.group(1))


def validate_source_identity(
    metadata: dict[str, str], context: Context, base_dir: Path
) -> list[str]:
    errors: list[str] = []
    source_pdf = metadata.get("Source PDF", "")
    if not source_pdf or "{{" in source_pdf:
        errors.append("Source PDF must be recorded.")
    if context.verification_scope != "source-aware":
        return errors
    digest = metadata.get("Source PDF SHA-256", "")
    if not SHA256_RE.fullmatch(digest):
        errors.append("Source-aware state requires a 64-character Source PDF SHA-256.")
    for label in ("Source PDF size bytes", "Source PDF page count"):
        raw = metadata.get(label, "")
        try:
            value = int(raw)
        except ValueError:
            value = 0
        if value <= 0:
            errors.append(f"Source-aware state requires a positive integer {label}.")
    if source_pdf.lower() in {"unavailable", "unknown", "none"}:
        errors.append("Source-aware state requires an available Source PDF path.")
    if errors:
        return errors
    try:
        actual_sha, actual_size, actual_pages = inspect_source_identity(source_pdf, base_dir)
    except (OSError, WorkflowError) as exc:
        errors.append(str(exc))
        return errors
    if actual_sha.lower() != digest.lower():
        errors.append(
            f"Source PDF SHA-256 does not match the recorded identity: {actual_sha}"
        )
    if actual_size != int(metadata["Source PDF size bytes"]):
        errors.append(
            f"Source PDF size does not match the recorded identity: {actual_size}"
        )
    if actual_pages != int(metadata["Source PDF page count"]):
        errors.append(
            f"Source PDF page count does not match the recorded identity: {actual_pages}"
        )
    return errors


def metadata_to_context(metadata: dict[str, str], contract: dict[str, Any]) -> Context:
    values: dict[str, str] = {}
    for name in EXPECTED_FIELDS:
        label = contract["canonical_fields"][name]["markdown_label"]
        values[name] = metadata.get(label, "")
    return context_from_values(values, contract)


def compare_cli_context(args: argparse.Namespace, context: Context, contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    actual = context_values(context, contract)
    for name in EXPECTED_FIELDS:
        supplied = getattr(args, name, None)
        if supplied is None:
            continue
        try:
            expected_context = context_from_values(
                {
                    key: (supplied if key == name else value)
                    for key, value in actual.items()
                },
                contract,
            )
        except WorkflowError as exc:
            errors.append(str(exc))
            continue
        expected = context_values(expected_context, contract)[name]
        if expected != actual[name]:
            label = contract["canonical_fields"][name]["markdown_label"]
            errors.append(f"CLI {label} does not match conversion-state.md.")
    return errors


def validate_notes(
    path: Path, state_metadata: dict[str, str], context: Context, contract: dict[str, Any]
) -> list[str]:
    labels = contract["state"]["notes_metadata"]
    metadata, errors = parse_metadata(path, labels)
    for label in labels:
        value = metadata.get(label, "")
        if not value:
            errors.append(f"{path}: missing required metadata field: {label}")
            continue
        if "{{" in value or "}}" in value:
            errors.append(f"{path}: unresolved placeholder in metadata field: {label}")
            continue
        expected = state_metadata.get(label, "")
        if label == "Document traits":
            try:
                if set(parse_traits(value, contract)) != set(context.document_traits):
                    errors.append(f"{path}: Document traits does not match conversion-state.md.")
            except WorkflowError as exc:
                errors.append(f"{path}: {exc}")
        elif value != expected:
            errors.append(f"{path}: {label} does not match conversion-state.md.")
    return errors


def validate_stateful(
    project_dir: Path, args: argparse.Namespace, contract: dict[str, Any]
) -> tuple[Context | None, list[str], list[str]]:
    errors: list[str] = []
    messages: list[str] = []
    state_path = project_dir / contract["state"]["file"]
    recognized = set(contract["state"]["required_metadata"])
    recognized.update(contract["state"]["forbidden_metadata"])
    for labels in contract["state"]["conditional_metadata"].values():
        recognized.update(labels)
    metadata, parse_errors = parse_metadata(state_path, recognized)
    errors.extend(parse_errors)

    for label in contract["state"]["required_metadata"]:
        if label not in metadata:
            errors.append(f"{state_path}: missing required metadata field: {label}")
    for label in contract["state"]["forbidden_metadata"]:
        if label in metadata:
            errors.append(f"{state_path}: legacy metadata field is not supported: {label}")

    if metadata.get("State schema") != str(contract["state_schema_version"]):
        errors.append(f"{state_path}: State schema must be {contract['state_schema_version']}.")
    if metadata.get("Skill version") != contract["skill_version"]:
        errors.append(f"{state_path}: Skill version must be {contract['skill_version']}.")
    if metadata.get("Contract version") != str(contract["contract_version"]):
        errors.append(f"{state_path}: Contract version must be {contract['contract_version']}.")

    try:
        context = metadata_to_context(metadata, contract)
    except WorkflowError as exc:
        errors.append(f"{state_path}: {exc}")
        return None, errors, messages

    state_operations = set(contract["state"]["state_required_operations"]) | set(
        contract["state"]["state_optional_operations"]
    )
    if context.operation not in state_operations:
        errors.append(
            f"{state_path}: operation {context.operation} must not use a workflow state file."
        )
    errors.extend(compare_cli_context(args, context, contract))
    errors.extend(validate_context_constraints(context, contract))
    errors.extend(validate_source_identity(metadata, context, project_dir))

    previous_delivery = metadata.get("Previous delivery level", "")
    downgrade_approval = metadata.get("Downgrade approval", "")
    errors.extend(
        validate_final_checks(
            context,
            metadata.get("Compile check", ""),
            metadata.get("Visual review", ""),
            metadata.get("Source fidelity", ""),
            metadata.get("Next action", ""),
            previous_delivery,
            downgrade_approval,
            contract,
        )
    )

    paths = required_files(contract, context)
    if context.operation in contract["state"]["state_optional_operations"]:
        for relative in (contract["state"]["file"], contract["state"]["notes_file"]):
            if relative not in paths:
                paths.append(relative)
    for relative in paths:
        candidate = project_dir / relative
        if not candidate.is_file():
            errors.append(f"Missing required file: {relative}")
        else:
            messages.append(f"Required file present: {relative}")

    notes_path = project_dir / contract["state"]["notes_file"]
    if notes_path.is_file():
        errors.extend(validate_notes(notes_path, metadata, context, contract))

    state_records, record_errors = parse_records(state_path)
    errors.extend(record_errors)
    all_records: list[Record] = list(state_records)
    for record in state_records:
        require_status = record.heading.startswith("Gate:") or record.heading.startswith("Blocker:")
        errors.extend(validate_record(record, contract, require_status=require_status))

    gate_records: dict[str, Record] = {}
    for record in state_records:
        if not record.heading.startswith("Gate:"):
            continue
        gate_id = record.heading.partition(":")[2].strip()
        if not is_concrete(gate_id):
            errors.append(f"{state_path}:{record.line_number}: Gate identifier is empty.")
        elif gate_id in gate_records:
            errors.append(f"{state_path}:{record.line_number}: duplicate Gate: {gate_id}")
        else:
            gate_records[gate_id] = record

    gates = required_gates(contract, context)
    for gate_id in gates:
        record = gate_records.get(gate_id)
        if record is None:
            errors.append(f"Missing required gate record: {gate_id}")
            continue
        if context.outcome in FINAL_OUTCOMES:
            status = record.fields.get("Status", "")
            if status not in contract["tracking"]["required_gate_complete_statuses"]:
                errors.append(f"Required gate is not reviewed: {gate_id} ({status or 'empty'})")

    record_files = set(contract["tracking"]["record_files"])
    for relative in paths:
        if relative not in record_files:
            continue
        path = project_dir / relative
        if not path.is_file():
            continue
        records, record_errors = parse_records(path)
        errors.extend(record_errors)
        if not records:
            errors.append(f"{relative} must contain at least one level-three lifecycle record.")
        for record in records:
            errors.extend(validate_record(record, contract, require_status=True))
        all_records.extend(records)

    blocked_records = [
        record for record in all_records if record.fields.get("Status") == "blocked"
    ]
    if context.outcome == "blocked" and not blocked_records:
        errors.append("Outcome blocked requires at least one blocked record.")
    if context.outcome in FINAL_OUTCOMES:
        complete_statuses = set(contract["tracking"]["complete_statuses"])
        for record in all_records:
            status = record.fields.get("Status")
            if status is not None and status not in complete_statuses:
                errors.append(
                    f"{record.path}:{record.line_number} ({record.heading}): "
                    f"final outcome cannot contain Status {status or '<empty>'}."
                )

    return context, errors, messages


def cli_values(args: argparse.Namespace) -> dict[str, str]:
    return {name: getattr(args, name, None) for name in EXPECTED_FIELDS}


def validate_stateless_workflow(
    project_dir: Path, args: argparse.Namespace, contract: dict[str, Any]
) -> tuple[Context | None, list[str], list[str]]:
    errors: list[str] = []
    messages: list[str] = []
    try:
        context = context_from_values(cli_values(args), contract)
    except WorkflowError as exc:
        return None, [str(exc)], messages
    stateless_allowed = context.operation == "review" or (
        context.operation == "repair"
        and context.execution_mode == "one-turn"
        and context.delivery_level != "publication-polish"
    )
    if not stateless_allowed:
        return None, [
            "A workflow without conversion-state.md must use review or a non-publication "
            "one-turn repair."
        ], messages
    errors.extend(validate_context_constraints(context, contract))

    if context.verification_scope == "source-aware":
        source_metadata = {
            "Source PDF": args.source_pdf or "",
            "Source PDF SHA-256": args.source_sha256 or "",
            "Source PDF size bytes": args.source_size_bytes or "",
            "Source PDF page count": args.source_page_count or "",
        }
        errors.extend(validate_source_identity(source_metadata, context, project_dir))

    required_cli = {
        "compile_check": "Compile check",
        "visual_review": "Visual review",
        "source_fidelity": "Source fidelity",
        "next_action": "Next action",
    }
    for name, label in required_cli.items():
        if getattr(args, name, None) is None:
            errors.append(f"Stateless workflow requires --{name.replace('_', '-')}: {label}")

    previous_delivery = args.previous_delivery_level or ""
    downgrade_approval = args.downgrade_approval or ""
    errors.extend(
        validate_final_checks(
            context,
            args.compile_check or "",
            args.visual_review or "",
            args.source_fidelity or "",
            args.next_action or "",
            previous_delivery,
            downgrade_approval,
            contract,
        )
    )
    for relative in required_files(contract, context):
        candidate = project_dir / relative
        if not candidate.is_file():
            errors.append(f"Missing required file: {relative}")
        else:
            messages.append(f"Required file present: {relative}")

    supplied_gates: dict[str, str] = {}
    for gate_id, status in args.gate or []:
        if gate_id in supplied_gates:
            errors.append(f"Duplicate stateless gate record: {gate_id}")
            continue
        if status not in contract["tracking"]["statuses"]:
            errors.append(f"Stateless gate {gate_id} has unsupported Status: {status}")
        supplied_gates[gate_id] = status
    expected_gates = required_gates(contract, context)
    unexpected_gates = sorted(set(supplied_gates) - set(expected_gates))
    for gate_id in unexpected_gates:
        errors.append(f"Unexpected stateless gate record: {gate_id}")
    for gate_id in expected_gates:
        status = supplied_gates.get(gate_id)
        if status is None:
            errors.append(f"Missing required stateless gate record: {gate_id}")
        elif context.outcome in FINAL_OUTCOMES and status not in set(
            contract["tracking"]["required_gate_complete_statuses"]
        ):
            errors.append(
                f"Required stateless gate is not reviewed: {gate_id} ({status})"
            )

    blockers = args.blocker or []
    blocker_ids: set[str] = set()
    for blocker_id, reason, next_action in blockers:
        if blocker_id in blocker_ids:
            errors.append(f"Duplicate stateless blocker record: {blocker_id}")
        blocker_ids.add(blocker_id)
        if not is_concrete(blocker_id):
            errors.append("Each --blocker requires a non-empty identifier.")
        if not is_concrete(reason):
            errors.append(f"Blocked item {blocker_id or '<empty>'} requires a non-empty reason.")
        if not is_concrete(next_action):
            errors.append(f"Blocked item {blocker_id or '<empty>'} requires a non-empty next action.")
    if context.outcome == "blocked" and not blockers:
        errors.append("Outcome blocked requires at least one --blocker ID REASON NEXT_ACTION.")
    for gate_id, status in supplied_gates.items():
        if status == "blocked" and gate_id not in blocker_ids:
            errors.append(
                f"Blocked stateless gate {gate_id} requires a matching --blocker record."
            )
    if context.outcome in FINAL_OUTCOMES and blockers:
        errors.append("A final stateless outcome cannot include blocked items.")
    return context, errors, messages


def validate_project(args: argparse.Namespace, contract: dict[str, Any]) -> int:
    project_dir = Path(args.project_dir).resolve()
    if not project_dir.is_dir():
        print(f"FAIL: Project directory not found: {project_dir}", file=sys.stderr)
        return contract["outcome_exit_codes"]["invalid"]

    state_path = project_dir / contract["state"]["file"]
    stateless_requested = args.operation == "review"
    if stateless_requested:
        context, errors, messages = validate_stateless_workflow(project_dir, args, contract)
    elif state_path.is_file():
        context, errors, messages = validate_stateful(project_dir, args, contract)
    else:
        context, errors, messages = validate_stateless_workflow(project_dir, args, contract)

    if errors or context is None:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        print(f"Workflow validation failed with {len(errors)} error(s).", file=sys.stderr)
        return contract["outcome_exit_codes"]["invalid"]

    for message in messages:
        print(f"PASS: {message}")
    print(f"Operation: {context.operation}")
    print(f"Outcome: {context.outcome}")

    if context.outcome == "blocked":
        print("BLOCKED: Workflow state is valid but work remains blocked.", file=sys.stderr)
    elif context.outcome == "in-progress":
        print("IN-PROGRESS: Workflow state is valid but not complete.", file=sys.stderr)
    else:
        print(f"Workflow gate check passed with outcome {context.outcome}.")
    return contract["outcome_exit_codes"][context.outcome]


def parse_skill_frontmatter(path: Path) -> tuple[dict[str, str], list[str]]:
    errors: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        return {}, [f"Cannot read UTF-8 SKILL.md: {exc}"]
    if not lines or lines[0] != "---":
        return {}, ["SKILL.md must start with YAML frontmatter."]
    try:
        closing = lines.index("---", 1)
    except ValueError:
        return {}, ["SKILL.md frontmatter is not closed."]
    metadata: dict[str, str] = {}
    for line_number, line in enumerate(lines[1:closing], start=2):
        match = FIELD_RE.match(line)
        if not match:
            errors.append(f"SKILL.md:{line_number}: invalid frontmatter line.")
            continue
        key = match.group(1).strip()
        value = match.group(2).strip()
        if key in metadata:
            errors.append(f"SKILL.md:{line_number}: duplicate frontmatter field: {key}")
        metadata[key] = value
    if set(metadata) != {"name", "description"}:
        errors.append("SKILL.md frontmatter must contain only name and description.")
    if metadata.get("name") != "pdf-to-latex":
        errors.append("SKILL.md frontmatter name must be pdf-to-latex.")
    description = metadata.get("description", "")
    if len(description) < 2 or description[0] != '"' or description[-1] != '"':
        errors.append("SKILL.md description must be a non-empty quoted string.")
    return metadata, errors


def referenced_resources(skill_dir: Path) -> tuple[set[str], list[str]]:
    resources: set[str] = set()
    errors: list[str] = []
    markdown_files = [skill_dir / "SKILL.md"]
    references_dir = skill_dir / "references"
    if references_dir.is_dir():
        markdown_files.extend(sorted(references_dir.glob("*.md")))
    for path in markdown_files:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"Cannot read UTF-8 resource references from {path}: {exc}")
            continue
        resources.update(match.group(1) for match in RESOURCE_RE.finditer(text))
    return resources, errors


def validate_package(skill_dir: Path, contract: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required_paths = (
        "SKILL.md",
        GOAL_REFERENCE,
        "references/workflow-contract.json",
        SELF_UPDATE_SCRIPT,
        "scripts/workflow_contract.py",
        "scripts/check_workflow_gates.sh",
        "assets/templates/main.tex",
        "assets/templates/worker-brief.md",
    )
    for relative in required_paths:
        if not (skill_dir / relative).is_file():
            errors.append(f"Missing package file: {relative}")

    if (skill_dir / "agents").exists():
        errors.append("Codex-only agents/ metadata must not be packaged for Grok.")
    if (skill_dir / "agents/openai.yaml").is_file():
        errors.append("agents/openai.yaml is not part of the Grok skill package.")

    if (skill_dir / "SKILL.md").is_file():
        skill_metadata, frontmatter_errors = parse_skill_frontmatter(
            skill_dir / "SKILL.md"
        )
        errors.extend(frontmatter_errors)
        description = skill_metadata.get("description", "")
        description_lower = description.lower()
        if SELF_UPDATE_TRIGGER not in description_lower:
            errors.append(
                f"SKILL.md description must advertise the {SELF_UPDATE_TRIGGER} trigger."
            )
        if SELF_UPDATE_TRIGGER_ZH not in description:
            errors.append(
                f"SKILL.md description must advertise the {SELF_UPDATE_TRIGGER_ZH} trigger."
            )
        if SELF_INSTALL_TRIGGER not in description_lower:
            errors.append(
                f"SKILL.md description must advertise the {SELF_INSTALL_TRIGGER} trigger."
            )
        if SELF_INSTALL_TRIGGER_ZH not in description:
            errors.append(
                f"SKILL.md description must advertise the {SELF_INSTALL_TRIGGER_ZH} trigger."
            )
        if "/pdf-to-latex" not in description:
            errors.append("SKILL.md description must advertise the /pdf-to-latex slash command.")
        try:
            skill_text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            skill_text = ""
        if skill_text:
            if GOAL_REFERENCE not in skill_text:
                errors.append(f"SKILL.md must reference {GOAL_REFERENCE}.")
            if GOAL_POLICY_MARKER not in skill_text.lower():
                errors.append(
                    "SKILL.md must never block on Goal startup (auto-start continuity)."
                )
            if GOAL_RESUMABLE_DEFAULT_MARKER not in skill_text.lower():
                errors.append(
                    "SKILL.md must use resumable by default when Goal is not already active."
                )
            if SELF_UPDATE_SCRIPT not in skill_text:
                errors.append(f"SKILL.md must reference {SELF_UPDATE_SCRIPT}.")
            if SELF_UPDATE_COMMAND not in skill_text:
                errors.append("SKILL.md must invoke the self-updater through Bash.")
            if SELF_UPDATE_EXACT_ROUTE_MARKER not in skill_text.lower():
                errors.append("SKILL.md must restrict self-update to exact command forms.")
            lowered = skill_text.lower()
            if "codex" in lowered or "$pdf-to-latex" in skill_text:
                errors.append("SKILL.md must not reference Codex or $pdf-to-latex.")

    goal_reference = skill_dir / GOAL_REFERENCE
    if goal_reference.is_file():
        try:
            goal_text = goal_reference.read_text(encoding="utf-8")
            goal_text_lower = goal_text.lower()
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(f"Cannot read UTF-8 {GOAL_REFERENCE}: {exc}")
        else:
            required_goal_rules = {
                GOAL_POLICY_MARKER: "never block on Goal startup",
                GOAL_RESUMABLE_DEFAULT_MARKER: "resumable default when Goal inactive",
                "do not ask for separate goal confirmation": "no separate Goal confirmation",
                "never lower delivery quality": "quality independent of Goal",
                "user-decision": "user-decision stop boundary",
                "check current goal state": "existing Goal inspection",
                "do not set a token budget unless the user explicitly requested one": "explicit token-budget authority",
                "mark a matching goal complete only after": "terminal completion validation",
                "blocker threshold": "Goal blocker-threshold handling",
                "update_goal": "Grok update_goal progress/completion",
                "spawn_subagent": "Grok spawn_subagent workers",
                "prefer `spawn_subagent`": "prefer subagents for multi-page work",
                "compact context packet": "minimal worker context",
                "run until complete": "run-to-completion default",
                "never ask the user to type": "no continue/继续 prompts",
                "worker-brief": "worker brief standing orders",
                "conversion-state.md": "project state authoritative",
            }
            for marker, label in required_goal_rules.items():
                if marker.lower() not in goal_text_lower:
                    errors.append(f"{GOAL_REFERENCE} is missing required rule: {label}.")
            # Optional multi-session pin may mention /goal, but hard-wait wording is forbidden.
            if "continue only after" in goal_text_lower and "goal" in goal_text_lower:
                errors.append(
                    f"{GOAL_REFERENCE} must not hard-wait for Goal activation before work."
                )
            if "codex" in goal_text_lower or "$pdf-to-latex" in goal_text:
                errors.append(f"{GOAL_REFERENCE} must not reference Codex or $pdf-to-latex.")

    resources, resource_errors = referenced_resources(skill_dir)
    errors.extend(resource_errors)
    for relative in sorted(resources):
        if not (skill_dir / relative).exists():
            errors.append(f"Referenced skill resource does not exist: {relative}")

    template_files = {
        required
        for rule in contract["path_rules"]
        for required in rule["require_files"]
    }
    for relative in sorted(template_files):
        template = skill_dir / "assets" / "templates" / relative
        if not template.is_file():
            errors.append(f"Contract-required file has no bundled template: {relative}")

    state_template = skill_dir / "assets/templates/conversion-state.md"
    if state_template.is_file():
        text = state_template.read_text(encoding="utf-8")
        for label in contract["state"]["required_metadata"]:
            if not re.search(rf"^{re.escape(label)}:", text, flags=re.MULTILINE):
                errors.append(f"conversion-state.md template is missing metadata field: {label}")
        if re.search(r"^Task profile:", text, flags=re.MULTILINE):
            errors.append("conversion-state.md template contains unsupported Task profile metadata.")

    scripts_dir = skill_dir / "scripts"
    if scripts_dir.is_dir():
        for path in sorted(scripts_dir.iterdir()):
            if path.is_file() and path.suffix in {".sh", ".py"} and not os.access(path, os.X_OK):
                errors.append(f"Helper script is not executable: scripts/{path.name}")

    forbidden_names = {"README.md", "INSTALL.md", "CHANGELOG.md"}
    for name in forbidden_names:
        if (skill_dir / name).exists():
            errors.append(f"Development documentation must not be bundled in the skill: {name}")
    for path in skill_dir.rglob("*"):
        if path.name == "__pycache__" or path.suffix in {
            ".pyc",
            ".aux",
            ".log",
            ".out",
            ".pdf",
        }:
            errors.append(f"Generated artifact must not be bundled: {path.relative_to(skill_dir)}")
    return errors


def add_context_arguments(parser: argparse.ArgumentParser, include_outcome: bool = True) -> None:
    parser.add_argument("--operation")
    parser.add_argument("--source-kind", dest="source_kind")
    parser.add_argument("--traits", dest="document_traits")
    parser.add_argument("--delivery-level", dest="delivery_level")
    parser.add_argument("--execution-mode", dest="execution_mode")
    parser.add_argument("--verification-scope", dest="verification_scope")
    if include_outcome:
        parser.add_argument("--outcome")


def context_from_query_args(args: argparse.Namespace, contract: dict[str, Any]) -> Context:
    values = cli_values(args)
    if values["outcome"] is None:
        values["outcome"] = "in-progress"
    return context_from_values(values, contract)


def output_values(values: Sequence[str], output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(list(values), indent=2))
    else:
        for value in values:
            print(value)


def build_parser() -> ExitOneArgumentParser:
    parser = ExitOneArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="Validate a workflow project.")
    validate.add_argument("project_dir", nargs="?", default=".")
    add_context_arguments(validate)
    validate.add_argument("--compile-check", dest="compile_check")
    validate.add_argument("--visual-review", dest="visual_review")
    validate.add_argument("--source-fidelity", dest="source_fidelity")
    validate.add_argument("--next-action", dest="next_action")
    validate.add_argument("--source-pdf", dest="source_pdf")
    validate.add_argument("--source-sha256", dest="source_sha256")
    validate.add_argument("--source-size-bytes", dest="source_size_bytes")
    validate.add_argument("--source-page-count", dest="source_page_count")
    validate.add_argument("--previous-delivery-level", dest="previous_delivery_level")
    validate.add_argument("--downgrade-approval", dest="downgrade_approval")
    validate.add_argument(
        "--blocker",
        nargs=3,
        action="append",
        metavar=("ID", "REASON", "NEXT_ACTION"),
        help="Record one blocker for a stateless review; may be repeated.",
    )
    validate.add_argument(
        "--gate",
        nargs=2,
        action="append",
        metavar=("ID", "STATUS"),
        help="Record one required stateless gate and its lifecycle status; may be repeated.",
    )

    for name, help_text in (
        ("required-files", "Print files required by a workflow context."),
        ("required-gates", "Print gates required by a workflow context."),
    ):
        query = subparsers.add_parser(name, help=help_text)
        add_context_arguments(query, include_outcome=False)
        query.add_argument("--format", choices=("lines", "json"), default="lines")

    render = subparsers.add_parser(
        "render-gates", help="Render initial Markdown records for required gates."
    )
    add_context_arguments(render, include_outcome=False)

    normalize = subparsers.add_parser(
        "normalize-context", help="Print the canonical workflow context as JSON."
    )
    add_context_arguments(normalize, include_outcome=False)

    subparsers.add_parser("validate-contract", help="Validate the JSON contract itself.")
    package = subparsers.add_parser(
        "validate-package", help="Validate a complete installable skill directory."
    )
    package.add_argument("skill_dir")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        require_python()
        parser = build_parser()
        args = parser.parse_args(argv)
        if args.command == "validate-package":
            skill_dir = Path(args.skill_dir).resolve()
            if not skill_dir.is_dir():
                raise WorkflowError(f"Skill directory not found: {skill_dir}")
            contract_path = skill_dir / "references/workflow-contract.json"
        else:
            contract_path = args.contract.resolve()
        contract = load_contract(contract_path)

        if args.command == "validate-contract":
            print(f"Workflow contract is valid: {contract_path}")
            return 0
        if args.command == "validate-package":
            errors = validate_package(skill_dir, contract)
            if errors:
                for error in errors:
                    print(f"FAIL: {error}", file=sys.stderr)
                print(f"Package validation failed with {len(errors)} error(s).", file=sys.stderr)
                return 1
            print(f"Skill package is valid: {skill_dir}")
            return 0
        if args.command == "validate":
            return validate_project(args, contract)

        context = context_from_query_args(args, contract)
        context_errors = validate_context_constraints(context, contract)
        if context_errors:
            raise WorkflowError(" ".join(context_errors))
        if args.command == "required-files":
            output_values(required_files(contract, context), args.format)
            return 0
        if args.command == "required-gates":
            output_values(required_gates(contract, context), args.format)
            return 0
        if args.command == "normalize-context":
            print(json.dumps(context_values(context, contract), indent=2))
            return 0
        if args.command == "render-gates":
            gates = required_gates(contract, context)
            for index, gate_id in enumerate(gates):
                if index:
                    print()
                print(f"### Gate: {gate_id}")
                print("Status: pending")
                print("Reason:")
                print(f"Next action: Complete and verify the {gate_id} gate.")
            return 0
        raise WorkflowError(f"Unsupported command: {args.command}")
    except WorkflowError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
