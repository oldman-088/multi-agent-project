"""Kill switch, autonomy level and action policy persistence (SPEC §13).

The kill switch is stored in the database (not memory) so it survives a restart
and cannot be cleared by restarting a worker. It can never be disabled by a
level, and it always audits.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ValidationFailedError
from app.models.enums import AutonomyLevel
from app.models.identity import Organization
from app.schemas.connections import PolicyRuleIn
from app.services import audit, event_service
from app.services import policy as policy_service

EMERGENCY_STOP_KEY = "emergency_stop"
POLICY_KEY = "action_policy"


def _settings(organization: Organization) -> dict[str, Any]:
    return dict(organization.settings or {})


async def get_autonomy(session: AsyncSession, organization: Organization) -> dict[str, Any]:
    settings = _settings(organization)
    stop = settings.get(EMERGENCY_STOP_KEY) or {}
    return {
        "autonomy_level": organization.autonomy_level,
        "emergency_stop_engaged": bool(stop.get("engaged")),
    }


async def set_autonomy(
    session: AsyncSession, *, organization: Organization, actor_id: str, level: AutonomyLevel
) -> dict[str, Any]:
    previous = organization.autonomy_level
    organization.autonomy_level = level.value
    await audit.record(
        session,
        action="system.set_autonomy",
        actor_id=actor_id,
        organization_id=organization.id,
        target_type="organization",
        target_id=organization.id,
        context={"from": previous, "to": level.value},
    )
    return await get_autonomy(session, organization)


async def set_emergency_stop(
    session: AsyncSession,
    *,
    organization: Organization,
    actor_id: str,
    engage: bool,
    reason: str = "",
) -> dict[str, Any]:
    """Engage or clear the global kill switch. Always audited and evented."""
    settings = _settings(organization)
    current = bool((settings.get(EMERGENCY_STOP_KEY) or {}).get("engaged"))
    if current == engage:
        raise ConflictError(
            f"Emergency stop is already {'engaged' if engage else 'cleared'}",
            code="emergency_stop_unchanged",
        )
    from app.db.base import utcnow

    settings[EMERGENCY_STOP_KEY] = {
        "engaged": engage,
        "reason": reason[:400],
        "actor_id": actor_id,
        "at": utcnow().isoformat(),
    }
    organization.settings = settings
    await event_service.append_event(
        session,
        organization_id=organization.id,
        event_type="emergency_stop.engaged" if engage else "emergency_stop.cleared",
        payload={"actor_id": actor_id, "reason": reason[:400]},
    )
    await audit.record(
        session,
        action="system.emergency_stop",
        actor_id=actor_id,
        organization_id=organization.id,
        target_type="organization",
        target_id=organization.id,
        context={"engage": engage, "reason": reason[:400]},
    )
    return {"engaged": engage, "reason": reason[:400]}


async def emergency_stop_state(session: AsyncSession, organization: Organization) -> dict[str, Any]:
    stop = _settings(organization).get(EMERGENCY_STOP_KEY) or {}
    return {"engaged": bool(stop.get("engaged")), "reason": stop.get("reason")}


async def ensure_not_stopped(organization: Organization) -> None:
    """Raise when the kill switch is engaged so mutating routes refuse politely."""
    from app.core.errors import EmergencyStopError

    stop = _settings(organization).get(EMERGENCY_STOP_KEY) or {}
    if stop.get("engaged"):
        raise EmergencyStopError(
            "The emergency stop is engaged; clear it before starting new work",
            details={"reason": stop.get("reason", "")},
        )


async def get_policy(
    session: AsyncSession, organization: Organization, level: AutonomyLevel | None = None
) -> list[dict[str, Any]]:
    """Return the stored rules for a level, or the built-in default for that level."""
    effective = level or AutonomyLevel(organization.autonomy_level)
    stored = (_settings(organization).get(POLICY_KEY) or {}).get(effective.value)
    if stored:
        return list(stored)
    return policy_service.default_policy(effective)


async def set_policy(
    session: AsyncSession,
    *,
    organization: Organization,
    actor_id: str,
    rules: list[PolicyRuleIn],
    level: AutonomyLevel | None = None,
) -> list[dict[str, Any]]:
    """Replace the rules for a level. Custom rules are validated and versioned by audit."""
    effective = level or AutonomyLevel(organization.autonomy_level)
    normalised = policy_service.validate_rules(rules)
    settings = _settings(organization)
    stored = dict(settings.get(POLICY_KEY) or {})
    stored[effective.value] = normalised
    settings[POLICY_KEY] = stored
    organization.settings = settings
    await audit.record(
        session,
        action="system.set_action_policy",
        actor_id=actor_id,
        organization_id=organization.id,
        target_type="organization",
        target_id=organization.id,
        context={"level": effective.value, "rule_count": len(normalised)},
    )
    return normalised


async def list_organizations_for_user(session: AsyncSession, user_id: str) -> list[Organization]:
    from app.models.identity import OrganizationMember

    return list(
        (
            await session.scalars(
                select(Organization)
                .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
                .where(OrganizationMember.user_id == user_id)
                .order_by(Organization.created_at)
            )
        ).all()
    )


def require_strong_confirmation(phrase: str, expected: str = "I UNDERSTAND") -> None:
    """Emptying the ask list or enabling host execution needs a typed phrase."""
    if phrase.strip() != expected:
        raise ValidationFailedError(
            "Confirmation phrase does not match",
            code="confirmation_required",
            details={"expected_phrase": expected},
        )
