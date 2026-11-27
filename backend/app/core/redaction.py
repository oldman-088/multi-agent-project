"""Key-based secret redaction for persisted payloads (docs/SPEC.md §7).

Every event payload and every persisted tool-call argument/result passes
through :func:`redact_mapping` so that credentials never land in the events
table or the audit log, even when a caller includes them by mistake.
"""

from __future__ import annotations

import re
from typing import Any

REDACTED = "***"

_SENSITIVE_KEY = re.compile(
    r"(pass(word)?|secret|token|api[-_]?key|authorization|cookie|credential)",
    re.IGNORECASE,
)

_MAX_REDACTION_DEPTH = 6


def is_sensitive_key(key: str) -> bool:
    return bool(_SENSITIVE_KEY.search(key))


def redact_value(value: Any, _depth: int = 0) -> Any:
    """Return a copy of ``value`` with sensitive mapping values replaced."""
    if _depth > _MAX_REDACTION_DEPTH:
        return "[depth-limit]"
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_str = str(key)
            if is_sensitive_key(key_str):
                redacted[key_str] = REDACTED
            else:
                redacted[key_str] = redact_value(item, _depth + 1)
        return redacted
    if isinstance(value, (list, tuple)):
        return [redact_value(item, _depth + 1) for item in value]
    return value


__all__ = ["REDACTED", "is_sensitive_key", "redact_value"]
