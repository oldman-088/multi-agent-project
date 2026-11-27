"""Authentication, first-run setup and organization membership schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models.enums import OrgRole
from app.schemas.common import ORMModel


class LoginRequest(BaseModel):
    email: EmailStr = Field(examples=["owner@nexus.local"])
    password: str = Field(min_length=8, max_length=200, examples=["correct horse battery staple"])


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=10)


class LogoutRequest(BaseModel):
    refresh_token: str | None = None


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth scheme name, not a secret
    expires_in: int
    user: UserOut


class UserOut(ORMModel):
    id: str
    email: str
    display_name: str
    is_active: bool
    is_superuser: bool
    locale: str
    theme: str
    last_login_at: datetime | None = None
    created_at: datetime


class OrganizationOut(ORMModel):
    id: str
    name: str
    slug: str
    autonomy_level: str
    created_at: datetime


class MembershipOut(ORMModel):
    organization_id: str
    user_id: str
    role: OrgRole


class MeResponse(BaseModel):
    """Who am I, in which organization, with which role and permissions."""

    user: UserOut
    organization: OrganizationOut
    role: OrgRole
    permissions: list[str]


class SetupStatus(BaseModel):
    needs_setup: bool = Field(
        description="True when no user exists yet; the client should show first-run setup."
    )
    user_count: int
    organization_count: int


class SetupRequest(BaseModel):
    """First-run: create the local owner account and its organization.

    NEXUS_ prefix keeps this out of accidental discovery; the endpoint is public
    by design (SPEC §6 Phase 2 item 1) and refuses once a user exists.
    """

    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    display_name: str = Field(min_length=1, max_length=120, examples=["Owner"])
    organization_name: str = Field(min_length=1, max_length=160, examples=["My Studio"])
    organization_slug: str | None = Field(
        default=None, max_length=80, pattern=r"^[a-z0-9][a-z0-9-]*$"
    )
    locale: str = Field(default="ar", pattern="^(ar|en|fa)$")


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=200)


class InviteMemberRequest(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=10, max_length=200)
    role: OrgRole = OrgRole.MEMBER


class MemberOut(BaseModel):
    user: UserOut
    role: OrgRole
    joined_at: datetime


class RoleUpdateRequest(BaseModel):
    role: OrgRole
