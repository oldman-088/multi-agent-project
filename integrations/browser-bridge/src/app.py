"""Local Browser Bridge.

- Binds 127.0.0.1 only (enforced in main()).
- /ws/userscript: userscript WebSocket. Origin is checked on every handshake; a paired
  device credential is required after a one-time pairing code.
- /api/...: local HTTP API for the AATM/NEXUS backend. Requires a bearer token from the
  BRIDGE_API_TOKEN environment variable. Without that variable the API answers 503.

The wire protocol is documented in docs/PROTOCOL.md.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from pairing import DeviceStatus, PairingStore, digest
from protocol import (
    HELLO_TIMEOUT_S,
    MAX_FRAME_CHARS,
    MIN_SCRIPT_VERSION,
    PROTOCOL_VERSION,
    CloseCode,
    DeltaMessage,
    HeartbeatMessage,
    HelloMessage,
    RequestIn,
    ResultMessage,
    SessionState,
    TabStateMessage,
)
from pydantic import BaseModel, ValidationError
from sessions import Connection, RequestNotFound, SessionRegistry, TabNotFound

log = logging.getLogger("browser_bridge")

BRIDGE_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


class _BadMessage(Exception):
    pass


@dataclass(frozen=True)
class BridgeSettings:
    api_token_digest: str | None
    allowed_origins: frozenset[str]
    port: int = DEFAULT_PORT

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> BridgeSettings:
        token = env.get("BRIDGE_API_TOKEN", "").strip()
        if token and len(token) < 32:
            raise ValueError("BRIDGE_API_TOKEN must be at least 32 characters")
        origins: set[str] = set()
        for raw in env.get("BRIDGE_ALLOWED_ORIGINS", "").split(","):
            if not raw.strip():
                continue
            origin = normalize_origin(raw)
            if not origin.startswith(("http://", "https://")) or origin.count("/") != 2:
                raise ValueError(
                    f"invalid origin in BRIDGE_ALLOWED_ORIGINS: {origin!r}"
                )
            origins.add(origin)
        port = int(env.get("BRIDGE_PORT", str(DEFAULT_PORT)))
        if not 1024 <= port <= 65535:
            raise ValueError("BRIDGE_PORT must be between 1024 and 65535")
        return cls(
            api_token_digest=digest(token) if token else None,
            allowed_origins=frozenset(origins),
            port=port,
        )


def normalize_origin(value: str) -> str:
    return value.strip().rstrip("/").lower()


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


# ----- response models ------------------------------------------------------


class PairingCodeOut(BaseModel):
    code: str
    expires_in_s: int


class DeviceOut(BaseModel):
    device_id: str
    name: str
    revoked: bool
    connected: bool


class TabOut(BaseModel):
    tab_id: str
    device_id: str
    state: SessionState
    agent_state: str | None
    pending: int


class RequestOut(BaseModel):
    request_id: str
    status: str
    text: str
    error_code: str | None
    queue_position: int


# ----- app factory ----------------------------------------------------------


def create_app(
    settings: BridgeSettings,
    *,
    pairing: PairingStore | None = None,
    registry: SessionRegistry | None = None,
) -> FastAPI:
    store = pairing or PairingStore()
    sessions = registry or SessionRegistry()
    app = FastAPI(
        title="NEXUS Local Browser Bridge",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    def require_api_token(request: Request) -> None:
        expected = settings.api_token_digest
        if expected is None:
            raise HTTPException(
                status_code=503, detail="bridge API token is not configured"
            )
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise HTTPException(status_code=401, detail="missing bearer token")
        if not hmac.compare_digest(digest(token.strip()), expected):
            raise HTTPException(status_code=403, detail="invalid bearer token")

    auth = [Depends(require_api_token)]

    @app.get("/health")
    async def health() -> dict[str, object]:
        return {"status": "ok", "protocol_version": PROTOCOL_VERSION}

    @app.post("/api/pairing-codes", response_model=PairingCodeOut, dependencies=auth)
    async def create_pairing_code() -> PairingCodeOut:
        code, ttl = store.create_code()
        return PairingCodeOut(code=code, expires_in_s=int(ttl))

    @app.get("/api/devices", response_model=list[DeviceOut], dependencies=auth)
    async def list_devices() -> list[DeviceOut]:
        return [
            DeviceOut(
                device_id=d.device_id,
                name=d.name,
                revoked=d.revoked,
                connected=sessions.is_connected(d.device_id),
            )
            for d in store.devices()
        ]

    @app.post("/api/devices/{device_id}/revoke", dependencies=auth)
    async def revoke_device(device_id: str) -> dict[str, bool]:
        if not store.revoke(device_id):
            raise HTTPException(status_code=404, detail="unknown device")
        await sessions.revoke_device(device_id)
        return {"revoked": True}

    @app.get("/api/tabs", response_model=list[TabOut], dependencies=auth)
    async def list_tabs() -> list[TabOut]:
        return [
            TabOut(
                tab_id=t.tab_id,
                device_id=t.device_id,
                state=t.state,
                agent_state=t.agent_state,
                pending=t.pending,
            )
            for t in sessions.list_tabs()
        ]

    def _out(req: Any) -> RequestOut:
        return RequestOut(
            request_id=req.request_id,
            status=req.status.value,
            text=req.text,
            error_code=req.error_code,
            queue_position=req.queue_position,
        )

    @app.post(
        "/api/tabs/{tab_id}/requests",
        response_model=RequestOut,
        status_code=202,
        dependencies=auth,
    )
    async def send_request(tab_id: str, body: RequestIn) -> RequestOut:
        try:
            req = sessions.enqueue(
                tab_id, body.prompt, body.idempotency_key, body.timeout_s
            )
        except TabNotFound as exc:
            raise HTTPException(status_code=404, detail="unknown tab") from exc
        return _out(req)

    @app.get(
        "/api/tabs/{tab_id}/requests/{request_id}",
        response_model=RequestOut,
        dependencies=auth,
    )
    async def get_request(tab_id: str, request_id: str) -> RequestOut:
        try:
            return _out(sessions.get_request(tab_id, request_id))
        except RequestNotFound as exc:
            raise HTTPException(status_code=404, detail="unknown request") from exc

    @app.post(
        "/api/tabs/{tab_id}/requests/{request_id}/cancel",
        response_model=RequestOut,
        dependencies=auth,
    )
    async def cancel_request(tab_id: str, request_id: str) -> RequestOut:
        try:
            req = await sessions.cancel(tab_id, request_id)
        except RequestNotFound as exc:
            raise HTTPException(status_code=404, detail="unknown request") from exc
        return _out(req)

    @app.websocket("/ws/userscript")
    async def userscript_socket(ws: WebSocket) -> None:
        await ws.accept()  # accept first so that the close code reaches the client
        origin = normalize_origin(ws.headers.get("origin", ""))
        if not origin or origin not in settings.allowed_origins:
            log.warning("ws.origin_refused origin_len=%d", len(origin))
            await ws.close(code=CloseCode.ORIGIN_REFUSED)
            return

        try:
            raw = await _receive_json(ws, timeout=HELLO_TIMEOUT_S)
            hello = HelloMessage.model_validate(raw)
        except TimeoutError:
            await ws.close(code=CloseCode.HELLO_TIMEOUT)
            return
        except (_BadMessage, ValidationError):
            await ws.close(code=CloseCode.BAD_MESSAGE)
            return
        except WebSocketDisconnect:
            return

        version = _version(hello.script_version)
        if version < MIN_SCRIPT_VERSION:
            await ws.close(code=CloseCode.SCRIPT_TOO_OLD)
            return

        if hello.pairing_code is not None:
            if not store.consume_code(hello.pairing_code):
                await ws.close(code=CloseCode.BAD_PAIRING_CODE)
                return
            device_id, credential = store.issue_device(hello.device_name)
            await ws.send_json(
                {"type": "paired", "device_id": device_id, "credential": credential}
            )
            log.info("device.paired device=%s", device_id)
        elif hello.device_id and hello.credential:
            status = store.verify(hello.device_id, hello.credential)
            if status is not DeviceStatus.OK:
                close_for = {
                    DeviceStatus.UNKNOWN: CloseCode.NOT_REGISTERED,
                    DeviceStatus.BAD_CREDENTIAL: CloseCode.BAD_CREDENTIAL,
                    DeviceStatus.REVOKED: CloseCode.REVOKED,
                }[status]
                await ws.close(code=close_for)
                return
            device_id = hello.device_id
        else:
            await ws.send_json({"type": "pairing_required"})
            await ws.close(code=CloseCode.NOT_REGISTERED)
            return

        conn = Connection(
            device_id=device_id,
            script_version=version,
            send_fn=ws.send_json,
            close_fn=lambda code: ws.close(code=code),
        )
        await sessions.attach(conn)
        try:
            await conn.send(
                {
                    "type": "welcome",
                    "protocol_version": PROTOCOL_VERSION,
                    "device_id": device_id,
                    "session_state": SessionState.AUTHENTICATED.value,
                }
            )
            while True:
                try:
                    data = await _receive_json(ws)
                except _BadMessage:
                    await ws.close(code=CloseCode.BAD_MESSAGE)
                    return
                await _dispatch(conn, data)
        except WebSocketDisconnect:
            pass
        finally:
            await sessions.detach(conn)

    async def _dispatch(conn: Connection, data: dict[str, Any]) -> None:
        kind = data.get("type")
        try:
            if kind == "heartbeat":
                HeartbeatMessage.model_validate(data)
                await conn.send({"type": "heartbeat_ack"})
            elif kind == "tab_state":
                msg = TabStateMessage.model_validate(data)
                await sessions.update_tab(
                    conn.device_id, msg.tab_id, msg.state, msg.agent_state
                )
            elif kind == "delta":
                msg_d = DeltaMessage.model_validate(data)
                sessions.handle_delta(conn.device_id, msg_d.request_id, msg_d.text)
            elif kind == "result":
                msg_r = ResultMessage.model_validate(data)
                await sessions.handle_result(
                    conn.device_id,
                    msg_r.request_id,
                    msg_r.status,
                    msg_r.text,
                    msg_r.error_code,
                )
            else:
                await conn.send({"type": "error", "code": "UNKNOWN_TYPE"})
        except ValidationError:
            await conn.send({"type": "error", "code": "BAD_MESSAGE"})

    return app


async def _receive_json(ws: WebSocket, timeout: float | None = None) -> dict[str, Any]:
    receive = ws.receive()
    message = await (
        asyncio.wait_for(receive, timeout) if timeout is not None else receive
    )
    if message["type"] == "websocket.disconnect":
        raise WebSocketDisconnect(code=int(message.get("code", 1000)))
    text = message.get("text")
    if not isinstance(text, str) or len(text) > MAX_FRAME_CHARS:
        raise _BadMessage
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _BadMessage from exc
    if not isinstance(data, dict):
        raise _BadMessage
    return data


def main() -> None:  # pragma: no cover - process entry point
    import uvicorn

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    settings = BridgeSettings.from_env(os.environ)
    if settings.api_token_digest is None:
        log.warning("BRIDGE_API_TOKEN is not set: the local API will answer 503")
    # The host is fixed. The bridge never listens on other interfaces.
    uvicorn.run(
        create_app(settings), host=BRIDGE_HOST, port=settings.port, log_level="warning"
    )


if __name__ == "__main__":  # pragma: no cover
    main()
