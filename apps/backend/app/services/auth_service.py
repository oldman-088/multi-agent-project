"""First-run setup, login/logout, token rotation and membership management."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import grants_for_role
from app.core.config import Settings
from app.core.errors import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationFailedError,
)
from app.core.security import (
    create_token,
    decode_token,
    hash_password,
    new_id,
    token_fingerprint,
    verify_password,
)
from app.db.base import utcnow
from app.models.enums import AuditOutcome, OrgRole
from app.models.identity import (
    Organization,
    OrganizationMember,
    Permission,
    RefreshToken,
    RoleGrant,
    User,
)
from app.schemas.auth import SetupRequest
from app.services import audit

_PERMISSION_CATALOG: dict[str, str] = {
    "org:read": "Read organization settings",
    "org:write": "Update organization settings",
    "members:write": "Invite and manage members",
    "agents:read": "List and read agents",
    "agents:write": "Create and edit agents",
    "runs:read": "Read runs and events",
    "runs:write": "Start runs",
    "runs:cancel": "Cancel runs",
    "events:read": "Read the event stream",
    "events:write": "Append events",
    "conversations:read": "Read conversations",
    "conversations:write": "Write messages",
    "connections:read": "Read connections",
    "connections:write": "Manage connections and credentials",
    "missions:read": "Read missions",
    "missions:write": "Create and control missions",
    "approvals:read": "Read approvals",
    "approvals:write": "Decide approvals",
    "audit:read": "Read the audit log",
    "schedules:read": "Read schedules",
    "schedules:write": "Manage schedules",
    "tools:read": "Read the tool registry",
    "tools:invoke": "Invoke tools",
    "tools:write": "Register or edit tools",
    "bridges:write": "Pair and revoke browser devices",
    "tabs:write": "Grant browser tabs to agents",
    "adapters:write": "Manage adapter versions",
    "system:write": "Change system-wide settings and the kill switch",
}


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "org"


async def needs_setup(session: AsyncSession) -> tuple[bool, int, int]:
    users = await session.scalar(select(func.count()).select_from(User))
    orgs = await session.scalar(select(func.count()).select_from(Organization))
    user_count = int(users or 0)
    org_count = int(orgs or 0)
    return user_count == 0, user_count, org_count


async def seed_permissions(session: AsyncSession) -> None:
    """Idempotently seed the permission catalogue and default role grants."""
    existing = set((await session.scalars(select(Permission.code))).all())
    for code, description in _PERMISSION_CATALOG.items():
        if code not in existing:
            session.add(Permission(code=code, description=description, category=code.split(":")[0]))
    await session.flush()


async def seed_role_grants(session: AsyncSession, organization_id: str) -> None:
    from app.auth.rbac import DEFAULT_GRANTS, OWNER_GRANTS

    matrix: dict[OrgRole, set[str]] = {OrgRole.OWNER: OWNER_GRANTS, **DEFAULT_GRANTS}
    existing = set(
        (
            await session.execute(
                select(RoleGrant.role, RoleGrant.permission_code).where(
                    RoleGrant.organization_id == organization_id
                )
            )
        ).all()
    )
    for role, codes in matrix.items():
        for code in codes:
            if (role, code) in existing:
                continue
            if code not in _PERMISSION_CATALOG:
                continue
            session.add(RoleGrant(organization_id=organization_id, role=role, permission_code=code))
    await session.flush()


async def create_first_owner(
    session: AsyncSession, payload: SetupRequest, settings: Settings
) -> tuple[User, Organization]:
    """First-run setup. Refuses once any user exists (no privilege escalation)."""
    setup_needed, _, _ = await needs_setup(session)
    if not setup_needed:
        raise ConflictError("Setup has already been completed", code="already_initialised")

    await seed_permissions(session)

    slug = payload.organization_slug or _slugify(payload.organization_name)
    if await session.scalar(select(Organization).where(Organization.slug == slug)):
        raise ConflictError("Organization slug already exists", code="slug_taken")

    user = User(
        email=payload.email.lower(),
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),
        is_active=True,
        is_superuser=True,
        locale=payload.locale,
        last_login_at=utcnow(),
    )
    organization = Organization(
        name=payload.organization_name, slug=slug, autonomy_level="3", settings={}
    )
    session.add_all([user, organization])
    await session.flush()

    session.add(
        OrganizationMember(organization_id=organization.id, user_id=user.id, role=OrgRole.OWNER)
    )
    await session.flush()
    await seed_role_grants(session, organization.id)
    await audit.record(
        session,
        action="auth.first_run_setup",
        actor_id=user.id,
        organization_id=organization.id,
        target_type="organization",
        target_id=organization.id,
        context={"email": user.email, "org_slug": slug},
    )
    return user, organization


async def authenticate(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    settings: Settings,
    ip: str | None = None,
) -> User:
    """Verify credentials with lockout after repeated failures (no user enumeration)."""
    user = await session.scalar(select(User).where(User.email == email.lower()))
    generic = "Invalid email or password"
    if user is None:
        # Still run a hash to keep timing similar for unknown accounts.
        verify_password(password, "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHQ$" + "0" * 43)
        raise AuthenticationError(generic, code="invalid_credentials")

    now = datetime.now(UTC)
    if user.locked_until and user.locked_until > now:
        raise AuthenticationError(
            "Account temporarily locked after repeated failures",
            code="account_locked",
            details={"locked_until": user.locked_until.isoformat()},
        )

    if not verify_password(password, user.password_hash):
        # Count the failure and, at the limit, lock the account. The counter and
        # the lock are flushed explicitly: this request ends in an error, so the
        # caller's transaction would otherwise be rolled back and the lock lost.
        attempts = int(user.failed_login_attempts or 0) + 1
        user.failed_login_attempts = attempts
        if attempts >= settings.max_failed_logins:
            user.locked_until = now + timedelta(seconds=settings.lockout_seconds)
            user.failed_login_attempts = 0
        await audit.record(
            session,
            action="auth.login_failed",
            actor_id=user.id,
            actor_type="user",
            organization_id=None,
            outcome=AuditOutcome.DENIED,
            context={"email": email, "attempt": attempts},
            ip_address=ip,
        )
        await session.commit()
        raise AuthenticationError(generic, code="invalid_credentials")

    if not user.is_active:
        raise AuthenticationError("Account is disabled", code="inactive_account")

    user.failed_login_attempts = 0
    user.locked_until = None
    user.last_login_at = utcnow()
    return user


async def resolve_primary_organization(session: AsyncSession, user: User) -> Organization:
    row = (
        await session.execute(
            select(Organization)
            .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
            .where(OrganizationMember.user_id == user.id)
            .order_by(OrganizationMember.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None:
        raise PermissionDeniedError("User belongs to no organization", code="no_organization")
    return row


async def role_for(session: AsyncSession, user_id: str, organization_id: str) -> OrgRole:
    member = await session.get(OrganizationMember, (organization_id, user_id))
    if member is None:
        raise PermissionDeniedError("Not a member of this organization")
    return OrgRole(member.role)


async def issue_tokens(
    session: AsyncSession,
    *,
    user: User,
    organization: Organization,
    settings: Settings,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """Mint an access/refresh pair and register the refresh token for revocation."""
    role = await role_for(session, user.id, organization.id)
    # `token_type` is the JWT claim ("access"/"refresh"), not a credential.
    access = create_token(
        subject=user.id,
        token_type="access",  # noqa: S106
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        ttl_seconds=settings.access_token_ttl_seconds,
        extra_claims={"org": organization.id, "role": role.value},
    )
    refresh = create_token(
        subject=user.id,
        token_type="refresh",  # noqa: S106
        secret=settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
        ttl_seconds=settings.refresh_token_ttl_seconds,
        extra_claims={"org": organization.id},
    )
    session.add(
        RefreshToken(
            id=new_id("rtk"),
            user_id=user.id,
            token_hash=token_fingerprint(refresh),
            expires_at=utcnow() + timedelta(seconds=settings.refresh_token_ttl_seconds),
            user_agent=(user_agent or "")[:255] or None,
        )
    )
    await session.flush()
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",  # noqa: S105 - OAuth scheme name, not a secret
        "expires_in": settings.access_token_ttl_seconds,
    }


async def refresh_tokens(
    session: AsyncSession, *, refresh_token: str, settings: Settings, user_agent: str | None = None
) -> dict[str, Any]:
    """Rotate a refresh token. Reusing a revoked token revokes the whole chain."""
    claims = decode_token(
        refresh_token, secret=settings.jwt_secret, algorithm=settings.jwt_algorithm
    )
    if claims.get("type") != "refresh":
        raise AuthenticationError("Not a refresh token", code="wrong_token_type")

    stored = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == token_fingerprint(refresh_token))
    )
    if stored is None:
        raise AuthenticationError("Refresh token is not recognised", code="invalid_token")
    if stored.revoked_at is not None:
        # Replay of a rotated token: revoke every outstanding token for the user.
        for row in (
            await session.scalars(
                select(RefreshToken).where(
                    RefreshToken.user_id == stored.user_id, RefreshToken.revoked_at.is_(None)
                )
            )
        ).all():
            row.revoked_at = utcnow()
        raise AuthenticationError("Refresh token was revoked", code="token_revoked")

    user = await session.get(User, stored.user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("Account is not active", code="inactive_account")

    organization = await resolve_primary_organization(session, user)
    stored.revoked_at = utcnow()
    return await issue_tokens(
        session, user=user, organization=organization, settings=settings, user_agent=user_agent
    )


async def revoke_refresh_token(session: AsyncSession, refresh_token: str | None) -> int:
    """Logout. Returns how many tokens were revoked."""
    if not refresh_token:
        return 0
    stored = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == token_fingerprint(refresh_token))
    )
    if stored is None or stored.revoked_at is not None:
        return 0
    stored.revoked_at = utcnow()
    return 1


async def change_password(
    session: AsyncSession, *, user: User, current_password: str, new_password: str
) -> None:
    if not verify_password(current_password, user.password_hash):
        raise AuthenticationError("Current password is incorrect", code="invalid_credentials")
    if verify_password(new_password, user.password_hash):
        raise ValidationFailedError("New password must differ from the current one")
    user.password_hash = hash_password(new_password)
    for row in (
        await session.scalars(
            select(RefreshToken).where(
                RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None)
            )
        )
    ).all():
        row.revoked_at = utcnow()


async def add_member(
    session: AsyncSession,
    *,
    organization: Organization,
    actor: User,
    email: str,
    display_name: str,
    password: str,
    role: OrgRole,
) -> tuple[User, OrganizationMember]:
    existing = await session.scalar(select(User).where(User.email == email.lower()))
    if existing is not None:
        member = await session.get(OrganizationMember, (organization.id, existing.id))
        if member is not None:
            raise ConflictError("User is already a member", code="already_member")
        raise ConflictError(
            "A user with this email exists; add them to this organization instead",
            code="user_exists",
        )
    user = User(
        email=email.lower(),
        display_name=display_name,
        password_hash=hash_password(password),
        is_active=True,
        locale="ar",
    )
    session.add(user)
    await session.flush()
    member = OrganizationMember(organization_id=organization.id, user_id=user.id, role=role)
    session.add(member)
    await session.flush()
    await audit.record(
        session,
        action="members.add",
        actor_id=actor.id,
        organization_id=organization.id,
        target_type="user",
        target_id=user.id,
        context={"role": role.value},
    )
    return user, member


async def list_members(
    session: AsyncSession, organization_id: str
) -> list[tuple[User, OrganizationMember]]:
    rows = (
        await session.execute(
            select(User, OrganizationMember)
            .join(OrganizationMember, OrganizationMember.user_id == User.id)
            .where(OrganizationMember.organization_id == organization_id)
            .order_by(User.display_name)
        )
    ).all()
    return [(user, member) for user, member in rows]


async def update_member_role(
    session: AsyncSession,
    *,
    organization: Organization,
    actor: User,
    user_id: str,
    role: OrgRole,
) -> OrganizationMember:
    member = await session.get(OrganizationMember, (organization.id, user_id))
    if member is None:
        raise NotFoundError("Member not found")
    if OrgRole(member.role) is OrgRole.OWNER and role is not OrgRole.OWNER:
        owners = await session.scalar(
            select(func.count())
            .select_from(OrganizationMember)
            .where(
                OrganizationMember.organization_id == organization.id,
                OrganizationMember.role == OrgRole.OWNER.value,
            )
        )
        if int(owners or 0) <= 1:
            raise ConflictError("Cannot demote the last owner", code="last_owner")
    member.role = role
    await audit.record(
        session,
        action="members.update_role",
        actor_id=actor.id,
        organization_id=organization.id,
        target_type="user",
        target_id=user_id,
        context={"role": role.value},
    )
    return member


def permissions_for(role: OrgRole) -> list[str]:
    return sorted(grants_for_role(role))
