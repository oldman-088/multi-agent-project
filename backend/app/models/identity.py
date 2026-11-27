"""Identity: users, organizations, memberships, roles, permissions, API sessions."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, UniqueConstraint, false, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base, PublicIdMixin, TimestampMixin, UTCDateTime
from backend.app.db.types import EnumValue, JSONType
from backend.app.models.enums import OrgRole


class Permission(Base, TimestampMixin):
    """Permission catalogue. Seeded by migration; referenced by role grants."""

    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    category: Mapped[str] = mapped_column(String(32), default="general")


class User(Base, PublicIdMixin, TimestampMixin):
    """A local account. Passwords are argon2id hashes; never plaintext."""

    __tablename__ = "users"
    id_prefix = "usr"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    is_superuser: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    locale: Mapped[str] = mapped_column(String(8), default="ar", nullable=False)
    theme: Mapped[str] = mapped_column(String(16), default="dark", nullable=False)
    failed_login_attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    memberships: Mapped[list[OrganizationMember]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:  # never include the hash in a repr
        return f"<User {self.id} {self.email}>"


class Organization(Base, PublicIdMixin, TimestampMixin):
    """Every tenant-scoped table carries ``organization_id`` (SPEC §6 Phase 2)."""

    __tablename__ = "organizations"
    id_prefix = "org"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)
    # Full-auto (SPEC §13.1) is the documented default autonomy level.
    autonomy_level: Mapped[str] = mapped_column(String(1), default="3", nullable=False)
    settings: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)

    members: Mapped[list[OrganizationMember]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )


class OrganizationMember(Base, TimestampMixin):
    """Membership ties a user to an organization with a role."""

    __tablename__ = "organization_members"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_org_members_org_user"),
        Index("ix_org_members_user", "user_id"),
    )

    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[OrgRole] = mapped_column(
        EnumValue(OrgRole), default=OrgRole.MEMBER, nullable=False
    )

    organization: Mapped[Organization] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships")


class RoleGrant(Base, TimestampMixin):
    """Role → permission mapping, scoped per organization."""

    __tablename__ = "role_grants"
    __table_args__ = (
        UniqueConstraint("organization_id", "role", "permission_code", name="uq_role_grants_spec"),
    )

    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[OrgRole] = mapped_column(EnumValue(OrgRole), primary_key=True)
    permission_code: Mapped[str] = mapped_column(
        String(64), ForeignKey("permissions.code", ondelete="CASCADE"), primary_key=True
    )


class RefreshToken(Base, TimestampMixin):
    """Server-side refresh-token registry so revocation is immediate."""

    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("ix_refresh_tokens_user", "user_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
