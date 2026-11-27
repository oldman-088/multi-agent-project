"""Providers, credentials, connections, terms acknowledgement, devices and tabs.

Security properties enforced here:
- a credential value is encrypted before it is stored and is never returned;
- a raw secret may only be persisted through ``SecretBox`` or an ``env:`` ref;
- terms are acknowledged once per browser connection (SPEC §3.1);
- revoking a device is immediate (``revoked_at``) and its credential hash removed.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError
from app.core.security import (
    SecretBox,
    validate_credential_ref,
)
from app.db.base import utcnow
from app.models.connections import (
    Adapter,
    BrowserDevice,
    BrowserProfile,
    BrowserSession,
    Credential,
    Provider,
    ProviderConnection,
)
from app.models.enums import (
    BrowserSessionState,
    ConnectionKind,
    ConnectionStatus,
    RuntimeKind,
)
from app.schemas.connections import CapabilityFlags, ConnectionCreate, ConnectionUpdate
from app.services import audit

TERMS_NOTICE = (
    "Browser Session connections drive your own signed-in provider tabs through their "
    "visible UI. Automation must comply with each provider's terms; NEXUS never solves "
    "CAPTCHAs, never reads cookies or credentials, and never calls private endpoints. "
    "Acknowledging this notice is recorded once per connection."
)

#: Honest starting capabilities per connection kind (SPEC §4.4, §3.3).
DEFAULT_CAPABILITIES: dict[ConnectionKind, dict[str, Any]] = {
    ConnectionKind.BROWSER_SESSION: CapabilityFlags(
        streaming=RuntimeKind.SUPPORTED,
        native_tool_calling=RuntimeKind.UNSUPPORTED,
        structured_output=RuntimeKind.PARTIAL,
        multimodal_input=RuntimeKind.PARTIAL,
        usage_reporting=RuntimeKind.UNSUPPORTED,
        agent_mode=RuntimeKind.SUPPORTED,
        max_concurrency=1,
        max_prompt_characters=120_000,
    ).model_dump(),
    ConnectionKind.LOCAL: CapabilityFlags(
        streaming=RuntimeKind.NOT_VERIFIED,
        native_tool_calling=RuntimeKind.NOT_VERIFIED,
        structured_output=RuntimeKind.NOT_VERIFIED,
        multimodal_input=RuntimeKind.NOT_VERIFIED,
        usage_reporting=RuntimeKind.NOT_VERIFIED,
        agent_mode=RuntimeKind.UNSUPPORTED,
        max_concurrency=4,
    ).model_dump(),
    ConnectionKind.API: CapabilityFlags(
        streaming=RuntimeKind.NOT_VERIFIED,
        native_tool_calling=RuntimeKind.NOT_VERIFIED,
        structured_output=RuntimeKind.NOT_VERIFIED,
        multimodal_input=RuntimeKind.NOT_VERIFIED,
        usage_reporting=RuntimeKind.NOT_VERIFIED,
        agent_mode=RuntimeKind.UNSUPPORTED,
        max_concurrency=4,
    ).model_dump(),
}


def _hash_credential(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


async def ensure_default_providers(
    session: AsyncSession, organization_id: str, settings: Settings
) -> list[Provider]:
    """Seed provider rows. API access stays disabled unless explicitly enabled."""
    existing = set(
        (
            await session.scalars(
                select(Provider.slug).where(Provider.organization_id == organization_id)
            )
        ).all()
    )
    defaults = [
        ("mock", "Mock provider", ConnectionKind.BROWSER_SESSION, True, None),
        ("generic", "Generic browser provider", ConnectionKind.BROWSER_SESSION, True, None),
        ("ollama", "Ollama (local)", ConnectionKind.LOCAL, True, settings.ollama_base_url),
        (
            "openai_compatible",
            "OpenAI-compatible API",
            ConnectionKind.API,
            settings.openai_enabled,
            settings.openai_base_url,
        ),
    ]
    created: list[Provider] = []
    for slug, name, kind, enabled, base_url in defaults:
        if slug in existing:
            continue
        provider = Provider(
            organization_id=organization_id,
            slug=slug,
            display_name=name,
            kind=kind,
            enabled=enabled,
            base_url=base_url,
            config={},
        )
        session.add(provider)
        created.append(provider)
    await session.flush()
    return created


async def list_providers(session: AsyncSession, organization_id: str) -> list[Provider]:
    return list(
        (
            await session.scalars(
                select(Provider)
                .where(Provider.organization_id == organization_id)
                .order_by(Provider.slug)
            )
        ).all()
    )


async def create_credential(
    session: AsyncSession,
    *,
    organization_id: str,
    actor_id: str,
    settings: Settings,
    name: str,
    kind: str,
    value: str,
) -> Credential:
    """Store a secret. ``env:VAR_NAME`` is kept as a reference; anything else is encrypted."""
    box = SecretBox(settings)
    if value.startswith("env:"):
        credential_ref = validate_credential_ref(value)
        ciphertext = box.encrypt("")  # placeholder keeps the column non-null
    else:
        credential_ref = None
        ciphertext = "fernet:" + box.encrypt(value)

    credential = Credential(
        organization_id=organization_id,
        name=name,
        kind=kind,
        ciphertext=ciphertext,
        credential_ref=credential_ref,
    )
    session.add(credential)
    await session.flush()
    await audit.record(
        session,
        action="credentials.create",
        actor_id=actor_id,
        organization_id=organization_id,
        target_type="credential",
        target_id=credential.id,
        context={"name": name, "kind": kind, "indirection": credential_ref is not None},
    )
    return credential


async def list_credentials(session: AsyncSession, organization_id: str) -> list[Credential]:
    return list(
        (
            await session.scalars(
                select(Credential)
                .where(Credential.organization_id == organization_id)
                .order_by(Credential.created_at.desc())
            )
        ).all()
    )


async def delete_credential(
    session: AsyncSession, *, organization_id: str, actor_id: str, credential_id: str
) -> None:
    row = await session.get(Credential, credential_id)
    if row is None or row.organization_id != organization_id:
        raise NotFoundError("Credential not found")
    await session.delete(row)
    await audit.record(
        session,
        action="credentials.delete",
        actor_id=actor_id,
        organization_id=organization_id,
        target_type="credential",
        target_id=credential_id,
    )


async def create_connection(
    session: AsyncSession,
    *,
    organization_id: str,
    actor_id: str,
    payload: ConnectionCreate,
) -> ProviderConnection:
    provider = await session.scalar(
        select(Provider).where(
            Provider.organization_id == organization_id, Provider.slug == payload.provider_slug
        )
    )
    if provider is None:
        raise NotFoundError("Provider not found", details={"slug": payload.provider_slug})
    if provider.kind is ConnectionKind.API and not provider.enabled:
        raise ConflictError(
            "API access is disabled by default; enable it in Settings first",
            code="provider_disabled",
        )
    if payload.credential_id:
        credential = await session.get(Credential, payload.credential_id)
        if credential is None or credential.organization_id != organization_id:
            raise NotFoundError("Credential not found")

    connection = ProviderConnection(
        organization_id=organization_id,
        provider_id=provider.id,
        name=payload.name,
        kind=payload.kind,
        status=ConnectionStatus.DISABLED,
        credential_id=payload.credential_id,
        model=payload.model,
        base_url=payload.base_url or provider.base_url,
        options=payload.options,
        capabilities=DEFAULT_CAPABILITIES.get(payload.kind, {}),
    )
    session.add(connection)
    await session.flush()
    await audit.record(
        session,
        action="connections.create",
        actor_id=actor_id,
        organization_id=organization_id,
        target_type="connection",
        target_id=connection.id,
        context={"kind": payload.kind.value, "provider": payload.provider_slug},
    )
    return connection


async def list_connections(session: AsyncSession, organization_id: str) -> list[ProviderConnection]:
    return list(
        (
            await session.scalars(
                select(ProviderConnection)
                .where(ProviderConnection.organization_id == organization_id)
                .order_by(ProviderConnection.created_at.desc())
            )
        ).all()
    )


async def get_connection(
    session: AsyncSession, organization_id: str, connection_id: str
) -> ProviderConnection:
    row = await session.get(ProviderConnection, connection_id)
    if row is None or row.organization_id != organization_id:
        raise NotFoundError("Connection not found")
    return row


async def provider_slug_for(session: AsyncSession, connection: ProviderConnection) -> str:
    provider = await session.get(Provider, connection.provider_id)
    return provider.slug if provider else ""


async def update_connection(
    session: AsyncSession,
    *,
    organization_id: str,
    actor_id: str,
    connection_id: str,
    payload: ConnectionUpdate,
) -> ProviderConnection:
    connection = await get_connection(session, organization_id, connection_id)
    data = payload.model_dump(exclude_unset=True)
    if "status" in data and data["status"] is not None:
        new_status = ConnectionStatus(data["status"])
        if (
            new_status is ConnectionStatus.ENABLED
            and connection.kind is ConnectionKind.BROWSER_SESSION
            and connection.terms_acknowledged_at is None
        ):
            raise ConflictError(
                "The browser transport needs its terms notice acknowledged first",
                code="terms_not_acknowledged",
            )
        connection.status = new_status
    for field in ("name", "model", "base_url", "options"):
        if field in data and data[field] is not None:
            setattr(connection, field, data[field])
    await audit.record(
        session,
        action="connections.update",
        actor_id=actor_id,
        organization_id=organization_id,
        target_type="connection",
        target_id=connection.id,
        context={"fields": sorted(data)},
    )
    return connection


async def acknowledge_terms(
    session: AsyncSession, *, organization_id: str, actor_id: str, connection_id: str
) -> ProviderConnection:
    """Record the single terms acknowledgement for the browser transport."""
    connection = await get_connection(session, organization_id, connection_id)
    if connection.terms_acknowledged_at is None:
        connection.terms_acknowledged_at = utcnow()
        connection.terms_acknowledged_by = actor_id
        await audit.record(
            session,
            action="connections.terms_acknowledged",
            actor_id=actor_id,
            organization_id=organization_id,
            target_type="connection",
            target_id=connection.id,
        )
    return connection


async def pair_device(
    session: AsyncSession,
    *,
    organization_id: str,
    actor_id: str,
    label: str,
    userscript_version: str,
) -> tuple[BrowserDevice, str]:
    """Pair a browser. The raw credential is returned once and never stored."""
    credential = secrets.token_urlsafe(32)
    device = BrowserDevice(
        organization_id=organization_id,
        label=label,
        credential_hash=_hash_credential(credential),
        userscript_version=userscript_version,
        last_seen_at=utcnow(),
    )
    session.add(device)
    await session.flush()
    await audit.record(
        session,
        action="devices.pair",
        actor_id=actor_id,
        organization_id=organization_id,
        target_type="browser_device",
        target_id=device.id,
        context={"label": label, "userscript_version": userscript_version},
    )
    return device, credential


async def revoke_device(
    session: AsyncSession, *, organization_id: str, actor_id: str, device_id: str
) -> BrowserDevice:
    device = await session.get(BrowserDevice, device_id)
    if device is None or device.organization_id != organization_id:
        raise NotFoundError("Device not found")
    device.revoked_at = utcnow()
    # Rotate the stored hash so the old credential can never match again.
    device.credential_hash = _hash_credential(secrets.token_urlsafe(32))
    for tab in (
        await session.scalars(
            select(BrowserSession)
            .join(BrowserProfile, BrowserProfile.id == BrowserSession.profile_id)
            .where(BrowserProfile.device_id == device.id)
        )
    ).all():
        tab.state = BrowserSessionState.DISCONNECTED
        tab.connected_at = None
    await audit.record(
        session,
        action="devices.revoke",
        actor_id=actor_id,
        organization_id=organization_id,
        target_type="browser_device",
        target_id=device.id,
    )
    return device


async def list_devices(session: AsyncSession, organization_id: str) -> list[BrowserDevice]:
    return list(
        (
            await session.scalars(
                select(BrowserDevice)
                .where(BrowserDevice.organization_id == organization_id)
                .order_by(BrowserDevice.created_at.desc())
            )
        ).all()
    )


async def register_tab(
    session: AsyncSession,
    *,
    organization_id: str,
    actor_id: str,
    device_id: str,
    provider_slug: str,
    url: str | None = None,
    title: str | None = None,
) -> BrowserSession:
    """Register a tab under a paired device; creates the profile on demand."""
    device = await session.get(BrowserDevice, device_id)
    if device is None or device.organization_id != organization_id:
        raise NotFoundError("Device not found")
    if device.revoked_at is not None:
        raise ConflictError("Device has been revoked", code="device_revoked")

    profile = await session.scalar(
        select(BrowserProfile).where(
            BrowserProfile.device_id == device.id, BrowserProfile.provider_slug == provider_slug
        )
    )
    if profile is None:
        profile = BrowserProfile(
            organization_id=organization_id,
            device_id=device.id,
            label=f"{device.label} · {provider_slug}",
            provider_slug=provider_slug,
            is_signed_in=True,
        )
        session.add(profile)
        await session.flush()

    tab = BrowserSession(
        organization_id=organization_id,
        profile_id=profile.id,
        provider_slug=provider_slug,
        state=BrowserSessionState.CONNECTED,
        url=url,
        title=title,
        connected_at=utcnow(),
    )
    session.add(tab)
    await session.flush()
    await audit.record(
        session,
        action="tabs.register",
        actor_id=actor_id,
        organization_id=organization_id,
        target_type="browser_session",
        target_id=tab.id,
        context={"provider": provider_slug},
    )
    return tab


async def list_tabs(session: AsyncSession, organization_id: str) -> list[BrowserSession]:
    return list(
        (
            await session.scalars(
                select(BrowserSession)
                .where(BrowserSession.organization_id == organization_id)
                .order_by(BrowserSession.created_at.desc())
            )
        ).all()
    )


async def get_tab(session: AsyncSession, organization_id: str, tab_id: str) -> BrowserSession:
    row = await session.get(BrowserSession, tab_id)
    if row is None or row.organization_id != organization_id:
        raise NotFoundError("Browser session not found")
    return row


async def update_tab(
    session: AsyncSession,
    *,
    organization_id: str,
    actor_id: str,
    tab_id: str,
    payload: dict[str, Any],
) -> BrowserSession:
    tab = await get_tab(session, organization_id, tab_id)
    for field, value in payload.items():
        if value is not None and hasattr(tab, field):
            setattr(tab, field, value)
    if payload.get("state") == BrowserSessionState.WAITING_FOR_USER:
        from app.services import event_service

        await event_service.append_event(
            session,
            organization_id=organization_id,
            event_type="browser.waiting_for_user",
            payload={"tab_id": tab.id, "provider": tab.provider_slug},
        )
    await audit.record(
        session,
        action="tabs.update",
        actor_id=actor_id,
        organization_id=organization_id,
        target_type="browser_session",
        target_id=tab.id,
        context={"fields": sorted(payload)},
    )
    return tab


async def grant_tab_to_agent(
    session: AsyncSession, *, organization_id: str, actor_id: str, tab_id: str, agent_id: str
) -> BrowserSession:
    """An agent may only use a tab explicitly granted to it (SPEC Phase 2.3)."""
    tab = await get_tab(session, organization_id, tab_id)
    from app.services.agent_service import get_agent

    await get_agent(session, organization_id, agent_id)
    tab.granted_agent_id = agent_id
    await audit.record(
        session,
        action="tabs.grant",
        actor_id=actor_id,
        organization_id=organization_id,
        target_type="browser_session",
        target_id=tab.id,
        context={"agent_id": agent_id},
    )
    return tab


async def create_adapter(
    session: AsyncSession,
    *,
    organization_id: str,
    actor_id: str,
    provider_slug: str,
    yaml_body: str,
    notes: str | None = None,
) -> Adapter:
    from app.services.adapter_service import validate_adapter_yaml

    document = validate_adapter_yaml(yaml_body)
    current_max = await session.scalar(
        select(Adapter.version)
        .where(Adapter.organization_id == organization_id, Adapter.provider_slug == provider_slug)
        .order_by(Adapter.version.desc())
        .limit(1)
    )
    adapter = Adapter(
        organization_id=organization_id,
        provider_slug=provider_slug,
        version=int(current_max or 0) + 1,
        yaml_body=yaml_body,
        notes=notes,
        is_active=True,
    )
    # Only one active version per provider.
    for row in (
        await session.scalars(
            select(Adapter).where(
                Adapter.organization_id == organization_id,
                Adapter.provider_slug == provider_slug,
            )
        )
    ).all():
        row.is_active = False
    session.add(adapter)
    await session.flush()
    await audit.record(
        session,
        action="adapters.create",
        actor_id=actor_id,
        organization_id=organization_id,
        target_type="adapter",
        target_id=adapter.id,
        context={
            "provider_slug": provider_slug,
            "version": adapter.version,
            "keys": sorted(document),
        },
    )
    return adapter


async def list_adapters(
    session: AsyncSession, organization_id: str, provider_slug: str | None = None
) -> list[Adapter]:
    conditions = [Adapter.organization_id == organization_id]
    if provider_slug:
        conditions.append(Adapter.provider_slug == provider_slug)
    return list(
        (
            await session.scalars(
                select(Adapter)
                .where(*conditions)
                .order_by(Adapter.provider_slug, Adapter.version.desc())
            )
        ).all()
    )


async def get_active_adapter(
    session: AsyncSession, organization_id: str, provider_slug: str
) -> Adapter:
    row = await session.scalar(
        select(Adapter).where(
            Adapter.organization_id == organization_id,
            Adapter.provider_slug == provider_slug,
            Adapter.is_active.is_(True),
        )
    )
    if row is None:
        raise NotFoundError(
            "No active adapter for this provider", details={"provider_slug": provider_slug}
        )
    return row


async def rollback_adapter(
    session: AsyncSession, *, organization_id: str, actor_id: str, adapter_id: str
) -> Adapter:
    """Re-activate a previous adapter version (SPEC §13.3 rollback)."""
    target = await session.get(Adapter, adapter_id)
    if target is None or target.organization_id != organization_id:
        raise NotFoundError("Adapter not found")
    for row in (
        await session.scalars(
            select(Adapter).where(
                Adapter.organization_id == organization_id,
                Adapter.provider_slug == target.provider_slug,
            )
        )
    ).all():
        row.is_active = row.id == target.id
    await audit.record(
        session,
        action="adapters.rollback",
        actor_id=actor_id,
        organization_id=organization_id,
        target_type="adapter",
        target_id=target.id,
        context={"version": target.version},
    )
    return target


def capability_status(connection: ProviderConnection, capability: str) -> str:
    """Read one honest capability value; never invent one."""
    value = (connection.capabilities or {}).get(capability)
    if value is None:
        return RuntimeKind.NOT_VERIFIED.value
    return str(value)


def assert_not_raw_secret(value: str) -> None:
    """Guard used before persisting anything credential-shaped."""
    validate_credential_ref(value)
