"""Built-in tools for the Tool Registry (docs/SPEC.md §2 Phase 2 item 7).

Four safe built-ins, each with a JSON Schema for its arguments:

- ``calculator``      — safe AST-based arithmetic (no eval, no names).
- ``current_time``    — current UTC time.
- ``knowledge_search``— stub that honestly reports ``not_configured``.
- ``http_get``        — HTTP GET restricted to the configured host allow-list
                         (SSRF guard). Flagged ``requires_approval``: the
                         gateway routes it through the approval hook (§3.2).

Executors raise :class:`ToolExecutionError` on operational failure; argument
validation happens against the JSON Schema in the gateway before execution.
"""

from __future__ import annotations

import ast
import operator
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

import httpx
from jsonschema import Draft7Validator

from backend.app.core.config import Settings


class ToolExecutionError(Exception):
    """A tool ran (or failed before running) and reports an operational error."""


Executor = Callable[[dict[str, Any], Settings], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    executor: Executor
    requires_approval: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------
# calculator — AST-walked arithmetic, no eval, no names, bounded magnitudes.
# --------------------------------------------------------------------------

_BIN_OPS: dict[type[ast.AST], Any] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_MAX_EXPONENT = 1_000
_MAX_OPERAND_ABS = 10**15


def _eval_node(node: ast.AST) -> int | float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        if abs(node.value) > _MAX_OPERAND_ABS:
            raise ToolExecutionError("calculator: operand too large")
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left, right = _eval_node(node.left), _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > _MAX_EXPONENT:
            raise ToolExecutionError("calculator: exponent too large")
        try:
            result = cast("int | float", _BIN_OPS[type(node.op)](left, right))
        except ZeroDivisionError as exc:
            raise ToolExecutionError("calculator: division by zero") from exc
        if isinstance(result, complex):
            raise ToolExecutionError("calculator: complex results are not supported")
        if abs(result) > _MAX_OPERAND_ABS * 10**6:
            raise ToolExecutionError("calculator: result too large")
        return result
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval_node(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value
    raise ToolExecutionError("calculator: only arithmetic expressions are allowed")


async def _execute_calculator(arguments: dict[str, Any], _settings: Settings) -> dict[str, Any]:
    expression = str(arguments["expression"])
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ToolExecutionError(f"calculator: invalid expression ({exc.msg})") from exc
    value = _eval_node(tree)
    return {"expression": expression, "result": value}


# --------------------------------------------------------------------------
# current_time
# --------------------------------------------------------------------------


async def _execute_current_time(_arguments: dict[str, Any], _settings: Settings) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {"utc": now.isoformat().replace("+00:00", "Z"), "epoch_seconds": int(now.timestamp())}


# --------------------------------------------------------------------------
# knowledge_search — honest stub (docs/SPEC.md §2 Phase 2 item 7).
# --------------------------------------------------------------------------


async def _execute_knowledge_search(
    arguments: dict[str, Any], _settings: Settings
) -> dict[str, Any]:
    return {"status": "not_configured", "query": str(arguments["query"]), "results": []}


# --------------------------------------------------------------------------
# http_get — allow-listed hosts only; redirects are NOT followed (they could
# silently leave the allow-list); response size and time are capped.
# NOTE: no credential-carrying arguments (headers/tokens) are supported —
# provider secrets belong in the Phase 2 encrypted-credentials store, not in
# tool arguments.
# --------------------------------------------------------------------------


def _hostname_of(url: str) -> str:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ToolExecutionError("http_get: only http/https URLs are allowed")
    host = parsed.hostname
    if not host:
        raise ToolExecutionError("http_get: URL has no host")
    return host


async def _execute_http_get(arguments: dict[str, Any], settings: Settings) -> dict[str, Any]:
    url = str(arguments["url"])
    try:
        async with httpx.AsyncClient(
            timeout=settings.tool_http_timeout_seconds, follow_redirects=False
        ) as client:
            response = await client.get(url)
    except (httpx.HTTPError, OSError) as exc:
        raise ToolExecutionError(f"http_get_failed: {type(exc).__name__}") from exc
    body = response.text[: settings.tool_http_max_bytes]
    return {
        "url": url,
        "status_code": response.status_code,
        "content_type": response.headers.get("content-type", ""),
        "truncated": len(response.text) > len(body),
        "body": body,
    }


# --------------------------------------------------------------------------
# Registry (docs/SPEC.md §2 Phase 2: Tool Registry + Tool Gateway)
# --------------------------------------------------------------------------

TOOL_SPECS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in [
        ToolSpec(
            name="calculator",
            description="Evaluate a safe arithmetic expression (no eval, no names).",
            input_schema={
                "type": "object",
                "properties": {"expression": {"type": "string", "minLength": 1}},
                "required": ["expression"],
                "additionalProperties": False,
            },
            executor=_execute_calculator,
        ),
        ToolSpec(
            name="current_time",
            description="Return the current UTC time.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
            executor=_execute_current_time,
        ),
        ToolSpec(
            name="knowledge_search",
            description="Knowledge search stub; reports not_configured until Phase 6.",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string", "minLength": 1}},
                "required": ["query"],
                "additionalProperties": False,
            },
            executor=_execute_knowledge_search,
        ),
        ToolSpec(
            name="http_get",
            description=(
                "HTTP GET restricted to the configured host allow-list; "
                "requires human approval (approval hook)."
            ),
            input_schema={
                "type": "object",
                "properties": {"url": {"type": "string", "minLength": 1}},
                "required": ["url"],
                "additionalProperties": False,
            },
            executor=_execute_http_get,
            requires_approval=True,
        ),
    ]
}


def get_spec(tool_name: str) -> ToolSpec | None:
    return TOOL_SPECS.get(tool_name)


def validate_arguments(spec: ToolSpec, arguments: dict[str, Any]) -> list[str]:
    """Validate arguments against the tool's JSON Schema; return error strings."""
    validator = Draft7Validator(spec.input_schema)
    return [error.message for error in sorted(validator.iter_errors(arguments), key=str)]


__all__ = [
    "TOOL_SPECS",
    "ToolExecutionError",
    "ToolSpec",
    "get_spec",
    "validate_arguments",
]
