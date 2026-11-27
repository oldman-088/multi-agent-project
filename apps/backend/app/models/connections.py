"""Providers, credentials, connections, browser devices/profiles/sessions, adapters.

Covers SPEC §6 Phase 2 item 2. Every table carries ``organization_id`` with an
index because it is tenant-scoped (except the credential cipher itself, which is
scoped through its owning organization row).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, PublicIdMixin, TimestampMixin, UTCDateTime
from app.db.types import EnumValue, JSONType
from app.models.enums import (
    BrowserSessionState,
    ConnectionKind,
    ConnectionStatus,
    RuntimeKind,
)


class Credential(Base, PublicIdMixin, TimestampMixin):
    """An encrypted secret. Plaintext never touches this table (SPEC §3.2)."""

    __tablename__ = "credentials"
    __table_args__ = (Index("ix_credentials_org", "organization_id"),)
    id_prefix = "cred"

    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), default="api_key", nullable=False)
    # Fernet ciphertext produced by SecretBox.encrypt(); never the raw value.
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    # Optional env:VAR_NAME indirection instead of a stored ciphertext.
    credential_ref: Mapped[str | None] = mapped_column(String(160), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    rotated_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    __mapper_args__ = {"eager_defaults": True}


class Provider(Base, PublicIdMixin, TimestampMixin):
    """A provider family, e.g. ``mock``, ``ollama``, ``openai_compatible``."""

    __tablename__ = "providers"
    __table_args__ = (UniqueConstraint("organization_id", "slug", name="uq_providers_org_slug"),)
    id_prefix = "prv"

    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[ConnectionKind] = mapped_column(EnumValue(ConnectionKind), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    base_url: Mapped[str | None] = mapped_column(String(400), nullable=True)
    config: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)


class ProviderConnection(Base, PublicIdMixin, TimestampMixin):
    """A configured connection. Browser connections carry the terms confirmation."""

    __tablename__ = "provider_connections"
    __table_args__ = (
        Index("ix_provider_connections_org", "organization_id"),
        UniqueConstraint("organization_id", "name", name="uq_provider_connections_org_name"),
    )
    id_prefix = "conn"

    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    provider_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("providers.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[ConnectionKind] = mapped_column(EnumValue(ConnectionKind), nullable=False)
    status: Mapped[ConnectionStatus] = mapped_column(
        EnumValue(ConnectionStatus), default=ConnectionStatus.DISABLED, nullable=False
    )
    credential_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("credentials.id", ondelete="SET NULL"), nullable=True
    )
    model: Mapped[str | None] = mapped_column(String(160), nullable=True)
    base_url: Mapped[str | None] = mapped_column(String(400), nullable=True)
    options: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    #: Honest capability declaration (SPEC §4.4). Never inferred.
    capabilities: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)

    # Terms notice for the browser transport (SPEC §3.1): one acknowledgement.
    terms_acknowledged_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    terms_acknowledged_by: Mapped[str | None] = mapped_column(String(64), nullable=True)

    @property
    def terms_acknowledged(self) -> bool:
        return self.terms_acknowledged_at is not None


class Adapter(Base, PublicIdMixin, TimestampMixin):
    """Versioned userscript adapter (declarative YAML) for a provider (SPEC §6 P1)."""

    __tablename__ = "adapters"
    __table_args__ = (
        UniqueConstraint("organization_id", "provider_slug", "version", name="uq_adapters_version"),
        Index("ix_adapters_org", "organization_id"),
    )
    id_prefix = "adp"

    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    provider_slug: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    yaml_body: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    notes: Mapped[str | None] = mapped_column(String(400), nullable=True)


class BrowserDevice(Base, PublicIdMixin, TimestampMixin):
    """A paired browser. The device credential is stored hashed only (SPEC §3.2)."""

    __tablename__ = "browser_devices"
    __table_args__ = (Index("ix_browser_devices_org", "organization_id"),)
    id_prefix = "dev"

    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    credential_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    userscript_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class BrowserProfile(Base, PublicIdMixin, TimestampMixin):
    """A signed-in browser profile that hosts tabs."""

    __tablename__ = "browser_profiles"
    __table_args__ = (Index("ix_browser_profiles_org", "organization_id"),)
    id_prefix = "prf"

    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    device_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("browser_devices.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    provider_slug: Mapped[str | None] = mapped_column(String(80), nullable=True)
    is_signed_in: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class BrowserSession(Base, PublicIdMixin, TimestampMixin):
    """One tab. Concurrency is 1 per tab by construction (SPEC §4.4)."""

    __tablename__ = "browser_sessions"
    __table_args__ = (
        Index("ix_browser_sessions_org", "organization_id"),
        Index("ix_browser_sessions_profile", "profile_id"),
    )
    id_prefix = "bsess"

    organization_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    profile_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("browser_profiles.id", ondelete="CASCADE"), nullable=False
    )
    provider_slug: Mapped[str] = mapped_column(String(80), nullable=False)
    state: Mapped[BrowserSessionState] = mapped_column(
        EnumValue(BrowserSessionState),
        default=BrowserSessionState.DISCONNECTED,
        nullable=False,
    )
    agent_page_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    url: Mapped[str | None] = mapped_column(String(600), nullable=True)
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    #: Depth of the per-tab queue; the tab is busy when this is non-zero.
    queue_depth: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    last_error: Mapped[str | None] = mapped_column(String(400), nullable=True)
    connected_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    #: An agent may only use a session explicitly granted to it (SPEC Phase 2.3).
    granted_agent_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )


class ConnectionCapability(Base, TimestampMixin):
    """Per-connection capability row using the four honest statuses (SPEC §3.3)."""

    __tablename__ = "connection_capabilities"

    connection_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("provider_connections.id", ondelete="CASCADE"), primary_key=True
    )
    capability: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[RuntimeKind] = mapped_column(
        EnumValue(RuntimeKind), default=RuntimeKind.NOT_VERIFIED, nullable=False
    )
    detail: Mapped[str | None] = mapped_column(String(300), nullable=True)
