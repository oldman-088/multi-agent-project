"""Role-based access control in the service layer (SPEC §6 Phase 2 item 1).

Roles are ``owner | admin | member | viewer``. Permission codes are strings such
as ``agents:write``. A role's grants are resolved from ``role_grants`` with a
built-in default matrix so a fresh database is usable and the matrix is testable.
"""

from __future__ import annotations

from backend.app.core.errors import PermissionDeniedError
from backend.app.models.enums import ROLE_RANK, OrgRole

#: Default grants per role. ``*`` is a wildcard action on a resource.
DEFAULT_GRANTS: dict[OrgRole, set[str]] = {
    OrgRole.VIEWER: {
        "org:read",
        "agents:read",
        "runs:read",
        "events:read",
        "conversations:read",
        "connections:read",
        "missions:read",
        "approvals:read",
        "audit:read",
        "schedules:read",
        "tools:read",
    },
    OrgRole.MEMBER: {
        "org:read",
        "agents:read",
        "runs:read",
        "runs:write",
        "events:read",
        "conversations:read",
        "conversations:write",
        "connections:read",
        "missions:read",
        "missions:write",
        "approvals:read",
        "approvals:write",
        "audit:read",
        "schedules:read",
        "schedules:write",
        "tools:read",
        "tools:invoke",
    },
    OrgRole.ADMIN: {
        "org:read",
        "org:write",
        "agents:read",
        "agents:write",
        "runs:read",
        "runs:write",
        "runs:cancel",
        "events:read",
        "events:write",
        "conversations:read",
        "conversations:write",
        "connections:read",
        "connections:write",
        "missions:read",
        "missions:write",
        "approvals:read",
        "approvals:write",
        "audit:read",
        "schedules:read",
        "schedules:write",
        "tools:read",
        "tools:invoke",
        "tools:write",
        "bridges:write",
        "tabs:write",
        "adapters:write",
    },
}

#: The owner implicitly holds every permission; this is the explicit list used
#: for the ``GET /auth/me`` payload so the UI can render available actions.
OWNER_GRANTS: set[str] = {
    "org:read",
    "org:write",
    "members:write",
    "agents:read",
    "agents:write",
    "runs:read",
    "runs:write",
    "runs:cancel",
    "events:read",
    "events:write",
    "conversations:read",
    "conversations:write",
    "connections:read",
    "connections:write",
    "missions:read",
    "missions:write",
    "approvals:read",
    "approvals:write",
    "audit:read",
    "schedules:read",
    "schedules:write",
    "tools:read",
    "tools:invoke",
    "tools:write",
    "bridges:write",
    "tabs:write",
    "adapters:write",
    "system:write",
}


def grants_for_role(role: OrgRole) -> set[str]:
    if role is OrgRole.OWNER:
        return set(OWNER_GRANTS)
    return set(DEFAULT_GRANTS.get(role, set()))


def has_permission(role: OrgRole, permission: str) -> bool:
    grants = grants_for_role(role)
    if permission in grants:
        return True
    resource, _, action = permission.partition(":")
    return f"{resource}:*" in grants or "*" in grants


def require_permission(role: OrgRole, permission: str) -> None:
    if not has_permission(role, permission):
        raise PermissionDeniedError(
            f"Role '{role.value}' lacks permission '{permission}'",
            details={"required_permission": permission, "role": role.value},
        )


def at_least(role: OrgRole, minimum: OrgRole) -> bool:
    return ROLE_RANK[role] >= ROLE_RANK[minimum]
