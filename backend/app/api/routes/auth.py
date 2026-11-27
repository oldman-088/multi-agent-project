"""Authentication, first-run setup and organization membership routes."""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from sqlalchemy import select

from backend.app.auth.dependencies import AppSettings, CurrentAuth, CurrentSession
from backend.app.core.errors import NotFoundError, PermissionDeniedError
from backend.app.core.security import decode_token
from backend.app.models.enums import OrgRole
from backend.app.models.identity import Organization, OrganizationMember, RoleGrant, User
from backend.app.schemas.auth import (
    InviteMemberRequest,
    LoginRequest,
    LogoutRequest,
    MemberOut,
    MeResponse,
    OrganizationOut,
    PasswordChangeRequest,
    RefreshRequest,
    RoleUpdateRequest,
    SetupRequest,
    SetupStatus,
    TokenPair,
    UserOut,
)
from backend.app.schemas.common import OkResponse
from backend.app.services import audit, auth_service, system_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get(
    "/setup-status",
    response_model=SetupStatus,
    summary="Whether first-run setup is still required (public)",
)
async def setup_status(session: CurrentSession) -> SetupStatus:
    needed, users, orgs = await auth_service.needs_setup(session)
    return SetupStatus(needs_setup=needed, user_count=users, organization_count=orgs)


@router.post(
    "/setup",
    response_model=TokenPair,
    status_code=status.HTTP_201_CREATED,
    summary="First-run: create the owner account and organization (public, once)",
)
async def setup(
    payload: SetupRequest,
    session: CurrentSession,
    settings: AppSettings,
    request: Request,
) -> TokenPair:
    user, organization = await auth_service.create_first_owner(session, payload, settings)
    tokens = await auth_service.issue_tokens(
        session,
        user=user,
        organization=organization,
        settings=settings,
        user_agent=request.headers.get("user-agent"),
    )
    await session.commit()
    return TokenPair(**tokens, user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenPair, summary="Log in with email and password (public)")
async def login(
    payload: LoginRequest, session: CurrentSession, settings: AppSettings, request: Request
) -> TokenPair:
    user = await auth_service.authenticate(
        session,
        email=payload.email,
        password=payload.password,
        settings=settings,
        ip=request.client.host if request.client else None,
    )
    organization = await auth_service.resolve_primary_organization(session, user)
    tokens = await auth_service.issue_tokens(
        session,
        user=user,
        organization=organization,
        settings=settings,
        user_agent=request.headers.get("user-agent"),
    )
    await audit.record(
        session,
        action="auth.login",
        actor_id=user.id,
        organization_id=organization.id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    await session.commit()
    return TokenPair(**tokens, user=UserOut.model_validate(user))


@router.post("/refresh", response_model=TokenPair, summary="Rotate the refresh token (public)")
async def refresh(
    payload: RefreshRequest, session: CurrentSession, settings: AppSettings, request: Request
) -> TokenPair:
    tokens = await auth_service.refresh_tokens(
        session,
        refresh_token=payload.refresh_token,
        settings=settings,
        user_agent=request.headers.get("user-agent"),
    )
    await session.commit()
    user_id = str(
        decode_token(
            tokens["access_token"], secret=settings.jwt_secret, algorithm=settings.jwt_algorithm
        )["sub"]
    )
    user = await session.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found")
    return TokenPair(**tokens, user=UserOut.model_validate(user))


@router.post("/logout", response_model=OkResponse, summary="Revoke a refresh token")
async def logout(payload: LogoutRequest, session: CurrentSession, auth: CurrentAuth) -> OkResponse:
    revoked = await auth_service.revoke_refresh_token(session, payload.refresh_token)
    await audit.record(
        session,
        action="auth.logout",
        actor_id=auth.user.id,
        organization_id=auth.organization_id,
        context={"revoked": revoked},
    )
    await session.commit()
    return OkResponse(message=f"{revoked} token(s) revoked")


@router.get("/me", response_model=MeResponse, summary="Current user, organization and permissions")
async def me(auth: CurrentAuth, session: CurrentSession) -> MeResponse:
    return MeResponse(
        user=UserOut.model_validate(auth.user),
        organization=OrganizationOut.model_validate(auth.organization),
        role=auth.role,
        permissions=auth.permissions,
    )


@router.post("/password", response_model=OkResponse, summary="Change your own password")
async def change_password(
    payload: PasswordChangeRequest, auth: CurrentAuth, session: CurrentSession
) -> OkResponse:
    await auth_service.change_password(
        session,
        user=auth.user,
        current_password=payload.current_password,
        new_password=payload.new_password,
    )
    await audit.record(
        session,
        action="auth.change_password",
        actor_id=auth.user.id,
        organization_id=auth.organization_id,
    )
    await session.commit()
    return OkResponse(message="Password changed; all refresh tokens were revoked")


@router.get(
    "/organizations", response_model=list[OrganizationOut], summary="Organizations you belong to"
)
async def my_organizations(auth: CurrentAuth, session: CurrentSession) -> list[OrganizationOut]:
    rows = await system_service.list_organizations_for_user(session, auth.user.id)
    return [OrganizationOut.model_validate(row) for row in rows]


@router.post(
    "/organizations/{organization_id}/switch",
    response_model=TokenPair,
    summary="Switch the active organization (re-issues tokens)",
)
async def switch_organization(
    organization_id: str,
    auth: CurrentAuth,
    session: CurrentSession,
    settings: AppSettings,
    request: Request,
) -> TokenPair:
    member = await session.get(OrganizationMember, (organization_id, auth.user.id))
    if member is None:
        raise PermissionDeniedError("Not a member of this organization")
    organization = await session.get(Organization, organization_id)
    if organization is None:
        raise NotFoundError("Organization not found")
    tokens = await auth_service.issue_tokens(
        session,
        user=auth.user,
        organization=organization,
        settings=settings,
        user_agent=request.headers.get("user-agent"),
    )
    await session.commit()
    return TokenPair(**tokens, user=UserOut.model_validate(auth.user))


members_router = APIRouter(prefix="/members", tags=["members"])


@members_router.get("", response_model=list[MemberOut], summary="List organization members")
async def list_members(auth: CurrentAuth, session: CurrentSession) -> list[MemberOut]:
    rows = await auth_service.list_members(session, auth.organization_id)
    return [
        MemberOut(
            user=UserOut.model_validate(user),
            role=OrgRole(member.role),
            joined_at=member.created_at,
        )
        for user, member in rows
    ]


@members_router.post(
    "",
    response_model=MemberOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a member to the organization",
)
async def add_member(
    payload: InviteMemberRequest, auth: CurrentAuth, session: CurrentSession
) -> MemberOut:
    auth.require("members:write")
    user, member = await auth_service.add_member(
        session,
        organization=auth.organization,
        actor=auth.user,
        email=payload.email,
        display_name=payload.display_name,
        password=payload.password,
        role=payload.role,
    )
    await session.commit()
    return MemberOut(
        user=UserOut.model_validate(user), role=OrgRole(member.role), joined_at=member.created_at
    )


@members_router.patch("/{user_id}", response_model=MemberOut, summary="Change a member's role")
async def update_member_role(
    user_id: str, payload: RoleUpdateRequest, auth: CurrentAuth, session: CurrentSession
) -> MemberOut:
    auth.require("members:write")
    member = await auth_service.update_member_role(
        session,
        organization=auth.organization,
        actor=auth.user,
        user_id=user_id,
        role=payload.role,
    )
    user = await session.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found")
    await session.commit()
    return MemberOut(
        user=UserOut.model_validate(user), role=OrgRole(member.role), joined_at=member.created_at
    )


@members_router.get(
    "/roles/grants",
    response_model=dict[str, list[str]],
    summary="Role to permission matrix for this organization",
)
async def role_grants(auth: CurrentAuth, session: CurrentSession) -> dict[str, list[str]]:
    """Effective permissions per role, read from ``role_grants`` rows."""
    rows = (
        await session.scalars(
            select(RoleGrant).where(RoleGrant.organization_id == auth.organization_id)
        )
    ).all()
    matrix: dict[str, set[str]] = {role.value: set() for role in OrgRole}
    for row in rows:
        matrix.setdefault(OrgRole(row.role).value, set()).add(row.permission_code)
    return {role: sorted(codes) for role, codes in matrix.items()}
