"""Constants and wire models for the Local Browser Bridge.

Mirrors docs/PROTOCOL.md. Change both together.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PROTOCOL_VERSION = 1
MIN_SCRIPT_VERSION: tuple[int, ...] = (1, 0, 0)
HELLO_TIMEOUT_S = 10.0
MAX_FRAME_CHARS = 65_536
MAX_PROMPT_CHARS = 20_000
MAX_DELTA_CHARS = 4_000
MAX_RESULT_CHARS = 200_000
MAX_REQUEST_TIMEOUT_S = 600.0
PAIRING_CODE_TTL_S = 300.0
PAIRING_CODE_LENGTH = 8
# Unambiguous alphabet: no I, O, 0, 1, L.
PAIRING_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


class CloseCode(IntEnum):
    BAD_MESSAGE = 4400
    BAD_CREDENTIAL = 4401
    BAD_PAIRING_CODE = 4402
    ORIGIN_REFUSED = 4403
    NOT_REGISTERED = 4404
    HELLO_TIMEOUT = 4408
    SCRIPT_TOO_OLD = 4409
    REVOKED = 4410
    REPLACED = 4411


class SessionState(StrEnum):
    DISCONNECTED = "DISCONNECTED"
    PAIRING_REQUIRED = "PAIRING_REQUIRED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    AUTHENTICATED = "AUTHENTICATED"
    READY = "READY"
    BUSY = "BUSY"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    RATE_LIMITED = "RATE_LIMITED"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    ERROR = "ERROR"


class RequestStatus(StrEnum):
    QUEUED = "queued"
    DISPATCHED = "dispatched"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ErrorCode(StrEnum):
    SELECTOR_NOT_FOUND = "SELECTOR_NOT_FOUND"
    SEND_FAILED = "SEND_FAILED"
    GENERATION_TIMEOUT = "GENERATION_TIMEOUT"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    RATE_LIMITED = "RATE_LIMITED"
    USER_ACTION_REQUIRED = "USER_ACTION_REQUIRED"
    TOOL_CALL_LIMIT = "TOOL_CALL_LIMIT"
    UNCERTAIN_SUBMISSION = "UNCERTAIN_SUBMISSION"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
    DEVICE_OFFLINE = "DEVICE_OFFLINE"
    PROVIDER_ERROR = "PROVIDER_ERROR"


class HelloMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["hello"]
    script_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    device_id: str | None = Field(default=None, max_length=64)
    credential: str | None = Field(default=None, max_length=256)
    pairing_code: str | None = Field(default=None, max_length=16)
    device_name: str = Field(default="browser", max_length=64)


class HeartbeatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["heartbeat"]


class TabStateMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["tab_state"]
    tab_id: str = Field(min_length=1, max_length=64)
    state: SessionState
    agent_state: str | None = Field(default=None, max_length=64)


class DeltaMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["delta"]
    request_id: str = Field(min_length=1, max_length=64)
    text: str = Field(max_length=MAX_DELTA_CHARS)


class ResultMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["result"]
    request_id: str = Field(min_length=1, max_length=64)
    status: Literal["completed", "failed"]
    text: str | None = Field(default=None, max_length=MAX_RESULT_CHARS)
    error_code: str | None = Field(default=None, max_length=64)


class RequestIn(BaseModel):
    """Body of POST /api/tabs/{tab_id}/requests."""

    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=MAX_PROMPT_CHARS)
    idempotency_key: str = Field(min_length=1, max_length=128)
    timeout_s: float = Field(default=120.0, gt=0, le=MAX_REQUEST_TIMEOUT_S)
