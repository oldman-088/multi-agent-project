"""Structured JSON logging with secret redaction (SPEC §3.2, §4.2)."""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

REDACTED = "***redacted***"

# Keys whose values must never reach a log sink.
SECRET_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "password_hash",
        "hashed_password",
        "token",
        "access_token",
        "refresh_token",
        "authorization",
        "api_key",
        "apikey",
        "secret",
        "jwt_secret",
        "encryption_key",
        "credential",
        "cookie",
        "set-cookie",
    }
)

# Substring markers: any key containing one of these is redacted too.
SECRET_MARKERS: tuple[str, ...] = ("password", "secret", "token", "api_key", "credential")


def redact(value: Any, *, _depth: int = 0) -> Any:
    """Recursively replace secret-looking values. Never logs prompt content."""
    if _depth > 8:  # defensive: never recurse unboundedly
        return "<max-depth>"
    if isinstance(value, dict):
        clean: dict[Any, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in SECRET_KEYS or any(marker in lowered for marker in SECRET_MARKERS):
                clean[key] = REDACTED if item else item
            else:
                clean[key] = redact(item, _depth=_depth + 1)
        return clean
    if isinstance(value, (list, tuple)):
        return [redact(item, _depth=_depth + 1) for item in value]
    return value


class JsonFormatter(logging.Formatter):
    """One JSON object per line, secrets redacted, exception text preserved."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(redact(extra))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(redact(payload), ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
