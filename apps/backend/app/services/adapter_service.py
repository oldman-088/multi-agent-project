"""Adapter YAML validation against a JSON Schema (SPEC §6 Phase 1, item 3).

Adapters are data, not code: selectors, stop selectors, completion rules and
capabilities live in YAML so a provider redesign means editing YAML rather than
rebuilding the userscript.
"""

from __future__ import annotations

import json
from typing import Any

import jsonschema
import yaml

from app.core.errors import ValidationFailedError
from app.schemas.connections import SelectorCheck, SelectorTestResult

CAPABILITY_VALUES = {"supported", "partial", "unsupported", "not_verified"}

ADAPTER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["id", "version", "selectors"],
    "additionalProperties": True,
    "properties": {
        "id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 80,
            "pattern": "^[a-z0-9][a-z0-9_-]*$",
        },
        "version": {"type": "integer", "minimum": 1},
        "display_name": {"type": "string", "maxLength": 120},
        "origin": {"type": "string", "maxLength": 400},
        "selectors": {
            "type": "object",
            "required": ["input", "send", "reply"],
            "additionalProperties": {"type": "string", "minLength": 1, "maxLength": 400},
            "properties": {
                "input": {"type": "string", "minLength": 1},
                "send": {"type": "string", "minLength": 1},
                "reply": {"type": "string", "minLength": 1},
                "stop": {"type": "string"},
                "generating_indicator": {"type": "string"},
                "keep_working": {"type": "string"},
                "pr_button": {"type": "string"},
                "repository_selector": {"type": "string"},
            },
        },
        "stop_selectors": {
            "type": "array",
            "maxItems": 40,
            "items": {
                "type": "object",
                "required": ["name", "selector"],
                "properties": {
                    "name": {
                        "type": "string",
                        "enum": [
                            "captcha",
                            "challenge",
                            "login_wall",
                            "terms_prompt",
                            "verification",
                        ],
                    },
                    "selector": {"type": "string", "minLength": 1, "maxLength": 400},
                },
                "additionalProperties": False,
            },
        },
        "completion": {
            "type": "object",
            "properties": {
                "indicator_disappears": {"type": "boolean"},
                "stable_ms": {"type": "integer", "minimum": 0, "maximum": 60_000},
                "hard_timeout_ms": {"type": "integer", "minimum": 1000, "maximum": 600_000},
            },
            "additionalProperties": False,
        },
        "capabilities": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "streaming": {"type": "string", "enum": sorted(CAPABILITY_VALUES)},
                "agent_mode": {"type": "string", "enum": sorted(CAPABILITY_VALUES)},
                "repository_selector": {"type": "string", "enum": sorted(CAPABILITY_VALUES)},
                "create_pr": {"type": "string", "enum": sorted(CAPABILITY_VALUES)},
            },
        },
    },
}


def parse_adapter_yaml(yaml_body: str) -> dict[str, Any]:
    try:
        document = yaml.safe_load(yaml_body)
    except yaml.YAMLError as exc:
        raise ValidationFailedError(
            "Adapter YAML is not valid YAML",
            code="invalid_adapter_yaml",
            details={"error": str(exc)},
        ) from exc
    if not isinstance(document, dict):
        raise ValidationFailedError("Adapter YAML must be a mapping", code="invalid_adapter_yaml")
    return document


def validate_adapter_yaml(yaml_body: str) -> dict[str, Any]:
    """Parse and validate. Returns the document so callers can log its keys."""
    document = parse_adapter_yaml(yaml_body)
    try:
        jsonschema.validate(instance=document, schema=ADAPTER_SCHEMA)
    except jsonschema.ValidationError as exc:
        raise ValidationFailedError(
            f"Adapter does not match the schema: {exc.message}",
            code="invalid_adapter_yaml",
            details={"path": [str(part) for part in exc.absolute_path]},
        ) from exc
    return document


def required_selectors(document: dict[str, Any]) -> list[SelectorCheck]:
    selectors = document.get("selectors") or {}
    checks = [
        SelectorCheck(selector=selectors[key], required=True) for key in ("input", "send", "reply")
    ]
    for optional in (
        "stop",
        "generating_indicator",
        "keep_working",
        "pr_button",
        "repository_selector",
    ):
        if selectors.get(optional):
            checks.append(SelectorCheck(selector=selectors[optional], required=False))
    for stop in document.get("stop_selectors") or []:
        checks.append(SelectorCheck(selector=stop["selector"], required=False))
    return checks


def run_selector_test(
    document: dict[str, Any], present_selectors: list[str] | None = None
) -> SelectorTestResult:
    """Dry-run of the selector test.

    ``present_selectors`` is what the bridge reports from the live page. When it
    is ``None`` the test only validates the adapter's shape, and reports that the
    live page was not checked — it never claims a selector passed unseen.
    """
    checks = required_selectors(document)
    if present_selectors is None:
        return SelectorTestResult(
            valid=True,
            checks=checks,
            missing=[],
            errors=["live page not checked: no page snapshot supplied by the bridge"],
        )
    present = set(present_selectors)
    missing = [
        check.selector for check in checks if check.required and check.selector not in present
    ]
    return SelectorTestResult(
        valid=not missing,
        checks=checks,
        missing=missing,
        errors=[] if not missing else [f"required selector not found: {item}" for item in missing],
    )


def document_to_json(document: dict[str, Any]) -> str:
    """Stable JSON rendering used by tests and the adapter editor's preview."""
    return json.dumps(document, ensure_ascii=False, sort_keys=True)
