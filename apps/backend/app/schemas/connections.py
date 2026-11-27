"""Connection Manager schemas: providers, credentials, connections, tabs, adapters."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models.enums import (
    AgentPageState,
    BrowserSessionState,
    ConnectionKind,
    ConnectionStatus,
    RuntimeKind,
)
from app.schemas.common import ORMModel

CapabilityStatus = RuntimeKind


class CapabilityFlags(BaseModel):
    """Honest capability declaration (SPEC §4.4). No value is ever guessed."""

    streaming: CapabilityStatus = RuntimeKind.NOT_VERIFIED
    native_tool_calling: CapabilityStatus = RuntimeKind.NOT_VERIFIED
    structured_output: CapabilityStatus = RuntimeKind.NOT_VERIFIED
    multimodal_input: CapabilityStatus = RuntimeKind.NOT_VERIFIED
    usage_reporting: CapabilityStatus = RuntimeKind.NOT_VERIFIED
    agent_mode: CapabilityStatus = RuntimeKind.NOT_VERIFIED
    max_concurrency: int = 1
    max_prompt_characters: int = 120_000


class CredentialCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["api_key", "password", "cookie", "token"] = "api_key"
    #: Either ``env:VAR_NAME`` or the raw value, which is encrypted before storage.
    value: str = Field(
        min_length=1,
        max_length=8000,
        description="Raw secret (encrypted at rest) or an env:VAR_NAME reference.",
    )


class CredentialOut(ORMModel):
    id: str
    name: str
    kind: str
    credential_ref: str | None = None
    last_used_at: datetime | None = None
    created_at: datetime


class ProviderOut(ORMModel):
    id: str
    slug: str
    display_name: str
    kind: ConnectionKind
    enabled: bool
    base_url: str | None = None


class ConnectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    provider_slug: str = Field(min_length=1, max_length=80, examples=["mock", "ollama"])
    kind: ConnectionKind
    model: str | None = Field(default=None, max_length=160)
    base_url: str | None = Field(default=None, max_length=400)
    credential_id: str | None = None
    options: dict = Field(default_factory=dict)


class ConnectionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    status: ConnectionStatus | None = None
    model: str | None = Field(default=None, max_length=160)
    base_url: str | None = Field(default=None, max_length=400)
    options: dict | None = None


class ConnectionOut(ORMModel):
    id: str
    name: str
    kind: ConnectionKind
    status: ConnectionStatus
    #: Resolved from the provider row by the route, never stored on the connection.
    provider_slug: str = ""
    model: str | None = None
    base_url: str | None = None
    capabilities: dict
    terms_acknowledged: bool = False
    created_at: datetime


class TermsAckOut(BaseModel):
    """One notice, one acknowledgement per connection (SPEC §3.1)."""

    connection_id: str
    acknowledged: bool
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = None
    notice: str


class BrowserSessionOut(ORMModel):
    id: str
    profile_id: str
    provider_slug: str
    state: BrowserSessionState
    agent_page_state: str | None = None
    url: str | None = None
    title: str | None = None
    queue_depth: int
    last_error: str | None = None
    granted_agent_id: str | None = None


class BrowserSessionUpdate(BaseModel):
    state: BrowserSessionState | None = None
    agent_page_state: AgentPageState | None = None
    url: str | None = Field(default=None, max_length=600)
    title: str | None = Field(default=None, max_length=300)
    last_error: str | None = Field(default=None, max_length=400)


class GrantSessionRequest(BaseModel):
    """An agent may only use a browser session explicitly granted to it."""

    agent_id: str


class PairingRequest(BaseModel):
    label: str = Field(min_length=1, max_length=120, examples=["Chrome — work profile"])
    userscript_version: str = Field(min_length=1, max_length=32, examples=["1.0.0"])


class PairingResponse(BaseModel):
    device_id: str
    credential: str = Field(description="Returned once. Only its hash is stored.")
    expires_in: int = 300


class AdapterCreate(BaseModel):
    provider_slug: str = Field(min_length=1, max_length=80)
    yaml_body: str = Field(min_length=1, max_length=100_000)
    notes: str | None = Field(default=None, max_length=400)


class AdapterOut(ORMModel):
    id: str
    provider_slug: str
    version: int
    yaml_body: str
    is_active: bool
    notes: str | None = None
    created_at: datetime


class SelectorTestRequest(BaseModel):
    yaml_body: str = Field(min_length=1, max_length=100_000)


class SelectorCheck(BaseModel):
    selector: str
    required: bool = True


class SelectorTestResult(BaseModel):
    """Result of checking adapter selectors against a page (SPEC §6 P1 item 7)."""

    valid: bool
    missing: list[str] = Field(default_factory=list)
    checks: list[SelectorCheck] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class TeamOut(ORMModel):
    id: str
    slug: str
    name: str
    pattern: str
    description: str
    is_enabled: bool


class ScheduleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    kind: Literal["once", "interval", "cron"] = "once"
    expression: str = Field(default="", max_length=120)
    timezone: str = Field(default="UTC", max_length=64)
    directive: str = Field(default="", max_length=20_000)
    agent_id: str | None = None
    max_runs: int = Field(default=0, ge=0)


class ScheduleOut(ORMModel):
    id: str
    name: str
    kind: str
    expression: str
    timezone: str
    directive: str
    enabled: bool
    max_runs: int
    run_count: int
    next_run_at: datetime | None = None
    agent_id: str | None = None


class ScheduleUpdate(BaseModel):
    enabled: bool | None = None
    expression: str | None = Field(default=None, max_length=120)
    timezone: str | None = Field(default=None, max_length=64)


class AutonomyUpdate(BaseModel):
    level: Literal["0", "1", "2", "3"]


class AutonomyOut(BaseModel):
    autonomy_level: str
    emergency_stop_engaged: bool
    level_names: dict[str, str] = Field(
        default_factory=lambda: {"0": "manual", "1": "assisted", "2": "autopilot", "3": "full_auto"}
    )


class PolicyRuleIn(BaseModel):
    """One ordered action-policy rule (SPEC §13.2). First match wins.

    A rule must declare at least one matcher, or set ``match_all`` explicitly.
    """

    decision: Literal["allow", "ask", "deny"]
    match_all: bool = Field(
        default=False,
        description="Match every action. Only valid as an explicit, deliberate catch-all.",
    )
    tool: str | None = Field(default=None, max_length=80)
    path_glob: str | None = Field(default=None, max_length=400)
    host: str | None = Field(default=None, max_length=255)
    command_pattern: str | None = Field(default=None, max_length=400)
    agent_id: str | None = None

    @field_validator("decision")
    @classmethod
    def _known(cls, value: str) -> str:
        return value


class PolicyEvaluateRequest(BaseModel):
    tool: str | None = None
    path: str | None = None
    host: str | None = None
    command: str | None = None
    agent_id: str | None = None


class PolicyEvaluateResult(BaseModel):
    decision: Literal["allow", "ask", "deny"]
    matched_rule: int | None = None
    reason: str
