"""Enumerations shared by models, schemas and services (SPEC §4, §7, §13)."""

from __future__ import annotations

from enum import StrEnum


class OrgRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


ROLE_RANK: dict[OrgRole, int] = {
    OrgRole.VIEWER: 10,
    OrgRole.MEMBER: 20,
    OrgRole.ADMIN: 30,
    OrgRole.OWNER: 40,
}


class RuntimeKind(StrEnum):
    """Values of RuntimeCapabilities.status and connection capabilities (§3.3)."""

    SUPPORTED = "supported"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    NOT_VERIFIED = "not_verified"


class ConnectionKind(StrEnum):
    """All model access goes through one connection interface (SPEC §4.4)."""

    BROWSER_SESSION = "browser_session"
    LOCAL = "local"
    API = "api"
    MCP = "mcp"
    CLI = "cli"
    CUSTOM = "custom"


class ConnectionStatus(StrEnum):
    DISABLED = "disabled"
    ENABLED = "enabled"
    ERROR = "error"


class BrowserSessionState(StrEnum):
    """Bridge/tab state machine (SPEC §6 Phase 1, item 4)."""

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


class AgentPageState(StrEnum):
    """Agent-mode page states reported alongside the bridge state (SPEC §4.4)."""

    READY = "ready"
    GENERATING = "generating"
    IDLE = "idle"
    KEEP_WORKING_VISIBLE = "keep_working_visible"
    TOOL_CALL_LIMIT = "tool_call_limit"
    PR_READY = "pr_ready"
    NEEDS_HUMAN = "needs_human"
    OFFLINE = "offline"


class AgentModeCommand(StrEnum):
    NEW_SESSION = "new_session"
    SUBMIT = "submit"
    KEEP_WORKING = "keep_working"
    STOP = "stop"
    READ_LAST_REPLY = "read_last_reply"
    SELECTOR_TEST = "selector_test"
    SELECT_REPO = "select_repo"
    CREATE_PR = "create_pr"
    CLOSE_FEEDBACK = "close_feedback"


class RunStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_FOR_USER = "waiting_for_user"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RESUME_AVAILABLE = "resume_available"


TERMINAL_RUN_STATUSES: frozenset[RunStatus] = frozenset(
    {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}
)


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ApprovalKind(StrEnum):
    TOOL_CALL = "tool_call"
    PLAN = "plan"
    MERGE = "merge"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class AutonomyLevel(StrEnum):
    """SPEC §13.1. Level 3 (full-auto) is the documented default."""

    MANUAL = "0"
    ASSISTED = "1"
    AUTOPILOT = "2"
    FULL_AUTO = "3"


class PolicyDecision(StrEnum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class AuditOutcome(StrEnum):
    SUCCESS = "success"
    DENIED = "denied"
    ERROR = "error"


class ScheduleKind(StrEnum):
    ONCE = "once"
    INTERVAL = "interval"
    CRON = "cron"


class RunTrigger(StrEnum):
    MANUAL = "manual"
    CHAT = "chat"
    SCHEDULE = "schedule"
    FILE_WATCH = "file_watch"
    GIT_EVENT = "git_event"
