"""Audit trail writing. Every mutating action and every policy decision lands here."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger, redact
from app.core.security import new_id
from app.db.base import utcnow
from app.models.enums import AuditOutcome
from app.models.runs import AuditLog

logger = get_logger(__name__)


async def record(
    session: AsyncSession,
    *,
    action: str,
    actor_id: str | None = None,
    actor_type: str = "user",
    organization_id: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    outcome: AuditOutcome = AuditOutcome.SUCCESS,
    context: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> AuditLog:
    """Append one audit row. The caller's transaction commits it (outbox pattern).

    ``context`` is secret-redacted before it is stored, so a caller cannot leak a
    credential into the audit log by accident.
    """
    entry = AuditLog(
        id=new_id("aud"),
        action=action,
        actor_id=actor_id,
        actor_type=actor_type,
        organization_id=organization_id,
        target_type=target_type,
        target_id=target_id,
        outcome=outcome,
        context=redact(context or {}),
        ip_address=ip_address,
        user_agent=(user_agent or "")[:255] or None,
        request_id=request_id,
        created_at=utcnow(),
        updated_at=utcnow(),
    )
    session.add(entry)
    logger.info(
        "audit",
        extra={
            "extra_fields": {
                "action": action,
                "actor_id": actor_id,
                "target": f"{target_type}:{target_id}" if target_type else None,
                "outcome": str(outcome),
            }
        },
    )
    return entry
