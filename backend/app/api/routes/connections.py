"""Connection Manager: providers, credentials, connections, devices, tabs, adapters."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from backend.app.auth.dependencies import AppSettings, CurrentAuth, CurrentSession, require
from backend.app.schemas.common import OkResponse
from backend.app.schemas.connections import (
    AdapterCreate,
    AdapterOut,
    BrowserSessionOut,
    BrowserSessionUpdate,
    ConnectionCreate,
    ConnectionOut,
    ConnectionUpdate,
    CredentialCreate,
    CredentialOut,
    GrantSessionRequest,
    PairingRequest,
    PairingResponse,
    ProviderOut,
    SelectorTestRequest,
    SelectorTestResult,
    TermsAckOut,
)
from backend.app.services import adapter_service, connection_service

router = APIRouter(prefix="/connections", tags=["connections"])

providers_router = APIRouter(prefix="/providers", tags=["connections"])
credentials_router = APIRouter(prefix="/credentials", tags=["connections"])
devices_router = APIRouter(prefix="/devices", tags=["connections"])
tabs_router = APIRouter(prefix="/browser-sessions", tags=["connections"])
adapters_router = APIRouter(prefix="/adapters", tags=["connections"])


# --------------------------------------------------------------------------- #
# Providers
# --------------------------------------------------------------------------- #
@providers_router.get("", response_model=list[ProviderOut], summary="List providers")
async def list_providers(auth: CurrentAuth, session: CurrentSession) -> list[ProviderOut]:
    auth.require("connections:read")
    rows = await connection_service.list_providers(session, auth.organization_id)
    return [ProviderOut.model_validate(row) for row in rows]


@providers_router.post(
    "/sync-defaults",
    response_model=list[ProviderOut],
    summary="Ensure mock/generic/ollama/openai-compatible providers exist",
    dependencies=[Depends(require("connections:write"))],
)
async def sync_defaults(
    auth: CurrentAuth, session: CurrentSession, settings: AppSettings
) -> list[ProviderOut]:
    await connection_service.ensure_default_providers(session, auth.organization_id, settings)
    rows = await connection_service.list_providers(session, auth.organization_id)
    await session.commit()
    return [ProviderOut.model_validate(row) for row in rows]


# --------------------------------------------------------------------------- #
# Credentials
# --------------------------------------------------------------------------- #
@credentials_router.get(
    "", response_model=list[CredentialOut], summary="List credentials (no secrets)"
)
async def list_credentials(auth: CurrentAuth, session: CurrentSession) -> list[CredentialOut]:
    auth.require("connections:read")
    rows = await connection_service.list_credentials(session, auth.organization_id)
    return [CredentialOut.model_validate(row) for row in rows]


@credentials_router.post(
    "",
    response_model=CredentialOut,
    status_code=status.HTTP_201_CREATED,
    summary="Store an encrypted credential or an env: reference",
    dependencies=[Depends(require("connections:write"))],
)
async def create_credential(
    payload: CredentialCreate, auth: CurrentAuth, session: CurrentSession, settings: AppSettings
) -> CredentialOut:
    credential = await connection_service.create_credential(
        session,
        organization_id=auth.organization_id,
        actor_id=auth.user.id,
        settings=settings,
        name=payload.name,
        kind=payload.kind,
        value=payload.value,
    )
    await session.commit()
    return CredentialOut.model_validate(credential)


@credentials_router.delete(
    "/{credential_id}", response_model=OkResponse, summary="Delete a credential"
)
async def delete_credential(
    credential_id: str, auth: CurrentAuth, session: CurrentSession
) -> OkResponse:
    auth.require("connections:write")
    await connection_service.delete_credential(
        session,
        organization_id=auth.organization_id,
        actor_id=auth.user.id,
        credential_id=credential_id,
    )
    await session.commit()
    return OkResponse(message="Credential deleted")


# --------------------------------------------------------------------------- #
# Connections
# --------------------------------------------------------------------------- #
@router.get("", response_model=list[ConnectionOut], summary="List connections")
async def list_connections(auth: CurrentAuth, session: CurrentSession) -> list[ConnectionOut]:
    auth.require("connections:read")
    rows = await connection_service.list_connections(session, auth.organization_id)
    items = []
    for row in rows:
        payload = ConnectionOut.model_validate(row)
        payload.provider_slug = await connection_service.provider_slug_for(session, row)
        payload.terms_acknowledged = row.terms_acknowledged
        items.append(payload)
    return items


@router.post(
    "",
    response_model=ConnectionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a connection",
    dependencies=[Depends(require("connections:write"))],
)
async def create_connection(
    payload: ConnectionCreate, auth: CurrentAuth, session: CurrentSession
) -> ConnectionOut:
    connection = await connection_service.create_connection(
        session, organization_id=auth.organization_id, actor_id=auth.user.id, payload=payload
    )
    out = ConnectionOut.model_validate(connection)
    out.provider_slug = await connection_service.provider_slug_for(session, connection)
    out.terms_acknowledged = connection.terms_acknowledged
    await session.commit()
    return out


@router.patch("/{connection_id}", response_model=ConnectionOut, summary="Update a connection")
async def update_connection(
    connection_id: str, payload: ConnectionUpdate, auth: CurrentAuth, session: CurrentSession
) -> ConnectionOut:
    auth.require("connections:write")
    connection = await connection_service.update_connection(
        session,
        organization_id=auth.organization_id,
        actor_id=auth.user.id,
        connection_id=connection_id,
        payload=payload,
    )
    out = ConnectionOut.model_validate(connection)
    out.provider_slug = await connection_service.provider_slug_for(session, connection)
    out.terms_acknowledged = connection.terms_acknowledged
    await session.commit()
    return out


@router.post(
    "/{connection_id}/terms-acknowledgement",
    response_model=TermsAckOut,
    summary="Record the one-time terms notice acknowledgement",
)
async def acknowledge_terms(
    connection_id: str, auth: CurrentAuth, session: CurrentSession
) -> TermsAckOut:
    auth.require("connections:write")
    connection = await connection_service.acknowledge_terms(
        session,
        organization_id=auth.organization_id,
        actor_id=auth.user.id,
        connection_id=connection_id,
    )
    await session.commit()
    return TermsAckOut(
        connection_id=connection.id,
        acknowledged=connection.terms_acknowledged,
        acknowledged_at=connection.terms_acknowledged_at,
        acknowledged_by=connection.terms_acknowledged_by,
        notice=connection_service.TERMS_NOTICE,
    )


# --------------------------------------------------------------------------- #
# Devices
# --------------------------------------------------------------------------- #
@devices_router.post(
    "/pair",
    response_model=PairingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Pair a browser; the credential is returned exactly once",
    dependencies=[Depends(require("bridges:write"))],
)
async def pair_device(
    payload: PairingRequest, auth: CurrentAuth, session: CurrentSession
) -> PairingResponse:
    device, credential = await connection_service.pair_device(
        session,
        organization_id=auth.organization_id,
        actor_id=auth.user.id,
        label=payload.label,
        userscript_version=payload.userscript_version,
    )
    await session.commit()
    return PairingResponse(device_id=device.id, credential=credential)


@devices_router.get("", response_model=list[dict], summary="List paired devices (no credentials)")
async def list_devices(auth: CurrentAuth, session: CurrentSession) -> list[dict]:
    auth.require("connections:read")
    rows = await connection_service.list_devices(session, auth.organization_id)
    return [
        {
            "id": row.id,
            "label": row.label,
            "userscript_version": row.userscript_version,
            "revoked": row.revoked_at is not None,
            "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@devices_router.post("/{device_id}/revoke", response_model=OkResponse, summary="Revoke a device")
async def revoke_device(device_id: str, auth: CurrentAuth, session: CurrentSession) -> OkResponse:
    auth.require("bridges:write")
    await connection_service.revoke_device(
        session, organization_id=auth.organization_id, actor_id=auth.user.id, device_id=device_id
    )
    await session.commit()
    return OkResponse(message="Device revoked; its socket closes immediately")


@devices_router.post(
    "/{device_id}/tabs",
    response_model=BrowserSessionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Register a tab under a paired device",
    dependencies=[Depends(require("tabs:write"))],
)
async def register_tab(
    device_id: str,
    auth: CurrentAuth,
    session: CurrentSession,
    provider_slug: Annotated[str, Query(min_length=1, max_length=80)],
    url: str | None = Query(default=None, max_length=600),
    title: str | None = Query(default=None, max_length=300),
) -> BrowserSessionOut:
    tab = await connection_service.register_tab(
        session,
        organization_id=auth.organization_id,
        actor_id=auth.user.id,
        device_id=device_id,
        provider_slug=provider_slug,
        url=url,
        title=title,
    )
    await session.commit()
    return BrowserSessionOut.model_validate(tab)


# --------------------------------------------------------------------------- #
# Browser sessions (tabs)
# --------------------------------------------------------------------------- #
@tabs_router.get("", response_model=list[BrowserSessionOut], summary="List browser tabs")
async def list_tabs(auth: CurrentAuth, session: CurrentSession) -> list[BrowserSessionOut]:
    auth.require("connections:read")
    rows = await connection_service.list_tabs(session, auth.organization_id)
    return [BrowserSessionOut.model_validate(row) for row in rows]


@tabs_router.patch("/{tab_id}", response_model=BrowserSessionOut, summary="Update tab state")
async def update_tab(
    tab_id: str, payload: BrowserSessionUpdate, auth: CurrentAuth, session: CurrentSession
) -> BrowserSessionOut:
    auth.require("tabs:write")
    tab = await connection_service.update_tab(
        session,
        organization_id=auth.organization_id,
        actor_id=auth.user.id,
        tab_id=tab_id,
        payload=payload.model_dump(exclude_unset=True, exclude_none=True),
    )
    await session.commit()
    return BrowserSessionOut.model_validate(tab)


@tabs_router.post(
    "/{tab_id}/grant", response_model=BrowserSessionOut, summary="Grant a tab to an agent"
)
async def grant_tab(
    tab_id: str, payload: GrantSessionRequest, auth: CurrentAuth, session: CurrentSession
) -> BrowserSessionOut:
    auth.require("tabs:write")
    tab = await connection_service.grant_tab_to_agent(
        session,
        organization_id=auth.organization_id,
        actor_id=auth.user.id,
        tab_id=tab_id,
        agent_id=payload.agent_id,
    )
    await session.commit()
    return BrowserSessionOut.model_validate(tab)


# --------------------------------------------------------------------------- #
# Adapters
# --------------------------------------------------------------------------- #
@adapters_router.get("", response_model=list[AdapterOut], summary="List adapter versions")
async def list_adapters(
    auth: CurrentAuth,
    session: CurrentSession,
    provider_slug: str | None = Query(default=None, max_length=80),
) -> list[AdapterOut]:
    auth.require("connections:read")
    rows = await connection_service.list_adapters(session, auth.organization_id, provider_slug)
    return [AdapterOut.model_validate(row) for row in rows]


@adapters_router.post(
    "",
    response_model=AdapterOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a validated adapter version (YAML as data)",
    dependencies=[Depends(require("adapters:write"))],
)
async def create_adapter(
    payload: AdapterCreate, auth: CurrentAuth, session: CurrentSession
) -> AdapterOut:
    adapter = await connection_service.create_adapter(
        session,
        organization_id=auth.organization_id,
        actor_id=auth.user.id,
        provider_slug=payload.provider_slug,
        yaml_body=payload.yaml_body,
        notes=payload.notes,
    )
    await session.commit()
    return AdapterOut.model_validate(adapter)


@adapters_router.post(
    "/selector-test",
    response_model=SelectorTestResult,
    summary="Validate an adapter and check selectors",
)
async def selector_test(payload: SelectorTestRequest, auth: CurrentAuth) -> SelectorTestResult:
    """Never claims a selector passed without a page snapshot from the bridge."""
    auth.require("adapters:write")
    document = adapter_service.validate_adapter_yaml(payload.yaml_body)
    return adapter_service.run_selector_test(document)


@adapters_router.post(
    "/{adapter_id}/rollback", response_model=AdapterOut, summary="Re-activate an adapter version"
)
async def rollback_adapter(
    adapter_id: str, auth: CurrentAuth, session: CurrentSession
) -> AdapterOut:
    auth.require("adapters:write")
    adapter = await connection_service.rollback_adapter(
        session,
        organization_id=auth.organization_id,
        actor_id=auth.user.id,
        adapter_id=adapter_id,
    )
    await session.commit()
    return AdapterOut.model_validate(adapter)


@adapters_router.get(
    "/active/{provider_slug}",
    response_model=AdapterOut,
    summary="The active adapter for a provider",
)
async def active_adapter(
    provider_slug: str, auth: CurrentAuth, session: CurrentSession
) -> AdapterOut:
    auth.require("connections:read")
    adapter = await connection_service.get_active_adapter(
        session, auth.organization_id, provider_slug
    )
    return AdapterOut.model_validate(adapter)
