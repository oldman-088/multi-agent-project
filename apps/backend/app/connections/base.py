"""ModelConnection interface (docs/SPEC.md section 4.4) and shared value types.

Capabilities are declared honestly: each flag is one of
supported | partial | unsupported | not_verified. Usage is reported only when the
provider returned it; it is never estimated.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

Capability = Literal["supported", "partial", "unsupported", "not_verified"]
CAPABILITY_VALUES: frozenset[str] = frozenset(
    {"supported", "partial", "unsupported", "not_verified"}
)
ConnectionKind = Literal["browser_session", "local", "api", "mcp", "cli", "custom"]
HealthStatus = Literal["ok", "degraded", "offline", "disabled"]

_CAPABILITY_FIELDS = (
    "streaming",
    "native_tool_calling",
    "structured_output",
    "multimodal_input",
    "usage_reporting",
    "agent_mode",
)


class UnsupportedOperation(Exception):
    """Raised for operations a connection declares as unsupported."""


class ConnectionRequestFailed(Exception):
    """A generation request failed. `code` is a stable, non-secret error code."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


@dataclass(frozen=True)
class ConnectionCapabilities:
    streaming: Capability = "not_verified"
    native_tool_calling: Capability = "not_verified"
    structured_output: Capability = "not_verified"
    multimodal_input: Capability = "not_verified"
    usage_reporting: Capability = "not_verified"
    agent_mode: Capability = "not_verified"
    # None means "not verified". Numeric limits are never guessed.
    max_concurrency: int | None = None
    max_prompt_characters: int | None = None

    def __post_init__(self) -> None:
        for name in _CAPABILITY_FIELDS:
            value = getattr(self, name)
            if value not in CAPABILITY_VALUES:
                raise ValueError(f"invalid capability {name}={value!r}")


@dataclass(frozen=True)
class GenerationRequest:
    prompt: str
    system: str | None = None
    timeout_s: float = 120.0
    idempotency_key: str | None = None


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int
    completion_tokens: int


@dataclass(frozen=True)
class GenerationResult:
    text: str
    connection_id: str
    usage: Usage | None = None
    model: str | None = None


@dataclass(frozen=True)
class GenerationChunk:
    text: str
    done: bool = False
    usage: Usage | None = None


@dataclass(frozen=True)
class ConnectionHealth:
    status: HealthStatus
    detail: str  # human-readable, never contains secrets


@runtime_checkable
class ModelConnection(Protocol):
    id: str
    kind: ConnectionKind

    async def capabilities(self) -> ConnectionCapabilities: ...

    async def generate(self, request: GenerationRequest) -> GenerationResult: ...

    def stream(self, request: GenerationRequest) -> AsyncIterator[GenerationChunk]: ...

    async def health(self) -> ConnectionHealth: ...


def compose_prompt(request: GenerationRequest) -> str:
    """Single-string prompt for providers without a separate system channel."""
    if request.system:
        return f"{request.system}\n\n{request.prompt}"
    return request.prompt
