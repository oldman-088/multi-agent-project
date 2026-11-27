"""Request-scoped auth: current user, current organization and RBAC enforcement.

Every route in this application depends on ``require_auth`` unless it is listed
as public (health, setup status/creation, login, refresh). Missing or invalid
credentials always yield 401; an authenticated user lacking a role yields 403.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import grants_for_role, require_permission
from app.core.config import Settings, get_settings
from app.core.errors import AuthenticationError, PermissionDeniedError
from app.core.security import decode_token
from app.db.session import get_session
from app.models.enums import OrgRole
from app.models.identity import Organization, OrganizationMember, User


@dataclass(frozen=True)
class AuthContext:
    """Everything a route needs to authorize and to attribute an action."""

    user: User
    organization: Organization
    role: OrgRole
    request_id: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None

    @property
    def organization_id(self) -> str:
        return self.organization.id

    @property
    def permissions(self) -> list[str]:
        return sorted(grants_for_role(self.role))

    def require(self, permission: str) -> None:
        require_permission(self.role, permission)


def _bearer_token(request: Request, authorization: str | None) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    # Test/CLI convenience: the same token can arrive as a cookie.
    cookie = request.cookies.get("nexus_access_token")
    if cookie:
        return cookie
    raise AuthenticationError(
        "Missing bearer credentials", details={"header": "Authorization: Bearer <token>"}
    )


async def require_auth(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    authorization: Annotated[str | None, Header()] = None,
    x_organization_id: Annotated[str | None, Header()] = None,
) -> AuthContext:
    """Resolve the caller, their organization and their role. Raises 401/403."""
    token = _bearer_token(request, authorization)
    claims = decode_token(token, secret=settings.jwt_secret, algorithm=settings.jwt_algorithm)
    if claims.get("type") != "access":
        raise AuthenticationError("A refresh token cannot authenticate", code="wrong_token_type")

    user_id = str(claims.get("sub", ""))
    if not user_id:
        raise AuthenticationError("Token has no subject", code="invalid_token")

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("Account is not active", code="inactive_account")

    # Organization selection: explicit header, else the token claim, else default.
    org_id = x_organization_id or claims.get("org")
    rows = (
        await session.execute(
            select(OrganizationMember, Organization)
            .join(Organization, Organization.id == OrganizationMember.organization_id)
            .where(OrganizationMember.user_id == user.id)
            .order_by(OrganizationMember.created_at)
        )
    ).all()
    if not rows:
        raise PermissionDeniedError("User belongs to no organization", code="no_organization")

    selected = None
    for member, organization in rows:
        if org_id and organization.id == org_id:
            selected = (member, organization)
            break
    if selected is None:
        if org_id:
            # Explicitly requested an organization the user is not a member of.
            raise PermissionDeniedError("Not a member of the requested organization")
        selected = rows[0]

    member, organization = selected
    return AuthContext(
        user=user,
        organization=organization,
        role=OrgRole(member.role),
        request_id=request.headers.get("x-request-id"),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


CurrentAuth = Annotated[AuthContext, Depends(require_auth)]
CurrentSession = Annotated[AsyncSession, Depends(get_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def require(permission: str) -> Callable[[AuthContext], Coroutine[Any, Any, AuthContext]]:
    """Route dependency factory: ``dependencies=[Depends(require("agents:write"))]``."""

    async def _dependency(auth: CurrentAuth) -> AuthContext:
        auth.require(permission)
        return auth

    return _dependency
